#!/usr/bin/env python3
"""One test, three cases, one red assert: what the S5 precheck says about it (HF2-3, GW1-22; spec t-085 rev. 3, part 3a2).

TP1-12586 (22-24.10.2026): the msteams test covers TC-004, TC-005 and TC-006 and stops at TC-004's Then 2, so the
Thens of TC-005 and TC-006 that stand after it never ran. The precheck read the whole case as the unit (a green generic
instance of TC-005 made the stale partition row `partial-green`) and had no word for a Then behind a red assert.
Now the unit is the (Then, instance) pair (AR-26): a green is compared with the instances and partitions of ITS row, a
`blocked_by_check` Then is judged without a person's word, and the ONE reader of red is `acceptance.red_by_requirement`
(AR-13, structural mode). Fixtures: `test_mixed_then_outcomes` (3a1), reused, not copied.

Keys: K1 the contradicts branch (but-green / no-instance / blocked-check-row / never partial-green), K2 uncovered-partition,
K3 the no-assert skip (and the N4 guard), K4 the blocked Then (labels, no word), K5 the four shapes by exact id sets,
K6 red-links-unbound, K7 FR-1 doors (no marker) and the census, K9 red-two-cases, K10 the `then-remainder-all` literal,
plus the edges (legacy stories silent, garbage does not crash, a scoped dispatch).
"""
import ast
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import contract as C  # noqa: E402
import s5_precheck as S  # noqa: E402
from test_mixed_then_outcomes import (CASES, G5, G6, MS, _blocked, _covered, shape_a as raw_shape_a,  # noqa: E402
                                      shape_b as raw_shape_b, with_stale_rows)

SOURCE = Path(S.__file__)
TASK = Path("QA-12586")
ROAD = "manifest_put.py --task <TICKET> --fragment <file>"
RETRACT_5 = 'retracted_unresolved: ["TC-005"]'


def pinned(story: dict) -> dict:
    """R5 (t-1508, t-1532 F3): the msteams test stops at TC-004's Then 2. The fixtures give both Thens of TC-004 ONE shared
    range (`tests/test_move.py:10-30`), the live shape that R5 names `red-own-order-unknown` (the order is not established).
    The keys below are not about that order, so they pin Then 1 before the red Then 2 (lines 11-13 and 14-16), the way a
    marker `then={1: "11-13", 2: "14-16"}` would. `test_mixed_then_outcomes` is untouched: its key pins today's values."""
    out = copy.deepcopy(story)
    for b in out["manifest"]["then_bindings"]:
        if (b["case"], b["instance_id"], b["then"]) in (("TC-004", MS, 1), ("TC-004", MS, 2)):
            b["assertion_ref"] = f"tests/test_move.py:{'11-13' if b['then'] == 1 else '14-16'}"
    return out


def shape_a(refs: str = "default") -> dict:
    return pinned(raw_shape_a(refs))


def shape_b(refs: str = "default") -> dict:
    return pinned(raw_shape_b(refs))


def run_all(story: dict, cases=CASES) -> list:
    """Every finding of the three checks this part owns, for the cases of `story` (the families `manifest`, `bindings`)."""
    manifest, findings, notes = story["manifest"], [], []
    S.check_manifest(manifest, list(cases), findings)
    for case in cases:
        S.check_bindings(manifest, case, story["texts"][case], [], [], findings)
    S.check_then_remainders(TASK, manifest, list(cases), story["texts"], findings, notes)
    return findings


def ids(findings: list) -> set:
    return {f["id"] for f in findings}


def one(findings: list, finding_id: str) -> dict:
    return next((f for f in findings if f["id"] == finding_id), {"message": "", "fix": "", "level": ""})


def edited(story: dict, edit) -> dict:
    out = copy.deepcopy(story)
    edit(out["manifest"])
    return out


def row_of(manifest: dict, case: str, then: int, instance: str = MS) -> dict:
    return next(b for b in manifest["then_bindings"] if (b["case"], b["then"], b["instance_id"]) == (case, then, instance))


def drop_blocked(case: str):
    def edit(m):
        m["then_bindings"] = [b for b in m["then_bindings"] if not (b["case"] == case and b.get("reason") == "blocked_by_check")]
    return edit


def stale(case: str, **extra) -> dict:
    return dict({"case": case, "reason": "contradicts_requirement", "partitions": ["P-msteams"], "detail": "stale"}, **extra)


# --- K5: the four shapes, exact id sets named before the run ---------------------------------------------------------

