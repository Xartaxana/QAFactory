#!/usr/bin/env python3
"""The S3 remarks travel as ONE package and are repaired by a fresh dispatch (speed-cost SC1-1 part B, release 0.10.3).

TP1-12586: the S3 exit printed its question-branch remarks AFTER S3 closed, as one long line; the conductor
resumed the plan's author (a 486k session) six times with a part of them. Now `stage_done.s3_branch_line` writes every
finding to one file (`state/findings/s3-remarks-<sha12>.md`) and prints a short line with ONE rework door that names it;
how the rework card is launched is the stage's `rework_mode` (`references/stages.json`, read by `contract.rework_mode`);
`story_step.finish` keeps that line whatever stage_done prints after it; the form refusal lists every problem.

Each check names the ONE mutation it kills:
  t1  the line has no package / the door's `--rows` is cut / the path is not project-relative / the reason is not narrowed
  t2  the rows section names a row with no id as an addressable row / `--rows` lists a row with no id
  t3  the time stands in the body that names the file (two injected clocks) / the same bytes make a second file
  t4  `>` for `>=` at the whole-read limit / the over-limit sentence is missing from the line or from the reason
  t5  a write that fails prints an empty line instead of the findings / the fallback line has no prefix
  t6  `[-4:]` without the prefix in `finish` / a fallback line that loses the prefix
  t7  `[:4]` back in `_handoff_check` / no file for a long list
  t8  "still holds the context" back / the S3 refusal names no rework_mode / the s3.md paragraph is over its size budget
  t9  the `--reason` loses the package path on its way to the card
  t10 a finding is cut at a line ceiling instead of wrapped
  t11 the S3 exit raises on a malformed stages.json (a list root, `stages` not a list, a row not an object)
"""
import argparse
import contextlib
import io
import json
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import planning_contract  # noqa: E402
import stage_done  # noqa: E402
import story_step  # noqa: E402

PREFIX = stage_done.S3_REMARK_PREFIX
STAGE_DONE_ARGS = ("T-3", "S3", "done", "qa-test-strategist", "plan", True)


# --- fixtures ---------------------------------------------------------------------------------------------

def s3_story(rows, prefix="qa-s3-remarks-", ticket="T-3"):
    """(project, task root, plan path): a story whose register has one question, Q1, and whose plan is `rows`."""
    project = temp_project(prefix)
    use_project(project)
    task = project / "qa-factory" / "artifacts" / ticket
    (task / "work").mkdir(parents=True)
    (task / "pipeline.json").write_text(json.dumps({"ticket": ticket, "stages": {}, "gates": {}}), encoding="utf-8")
    register = {"open_questions": [{"id": "Q1", "question": "Which reading?",
                                    "readings": [{"reading": "one"}, {"reading": "two"}]}]}
    (task / "work" / "requirements-readiness.json").write_text(json.dumps(register), encoding="utf-8")
    plan = task / "work" / "test-plan.json"
    plan.write_text(json.dumps(rows), encoding="utf-8")
    return project, task, plan


def bad_rows(*ids):
    """Rows whose ref resolves nowhere: one finding each, `<id>: `Q9` is not a question id of the register`."""
    return [{"id": rid, "question_refs": ["Q9"]} for rid in ids]


def package_of(line):
    """The project-relative package path the line names, or ''."""
    found = re.search(r"(qa-factory/artifacts/\S+/state/findings/s3-remarks-[0-9a-f]{12}\.md)", line)
    return found.group(1) if found else ""


def door_of(line):
    """The command between the backticks that starts with `controller.py`."""
    found = re.search(r"`(controller\.py [^`]*)`", line)
    return found.group(1) if found else ""


def finding(where, message):
    return {"kind": "invalid_variant", "owner": "strategist", "where": where, "question": "Q1", "message": message}


def remark_line(task):
    """`stage_done.s3_branch_line` with its filter emptied (RN1-2): the S3 exit now REFUSES every strategist kind of
    `planning_contract.S3_EXIT_KINDS` (and only WARNS for `S3_WARN_KINDS`), so the line never reports one. The WRITER of the
    remark package (`_s3_remark_package`, the line, the door) is unchanged - only its reachability shrank - and every
    assertion below still drives it through the one route, over real findings, with the two kind lists emptied."""
    held = planning_contract.S3_EXIT_KINDS, planning_contract.S3_WARN_KINDS
    planning_contract.S3_EXIT_KINDS = planning_contract.S3_WARN_KINDS = ()
    try:
        return stage_done.s3_branch_line(task)
    finally:
        planning_contract.S3_EXIT_KINDS, planning_contract.S3_WARN_KINDS = held


