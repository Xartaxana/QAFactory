"""The reporter is proven before gate A, on one existing test.

TP2-2553: Karma ran with `progress`, `kjhtml` and `coverage`, `karma-junit-reporter`
was in no dependency of the project, and the profile said the run writes a report. The runner
knows that cure and printed it — in the middle of S5, on the first real run, after the
approval; the story's only true execution gap cost a window nobody had planned.

The rehearsal already collects the project's suite and resolves the launcher. These tests
assert the last link: one existing test is run through the profile's own one-test command, a
report the factory can parse is an INFO line, and no report is a stand-gap card with the exact
cure on it — the same four answers as every other card, passed by a person's word.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup,  # noqa: E402
                     finish, temp_dir, use_project)

sys.path.insert(0, str(SCRIPTS))

import contract as C  # noqa: E402
import gate_preflight  # noqa: E402

TICKET = "TP2-2553"

PLAN_ROW = {"id": "TS-1", "requirement_ids": ["R-1"], "level": "api", "disposition": "automate",
            "impact": "moderate", "likelihood": "medium", "design_review_required": False,
            "confidence": "medium", "risk_rationale": "the report is the evidence",
            "coverage_refs": [], "unknowns": [], "verification_depth": "normal"}

# A stand-in for a project's runner: it writes whatever report the case asks for into the path
# it was handed, so a test here proves the rehearsal's reading and never a real framework.
WRITES_JUNIT = """import sys
from pathlib import Path
report, test = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "?")
Path(report).write_text(
    '<?xml version="1.0"?><testsuite name="s" tests="1" failures="1" errors="0" skipped="0" '
    'time="0.1"><testcase classname="c" name="' + test + '"><failure message="red"/>'
    '</testcase></testsuite>', encoding="utf-8")
sys.exit(1)
"""
WRITES_NOTHING = """import sys
print("Executed 1 of 1 SUCCESS", file=sys.stderr)
sys.exit(0)
"""


def helper_turn(root: Path, kind: str = "not_adapted", by: str = "conductor", understood: str = "") -> dict:
    """B-416 N3: the conductor's one turn on the CURRENT command of the profile `web`, as `report_adapt.py` leaves it - after it the
    unread report is a card for the person; before it, a finding for the conductor."""
    import onboarding_probe
    import report_adapt
    config = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
    argv = config["profiles"][0]["commands"]["one_test"]["argv"]
    row, problem = report_adapt.append(root, {"kind": kind, "by": by, "profile_id": config["profiles"][0]["profile_id"], "argv_digest": onboarding_probe.argv_digest(argv),
                                              "story": TICKET, "understood": understood})
    assert row is not None, problem
    # The record counts in whole seconds and an equal moment is not newer than the proof (E-M5): a test that proves and asks in one
    # second puts the row ONE SECOND AFTER the latest proof it follows, as a conductor's turn after a real proof would be.
    proofs = root / "qa-factory" / "state" / "reporter-rehearsals.json"
    if proofs.is_file():
        import datetime
        moments = [report_adapt._moment(r.get("at")) for r in json.loads(proofs.read_text(encoding="utf-8")).get("rehearsals", {}).values()]
        latest = max(moments, default=0)
        if report_adapt._moment(row["at"]) <= latest:
            record = json.loads(report_adapt.record_path(root).read_text(encoding="utf-8"))
            row["at"] = datetime.datetime.fromtimestamp(latest + 1, datetime.timezone.utc).isoformat(timespec="seconds")
            record["rows"][-1]["at"] = row["at"]
            report_adapt.record_path(root).write_text(json.dumps(record), encoding="utf-8")
    return row


def project(prefix: str, *, runner: str = WRITES_JUNIT, launcher: str = "",
            rehearsal: dict | None = None, helped: bool = False) -> Path:
    """A project with one automate case and one execution profile that runs one test. `helped`: the conductor has had its one turn on
    the command already (B-416), so an unread report is the person's card."""
    root = temp_dir(prefix)
    task_root = root / "qa-factory" / "artifacts" / TICKET
    (task_root / "work" / "test-cases").mkdir(parents=True)
    (task_root / "state").mkdir(parents=True)
    (root / "tests").mkdir()
    # Two, so that "the first test file found" and "the test the project named" can never be
    # the same file and pass each other's assertion.
    (root / "tests" / "test_a_first.py").write_text("def test_first():\n    pass\n",
                                                    encoding="utf-8")
    (root / "tests" / "test_z_named.py").write_text("def test_named():\n    pass\n",
                                                    encoding="utf-8")
    fake = root / "fake_runner.py"
    fake.write_text(runner, encoding="utf-8")
    (root / "qa-factory" / "config.json").write_text(json.dumps({
        "schema_version": 1, "tests_root": "tests", "app_root": ".",
        "gate_rehearsal": rehearsal or {},
        "profiles": [{"profile_id": "web", "capabilities": ["api"],
                      "reporter": {"kind": "junit-xml"},
                      "commands": {"one_test": {
                          "argv": [launcher or sys.executable, str(fake), "{report_path}",
                                   "<test-id>"],
                          "cwd": "."}}}]}), encoding="utf-8")
    (task_root / "work" / "test-plan.json").write_text(json.dumps([PLAN_ROW]), encoding="utf-8")
    (task_root / "pipeline.json").write_text(json.dumps(
        {"ticket": TICKET, "stages": {"S4": {"status": "done"}}}), encoding="utf-8")
    (task_root / "work" / "test-cases" / "TC-001.md").write_text(
        "---\nid: TC-001\n---\n\nPlan row: TS-1\n\n## When\n1. the report is read.\n",
        encoding="utf-8")
    if helped:
        helper_turn(root)
    return root


def rehearse(root: Path):
    """The one step, run on its own: the gate's other checks are other tests' subject."""
    r = gate_preflight.Rehearsal(root / "qa-factory" / "artifacts" / TICKET, "A")
    r.check_s5_reporter()
    return r


def test_a_profile_that_writes_a_report_is_stated_and_never_asked_about() -> None:
    root = project("qa-reporter-ok-")
    try:
        use_project(root)
        r = rehearse(root)
        check_eq("a proven reporter asks the person nothing", r.findings, [])
        check_eq("and leaves no card behind", r.stand_gaps, [])
        check_eq("what it proved is said out loud, once", len(r.info), 1)
        check_in("the line names the profile", "`web`", r.info[0]["message"])
        check_in("the test it ran", "tests/test_a_first.py", r.info[0]["message"])
        check_in("and the format the factory read", "junit-xml", r.info[0]["message"])
        check_in("a red test proves the reporter just as well", "1 test(s) counted",
                 r.info[0]["message"])
        check_in("the INFO reaches the human form of the rehearsal", "INFO (1)",
                 gate_preflight.render({"gate": "A", "next_stage": "S5", "can_proceed": True,
                                        "findings": [], "info": r.info,
                                        "by_class": {c: 0 for c in gate_preflight.CLASSES}}))
    finally:
        cleanup(root)


def test_a_run_that_leaves_no_report_is_a_card_with_the_cure_on_it() -> None:
    """Karma's own case: exit 0, a green log, and nothing any factory can read."""
    root = project("qa-reporter-gap-", runner=WRITES_NOTHING, helped=True)
    try:
        use_project(root)
        r = rehearse(root)
        check_eq("the gap travels as exactly one card", len(r.stand_gaps), 1)
        gap = r.stand_gaps[0]
        check_eq("the card is keyed to the profile it is about", gap["id"], "RP-web")
        check_eq("it is a reporter gap, in the contract's own word", gap["kind"], "reporter")
        # B-414 R1: the gap is about a whole LEVEL - every test of the execution contour - so it carries every case it costs and
        # no case of its own (it used to name `cases[0]`, which made a level accept apply to one case)
        check_eq("it is a LEVEL gap of the contour `web`, with every case it costs and no case of its own",
                 (gap["scope"], gap["contour"], gap["cases"], gap["case"]), ("level", "web", ["TC-001"], ""))
        check_eq("and says why the report could not be used, in a typed class", gap["reason_class"], "no_file")
        check_in("and says what is missing in one sentence",
                 "writes no junit-xml report", gap["what"])
        check_eq("the remedy is valid by the contract", C.remedy_errors(gap["remedy"]), [])
        check_in("it points at the profile's own command, never at application code",
                 "profiles[web].commands.one_test", gap["remedy"]["where"])
        check_eq("and says it in words for the person (no config key path)",
                 gap["remedy"]["where_words"], "qa-factory/config.json, the command that runs one web test")
        check_eq("there is one finding, and it only points at the card", len(r.findings), 1)
        check_eq("the card is the person's to answer",
                 r.findings[0]["class"], gate_preflight.PERSON_DECIDES)
        # t-357 F5 / t-364: one gap, one name. The pointer names the gap the way its card does - a level gap by its tests
        # (B-414: `the web tests`) - and never spells the block key `stand gap: <id>`, which travels in `waives`.
        check_eq("the pointer names the gap by what its card speaks of (the web tests)",
                 r.findings[0]["message"].startswith("the web tests — "), True)
        check_not_in("and the block key spelling `stand gap: RP-web` is not in the sentence a person reads",
                     "stand gap: RP-web", r.findings[0]["message"])
        check_not_in("nor the gap's own key `RP-web`", "RP-web", r.findings[0]["message"])
        check_in("and the way to answer it, in words (t-357: no command; the block travels as data in `waives`)",
                 "answer the card: write the line it shows, with one of the words it lists", r.findings[0]["fix"])
        check_eq("t-357: the block the word passes", [d["block"] for d in r.findings[0]["waives"]], ["stand gap: RP-web"])
        # The packet the person actually reads is the card, not the finding.
        import gate_brief
        lines, ids = gate_brief.stand_gap_cards(root / "qa-factory" / "artifacts" / TICKET, "A",
                                                rehearsed={"stand_gaps": r.stand_gaps})
        card = "\n".join(lines)
        check_eq("the packet carries the card", ids, ["RP-web"])
        check_in("with the four answers of every other stand gap (t-357: the same words, from the data file)", "- `accept` —", card)
        check_in("and the exact change on it", "the fix:", card)
        # the name in the pointer is the name the card is headed by, and the reader binds a line in that form to the gap
        check_in("the card is headed by the same name the pointer carries, says it is a whole level and names its case",
                 "Stand gap: the web tests — a whole level: every web test of this story (1 case: [TC-001](", card)
        check_not_in("the card never prints the old `stand gap: RP-web` spelling", "stand gap: RP-web", card.lower())
        check_in("the card shows the one form the answer is written in", "`<case id or level name>: <word>`", card)
        check_in("with the contour as the example", "`web: accept`", card)
        import stand_gaps
        gaps = stand_gaps.collect(root / "qa-factory" / "artifacts" / TICKET, "A", rehearsal={"stand_gaps": r.stand_gaps})
        read = gate_brief.read_stand_gap_answers("web: accept", gaps)
        check_eq("a line `web: accept` binds to this very gap (the answer reader, not a heading)",
                 ([row["gap"]["id"] for row in read["read"]], [row["option"] for row in read["read"]], read["unread"]),
                 (["RP-web"], ["accept"], []))
        check_eq("and the case id of one case it costs names no stand gap of its own (a level is not guessed from a case)",
                 [row["gap"]["id"] for row in gate_brief.read_stand_gap_answers("TC-001: accept", gaps)["read"]], [])
        gone = gate_brief.read_stand_gap_answers("stand gap: RP-web: accept", gaps)
        check_eq("negative: the old spelling `stand gap: RP-web: accept` binds to nothing",
                 [row["gap"]["id"] for row in gone["read"]], [])
    finally:
        cleanup(root)


def test_the_cure_is_the_one_the_runner_already_words() -> None:
    """The flag was written in `run_suite.py` before 2553 ran; only the moment it is read
    changed. Two wordings of one cure would be two facts to keep true."""
    import run_suite
    check_in("karma is told the reporter and the package it needs",
             "karma-junit-reporter", run_suite.report_cure(["npx", "karma", "start"]))
    check_in("jest is told its own", "jest-junit", run_suite.report_cure(["npx", "jest"]))
    check_in("dotnet is told the logger", "LogFilePath",
             run_suite.report_cure(["dotnet", "test"]))
    check_eq("pytest is told nothing, because the runner equips it itself",
             run_suite.report_cure(["poetry", "run", "pytest"]), "")


# --- KO7 (t-398, B-220 part 1 closed): the cure words have ONE home, references/report-cures.json (FR-13) ----------------
# `run_suite.report_cure` is a thin call into the leaf `report_cures`; the constant it used to carry is gone.

def _cures_file() -> Path:
    return SCRIPTS.parent / "references" / "report-cures.json"


def ko7_report_cure_reads_the_json_and_the_words_are_the_old_ones_but_for_vitest() -> None:
    import report_cures
    import run_suite
    check_eq("KO7: the constant is gone - the JSON is the only home of the words", hasattr(run_suite, "REPORT_CURES"), False)
    check_in("KO7: karma still comes out with its reporter flag", "`--reporters junit`", run_suite.report_cure(["npx", "karma", "start", "karma.conf.js"]))
    check_in("KO7: and the package it needs", "`karma-junit-reporter`", run_suite.report_cure(["ng", "test"]))
    check_in("KO7: jest still comes out with its own flag", "`--reporters=jest-junit`", run_suite.report_cure(["npx", "jest"]))
    check_in("KO7: dotnet still comes out with the logger", '`--logger "junit;LogFilePath=<path>"`', run_suite.report_cure(["dotnet", "test"]))
    check_in("KO7: playwright still comes out with its variable", "PLAYWRIGHT_JUNIT_OUTPUT_NAME", run_suite.report_cure(["npx", "playwright", "test"]))
    check_eq("KO7: pytest -> '' (the runner equips it), even behind a launcher", run_suite.report_cure(["poetry", "run", "pytest", "-q"]), "")
    check_eq("KO7: an empty argv -> ''", (run_suite.report_cure([]), run_suite.report_cure(None)), ("", ""))
    check_eq("KO7: a command no row names -> ''", run_suite.report_cure(["make", "check"]), "")
    vitest = run_suite.report_cure(["npx", "vitest", "run"])
    check_in("KO7: vitest is the CORRECTED row - its built-in junit reporter", "built-in junit reporter", vitest)
    check_in("KO7: with the flags that switch it on", "--reporter=junit --outputFile={report_path}", vitest)
    check_not_in("KO7: and no longer jest's package", "jest-junit", vitest)
    check_eq("KO7: the runner's function says what the leaf says", run_suite.report_cure(["npx", "karma"]), report_cures.cure_words(["npx", "karma"]))


def ko7_a_changed_value_in_the_json_changes_the_sentence() -> None:
    """The key that the words are READ: a temp copy of the file with one changed value changes what the runner says; the twin
    on the shipped file gives today's words (so the key cannot pass on a constant)."""
    import report_cures
    import run_suite
    shipped = json.loads(_cures_file().read_text(encoding="utf-8"))
    twin = run_suite.report_cure(["npx", "karma", "start"])
    check_in("KO7 twin: the shipped file gives today's karma words", "`karma-junit-reporter`", twin)
    temp = temp_dir("qa-ko7-")
    original = report_cures.cures_path
    try:
        changed = json.loads(json.dumps(shipped))
        for row in changed["rows"]:
            if row["id"] == "karma":
                row["words"] = "karma: SENTENCE-FROM-THE-TEMP-COPY"
        copy_path = temp / "report-cures.json"
        copy_path.write_text(json.dumps(changed), encoding="utf-8")
        report_cures.cures_path = lambda: copy_path
        check_eq("KO7: a changed value in the file is the sentence the runner gives", run_suite.report_cure(["npx", "karma", "start"]),
                 "karma: SENTENCE-FROM-THE-TEMP-COPY")
        check_in("KO7: a row nobody touched still says its own words", "jest-junit", run_suite.report_cure(["npx", "jest"]))
    finally:
        report_cures.cures_path = original
        cleanup(temp)
    check_eq("KO7 twin: with the shipped file back, today's words again", run_suite.report_cure(["npx", "karma", "start"]), twin)


