#!/usr/bin/env python3
"""The S5 repair limit through the one seam (conductor/1, C1-5b1; t-698 §4, §6 RL1-RL7, §7, §11 A3-A6, A8, A10).

What is proved here, in-process, with the roles recorded and never run (the rig of `test_repair_route.py`):
  * RL1  a window whose review closes over the spent cap is ASKED before the critic's finish: kind `repair_limit`, key
         `s5.repair_limit`, the answers round / debt / fixed / stop with their price lines, no paid call; the round number is in
         the words ("the critic sent the tests back {n} times; the factory's limit for that is {cap} rounds"), no id, no cause token;
  * RL2  `round` records the TWO passes of the controller's own keys (author, then critic), the loop dispatches the author round
         and the critic again; the keys are read from `repair_budget.passes`, never rebuilt;
  * RL3  `debt` writes the window through THE writer (`ledger.write_review_debt`) and the critic's finish closes the window;
  * RL4  `fixed` records the critic's pass only, and no author is dispatched;
  * RL5  the three `s5.nobody_*` keys by cause (environment > reviewer_error > tooling; a spent test_defect cap wins over all);
         `review` spends no cap (a critic rework with the cause the finding named);
  * RL6  a budget nobody can count is the SAME question, without `round` / `fixed`, with ONE defect_found;
  * RL7  the recovery road: a saved critic result with no answer asks (never closes), and `completion_for` closes only by the
         answer; an older controller (no `passes`) is a refusal naming the key, never a silent seam;
  * RL8  (C1-5b2, t-698 §4.4) the S7 repair loop at the spent cap, or with no count, ASKS: kind `repair_limit`, stage S7, key
         `s7.repair_limit`, round / debt / stop with their price lines, no `fixed`, no paid call; `round` records ONE pass (the author's,
         from `repair_budget.passes`) and the next entry runs exactly one round on that test's window; `debt` writes the §3.2 entry
         (`stage: S7`, the cases, the TESTS as instance ids) beside an S5 window of the same cases and BREAKS the test's loop; an
         unreadable count is the same question without `round`;
  * the R-code `sent_back` (a verdict that sends the window back naming no blocking finding), the L5 text and the old
    sentences, the dry-run text, and the question again with a changed body (FR-7);
  * the fix round after the integration critic (t-725 -> t-729, t-732): F1 one `defect_found` on the gate road; F2 the loop's forced
    budget is asked as `unknown`; F3 an owed round survives a person raised at the stand; F4 a recovery finish owes the ordinary round
    and `stage_S5` runs it before the L5 refusal; F5 the gate in the REAL `run_role` and `resume_role`; F6 = `rl2_real_controller`, the
    passes of the driver against the REAL controller CLI and `waiver.py`; F7/F8/S1/S2 `fix_round_cheap_pins`; S3 `take_answer` reaches
    the executor; an owed round on an unreadable count is asked, never a TypeError; the older controller for a `nobody` key (a pin of
    today's behaviour); t-733: a `debt` to the question of an owed round consumes it and the window closes (no round, no L5 refusal).
"""
import contextlib
import io
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import PLUGIN_ROOT, check, check_eq, check_in, check_not_in, finish  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import human_text  # noqa: E402
import story_run  # noqa: E402

TASK = "QA-9"
CRITIC = "S5-qa-code-critic-1"
PASSES = {"qa-automator": "round pass 3 for qa-automator on S5:aaaaaaaaaaaa", "qa-code-critic": "round pass 3 for qa-code-critic on S5:bbbbbbbbbbbb"}


def budget(counted=2, cap=2, mechanical=0, mechanical_cap=1, passes=True):
    found = {"counted": counted, "by_cause": {"test_defect": counted}, "cap": cap, "mechanical": mechanical,
             "mechanical_cap": mechanical_cap, "stand_signal": None}
    if passes:
        found["passes"] = dict(PASSES)
    return found


def digest_of(verdict):
    return f"qa-code-critic S5 TC-1 · {verdict}\nTC-1 · approved · reviewed\nwork/test-code/critic-findings.md"


def write_form(task_root, dispatch, rows):
    target = task_root / "work" / "handoffs" / f"{dispatch}.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("findings:\n" + "".join(
        f"  - id: {r['id']}\n    file: {r.get('file', 'tests/test_a.py') or chr(39) * 2}\n    problem: {r.get('problem', 'the check proves too little')}\n"
        f"    cause: {r.get('cause', 'test_defect')}\n    blocking: {str(r.get('blocking', True)).lower()}\n" for r in rows),
        encoding="utf-8")


class Rig:
    """One driver with the controller, the roles and the commands recorded. `value`: the budget (a dict, or an exception to raise)."""

    def __init__(self, value=None):
        from story_run_common import driver_for, seed
        self.root, self.task_root, env = seed(TASK)
        self.driver = driver_for(self.root, env, TASK, max_boundaries=1)
        self.value, self.log = value if value is not None else budget(), {"py": [], "finish": [], "rework": [], "roles": [], "conductor": 0}
        d = self.driver
        d.boundary = "S5:TC-1"
        d.controller_state = lambda: {"dispatches": {CRITIC: {"id": CRITIC, "scope": ["TC-1"], "stage": "S5", "role": "qa-code-critic"}}}
        d.repair_budget = self.read_budget
        d.py = self.spy_py
        d.finish = lambda dispatch, digest, **kw: self.log["finish"].append((dispatch, kw.get("complete"))) or (digest, {})
        d.conductor = lambda *a, **k: self.log.__setitem__("conductor", self.log["conductor"] + 1) or {"action": "continue"}

    def read_budget(self, stage, role, scope):
        if isinstance(self.value, Exception):
            raise self.value
        return self.value() if callable(self.value) else self.value

    def spy_py(self, script, *args, **kwargs):
        self.log["py"].append((script, list(args)))
        # the production controller prints ONE JSON object line for every operation (t-2020: no readable answer is a refusal)
        return 0, "{}" if script == "controller.py" else ""

    def waivers(self):
        return [a[a.index("--block") + 1] for s, a in self.log["py"] if s == "waiver.py"]

    def defects(self):
        return [a for s, a in self.log["py"] if s == "log_append.py" and "defect_found" in a]

    def ask(self, verdict="concerns", rows=None, scope=("TC-1",)):
        """Run the gate on a critic result; the Person it raises, or None."""
        if rows is not None:
            write_form(self.task_root, CRITIC, rows)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.driver.repair_limit_gate("S5", "qa-code-critic", CRITIC, digest_of(verdict), list(scope))
        except story_run.Person as person:
            return person
        return None

    def answer(self, words, dispatch=CRITIC, stage="S5"):
        d = self.driver
        d._answer = {"text": words, "rel": None}
        d.words_file = lambda text, name: self.task_root / "state" / "words" / "a.txt"
        d.answer_file = lambda: "state/words/a.txt"
        with contextlib.redirect_stdout(io.StringIO()):
            d._answer_repair_limit(words, "q", stage, dispatch)

    def real_roles(self, digest, ids=(CRITIC,)):
        """The REAL `run_role` and `resume_role` (and the real gate in them): only what reaches outside the process is replaced -
        `story_step start`, the model call, the handoff reader, the question threshold. Each call of `start` registers the next id
        of `ids` (the last one stays), so a second call with the same id reuses the saved result, as a relaunch does."""
        d, left = self.driver, list(ids)

        def start(*args):
            ident = left.pop(0) if len(left) > 1 else left[0]
            return f"dispatched {ident} (revision 1)\n--- Agent prompt, verbatim ---\nreview the tests\n--- the moment the Agent call returns ---\n"
        d.step = start
        d.run_claude = lambda *a, **k: {"session_id": "sess-1", "result": "x", "is_error": False}
        d.system_file = lambda *a, **k: None
        d.handoff = lambda role, stage, dispatch, result: digest
        d.question_threshold = lambda *a, **k: None
        d.progress_line = lambda: None
        d.state.setdefault("sessions", {})[CRITIC] = "sess-1"

    def quietly(self, call):
        """(the Person or Refusal the call raised, else None; what it printed)."""
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                call()
        except (story_run.Person, story_run.Refusal, TypeError) as raised:        # a TypeError is a FAIL line of the pin, not a crash of the file
            return raised, out.getvalue()
        return None, out.getvalue()

    def done(self):
        harness.cleanup(self.root)


def tokens_of(person):
    return re.findall(r"`([a-z ]+)` —", person.text)


def rl1_cap_is_asked():
    rig = Rig()
    try:
        person = rig.ask(rows=[{"id": "F-1", "problem": "the check never looks at the product"}])
        check("RL1: the spent cap raises a Person before the finish", person is not None)
        check_eq("RL1: the kind is repair_limit and the stage S5", (person.kind, person.stage, person.dispatch), ("repair_limit", "S5", CRITIC))
        check_eq("RL1: the answers are round / debt / fixed / stop, in the data's order", tokens_of(person), ["round", "debt", "fixed", "stop"])
        check_in("RL1: the round number and the limit are in the words", "the critic sent the tests back 2 times; the factory's limit for that is 2 rounds",
                 person.text)
        check_in("RL1: the critic's own words are listed", "the check never looks at the product", person.text)
        check_in("RL1: the three price lines follow each answer", "delivery waits until this is done", person.text)
        check_eq("RL1: the text obeys human-questions.md", human_text.problems(person.text + human_text.TAIL, offered=list(person.priced)), [])
        for needle in (CRITIC, "F-1", "test_defect", "reviewer_error", "waiver.py", "S5-qa"):
            check_not_in(f"RL1: no `{needle}` in what the person reads", needle, person.text)
        check_eq("RL1: no paid call", rig.log["conductor"], 0)
        check_eq("RL1: the finish was not reached (the gate sits before it)", rig.log["finish"], [])
        check_eq("RL1: the facts are kept for the answer", sorted(rig.driver.state["repair_ask"]["offer"]), ["debt", "fixed", "round", "stop"])
        check("RL1 negative: an approving verdict is not asked", rig.ask(verdict="approved", rows=[]) is None)
        check("RL1 negative: a round under the cap is not asked", Rig(budget(counted=1)).ask(rows=[{"id": "F-1"}]) is None)
        same = [{"id": "F-1", "problem": "the check never looks at the product"}]
        again = rig.ask(rows=same)
        check_eq("RL1: the same question again is the same body (FR-7 is `ask()`'s block)", again.text, person.text)
        rig.value = budget(counted=3, cap=3)
        later = rig.ask(rows=same)
        check_in("RL1/FR-7: the round number is VISIBLE, so a later question has a changed body", "3 times; the factory's limit for that is 3 rounds", later.text)
    finally:
        rig.done()


