#!/usr/bin/env python3
"""HF8-19 N1b: a manual runner's misread of its own captures goes back to the runner from S7, with a limit (keys Q5, Q6, Q9a-f).

  Q5   the word: `contract.TRIAGE_VERDICTS` = `vocabulary.yaml` = the kinds row = the delivery owner; the S7 contract's
       `repair_verdicts` does not hold it
  Q6   `contract.triage_contradiction_problems`: one row per refused input (each names a door, none raises); the form is judged,
       the meaning never (a quote that is there and does not decide is accepted); `failed:...` is `no`, owner the factory
  Q9a  `s7_repairs` makes exactly one `rework("S6", "qa-runner", [case], ...)`, with the budget, the limit question and the
       defect filing never touched; S7 is then closed by code
  Q9b  the real controller: a re-judge `rework` of the completed S6 is accepted with `stage_complete: false`, S6 stays `completed`
       and the next action is S7 again
  Q9c  a fall: an accepted round of this life is not run twice; a running re-judge is never a completion of S6
  Q9d  the limit: at `repair_cycles - 1` the round runs, at `repair_cycles` it does not (across lives, per attempt root)
  Q9e  the selection and the wording of `s7_open_work`
  Q9f  `code_sentences` and `s7_close`
Each check names the ONE mutation that kills it (the canon runs them, D-0056).
"""
import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import PLUGIN_ROOT, check, check_eq, check_in, check_not_in, finish  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import check_delivery as CD  # noqa: E402
import contract as C  # noqa: E402
import delivery_verdict as DV  # noqa: E402
import manual_evidence as M  # noqa: E402
import s7_pretriage as S  # noqa: E402
import story_run  # noqa: E402
from story_run_common import awaits  # noqa: E402
from test_story_run_s7 import LIFE, LimitRig, quietly, write  # noqa: E402

WORD = C.TRIAGE_MISREAD_VERDICT
CASE = "TC-1"
REL = "work/evidence/manual/TC-1/a9/captures/page.txt"
PAGE = "The page says: Saved successfully. Nothing else was shown."
QUOTE = "Saved successfully"


def contradiction(**over) -> dict:
    return dict({"then": 1, "runner_said": "the page showed no confirmation", "evidence": REL, "quote": QUOTE}, **over)


def misread(**over) -> dict:
    row = {"case": CASE, "instance_id": CASE, "attempt_id": "a9", "verdict": WORD, "evidence": REL, "contradiction": contradiction()}
    row.update(over)
    return row


def lay(task_root: Path, case=CASE, attempt="a9", name="page.txt", text=PAGE, thens=("1",)) -> str:
    """The captured text of one attempt (and the case's request.json with its Thens) under the task root; its relative path."""
    folder = task_root / "work" / "evidence" / "manual" / case
    (folder / attempt / "captures").mkdir(parents=True, exist_ok=True)
    (folder / attempt / "captures" / name).write_text(text, encoding="utf-8")
    (folder / "request.json").write_text(json.dumps({"thens": {n: f"Then {n}" for n in thens}}), encoding="utf-8")
    return f"work/evidence/manual/{case}/{attempt}/captures/{name}"


class Rig(LimitRig):
    """`LimitRig` with a re-judge world: the captured text laid, `rework` recorded (the S6 runner rounds), and every road that the
    S5 repair loop reads (the budget, the limit question, the defect filing) booby-trapped."""

    def __init__(self, rows, refuse=False):
        super().__init__(rows)
        lay(self.task_root)
        self.calls, self.refuse, self.touched, self.dispatches = [], refuse, [], {}
        d = self.driver
        d.controller_state = lambda: {"dispatches": dict(self.dispatches)}
        d.repair_budget = lambda *a, **k: self.touched.append("repair_budget") or (_ for _ in ()).throw(RuntimeError("budget read"))
        d.s7_limit = lambda *a, **k: self.touched.append("s7_limit")
        d.py_trace = lambda *a, **k: self.touched.append("defect_found")

    def rework(self, stage, role, cases, reason, **kw):
        if self.refuse:
            raise story_run.ReworkRefused("the controller refused")
        rid = f"S6-qa-runner-{len(self.calls) + 2}"
        self.calls.append(dict(kw, stage=stage, role=role, cases=list(cases), reason=reason, rid=rid))
        kw["on_request"](rid)
        self.dispatches[rid] = {"status": "accepted", "stage": stage, "role": role}
        return "digest", {}

    def closed_with(self) -> list:
        return [entry for entry in self.py_log if entry[0] == "code_only"]


