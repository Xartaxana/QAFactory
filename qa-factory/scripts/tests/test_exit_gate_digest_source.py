#!/usr/bin/env python3
"""HF4-6 (hotfix-12586/4): the exit gate judges the role's OWN last word, read from the subagent's own transcript.

Run 12586 blocked a role 17 times with "your final message is not the handoff form", quoting the PARENT session's
prose: `handoff_digest` read the `transcript_path` of the event, which on a SubagentStop is the session that stopped
the child, while the child's word lives in `agent_transcript_path`, as the input of its handback call. Keys:
K1 seam on the recorded run, K3 the old path unchanged, K4 unreadable child file, K5 the 400-row limit AT and BEYOND,
K6 halt, K7 `last_assistant_message`, K8 uncomfortable inputs, K9 (the probe's own tests, run apart), plus the
Codex form (decision F-2), K10 the seam through the gate's own composition, K11 the unread-child signal.
"""
import io
import json
import sys
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import exit_gate  # noqa: E402
import host_adapter as HA  # noqa: E402
import role_digest as RD  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "run-12586-digest"
HANDBACK = "SubagentHandback"
HALT = "qa-scout S1 halt · work/source-inventory.json · no diff - give --mr"


def digest_of(event: dict):
    """(digest, stderr text) of one event."""
    err = io.StringIO()
    with redirect_stderr(err):
        digest = exit_gate.handoff_digest(event)
    return digest, err.getvalue()


def assistant(*blocks) -> str:
    return json.dumps({"type": "assistant", "message": {"content": list(blocks)}})


def text(value: str) -> dict:
    return {"type": "text", "text": value}


def handback(value, name: str = HANDBACK) -> dict:
    return {"type": "tool_use", "id": "toolu_x", "name": name, "input": value}


def tool_result() -> str:
    return json.dumps({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "toolu_x", "content": [{"type": "text", "text": "{\"success\":true}"}]}]}})


def put(root: Path, name: str, rows: list) -> str:
    path = root / name
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return str(path)


def fixture_event() -> dict:
    event = json.loads((FIXTURE / "event.json").read_text(encoding="utf-8"))
    event["transcript_path"] = str(FIXTURE / event["transcript_path"])
    event["agent_transcript_path"] = str(FIXTURE / event["agent_transcript_path"])
    return event


def the_recorded_run_12586_reads_the_roles_own_word():
    """K1 + K2 + seam: the recorded SubagentStop yields the handback input, not the conductor's prose."""
    event = fixture_event()
    child = [json.loads(line) for line in Path(event["agent_transcript_path"]).read_text(encoding="utf-8").splitlines()]
    expected = child[0]["message"]["content"][0]["input"]["message"]
    digest, err = digest_of(event)
    check_eq("K1: the digest is exactly the handback input of the child's row", digest, expected)
    check_eq("K1: nothing is said on stderr when the word is found", err, "")
    check_not_in("K1: the parent's prose is not the role's word", "second-round case critic", digest)
    parent_digest, _ = digest_of({"transcript_path": event["transcript_path"]})
    check_in("the parent's own text is what the OLD path read (the false block's source)", "second-round case critic", parent_digest)
    # the seam: what the gate's judge (role_digest) does with the recorded word. The form errors of run 12586 named the
    # FIRST LINE of the parent's prose; the role's own word has a header line, so no such error can be raised.
    errors = RD.check(digest, ["TC-014"])
    shown = "\n".join(errors)
    check_not_in("seam: no 'first line is not a digest header' for the role's own word", "not a digest header", shown)
    check_not_in("seam: no 'this line is not in the form' for the role's own word", "this line is not in the form", shown)
    check_not_in("seam: the parent's prose is nowhere in what the gate would say", "case critic is checking", shown)
    # K2 (the seam, FULL result): the recorded role wrote the state `approved (approve_with_concerns)`; the role is told
    # the verdict words, so the gate must hold them. No refusal at all.
    check_eq("K2 seam: the recorded run-12586 word passes the digest check whole", errors, [])
    check_eq("K2 seam: the same through the exit gate's own check of the digest", RD.parse(digest)["errors"], [])