def the_exit_refuses_what_the_remarks_used_to_report():
    """KILLS (K-2.7, M-5): `s3_branch_line` filtering only `missing_branch` - a plan whose findings are all exit kinds says nothing here."""
    project, task, _plan = s3_story(bad_rows("TS-2"))
    try:
        check_eq("t12: an unresolved ref is the exit's, not a remark", stage_done.s3_branch_line(task), "")
        check_in("t12: ...and with the filter emptied the writer still reports it", "1 question-branch finding(s)", remark_line(task))
    finally:
        cleanup(project)


# --- t1: the line, the door, the package -------------------------------------------------------------------

def the_line_names_one_package_and_one_door():
    """KILLS: a line with no package; `--rows` cut to the shown rows; a path from the story root; a reason that
    does not narrow the dispatch; a head that is not the prefix."""
    project, task, plan = s3_story(bad_rows("TS-2", "TS-12"))
    try:
        before = plan.read_bytes()
        line = remark_line(task)
        check("t1: the line opens with the S3 remark head", line.startswith(PREFIX + " 2 question-branch finding(s)"), line[:120])
        check_eq("t1: it is ONE physical line", line.count("\n"), 0)
        rel = package_of(line)
        check("t1: it names the package from the PROJECT root (every path a role reads is spelled so, FR-37)",
              rel.startswith("qa-factory/artifacts/T-3/state/findings/s3-remarks-"), rel or line[:200])
        written = project / rel
        check("t1: and the package is a file there", written.is_file(), str(written))
        text = written.read_text(encoding="utf-8")
        check_in("t1: the package holds finding 1, whole", "- TS-2: `Q9` is not a question id of the register", text)
        check_in("t1: and finding 2, whole", "- TS-12: `Q9` is not a question id of the register", text)
        door = door_of(line)
        check_in("t1: the door is the rework of S3 for the strategist", "--operation rework --stage S3 --role qa-test-strategist", door)
        check_in("t1: its rows are the comma list, no spaces (a shell passes it as ONE argument)", "--rows TS-2,TS-12 ", door)
        check_in("t1: its task root is the real one, quoted", f'--task-root "{task}"', door)
        reason = re.search(r'--reason "([^"]*)"', door).group(1)
        check_eq("t1: the reason names the package and narrows the dispatch",
                 reason, f"repair every finding in {rel}; read only it and the plan rows it names")
        check(f"t1: and fits the {stage_done.S3_REMARK_REASON_MAX} characters the brief shows whole",
              len(reason) <= stage_done.S3_REMARK_REASON_MAX, str(len(reason)))
        check_in("t1: the line says the card is launched as a NEW agent (S3's rework_mode is fresh)", "as a NEW agent", line)
        check_in("t1: and why not the author's session", "never SendMessage into the author's session", line)
        check_in("t1: and that the S4 rehearsal stands behind it", "The gate rehearsal at the S4 exit stops on the same facts", line)
        check_eq("t1: the plan is not touched (E11: the package is a derived file beside it)", plan.read_bytes(), before)
        check_eq("t1: the only file written under state/ is the package",
                 sorted(p.name for p in (task / "state").rglob("*") if p.is_file()), [Path(rel).name])
        check_in("t1: the head of the package counts the findings and names the plan", "# 2 S3 question-branch finding(s), plan sha256 ", text)
        check_in("t1: it ends with the one instruction", "Repair every finding above in qa-factory/artifacts/T-3/work/test-plan.json", text)
    finally:
        cleanup(project)


def a_root_with_a_space_is_quoted_and_the_edges_say_nothing_or_one_line():
    """KILLS: an unquoted task root; a package or a line for a plan with nothing to say (E4)."""
    project, task, plan = s3_story(bad_rows("TS-1"), prefix="qa s3 space ")
    try:
        door = door_of(remark_line(task))
        check_in("t1: a task root with a space is one quoted argument", f'--task-root "{task}" ', door)
        check("t1: and the root does hold a space", " " in str(task), str(task))
    finally:
        cleanup(project)
    project, task, plan = s3_story([{"id": "TS-1", "question_refs": ["Q1"]}])
    try:
        check_eq("t1: a plan whose branches hold: no line", stage_done.s3_branch_line(task), "")
        check("t1: and no package, no directory (E4)", not (task / "state").exists())
    finally:
        cleanup(project)


# --- t2: the rows -------------------------------------------------------------------------------------------

