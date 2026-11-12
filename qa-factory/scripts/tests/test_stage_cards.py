#!/usr/bin/env python3
"""The stage cards in the phase files (speed-cost SC1-8 part A2, release 0.10.3).

TP1-12586: the conductor read the phase files of S0, S1 and S4 whole (76 KB, about 3.3 million token-reads). Each phase file now
opens with a `## Card` (the input, the commands, the config keys, the halts, the exit); `story_step.py card --stage S<n>` prints it.
This test holds the CARDS themselves (the printer is test_story_step_card.py): a card is small, says nothing the file does not
say, reads only config keys the project's config can carry, and points at the next card.

Each check names the ONE mutation it kills:
  one card                    a stage loses its card, gets a second one, or the card is not the file's first section
  size AT/BEYOND              the 4000-byte limit moves (4100), or a card grows past it
  card subset                 a card command that is not spelled in the body of the same file (a drifting twin, AR-19), or is only the
                              first part of a longer one there (a dropped trailing flag) with no `plus` / `with` / `above` on its card line
  bare command                a card command written outside backticks, where the subset check cannot see it
  no template, no work/       a card carries a `prompt: "You are` template (role_permissions reads it) or `work/<delivered file>`
  config keys                 a `config:` key that does not parse, or whose top-level key the project's config cannot carry
  next card                   a stage's exit does not name `card --stage S<n+1>` (S9: the last stage names none)
  no phase read               a body line still tells the conductor to read the next phase file whole
  s1 summary                  the scout's dispatch template drops `--summary` from peek / assess / inspect
  accept door                 a hand-written `--operation accept` text without the `story_step.py finish` door
  NO_CARD shrinks             the exemption list grows, or keeps a stage that has a card
"""
import contextlib
import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import artifact_registry  # noqa: E402
import config_contract  # noqa: E402
import config_view  # noqa: E402
import story_step  # noqa: E402

# The stages that have NO card yet. Shrink-only (AR-20): a stage joins the list only by a named raise in the verdict; S5 leaves it
# the day SC1-14 writes its card (the check below then fails until this line is edited).
NO_CARD = {"S5"}
NO_CARD_BASELINE = {"S5"}

PHASES = story_step.PHASES_DIR
FILES = sorted(PHASES.glob("s[0-9].md"))
STAGES = {path.stem.upper(): path for path in FILES}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def card_span(text: str):
    """The `(first, last)` line span of the file's `## Card` sections (a list; one is the contract)."""
    return [(first, last) for label, first, last in story_step._sections(story_step._lines_of(text)) if label == story_step.CARD_HEADING]


def card_of(text: str) -> str:
    return story_step._card_section(story_step._lines_of(text)) or ""


def rest_of(text: str) -> str:
    """The file without its card: what the card's commands must be spelled in."""
    lines, spans = story_step._lines_of(text), card_span(text)
    if not spans:
        return text
    first, last = spans[0]
    return "\n".join(lines[:first] + lines[last:])


def squash(text: str) -> str:
    """A shell line continuation and every run of blanks are one space: the card spells a command on one line."""
    return re.sub(r"\s+", " ", re.sub(r"\\\s*\n\s*", " ", text)).strip()


PY_COMMAND = re.compile(r'python\s+"\$\{CLAUDE_PLUGIN_ROOT\}/scripts/([a-z_0-9]+)\.py"[^`\n]*')
SPAN_COMMAND = re.compile(r"`(([a-z_0-9]+)\.py\b[^`\n]*)`")
BARE_COMMAND = re.compile(r"^[a-z_0-9]+\.py\b", re.M)


def card_commands(card: str) -> list:
    """Every command a card spells, except the two forms the card machinery itself owns (`story_step.py card ...`, `config_view.py ...`)."""
    found = []
    for match in PY_COMMAND.finditer(card):
        if match.group(1) == "config_view" or (match.group(1) == "story_step" and match.group(0).split('.py"', 1)[1].lstrip().startswith("card")):
            continue
        found.append(match.group(0).rstrip())
    for match in SPAN_COMMAND.finditer(card):
        if match.group(2) == "config_view" or match.group(1).startswith("story_step.py card"):
            continue
        found.append(match.group(1))
    return found