# ------------------------------------------------------------------------------------------------------ Q5
def q5_the_word() -> None:
    """M1 (`repair_verdicts` + the word) is killed here; M2 (the kinds row made `assert_stricter`) by the kind check."""
    check("Q5 the word is in contract.TRIAGE_VERDICTS", WORD in C.TRIAGE_VERDICTS)
    check_eq("Q5 the one spelling", WORD, "RUNNER_MISREAD_EVIDENCE")
    vocabulary = (PLUGIN_ROOT / "handoffs" / "vocabulary.yaml").read_text(encoding="utf-8")
    check_in("Q5 handoffs/vocabulary.yaml names it for the analyst alone", f"{WORD}: {{restricted_to: [qa-failure-analyst]", vocabulary)
    doc = DV.load_kinds()[0]
    check_eq("Q5 `failed:<word>` is `red` in the kinds file", DV._lookup("failed:" + WORD, doc.get("ledger_states") or {}), "red")
    check_eq("Q5 ... and its kind is red (not assert_stricter, not a waiver)", DV.kind_of_state("failed:" + WORD, doc), "red")
    check_eq("Q5 ... which decides `no`", DV.decide([DV.kind_of_state("failed:" + WORD, doc)], doc)[0], "no")
    check_eq("Q5 the delivery owner is the factory", CD.OWNER_BY_TRIAGE_VERDICT.get(WORD), "factory")
    import check_witness
    check("Q5 check_witness.TRIAGE_MATRIX derives the word (it passes the matrix by itself)", WORD in check_witness.TRIAGE_MATRIX)
    import handoff
    declared = handoff.null_outcomes("s7-analyst-to-automator")["scope"]["params"]["repair_verdicts"]
    check("Q5 the S7 contract's repair_verdicts does not hold it (no repair, no automator)",
          WORD not in {str(v).split(":")[0].upper() for v in declared}, str(declared))
    card = json.loads((PLUGIN_ROOT / "references" / "ahead-cards.json").read_text(encoding="utf-8"))
    check_in("Q5 the analyst's ahead card names it", WORD, json.dumps(card))


