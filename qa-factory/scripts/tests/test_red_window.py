#!/usr/bin/env python3
"""A red test the requirement contradicts closes its S5 window with its manifest row (HF2-4, GW1-23; spec t-085 rev. 3, 4a).

TP1-12586 (22-24.10.2026): the msteams test failed at TC-004's Then 2, its `unresolved[]` row said so, the critic
approved - and `window_record.py` refused three times: `product:` (no path for a red), `sensitivity:` (a probe on a red test
depends on the order of its asserts, F-20) and "probe is missing" (the shape). Here the story is built from
`test_window_record.a_story_at_s5` (imported, never copied): two `new_or_changed` instances, both red in their run blocks,
a `contradicts_requirement` row per case, no probe receipt, the critic's `approved`, no word of a person. The window is
`contradicts_requirement:*` x 2 with a `probe_not_applicable` block each, exit 0, the review receipt written.

Keys (spec 4.1): K5 the end to end; K5b a probe receipt on the red instance is NOT taken (F13, m4); K6 the battery
(a)...(o): every input that does not make a red explained stays a refusal; K7 a green with a row still owes its probe;
also the red `unchanged` edge (no block) and the position (l): a handed item is never red (m2).

Part 4b (spec 4.2): K1 the controller takes a red window only as an unresolved acceptance naming `contradicts_requirement`
(m1); K2 the door of a failed instance is the row road, never the person's `probe gap:` word (m4); K3/K3b the critic's
receipts item exempts a red test its row explains - the manifest-wide current red, never the window's own instances (m2,
m5); K4 `finish` derives the pair (m3); K5 the chain window -> finish -> accept -> `stage_done` closes S5 with no word;
K8 (the role texts) is rows of design/role-rules.json; K9 the exit of the state in `design/state-exits.md`.
"""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import acceptance as AC  # noqa: E402
import contract as C  # noqa: E402
import controller as CTRL  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_blocked_by_env_window as TB  # noqa: E402  (its CLI helper over the story fixture)
import test_window_record as TW  # noqa: E402  (the story fixture)

A, B, Z = "test_a[x]", "test_b[y]", "test_c[z]"
BLOCK_A, BLOCK_B = "20260924T090000000000Z-b1.json", "20260924T090100000000Z-b2.json"
WINDOW = "work/windows/" + TW.CRITIC + ".json"


def row_of(case, iids, thens=(1,)):
    return {"case": case, "reason": "contradicts_requirement", "instance_ids": list(iids), "thens": list(thens),
            "detail": f"{case} contradicts its requirement"}


def covered(case, iid, then=1):
    return {"case": case, "then": then, "instance_id": iid, "assertion_ref": f"tests/test_{case.lower()}.py:3",
            "status": "covered"}


def set_run(path: Path, status: str) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["execution_status"] = status
    data["results"][0].update(status=status, reason="AssertionError: coupon limit not enforced")
    TW.write(path, data)


def red_story(project: Path, receipt: bool = False) -> Path:
    """Two new_or_changed instances, both red, one row per case; `receipt`: the red test_a keeps its probe receipt."""
    task, _controller = TW.a_story_at_s5(project)
    path = task / "work/automation-manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for entry in manifest["tests"]:
        entry.update(status="red", change_disposition="new_or_changed")
    for binding in manifest["obligation_bindings"]:
        if binding.get("obligation_id") == "OB-TS-2":
            binding["change_disposition"] = "new_or_changed"
        if not receipt:
            binding.pop("probe_receipt_ref", None)
    if receipt:   # published on the row too, the way probe_by_code.py and red_sandbox.py leave it
        manifest["tests"][0]["sensitivity_proof"] = {"receipt_ref": {"path": TW.PROBE_REF,
                                                                     "sha256": TW.digest(task / TW.PROBE_REF)}}
    else:
        (task / TW.PROBE_REF).unlink()
    manifest["unresolved"] = [row_of("TC-1", [A]), row_of("TC-2", [B])]
    manifest["then_bindings"] = [covered("TC-1", A), covered("TC-2", B)]
    TW.write(path, manifest)
    set_run(task / "work/run-blocks" / BLOCK_A, "failed")
    set_run(task / "work/run-blocks" / BLOCK_B, "failed")
    return task


