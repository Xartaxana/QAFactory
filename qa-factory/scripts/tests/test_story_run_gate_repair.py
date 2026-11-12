#!/usr/bin/env python3
"""t-211 / F-cmp2-17: the gate-entry repair of the driver (`Driver.gate_repair`), with every model call replaced.

TP1-15045 (cmp2) asked gate A with 8 design-review findings, 6 unpinned cases and 1 question branch still in
the rehearsal; the factory could have repaired most of it by code before the person was addressed. What is proved
here, on the cmp2 shape (controller.json: S4 completed, designer-2 accepted AFTER critic-1, the stale
`active_dispatch_id` in the pipeline.json mirror):

  * K1/K2 the first await_gate raises no Person; the round re-pins (`case_versions --all`, then `--verify`) and THEN
    registers exactly one critic rework over the designer rework's six cases;
  * K3 a second round with the same key set is refused and goes to the conductor, once; a stopped series shows the
    gate with the list at its top, never a second conductor call, also after a relaunch;
  * K4 an absent, failed or malformed rehearsal shows the gate as it always was, and spends nothing;
  * the cap (AT 2 runs, BEYOND 3 is refused), the key set (by check + message, never by position; A -> B -> A);
  * the invariants of the position: nothing under an open question, nothing after the person spoke, a series
    stamped with its story revision, a failed move never silent and never repeated, an empty scope never registered;
  * the list reaches the conductor through the conductor's own call and not through the known-refusal table.

The F0 row (`stage_done`'s "stands in front of gate" continues) is proved in test_story_run_refusals.py.
The shared scaffolding is `story_run_common.py`.
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
from harness import check, check_eq, check_in, check_not_in  # noqa: E402
from story_run_common import driver_for, jsonl, run_scenarios, seam_option, seed  # noqa: E402

SEAM_TWO = [seam_option("retry", "person_does"), seam_option("stop", "stop_here")]     # a usable conductor answer (C1-1)

TASK = "QA-9"
CASES = [f"QA-9_TC_{n:03d}" for n in (1, 3, 4, 6, 8, 11, 12, 13, 14)]       # critic-1's scope
REWORKED = [f"QA-9_TC_{n:03d}" for n in (4, 6, 11, 12, 13, 14)]              # designer-2's scope
D1, C1, D2 = "S4-qa-case-designer-1", "S4-qa-case-critic-1", "S4-qa-case-designer-2"
FIXABLE = "factory_fixable"


def finding(check_id: str, n: int, message: str = "", klass: str = FIXABLE, **extra) -> dict:
    return {"id": f"{check_id}-{n}", "check": check_id, "class": klass,
            "message": message or f"{check_id} problem number {n}", "fix": "", **extra}


def cmp2_findings() -> list:
    """8 design-review findings, 6 unpinned cases and 1 question branch: what the cmp2 rehearsal held."""
    return ([finding("gate_decision", n, f"the gate A decision will NOT record: plan row TS-{n}: review") for n in range(1, 9)]
            + [finding("case_versions", n, f"a case the gate approves is not pinned at its current bytes: {c}")
               for n, c in enumerate(REWORKED, 1)]
            + [finding("question_branches", 1, "question branches - TS-4 rests on Q4", where="TS-4", question="Q4", kind="x")])


def reviews_after(author: str = D2, critic: str = C1, verdict: str = "accepted") -> list:
    """The controller's own design reviews (`build_gate_decision()["design_reviews"]`) for two critical rows."""
    return [{"plan_row": f"TS-{n}", "verdict": verdict, "author_dispatch_id": author, "reviewer_dispatch_id": critic}
            for n in (4, 8)]


class Rig:
    """One seeded project in the cmp2 shape, a Driver over it with every seam replaced by a recorder.
    `log` is the ONE ordered list of what the step did: ("rehearse", gate), ("case_versions", "--all"),
    ("rework", role, scope, cause), ("record", ...)."""

    def __init__(self, *, findings=None, reviews=None, pinned=None, order=None, budget="room", script=None):
        import story_run
        self.story_run = story_run
        self.root, self.task_root, self.env = seed(TASK)
        self.log, self.conductors, self.boundaries = [], [], []
        self.findings = cmp2_findings() if findings is None else findings
        self.script = list(script or [])
        self.reviews = reviews_after() if reviews is None else reviews
        self.pinned = list(CASES if pinned is None else pinned)
        self.order = order or {D1: 0, C1: 1, D2: 2}
        self.budget = {"counted": 0, "cap": 2} if budget == "room" else budget
        self.verdict = {"action": "continue", "did": "stub"}
        self.reasons = []
        self.pin_exit, self.pin_text = 0, ""
        self.rework_error = None
        self.revise_error = None
        self.write_state()
        self.driver = self.bind(driver_for(self.root, self.env, TASK))

    def write_state(self) -> None:
        """controller.json and the pipeline.json mirror in the cmp2 shape; READ the controller, not the mirror."""
        path = self.task_root / "state" / "controller.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["scope"] = list(CASES)
        data["stages"]["S4"] = {"status": "completed", "dispatch_id": C1, "reason": "",
                                "later_work_status": "pending", "later_work_settled": True}
        data["dispatches"] = {
            D1: {"id": D1, "stage": "S4", "role": "qa-case-designer", "status": "accepted", "scope": []},
            C1: {"id": C1, "stage": "S4", "role": "qa-case-critic", "status": "accepted", "scope": list(CASES)},
            D2: {"id": D2, "stage": "S4", "role": "qa-case-designer", "status": "accepted", "purpose": "repair_verify",
                 "rework_of": D1, "scope": list(REWORKED)}}
        path.write_text(json.dumps(data), encoding="utf-8")
        pipeline_path = self.task_root / "pipeline.json"
        pipeline = json.loads(pipeline_path.read_text(encoding="utf-8"))
        pipeline["stages"]["S4"] = {"status": "done", "dispatch_id": C1, "later_work_status": "pending",
                                    "active_dispatch_id": "S4-qa-case-critic-2", "later_work_settled": True}
        pipeline_path.write_text(json.dumps(pipeline), encoding="utf-8")

    def _revise_plan(self) -> None:
        self.log.append(("revise_plan",))
        if self.revise_error:
            raise self.revise_error

    def _render_appendix(self) -> None:
        """The case appendix embeds what the pinned cases are NOW: the stub writes how many moves came before it."""
        self.log.append(("render_appendix",))
        moves = sum(1 for e in self.log if e[0] in ("case_versions", "revise_plan", "rework"))
        path = self.task_root / "work" / "case-appendix.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"appendix after {moves} move(s)\n", encoding="utf-8")

    def add_dispatch(self, dispatch: str, role: str, scope: list) -> None:
        path = self.task_root / "state" / "controller.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["dispatches"][dispatch] = {"id": dispatch, "stage": "S4", "role": role, "status": "accepted", "scope": list(scope)}
        path.write_text(json.dumps(data), encoding="utf-8")

    def bind(self, driver):
        """Every seam the step reads, replaced. Nothing here starts a process or a model."""
        story_run = self.story_run

        def rehearse(gate):
            self.log.append(("rehearse", gate))
            value = self.script.pop(0) if self.script else {"findings": list(self.findings)}
            if isinstance(value, BaseException):
                raise value
            return value

        def py(script, *args, check=False, expect=""):      # C1-7c Q-3: the real `py`'s signature; a G site's `expect` is forwarded
            if script == "case_versions.py":
                self.log.append(("case_versions", "--all" if "--all" in args else "--verify"))
                if self.pin_exit:
                    if check:
                        raise (story_run.gate_refusal(script, self.pin_exit, self.pin_text, expect) if expect else
                               story_run.Refusal(f"case_versions.py --task-root x --all (exit {self.pin_exit}):\n{self.pin_text}"))
                    return self.pin_exit, self.pin_text
            else:
                self.log.append((script.replace(".py", ""),))
            return 0, ""

        def rework(stage, role, cases, reason, *, cause, purpose="repair_verify", extra=(), complete=False):
            self.log.append(("rework", role, tuple(cases), cause))
            self.reasons.append(reason)
            if self.rework_error:
                raise self.rework_error
            return "", None

        def conductor(text, *, words="", files=None, words_file=None):
            self.conductors.append(text)
            self.boundaries.append(driver.boundary)
            return dict(self.verdict)
        driver.rehearse, driver.py, driver.rework, driver.conductor = rehearse, py, rework, conductor
        driver.design_reviews = lambda gate: list(self.reviews)
        driver.accept_order = lambda: dict(self.order)
        driver.pinned_cases = lambda: list(self.pinned)
        driver.budget_or_none = lambda stage, role, scope, ref="": dict(self.budget) if self.budget else None
        driver.gate_text = lambda gate: "the packet"
        driver.judged_reply = lambda *a, **k: ""
        driver.revise_plan = self._revise_plan
        driver.render_appendix = self._render_appendix
        driver.rebuild_report = lambda: self.log.append(("rebuild_report",)) or True
        return driver

    def relaunch(self):
        """A new driver over the same project: the state file is all it knows (an exit-3 relaunch)."""
        self.driver = self.bind(driver_for(self.root, self.env, TASK))
        return self.driver

    def enter(self, gate: str = "A"):
        """One await_gate boundary. "returned" (a round ran, back to `where`), the Person raised, or the exception."""
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            try:
                self.driver.dispatch_action({"action": "await_gate", "gate": gate})
                result = "returned"
            except self.story_run.Person as person:
                result = person
            except Exception as exc:        # a crash is a failed check, not a crashed file
                result = exc
        self.out = printed.getvalue()
        return result

    def series(self, gate: str = "A") -> dict:
        path = self.task_root / "state" / "driver-state.json"
        if not path.is_file():
            return {}
        return (json.loads(path.read_text(encoding="utf-8")).get("gate_repair") or {}).get(gate) or {}

    def calls(self, name: str) -> list:
        return [e for e in self.log if e[0] == name]

    def first(self) -> str:
        """What the first conductor call was handed ("" when there was none: a failed check, not a crash)."""
        return self.conductors[0] if self.conductors else ""

    def close(self) -> None:
        os.chdir(harness.PLUGIN_ROOT)       # the Driver chdirs into the project; a removed cwd is a leftover tree
        harness.cleanup(self.root)


def is_person(result, kind: str = "gate_A") -> bool:
    import story_run
    return isinstance(result, story_run.Person) and result.kind == kind


def cmp2_round_stops_and_survives_a_relaunch() -> None:
    """K1, K2, K3 (M1: the step removed; M2: the critic before the re-pin)."""
    rig = Rig()
    try:
        first = rig.enter()
        check("K1: the first await_gate raises no Person before a repair round", first == "returned", repr(first))
        check_eq("K2 + C11: the round re-pins, revises the plan to the pinned ids, THEN registers exactly one critic "
                 "rework over the designer rework's six cases",
                 rig.log, [("rehearse", "A"), ("case_versions", "--all"), ("case_versions", "--verify"), ("revise_plan",),
                           ("rework", "qa-case-critic", tuple(REWORKED), "test_defect")])
        check_in("L2 counts what the factory repairs and names the round",
                 "gate A rehearsal: 15 thing(s) the factory repairs before anyone is asked (case versions 6, design "
                 "review 8, question branches 1) — repair round 1 of 2", rig.out)
        check_in("L3 says the cases are pinned again", "gate A repair: the cases are pinned again at their current bytes", rig.out)
        check_in("L4 names the cases and the designer round the critic reviews again",
                 f"the case critic reviews again the 6 case(s) the designer reworked in {D2}: " + ", ".join(REWORKED), rig.out)
        check_eq("no conductor was called for the round", rig.conductors, [])
        round_one = rig.series()["rounds"][0]
        check_eq("the round is in the state file with its moves and outcome",
                 (round_one["moves"], round_one["outcome"], round_one["stop"], len(round_one["keys"])),
                 (["pin_cases", "revise_plan", "critic_rework"], "repaired", "", 15))
        check_eq("and the series is stamped with the story's source revision", rig.series()["source_revision"], "src-1")
        runs = [r for r in jsonl(rig.task_root / "state/driver-runs.jsonl") if r.get("kind") == "gate_repair"]
        check_eq("driver-runs.jsonl gets a `gate_repair` row per record (started, then repaired)",
                 [(r["round"], r["outcome"]) for r in runs], [(1, "started"), (1, "repaired")])

        # K3: the same findings again -> refused, to the conductor once, boundary gate_A (C14)
        before = len(rig.log)
        second = rig.enter()
        check("K3: the second entry with the same key set is not a round", second == "returned", repr(second))
        check_eq("K3: nothing is pinned or reworked again (the appendix the repaired round owes is rendered, then the rehearsal)",
                 rig.log[before:], [("render_appendix",), ("rehearse", "A")])
        check_eq("K3: the conductor is called exactly once, at the boundary gate_A", rig.boundaries, ["gate_A"])
        check_in("L5 names the rounds that left the same set",
                 "gate A repair: round 1 left the same 15 thing(s) as round 1 — the list goes to the conductor; no further round", rig.out)
        stop = rig.series()["rounds"][-1]
        check_eq("C12: the stop is recorded with its reason", (stop["stop"], stop["outcome"]), ("same_set", "to_conductor"))
        check_in("the conductor is told what was tried and what to do", "The person has NOT been asked", rig.first())
        check_in("with what the earlier round did", "round 1: pin_cases, revise_plan, critic_rework (repaired)", rig.first())
        check_in("and the findings themselves", "plan row TS-3: review", rig.first())
        check_not_in("C8: but never the question branch, whose only move there is to ask the person", "TS-4 rests on Q4", rig.first())

        # C6: after a stop every await_gate shows the gate with the list at its top - no second conductor call
        third = rig.enter()
        check("C6: the stopped series shows the gate", is_person(third), repr(third))
        check_in("with the factory's own list at the top, stated as its own",
                 "What the factory could not repair before asking you", third.text)
        check_in("and the finding in it", "TS-4 rests on Q4", third.text)
        check("the list stands ABOVE the packet", third.text.index("What the factory could not repair") < third.text.index("the packet"))
        check_eq("no second conductor call", len(rig.conductors), 1)
        # ... also after a relaunch (the bound does not live in the conductor's in-memory count)
        rig.relaunch()
        before = len(rig.log)
        fourth = rig.enter()
        check("a relaunched driver shows the gate too", is_person(fourth), repr(fourth))
        check_eq("and repairs nothing, calls nobody", (rig.log[before:], len(rig.conductors)), ([("rehearse", "A")], 1))
    finally:
        rig.close()


def key_set_and_cap() -> None:
    """The key set is (check, message), compared against EVERY earlier round (M3), never by position (M4);
    the cap is 2: round 2 runs, round 3 is refused (M5)."""
    def pins(rig):
        return len(rig.calls("case_versions")) // 2

    def cv(text):
        return {"findings": [finding("case_versions", 1, f"a case the gate approves is not pinned at its current bytes: {text}")]}
    # A -> B -> A: caught although the previous round differs
    rig = Rig(script=[cv("A"), cv("B"), cv("A")])
    try:
        results = [rig.enter(), rig.enter(), rig.enter()]
        check_eq("A, B, A: two rounds run, the third entry is the conductor's", (results, pins(rig)), (["returned"] * 3, 2))
        stop = rig.series()["rounds"][-1]
        check_eq("M3: the oscillation is caught by the key set, and says so (not by the cap)",
                 (stop["stop"], stop["outcome"]), ("same_set", "to_conductor"))
        check_eq("and the conductor is called once", len(rig.conductors), 1)
    finally:
        rig.close()
    # a message that changes on every run defeats the key set; the cap stops it - AT 2 runs, BEYOND 3 does not
    rig = Rig(script=[cv(f"sha256:{n:064x}") for n in (1, 2, 3, 4)])
    try:
        results = [rig.enter(), rig.enter(), rig.enter()]
        check_eq("cap AT 2: rounds 1 and 2 are dispatched", (results, pins(rig)), (["returned"] * 3, 2))
        stop = rig.series()["rounds"][-1]
        check_eq("cap BEYOND (3): refused, with the reason `cap`", (stop["stop"], len(rig.series()["rounds"])), ("cap", 3))
        check_in("L5 (cap form) says so", "the cap of 2 rounds is spent with 1 thing(s) left", rig.out)
        check_eq("the conductor is called once", len(rig.conductors), 1)
        check("and the next entry shows the gate", is_person(rig.enter()))
    finally:
        rig.close()
    # M4: `gate_decision-1` is the first finding of its check, whichever row it is about: TS-1 then TS-3 differ
    rig = Rig(script=[{"findings": [finding("gate_decision", 1, "the gate A decision will NOT record: plan row TS-1")]},
                      {"findings": [finding("gate_decision", 1, "the gate A decision will NOT record: plan row TS-3")]}])
    try:
        results = [rig.enter(), rig.enter()]
        check_eq("M4: the same positional id over another row is another finding - both rounds run",
                 (results, len(rig.calls("rework"))), (["returned", "returned"], 2))
        check_eq("and no stop was recorded", [r["stop"] for r in rig.series()["rounds"]], ["", ""])
    finally:
        rig.close()
    # two findings with the same message are one key
    rig = Rig(findings=[finding("case_versions", 1, "same words"), finding("case_versions", 2, "same words")])
    try:
        check("two findings with one message: a round runs, no crash", rig.enter() == "returned")
        check_eq("and the key set holds the message once", len(rig.series()["rounds"][0]["keys"]), 1)
    finally:
        rig.close()


