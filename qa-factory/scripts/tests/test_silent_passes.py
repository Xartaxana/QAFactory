"""C1-7a (conductor/1, the owner's principle P22; spec t-1152 §3.2, §3.3, §3.5, §L-2): a factory script whose exit the driver does not
act on is a state without a move when it fails. This file pins the OWED-ROW ladder (a journal row the journal refused is written again
before any brief is built, and a second refusal is the seam's question), `py_trace` (a trace with a mandatory reason), the person's own
question back for pasted material that was not recorded and for a mode switch that was not recorded, and the `py(check=True, expect=)`
contract (the retry keeps `expect`, a timeout is a failure). It is the ONE killing file of every mutation of this node
(builder-rules 7a). C1-7b appends the keys of the gate steps.

    python -B scripts/tests/test_silent_passes.py
"""
import contextlib
import io
import json
import re
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402
from story_run_common import driver_for, eq, run_scenarios, seed  # noqa: E402

import story_run  # noqa: E402

TASK = "QA-9"
BLOCK = story_run.JOURNAL_ROWS_BLOCK


def stub(driver, codes: dict, seen: list, default: int = 0):
    """Replace `driver.py`: each script in `codes` answers from its own queue of exit codes (then `default`); every call is appended
    to `seen` as `(script, args)`; a script that is not in `codes` runs for real."""
    real, queues = driver.py, {name: list(values) for name, values in codes.items()}

    def py(script, *args, **kwargs):
        if script in queues:
            seen.append((script, args))
            code = queues[script].pop(0) if queues[script] else default
            return code, ("refused" if code else "written")
        return real(script, *args, **kwargs)
    driver.py = py
    return real


def quiet(call, *args, **kwargs):
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        try:
            return call(*args, **kwargs), buffer.getvalue()
        except story_run.Person as person:
            return person, buffer.getvalue()


def on_disk(task_root: Path) -> dict:
    return json.loads((task_root / "state" / "driver-state.json").read_text(encoding="utf-8"))


def runs(task_root: Path, kind: str) -> list:
    path = task_root / "state" / "driver-runs.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.is_file() else []
    return [r for r in rows if r.get("kind") == kind]


def person_text(person) -> str:
    return str(getattr(person, "text", "") or person)


def k1_owed_then_written() -> None:
    """K1 (W, AT the limit): a refused row is owed, one line is printed, nothing is asked; the next drain writes it. Zero owed rows and
    a state with no `owed_rows` key at all (recorded before this change) are a no-op: no call, no line, no question (E7)."""
    root, task_root, env = seed(TASK)
    try:
        driver, seen = driver_for(root, env, TASK), []
        stub(driver, {"log_append.py": [2, 0]}, seen)
        _none, out = quiet(driver.owed_rows_step)
        check_eq("K1: no key, nothing owed: no call, no line", (seen, out), ([], ""))
        result, out = quiet(driver.answer_row, "S2 test: ", "my words", what="your answer at the test")
        check_eq("K1: the first refusal returns nothing (no Person, no raise)", result, None)
        check_eq("K1: it is printed in ONE line", len([l for l in out.splitlines() if l.strip()]), 1)
        check_in("K1: the line says the row is owed", "written again before the next step", out)
        rows = on_disk(task_root)["owed_rows"]
        check_eq("K1: one row owed, saved to the state file", len(rows), 1)
        row = rows[0]
        check_eq("K1: the row keeps its script, its try count and a stage id",
                 (row["script"], row["tries"], row["exit"], bool(re.fullmatch(r"S\d", row["stage"]))), ("log_append.py", 1, 2, True))
        check_in("K1: the row carries the words by ARGUMENT, for the second write", "S2 test: my words", " ".join(row["args"]))
        result, out = quiet(driver.owed_rows_step)
        check_eq("K1: the drain writes it: nothing asked", result, None)
        check_eq("K1: the row left the list", on_disk(task_root)["owed_rows"], [])
        check_eq("K1: written exactly twice (the owe and the drain)", len(seen), 2)
        check_eq("K1: a row that writes at the second try leaves no `rows_given_up` trace", runs(task_root, "rows_given_up"), [])
        before = len(seen)
        quiet(driver.owed_rows_step)
        check_eq("K1: an empty list is a no-op", len(seen), before)
        driver.state["owed_rows"] = "not a list"
        result, _out = quiet(driver.owed_rows_step)
        check_eq("K1: a malformed record never blocks the loop", result, None)
        check_eq("K1: ...and it is not dropped unsaid: ONE trace_failed line", len(runs(task_root, "trace_failed")), 1)
        check_eq("K1: ...and it reads as no rows afterwards", driver.state["owed_rows"], [])
    finally:
        harness.cleanup(root)


def k2_second_failure_is_the_seam() -> None:
    """K2 (W, BEYOND the limit): the second refusal is the seam's question - `no_move` called DIRECTLY with the block the waiver knows,
    the priced fallback and no paid call; its text is row ids and counts, never the person's words (B-2). A `what` that holds a
    known-refusals phrase still reaches the seam (the table is not read)."""
    root, task_root, env = seed(TASK)
    try:
        driver, seen = driver_for(root, env, TASK), []
        stub(driver, {"log_append.py": []}, seen, default=2)
        driver.answer_row("S2 test: ", "SECRET-WORDS", what="the stage already completed; STORY BUDGET; expected_revision")
        states, real = [], driver.no_move
        driver.no_move = lambda state, moves=None: (states.append(state), real(state, moves))[1]
        person, _out = quiet(driver.owed_rows_step)
        check("K2: the second refusal raises the seam's Person", isinstance(person, story_run.Person), repr(person))
        check_eq("K2: the seam was called once, directly", len(states), 1)
        state = states[0]
        check_eq("K2: with the block the waiver knows and no paid call", (state["block"], state["call"], state["kind"]), (BLOCK, False, "refusal"))
        check_eq("K2: the doors are retry, go on, stop", state["fallback"], ["retry", "go on", "stop"])
        check_not_in("K2: the person's words are nowhere in what the seam is given", "SECRET-WORDS", json.dumps(state))
        check_in("K2: the text names the row id and the count", on_disk(task_root)["owed_rows"][0]["id"], state["text"])
        check_in("K2: the lead says the fault is the factory's own", "factory's own", state["lead"])
        check_eq("K2: the stage is a stage id (waiver.py --stage)", bool(re.fullmatch(r"S\d", state["stage"])), True)
        check("K2: the options offered are the three doors", set(getattr(person, "offered", ())) >= {"retry", "go on", "stop"}, repr(getattr(person, "offered", None)))
        owed_id = on_disk(task_root)["owed_rows"][0]["id"]
        check_eq("K2: the question carries the ids of the rows it is about, in the state and on the Person (B-1)",
                 (state["rows"], list(getattr(person, "rows", ()))), ([owed_id], [owed_id]))
        check_eq("K2: the row is still owed and no word is on it", on_disk(task_root)["owed_rows"][0].get("word"), None)
        check_not_in("K2 (F-2): the lead does not say the fault is recorded when nothing is filed", "is recorded as one", state["lead"])
        check_in("K2 (F-2): ...it says what is true: nothing is filed yet", "Nothing about it is filed yet", state["lead"])
        conductor = task_root / "state" / "conductor.jsonl"
        check("K2: no conductor row, no `known:` routing", not conductor.is_file() or "known:" not in conductor.read_text(encoding="utf-8"))
    finally:
        harness.cleanup(root)


def k3_position_before_any_brief() -> None:
    """K3 (B-1): the drain runs after the answer is taken and BEFORE the first step that can dispatch a role (the changed-ticket
    rework), and again first in every loop turn."""
    root, task_root, env = seed(TASK)
    try:
        driver, seen, events = driver_for(root, env, TASK), [], []
        stub(driver, {"log_append.py": [0]}, seen)
        driver.state["owed_rows"] = [{"id": "row-1", "script": "log_append.py", "args": ["--event", "human_answer", "--task", TASK, "--notes", "x"],
                                      "what": "your answer", "stage": "S1", "at": "2026-10-20T00:00:00+00:00", "tries": 1, "exit": 2, "tail": ""}]
        driver.answer_kind = "ticket_changed"
        real_py = driver.py
        driver.py = lambda script, *a, **k: (events.append("write") if script == "log_append.py" else None, real_py(script, *a, **k))[1]
        driver.ticket_rework_step = lambda: events.append("rework") or ""
        driver.where = lambda: {"action": "stop", "reason": "end of test"}
        result, _out = quiet(driver.run)
        check_eq("K3: the run ends", result, story_run.EXIT_DONE)
        check_eq("K3: the row is written BEFORE the changed-ticket rework dispatches a role (pre-loop)", events[:2], ["write", "rework"])
        check_eq("K3: and the list is empty", on_disk(task_root)["owed_rows"], [])

        # the loop turn: a row owed by a pre-loop step is written before the turn's rework step
        driver, seen, events = driver_for(root, env, TASK), [], []
        stub(driver, {"log_append.py": [2]}, seen)
        real_py = driver.py
        driver.py = lambda script, *a, **k: (events.append("write") if script == "log_append.py" else None, real_py(script, *a, **k))[1]
        driver.ticket_freshness_entry = lambda: driver.answer_row("S1 test: ", "w", what="your answer") or events.append("owed")
        driver.ticket_rework_step = lambda: events.append("rework") or ""
        driver.where = lambda: {"action": "stop", "reason": "end of test"}
        result, _out = quiet(driver.run)
        check_eq("K3: a row owed in the pre-loop is written first in the loop turn, before the turn's rework",
                 events[:4], ["write", "owed", "write", "rework"])
        check_eq("K3: ...and that run ends", result, story_run.EXIT_DONE)
    finally:
        harness.cleanup(root)


def k4_the_persons_go_on() -> None:
    """K4 (S5/S6, D-0043, B-2): the seam's question reaches the person through the real `ask`, the `go on` is recorded by the REAL
    waiver.py (the block is a row of references/block-names.json), the next drain gives the rows up with ONE `rows_given_up` line, a
    later row of the same script is given up with no question, another script is asked once, and an older word never answers a newer
    question."""
    root, task_root, env = seed(TASK)
    original_now = story_run._now
    try:
        driver, seen = driver_for(root, env, TASK), []
        real = stub(driver, {"log_append.py": []}, seen, default=2)
        driver.py = lambda script, *a, **k: (2, "refused") if script in ("log_append.py", "project_decisions.py") else real(script, *a, **k)
        driver.answer_row("S2 test: ", "w", what="the stage already completed")
        driver.where = lambda: {"action": "stop", "reason": "end of test"}
        result, out = quiet(driver.run)
        eq("K4: the run ends in the person's question (exit 3)", result, story_run.EXIT_PERSON, out[-300:])
        asked = on_disk(task_root)["asked"]
        check_eq("K4: the question carries the block", asked.get("block"), BLOCK)
        answer = root / "answer.md"
        answer.write_text("go on", encoding="utf-8")
        second = driver_for(root, env, TASK, answer=str(answer))
        second.py = lambda script, *a, **k: (2, "refused") if script in ("log_append.py", "project_decisions.py") else real(script, *a, **k)
        second.where = lambda: {"action": "stop", "reason": "end of test"}
        result, out = quiet(second.run)
        eq("K4: the `go on` is taken (the stage the row names may be done already) and the run goes on", result, story_run.EXIT_DONE, out[-600:])
        overrides = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8")).get("stage_overrides") or []
        check_eq("K4: the real waiver.py recorded the person's word under the block", [o["match"] for o in overrides], [BLOCK])
        state = on_disk(task_root)
        # two rows: the one that was asked about, and the row of the person's own `go on` (the same script, refused as well)
        check_eq("K4: the rows moved to rows_given_up (FR-40), nothing is owed", (state["owed_rows"], len(state["rows_given_up"])), ([], 2))
        check_eq("K4: ONE rows_given_up line in driver-runs.jsonl", len(runs(task_root, "rows_given_up")), 1)

        # The wall clock is FROZEN at the waiver's own second from here on: whatever the driver stamps now is in the same second as the
        # person's word, so an answer paired by clock would be paired by luck (t-1189 B-1; the pairing is by row id, K4b).
        word_at = overrides[0]["at"]
        story_run._now = lambda: word_at

        # a later row of the same script: given up with no question (the same run, the same word)
        third = driver_for(root, env, TASK)
        third.py = second.py
        third.answer_row("S3 test: ", "w2", what="your other answer")
        result, _out = quiet(third.owed_rows_step)
        check_eq("K4: a later row of the same script is given up with no question", result, None)
        check_eq("K4: ...and recorded", (on_disk(task_root)["owed_rows"], len(on_disk(task_root)["rows_given_up"])), ([], 3))

        # another script asks once, and the older word answers nothing of it (the same second as the word: the clock decides nothing)
        third.owe_row("project_decisions.py", "--root", str(root), "add-finding", what="the finding about a pass")
        person, _out = quiet(third.owed_rows_step)
        check("K4: another script asks, once", isinstance(person, story_run.Person), repr(person))
        again, _out = quiet(third.owed_rows_step)
        check("K4: the older word is no answer to the newer question: it is asked again", isinstance(again, story_run.Person), repr(again))
        check_eq("K4: ...and nothing more was given up", len(on_disk(task_root)["rows_given_up"]), 3)
        check_eq("K4: ...the row of the other script is still owed, with no word on it",
                 [(r["script"], r.get("word")) for r in on_disk(task_root)["owed_rows"]], [("project_decisions.py", None)])
    finally:
        story_run._now = original_now
        harness.cleanup(root)


