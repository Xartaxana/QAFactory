#!/usr/bin/env python3
"""HF4-11: the case critic says `reject` only for a failing case; its concerns travel to the S5 automator.

The owner's word (28.10.2026): a concern that is not critical is passed on and the automator takes it into account when it
automates the case. The real round is the one run 12586 recorded (fixtures/run-12586-concerns): round 3 reads `Verdict: reject`
beside 11 reviewed rows whose cells are all approving (5 of them `approve_with_concerns`, in 6 cases) and the words "No case
fails". Expectations come from that recorded round and from the rule, not from the code's output (FR-58).

Keys: K1 the round as recorded is refused with a door (the critic rewrites the `Verdict:` line), never read as accepted and never
rewritten by code (FR-35); K2 the corrected round passes; K3 the SEAM - the corrected round -> `carried_concerns` ->
`s5_plan.remarks_of` -> the automator's window brief shows each concern -> C12 refuses a form with no `plan_remarks` row for it;
K4 gate A prints the line; K5 the edges; K6 the critic's card says the rule (key presence, with a negative control).
Each mutation names the key that kills it: `_round_word_rule` rewrites the word -> K1; `_round_word_rule` removed -> K1;
`carried_concerns` left out of `remarks_of` -> K3; a concern taken from bytes the receipt did not measure -> K5.
"""
import contextlib
import hashlib
import io
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import FIXTURES, SCRIPTS, check, check_eq, check_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import controller as CT  # noqa: E402
import critic_rollcall as R  # noqa: E402
import gate_brief as GB  # noqa: E402
import s5_plan as SP  # noqa: E402
import s5_precheck as P  # noqa: E402

import test_s5_plan as BASE  # noqa: E402  (its fixture: s5_story; its checks run only under its own __main__)

FIX = FIXTURES / "run-12586-concerns"
FINDINGS_REL = "work/test-cases/integrations/critic-findings.md"
ALL_CASES = ["TC-001", "TC-002", "TC-004", "TC-005", "TC-006", "TC-007", "TC-008", "TC-009", "TC-011", "TC-012", "TC-014"]
CONCERN_CASES = ["TC-002", "TC-004", "TC-005", "TC-007", "TC-011", "TC-014"]    # the cells `approve_with_concerns` of round 3
RECORDED = (FIX / "critic-findings.md").read_bytes()
REJECT_LINE = b"Verdict: reject\n"
FIXED = RECORDED.replace(REJECT_LINE, b"Verdict: approve_with_concerns\n", 1)     # the ONE line the critic would rewrite


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def word_of(data: bytes, cases=ALL_CASES, why=None, receipts=()):
    return R.scoped_verdict(data, sha(data), set(cases), why=why, receipts=receipts)


def silent(call):
    """`(result, what the call wrote on stderr)`."""
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        result = call()
    return result, err.getvalue()


# --- K1 / K2: the word of the round ------------------------------------------------------------------------

def k1_k2_the_word():
    check("the recorded round is what the spec says: reject over cells with no reject", RECORDED.count(REJECT_LINE) == 1
          and b"| reject |" not in RECORDED.split(b"## Roll-call")[1].split(b"\n# Case critic findings")[0])
    check_eq("the corrected round differs in that line only (the third line of the file)",
             [(a, b) for a, b in zip(RECORDED.splitlines(), FIXED.splitlines()) if a != b],
             [(b"Verdict: reject", b"Verdict: approve_with_concerns")])
    why = []
    got = word_of(RECORDED, why=why)
    check_eq("K1: the round as recorded is partial over all its cases (not accepted, not approve_with_concerns)",
             got, ("partial", set(ALL_CASES)))
    check_eq("K1: the reason that decided comes first and is the rule's", why[0][0], "round_word_rule")
    check_in("K1: ... and it names the door - the `Verdict:` line", "rewrite the `Verdict:` line", why[0][1])
    check_in("K1: ... and says no case fails", "no case of it fails", why[0][1])
    check("K1: the critic's word is not rewritten - no reason says approve_with_concerns was read", all(
        basis != "column" for basis, _ in why) and len(why) == 1)
    one = word_of(RECORDED, cases=["TC-014"])
    check_eq("K1: a plan row's own cases get the same refusal", one, ("partial", {"TC-014"}))
    why2 = []
    got2 = word_of(FIXED, why=why2)
    check_eq("K2: the same round with `Verdict: approve_with_concerns` (new receipt) is accepted", got2, ("accepted", set(ALL_CASES)))
    check_eq("K2: ... with no reason", why2, [])
    check_eq("K2: the receipt of the OLD bytes no longer measures the corrected file", word_of(FIXED)[0], "accepted")
    stale = R.scoped_verdict(FIXED, sha(RECORDED), set(ALL_CASES))
    check_eq("K2: a receipt measured on the recorded bytes does not read the corrected file (I3)", stale[0], "partial")
    # a new round on TOP (the door the card names): the earlier bytes stay, the new receipt reads only the top round
    top = ("# Case critic findings - TP1-12586 - round 4 (dispatch S4-qa-case-critic-4)\n\nVerdict: approve_with_concerns\n\n"
           "## Roll-call\n\n| plan row | case | reviewed | verdict | note |\n|---|---|---|---|---|\n"
           "| TS-14 | TC-014 | yes | approve_with_concerns | F-1 origin project |\n\n").encode("utf-8")
    on_top = top + RECORDED
    check_eq("K2: the door - a new round on top of the recorded file - is read alone and accepted",
             R.scoped_verdict(on_top, sha(on_top), {"TC-014"}, receipts=[sha(RECORDED)]), ("accepted", {"TC-014"}))


