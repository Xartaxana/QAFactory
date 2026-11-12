"""RN1-11 (t-1697 D1-A, LOCAL-1): a letter answer on a before/now card is applied, and the card does not offer what nobody can write.

LOCAL-1, Q9: the person chose `b` ("A regression: ... unknown; say what it was") on a story with no diff; the case's Then
under `before` was the person's own words, but the code wanted a `before` value nobody writes, so the question stayed open, the
plan row stayed `unverifiable`, the report held the question open and gate B asked it again. Keys, fixed from the spec before
the first run:
  K-A1 the no-diff card has no "a regression" / "say what it was"; the `diff` story and an absent key keep the old text
  K-A2 `Q9: b` with every case Then carrying a real `before` text settles the question and the resolver gives that text
  K-A4 the answer reaches the plan (TS-26 `automate`) and the report's open list
  K-A5 gate B's list does not hold the answered question
(K-A3 and K-A6 live in test_question_branches.py.)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir, use_project  # noqa: E402
from harness import SCRIPTS  # noqa: E402

sys.path.insert(0, str(SCRIPTS))

import contract as C  # noqa: E402
import gate_brief as GB  # noqa: E402
import planning_contract as PC  # noqa: E402
import question_register as QR  # noqa: E402

TICKET = "LOCAL-1"
AT = "2026-11-02T10:00:00+00:00"
NOW_THEN = "Adding after session expiry asks for login and the product is added after re-authentication"
REGRESSION = "A regression: the behaviour before the change is the expected one - unknown; say what it was"


def q9(before="unknown", claims=True) -> dict:
    readings = [{"reading": "Intended: the behaviour now is the expected one (the product asks for login).", "from": "claim",
                 "if_chosen": "The expected value of the Then is the behaviour now.", "claim": "now"},
                {"reading": REGRESSION, "from": "claim",
                 "if_chosen": "The expected value of the Then is the behaviour before the change.", "claim": "before"}]
    if not claims:
        for r in readings:
            r.pop("claim")
    return {"id": "Q9", "question": "What must adding a product after session expiry do?", "severity": "major",
            "owner_role": "qa-requirements-tester", "before": {"value": before, "where": "none"},
            "now": {"value": "the product asks for login", "where": "session.ts:34"}, "readings": readings}


def plan_row(rid="TS-26", **extra) -> dict:
    return dict({"id": rid, "requirement_ids": ["R-26"], "level": "api", "disposition": "unverifiable",
                 "impact": "moderate", "likelihood": "medium", "design_review_required": False, "confidence": "medium",
                 "risk_rationale": "a session seam", "risk_source_refs": ["strategy/test-strategy.md@2026-09-14"],
                 "risk_policy_revision": "factory-starter-v1", "coverage_refs": [], "unknowns": [],
                 "verification_depth": "normal", "defect_hypothesis": "seam @ expiry vs add",
                 "required_scenarios": ["an expired session"], "test_level_rationale": "HTTP contract, no UI involved"}, **extra)


def case_file(cid, thens_line) -> str:
    return (f"---\nid: {cid}\nplan_row: TS-26\nquestion_thens: {thens_line}\n---\n\n## Then\n1. Then number 1.\n")


def entry(before=NOW_THEN, now="the product asks for login again", then=1) -> dict:
    return {"question": "Q9", "then": then, "readings": {"now": now, "before": before}}


def story(prefix, *, source="current-code", question=None, cases=None, rows=None):
    """A LOCAL-1-shaped story at S3: the register, the plan row that rests on Q9, the cases and `pipeline.json`."""
    root = temp_dir(prefix)
    task = root / "qa-factory" / "artifacts" / TICKET
    (task / "work" / "test-cases" / "area").mkdir(parents=True)
    (task / "state").mkdir(parents=True)
    (root / "qa-factory" / "config.json").write_text(json.dumps(
        {"schema_version": 1, "tests_root": "tests", "app_root": ".", "case_id_form": "{ticket}_TC_{nnn}"}), encoding="utf-8")
    rows = rows if rows is not None else [plan_row(question_refs=["Q9"], if_answered={"Q9": {"b": {"disposition": "automate"}}})]
    (task / "work" / "test-plan.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")
    (task / "work" / "requirements-readiness.json").write_text(
        json.dumps({"verdict": "blocked", "open_questions": [question or q9()]}), encoding="utf-8")
    for cid, line in (cases if cases is not None else {"TC_024": json.dumps([entry()])}).items():
        (task / "work" / "test-cases" / "area" / f"{cid}.md").write_text(case_file(cid, line), encoding="utf-8", newline="\n")
    pipeline = {"ticket": TICKET, "stages": {}}
    if source is not None:
        pipeline["implementation_source"] = source
    (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
    use_project(root)
    return root, task


def answer(task, letter="b") -> dict:
    shown = {x["id"]: x for x in QR.load(task)["questions"]}["Q9"]["row_hash"]
    return QR.record(task, "Q9", "answered", f"Q9: {letter}", "gate A", "person", shown, reading=letter, at=AT)


def loaded(task) -> dict:
    return {x["id"]: x for x in QR.load(task)["questions"]}["Q9"]


def card_of(question, no_diff) -> str:
    return "\n".join(GB.question_card(question, 1, None, no_diff=no_diff))


def test_k_a1_the_no_diff_card_offers_no_regression() -> None:
    root, task = story("qa-d1a-a1-")
    try:
        question = loaded(task)
        check_eq("K-A1: current-code is a no-diff story", GB.no_diff_story(task), True)
        card = card_of(question, GB.no_diff_story(task))
        check_not_in("K-A1: the card has no `a regression`", "a regression", card.lower())
        check_not_in("K-A1: nor `say what it was`", "say what it was", card.lower())
        check_not_in("K-A1: and no `before the change:` side line", "before the change:", card)
        check_in("K-A1: it prints NO_DIFF_BEFORE_READING", GB.NO_DIFF_BEFORE_READING, card)
        check_in("K-A1: and NO_DIFF_BEFORE_CHOSEN", GB.NO_DIFF_BEFORE_CHOSEN, card)
        check("K-A1: both constants fit the card's 200-character clip", len(GB.NO_DIFF_BEFORE_READING) <= 200
              and len(GB.NO_DIFF_BEFORE_CHOSEN) <= 200)
        check_in("K-A1: letters, `(from claim)` and the answer line stay", "  - b) ", card)
        check_in("K-A1: the answer line", "`Q9: a`, `Q9: b`", card)
        check_in("K-A1: the now side line stays", "now: the product asks for login", card)
        # negative controls: the same question on a diff story and with the key absent
        old = card_of(question, False)
        check_in("K-A1 control: no flag keeps the old reading", REGRESSION[:40], old)
        check_in("K-A1 control: and the `before the change:` line", "before the change: unknown", old)
        for label, source, want in (("diff", "diff", False), ("absent key", None, False), ("none (no diff found)", "none", True)):
            r2, t2 = story("qa-d1a-a1b-", source=source)
            try:
                check_eq(f"K-A1: implementation_source {label}", GB.no_diff_story(t2), want)
            finally:
                cleanup(r2)
        (task / "pipeline.json").write_text("{not json", encoding="utf-8")
        check_eq("K-A1 (E-A1): an unreadable pipeline.json is not a no-diff story", GB.no_diff_story(task), False)
        check_eq("K-A1 (E-A1): a missing one too", GB.no_diff_story(task / "nowhere"), False)
        # the question's own register hash is not touched by the card (the letter means what the person read)
        check_eq("K-A1: the register row is as it was", loaded(task)["row_hash"], question["row_hash"])
    finally:
        cleanup(root)
    # `collect` carries the key to `_question_lines`
    root, task = story("qa-d1a-a1c-")
    try:
        data = {"no_diff": True}
        lines = GB._question_lines(data, [loaded(task)])
        check_not_in("K-A1: `_question_lines` passes `no_diff` to the card", "say what it was", "\n".join(lines).lower())
        lines = GB._question_lines({}, [loaded(task)])
        check_in("K-A1: and without it prints the old card", "say what it was", "\n".join(lines).lower())
    finally:
        cleanup(root)


def test_k_a2_a_letter_whose_case_thens_name_the_value_settles_the_question() -> None:
    root, task = story("qa-d1a-a2-")
    try:
        check_eq("K-A2 control: before the answer the question is open", QR.settled(loaded(task)), False)
        rec = answer(task, "b")
        check_eq("K-A2: the record carries the stamp with the case", rec.get("before_from_thens"), {"cases": ["TC_024"]})
        question = loaded(task)
        check_eq("K-A2: settled, and `before_value_needed` is False", (QR.settled(question), C.before_value_needed(question)), (True, False))
        got = C.resolve_then_oracle({"then": 1, "source": "unknown", "ref": "Q9"}, question, entry())
        check_eq("K-A2: the resolver gives the case's own text", (got["state"], got["source"], got["expected"], got["reading"]),
                 ("settled", "person", NOW_THEN, "b"))
        # E-A5: a case that lost its text gives `open` for that Then, never a value it does not hold
        lost = C.resolve_then_oracle({"then": 1, "source": "unknown", "ref": "Q9"}, question, None)
        check_eq("K-A2 (E-A5): no case entry -> open", (lost["state"], lost["expected"]), ("open", None))
        empty = C.resolve_then_oracle({"then": 1, "source": "unknown", "ref": "Q9"}, question, entry(before=""))
        check_eq("K-A2 (E-A5): the case's text emptied after the answer -> an empty text is the case's word, never `before`",
                 empty["expected"], "")
    finally:
        cleanup(root)
    # a second case with `unknown`, or an empty text, writes nothing: no stamp, not settled (E-A2)
    for label, second in (("unknown", entry(before="unknown")), ("empty", entry(before=""))):
        root, task = story("qa-d1a-a2b-", cases={"TC_024": json.dumps([entry()]), "TC_025": json.dumps([second])})
        try:
            rec = answer(task, "b")
            question = loaded(task)
            check_eq(f"K-A2 ({label} in a second case): no stamp, not settled",
                     ("before_from_thens" in rec, QR.settled(question), C.before_value_needed(question)), (False, False, True))
        finally:
            cleanup(root)
    # F1 (t-1752, E-A3): a second case whose question_thens cannot be read gives no stamp, and the question stays open
    root, task = story("qa-d1a-a2h-", cases={"TC_024": json.dumps([entry()]), "TC_025": "[{"})
    try:
        rec = answer(task, "b")
        check_eq("K-A2 (E-A3, F1): an unreadable second case: no stamp, not settled",
                 ("before_from_thens" in rec, QR.settled(loaded(task))), (False, False))
    finally:
        cleanup(root)
    # no entry at all: not settled
    root, task = story("qa-d1a-a2c-", cases={"TC_024": json.dumps([{"question": "Q3", "then": 1, "readings": {"now": "x", "before": "y"}}])})
    try:
        rec = answer(task, "b")
        check_eq("K-A2: no entry for Q9: no stamp, not settled", ("before_from_thens" in rec, QR.settled(loaded(task))), (False, False))
    finally:
        cleanup(root)
    # E-A3: cases that cannot be read -> no stamp, the record is still written, nothing raises
    root, task = story("qa-d1a-a2d-", cases={})
    try:
        rec = answer(task, "b")
        check_eq("K-A2 (E-A3): no cases -> the record is written with no stamp", (rec["reading"], "before_from_thens" in rec), ("b", False))
    finally:
        cleanup(root)
    # reading `a`: no stamp, settled as today
    root, task = story("qa-d1a-a2e-")
    try:
        rec = answer(task, "a")
        check_eq("K-A2: reading `a` has no stamp and is settled as before", ("before_from_thens" in rec, QR.settled(loaded(task))), (False, True))
    finally:
        cleanup(root)
    # a real `before` value: the O2 branch still answers with it, stamp or none
    root, task = story("qa-d1a-a2f-", question=q9(before="the product shows the cart as empty"))
    try:
        rec = answer(task, "b")
        question = loaded(task)
        got = C.resolve_then_oracle({"then": 1, "source": "unknown", "ref": "Q9"}, question, entry())
        check_eq("K-A2: a real before value: no stamp, O2 gives the value", ("before_from_thens" in rec, got["expected"]),
                 (False, "the product shows the cart as empty"))
    finally:
        cleanup(root)
    # E-A4: a record without the stamp (written before this change) reads as today
    stale = dict(loaded(story("qa-d1a-a2g-")[1]), status="answered", reading="b", changed_since_answer=False)
    check_eq("K-A2 (E-A4): a row with no stamp is `before_value_needed` as before", C.before_value_needed(stale), True)


def test_k_a4_k_a5_the_answer_reaches_the_plan_the_report_and_gate_b() -> None:
    import report_facts
    root, task = story("qa-d1a-a4-")
    try:
        answer(task, "b")
        res = PC.apply_recorded_answers(task, "gate A")
        rows = {r["id"]: r for r in json.loads((task / "work" / "test-plan.json").read_text(encoding="utf-8"))["rows"]}
        check_eq("K-A4: TS-26 is `automate` after the answer", rows["TS-26"].get("disposition"), "automate")
        applied = [r for r in QR.load(task)["questions"] if r["id"] == "Q9"]
        check_eq("K-A4: the answer is applied, not refused", [x for x in res["lines"] if "asked again" in x], [])
        records = [json.loads(x) for x in (task / "work" / "question-answers.jsonl").read_text(encoding="utf-8").splitlines()
                   if '"answers_applied"' in x]
        check_eq("K-A4: one applied record, no `not_applied`", [(r["id"], r.get("not_applied"), r["rows"]) for r in records],
                 [("Q9", None, ["TS-26"])])
        unknown = {}
        listed = report_facts._questions(task, unknown)
        check_eq("K-A4: the report does not list Q9 as open", [x["id"] for x in (listed or {}).get("listed", [])], [])
        check_eq("K-A4: and counts it answered", (listed or {}).get("answered"), 1)
        check_eq("K-A5: gate B's list of unanswered questions does not hold Q9",
                 [x.get("id") for x in GB.unanswered_questions(task)], [])
        check_eq("K-A5: and no gate-B item of the report names it", [i for i in report_facts._gate_b_items(
                 {"ledger": {"items": []}}) if "Q9" in json.dumps(i)], [])
        check_eq("K-A4: (sanity) the question the applier saw is Q9", [x["id"] for x in applied], ["Q9"])
    finally:
        cleanup(root)


def main() -> None:
    test_k_a1_the_no_diff_card_offers_no_regression()
    test_k_a2_a_letter_whose_case_thens_name_the_value_settles_the_question()
    test_k_a4_k_a5_the_answer_reaches_the_plan_the_report_and_gate_b()
    finish("d1 answer card")


if __name__ == "__main__":
    main()
