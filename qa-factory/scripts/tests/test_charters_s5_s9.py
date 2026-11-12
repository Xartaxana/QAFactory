#!/usr/bin/env python3
"""The charters of S5-S9 (spec t-1765 X7, nodes X7-1 / X7-3 / X7-4; merged by round X7-9, critic verdict t-1883 M-4): the seven roles
`qa-automator`, `qa-code-critic`, `qa-runner`, `qa-failure-analyst`, `qa-bug-reporter`, `qa-doc-scribe`, `qa-retro-analyst`. ONE table-driven file:
one CHARTERS list, one KEYS table, one ratchet pair (RATCHET_NUMBERS / RATCHET_AC), one regexp pair (the AC word case-insensitive), one
craft-share helper, one procedure-word test over all seven; the role-specific checks are the named tests at the end.

What each test kills (builder-rules 7a):
  test_charter_shape                      -> `charter_errors` weakened to return []; a marker or heading dropped from one charter
  test_craft_keys_stand_verbatim          -> a key phrase deleted from a charter (the negative control proves the helper fails)
  test_no_principle_numbers_or_ac         -> a bare `P19`, a decision number or `AC` written into a charter (K-C1, K-C4)
  test_no_procedure_words                 -> "must run" / "Step 1" written into any of the seven (K-C3)
  test_x1_numbers_only_shrink             -> a number or `AC` added to an X1 charter; the table only shrinks
  test_craft_share                        -> craft share under 0.40 of the charter's bytes
  test_the_control_fails_on_purpose       -> `key_problems` / `number_problems` that cannot report
  test_front_matter_is_verbatim           -> `tools` / `disallowedTools` / the stage of the description changed on S8 / S9 (FR-56)
  test_brief_rows_and_key_pages           -> a role dropped from brief-form.json or its handoff-keys page from inject-map.json
  test_runner_phrases_kept / test_analyst_phrases_kept -> a phrase the pin register keeps on the charter removed (t-1765-x7-pins.md R-keep)
  test_retro_reads_only_the_numbers       -> the journal or `state/cost` named in the retro charter again
  test_scribe_accepts_the_triage          -> the S7 acceptance duty (`stage_acceptance`) dropped from the scribe (t-1883 B-2)
  test_x8_explore_charter_tells_the_recorder_words -> a recorder word cut from references/explore-charter.md; the retired `ignored by rule` sentence back (X9)
  test_m1_form_tokens_stand_in_tools      -> a form token of the code critic or the failure analyst written back into Techniques (X9)
  test_s5_critic_form_has_not_looked      -> `not_looked` removed from handoffs/s5-critic-to-automator.yaml
Run: python -B -m pytest scripts/tests/test_charters_s5_s9.py -q
"""
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import charter  # noqa: E402
import handoff  # noqa: E402
import role_load  # noqa: E402

PLUGIN = Path(harness.SCRIPTS).parent
AGENTS = PLUGIN / "agents"

# --- the seven charters of S5-S9 and the five of S1-S4 (X1) -----------------------------------------------------------------------
CHARTERS = ["qa-automator", "qa-code-critic", "qa-runner", "qa-failure-analyst", "qa-bug-reporter", "qa-doc-scribe", "qa-retro-analyst"]
CHARTERS_X1 = ["qa-scout", "qa-requirements-tester", "qa-test-strategist", "qa-case-designer", "qa-case-critic"]
# P<n> / D-0<nnn> and `AC` found in the X1 charters on 04.11.2026; only down. RAISE (named, AR-20): qa-test-strategist 4 -> 5 - its charter
# now carries P1, P2, P3, P19, P26 (the ladder P19 and the manual-agent rule P26 came with the X5 / X8 craft text; round G5 names the raise).
RATCHET_NUMBERS = {"qa-scout": 0, "qa-requirements-tester": 0, "qa-test-strategist": 5, "qa-case-designer": 0, "qa-case-critic": 8}
RATCHET_AC = {"qa-scout": 0, "qa-requirements-tester": 1, "qa-test-strategist": 0, "qa-case-designer": 0, "qa-case-critic": 1}
SHARE_FLOOR = 0.40                                                    # craft bytes / charter bytes; the aim is 0.50