def rl2_round_records_two_passes():
    rig = Rig()
    try:
        rig.ask(rows=[{"id": "F-1"}])
        rig.answer("round")
        check_eq("RL2: two passes, the controller's own keys, author first", rig.waivers(), [PASSES["qa-automator"], PASSES["qa-code-critic"]])
        for key in rig.waivers():
            check_not_in("RL2: no live block keyword in a pass key", "repair round", key)
        saved = rig.driver.state["repair_limit"]["S5|TC-1"]
        check_eq("RL2: the choice is kept for THIS critic dispatch", (saved["token"], saved["dispatch"], saved["executed"]), ("round", CRITIC, False))
        check_eq("RL2: the gate lets that review through now", rig.ask(), None)
        window = {"scope": ["TC-1"], "surface": "api", "accepted_by": {"qa-automator": 1, "qa-code-critic": 1}}
        order = []
        d = rig.driver
        d.rework = lambda stage, role, cases, reason, **kw: order.append(("rework", role, kw.get("cause"))) or ("", {})

        def critic(stage, role, **kw):
            order.append(("run_role", role))
            d.last_dispatch = "S5-qa-code-critic-2"
            return digest_of("approved"), {}
        d.run_role = critic
        with contextlib.redirect_stdout(io.StringIO()):
            owed, found = d.repair_owed([window])
            d.s5_window(window, True, [], owed)
        check_eq("RL2: the author round is dispatched first, then the critic reviews again", order,
                 [("rework", "qa-automator", "test_defect"), ("run_role", "qa-code-critic")])
        # "owed once" is pinned through `stage_S5` (t-729 F3: the mark is written there, after the stand and build checks)
    finally:
        rig.done()


def rl3_debt_closes_through_the_writer():
    import ledger
    rig = Rig()
    try:
        rig.ask(rows=[{"id": "F-1"}])
        rig.answer("debt")
        found = ledger.read_review_debts(rig.task_root)
        entry = found["windows"][0]
        check_eq("RL3: the window is in work/review-debts.json (THE writer)",
                 (entry["stage"], entry["cases"], entry["critic_dispatch"], entry["reason"], entry["choice"]["token"]),
                 ("S5", ["TC-1"], CRITIC, "cap", "debt"))
        check_eq("RL3: the rounds are the controller's count", (entry["rounds"]["counted"], entry["rounds"]["cap"]), (2, 2))
        check_eq("RL3: no pass is recorded for a debt", rig.waivers(), [])
        route, _form = rig.driver.route_of(digest_of("concerns"), budget(), CRITIC)
        answer = rig.driver.repair_answer(["TC-1"], CRITIC)
        check("RL3: the close predicate is true only with the answer", rig.driver.s5_window_closed(route, answer) and
              not rig.driver.s5_window_closed(route, {}))
        check_eq("RL3: an answer for an earlier dispatch is none (the next review is asked again)", rig.driver.repair_answer(["TC-1"], "S5-qa-code-critic-2"), {})
        rig.answer("debt")
        check_eq("RL3: a repeated answer leaves ONE entry", len(ledger.read_review_debts(rig.task_root)["windows"]), 1)
    finally:
        rig.done()


def rl4_fixed_is_the_critics_pass_only():
    rig = Rig()
    try:
        rig.ask(rows=[{"id": "F-1"}])
        rig.answer("fixed")
        check_eq("RL4: one pass, the critic's", rig.waivers(), [PASSES["qa-code-critic"]])
        d = rig.driver
        window = {"scope": ["TC-1"], "surface": "api", "accepted_by": {"qa-automator": 1, "qa-code-critic": 1}}
        seen = []
        d.rework = lambda *a, **k: seen.append(("rework", a[1])) or ("", {})

        def critic(stage, role, **kw):
            seen.append(("run_role", role))
            d.last_dispatch = "S5-qa-code-critic-2"
            return digest_of("approved"), {}
        d.run_role = critic
        with contextlib.redirect_stdout(io.StringIO()):
            owed, _w = d.repair_owed([window])
            d.s5_window(window, True, [], owed)
        check_eq("RL4: the author is not dispatched; the critic reviews again", seen, [("run_role", "qa-code-critic")])
    finally:
        rig.done()


def rl5_nobody_by_cause():
    cases = [("environment", "s5.nobody_environment", ["fixed", "debt", "stop"]),
             ("reviewer_error", "s5.nobody_review", ["review", "debt", "stop"]),
             ("tooling", "s5.nobody_tooling", ["debt", "stop"])]
    for cause, key, answers in cases:
        rig = Rig(budget(counted=0))
        try:
            person = rig.ask(rows=[{"id": "F-1", "cause": cause, "problem": "the check could not run to the end"}])
            check_eq(f"RL5: a {cause} finding asks {key}", (rig.driver.state["repair_ask"]["key"], tokens_of(person)), (key, answers))
            check_eq(f"RL5: the {cause} text obeys human-questions.md", human_text.problems(person.text + human_text.TAIL, offered=list(person.priced)), [])
            check_not_in(f"RL5: the cause token `{cause}` is not in the words", cause, person.text)
        finally:
            rig.done()
    rig = Rig(budget(counted=0))
    try:
        person = rig.ask(rows=[{"id": "F-1", "cause": "tooling"}, {"id": "F-2", "cause": "reviewer_error"}, {"id": "F-3", "cause": "environment"}])
        check_eq("RL5: environment wins over reviewer_error and tooling", rig.driver.state["repair_ask"]["key"], "s5.nobody_environment")
        check_in("RL5: every finding is listed under its own cause, in words", "a fault in the factory's own tools", person.text)
        check_in("RL5: and the critic's own doubt", "the critic's own review is in doubt", person.text)
    finally:
        rig.done()
    rig = Rig(budget(counted=2))
    try:
        rig.ask(rows=[{"id": "F-1", "cause": "test_defect"}, {"id": "F-2", "cause": "environment"}])
        check_eq("RL5: a spent test_defect cap outranks every nobody cause", rig.driver.state["repair_ask"]["key"], "s5.repair_limit")
    finally:
        rig.done()
    rig = Rig(budget(counted=0))
    try:
        rig.ask(rows=[{"id": "F-1", "cause": "reviewer_error"}])
        rig.answer("review")
        check_eq("RL5: `review` records no pass (it spends no cap)", rig.waivers(), [])
        d = rig.driver
        window = {"scope": ["TC-1"], "surface": "api", "accepted_by": {"qa-automator": 1, "qa-code-critic": 1}}
        seen = []

        def rework(stage, role, cases, reason, **kw):
            seen.append((role, kw.get("cause")))
            d.last_dispatch = "S5-qa-code-critic-2"
            return digest_of("approved"), {}
        d.rework = rework
        with contextlib.redirect_stdout(io.StringIO()):
            owed, _w = d.repair_owed([window])
            d.s5_window(window, True, [], owed)
        check_eq("RL5: the critic is dispatched with the cause the finding named, and no author", seen, [("qa-code-critic", "reviewer_error")])
    finally:
        rig.done()
    rig = Rig(budget(counted=0))
    try:
        rig.ask(rows=[{"id": "F-1", "cause": "environment"}])
        rig.answer("fixed")
        check_eq("RL5: `fixed` for the stand records no pass either", rig.waivers(), [])
    finally:
        rig.done()


def rl6_budget_unknown():
    rig = Rig(story_run.Refusal("controller prepare (exit 1):\nstate is locked"))
    try:
        rig.driver.budget_or_none("S5", "qa-automator", ["TC-1"])          # the loop's own read, before the review
        person = rig.ask(rows=[{"id": "F-1"}])
        check_eq("RL6: the same question, without round / fixed", tokens_of(person), ["debt", "stop"])
        check_in("RL6: it says the factory could not count", "could not count how many rounds", person.text)
        check_eq("RL6: exactly ONE defect_found for the unreadable budget (the loop's read and the gate's)", len(rig.defects()), 1)
        rig.answer("debt")
        import ledger
        check_eq("RL6: the debt carries the reason `unknown`", ledger.read_review_debts(rig.task_root)["windows"][0]["reason"], "unknown")
    finally:
        rig.done()


