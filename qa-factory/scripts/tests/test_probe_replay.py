"""t-2064 P4c: the replay of stored probes - the S5 settle (`probe_debt`), `proof_level._replay` and the S6 call (B2). FAST.

A settle never invents an edit: it replays a record only when every check of the test, on its CURRENT bytes, has an entry STORED in the
record's aggregate (`probe_by_code.replay_owed`, joined by `statement_sha`); else the item stays with the critic by name, "model owed", and
nothing runs. The runs here are stubs: `probe_debt.settle` over `test_probe_debt`'s world and stub runner, and `probe_by_code.probe` over
`test_probe_walk.World` (`test_probe_every_check.flip`). A red names the branch; each test names the mutation of the code that kills it
(none of them was actually run against that mutation). Runnable alone and collected by pytest."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import probe_by_code as PBC  # noqa: E402
import probe_debt as D  # noqa: E402
import proof_level as PL  # noqa: E402
import test_probe_debt as TD  # noqa: E402
import test_probe_every_check as TE  # noqa: E402
import test_probe_walk as TW  # noqa: E402

KEY = f"{TD.TEST_REL}:2"
PLAN_UNFINISHED = {"verdict": "incomplete", "cause": "tooling", "plan_unfinished": True, "plan_remaining": [KEY],
                   "restore": {"verified": True}, "notes": ["the settle's own timeout cut a row"]}


@pytest.fixture
def w():
    world = TD.world()
    TD.put_manifest(world, [TD.row(world, "test_a")])
    try:
        yield world
    finally:
        TD.cleanup(world.project)


def item_of(w) -> dict:
    return D.find(w.task_root, w.manifest, w.project, TD.CRITIC)["items"][0]


def drop_entries(w, iid="test_a", **more):
    """An aggregate that proved the check but stored no model for it: every row without its `entry`."""
    rows = [{k: v for k, v in row.items() if k != "entry"} for row in TD.stored_checks(w, f"{TD.TEST_REL}::{iid}")]
    return TD.record(w, iid, checks=rows, **more)


def rewrite(w, text: str) -> None:
    """The test file changes on disk and the manifest binds the new bytes (a replay on the current bytes is then a plain REPROBE)."""
    TD.write(w.project / TD.TEST_REL, text)
    w.sha = TD.sha((w.project / TD.TEST_REL).read_bytes())
    TD.put_manifest(w, [TD.row(w, "test_a")])


# --- the S5 settle: owed, or replayed with no flag -------------------------------------------------------------------------------------

def test_settle_no_stored_stays_with_critic_no_run(w):
    """An aggregate with no stored entry for the check: the item is LEAVE_TO_CRITIC, `model owed` naming the key and what the record proved,
    no command to copy, and the settle starts NOTHING (no probe, no rebind) - the item is left with reason `critic`. Killed by: `_item`
    not asking `replay_owed` (REPROBE, a probe the tool refuses before a byte), or running it anyway."""
    drop_entries(w)
    item = item_of(w)
    assert item["action"] == D.LEAVE_TO_CRITIC and item["command"] == "", item
    assert item["why"].startswith(f"model owed: the critic writes the entry for {KEY} (the record proved one check)"), item["why"]
    assert "work/probe-models/" in item["why"] and "no --at" in item["why"], "the door is named (FR-1)"
    stub = TD.Stub(w)
    doc = TD.settle(w, stub)
    assert stub.calls == [] and doc["outcomes"] == [], "nothing was started"
    assert [(left["instance_id"], left["reason"]) for left in doc["left"]] == [("test_a", "critic")] and "model owed" in doc["left"][0]["reason_words"]


@pytest.mark.parametrize("how", ["empty", "absent", "at"])
def test_settle_old_record_owed(w, how):
    """An old single-probe record - `checks: []`, no `checks` key at all, or one aimed by `--at` - proved one check of several and wrote no
    reason: it is owed, whatever `mutation` says, and no `--at` replay is made of it. Killed by: reading a missing `checks` as "nothing
    owed", or replaying `mutation_detail.at`."""
    detail = {"line": 2, "mutation": "invert", "at": 2} if how == "at" else None
    path = TD.record(w, "test_a", checks=[], detail=detail)
    if how == "absent":
        old = json.loads(path.read_text(encoding="utf-8"))
        old.pop("checks")
        TD.write(path, old)
    assert json.loads(path.read_text(encoding="utf-8")).get("mutation") == "invert"
    item = item_of(w)
    assert item["action"] == D.LEAVE_TO_CRITIC and item["command"] == "", f"{how}: {item}"
    assert f"model owed: the critic writes the entry for {KEY} (the record proved one check)" in item["why"], item["why"]
    stub = TD.Stub(w)
    TD.settle(w, stub)
    assert stub.calls == [], f"{how}: no run"


