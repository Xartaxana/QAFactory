#!/usr/bin/env python3
"""HF1-14 (EP1-10, third part): a probe that could not run, accepted by the person, closes the S5 window as a named gap.

TP1-12586 (22.10.2026): three UI probes came back `not_executed` (the wrong profile ran them), the person's word to go
on without receipts was recorded, and the S5 window stalled: "probe is missing for a new_or_changed instance" is a SHAPE
error that tier 2 of `controller._s5_completion_problems` refuses without reading any word, and `validate_window` wants
`approved`. The unit the fix adds is a `probe_gap` block on the window item, written by `window_record.build` ONLY when a
recorded word `probe gap: <case key>` names the instance (`contract.probe_gap_words`, the ONE reader),
accepted by `contract.window_shape_errors`, `acceptance.validate_window` and the controller's tiers 2 and 4 in one change.
Downstream (S8) nothing changes: D-0013's `review_unverified` -> "Left with you".

FIXTURE. The live 12586 copy is on the owner's stand, not on this machine (P0 of the spec is skipped by the Lead), so the
12586 shape is built: `test_window_record.a_story_at_s5` (a real controller, two cases, run blocks), with test_a[x]
`new_or_changed` and green, its receipt removed, the critic's `unverified` + `sensitivity_proof_missing_reason` on the
manifest row, a `work/probes/<stem>.json` record `not_executed` of the same bytes, and the person's word in
`pipeline.json`. SYNTHETIC: one instance, not three; the shapes the gate reads are the same.

Keys (spec section 6): K1 the end to end; K2 no word; K3 revoked / hand-written claim; K4 pipeline unreadable; K5 shape;
K6 the word reader, adversarial; K7 the review rule; K8 the probe record's verdicts; K9 non-ASCII words whole; K10 revoke;
K11 a receipt outranks the word; K12 the S8 road; K13 old windows unchanged; K14 the data row; K15 the limits;
K16 three kinds in one pair; K17 the negative control.
"""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import (check, check_eq, check_in, check_not_in, cleanup, finish, run_script,  # noqa: E402
                     temp_project, use_project)

sys.path.insert(0, str(harness.SCRIPTS))
import acceptance as AC  # noqa: E402
import contract as C  # noqa: E402
import controller as CONTROLLER  # noqa: E402
import proof_level  # noqa: E402
import story_step  # noqa: E402
import waiver as W  # noqa: E402
import window_record as WR  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_blocked_by_env_window as TB  # noqa: E402  (its CLI helpers over the story fixture)
import test_window_record as TW  # noqa: E402  (the story fixture and its stand-in detector)

IID = "test_a[x]"
CASE = "TC-1"
WORDS = "go on without the probe: the stand has no profile for it, I will check it by hand"
BLOCK = "probe gap: " + IID
WHY = "0 report rows are named by the node id"
PASSED_BY_PERSON = "state/passed-by-person.jsonl"


# --- the story ------------------------------------------------------------------------------------------------

def probe_record(task: Path, verdict="not_executed", sha=None, notes=(WHY,), raw=None, iid=IID, **extra) -> Path:
    """`work/probes/<stem>.json` the way `probe_by_code._new_record` leaves it (the keys the window reads); `extra` are more
    keys of the record (`cause`, `language`: what the tool says when it could not read the test)."""
    path = proof_level.probe_record_path(task, iid)
    if raw is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw, encoding="utf-8")
        return path
    body = {"schema_version": 1, "probe_tool": "probe_by_code.py", "instance_id": iid, "verdict": verdict,
            "test_file_sha256": sha or TW.SHAS[CASE], "notes": list(notes), "recorded_at": "2026-10-22T10:00:00+00:00", **extra}
    return TW.write(path, body)


def gap_story(project: Path, *, word=WORDS, record="not_executed", match=BLOCK) -> Path:
    """test_a[x] ran green, owes a live check, reached no receipt; the critic said `unverified` and why; `word` is the
    person's recorded word (None: nobody said anything); `record` the probe record's verdict (None: no record)."""
    task, _controller = TW.a_story_at_s5(project)
    manifest_path = task / "work/automation-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for binding in manifest["obligation_bindings"]:
        binding.pop("probe_receipt_ref", None)
    for row in manifest["tests"]:
        if row["instance_id"] == IID:
            row["critic_verdict"] = "unverified"
            row["sensitivity_proof_missing_reason"] = "probe_by_code.py: not_executed - " + WHY
    TW.write(manifest_path, manifest)
    (task / TW.PROBE_REF).unlink()
    if record:
        probe_record(task, record)
    if word is not None:
        TW.say_word(task, match, word)
    return task


def window_file(task: Path) -> dict:
    return json.loads((task / "work/windows" / (TW.CRITIC + ".json")).read_text(encoding="utf-8"))


def built(task: Path) -> tuple:
    """`window_record.build` in this process over the real controller and a detector that finds no changed test:
    (window, notes)."""
    with TW.Detector({"pairs": [], "unmeasured": []}):
        return WR.build(task, TW.CRITIC)


def item_of(window: dict, iid: str = IID) -> dict:
    return next(i for i in window["instances"] if i["instance_id"] == iid)


def passed_lines(task: Path) -> list:
    path = task / PASSED_BY_PERSON
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] \
        if path.is_file() else []


def k1_the_end_to_end():
    project = temp_project("qa-probe-gap-k1-")
    use_project(project)
    try:
        task = gap_story(project)
        built_cli = TB.run_window_cli(project, "--review-receipt")
        out = built_cli.stdout
        check_eq("K1: window_record exits 0 (acceptable as unresolved)", built_cli.returncode, 0)
        check_in("K1: the GAP line names the instance, its case, the probe's verdict, the why and the words whole",
                 f"acceptable as unresolved: 1 probe gap(s) named - {IID} ({CASE}): probe not_executed, "
                 f"{WHY}; their words: \"{WORDS}\"", out)
        check_not_in("K1/mutation 8: the word that WAS read is not printed as unread", "recorded, not read", out)
        check_not_in("K1: and the record is not called NOT acceptable", "NOT acceptable", out)
        window = window_file(task)
        gap = item_of(window)["probe_gap"]
        check_eq("K1: the item carries the block (verdict, record, why, named_by, words)",
                 (gap["verdict"], gap["record"], gap["why"], gap["named_by"], gap["words"]),
                 ("not_executed", "work/probes/" + proof_level.probe_record_path(task, IID).name, WHY, IID, WORDS))
        check("K1: and no `probe` beside it (the block is never inside `probe`)", "probe" not in item_of(window))
        check_eq("K1: the test_b item (unchanged, approved) is untouched: no block", "probe_gap" in item_of(window, "test_b[y]"), False)
        check_eq("K1: the shape check accepts it", C.window_shape_errors(window), [])
        check_eq("K1: and the ONLY gap is the named probe gap", AC.validate_window(window, task), ["probe_gap:" + IID])
        pair = story_step._derived_pair(AC.validate_window(window, task), "work/windows/x.json")
        check_eq("K1: story_step derives the pair", pair, ("probe_gap", "probe_gap; full list: work/windows/x.json; "
                                                           "probe_gap:" + IID))
        done = TB.finish_cli(project, task)
        check_eq("K1: story_step finish is accepted by the controller (exit 0)", done.returncode, 0, )
        check_in("K1: and says so", "accepted " + TW.CRITIC, done.stdout)
        state = CONTROLLER.Controller(task).state()
        record = state["dispatches"][TW.CRITIC]
        check_eq("K1: the dispatch is accepted, S5 is completed, `unresolved` is the word",
                 (record["status"], state["stages"]["S5"]["status"], record.get("unresolved")),
                 ("accepted", "completed", "probe_gap"))
        lines = passed_lines(task)
        check_eq("K1: ONE line in passed-by-person.jsonl: the stage, the block, the person's words whole, `by`",
                 [(l["stage"], l["block"], l["decision"], l["by"]) for l in lines],
                 [("S5", "probe_gap:" + IID, WORDS, "human")])
    finally:
        cleanup(project)


