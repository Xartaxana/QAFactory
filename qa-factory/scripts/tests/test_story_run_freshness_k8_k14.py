#!/usr/bin/env python3
"""k8 k14: a part of test_story_run_freshness.py, split by tools/test_split.py (TD-11c). The shared helpers are in story_run_freshness_common."""
import contextlib
import io
import json
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402
from story_run_common import OTHER_SCRIPT, driver_for, human_broken, run_scenarios, stub_calls
import human_text  # noqa: E402
from story_run_freshness_common import (  # noqa: E402
    KEY, adapter_calls, answer_file, asked_driver, entered, events, fixed_adapter, freshness_project, iso,
    looked, make_due, now_whole, person_of, question_of, spy_stdout,
)


UNREAD = "is not one of the answers this question takes, so nothing has moved yet."      # the ONE lead of an unread answer


def error_object(owner: str, message: str, status=None) -> str:
    return json.dumps({"ok": False, "owner": owner, "status": status, "retry_at": None, "message": message}
                      | ({"file": "jira-fields.json"} if owner in ("factory", "person") else {}))


# --- K8-K9 stop and the words that are not a token -------------------------------------------------------------------
def k8_stop_then_a_no_answer_run_asks_again_with_no_read() -> None:
    root, task_root, env, ticket = freshness_project()
    try:
        asked_driver(root, env, task_root, ticket)
        second = driver_for(root, env, KEY, answer=answer_file(root, "stop"))
        calls = spy_stdout(second)
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            code = second.run()
        check_eq("K8: `stop`: exit 3, the same question is open", (code, second.state["asked"].get("kind")), (3, "ticket_changed"))
        again = second.question_path().read_text(encoding="utf-8")
        import story_run
        held = story_run.Driver.stop_held("Answer `new text` or `old text` when you decide.")
        check_in("K8: the question comes back and says nothing runs (the ONE `stop_held` sentence)", held, again)
        check_eq("K8/F7: the held lines are there ONCE", again.count("You said to stop."), 1)
        check_eq("K8: nothing ran: no adapter call, no rework, the new text still waits", (adapter_calls(calls), second.state.get("ticket_rework"), (task_root / "work" / "ticket-snapshot.next.json").is_file()), ([], None, True))
        check("K8: the words are on the record, whole, before the question comes back (journal and driver-answers.jsonl)",
              any("stop" in str(r.get("notes")) for r in events(root, "human_answer"))
              and any(json.loads(l).get("words") == "stop" for l in (task_root / "state" / "driver-answers.jsonl").read_text(encoding="utf-8").splitlines()))
        import story_run
        body = story_run.QUESTION_HEAD_RE.sub("", story_run.ANSWER_BLOCK_RE.sub("", again), count=1).strip()
        check_eq("K8: the question that comes back still breaks no rule of human-questions.md", human_broken(body), [])
        # a run with no answer: the open ticket_changed question is asked again from the two files, the tracker is not read
        third = driver_for(root, env, KEY)
        calls = spy_stdout(third)
        with contextlib.redirect_stdout(io.StringIO()):
            code = third.run()
        check_eq("K8: a run with no answer re-asks (exit 3) and makes no adapter call at all", (code, adapter_calls(calls)), (3, []))
        check_in("K8: the asked-again question says it was answered before (FR-7)", "You have answered this exact question before", third.question_path().read_text(encoding="utf-8"))
        check_eq("K8: nothing was journaled twice", len(events(root, "ticket_changed")), 1)
    finally:
        harness.cleanup(root)


