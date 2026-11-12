#!/usr/bin/env python3
"""task_price.py: the ONE function that prices a task from two independent records (A: the cost
files re-priced at read at the catalogue's list price; B: the CLI's own charge from the driver's
journal) and checks them against each other, per session.

The check is a gate on our own measurers, so its error direction is fixed: a false alarm is
allowed; `agrees` while any comparable session differs, or while nothing was compared, is not.
One named check per requirement (R1..R7), per adversarial input of the spec's section 6 (B1..B13)
and per edge (E*). Every fixture is synthetic and lives in memory or in a temp directory; a cost
file carries a bogus PINNED valuation (999) so that anything reading pinned money shows at once.
"""
import json
import os
import sys
import tempfile
import time
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import cost_capture as CC  # noqa: E402
import driver_journal as DJ  # noqa: E402
import task_price as TP  # noqa: E402

T = "T-1"
MODEL = "claude-sonnet-5-5"          # catalogue: output $10 per 1M tokens -> 100000 output tokens = $1.00
CLOSE = 1e-9

WORK = temp_dir("task-price-")
OLD = WORK / "old.jsonl"
OLD.write_text("{}\n", encoding="utf-8")
os.utime(OLD, (time.time() - 3600, time.time() - 3600))   # written an hour ago: not live
LIVE = WORK / "live.jsonl"
LIVE.write_text("{}\n", encoding="utf-8")                   # written now: still live (< 300 s)


# ---------------------------------------------------------------------------------- fixtures

def req(sid, rid, dollars, stream="orchestrator", activity="unclassified", model=MODEL, provider="anthropic",
        requests=1, usage=None):
    tokens = int(Decimal(str(dollars)) * 100000)
    return {"request_key": f"{provider}:{sid}:{rid}:{stream}", "provider": provider, "session_id": sid,
            "request_id": rid, "stream": stream, "model_id": model, "timestamp": "2026-09-30T05:00:00+00:00",
            "activity_id": activity, "activity_segment_id": activity, "task": "(no task)",
            "usage": usage or {"requests": requests, "input": 0, "output": tokens, "cache_read": 0,
                               "cache_write_5m": 0, "cache_write_1h": 0},
            # a pinned valuation nobody may read: the old project table's 1.5x, here a flat 999
            "valuation": {"subtotal_usd": "999", "pricing_coverage": "complete", "missing_rate_categories": [],
                          "rate_provenance": {"kind": "legacy_project_override"}, "tariff_confirmation": "unconfirmed"}}


def doc(sid, dollars, transcript=OLD, activity="unclassified", **extra):
    """A cost file of one session; `dollars` is a number (one request) or a list of numbers."""
    amounts = dollars if isinstance(dollars, list) else [dollars]
    out = {"session_id": sid, "transcript": str(transcript), "has_factory_activity": True,
           "requests": [req(sid, f"r{i}", d, activity=activity) for i, d in enumerate(amounts)],
           "by_task": {"(no task)": {}}, "external_calls": [], "agents": [], "by_activity": {}}
    out.update(extra)
    return out


def story(sid, dollars, transcript=OLD, **extra):
    """A session no journal names, bound to the task by a story activity segment (orchestrator mode):
    a record A with no record B."""
    return doc(sid, dollars, transcript=transcript, activity="act-T",
               by_activity={"act-T": {"type": "story", "task": T}}, **extra)


def jrow(sid, total, role="qa-runner", kind="role", dispatch="d1", stage="S5", ts="2026-09-30T10:00:00+00:00", **extra):
    out = {"kind": kind, "role": role, "dispatch": dispatch, "stage": stage, "session_id": sid, "num_turns": 1,
           "total_cost_usd": total, "ts": ts}
    out.update(extra)
    return out


def entry(rows, task=T, journals=None):
    names = list(journals or [task])
    return {"task": task, "rows": rows, "journals": names, "no_timestamps": False, "multi_journal": len(names) > 1}


def driver(*sessions):
    """(by_session, spread) as parse_driver_runs builds it: each spec is (sid, [rows])."""
    return {sid: entry(rows) for sid, rows in sessions}, {sid: 1 for sid, _ in sessions}


def price(docs, drv, **kw):
    return TP.task_price(None, T, sessions=docs, driver=drv, **kw)


def col(result, name, key="a_usd"):
    return next((r[key] for r in result["by_agent"] if r["agent"] == name), "absent")


def partition_ok(result):
    """The rows by agent split the totals exactly (the assertion R6 makes of every result)."""
    rows_a = sum(r["a_usd"] or 0.0 for r in result["by_agent"])
    rows_price = sum(r["a_price_usd"] or 0.0 for r in result["by_agent"])
    rows_b = sum(r["b_usd"] or 0.0 for r in result["by_agent"])
    return (abs(rows_a - result["totals"]["a"]) < CLOSE and abs(rows_price - result["totals"]["a_price"]) < CLOSE
            and abs(rows_b - result["totals"]["b"]) < CLOSE)


def verdicts(result):
    return {r["session"]: r["verdict"] for r in result["sessions"]}