def k2_no_word_is_refused_with_the_door():
    project = temp_project("qa-probe-gap-k2-")
    use_project(project)
    try:
        task = gap_story(project, word=None)
        out = TB.run_window_cli(project)
        check_eq("K2: no word: window_record exits 1", out.returncode, 1)
        check_in("K2: with today's line", f"{IID}: probe is missing for a new_or_changed instance", out.stdout)
        check_in("K2: and the critic's door", "probe_by_code.py", out.stdout)
        check_in("K2: and the orchestrator's door, the block named, the words by file",
                 'waiver.py --task <T> --stage S5 --block "probe gap: <case key>" --words-file <file>', out.stdout)
        window = window_file(task)
        check_eq("K2: and no block was written (F6: the no-word path is today's)", "probe_gap" in item_of(window), False)
        refused = TW.accept_window(project, task, window, "k2")
        text = (refused.stdout + refused.stderr).replace('\\"', '"')   # the refusal is a JSON string
        check("K2: the controller refuses at tier 2", refused.returncode != 0, text)
        check_in("K2: with the shape list", f"S5 window record is incomplete: {IID}: probe is missing for a new_or_changed "
                                           "instance", text)
        check_in("K2: and the door sentence for the orchestrator, ending with the block named",
                 'waiver.py --task QA-WINDOW-1 --stage S5 --block "probe gap: <case key>" --words-file <file>', text)
        check_eq("K2: nothing was accepted", CONTROLLER.Controller(task).state()["dispatches"][TW.CRITIC]["status"],
                 "running")
        check_eq("K2: and nothing was recorded as a pass", passed_lines(task), [])
    finally:
        cleanup(project)


def k3_an_unrecorded_claim_is_refused_whatever_the_caller_typed():
    project = temp_project("qa-probe-gap-k3-")
    use_project(project)
    try:
        task = gap_story(project)
        check_eq("K3: (setup) the window with the word builds", TB.run_window_cli(project, "--review-receipt").returncode, 0)
        window = window_file(task)
        # the person takes the word back: the record on disk keeps the claim, the story no longer says so
        TW.say_word(task, BLOCK, WORDS, revoked=True)
        check_eq("K3: revoked: the claim is `probe_gap_unrecorded`, never `probe_gap`",
                 AC.validate_window(window, task), ["probe_gap_unrecorded:" + IID])
        for label, extra in (("no pair", {}),
                             ("a typed pair that names the word",
                              {"unresolved": ["probe_gap"], "reason": "probe_gap; the caller typed this"})):
            refused = TW.accept_window(project, task, window, "k3-" + label.split()[0], **extra)
            text = (refused.stdout + refused.stderr).replace('\\"', '"')   # the refusal is a JSON string
            check(f"K3: {label}: the controller refuses", refused.returncode != 0, text)
            check_in(f"K3: {label}: and says no recorded word names the instance", "no recorded word of the person names", text)
            check_in(f"K3: {label}: and names the door", 'waiver.py --task QA-WINDOW-1 --stage S5 --block "probe gap: <case key>"',
                     text)
            check_eq(f"K3: {label}: nothing was accepted",
                     CONTROLLER.Controller(task).state()["dispatches"][TW.CRITIC]["status"], "running")
        check_eq("K3: a rebuild after the revoke is today's refusal", TB.run_window_cli(project).returncode, 1)
        check_in("K3: with the probe-missing line", "probe is missing for a new_or_changed instance",
                 TB.run_window_cli(project).stdout)
    finally:
        cleanup(project)
    # a record written by hand, with NO word anywhere in the story
    project = temp_project("qa-probe-gap-k3b-")
    use_project(project)
    try:
        task = gap_story(project, word=None)
        window, _notes = built(task)
        item_of(window)["probe_gap"] = {"verdict": "not_executed", "record": None, "why": "typed by hand",
                                        "named_by": IID, "words": "the critic says the person agreed"}
        check_eq("K3: a hand-written claim with no word: the shape is fine", C.window_shape_errors(window), [])
        check_eq("K3: and the gap is `probe_gap_unrecorded`", AC.validate_window(window, task), ["probe_gap_unrecorded:" + IID])
        refused = TW.accept_window(project, task, window, "k3-hand", unresolved=["probe_gap"], reason="probe_gap; x")
        check("K3: and a typed pair does not pass it", refused.returncode != 0, refused.stdout + refused.stderr)
    finally:
        cleanup(project)


def k4_an_unreadable_pipeline_names_nobody():
    project = temp_project("qa-probe-gap-k4-")
    use_project(project)
    try:
        task = gap_story(project)
        window, _ = built(task)
        check("K4: (setup) with the word the block is written", "probe_gap" in item_of(window))
        for label, text in (("pipeline.json = []", "[]"), ("stage_overrides = {}", json.dumps({"stage_overrides": {}})),
                            ("not JSON at all", "{not json"), ("missing", None)):
            if text is None:
                (task / "pipeline.json").unlink()
            else:
                (task / "pipeline.json").write_text(text, encoding="utf-8")
            try:
                loaded = json.loads(text) if text is not None else None
            except ValueError:
                loaded = None
            check_eq(f"K4: {label}: the reader returns nothing", C.probe_gap_words(loaded), {})
            rebuilt, _ = built(task)
            check_eq(f"K4: {label}: no block is written", "probe_gap" in item_of(rebuilt), False)
            check_eq(f"K4: {label}: the claim of the earlier window reads unrecorded",
                     AC.validate_window(window, task), ["probe_gap_unrecorded:" + IID])
    finally:
        cleanup(project)


