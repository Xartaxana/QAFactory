"""t-1968 N4: the probe records WHICH statement it mutated (`target`), and a probe of another line never proves the obligation.

The fact is computed from the PLAN (what was mutated), never from what failed. `proof_level.receipt_off_target` is the one reader: the window
gap `semantic_sensitivity`, `proof_level.reached` (delivery) and `keep_standing_record` ask it. An unknown target (`null`) counts as today.
Fast: pure functions and temp files; no probe is run.
"""
import json
import re
import sys
import pytest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import acceptance  # noqa: E402
import probe_by_code as PBC  # noqa: E402
import proof_level as PL  # noqa: E402
import window_record as WR  # noqa: E402

SPEC_PY = {"file": "tests/test_cart.py", "chain": [], "function": "test_cart", "param": "", "node": "tests/test_cart.py::test_cart"}
SPEC_TS = {"file": "e2e/cart.spec.ts", "language": "typescript", "node": "e2e/cart.spec.ts::in stock"}

PY_SOURCE = (b"def test_cart():\n"
             b"    total = 1\n"
             b"    assert total == 1\n"
             b"    assert (\n"
             b"        total\n"
             b"        == 2\n"
             b"    )\n")


def target(detail, spec, assertion_id):
    return PBC.target_fact(detail, spec, assertion_id)


def test_target_true_when_mutated_line_is_assertion_id():
    detail = {"line": 43, "end_line": 43}
    assert target(detail, SPEC_TS, "e2e/cart.spec.ts:43") == {"line": 43, "end_line": 43, "assertion_id": "e2e/cart.spec.ts:43",
                                                               "is_assertion_id": True}
    # the file named by a longer path of the same file counts (the project-relative tail): `_same_file`
    assert target(detail, SPEC_TS, "proj/e2e/cart.spec.ts:43")["is_assertion_id"] is True
    # E4.4: a multi-line statement holds its inner lines; its first and last line too
    multi = {"line": 40, "end_line": 44}
    for n in (40, 42, 44):
        assert target(multi, SPEC_TS, f"e2e/cart.spec.ts:{n}")["is_assertion_id"] is True, n
    assert target(multi, SPEC_TS, "e2e/cart.spec.ts:45")["is_assertion_id"] is False       # one line beyond the statement
    assert target(multi, SPEC_TS, "e2e/cart.spec.ts:39")["is_assertion_id"] is False


def test_target_false_names_at_door():
    detail = {"line": 40, "end_line": 40}
    fact = target(detail, SPEC_TS, "e2e/cart.spec.ts:43")
    assert fact["is_assertion_id"] is False
    note = PBC._off_target_note(fact)
    assert "--at 43" in note and "line 40" in note and "e2e/cart.spec.ts:43" in note and "unverified" in note, note
    # the id of another file than the probed one prints its own spelling, so the door opens (N1: `--at <file>:<line>`)
    elsewhere = PBC._off_target_note(fact, "e2e/other.spec.ts")
    assert "--at e2e/cart.spec.ts:43" in elsewhere, elsewhere
    assert "--at 43" in PBC._off_target_note(fact, "e2e/cart.spec.ts")
    # another file is another check
    other = target(detail, SPEC_TS, "e2e/other.spec.ts:40")
    assert other["is_assertion_id"] is False, other


def test_target_null_when_absent():
    detail = {"line": 40, "end_line": 40}
    for absent in (None, "", "   ", "assert-total", "e2e/cart.spec.ts", "e2e/cart.spec.ts:", "e2e/cart.spec.ts:4x", 7):
        fact = target(detail, SPEC_TS, absent)
        assert fact["is_assertion_id"] is None, (absent, fact)
        assert fact["line"] == 40 and fact["end_line"] == 40
    # an unknown is never off-target: the receipt counts as today (E4.1)
    assert PL.receipt_off_target({"target": target(detail, SPEC_TS, None)}) == ""
    assert PL.receipt_off_target({}) == "" and PL.receipt_off_target(None) == ""            # E4.5: no `target` (written before N4)
    assert PL.receipt_off_target({"target": "x"}) == "" and PL.receipt_off_target({"target": {}}) == ""


