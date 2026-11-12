"""probe_by_code.py: `_aggregate_record`, the ONE writer of `work/probes/<iid>.json` for a walk (t-2064 P4b item 1).

Fast, no runner: the walk of `test_probe_walk.py` (its `World` stub, imported) gives real outcomes; hand-made outcomes give the verdicts a
stub walk cannot produce. Each test names the mutation that kills it (`Kills:`). Runnable alone and collected by pytest."""
import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import probe_by_code as PBC  # noqa: E402
import probe_debt  # noqa: E402
import proof_level  # noqa: E402
from test_probe_walk import FILE, World, entry_for, fire, row, thrown  # noqa: E402,F401

# The keys of today's single-check record (`_new_record`), which a plan of one must keep (verbatim from that function).
TODAY_KEYS = ("schema_version", "probe_tool", "task", "dispatch_id", "instance_id", "case", "test_node", "verdict", "mutation",
              "mutation_kind", "proof_level", "failure_kind", "expected_location", "actual_location", "expected_reason", "actual_reason",
              "observed", "input_hash", "input_hash_source", "test_file_sha256", "test_code_sha", "instance_identity",
              "instance_content_sha", "mutated_file", "obligation_ids", "obligation_hash", "defect_location", "assertion_id",
              "manifest_fields_missing", "target", "evidence_ref", "evidence_refs", "request", "mutation_detail", "restore", "notes",
              "recorded_at")
NEW_KEYS = ("checks", "plan_runs", "plan_remaining", "plan_unfinished", "words", "record")
# `s6_reprove`'s pattern for the path the answer's `record` must have (story_run.py, the literal copied: that method needs a driver)
S6_PATH = re.compile(r"work/probes/(?:product/)?[^/\\]+\.json")


def out(verdict, cause=None, proved_by=None, **more):
    got = {"verdict": verdict, "note": "", "observed": {}, "check_key": None, "read_in_joint": False, "rerun_alone": False}
    if cause:
        got["cause"] = cause
    if proved_by:
        got["proved_by"] = proved_by
    return dict(got, **more)


def proved(**more):
    return out("intended_failure", proved_by="marker", read_in_joint=True, **more)


def aggregate(world, outcomes=None, walk=None, entries=None):
    """Aggregate over hand-made `outcomes` ({key: outcome}) or a real walk's result `walk`."""
    walk = walk if walk is not None else {"outcomes": outcomes or {}, "runs": 1}
    return PBC._aggregate_record(world.ctx, world.plan, world.entries() if entries is None else entries, walk)


def stored(world) -> dict:
    return json.loads(PBC.record_path(world.task_root, "i1").read_text(encoding="utf-8"))


def walked(tmp_path, monkeypatch, kinds="sss", scenario=None):
    world = World(tmp_path, kinds).install(monkeypatch)
    world.scenario = scenario or fire(*range(len(kinds)))
    return world, world.walk()


# --- shape ---------------------------------------------------------------------------------------------------------------------

def test_one_check_same_record_shape(tmp_path, monkeypatch):
    """A plan of ONE keeps today's record: every key of `_new_record`, the location as `<file>:<line>` of the check, equal pairs.
    Kills: dropping a key from the record, or writing the location as the key without the file."""
    world, result = walked(tmp_path, monkeypatch, "s")
    record = aggregate(world, walk=result)
    line = world.checks[0]["line"]
    assert all(key in record for key in TODAY_KEYS + NEW_KEYS), [k for k in TODAY_KEYS + NEW_KEYS if k not in record]
    assert record["verdict"] == "intended_failure" and len(record["checks"]) == 1
    assert record["expected_location"] == record["actual_location"] == f"{FILE}:{line}"
    assert record["expected_reason"] == record["actual_reason"] and "1 of 1" in record["expected_reason"]
    assert record["failure_kind"] == "assertion" and record["mutation"] == "invert" and "at" not in record["mutation_detail"]
    assert stored(world) == record, "the record on disk is the answer"