def k4b_the_go_on_is_paired_by_row_ids() -> None:
    """K4b (t-1189 B-1, AR-24, FR-9): the person's `go on` reaches ONLY the rows its own question named, by row id and never by clock.
    A row of another script that is owed when the word is given is not given up (it is asked, with its own ids); a `retry` to that
    newer question gives nothing up; its own `go on` gives it up. Run with the clock frozen at the waiver's second (the critic's probe)
    and with the first question asked in the past. A question that named no rows marks none."""
    root, task_root, env = seed(TASK)
    original_now = story_run._now
    try:
        base = driver_for(root, env, TASK)
        real = stub(base, {"log_append.py": []}, [], default=2)
        refuse = lambda script, *a, **k: (2, "refused") if script in ("log_append.py", "project_decisions.py") else real(script, *a, **k)    # noqa: E731
        answer = root / "answer.md"

        def drive(words: str = "", seed_rows=()):
            if words:
                answer.write_text(words, encoding="utf-8")
            driver = driver_for(root, env, TASK, answer=str(answer)) if words else driver_for(root, env, TASK)
            driver.py, driver.where = refuse, (lambda: {"action": "stop", "reason": "end of test"})
            for script, args, what in seed_rows:
                driver.owe_row(script, *args, what=what)
            return driver

        def given_scripts() -> set:
            return {r["script"] for r in on_disk(task_root)["rows_given_up"]}

        story_run._now = lambda: "2026-01-01T00:00:00+00:00"            # the first question is asked in the past
        first = drive()
        first.answer_row("S2 test: ", "w", what="the stage already completed")
        result, out = quiet(first.run)
        eq("K4b: the first question reaches the person", result, story_run.EXIT_PERSON, out[-300:])
        first_ids = [r["id"] for r in on_disk(task_root)["owed_rows"]]
        check_eq("K4b: it carries the ids of ITS rows", (len(first_ids), on_disk(task_root)["asked"].get("rows")), (1, first_ids))

        # a row of ANOTHER script is owed when the person's word for the first question is taken; the word is not for it
        other = ("project_decisions.py", ("--root", str(root), "add-finding"), "the finding about a pass")
        result, out = quiet(drive("go on", seed_rows=[other]).run)
        eq("K4b: the word is taken and the other script's row is asked, not given up", result, story_run.EXIT_PERSON, out[-400:])
        state = on_disk(task_root)
        other_ids = [r["id"] for r in state["owed_rows"]]
        check_eq("K4b: only the first question's script was given up", given_scripts(), {"log_append.py"})
        check_eq("K4b: the other row is owed, tried twice, with no word on it",
                 [(r["script"], r["tries"], r.get("word")) for r in state["owed_rows"]], [("project_decisions.py", 2, None)])
        check_eq("K4b: the newer question carries the OTHER row's ids, not the first question's",
                 (state["asked"].get("rows"), set(other_ids) & set(first_ids)), (other_ids, set()))
        word_at = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))["stage_overrides"][0]["at"]

        # the clock is now the word's own second: the newer question and the older word share it
        story_run._now = lambda: word_at
        result, out = quiet(drive("retry").run)
        eq("K4b: `retry` to the newer question asks again", result, story_run.EXIT_PERSON, out[-400:])
        state = on_disk(task_root)
        check_eq("K4b: a `retry` gives nothing of the other script up, whatever the clock says",
                 (given_scripts(), [(r["script"], r["tries"]) for r in state["owed_rows"]]), ({"log_append.py"}, [("project_decisions.py", 3)]))
        check_eq("K4b: ...and the question still carries the other row's ids", state["asked"].get("rows"), other_ids)

        # a `go on` whose pass the waiver refused marks nothing: the rows are marked only AFTER the pass is recorded
        refused_pass = drive("go on")
        refused_pass.py = lambda script, *a, **k: (2, "no") if script == "waiver.py" else refuse(script, *a, **k)
        result, out = quiet(refused_pass.run)
        eq("K4b: a pass the waiver refused comes back as the question", result, story_run.EXIT_PERSON, out[-400:])
        check_eq("K4b: ...and no row carries a word", [r.get("word") for r in on_disk(task_root)["owed_rows"] if r["script"] == "project_decisions.py"], [None])

        result, out = quiet(drive("go on").run)
        eq("K4b: its own `go on` is taken", result, story_run.EXIT_DONE, out[-400:])
        check_eq("K4b: ...and gives that script up", (given_scripts(), on_disk(task_root)["owed_rows"]), ({"log_append.py", "project_decisions.py"}, []))
        # the lines: the first `go on` (log_append), the row of the `retry` answer itself (log_append, given up by the script's standing
        # word: Q-4 of the critic, harmless), the second `go on` (project_decisions)
        check_eq("K4b: the `rows_given_up` lines name only the scripts a word was given for",
                 [r["scripts"] for r in runs(task_root, "rows_given_up")],
                 [["log_append.py"], ["log_append.py"], ["log_append.py", "project_decisions.py"]])

        # a question that named no rows marks none; a mark reads the word only while it stands (revocation, case, the stage of the word)
        later = drive()
        rows = [{"id": "row-x", "script": "log_append.py", "args": [], "what": "x", "stage": "S2", "tries": 2}]
        later.state["owed_rows"] = rows
        for asked in ({}, {"rows": []}, {"rows": ["row-other"]}):
            later.mark_rows_word(asked, "S2")
            check_eq(f"K4b: a question with rows {asked.get('rows')!r} marks no row", rows[0].get("word"), None)
        check_eq("K4b: an unmarked row is not under the word although the word stands", later.rows_word(rows[0]), False)
        later.mark_rows_word({"rows": ["row-x"]}, "S2")
        stage = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))["stage_overrides"][0]["stage"]
        pipeline_file = task_root / "pipeline.json"
        data = json.loads(pipeline_file.read_text(encoding="utf-8"))
        override = data["stage_overrides"][0]
        rows[0]["word"] = stage
        check_eq("K4b: a marked row under a standing word is under it", later.rows_word(rows[0]), True)
        override["match"] = BLOCK.upper()
        pipeline_file.write_text(json.dumps(data), encoding="utf-8")
        check_eq("K4b (F-1): the word is read through the waiver's one reader: its case-folded match counts", later.rows_word(rows[0]), True)
        override["revoked_at"] = "2026-10-21T00:00:00+00:00"
        pipeline_file.write_text(json.dumps(data), encoding="utf-8")
        check_eq("K4b (F-1): a revoked word is no word", later.rows_word(rows[0]), False)
        del override["revoked_at"]
        pipeline_file.write_text(json.dumps(data), encoding="utf-8")
        check_eq("K4b: a mark of another stage than the word's is no word", later.rows_word(dict(rows[0], word="S9")), False)
    finally:
        story_run._now = original_now
        harness.cleanup(root)


def k5_duplicates_never_zero() -> None:
    """K5 (error direction): a write that landed and still exited non-zero is written again - a duplicate row is allowed, a lost row is
    not: the first run is never skipped."""
    root, task_root, env = seed(TASK)
    try:
        driver, seen = driver_for(root, env, TASK), []
        stub(driver, {"log_append.py": [1, 0]}, seen)
        quiet(driver.answer_row, "S2 test: ", "same words", what="your answer")
        check_eq("K5: the first write ran at once", len(seen), 1)
        quiet(driver.owed_rows_step)
        check_eq("K5: and again at the drain", len(seen), 2)
        check_eq("K5: two identical rows were written (allowed), never zero", seen[0], seen[1])
    finally:
        harness.cleanup(root)


def k13_recorded_earlier_is_not_owed() -> None:
    """K13 (t-1152 §L-4): a finding the registry already holds under that key (project_decisions.py's own exit code, read as a number) is
    WRITTEN: no owed row at the first try or at the drain, no second run, no question. The exit 3 of any other script, and any other
    non-zero of project_decisions.py, stays a failure (the control)."""
    root, task_root, env = seed(TASK)
    try:
        code = story_run.project_decisions.RECORDED_EARLIER_EXIT
        driver, seen = driver_for(root, env, TASK), []
        stub(driver, {"project_decisions.py": [code]}, seen)
        result, out = quiet(driver.owe_row, "project_decisions.py", "add-finding", what="the finding", stage="S0")
        check_eq("K13: the first run exits `recorded earlier`: nothing owed, one run", (result, driver.state.get("owed_rows") or [], len(seen)), (None, [], 1))
        check_in("K13: one line says it was recorded earlier", "recorded earlier", out)
        driver, seen = driver_for(root, env, TASK), []
        stub(driver, {"project_decisions.py": [2, code]}, seen)
        quiet(driver.owe_row, "project_decisions.py", "add-finding", what="the finding", stage="S0")
        check_eq("K13: a plain refusal (2) is owed", len(on_disk(task_root)["owed_rows"]), 1)
        result, _out = quiet(driver.owed_rows_step)
        check_eq("K13: the drain meets `recorded earlier`: the row leaves, no question", (result, on_disk(task_root)["owed_rows"], len(seen)), (None, [], 2))
        check_eq("K13: ...and nothing is given up", runs(task_root, "rows_given_up"), [])
        driver, seen = driver_for(root, env, TASK), []
        stub(driver, {"log_append.py": [code]}, seen)
        quiet(driver.owe_row, "log_append.py", "--event", "x", what="the line", stage="S0")
        check_eq("K13 control: the same number from another script is a failure, owed", len(on_disk(task_root)["owed_rows"]), 1)
    finally:
        harness.cleanup(root)


def k10_py_trace() -> None:
    """K10 (T): a trace that fails is one `trace_failed` line in driver-runs.jsonl and one printed line, never a raise; the reason is
    mandatory."""
    root, task_root, env = seed(TASK)
    try:
        driver, seen = driver_for(root, env, TASK), []
        stub(driver, {"factory_dashboard.py": [1, 0]}, seen)
        result, out = quiet(driver.py_trace, "factory_dashboard.py", why="no step of the story reads it")
        check_eq("K10: it returns nothing and does not raise", result, None)
        rows = runs(task_root, "trace_failed")
        check_eq("K10: ONE trace_failed row with the script, the exit and the reason",
                 [(r["script"], r["exit"], r["why"]) for r in rows], [("factory_dashboard.py", 1, "no step of the story reads it")])
        check_eq("K10: one printed line", len([l for l in out.splitlines() if l.strip()]), 1)
        quiet(driver.py_trace, "factory_dashboard.py", why="again")
        check_eq("K10: a success writes no row", len(runs(task_root, "trace_failed")), 1)
        for bad in ("", "   "):
            try:
                driver.py_trace("factory_dashboard.py", why=bad)
                raised = False
            except ValueError:
                raised = True
            check(f"K10: an empty reason ({bad!r}) is a ValueError", raised)
        try:
            driver.py_trace("factory_dashboard.py")
            raised = False
        except TypeError:
            raised = True
        check("K10: no reason at all is a TypeError (the argument is keyword-only and required)", raised)
    finally:
        harness.cleanup(root)


