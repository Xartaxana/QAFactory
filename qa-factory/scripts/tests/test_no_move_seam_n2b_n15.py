#!/usr/bin/env python3
"""n2b n15: a part of test_no_move_seam.py, split by tools/test_split.py (TD-11c). The shared helpers are in no_move_seam_common."""
import contextlib
import io
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402
from story_run_common import driver_for, jsonl, seed  # noqa: E402
import human_text  # noqa: E402
import no_move as NM  # noqa: E402
import story_run  # noqa: E402
from no_move_seam_common import (  # noqa: E402
    FACTS, answer, logged_rig, raised, rig, seam_asked, take, verdict,
)


def n2b_the_facts_are_read_from_the_project() -> None:
    root, task_root, driver = rig()
    try:
        facts = driver.no_move_facts({"dispatch": ""})
        check_eq("N2b: a clean project: not closed, nothing running, no attempt, no dispatch, no exclusion",
                 (facts["closed"], facts["running"], facts["attempts"], facts["dispatch_status"], facts["live_exclusions"]),
                 (False, False, 0, None, False))
        moves = NM.move_ids()
        check("N2b: a dispatch id the controller does not know removes the dispatch-tied moves",
              not {"resume_with_words", "release_and_restart"} & set(driver.open_moves({"dispatch": "S5-nope"}, moves)))
        driver.state["delivery_attempts"] = [{"status": "in_flight"}]
        check("N2b: a delivery attempt in flight removes rework_stage and release_and_restart",
              not {"rework_stage", "release_and_restart"} & set(NM.open_moves(driver.no_move_facts({"dispatch": ""}), moves)))
        driver.controller_state = lambda: {}
        broken = driver.no_move_facts({"dispatch": "S5-x"})
        check("N2b: an unreadable controller.json: every controller fact is None",
              all(broken[name] is None for name in ("dispatch_status", "session", "running", "closed", "rework_stages")), str(broken))
        check("N2b: and the moves that need them are removed",
              not {"rework_stage", "resume_with_words", "release_and_restart"} & set(NM.open_moves(broken, moves)))
        check_eq("N2b: the standing moves stay", sorted({"person_does", "stop_here"} & set(NM.open_moves(broken, moves))),
                 ["person_does", "stop_here"])
    finally:
        harness.cleanup(root)


def n5b_a_token_never_reaches_a_gate_recorder() -> None:
    root, task_root, driver = logged_rig()
    try:
        driver.boundary = "gate_A"
        seen = []
        driver.record_by_code = lambda *a, **k: seen.append(a) or True
        seam_asked(driver, stage="S4", dispatch="")
        check_eq("N5b: a `retry` to an options question raised at the gate boundary is read by the seam branch, nothing else",
                 take(driver, answer(task_root, "g.md", b"retry\r\n")), None)
        check_eq("N5b: record_by_code was called 0 times", seen, [])
        check_eq("N5b: and the conductor 0 times", driver.calls, [])
    finally:
        harness.cleanup(root)


def n6_s1_review_keeps_today() -> None:
    root, task_root, driver = logged_rig(answers=[{"action": "ask_person", "did": "x", "question": "Which source did you mean?",
                                                   "why_person": "access", "checked": "the refusal"}])      # RN1-9: the legacy road needs a class too (E-8)
    try:
        recorded = []
        driver.record_review = lambda words: (recorded.append(words), True)[1]
        driver.state["asked"] = {"kind": "s1_review", "stage": "S1", "dispatch": "S1-qa-scout-1"}
        check_eq("N6: an answer record_review reads is recorded as today", take(driver, answer(task_root, "r1.md", b"accepted as is\r\n")), None)
        check_eq("N6: record_review was called once with the words", recorded, ["accepted as is"])
        check_eq("N6: the conductor was not called, the words are filed for the dispatch",
                 (driver.calls, driver.state["pending_words"].get("S1-qa-scout-1")), ([], "accepted as is"))
        driver.record_review = lambda words: False
        driver.state["asked"] = {"kind": "s1_review", "stage": "S1", "dispatch": "S1-qa-scout-1"}
        person = take(driver, answer(task_root, "r2.md", b"something else entirely"))
        check("N6: an answer it cannot read goes to the conductor and back as the conductor's own question, with no options",
              person is not None and (person.kind, person.text, bool(person.offered)) == ("s1_review", "Which source did you mean?", False))
        check_not_in("N6: and the call carried no moves section", "## Moves open here", driver.calls[0]["text"])
    finally:
        harness.cleanup(root)


