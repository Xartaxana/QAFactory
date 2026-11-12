#!/usr/bin/env python3
"""The person's word about sources, given BEFORE the run: which sources the factory must not read.

    source_exclusions.py --task T --load FILE       orchestrator only: read the person's list
    source_exclusions.py --task T --show            print the record (open to every role)
    source_exclusions.py --task T --revoke <X-id|as_written> --words "<their words>"
                                                    orchestrator only: the person takes one back

The list is a plain-text file, one source per line: the source, then a dash and why it is left out
(`testproject1-ui!1924 - Draft MR of an earlier factory run, not a product change`). The record lives at
`work/source-exclusions.json` of the story and is written only here (`--load`), before the source
inventory exists: a source already read is never "left out" afterwards. `source_inventory.py` reads
the record on every inventory write and marks what matches; `ticket_adapter.py collect|peek` and
`inspect --media-url` refuse what matches. TP1-15045 (judge run, 23.09): the scout read a draft MR of
an earlier factory run, cited it as a requirement source and as existing coverage for six criteria.

Target kinds (`target.kind`):
  ticket  a Jira key (`TP1-13797`, any case) or a `/browse/KEY` link
  mr      a merge request link, or the short form `<path>!<iid>` (`testproject1-ui!1924`)
  url     any other http(s) link, compared exactly after normalisation
  ref     a commit (12 to 40 hex characters) or `branch:<name>`: for a story whose merge request is
          cited by its revision or branch and never by number (live testproject1-ui holds the branch of
          MR 1924 under a name with no "1924" in it)

THE MATCHER MAY ONLY ERR TOWARD "NO MATCH". A match on a source the word does not name reads
something the person said not to read; a miss shows up as "your list named X and nothing carried it"
at gate A. So: a ticket key is compared whole (`TP1-1379` is not `TP1-13797`, `MY_PROJ-12` is
not `PROJ-12`); a merge request's number is compared whole, never by prefix; a link word compares the
host and the FULL project path; a `ref` needs 12 hex characters or more.

Known ambiguity, accepted and stated: the SHORT form `testproject1-ui!1924` has no host, so it names every
merge request `!1924` of every project whose path is `testproject1-ui` or ends in `/testproject1-ui`, on every
host the story touches. The person who wants exactly one writes the link. The short form names GitLab
merge requests only (`/-/merge_requests/<n>`), never a GitHub `/pull/<n>`.

Exit codes: 0 done (also "nothing to revoke twice"); 2 the call or the file is wrong (no such file,
not UTF-8, larger than a list, an id the record does not have); 3 refused (the inventory exists, a
different list is already loaded, the record is unreadable).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from source_inventory import (TICKET_KEY_RE, VCS_URL_RE, _atomic_write, normalize_url,  # noqa: E402
                              revoke_marks, utc_now)
from hooklib import sorted_paths

SCHEMA_VERSION = 1
RECORD_NAME = "source-exclusions.json"
INVENTORY_NAME = "source-inventory.json"
MAX_LIST_BYTES = 64 * 1024
ORIGIN_PERSON = "person_before_run"
KINDS = ("ticket", "mr", "url", "ref")
MIN_SHA = 12
REASON_CLIP = 120
EXIT_BAD_INPUT = 2
EXIT_REFUSED = 3

_SEPARATOR_RE = re.compile(r"^\s*(?:—|-|:)\s*")
_SHORT_MR_RE = re.compile(r"^(?P<project>[\w.][\w./-]*)!(?P<iid>\d+)$", re.ASCII)
_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")
_BROWSE_PATH_RE = re.compile(r"^(?:/.*)?/browse/(?P<key>[^/]+)/?$")


class ExclusionRecordError(ValueError):
    """The record exists and cannot be trusted: nothing may be written over it or past it."""


class ListRefused(ValueError):
    """`--load` is refused: the story is past the point where a list can start."""


# ---- reading the list ---------------------------------------------------------------------------

def clip(text: str, limit: int = REASON_CLIP) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 3].rstrip() + "..."


def _host(parts) -> str:
    """host[:port], lowercased: the part of a link that says WHICH server."""
    name = (parts.hostname or "").lower()
    try:
        port = parts.port
    except ValueError:
        return ""
    return f"{name}:{port}" if name and port else name


def _norm_iid(value: str) -> str:
    return str(value).lstrip("0") or "0"


def split_vcs_url(url: str) -> dict | None:
    """A merge/pull request link as {host, project, iid, style}, or None when it is not one.

    `VCS_URL_RE` is applied to the PATH only: on the whole text it matched an MR inside a login
    `?next=` query, and the iid is taken from the regex's own digits, never by `rsplit` on the text
    (extracted URLs keep a trailing `.` or `**`). A digit run followed by a letter is no iid."""
    try:
        parts = urlsplit(normalize_url(url).strip())
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    path = parts.path
    found = VCS_URL_RE.search(path)
    if not found:
        return None
    after = path[found.end():found.end() + 1]
    if after and (after.isalnum() or after == "_"):
        return None
    project = path[:found.start()].strip("/")
    marker = re.match(r"^/(?:-/)?(?P<style>merge_requests|pull-requests|pull)/(?P<iid>\d+)$", found.group(0))
    if not project or not marker:
        return None
    return {"host": _host(parts), "project": project, "iid": marker.group("iid"), "style": marker.group("style")}


def _canon_url(url: str) -> str | None:
    """`normalize_url`, host lowercased, fragment dropped, one trailing `/` of the path dropped, query kept."""
    try:
        parts = urlsplit(normalize_url(url).strip())
    except ValueError:
        return None
    host = _host(parts)
    if parts.scheme.lower() not in ("http", "https") or not host:
        return None
    path = parts.path[:-1] if parts.path.endswith("/") else parts.path
    return f"{parts.scheme.lower()}://{host}{path}" + (f"?{parts.query}" if parts.query else "")


def _parse_target(token: str, strict_sha: bool = False) -> tuple:
    """(target, problem_code) for one token: exactly one of the two is None.

    `strict_sha` is for asking "does this word of a REASON look like a source": a 7-11 hex-character
    word there ("defaced") is not one, where as a first token it is a commit id that is too short."""
    token = token.rstrip(":,;")
    if not token:
        return None, "unreadable"
    if re.fullmatch(r"!\d+", token):
        return None, "bare_iid"
    if token.startswith("branch:"):
        name = token[len("branch:"):]
        return ({"kind": "ref", "sha": None, "branch": name}, None) if name else (None, "unreadable")
    if re.match(r"(?i)https?://", token):
        try:
            parts = urlsplit(normalize_url(token))
        except ValueError:
            return None, "unreadable"
        host = _host(parts)
        if not host:
            return None, "unreadable"
        browse = _BROWSE_PATH_RE.match(parts.path)
        if browse:
            key = browse.group("key").upper()
            if browse.group("key").isascii() and TICKET_KEY_RE.fullmatch(key):
                return {"kind": "ticket", "key": key, "host": host}, None
        mr = split_vcs_url(token)
        if mr:
            return {"kind": "mr", "host": mr["host"], "project": mr["project"], "iid": mr["iid"],
                    "style": mr["style"], "head_sha": None, "branch": None}, None
        return {"kind": "url", "url": _canon_url(token)}, None
    short = _SHORT_MR_RE.match(token)
    if short:
        return {"kind": "mr", "host": None, "project": short.group("project"), "iid": short.group("iid"),
                "style": "merge_requests", "head_sha": None, "branch": None}, None
    # ASCII only: `.upper()` turns a dotless i or a long s into a plain letter, which would name a
    # key the person did not type.
    if "!" not in token and token.isascii() and TICKET_KEY_RE.fullmatch(token.upper()):
        return {"kind": "ticket", "key": token.upper(), "host": None}, None
    if _HEX_RE.match(token) and 7 <= len(token) <= 40:
        if len(token) < MIN_SHA:
            return (None, "unreadable") if strict_sha else (None, "short_sha")
        return {"kind": "ref", "sha": token.lower(), "branch": None}, None
    return None, "unreadable"


def _identity(target: dict) -> tuple:
    """Two words of one kind naming the same thing share this. The URL form and the short form of one
    merge request differ on purpose: they are two words that match one item."""
    kind = target["kind"]
    if kind == "ticket":
        return (kind, target["key"], target.get("host"))
    if kind == "mr":
        return (kind, target.get("host"), str(target["project"]).lower(), _norm_iid(target["iid"]), target.get("style"))
    if kind == "url":
        return (kind, target["url"])
    return (kind, target.get("sha"), target.get("branch"))


def _problem(number: int, line: str, code: str, message: str, entry: dict | None = None) -> dict:
    return {"line": number, "text": line, "code": code, "message": message, "entry": entry}


_FORMS = ("a Jira key (PROJ-123), a Jira link, a merge request link, the short form "
          "project!123 (testproject1-ui!1924), a commit or branch:<name>, or another link")


def parse_list(text: str, task_key: str = "") -> tuple:
    """(entries, problems) of a list already decoded. Blank lines and `#` lines are skipped.

    Each clean entry is {line, as_written, target, reason}. A line the code could not read is a
    problem and is applied to nothing; a problem whose TARGET did read carries it as `entry`, so a
    person's "go on" can apply it anyway. The trigger is the token's shape, never the meaning of the
    reason (FR-12)."""
    entries: list = []
    problems: list = []
    by_identity: dict = {}
    text = text.lstrip("﻿")
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        pieces = stripped.split(None, 1)
        token, rest = pieces[0].rstrip(":,;"), (pieces[1] if len(pieces) > 1 else "")
        target, code = _parse_target(token)
        if target is None:
            messages = {
                "bare_iid": (f'line {number}: "{stripped}" names no project. Write the project before the '
                             "exclamation mark, for example testproject1-ui!1924, or paste the merge request link."),
                "short_sha": (f'line {number}: "{token}" looks like a commit id but is shorter than {MIN_SHA} '
                              "characters, which could name other commits. Write at least 12, or the branch "
                              "as branch:<name>."),
                "unreadable": (f'line {number}: "{stripped}" is not a source I can read. Write one source per '
                               f"line: {_FORMS}; then a dash and why it is left out."),
            }
            problems.append(_problem(number, line, code, messages[code]))
            continue
        if task_key and target["kind"] == "ticket" and target["key"] == str(task_key).upper():
            problems.append(_problem(
                number, line, "own_ticket",
                f"line {number}: {target['key']} is the ticket this story tests; its requirements come from "
                "it, so it cannot be left out. Remove the line."))
            continue
        separated = bool(_SEPARATOR_RE.match(rest))
        reason = _SEPARATOR_RE.sub("", rest, count=1).strip()
        entry = {"line": number, "as_written": token, "target": target, "reason": reason}
        if not reason:
            problems.append(_problem(
                number, line, "no_reason",
                f'line {number}: "{token}" has no reason. Write a dash and why it is left out, so it can be '
                "shown to you at the source review.", entry))
            continue
        first_word = reason.split(None, 1)[0]
        if not separated and _parse_target(first_word, strict_sha=True)[0] is not None:
            problems.append(_problem(
                number, line, "two_sources",
                f'line {number}: "{first_word}" after "{token}" reads as a second source. Put one source on '
                "each line, and a dash before the reason.", entry))
            continue
        key = _identity(target)
        first = by_identity.get(key)
        if first is None:
            by_identity[key] = entry
            entries.append(entry)
            continue
        # The same thing named twice: the first line stands, and nothing the person wrote is lost.
        first["reason"] = first["reason"] + " | " + reason
        first["line"] = (first["line"] if isinstance(first["line"], list) else [first["line"]]) + [number]
    return entries, problems


def parse_bytes(data: bytes, task_key: str = "") -> tuple:
    """`parse_list` for the file's bytes. A file that cannot be a list is ONE fatal problem and no
    entries: a wrong file never becomes a list, and nothing is guessed from undecodable bytes."""
    if len(data) > MAX_LIST_BYTES:
        return [], [dict(_problem(0, "", "too_large", "the file is larger than a list (64 KiB); did you name "
                                 "the right file?"), fatal=True)]
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = None
    if text is None or "\x00" in text:
        return [], [dict(_problem(0, "", "not_utf8", "the file is not UTF-8 text; save the list as plain "
                                 "text (UTF-8) and try again."), fatal=True)]
    return parse_list(text, task_key)


# ---- the record ---------------------------------------------------------------------------------

def record_path(work: Path) -> Path:
    return Path(work) / RECORD_NAME


def read_record(work: Path) -> dict | None:
    """The record of `work/`, None when there is none (a story with no list). An unreadable one
    RAISES: it errs toward refusing to write, never toward quietly not applying the person's word."""
    path = record_path(work)
    if not path.exists():
        return None
    story = Path(work).resolve().parent.name
    fix = (f"Restore it from a copy or from `source_exclusions.py --task {story} --show`, or remove the "
           "file to drop every exclusion; nothing was written.")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ExclusionRecordError(f"{path} is not readable as the record of sources the person left out "
                                   f"({type(exc).__name__}). {fix}") from None
    problem = ""
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        problem = f"schema_version is not {SCHEMA_VERSION}"
    elif not isinstance(data.get("exclusions"), list):
        problem = "exclusions is not a list"
    else:
        for index, entry in enumerate(data["exclusions"]):
            target = entry.get("target") if isinstance(entry, dict) else None
            if not isinstance(target, dict) or target.get("kind") not in KINDS or not entry.get("id"):
                problem = f"exclusions[{index}] has no id or no known target"
                break
    if problem:
        raise ExclusionRecordError(f"{path} cannot be trusted: {problem}. {fix}")
    return data