def test_aggregate_feeds_every_reader(tmp_path, monkeypatch):
    """Every reader of the record finds its keys. CALLED (pure over the record or a file): `_receipt_core`, `window_probe`,
    `proof_level._replay` (reads `work/probes/<iid>.json`), `probe_debt._replay_plan`. By KEY PRESENCE (the reader needs a driver or a
    window): `acceptance`'s probe test, `s6_reprove`'s path pattern and `words`.
    Kills: removing `test_node`, `mutation_detail`, `restore.sha256`, `expected_reason`, `record` or `words` from the record."""
    world, result = walked(tmp_path, monkeypatch, "ss")
    record = aggregate(world, walk=result)
    assert record["verdict"] == "intended_failure"
    core = PBC._receipt_core(record, "i1", {key: "f" for key in PBC.FACT_KEYS}, "restored")
    assert core["mutation"] == "invert" and core["assertion_location"] == record["expected_location"] and core["probe_record"] == record["record"]
    assert core["expected_assertion_failure"] == core["actual_failure"] == record["expected_reason"] and core["proved_by"] == "marker"
    assert record["restore"]["sha256"], "`attach_receipt` reads restore['sha256']"
    window = PBC.window_probe(record)
    assert set(window) == set(PBC.WINDOW_PROBE_FIELDS) and window["verdict"] == "intended_failure" and window["target"]
    assert all(key in record for key in PBC.WINDOW_PROBE_FIELDS), "every window field is a key of the record"
    replay = proof_level._replay({"instance_id": "i1"}, world.task_root)
    assert replay == {"test": PBC_NODE(), "instance": "i1", "mutation": "invert", "oracle": ""}, replay
    node, mutation, oracle, at, why = probe_debt._replay_plan(record, world.root)
    assert (node, mutation, oracle, at, why) == (PBC_NODE(), "invert", "", "", ""), (node, mutation, oracle, at, why)
    assert (record["verdict"] == "intended_failure" and record["expected_location"] == record["actual_location"]
            and record["expected_reason"] == record["actual_reason"] and record["failure_kind"] == "assertion"), "acceptance's probe test"
    assert S6_PATH.fullmatch(record["record"]) and record["words"] == "2 of 2 checks proved"


def PBC_NODE() -> str:
    return "tests/test_t.py::test_run"


# --- verdicts ------------------------------------------------------------------------------------------------------------------

def test_all_proved_is_intended_failure(tmp_path, monkeypatch):
    """Every check proved: `intended_failure`, `proved_by: marker`, each row carries its entry WHOLE, the restore is verified and the
    author's bytes are measured. Kills: a verdict rule that needs fewer proofs, an entry copied in part."""
    world, result = walked(tmp_path, monkeypatch, "sss")
    record = aggregate(world, walk=result)
    assert record["verdict"] == "intended_failure" and record["proved_by"] == "marker" and "cause" not in record
    assert [r["entry"] for r in record["checks"]] == world.entries(), "the entry as written"
    assert [r["key"] for r in record["checks"]] == world.keys and all(r["statement_sha"] and r["run"] == 1 for r in record["checks"])
    assert all(r["probe_kind"] == "actual" and r["supposes"] == "s" and r["read_in_joint"] for r in record["checks"])
    assert record["restore"]["verified"] is True and record["test_file_sha256"] == hashlib.sha256(world.original).hexdigest()
    assert record["plan_remaining"] == [] and record["plan_unfinished"] is False and record["plan_runs"] == 1
    assert record["expected_location"] == f"{FILE}:{world.checks[0]['line']}", "the FIRST proved check's"
    assert record["mutated_files"] and record["mutated_files"][0]["sha256"] == record["test_file_sha256"]


@pytest.mark.parametrize("kind", PBC._SURVIVOR_ORDER)
def test_one_survivor_of_each_kind(tmp_path, monkeypatch, kind):
    """One check survives among proved ones: the verdict is the survivor's, never `intended_failure`, and `words` names what is left.
    Kills: `intended_failure` decided by `any proved` (or by the first row) instead of every owed check."""
    world = World(tmp_path, "sss").install(monkeypatch)
    outcomes = {world.keys[0]: proved(), world.keys[1]: out(kind), world.keys[2]: proved()}
    record = aggregate(world, outcomes)
    assert record["verdict"] == kind and record["failure_kind"] is None and "cause" not in record
    assert record["words"] == f"2 of 3 checks proved; left: {world.keys[1]}"
    assert record["checks"][1]["verdict"] == kind and record["proved_by"] is None


def test_survivor_order_picks_the_one_that_says_most(tmp_path, monkeypatch):
    """`no_failure` outranks `wrong_location` outranks `not_executed` (`_SURVIVOR_ORDER`). Kills: reversing the order."""
    world = World(tmp_path, "sss").install(monkeypatch)
    assert aggregate(world, {world.keys[0]: out("not_executed"), world.keys[1]: out("wrong_location"), world.keys[2]: out("no_failure")})["verdict"] == "no_failure"
    assert aggregate(world, {world.keys[0]: out("not_executed"), world.keys[1]: out("wrong_location"), world.keys[2]: proved()})["verdict"] == "wrong_location"