def test_target_python_path():
    # the Python plan (`plan_mutation`) mutates the first assert; `detail` carries its line and end_line
    _mutated, detail = PBC.plan_mutation(PY_SOURCE, SPEC_PY, "invert", "i1")
    assert (detail["line"], detail["end_line"]) == (3, 3), detail
    assert target(detail, SPEC_PY, "tests/test_cart.py:3")["is_assertion_id"] is True
    off = target(detail, SPEC_PY, "tests/test_cart.py:6")                                    # the second, multi-line assert
    assert off["is_assertion_id"] is False
    note = PBC._off_target_note(off)
    assert "--at 6" in note and "not read" not in note and "unverified" in note, note        # Python reads `--at` now: the same door as every language
    # a helper the oracle followed to: `detail["file"]` is the probed file
    helper = dict(detail, file="tests/helpers.py")
    assert target(helper, SPEC_PY, "tests/test_cart.py:3")["is_assertion_id"] is False
    assert target(helper, SPEC_PY, "tests/helpers.py:3")["is_assertion_id"] is True


def new_record(tmp_path, detail, spec, assertion_id):
    entry = {"instance_id": "i1", "case": "TC-1", "covers": ["TC-1"], "obligation_ids": ["O-1"], "obligation_hash": "oh",
             "defect_location": "src/app.py:8"}
    if assertion_id:
        entry["assertion_id"] = assertion_id
    ctx = SimpleNamespace(task="T-1", dispatch="d1", instance_id="i1", case="TC-1", spec=spec, entry=entry, root=tmp_path,
                          path=tmp_path / "tests" / "test_cart.py", mutation="invert")
    (tmp_path / "tests").mkdir(exist_ok=True)
    oracle = tmp_path / "tests" / "test_cart.py"
    oracle.write_bytes(PY_SOURCE)
    detail = dict(detail, marker="m")
    return PBC._new_record(ctx, detail, {}, PY_SOURCE, PY_SOURCE, oracle)


def test_target_in_window_probe_block(tmp_path):
    record = new_record(tmp_path, {"line": 3, "end_line": 3}, SPEC_PY, "tests/test_cart.py:6")
    assert record["target"]["is_assertion_id"] is False and record["target"]["assertion_id"] == "tests/test_cart.py:6"
    assert "target" in PBC.WINDOW_PROBE_FIELDS
    assert PBC.window_probe(record)["target"] == record["target"]
    # the receipt core carries the same fact
    facts = {key: "x" for key in PBC.FACT_KEYS}
    record.update(mutation="invert", expected_reason="r", actual_reason="r", expected_location="tests/test_cart.py:3",
                  failure_kind="assertion", record="work/probes/i1.json", restore={"sha256": "s"})
    core = PBC._receipt_core(record, "i1", facts, "restored")
    assert core["target"] == record["target"]
    assert PL.receipt_off_target(core) == "the probe broke line 3, not the obligation's check at tests/test_cart.py:6"
    # no manifest assertion_id: null, and the record still says which line was mutated
    bare = new_record(tmp_path, {"line": 3, "end_line": 3}, SPEC_PY, "")
    assert bare["target"] == {"line": 3, "end_line": 3, "assertion_id": None, "is_assertion_id": None}
    # N1: a plan that knows where its target came from says so (`source`); one that does not (a record before N1) says nothing
    assert target({"line": 3, "end_line": 3, "target_source": "assertion_id"}, SPEC_PY, "tests/test_cart.py:3")["source"] == "assertion_id"
    assert "source" not in target({"line": 3, "end_line": 3}, SPEC_PY, "tests/test_cart.py:3")


def test_printed_line_door_holds_a_check():
    """N1: the `--at` an off-target note prints passes `check_on_line` - the first half of the door (the repeat check is N1b's)."""
    detail = {"line": 3, "end_line": 3}
    off = target(detail, SPEC_PY, "tests/test_cart.py:6")
    printed = int(re.search(r"--at (\d+)", PBC._off_target_note(off)).group(1))
    facts = PBC.check_on_line(PY_SOURCE, "tests/test_cart.py", None, printed)
    assert facts["found"] and facts["found"]["line"] == 4 and facts["found"]["end_line"] == 7, facts      # 6 lies inside the multi-line assert
    for inner in (4, 5, 6, 7):                                                    # every line of the statement opens the door
        assert PBC.check_on_line(PY_SOURCE, "t.py", None, inner)["found"]["line"] == 4, inner


