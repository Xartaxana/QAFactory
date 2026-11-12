"""host_probe.py must read the event and the challenge shapes a native Codex host really sends.

Five defects, four found by a legacy operator running the doctor on a Codex host and the fifth
(t-005, 13.10: two probe children answered a 48-hex challenge as 41/48 and 47/48, no '.' reproduced)
by the Desktop stand of TP2-2406:
- a native patch (`apply_patch`, `functions.apply_patch`) was invisible to the write family, so
  the guard-parse check could never turn green there;
- a code-mode call wraps the real shell call (`functions.exec`) and carries no `command` field,
  so the allow/deny probe never saw its own echo;
- the diagnostic instruction ended with the challenge itself, and a native agent that trims its
  last output character returned a challenge the verifier then rejected;
- `--root` pointed at a story artifact directory made the probe write a store no real hook reads;
- the delimiter was a '.' the children never reproduced: the challenge is now 32 hex with an `_END`
  sentinel inside the identifier, and an answer with the prefix but not the whole challenge is a
  named `mismatch`, never a pass.

Every check here is about what is read, never about what is trusted: a receipt still exists
only because a real hook event arrived, and a challenge still verifies only when complete."""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from harness import SCRIPTS, check, check_eq, check_in, cleanup, finish, temp_dir, temp_project

sys.path.insert(0, str(SCRIPTS))
import host_adapter  # noqa: E402
import host_capabilities  # noqa: E402
import host_probe  # noqa: E402

SESSION = "codex-session-1"


def run_cli(*args, cwd=None, env_root=None):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env.pop("CLAUDE_PROJECT_DIR", None)
    if env_root:
        env["CLAUDE_PROJECT_DIR"] = str(env_root)
    return subprocess.run([sys.executable, "-B", str(SCRIPTS / "host_probe.py"), *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          cwd=str(cwd) if cwd else None, env=env, timeout=120)


def store(root):
    return json.loads((root / "qa-factory/state/host-probe.json").read_text(encoding="utf-8"))


def exec_source(command):
    return "text(await tools.exec_command(" + json.dumps({"cmd": command}) + "));"


def wrapped(hook, source, tool_input_kind, session=SESSION, name="functions.exec"):
    tool_input = source if tool_input_kind == "string" else {"input": source}
    return {"hook_event_name": hook, "session_id": session, "tool_name": name,
            "tool_use_id": "exec-1", "tool_input": tool_input}


def patch_event(name, hook="PreToolUse", session=SESSION):
    return {"hook_event_name": hook, "session_id": session, "tool_name": name,
            "tool_use_id": "call-1",
            "tool_input": {"command": "*** Begin Patch\n*** Add File: x.txt\n+x\n*** End Patch"}}


def families(root, session):
    return host_probe.guard_parse(root, session)["families"]


def item1_native_patch(root):
    for name in ("apply_patch", "functions.apply_patch"):
        session = SESSION + "-" + name
        host_probe.note_guard_parse(root, patch_event(name, session=session), "guard_pre_tool.py", 0)
        fam = families(root, session)
        check_eq("patch exit 0 is write evidence: " + name, fam["write"]["status"], "verified")
        check_eq("and does not certify the shell family: " + name, fam["bash"]["status"], "unverified")

    session = SESSION + "-refused"
    host_probe.note_guard_parse(root, patch_event("apply_patch", session=session), "guard_pre_tool.py", 2)
    check_eq("a patch the guard refused (exit 2) is not write evidence",
             families(root, session)["write"]["status"], "unverified")

    session = SESSION + "-other-script"
    host_probe.note_guard_parse(root, patch_event("apply_patch", session=session), "exit_gate.py", 0)
    check_eq("only the guard's own receipt counts, not another script's",
             families(root, session)["write"]["status"], "unverified")
    session = SESSION + "-post"
    host_probe.note_guard_parse(root, patch_event("apply_patch", "PostToolUse", session),
                                "guard_pre_tool.py", 0)
    check_eq("only a PreToolUse receipt counts",
             families(root, session)["write"]["status"], "unverified")

    # Claude tool names keep their families exactly as before.
    session = SESSION + "-claude"
    claude = {"hook_event_name": "PreToolUse", "session_id": session, "tool_name": "Write",
              "tool_input": {"file_path": "x", "content": "y"}}
    host_probe.note_guard_parse(root, claude, "guard_pre_tool.py", 0)
    check_eq("Write is still write evidence", families(root, session)["write"]["status"], "verified")
    check_eq("and still not shell evidence", families(root, session)["bash"]["status"], "unverified")
    host_probe.note_guard_parse(root, dict(claude, tool_name="Bash", tool_input={"command": "ls"}),
                                "guard_pre_tool.py", 0)
    check_eq("Bash is still shell evidence", families(root, session)["bash"]["status"], "verified")

    # The function is fail-silent: odd raw shapes raise nothing and write nothing.
    for label, odd in (("a non-object event", "not an event"), ("a list event", [1, 2]),
                       ("a non-object tool_input", dict(claude, session_id="odd-1", tool_input="text")),
                       ("a list tool_input", dict(claude, session_id="odd-2", tool_input=["x"]))):
        try:
            host_probe.note_guard_parse(root, odd, "guard_pre_tool.py", 0)
            raised = ""
        except Exception as exc:  # noqa: BLE001 - the point is that nothing escapes
            raised = type(exc).__name__
        check_eq("no exception for " + label, raised, "")
    check("no receipt is written for an unreadable event",
          not host_probe._guard_parse_path(root, "odd-1").exists()
          and not host_probe._guard_parse_path(root, "odd-2").exists())


def item2_wrapped_probe(root):
    probe = host_probe.prepare(root, SESSION)
    allow, deny = probe["commands"]
    nonce = probe["nonce"]

    for kind in ("string", "dict"):
        data = store(root)
        data["checks"] = {}
        (root / "qa-factory/state/host-probe.json").write_text(json.dumps(data), encoding="utf-8")
        stops = host_probe.observe(root, wrapped("PreToolUse", exec_source(deny), kind))
        check_eq("a wrapped DENY echo makes the normal guard block (" + kind + ")", stops, True)
        check_eq("a wrapped ALLOW echo does not block (" + kind + ")",
                 host_probe.observe(root, wrapped("PreToolUse", exec_source(allow), kind)), False)
        check_eq("no receipt without a hook script: the event alone is not evidence (" + kind + ")",
                 store(root)["checks"], {})
        host_probe.observe(root, wrapped("PreToolUse", exec_source(allow), kind), "guard_pre_tool.py", 0)
        host_probe.observe(root, wrapped("PostToolUse", exec_source(allow), kind), "host_probe.py", 0)
        host_probe.observe(root, wrapped("PreToolUse", exec_source(deny), kind), "guard_pre_tool.py", 2)
        got = store(root)["checks"]
        check_eq("hook receipts exist for the wrapped pair (" + kind + ")",
                 sorted(got), ["allow_executed", "allow_guard", "deny_guard"])
        check_eq("the receipt records the extracted command (" + kind + ")",
                 got["allow_guard"]["command"], allow)

    # Parsing a wrapper proves nothing unless the command is exactly the nonce-bearing echo.
    data = store(root)
    data["checks"] = {}
    (root / "qa-factory/state/host-probe.json").write_text(json.dumps(data), encoding="utf-8")
    for label, source in (
            ("another command", exec_source("echo hello")),
            ("a chained command", exec_source(allow + " && echo extra")),
            ("a wrong nonce", exec_source("echo QA_FACTORY_PROBE_ALLOW_" + "0" * 32)),
            ("a prefixed command", exec_source("x; " + allow)),
            ("source that is not a literal call",
             "const c = " + json.dumps(allow) + "; text(await tools.exec_command({cmd: c}));"),
            ("a non-shell call that only mentions the echo",
             "text(" + json.dumps(allow) + ");"),
            ("empty source", ""), ("no source at all", None)):
        for kind in ("string", "dict"):
            event = wrapped("PreToolUse", source if source is not None else "", kind)
            if source is None:
                event["tool_input"] = {} if kind == "dict" else ""
            result = host_probe.observe(root, event, "guard_pre_tool.py", 0)
            check_eq("no receipt, no block for " + label + " (" + kind + ")", result, False)
    check_eq("none of those left a receipt", store(root)["checks"], {})
    check_eq("a wrapper under a tool that is not exec is not read",
             host_probe.observe(root, wrapped("PreToolUse", exec_source(allow), "string",
                                              name="functions.apply_patch"), "guard_pre_tool.py", 0), False)
    check_eq("another session's wrapped echo is not read",
             host_probe.observe(root, wrapped("PreToolUse", exec_source(allow), "string", session="other"),
                                "guard_pre_tool.py", 0), False)
    check_eq("still no receipt", store(root)["checks"], {})

    # observe is called inside the hook's one try block; an odd shape must not escape it.
    for label, event in (("a non-object event", "x"), ("a list event", []),
                         ("tool_input as a number", dict(wrapped("PreToolUse", "", "string"), tool_input=7)),
                         ("tool_input as a list", dict(wrapped("PreToolUse", "", "string"), tool_input=[1])),
                         ("tool_input as None", dict(wrapped("PreToolUse", "", "string"), tool_input=None))):
        try:
            result = host_probe.observe(root, event, "guard_pre_tool.py", 0)
            raised = ""
        except Exception as exc:  # noqa: BLE001
            result, raised = None, type(exc).__name__
        check_eq("observe does not raise on " + label, raised, "")
        check_eq("and records nothing for " + label, result, False)

    # The direct fields keep working exactly as before.
    direct = {"hook_event_name": "PreToolUse", "session_id": SESSION, "tool_name": "Bash",
              "tool_use_id": "t", "tool_input": {"command": deny}}
    check_eq("a direct DENY echo still blocks", host_probe.observe(root, direct), True)
    check_eq("a direct cmd field still works",
             host_probe.observe(root, dict(direct, tool_input={"cmd": deny})), True)
    check_in("the nonce in play is the prepared one", nonce, deny)

    # CL2-1 (AR-12): `observe` judges the cheap things first, but the fingerprint is still judged BEFORE the DENY block and
    # before any receipt - a probe made for other bytes blocks nothing and records nothing.
    data, path = store(root), root / "qa-factory/state/host-probe.json"
    path.write_text(json.dumps(dict(data, fingerprint="0" * 64)), encoding="utf-8")
    check_eq("a DENY echo under a foreign fingerprint is not blocked", host_probe.observe(root, direct), False)
    check_eq("...and a hook receipt under a foreign fingerprint is not recorded",
             (host_probe.observe(root, dict(direct, tool_input={"command": allow}), "guard_pre_tool.py", 0), store(root)["checks"]),
             (False, data["checks"]))
    path.write_text(json.dumps(data), encoding="utf-8")
    check_eq("positive control: under its own fingerprint the same DENY echo blocks", host_probe.observe(root, direct), True)


# --- the context probe (t-005 / t-006, TP2-2406 S4; CX1-2) ----------------------------------------
# Expectations come from the requirement (a child proves delivery only by reproducing the WHOLE challenge it
# was handed; anything less is named, never a pass) and from the two real 13.10 rows, never from what the
# code prints (FR-58).
PREFIX = "QA_CONTEXT_RECEIVED_"
C32 = "abcdef0123456789abcdef0123456789"
# Real 13.10 challenges of the TP2-2406 run (48 hex, the previous build): probe 1 was answered with its
# first 41 characters, probe 2 with its first 47.
REAL_41, REAL_47 = "6bb6009dee081e67f0260b74283248322de3cda45a625d45", "3ccb7b14c1bfe09d6aeded1af0cd2274dcd432e02c238e9e"
HASH_KEYS = ("child_transcript", "transcript_bytes", "transcript_hash")
DROP = object()


def write_store(root, data):
    (root / "qa-factory/state/host-probe.json").write_text(json.dumps(data), encoding="utf-8")


def put(root, **keys):
    """Set keys of the stored proof by hand (DROP deletes one): the store is a file a role can write."""
    data = store(root)
    for key, value in keys.items():
        if value is DROP:
            data["injection"].pop(key, None)
        else:
            data["injection"][key] = value
    write_store(root, data)


def probe_event(root, tool_use_id="spawn"):
    host_probe.prepare(root, "parent")
    return {"session_id": "parent", "tool_use_id": tool_use_id, "tool_input": {"prompt": "QA_FACTORY_CONTEXT_PROBE"},
            "transcript_path": str(root / "parent.jsonl")}


def fresh(root, event, challenge=C32):
    """A real injection_marker call (the whole `injection` rewritten), then the stored challenge replaced by a
    known one and the child bound: an `emitted` proof of a child called "child"."""
    host_probe.injection_marker(root, event)
    put(root, challenge=challenge)
    host_probe.bind_injection(root, event, "child")


def reset(root, challenge=None):
    """Back to `emitted` between two stops of one item (what a re-probe's fresh proof looks like to check_child)."""
    put(root, status="emitted", returned=DROP, child_transcript=DROP, transcript_bytes=DROP, transcript_hash=DROP,
        **({"challenge": challenge} if challenge else {}))


def claude(text):
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def codex(text, role="assistant", kind="output_text"):
    # The shape of row 15 of a 13.10 child rollout (`phase: final_answer`), and of the host's own instruction row
    # (`role: developer`, `input_text`).
    return {"timestamp": "2026-10-13T00:25:41.000Z", "type": "response_item",
            "payload": {"type": "message", "id": "msg_1", "role": role, "phase": "final_answer",
                        "content": [{"type": kind, "text": text}]}}


def claude_tool():
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "toolu_1", "name": "Read", "input": {"file_path": "qa-factory/state/host-probe.json"}}]}}


