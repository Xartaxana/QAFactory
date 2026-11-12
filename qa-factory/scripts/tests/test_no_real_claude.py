#!/usr/bin/env python3
"""No package test may start a real `claude -p` (t-036).

story_run's Driver takes its executable from STORY_RUN_CLAUDE and, when that is unset, from the
`claude` on PATH. test_human_questions took a conductor round trip through `take_answer` with no
stub of its own, so on a machine that has `claude` every run of it started a paid session that
acted in a temp project. harness.py now points STORY_RUN_CLAUDE at tests/no_claude.py unless a
test names its own stub; what is proved here:

  * with the variable unset before harness is imported, the Driver's `claude` is no_claude.py;
  * a conductor question answered with no stub of its own reaches no_claude's refusal (exit 97,
    written to NO_CLAUDE_LOG - no session was started); since C1-1 the person is not shown that
    refusal but the priced fallback question, and the unusable answer is recorded as the
    factory's own defect;
  * negative control: a copy of harness.py WITHOUT the guard leaves the variable unset (shown in a
    child process that constructs no Driver), so the assertions above can fail.

NO_CLAUDE_LOG: when the caller sets it, this test appends to that file (so a whole run can be
audited afterwards); otherwise it uses a file of its own.
"""
import json
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

# Before harness is imported: this is the state the guard exists for.
os.environ.pop("STORY_RUN_CLAUDE", None)
os.environ.pop("STORY_RUN_CODEX", None)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import story_run  # noqa: E402

NO_CLAUDE = Path(harness.__file__).resolve().parent / "no_claude.py"
MARKER = "a test tried to start a real claude session"
PROBE = "import os; print(os.environ.get('STORY_RUN_CLAUDE') or '<unset>')"
PROBE_CODEX = "import os; print(os.environ.get('STORY_RUN_CODEX') or '<unset>')"


def child_value(directory: Path, probe: str = PROBE, variable: str = "STORY_RUN_CLAUDE") -> str:
    """The variable as a child process sees it after importing the harness in `directory`."""
    env = {key: value for key, value in os.environ.items() if key != variable}
    done = subprocess.run([sys.executable, "-B", "-c", "import harness; " + probe],
                          capture_output=True, text=True, cwd=str(directory), env=env,
                          timeout=60, encoding="utf-8", errors="replace")
    return (done.stdout or "").strip() or f"<child failed: {done.stderr[-300:]}>"