def test_settle_stored_replays_no_flag(w):
    """Every check has a stored entry: REPROBE, and the call carries no flag that says "replay" - no `--at`, no `--oracle` - only the
    mutation word `invert` (a word the probe never reads as "no role"). Killed by: `--at` (or any new flag) in `_probe_args`' call,
    or an owed answer for a stored entry."""
    TD.record(w, "test_a", detail={"line": 2, "mutation": "invert", "at": 2})
    item = item_of(w)
    assert item["action"] == D.REPROBE and "--at" not in item["command"], item
    stub = TD.Stub(w)
    TD.settle(w, stub)
    assert stub.kinds() == ["probe:test_a"], stub.kinds()
    args = stub.calls[0][1]
    assert "--at" not in args and "--oracle" not in args, args
    assert args[args.index("--mutation") + 1] == "invert" and args[args.index("--test") + 1] == f"{TD.TEST_REL}::test_a", args


def python_world(body="    assert a == 1, \"c1\"\n    assert a == 2, \"c2\"\n"):
    data, spec, listed = TE.python_world(body)
    return data, spec, listed


def stored_of(listed, reason="R", **row_more) -> dict:
    return {"instance_id": "i1", "checks": [
        {"key": c["key"], "statement_sha": c["statement_sha"], **row_more,
         "entry": {"check": c["key"], "kind": "invert", "invert": reason, "instance": "", "alternative": "", "supposes": ""}} for c in listed]}


def test_settle_stored_invert_keeps_reason(tmp_path, monkeypatch):
    """A stored `invert` stands and replays as `invert` with ITS reason; a code-written no-role inversion does not stand under a role (it is
    owed), and the walk keeps the reason it was given. Killed by: `_standing_entry` letting `NO_ROLE_REASON` satisfy a role's call, or the
    join rewriting the stored reason."""
    data, spec, listed = python_world()
    keys = [c["key"] for c in listed]
    assert PBC.replay_owed(stored_of(listed), data, spec, None, []) == [], "a stored invert with a reason of its own stands"
    assert PBC.replay_owed(stored_of(listed, PBC.NO_ROLE_REASON), data, spec, None, []) == keys, "what code once wrote for no role is owed to a role"
    assert PBC.replay_owed(stored_of(listed[:1]), data, spec, None, []) == keys[1:], "only the check with no stored entry is owed"
    world = TE.flip(tmp_path, monkeypatch, "ss", stage="S5")
    TE.flip_models(world, [{"check": key, "invert": "R: the healthy value is all there is"} for key in world.keys])
    first = TE.flip_call(world)
    assert [row["probe_kind"] for row in first["checks"]] == ["invert"] * 2, first["checks"]
    (world.task_root / "work" / "probe-models" / "D.json").unlink()
    again = TE.flip_call(world)             # S5, a role, no model file: the stored entries are joined, no refusal
    assert [row["entry"]["invert"] for row in again["checks"]] == ["R: the healthy value is all there is"] * 2, again["checks"]
    assert {row["reason"] for row in again["checks"]} == {"R: the healthy value is all there is"}, "the reason stays the critic's"


def test_settle_moved_key_joined_by_statement(w):
    """A line inserted above the check moves its key (`:2` to `:3`): the stored entry is joined by the statement's sha, so nothing is
    owed and the item is a plain REPROBE. Killed by: joining a stored entry by its key or line."""
    TD.record(w, "test_a")
    stored_key = json.loads(PL.probe_record_path(w.task_root, "test_a").read_text(encoding="utf-8"))["checks"][0]["key"]
    assert stored_key == KEY
    rewrite(w, TD.TEST_SRC.replace("    assert 1 + 1 == 2\n", "    seed = 7\n    assert 1 + 1 == 2\n", 1))
    now = PBC.checks_of((w.project / TD.TEST_REL).read_bytes(), PBC.parse_node(f"{TD.TEST_REL}::test_a"), None, [], [], [])
    assert now[0]["key"] == f"{TD.TEST_REL}:3", "the key moved"
    item = item_of(w)
    assert item["action"] == D.REPROBE, item
    rewrite(w, TD.TEST_SRC.replace("    assert 1 + 1 == 2\n", "    assert  1 + 1   ==  2\n", 1))
    assert item_of(w)["action"] == D.REPROBE, "whitespace is folded in the statement's sha"


def test_settle_changed_expected_owed(w):
    """The statement of the check changed (the expected value is another): its stored entry is for another statement, so the check is
    owed - `model owed`, nothing runs. Killed by: a join that ignores the statement (by line, or by key)."""
    TD.record(w, "test_a")
    rewrite(w, TD.TEST_SRC.replace("assert 1 + 1 == 2", "assert 1 + 1 == 3", 1))
    item = item_of(w)
    assert item["action"] == D.LEAVE_TO_CRITIC and f"the critic writes the entry for {KEY}" in item["why"], item
    stub = TD.Stub(w)
    TD.settle(w, stub)
    assert stub.calls == [], "no run"


