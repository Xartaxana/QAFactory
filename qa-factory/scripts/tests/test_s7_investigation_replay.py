#!/usr/bin/env python3
"""The replay of the REAL TP1-14857 S7 road through the REAL driver and controller (P2 wave 5; t-087 section 4, t-108 section 5).

The fixture `fixtures/investigation-14857/` is a copy of the story folder of the run that left eight observations open. The
test copies it into a temp project, replays events 1..103 through the controller (the S7 analyst DISPATCHED and still running),
and only THEN writes `work/triage.json` (the 7 rows) and the analyst's saved result. From there the road is the driver's own:

  `where` -> `wait_existing_job` -> `_finish_saved_result` -> the form check -> `finish` -> `s7_open_work` -> `decision` `dispatch` ->
  `OpenWork("investigation_pending")` (D1 accepted, S7 open, the controller's refresh archives the 7 rows) -> `where` -> `prepare_stage S7`
  -> `stage_S7` -> `s7_repairs` -> `s7_close` -> the gate -> `project` (8 lines) -> ONE `run_role` (D2) -> `close_gaps` -> `close_by_code`.

Only `run_claude` is stubbed, and only D2 reaches it: the stub IS the investigating role - inside the call it writes the seed of the
real run's follow-up (FB-13) through the real CLIs (`exploratory_findings.py`, `investigation_probe.py`, `handoff_check.py`), then returns
the role's final message. The LLM is the stub; the CLIs, the controller, the gate and the register writer are real. No network.

  R-1  the build: the copy holds the run's blocks, handoffs, requests, evidence, cases, sources, inventory and blobs - not the run
       report, not the archive; the replay of 103 events; the prefix carries no S7 `code_only`
  R-2  D1 (the saved result of the real analyst): no controller event between the triage write and the form check (the spy), then the
       accept is the first event; the archive appears, `triage: []`, `s7_fresh()` True, the register absent
  R-3  the re-entry and the gate: 8 code lines, ONE dispatch with the targets whole in its lines, the order project -> run_role ->
       close_gaps -> close (K-M3-22), no repair round, the triage file untouched across the stub (the mtime window)
  R-4  the register after the close: one active line per target, the withdrawn chain, the gaps, the close reason with n = k + g
  R-5  the readers: the report block, the gate lines above "Bugs found - none", `facts["bugs"]` empty, `refresh` leaves the register alone
  R-6  the triage set (archive-aware) equals the 7 rows; K-M3-23 on the rebuilt rows (the evidence judge, with the file and without it)
"""
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
import synthetic_corpus  # noqa: E402
import harness  # noqa: E402
from harness import PLUGIN_ROOT, check, check_eq, check_in, finish  # noqa: E402
import story_run_common  # noqa: E402
from story_run_common import driver_for  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import contract as CT  # noqa: E402
import controller as CTL  # noqa: E402
import exploratory_findings  # noqa: E402
import investigation  # noqa: E402
import story_run  # noqa: E402

TASK = "TP1-14857"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "investigation-14857" / TASK
SCRIPTS = PLUGIN_ROOT / "scripts"
D1, D2 = "S7-qa-failure-analyst-1", "S7-qa-failure-analyst-2"
REGISTER = "work/exploratory-findings.jsonl"
DOT = "·"
WHY_END = "not investigated - " + investigation.WHY_TEXTS[1]
# What the copy leaves out (t-087 section 4, M-a / m-g): the run report is rebuilt by `refresh` from the blocks (the real one), the triage
# is written AFTER the replay (a triage present during it would be archived by the replay itself), no archive exists yet.
LEFT_OUT = {Path("work/run-report.json"), Path("work/triage.json"), Path("state/migration")}
SEED_EVIDENCE = "work/evidence/followup/stale-repro.jsonl"


def lines_of(path: Path) -> int:
    return len(path.read_bytes().splitlines()) if path.is_file() else 0


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def ignore_left_out(source: Path):
    def ignore(directory, names):
        relative = Path(directory).relative_to(source)
        return [name for name in names if relative / name in LEFT_OUT]
    return ignore


def digest_of_d1(task_root: Path) -> str:
    """The analyst's final message, rebuilt from its handover form (A holds no `state/driver-runs/`): one line per scope item (the dispatch
    scope was TC-001..TC-012; the real run's five green checks have no row in the form, the seven others are the `not_for_repair` rows)."""
    text = (task_root / "work" / "handoffs" / f"{D1}.yaml").read_text(encoding="utf-8")
    header = {key: re.search(rf"^  {key}: (.+)$", text, re.M).group(1).strip() for key in ("role", "stage", "window", "verdict")}
    out = [f"{header['role']} {header['stage']} {header['window']} {DOT} {header['verdict']}"]
    out += [f"TC-{n:03d} {DOT} passed {DOT} green in the current run" for n in range(1, 6)]
    rows = re.findall(r'^  - id: (\S+)\n    verdict: (\S+)\n    where_it_went: "(.*)"$', text.split("\nnot_for_repair:")[1], re.M)
    out += [f"{ident} {DOT} {verdict} {DOT} {went}"[:150] for ident, verdict, went in rows]
    return "\n".join(out + ["work/triage.json"]), len(rows)


