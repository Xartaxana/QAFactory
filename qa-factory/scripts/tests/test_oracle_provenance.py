"""Where an expected value comes from (t-227, P20: code is never an oracle) - contract, resolver, raise, texts.

TP1-15045 (cmp2), TC_015: Then 2 said `403`, read off the diff (the very change under test) and
labelled "the pre-refactor contract"; Then 4 had no literal and no source; R-17 and R-19 were derived
from the diff alone and reached the plan as requirements. The validator side (K1 the case, K2 the
register) lives in test_validators.py, the question shape in test_gate_question_form.py; this file holds
the rest of t-227a: the pure functions of contract.py, the ONE read-time resolver (C6), the designer's
`--raise` (F8) and the role texts. Sections b (planning) and c (readers) are appended by their builders.

Fixtures are the cmp2 artifacts, verbatim (`fixtures/oracle-provenance/`): the whole TC_015, the
register header with rows R-1, R-13, R-16..R-19, R-27 and their matrix rows (`ids`/`by_source` cut to
the rows kept), the cmp2 Q1 verbatim, and Q7 - which cmp2 never had - constructed to K1's shape.

DOC-WITNESS KEYS (C11). Quoted VERBATIM from the "Role text" / "Rule" / "Error direction" lines of
docs/tasks/specs/t-227-oracle-provenance.md BEFORE this file was first run; the checker below reads them
from DOC_KEYS and a negative control proves it can fail:
  s1 Role text   "`then_oracles` with the one-line form"        -> then_oracles (designer, contract, slice)
  s0 F1          "`ac | spec | precedent | person | unknown`"   -> the closed list, as written there
  s1 Rule        "`code` is not a word"                         -> designer charter, contract
  s1 Rule        "ONE front-matter line of JSON"                -> "ONE line of JSON" in the contract
  s2 Role text   "(the section, before_ref forms, \"never the as-built value as the intended reading\")"
                 + "templates/requirements-register.md; the tester slice"
  s1 Error dir.  "whether R-13's text supports 403 is the case critic's" -> the case critic's slice
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (  # noqa: E402
    PLUGIN_ROOT, SCRIPTS, check, check_eq, check_in, cleanup, finish, run_script, temp_dir, temp_project, use_project,
)

sys.path.insert(0, str(SCRIPTS))

import contract as C  # noqa: E402
import question_register as QR  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "oracle-provenance"
REGISTER = (FIXTURES / "requirements-register.md").read_text(encoding="utf-8")
TC015 = (FIXTURES / "TP1-15045_TC_015.md").read_text(encoding="utf-8")
READINESS = (FIXTURES / "requirements-readiness.json").read_text(encoding="utf-8")

# --- the doc-witness keys, written down before the run (see the header) ------------------------------
DOC_KEYS = (
    ("agents/qa-case-designer.md", "then_oracles"),
    # spec t-1765 X1 (B-D, "moved"): the oracle vocabulary and "`code` is not a word" stand in the contract and the designer's slice
    ("references/slices/qa-case-designer/artifact-contract.md", "requirement | ac | spec | precedent | person | unknown"),
    ("references/artifact-contract.md", "then_oracles"),
    ("references/artifact-contract.md", "ONE line of JSON"),
    ("references/artifact-contract.md", "`code` is not a word"),
    ("references/slices/qa-case-designer/artifact-contract.md", "then_oracles"),
    ("references/slices/qa-case-designer/artifact-contract.md", "`code` is not a word"),
    ("agents/qa-requirements-tester.md", "## Behaviour claims"),
    ("agents/qa-requirements-tester.md", "never the as-built value as the intended reading"),
    ("references/templates/requirements-register.md", "## Behaviour claims"),
    ("references/templates/requirements-register.md", "before_ref"),
    ("references/templates/requirements-register.md", "never the as-built value as the intended reading"),
    ("references/slices/qa-requirements-tester/artifact-contract.md", "Behaviour claims"),
    ("references/slices/qa-requirements-tester/artifact-contract.md", "before_ref"),
    ("references/slices/qa-case-critic/artifact-contract.md", "text supports"),
    ("references/slices/qa-case-critic/artifact-contract.md", "case critic's"),
)


def read_normalised(rel: str) -> str:
    """A reference or charter with every run of whitespace collapsed: a key may be wrapped."""
    if "#" in rel:  # `<file>#<role>`: the role's ahead-card text, as the role receives it
        name, role = rel.split("#", 1)
        try:
            card = json.loads((PLUGIN_ROOT / name).read_text(encoding="utf-8"))["cards"][role]["text"]
        except (ValueError, KeyError, TypeError) as exc:
            raise OSError(f"{rel}: no readable card ({exc!r})")
        return " ".join(card.split())
    return " ".join((PLUGIN_ROOT / rel).read_text(encoding="utf-8").split())


def missing_keys(read) -> list:
    """[(file, key)] of the DOC_KEYS the texts do not carry. `read(rel)` returns the text of a file."""
    out = []
    for rel, key in DOC_KEYS:
        try:
            text = read(rel)
        except OSError:
            out.append((rel, key))
            continue
        if " ".join(key.split()) not in text:
            out.append((rel, key))
    return out


def test_doc_witness_keys() -> None:
    check_eq("DOC-WITNESS: every key is carried by the file the spec's Role text names", missing_keys(read_normalised), [])
    # the NEGATIVE control: a key deliberately absent is reported, and only that one
    rel, key = DOC_KEYS[2]

    def without_key(name: str) -> str:
        return read_normalised(name).replace(key, "") if name == rel else read_normalised(name)

    def without_file(name: str) -> str:
        if name == rel:
            raise OSError(name)
        return read_normalised(name)

    check_eq("NEGATIVE CONTROL: with one key cut out of its file the check reports exactly that key",
             missing_keys(without_key), [(rel, key)])
    check_eq("NEGATIVE CONTROL: a file that is not there reports every key it should carry",
             missing_keys(without_file), [m for m in DOC_KEYS if m[0] == rel])


def test_the_oracle_words_and_what_they_need() -> None:
    check_eq("the words (F1, D-0050/P23): requirement | ac | spec | precedent | person | unknown, and `code` is not one",
             C.THEN_ORACLE_WORDS, ("requirement", "ac", "spec", "precedent", "person", "unknown"))
    # I3 / FR-14 / FR-40: the older word `ac` stays legal for ever and is read as it was; the new `requirement` takes the same
    # ref (R-n); `code` stays a refusal (I5, FR-58): renaming the word opened no new source of an expectation.
    register_ids = {"R-13"}
    for word in ("requirement", "ac"):
        text = TC015.replace("plan_row: TS-15\n", f'then_oracles: [{{"then": 1, "source": "{word}", "ref": "R-13"}}]\nplan_row: TS-15\n', 1)
        errors = C.then_oracle_errors("TC_015.md", C.front_line(text, "then_oracles"), None, [1], known_r=register_ids)
        check_eq(f"I3: a Then with source `{word}` and ref R-13 is not refused for its word", [e for e in errors if "none of" in e], [])
        check_eq(f"I3: and the resolver returns the STORED word `{word}` (FR-14)",
                 C.resolve_then_oracle({"then": 1, "source": word, "ref": "R-13"})["source"], word)
    check_eq("I5: `code` is still no word", C.resolve_then_oracle({"then": 1, "source": "code", "ref": "R-13"})["state"], "invalid")
    check("`claim` is a reading origin beside `person`", "claim" in C.READING_ORIGINS and "person" in C.READING_ORIGINS)
    check_eq("the cutoff is by day", C.ORACLE_CUTOFF, "2026-10-02")
    check("a case updated on the cutoff day is under the rule", C.after_oracle_cutoff("2026-10-02"))
    check("and one updated the day before is legacy (every cmp2 artifact, 01.10)", not C.after_oracle_cutoff("2026-10-01"))
    check("a date it cannot read is not under the rule", not C.after_oracle_cutoff("") and not C.after_oracle_cutoff(None))
    check("a precedent ref is the base revision's line", bool(C.PRECEDENT_REF_RE.match("base:b9c0c4e:src/a/b.py:989")))
    check("and nothing else is", not C.PRECEDENT_REF_RE.match("R-13") and not C.PRECEDENT_REF_RE.match("diff:src/a.py:9"))


def test_the_register_is_read_by_code_never_declared() -> None:
    check_eq("F0.3: R-16..R-19 are implementation-only (derived, no ac_ref, diff:, an all-silent matrix row)",
             C.implementation_only(REGISTER), ["R-16", "R-17", "R-18", "R-19"])
    check("negative control: R-1 (ac) is not", "R-1" not in C.implementation_only(REGISTER))
    check("negative control: R-13 (ac, ok:) is not", "R-13" not in C.implementation_only(REGISTER))
    check("negative control: R-27 (matrix not silent) is not", "R-27" not in C.implementation_only(REGISTER))
    check_eq("no claims section yet: no claim row", C.behaviour_claims(REGISTER), [])
    claims = ("\n## Behaviour claims\n\n| R | before | before_ref | now | now_ref | differs | question |\n"
              "|---|---|---|---|---|---|---|\n| R-17 | 400 | base:b9c0c4e:workflow.py:989 | 403 | diff:+w.py:158 | yes | Q7 |\n")
    rows = C.behaviour_claims(REGISTER + claims)
    check_eq("a claim row is read by its header", [(r["r"], r["before"], r["now"], r["differs"], r["question"]) for r in rows],
             [("R-17", "400", "403", "yes", "Q7")])
    check_eq("the register's own columns are untouched by the section",
             [r["r"] for r in C.register_rows(REGISTER + claims)], ["R-1", "R-13", "R-16", "R-17", "R-18", "R-19", "R-27"])
    check_eq("a claim's question, by R", C.claim_questions(REGISTER + claims), {"R-17": "Q7"})
    check_eq("with no answered question every implementation-only R is unconfirmed (the safe direction)",
             C.unconfirmed_implementation_only(REGISTER + claims), {"R-16", "R-17", "R-18", "R-19"})
    # t-256 O1: this line said `{"status": "answered"}` confirms - any answer, `b` and own wording included,
    # made `ac:R-19` legal again. Only reading `a` confirms (the section "## t-256" below holds the rest).
    check_eq("a question answered `a` confirms ITS claim only",
             C.unconfirmed_implementation_only(REGISTER + claims, {"Q7": {"status": "answered", "reading": "a",
                                                                          "changed_since_answer": False}}),
             {"R-16", "R-18", "R-19"})
    check_eq("a `named` question confirms nothing (FR-41: named is not answered)",
             C.unconfirmed_implementation_only(REGISTER + claims, {"Q7": {"status": "named"}}), {"R-16", "R-17", "R-18", "R-19"})


def test_the_case_front_matter_lines() -> None:
    check_eq("the verbatim TC_015 carries no then_oracles (None: the key is absent, not empty)",
             C.then_oracles_from_text(TC015), (None, ""))
    text = TC015.replace("plan_row: TS-15\n", 'then_oracles: [{"then": 1, "source": "ac", "ref": "R-13"}]\nplan_row: TS-15\n', 1)
    check_eq("one line of JSON is read", C.then_oracles_from_text(text)[0], [{"then": 1, "source": "ac", "ref": "R-13"}])
    empty = TC015.replace("plan_row: TS-15\n", "then_oracles:\nplan_row: TS-15\n", 1)
    check_in("an empty value is a problem, not an absent key", "empty", C.then_oracles_from_text(empty)[1])
    check_eq("a body line that looks like the key is never read", C.front_line("---\nid: x\n---\nthen_oracles: [1]\n", "then_oracles"), None)


def test_the_resolver_reads_an_answered_question_as_the_person() -> None:
    """C6/FR-16: AT READ TIME an `unknown` Then whose question is `answered` counts as `person`, its expected
    value the matching `question_thens` reading; the approved case is never edited after gate A."""
    entry = {"then": 4, "source": "unknown", "ref": "Q7"}
    qthen = {"question": "Q7", "then": 4, "readings": {"a": "HTTP 400, the behaviour now", "b": ""}, "not_needed": ""}
    answered = {"id": "Q7", "status": "answered", "reading": "a", "changed_since_answer": False}
    got = C.resolve_then_oracle(entry, answered, qthen)
    check_eq("an answered question: the Then is `person`", (got["source"], got["state"]), ("person", "settled"))
    check_eq("its expected value is the reading's text", got["expected"], "HTTP 400, the behaviour now")
    check_eq("and the letter is kept", got["reading"], "a")
    check_eq("it points at the same question", got["ref"], "Q7")
    asserts_nothing = C.resolve_then_oracle(entry, dict(answered, reading="b"), qthen)
    check_eq("a reading whose text is empty asserts nothing here, and is still the person's word",
             (asserts_nothing["source"], asserts_nothing["expected"]), ("person", ""))
    for label, question in (("an open question", {"id": "Q7", "status": "open"}),
                            ("a `named` question (the id was mentioned, nothing was answered)", {"id": "Q7", "status": "named"}),
                            ("a `not_needed` question", {"id": "Q7", "status": "not_needed"}),
                            ("a question answered in the person's own wording (no letter)", dict(answered, reading="")),
                            ("a question that changed after it was answered", dict(answered, changed_since_answer=True)),
                            ("no question at all", None)):
        read = C.resolve_then_oracle(entry, question, qthen)
        check_eq(f"{label} stays unknown", (read["source"], read["state"], read["expected"]), ("unknown", "open", None))
        check(f"and says why: {label}", bool(read["why"]))
    no_text = C.resolve_then_oracle(entry, dict(answered, reading="c"), qthen)
    check_eq("a letter question_thens has no text for stays unknown", (no_text["source"], no_text["state"]), ("unknown", "open"))
    check_eq("with no question_thens entry at all it stays unknown too",
             C.resolve_then_oracle(entry, answered, None)["source"], "unknown")
    for source, ref in (("ac", "R-13"), ("precedent", "base:b9c0c4e:w.py:989"), ("person", "Q7")):
        same = C.resolve_then_oracle({"then": 1, "source": source, "ref": ref}, {"id": "Q7", "status": "open"}, None)
        check_eq(f"a `{source}` Then is not touched by the resolver", (same["source"], same["state"]), (source, "settled"))
    check_eq("an invented word is `invalid`, never settled", C.resolve_then_oracle({"then": 1, "source": "code", "ref": "x"})["state"], "invalid")

    # end to end, through the real register and the real answers file
    root = temp_dir("qa-oracle-resolver-")
    try:
        work = root / "work"
        work.mkdir()
        (work / "requirements-readiness.json").write_text(READINESS, encoding="utf-8")
        before = {q["id"]: q for q in QR.load(root)["questions"]}["Q7"]
        check_eq("the register says Q7 is open until a person answers", before["status"], "open")
        check_eq("and the resolver keeps the Then unknown", C.resolve_then_oracle(entry, before, qthen)["source"], "unknown")
        QR.record(root, "Q7", "answered", "Q7: a", "gate A", "driver", before["row_hash"], reading="a")
        after = {q["id"]: q for q in QR.load(root)["questions"]}["Q7"]
        read = C.resolve_then_oracle(entry, after, qthen)
        check_eq("the recorded answer turns the same Then into `person`", (read["source"], read["expected"]),
                 ("person", "HTTP 400, the behaviour now"))
        (work / "requirements-readiness.json").write_text(READINESS.replace('"severity": "major",\n      "owner_role": "po_ba",\n      "before"',
                                                                         '"severity": "critical",\n      "owner_role": "po_ba",\n      "before"'), encoding="utf-8")
        changed = {q["id"]: q for q in QR.load(root)["questions"]}["Q7"]
        check_eq("the question was edited after the answer: the answer was given to another text", changed["changed_since_answer"], True)
        check_eq("so the Then is unknown again (the direction of the error is toward unconfirmed)",
                 C.resolve_then_oracle(entry, changed, qthen)["source"], "unknown")
    finally:
        cleanup(root)


def _story(prefix: str, case_text: str, readiness: str = READINESS):
    project = temp_project(prefix)
    story = project / "qa-factory" / "artifacts" / "TP1-15045"
    (story / "work" / "test-cases" / "workflow-visual-diff").mkdir(parents=True)
    (story / "work" / "requirements-readiness.json").write_text(readiness, encoding="utf-8")
    case = story / "work" / "test-cases" / "workflow-visual-diff" / "TP1-15045_TC_015.md"
    case.write_text(case_text, encoding="utf-8")
    return project, story, case


QUESTION = {"question": "Which status code must PUT /v1/workflows/{id} return for a body that breaks two checks at once?",
            "source_says": [{"quote": "returns the same results and error codes for every invalid input as before",
                             "where": "register R-19 (derived from the diff alone)"}],
            "severity": "major", "owner_role": "po_ba",
            "before": {"value": "unknown", "where": "the base revision is not in the hunk"},
            "now": {"value": "400", "where": "observed by the S5 run"}}


def test_the_designer_raises_a_before_now_question() -> None:
    """F8: TC_015's P-multi was never an S2 question. The author raises it; the id and the two readings
    are the code's; a Then that already has an oracle other than `unknown` is never asked about."""
    with_oracles = TC015.replace("updated: 2026-10-01", "updated: 2026-10-02").replace(
        "plan_row: TS-15\n",
        'then_oracles: [{"then": 1, "source": "ac", "ref": "R-13"}, {"then": 2, "source": "ac", "ref": "R-13"}]\nplan_row: TS-15\n', 1)
    project, story, case = _story("qa-oracle-raise-", with_oracles)
    try:
        row = QR.raise_question(story, case, 4, QUESTION)
        check_eq("the new id is one past the largest numbered id of the register (Q1, Q7 -> Q8)", row["id"], "Q8")
        check_eq("its readings are the fixed pair, in order", row["readings"], C.claim_readings("unknown", "400"))
        check_eq("it passes the shape check as it stands", C.question_errors(row), [])
        check_eq("and shows before and now", (row["before"]["value"], row["now"]["value"]), ("unknown", "400"))
        written = json.loads((story / "work" / "requirements-readiness.json").read_text(encoding="utf-8"))["open_questions"]
        check_eq("the readiness file holds it, after the old ones", [q["id"] for q in written], ["Q1", "Q7", "Q8"])
        check_eq("the questions that were there are untouched", written[0], json.loads(READINESS)["open_questions"][0])
        check_eq("the register reads it as an open question", {q["id"]: q["status"] for q in QR.load(story)["questions"]}["Q8"], "open")
        again = QR.raise_question(story, case, 3, QUESTION)
        check_eq("a second raise takes the next id, never the same", again["id"], "Q9")
        for label, then, needle in (("a Then that already has an `ac` oracle", 2, "already has the oracle `ac:R-13`"),
                                    ("a Then number not under ## Then", 9, "is not an item under `## Then`")):
            try:
                QR.raise_question(story, case, then, QUESTION)
                check(f"refused: {label}", False, "no refusal")
            except QR.Refused as exc:
                check_in(f"refused: {label}", needle, str(exc))
        check_eq("and nothing was written by the refusals",
                 [q["id"] for q in json.loads((story / "work" / "requirements-readiness.json").read_text(encoding="utf-8"))["open_questions"]],
                 ["Q1", "Q7", "Q8", "Q9"])
        for label, spec, needle in (("no `now`", {k: v for k, v in QUESTION.items() if k != "now"}, "needs `now` as an object"),
                                    ("no source_says", dict(QUESTION, source_says=[]), "source_says names no quote"),
                                    ("no severity", dict(QUESTION, severity=""), "needs `severity`"),
                                    ("a `where` that is blank", dict(QUESTION, now={"value": "400", "where": " "}), "question.now needs value and where")):
            try:
                QR.raise_question(story, case, 3, spec)
                check(f"refused: a question with {label}", False, "no refusal")
            except QR.Refused as exc:
                check_in(f"refused: a question with {label}", needle, str(exc))
        broken = case.read_text(encoding="utf-8").replace("then_oracles: [", "then_oracles: [{", 1)
        case.write_text(broken, encoding="utf-8")
        try:
            QR.raise_question(story, case, 3, QUESTION)
            check("refused: a case whose then_oracles cannot be read", False, "no refusal")
        except QR.Refused as exc:
            check_in("refused: a case whose then_oracles cannot be read", "cannot be read", str(exc))
        (story / "work" / "requirements-readiness.json").unlink()
        case.write_text(with_oracles, encoding="utf-8")
        try:
            QR.raise_question(story, case, 3, QUESTION)
            check("refused: no readiness file to add to", False, "no refusal")
        except QR.Refused as exc:
            check_in("refused: no readiness file to add to", "does not exist", str(exc))
    finally:
        cleanup(project)