# ------------------------------------------------------------------------------------------------------ Q6
def q6_the_form() -> None:
    """M3 (the `quote` substring check removed) is killed by `quote not in the file`."""
    root = harness.temp_dir("qa-s7rej-q6-")
    try:
        lay(root)
        (root / "work/evidence/manual/TC-1/a9/captures/binary.txt").write_bytes(b"\xff\xfe\x00 " + "café ok".encode("utf-8")[:4])
        absolute = str(root / REL)
        refused = {
            "no block": (misread(contradiction=None), "needs its `contradiction` block"),
            "block is a list": (misread(contradiction=[1]), "must be an object"),
            "then missing": (misread(contradiction=contradiction(then=None)), "`contradiction.then`"),
            "then is words": (misread(contradiction=contradiction(then="first")), "`contradiction.then`"),
            # HF819-bool (t-428): `True` is the int 1, and 1 is a Then of TC-1: only the bool test refuses it
            "then is true": (misread(contradiction=contradiction(then=True)), "`contradiction.then`"),
            "then is Arabic-Indic digits": (misread(contradiction=contradiction(then="١")), "`contradiction.then`"),
            "then not a Then of the case": (misread(contradiction=contradiction(then=7)), "not a Then of TC-1"),
            "runner_said empty": (misread(contradiction=contradiction(runner_said="")), "`contradiction.runner_said`"),
            "runner_said not text": (misread(contradiction=contradiction(runner_said=5)), "`contradiction.runner_said`"),
            "evidence empty": (misread(contradiction=contradiction(evidence="")), "`contradiction.evidence`"),
            "evidence absolute": (misread(contradiction=contradiction(evidence=absolute)), "absolute"),
            "evidence escapes": (misread(contradiction=contradiction(evidence="../x.txt")), "escapes"),
            "evidence with NUL": (misread(contradiction=contradiction(evidence="work/ev\x00.txt")), "NUL"),
            "evidence outside the case": (misread(contradiction=contradiction(evidence="work/triage.json")), "not under"),
            "evidence in the case but no attempt": (misread(contradiction=contradiction(evidence="work/evidence/manual/TC-1/request.json")),
                                                    "not inside an attempt"),
            "evidence is no file": (misread(contradiction=contradiction(evidence="work/evidence/manual/TC-1/a9/captures/none.txt")),
                                    "not a file"),
            "quote empty": (misread(contradiction=contradiction(quote="")), "`contradiction.quote`"),
            "quote of spaces": (misread(contradiction=contradiction(quote="   \n ")), "`contradiction.quote`"),
            "quote not in the file": (misread(contradiction=contradiction(quote="Saved unsuccessfully")), "is not in"),
            "quote 301 characters": (misread(contradiction=contradiction(quote="a" * 301)), "longer than 300"),
            "file not utf-8, quote beyond it": (misread(contradiction=contradiction(
                evidence="work/evidence/manual/TC-1/a9/captures/binary.txt", quote="café")), "is not in"),
            "an automated test": (misread(test="tests/test_a.py::test_one"), "automated test"),
            "another instance": (misread(instance_id="inst_1"), "automated test"),
            "no case": (misread(case=""), "no `case`"),
            "a reorder": (misread(reorder=True), "reorder"),
        }
        for label, (row, needle) in refused.items():
            problems = C.triage_contradiction_problems(row, root)
            check(f"Q6 refused: {label}", bool(problems) and any(needle in p for p in problems), str(problems))
            check(f"Q6 {label}: every problem names a door", all("writes the row again" in p or "write the row again" in p for p in problems),
                  str(problems))
        # F-8: the evidence lies in the attempt THE ROW NAMES, and is a capture, not the attempt's own record
        a8 = lay(root, attempt="a8")
        (root / "work/evidence/manual/TC-1/a9/record.json").write_text(json.dumps({"actual": PAGE}), encoding="utf-8")
        for label, row, needle in (
                ("evidence of attempt a8 on a row that names a9", misread(contradiction=contradiction(evidence=a8)), "names attempt a9"),
                ("a re-judge row a9-r1 with evidence of a8", misread(attempt_id="a9-r1", contradiction=contradiction(evidence=a8)), "names attempt a9-r1"),
                ("the attempt's own record.json as the capture", misread(contradiction=contradiction(
                    evidence="work/evidence/manual/TC-1/a9/record.json", quote="Saved")), "own record")):
            problems = C.triage_contradiction_problems(row, root)
            check(f"Q6 refused: {label}", bool(problems) and any(needle in p for p in problems), str(problems))
        check_eq("Q6 positive: a row a9-r1 (a re-judge of a9) with evidence of a9 is accepted",
                 C.triage_contradiction_problems(misread(attempt_id="a9-r1"), root), [])
        check_eq("Q6 positive: a row naming no attempt takes evidence of any attempt of the case",
                 C.triage_contradiction_problems(misread(attempt_id="", contradiction=contradiction(evidence=a8)), root), [])
        # the form is judged, never the meaning: a quote that is there and does not decide the Then is accepted
        check_eq("Q6 positive: a quote the file holds is accepted (code never judges the contradiction)",
                 C.triage_contradiction_problems(misread(), root), [])
        check_eq("Q6 positive: `then` as a digit string, instance_id = case", C.triage_contradiction_problems(
            misread(contradiction=contradiction(then="1")), root), [])
        exact = C.triage_contradiction_problems(misread(contradiction=contradiction(quote="x" * 300)), root)
        check("Q6 a quote of exactly 300 characters is within the limit (only `not in the file` is said)",
              not any("longer than 300" in p for p in exact) and any("is not in" in p for p in exact), str(exact))
        # a doubt about the caller: no task root - the file is not judged and the word never passes on its form alone
        check_eq("Q6 no task root: the field-level form still holds", C.triage_contradiction_problems(misread(), None), [])
        check("Q6 no task root: a missing field is still refused", bool(C.triage_contradiction_problems(
            misread(contradiction=contradiction(then=None)), None)))
        # never raises, whatever the row
        for odd in (None, [], "x", 5, {"verdict": WORD}, {"verdict": [WORD]}, {"verdict": WORD, "contradiction": "x"},
                    {"verdict": WORD, "case": [1], "contradiction": {"then": [], "evidence": {}, "quote": 3}}):
            try:
                got = C.triage_contradiction_problems(odd, root)
                check(f"Q6 {odd!r} does not raise", isinstance(got, list))
            except Exception as exc:        # pragma: no cover - the failure is the report
                check(f"Q6 {odd!r} does not raise", False, repr(exc))
        check_eq("Q6 a row of another verdict is not judged here", C.triage_contradiction_problems({"verdict": "APP_BUG"}, root), [])
        # the validator and the delivery check ask the same reader
        errors = []
        import validate_artifacts
        validate_artifacts.check_triage_v0(Path("triage.json"), {"triage": [misread(contradiction=None)]}, errors, task_root=root)
        check("Q6 check_triage_v0 refuses a row without its block", any("contradiction" in e for e in errors), str(errors))
        errors = []
        validate_artifacts.check_triage_v0(Path("triage.json"), {"triage": [misread()]}, errors, task_root=root)
        check_eq("Q6 check_triage_v0 takes a row with its block", [e for e in errors if "contradiction" in e], [])
    finally:
        harness.cleanup(root)


