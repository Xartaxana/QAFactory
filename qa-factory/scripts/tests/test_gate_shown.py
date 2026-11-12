#!/usr/bin/env python3
"""RN1-4: gate A reaches the person as the code's text - the message file and the Stop hook that checks the show.

Keys: K1-K5 the message file `gate_brief.write_gate_message` writes and its record (K2b: a failed message write leaves no
record), S1-S21 the hook `gate_shown.decide` (no open gate is silent, one refusal per message, an unknown refuses once with a
door and is released as `gate_unreadable`, a configured artifact root is found, the driver's mode and Codex are never judged),
H1-H6 `gate_shown.assistant_texts_since` (the turn window and its error direction), F1-F2 the declared fallback when the card
markers are not carried (heading + Answer lines + approval line), T1-T6 the texts that name the file (no "full artifacts", the
carrier agrees with the phase file).
No Cyrillic: the package is English (FR-30).
"""
import io
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import event_store  # noqa: E402
import gate_brief as GB  # noqa: E402
import gate_shown as GS  # noqa: E402
import launch_card  # noqa: E402

PKG = SCRIPTS.parent
SESSION = f"gate-shown-{os.getpid()}"       # per run: `person_signal`'s once-per-session marker lives in the OS temp folder
WRITTEN = datetime(2026, 11, 2, 10, 0, 0, 123000, tzinfo=timezone.utc)
AT = "2026-11-02T10:00:00.123Z"
LATER = "2026-11-02T10:00:05.000Z"
HASHES = {f"Q{n}": f"{n:x}".rjust(64, "a") for n in range(1, 16)}


def question(n: int) -> dict:
    return {"id": f"Q{n}", "severity": "high", "owner_role": "qa-x", "question": f"What about {n}?", "shown_hash": HASHES[f"Q{n}"],
            "readings": [{"reading": "one", "from": "ticket"}, {"reading": "two", "from": "code"}]}


def message(count: int = 2) -> str:
    return GB.render({"task": "QA-SHOWN", "open_questions": [question(n) for n in range(1, count + 1)]})


def row(kind: str, blocks, stamp=LATER, **extra) -> str:
    body = {"type": kind, "message": {"role": kind, "content": blocks}, **extra}
    if stamp is not None:
        body["timestamp"] = stamp
    return json.dumps(body)


def said(text: str, stamp=LATER, **extra) -> str:
    return row("assistant", [{"type": "text", "text": text}], stamp, **extra)


