"""A stand gap is a card with an exact fix and four answers — at both gates, and in the guard.

TP1-15045 (22.09.2026): the automator had already found `customer-config.yaml:304-311`
and `features:subWorkflow enabled: false`, and what reached the person was the word
`blocked_by_env` and a prose sentence. There was nothing they could answer except "accepted":
no "change it, I am telling you to" and no "run it where it works".

These tests assert the four things that decision turned into: the card carries the requirement,
the case, what the test does, what is missing and the exact change; a credential is named and
never printed; a gap the person answered shows the answer instead of asking again; and the
person's recorded `apply` word opens exactly one file under `protected_app_paths`, once, while
P-00 keeps everything else — including the second write of the same decision.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check_eq, check_in, check_not_in, cleanup,  # noqa: E402
                     finish, temp_dir, use_project)

sys.path.insert(0, str(SCRIPTS))

import contract  # noqa: E402
import stand_gaps  # noqa: E402

REMEDY = {"kind": "flag", "where": "app/config/customer-config.yaml:306-311",
          "change": "enabled: true", "restart": "testproject1, testproject1-ui"}
CREDENTIAL_REMEDY = {"kind": "credential", "where": "NON_OWNER_PASSWORD",
                     "change": "set it in tests/harness/.env, the file the conftest loads"}

CASE = ("---\nid: TC-007\ntask: TP1-15045\nplan_row: TS-1\ntitle: a sub-workflow node keeps "
        "its own state\n"
        'preconditions: [{"id": "PC-1", "kind": "feature_flag", "what": "sub-workflow states are '
        'enabled", "partitions": ["P-selfref"], "remedy": ' + json.dumps(REMEDY) + ', "check": '
        '{"http": {"path": "/v1/config", "status": 200, "json_path": "features.subWorkflow", '
        '"equals": true}}}]\n---\n\n## Given\n| P-selfref |\n\n'
        "## When\n1. create a workflow with a sub-workflow node.\n\n"
        "## Then\n1. the state is SUBWORKFLOW.\n")


def project(prefix: str, case_text: str = CASE) -> Path:
    """A project parked where TP1-15045 was: one case whose precondition names its own fix,
    and an application file the factory is forbidden to touch."""
    root = temp_dir(prefix)
    task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
    (task_root / "work" / "test-cases" / "workflows").mkdir(parents=True)
    (root / "app" / "config").mkdir(parents=True)
    (root / "app" / "config" / "customer-config.yaml").write_text("features:\n  subWorkflow:\n"
                                                                  "    enabled: false\n",
                                                                  encoding="utf-8")
    (root / "app" / "src.py").write_text("x = 1\n", encoding="utf-8")
    (root / "qa-factory" / "config.json").write_text(json.dumps(
        {"schema_version": 1, "tests_root": "tests", "app_root": ".",
         "protected_app_paths": ["app"],
         "environments": [{"name": "localhost", "base_url": "http://stand.invalid:8080"}]}),
        encoding="utf-8")
    (task_root / "work" / "test-cases" / "workflows" / "TC-007.md").write_text(
        case_text, encoding="utf-8")
    (task_root / "work" / "test-plan.json").write_text(json.dumps(
        [{"id": "TS-1", "requirement_ids": ["R-3"]}]), encoding="utf-8")
    (task_root / "pipeline.json").write_text(json.dumps({"ticket": "TP1-15045"}),
                                             encoding="utf-8")
    return root


def answer(root: Path, gap: str, decision: str, at: str = "2026-09-23T10:00:00+00:00",
           stage: str = "S5") -> None:
    """The person's word, where every decision of theirs already lands."""
    path = root / "qa-factory" / "artifacts" / "TP1-15045" / "pipeline.json"
    pipeline = json.loads(path.read_text(encoding="utf-8"))
    pipeline.setdefault("stage_overrides", []).append(
        {"stage": stage, "match": f"stand gap: {gap}", "decision": decision, "at": at,
         "by": "human"})
    path.write_text(json.dumps(pipeline), encoding="utf-8")


def human_broken(text: str) -> list:
    """The rules of `human-questions.md` a text breaks once it has the answer block every question ends in."""
    import human_text
    tail = "\n---\nAnswer: write your words to a file and run\n  python story_run.py --task QA-1 --answer <file>\n"
    return [p["rule"] for p in human_text.problems(text + tail)]


WORDS = ("change", "myself", "run", "accept")      # `references/question-vocabulary.json` `stand_gap_words`, by option


def test_the_gate_a_card_carries_the_exact_change_and_four_answers() -> None:
    root = project("qa-stand-gaps-a-")
    try:
        use_project(root)
        import gate_brief
        task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
        gaps = stand_gaps.collect(task_root, "A", probe=False)
        check_eq("one precondition, one gap", [g["id"] for g in gaps], ["PC-1"])
        card = stand_gaps.render(gaps)
        check_in("the case it costs and the requirement are named first (t-357: the gate B heading)",
                 "Stand gap: TC-007 (P-selfref) — needs R-3", card)
        check_in("what the test tries to do, in the case's own words",
                 "the test: a sub-workflow node keeps its own state", card)
        check_in("what is missing, with the stand it is missing on",
                 "feature flag: sub-workflow states are enabled", card)
        check_in("and the name of the stand", "(on localhost)", card)
        check_in("the exact change, file and lines",
                 "the fix:  app/config/customer-config.yaml:306-311 -> enabled: true", card)
        check_in("with what to restart afterwards", "restart testproject1, testproject1-ui", card)
        check_in("the one form of the answer", "write a line of its own: `<case id or level name>: <word>`, for example `TC-007: accept`", card)
        rows = gate_brief.stand_gap_words()
        check_eq("t-357: the words are the data file's four, in the record's order",
                 ([r["option"] for r in rows], [r["word"] for r in rows]), (list(contract.STAND_GAP_OPTIONS), list(WORDS)))
        for row in rows:
            check_in(f"the word `{row['word']}` is offered with its explanation", f"- `{row['word']}` — {row['says']}", card)
        check_in("handing it over says what the person does, in words: they run the test where the missing piece exists",
                 "- `run` — you run this test yourself, where the missing piece exists", card)
        for banned in ("handed", "apply", "theirs", "waiver.py", "--block", "--decision", "--stage", "stand gap:", "(a)", "(d)"):
            check_not_in(f"t-357: the gate A card never shows {banned!r} to a person", banned, card)
        # FR-10: gate A and gate B are one renderer - the same gap is told the same way at both gates
        check_eq("t-357: `stand_gaps.render` IS `gate_brief.stand_gap_card_lines` (one text for both gates)",
                 card, "\n".join(gate_brief.stand_gap_card_lines(None, gaps, None, limit=None)) + "\n")
        lines, ids = gate_brief.stand_gap_cards(task_root, "A",
                                                {"stand_gaps": stand_gaps.declared_preconditions(task_root)})
        check_in("and the packet's gate A block carries the same card", "Stand gap: [TC-007](", "\n".join(lines))
        check_eq("t-357: the packet's card and the CLI's card differ only by the case file link",
                 "\n".join(lines).replace("[TC-007](qa-factory/artifacts/TP1-15045/work/test-cases/workflows/TC-007.md)", "TC-007"),
                 card.rstrip("\n"))
        # the `the fix:` line is the remedy the ROLE wrote (`enabled: true` is the config line itself, which the rule on
        # a field with its machine value would call jargon): every other line is ours and must be clean
        ours = "\n".join(line for line in lines if not line.startswith("  the fix:"))
        check_eq("t-357: the card obeys human-questions.md (human_text.problems == [] over every line the factory writes)",
                 human_broken("A packet whose body is long enough to stand on its own feet.\n\n" + ours), [])
        # NEGATIVE control: the same checker must fail on the card this one replaced, or the key above proves nothing
        old = card.replace("Stand gap: TC-007", 'waiver.py --task TP1-15045 --stage S5 --block "stand gap: PC-1"\nStand gap: TC-007')
        check_in("t-357 control: a planted `waiver.py` in the card is caught by the same check", "script_name",
                 human_broken("A packet whose body is long enough to stand on its own feet.\n\n" + old))
        check_in("t-357 control: and its flag", "flag",
                 human_broken("A packet whose body is long enough to stand on its own feet.\n\n" + old))
    finally:
        cleanup(root)