# --- K3: the seam, recorded round -> automator ---------------------------------------------------------------

def critic_dispatch(identifier, data, role="qa-case-critic", status="accepted", stage="S4"):
    return {"id": identifier, "stage": stage, "role": role, "status": status, "scope": list(ALL_CASES),
            "evidence_refs": [{"path": FINDINGS_REL, "sha256": sha(data)}]}


WINDOWS = [{"index": 1, "surface": "other", "scope": ALL_CASES[:4]}, {"index": 2, "surface": "other", "scope": ALL_CASES[4:8]},
           {"index": 3, "surface": "other", "scope": ALL_CASES[8:]}]


@contextlib.contextmanager
def controller_cut():
    """The controller's side of a slice, fixed: the S5 scope is the 11 cases and the cut is three windows (the real cut is
    `Controller.s5_windows_for`, covered by test_s5_plan_check; this file asks what the slice does with the remarks)."""
    def rows(self, state=None):
        return {case: {"TS-" + case[-2:]} for case in ALL_CASES}, {}, "fixture"
    with patch.object(CT.Controller, "state", lambda self: {"dispatches": {}}),             patch.object(CT.Controller, "_case_rows", rows),             patch.object(CT.Controller, "_cases_by_disposition", lambda self, mapping, dispositions: {"automate": list(ALL_CASES)}),             patch.object(CT.Controller, "s5_windows_for",
                         lambda self, plan, state=None, scope=None, mapping=None: ([dict(w) for w in WINDOWS], {"grown": [], "why": "fixed"})):
        yield


def story(root, data):
    """A story folder with the recorded plan and the findings file on disk; the state the slice is read with holds the accepted
    S4 critic dispatch whose receipt measured `data`."""
    BASE.put(root, FINDINGS_REL, data)
    BASE.put(root, SP.PLAN_REL, (FIX / "s5-plan.json").read_bytes())
    return {"dispatches": {"S4-qa-case-critic-3": critic_dispatch("S4-qa-case-critic-3", data)}}


def k3_the_seam():
    root = temp_dir("qa-hf4-11-seam-")
    approving = FIXED.replace(b"| approve_with_concerns |", b"| approve |")
    control = temp_dir("qa-hf4-11-ctl-")
    try:
        state = story(root, FIXED)
        found = SP.remarks_of(root, state)
        check_eq("K3: the concerns of the corrected round are CC-1..6, one per `approve_with_concerns` row, in the rows' order",
                 [(r["id"], r["case"]) for r in found], [(f"CC-{n}", case) for n, case in enumerate(CONCERN_CASES, start=1)])
        by_case = {r["case"]: r for r in found}
        check_eq("K3: the problem is the row's note word for word (TC-002)", by_case["TC-002"]["problem"], "F-2 flag precondition")
        check_eq("K3: ... (TC-014)", by_case["TC-014"]["problem"], "F-1 origin project; F-2 stale plan row")
        check_eq("K3: a remark has the keys of the chain's shape, kind `remark`, no test and no Then",
                 (sorted(by_case["TC-014"]), by_case["TC-014"]["kind"], by_case["TC-014"]["test"], by_case["TC-014"]["then"],
                  by_case["TC-014"]["review"]),
                 (sorted(["id", "case", "test", "then", "kind", "check", "problem", "expected", "fix", "review"]), "remark",
                  None, None, "S4-qa-case-critic-3"))
        with controller_cut():
            piece = SP.window_slice(root, cases=["TC-014"], state=state)
            first = SP.window_slice(root, 1, state)
            import brief_pack as BP
            lines = BP.plan_lines(root, root.name, "W1", ["TC-014"], state, False)
        mine = {r["id"]: r for r in piece["remarks"]}
        check_eq("K3: the window of TC-014 holds the concerns of ITS cases only (TC-011 and TC-014), placed by the case",
                 {key: value["placement"] for key, value in mine.items()}, {"CC-5": "window", "CC-6": "window"})
        check_eq("K3: window 1 (TC-001, 002, 004, 005) holds the concerns of its cases, not those of the later windows",
                 [r["id"] for r in first["remarks"]], ["CC-1", "CC-2", "CC-3"])
        brief = SP.render_slice(piece)
        check_in("K3: the automator's window brief prints the concern for its case", "CC-6 [remark] case TC-014", brief)
        check_in("K3: ... with the critic's words", "F-1 origin project; F-2 stale plan row", brief)
        check("K3: brief_pack's head counts the remarks of the window, the concerns among them",
              any("2 remarks for this window" in line for line in lines["head"]), lines["head"])

        def conform(rows):
            findings, notes = [], []
            P._conform(root, {"tests": [], "then_bindings": []}, piece, {"plan_remarks": rows, "deviations": [], "origins": {}},
                       findings, notes)
            return [f["message"] for f in findings if "(C12)" in f["message"]]
        rows = [{"id": r["id"], "row": "applied", "reason": "done"} for r in piece["remarks"]]
        check_eq("K3: a row for every remark of the window - no C12 finding", conform(rows), [])
        missing = conform([row for row in rows if row["id"] != "CC-6"])
        check("K3: no row for CC-6 - C12 names it", len(missing) == 1 and "plan remark CC-6 has no row" in missing[0], missing)

        # the negative control: a round of approvals only carries nothing
        check("control: the replaced cells are what the control claims",
              approving.count(b"| approve_with_concerns |") == 0 and approving != FIXED)
        state = story(control, approving)
        check_eq("K3 control: a round of `approve` cells has no CC remark", SP.remarks_of(control, state), [])
        with controller_cut():
            quiet = SP.render_slice(SP.window_slice(control, cases=["TC-014"], state=state))
        check_in("K3 control: ... and the window brief says it has no remarks", "no remarks for this window", quiet)
    finally:
        cleanup(root)
        cleanup(control)


