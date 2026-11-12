#!/usr/bin/env python3
"""TR3-10 C: claims of `walk_session.py` - what a walk says it changes, refused to a second live walk (fake clock, no browser, no network).

Mutation -> the ONE test that kills it: a free record refused -> claim_free_granted; a live holder passed or waited for ever ->
claim_in_use_refused_after_wait_names_holder; a spelling that splits a kind -> kind_spelling_folded; `--all` and an instance that do not
meet -> all_blocks_instances_and_reverse; a walk blocked by its own claim -> own_claims_never_block; the verdict that frees nothing or
frees without the verdict's own `"teardown": "done"` (B1) -> verdict_teardown_not_done_goes_dirty / verdict_without_teardown_field_goes_dirty
(a verdict that frees nothing: verdict_teardown_done_frees; the release function: verdict_teardown_frees_else_dirty); a row assigned before
its walk opened read dirty or passed by `--all` (B2) -> assigned_before_open_blocks_all / _blocks_same_instance / _not_named_dirty; a failed
write granted or a traceback -> claim_write_oserror_refuses_nothing_granted; a dirty record granted -> dirty_refused; a vanished holder read free ->
dead_holder_reads_dirty; an unreadable list granted -> store_unreadable_refuses; a walk end that releases nothing -> close_marks_dirty; a
claim in an S7 walk -> settle_place_refused; a release before the verdict is stored -> released_only_after_stored_verdict; a held lock
waited for ever or a silent drop -> claim_lock_busy_names_holder_nothing_written.
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE / "fixtures" / "manual-evidence"))
import event_store as ES  # noqa: E402
import test_walk_record as R  # noqa: E402
import test_walk_session as W  # noqa: E402
import walk_session as WS  # noqa: E402

CASE = W.CASE


class Clock:
    """A fake clock whose sleep moves it: a wait of 120 s costs no real time."""

    def __init__(self):
        self.now = 0.0
        WS.SEAMS.update(clock=lambda: self.now, sleep=self.sleep)

    def sleep(self, seconds):
        self.now += seconds

    def off(self):
        WS.SEAMS.update(clock=None, sleep=None)


class Task:
    def __init__(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.clock = Clock()

    def walk(self, name, live=True, place="case", items=("TC-1",), opened=True):
        """`live`: a record of THIS process (alive); not live: a record of a walk that is over (it HAS a record, `dead`); `opened=False`: no
        record at all (a walk `assign_entities` wrote rows for before the agent opened it)."""
        walk = WS.Walk(self.root, name, list(items), ["guest"], place=place)
        walk.state = "ready" if live else "dead"
        if opened:
            walk.write_state()
        return walk

    def done(self):
        self.clock.off()
        self.dir.cleanup()


def claim(walk, item="TC-1", **fields):
    return walk.op_claim({"item": item, **fields})


def states(task):
    return {(r["walk"], r["instance"]): r["state"] for r in WS.claims_of(task.root)[0]}


def test_claim_free_granted():
    t = Task()
    try:
        code, answer = claim(t.walk("W1"), kind=" Book ", instance="17")
        assert code == 0 and answer["kind"] == "book" and answer["instance"] == "17", answer
        assert states(t) == {("W1", "17"): "in_use"}
        assert WS.claims_of(t.root, "nobody") == ([], "")
    finally:
        t.done()


def test_claim_in_use_refused_after_wait_names_holder():
    t = Task()
    try:
        claim(t.walk("W1"), kind="book", instance="17")
        code, answer = claim(t.walk("W2", items=("TC-2",)), item="TC-2", kind="book", instance="17")
        assert code == 2 and "walk W1" in answer["text"] and "item TC-1" in answer["text"] and "inconclusive" in answer["text"], answer
        assert t.clock.now >= WS.data()["claim_wait_s"], t.clock.now          # it waited the whole data value, and not longer than one poll beyond
        assert t.clock.now < WS.data()["claim_wait_s"] + 2 * WS.CLAIM_POLL_S
        assert states(t) == {("W1", "17"): "in_use"}                          # nothing granted to W2
    finally:
        t.done()


def test_kind_spelling_folded():
    t = Task()
    try:
        claim(t.walk("W1"), kind="Book", instance="17")
        with mock.patch.dict(WS.OVERRIDE, {"claim_wait_s": 1}):
            for spelling in (" book ", "BOOK", "BoOk"):
                assert claim(t.walk("W2", items=("TC-2",)), item="TC-2", kind=spelling, instance="17")[0] == 2, spelling
            assert claim(t.walk("W2", items=("TC-2",)), item="TC-2", kind="books", instance="17")[0] == 0     # two kinds: the walker's words
    finally:
        t.done()


def test_all_blocks_instances_and_reverse():
    t = Task()
    try:
        one = t.walk("W1")
        claim(one, kind="book", instance="17")
        two = t.walk("W2", items=("TC-2",))
        with mock.patch.dict(WS.OVERRIDE, {"claim_wait_s": 1}):
            assert claim(two, item="TC-2", kind="book", all=True)[0] == 2          # --all while another walk holds an instance
            claim(one, kind="shelf", all=True)
            assert claim(two, item="TC-2", kind="shelf", instance="a")[0] == 2     # an instance while another walk holds the whole list
        assert claim(two, item="TC-2", kind="shelf-b", all=True)[0] == 0
        assert claim(two, item="TC-2", kind="book")[0] == 2 and claim(two, item="TC-2", kind="book", instance="1", all=True)[0] == 2   # shape
        assert claim(two, item="TC-2", kind="book", instance="*")[0] == 2
    finally:
        t.done()


def test_own_claims_never_block():
    t = Task()
    try:
        one = t.walk("W1")
        assert claim(one, kind="book", instance="17")[0] == 0
        assert claim(one, kind="book", all=True)[0] == 0                          # --all over its own instance
        assert claim(one, kind="book", instance="18")[0] == 0 and claim(one, kind="book", instance="17")[0] == 0
        assert len(WS.claims_of(t.root, "W1")[0]) == 3                            # one row per (kind, instance): a repeat does not add one
    finally:
        t.done()


def teardown_road(teardown, names=True):
    """Claim book 17 in a real walk, store a verdict whose `teardown` is `teardown` (absent when None) on a case that does (`names`) or
    does not name a teardown; the states of the walk's rows afterwards."""
    rig = W.Rig().start()
    try:
        rig.step(W.GO)
        assert rig.call("claim", item=CASE, kind="book", instance="17")[0] == 0
        verdict = {"thens": [], "limitation": "the case lists no Then", **({} if teardown is None else {"teardown": teardown})}
        with R.case_file(rig, teardown="remove the book" if names else ""):
            code, answer = rig.call("verdict", item=CASE, verdict=verdict)
        assert code == 0, answer
        return [r["state"] for r in WS.claims_of(rig.t.task)[0]]
    finally:
        rig.done()