def live_in(work: Path) -> list:
    """The exclusions of `work/source-exclusions.json` that are not revoked; [] with no record."""
    record = read_record(work)
    return [e for e in (record or {}).get("exclusions", []) if not e.get("revoked_at")]


def live(task_root: Path) -> list:
    return live_in(Path(task_root) / "work")


def _sha_hit(known, given) -> bool:
    known, given = str(known or "").lower(), str(given or "").lower()
    if len(known) < MIN_SHA or len(given) < MIN_SHA or not _HEX_RE.match(known) or not _HEX_RE.match(given):
        return False
    return known.startswith(given) or given.startswith(known)


def _match_ticket(target: dict, canonical_ref) -> bool:
    ref = str(canonical_ref or "")
    if "/browse/" not in ref:
        return False
    item_key = ref.rsplit("/browse/", 1)[1].strip("/")
    if not item_key.isascii() or item_key.upper() != str(target.get("key") or ""):
        return False
    if target.get("host"):
        try:
            return _host(urlsplit(ref)) == str(target["host"]).lower()
        except ValueError:
            return False
    return True


def _match_mr(target: dict, url) -> bool:
    item = split_vcs_url(url) if url else None
    if item is None or _norm_iid(item["iid"]) != _norm_iid(target.get("iid")):
        return False
    project = str(target.get("project") or "").strip("/").lower()
    if target.get("host"):
        # A link names one project on one host: the FULL path, the same host, the same kind of request.
        return (item["host"] == str(target["host"]).lower() and item["project"].lower() == project
                and item["style"] == target.get("style"))
    # The short form: GitLab merge requests only, and the project path ends with the word's project.
    return item["style"] == "merge_requests" and bool(project) and (
        item["project"].lower() == project or item["project"].lower().endswith("/" + project))