class Replay:
    def __init__(self):
        self.root = harness.temp_project("qa-s7-replay-")
        harness.use_project(self.root)
        self.task_root = self.root / "qa-factory" / "artifacts" / TASK
        self.extra_roots = []
        self.env = dict(os.environ, CLAUDE_PROJECT_DIR=str(self.root))
        for key in ("STORY_RUN_CLAUDE", "STUB_CONTROL", "STUB_LOG"):
            self.env.setdefault(key, str(self.root / "unused"))
        self.saved = {name: getattr(story_run.Driver, name) for name in ("run_claude", "form_errors", "run_role", "close_by_code", "s7_repairs", "s7_close", "s7_await_scribe")}
        self.saved_inv = {name: getattr(investigation, name) for name in ("project", "close_gaps")}
        self.claude_calls, self.order, self.stub = [], [], {}
        self.driver = None

    def cli(self, script, *args, stdin=None):
        done = subprocess.run([sys.executable, "-B", str(SCRIPTS / script), *args], capture_output=True, text=True, encoding="utf-8",
                              cwd=str(self.root), env=self.env, input=stdin)
        return done.returncode, (done.stdout + done.stderr).strip()

    def events(self) -> Path:
        return self.task_root / "state" / "events.jsonl"

    def state(self) -> dict:
        return CTL.Controller(self.task_root).state()

    def drive(self, action) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.driver.dispatch_action(action)
        return out.getvalue()

    def done(self):
        for name, value in self.saved.items():
            setattr(story_run.Driver, name, value)
        for name, value in self.saved_inv.items():
            setattr(investigation, name, value)
        for root in [self.root, *self.extra_roots]:
            harness.cleanup(root)

    # ---------------------------------------------------------------- the stub (D2): the role's work, through the real CLIs
    def seed(self, dispatch: str) -> list:
        """The FB-13 seed as the investigating role writes it. Returns the refusals (an empty list = every call accepted)."""
        refused = []

        def call(script, *args):
            code, out = self.cli(script, *args)
            if code:
                refused.append(f"{script} {args[0]} (exit {code}): {out[-300:]}")
            return out

        base = ("--task-root", str(self.task_root), "--by", dispatch)
        listing = json.loads(call("exploratory_findings.py", "list", "--task-root", str(self.task_root)))
        by_target = {(line.get("origin") or {}).get("target"): line["id"] for line in listing["active"]}

        def add(kind, title, statement, *extra):
            call("exploratory_findings.py", "add", *base, "--kind", kind, "--title", title, "--statement", statement, "--why-not-a-bug",
                 "what the product did is recorded as seen; the expectation is not confirmed", "--evidence", SEED_EVIDENCE, *extra)

        add("unresolved_question", "EX-1 a failed reindex wipes the index", "after a failed full reindex the index answered with no documents",
            "--question", "is the index meant to be emptied by a failed reindex?", "--owner-role", "product owner")
        add("observation", "EX-2 stale text after recovery", "the text stayed stale after recovery in 5/5 repeats read from the follow-up file")
        add("observation", "EX-3 Incremental but a full rebuild", "the update mode called Incremental rebuilt the whole index",
            "--oracle-status", "documented_text_only")
        add("unresolved_question", "EX-4 the FAQ and the SDK disagree on the flags", "the FAQ and the SDK name different flags",
            "--question", "which flag set is current?", "--owner-role", "documentation owner")
        # EX-5 per F-7: seeded `unverified` through `record` (a status above that needs captures, which only `http` writes - the stand)
        call("investigation_probe.py", "record", "--task-root", str(self.task_root), "--dispatch", dispatch, "--target", "case-TC-011",
             "--kind", "observation", "--statement", "the file knowledge base stalled in the follow-up run", "--why-not-a-bug",
             "an environment stall seen once; no capture was taken in this pass", "--status", "unverified")
        # EX-6: the TC-006 line is withdrawn (its chain ends withdrawn; a later `project` skips it)
        if "case-TC-006" in by_target:
            call("exploratory_findings.py", "withdraw", "--task-root", str(self.task_root), "--by", dispatch, "--id", by_target["case-TC-006"],
                 "--reason", "the follow-up run settled TC-006 outside this register")
        else:
            refused.append("no active line of case-TC-006 to withdraw")
        add("coverage_gap", "GAP-1 the UI display was not observed", "the displayed last-indexed text was never looked at",
            "--missing-prerequisite", "a browser profile on the stand")
        add("coverage_gap", "GAP-2 SVN and SharePoint sources were not reached", "no SVN or SharePoint source could be indexed",
            "--missing-prerequisite", "a stand with those sources")
        return refused

    def fill_form(self, dispatch: str) -> tuple:
        """The role fills the form `story_step start` wrote: `scope: []` is the template's own empty outcome, no `not_for_repair` rows; the
        `inputs_read` row for work/run-report.json (version and failures, what the role read) and the provenance row; the claims."""
        form = self.task_root / "work" / "handoffs" / f"{dispatch}.yaml"
        report = json.loads((self.task_root / "work" / "run-report.json").read_text(encoding="utf-8"))
        failures = len([row for row in report.get("current_results") or [] if row.get("status") in ("failed", "error")]) or 7
        values = {"header.verdict": "ok", "inputs_read[0].version": sha(self.task_root / "work" / "run-report.json")[:16],
                  "inputs_read[0].failures": failures,
                  "inputs_read[1].path": "work/evidence/runtime-provenance-api-20261026T212438Z.json",
                  "inputs_read[1].version": "local-docker-mr4566-content-match",
                  "claims.every_repair_names_evidence_expected_and_check": True,
                  "claims.no_app_bug_expectation_was_handed_for_repair": True,
                  "claims.every_flaky_verdict_carries_three_isolated_reruns_and_a_mechanism": True}
        code, out = self.cli("handoff_check.py", "--file", str(form), "--task", TASK, "--task-root", str(self.task_root), "--fix", "--values", "-",
                             "--json", stdin=json.dumps(values))
        return code, out, form.read_text(encoding="utf-8")

    def claude(self, prompt, *, role="", dispatch="", stage="", **kw):
        triage = self.task_root / "work" / "triage.json"
        self.claude_calls.append((role, dispatch, stage))
        self.stub["prompt"] = prompt
        self.stub["events_in"] = lines_of(self.events())
        self.stub["mtime_in"], self.stub["triage_in"] = triage.stat().st_mtime_ns, sha(triage)
        self.stub["refused"] = self.seed(dispatch)
        self.stub["form_code"], self.stub["form_report"], self.stub["form"] = self.fill_form(dispatch)
        self.stub["events_out"] = lines_of(self.events())
        self.stub["mtime_out"], self.stub["triage_out"] = triage.stat().st_mtime_ns, sha(triage)
        # The exit gate owes ONE LINE PER ITEM of the dispatch scope (the 12 cases of the run), as at the triage: the five green checks are
        # `passed`, the seven that were open are `unresolved` here - what the pass saw is in the register, not in the digest.
        scope = re.search(r"Dispatch scope[^:]*: (.+)", prompt)
        self.stub["scope_line"] = scope.group(0)[:200] if scope else ""
        text = "\n".join([f"qa-failure-analyst S7 {TASK} {DOT} ok"]
                         + [f"TC-{n:03d} {DOT} passed {DOT} green in the current run" for n in range(1, 6)]
                         + [f"TC-{n:03d} {DOT} unresolved {DOT} read-only investigation: see the findings register" for n in range(6, 13)]
                         + [REGISTER])
        return {"is_error": False, "result": text, "session_id": "", "exit_code": 0, "stderr": ""}

    def wrap_order(self):
        """Record the order of the moves the gate makes (K-M3-22), each wrapper calling the original."""
        replay, order = self, self.order

        def wrapped(label, original):
            def inner(*args, **kw):
                order.append(label(*args, **kw) if callable(label) else label)
                return original(*args, **kw)
            return inner
        story_run.Driver.s7_repairs = wrapped("s7_repairs", self.saved["s7_repairs"])
        story_run.Driver.s7_close = wrapped("s7_close", self.saved["s7_close"])
        real_await = self.saved["s7_await_scribe"]

        def await_scribe(d, person_words=""):
            """X7-6c: S7 closes only over the consumer's (scribe's) `accept` record of the analyst's LAST triage dispatch; the stub scribe has
            judged it (the record written the way `stage_done.py --acceptance` writes it), so the repairs' end goes on to the close by code."""
            import acceptance
            author = acceptance.stage_author_dispatch(replay.state(), acceptance.stage_def_of("S7"))
            pipeline_path = replay.task_root / "pipeline.json"
            pipeline = json.loads(pipeline_path.read_text(encoding="utf-8")) if pipeline_path.is_file() else {}
            if author and not acceptance.accepted_for(pipeline, "S7", author):
                story_run_common.accept_record(replay.task_root, "S7", author)
            return real_await(d, person_words)
        story_run.Driver.s7_await_scribe = await_scribe
        story_run.Driver.run_role = wrapped(lambda d, stage, role, **kw: f"run_role:{stage}:{role}:{kw.get('purpose')}", self.saved["run_role"])
        story_run.Driver.close_by_code = wrapped(lambda d, stage, reason, evidence, **kw: f"close_by_code:{kw.get('site')}", self.saved["close_by_code"])
        investigation.project = wrapped("project", self.saved_inv["project"])
        investigation.close_gaps = wrapped("close_gaps", self.saved_inv["close_gaps"])
        story_run.Driver.run_claude = lambda d, kind, prompt, **kw: replay.claude(prompt, **kw)