def disk_root(journals=None, docs=None, config=None):
    """A project root on disk: journals {task: [rows]} under artifacts/<task>/state, cost files under
    state/cost, an optional config.json."""
    root = Path(tempfile.mkdtemp(prefix="task-price-root-", dir=WORK))
    for task, rows in (journals or {}).items():
        state = root / "qa-factory" / "artifacts" / task / "state"
        state.mkdir(parents=True)
        (state / "driver-runs.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    for sid, body in (docs or {}).items():
        folder = root / "qa-factory" / "state" / "cost"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{sid}.json").write_text(json.dumps(body), encoding="utf-8")
    if config is not None:
        (root / "qa-factory").mkdir(parents=True, exist_ok=True)
        (root / "qa-factory" / "config.json").write_text(json.dumps(config), encoding="utf-8")
    return root


# three sessions that agree: a role, the conductor, the S0 ticket call
def agreeing():
    docs = {"a1": doc("a1", 1.0), "c1": doc("c1", 0.5), "k1": doc("k1", 0.25)}
    drv = driver(("a1", [jrow("a1", 1.0)]),
                 ("c1", [jrow("c1", 0.5, kind="conductor", role="", dispatch="")]),
                 ("k1", [jrow("k1", 0.25, kind="ticket", role="jira", dispatch="", stage="S0")]))
    return docs, drv


# ---------------------------------------------------------------------- R1: the output contract
docs, drv = agreeing()
res = price(docs, drv)
check_eq("R1 the keys of the contract are all present",
         sorted(res), sorted(["status", "sessions", "by_agent", "totals", "differ", "one_record", "unknown",
                              "in_progress", "catalogue_revision", "finding", "compared", "rows_without_session",
                              "rate_overrides", "price_low_usd", "price_high_usd", "external_forms_line",
                              "single_source", "not_estimated_agents"]))   # HF7-5 (DP-5): the new answer field (E2)
check("R1 there is NO price_usd key, ever", "price_usd" not in res)
check_eq("R1 three agreeing sessions: status agrees", res["status"], "agrees")
check("R1 the price keys are numbers and equal when the records agree",
      isinstance(res["price_low_usd"], float) and res["price_low_usd"] == res["price_high_usd"]
      and abs(res["price_low_usd"] - 1.75) < CLOSE, str(res["price_low_usd"]))
check("R1 a session row is {session, agent, stage, a_usd, b_usd, verdict, why} (+ the price column)",
      set(res["sessions"][0]) == {"session", "agent", "stage", "a_usd", "b_usd", "a_price_usd", "verdict", "why"})
check_eq("R1 totals carry a, b, a_comparable, b_comparable (+ a_price)",
         sorted(res["totals"]), ["a", "a_comparable", "a_price", "b", "b_comparable"])
check("R1 by_agent rows carry agent, sessions, a_usd, b_usd, b_unknown (+ marks)",
      {"agent", "sessions", "a_usd", "b_usd", "b_unknown"} <= set(res["by_agent"][0]))
check_eq("R1 the catalogue revision is printed", res["catalogue_revision"], CC.load_catalogue()["catalogue_revision"])
check_eq("R1 compared says what was compared", res["compared"],
         "the CLI's own charge for the 3 sessions the driver's journal names; 0 priced from one record")
check("R1 the lists differ / one_record / unknown / in_progress are empty for agreeing sessions",
      res["differ"] == res["one_record"] == res["unknown"] == res["in_progress"] == [])
check("R1 the rows by agent split the totals", partition_ok(res))

# ------------------------------------------------------------------------------ R2: the sources
docs, drv = agreeing()
check_eq("R2 A is re-priced at read: the pinned 999 is never read", res["sessions"][0]["a_usd"], 1.0)
check("R2 the pinned legacy 1.5x valuation of a cost file reads at the catalogue's price and agrees "
      "(B-225 regression: the cmp1 shape)", res["status"] == "agrees")
check("R2 a sum of ten $0.10 sessions is exactly 1.0: sums are Decimal, never float",
      (lambda r: r["totals"]["a"] == 1.0 and r["price_low_usd"] == 1.0)(
          price({f"s{i}": doc(f"s{i}", 0.1) for i in range(10)},
                driver(*[(f"s{i}", [jrow(f"s{i}", 0.1)]) for i in range(10)]))))
small = price({f"s{i}": doc(f"s{i}", 0.004) for i in range(3)},
              driver(*[(f"s{i}", [jrow(f"s{i}", 0.004)]) for i in range(3)]))
check("R2 nothing is rounded to cents before summing: three $0.004 sessions total 0.012, not 0.0",
      abs(small["totals"]["a"] - 0.012) < CLOSE and abs(small["price_low_usd"] - 0.012) < CLOSE, str(small["totals"]))
OVERRIDE = {"rate_overrides": [{"model_id": MODEL, "aliases": [], "rates": {"input": 4, "output": 20, "cache_read": 0.4,
                                                                          "cache_write_5m": 5, "cache_write_1h": 8}}]}
over = price(docs, drv, cfg=OVERRIDE)
check("R2 with rate_overrides and agreeing usage the PRICE is the override-priced sum: low == high == 2x",
      over["status"] == "agrees" and abs(over["price_low_usd"] - 3.5) < CLOSE and over["price_low_usd"] == over["price_high_usd"],
      str((over["status"], over.get("price_low_usd"), over.get("price_high_usd"))))
check("R2 the CHECK stays at list price: a_usd is list A, a_price_usd is the override price",
      abs(over["totals"]["a"] - 1.75) < CLOSE and abs(over["totals"]["a_price"] - 3.5) < CLOSE)
check_in("R2 the finding says which models are priced at the project's own rate", f"Priced at the project's own rates: {MODEL}",
         over["finding"])
check_eq("R2 rate_overrides lists the model", over["rate_overrides"], [MODEL])
check("R2 the rows by agent split the override price too (P18: price == sum by agent)", partition_ok(over))
over_diff = price({"a1": doc("a1", 1.0)}, driver(("a1", [jrow("a1", 1.2)])), cfg=OVERRIDE)
# CHANGED in t-166 (M1): the range used to mix the list-price B (1.2) with the override-priced A (2.0) and
# read 1.2 .. 2.0, which does not even contain B on the price base. One rate base now: B is scaled to the
# price base, 1.2 * 2.0 / 1.0 = 2.4, so the range is 2.0 .. 2.4.
check("R2 overrides AND a failing check: ONE rate base, B is scaled to the price base (was 1.2 .. 2.0, now 2.0 .. 2.4)",
      over_diff["status"] == "differs" and abs(over_diff["price_low_usd"] - 2.0) < CLOSE
      and abs(over_diff["price_high_usd"] - 2.4) < CLOSE, str((over_diff["price_low_usd"], over_diff["price_high_usd"])))
check("R2 without overrides the price side is list A and a_price equals a",
      res["totals"]["a_price"] == res["totals"]["a"] and res["rate_overrides"] == [])
disk_cfg = disk_root({T: [jrow("a1", 1.0)]}, {"a1": doc("a1", 1.0)}, config={"cost": OVERRIDE})
try:
    from_config = TP.task_price(disk_cfg, T)
finally:
    cleanup(disk_cfg)
check("R2 cfg None reads the project's cost block from config.json: the override is the price",
      from_config["status"] == "agrees" and abs(from_config["price_low_usd"] - 2.0) < CLOSE, str(from_config["price_low_usd"]))
check("R2 cfg={} passed explicitly means the catalogue only",
      abs(price(docs, drv, cfg={})["price_low_usd"] - 1.75) < CLOSE)

# ---------------------------------------------------------------------------- R3: the statuses
check_eq("R3 every session has a record, one compared, none differs: agrees", res["status"], "agrees")
d_one = price({"a1": doc("a1", 1.0), "a2": doc("a2", 1.0)},
              driver(("a1", [jrow("a1", 1.0)]), ("a2", [jrow("a2", 1.3)])))
check_eq("R3 one comparable session differs: differs", d_one["status"], "differs")
check_eq("R3 no comparable session: not_cross_checked", price({"a1": story("a1", 1.0)}, driver())["status"], "not_cross_checked")
neither = price({"a1": doc("a1", 1.0)}, driver(("a1", [jrow("a1", 1.0)]), ("z9", [jrow("z9", None)])))
check_eq("R3 a session in neither record: incomplete", neither["status"], "incomplete")
check_eq("R3 that session is listed as unknown, with the reason", [(r["session"], r["verdict"]) for r in neither["unknown"]],
         [("z9", "unknown")])
check_in("R3 the reason says no cost file and no usable total", "no cost file for this session", neither["unknown"][0]["why"])
check_in("R3 the finding names it", "in neither record", neither["finding"])
check("R3 incomplete is not differs: the range is NOT printed (low == high)",
      neither["price_low_usd"] == neither["price_high_usd"])
empty_id_rows = [jrow("a1", 1.0), jrow("", None, dispatch="d2")]
root = disk_root({T: empty_id_rows}, {"a1": doc("a1", 1.0)})
try:
    bad_row = TP.task_price(root, T)
finally:
    cleanup(root)
check_eq("R3 a journal row with an empty session id (output was not JSON): incomplete", bad_row["status"], "incomplete")
check_eq("R3 ... and the count of such rows is reported", bad_row["rows_without_session"], 1)
check_in("R3 ... with the reason in plain words", "with no session id", bad_row["finding"])
root = disk_root({T: [jrow("a1", 1.0), {"ts": "2026-09-30T10:05:00+00:00", "kind": "delivery", "outcome": "nothing_outward"}]},
                 {"a1": doc("a1", 1.0)})
try:
    with_delivery = TP.task_price(root, T)
finally:
    cleanup(root)
check_eq("R3 a delivery row names no call and is never a missing session: agrees", with_delivery["status"], "agrees")
root = disk_root({T: [jrow("a1", 1.0), jrow("a2", 1.0, dispatch="d2"), jrow(chr(0xFFFD), 0.4, dispatch="d3"),
                      jrow(7, 0.3, dispatch="d4")]}, {"a1": doc("a1", 1.0), "a2": doc("a2", 1.5)})
try:
    both = TP.task_price(root, T)
finally:
    cleanup(root)
check_eq("R3 a row with an undecodable id or an integer id binds no session: counted, never guessed",
         both["rows_without_session"], 2)
check_eq("R3 differs outranks incomplete (the measured gap is the louder fact)", both["status"], "differs")
check_in("R3 ... and the incomplete reason is still told", "with no session id", both["finding"])
check_in("R3 the passed-in journal says its rows without a session id were not looked for",
         "were not looked for", res["finding"])
TP_BUCKET = TP._bucket


def _lossy(buckets, label, _o=TP_BUCKET):
    return _o({}, label) if label.startswith("sub") else _o(buckets, label)


TP._bucket = _lossy
try:
    broken = price({"a1": doc("a1", 1.0, agents=[{"agent": "sub-x", "file": "agent-1.jsonl"}],
                              requests=[req("a1", "r0", 0.6), req("a1", "r1", 0.4, stream="agent-1.jsonl")])},
                   driver(("a1", [jrow("a1", 1.0)])))
finally:
    TP._bucket = TP_BUCKET
check("R3 a partition breach becomes incomplete with the reason, and the price is still printed",
      broken["status"] == "incomplete" and "not a split of the total" in broken["finding"] and "price_low_usd" in broken,
      str((broken["status"], broken["finding"])))
check("R3 the partition helper names both columns of a breach",
      len(TP._partition_reasons({"x": {"a": Decimal("1"), "a_price": Decimal("2")}}, Decimal("3"), Decimal("3"))) == 2)

# ------------------------------------------------------------------------------ R4: the range
ranged = price({"x": doc("x", 1.0), "y": story("y", 0.5)}, driver(("x", [jrow("x", 1.2)])))
check_eq("R4 a differing session and a one-record session: differs", ranged["status"], "differs")
check("R4 a one-record session contributes its one figure to BOTH sums: low 1.5, high 1.7",
      abs(ranged["price_low_usd"] - 1.5) < CLOSE and abs(ranged["price_high_usd"] - 1.7) < CLOSE,
      str((ranged["price_low_usd"], ranged["price_high_usd"])))
only_b = price({"x": doc("x", 1.0)}, driver(("x", [jrow("x", 1.2)]), ("q", [jrow("q", 0.4, role="qa-scout")])))
check("R4 a session known only to the CLI adds its figure to both sums: low 1.4, high 1.6",
      abs(only_b["price_low_usd"] - 1.4) < CLOSE and abs(only_b["price_high_usd"] - 1.6) < CLOSE,
      str((only_b["price_low_usd"], only_b["price_high_usd"])))
check_in("R4 the finding names how many sessions differ", "For 1 of 1 session the transcripts", ranged["finding"])
check_not_in("R4 a count of one is never 'sessions'", "1 of 1 sessions", ranged["finding"])
# Plural by count in every sentence that prints a count of sessions (t-171 item 3): 1 is "session".
one_named = price({"a1": doc("a1", 1.0)}, driver(("a1", [jrow("a1", 1.0)])))
two_named = price({"a1": doc("a1", 1.0), "a2": doc("a2", 1.0)}, driver(("a1", [jrow("a1", 1.0)]), ("a2", [jrow("a2", 1.0)])))
none_named = price({"s1": story("s1", 0.5)}, driver())
check_eq("R4 plural: compared at 1 session", one_named["compared"],
         "the CLI's own charge for the 1 session the driver's journal names; 0 priced from one record")
check_eq("R4 plural: compared at 2 sessions", two_named["compared"],
         "the CLI's own charge for the 2 sessions the driver's journal names; 0 priced from one record")
check_eq("R4 plural: at 0 journal sessions no count is printed at all (the sentence changes, it does not say '0 sessions')",
         none_named["compared"],
         "nothing was compared: the driver's journal names no session of this task; 1 priced from one record")
check_not_in("R4 plural: and never 'the 0 session(s)'", "the 0 session", none_named["compared"])
check_not_in("R4 plural: compared at 1 never says 'the 1 sessions'", "the 1 sessions", one_named["compared"])
one_of_two = price({"x": doc("x", 1.0), "y": doc("y", 0.5)}, driver(("x", [jrow("x", 1.2)]), ("y", [jrow("y", 0.5)])))
two_of_two = price({"x": doc("x", 1.0), "y": doc("y", 0.5)}, driver(("x", [jrow("x", 1.2)]), ("y", [jrow("y", 0.8)])))
check_in("R4 plural: 1 of 2 sessions differ", "For 1 of 2 sessions the transcripts", one_of_two["finding"])
check_in("R4 plural: 2 of 2 sessions differ", "For 2 of 2 sessions the transcripts", two_of_two["finding"])
multi = price({"x": doc("x", 1.0), "y": doc("y", 0.5), "z": doc("z", 2.0)},
              driver(("x", [jrow("x", 1.2, role="qa-runner", stage="S6")]), ("y", [jrow("y", 0.8, role="qa-doc-scribe", stage="S8")]),
                     ("z", [jrow("z", 2.0)])))
check_in("R4 the finding names the largest: session, agent, stage, A and B",
         "The largest is y (qa-doc-scribe, S8): transcripts $0.50, CLI $0.80.", multi["finding"])
check_in("R4 the finding gives the total difference", "The total difference over these sessions is $0.50.", multi["finding"])
check_in("R4 the finding says it is a defect of the factory's measurement, not of the story",
         "This is a defect of the factory's measurement, not a fact about the story.", multi["finding"])
check_in("R4 when every differing session reads lower on the transcripts side it says so",
         "In all of them the transcripts are the lower figure.", multi["finding"])
check("R4 by agent carries two columns and marks the rows holding a differing session",
      col(multi, "qa-doc-scribe", "differing_sessions") == 1 and col(multi, "qa-runner", "differing_sessions") == 1
      and col(multi, "qa-doc-scribe", "b_usd") == 0.8 and col(multi, "qa-doc-scribe") == 0.5)
check("R4 the rows with no differing session are not marked", col(multi, "absent-row", "x") == "absent"
      and all(r["differing_sessions"] == 0 for r in multi["by_agent"] if r["agent"] not in ("qa-doc-scribe", "qa-runner")))
check("R4 while the records differ the price is a RANGE, never one figure: low < high",
      multi["price_low_usd"] < multi["price_high_usd"] and "price_usd" not in multi)
check("R4 the range is the smaller and the larger of the two totals (3.5 vs 4.0)",
      abs(multi["price_low_usd"] - 3.5) < CLOSE and abs(multi["price_high_usd"] - 4.0) < CLOSE)

# ------------------------------------------------------------------ R5: rows by agent (P7, F5)
docs, drv = agreeing()
check_eq("R5 the S0 ticket call is the scout's row, not its own row and not the conductor",
         [r["agent"] for r in res["by_agent"] if r["agent"] in ("ticket", "conductor", "qa-scout")].count("ticket"), 0)
check("R5 ... the ticket session is labelled qa-scout in sessions[]", any(r["agent"] == "qa-scout" for r in res["sessions"]))
check("R5 the conductor is its own row and a role is its own row",
      col(res, "conductor") == 0.5 and col(res, "qa-runner") == 1.0 and col(res, "qa-scout") == 0.25)
sub = price({"a1": doc("a1", 1.0, agents=[{"agent": "qa-helper", "file": "agent-1.jsonl"}],
                       requests=[req("a1", "r0", 0.6), req("a1", "r1", 0.4, stream="agent-1.jsonl")])},
            driver(("a1", [jrow("a1", 1.0)])))
check("R5 a subagent file inside a session is its agentType's row; the main chain keeps the session's label",
      col(sub, "qa-helper") == 0.4 and col(sub, "qa-runner") == 0.6 and partition_ok(sub), str(sub["by_agent"]))
check("R5 the session's B sits on its own label's row once", col(sub, "qa-runner", "b_usd") == 1.0
      and col(sub, "qa-helper", "b_usd") is None)
orch_doc = doc("o1", 0, by_activity={"act-T": {"type": "story", "task": T}, "act-X": {"type": "story", "task": "T-2"}},
               requests=[req("o1", "r0", 0.3, activity="act-T"), req("o1", "r1", 0.2, activity="act-T", stream="agent-9.jsonl"),
                         req("o1", "r2", 5.0, activity="act-X")],
               agents=[{"agent": "qa-scout", "file": "agent-9.jsonl"}])
orch = price({"o1": orch_doc}, driver())
check("R5 an orchestrator-mode main chain is `orchestrator`; its subagent is the agentType",
      col(orch, "orchestrator") == 0.3 and col(orch, "qa-scout") == 0.2 and partition_ok(orch), str(orch["by_agent"]))
check("R5 a session labelled from no journal row at all is `unlabelled`, never dropped",
      col(price({"u1": doc("u1", 1.0)}, driver(("u1", [{"session_id": "u1", "total_cost_usd": 1.0}]))), "unlabelled") == 1.0)
chat = doc("h1", 0, requests=[req("h1", "r0", 0.1), req("h1", "r1", 0.2), req("h1", "r2", 4.0)],
           chat_bindings=[{"task": T, "first_request": "r0", "last_request": "r1", "requests": 2},
                          {"task": "T-2", "first_request": "r2", "last_request": "r2", "requests": 1}])
chatted = price({"h1": chat}, driver())
check("R5 a chat binding is the person's chat row", col(chatted, "person's chat") == 0.30000000000000004
      or abs(col(chatted, "person's chat") - 0.3) < CLOSE, str(chatted["by_agent"]))
# CHANGED in t-166 (F6): `jira-assistant` is a data-fetching agent now (references/agent-labels.json), so its
# remote calls go under qa-scout; this check keeps the `<consumer> (remote)` row with a consumer that is not one.
remote_doc = doc("a1", 1.0, external_calls=[{"external_call_id": "testproject1:1", "consumer_agent": "testproject1-helper",
                                               "invocation_method": "testproject1 assistants chat", "usage_status": "pending",
                                               "observed_at": "2026-09-30T05:00:00+00:00"}])
remote = price({"a1": remote_doc}, driver(("a1", [jrow("a1", 1.0)])))
check("R5 a remote call with no receipt is a row `<consumer_agent> (remote)` with cost unknown (None), never $0",
      col(remote, "testproject1-helper (remote)") is None and col(remote, "testproject1-helper (remote)", "remote_calls") == 1
      and col(remote, "testproject1-helper (remote)", "b_usd") is None, str(remote["by_agent"]))
check("R5 the partition holds with the remote row present", partition_ok(remote))
check_eq("R5 agent_label of a journal record is the one the price function uses",
         DJ.agent_label([jrow("a1", 1.0, kind="ticket", role="jira")]), "qa-scout")

# ------------------------------------------------------------------------ R6: session membership
tagged = doc("t1", 5.0, by_task={T: {"cost": 5.0}}, tasks=[T])
for r in tagged["requests"]:
    r["task"] = T
check_eq("R6 a by_task tag, a marker and the ticket in the data never bind a session (FR-24): nothing is the task's",
         price({"t1": tagged}, driver())["status"], "incomplete")
check("R6 ... no session row appears for it", price({"t1": tagged}, driver())["sessions"] == [])
act_only = price({"o1": orch_doc}, driver())
check("R6 a story activity segment of the task binds those requests only (0.5, not 5.5)",
      abs(act_only["totals"]["a"] - 0.5) < CLOSE and act_only["sessions"][0]["verdict"] == "one_record", str(act_only["totals"]))
check("R6 ... the session has no B: one_record with the reason stated",
      "no driver journal names this session" in act_only["sessions"][0]["why"])
check("R6 a chat binding binds the requests it names only (0.3 of 4.3); the other task's turn is not ours",
      abs(chatted["totals"]["a"] - 0.3) < CLOSE and chatted["sessions"][0]["agent"] == "person's chat")
chat_list = doc("h2", 0, requests=[req("h2", "r0", 0.1), req("h2", "r1", 0.2), req("h2", "r2", 4.0)],
                chat_bindings=[{"task": T, "requests": ["r2"]}])
check("R6 a chat binding that lists its requests binds exactly those",
      abs(price({"h2": chat_list}, driver())["totals"]["a"] - 4.0) < CLOSE)
check("R6 an old cost file with no chat_bindings yields no chat rows",
      all(r["agent"] != "person's chat" for r in price({"a1": doc("a1", 1.0)}, driver(("a1", [jrow("a1", 1.0)])))["by_agent"]))
other = price({"a1": doc("a1", 1.0)}, ({"a1": entry([jrow("a1", 1.0, task="T-2")], task="T-2")}, {"a1": 1}))
check("R6 a session named by another task's journal is not this task's", other["sessions"] == [] and other["status"] == "incomplete")
two_a = [jrow("s1", 1.0, ts="2026-09-30T10:00:00+00:00")]
two_b = [jrow("s1", 1.0, ts="2026-09-30T11:00:00+00:00")]
root = disk_root({T: two_a, "T-2": two_b}, {"s1": doc("s1", 1.0)})
try:
    first_task = TP.task_price(root, T)
    second_task = TP.task_price(root, "T-2")
finally:
    cleanup(root)
check_eq("B10 a session named by two journals is one_record (never compared) under the earlier task",
         verdicts(first_task), {"s1": "one_record"})
check_in("B10 ... the reason says several journals, in words (F7 of t-182: the reader's code is not a person's text)",
         TP.WHY_WORDS[DJ.WHY_SEVERAL_JOURNALS], first_task["sessions"][0]["why"])
check_not_in("B10 ... and never the reader's raw code", DJ.WHY_SEVERAL_JOURNALS, first_task["sessions"][0]["why"])
check("B10 ... and is never counted twice: the later task has no session", second_task["sessions"] == [])
check("B10 ... never agrees", first_task["status"] != "agrees")

# --------------------------------------------------------------- the section 6 battery (B1..B13)
xy = price({"x": doc("x", 1.1), "y": doc("y", 0.9)}, driver(("x", [jrow("x", 1.0)]), ("y", [jrow("y", 1.0)])))
check("B1 +$0.10 on X and -$0.10 on Y: the sums are EQUAL ...",
      abs(xy["totals"]["a_comparable"] - xy["totals"]["b_comparable"]) < CLOSE)
check_eq("B1 ... and the status is differs (a sum-only comparison is killed)", xy["status"], "differs")
check_eq("B1 ... two sessions differ", len(xy["differ"]), 2)
no_b = price({"a1": story("a1", 1.0), "a2": story("a2", 2.0)}, driver())
check_eq("B2 an empty comparable set is not_cross_checked, never agrees", no_b["status"], "not_cross_checked")
check("B2 ... the price is still printed, one record (low == high)", no_b["price_low_usd"] == no_b["price_high_usd"] == 3.0)
check("B2 ... compared says nothing was compared", no_b["compared"].startswith("nothing was compared"))
all_unknown_b = price({"a1": doc("a1", 1.0)}, driver(("a1", [jrow("a1", None)])))
check_eq("B2 every B unknown: not_cross_checked too", all_unknown_b["status"], "not_cross_checked")
fall = price({"a1": doc("a1", 1.0)}, driver(("a1", [jrow("a1", 0.8), jrow("a1", 0.2)])))
check_eq("B3 a falling session is one_record", verdicts(fall), {"a1": "one_record"})
check_in("B3 ... the reason says it falls, in words", TP.WHY_WORDS[DJ.WHY_FALLS], fall["sessions"][0]["why"])
check_in("B3 ... the finding names why B is unknown, in a sentence (F7 of t-182: never `falls: 1`)",
         "CLI's own charge is unknown for 1 session (1 because its figure falls between calls, so it is one call's cost "
         "and not the session's)", " ".join(fall["finding"].split()))
check_not_in("B3 ... and no raw `falls: 1` in it", "falls: 1", fall["finding"])
check("B3 ... priced from A alone, never compared: not agrees", fall["status"] == "not_cross_checked"
      and fall["price_low_usd"] == 1.0)
rising = price({"a1": doc("a1", 1.5), "a2": doc("a2", 0.3)},
               driver(("a1", [jrow("a1", 0.5), jrow("a1", 1.0)]), ("a2", [jrow("a2", 0.3)])))
check_eq("B4 a per-call root whose values RISE (B-222 blind spot): B 1.0 < A 1.5 -> differs", rising["status"], "differs")
check_eq("B4 ... only the rising session differs", [r["session"] for r in rising["differ"]], ["a1"])
double = doc("a1", 0, requests=[req("a1", "r1", 0.3), req("a1", "r2", 0.2),
                                req("a1", "r1", 0.3, stream="agent-1.jsonl"),
                                ], agents=[{"agent": "qa-helper", "file": "agent-1.jsonl"}])
dbl = price({"a1": double}, driver(("a1", [jrow("a1", 0.5)])))
check_eq("B5 A with a sidechain double count (the same requestId in the main file and the agent file): differs",
         dbl["status"], "differs")
check_in("B5 ... the reason names the double count", "two streams", dbl["sessions"][0]["why"])
clean = doc("a1", 0, requests=[req("a1", "r1", 0.3), req("a1", "r2", 0.2, stream="agent-1.jsonl")],
            agents=[{"agent": "qa-helper", "file": "agent-1.jsonl"}])
check_eq("E10 sidechain usage counted ONCE (each request id in one stream): agrees",
         price({"a1": clean}, driver(("a1", [jrow("a1", 0.5)])))["status"], "agrees")
tail = price({"a1": doc("a1", 0.05)}, driver(("a1", [jrow("a1", 0.30)])))
check_eq("B6 A stale by a missing tail (1 of 6 requests, the D5 shape): differs", tail["status"], "differs")
legacy_catalogue = json.loads(json.dumps(CC.load_catalogue()))
for entry_ in legacy_catalogue["entries"]:
    entry_["rates"] = {k: v * 1.5 for k, v in entry_["rates"].items()}
legacy = price({"a1": doc("a1", 1.0)}, driver(("a1", [jrow("a1", 1.0)])), catalogue=legacy_catalogue)
check_eq("B7 A priced at the legacy table's 1.5x (the B-225 regression): differs", legacy["status"], "differs")
check("B7 ... A reads 1.5, B 1.0", abs(legacy["sessions"][0]["a_usd"] - 1.5) < CLOSE and legacy["sessions"][0]["b_usd"] == 1.0)
at = price({"a1": doc("a1", 1.0)}, driver(("a1", [jrow("a1", 1.001)])))
check_eq("B8 |A-B| exactly at the tolerance ($0.001): agrees", at["status"], "agrees")
beyond = price({"a1": doc("a1", 1.0)}, driver(("a1", [jrow("a1", 1.001000001)])))
check_eq("B8 tolerance + 1e-9: differs", beyond["status"], "differs")
check_eq("B8 below by the same amount is symmetric: A - B = tolerance agrees",
         price({"a1": doc("a1", 1.001)}, driver(("a1", [jrow("a1", 1.0)])))["status"], "agrees")
check_eq("B8 $0.004 apart differs: the tolerance is NOT compared after rounding to cents",
         price({"a1": doc("a1", 1.0)}, driver(("a1", [jrow("a1", 1.004)])))["status"], "differs")
check_eq("B8 the tolerance is one named constant, $0.001", TP.TOLERANCE_USD, Decimal("0.001"))
for label, total in (("a bool", True), ("NaN", float("nan")), ("a negative number", -1.0), ("the string 1.0", "1.0"),
                     ("infinity", float("inf"))):
    res9 = price({"a1": doc("a1", 1.0)}, driver(("a1", [jrow("a1", total)])))
    check(f"B9 total_cost_usd as {label}: B unknown, one_record, never agrees",
          verdicts(res9) == {"a1": "one_record"} and res9["status"] == "not_cross_checked" and res9["sessions"][0]["b_usd"] is None,
          str(res9["sessions"]))
chat_b = price({"h1": chat}, driver())
check_eq("B11 a chat-bound session with no B is one_record", verdicts(chat_b), {"h1": "one_record"})
check_eq("B11 ... and the status is not_cross_checked, never agrees", chat_b["status"], "not_cross_checked")
live = price({"a1": doc("a1", 1.0, transcript=LIVE)}, driver(("a1", [jrow("a1", 1.0)])))
check_eq("B12 a live transcript (written inside 300 s): in_progress", verdicts(live), {"a1": "in_progress"})
check_eq("B12 ... nothing comparable: not_cross_checked, never agrees", live["status"], "not_cross_checked")
check_in("B12 ... the finding says it is still being written", "still being written", live["finding"])
check("B12 ... it is in neither comparable total, and listed in in_progress[]",
      live["totals"]["a_comparable"] == 0.0 and [r["session"] for r in live["in_progress"]] == ["a1"])
for bound, stray, why in (("ABC1", "abc1", "a different case"), ("s1 ", "s1", "a trailing space")):
    root = disk_root({T: [jrow(bound, 1.0)]}, {stray: doc(stray, 1.0)})
    try:
        r13 = TP.task_price(root, T)
    finally:
        cleanup(root)
    check(f"B13 the same session id with {why} in the journal is NOT bound",
          [s["session"] for s in r13["sessions"]] == [bound] and r13["sessions"][0]["verdict"] == "one_record"
          and r13["status"] == "not_cross_checked", str(r13["sessions"]))

# ------------------------------------------------------------------------------------------ edges
none_at_all = TP.task_price(None, T)
check_eq("E12 root None and nothing passed: incomplete", none_at_all["status"], "incomplete")
check_in("E12 ... with the reason", "nothing to read", none_at_all["finding"])
root = disk_root()
try:
    nothing = TP.task_price(root, T)
finally:
    cleanup(root)
check_eq("E12 no cost files and no journal: incomplete", nothing["status"], "incomplete")
check_in("E12 ... no session of this task has a record", "no session of this task has a record", nothing["finding"].lower())
check("E12 ... the two price keys are ABSENT", "price_low_usd" not in nothing and "price_high_usd" not in nothing)
check_in("E12 ... compared says nothing was compared", "nothing was compared", nothing["compared"])
check("E12 a task with sessions but zero usage: A = 0, comparable only when B = 0",
      price({"z": doc("z", 0.0)}, driver(("z", [jrow("z", 0.0)])))["status"] == "agrees"
      and price({"z": doc("z", 0.0)}, driver(("z", [jrow("z", 0.5)])))["status"] == "differs")
check("E12 an empty task id is incomplete, not a crash", TP.task_price(None, "", sessions={})["status"] == "incomplete")
live_a = price({"a1": story("a1", 1.0, transcript=LIVE), "a2": doc("a2", 0.5)}, driver(("a2", [jrow("a2", 0.5)])))
check("E7 a live session with one known figure is still in the price, in neither comparable sum",
      abs(live_a["price_low_usd"] - 1.5) < CLOSE and abs(live_a["totals"]["a"] - 1.5) < CLOSE
      and abs(live_a["totals"]["a_comparable"] - 0.5) < CLOSE, str(live_a["totals"]))
check_eq("E7 ... and the rest is compared: a2 agrees, a1 is in_progress", verdicts(live_a), {"a1": "in_progress", "a2": "agrees"})
check_eq("E7 ... a live session does not stop the others from agreeing", live_a["status"], "agrees")
gone = price({"a1": doc("a1", 1.0, transcript=WORK / "no-such-file.jsonl")}, driver(("a1", [jrow("a1", 1.0)])))
check_eq("E7 a transcript that is gone is not live", gone["status"], "agrees")
remote_compared = remote["compared"]
check_in("E13 compared says the price covers the model sessions only", "the price covers the model sessions only", remote_compared)
check_eq("E13 a remote call with no receipt does not stop the model sessions from agreeing", remote["status"], "agrees")
check_in("E13 ... the finding says its cost is unknown and not in the price", "cost is unknown and is not in the price",
         remote["finding"])
remote_partial = doc("o1", 0, by_activity={"act-T": {"type": "story", "task": T}},
                     requests=[req("o1", "r0", 0.3, activity="act-T"), req("o1", "r1", 0.2, activity="act-T")],
                     external_calls=[{"external_call_id": "c1", "consumer_agent": "testproject1-helper", "invocation_method": "m",
                                      "usage_status": "pending", "observed_at": "2026-09-30T05:00:00+00:00"},
                                     {"external_call_id": "c2", "consumer_agent": "testproject1-helper", "invocation_method": "m",
                                      "usage_status": "pending", "observed_at": "2026-09-30T23:00:00+00:00"},
                                     {"external_call_id": "c3", "consumer_agent": "testproject1-helper", "invocation_method": "m",
                                      "usage_status": "pending", "task": T}])
check("E13 in a part of a session only the calls inside the task's own request span count (not a marker)",
      col(price({"o1": remote_partial}, driver()), "testproject1-helper (remote)", "remote_calls") == 1)
collapsed = {"session_id": "g1", "transcript": str(OLD), "has_factory_activity": False, "by_task": {"(no task)": {}},
             "requests": [req("g1", "carry:orchestrator:gpt-6-astra", 0, model="gpt-6-astra", provider="openai", requests=3,
                              usage={"requests": 3, "input": 1000, "output": 1000, "cache_read": 0, "cache_write_5m": 0,
                                     "cache_write_1h": 0})]}
e14 = price({"g1": collapsed}, driver(("g1", [jrow("g1", 0.25)])))
check_eq("E14 a collapsed file of a long-context model with several requests: A unpriced, one_record", verdicts(e14), {"g1": "one_record"})
check_in("E14 ... the reason is printed", "Context tariff requires individual request sizes", e14["sessions"][0]["why"])
check("E14 ... priced from B alone (never $0), never agrees", e14["price_low_usd"] == 0.25 and e14["status"] == "not_cross_checked"
      and e14["sessions"][0]["a_usd"] is None)
root = disk_root({T: [jrow("a1", 9.0)]}, {"a1": doc("a1", 9.0)})
try:
    passed_wins = TP.task_price(root, T, sessions={"a1": doc("a1", 1.0)}, driver=driver(("a1", [jrow("a1", 1.0)])))
    from_disk = TP.task_price(root, T)
finally:
    cleanup(root)
check("E* sessions and driver passed AND root given: the passed values win, nothing is read from disk for them",
      abs(passed_wins["price_low_usd"] - 1.0) < CLOSE and abs(from_disk["price_low_usd"] - 9.0) < CLOSE)
check("E* passing the cost files as a list of docs binds them by their session_id",
      price([doc("a1", 1.0)], driver(("a1", [jrow("a1", 1.0)])))["status"] == "agrees")
check("E* a missing cost file with a journal row is one_record (B alone), never $0",
      (lambda r: verdicts(r) == {"a1": "one_record"} and r["price_low_usd"] == 2.0 and r["sessions"][0]["a_usd"] is None)(
          price({}, driver(("a1", [jrow("a1", 2.0)])))))
check("E* a cost file with no request ledger is A unknown (one_record), never $0",
      (lambda r: verdicts(r) == {"a1": "one_record"} and "no request ledger" in r["sessions"][0]["why"])(
          price({"a1": doc("a1", 1.0, requests=[])}, driver(("a1", [jrow("a1", 1.0)])))))
check("E* a request no rate prices (unknown model) makes A unknown: the known part is never the session",
      (lambda r: r["sessions"][0]["a_usd"] is None and "could not be priced" in r["sessions"][0]["why"])(
          price({"a1": doc("a1", 0, requests=[req("a1", "r0", 1.0), req("a1", "r1", 1.0, model="no-such-model")])},
                driver(("a1", [jrow("a1", 2.0)])))))
legacy_cfg = {"model_prices": {"vendor-model": {"input": 1, "output": 10, "cache_read": 0.1, "cache_write_5m": 1, "cache_write_1h": 1}}}
fam = price({"a1": doc("a1", 0, requests=[req("a1", "r0", 1.0, model="vendor-model-v1")])}, driver(("a1", [jrow("a1", 1.0)])),
            cfg=legacy_cfg)
check("F10 a model the catalogue lacks is priced at the family rate and labelled; the check cannot compare it",
      abs(fam["price_low_usd"] - 1.0) < CLOSE and "family rate" in fam["finding"] and fam["sessions"][0]["a_usd"] is None,
      str(fam["finding"]))
check("one price: with overrides and an agreeing check the range is NOT printed (low == high)",
      over["price_low_usd"] == over["price_high_usd"] and over["status"] == "agrees")
# CHANGED in t-166 (F3): B1 (+$0.10 on one session, -$0.10 on another) used to print low == high == 2.0 while
# the status was `differs`, a range that hid the disagreement. The range is the sum of the per-session
# min and max now, so it is open (1.9 .. 2.1) whenever a session differs.
check("one price: the range is printed ONLY while the check fails (every non-differs status has low == high)",
      all(r["price_low_usd"] == r["price_high_usd"] for r in (res, neither, no_b, fall, live, e14, chat_b))
      and all(r["price_low_usd"] < r["price_high_usd"] for r in (ranged, multi, xy))
      and xy["status"] == "differs" and abs(xy["price_low_usd"] - 1.9) < CLOSE and abs(xy["price_high_usd"] - 2.1) < CLOSE,
      str((xy["price_low_usd"], xy["price_high_usd"])))   # B1: the sums cancel, the per-session range does not

# --------------------------------------------------------------------------- the real-shaped path
root = disk_root({T: [jrow("a1", 1.0, role="qa-runner"), jrow("c1", 0.5, kind="conductor", role="", dispatch="")]},
                 {"a1": doc("a1", 1.0), "c1": doc("c1", 0.5), "ZZ": doc("ZZ", 7.0)})
try:
    on_disk = TP.task_price(root, T)
finally:
    cleanup(root)
check("read from disk: journal and cost files are found under the root, a stray cost file binds nothing",
      on_disk["status"] == "agrees" and abs(on_disk["price_low_usd"] - 1.5) < CLOSE and on_disk["rows_without_session"] == 0
      and sorted(verdicts(on_disk)) == ["a1", "c1"])
check("the module is import-only: no main, no argparse", not hasattr(TP, "main") and "argparse" not in open(TP.__file__, encoding="utf-8").read())

# ================================================================== t-166 attempt 2: the critic's findings
def pair_ok(result):
    """P18 (F4): the price pair of the rows by agent adds up to the task's pair."""
    low = sum(r["price_low_usd"] or 0.0 for r in result["by_agent"])
    high = sum(r["price_high_usd"] or 0.0 for r in result["by_agent"])
    return abs(low - result["price_low_usd"]) < CLOSE and abs(high - result["price_high_usd"]) < CLOSE


def call(cid, consumer, status="pending", cost=None, at="2026-09-30T05:00:00+00:00"):
    out = {"external_call_id": cid, "consumer_agent": consumer, "invocation_method": "m", "usage_status": status,
           "observed_at": at}
    if status == "available":
        out["remote_receipt_ref"] = "rcpt-" + cid
    if cost is not None:
        out["cost_usd"] = cost
    return out


# ---------------------------------------------------------------- M1: ONE rate base in the range
two = price({"s1": doc("s1", 1.0), "s2": doc("s2", 2.0)},
            driver(("s1", [jrow("s1", 1.2)]), ("s2", [jrow("s2", 1.8, role="qa-doc-scribe")])), cfg=OVERRIDE)
check("M1 override + differs: per session B is put on the price base (1.2*2.0/1.0 = 2.4, 1.8*4.0/2.0 = 3.6): "
      "low 2.0 + 3.6, high 2.4 + 4.0",
      two["status"] == "differs" and abs(two["price_low_usd"] - 5.6) < CLOSE and abs(two["price_high_usd"] - 6.4) < CLOSE,
      str((two["status"], two["price_low_usd"], two["price_high_usd"])))
check("M1 ... the range contains the override-priced A total (6.0); the mixed-base range (list-price B 3.0 against A 6.0) "
      "started far below it", two["price_low_usd"] <= two["totals"]["a_price"] <= two["price_high_usd"]
      and two["price_low_usd"] > 5.0)
check("M1 ... without an override the range is unchanged: B scaled by A_price / A = 1 is B itself (1.0 .. 1.2)",
      (lambda r: abs(r["price_low_usd"] - 1.0) < CLOSE and abs(r["price_high_usd"] - 1.2) < CLOSE)(
          price({"a1": doc("a1", 1.0)}, driver(("a1", [jrow("a1", 1.2)])))))
ZERO_RATES = json.loads(json.dumps(CC.load_catalogue()))
for entry_ in ZERO_RATES["entries"]:
    if entry_.get("model_id") == MODEL:
        entry_["rates"] = {k: 0 for k in entry_["rates"]}
zero_a = price({"z1": doc("z1", 1.0)}, driver(("z1", [jrow("z1", 0.5)])), cfg=OVERRIDE, catalogue=ZERO_RATES)
zero_row = zero_a["sessions"][0]
check("M1 edge: a session whose A at list price is $0 while the override prices it ($2.00) cannot scale B: "
      "B is used as it stands, range 0.5 .. 2.0 for it",
      zero_row["a_usd"] == 0.0 and abs(zero_row["a_price_usd"] - 2.0) < CLOSE and zero_a["status"] == "differs"
      and abs(zero_a["price_low_usd"] - 0.5) < CLOSE and abs(zero_a["price_high_usd"] - 2.0) < CLOSE,
      str((zero_a["status"], zero_a["sessions"], zero_a.get("price_low_usd"), zero_a.get("price_high_usd"))))
check("M1 edge: ... the finding says B is used as it stands for it (the session's A is $0, B cannot be scaled)",
      "CLI's charge is used as it stands in the range" in zero_a["finding"], zero_a["finding"])
vendor_cfg = {"rate_overrides": OVERRIDE["rate_overrides"] + [
    {"model_id": "vendor-x", "aliases": [], "rates": {"input": 1, "output": 10, "cache_read": 0.1, "cache_write_5m": 1, "cache_write_1h": 1}}]}
only_override = price({"v1": doc("v1", 0, requests=[req("v1", "r0", 1.0, model="vendor-x")]), "s1": doc("s1", 1.0)},
                      driver(("v1", [jrow("v1", 1.5)]), ("s1", [jrow("s1", 1.2)])), cfg=vendor_cfg)
check("M1 edge: a session whose model only rate_overrides knows (A unknown) gives B as it stands: v1 1.0 .. 1.5, "
      "s1 2.0 .. 2.4 = 3.0 .. 3.9",
      only_override["status"] == "differs" and abs(only_override["price_low_usd"] - 3.0) < CLOSE
      and abs(only_override["price_high_usd"] - 3.9) < CLOSE, str((only_override["status"], only_override["price_low_usd"], only_override["price_high_usd"])))

# ---------------------------------------------------------------- M2: rows with no id, counted from the root
root = disk_root({T: [jrow("a1", 1.0), jrow("", None, dispatch="d2")]}, {"a1": doc("a1", 1.0)})
try:
    read_drv = DJ.parse_driver_runs(root)
    passed = TP.task_price(root, T, driver=read_drv)
    passed_both = TP.task_price(root, T, sessions={"a1": doc("a1", 1.0)}, driver=read_drv)
    no_root = TP.task_price(None, T, sessions={"a1": doc("a1", 1.0)}, driver=read_drv)
finally:
    cleanup(root)
check("M2 root given AND driver passed in (the dashboard's call): the rows with no id are counted from the root's "
      "journal, status incomplete", passed["status"] == "incomplete" and passed["rows_without_session"] == 1
      and "with no session id" in passed["finding"], str((passed["status"], passed["rows_without_session"])))
check("M2 ... and the finding does NOT claim the check was not run", "were not looked for" not in passed["finding"])
check("M2 ... sessions passed in as well: the same", passed_both["status"] == "incomplete" and passed_both["rows_without_session"] == 1)
check("M2 root None and driver passed: nothing to read them from, the finding says the check could not run",
      no_root["rows_without_session"] == 0 and "were not looked for" in no_root["finding"]
      and "no project root" in no_root["finding"] and no_root["status"] == "agrees")
root = disk_root(docs={"a1": story("a1", 1.0)})
try:
    no_journal = TP.task_price(root, T, driver=driver())
finally:
    cleanup(root)
check("M2 edge: a root with no journal file at all: 0 rows with no id and no finding line about them",
      no_journal["rows_without_session"] == 0 and "no session id" not in no_journal["finding"]
      and "not looked for" not in no_journal["finding"], no_journal["finding"])

# ---------------------------------------------------------------- F3 / F4: the range, and the rows' pair
check("F3 while differs, low < high for every differing fixture (never a degenerate range)",
      all(r["status"] == "differs" and r["price_low_usd"] < r["price_high_usd"] for r in (ranged, only_b, multi, xy, over_diff, two)))
for label, result in (("agreeing", res), ("override agrees", over), ("ranged", ranged), ("only B", only_b), ("multi", multi),
                      ("B1", xy), ("override differs", over_diff), ("two overridden", two), ("remote receipt row", remote),
                      ("sub rows", sub), ("orchestrator", orch), ("chat", chatted)):
    check(f"F4 ({label}) the rows by agent carry a price pair that adds up to the task's pair", pair_ok(result),
          str((result["price_low_usd"], result["price_high_usd"], [(r["agent"], r["price_low_usd"], r["price_high_usd"]) for r in result["by_agent"]])))
sub_over = price({"a1": doc("a1", 1.0, agents=[{"agent": "qa-helper", "file": "agent-1.jsonl"}],
                            requests=[req("a1", "r0", 0.6), req("a1", "r1", 0.4, stream="agent-1.jsonl")])},
                 driver(("a1", [jrow("a1", 1.3)])), cfg=OVERRIDE)
check("F4 a session of several rows under an override and a differing check: its range is split over its rows in "
      "proportion to their price (1.2 / 0.8 of 2.0; 1.56 / 1.04 of 2.6)",
      sub_over["status"] == "differs" and pair_ok(sub_over)
      and abs(col(sub_over, "qa-runner", "price_low_usd") - 1.2) < CLOSE and abs(col(sub_over, "qa-runner", "price_high_usd") - 1.56) < CLOSE
      and abs(col(sub_over, "qa-helper", "price_low_usd") - 0.8) < CLOSE and abs(col(sub_over, "qa-helper", "price_high_usd") - 1.04) < CLOSE,
      str(sub_over["by_agent"]))
check("F4 edge: a row of one-record sessions only has low == high (orchestrator 0.5 while the other row differs)",
      col(ranged, "orchestrator", "price_low_usd") == col(ranged, "orchestrator", "price_high_usd") == 0.5
      and col(ranged, "qa-runner", "price_low_usd") < col(ranged, "qa-runner", "price_high_usd"))
check("F4 a B-only session puts its figure on its own row, both ends", col(only_b, "qa-scout", "price_low_usd") == 0.4
      and col(only_b, "qa-scout", "price_high_usd") == 0.4)
check("F4 a row with nothing known has a price pair of None, never $0 (a remote call with no receipt)",
      col(remote, "testproject1-helper (remote)", "price_low_usd") is None and col(remote, "testproject1-helper (remote)", "price_high_usd") is None)
check_in("F4 a breach of the partition (a lost row) also names the price pair, and the status is incomplete",
         "in the low price", broken["finding"])
TP_SPLIT = TP._split
TP._split = lambda parts, total, target: {i: v / 2 for i, v in (TP_SPLIT(parts, total, target) or {}).items()} or None
try:
    lossy_pair = price({"a1": doc("a1", 1.0, agents=[{"agent": "qa-helper", "file": "agent-1.jsonl"}],
                                  requests=[req("a1", "r0", 0.6), req("a1", "r1", 0.4, stream="agent-1.jsonl")])},
                       driver(("a1", [jrow("a1", 1.2)])))
finally:
    TP._split = TP_SPLIT
check("F4 a price pair that does not add up is reported with the reason (status differs here, the reason is in the finding)",
      "in the low price" in lossy_pair["finding"] and "not a split of the total" in lossy_pair["finding"]
      and not pair_ok(lossy_pair), lossy_pair["finding"])
check("F4 the price pair helper names both ends of a breach",
      len(TP._price_pair_reasons({"x": {"lo": Decimal("1"), "hi": Decimal("1"), "pt": Decimal("1")}}, Decimal("2"), Decimal("3"), True)) == 2)

# ---------------------------------------------------------------- F5: a request bound to two tasks is nobody's
contest = doc("k1", 0, by_activity={"act-T": {"type": "story", "task": T}},
              requests=[req("k1", "r0", 0.3, activity="act-T"), req("k1", "r1", 0.2), req("k1", "r2", 0.1)],
              chat_bindings=[{"task": "T-2", "requests": ["r0", "r1"]}, {"task": T, "requests": ["r2"]}])
contest_t1 = TP.task_price(None, T, sessions={"k1": contest}, driver=driver())
contest_t2 = TP.task_price(None, "T-2", sessions={"k1": contest}, driver=driver())
check("F5 a story segment of T-1 and a chat binding of T-2 on one request: counted under NEITHER (T-1 keeps r2 = 0.1, "
      "T-2 keeps r1 = 0.2, r0 = 0.3 is in no price)",
      abs(contest_t1["totals"]["a"] - 0.1) < CLOSE and abs(contest_t2["totals"]["a"] - 0.2) < CLOSE,
      str((contest_t1["totals"], contest_t2["totals"])))
check("F5 ... the finding says which request and which tasks, for each of them",
      all("r0 of k1" in r["finding"] and "T-1 and T-2" in r["finding"] and "counted under none of them" in r["finding"]
          for r in (contest_t1, contest_t2)), contest_t1["finding"])
chat_chat = doc("k2", 0, requests=[req("k2", "r0", 0.3), req("k2", "r1", 0.2)],
                chat_bindings=[{"task": T, "requests": ["r0"]}, {"task": "T-2", "requests": ["r0", "r1"]}])
cc1 = TP.task_price(None, T, sessions={"k2": chat_chat}, driver=driver())
cc2 = TP.task_price(None, "T-2", sessions={"k2": chat_chat}, driver=driver())
check("F5 two chat bindings of two tasks on one request: counted under neither; the task that holds nothing else "
      "has no session and says why", cc1["sessions"] == [] and cc1["status"] == "incomplete"
      and "r0 of k2" in cc1["finding"] and abs(cc2["totals"]["a"] - 0.2) < CLOSE and "r0 of k2" in cc2["finding"],
      str((cc1["sessions"], cc1["finding"])))
same_task = doc("k3", 0, by_activity={"act-T": {"type": "story", "task": T}},
                requests=[req("k3", "r0", 0.3, activity="act-T"), req("k3", "r1", 0.2)],
                chat_bindings=[{"task": T, "requests": ["r0", "r1"]}])
st = TP.task_price(None, T, sessions={"k3": same_task}, driver=driver())
check("F5 edge: the SAME task naming a request twice (its segment and its chat binding) counts it once, not twice and not never",
      abs(st["totals"]["a"] - 0.5) < CLOSE and "counted under none" not in st["finding"], str(st["totals"]))
check("F5 edge: ... and a request of one task only is untouched by the other task's price (a 0.5 session, T-2 has none)",
      TP.task_price(None, "T-2", sessions={"k3": same_task}, driver=driver())["sessions"] == [])

# ---------------------------------------------------------------- F6: remote receipts; data-fetching is the scout's
rec = price({"a1": doc("a1", 1.0, external_calls=[call("c1", "testproject1-helper", "available", 0.25)])},
            driver(("a1", [jrow("a1", 1.0)])))
check("F6 a remote call WITH a receipt is in the price (1.0 + 0.25) at both ends and the models still agree",
      rec["status"] == "agrees" and abs(rec["price_low_usd"] - 1.25) < CLOSE and rec["price_low_usd"] == rec["price_high_usd"]
      and abs(rec["totals"]["a"] - 1.0) < CLOSE, str((rec["status"], rec["price_low_usd"])))
check("F6 ... and in its own row `<consumer> (remote)`: remote_usd 0.25, price pair 0.25, no unknown call",
      col(rec, "testproject1-helper (remote)", "remote_usd") == 0.25 and col(rec, "testproject1-helper (remote)", "price_low_usd") == 0.25
      and col(rec, "testproject1-helper (remote)", "remote_calls") == 0 and pair_ok(rec), str(rec["by_agent"]))
check_in("F6 ... the finding says the receipt is in the price", "left a receipt of $0.25, which is in the price", rec["finding"])
rec_range = price({"a1": doc("a1", 1.0, external_calls=[call("c1", "testproject1-helper", "available", 0.25)])},
                  driver(("a1", [jrow("a1", 1.2)])))
check("F6 a receipt adds the same amount to BOTH ends of a range (1.25 .. 1.45)",
      rec_range["status"] == "differs" and abs(rec_range["price_low_usd"] - 1.25) < CLOSE
      and abs(rec_range["price_high_usd"] - 1.45) < CLOSE and pair_ok(rec_range))
# B-407 D: the line under the price names the agent forms the cost files counted calls for (FR-41); an old file names none
named = price({"a1": doc("a1", 1.0, external_reconciliation={"complete": True, "recognized_forms": ["testproject1", "acme"]})},
              driver(("a1", [jrow("a1", 1.0)])))
check_eq("F6 the price carries `external calls counted for: testproject1, acme` from the cost file's recognized_forms",
         named["external_forms_line"], "external calls counted for: testproject1, acme")
told = price({"a1": doc("a1", 1.0, external_reconciliation={"complete": False, "recognized_forms": ["testproject1"],
                                                            "forms_problem": "cost.external_agent_forms is str, not a list"})},
             driver(("a1", [jrow("a1", 1.0)])))
check_eq("F6 ... and a forms_problem ends the line after a dash",
         told["external_forms_line"], "external calls counted for: testproject1 — cost.external_agent_forms is str, not a list")
# a forms problem means calls of an outside agent may be missing: the price is INCOMPLETE (what is known), never
# one figure that "agrees" (E-D3, FR-41); a pending call alone (complete False, no problem) is said by its own sentence
PROBLEM = "references/external-agent-calls.json is missing, unreadable or has no forms list; only the testproject1 floor is used"
unsure = price({"a1": doc("a1", 1.0, external_reconciliation={"complete": False, "recognized_forms": ["testproject1"],
                                                              "forms_problem": PROBLEM})},
               driver(("a1", [jrow("a1", 1.0)])))
check_eq("F6 a forms_problem makes the price INCOMPLETE where the records agree", unsure["status"], "incomplete")
check_in("F6 ... and the finding names the problem's own text", PROBLEM, unsure["finding"])
check("F6 ... the known figure stays (the floor), 1.0 at both ends",
      unsure["price_low_usd"] == unsure["price_high_usd"] == 1.0, str((unsure["price_low_usd"], unsure["price_high_usd"])))
fine = price({"a1": doc("a1", 1.0, external_reconciliation={"complete": False, "recognized_forms": ["testproject1"]})},
             driver(("a1", [jrow("a1", 1.0)])))
check_eq("F6 edge: complete False with NO forms_problem (a pending call) does not change the status", fine["status"], "agrees")
check_eq("F6 edge: a problem and records that differ is still INCOMPLETE, the range kept",
         (price({"a1": doc("a1", 1.0, external_reconciliation={"forms_problem": PROBLEM})}, driver(("a1", [jrow("a1", 1.2)])))["status"]),
         "incomplete")
check_eq("F6 edge: a cost file captured before the list existed prints nothing (an unknown is not a list of one)",
         price({"a1": doc("a1", 1.0)}, driver(("a1", [jrow("a1", 1.0)])))["external_forms_line"], "")
bad_receipts = price({"a1": doc("a1", 1.0, external_calls=[
    call("c1", "testproject1-helper", "available", "abc"), call("c2", "testproject1-helper", "available", -1.0),
    call("c3", "testproject1-helper", "available", True), call("c4", "testproject1-helper", "available", "NaN"),
    call("c5", "testproject1-helper", "available")])}, driver(("a1", [jrow("a1", 1.0)])))
check("F6 edge: a receipt with no readable cost (text, negative, a bool, NaN, absent) is no receipt: cost unknown, not in the price",
      col(bad_receipts, "testproject1-helper (remote)", "remote_calls") == 5 and abs(bad_receipts["price_low_usd"] - 1.0) < CLOSE
      and col(bad_receipts, "testproject1-helper (remote)", "remote_usd") is None, str(bad_receipts["by_agent"]))
fetch = price({"a1": doc("a1", 1.0, external_calls=[call("c1", "jira-assistant", "available", 0.25), call("c2", "jira-assistant")])},
              driver(("a1", [jrow("a1", 1.0)])))
check("F6 a remote call whose consumer is a data-fetching agent goes under qa-scout, receipt or not (0.25 in the price, "
      "1 call of unknown cost), and has no row of its own",
      col(fetch, "qa-scout", "remote_usd") == 0.25 and col(fetch, "qa-scout", "remote_calls") == 1
      and col(fetch, "jira-assistant (remote)") == "absent" and abs(fetch["price_low_usd"] - 1.25) < CLOSE and pair_ok(fetch),
      str(fetch["by_agent"]))
check_in("F6 ... the receipt-less call still says its cost is unknown (F5 of the forks)", "cost is unknown and is not in the price",
         fetch["finding"])
check_in("F6 ... and `compared` says the price covers the model sessions and the calls with a receipt only (a receipt IS in it)",
         "the price covers the model sessions and the remote calls with a receipt only", fetch["compared"])
sub_fetch = price({"a1": doc("a1", 1.0, agents=[{"agent": "jira-rw-assistant-cli", "file": "agent-1.jsonl"}],
                             requests=[req("a1", "r0", 0.6), req("a1", "r1", 0.4, stream="agent-1.jsonl")])},
                  driver(("a1", [jrow("a1", 1.0)])))
check("F6 a data-fetch subagent type inside a session (jira-rw-assistant-cli) is the scout's row, not its own",
      col(sub_fetch, "qa-scout") == 0.4 and col(sub_fetch, "jira-rw-assistant-cli") == "absent" and col(sub_fetch, "qa-runner") == 0.6
      and partition_ok(sub_fetch))
cased = price({"a1": doc("a1", 1.0, agents=[{"agent": "Jira-Assistant", "file": "agent-1.jsonl"}],
                         requests=[req("a1", "r0", 0.6), req("a1", "r1", 0.4, stream="agent-1.jsonl")],
                         external_calls=[call("c1", "Jira-Assistant")])},
              driver(("a1", [jrow("a1", 1.0)])))
check("F6 edge: names are matched EXACTLY: `Jira-Assistant` is not `jira-assistant`, it keeps its own label (subagent and remote)",
      col(cased, "Jira-Assistant") == 0.4 and col(cased, "Jira-Assistant (remote)", "remote_calls") == 1
      and col(cased, "qa-scout") == "absent", str(cased["by_agent"]))
BROKEN_DOCS = {"a1": doc("a1", 1.0, external_calls=[call("c1", "jira-assistant"), call("c2", "testproject1-helper")])}
BROKEN_DRV = driver(("a1", [jrow("a1", 1.0)]))
SAVED_PATH = DJ.LABELS_PATH
for why, body in (("missing", None), ("not JSON", "{ not json"), ("wrong shape", json.dumps({"data_fetch_kinds": "ticket"})),
                  ("an entry that is not a string", json.dumps({"data_fetch_kinds": [], "data_fetch_agent_types": [7]}))):
    table = WORK / f"labels-{len(why)}.json"
    if body is not None:
        table.write_text(body, encoding="utf-8")
    DJ.LABELS_PATH = table
    try:
        broken_table = price(BROKEN_DOCS, BROKEN_DRV)
    except Exception as exc:   # the contract is: never an exception
        broken_table = {"error": repr(exc), "by_agent": [], "finding": ""}
    finally:
        DJ.LABELS_PATH = SAVED_PATH
    check(f"F6 edge: the agent-label table is {why}: every remote call keeps `<consumer> (remote)`, one warning line, no exception",
          "error" not in broken_table and col(broken_table, "jira-assistant (remote)", "remote_calls") == 1
          and col(broken_table, "testproject1-helper (remote)", "remote_calls") == 1 and col(broken_table, "qa-scout") == "absent"
          and broken_table["finding"].count("agent-label table") == 1, str(broken_table))
check("F6 ... and with the real table in place again the same call is the scout's",
      col(price(BROKEN_DOCS, BROKEN_DRV), "qa-scout", "remote_calls") == 1)
check("F6 a healthy table says nothing in the finding", "agent-label table" not in price(BROKEN_DOCS, BROKEN_DRV)["finding"])

# ---------------------------------------------------------------- F7: the wording for a model only rate_overrides knows
vendor_only = price({"v1": doc("v1", 0, requests=[req("v1", "r0", 1.0, model="vendor-x")])},
                    driver(("v1", [jrow("v1", 1.5)])), cfg=vendor_cfg)
check("F7 a session whose model only rate_overrides knows: the finding says it is priced at the project's own rate for the model",
      "priced at the project's own rate for vendor-x" in vendor_only["finding"], vendor_only["finding"])
check("F7 ... never `unknown to rate_overrides` and never `the CLI's charge alone` when the price is the project's rate",
      "unknown to rate_overrides" not in vendor_only["finding"] and "charge alone" not in vendor_only["finding"]
      and "unknown to rate_overrides" not in vendor_only["sessions"][0]["why"], str((vendor_only["finding"], vendor_only["sessions"][0]["why"])))
check("F7 ... the price is the project's rate (1.0), not the CLI's 1.5; the session is one_record, not compared",
      abs(vendor_only["price_low_usd"] - 1.0) < CLOSE and vendor_only["price_low_usd"] == vendor_only["price_high_usd"]
      and verdicts(vendor_only) == {"v1": "one_record"})
unpriced = price({"v1": doc("v1", 0, requests=[req("v1", "r0", 1.0, model="vendor-x")])}, driver(("v1", [jrow("v1", 1.5)])))
check("F7 control: the same model with NO override is still the CLI's charge alone (the wording is kept where it is true)",
      "their price is the CLI's charge alone" in unpriced["finding"] and abs(unpriced["price_low_usd"] - 1.5) < CLOSE)

# ================================================================== t-182: the critic's findings on the true price
# ---- F6: the tolerance in words, from the constant
check_eq("T182 F6 the tolerance in words is the constant's ($0.001 = a tenth of a cent)", TP.tolerance_words(), "a tenth of a cent")
SAVED_TOLERANCE = TP.TOLERANCE_USD
try:
    TP.TOLERANCE_USD = Decimal("0.005")
    half = TP.tolerance_words()
    TP.TOLERANCE_USD = Decimal("0.0123")
    odd = TP.tolerance_words()
finally:
    TP.TOLERANCE_USD = SAVED_TOLERANCE
check_eq("T182 F6 ... and it follows the constant when the constant moves (half a cent; 1.23 cents)", (half, odd),
         ("half a cent", "1.23 cents"))

# ---- F1: the price base, one rule in one place
D1, D2, D0 = Decimal("1"), Decimal("2"), Decimal("0")
check_eq("T182 F1 B on the price base is B * price / list: 1.2 at list 1.0 and price 2.0 is 2.4, scaled",
         TP.b_on_price_base(D1, D2, Decimal("1.2")), (Decimal("2.4"), True))
check_eq("T182 F1 ... the price IS the list price: B as it stands (scaled: nothing was left over)",
         TP.b_on_price_base(D1, D1, Decimal("1.2")), (Decimal("1.2"), True))
check_eq("T182 F1 edge: the list price is $0 while the price is not: B as it stands, NOT scaled (the session is named)",
         TP.b_on_price_base(D0, D2, Decimal("0.5")), (Decimal("0.5"), False))
check_eq("T182 F1 edge: the list price is unknown (None) while the price is known: the same",
         TP.b_on_price_base(None, D2, Decimal("0.5")), (Decimal("0.5"), False))
check_eq("T182 F1 edge: no price base at all: B is the session's only figure, as it stands", TP.b_on_price_base(None, None, D1), (D1, True))
check_eq("T182 F1 edge: no B: nothing to put on the base", TP.b_on_price_base(D1, D2, None), (None, True))
check_eq("T182 F1 the factor is price / list, None at list price and with no list price to scale by",
         (TP.price_base_factor(D1, D2), TP.price_base_factor(D1, D1), TP.price_base_factor(D0, D2), TP.price_base_factor(None, D2),
          TP.price_base_factor(D1, None)), (D2, None, None, None, None))
check_eq("T182 F1 the range is built by the same function: (2.0 .. 2.4) for list 1.0, price 2.0, B 1.2",
         TP._session_range(D1, D2, Decimal("1.2")), (D2, Decimal("2.4"), True))
factors_o, unscaled_o = TP.session_factors(over_diff)
check_eq("T182 F1 an answer under an override: the session has factor 2 (price 2.0 / list 1.0) and nothing is unscaled",
         ({k: float(v) for k, v in factors_o.items()}, unscaled_o), ({"a1": 2.0}, []))
factors_z, unscaled_z = TP.session_factors(zero_a)
check_eq("T182 F1 edge: a session whose list price is $0 has no factor and is UNSCALED (its charge stands as it is)",
         (factors_z, unscaled_z), ({}, ["z1"]))
check_eq("T182 F1 an answer at list price has no factors and nothing unscaled", TP.session_factors(res), ({}, []))
check_in("T182 F1 edge (i): the finding NAMES the unscaled session (short id), not only the count",
         "For 1 session (z1) the CLI's charge is used as it stands", zero_a["finding"])
check("T182 F1 the answer says whether the price is at the project's own rates: override yes, plain no, a vendor-only rate yes",
      TP.project_rates_applied(over) and TP.project_rates_applied(over_diff) and TP.project_rates_applied(vendor_only)
      and not TP.project_rates_applied(res) and not TP.project_rates_applied({}) and not TP.project_rates_applied(None))

# ---- F3: cents that add up
def hundredths(*values):
    return [Decimal(v) for v in values]


thirds = TP.display_cents([hundredths("0.3333", "0.3333", "0.3333")])
check_eq("T182 F3 three thirds print 34 + 33 + 33 = 100 cents (plain rounding prints 33 x 3 = 99 under a printed $1.00)",
         (thirds, sum(thirds[0])), ([[34, 33, 33]], 100))
check_eq("T182 F3 one row: the row equals the total (half up: 1.005 -> 101)", TP.display_cents([hundredths("1.005")]), [[101]])
check_eq("T182 F3 an unknown figure (None) has no cents and is left out of the sum",
         TP.display_cents([[Decimal("1.0"), None, Decimal("2.0")]]), [[100, None, 200]])
check_eq("T182 F3 a column of nothing known is a column of None", TP.display_cents([[None, None]]), [[None, None]])
import random
rng = random.Random(182)
bad = []
for trial in range(300):
    amounts = [Decimal(rng.randrange(0, 400000)) / Decimal(10000) for _ in range(rng.randrange(1, 14))]
    cents = TP.display_cents([amounts])[0]
    want = int((sum(amounts, Decimal(0))).quantize(Decimal("0.01"), rounding="ROUND_HALF_UP") * 100)
    if sum(cents) != want or any(abs(c - a * 100) >= 1 for c, a in zip(cents, amounts)):
        bad.append((amounts, cents, want))
check_eq("T182 F3 300 seeded columns: every printed column adds up to its total at the cent, and no row moves by a whole cent",
         bad[:1], [])
lo_hi = TP.display_cents([hundredths("0.3345", "0.3345", "0.3345", "0.2"), hundredths("0.3345", "0.3345", "0.3345", "0.403")])
check_eq("T182 F3 a range: low and high are each rounded to their own end (120 and 141 cents) ...",
         (sum(lo_hi[0]), sum(lo_hi[1])), (120, 141))
check_eq("T182 F3 ... and a row whose two ends are exactly equal prints equal cents in both (no range of one row for nothing)",
         (lo_hi[0][:3], lo_hi[1][:3]), ([34, 33, 33], [34, 33, 33]))
low_ends, high_ends = hundredths("1.0146", "2.4436"), hundredths("1.0151", "2.4462")
alone = [TP.display_cents([low_ends])[0], TP.display_cents([high_ends])[0]]
check_eq("T182 F3 control: two INDEPENDENT roundings print a range backwards on the first row (low 102 cents, high 101)",
         alone, [[102, 244], [101, 245]])
pair = TP.display_cents([low_ends, high_ends], None, {1: 0})
check_eq("T182 F3 a range's high end is never below its low end of the same row, and each end still adds up to its own "
         "total (102 + 244 = 346 and 102 + 244 = 346, not 101 + 245)", (pair, sum(pair[0]), sum(pair[1])), ([[102, 244], [102, 244]], 346, 346))
noisy = TP.display_cents([[Decimal("1.6151149999999999"), Decimal("0.3849")], [Decimal("1.615115"), Decimal("0.3849")]])
check_eq("T182 F3 two ends that differ only at the 16th digit (Decimal sums split over rows, then floats) are ONE figure: "
         "no range of nothing, no 'from $1.62 to $1.61'", noisy[0][0] == noisy[1][0], True)
forced = TP.display_cents([[Decimal("0.5"), Decimal("0.5")], [Decimal("0.5"), Decimal("0.5")]], [None, Decimal("1.02")])
check_eq("T182 F3 edge: a lock that would miss the column's target gives way (the column keeps its sum: 51 + 51 = 102)",
         forced, [[50, 50], [51, 51]])
check_eq("T182 F3 edge: a target further than a cent a row from the sum is not forced (defensive: the floors, no crash)",
         TP.display_cents([[Decimal("1.0")]], [Decimal("5.0")]), [[100]])
check_eq("T182 F3 the cents print as dollars with a thousands separator", (TP.usd_from_cents(123456), TP.usd_from_cents(5)), ("$1,234.56", "$0.05"))

# ---- F5: what the contested requests cost
check_in("T182 F5 the contested request is named AND its money is said: r0 of k1 is $0.30 at the catalogue's rates",
         "Their money is in no task's price: the transcripts put it at $0.30 at the catalogue's list rates "
         "(the CLI has no charge for them: no driver journal names their sessions).", contest_t1["finding"])
contest_over = TP.task_price(None, T, sessions={"k1": contest}, driver=driver(), cfg=OVERRIDE)
check_in("T182 F5 under an override both figures are said ($0.30 list, $0.60 at the project's own rates)",
         "$0.30 at the catalogue's list rates and $0.60 at the project's own rates", contest_over["finding"])
vendor_contest = doc("k4", 0, by_activity={"act-T": {"type": "story", "task": T}},
                     requests=[req("k4", "r0", 0.3, activity="act-T", model="vendor-x"), req("k4", "r1", 0.2, model="vendor-x")],
                     chat_bindings=[{"task": "T-2", "requests": ["r0"]}])
vc = TP.task_price(None, T, sessions={"k4": vendor_contest}, driver=driver())
check_in("T182 F5 edge: a contested request the transcripts cannot price is said so, never $0.00",
         "The transcripts could not price them, so their money is unknown and is in no task's price", vc["finding"])
check_not_in("T182 F5 edge: ... and no dollar figure stands for it", "$0.00", vc["finding"])
mixed_contest = doc("k5", 0, by_activity={"act-T": {"type": "story", "task": T}},
                    requests=[req("k5", "r0", 0.3, activity="act-T"), req("k5", "r1", 0.2, activity="act-T", model="vendor-x")],
                    chat_bindings=[{"task": "T-2", "requests": ["r0", "r1"]}])
mc = TP.task_price(None, T, sessions={"k5": mixed_contest}, driver=driver())
check_in("T182 F5 edge: some priced, some not: the priced figure and that it is at least that much",
         "$0.30 at the catalogue's list rates, and 1 request could not be priced, so it is at least that much", mc["finding"])
check_not_in("T182 F5 edge (v): with no contested request there is no such sentence", "Their money is in no task's price", st["finding"])
check_not_in("T182 F5 edge (v): ... nor in a story with nothing shared at all", "no task's price", res["finding"])

# ================================================================== CD1-7: the package's rate table against the price page
# The measurer of "the table is the page" (FR-28): the page's numbers per model, typed here from the
# official page https://platform.claude.com/docs/en/about-claude/pricing as read 2026-10-16 (per 1M
# tokens: input, output, cache read, cache write 5m, cache write 1h), and the REAL references/
# model-rates.json read through the package's own loader. The dated Sonnet 4 id
# (claude-sonnet-4-20250514) is not on that reading's list: it is not asserted here and keeps its older verified_at.
PAGE_2026_10_16 = {
    "claude-sonnet-4-5-20250929": (3, 15, 0.30, 3.75, 6),
    "claude-sonnet-4-6": (3, 15, 0.30, 3.75, 6), "claude-sonnet-5": (2, 10, 0.20, 2.5, 4),
    "claude-sonnet-5-5": (2, 10, 0.10, 2.5, 4), "claude-haiku-4-5-20251001": (1, 5, 0.10, 1.25, 2),
    "claude-opus-4-6": (5, 25, 0.50, 6.25, 10), "claude-opus-4-7": (5, 25, 0.50, 6.25, 10),
    "claude-opus-4-8": (5, 25, 0.50, 6.25, 10), "claude-opus-5-5": (4, 20, 0.20, 5, 8),
    "claude-fable-5-1": (10, 50, 0.25, 12.5, 20), "claude-fable-5": (10, 50, 1.0, 12.5, 20),
    "claude-opus-5": (5, 25, 0.50, 6.25, 10),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125, 0.20),      # the prompt <= 100000 tokens tariff
}
RATE_KEYS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")
FILE_ROWS = {e["model_id"]: e for e in CC.load_catalogue()["entries"]}
for model_id, page in PAGE_2026_10_16.items():
    row = FILE_ROWS.get(model_id, {})
    check_eq(f"CD1-7 the file row of {model_id} equals the page (input, output, cache read, write 5m, write 1h)",
             tuple(row.get("rates", {}).get(k) for k in RATE_KEYS), page)
