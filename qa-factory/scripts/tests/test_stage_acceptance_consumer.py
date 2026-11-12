#!/usr/bin/env python3
"""X7-6 (t-1765, spec node X7-6): the outcome of S6 is accepted by its CONSUMER, the failure analyst of S7; S6 closes by that record.

The controller side is driven on a patched table (S2 plays the author whose acceptor is a role of S3: the same shape as S6 -> S7 without the
gates A/B and the stand); the writer (`stage_done.record_acceptance`) is driven into the consumer's form; the driver pieces (`consumer_awaits`,
`consumer_need_record`, the merged `consumer_*` set) are called on a stub `self`; the reject roads run over the REAL controller (`Rig`, X7-6c). Cases 1-6 of the node:
(1) S6 without a record is not closed, the analyst is dispatched into S7 while S6 awaits, any other role is refused with the door;
(2) `accept` with no quote closes S6; (3) `reject` -> the analyst's finish is `stage_superseded`, the runner's repair is owed;
(4) the repair cap spent -> the conductor's seam (`stage_review_exhausted`), never a code decision; (5) a record for an earlier dispatch of
the author does not count; (6) before the key (no `acceptance_by`) nothing refuses.
"""
import json
import sys
from pathlib import Path
import types
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import acceptance as A  # noqa: E402
import hooklib  # noqa: E402
import stage_done  # noqa: E402
import stage_guard  # noqa: E402
import story_run as SR  # noqa: E402
from event_store import StateConflict  # noqa: E402

import test_controller_stage_acceptance as T  # noqa: E402  (the X2 fixtures: story, dispatch, refused, Patched, quiet, record)
import test_controller_state as BASE  # noqa: E402  (evidence_ref)
import test_fixes_13797 as F  # noqa: E402  (runner: dispatch + accept of a qa-runner packet)
import test_story_step_manual_block as MB  # noqa: E402  (real_story: a real controller through gate A and S5)

AUTHOR, CONSUMER, OTHER = "qa-requirements-tester", "qa-failure-analyst", "qa-test-strategist"
AUTHOR_STAGE = {"id": "S2", "roles": [AUTHOR], "acceptance_by": CONSUMER}
NEXT_STAGE = {"id": "S3", "roles": [CONSUMER, OTHER]}
LATER = "2999-01-01T00:00:00+00:00"       # B-20 F1: a word is honoured only when it is later than the acceptance of the dispatch it passes
BOUND_METHODS = ("consumer_awaits", "consumer_pending", "consumer_person_pass", "accepted_at", "person_pass", "consumer_need_record", "s7_closed_by_scribe", "s7_open_words",
                 "s7_await_scribe", "consumer_close_words")


def stub(**kw):
    """A stub `self` for the driver pieces that read data only: the driver's own `consumer_*` methods bound to it (X7-6c: one merged helper set)."""
    d = SimpleNamespace(CONSUMER_ROUTES=SR.Driver.CONSUMER_ROUTES, **kw)
    for name in BOUND_METHODS:
        if not hasattr(d, name):
            setattr(d, name, types.MethodType(getattr(SR.Driver, name), d))
    return d
FORM = ("inputs_read:\n  - path: work/handoffs/{reviewed}.yaml\n    version: abc\n"
        "header:\n  role: qa-failure-analyst\n  stage: S3\n  window: QA-1\n  verdict: {word}\n{section}")
SECTION = ("stage_acceptance:\n  failure_class: capability\n  quote: \"work/run-report.json#TC-1 has no result row\"\n"
           "  witness_paths: [work/run-report.json]\n")


def awaiting(c, task, did="dA"):
    """The author stops with the open-work word: accepted, stage_complete false, `unresolved` carries the word."""
    receipt = T.dispatch(c, task, did, AUTHOR)
    c.apply("accept", dict(receipt, stage_complete=False, unresolved=A.AWAITS_WORD, reason="S2 awaits the acceptance of the analyst"))


def consumer_state(task):
    return json.loads((task / "pipeline.json").read_text(encoding="utf-8"))