def inventory(task_root: Path, urls) -> None:
    (task_root / "work").mkdir(parents=True, exist_ok=True)
    (task_root / "work" / "source-inventory.json").write_text(json.dumps({"sources": [{"source_id": "SRC-1", "materials": {"external_media": {
        "items": [{"url": url, "status": "pending"} for url in urls]}}}]}), encoding="utf-8")


def k11_pasted_material_not_recorded() -> None:
    """K11 (Q1, F-1): of two pasted blocks one fails to record, or no open item can be named for it: the person's own question comes
    back naming what IS recorded and what is not, and `accept-gap` is never called - the answer was material, not a decision. A fence
    that holds no readable block is never an acceptance either."""
    root, task_root, env = seed(TASK)
    try:
        words = "```\nthe first text, for http://a/1\n```\n```\nthe second text\n```"
        inventory(task_root, ["http://a/1", "http://a/2"])
        driver, seen = driver_for(root, env, TASK), []

        def py(script, *args, **kwargs):
            seen.append((script, args))
            return (1, "inspect refused http://a/2") if "http://a/2" in args else (0, "ok")
        driver.py = py
        person, _out = quiet(driver.record_gaps, "", words, ids=["SRC-1"])
        check("K11: the question comes back (a Person)", isinstance(person, story_run.Person), repr(person))
        text = person_text(person)
        check_in("K11: it names what IS recorded", "http://a/1", text)
        check_in("K11: and says what is not (1 of 2)", "1 of the 2", text)
        check_not_in("K11: accept-gap was NOT called", "accept-gap", " ".join(a for s, args in seen for a in args))
        check_eq("K11: the written block was inspected, the failing one tried", [a[a.index("--media-url") + 1] for s, a in seen if "--media-url" in a],
                 ["http://a/1", "http://a/2"])

        # an unmatched block (no open item to name): the same question, no accept-gap
        inventory(task_root, [])
        driver, seen = driver_for(root, env, TASK), []
        driver.py = py
        person, _out = quiet(driver.record_gaps, "", "```\nsome text\n```", ids=["SRC-1"])
        check("K11: a block no open item can be named for is the person's question too", isinstance(person, story_run.Person), repr(person))
        check_not_in("K11: ...and accept-gap is not called", "accept-gap", " ".join(a for s, args in seen for a in args))

        # a fence with no readable block: never an acceptance
        result, _out = quiet(driver.record_gaps, "", "```one line```", ids=["SRC-1"])
        check_eq("K11: a fence no block can be read from returns False (the conductor reads it)", result, False)
        check_not_in("K11: ...and accept-gap is not called", "accept-gap", " ".join(a for s, args in seen for a in args))

        # control: the same call without a fence IS an acceptance
        result, _out = quiet(driver.record_gaps, "", "not needed", ids=["SRC-1"])
        check_eq("K11: control - no fence, the word is the acceptance", result, True)
        check_in("K11: control - accept-gap ran", "accept-gap", " ".join(a for s, args in seen for a in args))
    finally:
        harness.cleanup(root)


def k12_mode_switch_not_recorded() -> None:
    """K12 (Q3, B-3): the mode-switch pass that was not recorded is the person's own question back, `package_question` is KEPT, so the
    next `go on` is the mode switch's again (never the package-copies pass), and that second `go on` records the block."""
    root, task_root, env = seed(TASK)
    try:
        driver, seen = driver_for(root, env, TASK), []
        pending = {"what": "mode", "stage": "S2", "text": "Switch the run mode?"}
        driver.state["package_question"] = dict(pending)
        driver._answer = {"text": "go on", "rel": None}
        answers = {"waiver.py": [1, 0], "log_append.py": []}
        stub(driver, answers, seen)
        person, _out = quiet(driver.take_package_answer, "go on", "", "S2", "")
        check("K12: a refused switch is the person's question back", isinstance(person, story_run.Person), repr(person))
        check_in("K12: it says nothing was switched", "nothing was switched", person_text(person))
        check_eq("K12: the question is KEPT", driver.state.get("package_question"), pending)
        check_eq("K12: no package-copies pass was made", driver.state.get("package_pass"), None)
        check_eq("K12: the person's answer is in the journal either way", [s for s, _a in seen].count("log_append.py"), 1)
        result, _out = quiet(driver.take_package_answer, "go on", "", "S2", "")
        check_eq("K12: the second `go on` records the pass", result, None)
        waivers = [a for s, a in seen if s == "waiver.py"]
        check_eq("K12: ...with the mode-switch block, twice in all", [a[a.index("--block") + 1] for a in waivers], ["mode switch", "mode switch"])
        check_eq("K12: ...and only now the question is popped", driver.state.get("package_question"), None)
    finally:
        harness.cleanup(root)


def py_contract() -> None:
    """B-4 (i), (iii) and F10: `expect` makes the refusal FR-1 shaped and unroutable by a phrase of its own output; its retry carries
    `expect`; a timeout is a failure of `check=True`; without `expect` the text is today's, byte for byte."""
    root, task_root, env = seed(TASK)
    try:
        driver = driver_for(root, env, TASK)
        real = story_run.subprocess.run

        def fake(argv, **kwargs):
            if fake.timeout:
                raise subprocess.TimeoutExpired(argv, kwargs.get("timeout") or 1)
            return subprocess.CompletedProcess(argv, fake.code, stdout=fake.out, stderr="")
        fake.timeout, fake.code, fake.out = False, 3, "the stage already completed; STORY BUDGET"
        story_run.subprocess.run = fake
        try:
            try:
                driver.py("render_case_appendix.py", "a", check=True, expect="work/case-appendix.md rendered")
                refusal = None
            except story_run.Refusal as exc:
                refusal = exc
            check("B-4: check=True with expect raises", refusal is not None)
            check_eq("B-4: the head names the step, the exit, what was expected, the door and the step's own words",
                     refusal.text,
                     "the factory step render_case_appendix.py did not complete (exit 3): expected work/case-appendix.md rendered. "
                     "The door: retry runs the same command; the step's own words: the stage already completed; STORY BUDGET")
            check_eq("F10: the refusal is marked as no known-table row's", getattr(refusal, "known", True), False)
            try:
                refusal.retry()
                again = None
            except story_run.Refusal as exc:
                again = exc
            check("B-4 i: the retry fails through the same contract", again is not None)
            check_eq("B-4 i: ...with `expect` and `known = False` still on it", (getattr(again, "known", True), "expected work/case-appendix.md" in again.text), (False, True))
            fake.out = ""
            try:
                driver.py("x.py", check=True, expect="the product")
            except story_run.Refusal as exc:
                check_in("edge: an empty output says the step said nothing", "the step said nothing", exc.text)
            fake.out = "boom"
            try:
                driver.py("x.py", "a", "b", check=True)
            except story_run.Refusal as exc:
                check_eq("without `expect` the text is today's, byte for byte", exc.text, "x.py a b (exit 3):\nboom")
                check_eq("...and carries no known mark", getattr(exc, "known", True), True)
            fake.timeout = True
            code, out = driver.py("check_delivery.py", "a")
            check_eq("B-4 iii: a timeout without check is still (124, the sentence)", (code, "did not finish within" in out), (124, True))
            try:
                driver.py("check_delivery.py", "a", check=True, expect="the verdict")
                timed = None
            except story_run.Refusal as exc:
                timed = exc
            check("B-4 iii: a timeout under check=True RAISES", timed is not None)
            check_in("B-4 iii: ...naming the timeout and its exit", "exit 124", timed.text)
            check_in("B-4 iii: ...and the sentence about the ceiling", "did not finish within", timed.text)
        finally:
            story_run.subprocess.run = real
    finally:
        harness.cleanup(root)


def block_names_row() -> None:
    """B-2: the block is a row of references/block-names.json whose reader exists, so the loader accepts it."""
    import waiver
    row = waiver.block_name_row(BLOCK, "S3")
    check_eq("B-2: the table names the block, for every stage", row and (row["reader"], row["stages"]), ("driver_conductor:DriverConductor.owed_rows_step", ("*",)))


# --- C1-7b: the gate steps (G), the legitimate no (L), the trace (T), the readiness record (R3), the Halts map --------------------

class Scripts:
    """`subprocess.run` replaced for the scripts in `plan` ONLY (the real `Driver.py` runs over it, so a `check=True` dropped at a site
    is seen): `plan[key]` is a list of `(exit, output)` answered in turn (then `(0, "")`), the key is `script` or `script:<first arg>`;
    the output "TIMEOUT" raises `subprocess.TimeoutExpired` as a ceiling does. Every call is appended to `seen` as `(script, args)`."""

    def __init__(self, plan: dict, seen: list):
        self.queues, self.seen, self.real = {k: list(v) for k, v in plan.items()}, seen, story_run.subprocess.run

    def __enter__(self):
        def fake(argv, **kwargs):
            script, args = Path(str(argv[2])).name, tuple(str(a) for a in argv[3:])
            key = f"{script}:{args[0]}" if args and f"{script}:{args[0]}" in self.queues else script
            if key not in self.queues:
                return self.real(argv, **kwargs)
            self.seen.append((script, args))
            code, out = self.queues[key].pop(0) if self.queues[key] else (0, "")
            if out == "TIMEOUT":
                raise subprocess.TimeoutExpired(argv, kwargs.get("timeout") or 1)
            return subprocess.CompletedProcess(argv, code, stdout=out, stderr="")
        story_run.subprocess.run = fake
        return self

    def __exit__(self, *exc):
        story_run.subprocess.run = self.real


def refusal_of(call, *args, **kwargs):
    """(the Refusal the call raised or None, the printed text)"""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        try:
            call(*args, **kwargs)
            return None, buffer.getvalue()
        except story_run.Refusal as refusal:
            return refusal, buffer.getvalue()


VERDICT_YES = json.dumps({"delivery_verdict": "yes", "delivery_ready": True, "reasons": []})
VERDICT_NO = json.dumps({"delivery_verdict": "no", "delivery_ready": False, "reasons": ["a requirement is not delivered"]})


def k6_render_appendix_is_a_gate() -> None:
    """K6 (G2): `render_case_appendix` exits 1 at S4 -> a Refusal with the head of the contract and the expected product; `retry` runs
    the same command again; exit 0 raises nothing."""
    root, task_root, env = seed(TASK)
    try:
        driver, seen = driver_for(root, env, TASK), []
        with Scripts({"render_case_appendix.py": [(1, "boom"), (0, "ok")]}, seen):
            refusal, _out = refusal_of(driver.render_appendix)
            check("K6: a non-zero exit raises", refusal is not None)
            check_in("K6: the head names the factory step", "the factory step render_case_appendix.py did not complete (exit 1)", refusal.text)
            check_in("K6: ...and what it was expected to leave", "expected work/case-appendix.md rendered from the pinned cases", refusal.text)
            check_eq("K6: ...marked as no known-table row's", refusal.known, False)
            again, _out = refusal_of(refusal.retry)
            check_eq("K6: `retry` runs the same command and passes when it passes", (again, [s for s, _a in seen]),
                     (None, ["render_case_appendix.py", "render_case_appendix.py"]))
            green, _out = refusal_of(driver.render_appendix)
            check_eq("K6 green twin: exit 0 raises nothing", green, None)
    finally:
        harness.cleanup(root)