def k5_four_shapes() -> None:
    ms_id = C.test_instance_id(shape_a()["manifest"]["tests"][0])
    check_eq("K5 fixture: the msteams instance id is the fixture's MS", ms_id, MS)
    unknown = {f"manifest:TC-004:red-own-order-unknown-{MS}-1"}
    check_eq("K5 a: shape A as the fixture is (one shared range for TC-004's Thens) -> exactly the order-unknown word for Then 1",
             ids(run_all(raw_shape_a())), unknown)
    check_eq("K5 a: ... Then 1 pinned before the red Then 2 -> no finding at all", ids(run_all(shape_a())), set())
    check_eq("K5 b: shape B as the fixture is (one shared range) -> exactly the order-unknown word for Then 1",
             ids(run_all(raw_shape_b())), unknown)
    check_eq("K5 b: ... Then 1 pinned before the red Then 2 -> no finding at all", ids(run_all(shape_b())), set())
    check_eq("K5 c: shape A + stale rows of TC-005, TC-006 -> `contradicts-no-instance` for each, no `partial-green`",
             ids(run_all(with_stale_rows(shape_a(), ["TC-005", "TC-006"]))),
             {"manifest:TC-005:contradicts-no-instance", "manifest:TC-006:contradicts-no-instance"})
    check_eq("K5 d (N1): shape B + a stale TC-005 row -> `red-two-cases` under TC-004 AND under TC-005",
             ids(run_all(with_stale_rows(shape_b(), ["TC-005"]))),
             {f"manifest:TC-004:red-two-cases-{MS}", f"manifest:TC-005:red-two-cases-{MS}"})
    check_eq("K5 d: ... and with both stale rows, three cases, three findings",
             ids(run_all(with_stale_rows(shape_b(), ["TC-005", "TC-006"]))),
             {f"manifest:{c}:red-two-cases-{MS}" for c in CASES})


# --- K1: the contradicts branch --------------------------------------------------------------------------------------

def k1_contradicts_branch() -> None:
    # a stale partition row naming the GENERIC partition: the green generic test is in its slice, the red msteams one is not
    story = edited(shape_b(), lambda m: m["unresolved"].append(stale("TC-005", partitions=["P-generic"])))
    found = run_all(story)
    check_eq("K1: a partition row, a green test of its partition -> `contradicts-but-green` (structurally the green test IS "
             "in the slice; whether it ran red is the run's word, not this check's)",
             ids(found), {"manifest:TC-005:contradicts-but-green"})
    check_not_in("K1: `partial-green` is never said for a contradicts row", "partial-green", " ".join(ids(found)))
    check_in("K1: the green sentence names the test of the slice", G5, one(found, "manifest:TC-005:contradicts-but-green")["message"])
    # a green of ANOTHER partition than the row's is not in its slice
    other = run_all(with_stale_rows(shape_a(), ["TC-005"]))
    check_not_in("K1: a green of another partition (P-generic against P-msteams) is not `contradicts-but-green`",
                 "contradicts-but-green", " ".join(ids(other)))
    # a green that declares NO partition stands for all of them: the direction of the error is the finding
    bare = edited(shape_a(), lambda m: (m["unresolved"].append(stale("TC-005")),
                                        [t.pop("partitions") for t in m["tests"] if t["instance_id"] == G5]))
    check_in("K1: a green with no partition is reached by a partition row", "manifest:TC-005:contradicts-but-green", ids(run_all(bare)))
    # a row naming an instance reaches that instance only
    named = edited(shape_b(), lambda m: m["unresolved"].append(
        {"case": "TC-005", "reason": "contradicts_requirement", "instance_ids": [MS], "thens": [1], "detail": "d"}))
    check_not_in("K1: a row that names the red instance does not reach the green one",
                 "contradicts-but-green", " ".join(ids(run_all(named))))
    # a whole-case row (no slice key): the slice is every instance of the case, as it has always been
    whole = edited(shape_b(), lambda m: m["unresolved"].append(
        {"case": "TC-005", "reason": "contradicts_requirement", "detail": "d"}))
    found = run_all(whole)
    check_eq("K1: a whole-case row beside a green sibling -> `contradicts-but-green`, the sentence unchanged",
             one(found, "manifest:TC-005:contradicts-but-green")["message"],
             "TC-005 is `green` while its unresolved[] row says contradicts_requirement — a test that passes does not "
             "prove the code contradicts the requirement")
    check_not_in("K1: ... and never `contradicts-no-instance` (that is for a row WITH a slice)",
                 "contradicts-no-instance", " ".join(ids(found)))
    # contradicts-no-instance: text, then a neighbour that has an instance behind the row
    found = run_all(with_stale_rows(shape_a(), ["TC-005"]))
    cni = one(found, "manifest:TC-005:contradicts-no-instance")
    check_eq("K1: contradicts-no-instance message (no thens -> 'a Then')", cni["message"],
             "TC-005's unresolved[] row says contradicts_requirement for partition [P-msteams], and no test in that slice "
             "binds a Then of TC-005 - a red the manifest names with no test behind it")
    check_in("K1: ... its fix names the covered binding, the retraction and the fragment road", "`then_bindings` (status covered",
             cni["fix"])
    check_in("K1: ... the retraction in the spec's spelling", RETRACT_5, cni["fix"])
    check_in("K1: ... and the road", ROAD, cni["fix"])
    check_eq("K1: ... family manifest, level repair", (cni.get("check"), cni["level"]), ("manifest", "repair"))
    named = edited(shape_a(), lambda m: m["unresolved"].append(
        {"case": "TC-005", "reason": "contradicts_requirement", "instance_ids": [MS], "thens": [1, 2], "detail": "d"}))
    check_in("K1: a row with thens names them ('Thens 1, 2' is 'Then 1, 2' in the sentence)", "binds Then 1, 2 of TC-005",
             one(run_all(named), "manifest:TC-005:contradicts-no-instance")["message"])
    check_eq("K1: the neighbour - the row has a red instance behind it (shape B, stale TC-005): no `contradicts-no-instance`",
             "manifest:TC-005:contradicts-no-instance" in ids(run_all(with_stale_rows(shape_b(), ["TC-005"]))), False)
    # a row whose slice holds no instance at all is as named as a row whose instances are green
    nobody = edited(shape_a(), lambda m: m["unresolved"].append(
        {"case": "TC-005", "reason": "contradicts_requirement", "instance_ids": ["no_such_test"], "detail": "d"}))
    check_in("K1: a slice with no instance in it -> `contradicts-no-instance`", "manifest:TC-005:contradicts-no-instance",
             ids(run_all(nobody)))
    # partial-green: the other reasons keep it, and only where the green's partition is the row's
    other_reason = lambda parts: edited(shape_a(), lambda m: m["unresolved"].append(  # noqa: E731
        {"case": "TC-005", "reason": "impossible", "partitions": parts, "detail": "d"}))
    check_in("K1: another reason, a partition a green test runs -> `partial-green`", "manifest:TC-005:partial-green",
             ids(run_all(other_reason(["P-generic"]))))
    check_not_in("K1: another reason, a partition no green test runs -> no `partial-green`", "partial-green",
                 " ".join(ids(run_all(other_reason(["P-msteams"])))))
    check_in("K1: ... the same partition spelled without `P-` is the same partition (partition_key)", "partial-green",
             " ".join(ids(run_all(other_reason(["generic"])))))
    # blocked-check-row
    row = edited(shape_a(), lambda m: m["unresolved"].append(
        {"case": "TC-005", "reason": "blocked_by_check", "detail": "waits"}))
    found = run_all(row)
    bcr = one(found, "manifest:TC-005:blocked-check-row")
    check_eq("K1: blocked-check-row message", bcr["message"],
             "TC-005's unresolved[] row says blocked_by_check; that reason belongs to a Then, not to a whole case")
    check_in("K1: ... its fix retracts the row and sends the Thens through the road", RETRACT_5, bcr["fix"])
    check_in("K1: ... the road", ROAD, bcr["fix"])
    check_in("K1: ... and the shape of the row it asks for", "blocking_check, detail}", bcr["fix"])
    check_not_in("K1: ... not also read as `both-lists`", "both-lists", " ".join(ids(found)))
    check_eq("K1: the neighbour - shape A has no such row", "manifest:TC-005:blocked-check-row" in ids(run_all(shape_a())), False)