def codex_tool(kind):
    return {"timestamp": "2026-10-13T00:25:40.000Z", "type": "response_item",
            "payload": {"type": kind, "name": "shell", "call_id": "call_1", "arguments": "{}"}}


def stop(root, rows, name, agent="child"):
    """Write the child's transcript, run the SubagentStop check; return the stored proof."""
    path = root / (name + ".jsonl")
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    host_probe.check_child(root, {"agent_id": agent, "agent_transcript_path": str(path)})
    return store(root)["injection"]


def raised(call):
    try:
        call()
    except Exception as exc:  # noqa: BLE001 - the point is that nothing escapes
        return type(exc).__name__
    return ""


def item3_sentinel(root):
    """K1: 32 lowercase hex, and a sentinel INSIDE the identifier the child is asked to reproduce."""
    event = probe_event(root)
    instruction = host_probe.injection_marker(root, event)
    challenge = store(root)["injection"]["challenge"]
    check_in("the instruction carries the challenge", PREFIX + challenge, instruction)
    check("K1: the challenge is exactly 32 lowercase hex characters", re.fullmatch(r"[0-9a-f]{32}", challenge) is not None,
          challenge)
    check("K1: the instruction asks for QA_CONTEXT_RECEIVED_<32 hex>_END. (sentinel inside the identifier)",
          re.search(r"Return exactly QA_CONTEXT_RECEIVED_[0-9a-f]{32}_END\.$", instruction) is not None, repr(instruction))
    check_eq("K1: what follows the challenge is the sentinel and the full stop", instruction.split(PREFIX + challenge, 1)[1],
             "_END.")
    check_in("the instruction still tells the child not to use tools", "use tools", instruction)
    host_probe.injection_marker(root, event)
    second = store(root)["injection"]["challenge"]
    check_eq("a re-probe writes a NEW challenge of the same form over the proof",
             (re.fullmatch(r"[0-9a-f]{32}", second) is not None, second != challenge), (True, True))


def item3_verdicts(root):
    """K2, K4 and edges 1-7, 13, 17: `delivered` only on the whole challenge; a prefixed near miss is `mismatch`."""
    event = probe_event(root)
    fresh(root, event)
    for tail in ("_END.", "_END", "_EN", "_E", "_", ""):
        reset(root)
        check_eq("edge 1: the whole challenge + " + repr(tail) + " (a trimmed sentinel included) is delivered",
                 stop(root, [claude(PREFIX + C32 + tail)], "whole")["status"], "delivered")
    # edge 2 - the invariant is "NOT delivered, and named": there is no partial match
    wrong = C32[:-1] + "0"
    for label, answer in (("a challenge missing its last character", PREFIX + C32[:-1] + "_END."),
                          ("...with no sentinel", PREFIX + C32[:-1]),
                          ("one missing its first character", PREFIX + C32[1:] + "_END."),
                          ("a wrong last character at the right length", PREFIX + wrong + "_END."),
                          ("the challenge in upper case", PREFIX + C32.upper()),
                          ("the sentinel alone", PREFIX + "_END"),
                          ("only the head, 10 characters", PREFIX + C32[:10]),
                          ("words after the prefix", PREFIX + "sorry_I_cannot")):
        reset(root)
        got = stop(root, [claude(answer)], "near")
        check_eq("edge 2: " + label + " is NOT delivered, it is a mismatch", got["status"], "mismatch")
        check_eq("edge 2: ...and `returned` is what came back, up to the first character outside [0-9A-Za-z_]",
                 got.get("returned"), re.match(r"[0-9A-Za-z_]*", answer).group())
        check("edge 2: ...no hash field was written (the acceptance reads them)",
              "transcript_hash" not in got and "transcript_bytes" not in got)
    # edge 3 / 17: no answer is `emitted`, and the prefix is case-sensitive: "no answer", never a pass
    for label, rows in (("no prefix at all", [claude("I am sorry, I cannot do that."), codex("done")]),
                        ("the prefix in lower case", [claude(PREFIX.lower() + C32)]),
                        ("the bare challenge without the prefix", [claude(C32)]),
                        ("silence", [])):
        reset(root)
        got = stop(root, rows, "silent")
        check_eq("edge 3/17: " + label + " stays emitted", got["status"], "emitted")
        check("edge 3/17: ...with no `returned`", "returned" not in got)
    # edge 4: only the child's own output counts, never a row of the host
    full_instruction = "Return exactly " + PREFIX + C32 + "_END."
    for role in ("developer", "user", "system"):
        reset(root)
        got = stop(root, [codex(full_instruction, role=role, kind="input_text")], "host-" + role)
        check_eq("K4/edge 4: a " + role + " row holding the full instruction alone stays emitted", got["status"], "emitted")
        check("K4: ...and records no answer", "returned" not in got)
    reset(root)
    got = stop(root, [{"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": full_instruction}]}}],
               "host-claude-user")
    check_eq("K4/edge 4: the Claude user row shape holding the full instruction alone stays emitted", got["status"], "emitted")
    reset(root)
    got = stop(root, [codex(full_instruction, role="developer", kind="input_text"), codex(PREFIX + C32[:-3])], "host+short")
    check_eq("K4/edge 4: the host row beside a short answer does not rescue it", got["status"], "mismatch")
    # edge 5: the decision is taken after the whole scan, in either order
    reset(root)
    check_eq("edge 5: a mismatch row followed by a whole-challenge row is delivered",
             stop(root, [codex(PREFIX + C32[:-1]), codex(PREFIX + C32 + "_END")], "scan-mw")["status"], "delivered")
    reset(root)
    check_eq("edge 5: a whole-challenge row followed by a mismatch row is delivered",
             stop(root, [codex(PREFIX + C32), codex(PREFIX + C32[:-1])], "scan-wm")["status"], "delivered")
    # edge 6 (I3): a delivered proof is never downgraded, and its hash fields are never touched
    before = dict(store(root)["injection"])
    after = stop(root, [codex(PREFIX + C32[:-1])], "downgrade")
    check_eq("edge 6: a delivered proof followed by a stop with a short answer stays delivered", after["status"], "delivered")
    check_eq("edge 6: ...hash fields and transcript untouched", {k: after.get(k) for k in HASH_KEYS},
             {k: before.get(k) for k in HASH_KEYS})
    check("edge 6: ...and no `returned` was added", "returned" not in after)
    # edge 7: a mismatch is a diagnosis, not an outcome
    reset(root)
    stop(root, [codex(PREFIX + C32[:-1])], "m1")
    check_eq("edge 7: after a mismatch the same child's whole answer is delivered",
             stop(root, [codex(PREFIX + C32)], "m2")["status"], "delivered")
    reset(root)
    stop(root, [codex(PREFIX + C32[:-1])], "m3")
    check_eq("edge 7: after a mismatch another short answer replaces `returned` with the last one",
             stop(root, [codex(PREFIX + C32[:5])], "m4")["returned"], PREFIX + C32[:5])


