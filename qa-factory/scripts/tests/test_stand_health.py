"""stand_health: telling a degraded stand from a defective test.

The rows below are the real S5 runs of TP1-15045 (2026-09-21), reduced to the fields the
summary really carries: six UI cases in a row failed with `Locator expected to be visible`
and every one was repaired as a test defect. Replayed here, the signal has to fire on the
third different case and stay silent on everything that came before.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import stand_health  # noqa: E402

UI = "tests.ui.workflows."
API = "tests.api.workflows.test_validate_api::"
VISIBLE = "AssertionError: Locator expected to be visible"
FILL = ('failed on setup with "playwright._impl._errors.TimeoutError: Locator.fill: Timeout 30000ms '
        'exceeded.\nCall log:\n  - waiting for locator("#username")"')
HISTORY = UI + "test_workflow_version_history::test_version_history_button_accessible_from_visual_editor[chromium]"
GRAPH = UI + "test_workflow_visual_diff::test_visual_diff_has_single_graph_and_working_controls[chromium]"
ADDED = UI + "test_workflow_visual_diff::test_visual_diff_marks_only_the_added_node[chromium]"
REMOVED = UI + "test_workflow_visual_diff::test_visual_diff_removed_node_kept_visible_with_decoration[chromium]"
MODIFIED = UI + "test_workflow_visual_diff::test_visual_diff_modified_node_hides_changed_values[chromium]"


def summary(label, duration, tests, exit_code, failed=(), passed=(), environment="localhost"):
    """The shape `run_suite.run()` writes: see evidence/runs/*/<label>-<ts>.json."""
    out = {"task": "TP1-15045", "label": label, "command": ["poetry", "run", "pytest"],
           "exit_code": exit_code, "duration_s": duration, "reporter": "pytest",
           "execution_status": "failed" if failed else "passed",
           "runtime_probe_before": {"profile_id": "e2e-ui", "environment_id": environment}}
    if tests is None:
        out["no_junitxml"] = "nothing to parse — read the raw log"
        out["log_tail"] = ["ERROR: not found: ...::test_x[buffer-R3-vs-selected-R1]"]
        return out
    out["totals"] = {"tests": tests, "failures": len(failed), "errors": 0, "skipped": 0,
                     "passed": tests - len(failed), "time_s": duration}
    out["failed"] = [{"test": test, "kind": "failure", "why": why} for test, why in failed]
    out["results"] = ([{"test_id": test, "status": "failed", "reason": why} for test, why in failed]
                      + [{"test_id": test, "status": "passed", "reason": ""} for test in passed])
    return out


REAL_RUN = [
    # API work in the morning: two different failures, a red probe, a run where nothing ran.
    ("initial-ca25918565df", 65.8, 13, 1, [(API + "test_outcome[sub-workflow-self-reference]",
                                           'AssertionError: validate status for partition: {"message":"Workflow configuratio'),
                                          (API + "test_same_warnings", "TimeoutError: Entity was not found within the timeout period.")]),
    ("repair_verify-e10ecaab0f13", 25.0, 7, 3, []),
    ("repair_verify-15ffdf4002d4", 16.3, 1, 0, []),
    ("red_probe-359d476251a2", 11.5, None, 4, []),
    ("red_probe-333edc6522ae", 22.6, 8, 1, [(API + "test_outcome[valid]", "AssertionError: validate status for partition: {")]),
    ("repair_verify-d9683258f11f", 26.3, 1, 0, []),
    ("repair_verify-43a00ca4b0d4", 27.0, 1, 0, []),
    ("initial-c2175c9dd1a2", 9.0, None, 4, []),
    # The afternoon: the same UI case three times, then five more cases, one line throughout.
    ("initial-5b34ed1ceb62", 406.8, 1, 1, [(HISTORY, VISIBLE)]),
    ("initial-8f5ada8bc99c", 526.5, 1, 1, [(HISTORY, VISIBLE)]),
    ("initial-40e71ec4046d", 643.2, 1, 1, [(HISTORY, VISIBLE)]),
    ("initial-e98b1f4f84a6", 447.4, 1, 1, [(GRAPH, VISIBLE)]),
    ("initial-28d3111700ef", 380.4, 1, 1, [(ADDED, VISIBLE)]),       # <- third different case
    ("initial-80f8b5474d1f", 293.0, 1, 1, [(REMOVED, VISIBLE)]),
    ("initial-a6c4f55a424f", 275.2, 1, 1, [(MODIFIED, VISIBLE)]),
]


def fresh_project(section=None):
    root = temp_project("qa-stand-health-")
    path = root / "qa-factory" / "config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["stand_health"] = {"probe_on_signal": False, **(section or {})}
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return root


def record(root) -> dict:
    return json.loads((root / "qa-factory" / "state" / "stand-health.json").read_text(encoding="utf-8"))


def replay_the_real_run():
    root = fresh_project()
    try:
        signals = []
        for label, duration, tests, exit_code, failed in REAL_RUN:
            passed = [API + "test_ok"] * ((tests or 0) - len(failed))
            signals.append((label, stand_health.observe(root, "TP1-15045", summary(
                label, duration, tests, exit_code, failed, passed))))
        fired = [label for label, signal in signals if signal]
        check_eq("the real run: silent until the third different case, then on every further one",
                 fired, ["initial-28d3111700ef", "initial-80f8b5474d1f", "initial-a6c4f55a424f"])
        signal = dict(signals)["initial-28d3111700ef"]
        check_eq("the signal has the fixed shape",
                 (signal["signal"], signal["reason"], sorted(signal)),
                 ("stand_suspect", "same_failure", ["evidence", "reason", "sentence", "signal"]))
        check_in("the sentence quotes the shared line", "Locator expected to be visible", signal["sentence"])
        check_in("and tells the person what it means", "points at the stand", signal["sentence"])
        check("the sentence is one ASCII sentence (any console prints it)",
              signal["sentence"].isascii() and "\n" not in signal["sentence"])
        check_eq("the evidence names the three cases, newest first",
                 [row.split(":", 1)[0] for row in signal["evidence"]],
                 ["test_visual_diff_marks_only_the_added_node",
                  "test_visual_diff_has_single_graph_and_working_controls",
                  "test_version_history_button_accessible_from_visual_editor"])
        last = dict(signals)["initial-a6c4f55a424f"]
        check_in("later signals count on: five different tests", "5 different tests", last["sentence"])
        rows = record(root)["runs"]
        check_eq("the record keeps the signal with its run",
                 [row["signal"] for row in rows[-3:]], ["same_failure"] * 3)
        check_eq("a red probe and a run where nothing ran are kept but do not count",
                 [(row["label"], row["counts"]) for row in rows if not row["counts"]],
                 [("repair_verify-e10ecaab0f13", False), ("red_probe-359d476251a2", False),
                  ("red_probe-333edc6522ae", False), ("initial-c2175c9dd1a2", False)])
        check_eq("the stand's name comes from the runtime probe of the summary",
                 rows[-1]["environment"], "localhost")

        # A green run ends the row of identical failures.
        check_eq("a green run gives no signal",
                 stand_health.observe(root, "TP1-15045", summary("repair_verify-79ca1fd32c77", 147.1, 1, 0,
                                                                     [], [REMOVED])), None)
        after = stand_health.observe(root, "TP1-15045", summary("repair_verify-2593b25cfadf", 149.4, 1, 1,
                                                                    [(ADDED, VISIBLE)]))
        check_eq("and the count starts again after it", after, None)
        shown = run_script("stand_health.py", "--project-root", root, "--status")
        status = json.loads(shown.stdout)
        check_eq("--status names the last signal", status["last_signal"]["label"], "initial-a6c4f55a424f")
    finally:
        cleanup(root)


def same_failure_rules():
    root = fresh_project()
    try:
        # The parallel-run incident: setup timeouts whose numbers and selectors differ.
        other = FILL.replace("30000", "45000").replace("#username", "#password")
        first = stand_health.observe(root, "T", summary("diagnostic-1", 249.5, 1, 1, [(HISTORY, FILL)]))
        second = stand_health.observe(root, "T", summary("diagnostic-2", 180.8, 1, 1, [(REMOVED, other)]))
        third = stand_health.observe(root, "T", summary("diagnostic-3", 213.9, 1, 1, [(ADDED, FILL)]))
        check("digits and quoted values do not split one failure into three",
              first is None and second is None and bool(third) and third["reason"] == "same_failure")
        check("the sentence survives a failure line full of quotes",
              third["sentence"].isascii() and '"' not in third["sentence"])
    finally:
        cleanup(root)

    root = fresh_project()
    try:
        params = [(API + f"test_outcome[{name}]", "AssertionError: validate status for partition: {") for name in
                  ("valid", "missing-assistant", "self-reference", "unknown-tool")]
        check_eq("four partitions of one parametrized test are one case, not four",
                 stand_health.observe(root, "T", summary("initial-p", 60.0, 4, 1, params)), None)
        bare = [stand_health.observe(root, "T", summary(f"initial-b{i}", 30.0, 1, 1,
                                                        [(API + f"test_b{i}", "AssertionError")])) for i in range(4)]
        check_eq("a bare exception name is not a shared failure", bare, [None] * 4)
    finally:
        cleanup(root)

    root = fresh_project()
    try:
        for index, (test, stand) in enumerate([(HISTORY, "localhost"), (GRAPH, "preview"), (ADDED, "localhost")]):
            signal = stand_health.observe(root, "T", summary(f"initial-e{index}", 300.0, 1, 1,
                                                             [(test, VISIBLE)], environment=stand))
        check_eq("failures on another stand are not this stand's", signal, None)
        signal = stand_health.observe(root, "T", summary("initial-e3", 300.0, 1, 1, [(REMOVED, VISIBLE)]))
        check("the third case on the same stand is", bool(signal))
    finally:
        cleanup(root)

    root = fresh_project({"same_failure_cases": 2})
    try:
        stand_health.observe(root, "T", summary("initial-1", 300.0, 1, 1, [(HISTORY, VISIBLE)]))
        signal = stand_health.observe(root, "T", summary("initial-2", 300.0, 1, 1, [(GRAPH, VISIBLE)]))
        check("stand_health.same_failure_cases is read from the config", bool(signal))
        probes = [stand_health.observe(root, "T", summary(f"red_probe-{i}", 250.0, 1, 1, [(test, VISIBLE)]))
                  for i, test in enumerate((ADDED, REMOVED, MODIFIED))]
        check_eq("a red probe fails on purpose and never signals", probes, [None] * 3)
        tagged = summary("whatever-label", 250.0, 1, 1, [(ADDED, VISIBLE)])
        tagged["purpose"] = "red_probe"
        check_eq("an explicit purpose field is honoured too", stand_health.observe(root, "T", tagged), None)
    finally:
        cleanup(root)


def slow_run_rules():
    root = fresh_project()
    try:
        for index, seconds in enumerate((20.9, 21.6, 24.5, 27.0)):
            stand_health.observe(root, "T", summary(f"repair_verify-a{index}", seconds, 1, 0, [], [API + "test_ok"]))
        check_eq("a UI run is not slow because the API runs before it were quick",
                 stand_health.observe(root, "T", summary("initial-ui0", 232.4, 1, 0, [], [HISTORY])), None)
        check_eq("fewer than three comparable runs say nothing",
                 stand_health.observe(root, "T", summary("initial-ui1", 900.0, 1, 0, [], [GRAPH])), None)
        stand_health.observe(root, "T", summary("initial-ui2", 147.1, 1, 0, [], [ADDED]))
        stand_health.observe(root, "T", summary("initial-ui3", 149.4, 1, 0, [], [REMOVED]))
        check_eq("a run under three medians is not slow",
                 stand_health.observe(root, "T", summary("initial-ui4", 400.0, 1, 0, [], [MODIFIED])), None)
        slow = stand_health.observe(root, "T", summary("initial-ui5", 1518.0, 1, 0, [], [MODIFIED]))
        check("a run over three medians of its peers is", bool(slow) and slow["reason"] == "slow_run")
        check_in("the sentence gives both numbers", "1518s", slow["sentence"])
        check("and is ASCII", slow["sentence"].isascii())
        check_in("the evidence shows the median", "median of", "\n".join(slow["evidence"]))
        check_eq("an API run of 70 s against 22 s IS slow (over the floor)",
                 (stand_health.observe(root, "T", summary("repair_verify-a9", 70.0, 1, 0, [], [API + "test_ok"]))
                  or {}).get("reason"), "slow_run")
        check_eq("a 12-test run is not compared with single tests",
                 stand_health.observe(root, "T", summary("initial-many", 400.0, 12, 0, [], [API + "test_ok"] * 12)), None)
    finally:
        cleanup(root)

    root = fresh_project()
    try:
        for index in range(3):
            stand_health.observe(root, "T", summary(f"unit-{index}", 2.5, 1, 0, [], [API + "test_ok"]))
        check_eq("9 s against 2.5 s is noise, not a slow stand (stand_health.slow_min_s)",
                 stand_health.observe(root, "T", summary("unit-9", 9.0, 1, 0, [], [API + "test_ok"])), None)
    finally:
        cleanup(root)

    root = fresh_project()
    try:
        # Red browser runs wait out timeouts and reruns: compare red with red when possible.
        for index, seconds in enumerate((147.0, 150.0, 149.0)):
            stand_health.observe(root, "T", summary(f"green-{index}", seconds, 1, 0, [], [HISTORY]))
        for index, seconds in enumerate((520.0, 540.0, 530.0)):
            stand_health.observe(root, "T", summary(f"red-{index}", seconds, 1, 1, [(HISTORY, f"AssertionError: step {index} differs from baseline")]))
        check_eq("an honest red run is measured against red runs",
                 stand_health.observe(root, "T", summary("red-9", 560.0, 1, 1,
                                                         [(HISTORY, "AssertionError: another step differs")])), None)
    finally:
        cleanup(root)


def the_runner_rows_exit_fact():
    """B-407 B-run: which exits mean "nothing was executed" is the runner row's fact, carried by the
    summary as `exit_means_not_executed`; None or absent is the legacy rule; 127 is the runner's own."""
    def counts(tests, exit_code, **extra):
        return stand_health._record("T", dict(summary("initial-x", 5.0, tests, exit_code), **extra))["counts"]
    check_eq("the legacy codes are launch_check's one copy", stand_health._LEGACY_NOT_EXECUTED, (2, 3, 4, 5))
    for exit_code in (2, 3, 4, 5):
        check_eq(f"absent field, exit {exit_code} with tests: the stand was not exercised (as before the rows)",
                 counts(3, exit_code), False)
        check_eq(f"None field, exit {exit_code}: the same legacy rule", counts(3, exit_code, exit_means_not_executed=None), False)
    for exit_code in (0, 1):
        check_eq(f"absent field, exit {exit_code} with tests: counts", counts(3, exit_code), True)
        check_eq(f"None field, exit {exit_code}: counts", counts(3, exit_code, exit_means_not_executed=None), True)
    check_eq("True: the row lists the code, so the run does not count (exit 1 here: data drives it)",
             counts(3, 1, exit_means_not_executed=True), False)
    check_eq("False: the row states its codes and does not list this one, so exit 2 with tests counts",
             counts(3, 2, exit_means_not_executed=False), True)
    check_eq("False with no tests still does not count", counts(0, 2, exit_means_not_executed=False), False)
    for value in (False, None):
        check_eq(f"127 is the runner's own launch failure: never counts (field {value})",
                 counts(3, 127, exit_means_not_executed=value), False)
    check_eq("a field that is not a bool is no fact: the legacy rule", counts(3, 4, exit_means_not_executed="no"), False)
    check_eq("... and exit 1 with it counts", counts(3, 1, exit_means_not_executed="yes"), True)
    red = stand_health._record("T", dict(summary("red_probe-x", 5.0, 3, 1), exit_means_not_executed=False))
    check_eq("a red probe never counts, whatever the row says", red["counts"], False)


def never_raises_and_stays_small():
    root = fresh_project()
    try:
        garbage = [None, [], "text", {}, {"failed": 7, "totals": "x", "results": {"a": 1}, "duration_s": "long"},
                   {"exit_code": [], "exit_means_not_executed": {}, "totals": {"tests": 1}},
                   {"exit_code": {"a": 1}, "exit_means_not_executed": [True], "totals": {"tests": 1}},
                   {"failed": [None, 3, {"test": None, "why": None}], "totals": {"tests": "1"}, "exit_code": "1"},
                   {"task": "T", "label": None, "exit_code": 127, "launch_error": "FileNotFoundError: poetry"},
                   {"runtime_probe_before": "matched", "results": [{"status": "failed"}], "totals": {"tests": 1}}]
        outcomes = []
        for item in garbage:
            try:
                outcomes.append(stand_health.observe(root, "T", item))
            except Exception as exc:  # the one thing this function must never do
                outcomes.append(exc)
        check_eq("observe never raises, whatever the summary looks like", outcomes, [None] * len(garbage))
        check_eq("a project root that does not exist is survived too",
                 stand_health.observe(root / "missing" / ("x" * 300), "T", summary("i", 1.0, 1, 0)), None)
        (root / "qa-factory" / "state" / "stand-health.json").write_text("{ broken", encoding="utf-8")
        check_eq("a corrupt record is started again", stand_health.observe(root, "T", summary("i-1", 5.0, 1, 0)), None)
        for index in range(45):
            stand_health.observe(root, "T", summary(f"i-{index}", 5.0, 1, 0, [], [API + "test_ok"]))
        check_eq("the record keeps the last 30 runs", len(record(root)["runs"]), 30)
        reset = run_script("stand_health.py", "--project-root", root, "--reset", "--reason", "stack restarted")
        check_eq("--reset forgets the runs", json.loads(reset.stdout), {"status": "reset", "dropped_runs": 30})
        check_eq("and keeps the person's reason", record(root)["reset"]["reason"], "stack restarted")
    finally:
        cleanup(root)


def the_probe():
    root = fresh_project()
    real_get = stand_health._get
    try:
        (root / "tests" / ".env").write_text(
            "API_DOMAIN=http://qa-user:hunter2@stand.example:8080\n"
            "FRONTEND_URL='http://stand.example:5173/?token=SECRETTOKEN'\n"
            "NATS_URL=nats://stand.example:4222\nAUTH_PASSWORD=hunter2\nAPI_KEY_URL=http://keys.example\n",
            encoding="utf-8")
        path = root / "qa-factory" / "config.json"
        cfg = json.loads(path.read_text(encoding="utf-8"))
        cfg["environment"] = {"env_file": "tests/.env", "base_url_key": "API_DOMAIN", "user_key": "AUTH_USERNAME",
                              "secret_keys": ["AUTH_PASSWORD"], "health_path": "/v1/config", "health_expect": [302],
                              "extra_keys": ["FRONTEND_URL", "NATS_URL", "API_KEY_URL"],
                              "integrations": [{"name": "gitlab", "health_url": "https://gitlab.example/-/health"}]}
        cfg["environments"] = [{"name": "localhost", "base_url": "http://localhost:8080",
                                "frontend_url": "http://localhost:5173", "auth_token_url": "http://idp.example"}]
        path.write_text(json.dumps(cfg), encoding="utf-8")

        asked = []

        def fake(url, expect):
            asked.append((url, list(expect)))
            return ("5173" not in url, f"{url} -> HTTP 200" if "5173" not in url else f"{url} -> NO ANSWER (URLError)")
        stand_health._get = fake
        result = stand_health.probe(root, "localhost")
        check_eq("URLs are found the way env_probe finds them, plus the named stand's own",
                 [c["name"] for c in result["checks"]],
                 ["liveness", "FRONTEND_URL", "integration gitlab", "localhost.base_url", "localhost.frontend_url"])
        check_eq("the liveness path is glued to the address from the env file",
                 asked[0], ("http://qa-user:hunter2@stand.example:8080/v1/config", [302]))
        check_eq("one dead URL makes the stand `down`", result["status"], "down")
        printed = json.dumps(result)
        check_not_in("a password inside a URL is never printed", "hunter2", printed)
        check_not_in("nor a token in its query", "SECRETTOKEN", printed)
        check_not_in("a key whose name looks secret is not even read", "keys.example", printed)
        check_in("the sentence says what does not answer", "does not answer", result["sentence"])
        check("every check is timed", all(isinstance(c["ms"], int) for c in result["checks"]))

        stand_health._get = lambda url, expect: (True, f"{url} -> HTTP 200")
        check_eq("all alive is `healthy`", stand_health.probe(root)["status"], "healthy")
        check_eq("without a stand name only the environment block is probed",
                 [c["name"] for c in stand_health.probe(root)["checks"]], ["liveness", "FRONTEND_URL", "integration gitlab"])

        cfg["stand_health"] = {"probe_slow_ms": 1}
        path.write_text(json.dumps(cfg), encoding="utf-8")

        def sluggish(url, expect):
            time.sleep(0.01)
            return (True, f"{url} -> HTTP 200")
        stand_health._get = sluggish
        check_eq("an answer slower than stand_health.probe_slow_ms is `degraded`",
                 stand_health.probe(root)["status"], "degraded")

        def explode(url, expect):
            raise RuntimeError("socket layer fell over")
        stand_health._get = explode
        check_eq("a failing GET is a dead URL, not an exception", stand_health.probe(root)["status"], "down")

        # A signal carries the probe, so the person's sentence says what the stand answered.
        stand_health._get = lambda url, expect: ("5173" not in url, "note")
        cfg["stand_health"] = {"same_failure_cases": 2}
        path.write_text(json.dumps(cfg), encoding="utf-8")
        stand_health.observe(root, "T", summary("initial-1", 300.0, 1, 1, [(HISTORY, VISIBLE)]))
        signal = stand_health.observe(root, "T", summary("initial-2", 300.0, 1, 1, [(GRAPH, VISIBLE)]))
        check_eq("a signal carries the probe of the run's own stand",
                 ((signal or {}).get("probe") or {}).get("status"), "down")
        check_in("and the sentence says which address did not answer",
                 "localhost.frontend_url did NOT answer", (signal or {}).get("sentence", ""))
    finally:
        stand_health._get = real_get
        cleanup(root)


RESULTS: list = []   # every probe result of this file: K-N3-18 reads them all
API_URL = "http://stand.example:8080/v1/config"


def page(code=200, kind="page"):
    """An answer the way `env_probe._fetch` returns one: a status and WHO wrote the body (`http_client` kind)."""
    import types
    return types.SimpleNamespace(status=code, verdict={"kind": kind, "said": "a page titled X"})


def stand(frontend=None, extra_keys=("FRONTEND_URL",), expect=(), environments=None, env_text="", health=True, secret_keys=()):
    """A project whose block names an API (8080), a frontend key and an integration; the answers are served by `serve`."""
    root = fresh_project()
    (root / "tests" / ".env").write_text(
        "API_DOMAIN=http://stand.example:8080\nFRONTEND_URL=http://stand.example:5173\n" + env_text, encoding="utf-8")
    path = root / "qa-factory" / "config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    block = {"env_file": "tests/.env", "base_url_key": "API_DOMAIN" if health else "", "user_key": "AUTH_USERNAME",
             "secret_keys": list(secret_keys), "health_path": "/v1/config" if health else "", "health_expect": list(expect),
             "extra_keys": list(extra_keys), "integrations": [{"name": "gitlab", "health_url": "https://gitlab.example/-/health"}]}
    if frontend is not None:
        block["frontend"] = frontend
    cfg["environment"] = block
    if environments is not None:
        cfg["environments"] = environments
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return root


def serve(api=200, fe=page(), feapi=200, other=200):
    """Answer by address (API 8080, frontend root, frontend API path, everything else) through the REAL `liveness`;
    returns the list of every URL that was asked."""
    import env_probe
    asked = []

    def fetch(url, timeout):
        asked.append(url)
        from urllib.parse import urlsplit
        parts = urlsplit(url)
        which = (api if parts.port == 8080 else other if parts.port != 5173
                 else fe if parts.path in ("", "/") else feapi)
        if isinstance(which, BaseException):
            raise which
        return which
    env_probe._fetch = fetch
    return asked


def run_probe(root, env=""):
    result = stand_health.probe(root, env)
    RESULTS.append(result)
    return result


def dependency_order():
    """RH1-7 N3: the probe names the FIRST dead part of the chain (AC-1, AC-2, AC-3, AC-5, AC-9)."""
    import urllib.error
    import env_probe
    real_fetch = env_probe._fetch
    FE = {"url_key": "FRONTEND_URL", "api_path": "/api/v1/config"}
    refused = urllib.error.URLError(ConnectionRefusedError())
    root = stand(FE)
    try:
        serve(api=refused, fe=page(), feapi=502)
        result = run_probe(root)
        d = result["diagnosis"]
        check_eq("K-N3-1 AC-1: the 26.10 shape is `down`, part api, cause nothing_listens", (result["status"], d["part"], d["cause"]),
                 ("down", "api", "nothing_listens"))
        check_in("K-N3-1 ... the sentence says nothing listens", "nothing listens", result["sentence"])
        check_in("K-N3-1 ... whatever its container shows", "whatever its container shows", d["sentence"])
        check_in("K-N3-1 ... and the frontend is not the cause", "The frontend is not the cause", d["sentence"])
        check_eq("K-N3-1 AC-3: the rest is listed after it", d["also"], ["frontend_proxy"])
        check_in("K-N3-1 the per-address notes follow", "Per address:", result["sentence"])
        check_eq("K-N3-1 the checks carry their role", [c["role"] for c in result["checks"]],
                 ["api", "frontend", "frontend_api", "integration"])

        for label, feapi in (("502", 502), ("no answer", urllib.error.URLError(ConnectionRefusedError())), ("500 empty", page(500, "empty")),
                             ("503 page", page(503, "page"))):
            serve(api=200, fe=page(), feapi=feapi)
            result = run_probe(root)
            check_eq(f"K-N3-2 AC-2: API alive, frontend alive, API path {label} -> frontend_proxy",
                     (result["status"], result["diagnosis"]["part"]), ("down", "frontend_proxy"))
            check_in(f"K-N3-2 ({label}) the sentence says the route is broken", "not through the frontend", result["sentence"])

        serve(api=refused, fe=page(), feapi=200)
        d = run_probe(root)["diagnosis"]
        check_eq("K-N3-3 E-F2: API dead, API path through the frontend alive -> part api", d["part"], "api")
        check_in("K-N3-3 ... and the contradiction is said", "may name different backends", d["sentence"])
        serve(api=refused, fe=refused, feapi=502)
        d = run_probe(root)["diagnosis"]
        check_eq("K-N3-3 E-F3 AC-3: everything dead -> api first, the frontend and its route after it", (d["part"], d["also"]),
                 ("api", ["frontend", "frontend_proxy"]))
        serve(api=200, fe=refused, feapi=502)
        d = run_probe(root)["diagnosis"]
        check_eq("K-N3-3 a dead frontend root with the API alive -> part frontend, its route after", (d["part"], d["also"]),
                 ("frontend", ["frontend_proxy"]))

        # K-N3-5 E-F5, K-N3-17 E-F19
        serve(api=200, fe=page(), feapi=page(200, "page"))
        result = run_probe(root)
        check_eq("K-N3-5 E-F5: a 200 HTML page through the frontend is `unknown`, exit 1 (status down)",
                 (result["status"], result["diagnosis"]["part"]), ("down", "unknown"))
        check_in("K-N3-5 ... it names the page and the way out", "returned a page, not the API's answer", result["sentence"])
        for label, feapi in (("302", 302), ("401 with cf-ray", page(401, "intermediary")), ("429", page(429, "service")),
                             ("414 html", page(414, "page")), ("400 cf-ray", page(400, "intermediary")), ("431", page(431, "unclear")),
                             ("500 empty", None), ("status 0", 0), ("string status", "200")):
            if feapi is None:
                continue
            serve(api=200, fe=page(), feapi=feapi)
            d = run_probe(root)["diagnosis"]
            check_eq(f"K-N3-7 invariant C: {label} through the frontend never proves the API", d["part"], "unknown")
        serve(api=200, fe=page(), feapi=page(200, "service"))
        check_eq("K-N3-5 control: the API's own JSON through the frontend is healthy",
                 (run_probe(root)["status"], RESULTS[-1]["diagnosis"]["part"]), ("healthy", "none"))
        serve(api=200, fe=page(), feapi=page(404, "service"))
        check_eq("K-N3-8 a 404 through the frontend: environment.frontend.api_path is wrong (config)",
                 run_probe(root)["diagnosis"]["part"], "config")
        serve(api=200, fe=page(), feapi=page(422, "service"))
        check_eq("K-N3-7 a 422 with the API's own message through the frontend -> config", run_probe(root)["diagnosis"]["part"], "config")
        serve(api=200, fe=page(), feapi=page(422, "ok"))
        check_eq("K-N3-7 ... but a 422 whose kind is `ok` is not shown to be the API's -> unknown", run_probe(root)["diagnosis"]["part"], "unknown")
        serve(api=200, fe=page(), feapi=page(500, "service"))
        d = run_probe(root)["diagnosis"]
        check_eq("K-N3-8 C9: a 500 the API wrote through the frontend is an API error", d["part"], "api")

        # the API's own address: K-N3-6, K-N3-7, K-N3-8
        serve(api=page(422, "service"))
        result = run_probe(root)
        check_eq("K-N3-6 C7b: 422 on the API direct -> part config", result["diagnosis"]["part"], "config")
        check_not_in("K-N3-6 ... the sentence does not say the stand does not answer", "does not answer", result["diagnosis"]["sentence"])
        serve(api=page(429, "service"))
        check_in("K-N3-7 C7a: 429 direct -> api, the API limits requests", "limits requests", run_probe(root)["diagnosis"]["sentence"])
        serve(api=page(400, "intermediary"))
        d = run_probe(root)["diagnosis"]
        check_eq("K-N3-7 C7c: 400 with cf-ray direct -> api, something in front refused", (d["part"], "Something in front" in d["sentence"]),
                 ("api", True))
        serve(api=502)
        check_eq("K-N3-8 C8: 502 on the API direct -> api", run_probe(root)["diagnosis"]["part"], "api")
        serve(api=page(500, "service"))
        check_in("K-N3-8 C9: 500 direct -> a server error", "server error", run_probe(root)["diagnosis"]["sentence"])
        serve(api=TimeoutError())
        check_in("K-N3-8 E-F11: a timeout on the API direct -> api, within 5 s", "within 5 s", run_probe(root)["diagnosis"]["sentence"])
        serve(api=200, feapi=TimeoutError())
        d = run_probe(root)["diagnosis"]
        check_eq("K-N3-8 E-F12: a timeout through the frontend with the API alive -> frontend_proxy", d["part"], "frontend_proxy")
        check_in("K-N3-8 ... the words say so", "no answer within 5 s through the frontend", d["sentence"])
        serve(api=urllib.error.URLError(__import__("socket").gaierror()))
        d = run_probe(root)["diagnosis"]
        check_eq("K-N3-1 a name that does not resolve is the network, first", (d["part"], d["cause"]), ("network", "name_unresolved"))
        serve(api=150)
        check_eq("K-N3-8 C10: HTTP 150 on the API is never alive", run_probe(root)["diagnosis"]["part"], "api")
        # K-N3-4 / K-N3-11: the healthy stand
        serve(api=200, fe=page(), feapi=page(200, "service"))
        result = run_probe(root)
        check_eq("K-N3-11 E-F15: all alive -> healthy, part none", (result["status"], result["diagnosis"]["part"], result["diagnosis"]["sentence"]),
                 ("healthy", "none", ""))
        check("K-N3-11 ... the sentence is today's form", result["sentence"].startswith("The stand answers: liveness in "))
    finally:
        env_probe._fetch = real_fetch
        cleanup(root)

    # K-N3-4 / AC-5: no frontend key -> today's checks, no frontend word; K-N3-9 E-F6, E-F7; K-N3-10 E-F10; the nesting battery
    try:
        for label, front in (("no key", None), ("empty object", {}), ("both empty", {"url_key": "", "api_path": ""})):
            root = stand(front)
            serve(api=refused, fe=page())
            result = run_probe(root)
            check_eq(f"K-N3-4 E-F4 ({label}): API-only, today's checks", [c["name"] for c in result["checks"]],
                     ["liveness", "FRONTEND_URL", "integration gitlab"])
            check_eq(f"K-N3-4 AC-5 ({label}): a dead API gets its cause class and no frontend line", (result["diagnosis"]["part"], "frontend" in result["sentence"].lower()),
                     ("api", False))
            cleanup(root)
        root = stand({"url_key": "NO_SUCH_KEY", "api_path": "/api/v1/config"})
        serve(api=200, fe=page())
        result = run_probe(root)
        check_eq("K-N3-9 E-F6: an unset frontend address is said, not probed, and the status is not lowered", result["status"], "healthy")
        check_in("K-N3-9 ... the line", "frontend configured but NO_SUCH_KEY is not set", result["sentence"])
        cleanup(root)
        root = stand({"url_key": "", "api_path": "/api/v1/config"})
        result = run_probe(root)
        check_in("K-N3-9 E-F7: an api_path with no frontend address is said", "frontend.api_path has no frontend address", result["sentence"])
        cleanup(root)
        for label, front in (("a list", [[]]), ("nesting", {"url_key": {"a": 1}, "api_path": ["/x"]}), ("null", None), ("a number", 5)):
            root = stand(front if label != "null" else None)
            if label == "null":
                path = root / "qa-factory" / "config.json"
                cfg = json.loads(path.read_text(encoding="utf-8"))
                cfg["environment"]["frontend"] = None
                path.write_text(json.dumps(cfg), encoding="utf-8")
            serve(api=200, fe=page())
            result = run_probe(root)
            check_in(f"K-N3-9 E-F18 ({label}): the block is unreadable, said, nothing raised", "frontend block unreadable", result["sentence"])
            check_eq(f"K-N3-9 ({label}): the probe goes on as API-only", [c["name"] for c in result["checks"]],
                     ["liveness", "FRONTEND_URL", "integration gitlab"])
            cleanup(root)
        root = stand({"url_key": "FRONTEND_URL", "api_path": "/api/v1/config"}, health=False)
        serve(feapi=502)
        result = run_probe(root)
        check_eq("K-N3-10 E-F10: no API address, the frontend's route dead -> unknown, and it says why",
                 (result["diagnosis"]["part"], "not configured" in result["diagnosis"]["sentence"]), ("unknown", True))
        cleanup(root)
        # K-N3-15 (host smuggling), the 4 KB path, the encoding row
        for bad in ("//evil.host/x", "http://evil/x", "@evil/x", "api/x", "/" + chr(92) + "x", chr(92) * 2 + "evil" + chr(92) + "x"):
            root = stand({"url_key": "FRONTEND_URL", "api_path": bad})
            asked = serve(api=200, fe=page())
            result = run_probe(root)
            check("K-N3-15 a path that leaves the frontend's host is refused: every URL asked is a known host",
                  all(u.startswith(("http://stand.example:8080", "http://stand.example:5173", "https://gitlab.example")) for u in asked)
                  and not any("evil" in u for u in asked), str(asked))
            check_in("K-N3-15 ... and the probe says it did not glue it", "is not a path starting with one /", result["sentence"])
            cleanup(root)
        for path in ("/" + "a" * 4096, "/api/v1/c" + chr(0xF6) + "nfig", "/api/%2e%2e/admin", "/" + chr(0x2028) + "x"):
            root = stand({"url_key": "FRONTEND_URL", "api_path": path})
            asked = serve(api=200, fe=page(), feapi=page(414, "page"))
            result = run_probe(root)
            check_eq("K-N3-15 an odd path is glued as given and judged by the table: a 414 page -> unknown, never 'proxy works'",
                     result["diagnosis"]["part"], "unknown")
            check("K-N3-15 ... every printed character is ASCII, the host is the frontend's", json.dumps(result, ensure_ascii=False).isascii()
                  and all(u.startswith("http://stand.example:5173") for u in asked if u.startswith("http://stand.example:5173")), "")
            cleanup(root)
        # K-N3-16 E-F20: the Test Project 1 shape: FRONTEND_URL in extra_keys AND frontend.url_key
        root = stand(FE)
        serve(api=200, fe=page(), feapi=page(200, "service"))
        result = run_probe(root)
        check_eq("K-N3-16 E-F20: ONE check named by the key, the API-path check after it",
                 [(c["name"], c["role"]) for c in result["checks"]],
                 [("liveness", "api"), ("FRONTEND_URL", "frontend"), ("FRONTEND_URL /api/v1/config", "frontend_api"), ("integration gitlab", "integration")])
        import re
        flat = re.sub(r"\d+ ms", "N ms", result["sentence"])
        check_eq("K-N3-16 ... the healthy sentence is today's plus the API-path check only",
                 flat.split(" No login")[0],
                 "The stand answers: liveness in N ms; FRONTEND_URL in N ms; FRONTEND_URL /api/v1/config in N ms; integration gitlab in N ms.")
        cleanup(root)
        # K-N3-17 E-F19: a declared 302 is the stand's norm for the API's address and NEVER for the frontend's API path
        root = stand(FE, expect=[302])
        serve(api=302, fe=page(), feapi=302)
        result = run_probe(root)
        check_eq("K-N3-17 E-F19: the API's own 302 is wants_login (alive), the frontend API path's 302 is unknown",
                 (result["checks"][0]["alive"], result["diagnosis"]["part"]), (True, "unknown"))
        check_eq("K-N3-17 ... the API path was probed with NO declared codes", [c["alive"] for c in result["checks"]], [True, True, False, True])
        cleanup(root)
    finally:
        env_probe._fetch = real_fetch


def frontend_edges():
    """RH1-7 N3: a named stand's own frontend (E-F13, E-F14), the remedy line (R-1..R-4), tuple fakes (E-F21), the order as
    data (K-N3-20), the CLI (K-N3-14), the secrets (K-N3-13), AC-9 (K-N3-18)."""
    import socket
    import subprocess
    import threading
    import urllib.error
    import env_probe
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    real_fetch, real_get, real_run = env_probe._fetch, stand_health._get, subprocess.run
    FE = {"url_key": "FRONTEND_URL", "api_path": "/api/v1/config"}
    refused = urllib.error.URLError(ConnectionRefusedError())
    roots = []
    try:
        # K-N3-10 E-F13 / E-F14: a named stand is never qualified by the block's frontend
        entry = {"name": "dev", "base_url": "http://dev.example:8080", "frontend": {"url": "http://dev.example:5173", "api_path": "/api/v1/user"}}
        legacy = {"name": "old", "base_url": "http://old.example:8080", "frontend_url": "http://old.example:5173"}
        root = stand(FE, environments=[entry, legacy]); roots.append(root)
        asked = serve(api=200, fe=page(), feapi=page(401, "service"), other=200)
        result = run_probe(root, "dev")
        names = [c["name"] for c in result["checks"]]
        check("K-N3-10 E-F13: the entry's frontend and its API path are checked", "dev.frontend" in names and "dev.frontend /api/v1/user" in names, str(names))
        check("K-N3-10 ... and the block's frontend API path is NOT borrowed", "FRONTEND_URL /api/v1/config" not in names
              and not any(u.endswith(":5173/api/v1/config") for u in asked), str(asked))
        asked = serve(api=200, fe=page(), feapi=200)
        result = run_probe(root, "old")
        names = [c["name"] for c in result["checks"]]
        check_eq("K-N3-10 E-F14: a legacy frontend_url is probed as today, no API-path check, role stand",
                 ([n for n in names if "old." in n], [c["role"] for c in result["checks"] if c["name"] == "old.frontend_url"]),
                 (["old.base_url", "old.frontend_url"], ["stand"]))
        check_eq("K-N3-10 an unknown --env falls back to the block alone", [c["name"] for c in run_probe(root, "nosuch")["checks"]],
                 ["liveness", "FRONTEND_URL", "FRONTEND_URL /api/v1/config", "integration gitlab"])
        same = {"name": "same", "base_url": "http://s.example:8080", "frontend_url": "http://s.example:5173",
                "frontend": {"url": "http://s.example:5173", "api_path": "/api/v1/config"}}
        cfgp = root / "qa-factory" / "config.json"
        cfg = json.loads(cfgp.read_text(encoding="utf-8"))
        cfg["environments"] = [same]
        cfgp.write_text(json.dumps(cfg), encoding="utf-8")
        serve()
        result = run_probe(root, "same")
        check_eq("K-N3-16 E-F20 (entry): the legacy frontend_url equal to frontend.url is ONE check, role frontend",
                 [(c["name"], c["role"]) for c in result["checks"] if c["name"].startswith("same.")],
                 [("same.api", "api"), ("same.base_url", "stand"), ("same.frontend_url", "frontend"),
                  ("same.frontend /api/v1/config", "frontend_api")])

        # K-N3-10b B1: a named stand's frontend chain is judged against THAT stand's API, never the block's live one
        stg = {"name": "stg", "base_url": "http://stg.example:9090",
               "frontend": {"url": "http://stg.example:5173", "api_path": "/api/v1/config"}}
        root = stand(FE, environments=[stg]); roots.append(root)

        def fetch_b1(url, timeout):
            from urllib.parse import urlsplit
            parts = urlsplit(url)
            if parts.port == 9090:
                raise refused
            if parts.port == 5173:
                return page() if parts.path in ("", "/") else page(502, "intermediary")
            return 200
        env_probe._fetch = fetch_b1
        result = run_probe(root, "stg")
        diag = result["diagnosis"]
        check_eq("K-N3-10b B1 stg API refused + stg frontend 502 -> part api, frontend_proxy only in also",
                 (diag["part"], "frontend_proxy" in diag["also"]), ("api", True))
        check("K-N3-10b ... and it never says the API answers on its own address",
              "answers on its own address" not in diag["sentence"], diag["sentence"])
        check_eq("K-N3-10b ... the cause is a word a person reads, not an internal tag (M3)", diag["cause"], "nothing_listens")
        check_eq("K-N3-10b ... the block's own API is outside this run's chain",
                 [c["name"] for c in result["checks"] if c["role"] == "api"], ["stg.api"])
        env_probe._fetch = real_fetch
        said: list = []
        env_probe.frontend_address("", "FRONTEND_URL", {}, said)  # M5: no table text still names what is missing
        check("K-N3-10c M5 a frontend address with no table text still says what is missing", len(said) == 1 and said[0].strip()
              and "missing" in said[0], str(said))
        check_eq("K-N3-10c M1/M2 one LOGIN_OUTCOMES and one api_path regex; the remedy goes through env_probe._row_takes",
                 (hasattr(stand_health, "LOGIN_OUTCOMES"), hasattr(stand_health, "_API_PATH"),
                  stand_health._login_remedy({"login_remedies": [{"outcomes": ["skipped"], "remedy": "R {user_key}"}]}, None, "skipped", "U")),
                 (False, False, "R U"))

        # S2 (t-1519): the block's frontend serves the ONLY entry (frontend_of, F-2 a), never one of several (E-F13)
        solo = {"name": "solo", "base_url": "http://solo.example:8080"}
        root = stand(FE, environments=[solo]); roots.append(root)
        serve(api=200, fe=page(), feapi=page(401, "service"), other=200)
        names = [c["name"] for c in run_probe(root, "solo")["checks"]]
        check("S2 AT one entry: the block's frontend and its API path are checked for the named entry",
              "FRONTEND_URL" in names and "FRONTEND_URL /api/v1/config" in names, str(names))
        root = stand(FE, environments=[solo, {"name": "other", "base_url": "http://other.example:8080"}]); roots.append(root)
        serve(api=200, fe=page(), feapi=page(401, "service"), other=200)
        checks = run_probe(root, "solo")["checks"]
        check_eq("S2 BEYOND two entries: the block's frontend is not borrowed (no API-path check, no frontend role)",
                 ("FRONTEND_URL /api/v1/config" in [c["name"] for c in checks],
                  [c["role"] for c in checks if c["name"] == "FRONTEND_URL"]), (False, ["extra"]))

        # K-N3-12 R-1..R-4: the remedy line; no subprocess is ever called
        def forbidden(*a, **k):
            raise AssertionError("the probe ran a command")
        subprocess.run = forbidden
        recipe = {"name": "dev", "base_url": "http://dev.example:8080", "bring_up": "docker compose up -d api && curl http://u:pw1234@dev.example:8080/x?token=abc "
                                                                                    "&& echo abcd ok xyz"}
        root = stand(FE, environments=[recipe], secret_keys=["AUTH_PASSWORD"], env_text="AUTH_PASSWORD=abcd\nOTHER_TOKEN=xyz\n"); roots.append(root)
        serve(api=refused, fe=page(), feapi=502)
        result = run_probe(root, "dev")
        remedy = result["diagnosis"]["remedy"]
        check_in("K-N3-12 R-1: the recipe is shown with the conductor clause", "Restarting is the conductor's move when it is authorized", remedy)
        check_in("K-N3-12 ... and the recipe itself", "docker compose up -d api", remedy)
        check_in("K-N3-12 ... in the sentence too", remedy, result["sentence"])
        check_not_in("K-N3-12 R-4: a 4-character secret value is replaced", "abcd", remedy)
        check_in("K-N3-12 R-4 ... by <redacted>", "<redacted>", remedy)
        check_in("K-N3-12 R-4 BEYOND the floor: a 3-character value is not masked", "xyz", remedy)
        check_not_in("K-N3-12 R-4: a URL in the recipe goes through _display: no userinfo", "pw1234", remedy)
        check_not_in("K-N3-12 ... and no query", "token=abc", remedy)
        subprocess.run = real_run
        result = run_probe(root, "")
        check_in("K-N3-12 R-2: no --env with exactly one entry -> that entry's recipe", "docker compose up -d api", result["diagnosis"]["remedy"])
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        cfg["environments"] = [recipe, {"name": "qa"}]
        (root / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        check_in("K-N3-12 R-2: with two entries and no --env -> no recipe", "No restart recipe is recorded", run_probe(root, "")["diagnosis"]["remedy"])
        check_in("K-N3-12 R-3: an entry without bring_up -> the no-recipe line", "No restart recipe is recorded", run_probe(root, "qa")["diagnosis"]["remedy"])
        serve(api=200, fe=page(), feapi=page(200, "service"))
        check_eq("K-N3-12 the remedy is printed only when the stand is down", run_probe(root, "dev")["diagnosis"]["remedy"], "")

        # K-N3-13: a password in the frontend URL and a token in its query are never printed
        root = stand(FE, env_text="FRONTEND_URL=http://qa-user:hunter2@stand.example:5173/?token=SECRETTOKEN\n"); roots.append(root)
        serve(api=refused, fe=page(), feapi=502)
        printed = json.dumps(run_probe(root))
        check("K-N3-13 neither the password nor the token reaches any text", "hunter2" not in printed and "SECRETTOKEN" not in printed)

        # K-N3-19 E-F21: a tuple fake has no means/cause, so the part comes from the role alone
        root = stand(FE); roots.append(root)
        for label, dead_port, part in (("API", 8080, "api"), ("frontend root", "root", "frontend"), ("frontend API path", "path", "frontend_proxy")):
            def fake(url, expect, dead_port=dead_port):
                from urllib.parse import urlsplit
                u = urlsplit(url)
                is_dead = (u.port == 8080 if dead_port == 8080 else u.port == 5173 and (u.path in ("", "/") if dead_port == "root"
                                                                                       else u.path not in ("", "/")))
                return (not is_dead, f"{url} -> {'NO ANSWER' if is_dead else 'HTTP 200'}")
            stand_health._get = fake
            d = run_probe(root)["diagnosis"]
            check_eq(f"K-N3-19 E-F21: a tuple fake dead at the {label} -> part {part}", (d["part"], d["cause"]), (part, "none"))
        stand_health._get = real_get
        # K-N3-20: the order is data: rows 2 and 5 swapped in a copy of the table -> the AC-1 shape names the frontend's route
        data = json.loads(env_probe.STAND_ANSWERS_PATH.read_text(encoding="utf-8"))
        for row in data["order"]:
            if row["id"] == "D2":
                row["order"] = 5
            elif row["id"] == "D5":
                row["order"] = 2
        import tempfile
        folder = Path(tempfile.mkdtemp(prefix="qa-order-"))
        saved = env_probe.STAND_ANSWERS_PATH
        try:
            (folder / "stand-answers.json").write_text(json.dumps(data), encoding="utf-8")
            serve(api=refused, fe=page(), feapi=502)
            check_eq("K-N3-20 baseline: the real table names the API", run_probe(root)["diagnosis"]["part"], "api")
            env_probe.STAND_ANSWERS_PATH = folder / "stand-answers.json"
            env_probe.reload_stand_answers()
            check_eq("K-N3-20 the order is data: swapped rows change the part (_diagnose has no order of its own)",
                     run_probe(root)["diagnosis"]["part"], "frontend_proxy")
            (folder / "broken.json").write_text("{ broken", encoding="utf-8")
            env_probe.STAND_ANSWERS_PATH = folder / "broken.json"
            env_probe.reload_stand_answers()
            result = run_probe(root)
            check_eq("K-N3-1 E-F17: an unreadable table is part unknown and never healthy", (result["status"], result["diagnosis"]["part"],
                                                                                           result["diagnosis"]["cause"]),
                     ("down", "unknown", "table_unreadable"))
            check_in("K-N3-1 ... it says the table could not be read", "could not be read", result["sentence"])
        finally:
            env_probe.STAND_ANSWERS_PATH = saved
            env_probe.reload_stand_answers()
            import shutil
            shutil.rmtree(folder, ignore_errors=True)

        # K-N3-14: the CLI on the AC-1 shape, over real sockets
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                code, body = (200, b"<!doctype html><html><title>app</title></html>") if self.path in ("", "/") else (502, b"")
                self.send_response(code)
                self.send_header("Content-Type", "text/html" if code == 200 else "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            dead_port = sock.getsockname()[1]
            sock.close()
            root = stand(FE, env_text=f"API_DOMAIN=http://127.0.0.1:{dead_port}\nFRONTEND_URL=http://127.0.0.1:{server.server_address[1]}\n"); roots.append(root)
            path = root / "qa-factory" / "config.json"
            cfg = json.loads(path.read_text(encoding="utf-8"))
            cfg["environment"]["integrations"] = []
            path.write_text(json.dumps(cfg), encoding="utf-8")
            shown = run_script("stand_health.py", "--project-root", root, "--probe")
            got = json.loads(shown.stdout)
            check_eq("K-N3-14 the CLI exits 1 on the AC-1 shape and names the API", (shown.returncode, got["diagnosis"]["part"]), (1, "api"))
        finally:
            server.shutdown()

        # K-N3-18 AC-9: the part is `none` iff the status is healthy or degraded, over every probe this file ran
        bad = [(r["status"], r["diagnosis"]["part"]) for r in RESULTS
               if (r["diagnosis"]["part"] == "none") != (r["status"] in ("healthy", "degraded"))]
        check_eq(f"K-N3-18 AC-9: part none iff healthy/degraded, over {len(RESULTS)} probes", bad, [])
        unconfigured = fresh_project(); roots.append(unconfigured)
        check_eq("K-N3-18 ... and a stand that could not be probed carries part unknown", stand_health.probe(unconfigured)["diagnosis"]["part"], "unknown")
    finally:
        env_probe._fetch, stand_health._get, subprocess.run = real_fetch, real_get, real_run
        for item in roots:
            cleanup(item)


def the_derived_address():
    """RN1-3 K-RN3-H1: a UI derived from the stand's own address adds NO target - the API target already is that address."""
    root = fresh_project()
    try:
        (root / "tests" / ".env").write_text("API_DOMAIN=http://stand.example:8080\nAUTH_USERNAME=u\n", encoding="utf-8")
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        cfg["environments"] = [{"name": "local", "base_url": "http://stand.example:8080"}]
        cfg["profiles"] = [{"profile_id": "e2e", "capabilities": ["web"]}]
        cfg["environment"] = {"env_file": "tests/.env", "base_url_key": "API_DOMAIN", "user_key": "AUTH_USERNAME",
                              "health_path": "/v1/config", "frontend": {"url_key": "", "api_path": ""},
                              "access": {"kind": "harness_command", "command": "npx playwright test", "user_key": "AUTH_USERNAME",
                                         "login_probe": {"user_key": "AUTH_USERNAME", "outcome": "ok", "checked_at": "2026-10-31T10:00:00"}}}
        import env_probe
        check_eq("K-RN3-H1 fixture: the reader derives the UI address here",
                 env_probe.frontend_of(cfg, "local", root=root)["same_origin"], True)
        plain = json.loads(json.dumps(cfg))
        del plain["environment"]["access"]
        check_eq("K-RN3-H1: the targets of a derived stand equal those of the same stand with no access block",
                 stand_health._targets(root, cfg, "local"), stand_health._targets(root, plain, "local"))
        check("K-RN3-H1: ... and no `frontend` role target is among them",
              all(role != "frontend" for _n, _u, _c, role in stand_health._targets(root, cfg, "local")))
    finally:
        cleanup(root)


def unconfigured_and_cli():
    root = fresh_project()
    try:
        result = stand_health.probe(root, "")
        check_eq("no address configured: said plainly, nothing probed", (result["status"], result["checks"]),
                 ("not_configured", []))
        check_eq("probe never raises on a project that is not there",
                 stand_health.probe(root / "nowhere")["status"], "not_configured")
        shown = run_script("stand_health.py", "--project-root", root, "--probe")
        check("--probe exits 1 when the stand cannot be called healthy",
              shown.returncode == 1 and json.loads(shown.stdout)["status"] == "not_configured")
        selftest = run_script("stand_health.py", "--selftest")
        check("--selftest passes", selftest.returncode == 0 and "FAIL" not in selftest.stdout)
    finally:
        cleanup(root)


if __name__ == "__main__":
    replay_the_real_run()
    same_failure_rules()
    slow_run_rules()
    the_runner_rows_exit_fact()
    never_raises_and_stays_small()
    the_probe()
    dependency_order()
    frontend_edges()
    the_derived_address()
    unconfigured_and_cli()
    finish("test_stand_health")