for model_id in PAGE_2026_10_16:
    check_eq(f"CD1-7 {model_id} was checked against the page on 2026-10-16", FILE_ROWS[model_id]["verified_at"], "2026-10-16")
for model_id, page in PAGE_2026_10_16.items():     # the cache write tiers are the page's 1.25x / 2x of input, every model
    rates = FILE_ROWS[model_id]["rates"]
    check("CD1-7 " + model_id + " cache writes are 1.25x (5m) and 2x (1h) of input",
          abs(rates["cache_write_5m"] - 1.25 * rates["input"]) < 1e-12 and abs(rates["cache_write_1h"] - 2 * rates["input"]) < 1e-12)


def session_a(model, usage):
    """The transcripts' price (A) of one request of `model`, through the package's task_price."""
    full = {"requests": 1, "input": 0, "output": 0, "cache_read": 0, "cache_write_5m": 0, "cache_write_1h": 0}
    full.update(usage)
    res = price({"p1": doc("p1", 0, requests=[req("p1", "r0", 0, model=model, usage=full)])}, driver(("p1", [jrow("p1", 1.0)])))
    return res["sessions"][0]


SMALL = {"input": 1000, "output": 500, "cache_read": 10000}
BIG = dict(SMALL, cache_write_5m=2000, cache_write_1h=3000)
small_a = session_a("claude-sonnet-5-5", SMALL)
check("CD1-7 control Sonnet 5.5, 1000 in + 500 out + 10000 cache read: 1000*2/1e6 + 500*10/1e6 + 10000*0.10/1e6 "
      "= 0.002 + 0.005 + 0.001 = 0.008 USD", abs(small_a["a_usd"] - 0.008) < CLOSE, str(small_a))