# --- K4: gate A ---------------------------------------------------------------------------------------------

def k4_gate_a_line():
    root = temp_dir("qa-hf4-11-gate-")
    try:
        state = story(root, FIXED)
        BASE.put(root, "state/controller.json", "{}")      # the brief reads the projection only where a controller state exists
        with patch.object(CT.Controller, "state", return_value=state):
            cases = GB.carried_concern_cases(root)
        check_eq("K4: the cases of the concerns, once each, in the rows' order", cases, CONCERN_CASES)
        text = "\n".join(GB._head_lines({"task": "T", "carried_concern_cases": cases}))
        check_in("K4: gate A prints the line", "Concerns carried to automation: TC-002, TC-004, TC-005, TC-007, TC-011, TC-014", text)
        check("K4: ... and none when no concern is carried", "Concerns carried" not in "\n".join(GB._head_lines({"task": "T"})))
        check("K4: ... or when the list is empty", "Concerns carried" not in "\n".join(
            GB._head_lines({"task": "T", "carried_concern_cases": []})))
        check_eq("K4: a story with no controller state prints nothing and does not raise", GB.carried_concern_cases(temp_dir("qa-hf4-11-none-")), [])
    finally:
        cleanup(root)


# --- K5: the edges --------------------------------------------------------------------------------------------

def table(declared, rows, column=True):
    text = f"# Critic findings - round 1 - dispatch d1\n\nVerdict: {declared}\n\n## Roll-call\n\n"
    text += ("| plan row | case | reviewed | verdict | note |\n|---|---|---|---|---|\n" if column
             else "| plan row | case | reviewed | note |\n|---|---|---|---|\n")
    for case, reviewed, word, note in rows:
        row = "TS-" + case.split("-")[-1]
        text += f"| {row} | {case} | {reviewed} | {word} | {note} |\n" if column else f"| {row} | {case} | {reviewed} | {note} |\n"
    return (text + "\n").encode("utf-8")


