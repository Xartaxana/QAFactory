#!/usr/bin/env python3
"""CD1-13 (t-1698 D2-C, K-C4 / K-C4b): an agent that RAN but whose usage was never read makes the price a floor.

`task_price` used to print such a price as exact: the agent entry (tools, tokens 0) was in the cost file and no
code looked at it. Now `not_estimated_agents` names it, the status is `incomplete` (`differs` still wins, E-C6),
the finding says the price is "at least" the figure shown, and an idle agent (no tool calls) is not a gap (E-C5).
Every document is synthetic and in memory; the numbers are fixture numbers, not money anyone paid.
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import task_price as TP  # noqa: E402

WORK = temp_dir("task-price-unest-")
OLD = WORK / "old.jsonl"
OLD.write_text("{}\n", encoding="utf-8")
os.utime(OLD, (time.time() - 3600, time.time() - 3600))   # written an hour ago: not live

T = "T-1"
MODEL = "claude-sonnet-5-5"
AT_LEAST = "at least the figure shown"


def req(sid, rid, dollars):
    tokens = int(dollars * 100000)
    return {"request_key": f"anthropic:{sid}:{rid}:orchestrator", "provider": "anthropic", "session_id": sid,
            "request_id": rid, "stream": "orchestrator", "model_id": MODEL, "timestamp": "2026-09-30T05:00:00+00:00",
            "activity_id": "act-T", "activity_segment_id": "act-T", "task": "(no task)",
            "usage": {"requests": 1, "input": 0, "output": tokens, "cache_read": 0, "cache_write_5m": 0, "cache_write_1h": 0}}


def agent(name, tokens=0, tools=None, task=T, n=0):
    return {"agent": name, "file": f"agent-{n}.jsonl", "task": task, "tokens": tokens, "tools": tools or {}}


def doc(agents, sid="s1", dollars=1.0):
    """A story session (bound to the task by its activity segment, no journal), with the given agents[]."""
    return {"session_id": sid, "transcript": str(OLD), "has_factory_activity": True,
            "requests": [req(sid, "r0", dollars)], "by_task": {"(no task)": {}}, "external_calls": [],
            "agents": agents, "by_activity": {"act-T": {"type": "story", "task": T}}}


def journal(sid, total):
    row = {"kind": "role", "role": "qa-runner", "dispatch": "d1", "stage": "S5", "session_id": sid, "num_turns": 1,
           "total_cost_usd": total, "ts": "2026-09-30T10:00:00+00:00"}
    return ({sid: {"task": T, "rows": [row], "journals": [T], "no_timestamps": False, "multi_journal": False}}, {sid: 1})


def price(docs, drv=None):
    return TP.task_price(None, T, sessions=docs, driver=drv if drv is not None else ({}, {}))


# --- baseline: every agent has usage -> nothing changes
base = price({"s1": doc([agent("qa-factory:qa-scout", tokens=500, tools={"Read": 3})])})
check_eq("K-C4 baseline: an agent with usage is no gap", base["not_estimated_agents"], [])
check("K-C4 baseline: the status is not forced to incomplete", base["status"] != "incomplete", base["status"])
check_not_in("K-C4 baseline: no 'at least' sentence", AT_LEAST, base["finding"])

# --- K-C4: tools and tokens 0
one = price({"s1": doc([agent("qa-factory:qa-case-critic", tools={"Read": 3, "Edit": 2})])})
check_eq("K-C4 the agent is named with its session and its tool calls", one["not_estimated_agents"],
         [{"agent": "qa-factory:qa-case-critic", "session": "s1", "tools": 5}])
check_eq("K-C4 the status is incomplete", one["status"], "incomplete")
check_in("K-C4 the finding says the price is at least the figure", AT_LEAST, one["finding"])
check_in("K-C4 the finding names the agent", "qa-factory:qa-case-critic", one["finding"])
check("K-C4 the price keeps its type and value (a float pair, low == high)",
      isinstance(one["price_low_usd"], float) and one["price_low_usd"] == one["price_high_usd"] == base["price_low_usd"],
      repr((one["price_low_usd"], one["price_high_usd"], base["price_low_usd"])))

# --- E-C5: an idle agent (tools 0, tokens 0) is not a gap; the same agent with no tools key at all
idle = price({"s1": doc([agent("qa-factory:qa-scout", tools={}), agent("qa-factory:qa-scout", tools={"Read": 0}, n=1)])})
check_eq("E-C5 an idle agent is not a gap", idle["not_estimated_agents"], [])
check_eq("E-C5 the status is what it was", idle["status"], base["status"])

# --- an agent of another task is not this task's gap; an agent of a session the journal binds whole is
other = price({"s1": doc([agent("qa-factory:qa-scout", tools={"Read": 3}, task="T-2")])})
check_eq("an agent of another task is not named", other["not_estimated_agents"], [])
bound = price({"s1": doc([agent("qa-factory:qa-scout", tools={"Read": 3}, task="(no task)")], dollars=1.0)}, journal("s1", 1.0))
check_eq("a session bound whole by the journal: its agent is named whatever its own task field says",
         [r["agent"] for r in bound["not_estimated_agents"]], ["qa-factory:qa-scout"])

# --- E-C6: differs wins the status and keeps both sentences
differing = price({"s1": doc([agent("qa-factory:qa-scout", tools={"Read": 3})], dollars=0.0)}, journal("s1", 0.5))
check_eq("E-C6 the status stays differs", differing["status"], "differs")
check_in("E-C6 the finding holds the differs sentence", "differ", differing["finding"])
check_in("E-C6 the finding holds the floor sentence", AT_LEAST, differing["finding"])
check_eq("E-C6 the agent is named", len(differing["not_estimated_agents"]), 1)

# --- K-C4b: the cap of five names, at 5 and at 6
def named(count):
    agents = [agent(f"qa-factory:role-{i}", tools={"Read": 1}, n=i) for i in range(count)]
    return price({"s1": doc(agents)})

five, six = named(5), named(6)
check_eq("K-C4b five agents: five rows", len(five["not_estimated_agents"]), 5)
check("K-C4b five agents: all five names, no 'and more'",
      all(f"qa-factory:role-{i}" in five["finding"] for i in range(5)) and "and more" not in five["finding"].split(AT_LEAST)[0].split("usage was not read")[-1],
      five["finding"])
check_eq("K-C4b six agents: six rows (the key is not capped)", len(six["not_estimated_agents"]), 6)
sentence = six["finding"].split("usage was not read")[-1].split(AT_LEAST)[0]
check("K-C4b six agents: five names and 'and more', the sixth is not named",
      all(f"qa-factory:role-{i}" in sentence for i in range(5)) and "qa-factory:role-5" not in sentence and "and more" in sentence, sentence)

# --- the key is present in every answer, also the empty one
check_eq("the empty answer carries the key too", TP.task_price(None, "")["not_estimated_agents"], [])

cleanup(WORK)
finish("test_task_price_unestimated")
