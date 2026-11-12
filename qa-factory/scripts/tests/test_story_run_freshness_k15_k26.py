#!/usr/bin/env python3
"""k15 k26: a part of test_story_run_freshness.py, split by tools/test_split.py (TD-11c). The shared helpers are in story_run_freshness_common."""
import contextlib
import io
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402
from story_run_common import FIXTURE_TICKET, d3_s8_done, driver_for, human_broken, run_scenarios, s0_answer, s0_project, s0_run, s0_state, seed
from story_run_freshness_common import (  # noqa: E402
    KEY, UTC, adapter, adapter_calls, answer_file, asked_driver, edit_requirements, entered, events,
    freshness_project, iso, looked, make_due, person_of, spy_stdout,
)


# --- K15-K20 the positions ------------------------------------------------------------------------------------------
def k15_positions_in_the_run() -> None:
    # (a) a fresh story: S0 runs in this process and the ticket is NOT looked at (K11 of the S0 file: no read, the hash is stable)
    root, task_root, env = s0_project(KEY)
    try:
        driver = driver_for(root, env, KEY, max_boundaries=0)
        entries = []
        driver.ticket_freshness_entry = lambda: entries.append("entry") or "x"
        with contextlib.redirect_stdout(io.StringIO()):
            driver.run()
        check_eq("K15: the process that wrote S0 never looks at the ticket", entries, [])
    finally:
        harness.cleanup(root)
    # (b), (c), (d) a resumed story
    root, task_root, env, ticket = freshness_project()
    try:
        order = []
        driver = driver_for(root, env, KEY, max_boundaries=0)
        real_entry, real_accept = driver.ticket_freshness_entry, driver.accept_no_trace
        driver.ticket_freshness_entry = lambda: order.append("freshness") or real_entry()
        driver.accept_no_trace = lambda: order.append("accept_no_trace") or real_accept()
        make_due(task_root)
        calls = spy_stdout(driver)
        with contextlib.redirect_stdout(io.StringIO()):
            driver.run()
        check_eq("K15: a resumed story is looked at ONCE, before `accept_no_trace` and the loop", (order, len(adapter_calls(calls))), (["freshness", "accept_no_trace"], 1))
        # another kind of question is open: never stacked
        make_due(task_root)
        edit_requirements(ticket)
        other = driver_for(root, env, KEY, max_boundaries=0)
        other.state["asked"] = {"kind": "halt", "stage": "S3", "dispatch": "S3-x-1"}
        other.question_path().write_text("# q\nkind: halt\nstage: S3\ndispatch: S3-x-1\n\nA role halted.\n", encoding="utf-8")
        calls = spy_stdout(other)
        with contextlib.redirect_stdout(io.StringIO()):
            code = other.run()
        check_eq("K15: another question is open: no look, no new question (the halt stays)", (adapter_calls(calls), other.state["asked"].get("kind"), code), ([], "halt", 0))
        # the person's answer to ANOTHER question is recorded before the look (FR-8)
        order = []
        stage_answer = driver_for(root, env, KEY, max_boundaries=0, answer=answer_file(root, "skip"))
        stage_answer.state["asked"] = {"kind": "retro", "stage": "S9", "dispatch": ""}
        stage_answer.question_path().write_text("# q\nkind: retro\n", encoding="utf-8")
        real_take, real_entry = stage_answer.take_answer, stage_answer.ticket_freshness_entry
        stage_answer.take_answer = lambda path: order.append("take_answer") or real_take(path)
        stage_answer.ticket_freshness_entry = lambda: order.append("freshness") or real_entry()
        with contextlib.redirect_stdout(io.StringIO()):
            stage_answer.run()
        check_eq("K15: the answer is recorded first, then the look", order, ["take_answer", "freshness"])
        check_eq("K15: and the look found the moved requirements: the question is open now", stage_answer.state["asked"].get("kind"), "ticket_changed")
    finally:
        harness.cleanup(root)