class Story:
    """A red story and the way to put a variant of it on disk: every variant starts from the pristine files."""

    def __init__(self, project: Path, receipt: bool = False):
        self.project, self.task = project, red_story(project, receipt)
        self.manifest_path = self.task / "work/automation-manifest.json"
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.blocks = {p.name: p.read_text(encoding="utf-8") for p in (self.task / "work/run-blocks").glob("*.json")}

    def put(self, edit=None, blocks=None):
        """The manifest with `edit(manifest)` applied; `blocks` maps a block name to `fn(path)` or None (delete)."""
        manifest = copy.deepcopy(self.manifest)
        if edit:
            edit(manifest)
        TW.write(self.manifest_path, manifest)
        for name, text in self.blocks.items():
            (self.task / "work/run-blocks" / name).write_text(text, encoding="utf-8")
        for name, fn in (blocks or {}).items():
            path = self.task / "work/run-blocks" / name
            if fn is None:
                path.unlink()
            else:
                fn(path)

    def run(self, *more, **variant):
        self.put(**variant)
        res = TB.run_window_cli(self.project, *more)
        window = json.loads((self.task / WINDOW).read_text(encoding="utf-8"))
        return res.returncode, res.stdout, window, AC.validate_window(window, self.task)


def item(window: dict, iid: str) -> dict:
    return next(i for i in window["instances"] if i["instance_id"] == iid)


def overrides(task: Path) -> list:
    path = task / "pipeline.json"
    return (json.loads(path.read_text(encoding="utf-8")).get("stage_overrides") or []) if path.is_file() else []


def refused(label, code, out, window, gaps, iid=A, still_red=(B,)):
    """The common shape of a refusal: exit 1, the instance is `product:` and never `contradicts_requirement:`, and the
    siblings the rows DO explain stay explained."""
    check_eq(f"{label}: exit 1", code, 1)
    check_in(f"{label}: the gap is product", "product:" + iid, gaps)
    check_not_in(f"{label}: never the red gap", "contradicts_requirement:" + iid, gaps)
    check_not_in(f"{label}: and no probe_not_applicable block", "probe_not_applicable", item(window, iid))
    for other in still_red:
        check_in(f"{label}: {other} stays explained", "contradicts_requirement:" + other, gaps)
    check_in(f"{label}: the record is NOT acceptable", "NOT acceptable", out)


def k5_the_end_to_end():
    project = temp_project("qa-red-window-k5-")
    use_project(project)
    try:
        story = Story(project)
        before = overrides(story.task)
        code, out, window, gaps = story.run("--review-receipt")
        check_eq("K5: exit 0", code, 0)
        check_in("K5: the red tests are named with the cases of their rows",
                 "acceptable as unresolved: 2 red test(s) the requirement contradicts - S7 triages them: "
                 f"{A} (TC-1); {B} (TC-2)", out)
        check_not_in("K5: not called NOT acceptable", "NOT acceptable", out)
        check_in("K5: the review receipt is printed", "review receipt: work/review-receipts/", out)
        check_eq("K5: and written", len(list((story.task / "work/review-receipts").glob("*.json"))), 1)
        check_eq("K5: the gaps are the red kind, one per instance",
                 gaps, [f"contradicts_requirement:{A}", f"contradicts_requirement:{B}"])
        check_eq("K5: the shape is whole", C.window_shape_errors(window), [])
        check_eq("K5: the block of test_a, the row as the manifest holds it",
                 item(window, A)["probe_not_applicable"],
                 {"why": "red", "reason": "contradicts_requirement",
                  "rows": [{"case": "TC-1", "instance_ids": [A], "thens": [1]}]})
        check("K5: no probe beside it", "probe" not in item(window, A))
        check_eq("K5: no new stage_overrides (no word of a person)", overrides(story.task), before)
        check_eq("K5: the critic's word is approved", item(window, A)["review"]["verdict"], "approved")
    finally:
        cleanup(project)


def k5b_a_receipt_on_the_red_instance_is_not_taken():
    project = temp_project("qa-red-window-k5b-")
    use_project(project)
    try:
        story = Story(project, receipt=True)
        code, out, window, gaps = story.run("--review-receipt")
        check_eq("K5b (m4): exit 0 with a probe receipt on the red instance", code, 0)
        mine = item(window, A)
        check_in("K5b: the block is there", "probe_not_applicable", mine)
        check("K5b: the receipt is not the window's probe", "probe" not in mine)
        check_not_in("K5b: nor cited as its evidence", TW.PROBE_REF, [e["path"] for e in mine["evidence_refs"]])
        check("K5b: the receipt stays on disk", (story.task / TW.PROBE_REF).is_file())
        check_eq("K5b: the shape is whole", C.window_shape_errors(window), [])
    finally:
        cleanup(project)


