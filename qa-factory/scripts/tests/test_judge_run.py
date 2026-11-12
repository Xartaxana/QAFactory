#!/usr/bin/env python3
"""J2, the diagnosis of a run: off by default, advisory in shadow, and honest when it moves.

The runs replayed here are the real S5 evidence of TP1-15045 (evidence/runs/*.json):
the account that was not on the stand and was reported as `broken_run`, the pytest plugin
that crashed before collection, the test id that did not exist, and the afternoon of
playwright timeouts that was triaged as six defective tests. Nothing here reaches the
network - `judge._post` answers from a table, exactly as scripts/tests/test_judge.py does.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402
from test_judge import fake_transport, set_judge  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import judge  # noqa: E402
import judge_run  # noqa: E402
import run_suite  # noqa: E402
import stand_health  # noqa: E402

NO_ACCOUNT = ('failed on setup with "AssertionError: NON_OWNER_EMAIL / NON_OWNER_PASSWORD must be '
              'set in the environment or in testproject1_test_harness/.env (the file conftest loads)"')
NOT_FOUND = ("ERROR: not found: testproject1_test_harness/tests/workflow/test_workflow_validate_api.py"
             "::test_validate_matches_update_outcome_per_partition[self-reference]")
FILL = "playwright._impl._errors.TimeoutError: Locator.fill: Timeout 30000ms exceeded"
VISIBLE = "AssertionError: Locator expected to be visible"
PARTITION = "AssertionError: validate status for partition: {"
UI = "tests.ui.workflows.test_workflow_visual_diff::"


def summary(status="broken_run", exit_code=1, why=NO_ACCOUNT, head=(), test="tests.workflow.t::test_x"):
    out = {"task": "TP1-15045", "label": "initial-1", "exit_code": exit_code,
           "execution_status": status, "duration_s": 39.7,
           "totals": {"tests": 1, "failures": 0, "errors": 1, "skipped": 0, "passed": 0}}
    if head:
        out["error_head"] = list(head)
    if why:
        out["failed"] = [{"test": test, "kind": "error", "why": why}]
    return out


def table(state, name, question):
    """The judge as TP1-15045 calibrated it: the missing account is an environment block,
    the missing test id is tooling, the timeouts are the stand, and a bare assertion is not
    decided at all."""
    text = json.dumps(state)
    if name == "culprit":
        if "NON_OWNER" in text:
            return ("environment", 1.0)
        if "not found:" in text:
            return ("tooling", 1.0)
        if "Locator.fill" in text:
            return ("stand_degraded", 0.98)
        return ("application", 0.4)
    if name == "same":
        return 0.92 if "expected to be visible" in text and "locator.fill" in text else 0.35
    if name == "kind":
        return ("credential", 0.89)
    if name == "where":
        return ("c1", 0.9)
    return 0.94 if "NON_OWNER" in text else 0.05  # run_env_blocked


def off_by_default(root: Path) -> None:
    before = json.dumps(summary(), sort_keys=True)
    run = summary()
    check_eq("provider none: nothing is asked", judge_run.attach(run, project_root=root, task="T"), None)
    check_eq("and the summary is byte for byte what it was", json.dumps(run, sort_keys=True), before)
    check_eq("provider none sends nothing", len(judge._post.calls), 0)
    run_suite.attach_diagnosis("TP1-15045", run)  # the seam itself, outside a project
    check_eq("the seam in run_suite is the same no-op", json.dumps(run, sort_keys=True), before)


def shadow_changes_nothing(root: Path) -> None:
    set_judge(root, {"provider": "typesafe", "mode": "shadow", "api_key_env": "QA_JUDGE_TEST_KEY"})
    run = summary()
    found = judge_run.attach(run, project_root=root, task="TP1-15045")
    check_eq("shadow diagnoses the run", (found["culprit"], found["advisory"]), ("environment", True))
    check_eq("the summary carries the diagnosis", sorted(run["diagnosis"]),
             ["advisory", "confidence", "culprit", "mode", "sentence"])
    check_eq("and the status the exit code proved is untouched", run["execution_status"], "broken_run")
    check_not_in("nothing was overridden", "execution_status_raw", json.dumps(run))
    check_in("the sentence names what it read", "run diagnosis: environment",
             run["diagnosis"]["sentence"])
    check("the sentence is one ASCII line",
          run["diagnosis"]["sentence"].isascii() and "\n" not in run["diagnosis"]["sentence"])
    journal = (root / "qa-factory/state/judgments.jsonl").read_text(encoding="utf-8")
    check_in("shadow journals what it would have passed", '"kind": "would_pass"', journal)
    check_eq("and passes nothing", judge.passes(root, "TP1-15045"), [])


def on_moves_one_status(root: Path) -> None:
    set_judge(root, {"provider": "typesafe", "mode": "on", "api_key_env": "QA_JUDGE_TEST_KEY"})
    run = summary()
    judge_run.attach(run, project_root=root, task="TP1-15045")
    check_eq("mode on: an environment block stops being a broken run",
             run["execution_status"], "env_blocked")
    check_eq("what the exit code proved is kept beside it", run["execution_status_raw"], "broken_run")
    check_eq("and the diagnosis says what it moved", run["diagnosis"]["overrode"], "broken_run")
    check_in("the sentence tells the person the judge moved it", "execution_status_raw",
             run["diagnosis"]["sentence"])
    rows = judge.passes(root, "TP1-15045")
    check_eq("the pass is journalled for the gate brief",
             [(row["refusal"], row["judgment"]) for row in rows], [("broken_run", "run_env_blocked")])

    failed = summary(status="failed", why=NO_ACCOUNT)
    judge_run.attach(failed, project_root=root, task="TP1-15045")
    check_eq("a `failed` run may be moved too", failed["execution_status"], "env_blocked")

    nothing = summary(status="not_executed", exit_code=4, why="", head=[NOT_FOUND])
    judge_run.attach(nothing, project_root=root, task="TP1-15045")
    check_eq("a status the judge may not move is left alone", nothing["execution_status"], "not_executed")
    check_eq("but it is still diagnosed", nothing["diagnosis"]["culprit"], "tooling")
    check_not_in("and run_env_blocked is not even asked for it", "run_env_blocked",
                 json.dumps([call["questions"] for call in judge._post.calls[-1:]]))

    green = {"task": "T", "execution_status": "passed", "exit_code": 0, "totals": {"tests": 3}}
    before = len(judge._post.calls)
    check_eq("a green run has nothing to diagnose", judge_run.attach(green, project_root=root), None)
    check_eq("and costs nothing", len(judge._post.calls), before)

    unsure = summary(status="failed", why="AssertionError: assert 3 == 4")
    judge_run.attach(unsure, project_root=root, task="TP1-15045")
    check_eq("an undecided culprit is recorded as unknown", unsure["diagnosis"]["culprit"], "unknown")
    check_eq("and moves no status", unsure["execution_status"], "failed")


def state_is_one_run(root: Path) -> None:
    run = summary(head=[f"ERROR: line {n}" for n in range(60)])
    state = judge_run.state_of(run)
    check_eq("the state is the five fields of this one run", sorted(state),
             ["error_head", "execution_status", "exit_code", "first_failure", "totals"])
    check_eq("the error head is capped at 25 lines", len(state["error_head"]), 25)
    check_in("the first failure carries the line a role would read first", "NON_OWNER_EMAIL",
             state["first_failure"])
    check("the state stays small", len(json.dumps(state)) < 4000)
    fallback = {"execution_status": "broken_run", "exit_code": 127,
                "launch_error": "FileNotFoundError: poetry"}
    check_eq("a run that left only a launch error still has something to read",
             judge_run.state_of(fallback)["error_head"], ["FileNotFoundError: poetry"])


def unreachable_is_never_a_halt(root: Path) -> None:
    def broken(*_a, **_k):
        raise RuntimeError("HTTP 529: overloaded")
    saved, judge._post = judge._post, broken
    try:
        run = summary()
        found = judge_run.attach(run, project_root=root, task="TP1-15045")
        check_eq("an unreachable judge diagnoses nothing", found, None)
        check_eq("and leaves the run exactly as it was", run["execution_status"], "broken_run")
        check_not_in("with no diagnosis invented", "diagnosis", json.dumps(run))
    finally:
        judge._post = saved


def execution_status_is_unchanged() -> None:
    """The statuses run_suite proves for itself are the contract; the judge is a second
    opinion, never a replacement."""
    cases = [({"exit_code": 124}, "timeout"),
             ({"exit_code": 1}, "broken_run"),
             ({"exit_code": 0}, "not_executed"),
             ({"exit_code": 1, "totals": {"tests": 3, "errors": 1, "failures": 0}}, "broken_run"),
             ({"exit_code": 1, "totals": {"tests": 3, "errors": 0, "failures": 2}}, "failed"),
             ({"exit_code": 0, "totals": {"tests": 0, "errors": 0, "failures": 0}}, "not_executed"),
             ({"exit_code": 0, "totals": {"tests": 3, "errors": 0, "failures": 0}}, "passed")]
    check_eq("execution_status decides exactly as before",
             [run_suite.execution_status(s) for s, _ in cases], [expected for _, expected in cases])


def remedy_names_never_values(root: Path) -> None:
    set_judge(root, {"provider": "typesafe", "mode": "on", "api_key_env": "QA_JUDGE_TEST_KEY"})
    (root / "config").mkdir(exist_ok=True)
    (root / "config/app.yaml").write_text(
        "features:\n  - id: subWorkflowNode\n    enabled: true\n  - id: features:subWorkflow\n"
        "    enabled: false\nNON_OWNER_PASSWORD: hunter2SecretValue1234\n", encoding="utf-8")
    (root / ".env.local").write_text("NON_OWNER_EMAIL=someone@example.com\n", encoding="utf-8")
    cfg_path = root / "qa-factory/config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["environment"] = {"env_file": ".env.local"}
    cfg["protected_app_paths"] = ["config"]
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    found = judge_run.remedy(NO_ACCOUNT, project_root=root, task="TP1-15045")
    text = json.dumps(found)
    check_eq("the kind the judge named is the one the row needs", found["kind"], "credential")
    check_in("the variable is named", "NON_OWNER_EMAIL", found["change"])
    check_not_in("and never its value", "hunter2SecretValue1234", text)
    check_not_in("nor the value in the env file, which is not even read", "someone@example.com", text)
    check_in("the declared env file is offered as a place", ".env.local", text)
    import contract
    check_eq("what is printed is a remedy the contract accepts",
             contract.remedy_errors({k: found[k] for k in ("kind", "where", "change")}), [])

    hidden = judge_run._redact("NON_OWNER_PASSWORD: hunter2SecretValue1234", "NON_OWNER_PASSWORD")
    check_in("a secret-looking value is hidden wherever it is read", "<value hidden>", hidden)
    line = judge_run._hit((root / "config/app.yaml").read_text(encoding="utf-8"), ["subWorkflow"])
    check_eq("the line offered per file is the one that carries the name, not the first mention",
             line[0], 4)
    check_in("with the setting under it", "enabled: false", line[2])


def wanted_names_skip_the_tests_own_names() -> None:
    """B-407 A6: a quoted identifier is a test's own name when ANY segment (split on `.`, `/`, `::`) names a test or is a
    test folder name, by the usual names as data (no `startswith` pair in the code); with the names unreadable nothing is
    skipped."""
    def names(*quoted: str) -> list:
        return judge_run.wanted_names("failed: " + " and ".join(f"'{q}'" for q in quoted) + "; API_BASE_URL is missing")

    check_eq("A6: API_BASE_URL (shouted) and contest_url are kept; test_login, tests.api.client, FooTests.Bar are skipped",
             names("test_login", "tests.api.client", "FooTests.Bar", "contest_url"), ["API_BASE_URL", "contest_url"])
    check_eq("A6: a segment that is a test folder name (spec, e2e, tests), a test name (foo_test, test_b) or a camel "
             "name skips the identifier, whatever the separator", names("pkg.spec", "e2e.helpers", "foo_test", "tests/api", "a::test_b",
                                                                        "x.FooSpec"), ["API_BASE_URL"])
    check_eq("A6: Latest.Build, AUDIT.Log, latest_report, protest_utils and settings.yaml are no tests: they stay, in order",
             names("Latest.Build", "AUDIT.Log", "latest_report", "protest_utils", "settings.yaml"),
             ["API_BASE_URL", "Latest.Build", "AUDIT.Log", "latest_report", "protest_utils", "settings.yaml"])
    check_eq("A6: at most six names, as before", len(names(*[f"name_{i}" for i in range(12)])), 6)
    import contextlib
    import hooklib
    import io
    import tempfile
    real_ref = hooklib.ref
    empty = Path(tempfile.mkdtemp(prefix="qa-jr-nomarkers-"))
    try:
        hooklib.ref = lambda rel: empty / rel
        with contextlib.redirect_stderr(io.StringIO()):
            blind = names("test_login", "tests.api.client", "contest_url")
        check_eq("A6: with the usual names unreadable nothing is skipped (noise is cheaper than a missed name)",
                 blind, ["API_BASE_URL", "test_login", "tests.api.client", "contest_url"])
    finally:
        hooklib.ref = real_ref
        harness.cleanup(empty)


def similar_failures_are_one_stand(root: Path) -> None:
    """The afternoon of TP1-15045: the same dead stand in two wordings. Exact matching
    counts two rows of two, the judge counts one row of four."""
    def run(label, test, why, environment="localhost"):
        return {"task": "TP1-15045", "label": label, "exit_code": 1, "duration_s": 300.0,
                "totals": {"tests": 1}, "environment": environment,
                "failed": [{"test": test, "kind": "failure", "why": why}],
                "results": [{"test_id": test, "status": "failed", "reason": why}]}

    set_judge(root, {"provider": "typesafe", "mode": "shadow", "api_key_env": "QA_JUDGE_TEST_KEY"})
    rows = [("a", UI + "test_one[chromium]", FILL), ("b", UI + "test_two[chromium]", VISIBLE),
            ("c", UI + "test_three[chromium]", FILL), ("d", UI + "test_four[chromium]", VISIBLE)]
    signals = [stand_health.observe(root, "TP1-15045", run(f"initial-{n}", t, w)) for n, t, w in rows]
    check_eq("shadow acts on nothing", signals, [None] * 4)
    check_in("but the question was asked and journalled", "run_same_cause",
             (root / "qa-factory/state/judgments.jsonl").read_text(encoding="utf-8"))

    stand_health.reset(root, "the next case starts from an empty record")
    set_judge(root, {"provider": "typesafe", "mode": "on", "api_key_env": "QA_JUDGE_TEST_KEY"})
    signals = [stand_health.observe(root, "TP1-15045", run(f"initial-{n}", t, w)) for n, t, w in rows]
    check_eq("nothing fires before three different cases", signals[:2], [None, None])
    signal = signals[2]
    check("the third case with a similar line is the stand", bool(signal))
    check_eq("recorded as the same signal the exact rule raises", signal["reason"], "same_failure")
    check_eq("and said to come from the judge", signal["matched"], "judge")
    check_in("the sentence says the lines are similar", "similar lines", signal["sentence"])
    check_in("and names the judgment that grouped them", "run_same_cause", signal["sentence"])
    check("the sentence is one ASCII line",
          signal["sentence"].isascii() and "\n" not in signal["sentence"])
    check_eq("the record keeps the signal with its run",
             stand_health.status(root)["recent"][-1]["signal"], "same_failure")

    stand_health.reset(root, "and unrelated failures are still unrelated")
    apart = [stand_health.observe(root, "TP1-15045", run(f"initial-x{n}", UI + f"test_{n}[chromium]", why))
             for n, why in enumerate([FILL, PARTITION, VISIBLE, PARTITION])]
    check_eq("two failures the judge does not group never make a row", apart, [None] * 4)


def the_command_line(root: Path) -> None:
    set_judge(root, None)
    task = root / "qa-factory/artifacts/TP1-15045"
    task.mkdir(parents=True, exist_ok=True)
    path = root / "summary.json"
    path.write_text(json.dumps(summary()), encoding="utf-8")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    done = harness.run_script("judge_run.py", "--task-root", task, "--summary", path, cwd=root, env=env)
    check_eq("with no judge the script still answers, and with exit 0", done.returncode, 0)
    check_eq("one line on stdout", len(done.stdout.strip().splitlines()), 1)
    check_in("saying it is off", "off", done.stdout)
    head = root / "head.txt"
    head.write_text(NO_ACCOUNT, encoding="utf-8")
    fixed = harness.run_script("judge_run.py", "--task-root", task, "--remedy",
                               "--error-head-file", head, "--json", cwd=root, env=env)
    check_eq("--remedy answers JSON on request", json.loads(fixed.stdout)["status"], "off")
    check_eq("and exits 0 when the judge is simply off", fixed.returncode, 0)


def main() -> None:
    root = harness.temp_project("qa-judge-run-")
    os.environ["QA_JUDGE_TEST_KEY"] = "not-a-real-key"
    real_post = judge._post
    try:
        harness.use_project(root)
        judge._post = fake_transport(table)
        off_by_default(root)
        shadow_changes_nothing(root)
        on_moves_one_status(root)
        state_is_one_run(root)
        unreachable_is_never_a_halt(root)
        execution_status_is_unchanged()
        remedy_names_never_values(root)
        wanted_names_skip_the_tests_own_names()
        similar_failures_are_one_stand(root)
        the_command_line(root)
    finally:
        judge._post = real_post
        harness.cleanup(root)
    harness.finish("test_judge_run")


if __name__ == "__main__":
    main()
