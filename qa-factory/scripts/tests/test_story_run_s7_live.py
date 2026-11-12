#!/usr/bin/env python3
"""The driver's S7 over the REAL controller (t-698 §18.8, §22 FX-5; the live worlds of `test_story_run_s7.py`, which keeps the unit pins).

Every world here is `Driver.run()` over the real controller CLI in a temp project, the real `story_step`, `finalize_task` and `stage_done`; only
`run_claude` is stubbed (an empty session id skips `bind`). A "process" is a NEW `Driver` in the SAME Python process (class-level patches and
module caches persist), the scripts are real subprocesses. The world runs with `handoffs.required: false` and deletes the handover form, so the
exit gate's triage binding is NOT exercised: this is the LEGACY road, on which nothing but the driver bounds a re-triage.

The file is in SLOW_TESTS (package-full only) and has a 600 s ceiling in selftest.TEST_TIMEOUTS (t-2197).

  * T-L1  two processes: the Person at the cap, `--answer round`, S7 closed by code, `next` is S8 (+ T-L2 a rerun re-asks, T-L4 `stop` is held);
  * T-L3  `debt` -> the other row is repaired -> the close; the debt names the LEDGER's ref (+ T-S4 the order of the close);
  * P2    (t-831 F1) a row below its cap is repaired and the repair round REWRITES the manifest; the next process (`--answer round`) neither
          repairs that row again nor asks the other row's question again: the row's identity within a life is its triage row's own name,
          the ledger refs are frozen per (life, row);
  * FX-3  (t-831 F3) a failure the analyst's triage never binds: ONE re-triage, then the seam asks the person - never a third analyst;
  * FX-2  (t-831 F2, §22/§23) `decide --open` recorded while the analyst runs: the rounds run, then ONE closed question (`s7.open_work`);
          unanswered it is asked again, `stop` is held, `close` closes S7 by code (`decide --close` is no door: it refuses an accepted dispatch).
"""
import contextlib
import io
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import PLUGIN_ROOT, check, check_eq, check_in, finish  # noqa: E402
from story_run_common import driver_for  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

TASK = "QA-9"


def stamp(task_root: Path) -> dict:
    """The sha256 of the two files a close must not change between the receipt and the end. The run report is NOT in it (t-698 §21 M-6): the
    controller's refresh rewrites its `controller_revision` after every committed event, before and after this node alike."""
    import hashlib
    return {name: (hashlib.sha256((task_root / "work" / name).read_bytes()).hexdigest() if (task_root / "work" / name).is_file() else None)
            for name in ("triage.json", "review-debts.json")}


