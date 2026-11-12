#!/usr/bin/env python3
"""`manifest_put`: the door that takes an `unresolved[]` row away, the replacement of a re-sent row's slice, and the refusal
of two reasons for one case (HF2-3, GW1-22, FB-5; spec t-085 rev. 3, part 3b).

TP1-12586 (22-24.10.2026): the author recorded the Thens behind TC-004's red one by one (`blocked_by_check`), and the
`contradicts_requirement` row of TC-004 (and the stale partition row of TC-005) stood on, because `unresolved[]` had no way
out for a row that names a slice: a green `tests[]` entry does not take it, and a re-sent row kept the old `partitions`
beside the new `instance_ids`.

Keys: K1 the retraction, K2 send-and-retract refused, K3 a key that names no row / an already gone one, K2b the replay,
K4 two reasons refused in `run` before the commit, K4b the fold of an old event with two reasons, K8 the replacement of a
slice in two independent groups, K8b `_partition_scoped` reads the one constant. The fixtures are `test_mixed_then_outcomes`'.

HF2-5 (spec t-085 rev. 3, part 5a, K1 / K5): `then_bindings` is merged by unit and no longer replaced whole. Keys: 5a-K1 (a) the
writer's fragment replaces the array, (b) a hand fragment of blocked rows leaves the covered rows of another test of the same
case, (c) a hand fragment of one case leaves the other cases, (d) a fragment without `then_bindings` leaves the array, (e)
two handed Thens of one case (null `instance_id`): the one the hand fragment does not send is taken out and named, and with
both sent nothing is; and the replay of an old journal that holds such a hand fragment folds by the new rule.

HF3-2 (spec t-1248 part B): a retracted instance takes the `then_bindings` rows of its spelling with it, while no remaining
row wears that spelling. Keys: B-K1 the retirement and its print, B-K4 a spelling a live row still wears keeps its rows,
B-K5 a fragment that binds a Then to the id it retracts (refused by `run`, kept by `merge` on replay), B-K7 the empties.
"""
import copy
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, finish  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import acceptance as AC  # noqa: E402
import contract as C  # noqa: E402
import manifest_put as MP  # noqa: E402
from test_manifest_projection import Stand  # noqa: E402
from test_mixed_then_outcomes import G5, MS, RED_ROW, items, shape_a, shape_b, with_stale_rows  # noqa: E402

CONTRADICTS, BLOCKED = "contradicts_requirement", "blocked_by_env"
GREEN_TC9 = {"instance_id": "test_nine[x]", "file": "tests/test_nine.py", "covers": ["TC-009"], "status": "green"}


def stale_story() -> dict:
    """TC-004's row (`instance_ids: [MS]`, `thens: [2]`) and the live stale form for TC-005 (`partitions`, no `thens`)."""
    return with_stale_rows(shape_b(), ["TC-005"])["manifest"]


def cases(manifest: dict) -> list:
    return [MP._case(r) for r in manifest.get("unresolved") or []]


def row_of(manifest: dict, case: str) -> dict:
    return next(r for r in manifest.get("unresolved") or [] if MP._case(r) == case)


def refusal(fn, *args) -> str:
    try:
        fn(*args)
    except ValueError as exc:
        return str(exc)
    return ""


def journal(*fragments, seed=None) -> list:
    events = [{"type": "manifest_seed", "sequence": 1, "idempotency_key": "s", "payload": {"manifest": seed}}] if seed else []
    return events + [{"type": "manifest_patch", "sequence": len(events) + n, "idempotency_key": f"k{n}",
                      "payload": {"fragment": f}} for n, f in enumerate(fragments, 1)]


# --- K1: the retraction ----------------------------------------------------------------------------------------------

def k1_retraction() -> None:
    story = stale_story()
    merged, summary = MP.merge(copy.deepcopy(story), {"retracted_unresolved": ["TC-005"]})
    check_eq("K1: the stale partition row of TC-005 is dropped, the red one of TC-004 stays", cases(merged), ["TC-004"])
    check_eq("K1: the key joins the manifest's history", merged.get("retracted_unresolved"), ["TC-005"])
    check_eq("K1: the summary counts the rows dropped", summary.get("retracted_unresolved"), 1)
    check_eq("K1: nothing else of the manifest moved", (merged["tests"], merged["then_bindings"]),
             (story["tests"], story["then_bindings"]))
    again, _ = MP.merge(merged, {"retracted_unresolved": ["TC-004"], "run_witness": "w.json"})
    check_eq("K1: a second retraction appends to the history, and the key is not copied as a scalar",
             (cases(again), again.get("retracted_unresolved"), again.get("run_witness")), ([], ["TC-005", "TC-004"], "w.json"))
    check_eq("K1: the row went WHOLE - the red instance of TC-004 is no longer explained by any row",
             (AC.red_by_requirement(story, items(), AC.story_scope(story), strict=False) != {},
              AC.red_by_requirement(again, items(), AC.story_scope(again), strict=False)), (True, {}))

    empty, summary0 = MP.merge(copy.deepcopy(story), {"retracted_unresolved": []})
    check_eq("K1: `retracted_unresolved: []` retracts nothing", (empty, summary0.get("retracted_unresolved")), (story, None))

    both = {"unresolved": [{"case": "speakers/TC-001", "reason": CONTRADICTS, "partitions": ["P-a"]},
                           {"case": "venues/TC-001", "reason": BLOCKED, "instance_ids": ["t[a]"]},
                           {"case": "venues/TC-002", "reason": "impossible"}]}
    bare, summary2 = MP.merge(copy.deepcopy(both), {"retracted_unresolved": ["TC-001"]})
    check_eq("K1: a bare key finds the row of every area and says so in the count", (cases(bare), summary2["retracted_unresolved"]),
             (["venues/TC-002"], 2))
    named, _ = MP.merge(copy.deepcopy(both), {"retracted_unresolved": ["venues/TC-001"]})
    check_eq("K1: an area-qualified key finds that area's row only", cases(named), ["speakers/TC-001", "venues/TC-002"])
    lines = MP.retracted_unresolved_lines(both, {"retracted_unresolved": ["TC-001"]})
    check_eq("K1: `run` names each row of a bare key with its slice", len(lines), 2)
    check_in("K1: the print carries the slice and the reason", 'partitions ["P-a"]', lines)
    check_in("K1: and the other area's instance row", 'instance_ids ["t[a]"]', lines)
    check_in("K1: the print carries the Thens of the dropped row",
             "thens [2]", MP.retracted_unresolved_lines(story, {"retracted_unresolved": ["TC-004"]}))
    check_in("K1: a whole-case row is said to be whole",
             "the whole case", MP.retracted_unresolved_lines(both, {"retracted_unresolved": ["venues/TC-002"]}))
    check_eq("K1: a fragment that retracts nothing prints nothing", MP.retracted_unresolved_lines(story, {"tests": []}), [])


# --- K2, K3: what the retraction refuses -------------------------------------------------------------------------------

def k2_k3_refusals() -> None:
    story = stale_story()
    text = refusal(MP.merge, copy.deepcopy(story),
                   {"retracted_unresolved": ["TC-005"], "unresolved": [{"case": "TC-005", "reason": CONTRADICTS}]})
    check_eq("K2: send and retract the row of one case in one fragment -> the refusal",
             text, "one fragment cannot both send and retract the unresolved row of TC-005 - send the new row, or retract the old one")
    check_in("K2: an area-qualified row is the same case as a bare key",
             "cannot both send and retract", refusal(MP.merge, copy.deepcopy(story),
                                                     {"retracted_unresolved": ["TC-005"],
                                                      "unresolved": [{"case": "area/TC-005", "reason": BLOCKED}]}))
    check_eq("K2: the neighbour (another case sent, this one retracted) is no clash", refusal(
        MP.merge, copy.deepcopy(story), {"retracted_unresolved": ["TC-005"], "unresolved": [{"case": "TC-006", "reason": BLOCKED}]}), "")

    text = refusal(MP.merge, copy.deepcopy(story), {"retracted_unresolved": ["TC-099"]})
    check_in("K3: a key that names no row and no history is refused", "names no unresolved[] row this manifest holds: TC-099", text)
    check_in("K3: and the door is the view", "manifest_view.py --task <T>", text)
    gone, _ = MP.merge(copy.deepcopy(story), {"retracted_unresolved": ["TC-005"]})
    text = refusal(MP.merge, gone, {"retracted_unresolved": ["TC-005"]})
    check_in("K3: a key an earlier revision already dropped -> already gone", "TC-005 is already gone", text)
    check_not_in("K3: and it is not told apart as 'names no row'", "names no unresolved[] row", text)
    check_in("K3: one bad key among good ones refuses the whole fragment (nothing half-dropped)", "TC-099",
             refusal(MP.merge, copy.deepcopy(story), {"retracted_unresolved": ["TC-005", "TC-099"]}))
    check_in("K3: a value that is no list is refused, not read letter by letter", "is a list of case keys",
             refusal(MP.merge, copy.deepcopy(story), {"retracted_unresolved": "TC-005"}))

    # The rename rule of `_retract_instances`: this fragment's own green test already moved the case out - satisfied.
    held = {"unresolved": [{"case": "TC-009", "reason": "impossible"}]}
    moved, summary = MP.merge(held, {"tests": [GREEN_TC9], "retracted_unresolved": ["TC-009"]})
    check_eq("K3: a retraction the merge itself already satisfied is recorded, counted as nothing, not refused",
             (cases(moved), moved.get("retracted_unresolved"), summary.get("retracted_unresolved")), ([], ["TC-009"], None))


# --- K2b: the replay ----------------------------------------------------------------------------------------------------

