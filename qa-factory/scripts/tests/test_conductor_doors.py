#!/usr/bin/env python3
"""The conductor's text names the doors a refusal gives it (t-299, B-253 b and c).

TP1-15045, rehearsal on cmp2r, 02.10: the S7 form of the factory had no legal answer to a triage with
nothing to repair, and the conductor - which held the person's words - did not take the one door the refusal
named (`finish --ignore-handoff`): it tried `project_decisions.py add-finding`, met a bare traceback, invented
a scope word, and ended in `stop`. Two defects of the TEXT it is given: row 38 never named the three scope
words, and nothing told it that a door a refusal names is taken or shown to the person.

HONEST NOTE (FR-33): this file proves the text IS there - the sentence, the three words, the door on the
stage-boundary row, the size. Whether the conductor obeys it is proven only by a live run: the next story that
reaches a refusal naming a door, with a conductor session in it.
"""
import contextlib
import copy
import inspect
import io
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import project_decisions as PD  # noqa: E402

CONDUCTOR = PLUGIN_ROOT / "references" / "conductor.md"
SIZE_CAP = 12000        # references/*.md, selftest --limits (builder-rules 5)

# The sentence of the spec, VERBATIM (t-294 node B, requirement 3). Quoted here before the run, never derived
# from the file it checks.
SENTINEL = ("A door a refusal names is taken or shown to the person: run it when its condition holds — a door "
            "that records a person's word (`finish --ignore-handoff`, `waiver.py`) only with "
            "their words in the prompt — otherwise answer `ask_person` with that door as the command that "
            "records their answer. `stop` is for a refusal that names no door and matches no row of this table.")


def has_the_sentinel(path: Path) -> bool:
    """The assertion of K6, over a FILE: the sentence stands whole in it, on one line."""
    return any(SENTINEL in line for line in path.read_text(encoding="utf-8").splitlines())


def row_of(text: str, start: str) -> str:
    return next((line for line in text.splitlines() if line.startswith(start)), "")


def the_sentence_is_in_how_you_decide() -> None:
    text = CONDUCTOR.read_text(encoding="utf-8")
    check("K6: the verbatim sentence about doors is in conductor.md", has_the_sentinel(CONDUCTOR))
    section = text.split("## How you decide", 1)[1].split("## Your answer", 1)[0]
    item5 = re.search(r"(?ms)^5\. .*?(?=^6\. )", section)
    check("K6: ...and it is part of item 5 of 'How you decide'", bool(item5) and SENTINEL in item5.group(0))
    # the negative control: the same assertion over a scratch copy with the sentence removed fails
    scratch = temp_dir("qa-conductor-sentinel-")
    try:
        gone = scratch / "conductor.md"
        gone.write_text(text.replace(SENTINEL, ""), encoding="utf-8")
        check("K6 negative control: the same assertion over a copy WITHOUT the sentence fails", not has_the_sentinel(gone))
        changed = scratch / "changed.md"
        changed.write_text(text.replace("only with their words in the prompt", "whenever it helps"), encoding="utf-8")
        check("K6 negative control: and over a copy with one clause of it changed", not has_the_sentinel(changed))
    finally:
        cleanup(scratch)


# t-329 item 4 (today's man1 stop #2, FR-48, class B-253(c)): the sentence of the spec, VERBATIM, quoted here before the
# run and never derived from the file it checks. Its negative control is below (a copy without it, a copy with a clause
# changed).
DOOR_RULE = ("When a refusal names two or more doors the conductor can take itself, it takes the first that keeps the "
             "story moving and tells the person afterwards in one line, written in `did`; it asks only when every "
             "door needs the person's word.")


def has_the_door_rule(path: Path) -> bool:
    return any(DOOR_RULE in " ".join(line.split()) for line in path.read_text(encoding="utf-8").splitlines())


def the_rule_for_several_doors_is_in_how_you_decide() -> None:
    """K7 (t-329; the stage-boundary checks below kept their older K7 label): a refusal that names several doors the conductor can take itself is not an `ask_person`: the first door that
    keeps the story moving is taken. HONEST NOTE (FR-33): proves the text is there; that the conductor obeys it is a
    live run's to prove. The driver's own conductor prompt (`story_run.Driver.conductor`) carries no rule text of its
    own - `references/conductor.md` is its system file - so the one place the sentence lives is this file."""
    text = CONDUCTOR.read_text(encoding="utf-8")
    check("K7 door rule: the sentence about several doors is in conductor.md", has_the_door_rule(CONDUCTOR))
    section = text.split("## How you decide", 1)[1].split("## Your answer", 1)[0]
    item5 = re.search(r"(?ms)^5\. .*?(?=^6\. )", section)
    check("K7 door rule: ...and it is part of item 5 of 'How you decide', beside the one rule of K6",
          bool(item5) and DOOR_RULE in " ".join(item5.group(0).split()) and SENTINEL in item5.group(0))
    scratch = temp_dir("qa-conductor-door-rule-")
    try:
        gone = scratch / "conductor.md"
        gone.write_text(text.replace(DOOR_RULE, ""), encoding="utf-8")
        check("K7 door rule, negative control: the same assertion over a copy WITHOUT the sentence fails", not has_the_door_rule(gone))
        changed = scratch / "changed.md"
        changed.write_text(text.replace("it asks only when every door needs", "it asks whenever a door needs"), encoding="utf-8")
        check("K7 door rule, negative control: and over a copy with one clause of it changed", not has_the_door_rule(changed))
        no_did = scratch / "no-did.md"
        no_did.write_text(text.replace(", written in `did`", ""), encoding="utf-8")
        check("K7 door rule (t-335 A-n4), negative control: and over a copy that does not say the one line goes in `did`",
              not has_the_door_rule(no_did))
    finally:
        cleanup(scratch)
    import story_run
    import inspect
    body = inspect.getsource(story_run.Driver.conductor)
    check("K7 door rule: the driver's prompt builder names conductor.md as the system file and adds no second copy of the rule",
          'self.plugin / "references" / "conductor.md"' in body and "two or more doors" not in body)


def row_38_names_the_three_scope_words() -> None:
    text = CONDUCTOR.read_text(encoding="utf-8")
    row = row_of(text, "| A finding about the factory itself")
    check("K5: the row about a finding of the factory is in the table", bool(row))
    for word in PD.FINDING_SCOPES:
        check(f"K5: row 38 names `{word}`", f"`{word}`" in row, row)
    check_eq("K5: row 38 names every word the writer accepts, and no other word of that shape",
             sorted(set(re.findall(r"`((?:local|upstream)-[a-z]+)`", row))), sorted(PD.FINDING_SCOPES))
    check_in("K5: row 38 says the scope is never a path or a topic", "never a path or a topic", row)
    check_in("K5: row 38 names the command with its four fields", "--idempotency-key", row)
    check_in("K5: ...and still forbids a plugin edit", "never a plugin edit", row)


def the_stage_boundary_row_lists_the_ignore_handoff_door() -> None:
    text = CONDUCTOR.read_text(encoding="utf-8")
    row = row_of(text, "| A stage boundary the driver cannot express")
    check("K7: the stage-boundary row is in the table", bool(row))
    check_in("K7: it lists `finish --ignore-handoff`", "`finish --ignore-handoff`", row)
    check_in("K7: with its condition: the person's words in the prompt", "only with the person's words in the prompt", row)
    check_in("K7: and says what it passes", "handover form", row)
    paragraph = next((p for p in text.split("\n\n") if p.startswith("`waiver.py`, `release`")), "")
    check_in("K7: the paragraph that lists the commands recording a person's word names it too",
             "`finish --ignore-handoff`", " ".join(paragraph.split()))


def the_size_stays_under_the_cap() -> None:
    size = len(CONDUCTOR.read_bytes())
    check(f"S6: conductor.md is {size} bytes, at most {SIZE_CAP}", size <= SIZE_CAP, str(size))
    text = CONDUCTOR.read_text(encoding="utf-8")
    cyrillic = re.compile("[" + chr(0x400) + "-" + chr(0x4FF) + "]")   # built from code points: this file is English too
    check("the text is English (no Cyrillic)", not cyrillic.search(text))
    # C1-2 (B3, C3): the cap holds for every reference this node touches, AT and BEYOND it - a copy padded to exactly 12000
    # bytes passes, one more byte fails - and the real files keep their margin where the node added text.
    def within(path: Path) -> bool:
        return len(path.read_bytes()) <= SIZE_CAP
    scratch = temp_dir("qa-conductor-size-")
    try:
        for name in ("conductor.md", "controller-api.md", "human-questions.md"):
            real = PLUGIN_ROOT / "references" / name
            check(f"S6: {name} is {len(real.read_bytes())} bytes, within the cap", within(real))
            body = real.read_bytes()
            for extra, want in ((0, True), (1, False)):
                padded = scratch / f"{extra}-{name}"
                padded.write_bytes((body + b"x" * SIZE_CAP)[:SIZE_CAP + extra])
                check(f"S6 boundary: {name} padded to {len(padded.read_bytes())} bytes is {'within' if want else 'beyond'} the cap",
                      within(padded) is want)
    finally:
        cleanup(scratch)
    check("S6: conductor.md keeps at least 100 bytes of margin (C3)", SIZE_CAP - len(CONDUCTOR.read_bytes()) >= 100)


# --- C1-2 (conductor/1, P22): the conductor's powers as data, and the prompts that carry them (K8-K14) --------------
# The sentences below are quoted from the spec (t-630 with its amendments) BEFORE the run and never derived from the files
# they check. HONEST NOTE (FR-33): this proves the text and the data ARE there; that the conductor obeys them is proven by
# a live run only.
ROLE_RULE = ("- Never run the test suite yourself, never start a role's session yourself and never edit by hand an "
             "artifact a role owns; the factory commands named in this file are the exceptions (the stray case file "
             "named by the S4 exit-gate refusal, `handoff_check.py --set`, `critic_rollcall --apply-fixes`). A role is called "
             "only through the controller — `rework` sends a stage's accepted work back to its role, `release` frees a "
             "dispatch nobody is doing — or through `story_step.py start` where a phase file names it; the driver runs "
             "the role's session in all three.")
OLD_ROLE_BAN = "- Never run the test suite yourself and never call a role."
MOVES_RULE = ("If their words ask for something else the factory can do, take that move from `moves` (or the row of "
              "`actions` that says it) in references/conductor-actions.json when its precondition holds; otherwise run nothing and answer "
              "`ask_person` with the options, each with what it costs and what it does to the story "
              "(references/human-questions.md).")