# The craft keys, verbatim: quoted from the DoD of the nodes before the texts were written (spec sections 2.1-2.7), and the recorder words of X8-4.
KEYS = {
    "qa-automator": ["can only pass", "through another route", "extend before you add", "the parameter id names", "never for time"],
    "qa-code-critic": ["beside its Then", "never beside the code", "could not verify", "a hint to read"],
    "qa-runner": ["one character at a time", "not only at a Then", "the goal of the check is yours", "nothing reported as checked",
                  "every `surprise:` line", "\"noise\" is not your word to give", "`look`, `watch`, `fill --whole`"],
    "qa-failure-analyst": ["what the red says", "without the change under test", "never against the application code", "a green one too",
                           "`#sur-<id>`", "`#sur-overflow`", "the surprise line itself",
                           "Find out the truth on the page", "In a triage, every suspicious place", "never a bug",
                           "the factory derived itself is no requirement"],
    "qa-bug-reporter": ["red test", "who loses what", "fewest steps"],
    "qa-doc-scribe": ["within these boundaries", "found, not run", "another machine", "accepted or returned", "`stage_acceptance`"],
    "qa-retro-analyst": ["Where did I not look", "Name a trap by its kind", "what its turns bought", "read as their next reader"],
}
EXPLORE_X8 = ("`look [<sel>]`", "`watch <sel> [<label>]`", "`fill --whole <sel> <text>`", "surprise: <id> step <n> (<word>) <kind>: <fact>",
              "\"surprise\": \"<id>\"", "`<case>#sur-<id>`", "`failed`")
# Front matter verbatim (FR-56): what the host reads as the role's tools. S8 / S9 roles (spec X7-4).
FRONT = {
    "qa-bug-reporter": ("Read, Grep, Glob, Write, Edit, Bash", "Agent, Task"),
    "qa-doc-scribe": ("Read, Grep, Glob, Bash, Write, Edit", "Agent, Task"),
    "qa-retro-analyst": ("Read, Grep, Glob, Bash, Write, Edit", "Agent, Task"),
}
# One regexp pair for every test below. The AC word is case-insensitive (it was case-sensitive in two of the three files this one replaced).
NUMBER_RE = re.compile(r"\b(P[0-9]{1,2}|D-0[0-9]{3})\b")
AC_RE = re.compile(r"\bAC\b|acceptance criteria", re.IGNORECASE)
# "Step 1" as a heading of a numbered procedure; a lowercase "before step 1" in a sentence is craft talk (the reporter's dirty-state bullet).
PROCEDURE_RE = re.compile(r"(?i:must run)|\bStep [0-9]")


def read(role: str) -> str:
    return (AGENTS / f"{role}.md").read_text(encoding="utf-8").replace("\r\n", "\n")


def flat(text: str) -> str:
    return " ".join(text.split())


def key_problems(text: str, keys: list) -> list:
    """One sentence per key that does not stand verbatim in the charter (whitespace-normalised: a wrapped line holds its key), naming the key."""
    body = flat(text)
    return [f"the craft key `{key}` is not in the charter; expected it verbatim" for key in keys if key not in body]


def number_problems(text: str) -> list:
    """One sentence per bare principle or decision number, and per `AC`, naming the hit (the package never ships PROJECT.md)."""
    out = [f"`{hit}` is a number of a document the package does not ship; write the idea, not the number" for hit in NUMBER_RE.findall(text)]
    out += [f"`{hit}` names a thing the factory does not use; write `requirement`" for hit in AC_RE.findall(text)]
    return out


def craft_share(text: str) -> float:
    craft, _ignored = role_load.craft_split(text)
    return craft / len(text.encode("utf-8"))


# --- the table-driven tests, over all seven -----------------------------------------------------------------------------------------
@pytest.mark.parametrize("role", CHARTERS)
def test_charter_shape(role):
    text = read(role)
    assert charter.is_charter(text)
    assert charter.charter_errors(text) == []
    assert charter.stray_markers(text) == []


@pytest.mark.parametrize("role", CHARTERS)
def test_craft_keys_stand_verbatim(role):
    assert key_problems(read(role), KEYS[role]) == []


@pytest.mark.parametrize("role", CHARTERS)
def test_no_principle_numbers_or_ac(role):
    assert number_problems(read(role)) == []