def world(prefix: str, ticket: str, text=None, rows=None, session: str = SESSION, written=WRITTEN, config=None, artifacts="artifacts") -> dict:
    """A project with one story whose gate A message is written by the real writer for `session`, and a transcript of `rows`."""
    root = temp_project(prefix)
    if config:
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        cfg.update(config)
        (root / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    use_project(root)
    task_root = (root / "qa-factory" / artifacts / ticket) if not config else (root / config["artifact_root"] / ticket)
    (task_root / "work").mkdir(parents=True)
    text = message() if text is None else text
    path = GB.write_gate_message(task_root, text, session, now=written)
    transcript = root / "claude" / f"{session}.jsonl"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("\n".join(rows if rows is not None else []) + "\n", encoding="utf-8")
    return {"root": root, "task_root": task_root, "path": path, "text": text, "transcript": transcript, "ticket": ticket,
            "event": {"hook_event_name": "Stop", "session_id": session, "transcript_path": str(transcript), "cwd": str(root)}}


def stop(w: dict, last=None, **extra):
    event = dict(w["event"], **extra)
    if last is not None:
        event["last_assistant_message"] = last
    return GS.decide(event)


def held(w: dict) -> dict:
    path = w["task_root"] / "state" / GS.SHOWN_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def signals(w: dict, kind: str) -> list:
    lines = [json.loads(line) for p in w["root"].rglob("journal.jsonl") for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [x for x in lines if x.get("event") == "hook_signal" and x.get("kind") == kind]


def states(w: dict) -> list:
    return [v.get("state") for v in held(w).values()]


def with_world(prefix, ticket, body, **kwargs):
    w = world(prefix, ticket, **kwargs)
    try:
        body(w)
    finally:
        cleanup(w["root"])


def keys_of_the_file():
    text = message()
    base = temp_dir("gs-k1-")
    try:
        root = base / "QA-SHOWN"
        (root / "work").mkdir(parents=True)
        path = GB.write_gate_message(root, text, "s-1", now=WRITTEN)
        check_eq("K1: the file holds exactly the text main prints", path.read_bytes(), text.encode("utf-8"))
        check_eq("K1: it is where the carrier says", path, root / "work" / GB.GATE_MESSAGE)
        for n in (1, 2):
            check_in(f"K1: the marker of Q{n} is in the file", GB.card_marker(f"Q{n}", HASHES[f"Q{n}"]).strip(), path.read_text(encoding="utf-8"))
            check_in(f"K1: the Answer line of Q{n} is in the file", GB._answer_line(f"Q{n}", "ab").strip(), path.read_text(encoding="utf-8"))
        check_in("K1: the approval line is in the file", GB.gate_a_approval_line(), path.read_text(encoding="utf-8"))
        record = json.loads((root / "state" / GB.GATE_MESSAGE_RECORD).read_text(encoding="utf-8"))
        import hashlib
        check_eq("K2: the record holds the gate, the sha, the session, the path", (record["gate"], record["sha256"], record["session_id"], record["path"]),
                 ("A", hashlib.sha256(path.read_bytes()).hexdigest(), "s-1", "work/gate-a-message.md"))
        check_eq("K2: written_at is UTC with milliseconds", datetime.strptime(record["written_at"], "%Y-%m-%dT%H:%M:%S.%fZ"),
                 datetime(2026, 11, 2, 10, 0, 0, 123000))
        # K5 negative control: the same required/missing pair, a file with one Answer line gone, reports it
        req = GS.required(text)
        check_eq("K5: the whole file misses nothing", GS.missing(req, [text]), {})
        cut = "\n".join(line for line in text.splitlines() if "`Q2: a`" not in line)
        check_eq("K5 negative control: a file without Q2's Answer line reports it", GS.missing(req, [cut]).get("answers", []),
                 [GS._bare(GB._answer_line("Q2", "ab"))])
        # K2b: a failed message write leaves no record (the record is the "asked" fact and goes LAST)
        other = base / "QA-OTHER"
        (other / "work").mkdir(parents=True)
        real = event_store.atomic_text

        def broken(*_a, **_k):
            raise OSError("disk full")
        event_store.atomic_text = broken
        try:
            try:
                GB.write_gate_message(other, text, "s-1", now=WRITTEN)
                failed = False
            except OSError:
                failed = True
        finally:
            event_store.atomic_text = real
        check("K2b: a failed message write raises OSError", failed)
        check("K2b: ...and leaves no record behind", not (other / "state" / GB.GATE_MESSAGE_RECORD).exists())
        # K3: a folder that does not exist: None, nothing created
        gone = base / "NO-SUCH-STORY"
        check_eq("K3: a task root that is not a directory gives None", GB.write_gate_message(gone, text, "s-1"), None)
        check("K3: ...and creates nothing", not gone.exists())
        check_eq("K2: an unbound session is written as an empty string", json.loads(
            (GB.write_gate_message(root, text, None, now=WRITTEN) and (root / "state" / GB.GATE_MESSAGE_RECORD)).read_text(encoding="utf-8"))["session_id"], "")
    finally:
        cleanup(base)


def main_keys():
    """K4: `main` writes the file on the skill path only (negative controls: the driver, `--json`, gate B)."""
    root = temp_project("gs-k4-")
    use_project(root)
    task_root = root / "qa-factory" / "artifacts" / "QA-MAIN"
    (task_root / "work").mkdir(parents=True)
    real = (GB.collect, GB.render_gate_b, sys.argv)
    GB.collect = lambda task: {"task": task, "open_questions": [question(1)]}
    GB.render_gate_b = lambda task: "# Gate B\n"
    held_env = {k: os.environ.pop(k, None) for k in (GB.RUN_MODE_ENV, "CLAUDE_CODE_SESSION_ID")}
    os.environ["CLAUDE_CODE_SESSION_ID"] = SESSION

    def run(*argv, mode=None):
        sys.argv = ["gate_brief.py", "--task", "QA-MAIN", *argv]
        if mode:
            os.environ[GB.RUN_MODE_ENV] = mode
        out, err = io.StringIO(), io.StringIO()
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = GB.main()
        finally:
            os.environ.pop(GB.RUN_MODE_ENV, None)
        return code, out.getvalue(), err.getvalue()
    message_file, record = task_root / "work" / GB.GATE_MESSAGE, task_root / "state" / GB.GATE_MESSAGE_RECORD
    try:
        run("--gate", "A", mode="driver")
        check("K4: in the driver's mode no message file is written", not message_file.exists() and not record.exists())
        run("--gate", "A", "--json")
        check("K4: --json writes none", not message_file.exists() and not record.exists())
        run("--gate", "B")
        check("K4: gate B writes none", not message_file.exists() and not record.exists())
        code, out, _err = run("--gate", "A")
        check_eq("K4 control: gate A on the skill path exits 0", code, 0)
        check_eq("K4 control: ...and writes what it printed", message_file.read_text(encoding="utf-8") + "\n", out)
        check_eq("K4 control: ...with this session in the record", json.loads(record.read_text(encoding="utf-8"))["session_id"], SESSION)
        check_in("K4: the marker of the question is in the file", "<!-- card Q1 ", message_file.read_text(encoding="utf-8"))
        # a story folder that does not exist: nothing is created, the brief is still printed
        sys.argv = ["gate_brief.py", "--task", "QA-NOPE", "--gate", "A"]
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            GB.main()
        check("K4: a typo in --task creates no folder", not (root / "qa-factory" / "artifacts" / "QA-NOPE").exists())
    finally:
        GB.collect, GB.render_gate_b, sys.argv = real
        for k, v in held_env.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)
        cleanup(root)
    check("T6: the receipt list names gate_brief.py (a command that needs its own session id)",
          "gate_brief.py" in json.loads((PKG / "references" / "session-identity.json").read_text(encoding="utf-8"))["receipt_scripts"])


def the_hook_is_silent_without_an_open_gate():
    """S1, S2, S11, S15, E1/E2 (mutants: M4 no sidecar read as open, M7 no session filter, M10 a decided gate not skipped)."""
    root = temp_project("gs-s1-")
    try:
        use_project(root)
        event = {"hook_event_name": "Stop", "session_id": SESSION, "cwd": str(root), "last_assistant_message": "| Q1 | a |"}
        check_eq("S1: no record in the project: silence", GS.decide(event), (0, ""))
    finally:
        cleanup(root)

    def other(w):
        w["event"]["session_id"] = SESSION         # the record is bound to `s-other`; this conductor is another session
        check_eq("S2: a record of another session never refuses this one", stop(w, last="| Q1 | a |"), (0, ""))
        check_eq("S2: ...and writes nothing", held(w), {})
    with_world("gs-s2-", "QA-S2A", other, session="s-other")

    def unbound(w):
        check_eq("S2: a record bound to no session never refuses", stop(w, last="| Q1 | a |"), (0, ""))
    with_world("gs-s2b-", "QA-S2B", unbound, session="")

    def decided(w):
        (w["task_root"] / "state").mkdir(exist_ok=True)
        (w["task_root"] / "state" / "controller.json").write_text(json.dumps({"source_revision": "r1", "decisions": {
            "d1": {"gate": "A", "status": "approved", "source_revision": "r1"}}}), encoding="utf-8")
        check_eq("S11: gate A decided: a retelling turn passes", stop(w, last="| Q1 | a |"), (0, ""))
        (w["task_root"] / "state" / "controller.json").write_text(json.dumps({"source_revision": "r2", "decisions": {
            "d1": {"gate": "A", "status": "approved", "source_revision": "r1"}}}), encoding="utf-8")
        check_eq("S11 control: a decision on an older revision does not decide it", stop(w, last="| Q1 | a |")[0], 2)
    with_world("gs-s11-", "QA-S11", decided)

    def unreadable_controller(w):
        (w["task_root"] / "state").mkdir(exist_ok=True)
        (w["task_root"] / "state" / "controller.json").write_text("{not json", encoding="utf-8")
        check_eq("S12: an unreadable controller.json is read as OPEN: the retelling is refused", stop(w, last="| Q1 | a |")[0], 2)
    with_world("gs-s12-", "QA-S12", unreadable_controller)

    def modes(w):
        os.environ[GS.RUN_MODE_ENV] = GS.DRIVER_MODE
        try:
            check_eq("S15: the driver's mode is never judged", stop(w, last="| Q1 | a |"), (0, ""))
        finally:
            os.environ.pop(GS.RUN_MODE_ENV, None)
        check_eq("S15 control: the same Stop outside the driver is refused", stop(w, last="| Q1 | a |")[0], 2)
        shown = GS.decide(dict(w["event"], turn_id="t-1", last_assistant_message="| Q1 | a |"))
        check_eq("S15: a Codex event is not judged", shown, (0, ""))
        check_eq("S15: a non-object event is not judged", GS.decide(None), (0, ""))
    with_world("gs-s15-", "QA-S15", modes)
    check_eq("S15: the name of the driver's variable is the driver's own", GS.RUN_MODE_ENV, launch_card.RUN_MODE_ENV)
    check_eq("S15: the record's name is the writer's own", GS.GATE_MESSAGE_RECORD, GB.GATE_MESSAGE_RECORD)


def the_hook_judges_the_turn():
    """S3-S10, S13, S16-S19 (mutants: M1 answers ignored, M3 no time bound, M5 no fuse, M6 id only, M9 `>` kept)."""
    text = message()

    def retold(w):
        code, said_text = stop(w, last="| Q1 | a |\n| Q2 | b |")
        check_eq("S3: a letters table with no card is refused", code, 2)
        check_in("S3: the text names Q1", "Q1", said_text)
        check_in("S3: ...and Q2", "Q2", said_text)
        check_in("S3: ...and the message file's path", str(w["path"].resolve()), said_text)
        check_in("S3: ...and the move", "print it as it is", said_text)
        check_in("S3: ...and the fuse", "refuses once per message", said_text)
        check_eq("S10: the first refusal is recorded before it is made", states(w), ["refused"])
        check_eq("S10: the SECOND Stop for the same message is released", stop(w, last="| Q1 | a |"), (0, ""))
        check_eq("S10: ...with one gate_not_shown signal", len(signals(w, "gate_not_shown")), 1)
        check_eq("S10: ...and the record says released", states(w), ["released"])
        check_eq("S10: a THIRD Stop passes", stop(w, last="again"), (0, ""))
        check_eq("S10: ...and files no second signal", len(signals(w, "gate_not_shown")), 1)
    with_world("gs-s3-", "QA-S3", retold, rows=[said("| Q1 | a |\n| Q2 | b |")])

    def whole(w):
        check_eq("S4: the file printed whole, then a paragraph: passes", stop(w, last="Q1: a, because it is the safe one."), (0, ""))
        check_eq("S4: ...and the record says shown", states(w), ["shown"])
        check_eq("S4: ...and a later Stop is still silent", stop(w, last="x"), (0, ""))
    with_world("gs-s4-", "QA-S4", whole, rows=[said(text + "\n\nQ1: a, because it is the safe one.")])

    def fenced(w):
        check_eq("S4b: the file printed inside a code fence passes", stop(w, last="done"), (0, ""))
    with_world("gs-s4b-", "QA-S4B", fenced, rows=[said("```\n" + text + "\n```\nmy words")])

    def quoted(w):
        check_eq("S5: the file printed inside a blockquote passes", stop(w, last="done"), (0, ""))
    with_world("gs-s5-", "QA-S5", quoted, rows=[said("\n".join("> " + line for line in text.splitlines()))])

    def bulleted(w):
        check_eq("S5b: every line of the file behind a bullet passes", stop(w, last="done"), (0, ""))
    with_world("gs-s5b-", "QA-S5B", bulleted, rows=[said("\n".join(line.strip() if line.strip().startswith("- ") else "- " + line.strip()
                                                                       for line in text.splitlines() if line.strip()))])

    other_hash = text.replace(HASHES["Q1"], "f" * 64)

    def wrong_hash(w):
        code, said_text = stop(w, last="done")
        check_eq("S6: a marker of the right id with ANOTHER fingerprint is refused", code, 2)
        check_in("S6: ...and names Q1", "the cards of Q1", said_text)
        check_not_in("S6: ...and not Q2, whose marker is right", "cards of Q1, Q2", said_text)
    with_world("gs-s6-", "QA-S6", wrong_hash, rows=[said(other_hash)])

    def only_in_tool_output(w):
        check_eq("S7: the message seen only in a tool_result is refused", stop(w, last="Here it is.")[0], 2)
    result = row("user", [{"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": text}]}])
    with_world("gs-s7-", "QA-S7", only_in_tool_output, rows=[result, said("Here it is.")])

    def too_early(w):
        check_eq("S8: a print one second BEFORE the message was written is refused", stop(w)[0], 2)
    with_world("gs-s8-", "QA-S8", too_early, rows=[said(text, "2026-11-02T09:59:59.900Z")])

    def same_second(w):
        check_eq("S8: the same print at the second the message was written passes", stop(w), (0, ""))
    with_world("gs-s8b-", "QA-S8B", same_second, rows=[said(text, "2026-11-02T10:00:00.900Z")])

    lines = text.splitlines()
    first, second = "\n".join(lines[:12]), "\n".join(lines[12:])

    def spread(w):
        check_eq("S9: the cards spread over two rows of the turn, the last message only the second part: passes", stop(w, last=second), (0, ""))
    call = row("assistant", [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "x"}}])
    with_world("gs-s9-", "QA-S9", spread, rows=[said(first), call, said(second)])

    def no_answers(w):
        code, said_text = stop(w, last="done")
        check_eq("S3b: the markers kept and the Answer lines dropped is refused", code, 2)
        check_in("S3b: ...and names the Answer lines", "the Answer lines of Q1, Q2", said_text)
        check_not_in("S3b: ...and not the cards", "the cards of", said_text)
    with_world("gs-s3b-", "QA-S3B", no_answers, rows=[said("\n".join(line for line in text.splitlines() if "Answer:" not in line))])

    def glued(w):
        check_eq("S17: the whole print and a glued recommendation after it: passes (the hook reads no words)",
                 stop(w, last="Q4, Q7, Q8, Q9: not needed - all minor"), (0, ""))
    with_world("gs-s17-", "QA-S17", glued, rows=[said(text + "\nQ4, Q7, Q8, Q9: not needed - all minor")])

    def unreadable_turn(w):
        code, said_text = stop(w, last="done")
        check_eq("S18: an unreadable transcript, a last message without the cards: refused", code, 2)
        check_in("S18: ...and the text says the turn could not be read", "the rest of your turn could not be read", said_text)
        w["event"]["last_assistant_message"] = text
        check_eq("S18: the last message with every card passes without the transcript", stop(w, last=text), (0, ""))
    w = world("gs-s18-", "QA-S18")
    try:
        w["event"]["transcript_path"] = str(w["root"] / "no-such-transcript.jsonl")
        unreadable_turn(w)
    finally:
        cleanup(w["root"])

    def unwritable(w):
        (w["task_root"] / "state" / GS.SHOWN_FILE).mkdir(parents=True)
        check_eq("S19: the hook's record cannot be written: no refusal", stop(w, last="| Q1 | a |"), (0, ""))
        check_eq("S19: ...and one gate_unreadable signal", len(signals(w, "gate_unreadable")), 1)
    with_world("gs-s19-", "QA-S19", unwritable)


