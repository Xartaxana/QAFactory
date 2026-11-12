"""V2 automation acceptance binds the real defect to its obligation and assertion."""
import hashlib
import shutil
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR / "scripts"))
from acceptance import validate_window  # noqa: E402

# Outside the package: a local-directory marketplace copies whatever lies in it.
ROOT = Path(tempfile.mkdtemp(prefix="qa-acceptance-semantics-"))


def record(evidence):
    return {"schema_version": 2, "input_hash": "input", "required_quality_checks": [],
        "instances": [{"schema_version": 2, "instance_id": "i1", "input_hash": "input",
        "outcome": "passed", "review": {"verdict": "approved", "input_hash": "input"},
        "obligation_ids": ["O-1"], "obligation_hash": "ohash", "assertion_id": "assert-total",
        "defect_location": "src/app.py:8", "change_disposition": "new_or_changed",
        "change_basis_ref": "diff", "probe": {"verdict": "intended_failure", "input_hash": "input",
        "obligation_ids": ["O-1"], "obligation_hash": "ohash", "assertion_id": "assert-total",
        "defect_location": "src/app.py:8", "expected_location": "tests/test_app.py:9",
        "actual_location": "tests/test_app.py:9", "expected_reason": "wrong total",
        "actual_reason": "wrong total", "failure_kind": "assertion",
        "mutation_kind": "real_behavior", "evidence_ref": "proof.txt"},
        "evidence_refs": [{"path": "proof.txt", "sha256": evidence}]}]}


def main():
    shutil.rmtree(ROOT, ignore_errors=True); ROOT.mkdir(); proof = ROOT / "proof.txt"; proof.write_text("proof")
    digest = hashlib.sha256(proof.read_bytes()).hexdigest(); good = record(digest)
    assert validate_window(good, ROOT) == [], validate_window(good, ROOT)
    tampered = record(digest); tampered["instances"][0]["probe"]["obligation_hash"] = "other"
    assert "semantic_sensitivity:i1" in validate_window(tampered, ROOT)
    assertion_only = record(digest); assertion_only["instances"][0]["defect_location"] = "tests/test_app.py:9"
    assertion_only["instances"][0]["probe"]["defect_location"] = "tests/test_app.py:9"
    assert "semantic_sensitivity:i1" in validate_window(assertion_only, ROOT)
    absent = record(digest); absent["instances"][0]["probe"].pop("evidence_ref")
    assert "probe_evidence:i1" in validate_window(absent, ROOT)
    mismatch = record(digest); mismatch["instances"][0]["probe"]["evidence_ref"] = "other.txt"
    assert "probe_evidence:i1" in validate_window(mismatch, ROOT)
    assertion_mutation = record(digest); assertion_mutation["instances"][0]["probe"]["mutation_kind"] = "assertion_edit"
    assert "probe_mutation_kind:i1" in validate_window(assertion_mutation, ROOT)
    # --- the levels (D-0010): the live check is a probe of the ASSERTION and owes no product mutation
    live = record(digest); live["instances"][0]["probe"].update(proof_level="live", mutation_kind="assertion")
    assert validate_window(live, ROOT) == [], validate_window(live, ROOT)
    bare_live = record(digest); bare_live["instances"][0]["probe"].update(proof_level="live")
    bare_live["instances"][0]["probe"].pop("mutation_kind")
    assert validate_window(bare_live, ROOT) == [], validate_window(bare_live, ROOT)
    # ... and everything else a probe owes is still owed at that level
    for what, gap, change in (
            ("obligation hash", "semantic_sensitivity:i1", {"obligation_hash": "other"}),
            ("evidence", "probe_evidence:i1", {"evidence_ref": "other.txt"}),
            ("the reason it failed", "sensitivity:i1", {"actual_reason": "another reason"}),
            ("the verdict", "sensitivity:i1", {"verdict": "no_failure"})):
        broken = record(digest); broken["instances"][0]["probe"].update(proof_level="live", mutation_kind="assertion")
        broken["instances"][0]["probe"].update(change)
        gaps = validate_window(broken, ROOT)
        assert gap in gaps, (what, gaps)
        assert "probe_mutation_kind:i1" not in gaps and "probe_level:i1" not in gaps, (what, gaps)
    product = record(digest); product["instances"][0]["probe"].update(proof_level="catches_broken_product")
    assert validate_window(product, ROOT) == [], validate_window(product, ROOT)
    claims = record(digest)
    claims["instances"][0]["probe"].update(proof_level="catches_broken_product", mutation_kind="assertion")
    assert validate_window(claims, ROOT) == ["probe_mutation_kind:i1"], validate_window(claims, ROOT)
    unknown = record(digest); unknown["instances"][0]["probe"].update(proof_level="mystery")
    assert validate_window(unknown, ROOT) == ["probe_level:i1"], validate_window(unknown, ROOT)
    # an old window has no level at all: today's rule holds, both ways
    old_live = record(digest); old_live["instances"][0]["probe"].update(mutation_kind="assertion")
    assert validate_window(old_live, ROOT) == ["probe_mutation_kind:i1"], validate_window(old_live, ROOT)
    # a handed test is never asked for a probe, at either level (B-375: handed only as far as the manifest says so)
    put_handed_world()
    handed = record(digest); handed["instances"][0]["outcome"] = "handed_to_person"
    handed["instances"][0]["probe"] = {}; handed["scope_instances"] = {"TC-1": ["i1"]}
    assert validate_window(handed, ROOT) == ["handed_to_person:i1"], validate_window(handed, ROOT)
    put_handed_world(row=False)
    unconfirmed = validate_window(handed, ROOT)
    assert "handed_unconfirmed:i1" in unconfirmed and not any(
        g.startswith(("handed_to_person", "product")) for g in unconfirmed), ("without the row the claim buys nothing", unconfirmed)
    # an unchanged test is not probed and blocks nothing
    unchanged = record(digest); unchanged["instances"][0]["change_disposition"] = "unchanged"
    unchanged["instances"][0]["probe"] = {}
    assert validate_window(unchanged, ROOT) == [], validate_window(unchanged, ROOT)
    # one predicate: a flag that makes a live check required is read here as it is everywhere
    flagged = record(digest); flagged["instances"][0]["change_disposition"] = "unchanged"
    flagged["instances"][0]["sensitivity_proof_required"] = True; flagged["instances"][0]["probe"] = {}
    assert "sensitivity:i1" in validate_window(flagged, ROOT), validate_window(flagged, ROOT)
    legacy = record(digest); legacy["schema_version"] = 1; legacy["instances"][0]["schema_version"] = 1
    for key in ("obligation_ids", "obligation_hash", "assertion_id", "defect_location"):
        legacy["instances"][0].pop(key, None); legacy["instances"][0]["probe"].pop(key, None)
    assert validate_window(legacy, ROOT) == [], validate_window(legacy, ROOT)
    per_test_binding(digest)
    mechanical_round_on_the_driver3_shape()
    a_blocked_instance_is_decided_by_the_manifest(digest)
    row_slice_says_what_a_row_speaks_about()
    a_red_instance_is_decided_by_the_manifest(digest)
    a_run_of_other_code_is_a_gap_of_its_own(digest)
    a_handed_instance_is_decided_by_the_manifest(digest)
    handed_instances_errs_toward_not_handed()
    rh1_9_the_file_of_an_instance_and_its_bytes()
    shutil.rmtree(ROOT, ignore_errors=True); print("PASS test_acceptance_semantics")


