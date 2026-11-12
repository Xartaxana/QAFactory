"""threshold: a part of test_story_run_loop_b.py, split by tools/test_split.py (TD-11c). The shared helpers are in story_run_loop_b_common."""
import json
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in  # noqa: E402
from story_run_common import run_scenarios, check_not_in_text, eq, rules_broken, seed
from story_run_loop_b_common import QStub, Q_TASK, ROLE_OF, q_load  # noqa: E402


def q_register(task_root: Path, ids, total: int = 24, requirements: dict | None = None) -> None:
    """The S2 role's register: each id is one open question with two readings."""
    rows = []
    for qid in ids:
        row = {"id": qid, "question": f"what should happen for {qid}?", "severity": "major",
               "readings": [{"reading": "the first reading", "from": "the ticket", "if_chosen": "x"},
                            {"reading": "the second reading", "from": "the code", "if_chosen": "y"}]}
        if requirements and qid in requirements:
            row["requirements"] = requirements[qid]
        rows.append(row)
    (task_root / "work").mkdir(parents=True, exist_ok=True)
    (task_root / "work" / "requirements-readiness.json").write_text(
        json.dumps({"verdict": "blocked", "register": {"total": total}, "open_questions": rows}), encoding="utf-8")


def question_stop_road() -> None:
    """R15 / R17 / Q8 on one story: the stop, the answer, the resume, the informed pass, the re-stop."""
    import story_run
    root, task_root, env = seed(Q_TASK)
    try:
        q_register(task_root, [f"Q{i}" for i in range(1, 8)])        # 7 open: over the default of 6
        s = QStub(root, env)
        d = s.driver
        person = s.run_role()
        check("stop: seven open questions end a role's handoff in a question", isinstance(person, story_run.Person))
        check_eq("stop: kind, stage, dispatch", (person.kind, person.stage, person.dispatch),
                 ("questions", "S2", s.dispatch))
        check_eq("stop: the stage is halted and was never closed - no finish ran before the stop (B2 row mutation b)",
                 (s.statuses(), s.finishes()), (["halted"], []))
        check_in("stop: the text says how many questions are to be decided", "7 questions to decide", person.text)
        check("stop: every open question is in the text, none cut (the gate's cap was six)",
              all(f"Q{i}" in person.text for i in range(1, 8)))
        check_in("stop: the limit is named as the factory's default, not as the project's", "default threshold", person.text)
        check_not_in_text("stop: no dispatch id and no closed stop-reason code in the words",
                          (s.dispatch, "over_threshold"), person.text)
        stop = d.state["question_stop"]
        check_eq("stop: driver state holds stage, dispatch, count", (stop["stage"], stop["dispatch"], stop["count"]),
                 ("S2", s.dispatch, 7))
        check("stop: and the instant, the share (unknown here) and no answer yet",
              bool(stop["at"]) and stop["share"] is None and "answered" not in stop)
        check("stop: the row hashes the person is shown are kept (a register changed before the answer stays visible)",
              sorted(stop["shown"]) == [f"Q{i}" for i in range(1, 8)] and all(len(h) == 64 for h in stop["shown"].values()))
        disk = json.loads((task_root / "state/driver-state.json").read_text(encoding="utf-8"))
        check_eq("stop: it is on disk, in the driver's state, not in the role's file", disk["question_stop"]["count"], 7)
        check("stop: the role's own readiness file is untouched (no `stop` block written by code)",
              "stop" not in json.loads((task_root / "work/requirements-readiness.json").read_text(encoding="utf-8")))
        check("stop: the role's result is kept for the resume, not consumed",
              (task_root / f"state/driver-runs/{s.dispatch}.json").is_file())

        # --- the console text, once (the question the person reads) ---
        d.ask(person)
        shown = (task_root / "state/driver-question.md").read_text(encoding="utf-8")
        check_in("ask: the question file says which kind it is", "kind: questions", shown)
        check_eq("ask: the text obeys human-questions.md", rules_broken(shown), [])

        # --- the answer: tokens by code, words whole, no conductor --------------------------------
        words = ("Q1: a\nQ2: b\nQ3: not needed\nQ4: c\nQ9: a\nQ5 I do not know yet, ask the owner.\n"
                 "Q6: a, but only for the admin role\n")
        said = s.answer(root, words)
        got = q_load(task_root)
        check_eq("answer: Q1 is answered with reading a, asked at the S2 stop",
                 (got["Q1"]["status"], got["Q1"]["reading"], got["Q1"]["where"]), ("answered", "a", "S2 stop"))
        check_eq("answer: Q2 is answered with reading b", (got["Q2"]["status"], got["Q2"]["reading"]), ("answered", "b"))
        check_eq("answer: Q3 is `not needed`", got["Q3"]["status"], "not_needed")
        check("answer: the words are kept WHOLE in the record (FR-8), not the line", got["Q1"]["words"] == words.strip())
        check_eq("answer: the record stores the hash of the row AS SHOWN", got["Q1"]["record_row_hash"], stop["shown"]["Q1"])
        check("answer: a letter beyond the readings is not recorded - it stays open",
              got["Q4"]["status"] == "open" and "beyond its 2 readings" in said)
        check("answer: prose about a question, and a letter followed by words, are not tokens - they stay open",
              got["Q5"]["status"] == "open" and got["Q6"]["status"] == "open")
        check_in("answer: an id that is not open is printed back as not recognised", "not recognised as open questions", said)
        check_in("answer: and is named", "Q9", said)
        check("answer: nothing is recorded for the unknown id", "Q9" not in got)
        check_eq("answer: the words wait for the role's own session, whole", d.state["pending_words"].get(s.dispatch), words.strip())
        check_eq("answer: the answer is the informed pass - the count and share the person saw are kept",
                 (d.state["question_stop"]["answered"]["count"], d.state["question_stop"]["answered"]["share"]), (7, None))
        check("answer: the question flag is cleared", not d.state.get("asked"))
        check("answer: the words are journalled as a human answer by code",
              any(sc == "log_append.py" and "human_answer" in a for sc, a in s.py_calls))
        check_eq("answer: no conductor was called (FR-48)", s.conductor_calls, [])

        # --- the resume: the SAME session, its own text, no conductor, halted -> running -> done ------
        check_eq("resume: the role's session is the one the driver stored", d.state["sessions"][s.dispatch], "sess-1")
        s.claude_calls.clear()
        d.resume_role("S2", s.role, s.dispatch, d.state["pending_words"][s.dispatch])
        check_eq("resume: ONE call, in the existing session, never a new dispatch (B2 row mutation c)",
                 [(c["kind"], c["resume"]) for c in s.claude_calls], [("role", "sess-1")])
        prompt = s.claude_calls[0]["prompt"]
        check_in("resume: it has its own text", 'The person answered the open questions: "Q1: a', prompt)
        check_in("resume: and says the answers are recorded and not to ask again",
                 f"Their answers are recorded; continue your dispatch {s.dispatch} on them — do not ask them again.", prompt)
        check_not_in_text("resume: not `from where you stopped`, said to a role that had finished",
                          ("from where you stopped",), prompt)
        check_eq("resume: the stage goes halted -> running, then the finish closes it (E-7)",
                 (s.statuses(), len(s.finishes())), (["halted", "running"], 1))
        check_eq("resume: no conductor on the resume (B2 row mutation a)", s.conductor_calls, [])
        check("resume: the words are consumed and the resume mark is gone",
              s.dispatch not in d.state["pending_words"] and "resume" not in d.state["question_stop"])

        # --- the informed pass (Q8): the same count does not stop again, only a larger one --------------
        q_register(task_root, [f"Q{i}" for i in range(1, 11)])       # Q4..Q10 open = 7, the count answered at
        halts = s.statuses().count("halted")
        try:
            d.question_threshold("S2", s.role, s.dispatch)
            same = None
        except story_run.Person as raised:
            same = raised
        check("informed pass: 7 open after an answer at 7 - NO second stop (the same count)",
              same is None and s.statuses().count("halted") == halts)
        q_register(task_root, [f"Q{i}" for i in range(1, 12)])       # Q4..Q11 open = 8
        try:
            d.question_threshold("S2", s.role, s.dispatch)
            again = None
        except story_run.Person as raised:
            again = raised
        check("informed pass: 8 open, one more than the person answered at - the stop comes back", again is not None)
        if again is not None:
            check_in("re-stop: the changed text says it is still open after the answer, and when",
                     "still open after your answer of ", again.text)
            check_in("re-stop: and what the answer settled (Q1, Q2 answered and Q3 not needed = 3)",
                     "Your answer settled 3 questions", again.text)
            check("re-stop: no answered question is asked again (FR-7)", not re.search(r"\bQ[123]\b", again.text))
            check("re-stop: the still-open ones are all there", all(f"Q{i}" in again.text for i in range(4, 12)))
            check_eq("re-stop: it is recorded at the new count, and the earlier answer is kept",
                     (d.state["question_stop"]["count"], d.state["question_stop"]["answered"]["count"]), (8, 7))
            check_eq("re-stop: the stage is halted again", s.statuses()[-1], "halted")
        check_eq("the conductor stayed out of all of it", s.conductor_calls, [])
    finally:
        harness.cleanup(root)


