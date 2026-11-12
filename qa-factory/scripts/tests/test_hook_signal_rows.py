#!/usr/bin/env python3
"""RH1-5 fix round (AR-22, AR-18): the readers and the writer around `hook_signal`.
N2: audit A6 knows the event `hook_signal` (a journal that holds a `person_signal` line is not "unknown event"; control: a
made-up event still is). N3: a gate receipt `unreadable` gives a `subagent_stop` line that is NOT `completed` (control: no
receipt is `completed`). N8: `exit_gate.journal_gate`, `hooklib.person_signal` and `subagent_journal` write the journal through
ONE function, `hooklib.append_journal_line` (the stamp, the seeded flag, the path), and the line it writes keeps the shape."""
import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, cleanup, finish, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import audit_factory as AF  # noqa: E402
import exit_gate as EG  # noqa: E402
import hooklib  # noqa: E402
import runtime_paths as RP  # noqa: E402
import subagent_journal as SJ  # noqa: E402


def journal_of(root: Path) -> Path:
    return RP.configured(root, hooklib.load_config().get("journal_path"), "journal.jsonl")


def a6_output() -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        AF.a6_journal_format()
    return out.getvalue()


def stop_line(root: Path, receipt: dict) -> dict:
    """The `subagent_stop` line the hook writes for a role whose gate receipt is `receipt`."""
    saved = {k: getattr(SJ, k) for k in ("read_event", "subagent_type", "_identity", "_existing", "_story_dispatch",
                                         "story_step_receipt", "record_return")}
    SJ.read_event = lambda: {"session_id": "s", "agent_type": "qa-automator"}
    SJ.subagent_type = lambda e: "qa-automator"
    SJ._identity = lambda e, a: ("key", {"task": "T-1", "dispatch": "d1", "attempt": 1, "hook": "h", "input_fingerprint": "f"})
    SJ._existing = lambda k: dict(receipt)
    SJ._story_dispatch = lambda e, s: None
    SJ.story_step_receipt = lambda e, s, d: ""
    SJ.record_return = lambda *a, **k: None
    try:
        try:
            SJ.main()
        except SystemExit:
            pass
    finally:
        for k, v in saved.items():
            setattr(SJ, k, v)
    lines = [json.loads(x) for x in journal_of(Path(hooklib.project_root())).read_text(encoding="utf-8").splitlines() if x]
    return [r for r in lines if r.get("event") == "subagent_stop"][-1]


def main() -> None:
    root = temp_project("qa-hook-signal-rows-")
    try:
        use_project(root)
        # N2: A6 reads the vocabulary of the journal; `hook_signal` is in it
        check_eq("N2: person_signal lands a line", hooklib.person_signal({"session_id": "s"}, "guard_crashed", "the guard crashed", task="T-1"), True)
        seen = a6_output()
        check("N2: A6 over a journal holding a hook_signal line reports no `unknown event`", "unknown event" not in seen, seen)
        with journal_of(root).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"ts": "2026-10-28T10:00:00+00:00", "event": "made_up_event", "agent": "x", "notes": "n"}) + "\n")
        seen = a6_output()
        check_in("N2 control: a made-up event is still `unknown event`", "unknown event 'made_up_event'", seen)
        check("N2 control: ...and the hook_signal line is not the one named", "unknown event 'hook_signal'" not in seen, seen)

        # N3: the receipt `unreadable` is not a completion
        line = stop_line(root, {"status": "unreadable"})
        check_eq("N3: a receipt `unreadable` gives `incomplete`, not `completed`", (line["status"], line.get("gate_receipt")), ("incomplete", "key"))
        check_eq("N3 control: a receipt `check_passed` is `completed`", stop_line(root, {"status": "check_passed"})["status"], "completed")
        check_eq("N3 control: no receipt is `completed`", stop_line(root, {})["status"], "completed")

        # N8: ONE writer
        calls = []
        real = hooklib.append_journal_line
        hooklib.append_journal_line = lambda event, rec: calls.append(dict(rec))
        try:
            EG.journal_gate("s1", "gate_block", "n", {"task": "T-1", "dispatch": "d", "attempt": 1, "hook": "h", "input_fingerprint": "f"})
            hooklib.person_signal({"session_id": "s1"}, "config", "a note", task="T-1")
        finally:
            hooklib.append_journal_line = real
        check_eq("N8: journal_gate and person_signal both write through append_journal_line", [c["event"] for c in calls], ["gate_block", "hook_signal"])
        check_eq("N8: ...and neither stamps `ts` itself (the one writer does)", ["ts" in c for c in calls], [False, False])
        landed = [json.loads(x) for x in journal_of(root).read_text(encoding="utf-8").splitlines() if x]
        stamped = [r for r in landed if r.get("event") == "hook_signal"][0]
        check("N8: the written line has the writer's stamp: UTC ISO with +00:00",
              stamped["ts"].endswith("+00:00") and "T" in stamped["ts"], str(stamped))
        EG.journal_gate("s1", "gate_block", "n", None)
        last = json.loads(journal_of(root).read_text(encoding="utf-8").splitlines()[-1])
        check_eq("N8: journal_gate's line keeps its shape", (last["event"], last["agent"], last["session"], last["notes"]), ("gate_block", "exit_gate", "s1", "n"))
    finally:
        cleanup(root)
    finish("test_hook_signal_rows")


if __name__ == "__main__":
    main()
