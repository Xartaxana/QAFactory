"""A person's words travel in a file, from the driver too (legacy-2406 W3-W2, M30).

The driver passed a person's words to a command as one argv element: not cut at a line break (a list argv has no
cmd.exe), but capped by the Windows command line (32767 characters), and it handed the conductor - a role with only
Bash, Read and Grep - an answer it could not put in a file. Every call now writes the words to
`<task root>/state/words/driver-<name>-<ms>.txt` first and passes `--words-file`; the conductor's prompt names that file.

What is proved, each in its own scenario:
  * the gate-decision path and each `ticket_adapter` words call (source review, gap acceptance) record the words
    byte-exact at 300 characters and at 40 000 (beyond the Windows command line), with `--words-file` and no inline
    words;
  * the one helper `Driver.words_file`: its names, its bytes (CRLF kept, no BOM), its folder, three calls in one
    millisecond, no name the secrets guard matches;
  * an empty or whitespace-only answer writes no file and is passed inline and empty, so the command's own refusal stands;
  * a failed write is the driver's own `Stop(EXIT_ERROR)`, never a fall back to inline words - also through the loop,
    where it leaves the question open;
  * the conductor's prompt names the file that holds the answer (one sentence), and not the tool list wider;
  * no other site of the driver set hands the words over inline (the count, with its negative control); upstream's own
    inline `--decision` waiver calls are a named, counted exemption (L5), and the one door text upstream wrote inline near
    `s0_list_too_late` is rendered by `person_words.door()` (L4).

Nothing here reaches the network or a real model. The stub and the helpers live in `story_run_common`.
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in  # noqa: E402
from story_run_common import (  # noqa: E402
    STUB,
    driver_for,
    run_scenarios,
    stub_calls,
)

PHRASE = '"do not publish"'

# The inline `"--decision"` waiver calls upstream's driver makes (list argv, no shell, one card line): the two stand-gap
# sites of `take_stand_gap_answers`. L5 leaves them as upstream wrote them; a third site is a new inline carrier and fails here
# until it is decided. (C1-7a, t-1162: the run-mode switch was a site - it now goes through `pass_block`, the words by file, and
# holds the person's question when the pass is not recorded; 5 -> 4. C1-6b, dedd10eb: the two stand-question executors, stand_confirm
# `go on` and stand_login `by hand`/`go on`, went through `take_seam_answer` -> `pass_block` -> `waiver.py --words-file`; 4 -> 2.)
UPSTREAM_INLINE_DECISION_SITES = 2


def put(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return path


def make_words(size: int, plain: bool = False) -> str:
    """An answer of exactly `size` characters: paragraphs, the quoted negative instruction, two
    non-ASCII characters (unless `plain`: the stub claude reads its stdin in the console's code
    page, so a prompt check needs ASCII), a first and a last character that are not whitespace."""
    head = ("Approve.\n\nScope: local only - " + PHRASE + " to Jira.\nKeep it local "
            + ("" if plain else chr(0xE9) + chr(0x4E2D)) + "\n")
    text = head
    while len(text) < size:
        text += "one more line of the answer, as long as the person wants\n"
    return text[:size - 1] + "z"


def put_gap_inventory(task_root: Path) -> None:
    """A work inventory with one required source the tracker refused: a gap to accept, no review yet.
    Put in AFTER gate A is recorded - an unreviewed inventory is itself a block of that gate."""
    source = {"source_id": "SRC-abc1", "canonical_ref": "https://jira/browse/APP-2", "relation": "referenced",
              "relevance": "unknown", "relevance_reason": "403 during assessment", "assessment_ref": None,
              "discovered_from": "SRC-task", "relation_evidence": "work/source.txt", "required": True,
              "status": "unavailable", "revision": None, "content_hash": None, "snapshot_ref": None,
              "fetched_at": "2026-09-19T00:00:00Z", "exclusion_or_error": "HTTP 403",
              "materials": {"comments": {"status": "unknown", "count": None},
                            "attachments": {"status": "unknown", "count": None, "items": []}}}
    put(task_root / "work" / "source-inventory.json", {"schema_version": 1, "sources": [source]})


def words_setup(task: str = "QA-9", gate: bool = False) -> tuple:
    """A temp project with the stub claude: (root, task_root, env). With `gate` the controller also
    stands at gate A (S0-S4 accepted, a plan): the slow part, built only where a decision is recorded."""
    root = harness.temp_project("qa-story-run-words-")
    harness.use_project(root)
    task_root = root / "qa-factory" / "artifacts" / task
    (task_root / "work").mkdir(parents=True)
    (task_root / "pipeline.json").write_text(json.dumps(
        {"ticket": task, "size": "S", "stages": {"S0": {"status": "done"}}, "gates": {}, "halts": []}),
        encoding="utf-8")
    if gate:
        import test_controller_rework_scope as SCOPED
        import test_controller_state as BASE
        from controller import Controller
        controller = Controller(task_root)
        controller.apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1",
                                        "known_paths": {"root": str(task_root), "project_root": str(root)},
                                        "idempotency_key": "init"})
        BASE.seed_plan(task_root, [SCOPED.plan_row(1, "automate")])
        for number in range(5):
            BASE.accept_stage(controller, task_root, f"S{number}")
    stub = root / "fake_claude.py"
    stub.write_text(STUB, encoding="utf-8")
    (root / "stub-control.json").write_text("{}", encoding="utf-8")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), STORY_RUN_CLAUDE=str(stub),
               STUB_CONTROL=str(root / "stub-control.json"), STUB_LOG=str(root / "stub-log.jsonl"))
    return root, task_root, env


def spying(driver) -> list:
    """Every factory script the driver runs, as (script, argv strings); the real script still runs."""
    calls, real = [], driver.py

    def spy(script, *args, **kwargs):
        calls.append((script, [str(a) for a in args]))
        return real(script, *args, **kwargs)
    driver.py = spy
    return calls


def words_files(task_root: Path) -> list:
    folder = task_root / "state" / "words"
    return sorted(folder.glob("*")) if folder.is_dir() else []


def count_sites(source: str, literal: str) -> int:
    """How many places in a driver source name `literal` (a quoted option, `"--words"`) as an argument."""
    return len(re.findall(re.escape(literal), source))


FILE_READER = re.compile(r'person_words\.read\(None,[^\n]*"--words"\)')


def inline_option_sites(source: str) -> int:
    """The places that spell `"--words"` as the inline option - every one except a `person_words.read(None, <file>, "--words")`
    file read, where the literal only names the option for a refusal and no words travel inline."""
    return count_sites(source, '"--words"') - len(FILE_READER.findall(source))


TASK = "QA-9"
GAP_TEXT = "exit gate for S1-qa-scout-1: source unavailable and not accepted by a person: SRC-abc1"


def recorded_gate_words(task_root: Path):
    from controller import Controller
    return ((Controller(task_root).state().get("decisions") or {}).get("gateA-" + TASK) or {}).get(
        "authorization_source")


def inventory_words(task_root: Path, key: str):
    found = json.loads((task_root / "work" / "source-inventory.json").read_text(encoding="utf-8"))
    return (found["sources"][0].get(key) or {}).get("words")


def words_gate_and_adapter_calls_are_byte_exact() -> None:
    """The gate-decision path and each ticket_adapter words call: byte-exact, at a small size (the control) and beyond
    the 32767-character command line. Upstream records stand answers FIRST, in `take_answer`
    (`take_stand_gap_answers`), before `record_by_code` is reached: this scenario drives `record_by_code` itself, the
    command that carries the whole answer."""
    small, big = make_words(300), make_words(40000)
    check_eq("the big answer is beyond the 32767-character Windows command line", len(big), 40000)
    for label, words in (("at a small size (the control)", small), ("beyond the command line limit", big)):
        root, task_root, env = words_setup(TASK, gate=True)
        try:
            driver = driver_for(root, env, TASK)
            calls = spying(driver)
            words = "approve\n" + words       # C1-4b: a gate is recorded by code only on its approval word, the rest travels whole
            check("the driver's folder for the words is absent until a call needs it", not words_files(task_root))
            check(f"gate A {label}: recorded by code", driver.record_by_code("gate_A", "S4", words) is True)
            got = recorded_gate_words(task_root)
            check(f"gate A {label}: authorization_source is byte-equal to the answer", got == words,
                  f"{len(got or '')} of {len(words)} characters")
            # DC1-19: the gate-decision call carries the answer TWICE, both by file - `--words-file` (the record, named by the gate) and
            # `--answers-file` (the lines the executor applies, named by the answers; the same bytes here: no earlier answer, no accepted gap)
            files = words_files(task_root)
            gate_files = [f for f in files if f.name.startswith("driver-gateA-")]
            answer_files = [f for f in files if f.name.startswith("driver-answersA-")]
            check_eq(f"gate A {label}: two files under state/words/ (the gate's words, the answers)", (len(files), len(gate_files), len(answer_files)), (2, 1, 1))
            if gate_files and answer_files:
                check_in(f"gate A {label}: named by the gate", "driver-gateA-", gate_files[0].name)
                check_eq(f"gate A {label}: a .txt file", (gate_files[0].suffix, answer_files[0].suffix), (".txt", ".txt"))
                check(f"gate A {label}: both files equal the answer, UTF-8, no BOM",
                      gate_files[0].read_bytes() == words.encode("utf-8") and answer_files[0].read_bytes() == words.encode("utf-8"))
            argv = next((a for s, a in calls if s == "controller.py"), [])
            check(f"gate A {label}: the command got --words-file and --answers-file, no inline words",
                  "--words-file" in argv and "--answers-file" in argv and "--words" not in argv and bool(gate_files) and bool(answer_files)
                  and Path(argv[argv.index("--words-file") + 1]).resolve() == gate_files[0].resolve()
                  and Path(argv[argv.index("--answers-file") + 1]).resolve() == answer_files[0].resolve(),
                  " ".join(argv)[-300:])

            put_gap_inventory(task_root)
            check(f"source review {label}: recorded by code", driver.record_review(words) is True)
            got = inventory_words(task_root, "human_review")
            check(f"source review {label}: the stored words are byte-equal", got == words.strip(),
                  f"{len(got or '')} of {len(words)} characters")
            check(f"source gap {label}: recorded by code", driver.record_gaps(GAP_TEXT, words) is True)
            got = inventory_words(task_root, "gap_acceptance")
            check(f"source gap {label}: the stored words are byte-equal", got == words.strip(),
                  f"{len(got or '')} of {len(words)} characters")
            adapter = [a for s, a in calls if s == "ticket_adapter.py" and ("review" in a or "accept-gap" in a)
                       and "--output" in a and ("--record" in a or "accept-gap" in a)]
            check_eq(f"{label}: the two ticket_adapter words calls were made", len(adapter), 2)
            check(f"{label}: and neither carried inline words",
                  all("--words-file" in a and "--words" not in a for a in adapter), str(adapter)[:300])
            files = words_files(task_root)
            check_eq(f"{label}: four calls (gate words, gate answers, review, gap), four files, none overwritten", len(files), 4)
            check(f"{label}: every file equals the answer",
                  all(f.read_bytes() == words.encode("utf-8") for f in files))
        finally:
            harness.cleanup(root)


def words_the_helper_names_bytes_and_folder() -> None:
    import guard_secrets
    import story_run
    root, task_root, env = words_setup(TASK)
    try:
        driver = driver_for(root, env, TASK)
        crlf = "line one\r\nline two\r\n\r\n" + PHRASE + "\n"
        path = driver.words_file(crlf, "gateB")
        check("a call creates state/words/ when it is absent",
              path is not None and path.parent.resolve() == (task_root / "state" / "words").resolve(), str(path))
        check_eq("CRLF and LF are written exactly as given, no BOM", path.read_bytes() if path else b"",
                 crlf.encode("utf-8"))
        # Two calls in one millisecond: the clock is held still, nothing waits on wall time.
        real_time = story_run.time.time
        story_run.time.time = lambda: 1700000000.5
        try:
            first, second, third = (driver.words_file(f"answer {n}", "s1gap") for n in range(3))
        finally:
            story_run.time.time = real_time
        names = [p.name for p in (first, second, third)]
        check_eq("three calls in the same millisecond get three different files", len(set(names)), 3)
        check("each keeps its own words", [p.read_text(encoding="utf-8") for p in (first, second, third)]
              == ["answer 0", "answer 1", "answer 2"])
        check("the name is driver-<word>-<millisecond stamp>", names[0] == "driver-s1gap-1700000000500.txt", names[0])
        check("no name matches the secrets guard", all(
            not re.search(pattern, "state/words/" + name) for name in names + [path.name]
            for pattern in guard_secrets.DEFAULT_SECRET_FILE_PATTERNS))
        check("a name for the gate, the review and the conductor does not either", all(
            not re.search(pattern, "state/words/" + driver.words_file("x", word).name)
            for word in ("gateA", "gateB", "s1review", "s1gap", "conductorS5")
            for pattern in guard_secrets.DEFAULT_SECRET_FILE_PATTERNS))
        check("the files are kept: nothing the driver ran deleted one", len(words_files(task_root)) >= 4)
    finally:
        harness.cleanup(root)


def words_an_empty_answer_writes_no_file() -> None:
    """No file, and the call is what an empty answer was before: the command's own refusal stands."""
    for label, empty in (("empty", ""), ("only whitespace", " \r\n\t ")):
        root, task_root, env = words_setup(TASK)
        try:
            driver = driver_for(root, env, TASK)
            calls = spying(driver)
            check(f"{label}: the helper writes no file", driver.words_file(empty, "gateA") is None)
            check(f"{label}: and creates no folder", not (task_root / "state" / "words").exists())
            check_eq(f"{label}: gate A is not recorded by code (the controller's own refusal stands)",
                     driver.record_by_code("gate_A", "S4", empty, approved_by="option"), False)     # C1-4b: the option road reaches the command
            argv = next((a for s, a in calls if s == "controller.py"), [])
            check(f"{label}: the command is called as before, with the answer inline", "--words" in argv
                  and "--words-file" not in argv, " ".join(argv))
            check_eq(f"{label}: nothing is recorded", recorded_gate_words(task_root), None)
            check_eq(f"{label}: no file was written by the call", words_files(task_root), [])
            put_gap_inventory(task_root)
            check_eq(f"{label}: a source review is not recorded either", driver.record_review(empty), False)
            check_eq(f"{label}: and no file was written for it", words_files(task_root), [])
        finally:
            harness.cleanup(root)