def test_the_raise_command() -> None:
    import os
    project, story, case = _story("qa-oracle-raise-cli-", TC015.replace("updated: 2026-10-01", "updated: 2026-10-02"))
    (project / "qa-factory" / "state").mkdir(exist_ok=True)
    question_file = temp_dir("qa-oracle-q-") / "q.json"
    question_file.write_text(json.dumps(QUESTION), encoding="utf-8")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project))
    try:
        done = run_script("question_register.py", "--task", "TP1-15045", "--raise", "--case-file", case,
                          "--then", "4", "--question-file", question_file, env=env)
        check_eq("--raise exits 0", done.returncode, 0)
        printed = json.loads(done.stdout)
        check_eq("and prints what it raised, as JSON only (FR-14)", (printed["raised"]["id"], printed["then"]), ("Q8", 4))
        refused = run_script("question_register.py", "--task", "TP1-15045", "--raise", "--case-file", case,
                             "--then", "x", "--question-file", question_file, env=env)
        check_eq("a Then that is not a number is refused (exit 2)", refused.returncode, 2)
        check_in("with the expected form named", "Expected the number of the item under `## Then`", refused.stderr)
        lacking = run_script("question_register.py", "--task", "TP1-15045", "--raise", "--case-file", case, env=env)
        check_eq("--raise with no --then and no --question-file is refused", lacking.returncode, 2)
        check_in("and names what it needs", "--then, --question-file", lacking.stderr)
        stray = run_script("question_register.py", "--task", "TP1-15045", "--raise", "--case-file", case, "--then", "4",
                           "--question-file", question_file, "--words", "x", env=env)
        check_in("an answer's flag has no meaning with --raise", "has no meaning with --raise", stray.stderr)
    finally:
        cleanup(project)
        cleanup(question_file.parent)


# ## t-227b -- the planning chain (appended by t-227b): a branch for every answer, applied after gate A ------
# DOC-WITNESS KEYS of this section, quoted VERBATIM from spec t-227 section 3 "Role text" ("every reading plus
# `not_needed`, `oracle_unknown: false` per letter, P19 words") and written down BEFORE the section first ran.
# The behaviour itself (missing_branch, apply_gate_answers, the S3 exit) is tested in test_question_branches.py
# and test_s3_s4_chain.py; here only what the strategist is TOLD.
T227B_KEYS = (
    ("references/ahead-cards.json#qa-test-strategist", "`oracle_unknown: false`"),  # moved charter -> card (t-1685 N3)
    # "manifesto ladder": the word the charter carries now (agents/qa-test-strategist.md line 25); it no longer says P19.
    ("agents/qa-test-strategist.md", "manifesto ladder"),
    ("references/artifact-contract-plan.md", "EVERY reading letter"),
    ("references/artifact-contract-plan.md", "`not_needed`"),
    ("references/slices/qa-test-strategist/artifact-contract-plan.md", "EVERY reading letter"),
    ("references/slices/qa-test-strategist/artifact-contract-plan.md", "`not_needed`"),
)


def t227b_missing(read) -> list:
    out = []
    for rel, key in T227B_KEYS:
        try:
            text = read(rel)
        except OSError:
            out.append((rel, key))
            continue
        if " ".join(key.split()) not in text:
            out.append((rel, key))
    return out


def test_t227b_doc_witness_keys() -> None:
    check_eq("t-227b DOC-WITNESS: the strategist's charter, the plan contract and its slice carry every key",
             t227b_missing(read_normalised), [])
    rel, key = T227B_KEYS[1]
    check_eq("t-227b NEGATIVE CONTROL: with one key cut out of its file the check reports exactly that key",
             t227b_missing(lambda name: read_normalised(name).replace(key, "") if name == rel else read_normalised(name)),
             [(rel, key)])