def k5_edges():
    failing = table("reject", [("TC-1", "yes", "approve_with_concerns", "c"), ("TC-2", "yes", "reject", "fails")])
    check_eq("K5: a `reject` cell and the word `reject`: reject, no refusal about the word",
             word_of(failing, cases=["TC-1", "TC-2"]), ("reject", {"TC-1", "TC-2"}))
    why = []
    word_of(failing, cases=["TC-2"], why=why)
    check("K5: ... and the reason is the cell's, not the rule's", why and why[0][0] == "column", why)
    check_eq("K5: a failing case is never approved, whatever word the round declares (Verdict: approve_with_concerns)",
             word_of(table("approve_with_concerns", [("TC-2", "yes", "reject", "fails")]), cases=["TC-2"])[0], "reject")
    check_eq("K5: ... even a cell written in another case (`Reject`)",
             word_of(table("approve_with_concerns", [("TC-2", "yes", "Reject", "fails")]), cases=["TC-2"])[0], "reject")
    no_column = table("reject", [("TC-1", "yes", "", "seen")], column=False)
    why = []
    check_eq("K5: no `verdict` column: the round's word stands, reject as declared, no rule refusal",
             word_of(no_column, cases=["TC-1"], why=why), ("reject", {"TC-1"}))
    check_eq("K5: ... its reason is the older one", [basis for basis, _ in why], ["round_word"])
    unread = table("reject", [("TC-1", "no", "approve", "x"), ("TC-2", "yes", "approve", "x")])
    why = []
    check_eq("K5: a row `reviewed: no` is partial the old way - the rule is not asked",
             word_of(unread, cases=["TC-1", "TC-2"], why=why)[0], "partial")
    check_eq("K5: ... for `no_review`", why[0][0], "no_review")
    blank = table("reject", [("TC-1", "yes", "", "x"), ("TC-2", "yes", "", "y")])
    why = []
    word_of(blank, cases=["TC-1"], why=why)
    check("K5: a `verdict` column empty on every row has no cells to contradict `reject`: the older rule, unreadable",
          why and why[0][0] == "unreadable", why)
    check_eq("K5: the rule itself - not `reject`, or a table without the column, or any unreviewed / failing row: None",
             [R._round_word_rule([{"verdict": "approve", "reviewed": True}], d) for d in ("approve", "partial", "approve_with_concerns")]
             + [R._round_word_rule([{"verdict": None, "reviewed": True}], "reject"),
                R._round_word_rule([{"verdict": "approve", "reviewed": None}], "reject"),
                R._round_word_rule([{"verdict": "approve", "reviewed": True}, {"verdict": "reject", "reviewed": True}], "reject"),
                R._round_word_rule([], "reject")], [None] * 7)
    check("K5: ... and for `reject` over approving reviewed cells it names the rule",
          R._round_word_rule([{"verdict": "approve", "reviewed": True}], "reject")[0] == "round_word_rule")

    # carried_concerns
    data = FIXED
    got, err = silent(lambda: R.carried_concerns(data, sha(data), review="S4-qa-case-critic-3"))
    check_eq("K5: the recorded round gives six concerns, in order", [(c["id"], c["case"]) for c in got],
             [(f"CC-{n}", case) for n, case in enumerate(CONCERN_CASES, start=1)])
    check_eq("K5: ... nothing on stderr when the round is sound", err, "")
    check_eq("K5: the dispatch of the critic is carried", {c["review"] for c in got}, {"S4-qa-case-critic-3"})
    wrong = data + b"\nan edit after the review\n"
    got, err = silent(lambda: R.carried_concerns(wrong, sha(data)))
    check_eq("K5: a receipt measured on other bytes: no concern is taken (I3)", got, [])
    check_in("K5: ... and stderr says why", "no concern carried", err)
    check_in("K5: ... naming the mismatch", "no end of the file matches the receipt", err)
    got, err = silent(lambda: R.carried_concerns(data, ""))
    check_eq("K5: a receipt with no hash measured nothing: none, said", (got, "no concern carried" in err), ([], True))
    got, err = silent(lambda: R.carried_concerns(b"", sha(data)))
    check_eq("K5: an empty file: none, said", (got, "no concern carried" in err), ([], True))
    got, err = silent(lambda: R.carried_concerns(b"Verdict: approve\n", sha(b"Verdict: approve\n")))
    check_eq("K5: a round with no roll-call: none, said", (got, "no roll-call table" in err), ([], True))
    two = (table("approve_with_concerns", [("TC-1", "yes", "approve_with_concerns", "a")]).split(b"# Critic")[0]
           + b"## Roll-call\n\n| plan row | case | reviewed | verdict | note |\n|---|---|---|---|---|\n"
             b"| TS-1 | TC-1 | yes | approve_with_concerns | a |\n\n## Roll-call\n\n| plan row | case | reviewed | verdict | note |\n"
             b"|---|---|---|---|---|\n| TS-1 | TC-1 | yes | approve_with_concerns | b |\n")
    got, err = silent(lambda: R.carried_concerns(two, sha(two)))
    check_eq("K5: two roll-calls in one round: none, said", (got, "two roll-calls" in err), ([], True))
    plain = table("approve", [("TC-1", "yes", "approve", "all dimensions pass"), ("TC-2", "yes", "approve", "ok")])
    check_eq("K5: zero concerns: nothing carried, nothing said", silent(lambda: R.carried_concerns(plain, sha(plain))), ([], ""))
    quiet = table("approve_with_concerns", [("TC-1", "yes", "approve_with_concerns", "")])
    check_eq("K5: a concern with no note says so, it is not dropped",
             [c["problem"] for c in R.carried_concerns(quiet, sha(quiet))], [R.NO_NOTE])
    notreviewed = table("partial", [("TC-1", "no", "approve_with_concerns", "unseen"), ("TC-2", "yes", "approve_with_concerns", "seen")])
    check_eq("K5: a row that is not reviewed carries nothing (its concern is nobody's)",
             [c["case"] for c in R.carried_concerns(notreviewed, sha(notreviewed))], ["TC-2"])
    several = table("approve_with_concerns", [("TC-1, TC-2", "yes", "approve_with_concerns", "both")])
    check_eq("K5: a row naming two cases carries the concern for each, numbered on",
             [(c["id"], c["case"]) for c in R.carried_concerns(several, sha(several), start=5)], [("CC-5", "TC-1"), ("CC-6", "TC-2")])
    older = table("reject", [("TC-9", "yes", "approve_with_concerns", "round 1 only")])
    stacked = table("approve", [("TC-1", "yes", "approve", "fine")]) + older
    check_eq("K5: only the round the receipt measured is read - the older round's concern is not carried",
             R.carried_concerns(stacked, sha(stacked), receipts=[sha(older)]), [])
    # remarks_of: the state edges
    root = temp_dir("qa-hf4-11-edge-")
    try:
        state = story(root, FIXED)
        BASE.put(root, FINDINGS_REL, FIXED + b"\nedited after the review\n")
        got, err = silent(lambda: SP.remarks_of(root, state))
        check_eq("K5: the findings file was edited after its receipt: remarks_of carries no concern, and says so", (got, "no concern carried" in err),
                 ([], True))
        BASE.put(root, FINDINGS_REL, plain + FIXED)
        two_rounds = {"dispatches": {"S4-qa-case-critic-3": critic_dispatch("S4-qa-case-critic-3", FIXED),
                                     "S4-qa-case-critic-5": critic_dispatch("S4-qa-case-critic-5", plain + FIXED)}}
        check_eq("K5: the later round (TC-1, TC-2: approvals) lists none of the cases of the earlier one: their concerns stay (HF4-11 fork 2)",
                 [(r["id"], r["case"], r["review"]) for r in SP.remarks_of(root, two_rounds)],
                 [(f"CC-{n}", case, "S4-qa-case-critic-3") for n, case in enumerate(CONCERN_CASES, start=1)])
        skipped = {"dispatches": {"S4-qa-case-critic-3": critic_dispatch("S4-qa-case-critic-3", FIXED, status="rejected")}}
        BASE.put(root, FINDINGS_REL, FIXED)
        check_eq("K5: a dispatch that is not accepted carries nothing", SP.remarks_of(root, skipped), [])
        check_eq("K5: no S4 dispatch at all (a run before this node): the chain alone, as before", SP.remarks_of(root, {"dispatches": {}}), [])
    finally:
        cleanup(root)


