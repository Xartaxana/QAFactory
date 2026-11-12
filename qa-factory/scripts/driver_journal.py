"""The one reader of the driver's journal (artifacts/<task>/state/driver-runs.jsonl).

In a driver run every role and every conductor call is its own `claude -p` session, and the
driver journals each launch: kind, role, dispatch, stage, session_id, num_turns, total_cost_usd.
The cost capture only ever sees `orchestrator` with no agents, so the journal is the one record
of who did what. Import-only: the dashboard, the retro and the metrics read it through here, so
that a session is bound to a task, priced and labelled the same way on every page.

What the journal's `total_cost_usd` means is NOT the same in every journal. Measured 30.09 on
four real runs: in cmp1 the figure is a running total of a resumed session (it never falls); in
three others it FALLS inside a session (driver3 session 29240aa1: $0.78, $9.51, $3.39, $0.19),
because there the figure is the cost of ONE call. Reading "the last row" of the second kind
prints $0.19 for a session that cost more than $15. So the reader only trusts a session whose
totals never fall; for any other session the driver record is unknown (None) and the caller
falls back to the cost file and says so. A fall anywhere proves the whole root is per-call, so
under such a root every session with more than one usable row is unknown too, and so is a
session named by several journals (its rows here are one journal's part of it): callers price
a root with `root_charged`, one entry with `entry_charged`, never with `driver_charged` of one
journal's rows. The remaining blind spot: a per-call root in which no session ever falls is
priced as if its totals were running totals (B-222).

Error direction (this reader is used in a gate role): it may fail to bind and it may say
"unknown"; it never binds a session the journal does not literally name and, but for that one
blind spot, never returns a wrong number.
"""
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from hooklib import sorted_paths

JOURNAL_NAME = "driver-runs.jsonl"
REPLACEMENT_CHAR = chr(0xFFFD)   # what the replacing decoder puts for a byte it cannot read


# --------------------------------------------------------------------------------- numbers