def rows_are_named_by_id_and_a_row_without_one_is_not_a_door():
    """KILLS: `row[0]` in `--rows` (the controller refuses it as not in the plan); a head that lists every row."""
    rows = bad_rows(*[f"TS-{n}" for n in range(1, 9)]) + [{"question_refs": ["Q9"]}]
    project, task, plan = s3_story(rows)
    try:
        line = remark_line(task)
        rel = package_of(line)
        text = (project / rel).read_text(encoding="utf-8")
        check_in("t2: the head names the first six rows and how many more, with the place", "TS-6 and 3 more (" + rel + ")", line)
        check_in("t2: the door's `--rows` names ALL eight (a cut door is a wrong door, E2)",
                 "--rows TS-1,TS-2,TS-3,TS-4,TS-5,TS-6,TS-7,TS-8 ", door_of(line))
        check_not_in("t2: a row with no id is not in `--rows`", "row[", door_of(line))
        check_in("t2: the package lists every id as a row to repair", "- TS-8\n", text)
        check_in("t2: the row with no id is named as such, by its place in the plan", "- row[8]: no id; locate it by its position", text)
        check_in("t2: the package tells the role how to find a row afresh, with the plan from the project root",
                 "Plan rows to repair, by id, in qa-factory/artifacts/T-3/work/test-plan.json", text)
        check_in("t2: ... by Grep and Read windows (a role without a shell), or the shell command", "plan_row.py", text)
        plan.write_text(json.dumps([{"question_refs": ["Q9"]}]), encoding="utf-8")
        alone = remark_line(task)
        check_not_in("t2: no id anywhere: the door carries no `--rows` (S3 allows it, E12)", "--rows", door_of(alone))
        check("t2: and it is still a line with a package", package_of(alone) != "", alone[:200])
    finally:
        cleanup(project)


# --- t3: idempotence ----------------------------------------------------------------------------------------

def the_same_bytes_are_the_same_file():
    """KILLS: the time in the body that names the file; a new file on every call; the same name for a changed plan."""
    project, task, plan = s3_story(bad_rows("TS-1", "TS-2"))
    try:
        # two DISTINCT clocks (`now_iso` has second resolution: two real calls almost always read the same second, and a
        # name that hashed the time would pass unseen): the name must not move with the time
        stamps = iter(["2026-01-01T00:00:00+00:00", "2027-02-02T00:00:00+00:00", "2028-03-03T00:00:00+00:00", "2029-04-04T00:00:00+00:00"])
        saved_clock = stage_done.now_iso
        stage_done.now_iso = lambda: next(stamps)
        try:
            first = package_of(remark_line(task))
            again = package_of(remark_line(task))
        finally:
            stage_done.now_iso = saved_clock
        check_eq("t3: a second call on the same bytes, at another time, names the same package", again, first)
        check_in("t3: the first clock stands in the file (the second call kept the file)", "2026-01-01T00:00:00+00:00",
                 (project / first).read_text(encoding="utf-8").split("\n", 1)[0])
        check_eq("t3: and there is ONE file in state/findings", len(list((task / "state" / "findings").glob("*"))), 1)
        before = (project / first).read_bytes()
        remark_line(task)
        check_eq("t3: a third call leaves the file byte for byte (it may be open in a role's reader)", (project / first).read_bytes(), before)
        plan.write_text(json.dumps(bad_rows("TS-1", "TS-2", "TS-3")), encoding="utf-8")
        changed = package_of(remark_line(task))
        check("t3: another plan, other findings: another name; the earlier package stands (the line names the current one)",
              changed != first and (project / first).is_file() and (project / changed).is_file(), f"{first} / {changed}")
        # the name is the content's: the time line is the ONLY thing outside it
        head, body = before.decode("utf-8").split("\n", 1)
        check("t3: the time stands on the head line", bool(re.search(r", \d{4}-\d\d-\d\dT", head)), head)
        check("t3: the body below the head carries no clock", not re.search(r"\d{4}-\d\d-\d\dT\d\d:", body), body[:200])
    finally:
        cleanup(project)


# --- t4: the whole-read limit -------------------------------------------------------------------------------

def set_read_limit(project, value):
    path = project / "qa-factory" / "config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["read"] = {"max_bytes": value}
    path.write_text(json.dumps(cfg), encoding="utf-8")


