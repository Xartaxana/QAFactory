"""retro_numbers.py: how many tests were run, how many times, and why (SC2-37; FR-41, FR-12, AR-1, AR-13, AR-23).

Owner's word 29.10.2026: a small bug got 5 tests and 31 runs, "now for the environment, now for the factory's errors", and
the retro said neither. The unit is the EXECUTED INSTANCE, the number `run_block_metrics` already prints as `executions`
(31 on TP1-14857); the cause of each repeat is read from structured fields (purpose, the dispatch's `repair_cause` in
`state/events.jsonl`, the previous attempt of the same test, a stand signal, a triage verdict), never from prose, and
`unknown` is a word with the launch's id, never a default.

Keys S1-S16 of the spec: the by-hand split of 14857 (S1, S2b), the real jobs of 12586 (S2), unknown over default (S3, S5),
precedence (S4), both carriers absent (S6), a damaged job (S7), purposes (S8), jobs that ran nothing (S9), no instances
(S10), the ten-id limit at and beyond (S11), the data file (S12), the dashboard's words (S13), the estimate ledger (S14),
an empty folder (S15) and the sum of the causes (S16).

Run on its own: `python -B scripts/tests/test_retro_test_runs.py`.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import FIXTURES, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import retro_numbers as RN  # noqa: E402

STORY_14857 = FIXTURES / "investigation-14857" / "TP1-14857"
STORY_12586 = FIXTURES / "run-12586-red-then" / "controller" / "TP1-12586"


def story() -> tuple:
    root = temp_dir("qa-retro-test-runs-")
    base = root / "qa-factory"
    troot = base / "artifacts" / "QA-1"
    (troot / "work").mkdir(parents=True)
    (troot / "state").mkdir(parents=True)
    (base / "state" / "cost").mkdir(parents=True)
    (base / "config.json").write_text("{}", encoding="utf-8")
    (troot / "pipeline.json").write_text(json.dumps({"ticket": "QA-1", "size": "S", "stages": {}}), encoding="utf-8")
    (troot / "work" / "test-plan.json").write_text("[]", encoding="utf-8")
    return root, base, troot


def stamp(n: int) -> str:
    return f"2026-10-27T00:{n // 60:02d}:{n % 60:02d}+00:00"


def block(troot: Path, n: int, purpose: str, dispatch: str, status: str, instances: list, **row_extra) -> str:
    """One `work/run-blocks` file; `n` orders it in time. Returns the block id."""
    block_id = f"b{n:02d}"
    rows = [{"instance_id": name, "status": "error" if status in ("broken_run", "failed_to_launch") else
             ("passed" if status == "passed" else "failed"), "attempt_id": block_id, **row_extra} for name in instances]
    folder = troot / "work" / "run-blocks"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"2026{n:04d}-{block_id}.json").write_text(json.dumps({
        "schema_version": 2, "block_id": block_id, "attempt_id": block_id, "attempt_started_at": stamp(n),
        "dispatch_id": dispatch, "purpose": purpose, "execution_status": status, "results": rows}), encoding="utf-8")
    return block_id


def job(troot: Path, name: str, purpose: str, dispatch: str, instances=None, status="completed", exec_status="passed",
        n: int = 0, **extra) -> None:
    folder = troot / "state" / "execution-jobs"
    folder.mkdir(parents=True, exist_ok=True)
    record = {"job_id": name, "status": status, "created_at": stamp(n), "execution_status": exec_status,
              "request": {"purpose": purpose, "dispatch_id": dispatch, "reason": "prose is never read: environment",
                          "selected_instance_ids": instances if instances is not None else []}}
    record.update(extra)
    (folder / f"{name}.json").write_text(json.dumps(record), encoding="utf-8")


def events(troot: Path, rows: list) -> None:
    lines = [json.dumps({"type": "dispatch", "payload": payload}) for payload in rows]
    (troot / "state" / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def shape_of_14857(troot: Path) -> None:
    """The nine launches of TP1-14857 (the plan critic's listing), instances renamed: four tests of one dispatch
    broken twice, red three times, then green; one test of another dispatch broken and green; five on a runner."""
    four = ["t1", "t2", "t3", "t4"]
    block(troot, 1, "initial", "S5-qa-automator-2", "broken_run", four)
    block(troot, 2, "repair_verify", "S5-qa-automator-2", "broken_run", four)
    for n in (3, 4, 5):
        block(troot, n, "repair_verify", "S5-qa-automator-2", "failed", four)
    block(troot, 6, "repair_verify", "S5-qa-automator-2", "passed", four)
    block(troot, 7, "initial", "S5-qa-automator-3", "broken_run", ["t5"])
    block(troot, 8, "repair_verify", "S5-qa-automator-3", "passed", ["t5"])
    block(troot, 9, "repair_verify", "S6-qa-runner-4", "passed", four + ["t5"])


def sums(label: str, counts: dict) -> None:
    check_eq(f"S16 the causes add up to the runs: {label}", sum((counts.get("by_cause") or {}).values()), counts.get("runs"))


def split_by_hand_and_the_probe() -> None:
    """S1 and S2b: 5 tests, 31 runs in 9 launches, plus a probe that is not a run."""
    root, base, troot = story()
    try:
        shape_of_14857(troot)
        job(troot, "probe-1", "red_probe", "S5-qa-code-critic-1", ["t1"], exec_status="failed", n=20)
        got = RN.test_run_counts(troot)
        check_eq("S1 the by-hand split: first run, launch failed, after red, planned stage run", got["by_cause"],
                 {"first_run": 5, "launch_failed": 9, "after_red": 12, "stage_run": 5})
        check_eq("S1 5 tests, 31 runs, 9 launches, 1 probe outside the runs",
                 (got["tests"], got["runs"], got["launches"], got["probes"]), (5, 31, 9, 1))
        check_eq("S1 no launch of unknown cause", got["unknown_jobs"], [])
        check_in("S1 the line shows the owner's numbers", "5 tests, 31 runs in 9 launches", RN.test_run_sentence(got))
        check_in("S1 launch_failed prints as what it is", "environment or factory, not told apart", RN.test_run_sentence(got))
        check_eq("S1 the unit is the execution, the same number run_block_metrics prints",
                 got["runs"], RN.run_block_metrics(troot)["executions"])
        check_eq("S1 per test: t1 ran 7 times, t5 3 times", (got["per_test"]["t1"], got["per_test"]["t5"]), (7, 3))
        sums("S1", got)
        # a stand signal on the summary of the launch that failed lifts launch_failed to environment (the one real source)
        job(troot, "b01", "initial", "S5-qa-automator-2", ["t1", "t2", "t3", "t4"], exec_status="broken_run", n=1,
            summary="qa-factory\\artifacts\\QA-1\\evidence\\runs\\b01\\initial-b01.json")
        summary = troot / "evidence" / "runs" / "b01"
        summary.mkdir(parents=True)
        (summary / "initial-b01.json").write_text(json.dumps({"stand_signal": {"reason": "same_failure"}}), encoding="utf-8")
        lifted = RN.test_run_counts(troot)
        check_eq("a stand signal on the previous run lifts its four repeats to environment",
                 (lifted["by_cause"].get("environment"), lifted["by_cause"].get("launch_failed")), (4, 5))
        sums("S1 lifted", lifted)
    finally:
        cleanup(root)


def real_shapes() -> None:
    """S2 (jobs of 12586) and S2b (run blocks of 14857, the owner's own story), with the control value."""
    jobs = RN.test_run_counts(STORY_12586)
    check_eq("S2 12586: 10 distinct tests, 18 runs, 3 launches, 2 probes (the critic's 20 selections = 18 + 2)",
             (jobs["tests"], jobs["runs"], jobs["launches"], jobs["probes"]), (10, 18, 3, 2))
    check_eq("S2 the 20 selections of the 5 jobs are the runs and the probes", jobs["runs"] + jobs["probes"], 20)
    check_eq("S2 the causes: a first run, and the later run on a red or a green first run",
             jobs["by_cause"], {"first_run": 10, "after_red": 3, "stage_run": 5})
    check_eq("S2 nothing unknown on real jobs", jobs["unknown_jobs"], [])
    sums("12586", jobs)
    lines = RN.observations({"test_run_counts": jobs})
    check("S2 observations speak when runs exceed tests in the new unit", any("run again" in line for line in lines), str(lines))
    check_eq("S2 and stay quiet when they do not", any("run again" in line for line in RN.observations(
        {"test_run_counts": {"known": True, "tests": 5, "runs": 5}})), False)
    blocks = RN.test_run_counts(STORY_14857)
    check_eq("S2b 14857: 5 tests, 31 runs, 9 launches, from run blocks with no jobs",
             (blocks["known"], blocks["tests"], blocks["runs"], blocks["launches"]), (True, 5, 31, 9))
    check_eq("S2b runs equal run_block_metrics.executions", blocks["runs"], RN.run_block_metrics(STORY_14857)["executions"])
    check_eq("S2b by-hand split holds on the real blocks", blocks["by_cause"],
             {"first_run": 5, "launch_failed": 9, "after_red": 12, "stage_run": 5})
    sums("14857", blocks)


def unknown_over_default_and_precedence() -> None:
    """S3, S4, S5: a dispatch with no cause is `unknown`, never test_defect; the recorded cause beats the inferred; a
    second initial on a seen test is not a first run."""
    root, base, troot = story()
    try:
        block(troot, 1, "initial", "S5-qa-automator-2", "", ["t1"])
        block(troot, 2, "repair_verify", "S5-qa-automator-2", "", ["t1"])
        events(troot, [{"id": "S5-qa-automator-2", "role": "qa-automator"}])
        got = RN.test_run_counts(troot)
        check_eq("S3 no repair_cause, no triage, no previous attempt status: unknown", got["by_cause"], {"first_run": 1, "unknown": 1})
        check_eq("S3 and the launch is named by its id", got["unknown_jobs"], ["b02"])
        check_not_in("S3 never a test defect by default", "test_defect", json.dumps(got))
        sums("S3", got)
    finally:
        cleanup(root)
    root, base, troot = story()
    try:
        block(troot, 1, "initial", "S5-qa-automator-2", "failed", ["t1"])
        block(troot, 2, "repair_verify", "S5-qa-automator-2", "passed", ["t1"])
        (troot / "work" / "triage.json").write_text(json.dumps({"triage": [
            {"test": "t1", "instance_id": "t1", "attempt_id": "b01", "verdict": "TEST_BUG"}]}), encoding="utf-8")
        events(troot, [{"id": "S5-qa-automator-2", "repair_cause": "environment"}])
        got = RN.test_run_counts(troot)
        check_eq("S4 the dispatch's repair_cause (environment) beats the triage TEST_BUG and the previous status",
                 got["by_cause"], {"first_run": 1, "environment": 1})
        events(troot, [{"id": "S5-qa-automator-2"}])
        later = RN.test_run_counts(troot)
        check_eq("S4 without a recorded cause the previous attempt speaks (failed: after red)", later["by_cause"],
                 {"first_run": 1, "after_red": 1})
        sums("S4", got)
        # the triage step itself: a previous status the table does not map, a TEST_BUG row bound to that failure
        block(troot, 1, "initial", "S5-qa-automator-2", "", ["t1"])
        later = RN.test_run_counts(troot)
        check_eq("S4 a triage verdict is the last word before unknown (ENV_ISSUE/TEST_BUG/APP_BUG are causes)",
                 later["by_cause"], {"first_run": 1, "test_defect": 1})
        (troot / "work" / "triage.json").write_text(json.dumps({"triage": [
            {"test": "t1", "instance_id": "t1", "attempt_id": "b01", "verdict": "NOT_EXECUTED"}]}), encoding="utf-8")
        check_eq("S4 NOT_EXECUTED is not a cause: unknown", RN.test_run_counts(troot)["by_cause"], {"first_run": 1, "unknown": 1})
    finally:
        cleanup(root)
    root, base, troot = story()
    try:
        block(troot, 1, "initial", "S5-qa-automator-2", "", ["t1"])
        block(troot, 2, "initial", "S5-qa-automator-2", "", ["t1"])
        got = RN.test_run_counts(troot)
        check_eq("S5 a second initial on a seen test is not a first run", got["by_cause"], {"first_run": 1, "unknown": 1})
        sums("S5", got)
        # a green test run again by the same hand is not a planned stage run
        block(troot, 3, "repair_verify", "S5-qa-automator-2", "passed", ["t2"])
        block(troot, 4, "repair_verify", "S5-qa-automator-2", "passed", ["t2"])
        block(troot, 5, "repair_verify", "S6-qa-runner-1", "passed", ["t2"])
        check_eq("a green rerun by the same role is unknown, by another role a stage run",
                 RN.test_run_counts(troot)["by_cause"], {"first_run": 2, "unknown": 2, "stage_run": 1})
    finally:
        cleanup(root)


def empty_and_damaged() -> None:
    """S6, S7, S15: both carriers absent is unknown (never 0); a damaged job is counted; an empty folder is zero."""
    root, base, troot = story()
    try:
        none = RN.test_run_counts(troot)
        check_eq("S6 both carriers absent: known false, with a reason and the carrier", (none["known"], bool(none["reason"]),
                 none["carrier"]), (False, True, "work/run-blocks+state/execution-jobs"))
        line = RN.test_run_lines(none)[0]
        check_in("S6 the line says not recorded", "not recorded", line)
        check_not_in("S6 and never 0 runs", "0 runs", line)
        check_eq("S6 run_block_metrics is as today", RN.run_block_metrics(troot)["executions"], 0)
        check_eq("S6 facts before the key existed render no line", RN.test_run_lines(None), [])
        (troot / "state" / "execution-jobs").mkdir()
        zero = RN.test_run_counts(troot)
        check_eq("S15 an existing folder with no job: known, 0 runs", (zero["known"], zero["runs"], zero["tests"]), (True, 0, 0))
        check_in("S15 the line says no test was run", "no test was run", RN.test_run_sentence(zero))
        sums("S15", zero)
        job(troot, "ok1", "initial", "S5-qa-automator-1", ["t1"], n=1)
        (troot / "state" / "execution-jobs" / "broken.json").write_text("{not json", encoding="utf-8")
        (troot / "state" / "execution-jobs" / "norequest.json").write_text(json.dumps({"job_id": "x"}), encoding="utf-8")
        (troot / "state" / "execution-jobs" / "list.json").write_text("[1]", encoding="utf-8")
        got = RN.test_run_counts(troot)
        check_eq("S7 a corrupt file, a job with no request and a non-object are counted, not raised",
                 (got["unreadable"], got["runs"]), (3, 1))
        data = RN.numbers("QA-1", base, troot)
        text = RN.render(data)
        check_in("S7 the retro still writes, with the damaged files said", "3 job files could not be read", text)
        check_in("S7 the retro line is there", "**Test runs:**", text)
    finally:
        cleanup(root)


def purposes_and_jobs_that_ran_nothing() -> None:
    """S8, S9, S10: purposes, not-executed jobs and jobs that name no test."""
    root, base, troot = story()
    try:
        job(troot, "j1", "initial", "S5-qa-automator-1", ["t1"], exec_status="", n=1)
        job(troot, "j2", "weird_purpose", "S5-qa-automator-1", ["t2"], n=2)
        job(troot, "j3", "build", "S5-qa-automator-1", ["t3"], n=3)
        job(troot, "j4", "collect", "S5-qa-automator-1", ["t4"], n=4)
        job(troot, "j5", "manual", "S6-qa-runner-1", ["t1"], exec_status="", n=5)
        job(troot, "j6", "diagnostic", "S6-qa-runner-1", ["t1"], n=6)
        got = RN.test_run_counts(troot)
        check_eq("S8 an unknown purpose is unknown with its id; build and collect are not runs",
                 (got["runs"], got["by_cause"], got["unknown_jobs"]),
                 (4, {"first_run": 1, "diagnostic": 1, "unknown": 2}, ["j2", "j5"]))
        check_eq("S8 the purposes are counted as the data names them", got["by_purpose"],
                 {"diagnostic": 1, "initial": 1, "manual": 1, "weird_purpose": 1})
        events(troot, [{"id": "S6-qa-runner-1", "repair_cause": "question_answer"}])
        said = RN.test_run_counts(troot)
        check_eq("S8 a manual run is the person's only when its dispatch says so; a weird purpose stays unknown",
                 (said["by_cause"].get("person"), said["by_cause"].get("unknown")), (1, 1))
        sums("S8", said)
    finally:
        cleanup(root)
    root, base, troot = story()
    try:
        job(troot, "r1", "initial", "S5-qa-automator-1", ["t1"], status="running", exec_status="", n=1)
        job(troot, "r2", "initial", "S5-qa-automator-1", ["t2"], exec_status="broken_run", n=2)
        job(troot, "r3", "initial", "S5-qa-automator-1", ["t3"], exec_status="failed_to_launch", n=3)
        job(troot, "r4", "initial", "S5-qa-automator-1", ["t4", "t5", "t6"], exec_status="not_executed", n=4)
        got = RN.test_run_counts(troot)
        check_eq("S9 a job that executed nothing (not completed, broken_run, failed_to_launch) is not a run",
                 (got["not_executed"], got["runs"]), (3, 3))
        check_eq("S9 a plain not_executed status with totals is counted in no_totals and its tests are runs",
                 (got["no_totals"], got["tests"]), (1, 3))
        sums("S9", got)
        check_in("S9 the retro says what it did not count", "3 jobs executed nothing and are not counted",
                 "\n".join(RN.test_run_lines(got)))
    finally:
        cleanup(root)
    root, base, troot = story()
    try:
        job(troot, "n1", "initial", "S5-qa-automator-1", [], n=1)
        job(troot, "n2", "initial", "S5-qa-automator-2", ["a", "b"], n=2)
        got = RN.test_run_counts(troot)
        check_eq("S10 a job naming no test is one run and a no_instances; tests are the union of what is named",
                 (got["runs"], got["no_instances"], got["tests"], got["by_cause"]), (3, 1, 2, {"first_run": 2, "unknown": 1}))
        sums("S10", got)
    finally:
        cleanup(root)


def manual_after_a_red_and_baselines() -> None:
    """F9: a manual run after a red run is `unknown` unless its dispatch says `person` (S8). F6: a baseline capture is no run."""
    root, base, troot = story()
    try:
        block(troot, 1, "initial", "S5-qa-automator-1", "failed", ["t1"])
        job(troot, "m1", "manual", "S6-qa-runner-1", ["t1", "t2"], n=2)       # a manual run is a job: no run block is written for it
        got = RN.test_run_counts(troot)
        check_eq("F9 manual after a red run: unknown (not after_red); a manual run of a new test is a first run",
                 got["by_cause"], {"first_run": 2, "unknown": 1})
        check_eq("F9 and the launch is named", got["unknown_jobs"], ["m1"])
        events(troot, [{"id": "S6-qa-runner-1", "repair_cause": "question_answer"}])
        check_eq("F9 the dispatch says the person asked: person", RN.test_run_counts(troot)["by_cause"],
                 {"first_run": 2, "person": 1})
        events(troot, [{"id": "S6-qa-runner-1", "repair_cause": "environment"}])
        check_eq("F9 a dispatch that names another cause is not the person's word: unknown", RN.test_run_counts(troot)["by_cause"],
                 {"first_run": 2, "unknown": 1})
    finally:
        cleanup(root)
    root, base, troot = story()
    try:
        job(troot, "base1", "initial", "S5-qa-automator-1", ["t1", "t2"], n=1)
        path = troot / "state" / "execution-jobs" / "base1.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["request"]["evidence_phase"] = "baseline"
        record["execution_status"] = "failed"
        path.write_text(json.dumps(record), encoding="utf-8")
        job(troot, "ver1", "initial", "S5-qa-automator-1", ["t1", "t2"], n=2)
        got = RN.test_run_counts(troot)
        check_eq("F6 a baseline job then a verification job: 2 tests, 2 runs, both first runs, the baseline apart",
                 (got["tests"], got["runs"], got["launches"], got["baselines"], got["by_cause"]),
                 (2, 2, 1, 1, {"first_run": 2}))
        sums("F6", got)
        check_in("F6 the retro says what it did not count", "1 baseline capture (old code, not a test run) is not counted",
                 "\n".join(RN.test_run_lines(got)))
    finally:
        cleanup(root)


def damaged_blocks_and_jobs() -> None:
    """F5: a block or a job of a shape the factory does not write is counted and named; the retro and the dashboard go on."""
    root, base, troot = story()
    try:
        block(troot, 1, "initial", "S5-qa-automator-1", "passed", ["t1"])
        folder = troot / "work" / "run-blocks"
        raw = {"20260002-b02.json": {"block_id": "b02", "purpose": "initial", "results": 5},
               "20260003-b03.json": {"block_id": "b03", "purpose": ["initial"], "results": []},
               "20260004-b04.json": [1, 2],
               "20260005-b05.json": {"block_id": "b05", "purpose": "initial", "attempt_started_at": stamp(5),
                                     "results": [{"instance_id": ["a"], "status": "passed"}, {"instance_id": "t9", "status": "passed"},
                                                 "not a row"]}}
        for name, body in raw.items():
            (folder / name).write_text(json.dumps(body), encoding="utf-8")
        job(troot, "jbad", "initial", "S5-qa-automator-1", None, n=6)
        path = troot / "state" / "execution-jobs" / "jbad.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["request"]["selected_instance_ids"] = "abc"
        path.write_text(json.dumps(record), encoding="utf-8")
        got = RN.test_run_counts(troot)
        check_eq("F5 the damaged blocks (results 5, purpose a list, not an object) are counted, the job whose selection is a string too",
                 (got["unreadable_blocks"], got["unreadable"]), (3, 1))
        check_eq("F5 a row whose instance_id is a list names no test, and still counts as a run; the good rows count",
                 (got["runs"], got["no_instances"], got["tests"]), (3, 1, 2))
        sums("F5", got)
        text = "\n".join(RN.test_run_lines(got))
        check_in("F5 the retro names the blocks", "3 run block files could not be read", text)
        check_in("F5 and the job", "1 job file could not be read", text)
        import factory_dashboard as FD
        check_in("F5 the dashboard's line is still printed", "runs", FD.test_runs_line({"artifact_path": str(troot)}))
        check_in("F5 and so are the retro's lines", "**Test runs:**", "\n".join(RN.test_run_lines(got)))
    finally:
        cleanup(root)


def the_limit_of_ten_ids() -> None:
    """S11: the line names ten launch ids whole, and "and N more" beyond; the JSON keeps all of them."""
    def counts(n: int) -> dict:
        ids = [f"j{i:02d}" for i in range(n)]
        return {"known": True, "tests": 1, "runs": n, "launches": n, "unknown_jobs": ids, "by_cause": {"unknown": n}}
    at = RN.test_run_lines(counts(10))
    check_in("S11 at the limit: ten ids, all of them", "j00, j01, j02, j03, j04, j05, j06, j07, j08, j09.", at)
    check_not_in("S11 at the limit: no 'more'", "more", at)
    beyond = RN.test_run_lines(counts(11))
    check_in("S11 beyond: ten ids and one more", "j09 and 1 more.", beyond)
    check_not_in("S11 beyond: the eleventh id is not on the line", "j10", beyond)
    root, base, troot = story()
    try:
        for i in range(11):
            job(troot, f"w{i:02d}", "weird_purpose", "S5-qa-automator-1", [f"t{i}"], n=i + 1)
        got = RN.test_run_counts(troot)
        check_eq("S11 the JSON always carries all eleven", len(got["unknown_jobs"]), 11)
        check_in("S11 and the line cuts them", "and 1 more", "\n".join(RN.test_run_lines(got)))
    finally:
        cleanup(root)


def the_data_file() -> None:
    """S12: every target is a cause; the closed varieties of the controller and the vocabulary are all keys; the file
    absent is `known: false`, named; a target the table does not name is unknown, never a crash."""
    table = json.loads((harness.PLUGIN_ROOT / "references" / "test-run-causes.json").read_text(encoding="utf-8"))
    causes = set(table["causes"])
    targets = [t for name in ("by_purpose", "by_previous_status", "by_repair_cause", "by_triage_verdict")
               for t in table[name].values() if t is not None]
    check_eq("S12 every target of every table is one of the causes", [t for t in targets if t not in causes], [])
    import controller
    check_eq("S12 every controller REPAIR_CAUSES value is a key of by_repair_cause",
             [c for c in controller.REPAIR_CAUSES if c not in table["by_repair_cause"]], [])
    vocabulary = (harness.PLUGIN_ROOT / "handoffs" / "vocabulary.yaml").read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(vocabulary) if line.startswith("  # --- a triage verdict"))
    verdicts = []
    for line in vocabulary[start + 1:]:
        found = re.match(r'^  "?([A-Za-z_:]+)"?:', line)
        if not found:
            break
        verdicts.append(found.group(1))
    check("S12 the triage verdicts of vocabulary.yaml were read", "APP_BUG" in verdicts and "NOT_EXECUTED" in verdicts, str(verdicts))
    check_eq("S12 every vocabulary verdict is a key (NOT_EXECUTED as a null: skipped)",
             [v for v in verdicts if v not in table["by_triage_verdict"]], [])
    check_eq("S12 NOT_EXECUTED is not a cause", table["by_triage_verdict"]["NOT_EXECUTED"], None)
    check_in("S12 'unknown' is one of the causes", "unknown", table["causes"])
    check_eq("F8 every cause has its plain words in the data file, and nothing else does",
             sorted(table["words"]), sorted(table["causes"]))
    check_eq("F8 the words are not in code", hasattr(RN, "CAUSE_WORDS"), False)
    root, base, troot = story()
    original = RN.TEST_RUN_CAUSES_FILE
    try:
        shape_of_14857(troot)
        RN.TEST_RUN_CAUSES_FILE = troot / "nowhere.json"
        gone = RN.test_run_counts(troot)
        check_eq("S12 the file absent: known false, and it says which file", gone["known"], False)
        check_in("S12 the reason names the file", "test-run-causes.json", gone["reason"])
        text = RN.render(RN.numbers("QA-1", base, troot))
        check_in("S12 the retro does not fall and says not recorded", "not recorded", text)
        bogus = dict(table, by_previous_status={"broken_run": "no_such_cause", "failed": "after_red", "passed": "stage_run"})
        RN.TEST_RUN_CAUSES_FILE = troot / "bogus.json"
        RN.TEST_RUN_CAUSES_FILE.write_text(json.dumps(bogus), encoding="utf-8")
        got = RN.test_run_counts(troot)
        check_eq("S12 a target the table does not name is unknown, not a crash and not a default",
                 got["by_cause"].get("unknown"), 9)
        sums("S12 bogus", got)
    finally:
        RN.TEST_RUN_CAUSES_FILE = original
        cleanup(root)


def dashboard_and_ledger() -> None:
    """S13 and S14: the dashboard prints the retro's sentence; the estimate ledger carries the counts."""
    root, base, troot = story()
    try:
        shape_of_14857(troot)
        import factory_dashboard as FD
        sentence = RN.test_run_sentence(RN.test_run_counts(troot))
        check_eq("S13 the dashboard's line is the retro's sentence", FD.test_runs_line({"artifact_path": str(troot)}), sentence)
        data = RN.numbers("QA-1", base, troot)
        check_in("S13 and the retro carries the same phrase", sentence, RN.render(data))
        check_eq("S13 a task row with no folder prints nothing", FD.test_runs_line({}), "")
        facts = RN.estimate_facts(data)
        check_eq("S14 the ledger facts carry tests, runs, launches and the causes", facts["actual"]["test_runs"],
                 {"tests": 5, "runs": 31, "launches": 9,
                  "by_cause": {"first_run": 5, "launch_failed": 9, "after_red": 12, "stage_run": 5}})
        import estimate_record
        check_eq("S14 the record accepts the facts", estimate_record.facts_problems(facts), [])
        empty = RN.estimate_facts(dict(data, test_run_counts={"known": False, "reason": "x"}))
        check_eq("S14 a story with no carrier says unknown in the ledger, not zero runs",
                 empty["actual"]["test_runs"], {"known": False})
        check_eq("the retro of facts written before the key existed renders no test-run line",
                 "**Test runs:**" in RN.render({k: v for k, v in data.items() if k != "test_run_counts"}), False)
    finally:
        cleanup(root)


def main() -> None:
    split_by_hand_and_the_probe()
    real_shapes()
    unknown_over_default_and_precedence()
    empty_and_damaged()
    purposes_and_jobs_that_ran_nothing()
    manual_after_a_red_and_baselines()
    damaged_blocks_and_jobs()
    the_limit_of_ten_ids()
    the_data_file()
    dashboard_and_ledger()
    finish("test_retro_test_runs")


if __name__ == "__main__":
    main()
