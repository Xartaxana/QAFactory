#!/usr/bin/env python3
"""HF8-15 (1a): a role that already handed its report back and then ends its turn in plain text is sent back once.

A role resumed by a message answers with the host's handback call; text is not a return and the conductor has nothing to
take. Keys: K3-1 E1/E2/E3 on built transcripts and the recorded run-12586 form as the positive control, K3-2 the
scenario of the finding (handback, user turn, text -> exit 2, then the door: a handback call -> check_passed, and the
host's own record reads RETURNED), K3-3 E4 (unknown is no refusal) and the name of the call as data, K3-4 E5 AT and BEYOND
the tail limit, K3-5 E7/E8, K3-6 the position (`finish` and the driver never see the record), E6 the one-block fuse.
"""
import io
import json
import sys
import time
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import detector_verdict as DV  # noqa: E402
import dispatch_liveness as DL  # noqa: E402
import exit_gate as gate  # noqa: E402
import host_adapter as HA  # noqa: E402
import test_conductor_stop as T  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "run-12586-digest"
HALT = "qa-scout S1 halt · work/source-inventory.json · no diff - give --mr"
TEXT_END = "The review is done; nothing else to add."
LINE = "Your last turn ended in text. A resumed role hands its report back with the host's handback call: call SubagentHandback with your digest line."
_COUNT = [0]


def rows_text_end() -> list:
    """A role resumed after its handback that answered in text."""
    return [T.prompt(), T.call(), T.ack(), T.prompt("Please look at one more case."), T.said(TEXT_END)]


def put(root: Path, rows: list, name: str = "child.jsonl") -> str:
    path = root / name
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return str(path)


def ended(root: Path, rows: list) -> bool:
    forms, _why = HA.report_forms()
    return HA.ended_in_text_after_handback(put(root, rows), forms, gate.DIGEST_TAIL_ROWS)


def records_of(event: dict, running: bool = True) -> list:
    """The records for `event` with the role's dispatch running (the unit rows have no controller of their own) or not."""
    real = gate._live_dispatch
    gate._live_dispatch = lambda agent, task: {"id": "S5-qa-code-critic-1"} if running else None
    try:
        return gate.text_end_after_handback(event, "qa-code-critic", "QA-TE")
    finally:
        gate._live_dispatch = real


def invoke(event: dict, errors=None):
    """`(exit code, stderr)` of the SubagentStop hook for `event`, the gate's other checks answering `errors`."""
    real = gate.all_errors
    gate.all_errors = lambda *a, **k: (list(errors or []), [])
    gate.read_event = lambda: dict(event)
    err = io.StringIO()
    try:
        with redirect_stderr(err):
            try:
                gate.main()
                code = 0
            except SystemExit as exc:
                code = int(exc.code or 0)
    finally:
        gate.all_errors = real
    return code, err.getvalue()


def event_of(path: str, **extra) -> dict:
    _COUNT[0] += 1
    return {"hook_event_name": "SubagentStop", "agent_type": "qa-factory:qa-code-critic", "session_id": "host-" + str(_COUNT[0]),
            "task_id": "QA-TE", "dispatch_id": f"S5-qa-code-critic-{_COUNT[0]}", "completion_attempt": "a1", "input_fingerprint": "f1",
            "agent_transcript_path": path, **extra}


def journal(root: Path) -> list:
    path = root / "qa-factory" / "records" / "journal.jsonl"
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.is_file() else []


