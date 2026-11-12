#!/usr/bin/env python3
"""The driver's refusals, with `claude` replaced by a stub (STORY_RUN_CLAUDE) and a temp project.

Nothing here reaches the network or a real model. What is proved:
  * a stage round trip and the gate: start -> role -> bind -> handoff check -> finish, the question file
    and exit 3, the person's answer recorded by code, and a refusal the known table handles never
    reaching the conductor while an unknown one goes to it;
  * the known-refusal table, its markers and the dispatch field a refusal carries;
  * the judge's reading of the person's words, and how a source gap is asked and closed;
  * every action the controller can return has a move on the driver's side;
  * an active sequential dispatch is a known refusal the driver answers itself;
  * the stage in front of a gate that `stage_done` refuses to record (t-211 F0, mutation M11) is gone over by
    the driver itself, and only while the controller holds that stage `completed`.
The shared scaffolding lives in `story_run_common.py`.
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
from story_run_common import (  # noqa: E402
    GOOD_MANIFEST,
    SCOUT_DIGEST,
    d2_conductor_calls,
    d2_pipeline,
    driver_for,
    eq,
    jsonl,
    run_driver,
    run_scenarios,
    seam_control,
    seed,
    set_control,
    stub_calls,
)


def recording_stub(result=True, calls=None):
    """A stand-in for `Driver.record_by_code` that takes ANY call (`*args, **kwargs`) and returns `result`: a signature the real
    method grows (C2-7 added `apply_words`) never breaks the test or silently drops an argument (FR-31, C4-14). The call is kept
    in `calls` (when given) as `{kind, stage, words, <the keywords given>}`."""
    def fake(*args, **kwargs):
        if calls is not None:
            calls.append({**dict(zip(("kind", "stage", "words"), args)), **kwargs})
        return result
    return fake


def refusal_round_trip_gate_and_routing() -> None:
    task = "QA-9"
    root, task_root, env = seed(task)
    try:
        out = run_driver(root, env, "--task", task, "--dry-run")
        check_eq("dry-run on a seeded project exits 0", out.returncode, 0)
        check_in("prints where", '"action": "prepare_stage", "stage": "S1"', out.stdout)
        check_in("and the stage it would start", "story_step start S1 qa-scout", out.stdout)
        check_in("and the claude command shape", "--agent qa-factory:<role>", out.stdout)
        check_eq("dry-run calls no stub", stub_calls(root), [])
        check("dry-run registers no dispatch", "S1-qa-scout-1" not in json.dumps(
            json.loads((task_root / "state/controller.json").read_text(encoding="utf-8")).get("dispatches", {})))

        # --- the stage round trip -----------------------------------------------------------
        set_control(root, {"roles": {"qa-scout": {
            "files": {"work/context-manifest.json": json.dumps(GOOD_MANIFEST).replace("{task}", task),
                      "work/context-bundle.json": "{}"},
            "result": SCOUT_DIGEST.replace("{task}", task)}}})
        out = run_driver(root, env, "--task", task, "--max-boundaries", "1")
        eq("one boundary runs and pauses with exit 0", out.returncode, 0, out.stdout[-1500:] + out.stderr[-800:])
        pipeline = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))
        check_eq("S1 is done", pipeline["stages"].get("S1", {}).get("status"), "done")
        check_eq("bind wrote the session id as the agent id", pipeline["stages"]["S1"].get("agent_id"), "sess-S1-qa-scout-1")
        calls = stub_calls(root)
        check_eq("exactly one claude -p for the role", [c["kind"] for c in calls], ["role"])
        check_in("the role prompt is the start block", "You are qa-scout. Ticket: QA-9. Dispatch: S1-qa-scout-1.", calls[0]["prompt"])
        check_in("plus the scout's launch lines", "Launch flags: none", calls[0]["prompt"])
        check_in("plus the handoff form", "· ok|concerns|halt|impossible", calls[0]["prompt"])
        check_in("the role is named to claude", "qa-factory:qa-scout", " ".join(calls[0]["argv"]))
        check_in("the tools are the role tools", "Bash,Read,Write,Edit,MultiEdit,Glob,Grep", " ".join(calls[0]["argv"]))
        check_eq("the role's cwd is the project root", Path(calls[0]["cwd"]).resolve(), root.resolve())
        system = Path(calls[0]["sysfile"])
        check("the rule layer travels as the appended system prompt", system.is_file() and "Your factory rules" in system.read_text(encoding="utf-8"))
        check_in("with the resolved task packet", "Resolved task packet", system.read_text(encoding="utf-8"))
        runs = jsonl(task_root / "state/driver-runs.jsonl")
        check_eq("driver-runs.jsonl has the one role line", len(runs), 1)
        check_eq("with the session id", runs[0].get("session_id"), "sess-S1-qa-scout-1")
        check_eq("the cost", runs[0].get("total_cost_usd"), 0.0123)
        check_eq("the kind, role and dispatch", (runs[0]["kind"], runs[0]["role"], runs[0]["dispatch"]), ("role", "qa-scout", "S1-qa-scout-1"))
        check("the saved result is kept as done", (task_root / "state/driver-runs/S1-qa-scout-1.done.json").is_file())
        check_eq("no refusal, no conductor line", jsonl(task_root / "state/conductor.jsonl"), [])
        out = run_driver(root, env, "--task", task, "--dry-run")
        check_in("the next dry-run is at S2", '"stage": "S2"', out.stdout)

        # --- the gate: a question file and exit 3 ---------------------------------------------
        import story_run
        driver = driver_for(root, env, task)
        driver.where = lambda: {"action": "await_gate", "gate": "A", "revision": 7}
        # t-211: the gate-entry repair rehearses first, and this half-built story's real rehearsal holds
        # factory_fixable findings (no plan rows yet) that would send a round to the conductor. What is proved
        # here is the gate's question file, so the rehearsal is one that finds nothing (the step is test_story_run_gate_repair.py's).
        driver.rehearse = lambda gate: {"findings": []}
        code = driver.run()
        check_eq("await_gate exits 3", code, 3)
        question = task_root / "state/driver-question.md"
        check("the question file exists", question.is_file())
        qtext = question.read_text(encoding="utf-8")
        check_in("its kind is gate_A", "kind: gate_A", qtext)
        check_in("it carries the gate brief", "Gate A", qtext)
        check_in("and how to answer", "--answer", qtext)
        check_eq("driver-state remembers the open question",
                 json.loads((task_root / "state/driver-state.json").read_text(encoding="utf-8"))["asked"]["kind"], "gate_A")

        # --- the answer goes through the conductor ------------------------------------------
        before = len(stub_calls(root))
        answer = root / "answer-a.md"
        answer.write_text("Gate A: approved. Dirty tree: go on.", encoding="utf-8")
        set_control(root, {"conductor": {"action": "continue", "did": "gate-decision recorded", "text": "Recorded."}})
        driver = driver_for(root, env, task, answer=str(answer))
        driver.where = lambda: {"action": "stop", "reason": "test stop"}
        code = driver.run()
        check_eq("the answered loop goes on and stops on `stop`", code, 0)
        calls = stub_calls(root)[before:]
        check_eq("a gate decision the controller refuses still reaches the conductor",
                 [c["kind"] for c in calls], ["conductor"])
        check_in("the conductor got the person's words", "Gate A: approved. Dirty tree: go on.", calls[0]["prompt"])
        check_in("and the question kind", "kind `gate_A`", calls[0]["prompt"])
        check_in("conductor.md is its system prompt", "conductor.md", calls[0]["sysfile"])
        check_in("with the conductor tools", "Bash,Read,Grep", " ".join(calls[0]["argv"]))
        check_in("and a turn cap", "--max-turns", " ".join(calls[0]["argv"]))
        conductor = jsonl(task_root / "state/conductor.jsonl")
        check_eq("conductor.jsonl records the recording call", (conductor[-1]["action"], conductor[-1]["words"]), ("continue", True))

        check("the question is kept as answered", (task_root / "state/driver-question.answered.md").is_file() and not question.exists())
        answers = jsonl(task_root / "state/driver-answers.jsonl")
        check_eq("driver-answers.jsonl carries the words", answers[-1]["words"], "Gate A: approved. Dirty tree: go on.")
        # And when the decision DOES record, the conductor is not called at all: on
        # TP1-13797 the gate-A answer cost $1.05 of conductor to write down words the driver
        # was already holding, plus a 21-turn `ask_person` that recorded nothing.
        quiet = len(stub_calls(root))
        answer_again = root / "answer-a2.md"
        answer_again.write_text("Gate A: approved again, same words.", encoding="utf-8")
        driver = driver_for(root, env, task, answer=str(answer_again))
        driver.where = lambda: {"action": "stop", "reason": "test stop"}
        (task_root / "state" / "driver-question.md").write_text(
            "# Driver question\nkind: gate_A\nstage: S4\n", encoding="utf-8")
        driver.state["asked"] = {"kind": "gate_A", "stage": "S4", "dispatch": ""}
        driver.save_state()
        driver.record_by_code = recording_stub()
        check_eq("the loop goes on", driver.run(), 0)
        check_eq("a recorded gate decision costs no conductor session",
                 len(stub_calls(root)) - quiet, 0)

        runs = jsonl(task_root / "state/driver-runs.jsonl")
        check_eq("driver-runs.jsonl has the conductor line", runs[-1]["kind"], "conductor")

        # --- a known refusal never reaches the conductor -------------------------------------
        before = len(stub_calls(root))
        driver = driver_for(root, env, task)

        def budget():
            raise story_run.Refusal("stage_done: STORY BUDGET: QA-9 is past its ceiling — 12 dispatches")
        driver.where = budget
        code = driver.run()
        check_eq("STORY BUDGET is the person's: exit 3", code, 3)
        # The refusal is the factory's own vocabulary, so it goes BESIDE the question, in a file
        # the answer block names - never in place of one (references/human-questions.md).
        qtext = question.read_text(encoding="utf-8")
        check_not_in("the question does not paste the refusal", "STORY BUDGET", qtext)
        # C1-1: the question is the seam's, with no paid call: the three standing answers, each with its three price lines
        for token in ("retry", "go on", "stop"):
            check_in(f"it offers `{token}`", f"`{token}` — ", qtext)
        for label in ("the factory:", "you:", "the story:"):
            check_in(f"and every answer has the line `{label}`", label, qtext)
        check_eq("and `asked` carries the three tokens and why", (driver.state["asked"]["offered"], driver.state["asked"]["why"]),
                 (["retry", "go on", "stop"], "refusal"))
        check_in("and names where our own words are", "driver-question-details.md", qtext)
        check_in("which is where the refusal is", "STORY BUDGET",
                 (task_root / "state/driver-question-details.md").read_text(encoding="utf-8"))
        check_in("with kind refusal", "kind: refusal", qtext)
        check_eq("no conductor was called", len(stub_calls(root)), before)
        check_eq("conductor.jsonl names the table row", jsonl(task_root / "state/conductor.jsonl")[-1]["action"], "known:story_budget")

        # --- an unknown refusal goes to the conductor: ask_person, then stop --------------------
        stand_question = "Which stand should I use? Say `retry` when you have started one, or `stop`."
        set_control(root, {"conductor": seam_control(stand_question)})
        driver = driver_for(root, env, task)

        def unknown():
            raise story_run.Refusal("controller: the moon is down and nobody knows why")
        driver.where = unknown
        code = driver.run()
        check_eq("the conductor's ask_person is exit 3", code, 3)
        qtext = question.read_text(encoding="utf-8")
        check_in("the question is the conductor's", "Which stand should I use?", qtext)
        check_in("and every option carries its three price lines (C1-1)", "the factory: nothing runs now\nyou: work of yours", qtext)
        check_eq("and `asked` carries what the seam offered",
                 (driver.state["asked"]["offered"], driver.state["asked"]["why"]), (["retry", "stop"], "refusal"))
        check_in("with kind conductor", "kind: conductor", qtext)
        check_not_in("without our own words pasted under it", "the moon is down", qtext)
        check_in("which are one file away", "driver-question-details.md", qtext)
        check_in("and are there", "the moon is down",
                 (task_root / "state/driver-question-details.md").read_text(encoding="utf-8"))
        last = jsonl(task_root / "state/conductor.jsonl")[-1]
        check_eq("conductor.jsonl records the verdict", (last["action"], last["question"]), ("ask_person", stand_question))
        check_in("the conductor saw the refusal", "the moon is down", stub_calls(root)[-1]["prompt"])
        check_in("and the stand-remedy authorization", "Stand remedy: NOT authorized", stub_calls(root)[-1]["prompt"])
        check_in("and the moves open here", "## Moves open here", stub_calls(root)[-1]["prompt"])
        set_control(root, {"conductor": seam_control("This violates P-00. Say `retry` or `stop`.", action="stop", did="nothing")})
        driver = driver_for(root, env, task)
        driver.where = unknown
        code = driver.run()
        check_eq("the conductor's stop is exit 4", code, 4)
        check_in("and the reason is in the question file", "This violates P-00.", question.read_text(encoding="utf-8"))

        # --- three conductor calls per boundary, then the person -----------------------------
        set_control(root, {"conductor": {"action": "continue", "did": "nothing changed"}})
        driver = driver_for(root, env, task)
        before = len(stub_calls(root))
        driver.where = unknown
        code = driver.run()
        check_eq("a refusal the conductor keeps 'continuing' ends with the person", code, 3)
        check_eq("after at most three conductor calls", len(stub_calls(root)) - before, 3)
    finally:
        harness.cleanup(root)


def refusal_table() -> None:
    # --- the table itself -------------------------------------------------------------------
    import story_run
    check_eq("STORY BUDGET is a known refusal", story_run.match_known("... STORY BUDGET: x ..."), ("story_budget", "ask_person"))
    check_eq("a stale revision is retried", story_run.match_known("StateConflict: expected_revision 4"), ("stale_revision", "retry"))
    check_eq("an unknown text matches nothing", story_run.match_known("the moon is down"), None)
    check_eq("the S1 source review outranks the handoff-form row (the scout's planned stop is a person question)",
             story_run.match_known("exit gate for S1-qa-scout-1 (qa-scout, S1): source-inventory.json: required "
                                   "sources remain pending: SRC-1; source-inventory.json: no person has reviewed "
                                   "the source decisions yet; digest: your final message is not the handoff form"),
             ("s1_review", "s1_review"))
    gap_text = ("exit gate for S1-qa-scout-1 (qa-scout, S1): source-inventory.json: source material unavailable "
                "and not accepted by a person: SRC-606b160f666899cfb29c — show it to the person; digest: your "
                "final message is not the handoff form")
    check_eq("an unaccepted source gap is the person's word by code", story_run.match_known(gap_text), ("s1_gap", "s1_gap"))
    # A word outside a closed list is the role's repair, whatever the wording: the marker routes it
    # and the table row catches it. TP1-13797, 26.09: `unresolved[0].reason: contradiction`
    # (one word from `contradicts_requirement`) reached the conductor and then the person.
    vocab = ("exit gate for S4-qa-case-designer-1 (qa-case-designer, S4): handover form "
             "S4-qa-case-designer-1.yaml - unresolved[0].reason: `contradiction` is not a value of "
             "this field. Write one of: blocked_by_env, contradicts_requirement, handed_to_person")
    check_eq("a closed-list miss is resumed, never asked", story_run.match_known(vocab)[1], "resume_handoff")
    check_eq("the S1 exit gate names its scout dispatch", story_run.Driver.s1_exit_gate(gap_text), "S1-qa-scout-1")
    check_eq("a gate-A text is not an S1 exit gate", story_run.Driver.s1_exit_gate("gate A waits for words"), "")
    check_eq("the conductor's last JSON line is read", story_run.last_json_line('did things\n{"action": "retry", "did": "x"}'),
             {"action": "retry", "did": "x"})
    check_eq("prose without a verdict is no verdict", story_run.last_json_line("no json here"), {})


def refusal_markers() -> None:
    import story_run
    # P6: the marker in the refusal's own text routes it, so a check added anywhere gets its
    # answer from the right party without a row being added to the table above.
    marked = ("manifest_put: obligation id OB-9 is not in the plan. " + story_run.REPAIR_MARKER
              + "; if they have already decided, the orchestrator records it with waiver.py")
    check_eq("a refusal marked as a repair goes back to the role, not to the conductor",
             story_run.match_known(marked), ("marked_repair", "resume_repair"))
    check_eq("and a refusal marked as the person's question goes to the person",
             story_run.match_known("stand_gaps: " + story_run.PERSON_MARKER + " (three options)"),
             ("marked_person", "ask_person"))
    check("the marker outranks the table it precedes",
          story_run.match_known("required key `run_witness` is missing. " + story_run.REPAIR_MARKER)
          == ("marked_repair", "resume_repair"))


def refusal_dispatch_field() -> None:
    import story_run
    # FR-16: an id travels in a field, not in a sentence the same code just wrote. The regex
    # stays for refusals other scripts raise, where the text is all there is.
    own = story_run.Refusal("exit gate for S1-qa-scout-2 (qa-scout, S1): no inventory",
                            dispatch="S1-qa-scout-2")
    check_eq("the driver's own refusal carries the dispatch as a field", own.dispatch,
             "S1-qa-scout-2")
    other = story_run.Refusal("source_preflight: the S1 review is not accepted")
    check_eq("a refusal that knows no id says so", other.dispatch, "")
    check_eq("and the text reader is still there for those",
             story_run.Driver.s1_exit_gate(own.text), "S1-qa-scout-2")


def refusal_judge_and_source_gaps() -> None:
    import story_run
    # J6: the judge reads the person's words into the option the conductor would have spent its
    # first turns deciding — and records nothing, which is the line plan section 10.6 draws.
    root, _tr, env = seed("QA-J6")
    try:
        driver = driver_for(root, env, "QA-J6")
        import judge_reply
        saved_intent, saved_gap = judge_reply.intent, judge_reply.stand_gap_option
        try:
            judge_reply.intent = lambda q, r, **k: {"status": "ok", "value": "approve_with_edits",
                                                    "leaning": "approve_with_edits",
                                                    "confidence": 0.93, "decided": True,
                                                    "judgment": "gate_reply_intent"}
            judge_reply.stand_gap_option = lambda r, **k: {"status": "ok", "value": "theirs",
                                                           "leaning": "theirs", "confidence": 0.95,
                                                           "decided": True,
                                                           "judgment": "gate_stand_gap_option"}
            read = driver.judged_reply("Approve the plan?", "yes, but drop TC-9", "gate_A")
            check_in("the gate answer is read into a registered option", "approve_with_edits", read)
            check_in("and the reading names the question that made it", "gate_reply_intent", read)
            check_in("with its confidence, so a weak reading is visible", "0.93", read)
            gap = driver.judged_reply("a stand gap card", "I'll do it myself", "stand_gap")
            check_in("a stand-gap card is read by its own question",
                     "gate_stand_gap_option", gap)
            judge_reply.intent = lambda q, r, **k: {"status": "off", "value": None}
            check_eq("with the judge off the conductor gets nothing extra",
                     driver.judged_reply("Approve?", "yes", "gate_A"), "")
            judge_reply.intent = lambda q, r, **k: {"status": "ok", "value": None,
                                                    "leaning": "reject", "confidence": 0.6,
                                                    "judgment": "gate_reply_intent"}
            undecided = driver.judged_reply("Approve?", "hmm", "gate_A")
            check_in("an undecided reading travels as a leaning, never as a decision",
                     "a leaning only", undecided)
        finally:
            judge_reply.intent, judge_reply.stand_gap_option = saved_intent, saved_gap
        check_in("and the prompt says the option decides nothing",
                 "it decides nothing and records nothing", story_run.PRE_FILLED)

        # 26.09: the person is told WHY material is out of reach, and an access failure is not a
        # gap to accept — it is a dropped VPN or an expired login to check.
        inventory = driver.task_root / "work" / "source-inventory.json"
        inventory.parent.mkdir(parents=True, exist_ok=True)
        mr_url = "https://githost.example.invalid/group/app/-/merge_requests/3890"
        inventory.write_text(json.dumps({"schema_version": 1, "sources": [
            {"source_id": "SRC-1", "canonical_ref": "https://jira.example.invalid/browse/APP-8384",
             "status": "read", "materials": {"external_media": {"status": "unavailable", "items": [
                 {"url": mr_url, "status": "unavailable", "error": "auth_required: 302 to the SSO login",
                  "cause": "auth_required", "access_problem": True}]}}}]}), encoding="utf-8")
        gap = driver.s1_gap_text("source material unavailable and not accepted by a person: SRC-1")
        check_in("the gap question carries the cause, not only the URL",
                 "auth_required: 302 to the SSO login", gap)
        check_in("and says that a lost login answers exactly this way",
                 "dropped VPN or an expired login", gap)
        check_in("and warns what accepting it would put on the record",
                 "reachable source on the record as unreachable", gap)

        # What the factory's own authenticated route can collect, code collects before asking.
        calls: list = []
        saved_py = driver.py

        def fake_py(script, *args, **kwargs):
            calls.append((script, args))
            if script == "vcs_evidence.py":
                target = driver.project / args[args.index("--output") + 1]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps({
                    "status": "read", "revision": "c862735b7efe", "complete": True,
                    "url": "https://githost.example.invalid/g/a/-/merge_requests/3890",
                    "discussions": [1, 2],
                    "notes": [{"author": {"name": "Reviewer"}, "body": "the fixture shape was unreal"}],
                    "diffs": [{"new_path": "src/webhook.py"}],
                    "metadata": {"title": "read the action from object_attributes", "state": "merged",
                                 "description": "the filter read the wrong field and 111 tests stayed green"},
                }), encoding="utf-8")
            return 0, ""

        driver.py = fake_py
        try:
            check_eq("a merge request handed in as material is collected by code",
                     driver.close_vcs_gaps(
                         ["source material unavailable and not accepted by a person: SRC-1"]), True)
            # The trigger is any complaint about material, not only a declared gap: "materials not
            # inspected" names no source id, and four merge requests sat `pending` behind exactly
            # that wording while the ladder waited for a gap to be declared first.
            check_eq("a refusal that names no source still runs the ladder over every source",
                     driver.close_vcs_gaps(["source-inventory.json: materials not inspected"]), True)
        finally:
            driver.py = saved_py
        scripts_called = [name for name, _ in calls]
        check_in("through the factory's own collector", "vcs_evidence.py", scripts_called)
        check_in("and recorded as material that was read", "ticket_adapter.py", scripts_called)
        # An API receipt is evidence and it is huge (the precedent's four: 79 KB … 3.8 MB), so code
        # writes the readable part beside it — that is what a brief can hand to a role.
        digest = driver.task_root / "work" / "sources" / "SRC-1" / "mr-3890.md"
        check("a digest is written next to the receipt", digest.is_file())
        body = digest.read_text(encoding="utf-8")
        check_in("with the author's own words", "111 tests stayed green", body)
        check_in("with the review's words", "the fixture shape was unreal", body)
        check_in("with the files it touched", "src/webhook.py", body)
        check_in("and a pointer to the evidence itself", "mr-3890.json", body)
        recorded = next(args for name, args in calls if name == "ticket_adapter.py")
        check_in("as read, because the API route gives description and discussions",
                 "read", list(recorded))

        # Route 2: the API did not answer, the local checkout carries the change — and the change
        # is not the discussion, so what is recorded is `partial`, never `read`.
        calls.clear()
        saved_git = driver.git_route

        def failing_py(script, *args, **kwargs):
            calls.append((script, args))
            return (1, "401 unauthenticated") if script == "vcs_evidence.py" else (0, "")

        driver.py, driver.git_route = failing_py, lambda url, rel: "the local checkout ../../app carries the change as abc123456"
        try:
            check_eq("the local git route still closes the material",
                     driver.close_vcs_gaps(
                         ["source material unavailable and not accepted by a person: SRC-1"]), True)
        finally:
            driver.py, driver.git_route = saved_py, saved_git
        partial = next(args for name, args in calls if name == "ticket_adapter.py")
        check_in("recorded as partial, not as read", "partial", list(partial))
        check_in("naming what the route could not give",
                 "discussions are not in it", " ".join(str(a) for a in partial))

        # The person's own route: they read it and paste what matters. That is material with its
        # own provenance, not an accepted gap.
        calls.clear()
        driver.py = fake_py
        try:
            supplied = driver.record_pasted({"SRC-1"}, "Here is the thread that matters:\n"
                                            "```\nreviewer: the fixture shape was unreal\n```")
        finally:
            driver.py = saved_py
        check_eq("pasted content becomes material of that source", len(supplied), 1)
        pasted_call = next(args for name, args in calls if name == "ticket_adapter.py")
        check_in("with the provenance saying who produced it", "person_pasted", list(pasted_call))
        check_in("and the question offers that route in words",
                 "provenance: person_pasted", gap)

        # F1: `ask_person` without a question is the conductor failing its own contract.
        driver.pass_to_person({"action": "ask_person", "question": "", "did": ""},
                              "conductor", "S1", "S1-qa-scout-1")
        check("an empty ask_person is not a question for the person", True)
        try:
            driver.pass_to_person({"action": "ask_person", "question": "Which stand?", "why_person": "access", "checked": "the refusal"},
                                  "halt", "S5", "S5-qa-runner-1")
            check("a real question still reaches the person", False)
        except story_run.Person as person:
            check_eq("in the conductor's own words", person.text, "Which stand?")
    finally:
        harness.cleanup(root)


def refusal_every_action_has_a_move() -> None:
    # --- every state the controller can return has a move on this side (FR-42) ---------------
    # Not a list somebody keeps up to date: the actions are read out of the controller's own
    # source, so an action added there fails this check until the driver answers it. Three were
    # missing when this was written - `observe_environment_job` (the controller's FIRST branch),
    # `handoff_ready` and `rollover_pending` - and each of them ended as "the driver has no move
    # for X" -> conductor -> a question to a person.
    controller_src = (harness.SCRIPTS / "controller.py").read_text(encoding="utf-8")
    body = controller_src[controller_src.index("def _next_action_for_state"):]
    body = body[:body.index("\n    @staticmethod")] if "\n    @staticmethod" in body else body
    # an action built in a module-level helper `_<name>_action(` that the body calls (t-1562 F5: `execute_gate_b` is built in
    # `_execute_gate_b_action`) is read too - otherwise it escapes this census in silence
    for helper in sorted(set(re.findall(r'\b(_\w+_action)\(', body))):
        start_helper = controller_src.find(f"\ndef {helper}(")
        if start_helper >= 0:
            body += controller_src[start_helper:].split("\n\n\n")[0]
    # `where` is story_step's answer, so its own action counts too: the controller names
    # twelve (the orders of gate B among them) and story_step adds `stop` when pipeline.stop_after ends the run.
    step_src = (harness.SCRIPTS / "story_step.py").read_text(encoding="utf-8")
    actions = sorted(set(re.findall(r'"action":\s*"(\w+)"', body))
                     | set(re.findall(r'"action":\s*"(\w+)"', step_src)))
    driver_src = harness.driver_text()
    handled = set(re.findall(r'kind == "(\w+)"', driver_src))
    handled |= {name for group in re.findall(r'kind in \(([^)]*)\)', driver_src)
                for name in re.findall(r'"(\w+)"', group)}
    handled |= set(re.findall(r'action\.get\("action"\) == "(\w+)"', driver_src))
    check("the other side's own sources name sixteen actions (`execute_gate_b` read from its helper; the three of the story held for code)",
          len(actions) == 16 and "execute_gate_b" in actions, str(actions))
    missing = [a for a in actions if a not in handled]
    check("and the driver has a branch for every one of them", not missing,
          f"no branch for {missing}")
    # the former tail of this function pinned the literal `kind == "..."` form inside the body of ONE member (`dispatch_action`):
    # a source pin of one named member, deleted by TD-11 phase 0 (F3, docs/TESTING.md l.94); the census above is the form census


def refusal_active_dispatch() -> None:
    import story_run
    # --- the refusal whose whole answer is "ask `where` again" --------------------------------
    # TP1-13797 run 5: four conductor sessions, $0.53, every one of them answering "No
    # command run - where already resolves it: wait_existing_job".
    check_eq("an active sequential dispatch is a known refusal the driver answers itself",
             story_run.match_known("story_step start (exit 2): story_step: refused - sequential "
                                   "task already has an active dispatch S5-qa-code-critic-2"),
             ("active_dispatch", "continue"))


def refusal_structured_artifact() -> None:
    """t-210 / F-cmp2-16: `story_step finish` refusing the role's STRUCTURED artifact resumes the role's OWN session
    once with the refusal verbatim, then `finish` runs again. INVARIANTS: never the conductor, never a fresh
    dispatch; the same refusal a second time (also after a relaunch: the count is in the state file), or no known
    session, is the person's; a refusal of any length is passed whole; a text with a form problem AND a structured
    problem resumes the role once, not twice and not never."""
    import story_run
    Refusal = story_run.Refusal
    task = "QA-9"
    root, task_root, env = seed(task)

    def lf(prompt: str) -> str:
        return prompt.replace(chr(13) + chr(10), chr(10))     # the prompt crosses stdin: Windows text mode adds CR
    try:
        def refused(dispatch: str, body: str = "") -> str:
            return (f"story_step finish {dispatch} (exit 2):\nstory_step: refused - S3 structured test plan invalid: "
                    "OB-1: sufficiency_review required: {author_dispatch_id, input_hash, rationale}, all non-empty; "
                    "OB-1: coverage_links[0] needs candidate_id (CAND-n) or test_ref (a test node id)" + body)

        def driver_at(dispatch: str, session: str = "sess-strategist"):
            driver = driver_for(root, env, task)
            driver.boundary = f"S3:{dispatch}"
            if session:
                driver.state["sessions"][dispatch] = session
            return driver

        def finish_loop(driver, dispatch: str, text: str) -> list:
            """What `guarded` does around `finish`: the move refuses, the retry is `finish` again."""
            ran = []

            def retry():
                ran.append("finish again")
                raise Refusal(text, retry=retry)      # the artifact is still refused

            def move():
                ran.append("finish")
                raise Refusal(text, retry=retry)
            try:
                driver.guarded(move, {"action": "wait_existing_job", "stage": "S3"})
            except story_run.Person as person:
                ran.append(person)
            return ran

        set_control(root, {"resume": {"result": "repaired"}})
        d1 = "S3-qa-test-strategist-1"
        text = refused(d1)
        check_eq("the row: a structured-artifact refusal of `finish` is resumed by the role",
                 story_run.match_known(text), ("structured_artifact", "resume_structured"))
        names = [row[0] for row in story_run.KNOWN_REFUSALS]
        check("POSITION: after form_vocabulary and before missing_output",
              names.index("form_vocabulary") < names.index("structured_artifact") < names.index("missing_output"), str(names))
        check("the S1 source-collection refusal is not this row",
              (story_run.match_known("story_step: refused - S1 source collection pending/invalid: x") or ("",))[0]
              != "structured_artifact")

        # (1) one resume of the role's own session with the refusal verbatim, then `finish` again
        before = len(stub_calls(root))
        driver = driver_at(d1)
        ran = finish_loop(driver, d1, text)
        calls = stub_calls(root)[before:]
        check_eq("(1) the role's own session is resumed once, and nothing else is called",
                 [(c["kind"], c["resume"]) for c in calls], [("resume", "sess-strategist")])
        check_in("(1) the prompt holds the refusal verbatim", text.strip(), lf(calls[0]["prompt"]))
        check_in("(1) and the one sentence", "Repair the named fields in the artifact, change nothing else", calls[0]["prompt"])
        check_eq("(1) `finish` runs again after the resume", ran[:2], ["finish", "finish again"])
        check_eq("(1) the count is in the state file, keyed by dispatch",
                 json.loads((task_root / "state/driver-state.json").read_text(encoding="utf-8")).get("structured_resumes"), {d1: 1})

        # (2) the same refusal again: a Person with the refusal verbatim, no conductor, no new dispatch
        person = ran[-1]
        check("(2) the second refusal is the person's", isinstance(person, story_run.Person), repr(ran))
        check_eq("(2) its details are the refusal, verbatim", person.details, text)
        check_eq("(2) one resume in all, no conductor, no new role", [c["kind"] for c in stub_calls(root)[before:]], ["resume"])
        # the count survives a relaunch (exit 3, a new driver over the same state file)
        before = len(stub_calls(root))
        again = driver_at(d1, session="")
        ran = finish_loop(again, d1, text)
        check("(2) a relaunched driver asks at once", isinstance(ran[-1], story_run.Person), repr(ran))
        check_eq("(2) and calls nothing", len(stub_calls(root)) - before, 0)

        # (3) no known session: the person, nothing is called
        before = len(stub_calls(root))
        d3 = "S3-qa-test-strategist-3"
        ran = finish_loop(driver_at(d3, session=""), d3, refused(d3))
        check("(3) no session known: the person", isinstance(ran[-1], story_run.Person), repr(ran))
        check_eq("(3) nothing is called", len(stub_calls(root)) - before, 0)

        # (4) a refusal of 7,000 characters is passed whole
        d4 = "S3-qa-test-strategist-4"
        big = refused(d4, "".join(f"; OB-{n}: sufficiency_review required: {{author_dispatch_id, input_hash, rationale}}"
                                 for n in range(2, 90)) + "; OB-LAST: the final named field")
        check("(4) fixture: over 7,000 characters", len(big) > 7000, str(len(big)))
        before = len(stub_calls(root))
        driver = driver_at(d4)
        driver.handle_refusal(Refusal(big, retry=lambda: None))
        calls = stub_calls(root)[before:]
        check_in("(4) the prompt holds all of it, down to the last named field", big.strip(), lf(calls[0]["prompt"]))

        # (5) a form problem and a structured problem in ONE text: the role is resumed once, with the whole text
        d5 = "S3-qa-test-strategist-5"
        combined = (f"story_step finish {d5} (exit 2):\nhandoff_check: handover form {d5}.yaml is not ready: "
                    "scope[0] is empty\nstory_step: refused - S3 structured test plan invalid: OB-1: sufficiency_review required")
        check_eq("(5) fixture: the table's first match is the form row",
                 story_run.match_known(combined), ("handover_form", "resume_handoff"))
        before = len(stub_calls(root))
        ran = finish_loop(driver_at(d5), d5, combined)
        calls = stub_calls(root)[before:]
        check_eq("(5) the role is resumed ONCE, in its own session", [(c["kind"], c["resume"]) for c in calls],
                 [("resume", "sess-strategist")])
        check_in("(5) with the whole text", combined.strip(), lf(calls[0]["prompt"]))
        check("(5) and the second refusal is the person's", isinstance(ran[-1], story_run.Person), repr(ran))
    finally:
        harness.cleanup(root)


def refusal_gate_stage_row() -> None:
    """t-211 (F0, C9): `stage_done` refusing to RECORD a stage in front of a gate ("stands in front of gate") is the
    driver's own to go on over - story_step has already had the controller accept the stage, so there is nothing to
    retry and the conductor would only say `continue` ($0.11-0.43, twice per gate stage in cmp2). The row is FIRST in
    the table (the text carries up to four rehearsal findings, whose words can hold a later row's phrase), and
    `handle_refusal` lets it go on ONLY while the controller's stage is `completed`; what the refused finish skipped
    (S4's case appendix, S8's report rebuild) is owed at gate entry."""
    import story_run
    Refusal = story_run.Refusal
    task = "QA-9"
    root, task_root, env = seed(task)

    def refused(stage: str, inside: str = "") -> str:
        gate = {"S4": "A", "S8": "B"}[stage]
        return (f"story_step finish {stage}-qa-case-critic-1 (exit 2):\nstage_done: {stage} stands in front of gate {gate}, and "
                f"the rehearsal (`gate_preflight.py --task QA-9 --gate {gate}`) still has 4 thing(s) the FACTORY has to repair "
                f"before anyone is asked: {inside}one; two; three; four. Repair them, then close the stage. If a person decided "
                f"to go to the gate anyway: `waiver.py --task QA-9 --stage {stage} --block \"gate rehearsal\" --decision "
                f"\"<their words>\"`.\nstory_step: stage_done refused {stage} (exit 2); the refusal above is the halt")

    def set_stage(stage: str, status: str) -> None:
        path = task_root / "state" / "controller.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["stages"][stage] = {"status": status}
        path.write_text(json.dumps(data), encoding="utf-8")
    try:
        check_eq("M11: the stage_done refusal in front of gate A continues, by the new row",
                 story_run.match_known(refused("S4")), ("gate_stage", "continue"))
        check_eq("and the one in front of gate B", story_run.match_known(refused("S8")), ("gate_stage", "continue"))
        check_eq("C9: the row is the first a rehearsal finding's words can match (only `committed_event`, which keys on "
                 "an event already in the journal, stands before it)",
                 [row[0] for row in story_run.KNOWN_REFUSALS][:2], ["committed_event", "gate_stage"])
        for phrase in ("STORY BUDGET: past its ceiling", "expected_revision 4", "executor unavailable", "readiness: stand missing",
                       "report check: damaged", "no person has reviewed the source decisions", "is not in this build",
                       "sequential task already has an active dispatch", "is not the handoff form", "already accepted"):
            check_eq(f"C9: a finding that holds `{phrase}` does not take the refusal to a later row",
                     (story_run.match_known(refused("S4", phrase + "; ")) or ("",))[0], "gate_stage")
        check("the row names nothing but its own phrase: a refusal that is not this one is not caught",
              (story_run.match_known("stage_done: S4 closes without it") or ("",))[0] != "gate_stage")

        # the controller's own stage decides: completed -> the driver goes on, with no conductor
        calls = []
        driver = driver_for(root, env, task)
        driver.conductor = lambda text, *, words="", files=None, words_file=None: calls.append(text) or {"action": "continue", "did": "stub"}
        set_stage("S4", "completed")
        driver.boundary = "S4:S4-qa-case-critic-1"
        with contextlib.redirect_stdout(io.StringIO()):
            outcome = driver.handle_refusal(Refusal(refused("S4"), retry=lambda: None))
        check_eq("a completed S4: `continue`, and the conductor is not called", (outcome, calls), ("continue", []))
        check_in("it is journalled as the known row", "known:gate_stage",
                 json.dumps(jsonl(task_root / "state/conductor.jsonl")))
        check_eq("C10: the case appendix S4's refused finish skipped is owed at gate entry (kept in the state file)",
                 sorted(json.loads((task_root / "state/driver-state.json").read_text(encoding="utf-8"))["gate_entry_owed"]), ["S4"])
        set_stage("S8", "completed")
        driver.boundary = "S8:S8-qa-doc-scribe-1"
        with contextlib.redirect_stdout(io.StringIO()):
            outcome = driver.handle_refusal(Refusal(refused("S8")))
        check_eq("a completed S8: the same, and the report rebuild is owed too",
                 (outcome, calls, sorted(driver.state["gate_entry_owed"])), ("continue", [], ["S4", "S8"]))
        # a stage the controller still holds open is NOT this refusal's case: the conductor, as before the row
        set_stage("S4", "running")
        driver = driver_for(root, env, task)
        driver.conductor = lambda text, *, words="", files=None, words_file=None: calls.append(text) or {"action": "continue", "did": "stub"}
        driver.state["gate_entry_owed"] = {}
        driver.boundary = "S4:S4-qa-case-critic-1"
        with contextlib.redirect_stdout(io.StringIO()):
            outcome = driver.handle_refusal(Refusal(refused("S4")))
        check_eq("an S4 the controller holds open: the conductor is called, nothing is owed",
                 (outcome, len(calls), driver.state["gate_entry_owed"]), ("continue", 1, {}))
        check_in("with the refusal", "stands in front of gate A", calls[0])
        set_stage("S4", "pending")
        driver.boundary = "S4:S4-qa-case-critic-1"
        with contextlib.redirect_stdout(io.StringIO()):
            driver.handle_refusal(Refusal(refused("S4")))
        check_eq("a stage that is not even running: the conductor too", len(calls), 2)
        data = json.loads((task_root / "state" / "controller.json").read_text(encoding="utf-8"))
        data["stages"].pop("S4")
        (task_root / "state" / "controller.json").write_text(json.dumps(data), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            driver.handle_refusal(Refusal(refused("S4")))
        check_eq("a stage the controller does not know: the conductor too", len(calls), 3)
    finally:
        os.chdir(harness.PLUGIN_ROOT)
        harness.cleanup(root)


def refusal_committed_event_recovers() -> None:
    """legacy-2406 W2 (M3): `controller.py` refuses with "event committed; ...; do not repeat the action" when the event
    is in the journal and only what comes after it failed. The door is a command code can run (`--operation recover`), so
    the conductor is not asked (FR-48, P3) - and the action is NOT repeated: the answer is `continue`, back to `where`.

    S1 (the table's order, `committed_event` -> `gate_stage` -> `report_check`): a text holding both a committed-event
    phrase and `stands in front of gate` routes to `committed_event`; a rehearsal text holding `STORY BUDGET` /
    `expected_revision` plus `stands in front of gate` still routes to `gate_stage` (`refusal_gate_stage_row` holds the
    rest of that row). S3: `conductor_round` takes `recover_failed` and `committed`; a caller that passes neither
    (`hand_to_conductor`) gets the call it always got."""
    import story_run
    task = "QA-9"
    committed = {
        "derived view": ('controller dispatch (exit 2):\n{"error": "event committed; derived view not '
                         'refreshed (OSError: disk full); do not repeat the action; `controller.py '
                         '--task-root T --operation recover` refreshes it (recorded in '
                         'state/dashboard-deferred.json)"}'),
        "projection": ('controller dispatch (exit 2):\n{"error": "event committed; projection stale; '
                       'recover, do not repeat action"}'),
        "projection on a replay": ('controller dispatch (exit 2):\n{"error": "event already committed; '
                                   'projection stale; recover, do not repeat action"}'),
        # The failure text may itself contain words another row knows: the committed event is the
        # fact that decides.
        "a failure that looks like another row": (
            'controller accept (exit 2):\n{"error": "event committed; derived view not refreshed '
            '(OSError: stage already completed, expected_revision 3); do not repeat the action"}'),
        # The third text the store itself produces (`event_store._run_after_commit`): the step after the commit failed.
        "the step that follows the commit": (
            'controller dispatch (exit 2):\n{"error": "event committed; the step that follows it did not finish '
            '(OSError: disk full); do not repeat the action"}'),
        "the step that follows, with a word of another row": (
            'controller accept (exit 2):\n{"error": "event committed; the step that follows it did not finish '
            '(RuntimeError: expected_revision 3, STORY BUDGET); do not repeat the action"}')}
    for label, text in committed.items():
        check_eq(f"{label}: the refusal is a known row", (story_run.match_known(text) or ("", ""))[1], "recover")

    # S1: the order of the table's head, and the two texts that decide it
    check_eq("S1: the table opens with committed_event, gate_stage, report_check, in this order",
             [row[0] for row in story_run.KNOWN_REFUSALS][:3], ["committed_event", "gate_stage", "report_check"])
    both = ('controller accept (exit 2):\n{"error": "event committed; derived view not refreshed (OSError: S4 stands in '
            'front of gate A); do not repeat the action"}')
    check_eq("S1: a text holding a committed-event phrase AND `stands in front of gate` is the committed event",
             story_run.match_known(both), ("committed_event", "recover"))
    rehearsal = ("story_step finish S4-qa-case-critic-1 (exit 2):\nstage_done: S4 stands in front of gate A, and the "
                 "rehearsal still has 2 thing(s) the FACTORY has to repair: STORY BUDGET: past its ceiling; "
                 "expected_revision 4.")
    check_eq("S1: a rehearsal text holding STORY BUDGET / expected_revision plus `stands in front of gate` is gate_stage",
             story_run.match_known(rehearsal), ("gate_stage", "continue"))

    root, task_root, env = seed(task)
    try:
        driver = driver_for(root, env, task)
        driver.boundary = "S1"
        for label, text in committed.items():
            ran, repeated, before = [], [], len(stub_calls(root))

            def recover(operation, *args, input_data=None, _ran=ran):
                _ran.append(operation)
                return {}
            driver.controller = recover

            def move(_repeated=repeated, _text=text):
                _repeated.append(1)
                raise story_run.Refusal(_text)
            driver.guarded(move, {"action": "prepare_stage", "stage": "S1"})
            check_eq(f"{label}: the driver ran recover once", ran, ["recover"])
            check_eq(f"{label}: and did not repeat the committed action", repeated, [1])
            check_eq(f"{label}: no conductor session was spent", len(stub_calls(root)) - before, 0)
            check_eq(f"{label}: conductor.jsonl names the table row",
                     jsonl(task_root / "state/conductor.jsonl")[-1]["action"], "known:committed_event")

        # recover itself refused: that is a refusal nothing here knows, so it goes where an unknown
        # one goes today - to the conductor - and recover is not run a second time.
        set_control(root, {"conductor": {"action": "ask_person", "question": "recover failed; what now?",
                                         "did": "read where"}})
        ran, before, defects = [], len(stub_calls(root)), []

        def failing_recover(operation, *args, input_data=None):
            ran.append(operation)
            raise story_run.Refusal("controller recover (exit 2):\nthe moon is down and nobody knows why")
        driver.controller = failing_recover
        real_py = driver.py
        driver.py = lambda script, *a, **k: (defects.append(a), (0, ""))[1] if script == "log_append.py" and "defect_found" in a \
            else real_py(script, *a, **k)
        try:
            driver.guarded(lambda: (_ for _ in ()).throw(story_run.Refusal(committed["projection"])),
                           {"action": "prepare_stage", "stage": "S1"})
            check("a second failure reaches the conductor and its answer", False)
        except story_run.Person as person:
            # C1-1: a conductor `ask_person` with NO options is not a usable answer: the priced fallback question is raised
            # instead, and the factory's own defect is journalled once (its words are not shown as a question).
            check_eq("the conductor's ask_person with no options ends the loop in the fallback question",
                     (person.kind, list(person.offered)), ("conductor", ["retry", "go on", "stop"]))
            check_not_in("and the conductor's bare question text is not shown", "recover failed; what now?", person.text)
            for label in ("the factory:", "you:", "the story:"):
                check_in(f"and every answer has the line `{label}`", label, person.text)
            check_eq("and exactly one defect_found is journalled", len(defects), 1)
        driver.py = real_py
        check_eq("recover was run once, not looped on", ran, ["recover"])
        check_eq("and the conductor was asked once", len(stub_calls(root)) - before, 1)
        check_in("with recover's own refusal in front of it", "the moon is down", stub_calls(root)[-1]["prompt"])
        check_in("and the refusal it was run for, so the conductor can judge the pair",
                 "event committed; projection stale", stub_calls(root)[-1]["prompt"])

        # The committed action is NEVER run again by any path: the conductor's `retry` is read as
        # `continue` (back to `where`), because `refusal.retry` would write the event twice.
        set_control(root, {"conductor": {"action": "retry", "did": "looked at recover's refusal"}})
        ran, again, moves, before = [], [], [], len(stub_calls(root))
        driver.boundary = "S2"  # the conductor's allowance is per boundary

        def committed_move():
            moves.append(1)
            raise story_run.Refusal(committed["derived view"], retry=lambda: again.append("re-ran"))
        driver.guarded(committed_move, {"action": "prepare_stage", "stage": "S1"})
        check_eq("recover failed: the conductor was asked, and said retry", len(stub_calls(root)) - before, 1)
        check_eq("the committed action was not run again", again, [])
        check_eq("and the move itself was made once", moves, [1])
        prompt = stub_calls(root)[-1]["prompt"]
        check_in("the conductor was shown the refusal the event came with", "derived view not refreshed", prompt)
        check_in("and recover's refusal beside it", "the moon is down", prompt)

        # What `retry` means for any OTHER row is unchanged: `dead_dispatch` is a refusal of an
        # action that never committed anything, so recover failing and the conductor saying
        # `retry` re-runs that action - there is no event it could write twice.
        ran, again, moves = [], [], []
        driver.boundary = "S5"

        def dead_move():
            moves.append(1)
            raise story_run.Refusal("story_step start (exit 2): wait_existing_job S5-qa-automator-1 returned",
                                    retry=lambda: again.append("re-ran"))
        driver.guarded(dead_move, {"action": "prepare_stage", "stage": "S5"})
        check_eq("dead_dispatch: recover was run once", ran, ["recover"])
        check_eq("and a conductor `retry` still re-runs its refused action", again, ["re-ran"])
        check_in("with both texts in front of the conductor", "wait_existing_job",
                 stub_calls(root)[-1]["prompt"])
        check_in("and recover's", "the moon is down", stub_calls(root)[-1]["prompt"])

        # F1: every committed text is the committed event - the third one too: recover failing and the conductor saying
        # `retry` never repeats the action (today: no row, `committed` stays False, `retry` runs `refusal.retry`).
        for label in ("the step that follows the commit", "the step that follows, with a word of another row"):
            driver.controller = failing_recover
            driver.conductor_calls = {}
            driver.boundary = "S2"
            ran, again, moves = [], [], []

            def third_move(_text=committed[label]):
                moves.append(1)
                raise story_run.Refusal(_text, retry=lambda: again.append("re-ran"))
            driver.guarded(third_move, {"action": "prepare_stage", "stage": "S1"})
            check_eq(f"F1 {label}: recover was run once", ran, ["recover"])
            check_eq(f"F1 {label}: the conductor's `retry` did not run the committed action again", again, [])
            check_eq(f"F1 {label}: and the move was made once", moves, [1])

        # F2: a committed finish over a stage the controller has CLOSED skipped the stage's tail: the same mark
        # `gate_stage` leaves, so the gate entry runs it - once. A stage that is not completed is not marked, and a
        # `recover` that refuses keeps the conductor's path with no mark.
        def set_stage(stage: str, status: str) -> None:
            path = task_root / "state" / "controller.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["stages"][stage] = {"status": status}
            path.write_text(json.dumps(data), encoding="utf-8")

        def finish_refused(stage: str, text: str):
            def move():
                raise story_run.Refusal(f"story_step finish {stage}-qa-case-critic-1 (exit 2):\n" + text)
            return move

        for label in ("derived view", "projection", "the step that follows the commit"):
            driver = driver_for(root, env, task)
            driver.state["gate_entry_owed"] = {}
            ran = []
            driver.controller = lambda operation, *args, input_data=None, _ran=ran: _ran.append(operation) or {}
            set_stage("S4", "completed")
            driver.boundary = "S4:S4-qa-case-critic-1"
            with contextlib.redirect_stdout(io.StringIO()):
                driver.guarded(finish_refused("S4", committed[label]), {"action": "prepare_stage", "stage": "S4"})
                driver.guarded(finish_refused("S4", committed[label]), {"action": "prepare_stage", "stage": "S4"})
            check_eq(f"F2 {label}: recovered twice (one per refusal), each time with no conductor", ran, ["recover", "recover"])
            check_eq(f"F2 {label}: a completed S4 is owed to gate A's entry, with one mark",
                     sorted(driver.state["gate_entry_owed"]), ["S4"])
            check_eq(f"F2 {label}: the mark is kept in the state file",
                     sorted(json.loads((task_root / "state/driver-state.json").read_text(encoding="utf-8")).get("gate_entry_owed") or {}),
                     ["S4"])
            rendered = []
            driver.render_appendix = lambda _r=rendered: _r.append(1)
            driver.gate_entry_steps("A")
            driver.gate_entry_steps("A")
            check_eq(f"F2 {label}: the gate entry runs the owed appendix once, not once per recovery", rendered, [1])
        driver = driver_for(root, env, task)
        driver.state["gate_entry_owed"] = {}
        rebuilt = []
        driver.rebuild_report = lambda: rebuilt.append(1)
        driver.controller = lambda operation, *args, input_data=None: {}
        set_stage("S8", "completed")
        driver.boundary = "S8:S8-qa-doc-scribe-1"
        with contextlib.redirect_stdout(io.StringIO()):
            driver.guarded(finish_refused("S8", committed["projection"]), {"action": "prepare_stage", "stage": "S8"})
        driver.gate_entry_steps("B")
        check_eq("F2: a completed S8 owes the report rebuild at gate B's entry", rebuilt, [1])
        for status in ("running", "pending"):
            driver = driver_for(root, env, task)
            driver.state["gate_entry_owed"] = {}
            driver.controller = lambda operation, *args, input_data=None: {}
            set_stage("S4", status)
            driver.boundary = "S4:S4-qa-case-critic-1"
            with contextlib.redirect_stdout(io.StringIO()):
                driver.guarded(finish_refused("S4", committed["derived view"]), {"action": "prepare_stage", "stage": "S4"})
            check_eq(f"F2: a stage that is `{status}` is not marked", driver.state["gate_entry_owed"], {})
        driver = driver_for(root, env, task)
        driver.state["gate_entry_owed"] = {}
        set_stage("S4", "completed")
        set_control(root, {"conductor": {"action": "continue", "did": "read where"}})
        driver.controller = failing_recover
        driver.conductor_calls = {}
        driver.boundary = "S4:S4-qa-case-critic-1"
        with contextlib.redirect_stdout(io.StringIO()):
            driver.guarded(finish_refused("S4", committed["derived view"]), {"action": "prepare_stage", "stage": "S4"})
        check_eq("F2: `recover` refused: the conductor's path, and no mark", driver.state["gate_entry_owed"], {})

        # S3: `conductor_round` itself. The gate-entry caller passes neither argument, and its `retry` stays `retry`.
        driver.conductor_calls = {}
        driver.boundary = "S3"
        calls = []
        driver.conductor = lambda text, *, words="", files=None, words_file=None: calls.append(text) or {"action": "retry", "did": "stub"}
        with contextlib.redirect_stdout(io.StringIO()):
            plain = driver.conductor_round(story_run.Refusal(committed["projection"]), "S3")
            held = driver.conductor_round(story_run.Refusal(committed["projection"]), "S3", committed=True,
                                          recover_failed="the moon is down")
        check_eq("S3: with neither argument a `retry` stays `retry` (the gate-entry caller's call)", plain, "retry")
        check_eq("S3: with `committed` a `retry` is read as `continue`", held, "continue")
        check_not_in("S3: with neither argument the conductor is shown the refusal alone", "was run for it and refused too",
                     calls[0])
        check_in("S3: with `recover_failed` it is shown both texts", "the moon is down", calls[1])
        check_in("S3: and the refusal beside it", "event committed; projection stale", calls[1])
    finally:
        harness.cleanup(root)


def git_fixture(root: Path):
    """A local bare 'remote' and a checkout of it under the temp project (nothing reaches a network):
    main holds A (TP1-100, an older commit of the ticket prefix) and B; `feat` adds C (TP1-15045),
    and the remote lists C as refs/merge-requests/1924/head. Returns (checkout, {"A","B","C"} full ids)."""
    import subprocess
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t")

    def git(cwd, *args):
        done = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, env=env, timeout=60)
        check_eq(f"fixture: git {' '.join(args[:2])}", done.returncode, 0)
        return done.stdout.strip()

    remote, app = root / "remote.git", root / "app"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-q", str(app)], check=True, capture_output=True)
    git(app, "checkout", "-q", "-b", "main")
    (app / "a.txt").write_text("a", encoding="utf-8")
    git(app, "add", "-A")
    git(app, "commit", "-q", "-m", "TP1-100 an older change of the ticket prefix")
    a = git(app, "rev-parse", "HEAD")
    (app / "b.txt").write_text("b", encoding="utf-8")
    git(app, "add", "-A")
    git(app, "commit", "-q", "-m", "an unrelated change")
    b = git(app, "rev-parse", "HEAD")
    git(app, "checkout", "-q", "-b", "feat")
    (app / "c.txt").write_text("c", encoding="utf-8")
    git(app, "add", "-A")
    git(app, "commit", "-q", "-m", "TP1-15045 draft evaluation tests")
    c = git(app, "rev-parse", "HEAD")
    git(app, "remote", "add", "origin", str(remote))
    git(app, "push", "-q", "origin", "main", "feat", f"{c}:refs/merge-requests/1924/head")
    return app, {"A": a, "B": b, "C": c}


def refusal_left_out_sources() -> None:
    """B-231 P4/P8: what the person left out before the run is never collected by code, never routed through the
    local checkout, and is named to the scout; the review question says how to take a word back."""
    import subprocess
    import source_exclusions as SE
    task = "TP1-15045"
    root, task_root, env = seed(task)
    try:
        app, sha = git_fixture(root)
        cfg_path = root / "qa-factory" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["implementation_repos"] = [{"repo_id": "testproject1-ui", "local_path": "app",
                                        "remote_identity": "git.example/tp1-group/testproject1-ui"}]
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        driver = driver_for(root, env, task)

        # --- close_vcs_gaps_skips_excluded: the `vcs_evidence` stub must not be called for the excluded item ---
        url_1924 = "https://git.example/tp1-group/testproject1-ui/-/merge_requests/1924"
        url_1881 = "https://git.example/tp1-group/testproject1-ui/-/merge_requests/1881"
        inventory = task_root / "work" / "source-inventory.json"
        inventory.write_text(json.dumps({"schema_version": 1, "sources": [
            {"source_id": "SRC-1", "canonical_ref": "https://jira.example.invalid/browse/TP1-15045", "status": "read",
             "materials": {"external_media": {"status": "pending", "items": [
                 {"url": url_1924, "status": "excluded", "excluded_by": {"exclusion": "X1"}},
                 {"url": url_1881, "status": "pending"}]}}}]}), encoding="utf-8")
        calls: list = []

        def fake_py(script, *args, **kwargs):
            calls.append((script, list(args)))
            if script == "vcs_evidence.py":
                target = driver.project / args[args.index("--output") + 1]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps({"status": "read", "revision": "abc123456789", "complete": True,
                                              "discussions": [], "notes": [], "diffs": [], "metadata": {}}), encoding="utf-8")
            return 0, ""

        saved_py = driver.py
        driver.py = fake_py
        try:
            check_eq("close_vcs_gaps_skips_excluded: the ladder collects what is pending", driver.close_vcs_gaps(
                ["source-inventory.json: materials not inspected"]), True)      # no id: "every source is fair game"
            fetched = [a[a.index("--url") + 1] for s, a in calls if s == "vcs_evidence.py"]
            check_eq("close_vcs_gaps_skips_excluded: vcs_evidence is asked for 1881 and never for 1924", fetched, [url_1881])
            recorded = [a[a.index("--media-url") + 1] for s, a in calls if s == "ticket_adapter.py"]
            check_eq("and only 1881 is recorded as inspected", recorded, [url_1881])
            calls.clear()
            check_eq("with a source id named the same skip holds", driver.close_vcs_gaps(
                ["source material unavailable and not accepted by a person: SRC-1"]), True)
            check_eq("(same again: 1881 only)", [a[a.index("--url") + 1] for s, a in calls if s == "vcs_evidence.py"], [url_1881])
            # an excluded item alone: nothing to collect, nothing asked of anyone
            inventory.write_text(json.dumps({"schema_version": 1, "sources": [
                {"source_id": "SRC-1", "status": "read", "materials": {"external_media": {"status": "read", "items": [
                    {"url": url_1924, "status": "excluded"}]}}}]}), encoding="utf-8")
            calls.clear()
            check_eq("only excluded items: no collection, the caller is not told something was collected",
                     (driver.close_vcs_gaps(["source-inventory.json: materials not inspected"]), calls), (False, []))
        finally:
            driver.py = saved_py

        # --- git_route: a commit only an excluded head carries is skipped (C2) --------------------------------
        def route(label):
            note = driver.git_route(url_1881, "sources/SRC-1/mr-1881-git.md")
            body = (task_root / "work" / "sources" / "SRC-1" / "mr-1881-git.md")
            return note, (body.read_text(encoding="utf-8") if body.is_file() else "")

        note, body = route("no list")
        check("git_route, no list: both commits of the ticket prefix are listed (today's behaviour)",
              sha["A"][:9] in note and sha["C"][:9] in note, note)
        text = "testproject1-ui!1924 - Draft MR of an earlier factory run, not a product change\n"
        entries, problems = SE.parse_bytes(text.encode("utf-8"), task)
        check_eq("the list parses", problems, [])
        entries[0]["target"]["head_sha"] = sha["C"]
        inventory.unlink()                     # a list is written before the inventory exists, never after
        SE.write_record(task_root, entries, "list.txt", text.encode("utf-8"))
        (task_root / "work" / "sources" / "SRC-1" / "mr-1881-git.md").unlink()
        note, body = route("excluded head")
        check("git_route skips the commit only the excluded head carries", sha["C"][:9] not in note and sha["C"] not in body,
              note + body[:400])
        check("git_route keeps the older commit of the prefix that main carries too (an ancestor of the head, not its own change)",
              sha["A"][:9] in note and sha["A"] in body, note + body[:400])
        # an unreachable head skips nothing
        record = json.loads((task_root / "work" / "source-exclusions.json").read_text(encoding="utf-8"))
        record["exclusions"][0]["target"]["head_sha"] = "f" * 40
        (task_root / "work" / "source-exclusions.json").write_text(json.dumps(record), encoding="utf-8")
        (task_root / "work" / "sources" / "SRC-1" / "mr-1881-git.md").unlink()
        note, body = route("unreachable head")
        check("git_route: a head this checkout does not hold skips nothing", sha["A"][:9] in note and sha["C"][:9] in note, note)
        # the head once main carries it too: no longer only the excluded request's own change
        git_env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        for args in (["checkout", "-q", "-B", "main", "feat"], ["commit", "-q", "--allow-empty", "-m", "later work on main"]):
            subprocess.run(["git", "-C", str(app), *args], check=True, capture_output=True, env=git_env)
        record["exclusions"][0]["target"]["head_sha"] = sha["C"]
        (task_root / "work" / "source-exclusions.json").write_text(json.dumps(record), encoding="utf-8")
        (task_root / "work" / "sources" / "SRC-1" / "mr-1881-git.md").unlink()
        note, body = route("merged head")
        check("git_route: a commit another branch carries is not skipped (in doubt it is read)",
              sha["C"][:9] in note, note)
        # an abbreviated head of a `ref` word resolves to the full id
        check("only_from_excluded_head: a head that resolves to nothing is False, a commit that is no hex is False",
              not driver.only_from_excluded_head(app, sha["A"], ["deadbeef" * 5]) and
              not driver.only_from_excluded_head(app, "not-a-sha", [sha["C"]]))

        # --- role_lines: the scout is told, with the head commit (C2) and the door ---------------------------------
        lines = driver.role_lines("S1", "qa-scout")
        told = [ln for ln in lines if ln.startswith("Left out by the person's word before the run")]
        check_eq("role_lines: one line for the scout", len(told), 1)
        check_in("role_lines: the word as written and the reason", 'testproject1-ui!1924 ("Draft MR of an earlier factory run', told[0])
        check_in("role_lines: the head commit, so a citation by commit is the same source", f"head commit {sha['C'][:12]}", told[0])
        check_in("role_lines: what not to do with it", "do not read, collect, cite as a source, precedent or existing coverage", told[0])
        check_in("role_lines: and the door", "say so in your handoff", told[0])
        check_eq("role_lines: other roles get no such line", [ln for ln in driver.role_lines("S2", "qa-requirements-tester")
                                                               if "Left out" in ln], [])
        SE.record_path(task_root / "work").write_text("{not json", encoding="utf-8")
        try:
            driver.role_lines("S1", "qa-scout")
            check("role_lines: an unreadable record refuses", False)
        except story_run_refusal() as refusal:
            check_in("role_lines: an unreadable record is a refusal that names the file", "source-exclusions.json", refusal.text)
        SE.record_path(task_root / "work").unlink()
        check_eq("role_lines: no record, no line (today's launch lines)",
                 [ln for ln in driver.role_lines("S1", "qa-scout") if "Left out" in ln], [])
        launch = (driver.state.setdefault("launch", {}))
        launch["mr_dropped"] = "!1924"
        driver.flags.mr = "!1924"
        check_in("role_lines: an --mr the person gave up at S0 is not in the scout's launch flags",
                 "Launch flags: none", "\n".join(driver.role_lines("S1", "qa-scout")))
        driver.flags.mr = None

        # --- the review question says how to take a word back -------------------------------------------------------
        driver.py = lambda script, *a, **k: (0, "THE TABLE")
        check_not_in("review text, no list: no sentence about left-out sources", "left out by you", driver.s1_review_text("digest"))
        (task_root / "work" / "source-exclusions.json").write_text(json.dumps(record), encoding="utf-8")
        shown = driver.s1_review_text("digest")
        check_in("review text, a list: the sentence", "The ones marked 'left out by you (before the run)' are not read; to read "
                 "one after all, name it in your answer.", shown)
        check_eq("review text: the sentence is there once", shown.count("left out by you"), 1)
    finally:
        harness.cleanup(root)


def refusal_adapter_forms_links_and_prefix() -> None:
    """B-405/B-406 (R9): `close_vcs_gaps` reads a link by `ticket_light.classify_url` - the PATH only, the number is group 2
    and must end the path or be followed by `/` (B7), a pull request is never sent to the GitLab collector - and `git_route`
    takes the ticket's prefix from the project's key form (none under a prefix-less form: the commit search is skipped)."""
    import subprocess
    task = "TP1-15045"
    root, task_root, env = seed(task)
    try:
        driver = driver_for(root, env, task)
        base = "https://githost.example.test/g/p"
        links = {
            "plain": f"{base}/-/merge_requests/5",
            "diffs": f"{base}/-/merge_requests/6/diffs",
            "query": "https://githost.example.test/login?next=/g/p/-/merge_requests/7",
            "glued": f"{base}/-/merge_requests/8a",
            "pull": "https://github.com/o/r/pull/9",
            "enterprise": "https://ghe.example.test/o/r/pull/10",
            "escaped": f"{base}/-/merge" + chr(92) + "_requests/11",
            "issue": f"{base}/-/issues/12",
            "bitbucket": "https://bitbucket.example.test/o/r/pull-requests/13",
            "fragment": "https://githost.example.test/login#/g/p/-/merge_requests/14",
        }
        inventory = task_root / "work" / "source-inventory.json"
        inventory.parent.mkdir(parents=True, exist_ok=True)
        inventory.write_text(json.dumps({"schema_version": 1, "sources": [
            {"source_id": "SRC-1", "canonical_ref": "https://jira.example.invalid/browse/TP1-15045", "status": "read",
             "materials": {"external_media": {"status": "pending", "items": [
                 {"url": url, "status": "pending"} for url in links.values()]}}}]}), encoding="utf-8")
        calls: list = []

        def fake_py(script, *args, **kwargs):
            calls.append((script, list(args)))
            if script == "vcs_evidence.py":
                target = driver.project / args[args.index("--output") + 1]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps({"status": "read", "revision": "abc123456789", "complete": True,
                                              "discussions": [], "notes": [], "diffs": [], "metadata": {}}), encoding="utf-8")
            return 0, ""

        saved_py = driver.py
        driver.py = fake_py
        shown = io.StringIO()
        try:
            with contextlib.redirect_stdout(shown):
                got = driver.close_vcs_gaps(["source-inventory.json: materials not inspected"])
        finally:
            driver.py = saved_py
        fetched = [a[a.index("--url") + 1] for s, a in calls if s == "vcs_evidence.py"]
        outputs = [a[a.index("--output") + 1].rsplit("/", 1)[-1] for s, a in calls if s == "vcs_evidence.py"]
        recorded = [a[a.index("--media-url") + 1] for s, a in calls if s == "ticket_adapter.py"]
        check_eq("forms/links: the ladder collected something", got, True)
        check_eq("forms/links: only the merge requests are sent to the GitLab collector (plain, /diffs, the markdown-escaped one)",
                 fetched, [links["plain"], links["diffs"], links["escaped"].replace(chr(92), "")])
        check_eq("forms/links B7: the number is group 2 of the kind's rule (5, 6 from /diffs, 11 through the escape)",
                 outputs, ["mr-5.json", "mr-6.json", "mr-11.json"])
        check_eq("forms/links: and only those are recorded as inspected", recorded, [links["plain"], links["diffs"], links["escaped"]])
        for name in ("query", "glued", "enterprise", "issue", "bitbucket", "fragment"):
            check(f"forms/links: `{name}` is no request (never collected without a receipt)", links[name] not in fetched, str(fetched))
        check("forms/links: a pull request is never sent to vcs_evidence", links["pull"] not in fetched)
        check_in("forms/links: ... one line says why, naming the link", links["pull"] + " is a pull request", shown.getvalue())
        check_in("forms/links: ... and that it stays pending", "left pending", shown.getvalue())
        items = {i["url"]: i["status"] for s in json.loads(inventory.read_text(encoding="utf-8"))["sources"]
                 for i in s["materials"]["external_media"]["items"]}
        check_eq("forms/links: the pull request item stays pending in the inventory", items[links["pull"]], "pending")
        check_eq("forms/links: so does a glued number", items[links["glued"]], "pending")
    finally:
        harness.cleanup(root)

    # --- git_route: the prefix is the key form's ---
    def route_for(task_name: str, ticket_cfg: dict | None, commits: tuple = (), url_iid: str = "1881"):
        proj, proj_root, proj_env = seed(task_name)
        try:
            app, _sha = git_fixture(proj)
            git_env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
            for message in commits:
                subprocess.run(["git", "-C", str(app), "commit", "-q", "--allow-empty", "-m", message], check=True,
                               capture_output=True, env=git_env)
            cfg_path = proj / "qa-factory" / "config.json"
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            cfg["implementation_repos"] = [{"repo_id": "testproject1-ui", "local_path": "app",
                                            "remote_identity": "git.example/tp1-group/testproject1-ui"}]
            if ticket_cfg is not None:
                cfg["adapters"]["ticket"].update(ticket_cfg)
            cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
            drv = driver_for(proj, proj_env, task_name)
            said = io.StringIO()
            with contextlib.redirect_stdout(said):
                note = drv.git_route(f"https://git.example/tp1-group/testproject1-ui/-/merge_requests/{url_iid}", "sources/SRC-1/mr-x-git.md")
            written = proj_root / "work" / "sources" / "SRC-1" / "mr-x-git.md"
            return note, said.getvalue(), (written.read_text(encoding="utf-8") if written.is_file() else "")
        finally:
            harness.cleanup(proj)

    note, said, body = route_for("TP1-15045", None)
    check("forms/git_route (Jira, today's behaviour): the ticket prefix finds the commits of the ticket", "the local checkout app" in note, note)
    check_not_in("forms/git_route (Jira): nothing is skipped, so nothing is said", "no project prefix", said)
    note, said, body = route_for("123", {"name": "github"})
    check_eq("forms/git_route (numeric story, no ref for this number): the prefix search is skipped, so nothing is found", (note, body), ("", ""))
    check_in("forms/git_route (numeric story): the line says the prefix search was skipped and why", "has no project prefix", said)
    note, said, body = route_for("123", {"name": "github"}, url_iid="1924")
    check("forms/git_route (numeric story): the merge-request ref is still asked and answers", "the local checkout app" in note, note)
    # MY_PROJ-12: the prefix is MY_PROJ (the old regex read PROJ, and `--grep=PROJ-` also lists the commits of PROJ-99, another project)
    note, said, body = route_for("MY_PROJ-12", None, commits=("MY_PROJ-12 the story's change", "PROJ-99 another project's change"))
    check_in("forms/git_route (MY_PROJ-12): the story's own commit is listed", "MY_PROJ-12 the story's change", body)
    check_not_in("forms/git_route (MY_PROJ-12): the other project's commit is not (the prefix is MY_PROJ, whole)", "PROJ-99 another", body)
    check_not_in("forms/git_route (MY_PROJ-12): a prefix exists, so no line about skipping", "no project prefix", said)


def refusal_launch_warns_on_a_task_that_is_no_key() -> None:
    """B-405 R14: `--task` that is not a ticket key of the project's form prints ONE WARN naming the form, and the run
    goes on (a warning, never a refusal: P1); a proper key prints nothing."""
    def launch(task: str, ticket_cfg: dict | None = None) -> tuple:
        root, task_root, env = seed(task)
        try:
            if ticket_cfg is not None:
                cfg_path = root / "qa-factory" / "config.json"
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                cfg["adapters"]["ticket"].update(ticket_cfg)
                cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
            shown = io.StringIO()
            with contextlib.redirect_stdout(shown):
                driver = driver_for(root, env, task)
            return [ln for ln in shown.getvalue().splitlines() if ln.startswith("WARN: --task")], driver.task
        finally:
            harness.cleanup(root)

    lines, task = launch("QA-9")
    check_eq("launch/jira: a proper key prints no WARN", (lines, task), ([], "QA-9"))
    lines, task = launch("my_task")
    check_eq("launch/jira: a task that is no key prints exactly one WARN and the driver is built (the run goes on)",
             (len(lines), task), (1, "my_task"))
    check_in("launch/jira: ... naming the task and the form", "'my_task' is not a ticket key of this project: a ticket key like PROJ-123", lines[0])
    check_in("launch/jira: ... and that it goes on", "going on", lines[0])
    lines, task = launch("123", {"name": "github"})
    check_eq("launch/github: a number is a key", (lines, task), ([], "123"))
    lines, task = launch("QA-9", {"name": "github"})
    check_eq("launch/github: a Jira-shaped task is not, and the WARN names the numeric form", (len(lines), "like #123" in lines[0]), (1, True))


def refusal_person_words_kept_whole() -> None:
    """t-208 / FR-8: the driver writes a person's answer into the `human_answer` journal note, and every later
    brief reads that note as the person's standing instructions. Cut at 1,500 characters (cmp2, 01.10: the S1
    source-review answer, about 1,900 characters), the sentence at the END of an answer - the standing
    instruction - never reached a role. INVARIANT: a note carries the words whole up to
    `brief_pack.PERSON_WORDS_MAX`; a cut past it says so; the stage prefix and an empty answer stay as they were."""
    import brief_pack
    import story_run
    standing = "Standing for every role after this: never write to the tracker, Draft only."
    # 2,500 characters with a line break in the middle and the standing sentence last: the part a cut at
    # 1,500 loses is the part that matters
    body = "\n".join(f"line {n}: the review of this source is as written." for n in range(1, 41))
    words = (body + "\n" + "w" * (2500 - len(body) - len(standing) - 2) + " " + standing)
    check_eq("fixture: the answer is 2,500 characters and ends with the standing sentence",
             (len(words), words.endswith(standing)), (2500, True))

    root, task_root, env = seed("QA-9")
    try:
        driver = driver_for(root, env, "QA-9")
        inventory = driver.task_root / "work" / "source-inventory.json"
        inventory.parent.mkdir(parents=True, exist_ok=True)
        inventory.write_text(json.dumps({"schema_version": 1, "sources": []}), encoding="utf-8")
        real_py = driver.py

        def py(script, *args, **kwargs):
            # the review recording is the adapter's own business (proved elsewhere); the journal is real
            return (0, "") if script == "ticket_adapter.py" else real_py(script, *args, **kwargs)
        driver.py = py

        def answer(kind: str, stage: str, dispatch: str, text: str) -> None:
            driver.state["asked"] = {"kind": kind, "stage": stage, "dispatch": dispatch}
            driver.state_dir.mkdir(parents=True, exist_ok=True)
            (driver.state_dir / "driver-question.md").write_text("---\nkind: " + kind + "\n---\nQuestion?\n", encoding="utf-8")
            sent = root / "answer.md"
            sent.write_bytes(text.encode("utf-8"))
            driver.take_answer(sent)

        def notes() -> list:
            return [str(e.get("notes")) for e in jsonl(root / "qa-factory" / "records" / "journal.jsonl")
                    if e.get("event") == "human_answer"]

        # (1) the S1 source review
        answer("s1_review", "S1", "S1-qa-scout-1", words)
        check_in("the S1 review answer is in its human_answer note whole, after the stage prefix",
                 "S1 source review: " + words, notes())
        check_eq("and the driver's own answers file holds it whole too",
                 jsonl(driver.state_dir / "driver-answers.jsonl")[-1]["words"], words)
        _shown, _minimal, whole = brief_pack.decisions({}, "S2", "qa-case-designer", "QA-9", root)
        check_in("the standing sentence at its end is in the next brief's decisions side file",
                 standing, "\n".join(whole))
        check_in("with the whole answer beside it", "S1 source review: " + words, "\n".join(whole))

        # (2) a question stop: the answer keeps its lead words and goes whole
        stop_words = words.replace("line 1:", "stop line 1:", 1)
        answer("questions", "S2", "S2-qa-case-designer-1", stop_words)
        check_in("a question-stop answer is in its note whole, after `S2 question stop: `",
                 "S2 question stop: " + stop_words, notes())
        check_in("and its standing sentence reaches the side file too", "S2 question stop: " + stop_words,
                 "\n".join(brief_pack.decisions({}, "S3", "qa-case-designer", "QA-9", root)[2]))

        # (3) at and beyond the limit, through the real journal writer (one command-line argument)
        at_limit = "a" * brief_pack.PERSON_WORDS_MAX
        beyond = "b" * (brief_pack.PERSON_WORDS_MAX + 1000)
        answer("questions", "S2", "S2-qa-case-designer-1", at_limit)
        check_in("an answer at the limit is written untouched", "S2 question stop: " + at_limit, notes())
        answer("questions", "S2", "S2-qa-case-designer-1", beyond)
        cut = [n for n in notes() if n.startswith("S2 question stop: b")]
        check_eq("an answer beyond the limit is written once", len(cut), 1)
        check_in("and its cut says how much and where the whole text is",
                 "[cut: 1000 more characters, the whole text is in ", cut[0] if cut else "")
        check_eq("while the answers file keeps all of it",
                 jsonl(driver.state_dir / "driver-answers.jsonl")[-1]["words"], beyond)

        # (4) edges of the helper itself: a prefix with nothing after it is today's note, CRLF becomes LF
        check_eq("an empty answer is the prefix alone, as before", story_run._answer_note("S1: ", ""), "S1: ")
        check_eq("CRLF in an answer becomes LF in the note", story_run._answer_note("S1: ", "a\r\nb"), "S1: a\nb")
    finally:
        harness.cleanup(root)


# --- t-217 / F-cmp2-23: the role is resumed once per finding set, then the stand, then the person -----------------------
RES_DISPATCH = "S5-qa-automator-1"
# What cmp2's S5 automator answered with (cmp2-19): every case "blocked_by_env", the stand was down while it worked.
RES_DIGEST = ("qa-automator S5 TC-1 · concerns\nTC-1 · blocked_by_env · tests written, not run: stand down\n"
              "work/automation-manifest.json")
RES_PLAIN = "qa-automator S5 TC-1 · concerns\nTC-1 · ok · written and run\nwork/automation-manifest.json"


def res_errors(*names: str) -> list:
    """Exit-gate errors that carry the repair marker, the way s5_precheck words them (cmp2-19)."""
    import story_run
    return [f"s5_precheck.py: {name}: the review receipt is missing. {story_run.REPAIR_MARKER}" for name in names]


def res_fixture(task: str = "QA-9", digest: str = RES_DIGEST, *, environment="local"):
    """A seeded project with the role's saved result on disk, as `wait_existing_job` meets it on every entry."""
    root, task_root, env = seed(task)
    saved = task_root / "state" / "driver-runs" / f"{RES_DISPATCH}.json"
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_text(json.dumps({"session_id": "sess-a", "result": digest, "is_error": False, "exit_code": 0,
                                 "stderr": "", "num_turns": 3}), encoding="utf-8")
    d2_pipeline(task_root, environment=environment)
    set_control(root, {"resume": {"result": digest}})
    return root, task_root, env


def res_driver(root, env, task: str, errors: list, probe=(0, "liveness: alive - http://localhost:5173 -> HTTP 200")):
    """A driver over the same project whose exit gate answers `errors` and whose stand probe answers `probe`.
    (driver, the probe calls). `claude` is the stub: a resume is a `resume` line in the stub's log."""
    driver = driver_for(root, env, task)
    driver.state["sessions"][RES_DISPATCH] = "sess-a"
    driver.exit_errors = lambda role, digest, dispatch=None: list(errors)
    driver.form_errors = lambda dispatch: []
    driver.controller_state = lambda: {"dispatches": {RES_DISPATCH: {"stage": "S5", "role": "qa-automator",
                                                                      "scope": ["TC-1"]}}}
    real_py, probes = driver.py, []

    def py(script, *args, **kwargs):
        if script == "env_probe.py":
            probes.append([str(a) for a in args])
            return probe
        return real_py(script, *args, **kwargs)
    driver.py = py
    return driver, probes


def res_entry(driver):
    """One entry the way the loop makes it: `where` says wait_existing_job, the move runs under `guarded`.
    The Person it raised, or None."""
    import story_run
    action = {"action": "wait_existing_job", "dispatch_id": RES_DISPATCH, "stage": "S5"}
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            driver.guarded(lambda: driver.dispatch_action(action), action)
    except story_run.Person as person:
        return person
    return None


def refusal_resume_once_per_finding_set() -> None:
    """K1 (cmp2-19 replay): marked exit-gate errors over a saved result whose digest holds a `blocked_by_env` row,
    the stand probe answering. The handoff resumes the role (twice: every error is mechanical), the refusal that
    follows is answered by ONE stand resume, then the PERSON - never the conductor - and a second entry on a FRESH
    driver over the same saved result makes no role call at all. INVARIANTS: a role is never resumed twice for the
    same finding set on one dispatch+session, across entries and relaunches; the record is written BEFORE the paid
    call; the stand is looked at once per dispatch+session; a refusal of the CALL class never resumes a role."""
    import story_run
    task = "QA-9"
    errors = res_errors("TC-1", "TC-2")
    root, task_root, env = res_fixture(task)
    try:
        driver, probes = res_driver(root, env, task, errors)
        check_eq("entry 1: the handoff's resumes and the stand's end in a pass back to the loop", res_entry(driver), None)
        calls = stub_calls(root)
        check_eq("K1: handoff resumes twice (every error is mechanical) and one resume for the stand, nothing else",
                 [c["kind"] for c in calls], ["resume", "resume", "resume"])
        check_eq("the stand was probed once, with `--env` and `--task` (the tool stand_check uses)",
                 probes, [["--env", "local", "--task", task]])
        check_in("the third resume carries the probe's own words whole", "liveness: alive - http://localhost:5173 -> HTTP 200",
                 calls[2]["prompt"])
        check_in("and the refusal, whole", errors[0], calls[2]["prompt"])
        check_in("and the one sentence", "Repair the named fields in the artifact, change nothing else", calls[2]["prompt"])
        check_eq("and every resume is in the role's OWN session", {c["resume"] for c in calls}, {"sess-a"})
        record = json.loads((task_root / "state/driver-state.json").read_text(encoding="utf-8"))["refusal_resumes"]
        check_eq("the record is keyed by dispatch, then session, then the finding set; the stand is its last word",
                 (list(record), list(record[RES_DISPATCH]), sorted(set(record[RES_DISPATCH]["sess-a"].values()))),
                 ([RES_DISPATCH], ["sess-a"], ["stand"]))
        person = res_entry(driver)
        check("K1: the next pass over the same findings is the PERSON's", isinstance(person, story_run.Person), repr(person))
        if person:
            check_eq("it is the ONE seam's question (t-764: kind exit_limit) about the dispatch the refusal names", (person.kind, person.dispatch),
                     ("exit_limit", RES_DISPATCH))
            check_in("and the check's lines, whole, are beside it", errors[0], person.details)
            check_in("the closed answers are offered (t-764): the paid round", "`round`", person.text)
            check_in("the pass over the check", "`go on`", person.text)
            check_in("and the stop", "`stop`", person.text)
        check_eq("K1: no conductor call at all (cmp2-19.log:6 `conductor: retry - stand_health.py` is gone)",
                 d2_conductor_calls(root), [])
        before = len(stub_calls(root))
        fresh, fresh_probes = res_driver(root, env, task, errors)
        again = res_entry(fresh)
        check("K1: a second entry on a FRESH driver over the same saved result is the person's again",
              isinstance(again, story_run.Person), repr(again))
        check_eq("and makes no role call and no probe (the record is in the state file, not in memory)",
                 (len(stub_calls(root)) - before, fresh_probes), (0, []))

        # (d) the probe's answer is a fact, not a guess: it fails, or prints nothing -> the stand does not answer
        for label, probe in (("fails", (1, "connection refused")), ("crashes", None), ("prints nothing", (0, ""))):
            root2, task_root2, env2 = res_fixture(task)
            try:
                d2, p2 = res_driver(root2, env2, task, errors, probe=probe or (0, ""))
                if probe is None:
                    real = d2.py
                    d2.py = lambda script, *a, **k: (_ for _ in ()).throw(OSError("no such executable")) \
                        if script == "env_probe.py" else real(script, *a, **k)
                # C1-1: a stand that does not answer is a state the conductor has moves for (the stand, a restart), so the seam CALLS it
                # once (D11) - and its question, with options, is the person's; the probe's words travel in the details
                set_control(root2, {"resume": {"result": RES_DIGEST}, "conductor": seam_control()})
                person = res_entry(d2)
                check(f"a probe that {label}: the person, the conductor asked once, and the stand is not resumed on",
                      isinstance(person, story_run.Person)
                      and [c["kind"] for c in stub_calls(root2)] == ["resume", "resume", "conductor"], repr(person))
                if person:
                    check_in(f"a probe that {label}: its words are beside the refusal", "What the probe of the stand printed",
                             person.details)
                    check_in(f"a probe that {label}: and the conductor was shown them", "What the probe of the stand printed",
                             stub_calls(root2)[-1]["prompt"])
                state = json.loads((task_root2 / "state/driver-state.json").read_text(encoding="utf-8"))
                check(f"a probe that {label}: nothing is recorded as a stand resume",
                      "stand" not in set(state["refusal_resumes"][RES_DISPATCH]["sess-a"].values()))
            finally:
                harness.cleanup(root2)

        # no `blocked_by_env` row, or no stand: no probe at all (the clause needs the closed state word AND a stand)
        for label, digest, environment in (("no blocked row", RES_PLAIN, "local"), ("no environment", RES_DIGEST, None)):
            root2, task_root2, env2 = res_fixture(task, digest, environment=environment)
            try:
                d2, p2 = res_driver(root2, env2, task, errors)
                person = res_entry(d2)
                check(f"{label}: the person after the handoff's own resumes, and no probe was run",
                      isinstance(person, story_run.Person) and p2 == [], repr((person, p2)))
            finally:
                harness.cleanup(root2)
        # the saved result is gone (the stand clause reads it): no stand clause, the person
        root2, task_root2, env2 = res_fixture(task)
        try:
            d2, p2 = res_driver(root2, env2, task, errors)
            refusal = story_run.Refusal("exit gate for " + RES_DISPATCH + " (qa-automator, S5): " + errors[0],
                                        dispatch=RES_DISPATCH, findings=errors)
            d2.note_resume(RES_DISPATCH, "sess-a", story_run.finding_key(errors), "handoff")
            (task_root2 / "state/driver-runs" / f"{RES_DISPATCH}.json").unlink()
            try:
                d2.resume_on_refusal(refusal, "S5", RES_DISPATCH)
                check("an absent saved result: the person", False)
            except story_run.Person:
                check("an absent saved result: the person, and no probe", p2 == [] and stub_calls(root2) == [], repr(p2))
        finally:
            harness.cleanup(root2)
    finally:
        harness.cleanup(root)


def refusal_resume_record_edges() -> None:
    """The record's own edges (t-217 §1, C3): written BEFORE the paid call; keyed by dispatch AND session; an alternation
    A, B, A ends at the second A; no dispatch or no session is the person's with nothing called; an accepted finish
    drops the record; a refusal's finding key ignores an order, a repeated line and the dispatch id."""
    import story_run
    task = "QA-9"
    root, task_root, env = res_fixture(task, RES_PLAIN)
    refused = lambda lines: story_run.Refusal("exit gate for " + RES_DISPATCH + " (qa-automator, S5): " + "; ".join(lines),
                                              dispatch=RES_DISPATCH, findings=lines)
    a, b = res_errors("TC-1"), res_errors("TC-2")
    try:
        # the key is a set: order, repeats, whitespace and the dispatch id do not make a new finding
        k = story_run.finding_key
        check_eq("key: the same lines in another order, with a repeat and other whitespace, are one set",
                 k(["x  y", "a"]), k(["a", "x y", "a", "  "]))
        check_eq("key: a dispatch id inside a line is `<dispatch>` - the next dispatch's same finding is the same",
                 k(["S5-qa-code-critic-2 has gaps"]), k(["S5-qa-code-critic-3 has gaps"]))
        check("key: another line is another key", k(["a"]) != k(["b"]))
        check_eq("key: no lines, no key (an empty set is never equal to anything)", (k([]), k(["", "  "])), ("", ""))

        # the record is written BEFORE the paid call: a call that dies still counts as the one resume
        driver, _p = res_driver(root, env, task, a)
        calls = []
        driver.run_claude = lambda *args, **kw: calls.append(args) or (_ for _ in ()).throw(RuntimeError("the call died"))
        try:
            driver.resume_on_refusal(refused(a), "S5", RES_DISPATCH)
            check("(c) a dying call raises", False)
        except RuntimeError:
            pass
        fresh, _p = res_driver(root, env, task, a)
        check("the record was on disk before the call: a FRESH driver reads it", story_run.finding_key(a) in
              fresh.resume_record(RES_DISPATCH, "sess-a"), json.dumps(fresh.state.get("refusal_resumes")))
        check_eq("(c) record-before-call: why = refusal", fresh.resume_record(RES_DISPATCH, "sess-a").get(story_run.finding_key(a)),
                 "refusal")
        fresh.run_claude = lambda *args, **kw: calls.append(args) or {"result": "x"}
        try:
            fresh.resume_on_refusal(refused(a), "S5", RES_DISPATCH)
            check("record-before-call: the second try is the person's", False)
        except story_run.Person:
            check_eq("record-before-call: and no second call was made", len(calls), 1)
        # handoff's own resume: the same
        root2, task_root2, env2 = res_fixture(task, RES_PLAIN)
        try:
            driver, _p = res_driver(root2, env2, task, a)
            driver.run_claude = lambda *args, **kw: (_ for _ in ()).throw(RuntimeError("the call died"))
            result = json.loads((task_root2 / "state/driver-runs" / f"{RES_DISPATCH}.json").read_text(encoding="utf-8"))
            try:
                driver.handoff("qa-automator", "S5", RES_DISPATCH, result)
                check("(b) a dying handoff resume raises", False)
            except RuntimeError:
                pass
            fresh, _p = res_driver(root2, env2, task, a)
            fresh.run_claude = lambda *args, **kw: (_ for _ in ()).throw(AssertionError("a second resume"))
            try:
                fresh.handoff("qa-automator", "S5", RES_DISPATCH, result)
                check("(b) the findings are still refused", False)
            except story_run.Person as person:
                check_eq("(b) record-before-call: a fresh handoff over the same findings resumes nothing and goes to the ONE seam (t-764)",
                         (person.kind, person.dispatch, a[0] in person.details), ("exit_limit", RES_DISPATCH, True))
        finally:
            harness.cleanup(root2)

        # C3: a NEW session of the same dispatch gets its own one resume; the old session's record is untouched
        root3, task_root3, env3 = res_fixture(task, RES_PLAIN)
        try:
            driver, _p = res_driver(root3, env3, task, a)
            check_eq("C3: a first resume in session A returns to the loop", driver.resume_on_refusal(refused(a), "S5", RES_DISPATCH), "continue")
            try:
                driver.resume_on_refusal(refused(a), "S5", RES_DISPATCH)
                check("C3: the same findings in the same session are the person's", False)
            except story_run.Person:
                pass
            driver.state["sessions"][RES_DISPATCH] = "sess-b"      # question_rework, an interrupted call, ...: a new session
            before = len(stub_calls(root3))
            check_eq("C3: a new session of the same dispatch gets its own one resume",
                     driver.resume_on_refusal(refused(a), "S5", RES_DISPATCH), "continue")
            check_eq("C3: one call, in the new session", [c["resume"] for c in stub_calls(root3)[before:]], ["sess-b"])
            try:
                driver.resume_on_refusal(refused(a), "S5", RES_DISPATCH)
                check("C3: and only one", False)
            except story_run.Person:
                check_eq("C3: both sessions are on record, keyed apart", sorted(driver.state["refusal_resumes"][RES_DISPATCH]),
                         ["sess-a", "sess-b"])
            # alternation A, B, A ends at the second A (the saved result stays the plain digest: no stand clause here)
            driver, _p = res_driver(root3, env3, task, a)
            driver.state["sessions"][RES_DISPATCH] = "sess-c"
            calls = len(stub_calls(root3))
            outcomes = []
            for lines in (a, b, a):
                try:
                    outcomes.append(driver.resume_on_refusal(refused(lines), "S5", RES_DISPATCH))
                except story_run.Person:
                    outcomes.append("person")
            check_eq("alternation A, B, A: the role is resumed on A and on B, and the second A is the person's",
                     (outcomes, len(stub_calls(root3)) - calls), (["continue", "continue", "person"], 2))
            # a resume that answers with an error and no words: spent, and the person's
            driver, _p = res_driver(root3, env3, task, b)
            driver.state["sessions"][RES_DISPATCH] = "sess-d"
            driver.run_claude = lambda *args, **kw: {"result": "", "is_error": True, "stderr": "no such session", "session_id": ""}
            try:
                driver.resume_on_refusal(refused(b), "S5", RES_DISPATCH)
                check("a resume that returns an error and no words is the person's", False)
            except story_run.Person as person:
                check_in("it says the session could not be asked", "its session no longer answers", person.text)
                check_in("and keeps the resume's own error beside the refusal", "no such session", person.details)
                check("and the resume is on record as spent", story_run.finding_key(b) in driver.resume_record(RES_DISPATCH, "sess-d"))

            # no dispatch, or no session: the seam CALLS the conductor once (C1-1, D11: it has a restart for them) and its
            # question with options is the person's
            set_control(root3, {"resume": {"result": RES_PLAIN}, "conductor": seam_control()})
            before = len(stub_calls(root3))
            driver, _p = res_driver(root3, env3, task, a)
            driver.state["sessions"].pop(RES_DISPATCH)
            for label, refusal, want in (("no session", refused(a), ("exit_limit", 0)),      # t-764 E9: the dispatch is known - the one seam, no call
                                         ("no dispatch", story_run.Refusal("exit gate for X (qa-automator, S5): " + a[0], findings=a), ("refusal", 1))):
                try:
                    driver.resume_on_refusal(refusal, "S5", RES_DISPATCH if label == "no session" else "")
                    check(f"{label}: the person", False)
                except story_run.Person as person:
                    check_eq(f"{label}: the person, and the conductor was called {want[1]} time(s)",
                             (person.kind, len(stub_calls(root3)) - before), want)
                    before = len(stub_calls(root3))
                    driver.conductor_calls.clear()
        finally:
            harness.cleanup(root3)

        # an accepted finish drops the dispatch's record (state-exits.md); a refused one keeps it
        root4, task_root4, env4 = res_fixture(task, RES_PLAIN)
        try:
            driver, _p = res_driver(root4, env4, task, a)
            driver.note_resume(RES_DISPATCH, "sess-a", story_run.finding_key(a), "handoff")
            driver.py = lambda script, *args, **kw: (3, "story_step: refused") if script == "story_step.py" else (0, "")
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    driver.finish(RES_DISPATCH, RES_PLAIN, complete=False, role="qa-automator", stage="S5")
            except story_run.Refusal as refusal:
                check_eq("a finish that is refused names its dispatch in the field (FR-16)", refusal.dispatch, RES_DISPATCH)
            check("a refused finish keeps the record", RES_DISPATCH in driver.state["refusal_resumes"])
            driver.py = lambda script, *args, **kw: (0, "accepted x")
            with contextlib.redirect_stdout(io.StringIO()):
                driver.finish(RES_DISPATCH, RES_PLAIN, complete=False, role="qa-automator", stage="S5")
            check("an accepted finish drops it", RES_DISPATCH not in driver.state["refusal_resumes"]
                  and RES_DISPATCH not in json.loads((task_root4 / "state/driver-state.json").read_text(encoding="utf-8"))["refusal_resumes"])
        finally:
            harness.cleanup(root4)
    finally:
        harness.cleanup(root)


def refusal_exit_limit_routes() -> None:
    """EL9 / EL11 (t-764, C1-5d2): a NEW finding set after nothing was resumed is still resumed once and then a `Refusal`, as today (the
    seam is only for a set the role has already seen); the NEXT entry over the same set is the person's, through the one seam (kind
    `exit_limit`), asked once - no conductor call - and a finish refusal that survived the resume (E8) reaches the same seam."""
    import story_run
    task, lines = "QA-9", ["plain unmarked finding of the check"]
    root, task_root, env = res_fixture(task, RES_PLAIN)
    try:
        driver, _p = res_driver(root, env, task, lines)
        result = json.loads((task_root / "state/driver-runs" / f"{RES_DISPATCH}.json").read_text(encoding="utf-8"))
        before = len(stub_calls(root))
        try:
            driver.handoff("qa-automator", "S5", RES_DISPATCH, result)
            check("EL9: a new set is refused", False)
        except story_run.Refusal as refusal:
            check_eq("EL9: a NEW set gets its one free resume and is a Refusal as today", (refusal.findings, len(stub_calls(root)) - before), (lines, 1))
        except story_run.Person:
            check("EL9: a new set is NOT the seam's yet", False)
        try:
            driver.handoff("qa-automator", "S5", RES_DISPATCH, result)
            check("EL9: the same set the next entry is asked", False)
        except story_run.Person as person:
            check_eq("EL9: the next entry over the same set is the ONE seam's, with no further call",
                     (person.kind, len(stub_calls(root)) - before, d2_conductor_calls(root)), ("exit_limit", 1, []))
        refusal = story_run.Refusal(f"story_step finish {RES_DISPATCH} (exit 3):\nstory_step: left none of the outputs", dispatch=RES_DISPATCH,
                                    findings=["story_step: left none of the outputs"])
        driver.note_resume(RES_DISPATCH, "sess-a", story_run.finding_key(refusal.findings), "refusal")
        try:
            driver.resume_on_refusal(refusal, "S5", RES_DISPATCH)
            check("EL11/E8: a finish refusal that survived its resume is asked", False)
        except story_run.Person as person:
            check_eq("EL11/E8: it reaches the same seam, the refusal whole beside it", (person.kind, refusal.text in person.details), ("exit_limit", True))
    finally:
        harness.cleanup(root)


def refusal_exit_limit_order_the_mechanical_third_turn_runs_before_the_seam() -> None:
    """EL8 (t-764, t-698 §12.1 E5 / positional invariant P1): a NEW set whose every error is mechanical (carries the repair marker) gets its free
    resume AND the one more cheap turn that SHOWS the lines, and only then is a `Refusal` as today; the NEXT entry over the same set is the
    seam's, with no further call. The seam stands AFTER the third turn: a seam placed before it would ask the person while a cheap turn at the role
    was still owed."""
    import story_run
    task = "QA-9"
    errors = res_errors("TC-1", "TC-2")
    root, task_root, env = res_fixture(task, RES_PLAIN)
    try:
        driver, _p = res_driver(root, env, task, errors)
        result = json.loads((task_root / "state/driver-runs" / f"{RES_DISPATCH}.json").read_text(encoding="utf-8"))
        before = len(stub_calls(root))
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                driver.handoff("qa-automator", "S5", RES_DISPATCH, result)
            check("EL8: a new mechanical set is refused", False)
        except story_run.Refusal as refusal:
            calls = stub_calls(root)[before:]
            check_eq("EL8: the free resume AND the third cheap turn ran, then a Refusal as today", ([c["kind"] for c in calls], refusal.findings),
                     (["resume", "resume"], errors))
            check_in("EL8: the second turn is the one that SHOWS the lines", "Two things and nothing else", calls[1]["prompt"])
        except story_run.Person:
            check("EL8: the seam is NOT reached before the third turn", False)
        after = len(stub_calls(root))
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                driver.handoff("qa-automator", "S5", RES_DISPATCH, result)
            check("EL8: the same set the next entry is asked", False)
        except story_run.Person as person:
            check_eq("EL8: THEN the seam, with no further call", (person.kind, len(stub_calls(root)) - after), ("exit_limit", 0))
    finally:
        harness.cleanup(root)


def refusal_call_class_stays_with_the_conductor() -> None:
    """C10 (FR-46): a refusal of the CALL class carries the marker too, but it is the driver's own mistake - the role is
    never resumed for it - and the head is matched ANCHORED: a text that only quotes `exit gate for <id>` further down
    is not that refusal. Only `exit gate for <id>` and `story_step finish <id> (exit 3)` take the role's own resume."""
    import story_run
    task = "QA-9"
    root, task_root, env = res_fixture(task, RES_PLAIN)
    marker = story_run.REPAIR_MARKER
    try:
        heads = [
            ("finish exit 2, --unresolved without --reason",
             "story_step finish " + RES_DISPATCH + " (exit 2):\nstory_step: finish got --unresolved without --reason. "
             + marker + ": repeat the call with both.", False),
            ("finish exit 2, no dispatch",
             "story_step finish " + RES_DISPATCH + " (exit 2):\nstory_step: no dispatch " + RES_DISPATCH
             + " in this story. " + marker + ": name one of them.", False),
            ("a text that only quotes the exit-gate head",
             "conductor note: exit gate for " + RES_DISPATCH + " (qa-automator, S5): " + marker, False),
            ("a text that quotes the finish head on its second line",
             "controller: refused\nstory_step finish " + RES_DISPATCH + " (exit 3): " + marker, False),
            ("the exit gate of a dispatch", "exit gate for " + RES_DISPATCH + " (qa-automator, S5): x. " + marker, True),
            ("finish exit 3 (the handover form)",
             "story_step finish " + RES_DISPATCH + " (exit 3):\nstory_step: the handover form is not complete - x\n  "
             + marker + ".", True),
        ]
        for number, (label, text, resumes) in enumerate(heads, 1):
            check_eq(f"{label}: the anchored head reads {'a dispatch' if resumes else 'nothing'}",
                     bool(story_run.Driver.resumable_head(text)), resumes)
            set_control(root, {"resume": {"result": RES_PLAIN}, "conductor": {"action": "continue", "did": "stub"}})
            before = len(stub_calls(root))
            driver, _p = res_driver(root, env, task, [])
            driver.state["sessions"][RES_DISPATCH] = f"sess-{number}"      # a session of its own: a clean record
            driver.state.pop("window_rounds", None)       # the cap of a window's rounds is not what is under test here
            driver.boundary = "S5:" + RES_DISPATCH
            with contextlib.redirect_stdout(io.StringIO()):
                outcome = driver.handle_refusal(story_run.Refusal(text, dispatch=RES_DISPATCH))
            kinds = [c["kind"] for c in stub_calls(root)[before:]]
            check_eq(f"{label}: {'the role is resumed, not the conductor' if resumes else 'the conductor, never a resume'}",
                     (outcome, kinds), ("continue", ["resume"]) if resumes else ("continue", ["conductor"]))
    finally:
        harness.cleanup(root)


def refusal_resumed_halt_is_heard() -> None:
    """The role's answer to a refusal-resume may be a halt (it cannot go on). `wait_existing_job` finishes the saved result,
    and `finish` would close the dispatch over a halt: the halt is heard first, as `run_role` hears it."""
    import story_run
    task = "QA-9"
    halting = "qa-automator S5 TC-1 · halt\nTC-1 · unresolved · cannot go on without the stand\nwork/automation-manifest.json"
    root, task_root, env = res_fixture(task, halting)
    try:
        driver, _p = res_driver(root, env, task, [])
        finished, done = [], []
        driver.finish = lambda *a, **k: finished.append(a)
        real = driver.py
        driver.py = lambda script, *a, **k: done.append(a) or (0, "") if script == "stage_done.py" else real(script, *a, **k)
        person = res_entry(driver)
        check("a halting saved result is the person's, not finished", isinstance(person, story_run.Person) and finished == [],
              repr((person, finished)))
        if person:
            check_eq("as a halt about the dispatch", (person.kind, person.dispatch), ("halt", RES_DISPATCH))
        check("and the stage is recorded halted", any("halted" in a for a in done), repr(done))
        # a result that does not halt is finished as before
        root2, task_root2, env2 = res_fixture(task, RES_PLAIN)
        try:
            driver, _p = res_driver(root2, env2, task, [])
            finished = []
            driver.finish = lambda *a, **k: finished.append(a)
            check_eq("a plain result is finished", (res_entry(driver), len(finished)), (None, 1))
        finally:
            harness.cleanup(root2)
    finally:
        harness.cleanup(root)


# --- t-217 / F-cmp2-22: whose answer it is - the field, never an id quoted in the text -----------------------------------
def refusal_answer_filed_by_the_field() -> None:
    """K3: cmp2-18.log:9 ("the answer is filed for S2-qa-requirements-tester-1, named by the refusal itself" - a gate-A
    packet quoting the S2 handoff) and cmp2-26.log:4 ("filed for <critic, named by the refusal itself" - a placeholder in a
    probe's hint). INVARIANTS: a gate answer is never filed to a dispatch; for the questions a refusal raises the field
    (`asked.dispatch`) decides and the text is never read; a question an OLDER driver asked (no `blocks` key) keeps the
    text reading, but a capture counts only when it is a dispatch id by shape and the only one; when unsure the words are
    filed to NO dispatch."""
    task = "QA-9"
    root, task_root, env = seed(task)
    try:
        driver = driver_for(root, env, task)
        driver.judged_reply = lambda *a, **k: ""
        conductor = []
        driver.conductor = lambda text, *, words="", files=None, words_file=None: conductor.append(words) or {"action": "continue", "did": "stub"}
        driver.record_by_code = recording_stub()

        def answer(asked: dict, qtext: str, words: str = "go on, I read it") -> str:
            driver.state["asked"] = dict(asked)
            driver.state["pending_words"] = {}
            driver.state.pop("gate_answer_kept", None)
            driver.state_dir.mkdir(parents=True, exist_ok=True)
            (driver.state_dir / "driver-question.md").write_text(qtext, encoding="utf-8")
            sent = root / "answer.md"
            sent.write_bytes(words.encode("utf-8"))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                driver.take_answer(sent)
            return out.getvalue()

        quoted = ("# Driver question\nkind: gate_A\n---\nGate A. Accept the S2 handoff of S2-qa-requirements-tester-1 "
                  "and run --dispatch S2-qa-requirements-tester-1 now.\n")      # a spelling the legacy text reading WOULD file
        said = answer({"kind": "gate_A", "stage": "S4", "dispatch": ""}, quoted, "approve\ngo on, I read it")     # C1-4b: an approval is its first-line word
        check_eq("K3: a gate-A answer files nothing (cmp2-18.log:9)", driver.state["pending_words"], {})
        check_in("and says so", "gate A: the answer is recorded by code and filed for no dispatch", said)
        check_not_in("the old line is gone", "named by the refusal itself", said)
        driver.record_by_code = recording_stub(False)       # the decision did not record
        said = answer({"kind": "gate_B", "stage": "S8", "dispatch": ""}, quoted.replace("gate_A", "gate_B"), "approve\ngo on, I read it")
        check_eq("a gate answer the controller did not record is kept for the gate and still filed nowhere",
                 (driver.state["pending_words"], bool(driver.state.get("gate_answer_kept"))), ({}, True))
        check_in("said as it is", "gate B: the answer is kept for the gate and filed for no dispatch", said)
        driver.record_by_code = recording_stub()

        question = "# Driver question\nkind: refusal\n---\nrun `--dispatch S5-qa-code-critic-9` or see \"dispatch_id\": \"S5-qa-automator-4\"\n"
        said = answer({"kind": "refusal", "stage": "S5", "dispatch": "S5-qa-code-critic-2", "blocks": []}, question)
        check_eq("the field decides, and a text with two other ids is never read",
                 driver.state["pending_words"], {"S5-qa-code-critic-2": "go on, I read it"})
        check_in("said as it is", "the answer is filed for S5-qa-code-critic-2, the dispatch the question is about", said)
        for kind in ("conductor", "refusal"):
            answer({"kind": kind, "stage": "S5", "dispatch": "S5-qa-code-critic-2", "blocks": []}, question)
            check_eq(f"kind {kind} files by the field", list(driver.state["pending_words"]), ["S5-qa-code-critic-2"])
        # cmp2-26.log:4: the body of the question holds a REAL `--dispatch S5-qa-code-critic-2` (the controller's text), the
        # field is empty and the key is there: nothing is filed
        said = answer({"kind": "conductor", "stage": "S5", "dispatch": "", "blocks": []},
                      "# q\n---\nLast refusal: use `--dispatch S5-qa-code-critic-2` to rebuild\n")
        check_eq("K3: a question of this driver that names no dispatch files nothing, whatever its text quotes (cmp2-26.log:4)",
                 driver.state["pending_words"], {})
        check_in("and says so", "the answer is filed for no dispatch: the question names none", said)
        # an OLDER driver's question: the text, with the shape check
        for label, text, expected in (
                ("a placeholder", "run `--dispatch <critic id>` first", {}),
                ("the `dispatch_id` key with an id", 'the packet {"dispatch_id": "S5-qa-code-critic-7"}', {"S5-qa-code-critic-7": "go on, I read it"}),
                ("the command with an id", "run --dispatch S5-qa-code-critic-7 again", {"S5-qa-code-critic-7": "go on, I read it"}),
                ("two different ids", '"dispatch_id": "S5-qa-code-critic-7" and --dispatch S5-qa-automator-2', {}),
                ("the same id twice", '"dispatch_id": "S5-qa-code-critic-7" and --dispatch S5-qa-code-critic-7',
                 {"S5-qa-code-critic-7": "go on, I read it"}),
                ("an id only in the body (the bare third spelling is gone)", "the refusal is about S5-qa-code-critic-7 only", {})):
            answer({"kind": "refusal", "stage": "S5", "dispatch": ""}, "# q\n---\n" + text + "\n")
            check_eq(f"older driver, {label}", driver.state["pending_words"], expected)
        # boundaries that name no dispatch by shape
        for boundary in ("S0:ticket", "gate_A", "S5:TC-1,TC-2", "S5:environment:job-1", "where", "start"):
            driver.boundary = boundary
            check_eq(f"boundary `{boundary}` names no dispatch", driver.boundary_dispatch(), "")
        for boundary in ("S5:S5-qa-code-critic-2", "S5:S5-qa-code-critic-2:resume", "S5:S5-qa-code-critic-2:answer"):
            driver.boundary = boundary
            check_eq(f"boundary `{boundary}` names one", driver.boundary_dispatch(), "S5-qa-code-critic-2")
    finally:
        harness.cleanup(root)


def refusal_persons_carry_their_dispatch() -> None:
    """C9: every Person raised from a refusal carries the dispatch as a field - the refusal's own, else the boundary's - and
    every raise site that knows its dispatch passes it; `ask()` writes it, and writes `blocks` for the kinds that carry
    named blocks (an empty list until the parser of t-228 lands)."""
    import story_run
    task = "QA-9"
    root, task_root, env = seed(task)
    try:
        driver = driver_for(root, env, task)
        budget = "stage_done: STORY BUDGET: QA-9 is past its ceiling"
        for label, refusal, boundary, expected in (
                ("the refusal's field", story_run.Refusal(budget, dispatch="S5-qa-code-critic-2"), "S5:TC-1", "S5-qa-code-critic-2"),
                ("the field outranks the boundary", story_run.Refusal(budget, dispatch="S5-qa-code-critic-2"),
                 "S5:S5-qa-automator-1", "S5-qa-code-critic-2"),
                ("the boundary when there is no field", story_run.Refusal(budget), "S5:S5-qa-automator-1", "S5-qa-automator-1"),
                ("neither", story_run.Refusal(budget), "S5:TC-1,TC-2", "")):
            driver.boundary = boundary
            try:
                driver.handle_refusal(refusal)
                check(f"{label}: a known `ask_person` row raises", False)
            except story_run.Person as person:
                check_eq(f"{label}: the Person carries it", person.dispatch, expected)
        # the conductor's cap
        driver.boundary = "S5:S5-qa-code-critic-2"
        driver.conductor_calls[driver.boundary] = story_run.CONDUCTOR_CALLS_PER_BOUNDARY
        # (C1-1: `conductor()` raises ConductorSpent, which only the seam catches; the seam's answer at the cap is the priced
        # fallback question, never the old "What should happen?" text)
        try:
            driver.conductor("some refusal")
            check("the cap raises", False)
        except story_run.ConductorSpent as spent:
            check_eq("the cap is a ConductorSpent that counts the calls", spent.count, story_run.CONDUCTOR_CALLS_PER_BOUNDARY)
        try:
            driver.no_move({"why": "refusal", "kind": "conductor", "stage": "S5", "dispatch": driver.boundary_dispatch(),
                            "text": "some refusal"})
            check("the cap raises", False)
        except story_run.Person as person:
            check_eq("the cap's Person carries the boundary's dispatch", person.dispatch, "S5-qa-code-critic-2")
            check_eq("and offers the three standing answers", list(person.offered), ["retry", "go on", "stop"])
            check_not_in("and not the old text", "What should happen?", person.text)
            check_in("with their price lines", "the factory:", person.text)
        # ask() writes the field, and the blocks key for the two kinds
        driver.ask(story_run.Person("refusal", "A question that is long enough to be a real question for a person, with "
                                    "words in it.", "S5", "S5-qa-code-critic-2"))
        check_eq("ask(): asked carries the dispatch and an empty `blocks` list (refusal)",
                 (driver.state["asked"]["dispatch"], driver.state["asked"]["blocks"]), ("S5-qa-code-critic-2", []))
        driver.ask(story_run.Person("conductor", "A question that is long enough to be a real question for a person, with "
                                    "words in it.", "S5", "S5-qa-code-critic-2"))
        check_eq("ask(): the same for conductor", driver.state["asked"]["blocks"], [])
        driver.ask(story_run.Person("retro", "A question that is long enough to be a real question for a person, with "
                                    "words in it.", "S9"))
        check("ask(): no `blocks` key for a kind that carries none", "blocks" not in driver.state["asked"])
        # raise sites that know their dispatch pass it
        action = {"action": "resume_checkpoint", "dispatch_id": "S5-qa-code-critic-2"}
        driver.state["sessions"]["S5-qa-code-critic-2"] = "sess-x"      # a dispatch this driver launched: wait_existing_job refuses
        driver.py = lambda script, *a, **k: (0, "")                      # (and resume_role's `stage_done` is not what is under test)
        for kind in ("resume_checkpoint", "resolve_return", "wait_existing_job"):
            try:
                driver.dispatch_action(dict(action, action=kind))
                check(f"{kind}: refuses", False)
            except story_run.Refusal as refusal:
                check_eq(f"{kind}: the Refusal carries its dispatch", refusal.dispatch, "S5-qa-code-critic-2")
        try:
            driver.resume_role("S5", "qa-code-critic", "S5-qa-code-critic-8", "go on")
            check("resume_role with no session refuses", False)
        except story_run.Refusal as refusal:
            check_eq("resume_role: the Refusal carries its dispatch", refusal.dispatch, "S5-qa-code-critic-8")
    finally:
        harness.cleanup(root)


# --- t-261: the fix wave after the critic of t-225 (spec t-217 section 0d): O1 and O2 --------------------------------------
def refusal_o1_the_handoffs_own_resumes_are_the_saved_result() -> None:
    """O1 (critic t-244): `handoff` resumes the role in its own session (`again`, then `third` when every error is
    mechanical) and used to leave `state/driver-runs/<dispatch>.json` holding the FIRST result. After a conductor
    `continue` on the open dispatch, `wait_existing_job` re-judged that stale result, found its finding set already in
    `refusal_resumes`, and raised a false "came back with the same findings" question. Now each resume's non-empty result
    is the saved one (an empty error result is never written: `resume_with`'s rule) and the second entry judges THAT."""
    import story_run
    task = "QA-9"
    marked = lambda *names: res_errors(*names)
    plain = lambda *names: [f"exit gate said: row {n} has no review receipt" for n in names]
    second = RES_PLAIN.replace("written and run", "written and run: second words")
    third = RES_PLAIN.replace("written and run", "written and run: third words")

    def fixture(results, errors_by_marker):
        root, task_root, env = res_fixture(task)
        set_control(root, {"resume": {"result": results}})
        driver = driver_for(root, env, task)
        driver.state["sessions"][RES_DISPATCH] = "sess-a"
        driver.exit_errors = lambda role, digest, dispatch=None: next((e for m, e in errors_by_marker if m in digest), [])
        driver.form_errors = lambda dispatch: []
        return root, task_root, driver

    def saved_of(task_root):
        return json.loads((task_root / "state" / "driver-runs" / f"{RES_DISPATCH}.json").read_text(encoding="utf-8"))

    def handoff(driver, task_root):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                return driver.handoff("qa-automator", "S5", RES_DISPATCH, saved_of(task_root)), None
            except story_run.Refusal as refusal:
                return None, refusal

    # (1) one resume that repairs: the saved result is the resumed one, with the session the dispatch had
    root, task_root, driver = fixture([second], [("blocked_by_env", plain("TC-1"))])
    try:
        before = saved_of(task_root)
        digest, refusal = handoff(driver, task_root)
        check_eq("O1: the resume repaired the handoff", (refusal, "second words" in (digest or "")), (None, True))
        saved = saved_of(task_root)
        check_in("O1: the saved result IS the resumed one (the killed mutation: it stayed the first)", "second words", saved["result"])
        check_eq("O1: ...with the session id the dispatch had", saved["session_id"], before["session_id"])
        check_eq("O1: ...and one resume was spent", [c["kind"] for c in stub_calls(root)], ["resume"])
    finally:
        harness.cleanup(root)
    # (2) two resumes (every error is mechanical): the saved result is the LAST one
    root, task_root, driver = fixture([second, third], [("blocked_by_env", marked("TC-1")), ("second words", marked("TC-2"))])
    try:
        digest, refusal = handoff(driver, task_root)
        check_eq("O1: the second resume repaired it", (refusal, "third words" in (digest or "")), (None, True))
        check_in("O1: the saved result is the THIRD words, not the second and not the first", "third words", saved_of(task_root)["result"])
        check_eq("O1: two resumes were spent", [c["kind"] for c in stub_calls(root)], ["resume", "resume"])
    finally:
        harness.cleanup(root)
    # (3) an EMPTY result is never written: the first result stands byte for byte
    root, task_root, driver = fixture([""], [("blocked_by_env", marked("TC-1"))])
    try:
        path = task_root / "state" / "driver-runs" / f"{RES_DISPATCH}.json"
        held = path.read_bytes()
        digest, refusal = handoff(driver, task_root)
        check("O1: nothing repaired it: a refusal", refusal is not None)
        check_eq("O1: an empty resume result is not written - the saved result is byte for byte the first", path.read_bytes(), held)
    finally:
        harness.cleanup(root)
    # (4) the session the resume reports none for stays the dispatch's own
    root, task_root, driver = fixture([second], [])
    try:
        driver.keep_resumed_result(RES_DISPATCH, {"result": "words", "session_id": ""}, {"session_id": "sess-a"})
        check_eq("O1: a resume that reports no session keeps the one before (a result with no session cannot be resumed again)",
                 (saved_of(task_root)["session_id"], saved_of(task_root)["result"]), ("sess-a", "words"))
        driver.keep_resumed_result(RES_DISPATCH, {"result": "  ", "session_id": "sess-b"}, {"session_id": "sess-a"})
        check_eq("O1: a blank result writes nothing", saved_of(task_root)["result"], "words")
    finally:
        harness.cleanup(root)
    # (5) the SECOND entry judges the new result: the resume answered with other findings; a fresh driver (the loop
    # came back after a conductor `continue`) must see THOSE, not the set the record says was already resumed on
    first_set, new_set = plain("TC-1"), plain("TC-2", "TC-3")
    root, task_root, driver = fixture([second], [("blocked_by_env", first_set), ("second words", new_set)])
    try:
        digest, refusal = handoff(driver, task_root)
        check_eq("O1: the resume came back with OTHER findings: the handoff is refused over those", refusal.findings if refusal else None, new_set)
        again = driver_for(root, env_of(root), task)
        again.state["sessions"][RES_DISPATCH] = "sess-a"
        again.exit_errors = driver.exit_errors
        again.form_errors = lambda dispatch: []
        digest, refusal = handoff(again, task_root)
        check_eq("O1: the next entry (a fresh driver over the saved result) judges the NEW result: its findings are the new set, "
                 "not the first set the record already holds (the false `same findings`)",
                 refusal.findings if refusal else None, new_set)
        check("O1: and nothing in that refusal is the first set", not refusal or not any(line in refusal.text for line in first_set))
    finally:
        harness.cleanup(root)


def env_of(root):
    """The environment `driver_for` needs, rebuilt from the project's own stub files."""
    return dict(os.environ, CLAUDE_PROJECT_DIR=str(root), STORY_RUN_CLAUDE=str(root / "fake_claude.py"),
                STUB_CONTROL=str(root / "stub-control.json"), STUB_LOG=str(root / "stub-log.jsonl"))


def refusal_o2_the_text_reading_is_for_the_two_refusal_kinds_only() -> None:
    """O2 (critic t-244): the fallback that reads a dispatch out of an OLDER question's text ran for any kind with no
    `blocks` key. An `environment` question with no dispatch that quotes `--dispatch S6-qa-test-runner-1` in its own
    words then filed the person's answer to that runner (the killed mutation). It now runs only for `conductor` and
    `refusal`, and only when there is no `blocks` key."""
    task = "QA-9"
    root, task_root, env = seed(task)
    try:
        driver = driver_for(root, env, task)
        driver.judged_reply = lambda *a, **k: ""
        driver.conductor = lambda text, *, words="", files=None, words_file=None: {"action": "continue", "did": "stub"}
        driver.record_by_code = recording_stub()

        def answer(asked: dict, qtext: str, words: str = "go on, I read it") -> str:
            driver.state["asked"] = dict(asked)
            driver.state["pending_words"] = {}
            driver.state.pop("gate_answer_kept", None)
            driver.state_dir.mkdir(parents=True, exist_ok=True)
            (driver.state_dir / "driver-question.md").write_text(qtext, encoding="utf-8")
            sent = root / "answer.md"
            sent.write_bytes(words.encode("utf-8"))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                driver.take_answer(sent)
            return out.getvalue()

        text = ("# Driver question\n---\nThe stand did not answer. Last run: python x.py --dispatch S6-qa-test-runner-1 "
                "and \"dispatch_id\": \"S6-qa-test-runner-1\".\n")
        for kind, words in (("environment", "go on, I read it"), ("package", "go on")):
            said = answer({"kind": kind, "stage": "S6", "dispatch": ""}, text, words)
            check_eq(f"O2: kind `{kind}`, no dispatch, no `blocks` key: the words are filed to NO dispatch (the quoted runner id is never read)",
                     driver.state["pending_words"], {})
            check_in(f"O2: kind `{kind}`: and it says so", "the answer is filed for no dispatch: the question names none", said)
            check_not_in(f"O2: kind `{kind}`: the old line is gone", "named by the refusal itself", said)
        # the two kinds an older driver raised from a refusal keep the reading (with its shape check), and only with no `blocks` key
        for kind in ("conductor", "refusal"):
            said = answer({"kind": kind, "stage": "S5", "dispatch": ""}, "# q\n---\nrun --dispatch S5-qa-code-critic-7 again\n")
            check_eq(f"O2: kind `{kind}` of an older driver (no `blocks` key) still files by the text",
                     driver.state["pending_words"], {"S5-qa-code-critic-7": "go on, I read it"})
            check_in(f"O2: kind `{kind}`: said as before", "the answer is filed for S5-qa-code-critic-7, named by the refusal itself", said)
            answer({"kind": kind, "stage": "S5", "dispatch": "", "blocks": []}, "# q\n---\nrun --dispatch S5-qa-code-critic-7 again\n")
            check_eq(f"O2: kind `{kind}` WITH the `blocks` key never reads the text", driver.state["pending_words"], {})
    finally:
        harness.cleanup(root)


def refusal_t667_take_answer_branches_no_other_file_reaches() -> None:
    """t-667 D14 (characterisation BEFORE the move, green on the unmodified tree): the branches of `take_answer` whose bodies move
    into helpers and that the rest of the rig never ran in this process - the S0 block, the S1 exit gate (a condition with a side
    effect, a reassigned `dispatch`), the stand and stand-login answers. INVARIANT: each runs exactly when it runs today, with
    its side effects in today's order, and the answer is cleared last."""
    import story_run
    task = "QA-9"
    root, task_root, env = seed(task)
    try:
        driver = driver_for(root, env, task)
        real_py = driver.py
        waiver = {"code": 0}
        seen = []

        def py(script, *args, **kwargs):
            if script == "waiver.py":
                seen.append(list(args))
                return waiver["code"], "waiver said no"
            return real_py(script, *args, **kwargs)
        driver.py = py

        def notes() -> list:
            return [str(e.get("notes")) for e in jsonl(root / "qa-factory" / "records" / "journal.jsonl")
                    if e.get("event") == "human_answer"]

        def answer(kind: str, stage: str, dispatch: str, text: str) -> str:
            driver.state["asked"] = {"kind": kind, "stage": stage, "dispatch": dispatch}
            driver.state["pending_words"] = {}
            driver.state_dir.mkdir(parents=True, exist_ok=True)
            (driver.state_dir / "driver-question.md").write_text("---\nkind: " + kind + "\n---\nQuestion?\n", encoding="utf-8")
            sent = root / "answer.md"
            sent.write_bytes(text.encode("utf-8"))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                try:
                    driver.take_answer(sent)
                except story_run.Person as held:      # C1-6b: a pass the waiver refused is the seam's held question, raised after the line is printed
                    held_questions.append(held.text)
            return out.getvalue()

        held_questions = []

        # (1) the S0 block: the words wait for the next S0 step, no conductor
        driver.state["s0_block"] = "source_list"
        said = answer("halt", "S0", "", "skip the vendor docs")
        check_eq("t667 S0 block: the words wait under `S0`", driver.state["pending_words"], {"S0": "skip the vendor docs"})
        check_eq("t667 S0 block: the journal note names the block", notes()[-1], "S0 source_list: skip the vendor docs")
        check_in("t667 S0 block: and the line says so", "S0 source_list: the answer is kept and read in the next S0 step", said)
        check_eq("t667 S0 block: the question is cleared last", driver.state["asked"], {})
        driver.state.pop("s0_block")

        # (2) the S1 exit gate: the condition runs `s1_exit_gate`, then `record_s1`, then the branch asks `s1_exit_gate` again for the
        # dispatch (E3/E4); the words are filed to THAT dispatch even when the question named none
        order = []
        driver.s1_exit_gate = lambda qtext: (order.append("s1_exit_gate"), "S1-qa-scout-1")[1]
        driver.record_s1 = lambda qtext, words: (order.append("record_s1"), True)[1]
        said = answer("conductor", "S1", "", "the review is fine")
        check_eq("t667 S1 exit gate: the condition, the recording, then the dispatch", order, ["s1_exit_gate", "record_s1", "s1_exit_gate"])
        check_eq("t667 S1 exit gate: the words are filed to the exit gate's dispatch", driver.state["pending_words"],
                 {"S1-qa-scout-1": "the review is fine"})
        check_eq("t667 S1 exit gate: and the answer row names that dispatch", jsonl(driver.state_dir / "driver-answers.jsonl")[-1]["dispatch"],
                 "S1-qa-scout-1")
        del driver.s1_exit_gate, driver.record_s1
        driver._answer_s1_gap = lambda words, asked, qtext, stage, dispatch: True      # C2-9: the answer's executor (record_gaps stands behind it)
        answer("s1_gap", "S1", "S1-qa-scout-1", "the gaps are as listed")
        check_eq("t667 S1 gap: a recorded gap answer is filed for its dispatch", driver.state["pending_words"],
                 {"S1-qa-scout-1": "the gaps are as listed"})
        del driver._answer_s1_gap

        # (3) the stand question: `go on` whose pass the waiver refuses is said, nothing is journaled, the flag is spent
        waiver["code"] = 1
        driver.state["stand_question"] = "S5"
        before = len(notes())
        said = answer("environment", "S5", "", "go on")
        check_in("t667 stand: a pass that was not recorded is said with the end of the refusal",
                 "S5: the pass was not recorded (waiver said no); the question comes back", said)
        check_eq("t667 stand: the seam journals the person's words once (C1-6b), the held question comes back", (len(notes()) - before, held_questions[-1].startswith("Your word could not be recorded as the pass")), (1, True))
        check("t667 stand: the flag is spent", "stand_question" not in driver.state, str(driver.state.get("stand_question")))

        # (4) the stand-login question: three readings, each with its executor
        waiver["code"] = 0
        driver.state["login_question"] = True
        said = answer("stand_login", "S6", "", "retry")
        check_in("t667 login retry: the line (the seam's `person_does`)", "S6: nothing is passed; the step runs again", said)
        check_eq("t667 login retry: the journal note", notes()[-1], "S6 (retry): retry")
        check("t667 login retry: the flag is spent", "login_question" not in driver.state)
        seen.clear()
        driver.state["login_question"] = True
        said = answer("stand_login", "S6", "", "by hand")
        # RN1-9 B1 (t-767, `Driver.waiver_road`): the call ends `--words-file <path> --by driver` (no `--why-person`: no class was asked
        # here); the path is the one varying element, dropped
        check_eq("t667 login by hand: ONE waiver, stage S6, the login block, the person's words by FILE (C1-6b: no inline --decision), on the driver road",
                 [call[:-3] + call[-2:] for call in seen],
                 [["--task", task, "--stage", "S6", "--block", driver.STAND_LOGIN_BLOCK, "--words-file", "--by", "driver"]])
        check_in("t667 login by hand: the line (the seam's `go_on_as_is`)", "S6: going on on the person's word; recorded", said)
        check_eq("t667 login by hand: the journal note", notes()[-1], "S6 (by hand): by hand")
        waiver["code"] = 1
        before = len(notes())
        driver.state["login_question"] = True
        said = answer("stand_login", "S6", "", "go on")
        check_in("t667 login go on, refused: said with the end of the refusal",
                 "S6: the pass was not recorded (waiver said no); the question comes back", said)
        check_eq("t667 login go on, refused: the seam journals the words once, the pass is not written", len(notes()) - before, 1)
        check_eq("t667: every answer above was cleared but the refused pass: its question is held (C1-6b)", driver.state["asked"],
                 {"kind": "stand_login", "stage": "S6", "dispatch": ""})
        check("t667: the story_run module the check read is the one under test", story_run.Driver is type(driver))
    finally:
        harness.cleanup(root)


def refusal_t667_dispatch_action_branches_no_other_file_reaches() -> None:
    """t-667 D15 (characterisation BEFORE the move): the branches of `dispatch_action` that move into one handler per kind and
    that the rest of the rig never ran in this process - S0, a halt that was asked, the liveness text of a failed read,
    `resolve_return` with the person's words and without them, and a kind the driver has no move for. INVARIANT: every
    path that returns today returns; an action with no move reaches the final `Refusal`."""
    import dispatch_liveness
    import story_run
    task = "QA-9"
    root, task_root, env = seed(task)
    dispatch = "S5-qa-test-runner-1"
    try:
        driver = driver_for(root, env, task)
        driver.controller_state = lambda: {"dispatches": {dispatch: {"stage": "S5", "role": "qa-test-runner"}}}
        driver.completion_for = lambda stage, role, record: "COMPLETE"
        made = []

        # (1) S0: a pipeline.json already there closes S0 by code; none there starts S0
        driver.code_only = lambda *args, **kwargs: made.append(("code_only", args))
        driver.s0 = lambda: made.append(("s0",))
        driver.dispatch_action({"action": "prepare_stage", "stage": "S0"})
        check_eq("t667 S0 with a pipeline.json: closed by code, the boundary is S0",
                 (made, driver.boundary), ([("code_only", ("S0", "preflight green: S0 closed on a task initialized before it", ["pipeline.json"]))], "S0"))
        made.clear()
        pipeline = task_root / "pipeline.json"
        kept = pipeline.read_bytes()
        pipeline.unlink()
        try:
            driver.dispatch_action({"action": "prepare_stage", "stage": "S0"})
        finally:
            pipeline.write_bytes(kept)
        check_eq("t667 S0 without one: S0 runs", made, [("s0",)])

        # (2) a gate whose repair round ran returns: the final Refusal is NOT reached (E10)
        made.clear()
        driver.gate_repair = lambda gate: {"ran": True, "top": ""}
        driver.gate = lambda gate, top="": made.append(("gate", gate))
        check_eq("t667 await_gate, a repair round ran: returns", driver.dispatch_action({"action": "await_gate", "gate": "A"}), None)
        check_eq("t667 await_gate, a repair round ran: the gate is not shown", made, [])

        # (3) wait_existing_job: a halt that was asked is asked again, from its question file
        driver.state["asked"] = {"dispatch": dispatch, "kind": "halt"}
        driver.state_dir.mkdir(parents=True, exist_ok=True)
        (driver.state_dir / "driver-question.md").write_text("a\nb\nc\nd\ne\nf\nTHE QUESTION\n", encoding="utf-8")
        try:
            driver.dispatch_action({"action": "wait_existing_job", "dispatch_id": dispatch})
            raised = None
        except story_run.Person as person:
            raised = person
        check_eq("t667 wait_existing_job, halt asked: a Person of that kind with the question's text, the stage and the dispatch",
                 raised and (raised.kind, raised.text, raised.stage, raised.dispatch), ("halt", "THE QUESTION\n", "S5", dispatch))
        # (4) wait_existing_job: nothing is waiting - the liveness read fails, and the refusal says so in the no-evidence word (FR-41)
        driver.state["asked"] = {}
        driver.state["sessions"][dispatch] = "sess"
        real_state = dispatch_liveness.state

        def broken(*args, **kwargs):
            raise RuntimeError("boom")
        dispatch_liveness.state = broken
        try:
            try:
                driver.dispatch_action({"action": "wait_existing_job", "dispatch_id": dispatch})
                refused = None
            except story_run.Refusal as exc:
                refused = exc
        finally:
            dispatch_liveness.state = real_state
        check_eq("t667 wait_existing_job, liveness unreadable: a Refusal for that dispatch", refused and refused.dispatch, dispatch)
        check_in("t667 wait_existing_job, liveness unreadable: the no-evidence word", f"wait_existing_job {dispatch}: nobody can tell whether "
                 "its agent is running: this host keeps no evidence either way — RuntimeError: boom", refused.text if refused else "")

        # (5) resolve_return: the person's words go back to the role; with none, a Refusal for the dispatch
        resumed = []
        driver.resume_role = lambda *args, **kwargs: resumed.append((args, kwargs))
        driver.state["pending_words"] = {dispatch: "accept it"}
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = driver.dispatch_action({"action": "resolve_return", "dispatch_id": dispatch})
        check_eq("t667 resolve_return with words: returns, the role resumed with them",
                 (result, resumed, driver.boundary), (None, [(("S5", "qa-test-runner", dispatch, "accept it"), {"complete": "COMPLETE"})], f"S5:{dispatch}"))
        check_in("t667 resolve_return with words: the line", f"{dispatch}: returned without acceptance", out.getvalue())
        driver.state["pending_words"] = {}
        try:
            driver.dispatch_action({"action": "resolve_return", "dispatch_id": dispatch})
            refused = None
        except story_run.Refusal as exc:
            refused = exc
        check_eq("t667 resolve_return without words: a Refusal for the dispatch", refused and refused.dispatch, dispatch)
        check("t667 resolve_return without words: and its text names the action", bool(refused) and refused.text.startswith("resolve_return: "),
              refused.text if refused else "")

        # (6) a kind with no move is the final Refusal
        try:
            driver.dispatch_action({"action": "bogus"})
            refused = None
        except story_run.Refusal as exc:
            refused = exc
        check("t667 an action with no move: the final Refusal", bool(refused) and refused.text.startswith("the driver has no move for `bogus`: "),
              refused.text if refused else "")
    finally:
        harness.cleanup(root)


# --- C2-1s (t-790; t-720 §3.4, §6): the whole list in the texts, and the route of a refusal that is a list -------------------
C21_STALE = "decision references stale source revision ('rev-1'); current is 'rev-2'"
C21_DONE = ("gate before prerequisite completion: gate must be A (after S4) or B (after S8), got 'B'; S8 is not started. If its last "
            "role was already accepted, this is the factory's own bookkeeping: `controller.py --operation recover` closes it")
C21_IDENTITY = "coverage v2 S5 completion requires distinct accepted author and active critic for the same window"


def c21_composite(*items: str) -> str:
    """The controller's combined refusal, as `Controller._raise_all` writes it (C2-2): the head states the count, the items are
    numbered, a continuation line of an item is indented by three spaces."""
    lines = [f"{len(items)} problems - the request is refused whole, every one is listed:"]
    lines += [f"{number}) " + item.replace("\n", "\n   ") for number, item in enumerate(items, 1)]
    return "\n".join(lines)


def c21_forms(text: str) -> dict:
    """The three shapes a combined refusal reaches the driver in (§L-3 id 3 / N1): the controller's bare text (the positive
    control), `story_step finish` (SR wraps `story_step: refused - {exc}`), and `--operation decision` (SR wraps the CLI's
    `{"error": "..."}` line, newlines JSON-escaped)."""
    return {"bare": text,
            "story_step": f"story_step finish {RES_DISPATCH} (exit 2):\nstory_step: refused - " + text,
            "decision": "controller decision (exit 2):\n" + json.dumps({"error": text})}


def refusal_c2_1_route_known_routes_a_list_item_by_item() -> None:
    """K1 (t-720 §3.4, §6): a refusal that is a LIST is routed by its items, never by one item's phrase or marker.
    INVARIANT: nothing that goes to the conductor alone today becomes `continue`, `retry` or a resume of the role through a
    neighbouring item; a head that is there but does not hold its count is the conductor's, NEVER `match_known` over the text."""
    import story_run
    known, marker = story_run.match_known, story_run.REPAIR_MARKER
    receipt = "code review receipt CR-1 is missing for the window " + marker
    check_eq("control: the item 1 alone is the conductor's (the row looks for `stale revision`, the text says `stale source revision`)",
             known(C21_STALE), None)
    check_eq("control: the item 2 alone is `continue`", known(C21_DONE), ("already_done", "continue"))
    check_eq("control: the marked item alone is a repair of the role", known(receipt), ("marked_repair", "resume_repair"))
    check_eq("control: the identity item alone is the conductor's", known(C21_IDENTITY), None)
    for label, items in (("example 1 (stale revision + prerequisite)", (C21_STALE, C21_DONE)),
                         ("example 2 (a marked receipt + the author's identity)", (receipt, C21_IDENTITY))):
        text = c21_composite(*items)
        check("control: " + label + " - the whole text would be routed by one item's phrase or marker by `match_known`",
              known(text) in (("already_done", "continue"), ("marked_repair", "resume_repair")), str(known(text)))
        for form, shown in c21_forms(text).items():
            check_eq(f"{label}, {form}: the conductor, not the neighbour's route", story_run.route_known(story_run.Refusal(shown)), None)
    # all items agree: that route; the marker travels only when EVERY item carries it
    for form, shown in c21_forms(c21_composite(receipt, receipt + " again")).items():
        check_eq(f"all items marked, {form}: a repair of the role", story_run.route_known(story_run.Refusal(shown)),
                 ("marked_repair", "resume_repair"))
    for form, shown in c21_forms(c21_composite(C21_DONE, C21_DONE + " (once more)")).items():
        check_eq(f"all items the same row, {form}: that row", story_run.route_known(story_run.Refusal(shown)), ("already_done", "continue"))
    for form, shown in c21_forms(c21_composite(C21_STALE, C21_IDENTITY)).items():
        check_eq(f"all items unknown, {form}: the conductor", story_run.route_known(story_run.Refusal(shown)), None)
    # a continuation line of an item stays in the item, not the neighbour (the three-space indent of `_raise_all`)
    tail = c21_composite(C21_STALE + "\n" + marker, C21_IDENTITY)
    check_eq("a marker on a CONTINUATION line of item 1 does not lead item 2", story_run.route_known(story_run.Refusal(tail)), None)
    # a head that does not hold its count is the conductor's, never `match_known` over the text
    mismatched = {"3 problems, two items": c21_composite(C21_STALE, C21_DONE).replace("2 problems", "3 problems", 1),
                  "2 problems, three items": c21_composite(C21_STALE, C21_DONE, C21_IDENTITY).replace("3 problems", "2 problems", 1),
                  "1 problem, one item": c21_composite(C21_DONE)}
    for label, text in mismatched.items():
        check("control: " + label + " - `match_known` of the text WOULD say " + str(known(text)), known(text) is not None)
        for form, shown in c21_forms(text).items():
            check_eq(f"{label}, {form}: the conductor", story_run.route_known(story_run.Refusal(shown)), None)
    # no head, fewer than two findings: `match_known` of the text, byte for byte
    for text in (C21_STALE, C21_DONE, receipt, "the moon is down", "story_step finish S1-qa-scout-1 (exit 3):\nstory_step: left none of the outputs"):
        check_eq(f"one item routes as `match_known` does: {text[:40]!r}", story_run.route_known(story_run.Refusal(text)), known(text))
    check_eq("one finding is the refusal's own text, as before",
             story_run.route_known(story_run.Refusal(receipt, findings=[receipt])), known(receipt))
    # an exit gate's findings: one with the marker and one without (a defect) are not a repair of the role
    mixed = story_run.Refusal("exit gate for S5-qa-automator-1 (qa-automator, S5): 2 finding(s):\n- " + receipt + "\n- " + C21_IDENTITY,
                              dispatch="S5-qa-automator-1", findings=[receipt, C21_IDENTITY])
    check_eq("control: the text of the mixed exit-gate refusal carries the marker", known(mixed.text), ("marked_repair", "resume_repair"))
    check_eq("findings [a marked finding, a defect] go to the conductor", story_run.route_known(mixed), None)
    marked = story_run.Refusal("x", findings=[receipt, receipt + " 2"])
    check_eq("findings that all carry the marker are a repair of the role", story_run.route_known(marked), ("marked_repair", "resume_repair"))


def refusal_c2_1_the_dry_run_routes_by_the_same_function() -> None:
    """The dry run's `would:` line (the old SR:10760) is `route_known` too: a combined refusal of `where` whose item 2 alone is
    `continue` is the conductor's in the dry run, as in the loop."""
    import story_run
    task = "QA-9"
    root, task_root, env = seed(task)
    try:
        driver = driver_for(root, env, task, dry_run=True)

        def where_refuses(text):
            def where():
                raise story_run.Refusal(text)
            driver.where = where
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                driver.describe()
            return out.getvalue()
        shown = where_refuses(c21_composite(C21_STALE, C21_DONE))
        check_in("the dry run says the conductor is called", "would: call the conductor", shown)
        check_not_in("and does not name the neighbour's row", "already_done", shown)
        check_in("a single known refusal is still named", "known refusal already_done -> continue", where_refuses(C21_DONE))
    finally:
        harness.cleanup(root)


def refusal_c2_1_the_texts_carry_the_whole_list() -> None:
    """K1 (t-720 §3.4, §6): the resume text, the mechanical third turn and the `Refusal` of the handoff say `N finding(s)` and carry
    EVERY line; past the byte ceiling they carry the path of the file that holds the whole list, written by that very call
    (FR-37); `Refusal.findings` stays whole and the head `exit gate for <id> (` is unchanged. The form's lines the code filled and
    the material it fetched go through the same renderer."""
    import detector_verdict as DV
    import story_run
    task = "QA-9"
    nine = [f"s5_precheck.py: [obligations] OB-{n} has no test bound - fix: bind it" for n in range(1, 10)]
    root, task_root, env = res_fixture(task, RES_PLAIN)
    try:
        driver, _p = res_driver(root, env, task, nine)
        result = json.loads((task_root / "state/driver-runs" / f"{RES_DISPATCH}.json").read_text(encoding="utf-8"))
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                driver.handoff("qa-automator", "S5", RES_DISPATCH, result)
            check("9 findings: the handoff is refused after its one resume", False)
        except story_run.Refusal as refusal:
            asked = stub_calls(root)[0]["prompt"].replace("\r\n", "\n")
            check_in("the resume text says the count", "The exit gate refused your handoff: 9 finding(s). Repair every one of them in this turn", asked)
            check("and carries all 9 lines, in order", all(f"- {line}" in asked for line in nine)
                  and [asked.index(line) for line in nine] == sorted(asked.index(line) for line in nine))
            check_not_in("and no pointer, no file: everything fits", "the whole list", asked)
            check_not_in("and does not claim a file", "(the rest in the file", asked)
            check("the Refusal is `exit gate for <id> (` + role and stage + the count + all 9 lines",
                  refusal.text.startswith(f"exit gate for {RES_DISPATCH} (qa-automator, S5): 9 finding(s):\n- ")
                  and all(f"- {line}" in refusal.text for line in nine), refusal.text)
            check_eq("its findings are all 9", refusal.findings, nine)
            check_eq("nothing was written where nothing was cut", (task_root / "state" / "findings").exists(), False)
    finally:
        harness.cleanup(root)

    # the mechanical third turn shows the same list: `fix exactly these 9 line(s)` and every line
    marked = res_errors(*[f"TC-{n}" for n in range(1, 10)])
    root, task_root, env = res_fixture(task, RES_PLAIN)
    try:
        driver, _p = res_driver(root, env, task, marked)
        result = json.loads((task_root / "state/driver-runs" / f"{RES_DISPATCH}.json").read_text(encoding="utf-8"))
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                driver.handoff("qa-automator", "S5", RES_DISPATCH, result)
            check("9 marked findings: refused after the third turn", False)
        except story_run.Refusal:
            third = stub_calls(root)[1]["prompt"].replace("\r\n", "\n")
            check_in("the third turn says the count", "Two things and nothing else. 1) Your handoff form: fix exactly these 9 line(s), one field at a time", third)
            check("and carries all 9 lines", all(f"- {line}" in third for line in marked))
    finally:
        harness.cleanup(root)

    # past the ceiling: a count and the path; the file holds every line and is the one the text names
    big = [f"s5_precheck.py: [obligations] OB-{n} " + "x" * 300 + f" END-{n}" for n in range(1, 41)]
    root, task_root, env = res_fixture(task, RES_PLAIN)
    try:
        driver, _p = res_driver(root, env, task, big)
        result = json.loads((task_root / "state/driver-runs" / f"{RES_DISPATCH}.json").read_text(encoding="utf-8"))
        path = driver.state_dir / "findings" / f"{RES_DISPATCH}-handoff.txt"
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                driver.handoff("qa-automator", "S5", RES_DISPATCH, result)
            check("40 long findings: refused after the resume", False)
        except story_run.Refusal as refusal:
            asked = stub_calls(root)[0]["prompt"].replace("\r\n", "\n")
            check_in("the resume text says 40 finding(s)", "The exit gate refused your handoff: 40 finding(s).", asked)
            check_in("and that the rest is in the file named at the end of the list", "(the rest in the file named at the end of the list):", asked)
            check_in("the last line of the list points at the file this very call wrote", f"the whole list: {path}", asked)
            check("the file exists and holds all 40, the last whole",
                  path.is_file() and path.read_text(encoding="utf-8").count("\n- ") == 40 and "END-40" in path.read_text(encoding="utf-8"))
            check("the text shows the ceiling's worth, in whole lines, and not the 40th", "END-1\n" in asked and "END-40" not in asked)
            shown_bytes = len(asked.split("\n- (+")[0].split(":\n", 1)[1].encode("utf-8"))
            check("the shown block is within the byte ceiling", shown_bytes <= DV.FINDINGS_MAX_BYTES + 400, str(shown_bytes))
            check_in("the Refusal names the count and the pointer too", "40 finding(s):", refusal.text)
            check_in("and the same path", f"the whole list: {path}", refusal.text)
            check_eq("its findings stay whole", refusal.findings, big)
        # the dry run names no file it did not write (FR-41)
        path.unlink()
        driver.dry = True
        said = driver.exit_ask("qa-automator", RES_DISPATCH, big)
        check_in("a dry run says the list could not be saved", "the whole list could not be saved", said)
        check_eq("and writes nothing", path.exists(), False)
        driver.dry = False
        # the lines the code filled and the material it fetched: every line, through the same renderer
        driver.state.setdefault("form_filled", {})[RES_DISPATCH] = [f"work.item[{n}].field = value {n}" for n in range(1, 21)]
        driver.state["collected"] = {"S1": [f"fetched material {n}" for n in range(1, 13)]}
        said = driver.exit_ask("qa-scout", RES_DISPATCH, nine)
        check("all 20 filled lines are shown, none cut at 12", all(f"- work.item[{n}].field = value {n}" in said for n in range(1, 21)))
        check("all 12 fetched lines are shown, none cut at 8", all(f"- fetched material {n}" in said for n in range(1, 13)))
        driver.state["form_filled"][RES_DISPATCH] = [f"work.item[{n}].field = " + "y" * 300 for n in range(1, 41)]
        driver.state["collected"] = {"S1": [f"fetched {n} " + "z" * 300 for n in range(1, 41)]}
        said = driver.exit_ask("qa-scout", RES_DISPATCH, nine)
        filled_path = driver.state_dir / "findings" / f"{RES_DISPATCH}-filled.txt"
        got_path = driver.state_dir / "findings" / f"{RES_DISPATCH}-collected.txt"
        check_in("a long filled list names its file", "+", said)
        check_in("filled: the pointer says lines, not findings, and the path", f"line(s) — the whole list: {filled_path}", said)
        check_in("collected: the same", f"line(s) — the whole list: {got_path}", said)
        check("and both files hold all 40", filled_path.read_text(encoding="utf-8").count("\n- ") == 40
              and got_path.read_text(encoding="utf-8").count("\n- ") == 40)
    finally:
        harness.cleanup(root)


def refusal_t809_f1_the_head_promises_a_file_only_when_it_was_written() -> None:
    """t-809 F-1 (critic t-806, FR-10/FR-41): the resume head says `(the rest in the file named at the end of the list)` ONLY when
    `render` wrote that file. A cut list whose file was not written (a dry run, a blank dispatch, a failed write) says so in the
    head - `the list is cut at N; the whole list could not be saved: <reason>` - and never promises a file. Each of the three lists
    (findings, filled, collected) is honest on its own: one save failing leaves the others' pointers as they were.
    INVARIANT: a head and the pointer line at the end of its list never contradict each other; a file left by an earlier call is
    never taken for this call's."""
    task = "QA-9"
    promise = "(the rest in the file named at the end of the list)"
    big = [f"s5_precheck.py: [obligations] OB-{n} " + "x" * 300 + f" END-{n}" for n in range(1, 41)]
    root, task_root, env = res_fixture(task, RES_PLAIN)
    try:
        driver, _p = res_driver(root, env, task, big)
        findings = driver.state_dir / "findings"
        path = findings / f"{RES_DISPATCH}-handoff.txt"

        def head_of(said: str) -> str:
            return said.split(":\n", 1)[0]
        # positive control: the file is written, the head promises it, the pointer names it
        said = driver.exit_ask("qa-automator", RES_DISPATCH, big)
        check_in("control: a written file - the head promises it", promise, head_of(said))
        check("control: and the file is there and the list's last line names it", path.is_file() and f"the whole list: {path}" in said)
        # (a) a dry run: no file is written, none is promised, the head says why
        path.unlink()
        driver.dry = True
        said = driver.exit_ask("qa-automator", RES_DISPATCH, big)
        driver.dry = False
        check_not_in("a dry run: the head does not promise a file", promise, said)
        check_not_in("a dry run: the head does not say everything is listed here", "they are all listed here", head_of(said))
        check("a dry run: the head says the list is cut at N and could not be saved, and why it was not",
              re.search(r"in this turn - the list is cut at \d+; the whole list could not be saved: this is a dry run, which writes no file$",
                        head_of(said)) is not None, head_of(said))
        check_eq("a dry run: nothing was written", path.exists(), False)
        # a blank dispatch has no file to write
        said = driver.exit_ask("qa-automator", "", big)
        check_not_in("a blank dispatch: no promise", promise, said)
        check_in("a blank dispatch: the head says the dispatch has no name", "could not be saved: the dispatch has no name", head_of(said))
        # (b) a failed write: the file's place is taken by a folder, so the write raises an OSError
        path.mkdir(parents=True)
        said = driver.exit_ask("qa-automator", RES_DISPATCH, big)
        check_not_in("a failed write: no promise", promise, said)
        check_in("a failed write: the head says the file could not be written", "could not be saved: the file could not be written", head_of(said))
        check_not_in("a failed write: no pointer to a path", f"the whole list: {path}", said)
        cut_at = re.search(r"the list is cut at (\d+);", head_of(said))
        shown = int(cut_at.group(1)) if cut_at else -1
        check_eq("the N of the head is the count of the whole lines shown", said.count("\n- s5_precheck.py"), shown)
        path.rmdir()
        # (c) the save failing on the SECOND list while the first succeeded: each pointer honest on its own
        driver.state.setdefault("form_filled", {})[RES_DISPATCH] = [f"work.item[{n}].field = " + "y" * 300 for n in range(1, 41)]
        driver.state["collected"] = {"S1": [f"fetched {n} " + "z" * 300 for n in range(1, 41)]}
        filled_path, got_path = findings / f"{RES_DISPATCH}-filled.txt", findings / f"{RES_DISPATCH}-collected.txt"
        filled_path.mkdir(parents=True)
        said = driver.exit_ask("qa-scout", RES_DISPATCH, big)
        check_in("second list fails, first succeeds: the head still promises the findings file", promise, head_of(said))
        check("and that file was written", path.is_file() and f"the whole list: {path}" in said)
        check_not_in("the filled list does not name a path it did not write", f"the whole list: {filled_path}", said)
        check_in("the filled list says it could not be saved", "line(s); the whole list could not be saved:", said)
        check_in("the collected list (third) is untouched by the second's failure", f"line(s) — the whole list: {got_path}", said)
        filled_path.rmdir()
        # and the other way round: the FIRST list fails, the others are written
        path.unlink()
        path.mkdir()
        said = driver.exit_ask("qa-scout", RES_DISPATCH, big)
        check_in("first list fails: the head says so", "could not be saved: the file could not be written", head_of(said))
        check_in("and the filled list's pointer is its own file", f"line(s) — the whole list: {filled_path}", said)
        check("and that file exists", filled_path.is_file())
        path.rmdir()
        # (d) a file of an earlier cut is not this call's: a list that fits removes it
        driver.exit_ask("qa-scout", RES_DISPATCH, big)
        check("the earlier cut's file is there", path.is_file())
        said = driver.exit_ask("qa-scout", RES_DISPATCH, big[:3])
        check_eq("a list that fits leaves no file of an earlier cut behind", path.exists(), False)
        check_not_in("and the head promises nothing", promise, head_of(said))
        # the third value of `listed`: "" when whole or written, the clause when not
        check_eq("listed: whole - nothing cut, no clause", driver.listed(big[:3], RES_DISPATCH, "handoff")[1:], (False, ""))
        check_eq("listed: cut and written - cut, no clause", driver.listed(big, RES_DISPATCH, "handoff")[1:], (True, ""))
    finally:
        harness.cleanup(root)


def refusal_t809_f2_the_s1_stops_are_evaluated_again_on_the_resumed_set() -> None:
    """t-809 F-2 (the Lead's decision: keep the S1 roads; critic t-806). `handoff` runs the scout's S1 person branches on the role's
    own message; the ladder's resume can leave a MIXED set (a source gap beside a review, a gap beside a form line), and the
    `Refusal` made of it reads as a list to `route_known` (C2-1s: the conductor). The branches run AGAIN on the resumed set, so
    the stop keeps its road: gap + review is `s1_review`, gap + a form line is `s1_gap`. POSITION INVARIANT: after the resume's
    recompute and BEFORE the `Refusal`. EDGES: a set the resume emptied raises nothing (the digest is returned); a set with
    neither a gap nor a review stays a `Refusal` with the same findings; another role's set is never an S1 stop."""
    import story_run
    task = "QA-9"
    gap = "source unavailable and not accepted by a person: SRC-1a2b"
    review = "no person has reviewed the source decisions"
    form = "handover form: `work.sources` is empty"
    first = res_errors("TC-1")

    def run(role: str, resumed: list):
        root, task_root, env = res_fixture(task, RES_PLAIN)
        try:
            driver, _p = res_driver(root, env, task, first)
            seen = []

            def exit_errors(r, digest, dispatch=None):
                seen.append(1)
                return list(first) if len(seen) == 1 else list(resumed)
            driver.exit_errors = exit_errors
            result = json.loads((task_root / "state/driver-runs" / f"{RES_DISPATCH}.json").read_text(encoding="utf-8"))
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    out = driver.handoff(role, "S1", RES_DISPATCH, result)
                return "digest", out, [c["kind"] for c in stub_calls(root)]
            except story_run.Person as person:
                return "person", person.kind, [c["kind"] for c in stub_calls(root)]
            except story_run.Refusal as refusal:
                return "refusal", refusal, [c["kind"] for c in stub_calls(root)]
        finally:
            harness.cleanup(root)
    for label, resumed, kind in (("a gap beside a review", [gap, review], "s1_review"),
                                 ("a gap beside a form line", [gap, form], "s1_gap"),
                                 ("two gaps", [gap, gap + " (2)"], "s1_gap"),
                                 ("a review beside a form line", [review, form], "s1_review")):
        got, what, calls = run("qa-scout", resumed)
        check_eq(f"the scout's resumed set, {label}: the person's stop {kind}, not a Refusal", (got, what), ("person", kind))
        check_eq(f"{label}: the role was resumed first (one resume per finding set), then the stop", calls[:1], ["resume"])
    got, what, _calls = run("qa-scout", [form, form + " 2"])
    check_eq("control: a resumed set with no gap and no review is still the Refusal", got, "refusal")
    if got == "refusal":
        check_eq("and its findings are the whole resumed set", what.findings, [form, form + " 2"])
    got, what, _calls = run("qa-scout", [])
    check_eq("EDGE: a set the resume emptied raises nothing - the digest comes back", got, "digest")
    got, what, _calls = run("qa-automator", [gap, review])
    check_eq("another role's set with the same lines is not an S1 stop", got, "refusal")
    # the route of the Refusal they used to become, for the record (the conductor, whole - the reason the branches run again)
    mixed = story_run.Refusal("exit gate for S1-qa-scout-1 (qa-scout, S1): 2 finding(s):\n- " + gap + "\n- " + review,
                              dispatch="S1-qa-scout-1", findings=[gap, review])
    check_eq("control: as a Refusal the mixed set is routed to the conductor", story_run.route_known(mixed), None)


# --- C2-8 (t-745): a stage the CODE closes with no role gets a move ------------------------------------------------------------------
CC_MEASURED = ("stage_done: S9 is a controller-managed stage and the controller has not accepted it, so `--status done` would record a "
               "completion no evidence stands behind. A stage a ROLE ran is closed by accepting its dispatch first. If a person decided "
               "to close it anyway: `waiver.py --task QA-9 --stage S9 --block \"no accepted controller stage\" --words-file <file>`.")


class CCRig:
    """A driver whose `stage_done --status` is refused with `text` (a refusal when `check`), whose conductor and waiver are recorded."""

    def __init__(self, text: str = "boom"):
        import story_run
        self.story_run, self.task = story_run, "QA-9"
        self.root, self.task_root, self.env = seed(self.task)
        self.driver = driver_for(self.root, self.env, self.task)
        self.text, self.calls, self.seen, self.scripts = text, [], [], []
        self.driver.conductor = lambda text, *, words="", files=None, words_file=None: self.calls.append(text) or {"action": "continue", "did": "stub"}
        real = self.driver.py

        def py(script, *args, check=False, expect=""):      # C1-7c Q-3: the real `py`'s signature; a G site's `expect` is forwarded
            self.scripts.append((script, [str(a) for a in args]))
            if script == "stage_done.py" and "--status" in args and self.text:
                self.seen.append(list(args))
                if check:
                    retry = lambda: py(script, *args, check=True, expect=expect)      # noqa: E731
                    raise (story_run.gate_refusal(script, 1, self.text, expect, retry) if expect else
                           story_run.Refusal(f"stage_done.py {' '.join(str(a) for a in args[:6])} (exit 1):\n{self.text}", retry=retry))
                return 1, self.text
            if script == "stage_done.py" and "--status" in args and not self.text:
                return 0, ""                                   # the record goes through once the refusal is lifted
            if script in ("waiver.py", "project_decisions.py") and self.waiver is not None:
                if check and self.waiver:      # C1-7c Q-3: a failing script under `check=True` raises what the real `py` raises
                    raise (story_run.gate_refusal(script, self.waiver, "waiver said no", expect) if expect else
                           story_run.Refusal(f"{script} {' '.join(str(a) for a in args[:6])} (exit {self.waiver}):\nwaiver said no"))
                return self.waiver, "waiver said no"
            return real(script, *args, check=check, expect=expect)
        self.waiver = None
        self.driver.py = py

    def controller(self, **stages) -> None:
        self.driver.controller_state = lambda: {"stages": {k: dict(v) for k, v in stages.items()}, "dispatches": {}}

    def pipeline(self, **stages) -> None:
        path = self.task_root / "pipeline.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["stages"].update({k: {"status": v} for k, v in stages.items()})
        path.write_text(json.dumps(data), encoding="utf-8")

    def lift(self, refusal, boundary: str):
        """What `handle_refusal` makes of `refusal`: ('person', the Person) or ('outcome', the string)."""
        self.driver.boundary = boundary
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                return "outcome", self.driver.handle_refusal(refusal)
            except self.story_run.Person as person:
                return "person", person

    def refusal(self, site: str, stage: str, *args, **kwargs):
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.driver.record_close(site, stage, *args, **kwargs)
        except self.story_run.Refusal as refusal:
            return refusal
        raise AssertionError("record_close did not refuse")

    def defects(self) -> int:
        return len([e for e in jsonl(self.root / "qa-factory" / "records" / "journal.jsonl") if e.get("event") == "defect_found"])

    def done(self) -> None:
        harness.cleanup(self.root)


def refusal_cc_the_record_of_a_stage_the_code_closed_is_asked_not_called() -> None:
    """CC1, CC8, CC10, CC11 (t-745): a refused `stage_done` after the code's own receipt (S6/S7) is put to the person with `retry` / `stop`
    (no `go on`: no word passes it), no conductor call, ONE defect; the deferred record is written only over its own receipt, at most
    twice idle, then the question comes back with the stage as the boundary."""
    from story_run_common import human_broken
    rig = CCRig()
    try:
        refusal = rig.refusal("s6.nothing", "S6", "--status", "done", "--digest", "nothing to execute", "--no-journal", receipt="S6-code-only-1")
        check_eq("CC1: record_close marks the refusal: site, stage, step", [refusal.close[k] for k in ("site", "stage", "step")],
                 ["s6.nothing", "S6", "record"])
        got, person = rig.lift(refusal, "S6")
        check_eq("CC1: the person is asked (kind code_close), the conductor is not called", (got, person.kind, rig.calls), ("person", "code_close", []))
        check_in("CC1: the question names `retry`, `stop` and says going on is not possible", "Going on as it is is not possible here", person.text)
        check_eq("CC1: its options are retry and stop", person.state_options if hasattr(person, "state_options") else
                 rig.driver.state["code_close"]["S6"]["offer"], ["retry", "stop"])
        check_eq("CC1: the question obeys the human-text rules", human_broken(person.text), [])
        check_eq("CC1: ONE defect_found; the deferred record is kept with the receipt",
                 (rig.defects(), rig.driver.state["code_close"]["S6"]["pending"]["receipt"]), (1, "S6-code-only-1"))
        rig.lift(refusal, "S6")
        check_eq("CC1: the same refusal again files no second defect", rig.defects(), 1)

        # CC10: the receipt was opened again -> nothing is written behind the person's back
        pending = rig.driver.state["code_close"]["S6"]["pending"]
        before = len(rig.seen)
        rig.controller(S6={"status": "running"})
        with contextlib.redirect_stdout(io.StringIO()):
            moved = rig.driver.code_close_step()
        check_eq("CC10: a stage open again drops the record and writes nothing", (moved, pending is not None, len(rig.seen),
                 rig.driver.state["code_close"]["S6"]["pending"]), (False, True, before, None))
        # CC10 (the receipt itself): completed under ANOTHER receipt than the one this record waited for -> dropped, nothing written
        rig.driver.state["code_close"]["S6"]["pending"] = dict(pending, idle=0)
        rig.controller(S6={"status": "completed", "receipt_id": "S6-code-only-2"})
        with contextlib.redirect_stdout(io.StringIO()):
            moved = rig.driver.code_close_step()
        check_eq("CC10: a stage completed under another receipt drops the record and writes nothing",
                 (moved, len(rig.seen) - before, rig.driver.state["code_close"]["S6"]["pending"]), (False, 0, None))
        # CC11: pipeline.json already `done` -> dropped
        rig.driver.state["code_close"]["S6"]["pending"] = dict(pending, idle=1)
        rig.controller(S6={"status": "completed", "receipt_id": "S6-code-only-1"})
        rig.pipeline(S6="done")
        with contextlib.redirect_stdout(io.StringIO()):
            moved = rig.driver.code_close_step()
        check_eq("CC11: a record already on file is dropped", (moved, rig.driver.state["code_close"]["S6"]["pending"]), (False, None))
        # CC8: the ceiling AT and BEYOND: two idle turns (a known refusal that continues), the third turn asks
        rig.pipeline(S6="running")
        rig.driver.state["code_close"]["S6"]["pending"] = dict(pending, idle=0)
        rig.text = "stage already completed"
        turns = []
        for _ in range(2):
            with contextlib.redirect_stdout(io.StringIO()):
                rig.driver.guarded(lambda: turns.append(rig.driver.code_close_step()), {"action": "code_close"})
        check_eq("CC8: two idle turns are tried (the known refusal continues each)", (turns, len(rig.seen) - before),
                 ([], 2))
        got = None
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rig.driver.guarded(lambda: turns.append(rig.driver.code_close_step()), {"action": "code_close"})
        except rig.story_run.Person as person:
            got = person
        check("CC8: the third turn asks instead of trying (no fourth write)", got is not None and got.kind == "code_close" and len(rig.seen) - before == 2,
              str(got))
        check_in("CC8: the question says the record was tried twice", "tried to record it twice", got.text)
        check_eq("CC8: the boundary is the stage, not `no_trace`", rig.driver.boundary, "S6")
        check_eq("CC8: `retry` resets the count", (rig.driver._answer_code_close("retry", got.text, "S6", ""),
                 rig.driver.state["code_close"]["S6"]["pending"]["idle"]), (True, 0))
    finally:
        rig.done()


def refusal_cc_the_s9_record_and_the_door_of_s0() -> None:
    """CC2 (B2), CC3, CC4, CC7, CC12, CC13, CC16, CC23 (t-745): the measured text of the retro's record is no S0 boundary; the first
    moves of code stay code's; the blocks are read from the state; `go on` / `full retro` / `retry` have one executor."""
    import story_run
    rig = CCRig(CC_MEASURED)
    try:
        rig.controller()                                           # a controller-managed story whose S9 the controller has not accepted
        rig.driver.controller_state = lambda: {"stages": {"S9": {"status": "pending"}}, "dispatches": {}}
        made = []
        rig.driver.code_only = lambda *args, **kwargs: made.append(args)
        refusal = rig.refusal("s9.numbers", "S9", "--status", "done", "--digest", "retro: numbers only")
        got, person = rig.lift(refusal, "S9")
        check_eq("CC2: the measured text on the S9 boundary does NOT answer with the move of S0", (made, got, person.kind), ([], "person", "code_close"))
        rec = rig.driver.state["code_close"]["S9"]
        check_eq("CC13: the block is read from the state; `full retro`, `go on`, `stop` are offered, `retry` is named absent",
                 (rec["block"], rec["offer"]), ("no accepted controller stage", ["full retro", "go on", "stop"]))
        check_in("CC13: and the question says why trying again changes nothing", "Trying again changes nothing here", person.text)
        control = story_run.Refusal(CC_MEASURED)
        rig.lift(control, "S0:ticket")
        check_eq("CC2 control: the same text on the boundary of S0 still answers with the move of S0, once", len(made), 1)
        # CC13 / CC7 / CC23: the executors
        rig.driver.state["asked"] = {"kind": "code_close", "stage": "S9", "dispatch": ""}
        rig.waiver = 1
        got = None
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rig.driver._answer_code_close("go on", person.text, "S9", "")
        except story_run.Person as held:
            got = held
        check_eq("CC23: a pass the writer refused is held, the block is marked refused", (got is not None, rec["refused"], rec["passed"]),
                 (True, ["no accepted controller stage"], []))
        rig.lift(refusal, "S9")
        check_eq("CC23: the next question has no `go on`", rec["offer"], ["full retro", "stop"])
        check_in("CC23: and says why", "your word could not be recorded against it", rig.driver.state["code_close"]["S9"]["lead"])
        rig.waiver = 0
        rec["refused"] = []
        rig.lift(refusal, "S9")
        with contextlib.redirect_stdout(io.StringIO()):
            took = rig.driver._answer_code_close("go on", "q", "S9", "")
        waivers = [a for s, a in rig.scripts if s == "waiver.py"]
        check_eq("CC7: `go on` writes ONE waiver for the stage and the block, and the block is passed",
                 (took, waivers[-1][:6], rec["passed"]), (True, ["--task", "QA-9", "--stage", "S9", "--block", "no accepted controller stage"],
                                                          ["no accepted controller stage"]))
        rig.lift(refusal, "S9")
        check_eq("CC7: after the pass the block is not offered again", rec["offer"], ["full retro", "stop"])
        check_in("CC7: and the question says the word is recorded", "your word for it is already recorded", rec["lead"])
        # CC13: `full retro` -> stage_done --set retro_mode=full, the record is gone
        with contextlib.redirect_stdout(io.StringIO()):
            took = rig.driver._answer_code_close("full retro", "q", "S9", "")
        sets = [a for s, a in rig.scripts if s == "stage_done.py" and "--set" in a]
        check_eq("CC13: `full retro` sets the retro to its role and drops the record", (took, sets[-1][-2:], "S9" in rig.driver.state["code_close"]),
                 (True, ["--set", "retro_mode=full"], False))
        # CC16: the stage is `skipped` already -> the words are recorded, nothing is executed
        rig.text = "boom"
        refusal = rig.refusal("s9.skip", "S9", "--status", "skipped", "--digest", "retro skipped: x")
        rig.lift(refusal, "S9")
        rig.pipeline(S9="skipped")
        sets_before = len(rig.scripts)
        with contextlib.redirect_stdout(io.StringIO()):
            took = rig.driver._answer_code_close("retry", "q", "S9", "")
        check_eq("CC16: an answer to a stage skipped already executes nothing but the record of the words", (took, [s for s, _a in rig.scripts[sets_before:]]),
                 (True, ["log_append.py"]))
        rig.pipeline(S9="pending")
        # CC12: a step left `running` is settled by code ONCE (recover), then the person is asked with the block `still running`
        rig.pipeline(S6="running")
        rig.driver.state.pop("code_close", None)
        recovered = []
        rig.driver.controller = lambda operation, *args, **kwargs: recovered.append(operation) or {}
        refusal = rig.refusal("s9.skip", "S9", "--status", "skipped", "--digest", "retro skipped: x")
        got, outcome = rig.lift(refusal, "S9")
        check_eq("CC12: the first refusal with a tail runs `recover` once and retries", (got, outcome, recovered), ("outcome", "retry", ["recover"]))
        got, person = rig.lift(refusal, "S9")
        rec = rig.driver.state["code_close"]["S9"]
        check_eq("CC12: the second asks, with the block `still running` and `go on`, `retry`, `stop`",
                 (got, recovered, rec["block"], rec["offer"], rig.calls), ("person", ["recover"], "still running", ["go on", "retry", "stop"], []))
        # CC3 / CC4: the known rows of code keep their move; the second report check is the conductor's
        rig.driver.state.pop("code_close", None)
        budget = rig.refusal("s7.no_failures", "S7", "--status", "done", "--digest", "d", "--no-journal")
        budget.text = "STORY BUDGET: past its ceiling"
        got, person = rig.lift(budget, "S7")
        check_eq("CC3: the story budget keeps its own question", (got, person.kind), ("person", "refusal"))
        check_eq("CC3: and no seam record was made", rig.driver.state.get("code_close", {}).get("S7"), None)
        report = rig.refusal("s9.skip", "S9", "--status", "skipped", "--digest", "d")
        report.text = "report check: damaged"
        rig.driver.state["report_rebuilds"] = {"S9": 1}
        rig.pipeline(S6="done")
        rig.lift(report, "S9")
        check_eq("CC4: the second `report check:` goes to the conductor, not to the seam", (len(rig.calls), rig.driver.state.get("code_close", {}).get("S9")),
                 (1, None))
    finally:
        rig.done()


def refusal_cc_the_factory_file_and_the_words_that_are_not_a_token() -> None:
    """CC14, CC6, CC19, CC20 (t-745): a file of the factory's own that the close needs is the factory's defect (`retry` / `stop`, never
    `go on`); words that are no token go back to the question; the record's retry repeats the tail once."""
    import story_run
    rig = CCRig("")
    try:
        refusal = story_run.Refusal("S7 repairs: the declaration cannot be read", close={"site": "s7.repair_verdicts", "stage": "S7", "step": "entry"})
        got, person = rig.lift(refusal, "S7")
        rec = rig.driver.state["code_close"]["S7"]
        check_eq("CC14: the entry of S7 asks `code_close.factory_file`: retry / stop, one defect", (got, rec["key"], rec["offer"], rig.defects()),
                 ("person", "code_close.factory_file", ["retry", "stop"], 1))
        check_in("CC14: `retry` says the factory's own file is repaired by whoever maintains the factory", "whoever maintains the factory", person.text)
        check_in("CC14: and going on is named as not possible", "the step would stay undone", person.text)
        # CC6: an answer that is no token reaches `unread` with the doors of the question
        sent = {}
        rig.driver.unread = lambda *args, **kwargs: sent.update(kwargs, args=args)
        took = rig.driver._answer_code_close("please look at it", "qtext", "S7", "")
        check_eq("CC6: no token -> the doors are the options, with `again` to show the question", (took, sent["doors"], callable(sent.get("again"))),
                 (False, ("retry", "stop"), True))
        # CC19: the conductor's options of this kind reach the SAME executor
        called = []
        rig.driver._answer_code_close = lambda *args, **kwargs: called.append(args[0]) or True
        asked = {"kind": "code_close", "options": [{"token": "full retro", "move": "site_door"}], "words_file": ""}
        with contextlib.redirect_stdout(io.StringIO()):
            took = rig.driver.take_seam_answer("full retro", asked, "q", "S9", "")
        check_eq("CC19: take_seam_answer hands a code_close token to the one executor", (took, called), (True, ["full retro"]))
        # CC20: a known `retry` of the record repeats the WHOLE record, the tail once
        del rig.driver._answer_code_close
        rig.text = "expected_revision 4"
        tail = [["--event", "dispatch_skipped", "--task", "QA-9", "--reason", "S7: no failures to triage"]]
        answers = iter([True])
        original = rig.driver.py

        def py(script, *args, check=False, expect=""):      # C1-7c Q-3: the real `py`'s signature; `expect` reaches the stub it wraps
            if script == "stage_done.py" and next(answers, False) is False:
                rig.text = ""
            return original(script, *args, check=check, expect=expect)
        rig.driver.py = py
        rig.scripts.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            rig.driver.guarded(lambda: rig.driver.record_close("s7.no_failures", "S7", "--status", "done", "--digest", "d", "--no-journal",
                                                               tail=tail, receipt="S7-code-only-1"), {"action": "x"})
        check_eq("CC20: the retried record writes the stage and the tail ONCE each",
                 [s for s, _a in rig.scripts if s in ("stage_done.py", "log_append.py")].count("log_append.py"), 1)
    finally:
        rig.done()


def refusal_cc_the_moves_of_code_stay_and_the_unknown_is_asked_with_what_is_known() -> None:
    """CC5, CC12 (recover failed), CC21, CC22 and the dry run (t-745): a refusal whose own `recover` refused goes to the conductor with both
    texts; a `recover` that refused at S9 is not run twice and its words stay beside the question; a key with no price rows is asked
    without prices and files ONE more defect; the refusal of S0's record is not this kind; a dry run writes nothing."""
    import no_move as NM
    import story_run
    rig = CCRig("event committed; the dispatch is recorded already")
    try:
        # CC5: a known `recover` row that refused falls through to the conductor, with both texts
        def refuse(operation, *args, **kwargs):
            raise story_run.Refusal("controller recover: nothing to recover here")
        rig.driver.controller = refuse
        refusal = rig.refusal("s7.no_failures", "S7", "--status", "done", "--digest", "d", "--no-journal")
        got, outcome = rig.lift(refusal, "S7")
        check_eq("CC5: the conductor is called once, the seam is not asked", (got, len(rig.calls), rig.driver.state.get("code_close")), ("outcome", 1, None))
        check("CC5: and it is shown both texts", "event committed;" in rig.calls[0] and "nothing to recover here" in rig.calls[0], rig.calls[0][:300])
        # CC22: the record of S0 is no code_close site (B1): an unmarked refusal takes the road of the conductor
        rig.calls.clear()
        rig.text = "boom"
        plain = story_run.Refusal("stage_done.py --task QA-9 --stage S0 (exit 1):\nboom")
        got, outcome = rig.lift(plain, "S0")
        check_eq("CC22: S0's record is the conductor's, as before", (got, len(rig.calls), rig.driver.state.get("code_close")), ("outcome", 1, None))
        # CC12 (recover failed): asked, ONE recover only, its words in the details beside the refusal
        rig.pipeline(S6="running")
        recovers = []

        def refuse_once(operation, *args, **kwargs):
            recovers.append(operation)
            raise story_run.Refusal("controller recover: the checkpoint is not readable")
        rig.driver.controller = refuse_once
        marked = rig.refusal("s9.skip", "S9", "--status", "skipped", "--digest", "retro skipped: x")
        got, person = rig.lift(marked, "S9")
        rec = rig.driver.state["code_close"]["S9"]
        check_eq("CC12: recover refused -> the person is asked, with `go on` for the block still running",
                 (got, recovers, rec["block"], rec["offer"]), ("person", ["recover"], "still running", ["go on", "retry", "stop"]))
        check_in("CC12: the lead says the factory could not settle it", "could not settle that by itself", rec["lead"])
        check_in("CC12: the writer's own words are beside the refusal (details)", "the checkpoint is not readable", rec["details"])
        rig.lift(marked, "S9")
        check_eq("CC12: a second refusal does not run `recover` again", recovers, ["recover"])
        # the dry run: the deferred record is announced and nothing is written
        pending = {"site": "s6.nothing", "args": ["--status", "done", "--digest", "x"], "tail": [], "receipt": "S6-code-only-1", "idle": 0}
        rig.driver.state["code_close"]["S6"] = {"site": "s6.nothing", "step": "record", "key": "code_close.stage", "block": "", "offer": ["retry", "stop"],
                                                "passed": [], "refused": [], "filed": [], "pending": pending}
        rig.controller(S6={"status": "completed", "receipt_id": "S6-code-only-1"})
        rig.pipeline(S6="running")
        rig.driver.dry = True
        before = len(rig.seen)
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            moved = rig.driver.code_close_step()
        check_eq("dry run: the turn is spent, nothing is written", (moved, len(rig.seen) - before), (True, 0))
        check_in("dry run: and the line says so", "dry run: the deferred record of S6 is not written", printed.getvalue())
    finally:
        rig.done()
    # CC21: no price rows for the key -> the question without prices and ONE more defect (FR-41)
    rig = CCRig()
    saved = NM.load_question_prices
    try:
        NM.load_question_prices = lambda: {}
        entry = story_run.Refusal("S7 repairs: the declaration cannot be read", close={"site": "s7.repair_verdicts", "stage": "S7", "step": "entry"})
        got, person = rig.lift(entry, "S7")
        check_eq("CC21: the question is shown (kind code_close) with the option lines, no price lines",
                 (got, person.kind, "`retry`" in person.text, "the factory: nothing runs" in person.text), ("person", "code_close", True, False))
        check_eq("CC21: the close's own defect and ONE for the missing prices", rig.defects(), 2)
    finally:
        NM.load_question_prices = saved
        rig.done()


def refusal_cc_fix_round_two_blocks_two_episodes_full_retro_and_s6_closes() -> None:
    """The fix round of t-914 (t-907 attempt 2): F-1 the two blocks of one S9 record come as TWO questions, in that order (spec 3.6(3));
    F-5 a record that went through leaves no stale facts, so the next episode of the stage is a clean one (I8); F-7 `full retro` is followed
    by the retro analyst's own session; F-6 the S6 closes go through `close_by_code(finalize=False)` and keep today's order and texts."""
    import story_run
    rig = CCRig(CC_MEASURED)
    try:
        rig.pipeline(S3="running")
        rig.driver.controller_state = lambda: {"stages": {"S9": {"status": "pending"}}, "dispatches": {}}
        recovers = []

        def refuse(operation, *args, **kwargs):
            recovers.append(operation)
            raise story_run.Refusal("controller recover: the checkpoint is not readable")
        rig.driver.controller = refuse
        refusal = rig.refusal("s9.numbers", "S9", "--status", "done", "--digest", "retro: numbers only")
        # F-1 step 1: the tail is non-empty and `recover` refused -> the question with the block `still running`
        got, first = rig.lift(refusal, "S9")
        rec = rig.driver.state["code_close"]["S9"]
        check_eq("F-1: the first question is `still running`, with `go on`, `retry`, `stop`", (got, rec["block"], rec["offer"], rig.calls),
                 ("person", "still running", ["go on", "retry", "stop"], []))
        # step 2: `go on` passes it
        rig.driver.state["asked"] = {"kind": "code_close", "stage": "S9", "dispatch": ""}
        rig.waiver = 0
        with contextlib.redirect_stdout(io.StringIO()):
            took = rig.driver._answer_code_close("go on", first.text, "S9", "")
        check_eq("F-1: `go on` passes `still running`", (took, rec["passed"]), (True, ["still running"]))
        # steps 3-4: the same record is refused again, now for the controller's stage; the pipeline still holds the tail
        got, second = rig.lift(refusal, "S9")
        check_eq("F-1: the SECOND question is `no accepted controller stage` with `full retro`, `go on`, `stop` (a pass is not asked twice)",
                 (got, rec["block"], rec["offer"], recovers, rig.calls),
                 ("person", "no accepted controller stage", ["full retro", "go on", "stop"], ["recover"], []))
        check("F-1: and it is another question than the first", second.text != first.text and "Trying again changes nothing here" in second.text,
              second.text[:200])
        with contextlib.redirect_stdout(io.StringIO()):
            rig.driver._answer_code_close("go on", second.text, "S9", "")
        rig.lift(refusal, "S9")
        check_eq("F-1: with both passed only `full retro` and `stop` remain", (rec["passed"], rec["offer"]),
                 (["still running", "no accepted controller stage"], ["full retro", "stop"]))
        # F-5: the record goes through -> the facts of the episode are gone; the next episode runs `recover` again and asks afresh
        rig.text = ""
        with contextlib.redirect_stdout(io.StringIO()):
            rig.driver.record_close("s9.numbers", "S9", "--status", "done", "--digest", "retro: numbers only")
        check_eq("F-5: a record that went through drops the stage's facts", "S9" in rig.driver.state.get("code_close", {}), False)
        rig.text = CC_MEASURED
        again = rig.refusal("s9.numbers", "S9", "--status", "done", "--digest", "retro: numbers only")
        got, third = rig.lift(again, "S9")
        fresh = rig.driver.state["code_close"]["S9"]
        check_eq("F-5: the second episode runs `recover` again and offers `go on` for `still running` afresh",
                 (got, recovers, fresh["passed"], fresh["block"], fresh["offer"]),
                 ("person", ["recover", "recover"], [], "still running", ["go on", "retry", "stop"]))
        # F-7 (CC13, second half): `full retro` sets the mode, and the next S9 step calls the retro analyst
        rig.pipeline(S3="done")
        rig.driver.state.pop("code_close", None)
        got, last = rig.lift(rig.refusal("s9.numbers", "S9", "--status", "done", "--digest", "retro: numbers only"), "S9")
        with contextlib.redirect_stdout(io.StringIO()):
            took = rig.driver._answer_code_close("full retro", last.text, "S9", "")
        ran, original = [], rig.driver.py
        rig.driver.after_gate_B, rig.driver.rebuild_report = (lambda: None), (lambda *a, **k: None)
        rig.driver.state["retro_asked"] = True
        rig.driver.run_role = lambda *args, **kwargs: ran.append(args)
        rig.driver.py = lambda script, *args, check=False, expect="": ((0, "") if script == "retro_numbers.py"
                                                                         else original(script, *args, check=check, expect=expect))   # C1-7b: G5 passes `expect`
        with contextlib.redirect_stdout(io.StringIO()):
            rig.driver.stage_S9()
        check_eq("F-7: after `full retro` the next S9 step runs the retro analyst, and no numbers-only record is made",
                 (took, rig.driver.pipeline().get("retro_mode"), ran, "S9" in rig.driver.state.get("code_close", {})),
                 (True, "full", [("S9", "qa-retro-analyst")], False))
    finally:
        rig.done()
    # F-6: the three S6 closes are `close_by_code(finalize=False)` after the site's OWN finalize; the order and the refusal texts stand
    rig = CCRig("")
    try:
        rig.driver.stage_scope = lambda stage, kind="": {"scope": []}
        rig.driver.controller_state = lambda: {"stages": {"S6": {"status": "pending"}}, "dispatches": {}}
        rig.driver.code_only = lambda stage, reason, evidence: "S6-code-only-1"
        finalize = [(0, "")]
        original = rig.driver.py

        def py(script, *args, check=False, expect=""):      # C1-7c Q-3: the real `py`'s signature; honours `check` (neutral today: no finalize_task.py call passes it)
            if script == "finalize_task.py":
                rig.scripts.append((script, list(args)))
                if check and finalize[0][0]:
                    raise (story_run.gate_refusal(script, finalize[0][0], finalize[0][1], expect) if expect else
                           story_run.Refusal(f"{script} (exit {finalize[0][0]}):\n{finalize[0][1]}"))
                return finalize[0]
            return original(script, *args, check=check, expect=expect)
        rig.driver.py = py
        with contextlib.redirect_stdout(io.StringIO()):
            rig.driver.stage_S6()
        order = [s for s, _a in rig.scripts if s in ("finalize_task.py", "stage_done.py")]
        record = next(a for s, a in rig.scripts if s == "stage_done.py" and "--status" in a)
        check_eq("F-6: S6 with nothing to execute: ONE finalize, then the record (same words, no journal row of its own)",
                 (order, record[record.index("--digest"):]), (["finalize_task.py", "stage_done.py"], ["--digest", "nothing to execute", "--no-journal"]))
        finalize[0] = (1, "report not buildable")
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rig.driver.stage_S6()
            raised = None
        except story_run.Refusal as refusal:
            raised = refusal
        check_eq("F-6: a finalize that fails keeps S6's own refusal text, unmarked (the conductor's)",
                 (raised is not None and raised.text, raised is not None and not raised.close),
                 ("S6 nothing to execute: finalize_task.py exit 1: report not buildable", True))
        finalize[0] = (0, "")
        rig.text = "boom"
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rig.driver.stage_S6()
            marked = None
        except story_run.Refusal as refusal:
            marked = refusal
        check_eq("F-6: a refused record is marked with the site (the seam's)", marked is not None and marked.close and
                 [marked.close[k] for k in ("site", "stage", "step")], ["s6.nothing", "S6", "record"])
    finally:
        rig.done()
    # F-3: ONE short-circuit for an answer after the stage is done; its words are the four old callers' words, byte for byte
    rig = CCRig("")
    try:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rig.driver.after_close("S9", "  my words ")
        row = [a for s, a in rig.scripts if s == "log_append.py"][-1]
        check_eq("F-3: the helper prints the old line and files the old journal row",
                 (out.getvalue(), row), ("S9 is done already; recording the words and going on\n",
                                         ["--event", "human_answer", "--task", "QA-9", "--notes", story_run._answer_note("S9 (after close): ", "my words")]))
    finally:
        rig.done()


CC9_WATCHED = {"stage_S6", "manual_close", "stage_S7", "s7_close", "stage_S9", "close_by_code"}
CC9_SITE_FREE = {"record_close", "close_by_code", "code_close_step"}      # retry lambda, pass-through, replay of a deferred record's own site
CC9_SITE_ARG = {"close_receipt": 0, "record_close": 0}                    # the position of `site` where it is positional; close_by_code: keyword only


def cc9_findings(source, sites) -> list:
    """THE predicate of CC9 (used by the census of the driver set AND by the planted controls): what is wrong in `source` (a text, or a list of texts).
    (1) a watched function that does not exist; (2) in a watched function a bare `self.code_only(` or `self.py("stage_done.py", ... "--status")`;
    (3) anywhere, a `close_by_code` / `close_receipt` / `record_close` call whose `site` is not a LITERAL non-empty key of `sites`
    (except inside `CC9_SITE_FREE`)."""
    import ast
    texts = [source] if isinstance(source, str) else list(source)      # one text, or the text of every file of the driver set (parsed apart)
    functions = [n for text in texts for n in ast.walk(ast.parse(text)) if isinstance(n, ast.FunctionDef)]
    problems = [f"missing:{name}" for name in sorted(CC9_WATCHED - {f.name for f in functions})]
    owner = {}
    for fn in functions:                                         # BFS: the outermost function owns a nested call
        for call in ast.walk(fn):
            owner.setdefault(id(call), fn.name)
    for fn in functions:
        for call in ast.walk(fn):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name)
                    and call.func.value.id == "self") or owner.get(id(call)) != fn.name:
                continue
            attr = call.func.attr
            strings = [a.value for a in call.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            if fn.name in CC9_WATCHED and (attr == "code_only" or (attr == "py" and "stage_done.py" in strings and "--status" in strings)):
                problems.append(f"bypass:{fn.name}:{call.lineno}")
            if attr in ("close_by_code", "close_receipt", "record_close") and fn.name not in CC9_SITE_FREE:
                given = next((k.value for k in call.keywords if k.arg == "site"), None)
                if given is None and attr in CC9_SITE_ARG and len(call.args) > CC9_SITE_ARG[attr]:
                    given = call.args[CC9_SITE_ARG[attr]]
                if not (isinstance(given, ast.Constant) and isinstance(given.value, str) and given.value in sites):
                    problems.append(f"site:{fn.name}:{call.lineno}:{attr}")
    return problems


def refusal_cc9_every_close_of_s6_s7_s9_goes_through_the_one_record() -> None:
    """CC9 (t-745 detector): in the stage functions that close a stage by code, no `stage_done.py --status` call and no bare `self.code_only(`
    is left - the close is `record_close` / `close_receipt` (or `close_by_code`, which holds them) - and every such call carries a LITERAL
    `site` that is a key of `CODE_CLOSE_SITES` (an unmarked refusal would go to the conductor in silence). The watched names must exist."""
    import story_run
    sites = set(story_run.CODE_CLOSE_SITES)
    source = harness.driver_text()
    check_eq("CC9: no close of S6/S7/S9 by code bypasses record_close / close_receipt, every call carries its site, every watched name exists",
             cc9_findings([text for _path, text in harness.driver_sources()], sites), [])
    check_eq("F-3: the after-close line lives in the one helper, and its four callers call it",
             (source.count("is done already; recording the words and going on"), source.count("self.after_close(")), (1, 4))
    # the negative controls: the SAME predicate sees each planted defect (and passes the planted good call)
    def planted(line: str, others: bool = True) -> str:
        rest = "".join(f"    def {name}(self):\n        pass\n" for name in sorted(CC9_WATCHED - {"stage_S6"})) if others else ""
        return "class D:\n    def stage_S6(self):\n        " + line + "\n" + rest

    plants = {
        "a stage_done call returned to py": ("self.py('stage_done.py', '--task', t, '--status', 'done', check=True)", "bypass:stage_S6"),
        "a bare code_only": ("self.code_only('S6', r, e)", "bypass:stage_S6"),
        "close_by_code with site=''": ("self.close_by_code('S6', r, e, finalize=False, site='')", "site:stage_S6"),
        "close_by_code with no site": ("self.close_by_code('S6', r, e, finalize=False)", "site:stage_S6"),
        "close_by_code with a site that is no key": ("self.close_by_code('S6', r, e, finalize=False, site='s6.nope')", "site:stage_S6"),
        "record_close with a variable site": ("self.record_close(site, 'S6', '--status', 'done')", "site:stage_S6"),
        "close_receipt with an empty positional site": ("self.close_receipt('', 'S6', r, e)", "site:stage_S6"),
    }
    for label, (line, expect) in plants.items():
        got = cc9_findings(planted(line), sites)
        check(f"CC9 control: {label} is red", any(p.startswith(expect) for p in got), str(got))
    check_eq("CC9 control: the planted good call is green",
             cc9_findings(planted("self.close_by_code('S6', r, e, finalize=False, site='s6.nothing')"), sites), [])
    check_eq("CC9 control: a renamed watched function is red",
             cc9_findings(planted("self.close_by_code('S6', r, e, finalize=False, site='s6.nothing')", others=False), sites),
             [f"missing:{name}" for name in sorted(CC9_WATCHED - {"stage_S6"})])


# --- C2-4 (t-917, K9): a role is resumed only for judgement ---------------------------------------------------------------------------
K9_LENGTH = "handover form S5-qa-automator-1.yaml - scope[0].reason: 90 characters, at most 80. This is a repair, not a question for the person."
K9_CUT = {"shortened": [{"field": "scope[0].reason", "kept_len": 80, "written_len": 90}]}


def k9_driver(root, env, task: str, exit_lines, *, form=None):
    """A driver whose exit gate answers `exit_lines()` (a callable) and whose form check is `form(shorten)` -> (report, lines)."""
    driver = driver_for(root, env, task)
    driver.state["sessions"][RES_DISPATCH] = "sess-a"
    driver.exit_errors = lambda role, digest, dispatch=None: list(exit_lines())
    driver.controller_state = lambda: {"dispatches": {RES_DISPATCH: {"stage": "S5", "role": "qa-automator", "scope": ["TC-1"]}}}
    cuts = []
    driver.form_report = lambda dispatch, shorten=False: (cuts.append(shorten) or form(shorten)) if form else (None, [])
    return driver, cuts


def k9_handoff(driver, root, task_root, role="qa-automator", stage="S5"):
    result = json.loads((task_root / "state/driver-runs" / f"{RES_DISPATCH}.json").read_text(encoding="utf-8"))
    with contextlib.redirect_stdout(io.StringIO()):
        return driver.handoff(role, stage, RES_DISPATCH, result)


def refusal_c2_4_a_length_is_cut_by_code_not_resumed_for():
    """C2-4 T15a/T15b/T16 + I5: (a) after the first resume only lengths are left: the form is cut, the digest returned, NO third
    resume (the ladder point); (b) at the first entry only lengths: no paid call at all (the `handoff` point); (c) length beside a
    judgement line: the cut is not asked for and the role is woken (the third turn as today); (d) a scout's S1 gap stands first."""
    import story_run
    task = "QA-9"
    length = [K9_LENGTH]
    root, task_root, env = res_fixture(task, RES_PLAIN)
    try:
        state = {"cut": False}
        driver, cuts = k9_driver(root, env, task, lambda: res_errors("TC-1") if not stub_calls(root) else [],
                                 form=lambda shorten: ((state.update(cut=True) or K9_CUT), []) if shorten else (None, [] if state["cut"] else length))
        out = k9_handoff(driver, root, task_root)
        check_eq("T15a: one resume for the judgement line, none for the length left after it; the digest comes back",
                 ([c["kind"] for c in stub_calls(root)], bool(out)), (["resume"], True))
        check_eq("T15a: the form was cut once, by the driver's flag", cuts.count(True), 1)
    finally:
        harness.cleanup(root)
    root, task_root, env = res_fixture(task, RES_PLAIN)
    try:
        state = {"cut": False}
        driver, cuts = k9_driver(root, env, task, lambda: [],
                                 form=lambda shorten: ((state.update(cut=True) or K9_CUT), []) if shorten else (None, [] if state["cut"] else length))
        out = k9_handoff(driver, root, task_root)
        check_eq("T15b: only a length at the first entry: no paid call, the digest comes back", (stub_calls(root), bool(out)), ([], True))
    finally:
        harness.cleanup(root)
    root, task_root, env = res_fixture(task, RES_PLAIN)
    try:
        driver, cuts = k9_driver(root, env, task, lambda: res_errors("TC-1"), form=lambda shorten: (None, length))
        try:
            k9_handoff(driver, root, task_root)
        except story_run.Refusal:
            pass
        check_eq("T16: a length beside a judgement line: never cut, the role is woken (resume x2 as today)",
                 (cuts.count(True), [c["kind"] for c in stub_calls(root)]), (0, ["resume", "resume"]))
    finally:
        harness.cleanup(root)
    root, task_root, env = res_fixture(task, RES_PLAIN)
    try:
        # t-919 F-2 (T16b): at the ladder point NO assembly follows a cut, so the final-message line left on the exit side after the
        # first resume is the role's to repair with its form's words: nothing is cut, the third resume runs
        import story_run as _sr
        final = "digest: your final message is not the handoff form. " + _sr.REPAIR_MARKER
        driver, cuts = k9_driver(root, env, task, lambda: res_errors("TC-1") if not stub_calls(root) else [final],
                                 form=lambda shorten: (None, length))
        try:
            k9_handoff(driver, root, task_root)
        except story_run.Refusal:
            pass
        check_eq("T16b: a length beside the final-message line after the first resume: not cut, the role is woken (resume x2)",
                 (cuts.count(True), [c["kind"] for c in stub_calls(root)]), (0, ["resume", "resume"]))
    finally:
        harness.cleanup(root)
    root, task_root, env = res_fixture(task, RES_PLAIN)
    try:
        gap = "source unavailable and not accepted by a person: SRC-1a2b"
        driver, cuts = k9_driver(root, env, task, lambda: [gap], form=lambda shorten: (K9_CUT, []) if shorten else (None, length))
        try:
            k9_handoff(driver, root, task_root, role="qa-scout", stage="S1")
            check("I5: a scout's S1 gap is the person's", False)
        except story_run.Person as person:
            check_eq("I5: the S1 stop is raised before any cut or resume", (person.kind, True in cuts, stub_calls(root)), ("s1_gap", False, []))
    finally:
        harness.cleanup(root)


def k9_door_rig(root, env, task: str, role: str, dispatch: str, retry, *, wrote=True):
    """A driver for the code doors: `py` stub (window_record / ticket_adapter) rewrites `target` when `wrote`; claude and the
    seam must not run unless the test allows it. (driver, door log)"""
    driver = driver_for(root, env, task)
    driver.controller_state = lambda: {"dispatches": {dispatch: {"stage": dispatch.split("-")[0], "role": role, "scope": ["TC-1"]}}}
    driver.form_report = lambda d, shorten=False: (None, [])
    log = []
    real_py = driver.py
    target = driver.task_root / "work" / ("automation-manifest.json" if role == "qa-code-critic" else "source-inventory.json")

    def py(script, *args, **kw):
        if script in ("window_record.py", "ticket_adapter.py"):
            log.append(script)
            if wrote:
                target.write_text(target.read_text(encoding="utf-8") + " ", encoding="utf-8")
            return 0, "done"
        return real_py(script, *args, **kw)
    driver.py = py
    driver.exit_limit = lambda *a, **kw: log.append("exit_limit")
    return driver, log


def k9_refusal(dispatch: str, retry, text: str = "the qa-code-critic window is not receipted", role="qa-code-critic", stage="S5"):
    import story_run
    return story_run.Refusal(f"story_step finish {dispatch} (exit 3):\n{text}", dispatch=dispatch, retry=retry)


def refusal_c2_4_the_doors_of_code_run_before_every_resume():
    """C2-4 T17 (a-g) + F-2 + F-6 (t-909): the review receipt, the scout's receipts and the form are written by code BEFORE a
    resume; success closes the refusal with no `note_resume`; a changed key takes the whole road; the same key keeps today's
    road over the original refusal; a record that already holds the key and no session at all are met too (position invariant);
    a gap/stale window writes no receipt (I4); the step is not entered from inside its own retry."""
    import story_run
    task, dispatch = "QA-9", "S5-qa-code-critic-1"
    for label, role, disp in (("review receipt", "qa-code-critic", dispatch), ("source receipts", "qa-scout", "S1-qa-scout-1")):
        root, task_root, env = res_fixture(task, RES_PLAIN)
        try:
            (task_root / "work").mkdir(parents=True, exist_ok=True)
            for name in ("automation-manifest.json", "source-inventory.json"):
                (task_root / "work" / name).write_text("{}", encoding="utf-8")
            (task_root / "work" / "test-code").mkdir(parents=True, exist_ok=True)
            (task_root / "work" / "test-code" / "critic-findings.md").write_text("#", encoding="utf-8")
            calls = []
            driver, log = k9_door_rig(root, env, task, role, disp, None)
            driver.state["sessions"][disp] = "sess-a"
            driver.run_claude = lambda *a, **kw: (_ for _ in ()).throw(AssertionError("a paid call"))
            refusal = k9_refusal(disp, lambda: calls.append("retry"))
            with contextlib.redirect_stdout(io.StringIO()) as out:
                got = driver.resume_on_refusal(refusal, disp.split("-")[0], disp)
            check_eq(f"T17 ({label}): the door wrote, the retry went through: continue, no paid call, no resume on record",
                     (got, log, calls, driver.state.get("refusal_resumes")), ("continue", [log[0]], ["retry"], None))
            check_in(f"T17 ({label}): and the print names the door", "closed by code", out.getvalue())
        finally:
            harness.cleanup(root)
    root, task_root, env = res_fixture(task, RES_PLAIN)
    try:
        (task_root / "work" / "test-code").mkdir(parents=True, exist_ok=True)
        (task_root / "work" / "test-code" / "critic-findings.md").write_text("#", encoding="utf-8")
        (task_root / "work" / "automation-manifest.json").write_text("{}", encoding="utf-8")
        # T17b: a retry that raises ANOTHER refusal -> the whole road; the SAME key -> today's first resume over the original
        driver, log = k9_door_rig(root, env, task, "qa-code-critic", dispatch, None)
        driver.state["sessions"][dispatch] = "sess-a"
        seen = []
        driver.handle_refusal = lambda r2: seen.append(r2.text) or "continue"
        def other():
            raise k9_refusal(dispatch, None, "a different refusal")
        with contextlib.redirect_stdout(io.StringIO()):
            got = driver.resume_on_refusal(k9_refusal(dispatch, other), "S5", dispatch)
        check_eq("T17b: the retry's new refusal (another key) takes handle_refusal", (got, len(seen)), ("continue", 1))
        driver2, log2 = k9_door_rig(root, env, task, "qa-code-critic", dispatch, None)
        driver2.state["sessions"][dispatch] = "sess-a"
        def same():
            raise k9_refusal(dispatch, None)
        before = len(stub_calls(root))
        with contextlib.redirect_stdout(io.StringIO()):
            got = driver2.resume_on_refusal(k9_refusal(dispatch, same), "S5", dispatch)
        check_eq("T17b: the same key: today's first resume (one paid call, on record)",
                 (got, [c["kind"] for c in stub_calls(root)[before:]], len(driver2.state["refusal_resumes"][dispatch]["sess-a"])), ("continue", ["resume"], 1))
        with contextlib.redirect_stdout(io.StringIO()):
            driver2.resume_on_refusal(k9_refusal(dispatch, same), "S5", dispatch)
        check_eq("T17b: the same (dispatch, key) a second time: the doors are not run again (the bound), the seam is met instead",
                 (log2.count("window_record.py"), log2.count("exit_limit")), (1, 1))
        # T17c: the set is already on record ("already resumed"): the door still closes it, exit_limit is not met
        driver3, log3 = k9_door_rig(root, env, task, "qa-code-critic", dispatch, None)
        driver3.state["sessions"][dispatch] = "sess-a"
        refusal = k9_refusal(dispatch, lambda: None)
        driver3.note_resume(dispatch, "sess-a", story_run.finding_key(driver3.refusal_lines(refusal)), "refusal")
        with contextlib.redirect_stdout(io.StringIO()):
            got = driver3.resume_on_refusal(refusal, "S5", dispatch)
        check_eq("T17c: a set already on record, the door closes it: continue, the seam not met", (got, "exit_limit" in log3), ("continue", False))
        # T17g: no session at all: the door is met before the `exit_limit` of the 'no session' branch
        driver4, log4 = k9_door_rig(root, env, task, "qa-code-critic", dispatch, None)
        driver4.state["sessions"].pop(dispatch, None)
        with contextlib.redirect_stdout(io.StringIO()):
            got = driver4.resume_on_refusal(k9_refusal(dispatch, lambda: None), "S5", dispatch)
        check_eq("T17g: no session: the door closes first, exit_limit is not called", (got, "exit_limit" in log4), ("continue", False))
        # T17d/e: window_record wrote nothing (a gap, a stale review, a collision) -> no retry, today's road
        driver5, log5 = k9_door_rig(root, env, task, "qa-code-critic", dispatch, None, wrote=False)
        driver5.state["sessions"][dispatch] = "sess-a"
        retried = []
        before = len(stub_calls(root))
        with contextlib.redirect_stdout(io.StringIO()):
            got = driver5.resume_on_refusal(k9_refusal(dispatch, lambda: retried.append(1), "a window with a gap"), "S5", dispatch)
        check_eq("T17d: a door that writes nothing is no closure: no retry, the first resume as today", (got, retried, [c["kind"] for c in stub_calls(root)[before:]]),
                 ("continue", [], ["resume"]))
        # F-10: no findings file -> the receipt door does not run (a receipt is immutable; the role is woken for the findings)
        (task_root / "work" / "test-code" / "critic-findings.md").unlink()
        driver6, log6 = k9_door_rig(root, env, task, "qa-code-critic", dispatch, None)
        driver6.state["sessions"][dispatch] = "sess-a"
        with contextlib.redirect_stdout(io.StringIO()):
            driver6.resume_on_refusal(k9_refusal(dispatch, lambda: None, "no findings yet"), "S5", dispatch)
        check_eq("F-10: no findings file, no receipt door", log6, [])
        # F-2: a door that writes on every pass + a retry raising a fresh key each time: ONE door run, then today's branches
        (task_root / "work" / "test-code" / "critic-findings.md").write_text("#", encoding="utf-8")
        driver7, log7 = k9_door_rig(root, env, task, "qa-code-critic", dispatch, None)
        driver7.state["sessions"][dispatch] = "sess-a"
        counter = []
        def fresh():
            counter.append(1)
            raise k9_refusal(dispatch, fresh, f"a refusal that changes: {len(counter)}")
        driver7.handle_refusal = lambda r2: driver7.resume_on_refusal(r2, "S5", dispatch)
        before = len(stub_calls(root))
        with contextlib.redirect_stdout(io.StringIO()):
            got = driver7.resume_on_refusal(k9_refusal(dispatch, fresh), "S5", dispatch)
        check_eq("F-2: the step is not entered from inside its own retry: one door run, one retry, one resume (the nested refusal's)",
                 (got, log7, len(counter), [c["kind"] for c in stub_calls(root)[before:]], driver7.in_code_step), ("continue", ["window_record.py"], 1, ["resume"], False))
    finally:
        harness.cleanup(root)


def refusal_c2_4_s4_keeps_open_only_when_the_round_will_run():
    """C2-4 T18/T18b + F-3/F-4/F-6 (t-909): the S4 case critic's finish says `OpenWork` (`--not-complete --unresolved --reason`)
    exactly when the rework branch will run (verdict sends cases back, a round is left, a findings file exists); with no findings
    file the old False stays (one resume of the critic, no new critic); the recovery road (`completion_for`) applies the same rule
    BEFORE `rework_of`; the reason is timeless and at most 300; the D3 pins and the F-6 (b) unknown-window pin."""
    import story_run
    task = "QA-9"
    root, task_root, env = res_fixture(task, RES_PLAIN)
    try:
        driver = driver_for(root, env, task)
        # X2-7: the critic's finish reads its form by the dispatch id and writes the stage acceptance first (a known word, a no-op writer)
        driver.last_dispatch = "S4-qa-case-critic-1"
        driver.stage_verdict_known = lambda form: True
        driver.stage_acceptance_write = lambda stage, dispatch: None
        # X2-7 point 7: a critic that sends cases back on the LAST round (or with a count that is no number) goes to the conductor seam; here the seam
        # answers "no move needed" (a stub, as in test_repair_route), so the T18 expectations of those rows (None) stay what they were
        driver.pipeline = lambda: {}
        driver.stage_review_exhausted = lambda stage, *a, **k: None
        digest = "qa-case-critic S4 TC-1 · concerns\nTC-1 · rejected · weak Then\nwork/test-cases/critic-findings.md"
        rule = driver.s4_critic_completion(["TC-1", "TC-2"], 0, 2)
        check_eq("F-3: concerns, a round left, NO findings file: the old False (one resume of the critic, no open stage)", rule(digest), False)
        findings = task_root / "work" / "test-cases" / "critic-findings.md"
        findings.parent.mkdir(parents=True, exist_ok=True)
        findings.write_text("# findings", encoding="utf-8")
        got = rule(digest)
        check_eq("T18: with a findings file the finish is OpenWork cases_in_repair", (type(got).__name__, got.unresolved), ("OpenWork", "cases_in_repair"))
        check_in("F-3 (t-919): the reason names the cases the critic REJECTED (1 of the 2 in scope) and the findings path",
                 "the case critic sent 1 case(s) back for repair; S4 was kept open for the repair round: TC-1; its findings: work/test-cases/critic-findings.md", got.reason)
        no_rows = driver.s4_critic_completion(["TC-1", "TC-2"], 0, 2)("qa-case-critic S4 TC-1 · concerns\nwork/test-cases/critic-findings.md").reason
        check_eq("F-3 (t-919): a rejected set that cannot be read prints no number (FR-41)",
                 (no_rows.startswith("the case critic sent work back for repair; S4 was kept open"), any(ch.isdigit() for ch in no_rows.split(";")[0])), (True, False))
        check_not_in("T18: and is timeless (no 'round k of cap', no present tense)", " is kept", got.reason)
        check_eq("T18: approve -> None (the critic closes S4)", rule(digest.replace("concerns", "approve")), None)
        check_eq("T18: the last round (counted == cap) -> None", driver.s4_critic_completion(["TC-1"], 2, 2)(digest), None)
        check_eq("T18/edge 15: a cap or count that is no number -> None, as today", driver.s4_critic_completion(["TC-1"], None, "x")(digest), None)
        long_scope = [f"TC-{i:04d}" for i in range(80)]
        long_digest = "qa-case-critic S4 TC-0000 · concerns\n" + "".join(f"{c} · rejected · weak Then\n" for c in long_scope) + "work/test-cases/critic-findings.md"
        reason = driver.s4_critic_completion(long_scope, 0, 2)(long_digest).reason
        check_eq("T18: a long list is cut to 300 and ends with the path of the findings", (len(reason), reason.endswith("… [list: work/test-cases/critic-findings.md]")), (300, True))
        driver.controller = lambda *a, **kw: {"repair_budget": {"counted": 0, "cap": 2}}
        recovered = driver.completion_for("S4", "qa-case-critic", {"id": "S4-qa-case-critic-1", "scope": ["TC-1"], "rework_of": "S4-qa-case-critic-1"})
        check_eq("F-4: the recovery road applies the same rule, before rework_of", type(recovered(digest)).__name__, "OpenWork")
        argv = []
        driver.py = lambda script, *args, **kw: argv.extend(str(a) for a in args) or (0, "accepted x")
        driver.finish("S4-qa-case-critic-1", digest, complete=got, role="qa-case-critic", stage="S4")
        check_eq("T18: the pair reaches story_step as --not-complete --unresolved … --reason …",
                 ("--not-complete" in argv, argv[argv.index("--unresolved") + 1] if "--unresolved" in argv else None, "--reason" in argv),
                 (True, "cases_in_repair", True))
        check_eq("T18b (D3 pin): a rework's finish stays False - the designer's repair round is not closed by itself",
                 (driver.completion_for("S4", "qa-case-designer", {"rework_of": "x"}), driver.completion_for("S2", "qa-x", {"purpose": "repair_verify"})),
                 (False, False))
        def broken(*a, **kw):
            raise story_run.Refusal("stage-scope: cannot read")
        driver.stage_scope = broken
        check_eq("F-6 (b) pin: an unreadable window state keeps False (FR-59: unknown is never a pass)",
                 driver.completion_for("S5", "qa-code-critic", {"scope": ["TC-1"]}), False)
    finally:
        harness.cleanup(root)


def refusal_c2_4_an_owed_s4_repair_round_starts_instead_of_a_new_critic():
    """t-919 F-1: a critic accepted with `cases_in_repair` and no designer rework registered (its finish went through the recovery
    road, or a refused finish that came back as `continue`, so `stage_S4`'s tail never ran) is owed its round: the next `stage_S4`
    entry registers the designer rework from the DATA and dispatches NO critic. The carrier is read from the real rule's own
    OpenWork, one case per road; and the entries that must still run a critic (a rework already registered, no findings file, the
    last round, another word, the live road)."""
    task = "QA-9"
    digest = "qa-case-critic S4 TC-1 · concerns\nTC-1 · rejected · weak Then\nwork/test-cases/critic-findings.md"

    def run(label, dispatches, *, findings=True, counted=0, live_digest=None):
        root, task_root, env = seed(task)
        try:
            driver = driver_for(root, env, task)
            findings_file = driver.task_root / "work" / "test-cases" / "critic-findings.md"      # the driver's own spelling of the root
            findings_file.parent.mkdir(parents=True, exist_ok=True)
            findings_file.write_text("verdict: approve_with_fixes\n", encoding="utf-8")
            roles, rework, calls = [], [], []
            driver.py = lambda script, *a, **k: calls.append(script) or (0, "")
            driver.controller_state = lambda: {"dispatches": dispatches}
            driver.run_role = lambda stage, role, **k: roles.append(role) or (live_digest or digest, None)
            driver.rework = lambda stage, role, cases, reason, **k: rework.append((stage, role, list(cases)))
            driver.pin_cases = lambda: None
            driver.revise_plan = lambda: None
            driver.render_appendix = lambda: calls.append("appendix")
            driver.critic_scope = lambda: ["TC-1", "TC-2"]
            driver.budget_or_none = lambda *a, **k: {"counted": counted, "cap": 2}
            driver.newest = lambda pattern: findings_file if findings else None
            driver.unraised_cases = lambda: False
            with contextlib.redirect_stdout(io.StringIO()):
                driver.stage_S4()
            return roles, rework, driver
        finally:
            harness.cleanup(root)

    base = {"S4-qa-case-designer-1": {"stage": "S4", "role": "qa-case-designer", "status": "accepted"}}

    def with_critic(unresolved, status="accepted"):
        return {**base, "S4-qa-case-critic-1": {"stage": "S4", "role": "qa-case-critic", "status": status, "unresolved": unresolved}}

    root, task_root, env = seed(task)
    try:
        probe = driver_for(root, env, task)
        # X2-7: the critic's finish reads its form by the dispatch id and writes the stage acceptance first (a known word, a no-op writer)
        probe.last_dispatch = "S4-qa-case-critic-1"
        probe.stage_verdict_known = lambda form: True
        probe.stage_acceptance_write = lambda stage, dispatch: None
        (task_root / "work" / "test-cases").mkdir(parents=True, exist_ok=True)
        (task_root / "work" / "test-cases" / "critic-findings.md").write_text("#", encoding="utf-8")
        probe.controller = lambda *a, **kw: {"repair_budget": {"counted": 0, "cap": 2}}
        recovery = probe.completion_for("S4", "qa-case-critic", {"id": "S4-qa-case-critic-1", "scope": ["TC-1"], "rework_of": "S4-qa-case-critic-1"})(digest)
        refused_then_continue = probe.s4_critic_completion(["TC-1"], 0, 2)(digest)
    finally:
        harness.cleanup(root)
    for road, open_work in (("recovery road (completion_for via _finish_saved_result)", recovery),
                            ("refused finish returned as continue", refused_then_continue)):
        roles, rework, _driver = run(road, with_critic(open_work.unresolved))
        check_eq(f"F-1, {road}: the owed round is registered from the data and no critic is dispatched",
                 (roles, rework), ([], [("S4", "qa-case-designer", ["TC-1", "TC-2"])]))
    roles, rework, _driver = run("a list-shaped record", with_critic(["cases_in_repair"]))
    check_eq("F-1: the word is found in whatever shape the record keeps it", (roles, len(rework)), ([], 1))
    roles, rework, _driver = run("normal road", base, live_digest=digest)
    check_eq("F-1, normal road: the live critic runs once and ITS tail registers the round once", (roles, len(rework)), (["qa-case-critic"], 1))
    later = {**with_critic("cases_in_repair"), "S4-qa-case-designer-2": {"stage": "S4", "role": "qa-case-designer", "status": "running"}}
    roles, rework, _driver = run("a rework registered", later, live_digest="qa-case-critic S4 TC-1 · ok\nwork/x.md")
    check_eq("F-1: a designer rework already registered after the critic: the pre-check stands down (the next critic is the live one)",
             (roles, rework), (["qa-case-critic"], []))
    roles, rework, _driver = run("no findings", with_critic("cases_in_repair"), findings=False, live_digest="qa-case-critic S4 TC-1 · ok\nx.md")
    check_eq("F-1: no findings file: the round cannot be started, the critic writes them (today's road)", (roles, rework), (["qa-case-critic"], []))
    roles, rework, _driver = run("last round", with_critic("cases_in_repair"), counted=2, live_digest="qa-case-critic S4 TC-1 · ok\nx.md")
    check_eq("F-1: the last round: no repair is owed", (roles, rework), (["qa-case-critic"], []))
    roles, rework, _driver = run("another word", with_critic("repairs_pending"), live_digest="qa-case-critic S4 TC-1 · ok\nx.md")
    check_eq("F-1: another word in the record is not this carrier", (roles, rework), (["qa-case-critic"], []))
    roles, rework, _driver = run("unreadable", with_critic(None), live_digest="qa-case-critic S4 TC-1 · ok\nx.md")
    check_eq("F-1: an absent `unresolved` is not owed: a fresh critic, never a silent close", (roles, rework), (["qa-case-critic"], []))


def refusal_n5_the_driver_refuses_as_the_hook_does_and_uses_the_one_packet() -> None:
    """RC1-14 step 5 (N5): `Driver.system_file` never starts a role with `blocks = []`. Over budget -> the hook's own text as a
    `Refusal` (`injection_over_budget`, `known` False) and the hook's denial line; any other failure, a missing map and an unknown
    role -> `injection_unbuilt` with the dry-run door and a denial line; a built layer -> the packet of `task_packet` with the kind
    of the dispatch's own record."""
    import inject_context
    import story_run
    task = "QA-9"
    root, task_root, env = seed(task)
    saved = {name: getattr(inject_context, name) for name in ("load_map", "collect_blocks")}
    try:
        driver = driver_for(root, env, task)
        denials = task_root / "state" / "dispatch-denials.jsonl"

        def attempt(role="qa-scout", dispatch="S1-qa-scout-1"):
            try:
                return driver.system_file(role, dispatch, ["TC-1"]), None
            except story_run.Refusal as refusal:
                return None, refusal

        # D1 / D2: the budget is read after .strip(), so a body of 26 000 chars is delivered and 26 001 is refused
        big = root / "big-slice.md"
        inject_context.load_map = lambda: {"common": [], "roles": {"qa-scout": ["project:big-slice.md"]}}
        big.write_text("x" * 26001, encoding="utf-8")
        try:
            inject_context.collect_blocks("qa-scout", inject_context.load_map())
            hook_text = ""
        except ValueError as exc:
            hook_text = str(exc)
        check("D1: the fixture is over the budget for collect_blocks", "exceeds budget" in hook_text, hook_text)
        path, refusal = attempt()
        check("D1: a Refusal is raised and no sysfile is written", refusal is not None and path is None)
        if refusal is not None:
            check_eq("D1: its text is the hook's own ValueError text, byte for byte", refusal.text, hook_text)
            check_eq("D1: its title", refusal.title, "injection_over_budget")
            check_eq("D1: its dispatch", refusal.dispatch, "S1-qa-scout-1")
            check_eq("D1: known is False on the instance, so the table never routes it", (refusal.known, story_run.route_known(refusal)), (False, None))
        check("D1: the sysfile of the refused dispatch is not there", not (driver.state_dir / "driver-tmp" / "S1-qa-scout-1.system.md").exists())
        check_eq("D1: no claude call", stub_calls(root), [])
        rows = jsonl(denials)
        check_eq("D1: one denial line `recover` can close", [(r.get("dispatch_id"), r.get("role"), r.get("reason")) for r in rows],
                 [("S1-qa-scout-1", "qa-scout", hook_text)])
        big.write_text("x" * 26000, encoding="utf-8")
        path, refusal = attempt()
        check("D2: 26 000 chars -> the role runs (a sysfile, no refusal)", refusal is None and path is not None and path.is_file())
        check_eq("D2: and no new denial line", len(jsonl(denials)), 1)

        # D3: any other exception, the map missing, the role unknown -> injection_unbuilt with a door and a denial line
        def boom(*args, **kwargs):
            raise RuntimeError("the slice reader broke")
        inject_context.collect_blocks = boom
        inject_context.load_map = saved["load_map"]
        path, refusal = attempt()
        check("D3: RuntimeError -> Refusal injection_unbuilt, no sysfile", refusal is not None and path is None and refusal.title == "injection_unbuilt")
        if refusal is not None:
            check_in("D3: the text names the door", "--dry-run --role qa-scout", refusal.text)
            check_in("D3: and the cause", "RuntimeError: the slice reader broke", refusal.text)
            check_eq("D3: known is False", (refusal.known, story_run.route_known(refusal)), (False, None))
        check_eq("D3: a denial line was written", len(jsonl(denials)), 2)
        inject_context.collect_blocks = saved["collect_blocks"]
        inject_context.load_map = lambda: {}
        path, refusal = attempt()
        check("D3: the map missing -> injection_unbuilt (not an empty rule layer)", refusal is not None and path is None and refusal.title == "injection_unbuilt")
        inject_context.load_map = saved["load_map"]
        path, refusal = attempt(role="qa-nobody")
        check("D3: a role the map does not name -> injection_unbuilt", refusal is not None and path is None and refusal.title == "injection_unbuilt")
        if refusal is not None:
            check_in("D3: naming the role", "qa-nobody", refusal.text)
        check_eq("D3: every refusal left its denial line", len(jsonl(denials)), 4)
        check_eq("D3: and no role was launched", stub_calls(root), [])

        # D4 / D5: the kind comes from THIS dispatch's record; the packet is `task_packet`'s
        state = driver.controller_state()
        records = {"S5-qa-automator-2": {"id": "S5-qa-automator-2", "stage": "S5", "role": "qa-automator", "scope": ["TC-1"],
                                         "rework_of": "S5-qa-automator-1", "repair_cause": "test_defect",
                                         "known_paths": {"package_fingerprint": "fp-1"}},
                   "S5-qa-automator-1": {"id": "S5-qa-automator-1", "stage": "S5", "role": "qa-automator", "scope": ["TC-1"]}}
        driver.controller_state = lambda: dict(state, dispatches=records)
        drop, keep = "### Profiles, leases and build commands", "### After a mechanical fix"
        path, refusal = attempt("qa-automator", "S5-qa-automator-2")
        check("D4: a repair record builds a sysfile", refusal is None and path is not None, getattr(refusal, "text", ""))
        text = path.read_text(encoding="utf-8")
        check("D4: a repair lacks the dropped section and holds the kept one", drop not in text and keep in text)
        path, refusal = attempt("qa-automator", "S5-qa-automator-1")
        first = path.read_text(encoding="utf-8")
        check("D4: a first record holds both", drop in first and keep in first)
        packet = lambda sysfile: json.loads(sysfile.split("# Resolved task packet", 1)[1].split("\n", 1)[1])
        repair_packet = packet(text)
        check_eq("D5: the dispatch projection has kind, role and scope", (repair_packet["dispatch"]["kind"], repair_packet["dispatch"]["role"],
                                                                         repair_packet["dispatch"]["scope"]), ("repair", "qa-automator", ["TC-1"]))
        check("D5: and no known_paths of its own", "known_paths" not in repair_packet["dispatch"])
        check_in("D5/E10: the record's own key is added to the one known_paths", "package_fingerprint", json.dumps(repair_packet["known_paths"]))
        check_in("D5/E10: and every stored value stays", "project_root", json.dumps(repair_packet["known_paths"]))
        first_packet = packet(first)
        check_eq("D5: a first record's kind", first_packet["dispatch"]["kind"], "first")
        path, _ = attempt("qa-automator", "S5-qa-automator-9")          # no record of this id
        none_packet = packet(path.read_text(encoding="utf-8"))
        check_eq("D5: no record -> kind first, role and scope from the arguments",
                 (none_packet["dispatch"]["kind"], none_packet["dispatch"]["role"], none_packet["dispatch"]["scope"], none_packet["dispatch"]["id"]),
                 ("first", "qa-automator", ["TC-1"], "S5-qa-automator-9"))
        check("D5: no record -> no known_paths in the dispatch", "known_paths" not in none_packet["dispatch"])
        driver.controller_state = type(driver).controller_state.__get__(driver)
        # a non-object record or state is kind first, never a crash
        driver.controller_state = lambda: {"dispatches": {"S5-qa-automator-3": "garbage"}}
        path, refusal = attempt("qa-automator", "S5-qa-automator-3")
        check("D5: a record that is not an object -> a sysfile of kind first", refusal is None and drop in path.read_text(encoding="utf-8"))
        driver.controller_state = type(driver).controller_state.__get__(driver)

        # D6: no controller.json -> the role runs with kind first, never a refusal
        (task_root / "state" / "controller.json").unlink()
        path, refusal = attempt("qa-automator", "S5-qa-automator-2")
        check("D6: no controller.json -> a sysfile, no refusal", refusal is None and path is not None, getattr(refusal, "text", ""))
        check_eq("D6: the kind is first", packet(path.read_text(encoding="utf-8"))["dispatch"]["kind"], "first")
    finally:
        for name, value in saved.items():
            setattr(inject_context, name, value)
        harness.cleanup(root)


def story_run_refusal():
    import story_run
    return story_run.Refusal


def main() -> None:
    run_scenarios([], [refusal_round_trip_gate_and_routing, refusal_table, refusal_markers, refusal_dispatch_field, refusal_judge_and_source_gaps, refusal_every_action_has_a_move, refusal_active_dispatch, refusal_structured_artifact, refusal_left_out_sources, refusal_adapter_forms_links_and_prefix, refusal_launch_warns_on_a_task_that_is_no_key, refusal_person_words_kept_whole, refusal_gate_stage_row,
                       refusal_committed_event_recovers,
                       refusal_resume_once_per_finding_set, refusal_resume_record_edges, refusal_exit_limit_routes, refusal_exit_limit_order_the_mechanical_third_turn_runs_before_the_seam, refusal_call_class_stays_with_the_conductor, refusal_resumed_halt_is_heard,
                       refusal_answer_filed_by_the_field, refusal_persons_carry_their_dispatch,
                       refusal_o1_the_handoffs_own_resumes_are_the_saved_result,
                       refusal_o2_the_text_reading_is_for_the_two_refusal_kinds_only,
                       refusal_t667_take_answer_branches_no_other_file_reaches,
                       refusal_t667_dispatch_action_branches_no_other_file_reaches,
                       refusal_c2_1_route_known_routes_a_list_item_by_item, refusal_c2_1_the_dry_run_routes_by_the_same_function,
                       refusal_c2_1_the_texts_carry_the_whole_list,
                       refusal_t809_f1_the_head_promises_a_file_only_when_it_was_written,
                       refusal_t809_f2_the_s1_stops_are_evaluated_again_on_the_resumed_set,
                       refusal_cc_the_record_of_a_stage_the_code_closed_is_asked_not_called,
                       refusal_cc_the_s9_record_and_the_door_of_s0,
                       refusal_cc_the_factory_file_and_the_words_that_are_not_a_token,
                       refusal_cc_the_moves_of_code_stay_and_the_unknown_is_asked_with_what_is_known,
                       refusal_cc_fix_round_two_blocks_two_episodes_full_retro_and_s6_closes,
                       refusal_cc9_every_close_of_s6_s7_s9_goes_through_the_one_record,
                       refusal_c2_4_a_length_is_cut_by_code_not_resumed_for,
                       refusal_c2_4_the_doors_of_code_run_before_every_resume,
                       refusal_c2_4_s4_keeps_open_only_when_the_round_will_run,
                       refusal_c2_4_an_owed_s4_repair_round_starts_instead_of_a_new_critic,
                       refusal_n5_the_driver_refuses_as_the_hook_does_and_uses_the_one_packet])
    harness.finish("test_story_run_refusals")


if __name__ == "__main__":
    main()