def k7_g_battery_is_never_a_pass() -> None:
    """K7 (F10, §3.1): a G step's output holds, in turn, each phrase of a known-refusals row, nothing at all, a timeout and an argparse
    exit: the step is NOT passed - `route_known` gives None (the table never reads a G step) and the refusal reaches the conductor."""
    root, task_root, env = seed(TASK)
    try:
        driver = driver_for(root, env, TASK)
        reached = []
        driver.conductor_round = lambda refusal, stage, **kw: (reached.append(refusal.text), "continue")[1]
        driver.window_round_gate = lambda refusal, stage: None
        cases = [(1, "the stage already completed"), (1, "STORY BUDGET: 9 of 8"), (1, "StateConflict: expected_revision 4"),
                 (1, "event committed; recover"), (1, "this stands in front of gate A"), (1, ""), (2, "usage: render_case_appendix.py")]
        for code, said in cases:
            seen = []
            with Scripts({"render_case_appendix.py": [(code, said)]}, seen):
                refusal, _out = refusal_of(driver.render_appendix)
            check(f"K7: exit {code} / {said[:24]!r} is a refusal", refusal is not None)
            check_eq(f"K7: ...and the table does not route it ({said[:24]!r})", story_run.route_known(refusal), None)
            before = len(reached)
            driver.handle_refusal(refusal)
            check_eq(f"K7: ...it reaches the conductor ({said[:24]!r})", len(reached), before + 1)
        control = story_run.Refusal("the stage already completed")
        check("K7 control: the same phrase WITHOUT the mark is routed by the table", story_run.route_known(control) is not None)
        seen = []
        with Scripts({"check_traceability.py": [(0, "")], "ledger.py": [(0, "")], "check_delivery.py": [(124, "TIMEOUT")]}, seen):
            refusal, _out = refusal_of(driver.stage_S8)
        check("K7: a timeout (124) of the S8 verdict check is a refusal, never a legitimate no", refusal is not None and refusal.known is False)
        if refusal is not None:
            check_in("K7: ...naming the exit", "exit 124", refusal.text)
            check_eq("K7: ...and the table does not route it", story_run.route_known(refusal), None)
    finally:
        harness.cleanup(root)


def s8_driver(root, env, plan: dict):
    """A Driver whose S8 role and report rebuild are stubs that record; returns (driver, seen, ran)."""
    driver, seen, ran = driver_for(root, env, TASK), [], []
    driver.run_role = lambda *a, **k: ran.append(a) or ("", None)
    driver.rebuild_report = lambda *a, **k: True
    return driver, seen, ran