def k5_the_shape():
    project = temp_project("qa-probe-gap-k5-")
    use_project(project)
    try:
        task = gap_story(project)
        base, _ = built(task)
        check_eq("K5: (setup) the well-formed block has no shape error at all", C.window_shape_errors(base), [])

        def errors(mutate) -> list:
            window = copy.deepcopy(base)
            mutate(item_of(window))
            return [e for e in C.window_shape_errors(window)]

        gap_errors = lambda es: [e for e in es if e.startswith(f"{IID}: probe_gap: ")]  # noqa: E731
        on_red = errors(lambda i: i.update(outcome="failed"))
        check_eq("K5/E6: a hand-written block on a RED instance is one shape error", len(gap_errors(on_red)), 1)
        check_in("K5/E6: that says the instance must have run green", "ran green", gap_errors(on_red)[0])
        check_not_in("K5/E6: and the probe-missing line is not added beside it", "probe is missing", "\n".join(on_red))
        beside = errors(lambda i: i.update(probe={"verdict": "intended_failure"}))
        check_eq("K5/E10: probe_gap beside probe is one shape error", len(gap_errors(beside)), 1)
        check_in("K5/E10: it says the two are never both", "not both", gap_errors(beside)[0])
        for label, value, expect in (
                ("a list", [], 1), ("a string", "not_executed", 1), ("None", None, 1),
                ("an empty object", {}, 4),
                ("verdict as a list", {"verdict": ["not_executed"], "why": "w", "named_by": "n", "words": "x"}, 1),
                ("an unknown verdict", {"verdict": "passed", "why": "w", "named_by": "n", "words": "x"}, 1),
                ("words as an object", {"verdict": "not_run", "why": "w", "named_by": "n", "words": {}}, 1),
                ("an empty why", {"verdict": "not_run", "why": "", "named_by": "n", "words": "x"}, 1),
                ("a blank named_by", {"verdict": "not_run", "why": "w", "named_by": "  ", "words": "x"}, 1),
                ("a record that is a number", {"verdict": "not_run", "why": "w", "named_by": "n", "words": "x",
                                               "record": 5}, 1)):
            got = gap_errors(errors(lambda i, v=value: i.update(probe_gap=v)))
            check_eq(f"K5/battery: {label}: {expect} shape error(s), one per problem", len(got), expect)
        check_eq("K5: a record of null or a string is fine",
                 [C.probe_gap_errors(dict(item_of(base), probe_gap=dict(item_of(base)["probe_gap"], record=r)))
                  for r in (None, "work/probes/x.json")], [[], []])
        check_eq("K5: an item with no block has nothing to say; a non-object is not this check's",
                 (C.probe_gap_errors({}), C.probe_gap_errors("x"), C.probe_gap_errors(None)), ([], [], []))
        # E1 / builder rule 9: an old window - no block, no probe, a new_or_changed instance - keeps today's line
        old = copy.deepcopy(base)
        del item_of(old)["probe_gap"]
        check_eq("K5/E1: an old window keeps today's line exactly",
                 [e for e in C.window_shape_errors(old)], [f"{IID}: " + C.PROBE_MISSING_ERROR])
        check_eq("K5: the constant is today's text", C.PROBE_MISSING_ERROR,
                 "probe is missing for a new_or_changed instance")
    finally:
        cleanup(project)


def words_of(*entries) -> dict:
    return C.probe_gap_words({"stage_overrides": [dict({"stage": "S5", "decision": "ok", "at": "t"}, **e)
                                                  for e in entries]})


def k6_the_reader_names_by_identifier_only():
    refused = [
        ("a star", {"match": "*"}), ("an empty value", {"match": "probe gap:"}),
        ("a colon-led value", {"match": "probe gap: :x"}), ("a value that is words", {"match": "probe gap: test_a extra words"}),
        ("no colon", {"match": "probe gap test_a"}), ("the prefix not at the start", {"match": "x probe gap: test_a"}),
        ("not receipted", {"match": "not receipted"}), ("a substring of the shape line", {"match": "probe is missing"}),
        ("the other family", {"match": "then handed: TC-007#1"}), ("empty words", {"match": "probe gap: test_a", "decision": ""}),
        ("another stage", {"match": "probe gap: test_a", "stage": "S6"}),
        ("a revoked record", {"match": "probe gap: test_a", "revoked_at": "2026-10-23T10:00:00"}),
        ("a no-break space inside the value", {"match": "probe gap: test_a b"}),
        ("a match that is not text", {"match": None}), ("a missing match", {}),
    ]
    for label, entry in refused:
        check_eq(f"K6: {label}: no entry", words_of(entry), {})
    check_eq("K6: an entry that is no object, and a pipeline with no list, give none",
             (C.probe_gap_words({"stage_overrides": ["probe gap: test_a", 5, None]}), C.probe_gap_words([]),
              C.probe_gap_words(None), C.probe_gap_words({"stage_overrides": "probe gap: test_a"})), ({}, {}, {}, {}))
    for label, match, key in (("the exact id", "probe gap: test_a[chromium]", "test_a[chromium]"),
                              ("the prefix folds in case and spaces", "PROBE   GAP:   test_b[chromium]", "test_b[chromium]"),
                              ("a case key", "probe gap: TC-007", "TC-007"),
                              ("quotes around the value are cut", 'probe gap: "test_c[x]"', "test_c[x]")):
        got = words_of({"match": match, "decision": "  I   accept\nthis  "})
        check_eq(f"K6: {label}: one entry, the words whole with whitespace folded",
                 got, {key: {"words": "I accept this", "at": "t"}})
    # the join: identifier equality, case kept, never a prefix of the id
    project = temp_project("qa-probe-gap-k6-")
    use_project(project)
    try:
        task = gap_story(project, word=None)
        window, _ = built(task)
        item_of(window)["probe_gap"] = {"verdict": "not_run", "record": None, "why": "w", "named_by": "n", "words": "x"}

        def named(*matches) -> dict:
            TW.write(task / "pipeline.json", {"stage_overrides": [
                {"stage": "S5", "match": m, "decision": "ok", "at": "t"} for m in matches]})
            return AC.probe_gap_named(window, task)

        check_eq("K6: the exact id names the instance", list(named(BLOCK)), [IID])
        check_eq("K6: and so does the case key of its scope (F3 b)", named("probe gap: " + CASE)[IID]["key"], CASE)
        check_eq("K6: another case names nothing", named("probe gap: TC-2"), {})
        check_eq("K6: a different spelling of the id names nothing (case kept)", named("probe gap: TEST_A[X]"), {})
        check_eq("K6: the id without its parameter names nothing", named("probe gap: test_a"), {})
        check_eq("K6: the instance of ANOTHER item names nothing here", named("probe gap: test_b[y]"), {})
        check_eq("K6: `*` names nothing", named("*"), {})
        check_eq("K6: `not receipted` names nothing", named("not receipted"), {})
    finally:
        cleanup(project)
    # end to end: a recorded `*` and a recorded `not receipted` never open the gap; the line says they were not read
    for label, match in (("a star", "*"), ("not receipted", "not receipted")):
        project = temp_project("qa-probe-gap-k6s-")
        use_project(project)
        try:
            task = gap_story(project, word=WORDS, match=match)
            out = TB.run_window_cli(project)
            check_eq(f"K6/E4: {label}: window_record exits 1", out.returncode, 1)
            check_in(f"K6/E4: {label}: with the probe-missing line", "probe is missing for a new_or_changed instance", out.stdout)
            if match == "*":   # `not receipted` matches no line of this window, so there is nothing to say about it
                check_in(f"K6/E4: {label}: and the word is printed as recorded, not read", "recorded, not read by this window",
                         out.stdout)
            check_eq(f"K6/E4: {label}: no block was written", "probe_gap" in item_of(window_file(task)), False)
            refused = TW.accept_window(project, task, window_file(task), "k6")
            check(f"K6/E4: {label}: the controller refuses", refused.returncode != 0, refused.stdout + refused.stderr)
        finally:
            cleanup(project)