def item3_unreadable(root):
    """Edge 13: a transcript that cannot be read whole, a foreign agent or none changes nothing - not even a mismatch."""
    event = probe_event(root)
    fresh(root, event)
    reset(root)
    host_probe.check_child(root, {"agent_id": "child", "agent_transcript_path": str(root / "does-not-exist.jsonl")})
    check_eq("edge 13: an unreadable transcript path changes nothing", store(root)["injection"]["status"], "emitted")
    host_probe.check_child(root, {"agent_id": "child"})
    check_eq("edge 13: no agent_transcript_path changes nothing", store(root)["injection"]["status"], "emitted")
    for label, text in (("a malformed line after a short answer", json.dumps(claude(PREFIX + C32[:-1])) + "\nnot json\n"),
                        ("a row that is not an object", json.dumps(claude(PREFIX + C32[:-1])) + "\n5\n"),
                        ("a null row", "null\n" + json.dumps(claude(PREFIX + C32[:-1])) + "\n"),
                        ("bytes that are not UTF-8", "\udcff")):
        path = root / "broken.jsonl"
        path.write_bytes(text.encode("utf-8", "surrogateescape"))
        err = raised(lambda: host_probe.check_child(root, {"agent_id": "child", "agent_transcript_path": str(path)}))
        check_eq("edge 13: " + label + " changes nothing", (err, store(root)["injection"]["status"]), ("", "emitted"))
    foreign = root / "foreign.jsonl"
    foreign.write_text(json.dumps(claude(PREFIX + C32)) + "\n", encoding="utf-8")
    host_probe.check_child(root, {"agent_id": "foreign", "agent_transcript_path": str(foreign)})
    check_eq("edge 13: a non-matching agent changes nothing", store(root)["injection"]["status"], "emitted")
    # edge 9 (iii): a late stop of an OLD child after a re-probe
    again = probe_event(root, "spawn-2")
    host_probe.injection_marker(root, again)
    put(root, challenge=C32)
    old = root / "old-child.jsonl"
    old.write_text(json.dumps(claude(PREFIX + C32)) + "\n", encoding="utf-8")
    host_probe.check_child(root, {"agent_id": "child", "agent_transcript_path": str(old)})
    check_eq("edge 9 (iii): before the new child is bound there is no agent_id - the old child's stop changes nothing",
             store(root)["injection"]["status"], "emitted")
    host_probe.bind_injection(root, again, "child-2")
    host_probe.check_child(root, {"agent_id": "child", "agent_transcript_path": str(old)})
    check_eq("edge 9 (iii): after the bind the old agent is a stranger - nothing changes", store(root)["injection"]["status"],
             "emitted")
    check_eq("...while the bound child's own whole answer is delivered", stop(root, [claude(PREFIX + C32)], "new-child",
                                                                             agent="child-2")["status"], "delivered")


def item3_returned(root):
    """Edge 8: `returned` is cut at 120 characters and at the first character outside [0-9A-Za-z_] (AT and BEYOND)."""
    event = probe_event(root)
    fresh(root, event)
    for count, want in ((99, 119), (100, 120), (101, 120), (500, 120)):
        reset(root)
        got = stop(root, [claude(PREFIX + "a" * count)], "cap")["returned"]
        check_eq(f"edge 8: an answer of {len(PREFIX) + count} characters keeps {want}", len(got), want)
    reset(root)
    check_eq("edge 8: `returned` stops at the first character outside [0-9A-Za-z_]",
             stop(root, [claude(PREFIX + "abécd and more")], "stop")["returned"], PREFIX + "ab")
    for label, junk in (("a quote", '"'), ("a control character", "\x07"), ("a newline", "\n"), ("a backslash", "\\"),
                        ("a space", " "), ("a bidi mark", "‮")):
        reset(root)
        check_eq("edge 8: " + label + " ends `returned` (the store stays JSON-safe and quote-free)",
                 stop(root, [claude(PREFIX + "ab" + junk + "cd")], "junk")["returned"], PREFIX + "ab")
    reset(root)
    check_eq("edge 8: words before the prefix are not kept, words after it are (until a non-identifier character)",
             stop(root, [claude("Sure: " + PREFIX + "sorry_I_cannot. bye")], "words")["returned"], PREFIX + "sorry_I_cannot")
    reset(root)
    check_eq("edge 8: the FIRST text that carries the prefix gives `returned`",
             stop(root, [claude("first " + PREFIX + "one"), claude(PREFIX + "two")], "first")["returned"], PREFIX + "one")


def item3_real_rows(root):
    """K3 and edge 9 (i), (ii), (iv): the real 13.10 rows; a store of the previous build (48 hex) is judged by the same rule."""
    event = probe_event(root)
    fresh(root, event, REAL_47)
    real_row = codex(PREFIX + REAL_47[:-1])
    got = stop(root, [real_row], "real-47")
    check_eq("K3: the real Codex row (47 of 48) is a mismatch, not delivered", got["status"], "mismatch")
    check_eq("K3: ...and `returned` is the 47 characters the child answered", got.get("returned"), PREFIX + REAL_47[:-1])
    reset(root)
    check_eq("K3: the same Codex row shape with the whole challenge is delivered",
             stop(root, [codex(PREFIX + REAL_47)], "real-48")["status"], "delivered")
    fresh(root, event, REAL_41)
    got = stop(root, [codex(PREFIX + REAL_41[:41])], "real-41")
    check_eq("K3: the real probe 1 row (41 of 48) is a mismatch with its 41 characters",
             (got["status"], got.get("returned")), ("mismatch", PREFIX + REAL_41[:41]))
    # edge 9 (i): fixture level - the stored length decides, whatever the build that wrote it
    fresh(root, event, REAL_47)
    check_eq("edge 9 (i): a stored 48-hex challenge answered 47/48 is a mismatch", stop(root, [codex(PREFIX + REAL_47[:47])], "i1")["status"],
             "mismatch")
    reset(root)
    check_eq("edge 9 (i): ...and answered with its first 32 characters only is a mismatch too",
             stop(root, [codex(PREFIX + REAL_47[:32])], "i2")["status"], "mismatch")
    # edge 9 (iv): a stored 32-hex challenge, an answer of 48 hex that begins with the whole 32 - the child reproduced it
    fresh(root, event, C32)
    check_eq("edge 9 (iv): a 48-hex answer that starts with the whole stored 32-hex challenge is delivered (containment)",
             stop(root, [codex(PREFIX + C32 + "0123456789abcdef")], "iv")["status"], "delivered")
    # edge 9 (ii): the next injection_marker writes a 32-hex challenge over the proof and resets it whole
    fresh(root, event, REAL_47)
    stop(root, [codex(PREFIX + REAL_47[:-1])], "ii")
    host_probe.injection_marker(root, event)
    proof = store(root)["injection"]
    check_eq("edge 9 (ii): the next injection_marker call writes a 32-hex challenge, status emitted, nothing of the old proof",
             (len(proof["challenge"]), proof["status"], "returned" in proof, "agent_id" in proof, "child_transcript" in proof),
             (32, "emitted", False, False, False))


def item3_form(root):
    """Edge 14 (F-3): a stored challenge of an unknown shape is NEVER judged - no verdict, no exception, no hash fields."""
    event = probe_event(root)
    fresh(root, event)
    answer = [claude(PREFIX + "sorry_I_cannot"), claude(PREFIX)]
    for label, value in (("empty", ""), ("null", None), ("an int", 32), ("a 32-digit int", 12345678901234567890123456789012),
                         ("a list", [C32]), ("a dict", {"x": C32}), ("31 characters", C32[:-1]), ("33 characters", C32 + "0"),
                         ("47 characters", REAL_47[:-1]), ("49 characters", REAL_47 + "0"), ("not hex", "g" * 32),
                         ("upper-case hex", C32.upper()), ("hex with a trailing newline", C32 + "\n"),
                         ("32 spaces", " " * 32), ("DROP", DROP)):
        for rows_label, rows in (("a prefixed answer", answer), ("the prefix alone", [claude(PREFIX)]),
                                 ("an answer holding the stored value", [claude(PREFIX + str(value))])):
            reset(root)
            put(root, challenge=value)
            err = raised(lambda: stop(root, rows, "form"))
            got = store(root)["injection"]
            check_eq(f"edge 14: a {label} stored challenge + {rows_label}: no exception, status unchanged, no hash field",
                     (err, got["status"], any(k in got for k in HASH_KEYS)), ("", "emitted", False))
    for label, value in (("32 hex", C32), ("48 hex", REAL_47)):
        reset(root, value)
        check_eq(f"edge 14 (control): a stored {label} challenge answered whole is delivered",
                 stop(root, [claude(PREFIX + value)], "form-ok")["status"], "delivered")
    # store and event shapes that are not what a build writes: nothing raises, nothing is written
    for label, mutate in (("a store that is a JSON list", lambda d: [d]), ("an injection that is a string", lambda d: dict(d, injection="x")),
                          ("an agent_id that is a number", lambda d: dict(d, injection=dict(d["injection"], agent_id=5)))):
        event = probe_event(root)
        fresh(root, event)
        write_store(root, mutate(store(root)))
        err = raised(lambda: host_probe.check_child(root, {"agent_id": "child", "agent_transcript_path": str(root / "form.jsonl")}))
        check_eq("F-3: check_child on " + label + " raises nothing", err, "")
    event = probe_event(root)
    fresh(root, event)
    for label, odd in (("None", None), ("a string", "x"), ("a list", [1]), ("a number as the transcript path",
                                                                              {"agent_id": "child", "agent_transcript_path": 5})):
        err = raised(lambda: host_probe.check_child(root, odd))
        check_eq("F-3: check_child on an event that is " + label + " raises nothing", (err, store(root)["injection"]["status"]),
                 ("", "emitted"))
    # an empty challenge could not have been written by injection_marker; the writer's own output is always a judged form
    host_probe.injection_marker(root, event)
    check("edge 14: whatever injection_marker writes is a form check_child judges",
          re.fullmatch(r"[0-9a-f]{32}", store(root)["injection"]["challenge"]) is not None)


def item3_tool(root):
    """F-1 (A): a child that made ANY tool call never yields `delivered` - it may have read the challenge from the store,
    the launch packet or the parent transcript. The error direction is "not proven"."""
    event = probe_event(root)
    fresh(root, event)
    whole = PREFIX + C32 + "_END."
    check_eq("pin: the same whole answer WITHOUT a tool row is delivered", stop(root, [claude(whole)], "no-tool")["status"],
             "delivered")
    for label, rows in (("a Claude Read of the store before the answer", [claude_tool(), claude(whole)]),
                        ("a Claude tool_use block in the same row as the answer",
                         [{"type": "assistant", "message": {"role": "assistant", "content": [
                             {"type": "tool_use", "id": "t", "name": "Grep", "input": {}},
                             {"type": "text", "text": whole}]}}]),
                        ("a Codex function_call", [codex_tool("function_call"), codex(whole)]),
                        ("a Codex custom_tool_call", [codex_tool("custom_tool_call"), codex(whole)]),
                        ("a Codex local_shell_call", [codex_tool("local_shell_call"), codex(whole)]),
                        ("a tool call AFTER the whole answer (the decision is taken after the scan)", [codex(whole), codex_tool("function_call")])):
        reset(root)
        got = stop(root, rows, "tool")
        check_eq("F-1 (A): the whole answer after " + label + " is NOT delivered", got["status"], "tool_used")
        check("F-1 (A): ...no hash field was written", not any(k in got for k in ("transcript_hash", "transcript_bytes")))
    reset(root)
    check_eq("F-1 (A): a tool call and no prefixed answer writes nothing", stop(root, [claude_tool(), claude("ok")], "tool-silent")["status"],
             "emitted")
    reset(root)
    put(root, status="mismatch", returned=PREFIX + "ab")
    got = stop(root, [claude_tool(), claude(PREFIX + "ab")], "tool-mm")
    check_eq("F-1 (A): a short answer after a tool call is `tool_used`, and the older `returned` is gone",
             (got["status"], "returned" in got), ("tool_used", False))
    check_eq("F-1 (A): rows that are not calls (a message, a reasoning row, a function_call_output) do not count",
             stop(root, [codex(whole, role="developer", kind="input_text"),
                         {"type": "response_item", "payload": {"type": "reasoning", "summary": []}},
                         {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "x", "output": "y"}},
                         codex(whole)], "not-calls")["status"], "delivered")
    # tool_used is a diagnosis, not an outcome (as a mismatch is): a later tool-free whole answer is delivered
    reset(root)
    stop(root, [claude_tool(), claude(whole)], "tool-first")
    check_eq("F-1 (A): ...a later whole answer without a tool row is delivered", stop(root, [claude(whole)], "tool-then")["status"],
             "delivered")