def n7_the_words_file_round_trip() -> None:
    raw = b"please look at the second window\r\nit is the stand, I think\r\n"
    root, task_root, driver = logged_rig(answers=[verdict((("retry", "person_does"), ("restart", "release_and_restart")),
                                                          question="What now? `retry` or `restart`?"),
                                                  {"action": "continue", "did": "restarted"}])
    try:
        driver.ask(story_run.Person("conductor", "What should happen at the plan stage?", "S5", "S5-qa-x-1"))
        person = take(driver, answer(task_root, "a1.md", raw))
        check("N7: a free two-line CRLF answer reaches the seam and comes back as an options question",
              person is not None and list(person.offered) == ["retry", "restart"])
        rel = person.words_file
        check("N7: the words file is task-root relative", rel.startswith("state/words/") and not Path(rel).is_absolute(), rel)
        check_eq("N7: and holds the answer's raw bytes", (task_root / rel).read_bytes(), raw)
        check_eq("N7: the conductor got the words with plain newlines", driver.calls[0]["words"],
                 "please look at the second window\nit is the stand, I think")
        check_eq("N7: the seam handed that very file to the conductor", driver.calls[0]["words_file"], rel)
        driver.ask(person)
        check_eq("N7: ask() keeps it in asked.words_file", driver.state["asked"]["words_file"], rel)
        driver.calls.clear()
        token_file = answer(task_root, "a2.md", b"restart\r\n")
        released = []
        real_release = story_run.waiver.run_release
        story_run.waiver.run_release = lambda task_root, dispatch, **kw: (released.append((dispatch, kw)), (0, "released"))[1]
        try:
            check_eq("N7: the token `restart` is read against the offered options and moves", take(driver, token_file), None)
        finally:
            story_run.waiver.run_release = real_release
        # C2-6 (t-722 §4.4): `restart` is executed by CODE through waiver.run_release with the ORIGINAL words' file, no conductor call
        check_eq("N7 (C2-6, t-873 F-1): `restart` released the dispatch the question names with the ORIGINAL file and the DRIVER'S env (UTF-8), and the conductor was not called",
                 (released, driver.calls), ([("S5-qa-x-1", {"words_file": str(driver.task_root / rel), "env": driver.env})], []))
        check_not_in("N7: the token is not filed into pending_words", "restart", json.dumps(driver.state["pending_words"]))
        row = jsonl(task_root / "state" / "driver-answers.jsonl")[-1]
        check_eq("N7: the driver-answers row has the token", row["token"], "restart")
        check_eq("N7: and the file of that very answer", (task_root / row["words_file"]).read_bytes(), b"restart\r\n")
        check_eq("N7: the question is closed", driver.state["asked"], {})
    finally:
        harness.cleanup(root)


def n7a_a_lone_cr_still_makes_one_words_file() -> None:
    """F-3: the file is NAMED by the seam, not worked out from the text: a lone CR (which `take_answer` reads as a newline) is
    where the old string comparison failed and a second file was written."""
    raw = b"a\rb"
    root, task_root, driver = logged_rig()
    try:
        seen = []
        driver.conductor = story_run.Driver.conductor.__get__(driver)
        driver.step = lambda *a, **k: "next: nothing"
        driver.run_claude = lambda kind, prompt, **k: (seen.append(prompt), {"result": '{"action": "continue", "did": "d"}', "session_id": "s",
                                                                             "stderr": "", "total_cost_usd": 0, "num_turns": 1})[1]
        driver.ask(story_run.Person("conductor", "What should happen at the plan stage?", "S5", "S5-qa-x-1"))
        check_eq("N7a: a lone-CR answer is taken", take(driver, answer(task_root, "cr.md", raw)), None)
        files = sorted(path for path in (task_root / "state" / "words").glob("*") if path.is_file())
        check_eq("N7a: ONE words file is written, with the raw bytes", [path.read_bytes() for path in files], [raw])
        row = jsonl(task_root / "state" / "driver-answers.jsonl")[-1]
        check("N7a: the prompt names it", len(seen) == 1 and str(driver.task_root / row["words_file"]) in seen[0], str(seen[:1])[:300])
        check_eq("N7a: and the driver-answers row names the same file", (task_root / row["words_file"]).resolve(), files[0].resolve())
    finally:
        harness.cleanup(root)