def rl7_recovery_road_asks():
    rig = Rig()
    try:
        write_form(rig.task_root, CRITIC, [{"id": "F-1"}])
        rig.driver.handoff = lambda role, stage, dispatch, result: digest_of("concerns")
        record = {"id": CRITIC, "scope": ["TC-1"]}
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rig.driver._finish_saved_result({"result": "x"}, "qa-code-critic", "S5", CRITIC, record)
            asked = None
        except story_run.Person as person:
            asked = person
        check("RL7: a saved critic result with no answer asks", asked is not None and asked.kind == "repair_limit")
        check_eq("RL7 negative pin: and the stage is NOT finished", rig.log["finish"], [])
        rig.answer("debt")
        with contextlib.redirect_stdout(io.StringIO()):
            rig.driver._finish_saved_result({"result": "x"}, "qa-code-critic", "S5", CRITIC, record)
        check_eq("RL7: with the answer the finish goes", [d for d, _c in rig.log["finish"]], [CRITIC])
        rig.driver.stage_scope = lambda stage, kind="": {"windows": [{"scope": ["TC-1"], "accepted_by": {}}]}
        closes = rig.driver.completion_for("S5", "qa-code-critic", record)
        check("RL7: completion_for is a callable bound to the dispatch", callable(closes))
        check("RL7: it closes over the spent cap once the person answered `debt`", closes(digest_of("concerns")) is True)
        rig.driver.state["repair_limit"] = {}
        check("RL7: completion_for ignoring the answer would close - here it does not", closes(digest_of("concerns")) is False)
        check("RL7: an approving review closes without an answer", closes(digest_of("approved")) is True)
    finally:
        rig.done()


def sent_back_and_edges():
    rig = Rig(budget(counted=0))
    try:
        person = rig.ask(rows=[{"id": "F-1", "blocking": False}])
        check_in("A8: a verdict that sends the window back naming no blocking finding is asked",
                 "the critic sent the tests back without naming a blocking finding", person.text)
        check_eq("A8: the same question key", rig.driver.state["repair_ask"]["key"], "s5.repair_limit")
        rig.answer("debt")
        import ledger
        check_eq("A8: and the debt says `sent_back`", ledger.read_review_debts(rig.task_root)["windows"][0]["reason"], "sent_back")
    finally:
        rig.done()
    old = Rig(budget(counted=2, passes=False))
    try:
        # `ask` returns the Person; an older controller's record is the generic question, never `repair_limit`
        generic = old.ask(rows=[{"id": "F-1"}])
        check("edge 4: an older controller (no `passes`) is NOT the seam question", generic is not None and generic.kind != "repair_limit")
        check_in("edge 4: the text says the controller does not report the rounds", "does not report them", generic.text)
        check_in("edge 4: the details name the missing key", "repair_budget.passes", generic.details)
    finally:
        old.done()
    rig = Rig()
    try:
        rig.ask(rows=[{"id": "F-1"}])
        rig.driver.s0_normalize("x")
        unread = []
        rig.driver.unread = lambda *a, **k: unread.append(k.get("doors"))
        with contextlib.redirect_stdout(io.StringIO()):
            rig.driver._answer_repair_limit("do it twice please", "q", "S5", CRITIC)
        check_eq("an unread word goes to the seam with the question's own doors", unread, [("round", "debt", "fixed", "stop")])
        check_eq("and nothing was recorded", (rig.waivers(), rig.driver.state.get("repair_limit")), ([], None))
    finally:
        rig.done()


def fix_round_cheap_pins():
    """t-729 (the critic's must-fix 7, 8 and should S1, S2): the finding lines, the dead branch and the unread field, the counter a
    `round` names, the record line of a surplus round, and ONE window-key formatter."""
    source = (PLUGIN_ROOT / "scripts" / "story_run.py").read_text(encoding="utf-8")
    rig = Rig()
    try:
        person = rig.ask(rows=[{"id": "F-1", "problem": "the check never looks at the product"}])
        check_in("F7: a finding line is `<test> - <problem in the critic's words>`", "- tests/test_a.py — the check never looks at the product", person.text)
        empty = rig.ask(rows=[{"id": "F-1", "file": "", "problem": "no test is named here"}])
        check_in("F7: a finding whose `file` is empty prints `(no test named)`", "- (no test named) — no test is named here", empty.text)
        check_not_in("F8: the field `n` nobody reads is gone", '"n": counted', source)
        check_not_in("F8: so is the branch the gate made unreachable", 'and key == "s5.repair_limit" and passes is None', source)
        d = rig.driver
        check_eq("S2: the conductor's window key and the repair key are ONE formatter",
                 (d.window_key("S5", CRITIC), d.repair_key(["TC-1"]), d.repair_key(["TC-2", "TC-1"], "S7")), ("S5|TC-1", "S5|TC-1", "S7|TC-1,TC-2"))
        check_not_in("S2: no `S5|` literal is left in the driver", '"S5|', source)
    finally:
        rig.done()
    mech = Rig(budget(counted=0, cap=2, mechanical=1, mechanical_cap=1))
    try:
        person = mech.ask(rows=[{"id": "F-1", "cause": "mechanical"}])
        check_eq("S1 setup: the mechanical cap is the reason", mech.driver.state["repair_ask"]["code"], "mech_cap")
        check_in("S1: the opening names the counter that is spent", "asked for technical fixes to the tests 1 times; the factory's limit for that is 1 rounds", person.text)
        check_in("S1: the `round` answer names the counter a round spends (0 of 2), not the mechanical one", "this is round 1 and the factory's limit is 2", person.text)
        mech.answer("round")
        notes = [a[a.index("--notes") + 1] for s, a in mech.log["py"] if s == "log_append.py" and "human_answer" in a]
        check_in("S1/answer 5: the record names the token and the budget state", "repair limit (round, round bought on a cap not spent)", notes[0])
    finally:
        mech.done()
    spent = Rig()
    try:
        spent.ask(rows=[{"id": "F-1"}])
        spent.answer("round")
        notes = [a[a.index("--notes") + 1] for s, a in spent.log["py"] if s == "log_append.py" and "human_answer" in a]
        check_not_in("answer 5 negative: a round bought on a spent cap carries no such line", "not spent", notes[0])
    finally:
        spent.done()


def window():
    return {"scope": ["TC-1"], "surface": "api", "accepted_by": {"qa-automator": 1, "qa-code-critic": 1}}


def owed_entry(token="round", dispatch=CRITIC, **extra):
    return dict({"dispatch": dispatch, "token": token, "cases": ["TC-1"], "key": "s5.repair_limit", "at": "t", "words_file": "", "cause": "",
                 "reason": "", "executed": False}, **extra)


def stub_s5_roles(driver, order, critic_id="S5-qa-code-critic-2"):
    """`rework` and `run_role` recorded in `order`; the critic approves (the window closes after the round)."""
    driver.rework = lambda stage, role, cases, reason, **kw: order.append(("rework", role, kw.get("cause"))) or ("", {})

    def critic(stage, role, **kw):
        order.append(("run_role", role))
        driver.last_dispatch = critic_id
        return digest_of("approved"), {}
    driver.run_role = critic


def f1_one_defect_on_the_gate_road():
    """t-729 F1 (the critic's must-fix 1): a tooling finding of a review that closes over the seam is filed and told ONCE, on the road
    the loop never reaches (the gate), however many times the question is asked and whichever road finishes the dispatch."""
    rig = Rig(budget(counted=0))
    try:
        write_form(rig.task_root, CRITIC, [{"id": "F-1", "cause": "tooling", "problem": "the runner lost the log"}])
        gate = lambda: rig.driver.repair_limit_gate("S5", "qa-code-critic", CRITIC, digest_of("concerns"), ["TC-1"])
        first, said = rig.quietly(gate)
        second, again = rig.quietly(gate)
        check("F1: the gate asks (nobody's round, tooling)", first is not None and rig.driver.state["repair_ask"]["key"] == "s5.nobody_tooling")
        check_eq("F1: the factory's defect for the tooling finding is filed on the gate road, ONCE for two asks", len(rig.defects()), 1)
        check_in("F1: and names the finding", "tooling finding F-1", " ".join(rig.defects()[0]))
        check_in("F1: the 'nobody's round' line is told", "is nobody's round", said)
        check_not_in("F1: and not told a second time", "is nobody's round", again)
        rig.answer("debt")
        rig.driver.handoff = lambda role, stage, dispatch, result: digest_of("concerns")
        rig.quietly(lambda: rig.driver._finish_saved_result({"result": "x"}, "qa-code-critic", "S5", CRITIC, {"id": CRITIC, "scope": ["TC-1"]}))
        check_eq("F1: ask twice, answer, finish by the recovery road: still ONE defect_found", len(rig.defects()), 1)
        route, form = rig.driver.route_of(digest_of("concerns"), budget(counted=0), CRITIC)
        rig.quietly(lambda: rig.driver.s5_note_findings(route, form, CRITIC))
        check_eq("F1: the loop's own call after the review is a no-op (the mark is the driver's state)", len(rig.defects()), 1)
        kept = story_run._read_json(rig.driver.state_dir / "driver-state.json")
        check_eq("F1: the mark is on disk, so a new process files nothing either", kept.get("noted"), [f"{CRITIC}|F-1|tooling"])
    finally:
        rig.done()


def f2_forced_budget_is_asked_not_closed():
    """t-729 F2 (must-fix 2, L3): the controller did not count the round just run. The loop's forced budget (`counted=None`) is the one
    the gate of THAT review judges - a non-last window is asked as `unknown`, never closed in silence - and `debt` is recorded `unknown`."""
    import ledger
    second = "S5-qa-code-critic-2"
    rig = Rig(budget(counted=1, cap=2))           # one of two before the round and still one of two after it: the round was not counted
    try:
        rig.real_roles(digest_of("concerns"), ids=(CRITIC, second))
        for ident in (CRITIC, second):
            write_form(rig.task_root, ident, [{"id": "F-1"}])
        d, rounds = rig.driver, []
        d.rework = lambda stage, role, cases, reason, **kw: rounds.append((role, kw.get("cause"))) or ("", {})
        person, said = rig.quietly(lambda: d.s5_window(window(), False, [], None))
        check("F2: the window is ASKED (a Person of kind repair_limit), not closed", person is not None and getattr(person, "kind", "") == "repair_limit")
        check_eq("F2: the reason is `unknown`: only debt / stop are offered", (d.state["repair_ask"]["code"], d.state["repair_ask"]["offer"]), ("unknown", ["debt", "stop"]))
        check_in("F2: the loop said the round was not counted", "did not count the round just run", said)
        check_eq("F2: one author round ran, and the second critic's finish was not reached", (rounds, [x for x, _c in rig.log["finish"]]),
                 ([("qa-automator", "test_defect")], [CRITIC]))
        rig.answer("debt", second)
        entry = ledger.read_review_debts(rig.task_root)["windows"][0]
        check_eq("F2: `debt` writes the review-debts entry with the reason `unknown`", (entry["reason"], entry["critic_dispatch"]), ("unknown", second))
    finally:
        rig.done()