def matches(exclusion: dict, *, canonical_ref=None, url=None, sha=None, branch=None) -> bool:
    """Does this ONE exclusion name the thing described by the given fields. Every field None: False.
    A revoked exclusion names nothing. Any surprise in the data is a miss, never a hit."""
    if not isinstance(exclusion, dict) or exclusion.get("revoked_at"):
        return False
    target = exclusion.get("target")
    if not isinstance(target, dict):
        return False
    try:
        kind = target.get("kind")
        if kind == "ticket":
            return _match_ticket(target, canonical_ref)
        by_revision = (_sha_hit(target.get("head_sha") if kind == "mr" else target.get("sha"), sha)
                       or bool(branch and target.get("branch") and target["branch"] == branch))
        if kind == "mr":
            return _match_mr(target, url) or by_revision
        if kind == "url":
            wanted = target.get("url")
            return bool(url and wanted and _canon_url(url) == wanted)
        if kind == "ref":
            return by_revision
    except (ValueError, TypeError, AttributeError, KeyError):
        return False
    return False


def first_match(exclusions: list, **fields):
    """The first exclusion, in the record's (line) order, that names the thing; None when none does."""
    return next((e for e in exclusions if matches(e, **fields)), None)


def first_ref_match(exclusions: list, ref):
    """The first live exclusion that a role's `ref` for a source names (a key, a link, a short `project!iid`, a commit, a
    branch: `_ref_hit`, plus the canonical match of a link), else None. The role route's guard (`record-source`, t-586 F-3):
    the fetch route checks `first_match`, which a bare key never satisfies. Any surprise in the data is a miss."""
    text = str(ref or "").strip()
    if not text:
        return None
    for exclusion in exclusions:
        try:
            if matches(exclusion, canonical_ref=text, url=text) or _ref_hit(exclusion, text):
                return exclusion
        except (ValueError, TypeError, AttributeError, KeyError):
            continue
    return None


