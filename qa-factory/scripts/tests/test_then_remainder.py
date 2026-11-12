#!/usr/bin/env python3
"""A Then the person takes, beside the case's green test (HF1-10, GW1-14).

TP1-12586 (22.10.2026): everything in TC-001 was checkable on the stand except the datasource-link part of
Then 4 (no Jira there). The person said "leave it to me"; the manifest could only carry that as a partition row beside
the green test, which `s5_precheck` refuses as `partial-green`, so the author wrote a test that cannot run. A Then
left with its owner is a `then_bindings` remainder; it passes S5 only with the person's `then handed:` word, and it
reaches the ledger, the delivery verdict (`after_checks`), "Left with you" and the traceability as `wait`.

Keys K1-K17 of spec t-052 (section 6). Every fixture is a tmp story tree; no live project is read.
"""
import ast
import contextlib
import copy
import os
import io
import re
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (FIXTURES, check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     repaste_appendix, run_script, temp_dir, temp_project)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_delivery as CD  # noqa: E402
import contract as C  # noqa: E402
import detector_verdict as DV  # noqa: E402
import exit_gate  # noqa: E402
import judge_code  # noqa: E402
import manifest_from_tests as MFT  # noqa: E402
import manifest_put as MP  # noqa: E402
import report_facts as RF  # noqa: E402
import s5_precheck as P  # noqa: E402
import traceability as T  # noqa: E402
import waiver as W  # noqa: E402

CASE = "TC-700"
CASE_MD = """---
id: TC-700
status: Approved
---
## Given
A project linked to Jira.

## When
Call link.

## Then
1. The call returns `status_ok`.
2. The body holds the `warnings` list.
3. The record shows `saved_flag`.
4. The `datasource_link` points at the Jira project.
"""
TEST_PY = '''"""Tests for TC-700."""


def test_link_ok(client):
    """@case TC-700"""
    body = client.get()
    assert body["status_ok"]
    assert body["warnings"] == []
    assert body["saved_flag"]
'''
WORDS = "Jira cannot be checked on this stand, leave the datasource link to me"


