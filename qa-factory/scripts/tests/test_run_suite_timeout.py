"""RH2-9: a test killed by the project's own pytest timeout is `timeout`, never "the stand" (K-T, K-L, K-J, K-R keys).

Run 14857: pytest-timeout killed TC-001 at 300 s, `run_suite` wrote `broken_run` with "read the raw log", the automator wrote
`blocked_by_env`, and a person spent 28 minutes proving the stand was fine. The runner's timeout lines are DATA in the pytest row of
`launch-causes.json`; `execution_request.pytest_timeout_setting` is the one reader of the project's limit. The hard-kill LOG fixture
is a REAL pytest-timeout 2.4.0 capture, paths redacted (hard-kill.txt, not .log: the package .gitignore holds *.log); the junit rows use the real message
`Failed: Timeout (>300.0s) from pytest-timeout.`
"""
import contextlib
import copy
import io
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import check, check_eq, check_in, cleanup, finish, temp_project, use_project  # noqa: E402

import execution_request as ER  # noqa: E402
import hooklib  # noqa: E402
import judge  # noqa: E402
import judge_run  # noqa: E402
import launch_check as LC  # noqa: E402
import run_suite as RUN  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "pytest-timeout"
PY = sys.executable
PYTEST = ["pytest", "tests/test_reindex.py"]
HARD_LOG = (FIX / "hard-kill.txt").read_text(encoding="utf-8")
ROOT = None


def request_of(*ids_and_reports) -> dict:
    ids = [i for i, _ in ids_and_reports]
    return {"selected_instance_ids": ids,
            "instance_contracts": {i: {"report_test_id": r} for i, r in ids_and_reports}}


def outcome(log=HARD_LOG, summary=None, request=None, argv=PYTEST, **more):
    return RUN.timeout_outcome(argv, log, {} if summary is None else summary, request or {}, ROOT, **more)


def parsed(name: str) -> dict:
    return RUN.parse_junitxml(FIX / name)


# --- K-L: the data and its validation -------------------------------------------------------------------------------

def k_l_the_data():
    row, problem = LC.runner_row(PYTEST)
    check_eq("K-L1 the shipped pytest row carries the three timeout keys, no problem",
             (problem, all(k in row for k in ("timeout_kill_line", "timeout_failure_message", "timeout_header_line"))), ("", True))
    real = "Failed: Timeout (>300.0s) from pytest-timeout."
    check_eq("K-L1 the real message matches and names the limit (the optional paren is load-bearing)",
             re.match(row["timeout_failure_message"], real).group("limit"), "300.0")
    check("K-L1 the kill banner and the header line match", bool(re.search(row["timeout_kill_line"], HARD_LOG, re.M))
          and re.search(row["timeout_header_line"], "timeout: 300.0s", re.M).group("limit") == "300.0")
    base = {"tool": "pytest", "append": ["--collect-only", "-q"], "ok_exits": [0, 5]}
    extras, problem = LC._runner_fields("t", dict(base, timeout_failure_message="^Failed: Timeout (>[0-9]+)"))
    check("K-L2 a timeout_failure_message with no `limit` group is a problem that names the key",
          extras is None and "timeout_failure_message" in problem and "limit" in problem, problem)
    extras, problem = LC._runner_fields("t", dict(base, timeout_kill_line="("))
    check("K-L2 a regex that does not compile is named", extras is None and "timeout_kill_line" in problem, problem)
    extras, problem = LC._runner_fields("t", dict(base, timeout_header_line=""))
    check("K-L2 an empty string is a problem", extras is None and "timeout_header_line" in problem, problem)
    extras, problem = LC._runner_fields("t", base)
    check_eq("K-L3 a row without the keys carries none: no fact", (problem, [k for k in extras if k.startswith("timeout")]), ("", []))


# --- K-T: the outcome -----------------------------------------------------------------------------------------------

