#!/usr/bin/env python3
"""RD1-9b: the S7 repair of a test the critic had REJECTED ends in a critic review of that one test (spec t-532 block RD1-9b).

Keys (every one in-process, the roles recorded and never run - the rig is `test_story_run_s7.LimitRig`):
  C-8   the author's patch does not clear `critic_verdict` (`manifest_put.merge`): the read BEFORE the round is the rule, not a luck;
  K1    rejected + a green author -> the critic is registered (`S7 repair review: <test>`, cause `test_defect`) and an approval repairs;
  K2    a test the critic had approved: no review, `repaired` as before (one round of the critic only for a rejected test, FR-55);
  K3    the verdict is read BEFORE the round: an author that clears it still meets the critic; the mark survives a restart;
  K4    the critic's outcomes: sent back (two authors, then the limit question), unverified / halting / rejected row -> no_progress;
  K5    `ReworkRefused` at the spent cap -> the limit question (no new stop); below the cap -> raised, S7 open;
  K6    the review's id is `review_round`, the author's stays in `round`;
  K7    `"REJECTED"` / an unreadable manifest / an empty case: no review, a printed line;
  K8    a restart: an accepted review is read once; a sent-back one clears its mark; a green author round that ended outside the
        loop leads to the review for a rejected test and to `repaired` for the others;
  K9    life `""`: the mark lives in this run only and says so.
"""
import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import PLUGIN_ROOT, check_eq, check_in, check_not_in, finish  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import story_run as SR  # noqa: E402
from test_story_run_s7 import GREEN, LIFE, PASSES, ROW_1, LimitRig, write  # noqa: E402

CRITIC_OK = "qa-code-critic S5 TC-1 · ok\nTC-1 · approved\nwork/x.md"
CONCERNS = "qa-code-critic S5 TC-1 · concerns\nTC-1 · rejected\nwork/x.md"
IDENT = "inst_1"
ENTRY = {"case": "TC-1", "covers": ["TC-1"], "file": "tests/test_a.py", "instance_id": "inst_1", "status": "green"}


def manifest(rig, verdict) -> None:
    entry = dict(ENTRY, **({"critic_verdict": verdict} if verdict is not None else {}))
    write(rig.task_root, man={"tests": [entry]})


class Scene:
    """One S7 repair of `ROW_1`: the manifest holds `verdict`; the author answers `author`; the critic answers `critics` in turn, or
    raises (`refuse`: a callable of the number of the critic's call). `log` holds (role, reason, cause) per rework."""

    def __init__(self, verdict="rejected", critics=(CRITIC_OK,), author=GREEN, counted=0, refuse=None, on_author=None):
        self.rig = rig = LimitRig([ROW_1], counted=counted)
        self.d, self.log, self.ids, self.calls = rig.driver, [], {}, {"c": 0}
        manifest(rig, verdict)
        d = self.d

        def rework(stage, role, cases, reason, **kw):
            self.log.append((role, reason, kw.get("cause")))
            rid = f"S5-{role}-{len(self.log)}"
            if role == "qa-automator":
                rig.n += 1
                self.ids["author"] = rid
                if kw.get("on_request"):
                    kw["on_request"](rid)
                if on_author:
                    on_author(rig)
                return author, {}
            if refuse is not None and refuse(self.calls["c"]):
                self.calls["c"] += 1
                raise SR.ReworkRefused("the controller refused the rework: the cap is spent")
            self.ids["critic"] = rid
            if kw.get("on_request"):
                kw["on_request"](rid)
            digest = critics[min(self.calls["c"], len(critics) - 1)]
            self.calls["c"] += 1
            d.last_dispatch = rid
            return digest, {}
        d.rework = rework

    def run(self, life=LIFE):
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                self.d.s7_repair_test(dict(ROW_1), IDENT, [IDENT], True, life)
        except Exception as raised:
            return raised, out.getvalue()
        return None, out.getvalue()

    def record(self) -> dict:
        return ((self.d.state.get("s7_rows") or {}).get(LIFE) or {}).get(IDENT) or {}

    def roles(self) -> list:
        return [role for role, _why, _cause in self.log]

    def done(self) -> None:
        self.rig.done()