def a_package_over_the_read_limit_says_so_to_the_conductor_and_to_the_role():
    """KILLS: `>` for `>=` at the limit (EXACTLY the limit is not over); no sentence in the line; no phrase in the reason
    (the role gets the reason, not the line); a limit of 0 (the guard off) that still warns."""
    project, task, plan = s3_story(bad_rows("TS-1", "TS-2"))
    try:
        rel = package_of(remark_line(task))
        size = (project / rel).stat().st_size
        for limit, over, label in ((size, False, "EXACTLY the limit"), (size - 1, True, "one byte under the limit"),
                                   (0, False, "limit 0 (guard off)"), (-5, False, "a negative limit (guard off)")):
            set_read_limit(project, limit)
            line = remark_line(task)
            check_eq(f"t4: {label}: the over-limit sentence is {'there' if over else 'absent'}",
                     "over the whole-read limit" in line, over)
            reason = re.search(r'--reason "([^"]*)"', line).group(1)
            check_eq(f"t4: {label}: and so is the phrase in the reason the ROLE receives",
                     "Read offset/limit" in reason, over)
            check(f"t4: {label}: the reason still fits the brief's {stage_done.S3_REMARK_REASON_MAX}",
                  len(reason) <= stage_done.S3_REMARK_REASON_MAX, str(len(reason)))
            if over:
                check_in("t4: the sentence says the size and the limit", f"The package is {size} bytes, over the whole-read limit {limit}", line)
        # the reason of a very long ticket key: the package path stays, the narrowing goes (named edge)
        long_rel = "qa-factory/artifacts/" + "T" * 70 + "/state/findings/s3-remarks-0123456789ab.md"
        reason = stage_done._s3_reason(long_rel, True)
        check_eq("t4: past the ceiling the reason is the package alone", reason, f"repair every finding in {long_rel}")
    finally:
        cleanup(project)


# --- t5: the package cannot be written ----------------------------------------------------------------------

def a_package_that_cannot_be_written_puts_the_findings_in_the_line():
    """KILLS: an empty line when the write fails; a fallback line without the prefix; a fallback that drops a message."""
    project, task, plan = s3_story(bad_rows("TS-1", "TS-2"))
    try:
        (task / "state").mkdir()
        (task / "state" / "findings").write_text("a file where the directory should be", encoding="utf-8")
        line = remark_line(task)
        check("t5: the fallback line still opens with the prefix (finish keeps it, M6)", line.startswith(PREFIX + " 2 question-branch"), line[:100])
        check_in("t5: it says the package was not written and why", "(the remark package was not written: ", line)
        check_in("t5: with every message inline, whole, in order (the findings are never lost)",
                 "repairs this row; TS-2: `Q9` is not a question id of the register", line)
        check_in("t5: the first message too", "): TS-1: `Q9` is not a question id of the register", line)
        check_eq("t5: still one physical line", line.count("\n"), 0)
        door = door_of(line)
        check_in("t5: and the same door, `--rows` whole", "--rows TS-1,TS-2 ", door)
        check_in("t5: its reason is the conductor's to fill (no package to name)", "--reason \"<the finding(s) above", door)
        check_in("t5: launched as a NEW agent all the same", "as a NEW agent", line)
        check_eq("t5: S3 still closes - the stage_done run exits 0 and prints it", _run_s3_done(project)[0], 0)
    finally:
        cleanup(project)


def _run_s3_done(project):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = stage_done.run(*STAGE_DONE_ARGS)
    return code, out.getvalue(), err.getvalue()


# --- t6: `finish` keeps the line ----------------------------------------------------------------------------

class FinishController:
    """Only what `story_step.finish` asks of a controller for an S3 dispatch."""

    def __init__(self, _root, wait_seconds=0.0):
        pass

    def state(self):
        return {"dispatches": {"D-1": {"stage": "S3", "role": "qa-test-strategist"}}}

    def prepare(self, options):
        return {"accept_request": dict(options)}

    def apply(self, operation, request):
        pass

    def next_action(self):
        return {"action": "prepare_stage", "stage": "S4"}

    def _next_action_for_state(self, _state):
        return self.next_action()