# ------------------------------------------------------------------------------------------------------ Q9a
def q9a_one_rework_of_the_runner() -> None:
    """M4 (`s7_repairs` without the call of `s7_rejudge_round`) is killed here."""
    rig = Rig([misread()])
    try:
        raised, printed = rig.run()
        check_eq("Q9a s7_repairs ends without a raise", raised, None)
        check_eq("Q9a exactly one rework", len(rig.calls), 1)
        call = rig.calls[0]
        check_eq("Q9a ... of the S6 runner over the one case", (call["stage"], call["role"], call["cases"]), ("S6", "qa-runner", [CASE]))
        check_eq("Q9a ... with the reason the receipt reads", call["reason"], "S7 re-judge: TC-1")
        check_eq("Q9a ... cause reviewer_error (QE-1 a), not the closing flag", (call["cause"], call["complete"]), ("reviewer_error", False))
        words = "\n".join(call["extra"])
        for label, needle in (("the attempt", "--of-attempt a9"), ("the Then", "Then 1"), ("the runner's words", "the page showed no confirmation"),
                              ("the quote", QUOTE), ("the file", REL), ("the command", "manual_evidence.py"), ("the run is not repeated", "nothing is captured again")):
            check_in(f"Q9a the runner is told {label}", needle, words)
        check("Q9a the copied command quotes the task root (a path with a space)", '--task-root "' + str(rig.driver.task_root) + '"' in words, words[-400:])
        check_eq("Q9a the budget, the limit question and the defect filing are never touched", rig.touched, [])
        check_eq("Q9a the count is kept under the case and the attempt root", rig.driver.state["s7_rejudge"], {"TC-1|a9": ["S6-qa-runner-2"]})
        check_eq("Q9a the outcome of the life", rig.driver.s7_outcome(LIFE, "TC-1"), "rejudged")
        closed = rig.closed_with()
        check_eq("Q9a S7 is closed by code after the round", len(closed), 1)
        check_in("Q9a ... saying a manual check was sent back", "1 manual check(s) were sent back to be judged again", closed[0][1][1])
        check_not_in("Q9a ... and not saying a test was repaired or nothing was found", "no failing test to repair", closed[0][1][1])
    finally:
        rig.done()


