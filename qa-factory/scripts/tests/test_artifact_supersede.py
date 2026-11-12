#!/usr/bin/env python3
"""FR-57 / B-012: the door of a ban that meets an interrupted artifact.

TP1-13877, 28.09: a network failure left `test-plan.json` with 3 rows, the guard refused a Write
over a plan that holds rows, and the only way on was a person deleting the file by hand. The guard
now names the way out to a role that can use it, and `artifact_supersede.py` is that way: the file
moves to `<name>.superseded[-N]` and the story's warnings say what was set aside, by whom and why.

  S1  the guard names the command and the row commands; after the command the Write is not refused,
      the old bytes are in `.superseded`, and `pipeline.json` gained exactly one warning line;
  S2  a second set-aside of the same path is `.superseded-2`, the first is untouched;
  S3  every refusal names what is wrong and what to do (missing, already set aside, a directory, a
      path outside the story, a file another writer owns, a role that is not its writer, no reason,
      a reason of two lines);
  S4  the reason is limited to 200 characters: 200 passes, 201 is refused;
  S5  a story that cannot record the warning gets its file back, and the refusal says so;
  S6  the rewrite guard names the door to a role that has Bash and not to one that has none (FR-2).
"""
import contextlib
import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, finish  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import guard_pre_tool as G  # noqa: E402

TASK = "QA-1"
PLAN = {"rows": [{"id": "TS-1", "disposition": "automate"}, {"id": "TS-2", "disposition": "manual-human"},
                 {"id": "TS-3", "disposition": "automate"}]}
REASON = "the file holds 3 rows of a run that was cut off; none match the register"


def blocked(check_fn, path: Path, agent: str = "") -> str:
    """What a guard check prints for a Write over `path`, or '' when it lets it through."""
    event = {"tool_name": "Write", "tool_input": {"file_path": str(path)}}
    if agent:
        event["agent_type"] = agent
    captured = io.StringIO()
    try:
        with contextlib.redirect_stderr(captured):
            check_fn(event, {})
    except SystemExit:
        pass
    return captured.getvalue()


def story(with_pipeline: bool = True):
    root = harness.temp_project("qa-supersede-")
    task_root = root / "qa-factory" / "artifacts" / TASK
    (task_root / "work").mkdir(parents=True)
    if with_pipeline:
        (task_root / "pipeline.json").write_text(json.dumps({"ticket": TASK, "stages": {}, "gates": {}}), encoding="utf-8")
    plan = task_root / "work" / "test-plan.json"
    plan.write_text(json.dumps(PLAN), encoding="utf-8")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    return root, task_root, plan, env


def supersede(root, env, *args, path="work/test-plan.json", role="qa-test-strategist", reason=REASON):
    return harness.run_script("artifact_supersede.py", "--task", TASK, "--path", path, "--role", role, "--reason", reason,
                              *args, cwd=root, env=env)


def warnings(task_root: Path) -> list:
    return json.loads((task_root / "pipeline.json").read_text(encoding="utf-8")).get("warnings") or []


def s1_and_s2():
    root, task_root, plan, env = story()
    try:
        said = blocked(G.plan_write_check, plan)
        check_in("S1: the guard names the supersede command", "artifact_supersede.py", said)
        check_in("S1: and the way to continue the plan", "--add-row", said)
        check_in("S1: with the path it refused, relative to the story", "--path work/test-plan.json", said)
        check_in("S1: and the story", f"--task {TASK}", said)
        old = plan.read_bytes()
        out = supersede(root, env)
        check_eq("S1: the command succeeds", out.returncode, 0)
        check_in("S1: it prints the new name", "test-plan.json.superseded", out.stdout)
        check_in("S1: and says the next Write is the first", "your next Write of work/test-plan.json is its first", out.stdout)
        check_eq("S1: after it the Write is not refused", blocked(G.plan_write_check, plan), "")
        aside = task_root / "work" / "test-plan.json.superseded"
        check_eq("S1: the old bytes are in .superseded", aside.read_bytes() if aside.exists() else None, old)
        check("S1: the path is free", not plan.exists())
        lines = warnings(task_root)
        check_eq("S1: pipeline.json gained exactly one warning", len(lines), 1)
        check_in("S1: it names the stage, the path, the new name, the size, the role and the reason",
                 f"S3: work/test-plan.json set aside as test-plan.json.superseded (3 rows) by qa-test-strategist: {REASON}", lines)

        plan.write_text(json.dumps({"rows": [{"id": "TS-9"}]}), encoding="utf-8")
        out = supersede(root, env)
        check_eq("S2: a second set-aside succeeds", out.returncode, 0)
        check("S2: as .superseded-2", (task_root / "work" / "test-plan.json.superseded-2").is_file())
        check_eq("S2: the first is untouched", aside.read_bytes(), old)
        plan.write_text("{}", encoding="utf-8")
        out = supersede(root, env)
        check("S2: and the third is -3", (task_root / "work" / "test-plan.json.superseded-3").is_file())
        check_eq("S2: one warning per set-aside", len(warnings(task_root)), 3)
        # the md copy: the guard names the path it watches, and the command accepts it
        md = task_root / "work" / "test-plan.md"
        md.write_text("| TS-1 | smoke |\n", encoding="utf-8")
        said = blocked(G.plan_write_check, md)
        check_in("S1: the plan's markdown copy is refused with the door too", "--path work/test-plan.md", said)
        out = supersede(root, env, path="work/test-plan.md")
        check_eq("S1: and the door opens for it (the registry keeps it at the task root)", out.returncode, 0)
        check_in("S1: in the plan's own stage", "S3: work/test-plan.md set aside", " ".join(warnings(task_root)))
    finally:
        harness.cleanup(root)