def k2b_replay() -> None:
    story = stale_story()
    fragment = {"retracted_unresolved": ["TC-005"], "run_witness": "w.json"}
    direct, _ = MP.merge(copy.deepcopy(story), fragment)
    direct["revision"] = 1
    folded = MP.fold(journal(fragment, seed=copy.deepcopy(story)))
    check_eq("K2b: the fold of a committed retraction is the merge's manifest, nothing unprojected",
             ({k: v for k, v in folded.items() if k != "revision"}, "unprojected_events" in folded),
             ({k: v for k, v in direct.items() if k != "revision"}, False))
    check_eq("K2b: the fold is deterministic - replayed twice, the same manifest",
             MP.fold(journal(fragment, seed=copy.deepcopy(story))), folded)


# --- K4, K4b: two reasons for one case ---------------------------------------------------------------------------------

def k4_two_reasons() -> None:
    both = {"unresolved": [{"case": "TC-005", "reason": CONTRADICTS, "detail": "d"},
                           {"case": "TC-005", "reason": BLOCKED, "instance_ids": ["t[a]"]}]}
    problems = MP.unresolved_reason_conflicts(both)
    check_eq("K4: two reasons of one case -> one problem", len(problems), 1)
    check_in("K4: it names the case, both reasons and the door", "TC-005", problems)
    check_in("K4: both reasons", f"{CONTRADICTS} and {BLOCKED}", problems)
    check_in("K4: the door", "send one row per case: the stand row OR the requirement row; `retracted_unresolved` drops the old one", problems)
    check_eq("K4: two `blocked_by_env` rows are united, not refused", MP.unresolved_reason_conflicts(
        {"unresolved": [{"case": "TC-5", "reason": BLOCKED, "instance_id": "a"}, {"case": "TC-5", "reason": BLOCKED, "instance_id": "b"}]}), [])
    check_eq("K4: two rows of one reason - the later wins as always, no refusal", MP.unresolved_reason_conflicts(
        {"unresolved": [{"case": "TC-5", "reason": CONTRADICTS, "thens": [1]}, {"case": "TC-5", "reason": CONTRADICTS, "thens": [2]}]}), [])
    check_eq("K4: two reasons of two DIFFERENT cases are no conflict", MP.unresolved_reason_conflicts(
        {"unresolved": [{"case": "TC-5", "reason": CONTRADICTS}, {"case": "TC-6", "reason": BLOCKED}]}), [])
    check_eq("K4: three reasons of one case are still one problem naming all three", len(MP.unresolved_reason_conflicts(
        {"unresolved": [{"case": "TC-5", "reason": r} for r in (CONTRADICTS, BLOCKED, "impossible")]})), 1)
    check_in("K4: a row with no reason differs from a named one (refused, not guessed at)", "(none)", MP.unresolved_reason_conflicts(
        {"unresolved": [{"case": "TC-5", "reason": CONTRADICTS}, {"case": "TC-5"}]}))
    for odd in ({}, {"unresolved": None}, {"unresolved": "TC-5"}, {"unresolved": [None, 3, {"reason": BLOCKED}]}, None):
        check_eq(f"K4: an unreadable `unresolved` ({odd!r}) conflicts with nothing", MP.unresolved_reason_conflicts(odd), [])

    with Stand() as stand:
        first = stand.put({"unresolved": [{"case": "TC-001", "reason": "impossible", "detail": "d"}]})
        before = (stand.journal(), stand.tree())
        code, out, err = stand.put(both)
        check_eq("K4: `run` refuses the fragment with EXIT_BAD_FRAGMENT", (first[0], code), (0, MP.EXIT_BAD_FRAGMENT))
        check_in("K4: the refusal names the case, the reasons and the door", "TC-005 with different reasons (contradicts_requirement and "
                 "blocked_by_env)", err)
        check_in("K4: and the repair marker", MP.REPAIR_MARKER, err)
        check_eq("K4: BEFORE the commit - the journal and the tree are exactly as they were", (stand.journal(), stand.tree()), before)
        united = {"unresolved": [{"case": "TC-005", "reason": BLOCKED, "instance_id": "t[a]"},
                                 {"case": "TC-005", "reason": BLOCKED, "instance_id": "t[b]"}]}
        check_eq("K4: two `blocked_by_env` rows of one case still commit", stand.put(united)[0], 0)
        check_eq("K4: and their instances are united", row_of(stand.manifest(), "TC-005").get("instance_ids"), ["t[a]", "t[b]"])


def k4b_old_events_fold() -> None:
    """An event committed before the rule (two reasons of one case) folds as it always did: the later wins, nothing unprojected."""
    patch = {"unresolved": [{"case": "TC-5", "reason": CONTRADICTS, "detail": "d"}, {"case": "TC-5", "reason": BLOCKED, "instance_ids": ["t[a]"]}]}
    seed = {"unresolved": [{"case": "TC-1", "reason": "impossible"}], "revision": 0}
    folded = MP.fold(journal(patch, seed=seed))
    check_eq("K4b: fold([seed, patch with two reasons]) -> the later wins", row_of(folded, "TC-5").get("reason"), BLOCKED)
    check_eq("K4b: no unprojected_events", "unprojected_events" in folded, False)
    check_eq("K4b: and the merge itself raises nothing", refusal(MP.merge, copy.deepcopy(seed), patch), "")
    reversed_patch = {"unresolved": list(reversed(patch["unresolved"]))}
    check_eq("K4b: the order decides, as before (the requirement row last -> it wins)",
             row_of(MP.fold(journal(reversed_patch, seed=seed)), "TC-5").get("reason"), CONTRADICTS)


# --- K8: the slice of a re-sent row ------------------------------------------------------------------------------------

def resend(old: dict, patch: dict) -> dict:
    """The `contradicts_requirement` row of TC-004 after `patch` is sent over `old` (both through the merge)."""
    standing = {"unresolved": [dict({"case": "TC-004", "reason": CONTRADICTS, "detail": "d"}, **old)]}
    merged, _ = MP.merge(standing, {"unresolved": [dict({"case": "TC-004"}, **patch)]})
    return row_of(merged, "TC-004")


def k8_slice_replacement() -> None:
    row = resend({"partitions": ["P-msteams"]}, {"instance_ids": ["x"]})
    check_eq("K8: a patch with instances replaces the partitions", (row.get("instance_ids"), "partitions" in row), (["x"], False))
    row = resend({"instance_ids": [MS]}, {"thens": [2]})
    check_eq("K8: a `thens`-only patch keeps `instance_ids` (the two groups are independent)",
             (row.get("instance_ids"), row.get("thens")), ([MS], [2]))
    row = resend({"instance_ids": [MS], "thens": [2]}, {"instance_ids": ["MS2"]})
    check_eq("K8: new instances keep the Thens", (row.get("instance_ids"), row.get("thens")), (["MS2"], [2]))
    row = resend({"instance_ids": [MS], "thens": [2]}, {"detail": "new words"})
    check_eq("K8: a `detail`-only patch leaves the slice and the Thens", (row.get("instance_ids"), row.get("thens"), row["detail"]),
             ([MS], [2], "new words"))
    check_eq("K8: and changes no byte of the row's key order", list(row), ["case", "reason", "detail", "instance_ids", "thens"])
    row = resend({"instance_ids": [MS], "thens": [2]}, {"thens": []})
    check_eq("K8: `thens: []` leaves the old Thens (an empty group is not carried)", row.get("thens"), [2])
    row = resend({"instance_ids": [MS], "thens": [2]}, {"instance_ids": [], "partitions": ""})
    check_eq("K8: an empty slice group leaves the old slice", (row.get("instance_ids"), "partitions" in row), ([MS], False))
    row = resend({"instance_ids": [MS]}, {"thens": []})
    check_eq("K8: an empty `thens` on a row that had none does not plant the key", "thens" in row, False)
    row = resend({"instance_ids": [MS], "thens": [2]}, {"thens": [1, 2]})
    check_eq("K8: new Thens replace the old (not united), the instances stay", (row.get("thens"), row.get("instance_ids")), ([1, 2], [MS]))
    row = resend({"instance_id": "old[a]"}, {"instance_ids": ["new[b]"]})
    check_eq("K8: the singular and the plural spelling are ONE group", (row.get("instance_ids"), "instance_id" in row), (["new[b]"], False))
    row = resend({"partitions": ["P-a"]}, {"instance_ids": ["x"], "partitions": ["P-b"]})
    check_eq("K8: a patch naming both keys of the group sends both", (row.get("instance_ids"), row.get("partitions")), (["x"], ["P-b"]))

    # other reasons are not this function's: today's merge (update) stays for them
    other = {"unresolved": [{"case": "TC-004", "reason": "handed_to_person", "partitions": ["P-a"]}]}
    merged, _ = MP.merge(other, {"unresolved": [{"case": "TC-004", "instance_ids": ["x"]}]})
    check_eq("K8: a row of another reason keeps the plain update (partitions beside instance_ids)",
             (row_of(merged, "TC-004").get("partitions"), row_of(merged, "TC-004").get("instance_ids")), (["P-a"], ["x"]))
    stand = {"unresolved": [{"case": "TC-004", "reason": BLOCKED, "instance_ids": ["a"]}]}
    merged, _ = MP.merge(stand, {"unresolved": [{"case": "TC-004", "instance_ids": ["b"]}]})
    check_eq("K8: and a `blocked_by_env` row keeps its own rule (`_replace_blocked_naming`)", row_of(merged, "TC-004").get("instance_ids"), ["b"])
    # the function itself, on its edge inputs
    check_eq("K8: a patch that changes the reason to contradicts_requirement is judged by the MERGED reason",
             MP._replace_contradicts_slice({"instance_ids": ["x"]}, {"reason": CONTRADICTS, "partitions": ["P-a"], "instance_ids": ["x"]},
                                           {"reason": BLOCKED, "partitions": ["P-a"]}), {"reason": CONTRADICTS, "instance_ids": ["x"]})
    handed = {"reason": CONTRADICTS, "partitions": ["P-a"], "instance_ids": ["x"]}
    snapshot = copy.deepcopy(handed)
    MP._replace_contradicts_slice({"instance_ids": ["x"]}, handed, {})
    check_eq("K8: the row handed in is not edited in place (the manifest shares its rows with the caller's)", handed, snapshot)