def a_run_of_other_code_is_a_gap_of_its_own(digest):
    """HF2-11a (K4): an item carrying the run's per-test shas (`run_identity`) and the test's identity now
    (`instance_identity`) is `stale_run:<iid>` when the two are not the same test - after the outcome's own gap, never
    in its place - and says nothing when the run or the test recorded no identity, when only a comment moved, or when the
    instance never ran here (handed, stopped)."""
    import acceptance as AC
    import proof_level as PL
    now = {"instance_content_sha": "c1", "instance_code_sha": "k1", "job_id": "j1"}
    ran = {"instance_content_sha": "c1", "instance_code_sha": "k1", "attempt_id": "run-1"}

    def window(outcome="passed", run=ran, identity=now, **item_over):
        built = record(digest)
        item = built["instances"][0]
        item["outcome"] = outcome
        if run is not None:
            item["run_identity"] = dict(run)
        if identity is not None:
            item["instance_identity"] = dict(identity)
        item.update(item_over)
        return built

    def gaps(built):
        return validate_window(built, ROOT)
    assert gaps(window()) == [], gaps(window())                                  # the same test: fresh, no gap
    other = dict(ran, instance_content_sha="c0", instance_code_sha="k0")
    assert gaps(window(run=other)) == ["stale_run:i1"], gaps(window(run=other))  # a green run of other code
    comment = dict(ran, instance_content_sha="c0")
    assert gaps(window(run=comment)) == [], gaps(window(run=comment))            # only a comment moved: no gap
    assert gaps(window(run=None)) == [], gaps(window(run=None))                  # the run recorded none: unknown, no gap
    assert gaps(window(run={"instance_content_sha": "c0"})) == [], "only the raw sha is not an identity"
    assert gaps(window(run={"instance_content_sha": "", "instance_code_sha": ""})) == [], "empty shas are no identity"
    assert gaps(window(run=other, identity=None)) == [], gaps(window(run=other, identity=None))  # no identity now: unknown
    # no identity now because a MEASUREMENT failed (a deleted helper): a run that had one is not kept by it
    measured = gaps(window(run=other, identity=None, instance_identity_why=PL.WHY_NO_CODE))
    assert measured == ["stale_run:i1"], measured
    # ...but not when nothing was measured (no run of the story selected the test): unknown, no gap
    assert gaps(window(run=other, identity=None, instance_identity_why=PL.WHY_NO_REQUEST)) == []
    # a red keeps its own gap and gets this one beside it: plain red, then a red its manifest row explains
    plain = gaps(window(outcome="failed", run=other))
    assert plain == ["product:i1", "stale_run:i1"], plain
    real = AC.red_by_requirement
    AC.red_by_requirement = lambda *a, **k: {"i1": [{"case": "TC-1"}]}
    try:
        explained = gaps(window(outcome="failed", run=other))
    finally:
        AC.red_by_requirement = real
    assert explained == ["contradicts_requirement:i1", "stale_run:i1"], explained
    # an instance that never ran here has no run to be stale: handed, and stopped by the stand
    # (the shared ROOT still holds the failed run block the red test left for i1: the handed case gets its own state, m-3)
    put_handed_world()
    handed = window(outcome="handed_to_person", run=other)
    handed["instances"][0]["probe"] = {}; handed["scope_instances"] = {"TC-1": ["i1"]}
    assert gaps(handed) == ["handed_to_person:i1"], gaps(handed)
    put_handed_world(row=False)
    assert "handed_unconfirmed:i1" in gaps(handed) and "handed_to_person:i1" not in gaps(handed), gaps(handed)
    real = AC.blocked_instances
    AC.blocked_instances = lambda *a, **k: {"i1": {"reason": "blocked_by_env"}}
    try:
        stopped = window(outcome="blocked_by_env", run=other, review={"verdict": "unverified", "input_hash": "input"})
        stopped["instances"][0]["probe"] = {}
        assert gaps(stopped) == ["blocked_by_env:i1"], gaps(stopped)
    finally:
        AC.blocked_instances = real
    # beside a stale review, each its own gap: the run's staleness is not the review's
    stale_review =window(run=other, review={"verdict": "approved", "input_hash": "elsewhere"})
    assert gaps(stale_review) == ["stale_review:i1", "stale_run:i1"], gaps(stale_review)


