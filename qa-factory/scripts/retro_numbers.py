"""Every number of the S9 retro, computed by code from the files the run already wrote.

The retro used to be an agent reading journals: `qa-retro-analyst` walked
`state/journal.jsonl`, every `state/cost/<session>.json` and the tool histograms of each
dispatch, and worked the arithmetic out in prose. On one pilot that dispatch passed 114k
tokens and was stopped by hand — a story's closing paragraph had eaten a weekly limit, and
the role had no blocking budget (`runtime_policy.py` mapped it to `discovery`, where
blocking is forced off). Arithmetic is the cheapest thing a machine does and the most
expensive thing a model does.

So the numbers come from here and the analyst gets a finished table. What it computes:
cost and tokens per stage and per role, the orchestrator's share, the three most expensive
dispatches, the cost of rework (repair rounds), rejects and gate blocks, halts and human
wait, time to the first test, and estimate against actual.

  retro_numbers.py --task TP1-15045                # the markdown table
  retro_numbers.py --task TP1-15045 --json         # the same facts as JSON
  retro_numbers.py --task TP1-15045 --output <task>/work/retro-numbers.md

The story's PRICE is one answer, `task_price.task_price`, asked ONCE per retro (P18, FR-10: the
dashboard and the budget ceiling read the same function). The story's sessions are the ones it
names by evidence (the driver's journal, a story activity segment, a chat binding), never the
ones that merely carry the ticket in a `by_task` tag (FR-24; B-223: that filter dropped 13 of
cmp1's 35 journal sessions). The retro prints what that answer says, in its own words: one
figure when the two records agree, a range when they differ, "single source (chat): nothing to
cross-check against" when the chat is the only record and no money is missing (otherwise "not
cross-checked"), what is known and why when it is incomplete. It names no record the
authoritative one, because none is.

**When a role's usage reads zero this file says `incomplete` and refuses to publish an
orchestrator share.** That zero is a known capture defect another package is fixing, and
the cost file carries `incomplete_agents: [names]` while it lasts; on TP1-15045 all six
roles read `tokens: 0` although their transcripts held 146 requests and 12.83M tokens, so
the honest share was "unknown", never "the orchestrator spent 100%".
"""
import argparse
import functools
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hooklib  # noqa: E402  (`read_json`, the one JSON reader)
from hooklib import artifacts_dir, require_project, role_name, state_dir, story_root  # noqa: E402
import runtime_paths as RP  # noqa: E402
from stage_done import clock_anomaly, clock_anomalies  # noqa: E402
import cost_capture as CC  # noqa: E402
import driver_journal as DJ  # noqa: E402
import task_price as TP  # noqa: E402
# ONE plural-by-count helper for every sentence of the price and the share that prints a count of
# sessions ("1 session", "2 sessions"): the price function's own, not a second copy (t-171).
from task_price import _plural  # noqa: E402
from hooklib import sorted_paths  # noqa: E402

STAGE_IN_PURPOSE = re.compile(r"\b(S[0-9])\b")

# The share of a story's cost the orchestrator may spend on holding it together before that
# becomes a finding about the factory. On TP2-2553 dispatching, hand-assembling
# requests, repeated acceptances and carrying context across S1-S8 took $47.86 of $100.37 and
# 123.8M tokens: management cost as much as the work it managed, and nothing anywhere bounded
# it. Read from `retro.orchestrator_share_max` in the project's config.json, as a fraction.
ORCHESTRATOR_SHARE_MAX = 0.35


# The value as parsed, or the caller's default for anything that cannot be read (`default` is each caller's own literal).
read_json = functools.partial(hooklib.read_json, errors=Exception)


def read_jsonl_known(path: Path) -> tuple:
    """`(rows, known)`: the ONE reader of a JSON-lines file. `known` is False when the file is absent or cannot be
    read - an unknown, which a caller that prints a count must not turn into a zero (FR-41). An unparsable line is
    skipped and the file is still known."""
    rows = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return [], False
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows, True


def read_jsonl(path: Path) -> list:
    return read_jsonl_known(path)[0]


def moment(value) -> datetime | None:
    if isinstance(value, (int, float)):
        try:
            from datetime import timezone
            return datetime.fromtimestamp(value, timezone.utc)
        except Exception:
            return None
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def span_seconds(start, end) -> int | None:
    a, b = moment(start), moment(end)
    if a is None or b is None:
        return None
    return max(0, int((b - a).total_seconds()))


def cost_files(task: str, root: Path | None = None, troot: Path | None = None,
               price: dict | None = None, docs: list | None = None) -> list:
    """[(path, data)] of the cost files of the sessions this story's PRICE names, and of no
    other (FR-24: evidence, never the ticket appearing in a `by_task` tag).

    It used to keep every file that mentioned the ticket, narrowed by the journal's own session
    ids. That is the B-223 defect: a session the driver launched whose file is a collapsed
    `(no task)` row carries no ticket tag at all, so 13 of cmp1's 35 journal sessions were
    dropped; and a session that only TOUCHED the ticket (the operator's own, run 5 of
    TP1-13797: $1,911.43 against the journal's $125.77) was counted. The set is now the one
    `task_price` names - the driver's journal, a story activity segment, a chat binding - and
    `price`/`docs` let a caller that already asked hand the answer in (one call per retro)."""
    base = Path(root) if root is not None else state_dir()
    docs = docs if docs is not None else all_cost_files(base)
    price = price if price is not None else price_of(task, base, docs)
    named = {str(r.get("session")) for r in price.get("sessions") or [] if isinstance(r, dict)}
    return [(path, data) for path, data in docs if session_key(path, data) in named]


def session_key(path, data) -> str:
    """The id a cost file answers to in `task_price`: its file name (the session id the capture
    writes it under)."""
    stem = getattr(path, "stem", None)
    return str(stem if stem else (data.get("session_id") if isinstance(data, dict) else "") or "")


def stage_of(agent: dict, pipeline: dict) -> str:
    """Which stage a dispatch belongs to: its purpose line first (`qa-case-critic S4 TICKET`),
    then the `agent_id` pipeline.json recorded for the stage."""
    match = STAGE_IN_PURPOSE.search(str(agent.get("purpose") or ""))
    if match:
        return match.group(1)
    handle = str(agent.get("file") or "").removeprefix("agent-").removesuffix(".jsonl")
    for sid, entry in ((pipeline.get("stages") or {}) or {}).items():
        if isinstance(entry, dict) and handle and entry.get("agent_id") == handle:
            return str(sid)
    return "unattributed"


def driver_rows(troot: Path, by_session: dict | None = None, factors: dict | None = None,
                rounds: dict | None = None) -> list:
    """One row per role session from `driver-runs.jsonl`, in the shape `dispatches()` returns.

    `rounds` ({dispatch id: row of `dispatch_rounds`}, RN1-25 item 3): when the controller holds dispatch records, a row
    whose `dispatch` id one of them names takes its `round` and `rework` from that record (a repeated scope), not from
    its ordinal among the role's rows (AR-15: one definition of a repair round; the ordinal rule counted every resume
    of one dispatch as another round). A row no record names keeps the ordinal rule.

    In a driver run each role is its own top-level session, so the cost files carry no
    `agents[]` for it and the walk below finds nothing of the factory's — only whatever the
    operator's own session dispatched. The journal carries the role, the stage, the dispatch
    and the cost the CLI itself reported, which is what the retro's per-role and per-stage
    tables are about.

    A row's `total_cost_usd` is a RUNNING total of its session, so a row costs its INCREMENT
    (`driver_journal.row_increments`: its total minus the previous usable total of the same
    session), never its raw total: a role launched at $0.40 and resumed to $0.80 cost $0.80,
    not $1.20 (the same class of defect t-138 fixed for the orchestrator's share; on cmp1 the
    stage table summed to $32.0 against the driver's $17.42). The cost is None (unknown, row
    `incomplete`) when the increment is unusable, when the session's totals FALL (the figure
    is then one call's cost, not a total), and, with `by_session` (the project's journals read
    whole, `read_root`), when the reader's root rule has no record for the session (a per-call
    root, several journals): the same rule the share and the price use (one source per ratio).

    `factors` (`price_base`) puts a row's cost on the price's rate base when the project prices at its
    own rates (the session's factor times the increment), so the stage and role tables, the top
    dispatches and the rework cost are on the rates of the price printed above them."""
    journal = DJ.read_rows(Path(troot) / "state" / DJ.JOURNAL_NAME)
    by_id: dict = {}
    for row in journal:
        sid = row.get("session_id")
        if isinstance(sid, str) and sid and DJ.REPLACEMENT_CHAR not in sid:
            by_id.setdefault(sid, []).append(row)
    charged = DJ.root_charged(by_session)[0] if by_session else {}
    increment_of: dict = {}
    for sid, session_rows in by_id.items():
        unknown = DJ.total_falls(session_rows) or (sid in charged and charged[sid] is None)
        for session_row, increment in zip(session_rows, DJ.row_increments(session_rows)):
            increment_of[id(session_row)] = None if unknown else increment
    rows = []
    for row in journal:
        if row.get("kind") != "role" or not row.get("role"):
            continue
        cost = _on_price(increment_of.get(id(row)), str(row.get("session_id") or ""), factors)
        rows.append({
            "role": str(row.get("role")),
            "stage": str(row.get("stage") or "unattributed"),
            "purpose": str(row.get("dispatch") or ""),
            "session": str(row.get("session_id") or ""),
            "tokens": 0,
            "cost": cost,
            "requests": int(row.get("num_turns") or 0),
            "tools": {},
            "started": row.get("ts"),
            "resumed": bool(row.get("resumed")),
            # The journal prices what the CLI charged; it carries no token counts, and a zero
            # token figure here is "not measured", exactly as it is below. A row with no
            # usable increment is not measured either.
            "incomplete": cost is None,
        })
    rows.sort(key=lambda r: str(r.get("started") or ""))
    seen = defaultdict(int)
    for row in rows:
        key = (row["stage"], row["purpose"] or row["role"])
        seen[key] += 1
        row["round"] = seen[key]
        row["rework"] = seen[key] > 1
        record = (rounds or {}).get(row["purpose"])
        if record:
            row["round"], row["rework"] = record["round"], record["rework"]
    return rows


DISPATCH_ID = re.compile(r"^(S\d+)-(.+)-(\d+)$")


def _scope_keys(value) -> list:
    """The non-blank case/test keys of a dispatch scope. Anything that is not a list of keys is no scope (E-D3)."""
    items = value if isinstance(value, (list, tuple, set)) else [value] if isinstance(value, str) else []
    return [str(item).strip() for item in items if str(item or "").strip()]


def _scopes_overlap(left: list, right: list, artifacts) -> bool:
    """At least one key of `left` names the same case as a key of `right`: the identity match `contract.case_matches`,
    asked in both directions (a bare id matches any area, two different areas never match, `TC-1` is not `TC-10`); a
    key that is not a case id (a `TS-n`) is compared exactly, which is what `case_matches` does for it."""
    import contract as C                         # lazy: the contract module is not the retro's import graph
    return any(C.case_matches(a, b, artifacts=artifacts) or C.case_matches(b, a, artifacts=artifacts)
               for a in left for b in right)


def _is_continuation(record: dict, records: dict) -> bool:
    """True when `record` was resumed from a parent for a continuation reason (F2 t-1753): its own `retry_reason`, or the one
    `contract.retry_reason_for` reads from the parent's recorded status when the record predates the field."""
    parent = str(record.get("parent_retry") or record.get("relaunch_of") or "")
    if not parent:
        return False
    import contract as C                         # lazy, as `_scopes_overlap`
    reason = str(record.get("retry_reason") or "")
    if not C.retry_reason_valid(reason):
        old = records.get(parent)
        reason = C.retry_reason_for(old if isinstance(old, dict) else {}, str(record.get("retry_words") or ""))
    return C.is_continuation_reason(reason)


def dispatch_rounds(task_root: Path) -> list:
    """One row per controller dispatch record, in the order they were made (RN1-25 items 3 and 4).

    Carrier: `state/controller.json`, the projection the controller writes on every commit (the reader
    `run_block_metrics` already uses; the record's fields are written at `controller.py` `kind == "dispatch"`: `id`,
    `stage`, `role`, `scope`, `dispatched_seq`). A `stale` record and an imported one are skipped. A row is
    `{"id", "stage", "role", "scope", "round", "rework"}`: `round` is the ordinal among the records of the same
    (stage, role); `rework` is True when the scope shares a key with the scope of an EARLIER record of the same
    (stage, role) (F-4: a window the role has not seen before is NOT a repair round), False when it does not, and None
    for an EMPTY scope. A record resumed by the controller (`parent_retry` / `relaunch_of`) for a CONTINUATION reason
    (`contract.CONTINUATION_RETRY_REASONS`: checkpoint, compaction, turn_budget, subagent_silent, no_digest_at_exit,
    host_error) is `rework: False, continuation: True` (F2 t-1753): the parent stopped for the run's sake, its work was not
    wrong; its reason is the record's `retry_reason`, or the one `contract.retry_reason_for` reads from the parent. The other
    reasons (unaccepted_result, person_word, factory_defect ...) stay subject to the scope overlap (E-D3: an unknown is neither a repair nor a new window; the line names it). No records (or no
    controller file) is `[]`: the caller then keeps the ordinal rule, labelled (E-D2)."""
    state = read_json(Path(task_root) / "state" / "controller.json", {})
    records = state.get("dispatches") if isinstance(state, dict) else None
    if not isinstance(records, dict):
        return []
    kept = []
    for position, (name, record) in enumerate(records.items()):
        if not isinstance(record, dict) or record.get("status") == "stale" or record.get("imported"):
            continue
        did = str(record.get("id") or name)
        parsed = DISPATCH_ID.match(did)
        seq = record.get("dispatched_seq")
        order = (0, seq, position) if isinstance(seq, int) and not isinstance(seq, bool) else (1, 0, position)
        kept.append((order, {"id": did,
                             "stage": str(record.get("stage") or (parsed.group(1) if parsed else "") or "unattributed"),
                             "role": role_name(record.get("role") or (parsed.group(2) if parsed else "")) or "unattributed",
                             "scope": _scope_keys(record.get("scope")),
                             "continuation": _is_continuation(record, records)}))
    earlier: dict = {}
    rows = []
    for _order, row in sorted(kept, key=lambda item: item[0]):
        before = earlier.setdefault((row["stage"], row["role"]), [])
        row["round"] = len(before) + 1
        row["rework"] = (False if row["continuation"] else
                         any(_scopes_overlap(row["scope"], seen, task_root) for seen in before if seen)
                         if row["scope"] else None)
        before.append(row["scope"])
        rows.append(row)
    return rows


def _stage_window(entry) -> tuple:
    """`(start, end)` of a pipeline stage entry as datetimes, by the same pair `stage_times` measures (the stage's own
    stamps first, then the entry's), or None for either end that cannot be read."""
    if not isinstance(entry, dict):
        return None, None
    start, end = moment(entry.get("stage_started")), moment(entry.get("stage_finished"))
    if span_seconds(entry.get("stage_started"), entry.get("stage_finished")) is None:
        start, end = moment(entry.get("started")), moment(entry.get("finished"))
    return start, end


def stage_machine_times(stage_times_out: dict, waits, pipeline: dict | None = None) -> dict:
    """{stage: seconds}: a stage's wall time minus the human waits that overlap its window (RN1-25 item 2).

    `stage_times_out` is `stage_times(pipeline)`; `waits` is the list of `human_waits` entries
    (`{"start", "end", ...}`, ISO stamps) of the story's cost files, or None when they are not measured. `pipeline`
    gives the stage windows (`stage_times` keeps only the seconds). The waits are united first, so two sessions waiting
    at the same time are subtracted once, and each is clipped to the window; the result is never below 0 (E-D5: a wait
    outside every stage lowers no stage; it stays in the story's total). A stage whose wall time is None (a clock
    anomaly, no stamps) has machine time None (E-D4, FR-41), and so has every stage while `waits` is None (E-D1: a
    cost file of a capture that did not measure question waits would give a machine time that is too long)."""
    stages = (pipeline or {}).get("stages") if isinstance(pipeline, dict) else None
    united = CC.merge_spans((moment(w.get("start")), moment(w.get("end"))) for w in (waits or []) if isinstance(w, dict))
    out = {}
    for stage, row in (stage_times_out or {}).items():
        wall = row.get("seconds") if isinstance(row, dict) else None
        if waits is None or not isinstance(wall, (int, float)):
            out[stage] = None
            continue
        start, end = _stage_window((stages or {}).get(stage))
        inside = 0.0
        if start is not None and end is not None:
            inside = sum(max(0.0, (min(b, end) - max(a, start)).total_seconds()) for a, b in united)
        out[stage] = max(0, int(wall - inside))
    return out


def dispatches(task: str, files: list, pipeline: dict) -> list:
    """One row per role dispatch, in the order they ran, with the stage and whether it was
    a repair round by the ORDINAL rule (the second and later agent file of the same role in the same stage).

    This is the FALLBACK of a story with no controller dispatch records (E-D2); `numbers` labels it. With records
    `dispatch_rounds` is the definition: a repair round is a repeated scope, and a dispatch is a record, not an agent
    file (a resumed agent is one file for several handoffs).

    `files` are the RE-PRICED cost files (`numbers` hands `revalue_document`'s output): a row's
    `cost` is the agent's re-priced `cost`, never the money pinned at capture (t-171)."""
    rows = []
    for path, data in files:
        incomplete_names = {role_name(n) for n in (data.get("incomplete_agents") or [])}
        for agent in data.get("agents") or []:
            if not isinstance(agent, dict):
                continue
            if agent.get("task") not in (task, "(no task)", None, ""):
                continue
            role = role_name(agent.get("agent"))
            tokens = agent.get("tokens")
            cost = agent.get("cost")
            rows.append({
                "role": role,
                "stage": stage_of(agent, pipeline),
                "purpose": str(agent.get("purpose") or ""),
                "session": str(data.get("session_id") or path.stem),
                "tokens": int(tokens or 0),
                "cost": cost,
                "requests": sum(int(m.get("requests") or 0)
                                for m in (agent.get("by_model") or {}).values()
                                if isinstance(m, dict)),
                "tools": dict(agent.get("tools") or {}),
                "started": agent.get("started"),
                # A zero is not a free dispatch, it is an unmeasured one. The distinction
                # is the whole difference between "the orchestrator spent 100%" and "we
                # cannot say yet".
                "incomplete": (not tokens) or role in incomplete_names,
            })
    rows.sort(key=lambda r: str(r.get("started") or ""))
    seen = defaultdict(int)
    for row in rows:
        key = (row["stage"], row["role"])
        seen[key] += 1
        row["round"] = seen[key]
        row["rework"] = seen[key] > 1
    return rows