def usable_total(value):
    """A `total_cost_usd` as a float, or None when it cannot be a charged total: a bool (True
    is not $1), NaN, infinity, a negative number, a string ("1.0" is never coerced), a number
    too large for a float. Never a guess."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _usable_totals(rows) -> list:
    return [t for t in (usable_total(r.get("total_cost_usd")) for r in rows) if t is not None]


def total_falls(rows) -> bool:
    """True when a session's usable total is LOWER than the previous usable total of the same
    session, in file order: the figure is then a per-call cost, not a running total."""
    totals = _usable_totals(rows)
    return any(later < earlier for earlier, later in zip(totals, totals[1:]))


def driver_charged(rows):
    """What the CLI charged for one session: the last usable `total_cost_usd`, a running total
    across its resumes, so rows are never summed. None (unknown) when no row carries a usable
    number, and None when the total ever FALLS between two rows (see the module note): the
    last row of such a session is one call's cost, not the session's."""
    totals = _usable_totals(rows)
    if not totals or total_falls(rows):
        return None
    return totals[-1]


WHY_NO_TOTAL = "no usable total"
WHY_FALLS = "falls"
WHY_SEVERAL_JOURNALS = "named by several journals"
WHY_PER_CALL_ROOT = "several rows under a root where totals are per call"


def _multi_journal(entry) -> bool:
    return bool(entry.get("multi_journal")) or len(entry.get("journals") or []) > 1


def entry_charged(entry):
    """`driver_charged` for one `parse_driver_runs` entry. None when the session is named by
    more than one journal: the entry's rows are the chosen journal's part only, and the last
    total of a part is not what the session cost (T1 holds it at $1.00, T2 at $3.00). Callers
    with a whole root use `root_charged`, which adds the per-root rule."""
    if _multi_journal(entry):
        return None
    return driver_charged(entry["rows"])


def root_charged(by_session) -> tuple:
    """(charged, unknown) for the first result of `parse_driver_runs`: `charged` maps EVERY
    session id to its driver record (a float, or None), `unknown` lists `(session, why)` for
    each session priced None, sorted by session id, `why` one of the WHY_* strings.

    What a row's total means is a property of the journal, not of a session (module note): if
    ANY session under the root falls, the root is per-call, so every session with more than one
    usable row is unknown (a per-call session whose costs happen to rise is not told apart from
    a running one); a session with a single usable row keeps its value. A root with no falling
    session prices each session as `entry_charged` does. Precedence of the reason: no usable
    total, falls, several journals, per-call root."""
    per_call_root = any(total_falls(entry["rows"]) for entry in by_session.values())
    charged, unknown = {}, []
    for sid in sorted(by_session):
        entry = by_session[sid]
        usable = _usable_totals(entry["rows"])
        why = None
        if not usable:
            why = WHY_NO_TOTAL
        elif total_falls(entry["rows"]):
            why = WHY_FALLS
        elif _multi_journal(entry):
            why = WHY_SEVERAL_JOURNALS
        elif per_call_root and len(usable) > 1:
            why = WHY_PER_CALL_ROOT
        charged[sid] = None if why else usable[-1]
        if why:
            unknown.append((sid, why))
    return charged, unknown


def row_increments(rows) -> list:
    """One entry per row, in file order: the row's total minus the previous usable total of the
    SAME session (0 before the first usable one). None when the row's own total is unusable,
    when the increment is negative, and when the PREVIOUS row of the session has an unusable
    total: what that row cost is unknown and would otherwise land inside this row's increment.
    The increments of a session whose totals are all usable and never fall telescope to its
    charged total."""
    out, previous, after_unusable = [], 0.0, False
    for row in rows:
        total = usable_total(row.get("total_cost_usd"))
        if total is None:
            out.append(None)
            after_unusable = True
            continue
        # A fall is unknown money, not a negative dollar; the next row is measured from THIS
        # row's total (the previous usable one in file order), fallen or not.
        out.append(total - previous if total >= previous and not after_unusable else None)
        previous, after_unusable = total, False
    return out


def _turns_of(row) -> int:
    try:
        return int(row.get("num_turns") or 0)
    except (TypeError, ValueError):
        return 0


# --------------------------------------------------------------------------------- roles

def driver_role(rows) -> tuple:
    """(label, mixed) — the first `kind: role` row names the session's role; a session with
    only conductor rows is `conductor`; one with neither (a delivery row alone, an unknown
    kind) is None, and the caller keeps the capture's own attribution. `mixed` says a session's
    role rows named different roles (the first one wins, the caller counts it)."""
    roles = [str(r.get("role") or "").strip() for r in rows if r.get("kind") == "role"]
    roles = [r for r in roles if r]
    if roles:
        return roles[0], len(set(roles)) > 1
    if any(r.get("kind") == "conductor" for r in rows):
        return "conductor", False
    return None, False


def record_label(rows) -> tuple:
    """(label, mixed) for a per-(session, dispatch) record. Only `kind == "conductor"` is the
    conductor. A session that is neither a role's nor the conductor's (the S0 ticket call
    journals `kind: "ticket"`) is a record of its own, named by its kind, and is not the
    orchestrator: whether the ticket call belongs to "conductor + code" is the owner's word.
    None when no row names a kind at all."""
    label, mixed = driver_role(rows)
    if label is not None:
        return label, mixed
    for row in rows:
        kind = row.get("kind")
        if isinstance(kind, str) and kind.strip():
            return kind.strip(), False
    return None, False


CONDUCTOR_LABEL = "conductor"
SCOUT_LABEL = "qa-scout"
ORCHESTRATOR_LABEL = "orchestrator"
CHAT_LABEL = "person's chat"
UNLABELLED = "unlabelled"

# What FETCHES data is the scout's work, whichever process ran it (owner, 30.09). Which journal
# kinds and which agent types fetch data is closed variety, so it lives in a data file (FR-13), not
# in a list here: a project's new fetching agent is one line there.
LABELS_PATH = Path(__file__).resolve().parent.parent / "references" / "agent-labels.json"
_LABEL_KEYS = ("data_fetch_kinds", "data_fetch_agent_types")
_label_cache: dict = {}


def _read_label_data(path) -> tuple:
    """(kinds, agent types, warning) of the data file. Anything unreadable or of the wrong shape is
    an EMPTY pair of sets and one warning line: a labeller must never raise, and with no table every
    name keeps its own label (a remote call stays `<consumer> (remote)`)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return frozenset(), frozenset(), (f"The agent-label table {Path(path).name} could not be read ({type(exc).__name__}): "
                                          "data-fetching calls keep their own names, not the scout's, until it is repaired.")
    sets = []
    for key in _LABEL_KEYS:
        values = data.get(key) if isinstance(data, dict) else None
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            return frozenset(), frozenset(), (f"The agent-label table {Path(path).name} is malformed ({key} must be a list of "
                                              "strings): data-fetching calls keep their own names, not the scout's, until it is repaired.")
        sets.append(frozenset(v.strip() for v in values if v.strip()))
    return sets[0], sets[1], ""