def k8_g_per_site() -> None:
    """K8 (G per site): the readiness `--write` (G1), the S6 running record (G3), the ledger at S8 (G4) and `retro_numbers` (G5) each
    raise on a non-zero exit, with the contract's head and their own product; the green twin (exit 0) raises nothing."""
    root, task_root, env = seed(TASK)
    try:
        # G4: the ledger, in the S8 loop - the failing iteration raises, the role is NOT started, `retry` runs the WHOLE step
        driver, seen, ran = s8_driver(root, env, {})
        plan = {"check_traceability.py": [(1, "gaps")], "ledger.py": [(1, "no such directory"), (0, "")], "check_delivery.py": [(1, VERDICT_NO)]}
        with Scripts(plan, seen):
            refusal, _out = refusal_of(driver.stage_S8)
            check("K8 G4: ledger.py exit 1 raises", refusal is not None)
            check_in("K8 G4: ...with its product", "expected work/ledger.json and work/ledger.md written", refusal.text)
            check_eq("K8 G4: ...before check_delivery and before the scribe", ([s for s, _a in seen], ran), (["check_traceability.py", "ledger.py"], []))
            check_eq("K8 G4 (E1): `retry` is the WHOLE step", refusal.retry, driver.stage_S8)
            plan["check_traceability.py"].append((1, "gaps"))
            again, _out = refusal_of(refusal.retry)
            check_eq("K8 G4: the whole step again passes: the scribe runs once", (again, len(ran)), (None, 1))
        # G5: retro_numbers before the close of S9 (numbers mode); T6: the estimate never raises and never blocks the close
        driver, seen = driver_for(root, env, TASK), []
        closed = []
        pipeline = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))
        pipeline["retro_mode"] = "numbers"
        (task_root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        driver.after_gate_B = lambda: None
        driver.rebuild_report = lambda *a, **k: True
        driver.state["retro_asked"] = True
        driver.record_close = lambda *a, **k: closed.append(a)
        with Scripts({"retro_numbers.py:--task": [(1, "boom")], "retro_numbers.py": []}, seen):
            refusal, _out = refusal_of(driver.stage_S9)
            check("K8 G5: retro_numbers exit 1 raises", refusal is not None)
            check_in("K8 G5: ...with its product", "expected work/retro-numbers.md and work/retro-numbers.json written", refusal.text)
            check_eq("K8 G5 (E3): ...and S9 is NOT recorded closed over it", closed, [])
        seen = []
        with Scripts({"retro_numbers.py": [(0, ""), (0, "")], "estimate_record.py": [(1, "no facts")]}, seen):
            refusal, out = refusal_of(driver.stage_S9)
            check_eq("K8 G5 green twin + T6: the estimate's failure raises nothing", refusal, None)
            check_eq("K8 T6 (E3): ...S9 is recorded closed", [a[0] for a in closed], ["s9.numbers"])
            check_eq("K8 T6: ...one trace_failed line carries the reason", [r["script"] for r in runs(task_root, "trace_failed")], ["estimate_record.py"])
            check_in("K8 T6: ...and the reason is the invariant", "no decision of this story reads it", runs(task_root, "trace_failed")[0]["why"])
        # W15: the skip words are an owed row when the journal refuses them
        pipeline["retro_mode"] = "skip"
        (task_root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        closed.clear()
        with Scripts({"log_append.py": [(2, "refused")]}, []):
            refusal, _out = refusal_of(driver.stage_S9)
        check_eq("K8 W15: a refused skip row is owed, never lost, and S9 still closes", (refusal, len(on_disk(task_root)["owed_rows"]), len(closed)), (None, 1, 1))
        # G3: the S6 running record before the dispatch
        driver, seen, ran = s8_driver(root, env, {})
        import controller as CT

        class Fake:
            def __init__(self, *a, **k):
                pass

            def state(self):
                return {"dispatches": {}}

            def prepare(self, request):
                return {"dispatch_request": {}}

            def apply(self, name, request):
                return {}
        real_controller, CT.Controller = CT.Controller, Fake
        try:
            driver.manual_gate_note = lambda: None
            driver.manual_plan = lambda cases, skip=(): {"refused": [], "blocks": [["TC-1"]]}
            driver.stand_login_gate = lambda plan: None
            driver.manual_request_paths = lambda block: []
            driver.role_lines = lambda *a: []
            with Scripts({"stage_done.py": [(1, "refused"), (0, "")]}, seen):
                refusal, _out = refusal_of(driver.run_manual_block, ["TC-1"])
                check("K8 G3: the S6 running record's exit 1 raises", refusal is not None)
                check_in("K8 G3: ...with its product", "expected S6 recorded running", refusal.text)
                check_eq("K8 G3: ...and the runner is NOT started over it", ran, [])
                green, _out = refusal_of(driver.run_manual_block, ["TC-1"])
                check_eq("K8 G3 green twin: exit 0 raises nothing and the runner starts", (green, len(ran)), (None, 1))
            # F-2 (fix round, B-4 ii): the retry of a refused running record CONTINUES into the role - the manual-block instructions
            # reach it - and never leaves the registered dispatch to `wait_existing_job`, which would start it without them
            calls, waited = [], []
            driver.run_role = lambda *a, **k: calls.append((a, k)) or ("", None)
            driver._act_wait_existing_job = lambda action: waited.append(action)
            driver.manual_request_paths = lambda block: ["req/TC-1.json"]
            with Scripts({"stage_done.py": [(1, "refused"), (0, "")]}, seen):
                refusal, _out = refusal_of(driver.run_manual_block, ["TC-1"])
                check_eq("K8 G3 (B-4 ii): the refused record has not started the runner", (refusal is not None, calls), (True, []))
                again, _out = refusal_of(refusal.retry)
            check_eq("K8 G3 (B-4 ii): a retry that passes raises nothing and runs the role ONCE", (again, len(calls)), (None, 1))
            if calls:
                args, kwargs = calls[0]
                check_eq("K8 G3 (B-4 ii): ...the S6 qa-runner, over the block, with its dispatch id", (args, kwargs["scope"], kwargs["rework"]["id"]),
                         (("S6", "qa-runner"), ["TC-1"], "S6-qa-runner-1"))
                check_in("K8 G3 (B-4 ii): ...with the manual-block instructions", "Execution kind: manual", " ".join(kwargs["extra"]))
                check_in("K8 G3 (B-4 ii): ...and the prepared request paths", "req/TC-1.json", " ".join(kwargs["extra"]))
            check_eq("K8 G3 (B-4 ii): ...and the registered dispatch is NOT left for wait_existing_job", waited, [])
            calls.clear()
            with Scripts({"stage_done.py": [(1, "refused"), (1, "refused again")]}, seen):
                refusal, _out = refusal_of(driver.run_manual_block, ["TC-1"])
                second, _out = refusal_of(refusal.retry)
            check_eq("K8 G3 (B-4 ii): a retry that fails raises the same G refusal, with a retry of its own, and the runner is not started",
                     (second is not None and "expected S6 recorded running" in second.text, second is not None and callable(second.retry), calls),
                     (True, True, []))
        finally:
            CT.Controller = real_controller
        # G1: the readiness `--write` of S0, and B-4 ii: the retry CONTINUES the rest of S0
        driver, seen = s0_driver(root, env)
        plan = {"readiness.py:--write": [(2, "usage")], "readiness.py:--require": [(0, READINESS_OK)], "stage_done.py": [(0, "")]}
        with Scripts(plan, seen):
            refusal, _out = refusal_of(driver.s0)
            check("K8 G1: readiness --write exit 2 raises", refusal is not None)
            check_in("K8 G1: ...with its product", "expected state/readiness.json rewritten", refusal.text)
            check_eq("K8 G1: ...and nothing after it ran", [s for s, _a in seen if s != "environment_selection.py"], ["readiness.py"])
            again, _out = refusal_of(refusal.retry)
            later = [s for s, _a in seen if s != "environment_selection.py"]
            check_eq("B-4 ii: a G1 retry that passes CONTINUES the rest of S0: the requirement check, the S0 record", (again, later),
                     (None, ["readiness.py", "readiness.py", "readiness.py", "stage_done.py"]))
            check("B-4 ii: ...and S0 was initialized and its pipeline written", (task_root / "pipeline.json").is_file() and driver.initialized)
    finally:
        harness.cleanup(root)


READINESS_OK = json.dumps({"capabilities": {name: {"status": "ok", "owner": "", "note": ""} for name in ("ticket_adapter", "test_repo", "vcs", "config_schema")}})


def s0_driver(root, env):
    """A Driver whose S0 steps BEFORE the readiness check are stubs (the ticket, the launch, the sources), so `s0()` reaches it."""
    driver, seen = driver_for(root, env, TASK), []
    driver.initialized = False
    driver.s0_note_launch = lambda: None
    driver.s0_read_word = lambda: None
    driver.s0_flags = lambda: {"mr": None, "branch": None, "commit": None, "env": None, "ticket_file": None}
    driver.s0_source_list = lambda flags: None
    driver.s0_ticket = lambda ticket_file: ({"key": TASK, "parent": None}, "{}", "tracker", True)
    driver.s0_criteria = lambda *a: None
    driver.write_snapshot = lambda out: None

    def initialize():
        driver.initialized = True
    driver.initialize = initialize
    return driver, seen


def k9_traceability_no_is_not_a_gate() -> None:
    """K9 (L1, E2): `check_traceability` exits 1 - gaps found, a correct "no" - and the S8 role still runs: no Refusal, no conductor call. A
    legitimate `no` of the verdict check is read from the record, never from the exit code."""
    root, task_root, env = seed(TASK)
    try:
        driver, seen, ran = s8_driver(root, env, {})
        plan = {"check_traceability.py": [(1, "REQUIREMENTS WITHOUT A TERMINAL OUTCOME: R1")], "ledger.py": [(0, "")], "check_delivery.py": [(1, VERDICT_NO)]}
        with Scripts(plan, seen):
            refusal, out = refusal_of(driver.stage_S8)
        check_eq("K9: traceability 1 and a `no` verdict (exit 1) raise nothing and the scribe runs", (refusal, len(ran)), (None, 1))
        check_in("K9: ...the verdict's word is printed", "the word it printed: no", out)
        for label, entry in (("a crash (exit 1, no record)", (1, "Traceback (most recent call last)")), ("exit 2", (2, "usage")),
                             ("a record with no word", (0, json.dumps({"reasons": []})))):
            driver, seen, ran = s8_driver(root, env, {})
            with Scripts({"check_traceability.py": [(0, "")], "ledger.py": [(0, "")], "check_delivery.py": [entry]}, seen):
                refusal, _out = refusal_of(driver.stage_S8)
            check_eq(f"K9: L2 {label} is the factory's own refusal and the scribe does NOT run", (refusal is not None and refusal.known, ran), (False, []))
        driver, seen, ran = s8_driver(root, env, {})
        with Scripts({"check_traceability.py": [(0, "")], "ledger.py": [(0, "")], "check_delivery.py": [(0, VERDICT_YES)]}, seen):
            refusal, _out = refusal_of(driver.stage_S8)
        check_eq("K9 green twin: the yes verdict (exit 0) passes", (refusal, len(ran)), (None, 1))
    finally:
        harness.cleanup(root)


def k17_one_verdict_parse() -> None:
    """K17 (fix round F-1, FR-14, AR-13): the three reads of a script's printed record - S0's capabilities (`s0_rest`), S8's verdict
    (`stage_S8`) and gate B's verdict (`delivery_check_word`) - go through the ONE `json_record`; a site that parses inline is red. The
    contract of the verdict read: a readable record gives its word (exit 1 with a `no` is the word `no`, E2); no record, an exit outside
    {0, 1}, a timeout or an unreadable record gives none."""
    check_eq("K17: the record and the text after it", story_run.json_record('x {"a": 1}\nWARN y'), ({"a": 1}, "WARN y"))
    check_eq("K17: no record is None and the text whole", story_run.json_record("no record here"), (None, "no record here"))
    check_eq("K17: an unreadable record is None", story_run.json_record('{"a": ')[0], None)
    check_eq("K17: nothing printed is None", story_run.json_record(""), (None, ""))
    root, task_root, env = seed(TASK)
    real = story_run.json_record
    try:
        driver = driver_for(root, env, TASK)
        for label, entry, want in (("exit 1 with a `no`", (1, VERDICT_NO), "no"), ("exit 0 with a `yes`", (0, VERDICT_YES), "yes"),
                                   ("exit 2 with a readable record", (2, VERDICT_YES), None), ("a timeout", (124, "TIMEOUT"), None),
                                   ("exit 1, no record", (1, "Traceback"), None), ("exit 0, an unreadable record", (0, '{"delivery_verdict": '), None),
                                   ("a record with a word of no row", (0, json.dumps({"delivery_verdict": "maybe"})), None)):
            with Scripts({"check_delivery.py": [entry]}, []):
                got = driver.delivery_record("qa-factory/artifacts/QA-9")
            check_eq(f"K17: the verdict read, {label}", got[2], want)
        seen_by_parse = []
        story_run.json_record = lambda out: (seen_by_parse.append(out), real(out))[1]
        driver, seen, ran = s8_driver(root, env, {})
        with Scripts({"check_traceability.py": [(0, "")], "ledger.py": [(0, "")], "check_delivery.py": [(1, VERDICT_NO)]}, seen):
            refusal, _out = refusal_of(driver.stage_S8)
        check_eq("K17: stage_S8 reads the verdict through json_record, once", (refusal, [VERDICT_NO in text for text in seen_by_parse]), (None, [True]))
        seen_by_parse.clear()
        with Scripts({"check_delivery.py": [(1, VERDICT_NO)]}, []), redirect_stdout(io.StringIO()):
            word = driver.delivery_check_word("qa-factory/artifacts/QA-9")
        check_eq("K17: delivery_check_word reads it through json_record, once, and returns the word", (word, [VERDICT_NO in text for text in seen_by_parse]), ("no", [True]))
        seen_by_parse.clear()
        driver, seen = s0_driver(root, env)
        driver._s0_passed = []
        with Scripts({"readiness.py": [(0, READINESS_OK)], "stage_done.py": [(0, "")]}, seen), redirect_stdout(io.StringIO()):
            driver.s0_rest(None, True, [], None, "", False, [])
        check_eq("K17: s0_rest reads the capabilities through json_record, once", [READINESS_OK in text for text in seen_by_parse], [True])
    finally:
        story_run.json_record = real
        harness.cleanup(root)


HALTS = {      # references/halts.md `## Halts` (first cell) -> (how the driver carries it, the Driver members that carry it): t-1152 §4, F7 (a)
    "`readiness.py --require` exits 1": ("V", ["s0_rest", "s0_stop"]),
    "`config.schema_version` mismatch": ("V", ["s0_rest"]),
    "`qa-scout ... no diff`": ("V", ["halt_text"]),
    "`qa-scout ... requirement/code conflict`": ("V", ["run_role", "_unread_halt_or_review"]),
    "`qa-scout ... <capability> unavailable`": ("V", ["run_role", "s1_person"]),
    "`qa-requirements-tester ... blocked`": ("V", ["run_role"]),
    "Dirty working tree at S5": ("remains", []),
    "`qa-automator ... not on story branch`": ("remains", []),
    "`qa-automator`/`qa-code-critic ... repair cap reached`": ("V", ["repair_limit_gate", "repair_limit_person"]),
    "`qa-case-critic ... round cap`": ("remains", ["s4_after_critic"]),
    "`qa-automator ... contradicts_requirement`": ("remains", ["failures_to_triage"]),
    "`stage_done.py` exits 3, `STORY BUDGET:`": ("V", ["handle_refusal", "no_move"]),
    "`qa-runner ... env_blocked`": ("V", ["take_stand_gap_answers", "environment_job"]),
    "`qa-failure-analyst ... cannot triage`": ("V", ["run_role"]),
    "`env_probe.py` exits 1": ("V", ["stand_check"]),
    "`run_suite: executor_unavailable`": ("V", ["handle_refusal"]),
    "`qa-doc-scribe ... cannot assemble gate B`": ("V", ["run_role"]),
    "A `stage_guard` denial on a dispatch or a command": ("remains", ["handle_refusal"]),
}


def halts_first_cells(text: str) -> list:
    """The first cell of every row of the table under the `## Halts` heading (located by the heading, not by a line number)."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "## Halts")
    rows = []
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        if line.startswith("|") and not line.startswith("|---") and not line.startswith("| Digest or condition"):
            rows.append(line.strip().strip("|").split("|")[0].strip())
    return rows


def t_traces_of_the_stage_functions() -> None:
    """T2, T4, T5 (C1-7b): a refused `defect_found` row of the driver's own is said on stderr WITH the rejection's words and journalled as a
    `trace_failed` row; the repair-budget and the tooling-finding traces never raise either. The trace is the invariant, not a stop."""
    root, task_root, env = seed(TASK)
    try:
        driver, seen = driver_for(root, env, TASK), []
        err = io.StringIO()
        with Scripts({"log_append.py": [(1, "JOURNAL: record rejected")]}, seen), contextlib.redirect_stderr(err):
            driver.file_defect("", "owner: factory - x")
        check_in("T2: the rejection's words are on stderr", "JOURNAL: record rejected", err.getvalue())
        rows = runs(task_root, "trace_failed")
        check_eq("T2: ONE trace_failed row names the script and the reason", [(r["script"], "cannot file its own failure" in r["why"]) for r in rows],
                 [("log_append.py", True)])
        driver.repair_budget = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no count"))
        with Scripts({"log_append.py": [(1, "refused")]}, seen):
            result, _out = quiet(driver.budget_or_none, "S5", "qa-automator", ["TC-1"])
        check_eq("T4: an unreadable budget closes with None and a refused defect row raises nothing", result, None)
        check_eq("T4: ...and the refusal is a trace_failed row with its reason", [r["script"] for r in runs(task_root, "trace_failed")], ["log_append.py", "log_append.py"])
    finally:
        harness.cleanup(root)


def k14_halts_map() -> None:
    """K14 (F7 a): every first cell of `references/halts.md`'s `## Halts` table is a key of the map above, every mapped Driver member exists,
    and a row added to a COPY of halts.md with no map entry is red. The map is data: halts.md itself is not edited."""
    skill = Path(story_run.__file__).resolve().parent.parent / "references" / "halts.md"
    text = skill.read_text(encoding="utf-8")
    cells = halts_first_cells(text)
    check_eq("K14: the table has its 18 rows", len(cells), 18)
    check_eq("K14: every first cell is a key of the map", [c for c in cells if c not in HALTS], [])
    check_eq("K14: ...and every key of the map is a row of the table", [k for k in HALTS if k not in cells], [])
    missing = [f"{key}: {name}" for key, (_how, names) in HALTS.items() for name in names if not hasattr(story_run.Driver, name)]
    check_eq("K14: every mapped Driver member exists", missing, [])
    check_eq("K14: every verdict is V or remains", sorted({how for how, _n in HALTS.values()}), ["V", "remains"])
    added = text.rstrip("\n") + "\n| A new halt condition | x | y |\n"
    check_eq("K14 negative control: a row added with no map entry is found", [c for c in halts_first_cells(added) if c not in HALTS],
             ["A new halt condition"])


def k16_readiness_record() -> None:
    """K16 (R3 / F6 a; the spec's table calls it K13): the required capabilities are read from `readiness.py --require --json`. A
    `missing` capability -> the person's S0 question; none missing -> go on; no record, an exit outside {0, 1}, or an exit 1 that names
    nothing missing -> the factory's own G refusal, never `s0_stop`, never a pass."""
    root, task_root, env = seed(TASK)
    try:
        def caps(**statuses):
            return json.dumps({"capabilities": {name: {"status": statuses.get(name, "ok"), "owner": "user", "note": f"{name} note"}
                                                for name in ("ticket_adapter", "test_repo", "vcs", "config_schema")}})

        def rest(plan: dict):
            driver, seen = s0_driver(root, env)
            driver._s0_passed = []
            buffer = io.StringIO()
            with Scripts(dict(plan, **{"stage_done.py": [(0, "")]}), seen), redirect_stdout(buffer):
                try:
                    driver.s0_rest(None, True, [], None, "", False, [])
                    raised = None
                except (story_run.Person, story_run.Refusal) as exc:
                    raised = exc
            return driver, raised

        driver, raised = rest({"readiness.py": [(1, caps(vcs="missing") + "\nTHIS STORY CANNOT START")]})
        check("K16: a missing capability is the person's question", isinstance(raised, story_run.Person), repr(raised))
        check_eq("K16: ...the readiness block, and the report names the capability", (driver.state.get("s0_block"), "vcs: missing" in driver.state["s0_ask"]["details"]), ("readiness", True))
        driver, raised = rest({"readiness.py": [(0, caps() + "\nWARN something")]})
        check_eq("K16: none missing (exit 0) goes on: the story's S0 is recorded and initialized", (raised, driver.initialized), (None, True))
        check_in("K16: ...the WARN line after the record becomes a warning", "WARN something", json.dumps(json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))))
        for label, entry in (("exit 2 with no record", (2, "usage: readiness.py")), ("exit 0 with nothing printed", (0, "")),
                             ("exit 1 with no record (a crash)", (1, "Traceback (most recent call last)")),
                             ("exit 1 with a record that names nothing missing", (1, caps())), ("exit 3 with a record", (3, caps()))):
            driver, raised = rest({"readiness.py": [entry]})
            check(f"K16: {label} is the factory's own refusal", isinstance(raised, story_run.Refusal) and raised.known is False, repr(raised))
            check_eq(f"K16: ...never the person's question, never a pass ({label})", (driver.state.get("s0_block"), driver.initialized), (None, False))
            if isinstance(raised, story_run.Refusal):
                check_in(f"K16: ...naming the step and its product ({label})", "the factory step readiness.py did not complete", raised.text)
    finally:
        harness.cleanup(root)


# --- C1-7c: the tail over other owners' sites (O1-O6) and the stubs of `py` (Q-3) -------------------------------------------------

HALT_DIGEST = "qa-test-strategist S3 all · halt\nTS-14 · unresolved · the size limit is in neither the ticket nor the code\n"
HALT_DISPATCH = "S3-qa-test-strategist-1"


def halt_driver(root, env, ran: list):
    """A Driver whose role is a stub that HALTS (the loop_b `halt_texts_are_words` rig, with the `is_error` field a real result carries):
    `run_claude` records each launch in `ran`; `stage_done.py` and the rest run for real under `Scripts`."""
    driver = driver_for(root, env, TASK)
    driver.step = lambda *a, **k: ("dispatched S3-qa-test-strategist-1 (revision 4)\n--- Agent prompt, verbatim ---\n"
                                   "You are qa-test-strategist.\n--- the moment the Agent call returns ---\n")
    driver.system_file = lambda *a, **k: ""
    driver.run_claude = lambda *a, **k: ran.append(k) or {"result": HALT_DIGEST, "session_id": "", "stderr": "", "total_cost_usd": 0.0,
                                                           "is_error": False}
    driver.handoff = lambda role, stage, dispatch, result: HALT_DIGEST
    return driver


def refusal_only(call, *args, **kwargs):
    """(the Refusal the call raised or None, the printed text): a role's Person that escapes because the gate under test did not raise is
    `None` here, so the key FAILS on `refusal is not None` and does not crash (the mutation table reads FAIL lines)."""
    try:
        return refusal_of(call, *args, **kwargs)
    except story_run.Person:
        return None, ""


def k18_halt_record_is_a_trace() -> None:
    """K18 (O1 `run_role`, O3 `_finish_saved_result`; kind T as T1; E-c1): the `halted` stage record written right before the halt's
    question is a TRACE. A refused write is ONE `trace_failed` row carrying the invariant (`HALT_RECORD_WHY`), the person is asked about
    the halt all the same, and the role is NOT run again for it. The green twin (exit 0) writes no row."""
    root, task_root, env = seed(TASK)
    try:
        for label, call in (("O1 run_role", lambda d: d.run_role("S3", "qa-test-strategist")),
                            ("O3 _finish_saved_result", lambda d: d._finish_saved_result({"result": HALT_DIGEST}, "qa-test-strategist", "S3",
                                                                                         HALT_DISPATCH, {}))):
            ran, seen = [], []
            driver = halt_driver(root, env, ran)
            before = len(runs(task_root, "trace_failed"))
            with Scripts({"stage_done.py": [(1, "the pipeline is locked")]}, seen):
                person, _out = quiet(call, driver)
            check_eq(f"K18 {label}: the person is asked about the halt all the same", (getattr(person, "kind", None), person.stage if hasattr(person, "stage") else None),
                     ("halt", "S3"))
            rows = runs(task_root, "trace_failed")[before:]
            check_eq(f"K18 {label}: ONE trace_failed row with the script and the exit", [(r["script"], r["exit"]) for r in rows], [("stage_done.py", 1)])
            check_eq(f"K18 {label}: ...whose reason is the invariant", [r["why"] for r in rows], [story_run.HALT_RECORD_WHY])
            check_eq(f"K18 {label}: the record was tried once, and the role was not run again for it",
                     ([a[0] for a in seen].count("stage_done.py"), len(ran)), (1, 1 if label.startswith("O1") else 0))
            ran2, seen2 = [], []
            driver = halt_driver(root, env, ran2)
            before = len(runs(task_root, "trace_failed"))
            with Scripts({"stage_done.py": [(0, "")]}, seen2):
                person, _out = quiet(call, driver)
            check_eq(f"K18 {label} green twin: exit 0 writes no trace row and still asks", (len(runs(task_root, "trace_failed")) - before, getattr(person, "kind", None)),
                     (0, "halt"))
        check("K18: the invariant text is not empty and names the trace", "journalled as trace_failed" in story_run.HALT_RECORD_WHY)
    finally:
        harness.cleanup(root)


def k19_resume_record_is_a_gate() -> None:
    """K19 (O2 `resume_role`; kind G as G3; E-c2): the `running` record before the role goes on. A non-zero exit is the factory's own
    refusal (named step, what was expected, the dispatch id), the role is NOT resumed over it, the person's words stay in `pending_words`,
    and `retry` is THIS resume (record, then the same run) - the registered running dispatch is run once, never a second time behind the
    refusal. The adversarial outputs of K7 do not route it."""
    root, task_root, env = seed(TASK)
    try:
        for tail in ("already completed", "STORY BUDGET: 9 of 5", "expected_revision 4", "", "TIMEOUT"):
            ran, seen = [], []
            driver = halt_driver(root, env, ran)
            driver.state["sessions"] = {HALT_DISPATCH: "sess-1"}
            driver.state["pending_words"] = {HALT_DISPATCH: "go on"}
            with Scripts({"stage_done.py": [(1, tail), (0, "")]}, seen):
                refusal, _out = refusal_only(driver.resume_role, "S3", "qa-test-strategist", HALT_DISPATCH, "go on")
                label = tail or "an empty output"
                check(f"K19: stage_done exit 1 with {label!r} raises", refusal is not None)
                if refusal is None:
                    continue
                check_in(f"K19: ...naming the step and what it must leave behind ({label!r})",
                         "the factory step stage_done.py did not complete", refusal.text)
                check_in(f"K19 (E-c8): ...and the dispatch, in the text AND in the field ({label!r})",
                         f"expected S3 recorded running for the dispatch {HALT_DISPATCH}", refusal.text)
                check_eq(f"K19: ...the field ({label!r})", (refusal.dispatch, refusal.known, story_run.route_known(refusal)), (HALT_DISPATCH, False, None))
                check_eq(f"K19: the role is NOT resumed over it, and the person's words are kept ({label!r})",
                         (ran, driver.state["pending_words"]), ([], {HALT_DISPATCH: "go on"}))
                person, _out = quiet(refusal.retry)
                check_eq(f"K19: `retry` is this resume: the record, then the role ONCE ({label!r})",
                         (getattr(person, "kind", None), len(ran), [a[0] for a in seen].count("stage_done.py")), ("halt", 1, 2))
        # a retry that fails raises the same refusal, with a retry of its own, and the role is still not run
        ran, seen = [], []
        driver = halt_driver(root, env, ran)
        driver.state["sessions"] = {HALT_DISPATCH: "sess-1"}
        driver.state["pending_words"] = {HALT_DISPATCH: "go on"}
        with Scripts({"stage_done.py": [(1, "refused"), (1, "refused again")]}, seen):
            refusal, _out = refusal_only(driver.resume_role, "S3", "qa-test-strategist", HALT_DISPATCH, "go on")
            second, _out = refusal_of(refusal.retry) if refusal is not None else (None, "")
        check_eq("K19: a retry that fails is the same G refusal, with a retry of its own, and the role is not run",
                 (second is not None and "expected S3 recorded running" in second.text, second is not None and callable(second.retry), ran),
                 (True, True, []))
        # the green twin: exit 0 raises nothing before the role, which is resumed once
        ran, seen = [], []
        driver = halt_driver(root, env, ran)
        driver.state["sessions"] = {HALT_DISPATCH: "sess-1"}
        driver.state["pending_words"] = {HALT_DISPATCH: "go on"}
        with Scripts({"stage_done.py": [(0, "")]}, seen):
            person, _out = quiet(driver.resume_role, "S3", "qa-test-strategist", HALT_DISPATCH, "go on")
        check_eq("K19 green twin: exit 0 resumes the role once", (getattr(person, "kind", None), len(ran)), ("halt", 1))
        # B-1 (t-1252): later work of a stage the controller has already COMPLETED (a rework, a repair) is resumed WITHOUT the record -
        # the REAL `stage_done.py` refuses `--status running` there by design ("already accepted by the controller"), so a record would
        # be a refusal no retry can cure. Real controller, real stage_done (the seeded story: S0 is completed); only the role is a stub.
        from controller import Controller
        check_eq("K19 B-1 premise: the controller has S0 completed", Controller(task_root).state()["stages"]["S0"]["status"], "completed")
        pipeline_before = (task_root / "pipeline.json").read_text(encoding="utf-8")
        rework = "S0-rework-1"
        ran = []
        driver = halt_driver(root, env, ran)
        driver.state["sessions"] = {rework: "sess-1"}
        driver.state["pending_words"] = {rework: "go on"}
        refusal, _out = refusal_only(driver.resume_role, "S0", "qa-scout", rework, "go on")
        check_eq("K19 B-1: the resume of a completed stage's later work raises no refusal and the role goes on ONCE", (refusal, len(ran)), (None, 1))
        check_eq("K19 B-1: ...and the stage record was not touched (nothing written, nothing lowered)",
                 (task_root / "pipeline.json").read_text(encoding="utf-8"), pipeline_before)
    finally:
        harness.cleanup(root)


def k23_the_refused_resume_is_found_again() -> None:
    """K23 (E-c8, the CX1-14 rule "a running record is never dropped"): after the O2 refusal and a conductor `continue` (no retry), the
    next `where` -> `_act_wait_existing_job` finds the dispatch by the id the refusal carried, still has the person's words, and resumes
    it: the role runs once, with the record written first."""
    root, task_root, env = seed(TASK)
    try:
        ran, seen = [], []
        driver = halt_driver(root, env, ran)
        driver.state["sessions"] = {HALT_DISPATCH: "sess-1"}
        driver.state["pending_words"] = {HALT_DISPATCH: "go on"}
        driver.controller_state = lambda: {"dispatches": {HALT_DISPATCH: {"stage": "S3", "role": "qa-test-strategist", "scope": []}}}
        driver.completion_for = lambda *a: None
        with Scripts({"stage_done.py": [(1, "locked"), (0, "")]}, seen):
            refusal, _out = refusal_only(driver.resume_role, "S3", "qa-test-strategist", HALT_DISPATCH, "go on")
            found = refusal.dispatch if refusal is not None else ""
            check_eq("K23: the refusal names the record by id (field and text)", (found, found in refusal.text if refusal else False), (HALT_DISPATCH, True))
            person, _out = quiet(driver._act_wait_existing_job, {"dispatch_id": found})
        check_eq("K23: the next entry finds it by that id and resumes it ONCE (the words were kept)", (getattr(person, "kind", None), len(ran), person.dispatch if hasattr(person, "dispatch") else None),
                 ("halt", 1, HALT_DISPATCH))
    finally:
        harness.cleanup(root)


def k20_relaunch_record_is_a_gate() -> None:
    """K20 (O4 `_act_relaunch`; kind G as G3; E-c2): the `running` record after the controller registered the packet. A non-zero exit is the
    factory's own refusal naming the relaunched dispatch; the role is NOT started; the packet is registered ONCE (`retry` never registers it
    again); `retry` is record-then-role, so the registered dispatch is run once WITH the relaunch lines. A rework (`rework_of`) writes no
    running record at all."""
    root, task_root, env = seed(TASK)
    try:
        def rig(request: dict):
            registered, started, seen = [], [], []
            driver = driver_for(root, env, TASK)
            driver.controller = lambda operation, input_data=None, **k: registered.append(operation) or {}
            driver.controller_state = lambda: {"dispatches": {}}
            driver.run_role = lambda *a, **k: started.append((a, k)) or ("", None)
            driver.completion_for = lambda *a: None
            driver.role_lines = lambda *a: ["the relaunch line"]
            driver.relaunch_reason = lambda request, action: "relaunched"
            action = {"stage": "S3", "role": "qa-test-strategist", "dispatch_request": request}
            return driver, action, registered, started, seen
        request = {"id": "S3-qa-test-strategist-2", "stage": "S3", "role": "qa-test-strategist", "scope": ["TC-1"]}
        driver, action, registered, started, seen = rig(request)
        with Scripts({"stage_done.py": [(1, "already completed"), (0, "")]}, seen):
            refusal, _out = refusal_of(driver._act_relaunch, action)
            check("K20: stage_done exit 1 raises", refusal is not None)
            if refusal is not None:
                check_in("K20: ...naming the step and the relaunched dispatch", "expected S3 recorded running for the relaunched dispatch S3-qa-test-strategist-2", refusal.text)
                check_eq("K20: ...the field, the mark, and no known-table row", (refusal.dispatch, refusal.known, story_run.route_known(refusal)),
                         ("S3-qa-test-strategist-2", False, None))
                check_eq("K20: the packet was registered once and the role is NOT started", (registered, started), (["dispatch"], []))
                again, _out = refusal_of(refusal.retry)
                check_eq("K20: `retry` passes and runs the role ONCE, with the relaunch lines; the packet is not registered again",
                         (again, registered, len(started), started[0][1]["extra"] if started else None, started[0][1]["rework"]["id"] if started else None),
                         (None, ["dispatch"], 1, ["the relaunch line"], "S3-qa-test-strategist-2"))
        driver, action, registered, started, seen = rig(request)
        with Scripts({"stage_done.py": [(1, "refused"), (1, "refused again")]}, seen):
            refusal, _out = refusal_of(driver._act_relaunch, action)
            second, _out = refusal_of(refusal.retry) if refusal is not None else (None, "")
        check_eq("K20: a retry that fails is the same G refusal with a retry of its own; still no role, still one registration",
                 (second is not None and "expected S3 recorded running" in second.text, second is not None and callable(second.retry), started, registered),
                 (True, True, [], ["dispatch"]))
        driver, action, registered, started, seen = rig(dict(request, rework_of="S3-qa-test-strategist-1"))
        with Scripts({"stage_done.py": [(1, "refused")]}, seen):
            refusal, _out = refusal_of(driver._act_relaunch, action)
        check_eq("K20: a rework of accepted work writes no running record, so it raises nothing and the role starts",
                 (refusal, [s for s, _a in seen], len(started)), (None, [], 1))
        driver, action, registered, started, seen = rig(request)
        with Scripts({"stage_done.py": [(0, "")]}, seen):
            refusal, _out = refusal_of(driver._act_relaunch, action)
        check_eq("K20 green twin: exit 0 raises nothing and the role starts once", (refusal, len(started)), (None, 1))
    finally:
        harness.cleanup(root)


def k26_continue_over_a_registered_dispatch_keeps_its_lines() -> None:
    """K26 (F-2 of t-1252, AR-24; the O4 refusal then the conductor's `continue`, and the G3 shape): a dispatch a G site registered and did
    not record is found by `where` as `wait_existing_job` (no session, no words, no result). Its never-launched branch starts the role the
    way the site would have: the `running` record first (through `record_running`; a refusal's `retry` is this whole branch), the role
    lines, and for a relaunched packet the relaunch reason (the fresh_line and the person's release words). The packet is registered ONCE."""
    root, task_root, env = seed(TASK)
    try:
        closed, packet = "S3-qa-test-strategist-1", "S3-qa-test-strategist-2"
        record = {"stage": "S3", "role": "qa-test-strategist", "scope": ["TC-1"], "relaunch_of": closed, "reason": "the packet's own reason"}

        def rig(dispatches: dict, stages: dict | None = None):
            registered, started, seen = [], [], []
            driver = driver_for(root, env, TASK)
            driver.controller = lambda operation, input_data=None, **k: registered.append(operation) or {}
            driver.controller_state = lambda: {"dispatches": dispatches, "stages": stages or {}}
            driver.run_role = lambda *a, **k: started.append((a, k)) or ("", None)
            driver.completion_for = lambda *a: None
            driver.role_lines = lambda *a: ["the role line"]
            driver.stand_check = lambda *a, **k: None
            driver.build_check = lambda *a, **k: None
            driver.state["exit_limit"] = {closed: {"fresh_line": "FRESH LINE"}}
            return driver, registered, started, seen
        dispatches = {closed: {"released_by_person": "do it differently"}, packet: dict(record)}
        driver, registered, started, seen = rig(dispatches)
        action = {"stage": "S3", "role": "qa-test-strategist",
                  "dispatch_request": dict(record, id=packet)}
        with Scripts({"stage_done.py": [(1, "locked"), (0, "")]}, seen):
            refusal, _out = refusal_of(driver._act_relaunch, action)
            check_eq("K26: the O4 record is refused, the packet is registered once and no role started", (refusal is not None, registered, started),
                     (True, ["dispatch"], []))
            # the conductor's `continue`: no retry, the next `where` is wait_existing_job over the registered packet
            quiet(driver._act_wait_existing_job, {"dispatch_id": packet})
        check_eq("K26: ...the branch writes the record (the refused one, then this one) and starts the role ONCE", ([s for s, _a in seen], len(started)),
                 (["stage_done.py", "stage_done.py"], 1))
        check_eq("K26: ...no second dispatch of the packet", registered, ["dispatch"])
        if started:
            args, kwargs = started[0]
            check_eq("K26: ...with the role lines", kwargs["extra"], ["the role line"])
            check_in("K26: ...and the relaunch reason: the fresh_line", "FRESH LINE", kwargs["rework"]["reason"])
            check_in("K26: ...the person's release words, whole", "do it differently", kwargs["rework"]["reason"])
            check_in("K26: ...and the packet's own reason", "the packet's own reason", kwargs["rework"]["reason"])
            check_eq("K26: ...the packet's id and scope", (args, kwargs["rework"]["id"], kwargs["scope"]), (("S3", "qa-test-strategist"), packet, ["TC-1"]))
        # the branch's own refusal: `retry` is the whole branch, the role is not started over it, and a retry that passes starts it once
        driver, registered, started, seen = rig(dispatches)
        with Scripts({"stage_done.py": [(1, "locked"), (0, "")]}, seen):
            refusal, _out = refusal_of(driver._act_wait_existing_job, {"dispatch_id": packet})
            check_eq("K26: a refused record in the branch is the factory's own refusal naming the relaunched packet, and no role started",
                     (refusal is not None and refusal.known, refusal.dispatch if refusal is not None else None, started), (False, packet, []))
            check_in("K26: ...with what it expected", f"expected S3 recorded running for the relaunched dispatch {packet}", refusal.text if refusal else "")
            again, _out = refusal_of(refusal.retry) if refusal is not None else (None, "")
        check_eq("K26: ...`retry` passes and starts the role ONCE", (again, len(started)), (None, 1))
        # the G3 shape: a registered manual block of S6 (no relaunch_of): the record, the role lines, the record's own reason
        manual = {"stage": "S6", "role": "qa-runner", "scope": ["TC-1"], "execution_kind": "manual", "reason": "manual block"}
        driver, registered, started, seen = rig({"S6-qa-runner-1": manual})
        with Scripts({"stage_done.py": [(0, "")]}, seen):
            quiet(driver._act_wait_existing_job, {"dispatch_id": "S6-qa-runner-1"})
        check_eq("K26 (G3 shape): the record is written for the manual block, the role starts once with its lines and its own reason",
                 ([(s, a[a.index("--stage") + 1]) for s, a in seen], len(started), started[0][1]["extra"] if started else None,
                  started[0][1]["rework"]["reason"] if started else None), ([("stage_done.py", "S6")], 1, ["the role line"], "manual block"))
        # B-1 through the same helper: a controller-completed stage's later work (a rework) is started with no record at all
        driver, registered, started, seen = rig({packet: dict(record, rework_of=closed)}, stages={"S3": {"status": "completed"}})
        with Scripts({"stage_done.py": [(1, "would be refused")]}, seen):
            refusal, _out = refusal_of(driver._act_wait_existing_job, {"dispatch_id": packet})
        check_eq("K26 (B-1): a completed stage's later work in this branch writes no record, raises nothing and starts the role",
                 (refusal, [s for s, _a in seen], len(started)), (None, [], 1))
    finally:
        harness.cleanup(root)


def k27_one_writer_of_the_running_record() -> None:
    """K27 (F-3 of t-1252, AR-15): `record_running` is the ONLY writer of a `--status running` stage record in the driver. The scan has its
    positive control: the same scan finds the `halted` writers (more than one), so an empty result is not a miscall of the pattern."""
    source = harness.driver_text()      # the whole driver set: the facade and its parts (one reader, AR-13)
    running = [i for i, line in enumerate(source.splitlines(), 1) if '"--status", "running"' in line]
    halted = [i for i, line in enumerate(source.splitlines(), 1) if '"--status", "halted"' in line]
    check("K27 control: the scan finds the `halted` writers", len(halted) >= 2)
    check_eq("K27: exactly ONE `--status running` writer, and it is `record_running`", len(running), 1)
    if running:
        head = source.splitlines()[:running[0]]
        owner = next(line for line in reversed(head) if line.lstrip().startswith("def "))
        check_in("K27: ...inside `record_running`", "def record_running(", owner)


def recompute_driver(root, env, plan: dict, seen: list):
    """A Driver at gate B with a report on disk, the report rebuild a stub, and the scripts of `recompute_verdict` answered from `plan`."""
    driver = driver_for(root, env, TASK)
    (driver.task_root / "test-report.md").write_text("# report\n", encoding="utf-8")
    driver.rebuild_report = lambda *a, **k: True
    return driver, Scripts(plan, seen)


def k21_verdict_ledger_is_a_gate_and_traceability_is_not() -> None:
    """K21 (O5 `recompute_verdict`; G for the ledger, L for the traceability; E-c3, E-c7): at gate B the ledger is rewritten over the
    answers; a failed `ledger.py` is a refusal that names the ledger files, stops BEFORE the verdict word is read, and whose `retry` is
    the whole step (`stage_S9`). `check_traceability` exits 1 (gaps found) is an answer, no refusal and no conductor call. An empty
    output says the step said nothing."""
    root, task_root, env = seed(TASK)
    try:
        plan = {"check_traceability.py": [(1, "REQUIREMENTS WITHOUT A TERMINAL OUTCOME: R1")], "ledger.py": [(1, "no such directory: x")],
                "check_delivery.py": [(0, VERDICT_YES)]}
        seen = []
        driver, scripts = recompute_driver(root, env, plan, seen)
        with scripts:
            refusal, _out = refusal_of(driver.recompute_verdict)
        check("K21: ledger.py exit 1 raises", refusal is not None)
        if refusal is not None:
            check_in("K21: ...with the ledger files it must leave", "expected work/ledger.json and work/ledger.md rewritten with the verdict row", refusal.text)
            check_eq("K21: ...the factory's own, not routed by the known table", (refusal.known, story_run.route_known(refusal)), (False, None))
            check_eq("K21: ...BEFORE the verdict word is read (no check_delivery) and `retry` is the whole step",
                     ([s for s, _a in seen], refusal.retry), (["check_traceability.py", "ledger.py"], driver.stage_S9))
        for label, out in (("an empty output", ""), ("already completed", "already completed"), ("STORY BUDGET", "STORY BUDGET: 9 of 5")):
            seen = []
            driver, scripts = recompute_driver(root, env, dict(plan, **{"ledger.py": [(1, out)]}), seen)
            with scripts:
                refusal, _out = refusal_of(driver.recompute_verdict)
            check_eq(f"K21: ledger exit 1 with {label} is the factory's own refusal and does not pass", (refusal is not None and refusal.known, [s for s, _a in seen].count("check_delivery.py")),
                     (False, 0))
            if label == "an empty output" and refusal is not None:
                check_in("K21 (E-c7): ...an empty output says the step said nothing", "the step said nothing", refusal.text)
        seen = []
        driver, scripts = recompute_driver(root, env, dict(plan, **{"ledger.py": [(0, "")], "report_facts.py": [(0, "")], "delivery_summary.py": [(0, "")]}), seen)
        with scripts:
            word, out = quiet(driver.recompute_verdict)
        check_eq("K21 (L): traceability exit 1 (gaps found) with a good ledger is no refusal: the verdict word is read", word, "yes")
        check_in("K21 (L): ...and the gaps line is printed", "check_traceability.py: exit 1", out)
        check_eq("K21: the whole step ran in its order", [s for s, _a in seen],
                 ["check_traceability.py", "ledger.py", "check_delivery.py", "report_facts.py", "delivery_summary.py"])
    finally:
        harness.cleanup(root)


def k22_verdict_description_is_a_gate() -> None:
    """K22 (O6 `recompute_verdict`; kind G; E-c3): the MR description is rewritten at the end of gate B's recompute; a failed
    `delivery_summary.py` is a refusal naming the description files, and `retry` is the whole step. Exit 0 returns the verdict word. A
    declined delivery and a report-check failure do not reach it (the earlier branches are unchanged)."""
    root, task_root, env = seed(TASK)
    try:
        base = {"check_traceability.py": [(0, "")], "ledger.py": [(0, "")], "check_delivery.py": [(0, VERDICT_YES)], "report_facts.py": [(0, "")]}
        seen = []
        driver, scripts = recompute_driver(root, env, dict(base, **{"delivery_summary.py": [(1, "no such task root")]}), seen)
        with scripts:
            refusal, _out = refusal_of(driver.recompute_verdict)
        check("K22: delivery_summary exit 1 raises", refusal is not None)
        if refusal is not None:
            check_in("K22: ...with the description files it must leave", "expected work/delivery-summary.json and work/delivery-summary.md rewritten", refusal.text)
            check_eq("K22: ...the factory's own, and `retry` is the whole step", (refusal.known, refusal.retry), (False, driver.stage_S9))
        seen = []
        driver, scripts = recompute_driver(root, env, dict(base, **{"delivery_summary.py": [(0, "")]}), seen)
        with scripts:
            word, _out = quiet(driver.recompute_verdict)
        check_eq("K22 green twin: exit 0 returns the verdict word", word, "yes")
        seen = []
        driver, scripts = recompute_driver(root, env, dict(base, **{"report_facts.py": [(1, "R1: not in the report")], "delivery_summary.py": [(1, "x")]}), seen)
        with scripts:
            raised, _out = quiet(driver.recompute_verdict)
        check_eq("K22: a report that does not match is still the person's question, and the description is not written", (getattr(raised, "kind", None),
                 [s for s, _a in seen].count("delivery_summary.py")), ("report_match", 0))
    finally:
        harness.cleanup(root)


# --- Q-3: the stubs of `py` in the tests that drive a G site ------------------------------------------------------------------------

# test_question_branches.py: 2 -> 0 (ae02ac71, DC1-19: its tests moved onto the controller seam, no `py` stub is left; the file stays listed
# at 0 so a stub that comes back is seen); a SHRINK, not a raise.
STUB_FILES = {"test_story_run_s7.py": 1, "test_question_branches.py": 0, "test_story_run_gate_repair.py": 4,
              "test_story_run_refusals.py": 4, "test_no_move_seam_n2b_n15.py": 1}
IGNORES_CHECK = "the stub takes `check` and returns a non-zero or non-constant exit with no `raise` under `if check`: it swallows a G site's check=True"
# The stubs of that shape that are KNOWN and not fixed here (t-1252 Q4, a queue line): the lambdas of test_story_run_gate_repair.py at
# :757 and :1463 (a non-zero exit for controller.py) and :1128 (an exit `code` read into RepairFailed) answer scripts the driver calls
# WITHOUT `check`, so a G site reached through them would raise TypeError on `expect` (loud), never pass silently. A SHRINK-ONLY count:
# fixing one lowers it; a new one is a problem, not a raise of this number.
KNOWN_IGNORING = {"test_story_run_gate_repair.py": 3}


def py_stubs(source: str) -> list:
    """`(line, parameters, the calls with a `check` keyword)` of each stub of `Driver.py` in a test source: a `def py(...)` or a lambda
    assigned to `<x>.py`, which takes `check`."""
    import ast
    found = []
    tree = ast.parse(source)
    defs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    for node in ast.walk(tree):
        fn = None
        if isinstance(node, ast.FunctionDef) and node.name == "py":
            fn = node
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Lambda) and any(isinstance(t, ast.Attribute) and t.attr == "py" for t in node.targets):
            fn = node.value
        elif (isinstance(node, ast.Assign) and isinstance(node.value, ast.Name) and node.value.id != "py" and node.value.id in defs
              and any(isinstance(t, ast.Attribute) and t.attr == "py" for t in node.targets)):
            # t-443: a named def assigned to `<x>.py` (`d.py = fake_py`, t-430 turned a lambda into one) is a stub all the same.
            fn = defs[node.value.id]
        if fn is None:
            continue
        names = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
        if "check" in names:
            found.append((node.lineno, names, [c for c in ast.walk(fn) if isinstance(c, ast.Call) and any(k.arg == "check" for k in c.keywords)], fn))
    return found


