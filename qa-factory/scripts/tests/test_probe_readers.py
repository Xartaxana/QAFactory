"""t-2064 node P6: the readers of the probe's aggregate, and the product receipt (EP-I, EP-K, EP-T, EP-W).

Fast: every record is a real file in a temp dir, written by hand in the shape `probe_by_code._aggregate_record` writes (the producer is P4b's and
has its own tests); the readers under test are `window_record._probe_from_receipt`, `unproved_keys_text`, `probe_gap_block`,
`proof_level._evaluate` / `reached`, `red_sandbox.write_sensitivity_receipts` and the unchanged `acceptance.validate_window`. Each docstring names
the mutation that must make its test fail.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import acceptance  # noqa: E402
import contract as C  # noqa: E402
import probe_by_code as PBC  # noqa: E402
import proof_level as PL  # noqa: E402
import red_sandbox as RS  # noqa: E402
import window_record as WR  # noqa: E402
from event_store import content_hash  # noqa: E402
from test_probe_target_fact import window, window_item  # noqa: E402

IID = "i1"
HASH = "input"
JUDGED_AT = "2026-11-05T10:00:00+00:00"
LATER = "2026-11-05T10:00:01+00:00"


def entry_of(key: str, kind: str = "actual") -> dict:
    return {"check": key, "kind": kind, kind: "999", "supposes": f"the value of {key}"}


def row(key: str, verdict: str = "intended_failure", **more) -> dict:
    """One `checks[]` row of the aggregate, as `_aggregate_rows` writes it (the fields the readers use)."""
    base = {"key": key, "statement_sha": f"sha-{key}", "entry": entry_of(key), "verdict": verdict,
            "cause": "judgment" if verdict == "incomplete" else None, "probe_kind": "actual"}
    base.update(more)
    return base


def write_aggregate(root: Path, rows: list, **more) -> dict:
    record = {"schema_version": 1, "probe_tool": "probe_by_code.py", "instance_id": IID, "test_file_sha256": HASH,
              "verdict": "incomplete", "checks": rows, "plan_remaining": [], "plan_unfinished": False, "receipt": None}
    record.update(more)
    path = PL.probe_record_path(root, IID)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")
    return record


def live_receipt(rows: list) -> dict:
    """The receipt `attach_receipt` would write for these rows: `_receipt_core`, the one producer of `checks`."""
    record = {"mutation": "invert", "expected_reason": "wrong total", "actual_reason": "wrong total", "expected_location": "tests/test_app.py:3",
              "failure_kind": "assertion", "record": f"work/probes/{IID}.json", "verdict": "intended_failure", "checks": rows}
    return PBC._receipt_core(record, IID, {key: "x" for key in PBC.FACT_KEYS}, "restored")


ITEM = {"instance_id": IID, "obligation_ids": ["O-1"], "obligation_hash": "ohash", "assertion_id": "tests/test_app.py:9",
        "defect_location": "src/app.py:8"}


def probe_over(block: dict) -> dict:
    """A window `probe` that is valid in every field but the ones the block under test decides: its verdict, scope and checks."""
    probe = window_item(...)
    probe["verdict"] = block["verdict"]
    probe.update({k: block[k] for k in ("scope", "checks") if k in block})
    return probe


def gaps_of(tmp_path: Path, block: dict) -> list:
    return acceptance.validate_window(window(tmp_path, probe_over(block)), tmp_path)


# --- item 1: the readers read the aggregate as it stands -------------------------------------------------

def test_partial_aggregate_is_sensitivity_gap(tmp_path):
    """A walk that proved one check of three has no receipt; its window block is not `intended_failure`, so `acceptance.validate_window`
    (unedited) gives `sensitivity:` as for any unproved test, and the window's text names the unproved keys with their verdicts.
    Killing mutations: `unproved_keys_text` returning "" for a partial aggregate; `_probe_from_receipt` stamping `intended_failure`."""
    write_aggregate(tmp_path, [row("t.py:3"), row("t.py:4", "no_failure", cause=None), row("t.py:5", "not_reached", cause=None)])
    said = WR.unproved_keys_text(tmp_path, IID, HASH)
    assert "1 of 3 checks of this test are proved" in said and "t.py:4 (no_failure)" in said and "t.py:5 (not_reached)" in said, said
    assert "t.py:3" not in said and "; " not in said, said                       # the proved key is not named; the sentence has no note separator
    assert WR._keys_first(tmp_path, {"instance_id": IID, "input_hash": HASH}).startswith("1 of 3 checks")
    assert gaps_of(tmp_path, {"verdict": "incomplete"}) == ["sensitivity:i1"]
    assert WR.unproved_keys_text(tmp_path, IID, "other bytes") == ""             # an aggregate of other bytes names nothing about these


def test_full_aggregate_passes_validate_window(tmp_path):
    """Every check proved (`not_owed` set aside): the receipt's block is `intended_failure`, the unedited validator gives no gap, and the
    aggregate names no unproved key. Killing mutation: `_probe_from_receipt` marking a receipt stale whose entries are the ones in play."""
    rows = [row("t.py:3"), row("t.py:4"), row("t.py:5", "not_owed", cause=None, entry=entry_of("t.py:5", "not_here"), reason="a branch it never takes")]
    write_aggregate(tmp_path, rows, verdict="intended_failure")
    block = WR._probe_from_receipt(live_receipt(rows), {"path": "proof.txt"}, ITEM, tmp_path)
    assert block["verdict"] == "intended_failure" and "stale_checks" not in block, block
    assert len(block["checks"]) == 3 and block["probe_tool"] == "probe_by_code.py"
    assert gaps_of(tmp_path, block) == []
    said = WR.unproved_keys_text(tmp_path, IID, HASH)
    assert "not proved" not in said and "t.py:5 (a branch it never takes)" in said, said


def test_old_receipt_info_line(tmp_path):
    """An old product receipt (no `scope`, `probe_tool: red_sandbox.py`) stands as before and the verdict says it proves one check, once;
    a receipt with a scope or a live one does not get the line. Killing mutation: `_probe_scope_notes` reading `scope` absent as no line."""
    old = {"proof_level": "catches_broken_product", "probe_tool": "red_sandbox.py", "assertion_location": "tests/test_app.py:3",
           "expected_assertion_failure": "denied", "actual_failure": "denied", "failure_kind": "assertion", "test_content_hash": "x"}
    block = WR._probe_from_receipt(old, {"path": "proof.txt"}, ITEM)
    assert block["verdict"] == "intended_failure" and "scope" not in block and "checks" not in block, block
    info = []
    WR._probe_scope_notes({"instances": [{"instance_id": IID, "probe": block}]}, info)
    assert len(info) == 1 and "proves one check" in info[0] and f"({IID})" in info[0], info
    for other in ({**block, "scope": "whole_unlisted"}, {**block, "probe_tool": "probe_by_code.py", "checks": [{"key": "t.py:3"}]}, "not a dict"):
        said = []
        WR._probe_scope_notes({"instances": [{"instance_id": IID, "probe": other}]}, said)
        assert "proves one check" not in " ".join(said), other
    # F7 (EP-I): an old LIVE receipt (`probe_by_code.py`, no `checks`) gets the same line through the same carrier, once, and its block is untouched
    live_old = {k: v for k, v in live_receipt([row("t.py:3")]).items() if k != "checks"}
    live_block = WR._probe_from_receipt(live_old, {"path": "proof.txt"}, ITEM, tmp_path)
    assert live_block["verdict"] == "intended_failure" and "checks" not in live_block, live_block
    said = []
    WR._probe_scope_notes({"instances": [{"instance_id": IID, "probe": live_block}]}, said)
    assert len(said) == 1 and "proves one check" in said[0] and "live receipt" in said[0] and f"({IID})" in said[0], said
    assert live_block["verdict"] == "intended_failure" and gaps_of(tmp_path, live_block) == []
    new_block = WR._probe_from_receipt(live_receipt([row("t.py:3")]), {"path": "proof.txt"}, ITEM, tmp_path)
    said = []
    WR._probe_scope_notes({"instances": [{"instance_id": IID, "probe": new_block}]}, said)
    assert said == [], said                                    # a new receipt (with `checks`) says nothing


def test_id_on_blank_line_unknown_not_off_target(tmp_path):
    """EP-I: the id's line lies on no check (arm B's `:46`): the aggregate's `target.is_assertion_id` is None, which counts, says so in the
    info, and is NEVER off target. Killing mutation: `receipt_off_target` reading None as False."""
    probe = window_item(None)
    assert PL.receipt_off_target(probe) == "" and WR.off_target_note(IID, probe) == ()
    info = []
    WR._unknown_target_notes({"instances": [{"instance_id": IID, "probe": probe}]}, info)
    assert len(info) == 1 and f"({IID})" in info[0], info
    assert acceptance.validate_window(window(tmp_path, probe), tmp_path) == []


def test_id_outside_body_off_target(tmp_path):
    """EP-I: the id's line lies outside the body and the plan: `is_assertion_id` False is off target, a `semantic_sensitivity:` gap with
    its door. Killing mutation: `receipt_off_target` returning "" for False."""
    probe = window_item(False)
    assert "not the obligation's check" in PL.receipt_off_target(probe)
    assert WR.off_target_note(IID, probe)[:2] == (IID, "semantic_sensitivity")
    assert acceptance.validate_window(window(tmp_path, probe), tmp_path) == ["semantic_sensitivity:i1"]


def test_person_after_critic_by_check(tmp_path, monkeypatch):
    """EP-K (fix round D, B2): the person's `probe not proved: <case>` is read only after the critic's `cannot_judge`, and its block names the
    case's unproved CHECKS (one word, whole case). Run on the record the REAL producers write - a walk with one check `cannot_judge` and one
    still owing `--judge` (the aggregate carries no judgment: the word names nothing), then the second `cannot_judge` too (the aggregate reads
    `cannot_judge`, the word is read and the block names the checks). The hand-built aggregate of before had no producer (AR-22). Killing
    mutations: `probe_gap_block` not prefixing the keys; reading the word while one row still owes `--judge`; `_judgment_fold` writing no
    top-level `judgment`."""
    from test_probe_every_check import TW, judge_check, judged_world
    world, walked = judged_world(tmp_path, monkeypatch, scenario=lambda w, run: [TW.row("failed", "boom: the badge was empty")])
    pipe = {"stage_overrides": [{"stage": "S5", "match": "probe not proved: CASE-A", "decision": "go on", "at": "2999-01-01T00:00:00+00:00"}]}
    words = C.probe_not_proved_words(pipe)
    item = {"instance_id": "i1", "input_hash": walked["test_file_sha256"], "outcome": "passed"}
    assert WR.probe_gap_block(world.task_root, item, ["CASE-A"], {}, None, words) is None             # the critic has not judged: the word is not read
    judge_check(world, check=world.keys[0], verdict="cannot_judge", quote="", why="it threw first")
    assert WR.probe_gap_block(world.task_root, item, ["CASE-A"], {}, None, words) is None             # the other check still owes `--judge`
    judge_check(world, check=world.keys[1], verdict="cannot_judge", quote="", why="the page is gone")
    block = WR.probe_gap_block(world.task_root, item, ["CASE-A"], {}, None, words)
    assert block is not None and block["named_by"] == "probe not proved: CASE-A", block
    assert world.keys[0] in block["why"] and world.keys[1] in block["why"] and "could not judge it: " in block["why"] and "it threw first" in block["why"], block
    assert WR.probe_gap_block(world.task_root, item, ["CASE-B"], {}, None, words) is None             # a word about another case names nothing


def test_not_owed_listed_in_window(tmp_path):
    """EP-T: a `not_owed` check is listed by key with the critic's reason, for the tier above, and a reason with `; ` in it never splits the
    note (`_explain_parts` splits at the first `; `). Killing mutations: dropping the not-owed clause; not folding `; ` in the reason."""
    write_aggregate(tmp_path, [row("t.py:3"), row("t.py:4", "incomplete"),
                               row("t.py:9", "not_owed", cause=None, entry=entry_of("t.py:9", "not_here"), reason="guest kept; no notice shown")])
    said = WR.unproved_keys_text(tmp_path, IID, HASH)
    assert "t.py:9 (guest kept, no notice shown)" in said and "t.py:4 (incomplete)" in said and "; " not in said, said
    missing, door = WR._explain_parts(f"{IID}: {C.PROBE_MISSING_ERROR}", [(IID, "probe", WR._keys_first(tmp_path, {"instance_id": IID, "input_hash": HASH})
                                                            + WR._origin_text("probe") + WR.PROBE_GAP_DOOR)])
    assert "t.py:9" in missing and "the tier above" in missing and door, (missing, door)
    write_aggregate(tmp_path, [row("t.py:3"), row("t.py:4", "not_owed", cause=None, reason="")])
    assert "no reason recorded" in WR.unproved_keys_text(tmp_path, IID, HASH)                  # an empty reason is said, never hidden


# --- items 2-5: the product receipt ----------------------------------------------------------------------

def product_receipt(task: Path, location: str = "tests/test_t.py:4", file=None) -> tuple:
    """`(entry, receipt dict, ref)` of a product receipt written by the unedited producer in the strictest contract mode."""
    (task / "state").mkdir(exist_ok=True)
    (task / "state/controller.json").write_text(json.dumps({"plan_contract_mode": "new"}), encoding="utf-8")
    binding = {"case_version": "cv_abc", "test_content_hash": "test-hash", "source_revision": "source", "build_id": "build",
               "restoration_evidence": "restored-hash"}
    target = {"instance_id": IID, "expected_location": location, "expected_reason": "denied", "mutation_kind": "real_behavior"}
    result = {"instance_id": IID, "status": "failed", "failure_kind": "assertion", "location": location, "reason": "denied",
              "semantic_verdict": "intended_failure"}
    identity = {IID: {"test_file": file}} if file else None
    refs = RS.write_sensitivity_receipts(task, {"repo": str(task), "original_hashes": {}, "targets": [target]}, [result], {IID: binding},
                                         identity=identity)
    entry = {"instance_id": IID, "case_version_links": [{"version": "cv_abc"}], "sensitivity_proof": refs[IID]}
    return entry, json.loads((task / refs[IID]["receipt_ref"]["path"]).read_text(encoding="utf-8")), refs[IID]["receipt_ref"]


NOW = {"input_hash": "test-hash", "instance_identity": {}}


def test_product_receipt_has_scope_and_checks(tmp_path):
    """EP-W: the receipt names what it proves, inside its hash: `one_check` and the key of its `assertion_location`; `whole_unlisted` and
    `[]` for a suffix with no reader; `one_check` with `[]` for a location it cannot read; an unreadable detector table reads as `one_check`.
    The strict contract still takes it. Killing mutations: `scope` outside the hash; the suffix test inverted; `[]` filled for an unread location."""
    entry, receipt, _ref = product_receipt(tmp_path)
    assert receipt["scope"] == "one_check" and receipt["checks"] == [{"key": "tests/test_t.py:4", "probe_kind": "product"}], receipt
    assert receipt["receipt_hash"] == content_hash({k: v for k, v in receipt.items() if k != "receipt_hash"})   # scope and checks are INSIDE the hash
    assert C.sensitivity_proof_issues(entry, tmp_path) == []                                                      # the contract refuses no unknown key
    other = tmp_path / "other"
    other.mkdir()
    unlisted = product_receipt(other, "tests/t.zzz:4")[1]
    assert (unlisted["scope"], unlisted["checks"]) == ("whole_unlisted", []), unlisted
    assert RS._receipt_scope("", "not a location") == ("one_check", [])
    assert RS._receipt_scope("tests/t.zzz", "") == ("whole_unlisted", [])
    assert RS._receipt_scope("", "") == ("one_check", [])                                                        # no file, no suffix: never "unlisted"
    import assertion_detectors as AD
    saved = AD.assertion_detectors
    try:
        def broken(*_a, **_k):
            raise AD.DetectorsUnreadable("unreadable")
        AD.assertion_detectors = broken
        assert RS._receipt_scope("tests/t.zzz", "tests/t.zzz:4") == ("one_check", [{"key": "tests/t.zzz:4", "probe_kind": "product"}])
    finally:
        AD.assertion_detectors = saved


def test_one_check_product_is_no_level(tmp_path):
    """EP-W: a `one_check` receipt shows no level, with one issue that names the door; `reached` follows by itself and shields nothing.
    Killing mutation: removing the `scope` line of `_evaluate`."""
    entry, _receipt, _ref = product_receipt(tmp_path)
    level, issues, _r, unknown, over, _how = PL._evaluate(entry, tmp_path, IID, NOW)
    assert level is None and issues == [PL.WHY_ONE_CHECK] and not unknown and not over, (level, issues)
    assert "`product` entry" in issues[0] and "stay owed" in issues[0]
    got = PL.reached(entry, {}, tmp_path, now=NOW)
    assert got["level"] is None and got["ref"] == {} and PL.WHY_ONE_CHECK in got["issues"], got
    assert PL.valid_level(entry, entry["sensitivity_proof"]["receipt_ref"], tmp_path) is None


def test_one_check_product_is_sensitivity_gap(tmp_path):
    """EP-W: the window reads the one-check receipt (the old lookups still find it) as `partial_product`; the unedited validator gives
    `sensitivity:`, and the note names the key and the `product` entry as the door. Killing mutation: `_probe_from_receipt` leaving the verdict."""
    _entry, receipt, ref = product_receipt(tmp_path)
    block = WR._probe_from_receipt(receipt, ref, ITEM, tmp_path)
    assert block["verdict"] == WR.PARTIAL_PRODUCT and block["scope"] == "one_check" and block["checks"][0]["key"] == "tests/test_t.py:4", block
    assert gaps_of(tmp_path, block) == ["sensitivity:i1"]
    note = WR._scope_note(IID, block, ref)
    assert note[:2] == (IID, "sensitivity") and "tests/test_t.py:4" in note[2] and '"product"' in note[2] and "probe-models" in note[2], note
    missing, door = WR._explain_parts("sensitivity:i1", [note])
    assert "proves one check" in missing and "probe_by_code.py" in door


def test_old_product_receipt_stands(tmp_path):
    """EP-I: a receipt written before this batch (no `scope`, no `checks`) keeps its level and reads exactly as before. Killing mutation:
    `_evaluate` treating an absent `scope` as `one_check`."""
    entry, receipt, _ref = product_receipt(tmp_path)
    old = {k: v for k, v in receipt.items() if k not in ("scope", "checks", "receipt_hash")}
    old["receipt_hash"] = content_hash(old)
    path = tmp_path / "work/sensitivity-receipts/old.json"
    path.write_text(json.dumps(old), encoding="utf-8")
    import hashlib
    entry["sensitivity_proof"] = {"receipt_ref": {"path": "work/sensitivity-receipts/old.json", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}
    level, issues, *_ = PL._evaluate(entry, tmp_path, IID, NOW)
    assert level == "catches_broken_product" and issues == [], (level, issues)
    block = WR._probe_from_receipt(old, {"path": "proof.txt"}, ITEM, tmp_path)
    assert block["verdict"] == "intended_failure" and "scope" not in block and "stale_checks" not in block
    assert gaps_of(tmp_path, block) == []


def test_no_entry_language_product_stands_with_note(tmp_path):
    """EP-W: a test whose language the factory cannot read keeps its only door: the `whole_unlisted` receipt keeps its level and says so.
    Killing mutation: `_evaluate` ending every `scope` that is not absent."""
    entry, receipt, ref = product_receipt(tmp_path, "tests/t.zzz:4")
    assert receipt["scope"] == "whole_unlisted"
    level, issues, *_ = PL._evaluate(entry, tmp_path, IID, NOW)
    assert level == "catches_broken_product" and issues == [], (level, issues)
    block = WR._probe_from_receipt(receipt, ref, ITEM, tmp_path)
    assert block["verdict"] == "intended_failure" and block["scope"] == "whole_unlisted" and block["checks"] == []
    info = []
    WR._probe_scope_notes({"instances": [{"instance_id": IID, "probe": block}]}, info)
    assert len(info) == 1 and "cannot list this test's checks" in info[0], info
    assert gaps_of(tmp_path, block) == [] and WR._scope_note(IID, block, ref) == ()


def test_product_entry_counts_its_key_only(tmp_path):
    """EP-W/EP-K, the reading side: 8 checks, one proved by a `product` entry, 7 owed: the aggregate is `incomplete`, has no receipt, the
    window names exactly the 7 and says 1 of 8; approved never stands on one of several. (`_product_entry_holds`, the entry's join, is P4b
    item 6 and not in this branch: the aggregate here is the shape that join would write.) Killing mutation: `unproved_keys_text` counting
    proved rows of any kind as the whole."""
    keys = [f"t.py:{n}" for n in range(3, 11)]
    rows = [row(keys[0], probe_kind="product", entry=entry_of(keys[0], "product"), proved_by="critic")] + \
           [row(k, "incomplete") for k in keys[1:]]
    write_aggregate(tmp_path, rows)
    said = WR.unproved_keys_text(tmp_path, IID, HASH)
    assert "1 of 8 checks of this test are proved" in said, said
    for key in keys[1:]:
        assert f"{key} (incomplete)" in said
    assert keys[0] not in said
    assert gaps_of(tmp_path, {"verdict": "incomplete"}) == ["sensitivity:i1"]
    assert PL.reached({"instance_id": IID}, {}, tmp_path, now={"input_hash": HASH})["level"] is None     # no receipt reaches the test


def test_receipt_of_a_changed_model_is_not_live(tmp_path):
    """P4b hand-over: a receipt whose `checks[].entry_sha` / `statement_sha` no longer match the entries in play (the aggregate's rows, or the
    newer per-check record a kept aggregate hides) reads `model_changed` naming the keys, never `intended_failure`; `checks: []` is never a
    pass; an old receipt (no `checks`) and an absent aggregate read as before; a kept aggregate's `last_attempt` is carried and said.
    Killing mutations: comparing `statement_sha` only; ignoring the per-check record; treating `checks: []` as nothing to compare."""
    rows = [row("t.py:3"), row("t.py:4")]
    receipt = live_receipt(rows)
    ref = {"path": "proof.txt"}
    assert WR._probe_from_receipt(receipt, ref, ITEM, tmp_path)["verdict"] == "intended_failure"          # no aggregate: today's behaviour
    write_aggregate(tmp_path, rows, verdict="intended_failure")
    assert WR._probe_from_receipt(receipt, ref, ITEM, tmp_path)["verdict"] == "intended_failure"          # the entries now in play are the receipt's
    # 1. the aggregate's own row moved to another entry
    moved = [rows[0], row("t.py:4", entry={**entry_of("t.py:4"), "actual": "-1"})]
    write_aggregate(tmp_path, moved)
    block = WR._probe_from_receipt(receipt, ref, ITEM, tmp_path)
    assert block["verdict"] == WR.MODEL_CHANGED and block["stale_checks"] == ["t.py:4"], block
    assert gaps_of(tmp_path, block) == ["sensitivity:i1"]
    assert WR._scope_note(IID, block, ref)[2].count("t.py:4") == 1
    # 2. the statement changed
    write_aggregate(tmp_path, [rows[0], row("t.py:4", statement_sha="sha-other")])
    assert WR._probe_from_receipt(receipt, ref, ITEM, tmp_path)["stale_checks"] == ["t.py:4"]
    # 3. a kept aggregate (the old proved rows) while the per-check record of the changed model says another entry sha
    write_aggregate(tmp_path, rows, verdict="intended_failure", last_attempt={"at": "t", "verdict": "not_executed", "why": "the stand was down"})
    held = WR._probe_from_receipt(receipt, ref, ITEM, tmp_path)
    assert held["verdict"] == "intended_failure" and held["last_attempt"]["verdict"] == "not_executed", held
    info = []
    WR._probe_scope_notes({"instances": [{"instance_id": IID, "probe": held}]}, info)
    assert len(info) == 1 and "the stand was down" in info[0] and "earlier one" in info[0], info
    per_check = PL.record_read_path(tmp_path, IID, 4, 1, file="t.py")
    per_check.parent.mkdir(parents=True, exist_ok=True)
    per_check.write_text(json.dumps({"entry_sha": "a-newer-model", "verdict": "not_executed"}), encoding="utf-8")
    assert WR._probe_from_receipt(receipt, ref, ITEM, tmp_path)["stale_checks"] == ["t.py:4"]
    per_check.unlink()
    # 4. a check the receipt does not name; `checks: []` names none, so it is never a pass
    write_aggregate(tmp_path, rows + [row("t.py:5")])
    assert WR._probe_from_receipt(receipt, ref, ITEM, tmp_path)["stale_checks"] == ["t.py:5"]
    emptied = {**receipt, "checks": []}
    assert WR._probe_from_receipt(emptied, ref, ITEM, tmp_path)["verdict"] == WR.MODEL_CHANGED
    # 5. an old receipt carries no `checks`: it reads as before, whatever the aggregate holds
    old = {k: v for k, v in receipt.items() if k != "checks"}
    assert WR._probe_from_receipt(old, ref, ITEM, tmp_path)["verdict"] == "intended_failure"
    assert WR._probe_from_receipt(receipt, ref, ITEM)["verdict"] == "intended_failure"                    # no task root: the comparison is not made


def test_window_reads_the_one_key_grammar_and_reader(tmp_path):
    """F8 (AR-13): the window names the same stale keys as before for a `<file>:<line>` row and a `<file>:<line>#2` row, read from the per-check
    record of THAT check (the ordinal and file through `probe_by_code._parse_at_row`, the record through `_read_check_record`); a key that is
    no `<file>:<line>` names no record and is skipped; and `window_record` holds no key grammar or per-check reader of its own.
    Killing mutations: `_entries_in_play` reading the ordinal as 1 for `#2` (the `#2` row would read the first check's record); restoring
    `_check_parts` (the source assertion)."""
    rows = [row("t.py:4"), row("t.py:4#2"), row("odd key")]
    receipt = live_receipt(rows)
    ref = {"path": "proof.txt"}
    write_aggregate(tmp_path, rows, verdict="intended_failure")
    assert WR._probe_from_receipt(receipt, ref, ITEM, tmp_path)["verdict"] == "intended_failure"
    for ordinal, key in ((1, "t.py:4"), (2, "t.py:4#2")):
        record = PL.record_read_path(tmp_path, IID, 4, ordinal, file="t.py")
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps({"entry_sha": "a-newer-model"}), encoding="utf-8")
        block = WR._probe_from_receipt(receipt, ref, ITEM, tmp_path)
        assert block["verdict"] == WR.MODEL_CHANGED and block["stale_checks"] == [key], (key, block)
        record.unlink()
    source = (SCRIPTS / "window_record.py").read_text(encoding="utf-8")
    assert "_check_parts" not in source and "(?:#" not in source and "#(\\d" not in source and "_load(proof_level.record_read_path" not in source


def test_unreadable_aggregate_is_stale_not_live(tmp_path, monkeypatch):
    """F9 (FR-59, AR-28): an ABSENT aggregate is today's behaviour (no comparison, the receipt reads live); an aggregate that EXISTS and cannot
    be read or parsed, is not an object, or has `checks` that is not a list - or a per-check record that exists and cannot be read - is an
    unknown: the block is `model_changed` with a note naming the file, never `intended_failure`; any other exception inside the comparison
    is stale with the exception's class in the note. Killing mutation: `_entries_in_play` returning `(None, {}, "")` for an unreadable file
    (the old `except Exception: return None, {}`)."""
    rows = [row("t.py:3"), row("t.py:4")]
    receipt = live_receipt(rows)
    ref = {"path": "proof.txt"}
    assert WR._probe_from_receipt(receipt, ref, ITEM, tmp_path)["verdict"] == "intended_failure"          # absent: as today
    path = PL.probe_record_path(tmp_path, IID)
    path.parent.mkdir(parents=True, exist_ok=True)
    for bad in ("{not json", "[1, 2]", json.dumps({"checks": "t.py:3"}), "�\x00"):
        path.write_text(bad, encoding="utf-8")
        block = WR._probe_from_receipt(receipt, ref, ITEM, tmp_path)
        assert block["verdict"] == WR.MODEL_CHANGED and path.name in block["stale_note"], (bad, block)
        assert block["stale_checks"] == ["t.py:3", "t.py:4"]
        assert gaps_of(tmp_path, block) == ["sensitivity:i1"]
        said = WR._scope_note(IID, block, ref)[2]
        assert path.name in said and "plain `probe_by_code.py` call" in said and "; " in said, said
        assert WR._explain_parts("sensitivity:i1", [WR._scope_note(IID, block, ref)])[1].startswith("make the plain")
    path.write_text(json.dumps({"checks": []}), encoding="utf-8")         # readable, no rows: nothing to compare with, as today
    assert WR._probe_from_receipt(receipt, ref, ITEM, tmp_path)["verdict"] == "intended_failure"
    write_aggregate(tmp_path, rows, verdict="intended_failure")           # readable and equal: live
    assert WR._probe_from_receipt(receipt, ref, ITEM, tmp_path)["verdict"] == "intended_failure"
    record = PL.record_read_path(tmp_path, IID, 4, 1, file="t.py")        # a per-check record that exists and is garbage
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text("garbage", encoding="utf-8")
    block = WR._probe_from_receipt(receipt, ref, ITEM, tmp_path)
    assert block["verdict"] == WR.MODEL_CHANGED and record.name in block["stale_note"], block
    record.unlink()
    monkeypatch.setattr(PBC, "_entry_sha", lambda entry: (_ for _ in ()).throw(RuntimeError("boom")))
    block = WR._probe_from_receipt(receipt, ref, ITEM, tmp_path)
    assert block["verdict"] == WR.MODEL_CHANGED and "RuntimeError" in block["stale_note"], block


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
