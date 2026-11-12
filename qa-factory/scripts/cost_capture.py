"""Incremental session cost capture from provider transcripts (lifecycle hooks, fail-silent).

The idea comes from the AICoE observability bundle, but without Prometheus: Claude Code
writes the usage of every API call into the session transcript and into the sibling
subagent files — everything is taken from there, including the ORCHESTRATOR's spend
(the blind spot of metrics.jsonl).

Lifecycle hooks tail complete JSONL records and idempotently rewrite
qa-factory/state/cost/<session_id>.json:

  tasks           — the session's tasks (from workflow markers, see by_task)
  by_task         — cost SPLIT BY TASK via timeline segmentation: boundary markers are
                    task artifact writes (Write/Edit into qa-factory/artifacts/<task>/)
                    and journal events `log_append --task <id>`; every API call is
                    attributed to the task of the last marker before it (the preamble
                    before the first marker stays "(no task)"; setup activity is separately
                    recorded and never retroactively assigned to the story). The active_s field is an estimate of the
                    task's pipeline time ("capped wall-clock"): the sum of gaps between
                    adjacent calls of its segments, each gap capped at human_wait_cap_s;
                    NOT machine time (short human waits are inside). The factory workflow makes task boundaries
                    visible — a session with several tasks is split by them instead of
                    showing up as one line
  orchestrator    — the transcript's main chain: usage by model + cost
  agents[]        — EVERY subagent call separately (file subagents/agent-*.jsonl;
                    name and purpose come from the sibling .meta.json)
  by_model        — the whole session by model (in/out/cache-read/cache-write 5m and 1h)
  reconciliation  — the "task sum matches the agent sum" invariant: total ==
                    orchestrator + sum(agents) (the same data, but both sums are
                    computed and written out explicitly — the reconciliation is visible,
                    not taken on faith)
  human_wait      — time waiting on the human: between turns (each gap capped at human_wait_cap_s) plus the
                    time a question put to the person stood open (measured, uncapped; the cost file says
                    `question_waits` measured|unmeasured, lists `human_waits[]` and counts `open_questions`)
  tools           — tool calls by name
  usage_reader    — written only when non-zero: {"bad_iterations", "split_missing"}, the counts of the
                    `usage.iterations` reader (a request served by a model fallback is priced by the
                    provider's per-message records, one row per model; see "one request, several
                    provider records" above `scan_file`)

Cost: one price list — the bundled exact-id catalogue (references/model-rates.json) by
default. A project rate exists only as config.cost.rate_overrides for a NAMED model (exact id
or alias), and it is asked first. Legacy config.cost.model_prices ($/1M, key = substring of
the model name, fields input / output / cache_read / cache_write_5m / cache_write_1h, the
legacy cache_write field accepted as both 5m and 1h) prices ONLY a model that neither
rate_overrides nor the catalogue knows, and its provenance says so (resolve_rate). No price
for a model -> cost: null, tokens are still counted honestly. `revalue_document` re-prices a
cost file in memory from its stored usage with that rule, so a file captured under the old
precedence reads at the catalogue rate without being rewritten. Formulas are shown on the
dashboard (factory_dashboard.py, the "Cost" tab).
"""
import contextlib
import copy
import hashlib
import json
import math
import os
import re
import sys
import time
import uuid
from decimal import Decimal
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hooklib import state_dir, read_event, load_config, load_ref_json, read_json, ref, project_root, role_name
import runtime_paths as RP
from event_store import atomic_json, content_hash, EventStore, StateConflict

# Directories under qa-factory/artifacts/ that are not tasks. Nothing under qa-factory/state/ is a task:
# that tree holds the factory's own files (`task_from_path`), so this set does not grow with it.
NOT_A_TASK = {"cost", "surface", "audit", "releases", "requirements"}

# --- which project a captured session belongs to ------------------------------------------
# A cost file lands in this project's state/cost because the hook ran here, not because the
# session belongs here: on TP1-15045 four sessions of the factory's OWN development,
# opened one and two directories above the project, were summed into the project's total and
# made it read ten times the real story spend. The transcript path carries the answer — the
# host names its transcript directory after the directory the session was opened in.
# The same eight foreign sessions cost time as well as money (I-93): by 0.7.12 the project
# held 10 cost files, 8 of them opened in `D:/ws4` and its children — 273 MB of
# transcripts, one of them a live session still growing — and every dashboard build
# recomputed the stale ones from those transcripts, so a render took minutes and the only
# way out was QA_FACTORY_SKIP_DASHBOARD_REFRESH=1. Since 0.7.15 ownership decides twice:
# the hook does not write a foreign session's cost file here at all, and the recapture pass
# never reads a foreign transcript (see `_recapture_skip`).