def item3b_detail(root):
    """K5: a mismatch (or a tool use) reaches the doctor as `injection_detail`, through the REAL inspect and
    host_capabilities.inspect. The guard prerequisites are met by the store's own checks and a patched
    `host_call_present` (the transcript-correlation lookup, covered elsewhere)."""
    from unittest import mock
    event = probe_event(root)
    host_probe.injection_marker(root, event)
    data = store(root)
    data["checks"] = {"allow_guard": {"exit_code": 0, "tool_use_id": "a"}, "deny_guard": {"exit_code": 2, "tool_use_id": "d"},
                      "allow_executed": {"exit_code": 0, "tool_use_id": "a"}}
    write_store(root, data)
    put(root, challenge=REAL_47)
    host_probe.bind_injection(root, event, "child")

    def detail_of():
        return host_probe.inspect(root).get("injection_detail", "")

    with mock.patch.object(host_probe, "host_call_present", return_value=True):
        check_eq("(control) before any answer: injection unverified, no detail",
                 ("injection_detail" in host_probe.inspect(root), host_probe.inspect(root)["injection"]), (False, "unverified"))
        stop(root, [codex(PREFIX + REAL_47[:-1])], "k5-mismatch")
        out = host_probe.inspect(root)
        check_eq("K5: a mismatch store: guard verified, injection unverified, next action the probe",
                 (out["status"], out["injection"], out["next_action"]), ("verified", "unverified", "dispatch_context_probe"))
        detail = out.get("injection_detail", "")
        check_in("K5: injection_detail names the first 47 of 48 characters", "first 47 of 48 characters match", detail)
        check_in("K5: ...and what came back", "'" + PREFIX + REAL_47[:-1] + "'", detail)
        check_in("K5/edge 16: ...and the door (a re-probe under a new task name)", "re-probe under a new task name", detail)
        caps = host_capabilities.inspect(root)
        check("K5: host_capabilities.inspect puts the detail first in the note", caps["note"].startswith(detail + ". "),
              caps["note"][:200])
        check_in("K5: ...followed by the existing instruction to dispatch the probe", "Dispatch the read-only qa_factory_context_probe",
                 caps["note"])
        check_eq("edge 15: story_ready stays false on a mismatch", (caps["story_ready"], caps["guard_probe"]["injection"]), (False, "unverified"))
        check_eq("edge 15: ...and the mechanism behaviour stays unverified", caps["mechanisms"]["inject_context.py"]["behavior"], "unverified")
        check_eq("edge 15: ...the doctor's output keeps its key set (one added key at most)",
                 sorted(set(host_probe.inspect(root)) - {"injection_detail"}),
                 sorted(["status", "injection", "guard_parse", "next_action", "session_id", "checks", "reason", "missing"]))

        # F-1: the number is the agreeing PREFIX of the challenge, so it never reads "all matched" beside `unverified`.
        def put_mismatch(returned, challenge=C32, **top):
            data = store(root)
            data["injection"].update({"status": "mismatch", "challenge": challenge, "returned": returned})
            data.update(top)
            write_store(root, data)
            return host_probe.inspect(root)

        for label, returned, want in (
                ("a wrong LAST character", PREFIX + C32[:-1] + "0_END", "first 31 of 32 characters match"),
                ("a dropped FIRST character", PREFIX + C32[1:], "first 0 of 32 characters match"),
                ("an uppercase answer", PREFIX + C32.upper(), "first 0 of 32 characters match"),
                ("an empty answer", PREFIX, "first 0 of 32 characters match"),
                ("no prefix at all", C32[:-1], "first 0 of 32 characters match"),
                ("one character dropped from the tail", PREFIX + C32[:-1], "first 31 of 32 characters match")):
            got = put_mismatch(returned)
            check_in("edge 11: " + label + " -> " + want, want, got.get("injection_detail", ""))
            check_eq("edge 11: ..." + label + ": injection stays unverified", got["injection"], "unverified")

        # edge 10 / I4: the detail names a door (re-probe) that stage_guard opens only for a verified guard
        stale_ts = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        check_eq("edge 10: a verified-guard mismatch store carries the key", "injection_detail" in put_mismatch(PREFIX + C32[:-1]), True)
        good = store(root)
        for label, top in (("a store older than 24 h", {"created_at": stale_ts}),
                           ("a fingerprint mismatch (a store of an older build is stale until --prepare)", {"fingerprint": "not-this-project"})):
            got = put_mismatch(PREFIX + C32[:-1], **top)
            check_eq("edge 10/16: " + label + " and a mismatch: no injection_detail key, never verified",
                     ("injection_detail" in got, got["injection"], got["status"] in ("stale", "unverified")), (False, "unverified", True))
            write_store(root, good)
        bad_guard = dict(good, checks=dict(good["checks"], deny_guard={"exit_code": 0, "tool_use_id": "d"}))
        write_store(root, bad_guard)
        got = host_probe.inspect(root)
        check_eq("edge 10: an unverified guard (deny did not block) and a mismatch: no injection_detail key",
                 ("injection_detail" in got, got["injection"]), (False, "unverified"))
        write_store(root, dict(good, fingerprint="an-older-build"))
        check_eq("edge 16: a store written by an older build gets no new challenge until --prepare (injection_marker is silent)",
                 host_probe.injection_marker(root, event), "")
        write_store(root, good)

        # F-3: a store a role can write holds any type; the detail is cut by the writer's own rule or not given at all
        for label, returned, want in (("a quote", PREFIX + C32[:3] + '"x', PREFIX + C32[:3]),
                                      ("a control character", PREFIX + C32[:3] + "\x07x", PREFIX + C32[:3]),
                                      ("120+ characters", PREFIX + "a" * 300, PREFIX + "a" * 100)):
            text = put_mismatch(returned).get("injection_detail", "")
            check_in("F-3: returned with " + label + " is cut to [0-9A-Za-z_], at most 120: '" + want[:30] + "...'", "answered '" + want + "'", text)
            check("F-3: ...nothing beyond the cut reaches the doctor", '"' not in text and "\x07" not in text and len(text) < 330, repr(text[:80]))
        for label, returned in (("an int", 5), ("null", None), ("a list", [PREFIX]), ("a dict", {})):
            err = raised(lambda: put_mismatch(returned))
            check_eq("F-3: returned as " + label + ": inspect raises nothing and gives no detail", (err, detail_of()), ("", ""))
        for label, challenge in (("null", None), ("a 32-digit int", 12345678901234567890123456789012), ("a list", [C32]),
                                 ("31 hex", C32[:-1]), ("empty", "")):
            err = raised(lambda: put_mismatch(PREFIX + "ab", challenge=challenge))
            check_eq("F-3/edge 14: challenge as " + label + ": inspect raises nothing, gives no detail, injection unverified",
                     (err, detail_of(), host_probe.inspect(root)["injection"]), ("", "", "unverified"))
        # the tool rule has its own words, and the same door
        put(root, status="tool_used", returned=DROP)
        check_eq("F-1 (A): a child that used a tool: the detail says so and names the door",
                 detail_of(), "the probe child used a tool; it must answer from its context alone - re-probe under a new task name")
        caps = host_capabilities.inspect(root)
        check("F-1 (A): ...first in the doctor's note", caps["note"].startswith(detail_of() + ". "))
        write_store(root, bad_guard)
        put(root, status="tool_used")
        check_eq("F-1 (A)/edge 10: ...and not while the guard is unverified", "injection_detail" in host_probe.inspect(root), False)
        write_store(root, good)

        # F-3: the delivered proof's acceptance never raises, whatever the store holds
        for label, keys in (("transcript_bytes as a string", {"transcript_bytes": "x"}),
                            ("transcript_bytes as a list", {"transcript_bytes": [1]}),
                            ("child_transcript as a number", {"child_transcript": 5}),
                            ("child_transcript missing", {"child_transcript": DROP}),
                            ("transcript_hash as a number", {"transcript_hash": 5}),
                            ("transcript_hash missing", {"transcript_hash": DROP})):
            reset(root, C32)
            stop(root, [claude(PREFIX + C32)], "acc")
            put(root, **keys)
            err = raised(lambda: host_probe.inspect(root))
            check_eq("F-3: a delivered store with " + label + ": inspect raises nothing and does not verify",
                     (err, host_probe.inspect(root)["injection"]), ("", "unverified"))
        reset(root, C32)
        stop(root, [claude(PREFIX + C32)], "acc-ok")
        out = host_probe.inspect(root)
        check_eq("K5/edge 15: a delivered store: verified, no injection_detail key",
                 (out["injection"], out["next_action"], "injection_detail" in out), ("verified", "none", False))
        caps = host_capabilities.inspect(root)
        check_eq("K5/edge 15: ...the note is the plain verified one and story_ready is true",
                 (caps["note"].startswith("Live guard and role-context delivery verified"), caps["story_ready"]), (True, True))
        data = store(root)
        data["injection"]["transcript_hash"] = "0" * 64
        write_store(root, data)
        check_eq("I3: a delivered proof whose transcript no longer hashes to the stored hash is not accepted",
                 host_probe.inspect(root)["injection"], "unverified")