@pytest.mark.parametrize("role", CHARTERS)
def test_no_procedure_words(role):
    """K-C3: what code holds is not rewritten as a procedure."""
    assert not PROCEDURE_RE.search(read(role))


@pytest.mark.parametrize("role", CHARTERS_X1)
def test_x1_numbers_only_shrink(role):
    text = read(role)
    assert len(NUMBER_RE.findall(text)) <= RATCHET_NUMBERS[role], "a new principle or decision number in an X1 charter"
    assert len(AC_RE.findall(text)) <= RATCHET_AC[role], "a new `AC` in an X1 charter"


def test_the_ratchet_tables_cover_the_x1_charters():
    assert set(RATCHET_NUMBERS) == set(CHARTERS_X1) == set(RATCHET_AC)


@pytest.mark.parametrize("role", CHARTERS)
def test_craft_share(role, capsys):
    share = craft_share(read(role))
    with capsys.disabled():
        print(f"\n  craft share {role}: {share:.2f} (floor {SHARE_FLOOR:.2f}, aim 0.50)")
    assert share >= SHARE_FLOOR, f"{role}: craft is {share:.2f} of the charter, under {SHARE_FLOOR:.2f}; add craft (where bugs hide, techniques)"
    thin = "\n".join(line for line in read(role).split("\n") if not line.startswith("- "))
    assert craft_share(thin) < share                                     # the control: the bullets are what carry it


def test_the_control_fails_on_purpose():
    """The negative control of the helpers: a fixture without a key, and one with a bare number, are refused BY NAME."""
    text = read("qa-automator")
    assert key_problems(text, KEYS["qa-automator"]) == []
    cut = text.replace("can only pass", "cannot pass")
    assert key_problems(cut, KEYS["qa-automator"]) == ["the craft key `can only pass` is not in the charter; expected it verbatim"]
    assert key_problems("", ["x"]) != []                                # the check cannot pass on an empty text
    assert number_problems(text) == []
    dirty = number_problems(text + "\nThe ladder is P19 and D-0042 and an AC and an ac.\n")
    assert any("`P19`" in line for line in dirty) and any("`D-0042`" in line for line in dirty)
    assert sum("`AC`" in line or "`ac`" in line for line in dirty) == 2        # the AC word is case-insensitive
    assert PROCEDURE_RE.search(text + "\nStep 3: run it.\n") and not PROCEDURE_RE.search(text)
    assert craft_share("# x\n\n<!-- kind: process -->\n## Outcome\n\ntext\n") == 0.0


# --- role-specific tests ------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("role", list(FRONT))
def test_front_matter_is_verbatim(role):
    head = read(role).split("---")[1]
    fields = dict(line.split(": ", 1) for line in head.strip().split("\n"))
    tools, disallowed = FRONT[role]
    assert fields["name"] == role
    assert fields["tools"] == tools
    assert fields["disallowedTools"] == disallowed
    assert fields["description"].endswith(f"Dispatched by qa-story at {'S9' if role == 'qa-retro-analyst' else 'S8'}.")


def test_a_broken_marker_is_refused_by_name():
    good = read("qa-doc-scribe")
    broken = good.replace("<!-- kind: craft -->\n## Techniques", "<!-- kind: process -->\n## Techniques")
    assert any("Techniques` is craft, its marker says process" in e for e in charter.charter_errors(broken))
    assert craft_share(broken) < craft_share(good)


@pytest.mark.parametrize("role", ["qa-bug-reporter", "qa-doc-scribe", "qa-retro-analyst"])
def test_brief_rows_and_key_pages(role):
    form = json.loads((PLUGIN / "references" / "brief-form.json").read_text(encoding="utf-8"))
    imap = json.loads((PLUGIN / "references" / "inject-map.json").read_text(encoding="utf-8"))
    row = form["roles"][role]
    for key in ("non_goals", "questions"):
        assert row[key].strip() and len(row[key]) <= form["line_chars"]
    assert f"plugin:references/slices/{role}/handoff-keys.md" in imap["roles"][role]
    assert (PLUGIN / "references" / "slices" / role / "handoff-keys.md").exists()


