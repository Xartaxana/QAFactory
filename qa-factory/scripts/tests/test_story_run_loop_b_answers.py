"""answers: a part of test_story_run_loop_b.py, split by tools/test_split.py (TD-11c). The shared helpers are in story_run_loop_b_common."""
import json
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402
from story_run_common import run_scenarios, eq, rules_broken, seed
from story_run_loop_b_common import QStub, Q_TASK, ROLE_OF, q_load  # noqa: E402


# --- HF2-7 part P5a: the driver's half of the person's answers (the owner's word of 24.10) -------------------------------------------
# The role, `claude -p`, the handoff, `stage_done` and the controller are stubbed (QStub); the register, the stop texts, the answer
# store and `question_register.record_answers` are the real ones. `planning_contract.apply_recorded_answers` is P3's (its own
# tests): here it is replaced by a recorder, because the subject is what the DRIVER does with what it returns.
def hf_register(task_root: Path, severities: dict, texts: dict | None = None, total: int = 24) -> None:
    """The S2 role's register: `severities` is {id: severity or None}; `texts` changes a question's own words (a row that changed)."""
    rows = []
    for qid, severity in severities.items():
        row = {"id": qid, "question": (texts or {}).get(qid) or f"what should happen for {qid}?",
               "readings": [{"reading": "the first reading", "from": "the ticket", "if_chosen": "x"},
                            {"reading": "the second reading", "from": "the code", "if_chosen": "y"}]}
        if severity:
            row["severity"] = severity
        rows.append(row)
    (task_root / "work").mkdir(parents=True, exist_ok=True)
    (task_root / "work" / "requirements-readiness.json").write_text(
        json.dumps({"verdict": "blocked", "register": {"total": total}, "open_questions": rows}), encoding="utf-8")


def hf_digest(s) -> str:
    return [a[a.index("--digest") + 1] for sc, a in s.py_calls if sc == "stage_done.py" and "--digest" in a][-1]


def hf2_7_halt_road() -> None:
    """K1 (B2): a halt over a register with open questions shows them and how to answer by id; the lines are recorded by CODE
    before the conductor is called; the conductor is not called when every line was a token (H31)."""
    root, task_root, env = seed(Q_TASK)
    try:
        hf_register(task_root, {"Q1": "major", "Q2": "minor", "Q3": "blocker", "Q4": None, "Q5": "blocker"})
        halting = f"{ROLE_OF['S2']} S2 {Q_TASK} · halt\nR-1 · unresolved · the ticket says two opposite things\n"
        s = QStub(root, env, digest=halting)
        d = s.driver
        person = s.run_role()
        check_eq("K1: the role's own halt is asked by the halt road", getattr(person, "kind", None), "halt")
        text = person.text
        check_in("K1: the text says it is ONE decision", "This is one decision: what the requirements tester should do about the stop above.", text)
        check("K1: every open question is a card, none cut", all(f"Q{i}" in text for i in range(1, 6)))
        block = text.split("## How to answer")[1]
        check("K1: the block offers `only stop`, not `go on`", "only `stop`" in block and "go on" not in block)
        check("K1: the block stands below the priced section", text.index("## What each answer costs") < text.index("## How to answer"))
        check_eq("K1: the text obeys human-questions.md (human_text.problems)", rules_broken(text + "\n\n---\nAnswer: x"), [])
        d.ask(person)
        words = "Q1: b\nQ2: a\nQ3: until the report\nQ4: a\nQ5: a\n"
        s.answer(root, words)
        got = q_load(task_root)
        check_eq("K1: four answers recorded by code, asked at the S2 stop",
                 [(got[q]["status"], got[q]["reading"], got[q]["where"]) for q in ("Q1", "Q2", "Q4", "Q5")], [("answered", r, "S2 stop") for r in "baaa"])
        check_eq("K1: `until the report` is kept open on the person's word", got["Q3"]["status"], "deferred_to_report")
        check_eq("K1: ONE human_answer row", sum(1 for sc, a in s.py_calls if sc == "log_append.py" and "human_answer" in a), 1)
        check_eq("K1: every line was a token - the conductor was not called (H31, FR-48)", s.conductor_calls, [])
        check_eq("K1: the words wait for the role, whole", d.state["pending_words"][s.dispatch], words.strip())
    finally:
        harness.cleanup(root)
    root, task_root, env = seed(Q_TASK)
    try:
        hf_register(task_root, {"Q1": "major", "Q2": "blocker"})
        s = QStub(root, env, digest=halting)
        d, seen = s.driver, []
        d.judged_reply = lambda *a, **k: ""
        d.unread = lambda kind, stage, dispatch, text, words="", **kw: seen.append(text)
        d.ask(s.run_role())
        s.answer(root, "Q1: b\nQ2 leave it open until the report please\n")
        prompt = seen[0] if seen else ""
        check("K1: a line code could not read goes to the conductor - once", len(seen) == 1)
        check("K1: told what code recorded, and not to record it again",
              "recorded by code: Q1: b" in prompt and "do not record these again" in prompt, prompt[:400])
        check("K1: and the conductor is not told to journal the words again", "log_append" not in prompt)
        check_eq("K1: Q1 was recorded by code, Q2 was not", (q_load(task_root)["Q1"]["status"], q_load(task_root)["Q2"]["status"]), ("answered", "open"))
    finally:
        harness.cleanup(root)