def k7_the_review_word():
    project = temp_project("qa-probe-gap-k7-")
    use_project(project)
    try:
        task = gap_story(project)
        window, _ = built(task)
        check_eq("K7: unverified and bound: no review gap", AC.validate_window(window, task), ["probe_gap:" + IID])
        approved = copy.deepcopy(window)
        item_of(approved)["review"]["verdict"] = "approved"
        check_eq("K7/F5: `approved` on a probe-gap item is a review gap (the critic would claim a live check that never ran)",
                 AC.validate_window(approved, task), sorted(["probe_gap:" + IID, "review:" + IID]))
        stale = copy.deepcopy(window)
        item_of(stale)["review"]["input_hash"] = "0" * 64
        gaps = AC.validate_window(stale, task)
        check_eq("K7/E19: `unverified` of OTHER bytes is `stale_review`", gaps, sorted(["probe_gap:" + IID, "stale_review:" + IID]))
        none = copy.deepcopy(window)
        item_of(none)["review"]["verdict"] = ""
        check_eq("K7: no verdict at all is a review gap", AC.validate_window(none, task), sorted(["probe_gap:" + IID, "review:" + IID]))
        # the sensitivity checks do not run for it: no `sensitivity:` / `probe_evidence:` would claim a probe ran and missed
        check_eq("K7: and none of the probe checks speaks", [g for g in gaps if g.split(":")[0] in
                 ("sensitivity", "semantic_sensitivity", "probe_evidence", "probe_level")], [])
        # an item that owes no probe ignores the block and keeps today's rule (approved)
        unchanged = copy.deepcopy(window)
        other = item_of(unchanged, "test_b[y]")
        other["probe_gap"] = copy.deepcopy(item_of(unchanged)["probe_gap"])
        check_eq("K7/E13: an item that owes no live check is judged as before: the block changes nothing",
                 AC.validate_window(unchanged, task), ["probe_gap:" + IID])
        # window_record names the review door when the critic wrote `approved`
        manifest_path = task / "work/automation-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for row in manifest["tests"]:
            if row["instance_id"] == IID:
                row["critic_verdict"] = "approved"
        TW.write(manifest_path, manifest)
        out = TB.run_window_cli(project)
        check_eq("K7: the build with `approved` exits 1", out.returncode, 1)
        check_in("K7: and the review line says the verdict of such an instance is `unverified`",
                 "the verdict of such an instance is `unverified`", out.stdout)
    finally:
        cleanup(project)


def k8_the_probe_record_says_what_happened():
    project = temp_project("qa-probe-gap-k8-")
    use_project(project)
    try:
        task = gap_story(project, record=None)

        def block(**kw) -> tuple:
            probe_record(task, **kw)
            window, notes = built(task)
            return item_of(window).get("probe_gap"), notes

        for verdict in ("not_executed", "incomplete"):
            gap, _ = block(verdict=verdict, notes=("first", WHY))
            check_eq(f"K8: a {verdict} record of these bytes is the verdict, with its LAST note",
                     (gap["verdict"], gap["why"]), (verdict, WHY))
        for verdict in ("intended_failure", "no_failure", "wrong_location"):
            gap, notes = block(verdict=verdict)
            check_eq(f"K8/E8: a record that JUDGED these bytes ({verdict}) writes no block", gap, None)
            check("K8/E8: and the probe-missing note keeps its door", any(n[1] == "probe" for n in notes), str(notes))
        gap, _ = block(verdict="not_executed", sha="0" * 64)
        check_eq("K8: a record of other bytes is `not_run`, said so", (gap["verdict"], gap["why"]),
                 ("not_run", "the probe record is of other bytes"))
        gap, _ = block(verdict="intended_failure", sha="0" * 64)
        check_eq("K8: and so is a judging record of OTHER bytes (these bytes were never probed)", gap["verdict"], "not_run")
        gap, _ = block(verdict="")
        check_eq("K8: a record with no verdict is `not_run`", (gap["verdict"], gap["why"]),
                 ("not_run", "the probe record has no verdict"))
        gap, _ = block(verdict="not_executed", notes=())
        check_eq("K8: a not_executed record with no note says the probe did not run", gap["why"], "the probe did not run")
        for label, raw in (("unreadable JSON", "{oops"), ("a list", "[1, 2]"), ("an empty object", "{}")):
            gap, _ = block(raw=raw)
            check_eq(f"K8: {label}: `not_run`, no probe of these bytes", (gap["verdict"], gap["why"]),
                     ("not_run", "no probe of these bytes was run"))
        probe_record(task).unlink()
        window, _ = built(task)
        gap = item_of(window)["probe_gap"]
        check_eq("K8: no record at all: `not_run`, and the record is null", (gap["verdict"], gap["record"]), ("not_run", None))
        # a red instance writes nothing, the word notwithstanding (E6)
        run_blocks = sorted((task / "work/run-blocks").glob("*b1.json"))
        failed = json.loads(run_blocks[0].read_text(encoding="utf-8"))
        failed["execution_status"] = "failed"
        failed["results"][0]["status"] = "failed"
        TW.write(run_blocks[0], failed)
        window, _ = built(task)
        check_eq("K8/E6: a RED instance with the word: no block", "probe_gap" in item_of(window), False)
        check_eq("K8/E6: and the window says `product:`", "product:" + IID in AC.validate_window(window, task), True)
    finally:
        cleanup(project)


def k9_the_persons_words_travel_whole():
    project = temp_project("qa-probe-gap-k9-")
    use_project(project)
    try:
        task = gap_story(project, word=None)
        # non-ASCII on purpose, written as escapes (the package carries no Cyrillic, FR-30): Greek, a check mark, guillemets
        text = "εντάξει ✓ no probe here\n«by hand», 日本語"
        folded = " ".join(text.split())
        words_file = task / "state" / "words" / "k9.txt"
        words_file.parent.mkdir(parents=True, exist_ok=True)
        words_file.write_bytes(text.encode("utf-8"))
        recorded = run_script("waiver.py", "--task", TW.TICKET, "--stage", "S5", "--block", BLOCK,
                              "--words-file", words_file, cwd=project)
        check_eq("K9: waiver.py records the block through the data row (exit 0)", recorded.returncode, 0)
        check_in("K9: and says what it recorded", BLOCK, recorded.stdout + recorded.stderr)
        window, _ = built(task)
        check_eq("K9: the item carries the words whole, whitespace folded", item_of(window)["probe_gap"]["words"], folded)
        out = TB.run_window_cli(project, "--review-receipt")
        check_eq("K9: window_record exits 0", out.returncode, 0)
        check_in("K9: and the GAP line prints the words whole", f'their words: "{folded}"', out.stdout)
        done = TB.finish_cli(project, task)
        check_eq("K9: the controller accepts", done.returncode, 0)
        check_eq("K9: and the journal line holds the words whole, as written",
                 [l["decision"] for l in passed_lines(task)], [folded])
    finally:
        cleanup(project)