def the_row_state_reader_takes_the_verdict_words_and_the_recorded_spelling():
    """K2 edges: the verdict words come from the one constant; `<word> (<state>)` is read; the rest is refused."""
    import critic_rollcall as CR

    def row(state: str):
        digest = f"qa-case-critic S4 TC-014 · ok\nTC-014 · {state} · reason\nwork/test-cases/critic-findings.md"
        return RD.check(digest, ["TC-014"])

    for word in CR.CASE_CRITIC_VERDICTS:
        check(f"K2: the verdict word {word} is a row state", word in RD.ROW_STATES)
        check_eq(f"K2: a row `{word}` passes", row(word), [])
    check_eq("K2: `approve (reject)` - both known, the first word wins",
             RD.parse("qa-case-critic S4 TC-014 · ok\nTC-014 · approve (reject) · r\nw/x.md")["rows"][0]["state"], "approve")
    check_eq("K2: first word not a state, the parenthesised known state is taken",
             RD.parse("qa-case-critic S4 TC-014 · ok\nTC-014 · looked-fine (reject) · r\nw/x.md")["rows"][0]["state"], "reject")
    check_eq("K2: `approve (reject)` passes", row("approve (reject)"), [])
    check_eq("K2: `looked-fine (partial)` passes", row("looked-fine (partial)"), [])
    for bad in ("approve ()", "approve ( )", "looked-fine (nonsense)", "approve (nonsense)", "nonsense (nonsense)",
                "looked-fine (reject) tail", "looked-fine ((reject))"):
        shown = "\n".join(row(bad))
        check_in(f"K2: `{bad}` is refused", "is not a state of the form", shown)
    check_in("K2: the refusal lists the verdict words", "approve_with_concerns", "\n".join(row("nonsense")))
    check_eq("K2: a verdict word on a non-critic role's row is accepted (shared vocabulary)",
             RD.check("qa-scout S1 work · ok\nsrc-1 · approve_with_concerns · r\nwork/x.json", ["src-1"]), [])


def the_old_path_is_unchanged_without_a_child_path():
    """K3: the same event without `agent_transcript_path` reads `transcript_path` as before."""
    event = fixture_event()
    del event["agent_transcript_path"]
    digest, _ = digest_of(event)
    check_in("K3: the parent's last word is read as before", "second-round case critic", digest)


def an_unreadable_child_file_is_not_judged_and_not_the_parents():
    """K4: the child's file is named but absent/unusable: "" + one stderr line, never the parent's text."""
    root = temp_dir("hf46-k4-")
    try:
        parent = put(root, "parent.jsonl", [assistant(text("parent prose: do the next thing"))])
        for label, value in (("absent file", str(root / "gone.jsonl")), ("number", 5), ("null", None), ("empty string", ""),
                             ("a directory", str(root))):
            digest, err = digest_of({"transcript_path": parent, "agent_transcript_path": value,
                                     "last_assistant_message": "parent prose too"})
            check_eq(f"K4: {label} gives no digest", digest, "")
            check_in(f"K4: {label} says so once on stderr", "its digest is not judged and not filed", err)
            check_eq(f"K4: {label} - exactly one gate note on stderr",
                     len([l for l in err.splitlines() if l.startswith("exit gate note:")]), 1)
        empty = put(root, "empty.jsonl", ["not json", "[1]", '"x"', tool_result()])
        digest, err = digest_of({"transcript_path": parent, "agent_transcript_path": empty})
        check_eq("K4: a child file with no assistant word gives no digest", digest, "")
        check_in("K4: and says so", "no assistant word", err)
    finally:
        cleanup(root)