def k_t_hard_kill_unit():
    block, note = outcome(request=request_of(("I1", "tests.test_reindex::test_reindex_last_indexed")))
    check_eq("K-T2 ONE instance selected: it is named, basis only_selected",
             (block["how"], block["tests"], block["test_basis"], note),
             ("hard_kill", ["tests.test_reindex::test_reindex_last_indexed"], "only_selected", ""))
    check_eq("K-T2 source is the project, the limit is not established without a configuration (no number is invented)",
             (block["source"], block["limit_s"], block["limit_from"].startswith("not established")), ("project", None, True))
    check_in("K-T2 the sentence says whose limit it was", "not a verdict on the stand", block["sentence"])
    check_eq("K-T1 a hard kill with no report is `timeout`, never broken_run",
             RUN.execution_status({"exit_code": 1, "timeout": block}), "timeout")
    for code in (2, 0):
        check_eq(f"K-T4 the banner, not the exit code ({code}), is the evidence",
                 RUN.execution_status({"exit_code": code, "timeout": outcome()[0]}), "timeout")
    check_eq("K-T5 no report, NO banner, exit 1: no block, broken_run (no timeout from silence)",
             (outcome(log="boom\n")[0], RUN.execution_status({"exit_code": 1})), (None, "broken_run"))
    check_eq("K-T5 a header line gives the run's own limit",
             outcome(log=HARD_LOG + "timeout: 120.0s\n")[0]["limit_s"], 120.0)


def k_t_sentence_and_block_rows():
    request = request_of(("I1", "tests.test_reindex::test_reindex_last_indexed"))
    block = outcome(request=request)[0]
    summary = {"execution_status": "timeout", "exit_code": 1, "timeout": block, "results": []}
    rows = RUN.build_run_block(dict(request, purpose="initial", profile_id="api"), summary, "att-1")["results"]
    check_eq("K-T3 the killed instance: not_run, report_matched False, reason_code project_timeout, the sentence as reason",
             (rows[0]["status"], rows[0]["report_matched"], rows[0]["reason_code"], rows[0]["reason"]),
             ("not_run", False, "project_timeout", block["sentence"]))
    unnamed = outcome()[0]
    check_eq("K-T11 several/unknown instances: unnamed, `a test of this run`",
             (unnamed["tests"], unnamed["test_basis"], unnamed["sentence"].startswith("a test of this run was killed")),
             ([], "not_established", True))


def k_t_stack_frame():
    two = request_of(("I1", "tests.test_reindex::test_reindex_last_indexed"), ("I2", "tests.test_other::test_x"))
    block = outcome(request=two)[0]
    check_eq("K-T11 several instances: the frame names exactly one (function AND file)",
             (block["tests"], block["test_basis"]), (["tests.test_reindex::test_reindex_last_indexed"], "stack_frame"))
    rows = RUN.build_run_block(dict(two, purpose="initial", profile_id="api"),
                               {"execution_status": "timeout", "exit_code": 1, "timeout": block, "results": []}, "a")["results"]
    check_eq("K-T11 / M10 only the named instance carries project_timeout",
             {r["instance_id"]: r.get("reason_code") for r in rows}, {"I1": "project_timeout", "I2": None})
    none = request_of(("I1", "tests.test_x::test_a"), ("I2", "tests.test_y::test_b"))
    check_eq("K-T11 no frame names one: not established", outcome(request=none)[1:] and outcome(request=none)[0]["tests"], [])
    same_function = request_of(("I1", "tests.test_reindex::test_reindex_last_indexed[a]"),
                               ("I2", "tests.test_reindex::test_reindex_last_indexed[b]"))
    check_eq("K-T11 two instances of the same function: not established (never a guess)",
             outcome(request=same_function)[0]["test_basis"], "not_established")
    other_file = request_of(("I1", "tests.test_elsewhere::test_reindex_last_indexed"), ("I2", "tests.test_y::test_b"))
    check_eq("K-T11 the function name alone is not enough: the file must be the frame's",
             outcome(request=other_file)[0]["tests"], [])


