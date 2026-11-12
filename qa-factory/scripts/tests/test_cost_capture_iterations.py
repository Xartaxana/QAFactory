"""CD1-9 (P18): a request served by a model FALLBACK is priced by the provider's own per-message records.

`cost_capture.scan_file` used to keep the LAST line of a request and price it by that line's `model` label.
A request whose lines all say opus-4-8 but whose `usage.iterations` hold a fable-5 message and an opus-4-8
message was priced as one opus message (0.154843 instead of 0.427694 for the real request below). The rule
now: 2 or more usable `iterations` entries are the request -- one stored row per entry, each priced by its
OWN model (the anchor keeps the bare request id, the others are `<id>|<model>`), the request = the sum.
Fixtures copy the SHAPE (model + usage, ASCII) of two real requests and of the zero-top-level shape:
  req_011CeTQmWnYoVsGZrpJVsvGh  agent-a877f9d0d06e97281.jsonl lines 108-112: fable-5 once, opus-4-8 four times,
                                line 112 carries the iterations      -> 0.21261  (today 0.06271675)
  req_011CeTUqHEnonHCQfNdNXVaS  cb6de03f-....jsonl lines 655-659: five lines, all opus-4-8, all carry the
                                iterations                           -> 0.427694 (today 0.154843)
  req_011CfFeB1F9Eg3Fn5KPwXRwN  the last line has ZERO top-level counts and one MODELLESS iterations entry that
                                holds the numbers (9 real requests): the earlier non-zero line wins, never $0.
Money is compared as Decimal, never as the rounded `cost`.

Run: python -B ai-packages/qa-factory/scripts/tests/test_cost_capture_iterations.py
"""
import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cost_capture as C
from harness import temp_project, temp_dir, cleanup, check, check_eq, finish, SCRIPTS

FABLE, OPUS, SONNET = "claude-fable-5", "claude-opus-4-8", "claude-sonnet-5"
RATES = {FABLE: {"input": 10, "output": 50, "cache_read": 1.0, "cache_write_5m": 12.5, "cache_write_1h": 20},
         OPUS: {"input": 5, "output": 25, "cache_read": 0.5, "cache_write_5m": 6.25, "cache_write_1h": 10},
         SONNET: {"input": 2, "output": 10, "cache_read": 0.2, "cache_write_5m": 2.5, "cache_write_1h": 4}}
CATALOGUE = {"catalogue_revision": "test", "entries": [
    {"model_id": m, "provider": "anthropic", "rates": r} for m, r in RATES.items()]}
D = Decimal
TMP = temp_dir("qa-iterations-")
_N = [0]

# --- the real shapes -------------------------------------------------------------------------------


def entry(model, inp, out, read, write, one_hour=None, kind="message"):
    e = {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": read,
         "cache_creation_input_tokens": write, "type": kind, "model": model}
    if one_hour is not None:
        e["cache_creation"] = {"ephemeral_5m_input_tokens": write - one_hour, "ephemeral_1h_input_tokens": one_hour}
    return e


TQM_FABLE = entry(FABLE, 2, 869, 102517, 625, 0)
TQM_OPUS = entry(OPUS, 2, 390, 98101, 0, 0, "fallback_message")
TQM_FIRST = {"input_tokens": 2, "cache_creation_input_tokens": 625, "cache_read_input_tokens": 102517,
             "output_tokens": 3, "cache_creation": {"ephemeral_5m_input_tokens": 625, "ephemeral_1h_input_tokens": 0}}
TQM_TOP = {"input_tokens": 2, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 98101, "output_tokens": 390,
           "cache_creation": {"ephemeral_1h_input_tokens": 0, "ephemeral_5m_input_tokens": 625},
           "service_tier": "standard", "speed": "standard"}
TQM_LAST = dict(TQM_TOP, iterations=[TQM_FABLE, TQM_OPUS])
UQ_FABLE = entry(FABLE, 2, 279, 229161, 2972, 2972)
UQ_OPUS = entry(OPUS, 2, 874, 206526, 0, 0, "fallback_message")
UQ_TOP = {"input_tokens": 2, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 206526, "output_tokens": 874,
          "cache_creation": {"ephemeral_1h_input_tokens": 2972, "ephemeral_5m_input_tokens": 0}}