# --- K2: uncovered-partition -----------------------------------------------------------------------------------------

CASE_TEXT = ("---\nid: TC-9\nstatus: Approved\n---\n## Then\n1. The call returns `status_ok` for P-ok.\n"
             "2. P-warn returns the `warnings` list.\n")


def k2_uncovered_partition() -> None:
    def partition_story(green_partitions, reason="impossible", row_partitions=("P-warn",)):
        test = {"instance_id": "test_nine", "file": "tests/test_nine.py", "covers": ["TC-9"], "status": "green"}
        if green_partitions is not None:
            test["partitions"] = list(green_partitions)
        manifest = {"tests": [test],
                    "unresolved": [{"case": "TC-9", "reason": reason, "partitions": list(row_partitions), "detail": "d"}],
                    "then_bindings": [_covered("TC-9", n, "test_nine", "tests/test_nine.py:3-9") for n in (1, 2)]}
        findings: list = []
        S.check_bindings(manifest, "TC-9", CASE_TEXT, [], [], findings)
        return ids(findings)

    want = "bindings:TC-9:uncovered-partition-2"
    check_in("K2: a green test with no partition covers the partition the row leaves open -> finding", want, partition_story(None))
    check_in("K2: ... a green test that runs that very partition -> finding", want, partition_story(["P-warn"]))
    check_not_in("K2: ... a green test of ANOTHER partition does not cover it -> no finding", "uncovered-partition",
                 " ".join(partition_story(["P-ok"])))
    check_not_in("K2: ... a `contradicts_requirement` row is a red test's row, not an uncovered partition",
                 "uncovered-partition", " ".join(partition_story(None, reason="contradicts_requirement")))
    check_in("K2: ... the row's `warn` is the clause's `P-warn` (partition_key)", want, partition_story(None, row_partitions=("warn",)))
    check_not_in("K2: ... a Then that names no open partition is not named", "uncovered-partition-1", " ".join(partition_story(None)))
    # the 12586 stale rows: TC-005's Then rests on no partition here, but the shape must stay silent whatever the clause says
    found = run_all(with_stale_rows(shape_b(), ["TC-005", "TC-006"]))
    check_not_in("K2: the 12586 shapes never say uncovered-partition", "uncovered-partition", " ".join(ids(found)))


# --- K3: the no-assert skip ------------------------------------------------------------------------------------------