# --- K7: per case, the latest round that lists it (fork 2); K8: the driver's route for the rule (fork 1) ----------

def round_on_top(rows, number=4):
    body = "".join(f"| TS-{case[-2:]} | {case} | yes | {word} | {note} |\n" for case, word, note in rows)
    return (f"# Case critic findings - TP1-12586 - round {number} (dispatch S4-qa-case-critic-{number})\n\n"
            "Verdict: approve_with_concerns\n\n## Roll-call\n\n| plan row | case | reviewed | verdict | note |\n"
            f"|---|---|---|---|---|\n{body}\n").encode("utf-8")


def two_round_state(top_bytes, extra=None):
    whole = top_bytes + FIXED
    state = {"dispatches": {"S4-qa-case-critic-3": critic_dispatch("S4-qa-case-critic-3", FIXED),
                            "S4-qa-case-critic-4": critic_dispatch("S4-qa-case-critic-4", whole)}}
    state["dispatches"].update(extra or {})
    return whole, state


def k7_latest_round_per_case():
    root = temp_dir("qa-hf4-11-latest-")
    try:
        # SEAM on the recorded round 3: a later scoped round over TC-001 only keeps the concerns of the six cases it did not list
        whole, state = two_round_state(round_on_top([("TC-001", "approve", "fine")]))
        BASE.put(root, FINDINGS_REL, whole)
        BASE.put(root, SP.PLAN_REL, (FIX / "s5-plan.json").read_bytes())
        got = SP.remarks_of(root, state)
        check_eq("K7 seam: the recorded round's cases keep their concerns under a later round that does not list them",
                 [(r["id"], r["case"], r["review"]) for r in got],
                 [(f"CC-{n}", case, "S4-qa-case-critic-3") for n, case in enumerate(CONCERN_CASES, start=1)])
        # a later round that lists TC-014 with a concern: the later one decides, the earlier one's note for TC-014 is out
        whole, state = two_round_state(round_on_top([("TC-014", "approve_with_concerns", "new note")]))
        BASE.put(root, FINDINGS_REL, whole)
        got = SP.remarks_of(root, state)
        check_eq("K7: a case listed by both rounds takes the LATEST round's concern, once",
                 [(r["case"], r["problem"], r["review"]) for r in got if r["case"] == "TC-014"],
                 [("TC-014", "new note", "S4-qa-case-critic-4")])
        check_eq("K7: ... and the other five cases keep the earlier round's, numbered on in the order of the rounds",
                 [(r["id"], r["case"]) for r in got if r["case"] != "TC-014"],
                 [(f"CC-{n}", case) for n, case in enumerate(CONCERN_CASES[:-1], start=1)])
        check_eq("K7: the ids are CC-1..6 with no gap", [r["id"] for r in got], [f"CC-{n}" for n in range(1, 7)][:len(got)])
        # EDGE: the latest listing round has 0 concerns for the case: the earlier round's concerns for it are superseded
        whole, state = two_round_state(round_on_top([("TC-014", "approve", "ok now")]))
        BASE.put(root, FINDINGS_REL, whole)
        got = SP.remarks_of(root, state)
        check_eq("K7 edge: the latest round lists TC-014 with no concern: nothing is carried for TC-014",
                 [r["case"] for r in got], CONCERN_CASES[:-1])
        # EDGE: a row of the latest round that is not reviewed does not list the case
        unreviewed = round_on_top([("TC-014", "approve", "x")]).replace(b"| TC-014 | yes |", b"| TC-014 | no |")
        whole, state = two_round_state(unreviewed)
        BASE.put(root, FINDINGS_REL, whole)
        check_eq("K7 edge: a row `reviewed: no` lists nothing - the earlier concern of TC-014 stays",
                 [r["case"] for r in SP.remarks_of(root, state)], CONCERN_CASES)
        # EDGE: one findings file that cannot be read is skipped with a line on stderr, the other file is still carried
        other = "work/test-cases/other/critic-findings.md"
        whole, state = two_round_state(round_on_top([("TC-001", "approve", "fine")]),
                                       {"S4-qa-case-critic-9": dict(critic_dispatch("S4-qa-case-critic-9", FIXED),
                                                                    evidence_refs=[{"path": other, "sha256": sha(FIXED)}])})
        BASE.put(root, FINDINGS_REL, whole)
        got, err = silent(lambda: SP.remarks_of(root, state))
        check_eq("K7 edge: the readable file's concerns are all carried",
                 [(r["case"], r["review"]) for r in got[:-1]], [(case, "S4-qa-case-critic-3") for case in CONCERN_CASES])
        gap = got[-1]
        check_eq("K7 edge: the unreadable file is a REMARK of the chain (global, kind remark, numbered on), not a stderr line",
                 (gap["id"], gap["case"], gap["kind"]), ("CC-7", None, "remark"))
        check_in("K7 edge: ... and it names the file", "other/critic-findings.md", gap["problem"])
        check_eq("K7 edge: ... nothing on stderr about it", "other/critic-findings.md" in err, False)
    finally:
        cleanup(root)


