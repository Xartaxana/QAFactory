#!/usr/bin/env python3
"""An exit-gate refusal that survives the resume limit goes through the ONE seam (conductor/1, C1-5d2; t-698 §12-§14, t-764).

What is proved here, in-process, with the roles and commands recorded and never run (the rig of test_story_run_repair_limit.py):
  * EL1  a set the role has already seen is ASKED: kind `exit_limit`, key `exit.resume_limit`, four priced answers, no paid call,
         the ticket keys of the S1 sources and no SRC- / dispatch id (`human_text.problems` empty);
  * EL2  `round` is granted by the answer and SPENT inside the seam on the next entry: `spent` is on disk BEFORE the call, the check's
         lines and the person's words go in whole, and the same set comes back asked again ("once more after your answer");
  * EL3  `fresh` releases through the controller's operation and the relaunch reason carries the check's lines AND outranks the packet's;
  * EL4  an absent option is SAID: no session -> no `round`; a dispatch that is not live / a closed story -> no `fresh`;
  * EL5  `go on` at S1 closes the sources' open work through `accept-gap --point` with the shown text;
  * EL6  `go on` writes one waiver row per line that reached the seam (the block = the whole line), files the factory's finding, and
         the ONE sweep revokes the rows of a dispatch that is no longer live; a set with a handover-form line offers no `go on` (A1);
  * EL7  `stop` is held;  EL10 a non-token word is read by the conductor, a token is not words for a role;
  * EL14 12 sources are listed whole, 13 as 12 + `(+1 more)`; a broken inventory falls to the count (Q-b);
  * A9 the lead is conditional (session gone / structured / the paid count only when above 0); A12 a resume spends `pending_words`.
  * worker 2 (t-764): EL5/EL3 END TO END over the REAL controller (`Live`: real exit gate, real `accept-gap`/`waiver.py`/`release`/`next`,
    only `claude` is the stub) and A1 (`handoff` RETURNS the digest after `go on`); the failed `accept-gap` / refused `release` edges; EL2/EL6 at
    an E8 finish refusal; A7 (the conductor road carries `asked.words_file`); EL10 through `take_answer`; A12 on `resume_role`; risk 4 (the
    conductor cap bounds a `go on` outside the offered list). Slow on purpose: each `Live` story is a seeded project with real commands.
  * fix round (t-781, merge critic t-778): M1 words outside the conductor's options go back to the SITE's question (and risk 4 ends in it);
    m2 an error with no words keeps `pending_words`; m3 the revoke is the driver's act in the driver's words; m4 the sweep at the top of
    `handoff`; m5 the paid round's head names the real refusal; m6 the ONE `pass_block` helper; m7 the offer is the data row's answers.
"""
import contextlib
import io
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import PLUGIN_ROOT, check, check_eq, check_in, check_not_in, finish  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import human_text  # noqa: E402
import story_run  # noqa: E402

REAL_RELEASE = story_run.waiver.run_release       # the Rig below swaps it for a recorder; `Rig.done` and the `Live` stories use this one
TASK, D = "QA-9", "S1-qa-scout-1"
LINES = ["source_preflight: SRC-1: materials lack retrieval or inspection receipts", "source_preflight: SRC-2: materials lack retrieval or inspection receipts"]


class Rig:
    def __init__(self, stage="S1", role="qa-scout", status="running", sid="sess-1", closed=False):
        from story_run_common import driver_for, seed
        self.root, self.task_root, env = seed(TASK)
        self.driver = d = driver_for(self.root, env, TASK, max_boundaries=1)
        self.stage, self.role, self.calls, self.prompts, self.spent_at_call = stage, role, [], [], []
        self.kinds, self.fail = [], {}            # the kind of every `claude` call; {script: (code, output)} - a command that fails
        d.boundary = f"{stage}:{D}"
        d.state["sessions"][D] = sid
        d.controller_state = lambda: {"dispatches": {D: {"id": D, "stage": stage, "role": role, "status": status, "released_by_person": ""}},
                                      "stages": {stage: {"status": "running"}}}
        d.no_move_facts = lambda state: {"dispatch_status": status, "closed": closed, "gate": ""}
        d.dispatch_role = lambda dispatch: role
        d.form_errors = lambda dispatch: []
        d.progress_line = lambda: None
        d.conductor = lambda *a, **k: self.calls.append(("conductor",)) or {"action": "continue"}
        d.py = self.spy
        # Since C2-6 (t-722 §4.4, N4) the release is `waiver.run_release`, not `d.py("controller.py", ...)`: this rig records it as the same
        # controller call (the argv the controller gets), so a command is still recorded and never run. The real release is `Live`'s.
        story_run.waiver.run_release = lambda task_root, dispatch, *, words="", words_file="", env=None: self.spy(
            "controller.py", "--operation", "release", "--dispatch", dispatch, "--words-file", words_file)
        d.run_claude = self.claude
        d.s1_open_work = lambda: [{"source_id": "SRC-1", "key": "TP3-1", "text": "materials not inspected", "points": ["source:not_inspected"]}]

    def spy(self, script, *args, **kw):
        self.calls.append((script, [str(a) for a in args]))
        return self.fail.get(script, (0, ""))

    def claude(self, kind, prompt, **kw):
        state = json.loads((self.task_root / "state" / "driver-state.json").read_text(encoding="utf-8"))
        self.spent_at_call.append((state.get("exit_limit") or {}).get(D, {}).get("rounds"))
        self.prompts.append(prompt)
        self.kinds.append(kind)
        return {"session_id": "sess-1", "result": "new words", "is_error": False, "stderr": "", "total_cost_usd": 0.0, "num_turns": 1}

    def seam(self, lines=LINES, sid="sess-1", why="handoff", stage=None, role=None):
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.driver.exit_limit(stage or self.stage, role or self.role, D, lines, sid=sid, why=why)
        except story_run.Person as person:
            return person
        return None

    def answer(self, words, file="state/words/a.txt", original=""):
        (self.task_root / "state" / "words").mkdir(parents=True, exist_ok=True)
        (self.task_root / (original or file)).write_text(words if not original else "do it once more, and check the body too", encoding="utf-8")
        self.driver._answer = {"text": words, "rel": file}
        with contextlib.redirect_stdout(io.StringIO()):
            return self.driver._answer_exit_limit(words, "q", self.stage, D, words_file=original)

    def scripts(self, name):
        return [a for s, a in (c for c in self.calls if len(c) == 2) if s == name]

    def done(self):
        story_run.waiver.run_release = REAL_RELEASE
        harness.cleanup(self.root)


def tokens_of(person):
    return re.findall(r"`([a-z ]+)` —", person.text)


