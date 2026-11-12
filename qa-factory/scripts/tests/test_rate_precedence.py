"""Rate precedence and re-pricing at read (B-225, piece Q1 of the true-price spec).

Root cause this guards: `resolve_rate` asked the project's legacy `model_prices` family table
BEFORE the bundled catalogue, so a model the catalogue knows by exact id (claude-sonnet-5-5)
was priced at the project's family rate. On the cmp1 run that table was exactly 1.5 times the
list price in every category, and session 248a7a20 read $0.4784169 where the rate-file figure of that day was $0.3189446
(the CLI's own charge, measured by B-225, was the same $0.3189446) - $24.97 for a story the CLI charged $17.42 for. Since
CD1-7 the bundled file prices Sonnet 5.5 cache reads at the page's $0.10, so its figure is 0.2945653, no longer the CLI's charge.

The rule now: rate_overrides for a named model, then the catalogue by exact id or alias, then
the legacy family table ONLY for a model neither knows, else unpriced. `revalue_document`
re-prices a stored cost file in memory from the usage its request rows carry.

Run: python -B ai-packages/qa-factory/scripts/tests/test_rate_precedence.py
"""
import builtins
import copy
import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cost_capture as C
from harness import check, check_eq, finish, temp_dir, cleanup

PRICE_15 = {"input": 3, "output": 15, "cache_read": 0.3, "cache_write_5m": 3.75, "cache_write_1h": 6}
# The cmp1 project's table: family keys, every category 1.5 times the catalogue's sonnet-5-5.
FAMILY = {"claude-opus": dict(PRICE_15), "claude-sonnet": dict(PRICE_15), "claude-haiku": dict(PRICE_15)}
FAMILY_99 = {"claude": {"input": 99, "output": 99, "cache_read": 99, "cache_write_5m": 99, "cache_write_1h": 99}}
NO_CATALOGUE = {"catalogue_revision": "empty", "entries": []}

CAT = {"catalogue_revision": "test-r1", "entries": [
    {"provider": "anthropic", "model_id": "claude-sonnet-5-5", "aliases": ["sonnet-five-five"],
     "valid_from": None, "valid_to": None,
     "rates": {"input": 2, "output": 10, "cache_read": 0.2, "cache_write_5m": 2.5, "cache_write_1h": 4}},
    {"provider": "anthropic", "model_id": "claude-sonnet-5", "aliases": [], "valid_from": None,
     "valid_to": None, "rates": {"input": 2, "output": 10, "cache_read": 0.2,
                                  "cache_write_5m": 2.5, "cache_write_1h": 4}},
    {"provider": "anthropic", "model_id": "claude-sonnet-4-20250514", "aliases": ["claude-sonnet-4-0"],
     "valid_from": "2025-05-22", "valid_to": None, "rates": {"input": 3, "output": 15}},
    {"provider": "openai", "model_id": "gpt-6-astra", "aliases": [], "valid_from": "2026-09-19",
     "valid_to": None, "rates": {"input": 10, "output": 50, "cache_read": 1.0},
     "long_context": {"threshold_input_tokens": 272000, "scope": "request",
                      "rates": {"input": 20, "output": 75.0, "cache_read": 2.0}}}]}
WINDOWS = {"catalogue_revision": "windows", "entries": [
    {"provider": "anthropic", "model_id": "m-x", "aliases": [], "valid_from": None,
     "valid_to": "2026-01-01", "rates": {"input": 1}},
    {"provider": "anthropic", "model_id": "m-x", "aliases": [], "valid_from": "2026-01-02",
     "valid_to": None, "rates": {"input": 2}}]}

# Session 248a7a20 of cmp1 (section 2 of the spec): usage 10/2115/243793/0/62254.
USAGE_248 = {"requests": 5, "input": 10, "output": 2115, "cache_read": 243793,
             "cache_write_5m": 0, "cache_write_1h": 62254}
TS = "2026-09-30T03:58:17.225000+00:00"
LEGACY_FIGURE = 0.4784169
CATALOGUE_FIGURE = 0.3189446
STALE = {"subtotal_usd": "999", "pricing_coverage": "complete", "missing_rate_categories": [],
         "rate_provenance": {"kind": "legacy_project_override", "revision": "x"},
         "tariff_confirmation": "unconfirmed"}


def usage(input_=0, output=0, cache_read=0, w5=0, w1=0, requests=1):
    return {"requests": requests, "input": input_, "output": output, "cache_read": cache_read,
            "cache_write_5m": w5, "cache_write_1h": w1}


def row(model, use, ts=TS, stream="orchestrator", task="(no task)", activity="unclassified",
        request_id=None, provider=None):
    return {"request_key": f"k:{request_id}", "provider": provider or C.model_provider(model),
            "session_id": "s", "request_id": request_id or f"r{id(use)}", "stream": stream,
            "model_id": model, "timestamp": ts, "activity_id": activity, "activity_segment_id": activity,
            "task": task, "usage": use, "valuation": copy.deepcopy(STALE)}


def stale_models(model, use):
    return {model: dict(use, valuation=copy.deepcopy(STALE), cost=99.0)}


def collapsed_doc(rows, by_task, by_activity, agents=None):
    """The shape capture writes for a session with no factory activity (carry rows)."""
    return {"session_id": "s", "has_factory_activity": False, "usage_status": "provisional",
            "catalogue_revision": "old-rev", "requests": rows, "by_task": by_task,
            "by_activity": by_activity, "orchestrator": {"by_model": {"x": {}}, "cost": 99.0},
            "agents": agents or [], "by_model": {"x": {}}, "total_cost_usd": 99.0,
            "priced_subtotal_usd": 99.0, "pricing_coverage": "complete",
            "external_reconciliation": {"complete": True},
            "reconciliation": {"session_total": 99.0, "orchestrator_plus_agents": 99.0,
                               "tasks_sum": 99.0, "match": None}}