def k_t_report_rows():
    block, note = outcome(log="", summary=parsed("signal-failed.junit.xml"))
    check_eq("K-T7 4-style partial: one timed-out test among results keeps the status and adds the block",
             (block["how"], block["tests"], block["limit_s"], note, RUN.execution_status({"exit_code": 1, **parsed("signal-failed.junit.xml"), "timeout": block})),
             ("failed_in_report", ["tests.test_reindex::test_reindex_last_indexed"], 300.0, "", "failed"))
    both = parsed("teardown-timeout.junit.xml")
    block = outcome(log="", summary=both)[0]
    check_eq("K-T6 failure + teardown timeout: the block names it, both rows stay in failed[], status broken_run",
             (block["how"], len(both["failed"]), RUN.execution_status({"exit_code": 1, **both, "timeout": block})),
             ("failed_in_report", 2, "broken_run"))
    check_eq("K-T6 / M2 the banner with a parsed report is failed_in_report, never hard_kill",
             outcome(summary=parsed("signal-failed.junit.xml"))[0]["how"], "failed_in_report")
    for text, limit in (("Failed: Timeout (>300s) from pytest-timeout.", 300.0), ("Failed: Timeout (>300.0s) from pytest-timeout.", 300.0),
                        ("Failed: Timeout >0.5s", 0.5)):
        got = outcome(log="", summary={"totals": {"tests": 1}, "failed": [{"test": "t::a", "kind": "failure", "why": text}]})[0]
        check_eq(f"K-T6 limit table: {text}", got and got["limit_s"], limit)
    rows = RUN.build_run_block(request_of(("I1", "tests.test_reindex::test_reindex_last_indexed")) | {"purpose": "initial", "profile_id": "api"},
                               {"execution_status": "failed", "timeout": {"how": "failed_in_report", "source": "project",
                                "tests": ["tests.test_reindex::test_reindex_last_indexed"]},
                                "results": [{"test_id": "tests.test_reindex::test_reindex_last_indexed", "status": "failed",
                                             "reason": "Failed: Timeout (>300.0s) from pytest-timeout."}]}, "a")["results"]
    check_eq("K-T6 failed_in_report: status and reason stay the report's, reason_code is added",
             (rows[0]["status"], rows[0]["reason"], rows[0]["reason_code"]),
             ("failed", "Failed: Timeout (>300.0s) from pytest-timeout.", "project_timeout"))


def k_t_not_a_timeout():
    for why in ("TimeoutError: Timeout 30000ms exceeded", "Failed: timeout waiting for index", "AssertionError: Failed: Timeout (>3s)"):
        got = outcome(log="", summary={"totals": {"tests": 1}, "failed": [{"test": "t::a", "kind": "failure", "why": why}]})
        check_eq(f"K-T8 the test's own words are no block: {why}", got, (None, ""))
    check_eq("K-T9 / E5 a jest-junit row never meets pytest's patterns: no block, no note",
             outcome(log=HARD_LOG, summary=parsed("jest-junit.xml"), argv=["npx", "jest"]), (None, ""))
    real = LC.runner_row
    try:
        LC.runner_row = lambda argv: ({"tool": "pytest", "append": [], "ok_exits": [0]}, "")
        check_eq("K-T10 / E11 an older table without the keys: today's behaviour, no block, no note",
                 outcome(log=HARD_LOG), (None, ""))
        LC.runner_row = lambda argv: (None, "launch-causes.json collect_forms[0] `timeout_kill_line` is not a regular expression")
        block, note = outcome(log=HARD_LOG)
        check_eq("K-T10 a broken table: no block, and the note names the problem", (block, "timeout_kill_line" in note), (None, True))
    finally:
        LC.runner_row = real


def k_t_run_suite_own_kill():
    block, note = outcome(log="x", killed_by_run_suite=True, run_timeout_s=600)
    check_eq("K-T12 run_suite's own kill: source run_suite, how run_killed", (block["source"], block["how"], block["limit_s"]),
             ("run_suite", "run_killed", 600))
    check_eq("K-T12 exit 124 alone is not proof (the project's command may exit 124): no block", outcome(log="x")[0], None)
    check_eq("K-T12 status 124 is `timeout` as before", RUN.execution_status({"exit_code": 124}), "timeout")
    check_eq("K-T12 a run_killed block is not the project's (the judge/evidence readers ignore it)",
             block["how"] in LC.PROJECT_TIMEOUT_HOWS, False)


# --- K-T1 end to end: a real pytest whose test SIMULATES the thread-method kill (the banner and os._exit come from the test; pytest-timeout is not involved) -------------------------------------

KILL_TEST = '''import os, sys

def test_reindex_last_indexed():
    sys.stdout.write("\\n" + "+" * 30 + " Timeout " + "+" * 30 + "\\n")
    sys.stdout.flush()
    os._exit(1)
'''


def call(*argv) -> tuple:
    hooklib._PROJECT_ROOT_CACHE = None
    out, err = io.StringIO(), io.StringIO()
    old_argv, old_cwd = sys.argv, os.getcwd()
    sys.argv = ["run_suite.py", *[str(a) for a in argv]]
    os.chdir(ROOT)
    code = 0
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                RUN.main()
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 0
    finally:
        sys.argv = old_argv
        os.chdir(old_cwd)
    return code, out.getvalue() + err.getvalue()