def f3_owed_round_survives_a_person_at_the_stand():
    """t-729 F3 (must-fix 3): a bought round is marked executed AFTER the stand and build checks. A stand question raised first leaves the
    round owed; the next entry runs it once, and the entry after that finds nothing owed."""
    rig = Rig(budget(counted=2, cap=2))
    try:
        d, order, stand = rig.driver, [], {"asks": True}
        d.stage_scope = lambda stage, kind="": {"scope": ["TC-1"], "windows": [window()]}
        d.state["repair_limit"] = {"S5|TC-1": owed_entry("round")}

        def stand_check(stage):
            if stand["asks"]:
                raise story_run.Person("environment", "The stand does not answer.", "S5", "")
        d.stand_check, d.build_check = stand_check, lambda stage, cases=None: None
        stub_s5_roles(d, order)
        raised, _ = rig.quietly(d.stage_S5)
        check("F3: the stand's question comes first", isinstance(raised, story_run.Person) and raised.kind == "environment")
        check_eq("F3: nothing was dispatched and the round is STILL owed", (order, d.state["repair_limit"]["S5|TC-1"]["executed"]), ([], False))
        stand["asks"] = False
        _, _ = rig.quietly(d.stage_S5)
        check_eq("F3: the next entry runs the round once: the author, then the critic", order, [("rework", "qa-automator", "test_defect"), ("run_role", "qa-code-critic")])
        check_eq("F3: and marks it executed", d.state["repair_limit"]["S5|TC-1"]["executed"], True)
        raised, _ = rig.quietly(d.stage_S5)
        check("F3: the third entry finds nothing owed (the L5 refusal of the factory's own state), and the round is not run twice",
              isinstance(raised, story_run.Refusal) and "--operation recover" in str(raised.text) and len(order) == 2)
    finally:
        rig.done()


def f4_recovery_finish_owes_the_round():
    """t-729 F4 (must-fix 4, A4): a recovery road that finishes a critic whose route still owes the AUTHOR a round (no seam reason) records
    it as owed (token `route`); `stage_S5` runs it BEFORE the L5 refusal, and the L5 refusal stays for the factory's own state."""
    for cause, action, digest in (("test_defect", "test_defect", "concerns"), ("mechanical", "mechanical", "approved")):
        rig = Rig(budget(counted=0))
        try:
            d, order = rig.driver, []
            write_form(rig.task_root, CRITIC, [{"id": "F-1", "cause": cause}])
            d.handoff = lambda role, stage, dispatch, result: digest_of(digest)
            record = {"id": CRITIC, "scope": ["TC-1"]}
            asked, _ = rig.quietly(lambda: d._finish_saved_result({"result": "x"}, "qa-code-critic", "S5", CRITIC, record))
            check(f"F4 {cause}: a route under the cap asks nothing and the finish goes", asked is None and [x for x, _c in rig.log["finish"]] == [CRITIC])
            owed = (d.state.get("repair_limit") or {}).get("S5|TC-1") or {}       # absent = a clean FAIL line below, never a KeyError
            check_eq(f"F4 {cause}: the owed round is recorded at the finish", (owed.get("token"), owed.get("executed"), owed.get("action"), owed.get("dispatch")),
                     ("route", False, action, CRITIC))
            kept = dict(owed)
            rig.quietly(lambda: d._finish_saved_result({"result": "x"}, "qa-code-critic", "S5", CRITIC, record))
            check_eq(f"F4 {cause}: a repeated finish of the same dispatch writes nothing new", (d.state.get("repair_limit") or {}).get("S5|TC-1") or {}, kept)
            d.stage_scope = lambda stage, kind="": {"scope": ["TC-1"], "windows": [window()]}
            d.stand_check, d.build_check = lambda stage: None, lambda stage, cases=None: None
            stub_s5_roles(d, order)
            raised, _ = rig.quietly(d.stage_S5)
            want = [("rework", "qa-automator", cause)] + ([("run_role", "qa-code-critic")] if cause == "test_defect" else [])
            check_eq(f"F4 {cause}: stage_S5 runs the owed round (no L5 refusal)", (raised, order), (None, want))
            raised, _ = rig.quietly(d.stage_S5)
            check(f"F4 {cause}: the next entry has nothing owed and the L5 text stays", isinstance(raised, story_run.Refusal) and "--operation recover" in str(raised.text))
        finally:
            rig.done()
    rig = Rig(budget(counted=2))
    try:
        write_form(rig.task_root, CRITIC, [{"id": "F-1"}])
        rig.driver.handoff = lambda role, stage, dispatch, result: digest_of("concerns")
        asked, _ = rig.quietly(lambda: rig.driver._finish_saved_result({"result": "x"}, "qa-code-critic", "S5", CRITIC, {"id": CRITIC, "scope": ["TC-1"]}))
        check_eq("F4 negative: a seam reason owes no ordinary round (it is asked)", (getattr(asked, "kind", ""), rig.driver.state.get("repair_limit")), ("repair_limit", None))
    finally:
        rig.done()


def f5_the_real_roads_ask():
    """t-729 F5 (must-fix 5): the gate is pinned in the REAL `run_role` and the REAL `resume_role`, not only where a test calls it:
    no answer -> a repair_limit Person and no finish; the answer `debt` -> the finish goes (the positive control)."""
    rig = Rig()
    try:
        write_form(rig.task_root, CRITIC, [{"id": "F-1"}])
        rig.real_roles(digest_of("concerns"))
        d = rig.driver
        asked, _ = rig.quietly(lambda: d.run_role("S5", "qa-code-critic", scope=["TC-1"]))
        check_eq("F5 run_role: a spent cap asks, and the dispatch is not finished", (getattr(asked, "kind", ""), rig.log["finish"]), ("repair_limit", []))
        rig.answer("debt")
        done, _ = rig.quietly(lambda: d.run_role("S5", "qa-code-critic", scope=["TC-1"]))
        check_eq("F5 run_role, positive control: with the answer the finish goes", (done, [x for x, _c in rig.log["finish"]]), (None, [CRITIC]))
    finally:
        rig.done()
    rig = Rig()
    try:
        write_form(rig.task_root, CRITIC, [{"id": "F-1"}])
        rig.real_roles(digest_of("concerns"))
        d = rig.driver
        asked, _ = rig.quietly(lambda: d.resume_role("S5", "qa-code-critic", CRITIC, "go on"))
        check_eq("F5 resume_role: a spent cap asks, and the dispatch is not finished", (getattr(asked, "kind", ""), rig.log["finish"]), ("repair_limit", []))
        rig.answer("debt")
        done, _ = rig.quietly(lambda: d.resume_role("S5", "qa-code-critic", CRITIC, "go on"))
        check_eq("F5 resume_role, positive control: with the answer the finish goes", (done, [x for x, _c in rig.log["finish"]]), (None, [CRITIC]))
    finally:
        rig.done()


def s3_take_answer_reaches_the_executor():
    """t-729 S3 (should 3): an answer to a raised `repair_limit` question goes through `take_answer` to `_answer_repair_limit` - even
    when the question carries `offered` - and never to the seam's `take_seam_answer`; a seam question (positive control) does the reverse."""
    rig = Rig()
    try:
        d, calls = rig.driver, []
        d._answer_repair_limit = lambda words, qtext, stage, dispatch: calls.append(("executor", words, dispatch))
        d.take_seam_answer = lambda *a, **k: calls.append(("seam",)) or True
        path = rig.task_root / "state" / "answer-s3.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("debt", encoding="utf-8")
        d.state["asked"] = {"kind": "repair_limit", "stage": "S5", "dispatch": CRITIC, "offered": ["round", "debt", "fixed"]}
        with contextlib.redirect_stdout(io.StringIO()):
            d.take_answer(path)
        check_eq("S3: kind repair_limit WITH a truthy `offered` reaches the executor and not the seam", calls, [("executor", "debt", CRITIC)])
        calls.clear()
        d.state["asked"] = {"kind": "conductor", "stage": "S5", "dispatch": CRITIC, "offered": ["retry", "stop"]}
        with contextlib.redirect_stdout(io.StringIO()):
            d.take_answer(path)
        check_eq("S3 positive control: a seam question with `offered` reaches the seam and not the executor", calls, [("seam",)])
    finally:
        rig.done()