def ko7_a_words_table_that_cannot_be_read_never_stops_a_run() -> None:
    """The invariant: a run's outcome does not depend on the cure words. A missing or broken table is '' in the runner (the
    probe, whose subject the table is, says it could not be read)."""
    import report_cures
    import run_suite
    temp = temp_dir("qa-ko7-")
    original = report_cures.cures_path
    try:
        for label, content in (("missing", None), ("not JSON", "{not json"), ("no rows list", json.dumps({"rows": "x"})),
                               ("a list", json.dumps([1, 2]))):
            path = temp / f"{label.replace(' ', '-')}.json"
            if content is not None:
                path.write_text(content, encoding="utf-8")
            report_cures.cures_path = lambda p=path: p
            try:
                report_cures.load()
                raised = ""
            except report_cures.CureTableUnreadable as exc:
                raised = str(exc)
            check_eq(f"KO7: {label}: the leaf raises its typed error with the sentence", raised.startswith("the cure table could not be read: "), True)
            check_eq(f"KO7: {label}: report_cure returns '' and does not raise",
                     (run_suite.report_cure(["npx", "karma", "start"]), run_suite.report_cure(["poetry", "run", "pytest"])), ("", ""))
        # a row of another shape is skipped, the others still speak
        odd = temp / "odd-rows.json"
        odd.write_text(json.dumps({"rows": [7, {"id": "x"}, {"match": "karma", "words": "w"}, {"id": "ok", "match": ["karma"], "words": "KARMA-OK"}]}),
                       encoding="utf-8")
        report_cures.cures_path = lambda: odd
        check_eq("KO7: broken rows are skipped, never a crash; the usable row speaks", run_suite.report_cure(["npx", "karma"]), "KARMA-OK")
    finally:
        report_cures.cures_path = original
        cleanup(temp)


def ko7_the_leaf_imports_neither_the_gate_nor_the_runner() -> None:
    """The layering key: `report_cures.py` imports none of gate_preflight / run_suite / onboarding_probe / story_run (an AST
    walk over EVERY import, the lazy ones too), and importing run_suite does not put the gate into `sys.modules`."""
    import ast
    import subprocess
    forbidden = {"gate_preflight", "run_suite", "onboarding_probe", "story_run"}
    tree = ast.parse((SCRIPTS / "report_cures.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    check_eq("KO7 layering: the leaf imports none of the gate, the runner, the probe, the story driver", sorted(imported & forbidden), [])
    check_in("KO7 layering control: the same walk sees the leaf's real imports", "json", sorted(imported))

    def closure(statement: str) -> str:
        done = subprocess.run([sys.executable, "-B", "-c", "import sys\nsys.path.insert(0, %r)\n%s\nprint('gate_preflight' in sys.modules)" % (str(SCRIPTS), statement)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(temp_root),
                              env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, timeout=120)
        return done.stdout.strip() or done.stderr.strip()[-300:]

    temp_root = temp_dir("qa-ko7-")
    try:
        check_eq("KO7 layering: importing run_suite does not import gate_preflight", closure("import run_suite"), "False")
        check_eq("KO7 layering control: the same probe sees gate_preflight when it IS imported", closure("import gate_preflight"), "True")
    finally:
        cleanup(temp_root)


def test_a_pytest_profile_that_writes_nothing_is_told_what_actually_went_wrong() -> None:
    """There is no flag to name for pytest — the runner passes `--junitxml` itself — so a
    card that named one would send the person after a cure that is not one."""
    root = project("qa-reporter-pytest-")
    try:
        use_project(root)
        task_root = root / "qa-factory" / "artifacts" / TICKET
        r = gate_preflight.Rehearsal(task_root, "A")
        r._reporter_card("s5_reporter", "api", ["TC-001"], "pytest", "tests/test_a.py::test_x",
                         {"why": "no report file was written", "returncode": 4, "stderr": "",
                          "stdout": "ModuleNotFoundError: No module named 'pydantic'\n"},
                         ["poetry", "run", "pytest"])
        change = r.stand_gaps[0]["remedy"]["change"]
        check_in("the card names the real cause instead of a flag", "pydantic", change)
        check_in("and says why no flag is named (t-357: in words, the flag itself is not shown to a person)",
                 "already asks pytest for a JUnit report itself", change)
        check_eq("the remedy is still valid by the contract",
                 C.remedy_errors(r.stand_gaps[0]["remedy"]), [])
    finally:
        cleanup(root)


def test_the_project_can_say_which_test_and_can_say_no() -> None:
    root = project("qa-reporter-named-",
                   rehearsal={"reporter_probe_test": {"web": "tests/test_z_named.py"}})
    try:
        use_project(root)
        r = rehearse(root)
        check_in("the test the project named is the test that runs",
                 "tests/test_z_named.py", r.info[0]["message"])
        check_in("and the card says where the choice came from",
                 "reporter_probe_test", r.info[0]["message"])
    finally:
        cleanup(root)
    root = project("qa-reporter-off-", runner=WRITES_NOTHING,
                   rehearsal={"skip_reporter": True})
    try:
        use_project(root)
        r = rehearse(root)
        check_eq("a project whose one test must not run at a gate says so once",
                 (r.findings, r.stand_gaps, r.info), ([], [], []))
    finally:
        cleanup(root)


def test_a_launcher_that_is_not_here_was_already_asked_about() -> None:
    """`check_s5_executor` asks that question with three answers. A second question about one
    missing binary is a second stop (TP2-2536)."""
    root = project("qa-reporter-nolauncher-", launcher="a-launcher-nobody-installed")
    try:
        use_project(root)
        r = rehearse(root)
        check_eq("the missing launcher raises no card of its own", r.stand_gaps, [])
        check_eq("and no second question", r.findings, [])
        check_in("it is stated as a fact, so the silence is not mistaken for a pass",
                 "was looked up on PATH with PATHEXT and not found", r.info[0]["message"])
    finally:
        cleanup(root)


def test_a_word_already_given_closes_the_card() -> None:
    """A person's word passes any block in this factory, and is not asked for twice."""
    root = project("qa-reporter-waived-", runner=WRITES_NOTHING, helped=True)
    try:
        use_project(root)
        task_root = root / "qa-factory" / "artifacts" / TICKET
        pipeline = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))
        pipeline["stage_overrides"] = [{"stage": "S5", "match": "stand gap: RP-web",
                                        "decision": "accept, report it not executed",
                                        "by": "human"}]
        (task_root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        r = rehearse(root)
        check_eq("the question is not asked again", r.findings, [])
        check_eq("while the card itself still travels, now with the answer on it",
                 len(r.stand_gaps), 1)
    finally:
        cleanup(root)


def test_the_step_is_part_of_the_gate_and_writes_nothing_of_its_own() -> None:
    root = project("qa-reporter-gate-", runner=WRITES_NOTHING, helped=True)
    try:
        use_project(root)
        task_root = root / "qa-factory" / "artifacts" / TICKET
        before = sorted(p.name for p in (task_root / "work").rglob("*"))
        result = gate_preflight.run(task_root, "A")
        check_eq("the reporter is rehearsed inside gate A, not beside it",
                 [f["check"] for f in result["findings"] if f["check"] == "s5_reporter"],
                 ["s5_reporter"])
        check_eq("its card reaches the result the packet reads",
                 [g["id"] for g in result["stand_gaps"]], ["RP-web"])
        check_eq("and the rehearsal still writes nothing",
                 sorted(p.name for p in (task_root / "work").rglob("*")), before)
    finally:
        cleanup(root)


# --- once per project + stand + deployed version (B-151, owner decision D-0019 item 2) ------------
# The launcher below is the project's runner with one more line: it records that it was started.
# The count of those lines is the only honest witness that "no subprocess ran".
COUNT_LAUNCH = ("from pathlib import Path\n"
                "with Path(__file__).with_name('launches.log').open('a') as _f:\n"
                "    _f.write('x' + chr(10))\n")
COUNTED_JUNIT = COUNT_LAUNCH + WRITES_JUNIT
COUNTED_NOTHING = COUNT_LAUNCH + WRITES_NOTHING

PROBE = """import json
import sys
from pathlib import Path
here = Path(__file__).parent
with (here / "probes.log").open("a") as _f:
    _f.write("x" + chr(10))
identity =(here / "identity.txt").read_text(encoding="utf-8").strip()
if identity == "FAIL":
    sys.exit(3)
print(json.dumps({"profile_id": "web", "timestamp": "2026-09-22T10:00:00Z",
                  "environment_id": "localhost", "expected_source_revision": "source-1",
                  "observed_runtime_identity": identity, "evidence_refs": ["probe"],
                  "result": "matched",
                  "provenance": {"technical_verification": True, "source_linkage": "exact",
                                 "deployed_source_revision": "source-1"}}))
"""


def edit_config(root: Path, change) -> None:
    path = root / "qa-factory" / "config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    change(cfg)
    path.write_text(json.dumps(cfg), encoding="utf-8")


def observe(root: Path, identity: str, *, star: bool = False) -> None:
    """Register a runtime probe whose answer is whatever `identity.txt` says right now."""
    (root / "probe.py").write_text(PROBE, encoding="utf-8")
    (root / "identity.txt").write_text(identity, encoding="utf-8")
    spec = {"argv": [sys.executable, str(root / "probe.py")], "cwd": ".", "timeout_s": 20}
    edit_config(root, lambda c: c.__setitem__(
        "execution", {"runtime_probes": {("*" if star else "web"): spec}}))


def redeploy(root: Path, identity: str) -> None:
    (root / "identity.txt").write_text(identity, encoding="utf-8")


def stand(root: Path, name: str) -> None:
    edit_config(root, lambda c: c.__setitem__("environments", [{"name": name}]))


def launches(root: Path) -> int:
    log = root / "launches.log"
    return len(log.read_text(encoding="utf-8").split()) if log.is_file() else 0


def new_process(root: Path):
    """What the next gate call in another process sees: an empty in-process map and a new
    Rehearsal object, with only the durable record carried over."""
    gate_preflight._REPORTER_PROBES.clear()
    return rehearse(root)


def probes(root: Path) -> int:
    log = root / "probes.log"
    return len(log.read_text(encoding="utf-8").split()) if log.is_file() else 0


def record_of(root: Path):
    path = root / "qa-factory" / "state" / "reporter-rehearsals.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def test_the_first_call_rehearses_and_keeps_the_proof() -> None:
    root = project("qa-reporter-keep-", runner=COUNTED_JUNIT)
    try:
        use_project(root)
        observe(root, "build-A")
        stand(root, "stage-1")
        check_eq("no record exists before the first positive rehearsal",
                 record_of(root), None)
        r = new_process(root)
        check_eq("the first call runs the test once", launches(root), 1)
        check_in("and says it proved the report", "1 test(s) counted", r.info[0]["message"])
        saved = record_of(root)
        check_eq("the record is created by it, with its schema", saved["schema_version"], 1)
        rows = list(saved["rehearsals"].values())
        check_eq("with one rehearsal in it", len(rows), 1)
        check_eq("that names the profile", rows[0]["profile_id"], "web")
        check_eq("the stand", rows[0]["environment"], "stage-1")
        check_eq("the version the probe observed", rows[0]["runtime_identity"], "build-A")
        check_eq("the test it ran", rows[0]["chosen"], "tests/test_a_first.py")
        check_eq("the format it read", rows[0]["fmt"], "junit-xml")
        check_eq("how many tests it counted", rows[0]["tests"], 1)
        check("and when", isinstance(rows[0]["at"], str) and rows[0]["at"][:2] == "20")
        # B-220 part 2 (F11): the row says WHAT it proved - the command, by words and by digest (the one definition the
        # onboarding wrote its rows with) - so a later gate tells "the command changed" from "it stopped working"
        import onboarding_probe
        argv = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))["profiles"][0]["commands"]["one_test"]["argv"]
        check_eq("F11: the row carries the argv it proved", rows[0]["argv"], argv)
        check_eq("F11: and its digest, by onboarding_probe.argv_digest (one definition)",
                 rows[0]["argv_digest"], onboarding_probe.argv_digest(argv))
        check_eq("F11: the record says `same_command` for that argv", onboarding_probe.earlier_proof(root, "web", argv)["state"],
                 "same_command")
    finally:
        cleanup(root)


def test_a_new_process_does_not_rehearse_again_and_says_so() -> None:
    root = project("qa-reporter-reuse-", runner=COUNTED_JUNIT)
    try:
        use_project(root)
        observe(root, "build-A")
        stand(root, "stage-1")
        new_process(root)
        r = new_process(root)
        check_eq("no subprocess ran in the second process", launches(root), 1)
        check_eq("and nobody is asked anything", (r.findings, r.stand_gaps), ([], []))
        message = r.info[0]["message"]
        check_in("the note says it was not rehearsed again", "not rehearsed again", message)
        check_in("names the profile", "`web`", message)
        check_in("F11: it names what the proof is OF - this command, by its words, test, format and dependency files",
                 "exactly this command (the same words, test, report format and dependency files)", message)
        check_not_in("F11: and claims neither a stand nor a version, which no longer key the proof", "stand", message)
        check_not_in("F11: nor a version", "version", message)
        check_in("and the date it was proved on", "rehearsed on 20", message)
        check_eq("a third process, too", (new_process(root).info[0]["message"] == message,
                                         launches(root)), (True, 1))
    finally:
        cleanup(root)


def test_a_redeploy_is_not_a_new_rehearsal_the_proof_is_of_the_command() -> None:
    """F11 (owner ruling, B-220): whether a command leaves a report the factory can read is a property of the command on this
    machine, not of the build a stand runs. It replaces the old key that held the observed version."""
    root = project("qa-reporter-redeploy-", runner=COUNTED_JUNIT)
    try:
        use_project(root)
        observe(root, "build-A")
        new_process(root)
        redeploy(root, "build-B")
        r = new_process(root)
        check_eq("F11: a stand that now runs another build is NOT rehearsed again", launches(root), 1)
        check_in("F11: and the note says so", "not rehearsed again", r.info[0]["message"])
        check_eq("F11: one row, the first proof's - the version it saw is information, not a key", sorted(
            v["runtime_identity"] for v in record_of(root)["rehearsals"].values()), ["build-A"])
    finally:
        cleanup(root)


def test_an_edited_dependency_file_is_a_new_rehearsal() -> None:
    """The reporter plugin lives in the dependency files: a changed byte there can change
    whether a report is written at all."""
    root = project("qa-reporter-deps-", runner=COUNTED_JUNIT)
    try:
        use_project(root)
        observe(root, "build-A")
        (root / "requirements.txt").write_text("pytest\n", encoding="utf-8")
        new_process(root)
        new_process(root)
        check_eq("unchanged dependencies are reused", launches(root), 1)
        (root / "requirements.txt").write_text("pytest\npytest-html\n", encoding="utf-8")
        new_process(root)
        check_eq("an edited one is not", launches(root), 2)
        (root / "package.json").write_text("{}", encoding="utf-8")
        new_process(root)
        check_eq("nor is a dependency file that appeared", launches(root), 3)
    finally:
        cleanup(root)


def test_another_stand_is_not_a_new_rehearsal() -> None:
    """F11: the stand is not part of the proof (the onboarding has no pipeline, so no stand: a key that held one would never
    match the proof the onboarding made, and a second stand would pay for the same proof again)."""
    root = project("qa-reporter-stand-", runner=COUNTED_JUNIT)
    try:
        use_project(root)
        observe(root, "build-A")
        stand(root, "stage-1")
        new_process(root)
        stand(root, "stage-2")
        r = new_process(root)
        check_eq("F11: the same command on another stand is NOT rehearsed again", launches(root), 1)
        check_in("F11: and says so", "not rehearsed again", r.info[0]["message"])
        base = gate_preflight.Rehearsal(root / "qa-factory" / "artifacts" / TICKET, "A")
        keys = []
        for name in ("stage-1", "stage-2", "stage-3"):
            stand(root, name)
            other = gate_preflight.Rehearsal(root / "qa-factory" / "artifacts" / TICKET, "A")
            keys.append(other._rehearsal_key("web", root, ["x", "{report_path}"], "tests/test_a_first.py", "junit-xml", "build-A", root))
        check_eq("F11: the key itself is the same for every stand (and every identity offered)", len(set(keys)), 1)
        check("F11: and it is built (an empty key means 'not durable')", bool(keys[0]))
        check_eq("F11: nor does an identity keep it apart",
                 base._rehearsal_key("web", root, ["x"], "t", "junit-xml", "build-A", root),
                 base._rehearsal_key("web", root, ["x"], "t", "junit-xml", "build-B", root))
        check("F11 control: another command IS another key",
              base._rehearsal_key("web", root, ["x"], "t", "junit-xml", "", root) != base._rehearsal_key("web", root, ["y"], "t", "junit-xml", "", root))
    finally:
        cleanup(root)