def task_entry(n, cost=99.0):
    return {"tokens": n, "requests": 1, "cost": cost, "priced_subtotal_usd": cost,
            "active_s": 5, "machine_s": 5}


def doc_248():
    """The real file's shape: one carry row, two by_task keys, one by_activity key."""
    carry = row("claude-sonnet-5-5", dict(USAGE_248), request_id="carry:orchestrator:claude-sonnet-5-5")
    carry["valuation"] = {"subtotal_usd": "0.4784169", "pricing_coverage": "complete",
                          "missing_rate_categories": [],
                          "rate_provenance": {"kind": "legacy_project_override", "revision": "x",
                                              "resolution": "longest_match"},
                          "tariff_confirmation": "unconfirmed"}
    doc = collapsed_doc([carry],
        {"(no task)": task_entry(121361, 0.3954), "TP1-13797": task_entry(186811, 0.083)},
        {"unclassified": {"type": "unclassified", "task": None, "status": "unknown", "tokens": 308172,
                          "cost": 0.4784, "active_s": None,
                          "by_model": stale_models("claude-sonnet-5-5", dict(USAGE_248))}})
    doc["total_cost_usd"] = 0.4784
    doc["priced_subtotal_usd"] = LEGACY_FIGURE
    return doc


def per_request_doc(extra_rows=()):
    rows = [row("claude-sonnet-5-5", usage(input_=1_000_000), task="T1", activity="A1", request_id="r1"),
            row("claude-sonnet-5-5", usage(output=100_000), task="T2", activity="A2", request_id="r2"),
            row("claude-sonnet-5-5", usage(input_=500_000), stream="agent-x.jsonl", task="T1",
                activity="A1", request_id="r3"), *extra_rows]
    return {"session_id": "s", "has_factory_activity": True, "usage_status": "actual",
            "catalogue_revision": "old-rev", "requests": rows,
            "external_reconciliation": {"complete": True},
            "orchestrator": {"by_model": {"x": {}}, "cost": 99.0},
            "agents": [{"agent": "qa-x", "file": "agent-x.jsonl", "by_model": {"x": {}}, "cost": 99.0}],
            "by_task": {"T1": task_entry(1, 99.0), "T2": task_entry(1, 99.0)},
            "by_activity": {"A1": {"type": "story", "task": "T1", "tokens": 1, "cost": 99.0, "by_model": {}},
                            "A2": {"type": "story", "task": "T2", "tokens": 1, "cost": 99.0, "by_model": {}}},
            "by_model": {"x": {}}, "total_cost_usd": 99.0,
            "reconciliation": {"session_total": 99.0, "orchestrator_plus_agents": 99.0,
                               "tasks_sum": 99.0, "match": None}}


def dump(value):
    return json.dumps(value, sort_keys=True, default=str)


# --------------------------------------------------------------------------------------------
# R1: resolve_rate precedence
# --------------------------------------------------------------------------------------------
OVERRIDE = {"model_id": "claude-sonnet-5-5", "aliases": ["sonnet-five-five"], "revision": "o1",
            "rates": {"input": 7, "output": 7, "cache_read": 7, "cache_write_5m": 7, "cache_write_1h": 7}}
rates, prov = C.resolve_rate("claude-sonnet-5-5", {"rate_overrides": [OVERRIDE], "model_prices": FAMILY}, CAT)
check("R1 step 1: rate_overrides is asked first, before the catalogue and the legacy table",
      rates and rates["input"] == 7 and prov["kind"] == "project_override")
rates, prov = C.resolve_rate("sonnet-five-five", {"rate_overrides": [OVERRIDE]}, CAT)
check("R1 step 1: an override matches by alias too", rates and rates["input"] == 7 and prov["kind"] == "project_override")
rates, prov = C.resolve_rate("claude-sonnet-5-5", {"model_prices": FAMILY}, CAT)
check("R1 step 2 (B-225): a catalogue-known id is priced by the catalogue, not by the family key",
      rates and rates["input"] == 2 and prov["kind"] == "bundled_exact")
rates, prov = C.resolve_rate("claude-sonnet-4-0", {"model_prices": FAMILY_99}, CAT)
check("E16: a catalogue ALIAS is never priced by a family key either",
      rates and rates["input"] == 3 and prov["kind"] == "bundled_exact" and prov["model_id"] == "claude-sonnet-4-20250514")
rates, prov = C.resolve_rate("claude-sonnet-4-20250514", {"model_prices": FAMILY_99}, CAT, "anthropic",
                             C.parse_ts("2025-01-01T00:00:00+00:00"))
check("E16: a catalogue-known id outside its validity window stays unpriced (alarm), never a family rate",
      rates is None and prov["kind"] == "unpriced" and "family rate is never used" in prov["reason"])
rates, prov = C.resolve_rate("claude-sonnet-4-20250514", {"model_prices": FAMILY_99}, CAT, "other",
                             C.parse_ts("2026-01-01T00:00:00+00:00"))
check("E16: a catalogue-known id asked for another provider stays unpriced, never a family rate", rates is None)
rates, prov = C.resolve_rate("vendor-model-v1", {"model_prices": {"model": {"input": 1, "cache_write": 2}}}, CAT)
check("R1 step 3 / O2: the legacy table prices a model neither override nor catalogue knows",
      rates and rates["input"] == 1 and rates["cache_write_5m"] == 2 and rates["cache_write_1h"] == 2
      and prov["kind"] == "legacy_project_override")
check("O2: the legacy provenance says it priced an unknown model",
      "unknown to rate_overrides and to the catalogue" in prov.get("reason", ""))
rates, prov = C.resolve_rate("claude-sonnet-5-5-x", {"model_prices": FAMILY}, CAT)
check("R1 step 3: a catalogue-unknown suffix of a known id falls to the legacy family key (labelled)",
      rates and rates["input"] == 3 and prov["kind"] == "legacy_project_override")