def hf2_7_blocking_stop() -> None:
    """K2, K3, K6, K10, K11 (M1, N9, H16, H26, H29, H30, H44): one open blocker stops the story below the count's limit; neither the
    count's early returns nor the stage's recorded pass hide it; `go on` passes it on the bytes shown and writes no waiver for it."""
    import story_run
    six = {f"Q{i}": "major" for i in range(1, 6)}
    root, task_root, env = seed(Q_TASK)
    try:
        hf_register(task_root, six | {"Q6": "blocker"})        # 6 open: not over the limit of 6
        s = QStub(root, env)
        d = s.driver
        person = s.run_role()
        check_eq("K2: six open questions, one a blocker: the story stops", getattr(person, "kind", None), "questions")
        check_in("K2: and says why, in words", "marked as blocking", person.text)
        check_in("K2: and how a blocking question is settled", "A question marked as blocking is settled only by a line with its id", person.text)
        # t-1336: the K15 census names this file as the pin of the key `questions.blocking` (the blocking stop's priced section, not the count's)
        check_eq("K2: the blocking stop's options are the priced section of `questions.blocking` (go on / stop)",
                 tuple(getattr(person.text, "priced", ())), ("go on", "stop"))
        check_in("K2: and `go on` is priced with the blocking row's own unverified line",
                 "the plan or the cases are written on the blocking questions left open", person.text)
        stop = d.state["question_stop"]
        check_eq("K2: the stop records its reasons and the hash of each blocker shown (H44)",
                 (stop["reasons"], stop["blocking_ids_shown"]), (["blocking"], {"Q6": stop["shown"]["Q6"]}))
        check_eq("K2: the digest says what the stop was for (H29)", hf_digest(s), "stopped on 1 blocking question(s): Q6")
        check_eq("K2: the stage is halted, never closed over the blocker", (s.statuses(), s.finishes()), (["halted"], []))
        check_eq("K2: the text obeys human-questions.md", rules_broken(person.text + "\n\n---\nAnswer: x"), [])
        d.ask(person)
        said = s.answer(root, "go on")
        check("K10: `go on` on a blocking-only stop writes no waiver (N9)", not any(sc == "waiver.py" for sc, a in s.py_calls), said)
        passed = d.state["question_stop"]["answered"]["blocking_ids"]
        check_eq("K10: and passes the blocker on the bytes it was shown with", passed, {"Q6": stop["shown"]["Q6"]})
        d.question_threshold("S2", s.role, s.dispatch)
        check("K10: the same blocker does not stop again", s.statuses().count("halted") == 1)
        hf_register(task_root, six | {"Q6": "blocker"}, texts={"Q6": "what should happen for Q6, now?"})
        try:
            d.question_threshold("S2", s.role, s.dispatch)
            again = None
        except story_run.Person as raised:
            again = raised
        check("K11: the text of the passed blocker changed - it stops again (H44)", again is not None and "Q6" in again.text)
        hf_register(task_root, six | {"Q6": "blocker", "Q7": "blocker"})
        try:
            d.question_threshold("S2", s.role, s.dispatch)
            newer = None
        except story_run.Person as raised:
            newer = raised
        check("K6: a NEW blocker always stops", newer is not None and set(d.state["question_stop"]["blocking_ids_shown"]) == {"Q6", "Q7"})
        d.ask(newer)
        s.answer(root, "Q1: a\nQ2: a")
        check_eq("K6: tokens never pass a blocker (H26)", d.state["question_stop"]["answered"]["blocking_ids"], passed)
        try:
            d.question_threshold("S2", s.role, s.dispatch)
            third = None
        except story_run.Person as raised:
            third = raised
        check("K6: the blockers the person left alone are asked again, as a re-stop that says what the answer settled",
              third is not None and "still open after your answer of " in third.text and "Q7" in third.text)
    finally:
        harness.cleanup(root)
    # the stage's recorded pass of the COUNT does not hide a blocker
    root, task_root, env = seed(Q_TASK)
    try:
        hf_register(task_root, {f"Q{i}": "major" for i in range(1, 8)} | {"Q8": "blocker"})
        s = QStub(root, env)
        d = s.driver
        code, out = d.py("waiver.py", "--task", Q_TASK, "--stage", "S2", "--block", "question threshold", "--decision", "go on, I read them")
        eq("K2: the pass of the count is recorded for the stage", code, 0, out)
        person = s.run_role()
        check_eq("K2: the count is passed by the person's word and the blocker still stops (M1)",
                 (getattr(person, "kind", None), d.state["question_stop"]["reasons"]), ("questions", ["blocking"]))
    finally:
        harness.cleanup(root)
    # one stop for the count and a blocker; `go on` there writes the waiver for the count
    root, task_root, env = seed(Q_TASK)
    try:
        hf_register(task_root, {f"Q{i}": "major" for i in range(1, 8)} | {"Q8": "blocker"})
        s = QStub(root, env)
        d = s.driver
        person = s.run_role()
        check_eq("K10: over the count AND a blocker: one stop for both", d.state["question_stop"]["reasons"], ["blocking", "over_threshold"])
        check_in("K10: and the count's own numbers", "8 questions are open", person.text)
        check_eq("K10: the text obeys human-questions.md", rules_broken(person.text + "\n\n---\nAnswer: x"), [])
        check_eq("K10: the digest says both (H29)", hf_digest(s), "stopped on 1 blocking question(s): Q8 and 8 open question(s)")
        d.ask(person)
        s.answer(root, "go on")
        check("K10: `go on` at a stop for the count writes the waiver", any(sc == "waiver.py" for sc, a in s.py_calls))
        check_eq("K10: and passes the blocker", list(d.state["question_stop"]["answered"]["blocking_ids"]), ["Q8"])
    finally:
        harness.cleanup(root)
    # S4 (H9, H30): the case designer's handoff stops; the critic's has no stop and no applying
    import planning_contract
    real, calls = planning_contract.apply_recorded_answers, []
    planning_contract.apply_recorded_answers = lambda *a, **k: calls.append(a) or {"lines": [], "rework": [], "applied": []}
    root, task_root, env = seed(Q_TASK)
    try:
        hf_register(task_root, {"Q1": "blocker"})
        s = QStub(root, env, stage="S4")
        person = s.run_role()
        check_eq("K3: S4 - the designer's handoff with an open blocker stops before the critic", (getattr(person, "kind", None), person.stage), ("questions", "S4"))
        check_eq("K3: and applied the answers first, at the S4 stop", [c[1] for c in calls], ["S4 stop"])
        calls.clear()
        s.driver.state.pop("question_stop", None)
        s.driver.question_threshold("S4", "qa-case-critic", "S4-qa-case-critic-1")
        check("K3: the critic's threshold: no stop, no applying (H30)", calls == [] and "question_stop" not in s.driver.state)
        s.driver.question_threshold("S5", "qa-automator", "S5-qa-automator-1")
        check("K3/H27: a later stage: no stop, no applying", calls == [] and "question_stop" not in s.driver.state)
    finally:
        planning_contract.apply_recorded_answers = real
        harness.cleanup(root)