def window_item(is_assertion_id):
    probe = {"verdict": "intended_failure", "input_hash": "input", "obligation_ids": ["O-1"], "obligation_hash": "ohash",
             "assertion_id": "tests/test_app.py:9", "defect_location": "src/app.py:8", "expected_location": "tests/test_app.py:9",
             "actual_location": "tests/test_app.py:9", "expected_reason": "wrong total", "actual_reason": "wrong total",
             "failure_kind": "assertion", "mutation_kind": "assertion", "proof_level": "live", "evidence_ref": "proof.txt"}
    if is_assertion_id is not ...:
        probe["target"] = {"line": 4, "end_line": 4, "assertion_id": "tests/test_app.py:9", "is_assertion_id": is_assertion_id}
    return probe


def window(tmp_path, probe):
    import hashlib
    proof = tmp_path / "proof.txt"
    proof.write_text("proof")
    digest = hashlib.sha256(proof.read_bytes()).hexdigest()
    return {"schema_version": 2, "input_hash": "input", "required_quality_checks": [],
            "instances": [{"schema_version": 2, "instance_id": "i1", "input_hash": "input", "outcome": "passed",
                           "review": {"verdict": "approved", "input_hash": "input"}, "obligation_ids": ["O-1"],
                           "obligation_hash": "ohash", "assertion_id": "tests/test_app.py:9", "defect_location": "src/app.py:8",
                           "change_disposition": "new_or_changed", "change_basis_ref": "diff", "probe": probe,
                           "evidence_refs": [{"path": "proof.txt", "sha256": digest}]}]}


def test_off_target_receipt_is_semantic_gap(tmp_path):
    assert acceptance.validate_window(window(tmp_path, window_item(False)), tmp_path) == ["semantic_sensitivity:i1"]
    # the positional invariant: an on-target, an unknown and a pre-N4 probe count exactly as today
    for state in (True, None, ...):
        assert acceptance.validate_window(window(tmp_path, window_item(state)), tmp_path) == [], state


def entry_with_receipt(tmp_path, is_assertion_id):
    receipt = {"proof_level": "live", "target": {"line": 4, "end_line": 4, "assertion_id": "t.py:9", "is_assertion_id": is_assertion_id}}
    if is_assertion_id is ...:
        receipt.pop("target")
    return {"instance_id": "i1", "sensitivity_proof": {"receipt_ref": {"path": "r.json", "sha256": "s"}}}, receipt


def reached_with(monkeypatch, tmp_path, is_assertion_id):
    entry, receipt = entry_with_receipt(tmp_path, is_assertion_id)
    monkeypatch.setattr(PL, "_evaluate", lambda variant, task_root, instance_id, now=None: ("live", [], receipt, False, False, "raw"))
    return PL.reached(entry, {}, tmp_path, now={"input_hash": "h"})


def test_off_target_receipt_not_reached_at_delivery(monkeypatch, tmp_path):
    for state in (True, None, ...):
        got = reached_with(monkeypatch, tmp_path, state)
        assert got["level"] == "live" and got["issues"] == [], (state, got)                 # counts exactly as today
    off = reached_with(monkeypatch, tmp_path, False)
    assert off["level"] is None and off["ref"] == {}, off
    assert len(off["issues"]) == 1 and "the probe broke line 4, not the obligation's check at t.py:9" in off["issues"][0], off
    assert "--at" in off["issues"][0] and "unverified" in off["issues"][0]                  # never a dead end (FR-57)


def test_off_target_gap_names_both_doors():
    note = WR.off_target_note("i1", window_item(False))          # `build` adds this note beside the probe it built
    assert note and note[:2] == ("i1", "semantic_sensitivity"), note
    missing, door = WR._explain_parts("semantic_sensitivity:i1", [note])
    assert "--at <n>" in door and "unverified" in door and "probe_by_code.py" in door, door
    assert "not proved" in door and missing.startswith("the probe broke line 4, not the obligation's check"), (missing, door)
    # the other gaps keep their own doors
    assert "--at" not in WR._explain_parts("sensitivity:i1", [note])[1]


def test_off_target_door_only_for_the_off_target_cause():
    """Q1: the gap `semantic_sensitivity` has other causes (obligation hash, ...); its door names `--at` only when the probe is off target."""
    for state in (True, None, ...):
        assert WR.off_target_note("i1", window_item(state)) == (), state
    assert WR.off_target_note("i1", None) == () and WR.off_target_note("i1", {}) == ()
    missing, door = WR._explain_parts("semantic_sensitivity:i1", [])           # no note: the plain door of the other causes
    assert "--at" not in door and "unverified" not in door, door
    # a note of another instance does not leak to this one
    other = WR.off_target_note("i2", window_item(False))
    assert "--at" not in WR._explain_parts("semantic_sensitivity:i1", [other])[1]