def test_incomplete_judgment_carries_its_cause(tmp_path, monkeypatch):
    """A check the code could not settle (`incomplete`, `judgment`) leaves the aggregate `incomplete` with that cause, and a stored
    `cause` shows it. Kills: a hard-coded cause, or an `incomplete` row counted as proved."""
    world = World(tmp_path, "ss").install(monkeypatch)
    record = aggregate(world, {world.keys[0]: proved(), world.keys[1]: out("incomplete", cause="judgment")})
    assert record["verdict"] == "incomplete" and record["cause"] == "judgment" and record["failure_kind"] is None


def test_tooling_mix_is_tooling(tmp_path, monkeypatch):
    """A tooling row among proved ones AND a survivor: the whole is `incomplete`, `cause: tooling` (re-run the call; the survivor stays
    in `checks[]`). Kills: survivor order applied before the tooling rule."""
    world = World(tmp_path, "sss").install(monkeypatch)
    record = aggregate(world, {world.keys[0]: proved(), world.keys[1]: out("incomplete", cause="tooling"), world.keys[2]: out("no_failure")})
    assert record["verdict"] == "incomplete" and record["cause"] == "tooling"
    assert [r["verdict"] for r in record["checks"]] == ["intended_failure", "incomplete", "no_failure"]


def test_unknown_verdict_is_incomplete_never_proved(tmp_path, monkeypatch):
    """An outcome with a verdict this module does not know, or none, is `incomplete`, `tooling`. Kills: passing the word through."""
    world = World(tmp_path, "ss").install(monkeypatch)
    for word in ("mystery", None, ""):
        record = aggregate(world, {world.keys[0]: proved(), world.keys[1]: {"verdict": word}})
        assert record["verdict"] == "incomplete" and record["cause"] == "tooling", word
        assert record["checks"][1]["verdict"] == "incomplete" and "intended_failure" not in record["checks"][1]["verdict"]


def test_not_owed_is_set_aside_and_all_not_owed_proves_nothing(tmp_path, monkeypatch):
    """A `not_here` check is `not_owed` (EP-T): the others decide. All `not_here`: nothing is proved: `incomplete`, `judgment`, and the
    locations are absent, not invented. Kills: counting `not_owed` as proved, or inventing a location from the first check."""
    world = World(tmp_path, "sss").install(monkeypatch)
    entries = [entry_for(world.checks[0]), entry_for(world.checks[1], "not_here", instance="i1", not_here="w"), entry_for(world.checks[2])]
    record = aggregate(world, {world.keys[0]: proved(), world.keys[2]: proved()}, entries=entries)
    assert record["verdict"] == "intended_failure" and record["words"] == "2 of 2 checks proved"
    assert record["checks"][1]["verdict"] == "not_owed" and record["checks"][1]["reason"] == "w"
    every = [entry_for(c, "not_here", instance="i1", not_here="w") for c in world.checks]
    none = aggregate(world, {}, entries=every)
    assert none["verdict"] == "incomplete" and none["cause"] == "judgment" and none["expected_location"] is None is none["actual_location"]
    assert none["failure_kind"] is None and none["words"] == "0 of 0 checks proved"


def test_no_proved_check_has_no_location(tmp_path, monkeypatch):
    """Nothing proved: no location is written. Kills: a location taken from the first check of the plan."""
    world = World(tmp_path, "ss").install(monkeypatch)
    record = aggregate(world, {world.keys[0]: out("no_failure"), world.keys[1]: out("no_failure")})
    assert record["expected_location"] is None and record["actual_location"] is None and record["words"].startswith("0 of 2")


# --- partial, wall, stop -------------------------------------------------------------------------------------------------------

def test_partial_names_the_rest_and_the_end_completes_it(tmp_path, monkeypatch):
    """After row one the record names `plan_remaining`, is `incomplete`, `tooling`, `plan_unfinished: true`; the call at the end, same
    file, is `intended_failure` with the flag off. Kills: a partial call that reads as complete; a flag left on at the end."""
    world = World(tmp_path, "hhh").install(monkeypatch)
    first = aggregate(world, {world.keys[0]: proved()})
    assert first["verdict"] == "incomplete" and first["cause"] == "tooling" and first["plan_unfinished"] is True
    assert first["plan_remaining"] == world.keys[1:] and [r["verdict"] for r in first["checks"]] == ["intended_failure", "not_reached", "not_reached"]
    assert stored(world)["plan_unfinished"] is True
    last = aggregate(world, {k: proved() for k in world.keys})
    assert last["verdict"] == "intended_failure" and last["plan_unfinished"] is False and last["plan_remaining"] == []