class _Stub:
    """Just what `Driver.review_precondition` reads of the driver."""
    def __init__(self, reviews, rounds_attempted=0):
        self._reviews = reviews
        self.rounds = rounds_attempted

    def design_reviews(self, gate):
        return self._reviews

    def controller_state(self):
        return {"dispatches": {"C1": {"scope": ["TC-1", "TC-2"]}}}

    def accept_order(self):
        return {"C1": 1}

    def pinned_cases(self):
        return ["TC-1", "TC-2"]

    def budget_or_none(self, *args):
        return {"counted": 0, "cap": 3}


def k8_driver_route():
    import story_run as SR
    stub_class = type("Stub", (_Stub,), {"attempted_rounds": staticmethod(SR.Driver.attempted_rounds)})

    def route(basis, rounds=(), extra=()):
        reviews = [{"reviewer_dispatch_id": "C1", "author_dispatch_id": "D1", "verdict": "partial", "verdict_basis": basis}]
        reviews += list(extra)
        return SR.Driver.review_precondition(stub_class(reviews), "A", [], rounds=rounds)
    got = route("round_word_rule")
    check_eq("K8: basis round_word_rule goes straight to a critic round over the critic's scope, no designer",
             (got["kind"], got["scope"], got["authors"]), ("critic", ["TC-1", "TC-2"], ["C1"]))
    check("K8: ... and it asks for no designer budget", "counted" not in got)
    other = route("column")
    check_eq("K8: any other basis is unchanged - the designer reworks", (other["kind"], other["scope"]), ("designer", ["TC-1", "TC-2"]))
    check_eq("K8: ... and an absent basis is unchanged", route(None)["kind"], "designer")
    mixed = route("round_word_rule", extra=[{"reviewer_dispatch_id": "C1", "verdict": "reject", "verdict_basis": "column"}])
    check_eq("K8 edge: a refusal set with another basis among them keeps the designer route", mixed["kind"], "designer")
    one_round = [{"stop": None}]
    check_eq("K8 edge: one round spent - one is left for the critic", route("round_word_rule", rounds=one_round)["kind"], "critic")
    capped = route("round_word_rule", rounds=[{"stop": None}, {"stop": None}])
    check("K8 edge: at the series cap it goes to the person (direct), as today", capped.get("direct") is True, capped)
    check_eq("K8 edge: a stop is not a spent round", route("round_word_rule", rounds=[{"stop": "cap"}, {"stop": "cap"}])["kind"], "critic")
    # review_move: the critic's brief says the truth for the rule, and is unchanged for the designer-rework critic round
    calls = []
    mover = type("Mover", (), {"rework": lambda self, stage, role, scope, reason, **kw: calls.append((role, scope, reason, kw))})()
    with contextlib.redirect_stdout(io.StringIO()):
        SR.Driver.review_move(mover, "A", [], {"kind": "critic", "scope": ["TC-1"], "authors": ["C1"], "rule": "round_word_rule"},
                              {"moves": []})
        SR.Driver.review_move(mover, "A", [], {"kind": "critic", "scope": ["TC-1"], "authors": ["D1"]}, {"moves": []})
        SR.Driver.review_move(mover, "A", [], {"kind": "critic", "scope": ["TC-1"], "authors": ["D1"], "rule": "other"}, {"moves": []})
    rule_reason, plain_reason, other_reason = calls[0][2], calls[1][2], calls[2][2]
    check_in("K8 move: the rule's brief says the Verdict line contradicts the critic's own cells",
             "Verdict line contradicts your own cells (no failing case)", rule_reason)
    check_in("K8 move: ... and that the cases were not changed", "the cases were not changed", rule_reason)
    check("K8 move: ... and does not say a designer reworked them", "designer reworked" not in rule_reason and
          "designer reworked" not in " ".join(calls[0][3]["extra"]), rule_reason)
    check_in("K8 move: a critic round after a designer's rework is worded as before", "the case designer reworked these cases", plain_reason)
    check_in("K8 move: ... also for any other `rule` value", "the case designer reworked these cases", other_reason)
    check_eq("K8 move: the move is the same critic round (role, scope)", (calls[0][0], calls[0][1]), ("qa-case-critic", ["TC-1"]))
    check("K8 edge: an approved row is no refusal - nothing to do", SR.Driver.review_precondition(
        stub_class([{"reviewer_dispatch_id": "C1", "verdict": "accepted", "verdict_basis": "round_word_rule"}]), "A", []) is None)


