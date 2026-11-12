#!/usr/bin/env python3
"""DC1-11 (batch driver-controller/1, run 14857 finding A2): an agent that takes several dispatches keeps all its bindings,
and the TURN BUDGET notice says what its count is.

Run 14857 sent four dispatches (`S6-qa-runner-1..4`) as messages to ONE agent. The receipt `state/host-dispatches/<sha(agent)>.json` is
one per agent and `story_step.py bind` overwrote its `dispatch_id`, so it forgot three of the four; the TURN BUDGET said "this dispatch
has made N" at 60, 90 and 120 to four dispatches. Now `bind` also writes `bound_dispatches` (the scalar `dispatch_id` stays the LAST
binding: no existing reader changes its answer), `host_dispatch.bound_dispatches` is its one reader, and the notice names the AGENT
and, from two dispatches up, how many it spans.

  K1-1 two binds of one agent: the list holds both, the scalar is the second; dispatch_liveness / worker_lifecycle answer by the scalar
  K1-2 the same bind twice: same length, the first element keeps its bound_at
  K1-3 a receipt written before the field (scalar only): the scalar is the first element
  K1-4 a receipt that is broken, empty or no object; a field that is no list or holds junk (parameterized)
  K1-5 stage_done refused: the receipt and the list are not touched
  K1-6 a bind of an already accepted dispatch (E8): the element is added, the scalar is overwritten as today
  K1-7 the same dispatch id in two stories is two elements; the pair is the identity
  K1-8 `turn_budget.message`: three forms, one ending, nothing of the orchestrator's, no "this dispatch has made"
  K1-9 `check` through the guard: 2 dispatches say so; no receipt / broken receipt / Codex spawn receipt / a session's receipt do not
  K1-10 the finding's fixture: 4 bindings of one agent, notices at 60, 90, 120 say `across 4 dispatches`, one counter file

Each key names the mutation it kills (test file: this one): `bind` does not read the old receipt -> K1-1; dedup by dispatch id alone ->
K1-7; dedup removed -> K1-2; a repeat moves bound_at -> K1-2; no scalar-without-field branch -> K1-3; the reader keeps junk -> K1-4;
the list written before the stage_done refusal -> K1-5; the scalar becomes the FIRST binding -> K1-1; the receipt read outside the `try`
-> K1-9; the threshold `dispatches >= 2` becomes `>= 1` -> K1-8; the receipt read before the notice is due -> K1-9.
"""
import contextlib
import io
import json
import os
import sys
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, run_script  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import dispatch_liveness as LIVE  # noqa: E402
import guard_pre_tool as G  # noqa: E402
import hooklib  # noqa: E402
import host_dispatch as HD  # noqa: E402
import story_step  # noqa: E402
import turn_budget as TB  # noqa: E402
import worker_lifecycle as WL  # noqa: E402
from controller import Controller  # noqa: E402

import test_bind_repair_dispatch as BR  # noqa: E402  (repair_story: S0-S3 accepted, one rework dispatch of S3 running)

TICKET = BR.TICKET
CONTROL_LINE = "the turn budget stops no call."


def env_of(root):
    return dict(os.environ, CLAUDE_PROJECT_DIR=str(root))


def bind_cli(root, dispatch, agent):
    return run_script("story_step.py", "bind", "--task", TICKET, "--dispatch-id", dispatch, "--agent-id", agent,
                      cwd=root, env=env_of(root))


def receipt_path(root, agent):
    return HD.binding_path(root, agent)


def receipt_of(root, agent):
    return json.loads(receipt_path(root, agent).read_text(encoding="utf-8"))


def ids_of(receipt):
    return [item["dispatch_id"] for item in HD.bound_dispatches(receipt)]


