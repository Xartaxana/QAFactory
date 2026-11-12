"""CD1-5: the forecast of a story's price from the precedents of its own size, in its own unit (FR-41, FR-10, AR-21, AR-22, AR-23, AR-26).

Owner's word 29.10.2026: recompute the forecast by OH3-15's new unit, on new data. A size letter counts the register's rows
(`requirements`, a record with no `size_unit`) or the functions; a letter of one unit never prices a letter of the other, and a
change of unit is never read as drift. The forecast errs toward "too few precedents", never toward a precise number from mixed
data. Keys C1-C12 and C8b of `docs/tasks/specs/r0107-s4b2-oh3-3-gw1-10-sc2-37-cd1-5-oh3-23.md` section 5.

Run on its own: `python -B scripts/tests/test_size_forecast.py`.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import retro_numbers as RN  # noqa: E402
import sizing  # noqa: E402


def rec(task, size="M", unit="functions", usd=10.0, ts="2026-10-20T00:00:00+00:00", **extra) -> dict:
    """One ledger record in the shape `estimate_record.append_record` writes. `unit=None` leaves `size_unit` out (an old record)."""
    forecast = {"size_final": size, "size_initial": size}
    if unit is not None:
        forecast["size_unit"] = unit
    forecast.update(extra.pop("forecast", {}))
    actual = {"usd": usd, "usd_low": None, "usd_high": None, "incomplete": False}
    actual.update(extra.pop("actual", {}))
    out = {"schema_version": 1, "task": task, "record_id": f"{task}-{ts}", "supersedes": [], "created_at": ts,
           "forecast": forecast, "actual": actual, "drivers": []}
    out.update(extra)
    return out


def story(rows=None, sizing_doc="default", size="M") -> tuple:
    """A project with one story QA-1 sized `size`, its `work/sizing.json` and an estimation ledger of `rows`."""
    root = temp_dir("qa-size-forecast-")
    base = root / "qa-factory"
    troot = base / "artifacts" / "QA-1"
    (troot / "work").mkdir(parents=True)
    (troot / "state").mkdir(parents=True)
    (base / "state" / "cost").mkdir(parents=True)
    (base / "records").mkdir(parents=True)
    (base / "config.json").write_text("{}", encoding="utf-8")
    (troot / "pipeline.json").write_text(json.dumps({"ticket": "QA-1", "size": size, "size_final": size, "stages": {}}),
                                         encoding="utf-8")
    (troot / "work" / "test-plan.json").write_text("[]", encoding="utf-8")
    if sizing_doc == "default":
        sizing_doc = {"size": size, "size_unit": "functions", "function_count": 7, "computed_budget": 14,
                      "reducers_applied": [], "size_override": None}
    if sizing_doc is not None:
        (troot / "work" / "sizing.json").write_text(json.dumps(sizing_doc), encoding="utf-8")
    if rows is not None:
        text = "\n".join(r if isinstance(r, str) else json.dumps(r) for r in rows) + "\n"
        (base / "records" / "estimation-ledger.jsonl").write_text(text, encoding="utf-8")
    return root, base, troot


THREE = [rec("A-1", usd=10.0), rec("A-2", usd=20.0), rec("A-3", usd=60.0)]


def forecast(rows, size="M", unit="functions", task="QA-1", **kw) -> dict:
    return RN.size_forecast(rows, task, size, unit, **kw)


def c1_and_c9_control_values() -> None:
    got = forecast(THREE)
    check_eq("C1 three same-unit rows at 10, 20, 60: the range, the median and the count",
             (got["known"], got["low"], got["median"], got["high"], got["precedents"], got["skipped"]),
             (True, 10.0, 20.0, 60.0, 3, {}))
    capped = [rec("A-1", usd=10.0, forecast={"defect_capped": True}), THREE[1], THREE[2]]
    got = forecast(capped)
    check_eq("C1 one of the three a capped defect: carried in the answer", got["defect_capped"], 1)
    root, base, troot = story(capped)
    try:
        line = RN.render(RN.numbers("QA-1", base, troot))
        check_in("C1 the line names the range, the median, the count and the rates", "M stories on the function count so far: "
                 "$10.00..$60.00, median $20.00, 3 precedents (of which 1 defect ticket), at the rates of each run.", line)
        check_in("C1 and the story's own price stands beside it", "This one: not priced, 7 functions.", line)
    finally:
        cleanup(root)
    # C9: a range row. The low goes to the low side, the high to the high side, the median stands on single figures only.
    ranged = [rec("A-1", usd=10.0), rec("A-2", usd=None, actual={"usd": None, "usd_low": 15.0, "usd_high": 90.0}),
              rec("A-3", usd=30.0)]
    got = forecast(ranged)
    check_eq("C9 a range row: low 10, high 90, two single figures are no median (not a forecast), three precedents",
             (got["known"], got["low"], got["median"], got["median_of"], got["high"], got["precedents"]),
             (True, 10.0, None, 2, 90.0, 3))
    # F1: the median stands on three or more single figures, and the line says how many it had
    one_single = [rec("A-1", usd=20.0),
                  rec("A-2", usd=None, actual={"usd": None, "usd_low": 10.0, "usd_high": 500.0}),
                  rec("A-3", usd=None, actual={"usd": None, "usd_low": 300.0, "usd_high": 900.0})]
    got = forecast(one_single)
    check_eq("F1 one single figure and two ranges: three precedents, no median, it stood on one",
             (got["known"], got["precedents"], got["median"], got["median_of"]), (True, 3, None, 1))
    check_in("F1 and the line says how many prices are one figure, never a median of one",
             "no median (only 1 of 3 prices are one figure, a median needs 3)",
             RN.size_forecast_line({"size_forecast": got, "price": {}}))
    check_not_in("F1 no 'median $20.00' beside '3 precedents'", "median $", RN.size_forecast_line({"size_forecast": got, "price": {}}))
    two = [rec("A-1", usd=20.0), rec("A-2", usd=100.0),
           rec("A-3", usd=None, actual={"usd": None, "usd_low": 10.0, "usd_high": 500.0})]
    check_eq("F1 two singles and a range: no median of two", (forecast(two)["median"], forecast(two)["median_of"]), (None, 2))
    four = THREE + [rec("A-4", usd=30.0)]
    check_eq("F1 four single figures: the median of four (even count), and it says four", (forecast(four)["median"],
             forecast(four)["median_of"]), (25.0, 4))
    zero = [rec("A-1", usd=None), rec("A-2", usd=20.0), rec("A-3", usd=30.0), rec("A-4", usd=40.0)]
    got = forecast(zero)
    check_eq("C9 a null usd is never read as 0: the low stays 20 and the row is counted as no price",
             (got["low"], got["precedents"], got["skipped"]), (20.0, 3, {"no_price": 1}))
    all_ranges = [rec(f"A-{i}", usd=None, actual={"usd": None, "usd_low": 10.0 + i, "usd_high": 50.0 + i}) for i in range(3)]
    got = forecast(all_ranges)
    check_eq("C9 three ranges and no single figure: a range, and no median is invented",
             (got["known"], got["low"], got["high"], got["median"]), (True, 10.0, 52.0, None))
    check_in("C9 and the line says so", "no median (only 0 of 3 prices are one figure, a median needs 3)",
             RN.size_forecast_line({"size_forecast": got, "price": {}}))


def c2_boundary() -> None:
    for count, expect in ((2, False), (3, True), (4, True)):
        got = forecast(THREE[:count] if count <= 3 else THREE + [rec("A-4", usd=30.0)])
        check_eq(f"C2 {count} precedents: known {expect}", got["known"], expect)
    got = forecast(THREE[:2])
    check_eq("C2 two of three: the form pins the count and the need", (got["precedents"], got["needed"]), (2, 3))
    line = RN.size_forecast_line({"size_forecast": got})
    check_eq("C2 the line says too few and how many", line, "**Forecast from precedents:** Too few M stories on the function count "
             "to forecast from (2 of 3).")


def c3_units_do_not_mix() -> None:
    mixed = [rec("A-1", usd=10.0), rec("A-2", usd=20.0), rec("O-1", unit=None, usd=900.0), rec("O-2", unit="requirements", usd=800.0)]
    got = forecast(mixed)
    check_eq("C3 old rows of the same letter are not counted: two precedents, two skipped as the other unit",
             (got["known"], got["precedents"], got["skipped"]), (False, 2, {"other_unit": 2}))
    got = forecast(mixed + [rec("A-3", usd=60.0)])
    check_eq("C3 three function rows price a functions story whatever the old rows say",
             (got["known"], got["high"], got["skipped"]), (True, 60.0, {"other_unit": 2}))
    got = forecast(mixed, unit="requirements")
    check_eq("C3 and a rows story is priced by rows, and the function rows are the other unit",
             (got["known"], got["precedents"], got["skipped"]), (False, 2, {"other_unit": 2}))
    check_eq("C3 another letter is another cohort, not a loss", forecast(THREE, size="S")["skipped"], {})
    check_eq("C3 a unit that is neither known word joins no cohort", forecast(THREE + [rec("U-1", unit="bananas")])["skipped"],
             {"unknown_unit": 1})
    check_eq("C3 record_unit: absent, None, known, unknown",
             [RN.record_unit(f) for f in ({}, {"size_unit": None}, {"size_unit": "functions"}, {"size_unit": "x"}, None)],
             ["requirements", "requirements", "functions", None, "requirements"])


def c4_adversarial() -> None:
    def three_plus(extra) -> dict:
        return forecast(THREE + [extra])
    got = three_plus(rec("B-1", usd=None, actual={"usd": None, "usd_low": 5.0, "usd_high": 7.0}))
    check_eq("C4 a range joins the cohort and widens it, it does not become a figure", (got["precedents"], got["low"], got["median"]),
             (4, 5.0, 20.0))
    for name, value in (("a string", "12"), ("a bool", True), ("a negative number", -4.0), ("not a number", float("nan"))):
        got = three_plus(rec("B-1", usd=value))
        check_eq(f"C4 usd as {name}: excluded and counted", (got["precedents"], got["skipped"], got["low"]), (3, {"bad_usd": 1}, 10.0))
    got = three_plus(rec("B-1", usd=1.0, actual={"incomplete": True}))
    check_eq("C4 incomplete: a floor is no price, excluded and counted", (got["precedents"], got["skipped"], got["low"]),
             (3, {"incomplete": 1}, 10.0))
    got = three_plus(rec("B-1", usd=None, actual={"usd": None, "usd_low": 9.0, "usd_high": 3.0}))
    check_eq("C4 a range turned upside down is no price", (got["precedents"], got["skipped"]), (3, {"no_price": 1}))
    got = three_plus(rec("B-1", usd=None, actual={"usd": None, "usd_low": -1.0, "usd_high": 3.0}))
    check_eq("C4 a negative end of a range is no price", (got["precedents"], got["skipped"]), (3, {"no_price": 1}))
    # several records per story: one counted, the newest by ts; the rest counted
    old = rec("A-1", usd=900.0, ts="2026-10-01T00:00:00+00:00")
    new = rec("A-1", usd=10.0, ts="2026-10-25T00:00:00+00:00")
    got = forecast([old, new, THREE[1], THREE[2]])
    check_eq("C4 two active records of one story: the newest by ts counts, the other is counted as older",
             (got["precedents"], got["high"], got["skipped"]), (3, 60.0, {"older_record": 1}))
    old["supersedes"] = []
    new["supersedes"] = [old["record_id"]]
    got = forecast([old, new, THREE[1], THREE[2]])
    check_eq("C4 a superseded record is counted, never priced", (got["precedents"], got["high"], got["skipped"]),
             (3, 60.0, {"older_record": 1}))
    # F2: an older record of a story OUTSIDE the cohort is not counted as left out; inside it, the grammar of one and of two
    other_letter = [rec("L-1", size="L", usd=900.0, ts="2026-10-01T00:00:00+00:00"),
                    rec("L-1", size="L", usd=800.0, ts="2026-10-02T00:00:00+00:00")]
    check_eq("F2 two records of a story of another letter: not counted, not said", forecast(THREE + other_letter)["skipped"], {})
    check_eq("F2 and a story of another unit is said as the other unit, its older record is not",
             forecast(THREE + [rec("O-1", unit="requirements", ts="2026-10-01T00:00:00+00:00"),
                               rec("O-1", unit="requirements", ts="2026-10-02T00:00:00+00:00")])["skipped"], {"other_unit": 1,
                                                                                                           "older_record": 1})
    line = RN.size_forecast_line({"size_forecast": forecast([old, new, THREE[1], THREE[2]]), "price": {}})
    check_not_in("F2 one older record never reads '1 older records'", "1 older records", line)
    check_in("F2 it reads as one record superseded", "1 superseded by a newer record of the same story", line)
    # F7: a recorded zero is no price (story_spend writes 0.0 when it saw no cost), never a $0.00 forecast
    zeros = [rec(f"Z-{i}", usd=0.0) for i in range(3)]
    got = forecast(zeros)
    check_eq("F7 three rows at 0.0: no price, counted, no forecast of $0.00",
             (got["known"], got["precedents"], got["skipped"]), (False, 0, {"no_price": 3}))
    got = forecast(THREE + [rec("Z-1", usd=0.0)])
    check_eq("F7 a zero beside three prices is left out as no price, the low stays 10", (got["low"], got["skipped"]),
             (10.0, {"no_price": 1}))
    no_schema = dict(THREE[0])
    del no_schema["schema_version"]
    got = forecast([no_schema, THREE[1], THREE[2]])
    check_eq("C4 a row with no schema_version is counted, not silently gone", (got["precedents"], got["skipped"]),
             (2, {"no_schema": 1}))
    check_eq("C4 a row naming no story is counted", forecast(THREE + [rec(None)])["skipped"], {"no_task": 1})
    check_eq("C4 a row that is not an object is ignored, the rest is read", forecast(THREE + ["x", 3, None])["known"], True)
    # size_final differs from sizing.json size with no override: the unit is requirements and the record is flagged
    doc = {"size": "S", "size_unit": "functions", "function_count": 3, "computed_budget": 6, "reducers_applied": []}
    check_eq("C4 size_final differs from sizing.json's size, no override: requirements, flagged",
             {k: RN.story_size_unit(doc, "M")[k] for k in ("size_unit", "size_mismatch")},
             {"size_unit": "requirements", "size_mismatch": True})
    check_eq("C4 with an override the letter is kept and the unit stays computed",
             {k: RN.story_size_unit(dict(doc, size_override="M"), "M")[k] for k in ("size_unit", "size_mismatch", "size_override")},
             {"size_unit": "functions", "size_mismatch": False, "size_override": True})
    check_eq("C4 the same letter: functions", RN.story_size_unit(doc, "S")["size_unit"], "functions")
    got = forecast(THREE + [rec("M-1", forecast={"size_mismatch": True, "size_unit": "requirements"})], unit="requirements")
    check_eq("C4 a flagged record is counted as a mismatch in any cohort", got["skipped"].get("mismatch"), 1)
    check_eq("C4 the story's override is visible in the answer", forecast(THREE, override=True)["by_override"], True)
    check_in("C4 and in the line", "The size is by override",
             RN.size_forecast_line({"size_forecast": forecast(THREE, override=True), "price": {}}))


def c5_empty_absent_corrupt() -> None:
    for name, rows in (("empty", []), ("absent", None), ("not a list", "x")):
        got = forecast(rows)
        check_eq(f"C5 a ledger that is {name}: unknown, zero precedents, no crash", (got["known"], got["precedents"]), (False, 0))
    root, base, troot = story(None)
    try:
        check_eq("C5 no ledger file: the retro says zero of three", RN.numbers("QA-1", base, troot)["size_forecast"]["precedents"], 0)
    finally:
        cleanup(root)
    root, base, troot = story([THREE[0], "{not json", THREE[1], "[1, 2]", THREE[2]])
    try:
        data = RN.numbers("QA-1", base, troot)
        check_eq("C5 a broken line and a non-object line are dropped by the reader; the rest forecasts",
                 (data["size_forecast"]["known"], data["size_forecast"]["precedents"]), (True, 3))
    finally:
        cleanup(root)
    check_eq("C5 no unit (no work/sizing.json): unknown, the reason named, never read as functions",
             (forecast(THREE, unit=None)["known"], "no work/sizing.json" in forecast(THREE, unit=None)["reason"]), (False, True))
    check_in("C5 and the line says so", "No forecast by size: the story has no work/sizing.json",
             RN.size_forecast_line({"size_forecast": forecast(THREE, unit=None)}))
    check_eq("C5 an unknown size is unknown", forecast(THREE, size="unknown")["known"], False)


def c6_own_record_excluded() -> None:
    own = rec("QA-1", usd=5000.0)
    got = forecast(THREE + [own])
    check_eq("C6 the story's own record is not a precedent, and a rerun is stable",
             (got["precedents"], got["high"], got["skipped"], got == forecast(THREE + [own, own])),
             (3, 60.0, {}, True))
    check_eq("C6 with only its own record there is nothing to forecast from", forecast([own])["precedents"], 0)


def c7_estimate_facts() -> None:
    import estimate_record
    root, base, troot = story(THREE)
    try:
        facts = RN.estimate_facts(RN.numbers("QA-1", base, troot))
        f = facts["forecast"]
        check_eq("C7 the facts carry the unit, the count and the budget",
                 (f["size_unit"], f["function_count"], f["computed_budget"]), ("functions", 7, 14))
        check_eq("C7 and the cap and the mismatch flags", (f["defect_capped"], f["size_mismatch"]), (False, False))
        check_eq("C7 the record accepts the facts", estimate_record.facts_problems(facts), [])
    finally:
        cleanup(root)
    capped_doc = {"size": "M", "size_unit": "functions", "function_count": 1, "computed_budget": 2,
                  "reducers_applied": [{"name": "defect-cap", "note": "x"}]}
    root, base, troot = story(THREE, sizing_doc=capped_doc)
    try:
        check_eq("C7 a defect cap in the sizing file is carried", RN.estimate_facts(RN.numbers("QA-1", base, troot))["forecast"]["defect_capped"], True)
    finally:
        cleanup(root)
    root, base, troot = story(THREE, sizing_doc=None)
    try:
        f = RN.estimate_facts(RN.numbers("QA-1", base, troot))["forecast"]
        check_eq("C7 no sizing file: the unit is None, never functions", (f["size_unit"], f["function_count"]), (None, None))
        check_eq("C7 and its ledger record then reads as the old unit", RN.record_unit(f), "requirements")
    finally:
        cleanup(root)
    root, base, troot = story(THREE, sizing_doc={"size": "M", "function_count": None})
    try:
        check_eq("C7 a sizing file with no size_unit is the old world: requirements",
                 RN.numbers("QA-1", base, troot)["estimate_vs_actual"]["size_unit"], "requirements")
    finally:
        cleanup(root)


def c8_dashboard_drift() -> None:
    import factory_dashboard as FD

    def drift(rows) -> list:
        return FD.estimate_signals([dict(r, delta={"direction": "above"}) for r in rows])
    old = [rec(f"O-{i}", unit=None, ts=f"2026-10-0{i}T00:00:00+00:00") for i in (1, 2)]
    new = [rec(f"N-{i}", ts=f"2026-10-2{i}T00:00:00+00:00") for i in (1, 2, 3)]
    check_eq("C8 two old and one new, three above in a row: no drift", drift(old + new[:1]), [])
    check_eq("C8 three old: the rows drift is still said, in the words it always had",
             drift(old + [rec("O-3", unit=None, ts="2026-10-03T00:00:00+00:00")]),
             ["The scale underestimates M: 3 tasks in a row above the range"])
    check_eq("C8 three new: drift on the function count", drift(new),
             ["The scale underestimates M on the function count: 3 tasks in a row above the range"])
    check_eq("C8 old, old, new, new, new: the new three drift, the old two do not mix in", drift(old + new),
             ["The scale underestimates M on the function count: 3 tasks in a row above the range"])
    check_eq("C8 three of an unknown unit join no cohort",
             drift([rec(f"U-{i}", unit="x", ts=f"2026-10-0{i}T00:00:00+00:00") for i in (1, 2, 3)]), [])
    check_eq("C8 the size cell says rows for an old record, nothing for a functions record, and says an unknown unit",
             [FD.size_unit_mark(f) for f in ({"size_final": "M"}, {"size_final": "M", "size_unit": "functions"},
                                              {"size_final": "M", "size_unit": "x"}, {})], [" (rows)", "", " (unit unknown)", ""])


def c8b_metric_signals_drift() -> None:
    import metric_signals as MS

    def snapshot(rows) -> dict:
        return {"as_of": "2026-10-30T10:00:00Z", "input_hash": "h",
                "metrics": [{"id": "C08", "label": "Tokenomics band hit", "value": None, "status": "unavailable",
                             "sample_size": 0, "scope": "project", "formula_version": 1,
                             "window_start": "2026-10-01T00:00:00Z", "window_end": "2026-10-30T10:00:00Z"}],
                "estimates": [dict(r, completed=True, complete_cost=r["actual"]["usd"],
                                   ts=r["created_at"], delta={"direction": "above"}) for r in rows]}

    def active(rows) -> list:
        with tempfile.TemporaryDirectory() as td:
            receipt, _ = MS.refresh(td, snapshot(rows), {}, [])
            return sorted(s["id"] for s in receipt["signals"]
                          if s["id"].startswith("legacy-estimate-v1:") and s.get("status") == "active")
    old = [rec(f"O-{i}", unit=None, ts=f"2026-10-0{i}T00:00:00+00:00") for i in (1, 2)]
    new = [rec(f"N-{i}", ts=f"2026-10-2{i}T00:00:00+00:00") for i in (1, 2, 3)]
    check_eq("C8b two old and one new above the range: no signal, a change of unit is not drift", active(old + new[:1]), [])
    check_eq("C8b three old: the rows signal keeps the id it always had",
             active(old + [rec("O-3", unit=None, ts="2026-10-03T00:00:00+00:00")]), ["legacy-estimate-v1:M-above"])
    check_eq("C8b three new: a signal of the function count, with an id of its own", active(new), ["legacy-estimate-v1:M-functions-above"])
    check_eq("C8b old, old, new, new, new: only the new cohort drifts", active(old + new), ["legacy-estimate-v1:M-functions-above"])


def c10_nearest_precedents() -> None:
    root, base, troot = story(THREE)
    try:
        facts = RN.estimate_facts(RN.numbers("QA-1", base, troot))
        facts["drivers"] = ["size: login form checks"]
        row = {"task": "QA-1", "forecast": facts["forecast"], "drivers": facts["drivers"]}
        got = sizing.nearest_precedents([row], 14, {"login", "checks"})
        check_eq("C10 `nearest_precedents` matches a record `estimate_facts` wrote, by its computed budget",
                 [(p["task"], p["budget"], p["overlap"]) for p in got], [("QA-1", 14, 2)])
    finally:
        cleanup(root)


def c11_render_lines() -> None:
    known = RN.size_forecast_line({"size_forecast": forecast(THREE), "price": {"price_low_usd": 30.0, "price_high_usd": 30.0},
                                   "estimate_vs_actual": {"function_count": 1}})
    check_eq("C11 the known line, whole", known, "**Forecast from precedents:** M stories on the function count so far: "
             "$10.00..$60.00, median $20.00, 3 precedents, at the rates of each run. This one: $30.00, 1 function.")
    left = RN.size_forecast_line({"size_forecast": forecast(THREE + [rec("O-1", unit=None), rec("I-1", actual={"incomplete": True})]),
                                  "price": {"price_low_usd": 1.0, "price_high_usd": 9.0}, "incomplete": True})
    check_in("C11 what was left out is said in plain words, with no field name",
             "2 records left out: 1 incomplete (a floor is no price), 1 counted in the other unit.", left)
    check_in("C11 a range of the story's own price is a range and a floor is marked", "This one: from $1.00 to $9.00 (a floor", left)
    check_not_in("C11 no key name reaches a person", "other_unit", left)
    rows_line = RN.size_forecast_line({"size_forecast": forecast([rec(f"O-{i}", unit=None) for i in range(3)], unit="requirements")})
    check_in("C11 a rows story is priced by rows and says so", "M stories on the requirement rows so far", rows_line)
    root, base, troot = story(THREE)
    try:
        data = RN.numbers("QA-1", base, troot)
        check_in("C11 the numbers of a story render the line", "Forecast from precedents", RN.render(data))
        check_not_in("C11 a facts file of before CD1-5 renders no forecast line", "Forecast from precedents",
                     RN.render({k: v for k, v in data.items() if k != "size_forecast"}))
    finally:
        cleanup(root)


def c12_no_money_in_the_test_report() -> None:
    import report_facts
    root, base, troot = story(THREE)
    try:
        RN.write_retro("QA-1", base, troot)
        built = json.dumps(report_facts.build(troot), default=str)
        check_not_in("C12 `report_facts` output holds no forecast line", "Forecast from precedents", built)
        check_not_in("C12 and no forecast key", "size_forecast", built)
        check_in("C12 the retro file does carry it (money lives only in retro.md and its facts, P18)", "Forecast from precedents",
                 (troot / "retro.md").read_text(encoding="utf-8"))
    finally:
        cleanup(root)


def main() -> None:
    c1_and_c9_control_values()
    c2_boundary()
    c3_units_do_not_mix()
    c4_adversarial()
    c5_empty_absent_corrupt()
    c6_own_record_excluded()
    c7_estimate_facts()
    c8_dashboard_drift()
    c8b_metric_signals_drift()
    c10_nearest_precedents()
    c11_render_lines()
    c12_no_money_in_the_test_report()
    finish("test_size_forecast")


if __name__ == "__main__":
    main()