# ## t-256 -- the fix wave after the critic of t-245/t-246 (spec t-227 section 0d): O1, O2, O4 ------------------
# DOC-WITNESS KEYS of this section, quoted VERBATIM from the spec's 0d O4 sentence ("the designer (no Bash) writes
# a one-line `raise_questions` entry per Then and `then_oracles` uses the ref `raise`") and written down BEFORE
# the section first ran; the negative control cuts one out and the checker must name exactly it.
T256_KEYS = (
    ("agents/qa-case-designer.md", "a one-line `raise_questions` entry"),
    ("agents/qa-case-designer.md", "`raise`"),
    ("references/artifact-contract.md", "`raise_questions`"),
    ("references/artifact-contract.md", "`raise`"),
)


def t256_missing(read) -> list:
    out = []
    for rel, key in T256_KEYS:
        try:
            text = read(rel)
        except OSError:
            out.append((rel, key))
            continue
        if " ".join(key.split()) not in text:
            out.append((rel, key))
    return out


def test_t256_doc_witness_keys() -> None:
    check_eq("t-256 DOC-WITNESS: the designer's charter and the case contract carry the `raise_questions` form",
             t256_missing(read_normalised), [])
    rel, key = T256_KEYS[0]
    check_eq("t-256 NEGATIVE CONTROL: with one key cut out of its file the check reports exactly that key",
             t256_missing(lambda name: read_normalised(name).replace(key, "") if name == rel else read_normalised(name)),
             [(rel, key)])
    check_eq("t-256 NEGATIVE CONTROL: a file that is not there reports every key it should carry",
             t256_missing(lambda name: (_ for _ in ()).throw(OSError(name)) if name == rel else read_normalised(name)),
             [m for m in T256_KEYS if m[0] == rel])


def test_t256_o1_only_reading_a_confirms_a_behaviour_claim() -> None:
    """The P20 leak after an answer: ANY `answered` confirmed the claim, so Q7 answered `b` (a regression) or in the
    person's own words made `ac:R-19` legal again and the implementation's literal came back."""
    answered = {"id": "Q7", "status": "answered", "reading": "a", "changed_since_answer": False}
    check("O1: reading a, the row as the person saw it: confirmed", C.claim_confirmed(answered))
    # t-271 F5: this line said a record with NO stored hash (None) still confirms. A record that cannot say which
    # text the person was shown confirms nothing (the t-271 section below holds the control and the mutation).
    check("O1/F5: ...the stored hash absent (None) is UNCONFIRMED", not C.claim_confirmed(dict(answered, changed_since_answer=None)))
    for label, question in (("reading b (a regression)", dict(answered, reading="b")),
                            ("the person's own wording (no letter)", dict(answered, reading="")),
                            ("a letter beyond the pair", dict(answered, reading="c")),
                            ("a row edited since the answer", dict(answered, changed_since_answer=True)),
                            ("`not_needed`", {"id": "Q7", "status": "not_needed"}),
                            ("`named`", {"id": "Q7", "status": "named"}), ("open", {"id": "Q7", "status": "open"}),
                            ("no question", None), ("a status only (no reading key)", {"status": "answered"})):
        check(f"O1: {label}: NOT confirmed", not C.claim_confirmed(question))
    claims = ("\n## Behaviour claims\n\n| R | before | before_ref | now | now_ref | differs | question |\n|---|---|---|---|---|---|---|\n"
              "| R-17 | 400 | base:b9c0c4e:workflow.py:989 | 403 | diff:+w.py:158 | yes | Q7 |\n")
    check_eq("O1: through the register: answered b leaves all four implementation-only R unconfirmed",
             C.unconfirmed_implementation_only(REGISTER + claims, {"Q7": dict(answered, reading="b")}), {"R-16", "R-17", "R-18", "R-19"})
    check_eq("O1: ...answered a confirms R-17 alone", C.unconfirmed_implementation_only(REGISTER + claims, {"Q7": answered}),
             {"R-16", "R-18", "R-19"})


def test_t256_o2_a_regression_answer_on_an_unknown_before_is_not_settled() -> None:
    """`Q7: b` with `before: unknown` settled `person` on the designer's PLACEHOLDER (FR-41): the person chose "the
    behaviour before the change" and the question itself says nobody could read it."""
    entry = {"then": 4, "source": "unknown", "ref": "Q7"}
    qthen = {"question": "Q7", "then": 4, "readings": {"a": "HTTP 400, the behaviour now", "b": "whatever the designer guessed"}}

    def row(letter, before_value, **more):
        return dict({"id": "Q7", "status": "answered", "reading": letter, "changed_since_answer": False,
                     "before": {"value": before_value, "where": "the base revision"}, "now": {"value": "400", "where": "the diff"}}, **more)
    got = C.resolve_then_oracle(entry, row("b", "unknown"), qthen)
    check_eq("O2: b with before `unknown` stays OPEN (still the designer's `unknown`, not `person`)",
             (got["source"], got["state"], got["expected"]), ("unknown", "open", None))
    check_in("O2: ...and says what is needed", "the person's value for before is needed", got["why"])
    for blank in ("Unknown", " UNKNOWN ", "", "  "):
        check_eq(f"O2: a before of {blank!r} is the same placeholder", C.resolve_then_oracle(entry, row("b", blank), qthen)["state"], "open")
    got = C.resolve_then_oracle(entry, row("b", "400"), qthen)
    check_eq("O2: b with a KNOWN before is settled `person` on that value (not the designer's guessed text)",
             (got["source"], got["state"], got["expected"], got["reading"]), ("person", "settled", "400", "b"))
    got = C.resolve_then_oracle(entry, row("a", "unknown"), qthen)
    check_eq("O2: reading a does not depend on the before: settled on the question_thens text",
             (got["source"], got["expected"]), ("person", "HTTP 400, the behaviour now"))
    check_eq("O2: a question that shows no before/now (every question written before t-227) keeps the old reading of b",
             C.resolve_then_oracle(entry, {"id": "Q7", "status": "answered", "reading": "b", "changed_since_answer": False}, qthen)["expected"],
             "whatever the designer guessed")
    for label, question in (("own wording", row("", "400")), ("a row edited since", row("b", "400", changed_since_answer=True)),
                            ("open", row("b", "400", status="open"))):
        check_eq(f"O2 control: {label} stays unknown", C.resolve_then_oracle(entry, question, qthen)["source"], "unknown")


def test_t256_o4_the_s4_exit_raises_the_designers_question_and_re_pins() -> None:
    """The designer has no Bash. It writes `unknown` with the ref `raise` and ONE `raise_questions` line; the S4-exit
    step that applies approve_with_fixes (`critic_rollcall.py --apply-fixes`) raises the question, writes the new id
    into the case, drops the line and re-pins - with or without a findings file."""
    import case_versions as V
    import critic_rollcall as R
    project = temp_project("qa-oracle-t256-exit-")
    try:
        use_project(project)
        task = project / "qa-factory" / "artifacts" / "QA-1"
        (task / "work").mkdir(parents=True)
        (task / "work" / "requirements-readiness.json").write_text(READINESS, encoding="utf-8")
        source = task / "work" / "test-cases" / "area" / "TC-100.md"
        source.parent.mkdir(parents=True)
        oracles = [{"then": 1, "source": "ac", "ref": "R-13"}, {"then": 2, "source": "unknown", "ref": "raise"}]
        qthens = [{"question": "raise", "then": 2, "readings": {"a": "HTTP 400", "b": ""}, "not_needed": ""}]
        text = ("---\nid: TC-100\nstatus: Draft\ntask: QA-1\n" + f"then_oracles: {json.dumps(oracles)}\nquestion_thens: {json.dumps(qthens)}\n"
                + f"raise_questions: {json.dumps([dict(QUESTION, then=2)])}\n---\nRequirements: R-1\nPlan row: TS-1\n\n## Then\n1. a.\n2. b.\n")
        source.write_text(text, encoding="utf-8", newline="\n")
        store = task / "work" / "test-cases"
        record = V.create_version(store, source)
        V.pin(task, record)
        before = {l["case_id"]: l for l in C.story_case_links(task)}["TC-100"]["version"]
        done = R.raise_pending(task)
        check_eq("O4: one question raised for the case, by (case, Then)", done["raised"], [{"case": "TC-100", "then": 2, "question": "Q8"}])
        check_eq("...nothing skipped", done["skipped"], [])
        new = source.read_text(encoding="utf-8")
        check_eq("the authoring file now says Q8 and the line is gone", (C.then_oracles_from_text(new)[0][1]["ref"],
                                                                         C.front_line(new, "raise_questions")), ("Q8", None))
        link = {l["case_id"]: l for l in C.story_case_links(task)}["TC-100"]
        pinned = (task / link["path"]).read_text(encoding="utf-8")
        check("the case was RE-PINNED: a new version, and the pinned text carries the id", link["version"] != before and '"ref": "Q8"' in pinned)
        check_eq("the question is in the readiness file, keyed by (case, Then)",
                 [(q["id"], q.get("raised_for")) for q in json.loads((task / "work" / "requirements-readiness.json").read_text(encoding="utf-8"))["open_questions"]][-1],
                 ("Q8", {"case": "TC-100", "then": 2}))
        again = R.raise_pending(task)
        check_eq("O4: a second run raises nothing and writes nothing (idempotent)", (again["raised"], again["skipped"]), ([], []))
        check_eq("...the pin did not move again", {l["case_id"]: l for l in C.story_case_links(task)}["TC-100"]["version"], link["version"])
        # the lost-rewrite crash: the case still says `raise` but the question exists - same id, no second question
        source.write_text(text, encoding="utf-8", newline="\n")
        record = V.create_version(store, source)
        V.pin(task, record, expected_previous_version=link["version"])
        replay = R.raise_pending(task)
        check_eq("O4: a case that still says `raise` after the question was raised gets THE SAME id", replay["raised"],
                 [{"case": "TC-100", "then": 2, "question": "Q8"}])
        check_eq("...and the readiness file holds three questions, never four",
                 len(json.loads((task / "work" / "requirements-readiness.json").read_text(encoding="utf-8"))["open_questions"]), 3)
        # the CLI: with no findings file at all, and JSON only on stdout (FR-14)
        source.write_text(text.replace("TC-100", "TC-100"), encoding="utf-8", newline="\n")
        record = V.create_version(store, source)
        V.pin(task, record, expected_previous_version={l["case_id"]: l for l in C.story_case_links(task)}["TC-100"]["version"])
        import os
        proc = run_script("critic_rollcall.py", "--apply-fixes", "--task-root", task, env=dict(os.environ, CLAUDE_PROJECT_DIR=str(project)))
        payload = json.loads(proc.stdout)
        check_eq("O4: `--apply-fixes` raises with NO findings file: exit 0, `raised` in the JSON", (proc.returncode, payload.get("raised")),
                 (0, [{"case": "TC-100", "then": 2, "question": "Q8"}]))
        check_eq("...and `applied`/`skipped` are as ever", (payload["applied"], payload["skipped"]), ([], []))
        # a Then with no raise_questions entry: reported, kept as `raise`, exit 1
        source.write_text(text.replace(f"raise_questions: {json.dumps([dict(QUESTION, then=2)])}\n", ""), encoding="utf-8", newline="\n")
        record = V.create_version(store, source)
        V.pin(task, record, expected_previous_version={l["case_id"]: l for l in C.story_case_links(task)}["TC-100"]["version"])
        got = R.raise_pending(task)
        check_eq("O4: a `raise` with no entry is skipped with the reason, never raised", (got["raised"], len(got["skipped"])), ([], 1))
        check_in("...naming the case and the Then", "TC-100: Then 2 is `unknown` with the ref `raise` but the case has no `raise_questions` entry for it",
                 got["skipped"][0]["reason"])
        check('...and the case still says `raise` (the rehearsal will refuse it by name)', '"ref": "raise"' in source.read_text(encoding="utf-8"))
    finally:
        cleanup(project)


