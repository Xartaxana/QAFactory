#!/usr/bin/env python3
"""RN1-21 (t-1699 D3, node N1): a Playwright run's report rows are bound to the instances that were selected.

Every input is a COPY of what run 3 of LOCAL-1 (the MyBooks stand, 02-03.11.2026) wrote, under `fixtures/local1-playwright/`
(`SOURCE.md` names each original and its sha256; the machine root is the token `{project_root}`, replaced here by a temp root).
What is proved:
  * N1-1: a bare-title or testDir-relative `report_test_id` binds ITS row (`red_sandbox.selection_rows`), and only its row -
    the adversarial table (K-N1-1b) pins the error direction: `not_run`, never another test's row
  * N1-2: the run block counts selected vs matched (`report_scope.selection_count`) and the console says a short count once
  * N1-3: the manifest join reads every spelling of an instance (`C.instance_id_aliases`)
  * N1-4: `manifest_from_tests.py` reads the real TypeScript spec into 11 rows (the code check; no code change)
"""
import json
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

import contract as C  # noqa: E402
import finalize_task as F  # noqa: E402
import red_sandbox as RS  # noqa: E402
import reporters  # noqa: E402
import run_suite as RUN  # noqa: E402

FX = Path(__file__).resolve().parent / "fixtures" / "local1-playwright"
FILE = "tests/api/cart/add-to-cart.spec.ts"
CLASSNAME = "api\\cart\\add-to-cart.spec.ts"            # what Playwright writes: the path from its testDir, with backslashes
TICKET = "LOCAL-1"
EF39 = "ef39dbfc032eb9587718"
TAG = "@regression "


def fixture_text(name: str, root: Path) -> str:
    """A fixture's text with `{project_root}` replaced by `root` (JSON-escaped for a .json, whose backslashes are doubled)."""
    text = (FX / name).read_text(encoding="utf-8")
    return text.replace("{project_root}", json.dumps(str(root))[1:-1] if name.endswith(".json") else str(root))


def fixture_json(name: str, root: Path):
    return json.loads(fixture_text(name, root))


def real_rows() -> list:
    return reporters.read_rows(FX / "ef39-repair_verify.junit.xml", "junit-xml")


def title_of(test_id: str) -> str:
    return test_id.partition("::")[2] or test_id


def request_for(contracts: dict, purpose: str = "repair_verify") -> dict:
    return {"purpose": purpose, "selected_instance_ids": list(contracts), "instance_contracts": contracts,
            "profile_id": "web", "dispatch_id": "S5-qa-automator-3"}


def ef39_contracts(block0: dict) -> dict:
    """The 4 contracts of the ef39 window: the file and the BARE-TITLE report id the block's own rows carry."""
    return {r["instance_id"]: {"file": FILE, "report_test_id": r["test_id"]} for r in block0["results"]}


def sel(report_test_id: str, file: str = FILE, rows=None, **extra) -> list:
    return RS.selection_rows(real_rows() if rows is None else rows, dict({"file": file, "report_test_id": report_test_id}, **extra))


# ----------------------------------------------------------------------------------------------------------------------------
def n1_1a_the_ef39_window_binds_its_four_rows(root: Path) -> None:
    block0 = fixture_json("ef39-run-block.json", root)
    rows = real_rows()
    print(f"premise (copied block): {len(block0['results'])} selected, statuses "
          f"{sorted({r['status'] for r in block0['results']})}, reasons {sorted({r['reason'] for r in block0['results']})}, "
          f"report_matched {sorted({r['report_matched'] for r in block0['results']})}; the report holds {len(rows)} rows, "
          f"test_id of the first: {rows[0]['test_id']!r}")
    check_eq("premise: today's block says 4 x not_run 'id not in report'",
             sorted((r["status"], r["reason"]) for r in block0["results"]), [("not_run", "id not in report")] * 4)
    check_eq("premise: the report's classname is the testDir path with backslashes", rows[0]["test_id"].split("::")[0], CLASSNAME)
    contracts = ef39_contracts(block0)
    check("premise: every contract id is a BARE title (no `::`)", all("::" not in c["report_test_id"] for c in contracts.values()))
    block = RUN.build_run_block(request_for(contracts), {"results": rows, "execution_status": "passed"}, EF39)
    check_eq("K-N1-1a: 4 rows passed", [r["status"] for r in block["results"]], ["passed"] * 4)
    check_eq("K-N1-1a: every row is report_matched", [r["report_matched"] for r in block["results"]], [True] * 4)
    chosen = {title_of(c["report_test_id"]) for c in contracts.values()}
    others = sorted(r["test_id"] for r in rows if title_of(r["test_id"]) not in chosen)
    check_eq("K-N1-1a: unmatched_report_rows are the 6 other titles", block["report_scope"]["unmatched_report_rows"], others)
    check_eq("K-N1-1a: and they are 6", len(others), 6)
    check_eq("K-N1-1a: no row carries a reason code", [r.get("reason_code") for r in block["results"]], [None] * 4)


