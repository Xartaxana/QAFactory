#!/usr/bin/env python3
"""t-2277 W3 (owner 11.11.2026): every test result the report shows says whether it came from real code or from a mock.

`ledger.real_or_mock` is the one producer; `ledger.build` writes it on every test row, `report_facts` renders it on every `Proven`
line, `validate_artifacts.check_report_left_with_you` names a line that lacks it. The owner's example is run end to end: the first run on a
mocked API (every line says `on a mock: api`), then the API is real and one call is kept by the person's decision (that test says
`kept by the person's decision`, the others `real code`). A green stays green in both.

Run on its own: `python -B scripts/tests/test_real_or_mock.py`.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import ledger as L  # noqa: E402
import report_facts as RF  # noqa: E402
import validate_artifacts as V  # noqa: E402

REGISTER = "---\ntask: T-1\n---\n\n## Register\n\n| R | Requirement | source | derived_from | verifiable | ac_ref |\n|---|---|---|---|---|---|\n| R-1 | The cart adds a book | ac | - | yes | AC-1 |\n"
PLAN = ("---\ntask: T-1\n---\n# Test plan - T-1\n\n## Plan\n\n| TS | what we verify | R | defect hypothesis | impact class | priority | observable | oracle | "
        "disposition + reason | fit | level | technique |\n|---|---|---|---|---|---|---|---|---|---|---|---|\n| TS-1 | add | R-1 | state @ add | degraded | P2 | "
        "diff:src/a.py:1 | requirement:R-1 | `automate` - core AC | new | api | decision table |\n\n## Recommended regression\n\n1. run the cart suite\n")
CASE = "---\nid: TC-001\ntitle: Add\narea: cart\ntask: T-1\ncovers: [R-1]\nplan_row: TS-1\n---\nRequirements: R-1\nPlan row: TS-1\n\n## Then\n1. The cart holds the book.\n"


def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value, (dict, list)) else value, encoding="utf-8", newline="\n")


def entry(iid: str, sides: dict, provisional=None) -> dict:
    row = {"case": "TC-001", "covers": ["TC-001"], "file": f"tests/{iid}.py", "instance_id": iid, "test_function": iid,
           "status": "green", "critic_verdict": "approved", "sides": sides}
    if provisional is not None:
        row["provisional"] = provisional
    return row


def run_row(iid: str, met, status: str = "passed") -> dict:
    return {"instance_id": iid, "case": "TC-001", "status": status, "sides_met": met}


def story(tests, rows, sides, provisional=None):
    root = temp_project("qa-real-or-mock-")
    task = root / "qa-factory" / "artifacts" / "T-1"
    work = task / "work"
    write(work / "requirements-register.md", REGISTER)
    write(task / "test-plan.md", PLAN)
    write(work / "test-cases" / "cart" / "TC-001.md", CASE)
    manifest = {"tests": tests, "then_bindings": [{"case": "TC-001", "then": 1, "instance_id": t["instance_id"], "status": "covered"} for t in tests]}
    if provisional:
        manifest["provisional"] = provisional
    write(work / "automation-manifest.json", manifest)
    write(work / "run-report.json", {"schema_version": 2, "task_id": "T-1", "execution_status": "passed", "current_results": rows, "results": rows})
    write(task / "pipeline.json", {"ticket": "T-1", "sides": sides, "gates": {"A": {"authorization_source": "Gate A: approved."}}})
    write(work / "sizing.json", {"size": "M", "cap": 13, "computed_budget": 9, "verifiable_count": 1})
    use_project(root)
    return task


def side(reality: str) -> dict:
    return {"reality": reality, "deliverable": True, "source": "person"}


def marks_of(task: Path) -> dict:
    ledger = L.build(task)
    write(task / "work" / "ledger.json", ledger)
    return {r["ref"]: r.get("real_or_mock") for r in ledger["rows"] if r.get("kind") == "test"}, ledger


def unit_cases() -> None:
    """`real_or_mock` over data: the owner's words, the several-sides edge, and the unknowns (AR-28)."""
    bound = {"rows": [], "by_test": {}, "skipped": []}
    a = entry("t_a", {"ui": "real", "api": "substituted"})
    check_eq("a test whose side the run met substituted: on a mock, the side named",
             L.real_or_mock(a, run_row("t_a", {"ui": "real", "api": "substituted"}), bound), "on a mock: api — the side was substituted")
    b = entry("t_b", {"ui": "real", "api": "real"})
    check_eq("every side real in the declaration and the stamp: real code", L.real_or_mock(b, run_row("t_b", {"ui": "real", "api": "real"}), bound), "real code")
    check_eq("a test that declares a side real, run while the story said it substituted: on a mock",
             L.real_or_mock(b, run_row("t_b", {"ui": "real", "api": "substituted"}), bound), "on a mock: api — the side was substituted")
    many = entry("t_m", {"ui": "substituted", "api": "substituted", "db": "real"})
    words = L.real_or_mock(many, run_row("t_m", {"ui": "substituted", "api": "substituted", "db": "real"}), bound)
    check("a test with several mocked sides lists each", "on a mock: ui" in words and "on a mock: api" in words and "db" not in words, words)
    prov = {"rows": [{"id": "P-1", "status": "kept_by_decision", "settles_on": "api", "what": "the add-to-cart call stays a mock"}],
            "by_test": {"t_k": ["P-1"], "t_b": []}, "skipped": []}
    kept = entry("t_k", {"ui": "real", "api": "substituted"}, ["P-1"])
    words = L.real_or_mock(kept, run_row("t_k", {"ui": "real", "api": "real"}), prov)
    check_in("a kept_by_decision row: on a mock, the side, kept by the person's decision", "on a mock: api (the add-to-cart call stays a mock) — kept by the person's decision", words)
    check_in("a kept row with no `decided_at` (an older row): the date is said as not recorded, never guessed", "(date not recorded)", words)
    dated = {"rows": [dict(prov["rows"][0], decided_at="2026-11-11")], "by_test": prov["by_test"], "skipped": []}
    check_in("F7: a kept row with `decided_at` prints that date", "kept by the person's decision 2026-11-11",
             L.real_or_mock(kept, run_row("t_k", {"ui": "real", "api": "real"}), dated))
    check_not_in("F7: ... and no longer says the date is not recorded", "(date not recorded)",
                 L.real_or_mock(kept, run_row("t_k", {"ui": "real", "api": "real"}), dated))
    dangling = entry("t_d", {"ui": "real", "api": "real"}, ["P-9"])
    check_eq("F2: a test naming a P-n no readable row answers (dangling id, repeated id, a skipped row): not established, never real code",
             L.real_or_mock(dangling, run_row("t_d", {"ui": "real", "api": "real"}), {"rows": [], "by_test": {"t_d": ["P-9"]}, "skipped": []}),
             L.REAL_OR_MOCK_UNKNOWN)
    check_eq("F2: a test naming the kept mock of a manifest whose `provisional` list could not be read: not established",
             L.real_or_mock(dangling, run_row("t_d", {"ui": "real", "api": "real"}), {"rows": [], "by_test": {"t_d": ["P-1"]}, "skipped": ["`provisional` is str, not a list"]}),
             L.REAL_OR_MOCK_UNKNOWN)
    check_eq("F4: the report check's words are the producer's own (one list)", L.REAL_OR_MOCK_MARKS, (L.REAL_CODE, "on a mock:", L.REAL_OR_MOCK_UNKNOWN))
    manifest = {"provisional": [{"id": "P-1", "kind": "placeholder_locator", "assumed_from": "first_look:R-1", "status": "kept_by_decision"},
                                {"id": "P-2", "kind": "placeholder_locator", "assumed_from": "first_look:R-1", "status": "open"}]}
    check_eq("F8 (owner word W3): a kept_by_decision first-look row is NOT open (it stays kept); an open one still is",
             sorted(L.open_placeholder_rows(manifest)), ["P-2"])
    check_eq("control - the same stamp on a test that names no kept row: real code", L.real_or_mock(b, run_row("t_b", {"ui": "real", "api": "real"}), prov), "real code")
    check_eq("an unreadable stamp: not established, never real code",
             L.real_or_mock(b, {"instance_id": "t_b", "status": "passed", "sides_met": "oops"}, bound), L.REAL_OR_MOCK_UNKNOWN)
    check_eq("`sides_unknown` on the run: not established",
             L.real_or_mock(b, {"instance_id": "t_b", "status": "passed", "sides_unknown": "no record"}, bound), L.REAL_OR_MOCK_UNKNOWN)
    check_eq("a test whose `provisional` field could not be read: not established",
             L.real_or_mock(b, run_row("t_b", {"ui": "real", "api": "real"}), {"rows": [], "by_test": {}, "skipped": ["tests[] t_b: `provisional` is str, not a list"]}),
             L.REAL_OR_MOCK_UNKNOWN)
    check_eq("no run row, no result, nothing to mark", L.real_or_mock(b, None, bound), "")
    check_eq("a red result is marked the same way (the mark is about where it ran)",
             L.real_or_mock(a, run_row("t_a", {"ui": "real", "api": "substituted"}, "failed"), bound), "on a mock: api — the side was substituted")


