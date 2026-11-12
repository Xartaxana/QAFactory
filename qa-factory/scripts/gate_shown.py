#!/usr/bin/env python3
"""RN1-4: the Stop hook that checks gate A reached the person as the CODE's text (inert until `hooks/hooks.json` names it).

LOCAL-1 showed the conductor retelling gate A: it read the code's brief and composed its own table of the questions, with
letters the person could not answer from and no card markers. The text the person reads at gate A is the file
`gate_brief.py --gate A` writes (`work/gate-a-message.md`), and the conductor prints it whole. This hook asks ONE question
when the conductor's session ends a turn: "gate A of this session's story is open and its message was written - does the
turn since then carry the code's lines?" - and when it does not, it refuses the end of the turn ONCE per message and names
the move (print the file as it is).

What it reads is structure the code wrote, never the conductor's words (FR-12): every card marker `gate_brief.card_marker`
built (id and 64-hex fingerprint), every `Answer:` line, and the approval line `gate_brief.gate_a_approval_line`. It compares
the conductor's lines for EQUALITY with these. A card whose marker is absent from the turn is still shown when its heading
line is carried verbatim (the declared fallback if the host shows hidden marker lines to a person): a marker of the right
id with ANOTHER fingerprint never counts. A whole print followed by prose of the conductor's own passes: the hook refuses only
the ABSENCE of the code's lines (the text rule of `phases/s4.md` carries the rest).

POSITION of the checks, cheapest first (AR-12: this runs at every Stop of every session): the driver's mode, the host and
the session answer before anything is read; then one glob of the project's story folders for the record of the message;
`gate_brief` is imported, the message file and a transcript are read ONLY for a record that is this session's and open.
INVARIANTS: a turn with no open gate of THIS session is never refused (another session's record, an unbound record with
`session_id` "", a decided gate: silence, FR-2); at most ONE refusal per (session, message bytes) - the key lives in
`state/gate-shown.json`, written before the refusal, so the second end of the turn always passes (FR-57); an unknown (the
message file gone or changed, the turn unreadable, the controller's record unreadable) is never "shown": it refuses once with a door
(FR-59), and its release is filed as `gate_unreadable`, not as a leak (FR-41); the hook's own crash or an unwritable record is
exit 0 and one `gate_unreadable` signal. The driver (`story_run.py`, `QA_FACTORY_RUN_MODE=driver`) never writes the message
file and shows its own packet (`Driver.gate`): it is never judged here.

Codex: not registered (`hooks/codex.json`); gate B: its message has no file and no markers yet (queued).
"""
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# NAMED here, not imported (`gate_brief` is a large module and this runs at every Stop, AR-12); `test_gate_shown.py` pins that
# each equals its definition (`launch_card.RUN_MODE_ENV`, `gate_brief.GATE_MESSAGE_RECORD`).
RUN_MODE_ENV = "QA_FACTORY_RUN_MODE"
DRIVER_MODE = "driver"
GATE_MESSAGE_RECORD = "gate-message.json"
SHOWN_FILE = "gate-shown.json"
MISSING_NAMED = 10          # ids named in one refusal; the rest are `and N more`

_BULLETS = ("- ", "* ", "\u2022 ")
_STAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d")
_ID_IN_ANSWER = re.compile(r"`([^`:\s]+):")


def _bare(line) -> str:
    """A line without the markdown that wraps a reprint: strip, every leading `>` (a blockquote) with the whitespace after it,
    ONE list bullet, strip again. Markdown syntax, not project variety (FR-13 n/a)."""
    text = str(line).strip()
    while text.startswith(">"):
        text = text[1:].lstrip()
    for bullet in _BULLETS:
        if text.startswith(bullet):
            text = text[len(bullet):]
            break
    return text.strip()


def _bare_lines(texts) -> list:
    return [_bare(line) for text in texts for line in str(text).splitlines()]


def required(text) -> dict:
    """From the MESSAGE FILE text: `cards` = `[(id, hash)]` in file order (`gate_brief.shown_hashes` over each line),
    `headings` = `{id: the bare heading line of that card}`, `answers` = the bare lines that start with `Answer:`, `approval` =
    `gate_brief.gate_a_approval_line()` when that exact bare line is in the file, else None."""
    import gate_brief
    lines = _bare_lines([text])
    cards, seen = [], set()
    for line in lines:
        for pair in gate_brief.shown_hashes(line).items():
            if pair not in seen:
                seen.add(pair)
                cards.append(pair)
    headings = {}
    for qid, _hash in cards:
        head = next((line for line in lines if line.startswith(f"**{qid}**")), None)
        if head:
            headings[qid] = head
    approval = gate_brief.gate_a_approval_line()
    return {"cards": cards, "headings": headings, "answers": [line for line in lines if line.startswith("Answer:")],
            "approval": approval if approval in lines else None}