CONTINUES = re.compile(r"^\s+-{1,2}[A-Za-z]")   # the body goes on with a flag right after the card's command
PARTIAL_WORDS = re.compile(r"\b(plus|with|above)\b")   # a card line that says out loud its command is a part of a longer one


def spelled_whole(command: str, body: str) -> bool:
    """True when `command` is in `body` (squashed) at a place where it ENDS: the text after it does not go on with another flag.
    A card that drops a trailing flag (`--role X`) is a prefix of the body's command, not a copy of it."""
    want, start = squash(command), 0
    while True:
        at = body.find(want, start)
        if at < 0:
            return False
        if not CONTINUES.match(body[at + len(want):]):
            return True
        start = at + 1


def commands_missing(card: str, rest: str) -> list:
    """The card's commands the rest of the file does not spell: absent from it, or only the first part of a longer command there
    (unless the card's own line says `plus` / `with` / `above`: three such explicit references are legal today)."""
    body, missing = squash(rest), []
    for command in card_commands(card):
        if squash(command) not in body:
            missing.append(command)
        elif not spelled_whole(command, body) and not PARTIAL_WORDS.search(next((l for l in card.splitlines() if command in l), "")):
            missing.append(command)
    return missing


def config_keys_of(card: str) -> list:
    keys = []
    for line in card.splitlines():
        if line.startswith("config:"):
            keys += [k.strip() for k in line[len("config:"):].split(",") if k.strip()]
    return keys


def key_problem(key: str):
    """None when the key parses and its top-level key is one the project's config can carry; else the reason."""
    try:
        segments, _ = config_view.parse_path(key)
    except config_view.PathSyntax as exc:
        return f"does not parse: {exc}"
    if segments[0] not in config_contract.config_keys()["keys"]:
        return f"top-level key {segments[0]!r} is not in references/config-keys.json"
    return None


NEXT = {f"S{n}": f"S{n + 1}" for n in range(9)}   # the card of S<n> ends by printing the card of S<n+1>; S9 is the last stage

# --- the exemption list only shrinks -------------------------------------------------------------------------------
check("NO_CARD shrinks: it names no stage the baseline does not (a raise is named in the verdict)", NO_CARD <= NO_CARD_BASELINE, str(NO_CARD))
check("the phase files are the ten stages S0..S9", sorted(STAGES) == [f"S{n}" for n in range(10)], str(sorted(STAGES)))
for stage in sorted(NO_CARD):
    check(f"NO_CARD shrinks: {stage} is exempt only while it has no card (remove it from NO_CARD when its card lands)",
          not card_span(read(STAGES[stage])))

# --- one card, first, in every stage that has one (the mutation: a stage loses or doubles its card) -----------------
carded = {stage: path for stage, path in STAGES.items() if stage not in NO_CARD}
sizes = []
for stage, path in sorted(carded.items()):
    text = read(path)
    spans = card_span(text)
    check_eq(f"one card: {stage} has exactly one `## Card`", len(spans), 1)
    labels = [label for label, _, _ in story_step._sections(story_step._lines_of(text)) if label]
    check_eq(f"one card: the card is the first `## ` section of {stage}", labels[:1], ["Card"])
    card = card_of(text)
    size = len(card.encode("utf-8"))
    sizes.append((stage, size, len(path.read_bytes())))

# --- size: AT passes, BEYOND fails, on synthetic text; then every real card -------------------------------------------
def fits(card_text: str) -> bool:
    return len(card_text.encode("utf-8")) <= story_step.CARD_MAX_BYTES


synthetic_at = "## Card\n" + "x" * (4000 - len("## Card\n"))
check("size AT: a card of exactly 4000 bytes passes", len(synthetic_at.encode()) == 4000 and fits(synthetic_at))
check("size BEYOND: a card of 4001 bytes fails", not fits(synthetic_at + "x"))
check("size BEYOND: bytes, not characters (2001 two-byte characters)", not fits("é" * 2001))
check_eq("size: the limit is the spec's 4000", story_step.CARD_MAX_BYTES, 4000)
for stage, size, whole in sizes:
    check(f"size: the {stage} card is {size} bytes, within 4000", size <= 4000, str(size))

