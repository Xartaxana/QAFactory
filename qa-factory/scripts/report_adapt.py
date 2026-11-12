"""The factory's helper for a test report the code could not read (B-416, D-0031).

Before this, a test command whose report the code could not read was a card for the PERSON at gate A. The owner's order (D-0031):
the code tries every reader it has (`reporters.fits`), then calls the conductor (FR-48); the conductor reads the kept report itself and
records what it changed or understood HERE, so the problem does not recur; the person is asked only when the conductor could not, with
what it already understood.

What is kept: the report the probe run wrote, copied to `qa-factory/state/reporter-unread/<profile>/` with a `manifest.json` (the
command, its digest, what was tried, the sha256 of every file). What is recorded: `qa-factory/records/report-adaptations.json`,
rows `RA-<n>` - `reporter_kind` (the profile's report kind was set to `junit-xml` or `trx`, with the command unchanged) or
`not_adapted` (what the helper understood, in words, when nothing could be changed).

  report_adapt.py kind --profile web --reader trx --by conductor [--task T]
  report_adapt.py understood --profile web --text-file F --by conductor [--task T]
  report_adapt.py show [--json]
  report_adapt.py forget --id RA-1

`kind` re-reads the KEPT bytes (their sha256 against the manifest, the manifest's command against the profile's command now) and writes
the config through `config_contract.apply_adaptation` - the one writer of `reporter.kind` - only for an EMPTY kind and a command that is
unchanged. A cure is never an adaptation here (a cure only decorates a message about a run that already went wrong): it is recorded as
`understood`, in words.

A row counts toward the one conductor turn per command (`countable`) only while it is NEWER than the latest proof of that command in
`qa-factory/state/reporter-rehearsals.json`; an equal time is not newer. A record or a proof file that cannot be read is `unknown`, which
the gate reads as "a row exists" (the card), never as "no row" (FR-59).
"""
import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from hooklib import sorted_paths

sys.path.insert(0, str(Path(__file__).resolve().parent))

RECORD_REL = "qa-factory/records/report-adaptations.json"
UNREAD_REL = "qa-factory/state/reporter-unread"
REHEARSALS_REL = "qa-factory/state/reporter-rehearsals.json"
SCHEMA_VERSION = 1
KINDS = ("reporter_kind", "not_adapted")
WHO = ("driver", "conductor", "orchestrator")
UNDERSTOOD_LIMIT = 2000       # stored; the card shows UNDERSTOOD_SHOWN of it
UNDERSTOOD_SHOWN = 400        # the characters of `understood` the gate card prints (read by `gate_brief._understood_line`)
TAIL_LIMIT = 400              # the tails of stdout / stderr kept in the manifest (read by both cuts of `gate_preflight._keep_unread`)
NOT_CALLED_TEXT = "the helper was called and recorded nothing"       # what the driver writes when the conductor recorded none


def record_path(root) -> Path:
    return Path(root) / Path(RECORD_REL)