def finish_printing(task, stage_done_output):
    """`story_step.finish` with `stage_done.py` printing `stage_done_output`: (exit code, the `note: ` lines)."""
    names = ("Controller", "_task_root", "_stages", "_run", "_post_work", "_judge_line", "config_finding", "_config",
             "_halt_gate", "_handoff_check", "_finish_gate", "_evidence", "_role_receipts", "_no_change_note",
             "_release_binding")
    saved = {name: getattr(story_step, name) for name in names}
    story_step.Controller = FinishController
    story_step._task_root = lambda _task: task
    story_step._stages = lambda: {"S3": {"roles": ["qa-test-strategist"], "outputs": [], "required_outputs": []}}
    story_step._run = lambda script, *args: (0, stage_done_output) if script == "stage_done.py" else (0, "")
    story_step._post_work = lambda *_a: []
    story_step._judge_line = lambda _task: "judge: off"
    story_step.config_finding = lambda *_a: []
    story_step._config = lambda: {}
    story_step._halt_gate = lambda *_a: ("", "")
    story_step._handoff_check = lambda *_a: ("none", "", "")
    story_step._finish_gate = lambda *_a: (0, "", [])
    story_step._evidence = lambda *_a: ["work/test-plan.json"]
    story_step._role_receipts = lambda *_a: []
    story_step._no_change_note = lambda *_a: ""
    story_step._release_binding = lambda *_a: None
    out = io.StringIO()
    try:
        args = argparse.Namespace(task="T-3", dispatch_id="D-1", digest="qa-test-strategist S3 done", output=None,
                                  not_complete=False, complete=False, ignore_handoff=False, window=None,
                                  unresolved=None, reason=None)
        with contextlib.redirect_stdout(out):
            code = story_step.finish(args)
    finally:
        for name, value in saved.items():
            setattr(story_step, name, value)
    return code, [ln[len("note: "):] for ln in out.getvalue().splitlines() if ln.startswith("note: ")]


def finish_keeps_the_remark_line_whatever_follows_it():
    """KILLS: `[-4:]` alone (the line pushed off by what stage_done prints after it); the prefix test dropped from the
    keep rule; a line in both groups taken twice; a fallback line without the prefix (M6)."""
    project, task, plan = s3_story(bad_rows("TS-1"))
    try:
        remark = f"{PREFIX} 1 question-branch finding(s) the strategist can repair on TS-1 - every one: qa-factory/x.md. One repair round: `controller.py ...`"
        fallback = f"{PREFIX} 1 question-branch finding(s) the strategist can repair on TS-1 (the remark package was not written: OSError): msg"
        others = [f"stage_done line {n}" for n in range(1, 8)]

        def with_at(line, place):
            lines = list(others)
            lines.insert(place, line)
            return "\n".join(lines)

        for label, line, place in (("second of eight", remark, 1), ("last", remark, 7), ("first", remark, 0),
                                   ("the fallback, second of eight", fallback, 1)):
            code, notes = finish_printing(task, with_at(line, place))
            mine = [n for n in notes if n.startswith(PREFIX)]
            check_eq(f"t6: {label}: the remark line reaches the conductor, ONCE", mine, [line])
        code, notes = finish_printing(task, with_at(remark, 1))
        check_eq("t6: the rest is the last four lines, as before, in the output's order",
                 [n for n in notes if n.startswith("stage_done line")], others[-4:])
        check_eq("t6: and the remark stands at ITS place, before them", [n for n in notes][:1], [remark])
        # a line in both groups is taken once, at its own place
        code, notes = finish_printing(task, "\n".join(others[:3] + [remark]))
        check_eq("t6: last place is in both groups: still once", [n for n in notes].count(remark), 1)
        # temporal (a story mid-S3 on 0.10.2): the old head, in the last four, is printed as it always was
        old = "S3: 1 question-branch problem(s) the strategist can repair: TS-1: x - repair with `controller.py ...`"
        code, notes = finish_printing(task, "\n".join(others[:5] + [old]))
        check_in("t6: the 0.10.2 line, if it stands in the last four, is still printed", old, notes)
        code, notes = finish_printing(task, "")
        check_eq("t6: an empty output adds nothing and exits 0", (code, [n for n in notes if "stage_done" in n]), (0, []))
    finally:
        cleanup(project)


