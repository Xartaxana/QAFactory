"""Story runner, S0 stand and no-trace scenarios: the stand question at S0, a stand that does not answer
or answers, the stand block door, and an experiment that leaves no trace (`--no-trace`). Moved out of
`test_story_run.py` unchanged (t-017 D1 (h), D2 (a)/(b), D3 (a)); the shared scaffolding is in
`story_run_common.py`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from story_run_common import (  # noqa: E402
    D2_DEAD, D2_ENVIRONMENT, D3_JIRA, D3_MR, D3_WARNING, check, check_in, d2_alive_server, d2_stand_at,
    d3_receipt, eq, human_broken, json, rules_broken, run_scenarios, s0_answer, s0_findings, s0_pipeline,
    s0_project, s0_question, s0_run, s0_state, stub_calls,
)


def s0_stand_question() -> None:
    check_eq = eq
    task = "QA-1"

    # --- (h) a stand named in another case: the configured spelling is used ------------------------
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading

    class Alive(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Alive)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    root, task_root, env = s0_project(task, config={
        "environments": [{"name": "Local", "base_url": url}, {"name": "Staging", "base_url": url}],
        "environment": {"env_file": "", "base_url_key": "QA_BASE_URL", "health_url": url + "/health"}})
    env["QA_BASE_URL"] = url
    try:
        out = s0_run(root, env, task, "--env", "Nowhere")
        check_eq("D1(h) a stand that is not configured asks: exit 3", out.returncode, 3, out.stdout[-800:])
        ask = s0_question(task_root)
        check_eq("D1(h) the block is the stand's", s0_state(task_root).get("s0_block"), "stand")
        check_in("D1(h) it names the configured stands", "`Local`, `Staging`", ask)
        check_in("D1(h) and offers each stand as a priced option line", "(a) `Local` — run the tests of this story on that stand; it is checked when the stage starts", ask)
        check_in("D1(h) the second stand", "(b) `Staging` — run the tests of this story on that stand", ask)
        check_in("D1(h) and `go on` without one", "(c) `go on` — go on without a stand for now", ask)
        check_in("D1(h) and `stop`", "(d) `stop` — stop the story here; nothing runs", ask)
        check_eq("D1(h) the stand question obeys human-questions.md (every option has its three price lines)", rules_broken(ask), [])
        out = s0_answer(root, env, task, "stop", "--env", "Nowhere")
        check_eq("D1(h) `stop` at the stand question holds it: exit 3", out.returncode, 3, out.stdout[-800:])
        held = s0_question(task_root)
        check_in("D1(h) with the first line that says nothing runs", "You said to stop. Nothing runs and nothing is spent.", held)
        check_in("D1(h) and the stands and `go on` to go on after all", "answer `Local` or `Staging` or `go on`.", held)
        check_eq("D1(h) the block stays the stand's and nothing is written", (s0_state(task_root).get("s0_block"), (task_root / "pipeline.json").exists()),
                 ("stand", False))
        check_eq("D1(h) no conductor at the stop", stub_calls(root), [])
        out = s0_answer(root, env, task, "STAGING", "--env", "Nowhere")
        check_eq("D1(h) the stand named in another case is taken: exit 0", out.returncode, 0, out.stdout[-1500:] + out.stderr[-500:])
        check_eq("D1(h) and it is the configured spelling that is used", s0_pipeline(task_root)["environment"], "Staging")
        check_eq("D1(h) no pass, no finding for a stand chosen by name", "s0-pass" in s0_findings(root), False)
        check_eq("D1(h) no conductor", stub_calls(root), [])
    finally:
        harness.cleanup(root)
    root, task_root, env = s0_project(task, config={"environments": [{"name": "Local", "base_url": url}]})
    try:
        s0_run(root, env, task, "--env", "Nowhere")
        out = s0_answer(root, env, task, "go on")
        check_eq("D1(h) `go on` at the stand question: exit 0", out.returncode, 0, out.stdout[-1200:] + out.stderr[-500:])
        pipeline = s0_pipeline(task_root)
        check_eq("D1(h) with no stand, pending, to be asked before any test", (pipeline["environment"], pipeline["environment_pending"]), (None, True))
        check_in("D1(h) and its pass on the record", "S0: the stand question passed by the person's word",
                 " ".join(pipeline["warnings"]))
    finally:
        harness.cleanup(root)
    server.shutdown()


def d2_s0_dead_stand() -> None:
    """(a): a stand that does not answer, named or found by the only-stand rule, is a warning at S0."""
    task = "QA-1"
    root, task_root, env = s0_project(task, config={"environments": [{"name": "Local"}], "environment": D2_ENVIRONMENT})
    d2_stand_at(root, D2_DEAD)
    try:
        out = s0_run(root, env, task)
        eq("D2(a) a stand that does not answer does not stop S0: exit 0", out.returncode, 0, out.stdout[-1500:] + out.stderr[-500:])
        pipeline = s0_pipeline(task_root)
        eq("D2(a) pending, and the stand's NAME is kept", (pipeline["environment"], pipeline["environment_pending"]), ("Local", True))
        line = next((w for w in pipeline["warnings"] if w.startswith("stand Local:")), "")
        check_in("D2(a) the warning says it did not answer the check, with the probe's first blocking line",
                 "stand Local: it did not answer the check (the stand does not answer: " + D2_DEAD, line)
        check("D2(a) and that the story goes on and the stand is checked again before tests run",
              line.endswith("); the story goes on and the stand is checked again before tests run"), line)
        eq("D2(a) the warning obeys human-questions.md", human_broken(line), [])
        eq("D2(a) the digest says the stand is not confirmed", pipeline["stages"]["S0"]["digest"],
           "preflight green, env=Local (not confirmed)")
        check_in("D2(a) the probe's own output is in the driver's log", "NO ANSWER", out.stdout)
        check("D2(a) no S0 stop is open and nothing was asked",
              not s0_state(task_root).get("s0_block") and not (task_root / "state" / "driver-question.md").exists())
        eq("D2(a) no conductor", stub_calls(root), [])
    finally:
        harness.cleanup(root)
    # no `environment` block at all: a named stand is judged by the probe's Layer 1 (CX1-4: no address), never "not configured" - the same warning
    root, task_root, env = s0_project(task, config={"environments": [{"name": "Local"}]})
    try:
        out = s0_run(root, env, task)
        eq("D2(a) a project with no environment block does not stop S0 either: exit 0", out.returncode, 0, out.stdout[-1500:])
        pipeline = s0_pipeline(task_root)
        eq("D2(a) name kept, pending", (pipeline["environment"], pipeline["environment_pending"]), ("Local", True))
        check_in("D2(a) the reason is the probe's first blocking line", "stand Local: it did not answer the check (the stand has no address",
                 " ".join(pipeline["warnings"]))
    finally:
        harness.cleanup(root)


def d2_s0_alive_and_empty() -> None:
    """The positive control of (a), and (b): a stand that answers is confirmed; a project with none is pending."""
    task = "QA-1"
    server, alive = d2_alive_server()
    root, task_root, env = s0_project(task, config={"environments": [{"name": "Local"}], "environment": D2_ENVIRONMENT})
    d2_stand_at(root, alive)
    try:
        out = s0_run(root, env, task)
        eq("D2(a) control: a stand that answers: exit 0", out.returncode, 0, out.stdout[-1500:])
        pipeline = s0_pipeline(task_root)
        eq("D2(a) control: it is confirmed - the name and pending false", (pipeline["environment"], pipeline["environment_pending"]), ("Local", False))
        check("D2(a) control: and there is no stand warning", not [w for w in pipeline["warnings"] if w.startswith("stand ")])
        eq("D2(a) control: the digest carries the name alone", pipeline["stages"]["S0"]["digest"], "preflight green, env=Local")
    finally:
        harness.cleanup(root)
        server.shutdown()
    root, task_root, env = s0_project(task, config={"environments": []})
    try:
        out = s0_run(root, env, task)
        eq("D2(b) a project with no stand: exit 0", out.returncode, 0, out.stdout[-1500:])
        pipeline = s0_pipeline(task_root)
        eq("D2(b) no name, and pending TRUE (it used to be false)", (pipeline["environment"], pipeline["environment_pending"]), (None, True))
        check_in("D2(b) and the line saying so is still printed", "this project records no stand", out.stdout)
        eq("D2(b) the digest", pipeline["stages"]["S0"]["digest"], "preflight green, env=pending")
    finally:
        harness.cleanup(root)


def d2_s0_stand_block_door() -> None:
    """D1's stand block still works with the new semantics: naming a stand (any case) whose probe then
    fails is a warning, not a second stop; `go on` is pending with no name, as before."""
    task = "QA-1"
    root, task_root, env = s0_project(task, config={"environments": [{"name": "Local"}, {"name": "Staging"}],
                                                    "environment": D2_ENVIRONMENT})
    d2_stand_at(root, D2_DEAD)
    try:
        out = s0_run(root, env, task, "--env", "Nowhere")
        eq("D2 door: a stand that is not configured still asks at S0: exit 3", out.returncode, 3, out.stdout[-800:])
        out = s0_answer(root, env, task, "local", "--env", "Nowhere")
        eq("D2 door: naming a configured stand whose probe fails goes on: exit 0", out.returncode, 0, out.stdout[-1500:] + out.stderr[-500:])
        pipeline = s0_pipeline(task_root)
        eq("D2 door: the configured spelling is kept, pending", (pipeline["environment"], pipeline["environment_pending"]), ("Local", True))
        eq("D2 door: no conductor", stub_calls(root), [])
    finally:
        harness.cleanup(root)


def d3_s0_no_trace() -> None:
    """(a) `--no-trace` on a fresh S0: the record is written, and the tracker is not asked. The
    control is the same project without the flag, where the probe leaves its receipt."""
    task = "QA-1"
    root, task_root, env = s0_project(task, config=D3_JIRA)
    try:
        out = s0_run(root, env, task)
        eq("D3(a) control: an ordinary S0 passes: exit 0", out.returncode, 0, out.stdout[-1200:] + out.stderr[-500:])
        check("D3(a) control: the tracker-write probe leaves its receipt", d3_receipt(root).is_file())
        check("D3(a) control: pipeline.json carries no `no_trace` key", "no_trace" not in s0_pipeline(task_root))
    finally:
        harness.cleanup(root)
    root, task_root, env = s0_project(task, config=D3_JIRA)
    try:
        out = s0_run(root, env, task, "--no-trace")
        eq("D3(a) `--no-trace`: S0 passes: exit 0", out.returncode, 0, out.stdout[-1200:] + out.stderr[-500:])
        pipeline = s0_pipeline(task_root)
        eq("D3(a) pipeline.no_trace is true", pipeline.get("no_trace"), True)
        check_in("D3(a) and the run says what it is, on the warnings gate A shows", D3_WARNING, pipeline["warnings"])
        eq("D3(a) and it is the FIRST warning (gate A shows the first five)", pipeline["warnings"][0], D3_WARNING)
        check("D3(a) the tracker-write receipt is not written (and not touched)", not d3_receipt(root).exists())
        readiness = json.loads((root / "qa-factory" / "state" / "readiness.json").read_text(encoding="utf-8"))["capabilities"]
        for name in ("tracker_write", "external_writes"):
            check_in(f"D3(a) readiness.json of the copy says {name} is closed for this run",
                     "closed for this run", readiness[name]["note"])
        eq("D3(a) no conductor", stub_calls(root), [])
    finally:
        harness.cleanup(root)


def d3_s0_survives_a_stop() -> None:
    """The flag is a fact of the launch: an S0 stop, answered by a command line with no flags at all,
    still ends in a pipeline.json that carries it (pipeline.json is written only at the end of S0)."""
    task = "QA-1"
    root, task_root, env = s0_project(task, config=D3_JIRA)
    try:
        out = s0_run(root, env, task, "--no-trace", "--mr", D3_MR, "--branch", "feature/x")
        eq("D3 stop: two launch sources ask which to keep: exit 3", out.returncode, 3, out.stdout[-800:])
        eq("D3 stop: the flag is kept with the launch", s0_state(task_root).get("launch", {}).get("no_trace"), True)
        check("D3 stop: no pipeline.json yet", not (task_root / "pipeline.json").exists())
        out = s0_answer(root, env, task, "branch")
        eq("D3 stop: the answer, with no flags on the command line: exit 0", out.returncode, 0, out.stdout[-1200:] + out.stderr[-500:])
        eq("D3 stop: the story is still an experiment", s0_pipeline(task_root).get("no_trace"), True)
        check("D3 stop: and the tracker was never asked", not d3_receipt(root).exists())
        eq("D3 stop: no conductor", stub_calls(root), [])
    finally:
        harness.cleanup(root)


def main() -> None:
    run_scenarios([s0_stand_question, d2_s0_dead_stand, d2_s0_alive_and_empty,
                   d2_s0_stand_block_door, d3_s0_no_trace, d3_s0_survives_a_stop], [])
    harness.finish("test_story_run_s0_stand_trace")


if __name__ == "__main__":
    main()
