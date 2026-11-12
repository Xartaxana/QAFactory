#!/usr/bin/env python3
"""k1 k5: a part of test_story_run_freshness.py, split by tools/test_split.py (TD-11c). The shared helpers are in story_run_freshness_common."""
import contextlib
import io
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402
from story_run_common import driver_for, human_broken, run_scenarios
import human_text  # noqa: E402
from story_run_freshness_common import (  # noqa: E402
    KEY, UTC, adapter_calls, asked_driver, edit_requirements, entered, events, fixed_adapter,
    freshness_project, looked, make_due, now_whole, person_of, record, set_checked, spy_stdout,
)


def edit_comments(ticket_file: Path) -> None:
    ticket_file.write_text(ticket_file.read_text(encoding="utf-8") + "- **qa** (2026-09-12): one more comment.\n", encoding="utf-8")


def snap_bytes(task_root: Path) -> bytes:
    return (task_root / "work" / "ticket-snapshot.json").read_bytes()


# --- K1 the window, the call --------------------------------------------------------------------------------------
def k1_the_window_at_and_beyond() -> None:
    root, task_root, env, _ticket = freshness_project()
    try:
        t0 = now_whole() - timedelta(hours=1)
        set_checked(task_root, t0, result="none")
        driver = driver_for(root, env, KEY)
        calls = spy_stdout(driver)
        got, printed = looked(driver, now=t0 + timedelta(hours=6))
        check_eq("K1: exactly 6 h after the last check: skipped, no subprocess, no print", (got, len(calls), printed), ("skipped", 0, ""))
        got, printed = looked(driver, now=t0 + timedelta(hours=6, seconds=1))
        said = adapter_calls(calls)
        check_eq("K1: 6 h and a second: the adapter runs once", (got, len(said)), ("none", 1))
        script, args, kwargs = said[0]
        check_eq("K1: the call is `freshness <task> --task-root <root> --json`, no --ticket-file on a tracker story",
                 (args[:3], Path(args[3]).resolve(), args[4:]), (("freshness", KEY, "--task-root"), task_root.resolve(), ("--json",)))
        check_eq("K1: with the 300 s ceiling, and the adapter's stderr not echoed twice", (kwargs.get("timeout"), kwargs.get("echo")), (300, False))
        check_eq("K1: nothing is printed for `none`", printed, "")
        check("K1: the adapter stamped the check (the trigger is measured from it)",
              abs((datetime.now(UTC) - datetime.fromisoformat(record(task_root)["checked_at"])).total_seconds()) < 120)
        # a story past the window is never resumed without a look; one inside it is never re-read
        calls.clear()
        got, _ = looked(driver)
        check_eq("K1: right after the look it is not due again: no second read", (got, len(calls)), ("skipped", 0))
    finally:
        harness.cleanup(root)


# --- K2-K4 what the adapter finds -----------------------------------------------------------------------------------
def k2_k3_none_and_context() -> None:
    root, task_root, env, ticket = freshness_project()
    try:
        driver = driver_for(root, env, KEY)
        before = snap_bytes(task_root)
        make_due(task_root)
        got, printed = looked(driver)
        check_eq("K2: an unchanged ticket: `none`, silent, the baseline is not rewritten", (got, printed, snap_bytes(task_root) == before), ("none", "", True))
        edit_comments(ticket)
        make_due(task_root)
        got, printed = looked(driver)
        check_eq("K3: a new comment is `context`", got, "context")
        check_in("K3: one line, in words: what changed, and that the story goes on",
                 f"ticket {KEY} changed while the story waited (the comments); the story goes on", printed)
        check("K3: the baseline was replaced (nothing is re-planned)", snap_bytes(task_root) != before)
        check_eq("K3: and no question is open", driver.state.get("asked"), {})
    finally:
        harness.cleanup(root)


def k4_requirements_is_the_persons_question() -> None:
    root, task_root, env, ticket = freshness_project()
    try:
        before = snap_bytes(task_root)
        edit_requirements(ticket)
        make_due(task_root)
        driver = driver_for(root, env, KEY)
        got, _ = looked(driver)
        person = person_of(got)
        check("K4: requirements -> a Person", person is not None, repr(got))
        check_eq("K4: kind and stage", (person.kind, person.stage), ("ticket_changed", "S0"))
        check_eq("K4: the question breaks no rule of human-questions.md (with the answer block `ask()` adds)",
                 human_broken(person.text), [])
        check_in("K4: it says what changed, in words", "the acceptance criteria", person.text)
        check_in("K4: it says the old text is kept and the new one set aside", "kept the text the story was built on and set the new text aside", person.text)
        check_in("K4: it quotes the three answers, word for word", "re-run S2–S3 against the new text · continue on the old text with that stated as a known gap · stop here.", person.text)
        check("K4: and ends with the priced section: the tokens it reads as option lines, and what the first line means",
              all(f"`{t}` — " in person.text.split("## What each answer costs and does")[1] for t in ("new text", "old text", "stop"))
              and "anything you write after the first line is kept with your answer for gate B" in person.text, person.text[-600:])
        check_eq("K4: every option has its three price lines (item 6)", human_text.price_problems(person.text, None), [])
        check_not_in("K4: no path and no command in the body", "ticket-snapshot", person.text)
        details = json.loads(person.details)
        check("K4: the details hold the fields the adapter named", "acceptance_criteria" in details["changed"] and "detail" in details and "revisions" in details, person.details[:200])
        check_eq("K4: the baseline's bytes are unchanged", snap_bytes(task_root), before)
        check("K4: and the new text waits beside it", (task_root / "work" / "ticket-snapshot.next.json").is_file())
        check_eq("K4: exactly one `ticket_changed` event is journaled (by the adapter)", len(events(root, "ticket_changed")), 1)
        # the same text again, with nobody having answered: still the question, and still ONE event
        again, _ = looked(driver, now=datetime.now(UTC) + timedelta(hours=7))
        check_eq("K4: asked again from a due look: the same question, no second event", (person_of(again) is not None, len(events(root, "ticket_changed"))), (True, 1))
    finally:
        harness.cleanup(root)