def test_verdict_teardown_done_frees():
    assert teardown_road("done") == ["free"]


def test_verdict_teardown_not_done_goes_dirty():
    assert teardown_road("not_done") == ["dirty"]           # B1: the walker said it could not restore the record: never offered again
    assert teardown_road("none") == ["dirty"]               # a case that names a teardown and a verdict that says there was none


def test_verdict_without_teardown_field_goes_dirty():
    assert teardown_road(None, names=False) == ["dirty"]    # no section, no field
    assert teardown_road("done", names=False) == ["dirty"]  # no section: nothing says the record was restored


def test_verdict_teardown_frees_else_dirty():
    t = Task()
    try:
        walk = t.walk("W1")
        claim(walk, kind="book", instance="17")
        claim(walk, kind="cart", instance="9")
        WS._release_claims(walk, "TC-1", teardown=True)
        assert states(t) == {("W1", "17"): "free", ("W1", "9"): "free"}
        claim(walk, kind="book", instance="17")
        WS._release_claims(walk, "TC-1", teardown=False)
        assert states(t) == {("W1", "17"): "dirty", ("W1", "9"): "free"}
        assert WS._release_claims(walk, "TC-2", teardown=True) == 0               # another item's claims stay
    finally:
        t.done()


def test_dirty_refused():
    t = Task()
    try:
        one = t.walk("W1")
        claim(one, kind="book", instance="17")
        WS._release_claims(one, "TC-1", teardown=False)
        code, answer = claim(t.walk("W2", items=("TC-2",)), item="TC-2", kind="book", instance="17")
        assert code == 2 and "changed by walk W1" in answer["text"] and "not restored" in answer["text"] and "use another record" in answer["text"], answer
        assert t.clock.now == 0, t.clock.now                                        # waiting does not restore a record: refused at once
        assert claim(t.walk("W2", items=("TC-2",)), item="TC-2", kind="book", instance="18")[0] == 0
        assert claim(one, kind="book", instance="17")[0] == 0                       # the walk that made it dirty is never blocked by itself
    finally:
        t.done()