def test_a_command_or_a_test_that_changed_is_a_new_rehearsal() -> None:
    root = project("qa-reporter-command-", runner=COUNTED_JUNIT)
    try:
        use_project(root)
        new_process(root)
        edit_config(root, lambda c: c["profiles"][0]["commands"]["one_test"]["argv"].append("-x"))
        new_process(root)
        check_eq("another argv is another rehearsal", launches(root), 2)
        edit_config(root, lambda c: c["gate_rehearsal"].update(
            {"reporter_probe_test": {"web": "tests/test_z_named.py"}}))
        new_process(root)
        check_eq("and so is another test", launches(root), 3)
    finally:
        cleanup(root)


def test_a_project_with_no_runtime_probe_reuses_and_records_the_version_as_not_observed() -> None:
    root = project("qa-reporter-unobserved-", runner=COUNTED_JUNIT)
    try:
        use_project(root)
        stand(root, "stage-1")
        new_process(root)
        row = list(record_of(root)["rehearsals"].values())[0]
        check_eq("what could not be observed is recorded as null, not as a version",
                 row["runtime_identity"], None)
        check_eq("the stand the proof was made on is recorded as information", row["environment"], "stage-1")
        r = new_process(root)
        check_eq("the second process does not launch", launches(root), 1)
        check_in("it says it was not rehearsed again", "not rehearsed again", r.info[0]["message"])
    finally:
        cleanup(root)
    root = project("qa-reporter-unnamed-", runner=COUNTED_JUNIT)
    try:
        use_project(root)
        new_process(root)
        r = new_process(root)
        check_in("a project that names no stand is reused too", "not rehearsed again", r.info[0]["message"])
    finally:
        cleanup(root)


def test_a_probe_registered_for_every_profile_is_read() -> None:
    root = project("qa-reporter-star-", runner=COUNTED_JUNIT)
    try:
        use_project(root)
        observe(root, "build-S", star=True)
        new_process(root)
        check_eq("the identity came from the `*` probe",
                 list(record_of(root)["rehearsals"].values())[0]["runtime_identity"], "build-S")
    finally:
        cleanup(root)


def test_a_probe_that_cannot_answer_does_not_matter_to_a_proof_of_the_command() -> None:
    """F11: the version is information, so a stand that cannot be asked neither breaks a proof nor is taken for a match - the
    proof was never about it. (Before B-220 this was a new rehearsal; the gate registry row `reporter_rehearsal_identity` says so.)"""
    root = project("qa-reporter-brokenprobe-", runner=COUNTED_JUNIT)
    try:
        use_project(root)
        observe(root, "build-A")
        new_process(root)
        redeploy(root, "FAIL")
        r = new_process(root)
        check_eq("F11: a stand that cannot be asked does not void the proof of the command", launches(root), 1)
        check_in("F11: and the note says it was not rehearsed again", "not rehearsed again", r.info[0]["message"])
        check_eq("F11: the reuse asked the stand nothing (a probe runs only when a proof is made)", probes(root), 1)
    finally:
        cleanup(root)


def test_a_negative_outcome_is_not_kept_and_the_next_call_looks_again() -> None:
    root = project("qa-reporter-negative-", runner=COUNTED_NOTHING, helped=True)
    try:
        use_project(root)
        observe(root, "build-A")
        r = new_process(root)
        check_eq("no report is a card", len(r.stand_gaps), 1)
        check_eq("nothing was written for it", record_of(root), None)
        new_process(root)
        check_eq("the next call rehearses again, because the fix is what it checks",
                 launches(root), 2)
        (root / "fake_runner.py").write_text(COUNTED_JUNIT, encoding="utf-8")
        r = new_process(root)
        check_eq("after the person's fix the card is gone", (r.findings, r.stand_gaps), ([], []))
        check_eq("and the proof is kept", len(record_of(root)["rehearsals"]), 1)
        new_process(root)
        check_eq("and reused", launches(root), 3)
    finally:
        cleanup(root)
    root = project("qa-reporter-negative-launcher-", launcher="a-launcher-nobody-installed")
    try:
        use_project(root)
        new_process(root)
        check_eq("a launcher that is not here is not kept either", record_of(root), None)
    finally:
        cleanup(root)


def test_a_record_that_does_not_parse_is_said_once_rehearsed_and_overwritten() -> None:
    for prefix, junk in (("qa-reporter-corrupt-", "{not json"),
                         ("qa-reporter-shape-", json.dumps(["a", "list"]))):
        root = project(prefix, runner=COUNTED_JUNIT)
        try:
            use_project(root)
            state = root / "qa-factory" / "state"
            state.mkdir(parents=True, exist_ok=True)
            (state / "reporter-rehearsals.json").write_text(junk, encoding="utf-8")
            r = new_process(root)
            check_eq(f"{prefix}: it rehearses", launches(root), 1)
            said = [i["message"] for i in r.info if "unreadable" in i["message"]]
            check_eq(f"{prefix}: and says so once", len(said), 1)
            check_in(f"{prefix}: in the words of the record's own name",
                     "reporter-rehearsals.json unreadable, rehearsing", said[0])
            check_eq(f"{prefix}: nobody is asked", (r.findings, r.stand_gaps), ([], []))
            check_eq(f"{prefix}: the next positive outcome overwrote it",
                     len((record_of(root) or {}).get("rehearsals") or {}), 1)
            r = new_process(root)
            check_eq(f"{prefix}: and it is reused from then on", launches(root), 1)
            check_eq(f"{prefix}: with no note about a broken file",
                     [i for i in r.info if "unreadable" in i["message"]], [])
        finally:
            cleanup(root)


def test_later_gate_calls_of_one_process_do_not_ask_the_stand_again() -> None:
    """The packet, the stage closure and the orchestrator's `--text` call each rehearse the
    same gate in ONE process: a reuse fills the per-process map like a launch does. B-220 F11: the version no longer keys a
    proof, so a reuse asks the stand nothing at all - only the call that MAKES a proof observes it, for the record."""
    root = project("qa-reporter-once-", runner=COUNTED_JUNIT)
    try:
        use_project(root)
        observe(root, "build-A")
        new_process(root)
        check_eq("the rehearsing call asked the stand once", probes(root), 1)
        new_process(root)
        check_eq("F11: a new process reusing the proof asks it NOT at all", probes(root), 1)
        for n in (1, 2, 3):
            r = rehearse(root)
            check_in(f"call {n} in the same process still says it was not rehearsed again",
                     "not rehearsed again", r.info[0]["message"])
        check_eq("and none of them ran the identity probe", probes(root), 1)
        check_eq("nor the test", launches(root), 1)
    finally:
        cleanup(root)


def test_a_record_that_cannot_be_saved_is_said_and_the_rehearsal_stands() -> None:
    root = project("qa-reporter-nosave-", runner=COUNTED_JUNIT)
    try:
        use_project(root)
        # A FILE where the state directory belongs: the write fails on every platform.
        (root / "qa-factory" / "state").write_text("not a directory", encoding="utf-8")
        r = new_process(root)
        said = [i["message"] for i in r.info if "could not be saved" in i["message"]]
        check_eq("one note says the saving failed", len(said), 1)
        check_in("it names the file", "reporter-rehearsals.json", said[0])
        check_in("and what follows from it", "the next gate rehearses again", said[0])
        check_eq("the rehearsal's own result is unchanged",
                 (r.findings, r.stand_gaps, launches(root)), ([], [], 1))
        check("the proven report is still stated",
              any("1 test(s) counted" in i["message"] for i in r.info))
        new_process(root)
        check_eq("with nothing kept, the next process rehearses again", launches(root), 2)
    finally:
        cleanup(root)


def test_the_reuse_note_names_the_door_to_a_new_rehearsal() -> None:
    root = project("qa-reporter-door-", runner=COUNTED_JUNIT)
    try:
        use_project(root)
        new_process(root)
        note = new_process(root).info[0]["message"]
        check_in("the note says whose entry to remove (F11: the command's, not a stand's)", "remove this command's entry", note)
        check_in("from which file", "qa-factory/state/reporter-rehearsals.json", note)
        check_in("or the file itself", "or the file", note)
        (root / "qa-factory" / "state" / "reporter-rehearsals.json").unlink()
        new_process(root)
        check_eq("and the door works: without the record it rehearses", launches(root), 2)
    finally:
        cleanup(root)


def test_the_files_pytest_reads_its_report_options_from_are_part_of_the_key() -> None:
    root = project("qa-reporter-ini-", runner=COUNTED_JUNIT)
    try:
        use_project(root)
        (root / "pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
        new_process(root)
        new_process(root)
        check_eq("an unchanged pytest.ini is reused", launches(root), 1)
        (root / "pytest.ini").write_text("[pytest]\naddopts = -q -p no:junitxml\n",
                                         encoding="utf-8")
        new_process(root)
        check_eq("an edited pytest.ini is a new rehearsal", launches(root), 2)
        for count, name in enumerate(("tox.ini", "setup.cfg", "conftest.py"), start=3):
            (root / name).write_text("# report options\n", encoding="utf-8")
            new_process(root)
            check_eq(f"a {name} that appeared is a new rehearsal", launches(root), count)
    finally:
        cleanup(root)


def test_a_handed_profile_and_a_switched_off_step_are_left_as_they_were() -> None:
    root = project("qa-reporter-handed-", runner=COUNTED_JUNIT)
    try:
        use_project(root)
        task_root = root / "qa-factory" / "artifacts" / TICKET
        pipeline = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))
        pipeline["stage_overrides"] = [{"stage": "S5", "match": "executor unavailable: web",
                                       "decision": "I run it myself", "by": "human"}]
        (task_root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        r = new_process(root)
        check_eq("a profile the person took over is not run", launches(root), 0)
        check_eq("and nothing is written for it", (r.info, record_of(root)), ([], None))
    finally:
        cleanup(root)
    root = project("qa-reporter-off2-", runner=COUNTED_JUNIT, rehearsal={"skip_reporter": True})
    try:
        use_project(root)
        new_process(root)
        check_eq("skip_reporter runs nothing and writes nothing", (launches(root), record_of(root)),
                 (0, None))
    finally:
        cleanup(root)


# --- B-220 part 2, item 1: the durable proof is of the COMMAND, and a card says whether it changed or stopped ------------------
# The onboarding probe (`onboarding_probe.probe_profiles`) writes a row keyed without a stand and carrying the argv it proved;
# gate A reads the same record (`onboarding_probe.earlier_proof`) and reuses the proof, or rehearses and says why it could not.

def rows_of(root: Path) -> list:
    saved = record_of(root)
    return sorted(((saved or {}).get("rehearsals") or {}).values(), key=lambda row: str(row.get("at")))


def argv_of(root: Path) -> list:
    return json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))["profiles"][0]["commands"]["one_test"]["argv"]


def a_proven_project(prefix: str, **kw) -> Path:
    root = project(prefix, runner=kw.pop("runner", COUNTED_JUNIT), **kw)
    use_project(root)
    new_process(root)       # the proof, by a gate A rehearsal
    return root


# --- B-407 B-deps: the files the key watches are data (references/dependency-files.json) -------------------------------------------
# D-0023: a proof is for a command AND the bytes its report options live in. The list is now the table's `names` and top-level
# `patterns` (the same list the run fingerprint watches), the project's own `run.dependency_files`, and the table's `report_config`.

# The key the code built for this exact fixture BEFORE the table existed (computed by the code of e0fe3ab on these bytes): a literal,
# never a call into the package - the reference project must keep reusing the rows it already has (K-D-1).
PYTHON_FIXTURE_KEY_BEFORE_THE_TABLE = "b39e5885d5bb793bdab3dbeebcfde374a13fea1eb0d2ef052956d61374eba22e"
PYTEST_ARGV = ["python", "-m", "pytest", "<test-file>", "-q"]


def key_of(root: Path, config=None, cwd=None) -> str:
    """The key the gate builds for a pytest profile run in `cwd`, from the project's config on disk or the `config` given (the
    onboarding before `qa-factory/config.json` exists has none)."""
    rehearsal = gate_preflight.Rehearsal(root / "qa-factory" / "artifacts" / TICKET, "A")
    if config is not None:
        rehearsal.config = config
    return rehearsal._rehearsal_key("web", cwd or root, PYTEST_ARGV, "tests/test_a.py", "pytest", "", root)


def python_fixture(root: Path) -> None:
    for name, data in (("pyproject.toml", b'[tool.poetry]\nname = "harness"\n'), ("poetry.lock", b"# poetry lock\n"),
                       ("Makefile", b"all:\n"), ("pytest.ini", b"[pytest]\naddopts = -q\n")):
        (root / name).write_bytes(data)


def test_b_deps_the_python_projects_key_is_the_one_built_before_the_table() -> None:
    root = project("qa-reporter-key-py-")
    try:
        use_project(root)
        python_fixture(root)
        check_eq("K-D-1: the Python fixture's key equals the literal the code built before the table (pyproject.toml, poetry.lock, "
                 "pytest.ini: no newly listed name is present)", key_of(root), PYTHON_FIXTURE_KEY_BEFORE_THE_TABLE)
        (root / "pytest.ini").write_bytes(b"[pytest]\naddopts = -q -p no:junitxml\n")
        check("K-D-1 control: the literal is a key of THESE bytes: an edited pytest.ini is another key",
              key_of(root) != PYTHON_FIXTURE_KEY_BEFORE_THE_TABLE)
    finally:
        cleanup(root)


def test_b_deps_a_java_dotnet_or_js_file_changes_the_key() -> None:
    root = project("qa-reporter-key-new-")
    try:
        use_project(root)
        python_fixture(root)
        base = key_of(root)
        for name, data in (("pom.xml", "<project/>\n"), ("App.csproj", "<Project/>\n"), ("jest.config.js", "module.exports = {};\n"),
                           ("go.mod", "module x\n"), ("karma.conf.js", "module.exports = () => {};\n"), (".runsettings", "<RunSettings/>\n")):
            (root / name).write_text(data, encoding="utf-8")
            first = key_of(root)
            check(f"K-D-2: a {name} that appeared is another key (the Java/.NET/JS project is rehearsed again)", first != base)
            (root / name).write_text(data + "<!-- edited -->\n", encoding="utf-8")
            check(f"K-D-2: and an edited {name} is another key again", key_of(root) not in (base, first))
            (root / name).unlink()
            check_eq(f"K-D-2 control: with {name} gone the key is the base again (what changed it is that file)", key_of(root), base)
        (root / "sub").mkdir()
        (root / "sub" / "App.csproj").write_text("<Project/>\n", encoding="utf-8")
        (root / "sub" / "pom.xml").write_text("<project/>\n", encoding="utf-8")
        check_eq("E-D-3: a pattern and a name read the top level only: a deeper one changes nothing", key_of(root), base)
    finally:
        cleanup(root)


def test_b_deps_the_projects_own_files_are_in_the_key_and_the_onboarding_without_a_config_is_one_rehearsal_more() -> None:
    root = project("qa-reporter-key-own-")
    try:
        use_project(root)
        python_fixture(root)
        on_disk = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        listing = dict(on_disk, run={"dependency_files": ["shared.lock", "sub/deep.lock"]})
        none_present = key_of(root, listing)
        check_eq("E-D-5: files the project lists that are not there change nothing", none_present, key_of(root, on_disk))
        (root / "sub").mkdir()
        (root / "shared.lock").write_text("a\n", encoding="utf-8")
        (root / "sub" / "deep.lock").write_text("b\n", encoding="utf-8")
        gate, onboarding = key_of(root, listing), key_of(root, {})
        check("E-D-3: `run.dependency_files` is the door for a file the table lacks: listed and present, it is in the key", gate != none_present)
        check_eq("E-D-5 TEMPORAL: the onboarding before the config exists has no `run.dependency_files`: its key is the base's, "
                 "and never the gate's (safe: one extra rehearsal, never a wrong reuse)", (onboarding == none_present, onboarding != gate), (True, True))
        before = key_of(root, listing)
        (root / "sub" / "deep.lock").write_text("b changed\n", encoding="utf-8")
        check("a nested path of the door is keyed by its cwd-relative path, and its bytes count", key_of(root, listing) != before)
        check_eq("a config whose `run.dependency_files` is no list is the same as none (and never raises)",
                 key_of(root, dict(on_disk, run={"dependency_files": "shared.lock"})), none_present)
    finally:
        cleanup(root)


