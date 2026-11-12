#!/usr/bin/env python3
"""walk_timing.py - what a manual walk cost in time, calls, tokens and money, per item (t-1957 N2, spec 3.4 and 3.10).

    python walk_timing.py --task <KEY> | --task-root <the story's folder> [--summary] [--json]

Reads, never writes: `state/driver-state.json` `walk_old_road` (items walked on the recorder, left out of every figure), `work/walks/<W>/timing.jsonl` (one line per item written by `walk_session.py verdict`, one `{after_end}` line written
by the driver's after-step), `state/driver-runs.jsonl` (the dispatch's `launched` row and its result rows), the role session's transcript
(found the way `friction.locate` finds it) and the conductor's cost record. Per dispatch: wall = its first `launched` row to the `after_end`
line, divided by its items; the role session's wall alone (launched -> the role's last result) for the comparison with a plain agent that has
no after-step; cost = the LAST `total_cost_usd` per `session_id` (cumulative over resumes). Per item, from the transcript, inside the item's
window [started_at, ended_at): the cost of the requests, the tool calls (plus the dispatch's calls outside every item window divided by its
items), the tokens in four parts (uncached input, cache creation, cache read, output) and the dispatch's final context divided by its items;
the recorder calls and the stops come from `timing.jsonl`. Every figure is grouped by `place` (S6 case, control, explore) and never averaged
across places. A figure that could not be measured says why (FR-41): it is never 0. No `timing.jsonl` at all: "no walk timed for <task>",
exit 0. A line that does not parse is counted and named, never skipped silently. The conductor's spend of the same story is printed
separately when its cost record exists (P18).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cost_capture
import driver_journal
import friction
import hooklib

PARTS = ("uncached_input", "cache_creation", "cache_read", "output")


def _when(value):
    moment = cost_capture.parse_ts(value)
    return moment.replace(tzinfo=timezone.utc) if moment is not None and moment.tzinfo is None else moment


def _rows(path, what, problems) -> list:
    """The object lines of a jsonl file; a line that does not parse is counted in `problems` with its number."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            row = None
        if isinstance(row, dict):
            out.append(row)
        else:
            problems.append(f"{what} line {number} is not a JSON object and was left out")
    return out


def old_road_items(task_root) -> dict:
    """{item: why} the driver marked `walk_old_road` (TR1-4: a lane whose walker session did not open, walked on the recorder as before)
    in `state/driver-state.json`. Their figures are not a walker's and never join a median. Absent or unreadable state: none marked."""
    doc = hooklib.read_json(Path(task_root) / "state" / "driver-state.json", {}, errors=Exception, kind=dict)
    marked = doc.get("walk_old_road") if isinstance(doc, dict) else None
    return {str(k): str(v) for k, v in marked.items()} if isinstance(marked, dict) else {}


def timed_walks(task_root, problems) -> dict:
    """{walk: {"items": [timing line], "after_end": iso|None}} from every `work/walks/<W>/timing.jsonl`; an item marked `walk_old_road`
    is left out (and counted in `old_road`), so no median holds it."""
    out = {}
    old = old_road_items(task_root)
    base = Path(task_root) / "work" / "walks"
    for path in sorted(base.glob("*/timing.jsonl")) if base.is_dir() else []:
        rows = _rows(path, f"work/walks/{path.parent.name}/timing.jsonl", problems)
        out[path.parent.name] = {"items": sorted((r for r in rows if "item" in r and str(r["item"]) not in old), key=lambda r: r.get("index", 0)),
                                 "old_road": sorted(str(r["item"]) for r in rows if "item" in r and str(r["item"]) in old),
                                 "after_end": next((r["after_end"] for r in reversed(rows) if r.get("after_end")), None)}
    return out


