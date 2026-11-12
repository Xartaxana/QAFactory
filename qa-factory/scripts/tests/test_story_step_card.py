#!/usr/bin/env python3
"""story_step.py card: the conductor reads a stage card, not the whole phase file (speed-cost SC1-8 part A1, release 0.10.3).

TP1-12586: the phase files of S0, S1 and S4 (76 KB) sat in the conductor's context for the whole run. `card --stage S<n>` prints the
`## Card` section of the stage's phase file, the values of the config keys its `config:` line names and the index of every other section as
a ready `Read <path> offset=<a> limit=<b>`. Edges of the spec (t-1251 section 4) 1-9 are the checks below.

Each check names the ONE mutation it kills:
  no card falls back          a file with no `## Card` prints nothing / raises instead of naming the file whole and its sections
  index covers once           the index drops, duplicates or overlaps a line (or counts a `## ` inside a code fence as a heading)
  size AT/BEYOND              the 4000-byte limit moves, or a card over it is cut / printed with no note
  two cards                   a second `## Card` is shown instead of the first, or passes without a note
  unknown stage               a guessed id (`s1`, `S10`, empty) is accepted, or the refusal names no ids
  missing file                a missing / empty phase file prints an empty card as a card
  config values               the `config:` keys' values are not printed under the line, or an absent key reads as empty
  crlf                        a CRLF file is counted in different lines than `Read` counts
  one slice                   `_stage_card` slices the card text again instead of printing what `_card_section` returns
  fence                       a fence is toggled on any ``` / ~~~ line (4-backtick blocks, ```text closers, mixed characters) so a heading shows or hides wrongly
"""
import argparse
import contextlib
import io
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check_eq, check_in, check_not_in, cleanup, finish, temp_dir, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import grammar  # noqa: E402
import story_step  # noqa: E402

INDEX_RE = re.compile(r"^- (.*): Read (.+) offset=(\d+) limit=(\d+)$")


def run_card(stage: str):
    """`(exit code, stdout)` of `story_step.py card --stage <stage>` in this process."""
    out, saved = io.StringIO(), sys.argv
    sys.argv = ["story_step.py", "card", "--stage", stage]
    try:
        with contextlib.redirect_stdout(out):
            code = story_step.main()
    finally:
        sys.argv = saved
    return code, out.getvalue()


def index_of(text: str) -> list:
    return [(m.group(1), int(m.group(3)), int(m.group(4))) for m in map(INDEX_RE.match, text.splitlines()) if m]


def covered(lines_in_file: int, ranges: list) -> list:
    """How many times each line (1-based) is covered by `(offset, limit)` ranges."""
    seen = [0] * (lines_in_file + 1)
    for offset, limit in ranges:
        for number in range(offset, offset + limit):
            seen[number] += 1
    return seen[1:]


FILE = """# S9 - the title
An intro paragraph.

## Card
Input: the thing.
Commands: `story_step.py start --task <TICKET>`
config: adapters.ticket.name, protected_app_paths, big_value
Exit: next card.

## First section
body one
```
## not a heading, it is inside a fence
```
more of the first

## Second section
body two

# A level-one heading after the sections
text under it

## Third section
body three
"""