# --- card subset: every command of a card is spelled in the body of the same file (AR-19: no drifting twin) --------------
body_with = "\n".join(["# S9 - t", "", "## Card", "x", "", "## Body",
                       'python "${CLAUDE_PLUGIN_ROOT}/scripts/stage_done.py" --task <TICKET> \\', "  --stage S9 --status done", ""])
good_card = 'python "${CLAUDE_PLUGIN_ROOT}/scripts/stage_done.py" --task <TICKET> --stage S9 --status done\nand `log_append.py`'
bad_card = good_card + '\npython "${CLAUDE_PLUGIN_ROOT}/scripts/stage_done.py" --task <TICKET> --stage S9 --status skipped'
span_bad = "a span `controller.py --operation nothing-of-the-kind`"
check_eq("card subset: a command spelled across a line continuation is found", commands_missing(good_card, body_with), ["log_append.py"])
check_eq("card subset: a command the body does not spell is reported (negative control)",
         sorted(commands_missing(bad_card, body_with)),
         sorted(["log_append.py", 'python "${CLAUDE_PLUGIN_ROOT}/scripts/stage_done.py" --task <TICKET> --stage S9 --status skipped']))
check_eq("card subset: a backtick span the body does not spell is reported (negative control)", commands_missing(span_bad, body_with), ["controller.py --operation nothing-of-the-kind"])
check_eq("card subset: the card forms (`story_step.py card`, `config_view.py`) are not checked",
         card_commands('python "${CLAUDE_PLUGIN_ROOT}/scripts/story_step.py" card --stage S2\n`story_step.py card --stage S3` `config_view.py --get x`'), [])
plain_body = "## Body\nstage_done.py --task <TICKET> --stage S9 --status done\n"
truncated = "`stage_done.py --task <TICKET> --stage S9`"   # drops `--status done`, which the body has
check_eq("card subset: a command that drops the body's trailing flag is reported (negative control, A2-F1)",
         commands_missing(truncated, plain_body), ["stage_done.py --task <TICKET> --stage S9"])
check_eq("card subset: ... unless its card line says `plus`, `with` or `above` (an explicit part of a longer command)",
         [commands_missing(truncated + f" {word} the status flag", plain_body) for word in ("plus", "with", "above")], [[], [], []])
check_eq("card subset: the whole command at its end passes (positive control)",
         commands_missing("`stage_done.py --task <TICKET> --stage S9 --status done`", plain_body), [])
check_eq("card subset: the python form is cut the same way", commands_missing(
    'python "${CLAUDE_PLUGIN_ROOT}/scripts/stage_done.py" --task <TICKET> --stage S9', body_with), [
    'python "${CLAUDE_PLUGIN_ROOT}/scripts/stage_done.py" --task <TICKET> --stage S9'])
check("card subset: a bare command line is detectable (so the cards keep every command in backticks or in the python form)",
      bool(BARE_COMMAND.search("stage_done.py --task <TICKET>")) and not BARE_COMMAND.search("see `stage_done.py --task <TICKET>`"))
for stage, path in sorted(carded.items()):
    text = read(path)
    card = card_of(text)
    check_eq(f"card subset: every command of the {stage} card is in the rest of {path.name}", commands_missing(card, rest_of(text)), [])
    check(f"card subset: the {stage} card has commands at all", len(card_commands(card)) >= 1 or stage in ("S0",), str(card_commands(card)))
    check_eq(f"bare command: no {stage} card line starts with a script name outside backticks", BARE_COMMAND.findall(card), [])

s2_text = read(STAGES["S2"])
check("card subset: a real card with one command altered is reported (negative control on a real file)",
      commands_missing(card_of(s2_text).replace("--validate", "--validated"), rest_of(s2_text)) != [])

# --- no dispatch template, no delivered file under work/ -------------------------------------------------------------------
delivered = [name for name, entry in artifact_registry.entries().items()
             if isinstance(entry, dict) and not str(entry.get("path", "")).startswith("work/")]