def reason_of(exclusions: list, exclusion_id: str) -> str:
    return next((str(e.get("reason") or "") for e in exclusions if e.get("id") == exclusion_id), "")


# ---- what a person and a role are told ----------------------------------------------------------

def console_line(exclusion: dict) -> str:
    return (f"Before the run you asked me not to read: {exclusion.get('as_written')} — "
            f"\"{clip(exclusion.get('reason') or '')}\". Nothing of it is fetched; the source review and "
            "gate A list it.")


def refusal_text(what: str, reason: str) -> str:
    """What a role reads when it reaches for a source the person left out (FR-1, FR-2: the door is
    the handoff, which the role can write)."""
    return (f"the person asked before the run not to read `{what}` (\"{reason}\"). Leave it; if you think it "
            "is needed, say so in your handoff - the person sees it at the source review.")


def left_out_line(what: str, reason: str) -> str:
    return f"left out by the person's word before the run: {what} — \"{clip(reason)}\"; nothing was fetched"


# ---- writing ------------------------------------------------------------------------------------

def _write(work: Path, record: dict) -> None:
    _atomic_write(record_path(work), json.dumps(record, indent=2, ensure_ascii=False).encode("utf-8") + b"\n")


def write_record(task_root: Path, entries: list, list_file: str, list_bytes: bytes,
                 at: str | None = None) -> dict:
    """Write `work/source-exclusions.json` (atomically) from parsed entries. Refused once the source
    inventory exists: a source already read cannot then be "left out before the run". The same bytes
    loaded again are a no-op that keeps every revocation; a different list over a record is refused."""
    work = Path(task_root) / "work"
    sha = hashlib.sha256(list_bytes).hexdigest()
    existing = read_record(work)
    if existing is not None:
        if existing.get("list_sha256") == sha:
            return existing
        raise ListRefused(f"{record_path(work)} already holds another list (from "
                          f"{existing.get('list_file')}); a list is read once, when a story starts. To read "
                          "one of its sources after all, revoke it with `source_exclusions.py --revoke`; to "
                          "leave another out, name it at the source review.")
    if (work / INVENTORY_NAME).exists():
        raise ListRefused("the source inventory of this story already exists, so a list is too late: a source "
                          "already read cannot be left out before the run. Name the sources to leave out at "
                          "the source review.")
    at = at or utc_now()
    exclusions = [{"id": f"X{number}", "origin": ORIGIN_PERSON, "line": entry["line"],
                   "as_written": entry["as_written"], "target": entry["target"], "reason": entry["reason"],
                   "by": "human", "at": at, "revoked_at": None, "revoked_by": None, "revoked_words": None}
                  for number, entry in enumerate(entries, start=1)]
    record = {"schema_version": SCHEMA_VERSION, "list_file": str(list_file), "list_sha256": sha,
              "loaded_at": at, "exclusions": exclusions}
    _write(work, record)
    return record