def owed_round_on_an_unreadable_count_asks():
    """The analog of F2 (t-729 report): `s5_author_round` indexes `budget['counted']`; an owed round (`round` / `route`) met with a budget
    nobody can read (None, or the loop's forced one) is asked as `unknown` and stays owed - never a TypeError, never run blind."""
    for label, token in (("round", "round"), ("route", "route")):
        rig = Rig(story_run.Refusal("controller prepare (exit 1):\nstate is locked"))
        try:
            d, order = rig.driver, []
            write_form(rig.task_root, CRITIC, [{"id": "F-1"}])
            stub_s5_roles(d, order)
            entry = d.state.setdefault("repair_limit", {})["S5|TC-1"] = owed_entry(token, executed=True, action="test_defect")      # as `stage_S5` marks it
            raised, _ = rig.quietly(lambda: d.s5_window(window(), True, [], entry))
            check_eq(f"owed {label}, no count: asked as `unknown` (debt / stop), no author dispatched, not a TypeError",
                     (getattr(raised, "kind", repr(raised)), (d.state.get("repair_ask") or {}).get("code"), (d.state.get("repair_ask") or {}).get("offer"), order),
                     ("repair_limit", "unknown", ["debt", "stop"], []))
            check_eq(f"owed {label}: and it is STILL owed (the mark is taken back)", d.state["repair_limit"]["S5|TC-1"]["executed"], False)
            rig.value = budget(counted=1)
            entry["executed"] = True
            raised, _ = rig.quietly(lambda: d.s5_window(window(), True, [], entry))
            check_eq(f"owed {label}, positive control: a readable count runs the round", (raised, order[:1]), (None, [("rework", "qa-automator", "test_defect")]))
        finally:
            rig.done()


def debt_on_an_owed_round_closes_the_window():
    """t-733 (the Lead's decision "debt on an owed round"): a `debt` to the `unknown` question of an OWED round (`round` / `route`) consumes it.
    The review-debts entry is written with the reason `unknown`, the owed step stays executed under the token `debt` (marked `owed`), and
    the next `stage_S5` entry runs no round, raises no L5 refusal and finishes the critic by the SAME close predicate as the gate's debt."""
    import ledger
    # `running`: the critic is still running (the real controller refuses a bare `--not-complete` accept of the stage's closing critic, so the
    # critic of the last window stays open and its window is in `todo`); not running: it is accepted and nothing else waits (the L5 world)
    for label, token, running in (("round", "round", False), ("route", "route", False), ("round, critic still running", "round", True),
                                  ("route, critic still running", "route", True)):
        rig = Rig(story_run.Refusal("controller prepare (exit 1):\nstate is locked"))
        try:
            d, order = rig.driver, []
            write_form(rig.task_root, CRITIC, [{"id": "F-1"}])
            held_window = dict(window(), accepted_by={"qa-automator": 1} if running else {"qa-automator": 1, "qa-code-critic": 1})
            d.stage_scope = lambda stage, kind="": {"scope": ["TC-1"], "windows": [held_window]}
            d.stand_check, d.build_check = lambda stage: None, lambda stage, cases=None: None
            stub_s5_roles(d, order)
            d.state.setdefault("repair_limit", {})["S5|TC-1"] = owed_entry(token, action="test_defect")
            raised, _ = rig.quietly(d.stage_S5)
            check_eq(f"owed {label}, no count: the entry asks `unknown` (debt / stop) and runs nothing",
                     (getattr(raised, "kind", repr(raised)), (d.state.get("repair_ask") or {}).get("code"), (d.state.get("repair_ask") or {}).get("offer"), order),
                     ("repair_limit", "unknown", ["debt", "stop"], []))
            held, _ = rig.quietly(lambda: rig.answer("stop"))
            check_eq(f"owed {label}: `stop` stays `stop` - the question is held, the round is still owed and nothing is recorded as a debt",
                     (isinstance(held, story_run.Person), d.state["repair_limit"]["S5|TC-1"]["token"], ledger.read_review_debts(rig.task_root).get("windows")),
                     (True, token, []))
            rig.answer("debt")
            found = d.state["repair_limit"]["S5|TC-1"]
            check_eq(f"owed {label}: `debt` consumes the owed step - token `debt`, executed, marked with what it replaced",
                     (found.get("token"), found.get("executed"), found.get("owed"), found.get("dispatch")), ("debt", True, token, CRITIC))
            debts = ledger.read_review_debts(rig.task_root)["windows"]
            check_eq(f"owed {label}: the review-debts entry is written with the reason `unknown`, as on the gate road",
                     [(e["stage"], e["cases"], e["critic_dispatch"], e["reason"], e["choice"]["token"]) for e in debts], [("S5", ["TC-1"], CRITIC, "unknown", "debt")])
            check_eq(f"owed {label}: nothing is finished and no round is run by the answer itself", (rig.log["finish"], order), ([], []))
            twice = json.loads(json.dumps(d.state["repair_limit"]))
            err, _ = rig.quietly(lambda: rig.answer("debt"))
            check_eq(f"owed {label}, edge 1: the same `debt` twice for the owed step - the second is a no-op (no refusal, nothing new, no paid call)",
                     (err, d.state["repair_limit"], len(ledger.read_review_debts(rig.task_root)["windows"]), rig.log["conductor"]), (None, twice, 1, 0))
            raised, _ = rig.quietly(d.stage_S5)
            check_eq(f"owed {label}: the next entry raises nothing (no L5 refusal), runs no round and no review", (raised, order), (None, []))
            check_eq(f"owed {label}: the critic is finished ONCE, as the window's close (no fresh review is dispatched)",
                     [dispatch for dispatch, _complete in rig.log["finish"]], [CRITIC])
            complete = rig.log["finish"][0][1] if rig.log["finish"] else None
            check(f"owed {label}: by the close predicate - the callable says COMPLETE for the critic's concerns", callable(complete) and complete(digest_of("concerns")) is True)
            check_eq(f"owed {label}: the finish is marked, so the entry does not finish it twice", d.state["repair_limit"]["S5|TC-1"].get("finished"), True)
            closed = json.loads(json.dumps(d.state["repair_limit"]))
            err, _ = rig.quietly(lambda: rig.answer("debt"))
            check_eq(f"owed {label}, edge 3: a `debt` after the window closed is a no-op (no refusal, nothing new, no second finish, no paid call)",
                     (err, d.state["repair_limit"], len(ledger.read_review_debts(rig.task_root)["windows"]), len(rig.log["finish"]), rig.log["conductor"]),
                     (None, closed, 1, 1, 0))
        finally:
            rig.done()
    # positive control: a readable count still runs the round, a debt that consumed nothing opens nothing
    rig = Rig(budget(counted=1))
    try:
        d, order = rig.driver, []
        d.stage_scope = lambda stage, kind="": {"scope": ["TC-1"], "windows": [window()]}
        d.stand_check, d.build_check = lambda stage: None, lambda stage, cases=None: None
        stub_s5_roles(d, order)
        d.state["repair_limit"] = {"S5|TC-1": owed_entry("round")}
        raised, _ = rig.quietly(d.stage_S5)
        check_eq("control: `round` with a readable count runs the round (the author, then the critic) and finishes nothing as a debt",
                 (raised, order, rig.log["finish"]), (None, [("rework", "qa-automator", "test_defect"), ("run_role", "qa-code-critic")], []))
        d.state["repair_limit"] = {"S5|TC-1": owed_entry("debt", executed=True)}
        raised, _ = rig.quietly(d.stage_S5)
        check("control: a gate-road debt (it consumed no owed round) is not a pending close - the L5 refusal of the factory's own state stays",
              isinstance(raised, story_run.Refusal) and "--operation recover" in str(raised.text) and rig.log["finish"] == [])
    finally:
        rig.done()


def two_windows(first_critic=True):
    """Window A (TC-1: author and critic accepted - the critic finished `--not-complete`) and window B (TC-2: reviewed next)."""
    first = {"scope": ["TC-1"], "surface": "api", "accepted_by": {"qa-automator": 1, "qa-code-critic": 1} if first_critic else {"qa-automator": 1}}
    return [first, {"scope": ["TC-2"], "surface": "api", "accepted_by": {"qa-automator": 1}}]


def refused_owed_round_is_not_lost():
    """t-760 (t-758 finding 3): the controller REFUSES to start the owed round (`ReworkRefused`, no role ran) on a NON-last window: the mark
    `executed` that `stage_S5` set is taken back, so the person's round is still owed and the next entry runs it; the refusal is raised as
    today. A refusal of a LATER rework of the same entry (the owed round did run) keeps the mark."""
    rig = Rig(budget(counted=1, cap=5))
    try:
        d, order = rig.driver, []
        d.stage_scope = lambda stage, kind="": {"scope": ["TC-1", "TC-2"], "windows": two_windows()}
        d.stand_check, d.build_check = lambda stage: None, lambda stage, cases=None: None
        d.state["repair_limit"] = {"S5|TC-1": owed_entry("round")}

        def refuse(stage, role, cases, reason, **kw):
            raise story_run.ReworkRefused("the controller refused the rework: the window is busy")
        d.rework = refuse
        raised, _ = rig.quietly(d.stage_S5)
        check_eq("t-760/3: the refusal of the owed round is raised as before", type(raised).__name__, "ReworkRefused")
        saved = json.loads((d.state_dir / "driver-state.json").read_text(encoding="utf-8"))
        check_eq("t-760/3: and the person's round is STILL owed (the mark is taken back, in memory and on disk)",
                 (d.state["repair_limit"]["S5|TC-1"]["executed"], saved["repair_limit"]["S5|TC-1"]["executed"]), (False, False))
        stub_s5_roles(d, order)
        raised, _ = rig.quietly(d.stage_S5)
        check_eq("t-760/3: the next entry runs the round once: the author, then the critic", (raised, order),
                 (None, [("rework", "qa-automator", "test_defect"), ("run_role", "qa-code-critic")]))
        check_eq("t-760/3: and marks it executed", d.state["repair_limit"]["S5|TC-1"]["executed"], True)
    finally:
        rig.done()
    # control: the owed round DID run (the first rework went through), then a later rework is refused - the mark stays
    rig = Rig()
    try:
        d, calls, count = rig.driver, [], {"n": 1}
        rig.value = lambda: budget(counted=count["n"], cap=5)
        write_form(rig.task_root, "S5-qa-code-critic-2", [{"id": "F-1"}])
        d.stage_scope = lambda stage, kind="": {"scope": ["TC-1", "TC-2"], "windows": two_windows()}
        d.stand_check, d.build_check = lambda stage: None, lambda stage, cases=None: None
        d.state["repair_limit"] = {"S5|TC-1": owed_entry("round")}

        def rework(stage, role, cases, reason, **kw):
            calls.append(role)
            if len(calls) == 2:
                raise story_run.ReworkRefused("the controller refused the second rework")
            count["n"] += 1
            d.last_dispatch = f"S5-{role}-{len(calls)}"
            return "", {}

        def critic(stage, role, **kw):
            d.last_dispatch = "S5-qa-code-critic-2"
            return digest_of("concerns"), {}
        d.rework, d.run_role = rework, critic
        raised, _ = rig.quietly(d.stage_S5)
        check_eq("t-760/3 control: the owed round ran, a LATER rework is refused - raised, and the mark stays (the round is not run twice)",
                 (type(raised).__name__, calls, d.state["repair_limit"]["S5|TC-1"]["executed"]), ("ReworkRefused", ["qa-automator", "qa-automator"], True))
    finally:
        rig.done()