OWN_TOKEN_RULE = ("A token from your own options is their choice: run that move (the row of `moves` whose token it is) "
                  "and say so in `did`.")
GATE_RULE = ("At gate A and gate B the person's words are the gate's answer. You never record a gate decision yourself. When "
             "their words approve what was shown and ask for no change, offer `approve`: the driver records it and applies "
             "their card answers first. When they ask for any change, offer the moves open here with what each costs. A rework "
             "of the stage that made it is followed by the stages after it running again and this gate being asked again. Run "
             "none of them before the person chooses.")
GATE_EXCLUSION = GATE_RULE      # the old name of the sentence the non-gate prompts must NOT carry (C1-4b replaced the exclusion by GATE_RULE)
DELIVERY_RULE = ("You never start a role's session and never edit what a role wrote. Only when a repair the decision "
                 "orders is still undone: it is never delivered around — while no delivery attempt is recorded (the line "
                 "`no attempt recorded` below), answer `ask_person` with the options of references/human-questions.md — "
                 "`go on` (deliver as it is) or `retry` (the person repairs it, then the delivery is asked again) — and send "
                 "nothing out; once an attempt is listed below, ask the same way and register nothing. When the person's "
                 "choice is in this prompt (the line `The person chose`), do what they chose: `go on` → the four steps; "
                 "`retry` → the person says the repair is done: check that it is, then the four steps, and while it is "
                 "still undone ask again and send nothing out. With no repair undone, do the four steps.")
OLD_DELIVERY_BAN = "you do NOT rework a stage"
ACTIONS = PLUGIN_ROOT / "references" / "conductor-actions.json"
VERDICTS = PLUGIN_ROOT / "references" / "delivery-verdict-kinds.json"
MOVE_KEYS = ("id", "token", "says", "run", "word", "precondition", "forbidden_when", "factory", "person", "delivery", "records")
NO_TOKEN = "—"
_HELP: dict = {}