def hf2_7_late_answers() -> None:
    """K4, K9, K12 (M4, F-11, H36, H40-H42, H47): what the driver does with what `apply_recorded_answers` returns."""
    import contextlib
    import io
    import planning_contract
    import question_register as QR
    import story_run
    real = planning_contract.apply_recorded_answers
    got = {"calls": [], "result": {}}
    planning_contract.apply_recorded_answers = lambda root, where, by="driver": got["calls"].append(where) or dict(got["result"])
    two = {"lines": ["Q1: your answer is now `b`, but the test plan was written for `a`; the test planner reworks the parts that followed `a`."],
           "rework": [{"owner": "designer", "where": "TC-011", "question": "Q5", "answer": "a", "record_at": "t2"},
                      {"owner": "strategist", "where": "TS-4", "question": "Q1", "answer": "b", "record_at": "t1"}],
           "applied": [{"id": "Q1", "rows": ["TS-4"]}]}
    root, task_root, env = seed(Q_TASK)
    try:
        hf_register(task_root, {f"Q{i}": "major" for i in range(1, 6)})
        for qid, reading in (("Q1", "b"), ("Q5", "a")):        # recorded by the command line, between the thresholds
            QR.record(task_root, qid, "answered", f"{qid}: {reading}", "S2 stop", "person", q_load(task_root)[qid]["row_hash"], reading=reading)
        s = QStub(root, env, stage="S3")
        d = s.driver
        got["result"] = two
        d.question_threshold("S3", s.role, s.dispatch)
        items = d.state["answer_rework"]["items"]
        check_eq("K9: one item per owner, the plan's first, the questions apart",
                 [(i["stage"], i["role"], i["rows"], i["cases"], [a["id"] for a in i["questions"]]) for i in items],
                 [("S3", "qa-test-strategist", ["TS-4"], [], ["Q1"]), ("S4", "qa-case-designer", [], ["TC-011"], ["Q5"])])
        check_eq("K4: the late answer was applied at the S3 threshold", got["calls"], ["S3 stop"])
        check_eq("K4: no conductor", s.conductor_calls, [])
        check_eq("K9: an answer from the command line: the words file is written once, with the words of the record",
                 [(task_root / i["words_file"]).read_text(encoding="utf-8") for i in items], ["Q1: b", "Q5: a"])
        check("K9: and is named driver-questionanswer-*", all(re.search(r"state/words/driver-questionanswer-\d+", i["words_file"]) for i in items))
        got["calls"].clear()
        d.question_threshold("S3", s.role, s.dispatch)
        check_eq("K9: the same pass again adds nothing to an item (the questions are not doubled)",
                 [len(i["questions"]) for i in d.state["answer_rework"]["items"]], [1, 1])
        d.question_threshold("S5", "qa-automator", "S5-qa-automator-1")
        check("K4/H27: a return at S5 applies nothing", got["calls"] == ["S3 stop"])
        # --- the step ---
        (task_root / "state").mkdir(exist_ok=True)
        (task_root / "state" / "controller.json").write_text("{}", encoding="utf-8")
        (task_root / "work" / "grounding.yaml").write_text("labels: []\n", encoding="utf-8")      # the labelled-table world: S3 closes by its projection
        dispatches, made = {}, []
        d.controller_state = lambda: {"dispatches": dispatches}
        d.rework = lambda *a, **k: made.append((a, k)) or ("", {})
        d.question_branch_findings = lambda: None
        projected = []
        d.s3_project = lambda *a, **k: projected.append(1)
        check("K9: the step moves", d.answer_rework_step() is True)
        (a, k) = made[0]
        check_eq("K9: the plan's owner first, with the rows", (a[0], a[1], a[2], k["rows"], k["cause"]), ("S3", "qa-test-strategist", [], ["TS-4"], "question_answer"))
        check_eq("K9: the person's words go by file", (k["words_file"], a[3]), (items[0]["words_file"], "Q1: b"))
        check("K8/N1: S3 closes by its projection, not by a flag: a callable whose outcome is None",
              callable(k["complete"]) and k["complete"]("digest") is None and projected == [1])
        check_in("K9: the owner is told which answer its rows do not follow yet",
                 "Q1 is answered `b` when the requirements were checked; the rows named in this rework do not follow it yet", " ".join(k["extra"]))
        check_eq("K9: one item went, the designer's is next", [i["stage"] for i in d.state["answer_rework"]["items"]], ["S4"])
        check("K9: the second step", d.answer_rework_step() is True)
        (a, k) = made[1]
        check_eq("K8/N1: the designer's rework: the cases, and complete=None (the stage's own rule)", (a[0], a[2], k["complete"]), ("S4", ["TC-011"], None))
        check("K9: the record goes with the last item", "answer_rework" not in d.state)
        # a crash after the controller registered the rework and before the item went: no second dispatch (H42)
        d.state["answer_rework"] = {"items": [dict(items[0], before=[])]}
        dispatches["S3-qa-test-strategist-9"] = {"stage": "S3", "repair_cause": "question_answer", "person_words": True, "status": "accepted"}
        made.clear()
        check("H42: the item's own dispatch is registered: it goes, nothing is started", d.answer_rework_step() is False and made == [] and "answer_rework" not in d.state)
        d.state["answer_rework"] = {"items": [dict(items[0], before=["S3-qa-test-strategist-9"])]}
        d.answer_rework_step()
        check("H42: a dispatch that was there before the item is not its own", len(made) == 1)
        dispatches["S3-qa-test-strategist-9"]["status"] = "running"
        d.state["answer_rework"] = {"items": [dict(items[0], before=["S3-qa-test-strategist-9"])]}
        made.clear()
        check("H42: a dispatch running: wait", d.answer_rework_step() is False and made == [] and "answer_rework" in d.state)
        dispatches.clear()
        # H41: the role already made the plan follow the answer. HF3-10: only a pair the check SAW when the rework was named can be dropped,
        # so the items are seeded with the pairs of a plan that branched on Q1 at TS-4 and TS-5 then (`seen` True)
        seen = [{"question": "Q1", "where": "TS-4", "seen": True}, {"question": "Q1", "where": "TS-5", "seen": True}]
        d.question_branch_findings = lambda: []
        d.state["answer_rework"] = {"items": [dict(items[0], pairs=seen[:1], before=[])]}
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            moved = d.answer_rework_step()
        check("H41: nothing is left to rework: no dispatch, the item goes", moved is False and made == [] and "answer_rework" not in d.state)
        check_in("H41: and one line says so", "the test strategist already made the plan follow your answer to Q1; no further rework is started", out.getvalue())
        d.state["answer_rework"] = {"items": [dict(items[0], rows=["TS-4", "TS-5"], pairs=seen, before=[])]}
        d.question_branch_findings = lambda: [{"question": "Q1", "where": "TS-5"}]
        d.answer_rework_step()
        check_eq("H41: a row the plan already follows leaves the item", made[-1][1]["rows"], ["TS-5"])
        # the words file: gone, or none at all -> the driver's own reason (C16)
        d.question_branch_findings = lambda: None
        d.state["answer_rework"] = {"items": [dict(items[0], words_file="state/words/gone.txt", before=[])]}
        d.answer_rework_step()
        (a, k) = made[-1]
        check("C16: a words file that is gone: the reason is the driver's own, no file named", k["words_file"] == "" and a[3].startswith("The person answered Q1"))
        # the controller refuses: the item goes and the conductor hears it WITH the words (H42)
        heard = []
        d.seam_rework_refused = lambda stage, text, words, rel, lines: heard.append((stage, text, words, rel))
        d.rework = lambda *a, **k: (_ for _ in ()).throw(story_run.ReworkRefused("controller said no"))
        d.state["answer_rework"] = {"items": [dict(items[0], before=[])]}
        check("H42: a refusal: the item goes, the conductor is told, the loop turn is spent",
              d.answer_rework_step() is True and "answer_rework" not in d.state and heard == [("S3", "controller said no", "Q1: b", items[0]["words_file"])], heard)
        # --- K12 (H36): the stop carries the pass lines into the resumed role's prompt ---
        hf_register(task_root, {f"Q{i}": "major" for i in range(1, 6)} | {"Q6": "blocker"})
        d.state.pop("question_stop", None)
        got["result"] = {"lines": two["lines"], "rework": [], "applied": [{"id": "Q1", "rows": ["TS-4"]}]}
        try:
            d.question_threshold("S3", s.role, s.dispatch)
        except story_run.Person:
            pass
        prompt = d.question_resume_prompt(s.dispatch, "Q6: a")
        check("K12: the resume prompt carries the lines of what code changed and says to read the plan again",
              two["lines"][0] in prompt and "the plan rows above were changed by code to follow the answers; read work/test-plan.json again before you edit it" in prompt)
        check("K12: and says it once", "read work/test-plan.json again" not in d.question_resume_prompt(s.dispatch, "Q6: a"))
    finally:
        planning_contract.apply_recorded_answers = real
        harness.cleanup(root)