def not_checked_lines_carry_the_prefix_and_are_kept():
    """RH1-12. KILLS: a "not checked" line with the old `S3: ` head (it fell out of `[-4:]`); a second spelling of the head;
    a silent cut past the limit (the count of the rest is said); the rest counted wrongly."""
    # the three "not checked" branches of s3_branch_line, each opens with the one prefix
    project, task, plan = s3_story(bad_rows("TS-1"))
    try:
        plan.write_text("{not json", encoding="utf-8")
        check("t8: unreadable plan: prefixed", remark_line(task).startswith(PREFIX + " question branches not checked ("))
        plan.write_text(json.dumps(bad_rows("TS-1")), encoding="utf-8")
        (task / "work" / "requirements-readiness.json").unlink()
        check("t8: no register: prefixed", remark_line(task).startswith(PREFIX + " question branches not checked: "))
        plan.unlink()
        check("t8: no plan: prefixed", remark_line(task).startswith(PREFIX + " question branches not checked: "))
        check_eq("t8: one spelling", stage_done.s3_remark_line("x"), PREFIX + " x")
        # finish: a not-checked line early in a long output is kept, once
        nc = stage_done.s3_remark_line("question branches not checked: the story has no work/test-plan.json")
        others = [f"stage_done line {n}" for n in range(1, 8)]
        code, notes = finish_printing(task, "\n".join(others[:1] + [nc] + others[1:]))
        check_eq("t8: the not-checked line reaches the conductor once", [n for n in notes if n == nc], [nc])
        check_not_in("t8: no count when nothing is cut", "more not checked", "\n".join(notes))
        # more than the limit: the first four are kept, the rest counted
        many = [stage_done.s3_remark_line(f"question branches not checked: reason {n}") for n in range(1, 8)]
        code, notes = finish_printing(task, "\n".join(others[:2] + many + others[2:]))
        check_eq("t8: four kept", [n for n in notes if n.startswith(PREFIX) and "reason" in n][:4], many[:4])
        check_in("t8: the rest is counted, never silently cut", "(+3 more not checked)", notes)
        code, notes = finish_printing(task, "")
        check_not_in("t8: empty output: no line", "not checked", "\n".join(notes))
    finally:
        cleanup(project)


# --- t7: the form refusal lists every problem ---------------------------------------------------------------

def the_form_refusal_lists_every_problem():
    """KILLS: `[:4]` back; no file past the ceiling; a pointer with no place; an item without `path`/`problem` that raises."""
    project, task, plan = s3_story(bad_rows("TS-1"))
    form = task / "work" / "handoffs" / "D-1.yaml"
    form.parent.mkdir(parents=True)
    form.write_text("x: 1\n", encoding="utf-8")
    saved = story_step._run
    try:
        def answering(problems):
            report = {"untouched": False, "fixed": [], "problems": problems}
            story_step._run = lambda script, *args: (1, json.dumps(report))

        answering([{"path": f"f{n}", "problem": f"p{n}"} for n in range(1, 10)])
        status, note, rel = story_step._handoff_check("T-3", "D-1", task)
        check_eq("t7: nine problems: the status", status, "problems")
        check("t7: ALL nine are in the note", all(f"f{n}: p{n}" in note for n in range(1, 10)), note)
        check_not_in("t7: and no pointer when they fit", "more form problem", note)
        answering([{"path": f"f{n}", "problem": f"p{n}"} for n in range(1, 5)])
        check_not_in("t7: control, four problems: no pointer", "more form problem", story_step._handoff_check("T-3", "D-1", task)[1])
        big = [{"path": f"field{n}", "problem": "x" * 400} for n in range(1, 41)]
        answering(big)
        status, note, rel = story_step._handoff_check("T-3", "D-1", task)
        whole = task / "state" / "findings" / "D-1-form.txt"
        check("t7: past the ceiling the whole list is in a file", whole.is_file() and whole.read_text(encoding="utf-8").count("field") == 40,
              str(whole))
        check_in("t7: and the note says how many are left and where", "more form problem(s)", note)
        check_in("t7: the place is that file", str(whole), note)
        answering([{"path": "f1", "problem": "p1", "extra": "key"}, "a bare string", {"problem": "no path"}])
        note = story_step._handoff_check("T-3", "D-1", task)[1]
        check("t7: another producer's extra keys and odd items do not raise; each is its own text",
              "f1: p1" in note and "a bare string" in note and "no path" in note, note)
    finally:
        story_step._run = saved
        cleanup(project)


# --- t8: the texts ------------------------------------------------------------------------------------------