def test_gate_a_cards_of_one_case_and_more_than_three_and_the_answers_that_read() -> None:
    """t-357 edge keys of the shared renderer, AT and BEYOND its limits: two gaps of one case (named by their own ids),
    the fourth gap and beyond (one line each, the same words), and the line `<id>: <word>` read at gate A by the SAME
    reader as at gate B (`gate_brief.read_stand_gap_answers`)."""
    import gate_brief

    def gap(gid, case, missing, remedy=None):
        return {"id": gid, "gate": "A", "stage": "S5", "case": case, "case_id": case, "requirement": "R-3",
                "partitions": [], "the_test": "a test", "missing": missing, "remedy": REMEDY if remedy is None else remedy,
                "task": "TP1-15045"}
    two = [gap("PC-1", "TC-007", "flag A"), gap("PC-2", "TC-007", "flag B")]
    card = stand_gaps.render(two)
    check_in("two gaps of one case: each is headed by its own id and says which case it costs",
             "Stand gap: PC-1 (case TC-007) — needs R-3", card)
    check_in("...the second too", "Stand gap: PC-2 (case TC-007) — needs R-3", card)
    check_in("...and the line says to start with what the card is headed by",
             "start the line with exactly what the card is headed by", card)
    check_not_in("a case with ONE gap is headed by its case id and the sentence is absent",
                 "start the line with exactly what the card is headed by", stand_gaps.render(two[:1]))
    found = gate_brief.read_stand_gap_answers("PC-1: change\nPC-2: run", two)
    check_eq("gate A: the person's line is read by the gate B reader - each gap by its own id",
             [(e["gap"]["id"], e["option"]) for e in found["read"]], [("PC-1", "apply"), ("PC-2", "handed")])
    found = gate_brief.read_stand_gap_answers("TC-007: accept", two)
    check_eq("gate A: the case id of a case with two gaps names no ONE gap: unread, said so, never guessed",
             ([e["gap"]["id"] for e in found["read"]], [u["why"] for u in found["unread"]]),
             ([], ["that id names more than one stand gap of this gate"]))
    found = gate_brief.read_stand_gap_answers("PC-1: change", [gap("PC-1", "TC-007", "flag A", remedy={})])
    check_eq("gate A: `change` for a gap whose card shows no exact change is unread (it was never offered)",
             (found["read"], len(found["unread"])), ([], 1))
    five = [gap(f"PC-{n}", f"TC-0{n}0", f"missing piece {n}") for n in range(1, 6)]
    card = stand_gaps.render(five, limit=3)
    check_in("five gaps: counted", "## Stand gaps (5)", card)
    check_eq("AT the limit: three are cards", card.count("Stand gap: "), 3)
    check_in("BEYOND it: the rest are listed one line each, with what is missing", "- TC-050 — needs R-3: missing piece 5", card)
    check_not_in("and no command is named to see them (t-357)", "stand_gaps.py", card)
    check_eq("`limit=None` (the command line) shows every card in full", stand_gaps.render(five).count("Stand gap: "), 5)
    check_eq("no gap, no text", stand_gaps.render([]), "")


def test_a_credential_is_named_and_never_printed() -> None:
    root = project("qa-stand-gaps-credential-",
                   CASE.replace(json.dumps(REMEDY), json.dumps(CREDENTIAL_REMEDY)))
    try:
        use_project(root)
        task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
        card = stand_gaps.render(stand_gaps.collect(task_root, "A", probe=False))
        check_in("the variable name and the file it goes into",
                 "NON_OWNER_PASSWORD -> set it in tests/harness/.env", card)
        check_not_in("no value of anything reaches the card", "=hunter", card)
        check_eq("a value that did reach a detail is reduced to its name",
                 stand_gaps.names_only("NON_OWNER_PASSWORD=hunter2 is missing"),
                 "NON_OWNER_PASSWORD=<value not printed> is missing")
    finally:
        cleanup(root)


def test_an_answered_gap_shows_the_answer_instead_of_asking_again() -> None:
    root = project("qa-stand-gaps-answered-")
    try:
        use_project(root)
        task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
        answer(root, "PC-1", "handed - I will run it on the dev stand")
        gaps = stand_gaps.collect(task_root, "A", probe=False)
        decided = stand_gaps.decisions(task_root)
        check_eq("the option is read from the person's first word",
                 decided["PC-1"]["option"], "handed")
        card = stand_gaps.render(gaps, decided)
        check_in("their answer is repeated back, as the word they would have written (t-357: never `handed`)",
                 "  answered: run (2026-09-23T10:00:00+00:00)", card)
        check_not_in("the driver's own bookkeeping sentence is not read back to them", "I will run it on the dev stand", card)
        check_not_in("and the four options are not asked a second time", "To answer a stand gap", card)
        check_not_in("nor the word `handed`", "handed", card)
    finally:
        cleanup(root)