ADVERSARIAL = [
    # (param id, report_test_id, contract file, expected: "none" | "bound")
    ("prefix title (...TC_01)", TAG + "LOCAL-1_TC_01", FILE, "none"),
    ("the contract's title is a prefix of a real title",
     TAG + "LOCAL-1_TC_010 repeat add of the same book", FILE, "none"),
    ("the contract's title is longer than a real title", TAG + "LOCAL-1_TC_012 guest and user carts are isolated again", FILE, "none"),
    ("same title, another file of the project", TAG + "LOCAL-1_TC_010 repeat add of the same book sums quantities in one line",
     "tests/api/cart/other.spec.ts", "none"),
    ("same title, a neighbour directory (mycart)", TAG + "LOCAL-1_TC_010 repeat add of the same book sums quantities in one line",
     "tests/api/mycart/add-to-cart.spec.ts", "none"),
    ("empty report_test_id", "", FILE, "none"),
    ("only `::` and a file", FILE + "::", FILE, "none"),
    ("smoke tag for a regression title", "@smoke LOCAL-1_TC_010 repeat add of the same book sums quantities in one line", FILE, "none"),
    ("case-changed title", TAG + "local-1_tc_010 repeat add of the same book sums quantities in one line", FILE, "none"),
    ("run-dir id names another file", "tests/api/other/add-to-cart.spec.ts::" + TAG +
     "LOCAL-1_TC_010 repeat add of the same book sums quantities in one line", FILE, "none"),
    ("run-dir id names a neighbour (mycart) file", "tests/api/mycart/add-to-cart.spec.ts::" + TAG +
     "LOCAL-1_TC_010 repeat add of the same book sums quantities in one line", FILE, "none"),
    ("bare title (the bug)", TAG + "LOCAL-1_TC_010 repeat add of the same book sums quantities in one line", FILE, "bound"),
    ("run-dir id against the backslash classname", FILE + "::" + TAG +
     "LOCAL-1_TC_010 repeat add of the same book sums quantities in one line", FILE, "bound"),
    ("a shorter tail of the file", "cart/add-to-cart.spec.ts::" + TAG +
     "LOCAL-1_TC_010 repeat add of the same book sums quantities in one line", FILE, "bound"),
    ("the whole id, as before (a report id with backslashes)", CLASSNAME + "::" + TAG +
     "LOCAL-1_TC_010 repeat add of the same book sums quantities in one line", FILE, "bound"),
]