def fixture_rows() -> list:
    return json.loads((FIXTURE / "work" / "triage.json").read_text(encoding="utf-8"))["triage"]


def triage_set(rows) -> set:
    return {(CT.row_names(row)[0], row.get("verdict")) for row in rows if isinstance(row, dict) and CT.row_names(row)}


def archived_rows(task_root: Path) -> list:
    rows = []
    for path in sorted((task_root / "state" / "migration").glob("stale-triage-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        found = data.get("rows") if isinstance(data, dict) else data
        rows += [row for row in (found or []) if isinstance(row, dict)]
    return rows


# ---------------------------------------------------------------------------------------------------------------- R-1
def r1_build(rp: Replay) -> dict:
    shutil.copytree(FIXTURE, rp.task_root, ignore=ignore_left_out(FIXTURE))
    # the four screenshots are not committed (a binary file is a leak the scanner cannot read): the helper rebuilds each one, named by
    # the sha256 of its bytes, as the same size and the same seed give it every time (fixtures/synthetic-derivations.json)
    synthetic_corpus.materialize_blobs(rp.task_root)
    # the helper writes each content-addressed blob WITH a `.png` suffix (selftest --lang skips binaries by suffix, FR-29); the
    # road reads `blobs/<sha256>` (inventory `local_ref`), so the copy takes the suffix off - the bytes are not touched
    renamed = []
    for blob in sorted((rp.task_root / "work" / "blobs").glob("*.png")):
        blob.rename(blob.with_suffix(""))
        renamed.append(blob.stem)
    inventory = json.loads((rp.task_root / "work" / "source-inventory.json").read_text(encoding="utf-8"))
    refs = []

    def walk(node):
        if isinstance(node, dict):
            if str(node.get("local_ref") or "").startswith("blobs/"):
                refs.append((node["local_ref"][len("blobs/"):], node.get("content_hash")))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(inventory)
    wanted = sorted({name for name, _hash in refs})
    check("R-1 every inventory blob reference has local_ref == blobs/<content_hash>", bool(refs) and all(name == h for name, h in refs), str(refs))
    check_eq("R-1 the four blobs lost their .png suffix on copy and match the inventory's local_ref", (len(renamed), sorted(renamed)), (4, wanted))
    check("R-1 each renamed blob's sha256 equals the inventory's content_hash and its own name",
          all(sha(rp.task_root / "work" / "blobs" / name) == name for name in wanted), str(wanted))
    copied = sorted((str(p.relative_to(rp.task_root)).replace("\\", "/"), p.stat().st_size) for p in rp.task_root.rglob("*") if p.is_file())
    print(f"FIXTURE COPY: {len(copied)} files, {sum(size for _n, size in copied)} bytes")
    for name, size in copied:
        print(f"  {size:>9}  {name}")
    names = {name for name, _size in copied}
    check("R-1 the copy holds the run blocks, the S6 handoffs, the request files, evidence, case files, sources, inventory and blobs",
          all(any(n.startswith(prefix) for n in names) for prefix in (
              "work/run-blocks/", "work/handoffs/S6-qa-runner-1.yaml", "work/handoffs/S7-qa-failure-analyst-1.yaml",
              "work/evidence/manual/TC-006/request.json", "work/evidence/followup/", "work/test-cases/", "work/sources/", "work/blobs/",
              "work/source-inventory.json")))
    check("R-1 the copy leaves out the run report, the triage and the archive (they are rebuilt, written later, absent)",
          not ({"work/run-report.json", "work/triage.json"} & names) and not any(n.startswith("state/migration") for n in names),
          str(sorted(n for n in names if n.startswith("state/"))[:6]))
    # the prefix is replayed through the controller: pipeline.json, controller.json, checkpoint.json come out of the events
    controller = CTL.Controller(rp.task_root)
    with contextlib.redirect_stdout(io.StringIO()):
        controller.store.recover(controller.project)
    events = lines_of(rp.events())
    state = rp.state()
    check_eq("R-1 the prefix is 103 events and the replay wrote none of its own", events, 103)
    stages = {name: (state.get("stages") or {}).get(name, {}).get("status") for name in ("S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7")}
    check_eq("R-1 the replay: S0..S6 completed, S7 running with the analyst's dispatch running",
             (stages, (state["dispatches"].get(D1) or {}).get("status")),
             ({**{f"S{n}": "completed" for n in range(7)}, "S7": "running"}, "running"))
    check("R-1 the replay produced pipeline.json, controller.json and checkpoint.json from the events",
          all((rp.task_root / rel).is_file() for rel in ("pipeline.json", "state/controller.json", "state/checkpoint.json")))
    types = [json.loads(line) for line in rp.events().read_text(encoding="utf-8").splitlines()]
    check("R-1 no S7 `code_only` event in the prefix (the new refresh trigger of `controller.project` did not fire at 1..103)",
          not any(e.get("type") == "code_only" and (e.get("payload") or {}).get("stage") in ("S6", "S7") for e in types),
          str(sorted({e.get("type") for e in types})))
    check("R-1 and the replay's refresh rebuilt the run report from the blocks, archived nothing and wrote no register",
          (rp.task_root / "work" / "run-report.json").is_file() and not (rp.task_root / "state" / "migration").exists()
          and not (rp.task_root / REGISTER).exists())
    return {"copied": copied}


# ---------------------------------------------------------------------------------------------------------------- R-2
def r2_first_analyst(rp: Replay) -> None:
    task_root = rp.task_root
    rows = fixture_rows()
    shutil.copyfile(FIXTURE / "work" / "triage.json", task_root / "work" / "triage.json")
    digest, listed = digest_of_d1(task_root)
    runs = task_root / "state" / "driver-runs"
    runs.mkdir(parents=True, exist_ok=True)
    session = next(json.loads(line)["payload"].get("agent_id") for line in reversed(rp.events().read_text(encoding="utf-8").splitlines())
                   if json.loads(line)["type"] == "dispatch" and (json.loads(line)["payload"].get("id") or json.loads(line)["payload"].get("dispatch_id")) == D1)
    (runs / f"{D1}.json").write_text(json.dumps({"result": digest, "session_id": session, "is_error": False}), encoding="utf-8")
    check_eq("R-2 the saved digest has one line per scope item TC-001..TC-012 (12), the header and the file line",
             (len(digest.splitlines()), listed, len(rows)), (14, 7, 7))
    after_write = lines_of(rp.events())
    rp.driver = driver_for(rp.root, rp.env, TASK)
    driver = rp.driver
    rp.wrap_order()
    probe = {}
    original = rp.saved["form_errors"]

    def spy(self, dispatch):
        if dispatch == D1 and "events" not in probe:
            probe["events"] = lines_of(rp.events())
        return original(self, dispatch)
    story_run.Driver.form_errors = spy
    check("R-2 PRECONDITION: the driver reads the story as fresh (no current failure without a triage row)", driver.s7_fresh() is True)
    action = driver.where()
    check_eq("R-2 `where` waits for the analyst's dispatch (its result is saved)", (action.get("action"), action.get("dispatch_id")),
             ("wait_existing_job", D1))
    out = rp.drive(action)
    story_run.Driver.form_errors = original
    check_eq("R-2 EVENT COUNT: no controller event between the triage write and the form check of D1 (the spy count equals the count after the write)",
             (probe.get("events"), after_write), (after_write, after_write))
    print(f"EVENT COUNTS: after the triage write {after_write}; inside Driver.form_errors({D1}) {probe.get('events')}; after D1's accept {lines_of(rp.events())}")
    last = json.loads(rp.events().read_text(encoding="utf-8").splitlines()[-1])
    check_eq("R-2 the first event after the form check is D1's accept (one event)",
             (lines_of(rp.events()), last.get("type"), (last.get("payload") or {}).get("id") or (last.get("payload") or {}).get("dispatch_id")),
             (after_write + 1, "accept", D1))
    check_in("R-2 the driver printed the accept of D1 with the stage left open", "accepted S7-qa-failure-analyst-1", out)
    state = rp.state()
    d1 = state["dispatches"][D1]
    check_eq("R-2 D1 is accepted and carries `investigation_pending`; S7 stays open (pending)",
             (d1.get("status"), d1.get("unresolved"), state["stages"]["S7"]["status"]), ("accepted", "investigation_pending", "pending"))
    check_in("R-2 the reason names the eight observations", "8 observations the run left open are not investigated yet", str(d1.get("reason")))
    archives = sorted((task_root / "state" / "migration").glob("stale-triage-*.json"))
    check_eq("R-2 the controller's refresh at the accept archived the 7 rows (one stale-triage file)", len(archives), 1)
    check_eq("R-2 and work/triage.json holds `triage: []` BEFORE the gate", json.loads((task_root / "work" / "triage.json").read_text(encoding="utf-8")).get("triage"), [])
    check("R-2 the register file does not exist before the gate", not (task_root / REGISTER).exists())
    check("R-2 the story is still fresh after the archive (s7_fresh)", driver.s7_fresh() is True)
    check_eq("R-2 the analyst was not run again (the saved result was read, run_claude not reached)", rp.claude_calls, [])
    check_eq("R-2 the order so far: nothing of the gate ran at D1's accept (K-M3-21b: the finish only asks)", rp.order, [])
    nxt = driver.where()
    check_eq("R-2 the next `where` is `prepare_stage S7`", (nxt.get("action"), nxt.get("stage")), ("prepare_stage", "S7"))
    rp.next_action = nxt
    rp.archived = archived_rows(task_root)
    rp.before = set(state["dispatches"])


# ---------------------------------------------------------------------------------------------------------------- R-3
def r3_gate(rp: Replay) -> None:
    out = rp.drive(rp.next_action)
    rp.out3 = out
    check_in("R-3 the gate says it dispatches ONE read-only investigation for 8 observations",
             "8 observation(s) the run left open are not investigated; one bounded read-only investigation is dispatched", out)
    check_eq("R-3 K-M3-22 / K-M3-11b: the order is s7_repairs, s7_close, project, ONE run_role (investigation), close_gaps, close_by_code",
             rp.order, ["s7_repairs", "s7_close", "project", "run_role:S7:qa-failure-analyst:investigation", "close_gaps",
                        "close_by_code:s7.after_repairs"])
    check_eq("R-3 the stubbed run_claude was reached exactly once, by D2, for the failure analyst", rp.claude_calls, [("qa-failure-analyst", D2, "S7")])
    check_eq("R-3 the seed CLIs refused nothing (a refused seed call is a stop, not a bend)", rp.stub.get("refused"), [])
    check_eq("R-3 the stub's form check passed (handoff_check exit 0)", rp.stub.get("form_code"), 0)
    prompt = rp.stub.get("prompt", "")
    check_in("R-3 the prompt carries the honesty line and the target list", "Findings to investigate:", prompt)
    state = rp.state()
    ids = [t for t in ["case-TC-006", "case-TC-007", "case-TC-008", "case-TC-009", "case-TC-010", "case-TC-011", "case-TC-012", "obs-S6-qa-runner-4-0"]]
    check("R-3 the prompt lists the 8 targets whole: id, Then, observed verbatim, before the change, evidence, why inconclusive",
          all(f"- {target}: Then: " in prompt for target in ids) and prompt.count(" | observed (verbatim): ") == 8
          and prompt.count(" | before the change: ") == 8 and prompt.count(" | why inconclusive: ") == 8,
          prompt[prompt.find("Findings to investigate:"):][:600])
    check_in("R-3 the caps line comes from the budget file", "12 probes per pass (used so far: 0), 3 per target, 20 minutes from the first probe; at most 4 targets", prompt)
    check("R-3 the commands, the six end states and the form note are in the lines before the work",
          all(token in prompt for token in ("investigation_probe.py", "exploratory_findings.py", "End states of a target", "`scope: []`")))
    check("R-3 the archived rows are no context of the dispatch (the triage was archived before the gate: no 'S7 triage said' line)",
          "S7 triage said" not in prompt)
    check_eq("R-3 the stub saw no controller event inside its call (events unchanged across it)", rp.stub["events_in"], rp.stub["events_out"])
    check_eq("R-3 the triage file is untouched across the stubbed run_claude call (mtime and bytes)",
             (rp.stub["mtime_in"], rp.stub["triage_in"]), (rp.stub["mtime_out"], rp.stub["triage_out"]))
    dispatches = state["dispatches"]
    members = investigation.pass_members(state)
    check_eq("R-3 exactly one investigation pass exists and it is accepted (D2); no other dispatch was made after D1 (no repair round)",
             ([(m["id"], m.get("status")) for m in members], sorted(set(dispatches) - rp.before)), ([(D2, "accepted")], [D2]))
    check_eq("R-3 S7 is completed by the close", state["stages"]["S7"]["status"], "completed")


# ---------------------------------------------------------------------------------------------------------------- R-4
def r4_register(rp: Replay) -> None:
    task_root = rp.task_root
    got = exploratory_findings.read(task_root)
    check_eq("R-4 every register line is readable", got["unreadable"], [])
    targets = ["case-TC-006", "case-TC-007", "case-TC-008", "case-TC-009", "case-TC-010", "case-TC-011", "case-TC-012", "obs-S6-qa-runner-4-0"]
    active = got["active"]
    chains = {t: [line for line in got["lines"] if (line.get("origin") or {}).get("target") == t] for t in targets}
    check("R-4 every target has a chain, and only case-TC-006's chain ends without an active line (withdrawn)",
          all(chains[t] for t in targets) and "case-TC-006" not in active and all(t in active for t in targets if t != "case-TC-006"),
          str({t: len(c) for t, c in chains.items()}))
    check_eq("R-4 the chain of case-TC-006: the code line, then the role's withdraw", [(l["op"], l["recorded_by"].split(".")[0]) for l in chains["case-TC-006"]],
             [("add", "code:investigation"), ("withdraw", D2)])
    check_eq("R-4 case-TC-011 carries the role's EX-5 as its active line: observation, unverified, 0 captures",
             (active["case-TC-011"]["recorded_by"], active["case-TC-011"]["kind"], active["case-TC-011"]["verification_status"],
              active["case-TC-011"]["probe"]["runs"]), (D2, "observation", "unverified", 0))
    gaps = [t for t in targets if t in active and active[t]["kind"] == "coverage_gap"]
    check_eq("R-4 the six targets the role never touched are coverage gaps: 'not investigated - the investigation ended before this target', written by code",
             (sorted(gaps), {active[t]["missing_prerequisite"] for t in gaps}, {active[t]["recorded_by"] for t in gaps}),
             (sorted(set(targets) - {"case-TC-006", "case-TC-011"}), {WHY_END}, {investigation.BY_CLOSE}))
    check("R-4 each gap chain is the code line corrected ONCE (one active line per target, no second correct on re-entry)",
          all([l["op"] for l in chains[t]] == ["add", "correct"] for t in gaps))
    untargeted = [line for key, line in active.items() if key not in targets]
    check_eq("R-4 the role's untargeted lines stand: EX-1..EX-4 and the two coverage gaps (6)", len(untargeted), 6)
    again = investigation.project(task_root, "S7")
    check_eq("R-4 a second `project` adds nothing and corrects nothing; the withdrawn and the role-touched chains are skipped",
             (again["added"], again["corrected"], sorted(again["skipped"])), ([], [], ["case-TC-006", "case-TC-011"]))
    # the close: the reason, the suffix with n = k + g (F-8)
    closes = [json.loads(l) for l in rp.events().read_text(encoding="utf-8").splitlines()]
    coded = [e for e in closes if e["type"] == "code_only" and (e.get("payload") or {}).get("stage") == "S7"]
    reason = str(coded[-1]["payload"].get("reason")) if coded else ""
    n, k, g = 8, 2, 6
    suffix = f"; {n} observation(s) the run left open were investigated read-only: {k} recorded by the analyst, {g} left as coverage gaps"
    check_eq("R-4 the close reason: the true sentence of a stage with nothing to repair + the suffix (n = k + g: 8 = 2 + 6; k counts the withdrawn chain)",
             reason, "no failing test to repair; the failure analyst's triage stands" + suffix)
    check_eq("R-4 n = k + g", n, k + g)
    receipt = {ref.get("path"): ref.get("sha256") for ref in (coded[-1]["payload"].get("evidence_refs") or [])} if coded else {}
    check_eq("R-4 the code_only receipt of the close stands on the register as the pass left it (path and sha256)",
             receipt.get(REGISTER), sha(task_root / REGISTER))


# ---------------------------------------------------------------------------------------------------------------- R-5
def r5_readers(rp: Replay) -> None:
    import finalize_task
    import gate_brief
    import report_facts
    task_root = rp.task_root
    before = sha(task_root / REGISTER)
    with contextlib.redirect_stdout(io.StringIO()):
        finalize_task.refresh(task_root)
    check("R-5 `finalize_task.refresh` leaves the register byte-identical", before and sha(task_root / REGISTER) == before)
    facts = report_facts.build(task_root)
    active = exploratory_findings.read(task_root)["active"]
    check_eq("R-5 the facts: no bug of the run (the register is not a bug carrier)", (facts["bugs"] or {}).get("records"), [])
    formal = (facts["exploratory"] or {}).get("formal", {})
    gaps = [l for l in active.values() if l["kind"] == "coverage_gap"]
    check_eq("R-5 the facts: the formal line counts the active findings and the gaps apart (findings + gaps == active)",
             (formal.get("findings"), formal.get("gaps")), (len(active) - len(gaps), len(gaps)))
    blocks = report_facts.render(facts)
    body = blocks.get("exploratory", "")
    check("R-5 the report carries the exploratory block with its three sections and every active finding in words (no register id)",
          all(h in body for h in ("### Observations", "### Unresolved questions", "### Coverage gaps"))
          and all(f"- {report_facts._plain(l.get('statement'))}" in body or f" — {report_facts._plain(l.get('statement'))} — " in body
                  for l in active.values()) and "EX-" not in body, body[:400])
    withdrawn = [l for l in exploratory_findings.read(task_root)["lines"] if l.get("_status") == "withdrawn"]
    check("R-5 the withdrawn line is struck through, with its reason and no register id",
          withdrawn and f"~~{report_facts._plain(withdrawn[0].get('statement'))}~~ — withdrawn:" in body)
    check("R-5 no line of the block is a bug: the block holds no 'severity' and no draft path", "severity" not in body and "bug-drafts" not in body)
    gate = report_facts.exploratory_gate_lines(task_root)
    check_in("R-5 the gate lines open with the count of active findings, 'not bugs'", f": {len(active)} — not bugs, nothing is filed from them", gate[0] if gate else "")
    brief = gate_brief.render_gate_b(TASK, task_root)
    at_gate, at_none = brief.find(gate[0]) if gate else -1, brief.find("Bugs found")
    check("R-5 the gate B packet holds the count line ABOVE 'Bugs found'", 0 <= at_gate < at_none, f"{at_gate} {at_none}")
    check_in("R-5 the packet still says there is no bug to file (the register adds none)", "Bugs found — none", brief)
    questions = [l for l in active.values() if l.get("oracle_status") == "owner_question"]
    check("R-5 every live question (any kind) is a line of the packet with its question in words and no register id (HF8-20, W2)",
          questions and all(report_facts._plain(l.get("question")) in brief for l in questions if l.get("question"))
          and not re.search(r"^- EX-\d+ — ", brief, re.M)      # (the old line shape; the fixture's TITLES say "EX-1 ...": their own words)
          and "Questions for you — is this intended? (" in brief, brief[:300])


# ---------------------------------------------------------------------------------------------------------------- R-6
def r6_triage_and_evidence(rp: Replay) -> None:
    task_root = rp.task_root
    rows = fixture_rows()
    now = triage_set(json.loads((task_root / "work" / "triage.json").read_text(encoding="utf-8")).get("triage") or []) | triage_set(archived_rows(task_root))
    check_eq("R-6 TRIAGE (archive-aware): the set of (row name, verdict) over work/triage.json and every stale-triage file equals the 7 rows",
             now, triage_set(rows))
    check_eq("R-6 the archive holds the 7 rows as the analyst wrote them (no row added, none dropped)", len(rp.archived), 7)
    # K-M3-23 on the rebuilt rows: a further temp copy gets the 7 rows back, as the analyst's file
    budget = json.loads((PLUGIN_ROOT / "references" / "investigation-budget.json").read_text(encoding="utf-8"))
    copy = harness.temp_dir("qa-s7-replay-copy-")
    rp.extra_roots.append(copy)
    one = copy / TASK
    shutil.copytree(task_root, one)
    shutil.copyfile(FIXTURE / "work" / "triage.json", one / "work" / "triage.json")
    env_rows = [row for row in rows if row.get("verdict") == "ENV_ISSUE"]
    check_eq("R-6 K-M3-23: the fixture holds the four ENV_ISSUE rows", len(env_rows), 4)
    issues = {row["case"]: CT.evidence_ref_issue(one / "work", {"path": row["evidence"]}, "triage evidence", require_hash=False, under="evidence")
              for row in env_rows}
    check_eq("R-6 K-M3-23: each ENV_ISSUE row's evidence is judged with the literal evidence_ref_issue call: '' for an existing file under work/",
             issues, {row["case"]: "" for row in env_rows})
    answer = investigation.unresolved_targets(one, budget)
    unresolved = {t["id"] for t in answer["unresolved"]}
    check("R-6 with the rows back, the ENV_ISSUE and NOT_EXECUTED cases stay UNRESOLVED (context, never a resolution)",
          {"case-TC-007", "case-TC-008", "case-TC-009", "case-TC-010", "case-TC-012"} <= unresolved and "case-TC-006" not in unresolved,
          str(sorted(unresolved)))
    check("R-6 and their triage rows are attached as context, without an evidence issue",
          all(any(c.startswith("triage ENV_ISSUE") and "; evidence:" not in c for c in answer["context"].get(f"case-{case}", [])) for case in issues),
          str(answer["context"].get("case-TC-007")))
    victim = env_rows[0]
    (one / "work" / victim["evidence"]).unlink()
    gone = investigation.unresolved_targets(one, budget)
    issue = CT.evidence_ref_issue(one / "work", {"path": victim["evidence"]}, "triage evidence", require_hash=False, under="evidence")
    check("R-6 K-M3-23: the same row with its file removed yields the issue text, attached to the target, never a resolution",
          bool(issue) and f"case-{victim['case']}" in {t["id"] for t in gone["unresolved"]}
          and any(f"; evidence: {investigation._unrooted(one, issue)}" in c for c in gone["context"].get(f"case-{victim['case']}", [])), str(gone["context"].get(f"case-{victim['case']}")))


def main() -> None:
    rp = Replay()
    try:
        r1_build(rp)
        r2_first_analyst(rp)
        r3_gate(rp)
        r4_register(rp)
        r5_readers(rp)
        r6_triage_and_evidence(rp)
    except BaseException as exc:   # a crash is a FAIL line of the file, not the end of it
        import traceback
        check("the replay ran to its end without an exception", False, "".join(traceback.format_exception(exc))[-1500:])
        print("THE STUB'S FORM CHECK:", rp.stub.get("form_code"), str(rp.stub.get("form_report"))[:2500], "REFUSED:", rp.stub.get("refused"))
    finally:
        rp.done()
    finish("test_s7_investigation_replay")


if __name__ == "__main__":
    main()