for unknown in ("claude-sonnet", "claude-sonnet-5-5-x", "claude-opus-5-unknown", "sonnet", "claude-sonnet-5-55", "gpt-6"):
    for table in ({}, {"zzz-no-match": {"input": 1}}):
        rates, prov = C.resolve_rate(unknown, {"model_prices": table}, CAT)
        check(f"E16/R1 step 4: {unknown!r} (substring of / containing a catalogue id) is not priced by "
              f"that entry, table={'none' if not table else 'unrelated'}",
              rates is None and prov["kind"] == "unpriced")
rates, prov = C.resolve_rate("no-such-model", {"model_prices": FAMILY}, CAT)
check("E16: a model neither the catalogue nor the table knows is unpriced, with the reason stated",
      rates is None and prov["kind"] == "unpriced" and "unknown to rate_overrides" in prov["reason"])
for bad_model in (None, "", 7):
    try:
        rates, prov = C.resolve_rate(bad_model, {"model_prices": FAMILY}, CAT)
        check(f"R1 edge: model {bad_model!r} is unpriced, no exception", rates is None and prov["kind"] == "unpriced")
    except Exception as exc:
        check(f"R1 edge: model {bad_model!r} is unpriced, no exception", False, repr(exc))
for bad_cfg in (None, {}, "junk", []):
    try:
        rates, prov = C.resolve_rate("claude-sonnet-5-5", bad_cfg, CAT)
        check(f"R1 edge: cfg {bad_cfg!r} still gets the catalogue rate", rates and rates["input"] == 2)
    except Exception as exc:
        check(f"R1 edge: cfg {bad_cfg!r} still gets the catalogue rate", False, repr(exc))
rates, _ = C.resolve_rate("m-x", {}, WINDOWS, "unknown", C.parse_ts("2025-06-01T00:00:00+00:00"))
rates_b, _ = C.resolve_rate("m-x", {}, WINDOWS, "unknown", C.parse_ts("2026-06-01T00:00:00+00:00"))
rates_none, _ = C.resolve_rate("m-x", {}, WINDOWS, "unknown", None)
check_eq("E16 window: the request's own timestamp decides (before / after the boundary)",
         (rates["input"], rates_b["input"]), (1, 2))
check_eq("E16 window: a request with no timestamp skips the window check, the first entry naming the id "
         "wins (existing behaviour, kept)", rates_none["input"], 1)
check("R1: the legacy helper cost_of still prices through the family table alone (empty catalogue)",
      C.cost_of(dict(USAGE_248), "claude-sonnet-5-5", FAMILY) == LEGACY_FIGURE)

# --------------------------------------------------------------------------------------------
# The real figure: session 248a7a20
# --------------------------------------------------------------------------------------------
check_eq("fixture control: the family table over the same usage gives the legacy figure 0.4784169 "
         "(a catalogue that does not know the model lets the table price it)",
         float(C.value_usage(dict(USAGE_248), "claude-sonnet-5-5", {"model_prices": FAMILY}, NO_CATALOGUE)["subtotal_usd"]),
         LEGACY_FIGURE)
figure = C.value_usage(dict(USAGE_248), "claude-sonnet-5-5", {"model_prices": FAMILY}, CAT)
check_eq("real figure: 248a7a20 usage priced with the family table present = the catalogue's 0.3189446",
         figure["subtotal_usd"], "0.3189446")
check("real figure: the legacy figure 0.4784169 is no longer produced for it",
      float(figure["subtotal_usd"]) != LEGACY_FIGURE)
# The bundled file prices Sonnet 5.5 cache reads at $0.10 (the price page, CD1-7; the test catalogue CAT above keeps
# the old 0.2, so the two figures differ on purpose): 10*2/1e6 + 2115*10/1e6 + 243793*0.10/1e6 + 62254*4/1e6
# = 0.00002 + 0.02115 + 0.0243793 + 0.249016 = 0.2945653 (the CAT figure 0.3189446 has 0.0487586 for the cache read).
bundled = C.value_usage(dict(USAGE_248), "claude-sonnet-5-5", {"model_prices": FAMILY}, None)
check_eq("real figure: against the bundled references/model-rates.json too (the rate-file figure at the page's 0.10; the CLI's own charge measured by B-225 was 0.3189446)",
         bundled["subtotal_usd"], "0.2945653")

# --------------------------------------------------------------------------------------------
# R2: revalue_document on the real shape (collapsed, two by_task keys, one by_activity key)
# --------------------------------------------------------------------------------------------
source = doc_248()
before = dump(source)
out = C.revalue_document(source, {"model_prices": FAMILY}, CAT)
check_eq("R2 real figure: total_cost_usd is 0.3189446, exact (not rounded, not 0.4784169)",
         out["total_cost_usd"], CATALOGUE_FIGURE)
check_eq("R2: priced_subtotal_exact_usd is the exact string", out["priced_subtotal_exact_usd"], "0.3189446")
check_eq("R2: priced_subtotal_usd", out["priced_subtotal_usd"], CATALOGUE_FIGURE)
check("R2: no money in the re-priced document is the legacy figure",
      str(LEGACY_FIGURE) not in dump({k: v for k, v in out.items() if k != "scan_checkpoints"}))
check_eq("R2: by_model carries the catalogue figure and a catalogue provenance",
         (out["by_model"]["claude-sonnet-5-5"]["cost"],
          out["by_model"]["claude-sonnet-5-5"]["valuation"]["rate_provenance"][0]["kind"]),
         (CATALOGUE_FIGURE, "bundled_exact"))
check_eq("R2: the request row's own valuation is replaced", out["requests"][0]["valuation"]["subtotal_usd"], "0.3189446")
check_eq("R2: orchestrator cost", out["orchestrator"]["cost"], CATALOGUE_FIGURE)
check_eq("R2: pricing_coverage", out["pricing_coverage"], "complete")
check_eq("R2: catalogue_revision is the one used", out["catalogue_revision"], "test-r1")
check_eq("O3: repriced_at_read names the revision, the rate source and the ledger shape; no unpriced keys",
         out["repriced_at_read"],
         {"catalogue_revision": "test-r1", "rates": "catalogue", "captured_catalogue_revision": "old-rev",
          "ledger": "collapsed"})