# ------------------------------------------------------------------------------------------------------ Q9b
def q9b_the_real_controller() -> None:
    """The way back into S7 on the REAL controller (the tail of `_next_action_for_state` read first: the stage loop answers the first
    stage that is not `completed`, and a `rework` never lowers S6). Mutation: none in the driver - this pins the controller's side."""
    import test_fixes_13797 as F
    import test_controller_state as BASE
    root = F.temp_project("qa-s7rej-q9b-")
    try:
        c = F.s6_story(root)
        check_eq("Q9b the automation half", F.runner(c, root, "S6-auto", "automation", ["TC-1"], False), "")
        check_eq("Q9b the manual half closes S6", F.runner(c, root, "S6-manual", "manual", ["TC-2"], True), "")
        check_eq("Q9b S6 completed", c.state()["stages"]["S6"]["status"], "completed")
        c.apply("dispatch", {"id": "S7-qa-failure-analyst-1", "stage": "S7", "role": "qa-failure-analyst", "scope": ["TC-1", "TC-2"],
                             "input_hash": "s7", "budget": {}, "known_paths": {}, "idempotency_key": "dispatch-s7"})
        c.apply("accept", {"id": "S7-qa-failure-analyst-1", "status": "accepted", "stage_complete": False,
                           "unresolved": "repairs_pending", "reason": "the analyst finished; S7 was kept open until the runner judges again",
                           "evidence_refs": [BASE.evidence_ref(root, "S7.txt", "s7")], "idempotency_key": "accept-s7"})
        before = c.next_action()
        check_eq("Q9b S7 is the next action before the re-judge", (before["action"], before.get("stage")), ("prepare_stage", "S7"))
        request = c.build_rework_request("S6", "qa-runner", ["TC-2"], "S7 re-judge: TC-2", "repair_verify", None, "reviewer_error")
        check_eq("Q9b the controller builds the manual runner rework (kind and cause)",
                 (request.get("execution_kind"), request.get("repair_cause")), ("manual", "reviewer_error"))
        c.apply("dispatch", dict(request))
        check_eq("Q9b the re-judge is accepted without closing S6 again", F.runner(c, root, request["id"], "manual", ["TC-2"], False), "")
        state = c.state()
        check_eq("Q9b the rework dispatch is accepted", state["dispatches"][request["id"]]["status"], "accepted")
        check_eq("Q9b S6 stays completed (set_stage is monotonic)", state["stages"]["S6"]["status"], "completed")
        after = c.next_action()
        check_eq("Q9b the next action is S7 again", (after["action"], after.get("stage")), ("prepare_stage", "S7"))
        # F-9: the S7 analyst of this life stays accepted, else `s7_life()` is empty and a SECOND analyst would start
        check_eq("Q9b the S7 analyst stays accepted through the re-judge (no second analyst)",
                 state["dispatches"]["S7-qa-failure-analyst-1"]["status"], "accepted")
        check_eq("Q9b ... and no other S7 dispatch exists", sorted(k for k, v in state["dispatches"].items() if v.get("stage") == "S7"),
                 ["S7-qa-failure-analyst-1"])
    finally:
        harness.cleanup(root)


# ------------------------------------------------------------------------------------------------------ Q9b2 (F-9)
def q9b2_the_real_driver_meets_the_real_controller() -> None:
    """F-9: `Driver.rework` (the real one, the real controller through its CLI) of the completed S6, from the real
    `s7_rejudge_round`; only the role's run is a stub. Kills: `ReworkRefused` raised by the controller for a re-judge; the dispatch not
    registered before the role runs; the accepted rework staling the S7 analyst; S6 lowered."""
    import test_fixes_13797 as F
    import test_controller_state as BASE
    from story_run_common import driver_for
    root = F.temp_project("qa-s7rej-q9b2-")
    try:
        task_root = root / "qa-factory" / "artifacts" / "QA-1"
        task_root.mkdir(parents=True)
        (task_root / "pipeline.json").write_text(json.dumps({"ticket": "QA-1", "stages": {}, "gates": {}, "halts": []}), encoding="utf-8")
        c = F.s6_story(task_root)
        F.runner(c, task_root, "S6-auto", "automation", ["TC-1"], False)
        F.runner(c, task_root, "S6-manual", "manual", ["TC-2"], True)
        c.apply("dispatch", {"id": "S7-qa-failure-analyst-1", "stage": "S7", "role": "qa-failure-analyst", "scope": ["TC-1", "TC-2"],
                             "input_hash": "s7", "budget": {}, "known_paths": {}, "idempotency_key": "dispatch-s7"})
        c.apply("accept", {"id": "S7-qa-failure-analyst-1", "status": "accepted", "stage_complete": False, "unresolved": "repairs_pending",
                           "reason": "the analyst finished; S7 was kept open until the runner judges again",
                           "evidence_refs": [BASE.evidence_ref(task_root, "S7.txt", "s7")], "idempotency_key": "accept-s7"})
        lay(task_root, case="TC-2")
        d = driver_for(root, {"STORY_RUN_CLAUDE": "", "STUB_CONTROL": "", "STUB_LOG": ""}, "QA-1")
        ran: list = []
        d.run_role = lambda stage, role, **kw: ran.append((stage, role, list(kw.get("scope") or []))) or ("digest", {})
        row = misread(case="TC-2", instance_id="TC-2", evidence=REL.replace("TC-1", "TC-2"),
                      contradiction=contradiction(evidence=REL.replace("TC-1", "TC-2")))
        with contextlib.redirect_stdout(io.StringIO()):
            d.s7_rejudge_round(row, "TC-2", "S7-qa-failure-analyst-1")
        state = c.state()
        rework = [k for k in state["dispatches"] if k.startswith("S6-qa-runner") and k not in ("S6-auto", "S6-manual")]
        check_eq("Q9b2 the controller registered ONE re-judge dispatch of the runner, and the role was run on it", (len(rework), ran),
                 (1, [("S6", "qa-runner", ["TC-2"])]))
        check_eq("Q9b2 the driver counted it under the case and the attempt root", sorted(d.state["s7_rejudge"]), ["TC-2|a9"])
        check_eq("Q9b2 S6 stays completed", state["stages"]["S6"]["status"], "completed")
        check_eq("Q9b2 the S7 analyst stays accepted (no second analyst)", state["dispatches"]["S7-qa-failure-analyst-1"]["status"], "accepted")
    finally:
        harness.cleanup(root)