def k3_no_assert_skip() -> None:
    root = temp_dir("qa-mixed-pre-")
    try:
        code = root / "test_nine.py"
        code.write_text('def test_nine(client):\n    assert client is not None\n', encoding="utf-8")
        parsed, problem = S.read_python(code)
        check("K3 fixture: the test file parses", parsed is not None and not problem, str(problem))
        text = ("---\nid: TC-9\nstatus: Approved\n---\n## Then\n1. The call returns `status_ok`.\n"
                "2. The page shows `flux_capacitor_value`.\n")

        def no_assert(extra_rows=(), extra_unresolved=()):
            manifest = {"tests": [{"instance_id": "test_nine", "file": "test_nine.py", "covers": ["TC-9"], "status": "red"}],
                        "then_bindings": [_covered("TC-9", 1, "test_nine", "test_nine.py:1-2"), *extra_rows],
                        "unresolved": list(extra_unresolved)}
            findings: list = []
            S.check_bindings(manifest, "TC-9", text, [parsed], [], findings)
            return ids(findings)

        want = "bindings:TC-9:no-assert-2"
        remainder = {"case": "TC-9", "then": 2, "instance_id": None, "assertion_ref": None, "status": "unresolved",
                     "detail": "d"}
        check_in("K3: nothing recorded for Then 2 -> `no-assert-2`", want, no_assert())
        check_not_in("K3: Then 2 left with its owner -> skipped (as before)", want,
                     " ".join(no_assert([dict(remainder, reason="handed_to_person", owner="person")])))
        check_not_in("K3: Then 2 behind a red check -> skipped", want,
                     " ".join(no_assert([dict(remainder, reason="blocked_by_check", blocking_check="TC-4", instance_id="test_nine")])))
        check_in("K3 (N4 guard): a `contradicts_requirement` row that names Then 2 grants no skip", want,
                 no_assert(extra_unresolved=[{"case": "TC-9", "reason": "contradicts_requirement", "thens": [2],
                                              "instance_ids": ["test_nine"], "detail": "d"}]))
        # 5a-K4: `blocked_by_env` is in UNRESOLVED_REASONS and now skips; the control is a word OUTSIDE the closed list
        check_in("K3: a row of an unknown reason on Then 2 grants no skip here either", want,
                 no_assert([dict(remainder, reason="gone_fishing")]))
        check_in("K3: a blocked row for Then 1 does not skip Then 2", want,
                 no_assert([dict(remainder, then=1, reason="blocked_by_check", blocking_check="TC-4")]))
    finally:
        cleanup(root)


# --- K4: the blocked Then without a person's word --------------------------------------------------------------------