UQ_USAGE = dict(UQ_TOP, iterations=[UQ_FABLE, UQ_OPUS])
TQM, UQ = "req_011CeTQmWnYoVsGZrpJVsvGh", "req_011CeTUqHEnonHCQfNdNXVaS"
TQM_TODAY, UQ_TODAY = D("0.06271675"), D("0.154843")     # the old reading: the last line's top level at the label's rate
PLAIN = {"input_tokens": 1000, "output_tokens": 100, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
         "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}}


def line(rid, model, usage, ts="2026-09-20T19:22:05Z", sidechain=False, uuid=None):
    _N[0] += 1
    body = {"type": "assistant", "isSidechain": sidechain, "uuid": uuid or f"u-{_N[0]}", "timestamp": ts,
            "message": {"model": model, "usage": usage, "content": []}}
    if rid:
        body["requestId"] = rid
    return json.dumps(body)


def tqm_lines(sidechain=False, with_iterations=True):
    last = TQM_LAST if with_iterations else TQM_TOP
    return ([line(TQM, FABLE, TQM_FIRST, sidechain=sidechain)]
            + [line(TQM, OPUS, usage, sidechain=sidechain) for usage in (TQM_FIRST, TQM_FIRST, TQM_FIRST, last)])


def uq_lines(sidechain=False):
    return [line(UQ, OPUS, UQ_USAGE, sidechain=sidechain) for _ in range(5)]


def write(lines):
    _N[0] += 1
    path = TMP / f"t{_N[0]}.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def scan(lines, own_chain=True):
    counts = {}
    rows = C.scan_file(write(lines), own_chain, [], None, counts)[0]
    return rows, counts


def valuation(model, usage, ts=None):
    """The valuation of one stored row, priced the way the capture prices it."""
    return C.request_record("anthropic", "s", "k", "orchestrator", model, usage, ts, "a", "seg", "T", {},
                            CATALOGUE)["valuation"]


def price(model, usage, ts=None):
    """(Decimal subtotal, coverage) of one stored row."""
    value = valuation(model, usage, ts)
    return D(value["subtotal_usd"]), value["pricing_coverage"]


def prices(rows):
    return {key: price(m, u, ts)[0] for key, (m, u, ts) in rows.items()}


def models(rows):
    return {key: m for key, (m, _u, _ts) in rows.items()}


# --- unit cases ------------------------------------------------------------------------------------


def t1_tqm():
    rows, counts = scan(tqm_lines())
    fable = TQM + "|" + FABLE
    check_eq("T1 TQm: keys are the anchor (opus, the label of the last line) and the fable part",
             list(rows), [TQM, fable])
    p = prices(rows)
    check_eq("T1 TQm: opus part 0.0588105", p[TQM], D("0.0588105"))
    check_eq("T1 TQm: fable part 0.1537995", p[fable], D("0.1537995"))
    check_eq("T1 TQm: the request is 0.21261", sum(p.values()), D("0.21261"))
    old = price(OPUS, TQM_TOP)[0]
    check_eq("T1 TQm: today's reading (the last line's top level at opus) was 0.06271675", old, TQM_TODAY)
    check("T1 TQm: the sum is not today's figure", sum(p.values()) != old)
    check_eq("T1 TQm: counts empty (every split known, nothing malformed)", counts, {})
    check_eq("T1 TQm: both parts carry the request's last timestamp",
             {ts for _m, _u, ts in rows.values()}, {C.parse_ts("2026-09-20T19:22:05Z")})
    check_eq("T1 TQm: the fable part's 5m write is its own 625", rows[fable][1]["cache_creation"],
             {"ephemeral_5m_input_tokens": 625, "ephemeral_1h_input_tokens": 0})


def t2_uq():
    rows, counts = scan(uq_lines())
    fable = UQ + "|" + FABLE
    check_eq("T2 UQ: keys {anchor opus, fable part}", list(rows), [UQ, fable])
    p = prices(rows)
    check_eq("T2 UQ: opus 0.125123", p[UQ], D("0.125123"))
    check_eq("T2 UQ: fable 0.302571", p[fable], D("0.302571"))
    check_eq("T2 UQ: the request is 0.427694", sum(p.values()), D("0.427694"))
    check_eq("T2 UQ: the fable part's 1-hour write is 2972",
             rows[fable][1]["cache_creation"]["ephemeral_1h_input_tokens"], 2972)
    old = price(OPUS, UQ_TOP)[0]
    check_eq("T2 UQ: today's reading was 0.154843", old, UQ_TODAY)
    check("T2 UQ: the sum is not today's figure", sum(p.values()) != old)
    check_eq("T2 UQ: counts empty", counts, {})


def t3_labels_disagree():
    rows, _ = scan([line("r", SONNET, TQM_FIRST), line("r", SONNET, TQM_LAST)])
    check_eq("T3 labels: no sonnet row, the anchor is the first entry (fable), the bare key",
             models(rows), {"r": FABLE, "r|" + OPUS: OPUS})
    check_eq("T3 labels: 0.21261", sum(prices(rows).values()), D("0.21261"))


def t4_threshold():
    base_rows, _ = scan([line("r", SONNET, PLAIN)])
    check_eq("T4 base: sonnet 1000 in / 100 out = 0.003", prices(base_rows)["r"], D("0.003"))
    modelless = {k: v for k, v in entry(SONNET, 1000, 100, 0, 0, 0).items() if k != "model"}
    for name, iterations in (("empty list", []), ("null (= absent)", None), ("one real modelless entry", [modelless])):
        rows, counts = scan([line("r", SONNET, dict(PLAIN, iterations=iterations))])
        check_eq(f"T4 {name}: the row's model and its whole valuation are today's, byte for byte",
                 [(m, valuation(m, u)) for m, u, _ in rows.values()],
                 [(m, valuation(m, u)) for m, u, _ in base_rows.values()])
        check_eq(f"T4 {name}: counts {{}} (a modelless one-entry list is ordinary, never bad)", counts, {})
    two = [entry(SONNET, 1000, 100, 0, 0, 0), entry(OPUS, 10, 10, 0, 0, 0)]
    rows, _ = scan([line("r", SONNET, dict(PLAIN, iterations=two))])
    check_eq("T4 two entries: two rows", list(rows), ["r", "r|" + OPUS])
    three = [entry(SONNET, 1, 1, 0, 0, 0), entry(OPUS, 2, 2, 0, 0, 0), entry(OPUS, 3, 3, 0, 0, 0)]
    rows, _ = scan([line("r", SONNET, dict(PLAIN, iterations=three))])
    check_eq("T4 three entries (the third repeats a model): K, K|X, K|X#2 -- never merged",
             list(rows), ["r", "r|" + OPUS, "r|" + OPUS + "#2"])
    check_eq("T4 three entries: each part keeps its own numbers", [u["output_tokens"] for _m, u, _t in rows.values()],
             [1, 2, 3])
    fifty = [entry(OPUS, i, i, 0, 0, 0) for i in range(50)]
    rows, _ = scan([line("r", OPUS, dict(PLAIN, iterations=fifty))])
    check_eq("T4 no cap: 50 entries are 50 rows", len(rows), 50)
    four = [entry(SONNET, 1, 1, 0, 0), entry(OPUS, 2, 2, 0, 0), entry(FABLE, 3, 3, 0, 0), entry(OPUS, 4, 4, 0, 0)]
    rows, _ = scan([line("r", SONNET, dict(PLAIN, iterations=four))])
    check_eq("T4 the suffix is the entry's POSITION: [A, X, B, X] -> K, K|X, K|B, K|X#3",
             sorted(rows), sorted(["r", "r|" + OPUS, "r|" + FABLE, "r|" + OPUS + "#3"]))
    synthetic = [entry("<synthetic>", 1, 1, 0, 0), entry(OPUS, 2, 2, 0, 0), entry(FABLE, 3, 3, 0, 0)]
    rows, counts = scan([line("r", OPUS, dict(PLAIN, iterations=synthetic))])
    check_eq("T4 a <synthetic> entry is dropped, the other two are the carrier", sorted(rows), sorted(["r", "r|" + FABLE]))
    only = [entry("<synthetic>", 1, 1, 0, 0), entry("<synthetic>", 2, 2, 0, 0), entry(OPUS, 3, 3, 0, 0)]
    rows, counts = scan([line("r", OPUS, dict(PLAIN, iterations=only))])
    check_eq("T4 fewer than two entries left after the <synthetic> ones: today's row, uncounted",
             (list(rows), counts), (["r"], {}))


def t4_zero_top_level():
    """R2: the real shape of req_011CfFeB1F9Eg3Fn5KPwXRwN -- the later line has zero top-level counts (and still the
    nested 1-hour split of the line before it) and ONE modelless iterations entry holding the numbers."""
    one = {k: v for k, v in entry(FABLE, 2, 525, 740217, 801, 801).items() if k != "model"}
    full = {"input_tokens": 2, "cache_creation_input_tokens": 801, "cache_read_input_tokens": 740217,
            "output_tokens": 525, "cache_creation": {"ephemeral_1h_input_tokens": 801, "ephemeral_5m_input_tokens": 0},
            "iterations": [one]}
    zero = dict(full, input_tokens=0, cache_creation_input_tokens=0, cache_read_input_tokens=0, output_tokens=0)
    want = D("0.782507")       # 2*10 + 525*50 + 740217*1.0 + 801*20 (1-hour), per 1M
    rows, counts = scan([line("f2", FABLE, full)] + [line("f2", FABLE, zero) for _ in range(3)])
    check_eq("T4 R2: three zero lines after the full one never displace it -- the full line's price, not $0",
             prices(rows), {"f2": want})
    check_eq("T4 R2: the row is the earlier line's usage", rows["f2"][1], full)
    check_eq("T4 R2: counts {}", counts, {})
    rows, _ = scan([line("f2", FABLE, zero), line("f2", FABLE, full)])
    check_eq("T4 R2: a zero line FIRST is displaced as ever (last wins)", prices(rows), {"f2": want})
    rows, _ = scan([line("f2", FABLE, zero), line("f2", FABLE, zero)])
    check_eq("T4 R2: nothing earlier has counts -> the last zero line stands (not invented, not hidden)",
             prices(rows), {"f2": D("0.016020")})
    odd = dict(full, output_tokens="525")
    rows, _ = scan([line("f2", FABLE, full), line("f2", FABLE, odd)])
    check_eq("T4 R2: a later line that is not zero (a str count) is an ordinary last line", rows["f2"][1], odd)


def t5_malformed():
    e1, e2 = dict(TQM_FABLE), dict(TQM_OPUS)
    cases = {"str": "x", "dict": {"a": 1}, "int": 5, "entry-not-an-object": [e1, "opus"],
             "no-model": [e1, {"input_tokens": 5}], "empty-model": [e1, dict(e2, model="")],
             "model-a-list": [e1, dict(e2, model=["x"])], "model-only": [e1, {"model": OPUS}],
             "count-str": [e1, dict(e2, output_tokens="many")], "count-bool": [e1, dict(e2, output_tokens=True)],
             "count-negative": [e1, dict(e2, output_tokens=-5)], "count-null": [e1, dict(e2, output_tokens=None)],
             "count-nan": [e1, dict(e2, output_tokens=float("nan"))], "count-inf": [e1, dict(e2, input_tokens=float("inf"))],
             "count-list": [e1, dict(e2, cache_read_input_tokens=[1])]}
    plain, _ = scan([line("r", OPUS, TQM_FIRST), line("r", OPUS, TQM_TOP)])
    for name, bad in cases.items():
        try:
            rows, counts = scan([line("r", OPUS, TQM_FIRST), line("r", OPUS, dict(TQM_TOP, iterations=bad))])
        except Exception as exc:    # iterations never raise
            check(f"T5 {name}: no raise", False, repr(exc))
            continue
        check_eq(f"T5 {name}: the rows (keys, models, whole valuations) are those of the same lines without iterations",
                 {k: (m, valuation(m, u)) for k, (m, u, _t) in rows.items()},
                 {k: (m, valuation(m, u)) for k, (m, u, _t) in plain.items()})
        check_eq(f"T5 {name}: bad_iterations 1", counts, {"bad_iterations": 1})
    rows, counts = scan([line("r", OPUS, dict(TQM_TOP, iterations="x")), line("r", OPUS, dict(TQM_TOP, iterations="y"))])
    check_eq("T5 bad_iterations counts LINES", counts, {"bad_iterations": 2})


def t5_clamp():
    """R1: W = the entry's cache_creation_input_tokens; the 1-hour split is clamped into [0, W]; the carrier is kept."""
    big = entry(FABLE, 0, 0, 0, 1000, 5000)
    big["cache_creation"]["ephemeral_5m_input_tokens"] = 0
    rows, counts = scan([line("r", OPUS, dict(TQM_TOP, iterations=[big, TQM_OPUS]))])
    check_eq("T5 R1: a 1-hour split above the write is clamped to the write (1000 at the 1-hour rate), carrier kept",
             (prices(rows)["r"], list(rows)), (D("0.0588105"), ["r", "r|" + FABLE]))
    fable = rows["r|" + FABLE][1]
    check_eq("T5 R1: the clamped part is 5m 0 / 1h 1000 and costs 1000*20/1e6",
             (fable["cache_creation"], price(FABLE, fable)[0]),
             ({"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 1000}, D("0.02")))
    check_eq("T5 R1: counts {} (a clamp is not a refusal)", counts, {})
    for name, split in (("negative", -5), ("str", "x")):
        odd = entry(FABLE, 0, 0, 0, 1000)
        odd["cache_creation"] = {"ephemeral_1h_input_tokens": split}
        rows, counts = scan([line("r", OPUS, dict(TQM_TOP, iterations=[odd, TQM_OPUS]))])
        check_eq(f"T5 a {name} 1-hour split is no split: 5m write, counted",
                 (rows["r|" + FABLE][1]["cache_creation"], counts["split_missing"]),
                 ({"ephemeral_5m_input_tokens": 1000, "ephemeral_1h_input_tokens": 0}, 1))


def t6_split_missing():
    no_split = entry(FABLE, 0, 0, 0, 1000)
    with_split = entry(OPUS, 0, 0, 0, 1000, 1000)
    rows, counts = scan([line("r", OPUS, dict(TQM_TOP, iterations=[no_split, with_split]))])
    p = prices(rows)
    check_eq("T6 split missing: the fable write is priced as 5-minute, 1000*12.5/1e6", p["r|" + FABLE], D("0.0125"))
    check_eq("T6 split missing: the opus write is its own 1-hour, 1000*10/1e6", p["r"], D("0.01"))
    check_eq("T6 split missing: counted once, as a request", (counts["split_missing"], counts["split_missing_keys"]),
             (1, ["r"]))
    lines = [line("r", OPUS, dict(TQM_TOP, iterations=[no_split, no_split])) for _ in range(2)] + \
            [line("q", OPUS, dict(TQM_TOP, iterations=[no_split, with_split]))]
    rows, counts = scan(lines)
    check_eq("T6 split missing counts DISTINCT requests (two parts, two lines, one request; two requests)",
             (counts["split_missing"], counts["split_missing_keys"]), (2, ["r", "q"]))


def t8_t10_carrier_choice():
    rows, _ = scan([line(TQM, OPUS, TQM_LAST), line(TQM, OPUS, TQM_FIRST)])
    check_eq("T8 the carrier is NOT on the last line: the parts still win over the later plain line",
             sum(prices(rows).values()), D("0.21261"))
    check_eq("T8 the later plain line's label still chooses the anchor", models(rows), {TQM: OPUS, TQM + "|" + FABLE: FABLE})
    other = dict(TQM_TOP, iterations=[entry(SONNET, 10, 10, 0, 0, 0), entry(OPUS, 20, 20, 0, 0, 0)])
    rows, _ = scan([line(TQM, OPUS, TQM_LAST), line(TQM, OPUS, other)])
    check_eq("T10 two carriers: the LAST one wins whole", models(rows), {TQM: OPUS, TQM + "|" + SONNET: SONNET})


def t9_no_carrier():
    growing = [dict(PLAIN, output_tokens=17), dict(PLAIN, output_tokens=17), dict(PLAIN, output_tokens=485)]
    rows, counts = scan([line("r", SONNET, u) for u in growing])
    check_eq("T9 no carrier: the last line's model and usage (today's reading)", rows["r"][:2], (SONNET, growing[-1]))
    rows, _ = scan([line("r", SONNET, growing[0]), line("r", OPUS, growing[1])])
    check_eq("T9 no carrier: the last line's LABEL too", rows["r"][0], OPUS)


def t11_sidechain():
    rows, _ = scan(tqm_lines(sidechain=True), own_chain=False)
    check_eq("T11 sidechain lines in the MAIN file (own_chain False): no row, the carrier is not read", rows, {})
    rows, _ = scan(tqm_lines(sidechain=True), own_chain=True)
    check_eq("T11 sidechain lines in an agent file: the parts", sum(prices(rows).values()), D("0.21261"))
    mixed = [line(TQM, OPUS, TQM_LAST, sidechain=True), line(TQM, OPUS, TQM_FIRST, sidechain=False)]
    rows, _ = scan(mixed, own_chain=False)
    check_eq("T11 a carrier on a sidechain line is not read in the main file; the main line stands",
             list(rows), [TQM])


def t12_ids():
    rows, _ = scan([line(None, OPUS, TQM_LAST, uuid="uu-1")])
    check_eq("T12 no requestId: the uuid keys it, the parts are uuid|model", list(rows), ["uu-1", "uu-1|" + FABLE])
    body = json.loads(line(None, OPUS, TQM_LAST))
    del body["uuid"]
    rows, _ = scan([json.dumps(body)])
    check_eq("T12 neither id: no row, as today", rows, {})


# --- the incremental path -------------------------------------------------------------------------------


def inc(path, prior=None, rows=None):
    return C.scan_file_incremental(path, prior, rows, True, [])


def records(usage):
    """The request rows a capture would have stored for a scan result (what the next scan is seeded from)."""
    return [C.request_record("anthropic", "s", key, "orchestrator", m, u, ts, "a", "seg", "T", {}, CATALOGUE)
            for key, (m, u, ts) in usage.items()]


def append(path, *lines):
    with path.open("a", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")


def t13_stamp_and_world1():
    path = write(tqm_lines())
    first = inc(path)
    check_eq("T13 the checkpoint carries the reader stamp", first[-1].get("reader"), C.READER_STAMP)
    old = {k: v for k, v in first[-1].items() if k != "reader"}      # a checkpoint of the reader that knew no iterations
    old_row = C.request_record("anthropic", "s", TQM, "orchestrator", OPUS, TQM_TOP, None, "a", "seg", "T", {}, CATALOGUE)
    rebuilt = inc(path, old, [old_row])
    check_eq("T13 (1a) a checkpoint with no stamp is rebuilt once: the old one-model row becomes the parts",
             sorted(rebuilt[0]), sorted([TQM, TQM + "|" + FABLE]))
    check_eq("T13 (1a) the rebuilt request is 0.21261", sum(prices(rebuilt[0]).values()), D("0.21261"))
    steady = inc(path, rebuilt[-1], records(rebuilt[0]))
    check_eq("T13 steady: nothing appended -> nothing re-read, the parts stay",
             (sorted(steady[0]), steady[-1]["offset"]), (sorted(rebuilt[0]), rebuilt[-1]["offset"]))
    check_eq("T13 steady: the same money", prices(steady[0]), prices(rebuilt[0]))
    path2 = write([line(TQM, FABLE, TQM_FIRST), line(TQM, OPUS, TQM_FIRST)])
    one = inc(path2)
    check_eq("T13 (1b) before the carrier: one row (the last line)", list(one[0]), [TQM])
    append(path2, line(TQM, OPUS, TQM_LAST))
    two = inc(path2, one[-1], records(one[0]))
    check_eq("T13 (1b) the carrier arrives in the tail: the anchor replaces the row, the fable part is added",
             (sorted(two[0]), sum(prices(two[0]).values())), (sorted([TQM, TQM + "|" + FABLE]), D("0.21261")))


def t14_world2_merge():
    path = write([line(TQM, OPUS, TQM_LAST)])
    r1 = inc(path)
    append(path, line(TQM, OPUS, dict(TQM_FIRST, output_tokens=7)))
    r2 = inc(path, r1[-1], records(r1[0]))
    check_eq("T14 M2: a plain line after a stored carrier keeps K and every K|* as saved", r2[0], r1[0])
    sonnet_carrier = dict(TQM_TOP, iterations=[entry(SONNET, 10, 10, 0, 0, 0), entry(OPUS, 20, 20, 0, 0, 0)])
    append(path, line(TQM, OPUS, sonnet_carrier))
    r3 = inc(path, r2[-1], records(r2[0]))
    check_eq("T14 M1: a new carrier with other models drops the old K|* whole -- no stale part",
             sorted(r3[0]), sorted([TQM, TQM + "|" + SONNET]))
    check_eq("T14 M1: the request is the new carrier's parts only", sum(prices(r3[0]).values()),
             price(SONNET, entry(SONNET, 10, 10, 0, 0, 0))[0] + price(OPUS, entry(OPUS, 20, 20, 0, 0, 0))[0])
    full = dict(PLAIN, input_tokens=500)
    zero = dict(PLAIN, input_tokens=0, output_tokens=0)
    path3 = write([line("z", SONNET, full)])
    z1 = inc(path3)
    append(path3, line("z", SONNET, zero))
    z2 = inc(path3, z1[-1], records(z1[0]))
    check_eq("T14 R2 across a checkpoint: a zero line in the next tail never displaces the saved full line",
             prices(z2[0]), prices(z1[0]))
    append(path3, line("z", SONNET, dict(PLAIN, input_tokens=900)))
    z3 = inc(path3, z2[-1], records(z2[0]))
    check_eq("T14 R2 across a checkpoint: a later line WITH counts replaces it as ever", z3[0]["z"][1]["input_tokens"], 900)


def t14_counts_across_checkpoints():
    no_split = entry(FABLE, 0, 0, 0, 1000)
    carrier = dict(TQM_TOP, iterations=[no_split, TQM_OPUS])
    path = write([line("m", OPUS, carrier), line("x", OPUS, dict(TQM_TOP, iterations="bad"))])
    c1 = inc(path)
    append(path, line("m", OPUS, carrier), line("x", OPUS, dict(TQM_TOP, iterations="bad")))
    c2 = inc(path, c1[-1], records(c1[0]))
    state = c2[-1]["state"]
    check_eq("T14 F-7: a carrier repeated across a checkpoint is ONE split_missing request",
             state.get("split_missing_keys"), ["m"])
    check_eq("T14 F-7: bad_iterations sums the lines of the two scans", state.get("bad_iterations"), 2)
    check_eq("T14 the document-level sum reads the per-file checkpoint counts",
             C.usage_reader_counts([c2[-1], c1[-1], {"adapter": "codex-x"}]),
             {"bad_iterations": 3, "split_missing": 2})
    check_eq("T14 a clean read is not decorated: no counts -> {}", C.usage_reader_counts([inc(write(tqm_lines()))[-1]]), {})


# --- the stored document: P18 end to end ---------------------------------------------------------------------

SESSION, TASK = "iter-session", "ITER-1"
ROOTS = []


def e2e(main_lines, agent_lines=None):
    """A real Stop capture (subprocess) of a story session; returns (root, document)."""
    root = temp_project()
    ROOTS.append(root)
    cfg_path = root / "qa-factory" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["cost"] = dict(cfg.get("cost") or {}, model_prices={})        # no legacy family rate may price an unknown id
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    transcripts = root / "transcripts"
    sub_dir = transcripts / SESSION / "subagents"
    sub_dir.mkdir(parents=True)
    main_path = transcripts / f"{SESSION}.jsonl"
    prompt = json.dumps({"type": "user", "isSidechain": False, "promptId": "p1", "uuid": "u0",
                         "timestamp": "2026-09-20T19:21:30Z", "message": {"role": "user", "content": "x"}})
    main_path.write_text("\n".join([prompt] + main_lines) + "\n", encoding="utf-8")
    if agent_lines:
        (sub_dir / "agent-aaaa1111.jsonl").write_text("\n".join(agent_lines) + "\n", encoding="utf-8")
        (sub_dir / "agent-aaaa1111.meta.json").write_text(json.dumps({
            "agentType": "qa-factory:qa-scout", "description": f"scout {TASK}", "toolUseId": "t1", "spawnDepth": 1}),
            encoding="utf-8")
    activities = root / "qa-factory" / "state" / "activities"
    activities.mkdir(parents=True)
    (activities / f"{SESSION}.json").write_text(json.dumps({
        "schema_version": 1, "session_id": SESSION,
        "activities": [{"activity_id": "act1", "type": "story", "task": TASK, "start_event_id": "e1",
                        "start_time": "2026-09-20T19:21:00Z", "end_event_id": None, "end_time": None,
                        "evidence_ref": None, "status": "open",
                        "segments": [{"segment_id": "seg1", "start_event_id": "e1", "start_time": "2026-09-20T19:21:00Z",
                                      "end_event_id": None, "end_time": None}]}],
        "active_stack": ["act1"], "processed_events": {}, "usage_completeness": "unknown"}), encoding="utf-8")
    event = {"hook_event_name": "Stop", "session_id": SESSION, "transcript_path": str(main_path), "cwd": str(root),
             "usage_complete": True}
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), QA_FACTORY_SKIP_DASHBOARD_REFRESH="1")
    result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "cost_capture.py")], input=json.dumps(event), text=True,
                            capture_output=True, encoding="utf-8", cwd=str(root), env=env, timeout=120)
    check_eq("e2e: the Stop capture exits 0", result.returncode, 0)
    doc = json.loads((root / "qa-factory" / "state" / "cost" / f"{SESSION}.json").read_text(encoding="utf-8"))
    return root, doc