def the_message_file_goes_missing():
    """S13 (E4/E6), m-2: an unknown refuses once with a door and is released as gate_unreadable, never as a leak."""
    def gone(w):
        w["path"].unlink()
        code, said_text = stop(w, last="| Q1 | a |")
        check_eq("S13: the message file gone after the record: refused", code, 2)
        check_in("S13: the text is U: the file is missing or changed", "missing or changed since it was written at " + AT, said_text)
        check_in("S13: ...and its door is the command that writes it", "gate_brief.py --task QA-S13 --gate A", said_text)
        check_eq("S13: the second Stop passes", stop(w, last="| Q1 | a |"), (0, ""))
        check_eq("S13: ...filed as gate_unreadable (an unknown, not a leak)", len(signals(w, "gate_unreadable")), 1)
        check_eq("S13: ...and not as gate_not_shown", len(signals(w, "gate_not_shown")), 0)
    with_world("gs-s13-", "QA-S13", gone)

    def changed(w):
        w["path"].write_text("# something else\n", encoding="utf-8")
        check_eq("S13b: bytes changed after the record: refused (U)", stop(w, last="| Q1 | a |")[0], 2)
    with_world("gs-s13b-", "QA-S13B", changed)

    def restored(w):
        w["path"].write_text("# something else\n", encoding="utf-8")
        w["path"].write_bytes(w["text"].encode("utf-8"))
        code, said_text = stop(w, last="| Q1 | a |")
        check_eq("S13b: the bytes back as measured: the turn is judged on its words", code, 2)
        check_in("S13b: ...so it is the refusal M, not the unknown", "does not carry", said_text)
    with_world("gs-s13b2-", "QA-S13B2", restored)

    def unknown_then_leak(w):
        saved = w["path"].read_bytes()
        w["path"].unlink()
        check_eq("S13d: Stop 1 on a missing file: refused (unreadable)", stop(w, last="| Q1 | a |")[0], 2)
        w["path"].write_bytes(saved)
        check_eq("S13d: Stop 2, the file back, the turn read and lacking: released", stop(w, last="| Q1 | a |"), (0, ""))
        check_eq("S13d: ...filed as gate_not_shown (the current judgement, not the first reason)", len(signals(w, "gate_not_shown")), 1)
        check_eq("S13d: ...and not as gate_unreadable", len(signals(w, "gate_unreadable")), 0)
    with_world("gs-s13d-", "QA-S13D", unknown_then_leak)

    def escaping(w):
        record = w["task_root"] / "state" / GB.GATE_MESSAGE_RECORD
        data = json.loads(record.read_text(encoding="utf-8"))
        data["path"] = "../../../outside.md"
        record.write_text(json.dumps(data), encoding="utf-8")
        check_in("S13c: a record whose path leaves the story folder is an unknown", "missing or changed", stop(w, last="x")[1])
    with_world("gs-s13c-", "QA-S13C", escaping)