def k6_the_battery():
    project = temp_project("qa-red-window-k6-")
    use_project(project)
    try:
        story = Story(project)

        def on_a(**keys):
            return lambda m: m["unresolved"][0].update(keys)

        # (a) a row of another case
        code, out, window, gaps = story.run(edit=on_a(case="TC-9"))
        refused("K6 (a) a row of another case", code, out, window, gaps)
        check_in("K6 (a)/m5: the red gets the row's road, not the probe's or a word's", "manifest_put.py --task <T> --fragment <file>", out)
        check_not_in("K6 (a)/m5: no dead door (a person's word)", "waiver.py", out)
        check_not_in("K6 (a): the marker is never named", "qa_unresolved", out)
        # (b) a row about an instance the story does not hold
        code, out, window, gaps = story.run(edit=on_a(instance_ids=["test_other[z]"]))
        refused("K6 (b) a row about another instance", code, out, window, gaps)
        # (c) only an `error` run: no terminal result, no outcome
        code, out, window, gaps = story.run(blocks={BLOCK_A: lambda p: set_run(p, "error")})
        check_eq("K6 (c) only error: exit 1", code, 1)
        check_in("K6 (c): the outcome is missing", f"{A}: outcome is missing", out)
        check_not_in("K6 (c): never red", "contradicts_requirement:" + A, out)
        # (d) no run at all, a row; and the claim of `failed` with no run on disk is believed by nothing
        claimed = story.run()[2]    # the built window: test_a CLAIMS `failed`
        code, out, window, gaps = story.run(blocks={BLOCK_A: None})
        check_eq("K6 (d) no run: exit 1", code, 1)
        check_in("K6 (d): the outcome is missing", f"{A}: outcome is missing", out)
        check_not_in("K6 (d): never red", "contradicts_requirement:" + A, out)
        check_in("K6 (d)/m3: a window that CLAIMS `failed` with no run on disk reads product",
                 "product:" + A, AC.validate_window(claimed, story.task))
        # (e) the row names the partition P-a, the test runs P-b
        def partitions(m):
            m["unresolved"][0] = {"case": "TC-1", "reason": "contradicts_requirement", "partitions": ["P-a"], "thens": [1],
                                  "detail": "d"}
            m["tests"][0]["partitions"] = ["P-b"]
        code, out, window, gaps = story.run(edit=partitions)
        refused("K6 (e) P-a vs P-b", code, out, window, gaps)
        check_in("K6 (e): the refusal names both partitions", "names partitions [P-a] and " + A + " runs [P-b]", out)
        # (f) no covered Then of the row's case on the instance
        code, out, window, gaps = story.run(edit=lambda m: m.update(then_bindings=[covered("TC-2", B)]))
        refused("K6 (f) no covered Then", code, out, window, gaps)
        check_in("K6 (f): and says which Then the row names", "binds no Then of TC-1", out)
        # (g) approved, and no row at all for the case
        code, out, window, gaps = story.run(edit=lambda m: m.update(unresolved=[row_of("TC-2", [B])]))
        refused("K6 (g) approved without a row", code, out, window, gaps)
        # (h) a word `*` and a word `probe gap: <iid>` open nothing
        pipeline = story.task / "pipeline.json"
        saved = pipeline.read_bytes() if pipeline.is_file() else None
        TW.say_word(story.task, "*", "go on, all of it")
        TW.say_word(story.task, "probe gap: " + A, "I accept it without a probe")
        code, out, window, gaps = story.run(edit=lambda m: m.update(unresolved=[row_of("TC-2", [B])]))
        refused("K6 (h) the words `*` and `probe gap`", code, out, window, gaps)
        check_not_in("K6 (h): no probe_gap block on a red", "probe_gap", item(window, A))
        check_not_in("K6 (h): no probe_gap gap", "probe_gap:" + A, gaps)
        if saved is None:
            pipeline.unlink()
        else:
            pipeline.write_bytes(saved)
        # (i) the latest run PASSED, the row stays: the green path, the probe is owed (K7)
        code, out, window, gaps = story.run(blocks={BLOCK_A: lambda p: set_run(p, "passed")})
        check_eq("K6 (i)/K7: a green with a row still owes its probe: exit 1", code, 1)
        check_in("K6 (i)/K7: the probe is missing", f"{A}: {C.PROBE_MISSING_ERROR}", out)
        check_in("K6 (i)/K7: and the sensitivity gap stands", "sensitivity:" + A, gaps)
        check_not_in("K6 (i)/K7: no red gap", "contradicts_requirement:" + A, gaps)
        check_not_in("K6 (i)/K7: no block", "probe_not_applicable", item(window, A))
        check_in("K6 (i)/K7: the green keeps the probe's doors (PROBE_GAP_DOOR, as today)", "waiver.py", out)
        # (j) the critic did not approve a red
        code, out, window, gaps = story.run(edit=lambda m: m["tests"][0].update(critic_verdict="unverified"))
        check_eq("K6 (j): exit 1", code, 1)
        check_in("K6 (j): `review:` stands beside the red gap", "review:" + A, gaps)
        check_in("K6 (j): the red gap is still named", "contradicts_requirement:" + A, gaps)
        # (l) a window assembled by hand: a handed item whose instance has a failed run block and a row is handed, not red
        code, out, window, gaps = story.run()
        check_eq("K6 (l) control: the built window is red for both", gaps,
                 [f"contradicts_requirement:{A}", f"contradicts_requirement:{B}"])
        hand = copy.deepcopy(window)
        mine = item(hand, A)
        mine.update(outcome="handed_to_person", execution_fingerprint="", evidence_refs=[])
        mine.pop("probe_not_applicable")
        # EP1-4 (t-626 FR-4/AR-28; t-740): the claim counts as far as the manifest confirms it - a handed row for TC-1 and the
        # window's `scope_instances` - and a terminal run of the instance outranks the hand-off (`handed_instances` rule 3)
        hand["scope_instances"] = {**(hand.get("scope_instances") or {}), "TC-1": [A], "TC-2": [B]}
        confirming = copy.deepcopy(story.manifest)
        confirming["unresolved"] = [{"case": "TC-1", "reason": "handed_to_person", "detail": "web: npx playwright test a.spec.ts"},
                                    row_of("TC-2", [B])]
        TW.write(story.manifest_path, confirming)
        found = AC.validate_window(hand, story.task)
        check_in("K6 (l)/m2: the claim over a failed run is refused as unconfirmed (a run outranks the hand-off)",
                 "handed_unconfirmed:" + A, found)
        check_not_in("K6 (l)/m2: and never red, whatever the row", "contradicts_requirement:" + A, found)
        (story.task / "work/run-blocks" / BLOCK_A).unlink()   # the instance nobody ran; story.put restores the block below
        found = AC.validate_window(hand, story.task)
        check_in("K6 (l)/m2: the handed item is handed", "handed_to_person:" + A, found)
        check_not_in("K6 (l)/m2: and never red", "contradicts_requirement:" + A, found)
        check_in("K6 (l): its sibling is still red", "contradicts_requirement:" + B, found)
        # (m) F7: a red instance with a row, a green sibling of the SAME case with none: no refusal for the sibling
        def sibling(m):
            m["tests"].append(TW.test_row(Z, "TC-1", "TS-1", TW.SHAS["TC-1"], "unchanged", TW.obligation_hashes(story.task)))
        TW.run_block(story.task, "20260924T090200000000Z-b3.json", Z, "fp-c", "fingerprint-c")
        code, out, window, gaps = story.run(edit=sibling)
        check_eq("K6 (m)/F7: exit 0", code, 0)
        check_not_in("K6 (m)/m6: no refusal for the green sibling", "contradicts_requirement row names", out)
        check_in("K6 (m): the sibling is in the window", Z, [i["instance_id"] for i in window["instances"]])
        check_not_in("K6 (m): and has no gap", Z, " ".join(gaps))
        (story.task / "work/run-blocks/20260924T090200000000Z-b3.json").unlink()
        # (n) a red beside a row about its sibling: ONE refusal, the road named, never the marker
        code, out, window, gaps = story.run(edit=lambda m: m.update(unresolved=[row_of("TC-1", [B]), row_of("TC-2", [B])]))
        named = [line for line in out.splitlines() if "contradicts_requirement row names [" in line]
        check_eq("K6 (n): exactly one refusal line", len(named), 1)
        check_in("K6 (n): it names the row's instance and this one", f"names [{B}], not {A}", named[0])
        check_in("K6 (n): and the fragment road", "manifest_put.py --task <T> --fragment <file>", named[0])
        check_not_in("K6 (n): never the marker", "qa_unresolved", out)
        check_eq("K6 (n): exit 1", code, 1)

        # (o) one test red for the rows of two cases: red, both rows in the manifest's order, a note, exit 0
        def two_cases(m):
            m["tests"][0]["covers"] = ["TC-1", "TC-2"]
            m["tests"][0]["case_version_links"].append({"case_id": "TC-2", "version": "cv_tc-2"})
            m["unresolved"] = [row_of("TC-1", [A]), row_of("TC-2", [A, B])]
            m["then_bindings"] = [covered("TC-1", A), covered("TC-2", A), covered("TC-2", B)]
        code, out, window, gaps = story.run(edit=two_cases)
        check_eq("K6 (o): exit 0", code, 0)
        check_eq("K6 (o): red for both", gaps, [f"contradicts_requirement:{A}", f"contradicts_requirement:{B}"])
        check_eq("K6 (o)/m7: the block of test_a holds BOTH rows, in the manifest's order",
                 [r["case"] for r in item(window, A)["probe_not_applicable"]["rows"]], ["TC-1", "TC-2"])
        check_eq("K6 (o): the block of test_b holds its one", [r["case"] for r in item(window, B)["probe_not_applicable"]["rows"]],
                 ["TC-2"])
        check_in("K6 (o): the note, not a problem", f"note: {A} is red for the rows of TC-1 and TC-2; "
                 "the S5 check asks to keep one", out)
        check_in("K6 (o): the print names the cases of the rows", f"{A} (TC-1, TC-2)", out)
        # the red `unchanged` test: a gap, no block (the block is written exactly where a probe would be owed)
        def unchanged(m):
            m["tests"][1]["change_disposition"] = "unchanged"
        code, out, window, gaps = story.run(edit=unchanged)
        check_eq("edge: a red unchanged test: exit 0", code, 0)
        check_in("edge: it is the red gap", "contradicts_requirement:" + B, gaps)
        check_not_in("edge: and carries no block", "probe_not_applicable", item(window, B))
        check_eq("edge: the shape is whole", C.window_shape_errors(window), [])
    finally:
        cleanup(project)