def exact(model_doc):
    return D(model_doc["valuation"]["subtotal_usd"])


def t15_end_to_end():
    ts = "2026-09-20T19:22:"
    main = [line(UQ, OPUS, UQ_USAGE, ts=ts + "10Z") for _ in range(5)] + [line("plain", SONNET, PLAIN, ts=ts + "20Z")]
    agent = [line(TQM, FABLE, TQM_FIRST, ts=ts + "30Z", sidechain=True)] + \
            [line(TQM, OPUS, u, ts=ts + "31Z", sidechain=True) for u in (TQM_FIRST, TQM_FIRST, TQM_FIRST, TQM_LAST)]
    root, doc = e2e(main, agent)
    by_model = doc["by_model"]
    check_eq("T15 by_model: each fallback part is under ITS model -- fable 0.302571 + 0.1537995",
             exact(by_model[FABLE]), D("0.4563705"))
    check_eq("T15 by_model: opus 0.125123 + 0.0588105", exact(by_model[OPUS]), D("0.1839335"))
    check_eq("T15 by_model: sonnet 0.003", exact(by_model[SONNET]), D("0.003"))
    check_eq("T15 every part row counts one request (a1): fable 2, opus 2, sonnet 1",
             {m: by_model[m]["requests"] for m in by_model}, {FABLE: 2, OPUS: 2, SONNET: 1})
    want = D("0.643304")           # 0.21261 + 0.427694 + 0.003
    check_eq("T15 the stored rows sum to the request figures",
             sum((D(r["valuation"]["subtotal_usd"]) for r in doc["requests"]), D("0")), want)
    keys = {r["request_key"] for r in doc["requests"]}
    check_eq("T15 the request keys: the anchor keeps the bare id, the other part is <id>|<model>",
             {k for k in keys if "req_" in k},
             {f"anthropic:{SESSION}:{UQ}:orchestrator", f"anthropic:{SESSION}:{UQ}|{FABLE}:orchestrator",
              f"anthropic:{SESSION}:{TQM}:agent-aaaa1111.jsonl", f"anthropic:{SESSION}:{TQM}|{FABLE}:agent-aaaa1111.jsonl"})
    check_eq("T15 P18: the exact session subtotal", D(doc["priced_subtotal_exact_usd"]), want)
    check_eq("T15 P18: the task's priced subtotal (Decimal of the stored float)",
             D(str(doc["by_task"][TASK]["priced_subtotal_usd"])), want)
    rec = doc["reconciliation"]
    check_eq("T15 P18: reconciliation.match is True (usage_complete, every row priced)", rec["match"], True)
    check("T15 P18: session_total == orchestrator_plus_agents == tasks_sum",
          rec["session_total"] == rec["orchestrator_plus_agents"] == rec["tasks_sum"] == 0.6433, repr(rec))
    revalued = C.revalue_document(doc, {"model_prices": {}}, None)
    check_eq("T15 read time: the document re-priced from its stored rows gives the same money",
             (D(revalued["priced_subtotal_exact_usd"]), revalued["reconciliation"]["match"]), (want, True))
    check("T15 a clean read writes no usage_reader field", "usage_reader" not in doc)
    check_eq("T15 the checkpoints are stamped", {c.get("reader") for c in doc["scan_checkpoints"].values()},
             {C.READER_STAMP})