def item_rn1_1_launch_id(root):
    """RN1-1: the probe child of the REAL launch answer. The Claude hook (`agent_autobind.decide`) and `host_dispatch.record` (the
    Codex hook, the older-key case) bind the id the host's answer carries
    (`agentId`, Claude Code 2.1.309; the older `agent_id` too) through `host_adapter.launch_id_of`; an answer with no id
    leaves the probe `unverified` and says why. Kills: a `record` that reads `agent_id` / `id` only (K1), a `record` that
    treats an answer with no id as bound (K3)."""
    from unittest import mock
    import agent_autobind
    import host_dispatch

    def launched(response, tool_use_id, hook=agent_autobind.decide):
        event = probe_event(root, tool_use_id)
        data_event = dict(event, hook_event_name="PostToolUse", tool_name="Agent", cwd=str(root), tool_response=response)
        data_event["tool_input"] = {"subagent_type": "qa-factory:qa-scout", "prompt": "QA_FACTORY_CONTEXT_PROBE"}
        host_probe.injection_marker(root, data_event)
        data = store(root)
        data["checks"] = {"allow_guard": {"exit_code": 0, "tool_use_id": "a"}, "deny_guard": {"exit_code": 2, "tool_use_id": "d"},
                          "allow_executed": {"exit_code": 0, "tool_use_id": "a"}}
        write_store(root, data)
        put(root, challenge=C32)
        hook(data_event)       # the hook the host RUNS: Claude's PostToolUse `Agent|Task` entry is `agent_autobind` (RN1-1 B-1)
        return data_event

    with mock.patch.object(host_probe, "host_call_present", return_value=True):
        for label, response in (("K1 background launch", {"isAsync": True, "status": "async_launched", "agentId": "add467ff",
                                                          "canContinueAgent": True}),
                                ("K1 foreground launch", {"status": "completed", "agentId": "add467ff", "content": []}),
                                ("K2 the older key", {"agent_id": "add467ff"})):
            launched(response, "spawn-" + label[:2], host_dispatch.record if "older" in label else agent_autobind.decide)
            check_eq(f"{label}: the proof holds the host's id", store(root)["injection"].get("agent_id"), "add467ff")
            check_eq(f"{label}: and the child's whole answer is judged `delivered`",
                     stop(root, [claude(PREFIX + C32 + "_END")], "rn11-" + label[:2], agent="add467ff")["status"], "delivered")
        launched({"isAsync": True, "status": "async_launched", "canContinueAgent": True}, "spawn-K3")
        proof = store(root)["injection"]
        check_eq("K3: an answer with no launch id binds nothing", proof.get("agent_id"), None)
        check_eq("K3: the child's whole answer is NOT judged (no `delivered`)",
                 stop(root, [claude(PREFIX + C32 + "_END")], "rn11-k3", agent="add467ff")["status"], "emitted")
        out = host_probe.inspect(root)
        check_eq("K3: the probe is `unverified`", out["injection"], "unverified")
        check_in("K3: ...with the reason", "host response carries no launch id", out.get("injection_detail", ""))
        check_eq("K3: (control) a bound proof has no such detail",
                 "launch id" in (launched({"agentId": "bound-1"}, "spawn-ctl") and host_probe.inspect(root).get("injection_detail", "")),
                 False)


def item_probe_command(root):
    """F-1 (a), edge 12 and 19, I5: the probe reads the command the GUARD reads - the normalized event's -
    and a failing read is '' (never an exception, never a receipt)."""
    probe = host_probe.prepare(root, SESSION)
    allow, deny = probe["commands"]
    tail = deny.split(" ", 1)[1]

    def event(name, tool_input, hook="PreToolUse", **extra):
        return dict({"hook_event_name": hook, "session_id": SESSION, "tool_name": name, "tool_use_id": "t-1",
                     "tool_input": tool_input}, **extra)

    # edge 19: an argv shell call is read as the guard reads it - its elements joined by a space
    check_eq("edge 19: local_shell [echo, DENY-token] is the DENY probe the guard blocks",
             host_probe.observe(root, event("local_shell", {"command": ["echo", tail]})), True)
    check_eq("edge 19: ...and its command is the joined text", host_probe.probe_command(event("local_shell", {"command": ["echo", tail]})), deny)
    check_eq("edge 19: shell [bash, -lc, echo ...] is the joined text 'bash -lc echo ...': no probe (as on main)",
             (host_probe.probe_command(event("shell", {"command": ["bash", "-lc", deny]})),
              host_probe.observe(root, event("shell", {"command": ["bash", "-lc", deny]}))), ("bash -lc " + deny, False))
    check_eq("edge 19: a direct Claude Bash `cmd` field is read as before", host_probe.probe_command(event("Bash", {"cmd": deny})), deny)
    check_eq("edge 19: a direct Claude Bash `command` field wins over `cmd`",
             host_probe.probe_command(event("Bash", {"command": allow, "cmd": deny})), allow)
    check_eq("edge 19: an exec_command call is its `cmd`", host_probe.probe_command(event("exec_command", {"cmd": deny})), deny)
    cell = "text(await tools.exec_command(" + json.dumps({"cmd": deny}) + "));"
    check_eq("edge 19: a code cell with one exec_command is its inner command", host_probe.probe_command(event("functions.exec", cell)), deny)
    tty = "text(await tools.exec_command(" + json.dumps({"cmd": deny, "tty": True}) + "));"
    check_eq("edge 19: a cell asking for a tty is refused by normalize: no command, no receipt",
             (host_probe.probe_command(event("functions.exec", tty)), host_probe.observe(root, event("functions.exec", tty))), ("", False))
    check_eq("edge 19: a cell with two calls is no command", host_probe.probe_command(event("functions.exec", cell + cell)), "")
    # F-3: any shape that normalize refuses or cannot read is '' - the hook wrapper never meets an exception
    for label, odd in (("a number tool_input on a cell", event("functions.exec", 5)), ("a list tool_input on a shell",
                                                                                         event("local_shell", [1])),
                       ("a dict tool_input of a non-text command", event("shell", {"command": {"x": 1}})),
                       ("no tool_input", {"tool_name": "Bash"}), ("a string event", "echo " + tail), ("None", None), ("a list", [deny])):
        err = raised(lambda: host_probe.probe_command(odd))
        check_eq("F-3: probe_command of " + label + " raises nothing and is empty", (err, host_probe.probe_command(odd)), ("", ""))
    # m-1 (t-981): an event refused by normalize reads '' even when a text `cmd` stands beside the refused `command`
    refused = event("shell", {"command": {"x": 1}, "cmd": deny})
    check_eq("edge 19: refused by normalize (a non-text `command` beside a text `cmd`): no command, no receipt",
             (host_probe.probe_command(refused), host_probe.observe(root, refused)), ("", False))
    check_eq("edge 19: ...and the refusal is on the normalized event (the pin reads the real refusal)",
             bool((host_adapter.normalize(refused).get("_qa_host") or {}).get("refusal")), True)
    check_eq("edge 19: a refusal key with a falsy value (None, '') is no refusal: read as before",
             (host_probe.probe_command(event("Bash", {"cmd": deny}, _qa_host={"refusal": None})),
              host_probe.probe_command(event("Bash", {"cmd": deny}, _qa_host={"refusal": ""}))), (deny, deny))
    check_eq("edge 19: an event without `_qa_host` is read as before", host_probe.probe_command(event("Bash", {"cmd": deny})), deny)
    # edge 12: a transport record a caller sent never makes a receipt; an event with one is read by its own tool_input
    forged = event("Bash", {"command": "ls"}, _qa_host={"name": "exec_command", "input": {"cmd": deny}, "codex": True})
    check_eq("edge 12: a forged transport beside an ordinary command: the command is the ordinary one, no receipt",
             (host_probe.probe_command(forged), host_probe.observe(root, forged, "guard_pre_tool.py", 0)), ("ls", False))
    check_eq("edge 12: a forged transport and no command at all: no command", host_probe.probe_command(
        event("exec", "text(1)", _qa_host={"name": "exec_command", "input": {"cmd": deny}})), "")
    check_eq("edge 12: ...and the receipt file stays empty", store(root)["checks"], {})
    check_eq("I5: one event, one command, before and after normalize",
             host_probe.probe_command(event("local_shell", {"command": ["echo", tail]})),
             host_probe.probe_command(host_adapter.normalize(event("local_shell", {"command": ["echo", tail]}))))


def item4_root(project):
    # 4a: a directory that is not a factory project is refused, nothing is created in it.
    bare = temp_dir("qa-probe-bare-")
    artifact = project / "qa-factory" / "artifacts" / "STORY-1"
    artifact.mkdir(parents=True)
    try:
        for flag in ("--prepare", "--check"):
            done = run_cli(flag, "--root", bare, "--session", SESSION)
            check("refused with a non-zero exit: " + flag + " on a non-project", done.returncode != 0,
                  str(done.returncode))
            check("nothing was created there: " + flag, not (bare / "qa-factory").exists())
            check_eq("stdout stays empty on a refusal: " + flag, done.stdout, "")
            check_in("says what is wrong: " + flag, "qa-factory/config.json", done.stderr)
            check_in("names the thing to pass: " + flag, "--root", done.stderr)
            check_in("and what it is: " + flag, "project root", done.stderr)

        before = sorted(p.name for p in artifact.rglob("*"))
        done = run_cli("--prepare", "--root", artifact, "--session", SESSION)
        check("a story artifact directory is refused", done.returncode != 0)
        check("and gets no probe store", not (artifact / "qa-factory").exists()
              and sorted(p.name for p in artifact.rglob("*")) == before)
        check_in("the refusal names the real project root", str(project.resolve()), done.stderr)

        # 4b: a project root works, existing keys and exit codes unchanged, two new keys.
        done = run_cli("--prepare", "--root", project, "--session", SESSION)
        check_eq("prepare on a project still exits 0", done.returncode, 0)
        out = json.loads(done.stdout)
        for key in ("nonce", "session_id", "fingerprint", "created_at", "checks", "commands"):
            check("prepare keeps its key: " + key, key in out)
        check_eq("prepare names where the session came from (B-410: an id given with --session)", out.get("identity_source"), "explicit")
        check_eq("prepare names the root it used", out.get("root"), str(project.resolve()))
        check_eq("prepare names the store it wrote", out.get("store"),
                 str((project / "qa-factory/state/host-probe.json").resolve()))
        check("and that store exists", (project / "qa-factory/state/host-probe.json").is_file())

        done = run_cli("--check", "--root", project)
        check_eq("check on an unverified probe still exits 2", done.returncode, 2)
        out = json.loads(done.stdout)
        for key in ("status", "injection", "guard_parse", "next_action", "session_id", "checks", "reason"):
            check("check keeps its key: " + key, key in out)
        check_eq("check names the root", out.get("root"), str(project.resolve()))
        check_eq("check names the store", out.get("store"),
                 str((project / "qa-factory/state/host-probe.json").resolve()))

        # 4c: --root omitted resolves the project exactly as before; --hook touches nothing.
        done = run_cli("--check", cwd=project, env_root=project)
        check_eq("no --root: the ambient project is used", json.loads(done.stdout).get("root"),
                 str(project.resolve()))
        done = run_cli("--hook", "--root", bare)
        check_eq("--hook returns 0 even for a non-project", done.returncode, 0)
        check("and touches nothing", not (bare / "qa-factory").exists() and done.stdout == "")
    finally:
        cleanup(bare)