def words_a_write_failure_is_the_drivers_own_error() -> None:
    """Never a silent fall back to inline words: the words are NOT put on a command line instead, because a long or
    multi-line text would be cut there."""
    import story_run
    small = make_words(300)
    root, task_root, env = words_setup(TASK)
    try:
        put_gap_inventory(task_root)
        driver = driver_for(root, env, TASK)
        calls = spying(driver)

        def full_disk(*args, **kwargs):
            raise OSError(28, "No space left on device")
        story_run.open = full_disk
        try:
            for label, move in (("gate A", lambda: driver.record_by_code("gate_A", "S4", "approve\n" + small)),
                                ("the source review", lambda: driver.record_review(small)),
                                ("the source gap", lambda: driver.record_gaps(GAP_TEXT, small))):
                try:
                    move()
                    stopped = None
                except story_run.Stop as stop:
                    stopped = stop
                check(f"{label}: a write failure stops the driver with its own error",
                      stopped is not None and stopped.code == story_run.EXIT_ERROR, str(stopped))
                check(f"{label}: and says what to do",
                      stopped is not None and "Nothing was recorded" in stopped.reason
                      and "--answer" in stopped.reason, getattr(stopped, "reason", ""))
        finally:
            del story_run.open
        check_eq("no command was run with the words after a write failure (no inline fallback)",
                 [s for s, a in calls if s in ("controller.py", "ticket_adapter.py")], [])
        check_eq("and nothing is recorded", recorded_gate_words(task_root), None)
        check_eq("and no half-written file stays", words_files(task_root), [])
    finally:
        harness.cleanup(root)

    # The same, through the loop: a folder that cannot be made ends the run with exit 1 and leaves
    # the question open, so the same answer file can be given again.
    root, task_root, env = words_setup(TASK)
    try:
        answer = root / "answer.md"
        answer.write_text(small, encoding="utf-8")
        (task_root / "state").mkdir(exist_ok=True)
        (task_root / "state" / "words").write_text("a file where the folder should be", encoding="utf-8")
        (task_root / "state" / "driver-question.md").write_text(
            "# Driver question\nkind: gate_A\nstage: S4\n", encoding="utf-8")
        driver = driver_for(root, env, TASK, answer=str(answer))
        driver.where = lambda: {"action": "stop", "reason": "test stop"}
        driver.state["asked"] = {"kind": "gate_A", "stage": "S4", "dispatch": ""}
        driver.save_state()
        check_eq("the loop ends with the driver's own error", driver.run(), story_run.EXIT_ERROR)
        saved = json.loads((task_root / "state" / "driver-state.json").read_text(encoding="utf-8"))
        check_eq("the question is still open, so the answer can be given again", saved["asked"].get("kind"), "gate_A")
        check_eq("and the gate is not recorded", recorded_gate_words(task_root), None)
        check_eq("no conductor was asked in place of the file", stub_calls(root), [])
    finally:
        harness.cleanup(root)