def a_red_instance_is_decided_by_the_manifest(digest):
    """HF2-4a (K2): an item that claims `outcome: failed` is `contradicts_requirement:<iid>` ONLY as far as the manifest
    under the root and the latest terminal run block say so (`red_by_requirement`, v-b), and the classification is
    handed -> stopped -> red -> `product:`. The allowed error is `product:` (a refusal costs a round); the forbidden one
    is a red nobody explained, or a green or unrun test, or a handed item, passing as red. A red item owes no probe."""
    import json
    work = ROOT / "work"
    blocks = work / "run-blocks"
    blocks.mkdir(parents=True, exist_ok=True)
    row = {"case": "TC-1", "reason": "contradicts_requirement", "instance_ids": ["i1"], "thens": [1], "detail": "d"}
    tests = [{"instance_id": "i1", "case": "TC-1", "covers": ["TC-1"]}]
    covered = {"case": "TC-1", "then": 1, "instance_id": "i1", "status": "covered", "assertion_ref": "t.py:1-2"}

    def put(unresolved=(row,), bindings=(covered,), entries=tests):
        (work / "automation-manifest.json").write_text(json.dumps(
            {"tests": entries, "unresolved": list(unresolved), "then_bindings": list(bindings)}), encoding="utf-8")

    def ran(status):
        (blocks / "20261001T000000000000Z-r1.json").write_text(json.dumps(
            {"results": [{"instance_id": "i1", "status": status}]}), encoding="utf-8")

    def window(outcome="failed", verdict="approved", disposition="new_or_changed", scope=True):
        built = record(digest)
        item = built["instances"][0]
        item.update(outcome=outcome, change_disposition=disposition)
        item.pop("probe")            # a red test is asked for no probe
        item["review"]["verdict"] = verdict
        if scope:
            built["scope_instances"] = {"TC-1": ["i1"]}
        return built

    def gaps(**kw):
        return validate_window(window(**kw), ROOT)

    put()
    ran("failed")
    assert gaps() == ["contradicts_requirement:i1"], gaps()
    assert gaps(disposition="unchanged") == ["contradicts_requirement:i1"], "a red unchanged test: the same gap"
    assert gaps(verdict="unverified") == ["contradicts_requirement:i1", "review:i1"], "the critic's word is `approved` only"
    assert gaps(verdict="") == ["contradicts_requirement:i1", "review:i1"], "no word is no approval"
    # an item that RAN GREEN is never asked about; a red item with a probe beside it is still judged by its rows
    assert validate_window(record(digest), ROOT) == [], "a green window is judged exactly as before"
    # every way the manifest can fail to explain the red: the gap is `product:`, never the new kind
    for label, change in (("no row", lambda: put(unresolved=())),
                          ("a row of another case", lambda: put(unresolved=[dict(row, case="TC-9")])),
                          ("a row about another instance", lambda: put(unresolved=[dict(row, instance_ids=["i2"])])),
                          ("a row of a partition this test lacks", lambda: put(unresolved=[dict(row, instance_ids=[], partitions=["P-a"])])),
                          ("a row for Then 3, the test binds Then 1", lambda: put(unresolved=[dict(row, thens=[3])])),
                          ("no covered binding", lambda: put(bindings=())),
                          ("a row of another reason", lambda: put(unresolved=[dict(row, reason="blocked_by_env")])),
                          ("no manifest tests row", lambda: put(entries=[]))):
        change()
        found = gaps()
        assert "product:i1" in found and not any(g.startswith("contradicts_requirement") for g in found), (label, found)
    put()
    # ... and every way the RUN can fail to say the test is red
    for label, status in (("the latest run passed", "passed"), ("only an error", "error"), ("skipped", "skipped")):
        ran(status)
        found = gaps()
        assert "product:i1" in found and not any(g.startswith("contradicts_requirement") for g in found), (label, found)
    (blocks / "20261001T000000000000Z-r1.json").unlink()
    found = gaps()
    assert "product:i1" in found and "contradicts_requirement:i1" not in found, ("no run at all", found)
    ran("failed")
    # a window that names no scope, or whose manifest cannot be read, believes nothing
    assert "product:i1" in gaps(scope=False), "no scope map"
    (work / "automation-manifest.json").write_text("{not json", encoding="utf-8")
    assert "product:i1" in gaps() and "contradicts_requirement:i1" not in gaps(), "an unreadable manifest"
    put()
    # position (M2): a handed or stopped item is never red, whatever the runs and the rows say
    # B-375 (E6): a handed claim beside a FAILED run block of the instance is not believed - the run's outcome outranks the
    # hand-off - and it is neither red nor `product:` (the fault is the record's); an unconfirmed `new_or_changed` claim
    # owes a probe like any item (E14)
    found = gaps(outcome="handed_to_person")
    assert "handed_unconfirmed:i1" in found and "sensitivity:i1" in found, found
    assert not any(g.startswith(("contradicts_requirement", "product", "handed_to_person")) for g in found), found
    claimed = gaps(outcome="blocked_by_env", verdict="unverified")
    assert "product:i1" in claimed and "contradicts_requirement:i1" not in claimed, ("a blocked claim with no blocked row", claimed)
    # the reader is asked once, and never for a window with no red item
    import acceptance
    asked: list = []
    real = acceptance.red_by_requirement
    acceptance.red_by_requirement = lambda *a, **k: asked.append(a) or real(*a, **k)
    try:
        validate_window(record(digest), ROOT)
        assert asked == [], "a green window does not ask"
        gaps()
        assert len(asked) == 1, "one call for the whole window"
    finally:
        acceptance.red_by_requirement = real


def row_slice_says_what_a_row_speaks_about():
    """HF2-3 (3a1-K4): `acceptance.row_slice` is a pure function of (row, test entry, case) and answers a code for every
    way a row can be about something else. The error direction is a code (a row that cannot be read speaks about nothing)."""
    from acceptance import row_slice
    ms = {"instance_id": "t_ms", "covers": ["TC-4", "TC-5"], "partitions": ["P-msteams"]}
    bare = {"instance_id": "t_plain", "covers": ["TC-4"]}
    red = {"case": "TC-4", "reason": "contradicts_requirement"}
    table = [
        ("a whole-case row", red, ms, "TC-4", ""),
        ("a whole-case row, an instance without partitions", red, bare, "TC-4", ""),
        ("`thens` is no slice key", dict(red, thens=[2]), bare, "TC-4", ""),
        ("another case", dict(red, case="TC-5"), ms, "TC-4", "other_case"),
        ("a row without a case", {"reason": "contradicts_requirement"}, ms, "TC-4", "other_case"),
        ("a blank case asked about", red, ms, "", "other_case"),
        ("the named instance", dict(red, instance_ids=["t_ms"]), ms, "TC-4", ""),
        ("the named instance, singular key", dict(red, instance_id="t_ms"), ms, "TC-4", ""),
        ("the named instance, one of two", dict(red, instance_ids=["x", "t_ms"]), ms, "TC-4", ""),
        ("another instance", dict(red, instance_ids=["t_plain"]), ms, "TC-4", "names_other"),
        ("an instance list that names nothing readable", dict(red, instance_ids=[None, ""]), ms, "TC-4", "names_other"),
        ("a partition row, an instance with none", dict(red, partitions=["P-msteams"]), bare, "TC-4", "no_partitions"),
        ("a partition row, an instance whose partition is only `P-`", dict(red, partitions=["P-msteams"]),
         dict(ms, partitions=["P-"]), "TC-4", "no_partitions"),
        ("the same partition under another label", dict(red, partitions=["msteams"]), ms, "TC-4", ""),
        ("the same partition, singular key, other case of letters", dict(red, partition="P-MSTEAMS"), ms, "TC-4", ""),
        ("another partition", dict(red, partitions=["P-a"]), dict(ms, partitions=["P-b"]), "TC-4", "other_partition"),
        ("a partition that is only `P-` meets nothing", dict(red, partitions=["P-"]), ms, "TC-4", "other_partition"),
        ("two partitions, one shared", dict(red, partitions=["P-a", "P-msteams"]), ms, "TC-4", ""),
        ("instance and partition, both must match", dict(red, instance_ids=["t_ms"], partitions=["P-a"]), ms, "TC-4",
         "other_partition"),
        ("a row that is no object", "x", ms, "TC-4", "other_case"),
        ("an entry that is no object", red, None, "TC-4", "other_case"),
    ]
    for label, row, entry, case, want in table:
        got = row_slice(row, entry, case)
        assert got == want, (label, got, want)
    before = repr((red, ms))
    row_slice(red, ms, "TC-4")
    assert repr((red, ms)) == before, "row_slice must not touch its inputs"


