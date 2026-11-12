#!/usr/bin/env python3
"""GW1-43 (release 0.10.8): the person's decision about a probe gap holds for every test of the story whose probe the tool could not read.

TP1-12586 / CART-1: a probe the tool refused was accepted by the person for ONE test, and the same question came back for the next
window, test after test. The word is now stored with the `class` of its data row (`references/block-names.json`, `waiver.apply_stage_override`),
read by ONE function (`contract.probe_gap_class_word`) AFTER the equality of the test's own word, and applied by the window
(`window_record.probe_gap_block`) and the acceptance (`acceptance.probe_gap_named`) only to a green test whose probe record says the TOOL
could not read it (`proof_level.probe_record_state` / `probe_could_not_run`).

Forbidden error: a window closed without a word, or over a probe nobody ran. Allowed error: ask again.

Keys: c1 the table of edges of spec section 4 through both readers (R1..R20); c2 the class stored by the real table, a bad table; c3 the
revocation rules; c4 the record state; c5 the window build end to end; c6 the segment; c7 the repeat of gate A (`check_vcs`) and its door;
c8 the F-4 observation; c9 the data row; c10 run_stage says it recorded without a class.
"""
import contextlib
import copy
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import acceptance as AC  # noqa: E402
import contract as C  # noqa: E402
import gate_preflight  # noqa: E402
import proof_level  # noqa: E402
import waiver as W  # noqa: E402
import window_record as WR  # noqa: E402

KLASS = "probe_gap_accepted"
KEY = "class:" + KLASS
WORDS = "go on: the tool cannot read these tests, I check them by hand"
BYTES = "a" * 64
OTHER = "b" * 64


# --- the fixtures -------------------------------------------------------------------------------------------------

def task_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="qa-decision-classes-"))


def say(pipeline: dict, match: str, words: str = WORDS, at: str = "2026-10-30T10:00:00+00:00", stage: str = "S5") -> dict:
    """The person's word, stored the way `waiver.py` stores it (the real table decides the class)."""
    return W.apply_stage_override(pipeline, stage, match, words, at)


def record(task: Path, iid: str, verdict: str = "not_executed", sha: str = BYTES, kind: str = "", **extra) -> Path:
    """`work/probes/<stem>.json` the way `probe_by_code` leaves it; `refused: tool` is the record of a refusal of the tool."""
    path = proof_level.probe_record_path(task, iid, kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"schema_version": 1, "probe_tool": "probe_by_code.py", "instance_id": iid, "verdict": verdict,
            "test_file_sha256": sha, "notes": ["probe_by_code: no declaration of the test"], "recorded_at": "2026-10-30T09:00:00+00:00", **extra}
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def window_of(iid: str, case: str = "TC-1", outcome: str = "passed", sha: str = BYTES) -> dict:
    return {"scope_instances": {case: [iid]},
            "instances": [{"instance_id": iid, "input_hash": sha, "outcome": outcome, "probe_gap": {"verdict": "not_run"}}]}