def the_form_of_a_text_end():
    """K3-1: E1, E2, E3 on built transcripts; the recorded run as the positive control of the form."""
    root = temp_dir("te-k1-")
    try:
        check_eq("K3-1: a resumed role that answered in text", ended(root, rows_text_end()), True)
        check_eq("K3-1 E1: a fresh role that ended in text, no handback before it", ended(root, [T.prompt(), T.said(TEXT_END)]), False)
        check_eq("K3-1 E1: ...also after working (text, a tool call, text)", ended(root, [
            T.prompt(), T.said("looking"), T.row("assistant", [{"type": "tool_use", "id": "t9", "name": "Read", "input": {}}]),
            T.said(TEXT_END)]), False)
        check_eq("K3-1 E2: a resumed role that handed back again", ended(root, rows_text_end() + [T.call("toolu_h2"), T.ack("toolu_h2")]), False)
        check_eq("K3-1 E3: the call and the text in ONE row is a handback", ended(root, [T.prompt(), T.row("assistant", [
            {"type": "text", "text": "reporting"}, {"type": "tool_use", "id": "t1", "name": T.HANDBACK, "input": {"message": "m"}}])]), False)
        check_eq("K3-1: the handback of a fresh role, nothing after it", ended(root, [T.prompt(), T.call(), T.ack()]), False)
        check_eq("K3-1: a tool call that merely resembles the handback is not one", ended(root, [
            T.prompt(), T.row("assistant", [{"type": "tool_use", "id": "t1", "name": T.HANDBACK + "X", "input": {}}]), T.said(TEXT_END)]), False)
        check_eq("K3-1: a row of thinking only after the text does not make it empty", ended(root, rows_text_end() + [
            T.row("assistant", [{"type": "thinking", "thinking": "hm"}])]), True)
        # the positive control of the FORM: the recorded child of run 12586 ends with its handback and its acknowledgement
        child = (FIXTURE / "subagents" / "agent-a19dac213a6228a50.jsonl").read_text(encoding="utf-8").splitlines()
        forms, _why = HA.report_forms()
        recorded = put(root, child)
        check_eq("K3-1 control: the recorded handback of run 12586 is no text end", HA.ended_in_text_after_handback(recorded, forms, 400), False)
        check_eq("K3-1 control: the same recorded rows, resumed and answered in text, ARE one",
                 ended(root, child + [T.prompt("one more"), T.said(TEXT_END)]), True)
    finally:
        cleanup(root)


def the_scenario_of_the_finding():
    """K3-2: handback, a user turn, text -> exit 2 naming the call; the door; and the host's record of a return."""
    w = T.world("te-k2-", rows_text_end(), task="QA-TE")
    try:
        event = event_of(str(w["child"]))
        code, text = invoke(event)
        check_eq("K3-2: the first stop of a role that ended in text is refused", code, 2)
        check_in("K3-2: the text names the call and the digest line", LINE, text)
        check_eq("K3-2: the journal holds one gate_block", len([x for x in journal(w["root"]) if x["event"] == "gate_block"]), 1)
        forms, _w = HA.report_forms(host="claude")
        receipt = json.loads(HA.Path(next((w["root"] / "qa-factory" / "state" / "host-dispatches").glob("*.json"))).read_text(encoding="utf-8"))
        limits = DL.thresholds(w["root"])
        check_eq("K3-2: before the door the host's record does not say the role returned", DL.claude_stop(w["root"], receipt, time.time(), limits), None)
        # the door: the role calls the handback tool
        with w["child"].open("a", encoding="utf-8") as handle:
            handle.write(T.call("toolu_h2", "qa-code-critic S5 done again") + "\n" + T.ack("toolu_h2") + "\n")
        code, text = invoke(dict(event, stop_hook_active=True))
        check_eq("K3-2: the re-entry after the door is released", code, 0)
        state = json.loads((w["root"] / "qa-factory" / "state" / ".exit_gate_blocks.json").read_text(encoding="utf-8"))
        check("K3-2: ...and recorded as passed", any(r.get("dispatch") == event["dispatch_id"] and r.get("status") == "check_passed"
                                                    for r in state.values()), str(state))
        verdict = DL.claude_stop(w["root"], receipt, time.time(), limits)
        check_eq("K3-2: after the door dispatch_liveness answers RETURNED", (verdict or {}).get("state"), DL.RETURNED)
        check_eq("K3-2: the gate agrees with itself: the repaired transcript is no text end", len(records_of(event)), 0)
    finally:
        cleanup(w["root"])


