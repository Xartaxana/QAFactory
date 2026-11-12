"""The context probe reads a child's answer that comes back through the host's handback call (OH3-13).

Claude Code (10.2026) returns a subagent's final report through a tool call: the child's assistant rows carry
no text block, only that call, whose `input` holds the words (measured: `input.message`). `_assistant_texts` read
text blocks only and counted every `tool_use` as a tool the child used, so a probe child that answered the
challenge perfectly was judged `tool_used` (or nothing at all) and `host_probe.py --check` kept asking for a
re-probe. The handback call is the answer: its strings are the child's texts and it is not a tool used.

The call's name is NOT in the code: it is a row of `references/host-report-forms.json`, read through
`host_adapter.report_forms` (AR-1, AR-5), matched exactly. With no readable form no call is a handback and the
probe stays unverified (AR-28). This test builds its transcripts with the name read from that same file, so a
renamed row moves the test with the data, not the other way round.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import check, check_eq, cleanup, finish, temp_dir  # noqa: E402

import host_adapter as HA  # noqa: E402
import host_probe as H  # noqa: E402

CHALLENGE = "0123456789abcdef0123456789abcdef"
ANSWER = H.CHALLENGE_PREFIX + CHALLENGE + "_END"
TOOL = HA.report_forms()[0]["claude"]["handback_tool"]


def transcript(rows) -> bytes:
    return (chr(10).join(json.dumps(r) for r in rows) + chr(10)).encode("utf-8")


def call(name, payload) -> dict:
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "toolu_x", "name": name, "input": payload}]}}


def handback(text, field="message") -> dict:
    """The measured real shape is {"message": <report>}; `field` lets another key be tried."""
    return call(TOOL, {field: text})


def event_for(path) -> dict:
    return {"agent_id": "agent-1", "session_id": "s-1", "agent_transcript_path": str(path)}


def emitted_store(store) -> None:
    store.write_text(json.dumps({"session_id": "s-1", "injection": {
        "agent_id": "agent-1", "challenge": CHALLENGE, "status": "emitted"}}), encoding="utf-8")


def judged(root, store, path, rows) -> str:
    """What check_child leaves in the store for a child transcript of `rows`."""
    emitted_store(store)
    path.write_bytes(transcript(rows))
    H.check_child(root, event_for(path))
    return json.loads(store.read_text(encoding="utf-8"))["injection"].get("status")


def main() -> None:
    user = {"type": "user", "message": {"content": "Return exactly " + ANSWER}}

    # E3: the measured real shape, input.message.
    texts, used = H._assistant_texts(transcript([user, handback(ANSWER)]))
    check_eq("the measured shape input.message is the child's text", texts, [ANSWER])
    check("and the handback is not a tool the child used", not used)
    texts, used = H._assistant_texts(transcript([user, handback(ANSWER, "report")]))
    check_eq("another string field of the call is read too (no field list in code)", texts, [ANSWER])

    nested = call(TOOL, {"summary": "done", "parts": [{"text": ANSWER}, 7]})
    texts, used = H._assistant_texts(transcript([user, nested]))
    check("every string inside the handback input is read, however nested", ANSWER in texts and "done" in texts)
    check("a number inside it is not a text", 7 not in texts and not used)

    texts, used = H._assistant_texts(transcript([user, call(TOOL, "a bare string input " + ANSWER)]))
    check("an input that is itself a string is read", texts == ["a bare string input " + ANSWER] and not used)

    texts, used = H._assistant_texts(transcript([user, call(TOOL, None)]))
    check("a handback with no input holds no text and is still not a tool", texts == [] and not used)

    bash = call("Bash", {"command": "ls"})
    texts, used = H._assistant_texts(transcript([user, bash, handback(ANSWER)]))
    check("a real tool call before the handback still counts as a tool used", used and ANSWER in texts)

    plain = {"type": "assistant", "message": {"content": [{"type": "text", "text": ANSWER}]}}
    texts, used = H._assistant_texts(transcript([user, plain]))
    check_eq("a plain text answer reads as before", (texts, used), ([ANSWER], False))

    # Exact-name match: a call that only resembles the handback is a tool and its input is not the child's text.
    for label, name in (("lower case", TOOL.lower()), ("trailing space", TOOL + " "),
                        ("an mcp prefix", "mcp__x__" + TOOL), ("a suffix", TOOL + "2"), ("empty name", "")):
        texts, used = H._assistant_texts(transcript([user, call(name, {"message": ANSWER})]))
        check(f"{label}: not a handback - counted as a tool, its input not read", used and ANSWER not in texts)
    nameless = {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t", "input": {"message": ANSWER}}]}}
    texts, used = H._assistant_texts(transcript([user, nameless]))
    check("a tool_use with no name is not a handback (None never equals the tool name)", used and ANSWER not in texts)
    texts, used = H._assistant_texts(transcript([user, {"type": "assistant", "message": {"content": [
        {"type": "text", "name": TOOL, "text": "x", "input": {"message": ANSWER}}]}}]))
    check("the name alone is not enough: the block must be a tool_use", ANSWER not in texts and not used)

    root = temp_dir("qa-probe-handback-")
    saved = HA.REPORT_FORMS_FILE
    try:
        (root / "qa-factory" / "state").mkdir(parents=True)
        (root / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
        store = root / "qa-factory" / "state" / "host-probe.json"
        path = root / "child.jsonl"

        # end to end: the SubagentStop judgement
        check_eq("check_child judges a handback answer delivered", judged(root, store, path, [user, handback(ANSWER)]),
                 "delivered")
        check_eq("and records the transcript it read",
                 json.loads(store.read_text(encoding="utf-8"))["injection"].get("child_transcript"), str(path))
        wrong = H.CHALLENGE_PREFIX + "f" * 32 + "_END"
        check_eq("a wrong challenge through a handback is a mismatch, as a text one is",
                 judged(root, store, path, [user, handback(wrong)]), "mismatch")
        check_eq("a child that used a real tool, then handed back the right answer, is tool_used",
                 judged(root, store, path, [user, bash, handback(ANSWER)]), "tool_used")
        check_eq("a child that handed back nothing of the prefix writes nothing (emitted stays)",
                 judged(root, store, path, [user, handback("no answer")]), "emitted")

        # E2: no usable form -> no call is a handback -> the probe stays unverified, never delivered.
        forms_dir = root / "forms"
        forms_dir.mkdir()
        broken = {
            "file absent": forms_dir / "absent.json",
            "file unreadable (a directory)": forms_dir,
            "not JSON": None,
            "not an object": None,
            "handback_tool not a string": None,
            "handback_tool empty": None,
            "no claude row": None,
        }
        bodies = {"not JSON": "SubagentHandback", "not an object": json.dumps([TOOL]),
                  "handback_tool not a string": json.dumps({"claude": {"handback_tool": [TOOL]}}),
                  "handback_tool empty": json.dumps({"claude": {"handback_tool": ""}}),
                  "no claude row": json.dumps({"codex": {}})}
        for label, target in broken.items():
            if target is None:
                target = forms_dir / (label.replace(" ", "-") + ".json")
                target.write_text(bodies[label], encoding="utf-8")
            HA.REPORT_FORMS_FILE = target
            texts, used = H._assistant_texts(transcript([user, handback(ANSWER)], ))
            check(f"{label}: the handback is a tool call and its answer is not read", used and ANSWER not in texts)
            # t-075 (survivor t057-2): with NO readable form the handback name is None, and a tool_use that carries no name
            # has `name` None too - None == None must not read its input as the child's text
            texts, used = H._assistant_texts(transcript([user, nameless]))
            check(f"{label}: and a tool_use with no name is still not a handback (None is not a name)",
                  used and ANSWER not in texts)
            check_eq(f"{label}: check_child leaves the probe unverified (emitted), never delivered",
                     judged(root, store, path, [user, handback(ANSWER)]), "emitted")
            plain_status = judged(root, store, path, [user, plain])
            check_eq(f"{label}: a plain text answer is still judged as before", plain_status, "delivered")
        HA.REPORT_FORMS_FILE = saved

        # A host whose forms name another tool: the new name is the handback, the old one is just a tool.
        other = forms_dir / "other.json"
        other.write_text(json.dumps({"claude": {"handback_tool": "ReturnReport"}}), encoding="utf-8")
        HA.REPORT_FORMS_FILE = other
        texts, used = H._assistant_texts(transcript([user, call("ReturnReport", {"message": ANSWER})]))
        check("the name comes from the data: a renamed row is the handback", texts == [ANSWER] and not used)
        texts, used = H._assistant_texts(transcript([user, handback(ANSWER)]))
        check("and the former name is then an ordinary tool", used and ANSWER not in texts)
    finally:
        HA.REPORT_FORMS_FILE = saved
        cleanup(root)
    finish("test_host_probe_handback")


if __name__ == "__main__":
    main()