def orchestrator_totals(task: str, files: list) -> dict:
    """The orchestrator's OWN tokens/cost on this task — never `by_task[task]`, which is the
    FOLDED total (orchestrator + every agent dispatched under it, per cost_capture.py's
    `task_models`). Using the folded figure here used to make `orchestrator_share_percent`
    meaningless the moment `story_spend`'s double-count was fixed: both numerator and
    denominator read the same folded number, so the share always came out ~100% — exactly the
    false reading this file's own docstring says must never be published. `requests[]` is the
    only place a call's `stream` and `task` are recorded together, so it is the only source
    for a true per-task, orchestrator-only split; a session without it (collapsed/legacy
    shape) contributes nothing here rather than a guess."""
    total = {"tokens": 0, "requests": 0, "cost": 0.0, "cost_known": False,
             "active_s": 0, "machine_s": 0, "tools": {}}
    for _path, data in files:
        entry = (data.get("by_task") or {}).get(task)
        if isinstance(entry, dict):
            total["active_s"] += int(entry.get("active_s") or 0)
            total["machine_s"] += int(entry.get("machine_s") or 0)
        for tool, n in (data.get("orchestrator") or {}).get("tools", {}).items():
            total["tools"][tool] = total["tools"].get(tool, 0) + int(n or 0)
        rows = data.get("requests")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or row.get("stream") != "orchestrator" or row.get("task") != task:
                continue
            usage = row.get("usage") or {}
            total["tokens"] += sum(usage.get(k, 0) or 0 for k in
                ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h"))
            total["requests"] += 1
            valuation = row.get("valuation") or {}
            if valuation.get("pricing_coverage") in ("partial", "complete"):
                total["cost"] += float(valuation.get("subtotal_usd") or 0)
                total["cost_known"] = True
    if not total["cost_known"]:
        total["cost"] = None
    return total


def share_limit_from_cfg(cfg) -> float:
    """`retro.orchestrator_share_max` as a percentage, from an already-loaded config.

    Read with a default so a project onboarded on 0.7.x keeps working untouched, and clamped
    to a real fraction so a config that says `35` where it means `0.35` cannot silently turn
    the threshold off. One reader, so the retro and the Factory tab cannot disagree."""
    try:
        value = float(((cfg or {}).get("retro") or {}).get("orchestrator_share_max"))
    except (TypeError, ValueError):
        value = ORCHESTRATOR_SHARE_MAX
    if not 0 < value <= 1:
        value = ORCHESTRATOR_SHARE_MAX
    return round(100.0 * value, 1)


def share_limit_percent(base: Path) -> float:
    """The same limit, for a caller that has only the project's state directory."""
    try:
        cfg = json.loads((Path(base) / "config.json").read_text(encoding="utf-8-sig"))   # a BOM is the encoding, not a parse error
    except Exception:
        cfg = {}
    return share_limit_from_cfg(cfg)


def journal_sessions(troot: Path) -> dict | None:
    """{session_id: rows} of a story's driver journal, rows in file order; None when the story
    has no journal file at all. A row whose `session_id` is not a non-empty string names no
    session and is not one (the delivery row carries no cost). An EMPTY journal is not None: it
    is a journal that names nothing, and the share it gives is unknown, not the branch of a run
    that never had one. An id holding U+FFFD is not a session either: the file is read with a
    replacing decoder, so two different undecodable ids would merge into one, and the reader
    (`driver_journal.parse_driver_runs`) never binds it."""
    path = Path(troot) / "state" / DJ.JOURNAL_NAME
    if not path.is_file():
        return None
    out: dict = {}
    for row in DJ.read_rows(path):
        sid = row.get("session_id")
        if isinstance(sid, str) and sid and DJ.REPLACEMENT_CHAR not in sid:
            out.setdefault(sid, []).append(row)
    return out


def codex_tariff_label(rows) -> str:
    """The line a story's Codex calls print beside their price, for the retro and the dashboard card (CX1-15 F-3, the
    owner's word 20.10: "with a note that the tariffs are the defaults and may be stale"): their `cost_basis`, each
    distinct text once, in the order the journal gave them. The driver prices a Codex call itself (the CLI reports no
    charge), so the figure is an estimate and the page says so; `rows` are any driver-journal rows, and only those of
    `host: codex` that carry a `cost_basis` count. "" when there is none: a Claude story prints nothing new."""
    seen = []
    for row in rows or []:
        if isinstance(row, dict) and row.get("host") == "codex":
            basis = " ".join(str(row.get("cost_basis") or "").split())
            if basis and basis not in seen:
                seen.append(basis)
    return f"Codex calls are priced by the factory, not charged by the CLI: {' | '.join(seen)}." if seen else ""


def all_cost_files(root: Path | None = None) -> list:
    """Every readable session cost file, whatever tickets it names. `cost_files` keeps the ones
    that mention a ticket; a driver session whose file names none (a collapsed `(no task)` row:
    13 of the 35 sessions of cmp1) still has a price there, which is all the journal share needs
    from it when the journal's own figure for the session cannot be trusted."""
    base = Path(root) if root is not None else state_dir()
    try:
        files = sorted_paths((base / "state" / "cost").glob("*.json"))
    except Exception:
        return []
    out = []
    for path in files:
        data = read_json(path)
        if isinstance(data, dict):
            out.append((path, data))
    return out


def _positive(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _has_usage(data: dict) -> bool:
    """True when the cost file records any usage at all: tokens under a task or an agent, or a
    request row. A file with none is a session nobody measured, whatever its total says."""
    by_task = data.get("by_task")
    if isinstance(by_task, dict) and any(isinstance(entry, dict) and _positive(entry.get("tokens"))
                                         for entry in by_task.values()):
        return True
    agents = data.get("agents")
    if isinstance(agents, list) and any(isinstance(a, dict) and _positive(a.get("tokens"))
                                        for a in agents):
        return True
    requests = data.get("requests")
    return isinstance(requests, list) and bool(requests)


def cost_file_amount(data: dict):
    """What one session's cost file says the whole session cost (`total_cost_usd`), or None when
    that figure is not a price. The whole session and not `by_task[<ticket>]`: a session the
    driver launched belongs to its story whole, and cmp1's cost files carry no ticket entry at
    all.

    None when the file has no usable number, when it declares `incomplete_agents`, when an agent
    in it has zero usage, and when it has no usage at all: cost capture writes a $0 (or a part
    of a price) for a session it could not measure, and a $0 or partial file is never a price
    (TP1-15045: six roles at `tokens: 0`; the first driver retro's critic found a share of
    100.0 where a role's $0 file, zero usage, stood in for its price).

    This is its own figure, and it reads the `total_cost_usd` of the document it is given: a
    caller hands the RE-PRICED document (`revalue_document`), because the money pinned at capture
    is another table's (measured 30.09: about 1.5 times the CLI's charge, B-225). It is never
    added to the driver's money and never stands in for a session the driver's record cannot
    price."""
    if not isinstance(data, dict):
        return None
    amount = DJ.usable_total(data.get("total_cost_usd"))
    if amount is None or data.get("incomplete_agents"):
        return None
    agents = data.get("agents")
    if isinstance(agents, list) and any(isinstance(a, dict) and not a.get("tokens") for a in agents):
        return None
    return amount if _has_usage(data) else None


def project_root_of(base: Path):
    """The project folder the driver's journals are read from, or None. `base` is the factory's
    state folder (`hooklib.state_dir`: `<project>/qa-factory`) that `numbers()` is given as
    `root`, so the project is its parent - the same folder `friction` is handed. A folder not
    named `qa-factory` is not a state folder this can place: the share is then unknown, with
    that reason, and nothing is guessed."""
    base = Path(base)
    return base.parent if base.name == "qa-factory" else None


def read_root(base: Path) -> tuple:
    """(by_session, problem): every journal of the project through the ONE reader, whole. Pricing
    a session is a property of its ROOT (`driver_journal.root_charged`: a falling session of
    another story proves that every journal here records each call's cost), so it never reads
    one story's journal alone. `problem` is "" or the reason nothing could be read."""
    project = project_root_of(base)
    if project is None:
        return {}, ("the project folder cannot be told from the factory's state folder "
                    f"({Path(base).name}), so the driver's journals of the project were not read")
    try:
        by_session, _spread = DJ.parse_driver_runs(project)
    except Exception as exc:  # a retro that cannot read its records says unknown, it does not stop (FR-41)
        return {}, f"the project's driver journals could not be read ({type(exc).__name__}: {exc})"
    return by_session, ""


def _bind(task: str, journal) -> dict:
    """The journal in the shape `parse_driver_runs` returns: `{sid: {"task", "rows", ...}}`. A
    plain `{sid: rows}` (`journal_sessions`) is one journal's part of the story: a single-journal
    entry of this task. An entry with no rows is not a session and is left out."""
    out: dict = {}
    for sid, entry in (journal or {}).items():
        if isinstance(entry, list):
            entry = {"task": task, "rows": entry, "journals": [task]}
        if isinstance(entry, dict) and isinstance(entry.get("rows"), list) and entry["rows"]:
            out[sid] = entry
    return out


def _is_here(entry: dict, task: str) -> bool:
    """A session belongs to this story when the reader bound it to it (`entry["task"]`; an entry
    with no task is one this caller built for the story)."""
    return entry.get("task") in (None, task)


# The reasons a session has no usable driver record, in plain words for a person (FR-6). The four
# of the reader (`driver_journal.WHY_*`) and one of this module's: a session the story's journal
# names that the project's journals do not list (the project folder was not found or moved).
WHY_NOT_READ = "not listed by the project's journals"
# The price function's own words for the four of the reader (one table, `task_price.WHY_WORDS`), plus this
# module's fifth.
WHY_WORDS = {
    **TP.WHY_WORDS,
    WHY_NOT_READ: "the project's journals do not list it, so its record was not found",
}


def price_base(price: dict) -> dict:
    """How the driver's money is put on the price's rate base, from the price answer's own rows
    (`task_price.session_factors`: the one place the scaling lives).

    The CLI's charge (B) is at the catalogue's list rates; when the project prices at its own rates the
    story's price is on those, and a figure derived from B that sat beside it (the share's "$3.07 of
    $17.42", the money handed back, a dispatch's cost) would be on another base than the price
    ("$3.07 of $17.42" beside "$26.14"). `factors` is {session: factor}: B times it is B on the price
    base; `unscaled` the sessions with a price and a charge and no list price to scale by (their charge
    stands at the CLI's own list-price figure, and the lines say so); `project_rates` whether the price
    is at the project's own rates at all. Without project rates, `factors` and `unscaled` are empty and
    every figure is what it was."""
    project = TP.project_rates_applied(price)
    factors, unscaled = TP.session_factors(price) if project else ({}, [])
    return {"factors": {sid: float(f) for sid, f in factors.items()}, "unscaled": unscaled if project else [],
            "project_rates": project}


def _on_price(usd, sid, factors):
    """`usd` of session `sid` on the price base (`factors` from `price_base`); None stays None."""
    if usd is None or not factors or sid not in factors:
        return usd
    return usd * factors[sid]


def session_prices(task: str, journal, factors: dict | None = None) -> list:
    """One record per session of this story, in journal order: {session, label, stage, usd, why}.

    `journal` is `parse_driver_runs`'s first result for the WHOLE project (or `{sid: rows}` of one
    journal, see `_bind`). A session the reader bound to another story is not this story's and is
    not here. `usd` is the DRIVER's record of the session and nothing else: the reader's root
    rule (`root_charged`, computed over the whole root handed in, so a falling session of another
    story counts for the per-call rule), a float, or None with `why` one of the reader's `WHY_*`.
    No cost file stands in for it: they are priced by another table (B-225). `label` is
    `driver_journal.agent_label`, the ONE name every page groups money by: only a session of
    kind conductor is "conductor", and the S0 ticket call (and any other data-fetching call) is
    the scout's (`qa-scout`), not a label of its own (owner, 30.09).

    `factors` (`price_base`) puts the driver's record on the price's rate base when the project
    prices at its own rates: `usd` is then the session's charge times its factor, so a share or a stage
    part is on the same rates as the price beside it. None: the record as the CLI charged it."""
    bound = _bind(task, journal)
    charged, unknown = DJ.root_charged(bound)
    why = dict(unknown)
    out = []
    for sid, entry in bound.items():
        if not _is_here(entry, task):
            continue
        rows = entry["rows"]
        stage = str(rows[0].get("stage") or "").strip() or "unattributed"
        out.append({"session": sid, "label": DJ.agent_label(rows), "stage": stage,
                    "usd": _on_price(charged.get(sid), sid, factors), "why": why.get(sid)})
    return out


def handed_back(task: str, journal, factors: dict | None = None) -> dict:
    """The money of role sessions that were RESUMED after a question or a return, as its own
    line of role spend. Choosing a role and handing it something to redo is the conductor's
    management; the extra work the role then does is the ROLE's cost (owner, 30.09, P18).

    Priced by per-row increments (`driver_journal.row_increments`) of the rows that carry
    `kind: role` and `resumed: true`, never by adding totals: a resumed session's total already
    holds its earlier rows (rows 1.0 then 1.5: $0.50 was handed back, not $2.50). A session
    whose driver record is unknown (`root_charged`), or one of whose resumed rows has no usable
    increment, cannot be attributed: it is counted unknown and is in no sum.
    {"usd", "sessions", "unknown"}: `sessions` are the attributed ones; `usd` is None when
    resumed sessions exist and none of them could be attributed, 0.0 when none was resumed.
    `factors` (`price_base`) puts each session's increments on the price's rate base (see
    `session_prices`)."""
    bound = _bind(task, journal)
    charged, _unknown = DJ.root_charged(bound)
    parts, unknown = [], 0
    for sid, entry in bound.items():
        if not _is_here(entry, task):
            continue
        rows = entry["rows"]
        resumed = [i for i, row in enumerate(rows) if row.get("kind") == "role" and row.get("resumed") is True]
        if not resumed:
            continue
        increments = DJ.row_increments(rows)
        if charged.get(sid) is None or any(increments[i] is None for i in resumed):
            unknown += 1
            continue
        parts.append(_on_price(math.fsum(increments[i] for i in resumed), sid, factors))
    return {"usd": round(math.fsum(parts), 6) if parts else (None if unknown else 0.0),
            "sessions": len(parts), "unknown": unknown}


def _reasons_in_words(unknown: list) -> str:
    """"2 because <words>; 1 because <words>" for the `(session, why)` pairs, one group per reason."""
    counts: dict = {}
    for _sid, why in unknown:
        counts[why] = counts.get(why, 0) + 1
    order = [DJ.WHY_NO_TOTAL, DJ.WHY_FALLS, DJ.WHY_SEVERAL_JOURNALS, DJ.WHY_PER_CALL_ROOT, WHY_NOT_READ]
    return "; ".join(f"{counts[why]} because {WHY_WORDS[why]}" for why in order if why in counts)


def journal_share(task: str, named, by_session, files=(), problem: str = "", rates: dict | None = None) -> dict:
    """The orchestrator's share of a driver run, from the driver's own record and from nothing
    else: the conductor's sessions over every session of the story, each priced by the reader's
    root rule (`session_prices`).

    ONE SOURCE PER RATIO. The share is published only when EVERY session of the story has a
    driver record: numerator and denominator are then both the driver's money. If any session is
    unknown the share is None, `reason` says how many and why, and the known amounts stay in
    `conductor_usd` / `role_usd` / `known_usd` as amounts. The project's cost files are priced by
    another table than the CLI's charge (B-225): a session they could price is still unknown here,
    because mixing the two currencies skews the share the way that keeps a limit finding silent.

    `named` is the sessions the story's own journal file names (`journal_sessions`), `by_session`
    the whole project's journals through the reader (`read_root`), `problem` why that could not be
    read. A session the story's file names that the reader bound to ANOTHER story is left out of
    both sums and listed in `left_out` (it is one process, counted once, where its earliest
    timestamp is); one the project's journals do not list at all is unknown (`WHY_NOT_READ`).
    A session of kind ticket is in the denominator and not in the numerator: the owner's word
    (30.09) is that the S0 ticket call, like every data-fetching call, is the SCOUT's spend
    (`driver_journal.agent_label`), so it counts with the roles and never with the conductor.
    `cost_files` is the cost files' own figure for the same sessions (`cost_file_amount`), read
    from `files` handed in RE-PRICED (`numbers` passes `revalue_document`'s output, never the
    money pinned at capture: t-171), never added to the driver's money and not the story's price
    (that is `task_price`). When the base is zero the share is None as well: an unknown is never a zero
    and never a hundred (FR-41).

    `rates` (`price_base`): when the project prices at its own rates, every driver amount here is put
    on the price's rate base, session by session (the price beside the share is at those rates: "$3.07
    of $17.42" under "$26.14" is two bases on one page). `basis["on_project_rates"]` says it was done
    and `basis["unscaled"]` lists the story's sessions left at the CLI's own list-price figure (no list
    price of the transcripts to scale by): the lines say both."""
    bound = _bind(task, by_session)
    rates = rates if isinstance(rates, dict) else {}
    records = session_prices(task, bound, rates.get("factors"))
    named_ids = list(named or [])
    left_out = [{"session": sid, "journals": len(bound[sid].get("journals") or []),
                 "counted_under": bound[sid].get("task")}
                for sid in named_ids if sid in bound and not _is_here(bound[sid], task)]
    missing = sorted(sid for sid in named_ids if sid not in bound)
    unknown = sorted([(r["session"], r["why"]) for r in records if r["usd"] is None]
                     + [(sid, WHY_NOT_READ) for sid in missing])
    known = [r for r in records if r["usd"] is not None]
    conductor = [r for r in records if r["label"] == DJ.CONDUCTOR_LABEL]
    conductor_known = [r for r in conductor if r["usd"] is not None]
    roles_known = [r for r in known if r["label"] not in (DJ.CONDUCTOR_LABEL, DJ.UNLABELLED)]
    sessions = len(records) + len(missing)
    orch = math.fsum(r["usd"] for r in conductor_known)
    total = math.fsum(r["usd"] for r in known)
    amounts: dict = {}
    on_disk: set = set()
    for path, data in files:
        sid = str(data.get("session_id") or getattr(path, "stem", "") or "")
        if sid:
            on_disk.add(sid)
        amount = cost_file_amount(data)
        if sid and amount is not None:
            amounts.setdefault(sid, amount)
    story_ids = [r["session"] for r in records] + missing
    on_files = [amounts[sid] for sid in story_ids if sid in amounts]
    # `sessions` counts the cost files BOUND to the story, priced or not, and `unpriced` the bound
    # ones that give no figure (a file with no request ledger, a declared-incomplete one): "2
    # sessions bound, no figure", never "0 sessions" for files that are there (t-171, FR-41).
    bound_files = [sid for sid in story_ids if sid in on_disk]
    complete = sessions > 0 and not unknown
    basis = {"sessions": sessions,
             "conductor_sessions": len(conductor),
             "conductor_known": len(conductor_known),
             "role_known": len(roles_known),
             "priced_by_driver": len(known),
             "unpriced": len(unknown),
             "unknown": [{"session": sid, "why": why} for sid, why in unknown],
             "left_out": left_out,
             "on_project_rates": bool(rates.get("project_rates")),
             "unscaled": [sid for sid in (rates.get("unscaled") or []) if sid in set(story_ids)],
             "known_usd": round(total, 6) if known else None,
             "conductor_usd": round(orch, 6) if known else None,
             "role_usd": round(math.fsum(r["usd"] for r in roles_known), 6) if known else None,
             "total_usd": round(total, 6) if complete else None,
             "cost_files": {"usd": round(math.fsum(on_files), 6) if on_files else None,
                            "sessions": len(bound_files), "unpriced": len(bound_files) - len(on_files),
                            "of": len(story_ids)},
             "share_percent": None, "reason": ""}
    if not sessions:
        basis["reason"] = ("every session this journal names is counted under another task, so "
                           "there is nothing to price here." if left_out else
                           "the driver's journal names no session, so there is nothing to price.")
    elif unknown:
        who = (f"none of the {_plural(sessions, 'session', 'sessions')} has a usable driver record"
               if len(unknown) == sessions
               else f"{len(unknown)} of the {_plural(sessions, 'session', 'sessions')} "
                    f"{'has' if len(unknown) == 1 else 'have'} no usable driver record")
        basis["reason"] = (f"{who}: {_reasons_in_words(unknown)}. A share needs "
                           "one record for every session, and the project's cost files are priced "
                           "by another table, so they are not mixed in."
                           + (f" ({problem}.)" if problem and missing else ""))
    elif total <= 0:
        basis["reason"] = (f"the {_plural(len(known), 'session', 'sessions')} "
                           f"{'adds' if len(known) == 1 else 'add'} up to nothing, so there is no base to "
                           "divide by.")
    else:
        basis["share_percent"] = round(100.0 * orch / total, 1)
    return basis


def orchestrator_by_stage(task: str, files: list, pipeline: dict, journal: dict | None = None,
                          factors: dict | None = None) -> dict:
    """The orchestrator's OWN priced cost per stage.

    WITHOUT a journal: from the receipts `orchestrator_totals` already reads: a request belongs
    to the stage whose recorded window contains its timestamp.

    The orchestrator's requests carry no stage of their own — it holds one context across
    S1-S8, which is the whole reason its share is worth bounding — so the story's own stage
    clock is the only receipt that can place them. A stage whose clock is missing or runs
    backwards places nothing: its requests stay `unattributed` rather than being folded into
    a neighbour and read as that neighbour's fault.

    WITH a journal (`parse_driver_runs`'s first result for the whole project, or the
    `journal_sessions` of one story): the conductor sessions' DRIVER record by `session_prices`
    (the reader's root rule), keyed by the `stage` of each conductor session's FIRST row, an
    empty or absent stage "unattributed". A conductor session with no driver record is in no
    stage. No clock is read: a driver run has no orchestrator stream to place, and `files` are
    not read: no cost file prices a session here. The parts add up to `journal_share`'s
    `conductor_usd` (on the same rate base: `factors`, from `price_base`, put each session's record
    on the price's rates when the project prices at its own, exactly as the share does).
    """
    if journal is not None:
        out: dict = {}
        for p in session_prices(task, journal, factors):
            if p["label"] == DJ.CONDUCTOR_LABEL and p["usd"] is not None:
                out[p["stage"]] = round(out.get(p["stage"], 0.0) + p["usd"], 6)
        return out
    windows = []
    for sid, entry in sorted((pipeline.get("stages") or {}).items()):
        if not isinstance(entry, dict) or clock_anomaly(entry):
            continue
        start = moment(entry.get("stage_started")) or moment(entry.get("started"))
        end = moment(entry.get("stage_finished")) or moment(entry.get("finished"))
        if start is not None and end is not None and end >= start:
            windows.append((start, end, str(sid)))
    out: dict = {}
    for _path, data in files:
        rows = data.get("requests")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or row.get("stream") != "orchestrator" \
                    or row.get("task") != task:
                continue
            valuation = row.get("valuation") or {}
            if valuation.get("pricing_coverage") not in ("partial", "complete"):
                continue
            when = moment(row.get("timestamp"))
            stage = next((sid for start, end, sid in windows
                          if when is not None and start <= when <= end), "unattributed")
            out[stage] = round(out.get(stage, 0.0) + float(valuation.get("subtotal_usd") or 0), 6)
    return out


def cache_read_rate(model: str = "", cost_cfg: dict | None = None):
    """USD per million cache-read tokens of `model`: the project's own rate for it (`rate_overrides`,
    a person's price replaces the catalogue's: P18), else the rate catalogue's; None when it is
    neither (an UNKNOWN, FR-41: the caller says so and prints no number).

    The model is matched by its EXACT id or an alias of an entry (compared without regard to case),
    never by a substring of either side. The substring match priced `claude-opus-5-5` at $0.5
    (measured by the critic of t-137): the catalogue's `claude-opus-5` is a substring of it and
    comes first, while the entry for `claude-opus-5-5` says $0.2. The same class as the project's
    family rate over the catalogue's exact one (B-225): a rate read for a model the catalogue does
    not name is a guess wearing a number. A model no entry names, and a call with no model, have NO
    rate: it used to be the first Sonnet entry's ($0.3 for a story run on claude-sonnet-5-5, whose
    rate is $0.2: the rules line read $2.20 where the figure is about $1.47, the critic of t-182),
    and another model's rate is never the answer for this one."""
    return cache_read_entry(model, cost_cfg)[0]


def cache_read_entry(model: str = "", cost_cfg: dict | None = None) -> tuple:
    """(rate, source) of `cache_read_rate`: `source` is "project" when the project's own table named the
    model, "catalogue" when the catalogue did, None (with rate None) when neither has a rate for it."""
    wanted = str(model or "").strip().lower()
    if not wanted:
        return None, None
    overrides = (cost_cfg or {}).get("rate_overrides") if isinstance(cost_cfg, dict) else None
    catalogue = [e for e in (CC.load_catalogue().get("entries") or []) if isinstance(e, dict)]
    for source, entries in (("project", [e for e in (overrides or []) if isinstance(e, dict)]), ("catalogue", catalogue)):
        for entry in entries:
            names = [entry.get("model_id"), *(entry.get("aliases") or [])]
            if wanted in [n.strip().lower() for n in names if isinstance(n, str)]:
                rate = (entry.get("rates") or {}).get("cache_read")
                if isinstance(rate, (int, float)) and not isinstance(rate, bool) and rate > 0:
                    return float(rate), source
                return None, None
    return None, None


def story_model(files) -> tuple:
    """(model id, how many models) of the cost files of the story's sessions: the model with the
    most cache-read tokens (what the rules' cost is about: a prompt re-read from cache), a tie to the
    first id in alphabetical order; ("", 0) when no file names a model. A file's own `by_model` is
    read, else its request rows' `model_id` and `usage`."""
    tally: dict = {}
    for _path, data in files:
        if not isinstance(data, dict):
            continue
        by_model = data.get("by_model")
        if isinstance(by_model, dict) and by_model:
            for name, value in by_model.items():
                if isinstance(name, str) and name:
                    tally[name] = tally.get(name, 0) + (int(value.get("cache_read") or 0) if isinstance(value, dict) else 0)
            continue
        for row in data.get("requests") if isinstance(data.get("requests"), list) else []:
            if isinstance(row, dict) and isinstance(row.get("model_id"), str) and row["model_id"]:
                usage = row.get("usage") if isinstance(row.get("usage"), dict) else {}
                tally[row["model_id"]] = tally.get(row["model_id"], 0) + int(usage.get("cache_read") or 0)
    if not tally:
        return "", 0
    return max(sorted(tally), key=lambda name: tally[name]), len(tally)


def rules_model(files, pipeline) -> tuple:
    """(model id, how many models) the rules' cost is priced at: the story's own cost files first
    (`story_model`: measured), else the model the pipeline names; ("", 0) with neither."""
    model, count = story_model(files)
    if model:
        return model, count
    named = pipeline.get("models") if isinstance(pipeline, dict) else None
    named = (named[0] if isinstance(named, list) and named else
             (pipeline.get("model") if isinstance(pipeline, dict) else "")) or ""
    return (str(named), 1) if str(named).strip() else ("", 0)


def rules_weight(rows: list, model: str = "", cost_cfg: dict | None = None, models: int = 0) -> dict:
    """What the ROLES' rules cost this story, in the currency everything else is measured in.

    A byte cap is a proxy, and a proxy cannot be compared with anything: "the charter grew 300
    bytes" and "the slice grew 3 KB" are the same sentence until they are both dollars (P7.5). A
    dispatch's prompt is read on its first turn and re-read from cache on every turn after it, so
    what a rule really costs is its bytes times the number of requests the role made, at the
    model's cache-read rate. The arithmetic is approximate in one place only - the bytes to a
    token (`bytes_per_token` of references/role-load.json, 4) - and it is named here rather than hidden, because the number it produces is meant for
    comparing layers with each other, not for billing.

    `model` is the model of the story (`story_model` of its cost files, else the pipeline's): the
    rate is ITS cache-read rate (`cache_read_rate`, the project's own rate for it when it has one).
    With no model, or a model with no rate, the rate is unknown: the tokens and the requests are
    still given, `usd` and `by_layer` are None and `rate_per_mtok` None, and `reason` says why
    (FR-41): no other model's rate stands in for it. `models` is how many models the story's files
    name (the dominant one is used and the line says so).
    """
    # The sum is `role_load`'s (RC1-14, AR-13): the four layers this report prices keep their names - charter, slices
    # (`injection_role`), common (`injection_common`), brief - and `bytes` stays the sum of THOSE four, not the load's
    # `total_bytes`. A role whose layer is null or PARTLY unreadable (`measured: false` on a file layer) is unmeasured and
    # named in `unmeasured_roles` (the renderer prints it beside the total), never priced at 0 or as a whole (FR-41). The brief is
    # a ceiling by design (`measured: false`, bytes present), so only its bytes are asked.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import role_load
        weights, unmeasured, bpt = {}, [], role_load.settings()["bytes_per_token"]
        for role in sorted({str(r.get("role") or "") for r in rows}):
            if role not in role_load.role_names():
                continue
            layers = {layer["name"]: layer for layer in role_load.static_load(role)["layers"]}
            names = ("charter", "injection_role", "injection_common", "brief")
            if any(layers[n]["bytes"] is None or (n != "brief" and not layers[n]["measured"]) for n in names):
                unmeasured.append(role)
                continue
            charter, slices, common, brief = [layers[n]["bytes"] for n in names]
            weights[role] = (role, charter, slices, common, brief, charter + slices + common + brief)
    except Exception as exc:
        # The rules' cost is UNKNOWN here, and the retro says so with the reason - a line that vanishes reads as "no rules cost".
        return {"unknown": f"role-load.json or the role files could not be read ({type(exc).__name__}: {exc})"}
    if not weights:
        if unmeasured:      # every role of the story is unmeasured: nothing to price, and that is said, not dropped
            return {"unknown": "the rules files of every role of the story could not be read", "unmeasured_roles": unmeasured}
        return {}
    rate, rate_source = cache_read_entry(model, cost_cfg)
    per_role, requests_total, bytes_total, usd_total = {}, 0, 0, 0.0
    layers = {"charter": 0.0, "slices": 0.0, "common": 0.0, "brief": 0.0}
    for row in rows:
        role = str(row.get("role") or "")
        entry = weights.get(role)
        requests = int(row.get("requests") or 0)
        if not entry or requests <= 0:
            continue
        _role, charter, slices, common, brief, total = entry
        per = per_role.setdefault(role, {"requests": 0, "bytes": total, "usd": 0.0 if rate is not None else None})
        per["requests"] += requests
        requests_total += requests
        bytes_total += total * requests
        if rate is None:
            continue
        usd = (total / bpt) * requests * rate / 1_000_000
        per["usd"] = round(per["usd"] + usd, 4)
        usd_total += usd
        for name, value in (("charter", charter), ("slices", slices), ("common", common),
                            ("brief", brief)):
            layers[name] += (value / bpt) * requests * rate / 1_000_000
    if not per_role:
        return {}
    reason = ""
    if rate is None:
        reason = (f"the model {model!r} has no cache-read rate in the project's own rates or the catalogue"
                  if str(model or "").strip() else
                  "no model is named in the story's cost files, so there is no cache-read rate to price it at")
    out = {"requests": requests_total, "tokens": int(bytes_total / bpt),
           "usd": round(usd_total, 4) if rate is not None else None, "rate_per_mtok": rate,
           "model": str(model or ""), "models": int(models or 0), "reason": reason, "rate_source": rate_source,
           "by_layer": {k: round(v, 4) for k, v in layers.items()} if rate is not None else None,
           "by_role": per_role,
           "assumption": f"{bpt} bytes per token, the model's cache-read rate, every request of "
                         "every dispatch re-reading the whole prompt"}
    if unmeasured:
        out["unmeasured_roles"] = unmeasured          # a role whose rules file could not be read is named, not priced at 0
    return out


def orchestrator_finding(data: dict) -> str:
    """The one line the retro and the Factory tab print when management outgrew the work.

    Empty when the share is under the limit, or when there is nothing to compare: a story
    whose spend is a floor, or one carrying no orchestrator receipts at all, reads as missing
    and never as zero.
    """
    share = data.get("orchestrator_share_percent")
    limit = data.get("orchestrator_share_limit_percent")
    if not isinstance(share, (int, float)) or not isinstance(limit, (int, float)) or share <= limit:
        return ""
    # The stage parts are divided by the base the SHARE was computed on, so they add up to the
    # headline. On a driver run that base is the driver's record; the cost files' spend covers
    # a different set of sessions (cmp1: 22 files, 5 of its 17 conductor sessions) and would
    # print parts that do not sum to the share (FR-25). A caller that carries no basis (the
    # dashboard's banner) keeps the story's spend.
    basis = data.get("orchestrator_share_basis")
    usd = basis.get("total_usd") if isinstance(basis, dict) else (data.get("story") or {}).get("usd")
    parts = [f"{stage} {100.0 * cost / usd:.0f} %" for stage, cost in
             sorted((data.get("orchestrator_by_stage") or {}).items(), key=lambda kv: (-kv[1], kv[0]))
             if isinstance(usd, (int, float)) and usd > 0]
    return (f"the orchestrator spent {share:.0f} % of the story (limit {limit:.0f} %)"
            + (" - " + ", ".join(parts) if parts else "")
            + ". Dispatching, re-assembling requests, repeated acceptances and holding context "
              "across the stages are the factory's own work: this is a finding about the "
              "factory (FB), never a cost line the person is asked to repair.")


def by_key(rows: list, key: str) -> dict:
    out = {}
    for row in rows:
        bucket = out.setdefault(str(row.get(key) or "unattributed"),
                                {"dispatches": 0, "tokens": 0, "cost": 0.0,
                                 "cost_known": False, "requests": 0, "incomplete": False})
        bucket["dispatches"] += 1
        bucket["tokens"] += int(row.get("tokens") or 0)
        bucket["requests"] += int(row.get("requests") or 0)
        if isinstance(row.get("cost"), (int, float)):
            bucket["cost"] += float(row["cost"])
            bucket["cost_known"] = True
        bucket["incomplete"] = bucket["incomplete"] or bool(row.get("incomplete"))
    for bucket in out.values():
        if not bucket["cost_known"]:
            bucket["cost"] = None
    return out


def price_of(task: str, base: Path, docs: list | None = None, by_session: dict | None = None,
             problem: str = "", cost_cfg: dict | None = None) -> dict:
    """The story's price: ONE `task_price` call, shaped for the retro and the budget ceiling.

    `base` is the factory's state folder (`<project>/qa-factory`), `docs` the cost files already
    loaded (`all_cost_files`), `by_session` the project's journals through the reader
    (`read_root`; read here, once, when not handed in). The project's own `cost` block
    (`rate_overrides`) comes from `base/config.json` unless given. The result is `task_price`'s
    answer plus `bound_by_journal` (the sessions the journal names whole) and `problem` (why the
    journals could not be read, or ""). It never raises: an exception inside the price function
    is `{"status": "error", "error": <exception class>}` with empty rows, so a reader says "price
    not computed" and goes on (a retro that cannot price says so, it does not stop: FR-41, P1)."""
    base = Path(base)
    try:
        if docs is None:
            docs = all_cost_files(base)
        if by_session is None:
            by_session, problem = read_root(base)
        if cost_cfg is None:
            config = read_json(base / "config.json", {})
            cost = config.get("cost") if isinstance(config, dict) else None
            cost_cfg = cost if isinstance(cost, dict) else {}
        price = dict(TP.task_price(project_root_of(base), task,
                                   sessions={session_key(p, d): d for p, d in docs},
                                   driver=(by_session, {}), cfg=cost_cfg))
        price["bound_by_journal"] = sorted(sid for sid, entry in by_session.items()
                                           if isinstance(entry, dict) and entry.get("task") == task)
        price["problem"] = problem
        return price
    except Exception as exc:
        return {"status": "error", "error": type(exc).__name__, "sessions": [], "by_agent": [],
                "differ": [], "one_record": [], "unknown": [], "in_progress": [], "finding": "",
                "compared": "", "bound_by_journal": [], "problem": problem}


def _session_tokens(data: dict, task: str, whole: bool) -> int:
    """The tokens of one named session. A session the driver's journal names is the story's
    WHOLE (its money is taken whole), so all the tokens of its file count: the sum over
    `by_task`, else over `agents[]`, else over its request rows. A session bound by an activity
    segment or a chat is the story's in part: `by_task[task]`, else the tokens of its `agents[]`
    of this task. `by_task[task]` already folds every agent dispatched under that task in, so
    the agents are added only when it is absent (summing both doubled a story once)."""
    by_task = data.get("by_task") if isinstance(data.get("by_task"), dict) else {}
    agents = [a for a in (data.get("agents") or []) if isinstance(a, dict)]
    if whole:
        counted = [int(e.get("tokens") or 0) for e in by_task.values() if isinstance(e, dict) and _positive(e.get("tokens"))]
        if counted:
            return sum(counted)
        from_agents = sum(int(a.get("tokens") or 0) for a in agents if _positive(a.get("tokens")))
        if from_agents:
            return from_agents
        return sum(sum(v for k, v in (r.get("usage") or {}).items() if k != "requests" and _positive(v))
                   for r in (data.get("requests") or []) if isinstance(r, dict))
    entry = by_task.get(task)
    if isinstance(entry, dict):
        return int(entry.get("tokens") or 0)
    return sum(int(a.get("tokens") or 0) for a in agents if a.get("task") in (task, "(no task)"))


def story_spend(task: str, root: Path | None = None, troot: Path | None = None,
                price: dict | None = None, docs: list | None = None) -> dict:
    """{usd, usd_low, usd_high, tokens, incomplete, reason, roles_missing, sessions, price_status}
    - the story's whole spend so far, read from the ONE price (`task_price`, via `price_of`).

    The story's sessions are the ones the price names, by evidence (FR-24, B-223): there is no
    ticket-tag filter any more. `usd` is the price when the two records give one figure (agree,
    or one record), None while they differ (`usd_low`/`usd_high` then carry the range, never a
    single figure that looks exact) and None when nothing is priced. A caller that already asked
    hands `price` (and the loaded `docs`) in: one `task_price` call per retro. `incomplete` true
    means a session has no record at all, or a role's usage did not make it into its file, or the
    price could not be computed: the figure is then a floor, never a total.

    Tokens: see `_session_tokens`. `roles_missing` is walked over the named sessions' `agents[]`: a role with an agent of
    zero usage, or declared incomplete with no zero-token entry of its own in the declaring file (a dispatch that left no
    transcript: always missing), and for which NO cost record of the story (an agent with tokens in any
    file, or a driver row with a cost) carries usage; the reason then reads "cost of <role> not estimated: its usage
    was not recorded." (RN1-25 item 5). A "(no task)" agent is counted there and in no total."""
    base = Path(root) if root is not None else state_dir()
    docs = docs if docs is not None else all_cost_files(base)
    price = price if price is not None else price_of(task, base, docs)
    files = cost_files(task, base, troot, price, docs)
    whole = set(price.get("bound_by_journal") or [])
    tokens, candidates, covered, gapped = 0, [], set(), set()
    for path, data in files:
        tokens += _session_tokens(data, task, session_key(path, data) in whole)
        # A role the capture declares incomplete with NO zero-token entry in the same file is a dispatch that left no
        # transcript (cost_capture.incomplete_roles, kind 2): missing whatever other files carry (AR-28, F1 t-1753). With
        # a zero-token entry it is the resumed-agent case and follows the RN1-25 rule below.
        zero_roles = {role_name(a.get("agent")) for a in (data.get("agents") or [])
                      if isinstance(a, dict) and not a.get("tokens")}
        gapped |= {r for r in (role_name(n) for n in (data.get("incomplete_agents") or [])) if r not in zero_roles}
        for agent in (data.get("agents") or []):
            if isinstance(agent, dict) and agent.get("task") in (task, "(no task)"):
                role = role_name(agent.get("agent"))
                if agent.get("tokens"):
                    covered.add(role)                 # a cost record WITH usage exists for this role
                    continue
                # A zero with tool calls is an unmeasured agent; a zero with NO tool calls is idle, not a gap (E-C5,
                # t-1698): `task_price.unread_agent_calls`, the one predicate (AR-15), the same one `task_price` asks.
                if TP.unread_agent_calls(agent) > 0:
                    candidates.append(role)
    # A role is missing only when NO cost record of the story carries usage for it: a zero-token file of a
    # resumed agent beside a file with tokens is not "no recorded usage" printed next to the role's cost line
    # (RN1-25 item 5). A driver row with a cost is a cost record too.
    if candidates and troot is not None:
        covered |= {row["role"] for row in driver_rows(Path(troot)) if isinstance(row.get("cost"), (int, float))}
    missing = [role for role in candidates if role not in covered] + sorted(gapped)
    status = price.get("status")
    low, high = price.get("price_low_usd"), price.get("price_high_usd")
    known = isinstance(low, (int, float)) and isinstance(high, (int, float))
    reasons = []
    if missing:
        reasons.append(" ".join(f"cost of {role} not estimated: its usage was not recorded."
                                for role in sorted(set(missing))))
    if status == "error":
        reasons.append(f"the price was not computed ({price.get('error')}).")
    elif not price.get("sessions"):
        reasons.append("no session of this story has a record.")
    elif status == "incomplete" or price.get("unknown") or price.get("rows_without_session"):
        reasons.append("at least one session of this story has no record of its cost.")
    return {"usd": round(low, 6) if known and low == high else None,
            "usd_low": round(low, 6) if known else None,
            "usd_high": round(high, 6) if known else None,
            "tokens": tokens, "incomplete": bool(reasons), "reason": " ".join(reasons),
            "roles_missing": sorted(set(missing)), "sessions": len(price.get("sessions") or []),
            "price_status": status,
            # the price's own list of agents that ran with usage unread (`task_price`, CD1-13): read here so a reader of
            # the facts sees the price's floor and the role line side by side; its sentence is in the price's finding
            "not_estimated_agents": [dict(a) for a in price.get("not_estimated_agents") or [] if isinstance(a, dict)]}


JOURNAL_CARRIER = "records/journal.jsonl"
NO_FINDING_TEXT = "(no finding text)"


def gate_block_class(notes) -> str:
    """The class of one gate block: the FIRST finding it names, not the whole notes line (the ONE reader; the dashboard
    card delegates here, F6-51 B-4).

    exit_gate writes "block 1/1; broken artifacts: N; first: <finding>; <finding>; <finding>", and N moves with artifacts
    that have nothing to do with the finding, while the findings after the first vary with the story. The class is the
    text after `first: ` cut at the first "; ", then its first 60 characters; a line with no `first: ` is read whole;
    nothing to read is `(no finding text)` - every block is counted under some class, none is dropped. Error direction:
    two defects merged into one class is acceptable, ONE defect split into several (under-counting) is the dangerous
    side, so the findings after the first never enter the key."""
    text = str(notes or "")
    marker = text.find("first: ")
    tail = text[marker + len("first: "):] if marker >= 0 else text
    return tail.strip().split("; ", 1)[0].strip()[:60] or NO_FINDING_TEXT


def gate_block_classes(rows: list, known: bool) -> dict:
    """The per-class count of `gate_block` rows (ONLY refusals: an `unsafe_completion` is not one) and whether one class
    repeats often enough to be a finding (`signal`, at or above the threshold of references/stage-joints.json). `known`
    False (no journal) is an unknown and carries no count and no signal (FR-41)."""
    counted: dict = defaultdict(int)
    for row in rows:
        if row.get("event") == "gate_block":
            counted[gate_block_class(row.get("notes"))] += 1
    worst = sorted(counted.items(), key=lambda kv: (-kv[1], kv[0]))[0] if counted else None
    from stage_joints import threshold          # lazy: the walker's graph is not the retro's
    limit = threshold()
    return {"known": known, "carrier": JOURNAL_CARRIER, "classes": dict(counted),
            "worst": list(worst) if worst else None, "threshold": limit,
            "signal": bool(known and worst and limit is not None and worst[1] >= limit)}


def journal_counts(task: str, root: Path | None = None) -> dict:
    base = Path(root) if root is not None else state_dir()
    # `base` is <project>/qa-factory. `known` comes from the ONE reader and covers every count of the journal: an
    # absent journal is unknown, and no number below it may be read as a measured zero (FR-41, FR-10).
    all_rows, known = read_jsonl_known(RP.record(base.parent, "journal.jsonl"))
    rows = [r for r in all_rows if isinstance(r, dict) and r.get("task") in (task, None, "")]
    events = defaultdict(int)
    families = defaultdict(int)
    for row in rows:
        event = str(row.get("event") or "")
        events[event] += 1
        if event in ("rejected", "reject"):
            families[str(row.get("reason_family") or "unstated")] += 1
    return {"known": known, "carrier": JOURNAL_CARRIER, "events": dict(events),
            "rejects": events.get("rejected", 0) + events.get("reject", 0),
            "reject_families": dict(families),
            "gate_blocks": events.get("gate_block", 0) + events.get("unsafe_completion", 0),
            "gate_block_classes": gate_block_classes(rows, known),
            "compacts": events.get("compact", 0),
            "halts_journalled": events.get("halt", 0)}


def journal_lines(journal) -> list:
    """The retro's journal lines (the Rejects line and the class line). One `known` rules both: a missing journal prints
    `unknown` for every count, never `0` beside an `unknown` (FR-10, FR-41). Facts written before `known` existed carry
    their counts as they were and print them as before."""
    journal = journal if isinstance(journal, dict) else {}
    known = journal.get("known", True)
    carrier = journal.get("carrier") or JOURNAL_CARRIER
    classes = journal.get("gate_block_classes") if isinstance(journal.get("gate_block_classes"), dict) else None
    if not known:
        lines = [f"**Rejects:** unknown · **gate blocks:** unknown · **compacts:** unknown — no journal ({carrier})."]
    else:
        lines = [f"**Rejects:** {journal.get('rejects', 0)}"
                 + (f" ({journal.get('reject_families')})" if journal.get("reject_families") else "")
                 + f" · **gate blocks:** {journal.get('gate_blocks', 0)} (the norm is zero)"
                   f" · **compacts:** {journal.get('compacts', 0)}."]
    if classes is None:                          # facts written before the key existed: no line, not a guess
        return lines
    if not classes.get("known", True):
        return lines + [f"**Gate blocks by class:** unknown — no journal ({carrier})."]
    counted = classes.get("classes") or {}
    if not counted:
        return lines + [f"**Gate blocks by class:** none (0) ({carrier})."]
    shown = "; ".join(f"{name} ×{n}" for name, n in sorted(counted.items(), key=lambda kv: (-kv[1], kv[0])))
    limit = classes.get("threshold")
    return lines + [f"**Gate blocks by class:** {shown} ({carrier})"
                    + ("." if limit is not None else " · threshold unknown (references/stage-joints.json).")]


def stage_times(pipeline: dict) -> dict:
    out = {}
    for sid, entry in sorted((pipeline.get("stages") or {}).items()):
        if not isinstance(entry, dict):
            continue
        seconds = span_seconds(entry.get("stage_started"), entry.get("stage_finished"))
        if seconds is None:
            seconds = span_seconds(entry.get("started"), entry.get("finished"))
        # `span_seconds` clamps a reversed pair to zero, which is how TP2-2553's S0
        # (started 13:20:00Z, finished 11:42:43Z) printed as a stage that took no time and was
        # summed as free. A stage whose clock runs backwards has no duration at all: the
        # finding replaces the number, here and everywhere it is read.
        anomaly = clock_anomaly(entry)
        row = {"status": entry.get("status"), "seconds": None if anomaly else seconds,
               "role": entry.get("role")}
        if anomaly:
            row["clock_anomaly"] = anomaly
        out[str(sid)] = row
    return out


def halts(pipeline: dict) -> dict:
    rows = []
    total = 0
    for halt in pipeline.get("halts") or []:
        if not isinstance(halt, dict):
            continue
        waited = span_seconds(halt.get("at"), halt.get("resolved_at"))
        if waited:
            total += waited
        rows.append({"stage": halt.get("stage"), "seconds": waited,
                     "resolved": bool(halt.get("resolved")),
                     "reason": " ".join(str(halt.get("reason") or "").split())[:160]})
    return {"count": len(rows), "waited_s": total, "rows": rows}


def run_block_metrics(task_root: Path) -> dict:
    """Test-execution volume from work/run-blocks/*.json: runs per S5 window, and the share
    of executions that re-ran an already-green, fingerprint-unchanged test (18 launches
    for a handful of S5 windows on TP1-15045, ~42 test executions, ~9 of them redundant —
    eight re-ran green tests no repair touched). Windows come from the controller's own
    dispatch records (state['dispatches'][id]['window']), the same field
    coverage_contract.py already trusts for S5 acceptance — not guessed from a dispatch id
    string."""
    task_root = Path(task_root)
    block_dir = task_root / "work" / "run-blocks"
    empty = {"jobs": 0, "windows": {}, "executions": 0,
             "duplicate_green_executions": 0, "duplicate_share_percent": None}
    if not block_dir.is_dir():
        return empty
    controller_state = read_json(task_root / "state" / "controller.json", {}) or {}
    dispatches = controller_state.get("dispatches") or {}
    windows: dict = {}
    executions = []
    for bp in sorted_paths(block_dir.glob("*.json")):
        block = read_json(bp, {})
        if not isinstance(block, dict):
            continue
        purpose = block.get("purpose") or (block.get("request") or {}).get("purpose")
        if block.get("import_provenance") or purpose not in \
                {"initial", "repair_verify", "diagnostic", "flaky_diagnostic"}:
            continue
        window = (dispatches.get(block.get("dispatch_id")) or {}).get("window")
        label = f"window {window}" if window is not None else "unscoped"
        windows[label] = windows.get(label, 0) + 1
        start = block.get("attempt_started_at")
        for row in block.get("results") or []:
            if not isinstance(row, dict):
                continue
            executions.append({
                "instance": row.get("instance_id"), "status": row.get("status"),
                "fingerprint": row.get("input_fingerprint") or block.get("input_fingerprint"),
                "started_at": start, "purpose": purpose})
    executions.sort(key=lambda r: r.get("started_at") or "")
    last_pass_fp: dict = {}
    duplicate = 0
    for row in executions:
        key = row["instance"]
        prior_fp = last_pass_fp.get(key)
        if key and prior_fp is not None and row.get("fingerprint") and prior_fp == row["fingerprint"] \
                and row.get("purpose") in ("initial", "repair_verify"):
            duplicate += 1
        if row.get("status") in ("pass", "passed"):
            last_pass_fp[key] = row.get("fingerprint")
        elif row.get("status") in ("fail", "failed") and key in last_pass_fp:
            last_pass_fp[key] = None
    share = round(100 * duplicate / len(executions), 1) if executions else None
    return {"jobs": sum(windows.values()), "windows": windows, "executions": len(executions),
            "duplicate_green_executions": duplicate, "duplicate_share_percent": share}


# SC2-37 (owner's word 29.10.2026: "5 tests, run 31 times, now for the environment, now for the factory's errors" and
# the retro said neither). The causes are DATA (`references/test-run-causes.json`, AR-1); this is the one reader of the
# question (AR-13). The unit is the executed instance, the same number `run_block_metrics` prints as `executions`.
TEST_RUN_CAUSES_FILE = Path(__file__).resolve().parents[1] / "references" / "test-run-causes.json"
UNKNOWN_IDS_SHOWN = 10          # launch ids the retro line names before "and N more" (the JSON keeps them all)
_BLOCK_RUN_PURPOSES = {"initial", "repair_verify", "diagnostic", "flaky_diagnostic"}   # the set run_block_metrics counts


def test_run_causes():
    """The cause table, or None when the file is absent or not the shape this reader needs."""
    table = read_json(TEST_RUN_CAUSES_FILE, None)
    if isinstance(table, dict) and isinstance(table.get("causes"), list):
        return table
    return None


def _run_role(dispatch_id) -> str:
    found = re.match(r"^S\d+-(.+)-\d+$", str(dispatch_id or ""))
    return found.group(1) if found else ""


def _stand_signalled(task_root: Path, job) -> bool:
    """The run's own summary (`stand_signal`, `run_suite.py`) says the stand was the trouble. A job that left no
    summary on disk, or a summary that does not say so, lifts nothing."""
    if not isinstance(job, dict) or not isinstance(job.get("summary"), str):
        return False
    name = re.split(r"[\\/]", job["summary"])[-1]
    data = read_json(task_root / "evidence" / "runs" / str(job.get("job_id")) / name, {})
    return isinstance(data, dict) and bool(data.get("stand_signal"))


def _triage_cause(prev_row, triage_rows: list, table: dict):
    """The verdict of the triage row bound (`contract.bind_triage`, the one binding) to the failure of the previous
    attempt, as a cause; None when no row binds or the verdict is not a cause."""
    if not isinstance(prev_row, dict) or not triage_rows:
        return None
    import contract as C   # lazy: the retro loads without the whole contract when no failure needs binding
    failures, _unnamed = C.triage_failures({"current_results": [prev_row]})
    bound = C.bind_triage(failures, triage_rows)["matched"]
    for rows in bound.values():
        for row in reversed(rows):
            verdict = row.get("verdict")
            target = (table.get("by_triage_verdict") or {}).get(verdict) if isinstance(verdict, str) else None
            if target in table["causes"]:
                return target
    return None


def _instance_name(value):
    """A test's name from a recorded field: a non-empty string, else None (a list or a number names no test)."""
    return value if isinstance(value, str) and value.strip() else None


def _block_launches(block_dir: Path) -> tuple:
    """The launches the run blocks on disk make: `(launches, block ids, unreadable)`. A block whose `purpose` or `results`
    is not the shape the factory writes is counted in `unreadable` and read no further: one story's damaged block never
    stops the retro or the dashboard (AR-2). A block with no purpose, an import and a purpose that is no run are skipped,
    as `run_block_metrics` skips them."""
    launches, block_ids, unreadable = [], set(), 0
    if not block_dir.is_dir():
        return launches, block_ids, unreadable
    for bp in sorted_paths(block_dir.glob("*.json")):
        block = read_json(bp, {})
        if not isinstance(block, dict):
            unreadable += 1
            continue
        request = block.get("request") if isinstance(block.get("request"), dict) else {}
        purpose = block.get("purpose") or request.get("purpose")
        if block.get("import_provenance"):
            continue
        if purpose is not None and not isinstance(purpose, str):
            unreadable += 1
            continue
        if purpose not in _BLOCK_RUN_PURPOSES:
            continue
        results = block.get("results")
        if results is not None and not isinstance(results, list):
            unreadable += 1
            continue
        block_id = str(block.get("block_id") or block.get("attempt_id") or bp.stem)
        block_ids.add(block_id)
        launches.append({"id": block_id, "purpose": purpose, "dispatch_id": block.get("dispatch_id"),
                         "status": block.get("execution_status"), "started": str(block.get("attempt_started_at") or ""),
                         "entries": [(_instance_name(row.get("instance_id")), row) for row in results or []
                                     if isinstance(row, dict)]})
    return launches, block_ids, unreadable


def _job_launches(jobs: list, block_ids: set, table: dict, never_ran) -> tuple:
    """The launches the jobs make where no run block names them: `(launches, apart)`. `apart` counts what is NOT a run:
    `probes` (red_probe), `baselines` (`evidence_phase: baseline`, a capture on the old code: `build_run_block` writes no
    block for it, so it is no run), `not_executed`, `no_totals` (counted by the tests it selected) and `unreadable` (a
    job whose `selected_instance_ids` is not a list)."""
    apart = {"probes": 0, "baselines": 0, "not_executed": 0, "no_totals": 0, "unreadable": 0}
    launches = []
    for job in jobs:
        request = job["request"]
        purpose = request.get("purpose")
        if request.get("evidence_phase") == "baseline":
            apart["baselines"] += 1
            continue
        if purpose in (table.get("not_a_run_purposes") or []):
            continue
        if purpose == "red_probe":
            apart["probes"] += 1
            continue
        job_id = str(job.get("job_id"))
        if job_id in block_ids:
            continue                      # the block names every instance that ran: it is the better record
        state = job.get("execution_status")
        if job.get("status") != "completed" or (isinstance(state, str) and state in never_ran):
            apart["not_executed"] += 1
            continue
        selected = request.get("selected_instance_ids")
        if selected is not None and not isinstance(selected, list):
            apart["unreadable"] += 1
            continue
        if state == "not_executed":
            apart["no_totals"] += 1
        named = [str(one) for one in selected or [] if str(one).strip()]
        launches.append({"id": job_id, "purpose": purpose, "dispatch_id": request.get("dispatch_id"),
                         "status": state, "started": str(job.get("created_at") or ""),
                         "entries": [(one, None) for one in named] or [(None, None)]})
    return launches, apart


def _cause_reader(task_root: Path, table: dict, jobs_by_id: dict):
    """`cause_of(launch, instance, before)`: the cause of one run, the first hit of the table's lookups (the order is in
    `test_run_counts`'s docstring). `manual` is a run whose cause is `person` only when its dispatch says so, else
    `unknown` (S8), whatever the previous attempt was; a manual run of a test not seen before is a first run."""
    causes = table["causes"]

    def target(value):
        return value if isinstance(value, str) and value in causes else None

    dispatches = {}
    for event in read_jsonl(task_root / "state" / "events.jsonl"):
        payload = event.get("payload") if isinstance(event, dict) and event.get("type") == "dispatch" else None
        if isinstance(payload, dict) and payload.get("id"):
            dispatches[str(payload["id"])] = payload
    triage = read_json(task_root / "work" / "triage.json", {})
    triage_rows = [row for row in (triage.get("triage") if isinstance(triage, dict) else None) or []
                   if isinstance(row, dict)]

    def cause_of(launch: dict, instance, before) -> str:
        purpose = launch["purpose"]
        if not isinstance(purpose, str) or purpose not in (table.get("by_purpose") or {}):
            return "unknown"
        fixed = target(table["by_purpose"][purpose])
        if fixed:
            return fixed
        if instance is None:
            return "unknown"
        if before is None:
            return "first_run"
        said = (dispatches.get(str(launch["dispatch_id"])) or {}).get("repair_cause")
        hit = target((table.get("by_repair_cause") or {}).get(said)) if isinstance(said, str) else None
        if purpose == "manual":
            return "person" if hit == "person" else "unknown"
        if hit:
            return hit
        was = before["launch"]
        status = was["status"]
        hit = target((table.get("by_previous_status") or {}).get(status)) if isinstance(status, str) else None
        if hit == "stage_run" and (was["dispatch_id"] == launch["dispatch_id"]
                                   or _run_role(was["dispatch_id"]) == _run_role(launch["dispatch_id"])):
            hit = None                    # a green test run again by the same hand is not a planned stage run
        if hit == "launch_failed" and _stand_signalled(task_root, jobs_by_id.get(was["id"])):
            hit = "environment"
        return hit or _triage_cause(before["row"], triage_rows, table) or "unknown"

    return cause_of


def test_run_counts(task_root: Path) -> dict:
    """How many tests were run, how many times, and why each repeat happened (SC2-37).

    `runs` is the number of executed instances (the number `run_block_metrics` prints as `executions`; the test pins
    them equal on 14857: "5 tests, 31 runs"); `launches` the blocks or jobs that made them; `probes` the red_probe jobs,
    which have no run block and are outside `runs`; `baselines` the `evidence_phase: baseline` jobs, which have none either.
    `unreadable_blocks` counts run blocks whose shape is damaged. `by_cause` sums to `runs`. A launch comes from
    `work/run-blocks/*.json` where the block is on disk (it names every instance that ran), else from the job in
    `state/execution-jobs` through `JobStore.jobs()` (its `selected_instance_ids`). A job that executed nothing
    (`status` not completed, or `execution_status` in `_NEVER_RAN_STATES`) is `not_executed`; a plain `not_executed`
    execution_status is `no_totals`, because that run "may have run every test" (execution_request.py). Corrupt job
    files are `unreadable` (`JobStore.jobs()` skips them silently, so the glob count is taken here).

    The cause of a run is the first hit of: its purpose; first run (the test is new to this story); the dispatch's own
    `repair_cause` in `state/events.jsonl` (NOT `controller.repair_cause`: that one defaults to test_defect, an answer
    to the very question asked); the status of the previous attempt of the same test; a stand signal on that run;
    a triage verdict bound to that failure; else `unknown`, named by launch id. What the controller recorded beats what
    is inferred. `request.reason` is prose and is never read (FR-12).

    Neither carrier on disk is `{"known": False}`, never zero (FR-41); an existing folder with no job is `runs: 0`."""
    task_root = Path(task_root)
    carrier = "work/run-blocks+state/execution-jobs"
    job_dir, block_dir = task_root / "state" / "execution-jobs", task_root / "work" / "run-blocks"
    if not job_dir.is_dir() and not block_dir.is_dir():
        return {"known": False, "carrier": carrier,
                "reason": "the story has neither work/run-blocks nor state/execution-jobs"}
    table = test_run_causes()
    if table is None:
        return {"known": False, "carrier": carrier,
                "reason": "references/test-run-causes.json is missing or unreadable"}
    causes = table["causes"]

    jobs, unreadable, never_ran = [], 0, ()
    if job_dir.is_dir():
        import execution_request as ER   # lazy: the one reader of jobs; a story with no jobs never loads it
        jobs = ER.JobStore(job_dir).jobs()
        never_ran = ER._NEVER_RAN_STATES
        unreadable = max(0, len(list(job_dir.glob("*.json"))) - len(jobs))
    jobs_by_id = {str(job.get("job_id")): job for job in jobs}
    launches, block_ids, unreadable_blocks = _block_launches(block_dir)
    job_launches, apart = _job_launches(jobs, block_ids, table, never_ran)
    launches += job_launches
    unreadable += apart["unreadable"]
    for order, launch in enumerate(launches):
        launch["order"] = order
    launches.sort(key=lambda item: (item["started"], item["order"]))
    cause_of = _cause_reader(task_root, table, jobs_by_id)
    seen: dict = {}
    by_cause: dict = {}
    by_purpose: dict = {}
    per_test: dict = {}
    unknown_ids: list = []
    runs = no_instances = 0
    for launch in launches:
        for instance, _row in launch["entries"]:
            cause = cause_of(launch, instance, seen.get(instance) if instance else None)
            runs += 1
            by_cause[cause] = by_cause.get(cause, 0) + 1
            word = launch["purpose"] if isinstance(launch["purpose"], str) else "unknown"
            by_purpose[word] = by_purpose.get(word, 0) + 1
            if instance is None:
                no_instances += 1
            else:
                per_test[instance] = per_test.get(instance, 0) + 1
            if cause == "unknown" and launch["id"] not in unknown_ids:
                unknown_ids.append(launch["id"])
        for instance, row in launch["entries"]:
            if instance:
                seen[instance] = {"launch": launch, "row": row}
    return {"known": True, "tests": len(per_test), "runs": runs, "launches": len(launches), "probes": apart["probes"],
            "per_test": dict(sorted(per_test.items())), "by_purpose": dict(sorted(by_purpose.items())),
            "by_cause": {cause: by_cause[cause] for cause in causes if cause in by_cause},
            "unknown_jobs": unknown_ids, "not_executed": apart["not_executed"], "no_totals": apart["no_totals"],
            "baselines": apart["baselines"], "no_instances": no_instances, "unreadable": unreadable,
            "unreadable_blocks": unreadable_blocks, "carrier": carrier}


def test_run_sentence(counts) -> str:
    """The ONE sentence for the test-run count; the retro and the dashboard print the same words (AR-19)."""
    if not isinstance(counts, dict):
        return ""
    if not counts.get("known"):
        return f"not recorded — {counts.get('reason') or 'no carrier'} ({counts.get('carrier') or 'unknown carrier'})."
    runs, tests = counts.get("runs", 0), counts.get("tests", 0)
    if not runs:
        return "no test was run."
    words = (test_run_causes() or {}).get("words") or {}
    head = (f"{_plural(tests, 'test', 'tests')}, {_plural(runs, 'run', 'runs')} "
            f"in {_plural(counts.get('launches', 0), 'launch', 'launches')}")
    if counts.get("probes"):
        head += f", plus {_plural(counts['probes'], 'sensitivity probe', 'sensitivity probes')} (not counted as runs)"
    why = ", ".join(f"{words.get(cause, cause)} {n}" for cause, n in (counts.get("by_cause") or {}).items())
    return head + (f": {why}." if why else ".")


def test_run_lines(counts) -> list:
    """The retro's lines for `test_run_counts`: nothing for facts written before the key existed, otherwise the
    sentence, what was not counted as a run and why, and the launches whose cause is unknown (ten ids whole, then
    "and N more"; the JSON always carries them all)."""
    if not isinstance(counts, dict):
        return []
    lines = [f"**Test runs:** {test_run_sentence(counts)}"]
    if not counts.get("known"):
        return lines
    odd = []
    if counts.get("not_executed"):
        odd.append(f"{_plural(counts['not_executed'], 'job', 'jobs')} executed nothing and "
                   f"{'is' if counts['not_executed'] == 1 else 'are'} not counted")
    if counts.get("no_totals"):
        odd.append(f"{_plural(counts['no_totals'], 'job', 'jobs')} recorded no totals (counted by the tests they selected)")
    if counts.get("no_instances"):
        odd.append(f"{_plural(counts['no_instances'], 'run', 'runs')} named no test")
    if counts.get("baselines"):
        odd.append(f"{_plural(counts['baselines'], 'baseline capture', 'baseline captures')} (old code, not a test run) "
                   f"{'is' if counts['baselines'] == 1 else 'are'} not counted")
    if counts.get("unreadable"):
        odd.append(f"{_plural(counts['unreadable'], 'job file', 'job files')} could not be read")
    if counts.get("unreadable_blocks"):
        odd.append(f"{_plural(counts['unreadable_blocks'], 'run block file', 'run block files')} could not be read")
    if odd:
        lines.append("- " + "; ".join(odd) + ".")
    ids = list(counts.get("unknown_jobs") or [])
    if ids:
        shown = ", ".join(str(one) for one in ids[:UNKNOWN_IDS_SHOWN])
        more = len(ids) - UNKNOWN_IDS_SHOWN
        lines.append(f"- launches with an unknown cause: {shown}" + (f" and {more} more" if more > 0 else "") + ".")
    return lines


def resume_metrics(troot: Path) -> dict:
    """How often a role's session was resumed and what it cost in wall time, per stage (t-342, B-273, FR-26/FR-41).

    man1 02.10: S7's analyst was resumed twice and S8's scribe once - about five minutes of 22 - and nothing in the
    retro said so. The carrier is the driver's own journal, `state/driver-runs.jsonl`: a row of `kind: role` with
    `resumed: true` is one resume, its `duration_ms` is the wall time of THAT call, and `resume_reason` (written
    since this field exists; "" on a row from before it) says why. Wall time is the sum of the rows that carry a
    number; rows without one are counted in `wall_unmeasured`, never as zero seconds. A story with no journal file
    has no measurement at all: `{"known": False, "reason": ...}` - an unknown, not "no resumes".

    `assembled_by_code` counts the handoffs the driver built by code instead of resuming the role
    (`state/driver-runs/<dispatch>.json` with `assembled_by: code`), by the stage the dispatch id names - the
    resumes that did not happen."""
    troot = Path(troot)
    path = troot / "state" / DJ.JOURNAL_NAME
    if not path.is_file():
        return {"known": False, "reason": f"the story has no driver journal ({DJ.JOURNAL_NAME})",
                "carrier": f"state/{DJ.JOURNAL_NAME}"}
    by_stage: dict = {}
    count, wall, unmeasured, unreasoned = 0, 0.0, 0, 0
    for row in DJ.read_rows(path):
        if row.get("kind") != "role" or row.get("resumed") is not True:
            continue
        stage = str(row.get("stage") or "unattributed")
        bucket = by_stage.setdefault(stage, {"count": 0, "wall_s": 0, "wall_unmeasured": 0, "reasons": {}})
        bucket["count"] += 1
        count += 1
        millis = row.get("duration_ms")
        if isinstance(millis, (int, float)) and not isinstance(millis, bool) and millis >= 0:
            bucket["wall_s"] += millis / 1000.0
            wall += millis / 1000.0
        else:
            bucket["wall_unmeasured"] += 1
            unmeasured += 1
        reason = str(row.get("resume_reason") or "").strip()
        if not reason:
            unreasoned += 1
            reason = "no reason recorded"
        bucket["reasons"][reason] = bucket["reasons"].get(reason, 0) + 1
    for bucket in by_stage.values():
        bucket["wall_s"] = int(round(bucket["wall_s"]))
    assembled: dict = {}
    try:
        for saved in sorted((troot / "state" / "driver-runs").glob("S*.json")):
            data = read_json(saved, {})
            if isinstance(data, dict) and data.get("assembled_by") == "code":
                stage = (re.match(r"^(S\d+)-", saved.name) or [None, "unattributed"])[1]
                assembled[stage] = assembled.get(stage, 0) + 1
    except OSError:
        pass
    return {"known": True, "carrier": f"state/{DJ.JOURNAL_NAME} (rows of kind role with resumed: true)",
            "cost": "unknown (B-219)",   # a resumed session's cost is cumulative: a cost per resume would be a guess (FR-41)
            "count": count, "wall_s": int(round(wall)), "wall_unmeasured": unmeasured, "no_reason": unreasoned,
            "by_stage": dict(sorted(by_stage.items())), "assembled_by_code": sum(assembled.values()),
            "assembled_by_stage": dict(sorted(assembled.items()))}


# CD1-5: the forecast of a story's price from the precedents of its own size, in its own unit. OH3-15 changed what the
# size letter counts (the register's rows before, the functions now); a letter of one unit never prices a letter of the other.
FORECAST_UNITS = ("requirements", "functions")
FORECAST_MIN_PRECEDENTS = 3       # a median of two is not a forecast; the same three `factory_dashboard.estimate_signals` asks for


def record_unit(forecast) -> str | None:
    """The unit a ledger record's size letter counts, the ONE reader (AR-13; the dashboard and `metric_signals` call it).
    No `size_unit` (a record written before OH3-15, or by a story without `work/sizing.json`) is `requirements`; a value
    that is neither known unit is None, so such a record joins no cohort."""
    value = forecast.get("size_unit") if isinstance(forecast, dict) else None
    if value is None:
        return "requirements"
    return value if value in FORECAST_UNITS else None


def story_size_unit(sizing_doc, size_final) -> dict:
    """The unit facts of one story, read from `work/sizing.json` (the file the unit is computed into), for `estimate_vs_actual`.

    `size_unit` is None while the story has no readable sizing file: an unknown unit is never read as functions (FR-41).
    A file with no `size_unit` is the old world, `requirements`. A re-run S2 moves `sizing.json` and does not overwrite
    `pipeline.json` (OH3-15 3.1), so a recorded `size_final` that differs from the file's `size` without a `size_override`
    was not computed by the unit: it is stamped `requirements` and flagged `size_mismatch`, never `functions`. With an
    override the person's letter is kept and the unit stays the computed one."""
    empty = {"size_unit": None, "function_count": None, "computed_budget": None, "defect_capped": False,
             "size_override": False, "size_mismatch": False}
    if not isinstance(sizing_doc, dict):
        return empty
    unit = "functions" if sizing_doc.get("size_unit") == "functions" else "requirements"
    override = bool(sizing_doc.get("size_override"))
    mismatch = (unit == "functions" and not override and bool(sizing_doc.get("size"))
                and sizing_doc.get("size") != size_final)
    if mismatch:
        unit = "requirements"
    reducers = sizing_doc.get("reducers_applied")
    return {"size_unit": unit,
            "function_count": sizing_doc.get("function_count"),
            "computed_budget": sizing_doc.get("computed_budget"),
            "defect_capped": isinstance(reducers, list) and any(
                isinstance(r, dict) and r.get("name") == "defect-cap" for r in reducers),
            "size_override": override,
            "size_mismatch": bool(mismatch)}


def _usd(value):
    """A usable money figure or None: a number, finite, not negative, never a bool (`True` is an int in Python)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and value > 0 else None   # zero is not a price (FR-41; `story_spend` writes 0.0 for "no cost seen")


def _zero_money(value) -> bool:
    """A recorded 0 (a number, not a bool): no price, which is not the same as a figure that is not a number."""
    return (isinstance(value, (int, float)) and not isinstance(value, bool) and value == 0)


def ledger_rows(state_base) -> list:
    """The estimation ledger's rows (the project is the parent of its `qa-factory/` folder): `sizing.parse_ledger`, the one reader."""
    import sizing
    return sizing.parse_ledger(Path(state_base).parent)


def size_forecast(rows, task: str, size, unit, override: bool = False) -> dict:
    """What stories of this size and unit cost so far: low, median and high of the recorded prices, or `known: false`.

    Direction of error (a ledger reader in a new role: `sizing.parse_ledger` was an optional check, this feeds a number a
    person reads, and it drops a broken line without a word): the forecast may err toward "too few precedents", never
    toward a precise number from mixed data. Only a record of the same unit AND the same size counts, once per story (the
    newest active record), never the story's own; an incomplete record is a floor and no price; a figure that is not a
    plain positive number is no price (a recorded 0 is counted as `no_price`); a null `usd` is never 0 (a range
    `usd_low`/`usd_high` feeds the two ends; the median stands on single figures only, and only on three or more). What was left out is counted in `skipped`, nothing vanishes unseen. Prices are
    as recorded, at the rates of each run (repricing is CD1-25's)."""
    from estimate_record import active_records
    base = {"known": False, "size": size, "unit": unit, "precedents": 0, "needed": FORECAST_MIN_PRECEDENTS}
    if unit not in FORECAST_UNITS:
        return {**base, "reason": "the story has no work/sizing.json, so its unit is not known"}
    if not isinstance(size, str) or size in ("", "unknown"):
        return {**base, "reason": "the story's size is not known"}
    skipped: dict = defaultdict(int)
    groups: dict = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        if row.get("schema_version") != 1:
            skipped["no_schema"] += 1
            continue
        name = row.get("task")
        if not isinstance(name, str) or not name:
            skipped["no_task"] += 1
            continue
        groups.setdefault(name, []).append(row)
    singles, lows, highs, capped = [], [], [], 0
    for name, group in groups.items():
        if name == task:
            continue
        active = active_records(group, name)
        # several active records: the newest by `ts` (a record carries `created_at` until the dashboard names it `ts`)
        chosen = max(enumerate(active), key=lambda p: (str(p[1].get("ts") or p[1].get("created_at") or ""), p[0]),
                     default=(0, None))[1]
        if chosen is None:
            continue
        fc = chosen.get("forecast") if isinstance(chosen.get("forecast"), dict) else {}
        if (fc.get("size_final") or fc.get("size_initial") or fc.get("size")) != size:
            continue                                  # another cohort, not a loss, and its older records are not counted
        skipped["older_record"] += len(group) - 1    # only a story of this cohort was counted; the rest of its records are said
        if fc.get("size_mismatch") is True:
            skipped["mismatch"] += 1
            continue
        row_unit = record_unit(fc)
        if row_unit is None:
            skipped["unknown_unit"] += 1
            continue
        if row_unit != unit:
            skipped["other_unit"] += 1
            continue
        actual = chosen.get("actual") if isinstance(chosen.get("actual"), dict) else {}
        if actual.get("incomplete"):
            skipped["incomplete"] += 1
            continue
        figure, low, high = _usd(actual.get("usd")), _usd(actual.get("usd_low")), _usd(actual.get("usd_high"))
        if actual.get("usd") is not None and figure is None and not _zero_money(actual.get("usd")):
            skipped["bad_usd"] += 1
            continue
        if figure is not None:
            singles.append(figure)
            lows.append(figure)
            highs.append(figure)
        elif low is not None and high is not None and low <= high:
            lows.append(low)
            highs.append(high)
        else:
            skipped["no_price"] += 1
            continue
        capped += 1 if fc.get("defect_capped") is True else 0
    skipped = {key: skipped[key] for key in sorted(skipped) if skipped[key]}
    count = len(lows)
    if count < FORECAST_MIN_PRECEDENTS:
        return {**base, "precedents": count, "skipped": skipped}
    # a median of fewer than three single figures is not a forecast either: it is not printed, and the line says how many it had
    median = statistics.median(singles) if len(singles) >= FORECAST_MIN_PRECEDENTS else None
    return {"known": True, "size": size, "unit": unit, "precedents": count, "low": round(min(lows), 2),
            "median": None if median is None else round(median, 2), "median_of": len(singles), "high": round(max(highs), 2),
            "defect_capped": capped, "by_override": bool(override), "skipped": skipped}


def estimate_vs_actual(task_root: Path, plan_rows: int) -> dict:
    readiness = read_json(task_root / "work" / "requirements-readiness.json", {}) or {}
    pipeline = read_json(task_root / "pipeline.json", {}) or {}
    links = read_json(task_root / "state" / "story-case-links.json", {}) or {}
    manifest = read_json(task_root / "work" / "automation-manifest.json", {}) or {}
    runs = manifest.get("runs") if isinstance(manifest.get("runs"), list) else []
    # Both ends of the size, under the names the dashboard's Precedents block reads. Until
    # 0.7.12 S9 wrote one `size` and the reader asked for `size_initial`/`size_final`, so the
    # block that was meant to answer "what did we forecast, what did it turn out to be" was
    # empty on every story (TP1-15045). A story sized before the split has only `size`,
    # and both ends read as that one value rather than as nothing.
    size = pipeline.get("size") or readiness.get("size") or "unknown"
    size_final = pipeline.get("size_final") or size
    unit = story_size_unit(read_json(task_root / "work" / "sizing.json", None), size_final)
    return {
        "size_forecast": size,
        "size_initial": pipeline.get("size_initial") or size,
        "size_final": size_final,
        "size_reason": pipeline.get("size_reason") or "",
        **unit,
        "requirements": ((readiness.get("register") or {}).get("total")
                         if isinstance(readiness.get("register"), dict) else None),
        "plan_rows": plan_rows,
        "cases_pinned": len([l for l in (links.get("links") or []) if isinstance(l, dict)]),
        "runs": len(runs),
        "runs_redundant": len([r for r in runs if isinstance(r, dict) and r.get("redundant")]),
    }


def _rework_facts(rounds: list, rows: list) -> tuple:
    """`(priced_rework, names, basis, unscoped, count)` of a story's repair rounds: by scope when the controller's dispatch
    records exist, else by the ordinal rule (F10 t-1753: extracted from `numbers`, unchanged)."""
    if rounds:
        # A repair round is a repeated scope (F-4); the money of a round is joined by dispatch id where a cost row
        # carries one (a driver row's `dispatch`), otherwise the round is unpriced.
        repeated = [r for r in rounds if r["rework"]]
        priced_rework = []
        for record in repeated:
            part = [row["cost"] for row in rows if row.get("purpose") == record["id"]
                    and isinstance(row.get("cost"), (int, float))]
            if part:
                priced_rework.append(sum(part))
        rework_names = [r["id"] for r in repeated]
        rework_basis, unscoped = "scope", [r["id"] for r in rounds if r["rework"] is None]
        rework_count = len(repeated)
    else:
        rework = [r for r in rows if r.get("rework")]
        priced_rework = [r["cost"] for r in rework if isinstance(r.get("cost"), (int, float))]
        rework_names = [f"{r['stage']}/{r['role']} round {r['round']}" for r in rework]
        rework_basis, unscoped, rework_count = "ordinal", [], len(rework)
    return priced_rework, rework_names, rework_basis, unscoped, rework_count


def _wait_facts(files: list) -> tuple:
    """`(wait_rows, not_measured, open_questions)` from the cost files' `human_waits[]` (D2-C); a file without it, or one that
    says `unmeasured`, counts in `not_measured` (E-D1). Extracted from `numbers` (F10 t-1753), unchanged."""
    wait_rows, not_measured, open_questions = [], 0, 0
    for _p, data in files:
        listed = data.get("human_waits")
        if data.get("question_waits") == "measured" and isinstance(listed, list):
            wait_rows += [w for w in listed if isinstance(w, dict)]
            open_questions += int(data.get("open_questions") or 0)
        else:
            not_measured += 1
    return wait_rows, not_measured, open_questions


def numbers(task: str, root: Path | None = None, task_root: Path | None = None) -> dict:
    base = Path(root) if root is not None else state_dir()
    troot = Path(task_root) if task_root is not None else artifacts_dir(task)
    pipeline = read_json(troot / "pipeline.json", {}) or {}
    config = read_json(base / "config.json", {})
    cost_cfg = config.get("cost") if isinstance(config, dict) and isinstance(config.get("cost"), dict) else {}
    # The project's journals are read WHOLE, once: the price, the share and the tables all stand
    # on this one reading (what a row's total means is a property of the root). The cost files are
    # loaded once too, and the story's price is asked ONCE (FR-10): everything below that speaks
    # of the story's money reads `price`.
    docs = all_cost_files(base)
    by_session, problem = read_root(base)
    price = price_of(task, base, docs, by_session, problem, cost_cfg)
    files = cost_files(task, base, troot, price, docs)
    spend = story_spend(task, base, troot, price, docs)
    incomplete = spend["incomplete"]
    # The story's cost files are re-priced ONCE, here, and every money figure this function puts in
    # the facts reads the re-priced document: the orchestrator's own money (so that
    # `orchestrator / story price` is a ratio on ONE rate base: a file captured while the project's
    # family table priced a model the catalogue knows holds 1.5 times the list price), the cost
    # files' amounts in the share's basis and the dispatches' costs. The pinned money on disk is
    # history (B-225, t-171): before this, `basis["cost_files"]` and `dispatches()` still printed the
    # 1.5x figures beside a price that had been re-priced.
    repriced = [(path, CC.revalue_document(data, cost_cfg, None)) for path, data in files]
    # In a driver run the journal is the record of what the factory dispatched; the cost files'
    # `agents[]` only ever held what the operator's own session dispatched beside it.
    # The driver's money (the CLI's charge) is at the catalogue's list rates; the price is at the
    # project's own rates when it has some. Every figure derived from the driver's record is put on
    # the price's rate base, session by session (`price_base`), so the page has ONE base: the share's
    # "$3.07 of $17.42" stood under a price of $26.14 until the critic of t-182 measured it.
    rates = price_base(price)
    rules_model_id, rules_models = rules_model(files, pipeline)
    # The controller's dispatch records are the definition of a dispatch and of a repair round (RN1-25): empty means
    # the old ordinal rule, and the facts say which one was used.
    rounds = dispatch_rounds(troot)
    rows = driver_rows(troot, by_session, rates["factors"], {r["id"]: r for r in rounds}) \
        or dispatches(task, repriced, pipeline)
    orch = orchestrator_totals(task, repriced)

    # A story with a driver journal takes the journal's share FIRST, before the branch below:
    # `orchestrator_totals / story_spend` would read about 100 % the day the capture tags driver
    # requests as the orchestrator. The invariant this position keeps: a run WITHOUT a journal
    # file reaches exactly the branch below with today's values; a run WITH one never reaches it,
    # and a journal that prices nothing (or names nothing, or is only partly priced) is an
    # unknown share, not a fall-through to it.
    journal = journal_sessions(troot)
    share, basis, handed = None, None, None
    if journal is not None:
        basis = journal_share(task, journal, by_session, repriced, problem, rates)
        share = basis["share_percent"]
        handed = handed_back(task, by_session, rates["factors"])
    elif not incomplete and isinstance(spend["usd"], (int, float)) and spend["usd"] > 0 \
            and isinstance(orch["cost"], (int, float)):
        share = round(100.0 * orch["cost"] / spend["usd"], 1)

    def weight(row):
        return (row["cost"] if isinstance(row.get("cost"), (int, float)) else 0.0,
                int(row.get("tokens") or 0))

    top = sorted(rows, key=weight, reverse=True)[:3]
    priced_rework, rework_names, rework_basis, unscoped, rework_count = _rework_facts(rounds, rows)
    # A repair round whose price never got captured is not a free repair round: the cost
    # stays unknown rather than collapsing to $0.00, which would read as "rework was free".
    rework_cost = round(sum(priced_rework), 4) if priced_rework else None
    # The dispatch count of a role and a stage is the number of records, not of agent files (a resumed agent is one
    # file for several handoffs: 14 handoffs read as 9). Only a bucket the money tables already hold is changed.
    by_stage, by_role = by_key(rows, "stage"), by_key(rows, "role")
    for bucket_of, field in ((by_stage, "stage"), (by_role, "role")):
        for name, bucket in bucket_of.items():
            records = sum(1 for r in rounds if r[field] == name)
            if records:
                bucket["dispatches"] = records
    first_test = span_seconds(((pipeline.get("stages") or {}).get("S0") or {}).get("started"),
                              pipeline.get("first_test_run_at"))
    plan = read_json(troot / "work" / "test-plan.json", [])
    plan_rows = len(plan) if isinstance(plan, list) else len((plan or {}).get("rows") or [])
    eva = estimate_vs_actual(troot, plan_rows)
    human_wait = sum(int((data.get("human_wait_s") or 0)) for _p, data in files)
    # `human_waits[]` is written by the capture that measures question waits (D2-C). A file without it (an older
    # capture) or one that says `unmeasured` keeps its `human_wait_s` as it was and is NAMED as not measured: its
    # figure is a floor, and no machine time is derived from it (E-D1, FR-41: an old file never reads as "no wait").
    wait_rows, not_measured, open_questions = _wait_facts(files)
    waits_known = bool(files) and not not_measured
    machine = stage_machine_times(stage_times(pipeline), wait_rows if waits_known else None, pipeline)
    # Friction with the factory's own code is measured from the roles' transcripts (FR-55). It is
    # read after everything above so that no failure in it can take the retro's other numbers down:
    # a measurement that cannot be taken is `unknown` with its reason, never an exception (FR-41).
    try:
        import friction as friction_module
        # The valuation reads the config's `cost` block (rate_overrides, model_prices), exactly as
        # cost_capture passes `load_config().get("cost")`; the whole config would price nothing.
        friction = friction_module.story_friction(
            troot, base, base.parent, (read_json(base / "config.json", {}) or {}).get("cost") or {})
    except Exception as exc:
        friction = {"status": "unknown", "reason": f"{type(exc).__name__}: {exc}"}
    # The sources the person left out before the run (t-172 P6): the same reader gate A uses, so the two
    # never tell two stories (FR-10). An unreadable record is a fact of its own, not an exception that
    # takes the retro down and not an empty list that reads as "nothing was left out" (FR-41).
    try:
        import gate_brief
        left_out, left_out_unread = gate_brief.left_out_sources(troot), ""
    except Exception as exc:
        left_out, left_out_unread = [], f"{type(exc).__name__}: {' '.join(str(exc).split())[:200]}"
    # The counters of the use of what the factory knew (t-2277 FL-8): `report_facts` is their one reader (AR-13); a key only for a story that
    # has them, so an older story's numbers are what they were. A counter that cannot be read is said, never dropped (FR-41).
    knowledge: dict = {}
    try:
        import report_facts
        kept = report_facts.knowledge_facts(troot)
        if kept:
            knowledge = {"facts": kept, "questions": report_facts.question_count(troot)}
    except Exception as exc:
        knowledge = {"problem": f"{type(exc).__name__}: {' '.join(str(exc).split())[:200]}"}

    return {
        **({"knowledge": knowledge} if knowledge else {}),
        "task": task,
        "sessions": [r["session"] for r in price.get("sessions") or []],
        "story": spend,
        # The story's price: `task_price`'s whole answer, asked once (see above), and why the
        # journals could not be read when they could not.
        "price": price,
        "price_problem": problem,
        "incomplete": incomplete,
        "incomplete_reason": spend["reason"],
        "orchestrator": orch,
        # There is no "control layer" total (owner, 30.09): the conductor's money is the share's
        # numerator, and the money of resumed roles is `handed_back_to_roles`.
        "handed_back_to_roles": handed,
        # The rules' cost is priced at the cache-read rate of the model the story RAN on: the dominant
        # model of its cost files, else the one the pipeline names; with neither the rate is unknown
        # and the line says so (FR-41), it is never another model's rate.
        "price_base": rates,
        "rules_weight": rules_weight(rows, rules_model_id, cost_cfg, rules_models),
        "orchestrator_share_percent": share,
        # The base of the share on a driver run (None on a run without a journal): the sums, the
        # session counts by record, and the reason when the share is unknown.
        "orchestrator_share_basis": basis,
        "orchestrator_share_limit_percent": share_limit_percent(base),
        "orchestrator_by_stage": (orchestrator_by_stage(task, repriced, pipeline) if journal is None
                                  else orchestrator_by_stage(task, [], pipeline, by_session, rates["factors"])),
        "clock_anomalies": [dict(stamps, stage=sid) for sid, stamps in clock_anomalies(pipeline)],
        "by_stage": by_stage,
        "by_role": by_role,
        "dispatches": rows,
        # the controller's dispatch records the counts and the repair rounds stand on (`[]`: none, the ordinal rule)
        "dispatch_records": rounds,
        "top_dispatches": [{"role": r["role"], "stage": r["stage"], "cost": r["cost"],
                            "tokens": r["tokens"], "requests": r["requests"],
                            "round": r["round"]} for r in top],
        # `basis`: "scope" (a round repeats an earlier scope of the same stage and role, from the dispatch records) or
        # "ordinal" (no records: the second and later agent file of a role); `unscoped`: dispatches with an empty scope,
        # which are neither counted as repairs nor as new windows; `priced_rounds`: how many rounds carry a price.
        "rework": {"dispatches": rework_count, "cost": rework_cost, "rounds": rework_names,
                   "basis": rework_basis, "unscoped": unscoped, "priced_rounds": len(priced_rework)},
        "journal": journal_counts(task, base),
        "stage_times": stage_times(pipeline),
        # a stage's wall time minus the question and turn waits inside it; None where the waits are not measured
        "stage_machine_s": machine,
        "halts": halts(pipeline),
        "human_wait_s": human_wait,
        "human_wait": {"seconds": human_wait,
                       "question_waits": ("measured" if waits_known else "not_measured" if not_measured else "no_cost_file"),
                       "files_not_measured": not_measured, "open_questions": open_questions},
        "human_waits": wait_rows,
        "time_to_first_test_s": first_test,
        "estimate_vs_actual": eva,
        # CD1-5: what stories of this size and unit cost before; read by `render` (the one line) and nowhere else
        "size_forecast": size_forecast(ledger_rows(base), task, eva["size_final"], eva["size_unit"],
                                       override=eva["size_override"]),
        "test_runs": run_block_metrics(troot),
        # SC2-37: tests, runs and the cause of each repeat; read by `render`, `observations`, `estimate_facts` and the dashboard
        "test_run_counts": test_run_counts(troot),
        # t-342 (B-273): resumes of role sessions and their wall time per stage, with the journal that carries them
        "resumes": resume_metrics(troot),
        "friction": friction,
        # [{id, as_written, reason (whole), origin, matched, revoked, revoked_words}]: in the JSON facts
        # even when the render has no line for it.
        "sources_left_out": left_out,
        "sources_left_out_unread": left_out_unread,
        # "" for a story with no Codex call: the render prints a line only for a non-empty one.
        "codex_tariff": codex_tariff_label(row for rows in (journal or {}).values() for row in rows),
    }


def money(value) -> str:
    return f"${value:,.2f}" if isinstance(value, (int, float)) else "not priced"


def clock(seconds) -> str:
    if not isinstance(seconds, (int, float)):
        return "unknown"
    seconds = int(seconds)
    return f"{seconds // 3600}h {seconds % 3600 // 60}m" if seconds >= 3600 \
        else f"{seconds // 60}m {seconds % 60}s"


def share_lines(basis: dict, share) -> list:
    """The share of a driver run for a person (FR-6: plain words, no field names), saying exactly
    what it stands on: "the driver's own record of N sessions" is written only when all N are
    priced by it, which is the only case a share exists. With any session unknown there is no
    share, only the reason and the known amounts as amounts (FR-41): no sentence then claims a
    charge for each session. The sessions the reader counted under another task come last."""
    if isinstance(share, (int, float)):
        lines = [f"**Orchestrator share: {share}%.** Measured on the driver's own record of "
                 f"{_plural(basis.get('sessions', 0), 'session', 'sessions')}, every one of them "
                 f"priced by it: the conductor's "
                 f"{_plural(basis.get('conductor_sessions', 0), 'session', 'sessions')} "
                 f"cost {money(basis.get('conductor_usd'))} of {money(basis.get('total_usd'))}. "
                 "The driver's code spends no model money, so the orchestrator here is the "
                 "conductor. Choosing a role and handing it something to redo is the conductor's "
                 "management and is all this share counts; the extra work the role then does is "
                 "the role's own cost, on its own line below."]
        on_rates = rates_sentence(basis.get("on_project_rates"), basis.get("unscaled"))
        if on_rates:
            lines[0] += " " + on_rates
    else:
        lines = [f"**Orchestrator share: not computable.** {basis.get('reason') or ''}".rstrip()]
        if basis.get("known_usd") is not None:
            lines[0] += (f" Known amounts, not a share: the conductor's "
                         f"{_plural(basis.get('conductor_known', 0), 'session', 'sessions')} with a driver "
                         f"record cost {money(basis.get('conductor_usd'))}; the roles' "
                         f"{_plural(basis.get('role_known', 0), 'session', 'sessions')} with one cost "
                         f"{money(basis.get('role_usd'))}.")
            on_rates = rates_sentence(basis.get("on_project_rates"), basis.get("unscaled"))
            if on_rates:
                lines[0] += " " + on_rates
    left = basis.get("left_out") or []
    if left:
        lines += ["", "Left out of both sums, because a session is one process and is counted once, "
                      "under the task with its earliest record:"]
        lines += [f"- session {row['session']} is named by {row['journals']} task journals; "
                  f"counted under {row['counted_under']}" for row in left]
    return lines


def rates_sentence(on_project, unscaled) -> str:
    """The sentence that says which rate base a driver-derived amount is on, when the project prices
    at its own rates (empty otherwise: then the amounts are what the CLI charged, as the price's own
    rates are the list prices). Sessions left at the CLI's own list-price figure are counted: there is
    no list price of their transcripts to put it on the project's rates by."""
    if not on_project:
        return ""
    text = ("Every amount is the driver's own charge put on the project's own rates, session by session: "
            "the same rates as the story's price.")
    if unscaled:
        n = len(unscaled)
        text += (f" {_plural(n, 'session', 'sessions')} could not be put on them (the transcripts at the catalogue's "
                 f"rates are $0 or unknown), so {'it stays' if n == 1 else 'they stay'} at the CLI's own "
                 "list-price charge.")
    return text


def handed_back_lines(handed, rates: dict | None = None) -> list:
    """The money of resumed role sessions as a line of ROLE spend (owner, 30.09): the conductor
    chose the role and handed the work back, which is its management; what the role then spent
    doing it is the role's cost and is in no part of the orchestrator's share. `rates`
    (`price_base`) says which rate base the amount is on when the project prices at its own."""
    if not isinstance(handed, dict):
        return []
    sessions, unknown = handed.get("sessions") or 0, handed.get("unknown") or 0
    why = (f"{_plural(unknown, 'resumed role session has', 'resumed role sessions have')} no usable "
           "driver record")
    if not sessions and not unknown:
        return ["**Role spend - work the conductor handed back to roles: none.** No role session "
                "was resumed after a question or a return."]
    if not sessions:
        head = f"**Role spend - work the conductor handed back to roles: not known.** {why.capitalize()}."
    else:
        head = (f"**Role spend - work the conductor handed back to roles: {money(handed.get('usd'))} "
                f"over {_plural(sessions, 'resumed role session', 'resumed role sessions')}.**"
                + (f" {why.capitalize()} and {'is' if unknown == 1 else 'are'} not in this amount."
                   if unknown else ""))
    on_rates = rates_sentence(bool((rates or {}).get("project_rates")), (rates or {}).get("unscaled"))
    return [head + " Choosing the role and handing the work back is the conductor's management; "
            "what the role then spent doing it is the role's own cost, so it is not counted as "
            "the orchestrator's." + (" " + on_rates if on_rates else "")]


def price_money(value) -> str:
    """$1,234.56 of a price figure, rounded half up ONCE, at display, from the figure's shortest
    decimal spelling (the price function sums in Decimal and rounds nowhere; `money` rounds a
    binary float half to even, which would print $0.12 for 0.125). `not priced` for no figure."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return "not priced"
    return "$" + format(Decimal(repr(float(value))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ",")


def price_words(pair: dict, to_the_cent: bool = False) -> str:
    """One figure, or `from $low to $high` while the two ends differ, for a pair of
    `price_low_usd` / `price_high_usd` (the story's, or one row by agent's). `to_the_cent` (a row
    of the table by agent) prints one figure when the two ends read the same at the cent, so a
    row whose records differ by a hundredth of a cent does not read as a range of nothing; the
    STORY's pair is never collapsed that way: while the records differ it is a range."""
    low, high = pair.get("price_low_usd"), pair.get("price_high_usd")
    if not isinstance(low, (int, float)) or not isinstance(high, (int, float)):
        return "not priced"
    if low == high or (to_the_cent and price_money(low) == price_money(high)):
        return price_money(low)
    return f"from {price_money(low)} to {price_money(high)}"


def price_lines(data: dict) -> list:
    """The story's price for a person (FR-6: plain words, no field name), exactly as `task_price`
    states it and from nothing else - the retro computes no second figure (FR-10, P18):

      agrees             one figure, and what was compared
      differs            "from $low to $high" - no single figure is published while the two
                         records disagree - and the price function's finding, in its own words
      not_cross_checked  the figure, marked not cross-checked: there is one record only (FR-41); when the
                         answer says `single_source` (the chat is the only record, no journal names a session,
                         no money missing) the mark is `task_price.SINGLE_SOURCE_WORDS`, and the paragraph
                         still ends `; INCOMPLETE` where a gap exists (information never hides a gap)
      incomplete         what is known ("at least") and why the rest is not; or "not known" when
                         no session has a record at all
      error              the exception class and "price not computed": the retro goes on

    No sentence says which record is the authoritative one, because neither is: a gap is a defect
    of the factory's measurement, to be fixed, not a caption under a number (P18). The project's
    own rates, when it has them, are named in the finding. The cost files' token count is printed
    after the figure, and the catalogue revision the rates come from (FR-27).

    UNDER THE PROJECT'S OWN RATES (`rate_overrides`: a person's price replaces the catalogue's, P18)
    the figure is at those rates, and the paragraph says so instead of "the catalogue's list prices":
    the records are compared at the catalogue's list rates (the CLI's charge is at them), so an agreeing
    pair is said to agree THERE, on its own figure, while the project's rates give the price; the
    not-cross-checked wording and the rates line name the project's price table. The tolerance of the
    check is the price function's constant, in words (`task_price.tolerance_words`)."""
    price, story = data.get("price") or {}, data.get("story") or {}
    status = price.get("status")
    finding = " ".join(str(price.get("finding") or "").split())
    compared = str(price.get("compared") or "").strip()
    figure = price_words(price)
    floor = bool(data.get("incomplete"))
    project = TP.project_rates_applied(price)
    tolerance = TP.tolerance_words()
    at_list = price_money((price.get("totals") or {}).get("a_comparable"))
    if not status:
        return ["**Story price: not known.** No price was computed for this render."]
    if status == "error":
        return [f"**Story price: price not computed ({price.get('error')}).** The factory could not "
                "price this story; this is a defect of its measurement, not a fact about the story. "
                "No figure is published."]
    if not isinstance(price.get("price_low_usd"), (int, float)):
        head = ("**Story price: not known.** No session of this story has a record of its cost. "
                + finding.replace("No session of this task has a record.", "").strip())
    elif status == TP.DIFFERS:
        head = (f"**Story price: {figure}.** The two records of this price disagree, so no single "
                "figure is published: the low end takes the lower record of every session, the high "
                + ("end the higher, both ends at the project's own rates (the CLI's charge is put on them "
                   "session by session). " if project else "end the higher. ") + finding)
    elif status == TP.AGREES:
        if project:
            head = (f"**Story price: {figure}{' — INCOMPLETE' if floor else ''}.** The project's own rates were "
                    "applied to it, so this is the price at the person's rates and not at the catalogue's list "
                    f"prices. At the catalogue's list rates the two records, the transcripts and the CLI's own "
                    f"charge, agree on {at_list}, session by session, within {tolerance} each. "
                    f"Compared: {compared}. {finding}")
        else:
            head = (f"**Story price: {figure}{' — INCOMPLETE' if floor else ''}.** Two records agree on it: "
                    "the transcripts priced at the catalogue's list rates and the CLI's own charge, "
                    f"session by session, within {tolerance} each. Compared: {compared}. {finding}")
    elif status == TP.NOT_CROSS_CHECKED:
        verdict = TP.SINGLE_SOURCE_WORDS if price.get("single_source") is True else "not cross-checked"
        head = (f"**Story price: {figure} — {verdict}{'; INCOMPLETE' if floor else ''}.** It "
                "comes from one record, the transcripts priced at "
                + ("the project's own rates" if project else "the catalogue's list rates")
                + f": nothing could be compared against a second record ({compared}). {finding}")
    else:
        head = f"**Story price: at least {figure} — INCOMPLETE.** {finding}"
    head = head.strip()
    if floor and isinstance(price.get("price_low_usd"), (int, float)):
        # Some role's usage never made it into its file, or a session has no record: whatever the
        # status says, the figure is a floor and is called one.
        head += f" {'' if 'INCOMPLETE' in head else 'INCOMPLETE. '}{data.get('incomplete_reason') or ''}" \
                " The figure is a floor, not a total."
    extra = [f"Tokens recorded in the cost files of these sessions: {story.get('tokens', 0):,}."]
    if price.get("catalogue_revision"):
        extra.append((f"Rates: the project's own price table where it has a rate, the catalogue's list prices "
                      f"(revision {price['catalogue_revision']}) for the rest; the driver's own amounts below are put "
                      "on the same rates." if project else
                      f"Rates: the catalogue's list prices, revision {price['catalogue_revision']}."))
    if data.get("price_problem"):
        extra.append(f"Note: {data['price_problem']}.")
    return [head + " " + " ".join(extra)]


def agent_table_lines(price: dict) -> list:
    """The price by agent: the two records as they stand, and each agent's share of the price.
    The price column adds up to the story's price, exactly (the price function checks it and is
    incomplete when it does not): the table is a split of the price, not a second figure.

    The heading says the column adds up "exactly", and a person adds the printed cents: rows that each
    round correctly summed a cent away from the printed story figure (the critic of t-182 measured
    it on the cmp1 copies). The cents of every column are chosen by the largest-remainder method
    (`task_price.display_cents`) so each printed column adds up to the printed total under it; a
    range's low and high are rounded independently, each to its own end."""
    rows = price.get("by_agent") or []
    if not rows:
        return []
    totals = price.get("totals") or {}

    def exact(value):
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None
    low_c, high_c, a_c, b_c = TP.display_cents(
        [[exact(r.get("price_low_usd")) for r in rows], [exact(r.get("price_high_usd")) for r in rows],
         [exact(r.get("a_usd")) for r in rows], [exact(r.get("b_usd")) for r in rows]],
        [exact(price.get("price_low_usd")), exact(price.get("price_high_usd")),
         exact(totals.get("a")), exact(totals.get("b"))], not_below={1: 0})
    lines = ["", "**Price by agent.** Each row is that agent's share of the story's price, and the "
                 "price column adds up to the story's price above, exactly: nothing is counted "
                 "twice and nothing is left out. The two records it rests on are beside it, as "
                 "they stand (the data-fetching calls are the scout's).",
             "", "| Agent | Sessions | Transcripts at catalogue rates | The CLI's own charge | Price |",
             "|---|---|---|---|---|"]
    for i, row in enumerate(rows):
        name = str(row.get("agent"))
        if row.get("differing_sessions"):
            name += f" ({_plural(row['differing_sessions'], 'session differs', 'sessions differ')})"
        if row.get("remote_calls"):
            name += f" ({_plural(row['remote_calls'], 'remote call', 'remote calls')} with no receipt: cost unknown)"
        if low_c[i] is None or high_c[i] is None:
            price_cell = "not priced"
        elif low_c[i] == high_c[i]:
            price_cell = TP.usd_from_cents(low_c[i])
        else:
            price_cell = f"from {TP.usd_from_cents(low_c[i])} to {TP.usd_from_cents(high_c[i])}"
        lines.append(f"| {name} | {row.get('sessions', 0)} | "
                     f"{TP.usd_from_cents(a_c[i]) if a_c[i] is not None else 'not priced'} | "
                     f"{TP.usd_from_cents(b_c[i]) if b_c[i] is not None else 'unknown'} | {price_cell} |")
    lines.append(f"| **Story** | {len(price.get('sessions') or [])} | {price_money(totals.get('a'))} | "
                 f"{price_money(totals.get('b'))} | {price_words(price)} |")
    return lines


def left_out_retro_lines(data: dict) -> list:
    """The sources the person left out before the run, for the retro: every one, the reason WHOLE (gate A
    clips it; a retro is the record), in the words gate A uses (`gate_brief.left_out_lines`). [] when the
    story has none - a story without a list renders exactly as before."""
    lines = []
    try:
        import gate_brief
        lines = gate_brief.left_out_lines(data.get("sources_left_out") or [])
    except Exception as exc:
        lines = [f"the sources the person left out before the run could not be listed "
                 f"({type(exc).__name__}): a defect of the factory's own record"]
    if data.get("sources_left_out_unread"):
        lines.append("the record of the sources the person left out before the run could not be read, so this "
                     "retro cannot say what it named: a defect of the factory's own record")
    return lines


FORECAST_UNIT_WORDS = {"functions": "the function count", "requirements": "the requirement rows"}
FORECAST_LEFT_OUT_WORDS = {      # plain words for what `size_forecast` left out (FR-6): the key is never shown
    "other_unit": "counted in the other unit", "unknown_unit": "of an unknown unit", "mismatch": "whose size letter was not computed by the unit",
    "incomplete": "incomplete (a floor is no price)", "bad_usd": "with a price that is not a plain number", "no_price": "with no price",
    "no_schema": "of an older record form", "no_task": "naming no story", "older_record": "superseded by a newer record of the same story"}


def size_forecast_line(data: dict) -> str:
    """The one line of the retro for `size_forecast` (CD1-5): the range and the median of what stories of this size and unit
    cost before, beside this story's price, or why there is no forecast. Prices are as recorded, never repriced here."""
    fc = data.get("size_forecast") or {}
    label = "**Forecast from precedents:** "
    size, unit = fc.get("size"), fc.get("unit")
    unit_words = FORECAST_UNIT_WORDS.get(unit, "an unknown unit")
    if not fc.get("known"):
        if fc.get("reason"):
            return label + f"No forecast by size: {fc['reason']}."
        return label + (f"Too few {size} stories on {unit_words} to forecast from "
                        f"({fc.get('precedents', 0)} of {fc.get('needed', FORECAST_MIN_PRECEDENTS)}).")
    capped = fc.get("defect_capped") or 0
    text = (f"{size} stories on {unit_words} so far: {money(fc.get('low'))}..{money(fc.get('high'))}, "
            + (f"median {money(fc['median'])}, " if fc.get("median") is not None else
               f"no median (only {fc.get('median_of') or 0} of {fc.get('precedents')} prices are one figure, a median needs "
               f"{FORECAST_MIN_PRECEDENTS}), ")
            + f"{fc.get('precedents')} precedents"
            + (f" (of which {_plural(capped, 'defect ticket', 'defect tickets')})" if capped else "")
            + ", at the rates of each run.")
    price = (data.get("price") or {})
    this = price_words(price)
    if data.get("incomplete") and this != "not priced":
        this += " (a floor: the cost capture is incomplete)"
    count = (data.get("estimate_vs_actual") or {}).get("function_count")
    text += f" This one: {this}" + (f", {_plural(count, 'function', 'functions')}" if unit == "functions"
                                    and isinstance(count, int) and not isinstance(count, bool) else "") + "."
    if fc.get("by_override"):
        text += " The size is by override: a person set it."
    left = fc.get("skipped") or {}
    if left:
        text += (f" {_plural(sum(left.values()), 'record', 'records')} left out: "
                 + ", ".join(f"{n} {FORECAST_LEFT_OUT_WORDS.get(key, key)}" for key, n in left.items()) + ".")
    return label + text


def rework_line(rework: dict) -> str:
    """The Rework line. It names the definition it counted by (RN1-25): a repeated scope when the controller's dispatch
    records are there, the per-role ordinal otherwise, and the dispatches whose empty scope could be neither (E-D3). A
    facts file written before `basis` existed prints the plain old line."""
    count = rework.get("dispatches", 0)
    basis = rework.get("basis")
    line = f"**Rework:** {count} repair round(s)"
    if count:
        line += f" ({', '.join(rework.get('rounds') or [])}) costing {money(rework.get('cost'))}"
        priced = rework.get("priced_rounds")
        if basis == "scope" and priced is not None and priced < count:
            line += f" (priced for {priced} of {count} round(s))"
    else:
        line += " — nothing was redone"
    if basis == "scope":
        line += " — a repair round is a dispatch whose scope an earlier dispatch of the same stage and role already had"
    elif basis == "ordinal":
        line += " (counted per role, dispatch records absent)"
    unscoped = rework.get("unscoped") or []
    if unscoped:
        line += (f"; {_plural(len(unscoped), 'dispatch', 'dispatches')} with an empty scope "
                 f"({', '.join(unscoped[:5])}{', and more' if len(unscoped) > 5 else ''}) "
                 "could not be told from a new window and are not counted")
    return line + "."


def human_wait_note(wait) -> str:
    """What the human-wait figure leaves out, in words: question waits an older capture did not measure (its figure is a
    floor, E-D1) and questions still open (an open wait has no known length, E-C2)."""
    if not isinstance(wait, dict):
        return ""
    if wait.get("question_waits") == "not_measured":
        return " (question waits not measured by this capture)"
    if wait.get("open_questions"):
        return f" ({_plural(wait['open_questions'], 'question', 'questions')} still open: an open wait is not a known length)"
    return ""


def render(data: dict, left_out: bool = True) -> str:
    """`work/retro-numbers.md`. `left_out=False` is for `retro_document`, which carries the lines of the
    sources the person left out under its own heading and not a second time inside this block."""
    task = data.get("task", "?")
    lines = [f"## Retro numbers — {task}", "",
             "<!-- computed by scripts/retro_numbers.py; do not recompute by hand -->", ""]
    basis = data.get("orchestrator_share_basis")
    # The story's price first, from the ONE price function and from nothing else. `retro.md`
    # carries this money on purpose: the owner's word (30.09, F11) is that a retro keeps its
    # money, and that "no money in the repository" is about the test report. That is the ONE
    # exemption from P18's "money in no file of the repository", and it is stated here, at the
    # writer, and not in the report file.
    lines += price_lines(data)
    if data.get("codex_tariff"):
        lines += ["", data["codex_tariff"]]
    if isinstance(basis, dict):
        # A driver run: the share is stated against the driver's own record of the sessions, so
        # the two quantities never read as one number (FR-25).
        lines += ["", *share_lines(basis, data.get("orchestrator_share_percent"))]
        handed = handed_back_lines(data.get("handed_back_to_roles"), data.get("price_base"))
        if handed:
            lines += ["", *handed]
        finding = orchestrator_finding(data)
        if finding:
            lines += ["", f"**Finding about the factory:** {finding}"]
    elif data.get("incomplete"):
        lines += ["", "No orchestrator share is published while the figure is a floor."]
    else:
        share = data.get("orchestrator_share_percent")
        lines += ["", "**Orchestrator share: " + (f"{share}%.**" if share is not None else "not computable.**")]
        finding = orchestrator_finding(data)
        if finding:
            lines += ["", f"**Finding about the factory:** {finding}"]
    lines += agent_table_lines(data.get("price") or {})
    rules = data.get("rules_weight") or {}
    unpriced = (" Not measured, so left out of this total: " + ", ".join(rules["unmeasured_roles"])
                + " (their rules file could not be read).") if rules.get("unmeasured_roles") else ""
    if rules.get("unknown"):
        lines += ["", f"**The rules' cost is not known** — unknown: {rules['unknown']}"
                      + (f" Not measured: {', '.join(rules['unmeasured_roles'])}." if rules.get("unmeasured_roles") else "")]
    elif rules and rules.get("rate_per_mtok") is None:
        # No model of the story is known, or it has no cache-read rate: the cost of the rules is an
        # UNKNOWN and says so (FR-41); the tokens and the requests are facts and stay.
        lines += ["", f"**The rules' cost is not known** — {rules['tokens']:,} cache-read tokens over "
                      f"{rules['requests']:,} requests, but {rules.get('reason') or 'there is no cache-read rate'}. "
                      "(" + rules["assumption"] + ".)" + unpriced]
    elif rules:
        layers = rules.get("by_layer") or {}
        heaviest = max(layers.items(), key=lambda kv: kv[1])[0] if layers else "?"
        which = ""
        if rules.get("model"):
            whose = "the project's own " if rules.get("rate_source") == "project" else "the "
            which = (f", {whose}cache-read rate of {rules['model']}"
                     + (f" (the model with the most cache-read tokens of the {rules['models']} in the story's cost files)"
                        if (rules.get("models") or 0) > 1 else ""))
        lines += ["", f"**The rules cost {money(rules['usd'])}** — "
                      f"{rules['tokens']:,} cache-read tokens over {rules['requests']:,} requests "
                      f"at ${rules['rate_per_mtok']}/Mtok{which}. By layer: "
                      + ", ".join(f"{name} {money(value)}" for name, value in
                                  sorted(layers.items(), key=lambda kv: -kv[1]))
                      + f". The heaviest is `{heaviest}` — a byte added there is billed on every "
                        "turn of every dispatch of every story. (" + rules["assumption"] + ".)" + unpriced]
    # The friction section prints even when nothing could be measured: a retro that says nothing
    # about it reads as "no friction", and `unknown` is the honest word (FR-41, FR-55).
    try:
        import friction as friction_module
        lines += friction_module.section_lines(data.get("friction"), money)
    except Exception as exc:
        lines += ["", "**Friction with the factory's own code**", "",
                  f"Friction: unknown — {type(exc).__name__}: {exc}"]
    # "Wall time" is the stage's clock; "Machine time" is that minus the waits for a person inside it. A facts file
    # written before `stage_machine_s` has no such column to fill: it prints `unknown`, never the wall time again.
    lines += ["", "| Stage | Dispatches | Requests | Tokens | Cost | Wall time | Machine time |",
              "|---|---|---|---|---|---|---|"]
    times = data.get("stage_times") or {}
    machine_times = data.get("stage_machine_s") or {}
    for stage, bucket in sorted((data.get("by_stage") or {}).items()):
        row = times.get(stage) or {}
        # A stage whose clock runs backwards has no duration to print. Until 0.7.18 the
        # clamped span put "0m 0s" here (TP2-2553's S0), which read as a stage that
        # cost nothing rather than as a stage nobody can time.
        spent = "clock anomaly" if row.get("clock_anomaly") else clock(row.get("seconds"))
        lines.append(f"| {stage} | {bucket['dispatches']} | {bucket['requests']} | "
                     f"{bucket['tokens']:,} | {money(bucket['cost'])}"
                     + (" (incomplete)" if bucket.get("incomplete") else "")
                     + f" | {spent} | {clock(machine_times.get(stage))} |")
    orch = data.get("orchestrator") or {}
    lines.append(f"| orchestrator | 1 | {orch.get('requests', 0)} | "
                 f"{orch.get('tokens', 0):,} | {money(orch.get('cost'))} | "
                 f"- | {clock(orch.get('machine_s'))} |")
    lines += ["", "| Role | Dispatches | Requests | Tokens | Cost |", "|---|---|---|---|---|"]
    for role, bucket in sorted((data.get("by_role") or {}).items()):
        lines.append(f"| {role} | {bucket['dispatches']} | {bucket['requests']} | "
                     f"{bucket['tokens']:,} | {money(bucket['cost'])}"
                     + (" (incomplete)" if bucket.get("incomplete") else "") + " |")
    top = data.get("top_dispatches") or []
    lines += ["", "**Three most expensive dispatches:** "
              + ("; ".join(f"{t['role']} {t['stage']} round {t['round']} — {money(t['cost'])}, "
                           f"{t['requests']} requests, {t['tokens']:,} tokens" for t in top)
                 or "none recorded")]
    lines.append(rework_line(data.get("rework") or {}))
    lines += journal_lines(data.get("journal"))
    halt = data.get("halts") or {}
    lines.append(f"**Halts:** {halt.get('count', 0)}, waiting {clock(halt.get('waited_s'))}"
                 f" · **human wait in session:** {clock(data.get('human_wait_s'))}"
                 + human_wait_note(data.get("human_wait")) + ".")
    lines.append(f"**Time to the first test:** {clock(data.get('time_to_first_test_s'))}"
                 " — the stretch before anything ran.")
    for row in data.get("clock_anomalies") or []:
        lines.append(f"**Clock anomaly ({row.get('stage')}):** started {row.get('started_at')}, "
                     f"finished {row.get('finished_at')} — owner: factory. The stage is left out "
                     "of the durations above rather than counted as taking no time.")
    eva = data.get("estimate_vs_actual") or {}
    lines.append(f"**Size:** forecast `{eva.get('size_initial')}` -> fact `{eva.get('size_final')}`"
                 + (f" — {eva['size_reason']}" if eva.get("size_reason")
                    else " — no re-estimation during the story") + ".")
    lines.append(f"**Estimate vs actual:** size forecast `{eva.get('size_forecast')}`, "
                 f"{eva.get('requirements')} requirements, {eva.get('plan_rows')} plan rows, "
                 f"{eva.get('cases_pinned')} cases pinned, {eva.get('runs')} run(s) of which "
                 f"{eva.get('runs_redundant')} redundant.")
    if isinstance(data.get("size_forecast"), dict):          # a facts file written before CD1-5 has none: no line, not a guess
        lines.append(size_forecast_line(data))
    runs = data.get("test_runs") or {}
    windows = runs.get("windows") or {}
    lines.append(f"**Test-execution jobs:** {runs.get('jobs', 0)}"
                 + (f" ({', '.join(f'{k}: {v}' for k, v in sorted(windows.items()))})" if windows else "")
                 + f" · {runs.get('executions', 0)} test executions, of which "
                   f"{runs.get('duplicate_green_executions', 0)} re-ran an already-green, "
                   "unchanged test"
                 + (f" ({runs['duplicate_share_percent']}%)."
                    if runs.get('duplicate_share_percent') is not None else "."))
    lines += test_run_lines(data.get("test_run_counts"))
    lines += resume_lines(data.get("resumes"))
    lines += knowledge_lines(data.get("knowledge"))
    kept_out = left_out_retro_lines(data) if left_out else []
    if kept_out:
        lines += ["", "**Sources the person left out before the run:**", ""] + ["- " + line for line in kept_out]
    return "\n".join(lines) + "\n"


def knowledge_lines(block) -> list:
    """The retro's question count with its counter-metrics and the table "knowledge: reached / used / not used" (t-2277 FL-8), as
    `report_facts` words them (`question_count_line`, `retro_lines`, one reader). No lines for facts that carry no such block (an older story);
    a block that could not be built is one `unmeasured` line. Words and counts only: nothing here refuses or judges (AR-29)."""
    if not isinstance(block, dict) or not block:
        return []
    if block.get("problem") or not isinstance(block.get("facts"), dict):
        return ["", f"**Knowledge the story had:** unmeasured: {block.get('problem') or 'the counters were not built'}"]
    import report_facts
    facts = block["facts"]
    table = report_facts.retro_lines(facts)
    out = ["", f"**{report_facts.question_count_line(block.get('questions'), facts)}**"]
    if table:
        out += ["", f"**{table[0]}**", ""] + [line if line.startswith("- ") else "- " + line for line in table[1:]]
    return out


def resume_lines(resumes) -> list:
    """The retro's lines for `resume_metrics`: nothing for facts written before the key existed, `unknown` with its
    reason when the journal is not there (FR-41), otherwise the count, the wall time, the stage split and the
    reasons - with the carrier named, so the number can be recounted (FR-26)."""
    if not isinstance(resumes, dict):
        return []
    carrier = resumes.get("carrier") or f"state/{DJ.JOURNAL_NAME}"
    if not resumes.get("known"):
        return ["", f"**Resumes of role sessions:** unknown — {resumes.get('reason') or 'no journal'} ({carrier})."]
    count = resumes.get("count", 0)
    made = resumes.get("assembled_by_code", 0)
    head = (f"**Resumes of role sessions:** {count}"
            + (f", {clock(resumes.get('wall_s'))} of wall time" if count else "")
            + (f" ({_plural(resumes['wall_unmeasured'], 'call has', 'calls have')} no recorded duration)"
               if resumes.get("wall_unmeasured") else ""))
    lines = ["", head + f" — counted from {carrier}."]
    for stage, bucket in (resumes.get("by_stage") or {}).items():
        why = "; ".join(f"{reason} ×{n}" for reason, n in sorted(bucket["reasons"].items(), key=lambda kv: -kv[1]))
        lines.append(f"- {stage}: {bucket['count']} · {clock(bucket['wall_s'])} — {why}")
    if made:
        lines.append(f"- handoffs the driver assembled by code instead of resuming the role: {made} "
                     "(" + ", ".join(f"{s} {n}" for s, n in (resumes.get("assembled_by_stage") or {}).items()) + ").")
    return lines


# --- the code-written retro (`retro_mode: numbers` only) --------------------------------------

def gate_answers(pipeline: dict) -> list:
    """The person's own words at both gates, plus every block they passed, as lines.

    A retro that does not carry them loses the only part of the story nobody can recompute."""
    lines = []
    for gate in ("A", "B"):
        entry = ((pipeline or {}).get("gates") or {}).get(gate) or {}
        if not isinstance(entry, dict) or not entry:
            continue
        words = str(entry.get("words") or entry.get("decision") or "").strip()
        if words:
            lines.append(f"Gate {gate}: {words}")
        risks = entry.get("deliver_with_risks")
        if isinstance(risks, dict) and str(risks.get("reason") or "").strip():
            lines.append(f"Gate {gate}: delivered with known gaps — {risks['reason']}")
    for row in ((pipeline or {}).get("stage_overrides") or []) + \
               ((pipeline or {}).get("gate_waivers") or []):
        if not isinstance(row, dict):
            continue
        decision = str(row.get("decision") or "").strip()
        if decision:
            subject = str(row.get("match") or row.get("requirement") or "a block").strip()
            line = f"{row.get('stage') or 'block'} — {subject}: {decision}"
            if row.get("revoked_at"):
                # History stays (FR-8), but a taken-back word is marked as one - the retro does not read it as standing (GW1-1).
                import waiver
                line = f"{line} {waiver.WITHDRAWN}"
            lines.append(line)
    return lines


def observations(data: dict) -> list:
    """The two or three lines the figures themselves argue for.

    Deterministic on purpose: in `retro_mode: numbers` nobody authors prose — not a role
    (none is dispatched) and not the orchestrator (SKILL.md forbids it writing content)."""
    out = []
    story = data.get("story") or {}
    if data.get("incomplete"):
        out.append(f"The spend is a floor, not a total — {data.get('incomplete_reason') or ''} "
                   "Read every cost line below as at least this much.".strip())
    rework = data.get("rework") or {}
    if rework.get("dispatches"):
        out.append(f"{rework['dispatches']} repair round(s) — "
                   f"{', '.join(rework.get('rounds') or [])} — costing {money(rework.get('cost'))}: "
                   "the work that had to be done twice"
                   + (" (counted per role, dispatch records absent)." if rework.get("basis") == "ordinal" else "."))
    halt = data.get("halts") or {}
    if halt.get("count"):
        out.append(f"{halt['count']} halt(s), {clock(halt.get('waited_s'))} of them waiting: "
                   "time the story stood still, not time it spent working.")
    if isinstance(data.get("human_wait_s"), (int, float)) and data["human_wait_s"] >= 1800:
        out.append(f"{clock(data['human_wait_s'])} of waiting for a person in session"
                   + human_wait_note(data.get("human_wait")) + " — "
                   "every gate answer is paid for twice, in wall clock and in context.")
    # Until 0.7.18 this line fired at a hard-coded 50% and said only that the share was large.
    # A threshold nobody set is not a limit, and a share without its stages is not something
    # anyone can act on (TP2-2553: 47.7% — under the old 50 and therefore silent).
    finding = orchestrator_finding(data)
    if finding:
        out.append(finding[0].upper() + finding[1:])
    for row in data.get("clock_anomalies") or []:
        out.append(f"Stage {row.get('stage')} finished before it started "
                   f"({row.get('started_at')} -> {row.get('finished_at')}) — a finding about the "
                   "factory's own clock; its duration is excluded rather than read as zero.")
    runs = data.get("test_runs") or {}
    if runs.get("duplicate_green_executions"):
        out.append(f"{runs['duplicate_green_executions']} execution(s) re-ran an already-green, "
                   "unchanged test.")
    counts = data.get("test_run_counts") or {}
    if counts.get("known") and counts.get("runs", 0) > counts.get("tests", 0):
        out.append("Tests were run again: " + test_run_sentence(counts))
    journal = data.get("journal") or {}
    if journal.get("known", True) and journal.get("gate_blocks"):
        out.append(f"{journal['gate_blocks']} gate block(s) — the norm is zero.")
    classes = journal.get("gate_block_classes") if isinstance(journal.get("gate_block_classes"), dict) else {}
    if classes.get("signal") and classes.get("worst"):
        name, n = classes["worst"]
        out.append(f"{n} gate blocks of one class (\"{name}\") — a repeat of one refusal is a defect of the factory's "
                   "code or of what the role is told (FR-55, FR-38), not of the role; it is a finding.")
    if not out:
        out.append(f"Nothing in the numbers argues for a change: a price of "
                   f"{price_words(data.get('price') or {})} and "
                   f"{story.get('tokens', 0):,} tokens, no rework, no halts.")
    return out


def estimate_facts(data: dict) -> dict:
    """The `--facts` object `estimate_record.py` takes, built from the same numbers.

    In `retro_mode: numbers` no role runs, so the precedent line that audit A15 requires of
    every completed S9 has to be produced here or not at all."""
    eva = data.get("estimate_vs_actual") or {}
    story = data.get("story") or {}
    rework = data.get("rework") or {}
    halt = data.get("halts") or {}
    drivers = []
    if rework.get("dispatches"):
        drivers.append(f"rework: {rework['dispatches']} round(s)"
                       + (" (counted per role, dispatch records absent)" if rework.get("basis") == "ordinal" else ""))
    if halt.get("count"):
        drivers.append(f"halts: {halt['count']}, waited {clock(halt.get('waited_s'))}")
    # The person's waiting in session (a question's span included) is a driver of the story's wall clock the halts
    # line never saw (LOCAL-1: 7h of waits, "halts 0"); an older capture's figure says it is a floor (E-D1).
    if isinstance(data.get("human_wait_s"), (int, float)) and data["human_wait_s"] >= 1800:
        drivers.append(f"human wait: {clock(data['human_wait_s'])}" + human_wait_note(data.get("human_wait")))
    if data.get("incomplete"):
        drivers.append("cost capture incomplete: the actual is a floor")
    if eva.get("size_reason"):
        drivers.append("size: " + str(eva["size_reason"]))
    counts = data.get("test_run_counts")
    test_runs = ({key: counts.get(key) for key in ("tests", "runs", "launches", "by_cause")}
                 if isinstance(counts, dict) and counts.get("known") else {"known": False})
    return {"forecast": {"size": eva.get("size_forecast"),
                         "size_initial": eva.get("size_initial"),
                         "size_final": eva.get("size_final"),
                         "size_reason": eva.get("size_reason") or "",
                         "requirements": eva.get("requirements"),
                         "plan_rows": eva.get("plan_rows"),
                         # CD1-5: the unit of the size letter (read by `size_forecast`, the dashboard and `metric_signals`
                         # through `record_unit`), the count (`function_count`: a carrier only, nothing reads it from the
                         # ledger yet) and the computed budget (`sizing.nearest_precedents` reads `computed_budget`: in
                         # the function era twice the count, or the defect's one), whether a defect cap shaped the size
                         # and whether the letter was not computed by the unit (`size_forecast` counts both)
                         "size_unit": eva.get("size_unit"),
                         "function_count": eva.get("function_count"),
                         "computed_budget": eva.get("computed_budget"),
                         "defect_capped": bool(eva.get("defect_capped")),
                         "size_mismatch": bool(eva.get("size_mismatch"))},
            # `usd` is the price when the records give one figure and None while they differ; the
            # range is then in `usd_low`/`usd_high` (never a single figure that looks exact).
            "actual": {"usd": story.get("usd"), "usd_low": story.get("usd_low"),
                       "usd_high": story.get("usd_high"), "tokens": story.get("tokens"),
                       "cases_pinned": eva.get("cases_pinned"), "runs": eva.get("runs"),
                       "runs_redundant": eva.get("runs_redundant"),
                       # SC2-37: a carrier for between-run comparison; no code reads it from the ledger yet (queued)
                       "test_runs": test_runs,
                       "time_to_first_test_s": data.get("time_to_first_test_s"),
                       "incomplete": bool(data.get("incomplete"))},
            "drivers": drivers}


def retro_document(data: dict, pipeline: dict, feedback: str = "") -> str:
    """`retro.md` for the mode the person asked for by name: numbers, no prose from a model."""
    task = data.get("task", "?")
    lines = [f"# {task} — retro", "",
             "<!-- Written by scripts/retro_numbers.py --write-retro, the retro the person "
             "asked for by name (`retro_mode: numbers`): no role was dispatched and no model "
             "authored a line of this file. Every figure comes from work/retro-numbers.json. -->",
             "", "## What the numbers say", ""]
    lines += ["- " + line for line in observations(data)]
    lines += ["", "## The numbers", "", render(data, left_out=False).rstrip(), "",
              "## Decisions this story recorded", ""]
    answers = gate_answers(pipeline)
    lines += ["- " + line for line in answers] if answers else \
        ["No gate words are recorded in `pipeline.json`."]
    # What the person said BEFORE the run, beside what they said at the gates.
    lines += ["- " + line for line in left_out_retro_lines(data)]
    lines += ["", "## The human's answer", ""]
    lines.append("> " + (feedback.strip() or "declined to answer"))
    return "\n".join(lines) + "\n"


def write_retro(task: str, root: Path | None = None, task_root: Path | None = None,
                feedback: str = "") -> dict:
    """Write `retro.md`, the rendered numbers and the estimate facts, and say where.

    `retro.md` is written BEFORE the facts file is used, because `estimate_record.py` binds
    its record to the retro's bytes: a record written first is stale the moment the file
    changes (audit A15 reports exactly that)."""
    if task_root is None:
        troot = story_root(task, "retro_numbers")        # the story EXISTS or a refusal (a `ValueError`): CX1-18
    else:
        troot = Path(task_root)
        if not troot.is_dir():                            # written UNDER a story folder; S0 makes it, this step never does
            from hooklib import StoryRootError
            raise StoryRootError(f"the retro is written under the story folder {troot}, which does not exist, so "
                                 "nothing was written (S0 creates a story folder; this step never does). Pass the "
                                 "folder of a story that exists")
    data = numbers(task, root, troot)
    pipeline = read_json(troot / "pipeline.json", {}) or {}
    feedback = feedback or str(pipeline.get("retro_feedback") or "")
    work = troot / "work"
    work.mkdir(exist_ok=True)
    written = {"retro": troot / "retro.md", "rendered": work / "retro-numbers.md",
               "facts": work / "retro-numbers.json", "estimate": work / "estimate-facts.json"}
    written["rendered"].write_text(render(data), encoding="utf-8")
    written["facts"].write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    # `retro.md` IS committed to the project and carries the story's price. That is exempt from
    # P18's "no money in a file of the repository" by the owner's own word (30.09, F11: "for a
    # retro that is normal"; the rule is about the test report, where prices would age).
    written["retro"].write_text(retro_document(data, pipeline, feedback), encoding="utf-8")
    written["estimate"].write_text(
        json.dumps(estimate_facts(data), indent=2, ensure_ascii=False), encoding="utf-8")
    return written


def selftest() -> int:
    import tempfile
    failures: list = []

    def case(name, got, expected):
        if got != expected:
            failures.append(f"{name}: expected {expected!r}, got {got!r}")

    case("a stage is read out of the purpose line",
         stage_of({"purpose": "qa-case-critic S4 TP1-1"}, {}), "S4")
    case("and out of the pipeline's agent_id when the purpose has none",
         stage_of({"file": "agent-abc.jsonl"},
                  {"stages": {"S1": {"agent_id": "abc"}}}), "S1")
    case("an unknown dispatch is named unattributed, not dropped",
         stage_of({"purpose": "something"}, {}), "unattributed")
    case("a span over two timestamps", span_seconds("2026-09-20T19:00:00+00:00",
                                                    "2026-09-20T19:30:00+00:00"), 1800)
    case("a span with a missing end is unknown", span_seconds("2026-09-20T19:00:00+00:00", None), None)
    # The cache-read rate is an exact id (or alias) of the catalogue, never a substring: the
    # catalogue's `claude-opus-5` is a substring of `claude-opus-5-5`, which costs $0.2 and not $0.5.
    case("the cache-read rate of an exact catalogue id", cache_read_rate("claude-opus-5-5"), 0.2)
    case("and of an id the first entry's name is a substring of", cache_read_rate("claude-opus-5"), 0.5)
    case("an alias of a catalogue entry matches", cache_read_rate("claude-sonnet-4-5"), 0.3)
    case("a prefix of an id is not a match: no rate (unknown), not the first entry that contains it",
         cache_read_rate("claude-opus"), None)
    case("no model: no rate, never another model's", cache_read_rate(""), None)

    def usage_of(dollars):
        """The usage of a request that costs `dollars` at the catalogue's claude-sonnet-5-5 rate
        ($10 per million output tokens)."""
        return {"requests": 1, "input": 0, "output": round(dollars * 100000), "cache_read": 0,
                "cache_write_5m": 0, "cache_write_1h": 0}

    def request_of(sid, rid, stream, dollars, activity="act-1"):
        # The pinned valuation is a bogus 999: a reader that takes the file's own money shows at once.
        return {"request_key": f"anthropic:{sid}:{rid}:{stream}", "provider": "anthropic",
                "session_id": sid, "request_id": rid, "stream": stream, "task": "QA-1",
                "model_id": "claude-sonnet-5-5", "timestamp": "2026-09-20T19:10:00+00:00",
                "activity_id": activity, "usage": usage_of(dollars),
                "valuation": {"pricing_coverage": "complete", "subtotal_usd": "999",
                              "missing_rate_categories": [], "tariff_confirmation": "unconfirmed",
                              "rate_provenance": {"kind": "legacy_project_override"}}}

    def session_file(sid, dollars):
        """A driver session's cost file: one request that costs `dollars`, no factory activity."""
        return {"session_id": sid, "by_task": {"(no task)": {"tokens": 7, "requests": 1}},
                "requests": [request_of(sid, "r1", "orchestrator", dollars, activity="unclassified")],
                "agents": []}

    with tempfile.TemporaryDirectory(prefix="qa-retro-numbers-") as td:
        base = Path(td) / "qa-factory"
        troot = base / "artifacts" / "QA-1"
        (base / "state" / "cost").mkdir(parents=True)
        (troot / "work").mkdir(parents=True)
        (troot / "state").mkdir(parents=True)
        (base / "config.json").write_text("{}", encoding="utf-8")
        (troot / "pipeline.json").write_text(json.dumps({
            "ticket": "QA-1", "size": "M",
            "stages": {"S0": {"status": "done", "started": "2026-09-20T19:00:00+00:00"},
                       "S1": {"status": "done", "role": "qa-scout",
                              "started": "2026-09-20T19:05:00+00:00",
                              "finished": "2026-09-20T19:35:00+00:00"}},
            "first_test_run_at": "2026-09-20T21:00:00+00:00",
            "halts": [{"stage": "S1", "at": "2026-09-20T19:10:00+00:00",
                       "resolved": True, "resolved_at": "2026-09-20T19:20:00+00:00"}],
        }), encoding="utf-8")
        (troot / "work" / "test-plan.json").write_text(json.dumps([{}, {}, {}]), encoding="utf-8")
        RP.record_new(base.parent, "journal.jsonl").parent.mkdir(parents=True, exist_ok=True)
        RP.record_new(base.parent, "journal.jsonl").write_text("\n".join(json.dumps(r) for r in [
            {"event": "rejected", "task": "QA-1", "reason_family": "grounding"},
            {"event": "gate_block", "task": "QA-1"},
            {"event": "compact", "task": "QA-1"},
        ]), encoding="utf-8")
        priced = {
            # An orchestrator-mode session: its requests fall inside a story activity segment of
            # QA-1 (the EVIDENCE that binds it to the story, FR-24: no journal names it). by_task
            # is the FOLDED total (orchestrator + both agent dispatches, matching
            # cost_capture.py's real task_models aggregation) — 1800 tokens; the requests cost
            # $6.0 (orchestrator) + $2.0 + $1.0 (the two agents) at the catalogue's rate = $9.0.
            "session_id": "s-1", "by_task": {"QA-1": {"tokens": 1800, "requests": 41,
                                                      "cost": 999.0, "machine_s": 3600}},
            "by_activity": {"act-1": {"type": "story", "task": "QA-1"}},
            "orchestrator": {"tools": {"Bash": 10}},
            # requests[] is the only place stream+task are recorded together, so it is what
            # orchestrator_totals() reads for the orchestrator's OWN (non-folded) share.
            "requests": [request_of("s-1", "r1", "orchestrator", 6.0),
                         request_of("s-1", "r2", "agent-a.jsonl", 2.0),
                         request_of("s-1", "r3", "agent-b.jsonl", 1.0)],
            "human_wait_s": 600,
            "agents": [
                {"agent": "qa-factory:qa-scout", "purpose": "qa-scout S1 QA-1", "task": "QA-1",
                 "tokens": 500, "cost": 2.0, "started": "2026-09-20T19:06:00+00:00",
                 "by_model": {"m": {"requests": 20}}, "file": "agent-a.jsonl"},
                {"agent": "qa-factory:qa-scout", "purpose": "qa-scout S1 QA-1", "task": "QA-1",
                 "tokens": 300, "cost": 1.0, "started": "2026-09-20T19:20:00+00:00",
                 "by_model": {"m": {"requests": 10}}, "file": "agent-b.jsonl"},
            ],
        }
        (base / "state" / "cost" / "s-1.json").write_text(json.dumps(priced), encoding="utf-8")
        data = numbers("QA-1", base, troot)
        case("the story's price is its sessions' requests at the catalogue's rates, not the file's own "
             "pinned money", data["story"]["usd"], 9.0)
        case("one record, so it says so", data["price"]["status"], "not_cross_checked")
        case("and the tokens are by_task's folded figure", data["story"]["tokens"], 1800)
        case("nothing is incomplete when every role has usage", data["incomplete"], False)
        case("the orchestrator's share is its own cost over the story's",
             data["orchestrator_share_percent"], 66.7)
        case("the second dispatch of one role in one stage is a repair round",
             data["rework"]["dispatches"], 1)
        case("and its cost is named", data["rework"]["cost"], 1.0)
        case("with no dispatch records the ordinal rule is used and says so",
             (data["rework"]["basis"], "counted per role, dispatch records absent" in render(data)), ("ordinal", True))
        case("a cost file with no human_waits keeps its human_wait_s and is named as not measured (E-D1)",
             (data["human_wait_s"], data["human_wait"]["question_waits"]), (600, "not_measured"))
        case("and no machine time is derived from it", data["stage_machine_s"]["S1"], None)
        case("and the line says question waits were not measured",
             "question waits not measured by this capture" in render(data), True)
        case("rejects are tallied by family",
             data["journal"]["reject_families"], {"grounding": 1})
        case("gate blocks are counted", data["journal"]["gate_blocks"], 1)
        case("halts carry the wait", data["halts"]["waited_s"], 600)
        case("time to the first test spans from S0", data["time_to_first_test_s"], 7200)
        case("the three most expensive dispatches are ranked",
             [t["cost"] for t in data["top_dispatches"]], [2.0, 1.0])
        text = render(data)
        case("the table names the role", "qa-scout" in text, True)
        case("and prints the share", "66.7%" in text, True)
        case("and the price, marked as one record (the chat is the only record: single source)",
             "**Story price: $9.00 — single source (chat): nothing to cross-check against" in text, True)
        case("the retro names no record the authoritative one", "authoritative" in text, False)

        # A driver run has the operator's own session open beside it, on the same ticket: they
        # read the artifacts, measure, fix the factory. Live TP1-13797 run 5: that session
        # carried its own by_task entry and the retro's headline read "story spend $1,911.43"
        # over 30 sessions while the driver's journal said $125.77 — and by_role named the
        # operator's agent types with not one qa-* role among them. No evidence binds it to the
        # story (no journal names it, it holds no story activity segment), so it is not the
        # story's, with or without a journal (FR-24, B-223).
        operator = {"session_id": "s-operator",
                    "by_task": {"QA-1": {"tokens": 9000000, "requests": 700, "cost": 1800.0}},
                    "agents": [{"agent": "general-purpose", "purpose": "measuring", "task": "QA-1",
                                "tokens": 9000000, "cost": 1800.0,
                                "started": "2026-09-20T19:07:00+00:00",
                                "by_model": {"m": {"requests": 700}}, "file": "agent-op.jsonl"}]}
        (base / "state" / "cost" / "s-operator.json").write_text(json.dumps(operator), encoding="utf-8")
        data = numbers("QA-1", base, troot)
        case("a session that only carries the ticket in a by_task tag is not the story's",
             (data["story"]["usd"], data["story"]["sessions"]), (9.0, 1))
        (base / "state" / "cost" / "s-1.json").unlink()
        # A running total per session: a role session launched at $2.0 and resumed to $3.0, and a
        # conductor session of $0.5. Each session has a cost file at the same price (A = B).
        (base / "state" / "cost" / "d-1.json").write_text(json.dumps(session_file("d-1", 3.0)), encoding="utf-8")
        (base / "state" / "cost" / "c-1.json").write_text(json.dumps(session_file("c-1", 0.5)), encoding="utf-8")
        (troot / "state" / "driver-runs.jsonl").write_text("\n".join(json.dumps(r) for r in [
            {"kind": "role", "role": "qa-scout", "dispatch": "S1-qa-scout-1", "stage": "S1",
             "session_id": "d-1", "num_turns": 30, "total_cost_usd": 2.0, "resumed": False,
             "ts": "2026-09-20T19:06:00+00:00"},
            {"kind": "role", "role": "qa-scout", "dispatch": "S1-qa-scout-1", "stage": "S1",
             "session_id": "d-1", "num_turns": 10, "total_cost_usd": 3.0, "resumed": True,
             "ts": "2026-09-20T19:20:00+00:00"},
            {"kind": "conductor", "role": "", "dispatch": "", "stage": "S1",
             "session_id": "c-1", "num_turns": 3, "total_cost_usd": 0.5, "resumed": False,
             "ts": "2026-09-20T19:25:00+00:00"},
        ]), encoding="utf-8")
        data = numbers("QA-1", base, troot)
        case("with a journal, the sessions are the ones it names, and the operator's is not among them",
             (data["story"]["sessions"], data["sessions"]), (2, ["c-1", "d-1"]))
        case("the two records agree, and the price is one figure", (data["price"]["status"], data["story"]["usd"]),
             ("agrees", 3.5))
        case("the roles named are the factory's, from the journal",
             sorted(data["by_role"]), ["qa-scout"])
        # A row costs its INCREMENT: $2.0 for the launch, then $3.0 - $2.0 = $1.0 for the resume,
        # $3.0 in all - not the raw totals $2.0 + $3.0 = $5.0 (the running total counts twice).
        case("with the cost the CLI itself reported, by increments: 2.0 + (3.0 - 2.0)",
             data["by_role"]["qa-scout"]["cost"], 3.0)
        case("and the operator's agent type is not among them",
             "general-purpose" in data["by_role"], False)
        (base / "state" / "cost" / "s-operator.json").unlink()
        # The share of a driver run is the conductor's over the driver's record, not the branches
        # that read a stream this run does not have (cmp1: $3.07 of $17.42, 17.6 %).
        (troot / "state" / "driver-runs.jsonl").write_text("\n".join(json.dumps(r) for r in [
            {"kind": "conductor", "session_id": "c-1", "stage": "S1", "total_cost_usd": 1.0},
            {"kind": "role", "role": "qa-scout", "session_id": "r-1", "stage": "S1",
             "total_cost_usd": 3.0}]), encoding="utf-8")
        data = numbers("QA-1", base, troot)
        case("a driver run's share is the conductor's record over the driver's",
             data["orchestrator_share_percent"], 25.0)
        case("its stage parts come from the journal", data["orchestrator_by_stage"], {"S1": 1.0})
        case("and the retro names the record the share stands on",
             "the driver's own record" in render(data), True)
        # The owner's decision on the control layer (30.09): the conductor's money is the
        # management figure, and the money of a resumed role is the ROLE's, priced by increments
        # (rows 1.0 then 1.5 after a return: $0.50 handed back, not $2.50).
        (troot / "state" / "driver-runs.jsonl").write_text("\n".join(json.dumps(r) for r in [
            {"kind": "conductor", "session_id": "c-1", "stage": "S1", "total_cost_usd": 1.0},
            {"kind": "role", "role": "qa-scout", "session_id": "r-1", "stage": "S1",
             "total_cost_usd": 1.0},
            {"kind": "role", "role": "qa-scout", "session_id": "r-1", "stage": "S1",
             "total_cost_usd": 1.5, "resumed": True}]), encoding="utf-8")
        data = numbers("QA-1", base, troot)
        case("the share is the conductor's own money over the driver's record",
             (data["orchestrator_share_basis"]["conductor_usd"], data["orchestrator_share_percent"]),
             (1.0, 40.0))
        case("resumed role money is its own figure, by increments", data["handed_back_to_roles"],
             {"usd": 0.5, "sessions": 1, "unknown": 0})
        case("and there is no control-layer total at all", "control_layer" in data, False)
        case("the retro says it in plain words",
             "work the conductor handed back to roles: $0.50 over 1 resumed role session" in render(data),
             True)
        # ONE SOURCE PER RATIO: a session whose totals fall has no driver record, and no cost file
        # stands in for it.
        (troot / "state" / "driver-runs.jsonl").write_text("\n".join(json.dumps(r) for r in [
            {"kind": "conductor", "session_id": "c-1", "stage": "S1", "total_cost_usd": 1.0},
            {"kind": "role", "role": "qa-scout", "session_id": "r-1", "stage": "S1",
             "total_cost_usd": 2.0},
            {"kind": "role", "role": "qa-scout", "session_id": "r-1", "stage": "S1",
             "total_cost_usd": 1.0, "resumed": True}]), encoding="utf-8")
        data = numbers("QA-1", base, troot)
        case("a session with no driver record makes the share unknown, not a mix of two tables",
             (data["orchestrator_share_percent"], data["orchestrator_share_basis"]["unpriced"]), (None, 1))
        (troot / "state" / "driver-runs.jsonl").unlink()

        # The capture defect of TP1-15045: six roles, every one at tokens 0.
        blind = dict(priced, agents=[dict(a, tokens=0, cost=None, tools={"Bash": 3}) for a in priced["agents"]])
        (base / "state" / "cost" / "s-1.json").write_text(json.dumps(blind), encoding="utf-8")
        data = numbers("QA-1", base, troot)
        case("a role with no recorded usage marks the story incomplete",
             data["incomplete"], True)
        case("and the reason names the role's cost as not estimated, in words",
             "cost of qa-scout not estimated: its usage was not recorded." in data["incomplete_reason"], True)
        case("and no orchestrator share is published",
             data["orchestrator_share_percent"], None)
        text = render(data)
        case("the table says so in words", "INCOMPLETE" in text, True)
        case("and never claims a 100% orchestrator share", "100.0%" in text, False)

        # The same defect, declared by the capture layer rather than inferred from a zero.
        declared = dict(blind, incomplete_agents=["qa-factory:qa-scout"])
        (base / "state" / "cost" / "s-1.json").write_text(json.dumps(declared), encoding="utf-8")
        case("a declared incomplete_agents entry with no usage anywhere is honoured too",
             numbers("QA-1", base, troot)["incomplete"], True)
        # Resumed agent: the declaring file holds a zero-token entry of the role beside the file with tokens.
        resumed = dict(priced, incomplete_agents=["qa-factory:qa-scout"],
                       agents=priced["agents"] + [{"agent": "qa-factory:qa-scout", "task": "QA-1", "tokens": 0,
                                                   "by_model": {}, "file": "agent-z.jsonl"}])
        (base / "state" / "cost" / "s-1.json").write_text(json.dumps(resumed), encoding="utf-8")
        case("a declared role with a zero-token sibling whose usage a cost record carries is not missing (RN1-25 item 5)",
             numbers("QA-1", base, troot)["story"]["roles_missing"], [])
        # No zero-token entry: a dispatch that left no transcript (incomplete_roles kind 2) stays missing (F1 t-1753).
        no_file = dict(priced, incomplete_agents=["qa-factory:qa-scout"])
        (base / "state" / "cost" / "s-1.json").write_text(json.dumps(no_file), encoding="utf-8")
        one_gap = numbers("QA-1", base, troot)
        case("a declared role with NO zero-token entry stays missing though a priced file carries it (AR-28)",
             (one_gap["story"]["roles_missing"], one_gap["incomplete"]), (["qa-scout"], True))

        # `retro_mode: numbers` — the file is written by this script, never by a model.
        (base / "state" / "cost" / "s-1.json").write_text(json.dumps(priced), encoding="utf-8")
        (troot / "pipeline.json").write_text(json.dumps(
            {"ticket": "QA-1", "retro_mode": "numbers",
             "gates": {"B": {"decision": "approved", "words": "ship it, file bug 1"}},
             "stage_overrides": [{"stage": "S5", "match": "story budget",
                                  "decision": "keep going"}]}), encoding="utf-8")
        written = write_retro("QA-1", base, troot, feedback="the gates were slow")
        text = written["retro"].read_text(encoding="utf-8")
        case("the retro is written where audit A15 reads it", written["retro"].name, "retro.md")
        case("it carries the computed table", "Retro numbers" in text, True)
        case("the person's gate words survive into it", "ship it, file bug 1" in text, True)
        case("and the block they passed", "keep going" in text, True)
        case("their closing answer is quoted verbatim", "> the gates were slow" in text, True)
        facts = json.loads(written["estimate"].read_text(encoding="utf-8"))
        case("the estimate facts carry a forecast", isinstance(facts["forecast"], dict), True)
        case("and an actual", isinstance(facts["actual"], dict), True)
        case("a rework round is named as a driver",
             any("rework" in d for d in facts["drivers"]), True)
        case("no answer is recorded as declined, never invented",
             "> declined to answer" in
             write_retro("QA-1", base, troot)["retro"].read_text(encoding="utf-8"), True)

    if failures:
        print("RETRO_NUMBERS SELFTEST: VIOLATIONS")
        for f in failures:
            print("  - " + f)
        return 1
    print("RETRO_NUMBERS SELFTEST: no violations (attribution, rework, incompleteness, render)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--task", default="")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--output", default="", help="write the rendered table to this path")
    ap.add_argument("--json-output", default="", help="write the facts as JSON to this path")
    ap.add_argument("--write-retro", action="store_true",
                    help="retro_mode numbers: write retro.md, the numbers and the estimate facts")
    ap.add_argument("--feedback", default="",
                    help="--write-retro: the person's closing answer, verbatim, or empty")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if not args.task:
        print("retro_numbers.py: --task is required", file=sys.stderr)
        return 2
    require_project("retro_numbers")
    if args.write_retro:
        try:
            written = write_retro(args.task, feedback=args.feedback)
        except ValueError as exc:                          # the story is not there: the call's fault (CX1-18)
            print(f"retro_numbers: {exc}", file=sys.stderr)
            return 2
        except OSError as exc:
            print(f"retro_numbers: could not write the retro: {exc}", file=sys.stderr)
            return 1
        for label in ("retro", "rendered", "facts", "estimate"):
            print(f"{label}: {written[label]}")
        print("next: estimate_record.py --task " + args.task +
              " --facts " + str(written["estimate"]) + " (the record binds retro.md's bytes, "
              "so nothing may edit retro.md afterwards)")
        return 0
    data = numbers(args.task)
    text = render(data)
    print(json.dumps(data, indent=2, ensure_ascii=False) if args.json else text)
    for path, payload in ((args.output, text),
                          (args.json_output, json.dumps(data, indent=2, ensure_ascii=False))):
        if not path:
            continue
        try:
            out = Path(path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(payload, encoding="utf-8")
        except Exception as exc:
            print(f"retro_numbers: could not write {path}: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