def k10_and_k11_the_way_out():
    project = temp_project("qa-probe-gap-k10-")
    use_project(project)
    try:
        task = gap_story(project)
        check_eq("K10: (setup) the window with the word is acceptable", TB.run_window_cli(project).returncode, 0)
        revoked = run_script("waiver.py", "--task", TW.TICKET, "--stage", "S5", "--block", BLOCK, "--revoke",
                             "--decision", "I changed my mind", cwd=project)
        check_eq("K10: waiver.py --revoke takes the block back (exit 0)", revoked.returncode, 0, )
        out = TB.run_window_cli(project)
        check_eq("K10/AR-25: the next build refuses again", out.returncode, 1)
        check_in("K10: with the probe-missing line", "probe is missing for a new_or_changed instance", out.stdout)
        check_eq("K10: and the earlier window file is rewritten without the block", "probe_gap" in item_of(window_file(task)), False)
    finally:
        cleanup(project)
    # K11: a receipt for the instance outranks the word
    project = temp_project("qa-probe-gap-k11-")
    use_project(project)
    try:
        task = gap_story(project)
        check_eq("K11: (setup) with the word the block is written", "probe_gap" in item_of(built(task)[0]), True)
        TW.write(task / TW.PROBE_REF, TW.live_body())
        manifest_path = task / "work/automation-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for binding in manifest["obligation_bindings"]:
            if binding["obligation_id"] == "OB-TS-1":
                binding["probe_receipt_ref"] = TW.PROBE_REF
        for row in manifest["tests"]:
            if row["instance_id"] == IID:
                row["critic_verdict"] = "approved"
                row.pop("sensitivity_proof_missing_reason", None)
        TW.write(manifest_path, manifest)
        window, _ = built(task)
        item = item_of(window)
        check_eq("K11/E9: a valid receipt wins: a `probe`, no `probe_gap`", ("probe" in item, "probe_gap" in item), (True, False))
        check_eq("K11: and the window is plain: no gap at all", AC.validate_window(window, task), [])
        done = TB.run_window_cli(project)
        check_in("K11: window_record says it is acceptable (not as unresolved)", "the window is acceptable", done.stdout)
    finally:
        cleanup(project)


def k12_the_s8_road_is_unchanged():
    import check_delivery
    import ledger
    project = temp_project("qa-probe-gap-k12-")
    use_project(project)
    try:
        task = gap_story(project)
        manifest = json.loads((task / "work/automation-manifest.json").read_text(encoding="utf-8"))
        row = next(t for t in manifest["tests"] if t["instance_id"] == IID)
        report = {"current_results": [{"instance_id": IID, "case": CASE, "status": "passed"}]}
        state, detail = ledger.test_state(row, report, {"triage": []})
        check_eq("K12: the ledger reads the critic's `unverified` on a green test as review_unverified (D-0013)",
                 state, "review_unverified")
        check_in("K12: with the critic's reason in the detail", "probe_by_code.py: not_executed", detail)
        records = check_delivery.unverified_records(task)
        check_eq("K12: and delivery counts ONE record left with the person for the case",
                 [(r["kind"], r["case"]) for r in records], [("review_unverified", CASE)])
    finally:
        cleanup(project)
    # the verdict itself, on the delivery fixture the existing test uses (the K1 story has no S8)
    import shutil
    from harness import GOOD
    root = temp_project("qa-probe-gap-k12b-")
    try:
        art = root / "qa-factory" / "artifacts" / "QA-1"
        shutil.copytree(GOOD, art)
        mpath = art / "work" / "automation-manifest.json"
        data = json.loads(mpath.read_text(encoding="utf-8"))
        data["tests"][0]["critic_verdict"] = "unverified"
        data["tests"][0]["sensitivity_proof_missing_reason"] = "probe_by_code.py: not_executed - " + WHY
        mpath.write_text(json.dumps(data), encoding="utf-8")
        doc = check_delivery.assess(art)
        check_eq("K12: the delivery verdict is `after_checks` (P21 third outcome), not ready, nothing blocking",
                 (doc["delivery_verdict"], doc["delivery_ready"], doc["blocked_by"]), ("after_checks", False, []))
        check_eq("K12: ONE counting item, review_unverified",
                 [(i["kind"], len(i["tests"])) for i in doc["left_items"] if i["counts"]], [("review_unverified", 1)])
    finally:
        cleanup(root)


def k13_a_story_without_the_word_is_today():
    project = temp_project("qa-probe-gap-k13-")
    use_project(project)
    try:
        task = gap_story(project, word=None, record=None)
        window, notes = built(task)
        check_eq("K13/E1: no word, no record: no block", "probe_gap" in item_of(window), False)
        check_eq("K13: the shape line is today's", [e for e in C.window_shape_errors(window)],
                 [f"{IID}: probe is missing for a new_or_changed instance"])
        check_eq("K13: the semantic gaps are today's: the probe checks and the `unverified` review of an item with "
                 "no probe, and nothing of the new kinds",
                 AC.validate_window(window, task),
                 sorted(["probe_evidence:" + IID, "probe_mutation_kind:" + IID, "review:" + IID,
                         "semantic_sensitivity:" + IID, "sensitivity:" + IID]))
        probe_note = next((n[2] for n in notes if n[:2] == (IID, "probe")), "")
        check("K13: the note for the probe is the one `build` always wrote",
              probe_note.startswith("no sensitivity receipt reaches this instance"), str(notes))
        check_in("K13: its door gains the second door (the orchestrator's word), the first stays",
                 "probe_by_code.py --task <T>", probe_note)
        check_in("K13: and the second", 'waiver.py --task <T> --stage S5 --block "probe gap: <case key>"', probe_note)
        check_eq("K13: `ORIGIN[\"probe\"]` stays the critic's command alone (test_red_sandbox_reports holds its flags)",
                 WR.ORIGIN["probe"][1], WR.PROBE_DOOR)
        for gap in ("sensitivity", "semantic_sensitivity", "probe_level", "probe_evidence"):
            check_not_in(f"K13: a probe that RAN and missed ({gap}) is not offered the word (it passes nothing there)",
                         "probe gap", WR.GAP_ORIGIN[gap][1])
    finally:
        cleanup(project)


def k14_the_data_row():
    row = W.block_name_row("probe gap: test_a[x]", "S5")
    check_eq("K14: the block is the data row's, read by contract:probe_gap_words",
             (row or {}).get("reader"), "contract:probe_gap_words")
    check_eq("K14: at S6 it is no name", W.block_name_row("probe gap: test_a[x]", "S6"), None)
    check_eq("K14: a value that is words is no name", W.block_name_row("probe gap: test_a and more", "S5"), None)
    check_eq("K14: an unfilled placeholder is no value", W.block_name_row("probe gap: <instance or case>", "S5"), None)
    check_eq("K14: `*` never reads the table", W.block_name_row("*", "S5"), None)
    check("K14: the loader validates every row, the new reader among them (a function of scripts/)",
          any(r["reader"] == "contract:probe_gap_words" for r in W.load_block_names()))