def the_required_set():
    """S14 (E2, F6 (a)), F1-F2 (the declared fallback: markers not carried), S16 (the one limit, ten ids)."""
    empty = GB.render({"task": "QA-S14"})

    def zero(w):
        check_eq("S14: nothing but the approval line is required", {k: bool(v) for k, v in GS.required(w["text"]).items()},
                 {"cards": False, "headings": False, "answers": False, "approval": True})
        code, said_text = stop(w, last="my own table")
        check_eq("S14: a turn without the approval line is refused", code, 2)
        check_in("S14: ...and names it", "the line naming the documents to approve", said_text)
    with_world("gs-s14-", "QA-S14", zero, text=empty, rows=[said("my own table")])

    def with_line(w):
        check_eq("S14: a turn with the approval line passes", stop(w, last="ok"), (0, ""))
    with_world("gs-s14b-", "QA-S14B", with_line, text=empty, rows=[said(empty)])

    nothing = "# Gate A\n\nplain text with no card, no answer and no approval line\n"
    with_world("gs-s14c-", "QA-S14C", lambda w: check_eq("S14c: a packet requiring nothing is shown at once", (stop(w, last="x"), states(w)),
                                                       ((0, ""), ["shown"])), text=nothing)

    text = message()
    no_markers = "\n".join(line for line in text.splitlines() if "<!-- card" not in line)

    def fallback(w):
        check_eq("F1: markers not carried, the headings, Answer lines and approval line carried: passes", stop(w, last="x"), (0, ""))
    with_world("gs-f1-", "QA-F1", fallback, rows=[said(no_markers)])

    def fallback_cut(w):
        code, said_text = stop(w, last="x")
        check_eq("F2: markers and Q1's heading not carried: refused", code, 2)
        check_in("F2: ...naming the card of Q1", "the cards of Q1", said_text)
        check_not_in("F2: ...and not Q2, whose heading is carried", "cards of Q1, Q2", said_text)
    with_world("gs-f2-", "QA-F2", fallback_cut, rows=[said("\n".join(line for line in no_markers.splitlines() if not line.lstrip().startswith("- **Q1**")))])

    big = message(11)

    def eleven(w):
        _code, said_text = stop(w, last="x")
        check_in("S16: 11 missing: the first ten are named", "Q1, Q2, Q3, Q4, Q5, Q6, Q7, Q8, Q9, Q10 and 1 more", said_text)
        check_not_in("S16: ...and the eleventh is not", "Q11", said_text)
    with_world("gs-s16a-", "QA-S16A", eleven, text=big, rows=[said("x")])

    def ten(w):
        _code, said_text = stop(w, last="x")
        check_in("S16: 10 missing: all ten are named", "Q1, Q2, Q3, Q4, Q5, Q6, Q7, Q8, Q9, Q10;", said_text)
        check_not_in("S16: ...with no `and N more`", " more", said_text)
    with_world("gs-s16b-", "QA-S16B", ten, text=message(10), rows=[said("x")])