check_eq("O1 (real file): TWO by_task keys on a collapsed ledger -> every cost None with the note, "
         "never a share of the total",
         [(e["cost"], e["priced_subtotal_usd"], e["reprice_note"]) for e in out["by_task"].values()],
         [(None, None, C.COLLAPSED_NOTE)] * 2)
check_eq("O1 (real file): ONE by_activity key = the whole session, exact",
         out["by_activity"]["unclassified"]["cost"], CATALOGUE_FIGURE)
check_eq("R2: reconciliation session_total is re-priced; tasks_sum is unknown, not a partial sum",
         (out["reconciliation"]["session_total"], out["reconciliation"]["tasks_sum"], out["reconciliation"]["match"]),
         (CATALOGUE_FIGURE, None, None))
check_eq("R2 input untouched: the pinned legacy money is still in the source",
         (dump(source) == before, source["total_cost_usd"], source["requests"][0]["valuation"]["subtotal_usd"]),
         (True, 0.4784, "0.4784169"))

single = doc_248()
single["by_task"] = {"TP1-13797": task_entry(308172, 0.4784)}
out = C.revalue_document(single, {"model_prices": FAMILY}, CAT)
check_eq("O1: a collapsed file with EXACTLY ONE by_task key: its cost is the exact session total",
         (out["by_task"]["TP1-13797"]["cost"], out["by_task"]["TP1-13797"]["priced_subtotal_usd"],
          "reprice_note" in out["by_task"]["TP1-13797"]), (CATALOGUE_FIGURE, CATALOGUE_FIGURE, False))
check_eq("O1: ... and the reconciliation then closes on it", out["reconciliation"]["tasks_sum"], CATALOGUE_FIGURE)

many = doc_248()
many["by_task"] = {"A": task_entry(100, 1.0), "B": task_entry(300, 2.0), "C": task_entry(600, 3.0)}
out = C.revalue_document(many, {"model_prices": FAMILY}, CAT)
check_eq("O1 never proportional: three by_task keys of unequal weight are all None, and so is the known part",
         [(e["cost"], e["priced_subtotal_usd"]) for e in out["by_task"].values()], [(None, None)] * 3)
check_eq("O1: the session total stays exact while the split is None", out["total_cost_usd"], CATALOGUE_FIGURE)

# several by_activity keys: the stored per-key usage re-prices exactly when nothing it depends on was lost
two_rows = [row("claude-sonnet-5-5", usage(1_000_000, 100_000, requests=4), request_id="carry:orchestrator:claude-sonnet-5-5")]
acts = {"A1": {"type": "story", "task": "T1", "status": "closed", "tokens": 650000, "cost": 99.0, "active_s": 1,
               "by_model": stale_models("claude-sonnet-5-5", usage(600_000, 50_000, requests=2))},
        "A2": {"type": "story", "task": "T2", "status": "closed", "tokens": 450000, "cost": 99.0, "active_s": 1,
               "by_model": stale_models("claude-sonnet-5-5", usage(400_000, 50_000, requests=2))}}
doc = collapsed_doc(two_rows, {"T1": task_entry(1), "T2": task_entry(1)}, copy.deepcopy(acts))
out = C.revalue_document(doc, {}, CAT)
costs = [out["by_activity"][k]["cost"] for k in ("A1", "A2")]
check_eq("O1 conflict clause: stored per-key usage that re-prices exactly IS priced exactly (1.7 and 1.3)",
         costs, [1.7, 1.3])
check_eq("O1 conflict clause: the parts add up to the session total to the last digit",
         Decimal(str(costs[0])) + Decimal(str(costs[1])), Decimal(str(out["total_cost_usd"])))
check_eq("O1 conflict clause: by_task of the same file is still None (no per-key usage is stored there)",
         [e["cost"] for e in out["by_task"].values()], [None, None])
bad = copy.deepcopy(acts)
bad["A2"]["by_model"]["claude-sonnet-5-5"]["input"] = 399_999
out = C.revalue_document(collapsed_doc(two_rows, {"T1": task_entry(1), "T2": task_entry(1)}, bad), {}, CAT)
check_eq("O1: stored per-key usage that does not add up to the ledger is None with the note",
         [(out["by_activity"][k]["cost"], out["by_activity"][k]["reprice_note"]) for k in ("A1", "A2")],
         [(None, C.COLLAPSED_NOTE)] * 2)
window_rows = [row("m-x", usage(1_000_000, requests=2), ts="2025-06-01T00:00:00+00:00",
                   request_id="carry:orchestrator:m-x"),
               row("m-x", usage(1_000_000, requests=2), ts="2026-06-01T00:00:00+00:00", stream="agent-a.jsonl",
                   request_id="carry:agent-a.jsonl:m-x")]
window_acts = {"A1": {"type": "story", "task": "T1", "tokens": 1, "cost": 99.0,
                      "by_model": stale_models("m-x", usage(1_000_000, requests=2))},
               "A2": {"type": "story", "task": "T2", "tokens": 1, "cost": 99.0,
                      "by_model": stale_models("m-x", usage(1_000_000, requests=2))}}
out = C.revalue_document(collapsed_doc(window_rows, {"T1": task_entry(1), "T2": task_entry(1)}, window_acts,
                                       [{"agent": "a", "file": "agent-a.jsonl", "by_model": {}, "cost": None}]),
                         {}, WINDOWS)
check_eq("O1: a model whose rate changes inside the session (two windows in one ledger) cannot be split: None",
         [out["by_activity"][k]["cost"] for k in ("A1", "A2")], [None, None])
check_eq("R2: ... but the session, orchestrator and agent figures are exact (carry rows keep the stream)",
         (out["total_cost_usd"], out["orchestrator"]["cost"], out["agents"][0]["cost"]), (3.0, 1.0, 2.0))