def test_the_gate_b_card_replaces_the_raw_manifest_row() -> None:
    root = project("qa-stand-gaps-b-")
    try:
        use_project(root)
        import gate_brief
        task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
        (task_root / "work" / "automation-manifest.json").write_text(json.dumps(
            {"unresolved": [{"case": "workflows/TC-007", "reason": "blocked_by_env",
                             "detail": "features.subWorkflow is false", "remedy": REMEDY,
                             "owner": "user"}]}), encoding="utf-8")
        gaps = stand_gaps.collect(task_root, "B")
        check_eq("the gap id at gate B is the case key", [g["id"] for g in gaps],
                 ["workflows/TC-007"])
        check_eq("and the answer is recorded against S9", gaps[0]["stage"], "S9")
        card = stand_gaps.render(gaps)
        check_in("the manifest's own detail becomes the missing line",
                 "missing:  features.subWorkflow is false", card)
        check_in("with the same exact change", "-> enabled: true", card)
        cards, carded = gate_brief.stand_gap_cards(task_root, "B")
        check_in("the packet carries the card", "## Stand gaps (1)", cards)
        check_eq("and knows which row it now states itself", carded, ["workflows/TC-007"])
        lines = gate_brief.open_before_mr(task_root, "B", tuple(carded))
        check_not_in("so the raw manifest line is not repeated under it",
                     "not automated: blocked_by_env", lines)
        check_in("while the same row without a card is still a loose end",
                 "not automated: blocked_by_env",
                 gate_brief.open_before_mr(task_root, "B"))
    finally:
        cleanup(root)


def test_the_gate_b_card_says_when_a_blocked_test_ran_red() -> None:
    """t-219 F3 (critic t-243, P20 / FR-10): a red parked as `blocked_by_env` shows `ran red: <reason>` on its card.

    The person who answers the card is the last reader who can say "that failure is the product's"; a card that
    reads like a test that never got to run hides it. The text is `acceptance.ran_red`'s (60 characters, an
    ellipsis, "(no reason recorded)" for an empty one); an instance that never ran, or whose latest run passed,
    gets no mark; a row that names no instance speaks only of a case with exactly one."""
    root = project("qa-stand-gaps-ran-red-")
    try:
        use_project(root)
        task_root = root / "qa-factory" / "artifacts" / "TP1-15045"

        def test(iid: str) -> dict:
            return {"case": "TC-007", "instance_id": iid, "covers": ["TC-007"], "test": iid}

        def block(name: str, *results) -> None:
            path = task_root / "work" / "run-blocks" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"attempt_started_at": "2026-10-01T10:00:00Z", "results": list(results)}),
                            encoding="utf-8")

        def card_of(rows, tests, *results, reason="blocked_by_env"):
            for old in (task_root / "work" / "run-blocks").glob("*.json"):
                old.unlink()
            if results:
                block("20261001T100000000000Z-aaaa.json", *results)
            (task_root / "work" / "automation-manifest.json").write_text(json.dumps(
                {"tests": tests, "unresolved": [dict(r, reason=reason) for r in rows]}), encoding="utf-8")
            gaps = stand_gaps.collect(task_root, "B")
            return gaps[0]["ran_red"], stand_gaps.render(gaps)

        row = {"case": "workflows/TC-007", "detail": "the page stayed on Loading", "remedy": REMEDY}
        failed = {"instance_id": "t[a]", "status": "failed", "reason": "AssertionError: Locator expected to be visible"}
        mark, card = card_of([dict(row, instance_ids=["t[a]", "t[b]"])], [test("t[a]"), test("t[b]")], failed)
        check_eq("F3: the instance ran and failed: the mark is `ran red: <reason>`",
                 mark, "ran red: AssertionError: Locator expected to be visible")
        check_in("F3: and it is on the card, beside the missing line", "  ran red: AssertionError: Locator", card)
        check_in("F3: the card keeps the detail, the fix and the four answers",
                 "missing:  the page stayed on Loading", card)
        check_in("F3: the exact change is still there", "-> enabled: true", card)
        mark, card = card_of([dict(row, instance_ids=["t[b]"])], [test("t[a]"), test("t[b]")], failed)
        check_eq("F3: the row names the instance that NEVER ran: no mark, not the sibling's", mark, "")
        check_not_in("F3: and no `ran red` on the card", "ran red", card)
        mark, _ = card_of([dict(row, instance_ids=["t[a]"])], [test("t[a]")],
                          dict(failed, reason="r" * 70))
        check_eq("F3: a reason past 60 characters is cut at 60 with an ellipsis", mark, "ran red: " + "r" * 60 + "…")
        mark, _ = card_of([dict(row, instance_ids=["t[a]"])], [test("t[a]")], dict(failed, reason=""))
        check_eq("F3: an empty reason says so", mark, "ran red: (no reason recorded)")
        mark, _ = card_of([dict(row, instance_ids=["t[a]"])], [test("t[a]")], dict(failed, status="passed"))
        check_eq("F3: the latest run PASSED: no mark", mark, "")
        mark, _ = card_of([dict(row, instance_ids=["t[a]", "t[b]"])], [test("t[a]"), test("t[b]")],
                          failed, dict(failed, instance_id="t[b]", reason="TimeoutError: page.goto"))
        check_eq("F3: two failed instances: both marks, once each, in the row's order",
                 mark, "ran red: AssertionError: Locator expected to be visible; ran red: TimeoutError: page.goto")
        mark, _ = card_of([dict(row, instance_ids=["t[a]", "t[b]"])], [test("t[a]"), test("t[b]")],
                          failed, dict(failed, instance_id="t[b]"))
        check_eq("F3: two failed instances with ONE reason: one mark", mark,
                 "ran red: AssertionError: Locator expected to be visible")
        mark, _ = card_of([row], [test("t[a]")], failed)
        check_eq("F3: a row naming no instance on a case with exactly one: that instance's mark",
                 mark, "ran red: AssertionError: Locator expected to be visible")
        mark, _ = card_of([row], [test("t[a]"), test("t[b]")], failed)
        check_eq("F3: a row naming none on a case with TWO instances: never guessed at, no mark", mark, "")
        mark, _ = card_of([dict(row, instance_ids=["t[a]"])], [test("t[a]")])
        check_eq("F3: no run block at all: no mark and no crash", mark, "")
        mark, card = card_of([dict(row, instance_ids=["t[a]"])], [test("t[a]")], failed, reason="handed_to_person")
        check_eq("F3: a row of another reason (handed) with a failed run: no mark", mark, "")
        check_not_in("F3: and none on its card", "ran red", card)
        mark, _ = card_of([dict(row, instance_ids=["t[ghost]"])], [test("t[a]")], failed)
        check_eq("F3: a row naming an instance the manifest does not hold and no run knows: no mark", mark, "")
    finally:
        cleanup(root)