class Live7:
    """The world: the REAL controller CLI, the real `story_step`, the real exit gate and `finalize_task`, and `Driver.run()` as the entry of
    every process; only `run_claude` is stubbed (the analyst's stub writes triage.json with two TEST_BUG rows and its digest; the automator's
    stub writes the manifest the exit gate asks for - it holds NO test, so the repair round REWRITES the manifest - and a green digest). Two
    cases, cap 2; `seeded` rework rounds of `seed_case` are already counted by the controller, so that case is AT the cap and the other at 0.
    Every process is a NEW Driver over the same task root on disk: nothing is carried in memory between two of them. `bound`: the manifest
    holds the two tests, so the ledger binds the rows."""

    def __init__(self, bound=False, seeded=2, seed_case="TC-1", open_decision=False, scribe=True):
        import datetime
        import test_controller_rework_scope as SCOPED
        import test_controller_state as BASE
        import test_fixes_13797 as F
        import story_run
        from controller import Controller
        self.SR, self.bound, self.open_decision, self.decided = story_run, bound, open_decision, (None, "")
        self.scribe = scribe        # X7-6c: S7 closes only over the consumer's (scribe's) accept record; True = the scribe accepts each triage at once
        self.root = harness.temp_project("qa-s7-live-")
        harness.use_project(self.root)
        self.task_root = self.root / "qa-factory" / "artifacts" / TASK
        self.work = self.task_root / "work"
        self.work.mkdir(parents=True)
        config = self.root / "qa-factory" / "config.json"
        cfg = json.loads(config.read_text(encoding="utf-8"))
        cfg["handoffs"] = {"required": False}
        config.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        (self.task_root / "pipeline.json").write_text(json.dumps({"ticket": TASK, "size": "S", "environment": "local",
                                                                  "stages": {"S0": {"status": "pending"}}, "gates": {}, "halts": []}), encoding="utf-8")
        (self.work / "ticket-freshness.json").write_text(json.dumps({"checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                                                                     "result": "none"}), encoding="utf-8")
        self.env = dict(os.environ, CLAUDE_PROJECT_DIR=str(self.root))
        for key in ("STORY_RUN_CLAUDE", "STUB_CONTROL", "STUB_LOG"):
            self.env.setdefault(key, str(self.root / "unused"))
        cases = ("TC-1", "TC-2")
        self.c = Controller(self.task_root)
        self.c.apply("initialize", {"scope": list(cases), "source_revision": "src-1", "known_paths": {"root": str(self.task_root), "project_root": str(self.root)},
                                    "idempotency_key": "init", "coverage_contract_version": 2, "plan_contract_mode": "new"})
        for n in range(5):
            BASE.accept_stage(self.c, self.task_root, f"S{n}")
        BASE.seed_plan(self.task_root, [SCOPED.plan_row(i, "automate") for i in range(1, 3)])
        (self.task_root / "state" / "story-case-links.json").write_text(json.dumps({"links": [{"case_id": case, "version": f"cv_{i}"}
                                                                                              for i, case in enumerate(cases, 1)]}), encoding="utf-8")
        decision = {"id": "gate-a", "gate": "A", "action": "approve", "status": "approved", "authorization_source": "human", "source_revision": "src-1",
                    "scope": list(cases), "input_revision": "src-1", "idempotency_key": "gate-a"}
        self.c.apply("decision", BASE.bind_gate_a(self.task_root, decision))
        BASE.accept_stage(self.c, self.task_root, "S5")
        self.setup_error = F.runner(self.c, self.task_root, "S6-qa-runner-1", "automation", list(cases), True)
        tests = [{"file": "tests/test_a.py", "test_function": f"test_{i}", "case": case} for i, case in enumerate(cases)] if bound else []
        witness = "evidence/repair-20261015T160000.json exit 0, 1 passed, 0 failed"
        # story_step finish re-runs the S5 exit gate (GW1-8): the SEEDING manifest carries a run_witness of the stub's form and lists no
        # test (a listed test needs a run block, which this fixture has not written), or finish refuses; the bound manifest is written after
        self.work.joinpath("automation-manifest.json").write_text(json.dumps({"tests": [], "unresolved": [], "run_witness": witness}), encoding="utf-8")
        key = "test_id" if bound else "test"
        results = [{key: f"tests/test_a.py::test_{i}", "status": "failed", "case": case, "reason": "boom"} for i, case in enumerate(cases)]
        self.work.joinpath("run-report.json").write_text(json.dumps({
            "execution_status": "failed", "current_totals": {"failed": len(results), "passed": 0}, "current_results": results}), encoding="utf-8")
        for _n in range(seeded):                 # the controller's own count of `seed_case`'s window: `seeded` accepted repair rounds
            code, out = self.ctl("--operation", "rework", "--stage", "S5", "--role", "qa-automator", "--reason", "seed round", "--purpose", "repair_verify",
                                 "--cause", "test_defect", "--cases", seed_case)
            rid = json.loads(out.splitlines()[-1])["request"]["id"]
            finish_code, finish_out = self.step("finish", "--task", TASK, "--dispatch-id", rid, "--digest", "qa-automator S5 QA-9 · fixed",
                                                "--ignore-handoff", "--not-complete")
            assert finish_code == 0, f"the seeding finish of {rid} was refused (exit {finish_code}): {finish_out[:1600]}"
        self.work.joinpath("automation-manifest.json").write_text(json.dumps({"tests": tests, "unresolved": [], "run_witness": witness}), encoding="utf-8")
        self.before = set(self.state()["dispatches"])
        self.claude_log, self.events, self.answers = [], [], 0
        self.saved = {name: getattr(story_run.Driver, name) for name in ("run_claude", "py", "code_only", "s7_await_scribe")}
        live, real_py, real_code_only, real_await = self, self.saved["py"], self.saved["code_only"], self.saved["s7_await_scribe"]

        def await_scribe(d, person_words=""):
            """X7-6c: the repairs ended and S7 would await the scribe; the stub scribe has judged the analyst's LAST triage `accept` (its record,
            written the way `stage_done.py --acceptance` writes it), so the close by code goes on. `scribe=False`: nobody judges it."""
            if live.scribe:
                import acceptance
                author = acceptance.stage_author_dispatch(live.state(), acceptance.stage_def_of("S7"))
                pipeline_path = live.task_root / "pipeline.json"
                pipeline = json.loads(pipeline_path.read_text(encoding="utf-8"))
                if author and not acceptance.accepted_for(pipeline, "S7", author):
                    pipeline.setdefault("acceptance", {})["S7"] = [{"stage": "S7", "role": "qa-failure-analyst", "acceptor": "qa-doc-scribe",
                                                                    "reviewed_dispatch": author, "verdict": "accept", "failure_class": None, "quote": "",
                                                                    "witness_paths": [], "at": "t"}]
                    pipeline_path.write_text(json.dumps(pipeline), encoding="utf-8")
            return real_await(d, person_words)

        def py(d, script, *args, **kw):
            if script == "finalize_task.py" or (script == "stage_done.py" and "S7" in args):
                live.events.append((script, stamp(live.task_root)))
            return real_py(d, script, *args, **kw)

        def code_only(d, stage, reason, evidence):
            live.events.append(("code_only", stamp(live.task_root)))
            real_code_only(d, stage, reason, evidence)
            if stage == "S7":
                live.receipt = dict((live.state().get("stages") or {}).get("S7") or {})
        story_run.Driver.run_claude = lambda d, kind, prompt, **kw: live.claude(prompt, **kw)
        story_run.Driver.py, story_run.Driver.code_only = py, code_only
        story_run.Driver.s7_await_scribe = await_scribe
        self.receipt = {}

    def state(self) -> dict:
        from controller import Controller
        return Controller(self.task_root).state()

    def run_cli(self, script, *args):
        import subprocess
        done = subprocess.run([sys.executable, "-B", str(PLUGIN_ROOT / "scripts" / script), *args], capture_output=True, text=True, encoding="utf-8",
                              cwd=str(self.root), env=self.env)
        return done.returncode, (done.stdout + done.stderr).strip()

    def step(self, *args):
        return self.run_cli("story_step.py", *args)

    def ctl(self, *args):
        return self.run_cli("controller.py", "--task-root", str(self.task_root), *args)

    def claude(self, prompt, *, role="", dispatch="", stage="", **kw):
        self.claude_log.append((role, dispatch, re.search(r"Dispatch scope[^:]*: (\S+)", prompt).group(1) if "Dispatch scope" in prompt else ""))
        (self.work / "handoffs" / f"{dispatch}.yaml").unlink(missing_ok=True)       # the handover form is not this pin's subject (config: not required)
        if role == "qa-failure-analyst":
            if self.open_decision:      # the person's `decide --open` while the analyst RUNS (an accepted dispatch refuses it)
                words = self.task_root / "state" / "open-words.txt"
                words.write_text("keep it open: the export check is still to be run by hand", encoding="utf-8")
                self.decided = self.step("decide", "--task", TASK, "--dispatch-id", dispatch, "--words-file", str(words), "--open")
            rows = [{"test": f"tests/test_a.py::test_{i}", "case": case, "verdict": "TEST_BUG", "evidence": "evidence/runs/x.json", "fix_result": ""}
                    for i, case in enumerate(("TC-1", "TC-2"))]
            self.work.joinpath("triage.json").write_text(json.dumps({"triage": rows}), encoding="utf-8")
            text = f"qa-failure-analyst S7 {TASK} · ok\nTC-1 · TEST_BUG · the test is wrong\nTC-2 · TEST_BUG · the test is wrong\nwork/triage.json"
        else:
            case = re.search(r"Dispatch scope[^:]*: (\S+)", prompt).group(1)
            # the author's exit gate asks for a run witness and for run blocks of any listed test: the stub's manifest lists none (the rows were bound
            # to the ledger's refs when the questions were built, before this write) - so the round REWRITES the manifest (P2)
            made = {"tests": [], "unresolved": [], "run_witness": "evidence/repair-20261015T160000.json exit 0, 1 passed, 0 failed"}
            self.work.joinpath("automation-manifest.json").write_text(json.dumps(made), encoding="utf-8")
            text = f"qa-automator S5 {TASK} · ok\n{case} · green · fixed\nwork/x.md"
        return {"is_error": False, "result": text, "session_id": "", "exit_code": 0, "stderr": ""}

    def process(self, words=None, boundaries=3):
        """One `story_run` process: a NEW Driver, the entry `run()`. Returns (its exit code or the exception that escaped, what it printed)."""
        kw = {}
        if words is not None:
            self.answers += 1
            path = self.task_root / "state" / f"answer-{self.answers}.txt"
            path.write_text(words, encoding="utf-8")
            kw["answer"] = str(path)
        driver = driver_for(self.root, self.env, TASK, max_boundaries=boundaries, **kw)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                code = driver.run()
            except BaseException as exc:      # a crash is a FAIL line of the pin, not the end of the file
                code = repr(exc)
        return code, out.getvalue()

    def add_failure(self, test: str) -> None:
        """A failure the analyst's stub never names joins the run report while S7 is open (what a person-word rework of an earlier stage does,
        t-831 P3): no row of the triage can bind it, however often the analyst is asked."""
        path = self.work / "run-report.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        report["current_results"].append({"test": test, "status": "failed", "case": "TC-2", "reason": "boom"})
        report["current_totals"]["failed"] += 1
        path.write_text(json.dumps(report), encoding="utf-8")

    def driver_state(self) -> dict:
        return json.loads((self.task_root / "state" / "driver-state.json").read_text(encoding="utf-8"))

    def asked(self):
        return self.driver_state().get("repair_ask") or {}

    def question(self) -> dict:
        """The question the driver has open (`asked` of the driver state): kind, stage, dispatch."""
        return self.driver_state().get("asked") or {}

    def new_rounds(self) -> list:
        return sorted(d for d in set(self.state()["dispatches"]) - self.before if d.startswith("S5-qa-automator"))

    def analysts(self) -> list:
        return [c[1] for c in self.claude_log if c[0] == "qa-failure-analyst"]

    def next_action(self) -> str:
        code, out = self.step("where", "--task", TASK)
        found = re.search(r"^next: (\{.*\})", out, re.M)
        return (json.loads(found.group(1)).get("stage") or json.loads(found.group(1)).get("action")) if found else out[-200:]

    def s7(self) -> dict:
        return dict((self.state().get("stages") or {}).get("S7") or {})

    def done(self):
        for name, value in self.saved.items():
            setattr(self.SR.Driver, name, value)
        harness.cleanup(self.root)


def tl1_live_two_processes() -> None:
    """T-L1 LIVE (+ T-L2, T-L4): `Driver.run()` over the real controller. Process 1: the analyst triages two TEST_BUG rows, its finish leaves S7 open,
    row 1 is AT the cap, so the Person `repair_limit` S7 comes. A rerun with no answer asks the SAME question and never reaches S8 (T-L2); `stop` is
    held and the next rerun asks again (T-L4); then `--answer round` (process N): the S5 rework is dispatched EXACTLY once for row 1, row 2 gets its
    round, `finalize_task` runs once, S7 is `completed` and `next` is S8. MU1 (the S7 branch of `completion_for` removed) closes S7 at the analyst's
    finish: process 1 reaches S8 and never asks."""
    live = Live7()
    SR = live.SR
    try:
        check_eq("T-L1 setup: the S6 runner was accepted", live.setup_error, "")
        check_eq("T-L1 setup: the controller counts 2 rounds of TC-1 (so row 1 is at the cap) and none were made by the driver",
                 (len([d for d in live.before if d.startswith("S5-qa-automator")]), live.claude_log), (2, []))
        code, out = live.process()
        ask = live.asked()
        check_eq("T-L1 process 1: the driver ends with the Person (exit 3), asking the S7 repair limit",
                 (code, ask.get("stage"), ask.get("key"), ask.get("offer")), (SR.EXIT_PERSON, "S7", "s7.repair_limit", ["round", "debt", "stop"]))
        check_eq("T-L1 process 1: the analyst ran once, no repair round was dispatched, no finalize",
                 ([c[0] for c in live.claude_log], live.new_rounds(), [e for e in live.events if e[0] == "finalize_task.py"]), (["qa-failure-analyst"], [], []))
        check_eq("T-L1 process 1: S7 is still PENDING (open) and the controller's next step is S7 again, never S8",
                 (live.s7().get("status"), live.next_action()), ("pending", "S7"))
        # T-L2: a rerun with no answer re-raises the same question
        code, out = live.process()
        check_eq("T-L2: a rerun with no answer asks the SAME question again and runs nothing",
                 (code, live.asked().get("dispatch") == ask.get("dispatch"), [c[0] for c in live.claude_log], live.new_rounds(), live.s7().get("status")),
                 (SR.EXIT_PERSON, True, ["qa-failure-analyst"], [], "pending"))
        check_eq("T-L2: and never enters S8", live.next_action(), "S7")
        # T-L4: `stop` is held (the question comes back changed), nothing is recorded, a rerun asks again
        code, out = live.process("stop")
        check_eq("T-L4: `stop` is held: exit 3, no round, S7 open, nothing recorded for the slot",
                 (code, live.new_rounds(), live.s7().get("status"), live.driver_state().get("repair_limit_s7")),
                 (SR.EXIT_PERSON, [], "pending", None))
        code, out = live.process()
        check_eq("T-L4: a rerun after `stop` asks again, with `round` among the answers", (code, live.asked().get("offer")), (SR.EXIT_PERSON, ["round", "debt", "stop"]))
        # T-L1: the person's `round`
        before = len([e for e in live.events if e[0] == "finalize_task.py"])
        code, out = live.process("round", boundaries=1)
        rounds = live.new_rounds()
        check_eq("T-L1 process N: the S5 rework is dispatched EXACTLY once per row (row 1 on its answer, row 2 below its cap) and nowhere else",
                 (code, len(rounds), [c for c in live.claude_log if c[0] == "qa-automator"]),
                 (SR.EXIT_DONE, 2, [("qa-automator", rounds[0], "TC-1"), ("qa-automator", rounds[1], "TC-2")] if len(rounds) == 2 else []))
        check_eq("T-L1 process N: finalize_task ran ONCE for the close", len([e for e in live.events if e[0] == "finalize_task.py"]) - before, 1)
        check_eq("T-L1 process N: the code_only receipt of S7 was written (status completed, code_only true at the receipt)",
                 (live.receipt.get("status"), live.receipt.get("code_only")), ("completed", True))
        final = live.s7()
        check_eq("T-L1 process N: S7 is completed by the stage_done record, which carries the repairs' words (stage_done REWRITES the entry: "
                 "the `code_only` flag is gone from it - observed, t-829 hand-back W2)",
                 (final.get("status"), "repairs: fixed=2 not_fixed=0 stopped=0" in str(final.get("reason"))), ("completed", True))
        check_eq("T-L1 process N: `next` is S8, and no question is left open", (live.next_action(), live.asked()), ("S8", {}))
    finally:
        live.done()


def tl3_ts4_live_debt_and_the_order_of_the_close() -> None:
    """T-L3 (LIVE, bound manifest): `debt` on row 1 -> row 2 is repaired -> S7 closes; the debt is in review-debts.json under the LEDGER's ref of the
    test (not the triage row's own nodeid). T-S4: the order is finalize_task -> code_only -> stage_done, and the hashes of triage.json and
    review-debts.json at the receipt equal those after stage_done (the run report's `controller_revision` stamp is outside the equality, §21 M-6).
    MU6 (finalize after the receipt) is killed here and by T-S5 E6 (test_story_run_s7.py)."""
    live = Live7(bound=True)
    SR = live.SR
    try:
        code, out = live.process()
        check_eq("T-L3: process 1 asks the repair limit of row 1", (code, live.asked().get("stage")), (SR.EXIT_PERSON, "S7"))
        import ledger
        asked_tests = list(live.asked().get("tests") or [])
        code, out = live.process("debt", boundaries=1)
        rounds = live.new_rounds()
        check_eq("T-L3: `debt` ends row 1 with no round; row 2 is repaired (ONE round, on TC-2); S7 completes",
                 (code, [c[2] for c in live.claude_log if c[0] == "qa-automator"], len(rounds), live.s7().get("status"), live.next_action()),
                 (SR.EXIT_DONE, ["TC-2"], 1, "completed", "S8"))
        windows = ledger.read_review_debts(live.task_root)["windows"]
        check_eq("T-L3: the debt is recorded once, for S7 and TC-1, under the ledger's ref of the test (the question named the same)",
                 ([(w["stage"], w["cases"], w["tests"]) for w in windows], asked_tests), ([("S7", ["TC-1"], ["test_0"])], ["test_0"]))
        names = [e[0] for e in live.events]
        check_eq("T-S4: the order is finalize_task, then the code_only receipt, then stage_done for S7", names, ["finalize_task.py", "code_only", "stage_done.py"])
        receipt, last = (live.events[1][1] if len(live.events) > 1 else {}), stamp(live.task_root)
        check_eq("T-S4: triage.json and review-debts.json hold the same bytes at the receipt and after stage_done "
                 "(the run report is outside: its controller_revision stamp is rewritten after every event, §21 M-6)", receipt, last)
        check("T-S4: the debt file existed at the receipt (the equality is not over two absent files)", receipt.get("review-debts.json") is not None)
    finally:
        live.done()


def p2_the_row_key_survives_the_manifest_the_round_rewrites() -> None:
    """P2 (t-831 F1, §22 FX-1): TC-1 is BELOW the cap and TC-2 AT it. Process 1 repairs TC-1 (its round rewrites `automation-manifest.json`, so
    the ledger refs of the rows are not what they were) and asks TC-2's question. Process 2 (`--answer round`) must NOT repair TC-1 a second
    time, must NOT ask TC-2 again, and runs TC-2's round: the identity of a row within a life is its triage row's own name, and the ledger refs
    are frozen per (life, row) at their first computation (frozen wins; the report reads the frozen list). MU-FX1 (the key rebuilt from the
    manifest) is killed here: TC-1 is rounded twice and TC-2 is asked again."""
    live = Live7(bound=True, seed_case="TC-2")
    SR = live.SR
    try:
        code, out = live.process()
        ask = live.asked()
        rounds = live.new_rounds()
        check_eq("P2 process 1: TC-1 (below its cap) is repaired by ONE round, then TC-2 (at its cap) is asked",
                 (code, len(rounds), [c[2] for c in live.claude_log if c[0] == "qa-automator"], ask.get("cases")), (SR.EXIT_PERSON, 1, ["TC-1"], ["TC-2"]))
        check_eq("P2 process 1: the question is keyed by the triage row's own name, and the ledger ref was read BEFORE the round rewrote the manifest",
                 (ask.get("ident"), ask.get("tests")), ("tests/test_a.py::test_1", ["test_1"]))
        manifest = json.loads(live.work.joinpath("automation-manifest.json").read_text(encoding="utf-8"))
        check_eq("P2 setup: the repair round DID rewrite the manifest (it holds no test now, so a ledger read would be another list)", manifest.get("tests"), [])
        code, out = live.process("round", boundaries=1)
        rounds = live.new_rounds()
        check_eq("P2 process 2 (`--answer round`): TC-1 is NOT repaired again, TC-2's round runs, nothing is asked again, S7 closes",
                 (code, [c[2] for c in live.claude_log if c[0] == "qa-automator"], len(rounds), live.asked(), live.s7().get("status"), live.next_action()),
                 (SR.EXIT_DONE, ["TC-1", "TC-2"], 2, {}, "completed", "S8"))
        kept = (live.driver_state().get("s7_rows") or {})
        life = next(iter(kept), "")
        check_eq("P2: the rows are keyed by the triage rows' own names and hold their FROZEN refs (TC-1's ledger ref survives the rewritten manifest)",
                 ({ident: (rec.get("tests"), rec.get("outcome")) for ident, rec in (kept.get(life) or {}).items()}),
                 {"tests/test_a.py::test_0": (["test_0"], "repaired"), "tests/test_a.py::test_1": (["test_1"], "repaired")})
    finally:
        live.done()


def fx3_a_second_not_fresh_triage_asks_the_person() -> None:
    """FX-3 (t-831 F3, §22): the legacy road (the handover form is off, nothing checks the analyst's binding). Process 1: S7 is open and waits for
    the person (row 1 is at its cap). Then a failure joins the run report that no triage row can bind. Process 2: the accepted analyst is not
    fresh, so the analyst is paid ONCE more (a new life, the question asked again). Process 3: that triage is still not fresh - the SECOND
    consecutive one - and the seam asks the person, naming the failure, instead of paying a third analyst; a rerun asks again at no cost.
    MU-FX3 (the bound removed) is killed here: a third analyst is dispatched."""
    live = Live7()
    SR = live.SR
    try:
        code, out = live.process()
        check_eq("FX-3 process 1: one analyst, and S7 waits on the person's repair-limit answer", (code, live.analysts(), live.s7().get("status")),
                 (SR.EXIT_PERSON, ["S7-qa-failure-analyst-1"], "pending"))
        live.add_failure("tests/test_a.py::test_extra")
        code, out = live.process()
        check_eq("FX-3 process 2: the accepted analyst is not fresh: ONE re-triage (a second analyst), recorded as started from the first",
                 (code, live.analysts(), (live.driver_state().get("s7_retriage") or {}).get("from")),
                 (SR.EXIT_PERSON, ["S7-qa-failure-analyst-1", "S7-qa-failure-analyst-2"], "S7-qa-failure-analyst-1"))
        code, out = live.process()
        check_eq("FX-3 process 3: the second consecutive not-fresh triage pays NO third analyst, and the Person is asked (exit 3)",
                 (code, live.analysts()), (SR.EXIT_PERSON, ["S7-qa-failure-analyst-1", "S7-qa-failure-analyst-2"]))
        check_in("FX-3 process 3: the question names the failure no row answers", "tests/test_a.py::test_extra", out)
        check_in("FX-3 process 3: and offers the seam's own words, `go on` and `stop`", "`go on`", out)
        check_eq("FX-3: S7 stays OPEN (no receipt, no stage_done) and no repair round was paid for the new life",
                 (live.s7().get("status"), [e[0] for e in live.events if e[0] in ("code_only", "stage_done.py")], live.new_rounds()),
                 ("pending", [], []))
        code, out = live.process()
        check_eq("FX-3: a rerun asks the same question again and pays nothing: still two analysts", (code, live.analysts()),
                 (SR.EXIT_PERSON, ["S7-qa-failure-analyst-1", "S7-qa-failure-analyst-2"]))
        check_in("FX-3: ...and it is the same question", "tests/test_a.py::test_extra", out)
    finally:
        live.done()


def fx2_the_open_work_question_live() -> None:
    """FX-2 (t-831 F2, §22 decided (a), §23): the person's `decide --open` is recorded WHILE the analyst runs (the real `story_step decide`). The
    analyst's finish leaves S7 open, both rows are below their cap so the rounds run, and when every row has ended the driver asks ONE closed
    question (kind `open_work`, no paid call): S7 stays PENDING and `next` stays S7, never S8. A rerun with no answer asks it again and runs
    nothing; `stop` is held and a rerun asks again; `close` closes S7 by code (finalize, the receipt, stage_done; `next` is S8) and runs no
    further round. `decide --close` on the accepted analyst is shown to refuse (the door the old text named). MU-FX2 (the closed question removed:
    the old print-and-return) is killed here: process 1 returns with S7 open and nothing asked."""
    live = Live7(seeded=0, open_decision=True, scribe=False)       # the person's `close` is the pass here, not the scribe's record
    SR = live.SR
    try:
        code, out = live.process()
        check_eq("FX-2 process 1: the analyst ran once and its `decide --open` was recorded (exit 0) while it ran",
                 (live.analysts(), live.decided[0]), (["S7-qa-failure-analyst-1"], 0))
        asked = live.question()
        check_eq("FX-2 process 1: both rows were repaired (two rounds), then the Person is asked the `open_work` question (exit 3) about the analyst's life",
                 (code, len(live.new_rounds()), asked.get("kind"), asked.get("stage"), asked.get("dispatch")),
                 (SR.EXIT_PERSON, 2, "open_work", "S7", "S7-qa-failure-analyst-1"))
        check_in("FX-2 process 1: the question quotes the person's own words and offers `close` and `stop`", "the export check is still to be run by hand", out)
        check_eq("FX-2 process 1: S7 is still PENDING, `next` is S7 (never S8), and nothing was finalized or closed",
                 (live.s7().get("status"), live.next_action(), [e[0] for e in live.events if e[0] in ("finalize_task.py", "code_only", "stage_done.py")]),
                 ("pending", "S7", []))
        refused = live.step("decide", "--task", TASK, "--dispatch-id", "S7-qa-failure-analyst-1", "--words-file",
                            str(live.task_root / "state" / "open-words.txt"), "--close")
        check("FX-2: `decide --close` on the accepted analyst REFUSES (so it is not the door the question may name)",
              refused[0] == 2 and "is accepted" in refused[1], refused)
        code, out = live.process()
        check_eq("FX-2: a rerun with no answer asks the SAME question again and runs nothing (no analyst, no round, S7 pending)",
                 (code, live.question().get("kind"), live.analysts(), len(live.new_rounds()), live.s7().get("status")),
                 (SR.EXIT_PERSON, "open_work", ["S7-qa-failure-analyst-1"], 2, "pending"))
        code, out = live.process("stop")
        check_eq("FX-2: `stop` is held: exit 3, S7 open, nothing closed, nothing run",
                 (code, live.s7().get("status"), len(live.new_rounds()), [e[0] for e in live.events if e[0] == "code_only"]), (SR.EXIT_PERSON, "pending", 2, []))
        check_in("FX-2: ...and the held question says how to go on after all", "answer `close`", out)
        code, out = live.process()
        check_eq("FX-2: a rerun after `stop` asks again", (code, live.question().get("kind"), live.s7().get("status")), (SR.EXIT_PERSON, "open_work", "pending"))
        before = len([e for e in live.events if e[0] == "finalize_task.py"])
        code, out = live.process("close", boundaries=1)
        check_eq("FX-2: `close` -> S7 is closed by code: finalize ONCE, the receipt (code_only true at the receipt), then completed with the repairs' words",
                 (code, len([e for e in live.events if e[0] == "finalize_task.py"]) - before, live.receipt.get("code_only"), live.s7().get("status"),
                  "repairs: fixed=2 not_fixed=0 stopped=0" in str(live.s7().get("reason"))), (SR.EXIT_DONE, 1, True, "completed", True))
        # X7-6c (M3): the person's `close` is recorded FIRST as the driver's accept (`stage_done.py --acceptor driver`, by: person), then the close by code
        check_eq("FX-2: the order is the person's pass recorded (stage_done), finalize_task, the code_only receipt, stage_done; no further round was paid; `next` is S8 and no question is open",
                 ([e[0] for e in live.events], len(live.new_rounds()), live.next_action(), live.question()),
                 (["stage_done.py", "finalize_task.py", "code_only", "stage_done.py"], 2, "S8", {}))
    finally:
        live.done()


def main() -> None:
    tl1_live_two_processes()
    tl3_ts4_live_debt_and_the_order_of_the_close()
    p2_the_row_key_survives_the_manifest_the_round_rewrites()
    fx3_a_second_not_fresh_triage_asks_the_person()
    fx2_the_open_work_question_live()
    finish("story run s7 live")


if __name__ == "__main__":
    main()