# ---------------------------------------------------------------------------------------------------------------------
# HF2-4 part 4b (spec t-085 rev. 3, 4.2): the controller, `finish` and the role texts take the red window by code.
# Keys: K1 the pair must name the word; K2 the door follows the outcome; K3/K3b the critic's proof item exempts only
# the CURRENT red; K4 `finish` derives the pair; K5 the chain to `stage_done`; K8 (the two role texts) is rows of design/role-rules.json.
# ---------------------------------------------------------------------------------------------------------------------
RED_WORD = "contradicts_requirement"
FINDINGS = {"evidence_refs": [{"path": "work/test-code/critic-findings.md"}]}


def blob(res) -> str:
    return (res.stdout or "") + (res.stderr or "")


def dispatch_status(task: Path) -> str:
    return CTRL.Controller(task).state()["dispatches"][TW.CRITIC]["status"]


def k1_the_pair_must_name_the_word():
    """4b-K1 (m1): a red window is accepted only as an unresolved acceptance that NAMES `contradicts_requirement`."""
    project = temp_project("qa-red-window-4bk1-")
    use_project(project)
    try:
        story = Story(project)
        code, out, window, gaps = story.run("--review-receipt")
        check_eq("K1 control: the red window is built, exit 0", code, 0)
        named = f"{RED_WORD}:{A}, {RED_WORD}:{B}"
        for number, (label, extra) in enumerate((
                ("a pair typed by hand without the word", {"unresolved": ["TC-1", "TC-2"], "reason": "could not close it"}),
                ("no pair at all", {}),
                ("passed_green", {"passed_green": True}),
                ("a pair naming another word", {"unresolved": "blocked_by_env", "reason": "the stand is down"}))):
            refusal = TW.accept_window(project, story.task, window, f"k1-{number}", **extra)
            text = blob(refusal)
            check(f"K1/m1: {label} is refused", refusal.returncode != 0, text[:300])
            check_in(f"K1: {label} - the refusal names the red gaps", named, text)
            check_in(f"K1: {label} - and the word the pair must carry",
                     "accept it as unresolved with `unresolved` naming `contradicts_requirement`", text)
            check_in(f"K1: {label} - and the command that derives it from the record",
                     "story_step.py finish --task " + TW.TICKET + " --dispatch-id " + TW.CRITIC, text)
            check_eq(f"K1: {label} - nothing was accepted", dispatch_status(story.task), "running")
        check_in("K1: passed_green is refused for its own reason too", "cannot be passed_green",
                 blob(TW.accept_window(project, story.task, window, "k1-green", passed_green=True)))
        # the pair that names the word is taken, with no word of a person
        before = overrides(story.task)
        taken = TW.accept_window(project, story.task, window, "k1-typed", unresolved=RED_WORD,
                                 reason=f"{RED_WORD}: {A}; {B}")
        check_eq("K1: a pair that names the word is accepted", taken.returncode, 0)
        check_eq("K1: the dispatch is accepted", dispatch_status(story.task), "accepted")
        check_eq("K1: and no word of a person was read or written", overrides(story.task), before)
    finally:
        cleanup(project)