def test_the_rehearsal_hands_the_gap_over_instead_of_spelling_it_out() -> None:
    """The rehearsal still says a question is open — it just stops making the person decode it."""
    root = project("qa-stand-gaps-rehearsal-")
    try:
        use_project(root)
        import gate_brief
        import gate_preflight
        task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
        real = gate_preflight.http_get
        gate_preflight.http_get = lambda url, timeout_s: (
            200, json.dumps({"features": {"subWorkflow": False}}))
        try:
            result = gate_preflight.run(task_root, "A")
            check_eq("the stand's answer travels with the gap",
                     [g["id"] for g in result["stand_gaps"]], ["PC-1"])
            check_in("with what the stand really said",
                     "`features.subWorkflow` is false", result["stand_gaps"][0]["detail"])
            finding = [f for f in result["findings"] if f["check"] == "case_preconditions"]
            check_eq("and the finding left behind is one line", len(finding), 1)
            check_in("that points at the card instead of restating it",
                     "the exact change is known, so this is a card at this gate", finding[0]["message"])
            check_eq("the question is still the person's", finding[0]["class"],
                     gate_preflight.PERSON_DECIDES)
            cards, _ = gate_brief.stand_gap_cards(task_root, "A", result)
            check_in("the gate-A packet carries the card itself", "## Stand gaps (1)", cards)
            check_in("with the exact change on it", "306-311 -> enabled: true", cards)

            answer(root, "PC-1", "apply - turn the flag on")
            after = gate_preflight.run(task_root, "A")
            check_eq("and one recorded word closes the question",
                     [f for f in after["findings"] if f["check"] == "case_preconditions"], [])
            check_eq("while the card stays, now showing the answer",
                     [g["id"] for g in after["stand_gaps"]], ["PC-1"])
            check_in("as the word they gave (t-357)",
                     "  answered: change (2026-09-23T10:00:00+00:00)",
                     gate_brief.stand_gap_cards(task_root, "A", after)[0])
        finally:
            gate_preflight.http_get = real
    finally:
        cleanup(root)


def test_t357_a_gate_a_packet_from_a_fixture_breaks_no_rule_of_human_questions() -> None:
    """The gate A packet as the person reads it - the card block, then the rehearsal text - over a story with one unmet
    precondition: `human_text.problems == []` (script, flag, exit code, block id, dispatch id, unexplained case id), and the
    same checker FAILS on the packet this one replaced (a planted `waiver.py` and the word `handed`)."""
    root = project("qa-stand-gaps-packet-",
                   CASE.replace(json.dumps(REMEDY), json.dumps(dict(REMEDY, change="turn the sub-workflow flag on"))))
    try:
        use_project(root)
        import gate_brief
        import gate_preflight
        task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
        real = gate_preflight.http_get
        gate_preflight.http_get = lambda url, timeout_s: (200, json.dumps({"features": {"subWorkflow": False}}))
        try:
            result = gate_preflight.run(task_root, "A")
            cards, _ids = gate_brief.stand_gap_cards(task_root, "A", result)
        finally:
            gate_preflight.http_get = real
        packet = ("The plan is ready and one stand gap waits for your word before the tests are written.\n\n"
                  + "\n".join(cards) + "\n\n## Rehearsal of gate A\n" + gate_preflight.render(result))
        check_in("the packet carries the card and the finding that points at it", "the exact change is known, so this is a card at this gate", packet)
        check_in("...and the door of that finding is in words", "fix: answer the card: write the line it shows, with one of the words it lists", packet)
        check_eq("t-357: the whole gate A packet obeys human-questions.md (human_text.problems == [])", human_broken(packet), [])
        planted = packet + '\n  answer:   waiver.py --task TP1-15045 --stage S5 --block "stand gap: PC-1" --decision "handed"\n'
        check_in("t-357 control: the same check fails on a packet that still carries the command", "script_name", human_broken(planted))
        check_in("t-357 control: ...and its flag", "flag", human_broken(planted))
        check_not_in("the word `handed` is never said to the person at gate A", "handed", packet)
        print("GATE A PACKET (t-357 fixture):\n" + packet)
    finally:
        cleanup(root)


def test_t357_the_command_line_prints_the_same_card_in_words() -> None:
    """`stand_gaps.py --gate A|B` is the third reader of the card: the same words, every card in full, no command."""
    import contextlib
    import io
    root = project("qa-stand-gaps-cli-")
    try:
        use_project(root)
        import gate_preflight
        task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
        real, argv = gate_preflight.http_get, sys.argv
        gate_preflight.http_get = lambda url, timeout_s: (200, json.dumps({"features": {"subWorkflow": False}}))
        try:
            printed, codes = {}, {}
            for gate in ("A", "B"):
                out = io.StringIO()
                sys.argv = ["stand_gaps.py", "--task-root", str(task_root), "--gate", gate]
                with contextlib.redirect_stdout(out):
                    codes[gate] = stand_gaps.main()
                printed[gate] = out.getvalue()
        finally:
            gate_preflight.http_get, sys.argv = real, argv
        check_eq("the command line answers both gates with exit 0", codes, {"A": 0, "B": 0})
        check_in("gate A: the card, headed as the packet heads it, the case linked to its file",
                 "Stand gap: [TC-007](qa-factory/artifacts/TP1-15045/work/test-cases/workflows/TC-007.md) (P-selfref) — needs R-3", printed["A"])
        check_in("gate A: the one form", "write a line of its own: `<case id or level name>: <word>`", printed["A"])
        for banned in ("waiver.py", "--block", "--decision", "handed", "stand gap:"):
            check_not_in(f"t-357: the command line never prints {banned!r}", banned, printed["A"])
        check_eq("gate B of a story with no stand gap says so in one line", printed["B"], "No stand gap at gate B for TP1-15045.\n")
    finally:
        cleanup(root)


def test_t357_open_before_mr_lists_what_is_undecided_without_a_script_or_a_field_name() -> None:
    """`gate_brief.open_before_mr` repeats the rehearsal's questions as `not decided: <message>` (and the MR description
    repeats them again): the message of the delivery check used to say `delivery_ready is not yes` and
    `check_delivery.py has not run`."""
    import human_text
    root = project("qa-stand-gaps-open-")
    try:
        use_project(root)
        import gate_brief
        task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
        text = "\n".join(gate_brief.open_before_mr(task_root, "B"))
        check_in("what is not decided is listed, in words",
                 "- not decided: the delivery is not ready: the delivery check has not run", text)
        for banned in ("check_delivery.py", "delivery_ready", "waiver.py", "--"):
            check_not_in(f"t-357: the list names no {banned!r}", banned, text)
        check_eq("t-357: and breaks no rule of the owner's list (human_text.problems)",
                 [p["rule"] for p in human_text.problems(text, kind="report") if p["rule"] in ("script_name", "flag", "exit_code")], [])
        check_in("control: the checker is awake - the old message is caught",
                 "script_name", [p["rule"] for p in human_text.problems("- not decided: delivery_ready is not yes: check_delivery.py has not run",
                                                                         kind="report")])
    finally:
        cleanup(root)