# --- K9: what the automator gets (F1), one reader of a round (F2), the later-round refusal (F3), gate A sentence (L1) --

def k9_fix_round():
    # F1: the remark names the file and the round, and carries the critic's own `fix` cell; no fix cell, no fix line
    with_fix = (b"# Case critic findings - round 1 - dispatch S4-qa-case-critic-3\n\nVerdict: approve_with_concerns\n\n## Roll-call\n\n"
                b"| plan row | case | reviewed | verdict | note | fix |\n|---|---|---|---|---|---|\n"
                b"| TS-14 | TC-014 | yes | approve_with_concerns | F-1 origin project | name the origin project in the Given |\n"
                b"| TS-02 | TC-002 | yes | approve_with_concerns | F-2 flag | |\n\n")
    root = temp_dir("qa-hf4-11-fix-")
    try:
        state = story(root, with_fix)
        got = {r["case"]: r for r in SP.remarks_of(root, state)}
        check_eq("K9: the critic's own `fix` cell is the remark's fix", got["TC-014"]["fix"], "name the origin project in the Given")
        check_in("K9: `expected` names the findings file (story-relative)", FINDINGS_REL, got["TC-014"]["expected"])
        check_in("K9: ... and the round (the critic's dispatch)", "round S4-qa-case-critic-3", got["TC-014"]["expected"])
        check_eq("K9: an empty `fix` cell is an empty fix, never 'none given'", got["TC-002"]["fix"], "")
        with controller_cut():
            piece = SP.window_slice(root, cases=["TC-014", "TC-002"], state=state)
        brief = SP.render_slice(piece)
        lines = {line.split()[1]: line for line in brief.splitlines() if line.startswith("- CC-")}
        check_in("K9: the rendered line carries the path", FINDINGS_REL, lines["CC-1"])
        check_in("K9: ... and the critic's fix", "Fix: name the origin project in the Given", lines["CC-1"])
        check("K9: a remark with no fix prints no Fix: part and never says 'none given'",
              "Fix:" not in lines["CC-2"] and "none given" not in brief, lines["CC-2"])
        check_in("K9: the heading no longer says the plan review wrote all of them", "## Remarks (plan review and case critic)", brief)
        check("K9: ... the old heading is gone", "## Remarks from the plan review" not in brief)
        check("K9: the recorded round (no fix column) has no fix on any remark", all(
            r["fix"] == "" for r in SP.remarks_of(root, story(root, FIXED))))
        # F2: the rounds of a file are read once, by one public function; s5_plan crosses no private name
        rounds = R.accepted_rounds(FIXED, [(sha(FIXED), "S4-qa-case-critic-3")])
        check_eq("K9: accepted_rounds lists the cases of the round's reviewed rows and its concerns",
                 (rounds[0]["review"], sorted(rounds[0]["listed"]), [c["case"] for c in rounds[0]["concerns"]]),
                 ("S4-qa-case-critic-3", sorted(ALL_CASES), CONCERN_CASES))
        check_eq("K9: a receipt on other bytes lists nothing and carries nothing",
                 R.accepted_rounds(FIXED, [(sha(RECORDED), "x")])[0]["listed"], set())
    finally:
        cleanup(root)


