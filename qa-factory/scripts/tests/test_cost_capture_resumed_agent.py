#!/usr/bin/env python3
"""CD1-13 (t-1698 D2-C, K-C2 / E-C7): a resumed agent's usage is never lost while its tools survive.

The failure the guard closes: an incremental scan keeps tools and events in its checkpoint but NOT the request
rows (those live in the cost file's `requests[]`). When the caller hands the second scan an empty ledger for the
stream while the checkpoint says part of the file was read, the usage of that part was gone and the agent was
priced at zero with its tool calls intact. `scan_file_incremental` now reads such a file again from 0. The
fixture `fixtures/resumed-agent/agent-sample.jsonl` is SYNTHETIC and content-free (see its README.txt).
Measured on the archived 12586 run (see the report): that agent's usage WAS read; the guard is a safety net.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import cost_capture as C  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "resumed-agent" / "agent-sample.jsonl"
RULE = {"flags": ["isMeta", "isCompactSummary"], "notification_prefixes": ["<task-notification>"], "question_tools": []}
WORK = temp_dir("resumed-agent-")
LINES = FIXTURE.read_text(encoding="utf-8").splitlines()


def ledger(usage):
    """What the cost file's requests[] holds for the stream after a scan: one row per request id."""
    return [{"request_id": rid, "model_id": model, "timestamp": ts.isoformat() if ts else None,
             "usage": {"input": u.get("input_tokens", 0), "output": u.get("output_tokens", 0),
                       "cache_read": u.get("cache_read_input_tokens", 0),
                       "cache_write_5m": (u.get("cache_creation") or {}).get("ephemeral_5m_input_tokens", 0),
                       "cache_write_1h": (u.get("cache_creation") or {}).get("ephemeral_1h_input_tokens", 0)}}
            for rid, (model, u, ts) in usage.items()]


def scan(path, prior, prior_usage):
    return C.scan_file_incremental(path, prior, prior_usage, own_chain=True, forms=[], person_rule=RULE)


def total_output(usage):
    return sum(u.get("output_tokens", 0) for _model, u, _ts in usage.values())


path = WORK / "agent-live.jsonl"
path.write_text("\n".join(LINES[:4]) + "\n", encoding="utf-8")
first = scan(path, None, [])
check_eq("fixture: chunk 1 carries two requests", sorted(first[0]), ["req-1", "req-2"])
check("fixture: chunk 1 saw tools", bool(first[1]), str(first[1]))
with path.open("a", encoding="utf-8") as stream:
    stream.write("\n".join(LINES[4:]) + "\n")
full = scan(path, None, [])
check_eq("fixture: a whole-file scan carries all four requests", sorted(full[0]), ["req-1", "req-2", "req-3", "req-4"])

# --- K-C2: the checkpoint holds tools/events, the ledger the caller passes for the stream is empty -> read from 0
lost = scan(path, first[-1], [])
check_eq("K-C2 an empty ledger with a read checkpoint: chunk 1's usage is present (re-read from 0)",
         sorted(lost[0]), ["req-1", "req-2", "req-3", "req-4"])
check_eq("K-C2 the usage equals the whole-file scan, nothing lost, nothing doubled", total_output(lost[0]), total_output(full[0]))
check_eq("K-C2 the tools are not doubled by the re-read", lost[1], full[1])

# --- the guard does not fire on the steady path: the ledger holds chunk 1's rows -> only the new bytes are scanned
seen_lines = []
real_scan_file = C.scan_file


def counting(temp, *args, **kwargs):
    # rows by "\n" and not splitlines(): a Windows text write leaves "\r" before "\n", which splitlines counts twice
    seen_lines.append(len([x for x in Path(temp).read_bytes().decode("utf-8").split("\n") if x.strip()]))
    return real_scan_file(temp, *args, **kwargs)


C.scan_file = counting
try:
    second = scan(path, first[-1], ledger(first[0]))
    scan(path, lost[-1], [])      # E-C7: nothing new, empty ledger, tools in the checkpoint: it reads the file again
finally:
    C.scan_file = real_scan_file
check_eq("steady: the ledger holds chunk 1 -> only the 3 appended lines are parsed", seen_lines[0], 3)
check_eq("steady: the usage is the whole-file usage", sorted(second[0]), sorted(full[0]))
check_eq("E-C7 an empty ledger on a read file errs toward re-reading (all 7 lines)", seen_lines[1], 7)

# --- E-C7: a file legitimately without usage yet is re-read until usage appears, and loses nothing
bare = WORK / "agent-bare.jsonl"
bare.write_text("\n".join(l for l in LINES[:2]).replace('"usage"', '"nousage"') + "\n", encoding="utf-8")
b1 = scan(bare, None, [])
check_eq("E-C7 no usage row: no request", b1[0], {})
with bare.open("a", encoding="utf-8") as stream:
    stream.write(LINES[2] + "\n")
b2 = scan(bare, b1[-1], [])
check_eq("E-C7 the usage that appears later is read", sorted(b2[0]), ["req-2"])
# a checkpoint that counted 0 requests says nothing can be lost: a usage-less file is steady, not re-read; an older
# checkpoint with no count cannot say and is judged by its tools and events (re-read)
steady_lines = []


def counting_bare(temp, *args, **kwargs):
    steady_lines.append(len([x for x in Path(temp).read_bytes().decode("utf-8").split("\n") if x.strip()]))
    return real_scan_file(temp, *args, **kwargs)


bare2 = WORK / "agent-bare2.jsonl"          # still without any usage row (the one above has gained one)
bare2.write_text("\n".join(LINES[:2]).replace('"usage"', '"nousage"') + "\n", encoding="utf-8")
b_bare = scan(bare2, None, [])
C.scan_file = counting_bare
try:
    scan(bare2, b_bare[-1], [])
    uncounted = dict(b_bare[-1])
    uncounted["state"] = {k: v for k, v in b_bare[-1]["state"].items() if k != "requests_seen"}
    scan(bare2, uncounted, [])
finally:
    C.scan_file = real_scan_file
check_eq("E-C7 a usage-less file with a counted checkpoint is steady (nothing new to parse), an uncounted one is re-read",
         steady_lines, [2])

# --- K-C2b pin: a row with no message.model keeps its usage under "?" (unpriced, never dropped)
check_eq("K-C2b a row with no model keeps its usage under '?'", full[0]["req-4"][0], "?")

# --- K-C2c: an agent with tools and no usage reads as tokens 0 with tools: the shape task_price names (test_task_price_unestimated)
tools_only = WORK / "agent-tools-only.jsonl"
tools_only.write_text(LINES[0].replace('"usage"', '"nousage"') + "\n", encoding="utf-8")
t = scan(tools_only, None, [])
check("K-C2c tools seen, usage absent", t[0] == {} and sum(t[1].values()) == 1, repr((t[0], t[1])))

cleanup(WORK)
finish("test_cost_capture_resumed_agent")