def the_texts_say_the_rule_by_rework_mode():
    """KILLS: "still holds the context" back in the refusal; a gate refusal that lets the finding list go one per
    message; an s3.md remarks paragraph over its size budget; an S5 (resume) text that says NEW agent."""
    fresh, resume = stage_done.rework_launch_text("S3"), stage_done.rework_launch_text("S5")
    check_in("t8: S3 (fresh): a NEW agent", "as a NEW agent", fresh)
    check_in("t8: S5 (resume): SendMessage the delta", "SendMessage the delta", resume)
    check_not_in("t8: and not a new agent", "NEW agent", resume)
    import test_story_step_materialize as MAT
    root, env, accepted, _controller = MAT.accepted_s3("qa-s3-remarks-running-")
    try:
        refused = harness.run_script("stage_done.py", "--task", MAT.TICKET, "--stage", "S3", "--status", "running",
                                     cwd=root, env=env)
        printed = refused.stderr + refused.stdout     # the refusal itself, as the conductor reads it
        check("t8: --status running on the accepted S3 is refused", refused.returncode != 0 and "already accepted" in printed, printed[:300])
        check_in("t8: the printed refusal launches the rework card as a NEW agent (S3 is fresh)", "as a NEW agent", printed)
        check_not_in("t8: ... and no longer says it reaches the agent that still holds the context", "still holds the context", printed)
        check_in("t8: it says the stage's rework_mode decides", "the stage's `rework_mode` in references/stages.json", printed)
        check_in("t8: it gives the waiver door whole", f'waiver.py --task {MAT.TICKET} --stage S3 --block "already accepted by the controller"', printed)
    finally:
        cleanup(root)
    project, task, plan = s3_story([])
    try:
        args = argparse.Namespace(task="T-3", dispatch_id="D-1")
        text = story_step._gate_refusal(args, task, {"stage": "S3", "role": "qa-test-strategist"}, ["a finding", "another"])
        check_in("t8: the gate refusal gives ALL findings back in ONE message", "ALL of these findings back in ONE message", text)
        check_in("t8: never one per message", "never one finding per message", text)
    finally:
        cleanup(project)
    s3 = (harness.PLUGIN_ROOT / "skills" / "qa-story" / "phases" / "s3.md").read_text(encoding="utf-8")
    # the paragraph's words are a row of design/role-rules.json (s3-remarks-paragraph-after-s3-closes); the size budget stays here
    paragraph = s3[s3.index("**Remarks after S3 closes.**"):].split("\n", 1)[0]
    check(f"t8: the s3.md remarks paragraph is at most 600 bytes ({len(paragraph.encode())})", len(paragraph.encode()) <= 600)


# --- t9: end to end -----------------------------------------------------------------------------------------

def the_printed_door_runs_and_the_card_carries_the_package():
    """KILLS: a `--reason` that loses the package path on its way to the card and the brief; a door that does not run
    as printed (the controller refuses it)."""
    import test_story_step_materialize as MAT
    root, env, task, controller = MAT.accepted_s3("qa-s3-remarks-e2e-")
    try:
        rows = json.loads((task / "work" / "test-plan.json").read_text(encoding="utf-8"))
        rows = rows["rows"] if isinstance(rows, dict) else rows
        for row in rows:
            if row["id"] in ("TS-1", "TS-3"):
                row["question_refs"] = ["Q9"]
        (task / "work" / "test-plan.json").write_text(json.dumps(rows), encoding="utf-8")
        (task / "work" / "requirements-readiness.json").write_text(json.dumps(
            {"open_questions": [{"id": "Q1", "question": "Which reading?", "readings": [{"reading": "one"}, {"reading": "two"}]}]}),
            encoding="utf-8")
        line = remark_line(task)
        check("e2e: the S3 exit line carries findings for the two rows", line.startswith(PREFIX + " 2 "), line[:160])
        rel = package_of(line)
        door = door_of(line)
        # every argument is TAKEN FROM the printed door (split as a shell would, a Windows path kept), none is added or typed here
        tokens = [t[1:-1] if len(t) > 1 and t[0] == t[-1] == '"' else t for t in shlex.split(door, posix=False)]
        check_eq("e2e: the printed door starts with the script", tokens[0], "controller.py")
        argv = tokens[1:]
        made = harness.run_script("controller.py", *argv, cwd=root, env=env)
        check_eq("e2e: the controller takes the door as printed", made.returncode, 0)
        check_in("e2e: and answers with the door that writes the card", "materialize", made.stdout)
        done = MAT.materialize(root, env)
        check_eq("e2e: materialize exits 0", done.returncode, 0)
        card = MAT.files_of(task)[2].read_text(encoding="utf-8")
        check_in("e2e: the card carries the package path (the reason reached the prompt, M3/M4)", rel, card)
        check_in("e2e: and the narrowing", "read only it and the plan rows it names", card)
        check_in("e2e: and the rows of the dispatch", "Plan rows of this dispatch: TS-1, TS-3", card)
        # The brief's head is NOT asserted: brief_pack.py:1387 prints the reason only for a dispatch with a `repair_cause`, and
        # the printed door names none (t-1316 finding: the card is what the role reads and it carries the reason; the brief
        # head carries only "Rework of ..." and the rows). The fork is the Lead's, see the t-1316 report.
        check("e2e: the package path from the card is a file from the PROJECT root", (root / rel).is_file(), rel)
    finally:
        cleanup(root)


# --- t10: nothing is cut ------------------------------------------------------------------------------------