def k9_an_answer_that_is_not_a_token() -> None:
    root, task_root, env, ticket = freshness_project()
    try:
        asked_driver(root, env, task_root, ticket)
        conducted = 0
        for label, words in (("prose", "I think the new one is fine, go ahead."), ("another script", OTHER_SCRIPT),
                             ("a token only on the second line", "please\nnew text"), ("empty first lines are skipped", "\n\n  New Text.  \nbecause")):
            driver = driver_for(root, env, KEY, answer=answer_file(root, words), max_boundaries=0)
            calls = spy_stdout(driver)
            with contextlib.redirect_stdout(io.StringIO()):
                code = driver.run()
            text = driver.question_path().read_text(encoding="utf-8") if driver.question_path().is_file() else ""
            if label.startswith("empty first lines"):
                # the FIRST non-empty line is the token: `New Text.` is `new text` after `s0_normalize` - adopted, not asked again
                check_eq("K9: the first NON-EMPTY line is the token (BOM, quotes, a full stop and case are only normalized)", (driver.state["asked"], (task_root / "work" / "ticket-snapshot.next.json").is_file()), ({}, False))
                continue
            check_eq(f"K9: {label}: asked again (exit 3), the same kind", (code, driver.state["asked"].get("kind")), (3, "ticket_changed"))
            check_in(f"K9: {label}: quotes the words and says nothing has moved yet (P03c: the one lead of an unread answer)",
                     "is not one of the answers this question takes, so nothing has moved yet.", text)
            check_not_in(f"K9: {label}: the old 'it takes only' lead is gone", "it takes only", text)
            check_eq(f"K9: {label}: the question comes back priced, every option with its three lines", human_text.price_problems(text, None), [])
            seen_calls = len([c for c in stub_calls(root) if c["kind"] == "conductor"])
            check_eq(f"K9: {label}: D-0041 - the unread answer was exactly ONE conductor call (a `continue` leaves the question standing; never `--adopt`)",
                     seen_calls, conducted + 1)
            conducted = seen_calls
            check_eq(f"K9: {label}: no adapter call, `.next` kept, no rework", (adapter_calls(calls), (task_root / "work" / "ticket-snapshot.next.json").is_file(), driver.state.get("ticket_rework")), ([], True, None))
    finally:
        harness.cleanup(root)


def k9b_a_choice_the_adapter_could_not_carry_out() -> None:
    root, task_root, env, ticket = freshness_project()
    try:
        driver, _ = asked_driver(root, env, task_root, ticket)
        for label, token, said, answer in (
                ("the new text could not be adopted", "new text", "the stored new text cannot be read",
                 fixed_adapter(3, error_object("tracker", "the stored new text cannot be read"), "ticket_adapter: the stored new text cannot be read")),
                ("the decline could not be recorded", "old text", "cannot write the story's record",
                 fixed_adapter(4, error_object("factory", "cannot write the story's record"), "ticket_adapter: cannot write the story's record")),
                ("the adapter did not finish in 300 s", "new text", "ticket_adapter.py did not finish within 300 seconds",
                 lambda args, kwargs: (124, "", "ticket_adapter.py did not finish within 300 seconds"))):
            calls = spy_stdout(driver, answer)
            person = None
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    driver.take_ticket_answer(token + "\nbecause", "# q\n", "S0", "")
            except Exception as exc:
                person = exc
            check(f"K9b: {label}: the question comes back, with the adapter's sentence (no script name in front) and the whole question after it",
                  person_of(person) is not None and f"Your choice could not be carried out: {said}\n\n" in person.text
                  and "anything you write after the first line is kept with your answer for gate B" in person.text
                  and person.text.rstrip().split("\n")[-1].startswith("the story: "), repr(person))
            check_eq(f"K9b: {label}: the words are on the record first, nothing is owed, the new text still waits, one adapter call",
                     (any("because" in str(r.get("notes")) for r in events(root, "human_answer")), driver.state.get("ticket_rework"),
                      (task_root / "work" / "ticket-snapshot.next.json").is_file(), len(adapter_calls(calls))), (True, None, True, 1))
    finally:
        harness.cleanup(root)