def k_t1_end_to_end():
    (ROOT / "qa-factory" / "artifacts" / "TO-1").mkdir(parents=True, exist_ok=True)   # S0 creates a story folder; a run never does
    (ROOT / "tests").mkdir(exist_ok=True)
    (ROOT / "tests" / "test_reindex.py").write_text(KILL_TEST, encoding="utf-8")
    code, out = call("--task", "TO-1", "--label", "kill", "--", PY, "-m", "pytest", "-s", "tests/test_reindex.py")
    lines = [line for line in out.strip().splitlines() if line.startswith("{")]
    summary = json.loads(lines[-1]) if lines else {}
    check_eq("K-T1 e2e (simulated kill): the process died with exit 1 and no report; execution_status is timeout",
             (code, summary.get("execution_status")), (1, "timeout")) or print(out[-600:])
    check_eq("K-T1 e2e (simulated kill): the block is a hard kill of the project", (summary.get("timeout") or {}).get("how"), "hard_kill")
    check_in("K-T1 e2e (simulated kill): no_junitxml keeps its key and names the timeout", "per-test timeout killed the run", summary.get("no_junitxml", ""))
    check("K-T1 e2e (simulated kill): the old 'read the raw log' text is gone", "read the raw log" not in summary.get("no_junitxml", ""), summary.get("no_junitxml"))


# --- K-J1: the judge never moves a project-timeout run toward the stand ---------------------------------------------------------

def k_j1_judge_guard():
    asked = []
    saved = (judge.active, judge.ask, judge.judged_refusal)
    judge.active = lambda cfg: True
    judge.ask = lambda state, questions, **kw: {"status": "ok", "advisory": False, "answers": {
        "culprit": {"value": "stand_degraded", "confidence": 0.9, "decided": True}}}
    judge.judged_refusal = lambda *a, **kw: asked.append(a) or {"passed": True, "decision": {"value": "yes", "probability": 0.9}}
    try:
        summary = {"execution_status": "failed", "exit_code": 1, "totals": {"tests": 2, "failures": 1},
                   "failed": [{"test": "t::a", "kind": "failure", "why": "Failed: Timeout (>300.0s) from pytest-timeout."}],
                   "timeout": {"how": "failed_in_report", "source": "project", "tests": ["t::a"], "sentence": "t::a was killed by the project's per-test timeout"}}
        found = judge_run.diagnose(summary, cfg={"mode": "on"})
        check_eq("K-J1 the env-blocked question is never asked on a project-timeout run (nothing journalled)", asked, [])
        check_eq("K-J1 no `overrode` in the diagnosis, and its sentence never says env_blocked or 'check the stand'",
                 ("overrode" in found, "env_blocked" in found["sentence"], "check the stand" in found["sentence"]), (False, False, False))
        attached = copy.deepcopy(summary)
        judge_run.attach(attached, cfg={"mode": "on"})
        check_eq("K-J1 attach keeps the proven status and writes no execution_status_raw",
                 (attached["execution_status"], "execution_status_raw" in attached), ("failed", False))
        check_in("K-J1 the judge reads the run's own word on the timeout", "project's per-test timeout", judge_run.state_of(summary)["timeout"])
        plain = {k: v for k, v in summary.items() if k != "timeout"}
        judge_run.diagnose(plain, cfg={"mode": "on"})
        check_eq("K-J1 control: the same run without a timeout block IS asked", len(asked), 1)
    finally:
        judge.active, judge.ask, judge.judged_refusal = saved


# --- K-R: the one reader of the project's limit ------------------------------------------------------------------------------

def tree(files: dict) -> Path:
    base = Path(ROOT) / f"r{len(list(Path(ROOT).glob('r*')))}"
    for name, text in files.items():
        (base / name).parent.mkdir(parents=True, exist_ok=True)
        (base / name).write_text(text, encoding="utf-8")
    return base


def read(files: dict, argv=("pytest",), cwd=".", stop=None) -> dict:
    base = tree(files)
    return ER.pytest_timeout_setting(base / cwd, list(argv), stop or base)