def words_the_conductor_prompt_names_the_file() -> None:
    """The conductor has Bash, Read and Grep and cannot make a file of an answer it was handed: the prompt names the
    file the driver made, in one sentence the conductor can act on."""
    import story_run
    small = make_words(300)
    root, task_root, env = words_setup(TASK)
    try:
        driver = driver_for(root, env, TASK)
        for label, words in (("a small answer", make_words(300, plain=True)),
                             ("an answer beyond the command line", make_words(40000, plain=True))):
            before = len(stub_calls(root))
            verdict = driver.conductor("a refusal the table does not know", words=words)
            check_eq(f"conductor, {label}: it answered", verdict.get("action"), "continue")
            call = stub_calls(root)[before]
            prompt = call["prompt"]
            found = re.search(r"The person's words are in (.+?\.txt); pass them as --words-file (.+?\.txt)\.", prompt)
            check(f"conductor, {label}: the prompt carries the one sentence", bool(found), prompt[-400:])
            if found:
                check_eq(f"conductor, {label}: naming the same path twice", found.group(1), found.group(2))
                named = Path(found.group(1))
                check(f"conductor, {label}: the named file exists and equals the answer",
                      named.is_file() and named.read_bytes() == words.encode("utf-8"))
                check(f"conductor, {label}: it lies under state/words/",
                      named.parent.resolve() == (task_root / "state" / "words").resolve(), str(named))
            # `run_claude` writes the prompt through a text-mode pipe (upstream's `text=True`): on Windows a line
            # break reaches the child as CRLF, whatever the answer held. The words are compared as lines.
            # C1-1: the prompt carries the words up to NO_MOVE_WORDS_IN_PROMPT and, beyond it, a pointer to the file (the carrier
            # of the words is the file, FR-8); the file is asserted whole just above
            shown = words.strip()[:story_run.NO_MOVE_WORDS_IN_PROMPT]
            check(f"conductor, {label}: the words stay visible in the prompt (up to the limit)",
                  shown in prompt.replace("\r\n", "\n"))
            check(f"conductor, {label}: and a cut is said, with the file that holds the rest",
                  ("(cut; the whole answer is in" in prompt) == (len(words.strip()) > story_run.NO_MOVE_WORDS_IN_PROMPT))
            tools = call["argv"][call["argv"].index("--allowedTools") + 1]
            check_eq(f"conductor, {label}: the tool list is not widened", tools, "Bash,Read,Grep")
        before_files = len(words_files(task_root))
        before = len(stub_calls(root))
        driver.conductor("a refusal with no person's answer behind it")
        prompt = stub_calls(root)[before]["prompt"]
        check("no answer: no sentence about a words file", "--words-file" not in prompt
              and "The person's words are in" not in prompt and "## The person's words" not in prompt, prompt[-300:])
        check_eq("no answer: no file is written", len(words_files(task_root)), before_files)
        # The fourth call at one boundary is the driver's own refusal (three per boundary): no
        # conductor session, so no file is made for it either.
        before_files = len(words_files(task_root))
        try:
            driver.conductor("a fourth refusal", words=small)
            fourth = None
        except story_run.ConductorSpent as spent:      # C1-1: the cap is a ConductorSpent that only the seam turns into a question
            fourth = spent
        check("a conductor call the driver refuses writes no words file", fourth is not None
              and len(words_files(task_root)) == before_files)
    finally:
        harness.cleanup(root)