def test_wall_leaves_plan_unfinished(tmp_path, monkeypatch):
    """The walk's time ran out (a REAL walk): `plan_unfinished: true`, `plan_remaining`, `incomplete`, `tooling`, never a pass. Kills: a
    wall that leaves the verdict at `intended_failure` for the rows done."""
    world = World(tmp_path, "hhh").install(monkeypatch)
    world.step = 60.0
    world.scenario = lambda w, run: [row("failed", thrown(w, run, *run["tokens"]))]
    result = world.walk(timeout=100)
    assert result["ended"] == "time"
    record = aggregate(world, walk=result)
    assert (record["verdict"], record["cause"], record["plan_unfinished"]) == ("incomplete", "tooling", True)
    assert record["plan_remaining"] == [world.keys[2]] and record["plan_runs"] == 2


def test_stop_is_judgment_and_not_unfinished(tmp_path, monkeypatch):
    """EP-G's stop (a REAL walk): `incomplete`, `cause: judgment`, rows `not_reached` listed, NOT `plan_unfinished` (the same call
    would stop again). Kills: reading a stop as a wall."""
    world = World(tmp_path, "hhh").install(monkeypatch)
    world.scenario = lambda w, run: [row("failed", thrown(w, run, *run["tokens"]))] if len(w.runs) == 1 else \
        [row("failed", "boom in a", site={"location": f"{FILE}:{w.checks[0]['line']}"})]
    result = world.walk()
    assert result["ended"] == "stop"
    record = aggregate(world, walk=result)
    assert (record["verdict"], record["cause"], record["plan_unfinished"]) == ("incomplete", "judgment", False)
    assert record["plan_remaining"] == world.keys[1:]


def test_restore_not_verified_on_one_row(tmp_path, monkeypatch):
    """One row reports an unverified restore: `restore.verified` is False for the aggregate and the author's bytes are NOT measured.
    Kills: `verified` taken from the last row, or from the walk alone."""
    world = World(tmp_path, "sss").install(monkeypatch)
    outcomes = {world.keys[0]: proved(), world.keys[1]: proved(restore={"verified": False, "error": "disk"}), world.keys[2]: proved()}
    record = aggregate(world, outcomes)
    assert record["restore"]["verified"] is False and record["restore"]["error"] == "disk" and record["restore"]["sha256"] is None
    assert record["test_file_sha256"] is None
    ok = aggregate(world, {k: proved(restore={"verified": True}) for k in world.keys})
    assert ok["restore"]["verified"] is True


# --- empty and stored ----------------------------------------------------------------------------------------------------------

def test_empty_plan_writes_nothing(tmp_path, monkeypatch):
    """No check in the plan (EP-A): nothing is written and a named reason is returned - an empty list never reads as all proved.
    Kills: an aggregate of zero rows, which `all([])` would call proved."""
    world = World(tmp_path, "s").install(monkeypatch)
    for plan in ({"checks": [], "runs": []}, {}, None):
        got = PBC._aggregate_record(world.ctx, plan, [], {"outcomes": {}})
        assert got["written"] is False and got["reason"] == "no_checks" and "verdict" not in got
    assert not PBC.record_path(world.task_root, "i1").exists()


def test_skipped_proved_key_is_read_back_from_its_record(tmp_path, monkeypatch):
    """The second call skips every key as proved (no outcomes): the aggregate reads each per-check record and is `intended_failure`; a
    per-check record that cannot be read is NOT proved (`incomplete`, `tooling`). Kills: skipped keys dropped from the rows, or counted
    proved without the record."""
    world, first = walked(tmp_path, monkeypatch, "ss")
    second = world.walk()
    assert second["proved"] == world.keys and second["outcomes"] == {}
    record = aggregate(world, walk=second)
    assert record["verdict"] == "intended_failure" and [r["proved_by"] for r in record["checks"]] == ["marker", "marker"]
    # the fixture corrupts the record through the SAME reader the walk and the aggregate use: the per-check record carries the file's
    # hash now, and the old un-hashed name (what this line built before) is a name no writer produces any more
    path = PBC.proof_level.record_read_path(world.task_root, "i1", world.checks[1]["line"], 1, file=world.checks[1]["file"])
    assert path.is_file()
    path.write_text("{ not json")
    broken = aggregate(world, walk=second)
    assert broken["verdict"] == "incomplete" and broken["cause"] == "tooling" and broken["checks"][1]["verdict"] == "incomplete"


def test_incomplete_never_replaces_a_stored_intended_failure(tmp_path, monkeypatch):
    """The write is `keep_standing_record`'s then `atomic_json`: an unfinished call after a proved aggregate keeps it and adds
    `last_attempt`. Kills: writing with `atomic_json` alone."""
    world, result = walked(tmp_path, monkeypatch, "ss")
    aggregate(world, walk=result)
    partial = aggregate(world, {world.keys[0]: proved()})
    assert partial["verdict"] == "incomplete"
    kept = stored(world)
    assert kept["verdict"] == "intended_failure" and kept["last_attempt"]["verdict"] == "incomplete"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
