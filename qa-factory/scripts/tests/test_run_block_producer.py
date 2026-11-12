"""Typed runner produces immutable per-attempt blocks consumed directly by finalizer."""
import json
import hashlib
import shutil
import sys
import tempfile
from pathlib import Path

from harness import PLUGIN_ROOT, check, check_eq, check_in, finish, temp_dir

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
from finalize_task import reduce  # noqa: E402
from run_suite import (build_run_block, parse_junitxml, process_started_at,  # noqa: E402
                       reparse_run_block, same_process)
from execution_request import JobStore, RequestError  # noqa: E402

# Outside the package: a local-directory marketplace copies whatever lies in it.
ROOT = Path(tempfile.mkdtemp(prefix="qa-run-block-producer-"))


def req(purpose: str, ids: list[str], fingerprint: str) -> dict:
    return {"task": "RB-1", "dispatch_id": "d-1", "profile_id": "api", "purpose": purpose,
            "selected_instance_ids": ids, "input_fingerprint": fingerprint,
            "fingerprint_components": {"source_sha": "a" * 40, "test_content_sha": fingerprint,
                                       "config_sha": "c" * 64},
            "runtime_provenance": {"result": "matched"},
            "instance_contracts": {item: {"report_test_id": f"suite::{item}",
                                           "parameters": {"db": item}}
                                   for item in ids}}


SHAS = {"instance_content_sha": "c" * 20, "instance_content_scope": "module",
        "instance_code_sha": "d" * 20}
OTHER = {"instance_content_sha": "e" * 20, "instance_content_scope": "function",
         "instance_code_sha": "f" * 20}
KEYS = ("instance_content_sha", "instance_content_scope", "instance_code_sha")


def prior_block(task_root: Path, sha_fields: dict, attempt: str = "attempt-7") -> Path:
    """A written run block of one attempt over a real junit report, its rows carrying `sha_fields`."""
    (task_root / "evidence").mkdir(parents=True)
    report = task_root / "evidence" / "report.xml"
    report.write_text('<testsuite tests="2" failures="1" errors="0" skipped="0">'
                      '<testcase classname="suite" name="i-1"/>'
                      '<testcase classname="suite" name="i-2"><failure message="red">t</failure>'
                      '</testcase></testsuite>', encoding="utf-8")
    request = req("initial", ["i-1", "i-2"], "7" * 64)
    for contract in request["instance_contracts"].values():
        contract.update(sha_fields)
    summary = {"execution_status": "failed", "reporter": "junit-xml",
               "started_at": "2026-09-30T04:48:47+00:00", "ended_at": "2026-09-30T04:49:00+00:00",
               "summary_path": "evidence/s.json", "report_evidence": {
                   "path": "evidence/report.xml", "sha256": hashlib.sha256(report.read_bytes()).hexdigest()},
               "results": [{"test_id": "suite::i-1", "status": "passed", "reason": ""},
                           {"test_id": "suite::i-2", "status": "failed", "reason": "red"}]}
    block = build_run_block(request, summary, attempt)
    directory = task_root / "work" / "run-blocks"
    directory.mkdir(parents=True)
    path = directory / f"20260930T044847000000Z-{attempt}.json"
    path.write_text(json.dumps(block), encoding="utf-8")
    return path


def reparse_rows(task_root: Path, prior: Path, sha_fields: dict, **extra) -> list[dict]:
    """Reparse `prior` with a mapping carrying `sha_fields` for both instances; the new rows."""
    mapping = {"instance_contracts": {item: {"report_test_id": f"suite::{item}", **sha_fields, **extra}
                                      for item in ("i-1", "i-2")}}
    target = reparse_run_block(task_root, prior, mapping)
    return json.loads(target.read_text(encoding="utf-8"))["results"]


