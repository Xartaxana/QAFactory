"""first_look.py - the record of the first look at the new version on the stand, the attempt that walks it, and the questions code asks of it.

    python scripts/first_look.py begin --task-root <story> --dispatch <id> --env <stand>   (the driver / the skill path: a walk is opened)
    python scripts/first_look.py end   --task-root <story> --outcome written|nothing_written|open_failed
    python scripts/first_look.py put   --task-root <story> --file <rows.yaml> | --null <reason>   (the walker: the record, once)
    python scripts/first_look.py show  --task-root <story> [--json]

WHAT THE FIRST LOOK IS. Before the plan is made, a walker looks at the stand once (the survey place of `walk_session.py`) and says, per
requirement of the register, what the stand showed: `confirms`, `contradicts`, `missing` or `unreachable` (`references/first-look-statuses.json`),
with the page, route or locator it found and the capture that shows it. The form is `references/artifact-contract-first-look.md`; the record
is `work/first-look.yaml`; the attempt that wrote it is `state/first-look-attempt.json`. Both are written ONLY here (AR-14).

WHAT CODE DOES (AR-29, FR-47, FR-58). It carries data and checks keys and cross-references: one row per requirement of the register, none for
a requirement that is not in it, a word of the closed lists, a capture that belongs to THIS walk's attempt of THAT requirement
(`walk_session.capture_cited`, always with the walk's stand). It never decides whether a row is TRUE: the record is an observation, never an
oracle, and the role that reads it weighs it. `put` writes `walked_at`, `walk`, `stand`, `stand_build`, `source_head`, `register_hash` and
`sides_met` itself and ignores whatever the role sent for them.

THE KEYS. `current_keys` is the ONE producer of the pair (the heads text, the register hash) that says "this is the code and the
requirement list the first look is about": `controller.py --operation first_look_continue` stores the pair as the driver gives it, and
`continued` here compares it with `current_keys` again. `read` is the ONE reader of the record: stale when the code heads or the register
changed since the walk.

Functions of the questions (all pure: they write nothing, FR-45): `current_keys`, `read`, `share`, `due`, `continued`, `asked`, `walk_actors`.
Functions that write: `begin`, `end`, `put`, `mark_asked`. A refusal is a list of problems, each with its door (FR-1, FR-2); nothing here raises for a role's mistake.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract as C  # noqa: E402
import event_store  # noqa: E402
import grounding_table as GT  # noqa: E402
import handoff  # noqa: E402
import handoff_check as HC  # noqa: E402
import hooklib  # noqa: E402
import role_cli  # noqa: E402
import stand_identity as SI  # noqa: E402
import walk_session as WS  # noqa: E402
from role_cli import RefusingParser, epilog, run_guarded  # noqa: E402

SCRIPT = "first_look.py"
SUBCOMMANDS = ("begin", "end", "put", "show")
DATA_PATH = hooklib.PLUGIN_ROOT / "references" / "first-look-statuses.json"
RECORD_PARTS = ("work", "first-look.yaml")
ATTEMPT_PARTS = ("state", "first-look-attempt.json")
FLOOR_KEY = ("first_look", "reachable_floor_percent")
FLOOR_DEFAULT = 30
REQ_ID = re.compile(r"R-\d+")
COMMIT = re.compile(r"[0-9a-f]{40}")

# The shape of the form (its field names are the contract, `references/artifact-contract-first-look.md`); the WORDS they take are data.
TOP_KEYS = ("rows", "gaps")
SENT_BY_CODE = ("walked_at", "walk", "stand", "stand_build", "source_head", "register_hash", "sides_met", "null")
ROW_KEYS = ("req", "status", "blocked_by", "why", "evidence", "quote", "path")
PATH_KEYS = ("url", "steps", "locators", "api", "data", "roles", "stand_needs")
PATH_LISTS = ("steps", "data", "roles", "stand_needs")
LOCATOR_KEYS = ("what", "selector", "seen")
API_KEYS = ("method", "path", "auth", "sample", "seen")
SAMPLE_KEYS = ("request", "status", "response")


def data() -> dict:
    """The closed words of the first look (`references/first-look-statuses.json`); `{}` when the file cannot be read."""
    return hooklib.read_json(DATA_PATH, {}, kind=dict)


def _words(key: str) -> list:
    value = data().get(key)
    return [str(w) for w in value] if isinstance(value, list) else []


def red_statuses() -> list:
    """The statuses the briefs list as 'the stand did not show it' (data: `red_statuses`)."""
    return _words("red_statuses")


def bug_candidate_blocked_by() -> dict:
    """`{status: [blocked_by words]}`: a row of that status reaches S7 as a bug candidate only with one of these words (data)."""
    value = data().get("bug_candidate_blocked_by")
    return {str(k): [str(w) for w in v] for k, v in value.items() if isinstance(v, list)} if isinstance(value, dict) else {}


def stand_build_confirmed() -> str:
    """The `stand_build` word of a record whose deployed revision was confirmed (data); `""` when the file cannot be read, so nothing equals it."""
    return str(data().get("stand_build_confirmed") or "")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canon(value) -> str:
    """The one canonical JSON text of a key (sorted keys, compact separators)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _record_path(task_root) -> Path:
    return Path(task_root).joinpath(*RECORD_PARTS)