# ------------------------------------------------------------------------------------------------------ Q9c
def q9c_a_fall() -> None:
    """M10 (step 1 does not look at `round`) and M8 (`completion_for` without its branch) are killed here."""
    rig = Rig([misread()])
    try:
        d = rig.driver
        d.s7_mark(LIFE, "TC-1", round="S6-qa-runner-2")
        rig.dispatches["S6-qa-runner-2"] = {"status": "accepted"}
        raised, printed = rig.run()
        check_eq("Q9c a round of this life the controller accepted: no second dispatch", (raised, rig.calls), (None, []))
        check_eq("Q9c ... and the check is `rejudged`", d.s7_outcome(LIFE, "TC-1"), "rejudged")
        check_in("Q9c ... said in a line", "finished outside the loop", printed)
    finally:
        rig.done()
    rig = Rig([misread()])
    try:
        d = rig.driver
        d.stage_scope = lambda *a, **k: {"scope": []}
        d.manual_plan = lambda scope, skip=(): {"blocks": [], "refused": []}
        record = {"id": "S6-qa-runner-2", "execution_kind": "manual", "scope": ["TC-1"]}
        # X7-6: the S6 rule is "the runner's finish that would close S6 awaits the consumer" (the open-work word), no longer a bare True
        check_eq("Q9c a record that is not ours takes the S6 rule (nothing left to run: it would close, so it awaits the consumer)",
                 awaits(d.completion_for("S6", "qa-runner", record)), "stage_awaits_acceptance")
        d.state["s7_rejudge"] = {"TC-1|a9": ["S6-qa-runner-2"]}
        check_eq("Q9c a running re-judge finished through wait_existing_job never closes S6", d.completion_for("S6", "qa-runner", record), False)
        check_eq("Q9c ... another dispatch still takes the S6 rule", awaits(d.completion_for("S6", "qa-runner", dict(record, id="S6-qa-runner-9"))), "stage_awaits_acceptance")
    finally:
        rig.done()


# ------------------------------------------------------------------------------------------------------ Q9d
def life_run(rig, life: str):
    rig.driver.s7_life = lambda: life
    return rig.run()