def hf3_10_changed_answer() -> None:
    """L1-L8 (HF3-10, H41): a changed answer reopens the rework. `apply_recorded_answers` is replaced by a recorder (its own tests are
    test_question_branches P1-P7); the subject is what the DRIVER does with its `rework` and `applied`: the pairs the branch check saw
    when the rework was named, the step that drops only what it saw, and the replacement of a rework that waits for an old answer."""
    import contextlib
    import copy
    import io
    import planning_contract
    import question_register as QR
    different = planning_contract.NOT_APPLIED_DIFFERENT
    real = planning_contract.apply_recorded_answers
    got = {"result": {}}
    planning_contract.apply_recorded_answers = lambda root, where, by="driver": dict(got["result"])

    def work(question: str, where: str, answer: str, at: str, was=None, owner: str = "strategist") -> dict:
        return dict({"owner": owner, "where": where, "question": question, "answer": answer, "record_at": at},
                    **({"was": was} if was is not None else {}))

    root, task_root, env = seed(Q_TASK)
    try:
        hf_register(task_root, {f"Q{i}": "major" for i in range(1, 6)})
        for qid, reading in (("Q1", "b"), ("Q5", "b")):
            QR.record(task_root, qid, "answered", f"{qid}: {reading}", "S2 stop", "person", q_load(task_root)[qid]["row_hash"], reading=reading)
        s = QStub(root, env, stage="S3")
        d = s.driver
        (task_root / "state").mkdir(exist_ok=True)
        (task_root / "state" / "controller.json").write_text("{}", encoding="utf-8")
        (task_root / "work" / "grounding.yaml").write_text("labels: []\n", encoding="utf-8")
        dispatches, made = {}, []
        d.controller_state = lambda: {"dispatches": dispatches}
        d.rework = lambda *a, **k: made.append((a, k)) or ("", {})
        d.s3_project = lambda *a, **k: None
        # L1: the first answer `a` patched the branch off TS-3, so the check names nothing - at the merge or at the step - and the
        # person's change to `b` must still reach the strategist
        got["result"] = {"lines": [], "rework": [work("Q5", "TS-3", "b", "t2", was="a")],
                         "applied": [{"id": "Q5", "answer": "b", "not_applied": different, "rows": []}]}
        d.question_branch_findings = lambda: []
        check("L1: the pass opens a rework", d.apply_question_answers("S3")["opened"] is True)
        item = copy.deepcopy(d.state["answer_rework"]["items"][0])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            moved = d.answer_rework_step()
        check("L1: the step CALLS the strategist for TS-3 - the change is not read as `already made`",
              moved is True and len(made) == 1 and made[0][1]["rows"] == ["TS-3"], (made, out.getvalue()))
        check_not_in("L1: and no line says the plan already follows the answer", "already made", out.getvalue())
        check_eq("L2: the item carries the pair, unseen", item.get("pairs"), [{"question": "Q5", "where": "TS-3", "seen": False}])
        check_eq("L2: and the answer it was changed from", [a.get("was") for a in item["questions"]], ["a"])
        # L3: the check NAMED the pair when the rework was named, and no longer names it: the role did it - dropped, as H41 always meant
        made.clear()
        got["result"] = {"lines": [], "rework": [work("Q1", "TS-4", "b", "t3", was="a")],
                         "applied": [{"id": "Q1", "answer": "b", "not_applied": different, "rows": []}]}
        d.question_branch_findings = lambda: [{"question": "Q1", "where": "TS-4"}]
        d.apply_question_answers("S3")
        check_eq("L3: the pair was seen at the merge", d.state["answer_rework"]["items"][0].get("pairs"),
                 [{"question": "Q1", "where": "TS-4", "seen": True}])
        d.question_branch_findings = lambda: []
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            moved = d.answer_rework_step()
        check("L3: now the check is silent: no dispatch, the item goes", moved is False and made == [] and "answer_rework" not in d.state)
        check_in("L3: and the H41 line says so", "already made the plan follow your answer to Q1", out.getvalue())
        # L4: a rework waits for `b`; the person changes to `a` before it starts - ONE question, `a`, and the role is never told `b`
        made.clear()
        got["result"] = {"lines": [], "rework": [work("Q5", "TS-3", "b", "t4", was="a")],
                         "applied": [{"id": "Q5", "answer": "b", "not_applied": different, "rows": []}]}
        d.question_branch_findings = lambda: []
        d.apply_question_answers("S3")
        got["result"] = {"lines": [], "rework": [work("Q5", "TS-3", "a", "t5", was="b")],
                         "applied": [{"id": "Q5", "answer": "a", "not_applied": different, "rows": []}]}
        d.apply_question_answers("S3")
        items = d.state["answer_rework"]["items"]
        check_eq("L4: one item, one question: Q5 `a`, changed from `b`",
                 [(i["rows"], [(a["id"], a["answer"], a.get("was")) for a in i["questions"]], i["pairs"]) for i in items],
                 [(["TS-3"], [("Q5", "a", "b")], [{"question": "Q5", "where": "TS-3", "seen": False}])])
        with contextlib.redirect_stdout(io.StringIO()):
            d.answer_rework_step()
        told = " ".join(made[0][1]["extra"]) if made else ""
        check("L4: the role is told `a` and never that Q5 is answered `b`", "`a`" in told and "answered `b`" not in told, told)
        # L5: the person says `a` again with no rework to add (the rows follow it already): the waiting `b` rework is gone
        made.clear()
        got["result"] = {"lines": [], "rework": [work("Q5", "TS-3", "b", "t6", was="a")],
                         "applied": [{"id": "Q5", "answer": "b", "not_applied": different, "rows": []}]}
        d.apply_question_answers("S3")
        check("L5 control: the `b` rework is queued", "answer_rework" in d.state)
        got["result"] = {"lines": [], "rework": [], "applied": [{"id": "Q5", "answer": "a"}]}
        opened = d.apply_question_answers("S3")["opened"]
        check("L5: the answer is back to `a` with nothing to rework: the record is gone, nothing opened",
              "answer_rework" not in d.state and opened is False, d.state.get("answer_rework"))
        check_eq("L5: nothing at all queued and nothing applied: no record is written",
                 (d.apply_question_answers("S3")["opened"], "answer_rework" in d.state), (False, False))
        # L5b: an answer that was not applied by code (a changed row, an approved plan) does not displace a queued rework
        got["result"] = {"lines": [], "rework": [work("Q5", "TS-3", "b", "t6", was="a")],
                         "applied": [{"id": "Q5", "answer": "b", "not_applied": different, "rows": []}]}
        d.apply_question_answers("S3")
        got["result"] = {"lines": [], "rework": [], "applied": [{"id": "Q5", "answer": "a", "not_applied": "gate A approved"},
                                                                {"id": "Q5", "answer": "a", "before_plan": True},
                                                                {"id": "Q5", "rows": []}, {"answer": "a"}, "odd"]}
        d.apply_question_answers("S3")
        check("L5b: a refused answer, a mark before the plan, and records with no id or no answer displace nothing",
              [a["answer"] for a in d.state["answer_rework"]["items"][0]["questions"]] == ["b"])
        d.state.pop("answer_rework")
        # L6: the line the role reads says what the answer was before
        lines = d.answer_rework_lines({"stage": "S3", "questions": [{"id": "Q5", "answer": "b", "record_at": "t", "was": "a"},
                                                                     {"id": "Q1", "answer": "a", "record_at": "t", "was": ""},
                                                                     {"id": "Q2", "answer": "a", "record_at": "t", "was": "not_needed"},
                                                                     {"id": "Q3", "answer": "b", "record_at": "t"}]})
        check_in("L6: a changed answer names both", "Q5 is answered `b`", lines[0])
        check_in("L6: and what it was before", "it was `a` before, and the rows named in this rework still follow that - make them follow the new answer", lines[0])
        check_in("L6: the person's own words as the old answer", "it was your own words before", lines[1])
        check_in("L6: `not needed` as the old answer", "it was `not needed` before", lines[2])
        check_in("L6: no `was`: the line as before", "the rows named in this rework do not follow it yet - make them follow it", lines[3])
        check_not_in("L6: and says nothing of an earlier answer", "before", lines[3])
        # L7: the check could not be read when the rework was named: every pair is unseen, so the step dispatches
        made.clear()
        got["result"] = {"lines": [], "rework": [work("Q1", "TS-4", "b", "t7", was="a")],
                         "applied": [{"id": "Q1", "answer": "b", "not_applied": different, "rows": []}]}
        d.question_branch_findings = lambda: None
        d.apply_question_answers("S3")
        check_eq("L7: unread at the merge: the pair is unseen", d.state["answer_rework"]["items"][0].get("pairs"),
                 [{"question": "Q1", "where": "TS-4", "seen": False}])
        d.question_branch_findings = lambda: []
        with contextlib.redirect_stdout(io.StringIO()):
            d.answer_rework_step()
        check("L7: and the silent check at the step does not drop it: the strategist is called", len(made) == 1 and made[0][1]["rows"] == ["TS-4"])
        # L9 (F6): the person's own words twice while the first words' rework is still queued: ONE entry, one line for the question
        d.state.pop("answer_rework", None)
        got["result"] = {"lines": [], "rework": [work("Q5", "TS-3", "", "t10", was="a")],
                         "applied": [{"id": "Q5", "answer": "", "not_applied": different, "rows": [], "record_at": "t10"}]}
        d.apply_question_answers("S3")
        got["result"] = {"lines": [], "rework": [work("Q5", "TS-3", "", "t11", was="")],
                         "applied": [{"id": "Q5", "answer": "", "not_applied": different, "rows": [], "record_at": "t11"}]}
        d.apply_question_answers("S3")
        items = d.state["answer_rework"]["items"]
        check_eq("L9: one item, one entry: the second words, said to follow the first",
                 [[(a["id"], a["answer"], a["record_at"], a.get("was")) for a in i["questions"]] for i in items], [[("Q5", "", "t11", "")]])
        check_eq("L9: so the role reads one line for Q5", len(d.answer_rework_lines(items[0])), 1)
        d.apply_question_answers("S3")
        check_eq("L9: the same words again (a repeat of the pass) change nothing",
                 [[a["record_at"] for a in i["questions"]] for i in d.state["answer_rework"]["items"]], [["t11"]])
        d.state.pop("answer_rework", None)
        # L8: an item whose rework the controller already registered is not displaced, and a new item starts beside it
        made.clear()
        got["result"] = {"lines": [], "rework": [work("Q5", "TS-3", "b", "t8", was="a")],
                         "applied": [{"id": "Q5", "answer": "b", "not_applied": different, "rows": []}]}
        d.question_branch_findings = lambda: []
        d.apply_question_answers("S3")
        mine = d.state["answer_rework"]["items"][0]
        mine["before"] = []                                           # its dispatch is not among the old ones: it is registered
        dispatches["S3-qa-test-strategist-9"] = {"stage": "S3", "repair_cause": "question_answer", "person_words": True, "status": "accepted"}
        got["result"] = {"lines": [], "rework": [work("Q5", "TS-3", "a", "t9", was="b")],
                         "applied": [{"id": "Q5", "answer": "a", "not_applied": different, "rows": []}]}
        d.apply_question_answers("S3")
        items = d.state["answer_rework"]["items"]
        check_eq("L8: the registered `b` item stays as it was and a new `a` item stands beside it",
                 [[(a["answer"]) for a in i["questions"]] for i in items], [["b"], ["a"]])
        check_eq("L8: and the registered item is the first the step meets, so it goes without a dispatch (H42 b)",
                 (d.answer_rework_step(), made), (False, []))
    finally:
        planning_contract.apply_recorded_answers = real
        harness.cleanup(root)