def k1_1_2_6_two_binds_and_the_same_bind_twice():
    root, task, controller, rework = BR.repair_story("qa-bindlist-a-")
    try:
        # E8 first: dS2 is already accepted, so stage_done refuses and bind writes the host receipt only, as before
        done = bind_cli(root, "dS2", "A1")
        check_eq("K1-6 bind of an accepted dispatch: exit 0 as today", done.returncode, 0)
        check_in("K1-6 ... the same note, the same line", "Only the host receipt is written", done.stdout)
        first = receipt_of(root, "A1")
        check_eq("K1-6/K1-1 the first binding: a list of one", ids_of(first), ["dS2"])
        check_eq("K1-6 ... and the scalar is that dispatch", first["dispatch_id"], "dS2")
        check_eq("K1-6 ... the controller's record still holds no agent id (the list is about the receipt)",
                 Controller(task).state()["dispatches"]["dS2"].get("agent_id"), None)
        check_eq("K1-1 the element carries the story", HD.bound_dispatches(first)[0]["task_id"], TICKET)
        stamp = HD.bound_dispatches(first)[0]["bound_at"]

        done = bind_cli(root, rework, "A1")
        check_eq("K1-1 a second bind of another dispatch to the same agent: exit 0", done.returncode, 0)
        second = receipt_of(root, "A1")
        check_eq("K1-1 the list holds BOTH, in the order of the first binding", ids_of(second), ["dS2", rework])
        check_eq("K1-1 the scalar is the LAST binding", second["dispatch_id"], rework)
        check_eq("K1-1 the first element keeps its bound_at", HD.bound_dispatches(second)[0]["bound_at"], stamp)
        # the control: the readers of the scalar answer as before
        found = [r for r in LIVE.host_bindings(root) if r.get("agent_id") == "A1"]
        check_eq("K1-1 control: dispatch_liveness.host_bindings reads one record, with the scalar",
                 [r.get("dispatch_id") for r in found], [rework])
        check_eq("K1-1 control: worker_lifecycle.active_binding answers for the scalar dispatch",
                 (WL.active_binding(root, rework, TICKET) or {}).get("agent_id"), "A1")
        check_eq("K1-1 control: ... and does not for the earlier one", WL.active_binding(root, "dS2", TICKET), None)

        done = bind_cli(root, rework, "A1")
        again = receipt_of(root, "A1")
        check_eq("K1-2 the same bind twice: same length", ids_of(again), ["dS2", rework])
        check_eq("K1-2 ... and the same first bound_at", [i["bound_at"] for i in HD.bound_dispatches(again)][0], stamp)
        check_eq("K1-2 ... and the second element's bound_at does not move either",
                 HD.bound_dispatches(again)[1]["bound_at"], HD.bound_dispatches(second)[1]["bound_at"])
    finally:
        cleanup(root)


def k1_3_a_receipt_written_before_the_field():
    root, task, controller, rework = BR.repair_story("qa-bindlist-b-")
    try:
        path = receipt_path(root, "A2")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"agent_id": "A2", "agent_type": "qa-worker", "task_id": TICKET, "dispatch_id": "dS1",
                                    "status": "running", "bound_by": "story_step", "bound_at": 111.5}), encoding="utf-8")
        old = json.loads(path.read_text(encoding="utf-8"))
        check_eq("K1-3 the reader: the scalar is one element, with the receipt's time",
                 HD.bound_dispatches(old), [{"task_id": TICKET, "dispatch_id": "dS1", "bound_at": 111.5}])
        bind_cli(root, rework, "A2")
        after = receipt_of(root, "A2")
        check_eq("K1-3 an in-flight story loses nothing: the scalar is the first element, the new bind the second",
                 ids_of(after), ["dS1", rework])
        check_eq("K1-3 ... with the old time", HD.bound_dispatches(after)[0]["bound_at"], 111.5)
        # the same dispatch bound again over a scalar-only receipt is not a second element
        path.write_text(json.dumps(dict(old, dispatch_id=rework)), encoding="utf-8")
        bind_cli(root, rework, "A2")
        check_eq("K1-3 a scalar equal to the new pair is not counted twice", ids_of(receipt_of(root, "A2")), [rework])
    finally:
        cleanup(root)


BROKEN_RECEIPTS = [
    ("garbage", "{not json"),
    ("empty file", ""),
    ("a list, not an object", "[1, 2]"),
    ("a string", '"dispatch"'),
]