def c8_the_patch_keeps_the_verdict() -> None:
    import manifest_put as MP
    current = {"tests": [dict(ENTRY, critic_verdict="rejected")]}
    merged = MP.merge(current, {"tests": [{k: v for k, v in ENTRY.items() if k != "status"} | {"status": "green"}]})[0]
    check_eq("C-8: a patch that does not carry `critic_verdict` leaves the rejection on the row (the merge overlays the old row)",
             merged["tests"][0].get("critic_verdict"), "rejected")
    merged = MP.merge(current, {"tests": [dict(ENTRY, critic_verdict="approved")]})[0]
    check_eq("C-8: a patch that carries a verdict replaces it (so the read must come BEFORE the round)",
             merged["tests"][0].get("critic_verdict"), "approved")


def k1_a_rejected_test_is_repaired_by_the_critics_word() -> None:
    s = Scene()
    try:
        raised, _out = s.run()
        check_eq("K1: no raise", raised, None)
        check_eq("K1: the author then the critic, both test_defect, the review in its own words",
                 [(r, why.split(":")[0], c) for r, why, c in s.log],
                 [("qa-automator", "S7 fix", "test_defect"), ("qa-code-critic", "S7 repair review", "test_defect")])
        check_in("K1: the review names the test", ": ", s.log[1][1])
        import s7_reorder
        check_eq("t-593 F-7: the review's reason is the constant `REPAIR_REVIEW_REASON` (one carrier, AR-13)",
                 s.log[1][1], s7_reorder.REPAIR_REVIEW_REASON.format(test=s.d.s7_test_name(dict(ROW_1))))
        # the K-R5-10 row of this reason: it is no S7 repair round of the author (`S7 fix`), so its dispatch hears the red-own words as findings
        import s5_precheck
        task = harness.temp_dir("qa-s7-repair-reason-")
        try:
            (task / "state").mkdir()
            (task / "state" / "controller.json").write_text(json.dumps({"dispatches": {"S5-qa-code-critic-9": {
                "id": "S5-qa-code-critic-9", "scope": ["TC-1"], "reason": s.log[1][1]}}}), encoding="utf-8")
            check_eq("t-593 F-7 (K-R5-10): `is_s7_fix_round` is False for the repair review's reason",
                     s5_precheck.is_s7_fix_round(task, "S5-qa-code-critic-9"), False)
        finally:
            harness.cleanup(task)
        check_eq("K1: the critic approves -> repaired", s.record().get("outcome"), "repaired")
        check_eq("K6: the author's id is in `round`, the critic's in `review_round` (never the other way)",
                 (s.record().get("round"), s.record().get("review_round")), (s.ids["author"], s.ids["critic"]))
        check_eq("K3: the mark stays in the record", s.record().get("was_rejected"), True)
    finally:
        s.done()


def k2_an_approved_test_has_no_review() -> None:
    for verdict in ("approved", None, "unverified"):
        s = Scene(verdict=verdict)
        try:
            s.run()
            check_eq(f"K2: verdict {verdict!r}: the author only, repaired, no critic round", (s.roles(), s.record().get("outcome")),
                     (["qa-automator"], "repaired"))
            check_eq(f"K2: and the mark says it was not rejected ({verdict!r})", s.record().get("was_rejected"), False)
        finally:
            s.done()


def k3_the_verdict_is_read_before_the_round() -> None:
    def clear(rig):
        manifest(rig, "approved")       # the author's patch carried its own verdict: the row no longer reads rejected
    s = Scene(on_author=clear)
    try:
        s.run()
        check_eq("K3: an author that rewrites the verdict still meets the critic (the read was BEFORE the round)",
                 (s.roles(), s.record().get("outcome")), (["qa-automator", "qa-code-critic"], "repaired"))
    finally:
        s.done()
    s = Scene(verdict="approved")
    try:
        s.d.state["s7_rows"] = {LIFE: {IDENT: {"was_rejected": True}}}      # a restart: the mark of the first entry
        s.run()
        check_eq("K3: the kept mark outranks the manifest as it stands now (a restart between the author and the critic)",
                 s.roles(), ["qa-automator", "qa-code-critic"])
    finally:
        s.done()


def k4_the_critics_outcomes() -> None:
    def authors(s):
        return s.roles().count("qa-automator")
    # F4 (e): a send-back with no typed finding is never a round on an assumed cause: the round is stopped, the debt stays in the triage row
    for label, digest in (("a send-back with no typed finding", CONCERNS),
                          ("unverified", "qa-code-critic S5 TC-1 · concerns\nTC-1 · unverified\nwork/x.md"),
                          ("a halting critic", "qa-code-critic S5 TC-1 · halt\nwork/x.md"),
                          ("an approving verdict with a rejected row", "qa-code-critic S5 TC-1 · ok\nTC-1 · rejected\nwork/x.md")):
        s = Scene(critics=(digest,))
        try:
            s.run()
            check_eq(f"K4: {label} -> no_progress, one author, one critic, never repaired", (s.record().get("outcome"), authors(s)),
                     ("no_progress", 1))
        finally:
            s.done()