def n1_1b_adversarial() -> None:
    for name, report_id, file, expected in ADVERSARIAL:
        got = sel(report_id, file)
        if expected == "none":
            check(f"K-N1-1b [{name}]: no row", got == [], str([r["test_id"] for r in got]))
        else:
            check(f"K-N1-1b [{name}]: bound to the one TC_010 row",
                  [r["test_id"] for r in got] == [CLASSNAME + "::" + TAG + "LOCAL-1_TC_010 repeat add of the same book sums quantities in one line"],
                  str([r["test_id"] for r in got]))
    # E4: a contract WITHOUT `file` is matched as today (the whole id), never by name
    bare = TAG + "LOCAL-1_TC_010 repeat add of the same book sums quantities in one line"
    check_eq("K-N1-1b [E4 no file: a bare title is not bound by name]",
             RS.selection_rows(real_rows(), {"report_test_id": bare}), [])
    # the other two branches keep their rule: `classname_match` and `report_match` are untouched by the new one
    check_eq("K-N1-1b [file_suffix branch unchanged: a bare title (no `::`) binds nothing]",
             sel(bare, classname_match="file_suffix"), [])
    # E3: one title in two classnames - both rows are returned, the caller reads them as ambiguous
    title = TAG + "LOCAL-1_TC_010 repeat add of the same book sums quantities in one line"
    two = [{"test_id": "api\\cart\\add-to-cart.spec.ts::" + title, "status": "passed"},
           {"test_id": "cart\\add-to-cart.spec.ts::" + title, "status": "passed"}]
    check_eq("K-N1-1b [one title in two classnames]: both rows come back", len(sel(title, rows=two)), 2)
    check("K-N1-1b [one title in two classnames]: and they are said to differ", RS.classnames_differ(sel(title, rows=two)))
    block = RUN.build_run_block(request_for({"i": {"file": FILE, "report_test_id": title}}),
                                {"results": two, "execution_status": "passed"}, "x1")
    check_eq("K-N1-1b [one title in two classnames]: not_run, ambiguous",
             (block["results"][0]["status"], block["results"][0]["reason"], block["results"][0]["report_matched"]),
             ("not_run", "report identity is ambiguous; multiple rows matched", False))
    # one report row wanted by two selected instances is nobody's (the existing claims rule keeps working over the new matcher)
    block = RUN.build_run_block(request_for({"a": {"file": FILE, "report_test_id": title}, "b": {"file": FILE, "report_test_id": CLASSNAME + "::" + title}}),
                                {"results": real_rows(), "execution_status": "passed"}, "x2")
    check_eq("K-N1-1b [two instances claim one row]: both not_run", [r["status"] for r in block["results"]], ["not_run", "not_run"])


def n1_1c_nearest() -> None:
    title = TAG + "LOCAL-1_TC_010 repeat add of the same book sums quantities in one line"
    real = CLASSNAME + "::" + title
    check_eq("K-N1-1c: a bare title one character off gives the real row", RS.nearest_row(real_rows(), {"report_test_id": title[:-1] + "x"}), real)
    check_eq("K-N1-1c: a run-dir id one character off gives the real row",
             RS.nearest_row(real_rows(), {"report_test_id": FILE + "::" + title[:-1] + "x"}), real)
    check_eq("K-N1-1c: an unrelated title gives None", RS.nearest_row(real_rows(), {"report_test_id": "zzzz qqqq"}), None)
    check_eq("K-N1-1c: an empty id gives None", RS.nearest_row(real_rows(), {"report_test_id": ""}), None)


def n1_1d_bind_row() -> None:
    title = TAG + "LOCAL-1_TC_010 repeat add of the same book sums quantities in one line"
    instance = title[len(TAG):]
    row, note = RS.bind_row({"instance_id": instance}, {instance: {"file": FILE, "report_test_id": title}}, real_rows(), "junit-xml")
    check_eq("K-N1-1d: the probe's reader binds the bare-title contract to the TC_010 row", (row or {}).get("test_id"), CLASSNAME + "::" + title)
    row, note = RS.bind_row({"instance_id": instance}, {instance: {"file": FILE, "report_test_id": title + "!"}}, real_rows(), "junit-xml")
    check_eq("K-N1-1d: a title one character off binds nothing, and says so", (row, "no row of the junit-xml report" in note), (None, True))