def debt_on_an_owed_round_of_a_non_last_window():
    """t-760 (t-758 finding 4): the real case of the debt road - the owed round is on window A whose critic is ACCEPTED, window B is still in
    `todo`. A `debt` to the `unknown` question writes the review-debts entry and consumes the step (executed, token `debt`, marked `owed`);
    the next entry finishes nothing (A's critic finish was made by its accept), raises no L5 refusal, and reviews window B."""
    import ledger
    for token in ("round", "route"):
        rig = Rig(story_run.Refusal("controller prepare (exit 1):\nstate is locked"))
        try:
            d, order = rig.driver, []
            write_form(rig.task_root, CRITIC, [{"id": "F-1"}])
            d.stage_scope = lambda stage, kind="": {"scope": ["TC-1", "TC-2"], "windows": two_windows()}
            d.stand_check, d.build_check = lambda stage: None, lambda stage, cases=None: None
            stub_s5_roles(d, order)
            d.state.setdefault("repair_limit", {})["S5|TC-1"] = owed_entry(token, action="test_defect")
            raised, _ = rig.quietly(d.stage_S5)
            check_eq(f"t-760/4 {token}: window A's owed round asks `unknown` (debt / stop) and runs nothing",
                     (getattr(raised, "kind", repr(raised)), (d.state.get("repair_ask") or {}).get("code"), order), ("repair_limit", "unknown", []))
            rig.answer("debt")
            found = d.state["repair_limit"]["S5|TC-1"]
            check_eq(f"t-760/4 {token}: `debt` consumes the owed step - token `debt`, executed, marked with what it replaced",
                     (found.get("token"), found.get("executed"), found.get("owed")), ("debt", True, token))
            debts = ledger.read_review_debts(rig.task_root)["windows"]
            check_eq(f"t-760/4 {token}: the review-debts entry is written with the reason `unknown`",
                     [(e["cases"], e["critic_dispatch"], e["reason"], e["choice"]["token"]) for e in debts], [(["TC-1"], CRITIC, "unknown", "debt")])
            rig.value = budget(counted=1)       # window B's count is readable
            raised, _ = rig.quietly(d.stage_S5)
            check_eq(f"t-760/4 {token}: the next entry raises nothing (no L5 refusal), finishes nothing and reviews the NEXT window",
                     (raised, rig.log["finish"], order), (None, [], [("run_role", "qa-code-critic")]))
            check_eq(f"t-760/4 {token}: the debt entry is not touched by the next window's review", d.state["repair_limit"]["S5|TC-1"], found)
        finally:
            rig.done()


def an_older_controller_for_nobody_keys():
    """Pin of today's behaviour (a remainder line of the t-732 report, no change): a controller whose `repair_budget` has no `passes`
    gets the generic refusal even for a `nobody` key, which needs no pass."""
    rig = Rig(budget(counted=0, passes=False))
    try:
        person = rig.ask(rows=[{"id": "F-1", "cause": "tooling"}])
        check("older controller, nobody key: today the generic refusal, not the seam question", person is not None and person.kind != "repair_limit")
        check_in("older controller, nobody key: it names the missing key", "repair_budget.passes", person.details)
    finally:
        rig.done()


def refusal_line(call) -> str:
    """The `error` of the controller refusal a driver call raised ('' when it went through)."""
    try:
        call()
    except story_run.Refusal as exc:
        last = str(exc.text).strip().splitlines()[-1]
        try:
            return str(json.loads(last).get("error", last))
        except ValueError:
            return last
    return ""


def rl2_real_controller():
    """RL2-real (the critic t-725, step 6 of its verdict): the passes the DRIVER writes are the ones the REAL controller accepts. A real
    seeded story (S0-S8 accepted, the author at 2 of 2 rounds, the critic at its own cap), the driver's own `repair_budget`, the real
    `waiver.py` through `_answer_repair_limit`, the real `controller.py rework` CLI. Steps 1-8 of the verdict; the lines are printed."""
    import hooklib
    import no_move
    import test_controller_rework as REWORK
    import test_words_doors as WORDS
    from controller import Controller
    from story_run_common import driver_for
    root, task = WORDS.ctrl_project("qa-repair-limit-real-")
    try:
        REWORK.story_to_s8(task)
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), STORY_RUN_CLAUDE=str(root / "none"), STUB_CONTROL=str(root / "c.json"), STUB_LOG=str(root / "l.jsonl"))
        d = driver_for(root, env, WORDS.TICKET, max_boundaries=1)
        check_eq("RL2-real setup: the driver reads the story the controller holds", d.task_root.resolve(), task.resolve())
        scope = ("TC-1",)

        def author_round(cause="test_defect", role="qa-automator", reason="x"):
            """One `rework` through the driver's own door to the real CLI: the dispatch id."""
            args = ["--stage", "S5", "--role", role, "--reason", reason, "--purpose", "repair_verify", "--cause", cause, "--cases", "TC-1"]
            return d.controller("rework", *args)["request"]["id"]

        def settle(identifier, critic=False):
            if not critic:
                REWORK.settle(Controller(task), task, {"id": identifier})
                return
            # a critic's rework ends with its findings file; the story has its manifest from S5, so the controller demands the receipt (C4-1)
            import test_controller_state as BASE
            Controller(task).apply("accept", {"id": identifier, "status": "accepted", "stage_complete": False,
                                              "evidence_refs": [BASE.evidence_ref(task, identifier + ".txt", identifier),
                                                                BASE.evidence_ref(task, identifier + "-findings.md", "# findings")],
                                              "idempotency_key": "accept-" + identifier})

        def review(name):
            return WORDS.refused_text(lambda: WORDS.critic_review(Controller(task), task, name, scope))

        def asked_for(critic, rows=({"id": "F-1"},)):
            """The gate on the critic's result `critic`: the Person it raised (the driver keeps the facts for the answer)."""
            write_form(task, critic, list(rows))
            raised = None
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    d.repair_limit_gate("S5", "qa-code-critic", critic, digest_of("concerns"), list(scope))
            except story_run.Person as person:
                raised = person
            return raised

        def answer(words, critic):
            d._answer = {"text": words, "rel": None}
            WORDS.story_pipeline(task)          # waiver.py records only into a story that has a pipeline.json
            with contextlib.redirect_stdout(io.StringIO()):
                d._answer_repair_limit(words, "q", "S5", critic)

        def counts(role="qa-automator"):
            got = d.repair_budget("S5", role, list(scope))
            return got["counted"], got["cap"]

        first = author_round()
        settle(first)
        check_eq("RL2-real setup: the critic's first re-review is dispatched", review("k2"), "")
        second = author_round()
        settle(second)
        check_eq("RL2-real setup: the critic's second re-review is dispatched (its round 2)", review("k3"), "")
        # step 1
        budget_now = d.repair_budget("S5", "qa-automator", list(scope))
        print("RL2-real 1 | prepare: " + json.dumps({k: budget_now[k] for k in ("counted", "cap", "passes")}))
        check_eq("RL2-real 1: the author is at 2 of 2 and `passes` carries both roles' keys", (counts(), sorted(budget_now["passes"])),
                 ((2, 2), ["qa-automator", "qa-code-critic"]))
        passes = budget_now["passes"]
        # step 2
        refused = refusal_line(lambda: author_round())
        print("RL2-real 2 | rework refused: " + refused[:160])
        check("RL2-real 2: the third rework is refused with the author's key as the head of the error line", refused.startswith(passes["qa-automator"]), refused[:200])
        check("RL2-real 2: and the critic's re-review is refused with the critic's key", review("k4").startswith(passes["qa-code-critic"]))
        # step 3
        person = asked_for("k3")
        check_eq("RL2-real 3 setup: the cap is asked (round / debt / fixed / stop)", tokens_of(person), ["round", "debt", "fixed", "stop"])
        check_eq("RL2-real 3 setup: the driver took the passes from the controller's own answer", d.state["repair_ask"]["passes"], passes)
        answer("round", "k3")
        third = author_round()
        print("RL2-real 3 | `round` answered with the real waiver.py -> the same rework accepted: " + third)
        check("RL2-real 3: the same rework is accepted after the answer `round`", bool(third))
        settle(third)
        # step 4
        check_eq("RL2-real 4: the critic's re-review past its cap is accepted on the critic's key", review("k4"), "")
        print("RL2-real 4 | critic re-review k4 accepted")
        # step 5
        after = d.repair_budget("S5", "qa-automator", list(scope))["passes"]
        refused = refusal_line(lambda: author_round())
        print("RL2-real 5 | next rework refused: " + refused[:160])
        check("RL2-real 5: the next author rework is refused with the NEXT key", refused.startswith(after["qa-automator"]) and after["qa-automator"] != passes["qa-automator"], refused[:200])
        # step 6
        check("RL2-real 6 setup: the critic's next review is refused (its round 4)", review("k5").startswith(after["qa-code-critic"]))
        asked_for("k4")
        answer("fixed", "k4")
        check_eq("RL2-real 6: `fixed` (the critic's pass only): the critic's next review is accepted", review("k5"), "")
        print("RL2-real 6 | `fixed`: the critic review k5 accepted past its cap")
        check("RL2-real 6: ...and the author is still refused (no pass was written for the author)", refusal_line(lambda: author_round()).startswith(after["qa-automator"]))
        # step 7
        before = (counts(), counts("qa-code-critic"))
        for cause in ("reviewer_error", "environment"):
            made = author_round(cause=cause, role="qa-code-critic", reason=f"the {cause} reason")
            settle(made, critic=True)
            print(f"RL2-real 7 | critic rework --cause {cause}: {made}; counted {before} -> {(counts(), counts('qa-code-critic'))}")
            check_eq(f"RL2-real 7: a critic rework with cause {cause} spends none of the cap", (counts(), counts("qa-code-critic")), before)
        # step 8
        person = asked_for("k9")            # a later review of the same window: no answer is recorded for it, so the cap is asked again
        render = [line for line in person.text.split("What each answer costs and does", 1)[-1].strip().splitlines() if line.strip()]
        print("RL2-real 8 | s5.repair_limit rendered lines:\n  " + "\n  ".join(render))
        resolved = no_move.delivery_text(no_move.data(), (hooklib.load_ref_json(no_move.VERDICTS_FILE) or {}).get("words") or {}, "no")
        print("RL2-real 8 | no_move.delivery_text(..., 'no') = " + repr(resolved))
        check("RL2-real 8: `no` resolves as a delivery value through delivery_text", bool(resolved))
        check_in("RL2-real 8: the rendered `debt` and `stop` lines carry that resolution", resolved, person.text)
    finally:
        harness.cleanup(root)