def k1_4_a_receipt_that_is_not_one():
    root, task, controller, rework = BR.repair_story("qa-bindlist-c-")
    try:
        for label, text in BROKEN_RECEIPTS:
            agent = "A-" + label.split()[0]
            path = receipt_path(root, agent)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            done = bind_cli(root, rework, agent)
            check_eq(f"K1-4 [{label}] bind still succeeds", done.returncode, 0)
            check_eq(f"K1-4 [{label}] the file is rewritten as today, with one element",
                     ids_of(receipt_of(root, agent)), [rework])
    finally:
        cleanup(root)
    pair = {"task_id": "QA-1", "dispatch_id": "D1", "bound_at": 5}
    junk_cases = [
        ("no field, no scalar", {}, []),
        ("receipt is a list", [pair], []),
        ("receipt is None", None, []),
        ("receipt is a string", "D1", []),
        ("field is a string", {"bound_dispatches": "D1", "dispatch_id": "S"}, ["S"]),
        ("field is a number, no scalar", {"bound_dispatches": 7}, []),
        ("field is an object", {"bound_dispatches": pair, "dispatch_id": "S"}, ["S"]),
        ("elements are strings", {"bound_dispatches": ["D1", "D2"]}, []),
        ("dispatch_id is a number", {"bound_dispatches": [{"dispatch_id": 7}]}, []),
        ("dispatch_id is empty", {"bound_dispatches": [{"dispatch_id": ""}, pair]}, ["D1"]),
        ("dispatch_id is None", {"bound_dispatches": [{"dispatch_id": None}, None, pair]}, ["D1"]),
        ("dispatch_id is a list", {"bound_dispatches": [{"dispatch_id": ["D1"]}]}, []),
        ("scalar is a number", {"dispatch_id": 7}, []),
        ("scalar is empty", {"dispatch_id": ""}, []),
        ("an empty list wins over the scalar", {"bound_dispatches": [], "dispatch_id": "S"}, []),
    ]
    for label, receipt, expected in junk_cases:
        try:
            got = [item["dispatch_id"] for item in HD.bound_dispatches(receipt)]
        except Exception as exc:  # the reader never raises
            got = f"raised {type(exc).__name__}"
        check_eq(f"K1-4 reader [{label}]", got, expected)
    odd = HD.bound_dispatches({"bound_dispatches": [{"dispatch_id": "D1", "task_id": 5, "bound_at": True},
                                                    {"dispatch_id": "D2", "bound_at": "soon"}]})
    check_eq("K1-4 a task id that is no string is '' and a bound_at that is no number (a bool included) is 0",
             odd, [{"task_id": "", "dispatch_id": "D1", "bound_at": 0}, {"task_id": "", "dispatch_id": "D2", "bound_at": 0}])
    # junk inside a real receipt does not stop the next bind and does not survive it
    root, task, controller, rework = BR.repair_story("qa-bindlist-c2-")
    try:
        path = receipt_path(root, "A-junk")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"agent_id": "A-junk", "bound_dispatches": ["x", {"dispatch_id": 3}, pair]}),
                        encoding="utf-8")
        bind_cli(root, rework, "A-junk")
        check_eq("K1-4 junk elements are dropped by the next bind, the real one stays",
                 ids_of(receipt_of(root, "A-junk")), ["D1", rework])
    finally:
        cleanup(root)


def k1_5_a_refused_bind_is_not_counted():
    root, task, controller, rework = BR.repair_story("qa-bindlist-d-")
    try:
        bind_cli(root, rework, "A5")
        before = receipt_path(root, "A5").read_bytes()
        real = story_step._run
        story_step._run = lambda *a, **k: (2, "stage_done: refused by the test")
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                code = story_step.bind(Namespace(task=TICKET, dispatch_id="dS2", agent_id="A5"))
                fresh = story_step.bind(Namespace(task=TICKET, dispatch_id="dS2", agent_id="A6"))
        finally:
            story_step._run = real
        check_eq("K1-5 stage_done refused: bind returns its code", (code, fresh), (2, 2))
        check_eq("K1-5 ... the receipt of the agent is byte for byte what it was", receipt_path(root, "A5").read_bytes(), before)
        check_eq("K1-5 ... and a refused first bind writes no receipt at all", receipt_path(root, "A6").exists(), False)
    finally:
        cleanup(root)