def label_data(path=None) -> tuple:
    """(data-fetch kinds, data-fetch agent types, warning) read from `path` (default: LABELS_PATH).
    Re-read when the file's size or mtime changes. `warning` is "" when the table is fine."""
    path = Path(path) if path is not None else Path(LABELS_PATH)
    try:
        stat = path.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        stamp = None
    cached = _label_cache.get(str(path))
    if cached is None or cached[0] != stamp:
        cached = (stamp, _read_label_data(path))
        _label_cache[str(path)] = cached
    return cached[1]


def label_data_warning() -> str:
    """The one warning line for a broken agent-label table, or "" (a page prints it once)."""
    return label_data()[2]


def agent_label(record) -> str:
    """The ONE name of the agent a record of spend belongs to, for every page that groups money
    by agent (the price function, the dashboard). Never None: a record with no name is
    `UNLABELLED`, so a row by agent always exists.

    `record` is a journal record, as `record_label` takes it (a list of one session's or pair's
    rows, or one row): the role's name; `conductor` for a conductor call; `qa-scout` for a
    data-fetching call (a kind in the data file's `data_fetch_kinds`, the S0 ticket call: a ticket
    is NOT its own row and NOT the conductor); any other kind keeps its kind as its name. Or a
    non-journal source, a dict `{"source": ...}`: "subagent" (`agent_type`: the subagent file's own
    name; `qa-scout` when that type is in `data_fetch_agent_types`), "orchestrator" (the main
    chain of an orchestrator-mode story), "chat" (a chat session bound to a task: the person's
    chat), "remote" (`consumer_agent`: a remote call, `qa-scout` when the consumer is in
    `data_fetch_agent_types`, else `<consumer_agent> (remote)`; with no receipt its cost is
    unknown, which the caller says). Names are matched EXACTLY (after trimming blanks): the case
    is part of the name, `Jira-Assistant` is not `jira-assistant`. A table that cannot be read
    makes every such name keep its own label (`label_data_warning` says so)."""
    kinds, agent_types, _warning = label_data()
    if isinstance(record, dict) and "source" in record:
        source = record.get("source")
        if source == "orchestrator":
            return ORCHESTRATOR_LABEL
        if source == "chat":
            return CHAT_LABEL
        name = str(record.get("agent_type" if source == "subagent" else "consumer_agent") or "").strip()
        if source == "subagent":
            return SCOUT_LABEL if name in agent_types else (name or UNLABELLED)
        if source == "remote":
            return SCOUT_LABEL if name in agent_types else f"{name or UNLABELLED} (remote)"
        return UNLABELLED
    rows = [record] if isinstance(record, dict) else [r for r in (record or []) if isinstance(r, dict)]
    label, _mixed = driver_role(rows)
    if label is not None:
        return label
    for row in rows:
        kind = row.get("kind")
        if isinstance(kind, str) and kind.strip():
            return SCOUT_LABEL if kind.strip() in kinds else kind.strip()
    return UNLABELLED


def pair_key(row) -> str:
    """The dispatch half of a row's (session, dispatch) key. A conductor row carries
    `dispatch: ""`, so its pair key is (session, ""); an absent or null dispatch is "" too."""
    dispatch = row.get("dispatch")
    return "" if dispatch is None else str(dispatch)


def pair_records(session_id, rows) -> list:
    """One record per (session, dispatch) of ONE session's rows, in order of first appearance:
    {"session", "dispatch", "role", "mixed", "rows", "turns", "cost"}.

    cost = the sum of the increments of the pair's rows (`row_increments`), so two dispatches
    that take turns inside one resumed session share the total between them without creating
    or losing a cent. It is None (unknown, never a number) when any of the pair's increments is
    negative or unusable (a row right after an unusable-total row included, see
    `row_increments`), and for EVERY pair of a session whose total falls: there the figure is
    a per-call cost and an increment of it is not money. Pair costs know nothing of the root
    (`root_charged`) or of several journals (`entry_charged`): the caller applies those."""
    increments = row_increments(rows)
    falls = total_falls(rows)
    pairs: dict = {}
    for row, increment in zip(rows, increments):
        pairs.setdefault(pair_key(row), []).append((row, increment))
    out = []
    for dispatch, members in pairs.items():
        member_rows = [m[0] for m in members]
        unknown = falls or any(m[1] is None for m in members)
        label, mixed = record_label(member_rows)
        out.append({"session": session_id, "dispatch": dispatch, "role": label, "mixed": mixed,
                    "rows": len(member_rows), "turns": sum(_turns_of(r) for r in member_rows),
                    "cost": None if unknown else math.fsum(m[1] for m in members)})
    return out