def k8b_one_constant() -> None:
    inputs = [{key: "x"} for key in C.UNRESOLVED_SLICE_KEYS] + [{key: [1]} for key in C.UNRESOLVED_SLICE_KEYS] + [
        {"thens": [2]}, {}, {"instance_ids": []}, {"partitions": ""}, None, "TC-1", []]
    check_eq("K8b: `_partition_scoped` and `contract._slice_scoped` agree on every input of the contract's key test",
             [MP._partition_scoped(e) for e in inputs], [C._slice_scoped(e) for e in inputs])
    check_eq("K8b: every slice key makes a row slice-scoped (the loop is over the constant)",
             [MP._partition_scoped({key: "x"}) for key in C.UNRESOLVED_SLICE_KEYS], [True] * len(C.UNRESOLVED_SLICE_KEYS))
    check_eq("K8b: `thens` is not a slice key", (MP._partition_scoped({"thens": [2]}), C.UNRESOLVED_THENS_KEY in C.UNRESOLVED_SLICE_KEYS), (False, False))
    scoped, replaced = inspect.getsource(MP._partition_scoped), inspect.getsource(MP._replace_contradicts_slice)
    # the census (AR-13): the readers carry no key list of their own; the control is a function that does (the stand's naming)
    own = inspect.getsource(MP._with_naming)
    check("K8b: control - the same literal-key search finds a private list where there is one", '"instance_ids"' in own, own[:80])
    for name, source in (("_partition_scoped", scoped), ("_replace_contradicts_slice", replaced)):
        check(f"K8b: {name} names no slice key of its own", not any(f'"{key}"' in source for key in C.UNRESOLVED_SLICE_KEYS + (C.UNRESOLVED_THENS_KEY,)), source[:60])
        check(f"K8b: {name} reads the contract's constants", "C.UNRESOLVED_" in source, source[:60])


# --- through `run` (the journal, the print, the replay) ---------------------------------------------------------------

def run_end_to_end() -> None:
    with Stand() as stand:
        seeded = {"tests": [{"instance_id": MS, "file": "tests/test_move.py", "covers": ["TC-004", "TC-005"], "status": "red",
                             "partitions": ["P-msteams"]}],
                  "unresolved": [dict(RED_ROW), {"case": "TC-005", "reason": CONTRADICTS, "partitions": ["P-msteams"], "detail": "stale"}]}
        check_eq("run: the rows are sent", stand.put(seeded)[0], 0)
        both = stand.put({"unresolved": [{"case": "TC-005", "instance_ids": [MS], "thens": [1]}]})
        check_eq("run: a re-sent row replaces its slice in the projection", both[0], 0)
        check_eq("run: ... partitions gone, instances and Thens as sent", (row_of(stand.manifest(), "TC-005").get("instance_ids"),
                                                                          "partitions" in row_of(stand.manifest(), "TC-005")), ([MS], False))

        before = (stand.journal(), stand.tree())
        code, _out, err = stand.put({"retracted_unresolved": ["TC-099"]})
        check_eq("run K3: a key naming no row is refused before the commit", (code, (stand.journal(), stand.tree())), (MP.EXIT_BAD_FRAGMENT, before))
        check_in("run K3: nothing was committed, and the door is the view", "manifest_view.py --task <T>", err)
        code, _out, err = stand.put({"retracted_unresolved": ["TC-005"], "unresolved": [{"case": "TC-005", "reason": BLOCKED}]})
        check_eq("run K2: send-and-retract is refused before the commit", (code, (stand.journal(), stand.tree())), (MP.EXIT_BAD_FRAGMENT, before))

        code, out, err = stand.put({"retracted_unresolved": ["TC-005"]})
        check_eq("run K1: the retraction commits", code, 0)
        check_in("run K1: and says what it dropped, slice and Thens", f'unresolved row of TC-005 retracted: reason {CONTRADICTS}, '
                 f'instance_ids ["{MS}"], thens [1]', out)
        manifest = stand.manifest()
        check_eq("run K1: the projection holds TC-004's row only, and the history", (cases(manifest), manifest.get("retracted_unresolved")),
                 (["TC-004"], ["TC-005"]))
        code, _out, err = stand.put({"retracted_unresolved": ["TC-005"], "run_witness": "w2.json"})
        check_eq("run K3: the same key again is refused as already gone", (code, "is already gone" in err), (MP.EXIT_BAD_FRAGMENT, True))
        count = stand.journal()
        code, out, _err = stand.recover()
        check_eq("run K2b: the replay of the journal is the projection already standing", (code, "already current" in out, stand.journal()),
                 (0, True, count))
        check_eq("run K2b: ... and the manifest is the same", stand.manifest(), manifest)


# --- 5a-K1: `then_bindings` by unit (HF2-5) -----------------------------------------------------------------------------

def bound(case: str, then: int, iid, ref="tests/t.py:1-5") -> dict:
    return {"case": case, "then": then, "instance_id": iid, "assertion_ref": ref, "status": "covered"}


def handed(case: str, then: int, detail: str = "the steps") -> dict:
    return {"case": case, "then": then, "instance_id": None, "assertion_ref": None, "status": "unresolved",
            "reason": "handed_to_person", "detail": detail}


def writer_test(iid: str, case: str) -> dict:
    return {"instance_id": iid, "file": "tests/t.py", "covers": [case], "status": "green", "generated_from": ["tests/t.py"]}


def k5a_k1_a_writer_replaces() -> None:
    current = {"tests": [writer_test("t7", "TC-007"), writer_test("t1", "TC-001")],
               "then_bindings": [bound("TC-007", 1, "t7"), bound("TC-001", 1, "t1")]}
    # RN1-22: the writer's array replaces the rows of what it WROTE ABOUT (the instances of its `tests[]`, the cases of its own
    # rows), so the moved test (t7) is in its `tests[]`; before, any writer fragment replaced the whole array.
    sent = [bound("TC-001", 1, "t1"), bound("TC-008", 1, "t7")]
    merged, _ = MP.merge(copy.deepcopy(current), {"tests": [writer_test("t7", "TC-008")], "then_bindings": sent})
    check_eq("5a-K1 (a): the writer's array replaces the old one: the test moved TC-007 -> TC-008, the covered TC-007 row is gone",
             merged["then_bindings"], sent)
    check_eq("5a-K1 (a): ... and the run prints the row it took out",
             MP.removed_then_lines(current, {"tests": [writer_test("t7", "TC-008")], "then_bindings": sent}),
             ["TC-007 Then 1 on t7"])
    hand_merged, _ = MP.merge(copy.deepcopy(current), {"then_bindings": sent})
    check_eq("5a-K1 (a) CONTROL: the same rows from a hand fragment (no `generated_from`) leave the unit they do not name",
             [(r["case"], r["then"]) for r in hand_merged["then_bindings"]], [("TC-007", 1), ("TC-001", 1), ("TC-008", 1)])
    only_unresolved = {"unresolved": [{"case": "TC-009", "reason": "impossible", "detail": "d"}], "then_bindings": sent}
    merged, _ = MP.merge(copy.deepcopy(current), only_unresolved)
    check_eq("5a-K1 (a): a fragment with no `tests[]` (only `qa_unresolved` rows) is a hand fragment: TC-007 stays",
             [(r["case"], r["then"]) for r in merged["then_bindings"]], [("TC-007", 1), ("TC-001", 1), ("TC-008", 1)])