def dispatch_facts(task_root, walk, problems) -> dict:
    """From `state/driver-runs.jsonl`: the first `launched` row of the dispatch, the last result row, the session totals."""
    rows = _rows(Path(task_root) / "state" / "driver-runs.jsonl", "state/driver-runs.jsonl", problems)
    launched = next((r for r in rows if r.get("kind") == "launched" and r.get("dispatch_id") == walk), None)
    ends = [r for r in rows if r.get("dispatch") == walk and r.get("exit_code") is not None]
    totals = {}
    for row in rows:
        if row.get("dispatch") == walk and row.get("session_id"):
            value = driver_journal.usable_total(row.get("total_cost_usd"))
            if value is not None:
                totals[str(row["session_id"])] = value          # the LAST value of a session: the total is cumulative over resumes
            else:
                totals.setdefault(str(row["session_id"]), None)
    return {"launched_at": (launched or {}).get("started_at") or (launched or {}).get("ts"),
            "role_end_at": ends[-1].get("ts") if ends else None, "totals": totals,
            "sessions": sorted({str(r["session_id"]) for r in rows if r.get("dispatch") == walk and r.get("session_id")})}


def _seconds(start, end):
    a, b = _when(start), _when(end)
    return None if a is None or b is None else round((b - a).total_seconds(), 1)