def main() -> None:
    task = "QA-9"
    check_eq("harness sets STORY_RUN_CLAUDE to no_claude.py when nothing was set",
             os.environ.get("STORY_RUN_CLAUDE"), str(NO_CLAUDE))
    check_eq("harness sets STORY_RUN_CODEX to no_claude.py when nothing was set (CX1-15, F-7)",
             os.environ.get("STORY_RUN_CODEX"), str(NO_CLAUDE))

    own_log = None
    if not os.environ.get("NO_CLAUDE_LOG"):
        handle, name = tempfile.mkstemp(prefix="no-claude-log-", suffix=".txt")
        os.close(handle)
        own_log = os.environ["NO_CLAUDE_LOG"] = name
    log = Path(os.environ["NO_CLAUDE_LOG"])
    before = log.read_text(encoding="utf-8").splitlines() if log.exists() else []

    root = harness.temp_project("qa-no-real-claude-")
    try:
        harness.use_project(root)
        task_root = root / "qa-factory/artifacts" / task
        (task_root / "work").mkdir(parents=True)
        (task_root / "pipeline.json").write_text(json.dumps(
            {"ticket": task, "size": "S", "environment": "local",
             "stages": {"S0": {"status": "done"}, "S1": {"status": "done"}, "S2": {"status": "done"},
                         "S3": {"status": "running"}}, "gates": {}, "halts": []}), encoding="utf-8")
        ns = types.SimpleNamespace(task=task, answer=None, until="end", dry_run=False, model="sonnet",
                                   plugin_dir=None, project=str(root), mr=None, branch=None, commit=None,
                                   ungrounded=False, ticket_file=None, env=None, branch_suffix="",
                                   max_boundaries=10)
        driver = story_run.Driver(ns)
        check_eq("a Driver built with no stub of its own points at no_claude.py",
                 driver.claude, [sys.executable, str(NO_CLAUDE)])
        on_codex = story_run.Driver(types.SimpleNamespace(**dict(vars(ns), host="codex", model=None)))
        check_eq("a Driver on the Codex host with no stub of its own points at no_claude.py too",
                 (on_codex.host, on_codex.claude), ("codex", [sys.executable, str(NO_CLAUDE)]))

        question = ("The plan stage (S3) stopped and needs your word. Should the factory go on as it "
                    "is, retry, or stop the story here?")
        driver.ask(story_run.Person("conductor", question, "S3", details="a refusal of the factory"))
        answer = task_root / "their-answer.md"
        answer.write_text("Accept it as it is and carry on.", encoding="utf-8")
        defect_calls = []                  # the driver's own defect_found calls (passed through, only recorded)
        real_py = driver.py

        def spy(script, *args, **kwargs):
            if script == "log_append.py" and "defect_found" in args:
                defect_calls.append(args)
            return real_py(script, *args, **kwargs)
        driver.py = spy
        ended, caught = "", None
        try:
            driver.take_answer(answer)
            ended = "returned"
        except (story_run.Person, story_run.Stop, story_run.Refusal) as exc:
            caught = exc
            ended = str(getattr(exc, "text", "") or getattr(exc, "reason", "") or exc)
        # C1-1 (P22): the guard's refusal is an unusable conductor answer; the person never reads it raw - the seam records
        # it as the factory's own defect and asks the PRICED fallback question (conductor-actions.json `fallback`).
        check("a conductor answer with no stub ends with a Person, not a raw refusal",
              isinstance(caught, story_run.Person), repr(caught))
        check_eq("that Person is a conductor question with the three standing words",
                 (getattr(caught, "kind", None), tuple(getattr(caught, "offered", ()))),
                 ("conductor", ("retry", "go on", "stop")))
        check_in("the question is the PRICED fallback (heading present, so a data regression shows)",
                 "## What each answer costs and does", ended)
        check_eq("with the three price labels under each of the three options",
                 tuple(ended.count(f"\n{label}: ") for label in ("the factory", "you", "the story")), (3, 3, 3))
        after = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
        added = after[len(before):]
        check_eq("and NO_CLAUDE_LOG got exactly one line for it", len(added), 1)
        check("that line names the call it refused", bool(added) and added[0].startswith(MARKER)
              and "--output-format" in added[0], str(added))
        check_in("positive control: the marker IS in the guard's log line", MARKER, added)
        check_not_in("and it is NOT in the person's text (the refusal stays with the factory)", MARKER, ended)
        # The defect (no_move_defect): ONE log_append defect_found call for the unusable answer, and ONE `unusable` mark in
        # conductor.jsonl. (The call is pinned, not the journal row it asks for: see the report - log_append rejects it today.)
        check_eq("the unusable answer is filed as the factory's defect exactly once", len(defect_calls), 1)
        notes = defect_calls[0][defect_calls[0].index("--notes") + 1] if defect_calls and "--notes" in defect_calls[0] else ""
        check("that defect names the owner and the unusable answer",
              notes.startswith("owner: factory") and "the conductor answered `_unreadable`" in notes, notes)
        conductor_rows = [json.loads(line) for line in (task_root / "state" / "conductor.jsonl").read_text(encoding="utf-8").splitlines()
                          if line.strip()]
        unusable = [row for row in conductor_rows if row.get("action") == "unusable"]
        check_eq("conductor.jsonl carries exactly one `unusable` mark, for the same rule",
                 [row.get("unusable") for row in unusable], ["the conductor answered `_unreadable`"])
        journal = task_root / "state" / "driver-runs.jsonl"
        rows = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()
                if line.strip()] if journal.exists() else []
        check_eq("the driver recorded that call as a failed one (exit 97)",
                 [(row.get("kind"), row.get("exit_code")) for row in rows if row.get("kind") != "launched"],
                 [("conductor", 97)])   # a `launched` row (t-363 B2) is the call's start, not a second call
    finally:
        harness.cleanup(root)
        if own_log:
            os.environ.pop("NO_CLAUDE_LOG", None)
            try:
                os.unlink(own_log)
            except OSError:
                pass

    # --- negative control: the same harness without the guard, and no Driver anywhere ---------
    source = Path(harness.__file__).read_text(encoding="utf-8")
    guard = ('if not os.environ.get("STORY_RUN_CLAUDE"):\n'
             '    os.environ["STORY_RUN_CLAUDE"] = str(Path(__file__).resolve().parent / "no_claude.py")\n')
    guard_codex = ('if not os.environ.get("STORY_RUN_CODEX"):\n'
                   '    os.environ["STORY_RUN_CODEX"] = str(Path(__file__).resolve().parent / "no_claude.py")\n')
    check("the guard is in harness.py as expected (the control below removes exactly it)", guard in source)
    stripped = source.replace(guard, "").replace(guard_codex, "")
    check("the stripped copy no longer mentions no_claude.py in code", 'no_claude.py")' not in stripped)
    copy_dir = harness.temp_dir("qa-harness-noguard-")
    try:
        (copy_dir / "harness.py").write_text(stripped, encoding="utf-8")
        check_eq("negative control: a harness copy WITHOUT the guard leaves STORY_RUN_CLAUDE unset",
                 child_value(copy_dir), "<unset>")
        (copy_dir / "harness.py").write_text(source, encoding="utf-8")
        check_eq("positive control: a copy WITH the guard sets it",
                 Path(child_value(copy_dir)).name, "no_claude.py")
        check("the Codex guard is in harness.py as expected (the control below removes exactly it)", guard_codex in source)
        (copy_dir / "harness.py").write_text(source.replace(guard_codex, ""), encoding="utf-8")
        check_eq("negative control: a harness copy WITHOUT the Codex guard leaves STORY_RUN_CODEX unset",
                 child_value(copy_dir, PROBE_CODEX, "STORY_RUN_CODEX"), "<unset>")
        (copy_dir / "harness.py").write_text(source, encoding="utf-8")
        check_eq("positive control: a copy WITH the Codex guard sets it",
                 Path(child_value(copy_dir, PROBE_CODEX, "STORY_RUN_CODEX")).name, "no_claude.py")
    finally:
        harness.cleanup(copy_dir)

    harness.finish("test_no_real_claude")


if __name__ == "__main__":
    main()