def k1_the_reader_and_its_twin():
    """`names_contradicts` is read like its twins: `unresolved` and `reason` together, whatever shape they take."""
    check_eq("K1: the word the controller spells is the one the window gap carries", CTRL.CONTRADICTS_WORD,
             AC.CONTRADICTS_REQUIREMENT)
    for label, payload, want in (
            ("a string and a reason", {"unresolved": RED_WORD, "reason": "x"}, True),
            ("the word in the reason only", {"unresolved": "pending", "reason": f"{RED_WORD}: {A}"}, True),
            ("a list of rows", {"unresolved": [{"case": "TC-1", "reason": RED_WORD}], "reason": "x"}, True),
            ("another word", {"unresolved": "blocked_by_env", "reason": "the stand"}, False),
            ("the word in a field nobody reads", {"unresolved": "x", "reason": "y", "note": RED_WORD}, False),
            ("an empty payload", {}, False),
            ("None", None, False),
            ("a payload that is no object", ["unresolved"], False)):
        check_eq(f"K1 reader: {label}", CTRL.names_contradicts(payload), want)
    check_eq("K1 reader: its twins do not answer to the word",
             (CTRL.names_blocked({"unresolved": RED_WORD, "reason": "x"}),
              CTRL.names_handed({"unresolved": RED_WORD, "reason": "x"})), (False, False))