def k5a_k1_b_c_d_hand_units() -> None:
    story = shape_a()["manifest"]
    rows = story["then_bindings"]
    blocked_ms = [dict(r, detail="check once TC-004 is fixed (sent again)") for r in rows
                  if r["case"] == "TC-005" and r["instance_id"] == MS]
    check_eq("5a-K1 (b) fixture: TC-005 has two blocked rows on MS and two covered rows on G5",
             (len(blocked_ms), len([r for r in rows if r["case"] == "TC-005" and r["instance_id"] == G5])), (2, 2))
    merged, _ = MP.merge(copy.deepcopy(story), {"then_bindings": blocked_ms})
    check_eq("5a-K1 (b): a hand fragment of the blocked rows of TC-005 on MS leaves the covered TC-005 rows on G5 as they were",
             [r for r in merged["then_bindings"] if r["case"] == "TC-005" and r["instance_id"] == G5],
             [r for r in rows if r["case"] == "TC-005" and r["instance_id"] == G5])
    check_eq("5a-K1 (b): ... the blocked rows are the ones sent, each where it stood, and nothing else moved",
             (len(merged["then_bindings"]), [r for r in merged["then_bindings"] if r["instance_id"] == MS and r["case"] == "TC-005"]),
             (len(rows), blocked_ms))
    check_eq("5a-K1 (b): ... every row of the other units is the row it was",
             [r for r in merged["then_bindings"] if r not in blocked_ms], [r for r in rows if r["case"] != "TC-005" or r["instance_id"] != MS])
    check_eq("5a-K1 (b): ... and nothing is printed as taken out",
             MP.removed_then_lines(story, {"then_bindings": blocked_ms}), [])

    own = [dict(r, assertion_ref="tests/test_generic.py:1-2") for r in rows if r["case"] == "TC-005" and r["instance_id"] == G5]
    merged, _ = MP.merge(copy.deepcopy(story), {"then_bindings": own})
    check_eq("5a-K1 (c): a hand fragment for TC-005 leaves the TC-004 and TC-006 rows as they were",
             [r for r in merged["then_bindings"] if r["case"] in ("TC-004", "TC-006")],
             [r for r in rows if r["case"] in ("TC-004", "TC-006")])
    check_eq("5a-K1 (c): ... and the TC-005 rows of the unit are the ones sent", [r for r in merged["then_bindings"] if r in own], own)
    check_eq("5a-K1 (c): ... TC-005's other unit (MS) is untouched too",
             [r for r in merged["then_bindings"] if r["case"] == "TC-005" and r["instance_id"] == MS],
             [r for r in rows if r["case"] == "TC-005" and r["instance_id"] == MS])

    merged, _ = MP.merge(copy.deepcopy(story), {"run_witness": "w.json"})
    check_eq("5a-K1 (d): a fragment without `then_bindings` leaves the array as it was", merged["then_bindings"], rows)
    merged, _ = MP.merge(copy.deepcopy(story), {"then_bindings": []})
    check_eq("5a-K1 (d): ... and `then_bindings: []` names no unit, so it takes nothing out", merged["then_bindings"], rows)
    sent = dict(own[1], then="2", assertion_ref="x")
    merged, _ = MP.merge(copy.deepcopy(story), {"then_bindings": [sent]})
    g5_rows = [r for r in rows if r["case"] == "TC-005" and r["instance_id"] == G5]
    check_eq("5a-K1 (d): ... a `then` written as \"2\" is the Then 2 of the row it replaces (one row, not two); Then 1 of the unit "
             "was not sent and STAYS (RN1-22: only `retract` takes it out)",
             [r for r in merged["then_bindings"] if r["case"] == "TC-005" and r["instance_id"] == G5], [g5_rows[0], sent])
    merged, _ = MP.merge(copy.deepcopy(story), {"then_bindings": [sent], "retract": ["then_bindings"]})
    check_eq("5a-K1 (d): ... and with `retract: [then_bindings]` Then 1 of the unit is out, as before RN1-22",
             [r for r in merged["then_bindings"] if r["case"] == "TC-005" and r["instance_id"] == G5], [sent])
    merged, _ = MP.merge(copy.deepcopy(story), {"then_bindings": "not an array"})
    check_eq("5a-K1: a value that is no array is carried as before, never raised (an old journal replays)",
             merged["then_bindings"], "not an array")


def k5a_k1_e_two_handed_thens() -> None:
    current = {"tests": [writer_test("t1", "TC-001")],
               "then_bindings": [bound("TC-001", 1, "t1"), handed("TC-001", 3), handed("TC-001", 4), bound("TC-002", 1, "t1")]}
    # RN1-22 (FK-1 a): a Then of a named unit the fragment did not send is taken out only by `retract: [then_bindings]`
    retracting = {"then_bindings": [handed("TC-001", 4, "new steps")], "retract": ["then_bindings"]}
    merged, _ = MP.merge(copy.deepcopy(current), retracting)
    check_eq("5a-K1 (e): two handed Thens of TC-001 (null instance), the hand fragment sends Then 4 with `retract`: Then 3 is taken out",
             [(r["case"], r["then"], r.get("detail")) for r in merged["then_bindings"]],
             [("TC-001", 1, None), ("TC-001", 4, "new steps"), ("TC-002", 1, None)])
    check_eq("5a-K1 (e): ... and the summary names it", MP.removed_then_lines(current, retracting), ["TC-001 Then 3 on none"])
    both = [handed("TC-001", 3), handed("TC-001", 4, "new steps")]
    merged, _ = MP.merge(copy.deepcopy(current), {"then_bindings": both})
    check_eq("5a-K1 (e) CONTROL: the fragment sends both: both stand", [(r["then"], r.get("detail")) for r in merged["then_bindings"]
                                                                    if r["case"] == "TC-001" and r["instance_id"] is None],
             [(3, "the steps"), (4, "new steps")])
    check_eq("5a-K1 (e) CONTROL: ... and nothing is printed", MP.removed_then_lines(current, {"then_bindings": both}), [])
    check_eq("5a-K1 (e): a null instance is a unit of its own: the covered TC-001 row on t1 is not the handed unit",
             [r for r in merged["then_bindings"] if r["instance_id"] == "t1" and r["case"] == "TC-001"], [bound("TC-001", 1, "t1")])


def k5a_k1_replay() -> None:
    seed = {"tests": [writer_test("t1", "TC-001")], "then_bindings": [bound("TC-001", 1, "t1"), handed("TC-001", 3), handed("TC-001", 4)]}
    old_hand_fragment = {"then_bindings": [handed("TC-001", 4, "new steps")]}
    folded = MP.fold(journal(old_hand_fragment, seed=seed))
    check_eq("5a-K1 replay: an old journal with a hand `then_bindings` fragment folds by the new rule (RN1-22, E12: Then 3 is kept, "
             "no `retract` was sent; the covered row stays)",
             [(r["then"], r["instance_id"]) for r in folded["then_bindings"]], [(1, "t1"), (3, None), (4, None)])
    check_not_in("5a-K1 replay: ... and nothing is reported as unprojected", "unprojected_events", " ".join(folded))
    check_eq("5a-K1 replay: ... the fold is deterministic (folding the journal twice is the same manifest)",
             MP.fold(journal(old_hand_fragment, seed=seed)), folded)


def k5a_k1_run_prints() -> None:
    with Stand() as stand:
        check_eq("5a-K1 run: the handed Thens are sent", stand.put({"then_bindings": [handed("TC-001", 3), handed("TC-001", 4)]})[0], 0)
        code, out, _err = stand.put({"then_bindings": [handed("TC-001", 3), handed("TC-001", 4, "again")]})
        check_eq("5a-K1 (e) run CONTROL: both sent: it commits and says nothing of rows taken out",
                 (code, "taken out" in out), (0, False))
        code, out, _err = stand.put({"then_bindings": [handed("TC-001", 4, "only this one")], "retract": ["then_bindings"]})
        check_eq("5a-K1 (e) run: only Then 4 sent, with `retract`: it commits", code, 0)
        check_in("5a-K1 (e) run: ... and prints the row it took out in the words `<case> Then <n> on <instance|none>`",
                 "TC-001 Then 3 on none", out)
        check_eq("5a-K1 (e) run: ... the projection holds Then 4 only",
                 [(r["then"], r["detail"]) for r in stand.manifest()["then_bindings"]], [(4, "only this one")])
        count = stand.journal()
        code, out, _err = stand.put({"then_bindings": [handed("TC-001", 4, "only this one")], "retract": ["then_bindings"]})
        check_eq("5a-K1 (e) run: the same fragment sent again takes nothing out (the replay prints nothing)",
                 (code, "taken out" in out, stand.journal()), (0, False, count))


# --- HF3-2: a retracted instance takes its Then rows with it (B-K1, B-K4, B-K5, B-K7) ------------------------------------

OLD_I, NEW_I, OTHER_I = "t_old[a]", "t_new[a]", "t_other[a]"


def test_row(iid: str, covered: str = "TC-020", **extra) -> dict:
    return dict({"instance_id": iid, "file": "tests/a.py", "covers": [covered], "status": "green"}, **extra)


def retire_story() -> dict:
    """TC-020 is proved by two tests; the Thens of OLD_I (two) and of OTHER_I (one) are bound."""
    return {"tests": [test_row(OLD_I), test_row(OTHER_I)],
            "then_bindings": [bound("TC-020", 1, OLD_I), bound("TC-020", 2, OLD_I), bound("TC-020", 1, OTHER_I)]}


def hf3_2_b_k1_retraction_takes_the_rows() -> None:
    story = retire_story()
    rename = {"retracted_instances": [OLD_I], "tests": [test_row(NEW_I)]}
    merged, summary = MP.merge(copy.deepcopy(story), rename)
    check_eq("B-K1: a rename (old retracted, new sent) takes the two Thens bound to the retired spelling and leaves the rest",
             [(r["then"], r["instance_id"]) for r in merged["then_bindings"]], [(1, OTHER_I)])
    check_eq("B-K1: ... the summary counts them, and the retraction is recorded as before",
             (summary.get("then_rows_retired"), summary.get("retracted_instances"), merged.get("retracted_instances")),
             (2, 1, [OLD_I]))
    check_eq("B-K1: ... `run` prints exactly those rows, in the words of the other block",
             MP.removed_then_lines(story, rename), [f"TC-020 Then 1 on {OLD_I}", f"TC-020 Then 2 on {OLD_I}"])
    _, summary = MP.merge(copy.deepcopy(story), {"tests": [test_row(NEW_I)]})
    check_eq("B-K1 CONTROL: the same new row WITHOUT the retraction takes nothing (and the summary has no such key)",
             ("then_rows_retired" in summary, MP.removed_then_lines(story, {"tests": [test_row(NEW_I)]})), (False, []))

    # the door of a ghost (A19): retracting the id AGAIN takes the Thens that still stand on it (m10 - "asked", not "first written")
    ghosted = copy.deepcopy(story)
    ghosted["retracted_instances"] = [OLD_I]
    ghosted["tests"] = [t for t in ghosted["tests"] if t["instance_id"] != OLD_I] + [{"instance_id": OLD_I, "status": "red"}]
    merged, summary = MP.merge(copy.deepcopy(ghosted), {"retracted_instances": [OLD_I]})
    check_eq("B-K1 door: retracting a ghost's id again drops the ghost AND the Thens still bound to it",
             ([t["instance_id"] for t in merged["tests"]], [(r["then"], r["instance_id"]) for r in merged["then_bindings"]],
              merged["retracted_instances"]), ([OTHER_I], [(1, OTHER_I)], [OLD_I]))

    with Stand() as stand:
        check_eq("B-K1 run: the story is sent", stand.put(story)[0], 0)
        code, out, _err = stand.put(rename)
        check_eq("B-K1 run: the rename commits", code, 0)
        check_in("B-K1 run: ... prints the block and the first row", "then_bindings rows taken out by this send", out)
        check_in("B-K1 run: ... and the rows by their words", f"TC-020 Then 2 on {OLD_I}", out)
        check_eq("B-K1 run: ... the projection holds the one row that stood on the other test",
                 [(r["then"], r["instance_id"]) for r in stand.manifest()["then_bindings"]], [(1, OTHER_I)])
        count = stand.journal()
        code, out, _err = stand.put(rename)
        check_eq("B-K1 run: the same fragment sent again is the store's reuse path (nothing new, nothing re-printed as taken)",
                 (code, stand.journal()), (0, count))