def k9_later_round_and_gate_a():
    import test_scoped_review_verdict as SV
    root = temp_dir("qa-hf4-11-later-")
    try:
        c = CT.Controller(root)
        first = SV.put(root, "area", SV.round_text(1, "approve", [(case, "yes", "approve") for case in SV.ALL]))
        second = SV.prepend(root, "area", SV.round_text(2, "reject", [("TC-2", "yes", "approve"), ("TC-3", "yes", "approve")]))
        dispatches = {"author": SV.author(), "critic1": SV.critic("critic1", SV.ALL, first),
                      "critic2": SV.critic("critic2", ["TC-3"], second)}
        got = SV.verdicts(c, dispatches)
        check_eq("F3: a later accepted round that says `reject` over approving cells refuses the row it lists but did not cover (TS-2, through "
                 "_later_refusal); its own row is partial; the row it does not list stays accepted", got,
                 {"TS-1": "accepted", "TS-2": "partial", "TS-3": "partial"})
        # L1: the sentence the person reads for that basis at the gate
        state = {"source_revision": "src", "plan_revision": "plan", "dispatches": dispatches}
        links = [{"case_id": case, "version": "cv_" + case} for case in SV.ALL]
        with patch.object(c, "_row_cases", return_value=SV.MAPPING), patch.object(c, "_rollcall_reviewed", return_value=set(SV.ALL)), \
                patch("contract.story_case_links", return_value=links):
            reviews = c._build_design_reviews(state, SV.ROWS)
            problems = c._design_review_problems({"design_reviews": reviews, "input_revision": "plan"}, state, SV.ROWS,
                                                 {case: "cv_" + case for case in SV.ALL})
        mine = [message for message in problems if message.startswith("plan row TS-2")]
        check("L1: gate A says the Verdict line contradicts the cells and the cases were not changed",
              len(mine) == 1 and "the case critic's Verdict line contradicts its cells; the critic rewrites the line - the "
              "cases were not changed" in mine[0] and "cannot read an approving word" not in mine[0], problems)
        # control: the same later round with a word that agrees with its cells holds nothing
        agreeing = SV.prepend(root, "area", SV.round_text(3, "approve", [("TC-2", "yes", "approve"), ("TC-3", "yes", "approve")]))
        dispatches["critic2"] = SV.critic("critic2", ["TC-3"], agreeing)
        check_eq("F3 control: a later round whose word agrees with its cells refuses nothing",
                 set(SV.verdicts(c, dispatches).values()), {"accepted"})
    finally:
        cleanup(root)


def k9_gate_a_collect():
    root = temp_dir("qa-hf4-11-collect-")
    try:
        state = story(root, FIXED)
        BASE.put(root, "state/controller.json", "{}")
        with patch.object(CT.Controller, "state", return_value=state):
            data = GB.collect("T", root)
            text = GB.render(data)
        check_eq("K9: gate_brief.collect carries the cases of the concerns under `carried_concern_cases`",
                 data.get("carried_concern_cases"), CONCERN_CASES)
        check_in("K9: ... and the rendered gate A brief prints the line", "Concerns carried to automation: TC-002", text)
    finally:
        cleanup(root)


# --- K6: the card's start load (the role-text keys of the rule moved to design/role-rules.json) -----------------

CARD = SCRIPTS.parent / "agents" / "qa-case-critic.md"


def k6_the_card():
    # The per-file 9000-byte cap of agents/*.md is retired (selftest --limits says "old 9000 per-file cap"): the cap
    # that binds is audit A22, the WHOLE start load of the role (role_load.py, in tokens). The card is checked against that one.
    import role_load as RL
    load = RL.static_load(CARD.stem, plugin_root=CARD.parent.parent)
    check("K6: the card's role stays within the start-load threshold of audit A22 (the per-file cap is retired)",
          load["verdict"] == "within" and load["tokens"] > 0, f"{load['tokens']} tokens, threshold {load['threshold_tokens']}")


if __name__ == "__main__":
    k1_k2_the_word()
    k3_the_seam()
    k4_gate_a_line()
    k5_edges()
    k7_latest_round_per_case()
    k8_driver_route()
    k9_fix_round()
    k9_later_round_and_gate_a()
    k9_gate_a_collect()
    k6_the_card()
    finish("test_carried_concerns")