check("CD1-7 negative control: the old cache read 0.2 would give 0.009 - the function does NOT return it",
      abs(small_a["a_usd"] - 0.009) > 1e-4)
# BIG adds 2000 write-5m and 3000 write-1h tokens; every figure below is hand-computed from the page
for model_id, expected, arithmetic in (
        ("claude-sonnet-5-5", 0.025, "0.002 + 0.005 + 0.001 + 2000*2.5/1e6 (0.005) + 3000*4/1e6 (0.012)"),
        ("claude-fable-5-1", 0.1225, "0.01 + 0.025 + 0.0025 + 2000*12.5/1e6 (0.025) + 3000*20/1e6 (0.06)"),
        ("claude-opus-5-5", 0.05, "0.004 + 0.01 + 0.002 + 2000*5/1e6 (0.01) + 3000*8/1e6 (0.024)"),
        ("claude-haiku-5-5", 0.0013, "0.0001 + 0.00025 + 0.0001 + 2000*0.125/1e6 (0.00025) + 3000*0.2/1e6 (0.0006)")):
    got = session_a(model_id, BIG)["a_usd"]
    check(f"CD1-7 control {model_id}, 1000 in + 500 out + 10000 read + 2000 w5m + 3000 w1h = {arithmetic} = {expected} USD",
          got is not None and abs(got - expected) < CLOSE, str(got))