def unknown_is_no_refusal():
    """K3-3: E4 parametrized - every input the gate cannot read gives no record - and the name of the call is data."""
    root = temp_dir("te-k3-")
    project = temp_project("te-k3p-")
    use_project(project)
    try:
        good = put(root, rows_text_end())
        check_eq("K3-3 control: the same transcript with a path IS refused", len(records_of({"agent_transcript_path": good})), 1)
        for label, event in (("no path", {}), ("an empty path", {"agent_transcript_path": ""}), ("a blank path", {"agent_transcript_path": "  "}),
                             ("a path that is not text", {"agent_transcript_path": 12}), ("a file that is not there", {"agent_transcript_path": str(root / "gone.jsonl")}),
                             ("a Codex event", {"agent_transcript_path": good, "turn_id": "t-1"}), ("not an event", None)):
            check_eq(f"K3-3 E4: {label}: no record", records_of(event), [])
        garbage = put(root, ["{ nope", "[]", "42", ""], "garbage.jsonl")
        check_eq("K3-3 E4: rows that are not JSON objects: no record", records_of({"agent_transcript_path": garbage}), [])
        # forms that cannot be read: no handback name, so no handback to look for
        saved = HA.REPORT_FORMS_FILE
        try:
            HA.REPORT_FORMS_FILE = root / "no-forms.json"
            check_eq("K3-3 E4: unreadable forms: no record", records_of({"agent_transcript_path": good}), [])
            # the NAME is data: another host's call name, from another forms file, is the one that counts (AR-1)
            other = root / "forms.json"
            other.write_text(json.dumps({"claude": {"handback_tool": "ReturnReport"}}), encoding="utf-8")
            HA.REPORT_FORMS_FILE = other
            check_eq("K3-3: with another name in the data the old name is not a handback", records_of({"agent_transcript_path": good}), [])
            renamed = put(root, [x.replace(T.HANDBACK, "ReturnReport") for x in rows_text_end()], "renamed.jsonl")
            found = records_of({"agent_transcript_path": renamed})
            check_eq("K3-3: ...and the new one is, and the text names IT", (len(found), "call ReturnReport with" in str(found[0]) if found else None), (1, True))
        finally:
            HA.REPORT_FORMS_FILE = saved
        check_eq("K3-3: the file is restored: the shipped name counts again", len(records_of({"agent_transcript_path": good})), 1)
    finally:
        cleanup(root)
        cleanup(project)


def only_a_role_with_a_dispatch_is_refused():
    """K3-7 (F-5): the host sends built-in agents to this hook too; a person's own agent, and a factory role with no
    running dispatch, are never refused. Mutant: drop the `_live_dispatch` condition (this file)."""
    w = T.world("te-k7-", rows_text_end(), task="QA-TE")
    try:
        good = str(w["child"])
        check_eq("K3-7 control: the factory role with its running dispatch IS refused", invoke(event_of(good))[0], 2)
        for agent_type in ("general-purpose", "Explore", "some-user-agent"):
            code, text = invoke(event_of(good, agent_type=agent_type))
            check_eq(f"K3-7 F-5 [{agent_type}] an agent that is not the factory's: exit 0, no refusal", (code, "HANDOFF BLOCKED" in text), (0, False))
        check_eq("K3-7 F-5 unit: no running dispatch, no record", records_of({"agent_transcript_path": good}, running=False), [])
        controller = w["root"] / "qa-factory" / "artifacts" / "QA-TE" / "state" / "controller.json"
        controller.parent.mkdir(parents=True, exist_ok=True)
        controller.write_text(json.dumps({"dispatches": {"S5-qa-code-critic-1": {"id": "S5-qa-code-critic-1", "stage": "S5",
                                                                                 "role": "qa-code-critic", "status": "accepted"}}}), encoding="utf-8")
        code, text = invoke(event_of(good))
        check_eq("K3-7 F-5 the role of an ACCEPTED dispatch (none running): exit 0", (code, "HANDOFF BLOCKED" in text), (0, False))
    finally:
        cleanup(w["root"])