def k16_a_pasted_story_passes_its_file() -> None:
    root, task_root, env, _ticket = freshness_project()
    try:
        paste = root / "pasted.md"
        paste.write_text(FIXTURE_TICKET, encoding="utf-8")
        out, got = adapter(root, env, task_root, "--ticket-file", str(paste))
        check("setup: the pasted text is read and its look stamped", out.returncode == 0, out.stderr[-300:])
        make_due(task_root)
        driver = driver_for(root, env, KEY, ticket_file=str(paste))
        calls = spy_stdout(driver)
        got, _ = looked(driver)
        script, args, _kwargs = adapter_calls(calls)[0]
        check_eq("K16: exactly when the launch names a ticket file, `--ticket-file <it>` is on the call", (args[-2:], got), (("--ticket-file", str(paste)), "none"))
        paste.write_text(FIXTURE_TICKET.replace("at most 5 tags; a sixth tag", "at most 7 tags; an eighth tag"), encoding="utf-8")
        make_due(task_root)
        got, _ = looked(driver)
        person = person_of(got)
        check("K16: a changed pasted text is the same question, saying so in the story's words", person is not None and "The ticket text you gave me" in person.text, repr(got))
        check_not_in("K16: with no path in the body", "pasted.md", person.text)
        check_in("K16: the person's own file is named in the answer block", "pasted.md", person.answer_note)
        check_eq("K16: and it breaks no rule", human_broken(person.text), [])
    finally:
        harness.cleanup(root)


def k17_the_word_that_the_ticket_is_not_needed_outlives_s0() -> None:
    root, task_root, env = s0_project(KEY)
    try:
        tickets = root / "tickets"
        text = (tickets / f"{KEY}.md").read_text(encoding="utf-8")
        (tickets / f"{KEY}.md").unlink()
        out = s0_run(root, env, KEY)
        check_eq("K17: the ticket cannot be read: the `ticket_read` question", (out.returncode, s0_state(task_root).get("s0_block")), (3, "ticket_read"))
        # a snapshot appears (the person put the text in place), and the person answers `not needed`: S0 goes on with it
        (tickets / f"{KEY}.md").write_text(text, encoding="utf-8")
        got = harness.run_script("ticket_adapter.py", "get", KEY, "--json", "--output", str(task_root / "work" / "ticket-snapshot.json"), cwd=root, env=env)
        check_eq("setup: the snapshot is on disk", got.returncode, 0)
        out = s0_answer(root, env, KEY, "not needed")
        state = s0_state(task_root)
        check_eq("K17: S0 finished", (out.returncode, (task_root / "pipeline.json").is_file()), (0, True))
        check_eq("K17: `launch.ticket_not_needed` was written before `s0_answers` was popped", ((state.get("launch") or {}).get("ticket_not_needed"), "s0_answers" in state), (True, False))
        # the next process: due, and the check is skipped on the word, with one line
        (task_root / "work" / "ticket-freshness.json").write_text(json.dumps({"checked_at": iso(datetime.now(UTC) - timedelta(hours=9)), "result": "none"}), encoding="utf-8")
        driver = driver_for(root, env, KEY)
        calls = spy_stdout(driver)
        word, printed = entered(driver)
        check_eq("K17: a due check is not run on the person's word, and one line says why", (word, adapter_calls(calls), "you said the ticket is not needed" in printed), ("not_needed", [], True))
        # control: the same story without the flag IS looked at
        driver.state["launch"].pop("ticket_not_needed")
        word, _ = entered(driver)
        check_eq("K17 control: without the word the same due story is looked at", (word, len(adapter_calls(calls))), ("none", 1))
    finally:
        harness.cleanup(root)


def k18_no_controller_means_no_look() -> None:
    root, task_root, env, ticket = freshness_project()
    try:
        make_due(task_root)
        edit_requirements(ticket)
        (task_root / "state" / "controller.json").unlink()
        driver = driver_for(root, env, KEY)
        calls = spy_stdout(driver)
        word, printed = entered(driver)
        check_eq("K18: no state/controller.json: no look, silent (`initialize` hashes the S0 snapshot first)", (word, adapter_calls(calls), printed), ("no_controller", [], ""))
        check("K18: and the snapshot is exactly the one the story was built on", not (task_root / "work" / "ticket-snapshot.next.json").is_file())
    finally:
        harness.cleanup(root)


def k19_a_closed_story_is_not_looked_at() -> None:
    root, task_root, env, ticket = freshness_project()
    try:
        make_due(task_root)
        edit_requirements(ticket)
        d3_s8_done(task_root)
        path = task_root / "pipeline.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["gates"] = {"B": {"decision": "approved", "status": "approved"}}
        path.write_text(json.dumps(data), encoding="utf-8")
        driver = driver_for(root, env, KEY)
        calls = spy_stdout(driver)
        word, printed = entered(driver)
        check_eq("K19: a closed story (gate B decided, S8 done) is not looked at, one line says so", (word, adapter_calls(calls), "this story is closed" in printed), ("closed", [], True))
    finally:
        harness.cleanup(root)