def words_no_other_site_hands_the_words_over_inline() -> None:
    """The problem, not the helper (FR-17): no other site hands the words over inline.

    `"--words"` is spelled in two kinds of place in the driver set. The CARRIER of inline words (`words_args`, the empty case)
    must stay ONE: that is the pin. The other kind is the flag NAME that `person_words.read(None, <file>, "--words")` takes -
    a file READER (`original_words`, C2-6 attempt 2, t-856; the same call story_step, environment_record and onboarding_notes
    make): inline is None there, so nothing is handed over inline and the name is never even printed (it shapes only the refusal
    of an inline value). It is a different road the carrier helper cannot cover, so it is counted apart, by its exact shape
    (`read(None, ..., "--words")`): any other spelling of the option - a list element, `read(<inline>, ...)` - is a carrier."""
    source = harness.driver_text()
    check_eq("the driver set names the inline words option in exactly one place, the helper's empty case",
             inline_option_sites(source), 1)
    check_eq("the driver set reads a words FILE with the option's name in exactly one place, `original_words`",
             len(FILE_READER.findall(source)), 1)
    check_eq("negative control: a second carrier is counted",
             inline_option_sites(source + '\nx = ["--words", w]\n'), 2)
    check_eq("negative control: a reader that is handed inline words is a carrier, not a file reader",
             inline_option_sites(source + '\nx = person_words.read(w, None, "--words")\n'), 2)
    check_eq("negative control: a further file reader is counted apart, not as a carrier",
             (inline_option_sites(source + '\nx = person_words.read(None, f, "--words")\n'),
              len(FILE_READER.findall(source + '\nx = person_words.read(None, f, "--words")\n'))), (1, 2))
    check_eq("the driver set names the inline decision option only in upstream's driver waiver calls (L5, a named exemption)",
             count_sites(source, '"--decision"'), UPSTREAM_INLINE_DECISION_SITES)
    check_eq("negative control: a third inline decision site is counted",
             count_sites(source + '\nx = ["--decision", w]\n', '"--decision"'), UPSTREAM_INLINE_DECISION_SITES + 1)
    # L4: the door text near `s0_list_too_late` is rendered by `person_words.door()`, not written inline
    check("the gate-A door of `s0_list_too_late` is rendered by person_words.door()",
          "person_words.door(" in source and '--gate A --words \\"' not in source)
    check("negative control: the inline spelling is found when it is there",
          '--gate A --words \\"' in source + 'details = "--gate A --words \\"<their words>\\""')