def hf2_7_gate_a_and_completion() -> None:
    """K5 (M5, H28, F-13): `gate_repair("A")` applies before the rehearsal, never under a packet the person is reading; K8 (N1, H39): the
    road through `completion_for` closes an answer rework by the stage's own rule."""
    import planning_contract
    real, calls = planning_contract.apply_recorded_answers, []
    result = {"value": {"lines": [], "rework": [], "applied": []}}
    planning_contract.apply_recorded_answers = lambda root, where, by="driver": calls.append(where) or dict(result["value"])
    root, task_root, env = seed(Q_TASK)
    try:
        s = QStub(root, env)
        d, order = s.driver, []
        d.rehearse = lambda gate: order.append("rehearse") or {"findings": []}
        out = d.gate_repair("A")
        check_eq("K5: applied at gate A, before the rehearsal reads the plan", (calls, order, out["ran"]), (["gate A"], ["rehearse"], False))
        result["value"] = {"lines": ["x"], "rework": [{"owner": "strategist", "where": "TS-4", "question": "Q1", "answer": "b", "record_at": "t"}],
                           "applied": []}
        calls.clear()
        order.clear()
        check_eq("K5/H28: a rework is owed: the call ends as a repair round (the loop goes back to `where`), no rehearsal now",
                 (d.gate_repair("A")["ran"], order, [i["stage"] for i in d.state["answer_rework"]["items"]]), (True, [], ["S3"]))
        d.state.pop("answer_rework")
        calls.clear()
        d.state["asked"] = {"kind": "gate_A"}
        (task_root / "state").mkdir(exist_ok=True)
        d.question_path().write_text("the packet", encoding="utf-8")
        d.gate_repair("A")
        check("K5/F-13: under an open gate A packet nothing is applied", calls == [] and "answer_rework" not in d.state)
        d.state["asked"] = {}
        d.gate_repair("B")
        check("K5: gate B applies nothing", calls == [])
        # K8: the recovery road
        (task_root / "work" / "grounding.yaml").write_text("labels: []\n", encoding="utf-8")
        owned = {"repair_cause": "question_answer", "rework_of": "S3-qa-test-strategist-1", "purpose": "repair_verify"}
        closing = d.completion_for("S3", "qa-test-strategist", dict(owned, stage="S3"))
        projected = []
        d.s3_project = lambda *a, **k: projected.append(1)
        check("K8: S3 through `wait_existing_job`: the projection closes it, outcome None - not the silent False", callable(closing) and closing("d") is None and projected == [1])
        check_eq("K8: S4's designer: no flag (None)", d.completion_for("S4", "qa-case-designer", dict(owned, stage="S4")), None)
        check_eq("K8: control - the same record without the cause is the silent False the rule always gave",
                 d.completion_for("S4", "qa-case-designer", {"rework_of": "x", "purpose": "repair_verify", "stage": "S4"}), False)
    finally:
        planning_contract.apply_recorded_answers = real
        harness.cleanup(root)