def k10_exit_3_is_an_informed_pass_journaled_once_per_window() -> None:
    root, task_root, env, _ticket = freshness_project()
    try:
        make_due(task_root)
        driver = driver_for(root, env, KEY)
        spy_stdout(driver, fixed_adapter(3, error_object("tracker", "the tracker could not be read for QA-1 (HTTP 503) - retry", status=503),
                                         "ticket_adapter: the tracker could not be read for QA-1 (HTTP 503) - retry"))
        t = now_whole()
        got, printed = looked(driver, now=t)
        check_eq("K10: exit 3: `unchecked`, one line, the story goes on", got, "unchecked")
        check_in("K10: the line", "ticket not checked: the tracker could not be read for QA-1 (HTTP 503) - retry; the story goes on with the text it was built on", printed)
        check_eq("K10: `ticket_unchecked` is journaled (and never as a change)", (len(events(root, "ticket_unchecked")), len(events(root, "ticket_changed"))), (1, 0))
        for label, later, count in (("at 6 h exactly: the same window", t + timedelta(hours=6), 1), ("6 h and a second: a new window", t + timedelta(hours=6, seconds=1), 2),
                                    ("a minute later: the line is said, not journaled", t + timedelta(hours=6, seconds=61), 2)):
            got, printed = looked(driver, now=later)
            check_eq(f"K10: {label}: the line is said every time", ("ticket not checked:" in printed, got), (True, "unchecked"))
            check_eq(f"K10: {label}: journaled {count} time(s) in all", len(events(root, "ticket_unchecked")), count)
        # a throttle stamp from the future is unknown: journaled; at the slack exactly it is read by time
        driver.state["ticket_unchecked_at"] = iso(t + timedelta(seconds=60))
        looked(driver, now=t)
        check_eq("K10: a throttle stamp 60 s ahead of the clock is read by time (inside the window): not journaled", len(events(root, "ticket_unchecked")), 2)
        driver.state["ticket_unchecked_at"] = iso(t + timedelta(seconds=61))
        looked(driver, now=t)
        check_eq("K10: 61 s ahead: unknown, journaled", len(events(root, "ticket_unchecked")), 3)
        check_eq("K10: the check stays due (the adapter stamped nothing): a failed look is not a look", check_due(task_root), True)
    finally:
        harness.cleanup(root)


def check_due(task_root: Path) -> bool:
    import ticket_adapter as TA
    return TA.check_is_due(task_root)


def k11_a_check_that_does_not_finish_is_unchecked() -> None:
    import story_run
    root, task_root, env, _ticket = freshness_project()
    try:
        make_due(task_root)
        driver = driver_for(root, env, KEY)
        seen = []
        real_run = story_run.subprocess.run

        def hanging(argv, *args, **kwargs):
            if Path(str(argv[2])).name != "ticket_adapter.py":
                return real_run(argv, *args, **kwargs)              # the journal line must land
            seen.append(kwargs.get("timeout"))
            raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))
        story_run.subprocess.run = hanging
        try:
            got, printed = looked(driver)
        finally:
            story_run.subprocess.run = real_run
        check_eq("K11: a call beyond 300 s is `unchecked`, with the ceiling passed", (got, seen), ("unchecked", [300]))
        check_in("K11: one line says it did not finish", "ticket not checked: ticket_adapter.py did not finish within 300 seconds; the story goes on with the text it was built on", printed)
        check_eq("K11: journaled like exit 3", len(events(root, "ticket_unchecked")), 1)
        # a call that returns is read as usual; every other caller of py_stdout has no ceiling at all
        seen.clear()

        def returning(argv, *args, **kwargs):
            if Path(str(argv[2])).name != "ticket_adapter.py":
                return real_run(argv, *args, **kwargs)
            seen.append(kwargs.get("timeout"))
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps({"result": "none", "changed": []}), stderr="")
        story_run.subprocess.run = returning
        try:
            got, _ = looked(driver)
            driver.py_stdout("ticket_adapter.py", "--selftest")
        finally:
            story_run.subprocess.run = real_run
        check_eq("K11: a call that returns within the ceiling is read as usual; a plain `py_stdout` passes no timeout", (got, seen), ("none", [300, None]))
        check_eq("K11: the S0 read has no ceiling of its own (an exit 124 there would read as a factory fault)", story_run.Driver.PY_TIMEOUTS.get("ticket_adapter.py"), None)
    finally:
        harness.cleanup(root)