def el1_asked_with_four_priced_answers():
    rig = Rig()
    try:
        person = rig.seam()
        check("EL1: the seam raises a Person", person is not None)
        check_eq("EL1: kind exit_limit, stage S1, the dispatch", (person.kind, person.stage, person.dispatch), ("exit_limit", "S1", D))
        check_eq("EL1: round / fresh / go on / stop, in the data's order", tokens_of(person), ["round", "fresh", "go on", "stop"])
        check_in("EL1: the ticket key and the point's own words", "TP3-1 — materials not inspected", person.text)
        check_in("EL1: the story's place and the role in words", "The scout finished its work there", person.text)
        check_in("EL1: the three price lines follow each answer", "delivery waits until this is done", person.text)
        check_eq("EL1: the text obeys human-questions.md", human_text.problems(person.text + human_text.TAIL, offered=list(person.priced)), [])
        for needle in (D, "SRC-", "source_preflight", "S1-qa"):
            check_not_in(f"EL1: no `{needle}` in what the person reads", needle, person.text)
        check_in("EL1: the check's lines, whole, are beside it", LINES[0], person.details)
        check_eq("EL1: no paid call", [c for c in rig.calls if c == ("conductor",)], [])
        check_not_in("EL9/A9: the paid count is not printed while it is 0", "after your answer", person.text)
        check_eq("EL1: the facts are kept for the answer", rig.driver.state["exit_limit"][D]["ask"]["offer"], ["round", "fresh", "go on", "stop"])
    finally:
        rig.done()


def el2_a_round_is_spent_inside_the_seam_before_the_call():
    rig = Rig()
    try:
        rig.seam()
        check("EL2: `round` is a token", rig.answer("round", original="state/words/orig.txt") is True)
        rec = rig.driver.state["exit_limit"][D]
        key = rec["key"]
        check_eq("EL2: granted 1, spent 0 until the next entry", (rec["rounds"][key]["granted"], rec["rounds"][key]["spent"]), (1, 0))
        rig.driver.state["pending_words"][D] = "old words"
        check_eq("EL2: the next entry spends the round and returns", rig.seam(), None)
        check_eq("EL2: `spent` was on disk BEFORE the call", rig.spent_at_call[0][key]["spent"], 1)
        check_in("EL2: the check's lines go in whole", LINES[1], rig.prompts[0])
        check_in("EL2: and the person's ORIGINAL words, whole (FR-8)", "do it once more, and check the body too", rig.prompts[0])
        check_not_in("EL2: no second sentence after the text (sentence='')", story_run.Driver.RESUME_SENTENCE, rig.prompts[0])
        check_eq("EL12/A12: the resume spent the pending words", rig.driver.state["pending_words"].get(D), None)
        person = rig.seam()
        check_in("EL2: the same set again is asked again, with the paid count", "once more after your answer", person.text)
        check_eq("EL2: no second round without an answer of its own", len(rig.prompts), 1)
    finally:
        rig.done()


def el3_fresh_releases_and_the_relaunch_reason_outranks_the_packet():
    rig = Rig()
    try:
        rig.seam()
        check("EL3: `fresh` is a token", rig.answer("fresh", original="state/words/orig.txt") is True)
        release = rig.scripts("controller.py")
        check_eq("EL3: the controller's own `release` ran once for the dispatch", [(a[a.index("--operation") + 1], a[a.index("--dispatch") + 1]) for a in release],
                 [("release", D)])
        check_in("EL3: with the person's ORIGINAL words file", "orig.txt", " ".join(release[0]))
        line = rig.driver.state["exit_limit"][D]["fresh_line"]
        check_in("EL3: the fresh line names the check's lines", LINES[0], line)
        rig.driver.controller_state = lambda: {"dispatches": {D: {"released_by_person": "start it again, and check the body too"}}}
        reason = rig.driver.relaunch_reason({"relaunch_of": D, "reason": "the packet's own reason"}, {})
        check_in("EL3: the relaunch reason carries the fresh line", LINES[0], reason)
        check_in("EL3: and the person's words, read once from the controller's record", "check the body too", reason)
        check_in("EL3: and the packet's reason AFTER them", "the packet's own reason", reason)
        check_not_in("EL3: not the old line", "never reached an agent", reason)
        check_in("EL3/A8: a release by ANY road carries the words (the conductor's `restart`)",
                 "check the body too", rig.driver.relaunch_reason({"relaunch_of": D}, {}))
        rig.driver.controller_state = lambda: {"dispatches": {}}
        rig.driver.state["exit_limit"].pop(D)
        check_in("EL3 negative: no release, no fresh line - today's line", "never reached an agent", rig.driver.relaunch_reason({"relaunch_of": D}, {}))
    finally:
        rig.done()


def el4_an_absent_option_is_said():
    rig = Rig()
    try:
        person = rig.seam(sid="")
        check_eq("EL4: no session -> no `round`", tokens_of(person), ["fresh", "go on", "stop"])
        check_in("EL4: and it says why", "session cannot be resumed", person.text)
        gone = Rig(status="superseded")
        person = gone.seam()
        check_eq("EL4: a dispatch that is not live -> no `fresh`", tokens_of(person), ["round", "go on", "stop"])
        check_in("EL4: and it says why", "Starting it again is not possible here", person.text)
        gone.done()
        closed = Rig(closed=True)
        check_in("EL4: a closed story (S9) -> no `fresh`, said", "the story is closed", closed.seam().text)
        closed.done()
        sessionless = Rig()
        person = sessionless.seam(why="session_gone")
        check_eq("EL4/E10: a session that no longer answers -> no `round`", tokens_of(person), ["fresh", "go on", "stop"])
        check_in("EL4/A9: the lead says so", "its session no longer answers", person.text)
        check_not_in("EL4/A9: it never claims to have sent the role back once more", "came back with the same gaps", person.text)
        sessionless.done()
        structured = Rig()
        check_in("A9: E11 says the structured handover", "over its structured handover", structured.seam(why="structured").text)
        structured.done()
    finally:
        rig.done()


def el5_go_on_at_s1_closes_the_sources_work_first():
    rig = Rig()
    try:
        rig.seam()
        check("EL5: `go on` is a token", rig.answer("go on") is True)
        gap = rig.scripts("ticket_adapter.py")
        check_eq("EL5: one accept-gap for the source, its point and the shown text", [(a[0], a[a.index("--source-id") + 1], a[a.index("--point") + 1]) for a in gap],
                 [("accept-gap", "SRC-1", "source:not_inspected")])
        check_in("EL5: --shown-text is the line the person was shown", "the step closes as it is", gap[0][gap[0].index("--shown-text") + 1])
        check_eq("EL5: then one waiver row per line", [a[a.index("--block") + 1] for a in rig.scripts("waiver.py")], LINES)
    finally:
        rig.done()


def el6_go_on_passes_whole_lines_files_the_finding_and_the_sweep_revokes():
    rig = Rig(stage="S4", role="qa-case-designer")
    try:
        lines = ["case_gate: TC-1 has no oracle", "case_gate: TC-2 has no oracle"]
        rig.seam(lines)
        rig.answer("go on")
        check_eq("EL6: one waiver row per line, the block = the whole line", [a[a.index("--block") + 1] for a in rig.scripts("waiver.py")], lines)
        check_eq("EL6/A6: the factory finding is filed (FR-4)", len(rig.scripts("project_decisions.py")), 1)
        check_eq("EL6: the rows are kept for the sweep", [p["block"] for p in rig.driver.state["exit_limit"][D]["passes"]], lines)
        rig.driver.revoke_passes_of_dead()
        check_eq("EL6/A5: a live dispatch's rows stand", len(rig.scripts("waiver.py")), 2)
        rig.driver.controller_state = lambda: {"dispatches": {D: {"status": "accepted"}}}
        rig.driver.revoke_passes_of_dead()
        revoked = [a for a in rig.scripts("waiver.py") if "--revoke" in a]
        check_eq("EL6/A5: the sweep revokes each row of a dispatch that is no longer live", [a[a.index("--block") + 1] for a in revoked], lines)
        check_eq("EL6/A5: and forgets them", rig.driver.state["exit_limit"][D]["passes"], [])
        rig.driver.forget_resumes(D)
        check("EL6/A5: `forget_resumes` clears the state", D not in rig.driver.state["exit_limit"])
        form = Rig(stage="S4", role="qa-case-designer")
        form.driver.form_errors = lambda dispatch: ["handover form x.yaml - scope: missing"]
        person = form.seam(lines + ["handover form x.yaml - scope: missing"])
        check_eq("EL6/A1: a handover-form line -> three options, `go on` absent", tokens_of(person), ["round", "fresh", "stop"])
        check_in("EL6/A1: and said, in the story's words", "handover form is not complete in 1 place(s); only the case designer can fill it", person.text)
        form.done()
    finally:
        rig.done()