def receipt_of(tmp_path, assertion_id, proved_by=None):
    record = new_record(tmp_path, {"line": 3, "end_line": 3}, SPEC_PY, assertion_id)
    facts = {key: "x" for key in PBC.FACT_KEYS}
    record.update(mutation="invert", expected_reason="wrong total", actual_reason="wrong total",
                  expected_location="tests/test_app.py:3", failure_kind="assertion", record="work/probes/i1.json",
                  restore={"sha256": "s"}, verdict="intended_failure")
    if proved_by:
        record["proved_by"] = proved_by
    return PBC._receipt_core(record, "i1", facts, "restored")


def test_window_gets_the_gap_from_a_real_receipt(tmp_path):
    """Q2: the receipt `probe_by_code` writes has no `window_probe`; the window's block is read field by field, and `target` and
    `proved_by` must survive that read or the gap never fires."""
    item = {"obligation_ids": ["O-1"], "obligation_hash": "ohash", "assertion_id": "tests/test_app.py:9",
            "defect_location": "src/app.py:8"}
    ref = {"path": "proof.txt"}
    off = WR._probe_from_receipt(receipt_of(tmp_path, "tests/test_cart.py:6", "marker"), ref, item)
    assert off["target"]["is_assertion_id"] is False and off["proved_by"] == "marker", off
    on = WR._probe_from_receipt(receipt_of(tmp_path, "tests/test_cart.py:3"), ref, item)
    assert on["target"]["is_assertion_id"] is True and "proved_by" not in on, on         # absent stays absent
    null = WR._probe_from_receipt(receipt_of(tmp_path, ""), ref, item)
    assert null["target"]["is_assertion_id"] is None
    old = WR._probe_from_receipt({k: v for k, v in receipt_of(tmp_path, "tests/test_cart.py:6").items() if k != "target"}, ref, item)
    assert "target" not in old                                                           # written before N4: nothing invented
    # the gap, through the same validator the window goes through
    for block, gaps in ((off, ["semantic_sensitivity:i1"]), (on, []), (null, [])):
        probe = dict(window_item(...), **{key: block[key] for key in ("target", "proved_by") if key in block})
        assert acceptance.validate_window(window(tmp_path, probe), tmp_path) == gaps, (block["target"], gaps)
    assert "proved_by" in PBC.WINDOW_PROBE_FIELDS                                        # an older-record block carries it too


def test_unknown_target_note_is_printed_in_verdict_info():
    """Q3, E4.1: a `null` target counts as today and is SAID; a known one and a pre-N4 probe say nothing."""
    def info_for(*probes):
        info = []
        WR._unknown_target_notes({"instances": [{"instance_id": f"i{n}", "probe": p} for n, p in enumerate(probes)]}, info)
        return info
    assert len(info_for(window_item(None))) == 1
    said = info_for(window_item(None))[0]
    assert "could not be compared with the obligation's assertion" in said and "<file>:<line>" in said and "(i0)" in said, said
    assert info_for(window_item(True), window_item(False), window_item(...)) == []
    assert info_for("not a dict", None) == []


def test_off_target_record_does_not_stand_over_reprobe(tmp_path):
    path = tmp_path / "rec.json"
    judgment = {"verdict": "incomplete", "cause": "judgment", "notes": ["asked the critic"], "recorded_at": "t"}

    def stored(state):
        record = {"verdict": "intended_failure", "test_file_sha256": "abc"}
        if state is not ...:
            record["target"] = {"line": 4, "end_line": 4, "assertion_id": "t.py:9", "is_assertion_id": state}
        path.write_text(json.dumps(record), encoding="utf-8")

    for state in (True, None, ...):                          # an on-target (or unknown) record keeps standing, as today
        stored(state)
        assert PBC.keep_standing_record(path, dict(judgment)) is True, state
        assert json.loads(path.read_text(encoding="utf-8"))["verdict"] == "intended_failure"
    stored(False)                                            # an off-target one does not: the re-probe is stored and judgeable
    assert PBC.keep_standing_record(path, dict(judgment)) is False
    assert json.loads(path.read_text(encoding="utf-8"))["verdict"] == "intended_failure"      # untouched by the keeper
    # a re-probe that is again off target stands over nothing either
    assert PBC.keep_standing_record(path, dict(judgment, target={"is_assertion_id": False})) is False


if __name__ == "__main__": raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
