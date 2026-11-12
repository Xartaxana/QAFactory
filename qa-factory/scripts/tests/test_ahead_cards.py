#!/usr/bin/env python3
"""references/ahead-cards.json — the rules a role's judge applies, said before the work.

Rule FR-38 (design/factory-rules.md): a check that will judge a role's output states its
requirement to the role BEFORE the work, in the fields the role must fill. The measured
payoff of the first card: S3 closed on the first dispatch, 51 turns and $2.53, against 176
turns and $12.83 over four attempts without it.

What is proved:
  * every role stages.json names has a card, and every card names the scripts it was read
    from — so "which check said this" is answerable from the data file alone;
  * every script a card names exists, and no card hands a role a door that is not the
    role's (FR-2): a write command `role-commands.json` scopes to other roles, or one of the
    three commands `guard_pre_tool.human_word_check` closes to every role;
  * the closed lists a card quotes are the checker's own: a verdict, a status or a section
    added to the code breaks this test until the card says it too — that is the whole point
    of writing the card down (FR-13, the card is data beside the check, not prose in a role
    charter that nobody updates);
  * a card stays inside its byte budget and the brief still carries the file list: the card
    is the one thing brief_pack never drops, so an oversized card is paid for by the paths
    the role would otherwise have been handed (FR-15);
  * the `expectation_changes[]` row the automator and the code critic are told about (B-194) is
    spelled the way the code reads it: every field a card, the charter, the contract or the
    rubric names is one `manifest_put.py` refuses a bad value of, and the fields the finding of
    `s5_precheck.py` asks for are the ones the automator card lists; the three verdicts are
    `vocabulary.yaml`'s, spelled exactly, wherever they occur;
  * brief_pack renders the card for every one of the twelve roles.
"""
import difflib
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import brief_pack  # noqa: E402
import contract as C  # noqa: E402
import critic_rollcall  # noqa: E402
import grammar as G  # noqa: E402
import handoff  # noqa: E402
import manifest_put  # noqa: E402
import s5_precheck  # noqa: E402
import validate_artifacts as V  # noqa: E402

PLUGIN = harness.PLUGIN_ROOT
CARD_MAX_BYTES = 1200

# The row of `expectation_changes[]` (B-194): who writes which field. The names are the ones the
# code reads; `code_reads` below proves it per name, so a rename in `manifest_put.py` or
# `s5_precheck.py` breaks this test until every text that says the old name is changed.
EXPECTATION_KEY = "expectation_changes"
AUTHOR_FIELDS = ("then_refs", "what_changed", "reason")
CRITIC_FIELDS = ("critic_verdict", "critic_note")
KEY_FIELDS = ("red_attempt", "green_attempt")
ROW_FIELDS = ("function", "functions", *KEY_FIELDS, *AUTHOR_FIELDS, *CRITIC_FIELDS)
# Words a sentence about the row may back-tick that are not row fields: the cause a finding
# carries and the reason a red test is handed over with.
NON_FIELD_TOKENS = ("test_defect", s5_precheck.CONTRADICTS)

# The closed lists the cards quote, each read from the module that enforces it. A list that
# grows in the code and not in the card is the failure this table exists to catch.
VOCABULARIES = [
    ("qa-scout", "related kinds", C.RELATED_KINDS),
    ("qa-requirements-tester", "requirement sources", G.REQ_SOURCES),
    ("qa-requirements-tester", "observable sources", V.OBSERVABLE_SOURCES_V0),
    ("qa-case-designer", "case frontmatter", V.CASE_REQUIRED + V.CASE_FORM_REQUIRED),
    ("qa-case-designer", "case priorities", V.CASE_PRIORITY),
    ("qa-case-designer", "case channels", V.CASE_CHANNEL),
    ("qa-automator", "dispute values", C.UNRESOLVED_DISPUTES),
    ("qa-code-critic", "expectation change verdicts", handoff.allowed(manifest_put.VERDICTS_LIST)),
    ("qa-case-critic", "critic verdicts", critic_rollcall.CASE_CRITIC_VERDICTS),
    ("qa-case-critic", "merge verdicts", critic_rollcall.MERGE_VERDICTS),
    ("qa-case-critic", "keep grounds", critic_rollcall.KEEP_GROUNDS),
    ("qa-runner", "execution status", C.EXECUTION_STATUS),
    ("qa-runner", "result status", C.RESULT_STATUS),
    ("qa-failure-analyst", "triage verdicts", C.TRIAGE_VERDICTS),
    ("qa-failure-analyst", "flake mechanisms", C.FLAKY_MECHANISMS),
    ("qa-doc-scribe", "report sections", [s[len("## "):] for s in G.REPORT_SECTIONS]),
    ("qa-bug-reporter", "bug confirmations", C.BUG_CONFIRMATIONS),
    ("qa-bug-reporter", "bug sections", V.BUG_FORM_SECTIONS),
    ("qa-retro-analyst", "estimate ledger keys", V.ESTIMATION_LEDGER_REQUIRED),
]