def s3_refusals():
    root, task_root, plan, env = story()
    try:
        # a file that was never there
        out = supersede(root, env, path="work/requirements-register.md", role="qa-requirements-tester")
        check_eq("S3: a missing file is refused", out.returncode, 2)
        check_in("S3: and says there is nothing to set aside", "does not exist", out.stderr)
        # already set aside
        supersede(root, env)
        out = supersede(root, env)
        check_eq("S3: a file that was already set aside is refused", out.returncode, 2)
        check_in("S3: and says where it went", "already set aside as `test-plan.json.superseded`", out.stderr)
        check_in("S3: and that the next Write is the first", "Your next Write of it is its first", out.stderr)
        # a directory
        (task_root / "work" / "test-cases").mkdir()
        out = supersede(root, env, path="work/test-cases", role="qa-case-designer")
        check_eq("S3: a directory is refused", out.returncode, 2)
        check_in("S3: with the file-at-a-time instruction", "is a directory", out.stderr)
        # outside the task root
        (task_root.parent / "other.json").write_text("{}", encoding="utf-8")
        out = supersede(root, env, path="../other.json")
        check_eq("S3: a path outside the story is refused", out.returncode, 2)
        check_in("S3: and names what it wants", "not inside this story's task root", out.stderr)
        out = supersede(root, env, path=str(task_root.parent / "other.json"))
        check_eq("S3: an absolute path outside is refused too", out.returncode, 2)
        out = supersede(root, env, path="project:obligations.md", role="qa-retro-analyst")
        check_eq("S3: a `project:` path is not the story's", out.returncode, 2)
        check("S3: and the file outside was not moved", (task_root.parent / "other.json").is_file())
        # a file another writer owns
        manifest = task_root / "work" / "automation-manifest.json"
        manifest.write_text('{"tests": []}', encoding="utf-8")
        out = supersede(root, env, path="work/automation-manifest.json", role="qa-automator")
        check_eq("S3: the manifest (a code writer) is refused", out.returncode, 2)
        check_in("S3: and the real writer is named", "manifest_put.py", out.stderr)
        check("S3: and stays where it was", manifest.is_file())
        # a role that is not the writer
        plan.write_text(json.dumps(PLAN), encoding="utf-8")
        out = supersede(root, env, role="qa-scout")
        check_eq("S3: another role's file is refused", out.returncode, 2)
        check_in("S3: with its writer", "qa-test-strategist (the role)", out.stderr)
        check("S3: and nothing was moved", plan.is_file())
        (task_root / "work" / "notes-of-nobody.txt").write_text("x", encoding="utf-8")
        out = supersede(root, env, path="work/notes-of-nobody.txt", role="qa-scout")
        check_eq("S3: a file the registry does not know has no writer to match: refused", out.returncode, 2)
        check_in("S3: and says the registry names none", "names no writer", out.stderr)
        # the reason
        out = supersede(root, env, reason="   ")
        check_eq("S3: an empty reason is refused", out.returncode, 2)
        check_in("S3: and asks for one line", "--reason is empty", out.stderr)
        out = supersede(root, env, reason="first line\nsecond line")
        check_eq("S3: a reason of two lines is refused", out.returncode, 2)
        check_in("S3: and says one line", "more than one line", out.stderr)
        check("S3: no refusal moved the plan", plan.is_file())
        check_eq("S3: no refusal wrote a warning", len(warnings(task_root)), 1)
        check_in("S3: every refusal ends with where an impossible one goes", "in your findings", out.stderr)
    finally:
        harness.cleanup(root)