# ----------------------------------------------------------------------------------------------------------------------------
def n1_2a_the_16f0_case(root: Path) -> None:
    summary = fixture_json("16f0-initial.summary.json", root)
    command = summary["command"]
    greps = [command[i + 1] for i, word in enumerate(command) if word == "--grep"]
    log = (FX / "16f0-initial.log").read_text(encoding="utf-8")
    print(f"premise (copied run): {len(greps)} `--grep` options, the first is {greps[0]!r}; log line 1: {log.splitlines()[0]!r}; "
          f"totals.tests={summary['totals']['tests']}, results={len(summary['results'])}")
    check_eq("premise: SIX --grep options, one per instance", len(greps), 6)
    check_eq("premise: the log says no tests were found", log.splitlines()[0], "Error: No tests found.")
    check_eq("premise: the report holds no row", (summary["totals"]["tests"], summary["results"]), (0, []))
    titles = [re.sub(r"\\(.)", r"\1", g)[1:-1] for g in greps]          # `^<escaped title>$` -> the bare title
    check("premise: every title is the bare `@regression ...` title", all(t.startswith(TAG) for t in titles), str(titles[:2]))
    contracts = {t[len(TAG):]: {"file": FILE, "report_test_id": t} for t in titles}
    block = RUN.build_run_block(request_for(contracts, "initial"), summary, "16f062e1e04674c1b12f")
    check_eq("K-N1-2a: selection_count is {6, 0, 0}", block["report_scope"]["selection_count"],
             {"selected": 6, "matched": 0, "report_rows": 0})
    check_eq("K-N1-2a: every row keeps not_run and its code (E7: one code per row)",
             sorted({(r["status"], r["reason_code"]) for r in block["results"]}), [("not_run", "id_not_in_report")])
    line = RUN.selection_line(block, "work/run-blocks/x.json")
    check("K-N1-2a: the console line is ONE line", line.count("\n") == 0 and bool(line), repr(line))
    check_in("K-N1-2a: it counts 0 of 6 and 0 report rows", "selection: 0 of 6 selected tests are in the report (0 report rows);", line)
    check_in("K-N1-2a: it says a repeated option keeps one value", "a runner that keeps one value of a repeated option runs one of them", line)
    check_in("K-N1-2a: it says a pattern may match more than the title", "a pattern the runner matches against more than the title may match none", line)
    check_in("K-N1-2a: it names the door", "check the selector_args of the unmatched instances (run block work/run-blocks/x.json, "
             "report_scope.unmatched_report_rows)", line)
    check_not_in("K-N1-2a: it names no runner", "playwright", line.lower())


def n1_2b_ef39_has_no_line(root: Path) -> None:
    block0 = fixture_json("ef39-run-block.json", root)
    block = RUN.build_run_block(request_for(ef39_contracts(block0)), {"results": real_rows(), "execution_status": "passed"}, EF39)
    check_eq("K-N1-2b: ef39 after N1-1 gives {4, 4, 10}", block["report_scope"]["selection_count"],
             {"selected": 4, "matched": 4, "report_rows": 10})
    check_eq("K-N1-2b: and no line", RUN.selection_line(block, "p"), "")


