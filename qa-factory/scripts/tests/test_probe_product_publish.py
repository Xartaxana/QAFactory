"""t-2064 fix round G (B3, R2): what `red_sandbox --probe` publishes to the manifest, and how delivery names an owed model.

B3 (EP-W, AR-22, AR-28): a product receipt whose `scope` is `one_check` proves the ONE check it names; it has no level for the test as a whole.
The publisher sends the manifest nothing for it (no `tests[].sensitivity_proof.receipt_ref`, no `proven` binding with `probe_receipt_ref`), because
`case_stamp._sensitivity_receipt` and `coverage_contract` read that pair without a level. A `whole_unlisted` receipt (the factory has no reader for
the test's language) publishes as it always did. R2 (FR-19, AR-27): the state "models owed / rows not selected" is the critic's
(`review_unverified`), never the factory's (`review_unverified_factory`).

Fast (a real probe in a stand-in project, a few seconds each): the world helpers are `test_red_sandbox_probe`'s. Each docstring names the
mutation that must make its test fail. The INV about the two readers: `case_stamp` is CALLED on the manifest after the probe; coverage reads the
same pair, so the test asserts the pair it reads (a `proven` binding with `probe_receipt_ref`) is absent or untouched.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import case_stamp  # noqa: E402
import check_delivery as CD  # noqa: E402
import proof_level as PL  # noqa: E402
import red_sandbox as RS  # noqa: E402
import test_red_sandbox_probe as TP  # noqa: E402

LIVE = "work/sensitivity-receipts/test_add-live-held.json"


def world_with_live_ref(root: Path) -> dict:
    """The manifest of `test_red_sandbox_probe.upgrades_a_live_receipt...`: the row and the binding hold a valid LIVE receipt of these bytes."""
    task_root = TP.task_of(root)
    live = {"instance_id": "test_add", "case_version": "cv_1", "test_content_hash": RS.digest(root / "tests" / "test_calc.py"),
            "source_revision": "src-1", "build_id": "build-1", "mutation": "invert", "expected_assertion_failure": "x",
            "actual_failure": "x", "assertion_location": "t.py:5", "restoration_evidence": "r", "failure_kind": "assertion",
            "proof_level": "live", "probe_tool": "probe_by_code.py", "mutation_kind": "assertion", "immutable": True,
            "receipt_hash": "h-live", "probe_record": "work/probes/test_add.json"}
    TP.write_json(task_root / LIVE, live)
    TP.write_json(task_root / "work" / "probes" / "test_add.json", {
        "schema_version": 1, "probe_tool": "probe_by_code.py", "instance_id": "test_add", "verdict": "intended_failure",
        "recorded_at": "2026-09-20T10:00:00+00:00", "receipt": {"path": LIVE},
        "test_file_sha256": RS.digest(root / "tests" / "test_calc.py"), "mutation_detail": {"line": 5}})
    held = {"path": LIVE, "sha256": RS.digest(task_root / LIVE)}
    manifest = TP.manifest_of(root)
    manifest["tests"][0]["sensitivity_proof"] = {"receipt_ref": held}
    manifest["obligation_bindings"] = [{"obligation_id": "OB-ADD-1", "instance_ids": ["test_add"], "sensitivity": "proven",
                                        "proof_kind": "executed_red_probe", "probe_receipt_ref": held["path"],
                                        "design_assessment": "sufficient"}]
    TP.write_json(task_root / "work" / "automation-manifest.json", manifest)
    return held


def manifest_bytes(root: Path) -> bytes:
    return (TP.task_of(root) / "work" / "automation-manifest.json").read_bytes()


def test_one_check_receipt_publishes_nothing_and_never_downgrades():
    """INV: a manifest row and binding holding a valid LIVE receipt are BYTE-IDENTICAL after a probe that wrote a `one_check` receipt; the
    receipt file exists with that scope; `case_stamp` still reads the live ref; the note names the `product` entry door.
    Killing mutations: removing the `held_back` filter in `red_sandbox.probe` (the live ref is overwritten by one with no level);
    `_written_scope` returning `whole_unlisted`."""
    root = TP.project(TP.fake())
    task_root = TP.task_of(root)
    try:
        TP.seed_green(root, "TC-100")
        held = world_with_live_ref(root)
        TP.give_word(root, "2999-01-01T00:00:00+00:00")                     # a person's word passes the repeat: the probe really runs
        before = manifest_bytes(root)
        result = TP.probe(root, TP.mutation_request(root))
        assert result["status"] == "accepted", result
        assert len(result["receipts"]) == 1
        receipt = json.loads((task_root / result["receipts"][0]["path"]).read_text(encoding="utf-8"))
        assert receipt["scope"] == "one_check" and receipt["checks"], receipt     # the receipt file is written as before
        assert manifest_bytes(root) == before                                      # no row ref, no binding: not one byte moved
        said = " ".join(result["notes"])
        assert "`product` entry" in said and "work/probe-models/<dispatch id>.json" in said and "stay owed" in said, said
        manifest = TP.manifest_of(root)
        assert case_stamp._sensitivity_receipt(manifest["tests"][0], manifest, task_root) == held["path"]   # the live ref still speaks
        pair = [b for b in manifest["obligation_bindings"] if b.get("probe_receipt_ref") == result["receipts"][0]["path"]]
        assert pair == [] and manifest["tests"][0]["sensitivity_proof"]["receipt_ref"] == held     # what coverage reads names no new receipt
    finally:
        TP.finish_project(root)


def test_one_check_receipt_never_stamps_or_witnesses_a_fresh_row():
    """INV (EP-W false proof): on a row that holds NO proof, a `one_check` receipt leaves no `proven` binding and no row ref, so
    `case_stamp` finds no receipt (the case is not stamped automated) and coverage's pair is absent. Killing mutation: publishing the
    binding (`sensitivity: proven` + `probe_receipt_ref`) for every receipt."""
    root = TP.project(TP.fake())
    task_root = TP.task_of(root)
    try:
        TP.seed_green(root, "TC-100")
        before = manifest_bytes(root)
        result = TP.probe(root, TP.mutation_request(root))
        assert result["status"] == "accepted" and len(result["receipts"]) == 1, result
        assert manifest_bytes(root) == before
        manifest = TP.manifest_of(root)
        assert not manifest.get("obligation_bindings"), manifest.get("obligation_bindings")
        assert "sensitivity_proof" not in manifest["tests"][0]
        assert case_stamp._sensitivity_receipt(manifest["tests"][0], manifest, task_root) == ""
    finally:
        TP.finish_project(root)


def test_whole_unlisted_receipt_still_publishes(monkeypatch):
    """A test whose checks the factory cannot list (`scope: whole_unlisted`, its only door) publishes the row ref and the `proven` binding as
    before. The decision reads the scope the receipt file carries. Killing mutations: the filter holding back every receipt;
    `_written_scope` reading a constant."""
    monkeypatch.setattr(RS, "_receipt_scope", lambda *_a, **_k: (PL.WHOLE_UNLISTED, []))
    root = TP.project(TP.fake())
    task_root = TP.task_of(root)
    try:
        TP.seed_green(root, "TC-100")
        result = TP.probe(root, TP.mutation_request(root))
        assert result["status"] == "accepted" and len(result["receipts"]) == 1, result
        new = result["receipts"][0]
        assert json.loads((task_root / new["path"]).read_text(encoding="utf-8"))["scope"] == "whole_unlisted"
        manifest = TP.manifest_of(root)
        assert manifest["tests"][0]["sensitivity_proof"]["receipt_ref"] == {"path": new["path"], "sha256": new["sha256"]}
        binding = next(b for b in manifest["obligation_bindings"] if b["obligation_id"] == "OB-ADD-1")
        assert (binding["sensitivity"], binding["probe_receipt_ref"]) == ("proven", new["path"])
        assert "`product` entry" not in " ".join(result["notes"])
    finally:
        TP.finish_project(root)


def test_written_scope_reads_the_file_and_errs_toward_one_check(tmp_path):
    """`_written_scope`: the scope of the receipt file; an unreadable or scope-less file says `one_check` (nothing is published for what
    cannot be named). Killing mutation: the fallback returning `whole_unlisted`."""
    (tmp_path / "r.json").write_text(json.dumps({"scope": "whole_unlisted"}), encoding="utf-8")
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "none.json").write_text("{}", encoding="utf-8")
    ref = lambda name: {"receipt_ref": {"path": name}}      # noqa: E731
    assert RS._written_scope(tmp_path, ref("r.json")) == "whole_unlisted"
    assert RS._written_scope(tmp_path, ref("bad.json")) == "one_check"
    assert RS._written_scope(tmp_path, ref("none.json")) == "one_check"
    assert RS._written_scope(tmp_path, ref("gone.json")) == "one_check"
    assert RS._written_scope(tmp_path, {}) == "one_check"


# --- fix round H: a repeated product probe is answered by its one-check receipt ----------------------------------------

def test_repeated_product_probe_is_answered_by_its_receipt_and_only_for_its_own_call():
    """A repeat of the same bytes and the same check is `already_probed` (the receipt file untouched, nothing published); the same call made
    the walk's way (`kind=""`, any other `kind`) is NOT answered by that receipt (it proves one check only); another check, or changed
    product bytes, is not answered. Killing mutations: dropping `kind="product"` in `red_sandbox.probe` (the repeat runs); making the
    new item ignore `kind` (the walk's call is answered); making it ignore `check_key` (another check is answered); dropping its
    `_mutated_files_hold` (changed product bytes are answered)."""
    root = TP.project(TP.fake())
    task_root = TP.task_of(root)
    try:
        TP.seed_green(root, "TC-100")
        first = TP.probe(root, TP.mutation_request(root))
        assert first["status"] == "accepted" and len(first["receipts"]) == 1, first
        receipt_file = task_root / first["receipts"][0]["path"]
        before, published = receipt_file.read_bytes(), manifest_bytes(root)
        key = f"tests/test_calc.py:{TP.ASSERT_LINE}"
        entry, manifest = TP.entry_of(root), TP.manifest_of(root)

        def ask(**more):
            return PL.already_probed(entry, manifest, task_root, project=root, dispatch=TP.DISPATCH, **more)
        got = ask(kind="product", check_key=key)
        assert got["probed"] is True and got["by"] == "product_receipt", got
        assert ask(kind="product")["probed"] is True                        # no key: the bytes guard alone
        assert ask()["probed"] is False                                     # the walk's way: a product receipt never answers it
        assert ask(kind="walk")["probed"] is False                          # an unknown kind is ""
        assert ask(kind="product", check_key="tests/test_calc.py:99")["probed"] is False     # another check runs
        again = TP.probe(root, TP.mutation_request(root))
        assert again["status"] == "already_probed", again                   # end to end: no second run
        assert receipt_file.read_bytes() == before and manifest_bytes(root) == published      # untouched, nothing published
        (root / "calc.py").write_text("X = 1\n" + (root / "calc.py").read_text(encoding="utf-8"), encoding="utf-8")
        assert ask(kind="product", check_key=key)["probed"] is False        # the product bytes it broke changed: it runs
    finally:
        TP.finish_project(root)


def test_unreadable_or_other_scope_receipt_never_answers_a_repeat():
    """An unreadable receipt file, a `whole_unlisted` one and one with no `scope` (old) do not answer a product repeat: the probe runs.
    Killing mutation: skipping the `holds` / `scope` test in `_product_receipt_repeat`."""
    root = TP.project(TP.fake())
    task_root = TP.task_of(root)
    try:
        TP.seed_green(root, "TC-100")
        first = TP.probe(root, TP.mutation_request(root))
        assert first["status"] == "accepted", first
        path = task_root / first["receipts"][0]["path"]
        good = path.read_bytes()
        entry, manifest = TP.entry_of(root), TP.manifest_of(root)
        for label, text in (("unreadable", "{not json"),
                            ("whole_unlisted", json.dumps(dict(json.loads(good), scope="whole_unlisted"))),
                            ("old", json.dumps({k: v for k, v in json.loads(good).items() if k not in ("scope", "checks")}))):
            path.write_text(text, encoding="utf-8")
            got = PL.already_probed(entry, manifest, task_root, project=root, dispatch=TP.DISPATCH, kind="product",
                                    check_key=f"tests/test_calc.py:{TP.ASSERT_LINE}")
            assert got["probed"] is False, (label, got)
        path.write_bytes(good)
    finally:
        TP.finish_project(root)


# --- R2: delivery names the owner of an owed model ----------------------------------------------------------

IID = "i1"
HASH = "bytes-1"


def aggregate(root: Path, **more) -> None:
    record = {"schema_version": 1, "probe_tool": "probe_by_code.py", "instance_id": IID, "test_file_sha256": HASH, "verdict": "incomplete",
              "cause": "judgment", "checks": [], "judgment_owed": []}
    record.update(more)
    path = PL.probe_record_path(root, IID)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")


def kinds(root: Path) -> list:
    facts = {"manifest": {"tests": [{"instance_id": IID, "critic_verdict": "unverified", "covers": ["TC-1"]}]}, "cfg": {}}
    return [r["kind"] for r in CD.unverified_records(root, facts)]


def test_plain_call_state_is_the_critics_and_a_judgment_state_is_the_factorys(tmp_path, monkeypatch):
    """R2: `judgment_owed == []` with no judgment (models owed / rows not selected: `probe_plain_call_owed`) reads `review_unverified` and
    is no `PROBE_NOT_JUDGED` finding; a check still owing `--judge`, and a `cannot_judge` record, read `review_unverified_factory`; a record
    of another cause reads `review_unverified`. Killing mutation: removing the `probe_plain_call_owed` line of `_owes_factory_judgment`."""
    monkeypatch.setattr(PL, "current_test_sha", lambda *_a, **_k: HASH)
    entry = {"instance_id": IID}
    aggregate(tmp_path)
    assert PL.probe_plain_call_owed(tmp_path, IID, HASH) is True
    assert CD._owes_factory_judgment(tmp_path, entry) is False
    assert kinds(tmp_path) == ["review_unverified"]
    facts = {"manifest": {"tests": [{"instance_id": IID, "critic_verdict": "unverified", "covers": ["TC-1"]}]}, "cfg": {}}
    assert CD.factory_data_gap_findings(tmp_path, facts) == []
    aggregate(tmp_path, judgment_owed=["t.py:3"])
    assert CD._owes_factory_judgment(tmp_path, entry) is True
    assert kinds(tmp_path) == ["review_unverified_factory"]
    assert [f["code"] for f in CD.factory_data_gap_findings(tmp_path, facts)] == ["PROBE_NOT_JUDGED"]
    aggregate(tmp_path, judgment={"verdict": "cannot_judge", "why": "gone", "at": "2026-11-05T10:00:00+00:00"})
    assert CD._owes_factory_judgment(tmp_path, entry) is True
    assert kinds(tmp_path) == ["review_unverified_factory"]
    aggregate(tmp_path, cause="tooling")
    assert CD._owes_factory_judgment(tmp_path, entry) is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