# --- K5 old text ----------------------------------------------------------------------------------------------------
def k5_old_text() -> None:
    root, task_root, env, ticket = freshness_project()
    try:
        driver, person = asked_driver(root, env, task_root, ticket)
        words = "old text\nthe criterion on tag limits is a typo fix, the plan stands"
        with contextlib.redirect_stdout(io.StringIO()):
            driver.take_ticket_answer(words, "# q\n", "S0", "")
        pipeline = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))
        remarks = pipeline.get("remarks") or []
        check("K5: the WHOLE answer is kept as a remark of S0", any(r.get("stage") == "S0" and "typo fix, the plan stands" in str(r) for r in remarks), json.dumps(remarks)[:300])
        check("K5: the declined mark is recorded", bool((record(task_root).get("declined") or {}).get("hash")))
        files = sorted((task_root / "state" / "words").glob("driver-ticketdecline-*.txt"))
        check_eq("K5: the words went to the adapter by file, whole", [f.read_text(encoding="utf-8") for f in files], [words])
        check("K5: the waiting text stays beside the baseline", (task_root / "work" / "ticket-snapshot.next.json").is_file())
        check_eq("K5: no rework is owed", driver.state.get("ticket_rework"), None)
        make_due(task_root)
        got, printed = looked(driver)
        check_eq("K5: the next due check says it is the declined text and goes on (not asked again)", got, "declined")
        check_in("K5: in one line with the date", "is the one declined on", printed)
        check_eq("K5: and journals no second `ticket_changed` event", len(events(root, "ticket_changed")), 1 + 1)   # the question's, then the adapter's `declined:` decision
    finally:
        harness.cleanup(root)


def k4b_an_unreadable_file_with_the_question_open_never_crashes() -> None:
    """F1: `ticket_field_words([])` used to raise IndexError, so with the baseline or the waiting text unreadable the open
    question crashed every run and every answer, with no door. The question is asked again, whatever the answer."""
    import story_run
    check_eq("F1: no names, no words (the callers say their own fallback)", (story_run.Driver.ticket_field_words([]), story_run.Driver.ticket_field_words(None)), ("", ""))
    for label, spoil in (("the waiting text", lambda task_root: (task_root / "work" / "ticket-snapshot.next.json").write_text("{ not json", encoding="utf-8")),
                         ("the baseline", lambda task_root: (task_root / "work" / "ticket-snapshot.json").write_text("{ not json", encoding="utf-8"))):
        root, task_root, env, ticket = freshness_project()
        try:
            asked_driver(root, env, task_root, ticket)
            spoil(task_root)
            got, _ = entered(driver_for(root, env, KEY))
            check(f"F1: {label} unreadable, question open: a run asks it again (no crash), saying nothing is named", person_of(got) is not None
                  and "something in the requirements" in got.text, repr(got))
            for words in ("stop", "maybe", "new text", "old text"):
                fresh = driver_for(root, env, KEY)
                try:
                    with contextlib.redirect_stdout(io.StringIO()):
                        fresh.take_ticket_answer(words, "# q\n", "S0", "")
                    outcome = "went on"
                except Exception as exc:
                    outcome = "asked again" if person_of(exc) is not None else repr(exc)
                check(f"F1: {label} unreadable, answer `{words}`: no crash (a Person, or the story goes on)", outcome in ("asked again", "went on"), outcome)
                if words in ("stop", "maybe"):
                    check_eq(f"F1: {label}, `{words}`: always asked again", outcome, "asked again")
        finally:
            harness.cleanup(root)
    root, task_root, env, _ticket = freshness_project()
    try:
        make_due(task_root)
        driver = driver_for(root, env, KEY)
        spy_stdout(driver, fixed_adapter(0, json.dumps({"result": "context", "changed": []})))
        got, printed = looked(driver)
        check_eq("F1: a `context` result naming no field is a line with a fallback, not a crash", (got, "(something)" in printed), ("context", True))
        spy_stdout(driver, fixed_adapter(0, json.dumps({"result": "requirements", "changed": [], "already_answered": True})))
        got, printed = looked(driver)
        check_eq("F1: an already-answered result naming no field: the same", (got, "(the requirements)" in printed), ("declined", True))
    finally:
        harness.cleanup(root)


SCENARIOS = [
    k1_the_window_at_and_beyond,
    k2_k3_none_and_context,
    k4_requirements_is_the_persons_question,
    k4b_an_unreadable_file_with_the_question_open_never_crashes,
    k5_old_text,
]


def main() -> None:
    """No argument: every scenario. Names (prefixes, `k7c k10`): only those - the one a mutation of the driver is checked
    by (builder-rules 7a), with the same checks; an argument that names nothing is an error, never a silent green."""
    wanted = sys.argv[1:]
    chosen = [s for s in SCENARIOS if not wanted or any(s.__name__.startswith(prefix) for prefix in wanted)]
    if not chosen:
        sys.exit(f"test_story_run_freshness: no scenario starts with {wanted}; they are: " + ", ".join(s.__name__ for s in SCENARIOS))
    run_scenarios([], chosen)
    harness.finish("test_story_run_freshness_k1_k5")


# split: runner piece 1
if __name__ == "__main__":
    main()