def test_retro_reads_only_the_numbers():
    """The S9 input is retro-numbers.json (X7-6); the charter names neither the journal nor the cost files."""
    text = read("qa-retro-analyst")
    assert "work/retro-numbers.json" in text
    assert "state/cost" not in text and "journal" not in text
    assert "on every story: the retro is always the full one" in text


def test_scribe_accepts_the_triage():
    """t-1883 B-2: the scribe is the S7 acceptor (stages.json `acceptance_by`); its charter teaches the judgment, and the form carries the record."""
    text = flat(read("qa-doc-scribe"))
    assert "accepted or returned" in text and "`stage_acceptance`" in text and "with the quote that shows why" in text
    stages = json.loads((PLUGIN / "references" / "stages.json").read_text(encoding="utf-8"))
    assert "qa-doc-scribe" in json.dumps(stages)
    page = (PLUGIN / "references" / "slices" / "qa-doc-scribe" / "handoff-keys.md").read_text(encoding="utf-8")
    assert "stage_acceptance" in page


def test_runner_phrases_kept_in_the_charter():
    """The pins of the register that stay on the charter (spec t-1765-x7-pins.md section 1, R-keep): kept in the runner's craft or tools."""
    keys = ["You drive the UI as a user", "its screenshot only for a failed step", "the goal of the check is yours",
            "An obstacle the excerpt or the screenshot shows", "is cleared and the step is run again",
            "Record FAIL only when the product does not do what the case demands",
            "fails twice with nothing in its way on the screen is `inconclusive`, with the limitation named",
            "--as default", "the forms of `--as`", "never a global admin", "{generated_username}",
            'python "${CLAUDE_PLUGIN_ROOT}/scripts/manual_evidence.py" validate',
            "`work/evidence/manual/<case>/seed-steps.md`",
            "Capture the state before the action under test", "record an `unresolved_question` at once and go on"]
    assert key_problems(read("qa-runner"), keys) == []
    assert "a second failure is FAIL" not in flat(read("qa-runner"))     # the old retry rule stays gone
    assert "run.parallel" not in read("qa-runner")                        # no concurrent run is promised (was test_manual_window K3-7)


def test_analyst_phrases_kept_in_the_charter():
    keys = ["the same action without the change under test", "test data weaker than the case's Given is a `TEST_BUG` of the data",
            "`APP_BUG` when both readings are tenable, and only after the control experiment",
            "only when EVERY difference is outside the requirement", "no return to gate A and no rewrite of the case",
            "running the action again with the same change is a reproduction, not a control experiment",
            "bug_records.py", "bug_snapshot.py", "distinct_defect", "never fetch or infer history just for metrics",
            "never a second full coverage review", "`detail` (optional: a row without it is not refused)", "No oracle, no draft",
            "bug_records.py open-bugs", "`evidence: \"code-reading\"`", "the test in the repository is never changed"]
    assert key_problems(read("qa-failure-analyst"), keys) == []