def k20_gate_b_is_checked_before_it_is_asked() -> None:
    root, task_root, env, _ticket = freshness_project()
    try:
        for gate, expected in (("B", ["freshness", "gate_repair"]), ("A", ["gate_repair"])):
            driver = driver_for(root, env, KEY)
            order = []
            driver.ticket_freshness_entry = lambda: order.append("freshness") or "none"
            driver.gate_repair = lambda g: order.append("gate_repair") or {"ran": True, "top": ""}
            driver.dispatch_action({"action": "await_gate", "gate": gate})
            check_eq(f"K20: gate {gate}: the order", order, expected)
        # M4: an open question of another kind (the gate's own, asked and unanswered) means the entry holds
        driver = driver_for(root, env, KEY)
        driver.state["asked"] = {"kind": "gate_B", "stage": "S8", "dispatch": ""}
        calls = spy_stdout(driver)
        make_due(task_root)
        word, _ = entered(driver)
        check_eq("K20 (M4): while a question is open the pre-check holds: no read, the open question is not replaced", (word, adapter_calls(calls), driver.state["asked"]["kind"]), ("held", [], "gate_B"))
    finally:
        harness.cleanup(root)


# --- K21-K26 the rest of the keys ------------------------------------------------------------------------------------
def k21_the_options_constant_is_in_s0_md() -> None:
    import story_run
    text = (harness.PLUGIN_ROOT / "skills" / "qa-story" / "phases" / "s0.md").read_text(encoding="utf-8")
    line = next(l.strip() for l in text.splitlines() if l.strip().startswith("> re-run"))
    check_eq("K21: TICKET_CHANGED_OPTIONS is the quoted line of phases/s0.md section 2b, character for character", story_run.TICKET_CHANGED_OPTIONS, line[2:])
    check_eq("K21: the tokens the code reads", story_run.TICKET_CHANGED_TOKENS, ("new text", "old text", "stop"))
    check("K21: the prose names the same three tokens and the cause", all(w in text for w in ("`new text`, `old text` or\n`stop`", "--cause ticket_changed")))


def k22_no_baseline_the_ticket_as_it_stands_becomes_one() -> None:
    root, task_root, env = seed(KEY)
    try:
        tickets = root / "tickets"
        tickets.mkdir()
        (tickets / f"{KEY}.md").write_text(FIXTURE_TICKET, encoding="utf-8")
        config = root / "qa-factory" / "config.json"
        cfg = json.loads(config.read_text(encoding="utf-8"))
        cfg["adapters"] = {"ticket": {"kind": "file", "path": str(tickets)}}
        config.write_text(json.dumps(cfg), encoding="utf-8")
        (task_root / "work" / "ticket-freshness.json").unlink()          # no stamp, no baseline: an unknown age is not a fresh one
        driver = driver_for(root, env, KEY)
        got, printed = looked(driver)
        check_eq("K22: no baseline: `baseline_written`, one line", (got, "the story had none to compare with" in printed), ("baseline_written", True))
        check("K22: and the baseline is there now", (task_root / "work" / "ticket-snapshot.json").is_file())
        got, _ = looked(driver)
        check_eq("K22: and the story is checked: not due", got, "skipped")
    finally:
        harness.cleanup(root)


def k23_a_waiting_text_after_a_crash_is_asked_again() -> None:
    root, task_root, env, ticket = freshness_project()
    try:
        edit_requirements(ticket)
        make_due(task_root)
        driver = driver_for(root, env, KEY)
        looked(driver)                                                    # the look stamped `checked_at` and wrote `.next`; the process "crashed" before asking
        check("setup: the check is stamped just now and `.next` waits", (task_root / "work" / "ticket-snapshot.next.json").is_file())
        fresh = driver_for(root, env, KEY)
        got, _ = looked(fresh)
        check_eq("K23: a waiting text nobody answered is due whatever the stamp says: the question is asked", person_of(got) is not None, True)
        check_eq("K23: and the same text is journaled once", len(events(root, "ticket_changed")), 1)
    finally:
        harness.cleanup(root)