def both(task: Path, pipeline: dict, iid: str, case: str = "TC-1", outcome: str = "passed", sha: str = BYTES):
    """(the acceptance's key or None, the window block's `named_by` or None) - the two readers over ONE story."""
    (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
    named = AC.probe_gap_named(window_of(iid, case, outcome, sha), task).get(iid)
    item = {"instance_id": iid, "input_hash": sha, "outcome": outcome}
    block = WR.probe_gap_block(task, item, [case], C.probe_gap_words(pipeline), C.probe_gap_class_word(pipeline, [iid, case]))
    return (named or {}).get("key"), (block or {}).get("named_by")


def classed(*values) -> dict:
    """One live class record per value, said a minute apart (the n-th at 10:0n)."""
    pipeline: dict = {}
    for n, value in enumerate(values):
        say(pipeline, "probe gap: " + value, at=f"2026-10-30T10:{n:02d}:00+00:00")
    return pipeline


# --- c1: the table of edges ---------------------------------------------------------------------------------------

def c1_the_edges() -> None:
    task = task_dir()
    try:
        pipeline = say({}, "probe gap: TC_ASKED_ABOUT")          # the word of the person, about ANOTHER test
        iid = "test_a[x]"
        record(task, iid, refused="tool")
        check_eq("R1 refusal of the tool (`refused: tool`): both readers take the class word", both(task, pipeline, iid), (KEY, KEY))
        block = WR.probe_gap_block(task, {"instance_id": iid, "input_hash": BYTES, "outcome": "passed"}, [], C.probe_gap_words(pipeline),
                                   C.probe_gap_class_word(pipeline, [iid]))
        check_eq("R1 the block: the person's words whole, the verdict as it stands, the record named",
                 (block["words"], block["verdict"], block["record"], block["at"]),
                 (WORDS, "not_executed", "work/probes/" + proof_level.probe_record_path(task, iid).name, "2026-10-30T10:00:00+00:00"))
        check_eq("R1 the shape check accepts the block", C.probe_gap_errors({"outcome": "passed", "probe_gap": block}), [])
        # R2 no record: a probe nobody tried
        os.remove(proof_level.probe_record_path(task, iid))
        check_eq("R2 no record: the probe nobody ran takes no class word", both(task, pipeline, iid), (None, None))
        record(task, iid, refused="tool", sha=OTHER)
        check_eq("R3 a record of other bytes takes none", both(task, pipeline, iid), (None, None))
        record(task, iid)
        check_eq("R4 `not_executed` with no `refused` (the stand was down): its own door", both(task, pipeline, iid), (None, None))
        record(task, iid, refused="stand")
        check_eq("R4b `refused` that is not `tool`: its own door", both(task, pipeline, iid), (None, None))
        record(task, iid, verdict="incomplete")
        check_eq("R5 `incomplete` of these bytes: the tool did not read it, the class word is taken", both(task, pipeline, iid), (KEY, KEY))
        for verdict in ("intended_failure", "no_failure", "wrong_location"):
            record(task, iid, verdict=verdict, refused="tool")
            check_eq(f"R6 a probe that JUDGED ({verdict}) takes none", both(task, pipeline, iid), (None, None))
        record(task, iid, verdict="", refused="tool")
        check_eq("R6b a record with no verdict is `not_run`", both(task, pipeline, iid), (None, None))
        record(task, iid, refused="tool")
        for outcome in ("failed", "handed_to_person", "blocked_by_env"):
            check_eq(f"R7 a {outcome} item takes none (`outcome == passed` is required, FR-18)", both(task, pipeline, iid, outcome=outcome),
                     (None, None))
        # R9 equality precedes the class
        own = say(copy.deepcopy(pipeline), "probe gap: " + iid, words="mine")
        check_eq("R9 the test's own word is quoted by the person, not by the class", both(task, own, iid), (iid, iid))
        case_word = say(copy.deepcopy(pipeline), "probe gap: TC-1", words="case")
        check_eq("R9b the word about its case comes before the class", both(task, case_word, iid), ("TC-1", "TC-1"))
        # R10 a record the role wrote itself, no word at all
        check_eq("R10 no word of the person: nothing", both(task, {}, iid), (None, None))
        # R11 an old record with no class; another value; another stage
        old = {"stage_overrides": [{"stage": "S5", "match": "probe gap: TC_OLD", "decision": WORDS, "at": "2026-10-01T00:00:00+00:00"}]}
        check_eq("R11 a record with no `class` (written before): only its own equality", both(task, old, iid), (None, None))
        foreign = {"stage_overrides": [{"stage": "S5", "match": "probe gap: TC_OLD", "decision": WORDS, "class": "something_else"}]}
        check_eq("R11b a `class` with a value that is not ours acts nowhere", both(task, foreign, iid), (None, None))
        other_stage = {"stage_overrides": [{"stage": "S6", "match": "probe gap: TC_OLD", "decision": WORDS, "class": KLASS}]}
        check_eq("R11c a `class` of another stage acts nowhere", both(task, other_stage, iid), (None, None))
        empty_words = {"stage_overrides": [{"stage": "S5", "match": "probe gap: TC_OLD", "decision": "  ", "class": KLASS}]}
        check_eq("R11d a class record with empty words acts nowhere", both(task, empty_words, iid), (None, None))
        # R12 words that are not a class record
        for label, match in (("a star", "*"), ("not receipted", "not receipted")):
            check_eq(f"R12 {label} is no class", both(task, say({}, match), iid), (None, None))
        # R13 an unreadable or absent pipeline
        (task / "pipeline.json").write_text("{not json", encoding="utf-8")
        check_eq("R13 an unreadable pipeline.json names nobody (acceptance)", AC.probe_gap_named(window_of(iid), task), {})
        for bad in (None, "text", [], {"stage_overrides": "x"}, {"stage_overrides": [None, 3, "x"]}):
            check_eq(f"R13 a pipeline that is {bad!r} gives no class word", C.probe_gap_class_word(bad, [iid]), None)
        # R14 a product-kind record (red_sandbox --probe) is not read
        os.remove(proof_level.probe_record_path(task, iid))
        record(task, iid, kind="product", refused="tool")
        check_eq("R14 a record of `work/probes/product/` is not read", both(task, pipeline, iid), (None, None))
        # R15 `at`
        record(task, iid, refused="tool")
        early = {"stage_overrides": [
            {"stage": "S5", "match": "probe gap: A", "decision": "dated", "at": "2026-10-02T00:00:00+00:00", "class": KLASS},
            {"stage": "S5", "match": "probe gap: B", "decision": "undated", "at": "", "class": KLASS},
            {"stage": "S5", "match": "probe gap: C", "decision": "garbled", "at": "yesterday", "class": KLASS}]}
        check_eq("R15 an empty or unreadable `at` is the oldest: the dated word is the class word",
                 C.probe_gap_class_word(early, [iid])["words"], "dated")
        undated = {"stage_overrides": [{"stage": "S5", "match": "probe gap: A", "decision": "first", "class": KLASS},
                                       {"stage": "S5", "match": "probe gap: B", "decision": "second", "class": KLASS}]}
        check_eq("R15b all undated: the later position", C.probe_gap_class_word(undated, [iid])["words"], "second")
        latest = {"stage_overrides": [
            {"stage": "S5", "match": "probe gap: A", "decision": "new", "at": "2026-10-03T00:00:00+00:00", "class": KLASS},
            {"stage": "S5", "match": "probe gap: B", "decision": "old", "at": "2026-10-01T00:00:00+00:00", "class": KLASS}]}
        check_eq("R15c the latest by `at`, not by position", C.probe_gap_class_word(latest, [iid])["words"], "new")
        check_eq("R15d the words travel whole and folded", C.probe_gap_class_word(
            {"stage_overrides": [{"stage": "S5", "match": "probe gap: A", "decision": "a  b\nc", "class": KLASS}]}, [iid])["words"], "a b c")
        # R17 a word about ONE language is no class word (GW1-43 question, Lead's decision): it closes that language's probes by
        # equality (`tooling_gap_key`), never every test of the story
        tooling = say({}, "probe gap: tooling:typescript")
        check_eq("R17 a `tooling:<language>` word stored with the class gives no class word", C.probe_gap_class_word(tooling, [iid]), None)
        check_eq("R17b ... so the readers over a refused test whose record names no language (a .py file, no detector entry) name nobody",
                 both(task, tooling, iid), (None, None))
        # F-2 (t-596): the matrix of "the tool could not read this" - ONE answer from `tooling_gap_key` and `probe_could_not_run`
        ts = {"cause": "tooling", "language": "typescript"}
        record(task, iid, refused="tool", **ts)
        check_eq("R17d `refused: tool` that says tooling + language (what the producer writes): the language word closes it, in both readers",
                 both(task, tooling, iid), ("tooling:typescript", "tooling:typescript"))
        check_eq("R17e ... and the class word (a word about another test) closes it too", both(task, pipeline, iid), (KEY, KEY))
        record(task, iid, **ts)
        check_eq("R17f `not_executed` + cause tooling (an unbound report row): the class word is taken, as the language word is",
                 (both(task, pipeline, iid), both(task, tooling, iid)), ((KEY, KEY), ("tooling:typescript", "tooling:typescript")))
        record(task, iid, verdict="incomplete", **ts)
        check_eq("R17g `incomplete` + cause tooling: both words close it",
                 (both(task, pipeline, iid), both(task, tooling, iid)), ((KEY, KEY), ("tooling:typescript", "tooling:typescript")))
        record(task, iid, verdict="incomplete", cause="tooling", language="python")
        check_eq("R17h another language: the class word closes it, the typescript word does not (a new question)",
                 (both(task, pipeline, iid), both(task, tooling, iid)), ((KEY, KEY), (None, None)))
        record(task, iid)
        check_eq("R17i a stand that did not run (`not_executed`, no cause, no refusal): no word of either kind closes it",
                 (both(task, pipeline, iid), both(task, tooling, iid)), ((None, None), (None, None)))
        record(task, iid, language="typescript")
        check_eq("R17j a language with no `cause: tooling` is no gap of the tool", both(task, tooling, iid), (None, None))
        record(task, iid, refused="tool")
        mixed = say(copy.deepcopy(tooling), "probe gap: TC_ASKED_ABOUT", words="the story", at="2026-10-30T09:00:00+00:00")
        check_eq("R17c a tooling word dated LATER than a class word does not take its place",
                 (C.probe_gap_class_word(mixed, [iid]) or {}).get("words"), "the story")
        # another history: its own pipeline.json
        elsewhere = task_dir()
        try:
            record(elsewhere, iid, refused="tool")
            check_eq("R16 another story has its own pipeline.json: the word does not leak", both(elsewhere, {}, iid), (None, None))
        finally:
            shutil.rmtree(elsewhere, ignore_errors=True)
    finally:
        shutil.rmtree(task, ignore_errors=True)


# --- c2: the class is stored by the real table -----------------------------------------------------------------------

def c2_the_class_is_stored() -> None:
    pipeline: dict = {}
    for match, want in (("probe gap: TC_1", KLASS), ("probe gap: tooling:typescript", KLASS), ("probe gap: <case key or tooling:language>", ""),
                        ("probe gap: two words", ""), ("then handed: TC-1#1", ""), ("executor unavailable: e2e-ui", ""), ("*", ""),
                        ("not receipted", ""), ("keep it local", "")):
        say(pipeline, match, stage="S5" if match != "keep it local" else "S8")
        entry = pipeline["stage_overrides"][-1]
        check_eq(f"c2 `{match}`: class {want!r}", entry.get("class", ""), want)
    check_eq("c2 `probe gap:` at another stage is no name, so no class", W.record_class("probe gap: TC_1", "S6"), ("", ""))
    # the same block said again replaces the record; the class follows the table at the new time
    again = say({}, "probe gap: TC_1")
    say(again, "probe gap: TC_1", words="again")
    check_eq("c2 said again: ONE record, with the class", [(e["decision"], e.get("class")) for e in again["stage_overrides"]], [("again", KLASS)])
    # a table that cannot be read: the word is still recorded, without a class
    real = W.load_block_names

    def broken(*args, **kwargs):
        raise W.BlockNamesError("references/block-names.json (x) cannot be used: row 4 is not an object")
    W.load_block_names = broken
    try:
        unread = say({}, "probe gap: TC_1")
        check_eq("c2 a table that cannot be read: the record is made, with no class", unread["stage_overrides"][0].get("class"), None)
        check_eq("c2 ... and `record_class` says why", W.record_class("probe gap: TC_1", "S5")[0], "")
        check_in("c2 ... naming the file", "block-names.json", W.record_class("probe gap: TC_1", "S5")[1])
        check_eq("c2 ... so the class acts nowhere (the person is asked again, nothing is passed)",
                 C.probe_gap_class_word(unread, ["TC_2"]), None)
    finally:
        W.load_block_names = real
    # the table validates the key
    tmp = task_dir()
    try:
        for label, value, ok in (("a string", "x_class", True), ("empty", "", False), ("blank", "  ", False), ("a number", 5, False), ("a list", ["x"], False)):
            row = {"block": "probe gap: <instance>", "reader": "contract:probe_gap_words", "stages": ["S5"], "class": value}
            (tmp / "names.json").write_text(json.dumps({"names": [row]}), encoding="utf-8")
            try:
                got = W.load_block_names(tmp / "names.json")[0].get("class")
            except W.BlockNamesError as exc:
                got = "ERR " + str(exc)
            check(f"c2 a table row with `class` = {label}: {'accepted' if ok else 'refused, naming the key'}",
                  (got == value.strip()) if ok else (isinstance(got, str) and got.startswith("ERR") and "`class`" in got), str(got))
        row = {"block": "probe gap: <instance>", "reader": "contract:probe_gap_words", "stages": ["S5"]}
        (tmp / "names.json").write_text(json.dumps({"names": [row]}), encoding="utf-8")
        check_eq("c2 a row with no `class` has none", "class" in W.load_block_names(tmp / "names.json")[0], False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- c3: revocation -------------------------------------------------------------------------------------------------

def c3_the_revocation() -> None:
    task = task_dir()
    try:
        ids = [f"TC_{n:03d}" for n in range(1, 11)]
        pipeline = classed(*ids)
        for iid in ("TC_003", "TC_004", "TC_011"):
            record(task, iid, refused="tool")
        W.revoke_stage_override(pipeline, "S5", "probe gap: TC_003", "no, not that one", "2026-10-30T11:00:00+00:00")
        check_eq("c3 a word about TC_003 was taken back (nine live): the window with TC_003 is not closed",
                 both(task, pipeline, "TC_003", case="TC_003")[0:2], (None, None))
        check_eq("c3 ... the test whose own word was taken back is asked once, by its own key", both(task, pipeline, "TC_003", case="TC-1"), (None, None))
        check_eq("c3 ... TC_004 keeps its own word (equality first)", both(task, pipeline, "TC_004"), ("TC_004", "TC_004"))
        check_eq("c3 ... and a test with no word of its own (TC_011) is covered by the class", both(task, pipeline, "TC_011"), (KEY, KEY))
        say(pipeline, "probe gap: TC_003", words="yes, this one too", at="2026-10-30T12:00:00+00:00")
        check_eq("c3 the same block said again after the revoke acts (FR-40)", both(task, pipeline, "TC_003")[0], "TC_003")
        # one revoked record of ten does not put out the class
        ten = classed(*ids)
        W.revoke_stage_override(ten, "S5", "probe gap: TC_010", "x", "2026-10-30T11:00:00+00:00")
        check_eq("c3 the tenth revoked, nine live: the class stands for another test", both(task, ten, "TC_011"), (KEY, KEY))
        # all revoked, or `*`
        gone = classed(*ids)
        for iid in ids:
            W.revoke_stage_override(gone, "S5", "probe gap: " + iid, "x", "2026-10-30T11:00:00+00:00")
        check_eq("c3 every record revoked: no class", both(task, gone, "TC_011"), (None, None))
        star = classed(*ids)
        W.revoke_stage_override(star, "S5", "*", "take it all back", "2026-10-30T11:00:00+00:00")
        check_eq("c3 a revoke of `*` takes every record, and so the class", both(task, star, "TC_011"), (None, None))
        check_eq("c3 ... the reader says None", C.probe_gap_class_word(star, ["TC_011"]), None)
        # a revoked key that is the CASE key of the instance
        case_revoked = classed("TC-9", *ids)
        W.revoke_stage_override(case_revoked, "S5", "probe gap: TC-9", "x", "2026-10-30T11:00:00+00:00")
        check_eq("c3 the revoked word named the instance's CASE: the instance is asked", both(task, case_revoked, "TC_011", case="TC-9"), (None, None))
        # `probe_gap_words` keeps the equality: a revoked word names nobody
        check_eq("c3 `probe_gap_words` is unchanged: the revoked is absent", "TC_003" in C.probe_gap_words(
            (lambda p: (W.revoke_stage_override(p, "S5", "probe gap: TC_003", "x", "t"), p)[1])(classed(*ids))), False)
    finally:
        shutil.rmtree(task, ignore_errors=True)


# --- c4: the record state -------------------------------------------------------------------------------------------

def c4_the_record_state() -> None:
    task = task_dir()
    try:
        iid = "t[1]"

        def state(**kw):
            return proof_level.probe_record_state(task, iid, kw.get("sha", BYTES))
        check_eq("c4 no record", (state()["state"], state()["record"], state()["refused"]), ("not_run", None, ""))
        check_eq("c4 and says why", state()["why"], "no probe of these bytes was run")
        record(task, iid, refused="tool")
        got = state()
        check_eq("c4 refused: tool", (got["state"], got["refused"], got["why"]), ("not_executed", "tool", "probe_by_code: no declaration of the test"))
        check_eq("c4 ... and can-not-run", proof_level.probe_could_not_run(task, iid, BYTES), True)
        check_eq("c4 empty `input_hash`: not_run and False", (state(sha="")["state"], proof_level.probe_could_not_run(task, iid, "")), ("not_run", False))
        check_eq("c4 other bytes: not_run and False", (state(sha=OTHER)["why"], proof_level.probe_could_not_run(task, iid, OTHER)),
                 ("the probe record is of other bytes", False))
        record(task, iid, sha="")
        check_eq("c4 empty `test_file_sha256`: False", proof_level.probe_could_not_run(task, iid, BYTES), False)
        proof_level.probe_record_path(task, iid).write_text("{broken", encoding="utf-8")
        check_eq("c4 an unreadable record: not_run, False", (state()["state"], proof_level.probe_could_not_run(task, iid, BYTES)), ("not_run", False))
        proof_level.probe_record_path(task, iid).write_text("[1, 2]", encoding="utf-8")
        check_eq("c4 a record that is no object: not_run, False", (state()["state"], proof_level.probe_could_not_run(task, iid, BYTES)), ("not_run", False))
        record(task, iid, verdict="incomplete", notes=["site_unread: the page was not read"])
        check_eq("c4 incomplete (site_unread): can-not-run", (state()["state"], state()["why"], proof_level.probe_could_not_run(task, iid, BYTES)),
                 ("incomplete", "site_unread: the page was not read", True))
        # t-1968 N2 (E15): a record that owes the critic's judgment is NOT "the tool could not read it"; the pair is (can-not-run, owes-judgment)
        gap = lambda sha=BYTES: (proof_level.probe_could_not_run(task, iid, sha), proof_level.probe_owes_judgment(task, iid, sha))
        record(task, iid, verdict="incomplete", cause="judgment")
        check_eq("c4 E15 (incomplete, judgment) of these bytes: can-not-run False, owes `unjudged`", gap(), (False, "unjudged"))
        check_eq("c4 E15: the state still says incomplete and carries the cause", (state()["state"], state()["cause"]), ("incomplete", "judgment"))
        check_eq("c4 E15 of OTHER bytes: False / ''", gap(OTHER), (False, ""))
        check_eq("c4 E15 with an empty hash: False / ''", gap(""), (False, ""))
        record(task, iid, verdict="incomplete", cause="judgment", judgment={"verdict": "cannot_judge"})
        check_eq("c4 E15 judged `cannot_judge`: still not can-not-run, owes `cannot_judge`", gap(), (False, "cannot_judge"))
        record(task, iid, verdict="incomplete", cause="tooling")
        check_eq("c4 incomplete + `cause: tooling`: can-not-run True, owes ''", gap(), (True, ""))
        record(task, iid, verdict="incomplete")
        check_eq("c4 incomplete with no cause: can-not-run True, owes ''", gap(), (True, ""))
        record(task, iid, verdict="not_executed", cause="judgment")
        check_eq("c4 not_executed + judgment: False / '' (only `incomplete` owes it)", gap(), (False, ""))
        record(task, iid, verdict="intended_failure", cause="judgment")
        check_eq("c4 a record that judged: False / ''", gap(), (False, ""))
        proof_level.probe_record_path(task, iid).write_text("{broken", encoding="utf-8")
        check_eq("c4 an unreadable record: '' (never raises)", proof_level.probe_owes_judgment(task, iid, BYTES), "")
        check_eq("c4 a task root that does not exist: ''", proof_level.probe_owes_judgment(task / "nope", iid, BYTES), "")
        record(task, iid, verdict="intended_failure", refused="tool", last_attempt={"verdict": "not_executed"})
        check_eq("c4 intended_failure with a last_attempt: the verdict that judged, not a gap",
                 (state()["state"], state()["refused"], proof_level.probe_could_not_run(task, iid, BYTES)), ("judged", "", False))
        record(task, iid, notes=[])
        check_eq("c4 no notes: the generic line", state()["why"], "the probe did not run")
        check_eq("c4 `refused` that is no string is no word", (record(task, iid, refused=["tool"]) and state()["refused"]), "")
        check_eq("c4 a task root that does not exist is not_run, never a raise",
                 proof_level.probe_record_state(task / "nope" / "deeper", iid, BYTES)["state"], "not_run")
    finally:
        shutil.rmtree(task, ignore_errors=True)


# --- c5: the window build end to end ------------------------------------------------------------------------------

def c5_the_window_build() -> None:
    import test_probe_gap_word as GP
    import test_window_record as TW
    project = temp_project("qa-decision-classes-c5-")
    use_project(project)
    try:
        task = GP.gap_story(project, record=None, match="probe gap: SOME_OTHER_TEST", word=WORDS)
        GP.probe_record(task, refused="tool")
        window, _ = GP.built(task)
        gap = GP.item_of(window).get("probe_gap") or {}
        check_eq("c5 build: the test whose tool refused it is covered by the class word",
                 (gap.get("named_by"), gap.get("verdict"), gap.get("words")), (KEY, "not_executed", WORDS))
        check_eq("c5 build: the window's only gap is the named probe gap", AC.validate_window(window, task), ["probe_gap:" + GP.IID])
        check_eq("c5 build: the acceptance reads the same word (one join)",
                 {k: v["key"] for k, v in AC.probe_gap_named(window, task).items()}, {GP.IID: KEY})
        check_eq("c5 build: the shape check accepts it", C.window_shape_errors(window), [])
        check_in("c5 build: the segment says it was applied to this test", "decision of 2026-",
                 "\n".join(WR.probe_gap_segments(window, ["probe_gap:" + GP.IID])))
        # a probe nobody ran
        GP.probe_record(task).unlink()
        window, _ = GP.built(task)
        check_eq("c5 build: no record, no block", "probe_gap" in GP.item_of(window), False)
        # the stand was down
        GP.probe_record(task)
        window, _ = GP.built(task)
        check_eq("c5 build: `not_executed` with no `refused`: no block", "probe_gap" in GP.item_of(window), False)
        # the test's own word, then the class
        TW.say_word(task, GP.BLOCK, "mine")
        window, _ = GP.built(task)
        check_eq("c5 build: the test's own word is quoted first", GP.item_of(window)["probe_gap"]["named_by"], GP.IID)
        # a red test
        GP.probe_record(task, refused="tool")
        run_blocks = sorted((task / "work/run-blocks").glob("*b1.json"))
        failed = json.loads(run_blocks[0].read_text(encoding="utf-8"))
        failed["execution_status"], failed["results"][0]["status"] = "failed", "failed"
        TW.write(run_blocks[0], failed)
        window, _ = GP.built(task)
        check_eq("c5 build: a RED test takes no word, the class included", "probe_gap" in GP.item_of(window), False)
    finally:
        cleanup(project)


# --- c6: the segment ------------------------------------------------------------------------------------------------

def c6_the_segment() -> None:
    base = {"scope_instances": {"TC-1": ["t[1]"]}, "instances": [{"instance_id": "t[1]", "probe_gap": {
        "verdict": "not_executed", "why": "w", "named_by": KEY, "words": "the words, whole", "at": "2026-10-30T10:00:00+00:00"}}]}
    lines = ["probe_gap:t[1]"]
    check_eq("c6 a class decision: the words whole, the date, 'applied to this test'", WR.probe_gap_segments(base, lines),
             ['t[1] (TC-1): probe not_executed, w; their words: "the words, whole"; decision of 2026-10-30, applied to this test'])
    base["instances"][0]["probe_gap"]["named_by"] = "t[1]"
    check_eq("c6 the test's own word: the segment as before", WR.probe_gap_segments(base, lines),
             ['t[1] (TC-1): probe not_executed, w; their words: "the words, whole"'])
    base["instances"][0]["probe_gap"].update(named_by=KEY, at="")
    check_eq("c6 a class decision with no date: no empty date", WR.probe_gap_segments(base, lines),
             ['t[1] (TC-1): probe not_executed, w; their words: "the words, whole"; decision, applied to this test'])


# --- c7: the repeat of gate A, `check_vcs` ------------------------------------------------------------------------

def git(repo: Path, *args) -> str:
    done = subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@example.com", "-c", "user.name=t", "-c", "commit.gpgsign=false", *args],
                          capture_output=True, text=True)
    return done.stdout.strip()


def c7_the_vcs_door() -> None:
    from story_run_common import driver_for, seed
    root, task_root, env = seed("QA-9")
    repo = task_dir()
    try:
        git(repo, "init", "-q")
        (repo / "a.txt").write_text("1", encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "one")
        head = git(repo, "rev-parse", "HEAD")

        def rehearsal(pipeline=None):
            r = gate_preflight.Rehearsal(task_root, "A")
            r.project_root, r.config = repo, {"tests_root": "."}
            if pipeline is not None:
                r.pipeline = pipeline
            r.check_vcs()
            return r
        clean = rehearsal()
        check_eq("c7 a clean tree: ONE finding", [f["id"] for f in clean.findings], ["vcs-test-repo"])
        block = f"test repository state: {head[:12]}"
        check_eq("c7 ... with the door of the HEAD, not the number of changes", [d["block"] for d in clean.findings[0]["waives"]], [block])
        check_in("c7 ... and the door in words in `fix`", "write `vcs-test-repo: accept` with your reason", clean.findings[0]["fix"])
        check_in("c7 ... the message is the one it was", "will write test code on branch", clean.findings[0]["message"])
        (repo / "b.txt").write_text("2", encoding="utf-8")
        dirty = rehearsal()
        check_eq("c7 a dirty tree: ONE finding, the SAME door (HEAD)", [d["block"] for d in dirty.findings[0]["waives"]], [block])
        check_in("c7 ... the message is the one it was", "uncommitted change(s)", dirty.findings[0]["message"])
        said = say({}, block)
        (repo / "c.txt").write_text("3", encoding="utf-8")
        check_eq("c7 the word on this HEAD holds while the number of changes grows (S5 writes tests here)", rehearsal(said).findings, [])
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "two")
        moved = rehearsal(said)
        check_eq("c7 HEAD moved: a new door, one question", [f["id"] for f in moved.findings], ["vcs-test-repo"])
        check_eq("c7 ... of the new HEAD", moved.findings[0]["waives"][0]["block"], f"test repository state: {git(repo, 'rev-parse', 'HEAD')[:12]}")
        # `split_overridden` itself (the reader of the gate): a different number of changes passes, a different HEAD does not
        text = gate_preflight.matched_text(clean.findings[0]["message"], clean.findings[0]["waives"])
        check_eq("c7 split_overridden: the word on the HEAD lifts the block at another count", W.split_overridden([text], said, "S5")[0], [])
        check_eq("c7 split_overridden: a word on another HEAD does not", W.split_overridden([text], say({}, "test repository state: 000000000000"), "S5")[0], [text])
        # the line `vcs-test-repo: accept <reason>` is read by the driver
        d = driver_for(root, env, "QA-9")
        finding = clean.findings[0]
        shown = f"[{finding['id']}] {finding['message']}"
        read = d.read_finding_doors("vcs-test-repo: accept the branch is the one I want", [finding], shown, {"vcs-test-repo": finding["waives"]})
        check_eq("c7 `vcs-test-repo: accept <reason>` is read: one entry, the door of the HEAD, the reason whole",
                 [(e["id"], e["word"], e["door"]["block"], e["reason"]) for e in read["read"]],
                 [("vcs-test-repo", "accept", block, "the branch is the one I want")])
        no_reason = d.read_finding_doors("vcs-test-repo: accept", [finding], shown, {"vcs-test-repo": finding["waives"]})
        check_eq("c7 ... and `accept` with no reason is unread", (no_reason["read"], len(no_reason["unread"])), ([], 1))
        # a HEAD that cannot be read: no door, as before (the branch is known, the HEAD is not)
        real_git = gate_preflight._git
        gate_preflight._git = lambda root, *a, **k: "" if a == ("rev-parse", "HEAD") else real_git(root, *a, **k)
        try:
            empty = rehearsal()
            check_eq("c7 an empty HEAD: the finding stands and has NO door (as before)",
                     ([f["id"] for f in empty.findings], empty.findings[0].get("waives")), (["vcs-test-repo"], None))
            check_in("c7 ... and its fix names no door", "answer with your approval", empty.findings[0]["fix"])
            check_not_in("c7 ... and no door in words", "to pass this check anyway", empty.findings[0]["fix"])
        finally:
            gate_preflight._git = real_git
    finally:
        os.chdir(harness.PLUGIN_ROOT)
        shutil.rmtree(repo, ignore_errors=True)
        cleanup(root)