def sha_checks() -> None:
    # build_run_block: the code sha rides beside the content sha and its scope.
    request = req("initial", ["i-1"], "5" * 64)
    request["instance_contracts"]["i-1"].update(SHAS)
    row = build_run_block(request, {"execution_status": "passed", "results": [
        {"test_id": "suite::i-1", "status": "passed", "reason": ""}]}, "attempt-5")["results"][0]
    for key in KEYS:
        check_eq(f"build_run_block copies {key} from the contract", row.get(key), SHAS[key])
    # Edge 1: a contract without a code sha (an old request) and one with an empty value.
    for label, patch in (("absent", {}), ("empty", {"instance_code_sha": ""})):
        request = req("initial", ["i-1"], "5" * 64)
        request["instance_contracts"]["i-1"].update({k: v for k, v in SHAS.items()
                                                     if k != "instance_code_sha"}, **patch)
        row = build_run_block(request, {"execution_status": "passed", "results": [
            {"test_id": "suite::i-1", "status": "passed", "reason": ""}]}, "attempt-5")["results"][0]
        check(f"edge 1: a {label} contract code sha gives a row with no such key",
              "instance_code_sha" not in row)
        check_eq(f"edge 1: the content sha is still copied ({label})",
                 row.get("instance_content_sha"), SHAS["instance_content_sha"])
    bare = build_run_block(req("initial", ["i-1"], "5" * 64), {"execution_status": "passed", "results": []},
                           "attempt-5")["results"][0]
    check("edge 1: a contract with none of the three gives a row with none of them",
          not any(key in bare for key in KEYS))

    # reparse_run_block. Each scenario has its own task root.
    scenarios = {}
    for name in ("carry", "prior_wins", "old_block", "old_block_mapping", "partial", "params"):
        scenarios[name] = temp_dir(f"qa-reparse-{name}-")
    try:
        root = scenarios["carry"]
        rows = reparse_rows(root, prior_block(root, SHAS), {})
        check_eq("edge 3: reparse carries the three shas from the prior row when the mapping lacks them",
                 [tuple(r.get(k) for k in KEYS) for r in rows], [tuple(SHAS[k] for k in KEYS)] * 2)
        check_eq("reparse keeps the red row's status from the raw report",
                 [r["status"] for r in rows], ["passed", "failed"])

        root = scenarios["prior_wins"]
        rows = reparse_rows(root, prior_block(root, SHAS), OTHER)
        check_eq("edge 2: the prior row's shas win over the mapping's",
                 [tuple(r.get(k) for k in KEYS) for r in rows], [tuple(SHAS[k] for k in KEYS)] * 2)

        root = scenarios["old_block"]
        rows = reparse_rows(root, prior_block(root, {}), {})
        check("edge 4: a prior row without shas gives reparse rows without any",
              not any(key in row for row in rows for key in KEYS))

        root = scenarios["old_block_mapping"]
        rows = reparse_rows(root, prior_block(root, {}), OTHER)
        check("edge 4: a sha the mapping brings never fills a prior row that had none",
              not any(key in row for row in rows for key in KEYS))

        root = scenarios["partial"]
        only_content = {k: v for k, v in SHAS.items() if k != "instance_code_sha"}
        rows = reparse_rows(root, prior_block(root, only_content), OTHER)
        check_eq("a prior row with the content sha only carries exactly that",
                 [tuple(r.get(k) for k in KEYS[:2]) for r in rows], [(SHAS[KEYS[0]], SHAS[KEYS[1]])] * 2)
        check("a prior row with no code sha gives reparse rows with no code sha, nothing invented",
              not any("instance_code_sha" in row for row in rows))

        # Edge 5: the reparse refuses a mapping that is not exactly the prior instances, so an
        # instance with no prior row never reaches the row builder; the refusal is what stands.
        root = scenarios["params"]
        prior = prior_block(root, SHAS)
        mapping = {"instance_contracts": {"i-1": {"report_test_id": "suite::i-1", **OTHER},
                                          "i-9": {"report_test_id": "suite::i-9", **OTHER}}}
        try:
            reparse_run_block(root, prior, mapping)
            refused = ""
        except RequestError as exc:
            refused = str(exc)
        check_in("edge 5: an instance with no prior row is refused, so it never gets shas",
                 "exactly the prior selected instances", refused)
        blocks = sorted((root / "work" / "run-blocks").glob("*reparse*"))
        check_eq("edge 5: the refusal writes no reparse block", blocks, [])

        # Edge 6: parameters / links / obligations still come from the prior row unless the
        # mapping has its own.
        rows = reparse_rows(root, prior, {}, parameters={"db": "mine"})
        check_eq("edge 6: the mapping's own parameters stand", rows[0]["parameters"], {"db": "mine"})
        check_eq("edge 6: missing case_version_links come from the prior row (empty list here)",
                 rows[0]["case_version_links"], [])
        fresh = temp_dir("qa-reparse-fresh-")
        scenarios["fresh"] = fresh
        rows = reparse_rows(fresh, prior_block(fresh, SHAS), {})
        check_eq("edge 6: missing parameters come from the prior row", rows[0]["parameters"], {"db": "i-1"})
    finally:
        for path in scenarios.values():
            shutil.rmtree(path, ignore_errors=True)