def k2_the_door_follows_the_outcome():
    """4b-K2 (m4): a failed instance without its block gets `RED_ROW_DOOR`, never the person's `probe gap:` word."""
    import window_record as WR
    project = temp_project("qa-red-window-4bk2-")
    use_project(project)
    try:
        story = Story(project)
        code, out, window, gaps = story.run("--review-receipt")
        check_eq("K2 control: built, exit 0", code, 0)
        bare = copy.deepcopy(window)
        item(bare, A).pop("probe_not_applicable")
        refusal = TW.accept_window(project, story.task, bare, "k2-red")
        text = blob(refusal)
        check("K2: a failed instance with no block is refused", refusal.returncode != 0, text[:300])
        check_in("K2: the shape names it", f"{A}: {C.PROBE_MISSING_ERROR}", text)
        check_in("K2/m4: the door is the one text of the row road", WR.RED_ROW_DOOR, text)
        check_not_in("K2/m4: and never the person's word for a probe", C.PROBE_GAP_MATCH_PREFIX, text)
        check_not_in("K2/m4: nor a waiver", "waiver.py", text)
        check_not_in("K2: the marker is not named", "qa_unresolved", text)
        # control: the same refusal for an instance that ran GREEN keeps the person's door, as today
        code, out, green, gaps = story.run(blocks={BLOCK_A: lambda p: set_run(p, "passed")})
        refusal = TW.accept_window(project, story.task, green, "k2-green")
        text = blob(refusal)
        check_in("K2 control: a green instance without a probe is refused", f"{A}: {C.PROBE_MISSING_ERROR}", text)
        check_in("K2 control: with the probe gap door", C.PROBE_GAP_MATCH_PREFIX, text)
        check_not_in("K2 control: and not the red road", WR.RED_ROW_DOOR, text)
        # both at once: the green one keeps its door and the red one gets its own
        mixed = copy.deepcopy(window)
        item(mixed, A).update(outcome="passed")
        item(mixed, A).pop("probe_not_applicable")
        item(mixed, B).pop("probe_not_applicable")
        text = blob(TW.accept_window(project, story.task, mixed, "k2-mixed"))
        check_in("K2 mixed: the green one's door", C.PROBE_GAP_MATCH_PREFIX, text)
        check_in("K2 mixed: and the red one's, naming it", f"For {B} (ran red): {WR.RED_ROW_DOOR}", text)
    finally:
        cleanup(project)


def code_review(task: Path) -> list:
    return CTRL.Controller(task)._code_review_problems(FINDINGS)


def unproven_in(problems: list) -> str:
    return " ".join(p for p in problems if "no sensitivity proof" in p)