# The three commands that turn a person's words into a passed gate. `guard_pre_tool` refuses
# every one of them to a role, so a card may only name them as somebody else's door.
HUMAN_WORD_COMMANDS = ("waiver.py --stage", "accept-gap", "review --record")

SCRIPT_RE = re.compile(r"`?([a-z][a-z0-9_]*\.py)")
ARTIFACT_PATH_RE = re.compile(r"(?:work|bugs|evidence)/[A-Za-z0-9_.*<>/-]+")


def cards() -> dict:
    data = json.loads((PLUGIN / "references" / "ahead-cards.json").read_text(encoding="utf-8"))
    return data.get("cards") or {}


def roles() -> list:
    model = json.loads((PLUGIN / "references" / "stages.json").read_text(encoding="utf-8"))
    out = []
    for stage in model.get("stages") or []:
        for role in (stage.get("roles") or ([stage["role"]] if stage.get("role") else [])):
            if role not in out:
                out.append(role)
    return out


def command_owners() -> dict:
    """{script name: set of roles allowed any of its write doors}, from role-commands.json."""
    data = json.loads((PLUGIN / "references" / "role-commands.json").read_text(encoding="utf-8"))
    owners: dict = {}
    for name, entry in (data.get("commands") or {}).items():
        script = name.split()[0]
        owners.setdefault(script, set()).update(entry.get("roles") or [])
    return owners


def door_owners(text: str, script: str) -> set:
    """The roles a card's mention of `script` is scoped to. A registry row is a script plus a door
    (`red_sandbox.py --diagnostic`); when the text names a door, only that door's row scopes it, and
    a door that has no row (the read-only `red_sandbox.py --probe`) is not scoped by another door's row."""
    data = json.loads((PLUGIN / "references" / "role-commands.json").read_text(encoding="utf-8"))
    rows = {name: set(entry.get("roles") or []) for name, entry in (data.get("commands") or {}).items()
            if name.split()[0] == script}
    named = [name for name in rows if " " in name and name in text]
    if named:
        return set().union(*(rows[name] for name in named))
    if any(" " in name for name in rows) and re.search(re.escape(script) + r"\s+--?[a-z]", text):
        return set()
    return command_owners().get(script) or set()


def code_reads(field: str) -> bool:
    """True when the code READS `field` of an `expectation_changes[]` row: `manifest_put.py`
    refuses a value of the wrong shape and names the field in its refusal. A name the code does
    not know is never named, so it is never refused, so it is not read."""
    base = {"function": "test_a.test_x", "red_attempt": "S5-r-1", "green_attempt": "S5-r-2",
            "then_refs": [{"case": "TC-1", "then": 1}], "what_changed": "a -> b", "reason": "why"}
    probe = dict(base)
    probe[field] = 12345          # no string, no list, no verdict: wrong for every field
    if field == "functions":
        probe.pop("function")
    problems = manifest_put.expectation_change_problems([probe], [base])
    return any(f"`{field}`" in p for p in problems)


def backticked_names(text: str) -> list:
    """The back-ticked bare identifiers of `text` (`then_refs`, not `s5_precheck.py --json`)."""
    return [t for t in re.findall(r"`([^`]+)`", text) if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", t)]


def sentences_naming(text: str, word: str) -> list:
    return [s for s in re.split(r"(?<=\.)\s+", text) if word in s]


def has_word(text: str, word: str) -> bool:
    """`word` as a whole identifier: `fitted_to_codes` does not contain `fitted_to_code`."""
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(word)}(?![A-Za-z0-9_])", text) is not None