def _answer_file(root: Path, text: str) -> Path:
    return put(root / "answer.txt", text)


def words_arrival_not_waiting_tokens_have_an_executor() -> None:
    """t-2181 PC-7 B2 (FR-9, FR-7): each of the three tokens of `arrival.not_waiting` is written to `launch.arrival.answer` by
    `take_answer` (the word `arrival_record` reads), so the question never comes back with the same text; a token is read whole
    (case and spaces only, FR-12); any other answer goes to the seam once; a token with no pending word changes nothing."""
    from story_run_common import seed
    for token in ("re-ground", "ignore", "stop"):
        root, task_root, env = seed("QA-5")
        try:
            driver = driver_for(root, env, "QA-5")
            driver.state.setdefault("launch", {})["arrival"] = {"source": {"branch": "feat"}, "side": {}}
            driver.state["asked"] = {"kind": "arrival_not_waiting", "stage": "S0", "dispatch": ""}
            driver.take_answer(_answer_file(root, f"  {token.upper()}  \n"))
            check_eq(f"{token}: the token is the pending word's answer", driver.state["launch"]["arrival"].get("answer"), token)
            check_eq(f"{token}: the question is closed", driver.state.get("asked"), {})
        finally:
            harness.cleanup(root)
    root, task_root, env = seed("QA-5")
    try:
        driver = driver_for(root, env, "QA-5")
        seen = []
        driver.unread = lambda *a, **k: seen.append((a, k))
        driver.state.setdefault("launch", {})["arrival"] = {"source": {"branch": "feat"}, "side": {}}
        taken = driver._answer_arrival_not_waiting("re-ground it please", "q", "S0")
        check_eq("other words are not a token: they go to the seam, with the two doors", (taken, len(seen), seen[0][1]["doors"]),
                 (False, 1, ("re-ground", "ignore")))
        check_eq("... and write no answer", "answer" in driver.state["launch"]["arrival"], False)
        driver.state["launch"].pop("arrival")
        check_eq("a token with no pending word is taken and changes nothing", driver._answer_arrival_not_waiting("ignore", "q", "S0"), True)
        check_eq("... and writes no record", "arrival" in driver.state["launch"], False)
    finally:
        harness.cleanup(root)


