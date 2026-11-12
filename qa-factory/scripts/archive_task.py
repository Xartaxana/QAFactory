# -*- coding: utf-8 -*-
"""Archive a story on a person's word — the only writer of `pipeline.json`'s `archived`.

Run (via run-py.cmd):
    archive_task.py --candidates [--days N] [--json]   (closed stories, and stalled ones)
    archive_task.py --task <TICKET> --note "<the human's words, verbatim>" [--force]
    archive_task.py --task <TICKET> --words-file <path> [--force]   (the words, as given, from a file)
    archive_task.py --task <TICKET> --undo
    archive_task.py --selftest

Until 0.3.0 the flag was set by S9, on its own inference that "the feature's last sibling
story closed" — which is the entire reason the factory ever went looking for sibling
tickets, walking an epic that other teams also work in. There is no sibling concept any
more, so there is no moment a role can infer. Archiving is now what it always meant to a
person: *stop showing me this*. `qa-doctor` offers the candidates, a person names them, and
this script writes the flag.

Two things follow from "a person said so", and both are the point of this file:

1. **It can hide an unfinished story.** A story with an unresolved halt or an unanswered
   gate is refused (exit 4) with the open items listed, so the doctor can put them to the
   human as their own question. `--force` is the human answering "archive it, those
   questions are no longer relevant" — and then the halts are *resolved* with that sentence
   as their resolution, because a decision that leaves the data contradicting it is not a
   decision, it is a flag on top of an open item nobody will look at again.
2. **It must be undoable.** `--undo` exists so the first wrong call is fixed here rather
   than by hand-editing JSON.

The folder never moves: moving it separates `requirements-register.md` from the `TC-*.md`
files citing it, and the exit gate then reports every case as inventing its requirements
(TP1-13958).
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hooklib  # noqa: E402  (`read_json`, the one JSON reader)
from hooklib import artifact_root, load_ref_json, story_closed  # noqa: E402
from hooklib import sorted_paths  # noqa: E402

DEFAULT_DAYS = 14
EXIT_OPEN_ITEMS = 4
EXIT_NOT_FOUND = 1
EXIT_BAD_ARGS = 2  # the same code argparse uses, and `main()` already returns it for no action


def read_json(path: Path) -> dict:
    """The JSON object in `path`, else {}: this script reads, changes and writes objects only. `{}` is written here, in
    the `def`, so every call gets its own (`cmd_archive` mutates the one it is handed)."""
    return hooklib.read_json(path, {}, kind=dict, errors=Exception)


def stage_order() -> list:
    return [s.get("id") for s in (load_ref_json("stages.json").get("stages") or [])]


def _parse_ts(raw) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def last_activity(pipeline: dict) -> datetime | None:
    """The newest timestamp anywhere in the pipeline — stages, gates, halts.

    "Old" is a fact about the file, not about the folder's mtime: a `git checkout` touches
    every mtime on the disk and would otherwise make a finished story look busy."""
    stamps = []
    stages = pipeline.get("stages") if isinstance(pipeline.get("stages"), dict) else {}
    for st in stages.values():
        if isinstance(st, dict):
            stamps += [_parse_ts(st.get("finished")), _parse_ts(st.get("started"))]
    gates = pipeline.get("gates") if isinstance(pipeline.get("gates"), dict) else {}
    for g in gates.values():
        if isinstance(g, dict):
            stamps.append(_parse_ts(g.get("at")))
    for h in pipeline.get("halts") or []:
        if isinstance(h, dict):
            stamps.append(_parse_ts(h.get("at")))
    stamps = [s for s in stamps if s is not None]
    if not stamps:
        return None
    return max(s if s.tzinfo else s.replace(tzinfo=timezone.utc) for s in stamps)


def hold_line(pipeline: dict) -> str:
    """The one line that says a story is held for code, for the doctor (`stage_guard.stories`) and the archive (`open_items`):
    `awaiting code since <date> (<sides>)`, `held after the first look since <date> (<sides>)`, `stopped waiting <date>` (+
    ` (after the first look)`); "" when nothing is held. Read through `contract.awaiting` (t-2181 PC-6, AR-13): a record written
    before the cause existed reads `s5_absent_side`. `<sides>` are the recorded sides that are not `real`."""
    import contract as C
    hold = C.awaiting(pipeline)
    if hold["state"] == "none":
        return ""
    first_look = hold["cause"] == "first_look_stop"
    if hold["state"] == "stopped":
        stopped = hold.get("stopped") if isinstance(hold.get("stopped"), dict) else {}
        return f"stopped waiting {str(stopped.get('at') or '')[:10] or 'at an unknown time'}" + (" (after the first look)" if first_look else "")
    sides = hold.get("sides") if isinstance(hold.get("sides"), dict) else {}
    names = ", ".join(str(name) for name, entry in sides.items() if not (isinstance(entry, dict) and entry.get("reality") == "real"))
    label = ("held after the first look" if first_look else "awaiting code" if hold["cause"] == C.AWAITING_DEFAULT_CAUSE
             else f"held for code ({hold['cause']})")
    return f"{label} since {str(hold.get('since') or '')[:10] or 'an unknown date'}" + (f" ({names})" if names else "")


def open_items(pipeline: dict) -> list:
    """What still asks something of a person. Empty list = a clean candidate."""
    out = []
    for h in pipeline.get("halts") or []:
        if isinstance(h, dict) and not h.get("resolved"):
            out.append("unresolved halt: " +
                       str(h.get("reason") or h.get("digest") or "no reason recorded")[:120])
    stages = pipeline.get("stages") if isinstance(pipeline.get("stages"), dict) else {}
    order = stage_order()
    reached = {sid for sid in order if (stages.get(sid) or {}).get("status")}
    import contract as C
    for name, after in (("A", "S3"), ("B", "S8")):
        # The question here is "was the person ever put in front of this gate", not "did they
        # approve": a decline is an answer and does not hold a story open. Both readings live
        # in contract.py since TP1-15045 taught the factory what one field in two vocabularies costs.
        if not C.gate_answered(pipeline, name) and (stages.get(after) or {}).get("status") == "done":
            out.append(f"gate {name} was opened after {after} and never answered")
    for sid in order:
        status = str((stages.get(sid) or {}).get("status") or "")
        if status in ("running", "halted"):
            out.append(f"{sid} left {status}")
    last = order[-1] if order else ""
    # t-2181 PC-6 (§2.4): a story held for code names what it waits for INSTEAD of "parked" (that sentence is for a story nobody
    # explains); a STOPPED story is no open item at all - the person ended the wait, and the story is theirs to archive.
    hold = C.awaiting(pipeline)
    if hold["state"] == "awaiting":
        out.append(hold_line(pipeline))
    elif hold["state"] == "none" and reached and last and (stages.get(last) or {}).get("status") != "done":
        out.append(f"the story never reached {last} done — it was parked, not finished")
    return out


def stories(days: int) -> list:
    root = artifact_root()
    if not root.exists():
        return []
    now = datetime.now(timezone.utc)
    rows = []
    for pj in sorted_paths(root.glob("*/pipeline.json")):
        if any(part in ("_archive", "archive") for part in pj.parts):
            continue
        data = read_json(pj)
        if not data or data.get("archived"):
            continue
        seen = last_activity(data)
        age = (now - seen).days if seen else None
        # A closed story is a candidate the day it closes, whatever --days says: standing
        # still is a GUESS that a story is over, and `closed_at` is the fact itself. Waiting
        # 14 days for it is what left TP2-2534 in the listing long enough to make the
        # live story's dispatches ambiguous (I-92). `open_items` is unchanged: a closed story
        # that still carries an unresolved halt is offered, and still named as carrying it.
        closed_at = story_closed(data)
        rows.append({"ticket": pj.parent.name, "age_days": age,
                     "closed_at": closed_at,
                     "open_items": open_items(data),
                     "candidate": bool(closed_at) or (age is not None and age >= days)})
    return rows


def cmd_candidates(days: int, as_json: bool) -> int:
    rows = [r for r in stories(days) if r["candidate"]]
    if as_json:
        print(json.dumps({"days": days, "candidates": rows}, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print(f"no story is closed and none has stood still for {days} days — nothing to offer")
        return 0
    for r in rows:
        age = f"{r['age_days']}d" if r["age_days"] is not None else "age unknown"
        head = f"{r['ticket']}  {age}"
        if r.get("closed_at"):
            head += f"  closed {r['closed_at']}"
        if r["open_items"]:
            print(f"{head}  OPEN ITEMS ({len(r['open_items'])}): "
                  + " | ".join(r["open_items"]))
        else:
            print(f"{head}  clean — every stage done, both gates answered")
    return 0


def cmd_archive(ticket: str, note: str, force: bool) -> int:
    path = artifact_root() / ticket / "pipeline.json"
    if not path.exists():
        print(f"{ticket}: no pipeline.json at {path} — nothing to archive", file=sys.stderr)
        return EXIT_NOT_FOUND
    data = read_json(path)
    if data.get("archived"):
        print(f"{ticket}: already archived ({data.get('archived_at') or 'no date recorded'})")
        return 0
    items = open_items(data)
    if items and not force:
        print(f"{ticket}: not archived — it still carries {len(items)} open item(s):",
              file=sys.stderr)
        for it in items:
            print("  - " + it, file=sys.stderr)
        print("Put these to the human as their own question. Archive anyway only on an "
              "explicit answer, and pass it through: --force --words-file <path to their words, "
              "as they were given>.",
              file=sys.stderr)
        return EXIT_OPEN_ITEMS
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data["archived"] = True
    data["archived_at"] = now
    data["archived_by"] = "human"
    if note:
        data["archived_note"] = note
    if items:
        data["archived_with_open_items"] = items
        resolution = "archived by human — " + (note or "no reason recorded")
        for h in data.get("halts") or []:
            if isinstance(h, dict) and not h.get("resolved"):
                h["resolved"] = True
                h["resolution"] = resolution
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    journal(ticket, f"archived by human: {note or 'no note'}"
            + (f" (with {len(items)} open item(s) resolved as no longer relevant)" if items else ""))
    print(f"{ticket}: archived at {now}"
          + (f", {len(items)} open item(s) closed as no longer relevant" if items else ""))
    return 0


def cmd_undo(ticket: str) -> int:
    path = artifact_root() / ticket / "pipeline.json"
    if not path.exists():
        print(f"{ticket}: no pipeline.json at {path}", file=sys.stderr)
        return EXIT_NOT_FOUND
    data = read_json(path)
    if not data.get("archived"):
        print(f"{ticket}: not archived — nothing to undo")
        return 0
    for key in ("archived", "archived_at", "archived_by", "archived_note",
                "archived_with_open_items"):
        data.pop(key, None)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    journal(ticket, "un-archived by human")
    print(f"{ticket}: un-archived. Halts closed by the archive stay closed — reopen the "
          "ones that matter by hand, they carry their resolution text.")
    return 0


def journal(ticket: str, notes: str) -> None:
    """Best-effort: a journal that cannot be written must not lose the archive itself."""
    try:
        from log_append import build_record, write
        write([build_record({"event": "archived", "task": ticket, "notes": notes})])
    except Exception:
        pass


def selftest() -> int:
    import tempfile
    failures = []

    def case(name, got, expected):
        if got != expected:
            failures.append(f"{name}: got {got!r}, expected {expected!r}")
        print(("PASS " if got == expected else "FAIL ") + name)

    old = datetime.now(timezone.utc) - timedelta(days=30)
    clean = {"ticket": "QA-1", "stages": {"S0": {"status": "done", "finished": old.isoformat()}},
             "gates": {"A": {"decision": "approve"}, "B": {"decision": "approve"}}, "halts": []}
    case("last_activity reads a stage timestamp", last_activity(clean) is not None, True)
    case("no timestamps anywhere -> None", last_activity({"stages": {}}), None)

    halted = {"stages": {"S3": {"status": "done"}, "S4": {"status": "halted"}},
              "gates": {"A": {"decision": "approve"}}, "halts": [{"reason": "no stand"}]}
    items = open_items(halted)
    case("an unresolved halt is an open item", any("unresolved halt" in i for i in items), True)
    case("a stage left halted is an open item", any("S4 left halted" in i for i in items), True)

    unanswered = {"stages": {"S3": {"status": "done"}}, "gates": {}, "halts": []}
    case("gate A opened and never answered is an open item",
         any("gate A" in i for i in open_items(unanswered)), True)

    resolved = {"stages": {"S3": {"status": "done"}},
                "gates": {"A": {"decision": "approve"}, "B": {"decision": "approve"}},
                "halts": [{"reason": "x", "resolved": True}]}
    case("a resolved halt is not an open item",
         any("unresolved halt" in i for i in open_items(resolved)), False)

    # A closed story is offered the day it closes (I-92) — `--days` is the guess that a
    # story standing still is over, `closed_at` is the fact, and 14 days of waiting is what
    # kept TP2-2534 in every listing while it made a live story's dispatches ambiguous.
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    closed_today = {"ticket": "QA-2", "closed_at": now_iso,
                    "stages": {"S8": {"status": "done", "finished": now_iso}},
                    "gates": {"A": {"decision": "approve"}, "B": {"decision": "approve"}}}
    case("a closed story is a candidate on day 0", story_closed(closed_today) == now_iso, True)
    legacy_closed = {"ticket": "QA-3",
                     "stages": {"S8": {"status": "done", "finished": old.isoformat()}},
                     "gates": {"A": {"decision": "approve"},
                               "B": {"decision": "approve", "at": old.isoformat()}}}
    case("a 0.7.x story with no closed_at closes by inference, no migration",
         bool(story_closed(legacy_closed)), True)

    with tempfile.TemporaryDirectory(prefix="qa-archive-") as td:
        import hooklib
        proj = Path(td)
        (proj / "qa-factory" / "artifacts" / "QA-9").mkdir(parents=True)
        # The project marker: the journal writer refuses a root without it.
        (proj / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
        pj = proj / "qa-factory" / "artifacts" / "QA-9" / "pipeline.json"
        pj.write_text(json.dumps({"ticket": "QA-9", "stages": {"S4": {"status": "halted"}},
                                  "halts": [{"reason": "no stand"}]}), encoding="utf-8")
        hooklib._PROJECT_ROOT_CACHE = proj
        print(f"SELFTEST ROOT: {hooklib.project_root()}")  # a hijacked root reads as line one
        case("open items refuse a bare archive", cmd_archive("QA-9", "", False), EXIT_OPEN_ITEMS)
        case("nothing was written on the refusal", read_json(pj).get("archived"), None)
        case("--force archives", cmd_archive("QA-9", "questions no longer relevant", True), 0)
        after = read_json(pj)
        case("the flag is set", after.get("archived"), True)
        case("the human is named as the author", after.get("archived_by"), "human")
        case("the halt was closed with the human's words",
             (after.get("halts") or [{}])[0].get("resolution"),
             "archived by human — questions no longer relevant")
        case("the open items are recorded, not hidden",
             bool(after.get("archived_with_open_items")), True)
        case("--undo clears the flag", cmd_undo("QA-9"), 0)
        case("the flag is gone", read_json(pj).get("archived"), None)

        closed_dir = proj / "qa-factory" / "artifacts" / "QA-2"
        closed_dir.mkdir(parents=True)
        (closed_dir / "pipeline.json").write_text(json.dumps(closed_today), encoding="utf-8")
        rows = {r["ticket"]: r for r in stories(DEFAULT_DAYS)}
        case("a story closed today is a candidate at --days 14",
             (rows.get("QA-2") or {}).get("candidate"), True)
        case("and the row carries closed_at, so the offer can say why",
             (rows.get("QA-2") or {}).get("closed_at"), now_iso)
        case("a story that is neither closed nor stale is still not offered",
             (rows.get("QA-9") or {}).get("candidate"), False)
        hooklib._PROJECT_ROOT_CACHE = None

    print(f"=== SELFTEST archive_task: {'PASSED' if not failures else f'FAILED ({len(failures)})'} ===")
    return 0 if not failures else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Archive a story on a person's word")
    ap.add_argument("--candidates", action="store_true",
                    help="list closed stories, and stories that have stood still for --days")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS)
    ap.add_argument("--task", default="", help="the ticket to archive or un-archive")
    ap.add_argument("--note", default=None, help="the human's words, verbatim")
    ap.add_argument("--words-file", default=None,
                    help="a file holding the human's words as they were given (UTF-8; "
                         "<story folder>/state/words/<name>.txt), instead of --note")
    ap.add_argument("--force", action="store_true",
                    help="archive despite open items — only on an explicit human answer")
    ap.add_argument("--undo", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if args.candidates:
        return cmd_candidates(args.days, args.json)
    if args.task and args.undo:
        return cmd_undo(args.task)
    if args.task:
        # Resolved ONCE, before the pipeline is read: a refusal archives nothing and journals
        # nothing. `--note` is optional, so an empty result is the existing "no note" archive.
        import person_words
        try:
            note = person_words.read(args.note, args.words_file, "--note")
        except person_words.WordsRefused as exc:
            print(f"archive_task: {exc}", file=sys.stderr)
            return EXIT_BAD_ARGS
        return cmd_archive(args.task, note or "", args.force)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
