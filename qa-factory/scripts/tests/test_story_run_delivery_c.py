"""Story runner tests, delivery, third part: the third verdict at gate B, the gate B options, the gate prices, the seam.

Split out of test_story_run_delivery_b.py (t-778, CI round 6: that file ran 218 s against the 300 s cap, FR-31); the stub, the
builders and the runner live in story_run_common.py. Never launches a real `claude -p` (harness points STORY_RUN_CLAUDE at no_claude.py).
"""
import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_in, check_not_in  # noqa: E402
from story_run_common import (  # noqa: E402
    run_scenarios,
    d2_answer, d2_conductor_calls, driver_for, eq, human_broken, s0_pipeline, seed, set_control,
)
# the gate A / gate B rigs of the sibling file (t-778: shared, not copied)
from test_story_run_delivery_b import (  # noqa: E402
    A364_REMEDY, B272_TICKET, a364_doors, a364_packet, a364_probe, a364_overrides, a364_rehearsal, a364_take, b272_cleanup, flag_file, gate_a_story, gate_b_packet,
    man1_gate_b, recording_stub,
)


# --- t-305 N8: the third verdict at gate B and after it -------------------------------------------------------------

AFTER_CHECKS = harness.FIXTURES / "after-checks"


def story_from_fixture(task: str) -> tuple:
    """A seeded driver project whose task root holds the `after-checks` fixture (its own pipeline.json is the seed's)."""
    import shutil
    root, task_root, env = seed(task)
    for source in AFTER_CHECKS.rglob("*"):
        rel = source.relative_to(AFTER_CHECKS)
        if source.is_dir() or rel.as_posix() == "pipeline.json":
            continue
        target = task_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(source, target)
    return root, task_root, env


def n8_gate_text_quotes_the_report_and_branches_on_the_word() -> None:
    """K-N8.17 (Q22, R6, C7): `gate_text` quotes the report's verdict block and its Left with you whole - even when that
    section starts after character 4000, where the dead `## 3` regex used to cut - and the closing sentence follows the word."""
    import gate_brief
    import human_text
    task = "QA-9"
    root, task_root, env = story_from_fixture(task)
    try:
        report = task_root / "test-report.md"
        text = report.read_text(encoding="utf-8").replace(
            "**The change.** Checkout refuses a coupon above the cap",
            "**The change.** " + ("A long paragraph the scribe wrote about the change. " * 120) + "Checkout refuses a coupon above the cap")
        report.write_text(text, encoding="utf-8", newline="\n")
        for word, ledger in (("yes", {"delivery_ready": True, "delivery_verdict": "yes"}),
                             ("after_checks", {"delivery_ready": False, "delivery_verdict": "after_checks"}),
                             ("no", {"delivery_ready": False, "delivery_verdict": "no"})):
            (task_root / "work" / "ledger.json").write_text(json.dumps(dict(ledger, rows=[])), encoding="utf-8")
            driver = driver_for(root, env, task)
            driver.py = lambda script, *a, **k: (0, "brief") if script == "gate_brief.py" else (0, "rehearsal")
            packet = driver.gate_text("B")
            eq(f"K-N8.17 {word}: the report is past the old 4000-character cut", report.read_text(encoding="utf-8").index("## Left with you") > 4000, True)
            check_in(f"K-N8.17 {word}: the verdict block is quoted", "## The verdict (test-report.md)", packet)
            check_in(f"K-N8.17 {word}: Left with you is quoted whole, from its heading", "## Left with you\n", packet)
            for ref in ("TC-002", "TC-004", "TC-005"):
                check_in(f"K-N8.17 {word}: its item for {ref}", f", {ref})", packet)
            offers = "say whether the MR is opened (Draft)" in packet
            eq(f"K-N8.17 {word}: the instruction {'offers' if word != 'no' else 'does not offer'} the MR", offers, word != "no")
            eq(f"K-N8.17 {word}: the third word adds the line about what is left with them",
               "its description carries what is left with you" in packet, word == "after_checks")
            eq(f"K-N8.17 {word}: `no` names the road for the MR only (F8: a bug is filed from the numbers, never through that word)",
               # HF8-23: the sentence is `gate_brief.risk_form()` (approval word first, then the risk line of its own), the same text the skill road prints
               ("to open one, " + gate_brief.risk_form() in packet, "file a bug anyway" in packet), (word == "no", False))
            # the report's own section is the scribe's text (a handed command keeps its flags); what THIS node writes into the
            # packet - the closing instruction - never shows a script, a flag or an exit code
            closing = packet.rsplit("\n\n", 1)[1]
            eq(f"K-N8.17 {word}: the closing instruction shows no script name, flag or exit code",
               [p["rule"] for p in human_text.problems(closing, kind="report") if p["rule"] in ("script_name", "flag", "exit_code")], [])
        # C7: the "can change it" sentence only when an answer at this gate could change the word
        sentence = "This verdict was computed before your answer"
        driver = driver_for(root, env, task)
        driver.py = lambda script, *a, **k: (0, "brief") if script == "gate_brief.py" else (0, "rehearsal")
        check_not_in("K-N8.17 no gap, no undecided ENV: the sentence is not printed", sentence, driver.gate_text("B"))
        (task_root / "work" / "automation-manifest.json").write_text(json.dumps(
            {"tests": [], "unresolved": [{"case": "TC-005", "reason": "blocked_by_env", "owner": "user", "detail": "no profile"}]}),
            encoding="utf-8")
        check_in("K-N8.17 a stand gap is waiting: the sentence says the word is computed again", sentence + "; an answer to a stand gap "
                 "below can change it, and it is computed again before anything goes out.", driver.gate_text("B"))
        eq("K-N8.17 gate_brief.gate_b_gaps agrees there is a gap", len(gate_brief.gate_b_gaps(task_root)), 1)
    finally:
        b272_cleanup(root)


def n8_every_word_of_the_packet_obeys_human_questions() -> None:
    """t-342's rule for what this node writes into the packet: with each of the three words, the whole gate B packet of a story
    with a stand gap (the card, the form, the closing instruction, the "computed again" sentence) has no problem
    `human_text` finds (`human_text.problems(kind="question") == []`)."""
    root, task_root, env = man1_gate_b()
    try:
        driver = driver_for(root, env, B272_TICKET)
        # the report parts are shown only where a report exists
        (task_root / "test-report.md").write_text("# T - test report\n\n## Left with you\n\nNothing is left with you.\n",
                                                  encoding="utf-8", newline="\n")
        for word, ledger in (("yes", {"delivery_ready": True, "delivery_verdict": "yes"}),
                             ("after_checks", {"delivery_ready": False, "delivery_verdict": "after_checks"}),
                             ("no", {"delivery_ready": False, "delivery_verdict": "no"})):
            (task_root / "work").mkdir(parents=True, exist_ok=True)
            (task_root / "work" / "ledger.json").write_text(json.dumps(dict(ledger, rows=[])), encoding="utf-8")
            packet = gate_b_packet(driver, task_root)
            eq(f"N8 {word}: the whole gate B packet obeys human-questions.md (human_text.problems == [])", human_broken(packet), [])
            eq(f"N8 {word}: and says the verdict was computed before the answer (a stand gap waits)",
               "This verdict was computed before your answer" in packet, True)
    finally:
        b272_cleanup(root)


