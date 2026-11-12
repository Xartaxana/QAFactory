#!/usr/bin/env python3
"""Text the factory puts in front of a person — `references/human-questions.md`, by code.

The rules were written after two measured failures and then lived as prose, so the next
boundary broke them again. What is proved here:

  * `human_text.problems` catches every shape the rules file forbids, and leaves a text that
    obeys them alone — including the one question from TP1-13797 run 5 that the person was
    actually shown ("The conductor needs your word." plus seven detector lines);
  * the `how to answer` block is exempt, because there a command is what to type (rule 5);
  * EVERY kind of question the driver can raise obeys the rules: `conductor`, `refusal`,
    `retro`, and the one the driver builds itself when nobody wrote a question;
  * the driver never pastes a refusal in place of a question: the factory's own words go to
    `state/driver-question-details.md`, named in the answer block;
  * every question is journalled with the rules it broke, so the share is a number the next
    run can read (run 5: 16 of 76 conductor sessions answered `ask_person` with an empty
    question, and the family that produced cost $9.01 over 21 sessions).
"""
import contextlib
import io
import json
import os
import re
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import human_text  # noqa: E402
import story_run  # noqa: E402

# What the person saw at S3 on 26.09, reconstructed from state/conductor.jsonl: the conductor
# answered `ask_person` with an empty question and the driver pasted the refusal under its own
# filler sentence.
RUN5 = """The conductor needs your word.

Refusal:
exit gate for S3-qa-test-strategist-1 (qa-test-strategist, S3): planning_contract.py: REAL exit 1
on the gate re-run (FB-27): - TS-14: low depth requires evidenced bounded, reversible effect
| handover form S3-qa-test-strategist-1.yaml - header.verdict: not filled
A person's word passes any of these: `waiver.py --task <TICKET> --stage S3 --block "<line>"`.

---
Answer: write your words to a file and run
  python story_run.py --task TP1-13797 --answer <file>
"""


# `take_answer` on a conductor question ends in a conductor session, i.e. `claude -p`. This test
# once fell through to whatever `claude` lay on PATH and started a real, paid session on every
# run. The stub below is story_run_common's conductor stub cut to what this test needs: it logs the
# call and answers with a valid conductor verdict (`continue`), so the round trip still runs.
import story_run_common as T  # noqa: E402

STUB = T.RECEIPT + r'''
import json, os, sys
from pathlib import Path
# The driver writes the prompt as UTF-8 bytes; `sys.stdin.read()` would decode them with the machine's
# locale (cp1252 on a Windows shell without PYTHONUTF8) - decoded explicitly, as story_run_common's stub does.
prompt = sys.stdin.buffer.read().decode("utf-8")
with Path(os.environ["STUB_LOG"]).open("a", encoding="utf-8") as handle:
    handle.write(json.dumps({"argv": sys.argv[1:], "prompt": prompt}) + "\n")
verdict = {"action": "continue", "did": "stub", "question": ""}
write_receipt("sess-stub")
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "session_id": "sess-stub",
                  "num_turns": 1, "total_cost_usd": 0.0, "duration_ms": 1,
                  "result": "I looked.\n" + json.dumps(verdict)}))
'''


def seed(task: str) -> tuple:
    root = harness.temp_project("qa-human-questions-")
    harness.use_project(root)
    task_root = root / "qa-factory/artifacts" / task
    (task_root / "work").mkdir(parents=True)
    (task_root / "pipeline.json").write_text(json.dumps(
        {"ticket": task, "size": "S", "environment": "local",
         "stages": {"S0": {"status": "done"}, "S1": {"status": "done"}, "S2": {"status": "done"},
                    "S3": {"status": "running"}}, "gates": {}, "halts": []}), encoding="utf-8")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    return root, task_root, env


def driver_for(root: Path, task: str):
    ns = types.SimpleNamespace(task=task, answer=None, until="end", dry_run=False, model="sonnet",
                               plugin_dir=None, project=str(root), mr=None, branch=None, commit=None,
                               ungrounded=False, ticket_file=None, env=None, branch_suffix="",
                               max_boundaries=10)
    return story_run.Driver(ns)


# --- C1-2 (conductor/1, P22): the sixth element, its worked example and its size -------------------------------------
# The sentence of the spec, VERBATIM (t-630 section 4), quoted here before the run and never derived from the file it checks.
ITEM_6 = ("6. **Price and consequences, per option.** Every option of the closed set is followed by three lines: `the factory:` "
          "what it costs the factory (nothing runs / a record only / a factory command runs, no agent works / one more "
          "working session of the role, named in words / the stages, named in words, run again); `you:` what it costs the person (nothing more / this answer / work of theirs "
          "outside the factory, named; checks left with them); `the story:` what stays unverified, in the story's words, what "
          "goes into the report as an open item, and what it does to delivery, said as one of: ready, not ready, ready after "
          "your checks, waits, unchanged, not known. A cost nobody measured is said as a class, never as a number; an unknown is said as "
          "not known. A question has at least two options and no two options make the same move; one possible move is not a "
          "question but a report.")
RULES = harness.PLUGIN_ROOT / "references" / "human-questions.md"
LABELS = ("the factory:", "you:", "the story:")
HQ_CAP = 12000


def has_item_6(text: str) -> bool:
    section = text.split("## What the text must carry", 1)[1].split("## What the text may never carry", 1)[0]
    return ITEM_6 in section.splitlines()


def example_problems(text: str, heading: str = "One with price and consequences") -> list:
    """What is wrong with the worked example under `## <heading>` ('One with price and consequences', or 'One at a gate'): the section
    is there, the shape rules over its body, two options at least, each followed by exactly the three labels in order, distinct
    tokens, and the rule names the delivery word."""
    if f"## {heading}\n" not in text:
        return [f"the section `## {heading}` is missing"]
    section = text.split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]
    quoted = [line[2:] for line in section.splitlines() if line.startswith("> ")]
    out = [f"shape: {p['rule']}" for p in human_text.shape_problems("\n".join(quoted))]
    tokens = []
    for index, line in enumerate(quoted):
        head = re.match(r"\(([a-z])\) `([^`]+)`", line)
        if not head:
            continue
        tokens.append(head.group(2))
        following = quoted[index + 1:index + 4]
        if [next((label for label in LABELS if row.startswith(label)), "") for row in following] != list(LABELS):
            out.append(f"option {head.group(1)}: not followed by exactly the three labels in order")
        after = quoted[index + 4] if index + 4 < len(quoted) else ""
        if after and not re.match(r"\([a-z]\) `", after):
            out.append(f"option {head.group(1)}: more than three lines follow it")
    if len(tokens) < 2:
        out.append("fewer than two options")
    if len(set(tokens)) != len(tokens):
        out.append("two options carry the same token")
    if "ready after your checks" not in text.split("## What the text must carry", 1)[1].split("## What the text may never carry", 1)[0]:
        out.append("the rule does not name `ready after your checks`")
    return out


def the_sixth_element_and_its_example() -> None:
    text = RULES.read_text(encoding="utf-8")
    check("HQ6: the sixth element stands verbatim under 'What the text must carry'", has_item_6(text))
    check_eq("HQ6-ex: the worked example is clean (shape rules, options, labels, tokens, the delivery word)",
             example_problems(text), [])
    check(f"HQ-size: human-questions.md is {len(RULES.read_bytes())} bytes, within {HQ_CAP}", len(RULES.read_bytes()) <= HQ_CAP)