def project_slug(path) -> str:
    """The host's own spelling of a directory: every non-alphanumeric character becomes '-'
    (`D:/ws/x` -> `D--ws-x`), which is how Claude Code and Codex name the
    per-project transcript folder."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path or "")).strip("-")


def session_project_slug(session: dict) -> str:
    """The project directory of one captured session, as a slug — "" when the host stores
    its transcripts without one (Codex writes them under a dated folder, not a project)."""
    transcript = str((session or {}).get("transcript") or "").replace("\\", "/")
    parts = [p for p in transcript.split("/") if p]
    for anchor in ("projects", "chats"):
        if anchor in parts:
            index = parts.index(anchor)
            if index + 1 < len(parts) - 1:   # a slug folder, not the transcript file itself
                return parts[index + 1]
    return ""


def session_belongs_to(session: dict, project_slug_value: str) -> str:
    """"this" (the project or a folder inside it), "parent" (a directory the project sits in,
    or an unrelated one), or "unknown" (no project folder in the path — the caller falls back
    to whether the session recorded any factory activity at all)."""
    slug = session_project_slug(session)
    if not slug or not project_slug_value:
        return "unknown"
    if slug == project_slug_value or slug.startswith(project_slug_value + "-"):
        return "this"
    return "parent"


def parse_ts(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def price_for(model: str, prices: dict):
    best = None
    for key, p in prices.items():
        if key and key in model and (best is None or len(key) > len(best[0])):
            best = (key, p)
    return best[1] if best else None


def load_catalogue():
    try:
        return json.loads(ref("model-rates.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "catalogue_revision": "unavailable", "entries": []}


def model_provider(model):
    return "anthropic" if str(model).startswith("claude-") else "openai" if str(model).startswith(("gpt-", "o1", "o3", "o4")) else "unknown"


def resolve_rate(model, cfg, catalogue=None, provider=None, at=None):
    """One price list, asked in this order (B-225; references/templates/config.json says the same):

      1. `rate_overrides` of the project, exact id or alias — a named model's own rate;
      2. the bundled catalogue, exact id or alias, valid on the request's date and provider;
      3. legacy `model_prices`, longest substring match — ONLY for a model that neither 1 nor
         2 knows. A model the catalogue knows by id or alias is never priced by a family key,
         not even when no catalogue entry is valid on the request's date or provider: that
         request stays unpriced, which is the allowed error (an alarm), not a wrong number.
         This step used to come first, and the cmp1 project's family table (1.5 times the
         list price in every category) priced every model the catalogue knows: $24.97 against
         the CLI's own $17.42;
      4. unpriced — a model nobody knows gets no rate; the catalogue matches by exact id or
         alias only, never by a substring of either side.

    `at` decides the catalogue window. With no timestamp the window is not checked: the first
    entry that names the id wins (the behaviour before this precedence change, kept)."""
    cfg = cfg if isinstance(cfg, dict) else {}
    catalogue = catalogue or load_catalogue()
    revision = catalogue.get("catalogue_revision")
    if not isinstance(model, str) or not model:
        return None, {"kind": "unpriced", "revision": revision, "reason": "the request names no model id"}
    for entry in (cfg.get("rate_overrides") or []):
        if isinstance(entry, dict) and model in [entry.get("model_id"), *(entry.get("aliases") or [])]:
            return entry.get("rates") or {}, {"kind": "project_override",
                "revision": entry.get("revision") or content_hash(entry), "model_id": entry.get("model_id")}
    day = at.date().isoformat() if isinstance(at, datetime) else str(at or "")[:10]
    catalogue_knows = False
    for entry in catalogue.get("entries") or []:
        if not isinstance(entry, dict) or model not in [entry.get("model_id"), *(entry.get("aliases") or [])]:
            continue
        catalogue_knows = True
        valid = (not day or (not entry.get("valid_from") or day >= entry["valid_from"]) and
                 (not entry.get("valid_to") or day <= entry["valid_to"]))
        provider_ok = not provider or provider == "unknown" or entry.get("provider") == provider
        if provider_ok and valid:
            return entry.get("rates") or {}, {"kind": "bundled_exact",
                "revision": revision, "model_id": entry.get("model_id"),
                "source_url": entry.get("source_url"), "verified_at": entry.get("verified_at"),
                "pricing_basis": entry.get("pricing_basis"), "long_context": entry.get("long_context")}
    if catalogue_knows:
        return None, {"kind": "unpriced", "revision": revision,
                      "reason": "the catalogue knows this model id but no entry is valid for the "
                                "request's date and provider; a family rate is never used for it"}
    prices = cfg.get("model_prices")
    prices = prices if isinstance(prices, dict) else {}
    legacy = price_for(model, prices)
    if isinstance(legacy, dict):
        legacy = dict(legacy)
        if "cache_write" in legacy:
            legacy.setdefault("cache_write_5m", legacy["cache_write"])
            legacy.setdefault("cache_write_1h", legacy["cache_write"])
        return legacy, {"kind": "legacy_project_override",
                        "revision": content_hash(prices), "resolution": "longest_match",
                        "reason": "model unknown to rate_overrides and to the catalogue; "
                                  "priced at the project's legacy family rate"}
    return None, {"kind": "unpriced", "revision": revision,
                  "reason": "model unknown to rate_overrides, the catalogue and the legacy model_prices"}


def pricing_migration(models, cfg, catalogue=None):
    """Describe legacy-prefix impact without rewriting negotiated project rates."""
    catalogue = catalogue or load_catalogue()
    legacy = cfg.get("model_prices") or {}
    rows = []
    for model in sorted(set(models)):
        old = price_for(model, legacy)
        exact, provenance = resolve_rate(model, {"rate_overrides":cfg.get("rate_overrides") or []}, catalogue)
        if old is not None:
            rows.append({"model_id":model,"legacy_revision":content_hash(legacy),
                         "legacy_rates":old,"exact_rates":exact,"exact_provenance":provenance,
                         "action":"review_project_override" if exact != old else "no_rate_change",
                         "confirmation":"required","applied":False})
    return {"migration_id":content_hash(rows),"rows":rows,
            "note":"Historical request valuations remain pinned; revaluation requires a separate receipt."}


def revalue_request(record, cfg, catalogue, reason):
    """Create an explicit comparison receipt; do not mutate the original valuation."""
    new_value = value_usage(record.get("usage") or zero(), record.get("model_id", ""), cfg,
                            catalogue, record.get("provider"), parse_ts(record.get("timestamp")))
    return {"request_key":record.get("request_key"),"reason":reason,
            "old_valuation":record.get("valuation"),"new_valuation":new_value,
            "old_rate_revision":(record.get("valuation") or {}).get("rate_provenance"),
            "new_rate_revision":new_value.get("rate_provenance")}


def value_usage(agg, model, cfg, catalogue=None, provider=None, at=None):
    rates, provenance = resolve_rate(model, cfg, catalogue, provider, at)
    categories = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")
    context_policy = provenance.get('long_context')
    if context_policy:
        if context_policy.get('scope') == 'session' and agg.get('session_input_tokens') is None:
            rates=None
            provenance=dict(provenance, reason='Session-wide context tariff needs observed session input size; reference rates are available')
        elif agg.get('requests',1)>1:
            rates=None
            provenance=dict(provenance, reason='Context tariff requires individual request sizes')
        elif (agg.get('session_input_tokens') if context_policy.get('scope') == 'session' else sum(agg.get(k,0) or 0 for k in ('input','cache_read','cache_write_5m','cache_write_1h'))) > context_policy['threshold_input_tokens']:
            rates=context_policy['rates']
            provenance=dict(provenance, context_band='long')
        else:
            provenance=dict(provenance, context_band='short')
    subtotal, missing = Decimal("0"), []
    if rates is None:
        missing = [key for key in categories if agg.get(key, 0)]
    else:
        for key in categories:
            count = int(agg.get(key, 0) or 0)
            if not count:
                continue
            if key not in rates:
                missing.append(key)
                continue
            subtotal += Decimal(count) * Decimal(str(rates[key])) / Decimal("1000000")
    nonzero = any(agg.get(key, 0) for key in categories)
    coverage = "none" if rates is None and nonzero else ("partial" if missing else "complete")
    confirmation = cfg.get("rate_confirmation", "unconfirmed")
    if isinstance(confirmation, dict):
        confirmation = confirmation.get("status", "unconfirmed")
    return {"subtotal_usd": str(subtotal), "pricing_coverage": coverage,
            "missing_rate_categories": missing, "rate_provenance": provenance,
            "tariff_confirmation": confirmation}


def zero():
    return {"requests": 0, "input": 0, "output": 0, "cache_read": 0, "cache_write_5m": 0, "cache_write_1h": 0}


def add_usage(agg: dict, u: dict) -> None:
    agg["requests"] += 1
    agg["input"] += u.get("input_tokens") or 0
    agg["output"] += u.get("output_tokens") or 0
    agg["cache_read"] += u.get("cache_read_input_tokens") or 0
    cc = u.get("cache_creation") or {}
    w5 = cc.get("ephemeral_5m_input_tokens")
    w1 = cc.get("ephemeral_1h_input_tokens")
    if w5 is None and w1 is None:
        w5 = u.get("cache_creation_input_tokens") or 0  # no breakdown -> count as 5m
        w1 = 0
    agg["cache_write_5m"] += w5 or 0
    agg["cache_write_1h"] += w1 or 0


def cost_of(agg: dict, model: str, prices: dict):
    """Legacy public helper: longest-match configured rates, now honest about partial cost."""
    valuation = value_usage(agg, model, {"model_prices": prices},
                            {"catalogue_revision": "legacy-only", "entries": []})
    return float(valuation["subtotal_usd"]) if valuation["pricing_coverage"] == "complete" else None


def apply_valuation(agg, model, cfg, catalogue):
    valuation = value_usage(agg, model, cfg, catalogue)
    agg["cost"] = float(valuation["subtotal_usd"]) if valuation["pricing_coverage"] != "none" else None
    agg["valuation"] = valuation


def request_record(provider, session, request_id, stream, model, usage, timestamp,
                   activity_id, activity_segment_id, task, cfg, catalogue, prior=None):
    """Normalize one deduplicated provider request and retain its original valuation."""
    agg = zero()
    add_usage(agg, usage)
    key = f"{provider}:{session}:{request_id}:{stream}"
    valuation = value_usage(agg, model, cfg, catalogue, provider, timestamp)
    if prior and prior.get("model_id") == model and prior.get("usage") == agg:
        valuation = prior.get("valuation") or valuation
    return {"request_key": key, "provider": provider, "session_id": session,
            "request_id": request_id, "stream": stream, "model_id": model,
            "timestamp": timestamp.isoformat() if timestamp else None,
            "activity_id": activity_id, "activity_segment_id": activity_segment_id,
            "task": task, "usage": agg,
            "valuation": valuation}


def apply_pinned_valuations(agg, records):
    """Aggregate retained per-request valuations without repricing old requests."""
    valuations = [r["valuation"] for r in records]
    subtotal = sum((Decimal(str(v.get("subtotal_usd", "0"))) for v in valuations), Decimal("0"))
    coverages = [v.get("pricing_coverage", "none") for v in valuations]
    coverage = ("complete" if coverages and all(x == "complete" for x in coverages)
                else "none" if coverages and all(x == "none" for x in coverages)
                else "partial" if coverages else "complete")
    missing = sorted({field for v in valuations for field in v.get("missing_rate_categories", [])})
    provenance = []
    for value in valuations:
        item = value.get("rate_provenance") or {}
        identity = (item.get("kind"), item.get("revision"), item.get("model_id"))
        if identity not in [(x.get("kind"), x.get("revision"), x.get("model_id")) for x in provenance]:
            provenance.append(item)
    valuation = {"subtotal_usd": str(subtotal), "pricing_coverage": coverage,
                 "missing_rate_categories": missing, "rate_provenance": provenance,
                 "tariff_confirmation": (valuations[0].get("tariff_confirmation", "unconfirmed")
                    if valuations and all(v.get("tariff_confirmation") == valuations[0].get("tariff_confirmation")
                                          for v in valuations) else "mixed")}
    agg["valuation"] = valuation
    agg["cost"] = float(subtotal) if coverage != "none" else None


# --- re-pricing a stored cost file at read time --------------------------------------------
# The money in state/cost/<session>.json is fixed at capture (per request, F2 of the
# true-price spec). A file captured while the project's family table priced catalogue-known
# models reads 1.5x too high on cmp1 (session 248a7a20: $0.4784169 against the catalogue's
# $0.3189446, which is also the CLI's own charge). Every request row stores its usage and model,
# so a reader can re-price the file in memory without the transcript and without rewriting it.
COLLAPSED_NOTE = "request ledger collapsed; split not re-priceable"
MIXED_SPLIT_NOTE = "stored tokens of this task differ from its request rows; split not re-priceable"
_RATE_WORD = {"project_override": "override", "bundled_exact": "catalogue",
              "legacy_project_override": "legacy"}


def _confirmation(cfg):
    value = cfg.get("rate_confirmation", "unconfirmed")
    return value.get("status", "unconfirmed") if isinstance(value, dict) else value


def _row_usage(row):
    """The usage of one stored request row as plain non-negative ints, or None when it is
    missing or unreadable (a bool, a string, NaN, a negative count): an unknown is not $0."""
    usage = row.get("usage") if isinstance(row, dict) else None
    if not isinstance(usage, dict) or not usage:
        return None
    out = zero()
    for key in out:
        value = usage.get(key)
        if value is None:
            value = 1 if key == "requests" else 0
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            return None
        if isinstance(value, float) and not math.isfinite(value):
            return None
        out[key] = int(value)
    return out


def _unpriced_valuation(reason, confirmation):
    return {"subtotal_usd": "0", "pricing_coverage": "none", "missing_rate_categories": [],
            "rate_provenance": {"kind": "unpriced", "reason": reason},
            "tariff_confirmation": confirmation}


def _revalue_row(row, cfg, catalogue, confirmation):
    """(model, usage, valuation) of one stored request row under the current rate rule. The
    row's own model and its own timestamp decide; a row with no model, or no readable usage,
    is unpriced with the reason stated."""
    body = row if isinstance(row, dict) else {}
    model = body.get("model_id")
    usage = _row_usage(body)
    if not isinstance(model, str) or not model.strip():
        return "?", usage, _unpriced_valuation("the request names no model id", confirmation), None
    if usage is None:
        return model, None, _unpriced_valuation("the request carries no readable usage", confirmation), None
    provider = body.get("provider") if isinstance(body.get("provider"), str) and body.get("provider") \
        else model_provider(model)
    at = parse_ts(body.get("timestamp"))
    return model, usage, value_usage(usage, model, cfg, catalogue, provider, at), (provider, at)


def _aggregate(items):
    """{model: aggregate} over (model, usage, valuation) triples, shaped like by_model:
    usage by category, the valuation summed the way `apply_pinned_valuations` sums it, and
    `cost` only when EVERY row of the model is completely priced (a partly priced model has a
    `priced_subtotal` in its valuation, never a cost that looks complete)."""
    groups: dict = {}
    for model, usage, valuation in items:
        groups.setdefault(model, []).append((usage, valuation))
    out = {}
    for model, rows in groups.items():
        agg = zero()
        for usage, _valuation in rows:
            if usage is None:
                agg["requests"] += 1
            else:
                for key in agg:
                    agg[key] += usage[key]
        apply_pinned_valuations(agg, [{"valuation": v} for _u, v in rows])
        if agg["valuation"]["pricing_coverage"] != "complete":
            agg["cost"] = None
        out[model] = agg
    return out


def _scope_exact(models):
    """Decimal total of a scope when it has models and every one is completely priced."""
    if not models:
        return None
    valuations = [m["valuation"] for m in models.values()]
    if any(v["pricing_coverage"] != "complete" for v in valuations):
        return None
    return sum((Decimal(v["subtotal_usd"]) for v in valuations), Decimal("0"))


def _scope_priced(models):
    return sum((Decimal(m["valuation"]["subtotal_usd"]) for m in models.values()), Decimal("0"))


def _as_float(value):
    return float(value) if value is not None else None


def _stored_tokens_match(entry, key_items):
    """True when the tokens capture stored for one by_task key equal the sum of the usage of the
    request rows that carry the key (input + output + cache reads and writes, the same sum capture
    writes into `by_task[*].tokens`). A missing or unreadable stored figure, a row with no
    readable usage, and a key with no rows at all are all False: the split is then not provable."""
    stored = entry.get("tokens") if isinstance(entry, dict) else None
    if isinstance(stored, bool) or not isinstance(stored, (int, float)) or not math.isfinite(stored):
        return False
    if not key_items or any(i["usage"] is None for i in key_items):
        return False
    return stored == sum(sum(v for k, v in i["usage"].items() if k != "requests") for i in key_items)


def _collapsed_activity_split(by_activity, items, cfg, catalogue, confirmation):
    """{activity: {model: aggregate} | None} for a collapsed file with several activities.

    The per-activity usage by model is stored (by_activity[*].by_model) even after the request
    ledger collapsed, so a split can be priced EXACTLY — but only when the price of a model does
    not depend on anything the collapse threw away: every carry row of the model resolves to the
    same rates, the rates carry no long-context tariff, and the stored per-activity usage adds
    up to the carry rows' usage. Then the parts add up to the session total to the last digit.
    Otherwise the activity is None: never a share, never a guess."""
    carry: dict = {}
    for item in items:
        carry.setdefault(item["model"], []).append(item)
    stored_total: dict = {}
    unreadable = set()
    for entry in by_activity.values():
        for model, agg in ((entry.get("by_model") if isinstance(entry.get("by_model"), dict) else {}).items()):
            usage = _row_usage({"usage": agg})
            total = stored_total.setdefault(model, dict(zero()))
            for key in total:
                total[key] += (usage or {}).get(key, 0)
            if usage is None:
                unreadable.add(model)
    exact: dict = {}
    for model, rows in carry.items():
        signature, ok = None, all(r["usage"] is not None for r in rows)
        for r in rows:
            rates, provenance = resolve_rate(model, cfg, catalogue, r["provider"], r["at"])
            if rates is None or provenance.get("long_context"):
                ok = False
                break
            mark = json.dumps([rates, provenance], sort_keys=True, default=str)
            if signature is None:
                signature = mark
            elif mark != signature:
                ok = False
                break
        if ok:
            sums = zero()
            for r in rows:
                for key in sums:
                    sums[key] += r["usage"][key]
            stored = stored_total.get(model) or {}
            ok = model not in unreadable and all(stored.get(key) == sums[key] for key in sums)
        exact[model] = rows[0] if ok else None
    result = {}
    for aid, entry in by_activity.items():
        stored_models = entry.get("by_model") if isinstance(entry.get("by_model"), dict) else {}
        triples, good = [], bool(stored_models)
        for model, agg in stored_models.items():
            usage = _row_usage({"usage": agg})
            anchor = exact.get(model)
            if usage is None or anchor is None:
                good = False
                break
            triples.append((model, usage, value_usage(usage, model, cfg, catalogue,
                                                      anchor["provider"], anchor["at"])))
        result[aid] = _aggregate(triples) if good else None
    return result


def revalue_document(doc, cfg, catalogue):
    """A NEW dict: one state/cost/<session>.json re-priced at read time, from the stored usage
    of its request rows, under the current rate rule (`resolve_rate`: rate_overrides, then the
    catalogue, then the legacy table only for a model neither knows).

    `cfg` is the project's `cost` block (None or {} = no project rates), `catalogue` the parsed
    model-rates.json (None or {} = the bundled one). Pure: the input is deep-copied and never
    mutated, nothing is written (FR-45); the pinned values on disk stay as history.

    Re-valued: every request row's `valuation`, and every aggregate a reader uses — by_model,
    orchestrator, agents[], by_task, by_activity, total_cost_usd, priced_subtotal_*,
    pricing_coverage, reconciliation. Money is NOT rounded here (capture rounds costs to four
    decimals). A cost is a number only when every request behind it is completely priced; an
    unpriced request never contributes $0 to a total (`priced_subtotal_*` hold the known part).

    A collapsed ledger (a session with no factory activity: one carry row per stream and model)
    keeps the session, orchestrator and agent figures exact. Its by_task / by_activity split is
    priced only when it is exact: one key = the whole session; several keys = None with
    `reprice_note`, except by_activity keys whose stored per-model usage re-prices exactly
    (see `_collapsed_activity_split`). A model with a long-context tariff and more than one
    request inside one row is unpriced, with the reason in `repriced_at_read`.

    A MIXED ledger (carry rows and per-request rows together) is not collapsed: its by_task is
    priced key by key from the rows, and only when the stored `tokens` of the key equal the sum of
    its rows; otherwise that key is None with `reprice_note`. Its by_activity keeps the carry-row
    route above.

    `repriced_at_read` says what was used: catalogue_revision, rates ("catalogue" | "override" |
    "legacy" | "mixed" | "none" when nothing was priced), ledger ("absent" | "empty" |
    "collapsed" | "mixed" | "per_request"), and — when any request stays
    unpriced — unpriced_requests and unpriced_reasons."""
    out = copy.deepcopy(doc) if isinstance(doc, dict) else {}
    cfg = cfg if isinstance(cfg, dict) else {}
    catalogue = catalogue if isinstance(catalogue, dict) and catalogue else load_catalogue()
    revision = catalogue.get("catalogue_revision")
    confirmation = _confirmation(cfg)
    rows = out.get("requests")
    items = []
    for row in rows if isinstance(rows, list) else []:
        body = row if isinstance(row, dict) else {}
        model, usage, valuation, where = _revalue_row(body, cfg, catalogue, confirmation)
        if isinstance(row, dict):
            row["valuation"] = valuation
        items.append({"model": model, "usage": usage, "valuation": valuation,
                      "stream": body.get("stream"), "task": body.get("task"),
                      "activity": body.get("activity_id"),
                      "provider": where[0] if where else None, "at": where[1] if where else None})
    # A ledger is COLLAPSED only when every row is a carry row. One with carry rows AND per-request
    # rows is MIXED (session 24477101 of the testproject1-sdk copy, story TP1-15045: a capture that
    # replays an earlier collapsed ledger as requests writes exactly that). Reading `any` carry row
    # as "collapsed" threw away a by_task that was exactly priceable from the rows (5 real files,
    # $75.93 in that one), so a mixed ledger prices by_task key by key when it can prove the split.
    row_list = rows if isinstance(rows, list) else []
    carry_count = sum(1 for r in row_list
                      if isinstance(r, dict) and str(r.get("request_id") or "").startswith("carry:"))
    collapsed = bool(row_list) and carry_count == len(row_list)
    mixed = 0 < carry_count < len(row_list)
    carry_like = carry_count > 0     # by_activity keeps its carry-row route for both shapes
    ledger = ("absent" if not isinstance(rows, list) else "empty" if not rows
              else "collapsed" if collapsed else "mixed" if mixed else "per_request")

    def triples(select):
        return [(i["model"], i["usage"], i["valuation"]) for i in items if select(i)]

    by_model = _aggregate(triples(lambda i: True))
    session_exact = _scope_exact(by_model)
    session_priced = _scope_priced(by_model)

    orchestrator = out.get("orchestrator")
    orch_models = _aggregate(triples(lambda i: i["stream"] == "orchestrator"))
    if isinstance(orchestrator, dict):
        had = bool(orchestrator.get("by_model"))
        orchestrator["by_model"] = orch_models
        if orch_models:
            orchestrator["cost"] = _as_float(_scope_exact(orch_models))
        elif had:
            orchestrator["cost"] = None
            orchestrator["reprice_note"] = "no request rows for the orchestrator stream"
    agent_exacts = []
    for agent in out.get("agents") if isinstance(out.get("agents"), list) else []:
        if not isinstance(agent, dict):
            continue
        mine = _aggregate(triples(lambda i: bool(agent.get("file")) and i["stream"] == agent.get("file")))
        had = bool(agent.get("by_model"))
        agent["by_model"] = mine
        if mine:
            agent["cost"] = _as_float(_scope_exact(mine))
        elif had:
            agent["cost"] = None
            agent["reprice_note"] = "no request rows for this agent file"
        agent_exacts.append(_scope_exact(mine))

    task_exacts = []
    by_task = out.get("by_task")
    if isinstance(by_task, dict):
        for key, entry in by_task.items():
            if not isinstance(entry, dict):
                continue
            if collapsed and len(by_task) == 1:
                exact, priced = session_exact, session_priced
            elif collapsed:
                exact, priced = None, None
                entry["reprice_note"] = COLLAPSED_NOTE
            else:
                mine = _aggregate(triples(lambda i: i["task"] == key))
                exact = _scope_exact(mine)
                priced = _scope_priced(mine) if mine else None
                if not mine:
                    entry["reprice_note"] = "no request rows carry this task"
                elif mixed and not _stored_tokens_match(entry, [i for i in items if i["task"] == key]):
                    # the rows do not add up to what capture stored for this task: the split is
                    # not provable, so it is None, never a figure that only looks exact
                    exact, priced = None, None
                    entry["reprice_note"] = MIXED_SPLIT_NOTE
            entry["cost"] = _as_float(exact)
            entry["priced_subtotal_usd"] = _as_float(priced)
            task_exacts.append(exact)
    by_activity = out.get("by_activity")
    if isinstance(by_activity, dict):
        split = (_collapsed_activity_split(by_activity, items, cfg, catalogue, confirmation)
                 if carry_like and len(by_activity) > 1 else {})
        for key, entry in by_activity.items():
            if not isinstance(entry, dict):
                continue
            if carry_like and len(by_activity) == 1:
                mine = copy.deepcopy(by_model)
            elif carry_like:
                mine = split.get(key)
                if mine is None:
                    entry["by_model"] = {m: dict(a, cost=None, valuation=_unpriced_valuation(COLLAPSED_NOTE, confirmation))
                                         for m, a in (entry.get("by_model") or {}).items() if isinstance(a, dict)}
                    entry["cost"] = None
                    entry["reprice_note"] = COLLAPSED_NOTE
                    continue
            else:
                mine = _aggregate(triples(lambda i: i["activity"] == key))
                if not mine:
                    entry["cost"] = None
                    entry["reprice_note"] = "no request rows carry this activity"
                    continue
            entry["by_model"] = mine
            entry["cost"] = _as_float(_scope_exact(mine))

    out["by_model"] = by_model
    out["total_cost_usd"] = _as_float(session_exact)
    out["priced_subtotal_exact_usd"] = str(session_priced)
    out["priced_subtotal_usd"] = float(session_priced)
    coverages = [m["valuation"]["pricing_coverage"] for m in by_model.values()]
    out["pricing_coverage"] = ("none" if not by_model else "complete" if all(c == "complete" for c in coverages)
                               else "partial" if any(c != "none" for c in coverages) else "none")
    out["catalogue_revision"] = revision
    reconciliation = out.get("reconciliation")
    if isinstance(reconciliation, dict):
        orch_exact = _scope_exact(orch_models)
        parts_exact = (None if orch_exact is None or any(v is None for v in agent_exacts)
                       else orch_exact + sum(agent_exacts, Decimal("0")))
        tasks_known = bool(task_exacts) and all(v is not None for v in task_exacts)
        tasks_exact = sum(task_exacts, Decimal("0")) if tasks_known else None
        parts_partial = (orch_exact or Decimal("0")) + sum((v for v in agent_exacts if v is not None), Decimal("0"))
        reconciliation["session_total"] = _as_float(session_exact)
        reconciliation["orchestrator_plus_agents"] = float(parts_partial) if session_exact is not None else None
        reconciliation["tasks_sum"] = _as_float(tasks_exact) if session_exact is not None else None
        settled = (out.get("usage_status") == "actual" and session_exact is not None
                   and parts_exact is not None and tasks_exact is not None
                   and (out.get("external_reconciliation") or {}).get("complete") is True)
        reconciliation["match"] = (abs(session_exact - parts_exact) <= Decimal("0.000001")
                                   and abs(session_exact - tasks_exact) <= Decimal("0.000001")) if settled else None

    priced_kinds = {_RATE_WORD.get((i["valuation"].get("rate_provenance") or {}).get("kind"))
                    for i in items if i["valuation"]["pricing_coverage"] != "none"} - {None}
    unpriced = [i["valuation"] for i in items if i["valuation"]["pricing_coverage"] != "complete"]
    marker = {"catalogue_revision": revision,
              "rates": (next(iter(priced_kinds)) if len(priced_kinds) == 1 else "mixed" if priced_kinds else "none"),
              "captured_catalogue_revision": doc.get("catalogue_revision") if isinstance(doc, dict) else None,
              "ledger": ledger}
    if unpriced:
        reasons = set()
        for valuation in unpriced:
            provenance = valuation.get("rate_provenance") or {}
            if provenance.get("reason"):
                reasons.add(provenance["reason"])
            if valuation.get("missing_rate_categories") and valuation["pricing_coverage"] == "partial":
                reasons.add("no rate for: " + ", ".join(valuation["missing_rate_categories"]))
        marker["unpriced_requests"] = len(unpriced)
        marker["unpriced_reasons"] = sorted(reasons)
    out["repriced_at_read"] = marker
    if ledger in ("absent", "empty"):
        out["reprice_note"] = "no request ledger; nothing was re-priced"
    return out


def collapse_requests(records, session_id, cfg, catalogue):
    """A session with no factory activity: fold every per-request row into one
    carry row per (stream, model) instead of persisting the whole ledger. Every real request
    already attributes to task "(no task)" / activity "unclassified" — there is no per-task or
    per-activity split to lose. Token and cost totals stay exact (the raw fields are summed
    verbatim before re-valuing); only the request COUNT a future incremental scan would replay
    collapses to one per carry row (corrected back to the true count for display here, but not
    preserved past the next capture) - an accepted approximation for a session doing no factory
    work. Measured need: one real non-factory session's requests[] alone was 1.3 MB of a 1.8 MB
    state/cost/<session>.json (1449 rows); this reduces the same data to one row per model.

    The carry row's money is the SUM of the valuations of the requests it folds, taken before
    they are dropped (`_carry_valuation`). It used to be the valuation of the summed tokens as if
    they were ONE request, which put a model with a long-context tariff into the long band
    whenever the sum crossed the threshold: three gpt-5.6-terra requests that cost 0.6036 were
    pinned at 1.2054."""
    buckets: dict = {}
    stamps: dict = {}
    members: dict = {}
    for r in records:
        key = (r.get("stream"), r.get("model_id"))
        members.setdefault(key, []).append(r)
        agg = buckets.setdefault(key, zero())
        for k in agg:
            agg[k] += (r.get("usage") or {}).get(k, 0)
        if r.get("timestamp"):
            stamps[key] = max(stamps.get(key) or "", r["timestamp"])
    collapsed = []
    for (stream, model), agg in buckets.items():
        raw_usage = {"input_tokens": agg["input"], "output_tokens": agg["output"],
                     "cache_read_input_tokens": agg["cache_read"],
                     "cache_creation": {"ephemeral_5m_input_tokens": agg["cache_write_5m"],
                                        "ephemeral_1h_input_tokens": agg["cache_write_1h"]}}
        record = request_record(model_provider(model), session_id, f"carry:{stream}:{model}", stream,
            model, raw_usage, parse_ts(stamps.get((stream, model))), "unclassified", "unclassified",
            "(no task)", cfg, catalogue)
        record["usage"]["requests"] = agg["requests"]
        if agg["requests"] > 1:
            record["valuation"] = _carry_valuation(members[(stream, model)], agg["requests"], cfg)
        collapsed.append(record)
    return collapsed


COST_REL = "qa-factory/state/cost/"      # where a project keeps its cost files (the folder `capture` writes <session>.json into)


def first_request_lookup(project, agent_id):
    """`(hit, reason)`: the EARLIEST request of one dispatched agent in a project's cost files (RC1-14, AR-13: the one
    reader of this shape for `role_load.py`'s control). Read-only, pure.

    Candidate rows are the `requests[]` rows of every `<project>/qa-factory/state/cost/*.json` whose `stream` is
    `agent-<agent_id>.jsonl` (a subagent's transcript), or whose `session_id` is the agent id and whose stream is
    `orchestrator` (driver mode: the role is its own session). A row with no parseable `timestamp`, no `usage` object, or a
    carry row of a collapsed ledger is skipped - a carry row is a SUM of many requests, never a first one. `hit` is
    `{"usage", "timestamp", "file"}` or None; when None, `reason` says which of the four ways it is None (no agent bound, no
    cost file, ledger collapsed, no request of this agent), so a caller never reads "nothing found" as a number (FR-41)."""
    agent = str(agent_id or "").strip()
    if not agent:
        return None, "the dispatch has no bound agent"
    folder = Path(project) / COST_REL
    files = sorted(folder.glob("*.json")) if folder.is_dir() else []
    if not files:
        return None, f"no cost file under {COST_REL}"
    stream = f"agent-{agent}.jsonl"
    best, collapsed = None, False
    for path in files:
        doc = read_json(path, None, kind=dict)
        rows = doc.get("requests") if doc else None
        by_task = doc.get("by_task") if doc else None
        if isinstance(by_task, dict) and any(isinstance(e, dict) and e.get("reprice_note") == COLLAPSED_NOTE
                                             for e in by_task.values()):
            collapsed = True
            continue
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            if not (row.get("stream") == stream
                    or (row.get("session_id") == agent and row.get("stream") == "orchestrator")):
                continue
            if str(row.get("request_id") or "").startswith("carry:"):
                collapsed = True
                continue
            when = parse_ts(row.get("timestamp")) if row.get("timestamp") else None
            if when is None or not isinstance(row.get("usage"), dict):
                continue
            if best is None or when.timestamp() < best[0]:
                best = (when.timestamp(), {"usage": row["usage"], "timestamp": row.get("timestamp"), "file": path.name})
    if best:
        return best[1], ""
    if collapsed:
        return None, "request ledger collapsed"
    return None, f"no request of agent {agent} in the cost files under {COST_REL}"


def _carry_valuation(member_records, requests, cfg):
    """The valuation of a carry row that folds `requests` (> 1) requests: the sum of the
    valuations those requests already carry, never the tariff applied to their summed tokens as
    one request. The row says so: `priced_as: "sum_of_requests"` and `requests_priced`.

    When any folded request has no valuation, or is not completely priced, the row is not a
    complete sum: a request with no valuation makes it unpriced (coverage none, reason stated),
    a partly priced set keeps the known part with coverage partial and a note. There is no
    long-context guess in either case."""
    confirmation = _confirmation(cfg if isinstance(cfg, dict) else {})
    valuations = [m.get("valuation") if isinstance(m, dict) else None for m in member_records]
    if not valuations or any(not isinstance(v, dict) for v in valuations):
        valuation = _unpriced_valuation(
            f"a carry row of {requests} requests: a folded request has no valuation, so the row "
            f"is not priced (never as one long-context request)", confirmation)
    else:
        holder: dict = {}
        apply_pinned_valuations(holder, [{"valuation": v} for v in valuations])
        valuation = dict(holder["valuation"])
        parts = valuation["rate_provenance"]
        valuation["rate_provenance"] = parts[0] if len(parts) == 1 else {"kind": "mixed", "parts": parts}
        if valuation["pricing_coverage"] != "complete":
            unpriced = sum(1 for v in valuations if v.get("pricing_coverage", "none") != "complete")
            valuation["note"] = (f"{unpriced} of {len(valuations)} folded requests are not completely "
                                 f"priced; the row's cost is not a complete sum")
    valuation["priced_as"] = "sum_of_requests"
    valuation["requests_priced"] = requests
    return valuation


TASK_FLAG =re.compile(r"--task\s+['\"]?([\w./-]+)")


# --- external agent calls: the command forms that count as one, as data (P18) -----------------
# A call to an agent outside the host (the package ships no such form; a project adds its own) is billed where the transcript cannot see
# it. Which shell commands count as such a call is `references/external-agent-calls.json` plus
# the project's own rows under config `cost.external_agent_forms`; nothing is derived from how a
# project invokes its agents (F-11). A call of an agent whose form is in no row is a shell
# command like any other, so the price names the forms it counted for (`recognized_forms`).
EXTERNAL_FORMS_FILE = "external-agent-calls.json"
EXTERNAL_PREFIX = "__external__:"
NO_CONSUMER = "identity-unavailable"   # the key's stand-in for a consumer the command did not name
UNMARKED_FORM = "unmarked"                  # a key with no `~` names no form (a checkpoint older than the form rows)
_FORM_ID_RE = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")
_CONSUMER_RE = re.compile(r"[A-Za-z0-9_.-]{1,128}")   # a `:` would shift the key's split
_FORM_FIELDS = ("id", "command_re", "consumer_re", "call_id_prefix", "invocation_method",
                "provider", "service", "unknown_consumer_label")


def _form_problem(row):
    """Why a form row cannot be used, or "" when it can. The grammar keeps the project's word
    from corrupting a key: no `:`/`~`/whitespace in an id or prefix, a group in consumer_re,
    and a command_re that matches nothing in particular is refused (it would count every call)."""
    if not isinstance(row, dict):
        return f"is {type(row).__name__}, not an object"
    for field in _FORM_FIELDS:
        if not (isinstance(row.get(field), str) and row[field].strip()):
            return f"has no {field}"
    for field in ("id", "call_id_prefix"):
        if not _FORM_ID_RE.fullmatch(row[field]):
            return f"{field} {row[field]!r} is not [a-z0-9][a-z0-9_.-]{{0,63}}"
    try:
        command, consumer = re.compile(row["command_re"]), re.compile(row["consumer_re"])
    except (re.error, RecursionError, OverflowError, ValueError) as exc:
        return f"has a regex that does not compile ({exc})"
    if consumer.groups < 1:
        return "consumer_re has no group"
    if command.search(""):
        return "command_re matches an empty command"
    return ""


def _form_rows(rows, where, seen):
    """(compiled rows, problems) for `rows`; a bad row, or one reusing an id or prefix already in
    `seen`, is skipped and named. Two rows sharing a prefix would give two agents one call id."""
    out, problems = [], []
    if not isinstance(rows, list):
        return out, [f"{where} is {type(rows).__name__}, not a list"]
    for index, row in enumerate(rows):
        named = row.get("id") if isinstance(row, dict) else None
        why = _form_problem(row)
        if not why:
            clash = [key for key in ("id", "call_id_prefix") if (key, row[key]) in seen]
            why = f"reuses {clash[0]} {row[clash[0]]!r} of an earlier row" if clash else ""
        if why:
            problems.append(f"{where}[{index}]" + (f" ({named})" if isinstance(named, str) else "") + f": {why}")
            continue
        seen.update((key, row[key]) for key in ("id", "call_id_prefix"))
        out.append({**row, "_cmd": re.compile(row["command_re"]), "_who": re.compile(row["consumer_re"])})
    return out, problems


def external_forms(project_rows=None):
    """(form rows in match order, problem text). Package rows first, then the project's.
    The package ships no agent form of its own (its list may be empty): which agent CLI a project
    calls is the project's word. Unreadable or invalid package data -> no package row is used, with a
    problem (FR-41/59); an invalid project row is skipped and named. A problem makes `complete` False
    downstream."""
    seen, where = set(), f"references/{EXTERNAL_FORMS_FILE}"
    data = load_ref_json(EXTERNAL_FORMS_FILE)    # {} for a missing or unreadable file
    rows = data.get("forms") if isinstance(data, dict) else None
    package, problems = _form_rows(rows, f"{where} forms", seen) if rows is not None else (
        [], [f"{where} is missing, unreadable or has no forms list"])
    if problems:
        seen.clear()
        package = []
        problems = ["; ".join(problems) + "; no package form is used"]
    mine, bad = _form_rows([] if project_rows is None else project_rows, "cost.external_agent_forms", seen)
    return package + mine, "; ".join(problems + bad)


def _external_hits(command, forms):
    """[(form, consumer or None)] for one tool_use: each form counts once; a span of the command
    that an earlier form matched is not matched again (one invocation is one call)."""
    lowered, claimed, hits = command.lower(), [], []
    for form in forms:
        for found in form["_cmd"].finditer(lowered):
            if found.start() == found.end() or any(found.start() < end and start < found.end() for start, end in claimed):
                continue
            claimed.append(found.span())
            who = form["_who"].search(command)
            name = who.group(1) if who else None
            hits.append((form, name if name and _CONSUMER_RE.fullmatch(name) else None))
            break
    return hits


def task_from_path(fp: str):
    """The task a written path belongs to: the folder under `qa-factory/artifacts/`, else None.

    `qa-factory/state/` is never a task anchor: its subfolders (`onboarding/`, `words/`, `doctor-...`) are the
    factory's own notes, and a Write there used to open a task named after the folder, so an onboarding run
    priced as a story (F-7; no writer of `state/<task>/` exists in the package, grep in the HF7-4 report).
    A wrong answer here moves money, so the error direction is None: no task, never somebody else's."""
    fp = fp.replace("\\", "/")
    anchor = "qa-factory/artifacts/"
    if anchor in fp:
        seg = fp.split(anchor, 1)[1].split("/")
        t = seg[1] if seg[0] in NOT_A_TASK and len(seg) > 1 else seg[0]
        if t and "." not in t and t not in NOT_A_TASK:
            return t
    return None


def _resolve_forms(forms, problems):
    """The form rows to match with. None = the package's own rows (a project's rows are the caller's
    to pass); the problem with that data goes to `problems`, a list the caller owns, never dropped (FR-41)."""
    if forms is not None:
        return forms
    rows, problem = external_forms()
    if problem and problems is not None:
        problems.append(problem)
    return rows


def forms_fingerprint(forms) -> str:
    """What a scan was done WITH: the effective rows in match order (id, prefix, both regexes), canonical
    JSON. Kept in every scan checkpoint: a file scanned with other rows must be rescanned whole, or
    `recognized_forms` would claim a form for calls that were never looked for (FR-41, P18)."""
    return content_hash([[f["id"], f["call_id_prefix"], f["command_re"], f["consumer_re"]] for f in forms])


# --- one request, several provider records: a model fallback (CD1-9, P18) ---------------------
# A request served by a model fallback is written as several `assistant` lines that repeat ONE
# snapshot under a label that is not true (real: five lines all labelled opus-4-8 whose
# `usage.iterations` hold a fable-5 message and an opus-4-8 message), so pricing the request by
# the last line's label priced the fable message at the opus rate. `usage.iterations` is the
# provider's own record of each message of the request: with 2 or more usable entries THAT is
# the request -- one part per entry, each priced by ITS OWN model, the request = the sum (P20:
# the record is the oracle, never the labels; the top level of a carrier line is NOT a record of
# the request total -- it holds the last entry's counts with the first entry's cache split -- so
# it is never compared with the parts). `tools/transcripts.request_parts` is the same
# rule for the measurement tools, which the package never imports; the two are two READERS of
# one provider record, not two records of one quantity. Differences from the tools reader, all
# deliberate: D1 no carrier -> the last line of the request (today's reading), the tools take the
# per-model MAX over the lines; D2 the bare key stays on the model of the request's last line
# (the row the old reader stored), the tools anchor on the labelled models; D3 an entry with a
# bool/str/negative/non-finite number is unusable (the tools int()-coerce); D4 a part is an
# `add_usage` dict with an explicit 5m/1h split; D5 a line with neither requestId nor uuid is
# skipped (as today), the tools key it by line number; D6 the carrier is read only on the lines
# the sidechain filter keeps; D7 the incremental merge (`_merge_usage`). The same as the tools:
# the threshold, `<synthetic>` entries dropped, the last carrier wins, labels ignored under a
# carrier, 0/1 entries ordinary and uncounted, iterations never raise, the 1-hour split clamped
# into [0, write] (R1).
# READER_STAMP is the version of what a capture derives from a transcript (usage, task markers, person turns, gaps):
# a checkpoint or a cost file of another value is rebuilt once; bump it with any change to what a scan or a capture
# writes. It is kept in every scan checkpoint, in `capture_key` and in the cost document (`capture_logic`).
READER_STAMP = "capture-0.10.7"
_COUNT_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")


def _count(value):
    """A usage number as an int, or None when it is not a non-negative finite number (a bool and a str are not)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return int(value) if value >= 0 else None


def _iteration_part(entry):
    """(model, usage, split_known) of one `usage.iterations` entry, or None when it is unusable: not an
    object, no non-empty str `model`, none of the four count keys, or a count key holding anything but a
    non-negative finite number. usage has `add_usage`'s shape; W = the entry's `cache_creation_input_tokens`
    (absent -> 0), the 1-hour split is clamped into [0, W] and the 5-minute part is W - 1h. A split that
    is absent or mistyped is not invented: the whole write is a 5-minute write and split_known is False."""
    model = entry.get("model") if isinstance(entry, dict) else None
    if not isinstance(model, str) or not model or not any(k in entry for k in _COUNT_KEYS):
        return None
    numbers = {k: _count(entry[k]) for k in _COUNT_KEYS if k in entry}
    if None in numbers.values():
        return None
    write = numbers.get("cache_creation_input_tokens", 0)
    split = entry.get("cache_creation")
    one_hour = _count(split.get("ephemeral_1h_input_tokens")) if isinstance(split, dict) else None
    held = 0 if one_hour is None else min(one_hour, write)
    usage = {k: numbers.get(k, 0) for k in _COUNT_KEYS}
    usage["cache_creation"] = {"ephemeral_5m_input_tokens": write - held, "ephemeral_1h_input_tokens": held}
    return model, usage, one_hour is not None


def _iteration_parts(usage):
    """(parts, bad) of a usage dict's `iterations`: parts = one (model, usage, split_known) per entry when the
    list holds 2 or more usable entries (a `<synthetic>` entry is not one), else None. bad = True when
    `iterations` is present but malformed (not a list, or any entry unusable): the line's iterations are then
    ignored and counted. null and absent are the same (no count); a list of 0 or 1 entries is ordinary --
    every single-model request carries one, and the real one is modelless -- so the length is checked
    BEFORE the entries (the other order would count them all as bad). Never raises."""
    entries = usage.get("iterations")
    if entries is None:
        return None, False
    if not isinstance(entries, list):
        return None, True
    if len(entries) < 2:
        return None, False
    parts = []
    for entry in entries:
        part = _iteration_part(entry)
        if part is None:
            return None, True
        if part[0] != "<synthetic>":
            parts.append(part)
    return (parts, False) if len(parts) >= 2 else (None, False)


def _empty_over_full(new, old) -> bool:
    """R2: True when `new` is a usage dict whose four top-level counts are all zero or absent while `old` has
    some -- the line that must not displace the earlier one. The nested `cache_creation` split is NOT counted:
    the real zero line echoes the split of the line before it."""
    def has_counts(usage):
        return isinstance(usage, dict) and any(usage.get(k) for k in _COUNT_KEYS)
    return isinstance(new, dict) and not has_counts(new) and has_counts(old)


def _fold_request(fold, model, usage, ts, counts):
    """One passing line into its request's fold ({"line": (model, usage, ts), "label", "ts", "parts"}; None =
    the first line). The line is the LAST line of the request, except that a line whose top-level counts are all
    zero never displaces an earlier line that has some (R2: the last line of 9 real requests is such a shape --
    zeros on top, the numbers only in its one-entry iterations -- and last-wins priced them $0). parts = the
    last carrier (`_iteration_parts`) of any line; `label` and `ts` are the request's last passing line's."""
    parts, bad = _iteration_parts(usage) if isinstance(usage, dict) else (None, False)
    if bad:
        counts["bad_iterations"] = counts.get("bad_iterations", 0) + 1
    older = fold["line"] if fold else None
    keep = older is not None and _empty_over_full(usage, older[1])
    return {"line": older if keep else (model, usage, ts), "label": model, "ts": ts,
            "parts": parts or (fold["parts"] if fold else None)}


def _part_suffixes(parts, anchor):
    """The row-key suffix of each part: the anchor keeps the bare request id, every other part adds
    `|<model>`, and a part whose `|<model>` is taken adds `#<position>` -- the part's index (the tools'
    `_part_suffixes` rule), not a counter: two entries of one model are two rows, never one."""
    used, suffixes = set(), []
    for i, part in enumerate(parts):
        suffix = "" if i == anchor else f"|{part[0]}"
        if suffix in used:
            suffix += f"#{i}"
        used.add(suffix)
        suffixes.append(suffix)
    return suffixes


def _request_rows(rid, fold):
    """The {key: (model, usage, ts)} rows of one request's fold. No carrier: the one row of the fold's line.
    A carrier: one row per part, the ANCHOR first under the bare id (the first part whose model is the label
    of the request's last line -- the row the old reader stored; none -> the first part), the others in
    iterations order under `<id>|<model>`; every part carries the request's last timestamp, so all parts land
    on one task, activity and rate window. The label chooses a key, never money."""
    parts = fold["parts"]
    if parts is None:
        return {rid: fold["line"]}
    anchor = next((i for i, part in enumerate(parts) if part[0] == fold["label"]), 0)
    suffixes = _part_suffixes(parts, anchor)
    order = [anchor] + [i for i in range(len(parts)) if i != anchor]
    return {rid + suffixes[i]: (parts[i][0], parts[i][1], fold["ts"]) for i in order}


def _usage_rows(folds, counts):
    """All requests' rows, in first-seen order of the request; the request ids whose carrier has a part with
    no 1-hour split go to counts["split_missing_keys"] (and their number to "split_missing")."""
    rows, missing = {}, []
    for rid, fold in folds.items():
        rows.update(_request_rows(rid, fold))
        if fold["parts"] and not all(part[2] for part in fold["parts"]):
            missing.append(rid)
    if missing:
        counts["split_missing_keys"], counts["split_missing"] = missing, len(missing)
    return rows


def _merge_usage(saved: dict, tail: dict) -> None:
    """The tail scan's request rows into the saved ones ({key: [model, usage, ts-iso]}). M1: a request whose
    tail result holds a carrier (a `<id>|...` key) first drops every saved `<id>|*` key, so a later carrier
    replaces an earlier one whole. M2: a tail result for an id WITHOUT a carrier, while the saved rows hold
    `<id>|*` parts, leaves the id and its parts as saved (the carrier wins over later lines across a
    checkpoint as inside one file); a tail line with no counts never displaces a saved row that has some (R2
    across a checkpoint: the money must not depend on where the scan chunks fell). A checkpoint of the old
    reader holds no parts, so for it neither rule can fire: the request is read as before."""
    bases = {}
    for key in saved:
        if "|" in key:
            bases.setdefault(key.split("|", 1)[0], []).append(key)
    carriers = {key.split("|", 1)[0] for key in tail if "|" in key}
    for base in carriers:
        for key in bases.get(base, ()):
            del saved[key]
    for key, (model, usage, ts) in tail.items():
        old = saved.get(key)
        if key not in carriers and (key in bases or (old and _empty_over_full(usage, old[1]))):
            continue
        saved[key] = [model, usage, ts.isoformat() if ts else None]


def _carry_reader_counts(state: dict, counts: dict) -> None:
    """The scan's `usage.iterations` counts into the checkpoint state. bad_iterations: lines, summed over
    scans (the lines of one scan are never read again). split_missing: DISTINCT request ids -- a carrier
    repeated on lines that straddle a checkpoint, or replaced by a later one, is one request, not two."""
    if counts.get("bad_iterations"):
        state["bad_iterations"] = state.get("bad_iterations", 0) + counts["bad_iterations"]
    if counts.get("split_missing_keys"):
        state["split_missing_keys"] = sorted(set(state.get("split_missing_keys") or []) | set(counts["split_missing_keys"]))


def usage_reader_counts(checkpoints) -> dict:
    """The cost document's `usage_reader`: the per-file checkpoint counts summed -- {"bad_iterations": lines whose
    `usage.iterations` was malformed and ignored, "split_missing": requests with a carrier part whose 1-hour
    split was absent (priced as a 5-minute write)} -- or {} when both are zero (FR-41: a count is shown, a
    clean read is not decorated)."""
    states = [(cp.get("state") or {}) for cp in checkpoints if isinstance(cp, dict)]
    bad = sum(int(s.get("bad_iterations") or 0) for s in states)
    missing = sum(len(s.get("split_missing_keys") or []) for s in states)
    return {"bad_iterations": bad, "split_missing": missing} if bad or missing else {}


# --- whose turn is a user line: the person's, a notification's, or neither (HF7-4, t-1518 DP-4) ----------
# A transcript's `user` rows are not all a person speaking: a tool result, a host meta line, a compaction
# summary and a background task's notification are `user` rows too, and the old reader counted every row with
# a `promptId` as the person coming back (a tool result carries the promptId of the turn it belongs to).
# Which rows are NOT the person is data of the host (`references/host-report-forms.json`,
# `claude.not_a_person_turn`), read through the one reader `host_adapter.report_forms` (AR-1, AR-5).
PERSON_FORMS_LEGACY = "legacy-promptId"   # the fingerprint of a scan made with the old predicate (no readable rule)


def _person_rule():
    """The rule of `claude.not_a_person_turn` as `{"flags": [...], "notification_prefixes": [...]}`, or False
    when the host forms cannot be read (one stderr line, never an exception: this runs in a hook). False means
    the OLD predicate (a `user` row with a `promptId` is a human event) and NO transfer of a turn into the
    activity it opened: without a measured turn nothing is moved (AR-28, the safe side)."""
    from host_adapter import report_forms
    forms, why = report_forms(host="claude")
    rule = ((forms or {}).get("claude") or {}).get("not_a_person_turn")
    if not isinstance(rule, dict):
        print(f"cost_capture: {why or 'host report forms hold no claude.not_a_person_turn'}; "
              "a user row with a promptId counts as the person's turn and no turn is moved into the activity it opened",
              file=sys.stderr)
        return False
    # `claude.person_question_tools`: the host's tool that puts a question to the person; the span between the
    # call and its answer is a wait the turn gaps never see (the answer is a tool_result row, "other"). Read here
    # and validated here (host_adapter's row table does not know the key): absent or malformed = no tool, so no
    # question is measured and the document says `unmeasured` - never a silent zero (AR-28, E-C1). The list is
    # part of the rule, so it is part of the `person_forms` fingerprint: a checkpoint made before the key existed
    # is rebuilt once and reads its question spans (E-D1).
    names = ((forms or {}).get("claude") or {}).get("person_question_tools")
    tools = [n for n in names if isinstance(n, str) and n.strip()] if isinstance(names, list) else []
    return {"flags": list(rule["flags"]), "notification_prefixes": list(rule["notification_prefixes"]),
            "question_tools": tools}


def user_line_kind(rec, rule):
    """What one transcript row is, as a turn: "person", "notification", "other", or None when it is not a
    `user` row of the main chain at all. ONE classifier for the wait time (`human_wait`) and for the turn that
    opens an activity (`start_turn_activities`) (AR-13).

    - `isSidechain` -> None (a role's own rows are not the main chain).
    - a flag of `rule["flags"]` set (`isMeta`, `isCompactSummary`) -> "other". A slash command is `isMeta` on
      one of its rows, and its `<command-message>` row is the person's: that one is "person".
    - a content block that is a `tool_result` -> "other" (the host answering a tool, never the person).
    - the text (a string, or the first text block of a list) starting with a prefix of
      `rule["notification_prefixes"]` -> "notification".
    - any other non-empty text -> "person". Content that is neither a string nor a list, a list with no text,
      an empty text -> "other".
    Error direction: this judges who is paid for and how long the person waited, so every doubt is "other"."""
    if not isinstance(rec, dict) or rec.get("type") != "user" or rec.get("isSidechain"):
        return None
    if any(rec.get(flag) for flag in rule["flags"]):
        return "other"
    message = rec.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):
        blocks = [b for b in content if isinstance(b, dict)]
        if any(b.get("type") == "tool_result" for b in blocks):
            return "other"
        text = next((b.get("text") for b in blocks if b.get("type") == "text"), None)
    else:
        text = content
    if not isinstance(text, str) or not text.strip():
        return "other"
    if any(text.lstrip().startswith(prefix) for prefix in rule["notification_prefixes"]):
        return "notification"
    return "person"


def _close_questions(rec, ts, question_open, questions):
    """A main-chain user row whose content holds a `tool_result` for an open question closes it: the pair
    `(asked, answered)` goes to `questions["spans"]`. The id leaves `question_open` on the first result, so a
    repeated result closes nothing (one question, one span: E-C3). A result before its call is unknown to us."""
    if not question_open:
        return
    message = rec.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    for block in (content if isinstance(content, list) else []):
        if isinstance(block, dict) and block.get("type") == "tool_result":
            asked = question_open.pop(str(block.get("tool_use_id")), None)
            if asked is not None:
                questions["spans"].append((asked, ts))


def scan_file(path: Path, own_chain: bool = True, forms=None, problems=None, counts=None, person_rule=None,
              questions=None):
    """One transcript -> (usage by requestId, tool calls, task markers, main-chain events).

    main-chain events: `(ts, "assistant" | "human" | "notification")`. "human" is a row `user_line_kind` calls a
    person's, "notification" a background task's; with `person_rule` False (the host forms are unreadable) the
    old predicate stands: a `user` row with a `promptId` is "human". `person_rule` None = read it now
    (`_person_rule`); the callers that scan several files pass the one they read.

    usage by requestId: {key: (model, usage, ts)}. A request read as ONE record (no `usage.iterations`
    carrier) is the key `<id>`; a request served by a model fallback has one entry per iterations part, the
    anchor under `<id>` and the others under `<id>|<model>` (`#<position>` for a repeated model) -- the
    tuple shape is unchanged, only the keys gain the suffix (FR-14). The rule: see `_iteration_parts`.

    questions: an optional dict owned by the caller: "spans" gets `(asked_ts, answered_ts)` for every question
    the person answered (a SEPARATE list, so the event tuples keep their shape: FR-14), "open" holds the calls
    still unanswered as `{tool_use_id: asked_ts}` and may be seeded by the caller (a chunk scan continues the
    previous chunk's open questions).

    counts: an optional dict owned by the caller, for ONE scan: "bad_iterations" (+1 per line whose
    iterations were malformed and ignored), "split_missing_keys" (the request ids with a carrier part that
    has no 1-hour split) and "split_missing" (their number); a key appears only when it is non-zero.

    forms: the external-agent form rows (`external_forms`) a shell command is matched against;
    None = the package's own rows (`problems` gets the data's problem, if any). A call is left in
    `tools` under an `__external__:` key.

    own_chain: True when every row in `path` belongs to the chain being priced (the main
    transcript's own turns, or — since TP1-15045 — a dedicated
    subagents/agent-*.jsonl file, where current Claude Code tags every single row
    isSidechain: true because the whole file IS a sidechain relative to the parent). False
    is for scanning the main transcript for its OWN spend: rows it did not originate (a
    child's turns replayed inline, if a host ever does that again) must not be double-billed
    with the child's dedicated file, so isSidechain rows are excluded there. Before this fix
    `scan_file` always excluded isSidechain usage, which zeroed every agent's tokens/cost
    (agents[] showed the six b156530d subagents at 146 requests / 12.83M tokens actually
    spent, reported as 0) because every row of an agent file carries that flag by design.
    """
    forms = _resolve_forms(forms, problems)
    person_rule = _person_rule() if person_rule is None else person_rule
    counts = {} if counts is None else counts
    # Question waits: a main-chain call of a `claude.person_question_tools` tool is open until the user row that
    # carries its `tool_result` (matched by the call's id). With no rule, or no tool in it, nothing is opened.
    question_tools = set((person_rule or {}).get("question_tools") or ()) if person_rule else set()
    questions = {"spans": [], "open": {}} if questions is None else questions
    question_open = questions.setdefault("open", {})   # tool_use id -> asked ts; a chunk scan is seeded with the previous one's
    questions.setdefault("spans", [])
    folds: dict = {}   # request id -> the fold of its passing lines (`_fold_request`)
    tools: dict = {}
    markers: list = []  # (ts, task) — task boundaries from the workflow
    main_events: list = []  # (ts, 'assistant'|'human'|'notification') — for human wait and the turn that opens an activity
    first_ts = last_ts = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        ts = parse_ts(rec.get("timestamp"))
        if ts:
            first_ts = min(first_ts, ts) if first_ts else ts
            last_ts = max(last_ts, ts) if last_ts else ts
        if rec.get("type") == "assistant":
            msg = rec.get("message") or {}
            usage, model = msg.get("usage"), msg.get("model") or "?"
            rid = rec.get("requestId") or rec.get("uuid")
            if usage and rid and model != "<synthetic>" and (own_chain or not rec.get("isSidechain")):
                folds[rid] = _fold_request(folds.get(rid), model, usage, ts, counts)
            for b in (msg.get("content") or []) if isinstance(msg.get("content"), list) else []:
                if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                    continue
                name = b.get("name", "?")
                tools[name] = tools.get(name, 0) + 1
                if name in question_tools and not rec.get("isSidechain") and ts and b.get("id"):
                    question_open.setdefault(str(b["id"]), ts)
                command = str((b.get("input") or {}).get("command", "")) if name in ("Bash", "PowerShell") else ""
                for form, consumer in _external_hits(command, forms):
                    invocation_id = str(b.get("id") or rec.get("uuid") or rec.get("requestId") or "unknown")
                    identity = form["id"] + "~" + content_hash(invocation_id)[:24]
                    safe_key = (EXTERNAL_PREFIX + identity + ":" + (consumer or NO_CONSUMER) + ":"
                                + (ts.isoformat() if ts else "unknown"))
                    tools[safe_key] = 1
                task = None
                if name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
                    # writing task artifacts is a strong marker; reading is not (reading someone
                    # else's artifacts mid-task should not cut the timeline)
                    task = task_from_path(str((b.get("input") or {}).get("file_path", "")))
                elif name in ("Bash", "PowerShell"):
                    cmd = str((b.get("input") or {}).get("command", ""))
                    if "log_append" in cmd:
                        m = TASK_FLAG.search(cmd)
                        task = m.group(1) if m else None
                if task and ts:
                    markers.append((ts, task))
            if not rec.get("isSidechain") and ts:
                main_events.append((ts, "assistant"))
        elif rec.get("type") == "user" and not rec.get("isSidechain") and ts:
            _close_questions(rec, ts, question_open, questions)
            if person_rule:
                kind = {"person": "human", "notification": "notification"}.get(user_line_kind(rec, person_rule))
            else:
                kind = "human" if rec.get("promptId") else None
            if kind:
                main_events.append((ts, kind))
    return _usage_rows(folds, counts), tools, sorted(markers), first_ts, last_ts, main_events


def scan_file_incremental(path: Path, prior=None, prior_usage=None, own_chain: bool = True, forms=None,
                          problems=None, person_rule=None):
    """Incrementally scan complete JSONL records; rebuild after truncation or replacement, or when
    the checkpoint was made with other external-agent forms (`forms_fingerprint`; a checkpoint with
    no fingerprint, made before it existed, is such a case: one rebuild, then steady), or with another
    reading of who the person is (`person_forms`: the fingerprint of `claude.not_a_person_turn`, or
    `PERSON_FORMS_LEGACY` when the rule was unreadable; the turn events live in the checkpoint, so a
    checkpoint of another rule keeps events of the other rule: HF7-4), or by another
    usage reader (`READER_STAMP`: a checkpoint of the reader that did not know `usage.iterations` is
    rebuilt once, so a live session's fallback request is read whole by the new rule; a finished
    session's file is not scanned again at all, `capture_key`)."""
    from codex_usage import metadata, scan
    if metadata(path):
        return scan(path)
    forms = _resolve_forms(forms, problems)
    scanned_with = forms_fingerprint(forms)
    person_rule = _person_rule() if person_rule is None else person_rule
    person_forms = content_hash(person_rule) if person_rule else PERSON_FORMS_LEGACY
    prior = prior if isinstance(prior, dict) else {}
    stat = path.stat()
    identity = f"{stat.st_dev}:{stat.st_ino}"
    offset = int(prior.get("offset", 0) or 0)
    rebuild = (prior.get("identity") != identity or stat.st_size < offset or prior.get("forms") != scanned_with
               or prior.get("person_forms") != person_forms or prior.get("reader") != READER_STAMP)
    # The usage-lost guard (CD1-13, H1): the checkpoint says the first `offset` bytes were read and holds the tools
    # or turn events found in them, yet the ledger the caller passes for this stream has no request. The usage of
    # that part is not recoverable from the checkpoint (it keeps no request rows), and carrying on would price the
    # file at zero while its tools survive. Re-read from 0. A file that legitimately has no usage row yet is read
    # again until one appears: the guard errs toward re-reading, never toward losing usage (E-C7). A checkpoint
    # that counted the requests it read (`requests_seen`) says whether usage existed at all: 0 = a file with no
    # usage so far, nothing can be lost, no re-read (a transcript of tool calls only stays steady); an older
    # checkpoint with no count cannot say, so it is judged by the tools and events alone.
    prior_state = prior.get("state") if isinstance(prior.get("state"), dict) else {}
    seen = prior_state.get("requests_seen")
    usage_lost = (not rebuild and offset > 0 and not prior_usage and (seen is None or seen > 0)
                  and bool(prior_state.get("tools") or prior_state.get("events")))
    rebuild = rebuild or usage_lost
    if rebuild: prior_usage = []
    state = {} if rebuild else dict(prior.get("state") or {})
    legacy_partial = prior.get("partial", "")
    partial = b"" if rebuild or isinstance(legacy_partial, dict) else str(legacy_partial).encode("utf-8")
    if rebuild: offset = 0
    with path.open("rb") as stream:
        stream.seek(offset); chunk = stream.read(); new_offset = stream.tell()
    data = partial + chunk
    pieces = data.split(b"\n")
    trailing = pieces.pop() if data and not data.endswith(b"\n") else b""
    lines = [x.decode("utf-8",errors="replace") for x in pieces if x.strip()]
    # Reuse the canonical parser on only the appended complete records, then merge facts.
    import tempfile
    counts: dict = {}
    # question calls left open by the previous chunks continue into this one (stored as ISO text in the checkpoint)
    questions = {"spans": [], "open": {k: parse_ts(v) for k, v in (state.get("question_open") or {}).items() if parse_ts(v)}}
    if lines:
        temp = Path(tempfile.gettempdir()) / ("qa-cost-tail-" + uuid.uuid4().hex + ".jsonl")
        try:
            temp.write_text("\n".join(lines)+"\n",encoding="utf-8")
            usage,tools,markers,first,last,events=scan_file(temp, own_chain, forms, counts=counts, person_rule=person_rule,
                                                            questions=questions)
        finally:
            try: temp.unlink()
            except OSError: pass
    else:
        usage,tools,markers,first,last,events={}, {}, [], None, None, []
    # Usage already lives in requests[]; checkpoints retain offsets and compact non-usage
    # parser state instead of duplicating the request ledger in memory/on disk.
    saved_usage = {r["request_id"]:[r["model_id"],{
        "input_tokens":r.get("usage",{}).get("input",0),"output_tokens":r.get("usage",{}).get("output",0),
        "cache_read_input_tokens":r.get("usage",{}).get("cache_read",0),
        "cache_creation_input_tokens":r.get("usage",{}).get("cache_write_5m",0)+r.get("usage",{}).get("cache_write_1h",0),
        "cache_creation":{
            "ephemeral_5m_input_tokens":r.get("usage",{}).get("cache_write_5m",0),
            "ephemeral_1h_input_tokens":r.get("usage",{}).get("cache_write_1h",0)}},r.get("timestamp")]
        for r in (prior_usage or []) if r.get("request_id") and r.get("model_id")}
    _merge_usage(saved_usage, usage)
    _carry_reader_counts(state, counts)
    saved_tools = state.setdefault("tools", {})
    for name,count in tools.items(): saved_tools[name]=saved_tools.get(name,0)+count
    state.setdefault("markers", []).extend([[ts.isoformat(),task] for ts,task in markers])
    state.setdefault("events", []).extend([[ts.isoformat(),kind] for ts,kind in events])
    state["requests_seen"] = int(state.get("requests_seen") or 0) + len(usage)   # the H1 guard reads it next time
    state.setdefault("question_spans", []).extend([[a.isoformat(),b.isoformat()] for a,b in questions["spans"]])
    state["question_open"] = {k: v.isoformat() for k, v in questions["open"].items()}
    candidates=[parse_ts(state.get("first")),first]
    state["first"]=(min(x for x in candidates if x) if any(candidates) else None)
    candidates=[parse_ts(state.get("last")),last]
    state["last"]=(max(x for x in candidates if x) if any(candidates) else None)
    state["first"] = state["first"].isoformat() if state["first"] else None
    state["last"] = state["last"].isoformat() if state["last"] else None
    state.pop("usage",None)
    # Do not persist transcript fragments: the next read resumes at the incomplete line.
    safe_offset = new_offset-len(trailing)
    checkpoint={"identity":identity,"offset":safe_offset,"forms":scanned_with,"person_forms":person_forms,"reader":READER_STAMP,
                "partial":{"bytes":len(trailing),"sha256":content_hash(trailing.hex()) if trailing else None},
                "state":state}
    return ({rid:(v[0],v[1],parse_ts(v[2])) for rid,v in saved_usage.items()},saved_tools,
            sorted((parse_ts(x[0]),x[1]) for x in state["markers"]),parse_ts(state["first"]),
            parse_ts(state["last"]),[(parse_ts(x[0]),x[1]) for x in state["events"]],checkpoint)


def task_at(markers: list, ts):
    """Return the last explicit task marker; never charge setup to the first story."""
    if not markers:
        return "(no task)"
    if ts is None:
        return "(no task)"
    current = "(no task)"
    for m_ts, m_task in markers:
        if m_ts <= ts:
            current = m_task
        else:
            break
    return current


EXTERNAL_STATUSES = {"pending", "available", "unavailable"}


def merge_external_calls(existing, incoming):
    """Upsert sanitized remote-consumer facts by external_call_id."""
    by_id = {x.get("external_call_id"): dict(x) for x in existing or []
             if isinstance(x, dict) and x.get("external_call_id")}
    for raw in incoming or []:
        if not isinstance(raw, dict) or not raw.get("external_call_id"):
            continue
        status = raw.get("usage_status", "pending")
        if status not in EXTERNAL_STATUSES:
            raise ValueError("external usage_status must be pending, available or unavailable")
        safe = {k: raw.get(k) for k in ("external_call_id", "consumer_agent",
            "invocation_method", "purpose", "task", "dispatch_id", "provider",
            "service", "usage_status", "remote_receipt_ref", "request_id",
            "cost_usd", "currency", "observed_at", "reason") if raw.get(k) is not None}
        if not safe.get("consumer_agent") or not safe.get("invocation_method"):
            raise ValueError("external call requires consumer_agent and invocation_method")
        if status == "available" and not safe.get("remote_receipt_ref"):
            raise ValueError("available external call requires remote_receipt_ref")
        by_id[safe["external_call_id"]] = {**by_id.get(safe["external_call_id"], {}), **safe}
    return sorted(by_id.values(), key=lambda x: x["external_call_id"])


def external_reconciliation(calls, forms_problem="", forms=None):
    """The external side of the price. `recognized_forms` names the agent forms the calls were
    counted for: a call of an agent in none of them is a shell command like any other, so a
    reader sees what is NOT counted by what is. `forms_problem` (unreadable data, a refused or
    unmatched row) makes `complete` False: the price is then a range, never one figure (P18)."""
    own = []
    rows = _resolve_forms(forms, own)   # no rows passed: the package's, and the problem with that data travels
    forms_problem = "; ".join(p for p in (forms_problem, *own) if p)
    known = [Decimal(str(x["cost_usd"])) for x in calls
             if x.get("usage_status") == "available" and x.get("cost_usd") is not None]
    unknown = [x for x in calls if x.get("usage_status") != "available" or x.get("cost_usd") is None]
    out = {"known_external_subtotal_usd": str(sum(known, Decimal("0"))),
           "unknown_external_calls": len(unknown), "complete": not unknown and not forms_problem,
           "recognized_forms": [form["id"] for form in rows],
           "dimensions": {"local_provider_requests": "session requests ledger",
                          "remote_consumers": "external_calls", "subscription_or_invoice": "not inferred",
                          "infrastructure": "not inferred", "human": "time only; not converted to USD"}}
    if forms_problem:
        out["forms_problem"] = forms_problem
    return out


def inferred_external_calls(tools, markers, task_hint=None, forms=None, problems=None):
    """The pending calls named by the `__external__:` keys a scan left in `tools` (popped). A key
    with no `~` names no form (a checkpoint older than the form rows) and a key whose form is in no
    row is a form with no row: each still becomes a call, and is named in `problems` (a list the
    caller owns): never lost."""
    rows = {form["id"]: form for form in _resolve_forms(forms, problems)}
    calls=[]
    for key in list(tools):
        if not key.startswith(EXTERNAL_PREFIX): continue
        _,identity,consumer,stamp=key.split(":",3)
        form_id, tilde, tail = identity.partition("~")
        form_id, identity = (form_id, tail) if tilde else (UNMARKED_FORM, identity)
        form = rows.get(form_id)
        if form is None:
            if problems is not None:
                problems.append(f"an external call of form {form_id!r} was found but no form row has that id")
            form = {"call_id_prefix": form_id, "invocation_method": f"{form_id} (no form row)",
                    "provider": None, "service": None,
                    "unknown_consumer_label": f"external agent {form_id} (no form row)"}
        label = consumer if consumer != NO_CONSUMER else form["unknown_consumer_label"]
        calls.append({"external_call_id":form["call_id_prefix"]+":"+identity,"consumer_agent":label,
            "invocation_method":form["invocation_method"],"task":task_hint or task_at(markers,parse_ts(stamp)),
            "provider":form["provider"],"service":form["service"],"usage_status":"pending",
            "observed_at":stamp if stamp!="unknown" else None,
            "reason":"Remote usage receipt was not present in the host transcript"})
        tools.pop(key,None)
    return calls


def activity_at(activities, ts):
    return activity_binding(activities, ts)[0]


def _segment_id(activity_id, segment):
    """The id of an activity segment: its own, else the hash of its activity and start event. The one
    formula of `activity_binding`, `attribution_activities` and `sticky_activity_binding` (AR-15)."""
    return segment.get("segment_id") or content_hash(
        {"activity_id": activity_id, "start_event_id": segment.get("start_event_id")})[:24]


def activity_binding(activities, ts):
    for item in activities:
        for segment in item.get("segments") or []:
            start, end = parse_ts(segment.get("start_time")), parse_ts(segment.get("end_time"))
            if ts is not None and start and start <= ts and (end is None or ts < end):
                return item["activity_id"], _segment_id(item["activity_id"], segment)
    return "unclassified", "unclassified"


def attribution_activities(activities):
    """(activities for binding, kept) - the activity list with every STOP-RESUMED window of a
    non-story activity taken out, and `{activity_id: [segment_id, ...]}` of the such windows that
    were kept (a story's Stop-pop opens a new segment for its parent at the Stop event; in that
    window the parent would swallow every later turn of the story).

    A segment S of activity P is a Stop-resumed window when P is not a story and another
    activity C is a story whose `end_event_id` starts with "stop:" (written by
    `activity_capture.close_pending` and `activity_capture.main`) and S starts at that very event.
    It is removed when it is open or was closed by another start; it is KEPT, and listed, when P's
    OWN end closed it. Error direction of that keep: the parent's own end proves where its window
    ENDS, not where it began, so the story's turns inside a kept window stay the parent's; the
    price names them (`task_price._open_parent_rows`) instead of showing one exact figure.

    Never mutates the input, never raises: a non-list gives ([], {}); an item that is not a dict
    or has no `segments` list is passed through unchanged; other segments are kept byte-equal."""
    if not isinstance(activities, list):
        return [], {}
    stops = {c["end_event_id"] for c in activities
             if isinstance(c, dict) and c.get("type") == "story" and isinstance(c.get("end_event_id"), str)
             and c["end_event_id"].startswith("stop:")}
    out, kept = [], {}
    for p in activities:
        if not stops or not isinstance(p, dict) or not isinstance(p.get("segments"), list) \
                or p.get("type") == "story":
            out.append(p)
            continue
        own_end = p.get("end_event_id")
        segments = []
        for s in p["segments"]:
            start = s.get("start_event_id") if isinstance(s, dict) else None
            if not (isinstance(start, str) and start in stops):
                segments.append(s)
                continue
            end = s.get("end_event_id")
            if isinstance(end, str) and end == own_end:   # the parent's own end closed it: keep, and list
                kept.setdefault(p.get("activity_id"), []).append(_segment_id(p.get("activity_id"), s))
                segments.append(s)
        q = dict(p)
        q["segments"] = segments
        out.append(q)
    return out, kept


def sticky_activity_binding(activities, ts):
    """Like `activity_binding`, but a gap between two segments of the SAME STORY — with no
    other activity's segment between them — belongs to that story, and so does the tail
    after the whole session's last segment ("sticky attribution"). Without this, a
    dollar spent in the gap the orchestrator opens before every stop
    (`activity_capture.py --action end --after-response`, closed while the person answers,
    reopened only on the NEXT explicit marker) belongs to nobody: on TP1-15045 (session
    57cf578c) three of five role dispatches opened with their first request inside exactly
    such a gap and were billed "(no task)" though the story never actually stopped.

    Restricted to `type == "story"`: doctor/onboarding silence must keep reading
    "unclassified", exactly as before this fix — test_codex_host.py's
    test_reviewed_historical_import_is_idempotent_and_keeps_gaps pins a doctor run's tail
    staying Unclassified, and a regression here doubled its Doctor bucket. A gap or tail
    whose nearest earlier segment is NOT a story, or whose nearest later segment belongs to
    a DIFFERENT activity, is not resolved here — nobody uniquely owns it — and stays
    "unclassified", same as before.

    One widening (TP1-14857): a skill re-entry makes a NEW story activity of the same task,
    so the gap between two story activities that name the SAME non-empty task belongs to that
    task; a gap to a story of another task, or one with no task, stays "unclassified"."""
    if ts is None:
        return "unclassified", "unclassified"
    segments = []
    for item in activities:
        if not isinstance(item, dict):
            continue
        aid = item.get("activity_id")
        atype = item.get("type")
        for segment in item.get("segments") or []:
            start = parse_ts(segment.get("start_time"))
            if start is None:
                continue
            end = parse_ts(segment.get("end_time"))
            segments.append((start, end, aid, _segment_id(aid, segment), atype, item.get("task")))
    segments.sort(key=lambda x: x[0])
    for start, end, aid, sid, _atype, _task in segments:
        if start <= ts and (end is None or ts < end):
            return aid, sid
    closed = [s for s in segments if s[1] is not None]
    before = [s for s in closed if s[1] <= ts]
    after = [s for s in segments if s[0] > ts]
    prev = max(before, key=lambda s: s[1]) if before else None
    nxt = min(after, key=lambda s: s[0]) if after else None
    if prev:
        _, _, p_aid, p_sid, p_type, p_task = prev
        if p_type == "story" and (nxt is None or nxt[2] == p_aid):
            return p_aid, p_sid
        if p_type == "story" and isinstance(p_task, str) and p_task:
            _, _, _, _, n_type, n_task = nxt
            if n_type == "story" and n_task == p_task:
                return p_aid, p_sid
    return "unclassified", "unclassified"


def sticky_activity_at(activities, ts):
    return sticky_activity_binding(activities, ts)[0]


def merge_spans(spans):
    """The question spans as sorted, non-overlapping `(start, end)` pairs: two questions open at once are one
    stretch of the person's time, counted once (total <= wall time, E-C4)."""
    merged = []
    for start, end in sorted((a, b) for a, b in spans or () if a and b and b > a):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def human_wait(main_events, activities, cap, question_spans=None, waits_out=None):
    """Seconds the person took to answer, and how many answers, from `main_events` `(ts, kind)`.

    Only a "human" event is an answer. A "notification" (a background task reporting back) is never the person
    coming back, and neither is anything else that is not "assistant" or "human": it is skipped, so it is
    neither a wait nor a new starting point (HF7-4; before, every non-assistant event counted).

    `question_spans` `[(asked, answered)]`: the time a question put to the person stood open. It is summed
    UNCAPPED (the cap bounds a guess at a turn gap, a question's span is measured; the cap value is unchanged),
    and the part of a turn gap that lies inside a question span is NOT counted again. `interactions` still
    counts turn answers only. `waits_out`, a list owned by the caller, gets one dict per counted wait:
    `{"start", "end", "seconds", "kind": "question"|"turn"}` (a turn's `seconds` is what was counted, after the
    cap and the overlap)."""
    spans = merge_spans(question_spans)
    total, interactions, previous = 0.0, 0, None
    for start, end in spans:
        seconds = (end - start).total_seconds()
        total += seconds
        if waits_out is not None:
            waits_out.append({"start": start.isoformat(), "end": end.isoformat(), "seconds": round(seconds), "kind": "question"})
    for ts, kind in sorted(main_events):
        if kind not in ("assistant", "human"):
            continue
        binding = activity_binding(activities, ts)
        if kind == "assistant":
            previous = (ts, binding)
        elif previous:
            gap = (ts - previous[0]).total_seconds()
            if gap > 1 and binding == previous[1]:
                overlap = sum(max(0.0, (min(end, ts) - max(start, previous[0])).total_seconds()) for start, end in spans)
                counted = min(max(gap - overlap, 0.0), cap)
                total += counted
                interactions += 1
                if waits_out is not None and counted > 0:
                    waits_out.append({"start": previous[0].isoformat(), "end": ts.isoformat(), "seconds": round(counted), "kind": "turn"})
    return total, interactions


def start_turn_activities(activities, events):
    """The activity list in which each activity's FIRST segment also owns the turn that started it.

    The orchestrator opens an activity with `activity_capture.py --action start` partway through a turn:
    the person's message and the orchestrator's first requests come BEFORE the start event, and used to be
    nobody's ("Unclassified") though that turn is what the activity was started for. For every activity of a
    real type (not "unclassified") its first segment (the earliest start) begins at
    `max(the last turn opener <= its start_time, the end of the latest recorded segment of any activity that
    ended <= its start_time)`. An opener is a "human" event, or a "notification" event (a turn begun by a
    background task is a turn, F-16).

    Edges, each tested: no opener at or before the start -> unchanged (Codex, `claude -p`); an opener AFTER the
    start is never used; a segment of another activity that is still open, or ends after the start (a nested
    start: the parent's segment is closed AT the child's start, so this reads as "the parent ends here") is a
    boundary the new start never crosses; only the first segment moves (resumed segments are as recorded); a
    segment or time that cannot be read changes nothing; two activities started in one turn: the second one's
    boundary is the first one's recorded segment, so it is never widened over it (when the first is still open
    or ends where the second starts, not at all).
    INVARIANT: a request inside a RECORDED segment of any activity keeps its owner (the new start is never
    inside another recorded segment), and a turn that started no activity is not touched. The input is never
    mutated; the answer is ONE list for the requests, the roles, `by_activity` and `human_wait` (AR-15).
    Position at the call: after `attribution_activities`, before any request is bound."""
    if not isinstance(activities, list):
        return activities
    openers = []
    for event in events or []:
        try:
            ts, kind = event
        except (TypeError, ValueError):
            continue
        if kind in ("human", "notification") and isinstance(ts, datetime):
            openers.append(ts)
    if not openers:
        return list(activities)
    segments = []   # (item index, segment index, start, end or None) of every segment that has a readable start
    for i, item in enumerate(activities):
        if isinstance(item, dict) and isinstance(item.get("segments"), list):
            for j, segment in enumerate(item["segments"]):
                start = parse_ts(segment.get("start_time")) if isinstance(segment, dict) else None
                if start is not None:
                    segments.append((i, j, start, parse_ts(segment.get("end_time"))))
    out = list(activities)
    try:
        for i, item in enumerate(activities):
            if not isinstance(item, dict) or item.get("type") == "unclassified":
                continue
            own = [s for s in segments if s[0] == i]
            if not own:
                continue
            first = min(own, key=lambda s: s[2])
            start = first[2]
            before = [o for o in openers if o <= start]
            if not before:
                continue
            floor = None
            for other in segments:
                if (other[0], other[1]) == (first[0], first[1]) or other[2] > start:
                    continue
                if other[3] is None or other[3] > start:
                    floor = start          # still open, or ending after the start: the turn is inside it
                    break
                floor = other[3] if floor is None else max(floor, other[3])
            new = max(before) if floor is None else max(max(before), floor)
            if new >= start:
                continue
            moved = dict(item)
            moved["segments"] = [dict(s, start_time=new.isoformat()) if k == first[1] else s
                                 for k, s in enumerate(item["segments"])]
            out[i] = moved
    except TypeError:   # a naive and an aware time cannot be ordered: nothing is moved (the safe side)
        return list(activities)
    return out


def incomplete_roles(agents, journal_records, session_id) -> list:
    """The roles whose usage is missing from a session: `[{"agent", "missing", "seen_at"}]`.

    Two kinds of gap, one list. (1) An `agents[]` entry with `tokens == 0` (a transcript the scan
    found but read no usage from): one element per name as `agentType` spells it, `missing` = such
    files, `seen_at` empty (the file itself is the place). (2) A `subagent_stop` line of this session
    the files do not cover: the lines are grouped by `role_name` of the journal's bare name, the
    distinct `dispatch` ids of a role (a line with no dispatch counts as its own) are set against the
    files of the same `role_name` that carry usage; an excess is an element named AS THE JOURNAL
    spells it, `missing` = the excess, `seen_at` = the `ts` of every line of that role.

    One role in two spellings (`qa-factory:qa-scout` in the file, `qa-scout` in the journal) is one
    role: the comparison goes through `hooklib.role_name` on BOTH sides (AR-5, AR-13). Direction of
    the error: `role_name` is a lookup normaliser that here judges "has usage", so it may err only
    toward naming a gap. A repeated dispatch id (a retry after a refusal) counts once: a gap can be
    missed there, never invented. A line that is not an object, another session's, nameless, or whose
    name has an empty tail (`qa-factory:`) is skipped one by one."""
    out = []
    zero = {}
    covered = {}
    for item in agents if isinstance(agents, list) else []:
        if not isinstance(item, dict) or not item.get("agent"):
            continue
        name = str(item["agent"])
        if item.get("tokens"):
            covered[role_name(name)] = covered.get(role_name(name), 0) + 1
        else:
            zero[name] = zero.get(name, 0) + 1
    out.extend({"agent": name, "missing": n, "seen_at": []} for name, n in zero.items())
    roles: dict = {}
    for rec in journal_records if isinstance(journal_records, list) else []:
        if not (isinstance(rec, dict) and rec.get("event") == "subagent_stop" and rec.get("session") == session_id
                and isinstance(rec.get("agent"), str) and rec["agent"]):
            continue
        role = role_name(rec["agent"])
        if not role:
            continue
        entry = roles.setdefault(role, {"agent": rec["agent"], "dispatches": 0, "named": set(), "seen_at": []})
        dispatch = rec.get("dispatch")
        if dispatch in (None, "") or isinstance(dispatch, (dict, list)):
            entry["dispatches"] += 1
        elif str(dispatch) not in entry["named"]:
            entry["named"].add(str(dispatch))
            entry["dispatches"] += 1
        if isinstance(rec.get("ts"), str):
            entry["seen_at"].append(rec["ts"])
    for role, entry in roles.items():
        excess = entry["dispatches"] - covered.get(role, 0)
        if excess > 0:
            out.append({"agent": entry["agent"], "missing": excess, "seen_at": entry["seen_at"]})
    return out


def _journal_records(event) -> list:
    """The parsed lines of the project's journal, one by one: a line that is not JSON is skipped
    alone (it used to end the whole read). No journal file = a session of no factory, no word; a
    journal that exists and cannot be opened is one stderr line, because roles with no transcript
    then go unchecked (FR-41)."""
    path = RP.configured(project_root(event), load_config(event).get("journal_path"), "journal.jsonl")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, NotADirectoryError):
        return []
    except OSError:
        print("cost_capture: the journal could not be read; roles with no transcript were not checked", file=sys.stderr)
        return []
    out = []
    for line in text.splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _gap_places(roles, activities) -> list:
    """`incomplete_where` of a cost file: for each journal gap of `incomplete_roles` (an element with
    `seen_at`) its name, the activities its lines fall in (`sticky_activity_at`, no repeats) and the
    number missing. A gap with a file keeps its place in `agents[]`, so it is not written here."""
    out = []
    for item in roles:
        if not item["seen_at"]:
            continue
        places = []
        for ts in item["seen_at"]:
            try:
                aid = sticky_activity_at(activities, parse_ts(ts))
            except (TypeError, ValueError):
                aid = "unclassified"
            if aid not in places:
                places.append(aid)
        out.append({"agent": item["agent"], "activities": places, "missing": item["missing"]})
    return out


def _session_scope_ok(event, tpath: Path) -> bool:
    """True when this hook may write cost data for the session whose transcript is `tpath`: the project
    is onboarded and the session is this project's. The one carrier of these two tests (AR-13): `_capture`
    asks it before anything is written, `_mark_started` before the "started" marker, which is written
    BEFORE the lock and so before `_capture` runs. The invariant: the hook never creates `qa-factory/`
    in a project that is not onboarded, nor writes into a foreign project.
    - Not onboarded: no `config.json`, so no `qa-factory/` to write cost data into.
    - A session opened ABOVE this project (factory development in `D:/ws3`, with the project two
      directories down) fires this project's hooks, and until 0.7.15 the capture wrote its cost file here:
      8 foreign sessions in TP1-15045's state/cost, 273 MB of transcripts read on every dashboard
      build. The transcript path says where the session was opened; "unknown" (Codex writes no project
      folder) keeps writing, as before. Files already written are left alone - the dashboard shows
      them as their own section."""
    if not (state_dir(event) / "config.json").exists():
        return False
    return bool(event.get("recapture_explicit")) or session_belongs_to(
        {"transcript": str(tpath)}, project_slug(project_root(event))) != "parent"


def _capture(event) -> bool:
    """Capture one session's cost. True when it ran to the end (the caller then runs
    `_after_capture` outside its lock); a session that is not this project's, or a project that
    is not onboarded, leaves through `sys.exit(0)` before anything is written, as ever."""
    capture_started = time.time()
    tpath = Path(event.get("transcript_path", "") or "")
    session_id = event.get("session_id", "") or tpath.stem
    if not tpath.is_file() or any(c in session_id for c in "/\\:") or session_id in (".", ".."):
        sys.exit(0)
    if not _session_scope_ok(event, tpath):
        sys.exit(0)

    cfg = (load_config(event).get("cost") or {})
    prices = cfg.get("model_prices") or {}
    catalogue = load_catalogue()
    wait_cap = float(cfg.get("human_wait_cap_s", 1800))
    forms, forms_problem = external_forms(cfg.get("external_agent_forms"))
    form_problems = [forms_problem] if forms_problem else []   # grows with calls of a form no row names
    person_rule = _person_rule()    # read ONCE for every file of this capture: one stderr line when unreadable (HF7-4)

    sub_dir = tpath.parent / tpath.stem / "subagents"
    files = [tpath] + (sorted(sub_dir.glob("agent-*.*")) if sub_dir.exists() else [])
    from activity_capture import activity_path as resolve_activity_path, close_pending
    from codex_usage import metadata as codex_metadata
    close_pending(event, session_id)
    activity_path = resolve_activity_path(event, session_id)
    activities_doc = {}
    # The hash of the bytes this capture read, kept in the cost file (`activities_hash`): a later
    # freshness check compares content, not a file time (`_stale_kind`). "" = no readable file.
    activities_hash = ""
    try:
        activities_bytes = activity_path.read_bytes()
        activities_hash = hashlib.sha256(activities_bytes).hexdigest()
        activities_doc = json.loads(activities_bytes.decode("utf-8"))
    except (OSError, json.JSONDecodeError):
        activities_doc = {"activities": []}
    activities = activities_doc.get("activities") or []
    activities, stop_kept = attribution_activities(activities)
    # likely_factory decides the SCANNING strategy below, before has_factory_activity (the
    # WRITE-time flag, computed later from by_activity) exists. It is exactly equivalent:
    # by_activity can only ever carry a doctor/onboarding/story type when `activities`
    # already carries one, so a False here guarantees has_factory_activity ends up False too.
    likely_factory = any(isinstance(a, dict) and a.get("type") in ("doctor", "onboarding", "story")
                         for a in activities)
    binding = {}
    if event.get('host_binding'):
        binding = json.loads(Path(event['host_binding']).read_text(encoding='utf-8'))
        if binding.get('activity'):
            # The child's dispatch belongs to its parent's explicit invocation, even after the parent returns.
            inherited = dict(binding['activity'])
            inherited['segments'] = [dict(inherited['segments'][-1], end_time=None)]
            activities = [inherited]
    key_inputs = {"files": [(str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in files],
                  "prices": prices, "catalogue": catalogue.get("catalogue_revision"),
                  "activities": content_hash(activities_doc), "binding": binding, "wait_cap": wait_cap,
                  "usage_complete": event.get("usage_complete") is True, "reader": READER_STAMP,
                  "external_calls": event.get("external_calls") or []}
    if cfg.get("external_agent_forms"):    # a project's own rows change what the file says; absent = key as before
        key_inputs["external_agent_forms"] = cfg["external_agent_forms"]
    capture_key = content_hash(key_inputs)
    output_path = state_dir(event) / "state" / "cost" / f"{session_id}.json"
    previous = {}
    if output_path.exists():
        previous = json.loads(output_path.read_text(encoding="utf-8"))
        # The 30 s debounce window is NOT decided here any more: it was, under the lock and after the
        # whole cost file was parsed and the activity file hashed, so every PostToolUse that the window
        # then turned away had already paid for the work (HF2-9, t-080). `main` asks
        # `_debounce_window_open` before it asks for the lock.
        if previous.get("capture_key") == capture_key:
            # Nothing changed since the capture that wrote this file: it is current, so a marker
            # left by a capture that gave up on the lock is answered too.
            _clear_pending(output_path.parent, session_id, capture_started)
            return
    # An incremental capture keeps the valuation a request was given the first time (history stays
    # pinned: `request_record` reuses it when the model and usage still match). A RECAPTURE is a new
    # capture of the whole session, asked for to repair a file: every request is valued afresh by
    # the current rate rule, so a pin written under the old precedence (session 248a7a20: the
    # legacy family rate, 0.4784169 against the catalogue's 0.3189446) does not survive it.
    prior_requests = {} if event.get("recapture") else {
        r.get("request_key"): r for r in previous.get("requests", [])
        if isinstance(r, dict) and r.get("request_key")}
    external_calls = merge_external_calls(previous.get("external_calls"), event.get("external_calls"))
    prior_scans = previous.get("scan_checkpoints") or {}
    scan_checkpoints = {}

    # --- Orchestrator: main chain of the primary transcript ---
    # A session with no factory activity never gets to replay its own history: the
    # persisted "requests" ledger is collapsed to a per-model carry row at write time below,
    # so seeding scan_file_incremental from it would silently drop every request the offset
    # already skipped past. Force a full, non-incremental rescan instead — the same thing the
    # Codex adapter already does unconditionally for every session, at whatever it costs in
    # CPU (async, debounced) to keep the cost file itself from growing without bound (a real
    # non-factory session left 1.8 MB of per-request rows in the project's state/cost/).
    usage, tools, markers, first_ts, last_ts, main_events, checkpoint = scan_file_incremental(
        tpath, prior_scans.get(str(tpath.resolve())) if likely_factory else None,
        ([r for r in previous.get("requests",[]) if r.get("stream")=="orchestrator"]
         if likely_factory else None), own_chain=False, forms=forms, person_rule=person_rule)
    main_checkpoint = checkpoint
    # the turn that started an activity is the activity's (not for a child dispatch, whose activity is inherited, nor for a Codex rollout, whose "human" rows are unmeasured, nor with no readable person rule)
    activities = start_turn_activities(activities, main_events) if person_rule and not binding.get("activity") and not codex_metadata(tpath) else activities
    scan_checkpoints[str(tpath.resolve())] = checkpoint
    external_calls = merge_external_calls(external_calls, inferred_external_calls(
        tools, markers, forms=forms, problems=form_problems))
    # Snapshot before the agent loop below folds every subagent's tools into `tools`:
    # what the main chain did by itself is the orchestrator's own bill, and on the
    # TP1-13958 pilot the orchestrator was the single largest consumer of the session
    # (318 requests, 52.5M tokens, 47%) with no way to see what it spent them on.
    orch_tools = dict(tools)
    orch_models: dict = {}
    task_models: dict = {}  # task -> model -> agg (timeline segmentation by markers)
    activity_models: dict = {}
    request_records = []
    task_ts: dict = {}      # task -> [main-chain call ts] — for the task-time estimate
    for rid, (model, u, ts) in usage.items():
        add_usage(orch_models.setdefault(model, zero()), u)
        t = task_at(markers, ts)
        aid, segment_id = sticky_activity_binding(activities, ts)
        activity = next((a for a in activities if a.get("activity_id") == aid), {})
        if activity.get('type') == 'story' and activity.get('task'):
            t = activity['task']
        elif event.get('task_id'):
            t = event['task_id']
        add_usage(task_models.setdefault(t, {}).setdefault(model, zero()), u)
        add_usage(activity_models.setdefault(aid, {}).setdefault(model, zero()), u)
        provider = model_provider(model)
        key = f"{provider}:{session_id}:{rid}:orchestrator"
        prior = prior_requests.get(key) or prior_requests.get(f"{provider}:{session_id}:{rid}:{tpath.name}") or prior_requests.get(f"anthropic:{session_id}:{rid}:orchestrator")
        request_records.append(request_record(provider, session_id, rid, "orchestrator",
            model, u, ts, aid, segment_id, t, cfg, catalogue, prior))
        if event.get('dispatch_id'):
            request_records[-1]['dispatch_id'] = event['dispatch_id']
        if ts is not None:
            task_ts.setdefault(t, []).append(ts)

    # Question waits are measured only when the rule names the host's question tool and the transcript is read by
    # this scanner (a Codex rollout keeps no such spans); otherwise the document says `unmeasured` (E-C1).
    main_state = main_checkpoint.get("state") if isinstance(main_checkpoint.get("state"), dict) else {}
    questions_measured = bool(person_rule and person_rule.get("question_tools")) and not codex_metadata(tpath)
    question_spans = [(parse_ts(a), parse_ts(b)) for a, b in main_state.get("question_spans") or []] if questions_measured else []
    human_waits: list = []
    wait_total, interactions = human_wait(main_events, activities, wait_cap, question_spans, human_waits)
    open_questions = len(main_state.get("question_open") or {}) if questions_measured else 0

    # --- Subagents: each call is a separate file + a .meta.json with its name ---
    agents = []
    sub_dir = tpath.parent / tpath.stem / "subagents"
    for af in sorted(sub_dir.glob("agent-*.jsonl")) if sub_dir.exists() else []:
        # Same reasoning as the orchestrator scan above: no replay from a collapsed ledger.
        a_usage, a_tools, a_markers, a_first, a_last, _, checkpoint = scan_file_incremental(
            af, prior_scans.get(str(af.resolve())) if likely_factory else None,
            ([r for r in previous.get("requests",[]) if r.get("stream")==af.name]
             if likely_factory else None), own_chain=True, forms=forms, person_rule=person_rule)
        scan_checkpoints[str(af.resolve())] = checkpoint
        meta = {}
        try:
            meta = json.loads(af.with_name(af.stem + ".meta.json").read_text(encoding="utf-8"))
        except Exception:
            pass
        a_models: dict = {}
        for model, u, _ts in a_usage.values():
            add_usage(a_models.setdefault(model, zero()), u)
        # Task of the agent call: its own markers win (order: own marker, then the
        # ticket its own prompt names, then the activity it ran inside, then "(no task)").
        if a_markers:
            counts: dict = {}
            for _ts, t in a_markers:
                counts[t] = counts.get(t, 0) + 1
            a_task = max(counts.items(), key=lambda kv: kv[1])[0]
        else:
            from hooklib import subagent_meta
            a_task = subagent_meta(af).get("ticket") or "(no task)"
        if a_task == "(no task)":
            # A role dispatched before the story's first artifact write, and with no
            # "Ticket:" line its own prompt named, has no marker to inherit: on
            # TP1-15045 the scout — the most expensive role of the run — was billed to
            # "(no task)". The story activity it ran inside names the task (sticky: a
            # dispatch that opened inside the gap the orchestrator leaves before every stop
            # still belongs to the story surrounding that gap, not to "unclassified").
            owner_aid = meta.get("activity_id") or sticky_activity_at(activities, a_first)
            owner = next((a for a in activities if a.get("activity_id") == owner_aid), {})
            if owner.get("type") == "story" and owner.get("task"):
                a_task = owner["task"]
        external_calls = merge_external_calls(external_calls, inferred_external_calls(
            a_tools, a_markers, a_task, forms=forms, problems=form_problems))
        for t, n in a_tools.items():
            tools[t] = tools.get(t, 0) + n
        a_activity = meta.get("activity_id") or sticky_activity_at(activities, a_first)
        for rid, (model, u, request_ts) in a_usage.items():
            provider = model_provider(model)
            key = f"{provider}:{session_id}:{rid}:{af.name}"
            prior = prior_requests.get(key) or prior_requests.get(f"anthropic:{session_id}:{rid}:{af.name}")
            _aid, segment_id = sticky_activity_binding(activities, request_ts or a_first)
            segment_id = meta.get("activity_segment_id") or segment_id
            request_records.append(request_record(provider, session_id, rid, af.name,
                model, u, request_ts, a_activity, segment_id, a_task, cfg, catalogue, prior))
        for model, agg in a_models.items():
            apply_pinned_valuations(agg, [r for r in request_records
                if r["stream"] == af.name and r["model_id"] == model])
        for m, agg in a_models.items():
            dst = task_models.setdefault(a_task, {}).setdefault(m, zero())
            for k in zero():
                dst[k] += agg[k]
            adst = activity_models.setdefault(a_activity, {}).setdefault(m, zero())
            for k in zero():
                adst[k] += agg[k]
        a_cost = sum(v["cost"] for v in a_models.values() if v.get("cost") is not None)
        a_tokens = sum(sum(v[k] for k in zero() if k != "requests") for v in a_models.values())
        agents.append({
            "agent": meta.get("agentType", af.stem),
            "purpose": (meta.get("description") or "")[:120],
            "task": a_task,
            "activity_id": a_activity,
            "file": af.name,
            "by_model": a_models,
            # Per-dispatch tool histogram (2026-09-15): the session-wide `tools` total
            # cannot say WHAT a marathon spent its turns on, which is the first question
            # asked of every marathon in the retro. scan_file already computed it; it used
            # to be summed away.
            "tools": dict(sorted(a_tools.items(), key=lambda kv: -kv[1])),
            "tokens": a_tokens,
            "cost": round(a_cost, 4) if a_models and all(v.get("cost") is not None for v in a_models.values()) else None,
            "started": a_first.isoformat() if a_first else None,
        })

    # --- Rollup by model (whole session) and sum reconciliation ---
    by_model: dict = {}
    for src in [orch_models] + [a["by_model"] for a in agents]:
        for m, agg in src.items():
            d = by_model.setdefault(m, zero())
            for k in zero():
                d[k] += agg[k]
    for m, agg in by_model.items():
        apply_pinned_valuations(agg, [r for r in request_records if r["model_id"] == m])
    for m, agg in orch_models.items():
        apply_pinned_valuations(agg, [r for r in request_records
            if r["stream"] == "orchestrator" and r["model_id"] == m])

    def total_cost(models: dict):
        vals = [v["cost"] for v in models.values() if v.get("cost") is not None]
        return round(sum(vals), 4) if vals and len(vals) == len(models) else None

    def exact_cost(models: dict):
        vals = [v.get("valuation") or {} for v in models.values()]
        if not vals or any(v.get("pricing_coverage") == "none" for v in vals):
            return None
        return sum((Decimal(str(v.get("subtotal_usd", "0"))) for v in vals), Decimal("0"))

    session_cost = total_cost(by_model)
    orch_cost = total_cost(orch_models)
    agents_cost = round(sum(a["cost"] for a in agents if a["cost"] is not None), 4)
    parts = round((orch_cost or 0) + agents_cost, 4)

    by_task: dict = {}
    for t, models in task_models.items():
        for m, agg in models.items():
            apply_pinned_valuations(agg, [r for r in request_records
                if r["task"] == t and r["model_id"] == m])
        # active_s — the task's pipeline-time estimate: the sum of gaps between adjacent
        # main-chain API calls of its segments, each gap capped at wait_cap (multi-day
        # breaks do not inflate the number). It is NOT machine time: short human waits
        # inside are included; the honest name is "capped wall-clock".
        # machine_s — the task's machine time: the same gaps, but the cap is 120 s — longer
        # gaps (human waits at gates, factory idle) are cut off. The 2026-09-02 measurement:
        # live tasks showed 7-8 h of capped wall-clock vs ~2 h machine — standing dominates,
        # the dashboard shows machine_s (operator's decision 2026-09-02).
        tss = sorted(task_ts.get(t) or [])
        # priced_subtotal_usd (written when model-rates.json lacked claude-fable-5-1; the
        # catalogue lists it now, but any model it does not list yet, or lists without a
        # rate key the usage needs, still leaves that model unpriced): "cost" goes null the
        # moment ONE model in the task is unpriced, same as
        # total_cost_usd — honest, but it also hides a priced model's dollars that ARE known
        # (e.g. a task that mixes a priced model with one the catalogue does not list yet). This
        # is the same exact-subtotal sum already used for the session-wide
        # priced_subtotal_usd, scoped to the task's own models; unpriced categories add 0.
        priced = sum((Decimal(str((v.get("valuation") or {}).get("subtotal_usd", "0")))
                      for v in models.values()), Decimal("0"))
        by_task[t] = {
            "tokens": sum(sum(v[k] for k in zero() if k != "requests") for v in models.values()),
            "requests": sum(v["requests"] for v in models.values()),
            "cost": total_cost(models),
            "priced_subtotal_usd": float(priced),
            "active_s": round(sum(min((b - a).total_seconds(), wait_cap)
                                  for a, b in zip(tss, tss[1:]))) if len(tss) > 1 else None,
            "machine_s": round(sum(min((b - a).total_seconds(), 120)
                                   for a, b in zip(tss, tss[1:]))) if len(tss) > 1 else None,
        }
    by_activity = {}
    activity_index = {a["activity_id"]: a for a in activities if isinstance(a, dict) and a.get("activity_id")}
    for aid, models in activity_models.items():
        for model, agg in models.items():
            apply_pinned_valuations(agg, [r for r in request_records
                if r["activity_id"] == aid and r["model_id"] == model])
        meta = activity_index.get(aid, {})
        segment_seconds = 0.0
        for segment in meta.get("segments") or []:
            start, end = parse_ts(segment.get("start_time")), parse_ts(segment.get("end_time"))
            stamps = sorted(parse_ts(r.get("timestamp")) for r in request_records
                            if r.get("activity_id") == aid and parse_ts(r.get("timestamp")) and
                            start and start <= parse_ts(r.get("timestamp")) and
                            (end is None or parse_ts(r.get("timestamp")) < end))
            segment_seconds += sum(min((b - a).total_seconds(), 120) for a, b in zip(stamps, stamps[1:]))
        by_activity[aid] = {"type": meta.get("type", "unclassified"), "task": meta.get("task"),
                            "status": meta.get("status", "unknown"), "by_model": models,
                            "tokens": sum(sum(v[k] for k in zero() if k != "requests") for v in models.values()),
                            "cost": total_cost(models),
                            "active_s": round(segment_seconds) if segment_seconds else None}
        if stop_kept.get(aid):
            by_activity[aid]["stop_resumed_segments"] = stop_kept[aid]
    tasks_cost = round(sum(v["cost"] for v in by_task.values() if v["cost"] is not None), 4)
    session_exact = exact_cost(by_model)
    parts_exact_values = [exact_cost(orch_models)] + [exact_cost(a["by_model"]) for a in agents]
    parts_exact = None if any(v is None for v in parts_exact_values) else sum(parts_exact_values, Decimal("0"))
    task_exact_values = [exact_cost(models) for models in task_models.values()]
    tasks_exact = None if any(v is None for v in task_exact_values) else sum(task_exact_values, Decimal("0"))
    pricing_complete = bool(by_model) and all(v["valuation"]["pricing_coverage"] == "complete"
                                              for v in by_model.values())
    usage_complete = event.get("usage_complete") is True

    # incomplete_agents (guard against recurrence): a dispatch with zero recorded usage
    # must never again look like a free role or inflate "orchestrator share" to 100% by
    # default. Any agents[] entry the scan above produced with tokens == 0 is one instance
    # of the exact b156530d defect (isSidechain zeroing a found transcript) or any future
    # variant of it. A subagent_stop journal record for this session whose agent never even
    # produced a subagents/agent-*.jsonl to scan is the same failure one step earlier (a
    # dispatch that left no transcript at all) and is folded in here too.
    # The two sides are compared by ROLE (`hooklib.role_name`) and by count, in `incomplete_roles`.
    # The field's shape is unchanged for its readers: the names, once each, first-seen order.
    gap_roles = incomplete_roles(agents, _journal_records(event), session_id)
    incomplete_agents = list(dict.fromkeys(item["agent"] for item in gap_roles))
    incomplete_where = _gap_places(gap_roles, activities)

    # has_factory_activity : a session whose cwd merely sat inside an
    # onboarded project (factory development, run analysis) still gets a cost file — do not
    # stop capturing it — but it never ran doctor/onboarding/story, so the dashboard (package
    # G) must be able to tell it apart from a session that actually did factory work.
    has_factory_activity = any(v.get("type") in ("doctor", "onboarding", "story")
                               for v in by_activity.values())

    out_dir = state_dir(event) / "state" / "cost"
    out_dir.mkdir(parents=True, exist_ok=True)
    external = external_reconciliation(external_calls, "; ".join(dict.fromkeys(form_problems)), forms)
    document = {
        "capture_key": capture_key,
        "capture_logic": READER_STAMP,    # which logic wrote this file (`_stale_kind` rule (i)); above the Codex branch
        "scan_checkpoints": scan_checkpoints,
        "usage_status": ("actual" if event.get("usage_complete") is True else "provisional"),
        "usage_completeness": "complete" if event.get("usage_complete") is True else
                              ("provisional" if usage else "unknown"),
        "pricing_coverage": ("none" if not by_model else
            ("complete" if all(v["valuation"]["pricing_coverage"] == "complete" for v in by_model.values())
             else "partial" if any(v["valuation"]["pricing_coverage"] != "none" for v in by_model.values()) else "none")),
        "tariff_confirmation": ((cfg.get("rate_confirmation") or {}).get("status", "unconfirmed")
            if isinstance(cfg.get("rate_confirmation"), dict)
            else cfg.get("rate_confirmation", "unconfirmed")),
        "catalogue_revision": catalogue.get("catalogue_revision"),
        "requests": request_records,
        "external_calls": external_calls,
        "external_reconciliation": external,
        "usage_as_of": datetime.now().astimezone().isoformat(timespec="seconds"),
        "telemetry_coverage": {"provider_usage": "complete" if event.get("usage_complete") is True else "provisional",
                               # a forms problem means calls may exist that no row recognized: "incomplete",
                               # even with no call recorded (FR-41); otherwise complete / partial as before
                               "external_usage": "incomplete" if "forms_problem" in external else "complete"
                               if not external_calls or all(
                                   x.get("usage_status") == "available" and x.get("cost_usd") is not None
                                   for x in external_calls) else "partial"},
        "priced_subtotal_exact_usd": str(sum((Decimal(str((v.get("valuation") or {}).get("subtotal_usd","0"))) for v in by_model.values()), Decimal("0"))),
        "priced_subtotal_usd": float(sum((Decimal(str((v.get("valuation") or {}).get("subtotal_usd","0"))) for v in by_model.values()), Decimal("0"))),
        "session_id": session_id,
        "has_factory_activity": has_factory_activity,
        "transcript": str(tpath),
        "started": first_ts.isoformat() if first_ts else None,
        "ended": last_ts.isoformat() if last_ts else None,
        "tasks": sorted(by_task, key=lambda t: -(by_task[t]["cost"] or by_task[t]["tokens"])),
        "by_task": by_task,
        "by_activity": by_activity,
        "attribution_provenance": {"method": "explicit_activity_intervals",
            "parent_subagent_overlap": "excluded_evidenced_sidechain; otherwise unknown",
            "unclassified_preserved": "unclassified" in by_activity,
            "stop_resumed_parent": "excluded"},
        "orchestrator": {"by_model": orch_models, "cost": orch_cost,
                         "tools": dict(sorted(orch_tools.items(), key=lambda kv: -kv[1]))},
        "agents": agents,
        "incomplete_agents": incomplete_agents,
        "incomplete_where": incomplete_where,
        "by_model": by_model,
        "total_cost_usd": session_cost,
        "reconciliation": {
            "session_total": session_cost,
            "orchestrator_plus_agents": parts if session_cost is not None else None,
            "tasks_sum": tasks_cost if session_cost is not None else None,
            "match": None if not (usage_complete and pricing_complete and session_exact is not None and
                                   parts_exact is not None and tasks_exact is not None and
                                   external["complete"]) else
                     (abs(session_exact - parts_exact) <= Decimal("0.000001") and
                      abs(session_exact - tasks_exact) <= Decimal("0.000001")),
        },
        "tools": dict(sorted(tools.items(), key=lambda kv: -kv[1])),
        "human_wait_s": round(wait_total),
        "human_waits": human_waits,
        "question_waits": "measured" if questions_measured else "unmeasured",
        "open_questions": open_questions,
        "interactions": interactions,
        "wait_cap_s": wait_cap,
        "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "activities_hash": activities_hash,
    }
    if activities_doc.get('recovery'):
        document['attribution_provenance']['recovery'] = activities_doc['recovery']
    reader_counts = usage_reader_counts(scan_checkpoints.values())
    if reader_counts:
        document["usage_reader"] = reader_counts
    if main_checkpoint.get("adapter", "").startswith("codex-"):
        checkpoint = main_checkpoint
        document["host"] = "codex"
        document["adapter_receipt"] = checkpoint
        document["attribution_provenance"]["parent_subagent_overlap"] = "response thread identity; aggregate notifications excluded"
        if checkpoint["status"] != "recorded":
            document["usage_completeness"] = checkpoint["status"]
            document["usage_status"] = "provisional"
            document["reconciliation"]["match"] = None
        role = event.get("factory_role")
        if role:
            # Child usage has its own session file. Never call it orchestrator spend.
            document["agents"] = [{"agent": role, "file": tpath.name,
                "by_model": document["orchestrator"]["by_model"], "cost": orch_cost,
                "tools": orch_tools, "task": event.get("task_id") or event.get("task") or "(no task)",
                "tokens": sum(sum(v[k] for k in zero() if k != "requests") for v in orch_models.values())}]
            document["orchestrator"] = {"by_model": {}, "cost": 0, "tools": {}}
            document["incomplete_agents"] = [a["agent"] for a in document["agents"] if not a["tokens"]]
            document["incomplete_where"] = []   # a Codex gap is only a zero-usage file: its place is in agents[]
            for record in request_records:
                record["stream"] = tpath.name
                record["request_key"] = record["request_key"].rsplit(":", 1)[0] + ":" + tpath.name
    # The FACT that a recapture found the session ended (`recapture_session`): kept only on a file that says
    # `complete`, `null` on every other (a hook capture, a session still being written, a Codex partial) - the
    # state of a session is never stored, it is worked out at the render (`session_marks`).
    final = event.get("usage_final")
    document["usage_final"] = (dict(final) if isinstance(final, dict) and document["usage_completeness"] == "complete"
                               else None)
    if not has_factory_activity:
        # Write the summary, not the per-request ledger — see collapse_requests.
        document["requests"] = collapse_requests(document["requests"], session_id, cfg, catalogue)
    atomic_json(output_path, document)
    _clear_pending(out_dir, session_id, capture_started)
    # Telemetry maintenance is NOT here any more (SC1-4b): every capture of every session paid it under this
    # lock, and a rotation by size could move a merged daily file out of the collect pack's count (B-2). The
    # Stop caller runs `_maintain_telemetry` after `_after_capture`, with this lock free.
    # Everything that follows the capture proper — the dashboard refresh and the signal notice —
    # is `_after_capture`, which the CALLER runs once the cost writer lock is released. Both
    # callers hold that lock around this function, and a render of any length held it: the
    # same observer-stalls-the-writer defect as the story lock (TP2-2406).
    return True


def _after_capture(event) -> None:
    """The dashboard refresh and the metric-signal notice that follow a finished capture.
    Called with the cost writer lock FREE. The notice reads what the refresh just produced,
    so the two stay together and in this order."""
    from dashboard_refresh import refresh_project
    refresh_project(project_root(event))
    # The metric-signals notice is printed to stdout for the host. A pass that holds the skip flag
    # (a recapture sets it for itself, a red probe for its whole batch) wants no notice: it would
    # land in front of the JSON `--recapture` prints, and a recapture has no user-facing result.
    if os.environ.get("QA_FACTORY_SKIP_DASHBOARD_REFRESH") != "1":
        from metric_signals import context as signal_context
        notice = signal_context(project_root(event))
        if notice:
            from host_adapter import context_output
            context_output(event, notice)


def _maintain_telemetry(event) -> None:
    """The Stop-time pass over `state/telemetry/` (`telemetry_capture.maintain_dir`): merge the closed per-process
    files into one file a day, refresh the aggregates of the files that changed. Called with the cost writer lock
    FREE and AFTER the cost file, the dashboard and the notice are done, so the price (P18) never waits for it.
    It takes its own lock (the merge lock the collect pack shares) and skips when that is busy. Nothing it does may
    fail the hook: the pass is a convenience, the cost record is already written."""
    try:
        import telemetry_capture
        telemetry_capture.maintain_dir(state_dir(event) / "state" / "telemetry")
    except Exception:  # noqa: BLE001 - fail-silent by contract
        pass


def _ends_dispatch(event) -> bool:
    """F-11: the end of a role's dispatch maintains telemetry even in the debounced form (a PostToolUse sample never does)."""
    return event.get("hook_event_name") == "SubagentStop"


def _pending_path(cost_dir: Path, session_id: str) -> Path:
    return Path(cost_dir) / f"{session_id}.pending"


def _read_pending(path: Path):
    """The marker `<cost>/<session>.pending`: left by a Stop capture that gave up on the session lock
    (`_leave_pending`, kind "gave_up") or that STARTED and has not been seen to finish
    (`_mark_started`, kind "started"). None when there is none or it cannot be read as an object.
    The one reader of the marker (AR-13): `_pending_reason`, `_catch_up_pending`, `recapture_stale`."""
    try:
        marker = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return marker if isinstance(marker, dict) else None


def _pending_reason(marker: dict) -> str:
    """The sentence a person reads for a marker, by its `kind`. "started": the Stop capture that wrote
    it is still running or was stopped (an asynchronous Stop the host cut off, a killed process).
    Anything else - "gave_up", or no `kind` at all (a marker written before the field existed) - keeps
    the text it always had. The one carrier of this wording (AR-13)."""
    at = marker.get("at") or "an unrecorded time"
    if marker.get("kind") == "started":
        return (f"a Stop capture started at {at} did not finish (still running or stopped): "
                f"the transcript may hold requests the file lacks")
    return (f"a capture gave up on the lock at {at}: "
            f"the transcript may hold requests the file lacks")


def _write_pending(event, session_id: str, tpath: Path, reason: str, kind: str) -> None:
    """The one writer of the marker's fields (AR-22): `kind` is written here, for both callers."""
    now = datetime.now().astimezone()
    atomic_json(_pending_path(state_dir(event) / "state" / "cost", session_id),
                {"session_id": session_id, "kind": kind, "transcript": str(tpath), "reason": reason,
                 "at": now.isoformat(timespec="seconds"), "at_epoch": time.time()})


def _leave_pending(event, session_id: str, tpath: Path, reason: str) -> None:
    """Record, WITHOUT the lock (the lock is what failed), that the Stop capture of this session
    did not run. B-228: on cmp1 the capture gave up after 20 x 50 ms in all 16 sessions whose last
    requests landed after the file, and returned silently; nothing said a capture was missing.
    `_stale_reason` reads this marker, so the next `recapture_stale` repairs the tail. Kind "gave_up";
    it replaces a "started" marker of the same session (this capture did not run at all)."""
    _write_pending(event, session_id, tpath, reason, "gave_up")


def _mark_started(event, session_id: str, tpath: Path) -> None:
    """Record, before the Stop capture asks for the lock, that it STARTED (HF2-9, F-2 (a)): the Stop
    entry is asynchronous, so the host may cut it off with the turn, and a capture killed half-way
    leaves nothing else to say the tail is missing. A capture of this session that STARTS after the
    marker and writes (or finds current) the file removes it (`_clear_pending`); a killed one leaves it,
    and the file is shown stale with `_pending_reason` until the next capture of the session or the
    catch-up of any Stop (`_catch_up_pending`) records the tail.

    POSITION (E5): the checks `_capture` makes before it writes anything - the project is onboarded,
    the session is this project's - run FIRST. The invariant: the hook never writes a file into a project
    that is not onboarded, nor into a foreign project (a session opened ABOVE it, I-93). Those two tests
    are `_session_scope_ok`, the same call `_capture` makes; it is asked here because the marker is
    written BEFORE the lock, and `_capture` runs after it. The transcript and the session id were
    checked by `main`. Best effort: a marker that cannot be written is no reason to skip the capture."""
    if not _session_scope_ok(event, tpath):
        return
    try:
        _write_pending(event, session_id, tpath,
                       "a Stop capture of this session started and has not been seen to finish", "started")
    except OSError:
        pass


def _clear_pending(cost_dir: Path, session_id: str, started: float) -> None:
    """Remove the marker once a capture that STARTED AFTER it has written (or found current) the
    file. A marker written after this capture began may name a tail it did not read: it stays."""
    path = _pending_path(cost_dir, session_id)
    marker = _read_pending(path)
    if marker is not None:
        at = marker.get("at_epoch")
        if isinstance(at, bool) or not isinstance(at, (int, float)) or not math.isfinite(at):
            at = 0.0
        if at > started:
            return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


DEBOUNCE_WINDOW_S = 30.0   # a `--debounced` run leaves a cost file written less than this long ago alone


def _debounce_window_open(output_path: Path, now: float) -> bool:
    """True when a `--debounced` run may skip: the session's cost file was written at most
    DEBOUNCE_WINDOW_S ago (`now` and the file's mtime are epoch seconds). Asked by `main` BEFORE the
    lock, so a skipped run costs one `stat`: no lock, no parse of the cost file, no hashing of the
    activity file. The one carrier of the window (AR-13).

    The window used to be a check INSIDE `_capture` (the file's `generated` stamp), made under the lock
    after the whole file was parsed (52 MB at 24 thousand requests): advice that cancelled work already
    done. Now it decides whether the capture happens at all, so its error direction is fixed: a doubt is
    "capture now", never "skip" - the request that a skip leaves out is recorded by the next capture
    of the session, and a lost one is recorded by nobody. It answers False when:
      - the file is missing (a cold session: absence is not freshness);
      - its age is below zero (an mtime in the future is a clock nobody can trust) or at/over the window;
        exactly 30.0 s old captures, as `< 30` always meant;
      - the file cannot be examined (OSError: permission, a vanished path);
      - the session has a marker, of either kind: a tail is known to be missing, and the age of a file
        says nothing about it.
    An mtime fresher than the content (the file was rewritten by something that is not a capture:
    `_record_not_recomputed`, `_restore_previous`) skips: "later", the allowed direction, because the Stop
    form does not read the window at all."""
    output_path = Path(output_path)
    try:
        if _pending_path(output_path.parent, output_path.name.removesuffix(".json")).exists():
            return False
        age = now - output_path.stat().st_mtime
    except (OSError, ValueError, TypeError):
        return False
    return 0 <= age < DEBOUNCE_WINDOW_S


def _catch_up_pending(event, session_id: str) -> list:
    """After this Stop's own capture, BEFORE its render: record the tail of OTHER sessions of this
    project that a marker says is missing (F-2b (ii)). The Stop entry is asynchronous now, so a Stop
    the host cut off leaves a marker and nobody asks for that session again; the next Stop of any session
    of the project does. A session is caught up only when ALL of these hold - otherwise its marker stays:
      - its marker names a transcript that exists;
      - nothing under that transcript was written for RECAPTURE_LIVE_WINDOW_S (it is not live: a session
        still being written is captured by its own hooks, and `transcript_footprint` is the one
        reader of "how old" that `recapture_stale` uses too);
      - the session is not another project's (`session_belongs_to` is not "parent");
      - ONE attempt at its lock succeeds (a busy lock means a capture is running: it answers the marker).
    The capture is the ordinary incremental one - an event WITHOUT `recapture`, so pinned valuations and
    scan checkpoints are kept (E15: no size limit, a marker with no cost file is a cold full capture).
    Each session's lock is held only around that session's capture; this function runs with no lock of
    the calling session held and before the render, which also runs with none (E7, the 2406 defect).
    Best effort per session: one that fails keeps its marker and never stops the Stop capture.
    AT MOST ONE session is caught up per call, the OLDEST marker (`at_epoch`, the oldest tail first) that
    passes the tests above; the others wait for the next Stop. Under Codex the Stop is synchronous, and a
    catch-up is a full capture of a transcript that may be large: the time added to a Stop is bounded by
    one. A session that is skipped (live, gone, foreign, lock busy, an early exit) does not use the
    turn; one whose capture ran - to the end or to an error - does.
    Returns the session ids it recorded (at most one)."""
    cost_dir = state_dir(event) / "state" / "cost"
    root = project_root(event)
    slug = project_slug(root)
    try:
        markers = [(path, _read_pending(path)) for path in cost_dir.glob("*.pending")]
    except OSError:
        return []

    def marker_epoch(item):
        at = (item[1] or {}).get("at_epoch")
        at = at if isinstance(at, (int, float)) and not isinstance(at, bool) and math.isfinite(at) else 0.0
        return (at, item[0].name)   # an unreadable epoch is the oldest; the name makes ties stable

    caught = []
    for marker_path, marker in sorted(markers, key=marker_epoch):
        other = marker_path.name[:-len(".pending")]
        if other == session_id or marker is None:
            continue
        transcript = str(marker.get("transcript") or "")
        _size, age = transcript_footprint(transcript)
        if age is None or age < RECAPTURE_LIVE_WINDOW_S:
            continue
        if session_belongs_to({"transcript": transcript}, slug) == "parent":
            continue
        replay = {"hook_event_name": "Stop", "session_id": other, "transcript_path": transcript, "cwd": str(root)}
        try:
            with _capture_lock(cost_dir / ".writers" / other):
                _capture(replay)
            caught.append(other)
        except (StateConflict, SystemExit):
            continue
        except Exception as exc:
            print(f"cost_capture: the catch-up of {other} failed ({type(exc).__name__}); its marker stays",
                  file=sys.stderr)
        break   # one capture ran (to the end or to an error): the rest wait for the next Stop
    return caught


def _stale_kind(doc: dict, activity_file: Path, pending=None, *, limits=None, slug=None, now=None):
    """(kind, reason) for one state/cost/<session>.json: kind is "" (current), "stale" (a
    recapture repairs it), "logic" (written by another capture logic: the same repair, told apart so the
    pass can say `kept` where it may not repair) or "lost" (a stream the file records has no file, or a
    shorter one, than its checkpoint: rebuilding from the files that remain would lower the recorded usage,
    so the unattended pass leaves the file alone and names the door). `pending` is the lock-give-up marker.

    The two rules that need no human (DP-3) come LAST, after `lost`: POSITION and INVARIANT - a file whose
    stream is lost is never rebuilt without a person, whatever its logic or its session says; the door
    `--recapture --session` is the only one.
      (i) the file's `capture_logic` is not `READER_STAMP` and its transcript is a file -> "logic". A file
          with no transcript is left as recorded (the pass could not recompute it; old logic alone is
          never an alarm).
      (ii) `usage_completeness == "provisional"`, the session is not another project's (I-93: its transcript
          is not read) and `session_settled` says `settled` -> "stale". Only with `limits` (idle_s, open_s),
          the pass's one reading of the two limits; `slug` is the project's transcript folder; `now` the
          clock of the boundary tests. Codex `partial`/`unsupported` and an `unknown` verdict never reach it."""
    if "has_factory_activity" not in doc:
        return "stale", "old format (no has_factory_activity field)"
    generated = parse_ts(doc.get("generated"))
    if pending:
        return "stale", _pending_reason(pending)
    try:
        if activity_file.exists() and generated:
            # By content when the document carries `activities_hash`: `generated` is the capture's
            # time rounded DOWN to the second, so a file written in that second, with the content the
            # capture read, is not "newer". Content wins both ways: the same bytes are current whatever
            # the file time, other bytes are stale whatever it is. A document without the field (written
            # before it existed), or a file that cannot be read, keeps the file-time rule.
            stored = doc.get("activities_hash")
            verdict = None
            if isinstance(stored, str):
                try:
                    verdict = hashlib.sha256(activity_file.read_bytes()).hexdigest() != stored
                except OSError:
                    verdict = None
            if verdict is None:
                verdict = activity_file.stat().st_mtime > generated.timestamp()
            if verdict:
                return "stale", "activity file changed after this capture"
    except OSError:
        pass
    grew, lost = _tail_findings(doc, generated)
    if grew:
        return "stale", grew
    if lost:
        return "lost", lost
    named = doc.get("transcript")
    if doc.get("capture_logic") != READER_STAMP and isinstance(named, str) and named and Path(named).is_file():
        return "logic", "captured by an older capture logic"
    # no type test on `named` here (t-427): `session_verdict` answers "unknown" for a transcript that is no non-empty string or path,
    # and "unknown" is not "settled". Rule (i) above keeps its own test: it builds a `Path` from the word.
    if (limits is not None and doc.get("usage_completeness") == "provisional"
            and session_belongs_to(doc, slug or "") != "parent"):
        state, why = session_settled(named, limits[0], limits[1], now)
        if state == "settled":
            return "stale", why
    return "", ""


def _stale_reason(doc: dict, activity_file: Path, pending=None):
    """Why one state/cost/<session>.json needs recomputing: predates
    `has_factory_activity` (b156530d, written by 0.7.4 — role tokens 0, no priced amounts
    per task), or a backfill landed in its activity file after this capture ran (58e0f9dc:
    the activity was restored retroactively, `has_factory_activity: false` never got
    recomputed, $4.56 of $6.62 stayed outside the story), or its transcript grew after the capture
    (`_transcript_tail_reason`), or a capture gave up on the lock (`pending`, the marker of
    `_leave_pending`). (False, "") means current. A file `_stale_kind` calls "lost" is reported
    stale here too: it is flagged, even though the unattended pass does not recompute it."""
    kind, reason = _stale_kind(doc, activity_file, pending)
    return bool(kind), reason


def _usage_bytes_past(path: Path, offset: int):
    """True when the complete lines of `path` past byte `offset` hold an `assistant` record that
    carries usage; None when `offset` lies beyond the end of the file (truncated or replaced).
    A last line with no newline is an incomplete record and never counts, exactly as the capture
    leaves it for the next scan (`scan_file_incremental` stops its checkpoint before it)."""
    size = path.stat().st_size
    if offset > size:
        return None
    with path.open("rb") as stream:
        stream.seek(offset)
        for raw in stream:
            if not raw.endswith(b"\n"):
                break
            try:
                rec = json.loads(raw.decode("utf-8", errors="replace"))
            except ValueError:
                continue
            msg = rec.get("message") if isinstance(rec, dict) else None
            if isinstance(rec, dict) and rec.get("type") == "assistant" and isinstance(msg, dict) \
                    and isinstance(msg.get("usage"), dict) and msg["usage"]:
                return True
    return False


def _written_after(path: Path, generated):
    """"" when `path` was last written before `generated`; else why the capture cannot be taken as
    current. A capture time that is absent or unreadable is an unknown age, and an unknown age reads
    as behind: the allowed direction."""
    if generated is None:
        return "the capture time is not recorded, so a missed tail cannot be ruled out"
    # `generated` is written to the whole second (rounded down), so the capture ran somewhere in
    # [generated, generated + 1 s): only a write at or after generated + 1 s is surely later.
    if path.stat().st_mtime >= generated.timestamp() + 1.0:
        return "it was written after this capture (file time against the capture time)"
    return ""


def _tail_findings(doc: dict, generated):
    """(grew, lost) - why the TRANSCRIPT, not the cost file's own format, says this capture is
    behind, and why a rebuild from the files would lose recorded usage. Either is "" when absent.

    The Stop capture is not always the last thing Claude Code writes: on cmp1 the final requests
    of 16 of 35 sessions landed after the capture and the files read $0.775 low. `grew`: past the
    byte offset its checkpoint recorded, the main transcript or a subagent file holds an
    `assistant` record with usage. Size alone is NOT the test: Claude Code appends
    `stop_hook_summary`, `last-prompt`, `cost-state` and `attachment` lines after every Stop
    capture, so "size exceeds offset" flags every session (measured: all 35). Also `grew`: a
    subagent file with no checkpoint, and a checkpoint with no integer offset (the Codex adapter's
    receipt) whose file was written after `generated`; a file with no checkpoints at all falls back
    to the transcript's mtime against `generated` the same way. An absent `generated` reads as behind.

    `lost`: a checkpoint names a file that no longer exists, or its offset lies past the end of its
    file. The file's recorded rows for that stream are then the only record of its money, and a
    rebuild from the files that remain would drop it (t-165: $4.0 became $2.0), so this is reported
    apart: `recapture_stale` leaves such a file untouched and names the door. `grew` wins over
    `lost` when both hold. A gone main transcript says nothing: `recapture_session` reports that
    case as `not_recomputed`. The error direction is the allowed one: an extra recapture costs
    time, a missed tail costs money."""
    tpath = Path(str(doc.get("transcript") or ""))
    if not doc.get("transcript") or not tpath.is_file():
        return "", ""
    checkpoints = doc.get("scan_checkpoints")
    checkpoints = checkpoints if isinstance(checkpoints, dict) else {}
    session = doc.get("session_id") or "<session>"
    door = (f"its recorded rows are kept and nothing is recaptured unattended; "
            f"`cost_capture.py --recapture --session {session}` rebuilds the file and keeps them")
    lost = ""
    try:
        if not checkpoints:
            why = _written_after(tpath, generated)
            return (f"transcript grew after this capture (no checkpoints: {why})" if why else ""), ""
        sub_dir = tpath.parent / tpath.stem / "subagents"
        watched = {str(tpath.resolve()): tpath}
        if str(tpath.resolve()) not in checkpoints:
            return "the main transcript has no checkpoint (the capture recorded none for it)", ""
        for af in sorted(sub_dir.glob("agent-*.jsonl")) if sub_dir.is_dir() else []:
            watched[str(af.resolve())] = af
            if str(af.resolve()) not in checkpoints:
                return f"transcript grew after this capture: subagent file {af.name} has no checkpoint", ""
        for key, cp in checkpoints.items():
            path = watched.get(key) or Path(key)
            if not path.is_file():
                lost = lost or f"a checkpoint names {path.name}, which no longer exists: {door}"
                continue
            offset = cp.get("offset") if isinstance(cp, dict) else None
            if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
                why = _written_after(path, generated)
                if why:
                    return (f"transcript grew after this capture: {path.name} has no byte offset in "
                            f"its checkpoint and {why}"), ""
                continue
            found = _usage_bytes_past(path, offset)
            if found is None:
                lost = lost or (f"checkpoint of {path.name} is past the end of the file (offset {offset}, "
                                f"size {path.stat().st_size}): the file was truncated or replaced after "
                                f"this capture; {door}")
                continue
            if found:
                return f"transcript grew after this capture: {path.name} holds an assistant record past byte {offset}", ""
    except OSError as exc:
        return f"transcript grew after this capture: a file could not be read ({type(exc).__name__})", ""
    return "", lost


def _transcript_tail_reason(doc: dict, generated):
    """Why the transcript says this capture is behind - the `grew` reason, else the `lost` one,
    else "" (see `_tail_findings`)."""
    grew, lost = _tail_findings(doc, generated)
    return grew or lost


# --- the session lock ------------------------------------------------------------------------
# `<cost>/.writers/<session>/state/events.lock` (EventStore: one byte, locked by the OS, released
# when the process dies) serialises the captures of one session. Its holder is not named there.
# Since t-165 the holder also writes `state/capture.owner` next to it (a record for a person and
# for the stale-record rule; it is NEVER a reason to capture without the lock):
#   before: events.lock only (nothing says who holds it)
#   after:  + capture.owner = {"pid": <int>, "at": <epoch seconds>, "token": <hex>}, written once
#           the lock is taken and removed when it is released (only by the token that wrote it).
# A busy lock whose record names a dead process has a STALE record (the OS frees a lock when its
# process dies, so a live process holds it now); the record is dropped and the lock retried.
# B-228 (measured on cmp1): the Stop capture waited 20 x 50 ms for the lock of an asynchronous
# capture that was later killed, gave up, and returned without a word; the tail it would have
# recorded was never captured in all 16 sessions that read low.
# HF2-9 (t-080): the Stop entry of hooks.json is asynchronous now, so this wait no longer holds the
# host's turn; a Stop that two of one session's captures overlap in (E10) still waits this long, then
# leaves the "gave_up" marker. Before the lock is asked for, a Stop writes a "started" marker
# (`_mark_started`): a Stop the host kills mid-capture leaves it, and the next capture of the session, or
# the catch-up of any Stop (`_catch_up_pending`), records the tail. Neither the catch-up nor the render
# that follows a Stop is ever inside this lock.
LOCK_WAIT_S = 8.0      # how long a Stop capture waits for the lock (the Stop hook entry in
                       # hooks.json sets no timeout of its own, so the host's default applies)
LOCK_POLL_S = 0.05     # poll interval while waiting
LOCK_STALE_S = 120.0   # an owner record older than this is dropped (the lock is still waited for)


def _pid_alive(pid) -> bool:
    """False only when `pid` is known to be gone. An unusable pid, or any error asking, reads as
    alive: a lock is never broken on a guess."""
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return True
    try:
        if os.name == "nt":
            import ctypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            kernel.OpenProcess.restype = ctypes.c_void_p
            kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = kernel.OpenProcess(0x1000, 0, pid)       # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return ctypes.get_last_error() != 87          # 87 = no such process; 5 = exists
            code = ctypes.c_ulong()
            ok = kernel.GetExitCodeProcess(handle, ctypes.byref(code))
            kernel.CloseHandle(handle)
            return (not ok) or code.value == 259              # 259 = STILL_ACTIVE
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except Exception:
        return True


def _owner_path(lock_root: Path) -> Path:
    return Path(lock_root) / "state" / "capture.owner"


@contextlib.contextmanager
def _capture_lock(lock_root: Path):
    """The session lock with its owner record (see above). Raises StateConflict when taken.

    A PermissionError while TAKING it (two processes opening a lock file that does not exist yet:
    the second one's first write meets the first one's byte lock on Windows - seen in the t-165
    race run, `event_store.py` `f.flush()`) is a busy lock too, not a crash: the caller waits."""
    with contextlib.ExitStack() as stack:
        try:
            stack.enter_context(EventStore(lock_root).lock())
        except OSError as exc:
            raise StateConflict(f"the session lock could not be taken ({type(exc).__name__})") from exc
        token = uuid.uuid4().hex
        owner = _owner_path(lock_root)
        try:
            atomic_json(owner, {"pid": os.getpid(), "at": time.time(), "token": token})
        except OSError:
            pass
        try:
            yield
        finally:
            try:
                if json.loads(owner.read_text(encoding="utf-8")).get("token") == token:
                    owner.unlink()
            except (OSError, ValueError, AttributeError):
                pass


def _drop_stale_owner(lock_root: Path) -> str:
    """Drop the owner RECORD when it is stale, and say why ("" = it is not stale, or there is none).
    The lock itself is never touched: the OS releases it when its process dies, so "lock busy and the
    record names a dead process" means the RECORD is stale and another live process holds the lock
    (the critic's race run: a killed holder and two waiting captures; breaking the lock on that
    evidence ran two captures at once in 9 of 12 runs). A record older than LOCK_STALE_S is dropped
    the same way. Either way the caller retries the lock and never captures without it. A record is
    removed only if it is still the one that was judged (its token)."""
    path = _owner_path(lock_root)
    try:
        owner = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(owner, dict):
        return ""
    pid, at = owner.get("pid"), owner.get("at")
    why = ""
    if not _pid_alive(pid):
        why = f"its owner, process {pid}, is gone"
    elif not isinstance(at, bool) and isinstance(at, (int, float)) and time.time() - at > LOCK_STALE_S:
        why = f"process {pid} has held the lock for {time.time() - at:.0f} s, over the {LOCK_STALE_S:g} s limit"
    if not why:
        return ""
    try:
        if json.loads(path.read_text(encoding="utf-8")).get("token") == owner.get("token"):
            path.unlink()
    except (OSError, ValueError, AttributeError):
        pass
    # "dropped" only if the judged record is gone now; one that could not be removed is waited out
    # like any other (the caller must not spin on it)
    try:
        still_there = json.loads(path.read_text(encoding="utf-8")).get("token") == owner.get("token")
    except (OSError, ValueError, AttributeError):
        still_there = False
    return "" if still_there else why


def _capture_with_wait(event, session_id: str, lock_root: Path, debounced: bool = False) -> str:
    """Run `_capture` under the session lock; "captured" or "deferred". Only the STOP form (no
    `--debounced`) renders, and it renders ONCE, with the lock RELEASED, whatever its capture did:
    finished, found the file current ("captured") or could not get the lock ("deferred"). Before the
    render it records the tail of other sessions' markers (`_catch_up_pending`). A `--debounced` capture
    (PostToolUse / SubagentStop, asynchronous, many per session) tries the lock once and lets the next
    one, or the Stop capture, do it: it is a sample, not the final record, and it never renders (HF2-9:
    every sample paid a full dashboard render, t-080 - 26 to 42 s of a 44 to 67 s process). A capture
    that ran to the end ("finished") leaves by `sys.exit(0)`, the exit the hook entry has always had;
    one that ends by `sys.exit(0)` of its own (not this project's session, not onboarded) leaves by that
    SystemExit and renders nothing. A render held the lock of a concurrent capture of the same session
    for as long as it took (the story-lock defect, TP2-2406), and the waiters below poll that
    lock, so neither the catch-up nor the render is ever inside THIS session's lock, and the catch-up
    holds another session's lock only around that session's capture. Never returns silently
    when it could not capture: a waiting capture polls for LOCK_WAIT_S, drops an owner record that
    is stale (its process is gone, or it is older than LOCK_STALE_S; a line on stderr) and retries
    the lock - it NEVER captures without the lock - and otherwise leaves the marker
    `_stale_reason` reads (`_leave_pending`) so the next capture or `recapture_stale` records the tail."""
    deadline = time.monotonic() + (0.0 if debounced else LOCK_WAIT_S)
    while True:
        try:
            with _capture_lock(lock_root):
                outcome = _run_capture(event)
        except StateConflict:
            pass
        else:
            # The lock is free here. Outside the `try`, so a StateConflict raised by the refresh is
            # never read as "another capture holds the lock" and retried.
            if not debounced:
                _render_then_maintain(event, session_id)
            elif _ends_dispatch(event):
                # F-11: the end of a role's dispatch is the other point the files pile up at (a long headless
                # turn waits for its own Stop). A PostToolUse sample (same `--debounced` form) never maintains.
                _maintain_telemetry(event)
            if outcome == CAPTURE_FINISHED:
                sys.exit(0)
            return outcome
        if debounced:
            if _ends_dispatch(event):   # F-11: the lock is another capture's, not ours; the pass takes its own lock
                _maintain_telemetry(event)
            return "deferred"
        stale = _drop_stale_owner(lock_root)
        if stale:
            print(f"cost_capture: dropped a stale owner record of the session lock of {session_id} "
                  f"({stale}); trying the lock again", file=sys.stderr)
            continue
        if time.monotonic() >= deadline:
            reason = (f"the session lock of {session_id} was still held after {LOCK_WAIT_S:g} s; "
                      f"this capture did not run")
            try:
                _leave_pending(event, session_id, Path(event.get("transcript_path", "") or ""), reason)
                where = "a marker was left, and the next recapture will record the tail"
            except OSError as exc:
                where = f"the marker could not be written ({type(exc).__name__})"
            print(f"cost_capture: {reason}; {where}", file=sys.stderr)
            # Nothing was captured, but the dashboard must not be older than this Stop (E8): the lock's
            # holder writes later and the next Stop draws that. No lock of ours is held here.
            _render_then_maintain(event, session_id)
            return "deferred"
        time.sleep(LOCK_POLL_S)


def _render_then_maintain(event, session_id) -> None:
    """The Stop's tail, with the session lock free: catch up other sessions' markers, refresh the dashboard, and then
    ALWAYS run the telemetry pass - a refresh that raises (a malformed config) still lets the pass run (F-8) and then
    propagates, as it did before the pass moved here."""
    try:
        _catch_up_pending(event, session_id)
        _after_capture(event)
    finally:
        _maintain_telemetry(event)


CAPTURE_FINISHED = "finished"   # the outcome whose caller owes `_after_capture`, with the lock free


def _run_capture(event) -> str:
    """`_capture` under the lock: "finished" when it ran to the end (the caller then runs
    `_after_capture` and exits 0), "captured" when it had nothing to write (an unchanged capture_key:
    nothing more is due, and `main` just returns; the 30 s window of a debounced run is asked by `main`
    before the lock, `_debounce_window_open`).
    A SystemExit of `_capture` itself is NOT caught here, it leaves `main()` as it did when `main()`
    called `_capture` itself (test_storage_visibility pins that)."""
    return CAPTURE_FINISHED if _capture(event) else "captured"


# --- a recapture never lowers a session's recorded usage ----------------------------------------
def _rows_usage(rows):
    """(tokens, requests) over stored request rows; a row with no readable usage counts as one
    request and no tokens (an unknown is not zero requests)."""
    tokens = requests = 0
    for row in rows:
        usage = _row_usage(row)
        if usage is None:
            requests += 1
            continue
        requests += usage["requests"]
        tokens += sum(v for k, v in usage.items() if k != "requests")
    return tokens, requests


def _stream_rows(rows, stream: str, main_names):
    if stream == "orchestrator":
        return [r for r in rows if isinstance(r, dict) and r.get("stream") in main_names]
    return [r for r in rows if isinstance(r, dict) and r.get("stream") == stream]


def _lost_streams(previous: dict, tpath: Path) -> dict:
    """{stream: why} for the streams of a stored cost file whose file is gone, or shorter than its
    checkpoint: a rebuild from the files that remain cannot read them, so their stored rows are
    all the file knows of that money."""
    lost = {}
    main_names = {"orchestrator", tpath.name}
    sub_dir = tpath.parent / tpath.stem / "subagents"
    for row in previous.get("requests") if isinstance(previous.get("requests"), list) else []:
        stream = row.get("stream") if isinstance(row, dict) else None
        if isinstance(stream, str) and stream not in main_names and not (sub_dir / stream).is_file():
            lost[stream] = "its file no longer exists"
    checkpoints = previous.get("scan_checkpoints")
    for key, cp in (checkpoints if isinstance(checkpoints, dict) else {}).items():
        path = Path(key)
        stream = "orchestrator" if str(path.resolve()) == str(tpath.resolve()) else path.name
        try:
            if not path.is_file():
                if stream != "orchestrator":
                    lost.setdefault(stream, "its file no longer exists")
                continue
            offset = cp.get("offset") if isinstance(cp, dict) else None
            if isinstance(offset, int) and not isinstance(offset, bool) and offset > path.stat().st_size:
                lost.setdefault(stream, "its file is shorter than its checkpoint")
        except OSError:
            continue
    # A stream an earlier recapture kept rows for stays kept: after that recapture its checkpoint
    # sits at the end of the shorter file, so "shorter than the checkpoint" no longer names it, yet
    # the file still does not hold those rows (found by the mutation run of t-165: the second
    # recapture of a truncated transcript dropped the rows the first had kept).
    carried = previous.get("recapture_carried")
    for note in carried if isinstance(carried, list) else []:
        stream = note.get("stream") if isinstance(note, dict) else None
        if isinstance(stream, str) and stream:
            lost.setdefault(stream, "an earlier recapture kept its stored rows")
    return lost


def _carry_targets(previous: dict, lost: dict, tpath: Path) -> dict:
    """{stream: why} for EVERY stream the stored file has rows for: the lost ones with their
    reason, all others with a general one. A transcript rewritten in place to at least its
    checkpoint size is neither gone nor past the end, yet the rebuild lacks the requests it no
    longer holds (t-165 critic: 4.0 -> 2.0), so the carry rule is not limited to lost streams;
    it acts only where the rebuild holds less than the file recorded."""
    targets = dict(lost)
    main_names = {"orchestrator", tpath.name}
    for row in previous.get("requests") if isinstance(previous.get("requests"), list) else []:
        stream = row.get("stream") if isinstance(row, dict) else None
        if isinstance(stream, str) and stream:
            targets.setdefault("orchestrator" if stream in main_names else stream,
                               "the rebuild from its file lacks rows the file recorded")
    return targets


def _carry_lost_streams(written: dict, previous: dict, lost: dict, tpath: Path, cfg: dict):
    """The freshly rebuilt document with the stored rows of every stream in `lost` (the streams to
    check: `_carry_targets`) put back where the rebuild holds less, or None when the rebuild lost
    nothing. Per stream: when neither side holds a collapsed (carry) row, the
    rows the rebuild did not find are added to the rows it did; otherwise the stream's stored rows
    replace the rebuilt ones. Either way a stream never ends with less usage than it was recorded
    with. The derived figures (by_model, orchestrator, agents, by_task, by_activity, the totals,
    the reconciliation) are then re-derived from the rows by `revalue_document`."""
    main_names = {"orchestrator", tpath.name}
    rows = list(written.get("requests") if isinstance(written.get("requests"), list) else [])
    prior = [r for r in previous.get("requests") if isinstance(r, dict)] \
        if isinstance(previous.get("requests"), list) else []
    removed, added, notes = [], [], []
    for stream, why in lost.items():
        old, new = _stream_rows(prior, stream, main_names), _stream_rows(rows, stream, main_names)
        old_tokens, old_requests = _rows_usage(old)
        new_tokens, new_requests = _rows_usage(new)
        if not old:
            continue
        has_carry = any(str(r.get("request_id") or "").startswith("carry:") for r in old + new)
        # a request is named by its id within the stream (request_key's provider prefix changed
        # between versions: an old file's key would never match a rebuilt one and double-count)
        have = {r.get("request_id") or r.get("request_key") for r in new
                if r.get("request_id") or r.get("request_key")}
        # per-request rows: every stored request the rebuild did not find is put back, whatever the
        # totals say (a request lost and a different one gained is not a wash: both cost money);
        # collapsed rows cannot be told apart by key, so the stream with more usage wins whole.
        extra = [] if has_carry else [r for r in old if (r.get("request_id") or r.get("request_key")) not in have]
        union_tokens, union_requests = _rows_usage(new + extra)
        drop = []
        if has_carry:
            if old_tokens <= new_tokens and old_requests <= new_requests:
                continue
            extra, drop = old, new
        elif not extra:
            continue
        elif union_tokens < old_tokens or union_requests < old_requests:
            extra, drop = old, new
        added += copy.deepcopy(extra)
        removed += drop
        notes.append({"stream": stream, "reason": why, "rows_kept": len(extra)})
    if not notes:
        return None
    drop_ids = {id(r) for r in removed}
    doc = copy.deepcopy(written)
    doc["requests"] = [r for r in rows if id(r) not in drop_ids] + added

    def bump(section, key_of, blank, changed, sign):
        table = doc.get(section)
        if not isinstance(table, dict):
            table = doc[section] = {}
        for row in changed:
            key = key_of(row)
            entry = table.get(key)
            if not isinstance(entry, dict):
                base = previous.get(section)
                base = base.get(key) if isinstance(base, dict) else None
                entry = copy.deepcopy(base) if isinstance(base, dict) else dict(blank)
                entry["tokens"] = 0
                if "requests" in blank:
                    entry["requests"] = 0
                table[key] = entry
            tokens, requests = _rows_usage([row])
            for field, amount in (("tokens", tokens), ("requests", requests)):
                if field in entry or field == "tokens":
                    have_now = entry.get(field)
                    have_now = have_now if isinstance(have_now, (int, float)) and not isinstance(have_now, bool) else 0
                    entry[field] = max(0, have_now + sign * amount)

    task_blank = {"tokens": 0, "requests": 0, "cost": None, "priced_subtotal_usd": 0.0,
                  "active_s": None, "machine_s": None}
    activity_blank = {"type": "unclassified", "task": None, "status": "unknown", "by_model": {},
                      "tokens": 0, "cost": None, "active_s": None}
    for changed, sign in ((removed, -1), (added, 1)):
        bump("by_task", lambda r: r.get("task") or "(no task)", task_blank, changed, sign)
        bump("by_activity", lambda r: r.get("activity_id") or "unclassified", activity_blank, changed, sign)
    agents = doc.get("agents") if isinstance(doc.get("agents"), list) else []
    doc["agents"] = agents
    for note in notes:
        stream = note["stream"]
        if stream == "orchestrator" or any(isinstance(a, dict) and a.get("file") == stream for a in agents):
            continue
        stored = next((a for a in previous.get("agents") or [] if isinstance(a, dict) and a.get("file") == stream), None)
        if stored:
            agents.append(copy.deepcopy(stored))
    out = revalue_document(doc, cfg, None)
    by_task = out.get("by_task") if isinstance(out.get("by_task"), dict) else {}
    out["tasks"] = sorted(by_task, key=lambda t: -((by_task[t].get("cost") or by_task[t].get("tokens") or 0)
                                                   if isinstance(by_task[t], dict) else 0))
    out["recapture_carried"] = notes
    return out


def _restore_previous(out_path: Path, previous: dict, reason: str) -> None:
    """A recapture that ended without writing leaves the file it stripped (capture_key and
    checkpoints, to force a rescan) as it found it, with the reason beside it. A file the capture
    did write (it carries a capture_key again) is never touched."""
    if not previous:
        return
    try:
        current = json.loads(out_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        current = None
    if isinstance(current, dict) and current.get("capture_key"):
        return
    restored = dict(previous)
    restored["recapture_status"] = {"status": "not_recomputed", "reason": reason,
                                    "checked_at": datetime.now().astimezone().isoformat(timespec="seconds")}
    try:
        atomic_json(out_path, restored)
    except OSError:
        pass


def _record_not_recomputed(out_path: Path, doc: dict, reason: str, extra=None) -> bool:
    """Write `recapture_status: not_recomputed` (with the reason) into an EXISTING cost file, money
    untouched, so the dashboard's stale-files alert can list it and its figure is not read as exact
    (FR-41). True when the file carries that status after the call; nothing is written when it
    already carries the same one (a dashboard build runs this on every pass). `extra` adds fields to the
    status (the retry guard of a file of an older capture logic: `capture_logic`, `transcript_bytes`)."""
    extra = dict(extra or {})
    status = doc.get("recapture_status") if isinstance(doc, dict) else None
    if (isinstance(status, dict) and status.get("status") == "not_recomputed" and status.get("reason") == reason
            and all(status.get(key) == value for key, value in extra.items())):
        return True
    if not isinstance(doc, dict) or not Path(out_path).exists():
        return False
    marked = dict(doc)
    marked["recapture_status"] = {"status": "not_recomputed", "reason": reason,
                                  "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"), **extra}
    try:
        atomic_json(out_path, marked)
    except OSError:
        return False
    return True


def recapture_session(root: Path, session_id: str, transcript=None, limits=None) -> dict:
    """Recompute one session's cost file from its own transcript (`cost_capture.py
    --recapture --session <id>`): rebuilds it exactly as a live Stop hook would, from the
    `transcript` path the existing file already recorded (`transcript`: the path to use when there
    is no file yet, the marker of a capture that gave up on the lock). A session whose transcript is
    gone is reported "not_recomputed", not treated as an error — the batch (`--all-stale`) must
    keep going over every other file. A capture that ends without writing (the transcript vanished
    mid-way, the project is not onboarded) is "not_recomputed" as well, with the file as it was.
    A stream whose file is gone, or shorter than its checkpoint, keeps its stored rows: no
    recapture lowers the usage a file records (`_carry_lost_streams`). Never raises.

    THE ONLY writer of `usage_complete` and `usage_final` (AR-14): the file says `complete` only when
    `session_verdict` finds the session ended (`limits` = (idle_s, open_s), the pass's one reading; read
    from the project's config when the CLI calls it alone) - a session still being written, one stopped
    mid-turn inside the open limit and one that cannot be judged stay `provisional`, with `usage_final`
    `null`. `usage_final` = {"rule": "settled" | "timed_out", "reason", "as_of"} is the FACT of finalisation."""
    root = Path(root).resolve()
    out_path = root / "qa-factory" / "state" / "cost" / f"{session_id}.json"
    previous = {}
    if out_path.exists():
        try:
            previous = json.loads(out_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = {}
    if not isinstance(previous, dict):
        previous = {}
    transcript = previous.get("transcript") or transcript
    tpath = Path(transcript) if transcript else None
    if not tpath or not tpath.is_file():
        recorded = bool(previous) and _record_not_recomputed(out_path, previous, "transcript file no longer present")
        if recorded:
            # the marker of a capture that gave up on the lock has its way out here (FR-40): the
            # cost file now says it could not be recomputed, which is what the marker was for
            _pending_path(out_path.parent, session_id).unlink(missing_ok=True)
        return {"session_id": session_id, "status": "not_recomputed",
                "reason": "transcript file no longer present"}
    # recapture_explicit: this recompute was asked for, by a person on the CLI or by the pass
    # that already checked ownership — it passes the hook's own "not this project's session"
    # refusal below, so `--recapture --session <id>` still recomputes a parent-directory
    # session whose figures somebody wants back (I-93).
    # recapture: a NEW capture of the session - every request is valued afresh (see `_capture`).
    event = {"hook_event_name": "Stop", "session_id": session_id, "transcript_path": str(tpath),
             "cwd": str(root), "usage_complete": False, "recapture_explicit": True, "recapture": True}
    if limits is None:
        limits = final_limits(project_cost_block(root))
    state, why, rule = session_verdict(tpath, limits[0], limits[1])
    if state == "settled":
        event["usage_complete"] = True
        event["usage_final"] = {"rule": rule, "reason": why,
                                "as_of": datetime.now().astimezone().isoformat(timespec="seconds")}
    lock_root = root / "qa-factory" / "state" / "cost" / ".writers" / session_id
    # _capture() ends every run with a dashboard refresh, and factory_dashboard.py's build
    # now calls recapture_stale() before it reads state/cost/*.json — without this guard a
    # recapture triggers a dashboard build that triggers another recapture pass, recursing
    # once per stale file still left to process (every dashboard-refresh path honours
    # QA_FACTORY_SKIP_DASHBOARD_REFRESH; a render happens once, after every file is fresh).
    prior_skip = os.environ.get("QA_FACTORY_SKIP_DASHBOARD_REFRESH")
    os.environ["QA_FACTORY_SKIP_DASHBOARD_REFRESH"] = "1"
    try:
        with _capture_lock(lock_root):
            lost = _lost_streams(previous, tpath)
            # Force a full rescan: a stale/old-format file's capture_key and checkpoints
            # describe an earlier scan that must not short-circuit `_capture()` ("nothing
            # changed") and must not resume from an offset a pre-schema file never recorded
            # compatibly. INSIDE the lock: until 0.7.18 the strip happened before the lock was
            # asked for, and a recapture reached from a capture's own dashboard refresh (which
            # already holds it) stripped the file, hit StateConflict and left it without its
            # idempotency key for good — the flaky historical-import test in test_codex_host.
            if out_path.exists():
                try:
                    forced = json.loads(out_path.read_text(encoding="utf-8"))
                    forced.pop("capture_key", None)
                    forced.pop("scan_checkpoints", None)
                    atomic_json(out_path, forced)
                except (OSError, json.JSONDecodeError):
                    pass
            try:
                finished = _capture(event)
            except SystemExit as exc:
                if exc.code not in (0, None):
                    _restore_previous(out_path, previous, f"cost_capture exit {exc.code}")
                    return {"session_id": session_id, "status": "not_recomputed",
                            "reason": f"cost_capture exit {exc.code}"}
                finished = False
            # `_capture` leaves by sys.exit(0) when its transcript vanished, the project is not
            # onboarded or the session is not this project's: no file was written, and "recomputed"
            # would be a claim about a run that did nothing (FR-41). The forced strip removed the
            # capture_key, so a file written by this run is the one that carries it again.
            try:
                written = json.loads(out_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                written = None
            if not (isinstance(written, dict) and written.get("capture_key")):
                reason = ("the transcript disappeared during the recapture" if not tpath.is_file()
                          else "the capture ended without writing a file (the project is not onboarded, "
                               "or the session is not this project's)")
                _restore_previous(out_path, previous, reason)
                return {"session_id": session_id, "status": "not_recomputed", "reason": reason}
            carried = _carry_lost_streams(written, previous, _carry_targets(previous, lost, tpath), tpath,
                                          load_config(event).get("cost") or {})
            if carried is not None:
                atomic_json(out_path, carried)
        # The cost writer lock is released here; the refresh follows it, never inside it.
        if finished:
            _after_capture(event)
    except StateConflict:
        return {"session_id": session_id, "status": "busy",
                "reason": "another writer is capturing this session"}
    except Exception as exc:
        _restore_previous(out_path, previous, f"{type(exc).__name__}: {exc}")
        return {"session_id": session_id, "status": "not_recomputed",
                "reason": f"{type(exc).__name__}: {exc}"}
    finally:
        if prior_skip is None:
            os.environ.pop("QA_FACTORY_SKIP_DASHBOARD_REFRESH", None)
        else:
            os.environ["QA_FACTORY_SKIP_DASHBOARD_REFRESH"] = prior_skip
    return {"session_id": session_id, "status": "recomputed"}


RECAPTURE_MAX_MB_DEFAULT = 64      # config key cost.recapture_max_mb
RECAPTURE_LIVE_WINDOW_S = 300      # a transcript touched inside this window is still being written


USAGE_FINAL_IDLE_MIN_DEFAULT = 30  # config key cost.usage_final_after_idle_min: quiet this long, a session may be final
USAGE_FINAL_OPEN_H_DEFAULT = 24    # config key cost.usage_final_after_open_h: a turn open this long is a session that died


def project_cost_block(root):
    """The `cost` block of <root>/qa-factory/config.json AS WRITTEN (None when there is no file, no block or no
    object): the ONE config reader of the recapture pass and of `recapture_session` (BOM-tolerant, as the pass
    always was). The callers hand it to `final_limits` and read their own keys from it; a block that is not an
    object is passed on as it is, so the limits' reader can say so."""
    cfg = read_json(Path(root) / "qa-factory" / "config.json", None, kind=dict)   # the package's one JSON reader (BOM-tolerant)
    return cfg.get("cost") if cfg else None


def _limit_seconds(cost_cfg, key, default, unit_s, problems) -> float:
    """`cost_cfg[key]` times `unit_s`; the default when the key is absent (silent: absent means default) and
    when the value is not a finite non-negative number (a line in `problems`). `json.loads` accepts NaN and
    Infinity, and a NaN would make every `age < limit` false and let a live session through (AR-28); a number
    too big to multiply is the same case."""
    if not isinstance(cost_cfg, dict) or key not in cost_cfg:
        return default * unit_s
    value = cost_cfg[key]
    try:
        # one finiteness test, on the product: NaN fails `value >= 0`, an infinity stays non-finite when multiplied (inf * 0 is NaN),
        # and a number too big to convert raises OverflowError below (t-427: the test on `value` alone was the same case twice)
        usable = (isinstance(value, (int, float)) and not isinstance(value, bool)
                  and value >= 0 and math.isfinite(value * unit_s))
    except OverflowError:
        usable = False
    if not usable:
        problems.append(f"cost.{key} is not a non-negative finite number")
        return default * unit_s
    return value * unit_s


def _say_limit_problems(problems) -> None:
    if problems:
        print("cost_capture: " + "; ".join(dict.fromkeys(problems)) + "; the default is used", file=sys.stderr)


def _block_problem(cost_cfg, problems) -> None:
    if cost_cfg is not None and not isinstance(cost_cfg, dict):
        problems.append("the cost block of the config is not an object")


def final_idle_s(cost_cfg, problems=None) -> float:
    """Seconds a session's transcript must be quiet before the session may count as ended
    (`cost.usage_final_after_idle_min`, default 30 minutes). Never below `RECAPTURE_LIVE_WINDOW_S`: the pass
    refuses a transcript younger than that as live, so a smaller limit would call `settled` what the pass then
    refuses (raised silently, it is a floor and not an error). `cost_cfg` is the `cost` BLOCK, not the whole
    config. `problems` collects the lines about unusable values; None says them on stderr at once."""
    found = [] if problems is None else problems
    _block_problem(cost_cfg, found)
    seconds = max(_limit_seconds(cost_cfg, "usage_final_after_idle_min", USAGE_FINAL_IDLE_MIN_DEFAULT, 60, found),
                  RECAPTURE_LIVE_WINDOW_S)
    if problems is None:
        _say_limit_problems(found)
    return seconds


def final_open_s(cost_cfg, problems=None) -> float:
    """Seconds after which a turn that never closed means the session died (`cost.usage_final_after_open_h`,
    default 24 hours); never below the idle limit. Same arguments as `final_idle_s`."""
    found = [] if problems is None else problems
    _block_problem(cost_cfg, found)
    seconds = max(_limit_seconds(cost_cfg, "usage_final_after_open_h", USAGE_FINAL_OPEN_H_DEFAULT, 3600, found),
                  final_idle_s(cost_cfg, []))
    if problems is None:
        _say_limit_problems(found)
    return seconds


def final_limits(cost_cfg) -> tuple:
    """`(idle_s, open_s)` read ONCE for a pass or a render, with at most ONE line on stderr (the recapture pass
    and the price ask on every session: a line per session would flood a hook)."""
    found = []
    limits = (final_idle_s(cost_cfg, found), final_open_s(cost_cfg, found))
    _say_limit_problems(found)
    return limits


def _is_chain_row(row, role_file) -> bool:
    """A row of the conversation chain: `user` or `assistant`, not a meta line, and (in the main transcript) not a
    sidechain row. A role's own file is all sidechain, so there any such row counts."""
    kind = row.get("type")
    if kind not in ("user", "assistant") or (kind == "user" and row.get("isMeta")):
        return False
    return role_file or not row.get("isSidechain")


def _last_chain_rows(path, cap, want=1, keep=None):
    """`(rows, problem)`: the last `want` rows (newest first) of the file at `path` that `keep` accepts (the chain
    rows of the main transcript by default), read from the END, within `cap` bytes. A transcript's last row is not
    its last LINE: Claude Code appends `last-prompt`, `attachment`, `system`, `cost-state` lines after the row that
    matters (measured t-243: after a `tool_use` the next line is not a message in 79 of 346 cases), so the last
    row is found by skipping them. `problem` says why the end cannot be trusted - the last line has no line break
    (still being written) or is not a JSON object, or no row lies within `cap` bytes - and `rows` is then empty.
    A file with no row at all gives ([], ""). Raises OSError as `open` does: the caller decides.
    Why not `dispatch_liveness._tail`: it gives the last TWO lines, which is not enough for that; the cap and the
    row parser are its own (`_LAST_ROW_CAP_BYTES`, `_json_row`)."""
    import dispatch_liveness as DL
    keep = keep or (lambda row: _is_chain_row(row, False))
    with open(path, "rb") as handle:
        size = handle.seek(0, 2)
        window = 65536
        while True:
            window = min(window, cap)
            start = max(size - window, 0)
            handle.seek(start)
            data = handle.read(size - start)
            body = data.rstrip()
            if body and b"\n" not in data[len(body):]:
                return [], "the last line has no line break (it is still being written)"
            parts = body.split(b"\n")
            lines = [part.strip() for part in (parts[1:] if start > 0 else parts) if part.strip()]
            if lines and DL._json_row(lines[-1]) is None:
                return [], "the last line is not a readable row"
            rows = []
            for line in reversed(lines):
                row = DL._json_row(line)
                if row is not None and keep(row):
                    rows.append(row)
                    if len(rows) == want:
                        return rows, ""
            if start == 0:
                return rows, ""
            if window >= cap:
                return (rows, "") if rows else ([], f"no row within the last {cap} bytes")
            window *= 2


def _answers_handback(last, older, handback) -> bool:
    """True when `last` is a user row holding the `tool_result` of a `handback` call that one of `older` made."""
    import host_adapter as HA
    message = last.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    answered = {b.get("tool_use_id") for b in content if isinstance(b, dict) and b.get("type") == "tool_result"} \
        if isinstance(content, list) else set()
    return any(b.get("type") == "tool_use" and b.get("name") == handback and b.get("id") in answered
               for row in older for b in HA.assistant_row_blocks(row))


def _file_closed(path, role_file, handback, cap) -> tuple:
    """("closed" | "open" | "torn", what) for one Claude transcript file. The main file is closed when the last
    chain row is an `assistant` row with no `tool_use` (a `user` row of any kind - a prompt, a `tool_result` - and
    a tool call both leave a turn to be answered). A role's file is closed by the same rule OR when its last row is
    the host's `tool_result` for the handback call `handback` names (`claude.handback_tool`): that is how every one
    of the 38 local role files ends. A file with no chain row has no turn open."""
    rows, problem = _last_chain_rows(path, cap, 8, lambda row: _is_chain_row(row, role_file))
    if problem:
        return "torn", problem
    if not rows:
        return "closed", ""
    import host_adapter as HA
    last = rows[0]
    if last.get("type") == "assistant":
        if any(b.get("type") == "tool_use" for b in HA.assistant_row_blocks(last)):
            return "open", "its last row is a tool call with no result"
        return "closed", ""
    if role_file and handback and _answers_handback(last, rows[1:], handback):
        return "closed", ""
    return "open", "its last row is a user row, not an answer of the assistant"


def _codex_closed(path, event, cap) -> tuple:
    """("closed" | "open" | "torn", what) for a Codex rollout: closed when its last event is `event`
    (`codex.completion_event`), as `dispatch_liveness._read_rollout` names the last event (an `event_msg` by its
    payload's `type`). `_read_rollout` itself reads CHILD rollouts only, so the parse is its own."""
    rows, problem = _last_chain_rows(path, cap, 1, lambda row: True)
    if problem:
        return "torn", problem
    if not rows:
        return "open", "the rollout holds no event"
    row = rows[0]
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    last_type = payload.get("type") if row.get("type") == "event_msg" else row.get("type")
    return ("closed", "") if last_type == event else ("open", f"its last event is not {event}")


def _unfinished(tpath) -> tuple:
    """`(open_files, unknown_reason)`: [(kind, file name, what)] for every file of the session that is not closed
    (`_file_closed`, `_codex_closed`), or ([], reason) when the end of the session cannot be told at all. OSError
    and ValueError (bytes that are not text) escape to `session_verdict`, which makes them `unknown`."""
    import dispatch_liveness as DL
    import host_adapter as HA
    from codex_usage import metadata
    cap = DL._LAST_ROW_CAP_BYTES
    if tpath.name.endswith(".zst"):
        return [], f"{tpath.name} is compressed (.zst) and cannot be read for its end"
    if metadata(tpath).get("id"):
        forms, _why = HA.report_forms(host="codex")
        event = ((forms or {}).get("codex") or {}).get("completion_event")
        if not isinstance(event, str) or not event:
            return [], "the host's session form is not read for its end"
        kind, what = _codex_closed(tpath, event, cap)
        return ([] if kind == "closed" else [(kind, tpath.name, what)]), ""
    forms, _why = HA.report_forms()    # the handback name only: one malformed row of another purpose does not take it
    handback = HA.handback_name(forms)
    sub_dir = tpath.parent / tpath.stem / "subagents"
    files = [(tpath, False)] + [(p, True) for p in (sorted(sub_dir.glob("agent-*.jsonl")) if sub_dir.is_dir() else [])
                                if p.is_file()]
    found = []
    for path, role_file in files:
        kind, what = _file_closed(path, role_file, handback, cap)
        if kind != "closed":
            found.append((kind, path.name, what))
    return found, ""


def session_verdict(transcript, idle_s, open_s, now=None) -> tuple:
    """`(state, reason, rule)` - the ONE reader of "has this session ended" (AR-13); `session_settled` is its
    two-field form. `state`: `live` (the transcript or a role's file changed less than `idle_s` ago), `open` (a turn
    is open and younger than `open_s`), `settled` (every file closed, or a turn open or a last line torn for
    `open_s` or more: the session died, `rule` "timed_out" - FR-41 names it in the file), `unknown` (no
    transcript, a last line not readable yet, a file that cannot be read, a host form not read, a `.zst`). `rule` is
    "settled" / "timed_out" for `settled`, else None. `now` is epoch seconds (the boundary tests set it).
    Every doubt is provisional or information, never final: an unknown form, an unreadable file and a clock in the
    future (age 0 -> live) all fall on that side. An OSError on a tail is `unknown` with NO timeout: a file that
    cannot be read is not a session that died."""
    now = time.time() if now is None else now
    # a name that is not a non-empty str or a Path is no file (an int, a list, True: `unknown`, never a TypeError)
    tpath = Path(transcript) if isinstance(transcript, (str, os.PathLike)) and transcript else None
    if tpath is None or not tpath.is_file():
        return "unknown", "the transcript is gone", None
    _size, age = transcript_footprint(tpath, now)
    if age is None:
        return "unknown", "the transcript could not be examined", None
    if age < idle_s:
        return "live", f"the transcript changed {int(age)} s ago", None
    try:
        problems, fatal = _unfinished(tpath)
    except (OSError, ValueError) as exc:    # ValueError holds UnicodeDecodeError: bytes that are not text
        return "unknown", f"{tpath.name} could not be read ({type(exc).__name__})", None
    if fatal:
        return "unknown", fatal, None
    if not problems:
        return "settled", "the session has ended", "settled"
    timed = age >= open_s
    kind, name, what = next((p for p in problems if p[0] == "torn"), problems[0])
    if kind == "torn":
        if timed:
            return "settled", f"ended with an unreadable last line (timed out): {name}: {what}", "timed_out"
        return "unknown", f"the last line of {name} is not readable: {what}", None
    if timed:
        return "settled", f"ended mid-turn (timed out): {name}: {what}", "timed_out"
    return "open", f"{name} is open: {what}", None


def session_settled(transcript, idle_s, open_s, now=None) -> tuple:
    """`(state, reason)` of `session_verdict`: `live` | `open` | `settled` | `unknown`."""
    state, reason, _rule = session_verdict(transcript, idle_s, open_s, now)
    return state, reason


def transcript_footprint(transcript, now=None) -> tuple:
    """`(bytes, seconds since last write)` of one session's transcript — its subagent files
    (`<stem>/subagents/agent-*.*`) counted in, because a capture reads every one of them and
    on TP1-15045 the subagent folder of the 16-dispatch run was larger than the main
    chain. `(0, None)` when the transcript is gone. `now` (epoch seconds, default the clock) is for the
    boundary tests: with the real clock an AT limit turns BEYOND by the fractions of a second the test takes."""
    tpath = Path(transcript) if transcript else None
    if not tpath or not tpath.is_file():
        return 0, None
    size, newest = 0, 0.0
    sub_dir = tpath.parent / tpath.stem / "subagents"
    for path in [tpath] + (sorted(sub_dir.glob("agent-*.*")) if sub_dir.is_dir() else []):
        try:
            stat = path.stat()
        except OSError:
            continue
        size += stat.st_size
        newest = max(newest, stat.st_mtime)
    if not newest:
        return size, None
    return size, max(0.0, (datetime.now().timestamp() if now is None else now) - newest)


def _recapture_skip(doc: dict, project_slug_value: str, max_mb: float, explicit: bool):
    """Why the recapture pass must NOT recompute this stale cost file, or None to go ahead.

    Ownership first, and it holds even for an explicit `--all-stale`: recomputing a session
    that was opened one directory above the project means reading a transcript that is none
    of this project's business (I-93 — 8 such sessions on TP1-15045, 273 MB, one of them
    live). A "parent" session keeps its recorded figures and the dashboard keeps showing it
    in its own section; `--recapture --session <id>` still recomputes it on demand, which is
    the way a person's word passes this block.

    "unknown" (Codex, whose transcript path carries no project folder) goes ahead, as before:
    the only two things that make a file stale are an old format that predates
    `has_factory_activity` and an activity backfill that landed after the capture (58e0f9dc),
    so the stored flag is either absent or the very field the backfill contradicts — it
    cannot be used to decide ownership here.

    The size and liveness thresholds are for the unattended pass only, the one a dashboard
    build triggers: a person who typed the command waits for their own recompute."""
    # `code` is the machine name of the refusal (`parent` | `size` | `live`): the pass tells `kept` from `skipped`
    # by it, and the dashboard tells a live session's refusal from a door - never by the wording of `reason`.
    if session_belongs_to(doc, project_slug_value) == "parent":
        return {"status": "skipped", "reason": "parent directory - not recaptured", "code": "parent"}
    if explicit:
        return None
    size, age = transcript_footprint(doc.get("transcript"))
    if max_mb > 0 and size > max_mb * 1048576:
        return {"status": "skipped", "code": "size",
                "reason": f"transcript {size / 1048576:.0f} MB exceeds {max_mb:g} MB"}
    if age is not None and age < RECAPTURE_LIVE_WINDOW_S:
        return {"status": "skipped", "reason": f"transcript changed {int(age)} s ago - still live", "code": "live"}
    return None


def recapture_stale(root: Path, explicit: bool = False) -> list:
    """`cost_capture.py --all-stale`, importable: recompute every state/cost/*.json that
    `_stale_reason` flags AND that this project may read (`_recapture_skip`). Best-effort per
    file — one broken file never stops the batch, and a skipped file is reported, not
    silently dropped. The dashboard build calls this with no arguments before it reads
    state/cost/*.json (respecting QA_FACTORY_SKIP_DASHBOARD_REFRESH, same as every other
    dashboard refresh path); `explicit=True` is the CLI, where the size and liveness
    thresholds do not apply because a person is waiting for the result.

    A file whose transcript grew after its capture (`_stale_reason`) is recomputed like any other
    stale one: a session still being written is skipped as live (reason given), a session whose
    transcript is gone comes back `not_recomputed` and keeps its file. No recapture prints the
    metric-signals notice (`_capture` honours QA_FACTORY_SKIP_DASHBOARD_REFRESH, which every
    recapture sets for itself).

    Never dropped, never lowered (t-165, E9 "a missing file is never $0"): a file this pass cannot
    read, and a file whose only finding is "lost" (a checkpoint names a file that is gone, or an
    offset past the end: `_stale_kind`), are reported `skipped` with the reason and left
    byte for byte as they are - a rebuild from the files that remain would drop recorded money. The
    reason names the door, `--recapture --session <id>`, which rebuilds the file and keeps those
    rows. A session with a lock-give-up marker (`<session>.pending`, see `_leave_pending`) is stale
    even when its cost file is missing or current; its marker is cleared by the capture that
    records it, and kept when the transcript is gone."""
    root = Path(root).resolve()
    cost_dir = root / "qa-factory" / "state" / "cost"
    activities_dir = root / "qa-factory" / "state" / "activities"
    results = []
    if not cost_dir.is_dir():
        return results
    # ONE reading of the `cost` block per pass (E5): the size limit and the two final limits come from it, a
    # block that is not an object gives the defaults and one stderr line, never the AttributeError the pass's
    # caller would have swallowed (no pass at all, silently).
    cost_cfg = project_cost_block(root)
    limits = final_limits(cost_cfg)
    block = cost_cfg if isinstance(cost_cfg, dict) else {}
    try:
        max_mb = float(block.get("recapture_max_mb", RECAPTURE_MAX_MB_DEFAULT))
        if not math.isfinite(max_mb):
            raise ValueError("not finite")
    except (TypeError, ValueError, OverflowError):
        max_mb = float(RECAPTURE_MAX_MB_DEFAULT)
    slug = project_slug(root)
    sessions = {f.stem for f in cost_dir.glob("*.json")} | \
        {p.name[:-len(".pending")] for p in cost_dir.glob("*.pending")}
    for session_id in sorted(sessions):
        f = cost_dir / f"{session_id}.json"
        pending = _read_pending(_pending_path(cost_dir, session_id))
        if f.exists():
            try:
                doc = json.loads(f.read_text(encoding="utf-8"))
                if not isinstance(doc, dict):
                    raise ValueError("the file does not hold a JSON object")
            except (OSError, ValueError) as exc:
                results.append({"session_id": session_id, "status": "skipped",
                                "reason": f"cost file could not be read ({type(exc).__name__}); left as it is",
                                "stale_reason": "unreadable cost file"})
                continue
            kind, reason = _stale_kind(doc, activities_dir / f"{session_id}.json", pending, limits=limits, slug=slug)
        elif pending:
            # the capture that gave up on the lock was the session's first: no cost file yet
            doc = {"session_id": session_id, "transcript": pending.get("transcript")}
            kind, reason = "stale", _pending_reason(pending)
        else:
            continue
        if not kind:
            continue
        if kind == "lost":
            results.append({"session_id": session_id, "status": "skipped", "reason": reason,
                            "stale_reason": reason})
            continue
        if pending and not Path(str(doc.get("transcript") or "")).is_file():
            # the marker stays (a person can see it); the cost file, when there is one, says it could
            # not be recomputed, so the stale-files alert lists it and its figure is not read as exact
            _record_not_recomputed(f, doc, "transcript file no longer present (" + _pending_reason(pending) + ")")
            results.append({"session_id": session_id, "status": "skipped", "stale_reason": reason,
                            "reason": "transcript file no longer present; the marker is kept"})
            continue
        # A file of an older capture logic is recomputed ONCE whatever its size (F-5: the size limit guards the
        # unattended pass against a transcript it would read again and again; this read happens once).
        logic = kind == "logic"
        skip = _recapture_skip(doc, slug, 0.0 if logic else max_mb, explicit)
        if skip and logic and skip.get("code") in ("parent", "live"):
            # not an alarm: a parent's transcript is not ours to read (I-93), a live session's own next capture
            # writes the current logic. The file stays as recorded; nothing lists it as stale.
            results.append({"session_id": session_id, "status": "kept", "stale_reason": reason,
                            "reason": f"{reason}; {skip['reason']}; shown as recorded"})
            continue
        if skip:
            results.append({"session_id": session_id, **skip, "stale_reason": reason})
            continue
        if logic and not explicit and _logic_retry_blocked(doc):
            status = doc["recapture_status"]
            results.append({"session_id": session_id, "status": "not_recomputed", "stale_reason": reason,
                            "reason": f"{status.get('reason')} (not tried again until the capture logic or the "
                                      "transcript size changes)"})
            continue
        outcome = recapture_session(root, session_id, transcript=doc.get("transcript"), limits=limits)
        outcome["stale_reason"] = reason
        if logic and outcome.get("status") == "not_recomputed":
            _remember_failed_logic_pass(f, outcome["reason"], doc.get("transcript"))
        results.append(outcome)
    return results


def _logic_retry_blocked(doc: dict) -> bool:
    """True when a pass already failed to recompute this file under this capture logic and the transcript has not
    changed size since: trying again on every render would make "one recompute" a lie (F-5)."""
    status = doc.get("recapture_status")
    if not (isinstance(status, dict) and status.get("status") == "not_recomputed"):
        return False
    size, _age = transcript_footprint(doc.get("transcript"))
    return status.get("capture_logic") == READER_STAMP and status.get("transcript_bytes") == size


def _remember_failed_logic_pass(path: Path, reason: str, transcript) -> None:
    """After a failed recompute of a file of an older logic: say so IN the file (`recapture_status`, the field the
    stale-files alert reads) with the logic and the size the failure was seen at, so `_logic_retry_blocked` can stand
    down until either changes. Money untouched; nothing written for a file that is gone."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    size, _age = transcript_footprint(transcript)
    _record_not_recomputed(path, doc, reason, {"capture_logic": READER_STAMP, "transcript_bytes": size})


def _cli_recapture() -> None:
    ap = __import__("argparse").ArgumentParser()
    ap.add_argument("--recapture", action="store_true")
    ap.add_argument("--all-stale", action="store_true")
    ap.add_argument("--session", default=None)
    ap.add_argument("--root", default=None)
    args, _ = ap.parse_known_args(sys.argv[1:])
    root = Path(args.root).resolve() if args.root else project_root()
    if args.all_stale:
        results = recapture_stale(root, explicit=True)
    elif args.session:
        results = [recapture_session(root, args.session)]
    else:
        print("cost_capture.py --recapture requires --session <id> (or --all-stale)", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(results))


def _choose_subagent_transcript(event) -> None:
    """Which file a SubagentStop event (it carries `agent_transcript_path`) is a capture of (F-7).
    Under Claude the event holds the PARENT's `session_id` and `transcript_path` and the subagent's file in
    `agent_transcript_path`; that file has no id of its own and is one of the parent's
    `<stem>/subagents/agent-*.jsonl`, which every capture of the parent reads anyway (`agents[]`). Taking
    it as the session's transcript wrote `cost/<parent>.json` from the subagent file alone: the parent's
    requests shrank and its main-transcript checkpoint was replaced by another file's. So the session's
    transcript stays the parent's `transcript_path`. The invariant: a capture never lowers the parent's
    `total_cost_usd` or request count, and a file belongs to its own session (FR-24).
    Under Codex the child's rollout names its own session (`session_meta.id`): it IS the session, captured
    as its own file with the child's role (`factory_role`), exactly as before.
    A subagent file outside the parent's `subagents/` directory is not one the parent's capture reads: one
    line on stderr says so (the trace; the cost document's fields stay as they are), and the parent is
    still captured from its own transcript."""
    agent = event.get("agent_transcript_path")
    if not agent:
        return
    agent_path = Path(agent)
    try:
        from codex_usage import metadata
        own_session = agent_path.is_file() and bool(metadata(agent_path).get("id"))
    except (OSError, ValueError, AttributeError):
        own_session = False
    if own_session:
        event["transcript_path"] = str(agent_path)
        event["factory_role"] = event.get("agent_type") or event.get("agent_name")
        return
    parent = Path(event.get("transcript_path", "") or "")
    sibling_dir = parent.parent / parent.stem / "subagents"
    inside = os.path.normcase(os.path.abspath(agent_path.parent)) == os.path.normcase(os.path.abspath(sibling_dir))
    if not inside:
        print(f"cost_capture: the subagent file {agent_path} lies outside {sibling_dir}; the parent session "
              f"{event.get('session_id') or parent.stem} is captured from its own transcript and does not count it",
              file=sys.stderr)


def main() -> None:
    if "--recapture" in sys.argv or "--all-stale" in sys.argv:
        return _cli_recapture()
    event = read_event() or {}
    _choose_subagent_transcript(event)
    tpath = Path(event.get("transcript_path", "") or "")
    if tpath.is_file():
        from codex_usage import metadata
        meta = metadata(tpath)
        if meta.get("id"):
            event["session_id"] = meta["id"]
    session_id = event.get("session_id", "") or tpath.stem
    if not tpath.is_file() or any(c in session_id for c in "/\\:") or session_id in (".", ".."):
        return
    debounced = "--debounced" in sys.argv
    cost_dir = state_dir(event) / "state" / "cost"
    if debounced:
        # BEFORE the lock (HF2-9, F-3 (a)): a run inside the window costs one `stat`. Outcome "captured":
        # no lock, no parse of the cost file, no marker - a sample that skips is not a failure. A held
        # lock does not change that (it is not even asked).
        if _debounce_window_open(cost_dir / f"{session_id}.json", time.time()):
            if _ends_dispatch(event):   # F-11: the window skips the capture, not the end of a dispatch's pass
                _maintain_telemetry(event)
            return
    else:
        # The Stop capture is asynchronous (F-2 (a)): write the "started" marker BEFORE the lock, so a
        # Stop the host kills half-way leaves the tail marked, not silently lost.
        _mark_started(event, session_id, tpath)
    _capture_with_wait(event, session_id, cost_dir / ".writers" / session_id, debounced)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        print(f"COST CAPTURE INCOMPLETE: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(0)  # telemetry does not stop the pipeline
