"""Story runner tests, delivery, second part: no delivery, stories in flight and the gate B packet of an experiment.

Split out of the old test_story_run.py (B-155); the stub, the builders and the runner live in
story_run_common.py. Never launches a real `claude -p` (harness points STORY_RUN_CLAUDE at no_claude.py).
The rest (the third verdict at gate B, the gate B options, the prices, the seam) is test_story_run_delivery_c.py (t-778).
Continues test_story_run_delivery.py (t-104).

t-342 (B-272): the gate B packet answers a stand gap in WORDS (`<case id>: <word>`), and the driver runs the recording
for the person - `b272_gate_b_card_in_words` (the packet obeys human-questions.md; the card never shows the command),
`b272_answer_by_words` (a line is read, recorded as the person's word and the decision keeps the whole answer; every
edge of the form goes to the conductor or is told in words).
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
    BOM, D3_PHRASE, OTHER_SCRIPT, d2_answer, d2_conductor_calls, d3_delivery_ends, d3_loop, d3_s8_done, driver_for,
    eq, human_broken, jsonl, rules_broken, s0_journal, s0_pipeline, s0_question, s0_state, seed, set_control,
)


def d3_no_delivery() -> None:
    """Q1: `no delivery` - read by code on a delivery question, however typed - closes the delivery as
    declined by the person: a mark like `continue`'s, a journal outcome, no conductor call. Any other
    words re-enter the delivery. On a question that is not the delivery's it is not read."""
    task = "QA-9"
    variants = ["no delivery", "No Delivery.", "  `no delivery`  ", BOM + "no delivery!", "NO   DELIVERY", '"no delivery"']
    cases = [("ask_person", {"action": "ask_person", "did": "pushed branch qa/x", "question": "Which reviewer?"}, variants),
             ("stop", {"action": "stop", "did": "pushed branch qa/x", "question": "The push was refused."}, variants[:1]),
             ("unknown", {"action": "retry", "did": "pushed branch qa/x", "question": ""}, variants[:1])]
    for kind, control, words_list in cases:
        for words in words_list:
            root, task_root, env = seed(task)
            try:
                label = f"D3 no delivery ({kind}, {words!r})"
                first, second, _ = d3_delivery_ends(root, env, task, control, words)
                eq(f"{label}: the delivery asks first", first, 4 if kind == "stop" else 3)
                eq(f"{label}: the answer ends the delivery, the story goes on: exit 0", second, 0)
                state = s0_state(task_root)
                mark = state.get("delivery") or {}
                eq(f"{label}: the mark is declined_by_person, done", (mark.get("done"), mark.get("action")), (True, "declined_by_person"))
                check(f"{label}: and says so with their words", str(mark.get("did")).startswith("nothing outward: the person declined the delivery ("), str(mark))
                eq(f"{label}: no second conductor call", len(d2_conductor_calls(root)), 1)
                check(f"{label}: the flag that named the question is gone", "delivery_question" not in state)
                eq(f"{label}: the driver's journal names the outcome",
                   [(r.get("kind"), r.get("outcome")) for r in jsonl(task_root / "state/driver-runs.jsonl") if r.get("kind") == "delivery"],
                   [("delivery", "declined_by_person")])
                check(f"{label}: the person's words are on the record",
                      any(e.get("event") == "human_answer" and "S8 delivery:" in str(e.get("notes")) for e in s0_journal(root)))
            finally:
                harness.cleanup(root)
    # the three questions offer it
    root, task_root, env = seed(task)
    try:
        for kind, control, _ in cases:
            d3_delivery_ends(root, env, task, control)
            ask = s0_question(task_root)
            check_in(f"D3 no delivery: the {kind} question offers the closed answer", "answer `no delivery`", ask)
            eq(f"D3 no delivery: the {kind} question obeys human-questions.md", rules_broken(ask), [])
            st = s0_state(task_root)
            for key in ("delivery_attempts", "delivery_question", "asked"):
                st.pop(key, None)
            (task_root / "state" / "driver-state.json").write_text(json.dumps(st), encoding="utf-8")
            (task_root / "state" / "driver-question.md").unlink()
    finally:
        harness.cleanup(root)
    # other words re-enter the delivery, with their words
    root, task_root, env = seed(task)
    try:
        first, _, _ = d3_delivery_ends(root, env, task, {"action": "ask_person", "did": "pushed", "question": "Which reviewer?"})
        set_control(root, {"conductor": {"action": "continue", "did": "done"}})
        d3_s8_done(task_root)
        driver = driver_for(root, env, task, answer=d2_answer(root, "No, not yet - use Sam Rivera"))
        d3_loop(driver)
        second = driver.run()
        eq("D3 no delivery: other words are not the token - the delivery is entered again", (first, second), (3, 0))
        eq("D3 no delivery: other words: a second conductor call, with their words", len(d2_conductor_calls(root)), 2)
        check_in("D3 no delivery: and the words are in it", "use Sam Rivera", d2_conductor_calls(root)[-1]["prompt"])
        mark = s0_state(task_root).get("delivery") or {}
        check("D3 no delivery: other words: no declined mark", mark.get("action") != "declined_by_person", str(mark))
    finally:
        harness.cleanup(root)
    # a question that is not the delivery's is not read for the token
    root, task_root, env = seed(task)
    try:
        d3_s8_done(task_root)
        driver = driver_for(root, env, task)
        driver.state["asked"] = {"kind": "conductor", "stage": "S8", "dispatch": ""}
        driver.save_state()
        (task_root / "state" / "driver-question.md").write_text("# q\nkind: conductor\n", encoding="utf-8")
        driver = driver_for(root, env, task)
        driver.take_answer(Path(d2_answer(root, "no delivery")))
        check("D3 no delivery: not on a question the delivery did not raise", "delivery" not in s0_state(task_root))
    finally:
        harness.cleanup(root)


def d3_in_flight() -> None:
    """Q2: a call is recorded before it is made and replaced by its verdict; one left on disk by a
    process that died is told to the next process's first prompt."""
    task = "QA-9"
    root, task_root, env = seed(task)
    try:
        seen: list = []
        driver = driver_for(root, env, task)

        def fake(kind, prompt, **kw):
            seen.append(([dict(a) for a in (s0_state(task_root).get("delivery_attempts") or [])], prompt))
            return {"result": 'done\n{"action": "continue", "did": "delivered", "question": ""}',
                    "session_id": "s-1", "total_cost_usd": 0.0, "num_turns": 1}
        driver.run_claude = fake
        driver.delivery({})
        eq("D3 in flight: while the call runs the record on disk has it", [bool(a.get("in_flight")) for a in seen[0][0]], [True])
        check_not_in("D3 in flight: a first call of a clean story has no earlier attempts", "Earlier attempts", seen[0][1])
        attempts = s0_state(task_root)["delivery_attempts"]
        eq("D3 in flight: the verdict replaces it", [(a.get("action"), a.get("in_flight")) for a in attempts], [("continue", None)])
    finally:
        harness.cleanup(root)
    root, task_root, env = seed(task)
    try:
        state = s0_state(task_root)
        state["delivery_attempts"] = [{"in_flight": True, "at": "2026-09-29T10:00:00+00:00"}]
        (task_root / "state" / "driver-state.json").write_text(json.dumps(state), encoding="utf-8")
        seen = []
        driver = driver_for(root, env, task)
        driver.run_claude = fake
        driver.delivery({})
        prompt = seen[0][1]
        check_in("D3 in flight: an interrupted call is named in the next process's first prompt", "never reported back", prompt)
        check_in("D3 in flight: with 'may have been interrupted'", "A previous call may have been interrupted", prompt)
        check_in("D3 in flight: and the reuse instruction", D3_PHRASE, prompt)
        check_not_in("D3 in flight: an interrupted call is not told as something that went out", "These already went out", prompt)
        eq("D3 in flight: the old line stays, the new verdict follows",
           [bool(a.get("in_flight")) or a.get("action") for a in s0_state(task_root)["delivery_attempts"]], [True, "continue"])
    finally:
        harness.cleanup(root)


