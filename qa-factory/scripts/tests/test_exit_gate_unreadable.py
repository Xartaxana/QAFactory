#!/usr/bin/env python3
"""RH1-5 B3: the exit gate reads the third state of a detector. E1-E3 (every unreadable is kept, a clean neighbour turns
nothing into a pass, a mixed set keeps both), E9 AT and BEYOND the timeout, E10 (did not start), E12-class records (D10-D12,
D16), K9 (the named word passes, `*` and the bare word do not), E25 (the two meanings of the word), D13 (the gate that
crashes exits 0 with a receipt and a signal), the adviser (a signal, never a block)."""
import contextlib
import io
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, finish  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import detector_verdict as DV  # noqa: E402
import exit_gate as EG  # noqa: E402
import hooklib  # noqa: E402

ROLE = "qa-automator"
REAL_RUN = subprocess.run


class Done:
    def __init__(self, code, out="", err=""):
        self.returncode, self.stdout, self.stderr = code, out, err


def with_run(fake, fn):
    saved = EG.subprocess.run
    EG.subprocess.run = fake
    try:
        return fn()
    finally:
        EG.subprocess.run = saved


def gates(scripts, advice=()):
    EG.detector_gates = lambda stage="": {ROLE: list(scripts)}
    EG.advice_detectors = lambda agent="", stage="": set(advice)