def a_blocked_instance_is_decided_by_the_manifest(digest):
    """t-219: an item that CLAIMS `outcome: blocked_by_env` is believed only as far as the manifest under the root
    says so (`blocked_instances`, B1). The allowed error is "not blocked" (the item then reads `product:`, a refusal
    costs one round); the forbidden one is "blocked" for an instance that is not. A blocked instance owes no probe
    and, when it never ran, no evidence; its review is `unverified` or it is a review gap."""
    import json
    from acceptance import blocked_instances
    work = ROOT / "work"
    work.mkdir(exist_ok=True)
    fix = {"kind": "service", "where": "frontend localhost:5173", "change": "the page must load", "restart": "re-run"}

    def put(unresolved, tests=None):
        tests = tests if tests is not None else [{"instance_id": "i1", "case": "TC-1", "covers": ["TC-1"]}]
        (work / "automation-manifest.json").write_text(json.dumps({"tests": tests, "unresolved": unresolved}),
                                                       encoding="utf-8")

    def row(**over):
        return dict({"case": "TC-1", "reason": "blocked_by_env", "partitions": ["p"], "remedy": dict(fix)}, **over)

    def window(verdict="unverified", refs=None, scope=None):
        built = record(digest)
        item = built["instances"][0]
        item.update(outcome="blocked_by_env", execution_fingerprint="", evidence_refs=[] if refs is None else refs)
        item["review"]["verdict"] = verdict
        item.pop("probe", None)
        built["scope_instances"] = scope if scope is not None else {"TC-1": ["i1"]}
        return built

    put([row()])
    assert validate_window(window(), ROOT) == ["blocked_by_env:i1"], validate_window(window(), ROOT)
    for verdict in ("approved", "rejected", "approved_with_fixes", ""):   # E5
        assert validate_window(window(verdict), ROOT) == ["blocked_by_env:i1", "review:i1"], verdict
    bad = [{"sha256": "0" * 64, "path": "proof.txt"}]
    assert validate_window(window(refs=bad), ROOT) == ["blocked_by_env:i1", "evidence:i1"], "a run that was cited is checked"
    # the claim with nothing behind it, and every way a row can fail to be one (B3, E1, E2)
    put([])
    assert "product:i1" in validate_window(window(), ROOT) and not any(
        g.startswith("blocked") for g in validate_window(window(), ROOT)), "no row: not blocked"
    no_remedy = row()
    no_remedy.pop("remedy")
    put([no_remedy])
    assert "product:i1" in validate_window(window(), ROOT), "E1: no remedy"
    put([row(remedy={"kind": "credential", "where": ".env", "change": "sk8A9fKq2LmN7xP4wZ1vB3cD"})])
    assert "product:i1" in validate_window(window(), ROOT), "E2: a remedy that looks like a secret"
    put([row()])
    assert "product:i1" in validate_window(window(scope={}), ROOT), "no scope map: nothing is blocked"
    put([row(case="TC-9")])
    assert "product:i1" in validate_window(window(), ROOT), "a row for a case outside the scope"
    # pair scoping (C3) and the single-instance rule (E7)
    two_cases = [{"instance_id": "i1", "case": "TC-1", "covers": ["TC-1", "TC-2"]}]
    both = {"TC-1": ["i1"], "TC-2": ["i1"]}
    put([row()], two_cases)
    assert "product:i1" in validate_window(window(scope=both), ROOT), "C3: it also proves a case the row is not about"
    put([row(partitions=[], instance_ids=["i1"])], two_cases)
    assert validate_window(window(scope=both), ROOT) == ["blocked_by_env:i1"], "C3: named, the alias branch asks less"
    two_tests = [{"instance_id": "i1", "case": "TC-1", "covers": ["TC-1"]},
                 {"instance_id": "i2", "case": "TC-1", "covers": ["TC-1"]}]
    put([row()], two_tests)
    refused: list = []
    assert blocked_instances({"tests": two_tests, "unresolved": [row()]}, [{"instance_id": "i1"}],
                             {"TC-1": ["i1", "i2"]}, ROOT, refused=refused) == {}
    assert "name the instance_id" in refused[0][2], refused
    # K1: a remedy with several problems is refused with ALL of them in the one line
    import contract as C
    bad = {"kind": "nope", "where": "", "change": "", "restart": ""}
    problems = C.remedy_errors(bad)
    assert len(problems) >= 2, problems
    refused = []
    assert blocked_instances({"tests": two_tests[:1], "unresolved": [row(remedy=bad)]}, [{"instance_id": "i1"}],
                             {"TC-1": ["i1"]}, ROOT, refused=refused) == {}
    assert f"{len(problems)} defect(s)" in refused[0][2] and all(p in refused[0][2] for p in problems), refused
    put([row(partitions=[], instance_ids=["i2"])], two_tests)
    assert "product:i1" in validate_window(window(scope={"TC-1": ["i1", "i2"]}), ROOT), "an id that is not this instance's"
    # one reader answers the same way directly: the row, keyed by the instance
    got = blocked_instances({"tests": two_tests, "unresolved": [row(partitions=[], instance_ids=["i1"])]},
                            [{"instance_id": "i1"}, {"instance_id": "i2"}], {"TC-1": ["i1", "i2"]}, ROOT)
    assert sorted(got) == ["i1"], got


def per_test_binding(digest):
    """t-043 C: `_bound_to` asks `proof_level.same_test` - a review and a probe are current when they still speak
    for THIS test (the same bytes, the same test after an edit of another one, or its same code), through the
    window's own fields, and never by two empty values."""
    import proof_level as PL
    same = {"instance_content_sha": "c1", "instance_code_sha": "k1", "job_id": "j1"}

    def window(item_raw="now-raw", identity=None, review=None, probe=None, **item_over):
        built = record(digest)
        item = built["instances"][0]
        item["input_hash"] = item_raw
        item["review"] = dict({"verdict": "approved", "input_hash": "input"}, **(review or {}))
        item["probe"].update({"input_hash": "input", "proof_level": "live", "mutation_kind": "assertion"}, **(probe or {}))
        if identity:
            item["instance_identity"] = identity
        item.update(item_over)
        return built

    def stale(built):
        gaps = validate_window(built, ROOT)
        return sorted(g for g in gaps if g.split(":")[0] in ("stale_review", "sensitivity", "mechanical_green"))

    # the same test after another test's edit: the file's raw bytes differ, the identity is equal
    with_identity = window(identity=same, review={"instance_identity": dict(same, job_id="old")},
                           probe={"instance_identity": dict(same, job_id="old")})
    assert stale(with_identity) == [], stale(with_identity)
    # the code of a test after a comment: the content differs, the code is the same
    comment = window(identity=same, review={"instance_identity": dict(same, instance_content_sha="c0")},
                     probe={"instance_identity": dict(same, instance_content_sha="c0")})
    assert stale(comment) == [], stale(comment)
    # both differ: a gap, even though the file's raw sha is equal (the fixture inside the identity changed)
    moved = window(item_raw="input", identity=same,
                   review={"instance_identity": {"instance_content_sha": "c9", "instance_code_sha": "k9", "job_id": "j"}},
                   probe={"instance_identity": {"instance_content_sha": "c9", "instance_code_sha": "k9", "job_id": "j"}})
    assert stale(moved) == ["sensitivity:i1", "stale_review:i1"], stale(moved)
    # the bound side has an identity and the current item has none because its measurement FAILED: a gap, though raw is equal
    failed = window(item_raw="input", review={"instance_identity": same}, probe={"instance_identity": same},
                    instance_identity_why=PL.WHY_NO_CODE)
    assert stale(failed) == ["sensitivity:i1", "stale_review:i1"], stale(failed)
    # ...but not when it has none because no run selected the test (nothing was measured): the raw rule as ever
    unmeasured = window(item_raw="input", review={"instance_identity": same}, probe={"instance_identity": same},
                        instance_identity_why=PL.WHY_NO_REQUEST)
    assert stale(unmeasured) == [], stale(unmeasured)
    # a window from before: raw only, both ways; and a code sha it never recorded keeps nothing
    assert stale(window(item_raw="input")) == []
    assert stale(window(item_raw="other")) == ["sensitivity:i1", "stale_review:i1"], stale(window(item_raw="other"))
    # a legacy probe that recorded `test_code_sha`, on a file whose code is the same: held; a legacy review has none: stale
    legacy_code = window(test_code_sha="code-1", probe={"test_code_sha": "code-1"}, review={})
    assert stale(legacy_code) == ["stale_review:i1"], stale(legacy_code)
    # two ABSENT values are never equal: no raw sha and no code sha on the bound side
    nothing = window(test_code_sha="", review={"input_hash": ""}, probe={"input_hash": ""})
    assert stale(nothing) == ["sensitivity:i1", "stale_review:i1"], stale(nothing)
    both_empty_code = window(test_code_sha="", probe={"test_code_sha": ""}, review={"test_code_sha": ""})
    assert stale(both_empty_code) == ["sensitivity:i1", "stale_review:i1"], stale(both_empty_code)
    assert isinstance(validate_window(with_identity, ROOT), list)