def q9d_the_limit() -> None:
    """M5 (the count in `s7_rows`, by life), M6 (`>=` -> `>`) and M7 (the key without the attempt root) are killed here."""
    import runtime_policy
    limit = runtime_policy.DEFAULT_LIMITS["repair_cycles"]
    rig = Rig([misread()])
    try:
        for n in range(limit):
            raised, _printed = life_run(rig, f"S7-qa-failure-analyst-{n + 1}")
            check_eq(f"Q9d round {n + 1} of {limit} runs (at {n} spent, below the limit)", (raised, len(rig.calls)), (None, n + 1))
        raised, printed = life_run(rig, f"S7-qa-failure-analyst-{limit + 1}")
        check_eq("Q9d at the limit no round runs, in a NEW life too (the count lives above lives)", (raised, len(rig.calls)), (None, limit))
        check_eq("Q9d ... the outcome is `limit`", rig.driver.s7_outcome(f"S7-qa-failure-analyst-{limit + 1}", "TC-1"), "limit")
        check_in("Q9d ... one line says so", f"the runner has judged this check again {limit} times", printed)
        check_eq("Q9d ... and S7 is closed by code (no question, no wait)", len(rig.closed_with()), limit + 1)
        check_eq("Q9d the budget and the limit seam are never asked", rig.touched, [])
        # the attempt root: `a9-r1` is a re-judge of a9 and counts with it
        write(rig.task_root, triage={"triage": [misread(attempt_id="a9-r1")]})
        before = len(rig.calls)
        life_run(rig, "S7-qa-failure-analyst-9")
        check_eq("Q9d the row of attempt a9-r1 counts under a9: no round", len(rig.calls), before)
        # a new attempt is a new dispute: the count starts again
        lay(rig.task_root, attempt="a10")
        write(rig.task_root, triage={"triage": [misread(attempt_id="a10", evidence=REL.replace("a9", "a10"),
                                                        contradiction=contradiction(evidence=REL.replace("a9", "a10")))]})
        life_run(rig, "S7-qa-failure-analyst-10")
        check_eq("Q9d a new attempt (a10) counts from zero: its round runs", len(rig.calls), before + 1)
        check_eq("Q9d ... under its own key", sorted(rig.driver.state["s7_rejudge"]), ["TC-1|a10", "TC-1|a9"])
    finally:
        rig.done()
    # a refusal of the controller before any registration: no count, no round, the refusal goes up to the seam
    rig = Rig([misread()], refuse=True)
    try:
        raised, _printed = rig.run()
        check("Q9d ReworkRefused goes up (it is the seam's)", isinstance(raised, story_run.ReworkRefused), repr(raised))
        check_eq("Q9d ... and spends no round", rig.driver.state.get("s7_rejudge") or {}, {})
        check_eq("Q9d ... and S7 is not closed over it", rig.closed_with(), [])
    finally:
        rig.done()


# ------------------------------------------------------------------------------------------------------ Q9e
def q9e_the_selection() -> None:
    """M9 (`s7_open_work` does not read `s7_rejudge_rows`) and M11 (no `wants_reorder` filter) are killed here."""
    rig = Rig([misread()])
    try:
        d = rig.driver
        check_eq("Q9e s7_repair_rows does not see the word (the automator is never sent it)", d.s7_repair_rows(), [])
        check_eq("Q9e s7_rejudge_rows takes the row", [r["case"] for r in d.s7_rejudge_rows()], [CASE])
        kept = d.s7_open_work()
        check_eq("Q9e s7_open_work keeps S7 open", getattr(kept, "kind", None) or type(kept).__name__, getattr(kept, "kind", None) or "OpenWork")
        check_in("Q9e ... saying the runner judges the check again", "manual check(s) whose record misreads its own captures", kept.reason)
        check_not_in("Q9e ... and never `whose fault is the test itself`", "whose fault is the test itself", kept.reason)
        for label, row in (("reorder: true", misread(reorder=True)), ("a bad quote", misread(contradiction=contradiction(quote="nope nope"))),
                           ("fixed", misread(fix_result="fixed")), ("no case", misread(case="")), ("another verdict", misread(verdict="APP_BUG"))):
            write(rig.task_root, triage={"triage": [row]})
            with contextlib.redirect_stdout(io.StringIO()):
                got = d.s7_rejudge_rows()
            check_eq(f"Q9e not selected: {label}", got, [])
        write(rig.task_root, triage={"triage": [misread()]})
        d.s7_decided = lambda life=None: {"close": {"words_ref": "x"}}
        raised, printed = rig.run()
        check_eq("Q9e the person's recorded `close` starts no round (their word outranks the code, P13)", (raised, rig.calls), (None, []))
        check_in("Q9e ... said in a line", "recorded decision closes S7", printed)
        d.s7_decided = lambda life=None: {}
        # a mix: both sentences, each only for its own list
        write(rig.task_root, triage={"triage": [misread(), {"case": "TC-2", "instance_id": "t_b", "verdict": "TEST_BUG"}]})
        mixed = d.s7_open_work().reason
        check_in("Q9e a mix: the sentence about the test", "failing test(s) whose fault is the test itself", mixed)
        check_in("Q9e a mix: the sentence about the check", "kept open until the runner judges them again: TC-1", mixed)
        write(rig.task_root, triage={"triage": [{"case": "TC-2", "instance_id": "t_b", "verdict": "TEST_BUG"}]})
        check_not_in("Q9e only a test: no sentence about a check", "misreads", d.s7_open_work().reason)
        # the cut at 300 / 301 characters (no repair row in the list: only the sentence about the check)
        write(rig.task_root, triage={"triage": []})
        for extra, expect_cut in ((0, False), (1, True)):
            short = "X"
            probe = f"the failure analyst found 1 manual check(s) whose record misreads its own captures; S7 was kept open until the runner judges them again: {short}"
            name = "TC-" + "A" * (300 - len(probe) - len("TC-") + len(short) + extra)
            real_rows = d.s7_rejudge_rows
            d.s7_rejudge_rows = lambda name=name: [{"case": name}]      # the selection is pinned above; here only the cut is
            reason = d.s7_open_work().reason
            d.s7_rejudge_rows = real_rows
            check_eq(f"Q9e the reason is at most 300 characters ({300 + extra} before the cut)", len(reason) <= 300, True)
            check_eq(f"Q9e ... cut with the list mark only past 300 ({300 + extra})", reason.endswith("… [list: work/triage.json]"), expect_cut)
        write(rig.task_root, triage={"triage": "x"})
        check_in("Q9e a triage file with no list keeps S7 open (unreadable is not empty)", "could not read", d.s7_open_work().reason)
    finally:
        rig.done()


