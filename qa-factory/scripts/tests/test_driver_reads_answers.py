#!/usr/bin/env python3
"""t-2020 (AR-13, AR-18, AR-28; FR-41): the driver reads a script's answer as the LAST line of stdout+stderr that is a JSON object.

A controller on a project folder copied elsewhere prints a path warning to stderr; the driver used to parse `out.splitlines()[-1]`,
got `{"raw": out}`, and S6 closed "nothing to execute" over a scope nobody had read. Here:
  test_warning_after_answer_is_read      the warning line comes AFTER the answer
  test_warning_before_answer_is_read     the warning line comes BEFORE the answer
  test_no_json_is_refused_never_empty    no JSON line: a Refusal naming what came back, never `{"raw": ...}`
  test_stage_s6_refuses_answer_without_scope   S6 does not close by code over an answer that has no `scope` list

Fast: a bare Driver (no seeded project); the script runner is a stub. Runs under pytest and as `python -B scripts/tests/test_driver_reads_answers.py`.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, finish  # noqa: E402


def eq(name, got, want):
    assert check_eq(name, got, want), f"{name}: expected {want!r}, got {got!r}"


def ok(name, cond, detail=""):
    assert check(name, bool(cond), detail), f"{name}: {detail}"

sys.path.insert(0, str(SCRIPTS))
import story_run as SR  # noqa: E402

WARNING = "project: the stored path (C:/old/place) is not the project this story is in here; using C:/new/place"
ANSWER = {"stage": "S6", "execution_kind": "manual", "scope": ["LOCAL-1_TC_101", "LOCAL-1_TC_102"]}


def driver(out: str, code: int = 0):
    d = object.__new__(SR.Driver)
    d.task_root = Path("task-root-not-read")
    d.py = lambda script, *args, **kw: (code, out)
    return d


def test_warning_after_answer_is_read():
    got = driver(json.dumps(ANSWER) + "\n" + WARNING).controller("stage-scope")
    eq("warning after the answer: the answer is read", got, ANSWER)


def test_warning_before_answer_is_read():
    got = driver(WARNING + "\n" + json.dumps(ANSWER)).controller("stage-scope")
    eq("warning before the answer: the answer is read", got, ANSWER)
    got = driver(WARNING + "\n" + json.dumps(ANSWER) + "\n" + WARNING).controller("stage-scope")
    eq("warnings on both sides: the answer is read", got, ANSWER)


def test_no_json_is_refused_never_empty():
    for name, out in (("only a warning", WARNING), ("nothing", ""), ("a JSON array is no answer", "[1, 2]"),
                      ("a broken object", '{"scope": [')):
        try:
            got = driver(out).controller("stage-scope")
        except SR.Refusal as exc:
            text = str(exc)
            ok(f"{name}: the refusal names the operation and what came back",
                  "stage-scope" in text and "JSON object" in text and (out.strip() == "" or out.strip()[:20] in text), text)
        else:
            ok(f"{name}: a Refusal, never an answer", False, repr(got))
    eq("the reader itself: no JSON line is None, not {}", SR._read_answer(WARNING), None)


def test_stage_s6_refuses_answer_without_scope():
    closed = []
    d = driver("")
    d.close_by_code = lambda *a, **k: closed.append(a)
    d.stage_scope = lambda stage, kind="": {"raw": WARNING}          # what the old reader returned for a warning-last controller
    try:
        d.stage_S6()
    except SR.Refusal as exc:
        ok("S6 refuses an answer without `scope`", "no `scope` list" in str(exc), str(exc))
    else:
        ok("S6 refuses an answer without `scope`", False, "no Refusal")
    eq("...and closed nothing by code", closed, [])
    d.stage_scope = lambda stage, kind="": {"scope": []} if kind == "automation" else {"raw": "x"}
    try:
        d.stage_S6()
    except SR.Refusal:
        ok("one half without `scope` is enough to refuse", True)
    else:
        ok("one half without `scope` is enough to refuse", False, "no Refusal")
    eq("...still nothing closed", closed, [])


FORM_ANSWER = {"contract": "handoff", "fixed": ["a"], "problems": [{"path": "x.y", "problem": "empty"}]}


def test_form_report_reads_answer_behind_a_warning():
    """story_run `form_report` (handoff_check --json): the warning no longer makes the answer unparsable; unparsable stays (None, lines)."""
    import shutil
    import tempfile
    root = Path(tempfile.mkdtemp(prefix="qa-t2020-"))
    try:
        (root / "work" / "handoffs").mkdir(parents=True)
        (root / "work" / "handoffs" / "D1.yaml").write_text("contract: handoff\n", encoding="utf-8")
        for name, out in (("warning after", json.dumps(FORM_ANSWER) + "\n" + WARNING), ("warning before", WARNING + "\n" + json.dumps(FORM_ANSWER))):
            d = driver(out)
            d.task_root, d.task, d.config = root, "QA-9", {}
            report, errors = d.form_report("D1")
            eq(f"form_report, {name}: the report", report, FORM_ANSWER)
            eq(f"form_report, {name}: the problem line", errors, ["handover form D1.yaml - x.y: empty"])
        d = driver(WARNING, code=1)
        d.task_root, d.task, d.config = root, "QA-9", {}
        eq("form_report, no JSON: today's answer (None and the last line)", d.form_report("D1"), (None, [f"handover form: handoff_check gave no readable answer (exit 1): {WARNING[:200]}"]))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_story_step_handoff_check_reads_answer_behind_a_warning():
    """story_step `_handoff_check` reads through the same `hooklib.read_answer`."""
    import shutil
    import tempfile
    import story_step as SS
    root = Path(tempfile.mkdtemp(prefix="qa-t2020-"))
    real = SS._run
    try:
        form = root / SS.FORM_REL.format(dispatch_id="D1")
        form.parent.mkdir(parents=True)
        form.write_text("contract: handoff\n", encoding="utf-8")
        for name, out in (("warning after", json.dumps(FORM_ANSWER) + "\n" + WARNING), ("warning before", WARNING + "\n" + json.dumps(FORM_ANSWER))):
            SS._run = lambda *a, _out=out: (0, _out)
            eq(f"story_step, {name}: the status is the report's, not 'none'", SS._handoff_check("QA-9", "D1", root)[0], "problems")
        SS._run = lambda *a: (1, WARNING)
        eq("story_step, no JSON: today's answer", SS._handoff_check("QA-9", "D1", root)[:2], ("problems", f"handoff_check gave no readable answer (exit 1): {WARNING}"))
    finally:
        SS._run = real
        shutil.rmtree(root, ignore_errors=True)


def test_reprove_reads_pretty_answer_behind_a_warning_with_a_brace():
    """story_run `s6_reprove` (probe_by_code --json, indent=1): a warning holding `{` beside the answer no longer hides it."""
    record = {"instance_id": "i1", "verdict": "intended_failure", "record": "work/probes/i1.json"}
    brace_warning = "probe_by_code: note {not json} on stderr"
    for name, out in (("brace warning before", brace_warning + "\n" + json.dumps(record, indent=1)),
                      ("brace warning after", json.dumps(record, indent=1) + "\n" + brace_warning)):
        d = driver(out)
        d.task, d.CUT = "QA-9", "..."
        d.controller_state = lambda: {"dispatches": {}}
        _lines, proved, _sec, records = d.s6_reprove({"i1": {"test": "t", "instance": "i1", "mutation": "m"}}, [], no_stand=False, unrun=[])
        eq(f"s6_reprove, {name}: proved and the record named", (proved, records), (1, ["work/probes/i1.json"]))
    eq("read_document: no object at column 0 is None", SR.hooklib.read_document(brace_warning), None)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    finish("test_driver_reads_answers")
