"""check_traceability.py — requirement -> plan row -> case -> terminal outcome."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import (  # noqa: E402
    BAD, GOOD, SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_project,
)

sys.path.insert(0, str(SCRIPTS))
import check_traceability as T  # noqa: E402


def outcome(result: dict, req: str) -> str:
    return next((r["outcome"] for r in result["rows"] if r["requirement"] == req), "<absent>")


def detail(result: dict, req: str) -> str:
    return next((r["detail"] for r in result["rows"] if r["requirement"] == req), "")


def main() -> None:
    # --- the good set: every link in the chain holds ---------------------------------------
    good = T.walk(GOOD)
    check_eq("good: three requirements traced", good["requirements"], 3)
    check_eq("good: nothing without an outcome", good["without_outcome"], [])
    check_eq("good: ok", good["ok"], True)
    check_eq("good: R-1 is an executed automated test", outcome(good, "R-1"), "executed_passed")
    check_eq("good: R-2 is an executed manual-agent case", outcome(good, "R-2"), "executed_passed")
    check_eq("good: R-3 is a recorded decision, not a silence",
             outcome(good, "R-3"), "deferred_by_decision")
    p = run_script("check_traceability.py", GOOD)
    check_eq("good: CLI exits 0", p.returncode, 0)
    check_in("good: the CLI says so out loud", "every requirement reaches a terminal outcome", p.stdout)

    # --- the bad set: two links break, each named ------------------------------------------
    bad = T.walk(BAD)
    check_eq("bad: four requirements traced", bad["requirements"], 4)
    check_eq("bad: R-1 still reaches an outcome", outcome(bad, "R-1"), "executed_passed")
    check_eq("bad: R-2 failed, which is still terminal", outcome(bad, "R-2"), "executed_failed")
    check_eq("bad: R-3 has no outcome (unresolved with no decision)", outcome(bad, "R-3"), "")
    check_in("bad: and the detail names why", "no decision attached", detail(bad, "R-3"))
    check_eq("bad: R-4 has no outcome (no plan row)", outcome(bad, "R-4"), "")
    check_in("bad: and the detail names the broken link",
             "no row of test-plan.md names this requirement", detail(bad, "R-4"))
    check_eq("bad: not ok", bad["ok"], False)
    p = run_script("check_traceability.py", BAD)
    check_eq("bad: CLI exits 1", p.returncode, 1)
    check_in("bad: the CLI lists the requirements", "R-3, R-4", p.stdout)

    # --- --json is the machine-readable form of the same walk -------------------------------
    p = run_script("check_traceability.py", GOOD, "--json")
    data = json.loads(p.stdout)
    check_eq("--json carries the same verdict", data["ok"], True)
    check_eq("--json carries one row per requirement", len(data["rows"]), 3)

    # --- a pending-implementation case is terminal, an unresolved one without a reason is not
    root = temp_project("qa-factory-trace-")
    try:
        art = root / "qa-factory" / "artifacts" / "QA-9"
        art.mkdir(parents=True)
        import shutil
        shutil.copy(BAD / "test-plan.md", art / "test-plan.md")
        (art / "work").mkdir(parents=True, exist_ok=True)
        for name in ("requirements-register.md", "run-report.json"):
            shutil.copy(BAD / "work" / name, art / "work" / name)
        shutil.copytree(BAD / "work" / "test-cases", art / "work" / "test-cases")
        (art / "work" / "automation-manifest.json").write_text(json.dumps({
            "tests": [], "unresolved": [
                {"case": "TC-001", "reason": "pending_implementation"},
                {"case": "TC-002", "reason": "deferred_by_decision:gateA"},
                {"case": "TC-003", "reason": "impossible"},
            ], "run_witness": "x"}), encoding="utf-8")
        (art / "work" / "run-report.json").write_text(json.dumps({"results": [], "manual_checks": []}),
                                             encoding="utf-8")
        result = T.walk(art)
        check_eq("pending_implementation is a terminal outcome",
                 outcome(result, "R-1"), "pending_implementation")
        check_eq("deferred_by_decision is a terminal outcome",
                 outcome(result, "R-2"), "deferred_by_decision")
        check_eq("impossible with no decision is not", outcome(result, "R-3"), "")

        # A gap the human accepted at a gate travels to the next gate. Without this,
        # TP2-2381's R-9 was recomputed at gate B and cost a second pass of the
        # whole pipeline to ask the same person the same question.
        check_eq("R-4 has no outcome to begin with", outcome(result, "R-4"), "")
        pipeline = art / "pipeline.json"
        pipeline.write_text(json.dumps({
            "ticket": "QA-9",
            "gates": {"A": {"decision": "approve", "by": "human"}},
        }), encoding="utf-8")
        p = run_script("waiver.py", "--task", "QA-9", "--gate", "A", "--requirement", "R-4",
                       "--decision", "the approved scope is sufficient",
                       env={"CLAUDE_PROJECT_DIR": str(root)})
        check_eq("waiver.py exits 0 on a recorded gate", p.returncode, 0)
        waived = T.walk(art)
        check_eq("a waived requirement is a recorded decision",
                 outcome(waived, "R-4"), "deferred_by_decision")
        check_in("the human's words travel with it",
                 "the approved scope is sufficient", detail(waived, "R-4"))
        check_in("and the gap stays visible beside them", "the gap:", detail(waived, "R-4"))
        check_eq("a waiver does not touch another requirement", outcome(waived, "R-3"), "")

        # No gate recorded, no waiver: otherwise this is the factory excusing itself.
        pipeline.write_text(json.dumps({"ticket": "QA-9", "gates": {}}), encoding="utf-8")
        p = run_script("waiver.py", "--task", "QA-9", "--gate", "A", "--requirement", "R-3",
                       "--decision", "nobody asked", env={"CLAUDE_PROJECT_DIR": str(root)})
        check_eq("a waiver without a gate decision is refused", p.returncode, 5)
        check_in("and says why", "nobody was asked", p.stderr)
    finally:
        cleanup(root)

    typed_gap_words()
    failure_outranks_handoff()
    red_run_outranks_manifest_status()
    tolerant_join_of_run_results()
    mixed_then_trace()
    proof_strength_then_is_not_pass()
    unrun_instance_in_a_then()
    legacy_join_of_run_rows()
    triage_joins_through_the_run_row()
    answered_suffix_needs_a_standing_answer()
    a_case_taken_by_hand_has_an_outcome()
    finish("test_traceability")


def failure_outranks_handoff() -> None:
    """K-N8.27 (t-305 N8 attempt 2, F1): the chain lets an OBSERVED failed result win over a `handed_to_person` row (the case
    RAN and went red: the hand-off promises nothing about it), and the report's own table does not show such a case as
    PROVEN. A handed case with NO failed result reads as it always did (the control)."""
    import shutil
    import traceability as TR
    from harness import FIXTURES, temp_dir
    root = temp_dir("qa-trace-handoff-")
    task = root / "QA-1"
    shutil.copytree(FIXTURES / "after-checks", task)
    try:
        def edit(rel: str, change) -> None:
            data = json.loads((task / rel).read_text(encoding="utf-8"))
            change(data)
            (task / rel).write_text(json.dumps(data), encoding="utf-8")

        def table(name: str) -> dict:
            return {r["requirement"] + "/" + r["case"]: r for r in TR.build(task.parents[1], task)["rows"]}
        control = T.walk(task)
        row = next(r for r in control["rows"] if r["requirement"] == "R-5")
        check_eq("K-N8.27 control: a handed case with no failure is a gap `unresolved:handed_to_person`",
                 (row["outcome"], row["gaps"]), ("", [{"case": "TC-005", "gap": "unresolved:handed_to_person"}]))
        check_eq("K-N8.27 control: ... and the report's table says it waits for the person (HF2-6: nothing run is no `pass`)",
                 table("control")["R-5/TC-005"]["result"], "wait")
        edit("work/automation-manifest.json", lambda m: m["unresolved"].append(
            {"case": "TC-001", "reason": "handed_to_person", "detail": "run it: npm test"}))
        edit("work/run-report.json", lambda r: r["results"][0].update(result="failed", attempt_id="a1"))
        failed = T.walk(task)
        row = next(r for r in failed["rows"] if r["requirement"] == "R-1")
        check_eq("K-N8.27 a failed result outranks the hand-off in the chain: its outcome, no gap",
                 (row["outcome"], row["gaps"]), ("executed_failed", []))
        check("K-N8.27 ... the report's table does not show the handed case as PROVEN",
              table("failed")["R-1/TC-001"]["result"] != "pass", str(table("failed")["R-1/TC-001"]))
        # a failing instance of TC-005, handed for android: its own failure, not a pass
        edit("work/run-report.json", lambda r: r["results"].append(
            {"test": "tests/e2e/coupon.android.spec.ts::TC-005", "case": "TC-005", "result": "failed", "attempt_id": "a1"}))
        check("K-N8.27 TC-005 failing on its own instance: the table does not show it as PROVEN either",
              table("tc5")["R-5/TC-005"]["result"] != "pass", str(table("tc5")["R-5/TC-005"]))
    finally:
        cleanup(root)


def red_run_outranks_manifest_status() -> None:
    """t-412 (B-303; critic t-403 G4): the appendix table never reads `pass` for an instance whose run result is red. `instance_outcome`
    used to read the manifest `status` first, so a manifest saying `green` printed `| R-1 | ... | TC-001 | pass |` under a verdict `no`
    and "Proven - 0 green tests". The run result outranks the manifest status for EVERY case; the table's vocabulary has no `failed`
    word (no new status words), so a red run reads as the existing red words: `blocked` (triage not recorded) or `bug`."""
    import shutil
    import traceability as TR
    from harness import FIXTURES, temp_dir
    root = temp_dir("qa-trace-red-run-")
    task = root / "QA-1"
    shutil.copytree(FIXTURES / "after-checks", task)
    try:
        def edit(rel: str, change) -> None:
            data = json.loads((task / rel).read_text(encoding="utf-8"))
            change(data)
            (task / rel).write_text(json.dumps(data), encoding="utf-8")

        def row_of(key: str = "R-1/TC-001") -> dict:
            return {r["requirement"] + "/" + r["case"]: r for r in TR.build(task.parents[1], task)["rows"]}[key]

        def manifest_says(word) -> None:
            def change(m):
                if word is None:
                    m["tests"][0].pop("status", None)
                else:
                    m["tests"][0]["status"] = word
            edit("work/automation-manifest.json", change)

        def run_says(word) -> None:
            def change(r):
                if word is None:
                    r["results"] = []
                else:
                    r["results"][0].update(result=word, attempt_id="a1")
            edit("work/run-report.json", change)

        # The fixture's manifest row carries a hash identity and its run row a function identity, so the two never join; a real
        # manifest holds the id the runner enumerates (FR-16). Give TC-001's row that id, so the run result IS the instance's.
        import contract as C
        run_row = json.loads((task / "work/run-report.json").read_text(encoding="utf-8"))["results"][0]
        edit("work/automation-manifest.json", lambda m: m["tests"][0].update(instance_id=C.test_instance_id(run_row)))
        # K2 control: a green run still reads pass, whatever non-red word the manifest carries
        for said in ("green", "pass", "written", "weird-word"):
            manifest_says(said)
            check_eq(f"K2 a green run still reads pass (manifest says {said!r})", row_of()["result"], "pass")
        # K1: a red run result, the manifest says pass / green
        for said in ("pass", "green"):
            manifest_says(said)
            for red in ("failed", "error"):
                run_says(red)
                got = row_of()
                check(f"K1 a red run result ({red}) is never `pass` in the table even when the manifest says {said!r}",
                      got["result"] != "pass", str(got))
                check_eq(f"K1 ... it reads the red word `blocked` (triage not recorded), manifest {said!r}, run {red}",
                         got["result"], "blocked")
                check_in("K1 ... and its basis names the red run", "red run", got["basis"])
        # K1 on the paths that reach the same function: a Then binding and the unbound-instance row
        manifest_says("green")
        run_says("failed")
        check("K1 the red run is not `pass` on any row of the case",
              all(r["result"] != "pass" for r in TR.build(task.parents[1], task)["rows"] if r["case"] == "TC-001"),
              str([r for r in TR.build(task.parents[1], task)["rows"] if r["case"] == "TC-001"]))
        # edge 5 / HF2-6 F-6: an unknown run-result word is not mapped to a pass, nor to red: nothing green was recorded, so
        # the instance is `not run` and the basis says which word the run recorded (the manifest's `green` is no execution)
        run_says("weird-word")
        manifest_says("green")
        got = row_of()
        check_eq("K5 an unknown run-result word is `not run`, whatever the manifest says (HF2-6)", got["result"], "not run")
        check_in("K5 ... and the basis names the word the run recorded", "weird-word", got["basis"])
        # HF3-7 C-K1 (FR-10, F-5 (b)): ONE Then, ONE word in the trace table and in both ledger readers. A run word outside the
        # vocabulary (`expected_product_failure` has no producer, the run-report validator refuses it) is `not run` in the table,
        # `not_executed:the run recorded <word> for this test` in the ledger's test row and `not_executed:` in the plan row of the
        # case - never `failed:*` (the old `rollup_status` reading), never `passed_green`/`pass`.
        import ledger as L
        plan_row = {"ts": "TS-1", "disposition": "automate"}

        def ledger_reads() -> tuple:
            manifest = json.loads((task / "work/automation-manifest.json").read_text(encoding="utf-8"))
            report = json.loads((task / "work/run-report.json").read_text(encoding="utf-8"))
            return (L.test_state(manifest["tests"][0], report, {"triage": []}, task, manifest),
                    L.plan_row_state(plan_row, manifest, report, {}, {"TS-1": ["TC-001"]}))

        for word in ("expected_product_failure", "weird-word"):
            run_says(word)
            manifest_says("green")
            seen = row_of()
            (test_row, _detail), (plan_state, plan_detail) = ledger_reads()
            check_eq(f"C-K1 {word}: the trace table says `not run`", seen["result"], "not run")
            check_in(f"C-K1 {word}: ... and its basis names the word", word, seen["basis"])
            check_eq(f"C-K1 {word}: the ledger's test row says the same, with the same word", test_row,
                     f"not_executed:the run recorded {word} for this test")
            check_eq(f"C-K1 {word}: the plan row of the case is `not_executed:` with the word",
                     plan_state, f"not_executed:the run recorded {word} for this row's cases")
            check_eq(f"C-K1 {word}: ... its detail is the case", plan_detail, "TC-001")
            for reader, said in (("trace", seen["result"]), ("test row", test_row), ("plan row", plan_state)):
                check(f"C-K1 {word}: the {reader} is neither green nor red", said not in ("pass", "passed_green")
                      and not said.startswith("failed") and said != "blocked" and said != "bug", said)
        # M3: the word does not change an environment block - the history of an `env_blocked` run keeps the owner of the block
        run_says("expected_product_failure")
        edit("work/run-report.json", lambda r: r.update(execution_status="env_blocked"))
        check_eq("C-K1 M3: an env_blocked run with an unknown word keeps `env_blocked:*` (the word never replaces the owner)",
                 ledger_reads()[0][0].split(":")[0], "env_blocked")
        edit("work/run-report.json", lambda r: r.update(execution_status="passed"))
        # the manifest's own `red` still reads red under a green run (as today)
        run_says("passed")
        manifest_says("red")
        check_eq("K2 a green run does not lift a manifest `red`", row_of()["result"], "blocked")
        # K3 / HF2-6 K1: no run result for the instance: `not run`, whatever word the manifest carries - a manifest status is
        # no execution (FR-41, FR-18); the basis is the ledger's own sentence, and never claims a red run that does not exist
        run_says(None)
        manifest_says("green")
        got = row_of()
        check_eq("K3 no run result: the manifest status `green` is `not run` (HF2-6)", got["result"], "not run")
        check_eq("K3 ... with the ledger's own words as its basis", got["basis"], "no result for this test in run-report.json")
        manifest_says("red")
        got = row_of()
        check_eq("K3 no run result: the manifest status `red` is `not run` as well", got["result"], "not run")
        check_not_in("K3 ... and its basis does not claim a red run", "red run", got["basis"])
        manifest_says(None)
        check_eq("K3 no run result and no manifest status: `not run`", row_of()["result"], "not run")
        # K4 / HF2-6: a handed-to-person case with no run record waits for the person (P21: what the person took stays
        # `after_checks`, neither `pass` nor `not run`); its own failed instance -> not pass
        edit("work/run-report.json", lambda r: r.update(results=[]))
        got = row_of("R-5/TC-005")
        check_eq("K4 a handed case with no result waits for the person (HF2-6)", got["result"], "wait")
        check_in("K4 ... in the words of the hand-off row", "android: npm run e2e", got["basis"])
        edit("work/run-report.json", lambda r: r["results"].append(
            {"test": "tests/e2e/coupon.android.spec.ts::TC-005", "case": "TC-005", "result": "failed", "attempt_id": "a1"}))
        check("K4 a handed case failing on its own instance is not `pass`", row_of("R-5/TC-005")["result"] != "pass",
              str(row_of("R-5/TC-005")))
    finally:
        cleanup(root)


def tolerant_join_of_run_results() -> None:
    """t-414 (B-308 a, c). The table finds an instance's run result by the exact id AND by the dashboard's tolerant rule
    (`factory_dashboard.match_run_row`): a manifest row with a hash identity (`ti_...`) and a run row with the runner's function
    identity never met under the exact join, so a red run read as "no run result" and the row stayed `pass` (the shape of the
    `after-checks` fixture). Keys J1-J6; the invariant is that a row reads `pass` only when no red run result can be joined to
    it by either rule, and that a run row of ANOTHER test never turns a green row red."""
    import shutil
    import traceability as TR
    from harness import FIXTURES, temp_dir
    root = temp_dir("qa-trace-join-")
    task = root / "QA-1"
    shutil.copytree(FIXTURES / "after-checks", task)
    hashed = "ti_0123456789abcdef0001"        # the manifest's identity: a hash, not the function id the runner enumerates
    test_id = "tests/test_coupon.py::test_cap_rejected"
    try:
        def edit(rel: str, change) -> None:
            data = json.loads((task / rel).read_text(encoding="utf-8"))
            change(data)
            (task / rel).write_text(json.dumps(data), encoding="utf-8")

        def row_of(key: str = "R-1/TC-001") -> dict:
            return {r["requirement"] + "/" + r["case"]: r for r in TR.build(task.parents[1], task)["rows"]}[key]

        def manifest_row(**fields) -> None:
            def change(m):
                m["tests"][0].update(status="green", **fields)
            edit("work/automation-manifest.json", change)

        def run_rows(*rows) -> None:
            edit("work/run-report.json", lambda r: r.update(results=[dict(row, attempt_id="a1") for row in rows]))

        def run_row(word, **fields) -> dict:
            return dict({"test": test_id, "case": "TC-001", "result": word}, **fields)

        manifest_row(instance_id=hashed, test=test_id)
        run_rows(run_row("failed"))
        story = TR.Story(task.parents[1], task)
        check("J1 precondition: the exact join misses (the manifest id is a hash, the run row's is the function id)",
              story.results.get(hashed) is None and "test_cap_rejected" in story.results, str(list(story.results)))
        # J1: a red run joined ONLY by the tolerant rule reads red, whatever the manifest says
        for red in ("failed", "error"):
            run_rows(run_row(red, reason="AssertionError: 422 expected"))
            got = row_of()
            check_eq(f"J1 a red run ({red}) joined only by the tolerant rule reads the red word `blocked`", got["result"], "blocked")
            check_in(f"J1 ... and its basis is the red run's own reason ({red})", "422 expected", got["basis"])
            check("J1 ... and no row of the case reads `pass`",
                  all(r["result"] != "pass" for r in TR.build(task.parents[1], task)["rows"] if r["case"] == "TC-001"))
        # J2: an exact match behaves as before (the id the runner enumerates, FR-16)
        manifest_row(instance_id="test_cap_rejected", test=test_id)
        run_rows(run_row("passed"))
        check_eq("J2 exact id, green run: pass as before", row_of()["result"], "pass")
        run_rows(run_row("failed"))
        check_eq("J2 exact id, red run: the red word as before (t-412)", row_of()["result"], "blocked")
        run_rows()
        check_eq("J2 no run row at all: `not run` - the manifest status `green` is no execution (HF2-6)", row_of()["result"], "not run")
        manifest_row(instance_id=hashed, test=test_id)
        check_eq("J2 no run row, hashed id: `not run` as well", row_of()["result"], "not run")
        # J3: two candidate run rows for one manifest row, one of them red: red, in either order; both green: pass
        for order in ("green first", "red first"):
            rows = [run_row("passed", instance_id="run-a"), run_row("failed", instance_id="run-b")]
            run_rows(*(rows if order == "green first" else rows[::-1]))
            check_eq(f"J3 two candidates, one red ({order}): red", row_of()["result"], "blocked")
        run_rows(run_row("passed", instance_id="run-a"), run_row("passed", instance_id="run-b"))
        check_eq("J3 control: two candidates, both green: pass", row_of()["result"], "pass")
        run_rows(run_row("passed", instance_id="run-a"), run_row("error", instance_id="run-b"))
        check_eq("J3 two candidates, one `error`: red as well", row_of()["result"], "blocked")
        # J4: a run row of another test does not join: another function name, a sibling parameter, the same case link alone
        other = "tests/test_other.py::test_other_thing"
        run_rows(run_row("failed", test=other, instance_id="test_other_thing"))
        check_eq("J4 a red run of another test (another function) does not turn the row red - and is no run of this one: `not run`",
                 row_of()["result"], "not run")
        manifest_row(instance_id=hashed, test=test_id + "[eu]")
        run_rows(run_row("failed", test=test_id + "[us]", instance_id="test_cap_rejected[us]"))
        check_eq("J4 a red run of a sibling parameter `[us]` does not turn the `[eu]` row red - and is no run of it: `not run`",
                 row_of()["result"], "not run")
        run_rows(run_row("failed", test=test_id + "[eu]", instance_id="test_cap_rejected[eu]"))
        check_eq("J4 control: the red run of its own `[eu]` parameter does read red", row_of()["result"], "blocked")
        manifest_row(instance_id=hashed, test=test_id)
        # J5: empty / None ids on either side join nothing and raise nothing
        run_rows({"instance_id": None, "test": "", "case": "TC-001", "result": "failed"},
                 {"instance_id": "", "test_id": None, "result": "error"})
        check_eq("J5 run rows with empty / None ids do not join the manifest row (no red, and no run of it: `not run`)",
                 row_of()["result"], "not run")
        story = TR.Story(task.parents[1], task)
        for label, args in (("no id, no entry", ("", None)), ("None id, empty entry", (None, {})),
                            ("an entry whose id fields are all empty", ("x", {"instance_id": "", "test": None, "marker": "",
                                                                             "selector": None, "report_test_id": ""}))):
            try:
                got = story._red_run_row(*args)
            except Exception as exc:  # noqa: BLE001 - the key is that nothing is raised
                got = f"raised {exc!r}"
            check_eq(f"J5 {label}: no join, no exception", got, None)
        manifest_row(instance_id="", test="", marker="", selector="")
        run_rows(run_row("failed"))
        try:
            ok = [r["result"] for r in TR.build(task.parents[1], task)["rows"] if r["case"] == "TC-001"]
        except Exception as exc:  # noqa: BLE001
            ok = f"raised {exc!r}"
        check("J5 a manifest row with every id field empty: the table is built (no exception)", isinstance(ok, list), str(ok))
        manifest_row(instance_id=hashed, test=test_id)
        # J6: a handed case whose run ERRORED counts as failed for the handed-case branch (TC-005 is handed in the fixture); the
        # run row names the case but joins no instance by id, so only the case-level reading can see it
        elsewhere = "tests/e2e/elsewhere.spec.ts::test_elsewhere"
        for word, expect in (("passed", "pass"), ("failed", "blocked"), ("error", "blocked")):
            run_rows({"test": elsewhere, "case": "TC-005", "result": word, "attempt_id": "a1"})
            check_eq(f"J6 a handed case whose run says {word}: {expect}", row_of("R-5/TC-005")["result"], expect)
        # (`passed` stays `pass`: TC-005 has one live entry with no identity of its own and the run has one row of TC-005 - the
        # legacy step of `case_stamp.run_row_for` joins them, as the ledger always did. HF2-6 section 11 P5 expected `wait` here;
        # that holds only without the legacy row - see the open question in the hand-off, t-122.)
        story = TR.Story(task.parents[1], task)
        check("J6 `_case_failed` is true for `error` exactly as for `failed`",
              story._case_failed("TC-005") is True, str(story.results))
        run_rows({"test": elsewhere, "case": "TC-005", "result": "skipped", "attempt_id": "a1"})
        check("J6 control: a skipped run is not failed", TR.Story(task.parents[1], task)._case_failed("TC-005") is False)
        check_eq("J6 ... and it is no pass either: the handed case's only row says `skipped` (legacy join): `not run`",
                 row_of("R-5/TC-005")["result"], "not run")
        run_rows()
        check_eq("J6 a handed case with no run row at all waits for the person", row_of("R-5/TC-005")["result"], "wait")
        # t-419 (critic t-418 F1, F3; edge 3): the table asks `case_stamp.red_run_for`, the one join the stamp, the coverage map
        # and gate B ask too. J7 = F1: a passed `x[unparseable]` whose manifest `test` is the bare function, beside a red
        # sibling `x[json]`. J8 = edge 3: an instance naming no parameter stands for the whole function. J9 = F3: a row the
        # reducer overwrote to `partial` keeps the run's word in `raw_status`.
        manifest_row(instance_id=None, test=test_id, parameter="unparseable")
        run_rows(run_row("passed", test=test_id + "[unparseable]", instance_id="test_cap_rejected[unparseable]"),
                 run_row("failed", test=test_id + "[json]", instance_id="test_cap_rejected[json]"))
        check_eq("J7 a red sibling parameter does not turn a passed instance red", row_of()["result"], "pass")
        run_rows(run_row("failed", test=test_id + "[unparseable]", instance_id="test_cap_rejected[unparseable]"),
                 run_row("passed", test=test_id + "[json]", instance_id="test_cap_rejected[json]"))
        check_eq("J7 control: its own parameter red reads red", row_of()["result"], "blocked")
        manifest_row(instance_id=hashed, test=test_id, parameter=None)
        run_rows(run_row("failed", test=test_id + "[a]", instance_id="test_cap_rejected[a]"),
                 run_row("passed", test=test_id + "[b]", instance_id="test_cap_rejected[b]"))
        check_eq("J8 a bare-test manifest row reads red when any of its parameters is red", row_of()["result"], "blocked")
        run_rows(run_row("passed", test=test_id + "[a]", instance_id="test_cap_rejected[a]"),
                 run_row("passed", test=test_id + "[b]", instance_id="test_cap_rejected[b]"))
        check_eq("J8 control: all its parameters green: pass", row_of()["result"], "pass")
        run_rows(run_row("passed", instance_id="test_cap_rejected"),
                 run_row("failed", test=test_id + "[a]", instance_id="test_cap_rejected[a]"))
        check_eq("J8 control: a bare row with its OWN passed run is not pulled red by a red parameter row",
                 row_of()["result"], "pass")
        ghost = {"instance_id": "ghost-1", "current_reason": "instance_manifest_join_failed"}
        for raw, expect in (("failed", "blocked"), ("error", "blocked"), ("passed", "not run"), (None, "not run")):
            fields = dict(ghost, raw_status=raw) if raw else dict(ghost)
            run_rows(run_row("partial", **fields))
            check_eq(f"J9 a join-failed `partial` row with raw status {raw!r}: {expect}", row_of()["result"], expect)
        run_rows(run_row("partial", **dict(ghost, raw_status="failed", superseded=True)))
        got = row_of()
        check_eq("J9 a superseded ghost is history, not the run's word: not red - and not green either: `not run`",
                 got["result"], "not run")
        check_in("J9 ... the basis names the word the run recorded (F-6)", "partial", got["basis"])
        # J10: an unreadable report builds the table (no run result), no exception
        for body in ("{not json", "[]", "null"):
            (task / "work/run-report.json").write_text(body, encoding="utf-8")
            try:
                got = row_of()["result"]
            except Exception as exc:  # noqa: BLE001
                got = f"raised {exc!r}"
            check_eq(f"J10 run-report.json = {body!r}: the table is built, no run record: `not run` (HF2-6)", got, "not run")
        # FR-18: a log under evidence/runs/ is not a run record - without run-report.json it reads as an empty report
        (task / "work/run-report.json").unlink()
        (task / "work/evidence/runs").mkdir(parents=True, exist_ok=True)
        (task / "work/evidence/runs/20261026T000000Z.log").write_text("1 passed in 0.1s\n", encoding="utf-8")
        check_eq("J10 evidence/runs/ present, no run-report.json: as an empty report - `not run`", row_of()["result"], "not run")
    finally:
        cleanup(root)


def typed_gap_words() -> None:
    """K-N8.23 (t-305 N8, F1/C5): the delivery verdict reads the TYPED word of the link that broke (`gap_of_case`), and the chain
    that says it is the one `outcome_for_case` walks - so the outcome and its detail are byte-equal to what they were."""
    from harness import FIXTURES
    import contract as C
    plan = {"disposition": ""}
    manual = dict(plan, disposition="manual-human")
    base = {"tests": [{"case": "TC-1", "file": "t.py", "marker": "TC-1"}], "unresolved": []}

    def gap(case, row=plan, manifest=base, report=None):
        return T.gap_of_case(case, row, manifest, report or {})
    check_eq("K-N8.23 a handed row", gap("TC-1", manifest=dict(base, unresolved=[{"case": "TC-1", "reason": "handed_to_person"}])),
             "unresolved:handed_to_person")
    check_eq("K-N8.23 an unconfirmed expectation", gap("TC-1", manifest=dict(base, unresolved=[
        {"case": "TC-1", "reason": "expectation_unconfirmed"}])), "unresolved:expectation_unconfirmed")
    check_eq("K-N8.23 a stand block", gap("TC-1", manifest=dict(base, unresolved=[{"case": "TC-1", "reason": "blocked_by_env"}])),
             "unresolved:blocked_by_env")
    check_eq("K-N8.23 any other reason keeps its word", gap("TC-1", manifest=dict(base, unresolved=[
        {"case": "TC-1", "reason": "contradicts_requirement"}])), "unresolved:contradicts_requirement")
    check_eq("K-N8.23 a row with no reason", gap("TC-1", manifest=dict(base, unresolved=[{"case": "TC-1"}])), "unresolved:no_reason")
    check_eq("K-N8.23 a decided deferral is no gap", gap("TC-1", manifest=dict(base, unresolved=[
        {"case": "TC-1", "reason": "deferred_by_decision:gateA"}])), "")
    check_eq("K-N8.23 a result that did not conclude",
             gap("TC-1", report={"manual_checks": [{"case": "TC-1", "result": "inconclusive"}]}), "result:inconclusive")
    # HF4-3 C-K5: the gap names every unknown run word of the case (the rollup's join), not the last one
    two = dict(base, tests=[{"case": "TC-1", "file": "t.py", "marker": "TC-1", "instance_id": "i1"},
                            {"case": "TC-1", "file": "t.py", "marker": "TC-1", "instance_id": "i2"}])
    check_eq("K-N8.23 C-K5 (HF4-3) two unknown run words are both in the gap",
             gap("TC-1", manifest=two, report={"current_results": [
                 {"instance_id": "i1", "case": "TC-1", "status": "weird"}, {"instance_id": "i2", "case": "TC-1", "status": "odd"}]}),
             "result:weird, odd")
    check_eq("K-N8.23 a passed result is no gap",
             gap("TC-1", report={"manual_checks": [{"case": "TC-1", "result": "pass"}]}), "")
    check_eq("K-N8.23 manual-human with no package", gap("TC-1", row=manual), "manual_human_no_package")
    check_eq("K-N8.23 manual-human with its package is no gap",
             gap("TC-1", row=manual, report={"manual_human": [{"case": "TC-1", "evidence": "work/x.md"}]}), "")
    check_eq("K-N8.23 a case in no list of the manifest", gap("TC-9"), "not_in_manifest")
    check_eq("K-N8.23 an automated test the run has no result for", gap("TC-1"), "no_result")
    # the rows of the walk carry them: one per case without an outcome, and the row-level words
    for fixture in ("artifacts-good", "artifacts-bad", "after-checks"):
        result = T.walk(FIXTURES / fixture)
        for row in result["rows"]:
            check(f"K-N8.23 {fixture} {row['requirement']}: `gaps` is a list", isinstance(row.get("gaps"), list), str(row))
            if row["outcome"]:
                continue
            check(f"K-N8.23 {fixture} {row['requirement']}: a row with no outcome names where it stopped",
                  bool(row["gaps"]) and all(g["gap"] for g in row["gaps"]), str(row))
    after = {r["requirement"]: [g["gap"] for g in r["gaps"]] for r in T.walk(FIXTURES / "after-checks")["rows"]}
    check_eq("K-N8.23 the fixture's gaps, by requirement",
             {k: v for k, v in after.items() if v},
             {"R-2": ["result:inconclusive"], "R-4": ["manual_human_no_package"], "R-5": ["unresolved:handed_to_person"]})
    # byte-equal: `outcome_for_case` is the first two values of the same walk, on every fixture case
    for fixture in ("artifacts-good", "artifacts-bad", "after-checks"):
        art = FIXTURES / fixture
        plan_rows = C.parse_plan(C.artifact(art, "test-plan.md"))
        manifest = C.load_json(C.artifact(art, "automation-manifest.json"))
        report = C.load_json(C.artifact(art, "run-report.json"))
        for case, meta in C.case_index(art).items():
            row = next((r for r in plan_rows if r["ts"] == meta.get("plan_row")), {})
            got = T.outcome_for_case(case, row, manifest, report)
            chain = T._case_chain(case, row, manifest, report)
            check_eq(f"K-N8.23 {fixture} {case}: outcome_for_case is the chain's own (outcome, detail)", got, chain[:2])


def mixed_story_of(top: Path, story: dict, name: str, drop_case_file: str = ""):
    """(Story, task) of a `test_mixed_then_outcomes` fixture written under `top / name`, with the Then sections of its case files
    laid over `on_disk` (which writes none). `drop_case_file` removes one case file: a title nobody can read."""
    import traceability as TR
    import test_mixed_then_outcomes as M
    task = M.on_disk(story, top / name)
    cases = task / "work" / "test-cases" / "checkout"
    for case, text in story["texts"].items():
        path = cases / f"{case}.md"
        path.write_text(path.read_text(encoding="utf-8") + "\n## Then" + text.split("## Then", 1)[1], encoding="utf-8")
    if drop_case_file:
        (cases / f"{drop_case_file}.md").unlink()
    return TR.Story(task.parents[1], task), task


T1_TC004 = ("not checked yet: in the same test, TC-004 (The check TC-004 of the moved integration) fails first; "
            "check this again once that is fixed")
T2_TC004_THEN2 = ("not proven: the test stopped at TC-004 (The check TC-004 of the moved integration), Then 2, "
                  "before reaching this check; check this again once that is fixed")


def proof_strength_then_is_not_pass() -> None:
    """t-2181 PC-5 / t-2277 J-C7 (AR-13, AR-15, FR-10): the Then table reads the ledger's proof-strength rule through
    `ledger.proof_readings`: a green that met only a substituted side is `wait` with the state's own words, never `pass`; the same
    story stamped all real (and the unstamped one) stays `pass`. KILLS: the table reading raw green rows only."""
    import copy
    import traceability as TR
    from harness import temp_dir
    import test_mixed_then_outcomes as M

    top = temp_dir("qa-trace-proof-")

    def stamped(met: dict, declared: dict) -> dict:
        story = copy.deepcopy(M.with_status(M.shape_b(), M.MS, "passed"))
        story["manifest"]["tests"][0].update(status="green")
        for entry in story["manifest"]["tests"]:
            entry["sides"] = dict(declared)
        for row in story["report"]["current_results"]:
            row["sides_met"] = dict(met)
        return story

    try:
        plain = copy.deepcopy(M.with_status(M.shape_b(), M.MS, "passed"))
        plain["manifest"]["tests"][0].update(status="green")
        check_eq("control: the unstamped story's Then is `pass`",
                 mixed_story_of(top, plain, "plain")[0].then_outcome("TC-005", 1, "R-5").get("result"), "pass")
        real = mixed_story_of(top, stamped({"backend": "real"}, {"backend": "real"}), "real")[0]
        check_eq("control: stamped real on both sides is `pass`", real.then_outcome("TC-005", 1, "R-5").get("result"), "pass")
        sub, _ = mixed_story_of(top, stamped({"backend": "substituted"}, {"backend": "substituted"}), "sub")
        got = sub.then_outcome("TC-005", 1, "R-5")
        check_eq("a green on a substituted side is `wait`, not `pass`", got.get("result"), "wait")
        check_in("... in the words of the state the summary prints", "stand-in", got.get("basis", ""))
        check_eq("... the same reading the ledger gives", sub.proof_reading("TC-005", 1)[0], "not_verified:on_substitute")
        check_eq("... and a Then of another case that is not stamped that way is read on its own",
                 sub.proof_reading("TC-005", 99), None)
        sub.manifest = {}                                  # an unreadable story reads nothing and never raises
        sub.__dict__.pop("_proof_readings", None)
        check_eq("an empty manifest reads no proof strength", sub.proof_reading("TC-005", 1), None)
        check_eq("the outcome keeps the table's worst-wins shape", TR._merge_outcomes([{"result": "pass"}, {"result": "wait"}])["result"], "wait")
    finally:
        cleanup(top)


def mixed_then_trace() -> None:
    """HF2-3 part 3c2 (spec t-085 rev. 3, keys 3c2-K5, K9; FA-11 variant (b), the safe default: the owner's word on (a) is
    pending, so no key pins a failure-site reader and key (g) is not built). TP1-12586: ONE test (MS) covers TC-004, TC-005
    and TC-006 and stops at TC-004's Then 2; the generic tests (G5, G6) are green. The fixtures are IMPORTED from
    `test_mixed_then_outcomes` (3a1); only the Then sections of the case files are laid over `on_disk`, which writes none."""
    import copy
    import human_text
    import acceptance as AC
    import traceability as TR
    from harness import check_not_in, temp_dir
    import test_mixed_then_outcomes as M

    top = temp_dir("qa-trace-mixed-")

    def story_of(story: dict, name: str, drop_case_file: str = ""):
        return mixed_story_of(top, story, name, drop_case_file)

    def ids(outcome: dict) -> set:
        return {t["instance_id"] for t in outcome.get("tests") or []}

    def edited(story: dict, change) -> dict:
        out = copy.deepcopy(story)
        change(out)
        return out

    def blocked_row(story: dict, case: str, then: int) -> dict:
        return next(b for b in story["manifest"]["then_bindings"]
                    if (b["case"], b["then"], b.get("reason")) == (case, then, "blocked_by_check"))

    try:
        # (a) Shape A: the Thens of TC-005 on the msteams test are blocked rows. One row for the Thens, BOTH tests in it.
        a, _ = story_of(M.shape_a(), "a")
        for then in (1, 2):
            got = a.then_outcome("TC-005", then, "R-5")
            check_eq(f"K5 (a) A: TC-005 Then {then} is blocked", got.get("result"), "blocked")
            check_eq("K5 (a) A: ... both the generic and the msteams test are in `tests`", ids(got), {M.G5, M.MS})
            check_eq("K5 (a) A: ... T1 verbatim, the blocker with its title, no instance id, no bug", got.get("basis"), T1_TC004)
        for then in (1, 2):
            check_eq(f"K5 (a) A: TC-004 Then {then} (red by its own row) reads as today",
                     a.then_outcome("TC-004", then, "R-4"), a.instance_outcome(M.MS, "TC-004", "R-4"))
        check_eq("K5 (a) A: TC-004 Then 2 is the red run, not T1/T2", a.then_outcome("TC-004", 2, "R-4").get("basis"),
                 "red run, triage not recorded: no reason recorded")
        row = blocked_row(M.shape_a(), "TC-005", 1)
        check_eq("K5 unresolved_outcome: a blocked_by_check row is `blocked`, basis T1",
                 (a.unresolved_outcome(row, "TC-005", "R-5")["result"], a.unresolved_outcome(row, "TC-005", "R-5")["basis"]),
                 ("blocked", T1_TC004))
        check_eq("K5 blocked_outcome: `tests` is the test that holds the Then (the row's instance), nothing else",
                 ids(a.blocked_outcome(row, "TC-005", "R-5")), {M.MS})
        check_eq("K5 blocked_outcome: `tests` carries the file too",
                 a.blocked_outcome(row, "TC-005", "R-5")["tests"], [{"instance_id": M.MS, "file": M.MS_FILE}])
        check_eq("K5: the cache is ONE dict per Story", a.red_map() is a.red_map(), True)
        check_eq("K5: ... of the red instances", {k: [r["case"] for r in v] for k, v in a.red_map().items()}, {M.MS: ["TC-004"]})

        # the table: ONE row per Then group, TC-005 Thens 1-2 together, both tests in it (no row per partition)
        table = TR.build(a.root, a.artifacts)["rows"]
        mine = [r for r in table if r["case"] == "TC-005"]
        check_eq("K5 table A: one row for TC-005, Thens 1-2", [(r["then"], r["result"]) for r in mine], [([1, 2], "blocked")])
        check_eq("K5 table A: ... with both tests", {t["instance_id"] for t in mine[0]["tests"]}, {M.G5, M.MS})

        # a blocker named by the instance that is red reads as the case it is red for; one red for nothing reads without an id
        by_instance = edited(M.shape_a(), lambda s: blocked_row(s, "TC-005", 1).update(blocking_check=M.MS))
        got = story_of(by_instance, "a-inst")[0].then_outcome("TC-005", 1, "R-5")
        check_eq("K5 T1: `blocking_check` an instance id -> the case that instance is red for", got.get("basis"), T1_TC004)
        nobody = edited(M.shape_a(), lambda s: blocked_row(s, "TC-005", 1).update(blocking_check=M.G5))
        got = story_of(nobody, "a-nobody")[0].then_outcome("TC-005", 1, "R-5")
        check_eq("K5 T1: an instance red for nothing -> no id at all",
                 got.get("basis"), "not checked yet: in the same test, another check fails first; "
                                   "check this again once that is fixed")

        # (b) Shape B: the Thens of TC-005 are COVERED on the msteams test, which is red for TC-004 - not proven (T2)
        b, _ = story_of(M.shape_b(), "b")
        for then in (1, 2):
            got = b.then_outcome("TC-005", then, "R-5")
            check_eq(f"K5 (b) B: TC-005 Then {then} is blocked", got.get("result"), "blocked")
            check_eq("K5 (b) B: ... T2 verbatim", got.get("basis"), T2_TC004_THEN2)
            check_eq("K5 (b) B: ... both tests", ids(got), {M.G5, M.MS})
        check_eq("K5 (b) B: the stopped outcome alone names the stopped test",
                 ids(b.stopped_outcome(M.MS, b.red_map()[M.MS], "TC-005", "R-5")), {M.MS})
        check_eq("K5 (b) B: TC-004 Then 2 (its own row) reads as today",
                 b.then_outcome("TC-004", 2, "R-4"), b.instance_outcome(M.MS, "TC-004", "R-4"))
        check_not_in("K5 (b) B: TC-004's own Then is not `stopped`", "not proven", b.then_outcome("TC-004", 2, "R-4").get("basis"))

        # (c) N1: with a stale TC-005 row (no `thens`) the msteams test is red by TC-005's OWN row as well
        stale, _ = story_of(M.with_stale_rows(M.shape_b(), ["TC-005"]), "stale")
        check_eq("K5 (c) N1: msteams is red by both rows", [r["case"] for r in stale.red_map()[M.MS]], ["TC-004", "TC-005"])
        check_eq("K5 (c): TC-004 Then 2 reads as today (instance_outcome), not T2",
                 stale.then_outcome("TC-004", 2, "R-4"), stale.instance_outcome(M.MS, "TC-004", "R-4"))
        for then in (1, 2):
            got = stale.then_outcome("TC-005", then, "R-5")
            check(f"K5 (c): TC-005 Then {then} is not `pass`", got.get("result") != "pass", str(got))
            check_not_in("K5 (c): ... and not `stopped at TC-005`", "stopped at", got.get("basis"))
            check_eq("K5 (c): ... the msteams test reads as today (its own row)", got,
                     TR._merge_outcomes([stale.instance_outcome(i, "TC-005", "R-5") for i in (M.G5, M.MS)]))

        # (d) a current result `passed` on msteams: not red by D1, so no T2; `error`: not red either, never `pass`
        passed, _ = story_of(M.with_status(M.shape_b(), M.MS, "passed"), "passed")
        check_eq("K5 (d): the report says passed -> nobody is red", passed.red_map(), {})
        got = passed.then_outcome("TC-005", 1, "R-5")
        check_eq("K5 (d): ... TC-005 Then 1 reads as today", got,
                 TR._merge_outcomes([passed.instance_outcome(i, "TC-005", "R-5") for i in (M.G5, M.MS)]))
        check_not_in("K5 (d): ... not T2", "stopped at", got.get("basis"))
        green = edited(M.with_status(M.shape_b(), M.MS, "passed"),
                       lambda s: s["manifest"]["tests"][0].update(status="green"))
        got = story_of(green, "green")[0].then_outcome("TC-005", 1, "R-5")
        check_eq("K5 (d): a green msteams test (manifest and report) is `pass` on both tests", (got.get("result"), ids(got)),
                 ("pass", {M.G5, M.MS}))
        errored = edited(M.with_status(M.shape_b(), M.MS, "error"), lambda s: s["manifest"]["tests"][0].pop("status"))
        er, _ = story_of(errored, "error")
        got = er.then_outcome("TC-005", 1, "R-5")
        check_eq("K5 edge: an instance red by `error` is not red by D1", er.red_map(), {})
        check("K5 edge: ... and the Then is red as today (`instance_outcome`), never `pass`",
              got.get("result") == "blocked" and "stopped at" not in got.get("basis"), str(got))
        check_eq("K5 edge: ... exactly what instance_outcome says",
                 got, TR._merge_outcomes([er.instance_outcome(i, "TC-005", "R-5") for i in (M.G5, M.MS)]))

        # edge: a bug on another instance of the same case still wins over `blocked`
        def a_bug(s: dict) -> None:
            for row in s["report"]["current_results"]:
                if row["instance_id"] == M.G5:
                    row["status"] = "failed"
        bugged, _ = story_of(edited(M.shape_a(), a_bug), "bug")
        bugged.bugs = [{"id": "BUG-1", "title": "The generic copy is lost", "cases": ["TC-005"], "requirements": ["R-5"],
                        "filed": True, "state": "confirmed"}]
        got = bugged.then_outcome("TC-005", 1, "R-5")
        check_eq("K5 edge: `bug` of another instance of the case wins over `blocked`", (got.get("result"), got.get("bug")),
                 ("bug", "BUG-1"))
        check_eq("K5 edge: ... and both tests stay in `tests`", ids(got), {M.G5, M.MS})

        # edge: a blocked row with no instance -> `tests: []`, `blocked`; the partition rule does not drop the Then
        def no_instance(s: dict) -> None:
            blocked_row(s, "TC-005", 1)["instance_id"] = None
            s["manifest"]["then_bindings"] = [x for x in s["manifest"]["then_bindings"]
                                              if (x["case"], x["then"], x["instance_id"]) != ("TC-005", 1, M.G5)]
            s["manifest"]["unresolved"].append({"case": "TC-005", "reason": "handed_to_person",
                                                "partitions": ["P-android"], "detail": "run it on a phone"})
        null, _ = story_of(edited(M.shape_a(), no_instance), "null")
        got = null.then_outcome("TC-005", 1, "R-5")
        check_eq("K5 edge: a blocked row with no instance -> `blocked`, no test (a Then without a test never reads as checked)",
                 (got.get("result"), got.get("tests")), ("blocked", []))
        check_eq("K5 edge: ... T1 still", got.get("basis"), T1_TC004)
        check_eq("K5 edge: ... blocked_outcome of that row", null.blocked_outcome(
            blocked_row(edited(M.shape_a(), no_instance), "TC-005", 1), "TC-005", "R-5")["tests"], [])

        # edge: a row without `thens` -> T2 without "Then m" (no number is invented)
        def no_thens(s: dict) -> None:
            s["manifest"]["unresolved"][0].pop("thens")
        nothens, _ = story_of(edited(M.shape_b(), no_thens), "nothens")
        got = nothens.then_outcome("TC-005", 1, "R-5")
        check_eq("K5 edge: no `thens` -> T2 names the case alone",
                 got.get("basis"), "not proven: the test stopped at TC-004 (The check TC-004 of the moved integration) "
                                   "before reaching this check; check this again once that is fixed")
        check_not_in("K5 edge: ... and invents no Then number", "Then", got.get("basis"))

        # edge: the title cannot be read -> `the check this one depends on (TC-004)`, the id ONCE
        for name, story, then in (("t1", M.shape_a(), "T1"), ("t2", M.shape_b(), "T2")):
            untitled, _ = story_of(story, "untitled-" + name, drop_case_file="TC-004")
            got = untitled.then_outcome("TC-005", 1, "R-5")
            check_in(f"K5 edge: {then} with an unreadable title", "the check this one depends on (TC-004)", got.get("basis"))
            check_eq("K5 edge: ... the id reaches the person once", got.get("basis").count("TC-004"), 1)

        # AR-13: the red map is read ONCE per Story, by the one reader, with the report
        calls, real = [], AC.red_by_requirement
        AC.red_by_requirement = lambda *a, **k: (calls.append(k.get("report")), real(*a, **k))[1]
        try:
            fresh, task = story_of(M.shape_b(), "once")
            TR.build(fresh.root, task)
            counted = TR.Story(fresh.root, task)
            for case in ("TC-004", "TC-005", "TC-006"):
                for then in (1, 2):
                    counted.then_outcome(case, then, "R-5")
        finally:
            AC.red_by_requirement = real
        check_eq("K5 AR-13: `red_by_requirement` is called once per Story (two Stories above), with `report=`",
                 [r is not None for r in calls], [True, True])

        # K9 (D8, FR-6): T1 and T2 on the 12586-shaped fixture, through the one checker of the rules
        words = {"T1": T1_TC004, "T2": T2_TC004_THEN2,
                 "T2 no Then": "not proven: the test stopped at TC-004 (The check TC-004 of the moved integration) before "
                               "reaching this check; check this again once that is fixed",
                 "T1 no case": "not checked yet: in the same test, another check fails first; check this again once that is fixed",
                 "T1 unreadable title": f"not checked yet: in the same test, {a._named('TC-999')} fails first; "
                                        "check this again once that is fixed"}
        for label, text in words.items():
            check_eq(f"K9 {label}: human_text.problems(text, kind='report') is empty", human_text.problems(text, kind="report"), [])
        check_eq("K9: the story's own words are exactly T1 / T2", (a.then_outcome("TC-005", 1, "R-5")["basis"],
                                                                 b.then_outcome("TC-005", 1, "R-5")["basis"]),
                 (words["T1"], words["T2"]))
    finally:
        cleanup(top)


def unrun_instance_in_a_then() -> None:
    """HF2-6 K4 (RD1-8): an instance of a Then that the run recorded nothing for is `not run`, and the Then reads the WORST of its
    instances. On the 12586-shaped fixture the generic test G5 has its row removed: beside a `blocked_by_check` row it stays
    `blocked`; beside an instance red for another case's requirement the Then is `stopped_outcome` (3c2), not `not run` and not
    `pass`; beside a green instance the Then is `not run` and both tests stay in `tests`. Kills: a `pass` for an instance
    with no row (m1), the handed branch reading `not run` (m4)."""
    import copy
    import test_mixed_then_outcomes as M
    from harness import temp_dir
    top = temp_dir("qa-trace-unrun-")

    def without_row(story: dict, iid: str) -> dict:
        out = copy.deepcopy(story)
        out["report"]["current_results"] = [r for r in out["report"]["current_results"] if r["instance_id"] != iid]
        return out

    try:
        a, _ = mixed_story_of(top, without_row(M.shape_a(), M.G5), "a")
        check_eq("K4 the instance with no row is `not run`, in the words of the ledger",
                 (a.instance_outcome(M.G5, "TC-005", "R-5")["result"], a.instance_outcome(M.G5, "TC-005", "R-5")["basis"]),
                 ("not run", "no result for this test in run-report.json"))
        got = a.then_outcome("TC-005", 1, "R-5")
        check_eq("K4 a `blocked_by_check` Then with an unrun covered instance reads `blocked` (the worst), both tests in it",
                 (got["result"], {t["instance_id"] for t in got["tests"]}), ("blocked", {M.G5, M.MS}))
        b, _ = mixed_story_of(top, without_row(M.shape_b(), M.G5), "b")
        got = b.then_outcome("TC-005", 1, "R-5")
        check_eq("K4 an instance red for ANOTHER case beside an unrun one: `stopped_outcome` (3c2)",
                 (got["result"], got["basis"]), ("blocked", T2_TC004_THEN2))
        green = M.with_status(without_row(M.shape_b(), M.G5), M.MS, "passed")
        green["manifest"]["tests"][0]["status"] = "green"   # the fixture's MS says `red`: a manifest `red` refuses a green row
        c, _ = mixed_story_of(top, green, "c")
        got = c.then_outcome("TC-005", 1, "R-5")
        check_eq("K4 an unrun instance beside a green one in one Then: `not run`, both tests in it",
                 (got["result"], got["basis"], {t["instance_id"] for t in got["tests"]}),
                 ("not run", "no result for this test in run-report.json", {M.G5, M.MS}))
        check_eq("K4 ... and the green one alone is a `pass` (the control: the join finds its row)",
                 c.instance_outcome(M.MS, "TC-005", "R-5")["result"], "pass")
        check_eq("K4 ... the whole requirement x case row of the table is `not run` too",
                 [r["result"] for r in trace_rows(c) if r["case"] == "TC-005"], ["not run"])
    finally:
        cleanup(top)


def trace_rows(story) -> list:
    """The rows of the trace table the `Story` is the reading of."""
    import traceability as TR
    return TR.build(story.root, story.artifacts)["rows"]


def legacy_join_of_run_rows() -> None:
    """HF2-6 section 11 P1 (the critic's probe): the `after-checks` fixture's TC-001 has no identity of its own (a marker that is
    the case) and its run row names the case, so the join is the legacy step of `case_stamp.run_row_for`: the only live entry
    of the case and the only current row of the case. It keeps its `pass` (the requirements keep `proven: 2`); a SECOND live
    entry of the case without a row reads `not run` for BOTH - no entry inherits the case's row. Kills: the legacy step
    without its one-entry condition (m9)."""
    import shutil
    import traceability as TR
    from harness import FIXTURES, temp_dir
    root = temp_dir("qa-trace-legacy-")
    task = root / "QA-1"
    shutil.copytree(FIXTURES / "after-checks", task)
    try:
        def table() -> dict:
            return {r["requirement"] + "/" + r["case"]: r for r in TR.build(task.parents[1], task)["rows"]}
        check_eq("K-legacy control: the fixture's TC-001 has no identity of its own and keeps `pass`",
                 table()["R-1/TC-001"]["result"], "pass")
        path = task / "work" / "automation-manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        first = manifest["tests"][0]
        second = dict(first, instance_id="second_of_tc001", status="green")
        manifest["tests"].append(second)
        path.write_text(json.dumps(manifest), encoding="utf-8")
        story = TR.Story(task.parents[1], task)
        import contract as C
        ids = [C.test_instance_id(first), "second_of_tc001"]
        check_eq("K-legacy a second live entry of the case, no row of its own: BOTH read `not run`",
                 [story.instance_outcome(i, "TC-001", "R-1")["result"] for i in ids], ["not run", "not run"])
        check_eq("K-legacy ... and the table row of the case is `not run`", table()["R-1/TC-001"]["result"], "not run")
    finally:
        cleanup(root)


def triage_joins_through_the_run_row() -> None:
    """HF2-6 fix round 2 (defect_found on 6a, found by 6b; FR-10, AR-13): `Story.triage_for` and `Story.attempts` find an
    instance's triage row and attempts through the SAME join as its run row (`case_stamp.run_row_for`), so the trace and the
    ledger read one fact one way. Before, both looked the instance up by its exact manifest id: a `ti_...` hash against the
    runner's function id never met, and the trace said "triage not recorded" beside a ledger that reddened the test APP_BUG.
    Keys T1-T5. T3 is the 6a neighbour veto: `TestB::t` is not `TestA::t`, so its triage row is never the verdict of `TestA`.
    Kills: `triage_for` asking the exact manifest id only (m1: T1, T2, T5); a joined row taken without the neighbour veto
    (m2: T3)."""
    import shutil
    import contract as C
    import ledger as L
    import traceability as TR
    from harness import FIXTURES, temp_dir
    root = temp_dir("qa-trace-triage-join-")
    task = root / "QA-1"
    shutil.copytree(FIXTURES / "after-checks", task)
    hashed = "ti_0123456789abcdef0001"
    test_id = "tests/test_coupon.py::test_cap_rejected"
    try:
        def edit(rel: str, change) -> None:
            data = json.loads((task / rel).read_text(encoding="utf-8"))
            change(data)
            (task / rel).write_text(json.dumps(data), encoding="utf-8")

        def setup(manifest_fields: dict, run_fields: dict, triage_rows: list) -> None:
            edit("work/automation-manifest.json", lambda m: m["tests"][0].update(status="green", **manifest_fields))
            edit("work/run-report.json", lambda r: r.update(results=[dict(
                {"case": "TC-001", "result": "failed", "attempt_id": "a1"}, **run_fields)]))
            edit("work/triage.json", lambda t: t.update(triage=[dict(row, attempt_id="a1") for row in triage_rows]))

        def reads(key: str = hashed):
            """(Story, entry, the verdict `triage_for` gives for the run row `instance_outcome` hands it)."""
            story = TR.Story(task.parents[1], task)
            entry = story.instances[key]
            joined = story._red_run_row(key, entry)
            return story, entry, str(story.triage_for(key, entry, joined).get("verdict") or "")

        def ledger_state(story, entry) -> str:
            report = C.load_json(task / "work/run-report.json")
            return L.test_state(entry, report, story.triage, task, story.manifest)[0]

        # T1: the `after-checks` fixture after `red(task)` (test_third_verdict): TC-001's row is `failed` and the analyst's row
        # names the run's test id; the manifest row has an identity of its own that is a hash (no `instance_id`, no `test`).
        edit("work/run-report.json", lambda r: r["results"][0].update(result="failed", attempt_id="a1"))
        edit("work/triage.json", lambda t: t["triage"].append(
            {"instance_id": test_id, "attempt_id": "a1", "verdict": "APP_BUG", "evidence": "evidence/sanity-20260911-105500.json"}))
        key = C.test_instance_id(TR.Story(task.parents[1], task).manifest["tests"][0])
        story, entry, got = reads(key)
        check_eq("T1 after `red`: the trace's triage row for TC-001 is the analyst's APP_BUG row", got, "APP_BUG")
        check_eq("T1 ... and the ledger reds the same test APP_BUG: one fact, one reading (FR-10)",
                 ledger_state(story, entry), "failed:APP_BUG")
        # HF2-6 fix round 3 (t-128 fork, decided (a)): no bug record -> the word stays `blocked`, but the basis tells the truth
        # about the triage the ledger reads. Kills: the old basis kept (m1).
        check_eq("T1 ... and the table row says so: `blocked`, triaged APP_BUG, no bug filed (not `triage not recorded`)",
                 story.instance_outcome(key, "TC-001", "R-1")["basis"],
                 "red run, triaged APP_BUG: no reason recorded; bug not filed")
        edit("work/triage.json", lambda t: t["triage"].pop())
        check_eq("T1 control: the same story without the triage row has no verdict for it", reads(key)[2], "")
        check_in("T1 control: ... and the table row says `triage not recorded`", "triage not recorded",
                 TR.Story(task.parents[1], task).instance_outcome(key, "TC-001", "R-1")["basis"])
        # t-1338 Q1: the assert-stricter word has no bug by definition, so its table row must not say "bug not filed" beside the
        # "Left with you" line of the same report (FR-10); the row stays `blocked` and names the person's decision instead.
        edit("work/triage.json", lambda t: t["triage"].append(
            {"instance_id": test_id, "attempt_id": "a1", "verdict": C.TRIAGE_STRICTER_VERDICT, "reason": "same keys without the change",
             "evidence": "evidence/sanity-20260911-105500.json"}))
        said = TR.Story(task.parents[1], task).instance_outcome(key, "TC-001", "R-1")
        check_eq("T1 Q1: the stricter word keeps the table word `blocked`", said["result"], "blocked")
        check_in("T1 Q1: ... names the word and the analyst's reason", f"triaged {C.TRIAGE_STRICTER_VERDICT}: same keys without", said["basis"])
        check_not_in("T1 Q1: ... and does not claim a bug that was not filed", "bug not filed", said["basis"])
        check_in("T1 Q1: ... it says the decision is the person's", "left with you", said["basis"])
        edit("work/triage.json", lambda t: t["triage"].pop())
        # T2: a hash in the manifest, the function id in the run row AND in the triage row (the shape of a real runner)
        setup({"instance_id": hashed, "test": test_id}, {"test": test_id, "instance_id": "test_cap_rejected"},
              [{"instance_id": "test_cap_rejected", "verdict": "APP_BUG"}])
        story, entry, got = reads()
        check("T2 precondition: the exact join misses (hash against function id)", hashed not in story.results, str(list(story.results)))
        check_eq("T2 a triage row carrying the function id is joined to the manifest's `ti_...` instance", got, "APP_BUG")
        check_eq("T2 ... and the ledger agrees", ledger_state(story, entry), "failed:APP_BUG")
        # T3: a triage row of ANOTHER test with the same `::` tail is not joined (the 6a neighbour veto)
        other = "tests/test_coupon.py::TestB::test_cap_rejected"
        setup({"instance_id": hashed, "test": "tests/test_coupon.py::TestA::test_cap_rejected"},
              {"test": other, "instance_id": "TestB.test_cap_rejected"},
              [{"instance_id": "TestB.test_cap_rejected", "test": other, "verdict": "APP_BUG"}])
        story, entry, got = reads()
        check("T3 precondition: the red row is a neighbour's - `red_run_for` finds it by the shared tail, `run_row_for` vetoes it",
              story._red_run_row(hashed, entry) is not None and story._run_row(entry) is None,
              str((story._red_run_row(hashed, entry), story._run_row(entry))))
        check_eq("T3 the neighbour's APP_BUG row is not TestA's verdict", got, "")
        check("T3 ... and the ledger does not red TestA with it either", ledger_state(story, entry) != "failed:APP_BUG",
              ledger_state(story, entry))
        check_in("T3 ... the table says what it said: triage not recorded",
                 "triage not recorded", story.instance_outcome(hashed, "TC-001", "R-1")["basis"])
        edit("work/automation-manifest.json", lambda m: m["tests"][0].update(test=other))
        check_eq("T3 control: the same rows with TestB's own manifest row ARE joined", reads()[2], "APP_BUG")
        # T4: no matching row at all: "triage not recorded", as today (a triage row of a test that did not run is no verdict)
        setup({"instance_id": hashed, "test": test_id}, {"test": test_id, "instance_id": "test_cap_rejected"},
              [{"instance_id": "tests/test_other.py::test_other", "verdict": "APP_BUG"}])
        story, entry, got = reads()
        check_eq("T4 a triage row naming another test: no verdict", got, "")
        check_in("T4 ... and the table keeps its words", "triage not recorded", story.instance_outcome(hashed, "TC-001", "R-1")["basis"])
        # T5: the attempts of an instance are found through the same join - the stand's "fails n of n"
        setup({"instance_id": hashed, "test": test_id}, {"test": test_id, "instance_id": "test_cap_rejected"},
              [{"instance_id": "test_cap_rejected", "verdict": "ENV_ISSUE", "owner": "user"}])
        edit("work/run-report.json", lambda r: r["results"].append(
            {"test": test_id, "instance_id": "test_cap_rejected", "case": "TC-001", "result": "failed", "attempt_id": "a2"}))
        edit("work/triage.json", lambda t: t["triage"][0].update(attempt_id="a2"))   # the current attempt's verdict
        story, entry, got = reads()
        check_eq("T5 an ENV_ISSUE row joined through the run row", got, "ENV_ISSUE")
        check_eq("T5 both attempts of the instance are counted under its manifest id", story.attempts(hashed), (2, 2))
        check_in("T5 ... and the stand's words use them", "fails 2 of 2 on the stand", story.instance_outcome(hashed, "TC-001", "R-1")["basis"])
        edit("work/automation-manifest.json", lambda m: m["tests"][0].update(test="tests/test_coupon.py::TestA::test_cap_rejected"))
        edit("work/run-report.json", lambda r: [row.update(test=other, instance_id="TestB.test_cap_rejected") for row in r["results"]])
        check_eq("T5 control: a neighbour's attempts are not the instance's", TR.Story(task.parents[1], task).attempts(hashed), (0, 0))
    finally:
        cleanup(root)


def answered_suffix_needs_a_standing_answer() -> None:
    """HF2-6 K6: `mark_answered` appends the gate A suffix only for an answer that still stands (`question_register.settled`):
    an answer to an earlier wording of the question (`changed_since_answer: True`) is no answer. `None` (a record that stores no
    hash) holds, as it did. Kills: `mark_answered` by the raw `status` (m7)."""
    import traceability as TR
    base = {"id": "Q1", "status": "answered", "where": "gate A", "line": "Q1: a", "reading": "a"}
    text = "Then rests on Q1 (owner decides)"
    for flag, suffixed in ((None, True), (False, True), (True, False)):
        got = TR.mark_answered(text, [dict(base, changed_since_answer=flag)])
        check_eq(f"K6 gate A answer, changed_since_answer={flag!r}: " + ("the suffix" if suffixed else "no suffix"),
                 got, text + (TR.ANSWERED_SUFFIX if suffixed else ""))
    check_eq("K6 a changed answer beside another standing one: no suffix (a text citing a question that does not stand gets none)",
             TR.mark_answered("rests on Q1 and Q2", [dict(base, changed_since_answer=True), dict(base, id="Q2", line="Q2: b")]),
             "rests on Q1 and Q2")
    check_eq("K6 the plan spelling (`Q-R14`) of a changed answer: no suffix",
             TR.mark_answered("rests on Q-R14", [dict(base, line="Q1 / Q-R14: reading a", changed_since_answer=True)]), "rests on Q-R14")


def a_case_taken_by_hand_has_an_outcome() -> None:
    """C5-4 (P21): a manual-agent case the person took by hand (`handed`) and that has no run result reads the gap
    `unresolved:handed_to_person` (kind `handed`, `after_checks`), where it read `not_in_manifest`. The chain keeps its order: any
    run result, a manifest `unresolved[]` row and a manual-human case are decided ABOVE the hand-off (an observed failure is older
    than a hand-off); a lane other than manual-agent, or no `handed`, keeps the gap it had.
    Kills: the branch moved above `if case in results` (K-C54.1), the lane test dropped (K-C54.3), `handed` ignored (K-C54.0/.4)."""
    import shutil
    import manual_capture as MC
    from harness import FIXTURES, temp_dir
    agent = {"disposition": "manual-agent"}
    empty = {"tests": [], "unresolved": []}
    hand = frozenset({"TC-1"})

    def gap(row=agent, manifest=empty, report=None, handed=hand, case="TC-1"):
        return T.gap_of_case(case, row, manifest, report or {}, handed=handed)
    check_eq("K-C54.0 a handed manual-agent case with no result: the person's line", gap(), "unresolved:handed_to_person")
    check_eq("K-C54.0 ... and no outcome, with a detail that says so", T.outcome_for_case("TC-1", agent, empty, {}, handed=hand),
             ("", "TC-1: taken by hand by the person"))
    check_eq("K-C54.0 control: the same case not handed keeps its old gap", gap(handed=frozenset()), "not_in_manifest")
    check_eq("K-C54.0 control: another case handed does not hand this one", gap(handed=frozenset({"TC-2"})), "not_in_manifest")
    check_eq("K-C54.1 a red result outranks the hand-off", T.outcome_for_case(
        "TC-1", agent, empty, {"manual_checks": [{"case": "TC-1", "result": "failed"}]}, handed=hand)[0], "executed_failed")
    check_eq("K-C54.1 a green result is no gap", gap(report={"manual_checks": [{"case": "TC-1", "result": "pass"}]}), "")
    check_eq("K-C54.1 a result that did not conclude keeps its own word", gap(
        report={"manual_checks": [{"case": "TC-1", "result": "inconclusive"}]}), "result:inconclusive")
    check_eq("K-C54.2 a manifest `blocked_by_env` row keeps its word", gap(
        manifest=dict(empty, unresolved=[{"case": "TC-1", "reason": "blocked_by_env"}])), "unresolved:blocked_by_env")
    # t-593 F-8 (b): only an `unresolved[]` row keeps its own gap (above the branch); a `tests[]` row with no result for the case is
    # BELOW it, so a handed case reads the hand-off, not `no_result` (the spec's position: the `if` sits above `not_in_manifest`/`no_result`)
    with_test = dict(empty, tests=[{"case": "TC-1", "file": "tests/a.py", "instance_id": "i1"}])
    check_eq("F-8 a handed case with a `tests[]` row and no result: the hand-off, not `no_result`", gap(manifest=with_test),
             "unresolved:handed_to_person")
    check_eq("F-8 control: the same row, not handed: `no_result`", gap(manifest=with_test, handed=frozenset()), "no_result")
    check_eq("K-C54.3 an automated lane is not the person's hand-off",gap(row={"disposition": "automate"}), "not_in_manifest")
    check_eq("K-C54.3 a row with no disposition is not either", gap(row={}), "not_in_manifest")
    check_eq("K-C54.3 manual-human keeps its own gap", gap(row={"disposition": "manual-human"}), "manual_human_no_package")

    # the walk reads the hand-off from the case's request.json (`check_delivery.person_check_rows`); every input that is not
    # exactly `refused.by == "person_checks"` stays the old gap - the direction of `no`
    root = temp_dir("qa-trace-by-hand-")
    task = root / "QA-1"
    shutil.copytree(FIXTURES / "after-checks", task)
    try:
        report = json.loads((task / "work" / "run-report.json").read_text(encoding="utf-8"))
        report["manual_checks"] = report["current_manual_checks"] = []
        (task / "work" / "run-report.json").write_text(json.dumps(report), encoding="utf-8")
        request = MC.case_root(task, "TC-002") / "request.json"
        request.parent.mkdir(parents=True, exist_ok=True)

        def row_gap() -> list:
            return next(r for r in T.walk(task)["rows"] if r["requirement"] == "R-2")["gaps"]
        check_eq("K-C54.4 control: no request.json - the old gap", row_gap(), [{"case": "TC-002", "gap": "not_in_manifest"}])
        for label, body, want in (
                ("person_checks", {"refused": {"by": "person_checks", "reason": "no stand"}}, "unresolved:handed_to_person"),
                ("left_unchecked", {"refused": {"by": "left_unchecked"}}, "not_in_manifest"),
                ("another case", {"refused": {"by": "Person_Checks"}}, "not_in_manifest"),
                ("a space", {"refused": {"by": " person_checks"}}, "not_in_manifest"),
                ("refused a string", {"refused": "person_checks"}, "not_in_manifest"),
                ("refused a list", {"refused": ["person_checks"]}, "not_in_manifest"),
                ("no refused", {"by": "person_checks"}, "not_in_manifest")):
            request.write_text(json.dumps(body), encoding="utf-8")
            check_eq(f"K-C54.4 request.json with {label}", row_gap()[0]["gap"], want)
        request.write_text("{not json", encoding="utf-8")
        check_eq("K-C54.4 an unreadable request.json: the old gap", row_gap()[0]["gap"], "not_in_manifest")
        request.write_text(json.dumps({"refused": {"by": "person_checks"}}), encoding="utf-8")
        check_eq("K-C54.4 `handed=frozenset()` given by the caller outranks the files", next(
            r for r in T.walk(task, handed=frozenset())["rows"] if r["requirement"] == "R-2")["gaps"][0]["gap"], "not_in_manifest")
        report["manual_checks"] = report["current_manual_checks"] = [
            {"case": "TC-002", "result": "failed", "attempt_id": "a1", "evidence_validated": True}]
        (task / "work" / "run-report.json").write_text(json.dumps(report), encoding="utf-8")
        row = next(r for r in T.walk(task)["rows"] if r["requirement"] == "R-2")
        check_eq("K-C54.1 walk: a red run beside a person_checks record is the red run's outcome", (row["outcome"], row["gaps"]),
                 ("executed_failed", []))
    finally:
        cleanup(root)


if __name__ == "__main__":
    main()