def test_a_remedy_of_the_wrong_shape_is_a_shape_error_not_a_card() -> None:
    root = project("qa-stand-gaps-shape-")
    try:
        use_project(root)
        import gate_preflight
        items, errors = gate_preflight.parse_preconditions(
            '[{"id": "PC-1", "kind": "feature_flag", "what": "x", "check": {"env": "A"}, '
            '"remedy": {"kind": "whatever", "where": "", "change": "y"}}]')
        check_in("the closed list of kinds is named", "remedy.kind must be one of", errors)
        check_in("and the empty field", "remedy.where is empty", errors)
        check_eq("a precondition with no remedy at all is still legal",
                 gate_preflight.parse_preconditions(
                     '[{"id": "PC-1", "kind": "env", "what": "x", "check": {"env": "A"}}]')[1], [])
    finally:
        cleanup(root)


# --- option (a): the one write P-00 lets through ------------------------------------------

def write_event(root: Path, target: str, agent: str = "") -> dict:
    event = {"tool_name": "Write", "cwd": str(root),
             "tool_input": {"file_path": str(root / target), "content": "enabled: true\n"}}
    if agent:
        event["agent_type"] = agent
    return event


def guarded(event: dict) -> tuple:
    """(exit code or None, what the guard said) for one call. Nothing here spawns a process:
    the guard is a function, and a test that shelled out would not see its stderr as a hook
    does. What it said is its stderr plus the notes of the `hook_signal` rows it wrote in the call (RH1-5, H9: a pass
    is recorded for the person, not printed at exit 0); the rows are in `guarded.rows`."""
    import io
    import contextlib
    import guard_app_under_test
    from hooklib import load_config, read_json
    import runtime_paths as RP

    def rows() -> list:
        root = Path(event["cwd"])
        path = RP.configured(root, read_json(root / "qa-factory" / "config.json", {}, kind=dict).get("journal_path"), "journal.jsonl")
        lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
        return [r for r in (json.loads(x) for x in lines if x.strip()) if r.get("event") == "hook_signal"]

    before = len(rows())
    err = io.StringIO()
    code = None
    try:
        with contextlib.redirect_stderr(err):
            guard_app_under_test.check(event, load_config(event))
    except SystemExit as exc:
        code = exc.code
    guarded.rows = rows()[before:]
    return (code, "\n".join([err.getvalue()] + [str(r.get("notes") or "") for r in guarded.rows]))


guarded.rows = []


def test_the_persons_word_opens_exactly_one_file_once() -> None:
    root = project("qa-stand-gaps-apply-")
    try:
        use_project(root)
        target = "app/config/customer-config.yaml"
        code, said = guarded(write_event(root, target))
        check_eq("with no decision recorded, P-00 blocks the change", code, 2)
        check_in("in the words it has always used", "APP-UNDER-TEST BOUNDARY", said)

        answer(root, "PC-1", "apply - turn the flag on, it is our own stand")
        code, said = guarded(write_event(root, target))
        check_eq("on the person's recorded word the one file opens", code, None)
        check_in("and the guard says which decision passed it",
                 "passed by your decision on stand gap PC-1", said)
        check_in("quoting their own words", "apply - turn the flag on", said)
        check_eq("...recorded as ONE journal signal of kind pass_recorded (the pin moved from stderr to the journal)",
                 [r.get("kind") for r in guarded.rows], ["pass_recorded"])

        code, said = guarded(write_event(root, "app/src.py"))
        check_eq("every other application file stays closed", code, 2)
        check_not_in("and is not passed by that decision", "passed by your decision", said)

        code, said = guarded(write_event(root, target))
        check_eq("the same decision opens the file once, not twice", code, 2)
        # t-427 N10: the guard's door is the first-word form with the words in a file (carrier: t-428),
        # not the inline `--decision`; what this file holds it to is the gap to record again and the word
        # that opens a file again
        check_in("and says how a second word would open it again",
                 '--block "stand gap: PC-1"', said)
        check_in("in the first-word form", "apply - the person wrote:", said)

        answer(root, "PC-1", "apply, once more: set it under features, not featureFlags",
               at="2026-09-23T11:00:00+00:00")
        code, said = guarded(write_event(root, target))
        check_eq("a person's word passes any block, including this one", code, None)
    finally:
        cleanup(root)


def test_a_role_never_changes_the_application_even_on_that_word() -> None:
    root = project("qa-stand-gaps-role-")
    try:
        use_project(root)
        answer(root, "PC-1", "apply - turn the flag on")
        code, said = guarded(write_event(root, "app/config/customer-config.yaml",
                                         agent="qa-automator"))
        check_eq("a dispatched role is refused as before", code, 2)
        check_not_in("the decision is the orchestrator's to carry out, not a role's",
                     "passed by your decision", said)
    finally:
        cleanup(root)


def test_only_an_apply_answer_opens_anything() -> None:
    root = project("qa-stand-gaps-other-options-")
    try:
        use_project(root)
        for words in ("theirs - I will change it myself", "accept - leave it blocked",
                      "handed - I will run it elsewhere"):
            path = root / "qa-factory" / "artifacts" / "TP1-15045" / "pipeline.json"
            pipeline = json.loads(path.read_text(encoding="utf-8"))
            pipeline["stage_overrides"] = []
            path.write_text(json.dumps(pipeline), encoding="utf-8")
            answer(root, "PC-1", words)
            code, _ = guarded(write_event(root, "app/config/customer-config.yaml"))
            check_eq(f"`{words.split()[0]}` changes nothing in the application", code, 2)
    finally:
        cleanup(root)


def test_a_revoked_apply_opens_nothing() -> None:
    """t-427 N4: an answer the person revoked (`revoked_at` on its record) is read by nobody
    (`contract.stand_gap_decisions`), so `apply_grant` finds no grant for it and the guard keeps
    the application closed. The live record before the revocation is the positive control (read
    through `apply_grant` itself: the guard's one-write receipt would hide a second call)."""
    root = project("qa-stand-gaps-revoked-")
    try:
        use_project(root)
        target = "app/config/customer-config.yaml"
        artifacts = root / "qa-factory" / "artifacts"
        answer(root, "PC-1", "apply - turn the flag on")
        control = stand_gaps.apply_grant(str(root / target), root, root / "app", artifacts)
        check_eq("control: the live apply record is a grant for the one file", control.get("gap"), "PC-1")
        path = artifacts / "TP1-15045" / "pipeline.json"
        pipeline = json.loads(path.read_text(encoding="utf-8"))
        pipeline["stage_overrides"][-1]["revoked_at"] = "2026-09-24T09:00:00+00:00"
        path.write_text(json.dumps(pipeline), encoding="utf-8")
        check_eq("a revoked `apply` is no grant",
                 stand_gaps.apply_grant(str(root / target), root, root / "app", artifacts), {})
        code, _ = guarded(write_event(root, target))
        check_eq("and the guard keeps the application closed", code, 2)
    finally:
        cleanup(root)