# ## t-227c -- the readers of the per-Then oracle and the S5-side texts (appended by t-227c) ------------------
# DOC-WITNESS KEYS of this section, from spec t-227 section 1 "Role text" and "Required behaviour" and written down BEFORE the
# section first ran (X7-8: the numbered steps of the old charters are gone, so the rows below name the rule by its text):
#   Role text   "the automator's charter: then_bindings `question`/`observed`; \"never a literal for an
#               unknown Then\"."                                  -> the automator's charter: `question`, `observed`,
#                                                                    "never a literal for an unknown Then"
#   Role text   "the code critic's charter: ONE pointer; the rule in code-review-rubric.md"
#                                                                  -> the charter names `invented_expectation` and the
#                                                                    rubric; the rubric holds the rule
#   Role text   "artifact-contract-automation.md (then_bindings)"  -> `question?`, `observed?`, `expectation_unconfirmed`
#   Role text   "vocabularies.md (oracle words, `expectation_unconfirmed`)" -> the five words, `claim`, the reason
#   Required    "`invented_expectation`, a findings entry with `cause: test_defect`"
#   behaviour                                                      -> the rubric
#   Rule (F1)   "`code` is not a word"                             -> vocabularies.md
# The slices are not keyed here: `contract_slices.py --check` is the witness that they follow their sources.
T227C_KEYS = (
    ("agents/qa-automator.md", "never a literal for an unknown Then"),
    ("agents/qa-automator.md", "expectation_unconfirmed"),
    ("agents/qa-automator.md", 'question="Q-n"'),
    ("agents/qa-automator.md", "observed="),
    ("agents/qa-code-critic.md", "invented_expectation"),
    ("agents/qa-code-critic.md", "code-review-rubric.md"),
    ("references/code-review-rubric.md", "invented_expectation"),
    ("references/code-review-rubric.md", "cause: test_defect"),
    ("references/code-review-rubric.md", "`open`/`invalid`"),
    ("references/artifact-contract-automation.md", "expectation_unconfirmed"),
    ("references/artifact-contract-automation.md", "question?, observed?"),
    ("references/vocabularies.md", "`expectation_unconfirmed`"),
    ("references/vocabularies.md", "`code` is not a word"),
    ("references/vocabularies.md", "- `ac` —"),
    ("references/vocabularies.md", "- `spec` —"),
    ("references/vocabularies.md", "- `precedent` —"),
    ("references/vocabularies.md", "- `person` —"),
    ("references/vocabularies.md", "- `unknown` —"),
    ("references/vocabularies.md", "- `claim` —"),
)


def t227c_missing(read) -> list:
    """[(file, key)] of T227C_KEYS the texts do not carry; `read(rel)` returns a file's text (OSError: not there)."""
    out = []
    for rel, key in T227C_KEYS:
        try:
            text = read(rel)
        except OSError:
            out.append((rel, key))
            continue
        if " ".join(key.split()) not in text:
            out.append((rel, key))
    return out


def test_t227c_doc_witness_keys() -> None:
    check_eq("t-227c DOC-WITNESS: the automator, the code critic, the rubric, the automation contract and the vocabularies carry every key",
             t227c_missing(read_normalised), [])
    rel, key = T227C_KEYS[7]
    check_eq("t-227c NEGATIVE CONTROL: with one key cut out of its file the check reports exactly that key",
             t227c_missing(lambda name: read_normalised(name).replace(key, "") if name == rel else read_normalised(name)),
             [(rel, key)])
    check_eq("t-227c NEGATIVE CONTROL: a file that is not there reports every key it should carry",
             t227c_missing(lambda name: (_ for _ in ()).throw(OSError(name)) if name == rel else read_normalised(name)),
             [m for m in T227C_KEYS if m[0] == rel])
    rubric = read_normalised("references/code-review-rubric.md")
    check("the rubric names the resolver's own words (settled | open | invalid), not a phrase list",
          all(word in rubric for word in ("`settled`", "`open`", "`invalid`")))
    check_eq("and the resolver speaks exactly those words",
             {C.resolve_then_oracle({"then": 1, "source": s, "ref": "Q1"})["state"] for s in ("ac", "unknown", "code")},
             {"settled", "open", "invalid"})
    check("the five oracle words of vocabularies.md are the contract's",
          all(f"`{w}`" in read_normalised("references/vocabularies.md") for w in C.THEN_ORACLE_WORDS))


# ## t-271 -- the fix wave after critic t-269 (F1 the date gate, F2 green on an open oracle, F3 the resolver state in the
# readers, F5 re-raise and the stored hash, F6 a decision in a code block, D2 `expectation_unconfirmed` as a contract word).
# No document is keyed here: every key of this section is code. The date gate (F1) is also proved on the validators in
# test_validators.py, and the manual-record reading (D5) in test_report_facts.py; each K-line below says where its twin is.

T271_PLAN = """---
task: TP1-15045
---
# Test plan - TP1-15045

## Plan

| TS | what we verify | R | defect hypothesis | impact class | priority | observable | oracle | disposition + reason | fit | level | technique |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TS-15 | PUT returns the same code per invalid input | R-19 | contract @ update | degraded | P2 | diff:src/workflow.py:532 | requirement:R-13 | `automate` - the cmp2 row | new | api | partitions |
"""
T271_ORACLES = ('then_oracles: [{"then": 1, "source": "ac", "ref": "R-13"}, {"then": 2, "source": "ac", "ref": "R-13"}, '
                '{"then": 3, "source": "ac", "ref": "R-13"}, {"then": 4, "source": "unknown", "ref": "Q7"}]\n'
                'question_thens: [{"question": "Q7", "then": 4, "readings": {"a": "HTTP 400, the behaviour now", "b": ""}, "not_needed": ""}]\n')


def _t271_story(*, bound_then_4: bool = True, oracles: str = T271_ORACLES, readiness: str = READINESS):
    """The cmp2 TC_015 shape, verbatim fixtures: Thens 1-3 sourced by AC-13, Then 4 `unknown` with Q7 (open, before
    `unknown`), every Then bound `covered` to ONE green instance (what the automator wrote when it asserted a value for
    Then 4). The case id is the default form, the plan row is TS-15, the requirement R-19."""
    project = temp_project("qa-t271-")
    task = project / "qa-factory" / "artifacts" / "TP1-15045"
    work = task / "work"
    (work / "test-cases" / "workflow-visual-diff").mkdir(parents=True)
    (task / "state").mkdir(parents=True)
    (work / "requirements-register.md").write_text(REGISTER, encoding="utf-8")
    (work / "requirements-readiness.json").write_text(readiness, encoding="utf-8")
    (task / "test-plan.md").write_text(T271_PLAN, encoding="utf-8")
    text = TC015.replace("updated: 2026-10-01", "updated: 2026-10-02").replace("TP1-15045_TC_015", "TC-015")
    text = text.replace("plan_row: TS-15\n", oracles + "plan_row: TS-15\n", 1)
    (work / "test-cases" / "workflow-visual-diff" / "TC-015.md").write_text(text, encoding="utf-8")
    bindings = [{"case": "TC-015", "then": n, "instance_id": "test_put[p]", "assertion_ref": "tests/t.py:9", "status": "covered"}
                for n in ((1, 2, 3, 4) if bound_then_4 else (1, 2, 3))]
    manifest = {"tests": [{"case": "TC-015", "covers": ["TC-015"], "file": "tests/t.py", "instance_id": "test_put[p]",
                           "shape": "new", "status": "green", "critic_verdict": "approved"}], "then_bindings": bindings, "unresolved": []}
    (work / "automation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (work / "run-report.json").write_text(json.dumps({"schema_version": 2, "execution_status": "passed", "results": [],
        "current_results": [{"instance_id": "test_put[p]", "case": "TC-015", "status": "passed"}]}), encoding="utf-8")
    return project, task, manifest


def _answer(task: Path, letter: str) -> None:
    view = {q["id"]: q for q in QR.load(task)["questions"]}["Q7"]
    QR.record(task, "Q7", "answered", f"Q7: {letter}", "gate A", "driver", view["row_hash"], reading=letter)


def test_t271_f1_an_unreadable_date_is_never_a_silent_off() -> None:
    states = {"2026-10-02": "dated", "2026-10-02T09:00:00Z": "dated", "2026-12-31": "dated", "2026-10-01": "legacy",
              "2025-01-01 10:00": "legacy", "": "missing", None: "missing", "   ": "missing", "yesterday": "unparseable",
              "2026-13-45": "unparseable", "02.10.2026": "unparseable", "20261002": "unparseable", "2026-10-2": "unparseable"}
    check_eq("F1: each `created`/`updated` value reads as dated | legacy | missing | unparseable",
             {k: C.oracle_date_state(k) for k in states}, states)
    check("F1: after_oracle_cutoff alone still reads an unparseable date as 'rule off' - which is why the problem line exists",
          not C.after_oracle_cutoff("yesterday") and not C.after_oracle_cutoff(""))
    for value in ("", "yesterday", "2026-13-45", "02.10.2026"):
        problem = C.oracle_date_problem(value, "created")
        check_in(f"F1: {value!r}: the refusal names the field", "`created` is", problem)
        check_in(f"F1: {value!r}: and the form expected", "ISO date, YYYY-MM-DD", problem)
    for value in ("2026-10-01", "2026-10-02", "2026-10-02T09:00:00Z"):
        check_eq(f"F1 control: {value!r} reads - no problem line", C.oracle_date_problem(value, "created"), "")
    check_eq("F1: a legacy date is one note line (`--verbose`), a dated or unreadable one is none",
             [C.oracle_date_note(v, "updated") for v in ("2026-10-01", "2026-10-02", "yesterday")],
             ["`updated` 2026-10-01 is before 2026-10-02: the oracle checks (then_oracles, behaviour claims) are off for this file", "", ""])
    # the coverage projection never refuses (P1): an unreadable register date turns the rule ON and says why
    import coverage_contract as CC
    project, task, _ = _t271_story()
    try:
        (task / "work" / "requirements-register.md").write_text(REGISTER.replace("created: 2026-10-01", "created: yesterday"), encoding="utf-8")
        (task / "work" / "test-plan.json").write_text(json.dumps({"rows": []}), encoding="utf-8")
        doc = CC.coverage_projection(task, {"current_results": []}, {})
        check_in("F1: the coverage projection names the unreadable `created` instead of switching the rule off", "`created` is 'yesterday'",
                 doc.get("oracle_date_problem", ""))
        (task / "work" / "requirements-register.md").write_text(REGISTER, encoding="utf-8")
        check_eq("F1 control: a legacy register (created 2026-10-01) adds no key to the projection",
                 "oracle_date_problem" in CC.coverage_projection(task, {"current_results": []}, {}), False)
    finally:
        cleanup(project)
    print("K-F1 | `created`/`updated` '' | 'yesterday' | '2026-13-45' | '02.10.2026' -> refused naming the field and YYYY-MM-DD "
          "(register, case, plan, S2 exit: test_validators.py); '2026-10-01' -> legacy, one `--verbose` note, checks off")