def the_tail_limit_is_400_rows():
    """K5: the role's word on the 400th row from the end is read, on the 401st it is not."""
    root = temp_dir("hf46-k5-")
    try:
        word = "qa-scout S1 done · work/manifest.json · 12 sources"
        filler = [json.dumps({"type": "user", "message": {"content": "tool output"}})]
        at = put(root, "at.jsonl", [assistant(handback({"message": word}))] + filler * 399)
        beyond = put(root, "beyond.jsonl", [assistant(handback({"message": word}))] + filler * 400)
        parent = put(root, "parent.jsonl", [assistant(text("parent prose"))])
        digest, err = digest_of({"transcript_path": parent, "agent_transcript_path": at})
        check_eq("K5 AT: the word on the 400th row from the end is read", digest, word)
        digest, err = digest_of({"transcript_path": parent, "agent_transcript_path": beyond})
        check_eq("K5 BEYOND: the word on the 401st row is not read, and the parent's is not put in its place", digest, "")
        check_in("K5 BEYOND: stderr says it was not found", "its digest is not judged and not filed", err)
    finally:
        cleanup(root)


def a_halt_is_the_roles_and_the_parents_halt_is_not():
    """K6: a halt in the handback is a halt; the parent's `qa-scout S1 halt` line is not the role's."""
    root = temp_dir("hf46-k6-")
    try:
        child = put(root, "child.jsonl", [assistant(handback({"message": HALT})), tool_result()])
        quiet = put(root, "quiet.jsonl", [assistant(text("working"))])
        parent = put(root, "parent.jsonl", [assistant(text(HALT))])
        digest, _ = digest_of({"transcript_path": parent, "agent_transcript_path": child})
        check("K6: the role's halt is a halt", exit_gate.is_halting_handoff(digest))
        digest, _ = digest_of({"transcript_path": parent, "agent_transcript_path": quiet})
        check("K6: the parent's halt line is not the role's halt when the child path is named",
              not exit_gate.is_halting_handoff(digest))
        digest, _ = digest_of({"transcript_path": parent, "agent_transcript_path": str(root / "gone.jsonl")})
        check("K6: nor when the child's file is unreadable", not exit_gate.is_halting_handoff(digest))
    finally:
        cleanup(root)


def last_assistant_message_is_read_only_without_a_child_path():
    """K7."""
    root = temp_dir("hf46-k7-")
    try:
        parent = put(root, "parent.jsonl", [assistant(text("parent prose"))])
        child = put(root, "child.jsonl", [assistant(text("child word"))])
        digest, _ = digest_of({"last_assistant_message": "the host's own last message", "transcript_path": parent})
        check_eq("K7: without a child path the host's last message comes before the transcript", digest, "the host's own last message")
        digest, _ = digest_of({"last_assistant_message": "the host's own last message", "agent_transcript_path": child})
        check_eq("K7: with a child path it is not read", digest, "child word")
        for bad in ("", "   ", 5, None, ["x"]):
            digest, _ = digest_of({"last_assistant_message": bad, "transcript_path": parent})
            check_eq(f"K7: {bad!r} is no word: the transcript is read", digest, "parent prose")
        digest, _ = digest_of({"last_assistant_message": "x" * 5000})
        check_eq("K7: the limit is 4000 characters", len(digest), 4000)
    finally:
        cleanup(root)