def d3_gate_b_experiment() -> None:
    """F1: an experiment's gate B packet and instruction say nothing of a merge request; an ordinary
    story's are unchanged. The story has one open question, so the open-items list exists."""
    import re as _re
    import gate_brief
    task = "QA-9"
    root, task_root, env = seed(task)
    try:
        (task_root / "work" / "requirements-readiness.json").write_text(json.dumps(
            {"open_questions": [{"id": "Q-1", "question": "Which reviewer?", "severity": "low", "owner_role": "qa-story"}]}),
            encoding="utf-8")
        mr = _re.compile(r"\bMR\b|merge request", _re.IGNORECASE)
        driver = driver_for(root, env, task)
        # t-305 N8 (R6): a packet offers the MR only on a verdict that opens it, and a story with NO ledger reads `no`:
        # the ordinary story of this scenario has a ledger that says `yes`
        (task_root / "work" / "ledger.json").write_text(json.dumps({"rows": [], "delivery_ready": True, "delivery_verdict": "yes"}),
                                                       encoding="utf-8")
        ordinary = driver.gate_text("B")
        check_in("F1 control: an ordinary gate B asks whether the MR is opened", "say whether the MR is opened (Draft) or not", ordinary)
        check_in("F1 control: and asks for the reason of known gaps", "'deliver with known gaps' needs its reason", ordinary)
        check_in("F1 control: the open list is titled before the MR", "## Open before the MR (", gate_brief.render_gate_b(task, task_root))
        check_in("F1 control: and offers to open the MR anyway", 'say "open the MR anyway"', gate_brief.render_gate_b(task, task_root))
        harness.run_script("stage_done.py", "--task", task, "--set", "no_trace=true", cwd=root, env=env)
        packet = gate_brief.render_gate_b(task, task_root)
        check_in("F1 an experiment: the open items are still listed, titled without the MR", "## Open items (", packet)
        check_not_in("F1 an experiment: and not titled before it", "Open before the MR", packet)
        check_in("F1 an experiment: and the question is in it", "Which reviewer?", packet)
        found = mr.findall(packet)
        eq("F1 an experiment: the packet says nothing of an MR or a merge request", found, [], packet)
        text = driver.gate_text("B")
        eq("F1 an experiment: neither does the whole gate text, instruction included", mr.findall(text), [], text)
        check_in("F1 an experiment: the instruction still asks for the bugs", "Answer by number for the bugs to file.", text)
        # t-342 (B-271, owner 02.10): the retro is always full - the packet offers no choice about it, in either text
        for label, packet in (("an ordinary story", ordinary), ("an experiment", text)):
            for phrase in ("silence is the full retro", "skipped or cut", "numbers alone", "The story ends with the retro"):
                check_not_in(f"B-271 {label}: the gate B text does not offer the retro to be cut ({phrase!r})", phrase, packet)
        check_in("B-271 control: the ordinary instruction still asks about the MR",
                 "say whether the MR is opened (Draft) or not; a 'deliver with known gaps' needs its reason.", ordinary)
    finally:
        harness.cleanup(root)


# --- t-342 (B-272): a stand gap at gate B is answered in words ---------------------------------------------------
B272_TICKET = "TP1-15045"
B272_CASE_A, B272_CASE_B = f"{B272_TICKET}_TC_010", f"{B272_TICKET}_TC_012"
B272_REMEDY = {"kind": "reporter", "where": "qa-factory/config.json:profiles[api].commands.one_test",
               "change": "the runner passes the report option itself", "restart": "the test runner"}


def man1_gate_b(*, second_area: bool = False, gaps: bool = True) -> tuple:
    """A project shaped like man1's gate B (TP1-15045): the project's own case id form, two cases the stand cannot
    run (the first with an exact change on its card, the second with none), two bug drafts and an XXL size.
    `second_area`: a third gap whose case id the second gap's area shares (the id alone then names two gaps)."""
    root, task_root, env = seed(B272_TICKET)
    config = root / "qa-factory" / "config.json"
    cfg = json.loads(config.read_text(encoding="utf-8"))
    cfg["case_id_form"] = "{ticket}_TC_{nnn}"
    config.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    import contract
    contract.case_config_reset()
    folder = task_root / "work" / "test-cases" / "workflows"
    folder.mkdir(parents=True, exist_ok=True)
    for case_id in (B272_CASE_A, B272_CASE_B):
        (folder / f"{case_id}.md").write_text(
            f"---\nid: {case_id}\ntitle: validate returns the same codes as update\nrequirements: R-13, R-17\n---\n\n"
            "## When\n1. call it\n", encoding="utf-8")
    rows = [{"case": f"workflows/{B272_CASE_A}", "reason": "blocked_by_env", "owner": "user",
             "detail": "the api runner writes no report the factory can read", "remedy": B272_REMEDY},
            {"case": f"workflows/{B272_CASE_B}", "reason": "blocked_by_env", "owner": "user",
             "detail": "the stand has one account only"}]
    if second_area:
        rows.append({"case": f"other/{B272_CASE_B}", "reason": "blocked_by_env", "owner": "user",
                     "detail": "the same case number in another area", "remedy": B272_REMEDY})
    (task_root / "work" / "automation-manifest.json").write_text(
        json.dumps({"tests": [], "unresolved": rows if gaps else []}), encoding="utf-8")
    (task_root / "work" / "sizing.json").write_text(json.dumps(
        {"size": "XXL", "computed_budget": 84, "recommended_budget": 28, "cap": 28, "overage": 56}), encoding="utf-8")
    drafts = task_root / "work" / "bug-drafts"
    drafts.mkdir(parents=True, exist_ok=True)
    for number in (1, 2):
        (drafts / f"BD-{number}.json").write_text(json.dumps(
            {"id": f"BD-{number}", "case": B272_CASE_A, "title": f"the filter loses its state ({number})",
             "impact": "degraded"}), encoding="utf-8")
    return root, task_root, env


def b272_cleanup(root) -> None:
    """The project goes, and the project's case id form with it: the contract memoises a config per process, and a
    later scenario of this file must not meet the form of this one."""
    harness.cleanup(root)
    import contract
    contract.case_config_reset()


def gate_b_packet(driver, task_root) -> str:
    """`gate_text("B")` the way the driver builds it, with the ONE part this node does not write held clean: the
    rehearsal's own lines (gate_preflight's text carries commands for the factory's findings - another file's text,
    reported not fixed) and the rehearsal the brief reads in-process. Everything else is the real thing: the brief,
    the waivers list, the manual checks, the instruction."""
    import gate_brief
    import gate_preflight
    real_run, real_py = gate_preflight.run, driver.py
    gate_preflight.run = lambda *a, **k: {"gate": "B", "findings": [], "can_proceed": True}

    def py(script, *args, **kw):
        if script == "gate_brief.py":
            return 0, gate_brief.render_gate_b(B272_TICKET, task_root)
        if script == "gate_preflight.py":
            return 0, "Gate B rehearsal: nothing stands in the way of the delivery."
        return real_py(script, *args, **kw)
    driver.py = py
    try:
        return driver.gate_text("B")
    finally:
        gate_preflight.run, driver.py = real_run, real_py