def test_t271_f2_a_green_run_on_an_open_oracle_is_not_a_pass() -> None:
    """cmp2 TC_015: Thens 1-3 sourced, Then 4 `{unknown, Q7}`, Q7 open, every Then bound covered to ONE green instance.
    Before: traceability `pass`, ledger `passed_green`, `person_debts` empty."""
    import coverage_contract as CC
    import ledger as L
    import traceability as T
    project, task, manifest = _t271_story()
    try:
        rows = T.build(project / "qa-factory", task)["rows"]
        then4 = [r for r in rows if r["case"] == "TC-015" and r["then"] == [4]]
        check_eq("F2: Then 4 reads `wait`, on its own row", [r["result"] for r in then4], ["wait"])
        check_eq("F2: ... with the reason in the task's own terms (the question and what the green proves)", then4[0]["basis"],
                 "expected value unconfirmed (Q7 open) — the green run proves only that the implementation does what it does")
        check_eq("F2: Thens 1-3 (settled by AC-13) keep `pass`", [r["result"] for r in rows if r["case"] == "TC-015" and r["then"] == [1, 2, 3]], ["pass"])
        # the ledger
        case_index = C.case_index(task)
        gaps = L.open_oracles(task, case_index)
        check_eq("F2: the ledger reads the SAME resolver: Then 4 open", {c: {t: g["state"] for t, g in v.items()} for c, v in gaps.items()},
                 {"TC-015": {4: "open"}})
        row = {"ts": "TS-15", "disposition": "automate"}
        report = {"current_results": [{"instance_id": "test_put[p]", "case": "TC-015", "status": "passed"}]}
        state, detail = L.plan_row_state(row, manifest, report, {}, {"TS-15": ["TC-015"]}, gaps)
        check_eq("F2: the plan row reads `not_verified:expectation_unconfirmed`, never `passed_green`", state, L.NOT_VERIFIED_UNCONFIRMED)
        check_in("F2: ... naming the Then and what the green proves", "TC-015 Then 4: expected value unconfirmed (Q7 open) — the green run proves only", detail)
        check_in("F2: ... and what is wanted of the person", "Needed: your answer to Q7", detail)
        check_eq("F2 CONTROL (the caller that has not read the cases, the old call): the same row IS `passed_green`",
                 L.plan_row_state(row, manifest, report, {}, {"TS-15": ["TC-015"]})[0], "passed_green")
        doc = L.build(task)
        check_eq("F2: through L.build the row reads the new state and person_debts lists it (nothing blocks on it)",
                 ([r["state"] for r in doc["rows"] if r["ref"] == "TS-15"], [d["ref"] for d in L.person_debts(doc)]),
                 ([L.NOT_VERIFIED_UNCONFIRMED], ["TS-15"]))
        # a settled Then keeps pass; a legacy case is untouched
        _answer(task, "a")
        check_eq("F2: Q7 answered `a`: Then 4 is `person` and the row is a pass again (a settled Then keeps `pass`)",
                 ([r["result"] for r in T.build(project / "qa-factory", task)["rows"] if r["case"] == "TC-015" and 4 in r["then"]],
                  L.plan_row_state(row, manifest, report, {}, {"TS-15": ["TC-015"]}, L.open_oracles(task, C.case_index(task)))[0]),
                 (["pass"], "passed_green"))
    finally:
        cleanup(project)
    # error direction: Q7 answered `b` while its `before` is `unknown` settles nothing -> still wait
    project, task, manifest = _t271_story()
    try:
        _answer(task, "b")
        check_eq("F2: Q7 answered `b` with before `unknown` (the designer's placeholder): Then 4 stays `wait`",
                 [r["result"] for r in T.build(project / "qa-factory", task)["rows"] if r["case"] == "TC-015" and r["then"] == [4]], ["wait"])
    finally:
        cleanup(project)
    # an invented oracle word is `invalid`, and a green run on it is no pass either
    project, task, manifest = _t271_story(oracles=T271_ORACLES.replace('"source": "unknown", "ref": "Q7"', '"source": "code", "ref": "x"'))
    try:
        then4 = [r for r in T.build(project / "qa-factory", task)["rows"] if r["case"] == "TC-015" and r["then"] == [4]]
        check_eq("F2: an `invalid` oracle (source `code`) read as covered: `wait`, said in words",
                 (then4[0]["result"], "'code' is not an oracle word" in then4[0]["basis"]), ("wait", True))
    finally:
        cleanup(project)
    # LEGACY: no then_oracles line at all -> nothing is read, today's `pass`
    project, task, manifest = _t271_story(oracles="")
    try:
        check_eq("F2 LEGACY: a case with no `then_oracles` reads exactly as before (pass, passed_green)",
                 ([r["result"] for r in T.build(project / "qa-factory", task)["rows"] if r["case"] == "TC-015"],
                  L.plan_row_state({"ts": "TS-15", "disposition": "automate"}, manifest,
                                   {"current_results": [{"instance_id": "test_put[p]", "case": "TC-015", "status": "passed"}]}, {},
                                   {"TS-15": ["TC-015"]}, L.open_oracles(task, C.case_index(task)))[0]),
                 (["pass"], "passed_green"))
    finally:
        cleanup(project)
    # coverage_contract: the obligation comes from the MAPPING, not from the case text printing its id
    project, task, _ = _t271_story()
    try:
        ob = {"obligation_id": "OB-15", "behavior": "b", "observation_boundary": "api", "completion_condition": "done",
              "requirement_refs": [{"ref": "R-19", "revision": "r"}], "applicable_scenarios": ["p"], "oracle_status": "resolved",
              "oracle_source_ref": "spec", "decision": "new", "execution_scope": "current_task",
              "sufficiency_review": {"author_dispatch_id": "d", "input_hash": "h", "rationale": "r"}, "coverage_links": [],
              "planned_check_refs": ["x"]}
        (task / "work" / "test-plan.json").write_text(json.dumps({"rows": [{"id": "TS-15", "schema_version": 2, "coverage_obligations": [ob]}]}), encoding="utf-8")
        case = task / "work" / "test-cases" / "workflow-visual-diff" / "TC-015.md"
        check("F2 CONTROL: the verbatim TC_015 prints the id OB-15 (it is removed from the text below)",
              "OB-15" in case.read_text(encoding="utf-8"))
        case.write_text(case.read_text(encoding="utf-8").replace("OB-15", "the obligation"), encoding="utf-8")
        item = CC.coverage_projection(task, {"current_results": []}, {"obligation_bindings": []})["obligations"][0]
        check_eq("F2: a case that never prints OB-15 still answers for it through the mapping: unresolved and the person's debt",
                 (item.get("oracle_status"), item["person_debt"], item["verified"]), ("unresolved", True, False))
        print("K-F2 | TC_015 Then 4 {unknown, Q7} open, binding covered, instance green: traceability wait ('expected value unconfirmed "
              "(Q7 open) - the green run proves only that the implementation does what it does'), ledger " + L.NOT_VERIFIED_UNCONFIRMED
              + ", person_debts [TS-15], Q7:a -> pass/passed_green, Q7:b+before unknown -> wait")
    finally:
        cleanup(project)