def k1_7_the_pair_is_the_identity():
    held = HD.with_bound_dispatch({}, "QA-1", "S5-qa-automator-12", 10.0)
    both = HD.with_bound_dispatch({"bound_dispatches": held}, "QA-2", "S5-qa-automator-12", 20.0)
    check_eq("K1-7 the same dispatch id in two stories is two elements",
             [(i["task_id"], i["dispatch_id"]) for i in both], [("QA-1", "S5-qa-automator-12"), ("QA-2", "S5-qa-automator-12")])
    again = HD.with_bound_dispatch({"bound_dispatches": both}, "QA-2", "S5-qa-automator-12", 99.0)
    check_eq("K1-7 the same pair again adds nothing and keeps the first time", again, both)
    check_eq("K1-7 a blank dispatch adds nothing", HD.with_bound_dispatch({"bound_dispatches": both}, "QA-2", "", 1.0), both)
    check_eq("K1-7 the function is pure: the receipt it was given is not touched",
             (len(held), len(both)), (1, 2))


def k1_8_the_texts():
    forms = {
        "agent, one dispatch": TB.message(60, 60, role=True, dispatches=1, latest="D1"),
        "agent, none known": TB.message(60, 60, role=True),
        "agent, several": TB.message(90, 60, role=True, dispatches=2, latest="D2"),
        "role without an agent id": TB.message(60, 60, role=True, scope="role"),
        "orchestrator": TB.message(60, 60, "QA-1", "S4"),
        "orchestrator, no stage": TB.message(60, 60, "QA-1"),
    }
    for name, text in forms.items():
        check(f"K1-8 [{name}] ends with the control line", text.endswith(CONTROL_LINE), text[-80:])
        check_not_in(f"K1-8 [{name}] never says 'this dispatch has made'", "this dispatch has made", text)
    roles = {k: v for k, v in forms.items() if not k.startswith("orchestrator")}
    for name, text in roles.items():
        check_not_in(f"K1-8 [{name}] carries none of the orchestrator's advice", "stage_done", text)
        check_not_in(f"K1-8 [{name}] ... nor its window", "this window has", text)
        check_in(f"K1-8 [{name}] carries the role's advice", "hand back your digest", text)
    check_in("K1-8 row 1", "this agent has made 60 tool calls — your own, counted from your first one, whichever dispatch they "
             "belonged to ", forms["agent, one dispatch"])
    check_eq("K1-8 none known reads as one", forms["agent, none known"].replace("90", "60"),
             forms["agent, one dispatch"])
    check_in("K1-8 row 2", "this agent has made 90 tool calls across 2 dispatches (latest D2) — your own; the count is this "
             "agent's context, not the current dispatch alone ", forms["agent, several"])
    check_in("K1-8 row 3", "this role has made 60 tool calls in this session — every dispatch of this role, the host names no "
             "agent ", forms["role without an agent id"])
    check_not_in("K1-8 the plain form does not claim a number of dispatches", "across", forms["agent, one dispatch"])


# ---- the notice through the guard: K1-9, K1-10 ----

SESSION = "s-dc1-11"
SOFT = {"turns": {"soft": 5, "repeat": 5}}


def configure(root, **blocks):
    path = root / "qa-factory" / "config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg.update(blocks)
    path.write_text(json.dumps(cfg), encoding="utf-8")


def role_event(agent, **extra):
    """A tool event of a role, as the guard gets it: through `host_dispatch.enrich`, never with `host_binding` laid by hand."""
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "session_id": SESSION, "agent_id": agent,
             "agent_type": "qa-factory:qa-worker", "tool_input": {"command": "ls"}}
    event.update(extra)
    return HD.enrich(event)


def seed(root, event, count):
    path = TB.counter_path(SESSION, event)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"scheme": TB.SCHEME, "count": count, "started": "2026-10-30T00:00:00+00:00", "notified": 0}),
                    encoding="utf-8")


def fifth_call(root, event):
    """The text of the role's FIFTH call (soft 5) through the guard's own `budget_notice`, in this process."""
    seed(root, event, 4)
    return G._noticed(G.budget_notice, event, SOFT) or ""