def run() -> None:
    old = hooklib._PROJECT_ROOT_CACHE
    # --- (1) the author stopped awaiting: the consumer is let in, nobody else; `next` names the consumer's stage
    root, task, c = T.story()
    hooklib._PROJECT_ROOT_CACHE = root
    try:
        with T.Patched({"S2": AUTHOR_STAGE, "S3": NEXT_STAGE}):
            check_eq("before the author ran: awaits_acceptance is empty", A.awaits_acceptance(c.state(), "S2"), "")
            awaiting(c, task)
            check_eq("(1) the author's accept with the open-work word keeps S2 open", c.state()["stages"]["S2"]["status"], "pending")
            check_eq("(1) awaits_acceptance (the one reader) names the author's last dispatch", A.awaits_acceptance(c.state(), "S2", consumer_state(task)), "dA")
            check_eq("(1) `next` names S3, the consumer's stage, while S2 awaits", (c.next_action().get("action"), c.next_action().get("stage")),
                     ("prepare_stage", "S3"))
            try:
                T.dispatch(c, task, "dX", OTHER, "S3")
                other = ""
            except StateConflict as exc:
                other = str(exc)
            check_in("(1) any other role into S3 is refused by the controller while S2 awaits", "required prior logical stage incomplete", other)
            text = stage_guard.dispatch_errors(consumer_state(task), "S3", task_root=task, role=OTHER)
            check_in("(1) ... and by the guard, naming the consumer and the door", "S2 awaits the acceptance of qa-failure-analyst", " ".join(text))
            check_in("(1) ... with the command that records the verdict", "--acceptance work/handoffs/", " ".join(text))
            ok = stage_guard.dispatch_errors(consumer_state(task), "S3", task_root=task, role=CONSUMER)
            check_eq("(1) the guard lets the consumer in", [m for m in ok if "S2" in m], [])
            analyst = T.dispatch(c, task, "dN", CONSUMER, "S3")
            check_eq("(1) the analyst is dispatched into S3 while S2 awaits", T.refused(c, analyst, False), "")
            refusal = A.consumer_close_refusal(consumer_state(task), c.state(), "S2")
            check_in("(1) S2 without a record is not closed: stage_done --status done is owed the record", "none stands for dA", refusal)
            # the author's OWN stage_complete=true finish is refused by E-B11 with the consumer's door (E-8), not "the stage critic"
            d = {"stage": "S2", "role": AUTHOR, "id": "dA"}
            said, _ = A.stage_acceptance_refusal(consumer_state(task), d, c.state(), lambda s, e: (e, []))
            check_in("(1) the author's own closing finish names the consumer's dispatch and form", "dispatch `qa-failure-analyst`", said)
            check("(1) ... and does not speak of the stage critic", "stage critic" not in said, said[:200])

            # --- (2) accept with no quote closes S2 (the record is written from the consumer's form)
            handoffs = task / "work" / "handoffs"
            handoffs.mkdir(parents=True, exist_ok=True)
            (handoffs / "dN.yaml").write_text(FORM.format(reviewed="dA", word="ok", section=""), encoding="utf-8")
            code, said = T.quiet(stage_done.record_acceptance, "QA-1", "S2", "work/handoffs/dN.yaml")
            check_eq("(2) a clean `ok` with no quote is recorded (exit 0)", code, 0)
            rec = A.stage_acceptance(consumer_state(task), "S2")
            check_eq("(2) the record: verdict, acceptor, reviewed dispatch, no failure class",
                     (rec["verdict"], rec["acceptor"], rec["reviewed_dispatch"], rec["failure_class"], rec["quote"]), ("accept", CONSUMER, "dA", None, ""))
            check_eq("(2) the stage no longer awaits (the record stands)", A.awaits_acceptance(c.state(), "S2", consumer_state(task)), "")
            check_eq("(2) stage_done --status done is owed nothing", A.consumer_close_refusal(consumer_state(task), c.state(), "S2"), "")
    finally:
        hooklib._PROJECT_ROOT_CACHE = old
        cleanup(root)

    # --- (3) reject: the record is a reject, the stage still awaits, the analyst's finish is `stage_superseded`, the repair is owed
    root, task, c = T.story()
    hooklib._PROJECT_ROOT_CACHE = root
    try:
        with T.Patched({"S2": AUTHOR_STAGE, "S3": NEXT_STAGE}):
            awaiting(c, task)
            c.apply("accept", dict(T.dispatch(c, task, "dN", CONSUMER, "S3"), stage_complete=False, unresolved="stage_superseded", reason="sent back"))
            handoffs = task / "work" / "handoffs"
            handoffs.mkdir(parents=True, exist_ok=True)
            (handoffs / "dN.yaml").write_text(FORM.format(reviewed="dA", word="concerns", section=SECTION), encoding="utf-8")
            code, _ = T.quiet(stage_done.record_acceptance, "QA-1", "S2", "work/handoffs/dN.yaml")
            rec = A.stage_acceptance(consumer_state(task), "S2")
            check_eq("(3) a `concerns` form is recorded as a reject with its class and quote", (code, rec["verdict"], rec["failure_class"]), (0, "reject", "capability"))
            check_eq("(3) a reject does not close: S2 still awaits", A.awaits_acceptance(c.state(), "S2", consumer_state(task)), "dA")
            check_in("(3) ... and stage_done --status done is refused", "none stands for dA", A.consumer_close_refusal(consumer_state(task), c.state(), "S2"))
            # (3)/(4) the analyst's finish through the driver piece: `run_real_completion` (the real controller and ledger, no lambda seam)

            # --- (5) a record for an earlier dispatch of the author does not count
            awaiting(c, task, "dB")          # the runner repaired: dB is now its last accepted dispatch
            T.write_pipeline(task, acceptance={"S2": [T.record("dA", "accept", stage="S2", role=AUTHOR, acceptor=CONSUMER)]})
            check_eq("(5) the accept for dA does not stop S2 awaiting dB", A.awaits_acceptance(c.state(), "S2", consumer_state(task)), "dB")
            check_in("(5) ... nor does it satisfy stage_done --status done", "none stands for dB", A.consumer_close_refusal(consumer_state(task), c.state(), "S2"))
    finally:
        hooklib._PROJECT_ROOT_CACHE = old
        cleanup(root)

    # --- the three S6 close sites and the open-work wrapper, with and without a consumer
    state = {"stages": {"S6": {"status": "pending"}}, "dispatches": {"S6-qa-runner-1": {"id": "S6-qa-runner-1", "stage": "S6", "role": "qa-runner",
                                                                                      "status": "accepted"}}}
    accepted = {"acceptance": {"S6": [{"verdict": "accept", "reviewed_dispatch": "S6-qa-runner-1"}]}}
    for label, consumer, pipe, want in (("no consumer (the world before the key)", "", {}, False), ("a consumer and no record", CONSUMER, {}, True),
                                        ("a consumer and its accept record", CONSUMER, accepted, False)):
        fake = stub(controller_state=lambda: state, pipeline=lambda pipe=pipe: pipe, task="QA-1")
        raised = False

        def sites(fake=fake):
            for site in ("s6_reentry", "s6_reprobed_close", "manual_close"):
                SR.Driver.consumer_need_record(fake, "S6", site)
        try:
            sites() if consumer else without_consumer(sites, "S6")
        except SR.Refusal as exc:
            raised = True
            said = str(exc)
        check_eq(f"close sites, {label}: " + ("refused" if want else "close as today"), raised, want)
        if want:
            check_in("... naming the missing record, the dispatch and the door", "no accept record of qa-failure-analyst stands for S6-qa-runner-1", said)
        awaits = lambda closes, fake=fake: (SR.Driver.consumer_awaits(fake, "S6", closes) if consumer
                                            else without_consumer(lambda: SR.Driver.consumer_awaits(fake, "S6", closes), "S6"))
        out = awaits(True)
        check_eq(f"the runner's finish, {label}: " + ("awaits the acceptance" if consumer else "completes as today"),
                 getattr(out, "unresolved", out), A.AWAITS_WORD if consumer else True)
        check_eq(f"... a non-closing finish is passed through, {label}", awaits(False), False)

    # --- (6) before the key: nothing refuses, nothing awaits (E-2), on the shipped-shape table without the key
    root, task, c = T.story()
    hooklib._PROJECT_ROOT_CACHE = root
    try:
        with T.Patched({"S2": {"id": "S2", "roles": [AUTHOR]}, "S3": NEXT_STAGE}):
            awaiting(c, task)
            check_eq("(6) no acceptance_by: nothing awaits", A.awaits_acceptance(c.state(), "S2", consumer_state(task)), "")
            check_eq("(6) ... stage_done owes no record", A.consumer_close_refusal(consumer_state(task), c.state(), "S2"), "")
            check_eq("(6) ... the closing finish of the author is not refused", A.stage_acceptance_refusal(consumer_state(task), {"stage": "S2", "role": AUTHOR, "id": "dA"}, c.state(), lambda s, e: (e, [])), ("", []))
            check_eq("(6) ... `next` stays on S2", c.next_action().get("stage"), "S2")
            try:
                T.dispatch(c, task, "dN", CONSUMER, "S3")
                said = ""
            except StateConflict as exc:
                said = str(exc)
            check_in("(6) ... the consumer is not let in (as before)", "required prior logical stage incomplete", said)
    finally:
        hooklib._PROJECT_ROOT_CACHE = old
        cleanup(root)
    check_eq("the shipped table: S6 is accepted by the analyst, S7 by the doc scribe, S8 by none (X7-10 closed without code)",
             (A.consumer_of("S6"), A.consumer_of("S7"), A.consumer_of("S8")), (CONSUMER, SCRIBE, ""))
    run_s7()


# --- X7-6b: S7 is accepted by its consumer, the doc scribe of S8 -----------------------------------------------------------------------
SCRIBE, ANALYST_ID = "qa-doc-scribe", "S7-qa-failure-analyst-1"
S7_STATE = {"stages": {"S7": {"status": "pending"}},
            "dispatches": {ANALYST_ID: {"id": ANALYST_ID, "stage": "S7", "role": CONSUMER, "status": "accepted", "unresolved": A.AWAITS_WORD}}}


def s7_record(verdict, reviewed=ANALYST_ID, quote=""):
    return {"stage": "S7", "role": CONSUMER, "acceptor": SCRIBE, "reviewed_dispatch": reviewed, "verdict": verdict,
            "failure_class": None if verdict == "accept" else "data", "quote": quote, "witness_paths": []}


def without_consumer(call, which="S7"):
    """Run `call` in the world before the key: `consumer_of` answers "" for `which`."""
    real = A.consumer_of
    A.consumer_of = lambda stage, table=None: "" if stage == which else real(stage, table)
    try:
        return call()
    finally:
        A.consumer_of = real


