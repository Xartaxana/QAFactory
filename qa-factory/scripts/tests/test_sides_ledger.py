#!/usr/bin/env python3
"""t-2181 PC-5 (spec §2.3, §1.3 first error-direction bullet, B1 B2 B5 S12): the ledger's proof-strength branch.

`ledger.plan_row_state` reads a green Then or a walked case through the sides its proof MET: `not_verified:sides_unknown` first,
then `not_verified:on_substitute`, never `passed_green` for a substituted or unknown side. Every adversarial input of the spec's
error-direction bullet is a named function here. Plus the dashboard's label of a held story (`awaiting_label`).

Mutations named, NOT run, each killed by this file: `_met_real` reading the stamp alone (the test-declaration cases); `_resolved_about`
returning [] for `about: []` (B1); the branch moved before the `failed:*` words (the red case); the branch before the deferral
(the position case); the stamp read from today's reader instead of the row (the became-real case).
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, finish  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import ledger as L  # noqa: E402

PLAN_ROW = {"ts": "TS-1", "disposition": "automate", "reason": ""}
CASES = {"TS-1": ["TC-1"]}


def test(iid: str, sides=None, covers=("TC-1",)) -> dict:
    entry = {"instance_id": iid, "test_function": iid, "covers": list(covers)}
    if sides is not None:
        entry["sides"] = sides
    return entry


def binding(iid: str, then: int = 1, about=None, case: str = "TC-1") -> dict:
    row = {"case": case, "then": then, "instance_id": iid, "status": "covered"}
    if about is not None:
        row["about"] = about
    return row


def run_row(iid: str, status: str = "passed", met=None, unknown: str = "", case: str = "TC-1") -> dict:
    row = {"instance_id": iid, "case": case, "status": status}
    if met is not None:
        row["sides_met"] = met
    if unknown:
        row["sides_unknown"] = unknown
    return row


def state(tests, bindings, rows, manual=None, unresolved=None, cases=CASES, provisional=None, triage=None) -> tuple:
    manifest = {"tests": tests, "then_bindings": bindings, "unresolved": unresolved or []}
    if provisional is not None:
        manifest["provisional"] = provisional
    report = {"results": rows}
    if manual is not None:
        report["current_manual_checks"] = manual
    return L.plan_row_state(PLAN_ROW, manifest, report, triage or {}, cases)


def word(result: tuple) -> str:
    return result[0]


STAND_SUB = {"ui": "real", "backend": "substituted"}


def empty_sides_no_about_on_stand_substitute_is_on_substitute() -> None:
    """B1: `tests[].sides: {}`, no `about`, the stamp says `backend: substituted` -> the empty claim never proves."""
    got = state([test("t1", {})], [binding("t1")], [run_row("t1", met=STAND_SUB)])
    check_eq("B1 empty sides + no about on a stand-level substitute", word(got), "not_verified:on_substitute")
    check_in("B1 ... the detail names the Then and the side", "TC-1 Then 1: backend", got[1])


def about_absent_and_empty_list_read_alike() -> None:
    for label, about in (("about absent", None), ("about: []", []), ("about of another type", {"x": 1}), ("about: ['']", [""])):
        got = state([test("t1", {})], [binding("t1", about=about)], [run_row("t1", met=STAND_SUB)])
        check_eq(f"B1 {label} falls to the union, never to nothing", word(got), "not_verified:on_substitute")


def test_row_with_no_sides_on_a_story_with_a_substituted_side() -> None:
    got = state([test("t1")], [binding("t1", about=["backend"])], [run_row("t1", met=STAND_SUB)])
    check_eq("a tests[] row with NO `sides` key on a story that has a substituted side: a missing key is not real", word(got),
             "not_verified:on_substitute")


def about_names_a_side_the_story_does_not_declare() -> None:
    got = state([test("t1", {"ui": "real"})], [binding("t1", about=["kiosk"])], [run_row("t1", met={"ui": "real"})])
    check_eq("`about` names a side nobody declared: not real", word(got), "not_verified:on_substitute")


def a_side_that_became_real_after_the_run_the_stamp_decides() -> None:
    # the test's declaration says real; the run's stamp says the side was substituted THEN (today's reader is not asked at all)
    got = state([test("t1", {"backend": "real"})], [binding("t1", about=["backend"])], [run_row("t1", met={"backend": "substituted"})])
    check_eq("declared real but stamped substituted: the stamp of the run decides", word(got), "not_verified:on_substitute")
    got = state([test("t1", {"backend": "real"})], [binding("t1", about=["backend"])], [run_row("t1", met={"backend": "real"})])
    check_eq("control: real in both reads as today", word(got), "passed_green")


def a_ui_then_on_a_mocked_backend_is_green_for_good() -> None:
    got = state([test("t1", STAND_SUB)], [binding("t1", about=["ui"])], [run_row("t1", met=STAND_SUB)])
    check_eq("`about: [ui]`, ui real, backend substituted: proven", word(got), "passed_green")


def a_real_green_beside_a_substituted_green_proves() -> None:
    tests = [test("t_sub", {"backend": "substituted"}), test("t_real", {"backend": "real"})]
    bindings = [binding("t_sub", about=["backend"]), binding("t_real", about=["backend"])]
    rows = [run_row("t_sub", met={"backend": "substituted"}), run_row("t_real", met={"backend": "real"})]
    check_eq("two instances covering one Then, one real and one substituted: the real green proves it", word(state(tests, bindings, rows)),
             "passed_green")


def evidence_of_two_tests_is_never_merged() -> None:
    """FR-18: each test is half real; together they cover both sides, alone neither does."""
    tests = [test("t_a", {"ui": "real", "backend": "substituted"}), test("t_b", {"ui": "substituted", "backend": "real"})]
    bindings = [binding("t_a", about=["ui", "backend"]), binding("t_b", about=["ui", "backend"])]
    rows = [run_row("t_a", met={"ui": "real", "backend": "real"}), run_row("t_b", met={"ui": "real", "backend": "real"})]
    check_eq("two half-real tests never prove a Then together", word(state(tests, bindings, rows)), "not_verified:on_substitute")


def a_red_on_a_substitute_stays_failed() -> None:
    got = state([test("t1", {"backend": "substituted"})], [binding("t1", about=["backend"])],
                [run_row("t1", status="failed", met={"backend": "substituted"})])
    check("a red on a substitute stays `failed:*`", word(got).startswith("failed:"), str(got))


def stamp_sides_unknown_is_not_verified() -> None:
    """S12: a stamp carrying `sides_unknown` reads `not_verified:sides_unknown`, before `on_substitute`."""
    got = state([test("t1", {"ui": "real"})], [binding("t1", about=["ui"])], [run_row("t1", unknown="the registry could not be read")])
    check_eq("S12 sides_unknown with no sides_met", word(got), "not_verified:sides_unknown")
    got = state([test("t1", {"ui": "real"})], [binding("t1", about=["ui"])],
                [run_row("t1", met={"ui": "real"}, unknown="a side row is malformed")])
    check_eq("S12 sides_unknown beside an all-real stamp is still unknown (never a pass)", word(got), "not_verified:sides_unknown")
    tests = [test("t1", {"backend": "substituted"}), test("t2", {"backend": "real"})]
    got = state(tests, [binding("t1", then=1, about=["backend"]), binding("t2", then=2, about=["backend"])],
                [run_row("t1", met={"backend": "substituted"}), run_row("t2", unknown="x")])
    check_eq("S12 one Then substituted and another unknown: unknown first", word(got), "not_verified:sides_unknown")


def manual_agent_green_on_stand_substitute_is_on_substitute() -> None:
    """B2: a walk with no `about` on a stand stamped `backend: substituted`."""
    got = state([], [], [], manual=[{"case": "TC-1", "result": "passed", "sides_met": STAND_SUB}])
    check_eq("B2 manual-agent walk, no about, stand substitute", word(got), "not_verified:on_substitute")
    got = state([], [], [], manual=[{"case": "TC-1", "result": "passed", "about": ["ui"], "sides_met": STAND_SUB}])
    check_eq("B2 manual-agent walk, about [ui], ui real: proven", word(got), "passed_green")
    got = state([], [], [], manual=[{"case": "TC-1", "result": "passed", "about": ["ui", "backend"], "sides_met": STAND_SUB}])
    check_eq("B2 manual-agent walk about the substituted side: on_substitute", word(got), "not_verified:on_substitute")
    got = state([], [], [], manual=[{"case": "TC-1", "result": "passed", "sides_unknown": "x"}])
    check_eq("B2 a walk whose stamp carries sides_unknown", word(got), "not_verified:sides_unknown")
    got = state([], [], [], manual=[{"case": "TC-1", "result": "passed"}])
    check_eq("control: an unstamped walk reads as today", word(got), "passed_green")


def an_unstamped_row_on_an_all_real_story_reads_as_today() -> None:
    check_eq("no stamp, no declaration: not read at all", word(state([test("t1")], [binding("t1")], [run_row("t1")])), "passed_green")
    check_eq("no stamp, declared real: not read at all", word(state([test("t1", {"ui": "real"})], [binding("t1")], [run_row("t1")])),
             "passed_green")
    check_eq("a stamped all-real story with an empty claim proves", word(state([test("t1", {})], [binding("t1")],
             [run_row("t1", met={"product": "real"})])), "passed_green")
    check_eq("an unstamped row whose test declares a non-real side is read conservatively",
             word(state([test("t1", {"backend": "substituted"})], [binding("t1")], [run_row("t1")])), "not_verified:on_substitute")


def a_case_with_no_covered_then_is_read_by_its_green_tests() -> None:
    got = state([test("t1", {})], [], [run_row("t1", met=STAND_SUB)])
    check_eq("no covered Then binding: the case's own green test, empty claim, stand substitute", word(got), "not_verified:on_substitute")
    check_eq("control: all-real stamp", word(state([test("t1", {})], [], [run_row("t1", met={"ui": "real"})])), "passed_green")


def a_stamped_row_that_joins_no_manifest_test_is_still_read() -> None:
    """A legacy row names its case only and joins no manifest test: its stamp alone is read (no declaration = nothing real)."""
    got = state([], [], [{"case": "TC-1", "status": "passed", "sides_met": STAND_SUB}])
    check_eq("an unjoined stamped row, case-level", word(got), "not_verified:on_substitute")
    got = state([], [binding("ghost", about=["backend"])], [run_row("ghost", met=STAND_SUB)])
    check_eq("a binding whose instance is in no manifest test, row stamped substituted", word(got), "not_verified:on_substitute")
    check_eq("control: an unjoined UNSTAMPED row reads as today", word(state([], [], [{"case": "TC-1", "status": "passed"}])), "passed_green")


def the_row_reads_the_weaker_of_its_thens() -> None:
    tests = [test("t1", STAND_SUB)]
    got = state(tests, [binding("t1", then=1, about=["ui"]), binding("t1", then=2, about=["ui", "backend"])],
                [run_row("t1", met=STAND_SUB)])
    check_eq("E-O1: Then 1 proven, Then 2 on a substitute: the row reads on_substitute", word(got), "not_verified:on_substitute")
    check_in("... naming only Then 2", "TC-1 Then 2", got[1])
    check("... and not Then 1", "Then 1" not in got[1], got[1])


def retracted_pending_row_the_run_decides() -> None:
    """B5: a pending row that stands is `pending_implementation`; once the automator retracted it, the runs decide - a green stamped
    real is `passed_green`, a red is `failed:*` (a retracted row never hides a red)."""
    pending = [{"case": "TC-1", "reason": "pending_implementation", "instance_ids": ["t1"]}]
    tests, bindings = [test("t1", {"product": "real"})], [binding("t1", about=["product"])]
    green = [run_row("t1", met={"product": "real"})]
    check_eq("the row stands: pending_implementation", word(state(tests, bindings, green, unresolved=pending)), "pending_implementation")
    check_eq("retracted + green stamped real: the run decides", word(state(tests, bindings, green)), "passed_green")
    red = [run_row("t1", status="failed", met={"product": "real"})]
    check("retracted + red: the red reads failed:*", word(state(tests, bindings, red)).startswith("failed:"), "")


def position_the_branch_is_the_last_check_before_passed_green() -> None:
    """A deferral and a stronger word above win over the branch: the branch only turns a would-be `passed_green` into the weaker word."""
    deferred = [{"case": "TC-1", "then": 2, "status": "unresolved", "reason": "deferred_by_decision:gateA"}]
    tests = [test("t1", {"backend": "substituted"})]
    got = state(tests, [binding("t1", about=["backend"])] + deferred, [run_row("t1", met={"backend": "substituted"})])
    check_eq("a deferred Then beside a substituted green stays deferred_by_decision (a `no` is never hidden)", word(got), "deferred_by_decision")
    skipped = state(tests, [binding("t1", about=["backend"])], [run_row("t1", status="skipped", met={"backend": "substituted"})])
    check("a skipped run on a substitute stays skipped", word(skipped).startswith("skipped:"), str(skipped))


def a_green_joined_only_by_the_tolerant_rule_is_read() -> None:
    """B1: the manifest's hash `ti_...` and the runner's function id never meet under the exact id; `case_stamp.run_row_for` joins them
    (the dashboard's tolerant rule). The ledger reads the row through that ONE join, so the substituted green is not `passed_green`."""
    def story(declared: dict, met: dict) -> tuple:
        entry = {"instance_id": "ti_abc", "test": "tests/a.py::test_x", "case": "TC-1", "covers": ["TC-1"], "sides": declared}
        row = {"test_id": "tests/a.py::test_x", "status": "passed", "case": "TC-1", "sides_met": met}
        return state([entry], [binding("ti_abc", about=["backend"])], [row])
    got = story({"backend": "substituted"}, {"ui": "real", "backend": "substituted"})
    check_eq("B1 a row joined only by the tolerant rule reads on_substitute, never passed_green", word(got), "not_verified:on_substitute")
    check_in("B1 ... naming the Then and the side", "TC-1 Then 1: backend", got[1])
    check_eq("control: the same join, real on both sides, reads passed_green", word(story({"backend": "real"}, {"backend": "real"})), "passed_green")
    spare = {"instance_id": "ti_abc", "test": "tests/a.py::test_x[json]", "case": "TC-1", "covers": ["TC-1"], "sides": {"backend": "substituted"}}
    row = {"test_id": "tests/a.py::test_x[json]", "status": "passed", "case": "TC-1", "sides_met": {"backend": "substituted"}}
    check_eq("B1 a `[param]` row joins by the same rule and is read",
             word(state([spare], [binding("ti_abc", about=["backend"])], [row])), "not_verified:on_substitute")


def a_covered_then_with_no_joined_row_reads_the_cases_green_rows() -> None:
    """B1: a covered Then whose bound instance has no green joined row is NEVER dropped - the case's green rows are its proofs."""
    sub, real = {"ui": "real", "backend": "substituted"}, {"ui": "real", "backend": "real"}
    # P1: the bound test has no row; a legacy row that names the case only
    p1 = state([test("t1", {})], [binding("t1")], [{"case": "TC-1", "status": "passed", "sides_met": sub}])
    check_eq("P1 a legacy substituted row beside a Then whose test has no row reads on_substitute", word(p1), "not_verified:on_substitute")
    check_eq("P1 control: the legacy row stamped real proves", word(state([test("t1", {})], [binding("t1")],
             [{"case": "TC-1", "status": "passed", "sides_met": real}])), "passed_green")
    # P2: the bound test has no row; a manifest test no binding names ran green on a substitute
    tests = [test("t1", {}), test("t2", {"backend": "substituted"})]
    p2 = state(tests, [binding("t1")], [run_row("t2", met=sub)])
    check_eq("P2 an unbound test's substituted green beside a Then with no row reads on_substitute", word(p2), "not_verified:on_substitute")
    check_eq("P2 control: that test real on every side proves", word(state([test("t1", {}), test("t2", {"backend": "real"})],
             [binding("t1")], [run_row("t2", met=real)])), "passed_green")
    check_eq("P3 control: the bound test's own substituted row reads on_substitute", word(state([test("t1", {"backend": "substituted"})],
             [binding("t1")], [run_row("t1", met=sub)])), "not_verified:on_substitute")
    two = state([test("t1", {}), test("t2", {"backend": "substituted"}), test("t3", {"backend": "real"})], [binding("t1")],
                [run_row("t2", met=sub), run_row("t3", met=real)])
    check_eq("the fallback rows are read one by one: a real green among them proves (never merged)", word(two), "passed_green")


def a_stamp_that_is_not_an_object_is_unknown() -> None:
    """B2: a `sides_met` that is no object is a record that cannot be read: `sides_unknown`, never a pass (AR-28, FR-59)."""
    got = ("", "")
    for label, bad in (("a string", "substituted"), ("a list", ["backend"]), ("null", None), ("a number", 1)):
        got = state([test("t1")], [binding("t1")], [dict(run_row("t1"), sides_met=bad)])
        check_eq(f"B2 a run row whose sides_met is {label} reads sides_unknown", word(got), "not_verified:sides_unknown")
    check_in("B2 ... the detail says the record could not be read", "could not be read", got[1])
    walk = state([], [], [], manual=[{"case": "TC-1", "result": "passed", "sides_met": "substituted"}])
    check_eq("B2 a walk whose sides_met is no object reads sides_unknown", word(walk), "not_verified:sides_unknown")
    check_eq("control: sides_met {} on an undeclared test still proves (an empty claim proves when the stamp holds no non-real side)",
             word(state([test("t1")], [binding("t1")], [run_row("t1", met={})])), "passed_green")
    check_eq("control: sides_met {} on a walk proves", word(state([], [], [], manual=[{"case": "TC-1", "result": "passed", "sides_met": {}}])),
             "passed_green")


# --- J-C7: not_verified:placeholder_open (PC-5 fix round, L1) -------------------------------------------------------------

def prow(pid="P-1", status="open", deps=None, **more) -> dict:
    """A J-C5 accounting row: a placeholder locator the first look marked."""
    row = {"id": pid, "kind": "placeholder_locator", "assumed_from": "first_look:R-1", "settles_on": "ui", "dependents": deps if deps is not None else [],
           "what": "the locator of a button that is not built yet"}
    if status is not None:
        row["status"] = status
    row.update(more)
    return row


def marked(iid: str, *ids, sides=None) -> dict:
    entry = test(iid, sides)
    entry["provisional"] = list(ids)
    return entry


def then1() -> list:
    return [{"case": "TC-1", "then": 1}]


def then_in_dependents_is_placeholder_open_whatever_test() -> None:
    got = state([test("t_clean")], [binding("t_clean")], [run_row("t_clean")], provisional=[prow(deps=then1())])
    check_eq("a Then named in an open row's dependents reads placeholder_open, though a CLEAN test covers it", word(got),
             "not_verified:placeholder_open")
    check_eq("... the state is the ledger's constant", word(got), L.PLACEHOLDER_OPEN_STATE)
    check_in("... the detail names the Then and the row", "TC-1 Then 1: P-1", got[1])
    check_eq("control: with no provisional row the same green is passed_green", word(state([test("t_clean")], [binding("t_clean")], [run_row("t_clean")])),
             "passed_green")
    ordinary = prow(deps=then1())
    ordinary.pop("assumed_from")
    check_eq("control: a placeholder row that is not J-C5 (no first_look reference) is not read here",
             word(state([test("t_clean")], [binding("t_clean")], [run_row("t_clean")], provisional=[ordinary])), "passed_green")


def green_placeholder_test_never_proves() -> None:
    """J-C7 (2): the green of a test whose `provisional` names an open row proves no Then, outside `dependents` too."""
    got = state([marked("t1", "P-1")], [binding("t1", then=2)], [run_row("t1")], provisional=[prow(deps=[])])
    check_eq("a green on an unsettled placeholder proves no Then", word(got), "not_verified:placeholder_open")
    check_in("... naming the Then and the row", "TC-1 Then 2: P-1", got[1])
    check_eq("control: the same test unmarked proves", word(state([test("t1")], [binding("t1", then=2)], [run_row("t1")], provisional=[prow(deps=[])])),
             "passed_green")
    case_level = state([marked("t1", "P-1")], [], [run_row("t1")], provisional=[prow()])
    check_eq("a case with no covered Then and only a placeholder test's green is placeholder_open too", word(case_level), "not_verified:placeholder_open")


def then_outside_dependents_proved_only_by_clean_binding() -> None:
    tests = [marked("t_mark", "P-1"), test("t_clean")]
    both = state(tests, [binding("t_mark", then=2), binding("t_clean", then=2)], [run_row("t_mark"), run_row("t_clean")], provisional=[prow()])
    check_eq("a clean green beside a marked one proves the Then", word(both), "passed_green")
    only = state(tests, [binding("t_mark", then=2)], [run_row("t_mark"), run_row("t_clean")], provisional=[prow()])
    check_eq("only the marked test is bound: placeholder_open", word(only), "not_verified:placeholder_open")
    unrun = state(tests, [binding("t_mark", then=2), binding("t_clean", then=2)], [run_row("t_mark")], provisional=[prow()])
    check_eq("the clean binding has no row: the marked green alone is no proof", word(unrun), "not_verified:placeholder_open")


def red_stays_failed() -> None:
    """The position: placeholder_open loses to `failed:*`."""
    got = state([marked("t1", "P-1")], [binding("t1")], [run_row("t1", status="failed")], provisional=[prow(deps=then1())])
    check("a red on a test with an open placeholder stays failed:*", word(got).startswith("failed:"), str(got))


def flaky_placeholder_test_is_placeholder_open() -> None:
    """The position: placeholder_open beats flaky and skipped."""
    flaky = {"triage": [{"instance_id": "t1", "case": "TC-1", "verdict": "FLAKY"}]}
    control = state([dict(test("t1"), case="TC-1")], [binding("t1")], [run_row("t1")], triage=flaky)
    check_eq("control: an unfixed flaky test with no placeholder reads not_verified_flaky", word(control), "not_verified_flaky")
    got = state([dict(marked("t1", "P-1"), case="TC-1")], [binding("t1")], [run_row("t1")], provisional=[prow(deps=then1())], triage=flaky)
    check_eq("a flaky test whose Then stands behind an open placeholder reads placeholder_open", word(got), "not_verified:placeholder_open")


def handed_placeholder_test_is_placeholder_open() -> None:
    """J-C7 position: the branches ABOVE `failed:*` (an unresolved hand-off, an env block, the manual hand-off of a case with no run) never
    read in place of `placeholder_open`; a red still outranks them."""
    handed = {"case": "TC-1", "reason": "handed_to_person", "detail": "ui: the person checks it"}
    control = state([test("t1")], [binding("t1")], [], unresolved=[handed])
    check_eq("control: a hand-off with no placeholder reads not_executed:handed_to_person", word(control), "not_executed:handed_to_person")
    got = state([marked("t1", "P-1")], [binding("t1")], [], unresolved=[handed], provisional=[prow(deps=then1())])
    check_eq("a Then behind an open placeholder whose case is handed reads placeholder_open", word(got), "not_verified:placeholder_open")
    red = state([marked("t1", "P-1")], [binding("t1")], [run_row("t1", status="failed")], unresolved=[handed], provisional=[prow(deps=then1())])
    check("a red outranks the hand-off and the placeholder: failed:*", word(red).startswith("failed:"), str(red))
    blocked = {"case": "TC-1", "reason": "blocked_by_env", "instance_ids": ["t1"]}
    control_env = state([test("t1")], [binding("t1")], [], unresolved=[blocked])
    check("control: an env block with no placeholder reads env_blocked", word(control_env).startswith("env_blocked"), str(control_env))
    got_env = state([marked("t1", "P-1")], [binding("t1")], [], unresolved=[blocked], provisional=[prow(deps=then1())])
    check_eq("a Then behind an open placeholder whose test is env-blocked reads placeholder_open", word(got_env), "not_verified:placeholder_open")
    plan = dict(PLAN_ROW, disposition="manual-human")
    report = {"results": [], "manual_human": [{"case": "TC-1", "evidence": "work/evidence/x"}]}   # the real key (`C.manual_human_evidence`)
    plain = {"tests": [test("t1")], "then_bindings": [binding("t1")], "unresolved": []}
    check_eq("control: the manual hand-off of a case with no run, no placeholder row, reads handed_to_person",
             word(L.plan_row_state(plan, plain, report, {}, CASES)), "not_executed:handed_to_person")
    held = {"tests": [marked("t1", "P-1")], "then_bindings": [binding("t1")], "unresolved": [], "provisional": [prow(deps=then1())]}
    check_eq("the manual hand-off of a case behind an open placeholder reads placeholder_open (the branch the control does not reach)",
             word(L.plan_row_state(plan, held, report, {}, CASES)), "not_verified:placeholder_open")
    settled = state([marked("t1", "P-1")], [binding("t1")], [], unresolved=[handed],
                    provisional=[prow(status="settled_matched", deps=then1(), evidence={"run": "blk-1"})])
    check_eq("a settled row (with its run) holds nothing: the hand-off reads as a hand-off", word(settled), "not_executed:handed_to_person")


def placeholder_never_excuses_run() -> None:
    """A test whose Then stands behind an open placeholder with NO run row still reads what no run says, never a pass and never
    `placeholder_open` standing in for the missing run (the S5 exit owes the run, J-C9 (d))."""
    got = state([marked("t1", "P-1")], [binding("t1")], [], provisional=[prow(deps=then1())])
    check_eq("no run row: not_executed, the placeholder excuses nothing", word(got), "not_executed:no result recorded for this row's cases")


def skipped_placeholder_test_is_placeholder_open() -> None:
    control = state([test("t1")], [binding("t1")], [run_row("t1", status="skipped")])
    check("control: a skipped run with no placeholder reads skipped:*", word(control).startswith("skipped:"), str(control))
    got = state([marked("t1", "P-1")], [binding("t1")], [run_row("t1", status="skipped")], provisional=[prow(deps=then1())])
    check_eq("a skipped run of a test behind an open placeholder reads placeholder_open, not skipped", word(got), "not_verified:placeholder_open")


def skip_decision_is_placeholder_open() -> None:
    """F3 (J-C7 position): a `disposition: skip` / `unverifiable` row never reads `skipped:*` in place of `placeholder_open`; a red wins."""
    tests, bindings, held = [marked("t1", "P-1")], [binding("t1")], [prow(deps=then1())]
    manifest = {"tests": tests, "then_bindings": bindings, "unresolved": [], "provisional": held}
    for disposition in ("skip", "unverifiable"):
        plan = dict(PLAN_ROW, disposition=disposition, reason="out of scope")
        got = L.plan_row_state(plan, manifest, {"results": [run_row("t1")]}, {}, CASES)
        check_eq(f"`{disposition}` behind an open placeholder, green test: placeholder_open", word(got), "not_verified:placeholder_open")
        red = L.plan_row_state(plan, manifest, {"results": [run_row("t1", status="failed")]}, {}, CASES)
        check(f"`{disposition}` behind an open placeholder, red test: failed:*", word(red).startswith("failed:"), str(red))
        clean = {"tests": [test("t1")], "then_bindings": bindings, "unresolved": []}
        control = L.plan_row_state(plan, clean, {"results": [run_row("t1")]}, {}, CASES)
        check(f"control: `{disposition}` with no placeholder still reads skipped:*", word(control).startswith("skipped:"), str(control))


def placeholder_beats_on_substitute() -> None:
    got = state([marked("t1", "P-1", sides={"backend": "substituted"})], [binding("t1", about=["backend"])],
                [run_row("t1", met={"backend": "substituted"})], provisional=[prow(deps=then1())])
    check_eq("both apply: placeholder_open wins", word(got), "not_verified:placeholder_open")


def settled_row_with_run_proves() -> None:
    for status in ("settled_matched", "settled_edited"):
        got = state([marked("t1", "P-1")], [binding("t1")], [run_row("t1")], provisional=[prow(status=status, deps=then1(), evidence={"run": "blk-1"})])
        check_eq(f"a row {status} with an evidence.run no longer holds the Then: the run proves it", word(got), "passed_green")
    gone = state([marked("t1", "P-1")], [binding("t1")], [run_row("t1")], provisional=[prow(status="retracted", deps=then1())])
    check_eq("a retracted row holds nothing", word(gone), "passed_green")


def settled_without_evidence_run_stays_open() -> None:
    for label, extra in (("no evidence", {}), ("evidence with no run", {"evidence": {"home_hash_after": "x"}}),
                         ("a blank run", {"evidence": {"run": "  "}}), ("evidence that is no object", {"evidence": "blk-1"})):
        got = state([marked("t1", "P-1")], [binding("t1")], [run_row("t1")], provisional=[prow(status="settled_matched", deps=then1(), **extra)])
        check_eq(f"settled_matched with {label} stays open", word(got), "not_verified:placeholder_open")


def missing_status_reads_open() -> None:
    for label, status in (("a missing status", None), ("an unknown word", "whatever")):
        got = state([marked("t1", "P-1")], [binding("t1")], [run_row("t1")], provisional=[prow(status=status, deps=then1())])
        check_eq(f"{label} reads open", word(got), "not_verified:placeholder_open")
    # t-2277 W3 (owner 11.11.2026, critic F8): what the person decided to keep stays kept; its green stays green (the report marks it on a mock)
    kept = state([marked("t1", "P-1")], [binding("t1")], [run_row("t1")], provisional=[prow(status="kept_by_decision", deps=then1())])
    check_eq("kept_by_decision on a real side stays kept: the green is not held open", word(kept), "passed_green")


def every_not_verified_state_of_the_proof_branches_has_its_own_kind() -> None:
    """The prefix row `not_verified` reads kind `decided_elsewhere` (verdict `none`): a state with no exact row counts as no debt.
    Reads the ledger's CONSTANTS, not a copy of their text."""
    import delivery_verdict as DV
    for constant, kind in ((L.ON_SUBSTITUTE_STATE, "on_substitute"), (L.SIDES_UNKNOWN_STATE, "sides_unknown"),
                           (L.PLACEHOLDER_OPEN_STATE, "placeholder_open")):
        got = DV.kind_of_state(constant)
        check_eq(f"{constant} is its own kind, never decided_elsewhere", got, kind)
        check_eq(f"{constant}: that kind is `after_checks`", DV.verdict_of_kind(got), "after_checks")
    check_eq("the placeholder kind is the product's (J-C5 blocked_by: product)", DV.owner_of_kind("placeholder_open"), "product")
    check_eq("control: an undeclared not_verified state still falls to the prefix row", DV.kind_of_state("not_verified:something_new"), "decided_elsewhere")


def the_report_words_of_the_three_states_are_exact_rows() -> None:
    """L3 (FR-6): each state reads its own words in the delivery summary, never the generic `not verified`."""
    import delivery_summary as DS
    for state_name in (L.ON_SUBSTITUTE_STATE, L.SIDES_UNKNOWN_STATE, L.PLACEHOLDER_OPEN_STATE):
        words, known = DS.state_words(state_name)
        check(f"{state_name} has exact words, not the prefix fallback", known and not words.startswith("not verified"), words)
        check(f"{state_name} words never print the code", "not_verified" not in words and "_" not in words, words)


def the_dashboard_label_of_a_held_story() -> None:
    import factory_dashboard as FD
    now = datetime(2026, 11, 11, 12, 0, 0)
    check_eq("not held: no label", FD.awaiting_label({}, now), "")
    check_eq("held with no cause: the default cause words, with the age", FD.awaiting_label({"awaiting": {"since": "2026-11-08T12:00:00"}}, now),
             "waiting for a fix, 3 days")
    check_eq("first_look_stop: its own words", FD.awaiting_label({"awaiting": {"cause": "first_look_stop", "since": "2026-11-10T11:00:00"}}, now),
             "stopped after the first look: the feature does not work yet, 1 day")
    check_in("stopped: the label says it was stopped", "the person stopped waiting",
             FD.awaiting_label({"awaiting": {"since": "2026-11-11T11:00:00", "stopped": {"at": "x", "words": "no"}}}, now))
    check_eq("an unreadable `since`: the label without a number", FD.awaiting_label({"awaiting": {"since": "yesterday"}}, now), "waiting for a fix")
    check_eq("a pipeline that is no object: no label", FD.awaiting_label(None, now), "")


def main() -> None:
    empty_sides_no_about_on_stand_substitute_is_on_substitute()
    about_absent_and_empty_list_read_alike()
    test_row_with_no_sides_on_a_story_with_a_substituted_side()
    about_names_a_side_the_story_does_not_declare()
    a_side_that_became_real_after_the_run_the_stamp_decides()
    a_ui_then_on_a_mocked_backend_is_green_for_good()
    a_real_green_beside_a_substituted_green_proves()
    evidence_of_two_tests_is_never_merged()
    a_red_on_a_substitute_stays_failed()
    stamp_sides_unknown_is_not_verified()
    manual_agent_green_on_stand_substitute_is_on_substitute()
    an_unstamped_row_on_an_all_real_story_reads_as_today()
    a_case_with_no_covered_then_is_read_by_its_green_tests()
    a_stamped_row_that_joins_no_manifest_test_is_still_read()
    the_row_reads_the_weaker_of_its_thens()
    retracted_pending_row_the_run_decides()
    position_the_branch_is_the_last_check_before_passed_green()
    a_green_joined_only_by_the_tolerant_rule_is_read()
    a_covered_then_with_no_joined_row_reads_the_cases_green_rows()
    a_stamp_that_is_not_an_object_is_unknown()
    then_in_dependents_is_placeholder_open_whatever_test()
    green_placeholder_test_never_proves()
    then_outside_dependents_proved_only_by_clean_binding()
    red_stays_failed()
    flaky_placeholder_test_is_placeholder_open()
    handed_placeholder_test_is_placeholder_open()
    placeholder_never_excuses_run()
    skipped_placeholder_test_is_placeholder_open()
    skip_decision_is_placeholder_open()
    placeholder_beats_on_substitute()
    settled_row_with_run_proves()
    settled_without_evidence_run_stays_open()
    missing_status_reads_open()
    every_not_verified_state_of_the_proof_branches_has_its_own_kind()
    the_report_words_of_the_three_states_are_exact_rows()
    the_dashboard_label_of_a_held_story()
    finish("test_sides_ledger")


if __name__ == "__main__":
    main()