# --- c8: the F-4 observation ----------------------------------------------------------------------------------------

def c8_the_f4_fixture() -> None:
    """Spec section 4, first move: `source_inventory.completeness` with a live `gap-classes` record and `closed_by_class` gives
    `inventory_complete`, and the condition of `person.words` (`null-outcomes.json`, node N5) is lifted. This pins what the code DOES today."""
    import null_outcomes
    import source_inventory as SI
    media = {"url": "https://git.example.com/team/sdk/-/merge_requests/510", "status": "unavailable", "cause": "host_unreachable",
             "probe_ref": "sources/SRC-m/mr-510.json", "probe_code": "host_unreachable"}
    row = {"source_id": "SRC-m", "canonical_ref": "https://jira/browse/SRC-m", "relation": "referenced", "relevance": "relevant",
           "required": True, "status": "read", "inspection_status": "read", "human_review": {"words": "ok", "shown": {"relevance": "relevant"}},
           "materials": {"comments": {"status": "read"}, "attachments": {"status": "read", "items": []},
                         "external_media": {"status": "unavailable", "items": [media]}}}
    inventory = {"schema_version": 1, "sources": [row]}
    got = SI.completeness(inventory, size_limit=30000,
                          classes=[{"id": "GC-1", "cause": "host_unreachable", "words": "skip", "by": "human", "at": "2026-10-30T00:00:00+00:00"}])
    check_eq("c8 F-4: a live gap-class closes the point (`closed_by_class` is set)", bool(got["closed_by_class"]), True)
    condition = null_outcomes.CONDITIONS["inventory_complete"]
    check_eq("c8 F-4 observation: the condition `inventory_complete` is `reserved` (no implementation), so no code lifts `person.words`",
             (condition.status, condition.impl), ("reserved", None))
    check_eq("c8 F-4 observation: `completeness()['complete']` is False when a gap was closed by a class (`accepted_gaps` is not empty)",
             (got["complete"], got["accepted_gaps"]), (False, ["SRC-m"]))