# --------------------------------------------------------------------------------------------
# E14: a collapsed row of a long-context-tariff model with more than one request
# --------------------------------------------------------------------------------------------
gpt_rows = [row("gpt-6-astra", usage(1000, 100, requests=3), request_id="carry:orchestrator:gpt-6-astra")]
out = C.revalue_document(collapsed_doc(gpt_rows, {"T": task_entry(1)}, {"unclassified": {"type": "unclassified",
                         "by_model": {}, "tokens": 1, "cost": 99.0}}), {}, CAT)
check_eq("E14: the session is unpriced, not guessed (total None, coverage none, known part 0)",
         (out["total_cost_usd"], out["pricing_coverage"], out["priced_subtotal_usd"]), (None, "none", 0.0))
check_eq("E14: the document states the count and the reason",
         (out["repriced_at_read"]["unpriced_requests"], out["repriced_at_read"]["unpriced_reasons"],
          out["repriced_at_read"]["rates"]),
         (1, ["Context tariff requires individual request sizes"], "none"))
check_eq("E14: the single by_task key is None too (an unpriced session has no exact cost)",
         out["by_task"]["T"]["cost"], None)
gpt_one = [row("gpt-6-astra", usage(1000, 100, requests=1), request_id="carry:orchestrator:gpt-6-astra")]
out = C.revalue_document(collapsed_doc(gpt_one, {"T": task_entry(1)}, {}), {}, CAT)
check_eq("E14 control: the same row with ONE request is priced (short band), so the refusal follows the count",
         out["total_cost_usd"], 0.015)

# --------------------------------------------------------------------------------------------
# Q1 fix (a): a MIXED ledger (carry rows AND per-request rows) is not a collapsed one
# --------------------------------------------------------------------------------------------
SONNET = "claude-sonnet-5-5"


def mixed_rows():
    return [row(SONNET, usage(input_=1_000_000, requests=4), task="T1", activity="A1",
                request_id="carry:orchestrator:" + SONNET),
            row(SONNET, usage(input_=500_000), task="T1", activity="A1", request_id="r2"),
            row(SONNET, usage(output=100_000), task="T2", activity="A2", request_id="r3")]


def tokens_entry(tokens):
    return dict(task_entry(tokens), tokens=tokens)


out = C.revalue_document(collapsed_doc(mixed_rows(), {"T1": tokens_entry(1_500_000), "T2": tokens_entry(100_000)}, {}),
                         {}, CAT)
check_eq("Q1a (mutation e): carry rows AND per-request rows read 'mixed', never 'collapsed'",
         out["repriced_at_read"]["ledger"], "mixed")
check_eq("Q1a (mutation e): by_task is priced per key from its rows when the stored tokens equal the row sums "
         "(T1 = carry 1M + 0.5M input, T2 = 100k output)",
         [(out["by_task"][k]["cost"], "reprice_note" in out["by_task"][k]) for k in ("T1", "T2")],
         [(3.0, False), (1.0, False)])
check_eq("Q1a: the session total is exact and the parts add up to it", out["total_cost_usd"], 4.0)
out = C.revalue_document(collapsed_doc(mixed_rows(), {"T1": tokens_entry(1_500_000)}, {}), {}, CAT)
check_eq("Q1a (mutation e): a mixed file with ONE by_task key prices that key from ITS rows (3.0), not the "
         "whole session (4.0): the one-key shortcut belongs to a fully collapsed ledger",
         out["by_task"]["T1"]["cost"], 3.0)
out = C.revalue_document(collapsed_doc(mixed_rows(), {"T1": tokens_entry(1_400_000), "T2": tokens_entry(100_000)}, {}),
                         {}, CAT)
check_eq("Q1a edge: stored tokens that do NOT equal the row sums -> None with the note; the other key is unaffected",
         [(out["by_task"][k]["cost"], out["by_task"][k]["priced_subtotal_usd"], out["by_task"][k].get("reprice_note"))
          for k in ("T1", "T2")],
         [(None, None, C.MIXED_SPLIT_NOTE), (1.0, 1.0, None)])
no_tokens = tokens_entry(100_000)
del no_tokens["tokens"]
out = C.revalue_document(collapsed_doc(mixed_rows(), {"T1": tokens_entry(1_500_000), "T9": tokens_entry(7),
                                                      "T2": no_tokens}, {}), {}, CAT)
check_eq("Q1a edge: a key with stored tokens but NO rows is None (the existing note); a key whose stored "
         "tokens are missing is None with the split note",
         [(out["by_task"][k]["cost"], out["by_task"][k]["reprice_note"]) for k in ("T9", "T2")],
         [(None, "no request rows carry this task"), (None, C.MIXED_SPLIT_NOTE)])
out = C.revalue_document(collapsed_doc(mixed_rows(), {"T1": tokens_entry(1_500_000)}, {}), {}, CAT)
check_eq("Q1a: the session figure of a mixed file is unchanged by the split rule",
         (out["total_cost_usd"], out["orchestrator"]["cost"]), (4.0, 4.0))
unreadable = mixed_rows()
unreadable[1]["usage"] = {"input": True}
out = C.revalue_document(collapsed_doc(unreadable, {"T1": tokens_entry(1_500_000)}, {}), {}, CAT)
check_eq("Q1a edge: a row of the key with unreadable usage -> the key is None, never a partial figure",
         out["by_task"]["T1"]["cost"], None)
for rows_, label in (([], "empty"), (None, "absent")):
    body = collapsed_doc(mixed_rows(), {"T1": tokens_entry(1)}, {})
    if rows_ is None:
        body.pop("requests")
    else:
        body["requests"] = rows_
    check_eq(f"Q1a control: the {label} ledger still reads {label}", C.revalue_document(body, {}, CAT)["repriced_at_read"]["ledger"], label)