def hf3_2_b_k4_a_spelling_a_row_still_wears() -> None:
    prefixed, bare = "TC-012::test_x[eu]", "test_x[eu]"
    old = {"tests": [test_row(bare, "TC-012", case="TC-012")], "then_bindings": [bound("TC-012", 1, prefixed), bound("TC-012", 2, bare)]}
    # `_current_spelling`: a 0.7.7 fragment sends the prefixed spelling of the row that stands bare; the prefixed one is
    # retired - and the surviving row still answers to it (`_identity`), so its Thens stay
    patch = {"tests": [test_row(prefixed, "TC-012", case="TC-012")]}
    merged, summary = MP.merge(copy.deepcopy(old), patch)
    check_eq("B-K4: the 0.7.7 spelling retired by `_current_spelling` (the rename of one live row) keeps its Thens",
             ([r["instance_id"] for r in merged["then_bindings"]], merged.get("retracted_instances"), "then_rows_retired" in summary),
             ([prefixed, bare], [prefixed], False))
    check_eq("B-K4: ... and `run` prints nothing taken", MP.removed_then_lines(old, patch), [])
    # `_retract_aliases`: two rows that are two spellings of one test collapse; the survivor wears both
    twin = {"tests": [test_row(prefixed, "TC-012", case="TC-012"), test_row(bare, "TC-012", case="TC-012")],
            "then_bindings": old["then_bindings"]}
    merged, summary = MP.merge(copy.deepcopy(twin), {"runs": [{"label": "w"}]})
    check_eq("B-K4: the collapse of two spellings of one test (`_retract_aliases`) keeps the Thens of both",
             ([t["instance_id"] for t in merged["tests"]], [r["instance_id"] for r in merged["then_bindings"]],
              "then_rows_retired" in summary), ([bare], [prefixed, bare], False))
    # CONTROL: an explicit retraction of that very alias with the row dropped by it is a retirement (nobody wears it after).
    # FLIPPED by the Lead's decision on HF3-2 Q2 (critic t-1276): the Then rows bound to ANY alias of the dropped row go with
    # it - the bare spelling too, not only the one that was named (was: `[bare], 1`)
    merged, summary = MP.merge(copy.deepcopy(old), {"retracted_instances": [prefixed]})
    check_eq("B-K4 CONTROL (Q2): retracting the prefixed id with no row left to wear it takes the Thens bound to it AND to its bare alias",
             ([t["instance_id"] for t in merged["tests"]], [r["instance_id"] for r in merged["then_bindings"]],
              summary.get("then_rows_retired")), ([], [], 2))


def hf3_2_b_k8_aliases_of_a_dropped_row() -> None:
    """Q2 (critic t-1276, the Lead's decision): a Then row bound to ANY spelling a dropped row answered to is retired with it
    (`contract.instance_id_aliases`: the canonical id, the 0.7.7 case-prefixed id, the bare id, the selector hash)."""
    prefixed, bare = "TC-012::test_x[eu]", "test_x[eu]"
    other = "test_y[eu]"
    row = test_row(prefixed, "TC-012", case="TC-012")
    thens = [bound("TC-012", 1, prefixed), bound("TC-012", 2, bare), bound("TC-012", 3, other)]
    story = {"tests": [row, test_row(other, "TC-012", case="TC-012")], "then_bindings": thens}
    aliases = MP._spellings(row)
    check_eq("B-K8: the alias set of the row holds the prefixed and the bare spelling", {prefixed, bare} <= aliases, True)
    for asked in (prefixed, bare):
        merged, summary = MP.merge(copy.deepcopy(story), {"retracted_instances": [asked]})
        check_eq(f"B-K8: retracting `{asked}` takes the Thens of EVERY alias of the dropped row and leaves the other test's",
                 ([t["instance_id"] for t in merged["tests"]], [(r["then"], r["instance_id"]) for r in merged["then_bindings"]],
                  summary.get("then_rows_retired")), ([other], [(3, other)], 2))
        check_eq(f"B-K8: ... and `run` prints the rows of both spellings (`{asked}`)",
                 MP.removed_then_lines(story, {"retracted_instances": [asked]}),
                 [f"TC-012 Then 1 on {prefixed}", f"TC-012 Then 2 on {bare}"])
    check_eq("B-K8 CONTROL: a row that survives keeps every Then of its aliases (nothing dropped, nothing retired)",
             MP._dropped_spellings(story, []), set())
    check_eq("B-K8: `_dropped_spellings` adds the aliases of the row that answers to a named spelling, and nothing for an unknown one",
             (MP._dropped_spellings(story, [prefixed]) >= {prefixed, bare}, MP._dropped_spellings(story, ["nobody"]),
              MP._dropped_spellings(None, [prefixed])), (True, {"nobody"}, {prefixed}))
    check_eq("B-K8: spelled in a rename (the new row wears the aliases): the rows of the spelling the new row answers to stay",
             MP._retire_then_rows({"tests": [row], "then_bindings": thens}, MP._dropped_spellings(story, [prefixed]), {}), [])


def hf3_2_b_k5_send_and_retract() -> None:
    story = retire_story()
    sent = {"retracted_instances": [OLD_I], "tests": [test_row(NEW_I)], "then_bindings": [bound("TC-020", 3, OLD_I)]}
    merged, summary = MP.merge(copy.deepcopy(story), sent)
    check_eq("B-K5 replay: `merge` never raises on a fragment that binds a Then to the id it retracts, and the sent row STAYS "
             "(the retirement runs before the merge of the fragment's own rows); the older rows of the id went",
             ([(r["then"], r["instance_id"]) for r in merged["then_bindings"]], summary.get("then_rows_retired")),
             ([(1, OTHER_I), (3, OLD_I)], 2))
    check_eq("B-K5 replay: ... and the old journal folds without a gap",
             "unprojected_events" in MP.fold(journal(sent, seed=story)), False)
    with Stand() as stand:
        stand.put(story)
        before = (stand.journal(), stand.tree())
        code, _out, err = stand.put(sent)
        check_eq("B-K5 run: the same fragment is refused BEFORE the commit and nothing changes",
                 (code, (stand.journal(), stand.tree())), (MP.EXIT_BAD_FRAGMENT, before))
        check_in("B-K5 run: ... with the rule's words", "one fragment cannot both bind a Then to and retract an instance", err)
        check_in("B-K5 run: ... the id", OLD_I, err)
        check_in("B-K5 run: ... and the door", "retract the old spelling, not the same id twice", err)
        control = dict(sent, then_bindings=[bound("TC-020", 3, NEW_I)])
        code, _out, err = stand.put(control)
        check_eq("B-K5 run CONTROL: the Then row on the NEW id commits", (code, err), (0, ""))


def hf3_2_b_k7_empties() -> None:
    story = retire_story()
    for label, fragment in (("an empty retraction", {"retracted_instances": [], "runs": [{"label": "w"}]}),
                            ("a null retraction", {"retracted_instances": None, "runs": [{"label": "w"}]}),
                            ("no then_bindings in the manifest", {"retracted_instances": [OLD_I]})):
        base = copy.deepcopy(story)
        if label.startswith("no then"):
            base.pop("then_bindings")
        try:
            merged, summary = MP.merge(base, fragment)
            raised = ""
        except Exception as exc:
            merged, summary, raised = {}, {}, f"{type(exc).__name__}: {exc}"
        check_eq(f"B-K7: {label} does not raise", raised, "")
        if label.startswith("no then"):
            check_eq("B-K7: ... and invents no array", ("then_bindings" in merged, "then_rows_retired" in summary), (False, False))
        else:
            check_eq(f"B-K7: ... {label} takes nothing", (merged["then_bindings"], "then_rows_retired" in summary),
                     (story["then_bindings"], False))
    base = copy.deepcopy(story)
    base["then_bindings"] = "not an array"
    merged, summary = MP.merge(base, {"retracted_instances": [OLD_I]})
    check_eq("B-K7: a `then_bindings` that is no array (an old journal) is carried as it was, never raised",
             (merged["then_bindings"], "then_rows_retired" in summary), ("not an array", False))
    check_eq("B-K7: `_retire_then_rows` with nothing to retire or nothing to read returns [] and touches nothing",
             [MP._retire_then_rows({"then_bindings": [bound("TC-020", 1, OLD_I)], "tests": []}, [], {}),
              MP._retire_then_rows({"then_bindings": [bound("TC-020", 1, OLD_I)], "tests": []}, [None, "", "  "], {}),
              MP._retire_then_rows({"then_bindings": None}, [OLD_I], {}), MP._retire_then_rows({}, [OLD_I], {})], [[]] * 4)
    garbage = {"then_bindings": [None, "x", 3, bound("TC-020", 1, OLD_I)], "tests": []}
    check_eq("B-K7: rows that are no objects are kept, the object row of the retired spelling goes",
             (MP._retire_then_rows(garbage, [OLD_I], {}), garbage["then_bindings"]), ([bound("TC-020", 1, OLD_I)], [None, "x", 3]))


# --- TQ1-7: introduced_helpers[] by (file, name) -------------------------------------------------------------------------