def k5_a_refusal_at_the_cap() -> None:
    # counted 1 of 2: the author's round spends the cap (n = 2), so the AUTHOR is at the cap when the critic is refused -> the limit question
    s = Scene(counted=1, refuse=lambda n: True)
    try:
        raised, out = s.run()
        check_eq("K5: ReworkRefused at the spent cap: the limit question is asked, not a raise of the refusal",
                 (type(raised).__name__, s.record().get("outcome")), ("Person", None))
        check_in("K5: and the printed line says why", "repair cap", out)
    finally:
        s.done()
    # counted 0 of 2: the author's round leaves one round - the refusal is not about the cap and goes up, S7 stays open
    s = Scene(counted=0, refuse=lambda n: True)
    try:
        raised, _out = s.run()
        check_eq("K5: ReworkRefused below the cap is raised, nothing marked", (type(raised).__name__, s.record().get("outcome")),
                 ("ReworkRefused", None))
    finally:
        s.done()
    # t-593 F-5: the controller counts PER ROLE. The critic is at ITS cap (2 of 2) with the author below it (counted 0): the refusal is
    # the critic's cap and goes back to the loop (the author's rounds reach the limit question), not a raise that leaves S7 open
    s = Scene(counted=0, refuse=lambda n: True)
    s.d.repair_budget = lambda stage, role, scope: {"counted": 2 if role == "qa-code-critic" else s.rig.n, "cap": 2, "by_cause": {},
                                                    "passes": dict(PASSES)}
    try:
        raised, out = s.run()
        check_eq("F-5: the critic at its own cap, the author below: the limit question, not a raise of the refusal",
                 (type(raised).__name__, s.record().get("outcome")), ("Person", None))
        check_in("F-5: and the printed line names the critic's role", "(qa-code-critic)", out)
    finally:
        s.done()