def test_b_deps_a_table_that_cannot_be_read_keeps_the_old_files_and_says_so() -> None:
    import hooklib
    root = project("qa-reporter-key-floor-")
    original = hooklib.load_ref_json
    try:
        use_project(root)
        python_fixture(root)
        (root / "pom.xml").write_text("<project/>\n", encoding="utf-8")
        whole = key_of(root)
        hooklib.load_ref_json = lambda name: {}
        rehearsal = gate_preflight.Rehearsal(root / "qa-factory" / "artifacts" / TICKET, "A")
        floor = rehearsal._rehearsal_key("web", root, PYTEST_ARGV, "tests/test_a.py", "pytest", "", root)
        check("E-D-4: with no table the key is built from today's files (pom.xml is not in it) and is not the whole table's", floor != whole)
        (root / "pom.xml").unlink()
        check_eq("E-D-4: and equals the pre-table literal on the Python fixture: never fewer files than before",
                 key_of(root), PYTHON_FIXTURE_KEY_BEFORE_THE_TABLE)
        check_eq("E-D-4: the gate says once that the table could not be read (an INFO line, never a stop)",
                 [i["message"].count("table of dependency files") for i in rehearsal.info if i["check"] == "s5_reporter"], [1])
        rehearsal._rehearsal_key("web", root, PYTEST_ARGV, "tests/test_a.py", "pytest", "", root)
        check_eq("... and not again for the next key of the same gate", len([i for i in rehearsal.info if i["check"] == "s5_reporter"]), 1)
    finally:
        hooklib.load_ref_json = original
        cleanup(root)


def test_b_deps_a_path_on_another_drive_keeps_the_key_and_a_programming_error_in_the_builder_is_said() -> None:
    """FIX 3: `os.path.relpath` raises ValueError across drives; that must cost one path its relative name, never the whole key (D-0023
    reuse lost silently). FIX 5: '' stays "not durable" for OSError/ValueError, but any other exception is a programming error and is said
    once in the gate's INFO line."""
    import execution_request
    root = project("qa-reporter-key-fault-")
    original_relpath, original_table = os.path.relpath, execution_request.dependency_table
    try:
        use_project(root)
        python_fixture(root)
        (root / "pom.xml").write_text("<project/>\n", encoding="utf-8")

        def across_drives(path, start=os.curdir):
            if str(path).endswith("pom.xml"):
                raise ValueError("path is on mount 'D:', start on mount 'C:'")
            return original_relpath(path, start)
        os.path.relpath = across_drives
        first, again = key_of(root), key_of(root)
        check("FIX 3: a path that has no relative name does not empty the key", bool(first))
        check_eq("FIX 3: and the key is stable", first, again)
        (root / "pom.xml").write_text("<project/><!-- edited -->\n", encoding="utf-8")
        check("FIX 3: and its bytes still count", key_of(root) not in (first, ""))
        os.path.relpath = original_relpath

        def broken(*_a, **_k):
            raise RuntimeError("a programming error")
        execution_request.dependency_table = broken
        rehearsal = gate_preflight.Rehearsal(root / "qa-factory" / "artifacts" / TICKET, "A")
        args = ("web", root, PYTEST_ARGV, "tests/test_a.py", "pytest", "", root)
        check_eq("FIX 5: a programming error leaves the key '' (never a wrong match)", rehearsal._rehearsal_key(*args), "")
        rehearsal._rehearsal_key(*args)
        said = [i["message"] for i in rehearsal.info if i["check"] == "s5_reporter"]
        check_eq("FIX 5: ... and says it ONCE, naming the exception class", (len(said), "RuntimeError" in said[0] if said else None), (1, True))

        def unreadable(*_a, **_k):
            raise OSError("cannot read")
        execution_request.dependency_table = unreadable
        quiet = gate_preflight.Rehearsal(root / "qa-factory" / "artifacts" / TICKET, "A")
        check_eq("FIX 5 control: an OSError is 'not durable' as before: key '' and no note", (quiet._rehearsal_key(*args), quiet.info), ("", []))
    finally:
        os.path.relpath = original_relpath
        execution_request.dependency_table = original_table
        cleanup(root)


def test_b_deps_a_row_written_before_a_manifest_appeared_is_rehearsed_once_more_and_replaced() -> None:
    """E-D-2, TEMPORAL, end to end: the project's row was proved when it had no `pom.xml`; the table now lists it, so the key built
    now is another one: the command is rehearsed again, and `_record_rehearsal` replaces the row (one row per command)."""
    root = a_proven_project("qa-reporter-key-java-")
    try:
        check_eq("the first gate rehearses and records one row", (launches(root), len(rows_of(root))), (1, 1))
        new_process(root)
        check_eq("unchanged: the row is reused", launches(root), 1)
        (root / "pom.xml").write_text("<project/>\n", encoding="utf-8")
        new_process(root)
        check_eq("a manifest that appeared is rehearsed again (a proof is never reused across a changed dependency set)", launches(root), 2)
        check_eq("and the row of that command was REPLACED, not added", len(rows_of(root)), 1)
        new_process(root)
        check_eq("the new row serves from then on", launches(root), 2)
        (root / "jest.config.js").write_text("module.exports = {};\n", encoding="utf-8")
        new_process(root)
        check_eq("a report config of another runner that appeared is a new rehearsal too", launches(root), 3)
    finally:
        cleanup(root)


def test_the_onboardings_proof_is_the_proof_gate_a_reuses() -> None:
    import onboarding_probe
    root = project("qa-reporter-onboarded-", runner=COUNTED_JUNIT)
    try:
        use_project(root)
        observe(root, "build-A")          # a project with a registered probe: the old key would never have matched
        stand(root, "stage-1")
        got = onboarding_probe.probe_profiles(root)
        check_eq("the onboarding proved the report by one run", (got["profiles"][0]["report"]["state"], launches(root)), ("proven", 1))
        check_eq("its row says whose proof it is", [row.get("source") for row in rows_of(root)], ["onboarding"])
        r = new_process(root)
        check_eq("F11: gate A does NOT run the test again (the proof is of the command, on a stand that has a version)", launches(root), 1)
        check_in("F11: and says the onboarding proved it", "the onboarding proved it on 20", r.info[0]["message"])
        check_eq("nobody is asked anything", (r.findings, r.stand_gaps), ([], []))
        check_eq("F11: the reuse wrote nothing (still the onboarding's one row)", [row.get("source") for row in rows_of(root)], ["onboarding"])
    finally:
        cleanup(root)


# --- t-411: ONE key for both moments, end to end, and the row an older package wrote ---------------------------------------------
# The live pair on cmp2r (pytest profile `api`): the onboarding row's key `ae60880c...` and the gate's `57a96896...` differed for the
# same command. Cause, by recomputing both keys from the live files (a calculation, nothing run): `ae60880c...` is the key of the
# PART-1 formula - the payload then held `environment: ""` and `runtime_identity: "unobserved"` beside the six fields - and
# `57a96896...` is the key the current code builds, at BOTH moments (the probe subclass and the gate's base give the same hash). So the
# onboarding that wrote the row ran the package of 57b65fb and the gate ran the package of 52c136d: a version skew, not a second
# formula in the current code. The key that existed (`test_the_onboardings_proof_is_the_proof_gate_a_reuses`) could not see it: it ran
# both moments on ONE package, through a non-pytest runner and a gate that ran only `check_s5_reporter`.

def old_formula_key(root: Path, profile_id: str, argv: list, chosen: str, fmt: str, cwd: str = ".") -> str:
    """The key the package of 57b65fb (part 1) built at onboarding, frozen as a literal: the six fields plus `environment: ""` and
    `runtime_identity: "unobserved"` (the probe subclass offered no stand and no identity). NOT a call into the package: a copy of the
    old payload is the only way a test can stand for a row an older package wrote."""
    import hashlib
    folder = (root / cwd).resolve()
    # the six dependency names and the four report-config names of that package, frozen with it (not the table's lists)
    frozen = {"pyproject.toml", "poetry.lock", "requirements.txt", "setup.cfg", "package.json", "package-lock.json",
              "pytest.ini", "tox.ini", "conftest.py"}
    deps = {name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
            for name in sorted(frozen) if (folder / name).is_file()}
    payload = {"profile_id": profile_id, "cwd": cwd, "argv": list(argv), "chosen": chosen, "fmt": fmt, "environment": "",
               "runtime_identity": "unobserved", "dependencies": deps}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def pytest_shaped_project(prefix: str) -> Path:
    """A project whose profile runs a real pytest on one existing test, with a registered runtime probe and a named stand: the two things
    an older key held and onboarding cannot know."""
    root = project(prefix)
    use_project(root)
    command = ["python", "-m", "pytest", "<test-file>", "-q"]
    # the command runs in `tests`, the folder the toolchain collect reports its node ids from
    edit_config(root, lambda c: (c["profiles"][0].pop("reporter", None),
                                 c["profiles"][0]["commands"]["one_test"].update(argv=command, cwd="tests"),
                                 c.__setitem__("test_command_templates", {"one_test": "python -m pytest <test-file>"})))
    observe(root, "build-A")
    stand(root, "stage-1")
    return root


def counting_runs():
    """(counter, restore): every real run of a test command by either moment goes through `Rehearsal._probe_reporter` (the probe's own
    override calls the base), so patching the base counts the runs of BOTH entry points."""
    counter = {"runs": 0}
    original = gate_preflight.Rehearsal._probe_reporter

    def counted(self, *args, **kwargs):
        counter["runs"] += 1
        return original(self, *args, **kwargs)
    gate_preflight.Rehearsal._probe_reporter = counted
    return counter, lambda: setattr(gate_preflight.Rehearsal, "_probe_reporter", original)


def the_whole_gate(root: Path) -> dict:
    gate_preflight._REPORTER_PROBES.clear()
    return gate_preflight.run(root / "qa-factory" / "artifacts" / TICKET, "A")


def test_t411_the_probe_writes_and_the_whole_gate_reads_one_key_end_to_end() -> None:
    """Through the two REAL entry points on one fixture: `onboarding_probe.probe_profiles` writes its row, `gate_preflight.run` (the
    whole gate: the toolchain collect, then the reporter step) reads it. A pytest-shaped profile, a stand and a runtime probe that the
    older key held. No row is built by hand."""
    import onboarding_probe
    root = pytest_shaped_project("qa-reporter-e2e-")
    counter, restore = counting_runs()
    try:
        got = onboarding_probe.probe_profiles(root)
        check_eq("the probe proved the report by ONE run of a real pytest", (got["profiles"][0]["report"]["state"], counter["runs"]), ("proven", 1))
        written = record_of(root)["rehearsals"]
        check_eq("and wrote ONE row, the onboarding's, carrying the argv", [(r.get("source"), r.get("argv_digest") == onboarding_probe.argv_digest(r["argv"]))
                                                                            for r in written.values()], [("onboarding", True)])
        result = the_whole_gate(root)
        check_eq("t-411: the whole gate did NOT run the test again (the proof the probe wrote is the proof it read)", counter["runs"], 1)
        check_eq("t-411: the key it looked up is the key the probe wrote: the record is byte-for-byte what the probe left", record_of(root)["rehearsals"], written)
        said = [i["message"] for i in result["info"] if i["check"] == "s5_reporter"]
        check_eq("t-411: and says whose proof it used", [("the onboarding proved it on 20" in m, "not rehearsed again" in m) for m in said], [(True, True)])
        check_eq("nobody is asked about the report", [f for f in result["findings"] if f["check"] == "s5_reporter"], [])
        check_eq("the probe subclass and the gate's own class build the SAME key from the same six inputs",
                 len({onboarding_probe.ProbeRehearsal(root)._rehearsal_key("web", root, ["x"], "t", "pytest", i, root) for i in ("", "build-A")}
                      | {gate_preflight.Rehearsal(root / "qa-factory" / "artifacts" / TICKET, "A")._rehearsal_key("web", root, ["x"], "t", "pytest", i, root)
                         for i in ("", "build-A")}), 1)
    finally:
        restore()
        cleanup(root)


def test_t411_a_row_the_part_one_package_wrote_is_read_as_none_rehearsed_once_then_replaced() -> None:
    """The live pair: the onboarding ran on the package of 57b65fb, the gate on the next one. Its row carries the argv and the digest, so
    `earlier_proof` says `same_command`, and its KEY is of the older formula, which no key built now equals: the gate must not reuse
    it (a key built for other bytes is never a proof), must not crash, rehearses the command ONCE, and the next write drops the old row
    (one row per command) so the gate's own row serves from then on."""
    import onboarding_probe
    root = pytest_shaped_project("qa-reporter-skew-")
    counter, restore = counting_runs()
    try:
        argv = argv_of(root)
        path = root / "qa-factory" / "state" / "reporter-rehearsals.json"
        onboarding_probe.probe_profiles(root)          # the probe's own writing path makes the row ...
        (current_key, row), = json.loads(path.read_text(encoding="utf-8"))["rehearsals"].items()
        old = old_formula_key(root, "web", argv, row["chosen"], row["fmt"], cwd="tests")
        check("... and the older formula gives another key for the very same inputs (the live pair)", old != current_key)
        path.write_text(json.dumps({"schema_version": 1, "rehearsals": {old: row}}), encoding="utf-8")   # ... which an older package would have filed it under
        counter["runs"] = 0
        check_eq("the record answers `same_command` for it (the digest is the command's)", onboarding_probe.earlier_proof(root, "web", argv)["state"], "same_command")
        the_whole_gate(root)
        check_eq("no false reuse: the older key does not match what is built now, so the command is rehearsed - once", counter["runs"], 1)
        rows = record_of(root)["rehearsals"]
        check_eq("the next write dropped the older row: one row for the command, the gate's own (no `source`)",
                 ([k == old for k in rows], [r.get("source") for r in rows.values()]), ([False], [None]))
        the_whole_gate(root)
        check_eq("and the gate's row serves from then on", counter["runs"], 1)
        # the same file with the older row and NO readable digest is simply not a proof: no crash either
        path.write_text(json.dumps({"schema_version": 1, "rehearsals": {old: {"at": "x", "profile_id": "web"}}}), encoding="utf-8")
        the_whole_gate(root)
        check_eq("a row of the oldest form (no argv) is read as `none`: rehearsed, no crash", counter["runs"], 2)
    finally:
        restore()
        cleanup(root)


def test_the_same_command_that_stops_writing_a_report_is_said_to_have_stopped() -> None:
    root = a_proven_project("qa-reporter-stopped-")
    try:
        (root / "fake_runner.py").write_text(COUNTED_NOTHING, encoding="utf-8")
        (root / "requirements.txt").write_text("pytest\n", encoding="utf-8")      # what the proof was about moved: the key misses
        r = new_process(root)
        check_eq("N3: the first call after the break is the conductor's finding - no card yet", (r.stand_gaps, len(r.findings)), ([], 1))
        helper_turn(root)
        r = new_process(root)
        check_eq("F11: the same words over other dependency files are rehearsed again, not reused (once for the finding, once for the card)", launches(root), 3)
        what = r.stand_gaps[0]["what"]
        check("F11: 'it stopped working' - the SAME digest failing now",
              what.startswith("the command stopped working: a run of exactly this command left a report the factory could read on 20"), what)
        check_not_in("and not the other sentence", "the command changed", what)
        check_in("the card still says what is wrong now", "web writes no junit-xml report", what)
    finally:
        cleanup(root)


def test_a_changed_command_that_fails_is_said_to_have_changed_and_the_old_proof_stays() -> None:
    import onboarding_probe
    root = a_proven_project("qa-reporter-changed-")
    try:
        old = argv_of(root)
        (root / "fake_runner.py").write_text(COUNTED_NOTHING, encoding="utf-8")
        edit_config(root, lambda c: c["profiles"][0]["commands"]["one_test"]["argv"].append("-x"))
        helper_turn(root)
        r = new_process(root)
        check_eq("a different argv is rehearsed, never reused (the invariant)", launches(root), 2)
        what = r.stand_gaps[0]["what"]
        check("F11: 'the command changed' - another digest", what.startswith("the command changed since it was last proved: "), what)
        check_in("with the day of the proof it is compared to", " on 20", what)
        check_not_in("and not 'stopped working'", "stopped working", what)
        check_eq("conflict (i): the old row stays for the old argv (a failure writes nothing)", [row["argv"] for row in rows_of(root)], [old])
        check_eq("and it is still a proof of the OLD command", onboarding_probe.earlier_proof(root, "web", old)["state"], "same_command")
        (root / "fake_runner.py").write_text(COUNTED_JUNIT, encoding="utf-8")
        new_process(root)
        check_eq("the new command, once it proves, has its own row beside the old one", [row["argv"] for row in rows_of(root)], [old, old + ["-x"]])
        check_eq("and the next gate reuses it", (new_process(root).stand_gaps, launches(root)), ([], 3))
    finally:
        cleanup(root)


