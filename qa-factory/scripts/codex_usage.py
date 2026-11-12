"""Versioned adapter for observed Codex rollout token_usage_record records.

The rollout format is not a public stable API. Only response-scoped usage with
an explicit response identity is admitted. Aggregate token_count notifications
are NEVER added to these records. Unknown formats remain unsupported.
"""
from __future__ import annotations
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

ADAPTER_VERSION = "codex-response-usage-v1"


def stamp(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def first_row(path):
    """The whole first line of a rollout, parsed: the row itself (its `timestamp` too), `{}` when the line is not JSON.

    The one reader of a rollout's first line. Anything else (a missing file, bytes that are not UTF-8, a JSON value
    of any type) is returned or raised exactly as `metadata` always did, so its callers see no change."""
    with Path(path).open(encoding="utf-8") as stream:
        first = stream.readline()
    try:
        return json.loads(first)
    except ValueError:
        return {}


def metadata(path):
    row = first_row(path)
    return row.get("payload", {}) if row.get("type") == "session_meta" else {}


def scan(path):
    meta = metadata(path)
    session = meta.get("id")
    usage, tools, events, diagnostics = {}, Counter(), [], []
    model, turn_models, first, last, request_turns = "unknown", {}, None, None, {}
    seen_calls = set()
    with Path(path).open(encoding="utf-8") as stream:
        lines = stream.readlines()
    for line in lines:
        if not line.endswith("\n"):
            break  # a streaming record is not complete yet
        try:
            row = json.loads(line)
        except ValueError:
            diagnostics.append("invalid_json_record")
            continue
        kind, payload, ts = row.get("type"), row.get("payload") or {}, stamp(row.get("timestamp"))
        if not isinstance(payload, dict):
            continue
        if ts:
            first = min(first, ts) if first else ts
            last = max(last, ts) if last else ts
        if kind == "turn_context":
            model = payload.get("model") or "unknown"
            if payload.get("turn_id"):
                turn_models[payload["turn_id"]] = model
        elif kind == "token_usage_record":
            if payload.get("thread_id") != session:
                continue  # don't add inherited/child/parent aggregate usage
            rid, raw = payload.get("response_id"), payload.get("usage")
            if not rid or not isinstance(raw, dict):
                diagnostics.append("missing_response_identity_or_usage")
                continue
            fields = [raw.get(k, 0) for k in ("input_tokens", "cached_input_tokens", "output_tokens",
                                            "reasoning_output_tokens", "cache_write_input_tokens")]
            if any(type(n) is not int or n < 0 for n in fields):
                diagnostics.append("invalid_token_counts")
                continue
            inp, cached, out, reasoning, cache_write = fields
            if cached > inp or reasoning > out or cache_write:
                diagnostics.append("unsupported_cache_or_reasoning_semantics")
                continue
            if raw.get("total_tokens", inp + out) != inp + out:
                diagnostics.append("token_total_mismatch")
                continue
            normalized = {"input_tokens": inp - cached, "cache_read_input_tokens": cached,
                          "output_tokens": out}
            current = (payload.get("model") or turn_models.get(payload.get("turn_id")) or model,
                       normalized, ts)
            if rid in usage and usage[rid][:2] != current[:2]:
                diagnostics.append("conflicting_response_usage")
                continue
            usage.setdefault(rid, current)
            request_turns[rid] = payload.get("turn_id")
        elif kind == "response_item":
            typ = payload.get("type")
            if typ in {"function_call", "custom_tool_call"}:
                call = payload.get("call_id")
                if call and call not in seen_calls:
                    tools[str(payload.get("name") or "unknown")] += 1
                    seen_calls.add(call)
            elif typ == "message" and ts and payload.get("role") in {"user", "assistant"}:
                events.append((ts, "human" if payload["role"] == "user" else "assistant"))
    note = {"adapter": ADAPTER_VERSION, "host_version": meta.get("cli_version"),
            "session_id": session, "source": str(path), "request_turns": request_turns,
            "status": "partial" if diagnostics else "recorded" if usage else "unsupported",
            "diagnostics": sorted(set(diagnostics)), "parent_aggregates": "excluded",
            "reasoning_tokens": "included_in_output", "cached_tokens": "included_in_input_then_split"}
    return usage, dict(tools), [], first, last, events, note