def words_s1_not_built_yet_records_the_side_like_the_s0_twin() -> None:
    """t-2181 PC-7 B3 (FR-9, AR-19): the `not built yet` answer of the S1 halt records `pipeline.sides.product` absent, deliverable,
    `source: person` - the three fields the `s0.no_change` answer records through `s0_sides_sets` - and files the words for the
    scout. The WHOLE answer only: other words take the unread road (not this branch)."""
    from story_run_common import seed
    root, task_root, env = seed("QA-5")
    try:
        driver = driver_for(root, env, "QA-5")
        driver.s1_has_no_diff = lambda: True
        driver.state["asked"] = {"kind": "halt", "stage": "S1", "dispatch": "S1-qa-scout-1"}
        driver.state.setdefault("pending_words", {})
        driver.take_answer(_answer_file(root, "Not built yet\n"))
        product = ((json.loads((task_root / "pipeline.json").read_text(encoding="utf-8")).get("sides") or {}).get("product") or {})
        twin = driver_for(root, env, "QA-5")
        twin.state.setdefault("launch", {})["not_built_yet"] = True
        wanted = {key.rsplit(".", 1)[1]: value for key, value in twin.s0_sides_sets().items()
                  if key.startswith("sides.product.") and not key.endswith(".at")}
        check_eq("the s1 answer records the product side the way the s0 answer does",
                 {key: product.get(key) for key in ("reality", "deliverable", "source")}, wanted)
        check_eq("... absent, deliverable, from the person", (product.get("reality"), product.get("deliverable"), product.get("source")),
                 ("absent", True, "person"))
        check_eq("the words wait for the scout", driver.state["pending_words"].get("S1-qa-scout-1"), "Not built yet")
        import contract
        check_eq("the story now parks after S5", contract.parks_after_s5(json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))), True)
    finally:
        harness.cleanup(root)