def test_a_command_never_proven_is_not_said_to_have_stopped() -> None:
    root = project("qa-reporter-never-", runner=COUNTED_NOTHING, helped=True)
    try:
        use_project(root)
        what = new_process(root).stand_gaps[0]["what"]
        check_eq("FR-41: no record, no 'no longer': the card says only what is wrong now",
                 [phrase for phrase in ("stopped working", "has changed", "changed since", "could not be read") if phrase in what], [])
        check("and it begins with the profile", what.startswith("web writes no junit-xml report"), what)
    finally:
        cleanup(root)


def test_a_record_that_cannot_be_read_is_never_a_pass_and_the_card_says_so() -> None:
    import onboarding_probe
    root = project("qa-reporter-unreadable-", runner=COUNTED_NOTHING, helped=True)
    try:
        use_project(root)
        state = root / "qa-factory" / "state"
        state.mkdir(parents=True, exist_ok=True)
        (state / "reporter-rehearsals.json").write_text("{not json", encoding="utf-8")
        r = new_process(root)
        check_eq("FR-59: an unreadable record is no proof: the gate rehearses", launches(root), 1)
        what = r.stand_gaps[0]["what"]
        check_in("and when it cannot establish the report, the card says the record could not be read", "record of earlier proofs could not be read", what)
        check_not_in("without claiming it stopped or changed", "stopped working", what)
    finally:
        cleanup(root)
    root = project("qa-reporter-unreadable-timeout-", runner="import time\ntime.sleep(30)\n", rehearsal={"reporter_timeout_s": 1})
    try:
        use_project(root)
        state = root / "qa-factory" / "state"
        state.mkdir(parents=True, exist_ok=True)
        (state / "reporter-rehearsals.json").write_text("{not json", encoding="utf-8")
        r = new_process(root)
        check_in("a rehearsal that cannot finish says the record could not be read either",
                 "record of earlier proofs could not be read either", r.findings[0]["message"])
    finally:
        cleanup(root)
    root = a_proven_project("qa-reporter-reader-broken-")
    try:
        original = onboarding_probe.earlier_proof
        onboarding_probe.earlier_proof = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("the reader is broken"))
        try:
            new_process(root)
        finally:
            onboarding_probe.earlier_proof = original
        check_eq("FR-59: a proof whose reader cannot answer is not reused: it is rehearsed", launches(root), 2)
    finally:
        cleanup(root)


def test_a_state_file_of_the_old_form_is_inert_and_the_next_proof_rewrites_it() -> None:
    """TEMPORAL: rows written before B-220 part 2 were keyed with the stand and the version and carried no argv."""
    import hashlib
    import onboarding_probe
    legacy = {"schema_version": 1, "rehearsals": {"a" * 64: {
        "at": "2026-09-01T10:00:00+00:00", "profile_id": "web", "environment": "stage-1", "runtime_identity": "build-A",
        "chosen": "tests/test_a_first.py", "fmt": "junit-xml", "tests": 1}}}
    root = project("qa-reporter-legacy-", runner=COUNTED_NOTHING, helped=True)
    try:
        use_project(root)
        path = root / "qa-factory" / "state" / "reporter-rehearsals.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(legacy), encoding="utf-8")
        argv = argv_of(root)
        check_eq("an old-form row is read as `none`: it never counts as a proof", onboarding_probe.earlier_proof(root, "web", argv)["state"], "none")
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        r = new_process(root)
        check_eq("it does not crash and it does not reuse: the gate rehearses", (launches(root), len(r.stand_gaps)), (1, 1))
        check_eq("a failing rehearsal does not touch the file (a negative outcome is never written)", hashlib.sha256(path.read_bytes()).hexdigest(), before)
        (root / "fake_runner.py").write_text(COUNTED_JUNIT, encoding="utf-8")
        new_process(root)
        rows = rows_of(root)
        check_eq("the move that rewrites it is the next PROVEN rehearsal: the old row is gone, the new one carries the argv", [row.get("argv") for row in rows], [argv])
        check_eq("and the next gate reuses it", (new_process(root).stand_gaps, launches(root)), ([], 2))
    finally:
        cleanup(root)


def test_one_row_per_command_a_newer_proof_of_the_same_words_replaces_the_older() -> None:
    root = a_proven_project("qa-reporter-onerow-")
    try:
        first = rows_of(root)
        (root / "requirements.txt").write_text("pytest\n", encoding="utf-8")
        new_process(root)
        check_eq("same words over other dependency files: re-proved, and still ONE row for that command", (launches(root), len(rows_of(root))), (2, 1))
        check("the surviving row is the newer one", rows_of(root)[0]["at"] >= first[0]["at"])
    finally:
        cleanup(root)


def test_a_word_to_go_on_without_the_report_does_not_hide_a_proof() -> None:
    """Conflict (ii): `accept` on the card, and a rehearsal that now reads the report. The PROOF wins what the gate says and
    records; the person's word is not erased (it stays in the pipeline), and what S5 does with an accepted case is not decided here."""
    root = project("qa-reporter-accept-then-proof-", runner=COUNTED_JUNIT)
    try:
        use_project(root)
        task_root = root / "qa-factory" / "artifacts" / TICKET
        pipeline_path = task_root / "pipeline.json"
        pipeline = json.loads(pipeline_path.read_text(encoding="utf-8"))
        pipeline["stage_overrides"] = [{"stage": "S5", "match": "stand gap: RP-web", "decision": "accept - the person wrote: TC-001: accept",
                                        "by": "human"}]
        pipeline_path.write_text(json.dumps(pipeline), encoding="utf-8")
        r = new_process(root)
        check_eq("no card and no question: the report is read", (r.findings, r.stand_gaps), ([], []))
        check_in("the proof is STATED, with the person's earlier word beside it", "you had said to go on without this report", r.info[0]["message"])
        check_in("and says the word stays on the record", "stays on the record", r.info[0]["message"])
        check_eq("the proof is recorded (the waiver did not stop the record)", len(rows_of(root)), 1)
        check_eq("the person's word is not erased", json.loads(pipeline_path.read_text(encoding="utf-8"))["stage_overrides"], pipeline["stage_overrides"])
        again = new_process(root)
        check_in("a reuse says it too", "you had said to go on without this report", again.info[0]["message"])
    finally:
        cleanup(root)
    root = project("qa-reporter-no-accept-", runner=COUNTED_JUNIT)
    try:
        use_project(root)
        check_not_in("control: with no such word the line does not mention one", "you had said", new_process(root).info[0]["message"])
    finally:
        cleanup(root)


# --- B-220 part 2, item 3 (F6): the `the fix:` line may carry a real command; nothing else of the card may -------------------

def a_card_with(argv: list, what_extra: str = ""):
    """(root, the card's lines, the gaps) for a reporter card of profile `web` whose recorded command is `argv`."""
    import gate_brief
    import stand_gaps
    root = project("qa-reporter-fixline-", runner=WRITES_NOTHING, helped=True)
    use_project(root)
    task_root = root / "qa-factory" / "artifacts" / TICKET
    r = gate_preflight.Rehearsal(task_root, "A")
    r._reporter_card("s5_reporter", "web", ["TC-001"], "none", "tests/test_a_first.py",
                     {"why": "no report file was written", "returncode": 0, "stderr": "", "stdout": ""}, argv, argv=argv)
    gaps = stand_gaps.collect(task_root, "A", rehearsal={"stand_gaps": r.stand_gaps})
    if what_extra:
        gaps[0]["missing"] = what_extra + " " + gaps[0]["missing"]       # at the front: the card cuts a `missing` line at 240
    return root, gate_brief.stand_gap_card_lines(task_root, gaps), gaps


def test_the_fix_line_carries_the_recorded_command_and_passes_the_text_rules() -> None:
    import human_text
    command = ["python", "manage.py", "test", "--junitxml={report_path}", "<test-id>"]
    root, lines, gaps = a_card_with(command)
    try:
        fix = next(line for line in lines if line.strip().startswith("the fix:"))
        check_in("F6: the action line names the command the profile records NOW, in backquotes",
                 "(the command recorded now: `python manage.py test --junitxml={report_path} <test-id>`)", fix)
        check_in("with the script name and the flag a real command has", "manage.py", fix)
        check_eq("F6: the whole card passes the text rules - the flag and the script name are legal on that line only",
                 [p["rule"] for p in human_text.shape_problems("\n".join(lines))], [])
        check_eq("and the remedy is still valid by the contract", C.remedy_errors(gaps[0]["remedy"]), [])
        # the negative twin: the SAME command anywhere else in the card is refused
        _root2, dirty, _ = a_card_with(command, what_extra="because python manage.py test --junitxml=out.xml wrote nothing")
        try:
            check_eq("F6 negative twin: the same command in the card's prose is refused (script name and flag)",
                     sorted(p["rule"] for p in human_text.shape_problems("\n".join(dirty))), ["flag", "script_name"])
        finally:
            cleanup(_root2)
    finally:
        cleanup(root)


def test_a_recorded_command_the_text_rules_refuse_is_left_off_the_fix_line_not_forced_onto_it() -> None:
    import human_text
    command = ["python", "-c", "settings=true", "<test-id>"]       # `settings=true` is a field-with-its-machine-value shape: refused on any line
    root, lines, _gaps = a_card_with(command)
    try:
        fix = next(line for line in lines if line.strip().startswith("the fix:"))
        check_not_in("F6: a command that would dirty the card is not printed (error direction: the person sees less)", "recorded now", fix)
        check_eq("and the card is clean", [p["rule"] for p in human_text.shape_problems("\n".join(lines))], [])
    finally:
        cleanup(root)


def test_a_person_command_at_the_gate_is_probed_and_never_reused_and_the_old_proof_stays() -> None:
    """Conflict (i): `same_command` reuse vs a person's `command` answer. The person's command has NO proof, so it is probed (one
    run of its own) and not reused; the old row stays for the old argv; the probe leaves no row (a candidate is measured, never
    remembered, until the yes and the next gate's own rehearsal)."""
    import gate_brief
    import onboarding_probe
    root = a_proven_project("qa-reporter-person-command-")
    proposals = temp_dir("qa-reporter-person-command-proposals-")
    try:
        old = argv_of(root)
        (root / "person_runner.py").write_text(COUNTED_JUNIT, encoding="utf-8")
        gap = {"id": "RP-web", "case_id": "TC-001", "remedy": {"kind": "reporter", "profile": "web", "offers": ["command", "theirs", "handed", "accept"]}}
        line = "python person_runner.py {report_path} <test-id>"
        asked = gate_brief.probe_reporter_command(root, gap, line, proposals)
        check_eq("the person's command is proven by its OWN run: not reused from the old command's proof", (asked["state"], launches(root)), ("ask", 2))
        check_eq("the old row stays, for the old argv, and the probe wrote no row of its own", [row["argv"] for row in rows_of(root)], [old])
        new = asked["new"]
        check_eq("the record still answers `same_command` for the old and `command_changed` for the new",
                 (onboarding_probe.earlier_proof(root, "web", old)["state"], onboarding_probe.earlier_proof(root, "web", new)["state"]),
                 ("same_command", "command_changed"))
        sealed = json.loads(Path(asked["proposal"]["path"]).read_text(encoding="utf-8"))
        done = gate_brief.apply_reporter_command(root, sealed, TICKET, gap, line)
        check_eq("applied on the yes", done["state"], "applied")
        r = new_process(root)
        check_eq("the next gate rehearses the NEW command (no proof of it yet) and proves it", (launches(root), r.stand_gaps), (3, []))
        check_eq("and now both commands have their own row", [row["argv"] for row in rows_of(root)], [old, new])
    finally:
        cleanup(root)
        cleanup(proposals)


def test_the_fix_line_limit_never_cuts_inside_a_command() -> None:
    """The limit this change introduces: a reporter card's fix line is cut at 480 characters (240 for the other cards), and a cut
    never leaves a backquoted command open. AT the limit nothing is cut; BEYOND it the span that would be cut goes whole."""
    import gate_brief
    at = "x " * 239 + "yy"                                         # exactly 480
    check_eq("AT the limit: untouched", (len(at), gate_brief._clip_whole_spans(at, 480)), (480, at))
    over = at + "z"
    clipped = gate_brief._clip_whole_spans(over, 480)
    check("BEYOND it: cut, marked", len(clipped) <= 481 and clipped.endswith("…"), clipped[-20:])
    spans = "a " * 230 + "`" + "b" * 40 + "`"                       # the cut at 480 falls inside the span
    check_eq("a cut that would fall inside a span goes before the whole span (no stray backquote)",
             (gate_brief._clip_whole_spans(spans, 480).count("`") % 2, "b" in gate_brief._clip_whole_spans(spans, 480)), (0, False))
    command = ["python", "-m", "tests.run"] + [f"--option-number-{n}-with-a-long-name" for n in range(30)] + ["<test-id>"]
    root, lines, _gaps = a_card_with(command)
    try:
        fix = next(line for line in lines if line.strip().startswith("the fix:"))
        check_eq("a very long recorded command: the line is clipped, balanced, and never shows half a command",
                 (len(fix.split("the fix:  ", 1)[1]) <= 481, fix.count("`") % 2), (True, 0))
    finally:
        cleanup(root)


# --- B-414 (D-0029, D-0032): the environment record is read AFTER the probe, on the card branch only -------------------------

ZERO_TESTS = """import sys
from pathlib import Path
Path(sys.argv[1]).write_text('<?xml version="1.0"?><testsuite name="s" tests="0" failures="0" errors="0" skipped="0"/>', encoding="utf-8")
sys.exit(0)
"""
ZERO_TESTS_FAILING = ZERO_TESTS.replace("sys.exit(0)", "sys.exit(4)")


def record_for(root: Path, **gap) -> dict:
    """One `accept always` for the level `web` of this project's CURRENT command, as the person's word would leave it."""
    import environment_record as ER
    config = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
    key = ER.property_key(dict({"scope": "level", "contour": "web", "reason_class": "zero_tests", "exit_code": 0}, **gap), config, "this stand")
    row, problem, _created = ER.record(root, key, "accept", "web: accept always", "T-0", "the web tests")
    assert row is not None, problem
    return row