def a_configured_artifact_root_is_found():
    """S21 (B-1): the record is found where the writer wrote it, through `hooklib.artifact_root`; the hook has no literal path."""
    def configured(w):
        check("S21: the story is under the configured root", "test-artifacts" in str(w["task_root"]))
        check("S21: ...and not under the default one", not (w["root"] / "qa-factory" / "artifacts").exists())
        check_eq("S21: a retelling turn is refused", stop(w, last="| Q1 | a |")[0], 2)
    with_world("gs-s21-", "QA-S21", configured, config={"artifact_root": "test-artifacts"})


def a_crash_is_exit_zero():
    """S20: an exception inside decide is exit 0, nothing on stderr to block on, and one gate_unreadable signal."""
    w = world("gs-s20-", "QA-S20")
    real = GS._open_records
    try:
        def crash(*_a, **_k):
            raise RuntimeError("the reader broke")
        GS._open_records = crash
        stdin, err = sys.stdin, io.StringIO()
        sys.stdin = io.StringIO(json.dumps(dict(w["event"], last_assistant_message="x")))
        try:
            with redirect_stderr(err):
                try:
                    GS.main()
                    code = 0
                except SystemExit as exc:
                    code = int(exc.code or 0)
        finally:
            sys.stdin = stdin
        check_eq("S20: a crash is exit 0", code, 0)
        check_eq("S20: ...with nothing on stderr to block on", err.getvalue(), "")
        found = signals(w, "gate_unreadable")
        check("S20: ...and ONE gate_unreadable signal names the hook", len(found) == 1 and "gate_shown: unreadable" in found[0]["notes"], str(found))
    finally:
        GS._open_records = real
        cleanup(w["root"])