def k4_blocked_then() -> None:
    def with_row(edit_row, case="TC-005", then=1):
        def edit(m):
            edit_row(next(b for b in m["then_bindings"] if (b["case"], b["then"], b.get("reason")) == (case, then, "blocked_by_check")))
        return edited(shape_a(), edit)

    base = run_all(shape_a())
    check_eq("K4: well-formed blocked rows of a red blocker -> nothing, and no `unrecorded` wait for a word", ids(base), set())
    notes: list = []
    S.check_then_remainders(TASK, shape_a()["manifest"], list(CASES), shape_a()["texts"], [], notes)
    check_eq("K4: ... and no note about a person's words", notes, [])

    def labels(story):
        return ids(run_all(story))

    bad = with_row(lambda r: r.pop("blocking_check"))
    got = run_all(bad)
    check_in("K4: no `blocking_check` -> `then-remainder-shape-1`", "bindings:TC-005:then-remainder-shape-1", ids(got))
    shape = one(got, "bindings:TC-005:then-remainder-shape-1")
    check_in("K4: ... it says what is wrong, in the blocked row's words (not 'left with its owner')", "behind a red check is malformed",
             shape["message"])
    check_in("K4: ... the door is the corrected `then_bindings` rows through the road", "send the corrected `then_bindings` rows of TC-005 "
             f"through `{ROAD.replace('<TICKET>', TASK.name)}`", shape["fix"])
    check_not_in("K4: ... the shape door never names the marker", "qa_unresolved", shape["fix"])
    check_in("K4: an owner on a blocked row -> shape", "bindings:TC-005:then-remainder-shape-1", labels(with_row(lambda r: r.update(owner="person"))))
    check_in("K4: an empty detail -> shape", "bindings:TC-005:then-remainder-shape-1", labels(with_row(lambda r: r.update(detail=" "))))
    check_in("K4: a blocker with a space -> shape", "bindings:TC-005:then-remainder-shape-1",
             labels(with_row(lambda r: r.update(blocking_check="TC 4"))))
    check_in("K4: an instance_id that is no string -> shape", "bindings:TC-005:then-remainder-shape-1",
             labels(with_row(lambda r: r.update(instance_id=7))))
    for label, value in (("a list", [1]), ("a bool", True), ("a float", 1.0), ("a string", "1"), ("None", None), ("zero", 0)):
        got = labels(with_row(lambda r, v=value: r.update(then=v)))
        check(f"K4: `then` is {label} -> a refusal, not a crash", any(i.startswith("bindings:TC-005:then-remainder-shape-") for i in got)
              or any(i.startswith("bindings:TC-005:") for i in got), str(sorted(got)))
    check_in("K4: a Then the case does not have -> `then-remainder-unknown-3`", "bindings:TC-005:then-remainder-unknown-3",
             labels(with_row(lambda r: r.update(then=3))))
    unknown = run_all(with_row(lambda r: r.update(blocking_check="TC-099")))
    check_in("K4: a blocker no case or test is called -> `blocked-check-unknown-1`", "bindings:TC-005:blocked-check-unknown-1", ids(unknown))
    check_eq("K4: ... message", one(unknown, "bindings:TC-005:blocked-check-unknown-1")["message"],
             "Then 1 of TC-005 is recorded behind TC-099, and no case or test of this manifest is called that")
    check_in("K4: ... fix", "correct `blocking_check` to the case key or the instance id of the red check and send the corrected "
             "`then_bindings` rows of TC-005 through", one(unknown, "bindings:TC-005:blocked-check-unknown-1")["fix"])
    notred = run_all(with_row(lambda r: r.update(blocking_check="TC-006")))
    check_in("K4: a blocker case with no red -> `blocked-check-not-red-1`", "bindings:TC-005:blocked-check-not-red-1", ids(notred))
    check_eq("K4: ... message", one(notred, "bindings:TC-005:blocked-check-not-red-1")["message"],
             "Then 1 of TC-005 is recorded behind TC-006, which is not red here")
    check_in("K4: ... fix names the stand door and the road", "`blocked_by_env` if a stand stopped it",
             one(notred, "bindings:TC-005:blocked-check-not-red-1")["fix"])
    check_in("K4: a blocker TEST that is green -> not red", "bindings:TC-005:blocked-check-not-red-1",
             labels(with_row(lambda r: r.update(blocking_check=G5))))
    check_eq("K4: ... a blocker TEST that is red (the msteams test) -> no finding", labels(with_row(lambda r: r.update(blocking_check=MS))), set())
    conflict = edited(shape_a(), lambda m: m["then_bindings"].append(_covered("TC-005", 1, MS, "tests/test_move.py:10-30")))
    got = run_all(conflict)
    check_in("K4: the same Then covered on the SAME instance -> `then-remainder-conflict-1`", "bindings:TC-005:then-remainder-conflict-1", ids(got))
    check_eq("K4: ... message", one(got, "bindings:TC-005:then-remainder-conflict-1")["message"],
             f"Then 1 of TC-005 is both proved by {MS} and recorded on {MS} as behind TC-004")
    check_eq("K4: ... the neighbour: covered on ANOTHER instance (the generic test) is the normal state of shape A",
             "then-remainder-conflict" in " ".join(ids(base)), False)
    nulled = edited(shape_a(), lambda m: [b.update(instance_id=None) for b in m["then_bindings"] if b.get("reason") == "blocked_by_check"])
    check_eq("K4: a blocked row with instance_id null is valid as a Then (no instance to conflict with, no word asked)",
             {i for i in ids(run_all(nulled)) if i.startswith("bindings:")}, set())
    check_eq("K4: ... but it is no row ON the red test, so K6 still says nothing tells what became of the Thens there",
             {i for i in ids(run_all(nulled)) if i.startswith("manifest:")},
             {"manifest:TC-005:red-links-unbound", "manifest:TC-006:red-links-unbound"})
    # the whole-case rule counts the Thens left with their owner only
    all_blocked = edited(shape_a(), lambda m: m.update(then_bindings=[
        b for b in m["then_bindings"] if not (b["case"] == "TC-005" and b["instance_id"] == G5)]))
    check_eq("K4: every Then of TC-005 only blocked (nothing covers one) is no whole-case hand-off: no `then-remainder-all`",
             [i for i in ids(run_all(all_blocked)) if "TC-005" in i], [])
    # a whole-case unresolved row keeps today's meaning: the per-clause blocked rows are not judged
    whole = edited(shape_a(), lambda m: m["unresolved"].append({"case": "TC-006", "reason": "handed_to_person", "detail": "d"}))
    check_not_in("K4: a case with a whole-case row is not judged for its Then rows", "TC-006:blocked-check", " ".join(ids(run_all(whole))))


# --- K6: red-links-unbound --------------------------------------------------------------------------------------------

def k6_red_links_unbound() -> None:
    lost = edited(shape_a(), drop_blocked("TC-006"))
    got = run_all(lost)
    check_eq("K6: shape A without the blocked rows of TC-006 -> exactly `red-links-unbound` under TC-006", ids(got),
             {"manifest:TC-006:red-links-unbound"})
    check_eq("K6: message", one(got, "manifest:TC-006:red-links-unbound")["message"],
             f"{MS} is red for TC-004 and covers TC-006, and nothing says what happens to TC-006's Thens on it")
    fix = one(got, "manifest:TC-006:red-links-unbound")["fix"]
    check_in("K6: fix names the road", ROAD, fix)
    check_in("K6: ... and says a later writer run keeps hand-sent rows unless it writes the same Then of the same test",
             "a later `manifest_from_tests.py` run keeps them unless it writes the same Then of the same test itself", fix)
    check_not_in("K6: ... and no longer says the writer drops them until HF2-12", "HF2-12", fix)
    check_not_in("K6: ... and never the marker", "qa_unresolved", fix)
    check_eq("K6: a writer re-run that drops every hand-sent row -> TC-005 and TC-006 both",
             ids(run_all(edited(lost, drop_blocked("TC-005")))),
             {"manifest:TC-005:red-links-unbound", "manifest:TC-006:red-links-unbound"})
    check_eq("K6: neighbour - shape B (the Thens are covered on the red test) -> none", ids(run_all(shape_b())), set())
    only_one = edited(lost, lambda m: m["then_bindings"].append(_blocked("TC-006", 1)))
    check_eq("K6: neighbour - ONE blocked row of TC-006 on the red test is something said about it -> none", ids(run_all(only_one)), set())
    other = edited(lost, lambda m: m["then_bindings"].append(_blocked("TC-006", 1) | {"instance_id": G6}))
    check_in("K6: ... a blocked row on ANOTHER instance says nothing about the red one", "manifest:TC-006:red-links-unbound",
             ids(run_all(other)))
    quiet = edited(lost, lambda m: m["unresolved"].__setitem__(0, dict(m["unresolved"][0], instance_ids=[G5])))
    check_not_in("K6: neighbour - the red instance is not red by any row (the row names another test) -> none",
                 "red-links-unbound", " ".join(ids(run_all(quiet))))
    check_not_in("K6: neighbour - the case that owns the row is never 'unbound' by it", "manifest:TC-004:red-links-unbound",
                 " ".join(ids(run_all(lost))))