def b272_gate_b_card_in_words() -> None:
    """The packet: a stand-gap card shows four answers in words and ONE form, never the script that records them."""
    import gate_brief
    root, task_root, env = man1_gate_b()
    try:
        driver = driver_for(root, env, B272_TICKET)
        text = gate_b_packet(driver, task_root)
        check_in("B-272: the heading counts the gaps", "## Stand gaps (2)", text)
        check_in("B-272: the gap is named by its case id, linked to the case file, and what it costs",
                 f"[{B272_CASE_A}](qa-factory/artifacts/{B272_TICKET}/work/test-cases/workflows/{B272_CASE_A}.md) — needs R-13, R-17", text)
        check_in("B-272: what is missing and the exact change are on the card",
                 "the fix:  qa-factory/config.json:profiles[api].commands.one_test -> the runner passes the report option itself", text)
        check_in("B-272: the form is ONE line shape", "`<case id or level name>: <word>`", text)
        check_in("B-272: with an example that is a real case id of this story", f"`{B272_CASE_A}: accept`", text)
        words = gate_brief.stand_gap_words()
        eq("B-272: the four answers come from the data file", [row["option"] for row in words],
           ["apply", "theirs", "handed", "accept"])
        for row in words:
            check_in(f"B-272: the word `{row['word']}` is offered with its explanation",
                     f"- `{row['word']}` — {row['says']}", text)
        check_in("B-272: `change` says it needs an exact change on the card", "offered only for a gap whose card shows an exact change", text)
        check_in("B-272: any other wording is said to go to the assistant running the story (GW1-32: one sentence, the shared constant)",
                 gate_brief.ANYTHING_ELSE_SENTENCE, text)
        for banned in ("waiver.py", "--block", "--decision", "stand gap:", "handed", "apply |", "--stage"):
            check_not_in(f"B-272: the packet never shows {banned!r}", banned, text)
        eq("B-272: the whole gate B packet obeys human-questions.md (human_text.problems == [])", human_broken(text), [])
        # the same checker over the card the packet used to carry: it must fail, or the key above proves nothing
        # t-357: `stand_gaps.render` is the ONE card now (no command in it), so the planted old card is spelled out
        old = ('Stand gap workflows/TC-001 (gate B)\n  the fix:  x -> y\n  options:  (a) apply   (b) theirs   (c) handed   (d) accept\n'
               '  answer:   waiver.py --task QA-9 --stage S9 --block "stand gap: workflows/TC-001" --decision "apply | theirs | handed | accept"\n')
        check_in("B-272 control: the old card (waiver.py in its answer line) is caught by the same check",
                 "script_name", human_broken("A packet whose body is long enough to stand on its own feet.\n\n" + old))
        # the size line, in words (B-271's budget words), and the bugs by number with their paths
        check_in("B-271: the size line says what the requirements weigh and the cap of the size",
                 "the requirements weigh 84 (each weighted by its priority and area); the XXL cap is 28, **over the cap by 56**", text)
        for old_words in ("budget 84", "recommended 28", "cap 28,"):
            check_not_in(f"B-271: the old budget words are gone ({old_words!r})", old_words, text)
        for number in (1, 2):
            check_in(f"B-271: bug {number} is listed by number", f"{number}. **the filter loses its state ({number})**", text)
            # HF8-20 (76789d2a, t-321; the owner's 29.10.2026 rule in human-text.json `technical_file_named`): a person is never
            # sent to the draft's JSON record. This fixture has written no readable text yet, so the bug carries no path at all
            # (gate_brief.bug_rows: a readable file only); the packet's own check above (human_broken == []) holds the same rule.
            check_not_in(f"B-271: bug {number} names no JSON record of the factory",
                         f"qa-factory/artifacts/{B272_TICKET}/work/bug-drafts/BD-{number}.json", text)
        # a story with no stand gap: no card and no form line
        harness.cleanup(root)
        root, task_root, env = man1_gate_b(gaps=False)
        quiet = gate_b_packet(driver_for(root, env, B272_TICKET), task_root)
        for absent in ("Stand gaps", "`<case id or level name>: <word>`"):
            check_not_in(f"B-272: a story with no stand gap has no card and no form line ({absent!r})", absent, quiet)
        eq("B-272: and its packet obeys human-questions.md too", human_broken(quiet), [])
        # a gap the person answered shows the word, not the question
        harness.cleanup(root)
        root, task_root, env = man1_gate_b()
        path = task_root / "pipeline.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["stage_overrides"] = [{"stage": "S9", "match": f"stand gap: workflows/{B272_CASE_A}", "by": "human",
                                    "decision": f"accept - the person wrote: {B272_CASE_A}: accept", "at": "2026-10-02T10:00:00+00:00"}]
        path.write_text(json.dumps(data), encoding="utf-8")
        answered = gate_b_packet(driver_for(root, env, B272_TICKET), task_root)
        check_in("B-272: an answered gap shows the word the person gave (FR-7)", "  answered: accept (2026-10-02T10:00:00+00:00)", answered)
        card_part = answered.split("## Stand gaps", 1)[1].split("\n## ", 1)[0]
        check_not_in("B-272: the card does not read the driver's own recording sentence back to them", "the person wrote", card_part)
        eq("B-272: with a gap still open the form stays", "`<case id or level name>: <word>`" in answered, True)
        # more gaps than cards: the rest are one line each and the same words answer them
        harness.cleanup(root)
        root, task_root, env = man1_gate_b(second_area=True)
        rows = json.loads((task_root / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
        for number in range(4, 8):
            rows["unresolved"].append({"case": f"area{number}/{B272_TICKET}_TC_0{number}0", "reason": "blocked_by_env",
                                       "owner": "user", "detail": f"missing piece {number}"})
        (task_root / "work" / "automation-manifest.json").write_text(json.dumps(rows), encoding="utf-8")
        many = gate_b_packet(driver_for(root, env, B272_TICKET), task_root)
        check_in("B-272: seven gaps are counted", "## Stand gaps (7)", many)
        eq("B-272: three are cards", many.count("Stand gap: "), 3)
        check_in("B-272: the rest are listed, one line each, with what is missing", "missing piece 7", many)
        check_not_in("B-272: and no command comes back in a long packet", "stand_gaps.py", many)
        eq("B-272: the long packet obeys human-questions.md", human_broken(many), [])
        # two gaps share one case id (two areas): the key is what the card shows, so the answer names ONE gap
        check_in("B-272: a case id two gaps share is written with its area", f"other/{B272_CASE_B}", many)
    finally:
        b272_cleanup(root)


def recording_stub(calls: list, note, result=True):
    """A stand-in for `Driver.record_by_code` that takes ANY call (`*args, **kwargs`), appends `note(call)` to `calls` and returns
    `result`; `call` is `{kind, stage, words, <the keywords given>}`. A signature the real method grows (C2-7 added `apply_words`)
    never breaks the test or silently drops an argument (FR-31, C4-14)."""
    def fake(*args, **kwargs):
        calls.append(note({**dict(zip(("kind", "stage", "words"), args)), **kwargs}))
        return result
    return fake


def b272_take(root, env, words: str, *, py=None, record=True) -> tuple:
    """One gate B answer taken by a fresh in-process driver: (driver, printed, the gate decisions recorded by code).
    `py` replaces the driver's script runner for the call (a refusal); the gate decision is recorded by a spy, so the
    gate's own prerequisites are not what is under test."""
    driver = driver_for(root, env, B272_TICKET, answer=d2_answer(root, words))
    decided = []
    driver.record_by_code = recording_stub(decided, lambda call: (call["kind"], call["words"]), record)
    driver.state["asked"] = {"kind": "gate_B", "stage": "S8", "dispatch": ""}
    driver.save_state()
    question = driver.state_dir / "driver-question.md"
    question.write_text("# Driver question — T\nkind: gate_B\nstage: S8\ndispatch: \nasked_at: x\n\n# Gate B\n\n"
                        "A packet with enough words in it to be a question.\n\n---\nAnswer: write your words to a file\n",
                        encoding="utf-8")
    if py is not None:
        real = driver.py
        driver.py = lambda script, *a, **k: py(script, real, *a, **k)
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        driver.take_answer(Path(d2_answer(root, words)))
    return driver, printed.getvalue(), decided


def b272_overrides(task_root) -> dict:
    """{gap id: the stage override recorded for it} - `waiver.py`'s own record, read back from pipeline.json."""
    return {o["match"].split("stand gap:", 1)[1].strip(): o for o in s0_pipeline(task_root).get("stage_overrides") or []
            if str(o.get("match") or "").startswith("stand gap:")}


def b272_answer_by_words() -> None:
    """The answer: a `<case id>: <word>` line is recorded for the person by the driver; the gate decision keeps the
    whole answer; what the form cannot read goes to the conductor and is never dropped."""
    import contract
    key_a, key_b = f"workflows/{B272_CASE_A}", f"workflows/{B272_CASE_B}"
    root, task_root, env = man1_gate_b()
    try:
        # --- a line is read, recorded as the person's word, and the decision keeps the whole answer ---
        words = f"approve\n{B272_CASE_A}: accept\nfile 1; 2 is not a bug"
        driver, printed, decided = b272_take(root, env, words)
        entry = b272_overrides(task_root).get(key_a) or {}
        eq("B-272: the recording is the one the card used to ask the person to type (stage S9, block `stand gap: <id>`)",
           (entry.get("stage"), entry.get("match")), ("S9", f"stand gap: {key_a}"))
        check_in("B-272: the person's own line is the recorded word (P13)", f"the person wrote: {B272_CASE_A}: accept", str(entry.get("decision")))
        eq("B-272: it reads back as the answer `accept` (the decision's first word)",
           contract.stand_gap_decisions(s0_pipeline(task_root)).get(key_a, {}).get("option"), "accept")
        eq("B-272: the gate decision is recorded by code with the WHOLE answer, bug lines included (FR-9)", decided, [("gate_B", words)])
        eq("B-272: no conductor is called for it (FR-48)", len(d2_conductor_calls(root)), 0)
        check_in("B-272: the log says what was recorded", f"gate B: stand gap {B272_CASE_A}: recorded on the person's word, as accept", printed)
        check("B-272: the person's word is in the project journal",
              any(e.get("event") == "human_answer" and f"stand gap: {key_a}" in str(e.get("notes")) for e in s0_journal(root)))
        eq("B-272: the other gap is not touched", key_b in b272_overrides(task_root), False)
        # --- two lines for one gap: the last wins, and it is said ---
        driver, printed, decided = b272_take(root, env, f"approve\n{B272_CASE_A}: accept\n{B272_CASE_A}: run")
        eq("B-272: the last line counts", contract.stand_gap_decisions(s0_pipeline(task_root))[key_a]["option"], "handed")
        check_in("B-272: and the answer says so", f"{B272_CASE_A} was answered more than once; the last line counts", printed)
        eq("B-272: one record for the gap, not two", len([o for o in s0_pipeline(task_root)["stage_overrides"] if o["match"] == f"stand gap: {key_a}"]), 1)
        check_in("B-272: and the record says which earlier line it replaces", f"(replaces their earlier line: {B272_CASE_A}: accept)",
                 b272_overrides(task_root)[key_a]["decision"])
        # --- the words, in the spellings the data file lists and the ones it normalises ---
        for said, option in (("Change.", "apply"), ("`myself`", "theirs"), ("  RUN  ", "handed"), ("accept as blocked", "accept"),
                             ("i will change it", "theirs"), ("handed", "handed")):
            b272_take(root, env, f"approve\n- {B272_CASE_A}: {said}")
            eq(f"B-272: `{said}` is {option}", contract.stand_gap_decisions(s0_pipeline(task_root))[key_a]["option"], option)
        # --- lines the form cannot read go to the conductor with the lines named, the decision is not recorded by code ---
        unreadable = [
            ("an id that is no stand gap of this gate", f"{B272_TICKET}_TC_099: accept", "that id is not a stand gap of this gate"),
            ("a word outside the list", f"{B272_CASE_B}: yes please", "the word is not one of the answers"),
            ("a word in another language", f"{B272_CASE_B}: {OTHER_SCRIPT}", "the word is not one of the answers"),
            ("`change` for a gap with no exact change on its card", f"{B272_CASE_B}: change", "never one of its answers"),
        ]
        for label, line, why in unreadable:
            set_control(root, {"conductor": {"action": "continue", "did": "recorded"}})
            before = len(d2_conductor_calls(root))
            driver, printed, decided = b272_take(root, env, f"approve\n{B272_CASE_A}: myself\n{line}")
            calls = d2_conductor_calls(root)[before:]
            eq(f"B-272: {label}: the conductor is called once", len(calls), 1)
            check_in(f"B-272: {label}: with the line named", line, calls[0]["prompt"])
            check_in(f"B-272: {label}: and why code did not read it", why, calls[0]["prompt"])
            check_in(f"B-272: {label}: and the line it DID record, not to be recorded again", f"already recorded: {B272_CASE_A}", calls[0]["prompt"])
            # critic t-346 F3: what the conductor needs to record a gap in the form the reader reads
            prompt = calls[0]["prompt"]
            check_in(f"F3: {label}: the note gives the block key of each gap", f"block `stand gap: {key_b}`, stage S9", prompt)
            check_in(f"F3: {label}: for every gap, not only the one named", f"block `stand gap: {key_a}`, stage S9", prompt)
            check_in(f"F3: {label}: and says the decision's first word is the option", "FIRST word must be the option", prompt)
            import gate_brief as _gb
            for row in _gb.stand_gap_words():
                check_in(f"F3: {label}: the word map comes from the data file ({row['option']})",
                         f"`{row['option']}` for " + ", ".join(f"`{w}`" for w in [row["word"], *row["synonyms"]]), prompt)
            eq(f"B-272: {label}: the decision is not recorded by code over a line nobody read", decided, [])
            eq(f"B-272: {label}: the answer is kept whole for the gate", (driver.state.get("gate_answer_kept") or {}).get("words"),
               f"approve\n{B272_CASE_A}: myself\n{line}")
            eq(f"B-272: {label}: the readable line of the same answer (another gap) was recorded",
               contract.stand_gap_decisions(s0_pipeline(task_root)).get(key_a, {}).get("option"), "theirs")
            (task_root / "pipeline.json").write_text(json.dumps(dict(
                s0_pipeline(task_root), stage_overrides=[o for o in s0_pipeline(task_root)["stage_overrides"]
                                                         if o["match"] != f"stand gap: {key_a}"])), encoding="utf-8")
        # --- critic t-346 F4: every line read, the gate decision does not record by code: the conductor is told what is on record ---
        set_control(root, {"conductor": {"action": "continue", "did": "recorded"}})
        before = len(d2_conductor_calls(root))
        driver, printed, decided = b272_take(root, env, f"approve\n{B272_CASE_B}: accept", record=False)
        calls = d2_conductor_calls(root)[before:]
        eq("F4: the gate decision failed to record: the conductor gets the words", len(calls), 1)
        check_in("F4: and is told the stand-gap line is already on the record", f"already recorded: {B272_CASE_B}", calls[0]["prompt"])
        check_not_in("F4: with no list of unread lines (there are none)", "could not read as a stand-gap answer", calls[0]["prompt"])
        (task_root / "pipeline.json").write_text(json.dumps(dict(
            s0_pipeline(task_root), stage_overrides=[o for o in s0_pipeline(task_root)["stage_overrides"]
                                                     if o["match"] != f"stand gap: {key_b}"])), encoding="utf-8")
        # --- critic t-346 F2: a readable line and then an unreadable one for ONE gap: nothing is recorded for it, the conductor gets both ---
        before = len(d2_conductor_calls(root))
        driver, printed, decided = b272_take(root, env, f"approve\n{B272_CASE_B}: run\n{B272_CASE_B}: no wait, not that")
        calls = d2_conductor_calls(root)[before:]
        eq("F2: the gap is not recorded by code", (key_b in b272_overrides(task_root), decided), (False, []))
        eq("F2: the whole gap goes to the conductor", len(calls), 1)
        check_in("F2: with the person's last line", f"{B272_CASE_B}: no wait, not that", calls[0]["prompt"])
        check_in("F2: and the earlier line beside it", f"{B272_CASE_B}: run", calls[0]["prompt"])
        # --- a line that is not the form at all stays in the person's words, as today ---
        before = len(d2_conductor_calls(root))
        prose = "file 1 and 2; Q1: a\nR-17: it is a bug"
        driver, printed, decided = b272_take(root, env, "approve\n" + prose)
        eq("B-272: with the approval word on its first line, prose and ids that are not stand gaps are recorded whole, as always",
           decided, [("gate_B", "approve\n" + prose)])
        eq("B-272: and no conductor is called", len(d2_conductor_calls(root)), before)
        # (the same prose WITHOUT the word is not an approval: `record_by_code` is spied here, so that pin lives in
        # test_story_run_gate_repair A1, where the real recorder runs)
        # --- the recording refuses: the person reads it in words, never the command ---
        from story_run import Person

        def refuse(script, real, *args, **kw):
            return (1, "waiver: boom - pipeline.json is locked") if script == "waiver.py" else real(script, *args, **kw)
        # D1 (C1-4b, G22, FR-3): the FACTORY repairs a record the story refused - the person is never made to send the answer again
        set_control(root, {"conductor": {"action": "continue", "did": "looked"}})
        before = len(d2_conductor_calls(root))
        raised = None
        try:
            driver, printed, decided = b272_take(root, env, f"approve\n{B272_CASE_B}: accept", py=refuse)
        except Person as person:
            raised = person
        eq("D1: a recording that fails raises NO Person to the person", raised, None)
        calls = d2_conductor_calls(root)[before:]
        eq("D1: one conductor call, and nothing recorded by code over the line the story refused", (len(calls), decided), (1, []))
        check_in("D1: the prompt names the failed line", f"{B272_CASE_B}: accept", calls[0]["prompt"])
        check_in("D1: and the refusal text of the record", "pipeline.json is locked", calls[0]["prompt"])
        check_not_in("D1: nowhere is the person asked to send the whole answer again", "send your whole answer again", calls[0]["prompt"])
        eq("D1: heard as an approval, the answer is kept for the gate", (driver.state.get("gate_answer_kept") or {}).get("approved_by"), "token")
    finally:
        b272_cleanup(root)
    # --- two gaps share a case id: the id alone names two, the key names one ---
    root, task_root, env = man1_gate_b(second_area=True)
    try:
        set_control(root, {"conductor": {"action": "continue", "did": "recorded"}})
        driver, printed, decided = b272_take(root, env, f"approve\n{B272_CASE_B}: accept")
        eq("B-272: an id two gaps share is not read (the conductor asks which)", (decided, len(d2_conductor_calls(root))), ([], 1))
        check_in("B-272: and the log says why", "that id names more than one stand gap of this gate", d2_conductor_calls(root)[0]["prompt"])
        driver, printed, decided = b272_take(root, env, f"approve\nother/{B272_CASE_B}: accept")
        eq("B-272: the key with its area names exactly one", (sorted(b272_overrides(task_root)), len(decided)), (["other/" + B272_CASE_B], 1))
    finally:
        b272_cleanup(root)
    # --- a story with no stand gap: nothing is read, whatever the lines look like ---
    root, task_root, env = man1_gate_b(gaps=False)
    try:
        driver, printed, decided = b272_take(root, env, f"approve\n{B272_CASE_A}: accept\nfile 1")
        eq("B-272: no stand gap, no form: the answer is recorded whole and no word is read", (len(decided), b272_overrides(task_root), len(d2_conductor_calls(root))), (1, {}, 0))
        check_not_in("B-272: and nothing about a stand gap is printed", "stand gap", printed)
    finally:
        b272_cleanup(root)


# --- t-364: the SAME answer reader at gate A (stand-gap cards of S5, the doors of the rehearsal's findings) ---------------
A364_REMEDY = {"kind": "flag", "where": "app/config.yaml:3", "change": "turn the flag on", "restart": "the app"}


def gate_a_story() -> tuple:
    """A project at gate A: TC-007 has ONE unmet precondition (PC-1), TC-008 has TWO (PC-2, PC-3). The rehearsal is the
    driver's seam (`Driver.rehearse`), so the fixture hands it the rows the real one would find."""
    root, task_root, env = seed(B272_TICKET)
    folder = task_root / "work" / "test-cases" / "workflows"
    folder.mkdir(parents=True, exist_ok=True)

    def pc(number: int, what: str) -> dict:
        return {"id": f"PC-{number}", "kind": "feature_flag", "what": what, "partitions": [], "remedy": A364_REMEDY,
                "check": {"http": {"path": "/v1/config", "status": 200, "json_path": f"features.f{number}", "equals": True}}}
    for case_id, items in (("TC-007", [pc(1, "sub-workflow states are enabled")]),
                           ("TC-008", [pc(2, "the first flag is on"), pc(3, "the second flag is on")])):
        (folder / f"{case_id}.md").write_text(
            f"---\nid: {case_id}\ntitle: a node keeps its own state\nrequirements: R-3\npreconditions: {json.dumps(items)}\n---\n\n"
            "## When\n1. call it\n", encoding="utf-8")
    return root, task_root, env


def a364_rehearsal(task_root, findings=None) -> dict:
    import stand_gaps
    return {"gate": "A", "findings": findings if findings is not None else [
        {"id": "stage_guard-1", "check": "stage_guard", "class": "factory_defect", "message": "after your approval ...",
         "fix": "to pass this check anyway, write `stage_guard-1: accept` with your reason",
         "waives": [{"block": "required stages are not done", "stage": "S5", "option": "accept"}]},
        {"id": "prepare-1", "check": "prepare", "class": "factory_fixable", "message": "S5 would be dispatched without x",
         "fix": "produce x before the gate"},
        {"id": "s5_reporter-1", "check": "s5_reporter", "class": "person_decides", "message": "RP-api: one test ran ...",
         "fix": "answer the card", "waives": [{"block": "stand gap: RP-api", "stage": "S5", "option": "any"}]},
        {"id": "e2e_stand_limit-1", "check": "e2e_stand_limit", "class": "person_decides", "message": "e2e stand limit: e2e-ui ...",
         "fix": "(a) ... to run it yourself, write `e2e_stand_limit-1: run`",
         "waives": [{"block": "executor unavailable: e2e-ui", "stage": "S5", "option": "handed"}]},
        {"id": "case_preconditions-1", "check": "case_preconditions", "class": "person_decides",
         "message": "TC-007 — a stand gap (sub-workflow states are enabled): the exact change is known",
         "fix": "answer the card: write the line it shows, with one of the words it lists",
         "waives": [{"block": "stand gap: PC-1", "stage": "S5", "option": "any"}]}],
        "stand_gaps": stand_gaps.declared_preconditions(task_root)}


def a364_packet(rehearsal: dict) -> str:
    """The rehearsal section of the packet as `gate_preflight.render` prints it: `  - [<id>] <message>` per finding."""
    return "## Rehearsal of gate A\n" + "\n".join(f"  - [{f['id']}] {f['message']}" for f in rehearsal.get("findings") or [])


def a364_doors(rehearsal: dict) -> dict:
    """What `Driver.gate()` stores when it asks: {finding id: its `waives`} - the door each id showed (t-369 N-2)."""
    return {f["id"]: list(f.get("waives") or []) for f in rehearsal.get("findings") or []}


def a364_take(root, env, task_root, words: str, *, kind="gate_A", rehearsal="default", shown="auto", shown_doors="auto",
              py=None, record=True, extra_state=None) -> tuple:
    """One gate answer taken by a fresh in-process driver over `gate_a_story()`: (driver, printed, gate decisions recorded
    by code, how many rehearsals were run). The rehearsal is the fixture's; the gate decision is a spy. `shown` is the
    rehearsal section of the packet the person was shown ("auto": the one the rehearsal now gives)."""
    driver = driver_for(root, env, B272_TICKET, answer=d2_answer(root, words))
    ran = []
    result = a364_rehearsal(task_root) if rehearsal == "default" else rehearsal
    driver.rehearse = lambda gate: ran.append(gate) or result
    decided = []
    driver.record_by_code = recording_stub(decided, lambda call: (call["kind"], call["words"]), record)
    driver.state["asked"] = {"kind": kind, "stage": "S4" if kind == "gate_A" else "S8", "dispatch": ""}
    driver.state["shown_doors"] = {kind[-1]: a364_doors(result) if shown_doors == "auto" else shown_doors}
    driver.state.update(extra_state or {})
    driver.save_state()
    (driver.state_dir / "driver-question.md").write_text(
        f"# Driver question — T\nkind: {kind}\nstage: S4\ndispatch: \nasked_at: x\n\n# Gate\n\n"
        "A packet with enough words in it to be a question.\n\n" + (a364_packet(result) if shown == "auto" else shown)
        + "\n\n---\nAnswer: write your words to a file\n", encoding="utf-8")
    if py is not None:
        real = driver.py
        driver.py = lambda script, *a, **k: py(script, real, *a, **k)
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        driver.take_answer(Path(d2_answer(root, words)))
    return driver, printed.getvalue(), decided, len(ran)


def a364_overrides(task_root) -> dict:
    """{block: the stage override recorded for it} - `waiver.py`'s own record, read back from pipeline.json."""
    return {o["match"]: o for o in s0_pipeline(task_root).get("stage_overrides") or []}


def a364_probe(root, env, task_root, words: str, **kw) -> tuple:
    """One answer, all three outcomes at once: (the waivers it wrote, gate decisions recorded by code, conductor calls, the
    conductor's prompt or ""). A key that checks only one of them can hide the others (critic t-367)."""
    before_calls, before = len(d2_conductor_calls(root)), dict(a364_overrides(task_root))
    driver, printed, decided, _ = a364_take(root, env, task_root, words, **kw)
    after = a364_overrides(task_root)
    calls = d2_conductor_calls(root)[before_calls:]
    return (sorted(k for k, v in after.items() if before.get(k) != v), len(decided), len(calls),
            calls[0]["prompt"] if calls else "", driver, printed)


def flag_file(args, flag: str):
    """The text of the file a controller call's `flag` names (DC1-19: the driver hands the answers, the shown hashes and the remedies BY FILE), else None."""
    args = list(args)
    return Path(args[args.index(flag) + 1]).read_bytes().decode("utf-8") if flag in args else None


def a364_answer_at_gate_a() -> None:
    """t-364: `<case id>: <word>` at gate A is recorded for the person by the driver (stage S5, block `stand gap: <gap id>`), the
    decision keeps the whole answer, and every edge of the form goes to the conductor or is told in words."""
    import contract
    import planning_contract
    root, task_root, env = gate_a_story()
    try:
        # --- a line is read, recorded as the person's word at S5, and the decision keeps the whole answer ---
        driver, printed, decided, ran = a364_take(root, env, task_root, "TC-007: accept\nnothing else to say")
        entry = a364_overrides(task_root).get("stand gap: PC-1") or {}
        eq("A364: the waiver is the one gate B writes - stage S5, block `stand gap: <gap id>`", (entry.get("stage"), entry.get("match")),
           ("S5", "stand gap: PC-1"))
        check_in("A364: the person's own line is the recorded word (P13)", "the person wrote: TC-007: accept", str(entry.get("decision")))
        eq("A364: it reads back as `accept` (the decision's first word)", contract.stand_gap_decisions(s0_pipeline(task_root))["PC-1"]["option"], "accept")
        eq("A364: the gate decision keeps the whole answer", decided, [("gate_A", "TC-007: accept\nnothing else to say")])
        check_in("A364: the driver says what it recorded", "gate A: stand gap TC-007: recorded on the person's word, as accept (TC-007: accept)", printed)
        eq("A364: one rehearsal served the answer", ran, 1)
        eq("A364: TC-007 has one gap and it is accepted: the case is handed to the executor of `accept as blocked`",
           driver.state.get("stand_accept_cases"), ["TC-007"])
        # --- the agreement with apply_gate_answers (edge 5): ONE read line, two records that cannot differ ---
        # DC1-19: the executor is the controller's `gate-decision`; the driver hands the answers' lines BY FILE (`--answers-file`)
        seen, real_py = [], driver.py

        def fake_py(script, *a, **k):
            if script == "controller.py":
                seen.append(flag_file(a, "--answers-file"))
                return 0, "recorded"
            return real_py(script, *a, **k)
        driver.py = fake_py
        driver.record_by_code = type(driver).record_by_code.__get__(driver)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                driver.record_by_code("gate_A", "S4", "approve\nTC-007: accept\nnothing else to say")
                again = list(seen)
                driver.state["stand_accept_cases"] = ["TC-007"]
                driver.record_by_code("gate_A", "S4", "approve\nTC-007: accept as blocked")
        finally:
            driver.py = real_py
        eq("A364 edge 5: the executor gets the person's line AND its own token for the accepted case",
           again, ["approve\nTC-007: accept\nnothing else to say\nTC-007: accept as blocked"])
        eq("A364 edge 5: a token the person wrote themselves is not repeated", seen[1:], ["approve\nTC-007: accept as blocked"])
        import question_register as QR
        read = QR.parse_choices(again[0], [], ["TC-007", "TC-008"])
        eq("A364 edge 5: the token reads as `accept as blocked` for TC-007 (the executor's own reader)",
           [(t["case"], t["decision"]) for t in read["case_tokens"]], [("TC-007", planning_contract.ACCEPT_AS_BLOCKED)])
        # --- the words of the data file, and a case with several gaps (edge 1): one waiver per gap, each by its own id ---
        for said, option in (("Change.", "apply"), ("`myself`", "theirs"), ("  RUN  ", "handed")):
            a364_take(root, env, task_root, f"- TC-007: {said}")
            eq(f"A364: `{said}` is {option}", contract.stand_gap_decisions(s0_pipeline(task_root))["PC-1"]["option"], option)
        set_control(root, {"conductor": {"action": "continue", "did": "recorded"}})
        before = len(d2_conductor_calls(root))
        driver, printed, decided, _ = a364_take(root, env, task_root, "PC-2: accept\nPC-3: myself")
        mine = a364_overrides(task_root)
        eq("A364 edge 1: two gaps of one case: one waiver for each, the block names the gap id",
           (mine["stand gap: PC-2"]["stage"], mine["stand gap: PC-3"]["stage"]), ("S5", "S5"))
        eq("A364 edge 1: and TC-008 is NOT blocked as a whole - only one of its gaps is accepted", driver.state.get("stand_accept_cases") or [], [])
        eq("A364 edge 1: no conductor was called", len(d2_conductor_calls(root)), before)
        driver, printed, decided, _ = a364_take(root, env, task_root, "PC-3: accept")
        eq("A364: ...the other gap accepted later: now every gap of the case is accepted (this answer + the earlier one on record)",
           driver.state.get("stand_accept_cases"), ["TC-008"])
        # the bare case id of a case with two gaps names none of them: the conductor (the t-342 rule), never a guess
        before = len(d2_conductor_calls(root))
        driver, printed, decided, _ = a364_take(root, env, task_root, "TC-008: accept")
        eq("A364 edge 1: the bare id of a case with two gaps goes to the conductor whole", (decided, len(d2_conductor_calls(root)) - before), ([], 1))
        check_in("A364 edge 1: and says why", "that id names more than one stand gap of this gate", d2_conductor_calls(root)[-1]["prompt"])
        # --- edge 2: a word on a case that has no gap at gate A: the conductor whole, with the note, never a waiver ---
        # B-361: the gate A answers also left the case-level records (`stand gap: TC-007`, `stand gap: TC-008`: the carries)
        for name in ("stand gap: PC-1", "stand gap: PC-2", "stand gap: PC-3", "stand gap: TC-007", "stand gap: TC-008"):
            (task_root / "pipeline.json").write_text(json.dumps(dict(
                s0_pipeline(task_root), stage_overrides=[o for o in s0_pipeline(task_root).get("stage_overrides") or []
                                                         if o["match"] != name])), encoding="utf-8")
        before = len(d2_conductor_calls(root))
        driver, printed, decided, _ = a364_take(root, env, task_root, "TC-099: accept")
        calls = d2_conductor_calls(root)[before:]
        eq("A364 edge 2: no gap of that id: the conductor is called once and the gate decision is not recorded by code", (len(calls), decided), (1, []))
        check_in("A364 edge 2: with the line and why", "TC-099: accept  [that id is not a stand gap of this gate]", calls[0]["prompt"])
        check_in("A364 edge 2: and the block key and stage of every gap of the gate (the F3 note)", "block `stand gap: PC-1`, stage S5", calls[0]["prompt"])
        eq("A364 edge 2: nothing was written as a waiver", a364_overrides(task_root), {})
        # --- the other reader's token is not an unreadable stand-gap line ---
        driver, printed, decided, _ = a364_take(root, env, task_root, "TC-099: accept as blocked")
        eq("A364: `accept as blocked` for a case with no gap card is the executor's token: recorded by code, no conductor",
           (len(decided), a364_overrides(task_root)), (1, {}))
        # --- edge 6: an unreadable LAST line of a gap's answer: the whole gap goes to the conductor ---
        before = len(d2_conductor_calls(root))
        driver, printed, decided, _ = a364_take(root, env, task_root, "PC-1: run\nPC-1: no wait, not that")
        calls = d2_conductor_calls(root)[before:]
        eq("A364 edge 6: the gap is not recorded by code and the conductor gets both lines",
           (a364_overrides(task_root), decided, len(calls)), ({}, [], 1))
        check_in("A364 edge 6: the last line", "PC-1: no wait, not that", calls[0]["prompt"])
        check_in("A364 edge 6: and the earlier one beside it", "PC-1: run", calls[0]["prompt"])
        # --- no line of the form: nothing is rehearsed, nothing is read ---
        driver, printed, decided, ran = a364_take(root, env, task_root, "approve\nthe rest in prose")
        eq("A364: an answer with no `<id>: <word>` line costs no rehearsal and is recorded whole", (ran, len(decided)), (0, 1))
        # --- the recording refuses: the person reads it in words, never the command ---
        from story_run import Person

        def refuse(script, real, *args, **kw):
            return (1, "waiver: boom - pipeline.json is locked") if script == "waiver.py" else real(script, *args, **kw)
        # D1 at gate A (C1-4b, G22): no Person asking for the answer again - the failed line goes to the conductor once
        before = len(d2_conductor_calls(root))
        raised = None
        try:
            _, _, decided, _ = a364_take(root, env, task_root, "approve\nTC-007: accept", py=refuse)
        except Person as person:
            raised = person
        eq("D1 gate A: a recording that fails raises NO Person to the person", raised, None)
        calls = d2_conductor_calls(root)[before:]
        eq("D1 gate A: one conductor call, the decision not recorded by code", (len(calls), decided), (1, []))
        check_in("D1 gate A: naming the failed line and the record's refusal", "pipeline.json is locked", calls[0]["prompt"])
    finally:
        b272_cleanup(root)


def a361_carry_at_gate_a() -> None:
    """B-361 (D-0026, FR-7): when EVERY stand gap of a case is accepted at gate A the driver writes one more record, the case's
    own (`stand gap: <case>`, stage S5, the person's line quoted), so the gate B card and the delivery check find the answer
    under the case key. Only `accept`; nothing for a partly accepted case, a changed word, a failed gap record or a precondition
    id two cases share; a failed carry is told and never asked; a changed word takes the carry back (R1b)."""
    import contract
    root, task_root, env = gate_a_story()
    try:
        # AK1: the `:823` answer gives the gap's record and the case's, both at S5
        driver, printed, decided, _ = a364_take(root, env, task_root, "TC-007: accept")
        mine = a364_overrides(task_root)
        eq("A361 AK1: the keys are the gap's and the case's, both at S5", sorted((k, v["stage"]) for k, v in mine.items()),
           [("stand gap: PC-1", "S5"), ("stand gap: TC-007", "S5")])
        check("A361 AK1: the case's decision starts `accept - the person wrote: TC-007: accept`",
              str(mine["stand gap: TC-007"]["decision"]).startswith("accept - the person wrote: TC-007: accept"), str(mine["stand gap: TC-007"]))
        eq("A361 AK1: it reads back as `accept` for the case", contract.stand_gap_decisions(s0_pipeline(task_root))["TC-007"]["option"], "accept")
        check_in("A361 AK1: and the driver says it", "gate A: TC-007: your answer is carried to gate B", printed)
        # AK2: a partly accepted case (TC-008 has PC-2 and PC-3) carries nothing; only the two gap records are written
        a364_take(root, env, task_root, "PC-2: accept")
        eq("A361 AK2: a partly accepted case is not carried", "stand gap: TC-008" in a364_overrides(task_root), False)
        # AK2: a non-accept word is not carried
        for said, option in (("Change.", "apply"), ("myself", "theirs"), ("run", "handed")):
            a364_take(root, env, task_root, f"TC-007: {said}")
            eq(f"A361 AK2: `{said}` ({option}) writes no live carry", "stand gap: TC-007" in {
                k for k, v in a364_overrides(task_root).items() if not v.get("revoked_at")}, False)
        # AK2: a failed GAP record: no carry (the carry write itself would have succeeded)
        from story_run import Person

        def refuse_gap(script, real, *args, **kw):
            blocked = script == "waiver.py" and "stand gap: PC-1" in args
            return (1, "waiver: boom - pipeline.json is locked") if blocked else real(script, *args, **kw)
        before = dict(a364_overrides(task_root))
        set_control(root, {"conductor": {"action": "continue", "did": "looked"}})
        try:
            a364_take(root, env, task_root, "approve\nTC-007: accept", py=refuse_gap)
            raised = None
        except Person as person:
            raised = person
        check("A361 AK2 (C1-4b, G22): a failed gap record no longer asks the person to send the answer again - the conductor reads it once",
              raised is None)
        eq("A361 AK2: and no carry was written for it", a364_overrides(task_root).get("stand gap: TC-007"), before.get("stand gap: TC-007"))
        # AK2: a failed CARRY write is printed and never asked
        def refuse_carry(script, real, *args, **kw):
            blocked = script == "waiver.py" and "--revoke" not in args and "stand gap: TC-007" in args
            return (1, "waiver: boom - pipeline.json is locked") if blocked else real(script, *args, **kw)
        driver, printed, decided, _ = a364_take(root, env, task_root, "TC-007: accept", py=refuse_carry)
        check_in("A361 AK2: the failed carry is told", "gate A: TC-007: the answer could not be carried to gate B (waiver: boom", printed)
        check_in("A361 AK2: and gate B is told to show its card", "gate B will show its card again", printed)
        eq("A361 AK2: it is not asked again (the gate decision was recorded by code)", len(decided), 1)
        # AK2b (R1b): `TC-007: accept`, then `TC-007: myself` revokes the carry; `accept` again makes it live again
        a364_take(root, env, task_root, "TC-007: accept")
        eq("A361 AK2b: the carry is live", a364_overrides(task_root)["stand gap: TC-007"].get("revoked_at"), None)
        driver, printed, decided, _ = a364_take(root, env, task_root, "TC-007: myself")
        revoked = a364_overrides(task_root)["stand gap: TC-007"]
        check("A361 AK2b: `TC-007: myself` revokes the carry (the entry stays, marked)", bool(revoked.get("revoked_at")), str(revoked))
        check_in("A361 AK2b: with the person's line as the reason", "the person changed their answer at gate A: TC-007: myself", str(revoked.get("revoked_decision")))
        check_in("A361 AK2b: and the driver says so", "the earlier acceptance of the whole case is taken back", printed)
        eq("A361 AK2b: so the contract reader no longer sees it", "TC-007" in contract.stand_gap_decisions(s0_pipeline(task_root)), False)
        a364_take(root, env, task_root, "TC-007: accept")
        eq("A361 AK2b: `TC-007: accept` again: live again (the replacement carries no `revoked_at`)",
           a364_overrides(task_root)["stand gap: TC-007"].get("revoked_at"), None)
        # AK2c (N4): PC-2 accept then PC-3 accept carries TC-008; then PC-2 accept + PC-3 myself revokes it and re-carries nothing (iii)
        a364_take(root, env, task_root, "PC-2: accept")
        a364_take(root, env, task_root, "PC-3: accept")
        live = lambda: {k for k, v in a364_overrides(task_root).items() if not v.get("revoked_at")}  # noqa: E731
        eq("A361 AK2c: PC-2 then PC-3 accepted: TC-008 carried, naming the earlier answer",
           ("stand gap: TC-008" in live(), "1 other stand gap(s) of this case were accepted in an earlier answer" in
            str(a364_overrides(task_root)["stand gap: TC-008"]["decision"])), (True, True))
        a364_take(root, env, task_root, "PC-2: accept\nPC-3: myself")
        eq("A361 AK2c: `PC-2: accept` + `PC-3: myself` revokes the carry and does not write it again (guard iii)",
           ("stand gap: TC-008" in live(), bool(a364_overrides(task_root)["stand gap: TC-008"].get("revoked_at"))), (False, True))
    finally:
        b272_cleanup(root)
    # B-361 (3): the writer stores `declared` - every precondition id the case declares at that moment, met or unmet, sorted - in the
    # carry; C5 opens the card again only for an id declared AFTER it. A met precondition (declared, no card, no accept) is not new.
    import stand_gaps
    root, task_root, env = gate_a_story()
    try:
        folder = task_root / "work" / "test-cases" / "workflows"
        item = lambda n, what: {"id": f"PC-{n}", "kind": "feature_flag", "what": what, "partitions": [], "remedy": A364_REMEDY,  # noqa: E731
                                "check": {"http": {"path": "/v1/config", "status": 200, "json_path": f"features.f{n}", "equals": True}}}
        text = lambda items: (f"---\nid: TC-007\ntitle: a node keeps its own state\nrequirements: R-3\npreconditions: {json.dumps(items)}\n---\n\n"  # noqa: E731
                              "## When\n1. call it\n")
        (folder / "TC-007.md").write_text(text([item(0, "already on"), item(1, "sub-workflow states are enabled")]), encoding="utf-8")
        # the stand meets PC-0: the rehearsal's gaps are PC-1 (and TC-008's) only
        rehearsal = a364_rehearsal(task_root)
        rehearsal["stand_gaps"] = [r for r in rehearsal["stand_gaps"] if r["id"] != "PC-0"]
        a364_take(root, env, task_root, "TC-007: accept", rehearsal=rehearsal)
        carry_row = a364_overrides(task_root)["stand gap: TC-007"]
        eq("A361 (3): the carry stores every id the case declares, met or unmet, sorted", carry_row.get("declared"), ["PC-0", "PC-1"])
        gap = {"id": "workflows/TC-007", "case_id": "TC-007"}
        eq("A361 (3) counter-case: a met precondition (in `declared`, no accept) does not reopen the card",
           stand_gaps.gate_b_answers(task_root, [gap])[0]["workflows/TC-007"]["change"], "")
        (folder / "TC-007.md").write_text(text([item(0, "already on"), item(1, "sub-workflow states are enabled"), item(4, "added later")]), encoding="utf-8")
        check_in("A361 (3) P8: a precondition declared AFTER the carry reopens it", "a new stand gap of this case appeared after your answer",
                 stand_gaps.gate_b_answers(task_root, [gap])[0]["workflows/TC-007"]["change"])
    finally:
        b272_cleanup(root)
    # AK2: a precondition id two cases share (PC-1 on both): `TC-007: accept` carries neither, and says why
    root, task_root, env = gate_a_story()
    try:
        item = {"id": "PC-1", "kind": "feature_flag", "what": "sub-workflow states are enabled", "partitions": [], "remedy": A364_REMEDY,
                "check": {"http": {"path": "/v1/config", "status": 200, "json_path": "features.f1", "equals": True}}}
        (task_root / "work" / "test-cases" / "workflows" / "TC-008.md").write_text(
            f"---\nid: TC-008\ntitle: another\nrequirements: R-3\npreconditions: {json.dumps([item])}\n---\n\n## When\n1. call it\n", encoding="utf-8")
        # B-414 R14 (F18): the rehearsal now names a shared precondition id per case (`PC-1@TC-007`, `PC-1@TC-008`), so the two gaps
        # never collide and the answer about TC-007 carries TC-007 alone
        driver, printed, decided, _ = a364_take(root, env, task_root, "TC-007: accept")
        eq("A361 AK2 (B-414): a shared id is qualified per case: TC-007's own gap and its case-level carry are recorded, nothing for TC-008",
           sorted(k for k in a364_overrides(task_root) if k not in ("stand gap: PC-1",)), ["stand gap: PC-1@TC-007", "stand gap: TC-007"])
        eq("A361 AK2: TC-008 is not carried by the answer about TC-007", "stand gap: TC-008" in a364_overrides(task_root), False)
        eq("A361 AK2: and TC-008's own gap is not answered", "stand gap: PC-1@TC-008" in a364_overrides(task_root), False)
    finally:
        b272_cleanup(root)
    # the guard stays for a rehearsal that still holds the RAW shared id (a rehearsal of an older build): `TC-007: accept` carries neither
    root, task_root, env = gate_a_story()
    try:
        item = {"id": "PC-1", "kind": "feature_flag", "what": "sub-workflow states are enabled", "partitions": [], "remedy": A364_REMEDY,
                "check": {"http": {"path": "/v1/config", "status": 200, "json_path": "features.f1", "equals": True}}}
        (task_root / "work" / "test-cases" / "workflows" / "TC-008.md").write_text(
            f"---\nid: TC-008\ntitle: another\nrequirements: R-3\npreconditions: {json.dumps([item])}\n---\n\n## When\n1. call it\n", encoding="utf-8")
        old = a364_rehearsal(task_root)
        old["stand_gaps"] = [dict(r, id=r["pc_id"]) for r in old["stand_gaps"]]
        driver, printed, decided, _ = a364_take(root, env, task_root, "TC-007: accept", rehearsal=old)
        eq("A361 AK2: a RAW shared gap id: no case-level record at all", sorted(k for k in a364_overrides(task_root) if k != "stand gap: PC-1"), [])
        check_in("A361 AK2: and the print line names the reason", "gate A: TC-007: the answer is not carried to gate B (its precondition id is shared with another case)", printed)
    finally:
        b272_cleanup(root)


def a369_the_gate_stores_the_doors_it_shows() -> None:
    """t-369 N-2: `rehearse` keeps the doors of the rehearsal it ran, and `gate()` stores them as `shown_doors[<gate>]` when it asks -
    with no second rehearsal. The answer's door lines are read against these."""
    from story_run import Person
    root, task_root, env = gate_a_story()
    try:
        driver = driver_for(root, env, B272_TICKET)
        result = a364_rehearsal(task_root)
        real_py, calls = driver.py, []

        def py(script, *a, **k):
            calls.append(script)
            return (0, json.dumps(result)) if script == "gate_preflight.py" else real_py(script, *a, **k)
        driver.py = py
        driver.gate_text = lambda gate: "a packet"
        driver.rehearse("A")
        try:
            driver.gate("A")
            raised = None
        except Person as person:
            raised = person
        check("N-2: gate() asks the person", raised is not None)
        eq("N-2: the doors shown are the rehearsal's, by finding id", driver.state["shown_doors"]["A"], a364_doors(result))
        eq("N-2: with the door of the card pointer in them", driver.state["shown_doors"]["A"]["case_preconditions-1"],
           [{"block": "stand gap: PC-1", "stage": "S5", "option": "any"}])
        eq("N-2: and no second rehearsal was run to find them", calls.count("gate_preflight.py"), 1)
        driver.state["last_rehearsal_doors"] = {}
        try:
            driver.gate("A")
        except Person:
            pass
        eq("N-2: a gate asked with no rehearsal behind it stores no door (every door line then goes to the conductor)",
           driver.state["shown_doors"]["A"], {})
    finally:
        b272_cleanup(root)



def main() -> None:
    run_scenarios([], [
        d3_no_delivery,
        d3_in_flight,
        d3_gate_b_experiment,
        b272_gate_b_card_in_words,
        b272_answer_by_words,
        a364_answer_at_gate_a,
        a361_carry_at_gate_a,
        a369_the_gate_stores_the_doors_it_shows,
    ])
    harness.finish("test_story_run_delivery_b")


if __name__ == "__main__":
    main()
