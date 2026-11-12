"""HF4-9 (hotfix-12586/4): a question raised at the S4 exit for a case reaches the `question_refs` of that case's plan row.

On the live run TP1-12586 TC-014's Then 1 was raised as Q7 at S4, but TS-14 (`oracle_unknown`, no `question_refs`) kept its own
card "no settled expected value", so the person had two cards for one fork. `question_register.raise_for_case` now writes the new id
into the row through `planning_contract.append_question_ref` (the code writer of the plan), unless the plan was approved at gate A.

Keys: K1 the seam (the recorded TC-014 version and the recorded TS-14 row through the real `raise_for_case`, then gate A), K2 an
approved plan is not written, K3 an unreadable plan / no plan / no row loses nothing (`raise_for_case` returns the WRITER's line in `plan_notes`, naming the question and the plan file, and
`critic_rollcall.raise_pending` / the S4 exit step prints it - FR-59; the raise rewrites `raise` to the new id so it cannot be retried), K4 idempotence and order, K5 the pins of the
F-4 measurement (who reads the row's `oracle` after gate A).
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import FIXTURES, SCRIPTS, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))

import gate_brief  # noqa: E402
import planning_contract as PC  # noqa: E402
import question_register as QR  # noqa: E402

FIX = FIXTURES / "run-12586-gate-a"
TASK = "TP1-12586"
CASE = "TC-014"


def story() -> tuple:
    """The stand's story at the S4 exit: Q1..Q6 answered, Q7 not raised yet (its record and its answer are taken out)."""
    base = temp_dir("qa-hf49-") / "qa-factory"
    root = base / "artifacts" / TASK
    shutil.copytree(FIX / "work", root / "work")
    shutil.copyfile(FIX / "pipeline.json", root / "pipeline.json")
    (root / "state").mkdir(parents=True)
    (base / "state" / "cost").mkdir(parents=True)
    (base / "config.json").write_text("{}", encoding="utf-8")
    ready = root / "work" / "requirements-readiness.json"
    data = json.loads(ready.read_text(encoding="utf-8"))
    data["open_questions"] = [q for q in data["open_questions"] if q["id"] != "Q7"]
    ready.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    answers = root / "work" / "question-answers.jsonl"
    answers.write_text("".join(line + "\n" for line in answers.read_text(encoding="utf-8").splitlines()
                               if json.loads(line)["id"] != "Q7"), encoding="utf-8")
    return base, root


def case_text() -> str:
    return (FIX / "case-TC-014-raise.md").read_text(encoding="utf-8")


def plan_path(root: Path) -> Path:
    return root / "work" / "test-plan.json"


def rows(root: Path) -> dict:
    return {r["id"]: r for r in json.loads(plan_path(root).read_text(encoding="utf-8"))["rows"]}


