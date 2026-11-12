#!/usr/bin/env python3
"""A refusal a role's or code's own work closes says so in the marker, and the driver routes on it.

P4b, measured on TP1-13797 run 5: `story_step finish` refused with "the manifest carries no
`review_receipt_ref` for R-1-OB1 ... write the immutable S5 review window and put its
task-relative path there through `manifest_put.py`. **These are the review's own receipts, not the
person's to produce.**" The factory said whose work it was in plain words, and the refusal still
travelled to the conductor and from there to the person, because the driver's table knew no such
wording. `role_cli.REPAIR_MARKER` is the one sentence it does know
(`story_run.match_known`, `story_run._mechanical`), and the scripts that can raise this class of
refusal are `handoff_check`, `manifest_put`, `plan_row`, `role_digest` and the controller — plus
`story_step`, `window_record` and `node_ids`, which did not carry it.

What is proved here:
  * the refusals of those three scripts are RUN, and their real text routes to `resume_repair`;
  * a refusal that belongs to a person keeps routing to `ask_person` — the marker is not a blanket;
  * nothing anywhere pastes the marker's sentence as a literal, because a driver matches it
    exactly and a paraphrase is what P4b is about;
  * the two refusals a test cannot reach cheaply (the runner's node-id block, the sandbox's
    mismatch) name the constant in the statement that builds them - a source check, and it says
    so: it holds the anchor phrase, not a line number.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import node_ids  # noqa: E402
import story_run  # noqa: E402
from role_cli import PERSON_MARKER, REPAIR_MARKER  # noqa: E402


def routed(name: str, text: str, expected: str = "resume_repair") -> None:
    """The marker is in the text, and the driver's own router agrees about what it means."""
    check_in(f"{name} carries the marker", REPAIR_MARKER, text)
    known = story_run.match_known(text)
    check_eq(f"and the driver routes {name} to {expected}",
             known[1] if known else "<no match>", expected)


def seed(root: Path, ticket: str) -> Path:
    task = root / "qa-factory" / "artifacts" / ticket
    (task / "work").mkdir(parents=True)
    (task / "pipeline.json").write_text(json.dumps(
        {"ticket": ticket, "size": "S", "environment": "local", "implementation_source": "diff",
         "stages": {"S0": {"status": "done"}}, "gates": {}, "halts": []}), encoding="utf-8")
    return task


def refusals_of_the_three_scripts() -> None:
    root = harness.temp_project("qa-repair-marker-")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    try:
        harness.use_project(root)
        seed(root, "QA-7")

        # story_step: a role that is not the stage's, and a dispatch id that is not this story's.
        out = harness.run_script("story_step.py", "start", "--task", "QA-7", "--stage", "S1",
                                 "--role", "qa-automator", cwd=root, env=env)
        check_eq("story_step refuses a role the stage does not declare", out.returncode, 2)
        routed("a role outside the stage", out.stdout + out.stderr)
        check_in("and names the roles it does declare", "qa-scout", out.stdout)

        out = harness.run_script("story_step.py", "finish", "--task", "QA-7",
                                 "--dispatch-id", "S1-qa-scout-9", "--digest", "d",
                                 cwd=root, env=env)
        check_eq("story_step refuses an unknown dispatch", out.returncode, 2)
        routed("an unknown dispatch at finish", out.stdout + out.stderr)

        # window_record: the ticket is not this story's.
        out = harness.run_script("window_record.py", "--task", "QA-NOSUCH",
                                 "--dispatch", "S5-qa-code-critic-1", cwd=root, env=env)
        check("window_record refuses a ticket with no artifacts", out.returncode != 0,
              out.stdout + out.stderr)
        routed("a ticket with no story artifacts", out.stdout + out.stderr)

        # node_ids: called without the pieces it needs. Its own module is standard library only,
        # so it fetches the constant at the moment it prints, and this is that moment.
        out = harness.run_script("node_ids.py", "--cwd", ".", "--ids", "tests/t.py::a",
                                 cwd=root, env=env)
        check_eq("node_ids refuses a call with no test command", out.returncode, 2)
        routed("node_ids without a command", out.stdout + out.stderr)
        check_eq("and the constant it fetched is the one the driver matches",
                 node_ids.repair_marker(), REPAIR_MARKER)
    finally:
        cleanup(root)


