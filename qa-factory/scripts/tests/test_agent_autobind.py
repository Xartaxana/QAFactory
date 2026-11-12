#!/usr/bin/env python3
"""SC2-38 (1), node N4: the PostToolUse hook on `Agent|Task` binds the launched agent to its dispatch (`agent_autobind.py`).

The hook joins the id the host's answer carries (`tool_response.agentId`, measured by N0) with the dispatch the prompt of
`story_step start` names, and runs the ONE writer, `story_step.py bind`. Its rule is that it never guesses: a wrong binding
is worse than none, so every doubt is exit 0 with nothing written.

  K4-1 the real `story_step._prompt` text: the id has no final dot; a FOREGROUND agent bound after its handback is confirmed
       is RETURNED once its first prompt names the dispatch (the regex was the wall: `anchored` was always False)
  K4-2 the hook's binding is the conductor's: the same receipt and the same record as `story_step.py bind` by hand (not `bound_at`)
  K4-3 two dispatches of one agent through the hook: the turn-budget notice says `across 2 dispatches`
  K4-4 E1 / E2 / E3 parametrised: no id, a string response, a path, no `Dispatch:` form, two ids, a closed, foreign or absent dispatch
  K4-5 E4 (a refused or crashed bind is ONE signal, exit 0), E7 (two agents, one dispatch), E8 (the conductor bound first)
  K4-9 E5 (Codex), a project that is not onboarded, a launch that is not a factory role, the literal script on junk input

Each key names the mutation it kills (test file: this one): no status check on the record -> K4-4 [closed dispatch]; no role check
-> K4-4 [another role]; a receipt written beside `bind` -> K4-2; the prompt read from anywhere but the first line -> K4-4; no
`pair already there` check -> K4-5 E8; a failed bind raised out of the hook -> K4-5; the tool name `Task` dropped -> K4-1; the
hook on Codex -> K4-9; a string response parsed as JSON -> K4-4 [string response].
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, PLUGIN_ROOT, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_dir, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import agent_autobind as AB  # noqa: E402
import dispatch_liveness as DL  # noqa: E402
import host_dispatch as HD  # noqa: E402
import inject_context  # noqa: E402
import runtime_paths as RP  # noqa: E402
import story_step  # noqa: E402
from controller import Controller  # noqa: E402

import test_bind_dispatch_list as BL  # noqa: E402  (the notice through the guard)
import test_bind_repair_dispatch as BR  # noqa: E402  (repair_story: S0-S3 accepted, one rework dispatch of S3 running)
import test_conductor_stop as TCS  # noqa: E402  (world: a transcript of a role that handed back)

TICKET, ROLE = BR.TICKET, BR.ROLE
AGENT = "a4deff8aea7fe1d21"            # a host id in the shape N0 measured
real_load_map = inject_context.load_map


def with_map():
    inject_context.load_map = lambda: {"roles": {ROLE: {}}}


def without_map():
    inject_context.load_map = real_load_map


def prompt_for(dispatch, role=ROLE, ticket=TICKET):
    return story_step._prompt(ticket, {"id": "S3", "inputs": []}, role, dispatch, [])


def launch(root, prompt, response=None, role=ROLE, tool="Agent", **extra):
    """The PostToolUse event of an `Agent` launch, as the N0 run logged it (the response is the measured shape)."""
    event = {"hook_event_name": "PostToolUse", "tool_name": tool, "session_id": "s-ab", "cwd": str(root),
             "tool_input": {"subagent_type": "qa-factory:" + role, "prompt": prompt, "run_in_background": True},
             "tool_response": response if response is not None else {"isAsync": True, "status": "async_launched",
                                                                      "agentId": AGENT, "canContinueAgent": True}}
    event.update(extra)
    return event


def receipts(root):
    return [(path.name, data) for path, data in HD.receipt_files(root)]


def bind_cli(root, dispatch, agent):
    return run_script("story_step.py", "bind", "--task", TICKET, "--dispatch-id", dispatch, "--agent-id", agent,
                      cwd=root, env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)))


def journal_kinds(root):
    path = RP.record(root, "journal.jsonl")
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.is_file() else []
    return [line.get("kind") for line in lines if line.get("event") == "hook_signal"]


def counting_bind():
    calls = []
    real = AB.bind
    AB.bind = lambda *args: (calls.append(args), real(*args))[1]
    return calls, lambda: setattr(AB, "bind", real)


def k4_1_foreground_is_returned_through_the_real_prompt():
    w = TCS.world("ab-k41-", rows=None)
    try:
        real = story_step._prompt("QA-WAKE", {"id": "S5", "inputs": []}, "qa-code-critic", TCS.DISPATCH, [])
        rows = [TCS.prompt(real), TCS.call(), TCS.ack()]
        w["child"].write_text("\n".join(rows) + "\n", encoding="utf-8")
        # the foreground launch returns its id AFTER the handback is confirmed: the receipt is newer than the acknowledgement,
        # and the agent's file is not named by the receipt - only the prompt (`anchored`) ties the transcript to it
        for path, _ in receipts(w["root"]):
            (w["root"] / "qa-factory" / "state" / "host-dispatches" / path).unlink()
        late = {"agent_id": "zz-not-the-file", "agent_type": "qa-code-critic", "task_id": TCS.TASK, "dispatch_id": TCS.DISPATCH,
                "status": "running", "bound_by": "story_step", "task_name": "zz-not-the-file", "bound_at": TCS.BOUND_AT + 7200}
        HD.binding_path(w["root"], "zz-not-the-file").write_text(json.dumps(late), encoding="utf-8")
        import time
        verdict = DL.claude_stop(w["root"], late, time.time(), DL.thresholds(w["root"]))
        check_eq("K4-1 a foreground agent bound after its confirmed handback: RETURNED (the real prompt anchors it)",
                 (verdict or {}).get("state"), DL.RETURNED)
        # the control: the old `Dispatch id:` spelling is the form that always anchored; and a prompt that names another dispatch does not
        w["child"].write_text("\n".join([TCS.prompt(real.replace(TCS.DISPATCH, "S5-qa-code-critic-9")), TCS.call(), TCS.ack()]) + "\n",
                              encoding="utf-8")
        other = DL.claude_stop(w["root"], late, time.time(), DL.thresholds(w["root"]))
        check_eq("K4-1 control: a first prompt that names ANOTHER dispatch anchors nothing", (other or {}).get("state"), None)
    finally:
        cleanup(w["root"])


def k4_1_the_task_tool_name_binds_too():
    root, task, controller, rework = BR.repair_story("ab-k41b-")
    with_map()
    try:
        for tool in ("Agent", "Task"):
            AB.decide(launch(root, prompt_for(rework), tool=tool, response={"agentId": "agent-" + tool.lower()}))
        names = sorted(data["agent_id"] for _, data in receipts(root))
        check_eq("K4-1 the payload says `Agent`, the host's tool list says `Task`: both launches are bound", names,
                 ["agent-agent", "agent-task"])
    finally:
        without_map()
        cleanup(root)


def k4_2_the_hook_binds_as_the_conductor_does():
    root, task, controller, rework = BR.repair_story("ab-k42a-")
    other, otask, ocontroller, orework = BR.repair_story("ab-k42b-")
    with_map()
    try:
        use_project(root)       # the second `repair_story` moved the process to ITS project
        found = AB.decide(launch(root, prompt_for(rework)))
        check_eq("K4-2 the hook binds the running dispatch of the prompt", found, (TICKET, rework, AGENT))
        use_project(other)
        done = bind_cli(other, orework, AGENT)
        check_eq("K4-2 control: the conductor's own `bind` succeeds", done.returncode, 0)
        mine, theirs = receipts(root), receipts(other)
        check_eq("K4-2 one receipt each, under the same file name", [name for name, _ in mine], [name for name, _ in theirs])

        def shape(data):
            data = dict(data, bound_at=0)
            data["bound_dispatches"] = [dict(item, bound_at=0) for item in data["bound_dispatches"]]
            return data
        check_eq("K4-2 ... the same receipt but `bound_at`", shape(mine[0][1]), shape(theirs[0][1]))
        check_eq("K4-2 ... and the same record of the dispatch in the controller",
                 Controller(task).state()["dispatches"][rework].get("agent_id"),
                 Controller(otask).state()["dispatches"][orework].get("agent_id"))
        check_eq("K4-2 ... the agent id is the host's", Controller(task).state()["dispatches"][rework].get("agent_id"), AGENT)
    finally:
        without_map()
        cleanup(root)
        cleanup(other)


def accept_and_rework_again(root, task, controller, dispatch):
    """The dispatch is accepted by the controller; a second rework of the same stage is running. Returns its id."""
    import hashlib
    evidence = task / "second.txt"
    evidence.write_text("second", encoding="utf-8")
    controller.apply("accept", {"id": dispatch, "status": "accepted", "stage_complete": True, "idempotency_key": "ab-accept",
                                "evidence_refs": [{"path": evidence.name, "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}]})
    request = dict(controller.build_rework_request("S3", ROLE, BR.CASES, "round two"))
    controller.apply("dispatch", request)
    return request["id"]


def k4_3_two_dispatches_of_one_agent():
    root, task, controller, rework = BR.repair_story("ab-k43-")
    with_map()
    try:
        BL.configure(root, turns={"soft": 5, "repeat": 5})
        AB.decide(launch(root, prompt_for(rework)))
        second = accept_and_rework_again(root, task, controller, rework)
        AB.decide(launch(root, prompt_for(second)))
        (_, receipt), = receipts(root)
        check_eq("K4-3 the agent's receipt holds both dispatches, in the order of binding",
                 [item["dispatch_id"] for item in HD.bound_dispatches(receipt)], [rework, second])
        check_eq("K4-3 ... the scalar is the last", receipt["dispatch_id"], second)
        text = BL.fifth_call(root, BL.role_event(AGENT))
        check_in("K4-3 the turn-budget notice says so", f"across 2 dispatches (latest {second})", text)
    finally:
        without_map()
        cleanup(root)


def k4_4_the_hook_never_guesses():
    root, task, controller, rework = BR.repair_story("ab-k44-")
    with_map()
    try:
        good = prompt_for(rework)
        body = good.split("\n", 1)[1]
        cases = [
            ("string response (the host sent text)", dict(response=json.dumps({"agentId": AGENT}))),
            ("response is a list", dict(response=[AGENT])),
            ("no id in the response", dict(response={"status": "async_launched"})),
            ("the id sits under a key the row does not name", dict(response={"uuid": AGENT})),
            ("an id that is a path", dict(response={"agentId": "/root/qa_x"})),
            ("an empty id", dict(response={"agentId": ""})),
            ("an id that is not a string", dict(response={"agentId": 17})),
            ("a launch error", dict(response={"is_error": True, "content": "refused"})),
            ("a prompt without the Dispatch form", dict(prompt=f"You are {ROLE}. Ticket: {TICKET}.\n" + body)),
            ("the form is not the first line", dict(prompt="Please start.\n" + good)),
            ("the form misses its last dot", dict(prompt=good.replace(f"Dispatch: {rework}.", f"Dispatch: {rework}", 1))),
            ("two dispatch ids in the text", dict(prompt=good + "\nDispatch: S3-qa-worker-99.")),
            ("the old spelling is a second id", dict(prompt=good + "\nDispatch id: S3-qa-worker-99")),
            ("another role in the prompt", dict(prompt=good.replace(f"You are {ROLE}.", "You are qa-other.", 1))),
            ("a prompt that is no text", dict(prompt=["a"])),
            ("a dispatch the story does not have", dict(prompt=prompt_for("S3-qa-worker-77"))),
            ("another ticket", dict(prompt=prompt_for(rework, ticket="QA-2"))),
            ("a ticket that climbs", dict(prompt=prompt_for(rework, ticket=".."))),
            ("a tool that is no launch", dict(tool="Write")),
            ("a launch of a role the factory does not know", dict(role="general-purpose")),
        ]
        for label, change in cases:
            event = launch(root, change.pop("prompt", good), **change)
            before = receipts(root)
            check_eq(f"K4-4 [{label}] binds nothing", AB.decide(event), None)
            check_eq(f"K4-4 [{label}] ... and writes nothing", receipts(root), before)
        # RN1-1: the keys are the row `launch_id_keys`, read by `host_adapter.launch_id_of` (kills: `agent_id_of` reading one key);
        # `plan` is the pure half of the hook, so nothing is bound before the control below
        check_eq("K4-4 RN1-1 the older key `agent_id` of the row still binds",
                 AB.plan(launch(root, good, response={"agent_id": "old-key-agent"}), Path(root)), (TICKET, rework, "old-key-agent"))
        check_eq("K4-4 RN1-1 an empty first key counts as absent: the next key of the row binds",
                 AB.plan(launch(root, good, response={"agentId": "", "agent_id": "next-key-agent"}), Path(root)),
                 (TICKET, rework, "next-key-agent"))
        check_eq("K4-4 RN1-1 several keys: the first in row order wins",
                 AB.plan(launch(root, good, response={"agent_id": "zz-older", "agentId": AGENT}), Path(root)), (TICKET, rework, AGENT))
        check_eq("K4-4 the control: the same launch with the real prompt and a plain response IS bound",
                 AB.decide(launch(root, good)), (TICKET, rework, AGENT))
    finally:
        without_map()
        cleanup(root)
    # a dispatch the controller has CLOSED, and one of ANOTHER role, are never washed into a binding
    root, task, controller, rework = BR.repair_story("ab-k44b-")
    with_map()
    try:
        second = accept_and_rework_again(root, task, controller, rework)
        check_eq("K4-4 [closed dispatch] the accepted one binds nothing", AB.decide(launch(root, prompt_for(rework))), None)
        check_eq("K4-4 [closed dispatch] ... and the receipts are empty", receipts(root), [])
        inject_context.load_map = lambda: {"roles": {ROLE: {}, "qa-other": {}}}
        check_eq("K4-4 [another role] the record is qa-worker's: a prompt and a launch of qa-other bind nothing",
                 AB.decide(launch(root, prompt_for(second, role="qa-other"), role="qa-other")), None)
        check_eq("K4-4 control: the running dispatch of the right role binds",
                 AB.decide(launch(root, prompt_for(second))), (TICKET, second, AGENT))
    finally:
        without_map()
        cleanup(root)


def k4_5_failure_and_repeats():
    root, task, controller, rework = BR.repair_story("ab-k45-")
    with_map()
    try:
        # E4: a refused bind, a crashed one, a timed-out one: ONE signal each, the hook returns (never raises)
        real = AB.bind
        for label, answer in (("refused", (2, "stage_done refused")), ("crashed", (-1, "OSError")), ("timed out", (-1, "TimeoutExpired"))):
            AB.bind = lambda *args, answer=answer: answer
            before = journal_kinds(root)
            AB.decide(launch(root, prompt_for(rework)))
            check_eq(f"K4-5 E4 [{label}] one signal of its own kind is written", journal_kinds(root)[len(before):], ["auto_bind_failed"])
        AB.bind = real
        check_eq("K4-5 E4 no receipt was written by the failures", receipts(root), [])
        real_run = subprocess.run
        subprocess.run = lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired("bind", 1))
        try:
            check_eq("K4-5 E4 `bind` itself turns a timeout into code -1", AB.bind(root, TICKET, rework, AGENT)[0], -1)
        finally:
            subprocess.run = real_run
        # E7: a repeated launch with the same dispatch and a different agent: both receipts hold the pair, the record keeps the last
        AB.decide(launch(root, prompt_for(rework), response={"agentId": "first-agent"}))
        AB.decide(launch(root, prompt_for(rework), response={"agentId": "second-agent"}))
        check_eq("K4-5 E7 both agents hold the pair", sorted(data["agent_id"] for _, data in receipts(root)),
                 ["first-agent", "second-agent"])
        check_eq("K4-5 E7 last bind wins on the record", Controller(task).state()["dispatches"][rework].get("agent_id"), "second-agent")
        # E8: the same agent again: the pair is there, nothing runs, the receipt is byte for byte what it was
        path = HD.binding_path(root, "second-agent")
        before = path.read_bytes()
        calls, restore = counting_bind()
        try:
            check_eq("K4-5 E8 the same launch again binds nothing", AB.decide(launch(root, prompt_for(rework),
                     response={"agentId": "second-agent"})), None)
        finally:
            restore()
        check_eq("K4-5 E8 ... `bind` was not run", calls, [])
        check_eq("K4-5 E8 ... and `bound_at` did not move: the receipt is the same bytes", path.read_bytes(), before)
    finally:
        without_map()
        cleanup(root)
    # E8, the other order: the conductor bound first; the hook leaves it alone
    root, task, controller, rework = BR.repair_story("ab-k45b-")
    with_map()
    try:
        bind_cli(root, rework, AGENT)
        before = HD.binding_path(root, AGENT).read_bytes()
        calls, restore = counting_bind()
        try:
            AB.decide(launch(root, prompt_for(rework)))
        finally:
            restore()
        check_eq("K4-5 E8 the conductor bound first: no second bind", calls, [])
        check_eq("K4-5 E8 ... one entry, the receipt untouched", HD.binding_path(root, AGENT).read_bytes(), before)
    finally:
        without_map()
        cleanup(root)


def k4_9_hosts_projects_and_the_script():
    root, task, controller, rework = BR.repair_story("ab-k49-")
    with_map()
    try:
        for label, extra in (("a Codex turn id", {"turn_id": "t-1"}), ("a Codex host marker", {"host": "codex"})):
            check_eq(f"K4-9 E5 [{label}] binds nothing", AB.decide(launch(root, prompt_for(rework), **extra)), None)
        check_eq("K4-9 E5 ... and writes nothing", receipts(root), [])
        bare = temp_dir("ab-k49-bare-")
        try:
            check_eq("K4-9 a project that is not onboarded: nothing, no qa-factory/ appears",
                     (AB.plan(launch(bare, prompt_for(rework)), bare), (bare / "qa-factory").exists()), (None, False))
        finally:
            cleanup(bare)
    finally:
        without_map()
        cleanup(root)
    # the literal script: junk and empty input are exit 0 and silent; the wiring names it on `Agent|Task`
    root = temp_dir("ab-k49-script-")
    try:
        for label, text in (("empty stdin", ""), ("not JSON", "{broken"), ("a list", "[1]"), ("an event with nothing", "{}"),
                            ("a non-Agent tool", json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Write"}))):
            done = subprocess.run([sys.executable, "-B", str(SCRIPTS / "agent_autobind.py")], input=text, capture_output=True,
                                  text=True, encoding="utf-8", cwd=str(root), env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)),
                                  timeout=60)
            check_eq(f"K4-9 the script on [{label}]: exit 0, silent", (done.returncode, done.stdout, done.stderr), (0, "", ""))
        check_eq("K4-9 ... and nothing was created", sorted(root.iterdir()), [])
    finally:
        cleanup(root)
    wiring = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    entry = [e for e in wiring["hooks"]["PostToolUse"] if "agent_autobind.py" in json.dumps(e)]
    check_eq("K4-9 hooks.json: ONE PostToolUse entry runs agent_autobind.py", len(entry), 1)
    check_eq("K4-9 ... on `Agent|Task`, synchronous (no race with the conductor's first message)",
             (entry[0]["matcher"], [h["async"] for h in entry[0]["hooks"]]), ("Agent|Task", [False]))
    codex = (PLUGIN_ROOT / "hooks" / "codex.json").read_text(encoding="utf-8")
    check_not_in("K4-9 E5 the Codex wiring does not carry it (host_dispatch.py is its road)", "agent_autobind", codex)


def k4_1_an_unbound_stop_on_claude_does_not_record_a_return():
    """K4-1 (spec): the stop of a role that is not bound, on Claude, with the PARENT's `transcript_path`: `record_return` is not
    called, as today (the `returned_unaccepted` at the stop is class OH3-16). Mutant: resolve the dispatch from the host id."""
    import subagent_journal as SJ
    w = TCS.world("ab-k41c-")
    try:
        event = {"hook_event_name": "SubagentStop", "agent_id": TCS.AGENT, "agent_type": "qa-factory:qa-code-critic",
                 "session_id": TCS.SESSION, "transcript_path": str(w["parent"]), "cwd": str(w["root"])}
        scope = {"task": TCS.TASK, "dispatch": TCS.AGENT}
        check_eq("K4-1 stop: a host id alone is no dispatch of the story", SJ._story_dispatch(event, scope), "")
        calls = []
        import controller as C
        real = C.Controller.record_return
        C.Controller.record_return = lambda self, *a, **k: calls.append(a) or True
        try:
            SJ.record_return(event, {"agent": ""}, scope)
            check_eq("K4-1 stop: `record_return` is not called for an unbound role", calls, [])
            SJ.record_return(event, {"agent": ""}, dict(scope, dispatch=TCS.DISPATCH))
            check_eq("K4-1 stop control: with the dispatch resolved it IS called", len(calls), 1)
        finally:
            C.Controller.record_return = real
    finally:
        cleanup(w["root"])


def k3_8_a_backslash_name_is_not_a_path_component():
    """F-11: `host_adapter.subagent_transcript_of` names nothing for a name with a backslash (`a\\b` is two components on
    Windows). Mutant: the old regex `[\\/:]` (a plain slash, no backslash)."""
    import host_adapter as HA
    root = temp_dir("ab-k38-")
    try:
        parent = root / "s.jsonl"
        parent.write_text("{}\n", encoding="utf-8")
        folder = root / "s" / "subagents"
        (folder / "agent-x").mkdir(parents=True)
        (folder / "agent-x" / "y.jsonl").write_text("{}\n", encoding="utf-8")
        (folder / "agent-ok.jsonl").write_text("{}\n", encoding="utf-8")
        check_eq("F-11 control: a plain name finds its file", HA.subagent_transcript_of(str(parent), ["ok"]), folder / "agent-ok.jsonl")
        check_eq("F-11 a name with a backslash names nothing", HA.subagent_transcript_of(str(parent), ["x\\y"]), None)
        check_eq("F-11 a name with a slash names nothing", HA.subagent_transcript_of(str(parent), ["x/y"]), None)
    finally:
        cleanup(root)


def f10_one_strict_reader_of_the_controller_record():
    """F-10: `agent_autobind` and `conductor_stop` read the controller's record through `host_dispatch.controller_record`;
    every doubt is None. Mutant: a twin copy that answers True on a ticket with a slash."""
    import conductor_stop as CS
    w = TCS.world("ab-f10-")
    try:
        root = w["root"]
        check_eq("F-10 the record of a running dispatch", (HD.controller_record(root, TCS.TASK, TCS.DISPATCH) or {}).get("status"), "running")
        for label, task, dispatch in (("no dispatch", TCS.TASK, ""), ("no ticket", "", TCS.DISPATCH), ("dot ticket", "..", TCS.DISPATCH),
                                      ("a slash", "a/b", TCS.DISPATCH), ("a backslash", "a\\b", TCS.DISPATCH), ("a colon", "a:b", TCS.DISPATCH),
                                      ("an unknown dispatch", TCS.TASK, "S9-none-1"), ("an unknown story", "QA-NONE", TCS.DISPATCH)):
            check_eq(f"F-10 [{label}]: None", HD.controller_record(root, task, dispatch), None)
        check_eq("F-10 the wake's reader says running", CS._running(root, TCS.TASK, TCS.DISPATCH), True)
        check_eq("F-10 ... and not for a path ticket", CS._running(root, "a\\b", TCS.DISPATCH), False)
        check_eq("F-10 the bind's reader needs the role too", (AB._record_matches(root, TCS.TASK, TCS.DISPATCH, "qa-code-critic"),
                                                                AB._record_matches(root, TCS.TASK, TCS.DISPATCH, "qa-scout")), (True, False))
    finally:
        cleanup(w["root"])


def k1_the_claude_hook_binds_the_doctors_probe():
    """RN1-1 B-1 / K1: on Claude the PostToolUse `Agent|Task` entry is THIS hook; the probe launch (not a story prompt, not
    onboarded as a role launch) binds `injection.agent_id` from the host's answer, and an answer with no id records the reason.
    Driven through the literal script on stdin, as the host runs it. Kills (this file): the `note_probe` call removed from
    `decide` -> every K1 line; the call placed after the story filters -> K1 (the probe prompt is no story prompt)."""
    root = temp_dir("ab-k1-")
    store = root / "qa-factory" / "state" / "host-probe.json"
    try:
        def put(tool_use_id="spawn-1", **proof):
            store.parent.mkdir(parents=True, exist_ok=True)
            store.write_text(json.dumps({"session_id": "s-ab", "injection": {
                "challenge": "0" * 32, "status": "emitted", "tool_use_id": tool_use_id, **proof}}), encoding="utf-8")

        def run(response, tool_use_id="spawn-1", prompt="QA_FACTORY_CONTEXT_PROBE", **extra):
            event = launch(root, prompt, response, role="qa-scout", tool_use_id=tool_use_id, **extra)
            done = subprocess.run([sys.executable, "-B", str(SCRIPTS / "agent_autobind.py")], input=json.dumps(event),
                                  capture_output=True, text=True, encoding="utf-8", cwd=str(root), timeout=60,
                                  env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)))
            check_eq("K1 the hook exits 0, silent", (done.returncode, done.stdout, done.stderr), (0, "", ""))
            return json.loads(store.read_text(encoding="utf-8"))["injection"]

        put()
        check_eq("K1 background launch: the proof holds the id of the answer",
                 run({"isAsync": True, "status": "async_launched", "agentId": "add467ff", "canContinueAgent": True}).get("agent_id"),
                 "add467ff")
        put()
        check_eq("K1 foreground launch: the same",
                 run({"status": "completed", "agentId": "add467ff", "content": []}).get("agent_id"), "add467ff")
        put()
        proof = run({"isAsync": True, "status": "async_launched"})
        check_eq("K1 an answer with no id: nothing bound, the reason recorded", (proof.get("agent_id"), proof.get("no_launch_id")),
                 (None, True))
        put()
        proof = run({"agentId": "other-launch"}, tool_use_id="another-call")
        check_eq("K1 negative control: a launch that is not the probe's call writes nothing",
                 (proof.get("agent_id"), proof.get("no_launch_id")), (None, None))
        put()
        proof = run({"agentId": "story-agent"}, tool_use_id="story-call", prompt="You are qa-scout. Ticket: QA-1. Dispatch: S1-qa-scout-1.")
        check_eq("K1 negative control: a role dispatch of the story (other call) leaves the probe unbound", proof.get("agent_id"), None)
        put()
        check_eq("K1 Codex-shaped event: the hook leaves the probe to host_dispatch",
                 run({"agentId": "x"}, turn_id="t-1").get("agent_id"), None)
    finally:
        cleanup(root)


def main():
    k1_the_claude_hook_binds_the_doctors_probe()
    k4_1_an_unbound_stop_on_claude_does_not_record_a_return()
    k3_8_a_backslash_name_is_not_a_path_component()
    f10_one_strict_reader_of_the_controller_record()
    k4_1_foreground_is_returned_through_the_real_prompt()
    k4_1_the_task_tool_name_binds_too()
    k4_2_the_hook_binds_as_the_conductor_does()
    k4_3_two_dispatches_of_one_agent()
    k4_4_the_hook_never_guesses()
    k4_5_failure_and_repeats()
    k4_9_hosts_projects_and_the_script()
    finish("test_agent_autobind")


if __name__ == "__main__":
    main()