def k1_9_the_notice_through_the_guard():
    root, task, controller, rework = BR.repair_story("qa-bindlist-e-")
    try:
        configure(root, turns={"soft": 5, "repeat": 5})
        bind_cli(root, "dS2", "A9")
        bind_cli(root, rework, "A9")
        text = fifth_call(root, role_event("A9"))
        check_in("K1-9 an agent bound to 2 dispatches is told so, with the latest", f"across 2 dispatches (latest {rework})", text)
        check_in("K1-9 ... and that the count is the agent's context", "this agent's context", text)
        check_eq("K1-9 ... in the agent's words", text.startswith("TURN BUDGET: this agent has made 5 tool calls across 2"), True)

        text = fifth_call(root, role_event("A-nobody"))
        check_in("K1-9/E12 no receipt: the plain form", "this agent has made 5 tool calls — your own, counted from your first one", text)
        check_not_in("K1-9/E12 ... no dispatch count", "across", text)

        # a broken receipt: found by enrich it names nothing; laid straight on the event it is read at the notice and fails soft
        path = receipt_path(root, "A-broken")
        path.write_text("{not json", encoding="utf-8")
        text = fifth_call(root, role_event("A-broken"))
        check_in("K1-9/E12 a broken receipt: the plain form, no exception", "this agent has made 5 tool calls — your own", text)
        for label, body in BROKEN_RECEIPTS:
            path.write_text(body, encoding="utf-8")
            text = fifth_call(root, role_event("A-broken", host_binding=str(path)))
            check_not_in(f"K1-9/E12 [{label}] read at the notice: the plain form, no count", "across", text)
            check_in(f"K1-9/E12 [{label}] ... and still a notice", CONTROL_LINE, text)
        text = fifth_call(root, role_event("A-broken", host_binding=str(root / "no" / "such.json")))
        check_not_in("K1-9/E12 a receipt path that is not a file: the plain form", "across", text)

        # AR-5, Codex: the spawn receipt (hashed by the uuid, no list) and the path receipt `bind` wrote; the uuid reaches the spawn one
        uuid = "019f0000-0000-7000-8000-000000000001"
        spawn = {"agent_id": uuid, "agent_type": "qa-worker", "task_id": TICKET, "status": "running", "dispatch_id": rework,
                 "task_name": "qa_x", "task_path": "/root/qa_x", "parent_session_id": SESSION, "host": "codex",
                 "bound_at": 1.0}
        receipt_path(root, uuid).write_text(json.dumps(spawn), encoding="utf-8")
        bind_cli(root, "dS2", "/root/qa_x")
        bind_cli(root, rework, "/root/qa_x")
        check_eq("K1-9/AR-5 the path receipt holds 2", ids_of(receipt_of(root, "/root/qa_x")), ["dS2", rework])
        text = fifth_call(root, role_event(uuid))
        check_in("K1-9/AR-5 Codex: the spawn receipt has no list, so row 1 (an undercount, never an overcount)",
                 "this agent has made 5 tool calls — your own, counted from your first one", text)
        check_not_in("K1-9/AR-5 ... and no dispatch count", "across", text)

        # E12: the driver's receipt is keyed by the SESSION; an agent without a receipt of its own must not be told its count
        bind_cli(root, "dS2", SESSION)
        bind_cli(root, rework, SESSION)
        check_eq("K1-9/E12 the session's receipt holds 2", ids_of(receipt_of(root, SESSION)), ["dS2", rework])
        event = role_event("A-sub")
        check_eq("K1-9/E12 enrich did find the session's receipt for the agent", bool(event.get("host_binding")), True)
        text = fifth_call(root, event)
        check_not_in("K1-9/E12 ... and the agent is NOT told the session's 2 dispatches", "across", text)
        check_in("K1-9/E12 ... the plain form", "this agent has made 5 tool calls — your own", text)

        # E14: no agent id, only the role: row 3, the receipt is not read
        reads = []
        real_read = hooklib.read_json
        hooklib.read_json = lambda path, *a, **k: (reads.append(str(path)), real_read(path, *a, **k))[1]
        try:
            event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "session_id": SESSION,
                     "agent_type": "qa-factory:qa-worker", "tool_input": {"command": "ls"}}
            seed(root, event, 4)
            text = G._noticed(G.budget_notice, event, SOFT) or ""
        finally:
            hooklib.read_json = real_read
        check_in("K1-9/E14 a host with no agent id: this role, in this session", "this role has made 5 tool calls in this session", text)
        check_eq("K1-9/E14 ... and no receipt was read for it", [r for r in reads if "host-dispatches" in r], [])

        # F7 (critic t-217): the receipt read sits inside `bound_count`'s `try`. `read_json(errors=Exception)` does not
        # raise on the broken files above, so a raising reader (the receipt only) is what kills a read moved outside it.
        def raising(path, *a, **k):
            if "host-dispatches" in str(path):
                raise OSError("the receipt cannot be read")
            return real_read(path, *a, **k)
        event = role_event("A9")   # enriched BEFORE the swap: `enrich` has its own reader
        hooklib.read_json = raising
        try:
            text = fifth_call(root, event)
        finally:
            hooklib.read_json = real_read
        check_in("K1-9/F7 a receipt read that raises: the plain form", "this agent has made 5 tool calls — your own", text)
        check_not_in("K1-9/F7 ... no dispatch count", "across", text)
        check_in("K1-9/F7 ... and still a notice", CONTROL_LINE, text)

        # E13: the threshold does not move, and the receipt is read on the notice only
        event = role_event("A9")
        path_s = event["host_binding"]
        seed(root, event, 0)
        reads.clear()
        hooklib.read_json = lambda path, *a, **k: (reads.append(str(path)), real_read(path, *a, **k))[1]
        try:
            seen = []
            for _ in range(6):
                seen.append(bool(TB.check(dict(event), SOFT)))
                seen[-1] = (seen[-1], len([r for r in reads if r == path_s]))
        finally:
            hooklib.read_json = real_read
        check_eq("K1-9/E13 soft 5: calls 1-4 silent, 5th speaks, 6th silent; the receipt is read once, on the 5th only",
                 seen, [(False, 0)] * 4 + [(True, 1), (False, 1)])
    finally:
        cleanup(root)