S7_ROW = {"case": "TC-1", "instance_id": "inst_7", "test": "tests/test_a.py::test_one", "verdict": "TEST_BUG"}
S7_BAD = "qa-automator S5 TC-1 · ok\nTC-1 · still_red · not fixed\nwork/x.md"


S7_LIFE = "S7-qa-failure-analyst-1"


def s7_rig(value=None, rows=(S7_ROW,), counted=2, counts=True, real_tests=False):
    """A Rig for `s7_repairs`: the triage holds `rows`; the budget follows `rig.count["n"]` (cap 2) unless `value` is given; every
    `rework` is recorded in `rig.rounds` as (stage, role, cases, cause) and, when `counts`, adds one to the count (the controller counts it)."""
    rig = Rig(value if value is not None else (lambda: budget(counted=rig.count["n"], cap=2)))
    rig.count, rig.rounds = {"n": counted}, []
    (rig.task_root / "work").mkdir(parents=True, exist_ok=True)
    (rig.task_root / "work" / "triage.json").write_text(json.dumps({"triage": list(rows)}), encoding="utf-8")

    def rework(stage, role, cases, reason, **kw):
        rig.rounds.append((stage, role, list(cases), kw.get("cause")))
        rig.count["n"] += int(counts)
        return S7_BAD, {}
    rig.driver.rework = rework
    rig.driver.s7_life = lambda: S7_LIFE            # the analyst's accepted dispatch (the temp controller holds none)
    rig.driver.s7_fresh = lambda: True
    if not real_tests:         # the ledger's refs are the end-to-end pin's (RL8b) and RL8c's; here the row's own id stands for the test
        rig.driver.s7_refs = lambda row: ([str(row.get("instance_id") or row.get("test") or row.get("case"))], True)
    return rig


def s7_run(rig):
    """(what `s7_repairs` raised - a Person, a Refusal, anything - or None, what it printed)."""
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            rig.driver.s7_repairs()
    except Exception as raised:      # a crash is a FAIL line of the pin, not the end of the file
        return raised, out.getvalue()
    return None, out.getvalue()


def s7_answer(rig, words):
    ask = rig.driver.state["repair_ask"]
    rig.answer(words, dispatch=ask["dispatch"], stage="S7")


def s7_kind(person):
    return (type(person).__name__, getattr(person, "kind", None), getattr(person, "stage", None))


def rl8_s7_cap_is_asked():
    """RL8 (t-698 §4.4, §6): the S7 repair loop at the spent cap ASKS - kind `repair_limit`, key `s7.repair_limit`, round / debt / stop with
    their price lines, no `fixed`, no paid call - and `round` / `debt` have executors; with no readable count the same question without
    `round`; `debt` ends the test's loop and writes the §3.2 entry with `stage: S7` and `tests`."""
    rig = s7_rig()
    try:
        person, _ = s7_run(rig)
        check_eq("RL8: the spent cap raises a Person of kind repair_limit at S7", s7_kind(person), ("Person", "repair_limit", "S7"))
        check_eq("RL8: the answers are round / debt / stop, in the data's order - NO `fixed`, no `review`", tokens_of(person), ["round", "debt", "stop"])
        check_in("RL8: the test and the count are in words", "tests/test_a.py::test_one still fails", person.text)
        check_in("RL8: the count and the limit are in words", "repaired the tests of this case 2 times", person.text)
        check_in("RL8: and the limit is said", "the factory's limit for that is 2 rounds, and it is used up", person.text)
        check_in("RL8: the three price lines follow each answer", "delivery waits until this is done", person.text)
        check_eq("RL8: the text obeys human-questions.md", human_text.problems(person.text + human_text.TAIL, offered=list(person.priced)), [])
        for needle in ("inst_7", "S7-", "S5-qa", "test_defect", "reviewer_error", "waiver.py", "fixed", "critic reviews"):
            check_not_in(f"RL8: no `{needle}` in what the person reads", needle, person.text)
        check_eq("RL8: no paid call, no round dispatched, no pass recorded", (rig.log["conductor"], rig.rounds, rig.waivers()), (0, [], []))
        ask = rig.driver.state["repair_ask"]
        check_eq("RL8: the facts kept for the answer: S7, the key, the offer, the instance id of the test",
                 (ask["stage"], ask["key"], ask["offer"], ask["tests"], ask["code"]), ("S7", "s7.repair_limit", ["round", "debt", "stop"], ["inst_7"], "cap"))
        check_eq("RL8: an answer is not a move's word and `fixed` has no executor at S7 (no pass for it)",
                 story_run.Driver.repair_pass_keys("fixed", ask, "S7"), [])
        # the question asked again after a restart with no answer: the loop asks again, nothing closes (the RL7 precedent)
        again, _ = s7_run(rig)
        check_eq("RL8: a rerun with no answer asks again, the same body, and runs nothing", (again.text == person.text, rig.rounds), (True, []))
    finally:
        rig.done()
    # below the cap the loop runs its round and asks only at the cap: from 1 of 2 exactly one round, then the question
    rig = s7_rig(counted=1)
    try:
        person, _ = s7_run(rig)
        check_eq("RL8: from 1 of 2 one round runs, on THAT test's window, then the question", (rig.rounds, s7_kind(person)),
                 ([("S5", "qa-automator", ["TC-1"], "test_defect")], ("Person", "repair_limit", "S7")))
        check_in("RL8: the question of the next count says 2 times", "repaired the tests of this case 2 times", person.text)
    finally:
        rig.done()


def rl8_round_is_one_pass_for_that_test():
    rig = s7_rig()
    try:
        s7_run(rig)
        s7_answer(rig, "round")
        check_eq("RL8: `round` records exactly ONE pass - the author's key from the controller's own passes (no critic's)", rig.waivers(),
                 [PASSES["qa-automator"]])
        saved = list(rig.driver.state["repair_limit_s7"].values())[0]
        check_eq("RL8: the choice is kept under the S7 store, for this test and count, not yet executed",
                 (saved["token"], saved["executed"], saved["tests"], saved["cases"]), ("round", False, ["inst_7"], ["TC-1"]))
        window = {"scope": ["TC-1"], "surface": "api", "accepted_by": {"qa-automator": 1}}
        check_eq("RL8: no S5 reader sees the S7 round as owed (the S5 store is untouched)", (rig.driver.repair_owed([window]), rig.driver.state.get("repair_limit")),
                 (({}, None), None))
        person, _ = s7_run(rig)
        check_eq("RL8: the next entry runs EXACTLY the one round, on that test's window", rig.rounds, [("S5", "qa-automator", ["TC-1"], "test_defect")])
        check_eq("RL8: the round is marked executed", list(rig.driver.state["repair_limit_s7"].values())[0]["executed"], True)
        check_eq("RL8: the count grew to 3, so the loop asks AGAIN (a new count, a new question, a changed body)", s7_kind(person), ("Person", "repair_limit", "S7"))
        check_in("RL8: the second question says 3 times", "repaired the tests of this case 3 times", person.text)
        # the controller does not count the person's round: one answer is worth one round, and the same count is not asked twice
        silent = s7_rig(counts=False)
        try:
            s7_run(silent)
            s7_answer(silent, "round")
            raised, printed = s7_run(silent)
            check_eq("RL8: a round the controller does not count: ONE round, no second question, no second round", (raised, len(silent.rounds)), (None, 1))
            check_in("RL8: and the stop is printed", "the person's answer `round` for this count is used; no further repair is dispatched", printed)
        finally:
            silent.done()
    finally:
        rig.done()


