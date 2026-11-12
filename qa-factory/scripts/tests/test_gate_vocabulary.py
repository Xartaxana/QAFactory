"""One gate vocabulary, and a person's word on the dispatch path.

The defect this file exists for, from TP1-15045: `controller.py` recorded the person's
"approve" as `gates.A.decision = "approved"`, `stage_guard.rule_gate_a` passed only
`"approve"`, and no test in the factory had ever carried a decision from the controller to a
reader — 113/113 green while the story could not enter S5. So the first part here is that
journey, end to end, through the real controller. Then: the person says "Go on", `waiver.py`
records it, and the block has to actually lift — silently printing OK over a standing block
is what sent the person to edit a line inside the plugin.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import (SCRIPTS, check, check_eq, check_in, cleanup, finish, run_script,  # noqa: E402
                     temp_project)

sys.path.insert(0, str(SCRIPTS))
from test_controller_state import record_stage_acceptance  # noqa: E402
import contract as C  # noqa: E402
import stage_guard as SG  # noqa: E402


# --- part 1: the one reader --------------------------------------------------------------

def part_contract_reader() -> None:
    table = [
        ("the orchestrator's own spelling", {"gates": {"A": {"decision": "approve"}}}, "A", True),
        ("the controller's spelling", {"gates": {"A": {"decision": "approved"}}}, "A", True),
        ("a record carrying only status", {"gates": {"A": {"status": "approved"}}}, "A", True),
        ("both, as the controller writes them",
         {"gates": {"A": {"decision": "approved", "status": "approved"}}}, "A", True),
        ("an edit is not an approval", {"gates": {"A": {"decision": "edit"}}}, "A", False),
        ("a decline is not an approval",
         {"gates": {"A": {"decision": "declined", "status": "declined"}}}, "A", False),
        ("a deferral is not an approval", {"gates": {"A": {"status": "deferred"}}}, "A", False),
        ("an empty record", {"gates": {"A": {}}}, "A", False),
        ("no gates at all", {}, "A", False),
        ("a null decision", {"gates": {"A": {"decision": None}}}, "A", False),
        ("gate B: deliver", {"gates": {"B": {"decision": "deliver"}}}, "B", True),
        ("gate B: deliver_with_risks (the dashboard's spelling)",
         {"gates": {"B": {"decision": "deliver_with_risks"}}}, "B", True),
        ("gate B: deliver_with_risk (external_writes' spelling)",
         {"gates": {"B": {"decision": "deliver_with_risk"}}}, "B", True),
        ("gate B: a deliver word does not approve gate A",
         {"gates": {"A": {"decision": "deliver"}}}, "A", False),
    ]
    for name, pipeline, gate, expected in table:
        check_eq(f"gate_approved — {name}", C.gate_approved(pipeline, gate), expected)

    check_eq("gate_answered — a decline is still an answer",
             C.gate_answered({"gates": {"A": {"decision": "declined"}}}, "A"), True)
    check_eq("gate_answered — nothing recorded",
             C.gate_answered({"gates": {"A": {"decision": None}}}, "A"), False)


# --- part 2: controller decision -> stage guard, end to end ------------------------------

def _plan_row() -> dict:
    ob = {"obligation_id": "O-1", "requirement_refs": [{"ref": "R-1", "revision": "2"}],
          "behavior": "the guarded behavior holds", "oracle_source_ref": "decision:R-1@2",
          "oracle_status": "resolved", "applicable_scenarios": ["state"],
          "observation_boundary": "case store", "completion_condition": "review complete",
          "coverage_links": [], "decision": "new", "remaining_gap": "",
          "planned_check_refs": ["TC-1"], "execution_scope": "current_task",
          "sufficiency_review": {"author_dispatch_id": "S3", "input_hash": "h",
                                 "rationale": "owner decision"},
          "observation_contract": {"claim_kind": ["ordinary"],
                                   "oracle_ref": {"ref": "R-1", "revision": "2"},
                                   "surfaces": [{"id": "s", "boundary": "case store",
                                                 "status": "planned", "assertion_ref": "TC-1"}],
                                   "controls": ["TC-1"], "completion_ref": "TC-1",
                                   "independent_expectations": [], "source_conflicts": []}}
    return {"id": "TS-1", "schema_version": 2, "impact": "low", "likelihood": "low",
            "confidence": "high", "risk_rationale": "bounded", "risk_source_refs": ["R-1"],
            "risk_policy_revision": "factory-starter-v1", "coverage_refs": ["R-1"],
            "unknowns": [], "verification_depth": "low", "required_scenarios": ["TC-1"],
            "test_level_rationale": "unit", "design_review_required": False,
            "bounded_reversible": True, "coverage_obligations": [ob],
            "coverage_contract_revision": "coverage-observation-v1",
            "coverage_delta": {"baseline_kind": "initial",
                               "initial_scope_rationale": "first baseline",
                               "entries": [{"obligation_id": "O-1", "disposition": "gap",
                                            "rationale": "new check",
                                            "gap_reason": "no prior coverage"}],
                               "counts": {"logical_cases_before": 0, "logical_cases_after": 1,
                                          "executable_instances_before": 0,
                                          "executable_instances_after": 1},
                               "planned_instance_ids": ["check-1"]}}


def _story_through_s4(root: Path):
    """A controller-managed story with S0..S4 accepted — the state gate A is asked in."""
    import hashlib
    from controller import Controller
    c = Controller(root)
    c.apply("initialize", {"scope": ["TC-1"], "source_revision": "src",
                           "known_paths": {"root": str(root)}, "idempotency_key": "init"})

    def evidence(name):
        path = root / name
        path.write_text(name, encoding="utf-8")
        return {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def stage(n):
        sid = f"S{n}"
        c.apply("dispatch", {"id": sid, "stage": sid, "role": "worker", "scope": ["TC-1"],
                             "input_hash": sid, "budget": {}, "known_paths": {},
                             "idempotency_key": "d" + sid})
        record_stage_acceptance(root, sid)  # E-B11 (no-op for S0/S1); the `worker` stub has no author dispatch
        c.apply("accept", {"id": sid, "status": "accepted", "stage_complete": True,
                           "evidence_refs": [evidence(sid + ".txt")], "idempotency_key": "a" + sid})

    for n in range(3):
        stage(n)
    (root / "work").mkdir(exist_ok=True)
    (root / "work" / "test-plan.json").write_text(
        json.dumps({"schema_version": 2, "rows": [_plan_row()]}), encoding="utf-8")
    for n in (3, 4):
        stage(n)
    state = root / "state"
    state.mkdir(exist_ok=True)
    (state / "story-case-links.json").write_text(
        json.dumps({"links": [{"case_id": "TC-1", "version": "cv1"}]}), encoding="utf-8")
    return c


def part_controller_to_guard() -> None:
    with tempfile.TemporaryDirectory(prefix="qa-gate-vocab-") as td:
        root = Path(td) / "QA-1"
        root.mkdir()
        c = _story_through_s4(root)
        pipeline_path = root / "pipeline.json"

        before = json.loads(pipeline_path.read_text(encoding="utf-8"))
        check("before the gate, S5 is refused",
              bool(SG.dispatch_errors(before, "S5", journal=False)))

        payload = {"id": "A", "gate": "A", "action": "approve", "status": "approved",
                   "authorization_source": "human", "source_revision": "src",
                   "scope": ["TC-1"], "input_revision": "src", "idempotency_key": "A"}
        payload.update(c.gate_inputs())
        c.apply("decision", payload)

        pipeline = json.loads(pipeline_path.read_text(encoding="utf-8"))
        check_eq("the controller projects the decision into pipeline.json",
                 (pipeline.get("gates") or {}).get("A", {}).get("decision"), "approved")
        check_eq("contract.gate_approved reads the controller's own projection",
                 C.gate_approved(pipeline, "A"), True)
        check_eq("and the stage guard lets S5 through — the whole of the incident",
                 SG.dispatch_errors(pipeline, "S5", journal=False), [])

        # The same journey with gate A absent and the person's word recorded instead.
        pipeline.pop("gates", None)
        check("with no gate at all, S5 is refused again",
              bool(SG.dispatch_errors(pipeline, "S5", journal=False)))
        from waiver import apply_stage_override
        apply_stage_override(pipeline, "S5", "gate A is not approved",
                             "Go on, I approved it out of band", "T1")
        check_eq("a recorded 'Go on' passes the block",
                 SG.dispatch_errors(pipeline, "S5", journal=False), [])
        check_eq("and so does a blanket override",
                 SG.dispatch_errors(apply_stage_override({"ticket": "QA-1",
                                                          "stages": pipeline["stages"]},
                                                         "S5", "*", "go", "T1"),
                                    "S5", journal=False), [])


# --- part 3: waiver.py re-checks what it recorded ----------------------------------------

def part_waiver_recheck() -> None:
    root = temp_project("qa-factory-gate-waiver-")
    try:
        art = root / "qa-factory" / "artifacts" / "QA-1"
        art.mkdir(parents=True)
        model = json.loads((SCRIPTS.parent / "references" / "stages.json").read_text(encoding="utf-8"))
        done = ("S0", "S1", "S2", "S3", "S4")
        stages = {s["id"]: {"status": "done" if s["id"] in done else "pending"}
                  for s in model["stages"]}
        (art / "pipeline.json").write_text(
            json.dumps({"ticket": "QA-1", "stages": stages, "gates": {}}), encoding="utf-8")
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(root)

        p = run_script("waiver.py", "--task", "QA-1", "--stage", "S5",
                       "--block", "gate A is not approved", "--decision", "Go on",
                       cwd=root, env=env)
        check_in("waiver.py says the block is lifted, and proves it by re-running the guard",
                 "block lifted", p.stdout + p.stderr)
        check_eq("waiver.py exits clean", p.returncode, 0)
        check_in("t-722 K4-2: ...in the words of what was checked: the guard no longer refuses on it, and nothing else stands",
                 "block lifted: the guard of S5 no longer refuses on it, and no other dispatch block of S5 stands",
                 p.stdout + p.stderr)

        # A word that names nothing standing must not claim to have lifted that block.
        (art / "pipeline.json").write_text(
            json.dumps({"ticket": "QA-1", "stages": {**stages, "S4": {"status": "pending"}},
                        "gates": {}}), encoding="utf-8")
        p = run_script("waiver.py", "--task", "QA-1", "--stage", "S5",
                       "--block", "gate A is not approved", "--decision", "Go on",
                       cwd=root, env=env)
        check_in("a block that is passed while another still stands is said out loud",
                 "still stand", p.stdout + p.stderr)
    finally:
        cleanup(root)


# --- part 4: a denied dispatch leaves proof it never started ----------------------

def part_denial_line() -> None:
    root = temp_project("qa-factory-gate-denial-")
    try:
        art = root / "qa-factory" / "artifacts" / "QA-1"
        art.mkdir(parents=True)
        model = json.loads((SCRIPTS.parent / "references" / "stages.json").read_text(encoding="utf-8"))
        stages = {s["id"]: {"status": "done" if s["id"] in ("S0", "S1") else "pending"}
                  for s in model["stages"]}
        (art / "pipeline.json").write_text(
            json.dumps({"ticket": "QA-1", "stages": stages, "gates": {}}), encoding="utf-8")
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(root)
        event = {"tool_name": "Task", "session_id": "s-gate-vocab",
                 "tool_input": {"subagent_type": "qa-test-strategist",
                                "prompt": "Task: QA-1\nDispatch id: S3-qa-test-strategist-1\n"}}
        p = subprocess.run([sys.executable, "-B", str(SCRIPTS / "inject_context.py")],
                           input=json.dumps(event), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", cwd=str(root), env=env, timeout=300)
        check_eq("the hook refuses a dispatch the stage guard blocks", p.returncode, 2)
        denials = art / "state" / "dispatch-denials.jsonl"
        check("the refusal is written down as proof the agent never started", denials.is_file())
        if denials.is_file():
            row = json.loads(denials.read_text(encoding="utf-8").splitlines()[0])
            check_eq("with the dispatch id from the prompt",
                     row.get("dispatch_id"), "S3-qa-test-strategist-1")
            check_eq("the stage", row.get("stage"), "S3")
            check_eq("the role", row.get("role"), "qa-test-strategist")
            check_in("and the reason", "required stages are not done", str(row.get("reason")))
            check("and the moment it happened", bool(row.get("at")))
    finally:
        cleanup(root)


# --- part 5: the words of a stand-gap answer are data, closed and English (t-342, B-272) --------------------------

def part_stand_gap_words() -> None:
    """`references/question-vocabulary.json` holds the one-word answers to a stand-gap card (FR-13); the reader is
    `gate_brief.read_stand_gap_answers`. What is held: the data is closed (every option of the record has its words, no
    word belongs to two options), English only, never spelled in code; a line is read only when its WHOLE answer is on the
    list - any other wording, in any language, is NOT read (it goes to the conductor); an id that names no gap, or two,
    is not read; and a story with no gap reads nothing."""
    import gate_brief
    data = json.loads((SCRIPTS.parent / "references" / "question-vocabulary.json").read_text(encoding="utf-8-sig"))
    every = data["stand_gap_words"]["answers"]
    rows = [r for r in every if not r.get("lasting")]
    lasting = [r for r in every if r.get("lasting")]
    check_eq("one standing row per option of the record, in the record's order", [r["option"] for r in rows], list(C.STAND_GAP_OPTIONS))
    check_eq("B-414: one LASTING row, `accept always`, of the option `accept`", [(r["option"], r["word"]) for r in lasting], [("accept", "accept always")])
    environment = data["environment_words"]["answers"]
    check_eq("B-414: the environment words are one row, `ask again`, the option `revoke`", [(r["option"], r["word"]) for r in environment], [("revoke", "ask again")])
    texts = [t for r in every + environment for t in [r["word"], r["says"], *r["synonyms"]]]
    check("every word, synonym and explanation is English: ASCII only (a person's other language goes to the conductor)",
          all(ord(ch) < 128 for t in texts for ch in t), str([t for t in texts if any(ord(ch) >= 128 for ch in t)]))
    keys = [gate_brief._word_key(t) for r in every + environment for t in [r["word"], *r["synonyms"]]]
    check_eq("no word or synonym belongs to two options or two lists (and none is written twice), the lasting row and `ask again` included",
             len(keys), len(set(keys)))
    check("no person-facing text of the data holds the config word `profile`, `RP-` or `profiles[`",
          not any(bad in t for t in texts + [data["probe_answers"]["reporter_accept"], data["probe_answers"]["command"]["says"]]
                  for bad in ("profile", "RP-", "profiles[")))
    check("every word is its own key", all(gate_brief.stand_gap_word_index(gate_brief.stand_gap_words(lasting=True)).get(gate_brief._word_key(r["word"])) == r["option"] for r in every))
    check_eq("the reader of the card's words returns the same four rows (the lasting row only on request)",
             ([r["option"] for r in gate_brief.stand_gap_words()], [r["word"] for r in gate_brief.stand_gap_words(lasting=True) if r["lasting"]]),
             (list(C.STAND_GAP_OPTIONS), ["accept always"]))
    index = gate_brief.stand_gap_word_index()
    check_eq("the old internal words still read, as synonyms", [index[w] for w in ("apply", "theirs", "handed", "accepted")],
             ["apply", "theirs", "handed", "accept"])
    # --- the reader: the whole text after the colon, against the list ---
    remedy = {"kind": "flag", "where": "app/config.yaml:3", "change": "enabled: true"}
    gaps = [{"id": "area/TC-001", "case_id": "TC-001", "stage": "S9", "remedy": remedy},
            {"id": "TC-002", "case_id": "TC-002", "stage": "S9", "remedy": {}}]
    other = "".join(chr(c) for c in (0x43f, 0x440, 0x438, 0x43d, 0x44f, 0x442, 0x44c))      # "accept" in Russian, from code points (FR-30)

    def read(words, gap_list=gaps):
        found = gate_brief.read_stand_gap_answers(words, gap_list)
        return [(r["gap"]["id"], r["option"]) for r in found["read"]], [u["line"] for u in found["unread"]]
    for said, option in (("TC-001: accept", "accept"), ("TC-001: ACCEPT!", "accept"), ("`TC-001`: `accept`", "accept"),
                         ("* TC-001 : accept.", "accept"), ("TC-001:accept", "accept"), ("tc-001: accept", "accept"),
                         ("[TC-001]: accept", "accept"), ("TC-001: accept as blocked", "accept"), ("TC-001:   i  will   run it", "handed"),
                         ("area/TC-001: myself", "theirs"), ("TC-001: change", "apply"), ("- TC-001: Fix it", "apply")):
        check_eq(f"`{said}` reads as {option}", read(said), ([("area/TC-001", option)], []))
    for label, said in (("a word that is not the whole answer", "TC-001: accept, thanks"), ("a word of another language", f"TC-001: {other}"),
                        ("a word nobody listed", "TC-001: yes please"), ("an id that is no gap", "TC-009: accept"),
                        ("`change` where the card offers no exact change", "TC-002: change")):
        check_eq(f"{label} is not read - it is named, never dropped", read(said), ([], [said]))
    check_eq("an id that two gaps share names none of them", read("TC-005: accept", gaps + [dict(gaps[0], id="other/TC-005", case_id="TC-005"), dict(gaps[0], id="third/TC-005", case_id="TC-005")]),
             ([], ["TC-005: accept"]))
    check_eq("its key names exactly one", read("third/TC-005: accept", gaps + [dict(gaps[0], id="third/TC-005", case_id="TC-005"), dict(gaps[0], id="other/TC-005", case_id="TC-005")])[0],
             [("third/TC-005", "accept")])
    check_eq("lines that are not the form are neither read nor named", read("file 1 and 3; 2 is not a bug\nQ1: a\nR-17: it is a bug\nTC-001"), ([], []))
    twice = gate_brief.read_stand_gap_answers("TC-001: accept\nTC-002: myself\nTC-001: run", gaps)
    check_eq("two lines for one gap: the last wins, the earlier one is kept beside it",
             [(r["gap"]["id"], r["option"], r["replaced"]) for r in twice["read"]],
             [("area/TC-001", "handed", ["TC-001: accept"]), ("TC-002", "theirs", [])])
    # critic t-346 F2: the person's LAST word on a gap decides it
    mixed = gate_brief.read_stand_gap_answers("TC-001: run\nTC-001: no wait, not that", gaps)
    check_eq("a readable line then an unreadable one for one gap: nothing is read for it", mixed["read"], [])
    check_eq("and both lines are named, the later first", [u["line"] for u in mixed["unread"]],
             ["TC-001: no wait, not that", "TC-001: run"])
    check_eq("unreadable then readable: the last line is the answer", read("TC-001: no wait\nTC-001: run")[0], [("area/TC-001", "handed")])
    check_eq("another gap's readable line is not held back by it", read("TC-002: myself\nTC-001: run\nTC-001: nope")[0], [("TC-002", "theirs")])
    check_eq("`change` where the card offers none, as the last line, holds the gap back too", read("TC-002: myself\nTC-002: change")[0], [])
    check_eq("a story with no stand gap reads nothing, whatever the lines look like", read("TC-001: accept\nTC-009: yes", []), ([], []))
    check_eq("an empty answer reads nothing", read(""), ([], []))
    # a data file that is damaged reads as fewer answers, never as a wrong one; one that cannot be read, as none (FR-41)
    import hooklib
    real = hooklib.load_ref_json
    try:
        hooklib.load_ref_json = lambda name: {"stand_gap_words": {"answers": [
            {"option": "bogus", "word": "x"}, {"option": "accept", "word": ""}, "junk",
            {"option": "accept", "word": "keep", "says": "it stays", "synonyms": ["stay", ""]}]}}
        check_eq("a damaged file: only the usable row is read", [(r["option"], r["word"]) for r in gate_brief.stand_gap_words()], [("accept", "keep")])
        check_eq("and the reader reads exactly that word", read("TC-001: keep")[0], [("area/TC-001", "accept")])
        check_eq("while `accept` is no longer on the list", read("TC-001: accept"), ([], ["TC-001: accept"]))
        hooklib.load_ref_json = lambda name: None
        check_eq("a file that cannot be read gives no answers at all", gate_brief.stand_gap_words(), [])
    finally:
        hooklib.load_ref_json = real


def part_stand_gap_words_at_both_gates() -> None:
    """t-357: the words of the stand-gap answer are shown at GATE A too (one renderer, FR-10), so what the data file says
    is what BOTH gates say to a person: the owner's rule (02.10) - never a script, a flag, a block id or the code's own
    option name (`handed`) - holds for every row of the data, and no word a person could have used is lost."""
    import gate_brief
    import human_text
    import stand_gaps
    rows = gate_brief.stand_gap_words()

    def says_the_option(row: dict) -> bool:
        return row["option"] != row["word"] and row["option"] in f"{row['word']} {row['says']}".lower()
    for row in rows:
        shown = f"{row['word']} {row['says']}"
        check_eq(f"the option's own name `{row['option']}` is the code's, never the card's: `{row['word']}` says it in words",
                 says_the_option(row), False)
        check_eq(f"`{row['word']}`: no script, flag or exit code in the word or its explanation",
                 [p["rule"] for p in human_text.problems(shown, kind="report") if p["rule"] in ("script_name", "flag", "exit_code")], [])
    handed = [r for r in rows if r["option"] == "handed"][0]
    check_in("the person who runs the test themselves is told so in plain words", "you run this test yourself", handed["says"])
    # no word of the list is ever lost: these are every spelling a person has been offered or has used
    must_read = {"apply": ("apply", "change it", "fix it", "you change it", "change"), "theirs": ("theirs", "mine", "i will change it", "i change it",
                 "i will fix it", "i fix it", "myself"), "handed": ("handed", "run it", "i will run it", "i run it", "i will run the test",
                 "i run the test", "run"), "accept": ("accepted", "blocked", "stay blocked", "stays blocked", "leave it blocked",
                 "accept as blocked", "accept")}
    index = gate_brief.stand_gap_word_index()
    check_eq("every spelling ever offered still reads as its option (the list may gain words, never lose one)",
             sorted((w, o) for o, ws in must_read.items() for w in ws if index.get(gate_brief._word_key(w)) != o), [])
    # the card of gate A, from the data: every row's word and explanation, in the record's order
    gap = {"id": "PC-1", "gate": "A", "stage": "S5", "case": "TC-007", "case_id": "TC-007", "requirement": "R-3", "partitions": [],
           "the_test": "a test", "missing": "a flag", "remedy": {"kind": "flag", "where": "a.yaml:1", "change": "on"}, "task": "T"}
    card = stand_gaps.render([gap])
    check_eq("gate A's card lists exactly the data's rows, in order",
             [line for line in card.splitlines() if line.startswith("- `")], [f"- `{r['word']}` — {r['says']}" + (
                 " (offered only for a gap whose card shows an exact change)" if r["option"] == "apply" else "") for r in rows])
    check_eq("...and so does gate B's (the same function)",
             card, "\n".join(gate_brief.stand_gap_card_lines(None, [dict(gap, gate="B", stage="S9")], None, limit=None)) + "\n")


# --- part 6: the option -> word map, five readers (t-666 R2) -----------------------------------------------------

def part_option_word_map() -> None:
    """Five readers turn a stand-gap option into the word the data file gives it: the answer reader's vocabulary
    (`_answer_vocab`), the conductor relay line (`relay_card_line`), the card context (`_card_context`), the recorded
    answer's words (`stand_gaps._option_word`) and the rehearsal's door text (`Rehearsal.word_of`). The reference is the
    DATA FILE read here, not the code under test. A file that cannot be read gives `{}` / "in your own words" / "" (E7); the
    map shown to a person never carries `command` or any key outside `contract.STAND_GAP_OPTIONS` (I3, critic t-648 F-4)."""
    import gate_brief
    import gate_preflight
    import hooklib
    import stand_gaps
    data = json.loads((SCRIPTS.parent / "references" / "question-vocabulary.json").read_text(encoding="utf-8-sig"))
    shipped = {r["option"]: r["word"] for r in data["stand_gap_words"]["answers"] if not r.get("lasting")}
    command = data["probe_answers"]["command"]["word"]
    gap = {"id": "RP-web", "stage": "S5", "remedy": {"offers": ["theirs", "handed", "accept"]}}
    options = ("apply", "theirs", "handed", "accept", "bogus", None)

    def seen() -> dict:
        return {"vocab": gate_brief._answer_vocab(None)["word_of"],
                "vocab_rows": gate_brief._answer_vocab(
                    [{"option": "accept", "word": "keep", "synonyms": []},
                     {"option": "accept", "word": "keep always", "synonyms": [], "lasting": True}])["word_of"],
                "card": gate_brief._card_context(None, [], [])[1],
                "relay": gate_brief.relay_card_line(gap, "TC-001", "S5"),
                "option_word": [stand_gaps._option_word(o) for o in options],
                "rehearsal": [gate_preflight.Rehearsal.word_of(o) for o in options]}
    got = seen()
    check_eq("R2 map: the shipped file's four standing words, in the record's order", list(shipped), list(C.STAND_GAP_OPTIONS))
    check_eq("R2 map 2.1: the answer reader's map is the four words plus the `command` word of the probe list",
             got["vocab"], dict(shipped, command=command))
    check_eq("R2 map 2.1: from a caller's own rows the lasting row is left out of the map", got["vocab_rows"], {"accept": "keep", "command": command})
    check_eq("R2 map 2.3: the card context's map is exactly the four words (no `command`)", got["card"], shipped)
    check_eq("R2 map 2.3: ...and its keys are the options of the record, nothing else", list(got["card"]), list(C.STAND_GAP_OPTIONS))
    check_in("R2 map 2.2: the relay line lists the words of the offered options, in the card's order",
             "takes ONLY `theirs`, `handed`, `accept` (the words: `myself`, `run`, `accept`); any other word is NOT recorded", got["relay"])
    check_eq("R2 map 2.4: the recorded answer's word per option; a word outside the list reads `in your own words`",
             got["option_word"], ["change", "myself", "run", "accept", "in your own words", "in your own words"])
    check_eq("R2 map 2.5: the door text's word per option; '' for an option outside the list",
             got["rehearsal"], ["change", "myself", "run", "accept", "", ""])
    mine = gate_brief._card_context(None, [], [])[1]
    mine["command"] = "added by a caller"
    check_eq("R2 map: each call builds its own dict (a caller that adds a key changes nobody else's map)",
             "command" in gate_brief._card_context(None, [], [])[1], False)
    # the carrier (gate_brief.stand_gap_word_of): the one map the five sites above are built from
    check_eq("R2 carrier: the data file's four standing words", gate_brief.stand_gap_word_of(), shipped)
    check_eq("R2 carrier I3: its keys are exactly the options of the record - never `command`, nothing outside",
             list(gate_brief.stand_gap_word_of()), list(C.STAND_GAP_OPTIONS))
    own = gate_brief.stand_gap_word_of()
    own["command"] = "added by a caller"
    check_eq("R2 carrier: a NEW dict on every call", gate_brief.stand_gap_word_of(), shipped)
    check_eq("R2 carrier: from a caller's own rows the lasting row is left out, the standing row stands",
             gate_brief.stand_gap_word_of([{"option": "accept", "word": "keep always", "lasting": True},
                                           {"option": "accept", "word": "keep"}, {"option": "apply", "word": "fix"}]),
             {"accept": "keep", "apply": "fix"})
    check_eq("R2 carrier: from no rows at all, an empty map", gate_brief.stand_gap_word_of([]), {})
    # --- a file that cannot be read: no words, said in words by each caller (E7) ---
    real = hooklib.load_ref_json
    try:
        hooklib.load_ref_json = lambda name: None
        dark = seen()
        check_eq("R2 map E7: unreadable file, 2.1 and 2.3 give an empty map", (dark["vocab"], dark["vocab_rows"] == {"accept": "keep"}, dark["card"]),
                 ({}, True, {}))
        check_in("R2 map E7: unreadable file, 2.2 lists no words", "(the words: ); any other word is NOT recorded", dark["relay"])
        check_eq("R2 map E7: unreadable file, 2.4 says `in your own words` for every option", set(dark["option_word"]), {"in your own words"})
        check_eq("R2 map E7: unreadable file, 2.5 gives '' for every option", set(dark["rehearsal"]), {""})
        check_eq("R2 carrier E7: unreadable file, an empty map", gate_brief.stand_gap_word_of(), {})
        # a damaged file with one option twice: every site keeps the LAST row (the door text took the FIRST before t-666 R2, E7)
        hooklib.load_ref_json = lambda name: {"stand_gap_words": {"answers": [
            {"option": "accept", "word": "first"}, {"option": "accept", "word": "second"}]}}
        twice = seen()
        check_eq("R2 map E7: a damaged file with one option twice: the dict sites keep the last row",
                 (twice["card"], twice["option_word"][3]), ({"accept": "second"}, "second"))
        check_eq("R2 map E7: ...and so does the door text now (it took the FIRST row before; the shipped file has one row per option)",
                 twice["rehearsal"][3], "second")
    finally:
        hooklib.load_ref_json = real


def main() -> None:
    part_contract_reader()
    part_controller_to_guard()
    part_waiver_recheck()
    part_denial_line()
    part_stand_gap_words()
    part_stand_gap_words_at_both_gates()
    part_option_word_map()
    finish("test_gate_vocabulary")


if __name__ == "__main__":
    main()