def k12_exit_5_the_lost_login_and_the_protection_service() -> None:
    import source_inventory as SI
    import story_run
    import ticket_adapter as TA
    root, task_root, env, _ticket = freshness_project()
    try:
        make_due(task_root)
        driver = driver_for(root, env, KEY)
        spy_stdout(driver, fixed_adapter(5, error_object("auth", "the tracker no longer accepts the token (HTTP 401)", status=401), "ticket_adapter: the tracker no longer accepts the token"))
        got, _ = looked(driver)
        # F3 (a) (C1-3 node B): the lost tracker login is the `ticket_auth` QUESTION (kind `ticket_auth`, exit 3), not `claude -p`'s InfraStop
        check("K12: exit 5, owner `auth`: the `ticket_auth` question (a Person, never an InfraStop), the door named in the answer block",
              isinstance(got, story_run.Person) and not isinstance(got, story_run.InfraStop) and (got.kind, got.stage, got.code) == ("ticket_auth", "S0", 3)
              and "tracker token variable" in got.answer_note, repr(got))
        check_eq("K12: and nothing is journaled as unchecked", len(events(root, "ticket_unchecked")), 0)
        spy_stdout(driver, fixed_adapter(5, "", "ticket_adapter: HTTP 401"))
        got, _ = looked(driver)
        check("K12: exit 5 with no object at all is still the lost login: the same question", isinstance(got, story_run.Person) and got.kind == "ticket_auth", repr(got))
        check("K12: its answers are priced option lines, `retry`, `go on`, `stop`, each with its three lines, and no hand command",
              all(f"`{t}` — " in got.text for t in ("retry", "go on", "stop")) and human_text.price_problems(got.text, None) == []
              and "--ticket-file" not in got.text and human_broken(got.text) == [], got.text[-700:])
        # K12b (B-408 seam): the SAME object the adapter prints for an answer the tracker is not shown to have written
        check("K12b: `intermediary` is one of the adapter's owners (B-408 is on this tree)", "intermediary" in TA.OWNERS)
        objects = []
        with contextlib.redirect_stderr(io.StringIO()):
            code = TA.refuse_auth(SI.Intercepted("HTTP 403: an HTML page, not the tracker's own answer (a firewall or a protection service)"), objects.append)
        check_eq("K12b: the adapter's own refusal of an intercepted read: exit 5, owner `intermediary`", (code, objects[0]["owner"]), (5, "intermediary"))
        sentence = objects[0]["message"]
        spy_stdout(driver, fixed_adapter(5, json.dumps(objects[0]), "ticket_adapter: " + sentence))
        got, printed = looked(driver)
        check_eq("K12b: a freshness read that meets a foreign answer is `unchecked`, never the lost-login stop", got, "unchecked")
        check_in("K12b: the line is the spec's, with B-408's own sentence in it (one path, no second text)",
                 f"ticket not checked: a protection service in front of the tracker answered, not the tracker ({sentence}); the story goes on with the text it was built on", printed)
        check_eq("K12b: journaled like exit 3, once", len(events(root, "ticket_unchecked")), 1)
        check_not_in("K12b: and the token is never told to be renewed", "renew", printed)
    finally:
        harness.cleanup(root)


def lost_login(driver):
    """A tracker that no longer accepts the token (the adapter's exit 5, owner `auth`) as the freshness check's answer."""
    return spy_stdout(driver, fixed_adapter(5, error_object("auth", "the tracker no longer accepts the token (HTTP 401)", status=401),
                                            "ticket_adapter: the tracker no longer accepts the token"))


def run_quiet(driver) -> int:
    with contextlib.redirect_stdout(io.StringIO()):
        return driver.run()


def asked_ticket_auth(root: Path, env: dict, task_root: Path):
    """A story whose check was due and whose tracker login is lost: the `ticket_auth` question is open (the first process)."""
    make_due(task_root)
    first = driver_for(root, env, KEY, max_boundaries=0)
    lost_login(first)
    got, _ = looked(first)
    person = person_of(got)
    check("setup: the lost login asks the `ticket_auth` question", person is not None and person.kind == "ticket_auth", repr(got))
    question_of(first, person)
    return first


def conductor_calls_of(root: Path) -> int:
    return len([c for c in stub_calls(root) if c["kind"] == "conductor"])