def owners_example() -> None:
    """First run on a mocked API; then the API is real and one call is kept by decision."""
    sides = {"ui": side("real"), "api": side("substituted")}
    tests = [entry("t_a", {"ui": "real", "api": "substituted"}), entry("t_b", {"ui": "real", "api": "substituted"})]
    task = story(tests, [run_row(t["instance_id"], {"ui": "real", "api": "substituted"}) for t in tests], sides)
    try:
        marks, ledger = marks_of(task)
        check_eq("first run on a mocked API: every test says on a mock: api", sorted(marks.values()), ["on a mock: api — the side was substituted"] * 2)
        check_eq("a green stays green: the tests are still passed_green", sorted(r["state"] for r in ledger["rows"] if r.get("kind") == "test"), ["passed_green"] * 2)
        proven = RF.render(RF.build(task))["proven"]
        lines = [ln for ln in proven.splitlines() if ln.startswith("- ")]
        check("the report's test lines all say on a mock: api", bool(lines) and all("on a mock: api" in ln for ln in lines), proven)
    finally:
        cleanup(task.parents[2])
    sides = {"ui": side("real"), "api": side("real")}
    prov = [{"id": "P-1", "kind": "mock", "what": "the add call", "settles_on": "api", "status": "kept_by_decision"}]
    tests = [entry("t_a", {"ui": "real", "api": "real"}), entry("t_b", {"ui": "real", "api": "substituted"}, ["P-1"])]
    task = story(tests, [run_row(t["instance_id"], {"ui": "real", "api": "real"}) for t in tests], sides, prov)
    try:
        marks, ledger = marks_of(task)
        check_eq("relaunch with the side real: the other test says real code", marks["t_a"], "real code")
        check_in("... and the kept test says it was kept by the person's decision", "kept by the person's decision", marks["t_b"])
        check_eq("a green stays green with a kept mock", [r["state"] for r in ledger["rows"] if r.get("ref") == "t_b"], ["passed_green"])
        proven = RF.render(RF.build(task))["proven"]
        check_in("the report line of the kept test says it", "kept by the person's decision", proven)
        check_in("and the report line of the other says real code", "real code", proven)
        check_not_in("a report with every line marked and the ledger agreeing has nothing named by the check", "unmarked", proven)
        report = task / "test-report.md"
        write(report, "# T\n\n## Proven — 2 green tests\n\n" + proven.split("\n", 2)[2] + "\n")
        errors: list = []
        V.check_report_test_marks(report, errors)
        check_eq("the report check: marked lines pass", errors, [])
        write(report, "# T\n\n## Proven — 2 green tests\n\n- R-1 The cart adds a book (TC-001) — reviewed by the code critic · not probed\n")
        V.check_report_test_marks(report, errors)
        check("the report check names a test line with no real/mock mark", any("neither `real code` nor `on a mock:`" in e for e in errors), str(errors))
        check("... and its door is the regenerate that DOES add the mark on a Proven line", any("--write` renders the mark on that line" in e for e in errors), str(errors))
        # B3: a Left with you item that names a test is joined to its ledger row BY NAME; the door is the scribe's own edit (FR-2)
        write(report, f"# T\n\n## Left with you\n\n1. R-1 TC-001: `t_b` ({marks['t_b']}). To check: the cart. Needed: nothing. How: open it.\n")
        errors = []
        V.check_report_test_marks(report, errors)
        check_eq("B3: an item that names its test and copies the ledger's words passes", errors, [])
        write(report, "# T\n\n## Proven — 1 green test\n\n- R-1 The cart (TC-001) — x · real code\n\n## Left with you\n\n"
                      "1. R-1 TC-001: test `t_b`, green but unverified. To check: the cart. How: open it.\n")
        errors = []
        V.check_report_test_marks(report, errors)
        named = [e for e in errors if "item 1 names test `t_b` without its mark" in e]
        check("B3: an unmarked item on a mocked test is named WITH the test, though another line says `real code` (no whole-file pass)", len(named) == 1, str(errors))
        check("B3: its door is the scribe's own edit of the item, never a regenerate",
              bool(named) and "copy `real_or_mock` of `t_b` from work/ledger.json into that item" in named[0] and "--write" not in named[0], str(named))
        write(report, "# T\n\n## Left with you\n\n1. R-1 TC-001: test `t_a`, green. To check: the cart. How: open it.\n")
        errors = []
        V.check_report_test_marks(report, errors)
        check("B3: the same item on a real-code test is checked the same way (every test carries its mark)", any("test `t_a` without its mark" in e for e in errors), str(errors))
        write(report, "# T\n\n## Left with you\n\n1. R-1 TC-001: the `cart` page. To check: the cart. How: open it.\n")
        errors = []
        V.check_report_test_marks(report, errors)
        check_eq("B3 control: a backticked word that is no test of the ledger is not judged", errors, [])
        legacy = {k: v for k, v in ledger.items()}
        legacy["rows"] = [{k: v for k, v in r.items() if k != "real_or_mock"} for r in ledger["rows"]]
        write(task / "work" / "ledger.json", legacy)
        errors = []
        write(report, "# T\n\n## Proven — 2 green tests\n\n- R-1 The cart adds a book (TC-001) — reviewed by the code critic · not probed\n")
        V.check_report_test_marks(report, errors)
        check_eq("a ledger written before the field existed is not checked (legacy)", errors, [])
        write(task / "work" / "ledger.json", "{not json")
        V.check_report_test_marks(report, errors)
        check_eq("an unreadable ledger is not this check's (control: no exception)", errors, [])
    finally:
        cleanup(task.parents[2])