# --- B-414 (D-0029, D-0032): level gaps, the environment record at gate B, qualified precondition ids ----------------------

ARGV = ["python", "runner.py", "{report_path}", "<test-id>"]
LEVEL_ROW = {"id": "RP-web", "case": "", "scope": "level", "contour": "web", "cases": ["TC-001", "TC-002"], "kind": "reporter",
             "reason_class": "zero_tests", "exit_code": 0, "what": "web writes no report", "partitions": [], "state": "unmet",
             "remedy": {"kind": "reporter", "where": "qa-factory/config.json:profiles[web].commands.one_test",
                        "where_words": "qa-factory/config.json, the command that runs one web test", "change": "name the flag",
                        "profile": "web", "offers": ["theirs", "handed", "accept"]}, "detail": ""}


def level_story(prefix: str):
    """(root, task root, the EP row): two cases keyed to the contour `web`, a blocked row each, the environment record holding
    ONE level row for the command, and the overrides the driver writes when it carries the record into the story."""
    import environment_record as ER
    root = temp_dir(prefix)
    task_root = root / "qa-factory" / "artifacts" / "T-414"
    (task_root / "work" / "test-cases").mkdir(parents=True)
    for case in ("TC-001", "TC-002"):
        (task_root / "work" / "test-cases" / f"{case}.md").write_text(f"---\nid: {case}\ntitle: {case} works\n---\n\n## When\n1. x\n", encoding="utf-8")
    config = {"schema_version": 1, "tests_root": "tests", "app_root": ".",
              "environments": [{"name": "QA", "base_url": "http://qa.invalid"}],
              "profiles": [{"profile_id": "web", "commands": {"one_test": {"argv": ARGV, "cwd": "."}}}]}
    (root / "qa-factory" / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (task_root / "work" / "automation-manifest.json").write_text(json.dumps({"tests": [], "unresolved": [
        {"case": c, "reason": "blocked_by_env", "owner": "user", "detail": "no report", "remedy": LEVEL_ROW["remedy"]}
        for c in ("TC-001", "TC-002")]}), encoding="utf-8")
    (task_root / "pipeline.json").write_text(json.dumps({"ticket": "T-414", "environment": "QA"}), encoding="utf-8")
    use_project(root)
    key = ER.property_key(LEVEL_ROW, config, "QA")
    ep, problem, _created = ER.record(root, key, "accept", "web: accept always", "T-0", "the web tests")
    return root, task_root, ep


def env_overrides(task_root: Path, ep: dict, by: str = "environment-record", level: bool = True, carries: bool = True, **extra) -> None:
    """The records `Driver.carry_environment_properties` writes: the level gap's own override and the case-key carry of each case."""
    path = task_root / "pipeline.json"
    pipeline = json.loads(path.read_text(encoding="utf-8"))
    prop = [{"id": ep["id"], "subject": ep["subject"]}]
    rows = ([("RP-web", {})] if level else []) + ([(c, {"declared": []}) for c in ("TC-001", "TC-002")] if carries else [])
    pipeline["stage_overrides"] = [dict({"stage": "S5", "match": f"stand gap: {gap}", "by": by, "at": "2026-10-05T11:00:00+00:00",
                                         "decision": "accept - the person wrote: web: accept always (recorded for this environment)",
                                         "property": prop}, **fields, **extra) for gap, fields in rows]
    path.write_text(json.dumps(pipeline), encoding="utf-8")


def test_b414_a_level_gap_says_why_about_the_command_and_a_case_gap_about_the_stand() -> None:
    root = project("qa-stand-gaps-b414-r2-")
    try:
        use_project(root)
        task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
        level = stand_gaps._gate_a_gaps(task_root, [LEVEL_ROW])[0]
        check_in("R2: a level gap says it is about the command recorded now", "(with the command recorded now)", level["missing"])
        check_not_in("R2: and never says it is on a stand", "(on ", level["missing"])
        check_eq("R2: it is about every test of the contour", level["the_test"], "every web test of this story")
        check_eq("R2: scope, contour, cases and reason class pass through", (level["scope"], level["contour"], level["cases"], level["reason_class"], level["case_id"]),
                 ("level", "web", ["TC-001", "TC-002"], "zero_tests", ""))
        case = stand_gaps.collect(task_root, "A", probe=False)[0]
        check_in("R2: a case gap says which stand it is missing on", "(on localhost)", case["missing"])
        check_eq("R2: and carries the stand's name for the card's lasting question", case["stand"], "localhost")
    finally:
        cleanup(root)


def test_b414_gate_b_covers_a_level_row_only_while_every_rule_holds() -> None:
    import environment_record as ER
    import gate_brief
    root, task_root, ep = level_story("qa-stand-gaps-b414-b-")
    try:
        env_overrides(task_root, ep)
        asked, covered = stand_gaps.gate_b_split(task_root)
        check_eq("R7: both rows are covered - nothing is asked", [g["id"] for g in asked], [])
        check_eq("R7: one covered LEVEL gap, with its cases and the record's row",
                 [(g["id"], g["scope"], g["contour"], g["cases"], g["property"]["id"]) for g in covered], [("RP-web", "level", "web", ["TC-001", "TC-002"], "EP-1")])
        lines = gate_brief.stand_gap_cards(task_root, "B")[0]
        check_in("R3: the packet holds the covered block", "## Decided once for this environment (1)", lines)
        check_not_in("R3: and no card (the covered rows are not asked)", "## Stand gaps", lines)
        check_eq("R7: `gate_b_gaps` - the list the answers are read against - holds no covered row", gate_brief.gate_b_gaps(task_root), [])
        # a row that RAN RED is carded whatever the record says (D-0026: a red run is always asked)
        rows = stand_gaps.collect(task_root, "B")
        rows[0]["ran_red"] = "ran red: the node lost its state"
        asked, covered = stand_gaps.gate_b_split(task_root, rows)
        check_eq("R7: a row with `ran_red` is carded, the other stays covered", ([g["id"] for g in asked], [g["cases"] for g in covered]), (["TC-001"], [["TC-002"]]))
        # the carry is not the record's: asked
        env_overrides(task_root, ep, by="human")
        check_eq("R7: a carry whose `by` is another's is not the record's: both asked", [g["id"] for g in stand_gaps.gate_b_split(task_root)[0]], ["TC-001", "TC-002"])
        # no gap-level override in this story
        env_overrides(task_root, ep, level=False)
        check_eq("R7: no override of the level gap in THIS story: asked", len(stand_gaps.gate_b_split(task_root)[0]), 2)
        # no carry for the cases: asked
        env_overrides(task_root, ep, carries=False)
        check_eq("R7: no carry of the cases: asked", len(stand_gaps.gate_b_split(task_root)[0]), 2)
        # the record taken back in another story reopens the rows (C4, E8)
        env_overrides(task_root, ep)
        check_eq("control: with the overrides back, covered again", len(stand_gaps.gate_b_split(task_root)[1]), 1)
        ER.revoke(root, "EP-1", "ask again")
        asked, covered = stand_gaps.gate_b_split(task_root)
        check_eq("E8/C4: a record taken back reopens both rows, and says why", ([g["id"] for g in asked], covered), (["TC-001", "TC-002"], []))
        answers, _had = stand_gaps.gate_b_answers(task_root, asked)
        check_in("C4: the card's words say the recorded property no longer holds", "the recorded environment property no longer holds (it was taken back)", answers["TC-001"]["change"])
        # an unreadable record covers nothing
        ER.record_path(root).write_text("{broken", encoding="utf-8")
        check_eq("E9: an unreadable record covers nothing: asked", (len(stand_gaps.gate_b_split(task_root)[0]), stand_gaps.gate_b_split(task_root)[1]), (2, []))
    finally:
        cleanup(root)


def test_b414_a_shared_precondition_id_is_qualified_per_case_and_counted_over_raw_ids() -> None:
    def pre(n: int, what: str) -> str:
        item = {"id": f"PC-{n}", "kind": "feature_flag", "what": what, "partitions": [], "remedy": REMEDY,
                "check": {"http": {"path": "/v1/config", "status": 200, "json_path": f"features.f{n}", "equals": True}}}
        return json.dumps([item])
    root = project("qa-stand-gaps-b414-r14-")
    try:
        use_project(root)
        task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
        folder = task_root / "work" / "test-cases" / "workflows"
        (folder / "TC-007.md").write_text(f"---\nid: TC-007\npreconditions: {pre(1, 'a')}\n---\n\n## When\n1. x\n", encoding="utf-8")
        (folder / "TC-008.md").write_text(f"---\nid: TC-008\npreconditions: {pre(2, 'b')}\n---\n\n## When\n1. x\n", encoding="utf-8")
        rows = stand_gaps.declared_preconditions(task_root)
        check_eq("F18: ids declared by ONE case keep their own form (in-flight stories are unchanged)", sorted(r["id"] for r in rows), ["PC-1", "PC-2"])
        (folder / "TC-008.md").write_text(f"---\nid: TC-008\npreconditions: {pre(1, 'b')}\n---\n\n## When\n1. x\n", encoding="utf-8")
        rows = stand_gaps.declared_preconditions(task_root)
        check_eq("F18: a shared id is `<PC id>@<case id>`, the raw id kept as `pc_id`",
                 sorted((r["id"], r["pc_id"], r["case"]) for r in rows), [("PC-1@TC-007", "PC-1", "TC-007"), ("PC-1@TC-008", "PC-1", "TC-008")])
        check_eq("F18: the precondition's own check travels with the row (the key of the environment record is built from it)",
                 sorted(next(iter(r["check"])) for r in rows), ["http", "http"])
        # M9: a case file that is broken for the moment still counts its raw ids
        (folder / "TC-008.md").write_text(f"---\nid: TC-008\npreconditions: {pre(1, 'b').replace('feature_flag', 'nonsense')}\n---\n\n## When\n1. x\n", encoding="utf-8")
        check_eq("M9: a case whose line has shape errors is skipped, but its raw id still qualifies the other's",
                 [r["id"] for r in stand_gaps.declared_preconditions(task_root)], ["PC-1@TC-007"])
        (folder / "TC-008.md").write_text('---\nid: TC-008\npreconditions: [{"id": "PC-1", broken\n---\n\n## When\n1. x\n', encoding="utf-8")
        check_eq("M9: even a line that is not JSON at all (its ids read out of the text)", [r["id"] for r in stand_gaps.declared_preconditions(task_root)], ["PC-1@TC-007"])
        (folder / "TC-008.md").write_text("---\nid: TC-008\n---\n\n## When\n1. x\n", encoding="utf-8")
        check_eq("control: with no second declaration the id is unqualified again", [r["id"] for r in stand_gaps.declared_preconditions(task_root)], ["PC-1"])
    finally:
        cleanup(root)


def test_b414_an_apply_grant_is_not_given_for_an_id_two_gaps_hold() -> None:
    root = project("qa-stand-gaps-b414-grant-")
    try:
        use_project(root)
        artifacts = root / "qa-factory" / "artifacts"
        target = str(root / "app/config/customer-config.yaml")
        answer(root, "PC-1", "apply - turn the flag on")
        check_eq("control: one gap of the id: the grant is given", stand_gaps.apply_grant(target, root, root / "app", artifacts).get("gap"), "PC-1")
        real = stand_gaps.collect
        gap = real(artifacts / "TP1-15045", "A", probe=False)[0]
        stand_gaps.collect = lambda tr, gate="A", *a, **k: [dict(gap), dict(gap)] if gate == "A" else []
        try:
            check_eq("R14: an id two gaps of ONE gate hold names neither of them: no grant",
                     stand_gaps.apply_grant(target, root, root / "app", artifacts), {})
        finally:
            stand_gaps.collect = real
        stand_gaps.collect = lambda tr, gate="A", *a, **k: [dict(gap)]       # the same gap shown at each gate is one gap per gate
        try:
            check_eq("R14 control: the same id at the two gates (one gap each) still grants", stand_gaps.apply_grant(target, root, root / "app", artifacts).get("gap"), "PC-1")
        finally:
            stand_gaps.collect = real
    finally:
        cleanup(root)


def test_gw1_31_k31_8_an_integration_card_says_what_is_missing_without_a_kind_prefix() -> None:
    """The `INT-*` row of an integration (`kind: env`) and a case's `check.integration` precondition (`kind: service`) read
    `<name> (..) - access ...`, never `env: ` / `service: `; any other row keeps its prefix; the row's `kind` is untouched (the
    `property_key` of a recorded `accept always` stands on it)."""
    root = project("qa-stand-gaps-gw1-31-")
    try:
        use_project(root)
        task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
        base = {"case": "TC-007", "scope": "case", "partitions": [], "state": "unmet", "remedy": CREDENTIAL_REMEDY}
        rows = [dict(base, id="INT-jira", pc_id="INT-jira", kind="env", check={"env": "JIRA_URL"}, what="jira (api)",
                     detail="access to jira is not set on this stand"),
                dict(base, id="PC-1", pc_id="PC-1", kind="service", check={"integration": "jira"}, what="access to jira",
                     detail="access to jira is not set on this stand"),
                dict(base, id="PC-2", pc_id="PC-2", kind="feature_flag", check={"http": {"path": "/x"}}, what="the flag",
                     detail="it is off")]
        gaps = {g["id"]: g for g in stand_gaps._gate_a_gaps(task_root, rows, texts={}, stand="localhost")}
        check_eq("K31.8: the INT row has no `env: ` prefix", gaps["INT-jira"]["missing"],
                 "jira (api) - access to jira is not set on this stand (on localhost)")
        check_eq("K31.8: the declared precondition has no `service: ` prefix", gaps["PC-1"]["missing"],
                 "access to jira - access to jira is not set on this stand (on localhost)")
        check_eq("K31.8: another kind keeps its prefix", gaps["PC-2"]["missing"], "feature flag: the flag - it is off (on localhost)")
        check_eq("K31.8: the kind of the INT row and of the declared row is unchanged",
                 (gaps["INT-jira"]["kind"], gaps["PC-1"]["kind"]), ("env", "service"))
        check_eq("K31.8: a row with no `what` still says the stand", stand_gaps._gate_a_gaps(
            task_root, [dict(base, id="INT-x", pc_id="INT-x", kind="env", check={"env": "X"})], texts={}, stand="")[0]["missing"],
                 "the stand")
    finally:
        cleanup(root)


def test_rd1_4_k14_a_process_output_never_rides_on_the_card() -> None:
    """RD1-4 (B-306 c, H5): a row that records a process run (it carries `exit_code`) puts the raw end of that run in
    `output_tail` for the conductor, never in `missing`; the card prints `missing`, so it never shows the tail. The key is the
    typed `exit_code` (presence, not value); every other row keeps `missing += " - <detail>"` (a precondition sentence is
    what the person needs)."""
    root = project("qa-stand-gaps-rd1-4-")
    try:
        use_project(root)
        import gate_brief
        import human_text
        task_root = root / "qa-factory" / "artifacts" / "TP1-15045"
        tail = "Traceback (most recent call last): ... run_suite.py --junitxml=x exit 2"
        base = {"id": "reporter-level", "case": "", "scope": "level", "contour": "api", "kind": "reporter",
                "what": "the test report could not be read", "state": "unmet", "remedy": {}}
        gap = stand_gaps._gate_a_gaps(task_root, [dict(base, exit_code=2, detail=tail)], texts={}, stand="localhost")[0]
        for needle in ("Traceback", "--junitxml", "run_suite.py"):
            check_not_in(f"K14: `missing` holds no `{needle}`", needle, gap["missing"])
        check_eq("K14: `output_tail` is the scrubbed tail (names_only)", gap.get("output_tail"), stand_gaps.names_only(tail))
        lines = gate_brief.stand_gap_card_lines(None, [gap], {})
        card = " ".join(lines)
        for needle in ("Traceback", "--junitxml", "run_suite.py"):
            check_not_in(f"K14: the card holds no `{needle}`", needle, card)
        missing_line = next((ln for ln in lines if "the test report could not be read" in ln), "")
        check_eq("K14: the card's `missing` line is a text that passes human_text (report kind)",
                 (bool(missing_line), human_text.problems(missing_line, kind="report")), (True, []))
        # the negative control: the same row WITHOUT `exit_code` keeps the tail on `missing` (the key is what decides)
        plain = stand_gaps._gate_a_gaps(task_root, [dict(base, detail=tail)], texts={}, stand="localhost")[0]
        check_in("K14 control: no `exit_code`, the tail rides on `missing`", "Traceback", plain["missing"])
        check_eq("K14 control: and there is no `output_tail`", "output_tail" in plain, False)
        # presence decides, not the value: 0 and None are runs too (M8)
        for value in (0, None):
            row = stand_gaps._gate_a_gaps(task_root, [dict(base, exit_code=value, detail=tail)], texts={}, stand="")[0]
            check_eq(f"K14: exit_code {value!r}: the tail is kept off `missing`", ("Traceback" in row["missing"], "output_tail" in row),
                     (False, True))
        # K15: a case precondition row (no exit_code) keeps its detail on `missing`; no output_tail
        pre = stand_gaps._gate_a_gaps(task_root, [{"id": "PC-1", "pc_id": "PC-1", "case": "TC-007", "scope": "case", "kind": "feature_flag",
                                                    "what": "the flag", "detail": "the flag is off", "state": "unmet", "remedy": REMEDY}],
                                      texts={}, stand="localhost")[0]
        check_eq("K15: a precondition row ends with its detail and the stand", pre["missing"], "feature flag: the flag - the flag is off (on localhost)")
        check_eq("K15: and has no `output_tail`", "output_tail" in pre, False)
        # K16: exit_code with an empty detail: no key, `missing` unchanged
        empty = stand_gaps._gate_a_gaps(task_root, [dict(base, exit_code=2, detail="")], texts={}, stand="localhost")[0]
        check_eq("K16: an empty detail makes no `output_tail`", "output_tail" in empty, False)
        check_eq("K16: and `missing` is the bare card text", empty["missing"], "reporter: the test report could not be read (with the command recorded now)")
        # K17: a secret never reaches any field
        secret = stand_gaps._gate_a_gaps(task_root, [dict(base, exit_code=1, detail="boom API_TOKEN=abc123 end")], texts={}, stand="")[0]
        check_in("K17: the name stays, the value is not printed", "API_TOKEN=<value not printed>", secret["output_tail"])
        check_not_in("K17: and `abc123` is in no field of the gap", "abc123", json.dumps(secret))
    finally:
        cleanup(root)


if __name__ == "__main__":
    test_rd1_4_k14_a_process_output_never_rides_on_the_card()
    test_gw1_31_k31_8_an_integration_card_says_what_is_missing_without_a_kind_prefix()
    test_b414_a_level_gap_says_why_about_the_command_and_a_case_gap_about_the_stand()
    test_b414_gate_b_covers_a_level_row_only_while_every_rule_holds()
    test_b414_a_shared_precondition_id_is_qualified_per_case_and_counted_over_raw_ids()
    test_b414_an_apply_grant_is_not_given_for_an_id_two_gaps_hold()
    test_the_gate_a_card_carries_the_exact_change_and_four_answers()
    test_gate_a_cards_of_one_case_and_more_than_three_and_the_answers_that_read()
    test_a_credential_is_named_and_never_printed()
    test_an_answered_gap_shows_the_answer_instead_of_asking_again()
    test_the_gate_b_card_replaces_the_raw_manifest_row()
    test_the_gate_b_card_says_when_a_blocked_test_ran_red()
    test_the_rehearsal_hands_the_gap_over_instead_of_spelling_it_out()
    test_t357_a_gate_a_packet_from_a_fixture_breaks_no_rule_of_human_questions()
    test_t357_the_command_line_prints_the_same_card_in_words()
    test_t357_open_before_mr_lists_what_is_undecided_without_a_script_or_a_field_name()
    test_a_remedy_of_the_wrong_shape_is_a_shape_error_not_a_card()
    test_the_persons_word_opens_exactly_one_file_once()
    test_a_role_never_changes_the_application_even_on_that_word()
    test_only_an_apply_answer_opens_anything()
    test_a_revoked_apply_opens_nothing()
    finish("stand gaps")