def el7_stop_is_held_and_el10_words_go_to_the_conductor():
    rig = Rig()
    try:
        rig.seam()
        try:
            rig.answer("stop")
            check("EL7: `stop` raises", False)
        except story_run.Person as held:
            check_in("EL7: the question is held with the stop sentence", "You said to stop. Nothing runs and nothing is spent.", held.text)
        unread = []
        rig.driver.unread = lambda *a, **k: unread.append((a, k))
        check_eq("EL10: other words are not a token", rig.answer("please give it one more try with this note"), False)
        check_eq("EL10: they go to the seam with the doors and an `again`", (len(unread), sorted(unread[0][1]["doors"]), callable(unread[0][1]["again"])),
                 (1, ["fresh", "go on", "round", "stop"], True))
        check_eq("EL10: a token leaves no pending words", rig.driver.state["pending_words"].get(D), None)
    finally:
        rig.done()


def el14_the_cut_of_the_source_list_and_a_broken_inventory():
    rig = Rig()
    try:
        many = lambda n: [{"source_id": f"SRC-{i}", "key": f"TP3-{i}", "text": "materials not inspected", "points": ["p"]} for i in range(n)]
        for n, tail in ((12, False), (13, True)):
            rig.driver.s1_open_work = lambda n=n: many(n)
            text = rig.seam().text
            check_eq(f"EL14: {n} sources -> {min(n, 12)} listed", len(re.findall(r"^- TP3-\d+ —", text, re.M)), min(n, 12))
            check_eq(f"EL14: the cut is said exactly when there are more ({n})", "(+1 more)" in text, tail)
        del rig.driver.s1_open_work
        (rig.task_root / "work").mkdir(parents=True, exist_ok=True)
        (rig.task_root / "work" / "source-inventory.json").write_text("{not json", encoding="utf-8")
        person = rig.seam()
        check("EL14/Q-b: a broken inventory still raises the SAME question (not the generic fallback)", person is not None and person.kind == "exit_limit")
        check_in("EL14/Q-b: with the count and the details file", "handover is not complete in 2 place(s)", person.text)
    finally:
        rig.done()


# --- the remainder of t-698 §12.5 / §14 (t-764, worker 2): the REAL controller, E8, the conductor road, the bounds -------------------------