def rl8_debt_breaks_and_writes_the_entry():
    import ledger
    rig = s7_rig()
    try:
        ledger.write_review_debt(rig.task_root, {"stage": "S5", "cases": ["TC-1"], "tests": [], "critic_dispatch": CRITIC, "form": "", "reason": "cap",
                                                 "rounds": {"counted": 2, "cap": 2, "by_cause": {}}, "choice": {"token": "debt", "words_file": "w", "at": "t"}})
        s7_run(rig)
        s7_answer(rig, "debt")
        found = ledger.read_review_debts(rig.task_root)["windows"]
        check_eq("RL8: `debt` writes a SECOND window - the S5 window of the same cases stays, nothing is merged", [(w["stage"], w["cases"]) for w in found],
                 [("S5", ["TC-1"]), ("S7", ["TC-1"])])
        entry = found[1]
        check_eq("RL8: the §3.2 entry: stage S7, the cases, the TESTS (instance ids), no critic, no form, the reason, the choice",
                 (entry["stage"], entry["cases"], entry["tests"], entry["critic_dispatch"], entry["form"], entry["reason"], entry["choice"]["token"]),
                 ("S7", ["TC-1"], ["inst_7"], "", "", "cap", "debt"))
        check_eq("RL8: the rounds are the controller's count", (entry["rounds"]["counted"], entry["rounds"]["cap"]), (2, 2))
        check_eq("RL8: no pass for a debt", rig.waivers(), [])
        raised, printed = s7_run(rig)
        check_eq("RL8: `debt` BREAKS: no round, no second question, and the repairs are finalized", (raised, rig.rounds, any(s == "finalize_task.py" for s, _a in rig.log["py"])),
                 (None, [], True))
        check_in("RL8: the answer used is printed", "the person's answer `debt` for this count is used", printed)
        s7_run(rig)
        check_eq("RL8: a repeated entry leaves ONE S7 entry", len(ledger.read_review_debts(rig.task_root)["windows"]), 2)
    finally:
        rig.done()
    # RL8c (FX-2, N5): a row no test of the plan is bound to (the temp project has no manifest): `tests` = `unbound:<the row's first name>`,
    # else `unbound:<case>#<its index>`; the `debt` words promise NO report line; a nameless row does not raise
    for label, row, expected in (("a test name only", {"case": "TC-1", "test": "tests/test_a.py::test_one", "verdict": "TEST_BUG"},
                                  ["unbound:tests/test_a.py::test_one"]),
                                 ("a case only", {"case": "TC-1", "verdict": "TEST_BUG"}, ["unbound:TC-1"]),
                                 ("no name at all", {"verdict": "TEST_BUG"}, ["unbound:#0"])):
        rig = s7_rig(rows=(row,), real_tests=True)
        try:
            s7_run(rig)
            ask = rig.driver.state["repair_ask"]
            check_in(f"RL8c: {label}: the debt words promise no report line", "recorded under the run's own name", rig.driver.s7_says(ask)["debt"][0])
            check_not_in(f"RL8c: {label}: and do not say the report lists it", "the report lists it", rig.driver.s7_says(ask)["debt"][0])
            s7_answer(rig, "debt")
            check_eq(f"RL8c: {label}: `tests` names the row as unbound", ledger.read_review_debts(rig.task_root)["windows"][0]["tests"], expected)
        finally:
            rig.done()


def rl8b_a_debt_on_a_contract_shape_row_reaches_the_report():
    """RL8b (FX-2 end to end, t-698 §18.4): the triage row of the contract shape names the test by its node id only (`test`), while the ledger's ref is the
    manifest entry's instance id. The driver's `debt` writes the REF (`ledger.triage_refs`), so `ledger.build` covers the failed row (`repair_limit` +
    `triage_words`) and the report's block `Runs left failing — 1` names the test. MU7 (the old ident ladder: the row's own `test`) writes a name the
    ledger never matches: the row is not covered and the block is empty."""
    import ledger
    import report_facts
    row = {"case": "TC-1", "test": "tests/test_coupon.py::test_limit", "verdict": "TEST_BUG", "evidence": "e"}
    rig = s7_rig(rows=(row,), real_tests=True)
    try:
        work = rig.task_root / "work"
        entry = {"file": "tests/test_coupon.py", "test_function": "test_limit", "case": "TC-1"}
        (work / "automation-manifest.json").write_text(json.dumps({"tests": [entry]}), encoding="utf-8")
        (work / "run-report.json").write_text(json.dumps({"current_results": [{"test_id": "tests/test_coupon.py::test_limit", "case": "TC-1",
                                                                              "status": "failed", "reason": "boom"}]}), encoding="utf-8")
        s7_run(rig)
        ask = rig.driver.state["repair_ask"]
        check_eq("RL8b: the question is BOUND to a test of the plan and its `tests` is the ledger's ref, not the row's node id",
                 (ask["bound"], ask["tests"]), (True, ["test_limit"]))
        check_in("RL8b: a bound row's `debt` words say the report lists it", "the report lists it", rig.driver.s7_says(ask)["debt"][0])
        s7_answer(rig, "debt")
        window = ledger.read_review_debts(rig.task_root)["windows"][0]
        check_eq("RL8b: the S7 entry holds the ledger's ref", (window["stage"], window["tests"]), ("S7", ["test_limit"]))
        built = ledger.build(rig.task_root)
        covered = [r for r in built["rows"] if r.get("kind") == "test" and isinstance(r.get("repair_limit"), dict)]
        check_eq("RL8b: `ledger.build` covers the failed row: `repair_limit` for S7 and the triage's words",
                 [(r["repair_limit"]["stage"], bool(r.get("triage_words"))) for r in covered], [("S7", True)])
        block = report_facts._r_review_gaps({"ledger": {"gaps": report_facts.review_gaps(built)}})
        check_in("RL8b: the report's block counts the run left failing", "### Runs left failing — 1", block)
        check_in("RL8b: ... and names it", "`test_limit` (TC-1)", block)
    finally:
        rig.done()


def rl8_unknown_count_is_the_same_question():
    import ledger
    rig = s7_rig(story_run.Refusal("controller prepare (exit 1):\nstate is locked"))
    try:
        person, _ = s7_run(rig)
        check_eq("RL8 unknown: the same question at S7, without `round`", (s7_kind(person), tokens_of(person)), (("Person", "repair_limit", "S7"), ["debt", "stop"]))
        check_in("RL8 unknown: the lead says the factory could not count", "could not count how many repair rounds", person.text)
        check_not_in("RL8 unknown: no price of a round is claimed", "one more working session", person.text)
        check_eq("RL8 unknown: no round is dispatched blind, ONE defect_found for the unreadable budget", (rig.rounds, len(rig.defects())), ([], 1))
        s7_answer(rig, "debt")
        entry = ledger.read_review_debts(rig.task_root)["windows"][0]
        check_eq("RL8 unknown: the debt carries the reason `unknown` and no count", (entry["stage"], entry["reason"], entry["rounds"]["counted"], entry["tests"]),
                 ("S7", "unknown", None, ["inst_7"]))
        check_eq("RL8 unknown: asked once - the next entry breaks on the recorded answer", (s7_run(rig)[0], rig.rounds), (None, []))
    finally:
        rig.done()
    older = s7_rig(budget(counted=2, passes=False))
    try:
        person, _ = s7_run(older)
        check("RL8 older controller: no passes in the budget -> a refusal naming the key, not a `round` the driver could not record",
              getattr(person, "kind", "") != "repair_limit" and "repair_budget.passes" in getattr(person, "details", ""), repr(person))
    finally:
        older.done()


def texts():
    source = (PLUGIN_ROOT / "scripts" / "story_run.py").read_text(encoding="utf-8")
    old_l5 = "the last critic's finish must close it (or `waiver.py --stage S5`)"
    check_not_in("edge 10: the old L5 sentence with `waiver.py --stage S5` is gone", old_l5, source)
    check_not_in("edge 10: so is the old L5 sentence's head", "every window is accepted by author and critic but the stage is still open", source)
    check_in("edge 10 positive control: a sentence that stays is found by the same search", "goes to the conductor", source)
    check_in("L5: the new text names `controller.py --operation recover`", "--operation recover", source)
    check_in("the dry-run text says what the step would do at the limit", "ONE closed question to", source)


def main():
    rl1_cap_is_asked()
    rl2_round_records_two_passes()
    rl3_debt_closes_through_the_writer()
    rl4_fixed_is_the_critics_pass_only()
    rl5_nobody_by_cause()
    rl6_budget_unknown()
    rl7_recovery_road_asks()
    rl8_s7_cap_is_asked()
    rl8_round_is_one_pass_for_that_test()
    rl8_debt_breaks_and_writes_the_entry()
    rl8b_a_debt_on_a_contract_shape_row_reaches_the_report()
    rl8_unknown_count_is_the_same_question()
    sent_back_and_edges()
    fix_round_cheap_pins()
    f1_one_defect_on_the_gate_road()
    f2_forced_budget_is_asked_not_closed()
    f3_owed_round_survives_a_person_at_the_stand()
    f4_recovery_finish_owes_the_round()
    f5_the_real_roads_ask()
    s3_take_answer_reaches_the_executor()
    owed_round_on_an_unreadable_count_asks()
    debt_on_an_owed_round_closes_the_window()
    refused_owed_round_is_not_lost()
    debt_on_an_owed_round_of_a_non_last_window()
    an_older_controller_for_nobody_keys()
    rl2_real_controller()
    texts()
    finish("story_run repair limit")


if __name__ == "__main__":
    main()