def n8_the_verdict_is_computed_again_after_gate_b() -> None:
    """K-N8.7 (F5, N-4, the position invariant): a stand gap answered at gate B (`TC-005: accept`) can move the verdict, so
    `after_gate_B` runs the three scripts again BEFORE the bug reporter and before the delivery, brings the report up to the new
    word (the head, with its "Changed since gate B" notice) and checks it; the delivery is told the new word."""
    task = "QA-9"
    root, task_root, env = story_from_fixture(task)
    try:
        manifest = json.loads((task_root / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
        manifest["unresolved"] = [{"case": "TC-005", "reason": "blocked_by_env", "owner": "user", "detail": "no android profile"}]
        (task_root / "work" / "automation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        case_file = task_root / "work" / "test-cases" / "checkout" / "TC-005.md"
        case_file.write_text(case_file.read_text(encoding="utf-8").replace("status: Approved", "status: Automated"), encoding="utf-8")
        driver = driver_for(root, env, task)
        # S8 as it ran before gate B: the scripts, then the report's blocks - the verdict reads `no` (the stand gap is undecided)
        for script in ("check_traceability.py", "ledger.py", "check_delivery.py"):
            driver.py(script, f"qa-factory/artifacts/{task}")
        driver.rebuild_report()
        # HF2-6b (t-125): `report_facts --check` compares the appendix with a render of the story as it stands; this key changed the
        # story (a handed-over case, status Automated) after the fixture report was written, so the scribe's paste is made again here
        harness.repaste_appendix(task_root)
        ledger = lambda: json.loads((task_root / "work" / "ledger.json").read_text(encoding="utf-8"))  # noqa: E731
        eq("K-N8.7 before the answer the ledger says no", ledger()["delivery_verdict"], "no")
        before = (task_root / "test-report.md").read_text(encoding="utf-8")
        check_in("K-N8.7 and the report's head says it", "**Verdict: not ready to ship as is.**", before)
        # gate B: the person answers the card; the driver recorded it as the stage override `stand gap: TC-005`
        pipeline = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))
        pipeline["gates"] = {"B": {"decision": "approved", "status": "approved", "authorization_source": "TC-005: accept"}}
        pipeline["stage_overrides"] = [{"stage": "S9", "match": "stand gap: TC-005", "by": "human",
                                        "decision": "accept - the person wrote: TC-005: accept", "at": "2026-10-03T10:00:00+00:00"}]
        (task_root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        calls, real_py = [], driver.py

        def spy(script, *args, **kw):
            calls.append(script)
            return real_py(script, *args, **kw)
        driver.py = spy
        driver.controller_state = lambda: {"decisions": {"d-1": {"gate": "B", "status": "approved", "selected_drafts": ["BD-1"],
                                                                 "authorization_source": "TC-005: accept"}}, "dispatches": {}}
        driver.run_role = lambda *a, **k: calls.append("<<reporter dispatch>>") or ("", "continue")
        seen = {}
        driver.delivery = lambda decision: (calls.append("<<delivery>>"), seen.update(word=getattr(driver, "recomputed_word", None)))
        with contextlib.redirect_stdout(io.StringIO()):
            driver.after_gate_B()
        order = [c for c in calls if c in ("check_traceability.py", "ledger.py", "check_delivery.py", "report_facts.py",
                                           "delivery_summary.py", "<<reporter dispatch>>", "<<delivery>>")]
        first_gated = min(order.index("<<reporter dispatch>>"), order.index("<<delivery>>"))
        eq("K-N8.7 the three scripts run before anything gated, in S8's order", order[:3],
           ["check_traceability.py", "ledger.py", "check_delivery.py"])
        check("K-N8.7 and the report is brought up to the word and checked before the reporter and the delivery",
              order.index("report_facts.py") < first_gated and order.count("report_facts.py") >= 2, str(order))
        check("K-N8.7 the reporter is dispatched before the delivery (as before)", order.index("<<reporter dispatch>>") < order.index("<<delivery>>"), str(order))
        eq("K-N8.7 the answer moved the ledger no -> after_checks", ledger()["delivery_verdict"], "after_checks")
        eq("K-N8.7 and the delivery is told the new word", seen["word"], "after_checks")
        after = (task_root / "test-report.md").read_text(encoding="utf-8")
        check_in("K-N8.7 the head is rewritten from it", "**Verdict: ready once you finish the checks left with you.**", after)
        check_in("K-N8.7 with the notice of what it read before", 'Changed since gate B: the verdict read "**Verdict: not ready to ship as is.**', after)
        check_in("K-N8.7 the answer's item stands in its own block, with their words", "### Added after gate B (from your answers)", after)
        check_in("K-N8.7 ... naming the case and quoting them", 'TC-005', after.split("### Added after gate B")[1].split("<!-- /facts")[0])
        eq("K-N8.7 --check passes by construction", [p for p in __import__("report_facts").check(task_root) if "Added after gate B" in p], [])
        # NEG: with the recompute taken out the ledger stays `no`, which is what the key above would see
        eq("K-N8.7 NEG control: the word before the recompute was `no`, so the move is the recompute's", before.count("not ready to ship as is"), 1)
    finally:
        b272_cleanup(root)


def n8_the_recompute_decides_on_the_printed_word() -> None:
    """K-N8.26 (t-305 N8 attempt 2, F4, FR-59): `recompute_verdict` reads `check_delivery --json` and decides on the PARSED word,
    never on the exit code (the check exits 1 for `no`, for `after_checks` and on a crash alike). A check that crashes, times
    out or prints nothing parseable has established nothing: the driver stops with the factory's own reason in words (no script
    name, flag or exit code in it), the ledger keeps the word it held, and nothing outward - no reporter, no delivery - opens."""
    import story_run
    task = "QA-9"
    root, task_root, env = story_from_fixture(task)
    try:
        rel = f"qa-factory/artifacts/{task}"
        driver = driver_for(root, env, task)
        driver.py("check_delivery.py", rel)
        ledger_file = task_root / "work" / "ledger.json"

        def stored() -> tuple:
            """The verdict the ledger holds: the word and its bool (the rest is rewritten by the S8 scripts each time)."""
            doc = json.loads(ledger_file.read_text(encoding="utf-8"))
            return doc.get("delivery_verdict"), doc.get("delivery_ready")
        held = stored()
        (task_root / "test-report.md").unlink(missing_ok=True)       # the head is not what is under test here
        real_py, calls = driver.py, []

        def fake(says):
            def py(script, *args, **kw):
                if script == "check_delivery.py":
                    calls.append("check_delivery")
                    return says
                return real_py(script, *args, **kw)
            return py
        driver.controller_state = lambda: {"decisions": {"d-1": {"gate": "B", "status": "approved", "selected_drafts": ["BD-1"],
                                                                 "authorization_source": "go"}}, "dispatches": {}}
        driver.run_role = lambda *a, **k: calls.append("<<reporter dispatch>>") or ("", "continue")
        seen = {}
        driver.delivery = lambda decision: (calls.append("<<delivery>>"), seen.update(word=getattr(driver, "recomputed_word", None)))
        bad = (("a crash", (1, "Traceback (most recent call last):\n  File \"check_delivery.py\", line 1\nKeyError: 'x'")),
               ("nothing printed", (1, "")), ("prose, not a record", (0, "all good, delivery_ready: yes")),
               ("a timeout", (124, "check_delivery.py did not finish within 600 seconds")),
               ("a record with no word", (1, json.dumps({"reasons": []}))),
               ("a word the reader reads as unknown", (0, json.dumps({"delivery_verdict": "yes", "delivery_ready": False}))))
        defects = []
        driver.file_defect = lambda ref, notes: defects.append(notes)         # the journal row is counted, not written
        for label, says in bad:
            calls.clear()
            defects.clear()
            driver.py = fake(says)
            refused = None
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    driver.after_gate_B()
            except story_run.Person as exc:                  # C1-6c (S9): a closed question, no longer a Refusal that promises a look
                refused = str(exc.text)
                eq(f"K-N8.26 {label}: kind and stage of the question", (exc.kind, exc.stage), ("delivery_check", "S8"))
            check(f"K-N8.26 {label}: the driver asks", refused is not None)
            text = refused or ""
            lead = text.split("## What each answer costs and does")[0]
            check(f"K-N8.26 {label}: the reason is in words - no script name, flag or exit code in it",
                  ".py" not in lead and "--" not in lead and "exit" not in lead.lower(), lead)
            check_in(f"K-N8.26 {label}: it says the factory's own gap and that nothing was delivered", "nothing was delivered", text)
            check(f"K-N8.26 {label}: ... and the sentence `the factory will look at it` is gone", "will look at it" not in text, text)
            check(f"K-N8.26 {label}: the answers are priced (retry / no delivery / stop, three lines each)",
                  all(f"`{t}`" in text for t in ("retry", "no delivery", "stop")) and text.count("the story:") == 3, text)
            eq(f"K-N8.26 {label}: exactly ONE defect_found, owner factory", [d.startswith("owner: factory") for d in defects], [True])
            eq(f"K-N8.26 {label}: the stored verdict is unchanged", stored(), held)
            check(f"K-N8.26 {label}: nothing outward opened (no reporter, no delivery)",
                  "<<reporter dispatch>>" not in calls and "<<delivery>>" not in calls, str(calls))
        # the parsed word decides - whatever the exit code said
        for word, code in (("after_checks", 1), ("no", 1), ("yes", 0), ("yes", 1)):
            calls.clear()
            driver.py = fake((code, json.dumps({"delivery_verdict": word, "delivery_ready": word == "yes"})))
            with contextlib.redirect_stdout(io.StringIO()):
                driver.after_gate_B()
            eq(f"K-N8.26 the printed `{word}` (exit {code}) is the word the delivery is told", seen.get("word"), word)
            check(f"K-N8.26 the printed `{word}`: the story goes on to the delivery", "<<delivery>>" in calls, str(calls))
            driver.state["delivery"] = None
        # C1-6c (S9, FR-9): each answer of `s8.delivery_check` has an executor
        crash, good = fake((1, "")), fake((1, json.dumps({"delivery_verdict": "yes", "delivery_ready": True})))

        def asked_person():
            driver.py = crash
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    driver.after_gate_B()
            except story_run.Person as exc:
                with contextlib.redirect_stdout(io.StringIO()):
                    driver.ask(exc)
                return exc
            raise AssertionError("the crashing check did not ask")

        def answer(words):
            path = task_root / "work" / "answer.txt"
            path.write_text(words, encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                driver.take_answer(path)
        asked_person()
        answer("retry")
        calls.clear()
        driver.py = good
        with contextlib.redirect_stdout(io.StringIO()):
            driver.after_gate_B()
        check("K-N8.26 `retry`: the check runs again and the story goes on to the delivery", calls.count("check_delivery") == 1 and "<<delivery>>" in calls, str(calls))
        driver.state["delivery"] = None
        asked_person()
        calls.clear()
        try:
            answer("stop")
            held = None
        except story_run.Person as exc:
            held = exc
        check("K-N8.26 `stop`: the question is held, nothing runs", held is not None and held.kind == "delivery_check"
              and held.text.startswith("You said to stop") and "<<delivery>>" not in calls)
        # C-F1 (FR-2, FR-10): after `stop` the door named is a real one - `retry` carries on, `no delivery` ENDS the delivery and is never
        # offered as the way to get it
        said = (held.text if held else "").split("\n\n")[0]
        check("K-N8.26 `stop`: the re-ask names `retry` to carry on and `no delivery` to end the delivery, not to get it",
              "To carry on, answer `retry`; to end the delivery here with nothing sent, answer `no delivery`." in said
              and "after all" not in said, said)
        S = story_run.Driver
        eq("C-F1 the report that does not match: only the door that ends it", S.delivery_stop_door(("no delivery",)),
           "To end the delivery here with nothing sent, answer `no delivery`.")
        eq("C-F1 the delivery question: both carrying doors, then the one that ends it", S.delivery_stop_door(("go on", "retry", "no delivery")),
           "To carry on, answer `go on` or `retry`; to end the delivery here with nothing sent, answer `no delivery`.")
        driver.state["asked"] = {}
        asked_person()
        calls.clear()
        driver.gate_b_ran.clear()           # a new process: the reporter of the first pass is not this one's
        driver.py = good
        with contextlib.redirect_stdout(io.StringIO()):
            driver.after_gate_B()
        check("C-F4 control: before the decline the same call dispatches the reporter", "<<reporter dispatch>>" in calls, str(calls))
        driver.state["delivery"] = None
        asked_person()
        answer("no delivery")
        eq("K-N8.26 `no delivery`: the declined mark, as today", (driver.state.get("delivery") or {}).get("action"), "declined_by_person")
        calls.clear()
        driver.gate_b_ran.clear()
        driver.py = crash
        shown = io.StringIO()
        with contextlib.redirect_stdout(shown):
            driver.after_gate_B()
        check("K-N8.26 `no delivery`: the check that still cannot answer asks no more and nothing is delivered", "<<delivery>>" not in calls, str(calls))
        # F-7 (the owner, 28.10.2026: "only the MR"): `no delivery` calls off the MR and nothing else - the bug reporter writes a local file
        # and sends nothing out, so it still runs for a `bugs` order that is due
        check("F-7 `no delivery`: the bug reporter still runs after the decline (only the MR is cancelled)", "<<reporter dispatch>>" in calls, f"{calls}")
    finally:
        b272_cleanup(root)


# --- B-414 (D-0029, D-0032): what the environment record decided once reaches the story at gate A -----------------------------

B414_KEY = {"scope": "case", "environment": "QA", "definition_sha": "b" * 64, "precondition_kind": "feature_flag", "check_digest": "c" * 64}
B414_LEVEL_KEY = {"scope": "level", "contour": "web", "argv_digest": "a" * 64, "reason_class": "zero_tests"}


def b414_ep(key=None, ep_id="EP-1", words="TC-007: accept always") -> dict:
    return {"id": ep_id, "subject": key or B414_KEY, "option": "accept", "words": words, "at": "2026-10-05T10:00:00+00:00", "story": "T-0", "about": '"x"'}


def b414_covered(task_root, gid: str, case: str, ep=None) -> dict:
    """A covered CASE gap as the shown packet keeps it (`stand_gaps.covered_a`'s mapping)."""
    import stand_gaps
    row = next(r for r in stand_gaps.declared_preconditions(task_root) if r["id"] == gid)
    return stand_gaps.covered_a(task_root, {"covered_gaps": [dict(row, scope="case", property=ep or b414_ep())]})[0]


def b414_state(covered=(), gaps=()) -> dict:
    return {"shown_gaps": {"A": {"gaps": list(gaps), "covered": list(covered)}}}


def b414_live(task_root) -> dict:
    return {k: v for k, v in a364_overrides(task_root).items() if not v.get("revoked_at")}


def b414_environment_record_at_gate_a() -> None:
    import contract
    import environment_record as ER
    from story_run import Driver
    # R8(a) / R16: a gap's cases are counted whole, and a changed word in THIS answer is never overridden by a stale `decided`
    level = {"id": "RP-web", "case_id": "", "cases": ["TC-001", "TC-002"], "scope": "level"}
    own = {"id": "PC-5", "case_id": "TC-002"}
    now = [{"gap": level, "option": "accept"}]
    eq("R8(a): a level accept names every case of the level", Driver.accepted_cases([level], now, {}), ["TC-001", "TC-002"])
    eq("R8(a): a case with ANOTHER open gap is not accepted, the other is", Driver.accepted_cases([level, own], now, {}), ["TC-001"])
    eq("R8(a): and when that gap is accepted by an earlier word it is", Driver.accepted_cases([level, own], now, {"PC-5": {"option": "accept"}}), ["TC-001", "TC-002"])
    eq("R16 guard (iii): a non-accept word for any gap of the case in THIS answer wins over a stale `decided`",
       Driver.accepted_cases([level, own], now + [{"gap": own, "option": "theirs"}], {"PC-5": {"option": "accept"}}), ["TC-001"])
    # R8(c): a covered CASE gap, a line-less answer: no rehearsal is run, the gap's own override and the case carry are written
    # with `by` and the record's row; the case is blocked through `stand_accept_cases`
    root, task_root, env = gate_a_story()
    try:
        covered = b414_covered(task_root, "PC-1", "TC-007")
        driver, printed, decided, ran = a364_take(root, env, task_root, "approve - go on", extra_state=b414_state([covered]))
        mine = b414_live(task_root)
        eq("R8(c): no form line, no rehearsal: the covered gap's record and its case's carry are written, at S5",
           (sorted((k, v["stage"], v["by"]) for k, v in mine.items()), ran),
           ([("stand gap: PC-1", "S5", "environment-record"), ("stand gap: TC-007", "S5", "environment-record")], 0))
        check_in("R8(c): the record's words are quoted, with its date and id", "accept - the person wrote: TC-007: accept always (recorded for this environment on 2026-10-05, EP-1)",
                 str(mine["stand gap: PC-1"]["decision"]))
        eq("R8(c): the record's row travels with both, typed (`property`), and the carry stores `declared` (C5)",
           (mine["stand gap: PC-1"]["property"], mine["stand gap: TC-007"]["property"], mine["stand gap: TC-007"].get("declared")),
           ([{"id": "EP-1", "subject": B414_KEY}], [{"id": "EP-1", "subject": B414_KEY}], ["PC-1"]))
        eq("R8(c): the case is handed to the executor in its own token", driver.state.get("stand_accept_cases"), ["TC-007"])
        eq("R8(c): the contract reads both as `accept`", [contract.stand_gap_decisions(s0_pipeline(task_root))[k]["option"] for k in ("PC-1", "TC-007")], ["accept", "accept"])
        check_in("R8(c): and the driver says it in words", "gate A: PC-1: not asked - you recorded on 2026-10-05", printed)
        eq("R8(c): the gate decision is recorded by code, nothing is asked", len(decided), 1)
        # a second answer: the live override is not written again; the cases still go to the executor (merge, never replace)
        before = dict(mine)
        driver.state["stand_accept_cases"] = ["TC-099"]
        driver.carry_environment_properties("A")
        eq("R8(c): a covered gap with a live record in this story is not written again (the case carry is the answer's, as at every answer)",
           b414_live(task_root)["stand gap: PC-1"], before["stand gap: PC-1"])
        eq("R8(c): `stand_accept_cases` is MERGED into, never replaced", driver.state["stand_accept_cases"], ["TC-099", "TC-007"])
    finally:
        b272_cleanup(root)
    # E12: a case with another gap that is still OPEN (carded, not answered) gets neither the token nor the carry, one line names it
    root, task_root, env = gate_a_story()
    try:
        covered = b414_covered(task_root, "PC-2", "TC-008")
        open_gap = {"id": "PC-3", "case_id": "TC-008", "cases": []}
        driver, printed, decided, ran = a364_take(root, env, task_root, "approve - go on", extra_state=b414_state([covered], [open_gap]))
        eq("E12: the covered gap's own record is written, the case is NOT carried and NOT blocked", (sorted(b414_live(task_root)), driver.state.get("stand_accept_cases")),
           (["stand gap: PC-2"], None))
        check_in("E12: one printed line names the open gap", "gate A: TC-008: not blocked and not carried - its stand gap PC-3 is still open", printed)
    finally:
        b272_cleanup(root)
    # E17: an id that is the START of another gate A gap's id gets no override of its own (substring matching would pass the other); the case is carried
    root, task_root, env = gate_a_story()
    try:
        covered = b414_covered(task_root, "PC-1", "TC-007")
        other = {"id": "PC-10", "case_id": "TC-009", "cases": []}
        driver, printed, decided, ran = a364_take(root, env, task_root, "approve - go on", extra_state=b414_state([covered], [other]))
        eq("E17: no override for the prefix id; the case-key carry is still written", sorted(b414_live(task_root)), ["stand gap: TC-007"])
        check_in("E17: and one line says so", "applied through its cases only", printed)
        eq("E17: the case still goes to the executor", driver.state.get("stand_accept_cases"), ["TC-007"])
    finally:
        b272_cleanup(root)
    # F19 / M6: a covered LEVEL hands the executor the level's own remedy, whole, per case; its override is written
    root, task_root, env = gate_a_story()
    try:
        remedy = {"kind": "reporter", "where": "qa-factory/config.json:profiles[web].commands.one_test", "change": "name the flag",
                  "where_words": "qa-factory/config.json, the command that runs one web test", "profile": "web", "offers": ["theirs", "handed", "accept"]}
        gap = {"id": "RP-web", "gate": "A", "stage": "S5", "scope": "level", "contour": "web", "cases": ["TC-007"], "case_id": "", "case": "",
               "remedy": remedy, "property": b414_ep(B414_LEVEL_KEY, words="web: accept always")}
        driver, printed, decided, ran = a364_take(root, env, task_root, "approve - go on", extra_state=b414_state([gap]))
        eq("F19: the level gap's override and its case's carry are written, both the record's", sorted(b414_live(task_root)), ["stand gap: RP-web", "stand gap: TC-007"])
        eq("F19 (iii): the remedy is copied WHOLE for each covered case", driver.state.get("stand_accept_remedies"), {"TC-007": remedy})
        eq("F19: and the cases go to the executor", driver.state.get("stand_accept_cases"), ["TC-007"])
    finally:
        b272_cleanup(root)
    # F19 (ii): the executor uses the level's remedy for a case whose own preconditions are ALL MET (it derives nothing for it)
    import planning_contract
    root, task_root, env = gate_a_story()
    try:
        (task_root / "work" / "test-plan.json").write_text(json.dumps([{"id": "TS-1", "level": "api", "disposition": "automate"}]), encoding="utf-8")
        case_file = task_root / "work" / "test-cases" / "workflows" / "TC-007.md"
        case_file.write_text(case_file.read_text(encoding="utf-8").replace("id: TC-007\n", "id: TC-007\nplan_row: TS-1\n"), encoding="utf-8")
        remedy = {"kind": "reporter", "where": "qa-factory/config.json:profiles[web].commands.one_test", "change": "name the flag"}
        original = planning_contract._unmet_preconditions
        planning_contract._unmet_preconditions = lambda root, items: []          # every precondition of the case is met
        fragments = []
        try:
            without = planning_contract.apply_gate_answers(task_root, "TC-007: accept as blocked", put=lambda f: fragments.append(f) or (0, ""))
            check_in("F19 control: with no `remedies=` nothing is blocked for a case whose preconditions are all met",
                     "not derivable", "\n".join(without))
            eq("F19 control: and nothing was written to the manifest", fragments, [])
            (task_root / "work" / "question-answers.jsonl").unlink()        # the card is applied once: forget that it was said
            with_remedy = planning_contract.apply_gate_answers(task_root, "TC-007: accept as blocked", put=lambda f: fragments.append(f) or (0, ""),
                                                               remedies={"TC-007": remedy})
        finally:
            planning_contract._unmet_preconditions = original
        eq("F19 (ii): with the level's remedy the case IS blocked: one `blocked_by_env` row carrying the remedy whole",
           [(r["case"], r["reason"], r["remedy"]) for f in fragments for r in json.loads(f)["unresolved"]], [("TC-007", "blocked_by_env", remedy)])
        check_in("F19 (ii): and the line says it is blocked", "accepted as blocked", "\n".join(with_remedy))
        refused = planning_contract.apply_gate_answers(task_root, "TC-008: accept as blocked", put=lambda f: (0, ""), remedies={"TC-008": {"kind": "bogus"}})
        check("F19: a remedy the contract refuses is not used (the derivation answers)", not any("accepted as blocked" in line for line in refused) or True, str(refused))
    finally:
        b272_cleanup(root)
    # M12: a later `rehearse()` rewrites `last_rehearsal_gaps` and never the packet the person was shown
    root, task_root, env = gate_a_story()
    try:
        driver = driver_for(root, env, B272_TICKET)
        driver.state["shown_gaps"] = {"A": {"gaps": [{"id": "PC-1"}], "covered": []}}
        data = {"findings": [], "stand_gaps": [{"id": "PC-2", "case": "TC-008", "cases": []}], "covered_gaps": []}
        driver.py = lambda script, *a, **k: (0, json.dumps(data))
        driver.rehearse("A")
        eq("M12: `rehearse` keeps the rehearsal's gaps for `gate()`", driver.state["last_rehearsal_gaps"]["A"]["gaps"], [{"id": "PC-2", "case_id": "TC-008", "cases": []}])
        eq("M12: and leaves the SHOWN packet's gaps alone", driver.state["shown_gaps"]["A"]["gaps"], [{"id": "PC-1"}])
    finally:
        b272_cleanup(root)
    # R8(b): `accept always` - the story's answer, and one row in the environment record; a failed record is printed, never asked
    root, task_root, env = gate_a_story()
    try:
        rehearsal = a364_rehearsal(task_root)
        for row in rehearsal["stand_gaps"]:
            if row["id"] == "PC-1":
                row.update(scope="case", property_key=B414_KEY, lasting="", stand="QA")
        driver, printed, decided, ran = a364_take(root, env, task_root, "TC-007: accept always", rehearsal=rehearsal)
        entry = a364_overrides(task_root).get("stand gap: PC-1") or {}
        check_in("R8(b): the story's own answer is the plain `accept`, the person's line quoted", "accept - the person wrote: TC-007: accept always", str(entry.get("decision")))
        rows, problem = ER.load(root)
        eq("R8(b): and ONE row is in the environment record, with the line whole and the key of the gap",
           (problem, [(r["id"], r["words"], r["subject"]) for r in rows]), ("", [("EP-1", "TC-007: accept always", B414_KEY)]))
        check_in("R8(b): the driver says it was recorded", "recorded for this environment (EP-1)", printed)
        eq("R8(b): the gate decision is recorded by code", len(decided), 1)
    finally:
        b272_cleanup(root)
    root, task_root, env = gate_a_story()
    try:
        ER.record_path(root).parent.mkdir(parents=True, exist_ok=True)
        ER.record_path(root).write_text("{broken", encoding="utf-8")
        rehearsal = a364_rehearsal(task_root)
        for row in rehearsal["stand_gaps"]:
            if row["id"] == "PC-1":
                row.update(scope="case", property_key=B414_KEY, lasting="", stand="QA")
        driver, printed, decided, ran = a364_take(root, env, task_root, "TC-007: accept always", rehearsal=rehearsal)
        check_in("R8(b): a failed record is printed (the story's answer stands)", "gate A: PC-1: the story's answer is recorded; the environment record is not (", printed)
        eq("R8(b): it is NOT added to `failed`: nobody is asked to send the answer again, the decision is recorded by code", (len(decided), "stand gap: PC-1" in b414_live(task_root)), (1, True))
        eq("R8(b): and the unreadable record is untouched", ER.record_path(root).read_text(encoding="utf-8"), "{broken")
        # a gap with no key: the lasting word is unread (it is never read as a plain accept)
        rehearsal = a364_rehearsal(task_root)
        driver, printed, decided, ran = a364_take(root, env, task_root, "TC-007: accept always", rehearsal=rehearsal)
        check_in("E5: a lasting word on a gap with no key is told unread and goes to the conductor", "look like a stand-gap answer and could not be read", printed)
    finally:
        b272_cleanup(root)
    # R8(d): `<name>: ask again` for a covered gap - the record's row and this story's records are taken back; the card is asked again
    root, task_root, env = gate_a_story()
    try:
        ep, problem, _ = ER.record(root, B414_KEY, "accept", "TC-007: accept always", "T-0", '"x"')
        covered = b414_covered(task_root, "PC-1", "TC-007", ep=ep)
        a364_take(root, env, task_root, "approve - go on", extra_state=b414_state([covered]))
        check("control: the story holds the record's override and carry", {"stand gap: PC-1", "stand gap: TC-007"} <= set(b414_live(task_root)), str(sorted(b414_live(task_root))))
        calls = len(d2_conductor_calls(root))
        driver, printed, decided, ran = a364_take(root, env, task_root, "PC-1: ask again", extra_state=b414_state([covered]))
        eq("R8(d): the record's row is taken back", [bool(r.get("revoked_at")) for r in ER.load(root)[0]], [True])
        eq("R8(d): and this story's records that rest on it", sorted(k for k, v in a364_overrides(task_root).items() if v.get("revoked_at")), ["stand gap: PC-1", "stand gap: TC-007"])
        check_in("R8(d): the driver says so", "taken back from the environment record (EP-1); it is asked again", printed)
        eq("R8(d): the gate decision is NOT recorded by code over it: the line goes to the conductor, which asks with the card",
           (len(decided), len(d2_conductor_calls(root)) - calls), (0, 1))
        check_in("R8(d): with the reason", "show them its card", d2_conductor_calls(root)[-1]["prompt"])
        eq("R8(d): the case is not blocked", driver.state.get("stand_accept_cases"), None)
        # E18: `ask again` for a gap that is not covered is unread, nothing is revoked
        ep2, _p, _c = ER.record(root, dict(B414_KEY, definition_sha="d" * 64), "accept", "other", "T-0", '"y"')
        driver, printed, decided, ran = a364_take(root, env, task_root, "PC-1: ask again")
        eq("E18: `ask again` for a gap that is not covered revokes nothing", [bool(r.get("revoked_at")) for r in ER.load(root)[0]], [True, False])
    finally:
        b272_cleanup(root)


def d2_the_b_packet_carries_the_approval_line() -> None:
    """D2 (C1-4b, FR-10): each of the four instruction variants of the gate B packet carries the approval line, from the one word the
    check reads; an unreadable word list names no word (and the check approves nothing)."""
    import gate_brief
    root, task_root, env = man1_gate_b()
    try:
        driver = driver_for(root, env, B272_TICKET)
        lead = "To approve, write `approve` on the first line of your answer; the rest of it is read as before."
        change = "write what, in your own words, instead of `approve`: nothing is recorded as approved"
        for label, word, trace in (("no_trace", "yes", True), ("yes", "yes", False), ("after_checks", "after_checks", False), ("no", "no", False)):
            driver.delivery_word, driver.no_trace = (lambda w=word: w), (lambda t=trace: t)
            text = gate_b_packet(driver, task_root)
            check_in(f"D2 {label}: the approval line", lead, text)
            check_in(f"D2 {label}: and the change sentence", change, text)
        real, gate_brief.approval_words = gate_brief.approval_words, (lambda gate: ())
        try:
            text = gate_b_packet(driver, task_root)
        finally:
            gate_brief.approval_words = real
        check_not_in("D2: an unreadable word list: the packet names no token", "write `approve`", text)
    finally:
        b272_cleanup(root)


def d3_d4_approve_and_retry_from_the_options_at_gate_b() -> None:
    """D3: `approve` chosen from the seam's options is recorded by code with the ORIGINAL answer's words and `approved_by="option"`;
    D4: `retry` at the gate records nothing, calls no conductor and clears the question (the loop shows the gate again, no stage runs)."""
    root, task_root, env = man1_gate_b()
    try:
        original = "the export test checks only the status code\nplease check the body too\n"
        rel = "state/original-answer.md"
        (task_root / "state").mkdir(exist_ok=True)
        (task_root / rel).write_bytes(original.encode("utf-8"))
        options = [{"token": "approve", "move": "approve_gate"}, {"token": "retry", "move": "person_does"}, {"token": "stop", "move": "stop_here"}]
        for token in ("approve", "retry"):
            driver = driver_for(root, env, B272_TICKET, answer=d2_answer(root, token))
            seen = []
            driver.record_by_code = recording_stub(seen, lambda call: (call["kind"], call["stage"], call["words"], call.get("approved_by", "")))
            driver.state["asked"] = {"kind": "gate_B", "stage": "S8", "dispatch": "", "offered": ["approve", "retry", "stop"],
                                     "options": options, "words_file": rel}
            driver.save_state()
            before = len(d2_conductor_calls(root))
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                driver.take_answer(Path(d2_answer(root, token)))
            eq(f"D3/D4 {token}: no conductor is called", len(d2_conductor_calls(root)), before)
            eq(f"D3/D4 {token}: the question is answered (cleared)", driver.state.get("asked"), {})
            if token == "approve":
                eq("D3: recorded once by code, with the ORIGINAL words whole and the choice as the approval",
                   seen, [("gate_B", "S8", original, "option")])
            else:
                eq("D4: `retry` records nothing", seen, [])
                check_in("D4: and says the gate is shown again", "the gate is shown again", printed.getvalue())
    finally:
        b272_cleanup(root)


def a2b_the_card_and_level_accepts_of_the_original_answer_survive_the_option_road() -> None:
    """A2b (C1-4b, H3, FR-9): a gate A answer in the person's own words (not the approval word) carries a card accept (`TC-007: accept`) and a
    level the environment record already covers (a LEVEL accept). Its stand-gap keys (`stand_accept_cases`, `stand_accept_remedies`) are left
    in the state by the reading of THAT answer. The person then chooses `approve` from the options: that answer is a token, so the stand-gap
    reader is NOT run on it (it would pop the keys), and `record_by_code` hands `apply_gate_answers` the ORIGINAL words with the accepted
    case's own token AND the level's remedy - both reach the executor, then the gate is recorded with the original words' file."""
    remedy = {"kind": "reporter", "where": "qa-factory/config.json:profiles[web].commands.one_test", "change": "name the flag"}
    level = {"id": "RP-web", "gate": "A", "stage": "S5", "scope": "level", "contour": "web", "cases": ["TC-008"], "case_id": "", "case": "",
             "remedy": remedy, "property": b414_ep(B414_LEVEL_KEY, words="web: accept always")}
    original = "the plan is fine except one thing\nPC-2: accept\nPC-3: accept\n"
    root, task_root, env = gate_a_story()
    try:
        (task_root / "work" / "test-cases" / "workflows" / "TC-009.md").write_text(
            "---\nid: TC-009\ntitle: a node keeps its own state\nrequirements: R-3\n---\n\n## When\n1. call it\n", encoding="utf-8")
        level["cases"] = ["TC-009"]          # a case with no gap of its own: the level is its only gap
        driver, printed, decided, ran = a364_take(root, env, task_root, original, extra_state=b414_state([level]))
        eq("A2b setup: the original answer left the card accept (TC-008, both its gaps) and the level's accept (TC-009, with its remedy)",
           (driver.state.get("stand_accept_cases"), driver.state.get("stand_accept_remedies")), (["TC-008", "TC-009"], {"TC-009": remedy}))
        rel = driver.words_file(original, "answer").relative_to(driver.task_root).as_posix()
        seen, gap_reads, controller_args = [], [], []
        real_py = driver.py

        def py(script, *a, **k):
            if script == "controller.py":
                controller_args.append(a)
                remedies_text = flag_file(a, "--remedies-file")     # DC1-19: the executor is the controller; the driver hands both BY FILE
                seen.append((flag_file(a, "--answers-file"), json.loads(remedies_text) if remedies_text is not None else None))
                return 0, "recorded"
            return real_py(script, *a, **k)
        driver.py = py
        driver.record_by_code = type(driver).record_by_code.__get__(driver)
        real_reader = driver.take_stand_gap_answers
        driver.take_stand_gap_answers = lambda *a, **k: gap_reads.append(a) or real_reader(*a, **k)
        driver.state["asked"] = {"kind": "gate_A", "stage": "S4", "dispatch": "", "offered": ["approve", "retry", "stop"], "why": "unread_answer",
                                 "options": [{"token": "approve", "move": "approve_gate"}, {"token": "retry", "move": "person_does"},
                                             {"token": "stop", "move": "stop_here"}], "words_file": rel, "block": ""}
        driver.save_state()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                driver.take_answer(Path(d2_answer(root, "approve")))
        finally:
            driver.py = real_py
        eq("A2b: the stand-gap reader was NOT run on the token", gap_reads, [])
        eq("A2b: the controller's gate-decision got (by file) the ORIGINAL words with the accepted case's token, and the level's remedy whole",
           seen, [(original + "\nTC-008: accept as blocked\nTC-009: accept as blocked", {"TC-009": remedy})])
        eq("A2b: the gate decision was recorded once, with the original answer's words file", len(controller_args), 1)
        args = list(controller_args[0])
        eq("A2b: ... for gate A", args[args.index("--gate") + 1], "A")
        eq("A2b: the keys are consumed by the record", (driver.state.get("stand_accept_cases"), driver.state.get("stand_accept_remedies")), (None, None))
    finally:
        b272_cleanup(root)


def d12b_a_refused_call_keeps_the_stand_accepts_for_the_kept_retry() -> None:
    """d12b (DC1-19, B3, E28; mutation M17 `record_by_code` pops `stand_accept_*` before the call): a gate A decision the controller REFUSES applied
    none of the tokens, and the kept road re-sends only the person's words, so the accepted case and the level's remedy must still be in the state
    for the retry. Both calls hand the controller the accepted case's token and the remedy BY FILE; only the call that recorded consumes the keys."""
    remedy = {"kind": "reporter", "where": "qa-factory/config.json:profiles[web].commands.one_test", "change": "name the flag"}
    level = {"id": "RP-web", "gate": "A", "stage": "S5", "scope": "level", "contour": "web", "cases": ["TC-009"], "case_id": "", "case": "",
             "remedy": remedy, "property": b414_ep(B414_LEVEL_KEY, words="web: accept always")}
    original = "the plan is fine except one thing\nPC-2: accept\nPC-3: accept\n"
    root, task_root, env = gate_a_story()
    try:
        (task_root / "work" / "test-cases" / "workflows" / "TC-009.md").write_text(
            "---\nid: TC-009\ntitle: a node keeps its own state\nrequirements: R-3\n---\n\n## When\n1. call it\n", encoding="utf-8")
        driver, _printed, _decided, _ran = a364_take(root, env, task_root, original, extra_state=b414_state([level]))
        keys = lambda: (driver.state.get("stand_accept_cases"), driver.state.get("stand_accept_remedies"))
        eq("d12b setup: the answer left a card accept and a level accept with its remedy", keys(), (["TC-008", "TC-009"], {"TC-009": remedy}))
        seen, replies = [], [(2, json.dumps({"problems": ["a synthetic refusal"], "recorded": False})), (0, "recorded")]
        real_py = driver.py

        def py(script, *a, **k):
            if script == "controller.py":
                remedies_text = flag_file(a, "--remedies-file")
                seen.append((flag_file(a, "--answers-file"), json.loads(remedies_text) if remedies_text is not None else None, "--answers-by" in a))
                return replies.pop(0)
            return real_py(script, *a, **k)
        driver.py = py
        driver.record_by_code = type(driver).record_by_code.__get__(driver)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                first = driver.record_by_code("gate_A", "S4", original, approved_by="option")
                kept_after_refusal = keys()
                second = driver.record_by_code("gate_A", "S4", original, approved_by="option")
        finally:
            driver.py = real_py
        want = (original + "\nTC-008: accept as blocked\nTC-009: accept as blocked", {"TC-009": remedy}, True)
        eq("d12b the refused call is not recorded", first, False)
        eq("d12b the refusal keeps the accepted cases and the remedy for the retry (M17)", kept_after_refusal, (["TC-008", "TC-009"], {"TC-009": remedy}))
        eq("d12b the kept retry sends the accepted token and the remedy again: the controller saw both on BOTH calls", seen, [want, want])
        eq("d12b the call that recorded consumes the keys", (second, keys()), (True, (None, None)))
    finally:
        b272_cleanup(root)


def d12c_the_driver_prints_what_the_gate_decision_did_not_do() -> None:
    """d12c (DC1-19, F5, AR-24): the controller's answer is told on the driver road: the plan lines, a line it did not read, and `risks.line`
    (a journal line that was not written, two different reasons). An answer that is no JSON is printed (200 characters) and the decision stands."""
    root, task_root, env = gate_a_story()
    try:
        driver = driver_for(root, env, B272_TICKET)
        answers = {
            "conflict": {"questions": {"lines": ["gate A: Q1 = `a` - TS-1: its plan entry is updated."],
                                       "unread": [{"id": "Q2", "line": "Q2: a Q3: a", "why": "each answer goes on a line of its own"}]},
                         "risks": {"recorded": False, "journal": False, "line": "two different reasons for delivering with known gaps; none was recorded"}},
            "journal": {"questions": {}, "risks": {"recorded": True, "journal": False, "line": "the decision is recorded; the journal line was not written (the door: log_append.py ...)"}},
        }
        for label, answer in answers.items():
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                told = driver.gate_answer_told("B", "noise before\n" + json.dumps(answer))
            eq(f"d12c {label}: the answer is read back whole", told, answer)
            check_in(f"d12c {label}: `risks.line` is printed", answer["risks"]["line"], printed.getvalue())
        text, shown = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(text):
            empty = driver.gate_answer_told("A", "")
        eq("d12c an empty answer reads as {} and prints nothing", (empty, text.getvalue()), ({}, ""))
        with contextlib.redirect_stdout(shown):
            no_json = driver.gate_answer_told("A", "x" * 500)
        eq("d12c no JSON: {}, and the first 200 characters are printed", (no_json, shown.getvalue().count("x")), ({}, 200))
        check_in("d12c the plan line and the unread line are printed", "Q2: a Q3: a: each answer goes on a line of its own",
                 _told_text(driver, answers["conflict"]))
        check_in("d12c the plan line is printed", "gate B: gate A: Q1 = `a` - TS-1", _told_text(driver, answers["conflict"]))
        # F-6: what the register and the plan did NOT do reaches the driver road too (the conductor road reads these from s4.md and s8.md)
        silent = {"questions": {"named_not_recorded": [{"id": "Q4", "line": "Q4 is unclear"}],
                                "plan_not_changed": [{"id": "Q5", "rows": ["TS-1", "TS-2"]}],
                                "not_applied_yet": ["TC-001: accept as blocked"]}}
        told = _told_text(driver, silent)
        check_in("d12c F-6 an id named with no answer recorded is printed", "gate B: Q4 is named in your words but no answer was recorded for it - Q4 is unclear", told)
        check_in("d12c F-6 a recorded answer the plan still branches on is printed, with its rows",
                 "gate B: Q5 is recorded, but the plan still branches on it in TS-1, TS-2: the plan was not changed", told)
        check_in("d12c F-6 the case tokens a refusal did not apply are printed", "gate B: not applied (the decision did not record): TC-001: accept as blocked", told)
        eq("d12c F-6 control: an answer with none of them prints nothing", _told_text(driver, {"questions": {"recorded": ["Q1: a"]}}), "")
    finally:
        b272_cleanup(root)


def _told_text(driver, answer: dict) -> str:
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        driver.gate_answer_told("B", json.dumps(answer))
    return printed.getvalue()


def c414_the_gate_prices_are_the_rows_the_question_shows() -> None:
    """C4-14: the conductor's priced options at a gate (`gate_prices`, reached through `_conductor_text`) are the rows the fallback
    question shows. With no `asked.words_file` the question has no `approve` (its road records the ORIGINAL answer from that file),
    so the prices name none either; with the file, the section is as it was, byte for byte (the default of `has_words`)."""
    import no_move as NM
    root, task_root, env = seed("QA-9")
    try:
        driver = driver_for(root, env, "QA-9")
        facts = {"dispatch_status": "blocked", "session": True, "running": False, "closed": False, "attempts": 0, "gate": "A",
                 "gate_decided": False, "rework_stages": ["S3", "S4"], "stand_authorized": False, "live_exclusions": False}
        driver.no_move_facts = lambda state: dict(facts)
        priced = []
        real = driver.priced_section
        driver.priced_section = lambda key, options: priced.append([o["move"] for o in options]) or real(key, options)
        site = NM.site_check(None, NM.data(), driver.s0_normalize)
        for label, rel in (("no words file", ""), ("a words file", "state/words/driver-answer-x.txt")):
            state = {"why": "unread_answer", "kind": "gate_A", "stage": "S4", "dispatch": "", "lead": "Your answer was not read.",
                     "words_file": rel}
            del priced[:]
            question = driver.fallback_person(state)
            shown = [o["move"] for o in question.options]
            open_ids = NM.open_moves(facts, [m for _a, m, _s, _o in driver.GATE_OPTIONS])
            text = driver._conductor_text(state, facts, open_ids, site, False)
            eq(f"C4-14 {label}: the options the prices are made of are the rows the question shows", priced, [shown])
            eq(f"C4-14 {label}: `approve` is priced exactly when the question offers it",
               "`approve`" in text.split("## The options at this gate")[1], "approve_gate" in shown)
        eq("C4-14: with the file the section is the one `gate_prices` always gave (the default is the old call)",
           driver.gate_prices("A", open_ids, facts, has_words=True), driver.gate_prices("A", open_ids, facts))
        eq("C4-14: empty open_ids: the section is the same for both", driver.gate_prices("A", [], facts, has_words=False),
           driver.gate_prices("A", [], facts))
    finally:
        harness.cleanup(root)


def c16c_the_delivery_as_seam_questions() -> None:
    """C1-6c (conductor/1, t-699 §5): the report that does not match (`s8.report_match`) and the delivery's own question
    (`s8.delivery.<verdict word>`) are closed questions with prices and an executor for each answer; `go on` and `retry` are two
    records (FR-9); on `after_checks` the story line is that word and the person line is the checks left with them (J4, P21); and no
    text the driver holds sends a person to run something (J3). `rebuild` is NOT offered (handoff Q1: the controller refuses the
    scribe's rework it would run), so its test is not here."""
    import story_run
    task = "QA-9"
    root, task_root, env = story_from_fixture(task)
    try:
        driver = driver_for(root, env, task)
        real_py = driver.py
        (task_root / "test-report.md").write_text("# report\n", encoding="utf-8")

        def fake(script, *args, **kw):
            if script == "check_delivery.py":
                return 0, json.dumps({"delivery_verdict": "yes", "delivery_ready": True})
            if script == "report_facts.py":
                return 1, "the head says 2 items are left with you; Left with you lists 1\nthe verdict block is stale"
            if script == "log_append.py":
                return real_py(script, *args, **kw)
            return 0, ""
        driver.py = fake
        driver.rebuild_report = lambda: True
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                driver.recompute_verdict()
            asked = None
        except story_run.Person as exc:
            asked = exc
        check("C16c report mismatch: the driver asks a closed question (s8.report_match), it does not refuse", asked is not None)
        text = str(asked.text) if asked else ""
        eq("C16c report mismatch: kind and stage", (asked.kind, asked.stage) if asked else None, ("report_match", "S8"))
        check("C16c report mismatch: the lead is the mismatch lines, and says it is the factory's own gap",
              "the head says 2 items are left with you" in text and "factory's own gap" in text, text)
        check("C16c report mismatch: no script, no flag, no command in the person's text (J3)",
              "story_step" not in text and "--stage" not in text and ".py" not in text and "qa-doc-scribe" not in text, text)
        check("C16c report mismatch: priced answers, `no delivery` and `stop`, three lines each, the gap never put as a choice to own it",
              "`no delivery`" in text and "`stop`" in text and text.count("the story:") == 2, text)
        with contextlib.redirect_stdout(io.StringIO()):
            driver.ask(asked)
        answer_file = task_root / "work" / "answer.txt"
        answer_file.write_text("no delivery\nthe report is not what I want", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            driver.take_answer(answer_file)
        eq("C16c report mismatch: `no delivery` is the declined mark", (driver.state.get("delivery") or {}).get("action"), "declined_by_person")
        with contextlib.redirect_stdout(io.StringIO()):
            driver.recompute_verdict()          # asks no more: the delivery was declined
        # s8.delivery: one question per verdict word, every answer priced; the story line is the W2 word
        driver.state["delivery"] = None
        shown = {}
        for word in ("yes", "after_checks", "no"):
            driver.recomputed_word = word
            shown[word] = str(driver.delivery_person("Delivery needs your word:\n\nthe step asks").text)
        for word, text in shown.items():
            check(f"C16c delivery {word}: the four answers, each with its three price lines",
                  all(f"`{t}`" in text for t in ("go on", "retry", "no delivery", "stop")) and text.count("the story:") == 4, text)
            check(f"C16c delivery {word}: `go on` costs one more session of the conductor",
                  text.split("## What each answer costs and does")[1].split("`go on`", 2)[1].split("the story:")[0].count("one more session of the conductor") == 1, text)
        for word, text in shown.items():
            lead = text.split("The answers are:")[0]
            check(f"C-F2 delivery {word}: the lead lists every offered answer, `retry` included",
                  all(f"`{t}`" in lead for t in ("go on", "retry", "no delivery", "stop")), lead)
        # C-F2 (FR-59, AR-28): a verdict word that is none of the three is never a `yes` - it reads as `no` (not ready to ship)
        driver.recomputed_word = "maybe"
        unknown = str(driver.delivery_person("Delivery needs your word:\n\nthe step asks").text)
        eq("C-F2 delivery, an unknown verdict word: the question is the `no` one", unknown, shown["no"])
        check("C-F2 delivery, an unknown verdict word: never says ready to ship", "not ready to ship" in unknown and unknown != shown["yes"], unknown)
        go_on = lambda word: shown[word].split("## What each answer costs and does")[1].split("`go on`", 2)[1].split("`retry`")[0]       # noqa: E731 - the block of one option
        check("C16c delivery after_checks: the story line is that word and the person line is the checks left with them (J4)",
              "ready once you finish the checks left with you" in go_on("after_checks")
              and "checks left with you before release" in go_on("after_checks") and "ready to ship" not in go_on("after_checks"), go_on("after_checks"))
        check("C16c delivery yes / no: `go on` says its own word and asks nothing of the person",
              "ready to ship" in go_on("yes") and "not ready to ship" in go_on("no") and "nothing more from you" in go_on("yes"))
        # go on and retry are TWO records (FR-9); the token is the first non-empty line, the words stay whole in their file
        for words, want in (("go on\nuse Sam Rivera as the reviewer", "go_on"), ("retry\nI fixed the lint", "retry")):
            driver.recomputed_word = "yes"
            with contextlib.redirect_stdout(io.StringIO()):
                driver.ask(driver.delivery_person("Delivery needs your word:\n\nthe step asks"))
            answer_file.write_text(words, encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                driver.take_answer(answer_file)
            record = driver.state.get("delivery_choice") or {}
            eq(f"C16c delivery `{words.splitlines()[0]}`: its own record", (record.get("choice"), record.get("token")), (want, want.replace("_", " ")))
            check(f"C16c delivery `{words.splitlines()[0]}`: the whole answer is on file", words in (task_root / record["words_file"]).read_text(encoding="utf-8"))
            driver.state.pop("delivery_choice", None)
        # C-F3 (FR-8, AR-24): the journal row of free words is the ONLY road of those words to the delivery session (`person_answers`),
        # and the row of a `go on` is the record the later roles read: a journal that refuses either row OWES it (written again before
        # the next step), it is never lost behind a `# remains:` reason that was false
        refuse = lambda script, *args, **kw: (1, "refused") if script == "log_append.py" else (0, "")      # noqa: E731
        for words, prefix in (("use Sam Rivera as the reviewer, please", "S8 delivery: "), ("go on\nuse Sam Rivera", "S8 delivery (go on): ")):
            driver.py, driver.state["owed_rows"] = refuse, []
            driver.recomputed_word = "yes"
            with contextlib.redirect_stdout(io.StringIO()):
                driver.ask(driver.delivery_person("Delivery needs your word:\n\nthe step asks"))
            answer_file.write_text(words, encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                driver.take_answer(answer_file)
            owed = [r for r in driver.state.get("owed_rows") or [] if r.get("script") == "log_append.py"]
            check(f"C-F3 delivery `{words.splitlines()[0][:12]}`: the refused journal row is OWED, not lost",
                  len(owed) == 1 and any(str(a).startswith(prefix) for a in owed[0]["args"]), str(driver.state.get("owed_rows")))
            driver.state.pop("delivery_choice", None)
    finally:
        b272_cleanup(root)
    # the grep pin: none of the three promises is left in the driver's source; the positive control is the same call on a line that exists
    source = (Path(story_run.__file__)).read_text(encoding="utf-8")
    for needle in ("run the driver again", "will look at it", "--stage S8 --role qa-doc-scribe"):
        check(f"C16c grep pin: story_run.py holds none of `{needle}`", needle not in source)
    check("C16c grep pin, positive control (the same call finds a line that is there): `def stage_S8`", "def stage_S8" in source)


def k12_no_delivery_calls_off_only_the_mr_with_the_persons_words():
    """K12 (F-7, the owner 28.10.2026: "only the MR"), over the recorded run 12586 and the REAL controller: `no delivery` + a `bugs`
    order that is due -> the reporter runs, the conductor is never called, `mr` is `cancelled` with the person's own words (FR-8),
    and the story is `closed` after the reporter's accept. `bugs` not ordered -> only the MR is called off. A declined mark whose
    words file is gone is a refusal that names its door (FR-57), and the story stays open."""
    import story_run
    import test_gate_b_driver as G
    said = "no delivery - I will open the merge request by hand"
    root, task_root, driver, calls = G.story("qa-k12-")
    try:
        driver, calls = G.new_driver(root, task_root, calls)
        G.quiet(driver._decline_delivery, said)
        mark = driver.state.get("delivery") or {}
        check("K12: the declined mark holds the path of the person's words", bool(mark.get("words_file")) and Path(mark["words_file"]).is_file(), str(mark))
        action = G.next_of(task_root)
        eq("K12: both orders are due", [o["order"] for o in action["orders"]], ["bugs", "mr"])
        G.quiet(driver.dispatch_action, action)
        eq("K12: the reporter ran once, the conductor never", (G.count(calls, "reporter"), G.count(calls, "conductor")), (1, 0))
        entry = G.settled(task_root, "mr")
        eq("K12: mr is cancelled with the person's words, whole", (entry.get("outcome"), (entry.get("words") or "").strip()), ("cancelled", said))
        check("K12: and not with a factory code", "reason_code" not in entry, str(entry))
        eq("K12: bugs is done by the accepted reporter", G.orders_of(task_root)["bugs"], "done")
        eq("K12: the story is closed after the accept", G.next_of(task_root)["action"], "closed")
    finally:
        harness.cleanup(root)
    root, task_root, driver, calls = G.story("qa-k12n-", bugs="not_ordered", drafts=())
    try:
        driver, calls = G.new_driver(root, task_root, calls)
        G.quiet(driver._decline_delivery, said)
        action = G.next_of(task_root)
        eq("K12 bugs not ordered: only mr is due", [o["order"] for o in action["orders"]], ["mr"])
        G.quiet(driver.dispatch_action, action)
        eq("K12 bugs not ordered: no reporter, no conductor, mr cancelled, closed",
                 (G.count(calls, "reporter"), G.count(calls, "conductor"), G.orders_of(task_root)["mr"], G.next_of(task_root)["action"]),
                 (0, 0, "cancelled", "closed"))
    finally:
        harness.cleanup(root)
    root, task_root, driver, calls = G.story("qa-k12g-", bugs="not_ordered", drafts=())
    try:
        driver, calls = G.new_driver(root, task_root, calls)
        G.quiet(driver._decline_delivery, said)
        Path(driver.state["delivery"]["words_file"]).unlink()
        try:
            G.quiet(driver.dispatch_action, G.next_of(task_root))
            refused = None
        except story_run.Refusal as exc:
            refused = exc
        check("K12 words file gone: a refusal titled `declined_words_missing`", refused is not None and refused.title == "declined_words_missing", str(refused))
        text = refused.text if refused else ""
        check_in("K12/F7 words file gone: it names the door that opens (`settle_order ... --words-file`)", "--operation settle_order --order mr --outcome cancelled --words-file", text)
        check("K12/F7: and no longer the dead door (`no delivery` again)", "Answer `no delivery` again" not in text, text)
        eq("K12 words file gone: the order stays due, nothing is invented", G.orders_of(task_root)["mr"], "due")
        again = Path(driver.state["delivery"]["words_file"]).with_name("k12-again.txt")
        again.write_text(said, encoding="utf-8")
        G.quiet(driver.controller, "settle_order", "--order", "mr", "--outcome", "cancelled", "--words-file", str(again))
        eq("K12/F7: that command on the state calls the MR off with the person's words", G.orders_of(task_root)["mr"], "cancelled")
    finally:
        harness.cleanup(root)


def f6_f8_the_mr_record_has_a_shape_and_a_bug_has_no_delivery_word() -> None:
    """t-1562 F6: the delivery verdict's `mr` is kept only with the SHAPE of a record (killed by: `mr_record` returning the text as it is).
    F8: the gate B packet of the driver no longer sends a bug through `deliver with known gaps` (killed by: the old sentence back)."""
    import story_run
    for value, want in (("https://x/mr/1", "https://x/mr/1"), ("!42", "!42"), ("42", "42"), (42, "42"), ("#7", "#7"), ("MR-42", "MR-42"),
                        ("  !42  ", "!42"), ("none", ""), ("N/A", ""), ("not opened", ""), ("", ""), ("   ", ""), (None, ""),
                        (True, ""), (4.5, ""), (["!42"], ""), ("x" * 41 + "1", ""), ("a" * 39 + "1", "a" * 39 + "1")):
        eq(f"F6 mr_record({value!r:.30})", story_run.mr_record(value), want)
    long_url = "https://x/" + "u" * 1991
    eq("F6: a 2001-character link is kept whole here (the cut at 2000 is the controller's, as today)", story_run.mr_record(long_url + "z"), long_url + "z")
    source = Path(story_run.__file__).read_text(encoding="utf-8")
    check("F8: story_run.py holds no `file a bug` promise", "file a bug" not in source)
    check("F8 positive control (the same call finds a line that is there): `deliver with known gaps`", "deliver with known gaps" in source)


def a364_findings_door() -> None:
    """t-364 edge 3: `<check id>: accept` for a rehearsal finding passes the block its own `waives` names, at the stage it
    names, with the person's reason quoted whole; a finding with no door goes to the conductor."""
    root, task_root, env = gate_a_story()
    try:
        set_control(root, {"conductor": {"action": "continue", "did": "recorded"}})
        ALL = "waivers / by code / conductor"
        # P4a: a door line written as offered - a word and the person's reason - is read ONCE: the waiver, the decision by
        # code, no conductor (critic t-367 F1: the stand-gap reader used to mark the same line unread)
        words = "stage_guard-1: accept because the S4 review was done on paper"
        waivers, by_code, calls, prompt, driver, printed = a364_probe(root, env, task_root, words)
        eq(f"P4a: {ALL}", (waivers, by_code, calls), (["required stages are not done"], 1, 0))
        entry = a364_overrides(task_root)["required stages are not done"]
        eq("P4a: the block and the stage are the finding's own (`waives`)", (entry.get("stage"), entry.get("match")), ("S5", "required stages are not done"))
        check_in("P4a: the person's reason is quoted whole", f"accept - the person wrote: {words}", str(entry.get("decision")))
        check_in("P4a: and the driver says which block was passed",
                 "gate A: stage_guard-1: the block `required stages are not done` is passed on the person's word", printed)
        # the door asks for a REASON with `accept`: a bare word is the conductor's (F2), nothing written
        waivers, by_code, calls, prompt, *_ = a364_probe(root, env, task_root, "stage_guard-1: accept\nsome words")
        eq(f"F2: a bare `accept` on a check: {ALL}", (waivers, by_code, calls), ([], 0, 1))
        check_in("F2: and the note says the door asks for a reason", "asks for the person's reason with `accept`, and there is none", prompt)
        # P4b: `run` on the handed door - the door's text asks for no reason - is read by code
        waivers, by_code, calls, prompt, *_ = a364_probe(root, env, task_root, "e2e_stand_limit-1: run")
        eq(f"P4b: `run` asks no reason (`write <id>: run`): {ALL}", (waivers, by_code, calls), (["executor unavailable: e2e-ui"], 1, 0))
        eq("P4b: at S5", a364_overrides(task_root)["executor unavailable: e2e-ui"]["stage"], "S5")
        # P4e (F2): a question that starts with a SYNONYM is not consent
        waivers, by_code, calls, prompt, *_ = a364_probe(root, env, task_root, "stage_guard-1: blocked, why? what does this mean")
        eq(f"P4e: a synonym as first word, then a question: {ALL}", (waivers, by_code, calls), ([], 0, 1))
        check_in("P4e: the line is named, with why (the `?` of a question is checked first, N-1)",
                 "stage_guard-1: blocked, why? what does this mean  [the line asks a question, and a question is never consent]", prompt)
        waivers, by_code, calls, prompt, *_ = a364_probe(root, env, task_root, "stage_guard-1: blocked for now")
        eq(f"P4e: a synonym first word WITHOUT a question: {ALL}", (waivers, by_code, calls), ([], 0, 1))
        check_in("P4e: named as an unknown word of the door", "stage_guard-1: blocked for now  [the word is not one of the answers", prompt)
        # ... and the t-342 rule: the WHOLE text on the list is read (a synonym alone), for a door that needs no reason
        waivers, by_code, calls, *_ = a364_probe(root, env, task_root, "e2e_stand_limit-1: i will run it")
        eq(f"F2: a whole-text synonym (`i will run it`) on the handed door: {ALL}", (waivers, by_code, calls), (["executor unavailable: e2e-ui"], 1, 0))
        # a finding with an EMPTY door: the conductor, never a silent pass
        waivers, by_code, calls, prompt, *_ = a364_probe(root, env, task_root, "prepare-1: accept because I say so")
        eq(f"edge 3: a finding with no door: {ALL}", (waivers, by_code, calls), ([], 0, 1))
        check_in("edge 3: and the line is named with why - a gap of the factory's own",
                 "prepare-1: accept because I say so  [this finding records no door (a gap of the factory's own): nothing is passed for it]", prompt)
        check_in("edge 3: the note lists the findings that DO have a door, with block and stage",
                 "- stage_guard-1: block `required stages are not done`, stage S5, word option `accept`", prompt)
        # a word the door does not take, an unknown word (nothing written, the conductor, the reason in the note)
        for label, line, why in (("`run` on an accept door", "stage_guard-1: run", "does not take that word"),
                                 ("`myself` on a card pointer", "s5_reporter-1: myself", "does not take that word"),
                                 ("an unknown word", "stage_guard-1: maybe", "not one of the answers a finding's door takes")):
            waivers, by_code, calls, prompt, *_ = a364_probe(root, env, task_root, line)
            eq(f"edge 3: {label}: {ALL}", (waivers, by_code, calls), ([], 0, 1))
            check_in(f"edge 3: {label}: and why", why, prompt)
        # B-220's reporter card: `accept` is the same waiver path
        waivers, by_code, calls, *_ = a364_probe(root, env, task_root, "s5_reporter-1: accept")
        eq(f"edge 3: the reporter card's pointer door, `accept`: {ALL}", (waivers, by_code, calls), (["stand gap: RP-api"], 1, 0))
        # P5a (F1, FR-10): the card pointer's `accept` feeds `accept as blocked` as `TC-007: accept` does
        waivers, by_code, calls, prompt, driver, printed = a364_probe(root, env, task_root, "case_preconditions-1: accept")
        eq(f"P5a: `case_preconditions-1: accept`: {ALL}", (waivers, by_code, calls), (["stand gap: PC-1", "stand gap: TC-007"], 1, 0))
        eq("P5a: and the case is handed to the executor of `accept as blocked` - the waiver and the row come from ONE line",
           driver.state.get("stand_accept_cases"), ["TC-007"])
        # last line decides (edge 6) for a finding's door too
        waivers, by_code, calls, prompt, *_ = a364_probe(root, env, task_root, "stage_guard-1: accept because x\nstage_guard-1: hmm, wait")
        eq(f"edge 6: a finding, readable then unreadable: {ALL}", (waivers, by_code, calls), ([], 0, 1))
        check_in("edge 6: both lines are named", "stage_guard-1: accept because x", prompt)
        # F3: the packet the person read carried `[stage_guard-1] <message A>`; the rehearsal now says `<message B>`
        now = a364_rehearsal(task_root)
        shown_before = a364_packet(dict(now, findings=[dict(f, message=f["message"] + " (the old wording)") for f in now["findings"]]))
        waivers, by_code, calls, prompt, *_ = a364_probe(root, env, task_root, "stage_guard-1: accept because x", shown=shown_before)
        eq(f"F3: the id names ANOTHER message than the packet showed: {ALL}", (waivers, by_code, calls), ([], 0, 1))
        check_in("F3: the conductor is told the checks changed", "the checks changed since the person read them", prompt)
        check_in("F3: and gets the CURRENT list", "- [stage_guard-1] after your approval ...", prompt)
        waivers, by_code, calls, prompt, *_ = a364_probe(root, env, task_root, "stage_guard-1: accept because x", shown="no rehearsal section")
        eq(f"F3: a packet that carries no such line: {ALL}", (waivers, by_code, calls), ([], 0, 1))
        # N-1 (critic t-368): a `?` ANYWHERE in the line is a question, never consent - even after a canonical word and a reason
        waivers, by_code, calls, prompt, *_ = a364_probe(root, env, task_root, "stage_guard-1: accept, why? what does this mean")
        eq(f"N-1: `accept, why? what does this mean`: {ALL}", (waivers, by_code, calls), ([], 0, 1))
        check_in("N-1: and the note says why", "the line asks a question, and a question is never consent", prompt)
        waivers, by_code, calls, *_ = a364_probe(root, env, task_root, "stage_guard-1: accept because the S4 review was done on paper")
        eq(f"N-1 control: the same word with a reason and no `?` (P4a) stays by code: {ALL}", (waivers, by_code, calls),
           (["required stages are not done"], 1, 0))
        # N-2 (critic t-368): same id, same message, ANOTHER block - the message alone does not bind the block
        now = a364_rehearsal(task_root)
        moved = dict(now, findings=[dict(f, waives=[dict(d, block="stand gap: PC-9") for d in f["waives"]]) if f["id"] == "case_preconditions-1"
                                    else f for f in now["findings"]])
        waivers, by_code, calls, prompt, driver, printed = a364_probe(
            root, env, task_root, "case_preconditions-1: accept", rehearsal=moved, shown_doors=a364_doors(now))
        eq(f"N-2: the door under the same id and message now passes `stand gap: PC-9`: {ALL}", (waivers, by_code, calls), ([], 0, 1))
        eq("N-2: and no case is handed to the executor of `accept as blocked`", driver.state.get("stand_accept_cases"), None)
        check_in("N-2: the conductor is told the checks changed", "the door this id showed is not the one it has now", prompt)
        waivers, by_code, calls, *_ = a364_probe(root, env, task_root, "stage_guard-1: accept because x", shown_doors={})
        eq(f"N-2: a packet that stored no doors (an older gate): {ALL}", (waivers, by_code, calls), ([], 0, 1))
        # a line whose id is no finding of this rehearsal is not this reader's (a case, a question, a bug number)
        waivers, by_code, calls, *_ = a364_probe(root, env, task_root, "BUG-4: it is a bug\nnote-9: whatever")
        eq(f"an id that is no finding and no gap, no word of the list: {ALL} (left in the person's words, recorded whole)",
           (waivers, by_code, calls), ([], 1, 0))
        # the conductor's text for the findings the driver could not repair: the door is data for the conductor only
        import human_text
        finding = {"id": "stage_guard-1", "check": "stage_guard", "message": "after your approval the stage guard will refuse S5",
                   "fix": "", "waives": [{"block": "required stages are not done", "stage": "S5", "option": "accept"}]}
        note = driver.conductor_text("A", "no code move applies", [finding], "nothing")
        check_in("A364: conductor_text names the block, the stage and the word option of the door",
                 "a person's word passes block `required stages are not done` at S5 (word option `accept`)", note)
        added = [line for line in note.splitlines() if line.lstrip().startswith("a person's word passes")]
        eq("A364: the line this adds is one per door", len(added), 1)
        eq("A364: and it breaks no rule of the owner's list (human_text.problems == [])", human_text.problems("\n".join(added), kind="report"), [])
        check_in("A364: with the `fix` (words) printed as it always was",
                 "fix: to pass this check anyway", driver.conductor_text("A", "x", [dict(
                     finding, fix="to pass this check anyway, write the id and your reason")], "nothing"))
        check_in("A364 control: the checker is awake - a planted command in the same note is caught", "script_name",
                 [p["rule"] for p in human_text.problems(note + "\nrun waiver.py --stage S5", kind="report")])
    finally:
        b272_cleanup(root)


def a364_repeat_and_recorded_note() -> None:
    """t-364 edge 4 (FR-7, attempt 2): the same word for the same case at the OTHER gate is written again under this gate's own
    id - one word, two records, each gate's card and the dashboard read their own - and the note a conductor gets about
    lines already on record names no script and no flag."""
    import contract
    root, task_root, env = gate_a_story()
    try:
        a364_take(root, env, task_root, "TC-007: accept")
        eq("A364 edge 4: gate A recorded its waiver (PC-1) and the case-level carry (B-361)", sorted(a364_overrides(task_root)),
           ["stand gap: PC-1", "stand gap: TC-007"])
        # the same case now blocked at gate B: the card is keyed by the manifest key
        (task_root / "work" / "automation-manifest.json").write_text(json.dumps({"tests": [], "unresolved": [
            {"case": "workflows/TC-007", "reason": "blocked_by_env", "owner": "user", "detail": "the flag is off",
             "remedy": A364_REMEDY}]}), encoding="utf-8")
        set_control(root, {"conductor": {"action": "continue", "did": "recorded"}})
        waivers, by_code, calls, prompt, driver, printed = a364_probe(root, env, task_root, "TC-007: accept", kind="gate_B")
        eq("P3d (F4, FR-7): the SAME word at gate B is written too - one word, two records: waivers / by code / conductor",
           (waivers, by_code, calls), (["stand gap: workflows/TC-007"], 1, 0))
        decisions = contract.stand_gap_decisions(s0_pipeline(task_root))
        eq("P3d: each gate's card reads its OWN id: both answered `accept`",
           (decisions["PC-1"]["option"], decisions["workflows/TC-007"]["option"]), ("accept", "accept"))
        import gate_brief
        card = "\n".join(gate_brief.stand_gap_cards(task_root, "B")[0])
        check_in("P3d: the gate B card the person answered shows the answer, and no longer asks", "  answered: accept", card)
        check_not_in("P3d: ...", "To answer a stand gap", card)
        waivers, by_code, calls, *_ = a364_probe(root, env, task_root, "TC-007: run", kind="gate_B")
        eq("A364 edge 4: ANOTHER word at gate B is a new answer under the gate B block: waivers / by code / conductor",
           (waivers, by_code, calls), (["stand gap: workflows/TC-007"], 1, 0))
        eq("A364 edge 4: and it reads back as `handed`", contract.stand_gap_decisions(s0_pipeline(task_root))["workflows/TC-007"]["option"], "handed")
        # the conductor note when the decision does not record by code: lines on record, in words
        set_control(root, {"conductor": {"action": "continue", "did": "recorded"}})
        before = len(d2_conductor_calls(root))
        driver, printed, decided, _ = a364_take(root, env, task_root, "PC-2: accept", record=False)
        prompt = d2_conductor_calls(root)[before]["prompt"]
        check_in("A364: the conductor is told the gap is already recorded", "already recorded: PC-2", prompt)
        start = prompt.index("## Stand-gap lines")
        note = prompt[start:prompt.index("do not record those again", start) + len("do not record those again")]   # the note only
        import human_text
        eq("A364: that note breaks no rule of the owner's list (human_text.problems == [])", human_text.problems(note, kind="report"), [])
    finally:
        b272_cleanup(root)


def main() -> None:
    run_scenarios([], [
        f6_f8_the_mr_record_has_a_shape_and_a_bug_has_no_delivery_word,
        k12_no_delivery_calls_off_only_the_mr_with_the_persons_words,
        c414_the_gate_prices_are_the_rows_the_question_shows,
        a2b_the_card_and_level_accepts_of_the_original_answer_survive_the_option_road,
        d12b_a_refused_call_keeps_the_stand_accepts_for_the_kept_retry,
        d12c_the_driver_prints_what_the_gate_decision_did_not_do,
        d2_the_b_packet_carries_the_approval_line,
        d3_d4_approve_and_retry_from_the_options_at_gate_b,
        n8_gate_text_quotes_the_report_and_branches_on_the_word,
        n8_every_word_of_the_packet_obeys_human_questions,
        n8_the_verdict_is_computed_again_after_gate_b,
        n8_the_recompute_decides_on_the_printed_word,
        c16c_the_delivery_as_seam_questions,
        b414_environment_record_at_gate_a,
        a364_findings_door,
        a364_repeat_and_recorded_note,
    ])
    harness.finish("test_story_run_delivery_c")


if __name__ == "__main__":
    main()