def help_of(script: str, sub: str = "") -> str:
    """`--help` of a script of the package (and of its sub-command, when `sub` is one), cached; '' when it prints none."""
    key = (script, sub)
    if key not in _HELP:
        argv = [sys.executable, "-B", str(PLUGIN_ROOT / "scripts" / script)] + ([sub] if sub else []) + ["--help"]
        done = subprocess.run(argv, capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
        _HELP[key] = done.stdout if done.returncode == 0 else ""
    return _HELP[key]


def moves_problems(data: dict, verdict_words: set) -> list:
    """K9: what is wrong with the `moves` of a conductor-actions.json (parsed). One line per problem; [] is clean."""
    out: list = []
    classes = data.get("price_classes") or {}
    moves = data.get("moves") or []
    seen_ids, seen_tokens = set(), set()
    non_verdicts = set(classes.get("delivery") or {})
    if non_verdicts & verdict_words:
        out.append(f"a delivery value is in both sets: {sorted(non_verdicts & verdict_words)}")
    for row in moves:
        name = str(row.get("id"))
        out += [f"{name}: key {key!r} is missing" for key in MOVE_KEYS if key not in row]
        if name in seen_ids:
            out.append(f"{name}: id repeated")
        seen_ids.add(name)
        token = row.get("token")
        if token and token != NO_TOKEN:
            if token in seen_tokens:
                out.append(f"{name}: token {token!r} repeated")
            seen_tokens.add(token)
        for key, family in (("factory", "factory"), ("person", "person")):
            if row.get(key) not in (classes.get(family) or {}):
                out.append(f"{name}: {key} {row.get(key)!r} is not a price class")
        if row.get("delivery") not in non_verdicts | verdict_words:
            out.append(f"{name}: delivery {row.get('delivery')!r} is neither a verdict word nor a non-verdict class")
        out += command_problems(name, str(row.get("run") or ""))
    return out


def command_problems(name: str, run: str) -> list:
    """The commands inside one `run` (segments split at ' ; '): the script exists, every flag is in its `--help`, and no
    person's words are typed inline (`source_exclusions.py --words` is the one carrier without a file, B-365)."""
    out: list = []
    for segment in run.split(" ; "):
        found = re.search(r"(?<![\w.-])([A-Za-z_][\w-]*\.py)\b", segment)
        if not found:
            continue
        script = found.group(1)
        if not (PLUGIN_ROOT / "scripts" / script).is_file():
            out.append(f"{name}: script {script} does not exist")
            continue
        rest = segment[found.end():].split()
        sub = rest[0] if rest and re.fullmatch(r"[a-z][a-z_-]*", rest[0]) else ""
        text = help_of(script) + "\n" + (help_of(script, sub) if sub else "")
        for flag in sorted(set(re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", segment))):
            if not re.search(re.escape(flag) + r"(?![\w-])", text):
                out.append(f"{name}: {script} has no flag {flag}")
        if script != "source_exclusions.py" and re.search(r'--(?:reason|words|decision)\s+\\?"<', segment):
            out.append(f"{name}: {script} takes a person's words inline")
    return out


def fallback_problems(fallback: dict, standing: list) -> list:
    """K11: the fallback is keyed by the standing tokens (TOKEN_ANSWERS) and by nothing else. [] is clean."""
    if sorted(fallback) == sorted(standing):
        return []
    return [f"fallback keys {sorted(fallback)} are not the standing tokens {sorted(standing)}"]


def actions_problems(data: dict, conductor_text: str) -> list:
    """F-6, F-7: no `says` of an `actions` row names a script or a flag (it is for a person; the command is in `run`), and
    the exclusions row has its id, which conductor.md names. [] is clean."""
    out = [f"says names a script or a flag: {row.get('says')[:60]}" for row in data.get("actions") or []
           if re.search(r"\.py\b|(?<![\w-])--[a-z]", str(row.get("says")))]
    if not any(row.get("id") == "exclusions" for row in data.get("actions") or []):
        out.append("no `actions` row has the id `exclusions`")
    if "`exclusions` row" not in conductor_text:
        out.append("conductor.md does not point at the `exclusions` row")
    return out


def carries_move_rules(prompt: str) -> bool:
    """K12: a non-gate site's prompt carries MOVES_RULE and the token sentence."""
    return MOVES_RULE in prompt and OWN_TOKEN_RULE in prompt


def the_role_rule_replaces_the_old_ban() -> None:
    """K8: the lifted ban stands in 'What you never do', whole; the old line is gone."""
    def has_role_rule(path: Path) -> bool:
        text = path.read_text(encoding="utf-8")
        section = text.split("## What you never do", 1)[1].split("## How you decide", 1)[0]
        return ROLE_RULE in section and OLD_ROLE_BAN not in text
    check("K8: ROLE_RULE is in 'What you never do' and the old line is gone", has_role_rule(CONDUCTOR))
    text = CONDUCTOR.read_text(encoding="utf-8")
    scratch = temp_dir("qa-conductor-role-rule-")
    try:
        old = scratch / "old.md"
        old.write_text(text.replace(ROLE_RULE, OLD_ROLE_BAN), encoding="utf-8")
        check("K8 negative control: a copy with the old line restored fails", not has_role_rule(old))
        changed = scratch / "changed.md"
        changed.write_text(text.replace("only through the controller", "by hand"), encoding="utf-8")
        check("K8 negative control: a copy with 'only through the controller' changed fails", not has_role_rule(changed))
    finally:
        cleanup(scratch)


def the_moves_are_data_with_existing_commands() -> None:
    """K9, K10, K11: the `moves`, `price_classes` and `fallback` of conductor-actions.json."""
    import human_text
    import story_run
    data = json.loads(ACTIONS.read_text(encoding="utf-8"))
    words = set(json.loads(VERDICTS.read_text(encoding="utf-8"))["words"])
    check_eq("K9: the moves are clean (keys, unique ids and tokens, classes, scripts, flags, no inline words)",
             moves_problems(data, words), [])
    rework = next((row for row in data.get("moves") or [] if row.get("id") == "rework_stage"), {})

    def breaks(change) -> bool:
        copy_of = copy.deepcopy(data)
        change(copy_of)
        return bool(moves_problems(copy_of, words))

    def row(copy_of: dict, name: str) -> dict:
        return next((r for r in copy_of["moves"] if r["id"] == name), {})     # a row that is gone: the control then fails, cleanly
    check("K9 negative control: an invented flag fails",
          breaks(lambda d: row(d, "rework_stage").update(run=row(d, "rework_stage").get("run", "").replace("--rows", "--rowz"))))
    check("K9 negative control: an unknown price class fails", breaks(lambda d: row(d, "stop_here").update(factory="teleport")))
    check("K9 negative control: a repeated id fails", breaks(lambda d: row(d, "stop_here").update(id="rework_stage")))
    check("K9 negative control: an inline --reason \"<their words>\" fails",
          breaks(lambda d: row(d, "rework_stage").update(
              run=row(d, "rework_stage").get("run", "").replace("--words-file <file>", '--reason "<their words>"', 1))))
    check("K9 negative control: a delivery value of an unknown kind fails", breaks(lambda d: row(d, "stop_here").update(delivery="maybe")))
    check("K9 negative control: a value in both delivery sets fails", breaks(lambda d: d["price_classes"]["delivery"].update(no="x")))
    check("K9 negative control: a missing script fails",
          breaks(lambda d: row(d, "story_fact").update(run="no_such_script.py --task <T>")))
    # t-721 C2-3 (K9): the door `story_step.py decide` - the move row that runs it is C2-3s, but the detector already
    # reads the door's own `--help`: its three forms and the file carrier are real flags, and the words go by file only.
    door = "story_step.py decide --task <T> --dispatch-id <id> --{form} --words-file <file>, then answer `continue`"
    for form in ("hand <case ids>", "open <ids>", "close"):
        check_eq(f"K9: the door line `decide --{form.split()[0]} ... --words-file <file>` is clean (flags exist, no words inline)",
                 command_problems("record_person_decision", door.format(form=form)), [])
    check("K9 negative control: an invented flag on the door fails",
          bool(command_problems("record_person_decision", door.format(form="handed <case ids>"))))
    check("K9 negative control: the person's words inline on the door (--reason) fail",
          bool(command_problems("record_person_decision", door.format(form='hand <case ids> --reason "<their words>"'))))
    check("K9 negative control: the person's words inline on the door (--words) fail",
          bool(command_problems("record_person_decision", door.format(form='hand <case ids> --words "<their words>"'))))
    # F-6, F-7: the `actions` rows keep scripts and flags in `run`, and the exclusions row is addressed by id
    conductor_text = CONDUCTOR.read_text(encoding="utf-8")
    check_eq("F-6/F-7: no says names a script or a flag; the exclusions row has its id and conductor.md names it",
             actions_problems(data, conductor_text), [])
    flagged = copy.deepcopy(data)
    flagged["actions"][0]["says"] = "the factory runs case_versions.py --all"
    check("F-7 negative control: a script and a flag in a `says` is found (the same checker)", bool(actions_problems(flagged, conductor_text)))
    nameless = copy.deepcopy(data)
    for action in nameless["actions"]:
        action.pop("id", None)
    check("F-6 negative control: no row with the id `exclusions` is found (the same checker)",
          bool(actions_problems(nameless, conductor_text)))
    check("F-6 negative control: conductor.md pointing at `the last row` is found (the same checker)",
          bool(actions_problems(data, conductor_text.replace("`exclusions` row", "last row"))))
    # K10 (C11: both waiver blocks, each with its cause; B11: no 'reopens' - a closed story has later stages completed)
    check("K10: the rework_stage row exists", bool(rework))
    check("K10: it runs `--operation rework` with `--words-file`",
          "--operation rework" in str(rework.get("run")) and "--words-file" in str(rework.get("run")))
    for key in ("accepted", "running", "after S<n>", "approved scope", "BOTH roles",
                "the pass of that round, as the refusal prints it", "the pass of that mechanical round, as the refusal prints it"):
        check(f"K10: its precondition names `{key}`", key in str(rework.get("precondition")), str(rework.get("precondition")))
    # C1-5a (A2): the stage-wide words of the old doors are gone from the data file - the round pass is the only door left. The pin
    # reads the whole file text, so a revival anywhere in it is red; its control is the same scan over the old precondition.
    def stage_wide_in(text: str) -> list:
        return [w for w in ('block \\"repair round\\"', 'block \\"mechanical round\\"', '\\"mechanical repair round\\"') if w in text]
    raw_text = (PLUGIN_ROOT / "references" / "conductor-actions.json").read_text(encoding="utf-8-sig")
    check_eq("K10 (C1-5a): conductor-actions.json holds no stage-wide round block (`repair round` / `mechanical round`)",
             stage_wide_in(raw_text), [])
    check_eq("K10 negative control (C1-5a): the same scan finds the old doors in the old precondition",
             len(stage_wide_in('--block \\"repair round\\" ... first needs the block \\"mechanical repair round\\" the same way')), 2)
    check_eq("K10 negative control (C1-5a): ...and the third door, `mechanical round`", stage_wide_in('--block \\"mechanical round\\"'),
             ['block \\"mechanical round\\"'])
    check("K10: ...and promises no reopening of a closed story", "reopens" not in str(rework.get("precondition")).lower())
    check_eq("K10 (C1-4b): the token of rework_stage is `rework`, its factory price `stages_again`",
             (rework.get("token"), rework.get("factory")), ("rework", "stages_again"))
    check("K10 (C1-4b): its precondition no longer waits for C1-4", "C1-4" not in str(rework.get("precondition")) and "the story is open" in str(rework.get("precondition")),
          str(rework.get("precondition")))
    approve = next((r for r in data.get("moves") or [] if r.get("id") == "approve_gate"), {})
    check_eq("K9 (C1-4b): the `approve_gate` row: token, who speaks, what it costs", (approve.get("token"), approve.get("word"), approve.get("factory"),
             approve.get("person"), approve.get("delivery")), ("approve", "person", "record", "none", "unchanged"))
    check("K9 (C1-4b): ...it is a gate move (precondition) and records the person's answer whole",
          "gate A or gate B" in str(approve.get("precondition")) and "authorization_source" in str(approve.get("records")))
    # K11 (C10): the texts a person reads obey the shape rules; the fallback is keyed by the standing tokens only
    texts = [str(text) for family in ("factory", "person", "delivery") for text in (data["price_classes"].get(family) or {}).values()]
    texts += [str(entry.get("says")) for entry in data["fallback"].values()]
    found = {text: [p["rule"] for p in human_text.shape_problems(text)] for text in texts if human_text.shape_problems(text)}
    check_eq("K11: every price class and fallback text passes the shape rules", found, {})
    standing = re.findall(r"^`([^`]+)`", story_run.TOKEN_ANSWERS, re.M)
    check_eq("K11: the fallback is keyed by TOKEN_ANSWERS only (retry / go on / stop)", fallback_problems(data["fallback"], standing), [])
    check_eq("K11: ...which are exactly retry, go on, stop", sorted(standing), ["go on", "retry", "stop"])
    check("K11 negative control: a text with a script name breaks the shape rules",
          bool(human_text.shape_problems("run waiver.py --task X --stage S3 --block y")))
    invented = copy.deepcopy(data)
    invented["fallback"]["go away"] = invented["fallback"]["stop"]
    check("K11 negative control: a fallback key that is no standing token is found (the same checker)",
          bool(fallback_problems(invented["fallback"], standing)))


class PromptRig:
    """One seeded project and an in-process driver whose conductor is a stub that records the prompt it was given, so the
    text each call site builds is the thing under test (C7). `take_answer` runs for real; `record_by_code`, `judged_reply`,
    `take_stand_gap_answers` and the review recorder are stubs that count their calls."""

    def __init__(self):
        import story_run_common as common
        self.common = common
        self.task = "QA-9"
        self.root, self.task_root, self.env = common.d2_seed(self.task, environment="Local", pending=False)
        self.gate_calls: list = []

    def driver(self):
        driver = self.common.driver_for(self.root, self.env, self.task)
        self.prompts, self.words = [], []
        driver.conductor = lambda text, *, words="", files=None, words_file=None: (self.prompts.append(text), self.words.append(words)) and \
            {"action": "continue", "did": "stub"}
        driver.judged_reply = lambda *a, **k: ""
        driver.take_stand_gap_answers = lambda *a, **k: {}
        driver.record_review = lambda *a, **k: False
        driver.record_by_code = lambda *a, **k: self.gate_calls.append(("record_by_code", a)) and False
        real_py = driver.py

        def spy_py(script, *args, **kwargs):
            if "gate-decision" in args:
                self.gate_calls.append(("gate-decision", args))
            return real_py(script, *args, **kwargs)
        driver.py = spy_py
        return driver

    def answer(self, kind: str, stage: str, words: str, dispatch: str = "", **state) -> str:
        driver = self.driver()
        driver.state["asked"] = {"kind": kind, "stage": stage, "dispatch": dispatch}
        driver.state.update(state)
        driver.save_state()
        (self.task_root / "state" / "driver-question.md").write_text(f"# q\nkind: {kind}\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            driver.take_answer(Path(self.common.d2_answer(self.root, words)))
        return self.prompts[-1] if self.prompts else ""

    def build_answer(self, words: str) -> str:
        driver = self.driver()
        driver.state["build_question"] = {"environment": "nowhere", "profile": "api", "answers": []}
        with contextlib.redirect_stdout(io.StringIO()):
            driver.take_build_answer(words, "# q\n", "S5", "")
        return self.prompts[-1] if self.prompts else ""


def the_prompts_carry_the_moves_and_the_gate_exclusion() -> None:
    """K12 per call site (B7, C1, C7) and K14 (B1): the five prompts that take a person's words carry MOVES_RULE and the
    token sentence; the gate branch carries the exclusion and NOT MOVES_RULE; `s1_review` carries neither; and a token
    answer at a non-gate kind never reaches the gate's decision code, while at a gate kind it still does (today's path)."""
    import story_run
    check_eq("K12: story_run.MOVES_RULE is the spec's sentence", story_run.MOVES_RULE, MOVES_RULE)
    check_eq("K12: story_run.OWN_TOKEN_RULE is the spec's sentence", story_run.OWN_TOKEN_RULE, OWN_TOKEN_RULE)
    check_eq("K12 (C1-4b): story_run.GATE_RULE is the spec's sentence (spec 4.2), and GATE_OPTIONS_RULE is gone",
             (story_run.GATE_RULE, hasattr(story_run, "GATE_OPTIONS_RULE")), (GATE_RULE, False))
    check("K12: Driver.conductor names `options` in the JSON line it asks for",
          '"options"' in inspect.getsource(story_run.Driver.conductor))
    check("K12: ...and types `story` as the dict (`unverified`, `report`, `delivery`), not a string",
          all(f'"{key}"' in inspect.getsource(story_run.Driver.conductor) for key in ("unverified", "report", "delivery")))
    rig = PromptRig()
    first_prompt = ""
    try:
        token = "prepare the stand"
        sites = {
            "environment (the stand question)": lambda: rig.answer("environment", "S6", "the staging one should be up", stand_question="S6"),
            "stand_login": lambda: rig.answer("stand_login", "S6", "I will look at the screens", login_question={"stage": "S6", "cases": []}),
            "stand_identity (take_build_answer)": lambda: rig.build_answer("it is the nightly one, I think"),
            "halt": lambda: rig.answer("halt", "S3", "carry on with the plan", dispatch="S3-qa-test-strategist-1"),
            "conductor (the generic prompt)": lambda: rig.answer("conductor", "S3", token),
        }
        for label, build in sites.items():
            prompt = build()
            first_prompt = first_prompt or prompt
            check(f"K12 {label}: a prompt was built", bool(prompt))
            check(f"K12 {label}: it carries MOVES_RULE", MOVES_RULE in prompt)
            check(f"K12 {label}: ...and the token sentence", OWN_TOKEN_RULE in prompt)
            check(f"K12 {label}: the site assertion `carries_move_rules` holds", carries_move_rules(prompt))
            check(f"K12 {label}: ...and not the gate exclusion", GATE_EXCLUSION not in prompt)
        check_eq("K14: a token answer at the non-gate kinds never reaches the gate's decision code", rig.gate_calls, [])
        for gate in ("gate_A", "gate_B"):
            prompt = rig.answer(gate, "S4" if gate == "gate_A" else "S8", token)
            check(f"K12 {gate} (C1-4b): the gate branch carries MOVES_RULE + OWN_TOKEN_RULE + GATE_RULE",
                  all(rule in prompt for rule in (MOVES_RULE, OWN_TOKEN_RULE, GATE_RULE)))
            check(f"K12 {gate}: ...and the old 'options are not offered' sentence is gone", "options are not offered" not in prompt)
            rig.gate_calls.clear()
        # K14 (flipped by C1-4b, I1/I2): the REAL recorder runs; a gate answer without the first-line word never reaches the gate's
        # decision code (`gate-decision`), with it it does
        def decisions(gate, stage, words):
            driver = rig.driver()
            driver.record_by_code = type(driver).record_by_code.__get__(driver)
            driver.report_attribution = lambda g, w: {}
            driver.py = lambda script, *a, **k: (rig.gate_calls.append(("gate-decision", a)) or (0, "")) if "gate-decision" in a else (0, "")
            driver.state["asked"] = {"kind": gate, "stage": stage, "dispatch": ""}
            driver.save_state()
            with contextlib.redirect_stdout(io.StringIO()):
                driver.take_answer(Path(rig.common.d2_answer(rig.root, words)))
            count = len(rig.gate_calls)
            rig.gate_calls.clear()
            return count
        for gate, stage in (("gate_A", "S4"), ("gate_B", "S8")):
            check_eq(f"K14 {gate}: prose and a standing word are never the decision (0 calls); the first-line word is (1 call)",
                     (decisions(gate, stage, token), decisions(gate, stage, "approved as it stands, but fix the export test"),
                      decisions(gate, stage, "approve\nplease keep the card answers"), decisions(gate, stage, "﻿approve\r\n")),
                     (0, 0, 1, 1))
        prompt = rig.answer("s1_review", "S1", "go on, the review is fine", dispatch="S1-qa-scout-1")
        check("K12 s1_review: a prompt was built", bool(prompt))
        check("K12 s1_review: it carries neither MOVES_RULE nor the token sentence nor the exclusion",
              MOVES_RULE not in prompt and OWN_TOKEN_RULE not in prompt and GATE_EXCLUSION not in prompt)
        # negative controls: the SAME site assertion over a real prompt with MOVES_RULE swapped for the old sentence, and
        # over one with the token sentence removed, fails
        old = "If their words do not say that, run nothing: answer `ask_person` with one question that says what is still unsettled."
        check("K12 negative control: a real prompt with the old sentence instead of MOVES_RULE fails the site assertion",
              carries_move_rules(first_prompt) and not carries_move_rules(first_prompt.replace(MOVES_RULE, old)))
        check("K12 negative control: a real prompt without the token sentence fails the site assertion",
              not carries_move_rules(first_prompt.replace(OWN_TOKEN_RULE, "")))
    finally:
        cleanup(rig.root)


def the_delivery_rule_replaces_the_delivery_ban() -> None:
    """K12 (delivery, C6): the delivery prompt carries DELIVERY_RULE and not the old ban; a first call says `no attempt
    recorded`, a later one lists its attempts and does not; with the person's `deliver as it is` in the prompt the stub's
    `continue` marks the delivery done (the prompt's instruction, not a model, is what is asserted)."""
    import story_run
    check("K12 delivery: the delivery step builds its prompt from DELIVERY_RULE and has no old ban in its source",
          "DELIVERY_RULE" in inspect.getsource(story_run.Driver.delivery)
          and OLD_DELIVERY_BAN not in inspect.getsource(story_run.Driver.delivery))
    rig = PromptRig()
    try:
        def deliver(attempts, answers=()):
            driver = rig.common.driver_for(rig.root, rig.env, rig.task)
            seen = []
            driver.recomputed_word = "yes"
            driver.person_answers = lambda: list(answers)
            if attempts:
                driver.state["delivery_attempts"] = attempts
            driver.run_claude = lambda kind, prompt, **kw: (seen.append(prompt) or
                {"result": '{"action": "continue", "did": "stub"}', "session_id": "s", "stderr": "", "total_cost_usd": 0.0,
                 "num_turns": 1, "is_error": False})
            with contextlib.redirect_stdout(io.StringIO()):
                driver.delivery({"action": "deliver", "authorization_source": "go"})
            return seen[0], driver
        prompt, driver = deliver([], answers=["go on"])
        check("K12 delivery: DELIVERY_RULE is in the prompt", DELIVERY_RULE in prompt)
        check("K12 delivery: the old ban is not", OLD_DELIVERY_BAN not in prompt)
        check("K12 delivery: the first call says `no attempt recorded`", "Delivery attempts so far: no attempt recorded." in prompt)
        check("K12 delivery (C1-6c): the person's `go on` is in the prompt next to the instruction that follows it",
              "go on" in prompt.split("The person's answers recorded in this story", 1)[1].split("\n", 1)[0]
              and "`go on` → the four steps" in prompt and "`retry` → the person says the repair is done" in prompt)
        check("K12 delivery (C1-6c): the rule names the tokens `go on` / `retry` and neither of the old, non-token options",
              all(f"`{t}`" in DELIVERY_RULE for t in ("go on", "retry")) and "the person repairs it `" not in DELIVERY_RULE
              and "`deliver as it is`" not in DELIVERY_RULE and "`the person repairs it`" not in DELIVERY_RULE)
        for choice, token, said in (("go_on", "go on", "deliver as it is."), ("retry", "retry", "they repaired what was undone themselves.")):
            chosen = rig.common.driver_for(rig.root, rig.env, rig.task)
            chosen.recomputed_word, chosen.person_answers = "yes", lambda: []
            chosen.state["delivery_choice"] = {"choice": choice, "token": token, "words_file": "state/words/a.txt", "at": "t"}
            seen_choice = []
            chosen.run_claude = lambda kind, prompt, **kw: (seen_choice.append(prompt) or
                {"result": '{"action": "continue", "did": "stub"}', "session_id": "s", "stderr": "", "total_cost_usd": 0.0,
                 "num_turns": 1, "is_error": False})
            with contextlib.redirect_stdout(io.StringIO()):
                chosen.delivery({"action": "deliver", "authorization_source": "go"})
            check(f"K12 delivery (C1-6c): the typed record `{choice}` reaches the prompt as `The person chose `{token}`: {said}`, and is spent",
                  f"The person chose `{token}`: {said}" in seen_choice[0] and "delivery_choice" not in chosen.state)
        check("K12 delivery: a `continue` verdict then marks the delivery done (no re-ask loop)",
              bool((driver.state.get("delivery") or {}).get("done")))
        later, _ = deliver([{"at": "2026-10-09T10:00:00", "action": "ask_person", "did": "", "question": "x"}])
        check("K12 delivery: a later call lists its attempts and does not say `no attempt recorded` as a state",
              "Earlier attempts at this delivery" in later and "Delivery attempts so far: no attempt recorded." not in later)
        check("K12 delivery: kept lines :6918 and :6920 (the delivery does only its four steps)",
              "in this order and nothing else" in prompt and "nothing it does not" in prompt)
    finally:
        cleanup(rig.root)


def the_registered_dispatch_gets_the_whole_reason() -> None:
    """K13 (F3, FR-8): a dispatch the conductor registered and this driver never launched runs with the controller
    record's own `reason` - the person's words whole - and falls back to `purpose`, then to the fixed word."""
    rig = PromptRig()
    try:
        def reason_for(record: dict):
            driver = rig.common.driver_for(rig.root, rig.env, rig.task)
            dispatch = "S3-qa-test-strategist-9"
            captured = []
            driver.controller_state = lambda: {"dispatches": {dispatch: dict(
                {"stage": "S3", "role": "qa-test-strategist", "scope": []}, **record)}}
            driver.completion_for = lambda *a, **k: True
            driver.run_role = lambda stage, role, **kw: captured.append(kw)
            driver.state["pending_words"], driver.state["sessions"] = {}, {}
            with contextlib.redirect_stdout(io.StringIO()):
                driver.dispatch_action({"action": "wait_existing_job", "dispatch_id": dispatch})
            return captured[0]["rework"]["reason"] if captured else None
        words = "the export test checks only the status code\nplease check the body too"
        check_eq("K13: a two-line reason travels whole", reason_for({"reason": words, "purpose": "repair_verify"}), words)
        check_eq("K13 boundary: no reason - the purpose", reason_for({"purpose": "repair_verify"}), "repair_verify")
        check_eq("K13 boundary: neither - the fixed word", reason_for({}), "registered dispatch")
    finally:
        cleanup(rig.root)


def question_price_problems(data: dict, classes: dict, verdict_words: set) -> list:
    """K15: every row of references/question-prices.json names price classes of conductor-actions.json and a delivery value
    that is in exactly one of the two sets (the non-verdict classes, the verdict words). [] is clean."""
    out: list = []
    non_verdicts = set((classes.get("delivery") or {}))
    for key, rows in (data.get("questions") or {}).items():
        for row in rows:
            name = f"{key}.{row.get('answer')}"
            for field, family in (("factory", "factory"), ("person", "person")):
                if row.get(field) not in (classes.get(family) or {}):
                    out.append(f"{name}: {field} {row.get(field)!r} is not a price class")
            delivery = row.get("delivery")
            if (delivery in non_verdicts) == (delivery in verdict_words):
                out.append(f"{name}: delivery {delivery!r} is in {'both sets' if delivery in non_verdicts else 'neither set'}")
    return out


QUESTION_SITE_RE = re.compile(r'\b(?:closed_question|priced_section)\(\s*"([^"]+)"')
# Keys whose rows are in the data before their site exists. C1-5a (t-702) put the five of the repair limit here: their sites arrive
# with C1-5b1 (S5) and C1-5b2 (S7), which take them off this list (and list them in PINNED_ELSEWHERE). A key listed here that the code
# already raises is a defect of THIS list, not a pass (the negative control below uses a synthetic list).
REPAIR_LIMIT_KEYS = ("s5.repair_limit", "s5.nobody_review", "s5.nobody_environment", "s5.nobody_tooling", "s7.repair_limit")
# C1-5b1 (S5) took the four `s5.*` keys off this list: their sites are `Driver.repair_limit_person`, pinned in
# test_story_run_repair_limit.py (PINNED_ELSEWHERE below). `s7.repair_limit` was listed here until C1-5b2 wrote the S7 site (`Driver.repair_limit_person`
# through `s7_limit`); it is in PINNED_ELSEWHERE now (RL8), and a key listed here that the code already raises is a defect of THIS list.
AWAITING_ITS_SITE: set = {"awaiting.stop"}  # PC-7 (t-2181): the row is data and priced (test_human_reading.py H9); no driver site asks it yet - the stop of a wait is the person's word through `controller.py --operation stop_waiting`. TR3-10 part D: `s6.walk_supply`, `s6.data_change` (test_walk_supply.py) and `s6.walk_account` (test_walk_account.py) have their builders and branches; the census counts them as raised
# Keys the code raises that this process cannot drive; each is raised, and its question text pinned, by the named file.
PINNED_ELSEWHERE = {"package.copies": "test_package_generation.py (D3)", "s0.flags": "test_story_run_s0.py",
                    "s0.key_form": "test_s0_key_form.py", "s0.no_change": "test_no_mr_entry.py",
                    "sides.deliverable": "test_no_mr_entry.py (not_built_yet_and_the_sides_at_launch: the question, its form, ours / another team's)",
                    "s0.stand": "test_story_run_s0_stand_trace.py", "s0.readiness": "test_story_run_s0.py",
                    "questions": "test_question_stop.py (T1..T5)",
                    "questions.blocking": "test_story_run_loop_b_answers.py (HF2-7 K2: the blocking stop's priced options and unverified line)",
                    "s5.repair_limit": "test_story_run_repair_limit.py (RL1-RL4, RL6)", "s5.nobody_review": "test_story_run_repair_limit.py (RL5)",
                    "s5.nobody_environment": "test_story_run_repair_limit.py (RL5)", "s5.nobody_tooling": "test_story_run_repair_limit.py (RL5)",
                    "exit.resume_limit": "test_story_run_exit_limit.py (EL1-EL7, EL10, EL14)", "s7.repair_limit": "test_story_run_repair_limit.py (RL8)",
                    "exit.resume_limit_halted": "test_exit_limit_halt_answered.py (t-1955 N4: the halted variant of the exit-limit question)",
                    "s7.open_work": "test_story_run_s7_live.py (FX-2)",
                    "code_close.stage": "test_story_run_refusals.py (CC1, CC8)", "code_close.closed_story": "test_story_run_refusals.py (CC13)",
                    "code_close.factory_file": "test_story_run_refusals.py (CC14)",
                    "code_close.behind": "test_code_close_behind.py (t-1988 N3: the close refused behind an earlier stage)",
                    "closed.held": "test_story_closed.py (C1-6a: the question and its three executors)",
                    "s6.stand_login": "test_story_run_s6.py (C1-6b: C16b stand_login, 3 x 3 lines, two records)",
                    "s6.walk_account": "test_walk_account.py (TR3-10 D3a step 3: the account question, its tokens and executors)",
                    "s6.walk_supply": "test_walk_supply.py (TR3-10 D3a: the way question, its tokens and executors)",
                    "s6.data_change": "test_walk_supply.py (TR3-10 D3a step 2: the data-change question, its tokens and executor)",
                    "s6.stand_confirm": "test_story_run_s6.py (C1-6b: C16b stand_confirm, the price section and the executors)",
                    "s6.gate_a_dry": "test_story_run_s6.py (C1-6b: C16b gate A dry, reapprove / go on / stop, edge 10)",
                    "s3.grounding_coverage": "test_grounding_coverage.py (G2-2: the coverage stop, go on / stop)",
                    "s3.grounding_coverage.not_known": "test_grounding_coverage.py (G2-2: only unknown outside the count)",
                    "s3.grounding_coverage.nothing_asked": "test_grounding_coverage.py (G2-2: N = 0)",
                    "s3.grounding_refactoring": "test_grounding_coverage.py (G2-2: the refactoring stop after the coverage one)",
                    "arrival.not_waiting": "test_story_run_arrival.py (A9: the question, its three tokens and their executors)",
                    "awaiting.absent_side": "test_story_sides.py (t-2559 W2 B3: the question at the S5 hold, its two tokens and their executors)",
                    "first_look.dead": "test_first_look_step.py (FL-5: below_floor_asks_once, the question and its tokens)",
                    "first_look.same_code": "test_first_look_code_look.py (FL-6: bare_relaunch_head_same_asks_same_code, the question and its answers)",
                    "explore.frame": "test_exploration.py (frame_text_passes_form, frame_prices)"}


def census_problems(raised: set, data_keys: set, driven: set, awaiting: set, pinned: set) -> list:
    """The census of the question keys, BOTH directions, naming each difference: [] is clean. `raised`: the keys the code's
    sites pass; `data_keys`: the keys of question-prices.json; `driven`: those this test drives; `awaiting`: data rows whose
    site is not written yet; `pinned`: raised keys another file pins."""
    out = [f"raised by the code, no row in the data: {k}" for k in sorted(raised - data_keys)]
    out += [f"a row in the data, no site raises it (and not awaiting its site): {k}" for k in sorted(data_keys - raised - awaiting)]
    out += [f"listed as awaiting its site, but the code raises it (take it off the list): {k}" for k in sorted(awaiting & raised)]
    out += [f"listed as awaiting its site, but the data has no row for it: {k}" for k in sorted(awaiting - data_keys)]
    out += [f"raised, but neither driven here nor pinned elsewhere: {k}" for k in sorted(raised - driven - pinned)]
    out += [f"listed as pinned elsewhere, but driven here (take it off the list): {k}" for k in sorted(pinned & driven)]
    out += [f"listed as pinned elsewhere, but the code does not raise it: {k}" for k in sorted(pinned - raised)]
    return out


def the_question_prices_are_data() -> None:
    """K15 (C1-3, G14): the priced options of the closed questions are DATA in references/question-prices.json, loaded by ONE
    loader; conductor-actions.json (read by the conductor on every call) carries no `questions` block; every class is a
    price class; and the answers the code offers per key are the data's rows."""
    import no_move as NM
    from story_run_common import driver_for, seed
    actions = json.loads((PLUGIN_ROOT / "references" / "conductor-actions.json").read_text(encoding="utf-8-sig"))
    raw = json.loads((PLUGIN_ROOT / "references" / "question-prices.json").read_text(encoding="utf-8-sig"))
    words = set((json.loads((PLUGIN_ROOT / "references" / "delivery-verdict-kinds.json").read_text(encoding="utf-8-sig")))["words"])
    check_eq("K15: the file's ONE top-level key is `questions`", list(raw), ["questions"])
    check("K15: conductor-actions.json keeps moves / price_classes / fallback and gains no `questions` block (G14)",
          "questions" not in actions and all(k in actions for k in ("moves", "price_classes", "fallback")))
    check_eq("K15: the one loader returns every key of the file", sorted(NM.load_question_prices()), sorted(raw["questions"]))
    check_eq("K15: every class and delivery value of every row resolves", question_price_problems(raw, actions["price_classes"], words), [])
    dirty = copy.deepcopy(raw)
    dirty["questions"]["halt"][0]["factory"] = "no_such_class"
    check("K15 negative control: an unknown class is found (the same checker)",
          any("halt.words: factory 'no_such_class'" in p for p in question_price_problems(dirty, actions["price_classes"], words)))
    dirty = copy.deepcopy(raw)
    dirty["questions"]["halt"][0]["delivery"] = "yes_and_unchanged"
    check("K15 negative control: a delivery value in neither set is found",
          any("neither set" in p for p in question_price_problems(dirty, actions["price_classes"], words)))
    for label, mutate in (("a second top-level key", lambda d: d.update(extra=1)),
                          ("a key with no rows", lambda d: d["questions"].update(halt=[])),
                          ("a row with no `person`", lambda d: d["questions"]["halt"][0].pop("person")),
                          ("one answer twice", lambda d: d["questions"]["halt"].append(dict(d["questions"]["halt"][0])))):
        broken = copy.deepcopy(raw)
        mutate(broken)
        shaped = False
        original = NM.hooklib.read_json
        NM.hooklib.read_json = lambda path, default=None, **kw: broken
        try:
            NM.load_question_prices()
        except NM.DataUnreadable:
            shaped = True
        finally:
            NM.hooklib.read_json = original
        check(f"K15: the loader raises DataUnreadable on {label}", shaped)
    # the answers the code offers, per key, are the data's rows (driven through the real renderers)
    root, task_root, env = seed("QA-9")
    driver = driver_for(root, env, "QA-9")
    offered: dict = {}
    real = NM.priced_options

    def spy(key, options, *args, **kw):
        offered.setdefault(key, set()).update(str(o.get("answer")) for o in options)
        return real(key, options, *args, **kw)
    NM.priced_options = spy
    try:
        digest = "qa-scout S1 all · halt\nR-1 · blocked · why\n"
        driver.halt_text("S2", "qa-requirements-tester", digest)
        (task_root / "work" / "context-manifest.json").write_text(json.dumps({"implementation": {"source": "none"}}), encoding="utf-8")
        driver.halt_text("S1", "qa-scout", digest)
        driver.s1_gap_text("source unavailable and not accepted by a person: SRC-1")
        # C2-9: the kind token (`not_needed_kind`) is offered only when a point with a cause is ASKED - one such source
        (task_root / "work" / "source-inventory.json").write_text(json.dumps({"schema_version": 1, "sources": [{
            "source_id": "SRC-1", "canonical_ref": "https://jira.example.invalid/browse/APP-1", "relation": "referenced",
            "relevance": "relevant", "required": True, "status": "read", "inspection_status": "read", "revision": "r1",
            "human_review": {"words": "ok", "shown": {"relevance": "relevant"}},
            "materials": {"comments": {"status": "read"}, "attachments": {"status": "read", "items": []},
                          "external_media": {"status": "unavailable", "items": [{
                              "url": "https://git.example.com/team/sdk/-/merge_requests/510", "status": "unavailable",
                              "cause": "auth_required", "access_problem": True, "error": "auth_required: 302 to the SSO login"}]}}}]}),
            encoding="utf-8")
        driver.s1_gap_text("source unavailable and not accepted by a person: SRC-1")
        (task_root / "work" / "source-inventory.json").unlink()        # the later questions are raised on the story as it was seeded
        driver.s1_review_text("a digest")
        # the questions that can be raised in this process (flags / stand / readiness are raised inside `s0()` and the package
        # copies need a hook receipt: PINNED_ELSEWHERE names the file that pins each; a row the data lacks shows as a question
        # with no price lines)
        import story_run

        def raised(call, *args):
            try:
                call(*args)
            except story_run.Person:
                pass
        raised(driver.s0_ticket_read_question, 1, "the tracker said no")
        raised(driver.s0_criteria, {"title": "T", "provenance": {"title_from": "first_line"}, "acceptance_criteria": []}, "through the tracker")
        # D-0050: a ticket with NO criteria section no longer asks; a criteria heading with text the reader took nothing from does
        raised(driver.s0_criteria, {"title": "T", "description": "## Acceptance criteria\n\nThe operator can tag an item.",
                                    "acceptance_criteria": []}, "through the tracker")                                  # s0.ticket_incomplete
        raised(driver.s0_criteria, {"title": "","acceptance_criteria": []}, "through the tracker")                   # s0.ticket_no_title
        raised(driver.s0_ticket_auth_question, "the tracker said 401")                                                # s0.ticket_auth
        driver.ticket_auth_person("the tracker said 401")                                                             # fresh.ticket_auth
        driver.ticket_changed_text(["acceptance_criteria"], False)                                                    # fresh.ticket_changed
        driver.state.setdefault("s0_answers", {})["ticket_read"] = "not needed"
        raised(driver.s0_rest_read)                                                                                   # ...not_needed_empty
        driver.state["s0_answers"].pop("ticket_read", None)
        raised(driver.s0_source_list, {"skip_sources": str(root / "no-such-list.txt"), "mr": None})
        conflicting = root / "conflicting-list.txt"
        conflicting.write_text("testproject1-ui!1924 — a draft merge request\n", encoding="utf-8")
        raised(driver.s0_source_list, {"skip_sources": str(conflicting), "mr": "!1924"})
        (task_root / "pipeline.json").write_text(json.dumps({"stages": {}, "run_mode": {
            "mode": "desktop", "plugin_root": str(driver.plugin), "plugin_version": "0", "since": "t"}}), encoding="utf-8")
        raised(driver.check_run_mode)
        (task_root / "work").mkdir(parents=True, exist_ok=True)
        (task_root / "work" / "source-inventory.json").write_text(json.dumps({"schema_version": 1, "sources": []}), encoding="utf-8")
        raised(driver.s0_list_too_late)
        for gate in ("A", "B"):                  # gate_A / gate_B (C1-4b): the options of a gate, priced from the data rows of that name
            driver.gate_prices(gate, ["rework_stage", "approve_gate", "person_does", "stop_here"], {"rework_stages": ["S3", "S4"]})
        # C1-6c: the delivery's questions (`s8.report_match`, `s8.delivery_check`, `s8.delivery.<W2 word>`), driven through the real builders
        driver.report_match_person(["Left with you: 2 items; the report says 1"])
        for word in ("yes", "after_checks", "no"):
            driver.recomputed_word = word
            driver.delivery_person("Delivery needs your word:\n\nthe step asks")
        real_py = driver.py
        driver.py = lambda script, *a, **k: (1, "")                      # a check that crashes: the question and its one defect
        raised(driver.delivery_check_word, "qa-factory/artifacts/QA-9")
        driver.py = real_py
    finally:
        NM.priced_options = real
    for key in sorted(offered):
        check_eq(f"K15: the answers the code offers at `{key}` are the data's ids", sorted(offered[key]),
                 sorted(row["answer"] for row in (raw["questions"].get(key) or [])))
    # the census: EVERY id the code's sites pass (read from the source, so a new site cannot be missed) against the data's keys,
    # both directions; a key driven here is compared by its answers above, a key not drivable here is named with its pinning file
    sites = set()
    for path in sorted((PLUGIN_ROOT / "scripts").glob("*.py")):
        sites |= set(QUESTION_SITE_RE.findall(path.read_text(encoding="utf-8")))
    census = lambda raised, data_keys: census_problems(raised, data_keys, set(offered), AWAITING_ITS_SITE, set(PINNED_ELSEWHERE))
    check_eq("K15: the census - every raised id has its rows and every row its site, both ways",
             census(sites, set(raw["questions"])), [])
    check("K15: the census reads the sites (not an empty scan)", len(sites) >= 16, sorted(sites))
    renamed = copy.deepcopy(raw["questions"])
    renamed["s0.source_list.conflicted"] = renamed.pop("s0.source_list.conflict")
    found = census(sites, set(renamed))
    check("K15 negative control: a renamed row is red in both directions, named",
          any("no row in the data: s0.source_list.conflict" in p for p in found)
          and any("no site raises it" in p and "s0.source_list.conflicted" in p for p in found), found)
    check("K15 negative control: a key the code stops raising is red",
          any("no site raises it" in p and "package.mode" in p for p in census(sites - {"package.mode"}, set(raw["questions"]))))
    check("K15 negative control: an awaiting key the code raises is red",
          any("take it off the list): fresh.ticket_changed" in p
              for p in census_problems(sites, set(raw["questions"]), set(offered), {"fresh.ticket_changed"}, set(PINNED_ELSEWHERE))))
    check("K15: the four keys of node B and `fresh.ticket_changed` are raised, driven here, and have rows (both directions)",
          all(k in sites and k in offered and k in raw["questions"] for k in (
              "s0.ticket_read.not_needed_empty", "s0.ticket_no_title", "s0.ticket_auth", "fresh.ticket_auth", "fresh.ticket_changed")),
          sorted(offered))
    check("K15 negative control (B): a node-B key the code stops raising is red in the census",
          any("no site raises it" in p and "s0.ticket_auth" in p for p in census(sites - {"s0.ticket_auth"}, set(raw["questions"]))))
    # C1-5a (edge 7): the five repair-limit keys load through the one loader with the answers §3.4 / A5 name, and no answer is a move's word
    # (`stop` is the standing token the fallback owns); a sixth key with no site that is not listed above turns the census red.
    loaded = NM.load_question_prices()
    check_eq("K15 (C1-5a): the five repair-limit keys load with exactly their answers",
             {k: [row["answer"] for row in loaded.get(k, [])] for k in REPAIR_LIMIT_KEYS},
             {"s5.repair_limit": ["round", "debt", "fixed", "stop"], "s5.nobody_review": ["review", "debt", "stop"],
              "s5.nobody_environment": ["fixed", "debt", "stop"], "s5.nobody_tooling": ["debt", "stop"],
              "s7.repair_limit": ["round", "debt", "stop"]})
    normalize = lambda token: " ".join(str(token).lower().split())
    reserved = NM.reserved_tokens(actions, normalize)
    check_eq("K15 (C1-5a): no answer of the five keys is a move's word (`stop` is the standing one)",
             sorted({row["answer"] for k in REPAIR_LIMIT_KEYS for row in loaded[k] if row["answer"] != "stop"} & reserved), [])
    check("K15 (C1-5a): their unverified lines are in human terms (no id, no cause token)",
          not any(word in row.get("unverified", "") for k in REPAIR_LIMIT_KEYS for row in loaded[k]
                  for word in ("test_defect", "reviewer_error", "dispatch", "TC-")))
    check("K15 negative control (C1-5a): a sixth key nobody raises and the list does not name is red in the census",
          any("no site raises it" in p and "s5.sixth_key" in p
              for p in census(sites, set(raw["questions"]) | {"s5.sixth_key"})))
    # t-698 §22 FX-2 / §23 (C1-5b2, t-833): the end-of-`open_work` question of S7 - its key is raised by the code (a site passes the literal),
    # pinned by the live file, and loads with exactly `close` / `stop`; `close` is no move's word (a site door), its words carry no id.
    check_eq("K15 (FX-2): `s7.open_work` loads with exactly close / stop, and `close` is no move's word",
             ([row["answer"] for row in loaded.get("s7.open_work", [])], "close" in reserved), (["close", "stop"], False))
    check("K15 (FX-2): `s7.open_work` is raised by a site and named as pinned by the live file (the census, both ways)",
          "s7.open_work" in sites and "s7.open_work" in PINNED_ELSEWHERE and "s7.open_work" in raw["questions"])
    check("K15 negative control (FX-2): `s7.open_work` with no site raising it is red in the census",
          any("no site raises it" in p and "s7.open_work" in p for p in census(sites - {"s7.open_work"}, set(raw["questions"]))))
    check("K15 negative control (FX-2): `s7.open_work` pinned elsewhere but not raised is red",
          any("pinned elsewhere, but the code does not raise it: s7.open_work" in p
              for p in census_problems(sites - {"s7.open_work"}, set(raw["questions"]) - {"s7.open_work"}, set(offered), AWAITING_ITS_SITE,
                                       set(PINNED_ELSEWHERE))))
    check("K15 (FX-2): its unverified line is in human terms (no id, no cause token)",
          not any(word in row.get("unverified", "") for row in loaded["s7.open_work"] for word in ("test_defect", "reviewer_error", "dispatch", "TC-")))
    # C1-6c (A9): the delivery's keys are raised with LITERAL ids (one per verdict word, so the census reads each), driven above, and loaded
    s8_keys = ("s8.report_match", "s8.delivery_check", "s8.delivery.yes", "s8.delivery.after_checks", "s8.delivery.no")
    check("K15 (C1-6c): the five s8 keys are raised by literal ids, driven here, and have rows (both directions)",
          all(k in sites and k in offered and k in raw["questions"] for k in s8_keys), sorted(offered))
    check("K15 negative control (C1-6c): a literal `s8.delivery.after_checks` site that goes missing is red in the census",
          any("no site raises it" in p and "s8.delivery.after_checks" in p
              for p in census(sites - {"s8.delivery.after_checks"}, set(raw["questions"]))))
    by_answer = {k: {row["answer"]: row for row in loaded[k]} for k in s8_keys}
    check_eq("K15 (C1-6c): `go on` carries the W2 word of its key as its story line (never `yes` on after_checks)",
             {k: by_answer[k]["go on"]["delivery"] for k in s8_keys[2:]}, {"s8.delivery.yes": "yes", "s8.delivery.after_checks": "after_checks",
                                                                         "s8.delivery.no": "no"})
    check_eq("K15 (C1-6c): the person line of `go on` is `your_checks` on after_checks only",
             {k: by_answer[k]["go on"]["person"] for k in s8_keys[2:]},
             {"s8.delivery.yes": "none", "s8.delivery.after_checks": "your_checks", "s8.delivery.no": "none"})
    check_eq("K15 (C1-6c): `go on` and `retry` of the delivery cost one more session of the conductor; every `no delivery` row says unchanged",
             ({(k, a): by_answer[k][a]["factory"] for k in s8_keys[2:] for a in ("go on", "retry")},
              {k: by_answer[k]["no delivery"]["delivery"] for k in s8_keys if "no delivery" in by_answer[k]}),
             ({(k, a): "conductor" for k in s8_keys[2:] for a in ("go on", "retry")}, {k: "unchanged" for k in s8_keys}))
    # F11: the class is data; the `price_classes` / `fallback` blocks are otherwise as they were (the re-pinned identity)
    check_eq("K15 (C1-6c, F11): price_classes.factory holds the six old classes and `conductor`, whose text is the spec's",
             (sorted(actions["price_classes"]["factory"]), actions["price_classes"]["factory"]["conductor"]),
             (["command", "conductor", "not_known", "nothing", "record", "role_round", "stages_again"], "one more session of the conductor"))
    check_eq("K15 (C1-6c, F11): the person and delivery classes and the fallback keys are untouched",
             (sorted(actions["price_classes"]["person"]), sorted(actions["price_classes"]["delivery"]), sorted(actions["fallback"])),
             (["answer", "none", "your_checks", "your_work"], ["no_story", "not_known", "unchanged", "waits"], ["go on", "retry", "stop"]))


def the_exit_limit_key_and_the_restart_words() -> None:
    """EL13 (C1-5d2, t-698 §12.2.4): `exit.resume_limit` loads through the one loader with exactly its four answers, none of them a
    move's word (`fresh`, not `restart`: NM.site_check would refuse it), and the `restart` move SAYS the new session gets the person's
    words - true since `_act_relaunch` reads the released dispatch's `released_by_person` for any release (`relaunch_reason`)."""
    import no_move as NM
    actions = json.loads((PLUGIN_ROOT / "references" / "conductor-actions.json").read_text(encoding="utf-8-sig"))
    loaded = NM.load_question_prices()
    check_eq("EL13: exit.resume_limit has exactly round / fresh / go on / stop", [row["answer"] for row in loaded.get("exit.resume_limit", [])],
             ["round", "fresh", "go on", "stop"])
    reserved = NM.reserved_tokens(actions, lambda token: " ".join(str(token).lower().split()))
    check_eq("EL13: its site doors (round, fresh) are no move's word", sorted({"round", "fresh"} & reserved), [])
    check("EL13: `restart` is a move's word, so it could never have been the site door", "restart" in reserved)
    says = NM.move_rows(actions)["release_and_restart"]["says"]
    check("EL13: the `restart` move says the new session gets the person's words", "gets the person's words" in says, says)
    check("EL13 negative control: the old sentence is gone", "does not see the person's words" not in says)
    # t-764 item 5 (Lead decision on the previous worker's question 1): the PRECONDITION of the same row agreed with the old `says`
    # ("the option says that the new session does not see the words") and is as false as that sentence now; the says/precondition census
    # of this row is one: neither text promises that the words stay behind, and the precondition carries the truth in one line.
    row = NM.move_rows(actions)["release_and_restart"]
    pre = str(row["precondition"])
    lies = lambda move: "not see the words" in str(move["precondition"]) and "gets the person's words" in str(move["says"])     # the census scan
    check("EL13/item 5: the precondition no longer says the new session does not see the words", "does not see" not in pre and "not see the words" not in pre, pre)
    check("EL13/item 5: it says the new session gets the person's words, in one line, with no clause about the option",
          "the new session gets the person's words" in pre and "the option says" not in pre and chr(10) not in pre, pre)
    check("EL13/item 5: the says/precondition census of the row is clean (the precondition does not contradict the says)", not lies(row))
    stale = dict(row, precondition="the dispatch is running; the option says that the new session does not see the words")
    check("EL13/item 5 negative control: the same census scan finds the old precondition next to the new says", lies(stale))


def the_conductor_never_records_a_gate_itself() -> None:
    """I6 (C1-4b, H5): conductor.md names `gate-decision` nowhere - not as a command the conductor runs, not among the commands a door
    may carry. The conductor PROPOSES (`approve`, `rework`); the driver records a gate. RED on a tree where t-692's conductor.md has not
    merged yet (the text still lists the command): that is the order of the batch, not a defect of this pin."""
    def names_it(text: str) -> bool:
        return "gate-decision" in text
    text = CONDUCTOR.read_text(encoding="utf-8")
    check("I6: conductor.md names `gate-decision` nowhere as a command the conductor runs", not names_it(text),
          f"{text.count('gate-decision')} occurrence(s)")
    check("I6 negative control: the same check finds it when the command is put back", names_it(text + "\n| a person's words | `gate-decision` |\n"))


def c26_the_rework_option_carries_args_and_a_chosen_call_may_decide() -> None:
    """t-722 C2-6 (§4.2, §4.3, §L-5): the form the conductor answers in names `args` in the places it reads that are data (the role file,
    the `rework_stage` row; the prompt of the driver was a source pin, deleted), and the role file names the one-option answer of a chosen call."""
    text = CONDUCTOR.read_text(encoding="utf-8")
    check_in("C26: conductor.md 'Your answer' names args in the option form", '"args": {"stage", "role", "cases"|"rows", "cause"}', text)
    check_in("C26: conductor.md names the one-option answer of a chosen call (L-5)", "ask_person may carry exactly ONE option", text)
    row = next(m for m in json.loads(ACTIONS.read_text(encoding="utf-8"))["moves"] if m["id"] == "rework_stage")
    check_in("C26: the rework_stage row names args", '"args"', row["run"])
    # the third place, the driver's prompt (`Driver.conductor`), was a source pin of one member: deleted by TD-11 phase 0 (F3)
    import no_move
    check_in("C26: the moves section renders the closed list", '"args" from these values only', no_move.moves_section(
        no_move.data(), ["rework_stage"], {"rework_stages": ["S5"], "rework_roles": {"S5": ["qa-automator"]}, "scope": ["TC-1"], "causes": ["test_defect"]}))


def c27_go_on_as_is_names_the_closed_block() -> None:
    """t-722 C2-7 (F-5d (a)): the `go_on_as_is` row names, word for word, what its `--block` may be - one of the standing refusal's
    lines, whole - and that `waiver.py` refuses any other, so the row and the writer (C2-5) say one thing. The negative control is the
    same scan over the row with the sentence taken out."""
    wanted = "the block: one of the refusal's lines, whole, or a named block such as `probe gap: <case key>`; waiver.py refuses anything else"
    row = next(m for m in json.loads(ACTIONS.read_text(encoding="utf-8"))["moves"] if m["id"] == "go_on_as_is")
    check_in("C27: the go_on_as_is row carries the closed-block sentence, verbatim", wanted, row["run"])
    check_not_in("C27 negative control: the same scan fails on the old `<the block>` row", wanted, row["run"].replace(wanted, "the block"))


def k_n4_2a_the_install_row_exists_and_names_its_check() -> None:
    """K-N4-2a (C3-18, E17/E18): the `actions` row `install_dependencies` has `id`, `says` and `run`; its `run` names the check
    that proves the install (`dependency_drift.py`, `in_sync`) and the no-command / failed-install door; the `says` names no script.
    The negative control is the same scan over the row with the check taken out."""
    data = json.loads(ACTIONS.read_text(encoding="utf-8"))
    row = next((r for r in data["actions"] if r.get("id") == "install_dependencies"), {})
    check("K-N4-2a: the install_dependencies row has id, says and run", all(row.get(k) for k in ("id", "says", "run")))
    check_in("K-N4-2a: its run names dependency_drift.py", "dependency_drift.py", row.get("run", ""))
    check_in("K-N4-2a: its run requires `in_sync` afterwards", "in_sync", row.get("run", ""))
    check_in("K-N4-2a: its run never installs a command the note did not name (E17)", "Never run an install command the note did not name",
             row.get("run", ""))
    check_eq("K-N4-2a: the actions rows pass the says/exclusions scan", actions_problems(data, CONDUCTOR.read_text(encoding="utf-8")), [])
    check_not_in("K-N4-2a negative control: the scan fails on a run with the check taken out", "in_sync",
                 row.get("run", "").replace("dependency_drift.py <project root> --json", "").replace("in_sync", ""))
    problems = command_problems("install_dependencies", row.get("run", ""))
    check_eq("K-N4-2a: the script in its run exists and takes the flags it names", problems, [])


# --- t-1936 F2 (N3): the conductor's own text always reaches the person, even when its options are refused -----------------------------------
# Plain `test_*` functions with asserts (pytest collects them; `f2_run` runs them in the script mode of this file too). The driver rig is
# the seam test's: a stubbed conductor on an in-process Driver.
from story_run_common import seam_option  # noqa: E402
from test_no_move_seam import raised, rig, verdict  # noqa: E402

import harness as _harness  # noqa: E402
import no_move as _NM  # noqa: E402

LIVE_FACTS = {"dispatch_status": "blocked", "session": True, "running": False, "closed": False, "attempts": 0, "rework_stages": [],
              "stand_authorized": False, "live_exclusions": False, "gate": "", "gate_decided": None}
RESUME_OPTIONS = (("resume", "resume_with_words"), ("retry", "person_does"))     # `resume_with_words` is never an option: the set is refused


def refused_person(question, tokens=RESUME_OPTIONS, state=None, answers=None, facts=None, **extra):
    """Drive the seam with a conductor answer whose options are refused; `(person, driver, conductor.jsonl rows)` (the rig is cleaned up)."""
    root, task_root, driver = rig(answers=answers or [verdict(tokens, question=question, **extra)])
    try:
        driver.boundary = "S2:S2-qa-case-critic-1"
        driver.no_move_facts = lambda state: dict(facts or LIVE_FACTS)
        _, person = raised(driver, dict({"why": "refusal", "text": "the details", "lead": "THE LEAD OF THE SITE", "stage": "S2"}, **(state or {})))
        journal = driver.state_dir / "conductor.jsonl"
        return person, driver, ([json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()] if journal.exists() else [])
    finally:
        _harness.cleanup(root)


def test_refused_options_keep_conductor_question() -> None:
    question = "The critic finished with ok, but its form names no tester handoff. How do you want to go on?"
    person, driver, lines = refused_person(question)
    text = person.text
    at = [text.find(part) for part in ("THE LEAD OF THE SITE", "What the conductor found:\n" + question, "## What each answer costs and does")]
    assert min(at) >= 0 and at == sorted(at), (at, text)
    assert list(person.offered) == ["retry", "go on", "stop"] and person.source == "fallback", (person.offered, person.source)
    assert len(driver.defects) == 1 and len([row for row in lines if row.get("action") == "unusable"]) == 1, (driver.defects, lines)
    assert "never an option" in " ".join(driver.defects[0]), driver.defects
    # E2.4: an empty conductor question, or an answer with no options, is today's behaviour: no conductor block
    person, driver, _ = refused_person("")
    assert "What the conductor found:" not in person.text and "THE LEAD OF THE SITE" in person.text, person.text
    person, driver, _ = refused_person(question, answers=[dict(verdict(), options=None, question=question)])
    assert "What the conductor found:" not in person.text and len(driver.defects) == 1, person.text
    # `stop` with refused options is the same: the question reaches the person, the code stays the gave-up one
    person, driver, _ = refused_person(question, answers=[dict(verdict(RESUME_OPTIONS, question=question), action="stop")])
    assert "What the conductor found:\n" + question in person.text and person.code == story_run_exit_gave_up(), person.code


def story_run_exit_gave_up() -> int:
    import story_run
    return story_run.EXIT_GAVE_UP


def test_conductor_text_cut_at_1200() -> None:
    limit = _NM.CONDUCTOR_TEXT_LIMIT
    assert limit == 1200
    for length, cut in ((limit - 1, False), (limit, False), (limit + 1, True), (limit + 300, True)):
        person, _driver, _ = refused_person("x" * length)
        shown = person.text.split("What the conductor found:\n", 1)[1].split("\n\n", 1)[0]
        assert (shown == "x" * length) is (not cut) and len(shown) == min(length, limit), (length, len(shown))
        assert shown.endswith("…") is cut and (not cut or shown == "x" * (limit - 1) + "…"), (length, shown[-3:])
    # E2.7: the token lines are computed on the WHOLE text - a token past the cut is still named as not offered
    person, _driver, _ = refused_person("y" * (limit + 50) + " and then `restart` would free it")
    shown = person.text.split("What the conductor found:\n", 1)[1]
    assert "`restart` would free it" not in shown and "\n`restart` is not offered here: " in shown, shown[-400:]


def test_unoffered_token_named_in_one_line() -> None:
    question = "Restart the critic? `restart` frees it, `restart` again, `retry` looks again, and `ok` was its word."
    person, _driver, _ = refused_person(question, state={"stage": "S2"})
    lines = [line for line in person.text.splitlines() if " is not offered here: " in line]
    assert len(lines) == 1 and lines[0].startswith("`restart` is not offered here: "), lines       # once; `retry` is offered; `ok` is no token
    # the pure half: the reason is the story's state where the move is closed, the generic words where the move is open or unread
    spec, normalize = _NM.data(), story_run_normalize()
    closed = {"rework_stages": [], "running": False, "closed": False, "attempts": 0}
    block, found = _NM.conductor_found("Send it back with `rework`, or `stop`.", ["retry", "stop"], spec, normalize, facts=closed)
    assert found == ["`rework` is not offered here: sending a stage back is not open now: " + _NM.rework_closed_reason(closed)], found
    _, found = _NM.conductor_found("Send it back with `rework`.", ["retry"], spec, normalize, facts=None)
    assert found == [f"`rework` is not offered here: {_NM.UNOFFERED_GENERIC}"], found
    _, found = _NM.conductor_found("Send it back with `rework`.", None, spec, normalize, facts=closed)
    assert found == [], found                                                 # the shown answers unknown: no line is claimed (FR-41)
    assert _NM.conductor_found("   ", ["retry"], spec, normalize) == ("", []), "an empty text adds nothing"


def story_run_normalize():
    import story_run
    return story_run.Driver.s0_normalize


def test_gate_fallback_keeps_conductor_text() -> None:
    question = "Do you approve this gate? I would `go on` past it, or `stop`, but `approve` records nothing without your words."
    person, driver, _ = refused_person(question, state={"kind": "gate_A", "stage": "S4", "why": "unread_answer", "words": "w"},
                                       facts=dict(LIVE_FACTS, gate="A", gate_decided=False))
    assert person.kind == "gate_A", person.kind
    assert "What the conductor found:\n" + question in person.text, person.text
    assert "go on" not in person.offered and list(person.offered) == ["retry", "stop"], person.offered          # E2.5: the added text offers nothing
    lines = [line for line in person.text.splitlines() if " is not offered here: " in line]
    assert "`go on` is not offered here: " + _NM.UNOFFERED_CLOSED in lines, lines              # at a gate the one pass is `approve`
    assert any(line.startswith("`approve` is not offered here: ") for line in lines), lines                       # no words file: approve is not a row
    assert len(driver.defects) == 1, driver.defects


# The arm B run (LOCAL-1, 05.11.2026, state/conductor.jsonl): the conductor asked or stopped 7 times and `validate_options` answered
# `unusable` each time, so the person was shown the generic words. Each row: the first characters of the conductor's `question`
# VERBATIM from that file, its `why_person`, and the options its answer carried, rebuilt from the refusal the file records (`args` on
# `restart` / `go on`, or the token `resume` for `resume_with_words`). The eighth `unusable` line (the conductor cap) has no question.
ARM_B = (
    ("process_decision", "restart", "The S2 critic finished its review with the verdict `ok`, but its form still lists a placeholder instead of the tester's real handoff file (S2-qa-requirements-tester-1.yaml) as an input it read, so the factory won't close S2. I can"),
    ("gate_word", "go on", "The S2 stage critic's second round did not leave a readable verdict. The tester's register has not changed since the critic's first review, which said ok. That review had one non-blocking finding, F-1, and one place not looked at:"),
    ("gate_word", "resume", "The test plan the strategist wrote (S3) is refused on all 20 rows. Each row carries `coverage_schema_version: 2`, but the factory reads `schema_version: 2`, so it counts every row as an old-format row. Nothing else in the plan was"),
    ("team_agreement", "go on", "The S3 plan critic approved the plan (verdict ok, all of R-1..R-14 covered, nothing to ask you). Its handoff form still has an unfilled template question row, which the register refuses, and the factory's fill command can't clear "),
    ("stage_override", "restart", "The case critic approved the S4 cases (10 of 10 reviewed), but its form does not name the case designer's form it reviewed, so the stage cannot be recorded. The designer's form is work/handoffs/S4-qa-case-designer-1.yaml (sha256 c"),
    ("gate_word", "restart", "The test plan for LOCAL-1 was refused at the S3 exit gate. In row TS-6, the new question Q5 has two readings, and each reading's source label doesn't start with an allowed prefix (acceptance_criteria, description, comment, parent_"),
    ("risk", "go on", "The code critic's review of TC_001 and TC_002 (the add-to-cart UI tests) cannot be closed on its own. The tool that probes whether a test really fails when the product is broken could not do it for three tests: the in-stock add te"),
)


def test_arm_b_unusable_lines_reach_the_person() -> None:
    """The replay: every one of the 7 arm B conductor questions reaches the person - as the conductor's own options when the answer is now
    usable (`args` dropped), else verbatim after `What the conductor found:` - and none is replaced by the generic words alone."""
    moves = {"restart": "release_and_restart", "go on": "go_on_as_is", "resume": "resume_with_words"}
    shown_by = {"conductor": 0, "fallback": 0}
    for why_person, bad, question in ARM_B:
        tokens = [(bad, moves[bad])] + [(t, m) for t, m in (("restart", "release_and_restart"), ("go on", "go_on_as_is")) if t != bad] + [("stop", "stop_here")]
        options = [dict(seam_option(token, move), args={"dispatch": "S2-x-1", "stage": "S2"}) if token == bad and bad != "resume" else seam_option(token, move)
                   for token, move in tokens]
        answer = dict(verdict(), question=question, why_person=why_person, options=options)
        person, driver, lines = refused_person(question, answers=[answer, answer])         # twice: a refused class is told to the conductor once
        question = question.strip()                                  # the seam strips a conductor question before it shows it
        assert question in person.text, (why_person, bad, person.text[:300])
        assert not [row for row in lines if row.get("action") == "args_dropped" and bad in ("resume",)], lines
        shown_by[person.source] += 1
        if bad == "resume":
            assert person.source == "fallback" and "What the conductor found:\n" + question in person.text, (bad, person.source)
        elif person.source == "conductor":
            assert bad in person.offered and all("args" not in option for option in person.options), person.options
            assert any(row.get("action") == "args_dropped" and bad in row["args_dropped"] for row in lines), lines
        else:                                               # the class `process_decision` / `stage_override` is no class of person-owned.json: the text still arrives
            assert "What the conductor found:\n" + question in person.text and why_person in ("process_decision", "stage_override"), why_person
    assert sum(shown_by.values()) == len(ARM_B) == 7, shown_by
    # the eighth line is the conductor cap: no answer, so no question - today's priced fallback, no block (E2.4)
    root, task_root, driver = rig()
    try:
        driver.boundary = "S2:S2-qa-case-critic-1"
        driver.conductor_calls[driver.boundary] = __import__("story_run").CONDUCTOR_CALLS_PER_BOUNDARY
        _, person = raised(driver, {"why": "refusal", "text": "t"})
        assert "What the conductor found:" not in person.text and list(person.offered) == ["retry", "go on", "stop"], person.text
    finally:
        _harness.cleanup(root)


F2_DOOR_TESTS = (test_refused_options_keep_conductor_question, test_conductor_text_cut_at_1200, test_unoffered_token_named_in_one_line,
                 test_gate_fallback_keeps_conductor_text, test_arm_b_unusable_lines_reach_the_person)


def f2_run() -> None:
    for scenario in F2_DOOR_TESTS:
        try:
            scenario()
            check(f"F2 {scenario.__name__}", True)
        except AssertionError as exc:
            check(f"F2 {scenario.__name__}", False, str(exc)[:600])


def main() -> None:
    f2_run()
    k_n4_2a_the_install_row_exists_and_names_its_check()
    c27_go_on_as_is_names_the_closed_block()
    c26_the_rework_option_carries_args_and_a_chosen_call_may_decide()
    the_conductor_never_records_a_gate_itself()
    the_question_prices_are_data()
    the_exit_limit_key_and_the_restart_words()
    the_role_rule_replaces_the_old_ban()
    the_moves_are_data_with_existing_commands()
    the_prompts_carry_the_moves_and_the_gate_exclusion()
    the_delivery_rule_replaces_the_delivery_ban()
    the_registered_dispatch_gets_the_whole_reason()
    the_sentence_is_in_how_you_decide()
    the_rule_for_several_doors_is_in_how_you_decide()
    row_38_names_the_three_scope_words()
    the_stage_boundary_row_lists_the_ignore_handoff_door()
    the_size_stays_under_the_cap()
    finish("conductor doors")


if __name__ == "__main__":
    main()