def n7b_tokens_by_code() -> None:
    root, task_root, driver = logged_rig(answers=[verdict(), {"action": "continue", "did": "took the move"}])
    try:
        seam_asked(driver)
        check_eq("N7b: `retry` goes back to where, no conductor", (take(driver, answer(task_root, "t1.md", b"retry")), driver.calls), (None, []))
        check("N7b: and is recorded as the person's answer", any("human_answer" in a for a in driver.logged))
        seam_asked(driver)
        person = take(driver, answer(task_root, "t2.md", b"stop"))
        check("N7b: `stop` brings the question back changed (exit 3), tokens kept, nothing called",
              person is not None and "You said to stop" in person.text and person.offered == ("retry", "stop") and not driver.calls)
        head = person.text.split("\n\n")[0]
        check_in("N7b: the stop re-ask names the offered token minus `stop`", "answer `retry`.", head)
        check_not_in("N7b: and not a token the question did not offer", "`go on`", head)
        seam_asked(driver, (("retry", "person_does"), ("go on", "go_on_as_is"), ("stop", "stop_here")))
        head = take(driver, answer(task_root, "t2b.md", b"stop")).text.split("\n\n")[0]
        check_in("N7b: with three offered tokens it names the two others", "answer `retry` or `go on`.", head)
        seam_asked(driver)
        person = take(driver, answer(task_root, "t3.md", b"go on"))
        check("N7b: a standing word the question did not offer is not a token: the seam reads it as words",
              person is not None and len(driver.calls) == 1 and driver.calls[0]["words"] == "go on")
        driver.calls.clear()
        waivers = []
        inner = driver.py
        driver.py = lambda script, *a, **k: (waivers.append(a), (0, ""))[1] if script == "waiver.py" else inner(script, *a, **k)
        seam_asked(driver, (("retry", "person_does"), ("go on", "go_on_as_is")), block="stand not confirmed")
        check_eq("N7b: `go on` with a block code knows runs waiver.py by code",
                 (take(driver, answer(task_root, "t4.md", b"go on\r\n")), driver.calls), (None, []))
        flat = list(waivers[0]) if waivers else []
        check("N7b: with the block and the file of THIS answer", "--block" in flat and "stand not confirmed" in flat and "--words-file" in flat
              and Path(flat[flat.index("--words-file") + 1]).read_bytes() == b"go on\r\n", str(flat))
        waivers.clear()
        seam_asked(driver, (("retry", "person_does"), ("go on", "go_on_as_is")), block="")
        check("N7b: `go on` with no block known is the conductor's (chosen), never a waiver by code",
              take(driver, answer(task_root, "t5.md", b"go on")) is None and not waivers and len(driver.calls) == 1)
        driver.calls.clear()
        driver.pipeline = lambda: {"stages": {"S5": {"status": "done"}}}
        seam_asked(driver, (("retry", "person_does"), ("restart", "release_and_restart")))
        logged = len(driver.logged)
        check_eq("N7b: a token at a stage that is already done is recorded and moves nothing",
                 (take(driver, answer(task_root, "t6.md", b"restart")), driver.calls), (None, []))
        check("N7b: it is recorded as the person's answer", len(driver.logged) > logged and "human_answer" in driver.logged[-1])
    finally:
        harness.cleanup(root)


def n7c_a_delivery_flag_cannot_capture_a_seam_answer() -> None:
    root, task_root, driver = logged_rig(answers=[verdict()])
    try:
        driver.state["delivery_question"] = True
        seam_asked(driver, stage="S8")
        person = take(driver, answer(task_root, "d.md", b"no delivery"))
        check("N7c: `no delivery` to a seam question at S8 is not the delivery branch's: no declined mark, the seam read the words",
              person is not None and "delivery" not in driver.state and len(driver.calls) == 1)
    finally:
        harness.cleanup(root)