# FR-41: a model the table does not list is a NAMED unknown, never a silent $0 and never the known part
unknown_a = session_a("no-such-model", SMALL)
check("CD1-7 an unlisted model: the transcripts' price is unknown (None), not $0", unknown_a["a_usd"] is None, str(unknown_a))
check_in("CD1-7 ... and the session's reason names the model: `rate unknown for no-such-model`",
         "rate unknown for no-such-model", unknown_a["why"])
check_not_in("CD1-7 control: a listed model's reason names no unknown rate", "rate unknown for", small_a["why"])
mixed_unknown = price({"p2": doc("p2", 0, requests=[req("p2", "r0", 1.0), req("p2", "r1", 1.0, model="no-such-model")])},
                      driver(("p2", [jrow("p2", 2.0)])))["sessions"][0]
check("CD1-7 edge: one listed and one unlisted request: the session is unknown and the reason names only the unlisted model",
      mixed_unknown["a_usd"] is None and "rate unknown for no-such-model" in mixed_unknown["why"]
      and "rate unknown for claude-sonnet-5-5" not in mixed_unknown["why"], str(mixed_unknown))
nousage = price({"p3": doc("p3", 0, requests=[dict(req("p3", "r0", 1.0), usage={})])}, driver(("p3", [jrow("p3", 1.0)])))["sessions"][0]
check("CD1-7 edge: a request with no readable usage is unknown too, but its reason does not claim an unknown rate",
      nousage["a_usd"] is None and "rate unknown for" not in nousage["why"], str(nousage))

cleanup(WORK)
finish("task_price")