OLD_GATE_SENTENCE = "A gate-B question with a rework option appears after C1-4, which gives that option its executor."


def the_example_at_a_gate() -> None:
    """HQ6-gate (C1-4b, t-692 / critic t-693 F3): `## One at a gate` is the worked example of a gate answer that was not the approval word -
    a closed question whose options (`rework`, `approve`, `retry`) each carry the three price lines, in the shape the rules demand."""
    text = RULES.read_text(encoding="utf-8")
    check_eq("HQ6-gate: the section is there and clean (shape rules, two or more options, three labels each, distinct tokens)",
             example_problems(text, "One at a gate"), [])
    section = (text.split("## One at a gate\n", 1) + [""])[1].split("\n## ", 1)[0]      # a missing section is red below, not a traceback
    tokens = re.findall(r"^> \([a-z]\) `([^`]+)`", section, flags=re.M)
    check_eq("HQ6-gate: the options are the gate's three moves, each once", tokens, ["rework", "approve", "retry"])
    check_eq("HQ6-gate: three price lines for each of them", [len(re.findall(r"^> (?:the factory|you|the story):", section, flags=re.M)), len(tokens)], [9, 3])
    check_not_in("HQ6-gate: the sentence that promised the section is gone", OLD_GATE_SENTENCE, text)