def k15_the_limits():
    project = temp_project("qa-probe-gap-k15-")
    use_project(project)
    try:
        task = gap_story(project, record=None)
        limit = C.PROBE_GAP_WHY_LIMIT
        check_eq("K15: the limit is 300", limit, 300)
        for length, label in ((limit, "AT"), (limit + 1, "BEYOND")):
            probe_record(task, notes=("w" * length,))
            gap = item_of(built(task)[0])["probe_gap"]
            if label == "AT":
                check_eq("K15: a why AT the limit is kept whole", (len(gap["why"]), gap["why"].endswith("…")), (limit, False))
            else:
                check_eq("K15: a why BEYOND the limit is cut with the cut marked (the mark counts)",
                         (len(gap["why"]), gap["why"].endswith("…")), (limit, True))
        probe_record(task, notes=("line one\n   line   two\t",))
        check_eq("K15: a why is ONE line: whitespace folded", item_of(built(task)[0])["probe_gap"]["why"], "line one line two")
        # the words themselves are never cut (FR-8)
        long_words = "εντάξει accepted " * 200
        TW.say_word(task, BLOCK, long_words)
        check_eq("K15: the person's words are never cut", item_of(built(task)[0])["probe_gap"]["words"], " ".join(long_words.split()))
        # E17: a derived reason over the limit keeps the kind in its head
        shown = "work/windows/" + TW.CRITIC + ".json"
        word, reason = story_step._derived_pair([f"probe_gap:{'i' * 5000}"], shown)
        check_eq("K15/E17: the kind stands first and the reason is cut at the limit", (word, len(reason)),
                 ("probe_gap", story_step.WINDOW_REASON_LIMIT))
        check("K15/E17: and `names_probe_gap` still finds its word", CONTROLLER.names_probe_gap({"unresolved": word, "reason": reason}))
        check_eq("K15/E17: a pair that does not say it is not read", CONTROLLER.names_probe_gap({"unresolved": ["x"], "reason": "y"}),
                 False)
        check_eq("K15: nor a payload that is no object", CONTROLLER.names_probe_gap(None), False)
        # magnitude battery: 40 items, 39 with words, one without -> exactly one refusal naming it
        base, _ = built(task)
        template = item_of(base)
        window = copy.deepcopy(base)
        window["instances"] = []
        window["scope_instances"] = {CASE: []}
        pipeline = {"stage_overrides": []}
        for n in range(40):
            item = copy.deepcopy(template)
            item["instance_id"] = f"test_a[p{n}]"
            window["instances"].append(item)
            window["scope_instances"][CASE].append(item["instance_id"])
            if n != 17:
                pipeline["stage_overrides"].append({"stage": "S5", "match": f"probe gap: test_a[p{n}]", "decision": "ok", "at": "t"})
        TW.write(task / "pipeline.json", pipeline)
        named = AC.probe_gap_named(window, task)
        check_eq("K15/magnitude: 39 of 40 are named", len(named), 39)
        check_eq("K15/magnitude: and the one without a word is exactly the one left out",
                 sorted(i["instance_id"] for i in window["instances"] if i["instance_id"] not in named), ["test_a[p17]"])
    finally:
        cleanup(project)


def k16_three_kinds_in_one_pair():
    gaps = ["blocked_by_env:a", "handed_to_person:b", "probe_gap:c"]
    word, reason = story_step._derived_pair(gaps, "w.json")
    check_eq("K16/E18: one pair names all three kinds in the gaps' own order", (word, reason.split("; full list")[0]),
             ("blocked_by_env", "blocked_by_env, handed_to_person, probe_gap"))
    payload = {"unresolved": word, "reason": reason}
    check_eq("K16: and each reader finds its word",
             (CONTROLLER.names_blocked(payload), CONTROLLER.names_handed(payload), CONTROLLER.names_probe_gap(payload)),
             (True, True, True))
    check_eq("K16: a gap of another kind among them derives nothing (t-204 F1)",
             story_step._derived_pair(gaps + ["sensitivity:d"], "w.json"), ())
    check_eq("K16: nor an UNRECORDED probe gap (no word names it)",
             story_step._derived_pair(["probe_gap_unrecorded:c"], "w.json"), ())
    # the tuple holds the third kind (`probe_gap`) and, since HF2-4b (t-115), a fourth: `contradicts_requirement` (a red test
    # its manifest row explains - an outcome S7 triages); `probe_gap_unrecorded` and `product:` stay out
    check_eq("K16: the tuple holds the third kind (and 4b's fourth)", story_step.DERIVED_GAP_KINDS,
             ("blocked_by_env", "handed_to_person", "probe_gap", "contradicts_requirement"))


def k17_the_negative_control():
    """K1's fixture WITHOUT the word, fed where K1 expects exit 0: the key must report failure (shown, not hidden)."""
    project = temp_project("qa-probe-gap-k17-")
    use_project(project)
    try:
        gap_story(project, word=None)
        out = TB.run_window_cli(project)
        expected_acceptable = "acceptable as unresolved: 1 probe gap(s) named" in out.stdout
        check_eq("K17: with no word the K1 expectation (exit 0 + the GAP line) does NOT hold, so K1 would fail here",
                 (out.returncode == 0, expected_acceptable), (False, False))
    finally:
        cleanup(project)


def k18_one_reader_skips_a_revoked_word():
    """t-070 F2: `probe_gap_words` is a join on `contract.stage_override_values`, the one reader `handed_profiles` and
    `then_handed_words` share: a revoked record is no word (control: the same record unrevoked is read)."""
    live = {"stage": "S5", "match": "probe gap: test_a", "decision": WORDS, "at": "t"}
    check_eq("K18 control: the unrevoked word is read", sorted(C.probe_gap_words({"stage_overrides": [live]})), ["test_a"])
    check_eq("K18: the same record revoked is not read",
             C.probe_gap_words({"stage_overrides": [dict(live, revoked_at="2026-10-23T10:00:00")]}), {})
    check_eq("K18: a live word beside a revoked one of ANOTHER instance reads only the live one",
             sorted(C.probe_gap_words({"stage_overrides": [live, dict(live, match="probe gap: test_b",
                                                                      revoked_at="2026-10-23T10:00:00")]})), ["test_a"])
    check_eq("K18: it IS the shared reader's join (the value of each record, once)",
             [v for v, _ in C.stage_override_values({"stage_overrides": [live]}, C.PROBE_GAP_MATCH_PREFIX)], ["test_a"])


def k19_a_word_that_matches_the_probe_gap_line_is_not_printed_as_unread():
    """t-075 (survivor t069-8, `WORD_READ_KINDS` without `probe_gap`). The constant is read at `window_record.verdict`
    (`if kind in WORD_READ_KINDS: read.add(line)`) and its effect is seen only through `_unread_words`, which asks
    `waiver.split_overridden` whether a recorded word's `match` is a SUBSTRING of the line. The probe-gap word itself
    (`probe gap: <id>`) is not a substring of the line (`probe_gap:<id> - ...`), so K1 never reaches the constant. A second
    word that IS one (`*`, which `contract.probe_gap_words` never reads as a name) does: the probe-gap line is read by
    the first word, so the second is not printed "recorded, not read" against it. Control in the same key: the same
    `*` word against a line of a kind nobody reads IS printed."""
    project = temp_project("qa-probe-gap-k19-")
    use_project(project)
    try:
        task = gap_story(project)
        STAR = "go on with everything else as well"
        TW.say_word(task, "*", STAR)
        window, notes = built(task)
        check_eq("K19 (setup): the item still carries the block - the `*` word names no instance",
                 "probe_gap" in item_of(window), True)
        info: list = []
        lines = WR.verdict(task, window, notes, info)
        check_eq("K19 (setup): and the one gap line is the probe gap's", [line.split(" ")[0] for line in lines],
                 ["probe_gap:" + IID])
        check_eq("K19: the word that matches the probe-gap line is not printed as unread - the line is read by its own word",
                 [line for line in info if "recorded, not read" in line], [])
        elsewhere: list = []
        WR._unread_words(task, [("quality:lint - not receipted", "")], elsewhere)
        check_in("K19 control: the same word against a line of a kind nobody reads is printed",
                 "recorded, not read by this window: " + STAR, "\n".join(elsewhere))
    finally:
        cleanup(project)


