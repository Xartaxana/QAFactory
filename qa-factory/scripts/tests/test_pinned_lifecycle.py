#!/usr/bin/env python3
"""Pinned Approved case + exact proof projects automated without mutating case bytes."""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import GOOD, check, check_eq, cleanup, install_artifacts, temp_project, use_project  # noqa: E402

root = temp_project("qa-pinned-lifecycle-")
use_project(root)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import case_versions as V  # noqa: E402
import check_coverage as CC  # noqa: E402
import check_delivery as D  # noqa: E402
import contract as C  # noqa: E402
import factory_dashboard as FD  # noqa: E402


def main():
    try:
        task = install_artifacts(root, GOOD, "QA-1")
        source = task / "work" / "test-cases" / "checkout" / "TC-001.md"
        # Immutable design approval precedes automation; proof lives in the manifest.
        source.write_text(source.read_text(encoding="utf-8").replace("status: Automated", "status: Approved")
                          .replace("automated_by: qa-code-critic\n", "")
                          .replace("red_probe: removed the cap check, the test failed on the expected status\n", ""),
                          encoding="utf-8")
        store = root / "qa-factory" / "state" / "case-store"
        record = V.create_version(store, source)
        V.pin(task, record)
        manual_record = V.create_version(store, task / "work" / "test-cases" / "checkout" / "TC-002.md")
        V.pin(task, manual_record)
        pinned = task / next(link["path"] for link in C.story_case_links(task)
                             if link["case_id"] == "TC-001")
        before = hashlib.sha256(pinned.read_bytes()).hexdigest()

        manifest_path = task / "work" / "automation-manifest.json"
        manifest = C.load_json(manifest_path)
        test = manifest["tests"][0]
        proof = {"instance_id": "repo:p:coupon", "case_version": record["version"],
                 "test_content_hash": "a" * 64, "source_revision": "source-1", "build_id": "build-1",
                 "mutation": "force assertion mismatch", "expected_assertion_failure": "coupon mismatch",
                 "actual_failure": "coupon mismatch", "assertion_location": "test.py:10",
                 "restoration_evidence": "repair receipt", "immutable": True, "receipt_hash": "b" * 64}
        test.update({"instance_id": "repo:p:coupon", "status": "green",
                     "critic_verdict": "approved", "sensitivity_proof": proof,
                     "case_version_links": [{"case_id": "TC-001", "version": record["version"],
                                              "content_hash": record["content_hash"]}]})
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        check_eq("pinned Approved case with exact proof satisfies lifecycle", D.lifecycle_reasons(task), [])
        check_eq("exact manifest CaseVersion link is current", D.case_version_reasons(task), [])
        check("delivery accepts the versioned lifecycle proof", D.assess(task)["delivery_ready"],
              "\n".join(D.assess(task)["reasons"]))

        # Coverage must use the task manifest proof, even though immutable frontmatter stays Approved.
        areas = CC.collect_cases(root)
        check_eq("coverage projects pinned proof as automated", areas["checkout"]["automated"], 1)
        tasks = FD.parse_taskruns(root)
        row = next(item for item in tasks if item["task"] == "QA-1")
        check("dashboard reads the same pin, manifest and green report",
              "TC-001" in row["planned_cases"] and row["report"].get("execution_status") == "passed"
              and any(C.manifest_test_links(item) == ["TC-001"] for item in row["manifest_entries"])
              and not row["case_lifecycle_issues"])
        after = hashlib.sha256(pinned.read_bytes()).hexdigest()
        check_eq("delivery, coverage and dashboard never mutate immutable case bytes", after, before)

        # t-415 (B-308 b): the manifest's `green` is what the automator wrote before the run; a run result that went
        # red for the same instance outranks it, so the map does not count the case automated. Only failed/error do:
        # no result, a green one, another instance's red, an unreadable report all read as before.
        report_path = task / "work" / "run-report.json"
        report_was = report_path.read_bytes() if report_path.is_file() else None
        try:
            def automated_with(report) -> int:
                if report is None:
                    report_path.unlink(missing_ok=True)
                else:
                    report_path.write_text(report if isinstance(report, str) else json.dumps(report), encoding="utf-8")
                return CC.collect_cases(root)["checkout"]["automated"]
            # HF3-1 (FR-59, FR-18; P20: the expectation follows the finding "three readers of green without a run row", not
            # the new code): the manifest's green counts as automated only with a GREEN run row of its own. The pins below
            # that used to count "as before" now hold (0); green stays 1, red and error stay 0.
            check_eq("A-K4 (R2 flipped): no run-report.json: the manifest's green alone is not a run - not counted", automated_with(None), 0)
            check_eq("A-K4 (edge 5 flipped): an unreadable report is no run - not counted",
                     automated_with("{ this is not json"), 0)
            check_eq("R3 t-415: a green run counts, as before",
                     automated_with({"current_results": [{"instance_id": "repo:p:coupon", "status": "passed"}]}), 1)
            check_eq("A-K4 (R2 flipped): another instance's red run does not touch this case - nor is it its run: not counted",
                     automated_with({"current_results": [{"instance_id": "repo:p:other", "status": "failed"}]}), 0)
            check_eq("R1 t-415: a red run under a green manifest is not counted automated",
                     automated_with({"current_results": [{"instance_id": "repo:p:coupon", "status": "failed"}]}), 0)
            check_eq("R1 t-415: an `error` run reads red too",
                     automated_with({"current_results": [{"instance_id": "repo:p:coupon", "status": "error"}]}), 0)
            check_eq("A-K4 (flipped): a `partial` run is not red, and not green either: not counted",
                     automated_with({"current_results": [{"instance_id": "repo:p:coupon", "status": "partial"}]}), 0)
            check_eq("A-K4: a `skipped` run is not a pass: not counted",
                     automated_with({"current_results": [{"instance_id": "repo:p:coupon", "status": "skipped"}]}), 0)
        finally:
            if report_was is None:
                report_path.unlink(missing_ok=True)
            else:
                report_path.write_bytes(report_was)

        # t-419 (critic t-418; C5), split by HF3-1 into two keys over the same shapes: the "red" key - "is there a red run for this
        # manifest instance" is ONE join, and the two readers that ask it (the traceability table `Story._red_run_row` and the
        # stamp's `not_green:` in `case_stamp.plan`) agree - and the A-K6 "hold" key - the three readers of "this case is proven
        # green" (the stamp, the coverage map `check_coverage.collect_cases`, gate B `check_delivery._cases_held`) say what
        # `case_stamp.instance_hold` says (the old `_cases_held_by_red_run` is gone). Shapes: F1: a passed `x[unparseable]` (its manifest `test` is the bare function) beside a red sibling
        # `x[json]`; F2: a hash identity met only by the tolerant rule; edge 3: an instance with no parameter stands for the whole
        # function; F3: a reducer-overwritten `partial` row keeps the run's word in `raw_status`.
        import case_stamp as S
        import traceability as TR
        ghost = {"instance_id": "ghost-1", "test_id": "tests/a.py::test_w", "status": "partial",
                 "current_reason": "instance_manifest_join_failed"}
        shapes = [
            ("F1 passed own parameter, red sibling", {"test": "tests/a.py::test_x", "parameter": "unparseable"},
             [{"instance_id": "test_x[unparseable]", "test_id": "tests/a.py::test_x[unparseable]", "status": "passed"},
              {"instance_id": "test_x[json]", "test_id": "tests/a.py::test_x[json]", "status": "failed", "case": "TC-002"}], False),
            ("F1 control: its own parameter red", {"test": "tests/a.py::test_x", "parameter": "unparseable"},
             [{"instance_id": "test_x[unparseable]", "test_id": "tests/a.py::test_x[unparseable]", "status": "failed"}], True),
            ("F2 hash identity, tolerant join only", {"instance_id": "ti_0123456789abcdef0001", "test": "tests/a.py::test_y"},
             [{"test_id": "tests.a::test_y", "status": "failed"}], True),
            ("edge 3 bare test, one red parameter", {"test": "tests/a.py::test_z"},
             [{"instance_id": "test_z[a]", "status": "failed"}, {"instance_id": "test_z[b]", "status": "passed"}], True),
            ("edge 3 control: bare test with its own passed row", {"instance_id": "test_q"},
             [{"instance_id": "test_q", "status": "passed"}, {"instance_id": "test_q[a]", "status": "failed"}], False),
            ("F3 partial + raw failed", {"instance_id": "ti_0123456789abcdef0002", "test": "tests/a.py::test_w"},
             [dict(ghost, raw_status="failed")], True),
            ("F3 partial + raw error", {"instance_id": "ti_0123456789abcdef0002", "test": "tests/a.py::test_w"},
             [dict(ghost, raw_status="error")], True),
            ("F3 control: partial + raw passed", {"instance_id": "ti_0123456789abcdef0002", "test": "tests/a.py::test_w"},
             [dict(ghost, raw_status="passed")], False),
            ("F3 control: partial, no raw status", {"instance_id": "ti_0123456789abcdef0002", "test": "tests/a.py::test_w"},
             [dict(ghost)], False),
            ("no run row at all", {"instance_id": "test_none"}, [], False),
        ]
        manifest_was, report_was2 = manifest_path.read_bytes(), report_path.read_bytes() if report_path.is_file() else None
        try:
            for label, fields, rows, expected in shapes:
                entry = dict(manifest["tests"][0])
                entry.pop("instance_id", None)
                entry.update(fields)
                manifest_path.write_text(json.dumps(dict(manifest, tests=[entry])), encoding="utf-8")
                report_path.write_text(json.dumps({"current_results": rows}), encoding="utf-8")
                stored = C.manifest_tests(C.load_json(manifest_path))[0]
                plan = S.plan(task)
                # C5 "red" key (two readers ask the RED question): the table and the stamp's `not_green:` agree on every shape
                red_answers = {
                    "traceability": TR.Story(root, task)._red_run_row(C.test_instance_id(stored), stored) is not None,
                    "case_stamp": any(item["case"] == "TC-001" and item["why"].startswith("not_green:") for item in plan["left"]),
                }
                check_eq(f"C5 the red readers agree on `{label}`", red_answers, dict.fromkeys(red_answers, expected))
                # A-K6 "hold" key (HF3-1, AR-13): the three readers of "this case is proven green" - the stamp (`plan.ready`), the
                # coverage map (`collect_cases`) and gate B (`_cases_held`) - all say what `case_stamp.instance_hold` says. A
                # shape holds when it is red, or when the run holds no GREEN row of its own for the instance (F3 controls, no row).
                holds = bool(S.instance_hold(stored, S.run_rows_of(task, C.load_json(manifest_path))))
                hold_answers = {
                    # this pinned fixture carries no stamp receipt, so `plan` may leave the case for ITS other reasons; what is
                    # compared is whether the stamp left it for a HOLD reason (`case_stamp.HOLDS`)
                    "case_stamp": any(item["case"] == "TC-001" and item["why"].split(":")[0] in S.HOLDS for item in plan["left"]),
                    "check_coverage": CC.collect_cases(root)["checkout"]["automated"] == 0,
                    "check_delivery": "TC-001" in D._cases_held(task, C.load_json(manifest_path)),
                }
                want_hold = expected or label.startswith("F3 control") or label == "no run row at all"
                check_eq(f"A-K6 the hold readers agree with instance_hold on `{label}`", (holds, hold_answers),
                         (want_hold, dict.fromkeys(hold_answers, want_hold)))
        finally:
            manifest_path.write_bytes(manifest_was)
            if report_was2 is None:
                report_path.unlink(missing_ok=True)
            else:
                report_path.write_bytes(report_was2)

        # RH1-8 (HF4-1; AR-13, AR-15, AR-28): the unit of "this pinned case is automated" is the CASE, and the three readers of it - the
        # stamp (`plan.left`), the coverage map (`collect_cases`) and gate B (`_cases_held`) - answer one table on the same
        # fixtures. Each row: (plan word, map counts it, TC-001 in `_cases_held`); `_cases_held` is the held-INSTANCE set it always was
        # (R6), so for a case whose instances are all clean (E4, E4-b, E4-c, E6) it stays empty - the unresolved row and the
        # version link keep a case out of the MAP and the STAMP, not into gate B's hold. Kills: m4 (the map counts per instance:
        # E1, E2), m5 (no `unresolved` check: E4, E4-b, E4-c), m6 (a version on one instance only: E6), m7 (`_cases_held` through
        # `case_holds`, keys for links: E11), m7b (the pin looked up in `case_holds`: E5-c).
        links_path = V.link_path(task)
        links_was = links_path.read_bytes()
        manifest_was3, report_was3 = manifest_path.read_bytes(), report_path.read_bytes() if report_path.is_file() else None
        current_link = {"case_id": "TC-001", "version": record["version"], "content_hash": record["content_hash"]}
        words = set(S.HOLDS) | {"unresolved", "no_automation_evidence"}

        def inst(name, **fields):
            out = dict(manifest["tests"][0])
            out.update({"instance_id": name, "status": "green", "critic_verdict": "approved", "covers": ["TC-001"],
                        "case_version_links": [dict(current_link)]})
            out.pop("selector", None)
            out.update(fields)
            return out

        def readers(tests, passed, failed=(), unresolved=()):
            """What the three readers say about TC-001 for this manifest and run."""
            manifest_path.write_text(json.dumps(dict(manifest, tests=list(tests), unresolved=list(unresolved))), encoding="utf-8")
            rows = [{"instance_id": n, "status": "passed"} for n in passed] + [{"instance_id": n, "status": "failed"} for n in failed]
            report_path.write_text(json.dumps({"current_results": rows}), encoding="utf-8")
            fresh = C.load_json(manifest_path)
            plan = S.plan(task)
            why = next((item["why"].split(":")[0] for item in plan["left"] if item["case"].rsplit("/", 1)[-1] == "TC-001"), "")
            return (why if why in words else "", CC.collect_cases(root)["checkout"]["automated"], "TC-001" in D._cases_held(task, fresh))

        handed = [{"case": "TC-001", "reason": "handed_to_person"}]
        dead = inst("t_dead", note="SUPERSEDED DUPLICATE - split")
        a, b, c = inst("t_a"), inst("t_b"), inst("t_c")
        try:
            table = [
                ("E1 (one green, one without a row, one red)", readers([a, b, c], ["t_a"], ["t_c"]), ("not_green", 0, True)),
                ("E1-c (three clean)", readers([a, b, c], ["t_a", "t_b", "t_c"]), ("", 1, False)),
                ("E2 (two instances, one without a row)", readers([a, b], ["t_a"]), ("not_run", 0, True)),
                ("E3 (a dead row only)", readers([dead], []), ("no_automation_evidence", 0, False)),
                ("E4 (handed_to_person, the instance clean)", readers([a], ["t_a"], unresolved=handed), ("unresolved", 0, False)),
                ("E4-b (another reason, the instance clean)", readers([a], ["t_a"], unresolved=[{"case": "TC-001", "reason": "blocked_by_env"}]),
                 ("unresolved", 0, False)),
                ("E4-c (an unresolved row without an area, the instance area-qualified)",
                 readers([inst("t_a", covers=["checkout/TC-001"])], ["t_a"], unresolved=handed), ("unresolved", 0, False)),
                ("E6 (the second clean instance links another version)",
                 readers([a, inst("t_b", case_version_links=[dict(current_link, version="cv_other")])], ["t_a", "t_b"]), ("", 0, False)),
                ("E11 (a prefix-only legacy instance, red, beside a clean one)",
                 readers([{"instance_id": "TC-001::test_x", "status": "green", "critic_verdict": "approved"}, a], ["t_a"], ["TC-001::test_x"]),
                 ("not_green", 0, False)),
            ]
            for label, got, want in table:
                check_eq(f"RH1-8 A-K6+ the three readers agree on {label}", got, want)
            check_eq("RH1-8 E2 finding key: two instances, one held -> map 0", readers([a, b], ["t_a"])[1], 0)
            # E1-d: the verdict is held by the TEST rows (`not_executed`), not by the case unit
            readers([a, b, c], ["t_a"], ["t_c"])
            done = D.assess(task)
            check("RH1-8 E1-d assess -> no with a not_executed test row",
                  done["delivery_verdict"] == "no" and any("not_executed" in str(r) for r in done["reasons"]),
                  f"{done['delivery_verdict']}: {done['reasons']}")
            # E5-c: a bare pin (0.7.x, no area) and area-qualified clean instances: the pin decides, not the spelling of a key
            stored = json.loads(links_was.decode("utf-8"))
            for link in stored["links"]:
                link.pop("area", None)
            links_path.write_text(json.dumps(stored), encoding="utf-8")
            check_eq("RH1-8 E5-c bare pin, qualified clean entries -> map 1",
                     readers([inst("t_a", covers=["checkout/TC-001"]), inst("t_b", covers=["checkout/TC-001"])], ["t_a", "t_b"])[1], 1)
            links_path.write_bytes(links_was)
            # E8: a broken join is no "held: no" - the map counts nothing for the task, gate B's reader raises
            readers([a], ["t_a"])
            check_eq("RH1-8 E8 control: the clean case counts before the join breaks", CC.collect_cases(root)["checkout"]["automated"], 1)
            real = (S.case_hold, S.held_case_links)

            def broken(*args, **kwargs):
                raise RuntimeError("the run join is broken")
            S.case_hold = S.held_case_links = broken
            try:
                raised = False
                try:
                    D._cases_held(task, C.load_json(manifest_path))
                except RuntimeError:
                    raised = True
                check("RH1-8 E8 broken case_stamp: collect_cases counts 0 for the task, _cases_held raises",
                      CC.collect_cases(root)["checkout"]["automated"] == 0 and raised)
            finally:
                S.case_hold, S.held_case_links = real
        finally:
            links_path.write_bytes(links_was)
            manifest_path.write_bytes(manifest_was3)
            if report_was3 is None:
                report_path.unlink(missing_ok=True)
            else:
                report_path.write_bytes(report_was3)

        # A later case version invalidates only this proof. The old immutable bytes remain,
        # but delivery/coverage/dashboard must stop calling the current version automated.
        source.write_text(source.read_text(encoding="utf-8") + "\nNew boundary for v2.\n", encoding="utf-8")
        newer = V.create_version(store, source)
        V.pin(task, newer, expected_previous_version=record["version"])
        reasons = D.case_version_reasons(task) + D.lifecycle_reasons(task)
        check("new pin makes the old manifest proof stale", any("stale case link" in reason or
              "lacks current pinned" in reason for reason in reasons), reasons)
        areas = CC.collect_cases(root)
        check_eq("coverage removes automation credit for stale version proof",
                 areas["checkout"]["automated"], 0)
        row = next(item for item in FD.parse_taskruns(root) if item["task"] == "QA-1")
        check("dashboard exposes the same stale version gap", bool(row["case_lifecycle_issues"]))
    finally:
        cleanup(root)

    from harness import finish
    finish("test_pinned_lifecycle")


if __name__ == "__main__":
    main()