def words_continue_command_drops_the_absent_pair_of_a_waited_side() -> None:
    """t-2181 PC-7 F7: the packet's restart line `... --branch <the branch>` never carries `--side <s>=absent` for a side the story
    waits for; the other pairs are repeated, and with no `drop_absent` the command is as before."""
    from story_run_common import seed
    root, task_root, env = seed("QA-5")
    try:
        driver = driver_for(root, env, "QA-5", side=[("product", "absent"), ("ui", "substituted")])
        full, cut = driver.continue_command(), driver.continue_command(drop_absent={"product"})
        check_in("by default every pair is repeated", "--side product=absent --side ui=substituted", full)
        check_eq("the waited side's absent pair is dropped, the other stays", ("product=absent" in cut, "--side ui=substituted" in cut), (False, True))
        other = driver_for(root, env, "QA-5", side=[("product", "real")]).continue_command(drop_absent={"product"})
        check_in("only an ABSENT pair is dropped: a real one stays", "--side product=real", other)
    finally:
        harness.cleanup(root)


def main() -> None:
    run_scenarios([], [
        words_arrival_not_waiting_tokens_have_an_executor,
        words_s1_not_built_yet_records_the_side_like_the_s0_twin,
        words_continue_command_drops_the_absent_pair_of_a_waited_side,
        words_gate_and_adapter_calls_are_byte_exact,
        words_the_helper_names_bytes_and_folder,
        words_an_empty_answer_writes_no_file,
        words_a_write_failure_is_the_drivers_own_error,
        words_the_conductor_prompt_names_the_file,
        words_no_other_site_hands_the_words_over_inline,
    ])
    harness.finish("test_story_run_words")


if __name__ == "__main__":
    main()