def question_stop_share_and_limits() -> None:
    """Q8 for the SHARE, and the boundaries of `larger_than_answered` (the threshold's own edges are B1's)."""
    import story_run
    larger = story_run.Driver.larger_than_answered
    check("larger: a larger count", larger(8, None, {"count": 7, "share": None}))
    check("larger: the same count is not larger (strictly)", not larger(7, None, {"count": 7, "share": None}))
    check("larger: a smaller count is not larger", not larger(6, None, {"count": 7, "share": None}))
    check("larger: a larger share", larger(3, 0.5, {"count": 3, "share": 0.4}))
    check("larger: the same share is not larger", not larger(3, 0.4, {"count": 3, "share": 0.4}))
    check("larger: an unknown share is never larger (FR-41)", not larger(3, None, {"count": 3, "share": 0.4}))
    check("larger: and is not compared with an unknown one", not larger(3, 0.4, {"count": 3, "share": None}))
    check("larger: a count that was never recorded is not compared", not larger(9, None, {"count": None, "share": None}))
    root, task_root, env = seed(Q_TASK)
    try:
        reqs = {"Q1": ["R-1", "R-2", "R-3"], "Q2": ["R-4", "R-5", "R-6"], "Q3": ["R-7", "R-8", "R-9"]}
        q_register(task_root, ["Q1", "Q2", "Q3"], total=24, requirements=reqs)     # 3 open, 9 of 24 = 0.375 > 1/3
        s = QStub(root, env)
        person = s.run_role()
        check("share: 3 questions are under the count limit but 9 of 24 requirements is over a third - it stops",
              isinstance(person, story_run.Person) and person.kind == "questions")
        check_eq("share: the stop records count and share", (s.driver.state["question_stop"]["count"],
                 round(s.driver.state["question_stop"]["share"], 3)), (3, 0.375))
        s.driver.ask(person)
        s.answer(root, "I will answer all three in words: go with the ticket.")
        try:
            s.driver.question_threshold("S2", s.role, s.dispatch)
            same = None
        except story_run.Person as raised:
            same = raised
        check("share: after a free-word answer the same share does not stop again", same is None)
        q_register(task_root, ["Q1", "Q2", "Q3"], total=24,
                   requirements={"Q1": reqs["Q1"] + ["R-10"], "Q2": reqs["Q2"], "Q3": reqs["Q3"]})   # 10 of 24
        try:
            s.driver.question_threshold("S2", s.role, s.dispatch)
            again = None
        except story_run.Person as raised:
            again = raised
        check("share: a LARGER share (10 of 24) stops again, with the changed text",
              again is not None and "still open after your answer of " in again.text)
    finally:
        harness.cleanup(root)