def s1_completed(task_root: Path) -> bool:
    """Is S1 of this story already completed: the controller's own word for it, or the pipeline's."""
    for name, words in (("state/controller.json", {"completed"}), ("pipeline.json", {"completed", "done"})):
        try:
            data = json.loads((Path(task_root) / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        stages = data.get("stages") if isinstance(data, dict) else None
        stage = stages.get("S1") if isinstance(stages, dict) else None
        if isinstance(stage, dict) and stage.get("status") in words:
            return True
    return False


def revoke(task_root: Path, key: str, words: str, by: str = "human") -> dict:
    """The person takes one exclusion back (FR-40). The entry stays with `revoked_at/by/words`.
    {"status": "no_record"|"unknown"|"already"|"revoked", "ids": [...], "entry": {...}, "restored": [...]}."""
    work = Path(task_root) / "work"
    record = read_record(work)
    if record is None:
        return {"status": "no_record", "ids": []}
    rows = record["exclusions"]
    ids = [f"{e['id']} {e.get('as_written')}" for e in rows]
    wanted = str(key).strip()
    found = [e for e in rows if e["id"].lower() == wanted.lower()] or [
        e for e in rows if str(e.get("as_written") or "").lower() == wanted.lower()]
    if len(found) != 1:
        return {"status": "unknown", "ids": ids}
    entry = found[0]
    if entry.get("revoked_at"):
        return {"status": "already", "ids": ids, "entry": entry}
    entry.update(revoked_at=utc_now(), revoked_by=by, revoked_words=words)
    _write(work, record)
    inventory = work / INVENTORY_NAME
    restored = revoke_marks(inventory, entry["id"]) if inventory.exists() else []
    return {"status": "revoked", "ids": ids, "entry": entry, "restored": restored}


def _script(name: str) -> str:
    """The form s1.md spells a script in: the conductor reads the plugin root from its prompt."""
    return f'python "${{CLAUDE_PLUGIN_ROOT}}/scripts/{name}.py"'


def _named_by(target: dict) -> str:
    """What the exclusion's own target calls the thing, for the case nothing of it was in the inventory."""
    kind = target.get("kind")
    if kind == "ticket":
        return str(target.get("key") or "")
    if kind == "url":
        return str(target.get("url") or "")
    if kind == "mr":
        if target.get("host"):
            style = str(target.get("style") or "merge_requests")
            path = f"/-/merge_requests/{target['iid']}" if style == "merge_requests" else f"/{style}/{target['iid']}"
            return f"https://{target['host']}/{str(target.get('project') or '').strip('/')}{path}"
        return f"{target.get('project')}!{target.get('iid')}"
    return str(target.get("sha") or (f"branch:{target['branch']}" if target.get("branch") else ""))


def _door(entry: dict, restored: list, task: str = "") -> str:
    """What the conductor runs to bring a taken-back source in when S1 is already completed (nothing in the
    factory reads a `pending` item then). Every command is whole: the key, url, source id and inventory path
    come from the exclusion, from what `revoke_marks` restored, or from the task; a step that cannot be a
    single command (it depends on what an earlier step printed, or on where the bytes come from) is named by
    its section of s1.md in words, never as a `<placeholder>`. Nothing restored (the item never was in the
    inventory, a commit or branch word, a link no source carried): the thing is named from the exclusion's
    own target."""
    target = entry["target"]
    kind = target["kind"]
    inventory = f"qa-factory/artifacts/{task}/work/{INVENTORY_NAME}"
    adapter = _script("ticket_adapter")
    late = f"`{adapter} review --output {inventory} --late`"
    lead = "S1 of this story is already completed, so nothing runs by itself: the conductor brings it in."
    if kind == "ticket":
        key = _named_by(target)
        rows = [r for r in restored if r.get("key")]
        source = f" for source {rows[0]['source_id']}" if rows and rows[0].get("source_id") else ""
        steps = [f"`{adapter} peek {key} --output {inventory} --summary`",
                 f"record it as relevant{source} with `assess` of the \"Source collection\" section of s1.md, the "
                 "person's own words as the reason and the assessment ref that `peek` printed",
                 f"`{adapter} collect {key} --output {inventory} --relation referenced --summary`",
                 f"the late review: {late}"]
        return lead + "\n" + "\n".join(f"{n}. {step}" for n, step in enumerate(steps, start=1))
    steps, names = [], []
    for row in restored:
        url = row.get("url")
        if not url:
            continue
        fetch = normalize_url(str(url))
        found = re.search(r"/-/merge_requests/(\d+)", fetch)
        if found and row.get("source_id"):
            rel = f"sources/{row['source_id']}/mr-{found.group(1)}.json"
            steps.append(f"`{_script('vcs_evidence')} --url \"{fetch}\" --output qa-factory/artifacts/{task}/work/{rel}`")
            steps.append(f"`{adapter} inspect --output {inventory} --source-id {row['source_id']} --media-url \"{url}\" "
                         f"--inspection-status read --local-ref {rel}` (when the collection failed, record why "
                         "with `--inspection-status unavailable --reason` and the failure instead)")
        else:
            names.append(str(url))
    if not steps and not names:
        names.append(_named_by(target))
    if names:
        steps.append(f"for {', '.join(names)}: repeat the \"Source collection\" section of s1.md (save the original "
                     "bytes, record them with `inspect --media-url`); no source of the inventory carries it, so "
                     "nothing is waiting to be read by itself")
    steps.append(f"the late review: {late}")
    return lead + "\n" + "\n".join(f"{n}. {step}" for n, step in enumerate(steps, start=1))


# ---- the command --------------------------------------------------------------------------------

def _task_root(task: str) -> Path:
    from hooklib import story_root
    return story_root(task, "--task")


def main(argv=None) -> int:
    # allow_abbrev off: the guard closes `--load` and `--revoke` to roles by their exact spelling, and
    # argparse would otherwise accept `--rev` for the same thing.
    # The reason and the revoke words are the person's own, in any language: a pipe on Windows
    # defaults to a legacy code page and would raise on print, so the streams are UTF-8.
    try:
        import console_io
        console_io.utf8_stdio(errors="replace")
    except ImportError:
        pass
    import hooklib
    ap = argparse.ArgumentParser(description="the person's word about sources, before the run")
    ap.add_argument("--task", required=True)
    ap.add_argument("--load", metavar="FILE", help="orchestrator only: read the person's list of sources")
    ap.add_argument("--show", action="store_true", help="print the record")
    ap.add_argument("--revoke", metavar="X-id|as_written",
                    help="orchestrator only: the person takes one exclusion back (needs --words)")
    ap.add_argument("--words", default="", help="--revoke: the person's own words")
    args = hooklib.exact_options(ap).parse_args(argv)
    if sum(bool(value) for value in (args.load, args.show, args.revoke)) != 1:
        print("source_exclusions: give exactly one of --load FILE, --show, --revoke <id> --words \"...\"",
              file=sys.stderr)
        return EXIT_BAD_INPUT
    try:
        task_root = _task_root(args.task)
    except ValueError as exc:
        print(f"source_exclusions: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT
    work = task_root / "work"
    try:
        if args.show:
            path = record_path(work)
            if not path.exists():
                print(f"{args.task} has no list of sources left out before the run")
                return 0
            print(path.read_text(encoding="utf-8-sig").rstrip())
            read_record(work)
            return 0
        if args.load:
            try:
                data = Path(args.load).read_bytes()
            except OSError as exc:
                print(f"source_exclusions: cannot read {args.load} ({type(exc).__name__}); name the file the "
                      "person gave", file=sys.stderr)
                return EXIT_BAD_INPUT
            entries, problems = parse_bytes(data, args.task)
            fatal = [p for p in problems if p.get("fatal")]
            if fatal:
                print(f"source_exclusions: {args.load}: {fatal[0]['message']}", file=sys.stderr)
                return EXIT_BAD_INPUT
            record = write_record(task_root, entries, args.load, data)
            for problem in problems:
                print(f"source_exclusions: not applied - {problem['message']}", file=sys.stderr)
            for exclusion in record["exclusions"]:
                print(console_line(exclusion))
            if not record["exclusions"]:
                print("the list names no source")
            return 0
        if not args.words.strip():
            print("source_exclusions: --revoke needs --words: what the person said when they took it back",
                  file=sys.stderr)
            return EXIT_BAD_INPUT
        result = revoke(task_root, args.revoke, args.words.strip())
        if result["status"] == "no_record":
            print(f"source_exclusions: {args.task} has no list of sources left out; nothing to revoke",
                  file=sys.stderr)
            return EXIT_BAD_INPUT
        if result["status"] == "unknown":
            print(f"source_exclusions: no exclusion `{args.revoke}` in {args.task}; it has: "
                  + "; ".join(result["ids"]), file=sys.stderr)
            return EXIT_BAD_INPUT
        entry = result["entry"]
        if result["status"] == "already":
            print(f"already revoked: {entry['id']} {entry.get('as_written')} (on {entry.get('revoked_at')}); "
                  "nothing changed")
            return 0
        print(f"revoked: {entry['id']} {entry.get('as_written')} - the person's word now: \"{clip(args.words)}\"")
        for row in result["restored"]:
            print(f"back to waiting: {row.get('url') or row.get('key')}")
        if s1_completed(task_root):
            print(_door(entry, result["restored"], args.task))
        return 0
    except ExclusionRecordError as exc:
        print(f"source_exclusions: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except ListRefused as exc:
        print(f"source_exclusions: {exc}", file=sys.stderr)
        return EXIT_REFUSED


# ==== BEGIN wave B (t-186): the net beyond the inventory ========================================
# `manifest_problems` is read by the S1 exit gate (`exit_gate.scoped_errors`). The inventory marks and the
# fetch doors stop the factory's own commands; this is the detector for what a role does with its OWN tools
# (a glab call, a git show) and then writes down: TP1-15045 (judge run, 23.09) cited the excluded draft MR
# as a requirement source, as existing coverage for six criteria, and kept its receipt. Two structural
# matches and a receipt scan - never the meaning of a sentence (FR-12): a free-text mention ("MR 1924 is
# evaluation-only", a path, the trail) is NOT matched, because the detector errs toward missing and never
# toward a false refusal.

_SHA_FIELDS = ("revision", "commit", "source_sha", "head_sha", "sha")
# The manifest has its own check (`_manifest_hits`): read as a receipt too, its nested objects would report the
# same citation a second time under a message that says "collected", which is not what it is.
_NOT_RECEIPTS = ("source-inventory.json", "source-exclusions.json", "context-manifest.json")
# A receipt is a JSON file, or the text of a diff a role saved; the text is read for its first 4 KiB only (a
# long file that names the thing deep inside is a document about it, not a receipt of having fetched it).
_TEXT_RECEIPTS = (".txt", ".diff", ".patch")
TEXT_SCAN_BYTES = 4096
# The fields of a manifest object that name WHAT it is. `path`, `selector`, `title`, `why` and free text are
# not here: a genuine candidate of the same repository can hold `/1924/` in a path or `(:1924)` in a selector.
_ID_FIELDS = ("candidate_id", "id", "ref", "mr", "source", "origin")


def _tail(text) -> str:
    """The last path segment of a project or repository, lower case ('' for nothing)."""
    parts = [p for p in re.split(r"[/:]", str(text or "").strip().strip("/")) if p]
    return parts[-1].removesuffix(".git").lower() if parts else ""


def _has_token(text, number) -> bool:
    """`number` as a whole token: 1924 is in 'C-UI-1924-factory' and not in '219245' or 'test_1924'."""
    return bool(number) and re.search(rf"(?<![0-9A-Za-z_]){re.escape(str(number))}(?![0-9A-Za-z_])",
                                      str(text or "")) is not None


def _cited(exclusion: dict, where: str) -> str:
    reason = str(exclusion.get("reason") or "")
    return (f"context-manifest.json: {where} cites {exclusion.get('id')} ({exclusion.get('as_written')}), which "
            "the person asked before the run not to read"
            + (f" (\"{clip(reason)}\")" if reason else "")
            + ". It is not a source, a precedent or existing coverage of this story: take the citation out. "
              "If you think it is needed, say so in your handoff; the person decides at the source review.")


def _as_dicts(value) -> list:
    if isinstance(value, dict):
        return [value]
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _id_texts(item: dict) -> list:
    """The values of the id-like fields of one object, each as a string: a list of strings is each of its
    strings, a number is its digits."""
    texts = []
    for field in _ID_FIELDS:
        value = item.get(field)
        for one in (value if isinstance(value, list) else [value]):
            if isinstance(one, (str, int)) and not isinstance(one, bool):
                texts.append(str(one))
    return texts


def _branch_hit(exclusion: dict, name) -> bool:
    """A branch as the role wrote it: bare, or as a remote lists it (`origin/<name>`)."""
    if not isinstance(name, str):
        return False
    name = name.strip()
    return matches(exclusion, branch=name) or (
        name.startswith("origin/") and matches(exclusion, branch=name[len("origin/"):]))


def _sha_fields_hit(exclusion: dict, item: dict) -> bool:
    """Does one object carry the excluded head: a revision field, the `sha` of a glab receipt, its `web_url`
    (through `matches(url=)`), or the `head_sha` of its `diff_refs` (one level down, and only when that is an
    object)."""
    if any(isinstance(item.get(field), str) and matches(exclusion, sha=item[field]) for field in _SHA_FIELDS):
        return True
    web_url = item.get("web_url")
    if isinstance(web_url, str) and matches(exclusion, url=web_url):
        return True
    refs = item.get("diff_refs")
    return isinstance(refs, dict) and isinstance(refs.get("head_sha"), str) and matches(exclusion, sha=refs["head_sha"])


def _iid_with_tail(exclusion: dict, text) -> bool:
    """`!<iid>` of an excluded merge request with its project's tail as a whole word on the SAME line
    (`MR !1924 (testproject1-ui)`, `testproject1-ui!1924`). Never the number alone, never another project's tail:
    `testproject1-backend!1924` and `!19245` are not this one."""
    target = exclusion.get("target") or {}
    project, iid = _tail(target.get("project")), _norm_iid(target.get("iid") or "")
    if target.get("kind") != "mr" or not project or not target.get("iid"):
        return False
    tail = re.compile(rf"(?<![\w.-]){re.escape(project)}(?![\w-]|\.\w)", re.IGNORECASE)
    return any(tail.search(line) and any(_norm_iid(n) == iid for n in re.findall(r"!(\d+)(?!\w)", line))
               for line in str(text or "").splitlines())


def _ref_hit(exclusion: dict, ref) -> bool:
    """Does one `requirement_sources[].ref` name the exclusion. Its FIRST word is read the way the list reads
    a word (`_parse_target`, with the strict commit rule): the word as the person wrote it, a short
    `project!iid` whose project tail and number are the word's, a commit, `branch:<name>`, or a bare branch
    name (as a remote lists it too); a link anywhere in the ref that the word names; or `!<iid>` with the
    project's tail in the same ref. An empty ref names nothing."""
    target = exclusion.get("target") or {}
    kind = target.get("kind")
    text = str(ref or "")
    words = text.split()
    first = words[0].rstrip(":,;") if words else ""
    if not first:
        return False
    if first.lower() == str(exclusion.get("as_written") or "").lower():
        return True
    if any(matches(exclusion, url=link.rstrip(".,;:*")) for link in re.findall(r"https?://[^\s<>\"')\]]+", text)):
        return True
    if kind == "ticket" and first.upper() == str(target.get("key") or ""):
        return True
    try:
        parsed, _code = _parse_target(first, strict_sha=True)
    except ValueError:
        parsed = None
    if parsed and parsed["kind"] == "mr" and not parsed.get("host") and kind == "mr":
        project = _tail(target.get("project"))
        if project and _tail(parsed["project"]) == project and _norm_iid(parsed["iid"]) == _norm_iid(target.get("iid") or ""):
            return True
    if parsed and parsed["kind"] == "ref" and (
            (parsed.get("sha") and matches(exclusion, sha=parsed["sha"]))
            or (parsed.get("branch") and _branch_hit(exclusion, parsed["branch"]))):
        return True
    return _branch_hit(exclusion, first) or _iid_with_tail(exclusion, text)


def _manifest_hits(exclusion: dict, manifest: dict) -> list:
    """Where the manifest cites ONE exclusion: the list of `where` strings."""
    target = exclusion.get("target") or {}
    kind, found = target.get("kind"), []
    project, iid = _tail(target.get("project")), target.get("iid")
    # 1. implementations[] (and the single `implementation`): the repo's tail is the project's tail AND `mr` is
    #    the number; or a revision field is the excluded head; or the branch is the excluded branch.
    for name in ("implementations", "implementation"):
        for index, item in enumerate(_as_dicts(manifest.get(name))):
            where = f"{name}[{index}]" if name == "implementations" else name
            repo = _tail(item.get("repo_id") or item.get("repo"))
            mr = str(item.get("mr") or "").strip()
            by_number = (kind == "mr" and project and repo == project and bool(mr)
                         and (_norm_iid(mr.lstrip("!")) == _norm_iid(iid) if re.fullmatch(r"!?\d+", mr)
                              else matches(exclusion, url=mr)))
            if by_number or _sha_fields_hit(exclusion, item) or _branch_hit(exclusion, item.get("branch")):
                found.append(where)
    # 2. requirement_sources[]: `ref` names the word (`_ref_hit`: as written, a short `project!iid`, a link, a
    #    commit, a branch, `!<iid>` with the project's tail), or is the key of an excluded ticket; or its
    #    revision is the excluded head.
    for index, item in enumerate(_as_dicts(manifest.get("requirement_sources"))):
        if _ref_hit(exclusion, item.get("ref")) or _sha_fields_hit(exclusion, item):
            found.append(f"requirement_sources[{index}]")
    # 3. existing_test_candidates[]: one OBJECT - its repo's tail is the project's tail AND (the number is a
    #    whole token of one of its ID-LIKE fields OR its revision is the excluded head); a commit word has no
    #    project, so the head alone decides. A path, a selector, a title or a sentence is never matched: a
    #    genuine candidate of the same repository holds `/1924/` in a path and `(:1924)` in a selector.
    for index, item in enumerate(_as_dicts(manifest.get("existing_test_candidates"))):
        texts = _id_texts(item)
        same_repo = bool(project) and _tail(item.get("repo")) == project
        if ((kind == "mr" and same_repo and any(_has_token(text, iid) for text in texts))
                or (kind == "mr" and same_repo and _sha_fields_hit(exclusion, item))
                or (kind == "ref" and _sha_fields_hit(exclusion, item))):
            found.append(f"existing_test_candidates[{index}]")
    return found


def _receipt_hits(exclusion: dict, receipt: dict, nested: bool = True) -> bool:
    """Is a JSON object a receipt of the excluded thing: its `url` or `web_url`, its host/project/iid, or a
    head commit (`revision`, `sha`, `diff_refs.head_sha`) name it. A raw glab answer keeps these in a nested
    object (`metadata`), so a value that is itself an object is read the same way, ONE level down."""
    url = receipt.get("url")
    if isinstance(url, str) and matches(exclusion, url=url):
        return True
    host, project, iid = receipt.get("host"), receipt.get("project"), receipt.get("iid")
    if all(isinstance(v, (str, int)) and v != "" for v in (host, project, iid)):
        if matches(exclusion, url=f"https://{host}/{str(project).strip('/')}/-/merge_requests/{iid}"):
            return True
    if _sha_fields_hit(exclusion, receipt):
        return True
    return nested and any(_receipt_hits(exclusion, value, nested=False)
                          for value in receipt.values() if isinstance(value, dict))


def _text_receipt_hits(exclusion: dict, text: str) -> bool:
    """Does the head of a saved diff or note name an excluded merge request: its link, `!<iid>` with the
    project's tail on the same line, or its FULL head commit. Never the bare number (a sentence that says
    "MR 1924 is evaluation-only" is prose), never a branch name, and only merge requests and commits: a
    ticket key or another link in a saved text is a mention, not a fetch."""
    target = exclusion.get("target") or {}
    kind = target.get("kind")
    full = str((target.get("head_sha") if kind == "mr" else target.get("sha")) or "").lower()
    if len(full) == 40 and _HEX_RE.match(full) and re.search(rf"(?<![0-9a-f]){full}(?![0-9a-f])", text, re.IGNORECASE):
        return True
    if kind != "mr":
        return False
    links = re.findall(r"https?://[^\s<>\"')\]]+", text)
    return any(matches(exclusion, url=link.rstrip(".,;:*")) for link in links) or _iid_with_tail(exclusion, text)


def _receipt_files(work: Path) -> list:
    """The files of `work/` that can be a receipt. Under `work/sources/` only `mr-*.json` (the `vcs_evidence`
    receipts `close_vcs_gaps` writes as `sources/<SRC>/mr-<iid>.json`, at any depth, matched by file NAME,
    case-sensitive) are read; the rest there is the inventory's own material of the person's sources (ticket
    snapshots, comments, attachments, any text), the ticket's own words, which legitimately name what the
    person left out and are never a fetch of it. Only a real directory is treated so: a file or a symlink
    called `sources` skips nothing."""
    if not work.is_dir():
        return []
    sources = work / "sources"
    skip = sources.is_dir() and not sources.is_symlink()
    return sorted_paths(path for path in work.rglob("*")
                  if path.suffix.lower() in (".json",) + _TEXT_RECEIPTS and path.name not in _NOT_RECEIPTS
                  and path.is_file()
                  and not (skip and sources in path.parents
                           and not (path.name.startswith("mr-") and path.suffix == ".json")))


def _read_head(path: Path) -> str:
    """The first TEXT_SCAN_BYTES bytes of a file as text; bytes that are not UTF-8 become replacement
    characters, never an error. '' for a file that cannot be read."""
    try:
        with path.open("rb") as handle:
            return handle.read(TEXT_SCAN_BYTES).decode("utf-8", errors="replace")
    except OSError:
        return ""


def manifest_problems(task_root, manifest) -> list:
    """`context-manifest.json: ...` (and receipt) errors for the scout: what its manifest or its `work/` still
    cites of a source the person asked before the run not to read (t-172 P8b, C2, C3). [] with no list of
    sources left out - a story with no list is today's story - and for a manifest that cites nothing named.

    Receipt scan: every `work/**/*.json` of THIS story whose `url`, `web_url`, `host`+`project`+`iid` or
    head commit (`revision`, `sha`, `diff_refs.head_sha`) names a live exclusion - at the top or one object
    down - is an error too: a role fetched what the person said not to fetch, with its own tools. So is a
    `work/**/*.txt`, `*.diff` or `*.patch` whose first 4 KiB hold the excluded request's link, `!<iid>` with
    its project's tail on one line, or its full head commit. Other stories' files are never read. The errors
    carry a file name the S1 gate knows, so the scout sees them (`exit_gate.scoped_errors` keeps the errors of
    the stage's own outputs)."""
    task_root = Path(task_root)
    try:
        exclusions = live(task_root)
    except ExclusionRecordError as exc:
        return [f"context-manifest.json: {exc}"]
    if not exclusions:
        return []
    manifest = manifest if isinstance(manifest, dict) else {}
    errors = []
    for exclusion in exclusions:
        for where in _manifest_hits(exclusion, manifest):
            errors.append(_cited(exclusion, where))
    work = task_root / "work"
    for path in _receipt_files(work):
        if path.suffix.lower() == ".json":
            try:
                receipt = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
            if not isinstance(receipt, dict):
                continue
            hit = lambda exclusion, receipt=receipt: _receipt_hits(exclusion, receipt)
        else:
            head = _read_head(path)
            hit = lambda exclusion, head=head: _text_receipt_hits(exclusion, head)
        for exclusion in exclusions:
            if hit(exclusion):
                reason = str(exclusion.get("reason") or "")
                errors.append(
                    f"source-inventory.json: {path.relative_to(task_root).as_posix()} holds what "
                    f"{exclusion.get('id')} ({exclusion.get('as_written')}) names, which the person asked before "
                    "the run not to read" + (f" (\"{clip(reason)}\")" if reason else "") + ". Do not cite it "
                    "anywhere, and say in your handoff that it was collected; the person sees it at the source "
                    "review and can ask for it there.")
                break
    return errors
# ==== END wave B ================================================================================


if __name__ == "__main__":
    sys.exit(main())