def returned_tuples(fn) -> list:
    """The result tuples a stub RETURNS itself (not a call it forwards to): a `return <tuple>` of a def, or the body of a lambda, through
    the branches of a conditional expression."""
    import ast
    values = [fn.body] if isinstance(fn, ast.Lambda) else [n.value for n in ast.walk(fn) if isinstance(n, ast.Return) and n.value is not None]
    leaves = []
    while values:
        value = values.pop()
        if isinstance(value, ast.IfExp):
            values.extend([value.body, value.orelse])
        else:
            leaves.append(value)
    return [v for v in leaves if isinstance(v, ast.Tuple) and v.elts]


def stub_problems(source: str, name: str) -> tuple:
    """`(how many stubs carry `expect`, the problems)`: a stub with `expect` forwards BOTH `check` and `expect` to what it wraps, and
    never fixes `check` at False (a stub that swallows `check=True` leaves the G site it stands for untested). F-1 (t-1252): a stub that
    takes `check` and RETURNS a non-zero or non-constant exit code (not a forward) with no `raise` under an `if check` swallows the
    `check=True` of a G site, with `expect` or without it. THE NAMED LIMIT: a stub with NEITHER parameter is not a stub of this class
    (`py_stubs` does not find it); `**kw` stubs and files outside `STUB_FILES` are not scanned either."""
    import ast
    carrying, problems = 0, []
    for line, names, calls, fn in py_stubs(source):
        raises = any(isinstance(n, ast.If) and any(isinstance(t, ast.Name) and t.id == "check" for t in ast.walk(n.test))
                     and any(isinstance(r, ast.Raise) for r in ast.walk(n)) for n in ast.walk(fn))
        if not raises and any(not (isinstance(t.elts[0], ast.Constant) and t.elts[0].value == 0) for t in returned_tuples(fn)):
            problems.append(f"{name}:{line} {IGNORES_CHECK}")
        if "expect" not in names:
            continue
        carrying += 1
        for call in calls:
            keys = {k.arg: k.value for k in call.keywords}
            if "expect" not in keys:
                problems.append(f"{name}:{line} a call passes `check` and drops `expect`")
            if isinstance(keys["check"], ast.Constant) and keys["check"].value is False:
                problems.append(f"{name}:{line} a call fixes `check=False`: the stub swallows the G site's check")
    return carrying, problems