def mechanical_round_on_the_driver3_shape():
    """t-016 Amendment 4: a mechanical round closes on the author's green run when the RAW sha of the
    test file - recorded by the job's request (`fingerprint_files`) the run block came from - equals
    the instance's raw `input_hash`. The shapes are TP1-13797's (driver3) S5-qa-automator-5 job
    2b65f846f6bacf1de627 and its run block; the manifest is built by manifest_from_tests.py itself.
    The block's own source_fingerprint.test_content_sha (a fingerprint over test and helper files)
    is another quantity and is never compared: before this, no round could close."""
    import json
    import os
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import harness
    import test_manifest_from_tests as MFT
    from acceptance import green_on_current_bytes_why
    from event_store import content_hash
    project = harness.temp_project("qa-acceptance-driver3-")
    old_env = os.environ.get("CLAUDE_PROJECT_DIR")
    harness.use_project(project)
    try:
        task = MFT.seed(project)
        wrote = MFT.run(project)
        assert wrote.returncode == 0, wrote.stdout + wrote.stderr
        manifest = json.loads((task / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
        row = next(t for t in manifest["tests"] if t["instance_id"] == "test_limit")
        test_file, helper = project / row["file"], project / "tests" / "data_coupon.py"
        raw = hashlib.sha256(test_file.read_bytes()).hexdigest()
        assert row["trace_binding"]["test_content_sha"] == raw
        records = [{"path": str(test_file.resolve()), "sha256": raw, "kind": "test_files"},
                   {"path": str(helper.resolve()), "sha256": hashlib.sha256(helper.read_bytes()).hexdigest(),
                    "kind": "helper_files"},
                   {"path": str((project / "qa-factory" / "config.json").resolve()), "sha256": "a" * 64,
                    "kind": "config_files"}]
        fingerprint = content_hash(records[:1] + records[1:2])  # execution_fingerprint.build's test_content_sha
        assert fingerprint != raw
        job_id, author = "2b65f846f6bacf1de627", "S5-qa-automator-5"
        components = {"source_sha": "92f6999018d7119964d28f0fac99eb9a40ca37cd", "test_content_sha": fingerprint}
        (task / "state" / "execution-jobs").mkdir(parents=True, exist_ok=True)
        (task / "state" / "execution-jobs" / "2b2440aebeac44099388563d39cd577d716643a7a53faaebf2b28747e4110c49.json"
         ).write_text(json.dumps({
            "job_id": job_id, "idempotency_key": f"{author}:initial:TC-001:ee3a7e686e9e", "status": "completed",
            "request": {"dispatch_id": author, "purpose": "initial", "input_fingerprint": "e37d447fb82e",
                        "fingerprint_components": components, "fingerprint_files": records,
                        "selected_instance_ids": ["test_limit"]},
            "run_block": f"qa-factory/artifacts/QA-700/work/run-blocks/20260927T072032710276Z-{job_id}.json"}),
            encoding="utf-8")
        (task / "work" / "run-blocks" / f"20260927T072032710276Z-{job_id}.json").write_text(json.dumps({
            "schema_version": 2, "block_id": job_id, "attempt_id": job_id, "dispatch_id": author,
            "purpose": "initial", "input_fingerprint": "e37d447fb82e", "source_fingerprint": components,
            "execution_status": "passed", "reporter_mapping": {"mode": "exact", "source_attempt_id": job_id},
            "results": [{"instance_id": "test_limit", "status": "passed", "attempt_id": job_id,
                         "input_fingerprint": "e37d447fb82e", "source_fingerprint": components}]}),
            encoding="utf-8")
        window = {"mechanical_round": {"author_dispatch_id": author, "reviewer_dispatch_id": "S5-qa-code-critic-5",
                                       "reviewed_input_hash": "0" * 64}}
        item = {"instance_id": "test_limit", "outcome": "passed", "execution_fingerprint": "e37d447fb82e",
                "input_hash": raw}
        assert green_on_current_bytes_why(item, window, task) == (True, ""), green_on_current_bytes_why(item, window, task)
        # the fingerprint in the instance's place is not these bytes any more
        green, why = green_on_current_bytes_why(dict(item, input_hash=fingerprint), window, task)
        assert not green and f"ran the test file as sha256 {raw}" in why, why
        # a review and a probe bound to the reviewed bytes are carried by the green run
        full = record("unused")["instances"][0]
        full.update(item, review={"verdict": "approved", "input_hash": "0" * 64})
        full["probe"].update(input_hash="0" * 64, proof_level="live", mutation_kind="assertion")
        full.update(evidence_refs=[{"path": f"work/run-blocks/20260927T072032710276Z-{job_id}.json",
                                    "sha256": hashlib.sha256((task / "work" / "run-blocks" /
                                                              f"20260927T072032710276Z-{job_id}.json").read_bytes()).hexdigest()}])
        full["probe"]["evidence_ref"] = full["evidence_refs"][0]["path"]
        gaps = validate_window({"required_quality_checks": [], "instances": [full], **window}, task)
        assert not any(g.startswith(("stale_review", "mechanical_green", "sensitivity:")) for g in gaps), gaps
        # the job gone: not green, and the words say which job
        next((task / "state" / "execution-jobs").glob("*.json")).unlink()
        green, why = green_on_current_bytes_why(item, window, task)
        assert not green and f"names job {job_id}, and no such job" in why, why
    finally:
        if old_env is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = old_env
        harness.cleanup(project)


def rh1_9_the_file_of_an_instance_and_its_bytes():
    """RH1-9 N4 (AR-13, AR-4): K-P the path rule of `_raw_record` is `proof_level.same_path` on every OS (run as is and with
    `os.path` swapped for `ntpath`, the platform-independent kill of the old `normcase` rule), E12, K-A1 an alias shared by two
    files names none, K-A2 the raw-bytes question is `proof_level.same_test`."""
    import json
    import ntpath
    import os
    import acceptance
    import contract as C
    import proof_level
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import harness

    def request(*paths):
        return {"fingerprint_files": [{"path": p, "sha256": f"sha-{n}", "kind": "test_files"} for n, p in enumerate(paths)]}
    rows = (("a recorded Windows absolute path ends in the manifest's POSIX relative one",
             request("C:\\proj\\tests\\test_m.py", "C:\\proj\\tests\\other.py"), "tests/test_m.py", "sha-0"),
            ("backslashes against slashes", request("tests\\sub\\test_m.py", "x\\y.py"), "tests/sub/test_m.py", "sha-0"),
            ("the tail must stand on a boundary", request("xtests/test_m.py", "z/a.py"), "tests/test_m.py", ""),
            ("E12: the recorded case is not the manifest's -> no record", request("C:\\p\\tests\\test_m.py", "C:\\p\\q.py"),
             "Tests/test_m.py", ""))
    real = (os.path, os.sep, os.altsep)
    for mode in ("as is", "os.path = ntpath"):
        if mode != "as is":
            os.path, os.sep, os.altsep = ntpath, ntpath.sep, ntpath.altsep
        try:
            for label, req, manifest_path, want in rows:
                sha, missing = acceptance._raw_record(req, manifest_path)
                assert sha == want, (mode, label, sha, missing)
                if not want:
                    assert manifest_path in missing, (mode, label, missing)
        finally:
            os.path, os.sep, os.altsep = real
    # K-A1 / E6: the exact id wins; a bare alias names a file only when ONE row carries it.
    project = harness.temp_project("qa-acceptance-rh19-")
    try:
        task = project / "task"
        (task / "work").mkdir(parents=True)
        manifest = {"tests": [{"instance_id": "TC-1::test_x", "file": "tests/a.py"},
                              {"instance_id": "TC-2::test_x", "file": "tests/b.py"},
                              {"instance_id": "TC-3::test_only", "file": "tests/c.py"}]}
        C.artifact(task, "automation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        assert acceptance._instance_test_file(task, "TC-2::test_x") == "tests/b.py"
        assert acceptance._instance_test_file(task, "test_x") == "", "K-A1: an alias of two files names none"
        assert acceptance._instance_test_file(task, "test_only") == "tests/c.py", "an alias of ONE row names its file"
        assert acceptance._instance_test_file(task, "no_such") == ""
    finally:
        harness.cleanup(project)
    # K-A2: the question is `same_test`; only the raw `input_hash` is asked (E11).
    window = {"mechanical_round": {"author_dispatch_id": "A", "reviewer_dispatch_id": "R", "reviewed_input_hash": "0" * 64}}
    item = {"instance_id": "i", "outcome": "passed", "execution_fingerprint": "fp", "input_hash": "raw-1"}
    root = Path(tempfile.mkdtemp(prefix="qa-acceptance-rh19b-"))
    try:
        (root / "work" / "run-blocks").mkdir(parents=True)
        (root / "state" / "execution-jobs").mkdir(parents=True)
        (root / "work" / "run-blocks" / "b.json").write_text(json.dumps({
            "block_id": "b", "attempt_id": "j1", "dispatch_id": "A", "input_fingerprint": "fp",
            "results": [{"instance_id": "i", "status": "passed"}]}), encoding="utf-8")
        (root / "state" / "execution-jobs" / "j1.json").write_text(json.dumps({
            "job_id": "j1", "request": {"fingerprint_files": [{"path": "t.py", "sha256": "raw-1", "kind": "test_files"}]}}),
            encoding="utf-8")
        assert acceptance.green_on_current_bytes_why(item, window, root) == (True, "")
        assert not acceptance.green_on_current_bytes_why(dict(item, input_hash="raw-2"), window, root)[0]
        assert not acceptance.green_on_current_bytes_why(dict(item, input_hash=""), window, root)[0], "an empty hash is no match"
        real_same = proof_level.same_test
        proof_level.same_test = lambda now, bound: ""
        try:
            assert not acceptance.green_on_current_bytes_why(item, window, root)[0], "K-A2: the answer is same_test's"
        finally:
            proof_level.same_test = real_same
        proof_level.same_test = lambda now, bound: "instance"
        try:
            assert not acceptance.green_on_current_bytes_why(item, window, root)[0], "E11: only `raw` counts here"
        finally:
            proof_level.same_test = real_same
    finally:
        shutil.rmtree(root, ignore_errors=True)


HANDED_ROW = {"case": "TC-1", "reason": "handed_to_person", "detail": "web: npx playwright test t.spec.ts"}


def put_handed_world(row=True, root=None):
    """The state of a story whose test i1 proves TC-1: a manifest (with the `handed_to_person` row of TC-1 when `row`) and NO
    run block - a shared ROOT keeps what an earlier test left (m-3)."""
    import json
    root = root or ROOT
    (root / "work" / "run-blocks").mkdir(parents=True, exist_ok=True)
    for old in (root / "work" / "run-blocks").glob("*.json"):
        old.unlink()
    (root / "work" / "automation-manifest.json").write_text(json.dumps({
        "tests": [{"instance_id": "i1", "case": "TC-1", "covers": ["TC-1"]}],
        "unresolved": [dict(HANDED_ROW)] if row else []}), encoding="utf-8")


def a_handed_instance_is_decided_by_the_manifest(digest):
    """B-375 A-T1: an item that CLAIMS `outcome: handed_to_person` is `handed_to_person:<iid>` ONLY as far as the manifest under
    the root says so (`handed_instances`), owes no evidence and no probe, and its review word is `approved` or `unverified`,
    bound to the bytes. The allowed error is `handed_unconfirmed:<iid>` (a refusal with a door, never `product:`, never a
    derivable gap); the forbidden one is a hand-off nobody wrote. A passed instance is never asked (B-1)."""
    import copy
    import json
    import acceptance
    root = Path(tempfile.mkdtemp(prefix="qa-acceptance-handed-"))
    try:
        (root / "work" / "run-blocks").mkdir(parents=True)
        manifest = root / "work" / "automation-manifest.json"
        tests = [{"instance_id": "i1", "covers": ["TC-1"]}, {"instance_id": "i2", "covers": ["TC-2"]}]
        rows = [dict(HANDED_ROW), dict(HANDED_ROW, case="TC-2")]

        def put(unresolved=rows):
            manifest.write_text(json.dumps({"tests": tests, "unresolved": list(unresolved)}), encoding="utf-8")

        def window(**over):
            built = record("unused")
            base = built["instances"][0]
            base.update(outcome="handed_to_person", evidence_refs=[], review={"verdict": "unverified", "input_hash": "input"})
            base.pop("probe")
            first, second = copy.deepcopy(base), copy.deepcopy(base)
            second["instance_id"] = "i2"
            built["instances"] = [first, second]
            built["scope_instances"] = {"TC-1": ["i1"], "TC-2": ["i2"]}
            built.update(over)
            return built

        def gaps(built=None):
            return validate_window(built or window(), root)
        put()
        both = ["handed_to_person:i1", "handed_to_person:i2"]
        assert gaps() == both, gaps()                                     # (1) no evidence:, no review:
        put(rows[:1])                                                     # (2) TC-2's row dropped
        found = gaps()
        assert "handed_unconfirmed:i2" in found and "handed_to_person:i1" in found, found
        assert "handed_to_person:i2" not in found and "product:i2" not in found, found
        put()                                                             # (3) the door opens
        assert gaps() == both, gaps()
        mixed = window()                                                  # (4) a mix: i2 passed with good evidence
        proof = root / "proof.txt"
        proof.write_text("proof")
        good = record(hashlib.sha256(proof.read_bytes()).hexdigest())["instances"][0]
        good["instance_id"] = "i2"
        mixed["instances"][1] = good
        asked: list = []
        real = acceptance.handed_instances
        acceptance.handed_instances = lambda m, items, *a, **k: asked.append([i["instance_id"] for i in items]) or real(m, items, *a, **k)
        try:
            assert gaps(mixed) == ["handed_to_person:i1"], gaps(mixed)
            assert asked == [["i1"]], ("the reader is asked about the handed claim only", asked)
            asked.clear()
            gaps(record(hashlib.sha256(proof.read_bytes()).hexdigest()))  # (9) a window with no handed item never asks
            assert asked == [], asked
        finally:
            acceptance.handed_instances = real
        blocks = root / "work" / "run-blocks"                             # (5) a run of the instance outranks the hand-off
        (blocks / "20261001T000000000000Z-r1.json").write_text(json.dumps(
            {"results": [{"instance_id": "i1", "status": "failed"}]}), encoding="utf-8")
        found = gaps()
        assert "handed_unconfirmed:i1" in found and "handed_to_person:i1" not in found, found
        assert "handed_to_person:i2" in found, found
        (blocks / "20261001T000000000000Z-r1.json").unlink()
        manifest.unlink()                                                 # (6) the manifest is absent: unknown is no pass
        for label in ("absent", "unreadable"):                            # (6) / (7) ... or unreadable
            if label == "unreadable":
                manifest.write_text("{not json", encoding="utf-8")
            found = gaps()
            assert {"handed_unconfirmed:i1", "handed_unconfirmed:i2"} <= set(found), (label, found)
            assert not any(g.startswith("handed_to_person") for g in found), (label, found)
        put()                                                             # (8) the review word
        for word, want in (("approved", both), ("unverified", both), ("rejected", both + ["review:i1"]),
                           ("", both + ["review:i1"])):
            built = window()
            built["instances"][0]["review"]["verdict"] = word
            assert gaps(built) == sorted(want), (word, gaps(built))
        stale = window()
        stale["instances"][0]["review"]["input_hash"] = "elsewhere"
        assert gaps(stale) == sorted(both + ["stale_review:i1"]), gaps(stale)
        # an unconfirmed claim is NOT derivable and is never `handed_to_person:`: its kind does not start with it
        assert not acceptance.HANDED_UNCONFIRMED_KIND.startswith(acceptance.HANDED_OUTCOME)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def handed_instances_errs_toward_not_handed():
    """B-375 A-T2: every doubt answers "not handed" (inputs a-m of the spec, with the compound row of B-2), and the positive
    controls show the reader is not simply closed. The rule for "this scope case is handed" is the controller's
    (`contract.scope_keys`: exact keys)."""
    from acceptance import handed_instances
    from pathlib import Path as P
    row = dict(HANDED_ROW)
    one = [{"instance_id": "i1", "covers": ["TC-1"]}]

    def hi(rows=(row,), tests=one, scope=None, runs=None, refused=None, iid="i1", manifest=None):
        built = manifest if manifest is not None else {"tests": tests, "unresolved": list(rows)}
        return handed_instances(built, [{"instance_id": iid}], {"TC-1": ["i1"]} if scope is None else scope, None,
                                {} if runs is None else runs, refused)
    # positive controls: the exact row, an area row of the same area, a compound row, two instances of one case
    assert {k: [r["case"] for r in v] for k, v in hi().items()} == {"i1": ["TC-1"]}, hi()
    area = dict(row, case="A/TC-1")
    assert list(hi(rows=[area], scope={"A/TC-1": ["i1"]})) == ["i1"], "an area row of the same area"
    compound = dict(row, case="TC-1/TC-2/TC-3")
    two = [{"instance_id": "i1", "covers": ["TC-1", "TC-3"]}]
    assert list(hi(rows=[compound], tests=two, scope={"TC-1": ["i1"], "TC-3": ["i1"]})) == ["i1"], "the compound row"
    twins = [{"instance_id": "i1", "covers": ["TC-1"]}, {"instance_id": "i2", "covers": ["TC-1"]}]
    both = handed_instances({"tests": twins, "unresolved": [row]}, [{"instance_id": "i1"}, {"instance_id": "i2"}],
                            {"TC-1": ["i1", "i2"]}, None, {})
    assert sorted(both) == ["i1", "i2"], "a row is about the CASE: every instance of it is the person's"
    # a. no row at all; b. every reason that is not exactly handed_to_person
    assert hi(rows=()) == {}
    for reason in ("impossible", "blocked_by_env", "contradicts_requirement", "handed_to_person ", "Handed_To_Person", ""):
        assert hi(rows=[dict(row, reason=reason)]) == {}, reason
    # c. a row for another case; a near-miss id
    assert hi(rows=[dict(row, case="TC-9")]) == {}
    assert hi(tests=[{"instance_id": "i1", "covers": ["TC-10"]}], scope={"TC-10": ["i1"]}) == {}, "TC-1 is not TC-10"
    # d. an area row of another area; e. a bare row with an area-keyed scope (the safe direction: no looser rule)
    assert hi(rows=[dict(row, case="B/TC-1")], scope={"A/TC-1": ["i1"]}) == {}
    assert hi(scope={"A/TC-1": ["i1"], "B/TC-1": ["i1"]}) == {}
    assert hi(scope={"A/TC-1": ["i1"]}) == {}
    # f. an instance proving a handed case and one that is not: partial, with its door
    mixed = [{"instance_id": "i1", "covers": ["TC-1", "TC-2"]}]
    refused: list = []
    assert hi(tests=mixed, scope={"TC-1": ["i1"], "TC-2": ["i1"]}, refused=refused) == {}
    assert [(k, i) for k, i, _s in refused] == [("partial", "i1")], refused
    assert "TC-1" in refused[0][2] and "TC-2" in refused[0][2] and "manifest_put.py" in refused[0][2], refused
    assert "run_suite" not in refused[0][2], "m-7: the profile is the person's, run_suite is no door"
    # g. a Then-remainder row alone is no whole-case hand-off
    then_only = {"tests": one, "unresolved": [], "then_bindings": [
        {"case": "TC-1", "then": 2, "status": "unresolved", "reason": "handed_to_person", "detail": "web: by hand"}]}
    assert hi(manifest=then_only) == {}
    # h. a terminal run outranks the hand-off, passed or failed
    for status in ("passed", "failed"):
        refused = []
        assert hi(runs={"i1": ({"status": status}, {}, P("work/run-blocks/b.json"))}, refused=refused) == {}, status
        assert [(k, i) for k, i, _s in refused] == [("ran", "i1")] and status in refused[0][2], refused
    # i. a manifest or a scope that cannot answer
    for bad in ({}, [], None, "x"):
        assert handed_instances(bad, [{"instance_id": "i1"}], {"TC-1": ["i1"]}, None, {}) == {}, bad
    for bad in (None, {}, {"TC-1": "i1"}, []):
        assert handed_instances({"tests": one, "unresolved": [row]}, [{"instance_id": "i1"}], bad, None, {}) == {}, bad
    # j. an item in no scope list; k. a row with no case; l. an instance the manifest holds no test row for
    assert hi(scope={"TC-1": ["i9"]}) == {}
    for blank in ("", None):
        assert hi(rows=[dict(row, case=blank)]) == {}, blank
    assert hi(tests=[{"instance_id": "other", "covers": ["TC-1"]}]) == {}, "no tests[] row for i1"
    # m. a hand-edited scope that drops a case of the test's own row does not make it handed
    refused = []
    assert hi(tests=mixed, scope={"TC-1": ["i1"], "TC-2": []}, refused=refused) == {}
    assert [(k, i) for k, i, _s in refused] == [("partial", "i1")], refused
    # runs unreadable (a raise): nobody can say none ran
    import window_record
    real = window_record._terminal_runs

    def boom(_root):
        raise OSError("unreadable")
    window_record._terminal_runs = boom
    try:
        assert handed_instances({"tests": one, "unresolved": [row]}, [{"instance_id": "i1"}], {"TC-1": ["i1"]}, ROOT) == {}
    finally:
        window_record._terminal_runs = real


def test_stage_acceptance_record():
    """X2-5: the form and binding of the stage acceptance record, its one reader, and the word table."""
    import acceptance as A
    s2 = {"id": "S2", "roles": ["qa-requirements-tester", "qa-case-critic"], "acceptance_by": "qa-case-critic"}
    good = {"stage": "S2", "role": "qa-requirements-tester", "acceptor": "qa-case-critic", "reviewed_dispatch": "dA", "verdict": "accept",
            "failure_class": None, "quote": "", "witness_paths": [], "at": "2026-11-04T10:00:00"}

    def errors(record, author="dA", stage_def=s2):
        return A.stage_acceptance_errors(record, stage_def=stage_def, author_dispatch=author)

    assert errors(good) == [], errors(good)
    reject = dict(good, verdict="reject", failure_class="spec", quote="work/requirements-register.md#R-7")
    assert errors(reject) == [], errors(reject)
    assert any("needs a quote" in e for e in errors(dict(reject, quote=" "))), "reject without a quote"
    assert any("needs failure_class" in e for e in errors(dict(reject, failure_class="opinion"))), "failure_class opinion"
    assert any("needs failure_class" in e for e in errors(dict(reject, failure_class=None)))
    assert any("failure_class null" in e for e in errors(dict(good, failure_class="spec"))), "accept carries no class"
    assert any("not one of accept|reject" in e for e in errors(dict(good, verdict="approve")))
    assert any("does not accept its own work" in e for e in errors(dict(good, acceptor="qa-requirements-tester"))), "acceptor == role"
    assert any("acceptor 'qa-code-critic'" in e for e in errors(dict(good, acceptor="qa-code-critic")))
    assert errors(dict(good, acceptor="driver")) == [], "the driver may accept"
    assert any("other bytes" in e for e in errors(dict(good, reviewed_dispatch="dOLD"))), "an old author dispatch"
    assert any("other bytes" in e for e in errors(good, author="")), "no author dispatch yet"
    missing = dict(good)
    del missing["quote"]
    assert any("missing quote" in e for e in errors(missing)), errors(missing)
    assert any("task-relative" in e for e in errors(dict(good, witness_paths=["C:/x/y"]))), "absolute path"
    assert any("task-relative" in e for e in errors(dict(good, witness_paths=["../y"]))), "escaping path"
    assert errors(dict(good, witness_paths=["work/a.md"])) == [], "empty/relative paths are legal"
    assert any("no stage acceptance for dA" in e for e in errors(None)), "no record"
    assert any("acceptor 'qa-case-critic'" in e for e in errors(good, stage_def={"id": "S2", "roles": s2["roles"]})), "no acceptance_by: the critic is no acceptor"
    # the reader: the LAST round, [] / junk read as none
    assert A.stage_acceptance({"acceptance": {"S2": [reject, good]}}, "S2") == good
    assert A.stage_acceptance({"acceptance": {"S2": [good, reject]}}, "S2") == reject
    for junk in ({}, {"acceptance": None}, {"acceptance": {"S2": "x"}}, {"acceptance": {"S2": []}}, {"acceptance": {"S2": [1]}}, None, []):
        assert A.stage_acceptance(junk, "S2") is None, junk
    # the table: the four words, nothing else; the error direction is "no verdict"
    assert [A.stage_acceptance_verdict(w) for w in ("approve", "approve_with_fixes", "concerns", "review", "ok")] == ["accept", "accept", "reject", "reject", "accept"]
    assert [A.stage_acceptance_verdict(w) for w in ("rejected", "", None, "Approve")] == [""] * 4
    form = {"header": {"verdict": "concerns"}, "stage_acceptance": {"failure_class": "capability", "quote": "q#a", "witness_paths": ["work/a.md"]}}
    record, problems = A.stage_acceptance_from_form(form, stage="S2", role="r", acceptor="a", reviewed_dispatch="dA", witness_form="work/handoffs/dC.yaml", at="t")
    assert problems == [] and record["verdict"] == "reject" and record["failure_class"] == "capability" and record["witness_paths"] == ["work/a.md"], record
    record, problems = A.stage_acceptance_from_form(dict(form, header={"verdict": "rejected"}), stage="S2", role="r", acceptor="a",
                                                    reviewed_dispatch="dA", witness_form="", at="t")
    assert record is None and "approve|approve_with_fixes|concerns|review" in problems[0], problems
    record, problems = A.stage_acceptance_from_form(dict(form, header={"verdict": "approve"}), stage="S2", role="r", acceptor="a",
                                                    reviewed_dispatch="dA", witness_form="", at="t")
    assert record["verdict"] == "accept" and record["failure_class"] is None, "an accept carries no class whatever the form says"
    # the last accepted dispatch of the author, in creation order; the author's own dispatch when it is the one being accepted
    state = {"dispatches": {"dA": {"id": "dA", "stage": "S2", "role": "qa-requirements-tester", "status": "accepted"},
                            "dC": {"id": "dC", "stage": "S2", "role": "qa-case-critic", "status": "running"},
                            "dA2": {"id": "dA2", "stage": "S2", "role": "qa-requirements-tester", "status": "accepted"},
                            "dA3": {"id": "dA3", "stage": "S2", "role": "qa-requirements-tester", "status": "superseded"}}}
    assert A.stage_author_dispatch(state, s2) == "dA2"
    assert A.stage_author_dispatch(state, s2, state["dispatches"]["dA3"]) == "dA3"
    assert A.stage_author_dispatch({}, s2) == "" and A.stage_author_dispatch(state, {}) == ""


if __name__ == "__main__":
    main()
    test_stage_acceptance_record()
    print("test_acceptance_semantics: stage acceptance record ok")
    print("=== test_acceptance_semantics: 2/2 ok ===")