def k12c_ticket_auth_retry_go_on_stop_unread() -> None:
    """G3 (FR-9, FR-7, FR-4): each word of the `ticket_auth` question has its executor. `retry` runs the check again in this process;
    `go on` is a recorded informed pass, honoured for the freshness window and asked again only when it has run out; `stop` holds the
    question once (F7); other words are new words for the conductor (D-0041), never a silent pass."""
    root, task_root, env, _ticket = freshness_project()
    try:
        asked_ticket_auth(root, env, task_root)
        # retry: the check runs again IN THIS process; the login still lost -> the question again, never a pass
        driver = driver_for(root, env, KEY, answer=answer_file(root, "retry"), max_boundaries=0)
        calls = lost_login(driver)
        code = run_quiet(driver)
        check_eq("K12c retry: the check ran again once (the adapter was asked) and the lost login is the same question: exit 3",
                 (code, len(adapter_calls(calls)), driver.state["asked"].get("kind")), (3, 1, "ticket_auth"))
        check_eq("K12c retry: nothing was passed: no `ticket_unchecked`, no `fresh.ticket_auth` kept",
                 (len(events(root, "ticket_unchecked")), (driver.state.get("s0_answers") or {}).get("fresh.ticket_auth")), (0, None))
        # retry with the token renewed: the question is gone and the story goes on
        driver = driver_for(root, env, KEY, answer=answer_file(root, "retry"), max_boundaries=0)
        calls = spy_stdout(driver, fixed_adapter(0, json.dumps({"result": "none", "changed": []})))
        code = run_quiet(driver)
        check_eq("K12c retry: a token that works clears the question (no question open, one look)", (driver.state.get("asked"), len(adapter_calls(calls))), ({}, 1))
        check("K12c retry: ... and the exit is not a question", code != 3, str(code))
        # go on: recorded as an informed pass (FR-4), the story goes on with its text, the look is not made again in the window (FR-7)
        asked_ticket_auth(root, env, task_root)
        driver = driver_for(root, env, KEY, answer=answer_file(root, "go on"), max_boundaries=0)
        calls = lost_login(driver)
        code = run_quiet(driver)
        check_eq("K12c go on: no question (exit is not 3) and the adapter was NOT asked again after the word", (code != 3, len(adapter_calls(calls))), (True, 0))
        check_eq("K12c go on: `ticket_unchecked` is journaled once (the informed pass), the word is kept for the window",
                 (len(events(root, "ticket_unchecked")), driver.state["s0_answers"].get("fresh.ticket_auth"), bool(driver.state.get("ticket_unchecked_at"))),
                 (1, "go on", True))
        check("K12c go on: the person's word is on the journal whole", any("ticket login lost (go on): " in str(r.get("notes")) for r in events(root, "human_answer")))
        again = driver_for(root, env, KEY, max_boundaries=0)
        calls = lost_login(again)
        make_due(task_root)
        got, printed = entered(again)
        check_eq("K12c go on: a later process inside the window does not ask again (FR-7) and does not look", (got, len(adapter_calls(calls))), ("unchecked", 0))
        check_in("K12c go on: and says so in a line", "you said to go on without looking at the ticket", printed)
        # expiry: the window has run out -> the key is dropped and the check runs again; the lost login is the question again
        again.state["ticket_unchecked_at"] = iso(now_whole() - timedelta(hours=7))
        again.save_state()
        got, _ = entered(again)
        check_eq("K12c go on: past the window the check runs and the question is asked again",
                 (person_of(got) is not None and got.kind == "ticket_auth", len(adapter_calls(calls)), "fresh.ticket_auth" in (again.state.get("s0_answers") or {})),
                 (True, 1, False))
        # an unreadable stamp is not a fresh one (FR-41): the word is not honoured
        again.state.setdefault("s0_answers", {})["fresh.ticket_auth"] = "go on"
        again.state["ticket_unchecked_at"] = "not a time"
        again.state["asked"] = {}
        got, _ = entered(again)
        check_eq("K12c go on: a stamp that is not a time honours nothing", person_of(got) is not None and got.kind == "ticket_auth", True)
        # stop: held once (F7) - a second stop does not stack the held lines; the question is the same; no conductor
        driver = driver_for(root, env, KEY, answer=answer_file(root, "stop"), max_boundaries=0)
        lost_login(driver)
        before = conductor_calls_of(root)
        make_due(task_root)
        driver.state["asked"] = {"kind": "ticket_auth", "stage": "S0", "dispatch": ""}
        driver.state.setdefault("s0_answers", {}).pop("fresh.ticket_auth", None)
        question_of(driver, driver.ticket_auth_person("401"))
        for round_ in (1, 2):
            driver = driver_for(root, env, KEY, answer=answer_file(root, "stop"), max_boundaries=0)
            lost_login(driver)
            code = run_quiet(driver)
            held = driver.question_path().read_text(encoding="utf-8")
            check_eq(f"K12c stop (round {round_}): exit 3, the question held, the held line ONCE (F7), no conductor",
                     (code, driver.state["asked"].get("kind"), held.count("You said to stop."), conductor_calls_of(root) - before), (3, "ticket_auth", 1, 0))
        check("K12c stop: the held question still offers `retry` and `go on` and is priced",
              "`retry`" in held and "`go on`" in held and human_text.price_problems(held.split("## How to answer")[0], None) == [], held[-600:])
    finally:
        harness.cleanup(root)
    # other words: D-0041 - exactly ONE conductor call; a usable-less conductor shows the question again with the one lead, priced
    root, task_root, env, _ticket = freshness_project()
    try:
        from story_run_common import set_control
        set_control(root, {"conductor": {"action": "ask_person", "question": "", "did": "no options"}})
        asked_ticket_auth(root, env, task_root)
        driver = driver_for(root, env, KEY, answer=answer_file(root, "I renewed it yesterday, I think"), max_boundaries=0)
        calls = lost_login(driver)
        code = run_quiet(driver)
        held = driver.question_path().read_text(encoding="utf-8")
        check_eq("K12c unread: exit 3, kind `ticket_auth`, exactly ONE conductor call, nothing passed",
                 (code, driver.state["asked"].get("kind"), conductor_calls_of(root), (driver.state.get("s0_answers") or {}).get("fresh.ticket_auth")),
                 (3, "ticket_auth", 1, None))
        check_in("K12c unread: the question comes back with the one lead", 'Your answer "I renewed it yesterday, I think" ' + UNREAD, held)
        check_eq("K12c unread: and priced, with its three answers", (human_text.price_problems(held.split("## How to answer")[0], None),
                                                                       all(f"`{t}` — " in held for t in ("retry", "go on", "stop"))), ([], True))
        # F-2 (critic t-689): an unread answer after an unread answer does not stack its leads (the question is the held one, and
        # the lead is the NEW one); a `stop` after them is the stop line alone above the question - neither unread lead stays
        for round_, words in ((2, "I will think about the login tomorrow"), (3, "maybe the day after")):
            driver = driver_for(root, env, KEY, answer=answer_file(root, words), max_boundaries=0)
            lost_login(driver)
            run_quiet(driver)
            held_n = driver.question_path().read_text(encoding="utf-8")
            check_eq(f"K12c unread (answer {round_}): ONE lead, the newest answer's, no earlier one stacked beneath it",
                     (held_n.count(UNREAD), held_n.count(f'Your answer "{words}"'), held_n.count("I renewed it yesterday")), (1, 1, 0))
        driver = driver_for(root, env, KEY, answer=answer_file(root, "stop"), max_boundaries=0)
        lost_login(driver)
        run_quiet(driver)
        held_stop = driver.question_path().read_text(encoding="utf-8")
        check_eq("K12c unread then `stop`: the stop line ONCE and no unread lead above or under it",
                 (held_stop.count("You said to stop."), held_stop.count(UNREAD), held_stop.count("maybe the day after")), (1, 0, 0))
        check("K12c unread then `stop`: the question under it is the same one (priced, `retry` / `go on` / `stop`)",
              all(f"`{t}` — " in held_stop for t in ("retry", "go on", "stop")), held_stop[-600:])
        # a conductor `continue` returns: nothing passed, the check runs again (which decides) - the question stands, never a silent pass
        set_control(root, {"conductor": {"action": "continue"}})
        driver = driver_for(root, env, KEY, answer=answer_file(root, "never mind the login"), max_boundaries=0)
        calls = lost_login(driver)
        code = run_quiet(driver)
        check_eq("K12c unread + conductor `continue`: nothing passed; the check ran again and the question stands (exit 3)",
                 (code, driver.state["asked"].get("kind"), len(adapter_calls(calls)), (driver.state.get("s0_answers") or {}).get("fresh.ticket_auth")),
                 (3, "ticket_auth", 1, None))
    finally:
        harness.cleanup(root)