CLASS = "tooling:typescript"
CLASS_BLOCK = "probe gap: " + CLASS
TOOLING = {"cause": "tooling", "language": "typescript"}


def k20_the_word_for_a_class_of_tooling_gaps():
    """EP1-36 item 9: ONE question for the class `tooling:<language>`; the probe's own record says the tool could not read the
    language. The class is the LAST key; it covers no record that judged, no other bytes, no other language, no red test."""
    project = temp_project("qa-probe-gap-k20-")
    use_project(project)
    try:
        task = gap_story(project, record=None, match=CLASS_BLOCK, word="one answer for every TypeScript test: I check them by hand")
        probe_record(task, **TOOLING)
        window, _ = built(task)
        gap = item_of(window).get("probe_gap") or {}
        check_eq("K20: the class word names the instance whose record says `cause: tooling`",
                 (gap.get("named_by"), gap.get("verdict"), gap.get("why")), (CLASS, "not_executed", WHY))
        check_eq("K20: the window's only gap is the named probe gap, and a gap of the tool is not a product gap",
                 AC.validate_window(window, task), ["probe_gap:" + IID])
        check_eq("K20: the acceptance reads the same word through the same key",
                 {k: v["key"] for k, v in AC.probe_gap_named(window, task).items()}, {IID: CLASS})
        cli = TB.run_window_cli(project, "--review-receipt")
        check_eq("K20: window_record (the CLI) exits 0: acceptable as unresolved", cli.returncode, 0)
        done = TB.finish_cli(project, task)
        check_eq("K20: story_step finish is accepted by the controller, as for a word about the instance", done.returncode, 0)
        check_eq("K20: ONE line of the person's words: the instance's block, the class word whole",
                 [(l["block"], l["decision"]) for l in passed_lines(task)],
                 [("probe_gap:" + IID, "one answer for every TypeScript test: I check them by hand")])
        # the record, the bytes and the language
        words = {CLASS: {"words": "w", "at": "t"}}
        item = {"instance_id": IID, "input_hash": TW.SHAS[CASE]}
        get = lambda **rec: (probe_record(task, **rec), WR.probe_gap_block(task, item, [], words))[1]
        check_eq("K20 control: the record that says tooling gives the gap", (get(**TOOLING) or {}).get("named_by"), CLASS)
        check_eq("K20 (BEYOND): another language is a new question", get(cause="tooling", language="java"), None)
        check_eq("K20: a stand that did not run (no cause) needs the word of its own", get(language="typescript"), None)
        check_eq("K20: another cause is not the tool's", get(cause="stand", language="typescript"), None)
        check_eq("K20: no language, no class", get(cause="tooling"), None)
        for verdict in ("intended_failure", "no_failure", "wrong_location"):
            check_eq(f"K20/E8: a record that JUDGED ({verdict}) takes no class word", get(verdict=verdict, **TOOLING), None)
        check_eq("K20: a record of other bytes takes none", get(sha="0" * 64, **TOOLING), None)
        check_eq("K20: an incomplete one does", (get(verdict="incomplete", **TOOLING) or {}).get("verdict"), "incomplete")
        probe_record(task, **TOOLING).unlink()
        check_eq("K20: no record, no class", WR.probe_gap_block(task, item, [], words), None)
        check_eq("K20: ...and the key is empty", proof_level.tooling_gap_key(task, IID, TW.SHAS[CASE]), "")
        probe_record(task, **TOOLING)
        check_eq("K20: tooling_gap_key reads the record once", proof_level.tooling_gap_key(task, IID, TW.SHAS[CASE]), CLASS)
        check_eq("K20: ...with the current bytes", proof_level.tooling_gap_key(task, IID, "0" * 64), "")
        check_eq("K20: ...and a hash that is empty names nothing", proof_level.tooling_gap_key(task, IID, ""), "")
        # AT: one question - the second window, another instance of the same class, no second word
        probe_record(task, iid="test_b[y]", **TOOLING)
        second = WR.probe_gap_block(task, {"instance_id": "test_b[y]", "input_hash": TW.SHAS[CASE]}, [], words)
        check_eq("K20 (AT): the second instance of the class is covered by the same word", (second or {}).get("named_by"), CLASS)
        # the word about the instance stays named_by
        both = {IID: {"words": "mine", "at": "t"}, **words}
        check_eq("K20: a word about the instance is read FIRST (`named_by` stays the instance)",
                 WR.probe_gap_block(task, item, [], both)["named_by"], IID)
        both = {CASE: {"words": "case", "at": "t"}, **words}
        check_eq("K20: ...and about its case before the class", WR.probe_gap_block(task, item, [CASE], both)["named_by"], CASE)
        # FR-12: the name is an identifier, never a pattern
        for label, value in (("a star", "*"), ("a part of it", "tooling:type"), ("the language alone", "typescript")):
            check_eq(f"K20/FR-12 ({label}): covers nothing", WR.probe_gap_block(task, item, [], {value: {"words": "w", "at": "t"}}), None)
        check_eq("K20: the table row takes the class as ONE token", W.block_name_row(CLASS_BLOCK, "S5")["reader"], "contract:probe_gap_words")
        check_eq("K20: two tokens are no name", W.block_name_row(CLASS_BLOCK + " x", "S5"), None)
        check_eq("K20: a part of the class names no instance", C.probe_gap_words({"stage_overrides": [
            {"stage": "S5", "match": "probe gap: tooling:type", "decision": "w"}]}).get(CLASS), None)
        # a red instance takes no word (E6)
        run_blocks = sorted((task / "work/run-blocks").glob("*b1.json"))
        failed = json.loads(run_blocks[0].read_text(encoding="utf-8"))
        failed["execution_status"], failed["results"][0]["status"] = "failed", "failed"
        TW.write(run_blocks[0], failed)
        probe_record(task, **TOOLING)
        window, _ = built(task)
        check_eq("K20/E6: a RED instance with the class word: no block", "probe_gap" in item_of(window), False)
        check_eq("K20/E6: and the window says `product:`", "product:" + IID in AC.validate_window(window, task), True)
    finally:
        cleanup(project)