# --- K9: red-two-cases ------------------------------------------------------------------------------------------------

def k9_red_two_cases() -> None:
    story = with_stale_rows(shape_b(), ["TC-005"])
    got = run_all(story)
    f4, f5 = one(got, f"manifest:TC-004:red-two-cases-{MS}"), one(got, f"manifest:TC-005:red-two-cases-{MS}")
    msg = (f"{MS} is red, and the unresolved[] rows of TC-004 and TC-005 each say contradicts_requirement for it - a test "
           "stops at its first failing assert, so only one of these cases' Thens failed and the others never ran")
    check_eq("K9: message (one text under both cases)", (f4["message"], f5["message"]), (msg, msg))
    check_eq("K9: one fix text under both cases", f4["fix"], f5["fix"])
    check_in("K9: the fix keeps the row of the failing case, retracts the other (the door of 3b)", 'retract every other row with '
             '`retracted_unresolved: ["<case>"]`', f4["fix"])
    check_in("K9: ... records the Thens behind it", "as `blocked_by_check` with `blocking_check: \"<kept case>\"`", f4["fix"])
    check_in("K9: ... one fragment through the road", ROAD, f4["fix"])
    check_not_in("K9: ... never the marker", "qa_unresolved", f4["fix"])
    check_eq("K9: family manifest, level repair; a word passes only the families of PASSABLE (manifest is not one)",
             (f4["check"], f4["level"], "manifest" in S.PASSABLE), ("manifest", "repair", False))
    three = run_all(with_stale_rows(shape_b(), ["TC-005", "TC-006"]))
    check_in("K9: three cases -> 'TC-004, TC-005 and TC-006'", "rows of TC-004, TC-005 and TC-006 each say",
             one(three, f"manifest:TC-006:red-two-cases-{MS}")["message"])
    # a second row with `thens` that no binding of the instance reaches does not make it red for that case
    unbound = edited(shape_b(), lambda m: (m["unresolved"].append(
        {"case": "TC-005", "reason": "contradicts_requirement", "partitions": ["P-msteams"], "thens": [3], "detail": "d"})))
    got = ids(run_all(unbound))
    check_not_in("K9: two cases, one row with `thens` that bind nothing -> no `red-two-cases`", "red-two-cases", " ".join(got))
    check_in("K9: ... that row has no test behind it", "manifest:TC-005:contradicts-no-instance", got)
    check_eq("K9: a dispatch of TC-004 alone still hears it, under TC-004 only",
             ids(run_all(story, cases=("TC-004",))) & {i for i in ids(run_all(story)) if "red-two-cases" in i},
             {f"manifest:TC-004:red-two-cases-{MS}"})
    # the stale row retracted (3b), the other case's Thens recorded as blocked -> the shape is silent again
    def retract_and_block(m):
        m["unresolved"] = [u for u in m["unresolved"] if u["case"] != "TC-005"]
        m["then_bindings"] = [b for b in m["then_bindings"] if not (b["case"] == "TC-005" and b["instance_id"] == MS)]
        m["then_bindings"] += [_blocked("TC-005", 1), _blocked("TC-005", 2)]

    fixed = edited(story, retract_and_block)
    check_eq("K9: neighbour - one row kept, the other retracted, its Thens `blocked_by_check` -> nothing", ids(run_all(fixed)), set())


# --- K7: FR-1 doors and the census; K10: the literal -----------------------------------------------------------------