def test_b414_a_covered_level_is_not_carded_but_the_probe_still_runs() -> None:
    root = project("qa-reporter-cover-", runner=ZERO_TESTS, helped=True)
    counter, restore = counting_runs()
    try:
        use_project(root)
        gate_preflight._REPORTER_PROBES.clear()
        r = rehearse(root)
        check_eq("control: with no record the level is a card (the report counts no test), `zero_tests`, a normal exit, and a key",
                 (len(r.stand_gaps), r.stand_gaps[0]["reason_class"], r.stand_gaps[0]["exit_code"], bool(r.stand_gaps[0]["property_key"]), r.stand_gaps[0]["lasting"]),
                 (1, "zero_tests", 0, True, ""))
        check_eq("control: and nothing is covered", r.covered_gaps, [])
        ep = record_for(root)
        gate_preflight._REPORTER_PROBES.clear()
        counter["runs"] = 0
        r = rehearse(root)
        check_eq("R7: with the record: no card and no finding", (r.stand_gaps, r.findings), ([], []))
        check_eq("R7: the covered gap is kept, with the record's row under `property`",
                 [(g["id"], g["scope"], g["cases"], g["property"]["id"]) for g in r.covered_gaps], [("RP-web", "level", ["TC-001"], ep["id"])])
        check_eq("E15: the cover sits AFTER the probe - the test command ran once", counter["runs"], 1)
        check_in("and one note says it in words", "not asked - on this environment the web tests cannot be checked", r.info[-1]["message"])
        result = gate_preflight.run(root / "qa-factory" / "artifacts" / TICKET, "A")
        check_eq("the result carries the covered gaps for the packet and the driver", [g["id"] for g in result["covered_gaps"]], ["RP-web"])
        import stand_gaps
        covered = stand_gaps.covered_a(root / "qa-factory" / "artifacts" / TICKET, result)
        check_eq("`stand_gaps.covered_a` maps them as gate A gaps (the same mapping as the cards)",
                 [(g["id"], g["gate"], g["the_test"], g["property"]["id"]) for g in covered], [("RP-web", "A", "every web test of this story", ep["id"])])
        # E4: another command is not covered, and the card says the earlier answer no longer applies
        config_path = root / "qa-factory" / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["profiles"][0]["commands"]["one_test"]["argv"].append("--other")
        config_path.write_text(json.dumps(config), encoding="utf-8")
        gate_preflight._REPORTER_PROBES.clear()
        r = rehearse(root)
        check_eq("N3: a command the helper has not had its turn on is the conductor's finding first - no card, nothing covered",
                 (len(r.stand_gaps), len(r.findings), r.covered_gaps), (0, 1, []))
        helper_turn(root)
        gate_preflight._REPORTER_PROBES.clear()
        r = rehearse(root)
        check_eq("E4: another command: the card is shown, nothing is covered", (len(r.stand_gaps), r.covered_gaps), (1, []))
        check_in("E4: and says the command changed since the earlier answer", "the command changed since", r.stand_gaps[0]["changed_since"])
        import gate_brief
        check_in("E4: the card prints it", "your earlier answer for this environment does not apply now: the command changed since",
                 "\n".join(gate_brief.stand_gap_card_lines(None, stand_gaps.collect(root / "qa-factory" / "artifacts" / TICKET, "A", rehearsal={"stand_gaps": r.stand_gaps}))))
        # E3: the contour was renamed: the old answer covers nothing, and a note names the contour it was given for
        config["profiles"][0]["commands"]["one_test"]["argv"].remove("--other")
        config["profiles"][0]["profile_id"] = "web2"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        helper_turn(root)
        gate_preflight._REPORTER_PROBES.clear()
        r = rehearse(root)
        check_eq("E3: a renamed contour: asked, nothing covered", (len(r.stand_gaps), r.covered_gaps), (1, []))
        check("E3: and a note names the contour the record was given for", any("`web`" in i["message"] and "no longer a test command" in i["message"] for i in r.info),
              str([i["message"] for i in r.info]))
    finally:
        restore()
        cleanup(root)


def test_b414_the_record_never_hides_a_report_the_probe_reads() -> None:
    root = project("qa-reporter-cover-e7-", runner=WRITES_JUNIT)
    try:
        use_project(root)
        record_for(root)
        gate_preflight._REPORTER_PROBES.clear()
        r = rehearse(root)
        check_eq("E7: a contour the probe now reads has no gap and is not `covered`", (r.stand_gaps, r.findings, r.covered_gaps), ([], [], []))
        check_in("E7: the proof is stated", "1 test(s) counted", r.info[0]["message"])
    finally:
        cleanup(root)


def test_b414_a_fault_of_a_file_or_the_machine_is_never_keyed_and_never_covered() -> None:
    for label, runner, reason in (("a report that was not written", WRITES_NOTHING, "no_file"),
                                  ("zero tests after an error exit", ZERO_TESTS_FAILING, "zero_tests")):
        root = project("qa-reporter-fault-", runner=runner, helped=True)
        try:
            use_project(root)
            record_for(root)                      # a row for the CONFIGURATION case exists; it must not cover a fault
            gate_preflight._REPORTER_PROBES.clear()
            r = rehearse(root)
            gap = r.stand_gaps[0]
            check_eq(f"M13: {label}: a card, a typed reason, no key, and the reason there is none is `fault`",
                     (len(r.stand_gaps), gap["reason_class"], gap["property_key"], gap["lasting"], r.covered_gaps), (1, reason, None, "fault", []))
            import gate_brief
            card = "\n".join(gate_brief.stand_gap_card_lines(None, [dict(gap, gate="A", stage="S5", case_id="", missing="x", the_test="x", requirement="")]))
            check_not_in(f"M13: {label}: the card offers no `accept always`", "accept always", card)
            check_in(f"M13: {label}: and says why", "not a property of the environment", card)
        finally:
            cleanup(root)


def test_b414_an_unreadable_record_covers_nothing_and_a_rehearsal_with_no_story_never_asks_it() -> None:
    root = project("qa-reporter-cover-e9-", runner=ZERO_TESTS, helped=True)
    try:
        use_project(root)
        record_for(root)
        import environment_record as ER
        ER.record_path(root).write_text("{broken", encoding="utf-8")
        gate_preflight._REPORTER_PROBES.clear()
        r = rehearse(root)
        check_eq("E9: an unreadable record: the card is shown, nothing is covered", (len(r.stand_gaps), r.covered_gaps), (1, []))
        check_in("E9: and one note says the record could not be read", "the environment record could not be read", r.info[-1]["message"])
        # E16: the onboarding probe has no story - its rehearsal never asks the record, even a good one
        ER.record_path(root).unlink()
        record_for(root)
        import onboarding_probe
        got = onboarding_probe.probe_profiles(root)
        check_eq("E16: the onboarding probe still reports the unread report (no cover check runs)", got["profiles"][0]["report"]["state"], "no_report")
    finally:
        cleanup(root)


TRX_TEXT = ('<?xml version="1.0"?><TestRun xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010"><Results>'
            '<UnitTestResult testId="1" testName="A.B" outcome="Passed" duration="00:00:01"/></Results>'
            '<TestDefinitions><UnitTest id="1" name="A.B"><TestMethod className="A" name="B"/></UnitTest></TestDefinitions>'
            '<ResultSummary outcome="Completed"><Counters total="1" executed="1" passed="1" failed="0" error="0" notExecuted="0" inconclusive="0"/>'
            '</ResultSummary></TestRun>')
WRITES_TRX = f"""import sys
from pathlib import Path
Path(sys.argv[1]).write_text({TRX_TEXT!r}, encoding="utf-8")
"""
# a TRX at the report path AND a JUnit file beside it: the declared reader (or the empty kind's own) fails on the first, and BOTH other
# readers fit somewhere in the run's files - the case where code never picks (G11)
WRITES_BOTH = WRITES_TRX + """Path(sys.argv[1]).with_name("TESTS-extra.xml").write_text(
    '<testsuite name="s" tests="1"><testcase classname="c" name="t"/></testsuite>', encoding="utf-8")
"""
WRITES_JUNK = """import sys
from pathlib import Path
Path(sys.argv[1]).write_bytes(bytes(range(256)) * 4)
"""
WRITES_MANY = """import sys
from pathlib import Path
base = Path(sys.argv[1])
for index in range(int(sys.argv[4])):
    base.with_name("part-%d.bin" % index).write_bytes(b"x" * int(sys.argv[3]))
"""


def no_kind(root: Path) -> None:
    """The profile records no report kind (B-416 N6 applies only then)."""
    edit_config(root, lambda c: c["profiles"][0].pop("reporter", None))


def classes(r) -> list:
    """The class of every finding of a rehearsal: a CARD is a `person_decides` finding AND a stand-gap row, the conductor's call is a
    `factory_fixable` finding and no row."""
    return [f["class"] for f in r.findings]


def kept_manifest(root: Path) -> dict:
    return json.loads((root / "qa-factory" / "state" / "reporter-unread" / "web" / "manifest.json").read_text(encoding="utf-8"))


def test_b416_n3_an_unread_report_goes_to_the_conductor_first_and_the_person_only_after() -> None:
    import report_adapt
    root = project("qa-reporter-n3-", runner=WRITES_TRX)
    try:
        use_project(root)
        no_kind(root)
        r = rehearse(root)
        check_eq("N3: no countable row: ONE finding, no card and no cover (acceptance key 1)", (len(r.findings), r.stand_gaps, r.covered_gaps), (1, [], []))
        finding = r.findings[0]
        check_eq("N3: it is the conductor's (`factory_fixable`) and of the check `s5_reporter`", (finding["class"], finding["check"].startswith("s5_reporter")),
                 ("factory_fixable", True))
        check_eq("N3: the typed fields: profile, digest, where it is kept, the reader that fits, the declared kind",
                 (finding["profile"], bool(finding["argv_digest"]), finding["kept"], finding["fit"], finding["declared_kind"]),
                 ("web", True, "qa-factory/state/reporter-unread/web/", "trx", ""))
        check_eq("N3: the fix is in WORDS and names no script", (finding["fix"], "report_adapt" in finding["fix"] or ".py" in finding["fix"]),
                 ("the factory's helper reads the kept report and records what it changed or understood", False))
        check_in("N3: the message says what was tried and where it is kept", "only trx reads a test in it; the report is kept in qa-factory/state/reporter-unread/web/", finding["message"])
        check_eq("N6: exactly one reader fits and the declared kind is empty: the finding carries the typed `report_adapt.py kind` argv",
                 (finding.get("argv") or [])[:6], ["{python}", "{plugin_root}/scripts/report_adapt.py", "kind", "--profile", "web", "--reader"])
        check_eq("N6: ... with the reader that fits, by the driver, for this story", (finding["argv"][6:]), ["trx", "--by", "driver", "--task", TICKET])
        manifest = kept_manifest(root)
        check_eq("N2: the manifest holds the command, what was tried and the fit", (manifest["argv_digest"] == finding["argv_digest"], manifest["fit"],
                 sorted({t["reader"] for t in manifest["tried"]}), manifest["reason_class"]), (True, "trx", ["junit-xml", "trx"], "zero_tests"))
        check_eq("N2: the kept file is the report, byte for byte", [(f["name"], f["kept"]) for f in manifest["files"]], [(Path(manifest["files"][0]["name"]).name, True)])
        # the conductor's turn: here the helper's own CLI, in-process (the driver runs the same command)
        check_eq("N6: the driver's command succeeds and records the adaptation", report_adapt.main(["kind", "--profile", "web", "--reader", "trx", "--by", "driver", "--task", TICKET]), 0)
        row = report_adapt.load(root)[0][0]
        check_eq("N6: the row is `reporter_kind` by the driver", (row["kind"], row["by"], row["reader"]), ("reporter_kind", "driver", "trx"))
        gate_preflight._REPORTER_PROBES.clear()
        r = rehearse(root)
        check_eq("N3: after the adaptation the report is READ: no finding, no card", (r.findings, r.stand_gaps), ([], []))
        check_in("N3: the proven note says since when it reads", "read since the adaptation of 20", r.info[-1]["message"])
        # N8: only a row a LATER proof confirms is listed (the row is put a minute back: the proof and the row are one second apart in a test)
        path = report_adapt.record_path(root)
        record = json.loads(path.read_text(encoding="utf-8"))
        record["rows"][0]["at"] = "2000-01-01T00:00:00+00:00"
        path.write_text(json.dumps(record), encoding="utf-8")
        check_eq("N8: the row and a later proof of the same command: listed", [x["id"] for x in report_adapt.proven_adaptations(root, TICKET)], ["RA-1"])
    finally:
        cleanup(root)


def test_b416_the_conductor_decides_between_readers_and_never_the_code_g11_and_m3() -> None:
    root = project("qa-reporter-g11-", runner=WRITES_BOTH)
    try:
        use_project(root)
        no_kind(root)
        finding = rehearse(root).findings[0]
        # EP1-22 (I-1): the probe reads the report FILE only. The JUnit file the runner also left beside it is no proof and is no
        # longer tried, so the readers that fit are those of the report itself: the TRX, one reader - the neighbour does not make
        # two (it used to; the conductor's choice between two readers is held at `reporters.fits` and the helper's own tests).
        check_eq("G11 (EP1-22): only the report file is read: its one reader fits, and the neighbour JUnit does not make a second one",
                 (finding["fit"], sorted({t["file"] for t in kept_manifest(root)["tried"]})), ("trx", ["report.xml"]))
        check_in("G11 (EP1-22): and the message does not say a neighbour was tried", "only trx reads a test in it", finding["message"])
        check_not_in("G11 (EP1-22): nor that the JUnit beside it was one of the readers", "junit-xml and trx", finding["message"])
    finally:
        cleanup(root)
    root = project("qa-reporter-m3-", runner=WRITES_TRX)                    # the profile DECLARES junit-xml, the report is TRX: one reader fits, a kind is recorded
    try:
        use_project(root)
        finding = rehearse(root).findings[0]
        check_eq("M3: a declared kind that conflicts: `fit` names the reader, but there is NO typed command (a person's recorded kind is never overwritten)",
                 (finding["fit"], finding["declared_kind"], "argv" in finding), ("trx", "junit-xml", False))
    finally:
        cleanup(root)
    root = project("qa-reporter-g2-", runner=WRITES_JUNK)
    try:
        use_project(root)
        no_kind(root)
        finding = rehearse(root).findings[0]
        check_eq("G2: a binary report: nothing fits, no command, and the bytes are kept with their sha256", (finding["fit"], "argv" in finding,
                 [(f["kept"], len(f["sha256"])) for f in kept_manifest(root)["files"]]), ("", False, [(True, 64)]))
    finally:
        cleanup(root)


def test_b416_g1_g5_the_bound_is_one_conductor_turn_per_command_since_its_last_proof() -> None:
    import report_adapt
    import onboarding_probe
    root = project("qa-reporter-g5-", runner=WRITES_JUNK)
    try:
        use_project(root)
        argv = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))["profiles"][0]["commands"]["one_test"]["argv"]
        check_eq("G1: before the first unread report there is no folder and no record", (report_adapt.kept_dir(root, "web").exists(), report_adapt.record_path(root).exists()), (False, False))
        check_eq("G5: the first call is the conductor's", (len(rehearse(root).findings), len(rehearse(root).stand_gaps)), (1, 0))
        check("G1: the rehearsal created the folder, and the helper's record is still not there (the CLI or the driver creates it)",
              report_adapt.kept_dir(root, "web").is_dir() and not report_adapt.record_path(root).exists())
        row, _ = report_adapt.append(root, {"kind": "not_adapted", "by": "driver", "profile_id": "web", "argv_digest": onboarding_probe.argv_digest(argv),
                                            "story": TICKET, "understood": report_adapt.NOT_CALLED_TEXT})
        r = rehearse(root)
        check_eq("G5/G10: the conductor recorded nothing, the driver's `not_adapted` row: now the person's card, and no finding for the conductor", (len(r.stand_gaps), classes(r)), (1, ["person_decides"]))
        check_in("N7: the card row carries what the helper understood", "the helper was called and recorded nothing", r.stand_gaps[0]["understood"])
        r = rehearse(root)
        check_eq("G5: and still unread: still the card, never a second conductor turn", (len(r.stand_gaps), classes(r)), (1, ["person_decides"]))
        # forget: the conductor once more
        report_adapt.main(["forget", "--id", row["id"]])
        r = rehearse(root)
        check_eq("G5: `forget`: the conductor once more", (len(r.findings), r.stand_gaps), (1, []))
        # a new proof of the same argv, followed by a failure: the conductor once more
        report_adapt.append(root, {"kind": "not_adapted", "by": "conductor", "profile_id": "web", "argv_digest": onboarding_probe.argv_digest(argv), "story": TICKET, "understood": "x"})
        check_eq("(control) a row, and the card", len(rehearse(root).stand_gaps), 1)
        proofs = root / "qa-factory" / "state" / "reporter-rehearsals.json"
        proofs.parent.mkdir(parents=True, exist_ok=True)
        proofs.write_text(json.dumps({"schema_version": 1, "rehearsals": {"k": {"at": "2999-01-01T00:00:00+00:00", "profile_id": "web",
                                                                                  "argv_digest": onboarding_probe.argv_digest(argv)}}}), encoding="utf-8")
        r = rehearse(root)
        check_eq("G5: a proof of that argv NEWER than the row, then a failure: the conductor once more", (len(r.findings), r.stand_gaps), (1, []))
    finally:
        cleanup(root)