def k24_py_stubs_carry_check_and_expect() -> None:
    """K24 (Q-3, E-c5): the stubs of `Driver.py` that C1-7c named (11 of the critic's list, plus the one that already forwarded) take
    `check=False, expect=""` as the real `py` does, and a stub that wraps another forwards both. Counted per file: a stub that loses
    `expect` lowers its file's count; one that swallows `check` is a problem line. WHAT IT IS (F-1 of t-1252): a forwarding pin over the
    COUNTED stubs of five files, plus the check-swallowing shape (`stub_problems`) over the stubs that take `check`; a stub with neither
    parameter, a `**kw` stub and a file outside `STUB_FILES` are not seen (the named limit), so it is not a structural pin of the class."""
    here = Path(__file__).resolve().parent
    got, problems, ignoring = {}, [], {}
    for name in STUB_FILES:
        got[name], found = stub_problems((here / name).read_text(encoding="utf-8"), name)
        problems.extend(p for p in found if IGNORES_CHECK not in p)
        if any(IGNORES_CHECK in p for p in found):
            ignoring[name] = sum(IGNORES_CHECK in p for p in found)
    check_eq("K24: the stubs that carry `expect`, per file", got, STUB_FILES)
    check_eq("K24: none drops `expect` on a forward or fixes `check=False`", problems, [])
    check_eq("K24 (F-1): the stubs that swallow `check` are exactly the known, queued ones (a new one is a problem)", ignoring, KNOWN_IGNORING)