def _function_sources() -> dict:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    lines = SOURCE.read_text(encoding="utf-8").splitlines()
    return {n.name: "\n".join(lines[n.lineno - 1:n.end_lineno]) for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


def k7_doors_and_census() -> None:
    sources = _function_sources()
    new_functions = ("_road", "_slice_words", "_row_thens", "_distinct_cases", "_greens_in_slice", "_check_contradicts_row",
                     "_check_red_rows", "_blocker_state", "_check_blocked_then")
    check_eq("K7 census: the functions of this part exist", [n for n in new_functions if n not in sources], [])
    check_eq("K7 census: none of them names the marker `qa_unresolved`", [n for n in new_functions if "qa_unresolved" in sources[n]], [])
    text = SOURCE.read_text(encoding="utf-8")
    check_eq("K7 census: the marker is named by three lines of the file - the `partial-green` door, the handed-row shape door and the open-oracle door (TQ1-1)",
             sorted(n for n, body in sources.items() if "qa_unresolved" in body), ["_open_oracle_door", "check_manifest", "check_then_remainders"])
    check_eq("K7 census: ... and by no other line (no comment, no constant)", text.count("qa_unresolved"), 3)
    check("K7 control: the same grep form finds the road (the constant carries the spec's text)",
          "manifest_put.py --task <T> --fragment" in text)
    every = " ".join(f["fix"] + f["message"] for f in run_all(with_stale_rows(shape_b(), ["TC-005"]))
                     + run_all(with_stale_rows(shape_a(), ["TC-005", "TC-006"])) + run_all(edited(shape_a(), drop_blocked("TC-006"))))
    check_not_in("K7: no finding of the family prints the marker", "qa_unresolved", every)
    check_in("K7: a door of check_then_remainders carries the task's name where the root is known",
             "manifest_put.py --task QA-12586 --fragment <file>",
             one(run_all(edited(shape_a(), lambda m: m["then_bindings"][4].pop("detail"))), "bindings:TC-005:then-remainder-shape-1")["fix"])
    check_in("K7: ... and check_manifest, which is given no root, prints `<TICKET>`", ROAD,
             one(run_all(with_stale_rows(shape_a(), ["TC-005"])), "manifest:TC-005:contradicts-no-instance")["fix"])


def k10_the_literal_and_the_handed_default() -> None:
    sources = _function_sources()
    check_not_in("K10: the literal 'then-remainder-all' is gone from check_then_remainders", '"then-remainder-all"',
                 sources["check_then_remainders"])
    check_in("K10: ... it is built from the contract's tag", 'THEN_REMAINDER_TAG + "all"', sources["check_then_remainders"])
    handed = {"case": "TC-004", "then": 1, "instance_id": None, "assertion_ref": None, "status": "unresolved",
              "reason": "handed_to_person", "owner": "person", "detail": "d"}
    story = edited(shape_b(), lambda m: m.update(then_bindings=[handed, dict(handed, then=2)],
                                                 unresolved=[], tests=m["tests"]))
    found = run_all(story, cases=("TC-004",))
    check_in("K10: the id is byte for byte what it was", "bindings:TC-004:then-remainder-all", ids(found))
    check_in("K10: ... and a handed Then still waits for the person's word (unrecorded-1)", "bindings:TC-004:then-remainder-unrecorded-1", ids(found))
    check_in("K10: ... conflicts keep their id", "bindings:TC-004:then-remainder-conflict-1",
             ids(run_all(edited(story, lambda m: m["then_bindings"].append(_covered("TC-004", 1, MS, "tests/test_move.py:10-30"))),
                         cases=("TC-004",))))
    check_in("K10: ... shape keeps its id", "bindings:TC-004:then-remainder-shape-1",
             ids(run_all(edited(story, lambda m: m["then_bindings"][0].update(detail="")), cases=("TC-004",))))
    check_in("K10: ... unknown keeps its id", "bindings:TC-004:then-remainder-unknown-7",
             ids(run_all(edited(story, lambda m: m["then_bindings"].append(dict(handed, then=7))), cases=("TC-004",))))
    check_eq("K10: the tag is the contract's", (S.THEN_REMAINDER_TAG, S.THEN_REMAINDER_WAITS), (C.THEN_REMAINDER_TAG, C.THEN_REMAINDER_WAITS))


# --- B-K6: the ghost of a retracted instance (HF3-2, F-4 (a)) ---------------------------------------------------------

def k6_ghost_of_a_retracted_instance() -> None:
    """TP2-2406 (26.10.2026): seq 115 retracted OLD and left its two Then rows, seq 117 re-sent OLD with no links; the
    ghost row made OLD look covered, so the Thens bound to a test that is gone were not named (`unlinked-`). `manifest_put`
    now takes the rows with the retraction and refuses the ghost; a projection written before that is NAMED here."""
    old, new = "Tests.Old.test_nine", "Tests.New.test_nine"
    refs = "tests/test_nine.py:3-9"
    live = {"instance_id": new, "file": "tests/test_nine.py", "covers": ["TC-9"], "status": "green"}
    ghost = {"instance_id": old, "case": "TC-9", "file": "tests/test_nine.py", "status": "red"}
    on_new = [_covered("TC-9", n, new, refs) for n in (1, 2)]
    on_old = [_covered("TC-9", n, old, refs) for n in (1, 2)]

    def found(manifest: dict) -> list:
        findings: list = []
        S.check_bindings(manifest, "TC-9", CASE_TEXT, [], [], findings)
        return findings

    projection_0102 = {"tests": [live, ghost], "then_bindings": on_old + on_new, "retracted_instances": [old]}
    found_0102 = found(projection_0102)
    check_eq("B-K6: the 0.10.2 projection (the ghost and the two OLD rows, no re-projection) -> one `ghost-<OLD>` finding",
             ids(found_0102), {f"bindings:TC-9:ghost-{old}"})
    finding = one(found_0102, f"bindings:TC-9:ghost-{old}")
    check_eq("B-K6: ... a repair, not a hint", finding["level"], "repair")
    check_in("B-K6: ... its door is to retract it again, as a fragment the role can send", json.dumps({"retracted_instances": [old]}),
             finding["fix"])
    check_in("B-K6: ... through the one road", "manifest_put.py --task <T> --fragment <file>", finding["fix"])
    check_in("B-K6: ... or to send the whole row with its links", "`covers` and `case_version_links`", finding["fix"])
    check_in("B-K6: ... and the message says what the row is", "ghost of an instance this manifest retracted", finding["message"])

    after = {"tests": [live], "then_bindings": on_new, "retracted_instances": [old]}
    check_eq("B-K6: the projection after HF3-2 (no ghost, no OLD rows) -> no `ghost-` and no `unlinked-`", ids(found(after)), set())
    check_not_in("B-K6: ... a ghost the fold re-projected away is not named", "ghost-", " ".join(ids(found(after))))

    unlinked = {"tests": [live], "then_bindings": on_new + [_covered("TC-9", 1, "Tests.Never.test_nine", refs)]}
    check_in("B-K6 CONTROL: a Then row on an id that was never retracted and is linked to nothing -> `unlinked-` as today",
             "bindings:TC-9:unlinked-Tests.Never.test_nine-1", ids(found(unlinked)))
    check_not_in("B-K6 CONTROL: ... and no `ghost-` for it", "ghost-", " ".join(ids(found(unlinked))))

    linked_return = {"tests": [live, dict(ghost, covers=["TC-9"])], "then_bindings": on_old + on_new, "retracted_instances": [old]}
    check_eq("B-K6 CONTROL: the retracted name sent back WITH its links is a return, not a ghost: nothing is named",
             ids(found(linked_return)), set())
    check_eq("B-K6 CONTROL: a link-less row whose spelling was never retracted is no ghost",
             {i for i in ids(found(dict(projection_0102, retracted_instances=[]))) if "ghost-" in i}, set())
    no_clause = []
    S.check_bindings(projection_0102, "TC-9", "no then section here", [], [], no_clause)
    check_eq("B-K6 edge: a case text with no Then clauses is silent as before", no_clause, [])
    for label, manifest in (("retracted_instances that is no list", dict(projection_0102, retracted_instances="x")),
                            ("tests that are no objects", dict(projection_0102, tests=[None, 3, live]))):
        try:
            found(manifest)
            crashed = ""
        except Exception as exc:
            crashed = f"{type(exc).__name__}: {exc}"
        check(f"B-K6 edge: {label} is read, not a crash", not crashed, crashed)


# --- edges ----------------------------------------------------------------------------------------------------------

def edges() -> None:
    legacy = {"manifest": {"tests": [{"case": "TC-500", "file": "t.py", "instance_id": "TC-500::test_a", "status": "green"}]},
              "texts": {"TC-500": CASE_TEXT}}
    check_eq("edge: an old story with no unresolved rows and no bindings -> none of the new findings",
             {i for i in ids(run_all(legacy, cases=("TC-500",))) if any(
                 w in i for w in ("red-two-cases", "red-links-unbound", "contradicts-no-instance", "blocked-check", "then-remainder"))},
             set())
    for label, manifest in (("an empty manifest", {}),
                            ("unresolved that is no list", {"unresolved": "x", "tests": [None, 3], "then_bindings": "y"}),
                            ("rows that are not objects", {"unresolved": [None, 5, {"case": "TC-004"}], "then_bindings": [None, "x", 3],
                                                           "tests": [{"covers": ["TC-004"]}]}),
                            ("a red row over nothing", {"unresolved": [stale("TC-004")], "tests": [], "then_bindings": []})):
        try:
            run_all({"manifest": manifest, "texts": {c: CASE_TEXT for c in CASES}})
            crashed = ""
        except Exception as exc:  # the gate refuses what it cannot read, it does not stop the factory
            crashed = f"{type(exc).__name__}: {exc}"
        check(f"edge: {label} is read, not a crash", not crashed, crashed)
    one_then = edited(shape_a(), lambda m: None)
    one_then["texts"]["TC-005"] = "---\nid: TC-005\n---\n## Then\n1. The only result is shown.\n"
    one_then["manifest"]["then_bindings"] = [b for b in one_then["manifest"]["then_bindings"]
                                             if not (b["case"] == "TC-005" and b["then"] == 2)]
    check_eq("edge: a case of ONE Then - the single blocked Then is legal", ids(run_all(one_then)), set())


def main() -> None:
    k5_four_shapes()
    k1_contradicts_branch()
    k2_uncovered_partition()
    k3_no_assert_skip()
    k4_blocked_then()
    k6_red_links_unbound()
    k9_red_two_cases()
    k7_doors_and_census()
    k10_the_literal_and_the_handed_default()
    k6_ghost_of_a_retracted_instance()
    edges()
    finish("test_mixed_then_precheck")


if __name__ == "__main__":
    main()