def k_r_the_reader():
    pyproject = '[tool.pytest.ini_options]\ntimeout = 300\n'
    got = read({"pyproject.toml": pyproject})
    check_eq("K-R1 pyproject timeout = 300", (got["state"], got["limit_s"], got["source"]),
             ("configured", 300.0, "pyproject.toml [tool.pytest.ini_options] timeout"))
    got = read({"pyproject.toml": pyproject}, argv=("pytest", "--timeout=900"))
    check_eq("K-R2 / E3c --timeout=900 in the profile's command beats the ini (M8)", (got["limit_s"], got["source"]), (900.0, "the profile's command"))
    check_eq("K-R2 the spaced form", read({"pyproject.toml": pyproject}, argv=("pytest", "--timeout", "45"))["limit_s"], 45.0)
    got = read({"pytest.ini": "[pytest]\naddopts = -q --timeout 600\ntimeout = 300\n"})
    check_eq("K-R4 / E3d addopts beats `timeout`", (got["limit_s"], got["source"]), (600.0, "pytest.ini addopts"))
    check_eq("K-R3 timeout = 0 is disabled", read({"pytest.ini": "[pytest]\ntimeout = 0\n"})["state"], "disabled")
    check_eq("K-R3 timeout = 0.001 is configured", read({"pytest.ini": "[pytest]\ntimeout = 0.001\n"})["limit_s"], 0.001)
    check_eq("K-R3 no timeout key in the ini: none", read({"pytest.ini": "[pytest]\naddopts = -q\n"})["state"], "none")
    check_eq("K-R3 no ini file at all: none", read({"README": "x"})["state"], "none")
    check_eq("K-B5 a quoted numeric string is a valid timeout (float semantics)",
             read({"pyproject.toml": '[tool.pytest.ini_options]\ntimeout = "300"\n'})["limit_s"], 300.0)
    for label, files in (("a word", {"pytest.ini": "[pytest]\ntimeout = abc\n"}),
                         ("a negative", {"pytest.ini": "[pytest]\ntimeout = -5\n"}),
                         ("broken toml", {"pyproject.toml": "[tool.pytest.ini_options]\ntimeout = = 3"}),
                         ("a bool", {"pyproject.toml": "[tool.pytest.ini_options]\ntimeout = true\n"}),
                         ("an ini with no section header", {"pytest.ini": "timeout = 3\n"}),
                         ("pytest 9 pytest.toml", {"pytest.toml": "[pytest]\ntimeout = 3\n"})):
        got = read(files)
        check(f"K-R5 / K-R6 {label}: unreadable with a reason, never none and never a number",
              got["state"] == "unreadable" and got["limit_s"] is None and got["why"], str(got))
    base = tree({"pyproject.toml": pyproject, "sub/x.txt": "x"})
    got = ER.pytest_timeout_setting(base / "sub", ["pytest"], base / "sub")
    check_eq("K-R7 / E3e an ini ABOVE the project root is not read: none", got["state"], "none")
    got = ER.pytest_timeout_setting(base / "sub", ["pytest"], base)
    check_eq("K-R8 the walk goes up from the cwd to the root", got["limit_s"], 300.0)
    check_eq("K-R9 a cwd outside the root: none, never a raise", ER.pytest_timeout_setting(base.parent, ["pytest"], base)["state"], "none")
    check_eq("K-R9 junk arguments never raise", ER.pytest_timeout_setting(None, None, None)["state"], "unreadable")
    setup = read({"setup.cfg": "[tool:pytest]\ntimeout = 12\n"})
    check_eq("K-R1 setup.cfg [tool:pytest]", (setup["limit_s"], setup["source"]), (12.0, "setup.cfg [tool:pytest] timeout"))


# --- AR checks -------------------------------------------------------------------------------------------------------

def k_ar_no_literals():
    scripts = Path(__file__).resolve().parents[1]
    for name in ("run_suite.py", "s5_precheck.py"):
        text = (scripts / name).read_text(encoding="utf-8")
        for token in ("pytest-timeout", "ConnectionRefused", "ConnectionReset", "+++ Timeout"):
            check(f"K-AR1 {name} holds no runner text literal: {token}", token not in text.replace("pytest-timeout`", ""), token)
    check("K-AR22 the reason_code has a reader (s5_precheck)", "PROJECT_TIMEOUT_CODE" in (scripts / "s5_precheck.py").read_text(encoding="utf-8")
          or "project_timeout" in (scripts / "s5_precheck.py").read_text(encoding="utf-8"))


def main() -> None:
    global ROOT
    ROOT = temp_project("qa-run-suite-timeout-")
    use_project(ROOT)
    try:
        for step in (k_l_the_data, k_t_hard_kill_unit, k_t_sentence_and_block_rows, k_t_stack_frame, k_t_report_rows,
                     k_t_not_a_timeout, k_t_run_suite_own_kill, k_t1_end_to_end, k_j1_judge_guard, k_r_the_reader, k_ar_no_literals):
            step()
    finally:
        cleanup(ROOT)
    finish("run_suite timeout")


if __name__ == "__main__":
    main()