def s3b_task_root_must_be_the_storys_own():
    root, task_root, plan, env = story()
    try:
        other = root / "elsewhere" / TASK
        other.mkdir(parents=True)
        (other / "work").mkdir()
        (other / "work" / "test-plan.json").write_text(json.dumps(PLAN), encoding="utf-8")
        out = supersede(root, env, "--task-root", str(other))
        check_eq("S3: a --task-root that is not the story's own is refused", out.returncode, 2)
        check_in("S3: the pair is refused as two different folders", "name different folders", out.stderr)
        check_in("S3: naming both paths (the --task-root as given)", str(other), out.stderr)
        check_in("S3: and the story's", str(task_root.resolve()), out.stderr)
        check("S3: nothing was moved", (other / "work" / "test-plan.json").is_file() and plan.is_file())
        check_eq("S3: no warning written", warnings(task_root), [])
        out = supersede(root, env, "--task-root", str(task_root))
        check_eq("S3: the story's own --task-root is accepted", out.returncode, 0)
    finally:
        harness.cleanup(root)


def s4_the_reason_limit():
    root, task_root, plan, env = story()
    try:
        out = supersede(root, env, reason="r" * 201)
        check_eq("S4: 201 characters are refused", out.returncode, 2)
        check_in("S4: and the limit is named", "the limit is 200", out.stderr)
        check("S4: the plan is where it was", plan.is_file())
        out = supersede(root, env, reason="r" * 200)
        check_eq("S4: 200 characters pass", out.returncode, 0)
        check_in("S4: and the whole reason is on record", "r" * 200, " ".join(warnings(task_root)))
    finally:
        harness.cleanup(root)


def s5_a_story_that_cannot_record_it():
    root, task_root, plan, env = story(with_pipeline=False)
    try:
        old = plan.read_bytes()
        out = supersede(root, env)
        check_eq("S5: with no pipeline.json the command refuses", out.returncode, 2)
        check_in("S5: and says the warning could not be recorded", "not set aside", out.stderr)
        check_eq("S5: the file is back where it was, byte for byte", plan.read_bytes() if plan.exists() else None, old)
        check("S5: and no .superseded is left behind", not list((task_root / "work").glob("test-plan.json.superseded*")))
    finally:
        harness.cleanup(root)


def s6_the_rewrite_guard_names_the_door_to_a_role_that_can_use_it():
    root, task_root, plan, env = story()
    try:
        manifest = task_root / "work" / "context-manifest.json"
        manifest.write_text('{"ticket": "QA-1"}', encoding="utf-8")
        with_bash = blocked(G.artifact_rewrite_check, manifest, agent="qa-scout")
        check_in("S6: a role with Bash is told the door", "artifact_supersede.py", with_bash)
        check_in("S6: with its own path", "--path work/context-manifest.json", with_bash)
        check_in("S6: the point-edit instruction is still there", "Change what changed instead", with_bash)
        without = blocked(G.artifact_rewrite_check, manifest, agent="qa-case-critic")
        check_in("S6: a role with no Bash still gets the refusal", "PRE-TOOL GUARD", without)
        check_not_in("S6: but is not sent to a command it cannot run", "artifact_supersede.py", without)
        plan_without = blocked(G.plan_write_check, plan, agent="qa-test-strategist")
        check_not_in("S6: the strategist (Read, Grep, Glob, Write, Edit) is not sent to it either", "artifact_supersede.py", plan_without)
        check_in("S6: it is sent to Edit", "Edit", plan_without)
        check_in("S6: a plan refusal for a role with Bash carries the continuation line", "continue it",
                 blocked(G.plan_write_check, plan, agent="qa-scout"))
    finally:
        harness.cleanup(root)


s1_and_s2()
s3_refusals()
s3b_task_root_must_be_the_storys_own()
s4_the_reason_limit()
s5_a_story_that_cannot_record_it()
s6_the_rewrite_guard_names_the_door_to_a_role_that_can_use_it()
finish("test_artifact_supersede")