def n8_by_hand_becomes_an_option() -> None:
    root, task_root, driver = logged_rig(answers=[verdict(), {"action": "ask_person", "did": "x", "question": "What now?"}])
    try:
        receipt = "state/environment-jobs/job-1.json"
        (task_root / receipt).parent.mkdir(parents=True, exist_ok=True)
        (task_root / receipt).write_text(json.dumps({"idempotency_key": "k-1"}), encoding="utf-8")
        inner = driver.py
        driver.py = lambda script, *a, **k: (0, json.dumps({"status": "blocked", "settled": False, "uncertain_process": True,
                                                            "job": {"steps": [{"name": "build", "status": "running"}], "phase": "up"}})
                                             ) if script == "environment_preparation.py" else inner(script, *a, **k)
        def job_question():
            try:
                driver.environment_job({"job_id": "job-1", "receipt_ref": receipt, "stage": "S5"})
            except story_run.Person as raised_person:
                return raised_person
        person = job_question()
        check("N8: the uncertain-process job ends in a closed question of kind environment",
              person is not None and person.kind == "environment" and {"retry", "stop"} <= set(person.offered))
        prompt = driver.calls[0]["text"]
        check("N8: the conductor reads the site's own account (the lead) BEFORE the moves section",
              "did NOT start it again" in prompt and "the process that owned it is gone" in prompt
              and prompt.index("did NOT start it again") < prompt.index("## Moves open here"), prompt[:300])
        path = f"qa-factory/artifacts/QA-9/{receipt}"
        check("N8: the options came back without the record path: the person's question keeps the lead above them",
              path in person.text and "did NOT start it again" in person.text
              and person.text.index("did NOT start it again") < person.text.index("## What each answer costs and does"))
        check_not_in("N8: the body carries no `reconcile`", "reconcile", person.text)
        check_not_in("N8: and no `.py`", ".py", person.text)
        check_in("N8: the command is in answer_note", "reconcile", person.answer_note)
        # the conductor's second answer has no options: the fallback shows the factory's own sentences (the lead) as the body
        fallback = job_question()
        check("N8: with no usable conductor answer the body (the lead) still carries no command",
              fallback is not None and list(fallback.offered) == ["retry", "go on", "stop"] and "did NOT start it again" in fallback.text
              and "reconcile" not in fallback.text and ".py" not in fallback.text, repr(fallback and fallback.text[:300]))
        check_in("N8: and the command is in answer_note", "reconcile", fallback.answer_note)
        driver.ask(person)
        shown = (driver.state_dir / "driver-question.md").read_text(encoding="utf-8")
        body, _, block = shown.partition("\n---\nAnswer:")
        check("N8: the question body has no command (no `reconcile`, no `.py`)", "reconcile" not in body and ".py" not in body)
        check("N8: the answer block carries the answer command and the probe command", "--answer" in block and "reconcile" in block and "--probe" in block)
    finally:
        harness.cleanup(root)


def n8b_the_lead_is_shown_only_when_the_prose_drops_a_kept_fact() -> None:
    path = "qa-factory/artifacts/QA-9/state/job.json"
    state = {"why": "by_hand", "kind": "environment", "stage": "S5", "text": "d", "keep": [path],
             "lead": f"THE FACTORY SAW a stopped job.\n- the record: {path}"}
    cases = [("the prose names the kept path", verdict(question=f"What now? `retry` or `stop`? The record is {path}."), state, False),
             ("the prose drops it", verdict(), state, True),
             ("the site kept nothing", verdict(), dict(state, keep=[]), False),
             ("a stop that drops it", verdict(action="stop"), state, True)]
    for label, answer_verdict, case_state, shown in cases:
        root, task_root, driver = rig(answers=[answer_verdict])
        try:
            driver.boundary = "S5:x"
            _, person = raised(driver, case_state)
            check_eq(f"N8b {label}: the lead is shown above the conductor's question", "THE FACTORY SAW" in person.text, shown)
            if shown:
                check("N8b: and it comes first", person.text.startswith("THE FACTORY SAW")
                      and person.text.index("THE FACTORY SAW") < person.text.index("What should happen?"))
        finally:
            harness.cleanup(root)