def main() -> None:
    real_gates, real_advice, real_signal = EG.detector_gates, EG.advice_detectors, hooklib.person_signal
    signals = []
    hooklib.person_signal = lambda event, kind, text, **kw: signals.append((kind, text)) or True
    try:
        # E1 / E3: one unreadable among clean neighbours stays an error
        gates(["a.py", "b.py"])
        fake = lambda cmd, **kw: Done(3, DV.unreadable_line("boom")) if cmd[-1].endswith("a.py") else Done(0, "fine")
        errs = with_run(fake, lambda: EG.detector_errors(ROLE))
        check_eq("E3: a.py unreadable, b.py clean: ONE record, kind unreadable, named by script",
                 [(e.kind, e.script) for e in errs], [("unreadable", "a.py")])
        check_in("the text starts with the script and `unreadable - `", "a.py: unreadable - boom - the factory's own defect", errs[0])
        # E1: all unreadable: every record stays (none vanishes because of its neighbour)
        errs = with_run(lambda cmd, **kw: Done(9, "", "Traceback"), lambda: EG.detector_errors(ROLE))
        check_eq("E1: both detectors unreadable: two records, one per script", sorted(e.script for e in errs), ["a.py", "b.py"])
        # E8 at the gate: a clean exit with the marker is refused
        errs = with_run(lambda cmd, **kw: Done(0, DV.unreadable_line("late")), lambda: EG.detector_errors(ROLE))
        check_eq("E8: exit 0 with the marker is unreadable at the gate too", len(errs), 2)
        # E10: did not start
        def no_start(cmd, **kw):
            raise OSError("no interpreter")
        errs = with_run(no_start, lambda: EG.detector_errors(ROLE))
        check_in("E10: a detector that did not start is unreadable with the type", "did not start (OSError)", errs[0])
        check_eq("E10: ...kind unreadable, not a finding of the role", errs[0].kind, "unreadable")
        # E9 AT and BEYOND the border, with a real wait
        EG.DETECTOR_TIMEOUT_S = 1
        def stub(seconds):
            return lambda cmd, **kw: REAL_RUN([sys.executable, "-c", f"import time; time.sleep({seconds})"], capture_output=True,
                                              text=True, timeout=kw.get("timeout"))
        gates(["a.py"])
        errs = with_run(stub(0.2), lambda: EG.detector_errors(ROLE))
        check_eq("E9 AT: a detector that finishes in time is read by the contract (exit 0 and silent: clean)", list(errs), [])
        t0 = time.time()
        errs = with_run(stub(2), lambda: EG.detector_errors(ROLE))
        check_in("E9 BEYOND: a detector past the border is unreadable 'timed out after 1 s'", "timed out after 1 s", errs[0] if errs else "")
        check("E9: ...and it did not wait for the 2 s run", time.time() - t0 < 1.9, str(time.time() - t0))
        EG.DETECTOR_TIMEOUT_S = 120
        # the adviser: a signal, never a block
        gates(["sizing.py"], advice=["sizing.py"])
        del signals[:]
        # GW1-10: the adviser runs AFTER the verdict, through `advice_errors`; `detector_errors` leaves it alone
        errs = with_run(lambda cmd, **kw: Done(3, DV.unreadable_line("sizing crashed")), lambda: EG.detector_errors(ROLE))
        check_eq("adviser: `detector_errors` does not run it (no error, no signal)", (errs, list(signals)), ([], []))
        errs = with_run(lambda cmd, **kw: Done(3, DV.unreadable_line("sizing crashed")), lambda: EG.run_advisers(ROLE))
        check_eq("adviser: unreadable adds NO error (returns nothing blocking, E-X2-2c)", errs, [])
        check_eq("adviser: ...and leaves one gate_unreadable signal marked advice", [(k, "advice" in t) for k, t in signals], [("gate_unreadable", True)])
        # GW1-10 F-3: exit 1 WITH output is not dropped: one signal, still no block (AR-28)
        del signals[:]
        errs = with_run(lambda cmd, **kw: Done(1, "junk"), lambda: EG.run_advisers(ROLE))
        # t-1815 F5 (the Lead's rule, E-A15): an adviser that FAILS (non-zero exit, timeout, unreadable) never blocks the stop; its failure is
        # ONE signal to the person, and what it printed is filed as advice
        check_eq("adviser F-3: exit 1 with stdout blocks nothing", errs, [])
        check_eq("adviser F-3: ...and its failure is ONE gate_unreadable signal marked advice", [(k, "advice" in t) for k, t in signals],
                 [("gate_unreadable", True)])
        del signals[:]
        # exit 1 AFTER printing records: the records are advice, the failure is one signal, no block
        out = "ADVICE — 1\nsizing: the story is large\n"
        errs = with_run(lambda cmd, **kw: Done(1, out + "junk"), lambda: EG.run_advisers(ROLE))
        check_eq("adviser F-5: printed records AND exited 1: no block, one signal", (errs, [(k, "advice" in t) for k, t in signals]),
                 ([], [("gate_unreadable", True)]))
        del signals[:]
        with_run(lambda cmd, **kw: Done(0, ""), lambda: EG.run_advisers(ROLE))
        check_eq("adviser F-3 (control): a clean adviser leaves no signal", list(signals), [])
        gates(["sizing.py"])
        errs = with_run(lambda cmd, **kw: Done(3, DV.unreadable_line("sizing crashed")), lambda: EG.detector_errors(ROLE))
        check_eq("adviser (control): the same crash without the declaration blocks", len(errs), 1)

        # witness: D8
        real_wg, real_root = EG.witness_gates, EG.artifact_root
        tmp = Path(tempfile.mkdtemp(prefix="qa-eg-wit-"))
        (tmp / "T-1").mkdir()
        (tmp / "T-1" / "w.json").write_text("{}", encoding="utf-8")
        EG.witness_gates = lambda: {ROLE: "w.json"}
        EG.artifact_root = lambda: tmp
        try:
            errs = with_run(no_start, lambda: EG.witness_errors(ROLE, "T-1"))
            check_eq("D8: check_witness that did not start is unreadable (not [])", [(e.kind, e.script) for e in errs], [("unreadable", "check_witness.py")])
            errs = with_run(lambda cmd, **kw: Done(0, "ok"), lambda: EG.witness_errors(ROLE, "T-1"))
            check_eq("D8 (control): a clean check_witness is []", errs, [])
        finally:
            EG.witness_gates, EG.artifact_root = real_wg, real_root
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

        # D10 / D12 / D16: the records of the other readers
        import question_register
        real_drift = question_register.readiness_drift
        question_register.readiness_drift = lambda root: (_ for _ in ()).throw(ValueError("x"))
        real_isdir = EG.is_story_folder
        EG.is_story_folder = lambda *a: True
        try:
            errs = EG.answered_question_errors("qa-requirements-tester", "T-1")
        finally:
            question_register.readiness_drift = real_drift
            EG.is_story_folder = real_isdir
        check_eq("D10: the drift check raising is an unreadable record named question_register", [(e.kind, e.script) for e in errs], [("unreadable", "question_register")])
        real_rd = EG.RD.check
        EG.RD.check = lambda *a, **k: (_ for _ in ()).throw(ValueError("x"))
        real_ld = EG._live_dispatch
        EG._live_dispatch = lambda *a, **k: None
        real_sid, real_scope = EG._stage_id, EG._scope_of
        EG._stage_id = lambda agent, task="": "S5"
        EG._scope_of = lambda *a, **k: {}
        try:
            errs = EG.digest_errors(ROLE, "T-1", "some digest")
        finally:
            EG.RD.check, EG._live_dispatch, EG._stage_id, EG._scope_of = real_rd, real_ld, real_sid, real_scope
        check_eq("D12: RD.check raising is an unreadable record named role_digest", [(e.kind, e.script) for e in errs], [("unreadable", "role_digest")])
        import grounding_table
        real_check = grounding_table.check
        grounding_table.check = lambda root: (_ for _ in ()).throw(ValueError("x"))
        try:
            errs = EG._window_one_errors(Path("."))
        finally:
            grounding_table.check = real_check
        check_eq("D16: GT raising is an unreadable record named grounding_table.py", [(e.kind, e.script) for e in errs], [("unreadable", "grounding_table.py")])

        # K9: the words
        rec = EG.unreadable_record("s5_precheck.py", "boom")
        def judged(match):
            pipe = {"stage_overrides": [{"stage": "S5", "match": match, "decision": "go on", "at": "t"}]}
            blocking, passed = EG.judge_words([rec], pipe, "S5")
            return len(blocking), len(passed)
        check_eq("K9: the named word passes (and is recorded as passed)", judged("s5_precheck.py: unreadable"), (0, 1))
        check_eq("K9: the star does NOT pass", judged("*"), (1, 0))
        check_eq("K9: the bare word `unreadable` does NOT pass", judged("unreadable"), (1, 0))
        check_eq("K9: a part of the script name (`precheck.py: unreadable`) does NOT pass", judged("precheck.py: unreadable"), (1, 0))
        check_eq("K9: another script's word does NOT pass", judged("sizing.py: unreadable"), (1, 0))
        check_eq("class of the record", EG.word_class(rec), "named_only")
        # E25: the refused `unmigrated` whose cause is the word unreadable keeps its class
        unm = DV.Record("x.py: unmigrated detector output", script="x.py", kind="unmigrated", refused=DV.UNREADABLE)
        check_eq("E25: unmigrated with refused='unreadable' stays `refused`, not named_only", EG.word_class(unm), "refused")
        # E1/E2 mix through all_errors-level judge: unreadable + finding both stay
        finding = DV.Record("a.py: [c 1] bad", script="a.py")
        blocking, _p = EG.judge_words([rec, finding], {}, "S5")
        check_eq("E2: unreadable and a finding both stay in blocking", len(blocking), 2)

        # D13: the gate that crashes exits 0, writes an unreadable receipt, leaves a signal
        recorded = []
        saved = {k: getattr(EG, k) for k in ("read_event", "subagent_type", "_identity", "handoff_digest", "awaiting_source_review",
                                             "_existing", "_record", "all_errors", "role_name")}
        EG.read_event = lambda: {"session_id": "s1", "agent_type": ROLE}
        EG.subagent_type = lambda e: ROLE
        EG.role_name = lambda raw: ROLE
        EG._identity = lambda e, a: ("key", {"task": "T-1"})
        EG.handoff_digest = lambda e: ""
        EG.awaiting_source_review = lambda a, t: False
        EG._existing = lambda k: {}
        EG._record = lambda key, scope, status, errors=None, **kw: recorded.append((status, [str(x) for x in (errors or [])]))
        EG.all_errors = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("gate bug"))
        del signals[:]
        try:
            try:
                EG.main()
                code = "returned"
            except SystemExit as exc:
                code = exc.code
        finally:
            for k, v in saved.items():
                setattr(EG, k, v)
        check_eq("D13: a gate that crashes exits 0", code, 0)
        check_eq("D13: the receipt says unreadable", recorded[0][0], "unreadable")
        check_in("D13: ...naming the crash", "RuntimeError", recorded[0][1][0])
        check_eq("D13: and one gate_unreadable signal", [k for k, _t in signals], ["gate_unreadable"])

        def drive(all_errors, stop_active=False):
            """`main()` with the receipt, the journal and the saved list stubbed: (exit code, receipts, signals, stderr)."""
            saved_main = {k: getattr(EG, k) for k in ("read_event", "subagent_type", "_identity", "handoff_digest",
                                                      "awaiting_source_review", "_existing", "_record", "all_errors",
                                                      "role_name", "journal_gate", "_render_saved", "_findings_path")}
            recorded_here, err = [], io.StringIO()
            EG.read_event = lambda: {"session_id": "s1", "agent_type": ROLE, "stop_hook_active": stop_active}
            EG.subagent_type = lambda e: ROLE
            EG.role_name = lambda raw: ROLE
            EG._identity = lambda e, a: ("key", {"task": "T-1"})
            EG.handoff_digest = lambda e: ""
            EG.awaiting_source_review = lambda a, t: False
            EG._existing = lambda k: {}
            EG._record = lambda key, scope, status, errors=None, **kw: recorded_here.append((status, [str(x) for x in (errors or [])])) or {}
            EG.journal_gate = lambda *a, **k: None
            EG._render_saved = lambda errors, f, t, label: ("TEXT", None)
            EG._findings_path = lambda a, t: None
            EG.all_errors = all_errors
            del signals[:]
            try:
                try:
                    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                        EG.main()
                    code = "returned"
                except SystemExit as exc:
                    code = exc.code
            finally:
                for k, v in saved_main.items():
                    setattr(EG, k, v)
            return code, recorded_here, list(signals), err.getvalue()

        unread_rec = EG.unreadable_record("sizing.py", "boom")
        plain = DV.Record("a.py: [c 1] bad", script="a.py")
        # N4: only unreadable records in `blocking`: the role is not woken (exit 0, receipt unreadable, one signal)
        code, got, sigs, err_text = drive(lambda *a, **k: ([unread_rec], []))
        check_eq("N4: unreadable-only blocking: exit 0 (no wake-up)", code, 0)
        check_eq("N4: ...receipt `unreadable`, not `blocked`", [s for s, _e in got], ["unreadable"])
        check_eq("N4: ...one gate_unreadable signal", [k for k, _t in sigs], ["gate_unreadable"])
        check("N4: ...and the role is told nothing to repair (no HANDOFF BLOCKED text)", "HANDOFF BLOCKED" not in err_text, err_text)
        code, got, sigs, err_text = drive(lambda *a, **k: ([plain], []))
        check_eq("N4 control: one plain finding still blocks, exit 2, receipt blocked", (code, [s for s, _e in got]), (2, ["blocked"]))
        code, got, sigs, err_text = drive(lambda *a, **k: ([unread_rec, plain], []))
        check_eq("N4 mixed: blocks (exit 2) on the author's finding only", (code, [s for s, _e in got]), (2, ["blocked"]))
        check_eq("N4 mixed: ...the receipt holds the finding, not the unreadable record", got[0][1], [str(plain)])
        check_in("N4 mixed: ...the text says the unreadable one is not the role's", "Not yours", err_text)
        check_eq("N4 mixed: ...and the person gets the signal", [k for k, _t in sigs], ["gate_unreadable"])
        # N5: the re-entry's crash writes the signal and the receipt, not stderr alone
        def boom(*a, **k):
            raise RuntimeError("gate bug on re-entry")
        code, got, sigs, err_text = drive(boom, stop_active=True)
        check_eq("N5: a crash of all_errors on the re-entry exits 0", code, 0)
        check_eq("N5: ...writes the receipt `unreadable`", [s for s, _e in got], ["unreadable"])
        check_eq("N5: ...and the signal gate_unreadable", [k for k, _t in sigs], ["gate_unreadable"])
        code, got, sigs, err_text = drive(lambda *a, **k: ([unread_rec], []), stop_active=True)
        check_eq("N4 re-entry: unreadable-only is the same road (receipt unreadable, one signal)",
                 ([s for s, _e in got], [k for k, _t in sigs]), (["unreadable"], ["gate_unreadable"]))

        # N1: the S2 register checks' unreadable records are NAMED by the file S2 owns, so S2 keeps them and S5 does not
        question_register.readiness_drift = lambda root: (_ for _ in ()).throw(ValueError("x"))
        EG.is_story_folder = lambda *a: True
        try:
            drift = EG.answered_question_errors("qa-requirements-tester", "T-1")
        finally:
            question_register.readiness_drift = real_drift
            EG.is_story_folder = real_isdir
        import validate_artifacts as va
        tmp2 = Path(tempfile.mkdtemp(prefix="qa-eg-reg-"))
        (tmp2 / "T-1").mkdir()
        (tmp2 / "T-1" / "requirements-register.md").write_text("---\ncreated: 2026-10-28\n---\n# r\n", encoding="utf-8")
        real_art, real_claims, real_dated, real_bug = EG.artifact_root, va.check_behaviour_claims, va._oracle_dated, EG.bug_audit_errors
        EG.artifact_root = lambda: tmp2
        va.check_behaviour_claims = lambda *a, **k: (_ for _ in ()).throw(ValueError("x"))
        va._oracle_dated = lambda *a, **k: True
        EG.bug_audit_errors = lambda *a, **k: []
        try:
            claims = [e for e in EG.collect_errors("T-1") if getattr(e, "kind", "") == "unreadable"]
        finally:
            EG.artifact_root, va.check_behaviour_claims, va._oracle_dated, EG.bug_audit_errors = real_art, real_claims, real_dated, real_bug
            import shutil
            shutil.rmtree(tmp2, ignore_errors=True)
        check_eq("N1: D11 crash gives one unreadable record named by the register file",
                 [(e.script, str(e).startswith("requirements-register.md: ")) for e in claims], [("requirements-register claims", True)])
        check_eq("N1: D10 record is named by the readiness file, script kept for the door",
                 [(e.script, str(e).startswith("requirements-readiness.json: ")) for e in drift], [("question_register", True)])
        check_in("N1: ...and the door text still names the script's unreadable", "question_register: unreadable - ", drift[0])
        real_collect = EG.collect_errors
        EG.collect_errors = lambda *a, **k: list(drift) + list(claims)
        try:
            s2 = EG.scoped_errors("qa-requirements-tester", "T-1")
            s5 = EG.scoped_errors("qa-automator", "T-1")
        finally:
            EG.collect_errors = real_collect
        check_eq("N1: an S2 agent keeps both records (its stop is blocked by the crash)",
                 sorted(e.script for e in s2 if e.kind == "unreadable"), ["question_register", "requirements-register claims"])
        check_eq("N1 control: an S5 agent keeps neither (an S2 crash does not block S5)", [e for e in s5 if getattr(e, "kind", "") == "unreadable"], [])
        for word in ("question_register: unreadable", "requirements-register claims: unreadable"):
            pipe = {"stage_overrides": [{"stage": "S2", "match": word, "decision": "go on", "at": "t"}]}
            _b, passed_now = EG.judge_words([drift[0], claims[0]], pipe, "S2")
            check_eq(f"N1: the named word `{word}` passes exactly its own record", len(passed_now), 1)
    finally:
        EG.detector_gates, EG.advice_detectors, hooklib.person_signal = real_gates, real_advice, real_signal
    finish("test_exit_gate_unreadable")


if __name__ == "__main__":
    main()