def k13_the_factorys_own_faults_are_reported() -> None:
    import story_run
    root, task_root, env, _ticket = freshness_project()
    try:
        make_due(task_root)
        driver = driver_for(root, env, KEY)
        for label, answer in (("exit 4", (4, error_object("factory", "refused - jira-fields.json is empty"), "ticket_adapter: refused")),
                              ("owner factory on exit 1", (1, error_object("factory", "an unexpected error"), "")),
                              ("exit 2 (usage)", (2, "", "usage: ticket_adapter.py freshness")),
                              ("a crash with no object", (7, "Traceback", "boom")),
                              ("exit 0 with no JSON object", (0, "this is not json", "")),
                              ("exit 0 with a result nobody knows", (0, json.dumps({"result": "weather"}), ""))):
            spy_stdout(driver, fixed_adapter(*answer))
            got, printed = looked(driver)
            check(f"K13: {label}: a Refusal that says it is the factory's own and names what is expected", isinstance(got, story_run.Refusal) and "the cause is the factory's own" in got.text, repr(got))
            check_eq(f"K13: {label}: never an informed pass, never journaled as unchecked", (printed, len(events(root, "ticket_unchecked"))), ("", 0))
        spy_stdout(driver, fixed_adapter(4, error_object("factory", "refused - jira-fields.json is empty"), ""))
        got, _ = looked(driver)
        check_in("K13: exit 4 names the file the adapter named", "jira-fields.json", got.text)
    finally:
        harness.cleanup(root)