def a_persons_boundary_is_still_a_persons() -> None:
    """The marker is not a blanket: it says "not the person's", so it must not be on a refusal
    that is. These four are the ones run 5 put to a person, and every one of them still goes
    there — the first because it is the person's money, the last because only a person's word
    can accept a gap in the material a story is about."""
    for text, expected in (
            ("STORY BUDGET exceeded: $120 of $100", "ask_person"),
            ("readiness: capability `playwright` missing", "ask_person"),
            ("executor_unavailable: no host can run this profile", "ask_person"),
            (f"the source review is not accepted. {PERSON_MARKER}.", "ask_person")):
        known = story_run.match_known(text)
        check_eq(f"{text[:40]!r} still reaches the person",
                 known[1] if known else "<no match>", expected)
        check_not_in("and carries no repair marker", REPAIR_MARKER, text)


def the_marker_is_never_pasted() -> None:
    """One sentence, one owner: a script prints the constant, never a copy of it. A copy drifts,
    and the driver matches the sentence — `role_cli` says so and this is what holds it."""
    pasted = []
    for path in sorted(harness.SCRIPTS.glob("*.py")):
        if path.name == "role_cli.py":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for quote in ('"' + REPAIR_MARKER, "'" + REPAIR_MARKER):
            if quote in text:
                pasted.append(path.name)
    check_eq("no script carries the marker's sentence as a literal", sorted(set(pasted)), [])
    check_in("and role_cli is where it is defined", 'REPAIR_MARKER = "' + REPAIR_MARKER,
             (harness.SCRIPTS / "role_cli.py").read_text(encoding="utf-8"))


def the_two_that_a_test_cannot_reach_cheaply() -> None:
    """The runner's node-id block and the sandbox's mismatch both need a real pytest collect
    inside a prepared sandbox, so they are held to their source instead: the statement that
    builds each refusal names the constant. Keyed on the anchor phrase the message carries, not
    on a line number — the same way the controller walk is held (design/controller-blocks.md)."""
    for script, anchor in (("run_suite.py", "Take the spelling"),
                           ("red_sandbox.py", "not the person's to repair")):
        text = (harness.SCRIPTS / script).read_text(encoding="utf-8")
        where = text.find(anchor)
        check(f"{script} still carries the refusal this check is about", where > 0, str(where))
        window = text[max(0, where - 1200):where + 1200]
        check_in("and its statement names REPAIR_MARKER", "REPAIR_MARKER", window)


def the_s5_exit_gate_refusal_is_the_roles_repair() -> None:
    """cmp2, TP1-15045, 06:19: the S5 exit gate's `s5_precheck` refused with "no run block
    carries a result row ..." - a repair the automator could make itself once the stand was back -
    and its footer said "These are repairs, not questions" in words the driver does not match, so
    the refusal went to the conductor three times and then to the person. The real script is run
    here on a story whose one test has no run block, and its real text is routed."""
    root = harness.temp_project("qa-repair-marker-s5-")
    try:
        task = root / "qa-factory" / "artifacts" / "QA-500"
        (task / "work" / "test-cases").mkdir(parents=True)
        (task / "work" / "run-blocks").mkdir(parents=True)
        (task / "work" / "automation-manifest.json").write_text(json.dumps(
            {"tests": [{"case": "TC-500", "file": "tests/test_validate.py",
                        "instance_id": "TC-500", "status": "green"}]}), encoding="utf-8")
        (root / "tests").mkdir(parents=True, exist_ok=True)
        (root / "tests" / "test_validate.py").write_text(
            "def test_ok(client):\n    '''@case TC-500'''\n    assert client\n", encoding="utf-8")
        out = harness.run_script("s5_precheck.py", "--task-root", str(task), cwd=root)
        check_eq("s5_precheck refuses a story whose test has no run block", out.returncode, 1)
        check_in("and it is a finding, not a crash", "finding(s) for the author", out.stdout)
        footer = [line for line in out.stdout.splitlines()
                  if line.startswith("These are repairs, not questions")]
        check_eq("the footer is ONE line of stdout", len(footer), 1)
        routed("the S5 exit gate's refusal", out.stdout)
        check_in("the marker sits on the footer line, with the sentence that says who does what",
                 REPAIR_MARKER, footer[0] if footer else "")
        check_not_in("and the person's marker is not there", PERSON_MARKER, out.stdout)
    finally:
        cleanup(root)


def main() -> None:
    refusals_of_the_three_scripts()
    a_persons_boundary_is_still_a_persons()
    the_marker_is_never_pasted()
    the_two_that_a_test_cannot_reach_cheaply()
    the_s5_exit_gate_refusal_is_the_roles_repair()
    finish("test_repair_marker")


if __name__ == "__main__":
    main()