def approve(root: Path) -> None:
    pipeline = json.loads((root / "pipeline.json").read_text(encoding="utf-8"))
    pipeline["gates"] = {"A": {"gate": "A", "status": "approved", "decision": "approved"}}
    (root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")


def _case_row(text: str) -> str:
    return QR._case_plan_row(text)


def test_k1_the_raise_reaches_ts_14() -> None:
    base, root = story()
    try:
        before = rows(root)
        check_eq("K1 (setup): TS-14 stands as the stand had it - `oracle_unknown`, no question_refs",
                 (before["TS-14"]["oracle_unknown"], "question_refs" in before["TS-14"]), (True, False))
        done = QR.raise_for_case(root, case_text(), CASE)
        check_eq("K1: Q7 is raised for TC-014 Then 1", done["raised"], [{"case": CASE, "then": 1, "question": "Q7"}])
        after = rows(root)
        check_eq("K1: TS-14 carries question_refs [Q7]", after["TS-14"].get("question_refs"), ["Q7"])
        check_eq("K1: ...and nothing else of the row changed", {k: v for k, v in after["TS-14"].items() if k != "question_refs"}, before["TS-14"])
        check_eq("K1: ...and no other row changed", {k: v for k, v in after.items() if k != "TS-14"}, {k: v for k, v in before.items() if k != "TS-14"})
        check_eq("K1: written -> nothing to say about the plan", done["plan_notes"], [])
        questions = gate_brief.contradiction_questions(root, list(after.values()))
        check_eq("K1: gate A no longer carries a TS-14 card of its own (only the contradiction nobody settled stays)",
                 [q["id"] for q in questions], ["R-2"])
        text = gate_brief.render(gate_brief.collect(TASK, root))
        check_in("K1: the card of the raised question is the one gate A shows", "**Q7**", text)
        check_not_in("K1: ...and TS-14 is not a second card for it", "**TS-14**", text)
        # control: the same story without the write (the stand's plan) keeps the second card
        check_eq("K1 control: the plan as it stood before the write still yields the TS-14 card",
                 [q["id"] for q in gate_brief.contradiction_questions(root, list(before.values()))], ["R-2", "TS-14"])
    finally:
        cleanup(base.parent)


def test_k2_an_approved_plan_is_not_written() -> None:
    base, root = story()
    try:
        approve(root)
        bytes_before = plan_path(root).read_bytes()
        done = QR.raise_for_case(root, case_text(), CASE)
        check_eq("K2: the question is raised all the same", done["raised"], [{"case": CASE, "then": 1, "question": "Q7"}])
        check_eq("K2: the approved plan is byte for byte as the person saw it", plan_path(root).read_bytes(), bytes_before)
        written, line = PC.append_question_ref(root, "TS-14", "Q7", CASE)
        check_eq("K2: the writer itself refuses too (it is the one gate)", written, False)
        check_in("K2: ...with a line in the person's words", "Q7 was raised for TC-014; you have already approved the test plan at gate A, so the plan is unchanged",
                 line)
    finally:
        cleanup(base.parent)


def test_k3_the_plan_never_costs_a_question() -> None:
    # unreadable plan
    base, root = story()
    try:
        plan_path(root).write_text("{not json", encoding="utf-8")
        done = QR.raise_for_case(root, case_text(), CASE)
        check_eq("K3: an unreadable plan - the question is raised", done["raised"], [{"case": CASE, "then": 1, "question": "Q7"}])
        check_eq("K3: ...the plan is the same bytes", plan_path(root).read_text(encoding="utf-8"), "{not json")
        check_in("K3: ...the writer says why", "the test plan could not be read", PC.append_question_ref(root, "TS-14", "Q7", CASE)[1])
        check_eq("K3: ...and the raise output carries a line naming Q7 and the plan file (FR-59)",
                 (len(done["plan_notes"]), "Q7" in done["plan_notes"][0], "work/test-plan.json" in done["plan_notes"][0],
                  "the test plan could not be read" in done["plan_notes"][0]), (1, True, True, True))
        check_in("K3: ...the question is in the register", "Q7", [q["id"] for q in QR.load(root)["questions"]])
        check_in("K3: ...and the case text was rewritten to name it", "\"ref\": \"Q7\"", done["text"])
    finally:
        cleanup(base.parent)
    # no plan yet
    base, root = story()
    try:
        plan_path(root).unlink()
        done = QR.raise_for_case(root, case_text(), CASE)
        check_eq("K3: no plan yet - raised", len(done["raised"]), 1)
        check_in("K3: ...the writer says so", "the story has no test plan yet, so the plan is unchanged", PC.append_question_ref(root, "TS-14", "Q7", CASE)[1])
        check_eq("K3: ...and no plan file appeared", plan_path(root).exists(), False)
    finally:
        cleanup(base.parent)
    # the case names no row / a row the plan does not have
    for label, text in (("a case with no plan_row", case_text().replace("plan_row: TS-14\n", "").replace("Plan row: TS-14\n", "")),
                        ("a case whose plan_row is not in the plan", case_text().replace("TS-14", "TS-99"))):
        base, root = story()
        try:
            bytes_before = plan_path(root).read_bytes()
            done = QR.raise_for_case(root, text, CASE)
            check_eq(f"K3: {label} - the question is raised", len(done["raised"]), 1)
            check_eq(f"K3: {label} - the plan is untouched", plan_path(root).read_bytes(), bytes_before)
            check_in(f"K3: {label} - the writer says no plan row names it", "Q7 was raised for TC-014; no plan row names it, so the plan is unchanged",
                     PC.append_question_ref(root, _case_row(text), "Q7", CASE)[1])
        finally:
            cleanup(base.parent)
    # the body line `Plan row:` alone names the row (the case reader of record reads both spellings)
    base, root = story()
    try:
        done = QR.raise_for_case(root, case_text().replace("plan_row: TS-14\n", ""), CASE)
        check_eq("K3: a case with only the body line `Plan row: TS-14` reaches the row too", rows(root)["TS-14"].get("question_refs"), ["Q7"])
    finally:
        cleanup(base.parent)
    # a row whose question_refs is no list is left, with a line
    base, root = story()
    try:
        document = json.loads(plan_path(root).read_text(encoding="utf-8"))
        for row in document["rows"]:
            if row["id"] == "TS-14":
                row["question_refs"] = "Q3"
        plan_path(root).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        bytes_before = plan_path(root).read_bytes()
        done = QR.raise_for_case(root, case_text(), CASE)
        check_eq("K3: question_refs that is no list - raised, plan untouched",
                 (len(done["raised"]), plan_path(root).read_bytes() == bytes_before), (1, True))
        check_in("K3: ...the writer says why", "question_refs is not a list", PC.append_question_ref(root, "TS-14", "Q7", CASE)[1])
    finally:
        cleanup(base.parent)


def test_k4_idempotent_and_ordered() -> None:
    base, root = story()
    try:
        document = json.loads(plan_path(root).read_text(encoding="utf-8"))
        for row in document["rows"]:
            if row["id"] == "TS-14":
                row["question_refs"] = ["Q3"]
        plan_path(root).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        first = QR.raise_for_case(root, case_text(), CASE)
        check_eq("K4: the new id is added at the END of the refs", rows(root)["TS-14"]["question_refs"], ["Q3", "Q7"])
        written = plan_path(root).read_bytes()
        # the raise rewrote `raise` to Q7 in the case, so the same call on the REWRITTEN text finds nothing waiting: no retry exists
        again = QR.raise_for_case(root, first["text"], CASE)
        check_eq("K4: the rewritten case raises nothing again and writes nothing (no retry path, no duplicate)",
                 (again["raised"], plan_path(root).read_bytes()), ([], written))
        check_eq("K4: the writer called directly with a ref the row has: not written, no line", PC.append_question_ref(root, "TS-14", "Q7", CASE), (False, ""))
        check_eq("K4: ...a second id is added after the first", PC.append_question_ref(root, "TS-14", "Q8", CASE), (True, ""))
        check_eq("K4: ...in order", rows(root)["TS-14"]["question_refs"], ["Q3", "Q7", "Q8"])
        # a case with nothing to raise returns the old shape and touches nothing
        settled = QR.raise_for_case(root, case_text().replace('"source": "unknown", "ref": "raise"', '"source": "ac", "ref": "R-15"'), CASE)
        check_eq("K4: no `raise` ref - nothing to do, the old result shape", settled, {"text": None, "raised": [], "problems": []})
    finally:
        cleanup(base.parent)


def test_k5_the_pins_of_the_f4_measurement() -> None:
    """K5 (F-4): the measurement found that a plan row's `oracle` is read after gate A only to be shown (s5_plan: the S3 line of a case in the
    window brief) and that `oracle_unknown` is read only by the plan validators (design review forced). These pins keep the finding true;
    a new reader that ACTS on either field fails here and the question F-4 asked is asked again."""
    readers = {}
    for path in sorted(SCRIPTS.glob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for needle in ('.get("oracle_unknown")', '["oracle_unknown"]'):
            if needle in text:
                readers.setdefault("oracle_unknown", set()).add(path.name)
        for needle in ('plan_row.get(key)', 'row.get("oracle")', "'oracle'", '"oracle"'):
            if needle in text and path.name in ("s5_plan.py", "validate_artifacts.py"):
                readers.setdefault("oracle", set()).add(path.name)
    check_eq("K5: `oracle_unknown` of a row is read only by gate_brief (the card), planning_contract (the validators) and s5_plan "
             "(F-4: the window brief shows a settled expected value; display only, the plan is never written) and check_delivery "
             "(G2-3: a green row whose flag nobody answered is an `unconfirmed_expectation` record; a reader, never a writer)",
             readers["oracle_unknown"], {"gate_brief.py", "planning_contract.py", "s5_plan.py", "check_delivery.py"})
    check_in("K5: `oracle` of a row is read by s5_plan (shown to the automator in the window brief)", "s5_plan.py", readers["oracle"])


# --- RN1-2 item 5: a question the case designer DECLARED it replaces takes the old one's place, by MEANING -----------------------------

def _mini(prefix, old_readings, md_cell="`unverifiable` - waits"):
    """A story with plan row TS-14 resting on Q4 (branches a / b / not_needed) and the new before/now question Q7 (the code's pair)."""
    import contract as C
    root = temp_dir(prefix) / "qa-factory" / "artifacts" / TASK
    (root / "work").mkdir(parents=True)
    old = {"id": "Q4", "question": "old?", "readings": old_readings, "severity": "major", "owner_role": "po_ba"}
    new = {"id": "Q7", "question": "new?", "readings": C.claim_readings("400", "403"), "before": {"value": "400", "where": "git"},
           "now": {"value": "403", "where": "code"}, "severity": "major", "owner_role": "po_ba"}
    (root / "work" / "requirements-readiness.json").write_text(json.dumps({"open_questions": [old, new]}), encoding="utf-8")
    patch_a, patch_b = {"disposition": "automate", "level": "api"}, {"disposition": "skip"}
    row = {"id": "TS-14", "reason": "waits", "question_refs": ["Q4"],
           "if_answered": {"Q4": {"a": patch_a, "b": patch_b, "not_needed": {}}}}
    (root / "work" / "test-plan.json").write_text(json.dumps({"rows": [row]}), encoding="utf-8")
    (root / "pipeline.json").write_text("{}", encoding="utf-8")
    (root / "test-plan.md").write_text("## Plan\n\n| TS | what | R | h | i | p | o | o | disposition + reason | fit | level | t |\n"
                                       "|---|---|---|---|---|---|---|---|---|---|---|---|\n"
                                       f"| TS-14 | w | R-1 | h | d | P2 | o | o | {md_cell} | | | t |\n", encoding="utf-8")
    return root, patch_a, patch_b


def _claims(first, second):
    import contract as C
    pair = {p["claim"]: p for p in C.claim_readings("400", "403")}
    return [dict(pair[first]), dict(pair[second])]


def test_k51_the_branch_moves_by_meaning_not_by_letter() -> None:
    root, patch_a, patch_b = _mini("qa-rn12-k51-", _claims("before", "now"))      # Q4: before = a, now = b; Q7 (the code's pair): now = a
    try:
        written, line = PC.repoint_question_ref(root, "TS-14", "Q4", "Q7", CASE)
        row = rows(root)["TS-14"]
        check_eq("K-5.1: written, nothing to say", (written, line), (True, ""))
        check_eq("K-5.1: the ref took the old one's place", row["question_refs"], ["Q7"])
        check_eq("K-5.1: Q7's `a` (now) is the patch the old branch held under its `b` (now), and Q7's `b` (before) the old `a`'s",
                 (row["if_answered"]["Q7"]["a"], row["if_answered"]["Q7"]["b"]), (patch_b, patch_a))
        check_eq("K-5.1: `not_needed` is copied and the old branch is gone", ("not_needed" in row["if_answered"]["Q7"], "Q4" in row["if_answered"]), (True, False))
        check_in("B-1: the human view follows the ref when no letters change places is not the case here - it is left alone, "
                 "so the cell still reads as it did", "waits", (root / "test-plan.md").read_text(encoding="utf-8"))
    finally:
        cleanup(root.parent.parent.parent)


def test_k51b_same_letters_rename_the_human_view() -> None:
    root, patch_a, patch_b = _mini("qa-rn12-k51b-", _claims("now", "before"), md_cell="`unverifiable` - waits for Q4; a: automate, b: skip")
    try:
        written, _ =PC.repoint_question_ref(root, "TS-14", "Q4", "Q7", CASE)
        md = (root / "test-plan.md").read_text(encoding="utf-8")
        check_eq("B-1: the same meaning positions: the branch keeps its letters and the md cell says Q7 where it said Q4",
                 (written, "waits for Q7; a: automate" in md, "Q4" in md), (True, True, False))
        check_eq("B-1: ...and the JSON agrees", rows(root)["TS-14"]["if_answered"]["Q7"]["a"], patch_a)
    finally:
        cleanup(root.parent.parent.parent)


def test_k51c_letters_that_change_places_do_not_leave_the_md_naming_the_old_id() -> None:
    root, patch_a, patch_b = _mini("qa-rn12-k51c-", _claims("before", "now"), md_cell="`unverifiable` - waits for Q4; a: skip, b: automate")
    try:
        written, line = PC.repoint_question_ref(root, "TS-14", "Q4", "Q7", CASE)
        check_eq("B-1: the md cell names Q4 beside letters that would change places: the move is NOT made (the strategist's rework sets it)",
                 (written, rows(root)["TS-14"]["question_refs"]), (True, ["Q4", "Q7"]))
        check_in("B-1: ...and the line says why", "test-plan.md names Q4 next to letters that change places", line)
        check_eq("B-1: ...if_answered of Q4 is untouched", rows(root)["TS-14"]["if_answered"].keys() == {"Q4"}.__or__(set()), True)
    finally:
        cleanup(root.parent.parent.parent)


def test_k53_adversarial_readings_never_re_point() -> None:
    """m-9: `claim_reading_index` in its writing role - `claim` twice on one reading, three readings, an unknown `claim` word: no re-point,
    the new ref is appended and the line says why (the error direction is "the question does not say")."""
    base = _claims("before", "now")
    cases = {
        "`claim` twice on one reading": [dict(base[0], claim="now"), dict(base[1], claim="now")],
        "three readings": base + [{"reading": "three", "from": "comment", "if_chosen": "c3", "claim": "now"}],
        "an unknown `claim` word": [dict(base[0], claim="sideways"), dict(base[1])],
    }
    for label, readings in cases.items():
        root, _a, _b = _mini("qa-rn12-k53-", readings)
        try:
            written, line = PC.repoint_question_ref(root, "TS-14", "Q4", "Q7", CASE)
            row = rows(root)["TS-14"]
            check_eq(f"m-9 [{label}]: no re-point - the new ref is appended and Q4's branch stays", (row["question_refs"], list(row["if_answered"])),
                     (["Q4", "Q7"], ["Q4"]))
            check_in(f"m-9 [{label}]: ...and the line names why", "does not say which of its readings", line)
        finally:
            cleanup(root.parent.parent.parent)


def test_k52_an_s2_question_without_meanings_is_not_moved() -> None:
    plain = [{"reading": "one", "from": "description", "if_chosen": "c1"}, {"reading": "two", "from": "comment", "if_chosen": "c2"}]
    root, patch_a, patch_b = _mini("qa-rn12-k52-", plain)
    try:
        written, line = PC.repoint_question_ref(root, "TS-14", "Q4", "Q7", CASE)
        row = rows(root)["TS-14"]
        check_eq("K-5.2: an S2 a/b question without meanings: no re-point, the new ref is appended as today",
                 (row["question_refs"], list(row["if_answered"])), (["Q4", "Q7"], ["Q4"]))
        check_in("K-5.2: ...and the line names `replaces` and why", "Q7 raised for TC-014 replaces Q4 on TS-14, but Q4 does not say which of its readings", line)
    finally:
        cleanup(root.parent.parent.parent)


def test_k53_no_replaces_is_today() -> None:
    root, patch_a, patch_b = _mini("qa-rn12-k53-", _claims("before", "now"))
    try:
        via_raise = QR._name_in_plan_row(root, "---\nplan_row: TS-14\n---\n", CASE, ["Q7"])
        check_eq("K-5.3: no `replaces`: byte-identical behaviour to today (the ref is appended, the branch stays on Q4)",
                 (via_raise, rows(root)["TS-14"]["question_refs"], list(rows(root)["TS-14"]["if_answered"])), ([], ["Q4", "Q7"], ["Q4"]))
    finally:
        cleanup(root.parent.parent.parent)
    root, patch_a, patch_b = _mini("qa-rn12-k53b-", _claims("before", "now"))
    try:
        replaced = QR._name_in_plan_row(root, "---\nplan_row: TS-14\n---\n", CASE, ["Q7"], {"Q7": "Q4"})
        check_eq("K-5.3: with `replaces` through the register's own door the branch moves", (replaced, list(rows(root)["TS-14"]["if_answered"])), ([], ["Q7"]))
    finally:
        cleanup(root.parent.parent.parent)


def test_k54_a_reason_that_names_the_old_id_is_a_fallback() -> None:
    root, patch_a, patch_b = _mini("qa-rn12-k54-", _claims("before", "now"))
    try:
        data = json.loads(plan_path(root).read_text(encoding="utf-8"))
        data["rows"][0]["reason"] = "waits for Q4"
        plan_path(root).write_text(json.dumps(data), encoding="utf-8")
        written, line = PC.repoint_question_ref(root, "TS-14", "Q4", "Q7", CASE)
        check_in("K-5.4: the row's reason names the old id: fallback with its line", "the row's reason names Q4", line)
        check_eq("K-5.4: ...the new ref is appended and the old branch stays", (rows(root)["TS-14"]["question_refs"], list(rows(root)["TS-14"]["if_answered"])),
                 (["Q4", "Q7"], ["Q4"]))
    finally:
        cleanup(root.parent.parent.parent)


def test_k55_an_approved_plan_is_not_repointed() -> None:
    root, patch_a, patch_b = _mini("qa-rn12-k55-", _claims("before", "now"))
    try:
        approve(root)
        held = plan_path(root).read_bytes()
        written, line = PC.repoint_question_ref(root, "TS-14", "Q4", "Q7", CASE)
        check_eq("K-5.5: gate A approved: nothing written", (written, plan_path(root).read_bytes()), (False, held))
        check_in("K-5.5: ...and the line says so", "you have already approved the test plan at gate A", line)
    finally:
        cleanup(root.parent.parent.parent)


if __name__ == "__main__":
    test_k51_the_branch_moves_by_meaning_not_by_letter()
    test_k51b_same_letters_rename_the_human_view()
    test_k51c_letters_that_change_places_do_not_leave_the_md_naming_the_old_id()
    test_k52_an_s2_question_without_meanings_is_not_moved()
    test_k53_adversarial_readings_never_re_point()
    test_k53_no_replaces_is_today()
    test_k54_a_reason_that_names_the_old_id_is_a_fallback()
    test_k55_an_approved_plan_is_not_repointed()
    test_k1_the_raise_reaches_ts_14()
    test_k2_an_approved_plan_is_not_written()
    test_k3_the_plan_never_costs_a_question()
    test_k4_idempotent_and_ordered()
    test_k5_the_pins_of_the_f4_measurement()
    finish("test_raise_reaches_plan_row")