def helper(file: str, name: str, novelty=None, **role) -> dict:
    row = {"file": file, "name": name, **role}
    if novelty:
        row["novelty"] = novelty
    return row


def tq1_7_helpers() -> None:
    """D1-K4/K6, D1-3: two writers, one row. The writer's row (it carries `novelty`) replaces; the files it read lose the
    rows of functions it did not send; a role row changes the role fields of a row that stands and creates none; a field
    that is none of the seven is refused with the fields named, before the commit. Killing test of M-D1-4 (merge not by pair)."""
    a, b = "tests/a.py", "tests/b.py"
    writer = {"introduced_helpers": [helper(a, "PO.read", "new", purpose="", searched="", similar_found="", keep=""),
                                     helper(a, "make", "changed", purpose="", searched="", similar_found="", keep=""),
                                     helper(b, "other", "new", purpose="", searched="", similar_found="", keep="")]}
    merged, summary = MP.merge({}, writer)
    check_eq("K4: the writer's rows are added, keyed by the pair", sorted((r["file"], r["name"]) for r in merged["introduced_helpers"]),
             [(a, "PO.read"), (a, "make"), (b, "other")])
    check_eq("K4: three added", summary["added"], 3)
    role = {"introduced_helpers": [{"file": a, "name": "make", "purpose": "builds", "searched": "tests/", "similar_found": "none"}]}
    merged2, _ = MP.merge(merged, role)
    row = next(r for r in merged2["introduced_helpers"] if r["name"] == "make")
    check_eq("K4: a role row sets the role fields and keeps the scaffold", (row["purpose"], row["searched"], row["novelty"], row["keep"]),
             ("builds", "tests/", "changed", ""))
    check_eq("K4: the other rows stand as they were", [r for r in merged2["introduced_helpers"] if r["name"] != "make"],
             [r for r in merged["introduced_helpers"] if r["name"] != "make"])
    # the writer again: the role's words survive an EMPTY role field of the writer, the function that is gone loses its row,
    # the row of the other file stays
    rewrite = {"introduced_helpers": [helper(a, "make", "changed", purpose="", searched="", similar_found="", keep="")],
               "tests": [{"instance_id": "t_one", "file": a, "generated_from": [a], "case": "TC-1", "covers": ["TC-1"]}]}
    merged3, _ = MP.merge(merged2, rewrite)
    check_eq("D1-3: a writer run over a.py drops the vanished PO.read, keeps b.py's row",
             sorted((r["file"], r["name"]) for r in merged3["introduced_helpers"]), [(a, "make"), (b, "other")])
    check_eq("K3: an empty role field of the writer does not wipe what the role wrote",
             next(r for r in merged3["introduced_helpers"] if r["name"] == "make")["purpose"], "builds")
    merged4, _ = MP.merge(merged2, {"introduced_helpers": [], "tests": rewrite["tests"]})
    check_eq("K4: an empty list with a writer-marked test row of the file takes every row of that file",
             sorted((r["file"], r["name"]) for r in merged4["introduced_helpers"]), [(b, "other")])
    merged5, _ = MP.merge(merged2, {"introduced_helpers": [], "tests": [{"instance_id": "t_one", "file": a}]})
    check_eq("D1-3: a test row without the writer's mark takes nothing", len(merged5["introduced_helpers"]), 3)
    check_eq("D1-2: an old manifest without the key stays without it under a fragment without it",
             "introduced_helpers" in MP.merge({"tests": []}, {"run_witness": "w"})[0], False)
    check_eq("K6 (merge): a role row for a pair nobody wrote creates nothing at replay",
             MP.merge({}, {"introduced_helpers": [{"file": a, "name": "ghost", "purpose": "x"}]})[0].get("introduced_helpers"), [])

    problems = MP.helper_row_problems(merged, {"introduced_helpers": [{"file": a, "name": "make", "colour": "red", "scope": 1}]})
    check("K6: a field that is none of the seven is refused and the fields are named",
          len(problems) == 1 and "colour, scope" in problems[0] and "purpose" in problems[0] and "novelty" in problems[0], str(problems))
    check_eq("K6: a role row for a pair the manifest holds no row for is refused with the door",
             ["manifest_from_tests.py" in p for p in MP.helper_row_problems(merged, {"introduced_helpers": [
                 {"file": a, "name": "ghost", "purpose": "x"}]})], [True])
    check_eq("K6: ... but not when the same fragment brings the writer's row of it",
             MP.helper_row_problems({}, {"introduced_helpers": [helper(a, "n", "new"), {"file": a, "name": "n", "purpose": "p"}]}), [])
    check("K6: a role field that is not text, and a `novelty` that is not one of the three, are named",
          len(MP.helper_row_problems(merged, {"introduced_helpers": [{"file": a, "name": "make", "purpose": 3},
                                                                       helper(a, "make", "maybe")]})) == 2)
    check_eq("K6: the key is a list", len(MP.helper_row_problems({}, {"introduced_helpers": "x"})), 1)
    check_eq("D1-2: a fragment without the key has no problem to name", MP.helper_row_problems({}, {"tests": []}), [])
    check("BY_HELPER is also in SCALAR_EXEMPT: the trailing scalar loop never copies the key whole",
          MP.BY_HELPER[0] in MP.SCALAR_EXEMPT, str(MP.SCALAR_EXEMPT))

    with Stand() as stand:
        check_eq("run: the writer's rows are committed", stand.put(writer)[0], 0)
        before = (stand.journal(), stand.tree())
        code, _out, err = stand.put({"introduced_helpers": [{"file": a, "name": "make", "colour": "red"}]})
        check_eq("K6 run: a row with a foreign field is refused before the commit, the journal unchanged",
                 (code, (stand.journal(), stand.tree())), (MP.EXIT_BAD_FRAGMENT, before))
        check_in("K6 run: the refusal names the field and the fields it takes", "colour", err)
        check_in("K6 run: ... and the repair marker", "repair", err.lower())
        code, _out, err = stand.put({"introduced_helpers": [{"file": a, "name": "ghost", "purpose": "x"}]})
        check_eq("K6 run: a role row for a helper nobody wrote is refused", (code, "manifest_from_tests.py" in err), (MP.EXIT_BAD_FRAGMENT, True))
        check_eq("run: the role's four fields go in", stand.put(role)[0], 0)
        check_eq("run: the projection holds them beside the scaffold",
                 [(r["purpose"], r["novelty"]) for r in stand.manifest()["introduced_helpers"] if r["name"] == "make"], [("builds", "changed")])


def tq1_18_base_outcome() -> None:
    """TQ1-18 (D3-K19, D3-K20, D3-2; kills M-D3-8 on the writer's side): `manifest_put` refuses a `base_outcome` whose word is not one of
    the two and one with no run, before the commit; and the value a REAL `manifest_put` wrote reaches `ledger.test_state` (the proof
    that the field has a producer and a reader: `test_field_producers.py` does not walk manifest-row fields, S-7)."""
    import ledger as L
    check("the ledger's word is the writer's", L.BASE_REFUSED in MP.BASE_OUTCOMES, str(MP.BASE_OUTCOMES))
    row = {"instance_id": "test_move", "file": "tests/t.py", "covers": ["TC-018"], "case": "TC-018", "critic_verdict": "approved"}
    with Stand() as stand:
        check_eq("the row is sent", stand.put({"tests": [row]})[0], 0)
        for name, block in (("an unknown outcome", {"outcome": "refusde", "run": "A1"}), ("no run", {"outcome": "refused"}),
                            ("an empty run", {"outcome": "working", "run": " "}), ("not an object", "refused")):
            before = (stand.journal(), stand.tree())
            code, _out, err = stand.put({"tests": [dict(row, base_outcome=block)]})
            check_eq(f"K19: {name} is refused before the commit", (code, (stand.journal(), stand.tree())), (MP.EXIT_BAD_FRAGMENT, before))
            check_in(f"K19: {name}: the refusal names the field and what it expects", "`base_outcome`", err)
        check_in("K19: ... and the two words", '"refused" | "working"', err)
        check_eq("a good record is committed", stand.put({"tests": [dict(row, base_outcome={"outcome": "refused", "run": "A1"})]})[0], 0)
        entry = C.manifest_tests(stand.manifest())[0]
        check_eq("the record is on the row", entry.get("base_outcome"), {"outcome": "refused", "run": "A1"})
        report = {"current_results": [{"instance_id": "test_move", "case": "TC-018", "status": "passed", "attempt_id": "A1"}]}
        check_eq("D3-K20: the value the real writer stored reaches the ledger", L.test_state(entry, report, {"triage": []}, None,
                                                                                         stand.manifest())[0], L.NOT_VERIFIED_REFUSED_BASE)


