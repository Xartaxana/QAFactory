#!/usr/bin/env python3
"""B-20 (t-1988 N3, N4): a code close refused because an EARLIER stage is still open gets a door, and the close says who accepted.

N3: `Driver.code_close` reads the behind stage from `controller.code_close_facts` (never from the refusal's words) and
    (a) the earlier stage waits for nobody (an accept record stands, or nothing to accept): ONE silent retry per controller revision
        (`CODE_CLOSE_IDLE_CAP` is the bound: refusal 1 retries, refusal 2 at the SAME revision asks) - AT and BEYOND the bound;
    (b) the earlier stage awaits its consumer role (no record): the question `code_close.behind` offers `go on` / `retry` / `stop`,
        and `go on` records the pass through `consumer_person_pass` (driver accept + finding), then the close runs again;
    another conflict (running work), an unreadable controller state and a refusal that is not the behind message keep today's road.
N4: see the second half of this file.

Fast: a real in-process Driver over a seeded temp project, the controller state and the script runner are stubs; no subprocess driver.
Runs under pytest and as `python -B scripts/tests/test_code_close_behind.py`.
"""
import atexit
import contextlib
import copy
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check_eq, cleanup, finish  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import acceptance as A  # noqa: E402
import story_run as SR  # noqa: E402
from story_run_common import driver_for, human_broken, seed  # noqa: E402

TASK = "QA-9"
RUNNER_1, ANALYST_1 = "S6-qa-runner-1", "S7-qa-failure-analyst-1"
REFUSED = '{"error": "required prior logical stage incomplete"}'


def eq(name, got, want):
    assert check_eq(name, got, want), f"{name}: expected {want!r}, got {got!r}"


def stage_states(**status):
    """S0-S5 completed (the closed history), then the given statuses by stage id."""
    out = {f"S{i}": {"status": "completed"} for i in range(6)}
    out.update({k: {"status": v} for k, v in status.items()})
    return out


def dispatch_row(ident, stage, role):
    return {"id": ident, "stage": stage, "role": role, "status": "accepted", "unresolved": A.AWAITS_WORD}