def run_s7() -> None:
    old = hooklib._PROJECT_ROOT_CACHE
    # --- S7 (1) the analyst's finish: a finish that WOULD close S7 awaits the scribe; open work and the world before the key pass through
    fake = stub()
    out = SR.Driver.consumer_awaits(fake, "S7", None)
    check_eq("S7 (1) the finish that would close S7 awaits the acceptance of the scribe", (type(out).__name__, out.unresolved), ("OpenWork", A.AWAITS_WORD))
    open_work = SR.OpenWork("repairs_pending", "rows remain")
    check_eq("S7 (1) open work (repairs, investigation) passes through unchanged", SR.Driver.consumer_awaits(fake, "S7", open_work), open_work)
    check_eq("S7 (6/5) before the key (no acceptance_by) the finish closes as today", without_consumer(lambda: SR.Driver.consumer_awaits(fake, "S7", None)), None)
    lam = SR.Driver.completion_for(SimpleNamespace(s7_open_work=lambda: None, consumer_awaits=lambda stage, x: SR.Driver.consumer_awaits(fake, stage, x), state={}), "S7", CONSUMER, {})
    check_eq("S7 (1) completion_for S7 wraps s7_open_work: the callable ends in the awaits word", getattr(lam("d"), "unresolved", None), A.AWAITS_WORD)

    # --- S7 (2) the close sites need the scribe's record of the analyst's LAST dispatch
    for label, consumer_on, pipe, want in (("no consumer (the world before the key)", False, {}, False), ("a consumer and no record", True, {}, True),
                                           ("a consumer and its accept record", True, {"acceptance": {"S7": [s7_record("accept")]}}, False),
                                           ("(3) a record for an EARLIER dispatch of the analyst", True,
                                            {"acceptance": {"S7": [s7_record("accept", reviewed="S7-qa-failure-analyst-0")]}}, True),
                                           ("a reject record", True, {"acceptance": {"S7": [s7_record("reject", quote="triage.json#r1")]}}, True)):
        fake = stub(controller_state=lambda: S7_STATE, pipeline=lambda pipe=pipe: pipe, task="QA-1")
        call = lambda: SR.Driver.consumer_need_record(fake, "S7", "s7_close")
        raised, said = False, ""
        try:
            call() if consumer_on else without_consumer(call)
        except SR.Refusal as exc:
            raised, said = True, str(exc)
        check_eq(f"S7 (2) close site, {label}: " + ("refused" if want else "closes as today"), raised, want)
        if want:
            check_in("S7 (2) ... naming the missing record, the dispatch and the door", f"no accept record of {SCRIBE} stands for {ANALYST_ID}", said)
            check_in("S7 (2) ... and the command that records it", "--stage S7 --acceptance work/handoffs/", said)
    fake = stub(controller_state=lambda: {"stages": {"S7": {"status": "pending"}}, "dispatches": {}}, pipeline=lambda: {}, task="QA-1")
    SR.Driver.consumer_need_record(fake, "S7", "s7_close")
    check("S7 (2) no analyst dispatch ran (S7 closed by code over no failures): nothing is owed", True)
    fake = stub(controller_state=lambda: dict(S7_STATE, stages={"S7": {"status": "completed"}}), pipeline=lambda: {}, task="QA-1")
    SR.Driver.consumer_need_record(fake, "S7", "s7_close")
    check("S7 (2) S7 completed already: nothing is owed", True)

    # --- S7 (2b) (i) the end of the repairs under a consumer with no record: S7 AWAITS (a marker), no refusal, no finalize, no receipt
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    (tmp / "pipeline.json").write_text(json.dumps({"ticket": "QA-1", "stages": {}}), encoding="utf-8")
    calls = []
    state_after_repair = {"stages": {"S7": {"status": "pending"}},
                          "dispatches": {ANALYST_ID: {"id": ANALYST_ID, "stage": "S7", "role": CONSUMER, "status": "accepted", "unresolved": "repairs_pending"}}}
    fake = stub(controller_state=lambda: state_after_repair, pipeline=lambda: json.loads((tmp / "pipeline.json").read_text(encoding="utf-8")),
                task="QA-1", task_root=tmp, s7_investigation_gate=lambda: calls.append("gate") or ("go", ""), s7_fresh=lambda: True,
                s7_open_answer=lambda life: False, close_by_code=lambda *a, **k: calls.append("close"),
                s7_close_places=lambda why: [], s7_gap_reason=lambda *a, **k: "",       # t-1991 U3a: the closer calls them before the gate
                py=lambda *a, **k: calls.append("py") or (0, ""), s7_outcome=lambda l, i: "repaired")
    check_eq("S7 (2b) before the end of the repairs the analyst (finished with repairs_pending) does not await",
             A.awaits_acceptance(state_after_repair, "S7", fake.pipeline()), "")
    SR.Driver.s7_close(fake, [], "life")
    check_eq("S7 (2b) the end of the repairs with no record: no refusal, no close; the reduction ran (B3) once, after the gate", calls, ["gate", "py"])
    check_eq("S7 (2b) ... the marker is the carrier `awaits_acceptance` reads: S7 awaits the analyst's last dispatch",
             (fake.pipeline()["acceptance_awaits"], A.awaits_acceptance(state_after_repair, "S7", fake.pipeline())), ({"S7": ANALYST_ID}, ANALYST_ID))
    calls.clear()
    SR.Driver.s7_close(fake, [], "life")
    check_eq("S7 (2b) ... a second entry keeps the same marker, runs no second reduction and closes nothing", (calls, fake.pipeline()["acceptance_awaits"]),
             (["gate"], {"S7": ANALYST_ID}))
    later = dict(state_after_repair, dispatches=dict(state_after_repair["dispatches"], n2={"id": "n2", "stage": "S7", "role": CONSUMER, "status": "accepted",
                                                                                          "unresolved": "x"}))
    check_eq("S7 (2b) ... a LATER analyst dispatch is not awaited by the old marker (bound to the dispatch)", A.awaits_acceptance(later, "S7", fake.pipeline()), "")
    # (iii) a bare close attempt with nothing awaiting and no record is still refused by consumer_need_record
    bare = stub(controller_state=lambda: state_after_repair, pipeline=lambda: {}, task="QA-1")
    try:
        SR.Driver.consumer_need_record(bare, "S7", "s7_close")
        said = ""
    except SR.Refusal as exc:
        said = str(exc)
    check_in("S7 (2b) (iii) consumer_need_record refuses a bare close with nothing awaiting and no record", f"no accept record of {SCRIBE} stands for {ANALYST_ID}", said)
    # (i, continued) the controller and the guard let the consumer in by the marker
    root, task, c = T.story()
    hooklib._PROJECT_ROOT_CACHE = root
    try:
        with T.Patched({"S2": AUTHOR_STAGE, "S3": NEXT_STAGE}):
            c.apply("accept", dict(T.dispatch(c, task, "dA", AUTHOR), stage_complete=False, unresolved="repairs_pending", reason="repairs"))
            check_eq("S7 (2b) (i) repairs_pending without the marker: the stage does not await, `next` stays",
                     (A.awaits_acceptance(c.state(), "S2", consumer_state(task)), c.next_action().get("stage")), ("", "S2"))
            T.write_pipeline(task, acceptance_awaits={"S2": "dA"})
            check_eq("S7 (2b) (i) with the marker: awaits, and `next` names the consumer's stage",
                     (A.awaits_acceptance(c.state(), "S2", consumer_state(task)), c.next_action().get("stage")), ("dA", "S3"))
            ok = stage_guard.dispatch_errors(consumer_state(task), "S3", task_root=task, role=CONSUMER)
            check_eq("S7 (2b) (i) rule_order lets the consumer in by the marker", [m for m in ok if "S2" in m], [])
            check_eq("S7 (2b) (i) the controller dispatches the consumer by the marker", T.refused(c, T.dispatch(c, task, "dN", CONSUMER, "S3"), False), "")
            bad = " ".join(stage_guard.dispatch_errors(consumer_state(task), "S3", task_root=task, role=OTHER))
            check_in("S7 (2b) (i) any other role is still refused with the door", "S2 awaits the acceptance of qa-failure-analyst", bad)
    finally:
        hooklib._PROJECT_ROOT_CACHE = old
        cleanup(root)
    # (i, continued) after the repairs and the scribe's accept the next entry closes S7 at s7.accepted
    closed = []
    fake2 = stub(controller_state=lambda: state_after_repair, pipeline=lambda: {"acceptance": {"S7": [s7_record("accept")]}}, s7_fresh=lambda: True,
                 state={}, save_state=lambda: None, close_by_code=lambda *a, **k: closed.append((a[0], k.get("site"))) or True)
    SR.Driver.stage_S7(fake2)
    check_eq("S7 (2b) (i) the scribe's accept closes S7 at s7.accepted on the next entry", closed, [("S7", "s7.accepted")])


    # --- S7 (3) the S7 entry closes by the record (site s7.accepted); no record / a reject / an earlier dispatch closes nothing
    for label, pipe, closes in (("an accept for the last dispatch", {"acceptance": {"S7": [s7_record("accept")]}}, True),
                                ("a reject", {"acceptance": {"S7": [s7_record("reject", quote="q")]}}, False),
                                ("an accept for an earlier dispatch", {"acceptance": {"S7": [s7_record("accept", reviewed="S7-qa-failure-analyst-0")]}}, False)):
        closed = []
        fake = stub(controller_state=lambda: S7_STATE, pipeline=lambda pipe=pipe: pipe, s7_fresh=lambda: True, state={}, save_state=lambda: None,
                    close_by_code=lambda *a, **k: closed.append((a[0], k.get("site"), k.get("finalize"))) or True,
                    s7_repairs=lambda: closed.append("repairs"))
        SR.Driver.stage_S7(fake)
        check_eq(f"S7 (3) stage_S7 entry with {label}", closed, [("S7", "s7.accepted", False)] if closes else ["repairs"])
    check_in("S7 (3) `s7.accepted` is a registered code-close site of S7", "s7.accepted", " ".join(SR.CODE_CLOSE_SITES))
    check_eq("S7 (3) ... for S7", SR.CODE_CLOSE_SITES["s7.accepted"][0], "S7")

    # --- S7 (4) the person's `stop` at the open-work question: no record is needed, S7 is not closed, nothing refuses
    class Stop(Exception):
        pass
    seen = []

    def ask(plan, life, decision):
        seen.append("ask")
        raise Stop()
    fake = SimpleNamespace(controller_state=lambda: S7_STATE, pipeline=lambda: {}, task="QA-1", s7_repair_rows=lambda: [], s7_life=lambda: "life",
                           s7_decided=lambda life: {"open_work": {"words_ref": ""}}, s7_plan=lambda rows, life: [], s7_rejudge_rows=lambda: [],
                           s7_open_answer=lambda life: False, s7_open_work_ask=ask, s7_close=lambda *a: seen.append("close"))
    try:
        SR.Driver.s7_repairs(fake)
    except SR.Refusal as exc:
        seen.append("refused: " + str(exc)[:60])
    except Stop:
        pass
    check_eq("S7 (4) the open-work question is asked (a stop holds it): no close, no refusal for a missing record", seen, ["ask"])


    # --- S7 (6) the scribe's form: `stage_acceptance` on `concerns`; a concern about the REPORT (`unresolved`, verdict ok) does not reopen S7
    text = (Path(__file__).resolve().parents[2] / "handoffs" / "s8-scribe-to-gate-b.yaml").read_text(encoding="utf-8")
    check_in("S7 (6) the scribe's form owes `stage_acceptance` on `concerns` (required_when)", "required_when:\n  concerns: [stage_acceptance]", text)
    check_in("S7 (6) ... with the failure class, the quote and the witness paths", "stage_acceptance:\n  failure_class: <spec|capability|data|tooling>\n  quote:", text)
    check_in("S7 (6) ... and the comment says which field carries which", "A concern about your own REPORT\n# belongs in `unresolved`", text)
    report_concern = {"header": {"verdict": "ok"}, "unresolved": [{"id": "report", "reason": "section Not proven is thin"}]}
    rec, problems = A.stage_acceptance_from_form(report_concern, stage="S7", role=CONSUMER, acceptor=SCRIBE, reviewed_dispatch=ANALYST_ID, witness_form="w", at="t")
    check_eq("S7 (6) a report concern with verdict ok is an accept: S7 is not reopened", (rec["verdict"], problems), ("accept", []))
    rec, problems = A.stage_acceptance_from_form({"header": {"verdict": "concerns"}}, stage="S7", role=CONSUMER, acceptor=SCRIBE, reviewed_dispatch=ANALYST_ID,
                                                 witness_form="w", at="t")
    errors = A.stage_acceptance_errors(rec, stage_def=A.stage_def_of("S7"), author_dispatch=ANALYST_ID)
    check("S7 (6) `concerns` with no stage_acceptance section is no record of a reject (class and quote are owed)", bool(errors), errors)

    # --- S7 (7) the world before the key: nothing awaits, `next` stays on the author's stage (X7-6 check 6 with S7 in its table)
    check_eq("S7 (7) the state awaits the scribe with the key", A.awaits_acceptance(S7_STATE, "S7", {}), ANALYST_ID)
    real = A.stage_def_of
    A.stage_def_of = lambda stage, table=None: {k: v for k, v in real(stage, table).items() if k != "acceptance_by"}
    try:
        check_eq("S7 (7) without `acceptance_by` nothing awaits", A.awaits_acceptance(S7_STATE, "S7", {}), "")
        check_eq("S7 (7) ... and stage_done owes no record", A.consumer_close_refusal({}, S7_STATE, "S7"), "")
    finally:
        A.stage_def_of = real
    check_in("S7 (7) with the key stage_done --status done names the missing record", f"none stands for {ANALYST_ID}", A.consumer_close_refusal({}, S7_STATE, "S7"))