def ep1_38_obligation_hash() -> None:
    """EP1-38 item 5 (AR-14): a `tests[]` row that SENDS an `obligation_hash` is checked against `content_hash(obligation_refs)`
    BEFORE the commit; the refs are the patch's, else the stored row's of the same instance (M-7). No hash -> not looked at."""
    from event_store import content_hash
    refs = [{"obligation_id": "OB-1", "obligation_hash": "h1"}, {"obligation_id": "OB-2", "obligation_hash": "h2"}]
    built = content_hash(refs)
    row = {"instance_id": "test_move", "file": "tests/t.py", "covers": ["TC-018"], "case": "TC-018", "status": "green"}
    check_eq("pure: a row with no hash is not looked at", MP.obligation_hash_problems({"tests": [dict(row, obligation_refs=refs)]}, []), [])
    check_eq("pure: the right hash of the patch's refs is accepted",
             MP.obligation_hash_problems({"tests": [dict(row, obligation_refs=refs, obligation_hash=built)]}, []), [])
    check_eq("pure: a null / empty hash is 'no hash'",
             MP.obligation_hash_problems({"tests": [dict(row, obligation_hash=None), dict(row, obligation_hash="")]}, []), [])
    check_eq("pure: no tests key, a non-dict row and a non-list stored are no problem",
             MP.obligation_hash_problems({}, None) + MP.obligation_hash_problems({"tests": ["x"]}, "y"), [])
    with Stand() as stand:
        check_eq("the row with its refs is sent (no hand hash)", stand.put({"tests": [dict(row, obligation_refs=refs)]})[0], 0)
        before = (stand.journal(), stand.tree())
        code, _out, err = stand.put({"tests": [dict(row, obligation_refs=refs, obligation_hash="zzz")]})
        check_eq("a wrong hash beside its refs is refused before the commit", (code, (stand.journal(), stand.tree())),
                 (MP.EXIT_BAD_FRAGMENT, before))
        check_in("... and says what the code builds", f"is not the hash of its obligation_refs ({built}); leave it out, the code builds it", err)
        check_in("... naming the row and the hash sent", "tests[0].obligation_hash zzz", err)
        code, _out, err = stand.put({"tests": [{"instance_id": "test_move", "obligation_hash": "zzz"}]})
        check_eq("M-7: a patch with no refs of its own is checked against the STORED refs of that instance",
                 (code, f"({built})" in err), (MP.EXIT_BAD_FRAGMENT, True))
        check_eq("M-7: ... and the right hash of the stored refs is accepted",
                 stand.put({"tests": [{"instance_id": "test_move", "obligation_hash": built}]})[0], 0)
        code, _out, err = stand.put({"tests": [dict(row, obligation_refs=[], obligation_hash=built)]})
        check_eq("empty refs in the patch + a hash: nothing to check it against -> refused",
                 (code, "cannot be checked: the row names no obligation_refs; leave it out, the code builds it" in err),
                 (MP.EXIT_BAD_FRAGMENT, True))
        code, _out, err = stand.put({"tests": [{"instance_id": "test_other", "file": "tests/t.py", "covers": ["TC-019"],
                                                "case": "TC-019", "obligation_hash": built}]})
        check_eq("a hash for an instance that holds no refs anywhere -> refused as unverifiable",
                 (code, "cannot be checked" in err), (MP.EXIT_BAD_FRAGMENT, True))
        check_eq("a patch that leaves the hash out is taken", stand.put({"tests": [dict(row, critic_verdict="approved")]})[0], 0)


def t9(iid: str = "test_nine[a]", **extra) -> dict:
    return dict({"instance_id": iid, "file": "tests/test_nine.py", "case": "TC-009", "covers": ["TC-009"]}, **extra)


THEN_ROW = {"case": "TC-009", "reason": CONTRADICTS, "thens": [2], "detail": "Then 2 contradicts the requirement"}


def tests_of(manifest: dict) -> list:
    return sorted(MP._instance(e) for e in manifest.get("tests") or [])


def ep1_39_then_row_keeps_tests() -> None:
    """EP1-39 (AR-14, AR-23, AR-25, AR-27): a `contradicts_requirement` row that names only Thens of a case that RAN does not
    take the case's `tests[]` rows with it; the rows that were taken are named. Table `edges` of the spec, one line per row."""
    # the tests are STORED and the fragment sends the row alone: only a stored row can be moved out by it
    send = lambda tests, row: MP.merge({"tests": copy.deepcopy(tests)}, {"unresolved": [row]})[0]
    # the predicate: one home (AR-13), and the forms that do NOT widen the protection
    check_eq("pred: the Then row is `contradicts_requirement` + non-empty `thens` list + no slice",
             (C.then_scoped_row(THEN_ROW), MP._then_row(THEN_ROW)), (True, True))
    for label, odd in (("thens []", dict(THEN_ROW, thens=[])), ("thens ''", dict(THEN_ROW, thens="")),
                       ("no thens", {k: v for k, v in THEN_ROW.items() if k != "thens"}), ("thens '2'", dict(THEN_ROW, thens="2")),
                       ("another reason", dict(THEN_ROW, reason="impossible")), ("blocked_by_env", dict(THEN_ROW, reason=BLOCKED)),
                       ("a slice", dict(THEN_ROW, instance_ids=["x"])), ("partitions", dict(THEN_ROW, partitions=["P-a"])),
                       ("not a dict", "x")):
        check_eq(f"pred: {label} is not the Then row", (C.then_scoped_row(odd), MP._then_row(odd)), (False, False))

    # a test that ran stands, and so does the row
    for label, status in (("a handwritten row with NO status (M-2)", {}), ("status ''", {"status": ""}), ("green", {"status": "green"}),
                          ("red", {"status": "red"})):
        merged = send([t9(**status)], THEN_ROW)
        check_eq(f"E-then-row: {label} + thens [2] with no slice -> the test stays and the row stays",
                 (tests_of(merged), cases(merged)), (["test_nine[a]"], ["TC-009"]))
    # a test that did not run is wholly unresolved, and the loss is named
    for status in ("pending_run", "not_run", "blocked_by_env"):
        merged = send([t9(status=status)], THEN_ROW)
        check_eq(f"M-2: status {status} is not a run -> the case is wholly unresolved", (tests_of(merged), cases(merged)), ([], ["TC-009"]))
    # the row without Thens, or with an unreadable `thens`, keeps its whole-case meaning
    for label, row in (("thens []", dict(THEN_ROW, thens=[])), ("thens ''", dict(THEN_ROW, thens="")),
                       ("no thens", {k: v for k, v in THEN_ROW.items() if k != "thens"}), ("thens '2'", dict(THEN_ROW, thens="2")),
                       ("another reason + thens", dict(THEN_ROW, reason="impossible")),
                       ("blocked_by_env + thens", dict(THEN_ROW, reason=BLOCKED))):
        check_eq(f"E-then-row: {label} -> the whole case, the test row goes", tests_of(send([t9(status="red")], row)), [])
    check_eq("slice: thens + instance_ids stays a slice, as today (the tests stay)",
             tests_of(send([t9(status="red")], dict(THEN_ROW, instance_ids=["test_nine[a]"]))), ["test_nine[a]"])
    # no instance that ran
    stored = {"tests": [t9(status="pending_run")]}
    merged = MP.merge(copy.deepcopy(stored), {"unresolved": [THEN_ROW]})[0]
    check_eq("no ran instance (only a pending one stored): the whole case, the row goes", (tests_of(merged), cases(merged)), ([], ["TC-009"]))
    merged = MP.merge({"tests": [t9(status="red")]}, {"unresolved": [THEN_ROW]})[0]
    check_eq("a ran instance STORED (the fragment sends none): the row stands", (tests_of(merged), cases(merged)), (["test_nine[a]"], ["TC-009"]))
    # a ran row of the FRAGMENT protects a stored pending sibling (the incoming side of `_ran_rows`)
    merged = MP.merge({"tests": [t9("test_nine[b]", status="pending_run")]},
                      {"tests": [t9("test_nine[a]", status="red")], "unresolved": [THEN_ROW]})[0]
    check_eq("_ran_rows reads the fragment's rows too: red a keeps pending b", (tests_of(merged), cases(merged)),
             (["test_nine[a]", "test_nine[b]"], ["TC-009"]))
    # the consolidated instance
    consolidated = {"instance_id": "t[all]", "file": "t.py", "case": "TC-003", "covers": ["TC-003", "TC-004", "TC-005"], "status": "red"}
    check_eq("`_moved_out:433`: a consolidated TC-003/004/005 with one Then row on TC-003 stays",
             tests_of(send([consolidated], dict(THEN_ROW, case="TC-003"))), ["t[all]"])

    # M-1: the stored Then row is taken by an explicit green only, and not beside a red instance
    base9 = {"unresolved": [dict(THEN_ROW)]}
    gone, _ = MP.merge(copy.deepcopy(base9), {"tests": [GREEN_TC9]})
    check_eq("pin GREEN_TC9: the only green instance, explicit -> the Then row is taken", cases(gone), [])
    red_b = t9("test_nine[b]", status="red")
    kept, _ = MP.merge({"unresolved": [dict(THEN_ROW)], "tests": [red_b]}, {"tests": [t9("test_nine[a]", status="green")]})
    check_eq("M-1: green a beside the STORED red b -> the row stands", (cases(kept), tests_of(kept)), (["TC-009"], ["test_nine[a]", "test_nine[b]"]))
    kept, _ = MP.merge({"unresolved": [dict(THEN_ROW)]}, {"tests": [t9("test_nine[a]", status="green"), t9("test_nine[b]", status="red")]})
    check_eq("M-1: green a and red b in ONE fragment -> the row stands", cases(kept), ["TC-009"])
    for label, status in (("no status (a critic patch)", {}), ("status ''", {"status": ""})):
        kept, _ = MP.merge({"unresolved": [dict(THEN_ROW)]}, {"tests": [t9(**status)]})
        check_eq(f"reverse hole: {label} is no explicit green -> the Then row stands", cases(kept), ["TC-009"])
    kept, _ = MP.merge({"unresolved": [dict(THEN_ROW)], "tests": [t9(status="red")]},
                       {"tests": [{"instance_id": "test_nine[a]", "critic_verdict": "approved", "critic_note": "re-read"}]})
    check_eq("reverse hole: a critic patch with no `status` over a stored row -> the Then row stands", (cases(kept), tests_of(kept)),
             (["TC-009"], ["test_nine[a]"]))

    # F-3 (t-555): a patch that names only the instance is read OVER its stored row, so it cannot hide a stored red
    a_green = t9("test_nine[a]", status="green")
    stored_ab = {"tests": [a_green, red_b], "unresolved": [dict(THEN_ROW)]}
    patch_b = {"instance_id": "test_nine[b]", "critic_verdict": "unverified"}
    kept, _ = MP.merge(copy.deepcopy(stored_ab), {"tests": [dict(a_green), patch_b]})
    check_eq("F-3: stored green a + red b, a fragment of green a and a bare patch of b -> the Then row stands",
             (cases(kept), tests_of(kept)), (["TC-009"], ["test_nine[a]", "test_nine[b]"]))
    p_pending = t9("test_nine[p]", status="pending_run")
    q_red = t9("test_nine[q]", status="red")
    patch_q = {"instance_id": "test_nine[q]", "critic_verdict": "unverified"}
    stored_pq = {"tests": [p_pending, q_red]}
    kept, _ = MP.merge(copy.deepcopy(stored_pq), {"tests": [patch_q], "unresolved": [dict(THEN_ROW)]})
    check_eq("F-3: stored pending p + red q, a bare patch of q and the Then row -> p stays (q is red and stands)",
             (tests_of(kept), cases(kept)), (["test_nine[p]", "test_nine[q]"], ["TC-009"]))
    check_eq("F-3: ... and the print names no moved row", MP.moved_out_lines(copy.deepcopy(stored_pq),
             {"tests": [patch_q], "unresolved": [dict(THEN_ROW)]}), [])
    kept, _ = MP.merge({"unresolved": [dict(THEN_ROW)]}, {"tests": [dict(a_green)]})
    check_eq("F-3 control: the only green instance, nothing else stored -> the Then row is taken", cases(kept), [])

    # idempotency and order
    fragment = {"tests": [t9(status="red")], "unresolved": [dict(THEN_ROW)]}
    once, _ = MP.merge({}, fragment)
    twice, _ = MP.merge(copy.deepcopy(once), fragment)
    check_eq("the same fragment twice -> the manifest byte for byte", twice, once)

    def normal(m):
        return {k: sorted(m.get(k) or [], key=lambda r: repr(sorted(r.items()))) for k in ("tests", "unresolved")}
    first, _ = MP.merge(MP.merge({}, {"tests": [t9(status="red")]})[0], {"unresolved": [dict(THEN_ROW)]})
    second, _ = MP.merge(MP.merge({}, {"unresolved": [dict(THEN_ROW)]})[0], {"tests": [t9(status="red")]})
    check_eq("{red tests, Then row} in both orders -> equal manifests (arrays normalised HERE, not in the code)", normal(first), normal(second))
    check_eq("... and both hold the test and the row", (tests_of(first), cases(first)), (["test_nine[a]"], ["TC-009"]))
    # the replay: a journal of the old order folds, and does not raise
    check_eq("replay: two fragments of the old order fold without an unprojected event",
             "unprojected_events" in MP.fold(journal({"unresolved": [dict(THEN_ROW)]}, {"tests": [t9(status="red")]})), False)

    # the print: lines come from the trail, one per moved row, and add up to `moved` of tests[]
    two = {"tests": [t9("test_nine[a]", status="pending_run"), t9("test_nine[b]", status="pending_run")], "unresolved": [THEN_ROW]}
    lines = MP.moved_out_lines({}, two)
    merged, summary = MP.merge({}, two)
    check_eq("print: one line per moved row, the sum is `moved` of tests[] (both rows were only in the fragment: none moved)",
             (len(lines), summary["moved"]), (0, 0))
    stored = {"tests": [t9("test_nine[a]", status="pending_run"), t9("test_nine[b]", status="pending_run")]}
    lines = MP.moved_out_lines(stored, {"unresolved": [THEN_ROW]})
    merged, summary = MP.merge(copy.deepcopy(stored), {"unresolved": [THEN_ROW]})
    check_eq("print: the lines add up to the rows moved out of tests[]", (len(lines), summary["moved"], tests_of(merged)), (2, 2, []))
    check_in("print: a line names the instance, the case and the door", "moved out of tests[]: test_nine[a] (case TC-009 is now wholly "
             "unresolved because the row names no instance_ids/partitions; if it is about particular Thens, name the instances: "
             "instance_ids: [...])", lines[0])
    check_eq("print: nothing moved -> no lines", MP.moved_out_lines({"tests": [t9(status="red")]}, {"unresolved": [THEN_ROW]}), [])
    check_eq("print: a before that cannot merge is no failure", MP.moved_out_lines("x", {"unresolved": [THEN_ROW]}), [])


