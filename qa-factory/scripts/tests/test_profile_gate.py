"""A project that cannot run a test is told so before gate A, not inside S5.

TP2-2553 (installed plugin 0.7.9): `qa-factory/config.json` carried no `profiles`.
`gate_preflight.s5_profiles` answers `{}` for such a config, so the executor question asked
nothing; `readiness.compute` validated profiles only when the key was present, so S0 was
green; and the first thing that said anything was `run_suite.py --mine` refusing every run
from inside S5, after which every typed request of that story was assembled by hand.

The gap belongs to the onboarding, so all three places now name the onboarding: the gate asks
one question with three answers, readiness reports the execution profile as not_configured
with the onboarding command in its step, and the runner's refusal says whose gap it is.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup,  # noqa: E402
                     finish, run_script, temp_dir, use_project)

sys.path.insert(0, str(SCRIPTS))

import gate_preflight  # noqa: E402
import readiness  # noqa: E402

TICKET = "TP2-2553"


def plan_row(row_id: str, disposition: str = "automate") -> dict:
    return {"id": row_id, "requirement_ids": ["R-1"], "level": "api",
            "disposition": disposition, "impact": "moderate", "likelihood": "medium",
            "design_review_required": False, "confidence": "medium",
            "risk_rationale": "a permission seam", "coverage_refs": [], "unknowns": [],
            "verification_depth": "normal", "required_scenarios": ["a denied caller"],
            "test_level_rationale": "HTTP contract, no UI involved"}


PROFILE = {"profile_id": "api", "selected": True, "roots": {"test": "tests"},
           "capabilities": ["api"], "reporter": {"kind": "pytest"},
           "commands": {"one_test": {"argv": [sys.executable, "-c", "pass", "<test-file>"],
                                     "cwd": "."}}}


def story(prefix: str, *, config: dict | None = None, disposition: str = "automate",
          pipeline_extra: dict | None = None) -> Path:
    """A project parked where 2553 was: S4 written, gate A not asked, two automate cases."""
    root = temp_dir(prefix)
    task_root = root / "qa-factory" / "artifacts" / TICKET
    (task_root / "work" / "test-cases" / "api").mkdir(parents=True)
    (task_root / "state").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "qa-factory" / "config.json").write_text(json.dumps(
        dict({"schema_version": 1, "tests_root": "tests", "app_root": "."}, **(config or {}))),
        encoding="utf-8")
    (task_root / "work" / "test-plan.json").write_text(
        json.dumps([plan_row("TS-1", disposition), plan_row("TS-2", disposition)]),
        encoding="utf-8")
    (task_root / "pipeline.json").write_text(json.dumps(
        dict({"ticket": TICKET, "stages": {"S4": {"status": "done"}}}, **(pipeline_extra or {}))),
        encoding="utf-8")
    for number, row in (("001", "TS-1"), ("002", "TS-2")):
        (task_root / "work" / "test-cases" / "api" / f"TC-{number}.md").write_text(
            f"---\nid: TC-{number}\n---\n\nPlan row: {row}\n\n## Then\n1. it answers 403.\n",
            encoding="utf-8")
    return root


def executor_findings(root: Path) -> list:
    use_project(root)
    rehearsal = gate_preflight.Rehearsal(root / "qa-factory" / "artifacts" / TICKET, "A")
    rehearsal.check_s5_executor()
    return rehearsal.findings


def test_the_gate_asks_before_it_refuses() -> None:
    root = story("qa-profile-gate-none-", config={"profiles": []})
    try:
        found = executor_findings(root)
        check_eq("a story with automation and no profile is exactly one question",
                 len(found), 1)
        finding = found[0]
        check_eq("asked under the executor check", finding["check"], "s5_executor")
        check_eq("and it is the person's call, not a repair the factory owes",
                 finding["class"], gate_preflight.PERSON_DECIDES)
        check_in("it names the file the profile is missing from",
                 "qa-factory/config.json", finding["message"])
        check_in("and what the story would otherwise hit inside S5",
                 "mine_refused", finding["message"])
        check_in("both cases are named", "TC-001", finding["message"])
        check_in("and the second one too", "TC-002", finding["message"])
        check_eq("the cases travel machine-readable as well",
                 finding["cases"], ["TC-001", "TC-002"])
        check_eq("three answers and no more",
                 [row["id"] for row in finding["options"]], ["a", "b", "c"])
        check_eq("(a) onboards, (b) takes the command, (c) hands the cases over",
                 [row["action"] for row in finding["options"]],
                 list(gate_preflight.PROFILE_OPTION_IDS))
        # t-373 F7: a plugin command is something to TYPE, so it is never in the sentence a person reads; it travels in
        # the option's own `command` field for the how-to-answer block.
        check_eq("(a) carries the onboarding command in its own field, for the how-to-answer block",
                 finding["options"][0].get("command"), "/qa-factory:qa-onboarding")
        check_not_in("and the command is not in the sentence a person reads (the options line)",
                     "/qa-factory:", finding["fix"])
        check_not_in("nor in the statement", "/qa-factory:", finding["message"])
        check_not_in("nor in the text of option (a) itself", "/qa-factory:", finding["options"][0]["text"])
        check_in("(a) says it in words: the onboarding step's execution batch",
                 "onboarding step's execution batch", finding["fix"])
        check_in("(b) asks for the one thing the profile needs",
                 "runs ONE test", finding["fix"])
        check_in("(c) promises the factory will not wait",
                 "never wait for your results", finding["fix"])
    finally:
        cleanup(root)


def test_the_question_is_asked_once_and_only_when_it_is_owed() -> None:
    absent = story("qa-profile-gate-absent-")
    try:
        check_eq("a config with no `profiles` key at all is the same question",
                 len(executor_findings(absent)), 1)
    finally:
        cleanup(absent)

    manual = story("qa-profile-gate-manual-", config={"profiles": []}, disposition="manual")
    try:
        check_eq("a story whose plan automates nothing is asked nothing",
                 executor_findings(manual), [])
    finally:
        cleanup(manual)

    skipped = story("qa-profile-gate-skip-",
                    config={"profiles": [], "gate_rehearsal": {"skip_executor": True}})
    try:
        check_eq("a project that turned the step off is asked nothing",
                 executor_findings(skipped), [])
    finally:
        cleanup(skipped)

    handed = story("qa-profile-gate-handed-", config={"profiles": []}, pipeline_extra={
        "stage_overrides": [{"stage": "S5", "match": "executor unavailable: no-profile",
                             "decision": "I run them myself this time",
                             "at": "2026-09-24T09:00:00+00:00"}]})
    try:
        check_eq("a person who already took the execution over is not asked twice",
                 executor_findings(handed), [])
    finally:
        cleanup(handed)

    working = story("qa-profile-gate-ok-", config={"profiles": [PROFILE]})
    try:
        check_eq("a project with a runnable profile is asked nothing new",
                 [f for f in executor_findings(working)
                  if f.get("profile") == gate_preflight.NO_PROFILE_ID], [])
    finally:
        cleanup(working)


def test_readiness_names_the_onboarding_as_the_owner_of_the_gap() -> None:
    for label, cfg in (("no profiles key", {"schema_version": 1}),
                       ("an empty list", {"schema_version": 1, "profiles": []}),
                       ("a profile with no one-test command", {
                           "schema_version": 1,
                           "profiles": [{"profile_id": "api", "roots": {"test": "tests"},
                                         "commands": {"run": {"argv": ["pytest"], "cwd": "."}}}]})):
        root = temp_dir("qa-profile-readiness-")
        try:
            (root / "tests").mkdir()
            data = readiness.compute(cfg, root)
            entry = data["execution_profile"]
            check_eq(f"{label}: the execution profile is not_configured",
                     entry["status"], readiness.NOT_CONFIGURED)
            check_eq(f"{label}: and it is the user's, through the onboarding",
                     entry["owner"], "user")
            check_in(f"{label}: the note says what S5 would do",
                     "mine_refused", entry["note"])
            check_in(f"{label}: the step is the onboarding command",
                     "/qa-factory:qa-onboarding", " ".join(entry["remedy"]["steps"]))
            check_in(f"{label}: and it says what is still possible",
                     "still written and reviewed", entry["remedy"]["blocks"])
        finally:
            cleanup(root)

    root = temp_dir("qa-profile-readiness-ok-")
    try:
        (root / "tests").mkdir()
        data = readiness.compute({"schema_version": 1, "profiles": [PROFILE]}, root)
        check_eq("a project with a runnable profile is green",
                 data["execution_profile"]["status"], readiness.OK)
        check_in("and the profile is named", "api", data["execution_profile"]["note"])
        check_eq("the capability block is untouched — no re-onboarding is asked for",
                 sorted(data["capabilities"]), sorted(readiness.compute(
                     {"schema_version": 1}, root)["capabilities"]))
    finally:
        cleanup(root)


def test_the_runner_refuses_by_naming_the_onboarding() -> None:
    """`--mine` on the 2553 config: the sentence that reached the automator names the gap."""
    root = story("qa-profile-mine-", config={"profiles": []})
    try:
        task_root = root / "qa-factory" / "artifacts" / TICKET
        (task_root / "state" / "controller.json").write_text(json.dumps(
            {"schema_version": "2", "revision": "1", "source_revision": "source-1",
             "dispatches": {"S5-qa-automator-1": {
                 "id": "S5-qa-automator-1", "stage": "S5", "role": "qa-automator",
                 "status": "running", "scope": ["TC-001", "TC-002"],
                 "budget": {"requests": 150}}}}), encoding="utf-8")
        (task_root / "work" / "automation-manifest.json").write_text(json.dumps(
            {"tests": [{"case": "TC-001", "file": "tests/test_a.py", "selector": "test_one"}]}),
            encoding="utf-8")
        (root / "tests" / "test_a.py").write_text("def test_one():\n    pass\n", encoding="utf-8")
        out = run_script("run_suite.py", "--mine", "TC-001", cwd=root,
                         env={"CLAUDE_PROJECT_DIR": str(root), "PATH": "",
                              "QA_FACTORY_SKIP_DASHBOARD_REFRESH": "1",
                              "SYSTEMROOT": str(Path(sys.executable).anchor)})
        payload = next((json.loads(line) for line in out.stdout.splitlines()
                        if line.startswith("{")), {})
        check("--mine without a profile refuses without launching anything",
              payload.get("status") == "mine_refused", out.stdout + out.stderr)
        error = payload.get("error", "")
        check_in("it names the case it could not run", "TC-001", error)
        check_in("it names the file the profile is missing from",
                 "qa-factory/config.json", error)
        check_in("it says whose gap this is", "gap of the onboarding", error)
        check_not_in("and never blames the test", "your test is", error)
        check_in("it points at the question the gate asks", "answer a/b/c", error)
        check_in("and at the way to close it now", "/qa-factory:qa-onboarding", error)
    finally:
        cleanup(root)


if __name__ == "__main__":
    test_the_gate_asks_before_it_refuses()
    test_the_question_is_asked_once_and_only_when_it_is_owed()
    test_readiness_names_the_onboarding_as_the_owner_of_the_gap()
    test_the_runner_refuses_by_naming_the_onboarding()
    finish("a project without an execution profile")