def item5_identity(project):
    """B-410 (K4): `--prepare` with no --session finds its own session or refuses; it never raises and never writes a store
    for a guessed id. Every name the rules read is cleared and the home is redirected (E26)."""
    import hashlib
    import session_identity
    rules = session_identity.load_rules()
    home = temp_dir("qa-probe-home-")
    store_path = project / "qa-factory/state/host-probe.json"

    def run(*args, **extra):
        env = {k: v for k, v in os.environ.items() if k not in rules["env_vars"] and k != "CLAUDE_PROJECT_DIR"}
        for key in ("HOME", "USERPROFILE", "TMP", "TEMP", "TMPDIR"):
            env[key] = str(home)
        env.update(PYTHONDONTWRITEBYTECODE="1", **extra)
        return subprocess.run([sys.executable, "-B", str(SCRIPTS / "host_probe.py"), *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", cwd=str(project), env=env, timeout=120)

    try:
        done = run("--prepare")
        check_eq("K4: --prepare with no id anywhere exits 1", done.returncode, 1)
        check_in("K4: ...with the refusal on stderr: what it could not tell, and the door", "Could not tell which session host_probe.py runs in", done.stderr)
        check_in("K4: ...the door is a separate cd and the doctor", "as its own shell call", done.stderr)
        check("K4: ...no traceback, nothing on stdout, and no store written", "Traceback" not in done.stderr and done.stdout == "" and not store_path.exists(),
              done.stderr[-300:])
        spool = home / ".qa-factory" / "spool" / rules["spool_dir"]
        spool.mkdir(parents=True)
        key = hashlib.sha256(b"s-k4").hexdigest()[:16]
        (spool / f"pretool-{key}-host_probe.json").write_text(json.dumps({
            "session_id": "s-k4", "script": "host_probe.py", "cwds": [str(project)], "command": "python host_probe.py --prepare",
            "observed_at": "t"}), encoding="utf-8")
        done = run("--prepare")
        out = json.loads(done.stdout) if done.returncode == 0 else {}
        check_eq("K4: with the hook's receipt it prepares, names the session and the source", (done.returncode, out.get("session_id"), out.get("identity_source")),
                 (0, "s-k4", "receipt"))
        check_eq("K4: ...and the store holds that session", store(project)["session_id"], "s-k4")
        store_path.unlink()
        (spool / f"pretool-{key}-host_probe.json").unlink()
        done = run("--prepare", CODEX_THREAD_ID="s-codex")
        out = json.loads(done.stdout) if done.returncode == 0 else {}
        check_eq("K4: with only the host's own variable it prepares and names it", (out.get("session_id"), out.get("identity_source")), ("s-codex", "env:CODEX_THREAD_ID"))
        done = run("--prepare", "--session", "s-given", CODEX_THREAD_ID="s-codex")
        out = json.loads(done.stdout) if done.returncode == 0 else {}
        check_eq("K4: an id a person gives wins over the variable", (out.get("session_id"), out.get("identity_source")), ("s-given", "explicit"))
        store_path.unlink()
        done = run("--prepare", "--session", "a/b")
        check("K4: an unsafe id is refused with the rule, exit 1, no store, no traceback",
              done.returncode == 1 and "1 to 128 characters" in done.stderr and "Traceback" not in done.stderr and not store_path.exists(), done.stderr[-300:])
        done = run("--prepare", CLAUDE_CODE_SESSION_ID="inherited", CODEX_THREAD_ID="other")
        check("K4: two variables that disagree: refused, nothing written", done.returncode == 1 and not store_path.exists(), done.stderr[-300:])
    finally:
        cleanup(home)


def tree_names(top):
    """Every path under `top` (relative), to prove that nothing was created or removed."""
    return sorted(str(p.relative_to(top)) for p in top.rglob("*"))


def item6_before_onboarding(unused):
    """OH3-5: before onboarding the probe refuses with exit 3 and writes nothing, at any root it took by itself.
    Expectations come from the requirement (no qa-factory/ under a root onboarding did not make; the refusal says
    unknown, owner factory, onboarding is the next step), never from the printed text of the old code (FR-58)."""
    import session_identity
    from harness import mark_project
    rules = session_identity.load_rules()
    home = temp_dir("qa-probe-home6-")
    top = temp_dir("qa-probe-mono-")
    nested = top / "sdk" / "test-harness"
    sub = nested / "src" / "deep"
    sub.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=str(top), capture_output=True, timeout=60)

    def run(*args, cwd=nested, project_dir=None, **extra):
        env = {k: v for k, v in os.environ.items() if k not in rules["env_vars"] and k != "CLAUDE_PROJECT_DIR"}
        for key in ("HOME", "USERPROFILE", "TMP", "TEMP", "TMPDIR"):
            env[key] = str(home)
        if project_dir is not None:
            env["CLAUDE_PROJECT_DIR"] = project_dir
        env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8", **extra)
        return subprocess.run([sys.executable, "-B", str(SCRIPTS / "host_probe.py"), *args], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", cwd=str(cwd), env=env, timeout=120)

    try:
        before = tree_names(top)
        for flag in ("--prepare", "--check"):
            done = run(flag, "--session", SESSION)
            check_eq("nested, no config, " + flag + ": exit 3, stdout empty", (done.returncode, done.stdout), (3, ""))
            check_eq("nested, no config, " + flag + ": nothing created anywhere", tree_names(top), before)
            check("nested, no config, " + flag + ": no probe store at the repository top or in the folder",
                  not (top / "qa-factory").exists() and not (nested / "qa-factory").exists())
            check_in("the refusal names onboarding", "/qa-factory:qa-onboarding", done.stderr)
            check_in("the refusal says the hooks are unknown, owner factory", "unknown, owner factory", done.stderr)
            check_in("the refusal says the project is not onboarded", "not onboarded", done.stderr)
            check("the refusal does not call the hooks inactive or broken",
                  not re.search(r"inactive|broken|not firing", done.stderr), done.stderr[-300:])
        done = run("--prepare")
        check_eq("refused before identity: no session anywhere still gives 3, not 1", done.returncode, 3)

        done = run("--hook")
        check("--hook without a project: 0, nothing touched",
              done.returncode == 0 and done.stdout == "" and tree_names(top) == before, str(done.returncode))

        # An old store in an unmarked root is neither read nor removed.
        old = top / "qa-factory" / "state" / "host-probe.json"
        old.parent.mkdir(parents=True)
        old.write_bytes(b'{"session_id": "old", "status": "verified"}')
        marker_tree = tree_names(top)
        done = run("--check", cwd=top)
        check("an old store in the unmarked root: refused, bytes unchanged, tree unchanged",
              done.returncode == 3 and done.stdout == "" and old.read_bytes() == b'{"session_id": "old", "status": "verified"}'
              and tree_names(top) == marker_tree, done.stderr[-300:])
        old.unlink()
        old.parent.rmdir()
        old.parent.parent.rmdir()

        # --root on a non-project with no marker above: the door names onboarding; the old pins stay (item4_root).
        done = run("--prepare", "--root", str(nested), "--session", SESSION)
        check("--root on a non-project without a marker above: exit 3, empty stdout, names --root and project root",
              done.returncode == 3 and done.stdout == "" and "--root" in done.stderr and "project root" in done.stderr)
        check_in("--root on a non-project without a marker above: door names onboarding", "/qa-factory:qa-onboarding", done.stderr)

        # F3: the ambient dir is unmarked but a marker IS above it: no "or above it", no onboarding; the door is --root.
        marked = temp_dir("qa-probe-marked-")
        try:
            mark_project(marked)
            below = marked / "sub"
            below.mkdir()
            text = host_probe._not_a_project(below, given=False)
            check("ambient dir below a marker: names --root <marker>, not 'or above it', not onboarding",
                  f"--root {marked.resolve()}" in text and "or above it" not in text and "qa-onboarding" not in text
                  and "not onboarded yet" not in text, text[:300])
        finally:
            cleanup(marked)

        # Hook receipt: the one sentence only when the pre-tool hook recorded a host_probe.py call here.
        done = run("--check")
        check_not_in_text("no receipt: says nothing about hooks", "pre-tool hook", done.stderr)
        spool = home / ".qa-factory" / "spool" / rules["spool_dir"]
        spool.mkdir(parents=True)
        (spool / "pretool-abcd-host_probe.json").write_text(json.dumps({
            "session_id": "s-6", "script": "host_probe.py", "cwds": [str(nested.resolve())],
            "command": "python host_probe.py --check", "observed_at": "t"}), encoding="utf-8")
        done = run("--check")
        check_in("hook receipt: the refusal says a pre-tool hook recorded a host_probe.py call in this folder moments ago",
                 "A pre-tool hook of this host recorded a host_probe.py call in this folder moments ago.", done.stderr)
        check("hook receipt: still exit 3, still nothing created", done.returncode == 3 and tree_names(top) == before)
        check_not_in_text("hook receipt: the refusal still does not call the hooks inactive", "inactive", done.stderr)

        # resolve raises: the refusal is the same as with no receipt, no traceback.
        real = session_identity.resolve
        try:
            def boom(*a, **k):
                raise RuntimeError("resolve is down")
            session_identity.resolve = boom
            plain = host_probe._not_a_project(nested, given=False)
        finally:
            session_identity.resolve = real
        check("resolve raises: the refusal is still given and names onboarding",
              "/qa-factory:qa-onboarding" in plain and "pre-tool hook" not in plain)

        # Battery: magnitude, encoding, nesting, empty and broken input.
        for label, args, kw in (("a 200-character --session", ("--prepare", "--session", "x" * 200), {}),
                                ("an unsafe --session a/b", ("--prepare", "--session", "a/b"), {}),
                                ("three levels below the git top", ("--check",), {"cwd": sub}),
                                ("an empty CLAUDE_PROJECT_DIR", ("--check",), {"project_dir": ""}),
                                ("CLAUDE_PROJECT_DIR on a folder with no marker", ("--check",), {"project_dir": str(nested)})):
            done = run(*args, **kw)
            check("battery: " + label + ": exit 3, empty stdout, no traceback, nothing created",
                  done.returncode == 3 and done.stdout == "" and "Traceback" not in done.stderr and tree_names(top) == before,
                  done.stderr[-300:])
        odd = top / ("".join(chr(c) for c in (0x43f, 0x440, 0x43e, 0x435, 0x43a, 0x442)) + " x")  # non-ASCII, escaped (FR-30)
        odd.mkdir()
        before_odd = tree_names(top)
        done = run("--check", cwd=odd, project_dir=str(odd))
        check("battery: a path with non-ASCII letters and a space: exit 3, the path is printed, no traceback",
              done.returncode == 3 and "Traceback" not in done.stderr and odd.name in done.stderr and tree_names(top) == before_odd,
              done.stderr[-300:])
        (nested / "qa-factory").mkdir()
        done = run("--check")
        check("battery: qa-factory/ without config.json: exit 3", done.returncode == 3 and done.stdout == "", done.stderr[-200:])
        (nested / "qa-factory" / "config.json").mkdir()
        done = run("--check")
        check("battery: config.json is a folder, not a file: exit 3 (is_file, not exists)", done.returncode == 3 and done.stdout == "",
              done.stderr[-200:])
        (nested / "qa-factory" / "config.json").rmdir()
        (nested / "qa-factory").rmdir()

        # E17: the marker appears, and the same folder now prepares into its own root; E20: from a subfolder too.
        mark_project(nested)
        done = run("--prepare", "--session", SESSION)
        out = json.loads(done.stdout) if done.returncode == 0 else {}
        check("config appears: the same folder now prepares into its own root",
              done.returncode == 0 and out.get("root") == str(nested.resolve()), done.stderr[-300:])
        check("config appears: nothing at the repository top", not (top / "qa-factory").exists())
        done = run("--check", cwd=sub)
        out = json.loads(done.stdout) if done.stdout.strip() else {}
        check("nested with config from a subfolder: the root is the marker's, not the git top",
              out.get("root") == str(nested.resolve()) and not (top / "qa-factory").exists(), done.stderr[-300:])
    finally:
        cleanup(top)
        cleanup(home)


def check_not_in_text(name, needle, text):
    return check(name, needle not in str(text), f"{needle!r} unexpectedly found in:\n{str(text)[:400]}")


def item6_skill_and_evals(unused):
    """The doctor's skill stays within its byte budget; eval 13 carries its assertions."""
    skill_path = SCRIPTS.parent / "skills" / "qa-doctor" / "SKILL.md"
    check("SKILL.md stays at most 19000 bytes", len(skill_path.read_bytes()) <= 19000, str(len(skill_path.read_bytes())))
    evals = json.loads((skill_path.parent / "evals" / "evals.json").read_text(encoding="utf-8"))["evals"]
    ids = [e["id"] for e in evals]
    check("evals.json ids are unique", len(ids) == len(set(ids)), str(ids))
    eval13 = next((e for e in evals if e["id"] == 13), {})
    names = {a.get("name") for a in eval13.get("assertions", [])}
    check("evals.json id 13 has its assertions", {"no-pair-no-probe", "unknown-owner-factory", "no-inactive-hooks-claim",
                                                  "next-step-onboarding", "nothing-created-at-repo-root"} <= names, str(names))


# --- role context: the delivery of a real dispatch's packet (HF8-12, W-5; spec r0107-s4a section 3 N3, edges E9, E17-E27) ----------
# The expectations come from the requirement (a role dispatched by the factory was handed its packet: the heading sits among
# the first rows of its own transcript, before its first move) and from the spawn gate (a receipt never opens it), never from
# what the code prints (FR-58).
HEADING = "# Resolved task packet"


def user_row(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def assistant_row(text="working"):
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def packet_rows(heading_row, total=24):
    """`total` input rows of a child, the packet heading in row `heading_row` (1-based), then the child's first answer."""
    rows = [user_row(f"opening row {n}") for n in range(1, total + 1)]
    rows[heading_row - 1] = user_row("Do the task.\n\n" + HEADING + " (reuse paths and completed checks)\n{}")
    return rows


def context_stop(project, rows, name, session="parent", agent_type="qa-scout", **extra):
    path = project / (name + ".jsonl")
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    event = {"hook_event_name": "SubagentStop", "session_id": session, "agent_id": "agent-" + name,
             "agent_type": agent_type, "agent_transcript_path": str(path)}
    event.update(extra)
    host_probe.check_role_context(project, event)
    return event


def delivery_files(project):
    return sorted((project / "qa-factory/state/host-receipts").glob("context-delivery-*.json"))


def hand_receipt(project, name, **over):
    row = {"session_id": "s-" + name, "agent_type": "qa-scout", "host": "claude-code",
           "child_transcript": "t.jsonl", "fingerprint": host_probe.fingerprint(project),
           "observed_at": datetime.now(timezone.utc).isoformat()}
    row.update(over)
    folder = project / "qa-factory/state/host-receipts"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"context-delivery-{name}.json").write_text(json.dumps(row), encoding="utf-8")
    return row


def item_role_context_receipt(project):
    from unittest import mock
    context_stop(project, packet_rows(20), "r20", session="s20", agent_type="qa-scout")
    got = delivery_files(project)
    check_eq("heading in row 20 counts: one receipt", len(got), 1)
    row = json.loads(got[0].read_text(encoding="utf-8")) if got else {}
    check_eq("...it names the session, its role, the host the event came from and the child's transcript, and no other key (AR-22)",
             (row.get("session_id"), row.get("agent_type"), row.get("host"), sorted(row)),
             ("s20", "qa-scout", "claude-code",
              ["agent_type", "child_transcript", "fingerprint", "host", "observed_at", "session_id"]))
    check_eq("...the child's transcript is the file the heading was read in", row.get("child_transcript"),
             str(project / "r20.jsonl"))
    check_eq("...and it is bound to the bytes of this project and package", row.get("fingerprint"), host_probe.fingerprint(project))
    context_stop(project, packet_rows(21), "r21", session="s21")
    check_eq("heading in row 21 does not count: still one receipt", len(delivery_files(project)), 1)
    context_stop(project, [user_row("opening"), assistant_row("I will quote it: " + HEADING)] + packet_rows(3, 5), "late", session="s-late")
    check_eq("heading after the first assistant row does not count (E17)", len(delivery_files(project)), 1)
    codex_rows = [{"type": "session_meta", "payload": {"id": "c1"}},
                  {"type": "response_item", "payload": {"type": "message", "role": "developer",
                                                        "content": [{"type": "input_text", "text": "Task.\n\n" + HEADING + "\n{}"}]}},
                  codex_tool("function_call")]
    context_stop(project, codex_rows, "cx", session="s-cx", turn_id="t1")
    got = [json.loads(p.read_text(encoding="utf-8")) for p in delivery_files(project)]
    check_eq("a Codex response_item row carries the heading: counted, host codex",
             sorted((r["session_id"], r["host"]) for r in got), [("s-cx", "codex"), ("s20", "claude-code")])
    late_codex = [{"type": "session_meta", "payload": {"id": "c2"}}, codex_tool("function_call"),
                  {"type": "response_item", "payload": {"type": "message", "role": "developer",
                                                        "content": [{"type": "input_text", "text": HEADING}]}}]
    context_stop(project, late_codex, "cx2", session="s-cx2", turn_id="t1")
    check_eq("a Codex heading after the first tool call does not count", len(delivery_files(project)), 2)

    before = len(delivery_files(project))
    probe_rows = [user_row("QA_FACTORY_CONTEXT_PROBE\n\nRead-only doctor diagnostic: do not collect tickets or use tools. "
                           "Return exactly QA_CONTEXT_RECEIVED_" + C32 + "_END."), assistant_row(PREFIX + C32 + "_END")]
    context_stop(project, probe_rows, "probe", session="s-probe")
    check_eq("probe child writes no role receipt (E18)", len(delivery_files(project)), before)

    broken = project / "broken.jsonl"
    cases = {"no path": {"hook_event_name": "SubagentStop", "session_id": "s-b1"},
             "a path that is not there": {"hook_event_name": "SubagentStop", "session_id": "s-b2",
                                          "agent_transcript_path": str(project / "nowhere.jsonl")},
             "a path of another type": {"hook_event_name": "SubagentStop", "session_id": "s-b3", "agent_transcript_path": 7},
             "no session": {"hook_event_name": "SubagentStop", "agent_transcript_path": str(broken)},
             "not a stop": {"hook_event_name": "PostToolUse", "session_id": "s-b4", "agent_transcript_path": str(broken)}}
    broken.write_text("{not json\n" + json.dumps(packet_rows(1)[0]) + "\n", encoding="utf-8")
    for label, event in cases.items():
        failure = raised(lambda e=event: host_probe.check_role_context(project, e))
        check_eq(f"E19: {label}: no exception, no receipt", (failure, len(delivery_files(project))), ("", before))
    for label, text in {"a row that is not JSON": "{not json\n", "a row that is a list": "[1, 2]\n",
                        "the heading behind a broken row": "oops\n" + json.dumps(packet_rows(1)[0]) + "\n"}.items():
        broken.write_text(text, encoding="utf-8")
        event = {"hook_event_name": "SubagentStop", "session_id": "s-b5", "agent_transcript_path": str(broken)}
        failure = raised(lambda e=event: host_probe.check_role_context(project, e))
        check_eq(f"E19: {label}: no exception, no receipt", (failure, len(delivery_files(project))), ("", before))

    calls = []
    real = host_probe.fingerprint
    with mock.patch.object(host_probe, "fingerprint", side_effect=lambda r: (calls.append(1), real(r))[1]):
        context_stop(project, packet_rows(2), "twice-1", session="s-twice")
        first = len(calls)
        one = json.loads(host_probe._context_path(project, "s-twice").read_text(encoding="utf-8"))
        context_stop(project, packet_rows(2), "twice-2", session="s-twice")
        two = json.loads(host_probe._context_path(project, "s-twice").read_text(encoding="utf-8"))
        context_stop(project, [user_row("no packet at all")], "twice-3", session="s-twice")
        three = json.loads(host_probe._context_path(project, "s-twice").read_text(encoding="utf-8"))
    check_eq("a second stop of the session does not walk the fingerprint", (first, len(calls)), (1, 1))
    check_eq("F2: ...it refreshes observed_at and keeps the held fingerprint, so a later story of the session is seen after its S0",
             (two["observed_at"] > one["observed_at"], two["fingerprint"] == one["fingerprint"], two["child_transcript"]),
             (True, True, str(project / "twice-2.jsonl")))
    check_eq("F2: ...a stop with no packet rewrites nothing", three, two)

    gone = project / "qa-factory/state/host-receipts" / delivery_files(project)[0].name
    before_config = (project / "qa-factory/config.json").read_text(encoding="utf-8")
    stamp = json.loads(gone.read_text(encoding="utf-8"))["fingerprint"]
    (project / "qa-factory/config.json").write_text(before_config.rstrip()[:-1] + ', "changed_after_receipt": 1}', encoding="utf-8")
    try:
        check_eq("changed config: role_context is None", host_probe.role_context(project), None)
        files_before = len(delivery_files(project))
        context_stop(project, packet_rows(2), "after-config", session="s20")
        check_eq("...and no new receipt is written in that session (the cost of the early exit, E20)",
                 (len(delivery_files(project)), json.loads(gone.read_text(encoding="utf-8"))["fingerprint"]), (files_before, stamp))
        context_stop(project, packet_rows(2), "after-config2", session="s-new-session")
        check_eq("...a new session records at its first dispatch", len(delivery_files(project)), files_before + 1)
    finally:
        (project / "qa-factory/config.json").write_text(before_config, encoding="utf-8")


def item_role_context_reader(project):
    ttl = host_probe.PROBE_TTL_S
    now = datetime.now(timezone.utc)
    check_eq("no folder: role_context is None, no exception", host_probe.role_context(project), None)
    hand_receipt(project, "fresh", observed_at=(now - timedelta(seconds=ttl - 60)).isoformat())
    got = host_probe.role_context(project)
    check_eq("an age just under PROBE_TTL_S is evidence", got and got["session_id"], "s-fresh")
    check_eq("...and so is the same receipt when the caller hands the fingerprint it walked",
             host_probe.role_context(project, host_probe.fingerprint(project)) == got, True)
    check_eq("another fingerprint: None", host_probe.role_context(project, "0" * 64), None)
    hand_receipt(project, "fresh", fingerprint="1" * 64)
    check_eq("role_context on another fingerprint is None (stored bytes differ)", host_probe.role_context(project), None)
    hand_receipt(project, "fresh", observed_at=(now - timedelta(seconds=ttl)).isoformat())
    check_eq("age at PROBE_TTL_S is None", host_probe.role_context(project), None)
    hand_receipt(project, "fresh", observed_at=(now + timedelta(hours=1)).isoformat())
    check_eq("a future time is no evidence", host_probe.role_context(project), None)
    hand_receipt(project, "fresh", observed_at=now.replace(tzinfo=None).isoformat())
    check_eq("E26: a time with no UTC offset: None", host_probe.role_context(project), None)
    folder = project / "qa-factory/state/host-receipts"
    for label, text in {"unreadable bytes": None, "not JSON": "{oops", "JSON that is not an object": "[1]",
                        "a field of another type": json.dumps({"session_id": 5, "host": ["x"], "fingerprint": 1,
                                                               "observed_at": 7})}.items():
        target = folder / "context-delivery-broken.json"
        if text is None:
            target.write_bytes(b"\xff\xfe\x00")
        else:
            target.write_text(text, encoding="utf-8")
        got = host_probe.role_context(project)
        failure = raised(lambda: host_capabilities.inspect(project))
        check_eq(f"E26: {label}: role_context None, inspect does not raise", (got, failure), (None, ""))
    target.unlink()
    hand_receipt(project, "old", observed_at=(now - timedelta(seconds=600)).isoformat(), session_id="older")
    hand_receipt(project, "fresh", observed_at=(now - timedelta(seconds=60)).isoformat())
    check_eq("the newest valid receipt wins", host_probe.role_context(project)["session_id"], "s-fresh")


def arm_guard(project, session="parent"):
    """A project whose live allow/deny guard is `verified` by its own checks (the transcript lookup patched, as item3b does)."""
    host_probe.prepare(project, session)
    data = store(project)
    data["checks"] = {"allow_guard": {"exit_code": 0, "tool_use_id": "a"}, "deny_guard": {"exit_code": 2, "tool_use_id": "d"},
                      "allow_executed": {"exit_code": 0, "tool_use_id": "a"}}
    write_store(project, data)


def item_role_context_gate(project):
    """E9: a receipt of a real dispatch is a statement about that dispatch; it never opens the spawn gate (`story_ready`),
    and on Codex it never makes `host_hooks` ok either."""
    from unittest import mock
    import readiness
    from harness import use_project
    use_project(project)
    config = json.loads((project / "qa-factory/config.json").read_text(encoding="utf-8"))

    def hooks():
        return readiness.compute(config, project)["capabilities"]["host_hooks"]

    def drop_receipts():
        for old in delivery_files(project):
            old.unlink()

    with mock.patch.object(host_probe, "host_call_present", return_value=True):
        arm_guard(project)
        caps = host_capabilities.inspect(project)
        check_eq("(control) a verified guard, no real dispatch seen: role_context None, hooks not proved, the door in the note",
                 (caps["role_context"], host_capabilities.hooks_proved(caps), "Dispatch the read-only qa_factory_context_probe" in caps["note"]),
                 (None, False, True))
        check_eq("(control) ...and readiness says unknown", hooks()["status"], "unknown")
        context_stop(project, packet_rows(3), "real", session="parent", agent_type="qa-scout")
        caps = host_capabilities.inspect(project)
        check_eq("E9: verified guard + role_context: story_ready False, injection unverified",
                 (caps["story_ready"], caps["guard_probe"]["injection"], caps["live_parity"], caps["mechanisms"]["inject_context.py"]["behavior"]),
                 (False, "unverified", "not_certified", "unverified"))
        check_eq("...the answer carries the receipt and says what was seen",
                 (caps["role_context"]["agent_type"], caps["note"].startswith("Live allow/deny guard verified; role-context delivery seen in a real dispatch of qa-scout at ")),
                 ("qa-scout", True))
        check_eq("...hooks are proved", host_capabilities.hooks_proved(caps), True)
        with mock.patch.object(host_probe, "fingerprint", side_effect=AssertionError("a second walk")):
            check_eq("the receipt is judged by the bytes inspect walked: no second walk of the package",
                     host_probe.role_context(project, store(project)["fingerprint"])["session_id"], "parent")
        entry = hooks()
        check_eq("readiness: host_hooks ok, proved by the role context, the remedy kept",
                 (entry["status"], entry.get("proved_by"), "remedy" in entry), ("ok", "role_context", True))
        drop_receipts()
        context_stop(project, packet_rows(3), "real-codex", session="parent", agent_type="qa-scout", turn_id="t1")
        caps = host_capabilities.inspect(project)
        entry = hooks()
        check_eq("E9: codex role_context does not make host_hooks ok, the door stays",
                 (host_capabilities.hooks_proved(caps), caps["story_ready"], "qa_factory_context_probe" in caps["note"], entry["status"]),
                 (False, False, True, "unknown"))
    drop_receipts()
    host_probe.prepare(project, "parent")   # a fresh probe: no checks, the guard is unverified
    context_stop(project, packet_rows(3), "real-2", session="parent")
    caps = host_capabilities.inspect(project)
    check_eq("E9: role_context + unverified guard: host_hooks unknown (readiness.compute)",
             (caps["role_context"] is not None, caps["guard_probe"]["status"], hooks()["status"]), (True, "unverified", "unknown"))
    check_eq("...the note keeps its door for the guard", "host_probe.py --prepare" in caps["note"], True)


def item_store_reader_and_hook(project):
    """F3/F4: every reader of the store on a hook path is the one reader, and a store of another shape is "no answer", never an
    exception (exit 1 is not a block on Claude Code). Then the recorder order of the hook wrapper (the `target_done` key)."""
    import hooklib
    import io
    from unittest import mock
    import telemetry_hook
    path = project / "qa-factory/state/host-probe.json"
    event = {"session_id": "s-shape", "tool_use_id": "spawn", "tool_input": {"prompt": "QA_FACTORY_CONTEXT_PROBE"}}
    host_probe.prepare(project, "s-shape")
    good = path.read_text(encoding="utf-8")
    check_eq("(control) a valid store hands out the challenge", host_probe.injection_marker(project, event).startswith("\n\nRead-only"), True)
    for label, text in {"a list": "[1]", "a number": "7", "a string": '"x"', "not JSON": "{oops", "empty": ""}.items():
        path.write_text(text, encoding="utf-8")
        got = []
        failure = raised(lambda: got.append(host_probe.injection_marker(project, event)))
        check_eq(f"F3: injection_marker on a store that is {label}: no exception, no challenge", (failure, got), ("", [""]))
        check_eq("F3: ...and observe on it: nothing observed", host_probe.observe(project, dict(event, hook_event_name="PreToolUse")), False)
    path.write_bytes(b"\xef\xbb\xbf" + good.encode("utf-8"))
    check_eq("F4: a store with a BOM is read like any JSON file of the package (the one reader)",
             isinstance(host_probe._read_dict(path), dict), True)
    path.unlink()
    path.mkdir()
    check_eq("F4: a directory where the store should be: None, no exception", (raised(lambda: host_probe._read_dict(path)), host_probe._read_dict(path)),
             ("", None))
    path.rmdir()

    # the target ran and finished clean, a recorder after it raises a TypeError: the guard's exit 0 stays on record (the order of
    # `target_done`: the failure path must not record a failure of the target for a failure of a recorder)
    allow = host_probe.prepare(project, "s-hook")["commands"][0]
    guard = project / "fake" / "guard_pre_tool.py"
    guard.parent.mkdir()
    guard.write_text("pass\n", encoding="utf-8")
    hook = {"hook_event_name": "PreToolUse", "session_id": "s-hook", "tool_name": "Bash", "tool_use_id": "a1",
            "tool_input": {"command": allow}, "cwd": str(project)}
    hooklib._PROJECT_ROOT_CACHE = None
    try:
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(project)}), \
                mock.patch.object(sys, "argv", ["telemetry_hook.py", str(guard)]), \
                mock.patch.object(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps(hook).encode("utf-8")), encoding="utf-8")), \
                mock.patch.object(host_probe, "note_guard_parse", side_effect=TypeError("a recorder failed after the guard")):
            failure = raised(telemetry_hook.main)
    finally:
        hooklib._PROJECT_ROOT_CACHE = None
    recorded = (store(project)["checks"].get("allow_guard") or {}).get("exit_code")
    check_eq("target_done: a recorder raises after a clean guard: the TypeError leaves, allow_guard stays exit 0 (not 1)",
             (failure, recorded), ("TypeError", 0))


