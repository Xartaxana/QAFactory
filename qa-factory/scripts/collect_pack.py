"""The collector of the COLLECT skill (CL1-2, t-1024; t-962 sections 2, 3, 8 as corrected by L-2): the records of a project that runs
the factory, packed into ONE zip for the factory's developers. A library: `pack()` does the whole job, `summary_lines()` is the
text a person reads, `Refused` is a refusal in FR-1 form (exit code 1). `main()` is the command line the qa-collect skill runs (CL1-4,
t-1062): `--root --problems-file --suggestions-file [--not-asked] [--extra SET=path] [--since install] [--activity-not-recorded] [--answers-not-split]
[--json]`; exit 0 packed, 1 a
refusal, 2 a usage error. No LLM is involved anywhere (FR-51).

Why it looks the way it does.
* Every byte that leaves passes the CL1-1 redactor (`machine_facts`): file contents, summaries, the manifest's strings, member names.
  After the archive is written it is READ BACK, every member must hash as the manifest says, and `Redactor.residue()` must find
  nothing in any member; a finding deletes the archive and refuses (I2: the detector of the filter itself, the mark does not move).
* What goes in is data, not code (FR-13): `references/collect-sets.json` names the sets A-H, their files, modes, ceilings and the
  never-list. A file no entry names is a manifest row (skipped, unknown file), never silence and never a crash (I4, edge 3).
* The window is the mark `state/collect/mark.json`. Append-only files (jsonl, events) are taken by the PREFIX OF THEIR BYTES: the
  mark holds the byte count and the sha256 of those bytes; a file whose prefix no longer matches is taken whole and flagged
  `prefix_changed`, an events file whose hash at the marked sequence differs is taken whole and flagged `chain_reset`. A line that is
  still being written is never taken: the boundary is the last `\\n` (I3: when in doubt, more, never a hole; the receiver drops duplicates).
* The archive is not written where git would see it: `git check-ignore` decides, not an assumption (I6); a place git would show
  goes to the temp folder with the named reason. The mark moves only after the archive was re-read and found whole.
* The manifest is the first member of part 1 and lists parts 2..n with their hashes; part 1 cannot hash itself (L-2 m8).
* Set H (CL1-4, t-962 F-5 (i) and L-2 F-2; CL3-9): every story gets the stall verdict of `collect_stall` (K1..K7, the mark as its window)
  and its loop verdict (L1..L7, the table `references/collect-loops.json`, loaded in `start()` beside the sets: a broken one refuses the
  whole collect); the transcripts of a STALLED or LOOPED story (or one whose looping is not known) - its sessions' main transcripts and the subagent transcripts whose session folder is the stem of one of
  them, never another story's roles - go into their OWN file `<archive>-transcripts.zip`, listed in the manifest like any part
  (`kind: transcripts`), so the person can delete just that file. A transcript that is not on disk or cannot be read is a gap with its
  session id (H does not search the disk). `stalled` is `None` only when `unreadable` is the single reason (an unknown is not a fact, FR-41);
  the transcripts are still taken then, because an extra transcript is the safe side.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import sys
import tempfile
import uuid
import zipfile
import zlib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect_stall  # noqa: E402
import hooklib  # noqa: E402
import machine_facts  # noqa: E402
import person_words  # noqa: E402
import project_inventory  # noqa: E402
import runtime_paths  # noqa: E402
import story_version  # noqa: E402

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SETS_FILE = PACKAGE_ROOT / "references" / "collect-sets.json"
SCHEMA = "qa-collect/1"
MODES = ("copy", "tail", "new", "sum", "index", "snapshots", "skip")
SET_LETTERS = "ABCDEFGH"
REQUIRED_KEYS = ("schema", "note", "limits", "archive", "set_names", "never_content", "entries")
LIMIT_KEYS = ("file_max_bytes", "part_max_bytes", "excerpt_lines")
EXCERPT_LINE_CHARS = 2000
HISTORY_FILES_THAT_TOUCH = ("state/events.jsonl", "pipeline.json")
ZIP_LOCAL, ZIP_CENTRAL, ZIP_END = 30, 46, 22
_REFUSAL_TAIL = "reinstall the plugin - packing without its redaction rules would send unredacted data"


class Refused(Exception):
    """A refusal in FR-1 form: what is wrong, what was expected, how to satisfy it. Nothing was written."""
    exit_code = 1


# --- the data and its glob ----------------------------------------------------------------------------------------------

def _glob_re(pattern: str):
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def compile_entries(sets: dict, onboarded: bool = True) -> list:
    """The table's entries as `[(entry, [compiled patterns])]` in table order: a `virtual` entry has no path, and a project that is
    not onboarded has only the set-A entries. The ONE compiler; the packer and the binding test both read the table through it."""
    out = []
    for e in sets["entries"]:
        if e.get("virtual") or (not onboarded and e["set"] != "A"):
            continue
        out.append((e, [_glob_re(p) for p in e.get("paths", []) + e.get("old_paths", [])]))
    return out


def match_entry(compiled: list, scope: str, rel: str):
    """The FIRST entry of `scope` one of whose patterns matches `rel` (a posix path), else None: the order of the table is the precedence."""
    for e, pats in compiled:
        if e["scope"] == scope and any(p.match(rel) for p in pats):
            return e
    return None


def load_sets(path=SETS_FILE) -> dict:
    """The packing data, validated; anything wrong refuses (a packer without its data would pack by guess)."""
    def refuse(why):
        return Refused(f"COLLECT: the packing rules {path} cannot be read ({why}); {_REFUSAL_TAIL}")
    nothing = object()
    data = hooklib.read_json(path, nothing, errors=Exception)
    if data is nothing:
        raise refuse("absent or not valid JSON")
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise refuse("not a JSON object of schema 1")
    missing = [k for k in REQUIRED_KEYS if k not in data] + [f"limits.{k}" for k in LIMIT_KEYS if k not in (data.get("limits") or {})]
    if missing:
        raise refuse(f"{missing[0]} missing")
    for e in data["entries"]:
        if e.get("set") not in tuple(SET_LETTERS) or e.get("mode") not in MODES or e.get("scope") not in ("p", "h"):
            raise refuse(f"entry {e.get('id')} has a set, mode or scope this reader does not know")
        if e["mode"] == "sum" and e.get("sum") not in SUMMARISERS:
            raise refuse(f"entry {e.get('id')} names the summary {e.get('sum')!r}, which this reader does not have")
    return data


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _iso(when: datetime) -> str:
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_epoch(seconds):
    """A signal's time (epoch seconds, as `collect_stall` keeps it) as the manifest's UTC text; None when there is none or it is not a time."""
    try:
        return _iso(datetime.fromtimestamp(float(seconds), timezone.utc))
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _parse_time(text):
    try:
        got = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
        return got if got.tzinfo else got.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _option_named(exc, name: str) -> str:
    """`person_words.read`'s refusal, said in this command's words: its own option (`--words-file`) becomes the one the person's
    command carries (`--<name>-file`), and the orchestrator's story folder it points a missing file to is left out - this command
    has no story folder. Everything else (what is wrong, how to satisfy it) is its text, unchanged (FR-1)."""
    text = str(exc).replace(person_words.OPTION, f"--{name}-file")
    return re.sub(r"\s*\(the orchestrator keeps them in [^)]*\)", "", text)


def _is_blank_file(path) -> bool:
    """A readable file that holds no words (zero bytes, a BOM, whitespace). Anything else - missing, NUL bytes, too big - is for `person_words.read` to refuse."""
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return False
    return b"\x00" not in raw and not raw.decode("utf-8-sig", "replace").strip()


def _stream_sha(path: Path, upto: int | None = None) -> tuple:
    """(sha256 hex of the first `upto` bytes or of the whole file, newline count of what was read)."""
    h, left, lines = hashlib.sha256(), upto, 0
    with open(path, "rb") as stream:
        while left is None or left > 0:
            chunk = stream.read(1 << 20 if left is None else min(1 << 20, left))
            if not chunk:
                break
            h.update(chunk)
            lines += chunk.count(b"\n")
            left = None if left is None else left - len(chunk)
    return h.hexdigest(), lines


# --- summaries (sum mode): small, named, no product text ----------------------------------------------------------------

def _json_of(path: Path):
    return hooklib.read_json(path, None, errors=Exception)


def _size_of(path: Path):
    """`st_size`, or None for a file that vanished after the pack listed it (a hook rotates or removes files while the
    pack runs; the same race `_sum_telemetry` counts as `vanished_files`)."""
    try:
        return path.stat().st_size
    except OSError:
        return None


def _with_vanished(summary: dict, vanished: int) -> dict:
    """The summary, naming the files that vanished before they could be measured - only when there were any (FR-41)."""
    return {**summary, "vanished_files": vanished} if vanished else summary


def _sum_dir_stats(run, files, e):
    kinds, statuses, total, vanished = Counter(), Counter(), 0, 0
    for p in files:
        size = _size_of(p)
        if size is None:
            vanished += 1
            continue
        total += size
        kinds[p.suffix.lower() or "(none)"] += 1
        if p.suffix.lower() == ".json":
            doc = _json_of(p)
            if isinstance(doc, dict) and isinstance(doc.get("status"), str):
                statuses[doc["status"]] += 1
    return _with_vanished({"files": len(files) - vanished, "bytes": total, "by_suffix": dict(sorted(kinds.items())),
                           "by_status": dict(sorted(statuses.items()))}, vanished)


def _sum_host_receipts(run, files, e):
    hosts, versions, total, vanished = Counter(), Counter(), 0, 0
    for p in files:
        size = _size_of(p)
        if size is None:
            vanished += 1
            continue
        total += size
        doc = _json_of(p)
        if not isinstance(doc, dict):
            continue
        if p.name.startswith("package-"):
            versions[str(doc.get("package_version") or doc.get("version") or "unknown")] += 1
        else:
            hosts[str(doc.get("host") or "unspecified")] += 1
    return _with_vanished({"files": len(files) - vanished, "bytes": total, "by_host": dict(sorted(hosts.items())),
                           "package_versions": dict(sorted(versions.items()))}, vanished)


COLLECT_MERGE_WAIT_S = 30.0   # how long the telemetry count waits for the Stop-time merge before it counts without the lock (F-13)


def _telemetry_listing(directories):
    """The telemetry files to count: every `*.jsonl` and `*.jsonl.merging` in each directory, one `os.scandir` each, in
    name order (a per-process `hook-<pid>` before the daily `hook-merged-<date>` a merge moves its lines to: a line seen
    in the source is seen again in the day and counted once). Only regular files: a symlink is never followed (the pack's
    classifier skips it) and a directory named `*.jsonl` is not a file. A folder that cannot be listed contributes nothing."""
    found = []
    for directory in directories:
        try:
            with os.scandir(directory) as entries:
                found.extend(Path(x.path) for x in entries
                             if x.name.endswith((".jsonl", ".jsonl.merging")) and _is_plain_file(x))
        except OSError:
            continue
    return sorted(found, key=lambda p: (str(p.parent), p.name))


def _is_plain_file(entry) -> bool:
    try:
        return entry.is_file(follow_symlinks=False)
    except OSError:
        return False


def _count_text(text, seen, days) -> int:
    """Count the span lines of one file's text into `days` (day -> Counter of `kind|outcome|reason`), each line once
    across ALL files: `seen` holds the `line_key` of every line already taken. Returns how many NEW lines were unreadable
    (not a JSON object with a `timestamp`) - a torn line that sits in two files is one unreadable line, not two."""
    import telemetry_capture
    bad = 0
    for line in telemetry_capture.split_lines(text):
        try:
            row = json.loads(line)
        except (ValueError, RecursionError):
            row = None
        identity = telemetry_capture.line_key(line, event=row)
        if identity in seen:
            continue
        seen.add(identity)
        try:
            day = str(row["timestamp"])[:10]
            key = "|".join(str(row.get(k)) for k in ("span_kind", "outcome", "reason_code"))
        except (KeyError, TypeError, AttributeError):
            bad += 1
            continue
        days.setdefault(day, Counter())[key] += 1
    return bad


def _lock_word(states) -> str:
    """One word for the directories' locks: "held" only when every one was; "unavailable" when any could not be made
    (nobody holds it - FR-41), else "busy"."""
    if all(s == "held" for s in states):
        return "held"
    return "unavailable" if "unavailable" in states else "busy"


def _sum_telemetry(run, files, e):
    """B8: span events per day, each event once. The Stop-time merge moves lines between files, so the count takes the
    merge lock (waits up to COLLECT_MERGE_WAIT_S), re-lists the directory under it, and counts a line by its
    `telemetry_capture.line_key` across ALL files. A lock not got in time is `merge_lock: "busy"`: counted without it,
    still never twice; a line caught between two files can then be missed (FR-41 names it, it does not hide it). A lock
    that could not be made at all says `unavailable`. `files` and `bytes` count the span files that were READ."""
    if not files:
        return {"files": 0, "bytes": 0, "unreadable_lines": 0, "vanished_files": 0, "merge_lock": "none", "days": {}}
    from contextlib import ExitStack
    import telemetry_capture
    directories = sorted({Path(p).parent for p in files})
    days, seen, bad, vanished, total, counted = {}, set(), 0, 0, 0, 0
    with ExitStack() as stack:
        states = [stack.enter_context(telemetry_capture.merge_lock(d, COLLECT_MERGE_WAIT_S)) for d in directories]
        for p in _telemetry_listing(directories):
            try:
                data = p.read_bytes()
            except OSError:
                vanished += 1
                continue
            total += len(data)
            counted += 1
            bad += _count_text(data.decode("utf-8", errors="replace"), seen, days)
    return {"files": counted, "bytes": total, "unreadable_lines": bad, "vanished_files": vanished,
            "merge_lock": _lock_word(states), "days": {d: dict(sorted(c.items())) for d, c in sorted(days.items())}}


def _sum_install_manifest(run, files, e):
    doc = _json_of(files[0])
    if not isinstance(doc, dict):
        return {"state": "unreadable"}
    entries = doc.get("entries") if isinstance(doc.get("entries"), list) else []
    return {"state": "ok", "package_version": doc.get("package_version"),
            "by_class": dict(sorted(Counter(str(x.get("class")) for x in entries if isinstance(x, dict)).items()))}


def _sum_open_questions(run, files, e):
    doc = _json_of(files[0])
    items = doc.get("open_questions") if isinstance(doc, dict) else None
    if not isinstance(items, list):
        return {"state": "no open_questions list", "count": None}
    return {"state": "ok", "count": len(items), "items": items}


def _sum_unresolved(run, files, e):
    out = {}
    for p in files:
        doc = _json_of(p)
        out[p.name] = ({"unresolved": doc.get("unresolved"), "source_completeness": doc.get("source_completeness")}
                       if isinstance(doc, dict) else {"state": "unreadable"})
    return out


def _count_key(node, key, want) -> int:
    if isinstance(node, dict):
        return sum(1 for k, v in node.items() if k == key and v == want) + sum(_count_key(v, key, want) for v in node.values())
    if isinstance(node, list):
        return sum(_count_key(v, key, want) for v in node)
    return 0


def _sum_artifacts(run, files, e):
    rows, vanished = {}, 0
    for p in files:
        rel = p.as_posix()
        size = _size_of(p)
        if size is None:
            vanished += 1
            continue
        row = {"bytes": size}
        if p.suffix == ".json":
            doc = _json_of(p)
            row["overridden_true"] = _count_key(doc, "overridden", True)
            if isinstance(doc, dict):
                row["delivery"] = {k: doc[k] for k in ("delivery_ready", "verdict") if isinstance(doc.get(k), (str, bool))}
        rows[p.name + "@" + _sha(rel.encode())[:6]] = row
    return _with_vanished({"files": len(files) - vanished, "rows": rows}, vanished)


def _sum_passport(run, files, e):
    return run.passport()


SUMMARISERS = {"dir_stats": _sum_dir_stats, "host_receipts": _sum_host_receipts, "telemetry": _sum_telemetry,
               "install_manifest": _sum_install_manifest, "open_questions": _sum_open_questions, "unresolved": _sum_unresolved,
               "artifacts_summary": _sum_artifacts, "passport": _sum_passport}


def _pre_cost_transcript(raw: bytes) -> bytes:
    """`transcript` is an absolute path to a file that is not packed here: its place is `<transcript:<session id>>`."""
    try:
        doc = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        return raw
    if isinstance(doc, dict) and "transcript" in doc:
        doc["transcript"] = f"<transcript:{doc.get('session_id') or 'unknown'}>"
        return json.dumps(doc, ensure_ascii=False).encode("utf-8")
    return raw


PRE = {"cost_transcript": _pre_cost_transcript}


# --- the run ------------------------------------------------------------------------------------------------------------

class _Run:
    def __init__(self, root, opts):
        self.opts = opts
        self.project = Path(root).resolve()
        self.home = self.project / runtime_paths.HOME
        self.now = opts["now"] or datetime.now(timezone.utc)
        self.git = opts["git"] or project_inventory._git
        self.members, self.rows, self.skipped, self.gaps, self.stories = [], [], [], [], []
        self.tmembers, self.packed_transcripts = [], {}      # H: the members of the transcripts file(s); path -> the entry of a transcript already packed
        self.doors = []                                      # (set, standard path) of each set whose data the config keeps elsewhere: the `--extra` door the summary prints
        self.new_files, self.new_events, self.arcs = {}, {}, set()
        self.counters = Counter()

    # -- small helpers --
    def gap(self, set_, what, why):
        self.gaps.append({"set": set_, "what": what, "why": why})

    def _arc(self, name: str) -> str:
        arc, n = self.red.member_name(name), 1
        base = arc
        while arc in self.arcs:
            n += 1
            arc = f"{base}~{n}"
        self.arcs.add(arc)
        return arc

    def _row(self, e, src_rel, mode, data, src_sha, key, flags=(), redactions=None, prefix=None, arc_name=None):
        arc = None
        if data:
            arc = self._arc(arc_name or f"{e['set']}/{src_rel}")
            (self.tmembers if e.get("transcript") else self.members).append((arc, data))
        row = {"arc": arc, "src_rel": src_rel, "set": e["set"], "mode": mode, "bytes": len(data or b""), "sha256": _sha(data) if data else None,
               "src_sha256": src_sha, "flags": list(flags), "redactions": redactions or {k: 0 for k in machine_facts.CATEGORIES}}
        if prefix:
            row["prefix"] = prefix
        self.rows.append(row)

    def _unchanged(self, e, src_rel, mode, key, size=0, entry=None):
        self.new_files[key] = entry
        self.rows.append({"arc": None, "src_rel": src_rel, "set": e["set"], "mode": mode, "bytes": 0, "sha256": None, "src_sha256": (entry or {}).get("sha256"),
                          "flags": ["unchanged"], "redactions": {k: 0 for k in machine_facts.CATEGORIES}})

    def _skip(self, e_set, src_rel, size, reason, **more):
        self.skipped.append({"src_rel": src_rel, "set": e_set, "bytes": size, "reason": reason, **more})

    @staticmethod
    def _load_loops(table):
        """The loop table, read ONCE in `start()` beside the sets: a table that cannot be read refuses the whole collect, before any
        story is read and outside `_stall`'s guard (which would turn the refusal into 'the story is stalled'). `table`: a test seam."""
        if table is not None:
            return table
        try:
            return collect_stall.load_loops()
        except ValueError as exc:
            raise Refused(f"COLLECT: the loop rules cannot be read ({exc}); {_REFUSAL_TAIL}") from None

    # -- reading the project --
    def start(self):
        o = self.opts
        if not self.home.is_dir():
            raise Refused(f"COLLECT: no qa-factory folder under {self.project}; run the skill from the project folder that holds "
                          "qa-factory/config.json, or pass --root <that folder>")
        self.sets = o["sets"] or load_sets()
        self.loops = self._load_loops(o["loops"])
        self.lim = self.sets["limits"]
        if o["part_max_bytes"]:
            self.lim = {**self.lim, "part_max_bytes": o["part_max_bytes"]}
        if o["file_max_bytes"]:
            self.lim = {**self.lim, "file_max_bytes": o["file_max_bytes"]}
        if o["since"] not in (None, "install"):
            raise Refused(f"COLLECT: --since takes the word install (pack everything since the install), not {o['since']!r}; "
                          "leave --since out to pack what is new since the factory last packed")
        cfg_path = self.home / "config.json"
        nothing = object()
        cfg = hooklib.read_json(cfg_path, nothing, errors=Exception, kind=dict)
        self.cfg_state = "ok" if cfg is not nothing else ("unreadable" if cfg_path.exists() else "absent")
        self.cfg = cfg if cfg is not nothing else {}
        self.onboarded = self.cfg_state != "absent"
        self._artifact_root()
        self._extras()
        self._identity()
        self._redactor()

    def _artifact_root(self):
        self.art_root = self.home / "artifacts"
        self.art_outside = False
        if self.cfg_state == "unreadable":
            self.gap("B", "artifact_root cannot be resolved", "qa-factory/config.json is not valid JSON: the standard artifacts folder is used")
            return
        try:
            root = hooklib.artifact_root(root=self.project)
        except Exception as exc:
            self.gap("B", "artifact_root cannot be resolved", f"the resolver refused it ({exc.__class__.__name__}): the standard artifacts folder is used")
            return
        self.art_root = root
        try:
            root.resolve().relative_to(self.project)
        except ValueError:
            self.art_outside = True

    def _extras(self):
        self.extra_files = []
        for set_, path in self.opts["extras"]:
            if set_ not in tuple(SET_LETTERS):
                raise Refused(f"COLLECT: --extra {set_}={path}: {set_!r} is not a set; expected A-H, e.g. --extra B=<path inside the project>")
            target = Path(path)
            target = (target if target.is_absolute() else self.project / target).resolve()
            is_art = self.art_outside and os.path.normcase(str(target)) == os.path.normcase(str(self.art_root.resolve()))
            if not is_art:
                try:
                    target.relative_to(self.project)
                except ValueError:
                    raise Refused(f"COLLECT: --extra {set_}={path} is outside the project folder {self.project}; only a path inside the "
                                  "project, or the folder artifact_root names, can be packed - move or copy it inside and pass --extra again") from None
            if not target.exists():
                raise Refused(f"COLLECT: --extra {set_}={path}: no such file or folder; pass the place the data really is, or leave --extra out")
            if is_art:
                self.art_ok = True
                continue
            for pat in self._secret_patterns():
                if re.search(pat, target.as_posix()):
                    raise Refused(f"COLLECT: --extra {set_}={path} matches the secret-file pattern {pat}; such a file is never packed - "
                                  "name another path or leave --extra out")
            base = target if target.is_dir() else target.parent
            for p in ([target] if target.is_file() else self._walk(target)):
                self.extra_files.append((set_, p, f"extra/{set_}/{p.relative_to(base).as_posix()}"))
        if self.art_outside and not getattr(self, "art_ok", False):
            raise Refused(f"COLLECT: artifact_root in qa-factory/config.json points outside the project ({self.art_root}); the stories kept "
                          f"there are packed only when you name that folder: pass --extra B={self.art_root} (the folder that holds the story folders)")

    def _secret_patterns(self):
        import guard_secrets
        return guard_secrets._patterns(self.cfg, "secret_file_patterns", list(guard_secrets.DEFAULT_SECRET_FILE_PATTERNS))

    @staticmethod
    def _walk(top: Path):
        out = []
        for cur, dirs, names in os.walk(top):
            dirs.sort()
            out += [Path(cur, n) for n in sorted(names)]
        return out

    def _git_out(self, *args):
        return self.git(self.project, *args)

    def _identity(self):
        code, top = self._git_out("rev-parse", "--show-toplevel")
        code2, remote = self._git_out("config", "--get", "remote.origin.url")
        self.git_state = "present" if code == 0 else ("absent" if code == 124 else "not_a_repository")
        remote = project_inventory._safe_remote(remote) if code2 == 0 else ""
        self.git_top = None
        if code == 0 and top:
            self.git_top = str(Path(top).resolve())
            try:
                rel = os.path.relpath(self.project, Path(top)).replace("\\", "/").strip("/")
            except ValueError:
                rel = self.project.as_posix().strip("/")
            rel = "" if rel == "." else rel
        else:
            rel = self.project.as_posix().strip("/")
        # F-6 / t-1043 F3: sha256(remote + "\n" + the folder's path from the git top)[:12]; with no remote the ABSOLUTE project path stands in its
        # place (sha256 of "" would be one id for every repository that has no origin), and the separator keeps "app"+"x" apart from "appx"+""
        self.project_id = _sha(((remote or self.project.as_posix()) + "\n" + rel).encode("utf-8"))[:12]
        self.legacy_project_id = _sha((remote + rel).encode("utf-8"))[:12]           # the formula of the marks written before this fix
        self.remote = remote
        self.mark_path = self.home / "state" / "collect" / "mark.json"
        mark = hooklib.read_json(self.mark_path, None, errors=Exception, kind=dict)
        self.prev, self.install_id, self.old_runs, self.previous = None, uuid.uuid4().hex, [], []
        self.first_run = True
        if self.mark_path.exists() and mark is None:
            self.gap("A", "the previous mark cannot be read", "state/collect/mark.json is not valid JSON; the window is everything since the install")
        elif isinstance(mark, dict):
            runs = mark.get("runs") if isinstance(mark.get("runs"), list) else []
            if not self._mark_is_ours(mark):
                self.previous = self._kept_marks(mark)
                self.gap("A", "the previous mark is not this project's", "it was written for another project folder, git checkout or machine (a copy of the project?); "
                         "the window is everything since the install and this installation gets a new install_id; the old mark is kept under previous")
            else:
                self.previous = [p for p in mark.get("previous") or [] if isinstance(p, dict)] if isinstance(mark.get("previous"), list) else []
                self.install_id = str(mark.get("install_id") or self.install_id)
                self.old_runs = [r for r in runs if isinstance(r, dict)]
                last = self.old_runs[-1] if self.old_runs else None
                when = _parse_time(last.get("collected_at")) if last else None
                if last and when and when > self.now:
                    self.gap("A", "the previous mark is dated in the future", "the clock moved back or the mark is not from this machine; the window is everything since the install")
                elif last and when and self.opts["since"] != "install" and isinstance(last.get("files"), dict):
                    self.prev, self.first_run = last, False
        self.prev_files = (self.prev or {}).get("files") or {}
        self.prev_events = (self.prev or {}).get("events") or {}
        self.since_at = (self.prev or {}).get("collected_at")

    def _mark_is_ours(self, mark) -> bool:
        """Was this mark born for THIS installation? The project_id alone is machine- and folder-independent when git has a remote, so a project
        copied together with its state/ would inherit the install_id (t-1043 F2): the mark also records the git top it was born under."""
        if mark.get("schema") != 1:
            return False
        if "git_top" not in mark:                  # a mark of the first generation (no git top): one time the same install, rewritten with the top
            return mark.get("project_id") in (self.project_id, self.legacy_project_id)
        was, now = mark.get("git_top"), self.git_top
        same_top = (was is None and now is None) or (isinstance(was, str) and now is not None and os.path.normcase(was) == os.path.normcase(now))
        return mark.get("project_id") == self.project_id and same_top

    @staticmethod
    def _kept_marks(mark) -> list:
        """The foreign mark as it is kept under `previous`: its identity and the run rows without the file tables, after the marks it already kept."""
        older = [p for p in mark.get("previous") or [] if isinstance(p, dict)] if isinstance(mark.get("previous"), list) else []
        runs = [{k: v for k, v in r.items() if k not in ("files", "events")} for r in (mark.get("runs") if isinstance(mark.get("runs"), list) else []) if isinstance(r, dict)]
        return older + [{**{k: v for k, v in mark.items() if k not in ("previous", "runs")}, "runs": runs}]

    def _redactor(self):
        if self.opts["redactor"] is not None:
            self.red = self.opts["redactor"]
            self.rules_sha = self.opts.get("rules_sha") or "injected"
            return
        try:
            rules = machine_facts.load_rules()
            ids = machine_facts.machine_identities(project_root=self.project)
            hosts = machine_facts.known_hosts(self.cfg, remotes=[self.remote], rules=rules)
            values, source_gaps = machine_facts.secret_values(self.cfg, os.environ, root=str(self.project))
            self.red = machine_facts.compile_redactor(
                rules, project_root=str(self.project), plugin_root=str(PACKAGE_ROOT), pythons=(sys.executable,), home=os.path.expanduser("~"),
                tmp=tempfile.gettempdir(), identities=ids, hosts=hosts, secret_values=values,
                config_patterns=[p for p in (self.cfg.get("secret_content_patterns") or []) if isinstance(p, str)], source_gaps=source_gaps)
            self.rules_sha = machine_facts.rules_sha256()
        except machine_facts.RulesUnreadable as exc:
            raise Refused(f"COLLECT: the packing rules {exc.path} cannot be read ({exc.why}); {_REFUSAL_TAIL}") from exc
        except machine_facts.PatternUnusable as exc:
            raise Refused(f"COLLECT: {exc}") from exc
        if self.cfg_state == "unreadable":
            self.gap("A", "the stand hosts of the config are not searched in plain text", "qa-factory/config.json is not valid JSON, so no host could be read from it; URLs are still hashed")
        for g in self.red.gaps:
            self.gap("A", g["what"], g["why"])

    # -- classification --
    def _entries(self):
        self._compiled = compile_entries(self.sets, self.onboarded)
        self._never = [_glob_re(n["glob"]) for n in self.sets["never_content"]]
        self._secret_rx = [re.compile(p) for p in self._secret_patterns()]

    def _match(self, scope, rel):
        return match_entry(self._compiled, scope, rel)

    def _is_never(self, scope, rel):
        return any(n.match(rel) for n in self._never)

    def collect_files(self):
        self._entries()
        groups, unknown = {}, []
        record_names = {}
        for e, _p in self._compiled:
            if e.get("record") and e["scope"] == "p":
                name = e["paths"][0].split("records/", 1)[-1]
                record_names[name] = e
        stories = []
        if self.art_root.is_dir():
            stories = [p for p in sorted(self.art_root.iterdir()) if p.is_dir() and not p.name.startswith(".")]
        self.touch = {s.name: self._touched(s) for s in stories}
        self.story_dirs = stories
        art = self.art_root.resolve()
        for dirpath, dirs, names in os.walk(self.home):
            here = Path(dirpath)
            dirs[:] = sorted(d for d in dirs if (here / d).resolve() != art)
            for n in sorted(names):
                self._classify("p", here / n, (here / n).relative_to(self.home).as_posix(), None, groups, unknown)
        for s in stories:
            if not self.touch[s.name]:
                continue
            for dirpath, dirs, names in os.walk(s):
                dirs.sort()
                for n in sorted(names):
                    p = Path(dirpath, n)
                    self._classify("h", p, p.relative_to(s).as_posix(), s.name, groups, unknown)
        self._records_winner(groups, record_names)
        for set_, p, rel in self.extra_files:
            self._classify_extra(set_, p, rel, groups)
        return groups, unknown

    def _classify(self, scope, path, rel, story, groups, unknown):
        src_rel = rel if scope == "p" else f"artifacts/{story}/{rel}"
        if scope == "p" and rel.startswith("state/collect/"):
            return
        e = self._match(scope, rel)
        if os.path.islink(path):
            self._skip(e["set"] if e else "A", src_rel, 0, "symlink: never followed")
            return
        if any(rx.search(src_rel) for rx in self._secret_rx):
            self._skip(e["set"] if e else "A", src_rel, self._size(path), "secret_file_pattern")
            return
        if e is None:
            if self._is_never(scope, rel):
                self._skip("A", src_rel, self._size(path), "never")
            elif self.onboarded:
                self._skip("A", src_rel, self._size(path), "unknown file")
            return
        if e["mode"] != "index" and e["mode"] != "skip" and self._is_never(scope, rel):
            self._skip(e["set"], src_rel, self._size(path), "never")
            return
        groups.setdefault((e["id"], story), (e, []))[1].append((path, rel, src_rel))

    def _classify_extra(self, set_, path, src_rel, groups):
        if os.path.islink(path):
            self._skip(set_, src_rel, 0, "symlink: never followed")
        elif any(rx.search(path.as_posix()) for rx in self._secret_rx):
            self._skip(set_, src_rel, self._size(path), "secret_file_pattern")
        elif self._is_never("p", path.relative_to(self.project).as_posix() if path.is_relative_to(self.project) else path.as_posix()) \
                or self._is_never("p", src_rel):
            self._skip(set_, src_rel, self._size(path), "never")
        else:
            e = {"id": f"extra-{set_}", "set": set_, "scope": "p", "mode": "copy", "nowindow": True}      # a place named by hand is packed WHOLE, never 'unchanged since the mark' (CL1-4 F1)
            groups.setdefault((e["id"], None), (e, []))[1].append((path, src_rel, src_rel))

    @staticmethod
    def _size(path):
        try:
            return os.stat(path).st_size
        except OSError:
            return 0

    def _records_winner(self, groups, record_names):
        for (eid, story), (e, files) in list(groups.items()):
            if not e.get("record") or e["scope"] != "p":
                continue
            name = e["paths"][0].split("records/", 1)[-1]
            winner = runtime_paths.record(self.project, name).resolve()
            keep = []
            for item in files:
                if item[0].resolve() == winner or len(files) == 1:
                    keep.append(item)
                else:
                    self._skip(e["set"], item[2], self._size(item[0]), "second copy of a record: the newer is taken")
            groups[(eid, story)] = (e, keep)

    def _touched(self, story: Path) -> bool:
        if self.first_run:
            return True
        keys = [f"artifacts/{story.name}/{rel}" for rel in HISTORY_FILES_THAT_TOUCH]
        for key in keys:
            p = story / key.split(f"artifacts/{story.name}/", 1)[1]
            m = self.prev_files.get(key)
            if not p.is_file():
                continue
            if m is None:
                return True
            if "bytes" in m:
                if p.stat().st_size != m["bytes"] or _stream_sha(p, m["bytes"])[0] != m.get("prefix_sha256"):
                    return True
            elif _stream_sha(p)[0] != m.get("sha256"):
                return True
        return not any(k in self.prev_files for k in keys)

    # -- the modes --
    def process(self, groups):
        order = {e["id"]: i for i, (e, _p) in enumerate(self._compiled)}
        for (eid, story), (e, files) in sorted(groups.items(), key=lambda kv: (order.get(kv[0][0], 10 ** 6), kv[0][1] or "")):
            files.sort(key=lambda t: t[2])
            mode = e["mode"]
            if mode == "skip":
                self._skip(e["set"], e.get("paths", [""])[0] if len(files) > 1 else files[0][2], sum(self._size(f[0]) for f in files), e.get("reason", "skipped"),
                           files=len(files))
            elif mode == "sum":
                self._do_sum(e, story, files)
            elif mode == "index":
                self._do_index(e, files)
            else:
                for path, rel, src_rel in files:
                    getattr(self, "_do_" + mode)(e, path, src_rel, story)

    def _redact(self, e, src_rel, raw: bytes, mode, src_sha, key, size, flags=(), mark_val=None, prefix=None):
        res = self.red.file(src_rel, raw)
        if res.status == "skipped":
            self._skip(e["set"], src_rel, size, res.reason)
            return False
        if res.status == "too_large" or (res.data and len(res.data) > self.lim["file_max_bytes"]):
            text = res.excerpt if res.excerpt is not None else self._excerpt(res.data)
            self._skip(e["set"], src_rel, size, "too_large", sha256=src_sha, lines=raw.count(b"\n") + 1, excerpt=text)
            return False
        self._row(e, src_rel, mode, res.data or b"", src_sha, key, [*flags, *(["empty"] if res.status == "empty" else [])], res.redactions, prefix)
        self.new_files[key] = mark_val if mark_val is not None else {"sha256": src_sha}
        return True

    def _excerpt(self, data: bytes) -> str:
        return self._excerpt_text(data[:1 << 20], data[-(1 << 20):])

    def _excerpt_text(self, head: bytes, tail: bytes) -> str:
        n = self.lim["excerpt_lines"]
        cut = lambda t: [ln[:EXCERPT_LINE_CHARS] for ln in t.decode("utf-8", "replace").split("\n")]    # noqa: E731
        lines = cut(head)[:n] + ["[... omitted ...]"] + cut(tail)[-n:]
        return self.red.lines("\n".join(lines))[0]

    def _oversize(self, e, path, src_rel, size, key=None):
        sha, lines = _stream_sha(path)
        with open(path, "rb") as f:
            head = f.read(1 << 20)
            f.seek(max(0, size - (1 << 20)))
            tail = f.read()
        self._skip(e["set"], src_rel, size, "too_large", sha256=sha, lines=lines + 1, excerpt=self._excerpt_text(head, tail))

    def _do_copy(self, e, path, src_rel, story):
        size = self._size(path)
        if size > self.lim["file_max_bytes"]:
            return self._oversize(e, path, src_rel, size)
        try:
            raw = path.read_bytes()
        except OSError:
            return self._skip(e["set"], src_rel, size, "unreadable")
        sha, mode = _sha(raw), e["mode"]
        if not e.get("nowindow") and (self.prev_files.get(src_rel) or {}).get("sha256") == sha:
            return self._unchanged(e, src_rel, mode, src_rel, entry={"sha256": sha})
        self._redact(e, src_rel, PRE[e["pre"]](raw) if e.get("pre") else raw, mode, sha, src_rel, size, flags=e.get("flags", ()))

    _do_new = _do_copy

    def _do_snapshots(self, e, path, src_rel, story):
        size = self._size(path)
        if size > self.lim["file_max_bytes"]:
            return self._oversize(e, path, src_rel, size)
        raw = path.read_bytes()
        sha = _sha(raw)
        doc = hooklib.read_json(path, None, errors=Exception, kind=dict)
        snaps = doc.get("snapshots") if isinstance(doc, dict) else None
        if not isinstance(snaps, list):
            return self._redact(e, src_rel, raw, "snapshots", sha, src_rel, size, flags=["shape_unknown"])
        since = _parse_time((self.prev or {}).get("metrics_history_last"))
        keep, last = [], (self.prev or {}).get("metrics_history_last")
        for s in snaps:
            when = _parse_time(s.get("generated_at")) if isinstance(s, dict) else None
            if since is None or when is None or when > since:
                keep.append(s)
        stamps = [(_parse_time(s.get("generated_at")), s.get("generated_at")) for s in keep if isinstance(s, dict) and _parse_time(s.get("generated_at"))]
        if stamps:
            last = max(stamps)[1]
        self.metrics_last = last
        if not keep and self.prev_files.get(src_rel):
            return self._unchanged(e, src_rel, "snapshots", src_rel, entry={"sha256": sha})
        body = json.dumps({**doc, "snapshots": keep}, ensure_ascii=False).encode("utf-8")
        self._redact(e, src_rel, body, "snapshots", sha, src_rel, size, flags=["snapshots:%d of %d" % (len(keep), len(snaps))])

    def _do_tail(self, e, path, src_rel, story):
        size, key = self._size(path), src_rel
        m, flags, start = self.prev_files.get(key), [], 0
        if m and "bytes" in m:
            if size >= m["bytes"] and _stream_sha(path, m["bytes"])[0] == m.get("prefix_sha256"):    # prefix check
                start = m["bytes"]
            else:
                flags.append("prefix_changed")
        if e.get("events") and story and start:
            want = self.prev_events.get(story)
            if want and not self._chain_ok(path, start, want):
                flags.append("chain_reset")
                start = 0
        if size - start > self.lim["file_max_bytes"]:
            return self._oversize(e, path, src_rel, size)
        with open(path, "rb") as f:
            f.seek(start)
            body = f.read()
        cut = body.rfind(b"\n")
        taken = body[: cut + 1] if cut >= 0 else b""
        if not taken:
            if m and not flags:
                return self._unchanged(e, src_rel, "tail", key, entry=m)
            if body:
                flags.append("partial_line_not_taken")
            self.new_files[key] = {"bytes": 0, "prefix_sha256": _sha(b"")}
            return self._row(e, src_rel, "tail", b"", _sha(b""), key, flags)
        boundary = start + len(taken)
        h = hashlib.sha256()
        if start:
            with open(path, "rb") as f:
                left = start
                while left:
                    chunk = f.read(min(1 << 20, left))
                    h.update(chunk)
                    left -= len(chunk)
        h.update(taken)
        entry = {"bytes": boundary, "prefix_sha256": h.hexdigest()}
        if e.get("events") and story:
            last = self._last_event(taken)
            if last:
                self.new_events[story] = last
        self._redact(e, src_rel, taken, "tail", h.hexdigest(), key, size, flags, entry, {"from": start, "to": boundary})

    def _chain_ok(self, path, upto, want) -> bool:
        with open(path, "rb") as f:
            text = f.read(upto).decode("utf-8", "replace")
        for line in text.split("\n"):
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if isinstance(ev, dict) and ev.get("sequence") == want.get("sequence"):
                return ev.get("event_hash") == want.get("event_hash")
        return False

    @staticmethod
    def _last_event(taken: bytes):
        best = None
        for line in taken.decode("utf-8", "replace").split("\n"):
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if isinstance(ev, dict) and isinstance(ev.get("sequence"), int) and (best is None or ev["sequence"] >= best["sequence"]):
                best = {"sequence": ev["sequence"], "event_hash": ev.get("event_hash")}
        return best

    def _do_sum(self, e, story, files):
        fn = SUMMARISERS[e["sum"]]
        doc = fn(self, [f[0] for f in files], e)
        self._land_summary(e, story, doc, files[0][2] if files else e["id"])

    def _land_summary(self, e, story, doc, src_rel):
        raw = json.dumps(doc, ensure_ascii=False, sort_keys=True).encode("utf-8")
        name = f"summaries/{e['set']}/{(story + '/') if story else ''}{e['id']}.json"
        key = f"sum:{name}"
        if not e.get("always") and (self.prev_files.get(key) or {}).get("sha256") == _sha(raw):
            return self._unchanged(e, name, "sum", key, entry={"sha256": _sha(raw)})
        res = self.red.file(name, raw)
        if res.status != "copied":
            return self._skip(e["set"], name, len(raw), res.reason or res.status)
        self._row(e, name, "sum", res.data, _sha(raw), key, [], res.redactions, arc_name=name)
        self.new_files[key] = {"sha256": _sha(raw)}

    def _do_index(self, e, files):
        rows = []
        for path, rel, src_rel in files:
            size = self._size(path)
            sha = _stream_sha(path)[0] if size <= self.lim["file_max_bytes"] else None
            rows.append({"path": self.red.text(src_rel)[0], "bytes": size, "sha256": sha, "flags": [] if sha else ["not_hashed"]})
        story = files[0][2].split("/")[1] if files and files[0][2].startswith("artifacts/") else None
        self._land_summary({**e, "id": e["id"] + "-index"}, story, {"files": len(rows), "bytes": sum(r["bytes"] for r in rows), "index": rows}, "")

    # -- the passport (set A) --
    def passport(self):
        if not hasattr(self, "_passport"):
            self._passport = self._build_passport()
        return self._passport

    def _build_passport(self):
        carriers = hooklib.version_carriers(self.project)
        ready = hooklib.read_json(runtime_paths.readiness(self.project), {}, errors=Exception, kind=dict)
        rt = ready.get("runtime_paths") if isinstance(ready.get("runtime_paths"), dict) else {}
        repos = []
        try:
            inv = project_inventory.build_inventory(self.cfg, self.project)
            repos = [{k: r.get(k) for k in ("repo_id", "roles", "presence", "git_state", "git_status", "status", "remote_identity")} for r in inv["repositories"]]
        except Exception as exc:
            self.gap("A", "the repository inventory could not be built", f"{exc.__class__.__name__}")
        return {"onboarded": self.onboarded, "config": self.cfg_state,
                "versions": {k: {"version": v.get("version"), "state": v.get("state")} for k, v in carriers.items()},
                "running_plugin_is_frozen_copy": carriers["running"].get("frozen"),
                "readiness": {"package_version": rt.get("package_version"), "package_fingerprint": rt.get("package_fingerprint"),
                              "host": (ready.get("host_integration") or {}).get("host") if isinstance(ready.get("host_integration"), dict) else None},
                "os": platform.platform(), "python": platform.python_version(), "git": self.git_state,
                "repositories": repos, "install_date": self.install_date(), "package_modified": self.pm}

    def install_date(self):
        stamps = []
        try:
            for line in runtime_paths.record(self.project, "onboarding-approvals.jsonl").read_text(encoding="utf-8").split("\n"):
                try:
                    stamp = json.loads(line).get("recorded_at")
                except (ValueError, AttributeError):
                    continue
                if _parse_time(stamp):
                    stamps.append(str(stamp))
        except OSError:
            pass
        if stamps:
            return {"value": min(stamps), "source": "earliest onboarding approval"}
        retired = runtime_paths.state_root(self.project) / "retired"
        days = sorted(p.name for p in retired.iterdir()) if retired.is_dir() else []
        return {"value": days[0], "source": "earliest retired folder"} if days else {"value": None, "source": "not known"}

    def package_modified(self):
        try:
            import release_fingerprint
        except ImportError:
            return {"package_modified": "unknown", "why": "fingerprint_unavailable"}
        try:
            got = release_fingerprint.compare(PACKAGE_ROOT)
            return {"package_modified": got.get("package_modified", "unknown"), "why": got.get("why"), "detail": {k: v for k, v in got.items() if k not in ("package_modified", "why")}}
        except Exception as exc:
            return {"package_modified": "unknown", "why": f"compare_failed:{exc.__class__.__name__}"}

    def fingerprint(self):
        try:
            import release_fingerprint
            return release_fingerprint.package_fingerprint(PACKAGE_ROOT)
        except ImportError:
            pass
        except Exception:
            return None
        try:
            import install_smoke
            return install_smoke.package_fingerprint()
        except Exception:
            return None

    def answers(self):
        out, o = {}, self.opts
        for name, file in (("problems", o["problems_file"]), ("suggestions", o["suggestions_file"])):
            if file is None:
                out[name] = {"state": "not_asked" if o["not_asked"] else "blank", "arc": None}
                continue
            if _is_blank_file(file):
                out[name] = {"state": "blank", "arc": None}         # L-2 m5: a named file with no words is a blank answer here (person_words refuses it)
                continue
            try:
                text = person_words.read(None, str(file), f"--{name}-file")    # the ONE reader of a person's words (t-962 section 6 step 4)
            except person_words.WordsRefused as exc:
                raise Refused(f"COLLECT: the {name} answers file was refused: {_option_named(exc, name)}") from None
            res = self.red.file(f"answers/{name}.txt", text.encode("utf-8"))
            if res.status != "copied":          # an answer is never recorded as given while its words are dropped (t-1043 F4)
                raise Refused(f"COLLECT: the {name} answers file {file} was not packed ({res.reason or res.status}); its words would be lost - "
                              f"shorten it or pass a plain text file, or leave --{name}-file out to record that no answer was given; nothing was written")
            arc = self._arc(f"answers/{name}.txt")
            self.members.append((arc, res.data))
            self.rows.append({"arc": arc, "src_rel": f"answers/{name}.txt", "set": "A", "mode": "copy", "bytes": len(res.data), "sha256": _sha(res.data),
                              "src_sha256": _sha(text.encode("utf-8")), "flags": ["answer"], "redactions": res.redactions})
            out[name] = {"state": "answered", "arc": arc}
        return out

    # -- the whole job --
    def execute(self):
        self.start()
        pm = self.pm = self.package_modified()
        groups, _unknown = self.collect_files()
        groups.setdefault(("A1", None), ({**next(e for e in self.sets["entries"] if e["id"] == "A1")}, []))
        self.process(groups)
        self.answers_doc = self.answers()
        self._said_by_the_skill()
        story_list = self._stories()
        self._gaps_for_sets(story_list)
        self._carry_untouched()
        return pm, story_list

    def _said_by_the_skill(self):
        """What only the skill's agent could see, carried as a gap line of the manifest (CL1-4 F9, F10): the packer does not guess it."""
        if self.opts["activity_not_recorded"]:
            self.gap("A", "the skill's activity was not recorded",
                     "qa-collect step 1 printed ACTIVITY NOT RECORDED (the host session could not be identified): this run's spend is not tagged as Collect")
        if self.opts["answers_not_split"]:
            self.gap("A", "answers not split; kept whole as problems",
                     "the person's text did not divide into the two questions: it is the whole problems answer "
                     f"(state: {self.answers_doc['problems']['state']}) and the suggestions answer is {self.answers_doc['suggestions']['state']}")

    def _carry_untouched(self):
        for story in self.story_dirs:
            if not self.touch[story.name]:
                prefix = f"artifacts/{story.name}/"
                self.new_files.update({k: v for k, v in self.prev_files.items() if k.startswith(prefix)})
                if story.name in self.prev_events:
                    self.new_events[story.name] = self.prev_events[story.name]
        for T, ev in self.prev_events.items():
            self.new_events.setdefault(T, ev)

    def _stories(self):
        out, mark, quiet = [], (self.prev or {}).get("collected_at"), self._quiet_hours()
        for story in self.story_dirs:
            pipeline = hooklib.read_json(story / "pipeline.json", {}, errors=Exception, kind=dict)
            item = {"task": story.name, "plugin_version": story_version.plugin_version_of(pipeline) or None, "touched": self.touch[story.name],
                    "closed_at": hooklib.story_closed(pipeline) or None, "stalled": None, "stall_signals": [], "looped": None, "loop_signals": [], "transcripts": [], "record": None}
            if self.onboarded:          # B-H are skipped for a project that is not onboarded (set_status says so); H does not pack transcripts the sets deny
                self._stall(story, item, mark, quiet)
            out.append(item)
        return out

    # -- H: the stall verdict of a story and the transcripts that go with a stalled one --
    def _quiet_hours(self):
        """`collect.stall_quiet_hours` of the project's config; a config written before the key existed (or a null) gets the rule's own
        default (t-962 section 5, 24). A value the rule cannot use (its own predicate `_quiet_seconds`: not a number, negative, not finite,
        or a config that cannot be read at all) gets the same default and ONE gap line of H that says so: the key has a declared default, so
        a wrong value must not turn every story into 'unknown' and pack every transcript (FR-59, CL1-4 F3). The rule itself stays strict."""
        block = self.cfg.get("collect")
        value = block.get("stall_quiet_hours") if isinstance(block, dict) else None
        default = collect_stall.DEFAULT_QUIET_HOURS
        if value is None and self.cfg_state != "unreadable":
            return default
        if collect_stall._quiet_seconds(value) is not None:
            return value
        why = ("qa-factory/config.json is not valid JSON, so collect.stall_quiet_hours could not be read" if value is None and self.cfg_state == "unreadable"
               else f"collect.stall_quiet_hours is {value!r:.60}, which is not a number of hours >= 0")
        self.gap("H", f"config: stall_quiet_hours unreadable, default {default:g} used", f"{why}; the stall verdicts were drawn with {default:g} hours")
        return default

    def _host_subagents(self):
        """hooklib's host-wide subagent list, read ONCE per run (it walks every cost file); `select_transcripts` cuts it per story."""
        if not hasattr(self, "_subagent_paths"):
            self._subagent_paths = hooklib.story_subagent_transcripts(self.project)
        return self._subagent_paths

    def _stall(self, story, item, mark, quiet):
        try:
            verdict = collect_stall.stall(self.project, story, mark, self.now.timestamp(), quiet, self.loops)
        except Exception as exc:        # built not to raise; if it does, the story is UNKNOWN - never "fine", and the safe side is its transcripts (FR-59)
            verdict = {"stalled": True, "current": False, "record": None, "looped": None,
                       "signals": [{"id": collect_stall.UNREADABLE, "where": f"the stall rule stopped ({type(exc).__name__})", "at": None}]}
        signals = [s for s in verdict.get("signals") or [] if isinstance(s, dict)]
        item["stall_signals"] = [{"id": s.get("id"), "where": s.get("where"), "at": _iso_epoch(s.get("at"))} for s in signals]
        item["record"] = verdict.get("record")
        unknown = bool(signals) and all(s.get("id") == collect_stall.UNREADABLE for s in signals) and not verdict.get("current")
        item["stalled"] = None if verdict.get("stalled") and unknown else bool(verdict.get("stalled"))
        item["looped"] = verdict.get("looped")
        item["loop_signals"] = [{"id": s.get("id"), "where": s.get("where"), "at": _iso_epoch(s.get("at"))}
                                for s in verdict.get("loop_signals") or [] if isinstance(s, dict)]
        if item["looped"] is None and not verdict.get("stalled") and verdict.get("loop_unreadable_reasons"):
            self.gap("H", f"loops of {story.name} unknown", "; ".join(str(r) for r in verdict["loop_unreadable_reasons"]))
        if collect_stall.wants_transcripts(verdict):
            self._pack_transcripts(story, verdict, item)

    def _pack_transcripts(self, story, verdict, item):
        task = story.name
        sessions = collect_stall.session_transcripts(self.project, story)
        got = collect_stall.select_transcripts(verdict, sessions, self._host_subagents())
        for g in got["gaps"]:
            self.gap("H", f"the transcript of session {g['sid']} of {task} is not packed" if g.get("sid") else f"the sessions of {task} could not all be read",
                     str(g.get("why")))
        if not (got["main"] or got["subagents"] or got["gaps"]):
            state = {(True, True): "stalled and looping", (True, False): "stalled", (False, True): "looping"}.get(
                (bool(verdict.get("stalled")), verdict.get("looped") is True), "possibly looping")
            self.gap("H", f"no transcripts for the {state} story {task}", str(got["why"]))
        e = {"id": "H-transcripts", "set": "H", "scope": "p", "mode": "copy", "transcript": True, "flags": ["transcript"]}
        sid_of = {str(s["transcript"]): s.get("sid") for s in sessions if s.get("transcript")}
        for path in got["main"]:
            sid = sid_of.get(path) or Path(path).stem
            self._transcript(e, item, task, Path(path), f"transcripts/{task}/{sid}.jsonl", sid, "main")
        for path in got["subagents"]:
            p = Path(path)
            self._transcript(e, item, task, p, f"transcripts/{task}/{p.parent.parent.name}/subagents/{p.name}", p.parent.parent.name, "subagent")

    def _transcript(self, e, item, task, path, src_rel, sid, kind):
        """One transcript into the transcripts file as a `copy` (through the redactor, the file ceiling, `unchanged` since the mark). The
        row's `src_rel` is a LOGICAL name, never the host path. A file two stories share (one interactive session) is packed once."""
        key = os.path.normcase(str(path))
        if key in self.packed_transcripts:
            item["transcripts"].append({**self.packed_transcripts[key], "shared_with": self.packed_transcripts[key]["task"]})
            return
        rows, skipped = len(self.rows), len(self.skipped)
        self._do_copy(e, path, src_rel, task)
        entry = {"sid": sid, "kind": kind, "task": task, "src_rel": src_rel, "arc": None}
        if len(self.rows) > rows:
            r = self.rows[-1]
            entry.update(arc=r["arc"], bytes=r["bytes"], sha256=r["sha256"], flags=r["flags"])
        elif len(self.skipped) > skipped:
            entry["skipped"] = self.skipped[-1]["reason"]
        self.packed_transcripts[key] = entry
        item["transcripts"].append(entry)

    def _gaps_for_sets(self, stories):
        if not self.onboarded:
            for s in "BCDEFGH":
                self.gap(s, f"{s}: nothing collected", "not onboarded: qa-factory/config.json is absent")
        for e, _p in self._compiled:
            if e.get("cfg_key") and self.cfg.get(e["cfg_key"]):
                target = runtime_paths.configured(self.project, self.cfg[e["cfg_key"]], Path(e["paths"][0]).name)
                try:
                    target.resolve().relative_to(self.home.resolve())
                except ValueError:
                    self.gap(e["set"], f"{e['set']}: {e['paths'][0]} not found at the standard place",
                             f"the config key {e['cfg_key']} names another place; pass it with --extra {e['set']}=<path>")
                    if e["set"] not in [s for s, _p in self.doors] and e["set"] not in [s for s, _p in self.opts["extras"]]:    # a set already given by hand is not asked again
                        self.doors.append((e["set"], e["paths"][0]))
        if stories:
            self.gap("F", "missed bugs", "no carrier records bugs the factory missed (escape-ledger.jsonl has no writer)")
            for s in stories:
                if s["touched"] and not (self.art_root / s["task"] / "retro.md").is_file():
                    self.gap("F", f"retro absent for {s['task']}", "the history did not reach S9")

    def set_status(self, pm):
        out = {}
        for s in SET_LETTERS:
            rows = [r for r in self.rows if r["set"] == s]
            gaps = [g for g in self.gaps if g["set"] == s]
            kept = [r for r in rows if r["mode"] in ("copy", "tail", "new", "snapshots") or r["flags"] == ["unchanged"]]
            if not self.onboarded and s != "A":
                status, note = "gap", (gaps[0]["why"] if gaps else "nothing collected")
            elif kept:
                status, note = "collected", f"{len(rows)} entries"
            elif rows:
                status, note = "summarised", f"{len(rows)} entries"
            elif gaps:
                status, note = "gap", gaps[0]["why"]
            else:
                status, note = "empty", "nothing recorded for this set"
            out[s] = {"status": status, "note": note + (f"; {len(gaps)} gap(s)" if gaps and status != "gap" else "")}
        return out