def main() -> None:
    the_sixth_element_and_its_example()
    the_example_at_a_gate()
    task = "QA-9"

    # --- the checker ------------------------------------------------------------------------
    broken = {p["rule"] for p in human_text.problems(RUN5)}
    for rule in ("filler", "relayed_refusal", "script_name", "exit_code", "form_field", "refusal_id"):
        check(f"the question run 5 actually showed breaks `{rule}`", rule in broken, str(sorted(broken)))
    check_eq("a text that obeys the rules is left alone", human_text.problems(human_text.CLEAN), [])
    body, how = human_text.split(human_text.CLEAN)
    check_in("the command lives in the `how to answer` block", "story_run.py", how)
    check_not_in("and nowhere else", "story_run.py", body)
    check("a text with no answer block at all is a finding",
          "no_how_to_answer" in {p["rule"] for p in human_text.problems("x " * 200)})
    check("and so is a one-line stand-in",
          "too_short" in {p["rule"] for p in human_text.problems("Your word?\n\n---\nAnswer: x")})

    # --- B-009: the shapes TP1-13877 showed a person, and the boundaries of the new rows ---
    tail = "\n\n---\nAnswer: write your words to a file and run\n  python story_run.py --task QA-9 --answer <file>\n"
    pad = "The plan is written and one row waits for a decision that only you can make here. "

    def rules_of(text: str, kind: str = "question") -> set:
        return {p["rule"] for p in human_text.problems(text, kind=kind)}

    check("a login error line with /login breaks slash_command",
          "slash_command" in rules_of(pad + "The tool answered: Not logged in - Please run /login" + tail))
    check("a URL that merely ends in /login is not a slash command",
          "slash_command" not in rules_of(pad + "See https://host.example/login for the page." + tail))
    # t-363 B3 (B-256 g): a configuration key path and a plugin command are an INSTRUCTION - they stand in the
    # answer block, never in the body. The rows are DATA (references/human-text.json), checked with a positive and a
    # negative sample each, and at the boundary of the key shape (two names are a file name, three are a key path).
    key = "adapters.ticket.direct_api.base_url"
    check("a key path in the body breaks config_key",
          "config_key" in rules_of(pad + f"The tracker's setting {key} is not recorded." + tail))
    check("negative: the same key path in the answer block is the instruction to type, not jargon",
          "config_key" not in rules_of(pad + "The setting named below is not recorded."
                                       + f"\n\n---\nAnswer: write your words to a file and run\n  python story_run.py\n\nThe setting: {key}\n"))
    check("a plugin command in the body breaks plugin_command",
          "plugin_command" in rules_of(pad + "Run /qa-factory:qa-onboarding to record it." + tail))
    check("negative: the same command in the answer block does not",
          "plugin_command" not in rules_of(pad + "Record it with the onboarding step."
                                           + "\n\n---\nAnswer: write your words to a file and run\n  /qa-factory:qa-onboarding\n"))
    # The Lead's correction (t-363, test_gate_preflight R8): only a key of OUR configuration counts - a dotted path of three
    # or more names whose FIRST name is a root of references/config-keys.json. An image label the stand reports is a fact
    # about the person's world (`oci_label.no_label` quotes `org.opencontainers.image.revision`), not our jargon.
    check("boundary AT the shape: three names joined by dots whose first name is a root of the configuration (`adapters.ticket.x`)",
          "config_key" in rules_of(pad + "The setting adapters.ticket.x is missing." + tail))
    check("a dotted profile key is ours (`profiles.api.commands`: the first name `profiles` is a root)",
          "config_key" in rules_of(pad + "Change profiles.api.commands for it." + tail))
    check("a bracketed profile key in the BODY is ours (`profiles[api].commands.one_test`, the shape of B-220), bare or behind `config.json:`",
          "config_key" in rules_of(pad + "Change `profiles[api].commands.one_test` for it." + tail)
          and "config_key" in rules_of(pad + "Change qa-factory/config.json:profiles[api].commands.one_test for it." + tail))
    # t-373 F9 (the Lead's decision): a card's ACTION slots - the lines gate_preflight renders as `where:` / `the fix:` - are the
    # card's own how-to-answer slot: the person must see where their setting lives to act on it. The rule is for the BODY.
    check("F9: the card's `the fix:` line names the setting and is exempt (the gate B packet stays clean)",
          "config_key" not in rules_of(pad + "Stand gap: TC-001\n  the fix:  qa-factory/config.json:profiles[api].commands.one_test -> "
                                       "the runner passes the report option itself" + tail))
    check("F9: `where:` is exempt too", "config_key" not in rules_of(pad + "\n  where:  qa-factory/config.json:profiles[api].commands.one_test" + tail))
    check("F9 (negative control): the same line under another prefix is the body and fires",
          "config_key" in rules_of(pad + "  note:  qa-factory/config.json:profiles[api].commands.one_test -> the runner" + tail))
    check("F9: only the action LINE is exempt - the rest of the card is checked: a key in the next line fires",
          "config_key" in rules_of(pad + "  the fix:  change the runner\n  missing:  environment.access is empty" + tail))
    check("NEGATIVE: an OCI image label (`org.opencontainers.image.revision`) is not a key of ours - the person must see it",
          "config_key" not in rules_of(pad + "The image does not carry the label org.opencontainers.image.revision at all." + tail))
    # t-373 F8: two names fire when the first is a root (`environment.access`, `driver.child_env.keep`: `driver` is a root
    # now); a last name that is a file extension or a top-level domain is a file or a host, never a key
    check("F8: a two-name key that the table LISTS whole fires (`environment.access`)",
          "config_key" in rules_of(pad + "The setting environment.access is missing." + tail))
    check("F8 negative: two names that are a root and a word, not listed, are not a key (`external_writes.bugs`, as the gate B brief's "
          "Filing line writes it)",
          "config_key" not in rules_of(pad + "bugs stay in this repository (`external_writes.bugs: markdown`); nothing is sent." + tail))
    check("F8: `driver.child_env.keep` fires (the `driver` root is in config-keys.json)",
          "config_key" in rules_of(pad + "Set driver.child_env.keep to the variable names." + tail))
    for label, line in (("a host under a root name (`run.example.com`)", "The tracker answers at run.example.com today."),
                        ("a host under another root name (`telemetry.example.org`)", "Sent to telemetry.example.org just now."),
                        ("a file with a root's name and an extension (`environment.prod.yaml`)", "Open environment.prod.yaml and look."),
                        ("a two-name file (`cost.json`)", "The figures are in cost.json today.")):
        check(f"F8 negative: {label} is not a key", "config_key" not in rules_of(pad + line + tail), label)
    for label, line in (("three names whose first is no root (`a.b.c`)", "The setting a.b.c is missing."),
                        ("a Python module path", "The import story_run.driver.run failed."),
                        ("two names are a file name (`config.json`)", "Open qa-factory/config.json and look."),
                        ("a file path with dots in its folder", "See work/ticket.view.v2.md today."),
                        ("a version number", "The factory is at version 0.7.24 now."),
                        ("an abbreviation", "Some tools, e.g. the linter, are slower."),
                        ("a URL's host", "See https://jira.example.test/browse for the page."),
                        ("a bare host name of three parts", "The tracker answers at jira.example.test today.")):
        check(f"negative: {label} is not a key path", "config_key" not in rules_of(pad + line + tail), label)
    block = human_text.rules().get("action_lines") or {}
    check("the action-line prefixes, the rows a backquoted command is exempt from and the file extensions / domains are DATA in the rules file "
          "(FR-13): ONE `action_lines` block at the top (B-220 F3), the row carries no list of its own",
          block.get("prefixes") == ["I propose to run", "the fix:", "where:", "To add a stand:"]
          and block.get("command_span_rows") == ["flag", "script_name", "config_key", "plugin_command"]
          and block.get("whole_line") == {"config_key": ["the fix:", "where:"]}
          and all(not r.get("exempt_line_prefixes") and "yaml" in r.get("skip_last_names", []) for r in human_text.rules()["forbidden"]
                  if r["id"] == "config_key"))
    # B-220 KO5 / F3 (the owner's ruling of 03.10, narrowed by the Lead after t-389): the sentence that offers a changed test command
    # carries its flag - "I propose to run it as: `<command with flag>`. Do it?" - and ONLY the backquoted command on an action line is
    # exempt, ONLY for the flag / script name / config key / plugin command rows.
    propose = 'I propose to run the web tests as: `dotnet test --logger "trx;LogFileName={report_path}" --reporters junit`. Do it? yes / no'
    check_eq("KO5: the offer, flag and all, is a text that obeys the rules (the sentence on its own line, an answer block under it)",
             human_text.problems(pad + "\n\n" + propose + tail), [])
    check("KO5 (negative control): the same flag on a body line without the exempt prefix is still caught",
          "flag" in rules_of(pad + "The runner could use --reporters junit here." + tail))
    check("KO5: only the offer's LINE is exempt - the next line is the body and a flag in it fires",
          "flag" in rules_of(pad + "\n\n" + propose + "\nAlso pass --reporters junit yourself." + tail))
    check("KO5: a prefix is a prefix of the LINE: the words inside a longer sentence do not exempt it",
          "flag" in rules_of(pad + "Maybe I propose to run it with --reporters junit, said the tool." + tail))
    # F3: what IS legal on an action line - the command, in backquotes - for the four rows; and each one's negative twin
    for label, command, rule in (("a script name", "python manage.py test", "script_name"),
                                 ("a flag", "dotnet test --reporters junit", "flag"),
                                 ("a plugin command", "/qa-factory:qa-onboarding", "plugin_command"),
                                 ("a config key", "profiles[api].commands.one_test", "config_key")):
        for prefix in ("the fix:", "I propose to run it as:", "To add a stand:"):
            check(f"F3: {label} inside backquotes on a `{prefix}` line is legal",
                  rule not in rules_of(pad + f"\n  {prefix}  run `{command}` now" + tail), command)
        check(f"F3 (negative twin): {label} OUTSIDE backquotes on an action line fires `{rule}`",
              rule in rules_of(pad + f"\n  I propose to run it as:  {command} now" + tail), command)
        check(f"F3 (negative twin): {label} inside backquotes on a line under another prefix fires `{rule}`",
              rule in rules_of(pad + f"\n  note:  run `{command}` now" + tail), command)
    # what is NOT legal on an action line, quoted or not: an exit code, a form field (the pins that made them legal are dropped)
    story = "the fix: run `story_run.py --resume` and look at exit code 2"
    check_eq("F3 (the critic's line): the command is legal, the exit code is reported - and nothing else",
             [p["rule"] for p in human_text.problems(pad + "\n" + story + tail)], ["exit_code"])
    check("F3 (negative twin): the same line as a body line reports the script, the flag and the exit code",
          {"script_name", "flag", "exit_code"} <= rules_of(pad + "\nnote: run `story_run.py --resume` and look at exit code 2" + tail))
    check("F3: an exit code inside backquotes on an action line is still caught", "exit_code" in rules_of(pad + "\nthe fix: run `tool --x` (`exit 1`)" + tail))
    check("F3: a form field on an action line is caught, quoted or not",
          "form_field" in rules_of(pad + "\nwhere:  header.verdict is not filled" + tail)
          and "form_field" in rules_of(pad + "\nthe fix: set `header.verdict` first" + tail))
    check("F3: a plugin command written bare on a `the fix:` line is caught (the old pin that made it legal is dropped)",
          "plugin_command" in rules_of(pad + "\n  the fix:  /qa-factory:qa-onboarding" + tail))
    check("F3 (t-373, kept): a card's `the fix:` / `where:` line is still the config-key slot, written without quotes",
          "config_key" not in rules_of(pad + "\n  where:  qa-factory/config.json:profiles[api].commands.one_test" + tail))
    # FR-13: the roots are the data of references/config-keys.json - a root added there is found with no change in code
    import hooklib
    spec = human_text.rules()           # read BEFORE the table is replaced: the rules file is read through the same loader
    real_load = hooklib.load_ref_json

    def broken_in(sample: str) -> set:
        return {p["rule"] for p in human_text.problems(sample, spec)}

    hooklib.load_ref_json = lambda name: {"keys": {"zzz": {}, "adapters.ticket.attachments": {}}} if name == "config-keys.json" else real_load(name)
    try:
        check("FR-13: a root added to the table is a key path with no code change; a root removed from it is not",
              "config_key" in broken_in(pad + "The setting zzz.alpha.beta is missing." + tail)
              and "config_key" not in broken_in(pad + "The setting judge.provider.name is missing." + tail))
    finally:
        hooklib.load_ref_json = real_load
    hooklib.load_ref_json = lambda name: {}
    try:
        check("edge: a table that cannot be read is no root: the row finds nothing and never raises",
              "config_key" not in broken_in(pad + f"The setting {key} is missing." + tail))
    finally:
        hooklib.load_ref_json = real_load
    check("control: the same sentence is caught again once the table is back", "config_key" in rules_of(pad + f"The setting {key} is missing." + tail))
    check("negative: a slash that is part of a path is not a plugin command",
          "plugin_command" not in rules_of(pad + "See docs/qa-factory:notes for it." + tail))
    check("both rows are for a question, not for a report section (a report names its keys in its own rules)",
          not rules_of("The tracker's setting adapters.ticket.direct_api.base_url and /qa-factory:qa-onboarding.", kind="report")
          & {"config_key", "plugin_command"})
    check("FR-13: both rows are DATA in the rules file",
          [r["id"] for r in human_text.rules()["forbidden"] if r["id"] in ("config_key", "plugin_command")]
          == ["config_key", "plugin_command"])
    check("a Cloudflare HTML page breaks relayed_markup",
          "relayed_markup" in rules_of(pad + "<!DOCTYPE html><html><head><title>Just a moment...</title>"
                                       "</head><body>cf-ray</body></html>" + tail))
    check("a traceback breaks relayed_traceback",
          "relayed_traceback" in rules_of(pad + "Traceback (most recent call last):\n  File x" + tail))
    check("a halt text led by a dispatch id breaks dispatch_id",
          "dispatch_id" in rules_of("S3-qa-test-strategist-1 stopped: it cannot go on." + tail))
    check("boundary: `S3-qa-x-1` is a dispatch id", "dispatch_id" in rules_of(pad + "S3-qa-x-1 failed." + tail))
    check("boundary: `S3-qa-x` (no launch number) is not",
          "dispatch_id" not in rules_of(pad + "S3-qa-x failed." + tail))
    check("boundary: a longer word does not hide a dispatch id inside it",
          "dispatch_id" not in rules_of(pad + "XS3-qa-x-1 failed." + tail))
    check("boundary: `TS-14 (the import size limit)` passes explained_ids",
          "explained_ids" not in rules_of(pad + "Row TS-14 (the import size limit) waits." + tail))
    check("boundary: `TS-14 says` fails explained_ids",
          "explained_ids" in rules_of(pad + "Row TS-14 says the limit is unknown." + tail))
    check("an id followed by a dash or a colon is explained",
          not {"explained_ids"} & (rules_of(pad + "TS-14 — the size limit; OBL-2: the retry rule." + tail)))
    check("`OBL-7 is open` is caught", "explained_ids" in rules_of(pad + "OBL-7 is open." + tail))
    check("only the FIRST mention of an id needs its explanation",
          "explained_ids" not in rules_of(pad + "TS-14 (the size limit) waits. Then TS-14 fails." + tail))
    check("a first mention without one is caught even when a later one has it",
          "explained_ids" in rules_of(pad + "TS-14 waits. Later TS-14 (the size limit) again." + tail))
    # B-009 part 2 (critic t-039 F3, the Lead's decision): a case id whose file is linked on the same
    # line is explained by the file; every other id keeps the rule.
    for label, line in (("a markdown link", "[TC-014](work/test-cases/x/TC-014.md) waits."),
                        ("a link on a code-quoted id", "[`TC-1`](work/test-cases/TC-1.md) waits."),
                        ("a link with a snapshot path", "[TC-014](state/case-versions/TC-014/cv_1.md) waits."),
                        ("a link on a bold id", "[**TC-014**](work/x/TC-014.md) waits."),
                        ("the id beside its file's path", "TC-014 waits in work/test-cases/x/TC-014.md today."),
                        ("a path with a suffix after the id", "See work/test-cases/x/TC-014-login.md for TC-014 waits.")):
        check(f"a TC id with its case file on the line is explained: {label}",
              "explained_ids" not in rules_of(pad + line + tail))
    for label, line in (("a link to another case's file", "[TC-1](work/test-cases/TC-2.md) waits."),
                        ("a link to a URL", "[TC-1](https://example.com/x) waits."),
                        ("a link to an anchor", "[TC-1](#tc-1) waits."),
                        ("a link to a longer id's file", "[TC-1](work/test-cases/TC-10.md) waits."),
                        ("a link written inside a code span", "`[TC-1](work/test-cases/TC-1.md)` waits."),
                        ("no link at all", "TC-014 waits."),
                        ("the same id elsewhere without a link comes first",
                         "TC-014 waits.\n[TC-014](work/x/TC-014.md) waits."),
                        ("a link two lines away", "[TC-013](work/x/TC-013.md) waits.\nTC-014 waits."),
                        ("another case's link", "[TC-013](work/x/TC-013.md) and TC-014 wait."),
                        ("a link to another file", "TC-014 waits, see [the plan](work/test-plan.md)."),
                        ("a longer id's file", "TC-014 waits in work/x/TC-0140.md today."),
                        ("a link in the other id families", "TS-14 waits, see [TS-14](work/x/TS-14.md)."),
                        ("the link's path is not a link", "TC-014 waits (work/x/TC-014.txt).")):
        check(f"no explanation without the link on THIS line: {label}",
              "explained_ids" in rules_of(pad + line + tail), label)
    check("a bare id before a link in a list is not an apposition: `TC-014, [TC-015](..)` flags TC-014",
          "TC-014" in human_text._unexplained(next(r for r in human_text.rules()["forbidden"]
                                                   if r.get("kind") == "explained_ids"),
                                              pad + "See TC-014, [TC-015](a/TC-015.md) today"))
    check_eq("the link exemption reports only the id that has none",
             human_text._unexplained(next(r for r in human_text.rules()["forbidden"] if r.get("kind") == "explained_ids"),
                                     pad + "[TC-013](a/TC-013.md), TC-014, SURF-2 (the widget)"),
             ["TC-014"])
    check("an id inside a longer token is not an id (a project's own case id form)",
          "explained_ids" not in rules_of(pad + "The case TP1-13877_TC_001 passed." + tail))
    check("the answer block may carry ids and commands",
          not rules_of(pad + "Nothing else." + tail.replace("<file>", "<file> for OBL-7 S3-qa-x-1 /login")))

    head = ("# Driver question — QA-9\nkind: halt\nstage: S3\ndispatch: S3-qa-test-strategist-1\n"
            "asked_at: 2026-09-29T10:00:00+00:00\n\n")
    check_eq("the question head (its dispatch id) is not the body: a clean question with a head is clean",
             human_text.problems(head + human_text.CLEAN), [])
    check("but the same id in the body is caught after the head",
          "dispatch_id" in rules_of(head + pad + "S3-qa-test-strategist-1 stopped." + tail))
    check_eq("one source for the head: human_text.HEAD_RE is the pattern the driver hashes with",
             human_text.HEAD_RE.pattern, story_run.QUESTION_HEAD_RE.pattern)
    check("and the driver holds that very object, not a copy of it (B-009 part 2)",
          story_run.QUESTION_HEAD_RE is human_text.HEAD_RE)
    check_eq("and it strips the same lines from a question",
             human_text.HEAD_RE.sub("", head + "Body.\n", count=1), "\nBody.\n")

    # X1: what counts as "explained where it first appears" (critic t-039 F1, Lead's fork on parens).
    for shape in ("TS-14 - the import limit", "`TS-14` (the import limit)", "**TS-14** (the import limit)",
                  "TS-14, the import limit,", "the import limit (TS-14)", "TS-14 — the import limit",
                  "TS-14 – the import limit", "TS-14: the import limit", "_TS-14_ (the import limit)"):
        check(f"an id explained on the spot is clean: {shape!r}",
              "explained_ids" not in rules_of(pad + shape + " waits." + tail))
    # Y1: a comma explains an id only when another id does not follow it (a list is not an apposition).
    listed = next(r for r in human_text.rules()["forbidden"] if r.get("kind") == "explained_ids")
    check_eq("`see TS-14, TS-15` flags both ids", human_text._unexplained(listed, pad + "See TS-14, TS-15 today"),
             ["TS-14", "TS-15"])
    check_eq("`TS-14, `TS-15`` (markup before the second id) flags both",
             human_text._unexplained(listed, pad + "See TS-14, `TS-15` today"), ["TS-14", "TS-15"])
    check_eq("a list of ids of different shapes is a list too",
             human_text._unexplained(listed, pad + "See OBL-2,\nTC-004 today"), ["OBL-2", "TC-004"])
    check_eq("`TS-14, the import limit,` stays clean",
             human_text._unexplained(listed, pad + "TS-14, the import limit, waits."), [])
    check_eq("an id first, the list second: only the unexplained one is flagged",
             human_text._unexplained(listed, pad + "TS-14 (the size limit), TS-15 waits."), ["TS-15"])
    check("a bare `see TS-14.` is still flagged", "explained_ids" in rules_of(pad + "See TS-14. It waits." + tail))
    explained_rule = next(r for r in human_text.rules()["forbidden"] if r.get("kind") == "explained_ids")
    check_eq("an id at the very end of the text with no explanation is flagged",
             human_text._unexplained(explained_rule, pad + "The row is TS-14"), ["TS-14"])
    check_eq("an id at the very end, inside parentheses after words, is explained",
             human_text._unexplained(explained_rule, pad + "The import limit (TS-14)"), [])
    check("a parenthesis after nothing is not an explanation: `(TS-14)` opening a line is flagged",
          "explained_ids" in rules_of(pad + "\n(TS-14) waits." + tail))
    check("a list bullet on the next line is not an explanation",
          "explained_ids" in rules_of(pad + "It is TS-14\n- and more." + tail))
    check("`TS-14-foo` is not explained by the hyphen", "explained_ids" in rules_of(pad + "It is TS-14-foo here." + tail))

    # X3: a dispatch id needs its launch number; `[0-9]+` -> `[0-9]*` must not survive.
    check("`S3-qa-test-strategist stopped` (no launch number) is clean",
          "dispatch_id" not in rules_of(pad + "S3-qa-test-strategist stopped." + tail))
    check("a trailing hyphen with no number is not a launch number either",
          "dispatch_id" not in rules_of(pad + "S3-qa-test-strategist- stopped." + tail))
    check("but `S3-qa-test-strategist-12` is one", "dispatch_id" in rules_of(pad + "S3-qa-test-strategist-12 stopped." + tail))

    # X4: a `#` line inside a fence is code, not a heading; an unclosed fence keeps the rest.
    # (X7-5: the sample is a script name - a factory id, a shape a report is checked for; `exit 3` is a phrase and is not.)
    fenced = "## Factory defects\n```\n# c\n```\nstory_run.py happened\n"
    check("a fenced comment does not end the section: what follows is still checked",
          "script_name" in {p["rule"] for p in human_text.section_problems(fenced, "## Factory defects")})
    check("a real heading after the fence does end it",
          human_text.section_problems(fenced + "## Size\nstory_run.py happened\n", "## Factory defects")
          == human_text.section_problems(fenced, "## Factory defects"))
    unclosed = "## Factory defects\n```\n# c\nstory_run.py happened\n## Size\n"
    check("a fence that never closes: the rest of the text is inside the section",
          "script_name" in {p["rule"] for p in human_text.section_problems(unclosed, "## Factory defects")})
    check_eq("an empty section (heading, then the next heading) is []",
             human_text.section_problems("## Factory defects\n\n## Size\nstory_run.py\n", "## Factory defects"), [])
    check_eq("a heading inside a fence is not the section's start",
             human_text.section_problems("```\n## Factory defects\nstory_run.py\n```\n", "## Factory defects"), [])

    # X2: a code span that CONTAINS a snake token anywhere in it (the scribe's promise).
    for span in ("`review_rejected`", "`run-report.json: execution_status is 'not_executed'`",
                 "`only the state review_rejected here`"):
        check(f"snake_token catches {span}", "snake_token" in rules_of(f"It stands {span} today.", kind="report"))
    for span in ("`partial`", "`obligations.md`", "`TS-2/TS-3`", "`a.b_c`"):
        check(f"snake_token leaves {span}", "snake_token" not in rules_of(f"It stands {span} today.", kind="report"))
    # Y2: a span that is ENTIRELY a file name or a path names a place, not a state.
    for span in ("`delivery_summary.md`", "`work/ledger_view.json`", "`scripts/gate_brief.py`",
                 "`work\\ledger_view.json`"):
        check(f"snake_token leaves the path {span}",
              "snake_token" not in rules_of(f"See {span} today.", kind="report"))
    for span in ("`ledger_state.`", "`ledger_state`", "`review_rejected`", "`work/ledger_state`",
                 "`delivery_summary.md: review_rejected`", "`run-report.json: execution_status ok`",
                 "`delivery_summary.md review_rejected`"):
        check(f"snake_token still catches {span}",
              "snake_token" in rules_of(f"See {span} today.", kind="report"))
    check("a path span does not hide a later state span in the same text",
          "snake_token" in rules_of("See `delivery_summary.md`; it is `review_rejected`.", kind="report"))
    fixture = Path(__file__).resolve().parent / "fixtures" / "report-13877-factory-defects" / "test-report.md"
    real_13877 = fixture.read_text(encoding="utf-8")
    found_13877 = human_text.section_problems(real_13877, "## Factory defects")
    check("the real 13877 Factory defects section is refused, naming snake_token",
          "snake_token" in {p["rule"] for p in found_13877}, str(found_13877))
    real_13797 = (
        "## Factory defects — nothing is wanted from you\n\n"
        "Most delivery blocks trace to one known tooling gap. The code critic's static review is\n"
        "**approved**, red probe completed, for every instance of TC-004 through TC-010. The reviewing\n"
        "tool's receipt shape does not match what the ledger's sensitivity check demands, so the\n"
        "ledger reports an unverified or rejected review instead, plus (TC-005–TC-008) a stale link to\n"
        "the case version the test was written against. Already named a factory defect at the S5 gate\n"
        "— no result waived, no repair round owed; open only pending a receipt-shape decision.\n\n"
        "Smaller: TS-2/TS-3 read `partial` because eight raw pytest ids from the two earliest,\n"
        "superseded run attempts never joined a manifest row; the later reparse fix does not retire\n"
        "them. R-2/R-11/R-13 are proven transitively per the plan's own \"Not planned\" table, but the\n"
        "checker only reads the main table, so it reports no terminal outcome. Procedurally: gate A\n"
        "named a local bug proposal for AC7; none is authored yet. All open in `obligations.md`.\n\n"
        "## Size\n")
    check_eq("the real 13797 section (`partial`, `obligations.md`) stays clean",
             human_text.section_problems(real_13797, "## Factory defects"), [])

    report_text = "The review was rejected twice, so the count in the ledger is higher than the tests shown."
    check_eq("a report in words has no problem, and no answer block is wanted",
             human_text.problems(report_text, kind="report"), [])
    check_eq("a report is not asked for five parts: an empty text is not a finding",
             human_text.problems("", kind="report"), [])
    check("a ledger state in code quotes breaks snake_token in a report",
          "snake_token" in rules_of("It is `review_rejected` in the ledger.", kind="report"))
    check("but the same words in a question are not a snake_token finding",
          "snake_token" not in rules_of(pad + "It is `review_rejected` in the ledger." + tail))
    check("a report is checked by the shared rows too: a script name",
          "script_name" in rules_of("Run traceability.py again.", kind="report"))
    check("and a bare row id in a report is not this rule (questions only)",
          "explained_ids" not in rules_of("TS-14 waits.", kind="report"))
    section = "## Proven\n\nfine\n\n## Factory defects — nothing is wanted from you\n\nIt is `review_rejected`.\n\n## Size\n\nS\n"
    check_eq("section_problems reads only its own section",
             [p["rule"] for p in human_text.section_problems(section, "## Factory defects")], ["snake_token"])
    check_eq("a state in another section is not checked",
             human_text.section_problems(section.replace("`review_rejected`", "words"), "## Factory defects"), [])
    check_eq("an absent section has no problem", human_text.section_problems("## Size\n\nS\n", "## Factory defects"), [])

    # --- every kind of question the driver raises -------------------------------------------
    root, task_root, env = seed(task)
    stub = root / "fake_claude.py"
    stub.write_text(STUB, encoding="utf-8")
    stub_log = root / "stub-log.jsonl"
    saved = {key: os.environ.get(key) for key in ("STORY_RUN_CLAUDE", "STUB_LOG")}
    os.environ.update(STORY_RUN_CLAUDE=str(stub), STUB_LOG=str(stub_log))
    try:
        driver = driver_for(root, task)
        refusal = story_run.Refusal(
            "exit gate for S3-qa-test-strategist-1 (qa-test-strategist, S3): planning_contract.py: "
            "REAL exit 1 on the gate re-run (FB-27): - TS-14: low depth requires evidenced bounded "
            "effect; handover form header.verdict: not filled")
        built = driver.question_from_refusal(refusal, "S3")
        check_in("the driver's own question says where the story is", "the plan stage (S3)", built)
        # C1-1: the lead is the driver's own words only; the three standing answers come from the seam, each with its price
        check_not_in("and the lead alone carries no standing answers (the seam adds them, with prices)", "(c) stop the story here", built)
        fallback = driver.fallback_person({"why": "refusal", "kind": "refusal", "stage": "S3", "lead": built})
        check_eq("the seam's fallback offers the three standing answers", list(fallback.offered), ["retry", "go on", "stop"])
        for token in ("retry", "go on", "stop"):
            check_in(f"and shows `{token}` as an option", f"`{token}` — ", fallback.text)
        check_eq("every option is followed by its three price lines (the clean sample of price_problems)",
                 human_text.price_problems(fallback.text, list(fallback.offered)), [])
        dirty = fallback.text.replace("\nyou: ", "\nyou - ", 1)
        found_dirty = human_text.price_problems(dirty, list(fallback.offered))
        check("a missing label is found (the dirty sample of price_problems)", bool(found_dirty), str(found_dirty))
        check("and `problems` passes it on when it is given the offered tokens",
              any(p["rule"] == "price_lines" for p in human_text.problems(dirty, offered=list(fallback.offered))), str(found_dirty))

        # t-884 (C2-7 §5.1, §5.5): the fallback question AT A GATE (rework with its stages slot in words) and the `cap` question obey the rules
        journal_file = task_root / "state/driver-questions.jsonl"
        journal_before = journal_file.read_bytes() if journal_file.is_file() else b""      # these asks are not part of the count below
        driver.no_move_facts = lambda state: {"gate": "A", "gate_decided": False, "running": False, "closed": False, "attempts": 0,
                                              "rework_stages": ["S3", "S4"]}
        gate_q = driver.fallback_person({"why": "unread_answer", "kind": "gate_A", "stage": "S4", "lead": "Your answer was not read.",
                                         "words_file": "state/words/x.txt"})
        check_eq("C27: the gate's fallback offers approve / rework / retry / stop", list(gate_q.offered), ["rework", "approve", "retry", "stop"])
        check_in("C27: the stages slot names the stages in words", "the plan stage (S3)", gate_q.text)
        def as_shown(person) -> str:
            """The question as the person reads it: through `ask()`, which adds the how-to-answer block (rule 5)."""
            with contextlib.redirect_stdout(io.StringIO()):
                driver.ask(person)
            return (task_root / "state/driver-question.md").read_text(encoding="utf-8")
        shown_gate = as_shown(gate_q)
        check_eq("C27: the gate's fallback question obeys human-questions.md and every option has its three price lines",
                 (human_text.problems(shown_gate, offered=list(gate_q.offered)), human_text.price_problems(shown_gate, list(gate_q.offered))), ([], []))
        with_stage, no_stage = driver.refused_text("S3"), driver.refused_text("")
        check_in("C27 cap: the lead says what the story is missing, in its own words, with the stage",
                 "What the story is missing: the plan stage (S3) has not finished, and the reasons it was turned back are written for the "
                 "factory's own scripts, so I cannot tell which answer of that step would move it.", with_stage)
        # t-891 F-7: the `cap` is raised at ANY boundary (a waiting job and a story closed after the retro have no stage), so with no stage the
        # lead claims nothing about a stage - only what is true there: the reasons are written for the factory's own scripts (FR-41)
        check_in("C27 cap, empty stage: no clause about a stage at all, the reasons only",
                 "What the story is missing: the reasons it was turned back are written for the factory's own scripts, so I cannot tell which "
                 "answer would move it.", no_stage)
        check_not_in("C27 cap, empty stage: never 'this story has not finished'", "this story has not finished", no_stage)
        check_not_in("C27 cap, empty stage: ...and never 'the stage before this gate' (untrue at a waiting job or a closed story)",
                     "stage before this gate", no_stage)
        for label, lead in (("with a stage", with_stage), ("with an empty stage", no_stage)):
            cap_q = driver.fallback_person({"why": "cap", "kind": "refusal", "call": False, "stage": "S3" if "with a" in label else "", "lead": lead})
            shown_cap = as_shown(cap_q)
            check_eq(f"C27 cap {label}: the question obeys human-questions.md and its options are priced",
                     (human_text.problems(shown_cap, offered=list(cap_q.offered)), human_text.price_problems(shown_cap, list(cap_q.offered))), ([], []))
        journal_file.write_bytes(journal_before)

        kinds = {"conductor": built, "refusal": built, "retro": story_run.S9_QUESTION}
        for kind, text in kinds.items():
            person = story_run.Person(kind, text, "S3", details=refusal.text)
            code = driver.ask(person)
            check_eq(f"{kind}: asking the person exits 3", code, 3)
            shown = (task_root / "state/driver-question.md").read_text(encoding="utf-8")
            found = [p["rule"] for p in human_text.problems(shown)]
            check(f"{kind}: the text shown obeys references/human-questions.md", not found, str(found))
            check_not_in(f"{kind}: and carries no pasted refusal", "REAL exit 1", shown)
            check_in(f"{kind}: while naming where our own words are", "driver-question-details.md", shown)
        details = (task_root / "state/driver-question-details.md").read_text(encoding="utf-8")
        check_in("which is where the refusal went, whole", "REAL exit 1", details)

        journal = [json.loads(line) for line
                   in (task_root / "state/driver-questions.jsonl").read_text(encoding="utf-8").splitlines()
                   if line.strip()]
        check_eq("every question is journalled", len(journal), len(kinds))
        check_eq("with the rules it broke, so the share is measurable",
                 [row["problems"] for row in journal], [[] for _ in kinds])
        check_eq("and the kinds it was asked under",
                 sorted(row["kind"] for row in journal), sorted(kinds))

        # A question that breaks the rules is still asked - our defect is not the person's
        # problem - and the break is what gets recorded.
        driver.ask(story_run.Person("halt", "The conductor needs your word.", "S3"))
        last = [json.loads(line) for line
                in (task_root / "state/driver-questions.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()][-1]
        check_in("a filler question is journalled as ours", "filler", last["problems"])
        check("and the person still gets it",
              "The conductor needs your word." in
              (task_root / "state/driver-question.md").read_text(encoding="utf-8"))
        # The 13877 shapes as the driver records them: each is journalled with its own rule
        # (the text is still shown), and the head's dispatch id is not counted against it.
        shapes = {
            "slash_command": "The tool answered: Not logged in - Please run /login",
            "relayed_markup": "<!DOCTYPE html><html><head><title>Just a moment...</title></head></html>",
            "dispatch_id": "The strategist (S3-qa-test-strategist-1) stopped without a reason.",
        }
        for rule, line in shapes.items():
            driver.ask(story_run.Person("halt", pad + line, "S3", dispatch="S3-qa-test-strategist-1"))
            last = [json.loads(row) for row
                    in (task_root / "state/driver-questions.jsonl").read_text(encoding="utf-8").splitlines()
                    if row.strip()][-1]
            check_in(f"13877 shape journalled with its rule: {rule}", rule, last["problems"])
            check_eq(f"and only that one ({rule}): the head's dispatch id is not counted",
                     last["problems"], [rule])
            check_in(f"and the person still gets the text ({rule})", line,
                     (task_root / "state/driver-question.md").read_text(encoding="utf-8"))
        # --- B-009 part 2: what the driver itself says when a role halts or a boundary sticks ---
        def journalled() -> dict:
            return [json.loads(row) for row
                    in (task_root / "state/driver-questions.jsonl").read_text(encoding="utf-8").splitlines()
                    if row.strip()][-1]

        def shown_now() -> str:
            return (task_root / "state/driver-question.md").read_text(encoding="utf-8")

        digest = ("qa-test-strategist S3 all · halt\n"
                  "TS-14 · unresolved · the size limit is in neither the ticket nor the code\n"
                  "TS-15 · blocked\n")
        halt = driver.halt_text("S3", "qa-test-strategist", digest)
        check_in("the halt names the stage and the role in words",
                 "The plan stage (S3) stopped: the test strategist cannot go on without a decision.", halt)
        check_in("one line per row, the row's own reason",
                 "- TS-14 — the size limit is in neither the ticket nor the code", halt)
        check_in("a row with no reason says so instead of inventing one",
                 "- TS-15 — the report gives no reason", halt)
        check_in("and the promise is kept, now in the option that makes it", "the same role continues in its own session", halt)
        # C1-3 (prices as data, G4): the halt carries the priced section, and the check reads EVERY option line of it - the
        # tokenless `words` option included, which the offered-token reading never saw.
        check_in("the halt has its priced section", "## What each answer costs and does", halt)
        check_in("and its tokenless option", "(a) answer in your own words", halt)
        check_eq("every option of the halt is priced", human_text.price_problems(halt + "\n---\nAnswer: x", None), [])
        check_eq("the halt's priced tokens are carried by the text", tuple(halt.priced), ("stop",))
        dropped = halt.replace("the factory:", "").replace("you:", "").replace("the story:", "")
        check_eq("NEGATIVE: a tokenless option whose three labels are dropped is reported (not only a token's)",
                 sorted(item["found"][:3] for item in human_text.price_problems(dropped + "\n---\nAnswer: x", None)),
                 ["(a)", "(b)"])
        check_eq("NEGATIVE: only the tokenless option's labels removed - exactly that line is reported",
                 [item["found"][:3] for item in human_text.price_problems(
                     halt.replace("the factory: one more working session", "xx one more working session") + "\n---\nAnswer: x", None)],
                 ["(a)"])
        # G4 on the key the spec names (C2-9: `not needed` and, with a cause named, `skip all like these` are tokens now; `route` and
        # `content` stay free words for the conductor): the token is priced and every option line has its three price lines
        gap = driver.s1_gap_text("source unavailable and not accepted by a person: SRC-1")
        check_eq("s1.gap: the token `not needed` is priced and every option line has its three price lines (T17)",
                 (tuple(gap.priced), human_text.price_problems(gap + "\n---\nAnswer: x", None)), (("not needed",), []))
        gap_dropped = gap.replace("the factory:", "").replace("you:", "").replace("the story:", "")
        check_eq("NEGATIVE (s1.gap): the three labels dropped - all three options are reported",
                 sorted(item["found"][:3] for item in human_text.price_problems(gap_dropped + "\n---\nAnswer: x", None)),
                 ["(a)", "(b)", "(c)"])
        with_kind = driver.closed_question("s1.gap", "lead", [
            {"answer": "not_needed", "token": "not needed", "says": "x"},
            {"answer": "not_needed_kind", "token": "skip all like these", "says": "y"},
            {"answer": "route", "says": "z"}, {"answer": "content", "says": "w"}])
        check_eq("T17 s1.gap with a kind: both tokens priced, route and content are not",
                 (tuple(with_kind.priced), human_text.price_problems(with_kind + "\n---\nAnswer: x", None)),
                 (("not needed", "skip all like these"), []))
        # an S0 question is priced the same way (C1-3 node A): the options mix tokens and a tokenless paste, and carry `stop`
        s0_text = driver.closed_question("s0.ticket_read", "lead",
                                         [{"answer": "not needed", "token": "not needed", "says": "x"},
                                          {"answer": "retry", "token": "retry", "says": "x"},
                                          {"answer": "paste", "says": "x"}, driver.STOP_OPTION])
        check_eq("S0 ticket_read: every option has its three price lines, `stop` among the priced tokens",
                 (human_text.price_problems(s0_text + "\n---\nAnswer: x", None), tuple(s0_text.priced)),
                 ([], ("not needed", "retry", "stop")))
        check_eq("NEGATIVE (S0 ticket_read): the labels dropped are reported for every option, token or not",
                 len(human_text.price_problems(s0_text.replace("the factory:", "xx") + "\n---\nAnswer: x", s0_text.priced)), 4)
        for raw in ("qa-test-strategist S3 all", "unresolved", "S3-qa-test-strategist-1", "halt\n"):
            check_not_in(f"the raw digest is not in the body: {raw!r}", raw, halt)
        again = driver.halt_text("S3", "qa-test-strategist", digest, again=True)
        check_in("a second halt says `stopped again`", "The plan stage (S3) stopped again:", again)
        for label, bad in (("an unparseable header", "the strategist stopped; TS-14 is open\nTS-14 · unresolved · why"),
                           ("an empty digest", ""), ("a header with no rows", "qa-test-strategist S3 all · halt\n")):
            text = driver.halt_text("S3", "qa-test-strategist", bad)
            check_in(f"{label}: the `no reason` sentence",
                     "It gave no reason in its report; its own words are in the file named below.", text)
            check_not_in(f"{label}: and no row is invented from it", "- TS-14", text)
        # The halting header may sit below prose (`is_halting` reads every line): its rows are read.
        buried = "I stopped: the size limit is unknown.\n\n" + digest
        text = driver.halt_text("S3", "qa-test-strategist", buried)
        check_in("a header buried under prose still gives its rows",
                 "- TS-14 — the size limit is in neither the ticket nor the code", text)
        check_not_in("and not the `no reason` sentence", "It gave no reason", text)
        check_not_in("nor the prose above the header", "I stopped", text)
        check_in("no stage at all: the story", "This story stopped:", driver.halt_text("", "qa-scout", digest))
        driver.ask(story_run.Person("halt", halt, "S3", "S3-qa-test-strategist-1", details=digest))
        check_eq("the driver-built halt journals no problem", journalled()["problems"], [])
        check_eq("and asks under the same kind, stage and dispatch",
                 (journalled()["kind"], journalled()["stage"], journalled()["dispatch"]),
                 ("halt", "S3", "S3-qa-test-strategist-1"))
        check_in("the raw digest is in the details file", "qa-test-strategist S3 all · halt",
                 (task_root / "state/driver-question-details.md").read_text(encoding="utf-8"))
        check_in("which the answer block names", "driver-question-details.md", shown_now())
        # The re-raise of a saved question splits the head off at the sixth newline: the head
        # stays six lines, so what follows it is exactly the text.
        check_eq("the head is six lines: what follows it is the text we built",
                 shown_now().split("\n", 6)[-1].split("\n\n---\nAnswer:")[0], halt)
        check_eq("and the head's own dispatch id is the only place it stands",
                 [line for line in shown_now().splitlines() if "S3-qa-test-strategist-1" in line],
                 ["dispatch: S3-qa-test-strategist-1"])

        # The two raw relays the driver used to build: `where` four times the same, six refusals.
        stuck = driver.stuck_text("S3")
        try:
            driver.no_move({"why": "threshold", "kind": "refusal", "call": False, "stage": "S3", "dispatch": "", "lead": stuck,
                            "text": '{"action": "stage", "stage": "S3"}'})
            seamed = None
        except story_run.Person as raised:
            seamed = raised
        check("the stuck-`where` state ends in the seam's question", seamed is not None)
        driver.ask(seamed)
        check_eq("the stuck-`where` text journals no problem", journalled()["problems"], [])
        check_eq("it offers `retry`, `go on` and `stop`", list(seamed.offered), ["retry", "go on", "stop"])
        check_eq("each with its three price lines", human_text.price_problems(seamed.text, list(seamed.offered)), [])
        check_not_in("the old (a)(b)(c) copy is gone from it", "(c) stop the story here.", seamed.text)
        check_not_in("and pastes no answer of the step", '"action"', seamed.text)
        check_in("the step's answer is in the details file", '"action": "stage"',
                 (task_root / "state/driver-question-details.md").read_text(encoding="utf-8"))

        met = []

        def boom():
            met.append(1)
            raise story_run.Refusal("ticket_adapter get QA-9 (exit 2): S3-qa-x-1 said /login", retry=boom)
        driver.handle_refusal = lambda refusal, **kw: "retry"
        try:
            driver.guarded(boom, {"action": "stage", "stage": "S3"})
            person = None
        except story_run.Person as raised:
            person = raised
        check("six refusals in a row end in a question", person is not None)
        if person is not None:
            check_eq("its kind and stage are unchanged", (person.kind, person.stage), ("refusal", "S3"))
            check_not_in("the refusal is not pasted into it", "/login", person.text)
            check_in("the number in its words is the cap plus the refusal that broke it (the same constant)",
                     f"{story_run.REFUSALS_PER_BOUNDARY + 1} times in a row", person.text)
            check("and that is the number of refusals the boundary actually met",
                  len(met) >= story_run.REFUSALS_PER_BOUNDARY + 1, str(len(met)))
            check_in("the last refusal is in its details, whole", "S3-qa-x-1 said /login", person.details)
            driver.ask(person)
            check_eq("the six-refusals text journals no problem", journalled()["problems"], [])
            check_eq("and offers `retry`, `go on` and `stop`", list(person.offered), ["retry", "go on", "stop"])
            check_eq("each with its three price lines", human_text.price_problems(person.text, list(person.offered)), [])
            check_not_in("and not the old (a)(b)(c) copy", "(a) you deal with what is in the way", person.text)
        del driver.handle_refusal

        # --- a boundary answered once never comes back word for word (FR-7) ----------------
        # One `resolve_return` packet reached the person three times unchanged in run 5, because
        # nothing compared what was being asked with what had already been answered.
        asked_once = (task_root / "state/driver-question.md").read_text(encoding="utf-8")
        body = story_run.question_body_sha(asked_once)
        check_eq("the same body asked again hashes the same",
                 story_run.question_body_sha(asked_once.replace("asked_at: 2026", "asked_at: 2027")),
                 body)
        check("text after the answer block is not part of the question either",
              story_run.question_body_sha(asked_once + "\n\na later note") == body)
        check("but a changed body is a changed question",
              story_run.question_body_sha(built + " And one more thing.")
              != story_run.question_body_sha(built))

        # What `take_answer` writes when the person answers: the hash of the question's body.
        # It is taken from the whole question file there and from the body here, and the two
        # agree - that is the point of stripping the head and the answer block.
        driver.state_dir.mkdir(parents=True, exist_ok=True)
        (driver.state_dir / "driver-answers.jsonl").write_text(json.dumps(
            {"ts": "2026-09-27T10:15:00+00:00", "kind": "conductor", "stage": "S3",
             "dispatch": "", "question_sha": story_run.question_body_sha(built),
             "words": "Go on, accept it as it is."}) + "\n", encoding="utf-8")
        driver.ask(story_run.Person("conductor", built, "S3", details=refusal.text))
        again = (task_root / "state/driver-question.md").read_text(encoding="utf-8")
        check_in("the repeat says it was answered before", "answered this exact question before", again)
        check_in("quotes what was said", "Go on, accept it as it is.", again)
        check_in("and says what the factory needs now", "the boundary has not moved", again)
        check("so the text is not the one that was answered",
              story_run.question_body_sha(again) != body)
        found = [p["rule"] for p in human_text.problems(again)]
        check("and the changed question still obeys the rules", not found, str(found))

        # The whole round trip through the driver's own two ends: ask, answer, ask the same
        # thing again. Nothing here writes the journal by hand.
        (task_root / "state" / "driver-answers.jsonl").unlink()
        driver.state["asked"] = {}
        driver.save_state()
        driver.ask(story_run.Person("conductor", built, "S3", details=refusal.text))
        answer = task_root / "their-answer.md"
        answer.write_text("Accept it as it is and carry on.", encoding="utf-8")
        driver.take_answer(answer)
        check_eq("the conductor round trip went to the stub, once (never a real claude)",
                 len(stub_log.read_text(encoding="utf-8").splitlines()) if stub_log.exists() else 0, 1)
        rows =[json.loads(line) for line
                in (task_root / "state/driver-answers.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()]
        check_eq("taking the answer records which question it settled",
                 [row.get("question_sha") for row in rows], [story_run.question_body_sha(built)])
        driver.ask(story_run.Person("conductor", built, "S3", details=refusal.text))
        third = (task_root / "state/driver-question.md").read_text(encoding="utf-8")
        check_in("so asking it again carries their words back", "Accept it as it is and carry on.", third)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        harness.cleanup(root)

    harness.finish("test_human_questions")


if __name__ == "__main__":
    main()