def n1_2c_boundaries(root: Path) -> None:
    block0 = fixture_json("ef39-run-block.json", root)
    contracts = ef39_contracts(block0)
    summary = {"results": real_rows(), "execution_status": "passed"}
    ids = list(contracts)
    # M = N: no line (K-N1-2b); M = N-1: the line
    short = {k: dict(v) for k, v in contracts.items()}
    short[ids[0]]["report_test_id"] += " (renamed)"
    block = RUN.build_run_block(request_for(short), summary, EF39)
    check_eq("K-N1-2c: M = N-1 counts {4, 3, 10}", block["report_scope"]["selection_count"], {"selected": 4, "matched": 3, "report_rows": 10})
    check_in("K-N1-2c: M = N-1 prints the line", "selection: 3 of 4 selected tests are in the report (10 report rows);", RUN.selection_line(block, "p"))
    check_eq("K-N1-2c: the unmatched row keeps its code `id_not_in_report` (E7)", block["results"][0]["reason_code"], "id_not_in_report")
    check_eq("K-N1-2c: the other three are passed", [r["status"] for r in block["results"][1:]], ["passed"] * 3)
    # a selected test with no `file` keeps its row byte for byte (E4): no code appears (the pin of test_run_suite_reports)
    plain = {k: dict(v) for k, v in contracts.items()}
    plain[ids[0]] = {"report_test_id": "no such test"}
    block = RUN.build_run_block(request_for(plain), summary, EF39)
    first = block["results"][0]
    check_eq("K-N1-2c: a no-file row stays not_run 'report row missing' with no code (E4)",
             (first["status"], first["reason"], "reason_code" in first), ("not_run", "report row missing", False))
    check_eq("K-N1-2c: but it IS counted short: {4, 3, 10}", block["report_scope"]["selection_count"],
             {"selected": 4, "matched": 3, "report_rows": 10})
    # a file contract whose row is ambiguous has no code of its own: it IS in the report, so "short" would be a false cause (t-1748 F1)
    title = TAG + "LOCAL-1_TC_010 repeat add of the same book sums quantities in one line"
    two = [{"test_id": "api\\cart\\add-to-cart.spec.ts::" + title, "status": "passed"},
           {"test_id": "cart\\add-to-cart.spec.ts::" + title, "status": "passed"}]
    block = RUN.build_run_block(request_for({"i": {"file": FILE, "report_test_id": title}}), {"results": two, "execution_status": "passed"}, "x1")
    check_eq("K-N1-2c: an ambiguous file row stays not_run with no code (no `selection_short`: the constant is gone)",
             (block["results"][0]["status"], "reason_code" in block["results"][0], hasattr(RUN, "SELECTION_SHORT_CODE")),
             ("not_run", False, False))
    # t-1748 F1: the critic's case - both bare titles ARE in the report, the run is inconclusive (a runtime change)
    both = {"a": {"file": FILE, "report_test_id": title}, "b": {"file": FILE, "report_test_id": title + " two"}}
    rows2 = [{"test_id": CLASSNAME + "::" + title, "status": "passed"}, {"test_id": CLASSNAME + "::" + title + " two", "status": "passed"}]
    summary_i = {"results": rows2, "execution_status": "inconclusive", "runtime_change_error": "runtime changed"}
    block = RUN.build_run_block(request_for(both), summary_i, "x3")
    check_eq("F1: inconclusive, both rows in the report: not_run with the runtime cause and no code",
             [(r["status"], r["reason"], "reason_code" in r) for r in block["results"]], [("not_run", "runtime changed", False)] * 2)
    check_eq("F1: ... and no selection line (the selectors are right, the runtime changed)", RUN.selection_line(block, "p"), "")
    block = RUN.build_run_block(request_for(both), {"results": rows2, "execution_status": "passed"}, "x4")
    check_eq("F1 control: the same report, passed: both matched, no line", (block["report_scope"]["selection_count"]["matched"], RUN.selection_line(block, "p")), (2, ""))
    # E7 beyond: a row that has a code keeps it - the project's own timeout wins over the count
    timeout = {"how": "hard_kill", "tests": [title], "sentence": "the project's timeout killed it"}
    block = RUN.build_run_block(request_for({"i": {"file": FILE, "report_test_id": title}}),
                                {"results": two, "execution_status": "passed", "timeout": timeout}, "x1")
    check_eq("K-N1-2c: a row with PROJECT_TIMEOUT_CODE keeps it (E7)", block["results"][0]["reason_code"], RUN.PROJECT_TIMEOUT_CODE)
    # N = 0: a whole-suite run is not called short (E5). build_run_block returns None before any count for no selection (reality);
    # the reader is safe over a block whose count says 0 selected
    check_eq("K-N1-2c: N = 0: build_run_block writes no block at all (its early return, unchanged)",
             RUN.build_run_block(request_for({}), summary, EF39), None)
    zero = {"report_scope": {"selection_count": {"selected": 0, "matched": 0, "report_rows": 10}}}
    check_eq("K-N1-2c: N = 0: the reader prints no line", RUN.selection_line(zero, "p"), "")
    check_eq("K-N1-2c: no block / no count: no line", (RUN.selection_line(None), RUN.selection_line({"report_scope": {}})), ("", ""))


# ----------------------------------------------------------------------------------------------------------------------------
def project_with_config() -> Path:
    """A temp project whose config carries the case id form the stand's config carries (`{ticket}_TC_{nnn}`)."""
    root = harness.temp_project("qa-pw-identity-")
    cfg_path = root / "qa-factory" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["case_id_form"] = "{ticket}_TC_{nnn}"
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    C.case_config_reset()
    return root