# --- parts, manifest, writing -------------------------------------------------------------------------------------------

def _deflated(data: bytes) -> int:
    co = zlib.compressobj(zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -15)
    return len(co.compress(data)) + len(co.flush())


def _cost(name: str, size: int) -> int:
    nb = len(name.encode("utf-8"))
    return ZIP_LOCAL + nb + size + ZIP_CENTRAL + nb


def _upper(name: str, data: bytes) -> int:
    return _cost(name, len(data) + 5 * (len(data) // 16383 + 1) + 16)


def plan_parts(members, manifest_for, limit: int):
    """Which member goes into which part, with every part (manifest included) at most `limit` bytes. members = [(arc, bytes)] without the
    manifest; manifest_for(parts_rows) -> bytes. Part 1 holds the manifest first, so it is planned last-in-mind: a single part is
    tested exactly (the manifest has no parts to list), several parts reserve an upper bound of the manifest that lists them."""
    costs = [_cost(a, _deflated(d)) for a, d in members]
    manifest = manifest_for([])
    if ZIP_END + _cost("manifest.json", _deflated(manifest)) + sum(costs) <= limit:
        return [list(range(len(members)))]
    n = 2
    for _ in range(12):
        reserve = _upper("manifest.json", manifest_for([{"name": "qa-collect-" + "0" * 40 + "-part9.zip", "sha256": "0" * 64, "bytes": limit}] * (n - 1)))
        parts, used, budget = [[]], ZIP_END + reserve, limit
        for i, cost in enumerate(costs):
            if used + cost > budget and parts[-1]:
                parts.append([])
                used = ZIP_END
            parts[-1].append(i)
            used += cost
        if len(parts) == n:
            return parts
        n = len(parts)
    raise Refused("COLLECT: internal error: the parts could not be planned; report this message to the QA factory developers")


def plan_transcript_parts(members, limit: int):
    """Which transcript goes into which file of the transcripts set, each at most `limit` bytes deflated (no manifest in them; a member
    that is alone over the limit stands alone - the 16 MiB file ceiling keeps that from happening)."""
    parts, used = [], 0
    for i, (arc, data) in enumerate(members):
        cost = _cost(arc, _deflated(data))
        if not parts or used + cost > limit - ZIP_END:
            parts.append([])
            used = 0
        parts[-1].append(i)
        used += cost
    return parts


def _write_zip(path: Path, members, when: datetime) -> None:
    """Written to `<name>.part` and moved into place at the end: a failed write (a full disk) leaves no `.zip` for anyone to mistake for an archive (t-1043 F5)."""
    stamp = (max(when.year, 1980), when.month, when.day, when.hour, when.minute, when.second)
    tmp = path.with_name(path.name + ".part")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in members:
                info = zipfile.ZipInfo(name, stamp)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                zf.writestr(info, data)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _free_base(out_dir: Path, base: str) -> str:
    """The archive name nobody has taken: `base`, then `base-2`, `base-3` ... An earlier archive is never overwritten (t-1043 F1, L-2 F-7)."""
    name, n = base, 1
    while (out_dir / f"{name}.zip").exists() or any(out_dir.glob(f"{name}-part*.zip")) or any(out_dir.glob(f"{name}-transcripts*.zip")):
        n += 1
        name = f"{base}-{n}"
    return name


def _temp_reason(run, out_dir: Path):
    rel = out_dir.relative_to(run.project).as_posix()
    code, _o = run.git(run.project, "check-ignore", "-q", rel + "/")
    if code == 0:
        return None
    return {1: f"git does not ignore {rel} (no .gitignore line covers state/), so the archive would show as untracked money data",
            128: "the project is not a git repository, so nothing says the folder is ignored",
            124: "git could not be run, so nothing says the folder is ignored"}.get(code, f"git check-ignore answered {code}")


def pack(root, *, problems_file=None, suggestions_file=None, not_asked=False, extras=(), since=None, now=None, git=None, redactor=None,
         sets=None, loops=None, part_max_bytes=None, file_max_bytes=None, temp_root=None, rules_sha=None, activity_not_recorded=False, answers_not_split=False) -> dict:
    """Pack the project under `root` (the folder that holds qa-factory/). Returns the result (see summary_lines); raises Refused.
    `activity_not_recorded` / `answers_not_split` are what the skill's agent saw and the packer cannot: each becomes a gap line of the manifest.
    Seams for tests: now, git (a runner like project_inventory._git), redactor, sets, loops (a loop table), part_max_bytes, file_max_bytes, temp_root."""
    opts = {"problems_file": problems_file, "suggestions_file": suggestions_file, "not_asked": not_asked, "extras": list(extras), "since": since,
            "now": now, "git": git, "redactor": redactor, "sets": sets, "loops": loops, "part_max_bytes": part_max_bytes, "file_max_bytes": file_max_bytes,
            "rules_sha": rules_sha, "activity_not_recorded": activity_not_recorded, "answers_not_split": answers_not_split}
    run = _Run(root, opts)
    pm, stories = run.execute()
    when = run.now
    stamp = when.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    arch = run.sets["archive"]
    out_dir = run.home / arch["out_folder"]
    why_temp = _temp_reason(run, out_dir)
    if why_temp:
        out_dir = Path(temp_root or tempfile.gettempdir()) / arch["temp_folder"]
    base = _free_base(out_dir, f"{arch['prefix']}-{run.install_id[:8]}-{stamp}")
    limit = run.lim["part_max_bytes"]
    static = {"schema": SCHEMA, "project_id": run.project_id, "install_id": run.install_id, "collected_at": _iso(when),
              "collector": {"package_version": run.passport()["versions"]["running"]["version"], "package_fingerprint": run.fingerprint()},
              "package_modified": pm["package_modified"], "package_modified_why": pm.get("why"), "package_modified_detail": pm.get("detail"),
              "window": {"since_archive": (run.prev or {}).get("archive") or "install", "since_at": run.since_at if run.prev else None, "until_at": _iso(when),
                         "rule": "new since the factory last packed them; --since install packs everything again"},
              "host": (run.passport()["readiness"]["host"]), "os": platform.platform(), "python": platform.python_version(), "sets": run.set_status(pm),
              "delivery": {"location": "temp" if why_temp else "project_state", "reason": why_temp, "mark": "qa-factory/state/collect/mark.json",
                           "note": "the mark sits in the project's state/ folder" + (" and git does not ignore it" if why_temp else "")},
              "redaction_rules_sha256": run.rules_sha}

    trows, written = [], []         # trows: the transcripts files, written FIRST so the manifest (and its size plan) can list them

    def manifest_for(parts):
        doc = {**static, "files": run.rows, "skipped": run.skipped, "gaps": run.gaps, "stories": stories, "answers": run.answers_doc,
               "parts": parts + trows, "part_count": len(parts) + len(trows) + 1}
        return _manifest_bytes(run, doc)

    try:
        for number, idxs in enumerate(plan_transcript_parts(run.tmembers, limit)):
            part = out_dir / (f"{base}-transcripts.zip" if number == 0 else f"{base}-transcripts-part{number + 1}.zip")
            out_dir.mkdir(parents=True, exist_ok=True)
            _write_zip(part, [run.tmembers[i] for i in idxs], when)
            written.append(part)
            trows.append({"name": part.name, "sha256": hashlib.sha256(part.read_bytes()).hexdigest(), "bytes": part.stat().st_size, "kind": "transcripts"})
        plan = plan_parts(run.members, manifest_for, limit)
        rows = []
        for idx in range(1, len(plan)):
            part = out_dir / (f"{base}-part{idx + 1}.zip")
            out_dir.mkdir(parents=True, exist_ok=True)
            _write_zip(part, [run.members[i] for i in plan[idx]], when)
            written.append(part)
            rows.append({"name": part.name, "sha256": hashlib.sha256(part.read_bytes()).hexdigest(), "bytes": part.stat().st_size})
        first = out_dir / f"{base}.zip"
        out_dir.mkdir(parents=True, exist_ok=True)
        _write_zip(first, [("manifest.json", manifest_for(rows))] + [run.members[i] for i in plan[0]], when)
        written.insert(0, first)
        _verify(run, written, rows)
        sha1 = hashlib.sha256(first.read_bytes()).hexdigest()
        _write_mark(run, first, sha1, rows + trows, stories)
    except BaseException:
        for p in written:
            p.unlink(missing_ok=True)
        raise
    return {"archive": str(first), "parts": [str(p) for p in written], "transcript_parts": [r["name"] for r in trows],
            "bytes": sum(p.stat().st_size for p in written), "location": static["delivery"]["location"],
            "reason": why_temp, "sets": static["sets"], "gaps": len(run.gaps), "extra_doors": [list(d) for d in run.doors],
            "skipped": len(run.skipped), "files": len(run.rows),
            "stories": stories, "unchanged": sum(1 for r in run.rows if "unchanged" in r["flags"]), "window": static["window"],
            "package_modified": pm["package_modified"], "project_id": run.project_id, "install_id": run.install_id}


def _manifest_bytes(run, doc) -> bytes:
    """Every string of the manifest passes the redactor (a src_rel may carry a name); keys stay, they are the schema or story keys."""
    def walk(node):
        if isinstance(node, str):
            return run.red.text(node)[0]
        if isinstance(node, list):
            return [walk(x) for x in node]
        if isinstance(node, dict):
            return {k: (v if k in ("sha256", "src_sha256", "arc", "name") else walk(v)) for k, v in node.items()}
        return node
    return json.dumps(walk(doc), ensure_ascii=False, indent=1).encode("utf-8")


def _kind(name: str) -> str:
    """The kind `residue_document` reads a member as, from the member's suffix: json, jsonl (.jsonl, .ndjson), anything else text."""
    low = name.lower()
    return "json" if low.endswith(".json") else "jsonl" if low.endswith((".jsonl", ".ndjson")) else "text"


def _verify(run, written, parts):
    """Read the archive back: every member hashes as the manifest says, the parts hash as listed, and the post-check finds nothing (I2)."""
    manifest, seen = None, {}
    for part in written:
        with zipfile.ZipFile(part) as zf:
            for info in zf.infolist():
                data = zf.read(info.filename)
                if info.filename == "manifest.json":
                    manifest = json.loads(data.decode("utf-8"))
                else:
                    seen[info.filename] = _sha(data)
                # the units the filter itself works on (a JSON string or key, a JSONL line, a text line): `residue_document` is the one leaf
                # reader, and it reads a key as the writer does (the escaped text of a whole JSON file reads `\\.env\\.` as a UNC path)
                found = run.red.residue(info.filename, _first=True) or run.red.residue_document(data.decode("utf-8", "replace"), _kind(info.filename), _first=True)
                if found:
                    raise Refused(f"COLLECT: the packed data still carries {found[0]['category']} data after redaction (member {run.red.member_name(info.filename)}, "
                                  f"finder {found[0]['finder']}); nothing was kept and the mark did not move. This is a defect of the packing rules, not of your "
                                  "data: update the plugin and collect again, and if it repeats send this message (it carries no value) to the QA factory developers")
    bad = [r["arc"] for r in manifest["files"] if r["arc"] and seen.get(r["arc"]) != r["sha256"]] if manifest else ["manifest.json"]
    listed = {p["name"]: p["sha256"] for p in (manifest or {}).get("parts", [])}
    bad += [p.name for p in written[1:] if listed.get(p.name) != hashlib.sha256(p.read_bytes()).hexdigest()]
    if bad:
        raise Refused(f"COLLECT: the archive written does not match its manifest (first member: {bad[0]}); nothing was kept and the mark did not move; "
                      "collect again, and if it repeats send this message to the QA factory developers")


def _write_mark(run, first: Path, sha1: str, parts, stories):
    run_row = {"archive": first.name, "sha256": sha1, "collected_at": _iso(run.now), "package_version": run.passport()["versions"]["running"]["version"],
               "parts": parts, "files": run.new_files, "events": run.new_events,
               "metrics_history_last": getattr(run, "metrics_last", (run.prev or {}).get("metrics_history_last"))}
    kept = [{k: v for k, v in r.items() if k not in ("files", "events")} for r in run.old_runs]       # only runs[-1] is read: older ones keep their identity
    mark = {"schema": 1, "project_id": run.project_id, "install_id": run.install_id, "git_top": run.git_top, "runs": kept + [run_row]}
    if run.previous:
        mark["previous"] = run.previous             # the marks of other installations this one found in its state/ (a copied project)
    run.mark_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = run.mark_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(mark, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, run.mark_path)


def summary_lines(result: dict) -> list:
    """What the person is told (at most 12 lines, FR-37: the real path)."""
    mb = result["bytes"] / 1_000_000
    lines = [f"Packed the factory's records into {result['archive']}", f"Size: {mb:.2f} MB in {len(result['parts'])} file(s); {result['files']} entries, "
             f"{result['unchanged']} unchanged since the last packing"]
    if result["location"] == "temp":
        lines.append(f"Written to the temp folder, not the project: {result['reason']}")
    win = result["window"]
    lines.append(f"Window: {'everything since the install' if win['since_archive'] == 'install' else 'new since ' + win['since_archive']} "
                 "(an archive you did not send stays on disk; --since install packs everything again)")
    lines.append(f"Gaps named: {result['gaps']}; files skipped with a reason: {result['skipped']}; transcripts: {sum(len(s['transcripts']) for s in result['stories'])}")
    tnames = list(result.get("transcript_parts") or [])
    main_parts = [Path(p).name for p in result["parts"] if Path(p).name not in tnames]
    if len(main_parts) > 1:
        lines.append("Send all parts together: " + ", ".join(main_parts))
    if tnames:       # t-962 F-5 (i) and L-2 F-2: its own file, so that deleting it is the person's choice; the main transcript carries other work too
        lines.append("Transcripts of the stories that stalled or looped (the agents' conversations; your own session's transcript also carries your other work) are in "
                     + ", ".join(tnames) + "; delete that file if you do not want to send it.")
    tail = ["Package modified: " + result["package_modified"], "Send the file to the QA factory developers; delete it if you do not want to send it."]
    # CL1-4 F1: the door is in the OUTPUT the skill's agent reads, one line per set (the manifest alone is never read by it); when the 12 lines
    # have no room for all of them the rest is one line that still names every set, and the closing two lines stay.
    doors = [f"{s}: not found at the standard place ({p}) - pass --extra {s}=<path inside the project> and run it again" for s, p in result.get("extra_doors") or []]
    room = 12 - len(lines) - len(tail)
    if len(doors) > room:
        rest = [d.split(":", 1)[0] for d in doors[max(room - 1, 0):]]
        doors = doors[:max(room - 1, 0)] + [f"{', '.join(rest)}: not found at the standard place - pass --extra <SET>=<path inside the project> for each and run it again"]
    return (lines + doors + tail)[:12]


def main(argv=None, **seams) -> int:
    """The command the qa-collect skill runs. 0 packed; 1 a refusal (FR-1 form, nothing written, the mark did not move); 2 a usage error
    (argparse). `seams` are `pack()`'s test seams. A person's answers come ONLY as files (`person_words.read`); with no file the answer
    is `blank`, and `--not-asked` says no person was there to ask (headless): `not_asked`."""
    ap = argparse.ArgumentParser(prog="collect_pack.py", description="Pack the factory's records of this project into one archive for the QA factory developers.")
    ap.add_argument("--root", default=".", help="the project folder (the one that holds qa-factory/config.json)")
    ap.add_argument("--problems-file", default=None, help="a file holding the person's answer about problems, exactly as given")
    ap.add_argument("--suggestions-file", default=None, help="a file holding the person's answer about what to improve, exactly as given")
    ap.add_argument("--not-asked", action="store_true", help="no person was there to ask: an answer with no file is recorded as not_asked, not blank")
    ap.add_argument("--extra", action="append", default=[], metavar="SET=PATH", help="a place inside the project that a set lives at (after 'not found at the standard place')")
    ap.add_argument("--since", default=None, help="only 'install': pack everything since the install, not what is new")
    ap.add_argument("--activity-not-recorded", action="store_true", help="the skill's start step printed ACTIVITY NOT RECORDED: the manifest says so in a gap line")
    ap.add_argument("--answers-not-split", action="store_true", help="the person's one text did not divide into the two questions and went whole into --problems-file: the manifest says so")
    ap.add_argument("--json", action="store_true", help="print the result as JSON, with the summary lines inside it")
    args = ap.parse_args(argv)
    try:
        extras = []
        for raw in args.extra:
            set_, sep, path = raw.partition("=")
            if not (sep and set_ and path):
                raise Refused(f"COLLECT: --extra {raw}: expected SET=path, for example --extra B=<path inside the project>, where A-H names the set the place belongs to")
            extras.append((set_, path))
        result = pack(args.root, problems_file=args.problems_file, suggestions_file=args.suggestions_file, not_asked=args.not_asked, extras=extras,
                      since=args.since, activity_not_recorded=args.activity_not_recorded, answers_not_split=args.answers_not_split, **seams)
    except Refused as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    except Exception as exc:             # P2 / FR-59: never a traceback for a person; pack() removes what it wrote and the mark moves last
        print(f"COLLECT: stopped by an unexpected error ({type(exc).__name__}: {str(exc)[:200]}); nothing was kept and the mark did not move; "
              "run it again, and if it repeats send this message to the QA factory developers", file=sys.stderr)
        return 1
    lines = summary_lines(result)
    print(json.dumps({**result, "summary": lines}, ensure_ascii=False, indent=1) if args.json else "\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