class Live:
    """The REAL controller, the real commands (`accept-gap`, `waiver.py`, `controller.py release`) and the real exit gate over a seeded story;
    only `claude` is the stub. `inventory`: a source inventory whose one source has an open work point (`source:not_inspected`)."""

    def __init__(self, inventory=True):
        import hashlib
        from controller import Controller
        from story_run_common import GOOD_MANIFEST, SCOUT_DIGEST, driver_for, seed
        self.root, self.task_root, self.env = seed(TASK)
        self.digest = SCOUT_DIGEST.replace("{task}", TASK)
        self.manifest = json.dumps(GOOD_MANIFEST).replace("{task}", TASK)
        work = self.task_root / "work"
        if inventory:
            import test_gap_points as GP
            text = b'{"key": "TP3-1"}'
            snapshot = work / "sources" / "SRC-1" / "r1" / "ticket.json"
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_bytes(text)
            item = GP.source("SRC-1", "TP3-1", relation="task", relevance_reason="the task", assessment_ref=None, discovered_from=None,
                             relation_evidence=None, fetched_at="t", revision="r1", snapshot_ref="sources/SRC-1/r1/ticket.json",
                             content_hash=hashlib.sha256(text).hexdigest(), inspection_status="pending")
            (work / "source-inventory.json").write_text(json.dumps(GP.inv(item)), encoding="utf-8")
            (work / "context-manifest.json").write_text(self.manifest, encoding="utf-8")
            (work / "context-bundle.json").write_text("{}", encoding="utf-8")
        Controller(self.task_root).apply("dispatch", {"id": D, "stage": "S1", "role": "qa-scout", "scope": [], "input_hash": "sources-1",
                                                      "budget": {}, "known_paths": {"root": str(self.task_root), "project_root": str(self.root)},
                                                      "idempotency_key": "dispatch:" + D})
        harness.run_script("stage_done.py", "--task", TASK, "--stage", "S1", "--status", "running", "--role", "qa-scout", cwd=self.root, env=self.env)
        self.driver = d = driver_for(self.root, self.env, TASK, max_boundaries=1)
        d.boundary = f"S1:{D}"
        d.state["sessions"][D] = "sess-1"
        d.progress_line = lambda: None
        self.result = {"is_error": False, "result": self.digest, "session_id": "sess-1", "exit_code": 0, "stderr": ""}

    def quiet(self, call, *args, **kw):
        with contextlib.redirect_stdout(io.StringIO()):
            return call(*args, **kw)

    def errors(self):
        return self.driver.exit_errors("qa-scout", self.digest) + self.driver.form_errors(D)

    def prime(self):
        """The role has already seen this finding set: the record the free resume writes (so the next entry is the seam's)."""
        self.driver.note_resume(D, "sess-1", story_run.finding_key(self.errors()), "handoff")

    def handoff(self):
        return self.quiet(self.driver.handoff, "qa-scout", "S1", D, self.result)

    def asked_person(self):
        try:
            self.handoff()
        except story_run.Person as person:
            return person
        return None

    def answer(self, words):
        """The person's answer to the open question, through `_answer_exit_limit`."""
        (self.task_root / "state" / "words").mkdir(parents=True, exist_ok=True)
        (self.task_root / "state" / "words" / "a.txt").write_text(words, encoding="utf-8")
        self.driver._answer = {"text": words, "rel": "state/words/a.txt"}
        return self.quiet(self.driver._answer_exit_limit, words, "q", "S1", D)

    def dispatch(self):
        from controller import Controller
        return (Controller(self.task_root).state().get("dispatches") or {}).get(D) or {}

    def accept_s1(self):
        """The controller's own `accept` of the S1 dispatch: the refusal's text, or None when it accepted."""
        import hashlib
        import story_step
        from controller import Controller
        from event_store import StateConflict
        path = self.task_root / "work" / "context-manifest.json"
        path.write_text(self.manifest, encoding="utf-8")
        try:
            # what `story_step finish` itself passes for the gaps a person accepted (`_s1_accepted_gaps`): the controller closes S1 over them by name
            Controller(self.task_root).apply("accept", {"id": D, "status": "accepted", "stage_complete": True, "idempotency_key": "accept:" + D,
                                                        "evidence_refs": [{"path": "work/context-manifest.json",
                                                                           "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}],
                                                        **story_step._s1_accepted_gaps(self.task_root)})
        except StateConflict as exc:
            return str(exc)
        return None

    def done(self):
        harness.cleanup(self.root)


def el5_end_to_end_go_on_at_s1_closes_the_sources_and_the_real_controller_accepts():
    """EL5 / A1 with nothing stubbed but `claude`: the REAL exit gate refuses S1 over the source receipts; the REAL controller refuses to accept S1
    (the person's waiver alone would not change that: `source_inputs` raises before `_passed_by_person`); `go on` runs the REAL `accept-gap
    --point` and `waiver.py`; then `handoff` RETURNS the digest (A1: the stage goes on, not merely "rows written"), the REAL controller accepts S1,
    gate A lists the sources among what the person decided, and the next stage's dispatch is not refused."""
    live = Live()
    try:
        live.prime()
        check_in("EL5/e2e: the real gate names the source receipts", "lack retrieval or inspection receipts", " ".join(live.errors()))
        person = live.asked_person()
        check("EL5/e2e: the second entry over the same set is asked (the seam), not resumed", person is not None and person.kind == "exit_limit")
        check_eq("EL5/e2e: round / fresh / go on / stop", tokens_of(person), ["round", "fresh", "go on", "stop"])
        check_in("EL5/e2e: the S1 sources are listed by ticket key and the point's own words", "TP3-1 — materials not inspected", person.text)
        control = live.accept_s1()
        check("EL5/e2e control: BEFORE `go on` the real controller refuses to accept S1", control is not None and "sources pending/invalid" in control, str(control))
        check_eq("EL5/e2e control: and the dispatch is still running", live.dispatch().get("status"), "running")
        check("EL5/e2e: `go on` is a token", live.answer("go on") is True)
        import source_inventory as SI
        inventory = SI.load_inventory(live.task_root / "work" / "source-inventory.json")
        summary = SI.completeness(inventory)
        check_eq("EL5/e2e: the REAL accept-gap closed the open work point (nothing open, the person closed it)",
                 (summary["open_points"], summary["closed_by_person"], summary["gate_blocked"]), ({}, {"SRC-1": ["source:not_inspected"]}, False))
        shown = inventory["sources"][0]["gap_acceptance"]["accepted_points"][0]["shown_text"]
        check_in("EL5/e2e: and stored the line the person was shown as the text they accepted", "the step closes as it is", shown)
        held = live.driver.state["exit_limit"][D]
        check_eq("EL5/A6/e2e: one waiver row per line that reached the seam", [p["block"] for p in held["passes"]], held["lines"])
        check_eq("EL5/A1: `handoff` now RETURNS the digest - the stage goes on", live.handoff(), live.digest.strip())
        check_eq("EL5/e2e: the real exit gate has nothing left to say", live.errors(), [])
        check_eq("EL5/e2e: the REAL controller accepts S1", live.accept_s1(), None)
        check_eq("EL5/e2e: and the dispatch is accepted", live.dispatch().get("status"), "accepted")
        import gate_brief
        gaps = gate_brief.sources(live.task_root)["accepted_gaps"]
        check("EL5/e2e: gate A lists the source among what the person decided (`Already decided by you`)", any(g.startswith("TP3-1") for g in gaps), str(gaps))
        from controller import Controller
        Controller(live.task_root).apply("dispatch", {"id": "S2-qa-requirements-tester-1", "stage": "S2", "role": "qa-requirements-tester", "scope": [],
                                                      "input_hash": "s2", "budget": {}, "known_paths": {"root": str(live.task_root), "project_root": str(live.root)},
                                                      "idempotency_key": "dispatch:s2"})
        check("EL5/e2e: at S2 nothing refuses", "S2-qa-requirements-tester-1" in (Controller(live.task_root).state().get("dispatches") or {}))
    finally:
        live.done()


def el5_a_failed_accept_gap_passes_nothing():
    """EL5 edge: the `accept-gap --point` of an S1 `go on` fails - the refusal is SHOWN (a held question carrying the command's output), no waiver
    row is written, no finding is filed, and nothing is kept as passed."""
    rig = Rig()
    try:
        rig.seam()
        rig.fail["ticket_adapter.py"] = (3, "ticket_adapter: refused: the inventory has changed")
        try:
            rig.answer("go on")
            check("EL5/edge: a failed accept-gap raises", False)
        except story_run.Person as held:
            check_in("EL5/edge: the refusal is shown, in words", "could not be recorded as the pass for the sources, so nothing was passed", held.text)
            check_in("EL5/edge: with the command's own output beside it", "the inventory has changed", held.details)
        check_eq("EL5/edge: no waiver row was written", rig.scripts("waiver.py"), [])
        check_eq("EL5/edge: no finding was filed", rig.scripts("project_decisions.py"), [])
        check_eq("EL5/edge: nothing is kept as passed", rig.driver.state["exit_limit"][D].get("passes", []), [])
    finally:
        rig.done()


def el3_end_to_end_fresh_releases_for_real_and_the_new_session_is_told():
    """EL3 with the REAL controller `release`, `next` and the new `run_role` prompt, on the conductor road (A7): the words file the conductor
    names is the person's ORIGINAL words - the controller's record carries them (`released_by_person`), the relaunch prompt carries the check's
    lines and the person's words, and not the old line "never reached an agent"."""
    from controller import Controller
    from story_run_common import set_control, stub_calls
    live = Live(inventory=False)
    try:
        lines = live.errors()
        check("EL3/e2e: the real gate refuses (outputs missing)", bool(lines) and "missing required output" in lines[0], str(lines))
        try:
            live.quiet(live.driver.exit_limit, "S1", "qa-scout", D, lines, sid="sess-1", why="handoff")
            check("EL3/e2e: the seam asks", False)
        except story_run.Person as person:
            check_eq("EL3/e2e: the question offers fresh", tokens_of(person), ["round", "fresh", "go on", "stop"])
        original = "state/words/orig-words.txt"
        (live.task_root / "state" / "words").mkdir(parents=True, exist_ok=True)
        (live.task_root / original).write_text("start the scout again, and read the comments twice", encoding="utf-8")
        (live.task_root / "state/words/token.txt").write_text("fresh", encoding="utf-8")
        live.driver._answer = {"text": "fresh", "rel": "state/words/token.txt"}
        asked = {"kind": "exit_limit", "words_file": original,
                 "options": [{"token": t, "move": m} for t, m in (("round", "site_door"), ("fresh", "site_door"), ("go on", "go_on_as_is"), ("stop", "stop_here"))]}
        check("EL3/A7/e2e: `fresh` chosen from the conductor's options of this kind is the one executor's",
              live.quiet(live.driver.take_seam_answer, "fresh", asked, "q", "S1", D) is True)
        record = live.dispatch()
        check_eq("EL3/e2e: the REAL release freed the dispatch, with the person's ORIGINAL words (not the token file)",
                 (record.get("status"), record.get("released_by_person")), ("released_by_person", "start the scout again, and read the comments twice"))
        action = Controller(live.task_root).next_action()
        check_eq("EL3/e2e: `next` gives a relaunch of THIS dispatch", (action.get("action"), (action.get("dispatch_request") or {}).get("relaunch_of")),
                 ("relaunch", D))
        set_control(live.root, {"roles": {"qa-scout": {"files": {"work/context-manifest.json": live.manifest, "work/context-bundle.json": "{}"},
                                                       "result": live.digest}}})
        live.quiet(live.driver.dispatch_action, action)
        prompts = [c["prompt"] for c in stub_calls(live.root) if c["kind"] == "role"]
        check_eq("EL3/e2e: the role was started once", len(prompts), 1)
        check_in("EL3/e2e: the new session is told what the check named", "is missing required output", prompts[0])
        check_in("EL3/A7/e2e: and the person's ORIGINAL words", "read the comments twice", prompts[0])
        check_not_in("EL3/e2e: not the old line", "never reached an agent", prompts[0])
        check_in("EL3/e2e: and what stays on disk for it to read", "stays on disk for you to read", prompts[0])
    finally:
        live.done()


def el3_a_release_the_controller_refuses_is_shown_and_nothing_relaunches():
    """EL3 edge: the controller's `release` of a `fresh` fails - the refusal is SHOWN (held, the command's output beside it), `fresh_line` is NOT
    written (so no relaunch is told anything), and the controller was asked once (the release), never to dispatch anything."""
    rig = Rig()
    try:
        rig.seam()
        rig.fail["controller.py"] = (3, "controller: refused: S1-qa-scout-1 is accepted, which holds nothing back")
        try:
            rig.answer("fresh", original="state/words/orig.txt")
            check("EL3/edge: a refused release raises", False)
        except story_run.Person as held:
            check_in("EL3/edge: the refusal is shown, in words", "could not set the work aside, so nothing was changed", held.text)
            check_in("EL3/edge: with the controller's own words beside it", "holds nothing back", held.details)
        check_eq("EL3/edge: no fresh line, so no relaunch is told anything", rig.driver.state["exit_limit"][D].get("fresh_line"), None)
        check_eq("EL3/edge: the controller was asked once (the release) and never to dispatch", [a[a.index("--operation") + 1] for a in rig.scripts("controller.py")],
                 ["release"])
    finally:
        rig.done()


def el2_el6_at_an_e8_finish_refusal():
    """A2: the paid round is spent INSIDE the seam - also at an E8 finish refusal (`resume_on_refusal`; the finish's exit 3 reaches only this site):
    `round` is granted by the answer, spent BEFORE the call, the check's lines and the person's words go in whole, the loop goes on ("continue"),
    and the same set comes back asked again; `go on` passes the lines that REACHED the seam (the refusal's own), never a re-read."""
    rig = Rig(stage="S4", role="qa-case-designer")
    try:
        rig.driver.stand_probe = lambda dispatch: None
        found = ["story_step: left none of the outputs", "story_step: case TC-9 has no oracle"]
        refusal = story_run.Refusal(f"story_step finish {D} (exit 3):\n" + "\n".join(found), dispatch=D, findings=found)
        rig.driver.note_resume(D, "sess-1", story_run.finding_key(found), "refusal")

        def entry():
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    return rig.driver.resume_on_refusal(refusal, "S4", D)
            except story_run.Person as person:
                return person

        person = entry()
        check_eq("EL2/E8: the refusal that survived its resume is the ONE seam's question", (person.kind, tokens_of(person)), ("exit_limit", ["round", "fresh", "go on", "stop"]))
        check("EL2/E8: `round` is a token", rig.answer("round", original="state/words/orig.txt") is True)
        key = rig.driver.state["exit_limit"][D]["key"]
        check_eq("EL2/E8: granted 1, spent 0 until the next entry", tuple(rig.driver.state["exit_limit"][D]["rounds"][key][k] for k in ("granted", "spent")), (1, 0))
        check_eq("EL2/E8: the next entry spends the round and the loop goes on", entry(), "continue")
        check_eq("EL2/E8: `spent` was on disk BEFORE the call", rig.spent_at_call[0][key]["spent"], 1)
        check_eq("EL2/E8: the call was a resume of the role (one)", rig.kinds, ["role"])
        for line in found:
            check_in("EL2/E8: the check's line goes in whole: " + line[:30], line, rig.prompts[0])
        check_in("EL2/E8: and the person's ORIGINAL words, whole", "do it once more, and check the body too", rig.prompts[0])
        again = entry()
        check_in("EL2/E8: the same set again is asked again, with the paid count", "once more after your answer", again.text)
        check_eq("EL2/E8: no second round without an answer of its own", len(rig.prompts), 1)
        check("EL6/E8: `go on` is a token", rig.answer("go on") is True)
        check_eq("EL6/E8: one waiver row per line of the REFUSAL, the block = the whole line", [a[a.index("--block") + 1] for a in rig.scripts("waiver.py")], found)
    finally:
        rig.done()


def a7_the_conductor_road_carries_the_original_words():
    """A7: on the conductor road every token of kind `exit_limit` reaches `_answer_exit_limit`, and `round` / `fresh` / `go on` carry
    `asked.words_file` - the person's original words - never the token's own file; `stop` is held."""
    rig = Rig()
    try:
        rig.seam()
        original = "state/words/orig.txt"
        (rig.task_root / "state" / "words").mkdir(parents=True, exist_ok=True)
        (rig.task_root / original).write_text("do it once more, and check the body too", encoding="utf-8")
        (rig.task_root / "state/words/token.txt").write_text("round", encoding="utf-8")
        asked = {"kind": "exit_limit", "words_file": original,
                 "options": [{"token": t, "move": m} for t, m in (("round", "site_door"), ("fresh", "site_door"), ("go on", "go_on_as_is"), ("stop", "stop_here"))]}

        def road(token):
            rig.driver._answer = {"text": token, "rel": "state/words/token.txt"}
            with contextlib.redirect_stdout(io.StringIO()):
                return rig.driver.take_seam_answer(token, asked, "q", "S1", D)

        check("A7: `round` on the conductor road is a token", road("round") is True)
        key = rig.driver.state["exit_limit"][D]["key"]
        check_eq("A7: the round carries the ORIGINAL words file, not the token's", rig.driver.state["exit_limit"][D]["rounds"][key]["words_file"], original)
        check("A7: `fresh` on the conductor road is a token", road("fresh") is True)
        release = rig.scripts("controller.py")[0]
        check("A7: the release carries the original words file", release[release.index("--words-file") + 1].replace("\\", "/").endswith(original), str(release))
        check("A7: `go on` on the conductor road is a token", road("go on") is True)
        check_eq("A7: and every pass carries the original words file",
                 {a[a.index("--words-file") + 1].replace("\\", "/").endswith(original) for a in rig.scripts("waiver.py")}, {True})
        try:
            road("stop")
            check("A7: `stop` is held", False)
        except story_run.Person as held:
            check_in("A7: `stop` is held with the stop sentence", "You said to stop", held.text)
    finally:
        rig.done()


def el10_a_token_through_take_answer_is_a_seam_token():
    """EL10 through `take_answer` (not the executor alone): a token of the question is a seam token - the audit row of the answer names it, and
    no word of it is filed for a role (`pending_words`); other words are NOT a token - the audit row names none and the conductor reads them once.
    (Reality: `_file_words` files nothing for kind `exit_limit` either way; `seam_token` is observable in the audit row's `token`.)"""
    rig = Rig()
    try:
        d = rig.driver
        rig.seam()
        answers = rig.task_root / "state" / "driver-answers.jsonl"

        def take(words):
            path = rig.task_root / "state" / "words" / "taken.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(words, encoding="utf-8")
            d.state["asked"] = {"kind": "exit_limit", "stage": "S1", "dispatch": D}
            with contextlib.redirect_stdout(io.StringIO()):
                d.take_answer(path)
            return [json.loads(x) for x in answers.read_text(encoding="utf-8").splitlines()][-1]

        row = take("round")
        check_eq("EL10: a token answer's audit row names the token (the answer was a seam token)", (row["token"], row["kind"], row["dispatch"]), ("round", "exit_limit", D))
        check_eq("EL10: and files no pending words for the role", d.state["pending_words"].get(D), None)
        row = take("could you give it one more try, with this note")
        check_eq("EL10: other words are not a token: no token in the row, the conductor read them once",
                 (row["token"], len([c for c in rig.calls if c == ("conductor",)])), ("", 1))
        check_eq("EL10: and they file no pending words for the role either", d.state["pending_words"].get(D), None)
    finally:
        rig.done()


def a12_resume_role_spends_the_pending_words_before_the_handoff_judges():
    """A12: `resume_role` pops `pending_words` right after the resumed result is saved - before `handoff` judges it, so a refusal of that handoff
    never re-sends the words on the next entry (on disk too, not only in memory)."""
    rig = Rig()
    try:
        d = rig.driver
        d.state["pending_words"][D] = "the person's old words"
        d.save_state()
        seen = {}

        def handoff(role, stage, dispatch, result):
            disk = json.loads((rig.task_root / "state" / "driver-state.json").read_text(encoding="utf-8"))
            seen.update(memory=D in d.state["pending_words"], disk=D in (disk.get("pending_words") or {}),
                        saved=(rig.task_root / "state" / "driver-runs" / f"{dispatch}.json").is_file())
            raise story_run.Refusal(f"exit gate for {dispatch} ({role}, {stage}): still wrong", dispatch=dispatch, findings=["still wrong"])

        d.handoff = handoff
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                d.resume_role("S1", "qa-scout", D, "the person's answer")
            check("A12: the refusal of the resumed handoff comes out", False)
        except story_run.Refusal:
            pass
        check_eq("A12: when the handoff judges the result, the words are already spent (memory and disk) and the result is saved",
                 seen, {"memory": False, "disk": False, "saved": True})
        check_in("A12: the role was resumed with the person's answer", "the person's answer", rig.prompts[0])
        d.state["pending_words"][D] = "words that were never sent"
        d.state["sessions"][D] = ""
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                d.resume_role("S1", "qa-scout", D, "again")
        except story_run.Refusal as refusal:
            check_in("A12 control: with no session known nothing is sent", "no session is known", refusal.text)
        check_eq("A12 control: so the words stay", d.state["pending_words"].get(D), "words that were never sent")
    finally:
        rig.done()


def risk4_a_go_on_outside_the_offered_list_is_bounded_by_the_conductor_cap():
    """Risk 4 of the first hand-back, re-pinned by t-781 M1: a conductor-road `go on` that the offered list does not carry (a handover-form line
    removed it) goes back to the SITE's question (`unread` with the site's doors and `again`). The bound is the conductor's per-boundary cap:
    with the REAL `Driver.conductor`, the first CAP answers each call it once, the answers AT the cap make no call and end with the SITE's
    question (`round` / `fresh` / `stop` - never the generic `retry` / `go on`, nothing unexecuted) and a defect that names the cap - and every
    answer ends in a question (no loop, nothing passed)."""
    import types
    rig = Rig(stage="S4", role="qa-case-designer")
    try:
        d = rig.driver
        d.form_errors = lambda dispatch: ["handover form x.yaml - scope: missing"]
        person = rig.seam(["case_gate: TC-1 has no oracle", "handover form x.yaml - scope: missing"])
        check_eq("risk 4: a handover-form line removes `go on` from the offer", tokens_of(person), ["round", "fresh", "stop"])
        asked = {"kind": "exit_limit", "words_file": "state/words/orig.txt", "options": [{"token": t, "move": m} for t, m in
                                                                                       (("round", "site_door"), ("fresh", "site_door"), ("stop", "stop_here"))]}
        d.conductor = types.MethodType(story_run.Driver.conductor, d)
        d.no_move_facts = types.MethodType(story_run.Driver.no_move_facts, d)
        d.defects = []
        d.no_move_defect = lambda note, ref="": d.defects.append(note)
        d.boundary = f"S4:{D}:answer"
        cap = story_run.CONDUCTOR_CALLS_PER_BOUNDARY
        shown, called = [], []
        for turn in range(cap + 2):
            before = rig.kinds.count("conductor")
            d._answer = {"text": "go on", "rel": "state/words/token.txt"}
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    d.take_seam_answer("go on", asked, "q", "S4", D)
                shown.append(None)
            except story_run.Person as raised:
                shown.append(raised)
            called.append(rig.kinds.count("conductor") - before)
        check_eq("risk 4: the conductor is called once per answer up to the cap and never beyond it", called, [1] * cap + [0] * 2)
        check("risk 4: every answer ended in a question for the person (no loop, no silent pass)", all(isinstance(p, story_run.Person) for p in shown))
        # t-781 M1: the floor is the SITE's question - only the tokens the site offered, nothing unexecuted (FR-9), no `go on` it withdrew (A1)
        check_eq("risk 4 AT the cap (M1): the SITE's question again - round / fresh / stop, the tokens the site offered",
                 (shown[-1].kind, tokens_of(shown[-1])), ("exit_limit", ["round", "fresh", "stop"]))
        for token in ("retry", "restart", "go on"):
            check_not_in(f"risk 4 AT the cap (M1): `{token}` is not offered - the site has no executor for it, or withdrew it", f"`{token}` —", shown[-1].text)
        check_in("risk 4 AT the cap (M1): and it says that the answer was not read", d.unread_lead("go on"), shown[-1].text)
        check("risk 4 AT the cap: and the defect names the conductor cap", any("the conductor cap was reached" in n for n in d.defects), str(d.defects))
        check_eq("risk 4: nothing was passed by the unread `go on`", (rig.scripts("waiver.py"), rig.scripts("ticket_adapter.py")), ([], []))
    finally:
        rig.done()


# --- the fix round (t-781, under the merge critic t-778): M1, m2-m7 ---------------------------------------------------------------------------


def _moves_section(prompt):
    """The conductor prompt's list of the moves open here (between its headings): the conductor may offer ONLY these."""
    return prompt.split("## Moves open here", 1)[1].split("## Answers this question already takes", 1)[0]


def m1_words_outside_the_conductors_options_go_back_to_the_sites_question():
    """t-781 M1: on the conductor road words that are not an offered token - a `go on` the site withdrew, any other words - are read by the
    SITE's reader before the generic `by_token` test: they go back to the site's question (`doors` = the tokens the site offered, `again`),
    and the conductor's prompt lists no move this kind cannot execute (`release_and_restart`, `retry`) - FR-9; a `go on` the site did not
    offer is not offered back (A1). With the REAL `Driver.conductor`."""
    import types
    rig = Rig(stage="S4", role="qa-case-designer")
    try:
        d = rig.driver
        d.form_errors = lambda dispatch: ["handover form x.yaml - scope: missing"]
        rig.seam(["case_gate: TC-1 has no oracle", "handover form x.yaml - scope: missing"])
        asked = {"kind": "exit_limit", "words_file": "state/words/orig.txt",
                 "options": [{"token": t, "move": m} for t, m in (("round", "site_door"), ("fresh", "site_door"), ("restart", "release_and_restart"),
                                                                  ("retry", "person_does"), ("stop", "stop_here"))]}
        d.conductor = types.MethodType(story_run.Driver.conductor, d)
        d.no_move_facts = types.MethodType(story_run.Driver.no_move_facts, d)
        d.no_move_defect = lambda note, ref="": None
        d.boundary = f"S4:{D}:answer"
        for word in ("go on", "please think about it once more", "restart"):
            d.conductor_calls = {}
            before = len(rig.prompts)
            d._answer = {"text": word, "rel": "state/words/token.txt"}
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    d.take_seam_answer(word, asked, "q", "S4", D)
                shown = None
            except story_run.Person as raised:
                shown = raised
            check(f"M1: `{word}` ends in a question for the person", shown is not None)
            check_eq(f"M1: `{word}` - the SITE's question again: round / fresh / stop, nothing unexecuted, no withdrawn `go on`",
                     (shown.kind, tokens_of(shown)), ("exit_limit", ["round", "fresh", "stop"]))
            check_eq(f"M1: `{word}` - one conductor call", len(rig.prompts) - before, 1)
            moves = _moves_section(rig.prompts[-1])
            check_in(f"M1: `{word}` - the conductor's open moves hold `stop_here` (control: the section was read)", "stop_here", moves)
            for move in ("release_and_restart", "person_does", "go_on_as_is"):
                check_not_in(f"M1: `{word}` - the conductor is not offered `{move}`", move, moves)
            check_in(f"M1: `{word}` - the conductor is told the site's own answers", "`fresh`", rig.prompts[-1])
        check_eq("M1: nothing was executed for words nobody read", [c for c in rig.calls if len(c) == 2 and c[0] in ("controller.py", "waiver.py", "ticket_adapter.py")], [])
    finally:
        rig.done()


def m2_an_error_with_no_words_keeps_the_persons_words():
    """t-781 m2 (A12 as intended): `resume_role` spends `pending_words` only when the resume returned a result that CARRIES words. An error with
    no words answered nothing - `handoff` refuses it and the person's words stay (memory and disk) for the next entry; a result with words AND an
    error did answer them (the role spoke), so they are spent before `handoff` judges it."""
    rig = Rig()
    try:
        d = rig.driver
        reply = {}
        d.run_claude = lambda kind, prompt, **kw: dict(reply)

        def disk():
            return (json.loads((rig.task_root / "state" / "driver-state.json").read_text(encoding="utf-8")).get("pending_words") or {}).get(D)

        def resume():
            d.state["pending_words"][D] = "the person's words"
            d.save_state()
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    d.resume_role("S1", "qa-scout", D, "the person's answer")
            except story_run.Refusal as refusal:
                return refusal
            return None

        reply.update(session_id="sess-1", result="", is_error=True, stderr="boom", exit_code=1, total_cost_usd=0.0, num_turns=0)
        refusal = resume()
        check("m2: an error and no words: `handoff` refuses it", refusal is not None and "failed" in refusal.text, str(refusal))
        check_eq("m2: and the person's words STAY (memory and disk)", (d.state["pending_words"].get(D), disk()), ("the person's words", "the person's words"))
        reply.update(result="partial words from the role")
        seen = {}

        def handoff(role, stage, dispatch, result):
            seen["memory"], seen["disk"] = D in d.state["pending_words"], disk() is not None
            raise story_run.Refusal("still wrong", dispatch=dispatch, findings=["still wrong"])

        d.handoff = handoff
        resume()
        check_eq("m2: words AND an error: the role answered, so they are spent before `handoff` judges it", seen, {"memory": False, "disk": False})
    finally:
        rig.done()


def m3_the_revoke_is_the_drivers_act_in_the_drivers_words():
    """t-781 m3: the sweep takes a `go on` pass back with a words file the DRIVER made (the gate-A revoke precedent: `stand_gaps.words_args`),
    not the person's grant words - which would read as the person taking their own pass back."""
    rig = Rig(stage="S4", role="qa-case-designer")
    try:
        lines = ["case_gate: TC-1 has no oracle"]
        rig.seam(lines)
        grant = "state/words/grant.txt"
        rig.answer("go on", original=grant)         # the person's grant words: "do it once more, and check the body too"
        rig.driver.controller_state = lambda: {"dispatches": {D: {"status": "accepted"}}}
        rig.driver.revoke_passes_of_dead()
        revoke = [a for a in rig.scripts("waiver.py") if "--revoke" in a]
        check_eq("m3: one revoke for the one row", len(revoke), 1)
        used = Path(revoke[0][revoke[0].index("--words-file") + 1])
        check("m3: the words file of the revoke is NOT the grant's", used != rig.task_root / grant and "driver-revoke-" in used.name, str(used))
        said = used.read_text(encoding="utf-8")
        check_in("m3: it says which dispatch ended and how", f"{D} ended (accepted)", said)
        check_in("m3: and that the DRIVER takes the pass back", "the driver takes the pass over the exit gate back", said)
        check_not_in("m3: not the person's grant words", "do it once more", said)
        grants = [a[a.index("--words-file") + 1].replace("\\", "/") for a in rig.scripts("waiver.py") if "--revoke" not in a]
        check("m3 control: the grant used the person's file", bool(grants) and all(g.endswith(grant) for g in grants), str(grants))
        check_eq("m3: the row is gone from the state", rig.driver.state["exit_limit"][D]["passes"], [])
    finally:
        rig.done()


def m4_a_dispatch_released_by_another_road_is_swept_at_the_top_of_handoff():
    """t-781 m4: the conductor's `restart` releases D with no call of the sweep; the relaunch D2's `handoff` reads the exit gate - the sweep
    runs FIRST, so D's `go on` rows do not pass D2's same lines. A live dispatch's rows stand, and with nothing dead the sweep writes nothing."""
    d2 = "S4-qa-case-designer-2"
    rig = Rig(stage="S4", role="qa-case-designer")
    try:
        d = rig.driver
        lines = ["case_gate: TC-1 has no oracle"]
        rig.seam(lines)
        rig.answer("go on")
        check_eq("m4: `go on` wrote a row for D", [p["block"] for p in d.state["exit_limit"][D]["passes"]], lines)
        result = {"is_error": False, "result": "digest", "session_id": "sess-2", "exit_code": 0, "stderr": ""}
        d.exit_errors = lambda role, digest, dispatch=None: rig.calls.append(("exit_errors",)) or []
        state_file = rig.task_root / "state" / "driver-state.json"
        d.controller_state = lambda: {"dispatches": {D: {"status": "running"}, d2: {"status": "running"}}}
        before = state_file.read_bytes()
        d.handoff("qa-case-designer", "S4", d2, result)
        check_eq("m4: D is live: its rows stand, nothing is revoked, the state file is not rewritten",
                 ([a for a in rig.scripts("waiver.py") if "--revoke" in a], state_file.read_bytes() == before), ([], True))
        d.controller_state = lambda: {"dispatches": {D: {"status": "released_by_person"}, d2: {"status": "running"}}}
        rig.calls.append(("mark",))
        d.handoff("qa-case-designer", "S4", d2, result)
        after = rig.calls[rig.calls.index(("mark",)):]
        names = [c[0] for c in after]
        revoked = [a[a.index("--block") + 1] for s, a in (c for c in after if len(c) == 2) if s == "waiver.py" and "--revoke" in a]
        check_eq("m4: D was released by `restart` alone: its row is revoked by D2's handoff", revoked, lines)
        check("m4: and BEFORE the exit gate of D2 reads the rows", "waiver.py" in names and names.index("waiver.py") < names.index("exit_errors"), str(names))
        check_eq("m4: the rows are gone from the state", d.state["exit_limit"][D]["passes"], [])
        rig.calls.append(("mark2",))
        d.handoff("qa-case-designer", "S4", d2, result)
        check_eq("m4 edge: nothing left to sweep: no waiver call at all", [c for c in rig.calls[rig.calls.index(("mark2",)):] if len(c) == 2 and c[0] == "waiver.py"], [])
    finally:
        rig.done()


def m5_the_paid_rounds_text_names_the_real_refusal():
    """t-781 m5: the instruction of a paid `round` names the refusal that reached the seam - the exit gate's for a handoff, the factory's
    closing of the dispatch for a finish refusal (E8/E9), the structured artifact's for E11 - and never calls the other two "the exit gate"."""
    exit_gate = "The exit gate refused your handoff"
    heads = {"handoff": exit_gate + ":", "refusal": "The factory refused to close your dispatch:",
             "structured": "The factory refused the structured artifact you handed over:"}
    for why, head in heads.items():
        rig = Rig()
        try:
            rig.seam(why=why)
            rig.answer("round", original="state/words/orig.txt")
            check_eq(f"m5/{why}: the next entry spends the round", rig.seam(why=why), None)
            check_in(f"m5/{why}: the head names the real refusal", head, rig.prompts[0])
            check_in(f"m5/{why}: and the check's lines follow it, whole", LINES[1], rig.prompts[0])
            if why != "handoff":
                check_not_in(f"m5/{why}: it is NOT told that the exit gate refused its handoff", exit_gate, rig.prompts[0])
        finally:
            rig.done()


def m6_one_helper_writes_the_pass_or_holds_it():
    """t-781 m6 (A13): the d2 sites go through the ONE `pass_block`; a refusal - or a `waiver.py` that fails altogether - is held with the
    command's output beside it and NOTHING is passed (no row kept, no finding)."""
    import inspect
    rig = Rig()
    try:
        d = rig.driver
        d.pass_block("S1", "the line", "state/words/w.txt", "Lead sentence.")
        call = rig.scripts("waiver.py")[0]
        check_eq("m6: one row: the stage, the block, the words by file (absolute)",
                 (call[call.index("--stage") + 1], call[call.index("--block") + 1], call[call.index("--words-file") + 1].replace("\\", "/").endswith("state/words/w.txt")),
                 ("S1", "the line", True))
        rig.fail["waiver.py"] = (1, "waiver: refused: no such block")
        try:
            d.pass_block("S1", "the line", "state/words/w.txt", "Lead sentence.")
            check("m6: a refused pass is held", False)
        except story_run.Person as held:
            check_in("m6: the lead the caller gave", "Lead sentence.", held.text)
            check_in("m6: with the command's own output beside it", "no such block", held.details)
        rig.seam()
        try:
            rig.answer("go on")
            check("m6: `go on` over a failing waiver is held", False)
        except story_run.Person as held:
            check_in("m6: the exit-limit site says nothing was passed", "so nothing was passed", held.text)
        check_eq("m6: and keeps no row, files no finding", (rig.driver.state["exit_limit"][D].get("passes", []), rig.scripts("project_decisions.py")), ([], []))
        rig.fail.clear()
        asked = {"kind": "s0", "options": [{"token": "go on", "move": "go_on_as_is"}], "block": "BLK-1"}
        d._answer = {"text": "go on", "rel": "state/words/a.txt"}
        n = len(rig.scripts("waiver.py"))
        with contextlib.redirect_stdout(io.StringIO()):
            d.take_seam_answer("go on", asked, "q", "S1", D)
        block = rig.scripts("waiver.py")[n]
        check_eq("m6: the seam's own `go on` with a block passes it through the helper too", block[block.index("--block") + 1], "BLK-1")
        # since C2-6 `take_seam_answer` only reads the token and hands the move to `seam_chosen`, which holds the pass (676c2b50)
        for fn in (story_run.Driver._exit_go_on, story_run.Driver.seam_chosen):
            source = inspect.getsource(fn)
            check_in(f"m6: {fn.__name__} writes through the helper", "self.pass_block(", source)
            check_not_in("m6: and has no inline waiver call of its own", '"waiver.py"', source)
    finally:
        rig.done()


def m7_the_seams_offer_is_the_data_rows_answers():
    """t-781 m7: the answers the seam offers are the answers of the data row `exit.resume_limit`, in its order (the unused Driver constant is
    gone: the pin reads the data and the seam's own offer)."""
    import no_move as NM
    rig = Rig()
    try:
        rig.seam()
        check("m7: no Driver.EXIT_LIMIT_ANSWERS constant is left", not hasattr(story_run.Driver, "EXIT_LIMIT_ANSWERS"))
        check_eq("m7: the offer the seam keeps is the data row's answers, in order", rig.driver.state["exit_limit"][D]["ask"]["offer"],
                 [row["answer"] for row in NM.load_question_prices()["exit.resume_limit"]])
    finally:
        rig.done()


def main():
    for scenario in (el1_asked_with_four_priced_answers, el2_a_round_is_spent_inside_the_seam_before_the_call,
                     el3_fresh_releases_and_the_relaunch_reason_outranks_the_packet, el4_an_absent_option_is_said,
                     el5_go_on_at_s1_closes_the_sources_work_first, el6_go_on_passes_whole_lines_files_the_finding_and_the_sweep_revokes,
                     el7_stop_is_held_and_el10_words_go_to_the_conductor, el14_the_cut_of_the_source_list_and_a_broken_inventory,
                     el5_end_to_end_go_on_at_s1_closes_the_sources_and_the_real_controller_accepts, el5_a_failed_accept_gap_passes_nothing,
                     el3_end_to_end_fresh_releases_for_real_and_the_new_session_is_told, el3_a_release_the_controller_refuses_is_shown_and_nothing_relaunches,
                     el2_el6_at_an_e8_finish_refusal, a7_the_conductor_road_carries_the_original_words, el10_a_token_through_take_answer_is_a_seam_token,
                     a12_resume_role_spends_the_pending_words_before_the_handoff_judges, risk4_a_go_on_outside_the_offered_list_is_bounded_by_the_conductor_cap,
                     m1_words_outside_the_conductors_options_go_back_to_the_sites_question, m2_an_error_with_no_words_keeps_the_persons_words,
                     m3_the_revoke_is_the_drivers_act_in_the_drivers_words, m4_a_dispatch_released_by_another_road_is_swept_at_the_top_of_handoff,
                     m5_the_paid_rounds_text_names_the_real_refusal, m6_one_helper_writes_the_pass_or_holds_it, m7_the_seams_offer_is_the_data_rows_answers):
        scenario()
    finish("story run exit limit")


if __name__ == "__main__":
    main()