# --- X7-6c: the reject roads over the REAL controller (the lambda stubs of `budget_or_none`, `rework` and `stage_review_exhausted` hid B1 and B2) ----
class Rig:
    """A driver (`SR.Driver` methods bound to a namespace) over a REAL story and the REAL `Controller`: `prepare` and `rework` run in-process
    (`build_rework_request` + `apply dispatch`, as the CLI does); only the conductor's seam (`no_move`), the role run (`run_role`), the defect
    trace (`py_trace`) and the record WRITER's file I/O are recorded stand-ins. `budget_or_none`, `repair_budget`, `rework`,
    `stage_review_exhausted` and every `consumer_*` method are the driver's own."""
    BOUND = ("budget_or_none", "repair_budget", "rework", "stage_review_exhausted", "consumer_awaits", "consumer_pending", "consumer_person_pass", "accepted_at", "person_pass",
             "consumer_need_record", "consumer_counts", "consumer_exhausted", "consumer_completion", "consumer_settled", "stage_verdict_known",
             "s7_closed_by_scribe", "s7_open_words", "s7_await_scribe", "s7_close", "stage_scope", "s7_open_answer", "s7_investigation_gate", "owe_row",
             "consumer_close_words")

    def __init__(self, dispositions=None):
        self.root = temp_dir("qa-x76c-")
        self.c = MB.real_story(self.root, dispositions or MB.MIXED_7)
        self.log, self.cmds = [], []
        d = self.d = SimpleNamespace(task="QA-9", task_root=self.root, state_dir=self.root / "state", CONSUMER_ROUTES=SR.Driver.CONSUMER_ROUTES,
                                     last_dispatch="", state={}, save_state=lambda: None, plugin=SCRIPTS.parent, stages=self.stages,
                                     project=self.root)       # `owe_row` files the finding of a pass by the person's word (B-20)
        d.controller, d.controller_state, d.pipeline = self.controller, self.c.state, self.pipeline
        d.no_move = lambda state: self.log.append(("seam", state.get("text"), state.get("call"))) or "SEAM"
        d.py_trace = lambda *a, **k: self.log.append(("trace", a))
        d.run_role = lambda stage, role, **k: self.log.append(("run", stage, role, k.get("scope"), (k.get("rework") or {}).get("id"))) or ("digest", {})
        d.stage_acceptance_write = self.write_record
        d.py = self.py
        d.stop_if_drained = d.count_launch = lambda: None      # t-2133: `rework` asks the scheduler (TR3-6); no chains run in this rig
        d.on_chain = SR.Driver.on_chain
        d.s7_close_places, d.s7_gap_reason = (lambda why: []), (lambda *a, **k: "")     # t-1991 U3a: `s7_close` calls them before the gate
        for name in self.BOUND:
            setattr(d, name, types.MethodType(getattr(SR.Driver, name), d))

    stages = staticmethod(lambda: {s["id"]: s for s in hooklib.load_ref_json("stages.json")["stages"]})

    def pipeline(self):
        return json.loads((self.root / "pipeline.json").read_text(encoding="utf-8-sig"))

    def controller(self, op, *args, input_data=None):
        if op == "prepare":
            return json.loads(json.dumps(self.c.prepare(input_data), default=str))
        assert op == "rework", op
        a = dict(zip(args[::2], args[1::2]))
        self.log.append(("rework-call", a.get("--cases")))
        try:
            request = self.c.build_rework_request(a["--stage"], a["--role"], (a.get("--cases") or "").split(","), a["--reason"], a["--purpose"],
                                                  [""], a["--cause"])
            self.c.apply("dispatch", dict(request))
        except (ValueError, StateConflict) as exc:
            raise SR.Refusal(f"controller rework (exit 2):\n{exc}") from exc
        return {"request": request}

    def py(self, script, *args, **kw):
        """`stage_done.py --acceptance` and `finalize_task.py` as recorded commands; the acceptance goes to the REAL writer's record shape."""
        self.cmds.append((script,) + args)
        if script == "stage_done.py" and "--acceptor" in args:
            at = lambda k: args[args.index(k) + 1]
            self.append_record(dict(stage=at("--stage"), role=A.stage_def_of(at("--stage"))["roles"][0], acceptor=A.DRIVER_ACCEPTOR,
                                    reviewed_dispatch=A.stage_author_dispatch(self.c.state(), A.stage_def_of(at("--stage"))),
                                    verdict="accept", failure_class=None, quote=at("--quote"), witness_paths=[], at="t"))
        return 0, ""

    def append_record(self, record):
        pipeline = self.pipeline()
        pipeline.setdefault("acceptance", {}).setdefault(record["stage"], []).append(record)
        (self.root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")

    def write_record(self, stage, dispatch):
        import handoff
        data = handoff.parse((self.root / "work" / "handoffs" / f"{dispatch}.yaml").read_text(encoding="utf-8")).data
        stage_def = A.stage_def_of(stage)
        record, problems = A.stage_acceptance_from_form(data, stage=stage, role=stage_def["roles"][0], acceptor=A.consumer_of(stage),
                                                        reviewed_dispatch=stage_done.reviewed_author_dispatch(data, self.c.state(), stage_def),
                                                        witness_form="w", at="t")
        assert record and not problems, problems
        self.append_record(record)

    def author(self, dispatch_id, kind, scope, stage="S6", awaits=True):
        """An accepted author dispatch (the runner, `kind` manual|automation) that stopped with the awaits word."""
        extra = dict(unresolved=A.AWAITS_WORD, reason="awaits the consumer") if awaits else {}
        return F.runner(self.c, self.root, dispatch_id, kind, scope, False, **extra)

    def consumer_form(self, dispatch_id, reviewed, word, stage_of_reviewed_role="qa-runner"):
        (self.root / "work" / "handoffs").mkdir(parents=True, exist_ok=True)
        text = FORM.format(reviewed=reviewed, word=word, section=SECTION if word == "concerns" else "")
        (self.root / "work" / "handoffs" / f"{dispatch_id}.yaml").write_text(text, encoding="utf-8")

    def consumer(self, dispatch_id, stage, role, reviewed, word, unresolved=A.AWAITS_WORD):
        """The consumer's accepted dispatch (it works in the consumer stage) with its form naming the reviewed author dispatch."""
        self.c.apply("dispatch", {"id": dispatch_id, "stage": stage, "role": role, "scope": ["TC-1"], "input_hash": dispatch_id, "budget": {},
                                  "known_paths": {}, "idempotency_key": "d-" + dispatch_id})
        self.consumer_form(dispatch_id, reviewed, word)
        extra = dict(unresolved=unresolved, reason="sent back") if unresolved else {}
        self.c.apply("accept", dict({"id": dispatch_id, "status": "accepted", "stage_complete": False,
                                     "evidence_refs": [BASE.evidence_ref(self.root, dispatch_id + ".txt", dispatch_id)],
                                     "idempotency_key": "a-" + dispatch_id}, **extra))
        self.d.last_dispatch = dispatch_id


def reject_record(stage, role, acceptor, reviewed):
    return dict(stage=stage, role=role, acceptor=acceptor, reviewed_dispatch=reviewed, verdict="reject", failure_class="capability",
                quote="work/run-report.json#TC-1 has no result row", witness_paths=[], at="t")


def run_real_s6() -> None:
    """B1, B2, M1, M2 for S6 (the runner, judged by the failure analyst) over the real controller."""
    old = hooklib._PROJECT_ROOT_CACHE
    rig = Rig()
    hooklib._PROJECT_ROOT_CACHE = rig.root
    try:
        manual = ["TC-2", "TC-3", "TC-4", "TC-5", "TC-6"]
        rig.author("S6-qa-runner-1", "automation", ["TC-1"])
        rig.author("S6-qa-runner-2", "manual", manual)
        rig.author("S6-qa-runner-3", "manual", ["TC-7"])
        c, d = rig.c, rig.d
        check_eq("S6 fixture: the runner's last dispatch awaits its consumer", A.awaits_acceptance(c.state(), "S6", rig.pipeline()), "S6-qa-runner-3")
        check_eq("S6 B1: the real `prepare` carries a repair budget for the runner of the reviewed dispatch (the first round: counted 0, cap 2)",
                 (d.consumer_counts("S6", "S6-qa-runner-3"), [e for e in rig.log if e[0] == "trace"]), ((0, 2), []))
        # --- B1 + B2: a reject with a round left reaches `rework` ONCE, over ONE half, with no `--cases`
        rig.append_record(reject_record("S6", "qa-runner", CONSUMER, "S6-qa-runner-3"))
        rig.consumer("S7-qa-failure-analyst-1", "S7", CONSUMER, "S6-qa-runner-3", "concerns", unresolved=A.SUPERSEDED_WORD)
        rig.log.clear()
        done = d.consumer_settled("S6", c.state(), "S6-qa-runner-3", True, ran=True)
        runs = [e for e in rig.log if e[0] == "run"]
        check_eq("S6 B1: a reject with a round left is reworked (no seam, no defect trace)", (done, [e[0] for e in rig.log if e[0] in ("seam", "trace")]), (True, []))
        check_eq("S6 B2: the call carries no `--cases`; the runner reworks the REVIEWED manual block, one half",
                 ([e[1] for e in rig.log if e[0] == "rework-call"], [(e[1], e[2], e[3]) for e in runs]), ([None], [("S6", "qa-runner", ["TC-7"])]))
        new = c.state()["dispatches"]["S6-qa-runner-4"]
        check_eq("S6 B2: the new dispatch reworks the reviewed one, is a manual block of its cases, and counts as round 1",
                 (new["rework_of"], new["execution_kind"], new["manual_case_ids"], d.consumer_counts("S6", "S6-qa-runner-3")), ("S6-qa-runner-3", "manual", ["TC-7"], (1, 2)))
        rig.author("S6-qa-runner-4", "manual", ["TC-7"], awaits=False)          # the round ran and stopped (accepted)
        try:
            c.build_rework_request("S6", "qa-runner", ["TC-1", "TC-7"], "the union the old call sent")
            union = ""
        except ValueError as exc:
            union = str(exc)
        check_in("S6 B2 control: the old call (both halves as one scope) IS refused by the controller", "one packet runs one half", union)
        # the automated half: reject for runner-1 -> rework of the automation packet (kind from the reviewed dispatch)
        rig.append_record(reject_record("S6", "qa-runner", CONSUMER, "S6-qa-runner-1"))
        rig.log.clear()
        d.consumer_settled("S6", c.state(), "S6-qa-runner-1", True, ran=True)
        auto = c.state()["dispatches"]["S6-qa-runner-5"]
        check_eq("S6 B2: the automation half is reworked over its own scope", (auto["rework_of"], auto["execution_kind"], auto["scope"]),
                 ("S6-qa-runner-1", "automation", ["TC-1"]))
        # --- B1: the cap counts ROUNDS: the second reject of the automation half is round 2; the third finds none left, and says so truthfully
        rig.author("S6-qa-runner-5", "automation", ["TC-1"], awaits=True)
        check_eq("S6 B1: after one rework the round count of the automation half is 1", d.consumer_counts("S6", "S6-qa-runner-1"), (1, 2))
        rig.append_record(reject_record("S6", "qa-runner", CONSUMER, "S6-qa-runner-5"))
        rig.log.clear()
        d.consumer_settled("S6", c.state(), "S6-qa-runner-5", True, ran=True)
        rig.author("S6-qa-runner-6", "automation", ["TC-1"], awaits=True)
        check_eq("S6 B1: two rounds spent on the half", d.consumer_counts("S6", "S6-qa-runner-1"), (2, 2))
        rig.append_record(reject_record("S6", "qa-runner", CONSUMER, "S6-qa-runner-6"))
        rig.log.clear()
        done = d.consumer_settled("S6", c.state(), "S6-qa-runner-6", True, ran=True)
        seams = [e for e in rig.log if e[0] == "seam"]
        check("S6 B1: no round left -> the ONE seam, with the true words (the consumer named, no stage critic) and no new runner",
              done and seams and "qa-failure-analyst rejected S6 and no repair round is left" in str(seams[0][1]) and "stage critic" not in str(seams[0][1])
              and not [e for e in rig.log if e[0] == "run"], seams[:1])
        # --- M1: the conductor sends the runner back for one more round: the seam is not told "no move"

        def conductor(state):
            rig.log.append(("seam", state.get("text"), state.get("call")))
            if state.get("call") is not False and len(c.state()["dispatches"]) == before:
                c.apply("dispatch", {"id": "S6-qa-runner-7", "stage": "S6", "role": "qa-runner", "execution_kind": "automation", "scope": ["TC-1"],
                                     "input_hash": "s6", "budget": {}, "known_paths": {}, "idempotency_key": "d-7", "rework_of": "S6-qa-runner-6",
                                     "repair_cause": "question_answer", "reason": "the person's words"})      # one more round on words, the conductor's move
            return "SEAM"
        d.no_move = conductor
        rig.consumer("S7-qa-failure-analyst-2", "S7", CONSUMER, "S6-qa-runner-6", "concerns", unresolved=A.SUPERSEDED_WORD)
        before = len(c.state()["dispatches"])
        out = d.stage_review_exhausted("S6", "qa-runner", "S7-qa-failure-analyst-2", reject_record("S6", "qa-runner", CONSUMER, "S6-qa-runner-6"),
                                       "work/handoffs/S7-qa-failure-analyst-2.yaml")
        check_eq("S6 M1: the conductor's rework dispatch (made after the CONSUMER's dispatch, a dispatch of the next stage) is seen: OpenWork, no fallback",
                 (type(out).__name__, out.unresolved), ("OpenWork", "stage_in_repair"))
        # --- M2: a consumer dispatch of an EARLIER life is not this handoff's judge
        old_judge = A.consumer_dispatch(c.state(), "S7", CONSUMER, "S6-qa-runner-7")
        check_eq("S6 M2: no consumer dispatch after the newest runner dispatch -> none (the earlier analysts are other lives)", old_judge, "")
        c.apply("accept", {"id": "S6-qa-runner-7", "status": "accepted", "stage_complete": False, "unresolved": A.AWAITS_WORD, "reason": "awaits",
                           "evidence_refs": [BASE.evidence_ref(rig.root, "r7.txt", "r7")], "idempotency_key": "a-7"})
        rig.consumer("S7-qa-failure-analyst-3", "S7", CONSUMER, "S6-qa-runner-7", "ok")
        check_eq("S6 M2: the superseded analysts are no judge; the accepted one that came AFTER the reviewed dispatch is",
                 (A.consumer_dispatch(c.state(), "S7", CONSUMER, "S6-qa-runner-3"), A.consumer_dispatch(c.state(), "S7", CONSUMER, "S6-qa-runner-7")),
                 ("S7-qa-failure-analyst-3", "S7-qa-failure-analyst-3"))
        rig.log.clear()
        c.apply("dispatch", {"id": "S6-qa-runner-8", "stage": "S6", "role": "qa-runner", "execution_kind": "automation", "scope": ["TC-1"],
                             "input_hash": "s6", "budget": {}, "known_paths": {}, "idempotency_key": "d-8", "rework_of": "S6-qa-runner-7",
                             "repair_cause": "question_answer", "reason": "the person's words"})
        c.apply("accept", {"id": "S6-qa-runner-8", "status": "accepted", "stage_complete": False, "unresolved": A.AWAITS_WORD, "reason": "awaits",
                           "evidence_refs": [BASE.evidence_ref(rig.root, "r8.txt", "r8")], "idempotency_key": "a-8"})
        d.stage_acceptance_write = lambda *a: log_error.append(a)
        log_error = []
        check_eq("S6 M2: a runner dispatch NEWER than every consumer dispatch (a rework by a person's words): no stale record is written, the consumer is asked for (False)",
                 (d.consumer_settled("S6", c.state(), "S6-qa-runner-8", True), log_error), (False, []))
    finally:
        hooklib._PROJECT_ROOT_CACHE = old
        cleanup(rig.root)


def s7_world():
    """A real story with S6 closed and the analyst's first triage accepted (repairs pending); `mark_awaiting` is the driver's marker."""
    rig = Rig(["automate"])
    rig.append_record(dict(stage="S6", role="qa-runner", acceptor=CONSUMER, reviewed_dispatch="S6-qa-runner-1", verdict="accept", failure_class=None,
                           quote="", witness_paths=[], at="t"))
    check_eq("S7 fixture: the runner's finish completes S6 over the analyst's record", F.runner(rig.c, rig.root, "S6-qa-runner-1", "automation", ["TC-1"], True), "")
    cases = ["TC-1"]
    rig.c.apply("dispatch", {"id": ANALYST_ID, "stage": "S7", "role": CONSUMER, "scope": cases, "input_hash": "s7", "budget": {}, "known_paths": {},
                             "idempotency_key": "d-an1"})
    rig.c.apply("accept", {"id": ANALYST_ID, "status": "accepted", "stage_complete": False, "unresolved": "repairs_pending", "reason": "repairs",
                           "evidence_refs": [BASE.evidence_ref(rig.root, "an1.txt", "an1")], "idempotency_key": "a-an1"})
    return rig


def put_pipeline(rig, pipeline):
    (rig.root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")


def accept_open(rig, dispatch):
    rig.c.apply("accept", {"id": dispatch, "status": "accepted", "stage_complete": False, "unresolved": A.AWAITS_WORD, "reason": "awaits",
                           "evidence_refs": [BASE.evidence_ref(rig.root, dispatch + ".txt", dispatch)], "idempotency_key": "a-" + dispatch})


def run_real_s7() -> None:
    """B1, B2 (S7), B3, M3, M4 over the real controller; the S6 half of B1/B2/M1/M2 is `run_real_s6` (one table, one helper set)."""
    old = hooklib._PROJECT_ROOT_CACHE
    rig = s7_world()
    hooklib._PROJECT_ROOT_CACHE = rig.root
    try:
        c, d = rig.c, rig.d
        # --- B3: S7 goes AWAITING only after the reduction of the current life; a stale triage opens no marker
        order, fresh = [], [False]
        d.s7_investigation_gate = lambda: ("proceed", "")
        d.s7_fresh = lambda: fresh[0]

        def py(script, *args, **kw):
            order.append((script, A.awaits_acceptance(c.state(), "S7", rig.pipeline())))     # what the scribe's door says AT the moment of the command
            return 0, ""
        d.py = py
        d.s7_outcome = lambda life, ident: "repaired"
        d.saved_done = lambda dispatch: ""
        d.close_by_code = lambda *a, **k: order.append(("close", k.get("site"))) or True
        SR.Driver.s7_close(d, [], "life")
        check_eq("S7 B3: not fresh after the finalize: finalize ran, NO marker was written, the scribe is not let in, nothing closed",
                 (order, rig.pipeline().get("acceptance_awaits"), A.awaits_acceptance(c.state(), "S7", rig.pipeline())), ([("finalize_task.py", "")], None, ""))
        order.clear()
        fresh[0] = True
        SR.Driver.s7_close(d, [], "life")
        check_eq("S7 B3: fresh: `finalize_task.py` ran BEFORE the marker (the scribe's door was shut at that moment), then the marker, and no close",
                 (order, rig.pipeline().get("acceptance_awaits"), A.awaits_acceptance(c.state(), "S7", rig.pipeline())),
                 ([("finalize_task.py", "")], {"S7": ANALYST_ID}, ANALYST_ID))
        order.clear()
        SR.Driver.s7_close(d, [], "life")
        check_eq("S7 B3: a second entry with the marker bound to this dispatch runs no second finalize", order, [])
        # `s7.accepted` only CLOSES: no second finalize
        accept_record = dict(stage="S7", role=CONSUMER, acceptor=SCRIBE, reviewed_dispatch=ANALYST_ID, verdict="accept", failure_class=None, quote="",
                             witness_paths=[], at="t")
        rig.append_record(accept_record)
        order.clear()
        d.close_by_code = lambda *a, **k: order.append((k.get("site"), k.get("finalize"))) or True
        check_eq("S7 B3: the scribe's accept closes at s7.accepted with finalize False", (d.s7_closed_by_scribe(c.state()), order), (True, [("s7.accepted", False)]))
        pipeline = rig.pipeline()
        pipeline["acceptance"].pop("S7")
        put_pipeline(rig, pipeline)
        # --- M4: an accepted read-only INVESTIGATION is not the author of the triage: not the awaited dispatch, not the reviewed one
        c.apply("dispatch", {"id": "S7-qa-failure-analyst-inv", "stage": "S7", "role": CONSUMER, "scope": [], "input_hash": "inv", "budget": {},
                             "known_paths": {}, "purpose": "investigation", "idempotency_key": "d-inv"})
        c.apply("accept", {"id": "S7-qa-failure-analyst-inv", "status": "accepted", "stage_complete": False, "unresolved": "investigation_pending",
                           "reason": "read-only pass", "evidence_refs": [BASE.evidence_ref(rig.root, "inv.txt", "inv")], "idempotency_key": "a-inv"})
        check_eq("S7 M4: with an accepted investigation after it, the triage is still the author and still the awaited dispatch",
                 (A.stage_author_dispatch(c.state(), A.stage_def_of("S7")), A.awaits_acceptance(c.state(), "S7", rig.pipeline())), (ANALYST_ID, ANALYST_ID))
        from controller import repair_ledger
        check_eq("S7 finding 2: the investigation dispatch spends NO round (counted 0 of 2; the triage is the opener)",
                 (d.consumer_counts("S7", ANALYST_ID), "S7-qa-failure-analyst-inv" in [r["id"] for r in repair_ledger(c.state()["dispatches"], c.state()["dispatches"][ANALYST_ID])["rounds"]]),
                 ((0, 2), False))
        check_eq("S7 m2: the superseded word is read as a TOKEN of `unresolved`, never inside the reason or a quote",
                 (A.unresolved_has_word({"unresolved": "stage_superseded"}, A.SUPERSEDED_WORD),
                  A.unresolved_has_word({"unresolved": ["x"], "reason": "stage_superseded"}, A.SUPERSEDED_WORD),
                  A.unresolved_has_word({"unresolved": "repairs_pending", "reason": "x"}, A.SUPERSEDED_WORD)), (True, False, False))
        # --- B1 + B2 (S7): the scribe rejects; a round left -> the analyst is reworked over its own scope, no `--cases`, no defect, no seam
        rig.consumer("S8-qa-doc-scribe-1", "S8", "qa-doc-scribe", ANALYST_ID, "concerns", unresolved=A.SUPERSEDED_WORD)
        rig.append_record(reject_record("S7", CONSUMER, SCRIBE, ANALYST_ID))
        d.s7_open_work = lambda: None
        rig.log.clear()
        done = d.consumer_settled("S7", c.state(), ANALYST_ID, True, ran=True)
        reworked = [dd for dd in c.state()["dispatches"].values() if dd.get("rework_of") == ANALYST_ID]
        check_eq("S7 B1/B2: reject with a round left: the analyst is reworked ONCE (no seam, no defect), over the scope of the reviewed dispatch",
                 (done, [e[0] for e in rig.log if e[0] in ("seam", "trace")], [e[1] for e in rig.log if e[0] == "rework-call"], len(reworked),
                  reworked[0]["scope"] if reworked else None), (True, [], [None], 1, ["TC-1"]))
        check_eq("S7 B1: that rework is round 1 of 2 in the ledger the controller keeps", d.consumer_counts("S7", ANALYST_ID), (1, 2))
        # the reworked analyst's finish is read AFTER the role wrote: nothing owed -> it awaits the scribe again
        check_eq("S7 B1: ... its finish awaits again when nothing is owed",
                 getattr(d.CONSUMER_ROUTES["S7"]["rework_complete"](d)("x"), "unresolved", None), A.AWAITS_WORD)
        # --- the cap spent: the next reject goes to the seam, truthfully
        second = reworked[0]["id"]
        accept_open(rig, second)
        rig.append_record(reject_record("S7", CONSUMER, SCRIBE, second))
        rig.consumer("S8-qa-doc-scribe-2", "S8", "qa-doc-scribe", second, "concerns", unresolved=A.SUPERSEDED_WORD)
        d.consumer_settled("S7", c.state(), second, True, ran=True)
        third = [dd["id"] for dd in c.state()["dispatches"].values() if dd.get("rework_of") == second][0]
        accept_open(rig, third)
        rig.append_record(reject_record("S7", CONSUMER, SCRIBE, third))
        rig.consumer("S8-qa-doc-scribe-3", "S8", "qa-doc-scribe", third, "concerns", unresolved=A.SUPERSEDED_WORD)
        rig.log.clear()
        done = d.consumer_settled("S7", c.state(), third, True, ran=True)
        seams = [e for e in rig.log if e[0] == "seam"]
        check("S7 B1: two rounds spent -> the ONE seam saying so, naming the scribe, and no further analyst",
              done and seams and "qa-doc-scribe rejected S7 and no repair round is left" in str(seams[0][1]) and not [e for e in rig.log if e[0] == "run"], seams[:1])
        # --- M3 (P13): the person's word moves the factory - a waiver, and the `close` answer, never a refusal
        latest = A.stage_author_dispatch(c.state(), A.stage_def_of("S7"))
        d.py = rig.py
        pipeline = rig.pipeline()
        pipeline["acceptance"].pop("S7")
        put_pipeline(rig, pipeline)
        try:
            d.consumer_need_record("S7", "s7_close")
            text = ""
        except SR.Refusal as exc:
            text = str(exc)
        check_in("S7 M3 control: with no word of a person the close is refused, and the refusal names the waiver door", "waiver.py", text)
        pipeline["stage_overrides"] = [{"stage": "S7", "match": "stage acceptance", "decision": "I accept the triage as it is", "at": LATER, "by": "human"}]
        put_pipeline(rig, pipeline)
        d.consumer_need_record("S7", "s7_close")
        rec = A.stage_acceptance(rig.pipeline(), "S7")
        check_eq("S7 M3: a waiver of `stage acceptance` passes the close site (no refusal) and is RECORDED as a driver accept `by: person`, with their words",
                 (rec["acceptor"], rec["verdict"], rec["reviewed_dispatch"] == latest, rec["quote"]), ("driver", "accept", True, "by: person - I accept the triage as it is"))
        check_eq("S7 M3: ... so the stage no longer awaits and `s7_await_scribe` leaves the close to go on",
                 (A.awaits_acceptance(c.state(), "S7", rig.pipeline()), SR.Driver.s7_await_scribe(d)), ("", False))
        # the `close` answer of the open-work question: recorded BEFORE any scribe wait; the close goes on by the person's word
        pipeline = rig.pipeline()
        pipeline["acceptance"].pop("S7")
        pipeline.pop("stage_overrides", None)
        put_pipeline(rig, pipeline)
        (rig.root / "state" / "words").mkdir(parents=True, exist_ok=True)
        (rig.root / "state" / "words" / "ans.txt").write_text("close it now, I will read the triage myself", encoding="utf-8")
        d.state = {"s7_open_work": {"life": {"token": "close", "words_file": "state/words/ans.txt"}}}
        order.clear()
        d.close_by_code = lambda *a, **k: order.append(("close", k.get("site"))) or True
        SR.Driver.s7_close(d, [], "life")
        rec = A.stage_acceptance(rig.pipeline(), "S7")
        check_eq("S7 M3: the recorded `close` answer: a driver accept by the person's words, the close by code goes on, nobody is refused",
                 (rec["acceptor"], rec["quote"], order), ("driver", "by: person - close it now, I will read the triage myself", [("close", "s7.after_repairs")]))
        # a waiver also takes a scribe's REJECT as the accept (the report is written, the scribe's S7 word is moot)
        pipeline = rig.pipeline()
        pipeline["acceptance"]["S7"] = [reject_record("S7", CONSUMER, SCRIBE, latest)]
        pipeline["stage_overrides"] = [{"stage": "S7", "match": "stage acceptance", "decision": "go on", "at": LATER, "by": "human"}]
        put_pipeline(rig, pipeline)
        rig.log.clear()
        check_eq("S7 M3: a scribe's reject under a person's waiver is not reworked: the pass is the accept, no round, no seam",
                 (d.consumer_settled("S7", c.state(), latest, True, ran=True), [e[0] for e in rig.log if e[0] in ("run", "seam")],
                  A.stage_acceptance(rig.pipeline(), "S7")["acceptor"]), (False, [], "driver"))
    finally:
        hooklib._PROJECT_ROOT_CACHE = old
        cleanup(rig.root)


def run_real_completion() -> None:
    """The consumer's FINISH (`consumer_completion`) over the real controller and its repair ledger: the checks (3), (4), the unknown word, the
    accept as a VALUE, the S7 twins (5) - one helper now, so one set of checks per road for both stages (X7-6c)."""
    old = hooklib._PROJECT_ROOT_CACHE
    for stage, role, mk in (("S6", "qa-runner", None), ("S7", CONSUMER, None)):
        rig = Rig(["automate"]) if stage == "S6" else s7_world()
        hooklib._PROJECT_ROOT_CACHE = rig.root
        try:
            c, d = rig.c, rig.d
            consumer_stage, consumer_role = ("S7", CONSUMER) if stage == "S6" else ("S8", "qa-doc-scribe")
            first = "S6-qa-runner-1" if stage == "S6" else ANALYST_ID
            if stage == "S6":
                rig.author(first, "automation", ["TC-1"])
            else:
                put_pipeline(rig, dict(rig.pipeline(), acceptance_awaits={"S7": ANALYST_ID}))      # the driver's marker: the scribe is let in
            label = f"{stage} finish"
            rig.consumer("X-1", consumer_stage, consumer_role, first, "wibble", unresolved=A.SUPERSEDED_WORD)
            check_eq(f"{label}: an unknown verdict word goes to the seam, not to a guess, and no record is written",
                     (d.consumer_completion(stage, "INNER")("d"), A.stage_acceptance(rig.pipeline(), stage) is None or stage == "S7"), ("SEAM", True))
            rig.consumer_form("X-1", first, "concerns")
            out = d.consumer_completion(stage, "INNER")("d")
            check_eq(f"{label}: reject with a round left: the consumer's finish is OpenWork stage_superseded (its work is stale), the record written first",
                     (type(out).__name__, out.unresolved, A.stage_acceptance(rig.pipeline(), stage)["verdict"]), ("OpenWork", A.SUPERSEDED_WORD, "reject"))
            check_eq(f"{label}: ... and the repair budget was read from the real ledger only now, with no defect filed", [e[0] for e in rig.log if e[0] == "trace"], [])
            rig.consumer_form("X-1", first, "ok")
            check_eq(f"{label}: an accept record: the finish goes on as the consumer's own completion (a VALUE, a callable is called)",
                     (d.consumer_completion(stage, "INNER")("d"), d.consumer_completion(stage, lambda x: "own:" + x)("d")), ("INNER", "own:d"))
            # two rounds spent through the real `rework` -> the next reject finds none left: the ONE seam, and the conductor's accept makes the finish go on
            tip = first
            for n in (1, 2):
                rig.append_record(reject_record(stage, role, A.consumer_of(stage), tip))
                d.s7_open_work = lambda: None
                d.consumer_settled(stage, c.state(), tip, False)
                tip = [dd["id"] for dd in c.state()["dispatches"].values() if dd.get("rework_of") == tip][0]
                (rig.author(tip, "automation", ["TC-1"]) if stage == "S6" else accept_open(rig, tip))
            check_eq(f"{label}: two rounds spent: the real ledger says (2, 2)", d.consumer_counts(stage, tip), (2, 2))
            rig.consumer("X-2", consumer_stage, consumer_role, tip, "concerns", unresolved=A.SUPERSEDED_WORD)      # the consumer judges the newest dispatch
            rig.log.clear()
            out = d.consumer_completion(stage, "INNER")("d")
            check_eq(f"{label}: reject on the last round: the conductor's seam is asked, its answer is the finish", (out, [e[0] for e in rig.log if e[0] == "seam"][:1]),
                     ("SEAM", ["seam"]))

            def accepts(state):
                if state.get("call") is not False:
                    rig.append_record(dict(stage=stage, role=role, acceptor=A.DRIVER_ACCEPTOR, reviewed_dispatch=tip, verdict="accept", failure_class=None,
                                           quote="the gap, in words", witness_paths=[], at="t"))
                return "SEAM"
            d.no_move = accepts
            check_eq(f"{label}: ... and after the conductor's own accept the finish goes on as the consumer's completion",
                     d.consumer_completion(stage, lambda x: "own:" + x)("d"), "own:d")
            d.no_move = lambda state: rig.log.append(("seam", state.get("text"), state.get("call"))) or "SEAM"
            d.consumer_counts = lambda *a: (None, None)
            pipeline = rig.pipeline()
            pipeline["acceptance"][stage].pop()      # the driver accept: the consumer's reject stands again
            put_pipeline(rig, pipeline)
            rig.log.clear()
            out = d.consumer_completion(stage, "INNER")("d")
            said = [e[1] for e in rig.log if e[0] == "seam"]
            check(f"{label}: a budget nobody can read is NOT «no round is left» (FR-41): the seam is told so", out == "SEAM" and said and "could not count" in str(said[0]), said[:1])
        finally:
            hooklib._PROJECT_ROOT_CACHE = old
            cleanup(rig.root)


if __name__ == "__main__":
    run()
    run_real_completion()
    run_real_s6()
    run_real_s7()
    finish("test_stage_acceptance_consumer")