def missing(req, texts) -> dict:
    """What of `req` the turn's `texts` do not carry; `{}` when nothing is missing. `cards`: the pairs whose marker (same id AND
    same fingerprint) is in no line - a card with no marker of its id at all is still carried when its heading is; `answers` and
    `approval`: required lines equal to no bare line. A fingerprint other than the file's never counts (a card shown from
    other bytes)."""
    import gate_brief
    lines = _bare_lines(texts)
    have = set(lines)
    shown = set()
    for line in lines:
        shown.update(gate_brief.shown_hashes(line).items())
    shown_ids = {qid for qid, _hash in shown}
    out = {}
    cards = [(qid, hash_) for qid, hash_ in req.get("cards") or []
             if (qid, hash_) not in shown
             and not (qid not in shown_ids and req.get("headings", {}).get(qid) in have)]
    if cards:
        out["cards"] = cards
    answers = [line for line in req.get("answers") or [] if line not in have]
    if answers:
        out["answers"] = answers
    if req.get("approval") and req["approval"] not in have:
        out["approval"] = req["approval"]
    return out


def assistant_texts_since(path, since_iso):
    """The text of every TEXT block of the assistant rows of the transcript at `path` stamped at or after `since_iso` (whole
    seconds, UTC), as a list; None when `path` is not a non-empty string or cannot be read. A row with no parseable
    `timestamp` is counted; a sidechain row is not; a `tool_use` input and a `tool_result` are never text of the turn (the
    person does not read tool output). A block with no `type` is text (a string content). The error goes toward MORE text,
    never less of the turn (it feeds a refusal). The ONE reader of a row's texts is `host_adapter.assistant_row_texts`
    (AR-13)."""
    import host_adapter
    if not isinstance(path, str) or not path.strip():
        return None
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    bound = str(since_iso or "")[:19]
    texts = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get("isSidechain"):
            continue
        stamp = row.get("timestamp")
        if isinstance(stamp, str) and _STAMP.match(stamp) and stamp[:19] < bound:
            continue
        texts.extend(text for text in host_adapter.assistant_row_texts(row) if text.strip())
    return texts


def _ids(items) -> str:
    """The ids, the first `MISSING_NAMED`, then `and N more`."""
    ids = list(dict.fromkeys(items))
    named = ", ".join(ids[:MISSING_NAMED])
    return named + (f" and {len(ids) - MISSING_NAMED} more" if len(ids) > MISSING_NAMED else "")


def _what(miss) -> str:
    parts = []
    if miss.get("cards"):
        parts.append("the cards of " + _ids(qid for qid, _hash in miss["cards"]))
    if miss.get("answers"):
        parts.append("the Answer lines of " + _ids((_ID_IN_ANSWER.search(line) or [None, "a question"])[1] for line in miss["answers"]))
    if miss.get("approval"):
        parts.append("the line naming the documents to approve")
    return "; ".join(parts)


def refusal_text(task, path, miss, unread) -> str:
    carry = ("your last message does not carry (the rest of your turn could not be read)" if unread
             else "your turn does not carry")
    return (f"Gate A of {task} is open and its message has not reached the person: {carry} {_what(miss)} of {path}. "
            "Expected: that file printed whole as the start of your message, its hidden <!-- card --> lines included; your own "
            "words after it, at most one line per question. Do now: Read the file and print it as it is. If this turn does not "
            "ask gate A, end the turn again: this check refuses once per message.")


def unknown_text(task, path, written_at) -> str:
    return (f"Gate A of {task} is open, but its message file {path} is missing or changed since it was written at {written_at}. "
            f"Do now: run gate_brief.py --task {task} --gate A and print the file it writes whole. If this turn does not ask "
            "gate A, end the turn again: this check refuses once per message.")


def _open_records(event, session) -> list:
    """`[(story folder, record)]`: the records of the message of gate A that THIS session asked, found where `gate_brief` writes
    them (`hooklib.artifact_root`, never a literal path, AR-13). `artifact_root` raises on a broken config: `main` says so."""
    import hooklib
    found = []
    for path in hooklib.sorted_paths(hooklib.artifact_root(event).glob(f"*/state/{GATE_MESSAGE_RECORD}")):
        record = hooklib.read_json(path, {}, kind=dict, errors=Exception)
        if record.get("gate") == "A" and record.get("session_id") == session:
            found.append((path.parent.parent, record))
    return found