def test_replay_owed_edges():
    """The edges of the pure function: a record that is not a dict, or has no usable `checks`, owes EVERY key (never `[]` by accident); a
    test with no check owes nothing; an entry of an alternative, of another instance, or one no longer standing is owed. Killed by:
    returning `[]` for a record it cannot read, or counting a row with no `entry` as stored."""
    data, spec, listed = python_world()
    keys = [c["key"] for c in listed]
    for junk in (None, [], "text", 7, {}, {"checks": None}, {"checks": "x"}, {"checks": [None, 3, {}]}, {"checks": [{"statement_sha": "x"}]}):
        assert PBC.replay_owed(junk, data, spec, None, []) == keys, junk
    nothing = python_world("    b = 2\n")
    assert PBC.replay_owed(None, *nothing[:2], None, []) == [] and PBC.replay_owed(stored_of(listed), *nothing[:2], None, []) == []
    record = stored_of(listed)
    record["checks"][0]["entry"]["alternative"] = "TC-1:ALT-1"
    record["checks"][1]["entry"]["instance"] = "i2"
    assert PBC.replay_owed(record, data, spec, None, []) == keys, "an alternative's and another instance's entry stand for nobody"
    gone = stored_of(listed)
    gone["checks"][0]["entry"] = {"check": keys[0], "kind": "find", "find": "seed = 7", "replace": "seed = 8", "supposes": "s", "instance": "", "alternative": ""}
    assert PBC.replay_owed(gone, data, spec, None, []) == keys[:1], "a `find` whose text is gone from the bytes is owed"
    before = json.dumps(record, sort_keys=True)
    PBC.replay_owed(record, data, spec, None, [])
    assert json.dumps(record, sort_keys=True) == before, "pure: the record is not touched"


# --- the settle's budget: a cut walk continues ---------------------------------------------------------------------------------------

def test_classify_plan_unfinished_continues():
    """`plan_unfinished: true` is its own result - not settled, `stop` False (the next item and the next settle go on), not in
    `STABLE_LEFT` (nothing is remembered as a repeat) - while an answer without the key classifies as before. Killed by: reading it
    as `not_executed` (`stop: True`), or adding it to `STABLE_LEFT`."""
    got = D._classify(1, json.dumps(PLAN_UNFINISHED), "")
    assert (got["result"], got["settled"], got["stop"]) == ("plan_unfinished", False, False), got
    assert KEY in got["words"] and "kept" in got["words"], got
    assert "plan_unfinished" not in D.STABLE_LEFT
    assert D._classify(1, json.dumps(dict(PLAN_UNFINISHED, restore={"verified": False})), "")["stop"] is True, "an unverified restore still stops"
    assert D._classify(1, json.dumps({"verdict": "incomplete", "plan_unfinished": True}), "")["stop"] is False, "no restore block: nothing says it failed"
    old = D._classify(1, json.dumps({"verdict": "incomplete", "restore": {"verified": True}, "notes": ["a"]}), "")
    assert (old["result"], old["settled"], old["stop"]) == ("incomplete", False, False), "an old answer classifies as today"
    for not_true in (False, None, "true", 1):
        assert D._classify(1, json.dumps({"verdict": "incomplete", "plan_unfinished": not_true, "restore": {"verified": True}}), "")["result"] == "incomplete", not_true
    assert D._classify(1, json.dumps({"verdict": "not_executed", "restore": {"verified": True}}), "")["stop"] is True, "not_executed still stops"
    assert D._classify(1, json.dumps(dict(PLAN_UNFINISHED, plan_remaining=None)), "")["result"] == "plan_unfinished"


