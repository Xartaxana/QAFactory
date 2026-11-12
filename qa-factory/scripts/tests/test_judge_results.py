"""S6-S9 judge questions: `judge_results.py`, `references/judgments.d/results.json`.

No test here reaches the network: `judge._post` is replaced by a table transport exactly as
`test_judge.py` does. What is checked is judge_results.py's own side - state assembly, the
APP_BUG-never-decided override, the reruns gate on `result_flaky_mechanism`, the dedup/priority
pairing of `--bugs`, and the three one-shot forms - plus one subprocess pass through the CLI
with `judge.provider: none` (deterministic, no fake transport needed across the process
boundary) to prove the argument wiring itself works.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import judge  # noqa: E402
import judge_results  # noqa: E402


def fake_transport(table):
    """Same shape as test_judge.py's: `table(state, name, question)` returns a float for a
    noul or `(label, confidence)` for a choice/score."""
    def post(payload, key, timeout, attempts=4):
        answers = {}
        for name, question in payload["questions"].items():
            value = table(payload["state"], name, question)
            if question["type"] == "noul":
                answers[name] = {"type": "noul", "noul": value}
            elif question["type"] == "choice":
                answers[name] = {"type": "choice", "choice": value[0], "confidence": value[1],
                                 "probabilities": {value[0]: value[1]}}
            else:
                answers[name] = {"type": "score", "score": value[0], "confidence": value[1],
                                 "probabilities": {str(value[0]): 1.0}}
        return {"model": "judge-test", "answers": answers, "usage": {"input_tokens": 42}}
    return post


def set_judge(root: Path, block: dict | None) -> None:
    path = root / "qa-factory/config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg.pop("judge", None)
    if block is not None:
        cfg["judge"] = block
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def seed_task(root: Path, ticket: str) -> Path:
    task = root / "qa-factory/artifacts" / ticket
    (task / "work/test-cases/area").mkdir(parents=True)
    (task / "work/bug-drafts").mkdir(parents=True)
    (task / "evidence/runs/attempt-env").mkdir(parents=True)
    (task / "evidence/runs/attempt-bug").mkdir(parents=True)
    (task / "evidence/runs/attempt-flaky").mkdir(parents=True)
    (root / "qa-factory/bugs").mkdir(parents=True, exist_ok=True)

    (task / "work/requirements-register.md").write_text(
        "## Register\n\n| R | Requirement | source |\n|---|---|---|\n"
        "| R-1 | The page loads within the timeout budget | ac |\n"
        "| R-2 | The error response names the offending input | ac |\n", encoding="utf-8")

    (task / "work/test-cases/area/TC-001.md").write_text(
        "---\nid: TC-001\ntitle: Page loads\nbasis: \"requirement:R-1\"\n---\n"
        "## Given\n- a session\n## When\n1. open the page\n## Then\n1. the page renders within budget\n",
        encoding="utf-8")
    (task / "work/test-cases/area/TC-002.md").write_text(
        "---\nid: TC-002\ntitle: Error names the input\nbasis: \"requirement:R-2\"\n---\n"
        "## Given\n- a bad config\n## When\n1. submit it\n## Then\n1. the error names the offending input\n",
        encoding="utf-8")

    for name, text in (("attempt-env", "line one\nTimeoutError: waiting for locator('h2')\nline three\n"),
                       ("attempt-bug", "line one\nAssertionError: response is missing the detail\nline three\n"),
                       ("attempt-flaky", "line one\nAssertionError: intermittent mismatch\nline three\n")):
        (task / "evidence/runs" / name / "run.log").write_text(text, encoding="utf-8")

    results = [
        {"instance_id": "test_env", "test_id": "tests/x.py::test_env",
         "case_version_links": [{"case_id": "TC-001"}], "status": "failed",
         "reason": "TimeoutError: waiting for locator('h2')", "attempt_id": "attempt-env"},
        {"instance_id": "test_appbug", "test_id": "tests/x.py::test_appbug",
         "case_version_links": [{"case_id": "TC-002"}], "status": "failed",
         "reason": "AssertionError: response is missing the detail", "attempt_id": "attempt-bug"},
        {"instance_id": "test_flaky", "test_id": "tests/x.py::test_flaky", "status": "passed"},
        {"instance_id": "test_flaky", "test_id": "tests/x.py::test_flaky", "status": "failed",
         "reason": "AssertionError: intermittent mismatch"},
        {"instance_id": "test_flaky", "test_id": "tests/x.py::test_flaky", "status": "failed",
         "reason": "AssertionError: intermittent mismatch", "attempt_id": "attempt-flaky"},
    ]
    current = [results[0], results[1], results[-1]]
    (task / "work/run-report.json").write_text(
        json.dumps({"results": results, "current_results": current}), encoding="utf-8")

    manifest = {"tests": [
        {"file": "tests/x.py", "selector": "test_env", "status": "green",
         "case_version_links": [{"case_id": "TC-001"}]},
        {"file": "tests/x.py", "selector": "test_appbug", "status": "green",
         "case_version_links": [{"case_id": "TC-002"}]},
    ]}
    (task / "work/automation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    draft = {"title": "Duplicate ADDED badge", "case": "TC-001", "impact": "minor",
            "expected": "exactly one badge", "actual": "two badges shown"}
    (task / "work/bug-drafts/d1.json").write_text(json.dumps(draft), encoding="utf-8")
    other_draft = {"title": "Unrelated timing glitch", "case": "TC-002", "impact": "minor",
                  "expected": "a stable timestamp", "actual": "a jittery timestamp"}
    (task / "work/bug-drafts/d2.json").write_text(json.dumps(other_draft), encoding="utf-8")

    (root / "qa-factory/bugs/BUG-1.md").write_text(
        "---\nid: BUG-1\ntitle: Some other bug\narea: area\n---\n"
        "## Expected result\na single result\n## Actual result\ntwo results\n", encoding="utf-8")
    (root / "qa-factory/bugs/BUG-2.md").write_text(
        "---\nid: BUG-2\ntitle: Duplicate ADDED badge\narea: area\n---\n"
        "## Expected result\nexactly one badge\n## Actual result\ntwo badges shown\n", encoding="utf-8")
    return task


def triage_table(state, name, question):
    if name == "verdict":
        text = (state.get("error_head", "") + state.get("assertion", "")).lower()
        if "timeout" in text or "locator" in text:
            return ("ENV_ISSUE", 0.92)
        if "missing the detail" in text:
            return ("APP_BUG", 0.95)
        return ("TEST_BUG", 0.3)
    if name == "case_defect":
        return 0.05
    if name == "flaky":
        return ("timing", 0.9)
    return 0.5


def bugs_table(state, name, question):
    if name == "dup":
        draft_t = (state.get("draft") or {}).get("title", "")
        bug_t = (state.get("existing_bug") or {}).get("title", "")
        return 0.95 if draft_t == bug_t else 0.03
    if name == "priority":
        return (0, 0.9)
    return 0.5


def observation_table(state, name, question):
    return 0.95 if state.get("then") == state.get("observed") else 0.05


def trap_table(state, name, question):
    text = str(state.get("trap") or "").lower()
    return ("framework-rules", 0.9) if "selector" in text else ("test-strategy", 0.85)


def diff_table(state, name, question):
    text = json.dumps(state.get("detail") or {})
    return ("requirements", 0.9) if "AC2" in text else ("context", 0.9)


def main() -> None:
    registry = judge.load_registry()
    for jid in ("result_triage_verdict", "result_case_defect", "result_flaky_mechanism",
               "result_bug_duplicate", "result_bug_priority", "result_observation_matches_then",
               "result_trap_owner", "result_ticket_change_severity"):
        check(f"{jid} is registered", jid in registry)
    check_eq("result_triage_verdict is a 7-way choice",
             sorted(registry["result_triage_verdict"]["criteria"]),
             sorted(["APP_BUG", "TEST_BUG", "TEST_BUG:collection", "ENV_ISSUE", "FLAKY",
                    "APP_CHANGED", "CASE_DEFECT"]))

    root = harness.temp_project("qa-judge-results-")
    real_post = judge._post
    try:
        harness.use_project(root)
        task = seed_task(root, "QA-9")

        # provider none: no file, no network, whatever the CLI form
        judge._post = fake_transport(lambda *a: 0.99)
        off = judge_results.run_triage(task)
        check_eq("triage is a no-op without a provider", off["status"], "off")
        check("and writes no file", not (task / "work/judge-triage.json").exists())
        off_bugs = judge_results.run_bugs(task)
        check_eq("bugs is a no-op without a provider", off_bugs["status"], "off")
        check("and writes no file either", not (task / "work/judge-bugs.json").exists())
        off_obs = judge_results.cmd_observation("x", "y", root)
        check_eq("--observation is a no-op without a provider", off_obs["status"], "off")
        check_eq("provider none never calls the transport", judge._post.calls if hasattr(judge._post, "calls") else [], [])

        # --triage: verdicts, the APP_BUG override, case_defect, and the reruns gate
        set_judge(root, {"provider": "typesafe", "mode": "on", "api_key_env": "QA_JUDGE_RESULTS_KEY"})
        os.environ["QA_JUDGE_RESULTS_KEY"] = "not-a-real-key"
        judge._post = fake_transport(triage_table)
        report = judge_results.run_triage(task)
        check_eq("triage runs over both failed rows", report["status"], "ok")
        by_test = {r["instance_id"]: r for r in report["results"]}
        check_eq("a timeout error head decides ENV_ISSUE",
                 by_test["test_env"]["verdict"]["value"], "ENV_ISSUE")
        check_eq("an APP_BUG leaning is never a decided value, whatever its probability",
                 (by_test["test_appbug"]["verdict"]["value"], by_test["test_appbug"]["verdict"]["decided"]),
                 (None, False))
        check_eq("the leaning still travels for the analyst to read",
                 by_test["test_appbug"]["verdict"]["leaning"], "APP_BUG")
        check_eq("case_defect is asked once a requirement is on file",
                 by_test["test_env"]["case_defect"]["value"], False)
        check_eq("flaky_mechanism only fires once FLAKY_MIN_RERUNS reruns exist",
                 by_test["test_flaky"]["flaky_mechanism"]["value"], "timing")
        check("test_env, with only 1 rerun, is never asked flaky_mechanism",
              "flaky_mechanism" not in by_test["test_env"])
        check("work/judge-triage.json is written", (task / "work/judge-triage.json").is_file())
        on_disk = json.loads((task / "work/judge-triage.json").read_text(encoding="utf-8"))
        check_eq("the file matches what run_triage returned", on_disk["rows"], report["rows"])

        # --bugs: duplicate dedup and the priority score
        judge._post = fake_transport(bugs_table)
        bugs_report = judge_results.run_bugs(task)
        check_eq("bugs runs over both drafts", bugs_report["status"], "ok")
        by_draft = {r["draft"]: r for r in bugs_report["results"]}
        check_eq("the matching draft/bug pair is flagged a duplicate",
                 [d["bug"] for d in by_draft["d1.json"]["duplicates"]], ["BUG-2"])
        check_eq("the unrelated draft is not flagged against either bug",
                 by_draft["d2.json"]["duplicates"], [])
        check_eq("the damage line decides a priority score",
                 by_draft["d1.json"]["priority"]["value"], 0)
        check("work/judge-bugs.json is written", (task / "work/judge-bugs.json").is_file())

        # one-shot forms
        judge._post = fake_transport(observation_table)
        matched = judge_results.cmd_observation("the badge is green", "the badge is green", root)
        check_eq("--observation: a matching pair decides true", matched["decision"]["value"], True)
        mismatched = judge_results.cmd_observation("the badge is green", "the badge is red", root)
        check_eq("--observation: a mismatched pair decides false", mismatched["decision"]["value"], False)

        judge._post = fake_transport(trap_table)
        trap = judge_results.cmd_trap("Testers keep picking a brittle CSS selector.", root)
        check_eq("--trap: a code/run trap leans framework-rules",
                 trap["decision"]["leaning"], "framework-rules")

        judge._post = fake_transport(diff_table)
        fixtures = Path(harness.PLUGIN_ROOT) / "evals/fixtures/tickets/QA-1.md"
        old_copy = root / "old.md"
        new_copy = root / "new.md"
        old_text = fixtures.read_text(encoding="utf-8")
        old_copy.write_text(old_text, encoding="utf-8")
        new_copy.write_text(old_text + "- **po** (2026-09-16): drop AC2, tags stay case-sensitive.\n",
                            encoding="utf-8")
        diff = judge_results.cmd_ticket_diff(old_copy, new_copy, root)
        check_eq("the code's own severity still calls a comment-only change `context`",
                 diff["code_severity"], "context")
        check_eq("the judge reads the comment text and decides `requirements`",
                 diff["decision"]["value"], "requirements")
        check_eq("mode `on` lets the decided answer override the code's severity",
                 diff["severity"], "requirements")
        set_judge(root, {"provider": "typesafe", "mode": "shadow", "api_key_env": "QA_JUDGE_RESULTS_KEY"})
        diff_shadow = judge_results.cmd_ticket_diff(old_copy, new_copy, root)
        check_eq("in shadow mode the code's own severity stands, whatever the judge decided",
                 diff_shadow["severity"], "context")

        unchanged = judge_results.cmd_ticket_diff(old_copy, old_copy, root)
        check_eq("an unchanged ticket is off, no question asked", unchanged["status"], "off")
    finally:
        judge._post = real_post
        harness.cleanup(root)

    # One CLI pass with provider none: the argument wiring itself, no fake transport needed
    # across the process boundary.
    root2 = harness.temp_project("qa-judge-results-cli-")
    try:
        harness.use_project(root2)
        task2 = seed_task(root2, "QA-10")
        result = harness.run_script("judge_results.py", "--task-root", str(task2), "--triage", "--json",
                                    cwd=root2, env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root2)))
        check_eq("the CLI exits 0 when the judge is off", result.returncode, 0)
        check_in("and reports status off in JSON", '"status": "off"', result.stdout)
        missing = harness.run_script("judge_results.py", "--triage", cwd=root2)
        check("--triage without --task-root is a usage error", missing.returncode == 2)
    finally:
        harness.cleanup(root2)

    failed_rows_follow_triage_targets()
    harness.finish("test_judge_results")


def failed_rows_follow_triage_targets() -> None:
    """K4 (t-319, critic t-312 F5): `_failed_rows` was the fifth reading of "a failure that needs triage" - a raw
    `status in (failed, error)` over `current_results or results`. It now asks `contract.triage_targets`."""
    import contract
    from test_s7_null_outcome import cmp2r_report
    report = cmp2r_report()
    rows = judge_results._failed_rows(report)
    names = {next(iter(contract.triage_targets({"current_results": [r]})["results"])) for r in rows}
    check_eq("K4: the cmp2r run (4 failed results, 3 manual inconclusive, 2 non-failures): the judge sorts the four failed rows, "
             "the very ones `triage_targets` names", (names, len(rows)), (contract.triage_targets(report)["results"], 4))
    check_eq("K4: ...a status the contract normalises (`fail`, an `error`, a `result` key) is a failure here too, as it is there",
             len(judge_results._failed_rows({"current_results": [{"instance_id": "a", "status": "fail"}, {"instance_id": "b", "result": "error"},
                                                                 {"instance_id": "c", "status": "passed"}]})), 2)
    check_eq("an EMPTY current view wins over the history: everything repaired, nothing to sort",
             judge_results._failed_rows({"results": [{"instance_id": "old", "status": "failed"}], "current_results": []}), [])
    check_eq("control: with no current list the legacy history is read (through the projection)",
             [r["instance_id"] for r in judge_results._failed_rows({"results": [{"instance_id": "old", "status": "failed"}]})], ["old"])
    check_eq("a failing row with no name is still a row to sort (a failure with no id)",
             len(judge_results._failed_rows({"current_results": [{"status": "failed"}]})), 1)
    check_eq("rows that are not rows are ignored", judge_results._failed_rows({"current_results": ["x", None, 5]}), [])


if __name__ == "__main__":
    main()