tmp = temp_dir("qa-card-phases-")
project = temp_project("qa-card-")
use_project(project)
real_dir = story_step.PHASES_DIR
try:
    story_step.PHASES_DIR = tmp
    (project / "qa-factory" / "config.json").write_text(json.dumps({
        "adapters": {"ticket": {"name": "jira"}}, "big_value": {"rows": ["r" * 50] * 14}}), encoding="utf-8")
    phase = tmp / "s9.md"
    phase.write_text(FILE, encoding="utf-8", newline="\n")
    lines_in_file = len(FILE.splitlines())

    code, out = run_card("S9")
    check_eq("card: exit 0", code, 0)
    check_in("card: the card text is printed", "Commands: `story_step.py start --task <TICKET>`", out)
    check_not_in("card: other sections' bodies are NOT printed", "body one", out)
    check_in("config values: the value of a named key sits under the config line",
             "config: adapters.ticket.name, protected_app_paths, big_value\n  adapters.ticket.name: \"jira\"\n  protected_app_paths: absent (absent_means: ", out)
    check_in("config values: a value over 600 bytes is its shape and the door", "  big_value: object of 1 keys - config_view.py --get big_value", out)
    check_in("config door: another key is asked through config_view", "config_view.py --get PATH", out)
    check_in("card: the phase file's absolute path is printed for the Read", f"Phase file: {phase}", out)

    # --- the index covers every line outside the card exactly once -------------------------------------------
    entries = index_of(out)
    labels = [e[0] for e in entries]
    check_eq("index covers once: the sections in order, the card absent, text outside any section named",
             labels, ["(rest of file)", "First section", "Second section", "(rest of file)", "Third section"])
    card_first, card_last = 4, 9    # lines 4..9 of FILE: `## Card` through the blank line before `## First section`
    seen = covered(lines_in_file, [(o, n) for _, o, n in entries])
    expect = [0 if card_first <= number <= card_last else 1 for number in range(1, lines_in_file + 1)]
    check_eq("index covers once: each line outside the card exactly once, the card's lines never", seen, expect)
    check_eq("index covers once: the sum of limits is the file's lines minus the card's",
             sum(n for _, _, n in entries), lines_in_file - (card_last - card_first + 1))
    check_in("index: a ready Read line", f"- First section: Read {phase} offset=10 limit=", out)
    check_eq("index: a `## ` inside a code fence is not a heading (no section of that name)",
             [l for l in labels if "not a heading" in l], [])

    # --- a file with only the card after its intro -----------------------------------------------------------
    phase.write_text("# S9 - t\nintro\n\n## Card\nconfig:\nthe card\n", encoding="utf-8", newline="\n")
    code, out = run_card("S9")
    entries = index_of(out)
    check_eq("rest of file: one line for the text before the card", [(e[0], e[1], e[2]) for e in entries], [("(rest of file)", 1, 3)])
    check_not_in("empty `config:`: no value lines", "  ", "\n".join(l for l in out.splitlines() if l.startswith("  ")))

    # --- a card with no config line: no values, the door still there ----------------------------------------
    phase.write_text("## Card\nonly text\n\n## Other\nx\n", encoding="utf-8", newline="\n")
    code, out = run_card("S9")
    check_eq("no config line: no indented value line", [l for l in out.splitlines() if l.startswith("  ")], [])

    # --- no card falls back (edge 1) ---------------------------------------------------------------------------
    body = "# S9 - old\nintro\n\n## Part A\na\n\n## Part B\nb\n"
    phase.write_text(body, encoding="utf-8", newline="\n")
    code, out = run_card("S9")
    first = out.splitlines()[0]
    check_eq("no card falls back: exit 0 (never silence)", code, 0)
    check_eq("no card falls back: names the file whole, its bytes and lines",
             first, f"S9 has no card yet: read {phase} whole ({len(body.encode())} bytes, {len(body.splitlines())} lines); or by section:")
    check_eq("no card falls back: the index covers every line once",
             covered(len(body.splitlines()), [(o, n) for _, o, n in index_of(out)]), [1] * len(body.splitlines()))
    phase.write_text("# S9 - only a title\njust text, no `## ` section\nmore\n", encoding="utf-8", newline="\n")
    code, out = run_card("S9")
    check_eq("file with no sections: one `(rest of file)` line for all of it", index_of(out), [("(rest of file)", 1, 3)])

    # --- size AT / BEYOND 4000 (edge 4) ------------------------------------------------------------------------
    def card_of(size: int) -> str:
        return "## Card\n" + "x" * (size - len("## Card\n")) + "\n\n## Other\ny\n"

    phase.write_text(card_of(story_step.CARD_MAX_BYTES), encoding="utf-8", newline="\n")
    code, out = run_card("S9")
    check_eq("size AT 4000: no defect note", "a package defect" in out, False)
    phase.write_text(card_of(story_step.CARD_MAX_BYTES + 1), encoding="utf-8", newline="\n")
    code, out = run_card("S9")
    check_eq("size BEYOND (4001): the card is printed whole and the note names the defect",
             (("x" * 3990) in out, "note: the S9 card is 4001 bytes, over 4000: a package defect" in out), (True, True))
    check_eq("size: the constant is the spec's 4000", story_step.CARD_MAX_BYTES, 4000)
    phase.write_text("## Card\n" + "é" * 2000 + "\n", encoding="utf-8", newline="\n")   # 2008 characters, 4008 bytes
    code, out = run_card("S9")
    check_in("size counts UTF-8 bytes, not characters", "note: the S9 card is 4008 bytes, over 4000", out)

    # --- two cards (edge 6) ------------------------------------------------------------------------------------
    phase.write_text("## Card\nfirst card\n\n## Mid\nm\n\n## Card\nsecond card\n", encoding="utf-8", newline="\n")
    code, out = run_card("S9")
    check_eq("two cards: the first is shown, the second is not, and a note says so",
             ("first card" in out, "second card" in out, "has 2 `## Card` sections; the first one is shown" in out), (True, False, True))
    check_eq("two cards: the second stays reachable in the index", [e[0] for e in index_of(out)], ["Mid", "Card"])

    # --- CRLF counted as Read counts it ------------------------------------------------------------------------
    phase.write_bytes(FILE.replace("\n", "\r\n").encode("utf-8"))
    code, out = run_card("S9")
    check_eq("crlf: the same offsets and limits as the LF file", index_of(out)[1:3], [("First section", 10, 7), ("Second section", 17, 3)])

    # --- one slice of the card text: `_stage_card` prints and counts what `_card_section` returns (A1-F3) -----------------------
    phase.write_text(FILE, encoding="utf-8", newline="\n")
    real_section = story_step._card_section
    story_step._card_section = lambda lines: "## Card\nPATCHED-CARD-TEXT"
    try:
        code, out = run_card("S9")
    finally:
        story_step._card_section = real_section
    check_eq("one slice: the printed card is what _card_section returns (no second slicing in _stage_card)",
             ("PATCHED-CARD-TEXT" in out, "Commands: `story_step.py start" in out), (True, False))

    # --- a fence is read as CommonMark, as grammar.heading_lines reads it (A1-F7) ---------------------------------------------
    def labels_of(text: str) -> list:
        phase.write_text(text, encoding="utf-8", newline="\n")
        return [label for label, _, _ in story_step._sections(story_step._lines_of(text)) if label]

    check_eq("fence: a 4-backtick block holding ``` lines keeps its `## ` lines inside",
             labels_of("## Card\nc\n\n## A\n````\n```\n## inside one\n```\n## inside two\n````\n## B\nb\n"), ["Card", "A", "B"])
    check_eq("fence: ```text is an opener, not a closer (a closer has no info string)",
             labels_of("## Card\nc\n\n## A\n```\ncode\n```text\n## inside\n```\n## B\nb\n"), ["Card", "A", "B"])
    check_eq("fence: ~~~ fences hide headings and are closed by ~~~ only",
             labels_of("## Card\nc\n\n## A\n~~~\n```\n## inside\n~~~\n## B\nb\n"), ["Card", "A", "B"])
    check_eq("fence: a fence opened and never closed hides the rest (as the other reader reads it)",
             labels_of("## Card\nc\n\n## A\n```\n## inside\n"), ["Card", "A"])

    # --- refusals (edges 2, 3) --------------------------------------------------------------------------------
    for wrong in ("s1", "S10", ""):
        code, out = run_card(wrong)
        check_eq(f"unknown stage {wrong!r}: exit 2", code, 2)
    check_in("unknown stage: the ids are listed", "the ids are S0, S1, S2", out)
    phase.unlink()
    code, out = run_card("S9")
    check_eq("missing file: exit 2, not an empty card", code, 2)
    check_in("missing file: says it and the door", "phases/s9.md of the plugin is missing or unreadable", out)
    check_in("missing file: reinstall", "reinstall the plugin", out)
    phase.write_text("", encoding="utf-8")
    code, out = run_card("S9")
    check_eq("empty phase file: exit 2", code, 2)
    check_in("empty phase file: said", "phases/s9.md of the plugin is empty", out)

    # --- config unknown: no config / unreadable -------------------------------------------------------------
    phase.write_text("## Card\nconfig: app_root\n", encoding="utf-8", newline="\n")
    (project / "qa-factory" / "config.json").write_text("{broken", encoding="utf-8")
    code, out = run_card("S9")
    check_in("config unreadable: one line, not an empty value", "  qa-factory/config.json is unreadable", out)
    (project / "qa-factory" / "config.json").unlink()
    code, out = run_card("S9")
    check_in("no config (S0 before onboarding): the onboarding door, the card still prints", "  no qa-factory/config.json - run /qa-factory:qa-onboarding", out)

    # --- `where` points at the card (the Lead's decision on t-1324): the LAST line, only when the action names a stage ----------
    from controller import Controller
    (project / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")   # the no-config rows above removed the marker
    story =project / "qa-factory" / "artifacts" / "TP3-1"
    story.mkdir(parents=True)
    Controller(story).apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1",
                                           "known_paths": {"root": str(story)}, "idempotency_key": "init"})

    def where_with(action: dict) -> list:
        real_next, out = story_step._next, io.StringIO()
        story_step._next = lambda controller, read_only=False: action
        try:
            with contextlib.redirect_stdout(out):
                story_step.where(argparse.Namespace(task="TP3-1"))
        finally:
            story_step._next = real_next
        return out.getvalue().splitlines()

    lines = where_with({"action": "prepare_stage", "stage": "S3", "revision": 4})
    check_eq("where card pointer: the last line, for the stage of the action", lines[-1], "stage card: story_step.py card --stage S3")
    check_eq("where card pointer: `next:` stays the first line, the judge's line stays before the pointer",
             (lines[0].startswith("next: "), lines[-2].startswith("judge:")), (True, True))
    lines = where_with({"action": "stop", "reason": "gate_A"})
    check_eq("where card pointer: an action with no stage gets no pointer", [l for l in lines if l.startswith("stage card:")], [])

    # --- the real phase files: the control for the synthetic ones ----------------------------------------------
    story_step.PHASES_DIR = real_dir
    for stage_id in story_step._stages():
        path = real_dir / f"{stage_id.lower()}.md"
        if not path.is_file():
            continue
        code, out = run_card(stage_id)
        total = len(story_step._lines_of(path.read_bytes().decode("utf-8-sig")))
        card_span = [(f, l) for label, f, l in story_step._sections(story_step._lines_of(path.read_bytes().decode("utf-8-sig")))
                     if label == "Card"]
        expect = [0 if card_span and card_span[0][0] < number <= card_span[0][1] else 1 for number in range(1, total + 1)]
        check_eq(f"real {stage_id}: exit 0 and every line outside the card indexed exactly once",
                 (code, covered(total, [(o, n) for _, o, n in index_of(out)])), (0, expect))
        text = path.read_bytes().decode("utf-8-sig")
        check_eq(f"real {stage_id}: the `## ` sections are the headings grammar.heading_lines finds (same fence reading)",
                 [label for label, _, _ in story_step._sections(story_step._lines_of(text)) if label],
                 [heading[3:].strip() for heading in grammar.heading_lines(text)])
        label = "card" if card_span else "no card yet"
        print(f"  measure: {stage_id} {label}: phase file {path.stat().st_size} bytes, printed {len(out.encode('utf-8'))} bytes")

    # --- the command needs no story and no project (S0's card is read first) ---------------------------------
    bare = temp_dir("qa-card-bare-")
    r = harness.run_script("story_step.py", "card", "--stage", "S0", cwd=bare, env={**os.environ, "CLAUDE_PROJECT_DIR": str(bare)})
    check_eq("cli, no project: exit 0 and the stage is named", (r.returncode, "S0" in r.stdout), (0, True))
    cleanup(bare)
finally:
    story_step.PHASES_DIR = real_dir
    cleanup(tmp)
    cleanup(project)

finish("test_story_step_card")