def n10_infra_inside_the_call_is_an_exit() -> None:
    root, task_root, env = seed("QA-9")
    driver = driver_for(root, env, "QA-9")
    try:
        def down(text, *, words="", files=None, words_file=None):
            raise story_run.InfraStop("auth", "the login is gone")
        driver.conductor = down
        driver.where = lambda: (_ for _ in ()).throw(story_run.Refusal("the moon is down"))
        code = driver.run()
        check_eq("N10: an InfraStop inside the conductor call is exit 5", code, story_run.EXIT_INFRA)
        check("N10: and no question file", not (driver.state_dir / "driver-question.md").exists())
        check_eq("N10: nothing is asked, the seam is free again", (driver.state.get("asked") or {}, driver._in_no_move), ({}, False))
    finally:
        harness.cleanup(root)


def n11_a_refusal_outside_guarded_is_a_question() -> None:
    root, task_root, env = seed("QA-9")
    first = driver_for(root, env, "QA-9")
    try:
        person = story_run.Person("environment", "Which stand should the story use?", "S5")
        person.stand_stage = "S5"
        first.ask(person)
        reply = answer(task_root, "stand.md", b"Local\r\n")
        driver = driver_for(root, env, "QA-9", answer=str(reply))
        driver.stand_names = lambda: ["Local"]
        inner = driver.py

        def py(script, *a, check=False, expect=""):      # C1-7c Q-3: the real `py`'s signature; a G site's `expect` is forwarded
            if script == "stage_done.py" and check:
                raise (story_run.gate_refusal(script, 1, "the pipeline is locked", expect) if expect else
                       story_run.Refusal("stage_done.py --task QA-9 (exit 1): the pipeline is locked", retry=None))
            return inner(script, *a, check=check, expect=expect)
        driver.py = py
        code = driver.run()
        check_eq("N11: a Refusal raised by py(check=True) inside take_answer is exit 3 (a question), not a traceback", code, story_run.EXIT_PERSON)
        shown = (driver.state_dir / "driver-question.md").read_text(encoding="utf-8")
        check_in("N11: the question file carries the priced options", "## What each answer costs and does", shown)
        check_not_in("N11: and not the refusal's own words", "pipeline is locked", shown)
        check_in("N11: those stay in the details file", "pipeline is locked", (driver.state_dir / "driver-question-details.md").read_text(encoding="utf-8"))
        check_eq("N11: asked carries what the seam offered", driver.state["asked"]["offered"], ["retry", "go on", "stop"])
        asked = driver.state["asked"]
        check("N11: asked.words_file names the file of the answer the refusal came out of, which holds its raw bytes",
              bool(asked.get("words_file")) and (task_root / asked["words_file"]).read_bytes() == b"Local\r\n", str(asked.get("words_file")))
        rows = jsonl(task_root / "state" / "driver-answers.jsonl")
        check_eq("N11: the person's word is on the record (one row: the words, no token, that very file)",
                 [(row["words"], row["token"], row["words_file"]) for row in rows], [("Local", "", asked["words_file"])])
        check_eq("N11: an answer already on the record is not settled twice", (driver.settle_unread_answer(), len(jsonl(task_root / "state" / "driver-answers.jsonl"))), ("", 1))
    finally:
        harness.cleanup(root)