def a_long_finding_wraps_and_loses_nothing():
    """KILLS: a finding cut at the line ceiling (an error of the contract gone from a file that promises every one);
    a package line longer than the ceiling (a host may cut a long `Read` line, M5); an empty message that vanishes."""
    project, task, plan = s3_story(bad_rows("TS-1"))
    saved = planning_contract.variant_errors
    try:
        errors = [f"OB-{n}: field_{n} is not filled; one of: alpha, beta, gamma" for n in range(1, 61)]
        long = "TS-1: if Q1 is answered (a) the row would break the plan contract: " + "; ".join(errors) + " - the strategist's rework repairs this row"
        planning_contract.variant_errors = lambda *a, **k: [finding("TS-1", long), finding("TS-2", ""), finding("TS-3", "short one")]
        line = remark_line(task)
        text = (project / package_of(line)).read_text(encoding="utf-8")
        ceiling = stage_done.S3_REMARK_LINE_MAX
        check(f"t10: the message is longer than the {ceiling}-character line ceiling ({len(long)})", len(long) > ceiling)
        check(f"t10: no line of the package is longer than {ceiling} characters", all(len(ln) <= ceiling for ln in text.split("\n")),
              str(max(len(ln) for ln in text.split("\n"))))
        flat = " ".join(text.split())
        check("t10: every one of the sixty errors is in the package, whole", all(e in flat for e in errors))
        check_in("t10: and the tail of the message", "the strategist's rework repairs this row", flat)
        check_in("t10: a finding with no message is still a line", "- (the finding has no message)", text)
        check_in("t10: the short one is one line", "\n- short one\n", text)
        check_in("t10: the head counts all three", "# 3 S3 question-branch finding(s)", text)
    finally:
        planning_contract.variant_errors = saved
        cleanup(project)


# --- t11: a malformed stages table -------------------------------------------------------------------------------

def a_malformed_stages_table_does_not_stop_the_s3_exit():
    """KILLS: a `rework_mode` reader that raises on a table whose root is a list, whose `stages` is not a list or whose row
    is not an object (the S3 exit crashed after the package was written, P1); a malformed table read as `resume`."""
    import tempfile
    import contract
    shapes = {"root is a list": [{"id": "S3", "rework_mode": "resume"}], "stages is a number": {"stages": 5},
              "stages is an object": {"stages": {"id": "S3", "rework_mode": "resume"}},
              "a row is a string": {"stages": ["S3"]}, "a row is a list": {"stages": [["S3", "resume"]]},
              "root is a string": "S3", "root is null": None}
    project, task, plan = s3_story(bad_rows("TS-1"))
    real = contract.rework_mode
    try:
        with tempfile.TemporaryDirectory(prefix="qa-s3-remarks-stages-") as folder:
            for name, shape in shapes.items():
                table = Path(folder) / "stages.json"
                table.write_text(json.dumps(shape), encoding="utf-8")
                contract.rework_mode = lambda stage, path=None, _t=table: real(stage, _t)
                try:
                    text = stage_done.rework_launch_text("S3")
                    line = remark_line(task)
                    raised = ""
                except Exception as exc:  # noqa: BLE001 - the check is that nothing is raised
                    text = line = ""
                    raised = f"{type(exc).__name__}: {exc}"
                check(f"t11: {name}: nothing is raised on the S3 exit", not raised, raised)
                check_in(f"t11: {name}: the card is launched as a NEW agent (the default, fresh)", "as a NEW agent", text)
                check(f"t11: {name}: and the S3 line is still the remark line with its package", line.startswith(PREFIX) and package_of(line) != "", line[:160])
    finally:
        contract.rework_mode = real
        cleanup(project)


def main():
    the_line_names_one_package_and_one_door()
    a_root_with_a_space_is_quoted_and_the_edges_say_nothing_or_one_line()
    rows_are_named_by_id_and_a_row_without_one_is_not_a_door()
    the_same_bytes_are_the_same_file()
    a_package_over_the_read_limit_says_so_to_the_conductor_and_to_the_role()
    a_package_that_cannot_be_written_puts_the_findings_in_the_line()
    finish_keeps_the_remark_line_whatever_follows_it()
    not_checked_lines_carry_the_prefix_and_are_kept()
    the_form_refusal_lists_every_problem()
    the_texts_say_the_rule_by_rework_mode()
    the_printed_door_runs_and_the_card_carries_the_package()
    a_long_finding_wraps_and_loses_nothing()
    a_malformed_stages_table_does_not_stop_the_s3_exit()
    the_exit_refuses_what_the_remarks_used_to_report()
    finish("test_s3_remarks")


if __name__ == "__main__":
    main()