def k24_an_answer_after_the_text_stopped_waiting() -> None:
    root, task_root, env, ticket = freshness_project()
    try:
        driver, _ = asked_driver(root, env, task_root, ticket)
        (task_root / "work" / "ticket-snapshot.next.json").unlink()      # a later look settled it
        for token in ("new text", "old text"):
            printed = io.StringIO()
            before = len(events(root, "human_answer"))
            with contextlib.redirect_stdout(printed):
                driver.take_ticket_answer(token, "# q\n", "S0", "")
            check_eq(f"K24: `{token}` with nothing waiting: the adapter's refusal is printed, the story goes on, nothing is owed", ("nothing" in printed.getvalue(), driver.state.get("ticket_rework")), (True, None))
            check_eq(f"K24: `{token}`: the words are on the journal's record all the same", len(events(root, "human_answer")), before + 1)
        # and the loop with the flag still set clears it the way `reconcile_question` clears one, then looks as usual
        later = driver_for(root, env, KEY)
        later.state["asked"] = {"kind": "ticket_changed", "stage": "S0", "dispatch": "", "at": "x"}
        later.question_path().write_text("# q\nkind: ticket_changed\nstage: S0\n\nThe ticket changed.\n", encoding="utf-8")
        ticket.write_text(FIXTURE_TICKET, encoding="utf-8")            # the text moved back: the look that follows finds nothing
        make_due(task_root)
        word, printed = entered(later)
        check_eq("K24: an open `ticket_changed` whose text is gone: the flag is cleared, the check goes on", (later.state["asked"], word), ({}, "none"))
        check_in("K24: and one line says the text no longer waits", "no longer waits", printed)
    finally:
        harness.cleanup(root)


def k26_the_drivers_word_is_never_a_reviewers() -> None:
    import judge_code
    import repair_route
    from controller import REPAIR_CAUSES, REVIEWER_CAUSES
    check_eq("K26: the controller's list is the reviewers' five and the driver's word", (REPAIR_CAUSES[-1], REVIEWER_CAUSES), ("ticket_changed", ("test_defect", "mechanical", "environment", "tooling", "reviewer_error")))
    rows = repair_route.findings({"findings": [{"id": "F1", "problem": "a sleep", "cause": "ticket_changed"}, {"id": "F2", "problem": "a stand", "cause": "environment"}]})
    check_eq("K26: a finding a reviewer typed `ticket_changed` reads as `test_defect` (it spends the cap): the safe side", [r["cause"] for r in rows], ["test_defect", "environment"])
    real = (judge_code.judge.settings, judge_code.judge.active, judge_code.judge.ask_one)
    try:
        judge_code.judge.settings = lambda root=None: {"provider": "stub", "mode": "active"}
        judge_code.judge.active = lambda cfg, name: True
        for said, expected in (("ticket_changed", "test_defect"), ("mechanical", "mechanical")):
            judge_code.judge.ask_one = lambda *a, **k: {"value": said, "decided": True, "confidence": 0.9}
            check_eq(f"K26: the judge's `{said}` reads as `{expected}`", judge_code.cause("a finding")["repair_cause"], expected)
    finally:
        judge_code.judge.settings, judge_code.judge.active, judge_code.judge.ask_one = real
    import ticket_adapter as TA
    now = datetime(2026, 10, 7, 12, 0, 0, tzinfo=UTC)
    check("K26: the adapter's future-time slack (60 s at, 61 s beyond) is the one helper both the trigger and the driver's throttle read", TA.stamp_is_ahead(iso(now + timedelta(seconds=61)), now) and not TA.stamp_is_ahead(iso(now + timedelta(seconds=60)), now))


SCENARIOS = [
    k15_positions_in_the_run,
    k16_a_pasted_story_passes_its_file,
    k17_the_word_that_the_ticket_is_not_needed_outlives_s0,
    k18_no_controller_means_no_look,
    k19_a_closed_story_is_not_looked_at,
    k20_gate_b_is_checked_before_it_is_asked,
    k21_the_options_constant_is_in_s0_md,
    k22_no_baseline_the_ticket_as_it_stands_becomes_one,
    k23_a_waiting_text_after_a_crash_is_asked_again,
    k24_an_answer_after_the_text_stopped_waiting,
    k26_the_drivers_word_is_never_a_reviewers,
]


def main() -> None:
    """No argument: every scenario. Names (prefixes, `k7c k10`): only those - the one a mutation of the driver is checked
    by (builder-rules 7a), with the same checks; an argument that names nothing is an error, never a silent green."""
    wanted = sys.argv[1:]
    chosen = [s for s in SCENARIOS if not wanted or any(s.__name__.startswith(prefix) for prefix in wanted)]
    if not chosen:
        sys.exit(f"test_story_run_freshness: no scenario starts with {wanted}; they are: " + ", ".join(s.__name__ for s in SCENARIOS))
    run_scenarios([], chosen)
    harness.finish("test_story_run_freshness_k15_k26")


# split: runner piece 1
if __name__ == "__main__":
    main()