def the_transcript_reader():
    """H1-H6 (error direction: toward MORE text of the turn, never less)."""
    base = temp_dir("gs-h-")
    try:
        path = base / "t.jsonl"
        rows = [
            said("no stamp", None),
            said("bad stamp", "yesterday"),
            said("sidechain", LATER, isSidechain=True),
            row("user", [{"type": "tool_result", "tool_use_id": "t", "content": [{"type": "text", "text": "tool output"}]}]),
            row("assistant", [{"type": "tool_use", "id": "t", "name": "Bash", "input": {"command": "tool input"}}]),
            said("on the second", "2026-11-02T10:00:00.999Z"),
            said("one second early", "2026-11-02T09:59:59.999Z"),
            json.dumps({"type": "assistant", "timestamp": LATER, "message": {"role": "assistant", "content": "plain string content"}}),
            "this line is not json",
        ]
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        got = GS.assistant_texts_since(str(path), AT)
        check_eq("H1-H5: the texts of the turn, in order", got, ["no stamp", "bad stamp", "on the second", "plain string content"])
        check_not_in("H2: a tool_result is not the turn's text", "tool output", " ".join(got))
        check_not_in("H2: a tool_use input is not the turn's text", "tool input", " ".join(got))
        check_not_in("H3: a sidechain row is not the turn's text", "sidechain", " ".join(got))
        check_not_in("H4: a row one second before the bound is not counted", "one second early", " ".join(got))
        check_in("H4: a row at the bound's second is", "on the second", " ".join(got))
        check_in("H5 (m-1): a string content has no block type and is text", "plain string content", " ".join(got))
        check_eq("H6: an unreadable path gives None", GS.assistant_texts_since(str(base / "none.jsonl"), AT), None)
        check_eq("H6: a path that is not a string gives None", (GS.assistant_texts_since(None, AT), GS.assistant_texts_since("  ", AT)), (None, None))
        check_eq("H6: a bound that is not a stamp counts every row", len(GS.assistant_texts_since(str(path), None)), 5)
    finally:
        cleanup(base)