def k3_the_critic_asks_no_probe_of_a_red_test():
    """4b-K3 (m2): item 3 of the receipts exempts a red test its row explains, and only while it is red."""
    project = temp_project("qa-red-window-4bk3-")
    use_project(project)
    real = AC.red_by_requirement
    try:
        story = Story(project)
        code, out, window, gaps = story.run("--review-receipt")
        check_eq("K3 control: built, exit 0", code, 0)
        check_eq("K3: both tests are new_or_changed with no sensitivity_proof, and every receipt is there",
                 code_review(story.task), [])
        # reader raised -> no exemption (FR-59: the refusal stands)
        def raising(*args, **kwargs):
            raise RuntimeError("the reader fell over")
        AC.red_by_requirement = raising
        try:
            owed = unproven_in(code_review(story.task))
        finally:
            AC.red_by_requirement = real
        check_in("K3/m2: the reader raised: A is unproven", A, owed)
        check_in("K3/m2: and B", B, owed)
        # reader answered {} -> no exemption
        AC.red_by_requirement = lambda *args, **kwargs: {}
        try:
            owed = unproven_in(code_review(story.task))
        finally:
            AC.red_by_requirement = real
        check_in("K3/m2: the reader answered {}: A is unproven", A, owed)
        check_in("K3/m2: and B", B, owed)
        # the exemption is the reader's, one call: a green test with a row owes its proof
        code, out, green, gaps = story.run("--review-receipt", blocks={BLOCK_A: lambda p: set_run(p, "passed")})
        owed = unproven_in(code_review(story.task))
        check_in("K3: a past red that went green owes its proof", A, owed)
        check_not_in("K3: the red sibling does not", B, owed)
        # the row retracted: no red escapes the word without its own record
        code, out, window, gaps = story.run(
            "--review-receipt", edit=lambda m: m.update(unresolved=[row_of("TC-2", [B])]))
        owed = unproven_in(code_review(story.task))
        check_in("K3: a red whose row was retracted owes its proof", A, owed)
        check_not_in("K3: the one with its row does not", B, owed)
        # a reason for the absence is a reason as before, with or without the exemption
        code, out, window, gaps = story.run(
            "--review-receipt", edit=lambda m: (m.update(unresolved=[row_of("TC-2", [B])]),
                                                 m["tests"][0].update(sensitivity_proof_missing_reason="tool stopped")))
        check_not_in("K3: a recorded reason still passes", A, unproven_in(code_review(story.task)))
    finally:
        AC.red_by_requirement = real
        cleanup(project)


def k3b_a_red_of_another_window_is_exempt_too():
    """4b-K3b (m5): window 2 holds red B; test A, red in window 1, stays in the manifest with no proof. The
    exemption is the manifest-wide current red, not the instances of the window under acceptance."""
    project = temp_project("qa-red-window-4bk3b-")
    use_project(project)
    try:
        story = Story(project)
        code, out, window, gaps = story.run("--review-receipt")
        check_eq("K3b window 1: A and B red with their rows, exit 0", code, 0)
        second = copy.deepcopy(window)   # window 2: B alone; A is not an instance of it
        second["instances"] = [i for i in second["instances"] if i["instance_id"] == B]
        second["scope_instances"] = {case: ids for case, ids in second["scope_instances"].items() if B in ids}
        check_eq("K3b: A is not in window 2", [i["instance_id"] for i in second["instances"]], [B])
        p = {**FINDINGS, "window": second}
        check_eq("K3b/m5: _code_review_problems is empty with A red in the manifest and absent from the window",
                 CTRL.Controller(story.task)._code_review_problems(p), [])
        # control: A's row retracted -> window 2 refused "not receipted ... A"
        code, out, window, gaps = story.run(
            "--review-receipt", edit=lambda m: m.update(unresolved=[row_of("TC-2", [B])]))
        problems = CTRL.Controller(story.task)._code_review_problems(p)
        owed = unproven_in(problems)
        check_in("K3b control: window 2 is not receipted", "the qa-code-critic window is not receipted: ", owed)
        check_in("K3b control: and A is the one named", A, owed)
        check_not_in("K3b control: not B", B, owed)
    finally:
        cleanup(project)