def transcript_figures(path, windows, price) -> dict:
    """Per window index: {cost, unpriced, calls, tokens{4}}, plus calls outside every window and the final context of the session."""
    usage_rows = cost_capture.scan_file(Path(path))[0]
    items = {i: {"cost": 0.0, "unpriced": 0, "requests": 0, "calls": 0, "tokens": dict.fromkeys(PARTS, 0)} for i in windows}
    last = None
    for model, usage, ts in usage_rows.values():
        moment = _when(ts)
        if moment is None:
            continue
        if last is None or moment > last[0]:
            last = (moment, usage)
        for i, (start, end) in windows.items():
            if start is not None and end is not None and start <= moment < end:
                row = items[i]
                value = price(model, usage)
                row["requests"] += 1
                row["cost"] += value or 0.0
                row["unpriced"] += 0 if value is not None else 1
                for part, key in zip(PARTS, ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")):
                    row["tokens"][part] += int((usage or {}).get(key) or 0)
    outside = 0
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict) or rec.get("type") != "assistant":
            continue
        content = (rec.get("message") or {}).get("content")
        calls = sum(1 for b in content if isinstance(b, dict) and b.get("type") == "tool_use") if isinstance(content, list) else 0
        moment = _when(rec.get("timestamp"))
        inside = [i for i, (start, end) in windows.items() if moment is not None and start is not None and end is not None and start <= moment < end]
        if inside:
            items[inside[0]]["calls"] += calls
        else:
            outside += calls
    final = None
    if last is not None:
        usage = last[1] or {}
        final = sum(int(usage.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    return {"items": items, "outside_calls": outside, "final_context": final}


def walk_report(task_root, walk, timed, config, problems) -> dict:
    items = timed["items"]
    facts = dispatch_facts(task_root, walk, problems)
    count = len(items) or 1
    wall = _seconds(facts["launched_at"], timed["after_end"])
    role_wall = _seconds(facts["launched_at"], facts["role_end_at"])
    out = {"walk": walk, "items": len(items),
           "wall_s": wall if wall is not None else "not measured: " + ("no `launched` row for this dispatch in state/driver-runs.jsonl"
                                                                        if facts["launched_at"] is None else "the walk has no `after_end` line"),
           "role_wall_s": role_wall if role_wall is not None else "not measured: " + (
               "no `launched` row for this dispatch in state/driver-runs.jsonl" if facts["launched_at"] is None
               else "the driver journal holds no result row of the role"),
           "per_item_wall_s": round(wall / count, 1) if wall is not None else None,
           "per_item_role_wall_s": round(role_wall / count, 1) if role_wall is not None else None}
    totals = facts["totals"]
    if not totals or any(v is None for v in totals.values()):
        out["cost_usd"] = "not measured: " + ("the driver journal names no session of this dispatch" if not totals
                                               else "a session of this dispatch has no usable total_cost_usd")
    else:
        out["cost_usd"] = round(sum(totals.values()), 4)
    windows = {i: (_when(r.get("started_at")), _when(r.get("ended_at"))) for i, r in enumerate(items)}
    price = friction.package_price(config)
    state_dir = Path(task_root).parents[1]
    project_root = Path(task_root).parents[2]
    per = {i: {"cost": 0.0, "unpriced": 0, "calls": 0, "tokens": dict.fromkeys(PARTS, 0)} for i in windows}
    outside, finals, why = 0, [], ""
    for sid in facts["sessions"]:
        path, source = friction.locate(sid, state_dir, project_root)
        if path is None:
            why = f"no transcript found for session {sid} ({source})"
            continue
        got = transcript_figures(path, windows, price)
        outside += got["outside_calls"]
        finals += [got["final_context"]] if got["final_context"] is not None else []
        for i, row in got["items"].items():
            per[i]["cost"] += row["cost"]
            per[i]["unpriced"] += row["unpriced"]
            per[i]["calls"] += row["calls"]
            for part in PARTS:
                per[i]["tokens"][part] += row["tokens"][part]
    if not facts["sessions"]:
        why = "the driver journal names no session of this dispatch"
    measured = not why and bool(facts["sessions"])
    out["final_context"] = round(sum(finals) / count) if measured and finals else f"not measured: {why or 'no usage in the transcript'}"
    rows = []
    for i, line in enumerate(items):
        row = {"item": line.get("item"), "index": line.get("index"), "place": line.get("place") or "case",
               "wall_s": _seconds(line.get("started_at"), line.get("ended_at")), "steps": line.get("steps"),
               "recorder_calls": line.get("batches"), "stops": line.get("stops"), "attempt": line.get("attempt")}
        if measured:
            row["cost_usd"] = (round(per[i]["cost"], 4) if not per[i]["unpriced"]
                               else f"not measured: {per[i]['unpriced']} request(s) of the window have no price")
            row["tool_calls"] = round(per[i]["calls"] + outside / count, 2)
            row["tokens"] = dict(per[i]["tokens"])
        else:
            for key in ("cost_usd", "tool_calls", "tokens"):
                row[key] = f"not measured: {why or 'the transcript holds no request'}"
        rows.append(row)
    out["rows"] = rows
    return out


def conductor_spend(task_root) -> object:
    """The conductor's spend of this story: the cost files of `state/cost/` that name the ticket and are no session of a walk dispatch."""
    ticket = Path(task_root).name
    cost_dir = Path(task_root).parents[1] / "state" / "cost"
    own = set()
    for path in Path(task_root).glob("state/driver-runs.jsonl"):
        own |= {str(r.get("session_id")) for r in _rows(path, "driver-runs.jsonl", []) if r.get("kind") == "role"}
    total, seen = 0.0, 0
    for path in sorted(cost_dir.glob("*.json")) if cost_dir.is_dir() else []:
        doc = hooklib.read_json(path, None, errors=Exception, kind=dict)
        if not doc or path.stem in own or ticket not in (doc.get("by_task") or {}):
            continue
        seen += 1
        for request in doc.get("requests") or []:
            valuation = (request or {}).get("valuation") or {}
            if valuation.get("pricing_coverage") != "complete":
                return "not measured: a request of the conductor's cost record has no complete price"
            total += float(valuation.get("subtotal_usd") or 0)
    return round(total, 4) if seen else "not measured: no cost record of the conductor for this story"


def report(task_root) -> dict:
    task_root = Path(task_root).resolve()
    problems = []
    walks = timed_walks(task_root, problems)
    # F7: an item walked on the old road never opened a session, so it has no timing row: the marks themselves are the list
    old_road = sorted(old_road_items(task_root))
    if not walks:
        return {"task": task_root.name, "timed": False, "text": f"no walk timed for {task_root.name}", "old_road": old_road,
                "problems": problems}
    config = hooklib.read_json(task_root.parents[2] / "qa-factory" / "config.json", {}, kind=dict)
    reports = [walk_report(task_root, walk, timed, config, problems) for walk, timed in sorted(walks.items())]
    places = {}
    for rep in reports:
        for row in rep["rows"]:
            place = places.setdefault(row["place"], {"items": 0, "walls": [], "role_walls": [], "recorder_calls": 0, "stops": 0, "costs": [],
                                                      "tool_calls": [], "unmeasured": set()})
            place["items"] += 1
            place["recorder_calls"] += row.get("recorder_calls") or 0
            place["stops"] += row.get("stops") or 0
            if rep["per_item_wall_s"] is not None:
                place["walls"].append(rep["per_item_wall_s"])
            if rep["per_item_role_wall_s"] is not None:
                place["role_walls"].append(rep["per_item_role_wall_s"])
            for key, bucket in (("cost_usd", "costs"), ("tool_calls", "tool_calls")):
                if isinstance(row.get(key), (int, float)):
                    place[bucket].append(row[key])
                else:
                    place["unmeasured"].add(f"{key}: {row.get(key)}")

    def mean(values):
        return round(sum(values) / len(values), 2) if values else None
    summary = {name: {"items": p["items"], "wall_s_per_item": mean(p["walls"]), "role_wall_s_per_item": mean(p["role_walls"]),
                      "recorder_calls_per_item": round(p["recorder_calls"] / p["items"], 2), "stops_per_item": round(p["stops"] / p["items"], 2),
                      "cost_usd_per_item": mean(p["costs"]), "tool_calls_per_item": mean(p["tool_calls"]), "not_measured": sorted(p["unmeasured"])}
               for name, p in sorted(places.items())}
    return {"task": task_root.name, "timed": True, "dispatches": reports, "places": summary, "conductor_cost_usd": conductor_spend(task_root),
            "old_road": old_road, "problems": problems}


def _old_road_line(data) -> str:
    return (f"left out of every figure (walked on the recorder, not by a walker session): {', '.join(data['old_road'])}"
            if data.get("old_road") else "")


def render(data, summary_only=False) -> str:
    if not data["timed"]:
        return (data["text"] + "".join(f"\n{line}" for line in [_old_road_line(data)] if line)
                + "".join(f"\nnote: {p}" for p in data["problems"]))
    lines = [f"walk timing of {data['task']}"]
    if not summary_only:
        for rep in data["dispatches"]:
            lines.append(f"- {rep['walk']}: {rep['items']} item(s); wall {rep['wall_s']} s, role wall {rep['role_wall_s']} s, cost {rep['cost_usd']}, "
                         f"final context {rep['final_context']}")
            for row in rep["rows"]:
                lines.append(f"    [{row['place']}] {row['item']}: wall {row['wall_s']} s, steps {row['steps']}, recorder calls {row['recorder_calls']}, "
                             f"stops {row['stops']}, tool calls {row['tool_calls']}, cost {row['cost_usd']}, tokens {row['tokens']}")
    for name, p in data["places"].items():
        lines.append(f"place {name}: {p['items']} item(s); per item: wall {p['wall_s_per_item']} s, role wall {p['role_wall_s_per_item']} s, "
                     f"recorder calls {p['recorder_calls_per_item']}, stops {p['stops_per_item']}, tool calls {p['tool_calls_per_item']}, "
                     f"cost {p['cost_usd_per_item']}" + "".join(f"; not measured - {m}" for m in p["not_measured"]))
    if data.get("old_road"):
        lines.append(_old_road_line(data))
    lines.append(f"conductor's spend (separate): {data['conductor_cost_usd']}")
    lines += [f"note: {p}" for p in data["problems"]]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--task", help="the story's key (the name of its folder under the artifact root)")
    parser.add_argument("--task-root", help="the story's folder, qa-factory/artifacts/<KEY>")
    parser.add_argument("--summary", action="store_true", help="the per-place lines only")
    parser.add_argument("--json", action="store_true", help="the whole answer as JSON")
    args = hooklib.exact_options(parser).parse_args(argv)
    task_root = hooklib.story_cli("walk_timing.py", key=args.task, root=args.task_root)
    data = report(task_root)
    print(json.dumps(data, indent=2, ensure_ascii=False) if args.json else render(data, args.summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
