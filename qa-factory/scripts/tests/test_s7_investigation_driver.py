#!/usr/bin/env python3
"""The driver's S7 road of the read-only investigation (P2 M3, wave 4; t-087 §2 M3 "M3 integration", t-108 §4).

`stage_S7`, `s7_open_work`, `s7_close`, `s7_life`, `completion_for`, `role_lines`, `s3_record_lines` and the two new methods
`s7_investigation_gate` / `investigation_lines` are judged in-process, on the unit rigs of `test_story_run_s7.py` (`rig`, `LimitRig`),
with the roles recorded and never run. The REAL `investigation.decision` / `pass_members` run; `unresolved_targets`, `project` and
`close_gaps` are replaced by recording fakes where a key judges the WIRING (their own behaviour is `test_investigation.py`). Roles and `py`
are stubbed WITHOUT a `check` parameter (`test_silent_passes.STUB_FILES` counts those).

  K-M3-10  no failure + 0 targets: the close is today's, the register file is not created (the byte-identity of K6 holds here too)
  K-M3-11  no failure + targets + gate B open: ONE dispatch (purpose investigation), then the `s7.no_failures` close with the suffix and the register
  K-M3-12  `s7_life` and `analyst_done` do not see an accepted investigation member
  K-M3-13  second entry: no second dispatch, the gaps are asked for once per entry
  K-M3-14  repairs, THEN the investigation, then finalize -> receipt -> record (LimitRig)
  K-M3-15  a halted run raises before any register write; NEGATIVE: the gate called first does write
  K-M3-16  gate B answered (and answered then reopened by the person's words): no dispatch, the gaps say so
  K-M3-17  `completion_for` on an investigation record is False (read through `s7_part_of`, not `purpose`)
  K-M3-21  the analyst's finish: dispatch / wait / gaps -> OpenWork("investigation_pending"), none -> None; K-M3-21b it only asks
  K-M3-22  the gate runs once before EACH of the three closers; `wait` returns without a close
  K-M3-26  the restart roads' lines carry the investigation lines; a triage record keeps today's lines
  K-M3-28  `s7.after_repairs` with no repair row: the true sentence + the suffix, the digest + the suffix, the register in the evidence
  K-W4-G   an exception / a missing import of the investigation code: ONE printed line and today's road
  K-W4-C   S7 completed: the gate projects nothing and dispatches nothing
  K-W4-L   the dispatch lines (honesty first, targets whole, caps from the budget file, zero targets, a broken budget, the form note)
  K-W4-R   the OpenWork reason AT 300 and BEYOND 301
  K-F1     the REAL close_gaps on a mixed state (t-114): only the unresolved targets are gaps, n = k + g in the close suffix
  K-M5     the dispatch lines count the probes used so far ("unknown" on a damaged capture file)
  K-W4-SR  `s7.md`: the section, the card line, the whys verbatim; K-M9 the gate-B key
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import PLUGIN_ROOT, check, check_eq, check_in, check_not_in, finish  # noqa: E402
from story_run_common import seed  # noqa: E402
from test_s7_pretriage import Verdict, check_row, report, result  # noqa: E402
from test_story_run_s7 import LIFE, NO_FAILURES, ROW_1, TASK, LimitRig, quietly, rig, write  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import investigation  # noqa: E402
import story_run  # noqa: E402
from test_investigation import FIXTURE  # noqa: E402
from story_run import Refusal  # noqa: E402

REGISTER = "work/exploratory-findings.jsonl"
WHY_END = "the investigation ended before this target"
WHY_B = "gate B is already decided"
TRIAGE = {"stage": "S7", "role": "qa-failure-analyst", "status": "accepted"}
PASS = {"stage": "S7", "role": "qa-failure-analyst", "request_binding": {"purpose": "investigation"}}


def target(i: int, observed: str = "the page said nothing") -> dict:
    return {"id": f"obs-S6-qa-runner-1-{i}", "then": f"Then item {i} shows", "observed": observed, "before_change": "was empty",
            "evidence": [f"work/evidence/manual/x{i}.png"], "why_inconclusive": "refused", "case": None}


def put_register(task_root: Path, *entries) -> None:
    """Lines of the findings register as the one writer leaves them, as far as the driver reads them: (target, recorded_by, op)."""
    path = task_root / REGISTER
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    for tid, by, op in entries:
        lines.append(json.dumps({"id": f"EX-{len(lines) + 1}", "op": op, "origin": {"dispatch": "D", "target": tid}, "recorded_by": by}))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class Fakes:
    """Recording replacements of `investigation.unresolved_targets` / `project` / `close_gaps` for the block."""

    def __init__(self, targets=(), closes=0, on_project=None, context=None):
        self.targets, self.closes, self.on_project, self.context, self.calls = list(targets), closes, on_project, context or {}, []

    def __enter__(self):
        self.saved = (investigation.unresolved_targets, investigation.project, investigation.close_gaps)
        investigation.unresolved_targets, investigation.project, investigation.close_gaps = self.unresolved, self.project, self.close_gaps
        return self

    def __exit__(self, *_exc):
        investigation.unresolved_targets, investigation.project, investigation.close_gaps = self.saved

    def unresolved(self, task_root, budget):
        self.calls.append(("unresolved", "no verdicts" if (budget or {}).get("resolving_verdicts") == [] else "budget"))
        return {"unresolved": list(self.targets), "resolved": [], "context": dict(self.context)}

    def project(self, task_root, dispatch):
        self.calls.append(("project", dispatch))
        if self.on_project:
            self.on_project(Path(task_root))
        return {"added": [], "corrected": [], "skipped": [], "printed": []}

    def close_gaps(self, task_root, why, printed=None, *, budget=None, unresolved=None):
        self.calls.append(("close_gaps", why))
        return [f"EX-{900 + i}" for i in range(self.closes)]

    def names(self) -> list:
        return [c[0] for c in self.calls]


def world(root, env, dispatches=None, stages=None, answered=False, on_run=None):
    """A rig whose controller state, role lines and `run_role` are ours: (driver, moves, launched). `run_role` lands in `moves` too, so the
    order of the dispatch against the close is judged on ONE list."""
    driver, moves, launched = rig(root, env, dispatches)
    state = {"dispatches": dict(dispatches or {})}
    if stages is not None:
        state["stages"] = stages
    driver.controller_state = lambda: state
    driver.role_lines = lambda stage, role, record=None: ["LINES " + json.dumps(record, sort_keys=True)]
    if answered:
        driver.pipeline = lambda: {"gates": {"B": {"status": "approved", "decision": "approve"}}}

    def run_role(stage, role, **kwargs):
        launched.append(dict(kwargs, stage=stage, role=role))
        moves.append(("run_role", kwargs.get("purpose"), kwargs.get("complete")))
        if on_run:
            on_run()
        return "", None
    driver.run_role = run_role
    return driver, moves, launched


def no_failure_story(task_root: Path) -> None:
    write(task_root, report(), {"tests": [], "unresolved": []})


def sha_set(task_root: Path) -> dict:
    return {str(p.relative_to(task_root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(task_root.rglob("*")) if p.is_file()}


CLOSE_TRIPLE = [("stage_done.py", ["--task", TASK, "--stage", "S7", "--status", "done", "--digest", NO_FAILURES, "--no-journal"]),
                ("log_append.py", ["--event", "dispatch_skipped", "--task", TASK, "--reason", "S7: no failures to triage"])]


# ------------------------------------------------------------------------------------------------------ K-M3-10
def k_m3_10_zero_targets_is_todays_close() -> None:
    root, task_root, env = seed(TASK)
    try:
        no_failure_story(task_root)
        driver, moves, launched = rig(root, env)                    # the REAL decision, the REAL (empty) targets
        _v, printed = quietly(driver.stage_S7)
        check_eq("K-M3-10: no failure + 0 targets: the same three calls with the same words as before this change", moves,
                 [("code_only", "S7", NO_FAILURES, ["work/run-report.json"])] + CLOSE_TRIPLE)
        check_eq("K-M3-10: no role, no register file, nothing printed", (launched, (task_root / REGISTER).exists(), printed), ([], False, ""))
    finally:
        harness.cleanup(root)


# ------------------------------------------------------------------------------------------------------ K-M3-11 / F-8
def k_m3_11_dispatch_then_the_close() -> None:
    root, task_root, env = seed(TASK)
    try:
        no_failure_story(task_root)
        ts = [target(1), target(2), target(3)]

        def projected(task):
            put_register(task, *[(t["id"], "code:investigation.project", "add") for t in ts])

        def the_role():     # the analyst records t1, withdraws t3 (no active line is left for it), leaves t2 to the gaps
            put_register(task_root, (ts[0]["id"], "role:qa-failure-analyst", "correct"), (ts[2]["id"], "role:qa-failure-analyst", "withdraw"))
        with Fakes(ts, closes=1, on_project=projected) as fakes:
            driver, moves, launched = world(root, env, on_run=the_role)
            _v, printed = quietly(driver.stage_S7)
        suffix = "; 3 observation(s) the run left open were investigated read-only: 2 recorded by the analyst, 1 left as coverage gaps"
        check_eq("K-M3-11: ONE dispatch with purpose `investigation`, not complete, then the code_only close, the record and the skip",
                 [m[0] for m in moves], ["run_role", "code_only", "stage_done.py", "log_append.py"])
        check_eq("K-M3-11: the dispatch is the investigation, synchronous, with the live gate's record", (moves[0], launched[0]["extra"]),
                 (("run_role", "investigation", False), ['LINES {"purpose": "investigation", "stage": "S7"}']))
        check_eq("K-M3-11: the close is the `s7.no_failures` one: today's words + the suffix, the register in the evidence",
                 moves[1], ("code_only", "S7", NO_FAILURES + suffix, ["work/run-report.json", REGISTER]))
        # t-1991 U3a: `s7_close_places` runs BEFORE the gate and computes the places over `unresolved_targets` (one leading read, the first call)
        check_eq("K-M3-11: the order: the places' read, then inside the gate project, then the targets, then the gaps AFTER the dispatch",
                 fakes.calls, [("unresolved", "budget"), ("project", "S7"), ("unresolved", "budget"), ("unresolved", "budget"), ("close_gaps", WHY_END)])
        check_in("K-M3-11: the dispatch is said", "3 observation(s) the run left open are not investigated; one bounded read-only", printed)
        check_eq("K-M3-11: the skip tail stays (no TRIAGE dispatch happened)", moves[3][1][-1], "S7: no failures to triage")
    finally:
        harness.cleanup(root)


# ------------------------------------------------------------------------------------------------------ K-M3-12 / K-M3-13
def k_m3_12_13_a_member_is_neither_life_nor_triage() -> None:
    root, task_root, env = seed(TASK)
    try:
        both = {"S7-qa-failure-analyst-1": dict(TRIAGE), "S7-qa-failure-analyst-2": dict(PASS, status="accepted")}
        driver, _m, _l = rig(root, env, both)
        check_eq("K-M3-12: the life is the triage, with the accepted investigation member beside it",
                 driver.s7_life(), "S7-qa-failure-analyst-1")
        alone = {"S7-qa-failure-analyst-2": dict(PASS, status="accepted")}
        driver, _m, _l = rig(root, env, alone)
        check_eq("K-M3-12: an accepted investigation alone is no life", driver.s7_life(), "")
        # K-M3-13 + the analyst_done filter: no failure, an accepted investigation member, targets still open
        no_failure_story(task_root)
        with Fakes([target(1)], closes=1) as fakes:
            driver, moves, launched = world(root, env, alone)
            _v, printed = quietly(driver.stage_S7)
        check_eq("K-M3-13: second entry: no second dispatch, the gaps are asked for once with the 'ended before' text",
                 (launched, [c for c in fakes.calls if c[0] == "close_gaps"]), ([], [("close_gaps", WHY_END)]))
        check_eq("K-M3-13: and the close carries it", moves[0][:3], ("code_only", "S7",
                 NO_FAILURES + f"; 1 observation(s) the run left open were not investigated: {WHY_END}"))
        check_not_in("K-M3-12: the accepted investigation is NOT a triage: no re-triage of a story with no failure", "triages again", printed)
        check_eq("K-M3-12: ...and no re-triage record", driver.state.get("s7_retriage"), None)
        # K-M3-19: a RUNNING member: no close, no second dispatch
        running = {"S7-qa-failure-analyst-2": dict(PASS, status="running")}
        with Fakes([target(1)], closes=1) as fakes:
            driver, moves, launched = world(root, env, running)
            _v, printed = quietly(driver.stage_S7)
        check_eq("K-M3-19: a running investigation on re-entry: no close, no second dispatch, nothing recorded", (moves, launched), ([], []))
        check_in("K-M3-19: ...and it is said", "S7: the investigation S7-qa-failure-analyst-2 is running; S7 is not closed over it", printed)
    finally:
        harness.cleanup(root)


# ------------------------------------------------------------------------------------------------------ K-M3-15 / K-M3-16
def k_m3_15_16_halt_and_gate_b() -> None:
    root, task_root, env = seed(TASK)
    try:
        write(task_root, {"execution_status": "env_blocked", "current_results": [], "current_manual_checks": [], "current_totals": {}},
              {"tests": [], "unresolved": []})
        with Fakes([target(1)]) as fakes:
            driver, moves, launched = world(root, env)
            try:
                quietly(driver.stage_S7)
                raised = None
            except Refusal as exc:
                raised = exc
            check_eq("K-M3-15: a halted run is a Refusal before any register write (no project, no gap, no role, no close)",
                     (type(raised).__name__, fakes.calls, moves, (task_root / REGISTER).exists()), ("Refusal", [], [], False))
            quietly(driver.s7_investigation_gate)
            check_eq("K-M3-15 NEGATIVE: the gate called on the same tree (before `failures_to_triage`) DOES project",
                     fakes.names()[:1], ["project"])
    finally:
        harness.cleanup(root)
    root, task_root, env = seed(TASK)
    try:
        no_failure_story(task_root)
        reopened = {"gates": {"B": {"status": "approved", "decision": "approve"}}, "reopened_at": "2026-10-29T10:00:00",
                    "reopened_by_words": "state/words/a.txt"}
        for label, pipeline in (("answered", None), ("answered then reopened by the person's words", reopened)):
            with Fakes([target(1)], closes=1) as fakes:
                driver, moves, launched = world(root, env, answered=True)
                if pipeline:
                    driver.pipeline = lambda: pipeline
                quietly(driver.stage_S7)
            check_eq(f"K-M3-16: gate B {label}: no dispatch, the gaps say so", (launched, [c for c in fakes.calls if c[0] == "close_gaps"]),
                     ([], [("close_gaps", WHY_B)]))
            check_in(f"K-M3-16: ...in the close ({label})", f"were not investigated: {WHY_B}", moves[0][2])
    finally:
        harness.cleanup(root)


# ------------------------------------------------------------------------------------------------------ K-M3-14 / K-M3-28
def k_m3_14_28_repairs_then_the_investigation() -> None:
    rig_ = LimitRig([ROW_1], counted=0, green=("TC-1",))
    try:
        d = rig_.driver
        write(rig_.task_root, report([result("inst_1")]))

        def run_role(stage, role, **kwargs):
            rig_.py_log.append(("run_role", [kwargs.get("purpose")]))
            put_register(rig_.task_root, ("obs-1", "role:qa-failure-analyst", "correct"))
            return "", None
        d.run_role = run_role
        d.role_lines = lambda stage, role, record=None: []
        d.s7_fresh = lambda: True
        with Fakes([target(1)], closes=0, on_project=lambda task: put_register(task, ("obs-1", "code:investigation.project", "add"))):
            raised, _printed = rig_.run()
        names = [s for s, _a in rig_.py_log]
        check_eq("K-M3-14: the repair round first, THEN the investigation, then finalize -> receipt -> record", (raised, rig_.rounds, names),
                 (None, [("qa-automator", ["TC-1"])], ["run_role", "finalize_task.py", "code_only", "stage_done.py"]))
        receipt = next(a for s, a in rig_.py_log if s == "code_only")
        check_in("K-M3-14: a non-empty plan keeps today's sentence, then the suffix", "repairs ended: 1 repaired; 0 left failing by your answer; 0 stopped because a round changed nothing; 1 observation(s)", receipt[1])
        check_eq("K-M3-14: evidence: today's two files + the register", receipt[2], ["work/triage.json", "work/run-report.json", REGISTER])
    finally:
        rig_.done()
    # K-M3-28: no repair row, a pass: the true sentence + suffix, digest + suffix, the register
    rig_ = LimitRig([])
    try:
        d = rig_.driver
        d.run_role = lambda stage, role, **kw: (rig_.py_log.append(("run_role", [kw.get("purpose")])), ("", None))[1]
        d.role_lines = lambda stage, role, record=None: []
        d.saved_done = lambda dispatch: "qa-failure-analyst S7 QA-9 · ok"
        with Fakes([target(1)], closes=1, on_project=lambda task: put_register(task, ("obs-1", "code:investigation.project", "add"))):
            quietly(lambda: d.s7_close([], LIFE))
        receipt = next(a for s, a in rig_.py_log if s == "code_only")
        suffix = "; 1 observation(s) the run left open were investigated read-only: 0 recorded by the analyst, 1 left as coverage gaps"
        check_eq("K-M3-28: no repair row: the sentence is true and the suffix follows; the register is in the evidence", receipt,
                 ["S7", "no failing test to repair; the failure analyst's triage stands" + suffix, ["work/triage.json", "work/run-report.json", REGISTER]])
        done = next(a for s, a in rig_.py_log if s == "stage_done.py")
        check_eq("K-M3-28: the digest carries the suffix too", done[done.index("--digest") + 1],
                 "qa-failure-analyst S7 QA-9 · ok; repairs: fixed=0 not_fixed=0 stopped=0" + suffix)
    finally:
        rig_.done()
    # T-S5 E6 shape with 0 targets: every byte of today's call
    rig_ = LimitRig([ROW_1])
    try:
        rig_.driver.state["s7_rows"] = {LIFE: {"inst_1": {"outcome": "repaired"}}}
        raised, printed = rig_.run()
        receipt = next((a for s, a in rig_.py_log if s == "code_only"), ["", "", []])
        check_eq("K-M3-10 at s7_close: 0 targets: today's reason and evidence, nothing printed by the gate", (raised, receipt[1], receipt[2]),
                 (None, "repairs ended: 1 repaired; 0 left failing by your answer; 0 stopped because a round changed nothing",
                  ["work/triage.json", "work/run-report.json"]))
    finally:
        rig_.done()


# ------------------------------------------------------------------------------------------------------ K-M3-17 / K-M3-26
def k_m3_17_26_the_recovery_roads() -> None:
    root, task_root, env = seed(TASK)
    try:
        no_failure_story(task_root)
        write(task_root, triage={"triage": []})
        driver, _m, _l = rig(root, env)
        driver.role_lines = story_run.Driver.role_lines.__get__(driver)        # the REAL lines for this key
        rec = dict(PASS, id="S7-qa-failure-analyst-2")
        for label, record in (("a saved result", rec), ("the binding wins over a top-level purpose", dict(rec, purpose="repair_verify")),
                              ("a request not yet a record (top-level purpose only)", {"stage": "S7", "purpose": "investigation"})):
            check_eq(f"K-M3-17: completion_for on an investigation record ({label}) is False", driver.completion_for("S7", "qa-failure-analyst", record), False)
        triage_rec = {"stage": "S7", "purpose": "investigation", "request_binding": {"purpose": "repair_verify"}, "id": "S7-qa-failure-analyst-1"}
        check_eq("K-M3-17: a top-level `purpose` overwritten over a triage binding does not make it an investigation (the binding is read)",
                 callable(driver.completion_for("S7", "qa-failure-analyst", triage_rec)), True)
        check_eq("K-M3-17: the live triage call (record {}) keeps today's callable", callable(driver.completion_for("S7", "qa-failure-analyst", {})), True)
        with Fakes([target(1, observed="line one\nline \"two\" é")], context={target(1)["id"]: ["triage ENV_ISSUE (work/evidence/e.txt): our_signal: x"]}):
            lines = driver.role_lines("S7", "qa-failure-analyst", rec)
            plain = driver.role_lines("S7", "qa-failure-analyst", dict(TRIAGE, id="S7-qa-failure-analyst-1"))
            check_eq("K-M3-26: a triage record keeps today's three lines", len(plain), 3)
            check_eq("K-M3-26: ...and so does `record=None`", driver.role_lines("S7", "qa-failure-analyst"), plain)
            check_eq("K-M3-26: an investigation RECORD gets today's three lines first", lines[:3], plain)
            check_in("K-M3-26: ...then the targets and the form note", "Findings to investigate:", lines)
            for stage, role, record, expect in (("S7", "qa-failure-analyst", rec, True), ("S7", "qa-failure-analyst", dict(TRIAGE), False),
                                                ("S7", "qa-runner", rec, False), ("S6", "qa-failure-analyst", rec, False)):
                got = driver.s3_record_lines(stage, role, record)
                check_eq(f"K-M3-26: s3_record_lines({stage}, {role}, {'investigation' if record is rec else 'triage'}): "
                         f"{'the investigation lines' if expect else '[] as today'}", "Findings to investigate:" in "\n".join(got), expect)
                if not expect:
                    check_eq("K-M3-26: ...and nothing else", got, [])
    finally:
        harness.cleanup(root)


# ------------------------------------------------------------------------------------------------------ K-M3-21 / 21b / R
def k_m3_21_the_analysts_finish() -> None:
    root, task_root, env = seed(TASK)
    try:
        write(task_root, triage={"triage": []})
        tail = {"dispatch": "S7 was kept open for one bounded read-only investigation", "wait": "an investigation of them is running",
                "gaps": f"before the close those only the factory has written are recorded as coverage gaps and those the analyst wrote are left as the analyst recorded them ({WHY_END})"}
        cases = (("dispatch", {}), ("wait", {"S7-qa-failure-analyst-2": dict(PASS, status="running")}),
                 ("gaps", {"S7-qa-failure-analyst-2": dict(PASS, status="accepted")}))
        for word, members in cases:
            with Fakes([target(1), target(2)]) as fakes:
                driver, moves, launched = world(root, env, members)
                before = sha_set(task_root)
                got = driver.s7_open_work()
                check_eq(f"K-M3-21: `{word}` -> OpenWork(investigation_pending, the word's reason)", got,
                         story_run.OpenWork("investigation_pending", "the failure analyst finished; 2 observations the run left open are not "
                                            f"investigated yet; {tail[word]}"))
                check_eq(f"K-M3-21b ({word}): the finish only asks: no role, no move, no project, no gap, no file changed",
                         (launched, moves, [c for c in fakes.calls if c[0] in ("project", "close_gaps")], sha_set(task_root) == before),
                         ([], [], [], True))
        with Fakes([]) as fakes:
            driver, moves, launched = world(root, env)
            check_eq("K-M3-21: `none` (no target) -> None, today's road", driver.s7_open_work(), None)
        # the repair rows outrank the investigation
        write(task_root, triage={"triage": [dict(ROW_1)]})
        with Fakes([target(1)]) as fakes:
            driver, moves, launched = world(root, env)
            got = driver.s7_open_work()
            check_eq("K-M3-14: with a repair row the finish says `repairs_pending` and `decision` is not asked", (got.unresolved, fakes.calls),
                     ("repairs_pending", []))
    finally:
        harness.cleanup(root)


def k_w4_r_the_reason_at_300() -> None:
    root, task_root, env = seed(TASK)
    try:
        write(task_root, triage={"triage": []})
        head = "the failure analyst finished; 1 observations the run left open are not investigated yet; before the close those only the factory has written are recorded as coverage gaps and those the analyst wrote are left as the analyst recorded them ()"
        for size in (300, 301):
            why = "w" * (size - len(head))
            with Fakes([target(1)]):
                saved = investigation.decision
                investigation.decision = lambda *a, _w=why: ("gaps", _w)
                try:
                    driver, _m, _l = world(root, env)
                    reason = driver.s7_open_work().reason
                finally:
                    investigation.decision = saved
            if size == 300:
                check_eq("K-W4-R: a reason of exactly 300 characters is whole", (len(reason), "…" in reason, reason.endswith(f"({why})")), (300, False, True))
            else:
                check_eq("K-W4-R: 301 is cut to 300 at most, with the mark and the path of the register",
                         (len(reason) <= 300, reason.endswith("… [list: work/exploratory-findings.jsonl]")), (True, True))
    finally:
        harness.cleanup(root)


# ------------------------------------------------------------------------------------------------------ K-M3-22 / K-W4-C
def k_m3_22_the_gate_before_each_closer() -> None:
    def gated(verdict):
        log = []

        def gate():
            log.append("gate")
            return verdict, " [S]"
        return log, gate
    # closer (i): s7.no_failures
    for verdict in ("proceed", "wait"):
        root, task_root, env = seed(TASK)
        try:
            no_failure_story(task_root)
            driver, moves, launched = world(root, env)
            log, driver.s7_investigation_gate = gated(verdict)
            driver.py = lambda script, *args, **kw: (moves.append((script, list(args))) or (0, ""))
            driver.code_only = lambda stage, reason, evidence: (moves.append(("code_only", reason)) or None)
            quietly(driver.stage_S7)
            expect = [("code_only", NO_FAILURES + " [S]")] if verdict == "proceed" else []
            check_eq(f"K-M3-22 (i) s7.no_failures: the gate runs once, a `{verdict}` {'closes with its suffix' if verdict == 'proceed' else 'returns without a close'}",
                     (log, [m for m in moves if m[0] == "code_only"]), (["gate"], expect))
        finally:
            harness.cleanup(root)
    # closer (ii): s7.pretriaged
    for verdict in ("proceed", "wait"):
        root, task_root, env = seed(TASK)
        try:
            write(task_root, report(manual=[check_row("TC-9")]), {"tests": [], "unresolved": []}, {"schema_version": 2, "triage": []})
            driver, moves, launched = world(root, env)
            log, driver.s7_investigation_gate = gated(verdict)
            with Verdict(True):
                quietly(driver.stage_S7)
            closes = [m for m in moves if m[0] == "code_only"]
            check_eq(f"K-M3-22 (ii) s7.pretriaged: the gate runs once before the close ({verdict})", (log, len(closes)), (["gate"], 1 if verdict == "proceed" else 0))
            if verdict == "proceed":
                check_eq("K-M3-22 (ii): the suffix and the evidence", (closes[0][2].endswith(" [S]"), closes[0][3]),
                         (True, ["work/run-report.json", "work/triage.json"]))
        finally:
            harness.cleanup(root)
    # closer (iii): s7.after_repairs
    for verdict in ("proceed", "wait"):
        rig_ = LimitRig([ROW_1], counted=0, green=("TC-1",))
        try:
            write(rig_.task_root, report([result("inst_1")]))
            log, rig_.driver.s7_investigation_gate = gated(verdict)
            raised, _p = rig_.run()
            names = [s for s, _a in rig_.py_log]
            check_eq(f"K-M3-22 (iii) s7.after_repairs: the gate runs once after the rounds ({verdict}); a `wait` closes nothing",
                     (raised, log, names), (None, ["gate"], ["finalize_task.py", "code_only", "stage_done.py"] if verdict == "proceed" else []))
        finally:
            rig_.done()


def k_w4_c_a_completed_stage() -> None:
    root, task_root, env = seed(TASK)
    try:
        with Fakes([target(1)]) as fakes:
            driver, moves, launched = world(root, env, stages={"S7": {"status": "completed"}})
            got, printed = quietly(driver.s7_investigation_gate)
            check_eq("K-W4-C: S7 completed + targets: proceed with no suffix, nothing projected, decided, dispatched or printed",
                     (got, fakes.calls, moves, launched, printed), (("proceed", ""), [], [], [], ""))
            driver, moves, launched = world(root, env, stages={"S7": {"status": "running"}})
            quietly(driver.s7_investigation_gate)
            check_eq("K-W4-C control: the same state with S7 running does project", fakes.names()[:1], ["project"])
    finally:
        harness.cleanup(root)


# ------------------------------------------------------------------------------------------------------ K-W4-G
def k_w4_g_the_investigation_code_fails() -> None:
    root, task_root, env = seed(TASK)
    try:
        no_failure_story(task_root)
        write(task_root, triage={"triage": []})
        saved_decision = investigation.decision
        saved_module = sys.modules.get("investigation")

        def boom(*a, **kw):
            raise RuntimeError("disk")
        for label in ("decision raises", "investigation is not importable"):
            if label == "decision raises":
                investigation.decision = boom
            else:
                sys.modules["investigation"] = None
            try:
                with Fakes([target(1)]):
                    driver, moves, launched = world(root, env)
                    _v, printed = quietly(driver.stage_S7)
                    finish_word, finish_printed = quietly(driver.s7_open_work)
            finally:
                investigation.decision = saved_decision
                if saved_module is not None:
                    sys.modules["investigation"] = saved_module
            check_eq(f"K-W4-G ({label}): today's close at a closer, byte for byte, no role", (moves, launched),
                     ([("code_only", "S7", NO_FAILURES, ["work/run-report.json"])] + CLOSE_TRIPLE, []))
            check_eq(f"K-W4-G ({label}): ONE printed line at the closer", len([l for l in printed.splitlines() if l.startswith("S7: the investigation")]), 1)
            check_eq(f"K-W4-G ({label}): None at the finish, one printed line", (finish_word, len(finish_printed.splitlines())), (None, 1))
        # project raising: one line, the gate goes on
        def broken_project(task_root_, dispatch):
            raise OSError("locked")
        with Fakes([target(1)], closes=1) as fakes:
            investigation.project = broken_project
            driver, moves, launched = world(root, env)
            _v, printed = quietly(driver.stage_S7)
        check_in("K-W4-G: `project` raising: the line names it", "could not be projected (OSError: locked)", printed)
        check_eq("K-W4-G: ...and the gate went on (decided, dispatched)", (len(launched), "unresolved" in fakes.names()), (1, True))
    finally:
        harness.cleanup(root)


# ------------------------------------------------------------------------------------------------------ K-W4-L
def k_w4_l_the_dispatch_lines() -> None:
    root, task_root, env = seed(TASK)
    try:
        weird = "line one\nline \"two\" é {braces} $HOME"
        ts = [target(1, observed=weird), target(2)]
        with Fakes(ts, context={ts[0]["id"]: ["triage ENV_ISSUE (work/evidence/e.txt): our_signal: stand down"]}) as fakes:
            driver, _m, _l = rig(root, env)
            lines = driver.investigation_lines()
            text = "\n".join(lines)
            check_eq("K-W4-L: the two honesty lines come FIRST", (lines[0].startswith("This dispatch is an INVESTIGATION (purpose `investigation`)"),
                     lines[1].startswith("The triage judge line and `work/judge-triage.json`")), (True, True))
            check_eq("K-W4-L: then the header and one line per target, the observation verbatim", (lines[2], weird in text, text.count("- obs-S6-qa-runner-1-")),
                     ("Findings to investigate:", True, 2))
            check_in("K-W4-L: the triage context of a target is shown as context", "S7 triage said (context, not a verdict): triage ENV_ISSUE", text)
            check_in("K-W4-L / m5: the caps from the budget file (12 / 3 / 20, 4 targets can reach `reproduced`), the probes used so far",
                     "12 probes per pass (used so far: 0), 3 per target, 20 minutes from the first probe; at most 4 targets", text)
            for needle in ("investigation_probe.py\" http --task-root", "investigation_probe.py\" record --task-root", "exploratory_findings.py\" list",
                           "`reproduced` / `not_reproduced` / `environment_event` / `unverified` (k of R) / `unresolved_question` / `coverage_gap`",
                           "never compare it with an expected value", "`scope: []`"):
                check_in(f"K-W4-L: the lines carry {needle[:48]!r}", needle, text)
            for needle in ("no `not_for_repair` rows", "`inputs_read` row [0] for `work/run-report.json` with its `version` and `failures`",
                           "`inputs_read` row [1] the template lists", "the three `claims.*` keys", "`header.verdict`",
                           "one line per item of this dispatch's scope", "every TC-n in scope", "`passed` for the ones that passed",
                           "`unresolved` for the targets above"):
                check_in(f"K-W4-L / FR-38: the form note carries the whole hand-back contract: {needle[:44]!r}", needle, text)
            check_not_in("K-W4-L / F-3: the false refusal clause is gone", "counted as untouched and refused", text)
            # a budget copy P=13 -> 13 probes, 4 targets (13 // 3)
            plugin = root / "plugin-copy"
            (plugin / "references").mkdir(parents=True)
            budget = json.loads((PLUGIN_ROOT / "references" / "investigation-budget.json").read_text(encoding="utf-8"))
            (plugin / "references" / "investigation-budget.json").write_text(json.dumps(dict(budget, probes_per_dispatch=13)), encoding="utf-8")
            driver.plugin = plugin
            check_in("K-W4-L: a budget copy with P=13 says 13 probes (the caps are read from the file, not typed)", "13 probes per pass", "\n".join(driver.investigation_lines()))
            # F-9: the budget broke after the dispatch
            (plugin / "references" / "investigation-budget.json").write_text(json.dumps(dict(budget, probes_per_dispatch=0)), encoding="utf-8")
            fakes.calls.clear()
            broken = "\n".join(driver.investigation_lines())
            check_in("K-W4-L / F-9: a broken budget says every probe is refused", "every probe is refused", broken)
            check_in("K-W4-L / F-9: ...the targets are still listed", "obs-S6-qa-runner-1-1", broken)
            check_eq("K-W4-L / F-9: ...and no verdict resolves anything meanwhile", fakes.calls, [("unresolved", "no verdicts")])
        with Fakes([]):
            driver, _m, _l = rig(root, env)
            none_left = "\n".join(driver.investigation_lines())
            check_in("K-W4-L: zero targets: 'none left', the form still asked for", "Findings to investigate: none left — each target already has an active line; hand back the form", none_left)
            check_in("K-W4-L: ...with the form note", "`scope: []`", none_left)
    finally:
        harness.cleanup(root)


# ------------------------------------------------------------------------------------------------------ K-F1 / m5
def k_f1_the_real_close_gaps_on_a_mixed_state() -> None:
    """t-114 F1: the REAL `project` / `decision` / `close_gaps` on the 14857 snapshot with a budget copy that resolves the ENV_ISSUE rows.
    Kill (named, not run): drop the resolved skip in `investigation.close_gaps` -> the close suffix reads n != k + g and the
    resolved TC-007.. targets are `coverage_gap`s."""
    root, task_root, env = seed(TASK)
    try:
        shutil.copytree(FIXTURE, task_root, dirs_exist_ok=True)
        plugin = root / "plugin-copy"
        (plugin / "references").mkdir(parents=True)
        shipped = json.loads((PLUGIN_ROOT / "references" / "investigation-budget.json").read_text(encoding="utf-8"))
        adding = dict(shipped, resolving_verdicts=list(shipped["resolving_verdicts"]) + ["ENV_ISSUE"])
        (plugin / "references" / "investigation-budget.json").write_text(json.dumps(adding), encoding="utf-8")
        found = investigation.open_targets(task_root, adding)
        waiting = sorted(t["id"] for t in found["unresolved"])
        resolved = sorted(t for t, _ in found["resolved"])
        check("K-F1 driver: the state is mixed (some resolved by the triage, some waiting)", bool(resolved) and len(waiting) > 1, f"{resolved} / {waiting}")
        import exploratory_findings as EF

        def the_role():     # the analyst records the first waiting target; the rest are left to the gaps
            active = EF.read(task_root)["active"][waiting[0]]
            line = {"op": "correct", "kind": active["kind"], "title": active["title"], "statement": "the role's own words",
                    "why_not_a_bug": "the role looked", "evidence_refs": [{"path": active["evidence_refs"][0]["path"]}],
                    "origin": {"dispatch": "S7-qa-failure-analyst-2", "target": waiting[0]},
                    "corrects": {"id": active["id"], "reason": "the role looked at it"}}
            line.update({key: active[key] for key in ("question", "owner_role", "missing_prerequisite") if key in active})
            EF.append(task_root, line, by="S7-qa-failure-analyst-2")
        driver, _moves, launched = world(root, env, on_run=the_role)
        driver.plugin = plugin
        (verdict, suffix), _printed = quietly(driver.s7_investigation_gate)
        n, k, g = len(waiting), 1, len(waiting) - 1
        check_eq("K-F1 driver: one pass, and the close suffix says n = k + g with the REAL close_gaps",
                 (verdict, len(launched), suffix),
                 ("dispatched", 1, f"; {n} observation(s) the run left open were investigated read-only: {k} recorded by the analyst, "
                                   f"{g} left as coverage gaps"))
        gapped = sorted(t for t, line in EF.read(task_root)["active"].items() if line["kind"] == "coverage_gap")
        check_eq("K-F1 driver: only the waiting targets the analyst left are gaps; no triage-resolved target is (a `gap-` record target is the unreadable-record gap)",
                 [t for t in gapped if not t.startswith(investigation.GAP_PREFIX)], waiting[1:])
        check("K-F1 driver: the resolved targets are still recorded, as observations", all(t in EF.read(task_root)["active"] for t in resolved))
    finally:
        harness.cleanup(root)


def k_m5_the_probes_used_so_far() -> None:
    root, task_root, env = seed(TASK)
    try:
        import investigation_probe
        with Fakes([target(1)]):
            driver, _m, _l = rig(root, env)
            saved = investigation_probe.capture_lines
            try:
                investigation_probe.capture_lines = lambda task: [{"n": 1}, {"n": 2}]
                check_in("K-M5 the used probes of the pass are counted (a retry sees the real remainder)", "(used so far: 2)",
                         "\n".join(driver.investigation_lines()))

                def broken(_task):
                    raise ValueError("a damaged captures.jsonl")
                investigation_probe.capture_lines = broken
                check_in("K-M5 a damaged capture file: 'unknown', never a stop", "12 probes per pass (used so far: unknown)",
                         "\n".join(driver.investigation_lines()))
            finally:
                investigation_probe.capture_lines = saved
    finally:
        harness.cleanup(root)


# ------------------------------------------------------------------------------------------------------ K-W4-SR
def k_w4_sr_the_skill_road() -> None:
    text = (PLUGIN_ROOT / "skills" / "qa-story" / "phases" / "s7.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    squashed = " ".join(text.split())
    # the section's rules are rows of design/role-rules.json; this join of the section with the code's `WHY_TEXTS` stays
    check("K-W4-SR: the three whys are the three of `investigation.WHY_TEXTS`, each in the section",
          all(f'"{w}"' in squashed or f"“{w}”" in squashed or w in squashed for w in investigation.WHY_TEXTS[:2]) and "gate B is already decided" in squashed)


def main() -> None:
    k_m3_10_zero_targets_is_todays_close()
    k_m3_11_dispatch_then_the_close()
    k_m3_12_13_a_member_is_neither_life_nor_triage()
    k_m3_15_16_halt_and_gate_b()
    k_m3_14_28_repairs_then_the_investigation()
    k_m3_17_26_the_recovery_roads()
    k_m3_21_the_analysts_finish()
    k_w4_r_the_reason_at_300()
    k_m3_22_the_gate_before_each_closer()
    k_w4_c_a_completed_stage()
    k_w4_g_the_investigation_code_fails()
    k_w4_l_the_dispatch_lines()
    k_f1_the_real_close_gaps_on_a_mixed_state()
    k_m5_the_probes_used_so_far()
    k_w4_sr_the_skill_road()
    finish("test_s7_investigation_driver")


if __name__ == "__main__":
    main()