def n12_unreadable_conductor_answer() -> None:
    root, task_root, driver = logged_rig(answers=[{"action": "_unreadable", "did": "", "question": ""}])
    try:
        driver.boundary = "S5:x"
        _, person = raised(driver, {"why": "refusal", "text": "t"})
        check_eq("N12: an unreadable answer renders the fallback", list(person.offered), ["retry", "go on", "stop"])
        check_eq("N12: with exactly one defect_found", len(driver.defects), 1)
    finally:
        harness.cleanup(root)
    root, task_root, driver = logged_rig(answers=[{"action": "_unreadable", "did": "", "question": ""}])
    try:
        driver.boundary = "S8:answer"
        result, person = raised(driver, {"why": "unread_answer", "kind": "gate_B", "stage": "S8", "text": "t", "words": "w"})
        check_eq("N12 (flipped by C1-4b): at a gate kind it is the gate fallback `retry` / `stop` (one defect_found), never raw output "
                 "as a question and no longer a silent `continue`",
                 (result, person.kind, list(person.offered), len(driver.defects)), (None, "gate_B", ["retry", "stop"], 1))
    finally:
        harness.cleanup(root)
    root, task_root, driver = logged_rig()
    try:
        driver.conductor = story_run.Driver.conductor.__get__(driver)
        driver.step = lambda *a, **k: "next: nothing"
        driver.run_claude = lambda kind, prompt, **k: {"result": "I looked at it for a long while and wrote no line of json.", "session_id": "s",
                                                       "stderr": "", "total_cost_usd": 0, "num_turns": 1}
        got = driver.conductor("r")
        check_eq("N12: Driver.conductor with no JSON line answers `_unreadable` with no question (the raw end is not a question)",
                 (got["action"], got["question"]), ("_unreadable", ""))
    finally:
        harness.cleanup(root)


def n12b_the_defect_row_reaches_the_real_journal() -> None:
    """t-668: `log_append` requires `ref` for `defect_found`; the seam's call carried none and the rejection was ignored, so no row was
    ever written. No stub on `log_append` here: the REAL script writes the row into the task's journal."""
    for site, state in (("the fallback", {"why": "refusal", "text": "t", "dispatch": "S5-qa-x-1"}),
                        ("the fallback with no dispatch", {"why": "refusal", "text": "t"}),
                        ("a gate kind", {"why": "unread_answer", "kind": "gate_B", "stage": "S8", "dispatch": "S8-gate", "text": "t", "words": "w"}),
                        ("a gate kind with no dispatch", {"why": "unread_answer", "kind": "gate_B", "stage": "S8", "text": "t", "words": "w"})):
        root, task_root, env = seed("QA-9")
        driver = driver_for(root, env, "QA-9")
        driver.conductor = lambda text, **k: {"action": "_unreadable", "did": "", "question": ""}
        driver.no_move_facts = lambda state: dict(FACTS)
        try:
            driver.boundary = "S8:answer"
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                raised(driver, state)
            rows = [r for r in jsonl(root / "qa-factory" / "records" / "journal.jsonl") if r.get("event") == "defect_found"]
            check_eq(f"N12b {site}: exactly one defect_found row in the real journal", len(rows), 1)
            row = rows[0] if rows else {}
            check(f"N12b {site}: the row has a non-empty ref and the factory's owner mark",
                  bool(row.get("ref")) and str(row.get("notes", "")).startswith("owner: factory"), str(row))
            check_eq(f"N12b {site}: ref = the state's dispatch, else the boundary", row.get("ref"), state.get("dispatch") or "S8:answer")
            check_eq(f"N12b {site}: nothing was rejected, so nothing is said on stderr", err.getvalue(), "")
        finally:
            harness.cleanup(root)
    # a journal that rejects the write is said once on stderr and the run goes on
    root, task_root, env = seed("QA-9")
    driver = driver_for(root, env, "QA-9")
    try:
        driver.py = lambda script, *a, **k: (1, "JOURNAL: record rejected:\n- event 'defect_found' requires field 'ref'")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            driver.file_defect("", "owner: factory — x")
        lines = err.getvalue().splitlines()
        check("N12b: a rejected write is one stderr line naming the rejection and does not raise",
              len(lines) == 1 and "requires field 'ref'" in lines[0], err.getvalue())
    finally:
        harness.cleanup(root)


def n13_a_megabyte_answer() -> None:
    root, task_root, driver = rig()
    try:
        big = "x" * 1_000_000
        driver.conductor = story_run.Driver.conductor.__get__(driver)
        driver.step = lambda *a, **k: "next: nothing"
        seen = []
        driver.run_claude = lambda kind, prompt, **k: (seen.append(prompt), {"result": '{"action": "continue", "did": "d"}', "session_id": "s",
                                                                             "stderr": "", "total_cost_usd": 0, "num_turns": 1})[1]
        driver._answer = {"text": big, "rel": None}
        driver.conductor("r", words=big, words_file=driver.answer_file())
        check("N13: a 1 MB answer: the prompt is cut at the limit", len(seen[0]) < story_run.NO_MOVE_WORDS_IN_PROMPT + 40000, str(len(seen[0])))
        check_eq("N13: and the words file holds all of it", len((task_root / driver.answer_file()).read_bytes()), 1_000_000)
    finally:
        harness.cleanup(root)