def test_b416_m5_an_unreadable_record_reads_as_a_row_exists_and_says_which_file() -> None:
    import report_adapt
    root = project("qa-reporter-m5-", runner=WRITES_JUNK)
    try:
        use_project(root)
        report_adapt.record_path(root).parent.mkdir(parents=True, exist_ok=True)
        report_adapt.record_path(root).write_text("{broken", encoding="utf-8")
        r = rehearse(root)
        check_eq("M5: an unreadable record of the helper is read as `a row exists`: the CARD, never a finding that would stop S4 for ever", (len(r.stand_gaps), classes(r)), (1, ["person_decides"]))
        check_in("M5: and one note names the file", "report-adaptations.json cannot be read", " ".join(i["message"] for i in r.info))
        report_adapt.record_path(root).unlink()
        (root / "qa-factory" / "state").mkdir(parents=True, exist_ok=True)
        (root / "qa-factory" / "state" / "reporter-rehearsals.json").write_text("{broken", encoding="utf-8")
        report_adapt.append(root, {"kind": "not_adapted", "by": "driver", "profile_id": "web", "argv_digest": "x"})
        gate_preflight._REPORTER_PROBES.clear()
        r = rehearse(root)
        check_eq("M5: an unreadable PROOF file reads the same way (no row of this command exists, so the file alone decides): the card",
                 (len(r.stand_gaps), classes(r)), (1, ["person_decides"]))
        check_in("M5: and one note names that file", "reporter-rehearsals.json", " ".join(i["message"] for i in r.info))
    finally:
        cleanup(root)


def test_b416_g15_a_covered_contour_still_gets_its_one_conductor_turn() -> None:
    root = project("qa-reporter-g15-", runner=ZERO_TESTS)
    counter, restore = counting_runs()
    try:
        use_project(root)
        record_for(root)
        gate_preflight._REPORTER_PROBES.clear()
        r = rehearse(root)
        check_eq("G15: a record covers the contour but there is no helper row: the conductor's finding FIRST - not covered, not a pass",
                 (len(r.findings), r.stand_gaps, r.covered_gaps, counter["runs"]), (1, [], [], 1))
        check_eq("G15: ... and it names the kept report (`zero_tests` is kept, too)", r.findings[0]["kept"], "qa-factory/state/reporter-unread/web/")
        helper_turn(root)
        gate_preflight._REPORTER_PROBES.clear()
        r = rehearse(root)
        check_eq("G15: after the helper's turn the record covers it (no card, one covered gap), the probe ran again", (r.stand_gaps, r.findings, len(r.covered_gaps)), ([], [], 1))
    finally:
        restore()
        cleanup(root)


def test_b416_g14_no_file_takes_the_same_road_with_the_tails_kept() -> None:
    root = project("qa-reporter-g14-", runner="import sys\nprint('toolchain says: restore failed for web.csproj', file=sys.stderr)\nsys.exit(3)\n")
    try:
        use_project(root)
        finding = rehearse(root).findings[0]
        manifest = kept_manifest(root)
        check_eq("G14: `no_file` goes to the conductor too, with `tried` empty and nothing to fit", (finding["class"], manifest["reason_class"], manifest["tried"], manifest["fit"], manifest["files"]),
                 ("factory_fixable", "no_file", [], "", []))
        check_in("G14: the tails of the run are kept for the helper to read the toolchain's fault", "restore failed for web.csproj", manifest["stderr_tail"])
        import report_adapt
        check("N2: the tails are at most TAIL_LIMIT characters", len(manifest["stderr_tail"]) <= report_adapt.TAIL_LIMIT and len(manifest["stdout_tail"]) <= report_adapt.TAIL_LIMIT)
    finally:
        cleanup(root)


def test_b416_g3_the_kept_files_and_bytes_at_and_beyond_their_limits() -> None:
    import reporters
    for count, label in ((reporters.KEEP_FILES, "AT KEEP_FILES"), (reporters.KEEP_FILES + 1, "BEYOND KEEP_FILES")):
        root = project("qa-reporter-g3-", runner=WRITES_MANY)
        try:
            use_project(root)
            edit_config(root, lambda c: c["profiles"][0]["commands"]["one_test"]["argv"].extend(["10", str(count)]))
            rehearse(root)
            files = kept_manifest(root)["files"]
            kept_on_disk = sorted(p.name for p in (root / "qa-factory" / "state" / "reporter-unread" / "web" / "files").iterdir())
            check_eq(f"G3: {label} ({count} files): {min(count, reporters.KEEP_FILES)} kept on disk, all {count} listed",
                     (len(files), sum(1 for f in files if f["kept"]), len(kept_on_disk)), (count, min(count, reporters.KEEP_FILES), min(count, reporters.KEEP_FILES)))
        finally:
            cleanup(root)
    for size, label in ((reporters.KEEP_LIMIT, "AT KEEP_LIMIT"), (reporters.KEEP_LIMIT + 1, "ONE BYTE BEYOND KEEP_LIMIT")):
        root = project("qa-reporter-g3b-", runner=WRITES_MANY)
        try:
            use_project(root)
            edit_config(root, lambda c: c["profiles"][0]["commands"]["one_test"]["argv"].extend([str(size), "1"]))
            rehearse(root)
            files = kept_manifest(root)["files"]
            check_eq(f"G3: {label}: the file is {'kept' if size == reporters.KEEP_LIMIT else 'listed with its size and NOT kept'}",
                     [(f["bytes"], f["kept"]) for f in files], [(size, size == reporters.KEEP_LIMIT)])
        finally:
            cleanup(root)


def kept_tails(stdout, stderr) -> tuple:
    """`(folder, stdout_tail, stderr_tail)`: what `Rehearsal._keep_unread` writes into the manifest for the run output given (the method
    is called directly, on a rehearsal of a project that has a story)."""
    root = project("qa-reporter-tail-")
    try:
        use_project(root)
        r = gate_preflight.Rehearsal(root / "qa-factory" / "artifacts" / TICKET, "A")
        slot = root / "slot"
        slot.mkdir()
        folder = r._keep_unread("s5_reporter", "web", ["run"], "junit-xml", "", slot, {"stdout": stdout, "stderr": stderr})
        manifest = kept_manifest(root)
        return folder, manifest["stdout_tail"], manifest["stderr_tail"]
    finally:
        cleanup(root)


def test_b426_d2_the_tails_are_cut_by_the_one_constant_at_and_beyond_it() -> None:
    import report_adapt
    from stand_gaps import names_only
    limit = report_adapt.TAIL_LIMIT
    digits = ("0123456789" * limit)
    at = digits[:limit]
    folder, out, err = kept_tails(at, at)
    check_eq("D2 AT: a tail of exactly TAIL_LIMIT characters is kept whole, both streams", (out, err), (at, at))
    check_eq("D2: and the kept folder is the one the person's project reads", folder, "qa-factory/state/reporter-unread/web/")
    plain = digits[:limit + 1]
    folder, out, err = kept_tails(plain, plain)
    check_eq("D2 BEYOND: one character more keeps the LAST TAIL_LIMIT - the END of the stream, both streams", (out, err), (plain[-limit:], plain[-limit:]))
    # `names_only` runs between the two cuts and lengthens `ABC=1` to `ABC=<value not printed>`: the first cut leaves TAIL_LIMIT characters
    # and the SECOND cut is the one that bites (a plain 401-character stream cannot show it).
    stream = "F" * (limit + 10) + " " + " ".join(["ABC=1"] * 20)
    first_cut = " ".join(stream.split())[-limit:]
    check("D2 fixture control: the first cut keeps TAIL_LIMIT characters and `names_only` makes them LONGER", len(first_cut) == limit and len(names_only(first_cut)) > limit)
    folder, out, err = kept_tails(stream, "")
    check_eq("D2 BEYOND (second cut): names_only lengthens the first cut and the tail is the last TAIL_LIMIT of it", out, names_only(stream)[-limit:])
    check("D2 BEYOND (second cut): it is exactly TAIL_LIMIT long, ends on the last pair and no value is printed", len(out) == limit and out.endswith("ABC=<value not printed>") and "ABC=1" not in out)
    for label, value in (("None", None), ("empty", ""), ("whitespace only", " \n\t ")):
        folder, out, err = kept_tails(value, value)
        check_eq(f"D2: {label} output -> both tails are the empty string", (out, err), ("", ""))


def understood_on_the_card(text, *, block_import: bool = False):
    """The gap row `_reporter_card` writes when the helper understood `text` of the unread report (the row itself; the card's
    method is called directly, as `test_a_pytest_profile_that_writes_nothing_is_told_what_actually_went_wrong` does).
    `block_import` makes `import report_adapt` fail inside it, the way a package without that module would."""
    root = project("qa-reporter-d10-")
    try:
        use_project(root)
        r = gate_preflight.Rehearsal(root / "qa-factory" / "artifacts" / TICKET, "A")
        held = sys.modules.get("report_adapt")
        if block_import:
            sys.modules["report_adapt"] = None          # `import report_adapt` now raises ImportError
        try:
            r._reporter_card("s5_reporter", "api", ["TC-001"], "pytest", "tests/test_a.py::test_x",
                             {"why": "no report file was written", "returncode": 4, "stderr": "", "stdout": ""},
                             ["poetry", "run", "pytest"], understood=text)
        finally:
            if block_import:
                sys.modules["report_adapt"] = held
        return r.stand_gaps[0]
    finally:
        cleanup(root)