def ep1_39_critic_approval() -> None:
    """EP1-39 item 7 (F-11 a): `approved` over a stored `unverified` needs a note; a note passes (legality is not judged)."""
    stored = [t9(critic_verdict="unverified", critic_note="no probe")]
    patch = lambda **kw: {"tests": [dict({"instance_id": "test_nine[a]", "critic_verdict": "approved"}, **kw)]}
    check_in("pure: approved over unverified with no note -> refused, naming the row",
             "tests[0] approves over a stored unverified verdict with no critic_note: say what changed (a probe result, a re-read); a "
             "receipt that lacks a probe is a tooling gap, not an approval", MP.critic_approval_problems(patch(), stored)[0])
    for label, kw in (("whitespace note", {"critic_note": "  "}), ("empty note", {"critic_note": ""})):
        check_eq(f"pure: {label} is no note", len(MP.critic_approval_problems(patch(**kw), stored)), 1)
    check_eq("pure: a non-empty note passes (no judgement of it)", MP.critic_approval_problems(patch(critic_note="probe read"), stored), [])
    check_eq("pure: over an approved / absent verdict -> nothing", MP.critic_approval_problems(patch(), [t9(critic_verdict="approved")])
             + MP.critic_approval_problems(patch(), [t9()]) + MP.critic_approval_problems(patch(), []), [])
    check_eq("pure: another row's unverified verdict is not this row's",
             MP.critic_approval_problems(patch(), [t9("test_other[x]", critic_verdict="unverified")]), [])
    check_eq("pure: odd inputs read as nothing", MP.critic_approval_problems({}, None) + MP.critic_approval_problems({"tests": ["x"]}, ["y"]), [])
    with Stand() as stand:
        check_eq("run: the unverified row is stored", stand.put({"tests": [t9(status="green", critic_verdict="unverified", critic_note="no probe")]})[0], 0)
        before = (stand.journal(), stand.tree())
        code, _out, err = stand.put(patch())
        check_eq("run: an `approved` with no note is refused before the commit", (code, (stand.journal(), stand.tree())), (MP.EXIT_BAD_FRAGMENT, before))
        check_in("run: ... and says what to do", "approves over a stored unverified verdict with no critic_note", err)
        check_eq("run: a note passes", stand.put(patch(critic_note="probe result read"))[0], 0)

        # the print through `run`: a pending test is moved out by a row with no slice
        stand.put({"tests": [t9("test_ten[a]", status="pending_run", case="TC-010", covers=["TC-010"])]})
        code, out, _err = stand.put({"unresolved": [{"case": "TC-010", "reason": CONTRADICTS, "thens": [1], "detail": "d"}]})
        check_eq("run: the move commits", code, 0)
        check_in("run: and `run` prints the moved row", "moved out of tests[]: test_ten[a] (case TC-010 is now wholly unresolved", out)


def pc3_provisional_beside_the_other_lists() -> None:
    """t-2181 PC-3: `provisional[]` is merged by `id` beside the other lists and folds like them. A fragment that also carries
    `tests[]`, `unresolved[]` and `then_bindings` leaves them as the merge always left them; the journal replays to the same
    manifest; a retraction naming a row nobody sent is NOT raised on replay (it is named in `unprojected_events`)."""
    prov = {"id": "P-1", "kind": "side_substitute", "what": "a mock of the payments side", "status": "open"}
    together = {"tests": [t9("test_pay[a]", provisional=["P-1"])], "provisional": [prov],
                "unresolved": [{"case": "TC-004", "reason": "pending_implementation", "instance_ids": ["test_pay[b]"]}]}
    merged, _ = MP.merge({}, together)
    check_eq("the lists of one fragment each land in their own key",
             (sorted(merged), [t["instance_id"] for t in merged["tests"]], merged["provisional"][0]["id"]),
             (["provisional", "tests", "unresolved"], ["test_pay[a]"], "P-1"))
    folded = MP.fold(journal(together, {"provisional": [{"id": "P-1", "status": "kept_by_decision"}]},
                             {"retracted_provisional": ["P-1"]}))
    check_eq("the journal replays to one row, retracted, with its first fields",
             [(r["id"], r["kind"], r["status"]) for r in folded["provisional"]], [("P-1", "side_substitute", "retracted")])
    check_eq("and the replay reports nothing unprojected", "unprojected_events" in folded, False)
    bad = MP.fold(journal({"retracted_provisional": ["P-5"]}, together))
    check_eq("a retraction of an id nobody sent is never raised on replay (the door refuses it before the commit) and retracts nothing",
             ("unprojected_events" in bad, [(r["id"], r["status"]) for r in bad["provisional"]]), (False, [("P-1", "open")]))


def main() -> None:
    pc3_provisional_beside_the_other_lists()
    ep1_39_then_row_keeps_tests()
    ep1_39_critic_approval()
    ep1_38_obligation_hash()
    tq1_18_base_outcome()
    tq1_7_helpers()
    hf3_2_b_k1_retraction_takes_the_rows()
    hf3_2_b_k4_a_spelling_a_row_still_wears()
    hf3_2_b_k8_aliases_of_a_dropped_row()
    hf3_2_b_k5_send_and_retract()
    hf3_2_b_k7_empties()
    k5a_k1_a_writer_replaces()
    k5a_k1_b_c_d_hand_units()
    k5a_k1_e_two_handed_thens()
    k5a_k1_replay()
    k5a_k1_run_prints()
    k1_retraction()
    k2_k3_refusals()
    k2b_replay()
    k4_two_reasons()
    k4b_old_events_fold()
    k8_slice_replacement()
    k8b_one_constant()
    run_end_to_end()
    finish("test_manifest_put_merge")


if __name__ == "__main__":
    main()