def k4_finish_derives_the_pair():
    """4b-K4 (m3): `contradicts_requirement` is a kind `finish` derives by itself; `product:` stays undeclared."""
    import story_step as SS
    check_in("K4: the kind is declared", RED_WORD, SS.DERIVED_GAP_KINDS)
    check_not_in("K4: `product` is not (a red nobody explained is the author's repair)", "product", SS.DERIVED_GAP_KINDS)
    check_eq("K4: the three kinds before it are kept", SS.DERIVED_GAP_KINDS[:3],
             ("blocked_by_env", "handed_to_person", "probe_gap"))
    shown = "work/windows/" + TW.CRITIC + ".json"
    red_only = SS._derived_pair([f"{RED_WORD}:{A}", f"{RED_WORD}:{B}"], shown)
    check_eq("K4: a window of reds gives the word", red_only[0], RED_WORD)
    check_in("K4: and the instances in the reason", f"{RED_WORD}:{A}; {RED_WORD}:{B}", red_only[1])
    both = [f"{RED_WORD}:{A}", f"handed_to_person:{B}"]
    word, reason = SS._derived_pair(both, shown)
    check_eq("K4: red + handed: the word is the first kind in sorted order", word, RED_WORD)
    check("K4: and the head names both kinds", reason.startswith(f"{RED_WORD}, handed_to_person; full list: {shown}"), reason)
    pair = {"unresolved": word, "reason": reason}
    check("K4: the controller reads handed_to_person in it", CTRL.names_handed(pair))
    check("K4: and contradicts_requirement", CTRL.names_contradicts(pair))
    # not cut at a reason over the limit: long ids push the list past 300, the head stays whole
    many = [f"{RED_WORD}:test_long_instance_name_{n:02d}[parametrized-{n:02d}]" for n in range(12)] + [f"handed_to_person:{B}"]
    word, reason = SS._derived_pair(many, shown)
    check(f"K4 limit: the list is over {SS.WINDOW_REASON_LIMIT}", len("; ".join(many)) > SS.WINDOW_REASON_LIMIT)
    check_eq("K4 limit: the reason is cut at the limit", len(reason), SS.WINDOW_REASON_LIMIT)
    check("K4 limit: the head is not cut", reason.startswith(f"{RED_WORD}, handed_to_person; full list: {shown}; "), reason)
    pair = {"unresolved": word, "reason": reason}
    check("K4 limit: names_handed still true", CTRL.names_handed(pair))
    check("K4 limit: names_contradicts still true", CTRL.names_contradicts(pair))
    # a gap of any other kind in the window derives nothing
    check_eq("K4: a red beside a product gap derives nothing", SS._derived_pair([f"{RED_WORD}:{A}", f"product:{B}"], shown), ())
    check_eq("K4: a red beside a sensitivity gap derives nothing",
             SS._derived_pair([f"{RED_WORD}:{A}", f"sensitivity:{B}"], shown), ())


def k5_the_chain_to_stage_done():
    """4b-K5 (m3): window -> `finish` -> accepted -> `stage_done --status done` S5, exit 0, no word of a person."""
    project = temp_project("qa-red-window-4bk5-")
    use_project(project)
    try:
        story = Story(project)
        before = overrides(story.task)
        code, out, window, gaps = story.run("--review-receipt")
        check_eq("K5 chain: the window exits 0", code, 0)
        done = TB.finish_cli(project, story.task)
        text = blob(done)
        check_eq("K5 chain: story_step finish exits 0", done.returncode, 0)
        check_in("K5 chain: and says it accepted the critic", "accepted " + TW.CRITIC, text)
        state = CTRL.Controller(story.task).state()
        record = state["dispatches"][TW.CRITIC]
        check_eq("K5 chain: the dispatch is accepted and S5 completed",
                 (record["status"], state["stages"]["S5"]["status"]), ("accepted", "completed"))
        check_eq("K5 chain: `unresolved` is the word", record.get("unresolved"), RED_WORD)
        check("K5 chain: the reason names both instances", A in str(record.get("reason")) and B in str(record.get("reason")),
              str(record.get("reason")))
        stage = harness.run_script("stage_done.py", "--task", TW.TICKET, "--stage", "S5", "--status", "done",
                              "--digest", "qa-code-critic S5 done", cwd=project)
        check_eq("K5 chain: stage_done --status done S5 exits 0", stage.returncode, 0)
        check_eq("K5 chain: no word of a person anywhere on the way", overrides(story.task), before)
    finally:
        cleanup(project)


def k9_the_exit_of_a_red_window():
    """4b-K9 (AR-25): the walk names how a story leaves a window accepted as unresolved with the red word."""
    text = (harness.PLUGIN_ROOT / "design/state-exits.md").read_text(encoding="utf-8")
    row = next((ln for ln in text.splitlines() if ln.startswith("| an S5 window accepted as `unresolved` with `contradicts_requirement`")), "")
    check("K9: the walk has the row", bool(row))
    for needle in ("probe_not_applicable", "story_step.py finish", "controller rework", "CASE_DEFECT", "APP_BUG",
                   "test_red_window.py"):
        check_in(f"K9: the row names {needle}", needle, row)


def main():
    k5_the_end_to_end()
    k5b_a_receipt_on_the_red_instance_is_not_taken()
    k6_the_battery()
    k1_the_pair_must_name_the_word()
    k1_the_reader_and_its_twin()
    k2_the_door_follows_the_outcome()
    k3_the_critic_asks_no_probe_of_a_red_test()
    k3b_a_red_of_another_window_is_exempt_too()
    k4_finish_derives_the_pair()
    k5_the_chain_to_stage_done()
    k9_the_exit_of_a_red_window()
    finish("red window")


if __name__ == "__main__":
    main()