def k14_exit_1_goes_by_the_owner() -> None:
    root, task_root, env, _ticket = freshness_project()
    try:
        make_due(task_root)
        driver = driver_for(root, env, KEY)
        spy_stdout(driver, fixed_adapter(1, error_object("person", "the ticket file you gave is missing or empty"), "ticket_adapter: the ticket file you gave is missing or empty"))
        got, printed = looked(driver)
        check_eq("K14: exit 1 owner `person`: its message in one line, `unchecked`, nothing journaled", (got, "the ticket file you gave is missing or empty" in printed, len(events(root, "ticket_unchecked"))), ("unchecked", True, 0))
        spy_stdout(driver, fixed_adapter(1, error_object("tracker", "QA-1 was not found (HTTP 404)", status=404), ""))
        got, printed = looked(driver)
        check_eq("K14: exit 1 owner `tracker` (not found): the exit-3 class, journaled", (got, len(events(root, "ticket_unchecked"))), ("unchecked", 1))
    finally:
        harness.cleanup(root)


SCENARIOS = [
    k8_stop_then_a_no_answer_run_asks_again_with_no_read,
    k9_an_answer_that_is_not_a_token,
    k9b_a_choice_the_adapter_could_not_carry_out,
    k10_exit_3_is_an_informed_pass_journaled_once_per_window,
    k11_a_check_that_does_not_finish_is_unchecked,
    k12_exit_5_the_lost_login_and_the_protection_service,
    k12c_ticket_auth_retry_go_on_stop_unread,
    k13_the_factorys_own_faults_are_reported,
    k14_exit_1_goes_by_the_owner,
]


def main() -> None:
    """No argument: every scenario. Names (prefixes, `k7c k10`): only those - the one a mutation of the driver is checked
    by (builder-rules 7a), with the same checks; an argument that names nothing is an error, never a silent green."""
    wanted = sys.argv[1:]
    chosen = [s for s in SCENARIOS if not wanted or any(s.__name__.startswith(prefix) for prefix in wanted)]
    if not chosen:
        sys.exit(f"test_story_run_freshness: no scenario starts with {wanted}; they are: " + ", ".join(s.__name__ for s in SCENARIOS))
    run_scenarios([], chosen)
    harness.finish("test_story_run_freshness_k8_k14")


# split: runner piece 1
if __name__ == "__main__":
    main()