def _attempt_path(task_root) -> Path:
    return Path(task_root).joinpath(*ATTEMPT_PARTS)


def _number(req: str) -> tuple:
    tail = str(req).rsplit("-", 1)[-1]
    return (int(tail) if tail.isdigit() else 10 ** 9, str(req))


# --- the keys ----------------------------------------------------------------------------------------------------------------

def _entry_name(entry: dict, number: int) -> str:
    """The id of a manifest implementation entry: its repository id (`repo_id`, else `repo`) - the name `GT.commit_value` is given; an entry
    that names no repository is named by its diff file, else by its position."""
    who = str(entry.get("repo_id") or entry.get("repo") or "").strip()
    if who:
        return who
    diff = str(entry.get("diff_path") or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    return diff or f"implementation-{number}"


def source_entries(task_root) -> dict:
    """{key: implementation entry} of `work/context-manifest.json`, read through `handoff_check.implementation_entries` (the one reader of
    that shape): THE one naming of the entries (AR-13) - the keys of the recorded `source_head` and of every later look at the same code.
    `{}` when the story has no manifest (or none that reads) or no entry. Two entries of one id keep both: the later is `<id>#2`."""
    manifest = hooklib.read_json(Path(task_root) / "work" / "context-manifest.json", None, kind=dict)
    out: dict = {}
    for number, entry in enumerate(HC.implementation_entries(manifest) if manifest is not None else [], 1):
        if not isinstance(entry, dict):
            continue
        name = _entry_name(entry, number)
        key, again = name, 1
        while key in out:
            again += 1
            key = f"{name}#{again}"
        out[key] = entry
    return out


def source_head_map(task_root) -> dict:
    """{repository id: sha | "unmeasured: ..."} of every implementation entry (`source_entries`), the value being `grounding_table.commit_value`
    (the one value). `{}` when the story has no manifest or no entry."""
    return {key: GT.commit_value(entry, key) for key, entry in source_entries(task_root).items()}


def _register(task_root) -> tuple:
    """`({"ids": [R-n...], "hash": sha256}, "")` or `(None, why)`. The hash is of the canonical JSON of [[id, text]...] in id order, so a
    reordered or re-spaced register is the same register and a changed statement is another."""
    info = GT.register_info(task_root)
    if not info.ok:
        return None, str(info.why or "the register cannot be read")
    ids = sorted({str(r) for r in info.ids}, key=_number)
    listed = [[r, " ".join(str(info.texts.get(r, "")).split())] for r in ids]
    return {"ids": ids, "hash": hashlib.sha256(_canon(listed).encode("utf-8")).hexdigest()}, ""


def current_keys(task_root) -> tuple:
    """`(source_head_text, register_hash)` - the ONLY producer of the pair (t-2277 N2): `source_head_text` is the canonical JSON text of the
    heads map (`json.dumps(map, sort_keys=True, separators=(",", ":"))`), `register_hash` the sha256 of the canonical register list. A
    register that cannot be read gives the hash `""`, which equals nothing (`continued` and `read` treat it as unknown, never as a match)."""
    register, _why = _register(task_root)
    return _canon(source_head_map(task_root)), (register["hash"] if register else "")


# --- the attempt -------------------------------------------------------------------------------------------------------------

def read_attempt(task_root) -> dict:
    """The attempt file as a dict, `{}` when there is none or it cannot be read as one (an unreadable attempt is no attempt)."""
    row = hooklib.read_json(_attempt_path(task_root), {}, kind=dict)
    if not isinstance(row.get("dispatch"), str) or not row.get("dispatch") or row.get("outcome") not in _words("attempt_outcomes"):
        return {}
    return row


def _write_attempt(task_root, row: dict) -> None:
    """The one writer of the attempt file: `event_store.atomic_json` (temp file, replace, the Windows replace retry)."""
    event_store.atomic_json(_attempt_path(task_root), row)


def begin(task_root, dispatch, env) -> dict:
    """Open an attempt for the CURRENT code and register: `walk` is the dispatch id, the outcome `walking`. A new head or register is a new
    attempt (`open_failures` starts again at 0); the same keys keep the failures counted so far."""
    heads = source_head_map(task_root)
    register, _why = _register(task_root)
    keys = (heads, register["hash"] if register else "")
    before = read_attempt(task_root)
    same = bool(before) and _canon(before.get("source_head")) == _canon(keys[0]) and before.get("register_hash") == keys[1]
    row = {"dispatch": str(dispatch), "walk": str(dispatch), "env": str(env), "source_head": keys[0], "register_hash": keys[1],
           "opened_at": _now(), "outcome": "walking", "open_failures": int(before.get("open_failures") or 0) if same else 0}
    _write_attempt(task_root, row)
    return row


def end(task_root, outcome) -> dict:
    """Set the attempt's outcome; `open_failed` counts one more failure to open. `{"ok": bool, "problem": text, "attempt": row}`."""
    allowed = [w for w in _words("attempt_outcomes") if w != "walking"]
    row = read_attempt(task_root)
    if outcome not in allowed:
        return {"ok": False, "attempt": row, "problem": f"--outcome is how the walk ended, one of: {', '.join(allowed)}; got {str(outcome)[:60]!r}"}
    if not row:
        return {"ok": False, "attempt": {}, "problem": "no first-look attempt is open for this story; `first_look.py begin` opens it (the driver does)"}
    row = dict(row, outcome=outcome)
    if outcome == "open_failed":
        row["open_failures"] = int(row.get("open_failures") or 0) + 1
    _write_attempt(task_root, row)
    return {"ok": True, "attempt": row, "problem": ""}


def mark_asked(task_root) -> dict:
    """Record that the question about THIS walk's record (`first_look.dead`) was put to the person: `asked_at` on the attempt, the one writer
    of that file (t-2277 FL-5, FR-7: the same text is not asked again of the same walk). A new walk (`begin`) is a new attempt without the
    mark, so a new head or register may ask again. `{"ok": bool, "problem": text}`; no attempt -> not ok, nothing written."""
    row = read_attempt(task_root)
    if not row:
        return {"ok": False, "problem": "no first-look attempt is open for this story, so there is no walk to mark as asked"}
    _write_attempt(task_root, dict(row, asked_at=_now()))
    return {"ok": True, "problem": ""}


def asked(task_root) -> bool:
    """Was the question about the current attempt's walk already put to the person (`mark_asked`)? An unreadable attempt: False."""
    return bool(read_attempt(task_root).get("asked_at"))


def walk_actors(project, cfg, stand, max_actors) -> dict:
    """The actors of the survey walk and what the factory knows beyond them (t-2277 J-18, FL-5 decision 2) - THE one reader of the account
    list (AR-13): `{"actors", "accounts", "left", "none", "problem"}`. `accounts` are the accounts the factory has on `stand`, in the ORDER
    of the sources' own rows: the stand's default login (`manual_capture.read_login`, as `default`) first, then the roles of
    `project_knowledge.roster` that have an account and a sign-in, in the roster's own order (data: no list of names in code). `actors` are
    the accounts first, up to `max_actors`, then `guest` when a slot is left (none -> guest; one -> account + guest; more than the slots
    -> the first ones). `left` are the accounts that did not fit (existing, not opened: a requirement that needs one is `unreachable` with
    `blocked_by: access`, and its why names the account). `none` are roles with no account on the stand. `problem` is the roster's own
    (an unreadable record narrows `accounts`; the caller says so). Never raises."""
    accounts, none, problem = [], [], ""
    try:
        import manual_capture as MC
        if MC.read_login(cfg, Path(project)) is not None:
            accounts.append("default")
    except ValueError:
        pass            # no readable default account: the walk goes on with what else the factory has
    except Exception as exc:  # noqa: BLE001 - an unreadable login is not an account
        problem = f"the stand's default login could not be read ({type(exc).__name__})"
    try:
        import project_knowledge as PK
        got = PK.roster(project, cfg, stand) if stand else {"elements": [], "problem": ""}
        problem = problem or str(got.get("problem") or "")
        for element in got.get("elements") or []:
            if element.get("sign_in") == "none":
                continue
            if element.get("account") is True:
                accounts.append(str(element["role"]))
            elif element.get("account") is False:
                none.append(str(element["role"]))
    except Exception as exc:  # noqa: BLE001 - a roster that cannot be read leaves the accounts it has
        problem = problem or f"the record of project knowledge could not be read ({type(exc).__name__})"
    accounts = list(dict.fromkeys(accounts))
    slots = max(1, int(max_actors))
    actors = accounts[:slots]
    if len(actors) < slots:
        actors.append("guest")
    return {"actors": actors, "accounts": accounts, "left": accounts[slots:], "none": list(dict.fromkeys(none)), "problem": problem}


# --- the record: what put checks ---------------------------------------------------------------------------------------------

def _text_of(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _list_faults(value, where: str) -> list:
    """`[]` for a list of non-empty strings (an absent value, null and an empty string read as the empty list), else what is wrong."""
    if value in (None, ""):
        return []
    if not isinstance(value, list) or not all(_text_of(v) for v in value):
        return [f"{where} is a list of lines (one `- <text>` each)"]
    return []


def _locator_faults(item, where: str) -> list:
    if not isinstance(item, dict):
        return [f"{where} is a mapping with what, selector and seen"]
    out = [f"{where}: unknown key `{k}` (allowed: {', '.join(LOCATOR_KEYS)})" for k in item if k not in LOCATOR_KEYS]
    out += [f"{where}.{k} is the text of what the walker found" for k in ("what", "selector") if not _text_of(item.get(k))]
    if item.get("seen") not in _words("seen"):
        out.append(f"{where}.seen is one of: {', '.join(_words('seen'))}; got {str(item.get('seen'))[:40]!r}")
    return out


def _auth_faults(auth, where: str) -> list:
    prefix = str(data().get("auth_account_prefix") or "account:")
    if auth in _words("auth") or (isinstance(auth, str) and auth.startswith(prefix) and auth[len(prefix):].strip()):
        return []
    return [f"{where}.auth is one of: {', '.join(_words('auth'))}, or {prefix}<role>; got {str(auth)[:40]!r}"]


def _api_faults(item, where: str) -> list:
    """One route of `path.api`: method, path, auth, seen, and an optional `sample` of what the walker SAW (never what it expects)."""
    if not isinstance(item, dict):
        return [f"{where} is a mapping with method, path, auth and seen"]
    out = [f"{where}: unknown key `{k}` (allowed: {', '.join(API_KEYS)})" for k in item if k not in API_KEYS]
    out += [f"{where}.{k} is the text of the route's {k}" for k in ("method", "path") if not _text_of(item.get(k))]
    out += _auth_faults(item.get("auth"), where)
    if item.get("seen") not in _words("seen"):
        out.append(f"{where}.seen is one of: {', '.join(_words('seen'))}; got {str(item.get('seen'))[:40]!r}")
    sample = item.get("sample")
    if sample not in (None, ""):
        if not isinstance(sample, dict):
            out.append(f"{where}.sample is a mapping of what the call showed: {', '.join(SAMPLE_KEYS)}")
        else:
            out += [f"{where}.sample: unknown key `{k}` - a sample is an observation (allowed: {', '.join(SAMPLE_KEYS)})"
                    for k in sample if k not in SAMPLE_KEYS]
    return out


def _path_faults(path, where: str) -> list:
    """The shape of a row's `path` (where the requirement lives on the stand); nothing here judges whether it is right."""
    if path in (None, ""):
        return []
    if not isinstance(path, dict):
        return [f"{where} is a mapping ({', '.join(PATH_KEYS)})"]
    out = [f"{where}: unknown key `{k}` (allowed: {', '.join(PATH_KEYS)})" for k in path if k not in PATH_KEYS]
    if path.get("url") not in (None, "") and not _text_of(path.get("url")):
        out.append(f"{where}.url is the address as text")
    for key in PATH_LISTS:
        out += _list_faults(path.get(key), f"{where}.{key}")
    for key, one in (("locators", _locator_faults), ("api", _api_faults)):
        listed = path.get(key)
        if listed in (None, ""):
            continue
        if not isinstance(listed, list):
            out.append(f"{where}.{key} is a list (one `- ` mapping each)")
            continue
        for n, item in enumerate(listed):
            out += one(item, f"{where}.{key}[{n}]")
    return out


def _row_faults(row, n: int, ids: list, stand: str, walk: str, task_root) -> list:
    """What is wrong with ONE row of the role's record: its words against the closed lists, its requirement against the register, its
    evidence against the walk (`walk_session.capture_cited`, with the walk's stand). `[]` when it is whole."""
    if not isinstance(row, dict):
        return [f"rows[{n}] is a mapping ({', '.join(ROW_KEYS)})"]
    req = row.get("req")
    where = f"rows[{n}]" + (f" ({req})" if _text_of(req) else "")
    out = [f"{where}: unknown key `{k}` (allowed: {', '.join(ROW_KEYS)})" for k in row if k not in ROW_KEYS]
    if not (isinstance(req, str) and REQ_ID.fullmatch(req)):
        out.append(f"{where}: `req` is a requirement id of the register (R-n); got {str(req)[:40]!r}")
    elif req not in ids:
        out.append(f"{where}: {req} is not in the register ({', '.join(ids[:12])}{' ...' if len(ids) > 12 else ''}); a row is for a requirement of the register")
    status, blocked = row.get("status"), row.get("blocked_by")
    stopped_statuses = _words("blocked_by_required_for")
    if status not in _words("statuses"):
        out.append(f"{where}: `status` is one of: {', '.join(_words('statuses'))}; got {str(status)[:40]!r}")
    if blocked not in (None, "") and blocked not in _words("blocked_by"):
        out.append(f"{where}: `blocked_by` is one of: {', '.join(_words('blocked_by'))}; got {str(blocked)[:40]!r}")
    elif status in stopped_statuses and blocked in (None, ""):
        out.append(f"{where}: a `{status}` row says what stopped it in `blocked_by` ({', '.join(_words('blocked_by'))})")
    elif blocked not in (None, "") and status in _words("statuses") and status not in stopped_statuses:
        out.append(f"{where}: `blocked_by` is only for {' / '.join(stopped_statuses)} rows (who or what stopped it); a `{status}` row "
                   "cites its capture in `evidence` and has no `blocked_by` - remove it")
    if not _text_of(row.get("why")):
        out.append(f"{where}: `why` is a sentence: what the walker did and saw")
    out += _path_faults(row.get("path"), f"{where}.path")
    evidence, quote = row.get("evidence"), row.get("quote")
    listed = evidence if isinstance(evidence, list) else []
    if evidence not in (None, "") and (not isinstance(evidence, list) or not all(_text_of(e) for e in evidence)):
        out.append(f"{where}: `evidence` is a list of capture paths (one `- <path>` each)")
        return out
    if blocked in _words("no_capture_needed") and not listed:
        return out
    if not listed:
        out.append(f"{where}: a row cites a capture of this walk in `evidence` (only `blocked_by: nature` needs none): "
                   "take it with `walk_session.py look` or `step` and copy its path from the printed JSON")
        return out
    if quote in (None, "") or not isinstance(quote, str):
        out.append(f"{where}: `quote` is words copied from the captures in `evidence`, as the capture holds them")
        return out
    if REQ_ID.fullmatch(str(req or "")):
        for path in listed:
            reason = WS.capture_cited(task_root, walk, req, path, quote, stand)
            if reason:
                out.append(f"{where}: evidence `{path[:120]}`: {reason}")
    return out


def put_problems(task_root, record, attempt) -> list:
    """What is wrong with the role's record (J-C3), each with its door; `[]` when it can be written. `record` is the parsed mapping, `attempt`
    the open attempt (the walk and the stand come from it, never from the record). Data only (AR-29): the shape of the form, the words of the
    closed lists, ONE row per requirement of the register and none outside it, and every cited capture tied to this walk's attempt of that
    requirement. Whether a row is true is for the reader of the record."""
    walk, stand = str(attempt.get("walk") or ""), str(attempt.get("env") or "")
    if not walk or not stand:
        return ["the attempt names no walk or no stand, so no capture can be tied to one; the driver opens it again (`first_look.py begin`)"]
    register, why = _register(task_root)
    if register is None:
        return [f"the register cannot be read now ({why}): a first look is about its requirements; record the reason with `put --null register_unreadable`"]
    ids = register["ids"]
    if not isinstance(record, dict):
        return ["the record is a mapping with `rows:` (one mapping per requirement) and optional `gaps:`; see references/artifact-contract-first-look.md"]
    out = [f"unknown key `{k}` (allowed: {', '.join(TOP_KEYS)}; `{'`, `'.join(SENT_BY_CODE)}` are written by the code)"
           for k in record if k not in TOP_KEYS and k not in SENT_BY_CODE]
    rows = record.get("rows")
    if not isinstance(rows, list) or not rows:
        out.append("`rows` is one mapping per requirement of the register (" + (", ".join(ids[:12]) or "the register holds none")
                   + (" - an empty register is `put --null empty_register`" if not ids else "") + ")")
        return out
    seen: dict = {}
    for n, row in enumerate(rows):
        out += _row_faults(row, n, ids, stand, walk, task_root)
        req = row.get("req") if isinstance(row, dict) else None
        if isinstance(req, str):
            if req in seen:
                out.append(f"rows[{n}] ({req}): a second row for {req} (rows[{seen[req]}]); one row per requirement")
            seen.setdefault(req, n)
    absent = [r for r in ids if r not in seen]
    if absent:
        out.append(f"no row for {', '.join(absent)}: every requirement of the register has one row (a requirement the stand does not show is "
                   "`missing`, never an absent row)")
    out += _list_faults(record.get("gaps"), "`gaps`")
    return out


def _sides_met(task_root) -> dict:
    """{side: reality} of the sides of the story that are not `real` - and `{}` for a story with every side real (then the record carries no
    `sides_met`). A reality that cannot be read is not `real` either (AR-28)."""
    pipeline = hooklib.read_json(Path(task_root) / "pipeline.json", {}, kind=dict)
    return {name: side["reality"] for name, side in C.story_sides(pipeline).items() if side["reality"] != "real"}


def _stand_build(task_root, attempt: dict) -> str:
    """`confirmed` when the person's word for this story and this (stand, profile) is a `deployed` row whose revision is the one head of
    the story's one implementation entry; else `not_established` (M14). The word is the person's, usually given at gate A, so the first look
    mostly says `not_established`, and that is meant: the stand may be an old build."""
    heads = attempt.get("source_head") if isinstance(attempt.get("source_head"), dict) else {}
    if len(heads) != 1:
        return "not_established"
    head = str(next(iter(heads.values())))
    profiles = WS.read_record(task_root, attempt.get("walk")).get("profiles") if attempt.get("walk") else None
    profiles = profiles if isinstance(profiles, dict) else {}
    for key in sorted(profiles, key=lambda k: (k != "ui", k)):
        word = SI.task_confirmation(task_root, str(attempt.get("env") or ""), str(profiles[key]))
        if word and word.get("kind") == "deployed" and COMMIT.fullmatch(head) and str(word.get("revision")) == head:
            return "confirmed"
    return "not_established"


def sides_met(task_root) -> dict:
    """The public reader of `_sides_met` (AR-13): {side: reality} of the sides of the story that are not real, `{}` when every side is real."""
    return _sides_met(task_root)


def register_ids(task_root) -> tuple:
    """The public reader of the ids the record must cover (AR-13): `(ids, "")` - the register's R-n in id order, the one sort of `_register` -
    or `([], why)` when the register cannot be read."""
    register, why = _register(task_root)
    return (list(register["ids"]), "") if register else ([], why)


def _frame(task_root, attempt: dict) -> dict:
    """The fields the code writes into every record (a role's values for them are dropped)."""
    out = {"walked_at": _now(), "walk": str(attempt.get("walk") or ""), "stand": str(attempt.get("env") or ""),
           "stand_build": _stand_build(task_root, attempt) if attempt else "not_established",
           "source_head": dict(attempt.get("source_head") or {}), "register_hash": str(attempt.get("register_hash") or "")}
    met = _sides_met(task_root)
    if met:
        out["sides_met"] = met
    return out


def _load_input(file) -> tuple:
    """`(mapping, "")` or `(None, why)`: the role's file, in the form's YAML subset (`handoff.parse`)."""
    try:
        text = Path(file).read_bytes().decode("utf-8")
    except OSError as exc:
        return None, f"--file {str(file)[:120]} cannot be read ({type(exc).__name__}); pass the path of the YAML file you wrote"
    except UnicodeDecodeError:
        return None, "--file is not UTF-8 text; write it as UTF-8"
    if text.lstrip("﻿").lstrip().startswith(("{", "[")):
        return None, "--file is JSON or a flow mapping; write it as block YAML (`rows:` and one `- req: R-1` mapping per requirement)"
    parsed = handoff.parse(text).data
    if not isinstance(parsed, dict) or not parsed:
        return None, "--file holds no YAML mapping; write `rows:` with one mapping per requirement of the register"
    return parsed, ""


def _store(task_root, record: dict) -> list:
    try:
        GT.write_yaml(_record_path(task_root), record)
    except TypeError as exc:
        return [f"the record cannot be written in the form's YAML subset: {exc}"]
    except OSError as exc:
        return [f"the record could not be written ({type(exc).__name__}: {exc})"]
    return []


def put(task_root, file, null_reason="") -> dict:
    """Write the record of the first look. `{"written": bool, "problems": [text], "null": reason, "rows": n, "ignored": [keys]}`.

    Without `null_reason`: the walk and the stand are the attempt's (no attempt: refused, "the walk is not open", the driver opens it), the
    file is checked by `put_problems`, and a whole record is written with the fields the code owns; the attempt then reads `written`. With
    `null_reason` (one of the declared words): `{null, rows: [], gaps: [the reason]}` - a declared empty outcome, written without a
    file and with or without an attempt, and it leaves the attempt as it was (an empty record is no attempt, and is not fresh when the
    stand or the code changes: `due` reads the attempt, not this record)."""
    task = Path(task_root)
    attempt = read_attempt(task)
    if null_reason:
        reasons = _words("null_reasons")
        if null_reason not in reasons:
            return {"written": False, "null": "", "rows": 0, "ignored": [],
                    "problems": [f"--null is why no first look was walked, one of: {', '.join(reasons)}; got {str(null_reason)[:60]!r}"]}
        existing = read(task)
        if not existing["problem"] and not existing["null"] and not existing["stale"]:
            return {"written": False, "null": "", "rows": 0, "ignored": [],
                    "problems": ["a walked first look of these heads and this register exists and is current; a null record does not replace it "
                                 "(a null is for a story with no walked record, or a stale one) - leave it, the driver reads the walked record"]}
        heads, reg_hash = current_keys(task)       # a null record is about the code and register of NOW, whatever an old attempt walked
        frame = _frame(task, {"source_head": json.loads(heads), "register_hash": reg_hash})
        record = {**frame, "null": null_reason, "rows": [], "gaps": [f"no first look: {null_reason.replace('_', ' ')}"]}
        problems = _store(task, record)
        return {"written": not problems, "null": null_reason, "rows": 0, "ignored": [], "problems": problems}
    if not attempt:
        return {"written": False, "null": "", "rows": 0, "ignored": [],
                "problems": ["the first-look walk for this story is not open; the driver opens it (`first_look.py begin`) - "
                             "record what you saw as a gap in your handover and halt"]}
    text, reg_hash = current_keys(task)
    if _canon(attempt.get("source_head")) != text or attempt.get("register_hash") != reg_hash:
        return {"written": False, "null": "", "rows": 0, "ignored": [],
                "problems": ["the code or the register changed since this walk was opened, so its rows would be about other things than the "
                             "walk saw; record what you saw as a gap in your handover and halt - the driver opens a new attempt "
                             "(`first_look.py begin`) for the current code and register"]}
    parsed, why = _load_input(file)
    if parsed is None:
        return {"written": False, "null": "", "rows": 0, "ignored": [], "problems": [why]}
    problems = put_problems(task, parsed, attempt)
    if problems:
        return {"written": False, "null": "", "rows": 0, "ignored": [], "problems": problems}
    frame = _frame(task, attempt)
    gaps = parsed.get("gaps") if isinstance(parsed.get("gaps"), list) else []
    record = {**frame, "rows": [{k: v for k, v in row.items() if v not in (None, "")} for row in parsed["rows"]],
              "gaps": [str(g) for g in gaps]}
    problems = _store(task, record)
    if not problems:
        _write_attempt(task, dict(attempt, outcome="written"))
    return {"written": not problems, "null": "", "rows": len(record["rows"]), "problems": problems,
            "ignored": [k for k in SENT_BY_CODE if k in parsed]}


# --- the questions (pure) ----------------------------------------------------------------------------------------------------

def read(task_root) -> dict:
    """THE reader of the record: `{rows, gaps, null, stale, stand_build, source_head, register_hash, walk, problem, absent}` (`absent`: the file does not exist; `state` classifies). `source_head` is the
    record's map. `stale` is true when the record's heads differ from the current heads (value by value; `unmeasured: ...` is a value) or its
    register hash from the current one, or the register cannot be read now. A record that is absent or cannot be read has `problem` and no
    rows; whether a stale record's rows are used is the caller's, and a stale record never confirms anything."""
    out = {"rows": [], "gaps": [], "null": "", "stale": False, "stand_build": "", "source_head": {}, "register_hash": "", "walk": "",
           "problem": "", "absent": False}
    path = _record_path(task_root)
    if not path.is_file():
        out["absent"] = True
        out["problem"] = "work/first-look.yaml does not exist: no first look was written for this story"
        return out
    try:
        doc = handoff.parse(path.read_bytes().decode("utf-8")).data
    except (OSError, UnicodeDecodeError) as exc:
        out["problem"] = f"work/first-look.yaml cannot be read ({type(exc).__name__})"
        return out
    rows, heads = doc.get("rows") if isinstance(doc, dict) else None, doc.get("source_head") if isinstance(doc, dict) else None
    if not isinstance(doc, dict) or not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows) \
            or not isinstance(heads, dict) and heads not in (None, ""):
        out["problem"] = "work/first-look.yaml is not a first-look record (rows and source_head are not the shapes the form says)"
        return out
    gaps = doc.get("gaps")
    out.update(rows=rows, gaps=[str(g) for g in gaps] if isinstance(gaps, list) else [], null=str(doc.get("null") or ""),
               stand_build=str(doc.get("stand_build") or ""), source_head={str(k): str(v) for k, v in (heads or {}).items()},
               register_hash=str(doc.get("register_hash") or ""), walk=str(doc.get("walk") or ""))
    text, reg_hash = current_keys(task_root)
    if not reg_hash:
        out["stale"], out["problem"] = True, "the register cannot be read now, so the record cannot be told current"
    elif _canon(out["source_head"]) != text or out["register_hash"] != reg_hash:
        out["stale"] = True
    return out


def state(task_root) -> dict:
    """THE classification of the record's state, for every consumer that renders it (AR-15): `{kind, got, error}`. `kind` is `absent` (no
    record), `null` (a declared empty first look), `stale` (other code or register; it confirms nothing), `unreadable` (a record that cannot be
    read), `ok` (rows to use) or `error` (the reader itself raised; `error` is the exception's name). The order is fixed: null, stale,
    absent, unreadable, ok - a consumer decides only the TEXT of each kind. Never raises."""
    try:
        got = read(task_root)
    except Exception as exc:  # noqa: BLE001 - a consumer's courtesy block must still be built
        return {"kind": "error", "got": {}, "error": type(exc).__name__}
    if got["null"]:
        kind = "null"
    elif got["stale"]:
        kind = "stale"
    elif got["absent"]:
        kind = "absent"
    elif got["problem"]:
        kind = "unreadable"
    else:
        kind = "ok"
    return {"kind": kind, "got": got, "error": ""}


def _floor(cfg) -> int:
    """`first_look.reachable_floor_percent` of the config: a whole number 0-100, else the default (AR-3)."""
    value = cfg
    for key in FLOOR_KEY:
        value = value.get(key) if isinstance(value, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 100 else FLOOR_DEFAULT


def share(task_root, cfg) -> dict:
    """`{reachable, counted, share, floor, below, problem}` of the record. `counted` leaves out the rows blocked by `access` and `nature` (what
    no walker can reach or see is not the stand's fault, J-7); `reachable` is the counted rows whose status is a `reachable` word. `below`
    is true only when something was counted AND the share is under the floor; a record that is absent, unreadable, stale or null is never
    below (`problem` says why) and nothing counted has no share (`None`)."""
    floor = _floor(cfg)
    got = read(task_root)
    out = {"reachable": 0, "counted": 0, "share": None, "floor": floor, "below": False, "problem": got["problem"]}
    if got["problem"]:
        return out
    if got["null"]:
        out["problem"] = f"the first look was not walked (null: {got['null']})"
        return out
    if got["stale"]:
        out["problem"] = "the first look is about other code or another register than the current ones"
        return out
    counted = [r for r in got["rows"] if r.get("blocked_by") not in _words("share_excludes")]
    reach = [r for r in counted if r.get("status") in _words("reachable")]
    out.update(reachable=len(reach), counted=len(counted))
    if counted:
        out["share"] = round(100 * len(reach) / len(counted), 1)
        out["below"] = len(reach) * 100 < floor * len(counted)
    return out


def due(task_root, pipeline, cfg) -> tuple:
    """`(bool, null_reason, why)`: is a first look to be walked now. Pure. False with `no_code_yet` when a deliverable side is absent; with
    `empty_register` / `register_unreadable`; with `no_stand` when no stand is named or it is not confirmed; False with no reason when an
    attempt on THESE heads and register already exists with the outcome walking, written or nothing_written (the paid dispatch is not
    repeated); an `open_failed` attempt (the role never ran, nothing was paid) is retried while `open_failures` <= `open_retry_max`, then
    False with `walk_not_opened`. Otherwise true. An empty or null record is no attempt. An attempt file that cannot be read is no attempt."""
    _ = cfg
    if C.parks_after_s5(pipeline):
        return False, "no_code_yet", "a side this story delivers does not exist yet"
    register, why = _register(task_root)
    if register is None:
        return False, "register_unreadable", why
    if not register["ids"]:
        return False, "empty_register", "the register holds no requirement"
    environment = pipeline.get("environment") if isinstance(pipeline, dict) else None
    if not environment or pipeline.get("environment_pending"):
        return False, "no_stand", "no stand is named and confirmed for this story"
    text, reg_hash = current_keys(task_root)
    attempt = read_attempt(task_root)
    if attempt and _canon(attempt.get("source_head")) == text and attempt.get("register_hash") == reg_hash:
        outcome = attempt["outcome"]
        if outcome in _words("attempt_settled"):
            return False, "", f"a first look of these heads and this register is already {outcome}"
        failures = int(attempt.get("open_failures") or 0)
        if failures <= int(data().get("open_retry_max") or 0):
            return True, "", f"the walk could not be opened {failures} time(s) on these heads; it is tried again"
        return False, "walk_not_opened", f"the walk could not be opened {failures} times on these heads"
    return True, "", "no first look of these heads and this register yet"


def continued(task_root, pipeline) -> bool:
    """Did the person say `continue` for THESE heads and THIS register: `pipeline.first_look_continue` (the controller's record of the
    word) carries the pair `current_keys` produces now. An unreadable register never matches."""
    word = pipeline.get("first_look_continue") if isinstance(pipeline, dict) else None
    if not isinstance(word, dict):
        return False
    text, reg_hash = current_keys(task_root)
    return bool(reg_hash) and word.get("source_head") == text and word.get("register_hash") == reg_hash


# --- the command line --------------------------------------------------------------------------------------------------------

def _command(argv) -> str:
    for token in argv:
        if token in SUBCOMMANDS:
            return f"{SCRIPT} {token}"
    return SCRIPT


def _parser(command: str) -> argparse.ArgumentParser:
    parser = RefusingParser(command=command, prog=SCRIPT, description=__doc__.split("\n\n")[0], epilog=epilog(SCRIPT),
                            formatter_class=argparse.RawDescriptionHelpFormatter)
    subs = parser.add_subparsers(dest="sub", required=True, parser_class=RefusingParser)
    for name in SUBCOMMANDS:
        sub = subs.add_parser(name, command=f"{SCRIPT} {name}", help=name)
        sub.add_argument("--task-root", required=True, help="the story folder (holds pipeline.json and work/)")
        if name == "begin":
            sub.add_argument("--dispatch", required=True, help="the dispatch id of the walk (it is the walk id)")
            sub.add_argument("--env", required=True, help="the name of the stand, exactly as the config names it")
        if name == "end":
            sub.add_argument("--outcome", required=True, help="written | nothing_written | open_failed")
        if name == "put":
            sub.add_argument("--file", help="your rows, a YAML file")
            sub.add_argument("--null", default="", help="no first look was walked: one of the reasons of references/first-look-statuses.json")
        if name == "show":
            sub.add_argument("--json", action="store_true", help="print the record, the attempt and the current keys as JSON")
    return parser


def _show(task, as_json: bool) -> int:
    got, attempt = read(task), read_attempt(task)
    text, reg_hash = current_keys(task)
    if as_json:
        pipeline = hooklib.read_json(Path(task) / "pipeline.json", {}, kind=dict)
        try:
            cfg = hooklib.load_config() or {}
        except Exception:  # noqa: BLE001 - an unreadable config gives the default floor
            cfg = {}
        is_due, reason, why = due(task, pipeline, cfg)       # the questions the driver asks (t-2277 FL-5 m4): one reader, shown, not re-derived
        print(json.dumps({"record": got, "attempt": attempt, "current_keys": {"source_head": text, "register_hash": reg_hash},
                          "due": {"due": is_due, "reason": reason, "why": why}, "share": share(task, cfg)},
                         ensure_ascii=False))
        return 0
    if got["problem"]:
        print(f"first look: {got['problem']}")
    else:
        print(f"first look of walk {got['walk'] or '-'}: {len(got['rows'])} row(s)" + (f", null: {got['null']}" if got["null"] else "")
              + (", STALE (the code or the register changed since)" if got["stale"] else "") + f", stand build: {got['stand_build'] or '-'}")
        for row in got["rows"]:
            print(f"{row.get('req')} | {row.get('status')}" + (f" | {row.get('blocked_by')}" if row.get("blocked_by") else "")
                  + f" | {row.get('why')}")
        for gap in got["gaps"]:
            print(f"gap: {gap}")
    print(f"attempt: {attempt.get('outcome', 'none')}" + (f" (dispatch {attempt['dispatch']})" if attempt else ""))
    return 0


def _cli(argv) -> int:
    args = hooklib.exact_options(_parser(_command(argv))).parse_args(argv)
    task = hooklib.story_of(SCRIPT, root=args.task_root, key_flag=None)
    command = f"{SCRIPT} {args.sub}"
    if args.sub == "begin":
        print(json.dumps(begin(task, args.dispatch, args.env), ensure_ascii=False))
        return 0
    if args.sub == "end":
        done = end(task, args.outcome)
        if not done["ok"]:
            return role_cli.refuse(command, done["problem"])
        print(json.dumps(done["attempt"], ensure_ascii=False))
        return 0
    if args.sub == "put":
        if bool(args.file) == bool(args.null):
            return role_cli.refuse(command, "give exactly one of --file <your rows> and --null <reason>")
        done = put(task, args.file, args.null)
        if not done["written"]:
            return role_cli.refuse(command, " | ".join(done["problems"]))
        print(json.dumps(done, ensure_ascii=False))
        return 0
    return _show(task, args.json)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    return run_guarded(_command(argv), lambda: _cli(argv))


if __name__ == "__main__":
    sys.exit(main())