def test_t683_d10_the_understood_text_is_cut_by_the_one_constant_at_and_beyond_it() -> None:
    import report_adapt
    from stand_gaps import names_only
    shown = report_adapt.UNDERSTOOD_SHOWN
    check_eq("D10: the constant is the 400 the card always showed (unchanged)", shown, 400)
    at = "ab" * (shown // 2)
    check_eq("D10 AT: exactly UNDERSTOOD_SHOWN characters are stored whole", understood_on_the_card(at).get("understood"), at)
    check_eq("D10 BEYOND: one character more stores the FIRST UNDERSTOOD_SHOWN", understood_on_the_card(at + "c").get("understood"), at)
    # `names_only` runs BEFORE the cut and lengthens `ABC=1` to `ABC=<value not printed>`: a cut made first would leave MORE than the limit
    pairs = " ".join(["ABC=1"] * 100)
    row = understood_on_the_card(pairs)
    check_eq("D10: names_only first, then the cut: the stored text is the first UNDERSTOOD_SHOWN of the names", row.get("understood"), names_only(pairs)[:shown])
    check("D10: ... exactly the limit long, and no value is printed", len(row["understood"]) == shown and "ABC=1" not in row["understood"])
    for label, value in (("empty", ""), ("whitespace only", " \n\t ")):
        check_eq(f"D10: {label} -> the row carries no `understood`", "understood" in understood_on_the_card(value), False)
    # FR-59 (F-5 (a)): the rule that says how much to show cannot be loaded -> nothing is stored, never a guess
    check_eq("D10: report_adapt cannot be imported -> the row carries no `understood` (an unknown is not printed)",
             "understood" in understood_on_the_card(at, block_import=True), False)
    # F-B2-1 (I-pure): the import guard covers the import and the constant only - a scrubber that raises propagates, as before D10
    import stand_gaps
    real = stand_gaps.names_only
    def scrubber_down(text):
        raise RuntimeError("scrubber down")
    stand_gaps.names_only = scrubber_down
    try:
        try:
            understood_on_the_card(at)
            reached = "swallowed"
        except RuntimeError as exc:
            reached = str(exc)
    finally:
        stand_gaps.names_only = real
    check_eq("D10: a names_only that raises propagates to the caller (the try guards the import, not the scrubber)", reached, "scrubber down")


def test_t683_d11_the_reporter_context_is_named_and_nothing_in_it_is_mutable() -> None:
    """t-683 D11 (E11): `_choose_test` and `_reporter_outcome` take ONE context; it holds the eight values known before a test is chosen,
    the argv as a tuple, and nothing can be assigned to it."""
    check_eq("D11: the fields, in order", gate_preflight.ReporterCtx._fields,
             ("check", "profile_id", "root", "cwd", "argv", "fmt", "declared_kind", "timeout", "identity"))  # EP1-22: + the last (`env` had no reader and is gone)
    ctx = gate_preflight.ReporterCtx("s5_reporter", "web", Path("."), Path("."), ("run", "<test>"), "junit-xml", "", 180)
    check_eq("D11: the argv is a tuple", isinstance(ctx.argv, tuple), True)
    try:
        ctx.fmt = "trx"
        refused = False
    except AttributeError:
        refused = True
    check_eq("D11: a field cannot be assigned", refused, True)


# --- B-426 D3 (t-625): characterisation of `Rehearsal._rehearse_reporter` before it is split ------------------------------------------
# One call, made the way `onboarding_probe._probe_one` makes it (positionally, with a temp folder of its own), and `_probe_reporter`
# replaced by a recorder: what the step LAUNCHES, which test it names and what it SAYS are read as data, whatever the helpers behind it are.

D3_PY = "PY"
D3_RUNNER = "RUNNER"


def d3_turn(root, commands, *, profile_id="web", declared=None, collect="", outcome=None, reporter=None, roots=None, timeout=30, rehearsal=None,
            clear=True):
    """`(rehearsal, [what `_probe_reporter` was asked to launch], str(temp))` of ONE `_rehearse_reporter` call on `profile_id`; the
    per-process cache is emptied first unless `clear` is False (a second call of one process)."""
    r = rehearsal or gate_preflight.Rehearsal(root / "qa-factory" / "artifacts" / TICKET, "A")
    r.collect_stdout = collect
    calls = []

    def recorder(launch, cwd, limit, report, fmt):
        calls.append({"launch": list(launch), "cwd": cwd, "timeout": limit, "report": report, "fmt": fmt, "slot_exists": Path(report).parent.is_dir()})
        return dict(outcome if outcome is not None else {"tests": 1})

    r._probe_reporter = recorder
    profile = {"profile_id": profile_id, "reporter": {"kind": "junit-xml"} if reporter is None else reporter, "commands": commands}
    if roots:
        profile["roots"] = roots
    temp = temp_dir("qa-reporter-d3-")
    if clear:
        gate_preflight._REPORTER_PROBES.clear()
    try:
        r._rehearse_reporter("s5_reporter", profile_id, {"cases": ["TC-001"]}, profile, root, temp, timeout, declared)
    finally:
        cleanup(temp)
    return r, calls, str(temp)


def d3_command(argv, cwd="."):
    return {"one_test": {"argv": argv, "cwd": cwd}}


def test_b426_d3_the_exits_before_a_run_and_the_chosen_test() -> None:
    root = project("qa-reporter-d3-a-")
    try:
        use_project(root)
        said = "`web`: no `commands.one_test.argv` in the profile, so no run could prove its report"
        for label, commands in (("no commands", {}), ("an empty argv", d3_command([])), ("blank tokens only", d3_command([" ", ""]))):
            r, calls, _ = d3_turn(root, commands)
            check_eq(f"D3 exit 1 ({label}): one note, no finding, no card, nothing launched, nothing cached",
                     ([i["message"] for i in r.info], r.findings, r.stand_gaps, calls, dict(gate_preflight._REPORTER_PROBES)), ([said], [], [], [], {}))
        command = d3_command([D3_PY, D3_RUNNER, "{report_path}", "<test-id>"])
        # the chain: the named test, then the first collected node (pytest-shaped only), then the first test file
        r, calls, temp = d3_turn(root, command, declared="tests/test_z_named.py", collect="tests/test_a_first.py::test_first\n")
        report = str(Path(temp) / "web" / "report.xml")
        check_eq("D3: the named test is run, in place of the placeholder; the report path replaces `{report_path}`",
                 [(c["launch"], c["fmt"], c["timeout"], str(c["report"]), c["slot_exists"]) for c in calls],
                 [([D3_PY, D3_RUNNER, report, "tests/test_z_named.py"], "junit-xml", 30, report, True)])
        check_eq("D3: and says where the choice came from",
                 [i["message"] for i in r.info],
                 ["`web` writes a junit-xml report S5 can read: 1 test(s) counted from tests/test_z_named.py (named by `gate_rehearsal.reporter_probe_test`)"])
        r, calls, _ = d3_turn(root, command, declared={"web": "tests/test_z_named.py"})
        check_eq("D3: a map names the test per profile", calls[0]["launch"][-1], "tests/test_z_named.py")
        r, calls, _ = d3_turn(root, command, declared={"api": "tests/test_z_named.py"}, collect="tests/test_z_named.py::test_named\n")
        check_eq("D3: a map that does not name this profile names nothing; a non-pytest command ignores the collect, the first test file is used",
                 (calls[0]["launch"][-1], [i["message"] for i in r.info]),
                 ("tests/test_a_first.py", ["`web` writes a junit-xml report S5 can read: 1 test(s) counted from tests/test_a_first.py (the first test file under .)"]))
        pytest_argv = [D3_PY, "-m", "pytest", "-q"]
        r, calls, temp = d3_turn(root, d3_command(pytest_argv), reporter={}, collect="collected 2 items\ntests/test_z_named.py::test_named\ntests/b.py::t\n")
        report = str(Path(temp) / "web" / "report.xml")
        check_eq("D3: a pytest command with no placeholder: the first collected node is appended, then `--junitxml=<report>`; the format is pytest",
                 [(c["launch"], c["fmt"]) for c in calls], [(pytest_argv + ["tests/test_z_named.py::test_named", f"--junitxml={report}"], "pytest")])
        check_eq("D3: and the note says the report is junit-xml and where the node came from",
                 [i["message"] for i in r.info],
                 ["`web` writes a junit-xml report S5 can read: 1 test(s) counted from tests/test_z_named.py::test_named "
                  "(the first test of the profile's own tests the gate's collect found)"])
        r, calls, _ = d3_turn(root, d3_command(pytest_argv), reporter={}, declared="tests/test_z_named.py", collect="tests/test_a_first.py::test_first\n")
        check_eq("D3: the named test wins over the collected node", calls[0]["launch"][4], "tests/test_z_named.py")
        r, calls, temp = d3_turn(root, d3_command(pytest_argv), reporter={}, collect="no node here\n")
        report = str(Path(temp) / "web" / "report.xml")
        check_eq("D3: a pytest command whose collect holds no node falls to the first test file",
                 (calls[0]["launch"], [i["message"] for i in r.info]),
                 (pytest_argv + ["tests/test_a_first.py", f"--junitxml={report}"],
                  ["`web` writes a junit-xml report S5 can read: 1 test(s) counted from tests/test_a_first.py (the first test file under .)"]))
        placed = [D3_PY, "-m", "pytest", "<test-file>", "--junitxml={report_path}"]
        r, calls, temp = d3_turn(root, d3_command(placed), reporter={}, collect="tests/test_z_named.py::test_named\n")
        report = str(Path(temp) / "web" / "report.xml")
        check_eq("D3: a placeholder is replaced and a `--junitxml` the command already has is not doubled",
                 calls[0]["launch"], [D3_PY, "-m", "pytest", "tests/test_z_named.py::test_named", f"--junitxml={report}"])
        r, calls, temp = d3_turn(root, d3_command([D3_PY, D3_RUNNER, "<{report_path}>", "<t>"]), declared="tests/test_z_named.py")
        report = str(Path(temp) / "web" / "report.xml")
        check_eq("D3: a token that holds `{report_path}` is a path even when it looks like a placeholder",
                 calls[0]["launch"], [D3_PY, D3_RUNNER, f"<{report}>", "tests/test_z_named.py"])
        r, calls, temp = d3_turn(root, d3_command([D3_PY, D3_RUNNER, "{report_path}"]), declared="tests/test_z_named.py")
        report = str(Path(temp) / "web" / "report.xml")
        check_eq("D3: a command with no placeholder, not pytest, runs as declared and says so",
                 (calls[0]["launch"], [i["message"] for i in r.info]),
                 ([D3_PY, D3_RUNNER, report],
                  ["`web` writes a junit-xml report S5 can read: 1 test(s) counted from the command as declared (the profile names no selector placeholder)"]))
        r, calls, temp = d3_turn(root, command, reporter={"kind": "trx"}, profile_id="w e/b")
        check_eq("D3: a trx report is `report.trx`, in a folder of the profile's own whose name is made safe, created before the launch",
                 [(Path(c["report"]).name, Path(c["report"]).parent.name, c["slot_exists"], c["fmt"]) for c in calls], [("report.trx", "w_e_b", True, "trx")])
        r, calls, _ = d3_turn(root, command, reporter={"kind": "mocha"})
        check_eq("D3: a declared kind the factory does not know, on a command that is not pytest, is format `none`", calls[0]["fmt"], "none")
        r, calls, _ = d3_turn(root, d3_command([D3_PY, D3_RUNNER, "<t>"], cwd="tests"))
        check_eq("D3: the test is searched for under the command's own directory and named relative to it",
                 (calls[0]["cwd"], calls[0]["launch"][-1], [i["message"] for i in r.info][0].endswith("(the first test file under tests)")),
                 ((root / "tests").resolve(), "test_a_first.py", True))
        r, calls, _ = d3_turn(root, d3_command([D3_PY, D3_RUNNER, "<t>"], cwd="no-such-dir"))
        check_eq("D3: a directory that is not there is the project root, and the search names the directory the profile gave",
                 (calls[0]["cwd"], calls[0]["launch"][-1], [i["message"] for i in r.info][0].endswith("(the first test file under no-such-dir)")),
                 (Path(root), "tests/test_a_first.py", True))
    finally:
        cleanup(root)
    root = project("qa-reporter-d3-roots-")
    try:
        use_project(root)
        (root / "tests" / "sub").mkdir()
        (root / "tests" / "sub" / "test_s.py").write_text("def test_s():\n    pass\n", encoding="utf-8")
        pytest_argv = [D3_PY, "-m", "pytest"]
        r, calls, _ = d3_turn(root, d3_command(pytest_argv), reporter={}, roots={"test": "tests/sub"},
                              collect="other.py::t\nsub/test_s.py::test_s\n")
        check_eq("D3: with `roots.test` the collected node is the first one BELOW it, not the project's first", calls[0]["launch"][3], "sub/test_s.py::test_s")
        r, calls, _ = d3_turn(root, d3_command(pytest_argv), reporter={}, roots={"test": "tests/sub"}, collect="other.py::t\n")
        check_eq("D3: and with no node below it the first test file under it", calls[0]["launch"][3], "tests/sub/test_s.py")
    finally:
        cleanup(root)
    root = project("qa-reporter-d3-notest-")
    try:
        use_project(root)
        for name in ("test_a_first.py", "test_z_named.py"):
            (root / "tests" / name).unlink()
        r, calls, _ = d3_turn(root, d3_command([D3_PY, D3_RUNNER, "<t>"], cwd="tests"))
        finding = r.findings[0] if r.findings else {}
        check_eq("D3 exit 2: no test to be found is ONE card for the person and nothing is launched, cached or noted",
                 (len(r.findings), len(r.info), r.stand_gaps, calls, dict(gate_preflight._REPORTER_PROBES)), (1, 0, [], [], {}))
        check_eq("D3 exit 2: its class, check, profile and cases", (finding.get("class"), finding.get("check"), finding.get("profile"), finding.get("cases")),
                 (gate_preflight.PERSON_DECIDES, "s5_reporter", "web", ["TC-001"]))
        check_eq("D3 exit 2: what it says", finding.get("message"),
                 "I could not list this project's tests (only pytest can be asked, this is not pytest), "
                 "and no file under `tests` has a usual test name, so nothing proves `web` writes a report the tests stage reads.")
        check_in("D3 exit 2: and the way out is the setting that names a test", "name one existing test in `gate_rehearsal.reporter_probe_test`", finding.get("fix", ""))
    finally:
        cleanup(root)


def test_b426_d3_what_the_run_came_to_and_what_the_step_keeps_of_it() -> None:
    root = project("qa-reporter-d3-b-")
    try:
        use_project(root)
        command = d3_command([D3_PY, D3_RUNNER, "{report_path}", "<test-id>"])
        r, calls, _ = d3_turn(root, command, outcome={"timed_out": True}, timeout=7)
        finding = r.findings[0] if r.findings else {}
        check_eq("D3 exit: timed out is one card for the person, and the timeout given is the one the run got",
                 (len(r.findings), len(r.info), r.stand_gaps, calls[0]["timeout"], finding.get("class"), finding.get("profile"), finding.get("cases")),
                 (1, 0, [], 7, gate_preflight.PERSON_DECIDES, "web", ["TC-001"]))
        check_eq("D3 exit: timed out says which test and how long", finding.get("message"),
                 "one test of `web` (tests/test_a_first.py) did not finish within 7s, so whether it writes a report S5 can read is unknown")
        check_in("D3 exit: and the way out is the setting", "raise `gate_rehearsal.reporter_timeout_s`", finding.get("fix", ""))
        r, calls, _ = d3_turn(root, command, outcome={"launcher_missing": True})
        check_eq("D3 exit: a missing launcher is one note that names it and the question already asked, and no card",
                 ([i["message"] for i in r.info], r.findings, r.stand_gaps),
                 ([f"`web`: `{D3_PY}` was looked up on PATH with PATHEXT and not found; install it, or correct argv[0] of the profile - "
                   "so its report is unproven; the launcher question already covers it"], [], []))
        r, calls, temp = d3_turn(root, command, outcome={"tests": 3})
        key = (str((root / ".").resolve()), tuple([D3_PY, D3_RUNNER, "{report_path}", "<test-id>"]), "tests/test_a_first.py", "junit-xml")
        check_eq("D3 exit: tests counted is one note and nothing else",
                 ([i["message"] for i in r.info], r.findings, r.stand_gaps),
                 (["`web` writes a junit-xml report S5 can read: 3 test(s) counted from tests/test_a_first.py (the first test file under .)"], [], []))
        check_eq("D3: the outcome is cached under the key (cwd, argv, test, format) and the argv is the one being rehearsed",
                 (list(gate_preflight._REPORTER_PROBES), gate_preflight._REPORTER_PROBES.get(key), r._rehearsing_argv),
                 ([key], {"tests": 3}, [D3_PY, D3_RUNNER, "{report_path}", "<test-id>"]))
        d3_turn(root, command, outcome={"tests": 9}, rehearsal=r, clear=False)
        check_eq("D3: a second call of the same process with the same key does not launch again and says the same",
                 (len(calls), [i["message"] for i in r.info]), (1, [r.info[0]["message"]] * 2))
        d3_turn(root, command, outcome={"tests": 2}, rehearsal=r, clear=False, reporter={"kind": "trx"})
        check_eq("D3: the same words with another report format are another key: they launch again",
                 sorted(k[3] for k in gate_preflight._REPORTER_PROBES), ["junit-xml", "trx"])
    finally:
        cleanup(root)
    root = project("qa-reporter-d3-card-")
    try:
        use_project(root)
        state = root / "qa-factory" / "state"
        state.mkdir(parents=True, exist_ok=True)
        (state / "reporter-rehearsals.json").write_text("{not json", encoding="utf-8")
        unread = {"why": "no report file was written", "reason_class": "no_file", "returncode": 0, "stdout": "", "stderr": "", "tried": []}
        r, calls, _ = d3_turn(root, d3_command([D3_PY, D3_RUNNER, "{report_path}", "<test-id>"]), outcome=unread)
        said = [i["message"] for i in r.info]
        check_eq("D3 exit: a helper record that cannot be read is read as a row: the note says so, then the card for the person (one gap, one finding)",
                 (len(said), said[0].startswith("`web`: ") and said[0].endswith(", so the helper is taken to have been called: the card is shown"),
                  len(r.stand_gaps), [f["class"] for f in r.findings]), (1, True, 1, [gate_preflight.PERSON_DECIDES]))
    finally:
        cleanup(root)


if __name__ == "__main__":
    test_b_deps_the_python_projects_key_is_the_one_built_before_the_table()
    test_b_deps_a_java_dotnet_or_js_file_changes_the_key()
    test_b_deps_the_projects_own_files_are_in_the_key_and_the_onboarding_without_a_config_is_one_rehearsal_more()
    test_b_deps_a_table_that_cannot_be_read_keeps_the_old_files_and_says_so()
    test_b_deps_a_path_on_another_drive_keeps_the_key_and_a_programming_error_in_the_builder_is_said()
    test_b_deps_a_row_written_before_a_manifest_appeared_is_rehearsed_once_more_and_replaced()
    test_b416_n3_an_unread_report_goes_to_the_conductor_first_and_the_person_only_after()
    test_b416_the_conductor_decides_between_readers_and_never_the_code_g11_and_m3()
    test_b416_g1_g5_the_bound_is_one_conductor_turn_per_command_since_its_last_proof()
    test_b416_m5_an_unreadable_record_reads_as_a_row_exists_and_says_which_file()
    test_b416_g15_a_covered_contour_still_gets_its_one_conductor_turn()
    test_b416_g14_no_file_takes_the_same_road_with_the_tails_kept()
    test_b416_g3_the_kept_files_and_bytes_at_and_beyond_their_limits()
    test_b426_d2_the_tails_are_cut_by_the_one_constant_at_and_beyond_it()
    test_t683_d10_the_understood_text_is_cut_by_the_one_constant_at_and_beyond_it()
    test_t683_d11_the_reporter_context_is_named_and_nothing_in_it_is_mutable()
    test_b426_d3_the_exits_before_a_run_and_the_chosen_test()
    test_b426_d3_what_the_run_came_to_and_what_the_step_keeps_of_it()
    test_b414_a_covered_level_is_not_carded_but_the_probe_still_runs()
    test_b414_the_record_never_hides_a_report_the_probe_reads()
    test_b414_a_fault_of_a_file_or_the_machine_is_never_keyed_and_never_covered()
    test_b414_an_unreadable_record_covers_nothing_and_a_rehearsal_with_no_story_never_asks_it()
    test_t411_the_probe_writes_and_the_whole_gate_reads_one_key_end_to_end()
    test_t411_a_row_the_part_one_package_wrote_is_read_as_none_rehearsed_once_then_replaced()
    test_a_person_command_at_the_gate_is_probed_and_never_reused_and_the_old_proof_stays()
    test_the_fix_line_limit_never_cuts_inside_a_command()
    test_the_onboardings_proof_is_the_proof_gate_a_reuses()
    test_the_same_command_that_stops_writing_a_report_is_said_to_have_stopped()
    test_a_changed_command_that_fails_is_said_to_have_changed_and_the_old_proof_stays()
    test_a_command_never_proven_is_not_said_to_have_stopped()
    test_a_record_that_cannot_be_read_is_never_a_pass_and_the_card_says_so()
    test_a_state_file_of_the_old_form_is_inert_and_the_next_proof_rewrites_it()
    test_one_row_per_command_a_newer_proof_of_the_same_words_replaces_the_older()
    test_a_word_to_go_on_without_the_report_does_not_hide_a_proof()
    test_the_fix_line_carries_the_recorded_command_and_passes_the_text_rules()
    test_a_recorded_command_the_text_rules_refuse_is_left_off_the_fix_line_not_forced_onto_it()
    test_the_first_call_rehearses_and_keeps_the_proof()
    test_a_new_process_does_not_rehearse_again_and_says_so()
    test_a_redeploy_is_not_a_new_rehearsal_the_proof_is_of_the_command()
    test_an_edited_dependency_file_is_a_new_rehearsal()
    test_another_stand_is_not_a_new_rehearsal()
    test_a_command_or_a_test_that_changed_is_a_new_rehearsal()
    test_a_project_with_no_runtime_probe_reuses_and_records_the_version_as_not_observed()
    test_a_probe_registered_for_every_profile_is_read()
    test_a_probe_that_cannot_answer_does_not_matter_to_a_proof_of_the_command()
    test_a_negative_outcome_is_not_kept_and_the_next_call_looks_again()
    test_a_record_that_does_not_parse_is_said_once_rehearsed_and_overwritten()
    test_a_handed_profile_and_a_switched_off_step_are_left_as_they_were()
    test_later_gate_calls_of_one_process_do_not_ask_the_stand_again()
    test_a_record_that_cannot_be_saved_is_said_and_the_rehearsal_stands()
    test_the_reuse_note_names_the_door_to_a_new_rehearsal()
    test_the_files_pytest_reads_its_report_options_from_are_part_of_the_key()
    test_a_profile_that_writes_a_report_is_stated_and_never_asked_about()
    test_a_run_that_leaves_no_report_is_a_card_with_the_cure_on_it()
    test_the_cure_is_the_one_the_runner_already_words()
    ko7_report_cure_reads_the_json_and_the_words_are_the_old_ones_but_for_vitest()
    ko7_a_changed_value_in_the_json_changes_the_sentence()
    ko7_a_words_table_that_cannot_be_read_never_stops_a_run()
    ko7_the_leaf_imports_neither_the_gate_nor_the_runner()
    test_a_pytest_profile_that_writes_nothing_is_told_what_actually_went_wrong()
    test_the_project_can_say_which_test_and_can_say_no()
    test_a_launcher_that_is_not_here_was_already_asked_about()
    test_a_word_already_given_closes_the_card()
    test_the_step_is_part_of_the_gate_and_writes_nothing_of_its_own()
    finish("the reporter proven before gate A")