# --------------------------------------------------------------------------------------------
# Q1 fix (b): the long_context guard of the collapsed by_activity split
# --------------------------------------------------------------------------------------------
gpt_acts = {"A1": {"type": "story", "task": "T1", "tokens": 1, "cost": 99.0,
                   "by_model": stale_models("gpt-6-astra", usage(500, 50, requests=1))},
            "A2": {"type": "story", "task": "T2", "tokens": 1, "cost": 99.0,
                   "by_model": stale_models("gpt-6-astra", usage(500, 50, requests=1))}}
gpt_two = [row("gpt-6-astra", usage(1000, 100, requests=2), request_id="carry:orchestrator:gpt-6-astra")]
out = C.revalue_document(collapsed_doc(gpt_two, {"T1": task_entry(1), "T2": task_entry(1)}, copy.deepcopy(gpt_acts)),
                         {}, CAT)
check_eq("Q1b (mutation f): a long-context-tariff model cannot be split by activity even when the stored "
         "per-activity usage adds up to the carry row: the band depends on request sizes the collapse "
         "threw away, so both activities are None with the note (never a short-band figure)",
         [(out["by_activity"][k]["cost"], out["by_activity"][k].get("reprice_note")) for k in ("A1", "A2")],
         [(None, C.COLLAPSED_NOTE)] * 2)
check_eq("Q1b control: the same shape on a model WITHOUT a long-context tariff splits exactly (the guard "
         "is the only difference)",
         [C.revalue_document(collapsed_doc(
             [row(SONNET, usage(1000, 100, requests=2), request_id="carry:orchestrator:" + SONNET)],
             {"T1": task_entry(1), "T2": task_entry(1)},
             {k: dict(v, by_model=stale_models(SONNET, usage(500, 50, requests=1))) for k, v in copy.deepcopy(gpt_acts).items()}),
             {}, CAT)["by_activity"][k]["cost"] for k in ("A1", "A2")],
         [0.0015, 0.0015])

