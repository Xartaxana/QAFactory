"""case_stamp.py: the code-only `Automated` transition — stamped only when a case's manifest
evidence is whole (every covering instance green, critic-approved, red-probed), left alone
with a reason otherwise, idempotent across repeated runs, and wired into `finalize_task.py`
so nobody has to remember to run it (mirrors `critic_rollcall.py --apply-fixes`, the same
shape for the case critic's own verdict)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import case_stamp as S  # noqa: E402
import contract as C  # noqa: E402
import finalize_task as F  # noqa: E402
from hooklib import parse_frontmatter  # noqa: E402

GREEN_PROBE = {"mutation_kind": "real_behavior", "evidence_ref": "work/sensitivity-receipts/x.json"}
LIVE_PROBE = {"proof_level": "live", "mutation_kind": "assertion", "evidence_ref": "work/sensitivity-receipts/x.json"}


def init_project(root: Path) -> None:
    (root / "qa-factory").mkdir(parents=True, exist_ok=True)
    (root / "qa-factory" / "config.json").write_text(json.dumps({"schema_version": 1}), encoding="utf-8")


def write_case(path: Path, case_id: str, task: str, **fields) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = {"id": case_id, "title": "a case", "area": "core", "priority": "P2",
          "status": "Approved", "channel": "auto", "reuse_decision": "new",
          "updated": "2026-09-01", "task": task}
    fm.update(fields)
    header = "\n".join(f"{k}: {v}" for k, v in fm.items())
    path.write_text(f"---\n{header}\n---\n\n## Then\n1. it happens.\n", encoding="utf-8")
    return path


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def pin_all(task_root: Path, root: Path):
    result = run_script("case_versions.py", "--task-root", task_root, "--all", cwd=root)
    check("cases pin cleanly", result.returncode == 0, result.stdout + result.stderr)
    return result


def entry(case: str, instance: str, status: str = "green", verdict: str = "approved",
         probe: dict | None = None) -> dict:
    row = {"covers": [case], "instance_id": instance, "status": status, "critic_verdict": verdict}
    if probe is not None:
        row["probe"] = probe
    return row


def manifest(*tests, unresolved=None) -> dict:
    return {"tests": list(tests), "unresolved": list(unresolved or [])}


def run_green(task: Path, *instances: str) -> None:
    """`run-report.json` holding one GREEN result row per named instance. HF3-1 (finding "three readers of green without a run
    row", FR-59, FR-18): the manifest's `green` is the automator's word before the run, so a case stamps only when the run
    recorded a green row of its own for every instance - the fixtures that stamp therefore carry the run they stand for."""
    rows = [{"instance_id": name, "status": "passed"} for name in instances]
    # `current_results` is what the readers take; `results` is what the reducer (`finalize_task`) takes from a legacy report
    write_json(task / "work" / "run-report.json", {"current_results": rows, "results": rows})


def run_row_for_keys() -> None:
    """HF2-6 K3 (RD1-8): `run_row_for` - "what did the run record for THIS manifest instance", the join the table and the ledger
    share. ERROR DIRECTION: a miss reads `not run`, a match can lift a reading to a pass, so a row of ANOTHER test is never
    returned (every None input below), and the controls beside them show the join still finds the instance's own row.
    Kills: a join through `results.get` by function name (m2: the `ti_` control), step 3 without "no own row" (m3), a `::` tail
    accepted when two tests share it (m8: the `TestB::t` input), the legacy step without its one-entry condition (m9)."""
    def row(test_id: str, status: str = "passed", **fields) -> dict:
        return dict({"test_id": test_id, "status": status}, **fields)

    def found(entry, rows, entries=None):
        """The row `run_row_for` returns for `entry` over `rows` (key -> row), as its test id, or None."""
        got = S.run_row_for(entry, S.run_rows_index(rows, entries))
        return None if got is None else got.get("test_id") or got.get("instance_id")

    a_t, b_t = "a.py::t", "b.py::t"
    # -- every None input of M1 and of the critic's section 11 (P2, P3, P4)
    nothing = [
        ("a row of another test of the same file", {"instance_id": "test_p"},
         {"test_q": row("tests/a.py::test_q", instance_id="test_q")}),
        ("`x[multi]` for `x[json]`", {"test": "tests/a.py::x", "parameter": "json"},
         {"x[multi]": row("tests/a.py::x[multi]", instance_id="x[multi]")}),
        ("`x[unparseable]` (its test is the bare function) beside the row `x[json]`", {"test": "tests/a.py::x", "parameter": "unparseable"},
         {"x[json]": row("tests/a.py::x[json]", instance_id="x[json]")}),
        ("a row of another instance of the same case", {"instance_id": "test_one", "case": "TC-1", "test": "tests/a.py::test_one"},
         {"test_two": row("tests/a.py::test_two", instance_id="test_two", case="TC-1")}),
        ("a row with no ids at all", {"instance_id": "", "test": None, "selector": ""}, {"k": {"status": "passed"}}),
        ("a `::` tail two tests share: TestA::t against the row of TestB::t (by id)", {"test": "a.py::TestA::t"},
         {"a.py::TestB::t": row("a.py::TestB::t")}),
        ("... and the same when the report keyed the row by the function name", {"test": "a.py::TestA::t"},
         {"t": row("a.py::TestB::t")}),
        ("`a.py::t` against the row of `b.py::t` (by id)", {"test": a_t}, {b_t: row(b_t)}),
        ("... and the same keyed by the function name", {"test": a_t}, {"t": row(b_t)}),
        ("a bare `t` when TWO tests answer to the tail `t`", {"instance_id": "t"}, {a_t: row(a_t), b_t: row(b_t)}),
        ("a bare `x` that two tests answer to must not stand for a third test's parameter row (step 3 needs NO row of its own)",
         {"instance_id": "x"}, {"a.py::x": row("a.py::x"), "b.py::x": row("b.py::x"), "c.py::x[p]": row("c.py::x[p]")}),
        ("a stale row", {"instance_id": "test_s"}, {"test_s": row("tests/a.py::test_s", instance_id="test_s", stale=True)}),
        ("a red-probe row", {"instance_id": "test_s"}, {"test_s": row("tests/a.py::test_s", "failed", instance_id="test_s", red_probe=True)}),
        ("a diagnostic row", {"instance_id": "test_s"}, {"test_s": row("tests/a.py::test_s", instance_id="test_s", purpose="diagnostic")}),
        ("a baseline row", {"instance_id": "test_s"}, {"test_s": row("tests/a.py::test_s", instance_id="test_s", evidence_phase="baseline")}),
    ]
    for label, entry, rows in nothing:
        check_eq(f"K3 None: {label}", found(entry, rows), None)
    # -- the controls: the join still finds what is the instance's own
    own = {"x[json]": row("tests/a.py::x[json]", instance_id="x[json]"), "x[multi]": row("tests/a.py::x[multi]", "failed", instance_id="x[multi]")}
    controls = [
        ("the exact id", {"instance_id": "test_x"}, {"test_x": row("tests/a.py::test_x", instance_id="test_x")}, "tests/a.py::test_x"),
        ("a hash identity against the runner's function id (dashboard's tolerant rule; `tests.a` is `tests/a.py`)",
         {"instance_id": "ti_0123456789abcdef0002", "test": "tests/a.py::test_y"}, {"test_y": row("tests.a::test_y")}, "tests.a::test_y"),
        ("its own `x[json]` beside a red `x[multi]`", {"test": "tests/a.py::x", "parameter": "json"}, own, "tests/a.py::x[json]"),
        ("a tail that only ONE test has, the manifest naming the bare function", {"instance_id": "t"}, {a_t: row(a_t)}, a_t),
        ("the same tests when both rows exist: the entry's own place decides", {"test": b_t}, {a_t: row(a_t), b_t: row(b_t)}, b_t),
        ("a manifest `test` that omits the class (`a.py::t`) against `a.py::TestA::t`", {"test": a_t},
         {"a.py::TestA::t": row("a.py::TestA::t")}, "a.py::TestA::t"),
    ]
    for label, entry, rows, want in controls:
        check_eq(f"K3 row: {label}", found(entry, rows), want)
    # -- P3: a bare function with several parameter rows reads its WORST row, whatever the order of the report
    bare = {"test": "tests/a.py::x"}
    for word in ("skipped", "partial", "failed"):
        for first in (True, False):
            pair = [("x[a]", row("tests/a.py::x[a]", instance_id="x[a]")), ("x[b]", row("tests/a.py::x[b]", word, instance_id="x[b]"))]
            got = S.run_row_for(bare, S.run_rows_index(dict(pair if first else pair[::-1])))
            check_eq(f"K3 P3: `x[a]` passed + `x[b]` {word}, {'in' if first else 'against the'} report order: the {word} row",
                     got and got.get("status"), word)
    both = S.run_row_for(bare, S.run_rows_index({"x[a]": row("tests/a.py::x[a]", instance_id="x[a]"),
                                                "x[b]": row("tests/a.py::x[b]", instance_id="x[b]")}))
    check("K3 P3 control: every parameter green -> a green row", both is not None and both["status"] == "passed", str(both))
    own_row = S.run_row_for(bare, S.run_rows_index({"x": row("tests/a.py::x", instance_id="x"),
                                                   "x[a]": row("tests/a.py::x[a]", "skipped", instance_id="x[a]")}))
    check_eq("K3 control: a bare function with its OWN row reads that row, not a skipped parameter", own_row and own_row["status"], "passed")
    # -- P1: the legacy step - an entry with no identity of its own, the only live entry of its case, the only row of the case
    legacy = {"case": "TC-1", "marker": "TC-1", "file": "tests/a.py"}
    one = {"k": row("tests/a.py::test_cap", case="TC-1")}
    check_eq("K-legacy control: the only entry and the only row of the case are joined", found(legacy, one, [legacy]), "tests/a.py::test_cap")
    twin = dict(legacy, instance_id="second")
    check_eq("K-legacy: a SECOND live entry of the case - the first does not take the row", found(legacy, one, [legacy, twin]), None)
    check_eq("K-legacy: ... nor the second", found(twin, one, [legacy, twin]), None)
    check_eq("K-legacy: two rows of the case join nothing", found(legacy, dict(one, k2=row("tests/a.py::test_two", case="TC-1")), [legacy]), None)
    check_eq("K-legacy: an entry that names its test has an identity of its own - the row of the case is not its row",
             found(dict(legacy, test="tests/a.py::test_mine"), one, [dict(legacy, test="tests/a.py::test_mine")]), None)
    check_eq("K-legacy: no manifest entries given, no legacy step", found(legacy, one), None)
    check_eq("K-legacy: a row of another case is not the case's", found(legacy, {"k": row("tests/a.py::test_cap", case="TC-2")}, [legacy]), None)
    # -- edge: nothing, or garbage, in; None out, no exception
    check_eq("K3 edge: no entry, no index, an index of nothing: None",
             [S.run_row_for(e, i) for e, i in ((None, S.run_rows_index(one)), ({"instance_id": "k"}, None), ({"instance_id": "k"}, {}),
                                              ({"instance_id": "k"}, S.run_rows_index({})), ({"instance_id": "k"}, S.run_rows_index(None)),
                                              ("x", S.run_rows_index(one)), ([], S.run_rows_index(one)))], [None] * 7)
    check_eq("K3 the index drops stale and probe rows once for both joins", sorted(S.run_rows_index(
        {"a": row("t::a"), "b": row("t::b", stale=True), "c": row("t::c", "failed", red_probe=True)})["rows"]), ["a"])


def instance_hold_keys() -> None:
    """HF3-1 A-K1 (AR-13, FR-59, FR-18): `instance_hold` - THE one predicate the stamp, the coverage map and gate B ask. `""` = can
    carry its case's stamp; else the first of `not_green` / `not_run` / `not_approved`. ERROR DIRECTION: a gate, so "hold" is the
    safe side; a row of another test, a word nobody knows and a missing row are never green. Kills: `not_run` never returned (m1),
    `skipped` read as green (m6), `approved_with_fixes` outside `APPROVING` (m3: the second row of the verdict table)."""
    def row(status: str = "passed", test_id: str = "tests/a.py::test_x", **fields) -> dict:
        return dict({"test_id": test_id, "instance_id": "test_x", "status": status}, **fields)

    def hold(rows, **fields) -> str:
        e = dict({"instance_id": "test_x", "status": "green", "critic_verdict": "approved"}, **fields)
        return S.instance_hold(e, S.run_rows_index(rows))

    own = {"test_x": row()}
    table = [
        # (label, the rows the run holds, the entry fields that differ, the hold)
        ("green + a green row of its own + approved", own, {}, ""),
        ("`approved_with_fixes` is a legal verdict and stamps like `approved` (F-2)", own, {"critic_verdict": "approved_with_fixes"}, ""),
        ("`rejected` -> not_approved", own, {"critic_verdict": "rejected"}, "not_approved"),
        ("`unverified` -> not_approved", own, {"critic_verdict": "unverified"}, "not_approved"),
        ("a verdict nobody knows -> not_approved", own, {"critic_verdict": "mystery"}, "not_approved"),
        ("no verdict at all -> not_approved", own, {"critic_verdict": None}, "not_approved"),
        ("manifest `red` beside a green row -> not_green (a green row does not lift the manifest's word)", own, {"status": "red"}, "not_green"),
        ("manifest with no status -> not_green", own, {"status": None}, "not_green"),
        ("green + a red row (failed) -> not_green", {"test_x": row("failed")}, {}, "not_green"),
        ("green + an `error` row -> not_green", {"test_x": row("error")}, {}, "not_green"),
        ("green + NO row at all -> not_run", {}, {}, "not_run"),
        ("green + only the row of another instance -> not_run", {"test_y": row(instance_id="test_y", test_id="tests/a.py::test_y")}, {}, "not_run"),
        ("green + `skipped` -> not_run (m6: skipped is not a pass)", {"test_x": row("skipped")}, {}, "not_run"),
        ("green + `partial` whose raw status is passed -> not_run", {"test_x": row("partial", raw_status="passed")}, {}, "not_run"),
        ("green + `partial` with no raw status -> not_run", {"test_x": row("partial")}, {}, "not_run"),
        ("green + `partial` whose raw status is failed (the reducer's overwrite) -> not_green", {"test_x": row("partial", raw_status="failed")}, {}, "not_green"),
        ("green + a word nobody knows -> not_run", {"test_x": row("weird")}, {}, "not_run"),
        ("green + `expected_product_failure` (no runner writes it) -> not_run", {"test_x": row("expected_product_failure")}, {}, "not_run"),
        ("the first reason wins: manifest red AND unapproved -> not_green", own, {"status": "red", "critic_verdict": "rejected"}, "not_green"),
        ("the first reason wins: no row AND unapproved -> not_run", {}, {"critic_verdict": "rejected"}, "not_run"),
        ("a row of ANOTHER test sharing the function name (TestB::t for TestA::t) is not its run -> not_run",
         {"a.py::TestB::t": row(test_id="a.py::TestB::t", instance_id="a.py::TestB::t")}, {"instance_id": "a.py::TestA::t", "test": "a.py::TestA::t"}, "not_run"),
        ("a stale row is no run -> not_run", {"test_x": row(stale=True)}, {}, "not_run"),
    ]
    for label, rows, fields, want in table:
        check_eq(f"A-K1: {label}", hold(rows, **fields), want)
    # edge: garbage in, a hold out, no exception (AR-23: the empty outcome is named)
    check_eq("A-K1 edge: no entry, a bare string, a list, an empty dict: not_green, no exception",
             [S.instance_hold(e, S.run_rows_index(own)) for e in (None, "x", [], {})], ["not_green"] * 4)
    check_eq("A-K1 edge: no index / an empty one for a green approved entry: not_run (never ''; the run is unknown)",
             [S.instance_hold({"instance_id": "test_x", "status": "green", "critic_verdict": "approved"}, i)
              for i in (None, {}, S.run_rows_index({}), S.run_rows_index(None))], ["not_run"] * 4)
    # the verdict set follows the critic's contract (handoffs/s5-critic-to-automator.yaml:45) and the report's own pair (drift detector)
    import report_facts as RF
    check_eq("A-K1: `APPROVING` equals `report_facts.APPROVING` (the twin; a drift here splits the readers)", S.APPROVING, RF.APPROVING)


def one_predicate_stories(root: Path) -> None:
    """HF3-1 A-K3 (the legacy join, a TEMPORAL edge) and critic t-1254 B1 (the instance set of a case is the LIVE one)."""
    task = root / "qa-factory" / "artifacts" / "QA-970"
    for number in (1010, 1011, 1012, 1013):
        write_case(task / "work" / "test-cases" / "core" / f"TC-{number}.md", f"TC-{number}", "QA-970")
    pin_all(task, root)

    def legacy(case: str, **fields) -> dict:
        # a 0.10.x entry: no identity of its own (`legacy_identity_is_the_case`); its run row carries only the case
        return dict({"case": case, "marker": case, "file": "tests/a.py", "status": "green", "critic_verdict": "approved",
                     "probe": GREEN_PROBE}, **fields)

    row_of = lambda case, word="passed": {"test_id": "tests/a.py::test_cap_" + case[-4:], "status": word, "case": case}  # noqa: E731
    # A-K3: the only live entry of the case + the only current row of the case, green -> the row is its run: ready
    write_json(task / "work" / "automation-manifest.json", manifest(legacy("TC-1010"), legacy("TC-1011"), legacy("TC-1011", instance_id="second"),
                                                                    legacy("TC-1012"), legacy("TC-1013")))
    write_json(task / "work" / "run-report.json", {"current_results": [row_of("TC-1010"), row_of("TC-1011"), row_of("TC-1012", "failed")]})
    done = S.plan(task)
    ready = {item["case"] for item in done["ready"]}
    left = {item["case"]: item["why"] for item in done["left"]}
    check_eq("A-K3: a legacy entry that is the only live entry of its case, and the case's only green row: ready", "TC-1010" in ready, True)
    check_in("A-K3: a SECOND live entry of the case, no row of its own: both are not_run (no inheritance of the case's row)",
             "not_run:", left.get("TC-1011", ""))
    check_eq("A-K3: ... and both entries are named", left.get("TC-1011", "").count(","), 1)
    check_in("A-K3: a legacy entry whose only case row is RED holds the case as not_green (the legacy step finds the red row too)",
             "not_green:", left.get("TC-1012", ""))
    check_in("A-K3: a legacy entry with no row of its case at all: not_run", "not_run:", left.get("TC-1013", ""))
    # without the live entries in the index the legacy step is dead: every 0.10.x story would read "not run" (the run_rows_of key)
    live_entry = legacy("TC-1010")
    check_eq("A-K3: `run_rows_of(task, manifest)` carries the legacy step (the case's row is found)",
             S.run_row_for(live_entry, S.run_rows_of(task, C.load_json(task / "work" / "automation-manifest.json"))) is not None, True)
    check_eq("A-K3: ... `run_rows_of(task)` alone is the red-only index (no legacy step - stand_gaps' reader is unchanged)",
             S.run_row_for(live_entry, S.run_rows_of(task)), None)

    # B1: a dead row (`SUPERSEDED DUPLICATE`) is no instance of its case - it neither holds nor stamps (red included)
    task = root / "qa-factory" / "artifacts" / "QA-971"
    for number in (1020, 1021):
        write_case(task / "work" / "test-cases" / "core" / f"TC-{number}.md", f"TC-{number}", "QA-971")
    pin_all(task, root)
    dead = dict(entry("TC-1020", "test_a_old", probe=GREEN_PROBE), note="SUPERSEDED DUPLICATE - split into test_a")
    only_dead = dict(entry("TC-1021", "test_z_old", probe=GREEN_PROBE), critic_note="SUPERSEDED DUPLICATE")
    write_json(task / "work" / "automation-manifest.json",
               manifest(entry("TC-1020", "test_a", probe=GREEN_PROBE), dead, only_dead))
    run_green(task, "test_a")
    done = S.plan(task)
    check_eq("B1: a live green instance with a run + a dead one with NO run: the case is ready (the dead row holds nothing)",
             [item["case"] for item in done["ready"]], ["TC-1020"])
    check_eq("B1: ... and the stamp names only the live instance", done["ready"][0]["automated_by"], "test_a")
    check_eq("B1: a case whose ONLY row is dead has no automation evidence (it does not stamp)",
             {item["case"]: item["why"] for item in done["left"]}.get("TC-1021"), "no_automation_evidence")
    write_json(task / "work" / "run-report.json", {"current_results": [
        {"instance_id": "test_a", "status": "passed"}, {"instance_id": "test_a_old", "status": "failed"}]})
    check_eq("B1: a RED row of the dead instance holds nothing either (it proves nothing; was: held the case)",
             [item["case"] for item in S.plan(task)["ready"]], ["TC-1020"])


def stamp_and_lifecycle_agree(root: Path) -> None:
    """HF3-1 A-K6 (AR-13; mutation m5 and m1's second killer): one history of five cases - green with a run, green with NO run, red,
    `approved_with_fixes` with a run, a live green with a run beside a dead row with none - and the two readers that decide on
    an unpinned case, the stamp (`plan.ready`) and gate B (`lifecycle_reasons` demands the stamp), name the SAME cases as
    `instance_hold` does. (The coverage map's pinned route agrees on its own fixtures: test_pinned_lifecycle A-K6.)"""
    import check_delivery as D
    task = root / "qa-factory" / "artifacts" / "QA-972"
    numbers = (1030, 1031, 1032, 1033, 1034)
    for number in numbers:
        write_case(task / "work" / "test-cases" / "core" / f"TC-{number}.md", f"TC-{number}", "QA-972")
    # no pin on purpose: a pinned case is judged by its CaseVersion links, the unpinned one by the `Automated` stamp (the question here)
    dead = dict(entry("TC-1034", "t_dead", probe=GREEN_PROBE), note="SUPERSEDED DUPLICATE")
    tests = [entry("TC-1030", "t_green", probe=GREEN_PROBE), entry("TC-1031", "t_norow", probe=GREEN_PROBE),
             entry("TC-1032", "t_red", probe=GREEN_PROBE), entry("TC-1033", "t_fixes", verdict="approved_with_fixes", probe=GREEN_PROBE),
             entry("TC-1034", "t_live", probe=GREEN_PROBE), dead]
    write_json(task / "work" / "automation-manifest.json", manifest(*tests))
    write_json(task / "work" / "run-report.json", {"current_results": [
        {"instance_id": "t_green", "status": "passed"}, {"instance_id": "t_red", "status": "failed"},
        {"instance_id": "t_fixes", "status": "passed"}, {"instance_id": "t_live", "status": "passed"}]})
    runs = S.run_rows_of(task, C.load_json(task / "work" / "automation-manifest.json"))
    clean = {f"TC-{n}" for n in numbers
             if all(not S.instance_hold(t, runs) for t in tests if f"TC-{n}" in C.manifest_test_links(t) and t is not dead)}
    ready = {item["case"] for item in S.plan(task)["ready"]}
    asked = {number for number in (f"TC-{n}" for n in numbers) if any(f"case {number}:" in r for r in D.lifecycle_reasons(task))}
    check_eq("A-K6: the predicate says which cases can be stamped", clean, {"TC-1030", "TC-1033", "TC-1034"})
    check_eq("A-K6: the stamp's `ready` is exactly that set", ready, clean)
    check_eq("A-K6: gate B demands the stamp of exactly that set (the file still says Approved)", asked, clean)


def rh1_8_case_hold_keys(root: Path) -> None:
    """RH1-8 (HF4-1; AR-13, AR-15, AR-23, AR-28): the unit of `Automated` is the CASE - `case_hold` is the one answer, over the
    population `_case_population` finds by `contract.case_matches`. Kills: `case_hold([])` -> "" (m1: E3), "any clean instance"
    instead of every one (m2: E1), a population by exact key equality (m3: E5), a population without the `instance_case`
    fallback (m3b: E11), `unresolved` read by the exact key (m3c: E4-c; the plan.left key). Each key is named in its label."""
    import traceability
    cfg = {}   # the default case form (`TC-NNN`); a dict, so the matchers resolve nothing

    def inst(case, name, status="green", verdict="approved", **fields):
        return dict({"covers": [case] if case else [], "instance_id": name, "status": status, "critic_verdict": verdict}, **fields)

    def rows_for(**words):
        """name -> the word the run recorded for it (a green row for 'passed'); a name left out has no row at all."""
        return S.run_rows_index({n: {"test_id": f"tests/a.py::{n}", "instance_id": n, "status": w} for n, w in words.items()})

    def old_cases_held(manifest, index):
        # the formula `check_delivery._cases_held` had before RH1-8, written out here
        return {cid for t in traceability.live_tests(manifest) if S.instance_hold(t, index) for cid in C.manifest_test_links(t)}

    a, b, c = inst("TC-1001", "ta"), inst("TC-1001", "tb"), inst("TC-1001", "tc")
    live = [a, b, c]
    # E1: one green of three does not lend its pass to the others (b: no row; c: red)
    idx = rows_for(ta="passed", tc="failed")
    check_eq("RH1-8 E1 one green of three holds the case", S.case_hold(live, idx), "not_green:tc")
    check_eq("RH1-8 E1 ... the same through case_holds", S.case_holds(manifest(*live), idx, cfg), {"TC-1001": "not_green:tc"})
    # E1-b: the order of HOLDS - not_run (b: no row) comes before not_approved (c: rejected, with a green row)
    idx = rows_for(ta="passed", tc="passed")
    check_eq("RH1-8 E1-b not_run before not_approved",
             S.case_hold([a, b, dict(c, critic_verdict="rejected")], idx), "not_run:tb")
    # E1-c: three clean instances: the empty string, and the control that not everything became a hold
    idx = rows_for(ta="passed", tb="passed", tc="passed")
    check_eq('RH1-8 E1-c three clean -> ""', S.case_hold(live, idx), "")
    # E3: no live instance is a hold of its own, never a pass; a dead row names no case at all
    check_eq("RH1-8 E3 empty population -> no_automation_evidence", [S.case_hold([], idx), S.case_hold(None, idx)],
             ["no_automation_evidence"] * 2)
    dead = dict(inst("TC-1002", "t_old"), note="SUPERSEDED DUPLICATE - split")
    check_eq("RH1-8 E3 dead rows only -> no key in case_holds", S.case_holds(manifest(dead), idx, cfg), {})
    # E5: an entry that names the number with no area belongs to every area's case - and holds it
    qual, bare = inst("a/TC-1003", "qa"), inst("TC-1003", "qb")
    idx = rows_for(qb="passed")   # `qa` has no row: not_run
    check_eq("RH1-8 E5 unqualified entry holds the qualified key",
             sorted(S.case_holds(manifest(qual, bare), idx, cfg).items()),
             [("TC-1003", "not_run:qa"), ("a/TC-1003", "not_run:qa")])
    check_eq("RH1-8 E5 ... the population of the qualified key holds both", [C.test_instance_id(e) for e in S._case_population([qual, bare], "a/TC-1003", cfg)], ["qa", "qb"])
    # E5-b: two explicit areas do not hold each other
    ra, rb = inst("a/TC-1004", "ra"), inst("b/TC-1004", "rb")
    idx = rows_for(rb="passed")
    check_eq("RH1-8 E5-b qualified areas do not hold each other", S.case_holds(manifest(ra, rb), idx, cfg),
             {"a/TC-1004": "not_run:ra", "b/TC-1004": ""})
    # E10: garbage in the entries and an empty key: skipped, asked nothing, no exception
    try:
        garbage = [None, "x", [], 7, {}, qual]
        got = [S._case_population(garbage, "", cfg), S._case_population(garbage, None, cfg),
               [C.test_instance_id(e) for e in S._case_population(garbage, "a/TC-1003", cfg)]]
        check_eq("RH1-8 E10 non-dict and empty key raise nothing", got, [[], [], ["qa"]])
        check_eq("RH1-8 E10 ... and case_holds skips them", S.case_holds({"tests": [None, "x", qual]}, rows_for(qa="passed"), cfg),
                 {"a/TC-1003": ""})
    except Exception as exc:   # a raise is the failure this key names
        check("RH1-8 E10 non-dict and empty key raise nothing", False, repr(exc))
    # E11: a legacy instance that names its case only by the `TC-NNNN::` prefix of its id stays in that case
    legacy = {"instance_id": "TC-1005::test_x", "status": "green", "critic_verdict": "approved"}
    twin = inst("TC-1005", "twin")
    idx = S.run_rows_index({"TC-1005::test_x": {"test_id": "tests/a.py::test_x", "instance_id": "TC-1005::test_x", "status": "failed"},
                            "twin": {"test_id": "tests/a.py::twin", "instance_id": "twin", "status": "passed"}})
    pop = S._case_population([legacy, twin], "TC-1005", cfg)
    check_eq("RH1-8 E11 a prefix-only legacy instance stays in its case",
             [C.test_instance_id(e) for e in pop], ["TC-1005::test_x", "twin"])
    check_eq("RH1-8 E11 ... and its red run holds the case", S.case_hold(pop, idx), "not_green:TC-1005::test_x")
    # held_case_links: the set gate B asked before, on the fixtures of E1, E5 and E11
    for label, m, index in (("E1", manifest(*live), rows_for(ta="passed", tc="failed")),
                            ("E5", manifest(qual, bare), rows_for(qb="passed")),
                            ("E11", manifest(legacy, twin), idx)):
        check_eq(f"RH1-8 held_case_links equals the old _cases_held set ({label})",
                 S.held_case_links(m, index, cfg), old_cases_held(m, index))
    check_eq("RH1-8 held_case_links E11: the prefix-only instance names no `manifest_test_links` case, so it widens nothing",
             S.held_case_links(manifest(legacy, twin), idx, cfg), set())
    check_eq("RH1-8 held_case_links E1: the held case", S.held_case_links(manifest(*live), rows_for(ta="passed", tc="failed"), cfg), {"TC-1001"})

    # plan on disk: the `left` strings, byte for byte as before (the snapshot), and E4-c
    task = root / "qa-factory" / "artifacts" / "QA-990"
    for number in (1090, 1091, 1092, 1093, 1094, 1095):
        write_case(task / "work" / "test-cases" / "core" / f"TC-{number}.md", f"TC-{number}", "QA-990")
    write_case(task / "work" / "test-cases" / "core" / "TC-1096.md", "TC-1096", "QA-990", area="a")
    tests = [entry("TC-1090", "p_green", probe=GREEN_PROBE), entry("TC-1091", "p_norow", probe=GREEN_PROBE),
             entry("TC-1092", "p_red", probe=GREEN_PROBE), entry("TC-1093", "p_r1", probe=GREEN_PROBE),
             entry("TC-1093", "p_r2", probe=GREEN_PROBE), entry("TC-1094", "p_handed", probe=GREEN_PROBE),
             entry("a/TC-1096", "p_a", probe=GREEN_PROBE)]
    write_json(task / "work" / "automation-manifest.json", manifest(*tests, unresolved=[
        {"case": "TC-1094", "reason": "handed_to_person"}, {"case": "TC-1096", "reason": "handed_to_person"}]))
    write_json(task / "work" / "run-report.json", {"current_results": [
        {"instance_id": "p_green", "status": "passed"}, {"instance_id": "p_red", "status": "failed"},
        {"instance_id": "p_r1", "status": "failed"}, {"instance_id": "p_handed", "status": "passed"},
        {"instance_id": "p_a", "status": "passed"}]})
    done = S.plan(task)
    left = {item["case"]: item["why"] for item in done["left"]}
    check_eq("RH1-8 plan.left strings unchanged", {k: v for k, v in left.items() if k != "a/TC-1096" and k != "TC-1096"},
             {"TC-1091": "not_run:p_norow", "TC-1092": "not_green:p_red", "TC-1093": "not_green:p_r1",
              "TC-1094": "unresolved:handed_to_person", "TC-1095": "no_automation_evidence"})
    check_eq("RH1-8 plan.ready unchanged: the one clean case", [item["case"] for item in done["ready"]], ["TC-1090"])
    check_eq("RH1-8 E4-c a bare unresolved row holds the qualified case",
             [left.get("a/TC-1096"), left.get("TC-1096")], ["unresolved:handed_to_person"] * 2)


def m2_stamp_of_0_10_2_without_a_run_row() -> None:
    """HF4-2 edge m2 (t-1530 F-1 (a), AR-28, AR-23, FR-59, FR-18): a case stamped by 0.10.2 (when the stamp did not need a run row:
    `status: Automated` + `automated_by` + `red_probe` in the frontmatter) whose live instance has NO green run row today. PINS
    today's behaviour, changes none: the stamp writes only forward - the case is `left` for `not_run:<ids>` and a real `stamp`
    leaves its bytes alone (no un-stamping, no rewrite, no re-pin); the ledger judges by the run, never by the frontmatter
    (`not_executed:`, not `passed_green`); the coverage map counts the old stamp as a NAMED claim of 0.10.2 (the pinned
    overcount, spec t-1530 F-1: a follow-up may change it, this key then moves with it).
    Kills: `stamp` removing or rewriting the frontmatter of a case in `left` (the sha); `plan` reading frontmatter `Automated` as
    readiness (the `left` / `ready` keys); `plan_row_state` reading the frontmatter instead of the run (the `not_executed:` key)."""
    import hashlib
    import check_coverage as CC
    import ledger as L
    root = temp_dir("qa-case-stamp-m2-")
    try:
        init_project(root)
        task = root / "qa-factory" / "artifacts" / "QA-m2"
        source = task / "work" / "test-cases" / "core" / "TC-1050.md"
        write_case(source, "TC-1050", "QA-m2", status="Automated", automated_by="t_old",
                   red_probe="work/sensitivity-receipts/x.json")
        # no pin on purpose: a pin copies the case into the store (`cases/<id>/cv_*.md`, same bytes, same `Automated`), which
        # `collect_cases` counts as a second file - the count below is of the authoring file alone
        tests = manifest(entry("TC-1050", "t_old", probe=GREEN_PROBE))
        write_json(task / "work" / "automation-manifest.json", tests)
        check("m2 fixture: no run-report.json at all", not (task / "work" / "run-report.json").exists())
        before = hashlib.sha256(source.read_bytes()).hexdigest()

        done = S.plan(task)
        left = {item["case"]: item["why"] for item in done["left"]}
        check_eq("m2: the case is not ready", [item["case"] for item in done["ready"]], [])
        check_eq("m2: the case is left for `not_run:` naming its instance", left.get("TC-1050"), "not_run:t_old")
        result = S.stamp(task)
        check_eq("m2: a real stamp stamps nothing", result["stamped"], [])
        check_eq("m2: ... and the case stays in `left`", {item["case"]: item["why"] for item in result["left"]}.get("TC-1050"), "not_run:t_old")
        check_eq("m2: the case file is byte-identical after a real stamp (written forward only: no un-stamp, no rewrite)",
                 hashlib.sha256(source.read_bytes()).hexdigest(), before)
        check_eq("m2: ... the old frontmatter is still there", C.case_status(source), "Automated")

        # the ledger judges by the run: the row of the plan is not executed, never green off the frontmatter
        state, detail = L.plan_row_state({"ts": "TS-m2", "disposition": "automate"}, tests, {}, {}, {"TS-m2": ["TC-1050"]})
        check_eq("m2: the ledger row reads `not_executed:` (no result recorded for the case)",
                 state, "not_executed:no result recorded for this row's cases")
        check_eq("m2: ... naming the case", detail, "TC-1050")
        check("m2: ... never `passed_green`", state != "passed_green", state)

        # the coverage map counts the 0.10.2 stamp: the named claim of the old stamp, not a verdict of new code (F-1 (a))
        check_eq("m2: coverage map counts the case automated from the old frontmatter - a named claim of the 0.10.2 stamp, spec t-1530 F-1",
                 CC.collect_cases(root)["core"]["automated"], 1)

        # control: with a green run row of its own the case is ready (the hold is the missing row, nothing else)
        run_green(task, "t_old")
        check_eq("m2 control: with a green run row the same case is ready", [item["case"] for item in S.plan(task)["ready"]], ["TC-1050"])
    finally:
        cleanup(root)


def main() -> int:
    root = temp_dir("qa-case-stamp-")
    try:
        init_project(root)
        task = root / "qa-factory" / "artifacts" / "QA-960"
        source = task / "work" / "test-cases" / "core" / "TC-960.md"

        # --- a fully proven case stamps, and stamping again is a no-op ----------------------
        write_case(source, "TC-960", "QA-960")
        pin_all(task, root)
        write_json(task / "work" / "automation-manifest.json",
                  manifest(entry("TC-960", "test_a", probe=GREEN_PROBE),
                          entry("TC-960", "test_b", probe=GREEN_PROBE)))
        run_green(task, "test_a", "test_b")

        dry = S.stamp(task, dry_run=True)
        check_eq("dry-run reports the proven case ready", dry["stamped"], ["TC-960"])
        check_eq("and writes nothing", C.case_status(source), "Approved")

        first = S.stamp(task)
        check_eq("the real run stamps it", first["stamped"], ["TC-960"])
        check_eq("status becomes Automated", C.case_status(source), "Automated")
        stamped_fm = parse_frontmatter(source.read_text(encoding="utf-8"))
        check_eq("automated_by names both instances", stamped_fm.get("automated_by"), "test_a, test_b")
        check_in("red_probe names the receipt", "sensitivity-receipts", str(stamped_fm.get("red_probe")))
        version_after_first = next(l["version"] for l in C.story_case_links(task) if l["case_id"] == "TC-960")

        second = S.stamp(task)
        check_eq("stamping again reports the same result", second, first)
        version_after_second = next(l["version"] for l in C.story_case_links(task) if l["case_id"] == "TC-960")
        check_eq("and no new version is pinned for an unchanged stamp", version_after_second, version_after_first)

        # --- every reason a case is left alone -------------------------------------------------
        write_case(task / "work" / "test-cases" / "core" / "TC-961.md", "TC-961", "QA-960")
        write_case(task / "work" / "test-cases" / "core" / "TC-962.md", "TC-962", "QA-960")
        write_case(task / "work" / "test-cases" / "core" / "TC-963.md", "TC-963", "QA-960")
        write_case(task / "work" / "test-cases" / "core" / "TC-964.md", "TC-964", "QA-960", status="Blocked")
        write_case(task / "work" / "test-cases" / "core" / "TC-966.md", "TC-966", "QA-960")
        for number in (967, 968, 969, 970, 971):
            write_case(task / "work" / "test-cases" / "core" / f"TC-{number}.md", f"TC-{number}", "QA-960")
        pin_all(task, root)
        write_json(task / "work" / "automation-manifest.json", manifest(
            entry("TC-960", "test_a", probe=GREEN_PROBE), entry("TC-960", "test_b", probe=GREEN_PROBE),
            entry("TC-961", "test_c", status="red"),
            entry("TC-962", "test_d", verdict="concerns"),
            entry("TC-963", "test_e"),  # green, approved, but no red-probe evidence at all
            entry("TC-964", "test_f", probe=GREEN_PROBE),
            # D-0010: what proves a case is a probe of a KNOWN level, live or better
            entry("TC-967", "test_h", probe=LIVE_PROBE),
            entry("TC-968", "test_i", probe={"proof_level": "mystery", "evidence_ref": "work/sensitivity-receipts/x.json"}),
            entry("TC-969", "test_j", probe={"mutation_kind": "assertion", "evidence_ref": "work/sensitivity-receipts/x.json"}),
            entry("TC-970", "test_k", probe={"mutation_kind": "assertion_edit", "evidence_ref": "work/sensitivity-receipts/x.json"}),
            entry("TC-971", "test_l", probe={"proof_level": "live", "mutation_kind": "assertion"}),
            unresolved=[{"case": "TC-965", "reason": "blocked_by_env"}]))
        # every instance below has run green (HF3-1), so what each case is left for is its OWN reason: test_c is red in the
        # manifest (a green row does not lift the manifest's word), the rest differ in verdict, proof or status
        run_green(task, "test_a", "test_b", "test_c", "test_d", "test_e", "test_f", "test_h", "test_i", "test_j", "test_k", "test_l")
        # TC-966 is pinned but never mentioned by the manifest at all.

        result = S.stamp(task, dry_run=True)
        left = {item["case"]: item["why"] for item in result["left"]}
        check_in("a red instance blocks the case", "not_green", left.get("TC-961", ""))
        check_in("a concerns verdict blocks the case", "not_approved", left.get("TC-962", ""))
        check_in("a green approved instance with no proof blocks the case", "no_sensitivity_proof",
                 left.get("TC-963", ""))
        check_in("a case a human already Blocked is never touched", "status_blocked", left.get("TC-964", ""))
        check_in("a case named only in unresolved[] is never touched", "unresolved:blocked_by_env",
                 left.get("TC-965", ""))
        check_in("a pinned case the manifest never mentions is left with a reason",
                 "no_automation_evidence", left.get("TC-966", ""))
        check("the already-proven case is not held back by its siblings", "TC-960" not in left, left)
        ready = {item for item in result["stamped"]}
        check_eq("a live probe (an assertion mutation, the level probe_by_code.py proves) stamps the case",
                 "TC-967" in ready, True)
        check_eq("so does a block with only the assertion mutation kind, which is the live level by its kind",
                 "TC-969" in ready, True)
        check_in("a probe of a level nobody knows proves nothing", "no_sensitivity_proof", left.get("TC-968", ""))
        check_in("nor does a mutation kind no level is made of", "no_sensitivity_proof", left.get("TC-970", ""))
        check_in("a live probe with no evidence to point at proves nothing either", "no_sensitivity_proof",
                 left.get("TC-971", ""))
        # D-0012: an unchanged reused instance is not probed and needs no receipt for Automated
        write_case(task / "work" / "test-cases" / "core" / "TC-972.md", "TC-972", "QA-960")
        write_case(task / "work" / "test-cases" / "core" / "TC-973.md", "TC-973", "QA-960")
        write_case(task / "work" / "test-cases" / "core" / "TC-974.md", "TC-974", "QA-960")
        pin_all(task, root)
        unchanged = entry("TC-972", "test_u")
        unchanged["change_disposition"] = "unchanged"
        flagged = entry("TC-973", "test_v")
        flagged.update(change_disposition="unchanged", sensitivity_proof_required=True)
        changed = entry("TC-974", "test_w")
        changed["change_disposition"] = "new_or_changed"
        write_json(task / "work" / "automation-manifest.json", manifest(unchanged, flagged, changed))
        run_green(task, "test_u", "test_v", "test_w")
        result = S.stamp(task, dry_run=True)
        left = {item["case"]: item["why"] for item in result["left"]}
        check_in("an unchanged reused instance needs no receipt for the Automated stamp", "TC-972", result["stamped"])
        check_in("an unchanged instance that a flag makes required still needs one", "no_sensitivity_proof",
                 left.get("TC-973", ""))
        check_in("a new or changed instance with no receipt is left", "no_sensitivity_proof", left.get("TC-974", ""))
        plan = S.plan(task)
        red = next(item["red_probe"] for item in plan["ready"] if item["case"] == "TC-972")
        check_eq("and red_probe (the state machine's key) carries the data's words for it", red,
                 "not probed (unchanged test)")
        # t-175: a case is handed to the person; its own row never reaches here (it is `unresolved`), but
        # a test that ALSO covers another case is handed for that case too: it reads "handed", never
        # "unchanged test" (FR-10).
        write_case(task / "work" / "test-cases" / "core" / "TC-977.md", "TC-977", "QA-960")
        write_case(task / "work" / "test-cases" / "core" / "TC-978.md", "TC-978", "QA-960")
        pin_all(task, root)
        shared = entry("TC-977", "test_shared")
        shared.update(covers=["TC-977", "TC-978"], change_disposition="unchanged")
        write_json(task / "work" / "automation-manifest.json", manifest(
            shared, unresolved=[{"case": "TC-978", "reason": "handed_to_person", "detail": "api: run it yourself"}]))
        run_green(task, "test_shared")
        plan = S.plan(task)
        red = next((item["red_probe"] for item in plan["ready"] if item["case"] == "TC-977"), None)
        check_eq("a case proven by a test that is also handed for another case: the handed words",
                 red, "not probed (handed to the person)")
        check_not_in("...and never the unchanged words", "unchanged test", str(red))
        # critic t-048 F2: the row's receipt stamps only when proof_level.reached says it holds for the
        # test's bytes NOW - a contract-valid receipt for OLD bytes does not stamp a changed test
        import hashlib
        from harness import use_project
        use_project(root)
        test_file = root / "tests" / "test_stamp.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("def test_s():\n    assert 1 + 1 == 2\n", encoding="utf-8")
        now = hashlib.sha256(test_file.read_bytes()).hexdigest()

        def receipt_row(case, instance, bytes_sha, tag):
            body = {"instance_id": instance, "case_version": "cv_" + tag, "test_content_hash": bytes_sha,
                    "source_revision": "s", "build_id": "b", "mutation": "invert", "expected_assertion_failure": "e",
                    "actual_failure": "e", "assertion_location": "tests/test_stamp.py:2",
                    "restoration_evidence": "r", "failure_kind": "assertion", "proof_level": "live",
                    "probe_tool": "probe_by_code.py", "mutation_kind": "assertion", "immutable": True,
                    "receipt_hash": "h-" + tag}
            path = task / "work" / "sensitivity-receipts" / f"{tag}.json"
            write_json(path, body)
            row = entry(case, instance)
            row.update(file="tests/test_stamp.py", sensitivity_proof={"receipt_ref": {
                "path": path.relative_to(task).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}})
            return row
        for number in (975, 976):
            write_case(task / "work" / "test-cases" / "core" / f"TC-{number}.md", f"TC-{number}", "QA-960")
        pin_all(task, root)
        current, stale = receipt_row("TC-975", "test_s1", now, "now"), receipt_row("TC-976", "test_s2", "0" * 64, "old")
        check_eq("the stale receipt is valid under the contract alone (what the stamp used to read)",
                 C.sensitivity_proof_issues(stale, task), [])
        write_json(task / "work" / "automation-manifest.json", manifest(current, stale))
        run_green(task, "test_s1", "test_s2")
        result = S.stamp(task, dry_run=True)
        left = {item["case"]: item["why"] for item in result["left"]}
        check_in("a receipt for the test's current bytes stamps the case", "TC-975", result["stamped"])
        check_eq("...and red_probe names that receipt", next(i["red_probe"] for i in S.plan(task)["ready"]
                                                             if i["case"] == "TC-975"), "work/sensitivity-receipts/now.json")
        check_in("a receipt for OTHER bytes does not stamp a changed test", "no_sensitivity_proof", left.get("TC-976", ""))

        # --- t-415 (B-308 b): a red run result outranks the manifest's green ------------------
        # The manifest's `status: green` is what the automator wrote before the run; the run result is what the run
        # observed. A case whose instance went red in `run-report.json` is not proven `Automated`, whatever the manifest
        # still says. HF3-1 (A-K2; FR-59, FR-18, P20 - the expectation follows the finding "three readers of green without
        # a run row", not the new code): the same holds for an instance the run recorded NOTHING green for - no row, a
        # `partial` without a red raw status, a sibling parameter's row - which used to stamp "as before".
        task4 = root / "qa-factory" / "artifacts" / "QA-963"
        names = {980: "test_r1", 981: "test_r2", 982: "test_r3", 983: "test_r4", 984: "test_r5[multi]", 985: "test_r6",
                 986: "test_r7", 987: "test_r8"}
        covers = {980: 980, 981: 981, 982: 982, 983: 983, 984: 984, 985: 985, 986: 986, 987: 986}
        for number in sorted(set(covers.values())):
            write_case(task4 / "work" / "test-cases" / "core" / f"TC-{number}.md", f"TC-{number}", "QA-963")
        pin_all(task4, root)
        write_json(task4 / "work" / "automation-manifest.json", manifest(
            *[entry(f"TC-{covers[n]}", inst, probe=GREEN_PROBE) for n, inst in names.items()]))
        report_path = task4 / "work" / "run-report.json"
        all_cases = {f"TC-{n}" for n in set(covers.values())}

        def stamped_with(rows):
            if rows is None:
                report_path.unlink(missing_ok=True)
            elif isinstance(rows, str):
                report_path.write_text(rows, encoding="utf-8")
            else:
                write_json(report_path, rows)
            plan4 = S.plan(task4)
            return {item["case"] for item in plan4["ready"]}, {item["case"]: item["why"] for item in plan4["left"]}

        # R2 flipped by HF3-1 (A-K2): no run result at all is no run, so NO proven case stamps - each is left `not_run:`
        # naming its instances; an unreadable report is "not read" (critic t-1254 m1, FR-59), named as such
        ready, left = stamped_with(None)
        check_eq("A-K2: no run-report.json: no case is ready (the manifest's green is not a run)", ready, set())
        check_eq("A-K2: ... every case is left", set(left), all_cases)
        check("A-K2: ... each for `not_run:` its instances", all(why.startswith("not_run:") for why in left.values()), str(left))
        check_eq("A-K2: ... the case of two instances names both", left["TC-986"], "not_run:test_r7,test_r8")
        for body in ("{ this is not json", "[]", "null", '"text"'):
            ready, left = stamped_with(body)
            check_eq(f"A-K2 m1: run-report.json = {body!r}: nothing is ready", ready, set())
            check_eq("A-K2 m1: ... every case is left as `run_report_unreadable`, not as not run",
                     set(left.values()), {"run_report_unreadable"})
        ready, left = stamped_with({"current_results": []})
        check_eq("A-K2: a run report with no row for any instance: nothing is ready", ready, set())
        check("A-K2 m1: ... each left for `not_run:` (an empty report is read, it just holds no run)",
              set(left) == all_cases and all(why.startswith("not_run:") for why in left.values()), str(left))
        ready, left = stamped_with({"results": "x", "current_results": 7})
        check("A-K2 m1: an object with wrong-typed fields is READ (it holds no row): `not_run:`, not unreadable",
              ready == set() and all(why.startswith("not_run:") for why in left.values()), str(left))
        rows = [{"instance_id": "test_r1", "status": "failed"},          # red under a green manifest
                {"instance_id": "test_r2", "status": "passed"},          # R3: a green run
                {"instance_id": "test_r4[chromium]", "status": "error"},  # the run row spells a parameter the manifest does not
                {"instance_id": "test_r5[json]", "status": "failed"},    # a SIBLING of the manifest's test_r5[multi]
                {"instance_id": "test_r6", "status": "partial"},         # a word that is not red
                {"instance_id": "test_r7", "status": "passed"}, {"instance_id": "test_r8", "status": "failed"}]
        ready, left = stamped_with({"current_results": rows})
        check("R1 t-415: a red run under a green manifest does not stamp the case", "TC-980" not in ready, ready)
        check_in("R1 t-415: and it is left in the words the site already uses", "not_green:test_r1", left.get("TC-980", ""))
        check_in("R1 t-415: an `error` row of a parameterised run reads red too", "not_green:test_r4", left.get("TC-983", ""))
        check_in("R1 t-415: one red instance of a case with two holds the whole case", "not_green:test_r8", left.get("TC-986", ""))
        check_not_in("R1 t-415: the green instance of that case is not named", "test_r7", left.get("TC-986", ""))
        check_in("R3 t-415: a green run stamps as before", "TC-981", ready)
        check_eq("A-K2 (R2 flipped): an instance with no run row is NOT ready - the manifest's green is not a run", "TC-982" in ready, False)
        check_eq("A-K2: ... it is left `not_run:` naming it", left.get("TC-982"), "not_run:test_r3")
        check_eq("A-K2 (:350 flipped): a red SIBLING parameter (x[json]) is not the manifest's x[multi] - and x[multi] has no row of its own: not_run",
                 left.get("TC-984"), "not_run:test_r5[multi]")
        check_not_in("A-K2 (:350): ... and the sibling's red is still NOT the instance's own: never `not_green`", "not_green", left.get("TC-984", ""))
        check_eq("A-K2 (:351 flipped): a `partial` run row is not red, and not green either: not_run",
                 left.get("TC-985"), "not_run:test_r6")
        check_eq("A-K2: the green cases stay ready, the rest are left", (ready, set(left)),
                 ({"TC-981"}, all_cases - {"TC-981"}))
        check_eq("no case stamps that was left, and none is left that was stamped", ready & set(left), set())
        legacy = {"results": [{"test": "test_r1", "result": "failed"}]}
        ready, left = stamped_with(legacy)
        check("R1 t-415: a legacy results[] report (no current_results) is read too", "TC-980" not in ready, ready)
        # the real write: the red case's file stays what it was, the others become Automated
        write_json(report_path, {"current_results": rows})
        done = S.stamp(task4)
        check("R1 t-415: the real stamp leaves the red-run case out", "TC-980" not in done["stamped"], done)
        check_eq("R1 t-415: its file still says Approved", C.case_status(task4 / "work" / "test-cases" / "core" / "TC-980.md"),
                 "Approved")
        check_eq("R3 t-415: the green one is Automated", C.case_status(task4 / "work" / "test-cases" / "core" / "TC-981.md"),
                 "Automated")
        # the door: the repaired run (green row) stamps the case at the next reduce
        rows[0] = {"instance_id": "test_r1", "status": "passed"}
        write_json(report_path, {"current_results": rows})
        check_in("R1 t-415: once the run is green the case stamps (the way out)", "TC-980", S.stamp(task4)["stamped"])

        # --- t-419: ONE join for "is there a red run for this manifest instance" (critic t-418 F1, F2, F3) ---------
        # Rows: F1 - a PASSED `x[unparseable]` (its manifest `test` is the bare function) beside a red sibling `x[json]`;
        # F2 - a hash identity joined to its run row only by the dashboard's tolerant rule (`tests/a.py::test_y` against
        # `tests.a::test_y`); edge 3 - an instance that names no parameter stands for the whole function; F3 - a row the
        # reducer overwrote to `partial` keeps what the run said in `raw_status`.
        task5 = root / "qa-factory" / "artifacts" / "QA-964"
        shapes5 = {
            # case: (manifest fields, expected reading of "this case's instance has a red run")
            990: ({"test": "tests/a.py::test_x", "parameter": "unparseable"}, False),    # F1: own row passed, sibling red
            991: ({"test": "tests/a.py::test_x", "parameter": "json"}, True),            # F1: the red sibling's own case
            992: ({"instance_id": "ti_0123456789abcdef0002", "test": "tests/a.py::test_y"}, True),   # F2
            993: ({"test": "tests/a.py::test_z"}, True),                                 # edge 3: bare, only x[a] red / x[b] green
            994: ({"instance_id": "test_q"}, False),                                     # bare WITH its own passed row
            995: ({"instance_id": "ti_0123456789abcdef0003", "test": "tests/a.py::test_w1"}, True),  # F3: partial + raw failed
            996: ({"instance_id": "ti_0123456789abcdef0004", "test": "tests/a.py::test_w2"}, False),  # partial + raw passed
            997: ({"instance_id": "ti_0123456789abcdef0005", "test": "tests/a.py::test_w3"}, False),  # partial, no raw_status
            998: ({"instance_id": "ti_0123456789abcdef0006", "test": "tests/a.py::test_w4"}, True),  # partial + raw error
            999: ({"instance_id": "ti_0123456789abcdef0007", "test": "tests/a.py::test_w5"}, False),  # superseded history row
        }
        for number in shapes5:
            write_case(task5 / "work" / "test-cases" / "core" / f"TC-{number}.md", f"TC-{number}", "QA-964")
        pin_all(task5, root)
        rows5 = []
        for number, (fields, _) in shapes5.items():
            row = entry(f"TC-{number}", "x", probe=GREEN_PROBE)
            row.pop("instance_id")
            row.update(fields)
            rows5.append(row)
        write_json(task5 / "work" / "automation-manifest.json", manifest(*rows5))
        def joined(n):  # a ghost: an identity of its own (no manifest row has it), the run's test id, the reducer's overwrite
            return {"instance_id": f"ghost-w{n}", "test_id": f"tests/a.py::test_w{n}", "status": "partial",
                    "current_reason": "instance_manifest_join_failed"}
        write_json(task5 / "work" / "run-report.json", {"current_results": [
            {"instance_id": "test_x[unparseable]", "test_id": "tests/a.py::test_x[unparseable]", "status": "passed"},
            {"instance_id": "test_x[json]", "test_id": "tests/a.py::test_x[json]", "status": "failed", "case": "TC-991"},
            {"test_id": "tests.a::test_y", "status": "failed", "case": "TC-992"},
            {"instance_id": "test_z[a]", "status": "failed"}, {"instance_id": "test_z[b]", "status": "passed"},
            {"instance_id": "test_q", "status": "passed"}, {"instance_id": "test_q[a]", "status": "failed"},
            dict(joined(1), raw_status="failed"), dict(joined(2), raw_status="passed"), joined(3),
            dict(joined(4), raw_status="error"), dict(joined(5), raw_status="failed", superseded=True),
        ]})
        plan5 = S.plan(task5)
        red5 = {item["case"] for item in plan5["left"] if item["why"].startswith("not_green:")}
        got5 = {f"TC-{n}": f"TC-{n}" in red5 for n in shapes5}
        want5 = {f"TC-{n}": expected for n, (_, expected) in shapes5.items()}
        check_eq("C1/C2/C3/C4 t-419: every shape reads as the one join says (red -> `not_green`, else not left for it)", got5, want5)
        check("C1 t-419: a red sibling parameter does not turn a passed instance red (TC-990 is ready, not left)",
              "TC-990" in {item["case"] for item in plan5["ready"]}, str(plan5["left"]))
        check("C2 t-419: a red row joined only by the tolerant rule holds the stamp (TC-992 is not ready)",
              "TC-992" not in {item["case"] for item in plan5["ready"]})
        check("C3 t-419: a bare-test manifest row reads red when any of its parameters is red (TC-993 not ready)",
              "TC-993" not in {item["case"] for item in plan5["ready"]})
        check("C4 t-419: a join-failed row with a red raw status holds the stamp (TC-995, TC-998 not ready)",
              not ({"TC-995", "TC-998"} & {item["case"] for item in plan5["ready"]}))
        # the pure function, on the same rows: red_run_for answers the same, and an unreadable report is no red run
        index5 = S.run_rows_of(task5)
        check_eq("one join: `red_run_for` over the same manifest rows",
                 {f"TC-{n}": S.red_run_for(rows5[i], index5) is not None for i, n in enumerate(shapes5)}, want5)
        check_eq("edge 6: no entry, an empty entry, an entry of empty ids: no red run, no exception",
                 [S.red_run_for(e, index5) is not None for e in (None, {}, {"instance_id": "", "test": None, "selector": ""}, "x", [])],
                 [False] * 5)
        check_eq("edge 6: no index, an index of nothing: no red run",
                 [S.red_run_for(rows5[0], i) is not None for i in (None, {}, S.run_rows_index({}), S.run_rows_index(None))], [False] * 4)
        for body in ("{not json", "[]", "null", '"text"', '{"results": "x", "current_results": 7}'):
            (task5 / "work" / "run-report.json").write_text(body, encoding="utf-8")
            check_eq(f"edge 6: run-report.json = {body!r}: no red run, no exception",
                     S.red_run_for(rows5[2], S.run_rows_of(task5)) is not None, False)
        (task5 / "work" / "run-report.json").unlink()
        check_eq("edge 6: no run-report.json: no red run", S.red_run_for(rows5[2], S.run_rows_of(task5)) is not None, False)

        run_row_for_keys()
        instance_hold_keys()
        one_predicate_stories(root)
        stamp_and_lifecycle_agree(root)
        rh1_8_case_hold_keys(root)
        m2_stamp_of_0_10_2_without_a_run_row()

        # --- CLI surface --------------------------------------------------------------------
        cli = run_script("case_stamp.py", "--task-root", task, "--dry-run")
        check("the CLI exits 0", cli.returncode == 0, cli.stdout + cli.stderr)
        payload = json.loads(cli.stdout)
        check_eq("and prints the documented shape", sorted(payload.keys()), ["dry_run", "left", "stamped"])

        # --- finalize_task calls it before anything reads a delivery manifest ----------------
        task2 = root / "qa-factory" / "artifacts" / "QA-961"
        source2 = task2 / "work" / "test-cases" / "core" / "TC-970.md"
        write_case(source2, "TC-970", "QA-961")
        pin_all(task2, root)
        write_json(task2 / "work" / "automation-manifest.json",
                  manifest(entry("TC-970", "test_g", probe=GREEN_PROBE)))
        run_green(task2, "test_g")   # the reducer stamps AFTER the run: the report it reads holds the run
        refreshed = F.refresh(task2)
        check("finalize_task wires the stamp in", "case_stamp" in refreshed, refreshed)
        check_eq("and the case is stamped through it", refreshed.get("case_stamp", {}).get("stamped"), ["TC-970"])
        check_eq("the authoring source itself changed", C.case_status(source2), "Automated")

        # --- a story with no manifest at all is untouched, never an error --------------------
        task3 = root / "qa-factory" / "artifacts" / "QA-962"
        refreshed3 = F.refresh(task3)
        check_eq("an empty story stamps nothing", refreshed3.get("case_stamp"), {"stamped": [], "left": []})

        # --- CS2: a manifest-bound immutable version is never re-pinned by the stamp -------------
        # The manifest's `case_version_links[]` is S5's proof against the reviewed version; a new
        # pin here would make that proof stale the moment it was written. Kills: `immutable_proof`
        # removed from `case_stamp.stamp` (the pin moves).
        task6 = root / "qa-factory" / "artifacts" / "QA-963"
        source6 = task6 / "work" / "test-cases" / "core" / "TC-980.md"
        write_case(source6, "TC-980", "QA-963")
        pin_all(task6, root)
        bound = next(l["version"] for l in C.story_case_links(task6) if l["case_id"] == "TC-980")
        write_json(task6 / "work" / "automation-manifest.json",
                   manifest(dict(entry("TC-980", "test_h", probe=GREEN_PROBE),
                                 case_version_links=[{"case_id": "TC-980", "version": bound}])))
        run_green(task6, "test_h")
        check_eq("the bound case is stamped", S.stamp(task6)["stamped"], ["TC-980"])
        check_eq("its lifecycle frontmatter is written", C.case_status(source6), "Automated")
        check_eq("and the manifest's pin does not move",
                 next(l["version"] for l in C.story_case_links(task6) if l["case_id"] == "TC-980"), bound)
    finally:
        cleanup(root)
    finish("test_case_stamp")


if __name__ == "__main__":
    main()