def k25_swallowing_stub_is_found() -> None:
    """K25 (negative control of K24): a planted stub that fixes `check=False` on its forward, one that drops `expect`, and one that loses the
    parameter are all found; the good form is not."""
    good = "def py(script, *a, check=False, expect=''):\n    return inner(script, *a, check=check, expect=expect)\n"
    swallow = good.replace("check=check", "check=False")
    drops = good.replace(", expect=expect)", ")")
    lost = "x.py = lambda script, *a, check=False: (0, '')\n"
    check_eq("K25: the good stub is counted and clean", stub_problems(good, "good"), (1, []))
    check_eq("K25: a stub that fixes check=False is a problem", len(stub_problems(swallow, "s")[1]), 1)
    check_eq("K25: a stub that drops expect on the forward is a problem", len(stub_problems(drops, "d")[1]), 1)
    check_eq("K25: a stub that lost the parameter is not counted (K24's per-file count goes red)", stub_problems(lost, "l"), (0, []))
    # F-1 (t-1252): the three shapes of the critic's probe. (a) the new signature that returns non-zero and ignores `check=True`; (c) a
    # check-only stub that returns non-zero; (b) a stub with NEITHER parameter stays a NAMED LIMIT (not found, not a problem).
    ignores = "def py(script, *a, check=False, expect=''):\n    return 1, 'refused'\n"
    check_only = "x.py = lambda script, *a, check=False: (1, 'refused') if script == 'controller.py' else (0, '')\n"
    non_constant = "x.py = lambda script, *a, check=False, code=2: (code, 'refused')\n"
    neither = "def py(script, *a):\n    return 1, 'refused'\n"
    honours = ("def py(script, *a, check=False, expect=''):\n    if check:\n        raise RuntimeError('refused')\n    return 1, 'refused'\n")
    check_eq("K25 (a): the new signature that returns non-zero and ignores check is a problem", stub_problems(ignores, "a"),
             (1, [f"a:1 {IGNORES_CHECK}"]))
    check_eq("K25 (c): a check-only stub that returns non-zero is a problem", stub_problems(check_only, "c"), (0, [f"c:1 {IGNORES_CHECK}"]))
    check_eq("K25 (c'): a non-constant exit code is a problem", stub_problems(non_constant, "n"), (0, [f"n:1 {IGNORES_CHECK}"]))
    check_eq("K25 (b): a stub with neither parameter is the NAMED LIMIT: not found, not a problem", stub_problems(neither, "b"), (0, []))
    check_eq("K25: a stub that raises under `if check` is clean", stub_problems(honours, "h"), (1, []))
    check_eq("K25: exit 0 and a forward are clean", (stub_problems("x.py = lambda script, *a, check=False: (0, '')\n", "z")[1],
                                                     stub_problems(good, "g")[1]), ([], []))


def main() -> None:
    run_scenarios([], [
        k18_halt_record_is_a_trace,
        k19_resume_record_is_a_gate,
        k20_relaunch_record_is_a_gate,
        k21_verdict_ledger_is_a_gate_and_traceability_is_not,
        k22_verdict_description_is_a_gate,
        k23_the_refused_resume_is_found_again,
        k26_continue_over_a_registered_dispatch_keeps_its_lines,
        k27_one_writer_of_the_running_record,
        k24_py_stubs_carry_check_and_expect,
        k25_swallowing_stub_is_found,
        k6_render_appendix_is_a_gate,
        k7_g_battery_is_never_a_pass,
        k8_g_per_site,
        k9_traceability_no_is_not_a_gate,
        t_traces_of_the_stage_functions,
        k14_halts_map,
        k16_readiness_record,
        k17_one_verdict_parse,
        k1_owed_then_written,
        k2_second_failure_is_the_seam,
        k3_position_before_any_brief,
        k4_the_persons_go_on,
        k4b_the_go_on_is_paired_by_row_ids,
        k5_duplicates_never_zero,
        k13_recorded_earlier_is_not_owed,
        k10_py_trace,
        k11_pasted_material_not_recorded,
        k12_mode_switch_not_recorded,
        py_contract,
        block_names_row,
    ])
    harness.finish("test_silent_passes")


if __name__ == "__main__":
    main()