def the_tail_limit_is_the_digests():
    """K3-4: E5 - the earlier handback AT the DIGEST_TAIL_ROWS-th row from the end is seen; one further is not."""
    root = temp_dir("te-k4-")
    try:
        n = gate.DIGEST_TAIL_ROWS
        filler = lambda count: [T.prompt(f"turn {i}") for i in range(count)]          # noqa: E731
        at = [T.call(), T.ack()] + filler(n - 4) + [T.prompt("resume"), T.said(TEXT_END)]
        check_eq("K3-4: the test builds the call exactly the limit from the end", len(at) - at.index(T.call()), n)
        check_eq("K3-4 E5: the handback AT the limit: refused", ended(root, at), True)
        beyond = [T.call(), T.ack()] + filler(n - 3) + [T.prompt("resume"), T.said(TEXT_END)]
        check_eq("K3-4 E5: the handback one row BEYOND the limit: not seen, no record", ended(root, beyond), False)
    finally:
        cleanup(root)


def one_block_for_everything_and_the_halt():
    """K3-5: E7 one block with the real findings too; E8 a halt in text is refused the same way; E6 the fuse."""
    w = T.world("te-k5-", rows_text_end(), task="QA-TE")
    try:
        finding = DV.Record("work/x.json: [c 1] a real finding", script="x.py")
        code, text = invoke(event_of(str(w["child"])), [finding])
        check_eq("K3-5 E7: findings AND a text end: one refusal", code, 2)
        check("K3-5 E7: ...carrying both", "a real finding" in text and LINE in text, text)
        halt_rows = [T.prompt(), T.call(), T.ack(), T.prompt("again"), T.said(HALT)]
        halted = put(w["root"], halt_rows, "halt.jsonl")
        code, text = invoke(event_of(halted))
        check_eq("K3-5 E8: a halt in text after a handback is refused too", code, 2)
        check_in("K3-5 E8: ...with the door (the call carries the digest)", LINE, text)
        check_eq("K3-5 E8: the halt is the role's word, the digest, as it was", gate.handoff_digest({"agent_transcript_path": halted}), HALT)
        # E6: the host's own re-entry is never refused by it, whatever the transcript says
        code, text = invoke(dict(event_of(str(w["child"])), stop_hook_active=True))
        check_eq("K3-5 E6: stop_hook_active: released", code, 0)
        check_not_in("K3-5 E6: ...with no record added", "ended in text", text)
        # E6: the fuse - the SAME input twice: one block, the second released (no loop)
        same = event_of(str(w["child"]))
        first, second = invoke(same)[0], invoke(same)[0]
        check_eq("K3-5 E6: the same input twice: refused once, then released", (first, second), (2, 0))
    finally:
        cleanup(w["root"])


def the_record_never_reaches_finish():
    """K3-6: POSITION - `main` asks, `all_errors` (what `finish` and the driver read) does not."""
    asked = []
    real = gate.text_end_after_handback
    names = ("scoped_errors", "detector_errors", "witness_errors", "grounding_errors", "case_identity_errors", "digest_errors", "required_outputs_errors")
    saved = {name: getattr(gate, name) for name in names}
    gate.text_end_after_handback = lambda *a, **k: asked.append(1) or [DV.Record("never")]
    for name in names:
        setattr(gate, name, lambda *a, **k: [])
    try:
        check_eq("K3-6: `all_errors` with every other check clean answers clean (what `finish` reads)", gate.all_errors("qa-code-critic", "QA-TE", ""), ([], []))
        check_eq("K3-6: ...and never asked the text-end question", asked, [])
    finally:
        gate.text_end_after_handback = real
        for name, value in saved.items():
            setattr(gate, name, value)


def main():
    the_form_of_a_text_end()
    the_scenario_of_the_finding()
    unknown_is_no_refusal()
    only_a_role_with_a_dispatch_is_refused()
    the_tail_limit_is_the_digests()
    one_block_for_everything_and_the_halt()
    the_record_never_reaches_finish()
    finish("exit text end")


if __name__ == "__main__":
    main()