def test_settle_budget_cut_keeps_rows():
    """One row cut by the settle's own `--timeout`: the probe answers `plan_unfinished`; the settle leaves that item with its reason and the
    keys left, goes on to the next item, remembers no attempt, and the record on disk (the rows that ran) is untouched; the next settle
    probes it again. The real cut by the timeout is CI's. Killed by: `not_executed`'s stop (the next item is not probed), remembering the
    attempt (the next settle skips it as `same_bytes`), or the settle rewriting the record."""
    world = TD.world()
    try:
        ids = ["t1", "t2"]
        TD.put_manifest(world, [TD.row(world, i) for i in ids])
        for i in ids:
            TD.record(world, i)
        before = PL.probe_record_path(world.task_root, "t1").read_bytes()
        stub = TD.Stub(world)
        stub.probe["t1"] = (1, PLAN_UNFINISHED)
        doc = TD.settle(world, stub)
        assert stub.kinds() == ["probe:t1", "probe:t2"], "the settle goes on after the cut walk"
        assert "--timeout" in stub.calls[0][1], "the probe's own timeout is the time left"
        got = {o["instance_id"]: o for o in doc["outcomes"]}
        left = {i["instance_id"]: i for i in doc["left"]}
        assert got["t1"]["result"] == "plan_unfinished" and left["t1"]["reason"] == "plan_unfinished" and KEY in left["t1"]["reason_words"], (got, left)
        assert got["t2"]["result"] == "published" and "t2" not in left
        assert not [a for a in doc["last_attempts"] if a["instance_id"] == "t1"], "a cut walk is not remembered as a repeat"
        assert PL.probe_record_path(world.task_root, "t1").read_bytes() == before, "the rows that ran stay as they were"
        again = TD.Stub(world)
        TD.settle(world, again)
        assert "probe:t1" in again.kinds(), "the next settle continues the walk"
    finally:
        TD.cleanup(world.project)


# --- `_replay` and S6 ---------------------------------------------------------------------------------------------------------------

def test_replay_reads_aggregate(tmp_path, monkeypatch):
    """The aggregate a walk wrote (`mutation: "invert"`, `mutation_detail` with no `at`) replays as it stands: test node, `invert`, no
    oracle - the S6 close's `s6_reprove` argv is built from it. Killed by: `_replay` requiring `mutation_detail.at` (or an `oracle_function`)."""
    world = TE.flip(tmp_path, monkeypatch, "ss", stage="S6")
    record = TE.flip_call(world)
    stored = json.loads((world.task_root / "work" / "probes" / "i1.json").read_text(encoding="utf-8"))
    assert stored["mutation"] == "invert" and "at" not in stored["mutation_detail"] and stored["checks"], "the aggregate as written"
    got = PL._replay({"instance_id": "i1", "case": "TC-1", "file": TW.FILE}, world.task_root)
    assert got == {"test": TW.NODE, "instance": "i1", "mutation": "invert", "oracle": ""}, (got, record["mutation_detail"])


def test_replay_old_at_none(w):
    """An old record made with `--at` (any spelling) still has no replay - a line anchor does not survive the edit that made the probe stale;
    the same record with no anchor replays (the control). Killed by: `_replay` dropping the `detail.at` test."""
    entry = TD.row(w, "test_a")
    for at in (2, 0, "tests/test_x.py:2", "2#2"):
        TD.record(w, "test_a", checks=[], detail={"line": 2, "mutation": "invert", "at": at})
        assert PL._replay(entry, w.task_root) is None, at
    TD.record(w, "test_a", checks=[], detail={"line": 2, "mutation": "invert"})
    got = PL._replay(entry, w.task_root)
    assert got and got["mutation"] == "invert" and got["test"] == f"{TD.TEST_REL}::test_a", got


def test_s6_replay_stored_then_inversion(tmp_path, monkeypatch):
    """The S6 call (no role) over a stored aggregate: a check whose statement has a stored entry walks THAT entry; a check with none is
    inverted by code with `no role at this call`, and the answer is the aggregate. A call under S5 over the same bytes is refused, never an
    inversion. Killed by: step 3 (the inversion) before step 2 (the stored entry), `_no_role` read from `--mutation`, or an inversion
    written under S5."""
    world = TE.flip(tmp_path, monkeypatch, "ss", stage="S5")
    TE.flip_models(world, TE.flip_actual(world))
    first = TE.flip_call(world)
    assert [row["probe_kind"] for row in first["checks"]] == ["actual"] * 2
    (world.task_root / "work" / "probe-models" / "D.json").unlink()
    changed = world.text.replace('"c2"', '"c2 is another statement"')
    world.path.write_bytes(changed.encode())
    world.original = changed.encode()
    assert "no model is stored" in TE.flip_refusal(world, mutation="invert"), "S5: a role, the second check owed; `--mutation invert` is no way past it"
    assert world.path.read_bytes() == world.original, "the refusal touched nothing"
    world.stage = "S6"
    record = TE.flip_call(world, mutation="invert")
    assert [row["probe_kind"] for row in record["checks"]] == ["actual", "invert"], record["checks"]
    assert record["checks"][1]["reason"] == PBC.NO_ROLE_REASON and record["checks"][0]["entry"]["actual"] == "2", record["checks"]
    assert any("no model is stored" in note for note in record["notes"]), record["notes"]
    stored = json.loads((world.task_root / "work" / "probes" / "i1.json").read_text(encoding="utf-8"))
    assert stored["record"] == record["record"] == "work/probes/i1.json" and "at" not in stored["mutation_detail"], "the aggregate is the answer"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