def uncomfortable_inputs_stay_on_the_safe_side():
    """K8: the error direction is 'no word', never an invented one."""
    root = temp_dir("hf46-k8-")
    try:
        def word(rows, **extra):
            path = put(root, "c.jsonl", rows)
            return digest_of({"agent_transcript_path": path, **extra})[0]

        check_eq("K8: an empty handback input gives no word", word([assistant(handback({"message": ""}))]), "")
        check_eq("K8: a handback input that is a number gives no word", word([assistant(handback(7))]), "")
        check_eq("K8: a handback input that is a dict of non-strings gives no word",
                 word([assistant(handback({"a": 1, "b": [None, {"c": 2}]}))]), "")
        check_eq("K8: two text blocks and a handback in one row are joined in order",
                 word([assistant(text("one"), text("two"), handback({"message": "three"}))]), "one\ntwo\nthree")
        check_eq("K8: a tool whose name only resembles the handback is NOT the role's word",
                 word([assistant(handback({"message": "not a word"}, name=HANDBACK + "X"))]), "")
        check_eq("K8: the handback of a different case is not the word either",
                 word([assistant(handback({"message": "not a word"}, name=HANDBACK.lower()))]), "")
        check_eq("K8: a nested input is read whole (message and parts)",
                 word([assistant(handback({"report": {"parts": ["a", "b"]}}))]), "a\nb")
        check_eq("K8: the last row with a word wins; a later tool call without text is passed over",
                 word([assistant(text("earlier")), assistant(handback({"message": "later"})),
                       assistant({"type": "tool_use", "id": "t", "name": "Bash", "input": {"command": "ls"}}), tool_result()]),
                 "later")
        check_eq("K8: a partial last line is skipped, the row before it is read",
                 word([assistant(handback({"message": "whole"})), '{"type": "assistant", "message": {"content": [{"type": "te']),
                 "whole")
        check_eq("K8: a row that is not an object is skipped", word([assistant(text("kept")), "[1]", '"x"', "5"]), "kept")
        check_eq("K8: the limit is 4000 characters", len(word([assistant(handback({"message": "y" * 5000}))])), 4000)
        # forms unreadable: only the text blocks are read, the handback input is not (the safe side), one reader
        saved = HA.REPORT_FORMS_FILE
        HA.REPORT_FORMS_FILE = root / "no-such-forms.json"
        try:
            check_eq("K8: with no readable forms a handback is no word",
                     word([assistant(handback({"message": "invisible"}))]), "")
            check_eq("K8: with no readable forms a text block is still read",
                     word([assistant(text("visible"), handback({"message": "invisible"}))]), "visible")
            digest, err = digest_of({"agent_transcript_path": put(root, "h.jsonl", [assistant(handback({"message": "invisible"}))])})
            check_in("M2: the forms file is named as the cause, not 'no assistant word'", "host report forms unreadable", err)
            check_not_in("M2: and the false cause is not given", "no assistant word", err)
        finally:
            HA.REPORT_FORMS_FILE = saved
        check_eq("K8: the same function on a row that is not an object", HA.assistant_row_texts([1], {}), [])
        check_eq("K8: and on a user row", HA.assistant_row_texts({"type": "user", "message": {"content": "x"}}, {}), [])
    finally:
        cleanup(root)


def a_codex_child_rollout_is_read_by_the_same_path():
    """F-2 (a): one reader for both host forms."""
    root = temp_dir("hf46-codex-")
    try:
        rows = [
            json.dumps({"type": "response_item", "payload": {"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": "the brief"}]}}),
            json.dumps({"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [
                {"type": "output_text", "text": "qa-scout S1 done · work/manifest.json · 3 sources"}]}}),
            json.dumps({"type": "event_msg", "payload": {"type": "task_complete"}}),
        ]
        path = put(root, "rollout.jsonl", rows)
        digest, _ = digest_of({"agent_transcript_path": path})
        check_eq("F-2: the Codex assistant row is the role's word", digest, "qa-scout S1 done · work/manifest.json · 3 sources")
        check_eq("F-2: a Codex user row is not", HA.assistant_row_texts(json.loads(rows[0]), {}), [])
    finally:
        cleanup(root)