def k7_what_is_not_a_rejection() -> None:
    s = Scene(verdict="REJECTED")
    try:
        s.run()
        check_eq("K7: `REJECTED` is not the critic's word: no review", (s.roles(), s.record().get("outcome")), (["qa-automator"], "repaired"))
        check_eq("K7: s7_was_rejected is False for it", s.d.s7_was_rejected("TC-1"), False)
        check_eq("K7: and True for the real word, read stripped",
                 (manifest(s.rig, " rejected "), s.d.s7_was_rejected("TC-1"))[1], True)
    finally:
        s.done()
    s = Scene()
    try:
        (s.rig.task_root / "work" / "automation-manifest.json").write_text("{not json", encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            got = s.d.s7_was_rejected("TC-1")
        check_eq("K7: an unreadable manifest is False", got, False)
        (s.rig.task_root / "work" / "automation-manifest.json").unlink()
        with contextlib.redirect_stdout(out):
            gone = s.d.s7_was_rejected("TC-1")
            empty = s.d.s7_was_rejected("")
        check_eq("K7: an absent manifest and an empty case are False too", (gone, empty), (False, False))
        check_in("K7: and the line is printed", "S7:", out.getvalue())
    finally:
        s.done()
    s = Scene(verdict="rejected")
    try:
        check_eq("K7 control: a rejected test of the case is True", s.d.s7_was_rejected("TC-1"), True)
        check_eq("K7 control: another case is False", s.d.s7_was_rejected("TC-2"), False)
    finally:
        s.done()


def k8_a_restart() -> None:
    def accepted(*ids):
        return lambda: {"dispatches": {i: {"status": "accepted"} for i in ids}}
    # (a) the review of this life was accepted and the driver fell before it read it
    s = Scene(critics=(CRITIC_OK,))
    try:
        d = s.d
        d.state["s7_rows"] = {LIFE: {IDENT: {"was_rejected": True, "round": "A1", "review_round": "C1"}}}
        d.controller_state, d.saved_done = accepted("A1", "C1"), lambda rid: CRITIC_OK
        with contextlib.redirect_stdout(io.StringIO()):
            got = d.s7_green_outside(LIFE, IDENT, dict(ROW_1), "t", "TC-1", True)
        check_eq("K8a: an accepted review is read once and decides (repaired), no new critic", (got, s.record().get("outcome"), s.roles()),
                 (True, "repaired", []))
        d.saved_done = lambda rid: CONCERNS
        d.state["s7_rows"][LIFE][IDENT].pop("outcome")
        with contextlib.redirect_stdout(io.StringIO()):
            got = d.s7_green_outside(LIFE, IDENT, dict(ROW_1), "t", "TC-1", True)
        check_eq("K8a: a send-back with no typed finding stops the round (F4 (e)): read once, marked no_progress",
                 (got, s.record().get("outcome")), (True, "no_progress"))
    finally:
        s.done()
    # (b) the author's round ended green outside the loop
    for was_rejected, want in ((True, ["qa-code-critic"]), (False, [])):
        s = Scene(critics=(CRITIC_OK,))
        try:
            d = s.d
            d.state["s7_rows"] = {LIFE: {IDENT: {"round": "A1"}}}
            d.controller_state, d.saved_done = accepted("A1"), lambda rid: GREEN
            with contextlib.redirect_stdout(io.StringIO()):
                got = d.s7_green_outside(LIFE, IDENT, dict(ROW_1), "t", "TC-1", was_rejected)
            check_eq(f"K8b: green outside, was_rejected={was_rejected}: repaired by the critic's word / at once",
                     (got, s.record().get("outcome"), s.roles()), (True, "repaired", want))
        finally:
            s.done()
    s = Scene(critics=(CONCERNS,))
    try:
        d = s.d
        d.state["s7_rows"] = {LIFE: {IDENT: {"round": "A1"}}}
        d.controller_state, d.saved_done = accepted("A1"), lambda rid: GREEN
        with contextlib.redirect_stdout(io.StringIO()):
            got = d.s7_green_outside(LIFE, IDENT, dict(ROW_1), "t", "TC-1", True)
        check_eq("K8b: green outside and the critic sends it back with no typed finding: not repaired, the round is stopped (F4 (e))",
                 (got, s.record().get("outcome")), (True, "no_progress"))
    finally:
        s.done()
    # a review that was never accepted is a new entry: the author's green round leads to a NEW review
    s = Scene(critics=(CRITIC_OK,))
    try:
        d = s.d
        d.state["s7_rows"] = {LIFE: {IDENT: {"round": "A1", "review_round": "C0"}}}
        d.controller_state, d.saved_done = accepted("A1"), lambda rid: GREEN
        with contextlib.redirect_stdout(io.StringIO()):
            got = d.s7_green_outside(LIFE, IDENT, dict(ROW_1), "t", "TC-1", True)
        check_eq("K8c: an unaccepted review_round is not read; a new review is registered", (got, s.roles()), (True, ["qa-code-critic"]))
        check_not_in("K8c: and its new id replaces the old one", "C0", s.record().get("review_round"))
    finally:
        s.done()


def k9_no_life() -> None:
    s = Scene()
    try:
        raised, out = s.run(life="")
        check_eq("K9: life '': the review still runs in this run", (raised, s.roles()), (None, ["qa-automator", "qa-code-critic"]))
        check_in("K9: and the line says the mark lives only in this run", "no life: the repair review mark lives only in this run", out)
        check_eq("K9: nothing is written to the state", s.d.state.get("s7_rows"), None)
    finally:
        s.done()


def default_words_are_unchanged() -> None:
    """`s7_reorder_outcome` keeps its default words byte for byte; `what="repair review"` says repair."""
    s = Scene()
    try:
        d = s.d
        d.budget_or_none = lambda *a, **k: {"counted": 0, "cap": 2, "by_cause": {}}
        halt = "qa-code-critic S5 TC-1 · halt\nwork/x.md"
        for what, want in (("reorder", "S7: t - the critic of the reorder round cannot go on; the round is stopped\n"),
                           ("repair review", "S7: t - the critic of the repair round cannot go on; the round is stopped\n")):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                end = d.s7_reorder_outcome(halt, "t", "TC-1", what=what)
            check_eq(f"words: {what} halting", (end, out.getvalue()), ("no_progress", want))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            d.s7_reorder_outcome(halt, "t", "TC-1")
        check_eq("words: the default is the reorder words", out.getvalue(), "S7: t - the critic of the reorder round cannot go on; the round is stopped\n")
    finally:
        s.done()


def main() -> None:
    c8_the_patch_keeps_the_verdict()
    k1_a_rejected_test_is_repaired_by_the_critics_word()
    k2_an_approved_test_has_no_review()
    k3_the_verdict_is_read_before_the_round()
    k4_the_critics_outcomes()
    k5_a_refusal_at_the_cap()
    k7_what_is_not_a_rejection()
    k8_a_restart()
    k9_no_life()
    default_words_are_unchanged()
    finish("S7 repair review")


if __name__ == "__main__":
    main()
