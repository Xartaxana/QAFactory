#!/usr/bin/env python3
"""HF4-12: the sensitivity probe finds a test whose report id carries a plugin-added parameter.

Run 12586, 28.10.2026: the S5 code critic probed a UI test; pytest-playwright reported it as `name[chromium]`, the probe asked for
`name`, matched by exact tail, read 0 rows and recorded `not_executed` -- the factory then asked the owner for her word.
The fix is `probe_by_code.matching_rows` (+ `_judge_param_rows`) used by `_judge_run`.

Keys: K1 the recorded junit (fixture) yields the `[chromium]` row; K2 the verdict end to end on that row; K3 0 / 1 / 2 param rows;
K4 the request WITH a param is an exact match; K5 no row at all names what the report held (<= 5); K6 class-method nodes;
K7 negative control: a survivor among several rows blocks `intended_failure`; K8 B1: {wrong_location, skipped} headline is
wrong_location and a stored intended_failure is NOT kept; K9 S1 rule `f[json]` ~ `f[chromium-json]`/`f[json-chromium]` and its edges
(empty param, two extra tokens, dashed param, order); K10 run_suite.build_run_block meets a param-less report id.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import FIXTURES, SCRIPTS, check, check_eq, check_in, cleanup, finish  # noqa: E402

sys.path.insert(0, str(SCRIPTS))

import probe_by_code as PBC  # noqa: E402

FIX = FIXTURES / "run-12586-probe-chromium" / "red_probe.junit.xml"
NODE = "testproject1_test_harness/tests/ui/integrations/test_edit_integration.py::test_edit_integration_change_project_confirmation_modal"
FUNC = "test_edit_integration_change_project_confirmation_modal"
FILE = "testproject1_test_harness/tests/ui/integrations/test_edit_integration.py"
MARKER = f"probe-{FUNC} invert: not_none()"
# N3b: the road's keys. The token the failure text must hold is `message_marker` (here the recorded message's own text, which the
# fixture's `AssertionError:` line carries), the plan's keys the judge reads (`language`, `candidates`, `target_source`, ...) are written
DETAIL = {"marker": MARKER, "message_marker": MARKER, "line": 220, "end_line": 220, "file": FILE, "language": "python", "candidates": [],
          "target_source": None, "target_outside_body": None, "fires_as": None, "pair": None, "pair_id": None}
REQUEST = {"command": {"argv": ["python", "-m", "pytest", "tests"]}, "instance_contracts": {}}     # a pytest launch, no file-bound contract
KEYS = ["edit_integration"]
TASK = "PLUGIN-PARAM-1"     # a walk's record always carries its task (e24925d8c: `_judge_rows` hands it to `_bind_report_rows`)

PASSED = '<testcase classname="tests.ui.integrations.test_edit_integration" name="{name}" time="1.0"/>'


def report(root: Path, testcases: str, name="report.junit.xml") -> Path:
    path = root / name
    path.write_text('<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest">' + testcases +
                    "</testsuite></testsuites>", encoding="utf-8")
    return path


def failed_case(name: str) -> str:
    text = FIX.read_text(encoding="utf-8")
    start = text.index("<testcase")
    end = text.index("</testcase>") + len("</testcase>")
    return text[start:end].replace(f'name="{FUNC}[chromium]"', f'name="{name}"')


def judge(root: Path, report_path: Path, node: str) -> dict:
    record = {"task": TASK, "notes": [], "test_node": node, "expected_location": f"{FILE}:220", "expected_reason": MARKER}
    summary = {"report_evidence": {"path": report_path.name}, "reporter": "junit-xml", "label": "x", "exit_code": 1}
    spec = PBC.parse_node(node)          # N3b: a Python spec carries `reader`, `language` and `entry`
    PBC._judge_run(root, root, record, summary, spec, DETAIL, REQUEST, root / "none", KEYS)
    return record


def main() -> None:
    root = Path(harness.tempfile.mkdtemp(prefix="plugin-param-"))
    try:
        # K1 the recorded junit, fed through the probe's report reader with the recorded unparametrized node.
        rows = PBC.report_rows(FIX, "junit-xml")
        found = PBC.matching_rows(rows, NODE)
        check_eq("K1 the recorded report holds one row", len(rows), 1)
        check_eq("K1 SEAM: the unparametrized recorded node yields the [chromium] row (not 0 rows)",
                 [r["test_id"] for r in found], [f"tests.ui.integrations.test_edit_integration::{FUNC}[chromium]"])

        # K2 end to end through _judge_run: killed, and the record names the matched id.
        record = {"task": TASK, "notes": [], "test_node": NODE, "expected_location": f"{FILE}:220", "expected_reason": MARKER}
        summary = {"report_evidence": {"path": FIX.name}, "reporter": "junit-xml", "label": "x", "exit_code": 1}
        PBC._judge_run(FIX.parent, FIX.parent, record, summary, PBC.parse_node(NODE), DETAIL, REQUEST, root / "n", KEYS)
        check_eq("K2 the verdict is judged on the [chromium] row", record.get("verdict"), "intended_failure")
        check_eq("K2 and proved by the marker, the only proof the code writes", record.get("proved_by"), "marker")
        check_eq("K2 the record names the matched report id", record.get("matched_report_id"),
                 f"tests.ui.integrations.test_edit_integration::{FUNC}[chromium]")

        # K3 zero / one / two parametrised rows.
        two = report(root, failed_case(f"{FUNC}[chromium]") + failed_case(f"{FUNC}[firefox]"), "two.junit.xml")
        record = judge(root, two, NODE)
        check_eq("K3 two rows, both killed: intended_failure", record.get("verdict"), "intended_failure")
        check_eq("K3 two rows: the record lists both ids",
                 [r["test_id"].rsplit("::", 1)[-1] for r in record.get("param_rows", [])],
                 [f"{FUNC}[chromium]", f"{FUNC}[firefox]"])
        survive = report(root, failed_case(f"{FUNC}[chromium]") + PASSED.format(name=f"{FUNC}[firefox]"), "survive.junit.xml")
        record = judge(root, survive, NODE)
        check_eq("K7 one of two rows survives: no_failure, never intended_failure", record.get("verdict"), "no_failure")
        check_in("K7 the survivor is named in the notes", f"{FUNC}[firefox]", " ".join(record["notes"]))
        check_eq("K7 the record lists each row's verdict",
                 [r["verdict"] for r in record.get("param_rows", [])], ["intended_failure", "no_failure"])

        # K8 B1: a judged survivor (wrong_location) next to an unrun row must be the headline and replace a stored kill.
        skipped = '<testcase classname="tests.ui.integrations.test_edit_integration" name="{n}"><skipped message="s"/></testcase>'
        # N3b: the judged survivor is a PASS (`no_failure`); a failure without the token is judgment (`incomplete`), no longer `wrong_location`
        mixed = report(root, PASSED.format(name=f"{FUNC}[chromium]") + skipped.format(n=f"{FUNC}[firefox]"), "mixed.junit.xml")
        record = judge(root, mixed, NODE)
        check_eq("K8 B1 rows {judged survivor, skipped}: headline is the judged verdict, not not_executed",
                 [r["verdict"] for r in record.get("param_rows", [])].count("not_executed") == 1 and record.get("verdict") == "no_failure", True)
        survivor = record
        other = report(root, failed_case(f"{FUNC}[chromium]").replace(MARKER, "some other message"), "other.junit.xml")
        record = judge(root, other, NODE)
        check_eq("K8 N3b a failure without the token is judgment, never proved", (record.get("verdict"), record.get("cause"), "proved_by" in record),
                 ("incomplete", "judgment", False))
        record = survivor
        stored = root / "stored.json"
        stored.write_text('{"verdict": "intended_failure"}', encoding="utf-8")
        check_eq("K8 B1 a judged survivor replaces a stored intended_failure (not kept)", PBC.keep_standing_record(stored, record), False)
        check_eq("K8 B1 the order puts every judged survivor above not_executed",
                 PBC._SURVIVOR_ORDER.index("wrong_location") < PBC._SURVIVOR_ORDER.index("not_executed"), True)

        # K9 S1: the plugin token merged into the author's bracket.
        rs = lambda *ids: [{"test_id": f"m::{i}"} for i in ids]
        def got(node, *ids):
            return [r["test_id"].split("::")[-1] for r in PBC.matching_rows(rs(*ids), "a.py::" + node)]
        check_eq("K9 f[json] ~ f[chromium-json] and f[json-chromium]", got("f[json]", "f[chromium-json]", "f[json-chromium]", "f[chromium-yaml]"),
                 ["f[chromium-json]", "f[json-chromium]"])
        check_eq("K9 exact wins over the plugin spelling", got("f[json]", "f[json]", "f[chromium-json]"), ["f[json]"])
        check_eq("K9 edge: f[] is no param (matches f[p])", got("f[]", "f[chromium]"), ["f[chromium]"])
        check_eq("K9 edge: two extra tokens do not match", got("f[json]", "f[a-b-json]", "f[json-a-b]", "f[a-json-b]"), [])
        check_eq("K9 edge: dashed param compared as a sequence", got("f[a-b]", "f[x-a-b]", "f[a-b-y]", "f[a-x-b]", "f[b-a]"), ["f[x-a-b]", "f[a-b-y]"])
        check_eq("K9 f[webkit] is not f[firefox]", got("f[webkit]", "f[firefox]"), [])
        check_eq("K9 a different function is not matched", got("f[json]", "g[chromium-json]", "f2[chromium-json]"), [])

        # K10 run_suite.build_run_block: a predicted param-less report id meets the reported `[chromium]` row.
        import run_suite as RUN
        def block(report_id, ids):
            req = {"selected_instance_ids": ["i1"], "instance_contracts": {"i1": {"report_test_id": report_id}}}
            res = RUN.build_run_block(req, {"results": [{"test_id": i, "status": "passed"} for i in ids]}, "a1")
            return res["results"][0]
        row = block("tests.ui.test_x::f", ["tests.ui.test_x::f[chromium]"])
        check_eq("K10 run_suite: the [chromium] row is bound", (row["report_matched"], row["status"]), (True, "passed"))
        row = block("tests.ui.test_x::f", ["tests.other.test_x::f[chromium]"])
        check_eq("K10 run_suite: another module's f[..] is no match", row["report_matched"], False)
        row = block("tests.ui.test_x::f", ["tests.ui.test_x::f[chromium]", "tests.ui.test_x::f[firefox]"])
        check_eq("K10 run_suite: several rows stay ambiguous", (row["report_matched"], row["reason"]),
                 (False, "report identity is ambiguous; multiple rows matched"))

        # K4 a request WITH a param is an exact match.
        with_param = NODE + "[firefox]"
        record = judge(root, two, with_param)
        check_eq("K4 with a param: the firefox row only", PBC.matching_rows(PBC.report_rows(two, "junit-xml"), with_param)[0]["test_id"].rsplit("::", 1)[-1],
                 f"{FUNC}[firefox]")
        check_eq("K4 with a param: no param_rows block (one exact row)", "param_rows" in record, False)
        record = judge(root, two, NODE + "[webkit]")
        check_eq("K4 with a param nobody ran: not matched to a sibling", record.get("verdict"), None)

        # K5 no row: the reason names the ids the report held, at most 5.
        other = report(root, "".join(PASSED.format(name=f"test_other_{i}") for i in range(7)), "other.junit.xml")
        record = judge(root, other, NODE)
        text = " ".join(record["notes"])
        check_eq("K5 no row: no verdict recorded (stays not_executed upstream)", record.get("verdict"), None)
        check_in("K5 the note names a held id", "test_other_0", text)
        check("K5 at most 5 ids named", "test_other_4" in text and "test_other_5" not in text and "+2 more" in text, text)

        # K6 class-method nodes and a different, unrelated name with the same prefix.
        cls_rows = PBC.report_rows(report(root, PASSED.format(name="test_x[chromium]") +
                                          PASSED.format(name="test_x_other[chromium]"), "cls.junit.xml"), "junit-xml")
        check_eq("K6 Class::func without a param finds func[p] only (not func_other[p])",
                 [r["test_id"].rsplit("::", 1)[-1] for r in PBC.matching_rows(cls_rows, "a/test_m.py::TestC::test_x")], ["test_x[chromium]"])
        check_eq("K6 an exact unparametrized row wins over param rows",
                 len(PBC.matching_rows(PBC.report_rows(report(root, PASSED.format(name="test_y") + PASSED.format(name="test_y[a]"), "ex.junit.xml"),
                                                        "junit-xml"), "t.py::test_y")), 1)

        # S the sibling: red_sandbox's `--probe` one-call row match (`bind_row` -> `_match_row`) uses the same matcher.
        import red_sandbox as RS
        check("S0 one matcher: probe_by_code.matching_rows IS red_sandbox.matching_rows", PBC.matching_rows is RS.matching_rows)
        target = {"instance_id": "i", "node_id": NODE}
        row, note = RS.bind_row(target, {}, rows, "junit-xml", pytest_command=True)
        check_eq("S1 SEAM: red_sandbox binds the recorded [chromium] row to the unparametrized node",
                 (row or {}).get("test_id"), f"tests.ui.integrations.test_edit_integration::{FUNC}[chromium]")
        row, note = RS.bind_row({"instance_id": "i", "node_id": NODE + "[chromium]"}, {}, rows, "junit-xml", pytest_command=True)
        check_eq("S2 with a param: exact", (row or {}).get("test_id"), rows[0]["test_id"])
        row, note = RS.bind_row({"instance_id": "i", "node_id": NODE + "[webkit]"}, {}, rows, "junit-xml", pytest_command=True)
        check("S3 with a param nobody ran: no row, the held id named", row is None and "[chromium]" in note, note)
        row, note = RS.bind_row(target, {}, PBC.report_rows(two, "junit-xml"), "junit-xml", pytest_command=True)
        check("S4 several param rows: never picked, ambiguous", row is None and "2 report rows" in note, note)
        row, note = RS.bind_row(target, {}, PBC.report_rows(other, "junit-xml"), "junit-xml", pytest_command=True)
        check("S5 no row: names at most 5 held ids", row is None and "test_other_4" in note and "test_other_5" not in note
              and "+2 more" in note, note)
    finally:
        cleanup(root)
    finish("probe plugin param")


if __name__ == "__main__":
    main()