def test_t271_f3_the_readers_use_the_resolver_state() -> None:
    import gate_brief as GB
    import report_facts as RF
    project, task, manifest = _t271_story(bound_then_4=False)
    try:
        manifest["then_bindings"].append({"case": "TC-015", "then": 4, "instance_id": None, "assertion_ref": None, "status": "unresolved",
                                          "reason": C.EXPECTATION_UNCONFIRMED, "question": "Q7", "observed": "400"})
        (task / "work" / "automation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        index = C.case_index(task)

        def line_state() -> tuple:
            found = RF._unconfirmed_thens(task, manifest, index, RF._key_fn(index))
            return found[0]["answered"], found[0]["line"]
        readiness_rows = json.loads(READINESS)["open_questions"]

        def still_open() -> list:
            return [q["id"] for q in GB.still_open(readiness_rows, QR.load(task), {}, task)]
        check_eq("F3: Q7 open: the Left-with-you line is owed and gate B lists the question",
                 (line_state(), "Q7" in still_open()), ((False, "To check: P-multi: one stable code, equal to the expected value; a different code than "
                                                         "before the refactor is a finding because the check order changed. Needed: your answer to Q7"), True))
        _answer(task, "b")
        check_eq("F3: Q7 answered `b` while its `before` is `unknown`: the line STAYS (answered is not settled) ...",
                 (line_state()[0], bool(line_state()[1])), (False, True))
        check_in("F3: ... and gate B still shows the question, with a note that says what is missing", "Q7", still_open())
        noted = [q for q in GB.still_open(readiness_rows, QR.load(task), {}, task) if q["id"] == "Q7"][0]
        check_in("F3: ... the note is plain words", "nobody knows what it was", noted["status_note"])
    finally:
        cleanup(project)
    project, task, manifest = _t271_story(bound_then_4=False)
    try:
        manifest["then_bindings"].append({"case": "TC-015", "then": 4, "instance_id": None, "assertion_ref": None, "status": "unresolved",
                                          "reason": C.EXPECTATION_UNCONFIRMED, "question": "Q7"})
        index = C.case_index(task)
        _answer(task, "a")
        found = RF._unconfirmed_thens(task, manifest, index, RF._key_fn(index))
        check_eq("F3 CONTROL: Q7 answered `a` is confirmed: the line is gone (the test was written before the answer, F19)",
                 (found[0]["answered"], found[0]["line"]), (True, ""))
        check_eq("F3 CONTROL: ... and gate B no longer lists it", "Q7" in [q["id"] for q in GB.still_open(
            json.loads(READINESS)["open_questions"], QR.load(task), {}, task)], False)
    finally:
        cleanup(project)
    # `b` with a KNOWN before is a value the person gave: settled, not listed (the control of the control)
    known = json.loads(READINESS)
    known["open_questions"][1]["before"] = {"value": "403", "where": "the base revision"}
    project, task, manifest = _t271_story(bound_then_4=False, readiness=json.dumps(known))
    try:
        _answer(task, "b")
        check_eq("F3 CONTROL: Q7 answered `b` with before `403` known is settled: not listed at gate B",
                 "Q7" in [q["id"] for q in GB.still_open(known["open_questions"], QR.load(task), {}, task)], False)
        check_eq("F3: the one predicate: it agrees with the resolver (`person`, 403)",
                 (C.before_value_needed({"status": "answered", "reading": "b", "before": {"value": "unknown"}}),
                  C.before_value_needed({"status": "answered", "reading": "b", "before": {"value": "403"}}),
                  C.before_value_needed({"status": "answered", "reading": "a", "before": {"value": "unknown"}}),
                  C.before_value_needed({"status": "answered", "reading": "b"})), (True, False, False, False))
    finally:
        cleanup(project)
    print("K-F3 | Q7 answered `b`, before `unknown`: Left-with-you line kept (answered False), gate B lists Q7 'you chose the "
          "behaviour before the change, but nobody knows what it was'; Q7 answered `a`: line gone, not listed")


def test_t271_f5_a_re_raise_with_other_facts_is_refused_and_a_hash_less_answer_confirms_nothing() -> None:
    with_oracles = TC015.replace("updated: 2026-10-01", "updated: 2026-10-02")
    project, story, case = _story("qa-oracle-t271-raise-", with_oracles)
    try:
        first = QR.raise_question(story, case, 4, QUESTION)
        check_eq("F5: the first raise takes Q8", first["id"], "Q8")
        check_eq("F5: the same (case, Then) with the SAME before/now is the same id (idempotent, as today)",
                 QR.raise_question(story, case, 4, QUESTION)["id"], "Q8")
        check_eq("F5: ... even with the words spaced differently (the facts are the same)",
                 QR.raise_question(story, case, 4, dict(QUESTION, now={"value": " 400 ", "where": "observed  by the S5 run"}))["id"], "Q8")
        for label, spec in (("another `now`", dict(QUESTION, now={"value": "403", "where": "observed by the S5 run"})),
                            ("another `before`", dict(QUESTION, before={"value": "400", "where": "the base revision"})),
                            ("another `where` only", dict(QUESTION, now={"value": "400", "where": "the diff"}))):
            try:
                QR.raise_question(story, case, 4, spec)
                check(f"F5: a re-raise with {label} is refused", False, "no refusal")
            except QR.Refused as exc:
                text = " ".join(str(exc).split())
                check_in(f"F5: {label}: the refusal names the existing question", "was already raised as Q8", text)
                check_in(f"F5: {label}: ... and the text it shows (before, now)", "showing before unknown (the base revision is not in the hunk), now 400 (observed by the S5 run)", text)
                check_in(f"F5: {label}: ... and the text of the new entry", "this entry shows before", text)
        check_eq("F5: nothing was added or changed by the refusals",
                 [(q["id"], (q.get("now") or {}).get("value")) for q in json.loads((story / "work" / "requirements-readiness.json").read_text(encoding="utf-8"))["open_questions"]][-1],
                 ("Q8", "400"))
        # the S4-exit step reports it per Then, never silently
        text = with_oracles.replace("plan_row: TS-15\n", 'then_oracles: [{"then": 4, "source": "unknown", "ref": "raise"}]\n'
                                    'question_thens: [{"question": "raise", "then": 4, "readings": {"a": "HTTP 400", "b": ""}, "not_needed": ""}]\n'
                                    + "raise_questions: " + json.dumps([dict(QUESTION, then=4, now={"value": "403", "where": "diff"})]) + "\nplan_row: TS-15\n", 1)
        done = QR.raise_for_case(story, text, "TP1-15045_TC_015")
        check_eq("F5: raise_for_case raises nothing for the changed facts and says why, once", (done["raised"], len(done["problems"])), ([], 1))
        check_in("F5: ... naming the existing id", "was already raised as Q8", done["problems"][0])
    finally:
        cleanup(project)
    # claim_confirmed: a record with no hash is unconfirmed; the card's hash, not the apply-time hash, is what detects an edit
    answered = {"id": "Q7", "status": "answered", "reading": "a"}
    check_eq("F5: changed_since_answer False confirms; True and None (no hash stored) do not; an absent key does not",
             [C.claim_confirmed(dict(answered, changed_since_answer=v)) for v in (False, True, None)] + [C.claim_confirmed(answered)],
             [True, False, False, False])
    project, task, _ = _t271_story()
    try:
        card_hash = {q["id"]: q for q in QR.load(task)["questions"]}["Q7"]["row_hash"]          # what the card showed
        readiness = task / "work" / "requirements-readiness.json"
        data = json.loads(readiness.read_text(encoding="utf-8"))
        # HF4-7: `where` is not in the readings' text, so the pair stays the code's pair (an edit of `now.value` would
        # unmark it: the readings are compared to `claim_readings(before, now)` byte for byte)
        data["open_questions"][1]["now"] = dict(data["open_questions"][1]["now"], where="edited after the card was shown")
        readiness.write_text(json.dumps(data), encoding="utf-8")                                 # the row moved under the card
        apply_time_hash = {q["id"]: q for q in QR.load(task)["questions"]}["Q7"]["row_hash"]
        check("F5: the row moved: the apply-time hash is not the card's", apply_time_hash != card_hash)
        QR.record(task, "Q7", "answered", "Q7: a", "gate A", "driver", card_hash, reading="a")
        stale = {q["id"]: q for q in QR.load(task)["questions"]}["Q7"]
        check_eq("F5: an answer stored with the CARD's hash is detected as changed -> unconfirmed",
                 (stale["changed_since_answer"], C.claim_confirmed(stale)), (True, False))
        QR.record(task, "Q7", "answered", "Q7: a", "gate A", "driver", apply_time_hash, reading="a")
        masked = {q["id"]: q for q in QR.load(task)["questions"]}["Q7"]
        check_eq("F5: the same answer stored with the APPLY-TIME hash hides the edit (the defect the applier must not have)",
                 (masked["changed_since_answer"], C.claim_confirmed(masked)), (False, True))
    finally:
        cleanup(project)
    print("K-F5 | re-raise (case, Then 4) with another now/before/where -> Refused 'was already raised as Q8 showing before unknown "
          "(...), now 400 (...); this entry shows ...'; same facts -> Q8; claim_confirmed(None hash) False; card hash != apply-time hash -> changed True")


def test_t271_f6_a_decision_inside_a_code_block_is_said_not_read() -> None:
    questions = [{"id": "Q1", "readings": [1, 2]}, {"id": "Q7", "readings": [1, 2]}]
    cases = ["TP1-15045_TC_014"]
    got = QR.parse_choices("```\nQ7: a\n```\n", questions, cases)
    check_eq("F6: `Q7: a` inside a fenced block applies nothing", got["choices"], {})
    check_eq("F6: ... and is reported, once", got["fenced"], ["Q7: a"])
    check_eq("F6: ... as the one line a caller prints", QR.fence_notices(got), ["a decision inside a code block is not read: Q7: a"])
    got = QR.parse_choices("Q1: b\n```\nQ7: a\n", questions, cases)
    check_eq("F6: after an UNCLOSED fence: the line before it is read, the one after is not",
             (got["choices"], got["fenced"]), ({"Q1": "b"}, ["Q7: a"]))
    got = QR.parse_choices("```\nTC_014: accept as blocked\nQ7: not needed\n```\n", questions, cases)
    check_eq("F6: a case decision and `not needed` inside a fence are reported too, applied to nothing",
             (got["case_tokens"], got["not_needed"], got["fenced"]), ([], [], ["TC_014: accept as blocked", "Q7: not needed"]))
    got = QR.parse_choices("Q7: a\n", questions, cases)
    check_eq("F6 CONTROL: the same line outside a fence is read and reports nothing", (got["choices"], got["fenced"]), ({"Q7": "a"}, []))
    got = QR.parse_choices("```\nprint('hello')\nsome words: of a code block\n```\n> Q7: a\n", questions, cases)
    check_eq("F6 CONTROL: a code block that holds no decision, and a quoted line, say nothing", (got["choices"], got["fenced"]), ({}, []))
    long_line = "Q7: a" + " " * 0 + "."
    got = QR.parse_choices("```\n" + long_line + "\n" + "- " * 5 + "Q1: a\n```\n", questions, cases)
    check_eq("F6: a list marker in front of the token is still the token (the notice shows the line as typed)",
             got["fenced"], ["Q7: a.", "- - - - - Q1: a"])
    check_eq("F6: a notice for a very long line is cut for the notice only", len(QR.fence_notices({"fenced": ["Q7: a " + "x" * 400]})[0]) < 260, True)
    print("K-F6 | '```\\nQ7: a\\n```' -> choices {} + 'a decision inside a code block is not read: Q7: a'; unclosed fence: the same; outside: read")


def test_t271_d2_expectation_unconfirmed_is_the_contracts_word() -> None:
    import ledger as L
    import role_digest as RD
    import stage_guard as SG
    import manifest_from_tests as MFT
    import judge_form
    check_eq("D2: one home - the contract's list holds the word exactly once", list(C.UNRESOLVED_REASONS).count("expectation_unconfirmed"), 1)
    check("D2: ... and ledger / manifest_from_tests spell it by importing it (FR-13, no second literal)",
          L.EXPECTATION_UNCONFIRMED is C.EXPECTATION_UNCONFIRMED and MFT.EXPECTATION_UNCONFIRMED is C.EXPECTATION_UNCONFIRMED)
    check_eq("D2: the contract accepts it as an `unresolved[]` reason, and rejects an invented one",
             (C.unresolved_reason_ok("expectation_unconfirmed"), C.unresolved_reason_ok("wishful")), (True, False))
    check_eq("D2: manifest_from_tests' list IS the contract's (no `+ word`, no duplicate)", tuple(MFT.UNRESOLVED_REASON_WORDS), tuple(C.UNRESOLVED_REASONS))
    check_eq("D2: stage_guard's closed list (the reader of S6-S8 dispatches) holds it once",
             list(SG.closed_unresolved_reasons()).count("expectation_unconfirmed"), 1)
    check_eq("D2: ... and its manifest rule refuses an invented word and passes this one",
             SG.unresolved_rows_without_decision({"unresolved": [{"case": "TC-1", "reason": "expectation_unconfirmed"}, {"case": "TC-2", "reason": "wishful"}]}),
             ["TC-2 (wishful)"])
    check("D2: role_digest knows it as a row state", "expectation_unconfirmed" in RD.ROW_STATES)
    # X7-2: the reason mapping left judge_form; the role chooses the route word, so no judge can put `expectation_unconfirmed` anywhere
    check("D2: judge_form has no reason mapping (the role chooses the route word; only a question's state makes a Then unconfirmed)",
          not any(hasattr(judge_form, name) for name in ("unresolved_reason", "normalise_unresolved", "UNRESOLVED_OPTIONS")))
    print("K-D2 | contract.UNRESOLVED_REASONS holds `expectation_unconfirmed` once; judge_form has no reason mapping; "
          "role_digest/stage_guard/check_manifest_v0 accept it; whole-case row: test_check_delivery.py (person debt, no hold)")


# ## G2-12 -- code and somebody else's test are no source of a requirement (`contract.unconfirmed_requirements`).
# DOC-WITNESS KEYS, quoted VERBATIM from the spec lines of docs/tasks/specs/t-527-s2-final.md (section 5) BEFORE this was run:
G212_KEYS = (
    ("references/templates/requirements-register.md", "test:<ref>"),
    ("references/templates/requirements-register.md", "bug:candidate-defect"),
    ("references/templates/requirements-register.md", "current-code:"),    # moved charter -> template (spec t-1765 X1, B-D)
    ("skills/qa-story/phases/s2.md", "test:<ref>"),
)


def _g212_register(rows: list, matrix: dict = None, created: str = "2026-10-31", claims: str = "") -> str:
    """A register of `(r, source, derived_from, ac_ref, observable)` rows; every matrix row `silent` unless `matrix` says."""
    head = f"---\ntask: X-1\ncreated: {created}\nids: [{', '.join(r[0] for r in rows)}]\n---\n" if created is not None else ""
    out = [head, "## Register\n", "| R | Requirement | source | derived_from | verifiable | ac_ref | observable | impact |",
           "|---|---|---|---|---|---|---|---|"]
    out += [f"| {r} | text | {s} | {d} | yes | {a} | {o} | degraded |" for r, s, d, a, o in rows]
    out += ["", "## Contradiction matrix\n", "| R | parent | comments | area cases | area bugs |", "|---|---|---|---|---|"]
    out += [f"| {r[0]} | " + (matrix or {}).get(r[0], "silent | silent | silent | n/a:none") + " |" for r in rows]
    return "\n".join(out) + "\n" + claims


G212_ROWS = [
    ("R-1", "derived", "aspect:x", "-", "current-code:src/a.py:1"),            # in: the plain class
    ("R-2", "derived", "aspect:x", "n/a", "current-code:src/a.py:2"),          # in: `n/a` is an empty ac_ref
    ("R-3", "derived", "aspect:x", "", "CURRENT-CODE:src/a.py:3"),             # in: case
    ("R-4", "derived", "aspect:x", "—", "`current-code:src/a.py:4`"),          # in: backticks
    ("R-5", "derived", "test:tests/t.py::test_a", "-", "expected-contract"),   # in: another side's test
    ("R-6", "derived", "Test:tests/t.py::test_b", "-", "none"),                # in: case of `test:`
    ("R-7", "ac", "—", "AC-1", "current-code:src/a.py:7"),                     # out: a ticket source, code is a surface
    ("R-8", "story", "—", "-", "current-code:src/a.py:8"),                     # out
    ("R-9", "discussion", "—", "-", "current-code:src/a.py:9"),                # out
    ("R-10", "derived", "aspect:x", "AC-2", "current-code:src/a.py:10"),       # out: non-empty ac_ref
    ("R-11", "derived", "aspect:x", "-", "current-code:src/a.py:11"),          # out: the matrix contradicts (below)
    ("R-12", "derived", "invariant:rule-1", "-", "expected-contract"),         # out: an invariant
    ("R-13", "derived", "aspect:x", "-", "diff:src/a.py:13"),                  # in: the older class, unchanged
]
G212_IN = {"R-1", "R-2", "R-3", "R-4", "R-5", "R-6", "R-13"}
G212_MATRIX = {"R-11": 'contradicts:"AC1" | silent | silent | n/a:none'}
G212_CLAIMS = ("\n## Behaviour claims\n\n| R | before | before_ref | now | now_ref | differs | question |\n|---|---|---|---|---|---|---|\n"
               "| R-1 | unknown | absent | 403 | current-code:src/a.py:1 | unknown | Q7 |\n")


def test_g2_12_code_and_a_foreign_test_are_no_source() -> None:
    reg = _g212_register(G212_ROWS, G212_MATRIX)
    check_eq("G2-12: the class is exactly the rows whose only source is the code or somebody else's test",
             C.unconfirmed_requirements(reg), G212_IN)
    check_eq("G2-12: `implementation_only` is not changed (the diff-only R-13 alone)", set(C.implementation_only(reg)), {"R-13"})
    check_eq("G2-12 (AR-28): `questions=None` confirms nothing - the whole class is listed", C.unconfirmed_requirements(reg, None), G212_IN)
    check_eq("G2-12: an empty question dict confirms nothing", C.unconfirmed_requirements(reg, {}), G212_IN)
    check_eq("G2-12: an unreadable question (not a dict) confirms nothing", C.unconfirmed_requirements(reg, {"Q7": "answered"}), G212_IN)
    check_eq("G2-12: nothing in the register -> set()", C.unconfirmed_requirements(_g212_register([])), set())
    check_eq("G2-12: no text at all -> set()", C.unconfirmed_requirements(""), set())
    claimed = _g212_register(G212_ROWS, G212_MATRIX, claims=G212_CLAIMS)
    answered = {"id": "Q7", "status": "answered", "reading": "a", "changed_since_answer": False}
    check_eq("G2-12 (AR-28): a register WITH a claim row and `questions=None` still lists the claimed R (no answer is no confirmation)",
             C.unconfirmed_requirements(claimed, None), G212_IN)
    check_eq("G2-12: a claim answered `a` on the text shown confirms ITS row only",
             C.unconfirmed_requirements(claimed, {"Q7": answered}), G212_IN - {"R-1"})
    for label, question in (("reading b", dict(answered, reading="b")), ("own words", dict(answered, reading="")),
                            ("edited since the answer", dict(answered, changed_since_answer=True)),
                            ("no stored hash", dict(answered, changed_since_answer=None)),
                            ("named", {"id": "Q7", "status": "named"}), ("open", {"id": "Q7", "status": "open"})):
        check_eq(f"G2-12: {label} leaves the claim unconfirmed", C.unconfirmed_requirements(claimed, {"Q7": question}), G212_IN)
    # the cutoff: a register written before it keeps the old reading (FR-14); a date nobody can read is the NEW world
    check_eq("G2-12: a register created the day before the cutoff reads as before (the diff-only R-13 alone)",
             C.unconfirmed_requirements(_g212_register(G212_ROWS, G212_MATRIX, created="2026-10-30")), {"R-13"})
    check_eq("G2-12: ...created ON the cutoff day reads as new", C.unconfirmed_requirements(_g212_register(G212_ROWS, G212_MATRIX)), G212_IN)
    for bad in ("yesterday", "2026-13-45", "", "31.10.2026"):
        check_eq(f"G2-12: created {bad!r} (unreadable) is the new world - the error is toward 'not confirmed'",
                 C.unconfirmed_requirements(_g212_register(G212_ROWS, G212_MATRIX, created=bad)), G212_IN)
    check_eq("G2-12: no front matter at all is the new world too", C.unconfirmed_requirements(_g212_register(G212_ROWS, G212_MATRIX, created=None)), G212_IN)
    check("G2-12: the old fixture (created 2026-10-01) is read as it was",
          C.unconfirmed_requirements(REGISTER) == C.unconfirmed_implementation_only(REGISTER) == {"R-16", "R-17", "R-18", "R-19"})
    # the refusal of an `ac` oracle on such a row is the old door (`unknown` + the question), said for the whole class
    errors = C.then_oracle_errors("TC.md", '[{"then": 1, "source": "ac", "ref": "R-1"}]', None, [1],
                                  impl_only=C.unconfirmed_requirements(reg), known_r={"R-1"})
    check_in("G2-12: an `ac` oracle on a current-code R is refused with the old words and the door", "R-1 is implementation-only", errors)
    check_in("G2-12: ...and the refusal names the new sources", "current-code", errors)
    check_in("G2-12: ...and the door", "Use `unknown` with the question that shows before/now", errors)
    row = {"r": "R-1", "before": "unknown", "before_ref": "", "now": "403", "now_ref": "current-code:src/a.py:1", "differs": "unknown", "question": "Q7"}
    check_eq("G2-12 (F-2): a claim row with `before: unknown` and a `current-code:` now_ref is a legal row", C.claim_row_errors(row), [])
    missing = C.claim_row_errors(dict(row, now_ref=""))
    check_in("G2-12: the text of the refusal names the current-code place", "diff line or current-code place", missing)
    check_in("G2-12: ...and keeps the words the older tests read", "`now` and `now_ref` are both required", missing)


def test_g2_12_the_grammar_and_the_gates() -> None:
    import grammar as G
    import validate_artifacts as VA
    for value in ("test:tests/t.py::test_a", "bug:candidate-defect", "bug:BUG-12", "norm:rfc-1"):
        check(f"G2-12: derived_from {value!r} passes the grammar", bool(G.DERIVED_FROM_RE.match(value)))
    for value in ("`test:tests/t.py`", "test:", "tests:x", "", "unit:x"):
        check(f"G2-12: derived_from {value!r} does not (backticks, empty ref, other word)", not G.DERIVED_FROM_RE.match(value))
    project = temp_project("qa-g212-")
    try:
        use_project(project)
        task = project / "qa-factory" / "artifacts" / "X-1"
        (task / "work").mkdir(parents=True)
        reg = _g212_register(G212_ROWS, G212_MATRIX)
        (task / "work" / "requirements-register.md").write_text(reg, encoding="utf-8")
        # the register check names the grammar in the new words (AR-22: form, template, charter, refusal together)
        errors: list = []
        VA.check_register(task / "work" / "requirements-register.md", errors)
        bad = _g212_register([("R-1", "derived", "whatever", "-", "current-code:a:1")])
        (task / "work" / "bad.md").write_text(bad, encoding="utf-8")
        errors = []
        VA.check_register(task / "work" / "bad.md", errors)
        check_in("G2-12: the grammar refusal names `test:`", "test:<ref>", errors)
        check_in("G2-12: ...`norm:`", "norm:<ref>", errors)
        check_in("G2-12: ...`bug:BUG-NNN` and `bug:candidate-defect`", "bug:candidate-defect", errors)
        # the plan gate (validate_artifacts :1605): an oracle naming a code-sourced R is refused; an empty `oracle` is not
        # (the row waits as `oracle_unknown`; the S3 fence of G2-15 asks for it) -- the gate must not lock the role
        plan = ("---\ntask: X-1\ncreated: 2026-10-31\n---\n# Test plan\n\n## Plan\n\n"
                "| TS | what we verify | R | defect hypothesis | impact class | priority | observable | oracle | disposition + reason | fit | level | technique |\n"
                "|---|---|---|---|---|---|---|---|---|---|---|---|\n"
                "| TS-1 | PUT returns the code | R-1 | contract @ update | degraded | P2 | diff:src/a.py:1 | {oracle} | `automate` - the row | new | api | partitions |\n")
        for oracle, refused in (("requirement:R-1", True), ("requirement:R-7", False), ("", False)):
            (task / "test-plan.md").write_text(plan.replace("{oracle}", oracle), encoding="utf-8")
            errors = []
            VA.check_plan_v0(task / "test-plan.md", errors)
            hit = [e for e in errors if "implementation-only" in e]
            check_eq(f"G2-12 pin (:1605): plan oracle {oracle!r} on a code-sourced register is {'refused' if refused else 'not refused for it'}",
                     bool(hit), refused)
        # the case gate (validate_artifacts :292) reads the same function
        tc = ("---\nid: TC-1\ntask: X-1\ntitle: t\nupdated: 2026-10-31\ncreated: 2026-10-31\n---\n## Then\n1. It answers 200.\n")
        errors = []
        VA.check_then_oracles(task / "TC-1.md", {"task": "X-1", "then_oracles": '[{"then": 1, "source": "ac", "ref": "R-1"}]'}, tc, errors)
        check_in("G2-12: the case gate refuses an `ac` oracle on a current-code R", "R-1 is implementation-only", errors)
        # the coverage reader and the manual-evidence reader
        import manual_evidence as ME
        gaps = ME.expectation_gaps(task, {"requirements": ["R-1", "R-7"], "path": ""})
        check_eq("G2-12: manual_evidence names the code-sourced R and not the ticket-sourced one",
                 [g[1].split(" ")[0] for g in gaps if g[1].startswith("R-")], ["R-1"])
    finally:
        cleanup(project)
    # the doc keys, with a negative control
    check_eq("G2-12 DOC-WITNESS: the form, the charter and the phase carry every key", missing_g212(read_normalised), [])
    rel, key = G212_KEYS[2]
    check_eq("G2-12 NEGATIVE CONTROL: with one key cut out the check reports exactly that key",
             missing_g212(lambda name: read_normalised(name).replace(key, "") if name == rel else read_normalised(name)), [(rel, key)])


def missing_g212(read) -> list:
    return [(rel, key) for rel, key in G212_KEYS if " ".join(key.split()) not in read(rel)]


def test_pc9a_reference_precedent_needs_a_parity_requirement_and_an_item() -> None:
    """C7 (t-2181 PC-9a): `precedent` + `reference:<item>` passes only with the item in the snapshot AND a basis `requirement:R-n` whose
    register row says `parity: yes`; the `base:` form is as before; no snapshot (the world before) refuses the reference form with a door."""
    register = ("## Register\n\n| id | Requirement | source | derived_from | x | ac_ref | observable | delta | parity |\n|---|---|---|---|---|---|---|---|---|\n"
                "| R-1 | cart as before | ticket | - | - | - | - | changed | yes |\n| R-2 | totals | ticket | - | - | - | - | changed | no |\n"
                "| R-3 | other | ticket | - | - | - | - | changed |  |\n")
    parity = C.parity_ids(register)
    check_eq("the parity column is read by its header: only the exact word `yes`", parity, {"R-1"})
    check_eq("a register with no such column has no parity requirement", C.parity_ids(register.replace(" | parity |", " |", 1)), set())

    def errors(ref, snapshot, basis, parity_ids=parity):
        raw = json.dumps([{"then": 1, "source": "precedent", "ref": ref}])
        return C.then_oracle_errors("TC.md", raw, None, [1], known_r={"R-1", "R-2", "R-3"}, snapshot_items=snapshot, parity=parity_ids, basis=basis)

    items = {"cart-total", "cart-badge"}
    ok = errors("reference:cart-total", items, "requirement:R-1")
    check_eq("an item of the snapshot under a parity requirement is accepted", ok, [])
    for label, got, want in (
            ("an item the snapshot lacks", errors("reference:nope", items, "requirement:R-1"), "not an item"),
            ("a requirement that is not parity", errors("reference:cart-total", items, "requirement:R-2"), "parity: yes"),
            ("a row with an empty parity cell", errors("reference:cart-total", items, "requirement:R-3"), "parity: yes"),
            ("a basis that names no requirement", errors("reference:cart-total", items, "history:old"), "requirement:R-n"),
            ("no snapshot at all", errors("reference:cart-total", None, "requirement:R-1"), "no reference snapshot"),
            ("a register that could not be read", errors("reference:cart-total", items, "requirement:R-1", None), "no `parity` column"),
            ("a ref of no known form", errors("reference:", items, "requirement:R-1"), "reference:<item>")):
        check(f"{label} is refused with a door ({want})", len(got) == 1 and want in got[0], str(got))
    check_eq("the `base:` form is as before, whatever the snapshot says",
             errors("base:b9c0c4e:src/a/b.py:989", None, "history:old"), [])
    check("and `reference:` is no oracle for the other words", any("needs a register requirement" in e for e in C.then_oracle_errors(
        "TC.md", json.dumps([{"then": 1, "source": "requirement", "ref": "reference:cart-total"}]), None, [1], known_r={"R-1"})))


def test_pc9a_the_case_gate_wires_the_snapshot_and_parity() -> None:
    """F2: `validate_artifacts.check_then_oracles` (the production caller) reads the story's own snapshot, the register's parity column and
    the case basis; an archived story finds its snapshot beside its register; a missing snapshot is refused truthfully."""
    import shutil
    import validate_artifacts as VA
    register = ("## Register\n\n| id | Requirement | source | derived_from | x | ac_ref | observable | delta | parity |\n|---|---|---|---|---|---|---|---|---|\n"
                "| R-1 | cart as before | ticket | - | - | - | - | changed | yes |\n| R-2 | totals | ticket | - | - | - | - | changed | no |\n")
    snapshot = "reference_env: sample\nwalked_at: 2026-11-11T00:00:00Z\nitems:\n  - id: cart-total\n    old_test: a.spec.ts:1\ngaps: []\n"
    text = "---\nid: TC-1\ntask: X-1\ntitle: t\nupdated: 2026-11-11\ncreated: 2026-11-11\n---\n## Then\n1. The total is as before.\n"

    def case(ref, basis="requirement:R-1"):
        return {"task": "X-1", "basis": basis, "then_oracles": json.dumps([{"then": 1, "source": "precedent", "ref": ref}])}

    def run(fm):
        errors: list = []
        VA.check_then_oracles(task / "TC-1.md", fm, text, errors)
        return errors

    project = temp_project("qa-pc9a-")
    try:
        use_project(project)
        task = project / "qa-factory" / "artifacts" / "X-1"
        (task / "work").mkdir(parents=True)
        (task / "work" / "requirements-register.md").write_text(register, encoding="utf-8")
        got = run(case("reference:cart-total"))
        check("PC-9a F2: with no snapshot file the reference form is refused with the true cause", len(got) == 1 and "no reference snapshot" in got[0], str(got))
        check_eq("PC-9a F2: a `base:` precedent is unchanged with no snapshot", run(case("base:b9c0c4e:src/a/b.py:989", "history:old")), [])
        (task / "work" / "reference-snapshot.yaml").write_text(snapshot, encoding="utf-8")
        check_eq("PC-9a F2: a snapshot item under a parity requirement passes through the case gate", run(case("reference:cart-total")), [])
        got = run(case("reference:cart-total", "requirement:R-2"))
        check("PC-9a F2: a basis whose register row is not parity is refused", len(got) == 1 and "parity: yes" in got[0], str(got))
        got = run(case("reference:nope"))
        check("PC-9a F2: an item the snapshot lacks is refused", len(got) == 1 and "not an item" in got[0], str(got))
        archive = project / "qa-factory" / "artifacts" / "_archive"
        archive.mkdir()
        shutil.move(str(task), str(archive / "X-1"))
        task = archive / "X-1"
        check_eq("PC-9a F2: an archived story finds its own snapshot and register", run(case("reference:cart-total")), [])
    finally:
        cleanup(project)


def test_pc9c_claims_take_the_reference_before_ref_with_its_item_check() -> None:
    """PC-9c B1 (critic t-2549): `before_ref: reference:<item>` is a legal claim form with ONE check, the item is in the story's reference
    snapshot (`snapshot_items`). Accepted with an existing item; refused naming the item, what was expected and the door for a missing one
    (and for an empty snapshot); with no snapshot given (a story with no reference stand) refused exactly as before PC-9a/9c, the four forms named."""
    row = {"r": "R-1", "before": "the Pay button", "before_ref": "base:b9c0c4e:src/a.py:9", "now": "x", "now_ref": "diff:+a.py:1",
           "differs": "no", "question": "Q1"}
    check_eq("a `base:` before_ref is still a legal claim", [e for e in C.claim_row_errors(row) if "before_ref" in e], [])
    check_eq("a `base:` before_ref stays legal with a snapshot given", [e for e in C.claim_row_errors(row, snapshot_items={"cart-total"}) if "before_ref" in e], [])
    check_eq("an existing snapshot item is accepted", C.claim_row_errors(dict(row, before_ref="reference:cart-total"), snapshot_items={"cart-total"}), [])
    for ref, items in (("reference:nope", {"cart-total"}), ("reference:nope", set())):
        got = [e for e in C.claim_row_errors(dict(row, before_ref=ref), snapshot_items=items) if "before_ref" in e]
        check(f"a missing item {ref!r} (snapshot of {len(items)}) is refused naming the item, the snapshot and the door",
              len(got) == 1 and "reference:nope" in got[0] and "reference-snapshot.yaml" in got[0] and "cite one of them" in got[0], str(got))
    for ref in ("reference:cart-total", "reference:"):
        got = [e for e in C.claim_row_errors(dict(row, before_ref=ref)) if "before_ref" in e]
        check(f"with no snapshot a claim `before_ref` {ref!r} is refused with the four forms named", len(got) == 1 and "`base:<rev>:<path>:<line>`" in got[0], str(got))
    got = [e for e in C.claim_row_errors(dict(row, before_ref="reference:"), snapshot_items={"cart-total"}) if "before_ref" in e]
    check("an empty `reference:` is refused even with a snapshot", len(got) == 1 and "`base:<rev>:<path>:<line>`" in got[0], str(got))
    check_eq("an `absent` claim with a reference ref is not read as a reference claim",
             [e for e in C.claim_row_errors(dict(row, before="absent", before_ref="reference:cart-total"), snapshot_items={"cart-total"}) if "before_ref" in e],
             ["`before_ref` of an `absent` claim is `absent`, not 'reference:cart-total'"])
    check_eq("requirement_id reads only `requirement:R-n`", (C.requirement_id(" requirement:R-12 "), C.requirement_id("requirement:R-"),
                                                             C.requirement_id("history:old"), C.requirement_id(None)), ("R-12", None, None, None))
    got = C.then_oracle_errors("TC.md", json.dumps([{"then": 1, "source": "precedent", "ref": "reference:x"}]), None, [1],
                               snapshot_items={"x"}, parity=None, basis="requirement:R-1")
    check("a register with no parity column is named so, not blamed on a row", len(got) == 1 and "no `parity` column" in got[0], str(got))


def test_pc9b_a_snapshot_the_runner_wrote_is_read_by_the_case_gate() -> None:
    """PC-9b (critic t-2429 F2, end to end): the snapshot is written by the RUNNER's command (`reference_snapshot.put`, the file its
    card names), and the production caller (`validate_artifacts.check_then_oracles`) accepts a `reference:` precedent on that item under a
    parity requirement and refuses an item the snapshot does not hold; with no snapshot written the refusal says so, truthfully."""
    import reference_snapshot as RS
    import validate_artifacts as VA
    register = ("## Register\n\n| id | Requirement | source | derived_from | x | ac_ref | observable | delta | parity |\n|---|---|---|---|---|---|---|---|---|\n"
                "| R-1 | cart as before | ticket | - | - | - | - | changed | yes |\n")
    text = "---\nid: TC-1\ntask: X-1\ntitle: t\nupdated: 2026-11-11\ncreated: 2026-11-11\n---\n## Then\n1. The total is as before.\n"

    def run(ref):
        fm = {"task": "X-1", "basis": "requirement:R-1", "then_oracles": json.dumps([{"then": 1, "source": "precedent", "ref": ref}])}
        errors: list = []
        VA.check_then_oracles(task / "TC-1.md", fm, text, errors)
        return errors
    project = temp_project("qa-pc9b-")
    try:
        use_project(project)
        task = project / "qa-factory" / "artifacts" / "X-1"
        (task / "work").mkdir(parents=True)
        (task / "work" / "requirements-register.md").write_text(register, encoding="utf-8")
        got = run("reference:cart-total")
        check("PC-9b: no snapshot written yet - refused with the true cause", len(got) == 1 and "no reference snapshot" in got[0], str(got))
        items = project / "items.json"
        items.write_text(json.dumps({"items": [{"id": "cart-total", "area": "cart", "user_path": "open", "observed": "total 10",
                                                "old_test": "a.spec.ts:1", "locators_portable": "unknown"}], "gaps": []}), encoding="utf-8")
        RS.put(task, "old", items)
        check_eq("PC-9b: the item the runner's put wrote is accepted by the production caller", run("reference:cart-total"), [])
        got = run("reference:other")
        check("PC-9b: an item the snapshot does not hold is refused", len(got) == 1 and "not an item" in got[0], str(got))
    finally:
        cleanup(project)


def test_pc9c_the_s2_check_and_the_s3_projector_pass_a_reference_claim() -> None:
    """PC-9c B1 at the production call sites (t-2551): a claim citing an item of the story's snapshot passes the S2 register check
    (`validate_artifacts.check_behaviour_claims`), the S3 projector's judge (`_judge`, :180), its read-back (`_post_build`, :609) and its
    S3 check (`s3_claim_errors`, :841); a missing item is refused at each, and so is the form when the story has no snapshot."""
    import claim_projector as CP
    import reference_snapshot as RS
    import validate_artifacts as VA
    project = temp_project("qa-pc9c-claims-")
    try:
        use_project(project)
        task = project / "qa-factory" / "artifacts" / "T-1"
        (task / "work").mkdir(parents=True)
        for name in ("requirements-register.md", "requirements-readiness.json"):
            (task / "work" / name).write_bytes((FIXTURES / name).read_bytes())
        claim_ref = "reference:cart-total"
        grounding = "\n".join([
            "schema_version: 1", "implementation_source: diff", "rows:", "  - id: G-4", "    label: behaviour_change", '    reason: "x"', "claims:",
            '  - r: "R-28"', '    row: "G-4"', '    requirement: "PUT answers 403 when both checks fail."', "    impact: degraded",
            '    before: "the cart showed 10.00"', f'    before_ref: "{claim_ref}"', '    now: "403"', '    now_ref: "diff:b/src/w.py:541"', '    differs: "yes"',
            "    question: raise", "    ask:", '      question: "Which status code must PUT return when both checks fail?"',
            '      source_says: [{quote: "returns the same results as before", where: "register R-19"}]', "      severity: major", "      owner_role: po_ba", ""])
        (task / "work" / "grounding.yaml").write_bytes(grounding.encode("utf-8"))

        def snapshot(*ids):
            items = project / "items.json"
            items.write_text(json.dumps({"items": [{"id": i, "area": "cart", "user_path": "open", "observed": "total 10", "old_test": "a.spec.ts:1",
                                                    "locators_portable": "unknown"} for i in ids], "gaps": ["none"] if not ids else []}), encoding="utf-8")
            RS.put(task, "old", items, replace=True)

        def s2_errors():
            errors: list = []
            reg = task / "work" / "requirements-register.md"
            VA.check_behaviour_claims(reg, reg.read_text(encoding="utf-8"), errors)
            return [e for e in errors if "R-28:" in e]      # the fixture's older rows R-16..R-19 owe claims of their own; this is R-28's

        res = CP.project(task)     # no snapshot: the form is refused, nothing written, the four forms named
        check("PC-9c B1 projector, no snapshot: refused with the four forms", res.wrote is False and any("`base:<rev>:<path>:<line>`" in str(p) for p in res.problems), str(res.problems))
        snapshot("other-item")
        res = CP.project(task)
        check("PC-9c B1 projector (_judge): an item the snapshot lacks is refused, naming it", res.wrote is False and any("cart-total" in str(p) and "not an item" in str(p) for p in res.problems), str(res.problems))
        snapshot("cart-total")
        res = CP.project(task)
        check_eq("PC-9c B1 projector (_judge, _post_build): an item the snapshot holds is projected", (res.projected, [str(p) for p in res.problems], res.wrote), (["R-28"], [], True))
        check_eq("PC-9c B1 S2 check (check_behaviour_claims): the projected claim with an existing item passes", s2_errors(), [])
        check_eq("PC-9c B1 S3 check (s3_claim_errors): no finding with the item present", [str(p) for p in CP.s3_claim_errors(task)], [])
        snapshot("other-item")
        got = s2_errors()
        check("PC-9c B1 S2 check: the item gone from the snapshot is refused, naming it", len(got) == 1 and "cart-total" in got[0] and "not an item" in got[0], str(got))
        found = [str(p) for p in CP.s3_claim_errors(task)]
        check("PC-9c B1 S3 check (s3_claim_errors): the item gone is a finding naming it", any("cart-total" in f and "not an item" in f for f in found), str(found))
        (task / "work" / "reference-snapshot.yaml").unlink()
        got = s2_errors()
        check("PC-9c B1 S2 check: no snapshot at all is refused with the four forms (never a pass)", len(got) == 1 and "`base:<rev>:<path>:<line>`" in got[0], str(got))
    finally:
        cleanup(project)


if __name__ == "__main__":
    test_pc9c_the_s2_check_and_the_s3_projector_pass_a_reference_claim()
    test_pc9b_a_snapshot_the_runner_wrote_is_read_by_the_case_gate()
    test_pc9a_reference_precedent_needs_a_parity_requirement_and_an_item()
    test_pc9a_the_case_gate_wires_the_snapshot_and_parity()
    test_pc9c_claims_take_the_reference_before_ref_with_its_item_check()
    test_g2_12_code_and_a_foreign_test_are_no_source()
    test_g2_12_the_grammar_and_the_gates()
    test_t271_f1_an_unreadable_date_is_never_a_silent_off()
    test_t271_f2_a_green_run_on_an_open_oracle_is_not_a_pass()
    test_t271_f3_the_readers_use_the_resolver_state()
    test_t271_f5_a_re_raise_with_other_facts_is_refused_and_a_hash_less_answer_confirms_nothing()
    test_t271_f6_a_decision_inside_a_code_block_is_said_not_read()
    test_t271_d2_expectation_unconfirmed_is_the_contracts_word()
    test_t227c_doc_witness_keys()
    test_t256_doc_witness_keys()
    test_t256_o1_only_reading_a_confirms_a_behaviour_claim()
    test_t256_o2_a_regression_answer_on_an_unknown_before_is_not_settled()
    test_t256_o4_the_s4_exit_raises_the_designers_question_and_re_pins()
    test_t227b_doc_witness_keys()
    test_the_oracle_words_and_what_they_need()
    test_the_register_is_read_by_code_never_declared()
    test_the_case_front_matter_lines()
    test_the_resolver_reads_an_answered_question_as_the_person()
    test_the_designer_raises_a_before_now_question()
    test_the_raise_command()
    test_doc_witness_keys()
    finish("oracle provenance")