def every_test_line_carries_the_mark() -> None:
    """B2 (owner W3: for EVERY test it must always be visible): the rejected tests and the runs left failing say where their result
    came from, from the same ledger row as a Proven line (one helper, `report_facts._test_mark`)."""
    mock_words = "on a mock: api — the side was substituted"
    rows = [{"ref": "t_r", "kind": "test", "state": "review_rejected", "function": "t_r", "case": "TC-001", "remarks": [{"problem": "a remark", "expected": "x", "fix": "y"}], "real_or_mock": ""},
            {"ref": "t_x", "kind": "test", "state": "failed", "function": "t_x", "case": "TC-002", "repair_limit": {"stage": "S7"},
             "triage_words": "the run failed: 500", "real_or_mock": mock_words},
            {"ref": "t_y", "kind": "test", "state": "failed", "function": "t_y", "case": "TC-003", "repair_limit": {"stage": "S7"},
             "triage_words": "red", "real_or_mock": ""}]
    gaps = RF.review_gaps({"rows": rows})
    failing = "\n".join(RF.run_gap_lines(gaps))
    check_in("B2: a red test left failing on a mocked side says on a mock", f"`t_x` (TC-002) · {mock_words}", failing)
    check_in("B2: a red run on a marked ledger with no reading is not established, never silent", f"`t_y` (TC-003) · {L.REAL_OR_MOCK_UNKNOWN}", failing)
    rejected = "\n".join(RF.review_gap_lines(gaps))
    check_in("B2: a rejected test that never ran has no result to mark: its line is as it was", '- `t_r` (TC-001) — the critic: "a remark"', rejected)
    rows[0]["real_or_mock"] = "real code"
    check_in("B2: a rejected test that did run says where", '- `t_r` (TC-001) · real code — the critic: "a remark"', "\n".join(RF.review_gap_lines(RF.review_gaps({"rows": rows}))))
    legacy = [{k: v for k, v in r.items() if k != "real_or_mock"} for r in rows]
    check_not_in("B2 legacy control: a ledger with no mark on any row renders none", " · ", "\n".join(RF.run_gap_lines(RF.review_gaps({"rows": legacy}))))