def test_x8_explore_charter_tells_the_recorder_words():
    """X8-4: look, watch, fill --whole, the surprise line and its citation are in the exploration charter; a word cut makes it red."""
    text = (PLUGIN / "references" / "explore-charter.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert [w for w in EXPLORE_X8 if w not in text] == []
    assert [w for w in EXPLORE_X8 if w not in text.replace("`look [<sel>]`", "")] == ["`look [<sel>]`"], "the check can fail"
    assert "ignored by rule" not in text                                  # X9: the retired sentence stays out (negative pin)


# X9 item 1 (M-1 moved): a form key, field, verdict word or file name belongs to `## Tools` (process), the experience to `## Techniques` (craft).
M1_TOKENS = {
    "qa-code-critic": ["`contradicts_requirement`", "--judge", "`sensitivity_proof_missing_reason`", "`cause: test_defect`",
                       "`critic-findings.md`", "`introduced_helpers[]`", "`for_the_reviewer`"],
    "qa-failure-analyst": ["`TEST_BUG`", "`evidence/`", "field_absent", "shape_ref", "`{path, line, quote}`", "`evidence: \"code-reading\"`",
                           "SETTLED", "`code_says: contradicts`"],
}


def m1_problems(role: str, text: str) -> list:
    """One sentence per token that is in the Techniques slice or is missing from the Tools slice, naming the token."""
    techniques = text.split("## Techniques", 1)[1].split("## Tools", 1)[0]
    tools = text.split("## Tools", 1)[1].split("## When to ask", 1)[0]
    out = [f"{role}: {t} stands in Techniques; it is a form token, move it to Tools" for t in M1_TOKENS[role] if t in techniques]
    return out + [f"{role}: {t} is not in Tools" for t in M1_TOKENS[role] if t not in tools]


@pytest.mark.parametrize("role", sorted(M1_TOKENS))
def test_m1_form_tokens_stand_in_tools(role):
    text = read(role)
    assert m1_problems(role, text) == []
    # negative control: the same text with one token written back into Techniques is refused BY NAME
    token = M1_TOKENS[role][0]
    back = text.replace("## Tools", f"- back {token}\n\n<!-- kind: process -->\n## Tools", 1)
    assert m1_problems(role, back) == [f"{role}: {token} stands in Techniques; it is a form token, move it to Tools"]


# --- t-2064 P7: the automator's non-stopping rule. Its sentences are the register rows `automator-non-stopping-form` and
# `automator-soft-only-when-independent` (design/role-rules.json); what stays here is a computation: no language named in the rule.
LANGUAGE_WORDS = ("typescript", "javascript", "python", "pytest", "playwright", "java", "c#", "kotlin", "ruby", "jest", "junit", "nunit",
                  "expect.soft", "softassert", "assertall", "assert.multiple", "pytest-check")


def soft_rule_sentences(text: str) -> list:
    """Every line of the text that speaks of the non-stopping form."""
    return [ln for ln in text.splitlines() if "non-stopping" in ln]


def test_no_language_named_in_soft_rule():
    for role in ("qa-automator", "qa-code-critic"):
        lines = soft_rule_sentences(read(role))
        assert lines or role == "qa-code-critic", f"{role} says nothing about the non-stopping form"   # the critic's text: held back (report)
        for ln in lines:
            assert [w for w in LANGUAGE_WORDS if w in ln.lower()] == [], f"{role}: {ln}"
    # negative control: the same check reports a language written into the rule
    assert [w for w in LANGUAGE_WORDS if w in "use expect.soft where it has one non-stopping".lower()] == ["expect.soft"]


def test_code_critic_charter_names_cause_key():
    """F4 (t-1936 N2): the charter tells the key path the route reads and the send-back rule, in Tools (process); the row keys are the form's own `# Fill:` line (t-1945 B1)."""
    text = read("qa-code-critic")
    tools = text.split("## Tools", 1)[1].split("## When to ask", 1)[0]
    for key in ("`findings[N].cause`", "`findings[N]` row of your form", "`concerns`", "`review`"):
        assert key in tools, key
    assert "`cause: data_row`" not in text            # the probe's word, not a finding cause (it stood in the list's way)


def test_code_critic_charter_cause_list_equals_vocabulary():
    """F4: the cause list written in the static charter equals `handoff.allowed("repair_causes")` (a word added to one only is red)."""
    text = read("qa-code-critic")
    listed = re.search(r"`cause` is one of ((?:`[a-z_]+`(?: \| )?)+)", text)
    assert listed, "the charter names no closed cause list"
    words = re.findall(r"`([a-z_]+)`", listed.group(1))
    assert sorted(words) == sorted(handoff.allowed("repair_causes"))
    # negative control: a list missing one word is caught
    assert sorted(words[:-1]) != sorted(handoff.allowed("repair_causes"))


def test_s5_critic_form_has_not_looked():
    spec = handoff.spec_of(handoff.template("s5-critic-to-automator"))
    for path in ("not_looked[].where", "not_looked[].why"):
        assert path in spec and not spec[path].optional, f"{path} is required in handoffs/s5-critic-to-automator.yaml"
    other = handoff.spec_of(handoff.template("s5-automator-to-critic"))       # negative control: a form that has no such list
    assert "not_looked[].where" not in other
    page = (PLUGIN / "references" / "slices" / "qa-code-critic" / "handoff-keys.md").read_text(encoding="utf-8")
    assert "`not_looked[].where` (required)" in page


if __name__ == "__main__": raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