def guarded(item, arg):
    """One item crashing must not hide the verdict of the others: report it as a failure."""
    try:
        item(arg)
    except Exception as exc:  # noqa: BLE001
        check(item.__name__ + " ran to the end", False, type(exc).__name__ + ": " + str(exc))


def main():
    root = temp_project("qa-probe-shapes-")
    try:
        for item in (item1_native_patch, item2_wrapped_probe, item_probe_command, item3_sentinel, item3_verdicts,
                     item3_unreadable, item3_returned, item3_real_rows, item3_form, item3_tool, item3b_detail,
                     item_rn1_1_launch_id):
            guarded(item, root)
    finally:
        cleanup(root)
    project = temp_project("qa-probe-root-")
    try:
        guarded(item4_root, project)
    finally:
        cleanup(project)
    project = temp_project("qa-probe-identity-")
    try:
        guarded(item5_identity, project)
    finally:
        cleanup(project)
    guarded(item6_before_onboarding, None)
    guarded(item6_skill_and_evals, None)
    for item in (item_role_context_receipt, item_role_context_reader, item_role_context_gate, item_store_reader_and_hook):
        project = temp_project("qa-probe-rolectx-")
        try:
            guarded(item, project)
        finally:
            cleanup(project)
    finish("test_host_probe_shapes")


if __name__ == "__main__":
    main()