def m3_cap_at_and_beyond_for_a_selected_instance() -> None:
    """HF4-2 edge m3 (t-1530 F-2 (a), AR-28, AR-23, AR-13): the 500-row `passed` cap of the summary against a SELECTED instance.
    PINS today's behaviour, changes none: a selected instance whose `passed` row is past the cap reads `not_run` /
    "report row missing" in the block - a false "not executed", never a pass - and every status reader (`case_stamp.instance_hold`,
    the one join) says `not_run`. The cost (named, not fixed): when ALL selected instances are past the cap, every row of the
    block has the shape of an unmatched reporter id. Empty run (0 rows): the same `not_run` / "report row missing".
    Kills: `RESULT_ROWS_CAP` 500 -> 499 (the AT row goes missing); `_cap_passed_rows` keeping rows past the cap (the BEYOND
    row becomes `passed`); the missing-row reason text changed (it is read by `run_history.MISSING_ROW` and `s5_precheck`)."""
    import case_stamp as S
    work = temp_dir("qa-m3-cap-")
    try:
        def block_of(total: int, picks: list[int]):
            """(summary, block rows by instance, the instance_hold of each) for a junit of `total` passed rows, selecting pass-<pick>."""
            xml = work / f"cap-{total}.xml"
            xml.write_text(f'<testsuite tests="{total}" failures="0" errors="0" skipped="0">'
                           + "".join(f'<testcase classname="suite" name="pass-{i}"/>' for i in range(total))
                           + '</testsuite>', encoding="utf-8")
            summary = parse_junitxml(xml)
            ids = [f"i-{pick}" for pick in picks]
            request = req("initial", ids, "9" * 64)
            for pick, item in zip(picks, ids):
                request["instance_contracts"][item]["report_test_id"] = f"suite::pass-{pick}"
            rows = build_run_block(request, summary, "attempt-m3")["results"]
            index = S.run_rows_index({row["instance_id"]: row for row in rows})
            holds = {item: S.instance_hold({"instance_id": item, "status": "green", "critic_verdict": "approved"}, index)
                     for item in ids}
            return summary, {row["instance_id"]: row for row in rows}, holds

        # AT: exactly 500 passed rows - the 500th is listed, matched, green for the reader
        summary, rows, holds = block_of(500, [499])
        check_eq("m3 AT 500: the summary lists all 500 rows", len(summary["results"]), 500)
        check("m3 AT 500: no results_note", not summary.get("results_note"), str(summary.get("results_note")))
        check_eq("m3 AT 500: the selected 500th row is `passed`", rows["i-499"]["status"], "passed")
        check_eq("m3 AT 500: ... and matched", rows["i-499"]["report_matched"], True)
        check_eq("m3 AT 500: instance_hold of it is empty (green + approved)", holds, {"i-499": ""})

        # control inside the cap, report beyond it: the selected row among the first 500 stays `passed`
        summary, rows, holds = block_of(501, [499])
        check_eq("m3 control: 501 rows, the selected one is the 500th: `passed`", rows["i-499"]["status"], "passed")
        check_eq("m3 control: ... instance_hold empty", holds, {"i-499": ""})

        # BEYOND: 501 passed rows, the selected instance is the 501st
        summary, rows, holds = block_of(501, [500])
        check_eq("m3 BEYOND 501: the summary lists 500 rows", len(summary["results"]), 500)
        check_eq("m3 BEYOND 501: the cut is said in results_note",
                 summary.get("results_note"), "1 passed rows beyond the 500-row cap are counted in totals, not listed")
        check("m3 BEYOND 501: the 501st row is not in the summary",
              all(row["test_id"] != "suite::pass-500" for row in summary["results"]))
        check_eq("m3 BEYOND 501: the block row is `not_run` (never `passed`)", rows["i-500"]["status"], "not_run")
        check_eq("m3 BEYOND 501: ... reason is the unmatched-id words", rows["i-500"]["reason"], "report row missing")
        check_eq("m3 BEYOND 501: ... not matched", rows["i-500"]["report_matched"], False)
        check_eq("m3 BEYOND 501: instance_hold is `not_run`, never a pass", holds, {"i-500": S.NOT_RUN})

        # ALL selected past the cap (502 rows, the 501st and the 502nd selected): every block row is the unmatched-id shape
        summary, rows, holds = block_of(502, [500, 501])
        check_eq("m3 all past the cap: every row `not_run`", sorted(row["status"] for row in rows.values()), ["not_run"] * 2)
        check_eq("m3 all past the cap: every reason is `report row missing` (the price named in t-1530 F-2 (a))",
                 sorted(row["reason"] for row in rows.values()), ["report row missing"] * 2)
        check_eq("m3 all past the cap: every instance_hold is `not_run`", holds, {"i-500": S.NOT_RUN, "i-501": S.NOT_RUN})

        # empty run: 0 rows - the pinned outcome is the same `not_run` / `report row missing`, no note
        summary, rows, holds = block_of(0, [0])
        check_eq("m3 empty run: no rows listed", summary.get("results"), [])
        check("m3 empty run: no results_note", not summary.get("results_note"), str(summary.get("results_note")))
        check_eq("m3 empty run: the selected row is `not_run` / `report row missing`",
                 (rows["i-0"]["status"], rows["i-0"]["reason"], rows["i-0"]["report_matched"]), ("not_run", "report row missing", False))
        check_eq("m3 empty run: instance_hold is `not_run`", holds, {"i-0": S.NOT_RUN})
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> None:
    if ROOT.exists():
        shutil.rmtree(ROOT, ignore_errors=True)
    work = ROOT / "work" / "run-blocks"
    work.mkdir(parents=True)
    try:
        evidence = ROOT / "evidence" / "report.xml"
        evidence.parent.mkdir(parents=True)
        evidence.write_text("immutable reporter bytes", encoding="utf-8")
        report_ref = {"path": "evidence/report.xml", "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}
        initial_summary = {"execution_status": "failed", "reporter": "pytest",
            "started_at": "2026-09-17T10:00:00+00:00", "ended_at": "2026-09-17T10:01:00+00:00",
            "summary_path": "evidence/initial.json", "report_evidence": report_ref, "results": [
                {"test_id": "suite::i-1", "status": "failed", "reason": "old bug"},
                {"test_id": "suite::i-2", "status": "passed", "reason": ""}]}
        initial = build_run_block(req("initial", ["i-1", "i-2"], "1" * 64), initial_summary, "attempt-1")
        check_eq("block keeps stable attempt identity", initial["attempt_id"], "attempt-1")
        check_eq("block keeps per-instance parameters", initial["results"][0]["parameters"], {"db": "i-1"})
        check_eq("block keeps source fingerprint", initial["results"][0]["source_fingerprint"]["source_sha"], "a" * 40)
        (work / "20260917T100000000000Z-attempt-1.json").write_text(json.dumps(initial), encoding="utf-8")

        repair_summary = {"execution_status": "passed", "reporter": "pytest",
                          "started_at": "2026-09-17T10:02:00+00:00", "ended_at": "2026-09-17T10:03:00+00:00",
                          "summary_path": "evidence/repair.json", "report_evidence": report_ref,
                          "results": [{"test_id": "suite::i-1", "status": "passed", "reason": ""}]}
        repair = build_run_block(req("repair_verify", ["i-1"], "2" * 64), repair_summary, "attempt-2")
        (work / "20260917T100001000000Z-attempt-2.json").write_text(json.dumps(repair), encoding="utf-8")
        report, _ = reduce(ROOT)
        check_eq("reducer preserves initial failure and repair pass", len(report["results"]), 3)
        check_eq("repair makes current instance green without collapsing history",
                 report["current_totals"].get("passed"), 2)
        check_eq("historical failure remains machine readable", report["totals"].get("failed"), 1)

        missing = build_run_block(req("initial", ["i-3"], "3" * 64),
                                  {"execution_status": "passed", "results": []}, "attempt-3")
        check_eq("missing exact reporter result is unverified", missing["results"][0]["status"], "not_run")
        check_eq("missing result is not claimed matched", missing["results"][0]["report_matched"], False)
        timed_out_probe = build_run_block(
            req("repair_verify", ["i-2"], "4" * 64),
            {"execution_status": "inconclusive", "runtime_change_error":
             "post-run runtime probe unavailable: timeout", "results": [
                 {"test_id": "suite::i-2", "status": "passed", "reason": ""}]}, "attempt-4")
        check_eq("post-run probe timeout cannot preserve a reporter green",
                 timed_out_probe["results"][0]["status"], "not_run")
        check_eq("post-run probe timeout row is immutable unverified evidence",
                 timed_out_probe["results"][0]["report_matched"], False)
        red = build_run_block(req("red_probe", ["i-1"], "4" * 64), repair_summary, "red-1")
        check_eq("red probe is excluded from product run blocks", red, None)

        xml = ROOT / "many.xml"
        cases = [f'<testcase classname="suite" name="pass-{i}"/>' for i in range(501)]
        cases.append('<testcase classname="suite" name="failure-501"><failure message="late failure">trace</failure></testcase>')
        xml.write_text('<testsuite tests="502" failures="1" errors="0" skipped="0">'
                       + "".join(cases) + '</testsuite>', encoding="utf-8")
        parsed = parse_junitxml(xml)
        check("failure after the 500th passed display row is preserved",
              any(row["test_id"] == "suite::failure-501" for row in parsed["results"]))
        check_eq("all failures remain in machine failure list", len(parsed["failed"]), 1)
        own_start = process_started_at(__import__('os').getpid())
        check("process birth identity is a UTC timestamp",
              bool(own_start and own_start.endswith("+00:00")))
        check("missing process birth evidence never proves ownership",
              (same_process(__import__('os').getpid(), own_start) if own_start else
               not same_process(__import__('os').getpid(), "")))
        check_eq("recycled/wrong PID start identity is not considered owned",
                 same_process(__import__('os').getpid(), "1900-01-01T00:00:00Z"), False)
        jobs = JobStore(ROOT / "jobs")
        running = {"job_id": "j1", "idempotency_key": "running", "request_digest": "d",
                   "status": "running", "runner_pid": __import__('os').getpid(),
                   "runner_started_at": own_start, "request": {"task": "RB-1"}}
        jobs.write(running)
        check_eq("recovery recognizes exact owned running process",
                 jobs.recover("running", lambda pid, started: pid == running["runner_pid"] and
                              started == running["runner_started_at"])["action"], "running")
        stopped = {**running, "job_id": "j2", "idempotency_key": "stopped",
                   "runner_started_at": "1900-01-01T00:00:00Z"}
        jobs.write(stopped)
        recovered = jobs.recover("stopped", same_process)
        check_eq("lost process becomes incomplete without relaunch", recovered["action"], "incomplete")
        check_eq("lost process durable status is incomplete", jobs.read("stopped")["status"], "incomplete")
        sha_checks()
        m3_cap_at_and_beyond_for_a_selected_instance()
    finally:
        shutil.rmtree(ROOT, ignore_errors=True)
    finish("test_run_block_producer")


if __name__ == "__main__":
    main()