def k21_the_factory_names_no_gap_of_its_own():
    """t-1968 N2 (E15, was RN1-9 B2): a green instance whose probe record of THESE bytes is `incomplete` with `cause: judgment` (the
    run failed at the mutated line on a text the factory cannot read) is the CODE CRITIC's to judge, never a gap: the window writes
    no `probe_gap` block for it (the factory names none), the class word does not cover it, the person's word about the instance
    still keeps `named_by`; at S8 it is left with the person under its own kind with ONE finding `PROBE_NOT_JUDGED`."""
    project = temp_project("qa-probe-gap-k21-")
    use_project(project)
    try:
        task = gap_story(project, record=None, word=None)
        probe_record(task, verdict="incomplete", cause="judgment")
        window, _ = built(task)
        check_eq("K21: no word, E15: the window writes NO probe_gap block (the factory names none)", "probe_gap" in item_of(window), False)
        item = {"instance_id": IID, "input_hash": TW.SHAS[CASE], "outcome": "passed"}
        mine = {IID: {"words": "mine", "at": "t"}}
        # t-2007 F1 (critic t-2000): a record still `unjudged` is NEVER named, by any word - the person's own word about the instance included
        check_eq("K21/m11: a record `unjudged` is named by no word, the person's word about the instance too", WR.probe_gap_block(task, item, [], mine), None)
        class_word = {"key": "class:probe_gap_accepted", "words": "class", "at": "t"}
        check_eq("K21: the GW1-43 class word does NOT cover a `cause: judgment` record", WR.probe_gap_block(task, item, [], {}, class_word), None)
        check_eq("K21: a RED instance (E15 record): no gap", WR.probe_gap_block(task, dict(item, outcome="failed"), [], {}), None)
        check_eq("K21/m12: other bytes: no gap", WR.probe_gap_block(task, dict(item, input_hash="0" * 64), [], {}), None)
        probe_record(task, **TOOLING)
        check_eq("K21: `cause: tooling` is not the critic's: no word, no gap", WR.probe_gap_block(task, item, [], {}), None)
        probe_record(task, verdict="not_executed", cause="judgment")
        check_eq("K21: `not_executed` + judgment is not owed a judgment", WR.probe_gap_block(task, item, [], {}), None)
        probe_record(task, verdict="incomplete")
        check_eq("K21: `incomplete` with no cause: no word, no gap", WR.probe_gap_block(task, item, [], {}), None)
        # S8: the kind and the ONE finding
        import check_delivery
        probe_record(task, verdict="incomplete", cause="judgment")
        check_eq("K21: S8: the record is of kind `review_unverified_factory`",
                 [(r["kind"], r["case"]) for r in check_delivery.unverified_records(task)], [("review_unverified_factory", CASE)])
        check_eq("K21: ... with ONE finding, owner factory, naming the instance",
                 [(f["code"], f["entity"], f["owner"]) for f in check_delivery.factory_data_gap_findings(task)],
                 [("PROBE_NOT_JUDGED", IID, "factory")])
        probe_record(task, verdict="incomplete", cause="tooling", language="typescript")
        check_eq("K21: the K12 control (not E15): plain `review_unverified`, no finding",
                 ([r["kind"] for r in check_delivery.unverified_records(task)], check_delivery.factory_data_gap_findings(task)),
                 (["review_unverified"], []))
        probe_record(task, verdict="incomplete", cause="judgment")
        manifest = json.loads((task / "work/automation-manifest.json").read_text(encoding="utf-8"))
        test_file = project / next(t["file"] for t in manifest["tests"] if t["instance_id"] == IID)
        saved = test_file.read_bytes()
        test_file.unlink()
        check_eq("K21/E-13c: the test file gone: plain `review_unverified`, no finding (an unknown never upgrades)",
                 ([r["kind"] for r in check_delivery.unverified_records(task)], check_delivery.factory_data_gap_findings(task)),
                 (["review_unverified"], []))
        test_file.write_bytes(saved)
    finally:
        cleanup(project)
    # the verdict itself, on the delivery fixture of K12
    import hashlib
    import shutil
    from harness import GOOD
    root = temp_project("qa-probe-gap-k21b-")
    try:
        art = root / "qa-factory" / "artifacts" / "QA-1"
        shutil.copytree(GOOD, art)
        mpath = art / "work" / "automation-manifest.json"
        data = json.loads(mpath.read_text(encoding="utf-8"))
        row = data["tests"][0]
        row["critic_verdict"] = "unverified"
        row["sensitivity_proof_missing_reason"] = "probe_by_code.py: incomplete - " + WHY
        mpath.write_text(json.dumps(data), encoding="utf-8")
        source = b"def test_coupon():\n    assert 1 + 1 == 2\n"
        (root / row["file"]).write_bytes(source)
        iid = C.test_instance_id(row)
        TW.write(proof_level.probe_record_path(art, iid), {
            "schema_version": 1, "probe_tool": "probe_by_code.py", "instance_id": iid, "verdict": "incomplete", "cause": "judgment",
            "test_file_sha256": hashlib.sha256(source).hexdigest(), "notes": [WHY], "recorded_at": "2026-11-02T10:00:00+00:00"})
        doc = check_delivery.assess(art)
        check_eq("K21/m17: the delivery word on the E15 fixture is `after_checks` (the kind is known; an unknown kind gives `no`)",
                 (doc["delivery_verdict"], doc["delivery_ready"], doc["blocked_by"]), ("after_checks", False, []))
        check_eq("K21: ONE counting item, `review_unverified_factory`",
                 [(i["kind"], len(i["tests"])) for i in doc["left_items"] if i["counts"]], [("review_unverified_factory", 1)])
        check_eq("K21/m18: `doc[factory_findings]` holds ONE PROBE_NOT_JUDGED, owner factory",
                 [(f["code"], f["entity"], f["owner"]) for f in doc["factory_findings"] if f["code"] == "PROBE_NOT_JUDGED"],
                 [("PROBE_NOT_JUDGED", iid, "factory")])
        written = json.loads((art / "work" / "ledger.json").read_text(encoding="utf-8"))
        check_in("K21: and the ledger the report reads carries it (the finding reaches the collector through ledger.json)",
                 "PROBE_NOT_JUDGED", [f.get("code") for f in written.get("factory_findings") or []])
    finally:
        cleanup(root)


def main() -> None:
    k20_the_word_for_a_class_of_tooling_gaps()
    k1_the_end_to_end()
    k2_no_word_is_refused_with_the_door()
    k3_an_unrecorded_claim_is_refused_whatever_the_caller_typed()
    k4_an_unreadable_pipeline_names_nobody()
    k5_the_shape()
    k6_the_reader_names_by_identifier_only()
    k7_the_review_word()
    k8_the_probe_record_says_what_happened()
    k9_the_persons_words_travel_whole()
    k10_and_k11_the_way_out()
    k12_the_s8_road_is_unchanged()
    k13_a_story_without_the_word_is_today()
    k14_the_data_row()
    k15_the_limits()
    k16_three_kinds_in_one_pair()
    k17_the_negative_control()
    k18_one_reader_skips_a_revoked_word()
    k19_a_word_that_matches_the_probe_gap_line_is_not_printed_as_unread()
    k21_the_factory_names_no_gap_of_its_own()
    finish("probe gap with the person's word")


if __name__ == "__main__":
    main()