def safe_name(profile_id) -> str:
    """The folder name of a profile's kept report (the slot name the rehearsal uses too)."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(profile_id))


def kept_dir(root, profile_id) -> Path:
    return Path(root) / Path(UNREAD_REL) / safe_name(profile_id)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _moment(value) -> float:
    import contract
    return contract._answer_moment(value)


def _digest(argv) -> str:
    from onboarding_probe import argv_digest
    return argv_digest(argv)


# --- the record ------------------------------------------------------------------------------------------------------

def load(root) -> tuple:
    """`(rows, problem)`; never raises. An absent file is `([], "")`. A file that cannot be read, is not an object, holds another
    schema or no `rows` list is `([], <why>)` - and `append` / `kind` / `understood` refuse to write over it."""
    path = record_path(root)
    try:
        if not path.is_file():
            return [], ""
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return [], f"{RECORD_REL} cannot be read ({str(exc)[:80] or type(exc).__name__})"
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION or not isinstance(data.get("rows"), list):
        return [], f"{RECORD_REL} is not a record of this version (schema_version {SCHEMA_VERSION}, a `rows` list)"
    return [r for r in data["rows"] if isinstance(r, dict)], ""


def next_id(rows) -> str:
    numbers = [int(str(r.get("id"))[3:]) for r in rows if str(r.get("id") or "").startswith("RA-") and str(r.get("id"))[3:].isdigit()]
    return f"RA-{max(numbers, default=0) + 1}"


def append(root, row: dict) -> tuple:
    """`(row, problem)`: one row after the others, with the next `RA-<n>` and the moment. Refused, nothing written, over a record
    that cannot be read or a row of another shape. Never raises."""
    if row.get("kind") not in KINDS or not str(row.get("profile_id") or "").strip() or not str(row.get("argv_digest") or "").strip():
        return None, "a row names its kind (reporter_kind | not_adapted), its profile and the digest of its command"
    if row.get("by") not in WHO:
        return None, f"`by` is one of {', '.join(WHO)}"
    rows, problem = load(root)
    if problem:
        return None, problem + "; nothing was written over it"
    new = dict(row, id=next_id(rows), at=now_iso())
    new["understood"] = " ".join(str(new.get("understood") or "").split())[:UNDERSTOOD_LIMIT]
    try:
        from event_store import atomic_json
        atomic_json(record_path(root), {"schema_version": SCHEMA_VERSION, "rows": rows + [new]})
    except Exception as exc:
        return None, f"{RECORD_REL} could not be written ({str(exc)[:80] or type(exc).__name__})"
    return new, ""


def _latest_proof(root, profile_id, digest) -> tuple:
    """`(moment of the latest proof of this command, problem)` - `(None, "")` when there is no proof; a file that cannot be read is a
    problem (the caller reads that as `unknown`)."""
    path = Path(root) / Path(REHEARSALS_REL)
    try:
        if not path.is_file():
            return None, ""
        rows = json.loads(path.read_text(encoding="utf-8")).get("rehearsals")
        if not isinstance(rows, dict):
            raise ValueError("no `rehearsals` map")
    except Exception as exc:
        return None, f"{REHEARSALS_REL} cannot be read ({str(exc)[:60] or type(exc).__name__})"
    moments = [_moment(r.get("at")) for r in rows.values()
               if isinstance(r, dict) and r.get("profile_id") == profile_id and r.get("argv_digest") == digest]
    return (max(moments) if moments else None), ""


def countable(root, profile_id, digest) -> dict:
    """`{state, rows, note}` - the helper's rows of THIS command that still bound the conductor to one turn.

    `state`: `rows` (at least one row newer than the latest proof of the command - an equal moment is not newer; the card branch),
    `none` (no such row: the conductor is called), `unknown` (the record or the proof file cannot be read: the gate reads it as
    `rows`, and `note` names the file - FR-59, M5)."""
    rows, problem = load(root)
    if problem:
        return {"state": "unknown", "rows": [], "note": problem}
    proof, problem = _latest_proof(root, profile_id, digest)
    if problem:
        return {"state": "unknown", "rows": [], "note": problem}
    mine = [r for r in rows if r.get("profile_id") == profile_id and r.get("argv_digest") == digest]
    live = [r for r in mine if proof is None or _moment(r.get("at")) > proof]
    return {"state": "rows" if live else "none", "rows": live, "note": ""}


def last_adaptation(root, profile_id, digest):
    """The newest `reporter_kind` row of this command, or None (an unreadable record is None too: this only decorates a note)."""
    rows, problem = load(root)
    mine = [r for r in rows if not problem and r.get("kind") == "reporter_kind" and r.get("profile_id") == profile_id
            and r.get("argv_digest") == digest]
    return max(mine, key=lambda r: _moment(r.get("at")), default=None)


def proven_adaptations(root, story: str) -> list:
    """The `reporter_kind` rows of THIS story (`story` = ticket) that a LATER proof of the same command confirms - what the factory adapted
    by itself AND what read afterwards (N8: nothing the proof did not confirm is listed, FR-41). [] when either file cannot be read."""
    rows, problem = load(root)
    if problem or not str(story):
        return []
    out = []
    for row in rows:
        if row.get("kind") != "reporter_kind" or row.get("story") != story:
            continue
        proof, why = _latest_proof(root, row.get("profile_id"), row.get("argv_digest"))
        if not why and proof is not None and proof > _moment(row.get("at")):
            out.append(row)
    return out


# --- what was not read -----------------------------------------------------------------------------------------------

def keep_unread(root, profile_id, slot: Path, meta: dict, keep_files: int, keep_limit: int) -> tuple:
    """`(manifest, problem)`: copy the report files of one probe run to `reporter-unread/<profile>/`, the folder REPLACED each time.

    At most `keep_files` files (in name order), each at most `keep_limit` bytes - the rest are listed with `kept: false` and their
    size, never copied. `meta` is the rehearsal's own facts (`argv`, `argv_digest`, `fmt`, `declared_kind`, `reason_class`, the two tails,
    `tried`, `fit`); the manifest adds `at` and `files`. Never raises: a copy that failed is `(None, why)` and one note."""
    target = kept_dir(root, profile_id)
    try:
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        files = []
        candidates = sorted_paths(p for p in Path(slot).rglob("*") if p.is_file()) if Path(slot).is_dir() else []
        for index, path in enumerate(candidates):
            size = path.stat().st_size
            name = path.relative_to(slot).as_posix()
            kept = index < keep_files and size <= keep_limit
            data = path.read_bytes() if size <= keep_limit else b""
            files.append({"name": name, "bytes": size, "sha256": hashlib.sha256(data).hexdigest() if size <= keep_limit else "",
                          "kept": kept})
            if kept:
                (target / "files").mkdir(exist_ok=True)
                copy = target / "files" / name
                copy.parent.mkdir(parents=True, exist_ok=True)
                copy.write_bytes(data)
        manifest = dict(meta, at=now_iso(), files=files)
        (target / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return manifest, ""
    except Exception as exc:
        return None, f"the report could not be kept ({str(exc)[:80] or type(exc).__name__})"


def read_kept(root, profile_id) -> tuple:
    """`(manifest, problem)` of the kept report of one profile, or `(None, why)`."""
    path = kept_dir(root, profile_id) / "manifest.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, f"no kept report of `{profile_id}` can be read ({UNREAD_REL}/{safe_name(profile_id)}/manifest.json): the next rehearsal of its command keeps one"
    return (data, "") if isinstance(data, dict) and isinstance(data.get("files"), list) else (None, "the manifest of the kept report is not one")


def _profile(cfg, profile_id):
    for profile in (cfg or {}).get("profiles") or []:
        if isinstance(profile, dict) and str(profile.get("profile_id") or "") == str(profile_id):
            return profile
    return None


def _argv(profile) -> list:
    import profile_contract as PC     # the ONE reader of the `commands` shape (OH3-27, AR-13)
    return PC.one_test_argv(profile)[0]      # a shape it cannot read records no command here: nothing is adapted


def _identity(profile) -> list:
    """The words that say WHICH command the profile records: `profile_contract.command_identity` (EP1-22 B-2), the single input of
    every digest of a command - the gate's manifest, its rows and these. The argv words when the command sets no `env`, so a
    project without one keeps every digest it has; `_argv` stays for what is SHOWN."""
    import profile_contract as PC
    return PC.command_identity(PC.profile_command(profile, "one_test")[0])


def prove_kept(root, profile_id, reader, cfg) -> tuple:
    """`(tests, problem)`: re-read the KEPT bytes before anything is written (G7: a receipt measured on other bytes never counts).

    The manifest's command must be the profile's command NOW (`argv_digest`), every kept file must still hash to its manifest entry,
    and `reader` must count at least one test in one of them (`reporters.fits`, the entity and size gates included)."""
    import reporters
    profile = _profile(cfg, profile_id)
    argv = _argv(profile)
    if not argv:
        return 0, f"the profile `{profile_id}` records no command that runs one test, so there is nothing to adapt"
    manifest, problem = read_kept(root, profile_id)
    if manifest is None:
        return 0, problem
    if manifest.get("argv_digest") != _digest(_identity(profile)):
        return 0, "the kept report was written by another command than the one the profile records now; it is rehearsed again first"
    folder = kept_dir(root, profile_id) / "files"
    best = 0
    for entry in manifest["files"]:
        if not isinstance(entry, dict) or not entry.get("kept"):
            continue
        path = folder / str(entry.get("name"))
        try:
            data = path.read_bytes()
        except OSError:
            return 0, f"the kept file {entry.get('name')} cannot be read any more"
        if hashlib.sha256(data).hexdigest() != entry.get("sha256"):
            return 0, f"the kept file {entry.get('name')} is not the bytes the manifest was written for (its sha256 differs)"
        for fit in reporters.fits(path):
            if fit["reader"] == reader:
                best = max(best, int(fit["tests"] or 0))
    if best < 1:
        return 0, f"`{reader}` reads no test in the kept report"
    return best, ""


# --- the command line ------------------------------------------------------------------------------------------------

def _refuse(message: str) -> int:
    print(f"report_adapt: {message}", file=sys.stderr)
    return 2


def _context():
    import hooklib
    root = Path(hooklib.project_root())
    try:
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    return root, cfg if isinstance(cfg, dict) else {}


def _story(ns) -> str:
    return str(ns.task or "")


def cmd_kind(ns) -> int:
    import config_contract as CC
    root, cfg = _context()
    profile = _profile(cfg, ns.profile)
    if profile is None:
        known = ", ".join(str(p.get("profile_id")) for p in cfg.get("profiles") or [] if isinstance(p, dict)) or "none"
        return _refuse(f"the profile `{ns.profile}` is not in this project's configuration (it has: {known}); nothing was written")
    if ns.reader not in CC.REPORT_KINDS:
        return _refuse(f"--reader is one of {', '.join(CC.REPORT_KINDS)}; nothing was written")
    kind = str((profile.get("reporter") or {}).get("kind") or "") if isinstance(profile.get("reporter"), dict) else ""
    door = f"record what was understood instead: `report_adapt.py understood --profile {ns.profile} --text-file <file> --by {ns.by}`"
    if kind:
        return _refuse(f"the profile `{ns.profile}` already records its report kind (`{kind}`), and a kind a person recorded is not "
                       f"overwritten; nothing was written. {door}")
    rows, problem = load(root)
    if problem:
        return _refuse(problem + "; nothing was written over it")
    tests, why = prove_kept(root, ns.profile, ns.reader, cfg)
    if why:
        return _refuse(f"{why}; nothing was written. {door}")
    argv = _argv(profile)
    ra = next_id(rows)
    sentence = f"Read the report of the `{ns.profile}` command ({CC.display_command(argv)}) as {ns.reader}?"
    try:
        proposal = CC.command_proposal(root, {"profile_id": ns.profile}, argv, reporter_kind=ns.reader, kind="cure",
                                       reason=f"report adaptation {ra}", question=sentence)
        CC.apply_adaptation(root, proposal, ra)
    except (ValueError, OSError) as exc:
        return _refuse(f"{exc}. {door}")
    row, problem = append(root, {"kind": "reporter_kind", "profile_id": ns.profile, "argv_digest": _digest(_identity(profile)), "story": _story(ns),
                                 "by": ns.by, "reader": ns.reader,
                                 "understood": f"the report was read as {ns.reader} ({tests} test(s) in the kept report)"})
    if row is None:
        print(f"report_adapt: the profile's report kind is now `{ns.reader}`, but the record row could not be written ({problem})", file=sys.stderr)
        return 1
    print(f"{row['id']}: the report of `{ns.profile}` is read as {ns.reader} from now on; the next rehearsal proves it.")
    return 0


PATH_RE = re.compile(r"[A-Za-z]:[\\/][^\s]*|(?<![\w/])/[\w.-]+/[^\s]*|[\w.-]+[\\/][\w.-]+[\\/][\w.-]+\.\w{1,5}\b")


def unfit_words(text) -> str:
    """Why `text` may not be stored as what the helper understood ('' when it may): the person reads it on a card (N7, FR-6), so a script
    name, a flag, a path or a `NAME=value` pair is refused here, where it is written - and the door says how to put it."""
    import human_text
    import stand_gaps
    flat = " ".join(str(text or "").split())
    found = [f"{p.get('rule')}: {p.get('found')}" for p in human_text.shape_problems(flat)]
    if stand_gaps.names_only(flat) != flat:
        found.append("a NAME=value pair")
    path = PATH_RE.search(flat)
    if path:
        found.append(f"path: {path.group(0)}")
    return "; ".join(found[:3])


def cmd_understood(ns) -> int:
    import person_words
    root, cfg = _context()
    profile = _profile(cfg, ns.profile)
    if profile is None:
        return _refuse(f"the profile `{ns.profile}` is not in this project's configuration; nothing was written")
    try:
        text = person_words.read(None, ns.text_file, "--text-file")
    except person_words.WordsRefused as exc:
        return _refuse(str(exc))
    if not str(text or "").strip():
        return _refuse("--text-file is required: what the helper understood, in words. "
                       + person_words.door(f"report_adapt.py understood --profile {ns.profile} --by {ns.by}"))
    unfit = unfit_words(text)
    if unfit:
        return _refuse(f"the text holds something a person is not shown ({unfit}); nothing was written. Say it in words: what the report "
                       "lacked and what would fix it, no commands, flags, file names or paths")
    argv = _argv(profile)
    if not argv:
        return _refuse(f"the profile `{ns.profile}` records no command that runs one test; nothing was written")
    row, problem = append(root, {"kind": "not_adapted", "profile_id": ns.profile, "argv_digest": _digest(_identity(profile)), "story": _story(ns),
                                 "by": ns.by, "understood": text})
    if row is None:
        return _refuse(problem)
    print(f"{row['id']}: recorded for `{ns.profile}`; the person is asked about it once, with this.")
    return 0


def cmd_show(ns) -> int:
    root, _cfg = _context()
    rows, problem = load(root)
    if ns.json:
        print(json.dumps({"rows": rows, "problem": problem}, indent=2, ensure_ascii=False))
    elif problem:
        print(problem)
    elif not rows:
        print("no report adaptation is recorded.")
    else:
        for r in rows:
            print(f"{r.get('id')} ({r.get('kind')}, {r.get('by')}, {str(r.get('at') or '')[:10]}): `{r.get('profile_id')}`"
                  + (f" read as {r['reader']}" if r.get("reader") else "") + f" - {' '.join(str(r.get('understood') or '').split())[:160]}")
    return 1 if problem else 0


def cmd_forget(ns) -> int:
    root, _cfg = _context()
    rows, problem = load(root)
    if problem:
        return _refuse(problem + "; nothing was written over it")
    if not any(str(r.get("id")) == ns.id for r in rows):
        return _refuse(f"there is no row {ns.id} in {RECORD_REL}; `report_adapt.py show` lists them")
    try:
        from event_store import atomic_json
        atomic_json(record_path(root), {"schema_version": SCHEMA_VERSION, "rows": [r for r in rows if str(r.get("id")) != ns.id]})
    except Exception as exc:
        return _refuse(f"{RECORD_REL} could not be written ({str(exc)[:80]})")
    print(f"{ns.id} is forgotten: the next unread report of that command goes to the conductor once more. The configuration is untouched.")
    return 0


def main(argv=None) -> int:
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    ap = argparse.ArgumentParser(description="The factory's helper for a test report the code could not read.")
    sub = ap.add_subparsers(dest="command", required=True)
    kind = sub.add_parser("kind")
    kind.add_argument("--profile", required=True)
    kind.add_argument("--reader", required=True)
    kind.add_argument("--by", required=True, choices=WHO)
    kind.add_argument("--task", default="")
    kind.set_defaults(fn=cmd_kind)
    understood = sub.add_parser("understood")
    understood.add_argument("--profile", required=True)
    understood.add_argument("--text-file", dest="text_file", default=None)
    understood.add_argument("--by", required=True, choices=WHO)
    understood.add_argument("--task", default="")
    understood.set_defaults(fn=cmd_understood)
    show = sub.add_parser("show")
    show.add_argument("--json", action="store_true")
    show.set_defaults(fn=cmd_show)
    forget = sub.add_parser("forget")
    forget.add_argument("--id", required=True)
    forget.set_defaults(fn=cmd_forget)
    ns = ap.parse_args(argv)
    return ns.fn(ns)


if __name__ == "__main__":
    sys.exit(main())