def n14_price_labels_that_cannot_be_read() -> None:
    real = human_text.rules()
    for count in (0, 1, 2):
        short = dict(real, price_lines={"labels": real["price_lines"]["labels"][:count]})
        try:
            human_text.price_labels(short)
            raised_it = False
        except human_text.LabelsUnreadable:
            raised_it = True
        check(f"N14: price_labels with {count} of the 3 labels raises", raised_it)
    try:
        human_text.price_labels({k: v for k, v in real.items() if k != "price_lines"})
        raised_it = False
    except human_text.LabelsUnreadable:
        raised_it = True
    check("N14: a rules file with no price_lines raises too", raised_it)
    check_eq("N14: and the three labels are returned whole", human_text.price_labels(real), ["the factory:", "you:", "the story:"])
    short = dict(real, price_lines={"labels": ["the factory:", "you:"]})
    check_eq("N14: price_problems (a detector) never raises on the same data", human_text.price_problems("(a) `retry` - x", ["retry"], short), [])
    original = human_text.rules
    for label, answers, state in (("the fallback", [], {"why": "refusal", "call": False, "text": "t"}),
                                  ("the conductor's own options", [verdict()], {"why": "refusal", "text": "t"})):
        root, task_root, driver = rig(answers=answers)
        try:
            driver.boundary = "S5:x"
            human_text.rules = lambda: short
            try:
                _, person = raised(driver, state)
            finally:
                human_text.rules = original
            check_eq(f"N14 {label}: unreadable labels end in the last-resort question (the three standing words)",
                     list(person.offered), ["retry", "go on", "stop"])
            check_not_in(f"N14 {label}: with no half-priced options", "## What each answer costs and does", person.text)
            check(f"N14 {label}: and exactly one defect_found", len(driver.defects) == 1, str(driver.defects))
        finally:
            human_text.rules = original
            harness.cleanup(root)


def n15_a_gave_up_stop_files_the_free_answer_for_its_dispatch() -> None:
    for boundary, expected in (("S5:S5-qa-code-critic-2", "S5-qa-code-critic-2"), ("gate_A", "")):
        root, task_root, env = seed("QA-9")
        driver = driver_for(root, env, "QA-9")
        try:
            def give_up():
                driver.boundary = boundary
                raise story_run.Stop(story_run.EXIT_GAVE_UP, "the conductor gave up on this step")
            driver.where = give_up
            with contextlib.redirect_stdout(io.StringIO()):
                code = driver.run()
            check_eq(f"N15 {boundary}: the exit code is the gave-up one", code, story_run.EXIT_GAVE_UP)
            check_eq(f"N15 {boundary}: the question names the dispatch of the boundary (a free answer is filed for it)",
                     driver.state["asked"].get("dispatch"), expected)
        finally:
            harness.cleanup(root)


def main() -> None:
    for scenario in (
        n2b_the_facts_are_read_from_the_project,
        n5b_a_token_never_reaches_a_gate_recorder,
        n6_s1_review_keeps_today,
        n7_the_words_file_round_trip,
        n7a_a_lone_cr_still_makes_one_words_file,
        n7b_tokens_by_code,
        n7c_a_delivery_flag_cannot_capture_a_seam_answer,
        n8_by_hand_becomes_an_option,
        n10_infra_inside_the_call_is_an_exit,
        n11_a_refusal_outside_guarded_is_a_question,
        n12_unreadable_conductor_answer,
        n12b_the_defect_row_reaches_the_real_journal,
        n13_a_megabyte_answer,
        n8b_the_lead_is_shown_only_when_the_prose_drops_a_kept_fact,
        n14_price_labels_that_cannot_be_read,
        n15_a_gave_up_stop_files_the_free_answer_for_its_dispatch,
    ):
        scenario()
    harness.finish("no_move seam_n2b_n15")


# split: runner piece 1
if __name__ == "__main__":
    main()