def the_texts_name_the_file():
    """T4-T5: the gate message file is named in s4.md as the carrier writes it (the role-text rules of the skill and s8.md are rows
    of design/role-rules.json)."""
    s4 = (PKG / "skills" / "qa-story" / "phases" / "s4.md").read_text(encoding="utf-8")
    check_in("T4: s4.md names the message file", "work/gate-a-message.md", s4)
    check_eq("T5: the literal in s4.md is the carrier's one name (two places, one name)", GB.GATE_MESSAGE, "gate-a-message.md")
    check_in("T5: ...in s4.md", f"work/{GB.GATE_MESSAGE}", s4)
    check_in("T5: ...and the asked-file path of the judge is the file the code writes", f"--asked-file <TASK_ROOT>/work/{GB.GATE_MESSAGE}", s4)


def the_literal_script_ends_clean():
    """The script as the launcher runs it: garbage and empty stdin are exit 0 and nothing to block on."""
    import subprocess
    for payload in ("", "   \n", "not json", "[]"):
        p = subprocess.run([sys.executable, "-B", str(SCRIPTS / "gate_shown.py")], input=payload, capture_output=True, text=True,
                           encoding="utf-8", timeout=60, env={k: v for k, v in os.environ.items() if k != GS.RUN_MODE_ENV})
        check_eq(f"literal script, stdin {payload!r}: exit 0", p.returncode, 0)
        check_not_in(f"literal script, stdin {payload!r}: nothing blocks", "Gate A of", p.stderr)
    w = world("gs-lit-", "QA-LIT", rows=[said("| Q1 | a |")])
    try:
        env = {k: v for k, v in os.environ.items() if k != GS.RUN_MODE_ENV}
        env["CLAUDE_PROJECT_DIR"] = str(w["root"])
        event = dict(w["event"], last_assistant_message="| Q1 | a |")
        p = subprocess.run([sys.executable, "-B", str(SCRIPTS / "gate_shown.py")], input=json.dumps(event), capture_output=True, text=True,
                           encoding="utf-8", timeout=60, env=env, cwd=str(w["root"]))
        check_eq("the literal script on a retelling turn: exit 2", p.returncode, 2)
        check_in("...with the refusal on stderr", "Gate A of QA-LIT is open", p.stderr)
    finally:
        cleanup(w["root"])


def main():
    os.environ.pop(GS.RUN_MODE_ENV, None)
    keys_of_the_file()
    main_keys()
    the_hook_is_silent_without_an_open_gate()
    the_hook_judges_the_turn()
    the_message_file_goes_missing()
    the_required_set()
    a_configured_artifact_root_is_found()
    a_crash_is_exit_zero()
    the_transcript_reader()
    the_texts_name_the_file()
    the_literal_script_ends_clean()
    finish("gate shown")


if __name__ == "__main__":
    main()