def _remember(path, key, entry) -> bool:
    """Write `entry` under `key` in the hook's record, keeping the other keys, atomically (a torn record would refuse twice).
    False when it cannot be written."""
    import hooklib
    from event_store import atomic_json
    try:
        held = hooklib.read_json(path, {}, kind=dict, errors=Exception)
        held[key] = dict(entry, at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        atomic_json(path, held)
        return True
    except Exception:  # noqa: BLE001 - an unwritable record means no refusal
        return False


def _message(task_root, record):
    """`(path, text)`: the message file the record names and its text, or `(path, None)` when it is absent, unreadable, or
    its bytes are not the ones the record measured (an unknown: it is never "shown")."""
    import hashlib
    rel = str(record.get("path") or "")
    path = Path(task_root) / rel
    try:
        if not rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
            return path, None
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != str(record.get("sha256") or ""):
            return path, None
        return path, data.decode("utf-8")
    except (OSError, ValueError):
        return path, None


def _judge(event, session, task_root, record) -> str:
    """The refusal text for one open story of this session, or "" (then the turn passes for it). Writes the hook's record."""
    import gate_brief
    import hooklib
    if gate_brief.gate_a_decided(task_root) is True:
        return ""                                   # decided; None (unreadable) stays OPEN: an unknown is never "decided" (AR-28)
    task, sha = Path(task_root).name, str(record.get("sha256") or "")
    shown_file, key = Path(task_root) / "state" / SHOWN_FILE, f"{session}|A|{sha}"
    held = hooklib.read_json(shown_file, {}, kind=dict, errors=Exception).get(key)
    state = held.get("state") if isinstance(held, dict) else ""
    if state in ("shown", "released"):
        return ""
    path, text = _message(task_root, record)
    unknown, unread, miss = text is None, False, {}
    if not unknown:
        req = required(text)
        if not (req["cards"] or req["answers"] or req["approval"]):
            _remember(shown_file, key, {"state": "shown"})
            return ""                               # nothing required: a packet is never refused for lines it does not have
        last = event.get("last_assistant_message")
        texts = [last] if isinstance(last, str) and last.strip() else []
        miss = missing(req, texts)
        if miss:
            more = assistant_texts_since(event.get("transcript_path"), record.get("written_at"))
            unread = more is None
            miss = missing(req, texts + more) if more is not None else miss
        if not miss:
            _remember(shown_file, key, {"state": "shown"})
            return ""
    reason = "unreadable" if unknown or unread else "missing"
    if state == "refused":
        _remember(shown_file, key, {"state": "released", "reason": reason})
        leak = reason == "missing"
        what = ("the turn that ended after the first refusal still did not carry the lines of " if leak
                else "the check could not establish whether the person saw ")
        hooklib.person_signal(event, "gate_not_shown" if leak else "gate_unreadable",
                              f"gate_shown: {what}the gate A message of {task} ({path}); the second end of the turn was released",
                              task=task, once_key=f"{task}|{sha}")
        return ""
    if not _remember(shown_file, key, {"state": "refused", "reason": reason}):
        hooklib.person_signal(event, "gate_unreadable",
                              f"gate_shown: unreadable - the record {shown_file} cannot be written, so gate A of {task} was not "
                              "refused (better no refusal than a loop)", task=task, once_key=f"unwritable|{task}|{sha}")
        return ""
    return unknown_text(task, path, record.get("written_at")) if unknown else refusal_text(task, path, miss, unread)


def decide(event, now=None) -> tuple:
    """`(exit code, text for stderr)`: 2 and the refusal text at most once per (session, message bytes), else 0 and nothing."""
    if os.environ.get(RUN_MODE_ENV, "").strip() == DRIVER_MODE:
        return 0, ""                                # the driver's own gate packet is code text already
    if not isinstance(event, dict):
        return 0, ""
    import host_adapter
    if host_adapter.is_codex(event):
        return 0, ""
    import session_identity
    session = session_identity.resolve(event, "", "gate_shown.py").get("session_id") or ""
    if not session:
        return 0, ""                                # no session, no record that is "hers": silence (AR-28)
    records = _open_records(event, session)
    texts = [text for text in (_judge(event, session, root, record) for root, record in records) if text]
    return (2, "\n".join(texts)) if texts else (0, "")


def main() -> None:
    import hooklib
    hooklib.run_stop_hook(decide, "gate_shown",
                          "gate_shown: unreadable - the check that gate A reached the person crashed ({exc}) - the factory's "
                          "own defect; the gate A message may have been retold: compare what you were shown with "
                          "work/gate-a-message.md")


if __name__ == "__main__":
    main()