class rig:
    """`with rig() as r`: a seeded project, a real Driver, a stubbed controller state (`r.ctl`) and script runner (`r.cmds`)."""

    SHARED: dict = {}          # ONE seeded project for the file (a seed runs a script and a controller: ~10 s); every rig resets what it touched

    def __enter__(self):
        if not self.SHARED:
            root, task_root, env = seed(TASK)
            driver = driver_for(root, env, TASK)
            self.SHARED.update(root=root, task_root=task_root, driver=driver, state=copy.deepcopy(driver.state),
                               pipeline=(task_root / "pipeline.json").read_text(encoding="utf-8"))
            atexit.register(cleanup, root)
        self.root, self.task_root, self.d = (self.SHARED[k] for k in ("root", "task_root", "driver"))
        (self.task_root / "pipeline.json").write_text(self.SHARED["pipeline"], encoding="utf-8")
        self.d.state = copy.deepcopy(self.SHARED["state"])
        self.cmds = []
        self.ctl = {"revision": 7, "stages": stage_states(S6="pending", S7="pending"), "dispatches": {}}
        self.d.controller_state = lambda: self.ctl
        self.d.py = self.py
        for name in ("consumer_person_pass", "close_by_code", "s7_fresh"):          # a test that replaced a method of the shared driver does not leak it
            self.d.__dict__.pop(name, None)
        return self

    def __exit__(self, *exc):
        return False

    # --- the world -----------------------------------------------------------------------------------------------
    def awaiting(self, stage="S6"):
        """The author of `stage` stopped with the awaits word (S6: the runner; S7: the analyst)."""
        row = dispatch_row(RUNNER_1, "S6", "qa-runner") if stage == "S6" else dispatch_row(ANALYST_1, "S7", "qa-failure-analyst")
        self.ctl["dispatches"][row["id"]] = row
        return row["id"]

    def pipeline(self):
        return json.loads((self.task_root / "pipeline.json").read_text(encoding="utf-8"))

    def put_record(self, stage, reviewed, acceptor, quote=""):
        pipeline = self.pipeline()
        pipeline.setdefault("acceptance", {}).setdefault(stage, []).append(
            dict(stage=stage, role=A.stage_def_of(stage)["roles"][0], acceptor=acceptor, reviewed_dispatch=reviewed, verdict="accept",
                 failure_class=None, quote=quote, witness_paths=[], at="t"))
        (self.task_root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")

    def py(self, script, *args, check=False, expect=""):
        args = tuple(str(a) for a in args)
        self.cmds.append((script,) + args)
        if script == "stage_done.py" and "--acceptor" in args:         # the one writer of a stage acceptance record
            at = lambda key: args[args.index(key) + 1]                  # noqa: E731
            self.put_record(at("--stage"), Path(at("--acceptance")).stem, at("--acceptor"), at("--quote"))
        return 0, ""

    # --- the moves -----------------------------------------------------------------------------------------------
    def refuse(self, stage="S7", site="s7.accepted", text=REFUSED, step="receipt"):
        return SR.Refusal(f"controller code_only (exit 2):\n{text}", close={"site": site, "stage": stage, "step": step})

    def close(self, refusal):
        """`Driver.code_close(refusal)`: ('outcome', the returned word, the printed lines) or ('person', the Person, the printed lines)."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                return "outcome", self.d.code_close(refusal), out.getvalue()
            except SR.Person as person:
                return "person", person, out.getvalue()

    def defects(self):
        return [c for c in self.cmds if c[0] == "log_append.py" and "defect_found" in c]

    def findings(self):
        return [c for c in self.cmds if c[0] == "project_decisions.py"]

    def rec(self, stage="S7"):
        return self.d.state["code_close"][stage]


# --- N3 -------------------------------------------------------------------------------------------------------------------------------------
def test_n3_1_a_standing_record_is_one_silent_retry():
    with rig() as r:
        did = r.awaiting("S6")
        r.put_record("S6", did, "qa-failure-analyst")
        eq("N3.1 the earlier stage has a standing accept record: it awaits nobody", A.awaits_acceptance(r.ctl, "S6", r.pipeline()), "")
        kind, got, printed = r.close(r.refuse())
        eq("N3.1 refusal 1: `retry`, no question", (kind, got), ("outcome", "retry"))
        eq("N3.1 ... one printed line that names both stages", printed.strip().splitlines(),
           ["S7: closed after S6, which is not closed yet; the factory goes back to it"])
        eq("N3.1 ... no defect filed, no finding, nothing written", (r.defects(), r.findings(), r.cmds), ([], [], []))


def test_n3_2_the_same_refusal_at_the_same_revision_is_asked():
    with rig() as r:
        did = r.awaiting("S6")
        r.put_record("S6", did, "qa-failure-analyst")
        eq("N3.2 AT the bound: refusal 1 retries", r.close(r.refuse())[:2], ("outcome", "retry"))
        kind, person, printed = r.close(r.refuse())
        eq("N3.2 BEYOND the bound: refusal 2 at the same revision is the question", (kind, person.kind), ("person", "code_close"))
        rec = r.rec()
        eq("N3.2 key and offer: `code_close.behind`, retry / stop", (rec["key"], rec["offer"], rec["behind"]), ("code_close.behind", ["retry", "stop"], "S6"))
        text = str(person.text)
        assert "(S6)" in text and "not closed yet" in text, text
        eq("N3.2 the question obeys the human-text rules", human_broken(text), [])
        eq("N3.2 it never tells the person that no word passes", "no word of yours passes" in text, False)
        eq("N3.2 no defect of the factory is filed for a stage open behind", r.defects(), [])
        r.ctl["revision"] = 8
        eq("N3.2 the revision moved: the bound starts again, a silent retry", r.close(r.refuse())[:2], ("outcome", "retry"))
        eq("N3.2 ... and the same revision asks again", r.close(r.refuse())[0], "person")


def test_n3_3_an_earlier_stage_that_awaits_its_consumer_gets_go_on():
    with rig() as r:
        did = r.awaiting("S6")
        kind, person, _ = r.close(r.refuse())
        eq("N3.3 the earlier stage awaits the analyst, no record: the question at once (no silent retry)", (kind, person.kind), ("person", "code_close"))
        rec = r.rec()
        eq("N3.3 the offer is go on / retry / stop", (rec["key"], rec["offer"], rec["awaits"]), ("code_close.behind", ["go on", "retry", "stop"], True))
        text = str(person.text)
        for needle in ("(S6)", "failure analyst", "runner's handoff", "`go on`", "`retry`", "`stop`"):
            assert needle in text, f"{needle!r} missing in:\n{text}"
        eq("N3.3 the text carries no dispatch id and no internal word", (did in text, "required prior" in text, "stage_awaits" in text), (False, False, False))
        eq("N3.3 the question obeys the human-text rules", human_broken(text), [])
        eq("N3.3 no defect filed", r.defects(), [])


def test_n3_4_go_on_records_the_pass_and_the_close_runs_again():
    with rig() as r:
        did = r.awaiting("S6")
        r.close(r.refuse())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            took = r.d._answer_code_close("go on", "q", "S7", "")
        eq("N3.4 go on is a token", took, True)
        record = A.stage_acceptance(r.pipeline(), "S6")
        eq("N3.4 a driver accept of the runner's dispatch, by the person's word",
           (record["acceptor"], record["verdict"], record["reviewed_dispatch"], record["quote"]), (A.DRIVER_ACCEPTOR, "accept", did, "by: person - go on"))
        eq("N3.4 the record is written by the one writer, no waiver", [c[0] for c in r.cmds if c[0] in ("stage_done.py", "waiver.py")], ["stage_done.py"])
        keys = [c[c.index("--idempotency-key") + 1] for c in r.findings()]
        eq("N3.4 the finding row of the pass (N2) exists", keys, [f"stage-acceptance-pass:{TASK}:S6:{did}"])
        eq("N3.4 `retry` follows: the close runs again", (r.rec()["recovered"], "the step runs again" in out.getvalue()), (False, True))
        eq("N3.4 the earlier stage awaits nobody now: the next refusal is a silent retry, not the question", r.close(r.refuse())[:2], ("outcome", "retry"))


def test_n3_5_other_refusals_keep_todays_road():
    with rig() as r:
        r.ctl["dispatches"]["S7-x-1"] = {"id": "S7-x-1", "stage": "S7", "role": "x", "status": "running"}
        kind, person, _ = r.close(r.refuse(text="checkpoint active work before code-only completion"))
        eq("N3.5 another conflict: today's question (retry / stop), key code_close.stage, ONE defect",
           (kind, r.rec()["key"], r.rec()["offer"], len(r.defects())), ("person", "code_close.stage", ["retry", "stop"], 1))
        eq("N3.5 ... and no behind mark in the record", "behind" in r.rec(), False)
    with rig() as r:
        r.ctl["dispatches"]["S7-x-1"] = {"id": "S7-x-1", "stage": "S7", "role": "x", "status": "running"}
        # B2 (TR1-9): "something is still running" is the CONTROLLER's verdict, carried by its sentence. The behind sentence ALONE means the
        # controller read the running row as not holding (a dead session), whatever the driver's default reading says: the behind road
        both = "checkpoint active work before code-only completion\nrequired prior logical stage incomplete"
        eq("N3.5 the running sentence WITH the behind one: today's road (the controller says a holder remains)",
           (r.close(r.refuse(text=both))[0], r.rec()["key"], len(r.defects())), ("person", "code_close.stage", 1))
    with rig() as r:
        r.ctl["dispatches"]["S7-x-1"] = {"id": "S7-x-1", "stage": "S7", "role": "x", "status": "running"}
        eq("B2 the behind sentence alone with a running row on the default reading: the behind road, a silent retry, no defect",
           (r.close(r.refuse())[:2], r.rec()["key"], len(r.defects())), (("outcome", "retry"), "code_close.behind", 0))
        kind, person, _ = r.close(r.refuse())
        eq("B2 ... and the same revision asks `code_close.behind` (retry / stop), never `no word of yours passes`",
           (kind, r.rec()["key"], r.rec()["offer"], "no word of yours passes" in str(person.text), len(r.defects())),
           ("person", "code_close.behind", ["retry", "stop"], False, 0))
    with rig() as r:
        r.ctl = {}
        eq("N3.5 an unreadable controller state: today's question, never a silent pass",
           (r.close(r.refuse())[0], r.rec()["key"], len(r.defects())), ("person", "code_close.stage", 1))
    with rig() as r:
        r.awaiting("S6")
        eq("N3.5 a refusal that is not the behind message: today's road although a stage is open behind",
           (r.close(r.refuse(text="boom"))[0], r.rec()["key"], len(r.defects())), ("person", "code_close.stage", 1))


def test_n3_6_s9_behind_s8_and_the_s7_row_use_the_same_branch():
    with rig() as r:
        r.ctl["stages"] = stage_states(S6="completed", S7="completed", S8="pending", S9="pending")
        refusal = r.refuse(stage="S9", site="s9.numbers")
        eq("N3.6 S9 behind S8 (nothing to accept): refusal 1 is a silent retry", r.close(refusal)[:2], ("outcome", "retry"))
        kind, person, _ = r.close(r.refuse(stage="S9", site="s9.numbers"))
        eq("N3.6 refusal 2 at the same revision: the question, retry / stop, S8 named",
           (kind, r.rec("S9")["key"], r.rec("S9")["offer"], "(S8)" in str(person.text)), ("person", "code_close.behind", ["retry", "stop"], True))
        eq("N3.6 ... obeys the human-text rules, no defect", (human_broken(str(person.text)), r.defects()), ([], []))
    with rig() as r:                                    # the S7 row of the consumer table: the scribe accepts S7, S9 is behind it
        r.ctl["stages"] = stage_states(S6="completed", S7="pending", S8="pending", S9="pending")
        did = r.awaiting("S7")
        kind, person, _ = r.close(r.refuse(stage="S9", site="s9.numbers"))
        text = str(person.text)
        eq("N3.6 S7 awaits the doc scribe: go on is offered, S7 and the scribe are named",
           (kind, r.rec("S9")["offer"], "(S7)" in text, "doc scribe" in text, "analyst's handoff" in text), ("person", ["go on", "retry", "stop"], True, True, True))
        eq("N3.6 ... the text obeys the rules and names no dispatch", (human_broken(text), did in text), ([], False))
        with contextlib.redirect_stdout(io.StringIO()):
            r.d._answer_code_close("go on", "q", "S9", "")
        eq("N3.6 go on: the driver accept of the analyst's dispatch stands", A.accepted_for(r.pipeline(), "S7", did, acceptor=A.DRIVER_ACCEPTOR), True)


def test_n3_7_a_pass_that_cannot_be_recorded_is_held_not_passed():
    with rig() as r:
        did = r.awaiting("S6")
        r.close(r.refuse())
        r.d.consumer_person_pass = lambda *a, **k: False
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                r.d._answer_code_close("go on", "q", "S7", "")
                held = None
            except SR.Person as person:
                held = str(person.text)
        assert held and "could not be recorded" in held, held
        eq("N3.7 nothing is recorded as accepted", A.accepted_for(r.pipeline(), "S6", did), False)


# --- N4 -------------------------------------------------------------------------------------------------------------------------------------
SCRIBE_REASON, SCRIBE_DIGEST = "the doc scribe accepted the failure analyst's triage", "accepted by the doc scribe"
ANALYST_REASON, ANALYST_DIGEST = "the failure analyst accepted the runner's handoff", "accepted by the failure analyst"


def s7_awaiting_scribe(r):
    r.ctl["stages"] = stage_states(S6="completed", S7="pending")
    return r.awaiting("S7")


def test_n4_1_a_persons_pass_is_reported_as_the_persons_word():
    with rig() as r:
        did = s7_awaiting_scribe(r)
        r.put_record("S7", did, A.DRIVER_ACCEPTOR, "by: person - the triage is fine")
        reason, digest = r.d.consumer_close_words("S7")
        eq("N4.1 S7: the digest says a person's word accepted it", digest, "accepted by a person's word")
        eq("N4.1 S7: the reason names the person's word and the handoff", reason, "a person's word passed the acceptance of the analyst's handoff")
        eq("N4.1 never the consumer's name", ("doc scribe" in reason + digest, "analyst accepted" in reason + digest), (False, False))
        seen = []
        r.d.close_by_code = lambda stage, reason, evidence, **kw: seen.append((stage, reason, kw.get("site"), kw.get("digest"))) or True
        r.d.s7_fresh = lambda: True
        eq("N4.1 the call line of s7_closed_by_scribe passes the words of the record", (r.d.s7_closed_by_scribe(r.ctl), seen),
           (True, [("S7", reason, "s7.accepted", digest)]))
        refusal = r.refuse(site="s7.accepted", text="boom")
        kind, person, _ = r.close(refusal)
        eq("N4.1 the lead of the code_close question says the same", (kind, reason in str(person.text), "doc scribe accepted" in str(person.text)), ("person", True, False))
    with rig() as r:
        did = r.awaiting("S6")
        r.put_record("S6", did, A.DRIVER_ACCEPTOR, "by: person - fine")
        eq("N4.1 S6 row: the same", r.d.consumer_close_words("S6"),
           ("a person's word passed the acceptance of the runner's handoff", "accepted by a person's word"))


def test_n4_2_the_consumers_own_record_keeps_todays_words():
    with rig() as r:
        did = s7_awaiting_scribe(r)
        r.put_record("S7", did, "qa-doc-scribe")
        eq("N4.2 S7: the scribe's record: today's reason and digest", r.d.consumer_close_words("S7"), (SCRIBE_REASON, SCRIBE_DIGEST))
        r.put_record("S7", did, A.DRIVER_ACCEPTOR, "an accept with a gap")             # a driver accept that is not the person's pass
        eq("N4.2 a driver accept whose quote is not `by: person`: today's words too", r.d.consumer_close_words("S7"), (SCRIBE_REASON, SCRIBE_DIGEST))
    with rig() as r:
        did = r.awaiting("S6")
        r.put_record("S6", did, "qa-failure-analyst")
        eq("N4.2 S6 row: the analyst's record: today's reason and digest", r.d.consumer_close_words("S6"), (ANALYST_REASON, ANALYST_DIGEST))


def test_n4_3_no_record_and_unreadable_state_give_the_default_text():
    with rig() as r:
        s7_awaiting_scribe(r)
        eq("N4.3 S7 no record: the default words", r.d.consumer_close_words("S7"), (SCRIBE_REASON, SCRIBE_DIGEST))
        eq("N4.3 S6 no record, no author: the default words", r.d.consumer_close_words("S6"), (ANALYST_REASON, ANALYST_DIGEST))
        did = r.awaiting("S6")
        r.put_record("S6", "S6-qa-runner-0", A.DRIVER_ACCEPTOR, "by: person - for an EARLIER dispatch")
        eq("N4.3 a person's pass for an earlier dispatch is not this close's: the default", r.d.consumer_close_words("S6"), (ANALYST_REASON, ANALYST_DIGEST))
        r.ctl = {}
        r.put_record("S6", did, A.DRIVER_ACCEPTOR, "by: person - fine")
        eq("N4.3 an unreadable controller state names nobody: the default", r.d.consumer_close_words("S6"), (ANALYST_REASON, ANALYST_DIGEST))
        (r.task_root / "pipeline.json").write_text("{ not json", encoding="utf-8")
        eq("N4.3 an unreadable pipeline: the default", r.d.consumer_close_words("S7"), (SCRIBE_REASON, SCRIBE_DIGEST))


def test_n4_4_the_s6_call_line_takes_its_words_from_the_record():
    for who, record, want in (("the person's pass", ("by: person - fine", A.DRIVER_ACCEPTOR),
                               ("a person's word passed the acceptance of the runner's handoff", "accepted by a person's word")),
                              ("the analyst's own record", ("", "qa-failure-analyst"), (ANALYST_REASON, ANALYST_DIGEST))):
        with rig() as r:
            r.put_record("S6", r.awaiting("S6"), record[1], record[0])
            seen = []
            r.d.stage_scope = lambda stage, kind: {"scope": []}       # nothing left to run in S6: the close by the standing record
            r.d.close_by_code = lambda stage, reason, evidence, **kw: seen.append((stage, reason, kw.get("site"), kw.get("digest"))) or True
            r.d.stage_S6()
            eq(f"N4.4 stage_S6 closes by {who} with the words of the record", seen, [("S6", want[0], "s6.accepted", want[1])])
            r.d.__dict__.pop("stage_scope", None)


def test_f7_the_refusal_sentence_is_pinned_to_its_source():
    """B-20 F7: `code_close` matches the controller's sentence by its words (the refusal carries no field); a reworded controller message would
    turn N3 off with every other test green. The sentence the controller yields for a stage behind an open one is the one the driver matches."""
    import controller
    state = {"revision": 7, "stages": stage_states(S6="pending", S7="pending"), "dispatches": {}}
    problems = [str(message) for _kind, message in controller.code_close_conflicts(state, "S7")]
    eq("F7 the controller still says the sentence the driver matches for a stage behind an open one",
       problems, ["required prior logical stage incomplete"])
    assert REFUSED.split('"')[3] in Path(SR.__file__).read_text(encoding="utf-8"), "F7 the driver still matches that sentence"


# --- TR1-9: a dispatch whose session is over does not hold a code close --------------------------------------------------------------------
def holder_state(row_stage, row_role, status="running"):
    ident = f"{row_stage}-{row_role}-6"
    return {"revision": 9, "stages": stage_states(S6="completed", S7="running"),
            "dispatches": {ident: {"id": ident, "stage": row_stage, "role": row_role, "status": status}}}, ident


def controller_reading(verdict):
    """A Controller with no store whose liveness reader answers `verdict` (a dict, or an Exception to raise)."""
    import controller
    c = controller.Controller.__new__(controller.Controller)
    c._project_root = lambda: Path(".")
    c._dispatch_starts = lambda: {}

    def reader(project, record, now=None, names=None):
        if isinstance(verdict, Exception):
            raise verdict
        return verdict
    c._liveness = reader
    return c


def close_over(state, verdict, stage="S7"):
    import controller
    c = controller_reading(verdict)
    verdicts = c._close_verdicts(state, stage)
    return (controller.code_close_conflicts(state, stage, verdicts), controller.code_close_facts(state, stage, verdicts))


def test_tr1_9_1_a_dead_dispatch_of_another_stage_closes_and_is_named():
    state, ident = holder_state("S6", "qa-runner")
    for word in ("abandoned", "never_started"):
        conflicts, facts = close_over(state, {"state": word, "evidence": []})
        eq(f"TR1-9.1 {word}: no conflict, the dispatch is passed over by name", (conflicts, facts["running"], [i for i, _ in facts["passed_over"]]), ([], [], [ident]))
    import controller
    eq("TR1-9.1 the close note names it", controller.code_close_note(close_over(state, {"state": "abandoned"})[1]["passed_over"]),
       f"; passed over, not holding the close: {ident} (abandoned)")


def test_tr1_9_2_the_closing_stages_own_returned_dispatch_is_named_returned_never_accepted():
    state, ident = holder_state("S7", "qa-failure-analyst")
    import controller
    conflicts, facts = close_over(state, {"state": "returned", "evidence": ["the driver recorded the session as ended"]})
    eq("TR1-9.2 no conflict, passed over", (conflicts, facts["running"]), ([], []))
    note = controller.code_close_note(facts["passed_over"])
    eq("TR1-9.2 the note says it by name", note, f"; passed over, not holding the close: {ident} (returned, never accepted)")
    state["dispatches"][ident]["status"] = "accepted"
    eq("TR1-9.2 an accepted row is not in the running list at all", close_over(state, {"state": "returned"})[1]["passed_over"], [])


def test_tr1_9_3_a_live_dispatch_refuses_names_it_and_the_door():
    state, ident = holder_state("S6", "qa-runner")
    conflicts, facts = close_over(state, {"state": "alive", "evidence": []})
    text = [str(message) for _kind, message in conflicts]
    eq("TR1-9.3 one refusal that keeps the pinned sentence", len(text) == 1 and text[0].startswith("checkpoint active work before code-only completion"), True)
    for needle in (ident, "qa-runner", "S6", "still running", "wait for it", "--operation release --dispatch " + ident):
        assert needle in text[0], f"{needle!r} missing in: {text[0]}"
    eq("TR1-9.3 it still holds", facts["running"], [ident])


def test_tr1_9_4_unknown_and_a_dead_reader_refuse_without_a_pass():
    state, ident = holder_state("S7", "qa-failure-analyst")
    for name, verdict in (("unknown", {"state": "unknown", "evidence": ["a stale receipt"]}), ("a reader that raises", RuntimeError("boom")),
                          ("a verdict that is no dict", None), ("a state nobody knows", {"state": "something-new"})):
        conflicts, facts = close_over(state, verdict)
        eq(f"TR1-9.4 {name}: refused, the dispatch still running, nothing passed over", (len(conflicts), facts["running"], facts["passed_over"]), (1, [ident], []))
        assert "could not tell" in str(conflicts[0][1]), conflicts
    import controller
    c = controller.Controller.__new__(controller.Controller)
    c._project_root = lambda: None
    c._dispatch_starts = lambda: {}
    eq("TR1-9.4 no project to read in: unknown, which holds", c._close_verdicts(state, "S7")[ident]["state"], "unknown")


def test_tr1_9_5_the_other_causes_and_the_default_reading_are_unchanged():
    import controller
    state, ident = holder_state("S6", "qa-runner")
    state["stages"]["S5"] = {"status": "running"}
    conflicts, _facts = close_over(state, {"state": "abandoned"})
    eq("TR1-9.5 a dead dispatch frees only the running list: the stage behind still refuses",
       [str(m) for _k, m in conflicts], ["required prior logical stage incomplete"])
    eq("TR1-9.5 without verdicts the sentence and the facts are the old ones",
       ([str(m) for _k, m in controller.code_close_conflicts(state, "S7")], sorted(controller.code_close_facts(state, "S7"))),
       (["checkpoint active work before code-only completion", "required prior logical stage incomplete"], ["behind", "completed", "running"]))


def test_tr1_9_f8_an_alive_verdict_holds_whatever_else_it_says():
    """F8: `dispatch_liveness.state` never gives `alive` with `process: gone`; the branch that read it is gone, and `alive` holds."""
    state, ident = holder_state("S6", "qa-runner")
    conflicts, facts = close_over(state, {"state": "alive", "process": "gone", "evidence": []})
    eq("F8 alive holds", (len(conflicts), facts["running"], facts["passed_over"]), (1, [ident], []))


def stopped_state(status, row_stage="S6", role="qa-runner"):
    ident = f"{row_stage}-{role}-6"
    return {"revision": 9, "stages": stage_states(S6="completed", S7="running"),
            "dispatches": {ident: {"id": ident, "stage": row_stage, "role": role, "status": status}}}, ident


def test_b4_a_row_already_stopped_is_named_not_only_a_running_one():
    """B4: `close_settled` may have moved the row to `returned_unaccepted` before the close: the name must not depend on that order."""
    import controller
    for status, label in (("returned_unaccepted", "returned, never accepted"), ("abandoned", "abandoned"),
                          ("blocked", "stopped, never accepted"), ("incomplete", "stopped, never accepted"), ("paused", "stopped, never accepted")):
        state, ident = stopped_state(status)
        conflicts, facts = close_over(state, {"state": "alive"})
        eq(f"B4 {status}: no conflict, named {label!r}", (conflicts, facts["passed_over"]), ([], [(ident, label)]))
    state, ident = stopped_state("returned_unaccepted")
    eq("B4 without verdicts the facts carry no passed_over key", "passed_over" in controller.code_close_facts(state, "S7"), False)
    state, ident = stopped_state("accepted")
    eq("B4 an accepted row is no one's loss", close_over(state, {"state": "alive"})[1]["passed_over"], [])
    state, ident = stopped_state("returned_unaccepted", row_stage="S8")
    eq("B4 a row of a LATER stage is not this close's", close_over(state, {"state": "alive"})[1]["passed_over"], [])
    state, ident = stopped_state("returned_unaccepted")
    state["dispatches"]["S6-qa-runner-7"] = {"id": "S6-qa-runner-7", "stage": "S6", "role": "qa-runner", "status": "accepted"}
    eq("B4 a later accepted dispatch of the same stage and role replaced it: not named", close_over(state, {"state": "alive"})[1]["passed_over"], [])
    state["dispatches"]["S6-qa-runner-7"]["role"] = "someone-else"
    eq("B4 ... another role's acceptance does not", [i for i, _ in close_over(state, {"state": "alive"})[1]["passed_over"]], [ident])


def close_events(passed, reason="closed by code"):
    return [{"sequence": 1, "type": "initialize", "payload": {"legacy_import": {
                "stages": stage_states(S6="completed", S7="running"),
                "dispatches": {"S7-qa-failure-analyst-6": {"id": "S7-qa-failure-analyst-6", "stage": "S7", "role": "qa-failure-analyst",
                                                           "status": "returned_unaccepted"},
                               "S6-qa-runner-6": {"id": "S6-qa-runner-6", "stage": "S6", "role": "qa-runner", "status": "running"}}}}},
            {"sequence": 2, "type": "code_only", "payload": {"stage": "S7", "id": "rcpt-1", "reason": reason, "passed_over": passed}}]


def test_b3_a_passed_over_row_is_set_aside_so_next_moves_on_and_a_replay_agrees():
    import copy
    import controller
    passed = [{"id": "S7-qa-failure-analyst-6", "label": "returned, never accepted"}, {"id": "S6-qa-runner-6", "label": "abandoned"}]
    state = controller.projection(close_events(passed))
    rows = state["dispatches"]
    eq("B3 both rows are superseded by the receipt", {i: (r["status"], r["passed_over_by"]) for i, r in rows.items()},
       {"S7-qa-failure-analyst-6": ("superseded", "rcpt-1"), "S6-qa-runner-6": ("superseded", "rcpt-1")})
    eq("B4 the stage entry keeps the names", state["stages"]["S7"]["passed_over"], passed)
    act = controller.Controller._next_action_for_state(copy.deepcopy(state))
    eq("B3 `next` does not wait on, or ask to resolve, a closed stage's dispatch", act.get("action") not in ("wait_existing_job", "resolve_return"), True)
    eq("B3 a replay of the same journal gives the same state", controller.projection(close_events(passed)), state)
    held = controller.projection(close_events([]))
    eq("B3 a close that passed nothing over leaves the rows as they were and writes no names",
       (held["dispatches"]["S7-qa-failure-analyst-6"]["status"], "passed_over" in held["stages"]["S7"]), ("returned_unaccepted", False))


def test_b4_validate_refuses_a_close_whose_names_are_not_the_states():
    import controller
    state, ident = stopped_state("returned_unaccepted")
    c = controller_reading({"state": "alive"})
    c.store = type("S", (), {"root": Path(".")})()
    c._ref_issues = lambda refs, what="": []
    c._among = lambda stage, allowed: stage in allowed
    state["source_revision"] = "r1"
    base = {"stage": "S7", "id": "r", "reason": "x", "evidence_refs": ["e"]}
    named = [{"id": ident, "label": "returned, never accepted"}]
    seen = []
    for name, payload in (("the names it passes over", dict(base, passed_over=named)), ("no names at all", dict(base)),
                          ("a name that is not the state's", dict(base, passed_over=[{"id": ident, "label": "abandoned"}]))):
        try:
            c.validate("code_only", payload, copy.deepcopy(state))
            seen.append((name, "ok"))
        except controller.StateConflict as error:
            seen.append((name, "moved" if "state moved" in str(error) else str(error)))
    eq("B4 only the state's own names pass", seen, [("the names it passes over", "ok"), ("no names at all", "moved"), ("a name that is not the state's", "moved")])


def test_b4_the_driver_files_one_idempotent_finding_per_passed_over_dispatch():
    with rig() as r:
        r.ctl["stages"]["S7"] = {"status": "completed", "passed_over": [
            {"id": ANALYST_1, "label": "returned, never accepted"}, {"id": RUNNER_1, "label": "abandoned"}, {"id": ""}, "junk"]}
        r.ctl["dispatches"][ANALYST_1] = {"id": ANALYST_1, "stage": "S7", "role": "qa-failure-analyst", "status": "superseded"}
        r.d.file_passed_over("S7", "rcpt-1")
        r.d.file_passed_over("S7", "rcpt-1")
        keys = [c[c.index("--idempotency-key") + 1] for c in r.findings()]
        eq("B4 one key per dispatch, the same on a repeat (the writer dedups by it)", keys,
           [f"close-passed-over:{TASK}:S7:{ANALYST_1}", f"close-passed-over:{TASK}:S7:{RUNNER_1}"] * 2)
        first = r.findings()[0]
        essence = first[first.index("--essence") + 1]
        eq("B4 the essence names the role, the dispatch and the label", all(w in essence for w in ("qa-failure-analyst", ANALYST_1, "returned, never accepted")), True)
    with rig() as r:
        r.d.file_passed_over("S7", "rcpt-1")
        r.ctl = {}
        r.d.file_passed_over("S7", "rcpt-1")
        eq("B4 a stage that passed nothing over, and an unreadable state, file nothing", r.findings(), [])


def test_b4_the_report_names_every_passed_over_dispatch_and_an_unreadable_record():
    import tempfile
    import report_facts
    with tempfile.TemporaryDirectory() as tmp:
        art = Path(tmp)
        eq("B4 report: no record, no line (it is said once elsewhere)", report_facts._passed_over_gap(art), "")
        (art / "pipeline.json").write_text(json.dumps({"stages": {"S6": {"status": "completed"}, "S7": {"status": "completed", "passed_over": [
            {"id": ANALYST_1, "label": "returned, never accepted"}, {"id": "odd", "label": "abandoned"}]}}}), encoding="utf-8")
        got = report_facts._passed_over_gap(art).splitlines()
        eq("B4 report: one line each", len(got), 2)
        assert ANALYST_1 in got[0] and "qa-failure-analyst's work of S7 was returned, never accepted" in got[0] and "S7 was closed by code over it" in got[0], got
        assert "odd" in got[1] and "abandoned" in got[1], got
        (art / "pipeline.json").write_text(json.dumps({"stages": {"S7": {"status": "completed"}}}), encoding="utf-8")
        eq("B4 report: no names, no line", report_facts._passed_over_gap(art), "")
        (art / "pipeline.json").write_text("{broken", encoding="utf-8")
        assert "could not be established" in report_facts._passed_over_gap(art), "an unreadable record says so (AR-28)"


def main():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for _name, fn in tests:
        fn()
    finish("test_code_close_behind")


if __name__ == "__main__":
    main()