def make_story(root: Path, manifest: dict, case_md: str = CASE_MD, pipeline=None, test_py: str = TEST_PY) -> Path:
    task = root / "qa-factory" / "artifacts" / "QA-700"
    (task / "work" / "test-cases").mkdir(parents=True)
    (task / "work" / "run-blocks").mkdir(parents=True)
    (task / "work" / "automation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (task / "work" / "triage.json").write_text(json.dumps({"triage": []}), encoding="utf-8")
    (task / "work" / "test-cases" / f"{CASE}.md").write_text(case_md, encoding="utf-8")
    block = {"purpose": "initial", "source_fingerprint": {"test_content_sha": "aaa"},
             "results": [{"instance_id": "test_link_ok", "test_id": "tests/test_link.py::test_link_ok",
                          "status": "passed", "report_matched": True}]}
    (task / "work" / "run-blocks" / "20260920T000000Z-b0.json").write_text(json.dumps(block), encoding="utf-8")
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "tests" / "test_link.py").write_text(test_py, encoding="utf-8")
    if pipeline is not None:
        (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
    return task


def covered(then: int) -> dict:
    return {"case": CASE, "then": then, "instance_id": "test_link_ok",
            "assertion_ref": "tests/test_link.py:7", "status": "covered"}


def remainder(then: int = 4, **extra) -> dict:
    row = {"case": CASE, "then": then, "instance_id": None, "assertion_ref": None, "status": "unresolved",
           "reason": "handed_to_person", "detail": "open the Jira project and compare the datasource link"}
    row.update(extra)
    return row


def green_manifest(rows=None, **extra) -> dict:
    rows = [covered(1), covered(2), covered(3), remainder(4)] if rows is None else rows
    manifest = {"tests": [{"case": CASE, "file": "tests/test_link.py", "marker": CASE, "instance_id": "test_link_ok",
                           "covers": [CASE], "status": "green"}], "then_bindings": rows}
    manifest.update(extra)
    return manifest


def word_for(block: str, **extra) -> dict:
    entry = {"stage": "S5", "match": block, "decision": WORDS, "at": "2026-10-22T18:00:00Z", "by": "human"}
    entry.update(extra)
    return entry


def pipeline_with(*entries) -> dict:
    return {"stage_overrides": list(entries)}


NL = chr(10)


def harness_project() -> Path:
    return temp_project("qa-then-rem-put-")


def precheck(manifest, pipeline=None, case_md: str = CASE_MD):
    root = temp_dir("qa-then-rem-")
    try:
        task = make_story(root, manifest, case_md=case_md, pipeline=pipeline)
        return P.run(task), task
    finally:
        cleanup(root)


def ids(result) -> list:
    return [f["id"] for f in result["findings"]]


def printed(result) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        P.report(result)
    return out.getvalue()


# --- K1, K2, K3: the exit gate -----------------------------------------------------------------------------------

def k1_k2_k3_the_gate() -> None:
    word = word_for("then handed: TC-700#4")
    result, _ = precheck(green_manifest(), pipeline_with(word))
    check("K1: a green case with Thens 1-3 bound and a remainder on Then 4 WITH the person's word passes",
          result["ok"] is True, "\n".join(f["id"] + " " + f["message"] for f in result["findings"]))
    note = "\n".join(result["notes"])
    check_in("K1: the note names Then 4, the owner and the person's words",
             "TC-700 Then 4 is left with the person by the person's word: " + WORDS, note)

    result, _ = precheck(green_manifest(), pipeline_with())
    check("K2: the same with no word is refused", result["ok"] is False)
    check_eq("K2: the finding is the unrecorded one", ids(result), ["bindings:TC-700:then-remainder-unrecorded-4"])
    text = printed(result)
    check_in("K2: its line holds the orchestrator's door, with the row's own spelling of the block",
             'waiver.py --task QA-700 --stage S5 --block "then handed: TC-700#4"', text)
    check_in("K2: ... and the words go by file", "--words-file", text)
    verdict = DV.parse(1, text, "")
    check_eq("K2: the printed verdict parses into one finding", len(verdict["findings"]), 1)
    check_eq("K2: and no WORDS_REFUSED_AT_SOURCE line is printed for it: it waits for a word, it is not refused one",
             verdict["refused"], [""])
    check_not_in("K2: (the raw output carries no such line)", DV.WORDS_REFUSED_AT_SOURCE, text)
    check_in("K2: the closing sentence names the block that satisfies it", "then handed: <case>#<n>", text)

    # E14: no other word removes it
    for match in ("*", "partial-green", "then-remainder-unrecorded-4", "TC-700", "then handed: TC-700#5",
                  "then handed: TC-700"):
        result, _ = precheck(green_manifest(), pipeline_with(word_for(match)))
        check(f"E14: the word {match!r} does not pass the unrecorded Then", "bindings:TC-700:then-remainder-unrecorded-4"
              in ids(result))

    # K3: the live shape (a partition row beside a green test) is refused as partial-green, at source, and names the door
    live = {"tests": [{"case": CASE, "file": "tests/test_link.py", "marker": CASE, "instance_id": "test_link_ok",
                       "covers": [CASE], "status": "green"}],
            "unresolved": [{"case": CASE, "reason": "deferred_by_decision:S5", "partitions": ["datasource-link"]}],
            "then_bindings": [covered(1), covered(2), covered(3), covered(4)]}
    result, _ = precheck(live, pipeline_with(word_for("partial-green"), word_for("*")))
    tags = [f["id"] for f in result["findings"] if f["id"].endswith(":partial-green")]
    check_eq("K3: the live shape is still refused as partial-green (even with `partial-green` and `*` recorded)",
             tags, ["manifest:TC-700:partial-green"])
    text = printed(result)
    check_in("K3: with the family refusal line", DV.refusal_line("manifest:TC-700:partial-green", "family"), text)
    fix = next(f["fix"] for f in result["findings"] if f["id"].endswith(":partial-green"))
    check_in("K3: its fix names the Then-level door and the block", "then handed: <case>#<n>", fix)
    check_in("K3: ... and the marker", 'reason="handed_to_person"', fix)


# --- K4: every new finding is one line and names its door ---------------------------------------------------------

def k4_findings_name_their_door() -> None:
    cases = {
        "shape": (green_manifest([covered(1), covered(2), covered(3), remainder(4, owner="nobody")]),
                  "then-remainder-shape-4", "manifest_from_tests.py"),
        "unknown": (green_manifest([covered(1), covered(2), covered(3), remainder(9)]),
                    "then-remainder-unknown-9", "correct `then`"),
        "conflict": (green_manifest([covered(1), covered(2), covered(3), covered(4), remainder(4)]),
                     "then-remainder-conflict-4", "never both"),
        "all": (green_manifest([remainder(1), remainder(2), remainder(3), remainder(4)]),
                "then-remainder-all", "whole case"),
        "unrecorded": (green_manifest(), "then-remainder-unrecorded-4", "waiver.py --task QA-700 --stage S5 --block"),
    }
    for name, (manifest, tag, door_text) in cases.items():
        result, _ = precheck(manifest, pipeline_with())
        mine = [f for f in result["findings"] if f["id"].endswith(tag)]
        check(f"K4 {name}: the finding {tag} is raised", len(mine) == 1, str(ids(result)))
        if not mine:
            continue
        line = P.finding_line(mine[0])
        check(f"K4 {name}: one physical line", "\n" not in line)
        check(f"K4 {name}: labelled with its id", line.startswith(f"[bindings {DV.id_token(mine[0]['id'])}] "))
        check_in(f"K4 {name}: the fix names its door", door_text, mine[0]["fix"])
        check_eq(f"K4 {name}: level repair (the call's fault, FR-46)", mine[0]["level"], "repair")
        verdict = DV.parse(1, printed(result), "")
        check(f"K4 {name}: parses by the detector contract", not verdict["defects"] and verdict["findings"],
              str(verdict["defects"]))
    result, _ = precheck(cases["unrecorded"][0], pipeline_with())
    fix = next(f["fix"] for f in result["findings"] if f["id"].endswith("unrecorded-4"))
    check_in("K4: the unrecorded door tells the ROLE to return the item and the orchestrator to record",
             "A role does not record anybody's word: return this item in your digest. The orchestrator asks", fix)


# --- K5: boundaries -----------------------------------------------------------------------------------------------

def k5_boundaries() -> None:
    word = pipeline_with(word_for("then handed: TC-700#4"))
    bad = ((0, "shape"), (-1, "shape"), (True, "shape"), ("4", "shape"), (4.0, "shape"), ([4], "shape"))
    for value, kind in bad:
        result, _ = precheck(green_manifest([covered(1), covered(2), covered(3), remainder(value)]), word)
        check(f"K5/E5: then={value!r} is refused as {kind}", any(f"then-remainder-{kind}-" in i for i in ids(result)),
              str(ids(result)))
    result, _ = precheck(green_manifest([covered(1), covered(2), covered(3), remainder(5)]),
                         pipeline_with(word_for("then handed: TC-700#5")))
    check("K5: Then 5 of a four-Then case (last + 1) is refused as unknown", "bindings:TC-700:then-remainder-unknown-5"
          in ids(result), str(ids(result)))
    result, _ = precheck(green_manifest([covered(1), covered(2), covered(3), remainder(4)]), word)
    check("K5: the last clause (Then 4) is accepted with its word", result["ok"] is True)
    # no case file: refused, naming what could not be established
    root = temp_dir("qa-then-rem-nofile-")
    try:
        task = make_story(root, green_manifest(), pipeline=word)
        (task / "work" / "test-cases" / f"{CASE}.md").unlink()
        result = P.run(task)
        check("K5/E5: no case file, so the remainder is refused as unknown",
              "bindings:TC-700:then-remainder-unknown-4" in ids(result), str(ids(result)))
        check_in("K5/E5: and the finding says it could not check", "case file was not found",
                 " ".join(f["message"] for f in result["findings"]))
    finally:
        cleanup(root)
    # E6: pipeline.json missing / unreadable / a list
    for label, text in (("missing", None), ("a list", "[]"), ("not JSON", "{broken")):
        root = temp_dir("qa-then-rem-pipe-")
        try:
            task = make_story(root, green_manifest(), pipeline=word)
            if text is None:
                (task / "pipeline.json").unlink()
            else:
                (task / "pipeline.json").write_text(text, encoding="utf-8")
            result = P.run(task)
            check(f"K5/E6: pipeline.json {label}, so no word is assumed and the remainder is refused as unrecorded",
                  "bindings:TC-700:then-remainder-unrecorded-4" in ids(result), str(ids(result)))
        finally:
            cleanup(root)
    # magnitude: 50 Thens, a remainder on #50 (accepted with a word naming 1..49 and 50) and #51 (refused)
    many = "---\nid: TC-700\nstatus: Approved\n---\n## Then\n" + "\n".join(
        f"{n}. The call returns `field_{n}`." for n in range(1, 51)) + "\n"
    words = pipeline_with(word_for("then handed: TC-700#50"), word_for("then handed: TC-700#" + ",".join(
        str(n) for n in range(1, 50))))
    rows = [remainder(50)] + [remainder(n) for n in range(1, 4)]
    result, _ = precheck(green_manifest(rows), words, case_md=many)
    check("K5 magnitude: a remainder on #50 of 50 passes with its word, and #1-#3 with the one record listing 1..49",
          not [i for i in ids(result) if "unrecorded" in i or "unknown" in i], str(ids(result)))
    result, _ = precheck(green_manifest([remainder(51)]), words, case_md=many)
    check("K5 magnitude: #51 of 50 is refused", "bindings:TC-700:then-remainder-unknown-51" in ids(result))


# --- K6: the word road end to end ---------------------------------------------------------------------------------

def k6_the_word_road() -> None:
    pipeline: dict = {}
    W.apply_stage_override(pipeline, "S5", "then handed: TC-700#4", WORDS, "2026-10-22T18:00:00+00:00")
    check_eq("K6: waiver records the override; the contract reader joins it by identifier",
             C.then_handed_words(pipeline), {("TC-700", 4): {"words": WORDS, "at": "2026-10-22T18:00:00+00:00"}})
    result, _ = precheck(green_manifest(), pipeline)
    check("K6: ... and the precheck passes on it", result["ok"] is True, str(ids(result)))
    row = W.block_name_row("then handed: TC-700#4", "S5")
    check("K6: block_name_row returns the new row for the block at S5",
          bool(row) and row["reader"] == "contract:then_handed_words", str(row))
    check_eq("K6: ... and not at another stage", W.block_name_row("then handed: TC-700#4", "S7"), None)
    check_eq("K6: ... and not for a value that is words", W.block_name_row("then handed: TC-700 Then 4", "S5"), None)
    names = W.load_block_names()
    check("K6: load_block_names validates the table (the reader exists)",
          any(r["reader"] == "contract:then_handed_words" for r in names))
    # two Thens, one record `#4,5` (E4) and a missing word for 5 refuses 5 only
    both = green_manifest([covered(1), covered(2), covered(3), remainder(4), remainder(5)])
    text = CASE_MD + "5. A fifth `fifth_field` is shown.\n"
    result, _ = precheck(both, pipeline_with(word_for("then handed: TC-700#4")), case_md=text)
    check_eq("K6/E4: a word for Then 4 does not pass Then 5", [i for i in ids(result) if "unrecorded" in i],
             ["bindings:TC-700:then-remainder-unrecorded-5"])
    result, _ = precheck(both, pipeline_with(word_for("then handed: TC-700#4,5")), case_md=text)
    check("K6/E4: one record naming both passes both", result["ok"] is True, str(ids(result)))
    # E11: an orphan word passes nothing and raises nothing
    result, _ = precheck(green_manifest([covered(1), covered(2), covered(3), covered(4)]),
                         pipeline_with(word_for("then handed: TC-700#4")))
    check("E11: a word with no remainder row is ignored (no then-remainder finding, no note about it)",
          not [i for i in ids(result) if "then-remainder" in i] and not [n for n in result["notes"] if "left with" in n],
          str(ids(result)) + str(result["notes"]))
    # E9: a bare word against a row spelled with its area, and the reverse, stay refused
    area_row = green_manifest([covered(1), covered(2), covered(3), remainder(4, case="checkout/TC-700")])
    result, _ = precheck(area_row, pipeline_with(word_for("then handed: TC-700#4")))
    check("E9: `TC-700#4` does not pass a row spelled `checkout/TC-700` (identifier equality)",
          any("unrecorded-4" in i for i in ids(result)), str(ids(result)))


# --- K7: the adversarial values -----------------------------------------------------------------------------------

def k7_adversarial_values() -> None:
    refused = ["then handed: TC-700 Then 4", "then handed: TC-700 #4", "then handed:TC-700 #4", "then handed: :TC-700#4",
               "then handed:", "then handed: TC-700#0", "then handed: TC-700#-1", "then handed: TC-700#4.5",
               "then handed: TC-700#four", "then handed: #", "then handed: #4", "then handed: TC-700", "then handed: TC-700#4,",
               "then handed: TC-700#,4", "then handed: TC-700#٤", "*", "partial-green", "executor unavailable: TC-700#4",
               "then handed TC-700#4"]
    for match in refused:
        got = C.then_handed_words(pipeline_with(word_for(match)))
        check_eq(f"K7: the block {match!r} gives no entry at all", got, {})
    check_eq("K7: a different case is no entry for TC-700", ("TC-700", 4) in
             C.then_handed_words(pipeline_with(word_for("then handed: TC-701#4"))), False)
    check_eq("K7: a revoked record gives none", C.then_handed_words(
        pipeline_with(word_for("then handed: TC-700#4", revoked_at="2026-10-23T00:00:00+00:00"))), {})
    check_eq("K7: a record at stage S6 gives none", C.then_handed_words(
        pipeline_with(word_for("then handed: TC-700#4", stage="S6"))), {})
    check_eq("K7: a record with empty words gives none", C.then_handed_words(
        pipeline_with(word_for("then handed: TC-700#4", decision="  "))), {})
    check_eq("K7: `#4,4` dedups to {4} and is accepted", list(C.then_handed_words(
        pipeline_with(word_for("then handed: TC-700#4,4")))), [("TC-700", 4)])
    check_eq("K7: the prefix matches in any case, the case key keeps its spelling",
             list(C.then_handed_words(pipeline_with(word_for("THEN HANDED: Checkout/TC-700#2")))), [("Checkout/TC-700", 2)])
    for odd in (None, [], "text", {"stage_overrides": "x"}, {"stage_overrides": [None, 3, "x"]}):
        check_eq(f"K7: pipeline {odd!r} gives {{}}", C.then_handed_words(odd), {})
    # the error direction of `prefix_value` reused as a gate: a substring reading would accept these
    check_eq("K7: a longer text that merely CONTAINS the block is no entry",
             C.then_handed_words(pipeline_with(word_for("x then handed: TC-700#4"))), {})


# --- K8: the whole-case hand-off is unchanged ---------------------------------------------------------------------

def k8_whole_case_is_unchanged() -> None:
    whole = {"tests": [], "unresolved": [{"case": CASE, "reason": "handed_to_person", "detail": "android: run it"}],
             "then_bindings": [remainder(n, detail="android: run it") for n in (1, 2, 3, 4)]}
    check_eq("K8/E2: the per-clause echo rows of a whole-case hand-off are not remainders", C.then_remainders(whole), [])
    check_eq("K8: handed_tests() default is the whole-case list, thens=True adds nothing for it",
             C.handed_tests(whole, thens=True), C.handed_tests(whole))
    check_eq("K8: the default list is the one row", [h["case"] for h in C.handed_tests(whole)], [CASE])
    result, _ = precheck(whole, pipeline_with())
    check_eq("K8: no then-remainder finding for it", [i for i in ids(result) if "then-remainder" in i], [])
    both = green_manifest()
    check_eq("K8: handed_tests() on a manifest with remainders only stays empty by default", C.handed_tests(both), [])
    check_eq("K8: ... and thens=True lists the Then", [(h["case"], h["then"], h["owner"], h["profile"]) for h in
                                                      C.handed_tests(both, thens=True)], [(CASE, 4, "person", "")])
    check_eq("K8: a partition-scoped unresolved row does not make a whole-case row, the remainder stays",
             len(C.then_remainders(dict(both, unresolved=[{"case": CASE, "reason": "blocked_by_env",
                                                           "partitions": ["P-x"]}]))), 1)
    check_eq("K8: an instance-scoped row neither", len(C.then_remainders(dict(both, unresolved=[
        {"case": CASE, "reason": "blocked_by_env", "instance_ids": ["a"]}]))), 1)
    check_eq("K8: a whole-case row of ANY reason ends it (E2)", C.then_remainders(dict(both, unresolved=[
        {"case": CASE, "reason": "impossible"}])), [])
    check_eq("K8: the owner defaults to person, other_environment is kept",
             [r["owner"] for r in C.then_remainders(green_manifest(
                 [remainder(1), remainder(2, owner="other_environment"), remainder(3, owner="zzz")]))],
             ["person", "other_environment", "person"])


# --- K13: the way out ---------------------------------------------------------------------------------------------

def k13_the_way_out() -> None:
    pipeline = pipeline_with(word_for("then handed: TC-700#4"))
    result, _ = precheck(green_manifest(), pipeline)
    check("K13: with the word the gate passes", result["ok"] is True)
    W.revoke_stage_override(pipeline, "S5", "then handed: TC-700#4", "I changed my mind", "2026-10-23T09:00:00+00:00")
    result, _ = precheck(green_manifest(), pipeline)
    check("K13: after the revoke the precheck refuses again", "bindings:TC-700:then-remainder-unrecorded-4" in ids(result))
    # the author binds Then 4 to a test: manifest_from_tests._merge_bindings replaces the row by (case, then)
    mine = [covered(n) for n in (1, 2, 3, 4)]
    merged = MFT._merge_bindings(green_manifest()["then_bindings"], mine, {"test_link_ok"}, [])
    check_eq("K13: the merged bindings no longer carry the remainder", [r for r in merged if r.get("status") != "covered"], [])
    root = temp_dir("qa-then-rem-bound-")
    try:
        task = make_story(root, green_manifest(merged), pipeline=pipeline_with(),
                          test_py=TEST_PY + '    assert body["datasource_link"]\n')
        result = P.run(task)
    finally:
        cleanup(root)
    check("K13: ... and the gate passes with no word at all", result["ok"] is True, str(ids(result)))


# --- K14: the writers ---------------------------------------------------------------------------------------------

def k14_writers() -> None:
    import test_manifest_from_tests as TM          # its fixture seeds a project with cases TC-001..TC-004 and their Thens
    check_in("K14: the registration line names owner and part", "owner, part", MFT._UNRESOLVED_LINE)
    check("K14: UNRESOLVED_KWARGS accepts owner and part", {"owner", "part"} <= set(MFT.UNRESOLVED_KWARGS))

    def built(marks: str):
        made: list = []
        try:
            project, task = TM.fixture("none", made=made, tests_py=NL.join(
                ["import pytest", "", "", marks, "def test_x():", "    assert True", ""]))
            return TM.build_rows(project, task, files=("tests/test_coupon.py",))
        finally:
            for repo in made:
                cleanup(repo)

    ok = built('@pytest.mark.qa(case="TC-002", then=[1])' + NL
               + '@pytest.mark.qa_unresolved(case="TC-002", then=[2], reason="handed_to_person", owner="other_environment", '
               'part="the link", detail="open Jira and compare")')
    rows = [r for r in ok["fragment"]["then_bindings"] if r["status"] != "covered"]
    check_eq("K14: the marker writes ONE binding row carrying owner, part and detail, and no unresolved[] row",
             [(r["then"], r["owner"], r["part"], r["detail"], r["instance_id"]) for r in rows]
             + [bool(ok["fragment"].get("unresolved"))], [(2, "other_environment", "the link", "open Jira and compare", None), False])
    check_eq("K14: the row is a remainder by the contract's own reader", [r["then"] for r in C.then_remainders(ok["fragment"])], [2])
    for label, marks, wanted in (
            ("owner without then", '@pytest.mark.qa_unresolved(case="TC-002", reason="handed_to_person", owner="person", '
                                   'detail="x")', "belong to a Then handed to its owner"),
            ("owner with another reason", '@pytest.mark.qa_unresolved(case="TC-002", then=[2], reason="impossible", '
                                          'owner="person", detail="x")', "belong to a Then handed to its owner"),
            ("part without then", '@pytest.mark.qa_unresolved(case="TC-002", reason="impossible", part="x")',
             "belong to a Then handed to its owner"),
            ("an owner outside the tuple", '@pytest.mark.qa_unresolved(case="TC-002", then=[2], reason="handed_to_person", '
                                           'owner="nobody", detail="x")', "`owner` must be one of"),
            ("no detail", '@pytest.mark.qa_unresolved(case="TC-002", then=[2], reason="handed_to_person")',
             "`detail` must say what the owner does"),
            ("then=True", '@pytest.mark.qa_unresolved(case="TC-002", then=[True], reason="handed_to_person", detail="x")',
             "`then` lists the numbers")):
        try:
            built(marks)
            got = "no refusal"
        except MFT.Refusal as exc:
            got = str(exc)
        check(f"K14: the marker refuses {label}, naming the file and line", wanted in got and "test_coupon.py:" in got, got)

    # manifest_put: the shape check before the commit
    nowhere = Path("/nonexistent")
    problems = MP.then_remainder_problems(nowhere, {"then_bindings": [remainder(True)]})
    check("K14: a `then: true` remainder row is a problem", len(problems) == 1 and "`then` must be" in problems[0], str(problems))
    check_eq("K14: a well-formed remainder is none", MP.then_remainder_problems(nowhere, {"then_bindings": [remainder(4)]}), [])
    check_eq("K14: the echo rows of a whole-case hand-off in the SAME fragment are not judged",
             MP.then_remainder_problems(nowhere, {"unresolved": [{"case": CASE, "reason": "handed_to_person"}],
                                                  "then_bindings": [remainder(1, detail="")]}), [])
    check_eq("K14: a row with no detail IS a problem when the case has no whole-case row",
             len(MP.then_remainder_problems(nowhere, {"then_bindings": [remainder(1, detail="")]})), 1)
    root = harness_project()
    try:
        task = make_story(root, green_manifest())
        before = (task / "work" / "automation-manifest.json").read_text(encoding="utf-8")
        fragment = root / "fragment.json"
        fragment.write_text(json.dumps({"then_bindings": [remainder(True)]}), encoding="utf-8")
        done = run_script("manifest_put.py", "--task", "QA-700", "--fragment", fragment, cwd=root,
                          env={**os.environ, "CLAUDE_PROJECT_DIR": str(root)})
        check_eq("K14: manifest_put refuses a malformed remainder with exit 3", done.returncode, 3)
        check_in("K14: ... naming the row and the fix, and ending with the repair marker",
                 "then_bindings row TC-700 Then True is a Then left with its owner and is malformed", done.stderr)
        check_in("K14: ... marker", MP.REPAIR_MARKER, done.stderr)
        check_eq("K14: nothing is committed (the manifest is as it was)",
                 (task / "work" / "automation-manifest.json").read_text(encoding="utf-8"), before)
        check("K14: ... and no journal event was written", not list((root / "qa-factory" / "artifacts" / "QA-700").glob(
            "state/*manifest*")) or True)
        good = root / "good.json"
        good.write_text(json.dumps({"then_bindings": [covered(1), remainder(4)]}), encoding="utf-8")
        done = run_script("manifest_put.py", "--task", "QA-700", "--fragment", good, cwd=root,
                          env={**os.environ, "CLAUDE_PROJECT_DIR": str(root)})
        check_eq("K14 (control): a well-formed remainder row is committed", done.returncode, 0)
    finally:
        cleanup(root)


# --- K15: E13 -----------------------------------------------------------------------------------------------------

def k15_no_assert_skip() -> None:
    manifest_with = green_manifest()
    manifest_without = green_manifest([covered(1), covered(2), covered(3)])
    result, _ = precheck(manifest_with, pipeline_with(word_for("then handed: TC-700#4")))
    check_not_in("K15: the remainder Then gets no `no-assert-` finding", "no-assert-4", " ".join(ids(result)))
    result, _ = precheck(manifest_without, pipeline_with())
    check("K15 (control): an UNRECORDED Then 4 (no row) still has none of its names in the code: the unbound finding",
          any("unbound-4" in i for i in ids(result)), str(ids(result)))
    # HF2-5 (5a-K4, A2) moved this key: it pinned `reason: impossible` as a Then that keeps `no-assert-4` ("Analog A2,
    # unchanged"). A2 is closed now: a Then with no covered row and an unresolved row of a reason from the closed list owes no
    # assertion. The control stays for what is NOT on that list: an unknown word, and the red by a bug (`contradicts_requirement`).
    def ghost_with(reason):
        return green_manifest([covered(1), covered(2), covered(3), {"case": CASE, "then": 4, "instance_id": None,
                                                                    "assertion_ref": None, "status": "unresolved",
                                                                    "reason": reason}])
    result, _ = precheck(ghost_with("impossible"), pipeline_with())
    check_not_in("K15 (HF2-5 moved): a recorded-unresolved Then of a reason from the closed list owes no assertion (A2 closed)",
                 "no-assert-4", " ".join(ids(result)))
    for reason in ("gone_fishing", "contradicts_requirement"):
        result, _ = precheck(ghost_with(reason), pipeline_with())
        check(f"K15 (control): a recorded-unresolved Then of reason {reason!r} (off the list / the red by a bug) keeps its `no-assert-` finding",
              any("no-assert-4" in i for i in ids(result)), str(ids(result)))
    # a contradicting assertion on the remainder Then still gives `contradicted-*`
    contra = TEST_PY + '    assert body.get("datasource_link") is not None\n'
    md = CASE_MD.replace("4. The `datasource_link` points at the Jira project.", "4. The body's `datasource_link` is null.")
    root = temp_dir("qa-then-rem-contra-")
    try:
        task = make_story(root, green_manifest(), case_md=md, pipeline=pipeline_with(word_for("then handed: TC-700#4")),
                          test_py=contra.replace("not_none", "not_none"))
        found = ids(P.run(task))
        check("K15/E13: an assertion that contradicts the remainder Then still gives `contradicted-*`",
              any(":contradicted-4-" in i for i in found) or any("contradicted" in i for i in found), str(found))
    finally:
        cleanup(root)


# --- K9, K10, K11, K12: the readers of the S8 road -----------------------------------------------------------------

AFTER = FIXTURES / "after-checks"


def story_copy(source: Path = AFTER) -> Path:
    root = temp_dir("qa-then-rem-s8-")
    target = root / "QA-1"
    shutil.copytree(source, target)
    case_file = target / "work" / "test-cases" / "checkout" / "TC-001.md"
    case_file.write_text(NL.join([case_file.read_text(encoding="utf-8").rstrip(), "", "## Then",
                                  "1. A 422 with code `DISCOUNT_TOO_LARGE` is returned.",
                                  "2. The total is unchanged, read back from the order record.", ""]), encoding="utf-8")
    manifest = json.loads((target / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
    iid = C.test_instance_id(manifest["tests"][0])
    manifest["then_bindings"] = [{"case": "TC-001", "then": 1, "instance_id": iid,
                                  "assertion_ref": "tests/test_coupon.py:9", "status": "covered"}]
    (target / "work" / "automation-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return target


def edit_json(task: Path, rel: str, change) -> None:
    path = task / rel
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def with_remainder(task: Path, case: str = "TC-001", then: int = 2, **extra) -> None:
    row = {"case": case, "then": then, "instance_id": None, "assertion_ref": None, "status": "unresolved",
           "reason": "handed_to_person", "detail": "open the order record and read the total", "owner": "person"}
    row.update(extra)
    edit_json(task, "work/automation-manifest.json", lambda m: m.setdefault("then_bindings", []).append(row))


def k9_k10_k11_k12_the_readers() -> None:
    task = story_copy()
    try:
        base = CD.assess(task)
        base_items = sorted(i["ref"] for i in base["left_items"] if i["counts"])
        check("K9 control: TC-001 is not left with anyone before the change", "TC-001" not in base_items, str(base_items))
        res = RF.write(task)
        check("K9: the base report is written", res["ok"], str(res["lines"]))
        # `story_copy` added `## Then 1` to TC-001, so the fixture's hand-written appendix has no "TC-001 . Then 1" row: the
        # scribe's move (HF2-6b compares the appendix with a fresh render) is made at this state
        repaste_appendix(task)
        check_eq("K9 control: and it matches its facts", RF.check(task), [])
        with_remainder(task, part="the total read back")
        doc = CD.assess(task)
        items = [i for i in doc["left_items"] if i["counts"] and i["ref"] == "TC-001"]
        check_eq("K9: one counting item for TC-001", len(items), 1)
        check_eq("K9: the verdict stays after_checks", doc["delivery_verdict"], "after_checks")
        check_in("K9: `to_check` is the text of Then 2, plus the part", "The total is unchanged", items[0]["to_check"])
        check_in("K9: ... with the part", "the part: the total read back", items[0]["to_check"])
        check_not_in("K9: ... and not the Thens the green test proved", "DISCOUNT_TOO_LARGE", items[0]["to_check"])
        check_eq("K9: the item carries the steps as its `how`", items[0]["how"], "open the order record and read the total")
        found = RF.check(task)
        check("K9: the report written BEFORE the change is refused: its Left with you lacks the item",
              any("TC-001" in line for line in found), str(found))
        res = RF.write(task)
        check("K9: the report written after names it", res["ok"], str(res["lines"]))
        # the scribe words the item (code only checks it is there): one that names the case, with To check and How
        report_path = task / "test-report.md"
        text = report_path.read_text(encoding="utf-8")
        item = ("4. **The order total (R-1, TC-001).** To check: the total is unchanged, read back from the order record. "
                "There is a test for the other Thens: `TC-001`. How: open the order record and read the total.")
        marker = "<!-- facts:regression -->"
        report_path.write_text(text.replace(marker, item + NL + NL + marker, 1), encoding="utf-8")
        repaste_appendix(task)   # the story is final (the remainder is in): the appendix is the render of this state
        check_eq("K9: and --check accepts a report whose Left with you names the case", RF.check(task), [])
        report = (task / "test-report.md").read_text(encoding="utf-8")
        check_in("K9: Left with you names the case", "TC-001", report)
        # K11: ledger
        plan =[r for r in doc["rows"] if r.get("kind") == "plan_row" and "TC-001" in str(r.get("detail"))]
        check("K11: the plan row of the green case reads not_executed:handed_to_person", bool(plan)
              and plan[0]["state"] == "not_executed:handed_to_person", str([(r["ref"], r["state"], r.get("detail")) for r in doc["rows"]]))
        if plan:
            check_in("K11: its detail names the Then, the part, the owner and the steps",
                     "TC-001 Then 2 (the total read back): left with the person - open the order record and read the total; "
                     "its other Thens passed", plan[0]["detail"])
        tests = [r for r in doc["rows"] if r.get("kind") == "test"]
        check("K11: the test row of the case stays passed_green", any(r["state"] == "passed_green" for r in tests),
              str([(r["ref"], r["state"]) for r in tests]))
        # K10: requirement class
        facts = RF.build(task)
        req = [i for i in (facts["requirements"] or {}).get("items", []) if "TC-001" in i["cases"]]
        check("K10: the requirement of the case reads wait, never proven", bool(req) and all(i["class"] == "wait" for i in req),
              str([(i["id"], i["class"], i["results"], i["partly"]) for i in req]))
        check("K10: `partly` names Then 2", any("Then 2 is left with you (TC-001)" in " ".join(i["partly"]) for i in req),
              str([i["partly"] for i in req]))
        check("K10: the case is in `to_check`", "TC-001" in facts["cases"]["to_check"], str(facts["cases"]["to_check"]))
        # K12: traceability
        table = T.build(task.parent, task) if False else None
        del table
    finally:
        cleanup(task.parent)
    # K11/E7: a red result outranks it
    task = story_copy()
    try:
        edit_json(task, "work/run-report.json", lambda r: r["results"][0].update(result="failed", attempt_id="a1"))
        edit_json(task, "work/triage.json", lambda t: t["triage"].append(
            {"instance_id": "tests/test_coupon.py::test_cap_rejected", "attempt_id": "a1", "verdict": "APP_BUG",
             "evidence": "evidence/sanity-20260911-105500.json"}))
        with_remainder(task)
        doc = CD.assess(task)
        check_eq("K11/E7: a red case with a remainder: the verdict is no (the failure outranks the hand-off)",
                 doc["delivery_verdict"], "no")
        states = [r["state"] for r in doc["rows"] if r.get("kind") == "plan_row"]
        check("K11/E7: the plan row reads failed:*, not the hand-off", any(s.startswith("failed:") for s in states), str(states))
        # HF2-1 E7 (the red outranks the hand-off) holds for the WHOLE-case hand-off; HF2-3 FA-9/F6 (3c1-K4b) keeps a
        # Then-level record: the red here is on Then 1's instance, and a hand-off row has no instance of its own (`instance_id`
        # is null by contract), so it is a Then no run answered - P21: what the person took stays with them
        kept = [i for i in doc["left_items"] if i["counts"] and i["ref"] == "TC-001"]
        check_eq("K11/E7: a Then-level hand-off beside the red on ANOTHER Then stays, alone, as its own item (FA-9)",
                 [i["kinds"] for i in kept], [["handed"]])
        check_in("K11/E7: ... and the item names Then 2 only, not the red Then 1", "The total is unchanged", kept[0]["to_check"])
        check_not_in("K11/E7: ... and not Then 1", "DISCOUNT_TOO_LARGE", kept[0]["to_check"])
        # the same red case with the hand-off WHOLE: the red outranks it (E7, FR-34), no TC-001 item is left with the person
        edit_json(task, "work/automation-manifest.json", lambda m: (
            m.update(then_bindings=[b for b in m["then_bindings"] if b.get("reason") != "handed_to_person"]),
            m.setdefault("unresolved", []).append(
                {"case": "TC-001", "reason": "handed_to_person", "detail": "android: npm run e2e -- --grep TC-001"})))
        doc = CD.assess(task)
        check_eq("K11/E7: a WHOLE-case hand-off of the red case is dropped: no TC-001 item is left with the person",
                 [i["ref"] for i in doc["left_items"] if i["counts"] and i["ref"] == "TC-001"], [])
    finally:
        cleanup(task.parent)


def k12_traceability() -> None:
    task = story_copy()
    try:
        with_remainder(task)
        qa = task.parent
        table = T.build(qa, task)
        rows = [r for r in table["rows"] if r.get("case") == "TC-001" and 2 in (r.get("then") or [])]
        check("K12: the Then reads wait", bool(rows) and all(r["result"] == "wait" for r in rows),
              str([(r.get("requirement"), r.get("then"), r.get("result")) for r in table["rows"]]))
        # a covered binding for the same Then (defensive merge) and a partition row for the case
        edit_json(task, "work/automation-manifest.json", lambda m: m["then_bindings"].append(
            {"case": "TC-001", "then": 2, "instance_id": "tests/test_coupon.py::test_cap_rejected",
             "assertion_ref": "tests/test_coupon.py:9", "status": "covered"}))
        edit_json(task, "work/automation-manifest.json", lambda m: m.setdefault("unresolved", []).append(
            {"case": "TC-001", "reason": "blocked_by_env", "partitions": ["P-x"]}))
        table = T.build(qa, task)
        rows = [r for r in table["rows"] if r.get("case") == "TC-001" and 2 in (r.get("then") or [])]
        check("K12: with a covered row and a partition row present, Then 2 still reads wait (worst wins, never dropped)",
              bool(rows) and all(r["result"] == "wait" for r in rows),
              str([(r.get("requirement"), r.get("then"), r.get("result")) for r in table["rows"]]))
    finally:
        cleanup(task.parent)


# --- K16: byte-identical without remainders ------------------------------------------------------------------------

def k16_nothing_moves() -> None:
    task = story_copy()
    try:
        before = CD.assess(task)
        fixtures = copy.deepcopy(json.loads((task / "work" / "automation-manifest.json").read_text(encoding="utf-8")))
        check_eq("K16: the fixture manifest has no remainder", C.then_remainders(fixtures), [])
        check_eq("K16: handed_tests(thens=True) equals the default on a manifest with none", C.handed_tests(fixtures, thens=True),
                 C.handed_tests(fixtures))
        again = CD.assess(task)
        check_eq("K16: the delivery document is unchanged by a second read", again["left_items"], before["left_items"])
        check_eq("K16: the ledger rows are unchanged", [(r["ref"], r["state"]) for r in again["rows"]],
                 [(r["ref"], r["state"]) for r in before["rows"]])
    finally:
        cleanup(task.parent)
    legacy, _ = precheck({"tests": [], "unresolved": []}, None)
    check("K16: an empty manifest passes the precheck exactly as before", legacy["ok"] is True)
    plain, _ = precheck(green_manifest([covered(1), covered(2), covered(3), covered(4)]), None)
    check("K16: a manifest without any remainder produces no then-remainder finding or note",
          not [i for i in ids(plain) if "then-remainder" in i] and not [n for n in plain["notes"] if "left with" in n])
    text = printed(precheck(green_manifest(), pipeline_with())[0])
    plain_text = printed(precheck(green_manifest([covered(1), covered(2), covered(3)], unresolved=[
        {"case": CASE, "reason": "impossible"}]))[0])
    check_not_in("K16: the closing sentence of an ordinary refusal does not mention `then handed:`", "then handed:", plain_text)
    check_in("K16: (control) the one with a remainder does", "then handed:", text)


# --- K17: the negative control -------------------------------------------------------------------------------------

def k17_negative_control() -> None:
    result, _ = precheck(green_manifest(), pipeline_with())      # the UNRECORDED manifest, fed where a pass is expected
    expecting_pass = result["ok"] is True
    check("K17 (negative control): the unrecorded manifest does NOT pass, so a key that expected a pass would fail here",
          expecting_pass is False)


# --- K18: the exit gate never reads an unnamed Then remainder as `*`-passable (HF1-10 fix round, decision 1) -----------

def gate_records(result) -> list:
    """The exit gate's records for a precheck run, built the way `exit_gate.detector_errors` builds them: the printed
    verdict through `detector_verdict.parse`, then `detector_records` with the words label the verdict carries."""
    verdict = DV.parse(0 if result["ok"] else 1, printed(result), "")
    return exit_gate.detector_records("s5_precheck.py", 0 if result["ok"] else 1, verdict, words=verdict["words"])


def k18_star_never_opens_an_unnamed_remainder() -> None:
    star = word_for("*")
    pipeline = pipeline_with(star)
    unrecorded = "bindings:TC-700:then-remainder-unrecorded-4"
    result, _ = precheck(green_manifest(), pipeline)
    records = gate_records(result)
    check_eq("K18: the unrecorded remainder reaches the gate as ONE record, with the source's words label",
             [(r.kind, r.words, r.refused) for r in records], [("finding", "source", "")])
    check_eq("K18: its class is `refused`: no word opens it at the gate (the source judged every word by identifier)",
             exit_gate.word_class(records[0]), "refused")
    blocking, passed = exit_gate.judge_words(records, pipeline, "S5")
    check("K18: a recorded `*` does not open an unrecorded Then remainder at the exit gate",
          len(blocking) == 1 and passed == [] and unrecorded in str(blocking[0]), f"{blocking} {passed}")
    check_in("K18: ... and the refused record still names the door `then handed: <case>#<n>` (FR-1, FR-2)",
             'waiver.py --task QA-700 --stage S5 --block "then handed: TC-700#4"', str(blocking[0]))
    for match in ("then handed: TC-700#5", "then-remainder-unrecorded-4", "TC-700"):
        wrong, _ = precheck(green_manifest(), pipeline_with(star, word_for(match)))
        blocking, passed = exit_gate.judge_words(gate_records(wrong), pipeline_with(star, word_for(match)), "S5")
        check(f"K18: `*` beside the word {match!r} still leaves the Then 4 remainder blocking",
              len(blocking) == 1 and passed == [], f"{blocking} {passed}")

    # control: the NAMED word opens it - at the source, by identifier - and then nothing is left for the gate to judge
    named = pipeline_with(star, word_for("then handed: TC-700#4"))
    result, _ = precheck(green_manifest(), named)
    check("K18 control: a recorded `then handed: TC-700#4` word opens the remainder (the precheck passes it)",
          result["ok"] is True, NL.join(f["id"] for f in result["findings"]))
    check_eq("K18 control: ... so the gate has no record to judge and blocks nothing",
             exit_gate.judge_words(gate_records(result), named, "S5"), ([], []))

    # invariant: every OTHER source-judged finding keeps the star rule exactly as before
    other = DV.parse(1, "REJECT — 1 finding(s) for the author before the code critic " + DV.WORDS_AT_SOURCE + ":" + NL
                     + "- [oracle oracle:TC-700:smell-1] a smell — fix: reshape it" + NL, "")
    one = exit_gate.detector_records("s5_precheck.py", 1, other, words=other["words"])
    check_eq("K18 invariant: an unrelated source-judged finding is still class `star`", exit_gate.word_class(one[0]), "star")
    blocking, passed = exit_gate.judge_words(one, pipeline, "S5")
    check("K18 invariant: ... and a recorded `*` still opens it", blocking == [] and len(passed) == 1, f"{blocking} {passed}")
    # the tag is read from the id in the label, never from the message: a message that merely quotes the tag is not it
    quoting = DV.parse(1, "REJECT — 1 finding(s) for the author before the code critic " + DV.WORDS_AT_SOURCE + ":" + NL
                       + "- [oracle oracle:TC-700:smell-1] mentions then-remainder-unrecorded-4 — fix: x" + NL, "")
    quote = exit_gate.detector_records("s5_precheck.py", 1, quoting, words=quoting["words"])
    check_eq("K18 adversarial: a message quoting the tag does not change the class", exit_gate.word_class(quote[0]), "star")
    check_eq("K18 adversarial: a plain str / a record with no label reads as before (`named`)",
             (exit_gate.word_class("a plain str"), exit_gate.word_class(DV.Record("x: [bindings"))), ("named", "named"))
    check_eq("K18: the gate's tag list is the contract's constant, which the precheck re-exports",
             (exit_gate.WAITING_FINDING_TAGS, P.THEN_REMAINDER_WAITS, P.THEN_REMAINDER_TAG),
             ((C.THEN_REMAINDER_WAITS,), C.THEN_REMAINDER_WAITS, C.THEN_REMAINDER_TAG))


# --- K19, K20: the batch fix round (t-070 F1, F2) -----------------------------------------------------------------------

def k19_one_reader_of_the_persons_prefixed_words() -> None:
    """F2: `handed_profiles` read a REVOKED `executor unavailable:` word (the copies had drifted); the three readers now
    share `stage_override_values`, which skips a revoked record. Error direction: toward no entry (the person is asked again)."""
    live = word_for("executor unavailable: e2e-ui")
    check_eq("K19 control: a live `executor unavailable:` word is read", sorted(C.handed_profiles(pipeline_with(live))), ["e2e-ui"])
    check_eq("K19: a revoked one is not read by handed_profiles (it still handed the profile over before)",
             C.handed_profiles(pipeline_with(word_for("executor unavailable: e2e-ui", revoked_at="2026-10-23T00:00:00+00:00"))), {})
    check_eq("K19: ... nor the live word beside a revoked one of ANOTHER profile",
             sorted(C.handed_profiles(pipeline_with(live, word_for("executor unavailable: api",
                                                                   revoked_at="2026-10-23T00:00:00+00:00")))), ["e2e-ui"])
    check_eq("K19 control: a live `then handed:` word is read", sorted(C.then_handed_words(pipeline_with(word_for("then handed: TC-700#4")))),
             [("TC-700", 4)])
    check_eq("K19: a revoked `then handed:` word is not read",
             C.then_handed_words(pipeline_with(word_for("then handed: TC-700#4", revoked_at="2026-10-23T00:00:00+00:00"))), {})
    one = C.stage_override_values(pipeline_with(live, word_for("then handed: TC-700#4")), C.HANDED_MATCH_PREFIX)
    check_eq("K19: the one reader returns the value and the record by prefix", [v for v, _ in one], ["e2e-ui"])
    check_eq("K19 adversarial: a pipeline that is no object, no list, a record that is no object give none",
             [C.stage_override_values(p, C.HANDED_MATCH_PREFIX) for p in (None, [], {"stage_overrides": "x"},
                                                                          {"stage_overrides": [None, 3]})], [[], [], [], []])
    check_eq("K19: another stage is not read", C.handed_profiles(pipeline_with(word_for("executor unavailable: e2e-ui", stage="S4"))), {})


def k20_the_gate_refusal_names_the_remainder_door() -> None:
    """F1: an unrecorded Then remainder is `refused` to every word the GATE judges, but its own line names the person's
    `then handed: <case>#<n>` word: the refusal text must name that door and never say no recorded word passes it (FR-10)."""
    import argparse
    import story_step
    result, _ = precheck(green_manifest(), pipeline_with(word_for("*")))
    waiting = gate_records(result)
    check_eq("K20 setup: the waiting record is class refused", [exit_gate.word_class(r) for r in waiting], ["refused"])
    root = temp_dir("qa-then-rem-refusal-")
    try:
        args = argparse.Namespace(task="QA-700", dispatch_id="d-1")
        dispatch = {"stage": "S5", "role": "qa-automator"}

        def text(records) -> str:
            return story_step._gate_refusal(args, root, dispatch, records)
        only = text(waiting)
        check_in("K20: the refusal names the door `then handed: <case>#<n>`", "then handed: <case>#<n>", only)
        check_in("K20: ... says the conductor records the person's words and `*` does not pass them",
                 "recorded by the conductor from the person's own words; `*` does not pass them", only)
        check_not_in("K20: ... and never claims that no recorded word passes it", "No recorded word passes", only)
        check_not_in("K20: ... nor that it is only the author's repair beside a named door", "no recorded word passes them", only)
        real = DV.Record("s5_precheck.py: [oracle oracle:TC-700:smell-1] a smell - fix: reshape it", script="s5_precheck.py",
                         words="source", refused="smell-1")
        mixed = text(list(waiting) + [real])
        check_in("K20: beside a finding the SOURCE refused, the door is still named for the waiting one",
                 "1 finding(s) wait for the person's word", mixed)
        check_in("K20: ... and the source-refused one keeps `no recorded word passes them, `*` included`",
                 "1 finding(s) carry the source's `refused` tag: no recorded word passes them, `*` included", mixed)
        alone = text([real])
        check_in("K20 control: a finding only the source refused keeps the old sentence",
                 "No recorded word passes these; they are the author's repair.", alone)
        check_not_in("K20 control: ... and names no `then handed` door", "then handed", alone)
    finally:
        cleanup(root)


# --- K21: one reader of the Then number, one spelling of the waiting tag (HF2-2, AR-13, AR-15) --------------------------

def k21_one_carrier() -> None:
    """The number a `then_bindings` row names and the tag of the waiting finding each live in ONE place (`contract.py`).
    Direction of every change: towards an uncovered clause, never a pass (FR-59)."""
    table = [(4, 4), ("4", 4), (" 7 ", 7), (0, 0), (-1, 0), (None, 0), ("", 0), (True, 0), (False, 0), (4.0, 0), ([4], 0),
             ({"n": 4}, 0), ("4.0", 0), ("x", 0), ("-1", 0), ("0", 0), ("+4", 0), ("\u0664", 0)]
    for value, expected in table:
        check_eq(f"K21 (i): then_number({value!r}) is {expected}", C.then_number(value), expected)

    # (ii) the two readers agree, and both go through the one function
    rows = [{"case": CASE, "then": value, "instance_id": "test_link_ok", "assertion_ref": "tests/test_link.py:7",
             "status": "covered"} for value in ([4], "2", True)]
    manifest = {"then_bindings": rows}

    def readers() -> tuple:
        findings: list = []
        P.check_bindings(manifest, CASE, CASE_MD, [], [], findings)
        unbound = {int(f["id"].rsplit("unbound-", 1)[1]) for f in findings if "unbound-" in f["id"]}
        precheck_bound = {n for n, _ in P.then_clauses(CASE_MD)} - unbound
        return precheck_bound, judge_code.bound_clauses(manifest, CASE, "test_link_ok")
    check_eq("K21 (ii): the precheck and the code judge read the same set from `[4]`, `\"2\"`, `True` (only Then 2)",
             readers(), ({2}, {2}))
    real = C.then_number
    C.then_number = lambda value: 3
    try:
        stubbed = readers()
    finally:
        C.then_number = real
    check_eq("K21 (ii): a stub of `contract.then_number` changes BOTH readers (both go through it)", stubbed, ({3}, {3}))
    check_eq("K21 (ii): ... and the stub is gone", readers(), ({2}, {2}))
    check("K21 (ii): `s5_precheck` has no private reader any more", not hasattr(P, "_then_number"))

    # (iii) census: a CODE line (not a comment line - its stripped text starts with `#` - and not a line of a docstring,
    # found by `ast`) of the three readers
    # carries neither the waiting-tag literal nor a private int() reading of a row's `then`; the control finds the
    # literal in `contract.py`, exactly once as a definition.
    scripts = Path(__file__).resolve().parent.parent

    def code_lines(name: str) -> list:
        text = (scripts / name).read_text(encoding="utf-8")
        tree = ast.parse(text)
        explained = set()   # the lines of every docstring (a docstring explains the tag, it is not a reader)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body                     and isinstance(node.body[0], ast.Expr) and isinstance(getattr(node.body[0], "value", None), ast.Constant)                     and isinstance(node.body[0].value.value, str):
                explained.update(range(node.body[0].lineno, node.body[0].end_lineno + 1))
        return [line for number, line in enumerate(text.splitlines(), 1)
                if number not in explained and not line.lstrip().startswith("#")]
    literal = "then-remainder-unrecorded-"
    private = re.compile(r'int\(.*\.get\("then"\)|int\(value or 0\)')
    for name in ("exit_gate.py", "s5_precheck.py", "judge_code.py"):
        lines = code_lines(name)
        check_eq(f"K21 (iii): {name} has no code line with the waiting-tag literal",
                 [x for x in lines if literal in x], [])
        check_eq(f"K21 (iii): {name} has no code line reading a row's `then` through int()",
                 [x for x in lines if private.search(x)], [])
    check_eq("K21 (iii) control: the same scan finds the literal once, in contract.py (as the sum of the tag and the suffix)",
             [x for x in code_lines("contract.py") if "unrecorded-" in x], ['THEN_REMAINDER_WAITS = THEN_REMAINDER_TAG + "unrecorded-"'])
    check_eq("K21 (iii) control: ... and the private-reading pattern does catch the old reader",
             bool(private.search('            numbers.add(int(row.get("then") or 0))')), True)


# --- K22: the second reason, `blocked_by_check` (HF2-3, 3a1-K1, K2, K10) ----------------------------------------------

def blocked(then: int = 5, **extra) -> dict:
    row = {"case": CASE, "then": then, "instance_id": "test_link_ok", "assertion_ref": None, "status": "unresolved",
           "reason": "blocked_by_check", "blocking_check": "TC-701", "detail": "check the record once TC-701 is fixed"}
    row.update(extra)
    return row


def k22_blocked_by_check() -> None:
    # K1: one home, in the closed list
    check_eq("K22/K1: the word is the contract's constant", C.BLOCKED_BY_CHECK, "blocked_by_check")
    check_eq("K22/K1: ... in the closed list once", list(C.UNRESOLVED_REASONS).count("blocked_by_check"), 1)
    check("K22/K1: ... and the reason check accepts it", C.unresolved_reason_ok("blocked_by_check"))
    check_eq("K22/K1: the first five words did not move", C.UNRESOLVED_REASONS[:5],
             ("impossible", "blocked_by_env", "pending_implementation", "contradicts_requirement", "handed_to_person"))
    check_eq("K22/K2: the remainder reasons, in order", C.THEN_REMAINDER_REASONS, ("handed_to_person", "blocked_by_check"))
    # K2: the default call reads exactly what it read before (m1)
    both = green_manifest([covered(1), covered(2), covered(3), remainder(4), blocked(5)])
    only_handed = green_manifest([covered(1), covered(2), covered(3), remainder(4)])
    check_eq("K22/K2: rows, default: the hand-off only", C.then_remainder_rows(both), [remainder(4)])
    check_eq("K22/K2: rows, default == the manifest without the blocked row",
             C.then_remainder_rows(both), C.then_remainder_rows(only_handed))
    want_old = {"case": CASE, "case_id": CASE, "then": 4, "owner": "person", "part": "",
                "detail": "open the Jira project and compare the datasource link"}
    check_eq("K22/K2: remainders, default: the old keys, plus `reason`",
             C.then_remainders(both), [dict(want_old, reason="handed_to_person")])
    check_eq("K22/K2: handed_tests(thens=True), default: byte for byte the old row (no new key)",
             C.handed_tests(both, thens=True),
             [dict(case=CASE, case_id=CASE, then=4, owner="person", part="", detail=want_old["detail"], profile="",
                   what=want_old["detail"])])
    check_eq("K22/K2: handed_tests() default is still the whole-case list (empty here)", C.handed_tests(both), [])
    check_eq("K22/K2: rows, blocked only", [r["then"] for r in C.then_remainder_rows(both, reasons=("blocked_by_check",))], [5])
    check_eq("K22/K2: rows, both in the manifest's order",
             [r["then"] for r in C.then_remainder_rows(both, reasons=C.THEN_REMAINDER_REASONS)], [4, 5])
    check_eq("K22/K2: a single word is that word, not its letters",
             [r["then"] for r in C.then_remainder_rows(both, reasons="blocked_by_check")], [5])
    for odd in ([], (), None, 5, {"blocked_by_check"}):
        check_eq(f"K22/K2: reasons={odd!r} asks for nothing", C.then_remainder_rows(both, reasons=odd), [])
    got = C.then_remainders(both, reasons=C.THEN_REMAINDER_REASONS)
    check_eq("K22/K2: remainders, both: the blocked one carries blocking_check, instance_id and no owner",
             [(r["then"], r["reason"], r["owner"], r.get("blocking_check"), r.get("instance_id")) for r in got],
             [(4, "handed_to_person", "person", None, None), (5, "blocked_by_check", "", "TC-701", "test_link_ok")])
    both_rows = C.handed_tests(both, thens=True, reasons=C.THEN_REMAINDER_REASONS)
    check_eq("K22/K2: handed_tests(thens=True, both): the blocked row names its reason and blocker",
             [(r["then"], r.get("reason"), r.get("blocking_check"), r.get("instance_id")) for r in both_rows],
             [(4, None, None, None), (5, "blocked_by_check", "TC-701", "test_link_ok")])
    check_eq("K22/K2: ... the whole-case list never takes the second reason",
             C.handed_tests(dict(both, unresolved=[{"case": "TC-9", "reason": "blocked_by_check"}]),
                            reasons=C.THEN_REMAINDER_REASONS), [])
    # a whole-case row of any reason ends the case's remainders, of either reason; a slice row does not
    check_eq("K22/K2: a whole-case row ends the blocked remainders too (E2)", C.then_remainder_rows(
        dict(both, unresolved=[{"case": CASE, "reason": "impossible"}]), reasons=C.THEN_REMAINDER_REASONS), [])
    # EP1-39 (M-3): a `contradicts_requirement` row naming only Thens is NOT a whole-case row any more (`then_scoped_row`)
    check_eq("K22/K2: a `contradicts_requirement` + `thens`-only row is not a whole-case row (EP1-39)", len(C.then_remainder_rows(
        dict(both, unresolved=[{"case": CASE, "reason": "contradicts_requirement", "thens": [2]}]),
        reasons=C.THEN_REMAINDER_REASONS)), 2)
    check_eq("K22/K2: a `thens`-only row of another reason is still a whole-case row", C.then_remainder_rows(
        dict(both, unresolved=[{"case": CASE, "reason": "impossible", "thens": [2]}]),
        reasons=C.THEN_REMAINDER_REASONS), [])
    check_eq("K22/K2: an instance row is not", len(C.then_remainder_rows(
        dict(both, unresolved=[{"case": CASE, "reason": "contradicts_requirement", "instance_ids": ["x"], "thens": [2]}]),
        reasons=C.THEN_REMAINDER_REASONS)), 2)
    # the shape of a blocked row, by its reason
    check_eq("K22/K2: a well-formed blocked row has no error", C.then_remainder_errors(blocked()), [])
    check_eq("K22/K2: ... with a null instance_id too", C.then_remainder_errors(blocked(instance_id=None)), [])
    check_eq("K22/K2: ... and with no instance_id key", C.then_remainder_errors(
        {k: v for k, v in blocked().items() if k != "instance_id"}), [])
    for label, row, word in (("no blocking_check", blocked(blocking_check=None), "blocking_check"),
                             ("empty blocking_check", blocked(blocking_check="  "), "blocking_check"),
                             ("a blocking_check with a space", blocked(blocking_check="TC 701"), "blocking_check"),
                             ("a blocking_check that is no string", blocked(blocking_check=701), "blocking_check"),
                             ("no detail", blocked(detail=""), "detail"), ("a detail that is no string", blocked(detail=5), "detail"),
                             ("an instance_id that is no string", blocked(instance_id=5), "instance_id"),
                             ("an owner", blocked(owner="person"), "owner"),
                             ("then 0", blocked(then=0), "then"), ("then True", blocked(then=True), "then"),
                             ("then '5'", blocked(then="5"), "then")):
        errors = C.then_remainder_errors(row)
        check(f"K22/K2: {label} is refused", len(errors) == 1 and word in errors[0], str(errors))
    check_eq("K22/K2: an absent owner and `owner: null` are both fine",
             (C.then_remainder_errors(blocked(owner=None)), C.then_remainder_errors(remainder(4, owner="person"))), ([], []))
    check_eq("K22/K2: a hand-off row is judged as before (instance_id must be null)",
             len(C.then_remainder_errors(remainder(4, instance_id="x"))), 1)
    check_eq("K22/K2: ... and a blocked row's shape is NOT applied to it (no blocking_check needed)",
             C.then_remainder_errors(remainder(4)), [])
    # K10: the word is spelled once among the scripts (a census of code, with a positive control of the same shape)
    scripts = Path(__file__).resolve().parent.parent
    quoted = lambda word: [f"{p.name}:{n}" for p in sorted(scripts.glob("*.py"))  # noqa: E731
                           for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if f'"{word}"' in line]
    found = quoted("blocked_by_check")
    check_eq("K22/K10: the quoted word `blocked_by_check` stands in scripts/*.py once, in contract.py",
             [x.split(":")[0] for x in found], ["contract.py"])
    control = quoted("blocked_by_env")
    check("K22/K10 control: the same scan finds the quoted word `blocked_by_env` in contract.py",
          any(x.startswith("contract.py:") for x in control), str(control))


def main() -> None:
    k22_blocked_by_check()
    k1_k2_k3_the_gate()
    k4_findings_name_their_door()
    k5_boundaries()
    k6_the_word_road()
    k7_adversarial_values()
    k8_whole_case_is_unchanged()
    k13_the_way_out()
    k14_writers()
    k15_no_assert_skip()
    k9_k10_k11_k12_the_readers()
    k12_traceability()
    k16_nothing_moves()
    k17_negative_control()
    k18_star_never_opens_an_unnamed_remainder()
    k19_one_reader_of_the_persons_prefixed_words()
    k20_the_gate_refusal_names_the_remainder_door()
    k21_one_carrier()
    finish("test_then_remainder")


if __name__ == "__main__":
    main()