def reference_runs_and_folders() -> None:
    """F6 (a reparse of a sample is not a second run), F3 (the samples folder is protected), F1 / B1 edge 2 (a reparse keeps the folder and the mark
    of the block it supersedes, never today's), and the one folder choice (`run_suite.block_folder`)."""
    import artifact_packet
    import artifact_producer
    import run_suite as RS
    import stand_identity as SI
    from unittest import mock
    root = temp_project("qa-reference-runs-")
    task = root / "qa-factory" / "artifacts" / "T-1"
    folder = task / "work" / SI.REFERENCE_RUNS_DIR
    mark = {"stand": "old", "side": "product", "story_code": False, "words": SI.REFERENCE_RUN_WORDS}
    try:
        write(folder / "a.json", {"attempt_id": "att-1", "reference_run": mark})
        write(folder / "b-reparse.json", {"attempt_id": "att-1", "supersedes_block_id": "att-1", "reference_run": mark})
        write(folder / "c.json", {"attempt_id": "att-2", "reference_run": mark})
        check_eq("F6: two files of one attempt (a reparse) and one of another are TWO runs", RF._reference_runs(task), [{"stand": "old", "side": "product", "runs": 2}])
        write(folder / "d.json", {"reference_run": mark})
        write(folder / "e.json", {"reference_run": mark})
        check_eq("F6 control: blocks with no attempt id are each counted", RF._reference_runs(task)[0]["runs"], 4)
        check_eq("block_folder: a marked block goes to the samples folder, a plain one and a non-object to run-blocks",
                 (RS.block_folder({"reference_run": mark}), RS.block_folder({}), RS.block_folder(None)), (SI.REFERENCE_RUNS_DIR, "run-blocks", "run-blocks"))
        check("F3: the samples folder is one of the protected receipt folders", SI.REFERENCE_RUNS_DIR in SI.PROTECTED_RECEIPT_FOLDERS)
        for name, call in (("artifact_packet.work_path", lambda: artifact_packet.work_path(task, f"work/{SI.REFERENCE_RUNS_DIR}/x.json")),
                           ("artifact_producer.publish", lambda: artifact_producer.publish(task, "case", {}, f"work/{SI.REFERENCE_RUNS_DIR}/x.json"))):
            try:
                call()
                refused = False
            except ValueError:
                refused = True
            check(f"F3: {name} refuses a role write into the samples folder", refused)
        # reparse: the mark and the folder are the superseded block's
        (task / "evidence").mkdir(parents=True)
        report = task / "evidence" / "report.xml"
        report.write_text('<testsuite><testcase classname="t" name="a"/></testsuite>', encoding="utf-8")
        import hashlib

        def old_block(extra, where):
            block = RS.build_run_block({"purpose": "initial", "selected_instance_ids": ["i-1"], "instance_contracts": {"i-1": {"report_test_id": "t::a"}}},
                                       {"results": [{"test_id": "t::a", "status": "passed"}], "execution_status": "passed"}, "a1")
            block.update(extra)
            block["evidence"] = [{"summary": "", "reporter": "junit-xml", "report_path": "evidence/report.xml",
                                  "report_sha256": hashlib.sha256(report.read_bytes()).hexdigest()}]
            block["attempt_started_at"], block["attempt_ended_at"] = "2026-11-10T10:00:00+00:00", "2026-11-10T10:01:00+00:00"
            path = task / "work" / where / "old.json"
            write(path, block)
            return path
        mapping = {"instance_contracts": {"i-1": {"report_test_id": "t::a"}}}
        plain_old = old_block({}, "run-blocks")                                      # written when the stand was no reference
        with mock.patch.object(RS, "reference_mark_of", lambda request: dict(mark)):    # TODAY's record names the stand as a reference
            plain = RS.reparse_run_block(task, plain_old, mapping)
            check("F1: a reparse of a plain block stays plain and stays in run-blocks, though today's record names the stand",
                  plain.parent.name == "run-blocks" and "reference_run" not in json.loads(plain.read_text(encoding="utf-8")), str(plain))
        (task / "work" / "run-blocks" / "old.json").unlink()
        sample_old = old_block({"reference_run": mark}, SI.REFERENCE_RUNS_DIR)
        with mock.patch.object(RS, "reference_mark_of", lambda request: {}):           # TODAY's record names no reference
            sample = RS.reparse_run_block(task, sample_old, mapping)
            body = json.loads(sample.read_text(encoding="utf-8"))
            check("edge 2: a reparse of a sample keeps its folder and its mark", sample.parent.name == SI.REFERENCE_RUNS_DIR and body.get("reference_run") == mark, str(sample))
            check_eq("edge 2: ... and keeps the attempt (a reparse is not a second sample)", body.get("attempt_id"), "a1")
    finally:
        cleanup(root)


def main() -> None:
    unit_cases()
    every_test_line_carries_the_mark()
    reference_runs_and_folders()
    owners_example()
    finish("test_real_or_mock")


if __name__ == "__main__":
    main()