def k1_10_the_finding_fixture():
    root, task, controller, rework = BR.repair_story("qa-bindlist-f-")
    try:
        for dispatch in ("dS0", "dS1", "dS2", "dS3"):
            check_eq(f"K1-10 bind {dispatch} to the one agent", bind_cli(root, dispatch, "A-run").returncode, 0)
        check_eq("K1-10 the receipt holds the four", ids_of(receipt_of(root, "A-run")), ["dS0", "dS1", "dS2", "dS3"])
        event = role_event("A-run")
        seed(root, event, 0)
        notices = {}
        for call in range(1, 121):
            text = TB.check(dict(event), {})  # the shipped defaults: soft 60, repeat 30
            if text:
                notices[call] = text
        check_eq("K1-10 notices at 60, 90 and 120 and nowhere else", sorted(notices), [60, 90, 120])
        for call, text in notices.items():
            check_in(f"K1-10 the notice at {call} says it spans 4 dispatches", "tool calls across 4 dispatches (latest dS3)", text)
            check_in(f"K1-10 ... of {call} tool calls", f"this agent has made {call} tool calls", text)
        files = sorted(p.name for p in (root / "qa-factory" / "state" / "turns" / "dispatches").glob("*.json"))
        check_eq("K1-10 one counter file for the agent", files, ["A-run.json"])
    finally:
        cleanup(root)


def main():
    k1_1_2_6_two_binds_and_the_same_bind_twice()
    k1_3_a_receipt_written_before_the_field()
    k1_4_a_receipt_that_is_not_one()
    k1_5_a_refused_bind_is_not_counted()
    k1_7_the_pair_is_the_identity()
    k1_8_the_texts()
    k1_9_the_notice_through_the_guard()
    k1_10_the_finding_fixture()
    finish("test_bind_dispatch_list")


if __name__ == "__main__":
    main()