def question_stop_edges() -> None:
    """The edges of the wiring: (i) a failing count, (ii) the role's own halt, (viii) the person's pass,
    (v) free words, (ix) S3, and the stop at a stage with no stop defined."""
    import question_stop
    root, task_root, env = seed(Q_TASK)
    try:
        q_register(task_root, [f"Q{i}" for i in range(1, 8)])
        s = QStub(root, env)
        # (i) the count itself fails: told, never a stop (P1)
        real = question_stop.over_threshold
        try:
            def broken(*a, **k):
                raise RuntimeError("the thresholds file is gone")
            question_stop.over_threshold = broken
            import contextlib
            import io
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                person = s.run_role()
            check("(i) a count that raises does not stop the factory: the stage closes", person is None and len(s.finishes()) == 1)
            check_in("(i) and the failure is printed as a note", "the question threshold was not checked at S2", out.getvalue())
            check_in("(i) with its cause", "the thresholds file is gone", out.getvalue())
        finally:
            question_stop.over_threshold = real
        # (i) a malformed register is not over: no stop, no crash
        (task_root / "work" / "requirements-readiness.json").write_text("{not json", encoding="utf-8")
        s = QStub(root, env)
        person = s.run_role()
        check("(i) a malformed register is not over: the stage closes", person is None and len(s.finishes()) == 1)
        (task_root / "work" / "requirements-readiness.json").unlink()
        s = QStub(root, env)
        person = s.run_role()
        check("(i) no register at all: nothing to count, the stage closes", person is None and len(s.finishes()) == 1)

        # (ii) the role stopped on its own: the `halt` road only, the threshold does not double-stop
        q_register(task_root, [f"Q{i}" for i in range(1, 8)])
        halting = f"{ROLE_OF['S2']} S2 {Q_TASK} · halt\nR-1 · unresolved · the ticket says two opposite things\n"
        s = QStub(root, env, digest=halting)
        person = s.run_role()
        check_eq("(ii) a role that halted itself is asked by the halt road", getattr(person, "kind", None), "halt")
        check("(ii) and no threshold stop is recorded", "question_stop" not in s.driver.state)
        check_eq("(ii) and the stage is halted once", s.statuses(), ["halted"])

        # (viii) the person's word passes the block, recorded by the waiver itself (FR-4)
        s = QStub(root, env)
        code, out = s.driver.py("waiver.py", "--task", Q_TASK, "--stage", "S3", "--block", "question threshold",
                                "--decision", "go on, I read them")
        eq("(viii) a pass for ANOTHER stage is recorded", code, 0, out)
        person = s.run_role()
        check("(viii) and does not pass this stage", getattr(person, "kind", None) == "questions")
        s.driver.state.pop("question_stop", None)           # the next driver starts without that stop
        s.driver.save_state()
        s = QStub(root, env)
        code, out = s.driver.py("waiver.py", "--task", Q_TASK, "--stage", "S2", "--block", "question threshold",
                                "--decision", "go on, I read them")
        eq("(viii) the pass for this stage is recorded by waiver.py", code, 0, out)
        check_in("(viii) in the story's own file, with the words",
                 "go on, I read them", (task_root / "pipeline.json").read_text(encoding="utf-8"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            person = s.run_role()
        check("(viii) with the pass recorded, there is no stop and the stage closes", person is None and len(s.finishes()) == 1)
        check_in("(viii) and the pass is said in the log, with the words", "go on, I read them", out.getvalue())
        check("(viii) no stop was recorded in the driver's state", "question_stop" not in s.driver.state)
    finally:
        harness.cleanup(root)

    # (ix) S3: the strategist's stop; a free-word answer is kept whole and goes to the role
    root, task_root, env = seed(Q_TASK)
    try:
        q_register(task_root, [f"Q{i}" for i in range(1, 9)])
        s = QStub(root, env, stage="S3")
        person = s.run_role()
        check_eq("(ix) S3: the stop is asked at the plan stage", (person.kind, person.stage), ("questions", "S3"))
        check_in("(ix) S3: the batch carries every open question of the register", "8 questions to decide", person.text)
        s.driver.ask(person)
        free = "Go with what the ticket says everywhere, and tell me in the plan what you assumed."
        s.answer(root, free)
        got = q_load(task_root)
        check("(v) free words record nothing by code: no question is marked answered that the person did not name",
              all(q["status"] == "open" for q in got.values()))
        check_eq("(v) the words are kept whole for the role", s.driver.state["pending_words"][s.dispatch], free)
        check_in("(v) and in the driver's answer file, whole", free,
                 (task_root / "state/driver-answers.jsonl").read_text(encoding="utf-8"))
        s.driver.resume_role("S3", s.role, s.dispatch, free)
        check_in("(v) the resume carries them", free, s.claude_calls[-1]["prompt"])
        check_eq("(ix) S3: halted -> running -> done, nothing deleted", (s.statuses(), len(s.finishes())),
                 (["halted", "running"], 1))
    finally:
        harness.cleanup(root)
    root, task_root, env = seed(Q_TASK)
    try:
        q_register(task_root, [f"Q{i}" for i in range(1, 9)])
        s = QStub(root, env, stage="S3")
        s.driver.ask(s.run_role())
        s.answer(root, "Q1: a\nQ2: not needed")
        got = q_load(task_root)
        check_eq("(ix) S3: a token answer is recorded as asked at the S3 stop", (got["Q1"]["where"], got["Q2"]["where"]),
                 ("S3 stop", "S3 stop"))
    finally:
        harness.cleanup(root)


def question_stop_fallbacks() -> None:
    """R17, FR-57, edge (iv): a resume goes to the existing session; with none, or a failed one, the SAME dispatch
    runs again in a new session as a rework whose reason is the words, verbatim. Never both."""
    words = "Q1: a\nand please keep the admin cases apart"
    for label, sid, failing in (("no session id", False, False), ("a session that cannot be resumed", True, True),
                                ("a session that resumes", True, False)):
        root, task_root, env = seed(Q_TASK)
        try:
            q_register(task_root, [f"Q{i}" for i in range(1, 8)])
            s = QStub(root, env)
            d = s.driver
            person = s.run_role()
            d.ask(person)
            s.answer(root, words)
            if not sid:
                d.state["sessions"].pop(s.dispatch, None)
            check_eq(f"{label}: the words wait for the role", d.state["pending_words"][s.dispatch], words)
            reworks, before = [], len(s.claude_calls)
            d.run_role = lambda stage, role, **kw: reworks.append(dict(kw, stage=stage, role=role)) or ("", {})
            if failing:
                s.claude_result = {"result": "", "session_id": "", "stderr": "no such session", "total_cost_usd": 0.0,
                                   "is_error": True, "exit_code": 1}
            d.resume_role("S2", s.role, s.dispatch, words, complete=None)
            if label == "a session that resumes":
                check_eq(f"{label}: no rework, no new dispatch (B2 row mutation c)", reworks, [])
                check_eq(f"{label}: the existing session got the call", [c["resume"] for c in s.claude_calls[before:]], ["sess-1"])
            else:
                check_eq(f"{label}: one rework of the SAME dispatch, reason = the words verbatim",
                         [(r["rework"]["id"], r["rework"]["reason"], r["stage"], r["role"]) for r in reworks],
                         [(s.dispatch, words, "S2", s.role)])
                check_eq(f"{label}: and no resume call reached a session that does not exist",
                         [c["resume"] for c in s.claude_calls[before:]], [] if not sid else ["sess-1"])
                runs = task_root / "state" / "driver-runs"
                check(f"{label}: the saved result is set aside, not deleted, so the role runs again and sees the words",
                      not (runs / f"{s.dispatch}.json").is_file() and (runs / f"{s.dispatch}.stopped.json").is_file())
                check(f"{label}: the words are consumed", s.dispatch not in d.state["pending_words"])
                check_eq(f"{label}: the conductor stayed out", s.conductor_calls, [])
        finally:
            harness.cleanup(root)


def question_stop_loop_moves() -> None:
    """The loop's moves for a question stop (edge x): an unanswered stop is asked again and never finished
    from the saved result; an answered one is resumed by the loop with the question text."""
    import story_run
    root, task_root, env = seed(Q_TASK)
    try:
        q_register(task_root, [f"Q{i}" for i in range(1, 8)])
        s = QStub(root, env)
        d = s.driver
        person = s.run_role()
        d.ask(person)
        action = {"action": "wait_existing_job", "dispatch_id": s.dispatch}
        before = len(s.finishes())
        try:
            d.dispatch_action(action)
            again = None
        except story_run.Person as raised:
            again = raised
        check("loop: an unanswered stop is asked again", again is not None and again.kind == "questions")
        check_eq("loop: and the saved result is NOT finished over it", len(s.finishes()), before)
        if again is not None:
            check_eq("loop: same stage and dispatch", (again.stage, again.dispatch), ("S2", s.dispatch))
            check_in("loop: the same batch", "7 questions to decide", again.text)
            check_not_in_text("loop: the answer block is not printed twice", ("Answer: write your words",), again.text)
        s.answer(root, "Q1: a\nQ2: a\nQ3: a")
        s.claude_calls.clear()
        d.dispatch_action(action)
        check_eq("loop: an answered stop is resumed by the loop, in the existing session",
                 [(c["kind"], c["resume"]) for c in s.claude_calls], [("role", "sess-1")])
        check_in("loop: with the question text", "The person answered the open questions:", s.claude_calls[0]["prompt"])
        check_eq("loop: halted -> running -> done", (s.statuses(), len(s.finishes())), (["halted", "running"], before + 1))
        check_eq("loop: no conductor", s.conductor_calls, [])
        # a halt answered the old way keeps its own text (the resume mark belongs to a stop only)
        d.state["pending_words"][s.dispatch] = "go on"
        s.claude_calls.clear()
        d.resume_role("S2", s.role, s.dispatch, "go on")
        check_in("loop: an ordinary resume keeps the halt road's text", "from where you stopped", s.claude_calls[0]["prompt"])
    finally:
        harness.cleanup(root)


def main() -> None:
    run_scenarios([], [
        question_stop_road,
        question_stop_share_and_limits,
        question_stop_edges,
        question_stop_fallbacks,
        question_stop_loop_moves,
    ])
    harness.finish("test_story_run_loop_b_threshold")


# split: runner piece 1
if __name__ == "__main__":
    main()