def test_dead_holder_reads_dirty():
    t = Task()
    try:
        gone = t.walk("W1", live=False)                                             # no record of it: not alive
        claim(gone, kind="book", instance="17")
        code, answer = claim(t.walk("W2", items=("TC-2",)), item="TC-2", kind="book", instance="17")
        assert code == 2 and "walk ended" in answer["text"] and "not restored" in answer["text"], answer
        assert t.clock.now == 0 and states(t)[("W1", "17")] == "in_use"            # read as dirty, the row is not rewritten by a reader
    finally:
        t.done()


def test_store_unreadable_refuses():
    t = Task()
    try:
        path = WS.claims_path(t.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        for body in ("{not json", json.dumps({"claims": "x"}), json.dumps({"claims": [{"kind": "book"}]})):
            path.write_text(body, encoding="utf-8")
            assert WS.claims_of(t.root)[1] != ""
            code, answer = claim(t.walk("W1"), kind="book", instance="17")
            assert code == 2 and "record of claims cannot be read" in answer["text"], answer
            assert path.read_text(encoding="utf-8") == body                        # nothing written
    finally:
        t.done()


def test_close_marks_dirty():
    rig = W.Rig().start()
    try:
        assert rig.call("claim", item=CASE, kind="book", instance="17")[0] == 0
        assert {r["state"] for r in WS.claims_of(rig.t.task)[0]} == {"in_use"}
        rig.call("close")
        assert {(r["walk"], r["state"]) for r in WS.claims_of(rig.t.task)[0]} == {(W.WALK, "dirty")}
    finally:
        rig.done()


def test_settle_place_refused():
    t = Task()
    try:
        code, answer = claim(t.walk("W1", place="settle"), kind="book", instance="17")
        assert code == 2 and "claims are for case lanes" in answer["text"], answer
        assert not WS.claims_path(t.root).exists()
    finally:
        t.done()


def test_released_only_after_stored_verdict():
    rig = W.Rig().start()
    try:
        rig.step(W.GO)
        rig.call("claim", item=CASE, kind="book", instance="17")
        code, answer = rig.call("verdict", item=CASE, verdict={"thens": [{"n": 99, "result": "pass", "quote": "nothing like this"}]})
        assert code == 2, answer                                                    # refused: nothing stored
        assert [r["state"] for r in WS.claims_of(rig.t.task)[0]] == ["in_use"]       # the claim is kept
        with R.case_file(rig, teardown="remove the book"):
            code, answer = rig.call("verdict", item=CASE, verdict={"thens": [], "limitation": "the case lists no Then", "teardown": "done"})
        assert code == 0, answer
        assert [r["state"] for r in WS.claims_of(rig.t.task)[0]] == ["free"]         # stored, then released (a teardown is named and done)
    finally:
        rig.done()


def test_claim_lock_busy_names_holder_nothing_written():
    t = Task()
    try:
        held = ES.take_file_lock(WS.claims_path(t.root).with_suffix(".lock"), 0, purpose="test holds it", record_holder=True)
        try:
            with mock.patch.object(WS, "CLAIM_LOCK_WAIT_S", 0.2):
                code, answer = claim(t.walk("W1"), kind="book", instance="17")
        finally:
            held.release()
        assert code == 2 and "held by another walker for over 0.2 s: nothing was written. Repeat the step; " in answer["text"], answer
        assert not WS.claims_path(t.root).exists()
        assert claim(t.walk("W1"), kind="book", instance="17")[0] == 0              # released: the same call now writes
    finally:
        t.done()


def test_instance_cut_at_200_in_texts_kept_whole_in_the_list():
    t = Task()
    try:
        one = t.walk("W1")
        for size in (200, 201):
            instance = "x" * size
            claim(one, kind="k" + str(size), instance=instance)
            with mock.patch.dict(WS.OVERRIDE, {"claim_wait_s": 1}):
                code, answer = claim(t.walk("W2", items=("TC-2",)), item="TC-2", kind="k" + str(size), instance=instance)
            assert code == 2 and ("x" * 200) in answer["text"] and ("x" * 201) not in answer["text"], size
            assert any(r["instance"] == instance for r in WS.claims_of(t.root)[0])
    finally:
        t.done()


def test_all_granted_over_dirty_names_them():
    t = Task()
    try:
        one = t.walk("W1")
        claim(one, kind="book", instance="17")
        claim(one, kind="book", instance="18")
        claim(one, kind="cart", instance="9")
        WS._release_claims(one, "TC-1", teardown=False)                            # all three are dirty now
        code, answer = claim(t.walk("W2", items=("TC-2",)), item="TC-2", kind="Book", all=True)
        assert code == 0, answer                                                    # L1: not refused because of a dirty instance
        assert answer["note"] == "changed earlier and not restored: 17, 18", answer     # this kind only, one line
        assert states(t)[("W2", "*")] == "in_use"
        gone = t.walk("W3", live=False, items=("TC-3",))
        claim(gone, item="TC-3", kind="shelf", instance="s1")
        code, answer = claim(t.walk("W4", items=("TC-4",)), item="TC-4", kind="shelf", all=True)
        assert code == 0 and "s1" in answer["note"], answer                        # a holder that is gone reads dirty: named too
    finally:
        t.done()


def assign(t, walk, kind, instance, item="TC-1"):
    """What `walk_pool.assign_entities` writes before a dispatch: an `in_use` row for a walk that has no record yet."""
    row = {"kind": kind, "instance": instance, "walk": walk, "item": item, "state": "in_use", "at": "2026-11-10T00:00:00"}
    assert WS.update_claims(t.root, lambda rows: ([*rows, row], None))[0] == ""


def test_assigned_before_open_blocks_all():
    t = Task()
    try:
        assign(t, "W1", "book", "17")                                               # W1's agent has not opened the walk: no record
        two = t.walk("W2", items=("TC-2",))
        with mock.patch.dict(WS.OVERRIDE, {"claim_wait_s": 1}):
            code, answer = claim(two, item="TC-2", kind="book", all=True)
            assert code == 2 and "walk W1" in answer["text"], answer                # C.1: never `*` over an instance another walk holds
            assert t.clock.now >= 1, t.clock.now                                    # held, not dirty: it WAITED the data value
            assert ("W2", "*") not in states(t)
            t.walk("W1")                                                            # the agent opens the walk: the live rule reads the same row
            assert claim(two, item="TC-2", kind="book", all=True)[0] == 2
            t.walk("W1", live=False)                                                # the walk ended (a record that is not alive): dirty
            code, answer = claim(two, item="TC-2", kind="book", all=True)
        assert code == 0 and "17" in answer["note"], answer
    finally:
        t.done()


def test_settle_unopened_is_the_exit_of_a_walk_that_never_opened():
    """R1 (AR-25): rows assigned to a walk with no record go `dirty` (or `free` for a reservation no dispatch took); a walk with a record is untouched."""
    t = Task()
    try:
        assign(t, "W1", "book", "17")
        assign(t, "W3", "book", "19")
        t.walk("W3")                                                                # W3 opened: it has a record, its own end releases the row
        assert WS.settle_unopened(t.root, "W3") == (0, ""), "a walk with a record is not touched"
        assert WS.settle_unopened(t.root, "W1") == (1, "")
        assert [(r["walk"], r["state"]) for r in WS.claims_of(t.root)[0]] == [("W1", "dirty"), ("W3", "in_use")]
        assign(t, "W2", "book", "21")
        assert WS.settle_unopened(t.root, "W2", "free") == (1, "")
        assert WS.settle_unopened(t.root, "W2") == (0, ""), "nothing left to settle: no lock, no change"
        assert ("W2", "free") in [(r["walk"], r["state"]) for r in WS.claims_of(t.root)[0]]
    finally:
        t.done()


def test_assigned_before_open_blocks_same_instance():
    t = Task()
    try:
        assign(t, "W1", "Book", "17")
        two = t.walk("W2", items=("TC-2",))
        with mock.patch.dict(WS.OVERRIDE, {"claim_wait_s": 1}):
            assert claim(two, item="TC-2", kind="book", instance="17")[0] == 2
            assert claim(two, item="TC-2", kind="book", instance="18")[0] == 0      # another record of the kind is free
            assert claim(two, item="TC-2", kind="shelf", all=True)[0] == 0          # another kind is free
    finally:
        t.done()


def test_assigned_before_open_not_named_dirty():
    t = Task()
    try:
        assign(t, "W1", "book", "17")
        two = t.walk("W2", items=("TC-2",))
        with mock.patch.dict(WS.OVERRIDE, {"claim_wait_s": 1}):
            for fields in ({"instance": "17"}, {"all": True}):
                code, answer = claim(two, item="TC-2", kind="book", **fields)
                text = answer["text"]
                assert code == 2 and "is in use by walk W1" in text and "not restored" not in text and "ended" not in text, text
        assert WS.claim_state({"state": "in_use", "walk": "W1"}, WS.held_walk_ids(t.root, WS.claims_of(t.root)[0])) == "held"
        assert WS._dirty_instances(WS.claims_of(t.root)[0], "book", WS.held_walk_ids(t.root, WS.claims_of(t.root)[0])) == []      # no "changed earlier" note
    finally:
        t.done()


def test_claim_write_oserror_refuses_nothing_granted():
    t = Task()
    try:
        one = t.walk("W1")
        with mock.patch.object(ES, "atomic_json", side_effect=OSError("disk full")):
            code, answer = claim(one, kind="book", instance="17")
        assert code == 2 and "the list of claims could not be written: nothing was written. Repeat the step." in answer["text"], answer
        assert answer.get("status") != "ok" and "Traceback" not in answer["text"]
        assert WS.claims_of(t.root) == ([], "")                                     # nothing was granted
        assert claim(t.walk("W1"), kind="book", instance="17")[0] == 0              # the repeat writes
    finally:
        t.done()


def test_all_with_no_dirty_prints_no_line():
    t = Task()
    try:
        one = t.walk("W1")
        claim(one, kind="book", instance="17")
        WS._release_claims(one, "TC-1", teardown=True)                              # free, not dirty
        code, answer = claim(t.walk("W2", items=("TC-2",)), item="TC-2", kind="book", all=True)
        assert code == 0 and "note" not in answer, answer
        code, answer = claim(t.walk("W3", items=("TC-3",)), item="TC-3", kind="cart", instance="9")
        assert code == 0 and "note" not in answer, answer                          # an instance claim never carries the line
    finally:
        t.done()


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