def reduce_over(root: Path, manifest: dict, blocks: dict, with_ef39_report: bool = False) -> dict:
    task = root / "qa-factory" / "artifacts" / TICKET
    (task / "work" / "run-blocks").mkdir(parents=True, exist_ok=True)
    (task / "work" / "automation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for name, block in blocks.items():
        (task / "work" / "run-blocks" / f"{name}.json").write_text(json.dumps(block), encoding="utf-8")
    if with_ef39_report:
        relative = task / "evidence" / "runs" / EF39
        relative.mkdir(parents=True, exist_ok=True)
        shutil.copy(FX / "ef39-repair_verify.junit.xml", relative / "repair_verify-ef39dbfc032eb9587718-20261103-003000.junit.xml")
    C.case_config_reset()
    return F.reduce(task)[0]


def join_findings(report: dict) -> list:
    return [f for f in report["factory_findings"] if f["code"] == "INSTANCE_MANIFEST_JOIN_FAILED"]


def block_of(rows: list, name: str = "b1", stamp: str = "2026-11-02T23:30:00+00:00") -> dict:
    return {"block_id": name, "attempt_id": name, "attempt_started_at": stamp,
            "results": [dict(r, status="passed", attempt_id=name) for r in rows]}


def n1_3a_the_old_spelling_joins(root: Path) -> None:
    manifest = fixture_json("manifest-run3.json", root)
    tests = manifest["tests"]
    target = next(t for t in tests if "TC_010" in t["instance_id"])
    spelled = "LOCAL-1_TC_010" + C.INSTANCE_SEP + target["instance_id"]
    old_keys = {C.test_instance_id(t) for t in tests}
    print(f"premise: the join was keyed by C.test_instance_id only: {len(old_keys)} keys; the 0.7.7 spelling {spelled!r} is one of "
          f"them: {spelled in old_keys}; it is an alias of its row: {spelled in C.instance_id_aliases(target, C.case_config(root))}")
    check("premise: the old keys do not hold the 0.7.7 spelling (it was a phantom)", spelled not in old_keys)
    check("premise: the alias reader answers to it", spelled in C.instance_id_aliases(target, C.case_config(root)))
    report = reduce_over(root, manifest, {"b1": block_of([{"instance_id": spelled}])})
    check_eq("K-N1-3a: no join finding", join_findings(report), [])
    row = report["results"][0]
    check_eq("K-N1-3a: the row is joined to the manifest row of TC_010 (its case links are the manifest's)",
             (row.get("current_reason"), row.get("case_version_links")), (None, target["case_version_links"]))


def n1_3b_two_instances_of_one_case(root: Path) -> None:
    case = "LOCAL-1_TC_009"
    rows = [{"case": case, "covers": [case], "file": "tests/a.spec.ts", "test": "test_a", "instance_id": f"test_a[{p}]",
             "parameters": {"p": p}, "selector": "test_a"} for p in ("x", "y")]
    report = reduce_over(root, {"tests": rows}, {"b1": block_of([{"instance_id": "test_a[x]"}, {"instance_id": case + C.INSTANCE_SEP + "test_a[y]"}])})
    check_eq("K-N1-3b: `test_a[x]` and the 0.7.7 `case::test_a[y]` both join: no finding", join_findings(report), [])
    got = {r["instance_id"]: r.get("parameters") for r in report["results"]}
    check_eq("K-N1-3b: each joins ITS row (x to x, y to y)", got, {"test_a[x]": {"p": "x"}, case + C.INSTANCE_SEP + "test_a[y]": {"p": "y"}})
    # E8: an alias that answers two DISTINCT manifest rows is a finding, never a join of two tests
    clash = [{"case": "LOCAL-1_TC_008", "covers": ["LOCAL-1_TC_008"], "file": "tests/a.spec.ts", "test": "dup", "instance_id": "dup[x]"},
             {"case": "LOCAL-1_TC_009", "covers": ["LOCAL-1_TC_009"], "file": "tests/a.spec.ts", "test": "dup",
              "instance_id": "LOCAL-1_TC_008" + C.INSTANCE_SEP + "dup[x]"}]
    report = reduce_over(root, {"tests": clash}, {"b1": block_of([{"instance_id": "dup[x]"}])})
    found = join_findings(report)
    check_eq("K-N1-3b [E8]: two distinct rows answer to `dup[x]`: one finding, today's text",
             [(f["entity"], f["detail"]) for f in found], [("dup[x]", "duplicate manifest identity")])
    check_eq("K-N1-3b [E8]: and the row is not joined", report["results"][0].get("current_reason"), F.JOIN_FAILED)
    # none answers: today's text
    report = reduce_over(root, {"tests": rows}, {"b1": block_of([{"instance_id": "test_a[z]"}])})
    check_eq("K-N1-3b: no row answers: `no manifest row`", [f["detail"] for f in join_findings(report)], ["no manifest row"])


def n1_3c_run3_manifest_with_the_ef39_rows(root: Path) -> None:
    manifest = fixture_json("manifest-run3.json", root)
    block = fixture_json("ef39-run-block.json", root)
    check_eq("premise: the run-3 manifest holds 11 instances", len({C.test_instance_id(t) for t in manifest["tests"]}), 11)
    every = block_of([{"instance_id": C.test_instance_id(t)} for t in manifest["tests"]], "b0", "2026-11-02T20:00:00+00:00")
    report = reduce_over(root, manifest, {"b0": every, "b1": block}, with_ef39_report=True)
    check_eq("K-N1-3c: 0 join findings over the run-3 manifest and the 4 ef39 rows", join_findings(report), [])
    check_eq("K-N1-3c: 11 instances stand in the current results", len({r["instance_id"] for r in report["current_results"]}), 11)


# ----------------------------------------------------------------------------------------------------------------------------
def n1_4a_manifest_from_tests_reads_the_real_spec(root: Path) -> None:
    spec = (FX / "add-to-cart.spec.ts").read_text(encoding="utf-8")
    titles = re.findall(r"^test\('" + re.escape(TAG) + r"(.*?)', async", spec, re.M)
    manifest = json.loads((FX / "manifest-run3.json").read_text(encoding="utf-8"))
    print(f"premise: the copied spec holds {len(titles)} `test('@regression ...` calls; the run-3 manifest holds {len(manifest['tests'])} tests[] rows")
    check_eq("premise: 11 literal titles in the spec", len(titles), 11)
    project = harness.temp_project("qa-pw-n14-")
    try:
        cfg_path = project / "qa-factory" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["case_id_form"] = "{ticket}_TC_{nnn}"
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        task = project / "qa-factory" / "artifacts" / TICKET
        (task / "work" / "run-blocks").mkdir(parents=True)
        (task / "state").mkdir(parents=True)
        links = {}
        for t in manifest["tests"]:
            for link in t["case_version_links"]:
                links[link["case_id"]] = link
        (task / "state" / "story-case-links.json").write_text(json.dumps({
            "schema_version": 2, "task_id": TICKET,
            "links": [dict(l, path=f"work/test-cases/{l['case_id']}.md", area="cart") for l in links.values()]}), encoding="utf-8")
        (task / "state" / "controller.json").write_text(json.dumps({"dispatches": {"S5-qa-automator-1": {
            "id": "S5-qa-automator-1", "stage": "S5", "role": "qa-automator", "status": "running", "scope": sorted(links)}}}), encoding="utf-8")
        shutil.copy(FX / "manifest-run3.json", task / "work" / "automation-manifest.json")
        (project / "tests" / "api" / "cart").mkdir(parents=True)
        shutil.copy(FX / "add-to-cart.spec.ts", project / FILE)
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project))
        done = harness.run_script("manifest_from_tests.py", "--task", TICKET, "--dispatch", "S5-qa-automator-1", "--file", FILE,
                                  "--dry-run", "--json", cwd=project, env=env)
        check_eq("K-N1-4a: manifest_from_tests exits 0", done.returncode, 0)
        out = json.loads(done.stdout) if done.stdout.strip() else {}
        got = [t["instance_id"] for t in (out.get("fragment") or {}).get("tests") or []]
        check_eq("K-N1-4a: 11 tests[] rows", len(got), 11)
        check_eq("K-N1-4a: each id is the title without `@regression `", sorted(got), sorted(titles))
        check_eq("K-N1-4a: and they are the ids the run-3 manifest holds", sorted(got), sorted(t["instance_id"] for t in manifest["tests"]))
    finally:
        cleanup(project)
        C.case_config_reset()


def main() -> None:
    root = temp_dir("qa-pw-substitute-")          # the `{project_root}` of the fixtures: a path that exists on this machine
    try:
        n1_1a_the_ef39_window_binds_its_four_rows(root)
        n1_1b_adversarial()
        n1_1c_nearest()
        n1_1d_bind_row()
        n1_2a_the_16f0_case(root)
        n1_2b_ef39_has_no_line(root)
        n1_2c_boundaries(root)
        for step in (n1_3a_the_old_spelling_joins, n1_3b_two_instances_of_one_case, n1_3c_run3_manifest_with_the_ef39_rows):
            project = project_with_config()
            try:
                step(project)
            finally:
                cleanup(project)
                C.case_config_reset()
        n1_4a_manifest_from_tests_reads_the_real_spec(root)
    finally:
        cleanup(root)
    finish("test_playwright_identity_local1")


if __name__ == "__main__":
    main()