def main() -> None:
    table = cards()
    everyone = roles()

    # --- FR-38: every role that hands an artifact to code is told the rules first ----------
    missing = [r for r in everyone if not str((table.get(r) or {}).get("text") or "").strip()]
    check("every role has a card of the rules code will apply to it", not missing, str(missing))
    extra = [r for r in table if r not in everyone]
    check("and no card names a role the stage model does not", not extra, str(extra))

    stage_model_text = (PLUGIN / "references" / "stages.json").read_text(encoding="utf-8")
    script_text = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                            for p in sorted(harness.SCRIPTS.glob("*.py")))
    for role in everyone:
        card = table[role]
        text = card["text"]
        size = len(text.encode("utf-8"))
        check(f"{role}: the card fits the budget ({size} B <= {CARD_MAX_BYTES})", size <= CARD_MAX_BYTES)
        check(f"{role}: the card names the checks it was read from", bool(card.get("sources")))
        for source in card.get("sources") or []:
            check(f"{role}: source {source} exists", (harness.SCRIPTS / source).is_file())
        for script in dict.fromkeys(SCRIPT_RE.findall(text)):
            check(f"{role}: the card names no script that does not exist ({script})",
                  (harness.SCRIPTS / script).is_file())
            allowed = door_owners(text, script)
            if allowed:
                check(f"{role}: {script} is a door this role may open",
                      role in allowed, f"role-commands.json scopes it to {sorted(allowed)}")
        for command in HUMAN_WORD_COMMANDS:
            if command in text:
                check(f"{role}: {command} is named as the orchestrator's, not the role's",
                      "orchestrator" in text)
        # FR-37: a path in text a role reads is the path the code writes. Every one of them
        # is spelled somewhere in the stage model or in a script — not by hand here.
        for path in dict.fromkeys(ARTIFACT_PATH_RE.findall(text)):
            check(f"{role}: the card spells {path} the way the code does",
                  path in stage_model_text or path in script_text)

    # --- the closed lists are the checker's own, not a snapshot of them -------------------
    for role, label, values in VOCABULARIES:
        text = table[role]["text"]
        absent = [v for v in sorted(values) if v not in text]
        check(f"{role}: the card carries every {label} the code knows", not absent,
              f"absent from the card: {absent}")

    # A quoted number is the code's number: FLAKY_MIN_RERUNS and the report's byte cap are
    # the two a card states outright.
    check_in("the analyst is told the real rerun threshold",
             f">= {C.FLAKY_MIN_RERUNS} isolated executions", table["qa-failure-analyst"]["text"])
    check_in("the scribe is told the real prose budget",
             f"{V.TEST_REPORT_MAX_BYTES:,} bytes", table["qa-doc-scribe"]["text"])

    # --- B-194: the expectation-change row is spelled the way the code reads it ------------
    # A text that names a field `s5_precheck.py` / `manifest_put.py` do not read tells the role to
    # write something nothing reads (FR-11, FR-38): the row is refused, or silently ignored.
    verdicts = handoff.allowed(manifest_put.VERDICTS_LIST)
    for field in ROW_FIELDS:
        check(f"the code reads the row field {field}", code_reads(field))
    finding = s5_precheck._record_fix(Path("QA-9"), {"function": "test_a.test_x",
                                                    "red_attempt": "S5-r-1", "green_attempt": "S5-r-2",
                                                    "cases": ["TC-1"]}, {})
    prefill = re.search(r"--fragment '(\{.*?\})'", finding)
    row = json.loads(prefill.group(1))[EXPECTATION_KEY][0] if prefill else {}
    check_eq("the finding of s5_precheck asks the author for exactly the fields the card lists",
             sorted(row), sorted(("function", *KEY_FIELDS, *AUTHOR_FIELDS)))

    auto, critic = table["qa-automator"]["text"], table["qa-code-critic"]["text"]
    known = {f for f in ROW_FIELDS if code_reads(f)} | {EXPECTATION_KEY, *NON_FIELD_TOKENS, *verdicts}
    for role, text, owed in (("qa-automator", auto, AUTHOR_FIELDS),
                             ("qa-code-critic", critic, (*CRITIC_FIELDS, *KEY_FIELDS))):
        check_in(f"{role}: the card names {EXPECTATION_KEY}", EXPECTATION_KEY, text)
        for field in owed:
            check(f"{role}: the card names the row field {field}", has_word(text, field))
        for sentence in sentences_naming(text, EXPECTATION_KEY):
            for name in backticked_names(sentence):
                check(f"{role}: `{name}`, named beside the row, is a name the code reads",
                      name in known)
    check_in("the automator is told the rule for a Then-fixed value: RED", "NEVER changed after a red run", auto)
    check("the automator card names the door the code offers: manifest_put.py",
          "manifest_put.py" in auto and "manifest_put.py" in critic)
    for verdict in verdicts:
        check(f"qa-code-critic: the card spells the verdict {verdict} whole", has_word(critic, verdict))
    check_in("the critic is told what fitted_to_code leads to", s5_precheck.CONTRADICTS, critic)
    names = [*ROW_FIELDS, *verdicts, EXPECTATION_KEY]
    for role, entry in table.items():
        near = sorted({tok for tok in re.findall(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+", entry["text"])
                       if tok not in names and difflib.get_close_matches(tok, names, n=1, cutoff=0.85)})
        check(f"{role}: no word of the card is a near-miss of a row field or a verdict", not near,
              f"misspelled: {near}")

    charter = (PLUGIN / "agents" / "qa-automator.md").read_text(encoding="utf-8")
    contract = (PLUGIN / "references" / "artifact-contract-automation.md").read_text(encoding="utf-8")
    rubric = (PLUGIN / "references" / "code-review-rubric.md").read_text(encoding="utf-8")
    check_in("the automator's charter names the row", EXPECTATION_KEY, charter)
    for field in AUTHOR_FIELDS:
        check(f"the automator's charter names the row field {field}", has_word(charter, field))
    check("the charter no longer calls a changed expected value 'never a self-fix' (B-194)",
          "never a self-fix" not in charter)
    check("the rubric no longer sends a changed expected value to triage",
          "belongs in triage" not in rubric)
    check_in("the rubric says the change is recorded in the row", f"{EXPECTATION_KEY}[]", rubric)
    for verdict in verdicts:
        check(f"the rubric spells the verdict {verdict} whole", has_word(rubric, verdict))
        check(f"the contract spells the verdict {verdict} whole", has_word(contract, verdict))
    for field in ROW_FIELDS:
        check(f"the contract documents the row field {field}", has_word(contract, field))
    check_in("an old manifest without the list is read, not refused (stories in flight)",
             "is read, not refused", contract)
    example = re.search(r"```json\s*(\{\"expectation_changes\".*?\})\s*```", contract, re.S)
    rows = json.loads(example.group(1)).get(EXPECTATION_KEY) if example else None
    check("the contract carries one example row", bool(rows))
    check("and manifest_put accepts it as written", bool(rows) and not
          manifest_put.expectation_change_problems(rows), str(manifest_put.expectation_change_problems(rows)))

    # --- brief_pack renders it, and the brief still fits -----------------------------------
    root = harness.temp_project("qa-ahead-cards-")
    try:
        harness.use_project(root)
        task = root / "qa-factory/artifacts/QA-9"
        (task / "work").mkdir(parents=True)
        (task / "pipeline.json").write_text(json.dumps(
            {"ticket": "QA-9", "size": "S", "environment": "local",
             "stages": {"S0": {"status": "done"}}, "gates": {}, "halts": []}), encoding="utf-8")
        stages = {s["id"]: s for s in json.loads(
            (PLUGIN / "references" / "stages.json").read_text(encoding="utf-8"))["stages"]}
        for stage_id, stage in stages.items():
            for role in stage.get("roles") or []:
                dispatch = f"{stage_id}-{role}-1"
                result = brief_pack.build("QA-9", stage_id, role, dispatch, write=False)
                check_in(f"{role}: the brief carries the rules ahead of the work",
                         "## The rules code will apply to your handoff", result["markdown"])
                check_in(f"{role}: and the card itself", table[role]["text"][:60], result["markdown"])
                check(f"{role}: the brief stays under 6 KB ({result['budget_bytes']} B)",
                      result["budget_bytes"] <= brief_pack.BRIEF_MAX_BYTES)
                # The card is the one thing brief_pack never drops, so the question is what
                # it cost: the same brief built without a card must list the same files.
                real = brief_pack.ahead_card
                brief_pack.ahead_card = lambda _role: ""
                try:
                    bare = brief_pack.build("QA-9", stage_id, role, dispatch, write=False)
                finally:
                    brief_pack.ahead_card = real
                check(f"{role}: and the card cost the role no path from its file list",
                      bare["files"] == result["files"],
                      f"without the card: {bare['files']}")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    harness.finish("test_ahead_cards")


if __name__ == "__main__":
    main()