def t7_unpriced_part():
    never = dict(TQM_FABLE, model="claude-never-priced")
    main = [line(TQM, OPUS, dict(TQM_TOP, iterations=[never, TQM_OPUS]), ts="2026-09-20T19:22:10Z")]
    root, doc = e2e(main)
    row = next(r for r in doc["requests"] if r["model_id"] == "claude-never-priced")
    check_eq("T7 the unpriced part: its own row, coverage none", row["valuation"]["pricing_coverage"], "none")
    check("T7 the unpriced part: cost None, never a neighbour's price or $0",
          doc["by_model"]["claude-never-priced"]["cost"] is None)
    check_eq("T7 the priced part keeps its own figure", D(doc["priced_subtotal_exact_usd"]), D("0.0588105"))
    check_eq("T7 the session is partial, the total is None", (doc["pricing_coverage"], doc["total_cost_usd"]),
             ("partial", None))
    check_eq("T7 reconciliation.match is None (never True over an unpriced part)", doc["reconciliation"]["match"], None)
    revalued = C.revalue_document(doc, {"model_prices": {}}, None)
    check_eq("T7 read time: one unpriced request", revalued["repriced_at_read"]["unpriced_requests"], 1)


def t15b_usage_reader_field():
    no_split = entry(FABLE, 0, 0, 0, 1000)
    main = [line("m", OPUS, dict(TQM_TOP, iterations=[no_split, TQM_OPUS]), ts="2026-09-20T19:22:10Z"),
            line("x", SONNET, dict(PLAIN, iterations="bad"), ts="2026-09-20T19:22:20Z")]
    root, doc = e2e(main)
    check_eq("T15b the cost document names the counts (non-zero only)", doc.get("usage_reader"),
             {"bad_iterations": 1, "split_missing": 1})
    check_eq("T15b the malformed line is read as today (sonnet 0.003) and the carrier is still two rows",
             sorted(r["request_id"] for r in doc["requests"]), sorted(["m", "m|" + FABLE, "x"]))


def t16_bundled_rates():
    bundled = {e["model_id"]: e["rates"] for e in C.load_catalogue()["entries"] if e.get("model_id") in RATES}
    check_eq("T16 the bundled model-rates.json rows for fable-5 / opus-4-8 / sonnet-5 are the numbers this file prices with "
             "(a rate change fails HERE, not as a reader failure)", bundled, RATES)


def main():
    try:
        for test in (t1_tqm, t2_uq, t3_labels_disagree, t4_threshold, t4_zero_top_level, t5_malformed, t5_clamp,
                     t6_split_missing, t8_t10_carrier_choice, t9_no_carrier, t11_sidechain, t12_ids,
                     t13_stamp_and_world1, t14_world2_merge, t14_counts_across_checkpoints, t16_bundled_rates,
                     t15_end_to_end, t7_unpriced_part, t15b_usage_reader_field):
            try:
                test()
            except Exception as exc:     # a broken reader fails the case by name, the others still run
                check(f"{test.__name__}: raised {type(exc).__name__}", False, repr(exc))
    finally:
        for root in ROOTS:
            cleanup(root)
        cleanup(TMP)
    finish("test_cost_capture_iterations")


if __name__ == "__main__":
    main()