# ------------------------------------------------------------------------------------------------------ Q9f
def q9f_sentences_and_close() -> None:
    """M12 (`s7_close` without the `sent > 0` condition) and M13 (`code_sentences` without `rejudge_sentence`) are killed here."""
    sentence = M.rejudge_sentence("a9", "the quote decides Then 1")
    check_in("Q9f code_sentences knows the re-judge sentence of a record's own fields", sentence,
             S.code_sentences({"rejudge_of": "a9", "rejudge_reason": "the quote decides Then 1"}))
    check_eq("Q9f ... and a record with no re-judge adds none", sentence in S.code_sentences({"limitations": [sentence]}), False)
    check_eq("Q9f ... so the runner's own limitation is never taken for code's",
             S.role_limitations({"rejudge_of": "a9", "rejudge_reason": "r", "limitations": [M.rejudge_sentence("a9", "r"), "the page was blank"]}),
             ["the page was blank"])
    rig = Rig([misread()])
    try:
        d = rig.driver
        d.s7_mark(LIFE, "TC-1", outcome="rejudged")
        quietly(lambda: d.s7_close([], LIFE, [(misread(), "TC-1")]))
        said = rig.closed_with()[-1][1][1]
        check_eq("Q9f plan == [], one check sent back: the reason says only that", said, "1 manual check(s) were sent back to be judged again")
        check_not_in("Q9f ... never `no failing test to repair`", "no failing test to repair", said)
        quietly(lambda: d.s7_close([], LIFE, []))
        check_in("Q9f nothing sent back: today's words", "no failing test to repair; the failure analyst's triage stands", rig.closed_with()[-1][1][1])
        d.s7_mark(LIFE, "TC-1", outcome="limit")
        quietly(lambda: d.s7_close([], LIFE, [(misread(), "TC-1")]))
        check_in("Q9f a check left at the limit is not `sent back`", "no failing test to repair", rig.closed_with()[-1][1][1])
    finally:
        rig.done()


def main() -> None:
    for step in (q5_the_word, q6_the_form, q9a_one_rework_of_the_runner, q9b_the_real_controller, q9b2_the_real_driver_meets_the_real_controller, q9c_a_fall, q9d_the_limit,
                 q9e_the_selection, q9f_sentences_and_close):
        step()
    finish("test_s7_rejudge")


if __name__ == "__main__":
    main()