# --------------------------------------------------------------------------------------------
# Q1 fix (d): a carry row of N > 1 requests is the SUM of its requests' valuations
# --------------------------------------------------------------------------------------------
RAW_100K = {"input_tokens": 100_000, "output_tokens": 1000, "cache_read_input_tokens": 0,
            "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}}


def requests_of(model, count, raw=RAW_100K, provider=None):
    return [C.request_record(provider or C.model_provider(model), "s", f"r{i}", "orchestrator", model, raw,
                             C.parse_ts(TS), "unclassified", "unclassified", "(no task)", {}, CAT)
            for i in range(count)]


members = requests_of("gpt-6-astra", 3)
check_eq("Q1d fixture: each of the three requests is in the SHORT band (100k input < 272k) and costs 1.05",
         [m["valuation"]["subtotal_usd"] for m in members], ["1.05"] * 3)
as_one = C.value_usage({"requests": 1, "input": 300_000, "output": 3000, "cache_read": 0,
                        "cache_write_5m": 0, "cache_write_1h": 0}, "gpt-6-astra", {}, CAT, "openai", C.parse_ts(TS))
check_eq("Q1d fixture: the summed tokens read as ONE request fall into the long band (6.225): the old pin",
         as_one["subtotal_usd"], "6.225")
carry = C.collapse_requests(members, "s", {}, CAT)
check_eq("Q1d: three requests fold into ONE carry row that says it carries three",
         (len(carry), carry[0]["usage"]["requests"], carry[0]["usage"]["input"]), (1, 3, 300_000))
check_eq("Q1d (mutation h): the carry row is priced as the SUM of its requests (3.15), never as one "
         "long-context request (6.225)", carry[0]["valuation"]["subtotal_usd"], "3.15")
check_eq("Q1d: the row says its cost is a sum and of how many requests, and it is completely priced",
         (carry[0]["valuation"].get("priced_as"), carry[0]["valuation"].get("requests_priced"),
          carry[0]["valuation"]["pricing_coverage"], carry[0]["valuation"]["rate_provenance"]["kind"]),
         ("sum_of_requests", 3, "complete", "bundled_exact"))
partly = requests_of("gpt-6-astra", 3)
partly[1]["valuation"] = C._unpriced_valuation("test: no rate", "unconfirmed")
carry = C.collapse_requests(partly, "s", {}, CAT)
check_eq("Q1d edge: one request unpriced at collapse -> the row keeps only the known part (2.10), says it is "
         "partly priced and carries a note; never the long-context figure",
         (carry[0]["valuation"]["subtotal_usd"], carry[0]["valuation"]["pricing_coverage"],
          "1 of 3" in carry[0]["valuation"].get("note", ""), carry[0]["valuation"].get("priced_as")),
         ("2.10", "partial", True, "sum_of_requests"))
nothing = requests_of("gpt-6-astra", 3)
for member in nothing:
    del member["valuation"]
carry = C.collapse_requests(nothing, "s", {}, CAT)
check_eq("Q1d edge: requests with no valuation at all -> the row is unpriced (none, 0), with the reason",
         (carry[0]["valuation"]["pricing_coverage"], carry[0]["valuation"]["subtotal_usd"],
          "no valuation" in (carry[0]["valuation"]["rate_provenance"].get("reason") or "")), ("none", "0", True))
one = requests_of("gpt-6-astra", 1)
carry = C.collapse_requests(one, "s", {}, CAT)
check_eq("Q1d edge: a bucket of ONE request keeps that request's own valuation and no 'sum' marker",
         (carry[0]["valuation"]["subtotal_usd"], "priced_as" in carry[0]["valuation"]), ("1.05", False))
sonnets = requests_of(SONNET, 3)
carry = C.collapse_requests(sonnets, "s", {}, CAT)
summed = C.value_usage({"requests": 1, "input": 300_000, "output": 3000, "cache_read": 0, "cache_write_5m": 0,
                        "cache_write_1h": 0}, SONNET, {}, CAT, "anthropic", C.parse_ts(TS))
check_eq("Q1d control: a model with no long-context tariff folds to the same money as before (linear)",
         carry[0]["valuation"]["subtotal_usd"], summed["subtotal_usd"])
two_streams = requests_of("gpt-6-astra", 2) + [dict(m, stream="agent-a.jsonl") for m in requests_of("gpt-6-astra", 2)]
check_eq("Q1d: each (stream, model) carry row is summed on its own (two rows of 2.10)",
         sorted(c["valuation"]["subtotal_usd"] for c in C.collapse_requests(two_streams, "s", {}, CAT)), ["2.10", "2.10"])

# --------------------------------------------------------------------------------------------
# R2 on a per-request ledger, and O3 (what was used, what stays unpriced)
# --------------------------------------------------------------------------------------------
doc = per_request_doc()
before = dump(doc)
out = C.revalue_document(doc, {"model_prices": FAMILY_99}, CAT)
check_eq("R2 per-request: session total (2 + 1 + 1) at the catalogue rate, family table present",
         out["total_cost_usd"], 4.0)
check_eq("R2 per-request: orchestrator and the agent file are re-priced from their own stream",
         (out["orchestrator"]["cost"], out["agents"][0]["cost"]), (3.0, 1.0))
check_eq("R2 per-request: by_task priced per key from the rows' own task",
         (out["by_task"]["T1"]["cost"], out["by_task"]["T2"]["cost"]), (3.0, 1.0))
check_eq("R2 per-request: by_activity priced per key", (out["by_activity"]["A1"]["cost"], out["by_activity"]["A2"]["cost"]), (3.0, 1.0))
check_eq("R2 per-request: by_task keeps its non-money fields", (out["by_task"]["T1"]["active_s"], out["by_task"]["T1"]["tokens"]), (5, 1))
check_eq("R2 per-request: the reconciliation is recomputed and closes (usage actual, all priced)",
         out["reconciliation"], {"session_total": 4.0, "orchestrator_plus_agents": 4.0, "tasks_sum": 4.0, "match": True})
check_eq("O3: rates word is 'catalogue' and no unpriced keys when everything is priced",
         out["repriced_at_read"], {"catalogue_revision": "test-r1", "rates": "catalogue",
                                   "captured_catalogue_revision": "old-rev", "ledger": "per_request"})
check_eq("R2: input never mutated (deep compare before / after)", dump(doc) == before, True)

out = C.revalue_document(per_request_doc(), {"rate_overrides": [OVERRIDE]}, CAT)
check_eq("E16 through revalue: an override wins over the catalogue for its model (7 per M input: 1M+0+0.5M)",
         (out["repriced_at_read"]["rates"], out["by_task"]["T1"]["cost"]), ("override", 10.5))
legacy_rows = [row("vendor-model-v1", usage(input_=1_000_000), task="T2", activity="A2", request_id="r4")]
out = C.revalue_document(per_request_doc(legacy_rows), {"model_prices": {"vendor": {"input": 5}}}, CAT)
check_eq("O2/O3: a model neither knows is priced by the legacy table and the marker says 'mixed'",
         (out["repriced_at_read"]["rates"], out["by_task"]["T2"]["cost"], out["total_cost_usd"]), ("mixed", 6.0, 9.0))
out = C.revalue_document(per_request_doc(legacy_rows), {"model_prices": {"vendor": {"input": 5}}}, NO_CATALOGUE)
check_eq("O3: only the legacy table priced anything -> 'legacy'", out["repriced_at_read"]["rates"], "legacy")
unknown_rows = [row("claude-sonnet-5-5-x", usage(input_=1_000_000), task="T2", activity="A2", request_id="r4")]
out = C.revalue_document(per_request_doc(unknown_rows), {}, CAT)
check_eq("E16/O3: a catalogue-unknown model containing a catalogue id is unpriced and counted; the total is "
         "None, never a total with $0 in it",
         (out["total_cost_usd"], out["pricing_coverage"], out["repriced_at_read"]["unpriced_requests"]),
         (None, "partial", 1))
check_eq("O3: the known part stays visible next to the None total", out["priced_subtotal_usd"], 4.0)
check_eq("O3: the priced model still has its own cost; the task with the unpriced request has none",
         (out["by_model"]["claude-sonnet-5-5"]["cost"], out["by_task"]["T1"]["cost"], out["by_task"]["T2"]["cost"]),
         (4.0, 3.0, None))
check_eq("O3: the reconciliation cannot claim a match over an unpriced request",
         (out["reconciliation"]["session_total"], out["reconciliation"]["match"]), (None, None))
check("O3: the reason is written in the document",
      out["repriced_at_read"]["unpriced_reasons"] == ["model unknown to rate_overrides, the catalogue and the legacy model_prices"])

window_doc = {"requests": [row("m-x", usage(input_=1_000_000), ts="2025-06-01T00:00:00+00:00", request_id="a"),
                           row("m-x", usage(input_=1_000_000), ts="2026-06-01T00:00:00+00:00", request_id="b"),
                           row("m-x", usage(input_=1_000_000), ts=None, request_id="c")]}
out = C.revalue_document(window_doc, {}, WINDOWS)
check_eq("E16 window through revalue: each request is priced at its own timestamp's window; no timestamp = "
         "first entry (existing behaviour)",
         [r["valuation"]["subtotal_usd"] for r in out["requests"]], ["1", "2", "1"])

# --------------------------------------------------------------------------------------------
# edge inputs: no exception, input untouched, nothing written
# --------------------------------------------------------------------------------------------
writes = []
orig_atomic, orig_write_text, orig_write_bytes, orig_open = C.atomic_json, Path.write_text, Path.write_bytes, builtins.open
work = temp_dir("qa-rate-precedence-")


def guarded_open(file, mode="r", *args, **kwargs):
    if any(flag in str(mode) for flag in "wax+"):
        writes.append(("open", str(file), mode))
    return orig_open(file, mode, *args, **kwargs)


C.atomic_json = lambda *a, **k: writes.append(("atomic_json",) + a[:1])
Path.write_text = lambda self, *a, **k: writes.append(("write_text", str(self)))
Path.write_bytes = lambda self, *a, **k: writes.append(("write_bytes", str(self)))
builtins.open = guarded_open
EDGES = {
    "doc is None": None, "doc is a list": [], "empty dict": {},
    "no requests key": {"session_id": "s", "by_model": {"m": {}}, "total_cost_usd": 5.0},
    "requests []": {"session_id": "s", "requests": [], "by_task": {"T": {"cost": 5.0}}, "total_cost_usd": 5.0},
    "requests not a list": {"requests": "x", "by_task": "y", "by_activity": 3, "agents": {"a": 1}, "orchestrator": []},
    "rows not objects": {"requests": [None, 5, "x"]},
    "row without model": {"requests": [{"usage": usage(input_=10), "stream": "orchestrator"}]},
    "row without usage": {"requests": [{"model_id": "claude-sonnet-5-5", "stream": "orchestrator"}]},
    "row with empty usage": {"requests": [{"model_id": "claude-sonnet-5-5", "usage": {}}]},
    "usage junk": {"requests": [{"model_id": "claude-sonnet-5-5", "usage": {"input": True}},
                                {"model_id": "claude-sonnet-5-5", "usage": {"input": "5"}},
                                {"model_id": "claude-sonnet-5-5", "usage": {"input": -1}},
                                {"model_id": "claude-sonnet-5-5", "usage": {"input": float("nan")}},
                                {"model_id": "claude-sonnet-5-5", "usage": {"input": float("inf")}}]},
    "model is not a string": {"requests": [{"model_id": 7, "usage": usage(input_=10)}]},
    "timestamp garbage": {"requests": [row("claude-sonnet-5-5", usage(input_=1_000_000), ts="not a time")]},
    "by_task entries not objects": {"requests": [], "by_task": {"T": 5}, "by_activity": {"A": None}},
}
failures, results = [], {}
for name, doc in EDGES.items():
    for cfg in (None, {}, "junk", {"model_prices": "junk", "rate_overrides": "junk"}):
        for cat in (None, {}, CAT, "junk"):
            frozen = dump(doc)
            try:
                got = C.revalue_document(doc, cfg, cat)
                if not isinstance(got, dict) or dump(doc) != frozen:
                    failures.append((name, "returned non-dict or mutated its input"))
                results[name] = got
            except Exception as exc:
                failures.append((name, repr(exc)))
C.atomic_json, Path.write_text, Path.write_bytes, builtins.open = orig_atomic, orig_write_text, orig_write_bytes, orig_open
cleanup(work)
check_eq("edges: no exception, a dict back, input unchanged, for every doc x cfg x catalogue combination",
         sorted(set(failures)), [])
check_eq("edges: nothing written to disk (atomic_json, open for write, write_text, write_bytes)", writes, [])
res = results["requests []"]
check_eq("edge requests []: totals from nothing are None / none / 0.0, the ledger is 'empty', the note says so",
         (res["total_cost_usd"], res["pricing_coverage"], res["priced_subtotal_usd"], res["by_model"],
          res["repriced_at_read"]["ledger"], res["reprice_note"], "unpriced_requests" in res["repriced_at_read"]),
         (None, "none", 0.0, {}, "empty", "no request ledger; nothing was re-priced", False))
check_eq("edge requests []: a pinned by_task cost does not survive as a number (no rows carry the task)",
         results["requests []"]["by_task"]["T"]["cost"], None)
check_eq("edge no requests key: the stale total is replaced, the ledger is 'absent'",
         (results["no requests key"]["total_cost_usd"], results["no requests key"]["repriced_at_read"]["ledger"]),
         (None, "absent"))
check_eq("edge rows not objects: each counts as an unpriced request",
         results["rows not objects"]["repriced_at_read"]["unpriced_requests"], 3)
check_eq("edge row without model: unpriced, reason stated, total None",
         (results["row without model"]["repriced_at_read"]["unpriced_requests"],
          results["row without model"]["repriced_at_read"]["unpriced_reasons"],
          results["row without model"]["total_cost_usd"]),
         (1, ["the request names no model id"], None))
check_eq("edge row without usage / with empty usage: unpriced, not $0",
         (results["row without usage"]["total_cost_usd"], results["row without usage"]["repriced_at_read"]["unpriced_requests"],
          results["row with empty usage"]["total_cost_usd"], results["row with empty usage"]["repriced_at_read"]["unpriced_requests"]),
         (None, 1, None, 1))
check_eq("edge usage junk (bool, string, negative, NaN, inf): all five unpriced",
         results["usage junk"]["repriced_at_read"]["unpriced_requests"], 5)
check_eq("edge model not a string: unpriced", results["model is not a string"]["repriced_at_read"]["unpriced_requests"], 1)
res = C.revalue_document({"requests": [row("claude-sonnet-5-5", usage(input_=1_000_000)),
                                       {"model_id": "claude-sonnet-5-5"}]}, {}, CAT)
check_eq("edge mixed: one priced row + one with no usage -> total None, known part 2.0, coverage partial",
         (res["total_cost_usd"], res["priced_subtotal_usd"], res["pricing_coverage"]), (None, 2.0, "partial"))
res = C.revalue_document({"requests": [row("claude-sonnet-5-5", usage(input_=1_000_000), ts="not a time")]}, {}, CAT)
check_eq("edge unparseable timestamp counts as no timestamp (priced, window skipped)", res["total_cost_usd"], 2.0)
res = C.revalue_document(per_request_doc(), None, None)
check("edge cfg None + catalogue None loads the bundled catalogue and prices (sonnet-5-5 input 2 per M)",
      res["total_cost_usd"] is not None and res["repriced_at_read"]["rates"] == "catalogue")

finish("test_rate_precedence")