def hf2_7_cause_is_a_driver_word() -> None:
    """The cause `question_answer` is the driver's word: in the controller's list BEFORE `ticket_changed` (the pin of K26), not the reviewers'."""
    import question_register as QR
    from controller import REPAIR_CAUSES, REVIEWER_CAUSES
    check_eq("controller: the list ends with ticket_changed and holds source_arrived just before it",
             (REPAIR_CAUSES[-2:], "question_answer" in REVIEWER_CAUSES), (("source_arrived", "ticket_changed"), False))
    api = (Path(__file__).resolve().parent.parent.parent / "references" / "controller-api.md").read_text(encoding="utf-8")
    check_in("controller-api.md names the cause in the list", "reviewer_error|question_answer|source_arrived|ticket_changed", api)
    check_eq("the S4 stop is in the vocabulary, in words", ("S4 stop" in QR.vocabulary()["where"], QR.where_words("S4 stop")),
             (True, "while the test cases were written"))


def main() -> None:
    run_scenarios([], [
        hf2_7_halt_road,
        hf2_7_blocking_stop,
        hf2_7_late_answers,
        hf3_10_changed_answer,
        hf2_7_gate_a_and_completion,
        hf2_7_cause_is_a_driver_word,
    ])
    harness.finish("test_story_run_loop_b_answers")


# split: runner piece 1
if __name__ == "__main__":
    main()