# --- c9: the data row -----------------------------------------------------------------------------------------------

def c9_the_data_row() -> None:
    rows = W.load_block_names()
    marked = [r["block"] for r in rows if r.get("class")]
    check_eq("c9 exactly one row of the shipped table carries a class (the other rows get none)", marked, [W._fold("probe gap: <case key or tooling:language>")])
    check_eq("c9 ... and its value is the one the reader takes", [r["class"] for r in rows if r.get("class")], [C.PROBE_GAP_CLASS])
    check_eq("c9 the key a window prints", C.PROBE_GAP_CLASS_KEY, KEY)


# --- c10: run_stage says it recorded without a class ------------------------------------------------------------------

def c10_run_stage_says_so() -> None:
    project = temp_project("qa-decision-classes-c10-")
    use_project(project)
    real_load, real_standing, real_report = W.load_block_names, W.block_standing, W.standing_report
    try:
        task = project / "qa-factory" / "artifacts" / "T-1"
        task.mkdir(parents=True)
        (task / "pipeline.json").write_text(json.dumps({"ticket": "T-1"}), encoding="utf-8")

        def broken(*args, **kwargs):
            raise W.BlockNamesError("references/block-names.json (x) cannot be used")
        W.block_standing = lambda *a, **k: ("verified", [], None)
        W.standing_report = lambda *a, **k: []
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = W.run_stage("T-1", "S5", "probe gap: TC_1", "go on", "human")
        check_eq("c10 the real table: exit 0, the record has the class and nothing is said about a class",
                 (code, "recorded without a class" in out.getvalue(),
                  json.loads((task / "pipeline.json").read_text(encoding="utf-8"))["stage_overrides"][0].get("class")), (0, False, KLASS))
        (task / "pipeline.json").write_text(json.dumps({"ticket": "T-1"}), encoding="utf-8")
        W.load_block_names = broken
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = W.run_stage("T-1", "S5", "probe gap: TC_1", "go on", "human")
        check_eq("c10 a table that cannot be read: still exit 0 and the word is on record, without a class",
                 (code, json.loads((task / "pipeline.json").read_text(encoding="utf-8"))["stage_overrides"][0].get("class")), (0, None))
        check_in("c10 ... and the line says so, naming the file", "recorded without a class: BlockNamesError: references/block-names.json", out.getvalue())
    finally:
        W.load_block_names, W.block_standing, W.standing_report = real_load, real_standing, real_report
        cleanup(project)


def main() -> None:
    c1_the_edges()
    c2_the_class_is_stored()
    c3_the_revocation()
    c4_the_record_state()
    c5_the_window_build()
    c6_the_segment()
    c7_the_vcs_door()
    c8_the_f4_fixture()
    c9_the_data_row()
    c10_run_stage_says_so()
    finish("GW1-43 decision classes")


if __name__ == "__main__":
    main()