def the_loop_reaches_the_gate_before_its_own_stuck_guard() -> None:
    """The whole loop (`run`) on an `await_gate` that never changes: round 1, round 2, the stop and the conductor,
    then the gate - four boundaries with one signature, and the loop's own guard (`repeats >= 4`, a question about a
    boundary that does not move) must not ask a person about the loop before the gate is asked."""
    def cv(n):
        return {"findings": [finding("case_versions", 1, f"unpinned, variant {n}")]}
    rig = Rig(script=[cv(1), cv(2), cv(3), cv(3), cv(3)])
    try:
        rig.driver.where = lambda: {"action": "await_gate", "gate": "A", "revision": 7}
        with contextlib.redirect_stdout(io.StringIO()):
            code = rig.driver.run()
        question = (rig.task_root / "state" / "driver-question.md").read_text(encoding="utf-8")
        check_eq("the loop ends in the gate question, exit 3", (code, "kind: gate_A" in question), (3, True))
        check_eq("after two rounds and one conductor call", (len(rig.calls("case_versions")) // 2, len(rig.conductors)), (2, 1))
        check_in("with the factory's own list at the top of the question", "What the factory could not repair before asking you", question)
        check_not_in("and no question about the loop itself", "kind: refusal", question)
    finally:
        rig.close()


def rehearsal_edges() -> None:
    """K4 and the adversarial inputs: a rehearsal this build cannot run, or cannot trust, never blocks the gate
    and never spends a dispatch (M6)."""
    for name, value in (("raises", RuntimeError("boom")), ("findings is None", {"findings": None}),
                        ("findings is not a list", {"findings": "x"}), ("findings absent", {}),
                        ("not even a dict", "garbage")):
        rig = Rig(script=[value])
        try:
            result = rig.enter()
            check(f"{name}: the gate is shown", is_person(result), repr(result))
            check_eq(f"{name}: nothing was repaired, nobody was called", (rig.log, rig.conductors), ([("rehearse", "A")], []))
            check_in(f"{name}: L7 says it", "gate A rehearsal could not run (", rig.out)
            check_in(f"{name}: and that the gate is shown without it", "the gate is shown without it", rig.out)
            check_not_in(f"{name}: the packet has no list at its top", "What the factory could not repair", result.text)
            check_eq(f"{name}: no series is kept", rig.series(), {})
        finally:
            rig.close()
    # an empty set: L1, the gate, no round and no record. Not-fixable findings are an empty set too (an older
    # build writes no `class`; a person's question is not ours to repair).
    others = [finding("case_versions", 1, klass="person_decides"), {"check": "gate_decision", "message": "no class"},
              {"class": FIXABLE, "message": "no check"}, {"class": FIXABLE, "check": 7, "message": "check is no text"},
              "not a finding", None]
    for name, findings in (("empty", []), ("not factory_fixable", others)):
        rig = Rig(findings=findings)
        try:
            result = rig.enter()
            check(f"{name}: the gate is shown", is_person(result), repr(result))
            check_in(f"{name}: L1", "gate A rehearsal: nothing the factory has to repair — the gate is shown", rig.out)
            check_eq(f"{name}: nothing is repaired, no record is made",
                     (rig.log, rig.conductors, rig.series(), (rig.task_root / "state/driver-runs.jsonl").exists()),
                     ([("rehearse", "A")], [], {}, False))
        finally:
            rig.close()
    # a waived block never reaches the driver: gate_preflight's own `add` drops it (a real Rehearsal, a real waiver)
    import gate_preflight
    rig = Rig()
    try:
        rehearsal = gate_preflight.Rehearsal(rig.task_root, "A")
        rehearsal.pipeline = {"stage_overrides": [{"stage": "S5", "decision": "go on", "match": "not pinned"}]}
        rehearsal.add("case_versions", gate_preflight.FACTORY_FIXABLE, "a case the gate approves is not pinned at its current bytes: X")
        check_eq("a waived block is not raised again by the rehearsal itself", rehearsal.findings, [])
        rig.script = [{"findings": rehearsal.findings}]
        result = rig.enter()
        check_eq("and with it gone the gate is shown, no round", (is_person(result), rig.calls("rework"), rig.calls("case_versions")), (True, [], []))
    finally:
        rig.close()
    # an unknown check: no move applies -> the conductor once; the next entry shows the gate
    rig = Rig(findings=[finding("mystery_check", 1, "something this build has never heard of")])
    try:
        check("an unknown check is the conductor's: no Person yet", rig.enter() == "returned")
        check_eq("no move was made, one conductor call", (rig.log, len(rig.conductors)), ([("rehearse", "A")], 1))
        check_eq("with the reason `no_move`", rig.series()["rounds"][-1]["stop"], "no_move")
        check_in("L5 (no-move form)", "gate A repair: 1 thing(s) no code move repairs — the list goes to the conductor", rig.out)
        shown = rig.enter()
        check_eq("then the gate, with the thing at its top, and no second call",
                 (is_person(shown), "something this build has never heard of" in shown.text, len(rig.conductors)), (True, True, 1))
    finally:
        rig.close()
    # 8 unpinned cases listed (AT) and 9 (BEYOND: gate_preflight lists unpinned[:8]): `--all` pins every case,
    # so ONE round clears all of them and the next rehearsal is empty
    for listed in (8, 9):
        rig = Rig(script=[{"findings": [finding("case_versions", n, f"unpinned {n}") for n in range(1, min(listed, 8) + 1)]},
                          {"findings": []}])
        try:
            check_eq(f"{listed} unpinned: a round runs", rig.enter(), "returned")
            check_eq(f"{listed} unpinned: ONE `--all` and its `--verify`, no dispatch",
                     (rig.calls("case_versions"), rig.calls("rework")), ([("case_versions", "--all"), ("case_versions", "--verify")], []))
            result = rig.enter()
            check_eq(f"{listed} unpinned: then the gate, with nothing left to say", (is_person(result), len(rig.series()["rounds"])), (True, 1))
        finally:
            rig.close()


def open_question_and_kept_answer() -> None:
    """(iii) nothing is repaired under a question a person is reading (M7); (iv) nothing after they spoke (C3)."""
    rig = Rig()
    try:
        rig.driver.state["asked"] = {"kind": "gate_A", "stage": "S4", "dispatch": ""}
        (rig.task_root / "state" / "driver-question.md").write_text("# Driver question\nkind: gate_A\n", encoding="utf-8")
        result = rig.enter()
        check("an open gate question: the gate is shown as today", is_person(result), repr(result))
        check_eq("(iii) nothing was rehearsed, repaired or asked of the conductor", (rig.log, rig.conductors), ([], []))
        check_in("L8 says why", "gate A: a question about this gate is already open — nothing is repaired under it", rig.out)
        (rig.task_root / "state" / "driver-question.md").unlink()
        rig.driver.state["asked"] = {"kind": "gate_A"}
        result = rig.enter()
        check_eq("a flag with no question file is no open question: the rehearsal runs", (result, rig.calls("rehearse")), ("returned", [("rehearse", "A")]))
        rig2 = Rig()
        try:
            rig2.driver.state["asked"] = {"kind": "gate_B", "stage": "S8"}
            (rig2.task_root / "state" / "driver-question.md").write_text("kind: gate_B\n", encoding="utf-8")
            check_eq("a question about the OTHER gate does not hold this one", rig2.enter(), "returned")
        finally:
            rig2.close()
    finally:
        rig.close()
    # C3: a kept, unrecorded answer is recorded again, never rehearsed under and never asked again
    rig = Rig()
    try:
        words = "approve\nThe question branches stand as they are."       # C1-4b: an approval is its first-line word
        rig.driver.state["gate_answer_kept"] = {"gate": "A", "words": words, "at": "t", "source_revision": "src-1"}
        recorded = []
        rig.driver.record_by_code = lambda kind, stage, w, again=False: recorded.append((kind, w, again)) or True
        result = rig.enter()
        check_eq("C3: the kept words go straight to the gate decision (again)", (result, recorded), ("returned", [("gate_A", words, True)]))
        check_eq("C3: and nothing was rehearsed or repaired", rig.log, [])
        rig.driver.record_by_code = lambda kind, stage, w, again=False: recorded.append("again") or False
        result = rig.enter()
        check("C3: a decision that still does not record shows the gate (today's behaviour)", is_person(result), repr(result))
        check_eq("C3: with no repair under the words", (rig.log, rig.conductors), ([], []))
        rig.driver.state["gate_answer_kept"]["source_revision"] = "src-OLD"
        recorded.clear()
        check_eq("an answer kept at another story revision is not an answer to this gate: the rehearsal runs",
                 (rig.enter(), recorded, rig.calls("rehearse")), ("returned", [], [("rehearse", "A")]))
        rig.driver.state["gate_answer_kept"] = {"gate": "B", "words": words, "source_revision": "src-1"}
        rig.log.clear()
        rig.enter()
        check_eq("an answer kept for gate B is not gate A's", rig.calls("rehearse"), [("rehearse", "A")])
    finally:
        rig.close()
    # the answer path keeps the words BEFORE the conductor sees them; a decision that records clears them and the series
    rig = Rig()
    try:
        d = rig.driver
        d.state["asked"] = {"kind": "gate_A", "stage": "S4", "dispatch": ""}
        d.state["gate_repair"] = {"A": {"source_revision": "src-1", "rounds": [{"keys": [], "stop": ""}]}}
        d.save_state()
        question = rig.task_root / "state" / "driver-question.md"
        question.write_text("# Driver question\nkind: gate_A\nstage: S4\n\nthe gate\n", encoding="utf-8")
        answer = rig.root / "answer.md"
        answer.write_bytes(b"approve\ngo on.")
        seen = []
        d.record_by_code = lambda kind, stage, w, again=False: False
        d.conductor = lambda text, *, words="", files=None, words_file=None: seen.append(dict(d.state.get("gate_answer_kept") or {})) or {"action": "continue", "did": "x"}
        with contextlib.redirect_stdout(io.StringIO()):
            d.take_answer(answer)
        check_eq("C3: the words are kept BEFORE the conductor is called", [s.get("words") for s in seen], ["approve\ngo on."])
        kept = json.loads((rig.task_root / "state/driver-state.json").read_text(encoding="utf-8"))["gate_answer_kept"]
        check_eq("and in the state file, for the gate and the revision", (kept["gate"], kept["source_revision"]), ("A", "src-1"))
        # the decision records (the real method, the controller call replaced): the kept words and the series go
        d2 = rig.relaunch()
        d2.report_attribution = lambda gate, words: {}
        d2.py = lambda script, *args, check=False, expect="": (0, "{}")      # C1-7c Q-3: the real `py`'s signature; exit 0, `check` never raises
        with contextlib.redirect_stdout(io.StringIO()):
            ok = d2.record_by_code("gate_A", "S4", "approve\ngo on.")
        check_eq("a decision that records ends the series and the kept answer",
                 (ok, "gate_answer_kept" in d2.state, "A" in (d2.state.get("gate_repair") or {})), (True, False, False))
    finally:
        rig.close()


def series_stamp() -> None:
    """C7: a series belongs to one story revision, and ends with the gate's approval at that revision."""
    stale = {"A": {"source_revision": "src-OLD", "rounds": [{"keys": [["x", "y"]], "moves": [], "outcome": "repaired", "stop": ""},
                                                           {"keys": [["x", "z"]], "moves": [], "outcome": "repaired", "stop": ""}]}}
    rig = Rig()
    try:
        rig.driver.state["gate_repair"] = json.loads(json.dumps(stale))
        check_eq("a series of another revision is dropped: a round runs although two were spent", rig.enter(), "returned")
        series = rig.series()
        check_eq("and the new series starts at the current revision with ONE round", (series["source_revision"], len(series["rounds"])), ("src-1", 1))
    finally:
        rig.close()
    rig = Rig()
    try:
        rig.driver.state["gate_repair"] = {"A": {"source_revision": "src-1", "rounds": [{"keys": [["x", "y"]], "moves": [], "outcome": "repaired", "stop": ""},
                                                                                         {"keys": [["x", "z"]], "moves": [], "outcome": "repaired", "stop": ""}]}}
        check("the same revision keeps its two rounds: the cap stops a third", rig.enter() == "returned" and rig.calls("rework") == [])
        check_eq("(the stop is the cap)", rig.series()["rounds"][-1]["stop"], "cap")
    finally:
        rig.close()
    # an approved decision of the gate at the current revision ends the series; one at an older revision does not
    # (it would reset the cap at every await_gate: unbounded spend)
    rig = Rig()
    try:
        path = rig.task_root / "state" / "controller.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["decisions"] = {"gateA-old": {"gate": "A", "status": "approved", "source_revision": "src-OLD"}}
        path.write_text(json.dumps(data), encoding="utf-8")
        rig.driver.state["gate_repair"] = {"A": {"source_revision": "src-1", "rounds": [{"keys": [["x", "y"]], "moves": [], "outcome": "repaired", "stop": ""},
                                                                                         {"keys": [["x", "z"]], "moves": [], "outcome": "repaired", "stop": ""}]}}
        rig.enter()
        check_eq("an approved decision of an OLDER revision does not reset the cap", rig.series()["rounds"][-1]["stop"], "cap")
        data["decisions"] = {"gateA-now": {"gate": "A", "status": "approved", "source_revision": "src-1"}}
        path.write_text(json.dumps(data), encoding="utf-8")
        rig.log.clear()
        rig.enter()
        check_eq("an approved decision at the CURRENT revision ends the series: a fresh one starts",
                 (len(rig.series()["rounds"]), rig.series()["rounds"][0]["stop"]), (1, ""))
    finally:
        rig.close()


def empty_scope_and_failed_repair() -> None:
    """F8: a critic rework with an empty scope is never registered (M8). A failed move is printed, recorded and
    handed to the conductor with its output - never silent (M9), never repeated blindly."""
    # the designer's cases are not pinned and no re-pin is planned: nothing to review
    rig = Rig(findings=[finding("gate_decision", 1, "the gate A decision will NOT record: x")], pinned=[])
    try:
        result = rig.enter()
        check_eq("F8: no critic rework is registered over an empty scope", (result, rig.calls("rework")), ("returned", []))
        check_eq("F8: the conductor gets it, once, as `no_move`", (len(rig.conductors), rig.series()["rounds"][-1]["stop"]), (1, "no_move"))
    finally:
        rig.close()
    # the designer has an empty scope of its own: same
    rig = Rig(findings=[finding("gate_decision", 1, "x")], pinned=CASES)
    try:
        rig.driver.controller_state = lambda: {"source_revision": "src-1", "stages": {"S4": {"status": "completed"}},
                                               "dispatches": {C1: {"scope": CASES}, D2: {"scope": []}}}
        rig.enter()
        check_eq("F8: a designer with an empty scope gives no critic round", (rig.calls("rework"), len(rig.conductors)), ([], 1))
    finally:
        rig.close()
    # the re-pin is planned, the cases of the designer round get pinned by it: the critic's scope is cut AFTER it
    rig = Rig(pinned=REWORKED[:3])
    try:
        rig.enter()
        check_eq("the critic reviews the designer's cases that are pinned when its turn comes",
                 rig.calls("rework"), [("rework", "qa-case-critic", tuple(REWORKED[:3]), "test_defect")])
    finally:
        rig.close()
    # M9: case_versions fails -> no critic, a recorded `failed` round, the conductor with the command and its tail
    rig = Rig()
    try:
        rig.pin_exit, rig.pin_text = 2, "\n".join(f"line {n}" for n in range(1, 31))
        result = rig.enter()
        check("M9: a failed re-pin is handed on, not raised and not swallowed", result == "returned", repr(result))
        check_eq("M9: the critic is NOT dispatched after a failed re-pin", rig.calls("rework"), [])
        check_eq("M9: the conductor was called once", len(rig.conductors), 1)
        check_in("L6 names the command, its exit and where its output goes",
                 "gate A repair: case_versions.py --all, then --verify failed (exit 2) — its output goes to the conductor", rig.out)
        text = rig.first()
        check_in("the conductor gets the command", "case_versions.py --all, then --verify failed (exit 2)", text)
        check_in("and the LAST 20 lines of its output", "line 30", text)
        check_in("(from line 11 on)", "line 11", text)
        check_not_in("(and not the first ten)", "line 10\n", text)
        last = rig.series()["rounds"][-1]
        check_eq("the round is recorded as failed, with its reason", (last["outcome"], last["stop"], last["moves"]),
                 ("failed", "failed", ["pin_cases (failed)"]))
        shown = rig.enter()
        check_eq("the same move is not repeated: the next entry shows the gate, no second call",
                 (is_person(shown), len(rig.calls("case_versions")), len(rig.conductors)), (True, 1, 1))
    finally:
        rig.close()
    # the controller refuses the rework: failed, with the controller's words to the conductor
    import story_run
    rig = Rig()
    try:
        rig.rework_error = story_run.ReworkRefused("controller rework (exit 2):\nStateConflict: qa-case-critic has already had 2 repair round(s)")
        check("a refused rework is handed on", rig.enter() == "returned")
        check_in("with the controller's own words", "already had 2 repair round(s)", rig.first())
        check_eq("and recorded", (rig.series()["rounds"][-1]["outcome"], rig.series()["rounds"][-1]["moves"]),
                 ("failed", ["pin_cases", "revise_plan", "critic_rework (refused)"]))
    finally:
        rig.close()
    # a refusal of the ROLE's own run is not a failed repair: it reaches `guarded` and the known table, the round counts
    rig = Rig()
    try:
        rig.rework_error = story_run.Refusal("handoff_check: handover form S4-qa-case-critic-2.yaml is not ready")
        result = rig.enter()
        check("a role-run refusal propagates, unclassified by the step", isinstance(result, story_run.Refusal) and not isinstance(result, story_run.ReworkRefused), repr(result))
        check_eq("the round was recorded before the dispatch (it spent something)", rig.series()["rounds"][-1]["outcome"], "started")
        check_eq("and no conductor was called by the step", rig.conductors, [])
    finally:
        rig.close()


def list_goes_through_the_conductor_not_the_table() -> None:
    """M10: the findings are the factory's own words, not a refusal: a finding that holds a phrase of
    KNOWN_REFUSALS must not turn into `continue`, `retry` or a question to the person."""
    import story_run
    phrases = ["the stage was already completed", "StateConflict: expected_revision 4 revision conflict",
               "STORY BUDGET: past its ceiling", "executor unavailable"]
    check("fixture: each phrase IS one the table matches", all(story_run.match_known(p) for p in phrases))
    rig = Rig(findings=[finding("mystery_check", n, p) for n, p in enumerate(phrases, 1)])
    try:
        result = rig.enter()
        check("9: a list full of table phrases does not become a question or a retry", result == "returned", repr(result))
        check_eq("9: the conductor is called ONCE, with the whole list", len(rig.conductors), 1)
        for p in phrases:
            check_in(f"9: the conductor reads `{p[:24]}`", p, rig.first())
        names = [r.get("action") for r in jsonl(rig.task_root / "state/conductor.jsonl")]
        check_eq("9: and no `known:` row was journalled for it", [n for n in names if str(n).startswith("known:")], [])
    finally:
        rig.close()
    # the conductor's verdicts: continue -> back to where; ask_person -> the person, with the conductor's question
    rig = Rig(findings=[finding("mystery_check", 1, "x")])
    try:
        rig.verdict = {"action": "ask_person", "did": "looked", "options": SEAM_TWO, "why_person": "access", "checked": "the refusal",
                       "question": "Which stand should the cases run on? Say `retry` once one is up, or `stop`."}
        result = rig.enter()
        check("the conductor's ask_person is the person's, kind conductor",
              is_person(result, "conductor") and "Which stand should the cases run on?" in result.text, repr(result))
        check("and it carries its options with their price lines", list(result.offered) == ["retry", "stop"]
              and "\nthe factory: " in result.text, repr(result))
    finally:
        rig.close()


def designer_round_and_cap() -> None:
    """F2/C5: a critic that did not approve sends the designer back over the critic's own scope - only while a round
    is left for the critic that follows, and the designer's own cap has room; else the gate, with the critic's
    findings at its top and no conductor."""
    gd = [finding("gate_decision", 1, "the gate A decision will NOT record: the case critic's own declared verdict is 'concerns'")]
    behind = reviews_after(author=D1, critic=C1, verdict="concerns")        # the designer is BEFORE the critic
    rig = Rig(findings=gd, reviews=behind)
    try:
        findings_file = rig.task_root / "work" / "test-cases" / "critic-findings.md"
        findings_file.parent.mkdir(parents=True)
        findings_file.write_text("verdict: concerns\nTC_004 asserts nothing about the ghost node\n", encoding="utf-8")
        check_eq("F2 a: the first round is the designer's", rig.enter(), "returned")
        check_eq("over the critic dispatch's own scope, as a round about the test",
                 rig.calls("rework"), [("rework", "qa-case-designer", tuple(CASES), "test_defect")])
        check_in("L4b names the cases, the critic and the designer round", f"the case designer reworks the 9 case(s) the critic did not approve in {C1}: ", rig.out)
        check_in("(designer round 1 of 2)", "(designer round 1 of 2)", rig.out)
        check_in("the designer's reason is the critic's findings", "TC_004 asserts nothing about the ghost node", rig.reasons[0])
        check_eq("the round holds the designer move", rig.series()["rounds"][0]["moves"], ["designer_rework"])
    finally:
        rig.close()
    # the designer round has run (one round spent): a second designer round would leave no round for its critic
    rig = Rig(findings=gd, reviews=behind)
    try:
        findings_file = rig.task_root / "work" / "test-cases" / "critic-findings.md"
        findings_file.parent.mkdir(parents=True)
        findings_file.write_text("verdict: concerns\n", encoding="utf-8")
        rig.driver.state["gate_repair"] = {"A": {"source_revision": "src-1", "rounds": [
            {"keys": [["gate_decision", "earlier"]], "moves": ["critic_rework"], "outcome": "repaired", "stop": ""}]}}
        result = rig.enter()
        check("C5/F2 c: no round left for a critic: the gate is shown", is_person(result), repr(result))
        check_eq("C5: no designer round, no conductor", (rig.calls("rework"), rig.conductors), ([], []))
        check_in("with the finding at the top", "the case critic's own declared verdict is 'concerns'", result.text)
        check_in("and where the critic's findings are", "qa-factory/artifacts/QA-9/work/test-cases/critic-findings.md", result.text)
        check_eq("the stop is recorded", rig.series()["rounds"][-1]["stop"], "no_move")
    finally:
        rig.close()
    # the designer's own cap is spent, or cannot be read: the same
    for name, budget in (("spent", {"counted": 2, "cap": 2}), ("unreadable", None), ("no numbers", {"counted": "x"})):
        rig = Rig(findings=gd, reviews=behind, budget=budget)
        try:
            result = rig.enter()
            check_eq(f"designer cap {name}: the gate with the list, no designer, no conductor",
                     (is_person(result), rig.calls("rework"), rig.conductors), (True, [], []))
        finally:
            rig.close()
    # a critic that did not approve and NO designer round after it, but also nothing for the designer to rework
    rig = Rig(findings=gd, reviews=reviews_after(author=D1, critic="S4-qa-case-critic-9", verdict="concerns"))
    try:
        rig.enter()
        check_eq("a critic dispatch with no scope of its own gives no designer round", (rig.calls("rework"), len(rig.conductors)), ([], 1))
    finally:
        rig.close()
    # M2's twin: designer round 1, then (re-pin + critic) round 2, then a third round is refused
    rig = Rig(script=[{"findings": gd}, {"findings": gd + [finding("case_versions", 1, "unpinned")]}, {"findings": gd}],
              reviews=behind)
    try:
        rig.enter()
        rig.reviews = reviews_after(author=D2, critic=C1, verdict="concerns")       # the designer's rework is now accepted
        rig.enter()
        check_eq("round 1 is the designer, round 2 re-pins and THEN the critic",
                 [e for e in rig.log if e[0] in ("rework", "case_versions")],
                 [("rework", "qa-case-designer", tuple(CASES), "test_defect"), ("case_versions", "--all"), ("case_versions", "--verify"),
                  ("rework", "qa-case-critic", tuple(REWORKED), "test_defect")])
        rig.add_dispatch("S4-qa-case-critic-2", "qa-case-critic", REWORKED)
        rig.reviews = reviews_after(author=D2, critic="S4-qa-case-critic-2", verdict="concerns")
        rig.order["S4-qa-case-critic-2"] = 3
        result = rig.enter()
        check("a critic that rejects again after two rounds: the gate, with the list", is_person(result), repr(result))
        check_eq("no third dispatch and no conductor", (len(rig.calls("rework")), rig.conductors), (2, []))
    finally:
        rig.close()


def critic_fixes_t214() -> None:
    """t-214 attempt 2: C1 the plan is revised to the pinned ids after the re-pin (M12); C2 a repaired round owes the
    next gate entry the case appendix again (M13); C3 a kept answer that still does not record is asked again only
    with their words and the controller's refusal on top (M14); C4 the critic's findings are a gate A line only."""
    import story_run
    # C1: pin, then revise_plan, then the critic; a refused revise_plan is a failed round and no critic is dispatched
    rig = Rig()
    try:
        rig.revise_error = story_run.Refusal("controller revise_plan (exit 2):\nStateConflict: scope is stale")
        result = rig.enter()
        check_eq("C1: a failed revise_plan is handed on, no critic is dispatched after it",
                 (result, [e[0] for e in rig.log if e[0] in ("case_versions", "revise_plan", "rework")], len(rig.conductors)),
                 ("returned", ["case_versions", "case_versions", "revise_plan"], 1))
        last = rig.series()["rounds"][-1]
        check_eq("C1: the round is recorded as failed at revise_plan", (last["outcome"], last["moves"]), ("failed", ["pin_cases", "revise_plan (failed)"]))
        check_in("C1: and the conductor is told which command", "controller.py --operation revise_plan failed (exit 2)", rig.first())
    finally:
        rig.close()
    # C2: the appendix a repaired round's moves changed is rendered again, AFTER them, at the next gate entry
    rig = Rig(script=[{"findings": cmp2_findings()}, {"findings": []}])
    try:
        appendix = rig.task_root / "work" / "case-appendix.md"
        rig._render_appendix()
        before = appendix.read_bytes()
        check_eq("C2: round 1 repaired", rig.enter(), "returned")
        check_eq("C2: a repaired round owes the next entry the appendix", list((rig.driver.state.get("gate_entry_owed") or {})), ["S4"])
        result = rig.enter()
        check("C2: the next entry shows the gate", is_person(result), repr(result))
        names = [e[0] for e in rig.log]
        check("C2: the appendix is rendered after the moves and BEFORE the rehearsal that follows them",
              names[-2:] == ["render_appendix", "rehearse"] and names.index("rework") < len(names) - 2, str(names))
        check_eq("C2: its bytes are not the pre-round ones (they carry the moves)", (appendix.read_bytes() != before, appendix.read_text(encoding="utf-8")),
                 (True, "appendix after 4 move(s)\n"))
        check_eq("C2: and it is owed once", rig.driver.state.get("gate_entry_owed"), {})
    finally:
        rig.close()
    # C3: the kept answer does not record again: the gate is asked with their words and the refusal on top
    words = "approve\n" + "x" * 190 + "TAIL-NOT-SHOWN" + "y" * 100       # C1-4b: only an approval is kept, so the kept words start with the word
    for size, cut in ((2000, False), (2001, True)):
        rig = Rig()
        try:
            refusal = "R" * size
            rig.driver.py = lambda script, *a, check=False, refusal=refusal: (2, refusal) if script == "controller.py" else (0, "")
            rig.driver.state["gate_answer_kept"] = {"gate": "A", "words": words, "at": "2026-10-01T05:00:00", "source_revision": "src-1"}
            result = rig.enter()
            check(f"C3 ({size}): a kept answer that does not record shows the gate", is_person(result), repr(result))
            text = result.text if is_person(result) else ""
            check_in(f"C3 ({size}): the top block says their words are kept", "Your earlier answer is kept, and it did not record", text)
            check_in(f"C3 ({size}): and when they gave them", "2026-10-01T05:00:00", text)
            check_in(f"C3 ({size}): the first 200 characters of the words", " ".join(words.split())[:200], text)
            check_not_in(f"C3 ({size}): and not what follows them", "TAIL-NOT-SHOWN", text)
            check_in(f"C3 ({size}): the controller's refusal, whole up to 2000", "R" * 2000, text)
            check_eq(f"C3 ({size}): cut only beyond 2000 characters, and it says so",
                     ("R" * 2001 in text, "(cut at 2000 characters)" in text), (False, cut))
            check("C3: the packet is no longer the one they answered: the block stands above it", text.index("Your earlier answer") < text.index("the packet"))
            check_eq("C3: nothing was rehearsed or repaired under their words", (rig.calls("rehearse"), rig.calls("rework")), ([], []))
        finally:
            rig.close()
    # C4: the critic's findings file is a gate A line; at B the same check id is about the delivery decision
    rig = Rig()
    try:
        findings_file = rig.task_root / "work" / "test-cases" / "critic-findings.md"
        findings_file.parent.mkdir(parents=True)
        findings_file.write_text("verdict: concerns\n", encoding="utf-8")
        gd = [finding("gate_decision", 1, "the gate decision will NOT record: x")]
        check_in("C4: at gate A the critic's findings are named", "The case critic's own findings:", rig.driver.unrepaired_text("A", gd))
        check_not_in("C4: at gate B they are not", "The case critic's own findings", rig.driver.unrepaired_text("B", gd))
    finally:
        rig.close()


def what_the_step_reads() -> None:
    """The step reads the CONTROLLER (not the pipeline.json mirror), the `accept` events (not dispatch numbers),
    and only `check`/`class`/`message` of a finding (never its wording)."""
    rig = Rig()
    try:
        d = rig.driver
        check_eq("the controller says S4 is completed", d.stage_completed("S4"), True)
        pipeline = json.loads((rig.task_root / "pipeline.json").read_text(encoding="utf-8"))["stages"]["S4"]
        check_eq("while the pipeline.json mirror still names an active dispatch (the cmp2 shape)",
                 (pipeline["status"], pipeline["active_dispatch_id"]), ("done", "S4-qa-case-critic-2"))
        path = rig.task_root / "state" / "controller.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["stages"]["S4"]["status"] = "running"
        path.write_text(json.dumps(data), encoding="utf-8")
        check_eq("a controller that holds the stage open is not completed, whatever the mirror says", d.stage_completed("S4"), False)
        check_eq("an unknown stage is not completed", d.stage_completed("S9"), False)
    finally:
        rig.close()
    # accept_order from a real events file: the position of each `accept`, dispatch events and garbage ignored
    rig = Rig()
    try:
        events = rig.task_root / "state" / "events.jsonl"
        rows = [{"type": "dispatch", "payload": {"id": C1}}, {"type": "accept", "payload": {"id": C1}},
                {"type": "dispatch", "payload": {"id": D2}}, {"type": "accept", "payload": {"id": D2}}, {"type": "accept", "payload": {"note": "no id"}},
                {"type": "accept", "payload": {"id": 5}}]      # the store takes object payloads only; a non-string id is ignored
        # Controller.accept_order reads through the store's verified reader (90f9362df, t-1758 Q1): the events are committed
        # through the store (a hash chain), not hand-written lines; a hand-written file is "unknown order" (pinned below)
        import event_store
        events.unlink(missing_ok=True)
        store = event_store.EventStore(rig.task_root)
        for n, row in enumerate(rows):
            store.commit(row["type"], row["payload"], f"k{n}")
        import story_run
        order = story_run.Driver.accept_order(rig.driver)
        check_eq("accept_order: the position of each accept event, in file order", order, {C1: 2, D2: 4})
        with events.open("a", encoding="utf-8") as handle:
            handle.write("not json\n")
        check_eq("accept_order: a broken chain is an unknown order, never a partial one", story_run.Driver.accept_order(rig.driver), {})
        events.unlink()
        check_eq("no events file: no order, no move", story_run.Driver.accept_order(rig.driver), {})
        # a designer accepted BEFORE the critic (the cmp2 order of designer-1) is not a rework after its review
        rig.order = {D2: 0, C1: 1}
        rig.findings = [finding("gate_decision", 1, "x")]
        rig.reviews = reviews_after(author=D2, critic=C1)
        rig.enter()
        check_eq("the move follows the ACCEPT order, not the dispatch numbers: designer-2 before critic-1 gives no critic round",
                 rig.calls("rework"), [])
    finally:
        rig.close()
    # the real rehearsal seam: `gate_preflight.py` as JSON on the half-built story, and every way it can fail
    rig = Rig()
    try:
        import story_run
        real = story_run.Driver(rig.driver.flags)
        result = real.rehearse("A")
        check("rehearse: the real gate_preflight run is a result with a findings list",
              isinstance(result, dict) and isinstance(result.get("findings"), list) and result.get("gate") == "A", str(result)[:300])
        check("and it holds the class word the step reads",
              all(f.get("class") in ("factory_fixable", "person_decides", "factory_defect") for f in result["findings"]))
        for name, reply in (("a non-zero exit", (2, "boom")), ("no JSON", (0, "nothing here")), ("a JSON list", (0, "[1, 2]")),
                            ("a broken object", (0, "{\"findings\": [")), ("nothing at all", (0, ""))):
            real.py = lambda script, *args, check=False, reply=reply: reply
            try:
                real.rehearse("A")
                raised = False
            except RuntimeError:
                raised = True
            check(f"rehearse: {name} raises, and the step shows the gate without it", raised)
        real.py = lambda script, *args, check=False, expect="": (0, "note: x\n" + json.dumps({"findings": []}) + "\nwarning")
        check_eq("rehearse: noise around the JSON object is read past", real.rehearse("A"), {"findings": []})
    finally:
        rig.close()
    # the real design_reviews on a story with no plan: it cannot be built, so no move applies (the safe direction)
    rig = Rig()
    try:
        import story_run
        check_eq("design_reviews that cannot be built is empty", story_run.Driver.design_reviews(rig.driver, "A"), [])
    finally:
        rig.close()
    # the table holds only checks gate_preflight emits (C15), and the class word is its own
    import gate_preflight
    import story_run
    source = (harness.SCRIPTS / "gate_preflight.py").read_text(encoding="utf-8")
    emitted = set(re.findall(r'^\s+check = "([a-z_0-9]+)"', source, re.M)) | set(re.findall(r'self\.(?:add|unavailable)\("([a-z_0-9]+)"', source))
    check("control: the reader finds the checks the rehearsal emits, `gate_decision` and `case_versions` among them",
          {"gate_decision", "case_versions", "question_branches"} <= emitted, str(sorted(emitted)))
    check("control: and does not find a check that is not there", "no_such_check" not in emitted)
    for gate, check_id, precondition, move in story_run.GATE_REPAIRS:
        check(f"C15: the table's check `{check_id}` is a check id gate_preflight emits", check_id in emitted)
        check("C15: its precondition and move exist as methods", callable(getattr(story_run.Driver, precondition, None)) and callable(getattr(story_run.Driver, move, None)))
        check(f"C15: and `{gate}` is a gate gate_preflight knows", gate in gate_preflight.GATE_STAGE)
    check_eq("the class word is gate_preflight's own", story_run.FACTORY_FIXABLE, gate_preflight.FACTORY_FIXABLE)
    check_eq("the stage in front of each gate is gate_preflight's own (the one after it is its GATE_STAGE)",
             {g: s for g, s in story_run.GATE_STAGE_OF.items()}, {"A": "S4", "B": "S8"})
    check("no gate B row: at B every finding goes to the conductor until a B move exists",
          all(row[0] == "A" for row in story_run.GATE_REPAIRS))
    check("the question-branch check is the one that is listed, never routed", story_run.GATE_DIRECT_CHECKS == ("question_branches",))


def gate_b_and_the_list_at_the_top() -> None:
    """F6: gate B goes through the same step; with no B row every finding goes to the conductor once, and the
    list at the top of a gate packet is bounded."""
    rig = Rig(findings=[finding("delivery", 1, "test-report.md is not on disk, and gate B reads it"),
                        finding("delivery", 2, "work/delivery-summary.json is not on disk, and gate B reads it")])
    try:
        check("gate B: the step runs", rig.enter("B") == "returned")
        check_eq("gate B: no move, the conductor once, at the boundary gate_B", (rig.calls("case_versions"), rig.calls("rework"), rig.boundaries), ([], [], ["gate_B"]))
        check_in("gate B: the line says no code move repairs it", "gate B repair: 2 thing(s) no code move repairs — the list goes to the conductor", rig.out)
        shown = rig.enter("B")
        check_eq("gate B: then the gate B question, with the list at its top", (is_person(shown, "gate_B"), "is not on disk" in shown.text), (True, True))
        check_eq("the series of gate B is its own", (rig.series("A"), len(rig.series("B")["rounds"])), ({}, 1))
    finally:
        rig.close()
    # the list at the top: AT the limit every line is shown, BEYOND it the rest is counted
    rig = Rig()
    try:
        d = rig.driver
        top = lambda n: d.unrepaired_text("A", [finding("question_branches", i, f"branch {i}") for i in range(1, n + 1)])
        at, beyond = top(12), top(13)
        check_eq("AT 12: all twelve are listed, none is counted away", (at.count("\n- branch"), "more in the rehearsal" in at), (12, False))
        check_eq("BEYOND (13): twelve are listed and one is counted", (beyond.count("\n- branch"), "(and 1 more in the rehearsal below)" in beyond), (12, True))
        check_eq("a message listed twice is listed once",
                 d.unrepaired_text("A", [finding("question_branches", 1, "same"), finding("question_branches", 2, "same")]).count("- same"), 1)
        # the conductor's list is bounded too: AT 20 every finding, BEYOND it the rest is counted (and pointed to)
        listed = lambda n: d.conductor_text("A", "why", [finding("mystery_check", i, f"thing {i}") for i in range(1, n + 1)], "")
        at20, beyond = listed(20), listed(21)
        check_eq("conductor list AT 20: all twenty, none counted away", (at20.count("\n- [mystery_check-"), "more:" in at20), (20, False))
        check_eq("conductor list BEYOND (21): twenty and one counted, with the command that lists them",
                 (beyond.count("\n- [mystery_check-"), "(and 1 more: `gate_preflight.py --task QA-9 --gate A --text`)" in beyond), (20, True))
        # only question branches: nothing for the conductor, the gate at once (C8)
        rig.findings = [finding("question_branches", 1, "question branches - TS-4 rests on Q4")]
        result = rig.enter()
        check_eq("C8: question branches alone are shown at the top, never put to the conductor",
                 (is_person(result), rig.conductors, "TS-4 rests on Q4" in result.text), (True, [], True))
        check_eq("and the stop is recorded as shown", [(r["stop"], r["outcome"]) for r in rig.series()["rounds"]], [("no_move", "shown")])
    finally:
        rig.close()


def gate_entry_steps_owed_by_a_refused_finish() -> None:
    """C10: the refused finish (F0) raised before S4's case appendix and S8's report rebuild; gate entry runs them
    BEFORE it rehearses - and only then, so the ordinary path is unchanged."""
    rig = Rig()
    try:
        rig.driver.state["gate_entry_owed"] = {"S4": "t"}
        rig.findings = []
        rig.enter()
        check_eq("A, owed: the case appendix is rendered, then the rehearsal runs",
                 [e[0] for e in rig.log][:2], ["render_appendix", "rehearse"])
        check_eq("and it is owed once", rig.driver.state["gate_entry_owed"], {})
        rig.log.clear()
        rig.enter()
        check_eq("not owed any more: only the rehearsal", [e[0] for e in rig.log][:1], ["rehearse"])
        check("no rebuild at gate A", rig.calls("rebuild_report") == [])
    finally:
        rig.close()
    rig = Rig()
    try:
        rig.driver.state["gate_entry_owed"] = {"S8": "t"}
        rig.findings = []
        rig.enter("B")
        check_eq("B, owed: the report is rebuilt, then the rehearsal runs", [e[0] for e in rig.log][:2], ["rebuild_report", "rehearse"])
        check("and no appendix at gate B", rig.calls("render_appendix") == [])
        rig.log.clear()
        rig.driver.state["gate_entry_owed"] = {"S4": "t"}
        rig.findings = []
        rig.enter("B")
        check_eq("what gate A owes is not gate B's", [e[0] for e in rig.log], ["rehearse"])
        rig.log.clear()
        rig.driver.state["gate_entry_owed"] = {}
        rig.enter("A")
        check_eq("nothing owed: the ordinary path runs neither step", [e[0] for e in rig.log], ["rehearse"])
    finally:
        rig.close()


def dry_run_writes_nothing() -> None:
    """--dry-run: "would: rehearse gate X, then repair: <moves>"; nothing is written, dispatched or asked."""
    rig = Rig()
    try:
        rig.driver.dry = True
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rig.driver.where = lambda: {"action": "await_gate", "gate": "A", "revision": 3}
            code = rig.driver.describe()
        text = out.getvalue()
        check_eq("describe exits 0", code, 0)
        check_in("it says what it would do", "would: rehearse gate A, then repair: case_versions: pin move; gate_decision: review move; "
                 "to the conductor or the top of the gate: question_branches (at most 2 rounds)", text)
        check_in("and still how the question would be written", "would: write state/driver-question.md", text)
        check_eq("the rehearsal is read, nothing else", rig.log, [("rehearse", "A")])
        check_eq("no dispatch, no conductor", (rig.calls("rework"), rig.conductors), ([], []))
        state_dir = rig.task_root / "state"
        check("no state file and no journal line is written",
              not (state_dir / "driver-state.json").exists() and not (state_dir / "driver-runs.jsonl").exists())
        with contextlib.redirect_stdout(io.StringIO()) as again:
            returned = rig.driver.gate_repair("A")
        check_eq("the step itself prints the same and returns the gate",
                 (returned, rig.driver.state.get("gate_repair"), again.getvalue().startswith("would: rehearse gate A, then repair:")),
                 ({"ran": False, "top": ""}, None, True))
        rig.script = [RuntimeError("boom")]
        with contextlib.redirect_stdout(io.StringIO()):
            line = rig.driver.gate_repair_would("A")
        check_in("a rehearsal that cannot run is said, in the dry run too", "which could not run now (RuntimeError: boom)", line)
    finally:
        rig.close()


def a_story_from_before_the_change() -> None:
    """§4: a state file with no `gate_repair` key is an empty series (cmp2 relaunched: gate A asked, critic-2 accepted,
    the S4 waiver recorded)."""
    rig = Rig(findings=[])
    try:
        state_file = rig.task_root / "state" / "driver-state.json"
        old = {"sessions": {}, "pending_words": {}, "asked": {"kind": "gate_A", "stage": "S4", "dispatch": ""}, "interrupted": {}}
        state_file.write_text(json.dumps(old), encoding="utf-8")
        question = rig.task_root / "state" / "driver-question.md"
        question.write_text("# Driver question\nkind: gate_A\nstage: S4\n", encoding="utf-8")
        d = rig.relaunch()
        check_eq("the old state has no series", d.state.get("gate_repair"), None)
        result = rig.enter()
        check_eq("question still open: nothing is rehearsed or repaired (today's behaviour)", (is_person(result), rig.log), (True, []))
        question.unlink()
        with contextlib.redirect_stdout(io.StringIO()):
            said = d.reconcile_question()
        check_in("the flag with no file is cleared by the existing reconcile", "no driver-question.md", said)
        result = rig.enter()
        check_eq("then the rehearsal runs, finds nothing, and the gate is shown with no round",
                 (is_person(result), rig.log, rig.series()), (True, [("rehearse", "A")], {}))
        check_not_in("the packet has no list at its top", "What the factory could not repair", result.text)
    finally:
        rig.close()


# --- t-261: the two code rows the t-241 wave left to the driver: `s5_runtime_probe` and `unraised_questions` -------------
# t-218 W5: the probe the rehearsal derived and the stand proved is registered by the driver, from the finding's `argv`
# FIELD; the config's portable form (`{python}`, `{plugin_root}`) is resolved with `runtime_probe.resolve_argv` first, an
# older absolute argv runs as written, and an argv with any other `{token}` is never executed.

def portable_probe(profile="api", **extra):
    return ["{python}", "{plugin_root}/scripts/runtime_probe.py", "--suggest", "--write", "--profile", profile,
            "--environment", "localhost", "--container", f"{profile}-c", "--checkout", "../../testproject1",
            "--app-root", "/app", "--task-root", "/stories/QA-9"]


def probe_finding(profile="api", argv=None, n=1) -> dict:
    return finding("s5_runtime_probe", n, f"`{profile}`: `{profile}-c` runs this story's code (3 file(s) compared by content) "
                   "and no probe is registered for it yet.", profile=profile,
                   **({} if argv is False else {"argv": portable_probe(profile) if argv is None else argv}))


def repair_rows_probe_and_unraised() -> None:
    import hooklib
    import story_run
    # the rows exist, in the table and in the words of the counts
    check("t-261: the table has the two rows, both for gate A",
          [(g, c) for g, c, _p, _m in story_run.GATE_REPAIRS if c in ("s5_runtime_probe", "unraised_questions")]
          == [("A", "unraised_questions"), ("A", "s5_runtime_probe")])
    check_eq("t-261: the counts name both in words, not ids", (story_run.CHECK_WORDS["s5_runtime_probe"], story_run.CHECK_WORDS["unraised_questions"]),
             ("stand probe to register", "questions not yet raised"))
    # (a) the derived probe: portable argv -> resolved BEFORE it runs
    rig = Rig(findings=[probe_finding()], reviews=[])
    try:
        ran = []
        rig.driver.run_argv = lambda argv: ran.append(list(argv)) or (0, "wrote")
        result = rig.enter()
        check("probe row: the round ran (no Person)", result == "returned", repr(result))
        check_eq("probe row: ONE command was run", len(ran), 1)
        resolved = ran[0] if ran else []
        check_eq("probe row: `{python}` is this interpreter and `{plugin_root}` is the plugin (resolve_argv ran first)",
                 resolved[:2], [sys.executable, str(hooklib.PLUGIN_ROOT) + "/scripts/runtime_probe.py"])
        check_eq("probe row: the rest of the argv is the finding's own, element for element", resolved[2:], portable_probe()[2:])
        check_not_in("probe row: no `{token}` reaches the command line", "{", " ".join(resolved))
        check_in("probe row: it says what it did", "gate A repair: the probe the stand proved is registered for `api`", rig.out)
        check_eq("probe row: the round is recorded with that move and as repaired",
                 (rig.series()["rounds"][0]["moves"], rig.series()["rounds"][0]["outcome"]),
                 (["runtime_probe --suggest --write api"], "repaired"))
        check_eq("probe row: no conductor was called", rig.conductors, [])
    finally:
        rig.close()
    # a LEGACY absolute argv has no token and runs exactly as written
    legacy = [r"C:\old\python.exe", r"C:\old\plugin\scripts\runtime_probe.py", "--suggest", "--write", "--profile", "api"]
    rig = Rig(findings=[probe_finding(argv=legacy)], reviews=[])
    try:
        ran = []
        rig.driver.run_argv = lambda argv: ran.append(list(argv)) or (0, "wrote")
        rig.enter()
        check_eq("probe row: an older config's ABSOLUTE argv runs as written (the temporal edge: both worlds)", ran, [legacy])
    finally:
        rig.close()
    # an argv with an UNKNOWN token is refused, naming the two that exist, and never run
    for bad in (["{python}", "{foo}/scripts/runtime_probe.py", "--suggest", "--write"],
                ["{python}", "{plugin_root}/scripts/runtime_probe.py", "--checkout", "{project}/x"]):
        rig = Rig(findings=[probe_finding(argv=bad)], reviews=[])
        try:
            ran = []
            rig.driver.run_argv = lambda argv: ran.append(list(argv)) or (0, "wrote")
            rig.enter()
            check_eq(f"probe row: an unknown token ({[a for a in bad if '{' in a and 'plugin_root' not in a and a != '{python}'][0][:12]}...) is NEVER executed", ran, [])
            first = rig.first()
            for word in ("{python}", "{plugin_root}", "was not run"):
                check_in(f"probe row: the refusal handed to the conductor names `{word}`", word, first)
            check_in("probe row: and the unknown one", "{foo}" if "{foo}/scripts/runtime_probe.py" in bad else "{project}", first)
            check_eq("probe row: the round is recorded as failed, the series stops", (rig.series()["rounds"][0]["outcome"], rig.series()["rounds"][0]["stop"]),
                     ("failed", "failed"))
        finally:
            rig.close()
    # the command fails: failed round, its output goes to the conductor (never a blind second try)
    rig = Rig(findings=[probe_finding()], reviews=[])
    try:
        rig.driver.run_argv = lambda argv: (2, "config.json is read-only")
        rig.enter()
        check_in("probe row: a failing write goes to the conductor with its own words", "config.json is read-only", rig.first())
        check_eq("probe row: ...as a failed round", rig.series()["rounds"][0]["outcome"], "failed")
    finally:
        rig.close()
    # a finding with no `argv` field (or a malformed one) has NO move: the sentence is never read (FR-12)
    for label, argv in (("no argv field", False), ("an empty list", []), ("a list with a non-string", ["python", 3])):
        rig = Rig(findings=[probe_finding(argv=argv)], reviews=[])
        try:
            ran = []
            rig.driver.run_argv = lambda argv: ran.append(list(argv)) or (0, "wrote")
            rig.enter()
            check_eq(f"probe row: {label}: nothing is run (the finding goes to the conductor)", (ran, len(rig.conductors)), ([], 1))
        finally:
            rig.close()
    # INFO stays INFO: a probe line in the rehearsal's `info` (the shape before the finding exists) repairs nothing
    rig = Rig(findings=[], reviews=[], script=[{"findings": [], "info": [{"check": "s5_runtime_probe", "profile": "api", "message": "m", "argv": portable_probe()}]}])
    try:
        ran = []
        rig.driver.run_argv = lambda argv: ran.append(list(argv)) or (0, "wrote")
        result = rig.enter()
        check_eq("probe row: a derived probe that is only an INFO line is never registered by the driver", (is_person(result), ran), (True, []))
    finally:
        rig.close()
    # (b) unraised questions: the S4 exit's own command, then the re-pin
    rig = Rig(findings=[finding("unraised_questions", 1, "question left unraised - QA-9_TC_001: Then 2 says `unknown`", where="QA-9_TC_001")], reviews=[])
    try:
        result = rig.enter()
        check("unraised row: the round ran (no Person)", result == "returned", repr(result))
        check_eq("unraised row: the command, then the re-pin and nothing else",
                 rig.log, [("rehearse", "A"), ("critic_rollcall",), ("case_versions", "--all"), ("case_versions", "--verify")])
        check_eq("unraised row: the round's moves", rig.series()["rounds"][0]["moves"], ["critic_rollcall --apply-fixes", "pin_cases"])
        check_in("unraised row: said in words", "gate A repair: the questions the designer could only name are raised by code", rig.out)
        check_eq("unraised row: no conductor, no designer round", (rig.conductors, rig.calls("rework")), ([], []))
    finally:
        rig.close()
    for code, expected_outcome in ((1, "repaired"), (2, "failed")):
        rig = Rig(findings=[finding("unraised_questions", 1, "question left unraised - QA-9_TC_001: Then 2", where="QA-9_TC_001")], reviews=[])
        try:
            real = rig.driver.py
            rig.driver.py = lambda script, *a, check=False, real=real, code=code: (code, '{"skipped": [{"case_id": "x", "reason": "no way"}]}') \
                if script == "critic_rollcall.py" else real(script, *a, check=check)
            rig.enter()
            check_eq(f"unraised row: the command's exit {code} is {expected_outcome} (1 = some could not be raised: the next rehearsal judges "
                     "what is left; anything else is a failed move)", rig.series()["rounds"][0]["outcome"], expected_outcome)
            if code == 2:
                check_in("unraised row: a failed command goes to the conductor with its words", "critic_rollcall.py --apply-fixes", rig.first())
        finally:
            rig.close()


# --- B-416 N3/N4/N6 (D-0031): a test report the code could not read - the code's own move, and the bound that is the CALL --------

DIGEST = "d" * 64


def adapt_argv(profile="web", reader="trx") -> list:
    return ["{python}", "{plugin_root}/scripts/report_adapt.py", "kind", "--profile", profile, "--reader", reader, "--by", "driver", "--task", TASK]


def reporter_finding(profile="web", argv=None, n=1) -> dict:
    return finding("s5_reporter", n, f"the {profile} tests: one existing test ran and left no report S5 can read", profile=profile,
                   argv_digest=DIGEST, kept="qa-factory/state/reporter-unread/web/", fit="trx", declared_kind="",
                   **({} if argv is False else {"argv": adapt_argv(profile) if argv is None else argv}))


def helper_rows(rig) -> list:
    import report_adapt
    return report_adapt.load(rig.root)[0]


def repair_row_adapt_reporter_and_the_bound_is_the_call() -> None:
    import hooklib
    import story_run
    import report_adapt
    check("N4: the table has the row, for gate A, with its two members",
          [(g, c, p, m) for g, c, p, m in story_run.GATE_REPAIRS if c == "s5_reporter"] == [("A", "s5_reporter", "adapt_precondition", "adapt_move")])
    check_eq("N4: the counts name it in words, not an id", story_run.CHECK_WORDS["s5_reporter"], "report kind to record")
    # (a) the typed command: resolved, then run by code - no conductor (N6)
    rig = Rig(findings=[reporter_finding()], reviews=[])
    try:
        ran = []
        rig.driver.run_argv = lambda argv: ran.append(list(argv)) or (0, "RA-1: the report of `web` is read as trx")
        result = rig.enter()
        check("N6: the round ran (no Person)", result == "returned", repr(result))
        check_eq("N6: ONE command, with `{python}` and `{plugin_root}` resolved (the probe_move invariant)",
                 (len(ran), ran[0][:3] if ran else []), (1, [sys.executable, str(hooklib.PLUGIN_ROOT) + "/scripts/report_adapt.py", "kind"]))
        check_not_in("N6: no `{token}` reaches the command line", "{", " ".join(ran[0]) if ran else "{")
        check_eq("N6: the rest is the finding's own: profile, the reader that fits, `--by driver`, this story",
                 ran[0][3:] if ran else [], ["--profile", "web", "--reader", "trx", "--by", "driver", "--task", TASK])
        check_eq("N6: the round is recorded with the move and as repaired", (rig.series()["rounds"][0]["moves"], rig.series()["rounds"][0]["outcome"]),
                 (["report_adapt kind web"], "repaired"))
        check_eq("N6: no conductor was called and the driver wrote no row of its own (`kind` writes its own, here a stub)", (rig.conductors, helper_rows(rig)), ([], []))
    finally:
        rig.close()
    # an UNKNOWN token is refused unrun; a failing `kind` goes to the conductor with its words - and that call is the bound
    for label, argv, runner, expect in (
            ("an unknown token", ["{python}", "{foo}/report_adapt.py", "kind"], lambda a: (0, ""), "was not run"),
            ("a refusal of `kind` itself (exit 2)", None, lambda a: (2, "report_adapt: the profile `web` already records its report kind"), "already records its report kind")):
        rig = Rig(findings=[reporter_finding(argv=argv)], reviews=[])
        try:
            ran = []
            rig.driver.run_argv = lambda a, runner=runner: ran.append(list(a)) or runner(a)
            rig.enter()
            check_eq(f"G17: {label}: " + ("nothing is run" if label == "an unknown token" else "it ran once"), len(ran), 0 if label == "an unknown token" else 1)
            check_in(f"G17: {label}: the conductor is handed the words", expect, rig.first())
            check_eq(f"G17: {label}: the round failed and the series stopped", (rig.series()["rounds"][0]["outcome"], rig.series()["rounds"][0]["stop"]), ("failed", "failed"))
            rows = helper_rows(rig)
            check_eq(f"G5/G10: {label}: the conductor wrote nothing: the DRIVER's row ends the bound, once",
                     [(r["kind"], r["by"], r["profile_id"], r["argv_digest"], r["story"], r["understood"]) for r in rows],
                     [("not_adapted", "driver", "web", DIGEST, TASK, report_adapt.NOT_CALLED_TEXT)])
        finally:
            rig.close()
    # a finding with no typed `argv` (several readers fit, or a kind is recorded): no code move; the conductor is called ONCE
    for label, argv in (("no argv field", False), ("an empty list", []), ("a list with a non-string", ["python", 3])):
        rig = Rig(findings=[reporter_finding(argv=argv)], reviews=[])
        try:
            ran = []
            rig.driver.run_argv = lambda a: ran.append(list(a)) or (0, "")
            rig.enter()
            check_eq(f"N4: {label}: nothing is run, the conductor is called once", (ran, len(rig.conductors)), ([], 1))
            check_eq(f"N4: {label}: and the driver's row follows the call", [(r["kind"], r["by"]) for r in helper_rows(rig)], [("not_adapted", "driver")])
        finally:
            rig.close()
    # the bound holds over every way the call can end
    rig = Rig(findings=[reporter_finding(argv=False)], reviews=[])
    try:
        rig.enter()
        check_eq("G5: first await_gate: ONE conductor call and the driver's row", (len(rig.conductors), len(helper_rows(rig))), (1, 1))
        check_in("N4: the conductor's list names the finding", "one existing test ran and left no report", rig.first())
        rig.enter()
        check_eq("G5: the second await_gate (a stopped series, the row now counts): no second call, no second row", (len(rig.conductors), len(helper_rows(rig))), (1, 1))
        rig.relaunch()
        rig.enter()
        check_eq("G5: and after a relaunch the same - the bound lives in the record, not in memory", (len(rig.conductors), len(helper_rows(rig))), (1, 1))
    finally:
        rig.close()
    rig = Rig(findings=[reporter_finding(argv=False)], reviews=[])
    try:
        def writes(text, *, words="", files=None, words_file=None):
            rig.conductors.append(text)
            report_adapt.append(rig.root, {"kind": "not_adapted", "by": "conductor", "profile_id": "web", "argv_digest": DIGEST, "story": TASK,
                                           "understood": "a binary report; cure: run with --logger junit"})
            return {"action": "continue", "did": "wrote understood"}
        rig.driver.conductor = writes
        rig.enter()
        check_eq("N4: the conductor recorded its own words: the driver adds NOTHING (one row, the conductor's)",
                 [(r["by"], r["understood"][:8]) for r in helper_rows(rig)], [("conductor", "a binary")])
    finally:
        rig.close()
    rig = Rig(findings=[reporter_finding(argv=False)], reviews=[])
    try:
        rig.verdict = {"action": "stop", "did": "cannot read it", "options": SEAM_TWO, "why_person": "access", "checked": "the refusal",
                       "question": "What is this format? Say `retry` once it is readable, or `stop`."}
        result = rig.enter()
        check("G10: the conductor's call ended in the person's question (the call cap / a stop): the exception is not swallowed",
              is_person(result, "conductor"), repr(result))
        check_eq("G10: and the `finally` still appended the driver's row (the bound is the CALL)", [(r["by"], r["kind"]) for r in helper_rows(rig)], [("driver", "not_adapted")])
    finally:
        rig.close()
    rig = Rig(findings=[reporter_finding(argv=False)], reviews=[])
    try:
        def crashes(text, *, words="", files=None, words_file=None):
            rig.conductors.append(text)
            raise RuntimeError("the call died")
        rig.driver.conductor = crashes
        result = rig.enter()
        check("G10: a crash inside the call: the exception propagates", isinstance(result, RuntimeError), repr(result))
        check_eq("G10: and the driver's row is there all the same", [r["by"] for r in helper_rows(rig)], ["driver"])
    finally:
        rig.close()
    # M5: an unreadable record reads as `a row exists`: the driver writes nothing over it
    rig = Rig(findings=[reporter_finding(argv=False)], reviews=[])
    try:
        report_adapt.record_path(rig.root).parent.mkdir(parents=True, exist_ok=True)
        report_adapt.record_path(rig.root).write_text("{broken", encoding="utf-8")
        rig.enter()
        check_eq("M5: an unreadable record is left as it is, no row is forced over it", report_adapt.record_path(rig.root).read_text(encoding="utf-8"), "{broken")
    finally:
        rig.close()
    # N4: a stopped series hands an `s5_reporter` over ONCE, alone
    rig = Rig(findings=[finding("whatever", 1, "a thing no code move repairs")], reviews=[])
    try:
        rig.enter()
        check_eq("N4 (control): an unrelated finding with no move stops the series and goes to the conductor once", (len(rig.conductors), bool(rig.series().get("rounds"))), (1, True))
        rig.findings[:] = [finding("whatever", 1, "a thing no code move repairs"), reporter_finding(argv=False)]
        rig.enter()
        check_eq("N4: the stopped series hands the unread report over - once - and ONLY it", (len(rig.conductors), "a thing no code move repairs" in rig.conductors[-1],
                 "one existing test ran and left no report" in rig.conductors[-1]), (2, False, True))
        check_in("N4: it says why it was handed over", "the series has stopped", rig.out)
        check_eq("N4: the driver's row ended the bound", [r["by"] for r in helper_rows(rig)], ["driver"])
        rig.enter()
        check_eq("N4: the next await_gate lists what is left and calls nobody (stopped series, row recorded)", (len(rig.conductors), len(helper_rows(rig))), (2, 1))
    finally:
        rig.close()
    # a failed append is printed and remembered: not tried again, the finding stays at the top of the gate
    rig = Rig(findings=[finding("whatever", 1, "a thing no code move repairs")], reviews=[])
    try:
        rig.enter()
        rig.findings[:] = [finding("whatever", 1, "a thing no code move repairs"), reporter_finding(argv=False)]
        real = report_adapt.append
        report_adapt.append = lambda root, row: (None, "the record cannot be written")
        try:
            rig.enter()
            check_in("N4: a failed append is said", "could not be recorded", rig.out)
            rig.enter()
        finally:
            report_adapt.append = real
        check_eq("N4: a failed append is not retried by a loop: ONE handover only", len(rig.conductors), 2)
        check_eq("N4: and remembered in the state", json.loads((rig.task_root / "state" / "driver-state.json").read_text(encoding="utf-8")).get("adapt_handed"), [f"web|{DIGEST}"])
    finally:
        rig.close()


def gate_a_answer_is_recorded_against_the_card_as_shown() -> None:
    """t-291 / t-279 F5 (K-SHOWN): `record_by_code` hands the applier the fingerprints the SHOWN packet's cards carry
    (`state/driver-question.md`), so an answer to a card whose row was edited since reads `changed_since_answer`;
    with no packet on disk the answer is recorded against the row as it stands, as it was before."""
    import gate_brief
    import question_register as QR
    plan_row = {"id": "TS-1", "requirement_ids": ["R-1"], "level": "api", "disposition": "automate",
                "impact": "moderate", "likelihood": "medium", "design_review_required": False,
                "confidence": "medium", "risk_rationale": "a permission seam",
                "risk_source_refs": ["strategy/test-strategy.md@2026-09-14"],
                "risk_policy_revision": "factory-starter-v1", "coverage_refs": [], "unknowns": [],
                "verification_depth": "normal", "defect_hypothesis": "seam @ validate vs update",
                "required_scenarios": ["a denied caller"], "test_level_rationale": "HTTP contract, no UI involved",
                "question_refs": ["Q1"],
                "if_answered": {"Q1": {"a": {"disposition": "automate"}, "b": {}, "not_needed": {}}}}
    question = {"id": "Q1", "question": "Which behaviour for Q1?", "severity": "major",
                "readings": [{"reading": f"r{n}", "from": "description", "if_chosen": "x"} for n in range(2)]}

    def story(name: str, asked: bool):
        """A seeded story with Q1 open, a driver whose controller call is replaced, the packet as the driver wrote
        it (or none), and Q1 reworded AFTER the card was shown. Returns (root, task_root, driver, the row's hash on the card)."""
        root, task_root, env = seed(name)
        (task_root / "work" / "test-plan.json").write_text(json.dumps({"rows": [plan_row]}), encoding="utf-8")
        readiness = task_root / "work" / "requirements-readiness.json"
        readiness.write_text(json.dumps({"open_questions": [question]}), encoding="utf-8")
        shown_hash = {q["id"]: q for q in QR.load(task_root)["questions"]}["Q1"]["row_hash"]
        packet = gate_brief.render(gate_brief.collect(name, task_root))
        d = driver_for(root, env, name)
        # DC1-19 (ae02ac71): the answers are recorded and applied by the controller's `gate-decision` (the ONE executor, AR-15), not by
        # the driver. The driver's half is what it HANDS that call: the stub below keeps the call, and the keys read it. The executor's
        # half is pinned where the executor is: the stored hash of the row as shown (`record_row_hash`) in test_question_register.py
        # (E2, E3), `changed_since_answer` on the applier in test_question_branches.py, and only the REFUSAL of a missing `--shown-file`
        # through `gate-decision` in test_gate_words_road.py (d11/E21). The pin that `gate-decision` applies a hash it was handed by
        # `--shown-file` is owed there (worker t-435).
        d.calls = []

        def py(script, *args, check=False, expect=""):      # C1-7c Q-3: the real `py`'s signature; exit 0, `check` never raises
            d.calls.append((script, list(args)))
            return 0, "{}"
        d.py = py
        d.report_attribution = lambda gate, words: {}
        if asked:
            d.state["asked"] = {"kind": "gate_A", "stage": "S4", "dispatch": ""}
            (task_root / "state" / "driver-question.md").write_text(packet, encoding="utf-8")
        reworded = dict(question, question="Which behaviour for Q1 - reworded by the requirements tester?")
        readiness.write_text(json.dumps({"open_questions": [reworded]}), encoding="utf-8")
        return root, task_root, d, shown_hash, packet

    def answered(task_root) -> dict:
        return {q["id"]: q for q in QR.load(task_root)["questions"]}["Q1"]

    root, task_root, d, shown_hash, packet = story("QA-91", asked=True)
    try:
        check_in("K-SHOWN: the packet the driver wrote carries the card's fingerprint", f"<!-- card Q1 {shown_hash} -->", packet)
        with contextlib.redirect_stdout(io.StringIO()):
            ok = d.record_by_code("gate_A", "S4", "approve\nQ1: a")
        q = answered(task_root)
        check_eq("K-SHOWN: the decision is recorded by ONE gate-decision call of the executor", (ok, len(d.calls), d.calls[0][0], "gate-decision" in d.calls[0][1]),
                 (True, 1, "controller.py", True))
        args = d.calls[0][1]
        handed = json.loads(Path(args[args.index("--shown-file") + 1]).read_text(encoding="utf-8")) if "--shown-file" in args else None
        check_eq("K-SHOWN: the call hands over the hash the card carried (not the apply-time one: the row was reworded since)",
                 (handed, q["row_hash"] != shown_hash), ({"Q1": shown_hash}, True))
        check_eq("K-SHOWN: and the person's lines by file", Path(args[args.index("--answers-file") + 1]).read_text(encoding="utf-8").strip(), "approve\nQ1: a")
        # a question of another kind open: its text is not this gate's packet
        check_eq("K-SHOWN: a packet is read only while this gate's question is the open one",
                 (d.shown_packet("gate_A") == packet, d.shown_packet("gate_B")), (True, ""))
    finally:
        os.chdir(harness.PLUGIN_ROOT)
        harness.cleanup(root)
    # control, the world before: no packet on disk (a kept-answer retry, an older state) - the row as it stands
    root, task_root, d, shown_hash, packet = story("QA-92", asked=False)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            ok = d.record_by_code("gate_A", "S4", "approve\nQ1: a")
        q = answered(task_root)
        check_eq("K-SHOWN control: with no packet no shown hash is handed (the executor then takes the row as it stands; nothing crashed)",
                 (ok, len(d.calls), "--shown-file" in d.calls[0][1], q["row_hash"] != shown_hash), (True, 1, False, True))
    finally:
        os.chdir(harness.PLUGIN_ROOT)
        harness.cleanup(root)


ANSWERS = Path(__file__).resolve().parent / "fixtures" / "bench-13797-answers"   # the two gate A answers of the comparison run, copied into the package (AR-4)


def c14b_rig(gate_kind="gate_B"):
    rig = Rig()
    d = rig.driver
    d.report_attribution = lambda gate, words: {}
    return rig, d, (lambda: rig.log.count(("controller",))), (lambda: rig.log.count(("log_append",)))


def c14b_approval_is_its_word() -> None:
    """A1 (C1-4b, I1/I2, FR-12): `record_by_code` records a gate only on the approval word as the first non-empty line; every other
    input is not an approval. The error direction is not approving (the allowed error), never approving words that are not the word."""
    rig, d, decisions, defects = c14b_rig()
    try:
        not_approvals = ["approve, but fix the export test", "I approve", "approved", "Approved: the plan stands", "do not approve",
                         "the export test is wrong\napprove", "```\napprove\n```", "approve it", "approve!!", "","\n \n", "yes",
                         "x" * 5000, "approve\u200b", "app\u200brove", "\u0430pprove"]       # zero-width characters inside the word, and a Cyrillic a (ASCII source: FR-30)
        for text in not_approvals:
            before = decisions()
            with contextlib.redirect_stdout(io.StringIO()):
                ok = d.record_by_code("gate_B", "S8", text)
            check_eq(f"A1: {text[:30]!r} is not the approval word: nothing recorded", (ok, decisions() - before), (False, 0))
        approvals = ["approve", "Approve.", "`approve`", "﻿approve\r\n", "\n\napprove", "approve\nbugs 1 and 2", "﻿\r\napprove\r\nthe rest, CRLF\r\n",
                     "  APPROVE  ", "'approve'", "approve!"]       # ONE closing `.` or `!` is the normalizer's (s0_normalize), nothing more
        for text in approvals:
            before = decisions()
            with contextlib.redirect_stdout(io.StringIO()):
                ok = d.record_by_code("gate_B", "S8", text)
            check_eq(f"A1: {text[:30]!r} approves, recorded once", (ok, decisions() - before), (True, 1))
        check_eq("A1: an unrecognised kind is never an approval", d.gate_approval("conductor", "approve"), False)
        before = decisions()
        with contextlib.redirect_stdout(io.StringIO()):
            ok = d.record_by_code("gate_B", "S8", "I am sure it is fine", approved_by="option")
        check_eq("A1: the person's CHOICE of `approve` from the options is the approval, whatever the original words (approved_by)",
                 (ok, decisions() - before), (True, 1))
        with contextlib.redirect_stdout(io.StringIO()):
            ok = d.record_by_code("gate_B", "S8", "hm", approved_by="because I said so")
        check_eq("A1: and a made-up approved_by is not one", ok, False)
    finally:
        rig.close()


def c14b_gate_a_prose_under_the_word_is_recorded() -> None:
    """A2 (Lead answer 3, D-0042): the first-line word ALONE approves at gate A; the lines below are read by their own readers and
    ignored when they match neither. The REAL answers of the comparison run (`approve` on top of the old prose) are recorded, no
    seam call; an unreadable stand-gap FORM line rides the approval (GW1-33); a line whose record was REFUSED still holds it (G22)."""
    rig, d, decisions, defects = c14b_rig()
    try:
        d.state["asked"] = {"kind": "gate_A", "stage": "S4", "dispatch": ""}
        d.rehearse = lambda gate: {"findings": [], "stand_gaps": []}
        for name in ("driver-gate-a.md", "driver2-gate-a.md"):
            prose = (ANSWERS / name).read_text(encoding="utf-8")
            body = prose if prose.lstrip().lower().startswith("approve\n") else "approve\n" + prose
            before = decisions()
            path = rig.root / name
            path.write_bytes(body.encode("utf-8"))
            rig.conductors.clear()
            d.state["asked"] = {"kind": "gate_A", "stage": "S4", "dispatch": ""}
            with contextlib.redirect_stdout(io.StringIO()):
                d.take_answer(path)
            check_eq(f"A2 {name}: `approve` + the old prose is recorded by code once, and the conductor is not called",
                     (decisions() - before, len(rig.conductors)), (1, 0))
        d.state["asked"] = {"kind": "gate_A", "stage": "S4", "dispatch": ""}
        d.state["asked"] = {"kind": "gate_A", "stage": "S4", "dispatch": ""}
        d.take_stand_gap_answers = lambda kind, words, qtext, stage, dispatch, **k: {"unread": ["TC-9: maybe later"], "recorded": [], "note": "n"}
        path = rig.root / "unreadable.md"
        path.write_bytes(b"approve\nTC-9: maybe later")
        before = decisions()
        with contextlib.redirect_stdout(io.StringIO()):
            d.take_answer(path)
        check_eq("A2: an unreadable stand-gap FORM line under the word rides the approval: recorded by code, the conductor is not called; "
                 "the line is told, whole in the answer row", (decisions() - before, len(rig.conductors)), (1, 0))
        # t-550 F3: the old G22 meaning lives on for a line whose record was REFUSED (`hold`): the approval stays kept for the conductor
        d.state["asked"] = {"kind": "gate_A", "stage": "S4", "dispatch": ""}
        d.take_stand_gap_answers = lambda kind, words, qtext, stage, dispatch, **k: {
            "unread": ["TC-9: accept"], "recorded": [], "note": "n", "hold": ["TC-9: accept"]}
        path = rig.root / "held.md"
        path.write_bytes(b"approve\nTC-9: accept")
        before = decisions()
        with contextlib.redirect_stdout(io.StringIO()):
            d.take_answer(path)
        check_eq("A2: a line whose record was REFUSED (held) still keeps the approval: not recorded by code, the conductor takes it",
                 (decisions() - before, len(rig.conductors)), (0, 1))
    finally:
        rig.close()


def c14b_kept_and_old_answers() -> None:
    """A3/H4/H8: only an approval is kept for the gate; an option-approved decision the controller refused keeps its mark; an answer an
    OLDER driver kept (prose) is dropped and handed to the seam once, never told as 'refused'."""
    rig, d, decisions, defects = c14b_rig()
    try:
        d.state["asked"] = {"kind": "gate_B", "stage": "S8", "dispatch": ""}
        d.rehearse = lambda gate: {"findings": []}
        d.unread = lambda *a, **k: rig.log.append(("unread", k.get("words")))
        path = rig.root / "prose.md"
        path.write_bytes(b"the automation needs changes - the export test checks only the status code")
        with contextlib.redirect_stdout(io.StringIO()):
            d.take_answer(path)
        check_eq("A3: words that are not the approval word are never kept as one", d.state.get("gate_answer_kept"), None)
        d.state["asked"] = {"kind": "gate_B", "stage": "S8", "dispatch": ""}
        d.py = lambda script, *a, check=False: (1, "controller: refused for a reason") if script == "controller.py" else (0, "")
        path.write_bytes(b"approve\nbug 1")
        with contextlib.redirect_stdout(io.StringIO()):
            d.take_answer(path)
        kept = d.state.get("gate_answer_kept") or {}
        check_eq("A3: an approval the controller refused is kept, marked as an approval by the word", (kept.get("words"), kept.get("approved_by")),
                 ("approve\nbug 1", "token"))
        check_in("A3: and the gate asked again names the word", "`approve`", d.kept_answer_text(kept))
        # H4: the mark travels on the kept road
        rev = d.controller_state().get("source_revision")
        d.state["gate_answer_kept"] = {"gate": "B", "words": "change the export test", "at": "t", "approved_by": "option", "source_revision": rev}
        seen = []
        d.record_by_code = lambda kind, stage, w, again=False, approved_by="": seen.append((kind, w, again, approved_by)) or True
        d.gate_repair("B")
        check_eq("H4: the kept road re-records an option-approved decision as approved, never 'refused forever'",
                 seen, [("gate_B", "change the export test", True, "option")])
        # H8: an answer kept by the older driver
        seen.clear()
        d.state["gate_answer_kept"] = {"gate": "B", "words": "approved as it stands, fix the test later", "at": "t", "source_revision": rev}
        out = d.gate_repair("B")
        check_eq("H8: prose kept by an older driver is dropped, goes to the seam ONCE, and is not re-recorded",
                 (d.state.get("gate_answer_kept"), [e for e in rig.log if e[0] == "unread"][-1:], seen, out.get("ran")),
                 (None, [("unread", "approved as it stands, fix the test later")], [], True))
    finally:
        rig.close()


def c14b_no_word_list_and_the_note() -> None:
    """A4: the word list unreadable -> nothing recorded by code, the packet names no token, ONE defect. A5: the rework note at 200 and 201."""
    import gate_brief
    rig, d, decisions, defects = c14b_rig()
    real = gate_brief.approval_words
    gate_brief.approval_words = lambda gate: ()
    try:
        d.gate_text = type(d).gate_text.__get__(d)
        for words in ("approve", "approve", "approve"):
            with contextlib.redirect_stdout(io.StringIO()):
                ok = d.record_by_code("gate_A", "S4", words)
            check_eq("A4: nothing is recorded by code over an unreadable word list", (ok, decisions()), (False, 0))
        check_eq("A4: ONE defect_found for the unreadable list, not one per answer", defects(), 1)
        check_not_in("A4: the packet names no token", "`approve`", d.kept_answer_close("A"))
    finally:
        gate_brief.approval_words = real
        rig.close()
    rig, d, decisions, defects = c14b_rig()
    try:
        made = {}
        d.controller_state = lambda: {"dispatches": dict(made), "source_revision": "src-1", "decisions": {}}
        check_eq("A5: a gate never shown before says nothing (and seeds the list)", d.gate_rework_note("B"), "")
        for size in (200, 201):
            made[f"S5-qa-automator-{size}"] = {"id": f"S5-qa-automator-{size}", "stage": "S5", "status": "accepted", "rework_of": "x",
                                               "reason": "w" * size, "person_words": True,
                                               "rerun_after": {"stages": ["S6", "S7", "S8"]}}
            note = d.gate_rework_note("B")
            quoted = re.search(r'"(w+\.*)"', note)
            check_eq(f"A5: {size} characters: {'whole' if size == 200 else 'cut with ...'}",
                     quoted.group(1) if quoted else None, "w" * 200 + ("" if size == 200 else "..."))
            check_in(f"A5 {size}: the note names the stages that ran again", "ran again", note)
        check_eq("A5 (FR-7): the same ids are never noted twice", d.gate_rework_note("B"), "")
    finally:
        rig.close()


def c14b_the_note_derives_from_every_accepted_rework() -> None:
    """H7 + edge 4 + FR-7 (I5): the note at the top of a gate asked AGAIN comes from EVERY accepted rework (`rework_of`) registered since the
    gate was last shown - the unstamped one too, so an S8 scribe rework with nothing after it still changes the text and the unchanged packet
    is never shown without a note. A SECOND rework after the re-run is a new note with the new words only (edge 4: each re-show says what
    changed); a rework that is not accepted, or is the B-364 road's (`ticket_changed`), says nothing here; each gate keeps its own list."""
    rig, d, decisions, defects = c14b_rig()
    try:
        made = {}
        d.controller_state = lambda: {"dispatches": dict(made), "source_revision": "src-1", "decisions": {}}

        def rework(name, stage, reason, status="accepted", **extra):
            made[name] = dict({"id": name, "stage": stage, "status": status, "rework_of": "x", "reason": reason}, **extra)
        check_eq("FR-7 setup: the first show of each gate seeds its list and says nothing", (d.gate_rework_note("B"), d.gate_rework_note("A")), ("", ""))
        rework("S8-scribe-2", "S8", "fix the report wording", person_words=True)
        note = d.gate_rework_note("B")
        check_in("FR-7/H7: an UNSTAMPED rework (nothing runs after the scribe) still makes a note: the words", "fix the report wording", note)
        check_in("FR-7/H7: and says the stage was done again", "was done again", note)
        check_not_in("FR-7/H7: and, with nothing stamped, claims no stage ran after it", "ran again", note)
        check_eq("FR-7: the same ids are not noted twice (the packet changed only once)", d.gate_rework_note("B"), "")
        rework("S5-qa-automator-9", "S5", "the second round: check the body too", person_words=True,
               rerun_after={"stages": ["S6", "S7", "S8"]})
        rework("S5-qa-automator-10", "S5", "never accepted", status="running", rerun_after={"stages": ["S6"]})
        rework("S4-designer-3", "S4", "the ticket changed", repair_cause="ticket_changed")
        note = d.gate_rework_note("B")
        check_in("edge 4: a SECOND rework after the re-run: a new note with the new words", "the second round: check the body too", note)
        check_not_in("edge 4: and not the first round's words again", "fix the report wording", note)
        check_in("edge 4: and the stages that ran again after it", "then", note)
        check_not_in("edge 4: a rework that was never accepted is no change to tell", "never accepted", note)
        check_not_in("edge 4: nor is the ticket road's (it has its own note, B-364)", "the ticket changed", note)
        check_eq("edge 4: each note is told once", d.gate_rework_note("B"), "")
        check_in("each gate keeps its own list: gate A was last shown before ALL of them, so it tells every accepted one",
                 "fix the report wording", d.gate_rework_note("A"))
    finally:
        rig.close()


def c14b_f1_a_driver_issued_rework_is_never_told_as_the_persons_words() -> None:
    """F1 (critic t-693, FR-41/FR-10, I5): the driver's and the conductor's own reworks (an S4 critic round, an S5 / S7 repair, the rehearsal)
    also carry `rework_of`, with a reason typed by code. The note quotes `on your words` ONLY for a record the controller marked
    `person_words` (`--words-file`); every other accepted rework is told neutrally, without its reason - and a record with no mark at all
    (an older controller wrote it) is treated as the driver's, never quoted as the person's (FR-59)."""
    rig, d, decisions, defects = c14b_rig()
    try:
        made = {}
        d.controller_state = lambda: {"dispatches": dict(made), "source_revision": "src-1", "decisions": {}}

        def rework(name, stage, reason, **extra):
            made[name] = dict({"id": name, "stage": stage, "status": "accepted", "rework_of": "x", "reason": reason}, **extra)
        check_eq("F1 setup: the first show seeds the list", d.gate_rework_note("B"), "")
        rework("S5-qa-automator-4", "S5", "critic finding CF-7: the export test asserts a hard-coded status", repair_cause="reviewer_error")
        rework("S7-qa-triager-2", "S7", "repair: the table is stale", person_words=False)
        rework("S4-qa-case-designer-3", "S4", "mechanical fix of the card ids")
        note = d.gate_rework_note("B")
        for words in ("CF-7", "hard-coded", "the table is stale", "card ids"):
            check_not_in(f"F1: the code-typed reason {words!r} is not quoted", words, note)
        check_not_in("F1: and nothing is told as the person's words", "your words", note)
        check_in("F1: but the change is told - the stage ran again, after the factory's own repair round", "S5", note)
        check_in("F1: with its cause class, not its text", "(reviewer error)", note)
        check_eq("F1 edge: all three stages are named, once each", [note.count(s) for s in ("(S5)", "(S7)", "(S4)")], [1, 1, 1])
        rework("S5-qa-automator-5", "S5", "the export test must check the body", person_words=True, rerun_after={"stages": ["S6"]})
        rework("S7-qa-triager-3", "S7", "a second finding typed by code")
        note = d.gate_rework_note("B")
        check_in("F1: a marked rework in the same batch is still quoted as the person's words", 'on your words "the export test must check the body"', note)
        check_not_in("F1: and the unmarked one beside it is not", "a second finding typed by code", note)
        check_eq("FR-7: all of them were noted once", d.gate_rework_note("B"), "")
    finally:
        rig.close()


def c14b_a_byte_order_mark_and_crlf_and_go_on_through_take_answer() -> None:
    """H11 + the closed `go on` (I1/I2), through `take_answer` and not only through the recorder: an answer FILE that opens with a BOM and
    ends its lines with CRLF is the approval word (recorded once, nothing sent to the seam); `go on` at a gate - on a plain gate question and
    on a seam question whose options do not offer it - is nothing the gate reads: it goes to the seam once (`unread`), nothing is recorded
    and no waiver is run (`go on` passes no gate: at a gate the one pass is `approve`)."""
    rig, d, decisions, defects = c14b_rig()
    try:
        d.rehearse = lambda gate: {"findings": []}
        d.unread = lambda *a, **k: rig.log.append(("unread", k.get("words")))

        def take(body: bytes, **asked):
            d.state["asked"] = dict({"kind": "gate_B", "stage": "S8", "dispatch": ""}, **asked)
            path = rig.root / "answer-file.md"
            path.write_bytes(body)
            with contextlib.redirect_stdout(io.StringIO()):
                d.take_answer(path)
        unreads = lambda: [e for e in rig.log if e[0] == "unread"]
        take((chr(0xFEFF) + "approve\r\nbug 1 and 2\r\n").encode("utf-8"))      # the BOM as a code point: no control byte in the source (FR-29)
        check_eq("H11: a BOM + CRLF file is the approval word: recorded once, the seam not called", (decisions(), unreads()), (1, []))
        take(b"go on")
        check_eq("go on at a gate: the seam once with the words, nothing recorded, no waiver", (decisions(), unreads(), rig.calls("waiver")),
                 (1, [("unread", "go on")], []))
        take(b"go on", offered=["approve", "retry", "stop"], why="unread_answer", block="",
             options=[{"token": "approve", "move": "approve_gate"}, {"token": "retry", "move": "person_does"}, {"token": "stop", "move": "stop_here"}])
        check_eq("go on to a seam question that does not offer it: the seam again, nothing recorded, no waiver",
                 (decisions(), len(unreads()), rig.calls("waiver")), (1, 2, []))
    finally:
        rig.close()


ORIGINAL = "the automation needs changes - the export test checks only the status code\r\nplease check the body too\r\n"
GATE_OPTIONS = [{"token": "rework", "move": "rework_stage"}, {"token": "approve", "move": "approve_gate"},
                {"token": "retry", "move": "person_does"}, {"token": "stop", "move": "stop_here"}]


def c14b_story_waiting_at_gate_b():
    """A project whose story QA-10 stands at gate B on the REAL controller (S0-S8 completed, gate A approved), a driver over it with its
    conductor and the judge replaced; the person's original answer is on file. (root, driver, words file path relative to the task root)."""
    import test_controller_rework_scope as SCOPED
    import test_controller_state as BASE
    root, _unused, env = seed(TASK)
    second = root / "qa-factory" / "artifacts" / "QA-10"
    second.mkdir(parents=True)
    controller = SCOPED.gate_a_task(second)
    for number in range(5, 9):
        BASE.accept_stage(controller, second, f"S{number}")
    driver = driver_for(root, env, "QA-10")
    driver.judged_reply = lambda *a, **k: ""
    driver.calls = []
    driver.conductor = lambda text, *, words="", files=None, words_file=None: driver.calls.append((text, words_file)) or {"action": "continue", "did": "stub"}
    path = driver.words_file(ORIGINAL, "answer")
    return root, driver, path.relative_to(driver.task_root).as_posix()


def c14b_answer(driver, root, token, kind, stage, rel):
    """One token answer to a seam question that carries the gate's options; the Person the seam raised, else None."""
    driver.state["asked"] = {"kind": kind, "stage": stage, "dispatch": "", "offered": [o["token"] for o in GATE_OPTIONS],
                             "options": list(GATE_OPTIONS), "words_file": rel, "why": "unread_answer", "block": ""}
    driver.save_state()
    path = root / "token.md"
    path.write_bytes(token.encode("utf-8"))
    import story_run
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            driver.take_answer(path)
        except story_run.Person as person:
            return person
    return None


def c14b_reworking_conductor(driver):
    """The conductor as the `rework` option runs it: ONE real `controller.py --operation rework --words-file` over the original answer's file;
    what the controller printed is kept in `driver.registered`."""
    def conductor(text, *, words="", files=None, words_file=None):
        driver.calls.append((text, words_file))
        code, out = driver.py("controller.py", "--task-root", str(driver.task_root), "--operation", "rework", "--stage", "S5",
                              "--role", "qa-automator", "--cases", "TC-1", "--words-file", str(driver.task_root / words_file))
        driver.registered = (code, out)
        return {"action": "continue", "did": "reworked S5 with the person's words"}
    return conductor


def c14b_finish_the_loop(driver, rework_id, tag="r2"):
    """What the real controller needs for the loop after a rework of S5 to reach gate B again: the rework accepted (the stage stays open),
    a NEW S5 critic over it with its window, then S6, S7, S8 each run again and accepted. Ids carry `tag`: the first run's are taken."""
    import test_controller_state as BASE
    from controller import Controller
    root = driver.task_root
    controller = Controller(root)

    def receipt(identifier):
        return [BASE.evidence_ref(root, identifier + ".txt", identifier)]

    controller.apply("accept", {"id": rework_id, "status": "accepted", "stage_complete": False, "evidence_refs": receipt(rework_id),
                                "idempotency_key": "accept-" + rework_id})
    critic = f"dS5-{tag}"
    controller.apply("dispatch", {"id": critic, "stage": "S5", "role": "qa-code-critic", "scope": ["TC-1"], "input_hash": "S5", "budget": {},
                                  "known_paths": {}, "idempotency_key": "dispatch-" + critic})
    # a real S5 critic leaves its findings file; with the manifest on disk (the real S5 left it) the window check demands it
    refs = receipt(critic) + [BASE.evidence_ref(root, critic + "-findings.md", "# findings")]
    window = {"schema_version": 2, "input_hash": "S5", "author_dispatch_id": rework_id, "reviewer_dispatch_id": critic,
              "required_quality_checks": [], "quality_receipts": [], "scope_instances": {"TC-1": ["i"]},
              "instances": [dict({"instance_id": "i", "outcome": "passed", "input_hash": "S5",
                                  "review": {"verdict": "approved", "input_hash": "S5"}, "change_disposition": "unchanged",
                                  "change_basis_ref": "manifest:TC-1", "evidence_refs": refs},
                                 **BASE.v2_binding(obligation_hash=BASE.plan_obligation_hash(root)))]}
    controller.apply("accept", {"id": critic, "status": "accepted", "stage_complete": True, "evidence_refs": refs, "window": window,
                                "idempotency_key": "accept-" + critic})
    for stage in ("S6", "S7", "S8"):
        identifier = f"d{stage}-{tag}"
        controller.apply("dispatch", {"id": identifier, "stage": stage, "role": "qa-worker", "scope": ["TC-1"], "input_hash": identifier,
                                      "budget": {}, "known_paths": {}, "idempotency_key": "dispatch-" + identifier})
        controller.apply("accept", {"id": identifier, "status": "accepted", "stage_complete": True, "evidence_refs": receipt(identifier),
                                    "idempotency_key": "accept-" + identifier})


def c14b_gate_b_shown(driver, ask=False):
    """The Person gate B raises over a stubbed packet (the packet's own content is not the subject); `ask` also writes the question file
    the way the loop does, so the FR-7 comparison has its carrier."""
    import story_run
    driver.gate_text = lambda gate: "the packet of gate B"
    try:
        driver.gate("B")
    except story_run.Person as person:
        if ask:
            with contextlib.redirect_stdout(io.StringIO()):
                driver.ask(person)
        return person
    raise AssertionError("gate B raised no Person")


def c14b_a6_the_loop_after_the_rework_reaches_gate_b_with_the_note_once() -> None:
    """A6, the loop half (critic t-693 F2; I5, FR-7): after the conductor's real `rework` at gate B (S5 open again, S6-S8 lowered) the story
    goes on - the S5 critic reviews the rework, S6, S7, S8 run again - and gate B is raised AGAIN, now with ONE note at the top that names the
    person's words, the stage done again and the stages that ran again. The changed packet is NOT met by the FR-7 block ('You have answered
    this exact question before'), the note is told once across re-shows, and the same packet WITHOUT the note is (the control: the block
    exists and would have fired)."""
    root, driver, rel = c14b_story_waiting_at_gate_b()
    try:
        first = c14b_gate_b_shown(driver, ask=True)
        check_not_in("A6 loop: the FIRST show of gate B has no note (it seeds the list)", "is asked again", first.text)
        driver.conductor = c14b_reworking_conductor(driver)
        c14b_answer(driver, root, "rework", "gate_B", "S8", rel)
        code, out = driver.registered
        check_eq("A6 loop: the conductor's rework ran", code, 0)
        request = json.loads(out)["request"]
        check_eq("A6 loop: and the controller marked it as the person's words", request.get("person_words"), True)
        c14b_finish_the_loop(driver, request["id"])
        state = driver.controller_state()
        check_eq("A6 loop: S5-S8 are completed again, no gate B decision was recorded", ([state["stages"][s]["status"] for s in ("S5", "S6", "S7", "S8")],
                 [d for d in state["decisions"].values() if d.get("gate") == "B"]), (["completed"] * 4, []))
        check_eq("A6 loop: the rework is accepted on the record, with the mark", (state["dispatches"][request["id"]]["status"],
                 state["dispatches"][request["id"]].get("person_words")), ("accepted", True))
        second = c14b_gate_b_shown(driver, ask=True)
        check_eq("A6 loop: gate B asked again carries ONE note", second.text.count("Gate B is asked again"), 1)
        check_in("A6 loop: the note quotes the person's words", 'on your words "the automation needs changes - the export test checks only the status code please check the body too"', second.text)
        check_in("A6 loop: and names the stage done again, then the stages that ran again", "was done again, then", second.text)
        for stage in ("S6", "S7", "S8"):
            check_in(f"A6 loop: and {stage} among the stages that ran again", f"({stage})", second.text.split("was done again")[1].split("\n")[0])
        asked_text = (driver.state_dir / "driver-question.md").read_text(encoding="utf-8")
        check_not_in("FR-7 (changed packet): the block 'You have answered this exact question before' does not fire", "answered this exact question", asked_text)
        third = c14b_gate_b_shown(driver)
        check_not_in("A6 loop: the note is told once across re-shows (the third show has none)", "is asked again", third.text)
        check_in("A6 loop: the packet itself is still there", "the packet of gate B", third.text)
        # the control: the FR-7 comparison exists - the very question of the first show, asked again unchanged, meets its earlier answer
        import story_run
        driver.state["asked"] = {}
        with contextlib.redirect_stdout(io.StringIO()):
            driver.ask(story_run.Person(first.kind, first.text, first.stage))
        control = (driver.state_dir / "driver-question.md").read_text(encoding="utf-8")
        check_in("A6 loop control: the unchanged packet of the first show IS met by the FR-7 block", "answered this exact question", control)
    finally:
        os.chdir(harness.PLUGIN_ROOT)
        harness.cleanup(root)


def c14b_h2_a_token_at_a_gate_is_executed_on_a_done_stage_and_nowhere_else() -> None:
    """H2 (both sides, I4): `done and kind not in ('gate_A', 'gate_B')` short-circuits as today - a non-gate kind whose stage is done is never
    reopened by a token (C1-1 edge 8: the words are logged, the conductor is not called, the controller is untouched) - and at a gate, where
    the stage in front of it (S8) is ALWAYS done, `approve` is EXECUTED (the recorder of the option is called once with the original
    words' file) and `rework` is not swallowed. A6: the conductor's `rework` is carried out on the real controller: the rework request exists
    with the person's words from `--words-file` byte for byte, the stamp names what runs again, and nothing was recorded as approved."""
    root, driver, rel = c14b_story_waiting_at_gate_b()
    try:
        before = driver.controller_state()
        check_eq("H2 setup: S8 is DONE in the mirror the short-circuit reads", driver.pipeline()["stages"]["S8"]["status"], "done")
        c14b_answer(driver, root, "rework", "conductor", "S8", rel)
        after = driver.controller_state()
        check_eq("H2 non-gate side: a `rework` token to a done stage of a question that is no gate: the conductor is not called",
                 len(driver.calls), 0)
        check_eq("H2 non-gate side: and the controller is untouched (nothing reopened, no rework registered)",
                 (after["revision"], sorted(after["dispatches"]), after["stages"]["S5"]["status"]),
                 (before["revision"], sorted(before["dispatches"]), "completed"))
        seen = []
        driver.approve_by_option = lambda kind, stage, asked: seen.append((kind, stage, asked.get("words_file")))
        c14b_answer(driver, root, "approve", "gate_B", "S8", rel)
        check_eq("H2 gate side: `approve` at gate B on a done S8 is EXECUTED once, with the original answer's words file, no conductor",
                 (seen, len(driver.calls)), ([("gate_B", "S8", rel)], 0))
        seen.clear()
        c14b_answer(driver, root, "approve", "conductor", "S8", rel)
        check_eq("H2 non-gate side: the same `approve` token to a done stage of another kind is not executed", (seen, len(driver.calls)), ([], 0))
        # --- A6: the rework is carried out ---------------------------------------------------------------
        driver.conductor = c14b_reworking_conductor(driver)
        c14b_answer(driver, root, "rework", "gate_B", "S8", rel)
        check_eq("A6: the conductor was asked once, with the file of the ORIGINAL answer", [file for _text, file in driver.calls], [rel])
        prompt = driver.calls[0][0]
        check_in("A6: its prompt names the chosen move", "`rework_stage`", prompt)
        check_in("A6: and the person's choice, with what the option says (C2-6 §4.3)", "The person chose `rework` (move `rework_stage`)", prompt)
        check_in("A6: and that the original words are the instruction, not the token (C2-6 §4.3)", "the token answer itself is not the instruction", prompt)
        code, out = driver.registered
        check_eq("A6: the controller's rework ran", code, 0)
        request = json.loads(out)["request"]
        check_eq("A6: the request carries the person's words from the file, CRLF and both lines whole", request["reason"].encode("utf-8"), ORIGINAL.encode("utf-8"))
        check_eq("A6: and the stamp: S6-S8 run again, the S5 critic is reviewed again", (request["rerun_after"]["stages"], request["rerun_after"]["reviews"]),
                 (["S6", "S7", "S8"], ["dS5"]))
        state = driver.controller_state()
        check_eq("A6: the rework is registered and RUNNING, S5 is open again, S6-S8 wait", (state["dispatches"][request["id"]]["status"],
                 state["stages"]["S5"]["status"], [state["stages"][s]["status"] for s in ("S6", "S7", "S8")]),
                 ("running", "running", ["pending", "pending", "pending"]))
        check_eq("A6: nothing was recorded as approved for gate B", [d for d in state["decisions"].values() if d.get("gate") == "B"], [])
        check_eq("A6: the question is answered (the loop goes back to `where`)", driver.state.get("asked"), {})
    finally:
        os.chdir(harness.PLUGIN_ROOT)
        harness.cleanup(root)


def c26_rig():
    """cmp3 19:39 on the REAL controller: gate B, the person's prose on file, a driver whose conductor is counted and whose role
    sessions are recorded (the controller's `rework` is the real one). (root, driver, words file rel, controller argv log, runs)."""
    root, driver, rel = c14b_story_waiting_at_gate_b()
    argv_log, runs, inner = [], [], driver.py
    driver.py = lambda script, *a, **k: (argv_log.append((script, a)), inner(script, *a, **k))[1]
    driver.run_role = lambda *a, **k: runs.append((a, k)) or ("", "")
    return root, driver, rel, argv_log, runs


def c26_rework_calls(argv_log) -> list:
    return [a for script, a in argv_log if script == "controller.py" and "rework" in a]


def c26_cmp3_1939_the_token_runs_the_rework_by_code() -> None:
    """§7 C2-6: the conductor offered `rework` WITH args, the person answered `rework`: the record is written, the conductor is NOT
    called again, the next step runs `controller.py --operation rework --words-file` over the ORIGINAL file byte for byte; the record
    goes only after the controller registered it (a second step registers nothing); purpose is the default, the stage is not closed."""
    root, driver, rel, argv_log, runs = c26_rig()
    args = {"stage": "S5", "role": "qa-automator", "cases": ["TC-1"], "cause": "test_defect"}
    options = [dict(GATE_OPTIONS[0], args=args, says="the automator changes the export test")] + GATE_OPTIONS[1:]
    driver.state["asked"] = {"kind": "gate_B", "stage": "S8", "dispatch": "", "offered": [o["token"] for o in options],
                             "options": options, "words_file": rel, "why": "unread_answer", "block": ""}
    driver.save_state()
    token = root / "token.md"
    token.write_bytes(b"rework")
    with contextlib.redirect_stdout(io.StringIO()):
        driver.take_answer(token)
    record = driver.state.get("seam_rework") or {}
    check_eq("C26: the record carries the option's args, the ORIGINAL file and `before`",
             ({k: record.get(k) for k in ("stage", "role", "cases", "cause", "words_file")}, "before" in record),
             ({**args, "words_file": rel}, True))
    check_eq("C26: the conductor was not called for the token", driver.calls, [])
    check_eq("C26: nothing reached the controller at answer time", c26_rework_calls(argv_log), [])
    with contextlib.redirect_stdout(io.StringIO()):
        moved = driver.seam_rework_step()
    calls = c26_rework_calls(argv_log)
    check_eq("C26: the step ran and the controller's rework got the words by FILE, no --reason, the default purpose",
             (moved, len(calls), "--words-file" in calls[0] and "--reason" not in calls[0], "repair_verify" in calls[0]), (True, 1, True, True))
    sent = Path(calls[0][calls[0].index("--words-file") + 1]).read_bytes()
    check_eq("C26: ...and that file is the original answer, byte for byte", sent, (driver.task_root / rel).read_bytes())
    check_eq("C26: the role ran on the stage's open road (complete=False)", (len(runs), runs[0][1].get("complete")), (1, False))
    check("C26: the record is gone after the registration", "seam_rework" not in driver.state)
    check_eq("C26: a second step registers nothing", (driver.seam_rework_step(), len(c26_rework_calls(argv_log))), (False, 1))
    # N2: the record is alive, the controller already holds its own dispatch (a crash after the registration) -> no second registration
    path = driver.state_dir / "controller.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for held in data["dispatches"].values():          # the role was a recorder: its dispatch is still `running`; the crash happened after it ended
        held["status"] = "accepted" if held.get("status") == "running" else held.get("status")
    path.write_text(json.dumps(data), encoding="utf-8")
    driver.state["seam_rework"] = dict(record, before=[])
    check_eq("C26 N2: own dispatch already registered -> the record is dropped, `rework` not called again",
             (driver.seam_rework_step(), "seam_rework" in driver.state, len(c26_rework_calls(argv_log))), (False, False, 1))
    # a running dispatch: the step leaves the record alone
    data = json.loads(path.read_text(encoding="utf-8"))
    some = next(iter(data["dispatches"]))
    data["dispatches"][some]["status"] = "running"
    path.write_text(json.dumps(data), encoding="utf-8")
    driver.state["seam_rework"] = dict(record)
    check_eq("C26 N2: a running dispatch -> False, the record stays", (driver.seam_rework_step(), "seam_rework" in driver.state), (False, True))


def c26_words_edges_and_the_long_words() -> None:
    """§4.2 p.6 / §4.6 / §6 p.16: no words on file -> held (no record); a file named but gone -> held (no record); words over 1500
    characters reach the controller as the file whole and the role as its path."""
    import story_run
    root, driver, rel, argv_log, runs = c26_rig()
    args = {"stage": "S5", "role": "qa-automator", "cases": ["TC-1"], "cause": "test_defect"}
    options = [dict(GATE_OPTIONS[0], args=args)] + GATE_OPTIONS[1:]
    for label, words_file in (("no words on file", ""), ("a file that is gone", "state/words/not-there.txt")):
        driver.state["asked"] = {"kind": "gate_B", "stage": "S8", "dispatch": "", "offered": [o["token"] for o in options], "options": options,
                                 "words_file": words_file, "why": "unread_answer", "block": ""}
        driver.save_state()
        token = root / "token.md"
        token.write_bytes(b"rework")
        person = None
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                driver.take_answer(token)
        except story_run.Person as exc:
            person = exc
        check(f"C26 {label}: the question comes back held, no record, no conductor call",
              person is not None and "seam_rework" not in driver.state and driver.calls == [], str(person))
    longer = "x" * 1700 + " change the export test\r\n"
    path = driver.words_file(longer, "long")
    long_rel = path.relative_to(driver.task_root).as_posix()
    with contextlib.redirect_stdout(io.StringIO()):
        driver.rework("S5", "qa-automator", ["TC-1"], longer, cause="test_defect", words_file=long_rel)
    calls = c26_rework_calls(argv_log)
    check_eq("C26 long words: the controller got the whole file (no --reason)", ("--words-file" in calls[-1], "--reason" in calls[-1]), (True, False))
    given = runs[-1][1].get("rework") or {}
    check("C26 long words: the role is told the path and the length, not a cut of the words",
          str(path) in given.get("line", "") and f"{len(longer)} characters" in given.get("line", "") and "reason" in given, str(given)[:300])


C26_ARGS = {"stage": "S5", "role": "qa-automator", "cases": ["TC-1"], "cause": "test_defect"}


def c26_choose(driver, root, rel) -> dict:
    """The person answers `rework` to the gate-B question whose `rework` option carries `C26_ARGS`; the record the seam wrote."""
    options = [dict(GATE_OPTIONS[0], args=C26_ARGS, says="the automator changes the export test")] + GATE_OPTIONS[1:]
    driver.state["asked"] = {"kind": "gate_B", "stage": "S8", "dispatch": "", "offered": [o["token"] for o in options],
                             "options": options, "words_file": rel, "why": "unread_answer", "block": ""}
    driver.save_state()
    token = root / "token.md"
    token.write_bytes(b"rework")
    with contextlib.redirect_stdout(io.StringIO()):
        driver.take_answer(token)
    return dict(driver.state.get("seam_rework") or {})


def c26_n2_a_crash_before_the_registration_loses_nothing() -> None:
    """§7 C2-6 (§L-4 N2), the mutation's own pin: the process dies AFTER the person answered and BEFORE the controller registered the
    rework (nothing is registered): the record is still in memory and in the saved state, and the next entry registers the rework
    exactly once and only then drops the record. A step that drops the record first loses the choice - no record, no rework."""
    root, driver, rel, argv_log, runs = c26_rig()
    try:
        record = c26_choose(driver, root, rel)

        def crash(*a, **k):
            raise RuntimeError("the process died before the controller registered the rework")
        driver.rework = crash
        died = False
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                driver.seam_rework_step()
        except RuntimeError:
            died = True
        saved = json.loads((driver.state_dir / "driver-state.json").read_text(encoding="utf-8")).get("seam_rework")
        check_eq("C26 N2 crash: the step died, the record is alive in memory and in the saved state, nothing was registered",
                 (died, driver.state.get("seam_rework") == record, saved == record, c26_rework_calls(argv_log)), (True, True, True, []))
        del driver.rework
        with contextlib.redirect_stdout(io.StringIO()):
            moved = driver.seam_rework_step()
        check_eq("C26 N2 crash: the next entry registers the rework exactly once and then drops the record",
                 (moved, len(c26_rework_calls(argv_log)), "seam_rework" in driver.state), (True, 1, False))
    finally:
        os.chdir(harness.PLUGIN_ROOT)
        harness.cleanup(root)


def c26_after_the_rework_the_reviewer_is_dispatched_again() -> None:
    """§7 C2-6 (§L-5 F-N2), cmp3 19:39 on S5: the chosen rework runs as the author's dispatch that does NOT close the stage (the author's
    finish gets the closing flag the driver passed), so S5 stays open and the next entry dispatches the window's reviewer
    (`qa-code-critic`) over the same cases; the controller's `rework` got `--purpose repair_verify`. A step that passes a true closing
    flag closes S5 over the author and no reviewer is sent."""
    from controller import Controller
    import test_controller_state as BASE
    root, driver, rel, argv_log, runs = c26_rig()
    try:
        c26_choose(driver, root, rel)

        refused = []

        def author_finish(*a, **k):
            runs.append((a, k))
            if a[1] == "qa-automator":          # the finish the real run_role makes: accepted, the stage closed only if the flag says so
                for did, held in driver.controller_state()["dispatches"].items():
                    if held.get("status") == "running" and held.get("role") == "qa-automator":
                        try:
                            Controller(driver.task_root).apply("accept", {
                                "id": did, "status": "accepted", "stage_complete": k.get("complete") is True,
                                "evidence_refs": [BASE.evidence_ref(driver.task_root, did + ".txt", did)], "idempotency_key": "accept-" + did})
                        except Exception as exc:          # the controller refuses to close S5 over the author (no window record)
                            refused.append(str(exc)[:80])
            return "", ""
        driver.run_role = author_finish
        with contextlib.redirect_stdout(io.StringIO()):
            moved = driver.seam_rework_step()
        calls = c26_rework_calls(argv_log)
        check_eq("C26 F-N2: the step ran the author's round, not closing the stage; the controller got the default purpose",
                 (moved, len(calls), "repair_verify" in calls[0], refused), (True, 1, True, []))
        state = driver.controller_state()
        check_eq("C26 F-N2: S5 is NOT closed by the author's round", state["stages"]["S5"]["status"], "pending")
        action = driver.where()
        check_eq("C26 F-N2: the next entry of the loop owes S5 its stage again", (action.get("action"), action.get("stage")), ("prepare_stage", "S5"))
        driver.stand_check = lambda *a, **k: None
        driver.build_check = lambda *a, **k: None
        del runs[:]
        with contextlib.redirect_stdout(io.StringIO()):
            driver.stage_S5()
        check_eq("C26 F-N2: and that entry dispatches the window's reviewer over the reworked cases",
                 [(a[0], a[1], k.get("scope")) for a, k in runs], [("S5", "qa-code-critic", ["TC-1"])])
    finally:
        os.chdir(harness.PLUGIN_ROOT)
        harness.cleanup(root)


def c26_a_dry_run_says_once_and_does_not_spin_the_loop() -> None:
    """Lead's answer 5 on t-856: in a dry run `seam_rework_step` prints ONE line, starts nothing, keeps the record and returns False -
    nothing moved, so the loop does not go round `max_boundaries` times over the same line. Through `run()`: the line appears once."""
    root, driver, rel, argv_log, runs = c26_rig()
    try:
        record = c26_choose(driver, root, rel)
        driver.dry = True
        shown = io.StringIO()
        with contextlib.redirect_stdout(shown):
            moved = driver.seam_rework_step()
        lines = [line for line in shown.getvalue().splitlines() if line.strip()]
        check_eq("C26 dry: one line, False, nothing started, the record kept",
                 (moved, len(lines), "dry run" in (lines or [""])[0], c26_rework_calls(argv_log), runs, driver.state.get("seam_rework") == record),
                 (False, 1, True, [], [], True))
        driver.max_boundaries = 5
        driver.where = lambda: {"action": "stop", "reason": "the stub stops the loop"}
        shown = io.StringIO()
        with contextlib.redirect_stdout(shown):
            code = driver.run()
        check_eq("C26 dry: through the loop the line is said once and the loop ends at `where`",
                 (shown.getvalue().count("dry run: the rework the person chose is not started"), "paused after" in shown.getvalue(), code),
                 (1, False, 0))
    finally:
        os.chdir(harness.PLUGIN_ROOT)
        harness.cleanup(root)


def c26_running_dispatch():
    """The c26 rig with ONE running dispatch on the REAL controller (the chosen rework registered; the role is a recorder).
    (root, driver, the dispatch id, the rel of a words file holding Cyrillic and an arrow)."""
    root, driver, rel, argv_log, runs = c26_rig()
    c26_choose(driver, root, rel)
    with contextlib.redirect_stdout(io.StringIO()):
        driver.seam_rework_step()
    running = [did for did, held in driver.controller_state()["dispatches"].items() if held.get("status") == "running"]
    words = "".join(chr(c) for c in (0x43D, 0x435, 0x20, 0x43D, 0x443, 0x436, 0x435, 0x43D)) + " " + chr(0x2192) + " start it again\r\n"
    return root, driver, running[0], driver.words_file(words, "f1").relative_to(driver.task_root).as_posix()


def c26_t873_f1_a_release_by_code_reaches_the_real_controller_in_the_drivers_environment() -> None:
    """t-873 F-1, both roads that release by code - `_exit_fresh` (the exit-limit `fresh`) and `restart_by_option` (the `restart` token) -
    on the REAL controller: the words hold Cyrillic and an arrow, neither UTF-8 variable is in the parent's environment, the release is
    recorded (`released_by_person`), nothing is held, and the child's environment is the DRIVER'S own (`self.env`, UTF-8 included).
    The edge: a controller that fails for another reason (a dispatch it does not know) records nothing - the held text is true then,
    and the proof is the controller's record (the statuses), not what it printed."""
    import subprocess
    import story_run
    kept = {name: os.environ.pop(name) for name in ("PYTHONUTF8", "PYTHONIOENCODING") if name in os.environ}
    real_run, seen = subprocess.run, []
    subprocess.run = lambda argv, *a, **k: (seen.append((argv, k.get("env"))), real_run(argv, *a, **k))[1]
    try:
        for road in ("restart_by_option", "_exit_fresh"):
            root, driver, dispatch, rel = c26_running_dispatch()
            try:
                del seen[:]
                with contextlib.redirect_stdout(io.StringIO()):
                    if road == "restart_by_option":
                        driver.restart_by_option("S8", dispatch, rel)
                    else:
                        driver._exit_fresh({"lines": ["a line"]}, "S5", dispatch, rel)
                releases = [env for argv, env in seen if "release" in argv]
                check_eq(f"C26 t-873 F-1 {road}: the controller recorded the release (rc 0 and the answer were read, nothing held)",
                         driver.controller_state()["dispatches"][dispatch].get("status"), "released_by_person")
                check_eq(f"C26 t-873 F-1 {road}: ONE release call, in the driver's own environment", (len(releases), releases[0] is driver.env), (1, True))
                check_eq(f"C26 t-873 F-1 {road}: ...which carries UTF-8 although the parent's environment does not",
                         (driver.env.get("PYTHONUTF8"), driver.env.get("PYTHONIOENCODING")), ("1", "utf-8"))
                before = {did: held.get("status") for did, held in driver.controller_state()["dispatches"].items()}
                held = None
                try:
                    with contextlib.redirect_stdout(io.StringIO()):
                        if road == "restart_by_option":
                            driver.restart_by_option("S8", "S9-nobody-7", rel)
                        else:
                            driver._exit_fresh({"lines": ["a line"]}, "S5", "S9-nobody-7", rel)
                except story_run.Person as person:
                    held = person
                check_eq(f"C26 t-873 F-1 {road} edge: a controller that fails for another reason: held, and its record shows nothing was released",
                         (held is not None and "nothing was" in held.text, {did: h.get("status") for did, h in driver.controller_state()["dispatches"].items()}),
                         (True, before))
            finally:
                os.chdir(harness.PLUGIN_ROOT)
                harness.cleanup(root)
    finally:
        subprocess.run = real_run
        os.environ.update(kept)


LEGACY_TWO = [{"token": "retry", "move": "person_does"}, {"token": "stop", "move": "stop_here"}]


def g27_take(d, rig, body: bytes, name: str, **asked) -> None:
    """One answer to a gate question the seam raised (`offered` retry / stop, the words of the original answer on file)."""
    d.state["asked"] = dict({"kind": "gate_B", "stage": "S8", "dispatch": "", "offered": ["retry", "stop"], "options": list(LEGACY_TWO),
                             "words_file": "", "why": "unread_answer", "block": ""}, **asked)
    path = rig.root / name
    path.write_bytes(body)
    with contextlib.redirect_stdout(io.StringIO()):
        d.take_answer(path)


def g27_held(d, rig, body: bytes, name: str, **asked):
    """`g27_take`, for an answer that comes back as the held question: the Person it raised (None when it raised nothing)."""
    import story_run
    try:
        g27_take(d, rig, body, name, **asked)
    except story_run.Person as person:
        return person
    return None


def g27_cmp3_1717_a_word_the_site_does_not_offer_is_the_gates_answer() -> None:
    """§7 C2-7 (cmp3 17:17, F-7c): the seam asked a gate `retry` / `stop`; the person answered `approve`. It is not a token of THAT
    question, so it is the gate's own answer: recorded once by code with the original prose kept under it (no circle through the
    conductor); words that are no approval go whole to the conductor with the earlier answer; a TOKEN still reads as a token; no file
    on record, no tail; a card line beside `approve` is not a token (the whole answer is compared)."""
    rig, d, decisions, defects = c14b_rig()
    try:
        d.rehearse = lambda gate: {"findings": []}
        rel = d.words_file(ORIGINAL, "answer").relative_to(d.task_root).as_posix()
        tail = "\n\nEarlier answer at this gate:\n" + ORIGINAL.strip()
        recorded, unread, stand, files = [], [], [], []
        real = d.record_by_code
        d.record_by_code = lambda kind, stage, words, **k: recorded.append(words) or real(kind, stage, words, **k)
        d.unread = lambda *a, **k: unread.append(k.get("words")) or files.append(d.answer_file())     # `unread` names `answer_file()` as `words_file`
        g27_take(d, rig, b"approve", "a1.md", words_file=rel)
        check_eq("C27 cmp3 17:17: `approve` to a retry / stop question is recorded ONCE, the original prose kept under it, the seam not called",
                 (recorded, decisions(), unread, d.state.get("asked")), (["approve" + tail], 1, [], {}))
        recorded.clear()
        g27_take(d, rig, b"make the export test stricter", "a2.md", words_file=rel)
        check_eq("C27: words that are no approval: nothing recorded, the conductor gets them with the earlier answer whole",
                 (decisions(), unread), (1, ["make the export test stricter" + tail]))
        # t-891 F-1: the file the NEXT question names (`unread` -> `words_file=answer_file()`) holds BOTH answers, the one the seam tokens
        # (`approve`, `rework --words-file`, `go on`) read through `original_words`; the first answer is not lost after one hop
        check_eq("C27 F-1: the next question's words file holds the new answer and the earlier one whole, and `original_words` reads it so",
                 ((d.task_root / files[-1]).read_bytes().decode("utf-8"), (d.original_words({"words_file": files[-1]}) or ("", ""))[1]),
                 (("make the export test stricter" + tail,) * 2))
        unread.clear()
        g27_take(d, rig, b"retry", "a3.md", words_file=rel)
        check_eq("C27 invariant 1: a token of the question reads as a token - nothing recorded, no seam call, no tail",
                 (decisions(), unread, d.state.get("asked")), (1, [], {}))
        g27_take(d, rig, b"approve", "a4.md", words_file="")
        check_eq("C27 edge: no words file on the question - the words go on as they are, no `Earlier answer` tail",
                 (recorded[-1:], decisions()), (["approve"], 2))
        # t-891 F-3: a words file that is NAMED and gone is the held road of the `approve` token in the same situation (t-722 4.6): nothing is
        # recorded, the person is told - never recorded silently without the earlier answer. Both roads into one gate behave the same.
        recorded.clear()
        held = [g27_held(d, rig, b"approve", "a5.md", words_file="state/words/gone.txt"),
                g27_held(d, rig, b"approve", "a5t.md", words_file="state/words/gone.txt",
                         offered=["approve", "retry", "stop"], options=[seam_option("approve", "approve_gate")] + LEGACY_TWO)]
        check_eq("C27 F-3: a gone words file: the typed `approve` (not a token of retry / stop) and the token `approve` are BOTH held - "
                 "a Person, nothing recorded, no decision", ([bool(person) for person in held], recorded, decisions()), ([True, True], [], 2))
        check_in("C27 F-3: ...and the person is told why", "nothing was recorded", held[0].text)
        check_eq("C27 F-3: the held answer is on the record first (its row names the words as the person wrote them)",
                 [row["words"] for row in jsonl(d.state_dir / "driver-answers.jsonl")][-1:], ["approve"])
        d.take_stand_gap_answers = lambda kind, words, qtext, stage, dispatch, **k: stand.append(k) or {"unread": ["TC-7: maybe"], "recorded": [], "note": "n"}
        before = decisions()
        g27_take(d, rig, b"approve\nTC-7: maybe", "a6.md", words_file=rel)
        check_eq("C27 invariant 4 (gate B): `approve` + a card line is no token: the cards are read with the earlier keys kept; an "
                 "unreadable line holds the approval at gate B (no open-items net there, t-550 F1), the words go to the conductor whole",
                 (stand, decisions() - before, unread[-1:]), ([{"keep_earlier": True}], 0, ["approve\nTC-7: maybe" + tail]))
        # t-550 F3: at gate A the same line rides the approval and the record keeps the whole words
        stand.clear()
        before = decisions()
        g27_take(d, rig, b"approve\nTC-7: maybe", "a6a.md", words_file=rel, kind="gate_A", stage="S4")
        check_eq("C27 invariant 4 (gate A): `approve` + a card line is no token: the cards are read with the earlier keys kept; an unreadable "
                 "line rides the approval and the record keeps the whole words", (stand, decisions() - before),
                 ([{"keep_earlier": True}], 1))
        # t-550 F3: the old meaning lives on for a HELD line (a refused record, `ask again`, `?`) at gate A: the conductor gets the words whole
        stand.clear()
        d.take_stand_gap_answers = lambda kind, words, qtext, stage, dispatch, **k: stand.append(k) or {
            "unread": ["TC-7: maybe"], "hold": ["TC-7: maybe"], "recorded": [], "note": "n"}
        before = decisions()
        g27_take(d, rig, b"approve\nTC-7: maybe", "a6h.md", words_file=rel, kind="gate_A", stage="S4")
        check_eq("C27 invariant 4 (held): a held line keeps the approval, the words go to the conductor whole",
                 (decisions() - before, unread[-1:]), (0, ["approve\nTC-7: maybe" + tail]))
        stand.clear()
        g27_take(d, rig, b"retry", "a7.md", words_file=rel)
        check_eq("C27 invariant 1: a token does not run the card reader (its keys live on to the recorder)", stand, [])
        g27_take(d, rig, b"approve\nTC-7: maybe", "a8.md", words_file=rel, kind="conductor", stage="S5")
        check_eq("C27 invariant 3: a kind that is no gate reads as before - no card reader, the seam", stand, [])
    finally:
        rig.close()


def g27_finding_6_the_keys_of_the_earlier_answer_live_on() -> None:
    """§5.3 (finding 6): `take_stand_gap_answers(..., keep_earlier=True)` leaves the cases and remedies an EARLIER answer set; the plain
    call drops them as it always did."""
    rig, d, decisions, defects = c14b_rig()
    try:
        for keep in (True, False):
            d.state["stand_accept_cases"], d.state["stand_accept_remedies"] = ["TC-1"], {"TC-1": {"kind": "x"}}
            with contextlib.redirect_stdout(io.StringIO()):
                d.take_stand_gap_answers("gate_A", "approve", "the question of the seam", "S4", "", keep_earlier=keep)
            check_eq(f"C27 finding 6: keep_earlier={keep}: the earlier keys are {'kept' if keep else 'dropped, as before'}",
                     (d.state.get("stand_accept_cases"), d.state.get("stand_accept_remedies")),
                     ((["TC-1"], {"TC-1": {"kind": "x"}}) if keep else (None, None)))
    finally:
        rig.close()


def g27_handed(d) -> list:
    """DC1-19: the answers are applied by the controller's `gate-decision` (the ONE executor), not by the driver, and the rig's `py` applies
    nothing. The driver's half is what it HANDS that call: this wraps `d.py` and keeps, per `gate-decision` call, the lines of the
    `--answers-file` as the call read them (split into lines: the file's line ends are the writer's)."""
    handed = []
    inner = d.py

    def py(script, *args, **k):
        if script == "controller.py" and "gate-decision" in args and "--answers-file" in args:
            handed.append(Path(args[args.index("--answers-file") + 1]).read_text(encoding="utf-8").strip().splitlines())
        return inner(script, *args, **k)
    d.py = py
    return handed


def g27_f2_the_earlier_answer_is_never_read_for_the_cards() -> None:
    """t-891 F-2: a second answer at a gate that CORRECTS a card id (`Q1: a` after `Q1: b`) applies `a`: the plan reads the card lines of
    the NEW answer alone (the `Earlier answer` tail would be a `parse_choices` conflict and nothing would be chosen), while the record the
    decision keeps (`record_by_code` words) is the person's words whole, the earlier answer under them (FR-8, FR-9)."""
    rig, d, decisions, defects = c14b_rig()
    try:
        d.rehearse = lambda gate: {"findings": []}
        first = "Q1: b\r\nbut keep the export test as it is\r\n"
        rel = d.words_file(first, "answer").relative_to(d.task_root).as_posix()
        handed = g27_handed(d)
        recorded = []
        real = d.record_by_code
        d.record_by_code = lambda kind, stage, words, **k: recorded.append((words, k.get("apply_words"))) or real(kind, stage, words, **k)
        g27_take(d, rig, b"approve\nQ1: a", "f2.md", kind="gate_A", stage="S4", words_file=rel)
        tail = "\n\nEarlier answer at this gate:\n" + first.strip()
        check_eq("C27 F-2: the decision keeps the person's words whole (the new answer, the earlier one under it); the cards are read from the new answer",
                 (recorded, decisions()), ([("approve\nQ1: a" + tail, "approve\nQ1: a")], 1))
        check_eq("C27 F-2: the executor is HANDED the new answer's lines alone (`Q1: a`) - not the earlier `Q1: b`, which would conflict with it",
                 handed, [["approve", "Q1: a"]])
    finally:
        rig.close()


def g27_f2_the_approve_token_reads_the_cards_of_the_new_answer_only() -> None:
    """t-891 F-2 on the TOKEN road: `Q1: b`, then `Q1: a` (prose that is no approval, so the seam asks again with the COMBINED words file), then
    the `approve` token on that question: `approve_by_option` reads the combined file whole as the record, but the cards only from its HEAD
    (the new answer) - Q1 reads `a`, `answered`, no conflict. Negative control: a words file with NO tail is passed on as before."""
    approve_options = dict(offered=["approve", "retry", "stop"], options=[seam_option("approve", "approve_gate")] + LEGACY_TWO)

    def story():
        rig, d, decisions, defects = c14b_rig()
        d.rehearse = lambda gate: {"findings": []}
        handed = g27_handed(d)
        recorded, files = [], []
        real = d.record_by_code
        d.record_by_code = lambda kind, stage, words, **k: recorded.append((words, k.get("apply_words"))) or real(kind, stage, words, **k)
        d.unread = lambda *a, **k: files.append(d.answer_file())
        return rig, d, decisions, recorded, files, handed

    first, second = "Q1: b\r\nbut keep the export test as it is\r\n", "Q1: a\nplease keep the export test as it is"
    rig, d, decisions, recorded, files, handed = story()
    try:
        rel = d.words_file(first, "answer").relative_to(d.task_root).as_posix()
        g27_take(d, rig, second.encode(), "t1.md", kind="gate_A", stage="S4", words_file=rel)
        combined = (d.task_root / files[-1]).read_bytes().decode("utf-8")
        g27_take(d, rig, b"approve", "t2.md", kind="gate_A", stage="S4", words_file=files[-1], **approve_options)
        check_eq("C27 F-2 token: the record holds BOTH answers whole, the cards are read from the new answer alone",
                 (recorded, decisions()), ([(combined, second)] * 2, 1))      # the 2nd answer's own (refused) try, then the token's
        check_eq("C27 F-2 token: the executor is HANDED the new answer's lines alone (`Q1: a`), once - no `Q1: b` to conflict with it",
                 handed, [second.splitlines()])
    finally:
        rig.close()
    rig, d, decisions, recorded, files, handed = story()
    try:
        rel = d.words_file(first, "answer").relative_to(d.task_root).as_posix()
        g27_take(d, rig, b"approve", "t3.md", kind="gate_A", stage="S4", words_file=rel, **approve_options)
        check_eq("C27 F-2 token control: a words file with no tail is recorded as before, no `apply_words`, the lines handed are its own",
                 (recorded, decisions(), handed), ([(first, None)], 1, [first.strip().splitlines()]))
    finally:
        rig.close()


def g27_the_fallback_rework_runs_once_with_the_original_words() -> None:
    """§7 C2-7 (§L-4 id 2, §L-5), through `take_answer` on the REAL controller: the fallback question of gate B, the answer `rework`, the
    conductor answers `ask_person` with ONE `rework` option carrying args -> the record is written, NO Person is raised (the person is
    not asked again), and the next entry calls `--operation rework` exactly once with the original answer's file, byte for byte."""
    import story_run
    root, driver, rel, argv_log, runs = c26_rig()
    try:
        from story_run_common import seam_option
        option = dict(seam_option("rework", "rework_stage"), args=C26_ARGS)
        driver.conductor = lambda text, *, words="", files=None, words_file=None: driver.calls.append((text, words_file)) or {
            "action": "ask_person", "did": "x", "question": "Which one?", "why_person": "access", "checked": "the refusal", "options": [option]}
        with contextlib.redirect_stdout(io.StringIO()):
            driver.ask(driver.fallback_person({"why": "unread_answer", "kind": "gate_B", "stage": "S8", "dispatch": "", "lead": "Your answer was not read.",
                                               "words_file": rel}))
        asked = driver.state["asked"]
        check_eq("C27 rework: the fallback question offers approve / rework / retry / stop with the original file", (asked["offered"], asked["words_file"]),
                 (["rework", "approve", "retry", "stop"], rel))
        token = root / "token.md"
        token.write_bytes(b"rework")
        raised = None
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                driver.take_answer(token)
        except story_run.Person as person:
            raised = person
        check_eq("C27 rework: the person is not asked again; the conductor was called once with the original file; the record is written",
                 (raised, [file for _text, file in driver.calls], (driver.state.get("seam_rework") or {}).get("words_file")), (None, [rel], rel))
        with contextlib.redirect_stdout(io.StringIO()):
            driver.seam_rework_step()
        calls = c26_rework_calls(argv_log)
        check_eq("C27 rework: the next entry calls `--operation rework` ONCE, with the words by file", (len(calls), "--words-file" in calls[0]), (1, True))
        check_eq("C27 rework: ...and that file is the original answer, byte for byte",
                 Path(calls[0][calls[0].index("--words-file") + 1]).read_bytes(), (driver.task_root / rel).read_bytes())
    finally:
        os.chdir(harness.PLUGIN_ROOT)
        harness.cleanup(root)


def cx1_11_the_driver_records_the_pinned_cases_by_keys_and_keys_its_call_by_content() -> None:
    """CX1-11 B-1/N-4/N-5/N-6, E11: `Driver.revise_plan` is the second writer of the scope. Real controller, real store."""
    import story_run
    import test_controller_rework_scope as RS
    from controller import Controller
    from event_store import StateConflict
    root, parent, _ = RS.keyed_story(gate=False)

    class Stub:
        task_root, task = root, root.name

        def controller_state(self):
            return Controller(root).state()

        def controller(self, operation, *args, input_data=None):
            try:
                return {"event": Controller(root).apply(operation, dict(input_data))}
            except (ValueError, StateConflict) as exc:
                raise story_run.Refusal(f"controller {operation}:\n{exc}")

    fixed_plan = []          # the plan bytes every call after the first sees: a write of the scope marks the plan, so without this
                             # the plan hash differs between two calls of the same pins, and the revision in the key is never tested

    def call():
        if fixed_plan:
            (root / "work" / "test-plan.json").write_bytes(fixed_plan[0])
        story_run.Driver.revise_plan(Stub())

    def events():
        return len(Controller(root).store.read())

    def scope():
        return Controller(root).state()["scope"]
    try:
        before = events()
        call()
        check_eq("an identical repeat: the store already holds the pinned keys, no event, no refusal", events(), before)
        plan = root / "work" / "test-plan.json"
        plan.write_text(plan.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        fixed_plan.append(plan.read_bytes())
        call()
        check_eq("N-4: the plan changed, the scope did not: skip, no event (the drift is `_plan_drift`'s, at S5)", events(), before)
        RS.pin_case_files(root, {**RS.AREAS, 3: ["session-feedback"]})          # B: an area dropped, the COUNT is the same
        call()
        check_eq("an area dropped at a constant count is ONE new event, not a silent skip", events(), before + 1)
        check_eq("and the store follows the pins", scope(), ["TC-001", "TC-002", "TC-003", "TC-004"])
        RS.pin_case_files(root, RS.AREAS)                                          # A again
        call()
        check_eq("N-5: the driver writes A again after B (a new event)", events(), before + 2)
        check_eq("and the store holds A", scope(), RS.APPROVED_KEYS)
        RS.pin_case_files(root, {**RS.AREAS, 3: ["session-feedback"]})             # B once more: the driver wrote B before
        call()
        check_eq("N-5: A -> B -> A -> B is a FOURTH event: the key carries the revision, so no replay of the first B",
                 (events(), scope()), (before + 3, ["TC-001", "TC-002", "TC-003", "TC-004"]))
        RS.pin_case_files(root, {**RS.AREAS, 1: ["session-feedback", "billing"]})  # a re-key (E12)
        call()
        check_eq("a re-key is a new event, not 'idempotency key reused'", events(), before + 4)
        check("and the store holds the qualified keys", "billing/TC-001" in scope() and "TC-001" not in scope(), str(scope()))
        broken = next((root / "state" / "case-versions" / "TC-002").glob("*.md"))
        broken.write_text(broken.read_text(encoding="utf-8").replace("id: TC-002", "id: TC-052"), encoding="utf-8")
        refused = ""
        try:
            call()
        except story_run.Refusal as exc:
            refused = exc.text
        check_in("N-6: an index that cannot be built is a Refusal with the controller's words, not a crash",
                 "the case index cannot be built", refused)
        check_eq("and no event was written", events(), before + 4)
    finally:
        harness.cleanup(parent)


def main() -> None:
    run_scenarios([], [cx1_11_the_driver_records_the_pinned_cases_by_keys_and_keys_its_call_by_content, g27_cmp3_1717_a_word_the_site_does_not_offer_is_the_gates_answer, g27_finding_6_the_keys_of_the_earlier_answer_live_on,
                       g27_f2_the_earlier_answer_is_never_read_for_the_cards, g27_f2_the_approve_token_reads_the_cards_of_the_new_answer_only,
                       g27_the_fallback_rework_runs_once_with_the_original_words, c26_cmp3_1939_the_token_runs_the_rework_by_code, c26_n2_a_crash_before_the_registration_loses_nothing,
                       c26_after_the_rework_the_reviewer_is_dispatched_again, c26_a_dry_run_says_once_and_does_not_spin_the_loop,
                       c26_t873_f1_a_release_by_code_reaches_the_real_controller_in_the_drivers_environment,
                       c26_words_edges_and_the_long_words, c14b_approval_is_its_word, c14b_gate_a_prose_under_the_word_is_recorded, c14b_kept_and_old_answers,
                       c14b_no_word_list_and_the_note, c14b_the_note_derives_from_every_accepted_rework,
                       c14b_f1_a_driver_issued_rework_is_never_told_as_the_persons_words,
                       c14b_a6_the_loop_after_the_rework_reaches_gate_b_with_the_note_once,
                       c14b_a_byte_order_mark_and_crlf_and_go_on_through_take_answer,
                       c14b_h2_a_token_at_a_gate_is_executed_on_a_done_stage_and_nowhere_else,
                       gate_a_answer_is_recorded_against_the_card_as_shown, cmp2_round_stops_and_survives_a_relaunch, key_set_and_cap,
                       the_loop_reaches_the_gate_before_its_own_stuck_guard, rehearsal_edges,
                       open_question_and_kept_answer, series_stamp, empty_scope_and_failed_repair,
                       list_goes_through_the_conductor_not_the_table, designer_round_and_cap, critic_fixes_t214, what_the_step_reads,
                       gate_b_and_the_list_at_the_top, gate_entry_steps_owed_by_a_refused_finish,
                       dry_run_writes_nothing, a_story_from_before_the_change, repair_rows_probe_and_unraised,
                       repair_row_adapt_reporter_and_the_bound_is_the_call])
    harness.finish("test_story_run_gate_repair")


if __name__ == "__main__":
    main()