for stage, path in sorted(carded.items()):
    card = card_of(read(path))
    check_not_in(f'no template: the {stage} card has no `prompt: "You are` (role_permissions reads those)', 'prompt: "You are', card)
    offenders = [name for name in delivered if re.search(r"work/" + re.escape(name), card)]
    check_eq(f"no work/ delivered file: the {stage} card names none under work/", offenders, [])

# --- config keys ---------------------------------------------------------------------------------------------------------
check_eq("config keys: a good dotted key passes", key_problem("adapters.ticket.name"), None)
check("config keys: an empty segment fails (negative control)", key_problem("adapters..name") is not None)
check("config keys: a top-level key the config table lacks fails (negative control)", "not in references/config-keys.json" in (key_problem("no_such_key.x") or ""))
for stage, path in sorted(carded.items()):
    for key in config_keys_of(card_of(read(path))):
        check_eq(f"config keys: {stage} `{key}`", key_problem(key), None)

# --- every stage names the next card; no body line tells the conductor to read the next phase file whole ----------------
for stage, path in sorted(carded.items()):
    text = read(path)
    card = card_of(text)
    want = NEXT.get(stage)
    if want:
        check(f"next card: the {stage} card prints `card --stage {want}`",
              bool(re.search(r'story_step\.py"? card --stage ' + want + r"\b", card)), card[-200:])
    else:
        check(f"next card: the {stage} card is the last stage's and names no next card", "card --stage" not in card)
    reads = re.findall(r"[Rr]ead\s+`?(?:\$\{CLAUDE_SKILL_DIR\}/)?phases/s\d\.md", text)
    check_eq(f"no phase read: {path.name} has no line that reads a phase file whole", reads, [])

# --- the card printed for real, with a project config: the values sit under the line, no 'package defect' note -----------
project = temp_project("qa-stage-cards-")
use_project(project)
try:
    (project / "qa-factory" / "config.json").write_text((harness.PLUGIN_ROOT / "references" / "templates" / "config.json").read_text(encoding="utf-8"),
                                                         encoding="utf-8")
    for stage in sorted(carded):
        out, saved = io.StringIO(), sys.argv
        sys.argv = ["story_step.py", "card", "--stage", stage]
        try:
            with contextlib.redirect_stdout(out):
                code = story_step.main()
        finally:
            sys.argv = saved
        text = out.getvalue()
        check_eq(f"printed: {stage} card exits 0", code, 0)
        check_not_in(f"printed: the {stage} card carries no 'package defect' note", "package defect", text)
        for key in config_keys_of(card_of(read(carded[stage]))):
            check_in(f"printed: the {stage} card prints the value line of `{key}`", f"  {key}: ", text)
finally:
    cleanup(project)

# --- the dispatch template of S1: the scout's card form (brief_pack.TOOLING after SC1-10) ---------------------------------
s1 = read(STAGES["S1"])
template = s1[s1.index('prompt: "You are qa-scout'):]
template = template[:template.index("Return your digest line only.")]
joined = re.sub(r"\n\s+--", " --", template)
for sub in ("peek", "assess", "inspect"):
    line = next((l for l in joined.splitlines() if re.match(rf"\s*A {sub}\b", l)), "")
    check(f"s1 summary: the scout's `{sub}` command ends with --summary", line.rstrip().endswith("--summary"), line)

# --- the manual accept text carries the door the refusal prints ----------------------------------------------------------
for name in ("s1.md", "s2.md", "s8.md"):
    text = read(PHASES / name)
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if "--operation accept" in re.sub(r"\s+", " ", p)]
    check(f"accept door: {name} has a hand-written accept text", len(paragraphs) >= 1)
    for paragraph in paragraphs:
        check(f"accept door: in {name} the paragraph with `--operation accept` names `story_step.py finish`",
              "story_step.py finish" in re.sub(r"\s+", " ", paragraph), paragraph[:80])

# --- the measure (the witness of the spec's section 7): card against phase file ----------------------------------------------
for stage, size, whole in sizes:
    print(f"{stage} card {size} bytes vs phase {whole} bytes")

finish("test_stage_cards")