def the_recorded_run_goes_through_the_gates_own_composition():
    """K10 (M1, the owner's word 28.10): `digest_errors` with a live S4 case-critic dispatch - live lookup, scope, filing,
    the refusal wrapper. The recorded event gives no refusal and the file is the handback text; the parent-only event
    (the old path, the false block's source) is refused and not filed."""
    ticket, dispatch = "TP1-12586", "S4-qa-case-critic-2"
    root = temp_project("hf46-k10-")
    use_project(root)
    task = root / "qa-factory" / "artifacts" / ticket
    (task / "state").mkdir(parents=True)
    (task / "work").mkdir(parents=True)
    record = {"id": dispatch, "stage": "S4", "role": "qa-case-critic", "status": "running", "scope": ["TC-014"]}
    (task / "state" / "controller.json").write_text(json.dumps({"dispatches": {dispatch: record}}), encoding="utf-8")
    saved = exit_gate.artifact_root
    exit_gate.artifact_root = lambda: root / "qa-factory" / "artifacts"
    filed = task / "work" / "digests" / f"{dispatch}.txt"
    try:
        event = fixture_event()
        agent = exit_gate.role_name(event["agent_type"])
        check_eq("K10: the role name the gate derives", agent, "qa-case-critic")
        err = io.StringIO()
        with redirect_stderr(err):
            errors = exit_gate.digest_errors(agent, ticket, exit_gate.handoff_digest(event))
        child = json.loads(Path(event["agent_transcript_path"]).read_text(encoding="utf-8").splitlines()[0])
        check_eq("K10: the recorded run-12586 event is no refusal through the gate", errors, [])
        check_eq("K10: and nothing is said", err.getvalue(), "")
        check_eq("K10: the filed digest is the handback text", filed.read_text(encoding="utf-8") if filed.is_file() else None,
                 child["message"]["content"][0]["input"]["message"])
        filed.unlink()
        parent_only = {"transcript_path": event["transcript_path"]}
        with redirect_stderr(io.StringIO()):
            errors = exit_gate.digest_errors(agent, ticket, exit_gate.handoff_digest(parent_only))
        check_in("K10 control: the parent-only event is refused", "not the handoff form", " ".join(errors))
        check("K10 control: and not filed", not filed.is_file())
    finally:
        exit_gate.artifact_root = saved
        cleanup(root)


def an_unread_child_transcript_reaches_the_journal_once_per_dispatch():
    """K11 (Q2, FR-59): stderr at exit 0 reaches nobody; the unknown is a `hook_signal` of the project journal, once."""
    root = temp_project("hf46-k11-")
    use_project(root)
    try:
        event = {"session_id": "k11-" + root.name, "agent_transcript_path": str(root / "gone.jsonl"),
                 "transcript_path": str(root / "parent.jsonl")}
        for _ in range(2):
            with redirect_stderr(io.StringIO()):
                check_eq("K11: no digest, no fall-through", exit_gate.handoff_digest(event), "")
        lines = [json.loads(l) for path in root.rglob("journal.jsonl") for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        signals = [l for l in lines if l.get("event") == "hook_signal" and l.get("kind") == "gate_unreadable"]
        check_eq("K11: exactly one signal for the dispatch, though the gate read it twice", len(signals), 1)
        check_in("K11: it names the cause", "could not be read", signals[0]["notes"] if signals else "")
        other = dict(event, agent_transcript_path=str(root / "gone-too.jsonl"))
        with redirect_stderr(io.StringIO()):
            exit_gate.handoff_digest(other)
        lines = [json.loads(l) for path in root.rglob("journal.jsonl") for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        check_eq("K11: another dispatch gets its own signal",
                 len([l for l in lines if l.get("kind") == "gate_unreadable"]), 2)
    finally:
        cleanup(root)


def main():
    the_recorded_run_12586_reads_the_roles_own_word()
    the_row_state_reader_takes_the_verdict_words_and_the_recorded_spelling()
    the_old_path_is_unchanged_without_a_child_path()
    an_unreadable_child_file_is_not_judged_and_not_the_parents()
    the_tail_limit_is_400_rows()
    a_halt_is_the_roles_and_the_parents_halt_is_not()
    last_assistant_message_is_read_only_without_a_child_path()
    uncomfortable_inputs_stay_on_the_safe_side()
    a_codex_child_rollout_is_read_by_the_same_path()
    the_recorded_run_goes_through_the_gates_own_composition()
    an_unread_child_transcript_reaches_the_journal_once_per_dispatch()
    finish("exit gate digest source")


if __name__ == "__main__":
    main()