def falling_sessions(by_session) -> list:
    """The ids of the sessions (of `parse_driver_runs`'s first result) whose driver record is
    unknown because their total falls, sorted. The page says which sessions these are."""
    return sorted(sid for sid, entry in by_session.items() if total_falls(entry["rows"]))


# --------------------------------------------------------------------------------- binding

def parse_ts(value):
    """A row's `ts` as a UTC-aware datetime, or None. ONE normalisation: an aware time is
    converted to UTC, a naive time is read AS UTC (the driver writes `+00:00`; a naive stamp is
    never compared with an aware one). Not a string, or not ISO 8601, is None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
        if moment.tzinfo is None:
            return moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc)
    except (ValueError, OverflowError, TypeError):
        return None


def _journal_paths(root) -> list:
    """[(task, path)] for artifacts/<task>/state/driver-runs.jsonl, depth 1 only (an archived
    story's journal is still read; a legacy archive/ folder is not descended into). A root with
    no artifacts folder, or a config the artifact root cannot be resolved from, is no journal."""
    # Imported OUTSIDE the try: a missing hooklib is a broken install, not "no journal".
    from hooklib import artifact_root
    try:
        art = artifact_root(root=Path(root))
        folders = sorted_paths(d for d in art.iterdir() if d.is_dir()) if art.exists() else []
    except (OSError, ValueError):
        # OSError: the folder or the config file cannot be read. ValueError: the config is not
        # JSON (JSONDecodeError, UnicodeDecodeError) or names an empty artifact_root, or the path
        # is malformed. Anything else (TypeError, AttributeError, a bug in hooklib) propagates.
        return []
    return [(d.name, d / "state" / JOURNAL_NAME) for d in folders if (d / "state" / JOURNAL_NAME).is_file()]


def read_rows(path) -> list:
    """The object rows of one journal, in file order. Read as utf-8-sig (a BOM would make the
    first line unparseable and drop row 1); split on "\\n" only, because str.splitlines also
    breaks on U+2028 and other separators a JSON string may legally hold. A broken line, a line
    that is not an object, an unreadable file: skipped, never an exception."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    except Exception:
        return []
    rows = []
    for line in text.split("\n"):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def parse_driver_runs(root) -> tuple:
    """(by_session, spread): by_session maps a session id to
    {"task", "rows", "journals", "no_timestamps", "multi_journal"}; spread maps it to how many
    task journals name it.

    A session is bound only by a row whose `session_id` is a non-empty STRING, compared
    literally (case and trailing whitespace count; an integer id is not converted). Rows
    without one (the delivery row) carry no cost and are skipped, and so is a row whose id
    holds U+FFFD: the file is read with a replacing decoder, so two different undecodable ids
    would merge into one. "rows" are the chosen task's rows in file order. "journals" lists
    every task name that names the session; "multi_journal" is True when there is more than one
    (its rows are then one journal's part, priced by no one: see `entry_charged`).

    A session found under several tasks is one process, never two stories': it goes to the
    task whose journal holds the EARLIEST PARSEABLE `ts` of it (`parse_ts`: UTC). A row with no
    or an unparseable ts never wins. When no candidate has a ts, the lexicographically first
    task name wins and "no_timestamps" is True (the caller says so). Equal instants go to the
    first task name too. "no_timestamps" is False for a session only one journal names."""
    found: dict = {}
    for task, path in _journal_paths(root):
        for row in read_rows(path):
            sid = row.get("session_id")
            if isinstance(sid, str) and sid and REPLACEMENT_CHAR not in sid:
                found.setdefault(sid, {}).setdefault(task, []).append(row)
    by_session, spread = {}, {}
    for sid, per_task in found.items():
        spread[sid] = len(per_task)
        earliest = {}
        for task, rows in per_task.items():
            stamps = [m for m in (parse_ts(r.get("ts")) for r in rows) if m is not None]
            if stamps:
                earliest[task] = min(stamps)
        if len(per_task) == 1:
            task, no_timestamps = next(iter(per_task)), False
        elif earliest:
            task, no_timestamps = min(earliest, key=lambda t: (earliest[t], t)), False
        else:
            task, no_timestamps = min(per_task), True
        by_session[sid] = {"task": task, "rows": per_task[task], "journals": sorted(per_task),
                           "no_timestamps": no_timestamps, "multi_journal": len(per_task) > 1}
    return by_session, spread
