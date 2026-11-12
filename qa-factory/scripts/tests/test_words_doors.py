#!/usr/bin/env python3
"""Every door that carries a person's words names the FILE form (legacy-2406 wave 3, node W3-D-A).

W3-W1 made a person's words travel by file (`--words-file`, one reader: `person_words.read`),
because cmd.exe stops a command line at its first line break and an inline answer is recorded
cut (M30). About 45 refusals, hints and docs still told the orchestrator to pass the words inline
(`waiver.py ... --decision "<their words>"`): a door contradicting the rule the roles read (FR-37),
a second mechanism for one job (FR-17). This is the class fix: ONE renderer
(`person_words.door`), ONE detector (here), and a door-opening test per refusal a program prints.

  (a) the detector greps for the PROBLEM (an inline words part after a recording command), over
      the string constants of `scripts/*.py` and over the text of skills / references / design /
      handoffs / agents. Sites that belong to other open nodes are in PENDING: a hit there is
      printed, not failed; a pending file found clean says "clean now: remove <path>".
  (b) FR-2: every refusal a program prints is produced from the REAL code, the command is taken
      out of the printed backtick span (never retyped), only named placeholders are filled, the
      REAL CLI is run, and the refusing code then no longer refuses.
  (c) a story in flight: overrides recorded under the keywords the OLD texts advised still pass
      the new texts.
  (d) Windows only: one door through the real launcher (hooks/run-py.cmd).
"""
import ast
import io
import json
import os
import re
import shlex
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (PLUGIN_ROOT, SCRIPTS, check, check_eq, check_in, check_not_in,  # noqa: E402
                     cleanup, driver_sources, finish, run_script, s5_apply, temp_dir, temp_project, use_project)

sys.path.insert(0, str(SCRIPTS))
import person_words  # noqa: E402
import refusal_registry as RR  # noqa: E402
import stage_done  # noqa: E402
import stage_guard  # noqa: E402
import waiver  # noqa: E402

import test_gate_preflight as GP  # noqa: E402
import test_obligation_join as OJ  # noqa: E402
import test_s0_close_order as S0  # noqa: E402

WIN = os.name == "nt"
LAUNCHER = PLUGIN_ROOT / "hooks" / "run-py.cmd"
FLAG = "--words-file"
WORDS = "Go on.\n\nKeep it local - \"do not publish\" to Jira.\n"

# --- (a) the detector --------------------------------------------------------------------------

# The recording commands, then up to 300 characters of the same command (no backtick or bare pipe,
# so one command in one markdown span or table cell; an ESCAPED pipe `\|` is a character of the
# command - a table cell cannot hold a bare one, and `--gate A\|B` hid the door behind it), then a
# words option whose value is typed on the line: a quote, a backslash-quote (yaml / json) or a
# `<placeholder>`.
INLINE_DOOR = re.compile(
    r'''(waiver\.py|gate-decision|--operation release|archive_task\.py|project_decisions\.py'''
    r'''|accept-gap|review --record|onboarding_notes\.py|story_step\.py decide)(?:\\\||[^`|]){0,300}?\s(--decision|--words|--text|--note)\s+\\?["'<]''')

# Inline doors of upstream 0.8.1 that the merge brought in and that are queued, not converted
# (B-387 names the doors listed here; B-365 names two other carriers, `stand_identity --words` and
# `source_exclusions --revoke --words`, which the scan's command list does not read). A pending
# file lists the EXACT texts the scan matched there: a hit that
# is not one of them - a NEW inline door in the same file - still fails. The node that lands the
# file form removes its entry; a file found clean says so below. `gate_preflight.py` and
# `stand_gaps.py` are not here: their cards are upstream's renderer now (a person answers
# `<id>: <word>`, no script), and the scan finds nothing in them.
PENDING_REASON = "upstream 0.8.1 door, queued B-387"
DRIVER_KEY = "scripts/story_run.py"  # the one key of the whole driver set (the entry file and its driver_*.py parts)
PENDING = {
    # The remedy of a tracker route that is not proven: upstream's text, kept by decision (spec
    # t-428: the readiness texts name no script of ours, so ours' `door(..., for_person=True)` is
    # not carried).
    "scripts/readiness.py": ('waiver.py --stage S1 --block "tracker route" --decision "',),
    # The driver's own texts, upstream's, shown to a person or put to the conductor: the note about a
    # stand-gap line it could not read; the mode-switch question (`{self.scripts / 'waiver.py'}` is read
    # as `waiver.py`: `_placeholder`, the blind spot of the first version); the two stand questions.
    DRIVER_KEY: ('waiver.py --task <T> --stage <stage> --block "<block>" --decision "',
                             'waiver.py" --task {} --stage {} --block "mode switch" --decision "',
                             ),      # C1-6b took off the two stand questions: their free-words prompts hand the words by `--words-file`
    "skills/qa-story/phases/s5.md": ('waiver.py --task <TICKET> --stage S5 --block "stand not confirmed" --decision "',),
    # Two doors that were converted to the file form and are back to upstream's inline text, because an
    # upstream test pins that text: the S9 report-check door (test_story_closed.py) and the mode-switch
    # door of `run_mode_refusal` (test_package_generation.py). The matched text is as the scan renders it
    # (`{}` for a formatted value; the second one keeps the quote that closes the script's path).
    "scripts/stage_done.py": ('waiver.py --task {} --stage S9 --block "{}" --decision "',),
    "scripts/story_step.py": ('waiver.py" --task {} --stage {} --block "{}" --decision "',),
}
# Entries whose reason is not the default one.
PENDING_PINNED = ("scripts/stage_done.py", "scripts/story_step.py")
PENDING_PINNED_REASON = "upstream 0.8.1 door pinned by an upstream test, queued B-387"
# A NAMED exemption, not a finding: the driver records a person's words by calling `waiver.py` itself
# with a LIST argv (no shell, so no cmd.exe cut at the first line break) and the words as one argument;
# the scan reads string constants and cannot see such a call, so `driver_inline_calls` finds them
# and the check below fails if the exemption no longer names one (a stale exemption is a lie).
# `waiver.py` and `person_words.read` keep accepting an inline `--decision` for them (spec t-428 L5).
EXEMPT = {
    DRIVER_KEY: "upstream's driver waiver calls: list argv, no shell, one card line (the "
                            "`take_stand_gap_answers` family)",
}
DOC_DIRS = ("skills", "references", "design", "handoffs", "agents")
DOC_SUFFIXES = (".md", ".yaml", ".yml", ".json")


# The same problem written as prose, with the option named and no value shown (`--words`,
# `... --gate A --words with their words`): the shape the evals and a conductor table use. The
# lookahead keeps `--words-file` out; the same command stretch rule applies.
BARE_DOOR = re.compile(
    r'''(waiver\.py|gate-decision|--operation release|archive_task\.py|project_decisions\.py'''
    r'''|accept-gap|review --record|onboarding_notes\.py|story_step\.py decide)(?:\\\||[^`|]){0,300}?\s(--decision|--words|--text|--note)(?![-\w])''')


def normalised(text: str) -> str:
    return " ".join(text.split())


def hits_in(text: str) -> list:
    """The inline doors in one text, whitespace-normalised: each as the matched excerpt. A value
    typed on the line first; then a bare option name that no such hit already covers."""
    flat = normalised(text)
    quoted = list(INLINE_DOOR.finditer(flat))
    found = [match.group(0) for match in quoted]
    for match in BARE_DOOR.finditer(flat):
        if not any(hit.start() <= match.start() < hit.end() for hit in quoted):
            found.append(match.group(0))
    return found


SCRIPT_NAME = re.compile(r"[A-Za-z_][\w-]*\.py")


def _placeholder(part) -> str:
    """An f-string placeholder as `{}`, except one whose expression NAMES a script
    (`{self.scripts / 'waiver.py'}`): that is the command's own word, so it is kept as the script's
    basename. Rendered `{}`, the command vanished from the text and the door behind it was never read
    (the mode-switch door of the driver, which a person sees, was missed that way)."""
    try:
        source = ast.unparse(part.value if isinstance(part, ast.FormattedValue) else part)
    except Exception:  # noqa: BLE001 - an expression that cannot be unparsed is a plain placeholder
        return "{}"
    named = SCRIPT_NAME.search(source)
    return named.group(0) if named else "{}"


def _render(node):
    """A string constant, an f-string (every `{...}` as `{}`), or a `+` chain of them; else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(part.value if isinstance(part, ast.Constant) else _placeholder(part) for part in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _render(node.left), _render(node.right)
        if left is None and right is None:
            return None
        return ("{}" if left is None else left) + ("{}" if right is None else right)
    return None


def _strings(node, skip: set, out: list) -> None:
    if id(node) in skip:
        return
    text = _render(node)
    if text is not None:
        out.append(text)
        return
    for child in ast.iter_child_nodes(node):
        _strings(child, skip, out)


def python_texts(source: str) -> list:
    """The checked strings of one script. Skipped: an `add_argument` help (the CLI documents its
    own inline option beside the file form), the arguments of `.error(` (an argparse refusal
    names both options), and the module docstring of a CLI that itself names `--words-file`."""
    tree = ast.parse(source)
    skip: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "add_argument":
                skip.update(id(kw.value) for kw in node.keywords if kw.arg == "help")
            elif node.func.attr == "error":
                skip.update(id(arg) for arg in node.args)
    first = tree.body[0] if tree.body else None
    if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str) and FLAG in first.value.value):
        skip.add(id(first.value))
    out: list = []
    _strings(tree, skip, out)
    return out


def script_units(plugin_root: Path) -> list:
    """[(key, text)] of every script the inventory reads. The files of the driver set (`harness.driver_sources`) all
    carry the one key DRIVER_KEY, so a door that moves between the driver's parts keeps its entry."""
    in_driver = {path: text for path, text in driver_sources(plugin_root)}
    units = [(DRIVER_KEY, text) for text in in_driver.values()]
    for path in sorted((plugin_root / "scripts").glob("*.py")):
        if path in in_driver or path.name == "person_words.py":
            continue  # person_words: the reader and the renderer, they name the inline option to refuse it
        units.append((path.relative_to(plugin_root).as_posix(), path.read_text(encoding="utf-8")))
    return units


def scan(plugin_root: Path = PLUGIN_ROOT) -> dict:
    """{path relative to the package: [inline doors found]} over everything the detector reads."""
    found: dict = {}
    for key, source in script_units(plugin_root):
        try:
            texts = python_texts(source)
        except SyntaxError:
            continue  # another builder's unfinished edit: the syntax error is that node's to report
        hits = [hit for text in texts for hit in hits_in(text)]
        if hits:
            found.setdefault(key, []).extend(hits)
    for directory in DOC_DIRS:
        for path in sorted((plugin_root / directory).rglob("*")):
            if path.is_file() and path.suffix in DOC_SUFFIXES:
                hits = hits_in(path.read_text(encoding="utf-8", errors="replace"))
                if hits:
                    found[path.relative_to(plugin_root).as_posix()] = hits
    return found


def unlisted_of(found: dict) -> dict:
    """The hits that are neither in a pending file's own list of matched texts nor exempt by name."""
    out = {}
    for path, hits in found.items():
        listed = PENDING.get(path, ())
        rest = [hit for hit in hits if hit not in listed]
        if rest:
            out[path] = rest
    return out


def _is_door_call(node) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "door"
    return (isinstance(func, ast.Attribute) and func.attr == "door"
            and isinstance(func.value, ast.Name) and func.value.id in ("person_words", "PW"))


def converted_doors(plugin_root: Path = PLUGIN_ROOT) -> dict:
    """{script: number of `person_words.door()` calls}: the doors that ARE in the file form. The scan
    finds only the problem, so this is its positive control: a scan that finds nothing is read
    together with the files that were converted."""
    out: dict = {}
    for key, source in script_units(plugin_root):
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        count = sum(1 for node in ast.walk(tree) if _is_door_call(node))
        if count:
            out[key] = out.get(key, 0) + count
    return out


def driver_inline_calls(plugin_root: Path = PLUGIN_ROOT) -> list:
    """The `file:line` of the calls `X("waiver.py", ..., "--decision", value, ...)` in the driver set (`harness.driver_sources`): a
    list argv with the words as one argument (the named exemption)."""
    lines = []
    for path, text in driver_sources(plugin_root):
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Call):
                consts = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
                if consts[:1] == ["waiver.py"] and "--decision" in consts:
                    lines.append(f"{path.name}:{node.lineno}")
    return sorted(lines)


def part_detector() -> None:
    inline = 'waiver.py --task T --stage S1 --block "x" --decision "<their words>"'
    check("negative control: the inline door is a hit", len(hits_in(inline)) == 1, str(hits_in(inline)))
    file_form = 'waiver.py --task T --stage S1 --block "x" --words-file <file>'
    check_eq("and the same door with --words-file is not", hits_in(file_form), [])
    check("a markdown line broken across two lines is still one door",
          len(hits_in('`waiver.py --task T --stage S1 --block "x" --decision\n"<their words>"`')) == 1)
    check("a yaml / json escaped quote is read",
          len(hits_in('recorded_by: "waiver.py --task <T> --block \\"k\\" --decision \\"<words>\\""')) == 1)
    check_eq("a bare option name (prose, no value shown) is a hit; the file option is not",
             [len(hits_in(text)) for text in ("`controller.py --operation release --dispatch S3-x --words (or ...)`",
                                              "`controller.py --operation release --dispatch S3-x --words-file <file>`")],
             [1, 0])
    check("a gate-decision door is a hit",
          len(hits_in("`controller.py --operation gate-decision --gate A --words \"<their words>\"`")) == 1)
    # B-411 A9: the notes CLI records a person's words (`answer`), so it is on the detector's closed command lists
    check("A9: an inline words option on onboarding_notes.py answer is a hit (the command is on the detector's list)",
          len(hits_in('onboarding_notes.py --root . answer --batch b1 --answered t1 --words "<their words>"')) == 1)
    check_eq("A9: the file form of the same door is not a hit",
             hits_in(f'onboarding_notes.py --root . answer --batch b1 --answered t1 {FLAG} <file>'), [])
    check_eq("A9: a bare option name in prose on that command is a hit too",
             len(hits_in("`onboarding_notes.py --root . answer --batch b1 --words (their words)`")), 1)
    # t-721 D4/T-door: `story_step.py decide` records a person's decision and takes its words ONLY by file
    check("decide: an inline words option on story_step.py decide is a hit (the command is on the detector's list)",
          len(hits_in('story_step.py decide --task T --dispatch-id D --hand TC-1 --words "<their words>"')) == 1)
    check_eq("decide: the file form of the same door is not a hit",
             hits_in(f'story_step.py decide --task T --dispatch-id D --hand TC-1 {FLAG} <file>'), [])
    decide_source = (PLUGIN_ROOT / "scripts" / "story_step.py").read_text(encoding="utf-8")
    import re as _re

    def decide_reads_by_file_only(source: str) -> bool:
        """The one search, run over a source text: `decide` reads through `person_words.read` from `--words-file`, names no
        inline `args.words`, and the parser has no inline `--words` option."""
        body = _re.search(r"\ndef decide\(.*?\n\n\n", source, _re.S)
        return (bool(body) and "person_words.read(None, args.words_file," in body.group(0)
                and "args.words," not in body.group(0) and 'add_argument("--words"' not in source)
    check("decide: the words come through the one reader, person_words.read, from --words-file (and no inline option)",
          decide_reads_by_file_only(decide_source))
    # t-827 FX-4: the control is the SAME search over a mutated copy of the real source (the reader switched to the inline
    # option), which must fail - and a copy that grew the inline parser option must fail too
    inline_reader = decide_source.replace("person_words.read(None, args.words_file,", "person_words.read(args.words, None,")
    check("decide: negative control - the mutation applied to the source text (exactly one reader call)",
          decide_source.count("person_words.read(None, args.words_file,") == 1 and inline_reader != decide_source)
    check_eq("decide: negative control - the same search over a copy that reads inline words fails",
             decide_reads_by_file_only(inline_reader), False)
    inline_option = decide_source.replace('p.add_argument("--words-file"', 'p.add_argument("--words")\n    p.add_argument("--words-file"')
    check_eq("decide: negative control - the same search over a copy with an inline `--words` parser option fails",
             (inline_option != decide_source, decide_reads_by_file_only(inline_option)), (True, False))
    check_eq("a bare `--text` of another command is not a door",
          hits_in('judge_reply.py --reply "<their words>" --text "x"'), [])
    # A markdown table cell writes the pipe inside it as `\|` (`--gate A\|B`): the escaped pipe is
    # still the same command, and the stretch rule used to stop there, hiding the door behind it.
    # The line is the one conductor.md carried before the file form (git HEAD of 2026-10-03).
    table_inline = ("| A person's words for gate A or B | `controller.py --task-root <task root> --operation "
                    "gate-decision --gate A\\|B --words \"<their words, verbatim>\"` (`--drafts <ref,ref>` at B "
                    "for the bug drafts they chose by number, taken from the gate message) |")
    table_file = table_inline.replace('--words "<their words, verbatim>"', f"{FLAG} <file>")
    check_eq("an escaped table pipe does not hide an inline door (the conductor.md gate-decision line)",
             len(hits_in(table_inline)), 1)
    check_eq("and the same line in the file form is not a hit", hits_in(table_file), [])
    check_eq("a bare option name behind an escaped pipe is a hit too",
             len(hits_in("`controller.py --operation gate-decision --gate A\\|B --words (their words)`")), 1)
    check_eq("an unescaped pipe still ends the command's stretch",
             hits_in("`controller.py --operation gate-decision --gate A` | `x --words \"<w>\"`"), [])
    check("a python string constant is read, an f-string with `{}` too",
          len([h for t in python_texts('x = f"waiver.py --task {t} --stage S --block \\"k\\" --decision \\"<w>\\""')
               for h in hits_in(t)]) == 1)
    # A door whose script path is a placeholder (`{self.scripts / 'waiver.py'}`) was rendered `{}`, so the
    # command word was gone and the door behind it was never read (the driver's mode-switch door).
    quote = chr(92) + '"'
    placed = ("x = f\"python {self.scripts / 'waiver.py'} --task {t} --stage S1 --decision " + quote
              + "<your words>" + quote + "\"\n")
    check_eq("a placeholder that names the script keeps its name, so the inline door behind it is a hit",
             [len(hits_in(t)) for t in python_texts(placed)], [1])
    check_eq("...the same door in the file form is not a hit",
             [len(hits_in(t)) for t in python_texts(
                 "x = f\"python {self.scripts / 'waiver.py'} --task {t} --words-file <file>\"\n")], [0])
    check_eq("...and a placeholder that names no script stays a plain `{}`",
             python_texts("x = f\"python {path} --task {t}\"\n"), ["python {} --task {}"])
    check_eq("an add_argument help and an .error( argument are skipped",
             [h for t in python_texts(
                 'ap.add_argument("--x", help=\'waiver.py --block k --decision "<w>"\')\n'
                 'ap.error(\'waiver.py --block k --decision "<w>"\')\n') for h in hits_in(t)], [])
    check_eq("a CLI docstring that also names --words-file is skipped, another one is not",
             [len([h for t in python_texts(f'"""{extra}waiver.py --block k --decision "<w>"\n"""\n')
                   for h in hits_in(t)]) for extra in (f"{FLAG} <f> ", "")], [0, 1])

    # The negative control of the whole scan, on a synthetic package: an inline door in a script, in
    # a document and in a pending file (a text that is not the listed one) is unlisted; a door in
    # the file form, the listed text of a pending file and a door built by `door()` are not.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        fake = Path(tmp)
        (fake / "scripts").mkdir()
        (fake / "skills").mkdir()
        (fake / "scripts" / "new_door.py").write_text(
            'MSG = \'waiver.py --task T --stage S1 --block "x" --decision "<their words>"\'\n', encoding="utf-8")
        (fake / "scripts" / "story_run.py").write_text(
            'A = \'' + PENDING[DRIVER_KEY][0] + '<w>"\'\n'
            'B = \'waiver.py --task T --stage S2 --block "other" --decision "<w>"\'\n', encoding="utf-8")
        (fake / "scripts" / "file_form.py").write_text(
            'import person_words\nMSG = person_words.door(\'waiver.py --task T --stage S1 --block "x"\')\n'
            'FILE = \'waiver.py --task T --stage S1 --block "x" --words-file <file>\'\n', encoding="utf-8")
        (fake / "skills" / "s.md").write_text(
            '`waiver.py --task <T> --stage S1 --block "x" --decision "<their words>"`\n', encoding="utf-8")
        synthetic = scan(fake)
        check_eq("negative control: a synthetic package is scanned (script, pending file, document; not the file form)",
                 sorted(synthetic), ["scripts/new_door.py", DRIVER_KEY, "skills/s.md"])
        check_eq("negative control: an inline door in a new script and a new document is unlisted",
                 sorted(path for path in unlisted_of(synthetic) if path != DRIVER_KEY),
                 ["scripts/new_door.py", "skills/s.md"])
        check_eq("negative control: a pending file lists its own text only; a NEW door in it is unlisted",
                 ["other" in hit for hit in unlisted_of(synthetic).get(DRIVER_KEY, [])],
                 [True])

    found = scan()
    unlisted = unlisted_of(found)
    check("positive control: the scan read the package (it found the pending doors, so an empty "
          "`unlisted` is not an empty scan)", sum(len(hits) for hits in found.values()) >= len(PENDING), str(sorted(found)))
    converted = converted_doors()
    # `story_step.py` is not here: its mode-switch door is upstream's inline text again (pending above).
    expected = ("controller.py", "manifest_put.py", "stage_done.py", "story_run.py")
    check_eq("positive control: the files whose doors were converted call person_words.door()",
             [name for name in expected if f"scripts/{name}" not in converted], [])
    check("the doors in the file form are listed: " + ", ".join(f"{p.split('/')[-1]} {n}" for p, n in sorted(converted.items())),
          len(converted) >= len(expected), str(converted))
    calls = driver_inline_calls()
    check("the named exemption names real calls: " + EXEMPT[DRIVER_KEY] + f" ({len(calls)} at lines "
          + ", ".join(map(str, calls)) + ")", len(calls) >= 1, "the driver set holds no waiver call with an inline --decision: "
          "remove the exemption")
    check_eq("no inline door outside the exemption and the pending list (B-387)", unlisted, {})
    for path, texts in sorted(PENDING.items()):
        reason = PENDING_PINNED_REASON if path in PENDING_PINNED else PENDING_REASON
        if found.get(path):
            print(f"PENDING {reason}: {path}: {len(found[path])} inline door(s), not failed here")
        else:
            print(f"clean now: remove {path} (pending: {reason})")
    for path, hits in sorted(unlisted.items()):
        for hit in hits:
            print(f"INLINE DOOR {path}: {hit[:140]}")


# --- item 1: the renderer ----------------------------------------------------------------------

def part_renderer() -> None:
    command = 'waiver.py --task T --stage S1 --block "x"'
    check_eq("door: the file option is appended", person_words.door(command), command + " --words-file <file>")
    check_eq("door: trailing whitespace is dropped, nothing else changes",
             person_words.door(command + "  \n"), command + " --words-file <file>")
    check_eq("door: for a person the placeholder says what goes in the file",
             person_words.door(command, for_person=True), command + " --words-file <file with your words>")
    check("door: the command itself is never changed (block quoting stays the site's own)",
          person_words.door(command).startswith(command))
    for label, empty in (("empty", ""), ("whitespace-only", " \n\t "), ("None", None)):
        try:
            person_words.door(empty)
            check(f"door: a {label} command is refused", False, "no ValueError")
        except ValueError:
            check(f"door: a {label} command is refused", True)


# --- (b) FR-2: the printed door opens ------------------------------------------------------------

SPAN = re.compile(r"`([^`]*)`")


def project_env(root: Path) -> dict:
    return dict(os.environ, CLAUDE_PROJECT_DIR=str(root), PYTHONDONTWRITEBYTECODE="1")


def door_of(text: str) -> str:
    """The waiver command in the LAST backtick span of a printed text that holds one."""
    spans = [s for s in SPAN.findall(text) if "waiver.py" in s]
    return spans[-1] if spans else ""


def part_doors_hold_the_whole_words_clause() -> None:
    """GW1-1 G-3: every printed door with `<part of the line>` carries `person_words.WHOLE_PART` right after its closing backtick
    (the check refuses a cut inside a word, so the text must not invite one); one row per door."""
    clause = person_words.WHOLE_PART
    check_in("the clause says whole words and no cut inside a word", "never a cut inside a word", clause)
    for name in ("branch_accounting.py", "controller.py", "critic_rollcall.py", "planning_contract.py", "s5_precheck.py"):
        text = (SCRIPTS / name).read_text(encoding="utf-8")
        at = [m.start() for m in re.finditer(r'<part of the line>', text) if "--block" in text[max(0, m.start() - 60):m.start()]]
        check(f"G-3 {name}: a printed `<part of the line>` door exists", bool(at))
        check(f"G-3 {name}: and the clause follows each (within the same statement)",
              all("WHOLE_PART" in text[i:i + 260] for i in at), name)
    check_in("G-3 the registry's WAIVER holds the one clause", clause, RR.WAIVER)


def whole_cut(text: str, n: int = 30) -> str:
    """The door's `<part of the line>` is whole words: at most `n` characters, never ending inside a word. A text
    shorter than `n` stays whole; with no space within the cut the first word is taken whole."""
    if len(text) <= n:
        return text
    cut = text[:n]
    word = re.compile(r"[A-Za-z0-9_-]")
    if word.match(text[n]) and word.match(cut[-1]):
        space = cut.rfind(" ")
        if space > 0:
            return cut[:space]
        return text.split(" ", 1)[0]
    return cut


def open_door(root: Path, text: str, ticket: str, stage: str, head: str = ""):
    """Run the command printed in `text` through the real waiver.py: the span is taken as printed,
    only the named placeholders are filled, the words go to a UTF-8 file under state/words/."""
    span = door_of(text)
    check_in("the printed door is the file form", FLAG, span)
    if FLAG not in span:
        return None, [], ""
    tail = span[span.index(FLAG):]
    check("and ends with a file placeholder",
          tail in (f"{FLAG} <file>", f"{FLAG} <file with your words>"), tail)
    argv = []
    for token in shlex.split(span[:span.index(FLAG)]):
        for placeholder, value in (("<TICKET>", ticket), ("<T>", ticket), ("<id>", ticket),
                                   ("<S>", stage), ("<part of the line>", head)):
            token = token.replace(placeholder, value)
        argv.append(token)
    left = [t for t in argv if "<" in t and ">" in t]
    check_eq("no placeholder is left unnamed", left, [])
    check_eq("the command is waiver.py", argv[0], "waiver.py")
    words = root / "qa-factory" / "artifacts" / ticket / "state" / "words" / "door.txt"
    words.parent.mkdir(parents=True, exist_ok=True)
    words.write_bytes(WORDS.encode("utf-8"))  # bytes: write_text would turn \n into \r\n on Windows
    done = run_script(argv[0], *argv[1:], FLAG, str(words), cwd=root, env=project_env(root))
    return done, argv, str(words)


def overrides_of(root: Path, ticket: str) -> list:
    path = root / "qa-factory" / "artifacts" / ticket / "pipeline.json"
    return json.loads(path.read_text(encoding="utf-8")).get("stage_overrides") or []


def recorded(label: str, done, root: Path, ticket: str, stage: str, block: str) -> None:
    check(f"{label}: the real waiver.py records the printed door (exit 0)",
          done is not None and done.returncode == 0,
          "" if done is None else f"{done.returncode} {done.stdout} {done.stderr}")
    mine = [o for o in overrides_of(root, ticket) if o.get("match") == block and o.get("stage") == stage]
    check_eq(f"{label}: one override of exactly that block, with the person's words from the file",
             [o.get("decision") for o in mine], [WORDS.strip()])


def captured(call):
    """(returned value, stdout, stderr) of an in-process call."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        value = call()
    return value, out.getvalue(), err.getvalue()


def row_13_rehearsal() -> None:
    root = GP.story("qa-words-door-rehearsal-")
    try:
        use_project(root)
        ticket = "TP1-15045"

        def close():
            return captured(lambda: stage_done.run(ticket, "S4", "done", "qa-case-critic", "cases reviewed", True))
        code, _, err = close()
        check_eq("13 rehearsal: S4 is refused while the factory owes itself a repair", code, stage_done.EXIT_BAD_ARGS)
        check_in("13 rehearsal: every finding carries the block word the door advises (F-6)",
                 "gate rehearsal: ", err)
        done, _, _ = open_door(root, err, ticket, "S4")
        recorded("13 rehearsal", done, root, ticket, "S4", "gate rehearsal")
        code, _, err = close()
        check_eq("13 rehearsal: the refusing code no longer refuses", code, 0)
    finally:
        cleanup(root)


def row_14_still_running() -> None:
    root = temp_project("qa-words-door-running-")
    try:
        use_project(root)
        art = S0.story(root)
        pipeline = json.loads((art / "pipeline.json").read_text(encoding="utf-8"))
        pipeline["stages"] = {"S5": {"status": "running", "role": None, "digest": ""}}
        (art / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")

        def close():
            return captured(lambda: stage_done.run(S0.TASK, "S9", "done", None, "retro done", True))
        code, _, err = close()
        check_eq("14 still running: S9 refuses to close over a running stage", code, stage_done.EXIT_BAD_ARGS)
        done, _, _ = open_door(root, err, S0.TASK, "S9")
        recorded("14 still running", done, root, S0.TASK, "S9", "still running")
        # 0.8.1 added checks of its own to the close of S9 (sizing, the report, the stages before it), so
        # the fixture's story is refused for THOSE even after the person's word: the claim here is that
        # the block the door names is lifted and the word is quoted, not that S9 closes.
        _, out, err = close()
        check_not_in("14 still running: the refusing code no longer refuses over the running stage",
                     "is still running", err)
        check_in("14 still running: and it says it closes over it on the person's word",
                 "closing S9 over a running stage on the person's word", err)
    finally:
        cleanup(root)


def row_15_16_controller_stage() -> None:
    root = temp_project("qa-words-door-managed-")
    try:
        use_project(root)
        art = S0.story(root)
        S0.initialize(art)
        code, err = S0.close(art)
        check_eq("15 not accepted: a managed stage the controller has not accepted is refused",
                 code, stage_done.EXIT_BAD_ARGS)
        done, _, _ = open_door(root, err, S0.TASK, "S0")
        recorded("15 not accepted", done, root, S0.TASK, "S0", "no accepted controller stage")
        check_eq("15 not accepted: the refusing code no longer refuses", S0.close(art)[0], 0)
    finally:
        cleanup(root)
    root = temp_project("qa-words-door-reopen-")
    try:
        use_project(root)
        art = S0.story(root)
        S0.initialize(art)
        import hashlib
        from controller import Controller
        Controller(art).apply("code_only", {
            "id": "s0-preflight", "stage": "S0", "reason": "no role runs preflight",
            "evidence_refs": [{"path": "pipeline.json",
                               "sha256": hashlib.sha256((art / "pipeline.json").read_bytes()).hexdigest()}],
            "idempotency_key": "code-only-S0"})
        code, err = S0.close(art, status="running")
        check_eq("16 reopen: lowering a stage the controller accepted is refused", code, stage_done.EXIT_BAD_ARGS)
        done, _, _ = open_door(root, err, S0.TASK, "S0")
        recorded("16 reopen", done, root, S0.TASK, "S0", "already accepted by the controller")
        check_eq("16 reopen: the refusing code no longer refuses", S0.close(art, status="running")[0], 0)
    finally:
        cleanup(root)


def story_with(root: Path, ticket: str, stages: dict) -> Path:
    task = root / "qa-factory" / "artifacts" / ticket
    task.mkdir(parents=True, exist_ok=True)
    (task / "pipeline.json").write_text(json.dumps({"ticket": ticket, "stages": stages}), encoding="utf-8")
    return task


def row_17_stage_guard_hint() -> None:
    root = temp_project("qa-words-door-hint-")
    try:
        use_project(root)
        story_with(root, "QA-1", {})

        def pipeline():
            return json.loads((root / "qa-factory" / "artifacts" / "QA-1" / "pipeline.json").read_text(encoding="utf-8"))
        errors = stage_guard.dispatch_errors(pipeline(), "S2", journal=False)
        check_eq("17 hint: S2 is refused while S1 is not done", len(errors), 1)
        if errors:
            check_in("17 hint: the refusal still starts with its own words", "required stages are not done", errors[0])
            # 0.8.1: `waiver_hint` is a plain `door()` (spec t-428 L7): the stage guard's refusal is read by the
            # orchestrator, whose placeholder is `<file>`; the person's form is the one of the gate packets.
            check_in("17 hint: the hint is the plain file form (a `door()`, not the person's placeholder)",
                     f"{FLAG} <file>", errors[0])
            check_not_in("17 hint: and carries no person's placeholder", "<file with your words>", errors[0])
            check_in("17 hint: the hint keeps its prefix", stage_guard.WAIVER_HINT_PREFIX, errors[0])
            done, _, _ = open_door(root, errors[0], "QA-1", "S2")
            recorded("17 hint", done, root, "QA-1", "S2", "required stages are not done")
            check_eq("17 hint: the refusing code no longer refuses",
                     stage_guard.dispatch_errors(pipeline(), "S2", journal=False), [])
    finally:
        cleanup(root)


def detector_row(label: str, script: str, agent: str, stage: str, make_story) -> None:
    """Rows 19-21: the gate re-runs the detector script; its last line is the door."""
    root = temp_project(f"qa-words-door-{script[:6]}-")
    try:
        use_project(root)
        make_story(root)
        run = run_script(script, cwd=root, env=project_env(root))
        check_eq(f"{label}: the detector refuses", run.returncode, 1)
        lines = [line for line in run.stdout.strip().splitlines() if line.strip()]
        check_in(f"{label}: the last line is the person's-word door", "waiver.py", lines[-1] if lines else "")
        head = whole_cut(lines[-2].strip().lstrip("- ")) if len(lines) > 1 else ""
        import exit_gate
        before = exit_gate.detector_errors(agent)
        check(f"{label}: the gate's own re-run refuses", bool(before), str(run.stdout)[-300:])
        done, _, _ = open_door(root, run.stdout, "QA-1", stage, head)
        recorded(label, done, root, "QA-1", stage, head)
        pipeline = json.loads((root / "qa-factory" / "artifacts" / "QA-1" / "pipeline.json").read_text(encoding="utf-8"))
        # C2-1: the rule of the gate is `judge_words` (a record is judged by whoever produced it), no longer
        # `split_overridden` over the whole output
        records = exit_gate.detector_errors(agent)
        blocking, passed = exit_gate.judge_words(records, pipeline, stage)
        check_eq(f"{label}: the refusing code no longer refuses (the gate re-run is passed over)", blocking, [])
        check(f"{label}: and the pass names the words", bool(passed) and passed[0]["decision"] == WORDS.strip(),
              str(passed))
        # a word taken from one finding's line passes that finding only; the word of the summary line (row 20) none
        # of them by itself but, for one release, the whole detector
        findings = [r for r in records if getattr(r, "kind", "") == "finding"]
        if len(findings) > 1:
            part = str(findings[0]).split(": ", 1)[1]
            part = whole_cut(part)
            one = {"stage_overrides": [{"stage": stage, "match": part, "decision": "x", "at": "2026-10-01T10:00:00"}]}
            blocking, passed = exit_gate.judge_words(records, one, stage)
            check_eq(f"{label}: a word from the line of one finding passes that finding and none of the others",
                     (len(passed), len(blocking)), (sum(1 for f in findings if part.lower() in f.lower()),
                                                     len(findings) - sum(1 for f in findings if part.lower() in f.lower())))
    finally:
        cleanup(root)


def critic_story(root: Path) -> None:
    task = story_with(root, "QA-1", {"S4": {"status": "running"}})
    folder = task / "work" / "test-cases" / "workflows"
    folder.mkdir(parents=True)
    (folder / "critic-findings.md").write_text("# Critic findings\n\nVerdict: reject.\n", encoding="utf-8")


def plan_story(root: Path) -> None:
    task = story_with(root, "QA-1", {"S3": {"status": "running"}})
    (task / "work").mkdir()
    (task / "work" / "test-plan.json").write_text(json.dumps({"rows": [{"id": "TS-1"}]}), encoding="utf-8")


def s5_story(root: Path) -> None:
    task = root / "qa-factory" / "artifacts" / OJ.TICKET
    (task / "work" / "test-cases").mkdir(parents=True)
    (task / "work" / "test-plan.json").write_text(json.dumps({"rows": OJ.PLAN_ROWS}), encoding="utf-8")
    for case, row in (("TC-005", "TS-1"), ("TC-006", "TS-2")):
        (task / "work" / "test-cases" / f"{case}.md").write_text(OJ.CASE_MD.format(case=case, row=row),
                                                               encoding="utf-8")
    (task / "work" / "automation-manifest.json").write_text(json.dumps({
        "tests": [{"case": "TC-005", "file": "tests/t.py", "instance_id": "test_five",
                   "covers": ["TC-005"], "status": "green"}],
        "obligation_bindings": [{"obligation_id": "OB-1", "instance_ids": ["test_five"]}]}), encoding="utf-8")
    (task / "pipeline.json").write_text(json.dumps(
        {"ticket": OJ.TICKET, "stages": {"S5": {"status": "running"}}}), encoding="utf-8")


def row_19_20_21_detectors() -> None:
    detector_row("19 critic_rollcall", "critic_rollcall.py", "qa-case-critic", "S4", critic_story)
    detector_row("20 planning_contract", "planning_contract.py", "qa-test-strategist", "S3", plan_story)
    root = temp_project("qa-words-door-s5pre-")
    try:
        use_project(root)
        s5_story(root)
        run = run_script("s5_precheck.py", cwd=root, env=project_env(root))
        check_eq("21 s5_precheck: the detector refuses", run.returncode, 1)
        lines = [line for line in run.stdout.strip().splitlines() if line.strip()]
        # C2-1 (§6 row 21): the word is taken from a PRINTED line. The fixture gives four findings: two of the
        # `obligations` family (a word passes them, at the source) and two of `run_mapping`/`bindings` (no word
        # passes them, `*` included: their lines carry `WORDS_REFUSED_AT_SOURCE ... family`).
        wanted = next(line for line in lines if line.startswith("- [obligations "))
        head = whole_cut(wanted.strip().lstrip("- "))
        import exit_gate
        check("21 s5_precheck: the gate's own re-run refuses", bool(exit_gate.detector_errors("qa-automator")))
        done, _, _ = open_door(root, run.stdout, OJ.TICKET, "S5", head)
        recorded("21 s5_precheck", done, root, OJ.TICKET, "S5", head)
        pipeline = json.loads((root / "qa-factory" / "artifacts" / OJ.TICKET / "pipeline.json")
                              .read_text(encoding="utf-8"))
        records = exit_gate.detector_errors("qa-automator")
        blocking, passed = exit_gate.judge_words(records, pipeline, "S5")
        check_eq("21 s5_precheck: the word taken from the printed line passed its finding at the SOURCE; the gate "
                 "holds the two families no word passes, and passes nothing itself",
                 ([b.refused for b in blocking], passed), (["family", "family"], []))
        star = {"stage_overrides": [{"stage": "S5", "match": "*", "decision": "all of it",
                                     "at": "2026-10-01T10:00:00"}]}
        blocking, passed = exit_gate.judge_words(records, star, "S5")
        check_eq("21 s5_precheck: `*` does not pass them either: the tag of the source stands above it",
                 ([b.refused for b in blocking], passed), (["family", "family"], []))
        bound = next(line for line in lines if line.startswith("- [bindings "))
        word = {"stage_overrides": [{"stage": "S5", "match": whole_cut(bound.lstrip("- ")), "decision": "x",
                                     "at": "2026-10-01T10:00:00"}]}
        blocking, passed = exit_gate.judge_words(records, word, "S5")
        check_eq("21 s5_precheck: a word taken from the line of a family nobody can pass leaves it blocked",
                 ([b.refused for b in blocking], passed), (["family", "family"], []))
    finally:
        cleanup(root)


def row_22_manifest_put() -> None:
    root, task = OJ.make_story()
    try:
        fragment = {"tests": [{"case": "TC-005", "file": "tests/t.py", "instance_id": "test_ok",
                               "covers": ["TC-005"]}],
                    "obligation_bindings": [{"obligation_id": "OB-1", "instance_ids": ["test_ok"]}]}
        refused = OJ.put(root, fragment)
        import manifest_put
        check_eq("22 manifest_put: an obligation id the plan does not name is refused",
                 refused.returncode, manifest_put.EXIT_BAD_FRAGMENT)
        (task / "pipeline.json").write_text(json.dumps({"ticket": OJ.TICKET, "stages": {}}), encoding="utf-8")
        done, _, _ = open_door(root, refused.stderr, OJ.TICKET, "S5")
        recorded("22 manifest_put", done, root, OJ.TICKET, "S5", "obligation-id")
        check_eq("22 manifest_put: the refusing code no longer refuses", OJ.put(root, fragment).returncode, 0)
    finally:
        cleanup(root)


def row_23_24_story_budget() -> None:
    import story_budget
    root = temp_project("qa-words-door-budget-")
    try:
        use_project(root)
        base = root / "qa-factory"
        troot = story_with(root, "QA-1", {})
        (base / "state" / "cost").mkdir(parents=True, exist_ok=True)
        (base / "config.json").write_text(json.dumps({"budget": {"story_usd": 10, "warn_at": [0.5]}}), encoding="utf-8")
        # 0.8.1 (FR-24): a story's spend is the sessions its OWN driver journal names, so the session is bound
        # the way the price function reads it (the journal row with the running total; a `by_task` tag of
        # the cost file binds nothing), as test_window_and_budgets.bind_session does.
        (troot / "state").mkdir(parents=True, exist_ok=True)
        (troot / "state" / "driver-runs.jsonl").write_text(json.dumps(
            {"kind": "role", "role": "qa-scout", "dispatch": "S1-qa-scout-1", "stage": "S1", "session_id": "s-1",
             "num_turns": 3, "total_cost_usd": 11.0, "ts": "2026-09-30T10:00:00+00:00"}) + "\n", encoding="utf-8")
        (base / "state" / "cost" / "s-1.json").write_text(json.dumps(
            {"session_id": "s-1", "by_task": {"QA-1": {"tokens": 10}}, "agents": []}), encoding="utf-8")
        state = story_budget.check("QA-1", base, troot)
        check_eq("24 story_budget: past the ceiling the story stops and asks", state["stop"], True)
        done, _, _ = open_door(root, state["notice"], "QA-1", "S5")
        recorded("24 story_budget", done, root, "QA-1", "S5", "story budget")
        story_budget.marker_path("QA-1", base).unlink()
        again = story_budget.check("QA-1", base, troot)
        check_eq("24 story_budget: the refusing code no longer stops the story", again["stop"], False)
        check_eq("24 story_budget: and it quotes the person's words",
                 (again["overridden"] or {}).get("decision"), WORDS.strip())
        doc = (SCRIPTS / "story_budget.py").read_text(encoding="utf-8").split('"""')[1]
        check_in("23 story_budget: its own docstring shows the file form", f'--block "story budget" {FLAG} <file>', doc)
    finally:
        cleanup(root)


def row_block_names() -> None:
    """conductor/4 C4-3 (FR-2): the doors the roles are taught for the block NAMES a reader acts on - `keep it local` (s8.md),
    `executor unavailable: <profile>` (s4.md, SKILL.md) - open through the real waiver.py while the driver's record of that
    stage holds another line; a text that is no name (the NO_ADAPTER wording `keep local`) is refused as before."""
    import contract
    import external_writes
    root = temp_project("qa-words-door-names-")
    try:
        use_project(root)
        task = story_with(root, "QA-1", {})
        state = task / "state"
        state.mkdir(parents=True, exist_ok=True)
        for stage, block in (("S8", "keep it local"), ("S5", f"{contract.HANDED_MATCH_PREFIX} e2e-ui")):
            (state / "standing-refusal.json").write_text(json.dumps(
                {"stage": stage, "lines": ["a problem that is not the person's word to pass"]}), encoding="utf-8")
            door = person_words.door(f'waiver.py --task <T> --stage {stage} --block "{block}"')
            done, _, _ = open_door(root, f"the roles are taught: `{door}`", "QA-1", stage)
            recorded(f"names: `{block}` at {stage}, another line standing", done, root, "QA-1", stage, block)
        check_eq("names: the reader of `keep it local` acts on what was recorded",
                 bool(external_writes.local_only_decision("QA-1")), True)
        check_eq("names: the reader of the handed profile acts on what was recorded",
                 sorted(contract.handed_profiles(json.loads((task / "pipeline.json").read_text(encoding="utf-8")))), ["e2e-ui"])
        (state / "standing-refusal.json").write_text(json.dumps(
            {"stage": "S8", "lines": ["a problem that is not the person's word to pass"]}), encoding="utf-8")
        before = overrides_of(root, "QA-1")
        door = person_words.door('waiver.py --task <T> --stage S8 --block "keep local"')
        done, _, _ = open_door(root, f"`{door}`", "QA-1", "S8")
        check_eq("names: `keep local` (the NO_ADAPTER wording) is no name: the real waiver.py refuses it (exit 2)",
                 done is not None and done.returncode, 2)
        check_eq("names: ...and records nothing", overrides_of(root, "QA-1"), before)
        # t-894 F-1: words after the prefix are no profile id - the real waiver.py refuses them, the reader never sees them
        (state / "standing-refusal.json").write_text(json.dumps(
            {"stage": "S5", "lines": ["a problem that is not the person's word to pass"]}), encoding="utf-8")
        before = overrides_of(root, "QA-1")
        door = person_words.door(f'waiver.py --task <T> --stage S5 --block "{contract.HANDED_MATCH_PREFIX} e2e ui"')
        done, _, _ = open_door(root, f"`{door}`", "QA-1", "S5")
        check_eq("names: `executor unavailable: e2e ui` (words, not one profile) is no name: the real waiver.py refuses it (exit 2)",
                 done is not None and done.returncode, 2)
        check_eq("names: ...and records nothing", overrides_of(root, "QA-1"), before)
    finally:
        cleanup(root)


def row_25_readiness_and_tracker_route() -> None:
    import readiness
    cap = readiness.session_route("jira", "mcp_tool", "jira_get_issue")
    steps = " | ".join(cap["remedy"]["steps"])
    # 0.8.1 (spec t-428): the remedy of an unproven tracker route is upstream's text, which names the
    # script on the action line and takes the words inline (`--decision "<your words>"`). It is the
    # one inline door of the readiness doctor, listed in PENDING (B-387), so the check here is that
    # the pending text is the one the code prints - the file form is the stage guard's refusal below.
    check_in("25 readiness: the remedy is upstream's text, the pending door of the detector",
             PENDING["scripts/readiness.py"][0], steps)
    root = temp_project("qa-words-door-tracker-")
    try:
        use_project(root)
        story_with(root, "QA-1", {"S0": {"status": "done"}})
        (root / "qa-factory" / "readiness.json").write_text(json.dumps(
            {"capabilities": {"ticket_adapter": dict(cap, status="not_configured")}}), encoding="utf-8")
        pipeline = json.loads((root / "qa-factory" / "artifacts" / "QA-1" / "pipeline.json").read_text(encoding="utf-8"))
        refusal = stage_guard.rule_tracker_route("QA-1", "qa-scout", "S1", pipeline)
        check("25 tracker route: S1 is refused while the route is not proven", bool(refusal), str(refusal))
        done, _, _ = open_door(root, refusal or "", "QA-1", "S1")
        recorded("25 tracker route", done, root, "QA-1", "S1", "tracker route")
        pipeline = json.loads((root / "qa-factory" / "artifacts" / "QA-1" / "pipeline.json").read_text(encoding="utf-8"))
        check_eq("25 tracker route: the refusing code no longer refuses",
                 stage_guard.rule_tracker_route("QA-1", "qa-scout", "S1", pipeline), None)
    finally:
        cleanup(root)


def registry_texts() -> None:
    by_id = {entry["id"]: entry for entry in RR.REGISTRY}
    check_in("registry: WAIVER names the file form", f'--block "<part of the line>" {FLAG} <file>', RR.WAIVER)
    check_in("registry: SG-tracker-route names the file form", f'--block "tracker route" {FLAG} <file>',
             by_id["SG-tracker-route"]["override"])
    blocked = by_id["CTRL-next-blocked"]["override"]
    check_in("registry: CTRL-next-blocked names the file form", f'--block "wait_existing_job" {FLAG} <file>', blocked)
    check_in("registry: and says route_release passes the same words on to release",
             "--operation release", blocked)
    check_in("registry: through the file the person's words came in", "route_release", blocked)
    for eid, entry in by_id.items():
        check_eq(f"registry: {eid} carries no inline words part", hits_in(str(entry.get("override") or "")), [])


# --- (b) FR-2 for the controller's own refusals (legacy-2406 wave 3, node W3-D-B) -----------------
# The controller printed `waiver.py ... --decision "<their words>"` in nine places, the stage guard's
# own hint in a tenth, a release door in two more (`next` and the spawn guard), and a gate-decision
# door in a thirteenth. Every one is produced here from the REAL code, the command is taken from the
# printed text, the REAL CLI is run with a words file, and the refusing code then no longer refuses.

TICKET = "QA-1"


def ctrl_project(prefix: str):
    """(project root, task root): a controller story lives where waiver.py looks for it."""
    root = temp_project(prefix)
    use_project(root)
    task = root / "qa-factory" / "artifacts" / TICKET
    task.mkdir(parents=True)
    return root, task


def refused_text(call) -> str:
    """The message of a refusal the controller raises, or '' when the call went through."""
    from event_store import StateConflict
    try:
        call()
    except (StateConflict, ValueError) as exc:
        return str(exc)
    return ""


def critic_review(c, task, name, scope):
    """The code critic's re-review the way a real one ends: it leaves its findings file. A story that came through S5 has its manifest
    on disk, and with one the controller demands the findings receipt at the critic's accept (C4-1 fixtures)."""
    import test_controller_state as BASE
    import test_s5_process as S5
    S5.dispatch(c, task, name, role="qa-code-critic", scope=scope, accept=False)
    c.apply("accept", {"id": name, "status": "accepted", "stage_complete": False, "unresolved": True,
                       "reason": "the window's repair round is still open",
                       "evidence_refs": [S5.evidence(task, name + ".txt"), BASE.evidence_ref(task, name + "-findings.md", "# findings")],
                       "idempotency_key": name + "-ok"})


def story_pipeline(task: Path) -> None:
    """waiver.py records only into a story that has a pipeline.json; the controller does not write
    one itself in these fixtures. Written AFTER the refusal, with every stage done, so it adds no
    refusal of the stage guard's own."""
    path = task / "pipeline.json"
    if not path.is_file():
        path.write_text(json.dumps({"ticket": TICKET, "stages": {f"S{n}": {"status": "done"} for n in range(10)}}),
                        encoding="utf-8")


def waiver_door(root: Path, task: Path, label: str, text: str, stage: str, block: str, head: str = "") -> None:
    """The printed waiver door, opened through the real waiver.py: records `block` for `stage`."""
    check_in(f"{label}: the refusal prints a waiver door", "waiver.py", text)
    story_pipeline(task)
    done, _, _ = open_door(root, text, TICKET, stage, head)
    recorded(label, done, root, TICKET, stage, block)


def span_with(text: str, needle: str) -> str:
    spans = [s for s in SPAN.findall(text) if needle in s]
    return spans[-1] if spans else ""


def run_printed(root: Path, task: Path, label: str, span: str, words: Path, extra: tuple = ()):
    """Run a printed `controller.py ...` / `--operation ...` span through the real CLI, the file
    placeholder replaced by the words file. `extra` is what the printed text leaves to the caller."""
    check_in(f"{label}: the printed door is the file form", f"{FLAG} <file>", span)
    head = span[:span.index(FLAG)].split()
    argv = head if head and head[0] == "controller.py" else ["controller.py", "--task-root", str(task)] + head
    words.parent.mkdir(parents=True, exist_ok=True)
    words.write_bytes(WORDS.encode("utf-8"))
    return run_script(argv[0], *argv[1:], *extra, FLAG, str(words), cwd=root, env=project_env(root))


def row_1_2_design_review() -> None:
    from controller import Controller
    root, task = ctrl_project("qa-words-door-design-")
    try:
        import test_controller_gate_decision as GATE
        c = GATE.story(task)
        # One story: both refusals are read first (a recorded `design review` word would pass the
        # second), then row 2's waiver is opened, then row 1's CLI records the decision.
        built = c.build_gate_decision("A", WORDS)
        built["design_reviews"] = [dict(built["design_reviews"][0], verdict="rejected")]
        text = "\n".join(str(p) for p in c.check_decision(built))
        check_in("2 design review: a critic's own rejection is refused", "declared verdict is 'rejected'", text)
        broken = dict(built, design_reviews=[])
        missing = "\n".join(str(p) for p in c.check_decision(broken))
        check_in("1 design review: the missing-review refusal is printed", "requires an independent design review",
                 missing)
        waiver_door(root, task, "2 design review", text, "S4", "design review")
        check_eq("2 design review: the refusing code no longer refuses",
                 [p for p in c.check_decision(built) if "design review" in str(p)], [])
        span = span_with(missing, "gate-decision")
        result = run_printed(root, task, "1 design review", span, task / "state" / "words" / "door.txt")
        check("1 design review: the real controller records the gate decision from the file (exit 0)",
              result.returncode == 0, f"{result.returncode} {result.stdout[-300:]} {result.stderr[-300:]}")
        decisions = (Controller(task).state().get("decisions") or {}).values()
        check_eq("1 design review: the decision carries the person's words from the file, whole",
                 [d.get("authorization_source") for d in decisions if d.get("gate") == "A"], [WORDS])
    finally:
        cleanup(root)


def row_3_empty_scope_at_gate_a() -> None:
    import test_controller_state as BASE
    import test_controller_rework_scope as SCOPED
    from controller import Controller
    root, task = ctrl_project("qa-words-door-empty-a-")
    try:
        c = Controller(task)
        c.apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1",
                               "known_paths": {"root": str(task)}, "idempotency_key": "init"})
        for number in range(5):
            BASE.accept_stage(c, task, f"S{number}")
        BASE.seed_plan(task, [SCOPED.plan_row(1, "automate")])
        c.apply("revise_plan", {"scope": [], "plan_revision": "plan-2",
                                "reason": "scope recorded empty by mistake", "idempotency_key": "revise"})
        decision = {"id": "gate-a", "gate": "A", "action": "approve", "status": "approved",
                    "authorization_source": "human", "source_revision": "src-1", "scope": [],
                    "input_revision": "plan-2", "idempotency_key": "gate-a"}
        decision.update(c.gate_inputs())
        text = refused_text(lambda: c.apply("decision", dict(decision)))
        check_in("3 empty scope (gate A): an empty scope under a plan with rows is refused", "empty scope", text)
        waiver_door(root, task, "3 empty scope (gate A)", text, "S4", "empty scope")
        check_eq("3 empty scope (gate A): the refusing code no longer refuses",
                 refused_text(lambda: c.apply("decision", dict(decision))), "")
    finally:
        cleanup(root)


def settle(c, task: Path, dispatch_id: str) -> None:
    """Accept a running S5 author dispatch (open work), so the next dispatch of the story may start."""
    import test_s5_process as S5
    c.apply("accept", {"id": dispatch_id, "status": "accepted", "stage_complete": False, "unresolved": True,
                       "reason": "the window's repair round is still open",
                       "evidence_refs": [S5.evidence(task, dispatch_id + ".txt")],
                       "idempotency_key": dispatch_id + "-settled"})


def rows_4_5_11_dispatch_doors() -> None:
    """One S5 story: an empty scope (row 4), a dispatch the stage guard holds (row 11), a reviewer for
    a mechanical round (row 5). Their block words differ, so each override passes only its own."""
    import test_s5_process as S5
    root, task = ctrl_project("qa-words-door-dispatch-")
    real = stage_guard.dispatch_errors
    bare = "stage S5 is held by a rule of the guard that prints no command of its own"

    def stand_in(pipeline, stage_id, **_):
        # `stage_guard_errors` adds its door ONLY to a message that carries none, and the real
        # `dispatch_errors` always appends its own hint: a rule that returns bare text stands in for
        # it here, passed through the same `waiver.split_overridden` the real one uses.
        return waiver.split_overridden([bare], pipeline, stage_id)[0]
    try:
        c = S5.s5_task(task)
        request = {"id": "empty-s5", "stage": "S5", "role": "qa-automator", "scope": [], "input_hash": "h",
                   "budget": {}, "known_paths": {}, "idempotency_key": "empty-s5"}
        text = refused_text(lambda: s5_apply(c, dict(request)))
        check_in("4 empty scope (dispatch): an empty S5 scope is refused", "empty scope", text)
        waiver_door(root, task, "4 empty scope (dispatch)", text, "S5", "empty scope")
        check_eq("4 empty scope (dispatch): the refusing code no longer refuses",
                 refused_text(lambda: s5_apply(c, dict(request))), "")
        settle(c, task, "empty-s5")
        guarded = {"id": "guarded", "stage": "S5", "role": "qa-automator", "scope": ["TC-1", "TC-2"],
                   "input_hash": "h2", "budget": {}, "known_paths": {}, "idempotency_key": "guarded"}
        stage_guard.dispatch_errors = stand_in
        text = refused_text(lambda: s5_apply(c, dict(guarded)))
        check_in("11 stage guard: the dispatch is refused with the guard's own words", bare, text)
        check_in("11 stage guard: the controller adds the person's-word door", "a person's word passes this", text)
        # `<part of the line>` is the person's to fill: any part of the refused line
        waiver_door(root, task, "11 stage guard", text, "S5", "prints no command of its own",
                    head="prints no command of its own")
        check_eq("11 stage guard: the refusing code no longer refuses",
                 refused_text(lambda: s5_apply(c, dict(guarded))), "")
        stage_guard.dispatch_errors = real
        settle(c, task, "guarded")

        def critic():
            return S5.dispatch(c, task, "k1", role="qa-code-critic", repair_cause="mechanical",
                               reason="check the sleep fix", accept=False)
        text = refused_text(critic)
        check_in("5 mechanical repair round (critic): a reviewer for a mechanical round is refused",
                 "not dispatched for a mechanical repair round", text)
        # C1-5a: the door is the pass of THAT round (`mechanical pass <n> for <role> on <stage>:<hash>`), the line's first words
        waiver_door(root, task, "5 mechanical repair round (critic)", text, "S5", pass_blocks(text)[0])
        check_eq("5 mechanical repair round (critic): the refusing code no longer refuses",
                 refused_text(critic), "")
    finally:
        stage_guard.dispatch_errors = real
        cleanup(root)


def rows_6_7_repair_rounds() -> None:
    """One S5 story, two refusals: the mechanical cap, then the cap on plain rounds. The block word
    `mechanical repair round` is not in the plain cap's text, and `repair round` is recorded last."""
    import test_s5_process as S5
    root, task = ctrl_project("qa-words-door-rounds-")
    try:
        c = S5.s5_task(task)
        S5.dispatch(c, task, "a1")
        S5.dispatch(c, task, "m1", repair_cause="mechanical", reason="TC-1: a sleep -> a wait")

        def again():
            return S5.dispatch(c, task, "m2", repair_cause="mechanical", reason="again")
        text = refused_text(again)
        check_in("6 mechanical repair round (cap): a second mechanical round is refused",
                 "mechanical repair round(s); the cap is 1", text)
        waiver_door(root, task, "6 mechanical repair round (cap)", text, "S5", pass_blocks(text)[0])
        check_eq("6 mechanical repair round (cap): the refusing code no longer refuses",
                 refused_text(again), "")

        text = ""
        for number in range(8):  # plain rounds about the test, until the cap says no
            text = refused_text(lambda: S5.dispatch(c, task, f"p{number}"))
            if text:
                break
        check_in("7 repair round (cap): the rounds about the test run out", "repair round(s) about the test", text)
        # C1-5a: two doors, the author's pass first and the critic's second; the author's opens its own round
        blocks = pass_blocks(text)
        check_eq("7 repair round (cap): the refusal prints a pass for each of the two roles",
                 [b.split(" on ")[0].split(" for ")[1] for b in blocks], ["qa-automator", "qa-code-critic"])
        waiver_door(root, task, "7 repair round (cap)", f"`{door_spans(text)[0]}`", "S5", blocks[0])
        check_eq("7 repair round (cap): the refusing code no longer refuses",
                 refused_text(lambda: S5.dispatch(c, task, f"p{number}")), "")
    finally:
        cleanup(root)


def row_round_pass_keys() -> None:
    """C1-5a (A2, A3, F3; t-700 Q1): a person's word passes ONE round with its own key. `waiver.split_overridden` matches a word by
    substring, case-folded, and never uses it up, so a stage-wide `repair round` passed every later round of the window. The key
    `round pass {n} for {role} on {stage}:{hash12}` names the round; hash12 comes from the window's ledger key and its life (F2:
    `content_hash(ledger_key + "|" + life)[:12]`, the life "" for the first; a changed case list must not change it); neither key form holds a live keyword; an old stage-wide record keeps its old power (edge 3, temporal)."""
    import test_s5_process as S5
    from controller import ledger_key, mechanical_pass_key, repair_pass_key, repair_passes
    from event_store import content_hash
    root, task = ctrl_project("qa-words-door-pass-")
    try:
        c = S5.s5_task(task)
        window = {"stage": "S5", "role": "qa-automator", "scope": ["TC-1", "TC-2"]}
        for name in ("a1", "a2", "a3"):                      # the opener and two rounds about the test: the author's cap is spent
            S5.dispatch(c, task, name)
        for name in ("k1", "k2", "k3"):                      # the same for the critic
            S5.dispatch(c, task, name, role="qa-code-critic")
        text = refused_text(lambda: S5.dispatch(c, task, "a4"))
        author, critic = blocks = pass_blocks(text)
        packet = c.prepare(dict(window))
        check_eq("pass keys: the refusal prints the keys `repair_budget` carries, for both roles, in its order (never rebuilt)",
                 blocks, list(packet["repair_budget"]["passes"].values()))
        check_eq("pass keys: round 3 for each role (counted 2 each)", [b.split(" on ")[0] for b in blocks],
                 ["round pass 3 for qa-automator", "round pass 3 for qa-code-critic"])
        check("pass keys: the refused line STARTS with the author's own key, then today's sentence",
              text.startswith(author + ": qa-automator has already had 2 repair round(s) about the test"), text[:160])
        check_not_in("pass keys: the refused line does not carry the other role's key (a word matches by substring)",
                     critic, text.split(" If a person wants one more round")[0])
        mechanical = mechanical_pass_key(c.state()["dispatches"], window)
        for key in (author, critic, mechanical):
            for live in ("repair round", "mechanical round"):
                check_not_in(f"pass keys: `{key[:34]}...` holds no live keyword `{live}`", live, key.lower())
        check("pass keys: the mechanical key is its own form", mechanical.startswith("mechanical pass 1 for qa-automator on S5:"), mechanical)
        check("pass keys: round 1 is not a substring of round 10 (the ` for ` after the number)",
              repair_pass_key("S5", "qa-automator", 1, "k") not in repair_pass_key("S5", "qa-automator", 10, "k"))
        check_eq("pass keys: hash12 = content_hash(ledger_key(p) + '|' + life)[:12], the first life being '' (F2: the key ends with the bar)",
                 author.rsplit(":", 1)[1], content_hash(ledger_key(window) + "|")[:12])
        check("pass keys: ...which is not the hash of the scope list", author.rsplit(":", 1)[1] != content_hash(sorted(window["scope"]))[:12])
        designer = {"stage": "S4", "role": "qa-case-designer", "scope": ["TC-1"]}
        check_eq("pass keys: a changed case list does not change the S4 designer's key (its ledger key is story-wide)",
                 repair_passes({}, designer)["qa-case-designer"],
                 repair_passes({}, dict(designer, scope=["TC-1", "TC-2", "TC-3"]))["qa-case-designer"])
        check_eq("pass keys: an empty scope still has a key (the ledger hashes the empty list, no `no key` branch)",
                 sorted(repair_passes({}, dict(window, scope=[]))), ["qa-automator", "qa-code-critic"])
        story_pipeline(task)
        done, _, _ = open_door(root, f"`{door_spans(text)[1]}`", TICKET, "S5")
        recorded("pass keys: the critic's pass", done, root, TICKET, "S5", critic)
        check_in("pass keys: the critic's pass alone does not pass the author's round", author,
                 refused_text(lambda: S5.dispatch(c, task, "a4")))
        done, _, _ = open_door(root, f"`{door_spans(text)[0]}`", TICKET, "S5")
        recorded("pass keys: the author's pass", done, root, TICKET, "S5", author)
        check_eq("pass keys: the author's pass opens its round (3)", refused_text(lambda: S5.dispatch(c, task, "a4")), "")
        again = refused_text(lambda: S5.dispatch(c, task, "a5"))
        check("pass keys: the word passes exactly ONE round - round 4 is refused with its own key",
              again.startswith("round pass 4 for qa-automator on S5:"), again[:120])
        check_eq("pass keys: the critic's own round 3 passes with its pass", refused_text(lambda: S5.dispatch(c, task, "k4", role="qa-code-critic")), "")
        check("pass keys: ...and its round 4 is refused with its own key",
              refused_text(lambda: S5.dispatch(c, task, "k5", role="qa-code-critic")).startswith("round pass 4 for qa-code-critic on S5:"))
    finally:
        cleanup(root)
    root, task = ctrl_project("qa-words-door-oldpass-")
    try:
        c = S5.s5_task(task)
        S5.dispatch(c, task, "a1")
        S5.dispatch(c, task, "m1", repair_cause="mechanical", reason="TC-1: a sleep -> a wait")
        for name in ("a2", "a3"):
            S5.dispatch(c, task, name)
        story_pipeline(task)
        path = task / "pipeline.json"
        pipeline = json.loads(path.read_text(encoding="utf-8"))
        def old_record(match: str) -> None:                           # a word recorded by an OLD door, stage-wide
            waiver.apply_stage_override(pipeline, "S5", match, "an old word", waiver.now_iso())
            path.write_text(json.dumps(pipeline), encoding="utf-8")
        old_record("mechanical repair round")
        check_eq("pass keys, temporal: an OLD `mechanical repair round` record still passes the mechanical cap",
                 refused_text(lambda: S5.dispatch(c, task, "m2", repair_cause="mechanical", reason="again")), "")
        check("pass keys, temporal: ...and is not the plain cap's word (that text does not hold it)",
              refused_text(lambda: S5.dispatch(c, task, "a4")).startswith("round pass 3 for qa-automator on S5:"))
        old_record("repair round")
        check_eq("pass keys, temporal: an OLD `repair round` record still passes the cap, round after round (the sentence after the key holds it)",
                 [refused_text(lambda: S5.dispatch(c, task, name)) for name in ("a4", "a5")], ["", ""])
    finally:
        cleanup(root)


def row_pass_key_counting_and_life() -> None:
    """t-708 (F1, F2; integration critic t-706), on the pure functions and a hand-built journal. F1: the reviewer's mechanical pass
    number counts with the ledger's predicate (A1) - a round an own-stage `reviews` stamp set aside is a PAID round, or the old
    word would pass a second reviewer mechanical round (I2); one an earlier stage's rework set aside opens a new window. F2: the
    window's LIFE (the latest earlier-stage rework that set it aside) is in the hash, "" for the first life."""
    from controller import (apply_rerun_after, mechanical_pass_key, mechanical_rounds, repair_pass_key,
                            repair_passes, window_life)
    from event_store import content_hash

    def state_of(rework_stage):
        def d(identifier, role, stage="S5", **extra):
            return dict({"id": identifier, "stage": stage, "role": role, "scope": ["TC-1"], "status": "accepted"}, **extra)
        return {"dispatches": {"a1": d("a1", "qa-automator"), "m1": d("m1", "qa-automator", repair_cause="mechanical"),
                               "k1": d("k1", "qa-code-critic", repair_cause="mechanical"),
                               "r": d("r", "qa-automator" if rework_stage == "S5" else "qa-worker", stage=rework_stage,
                                      status="running", rework_of="x")},
                "stages": {"S5": {"status": "completed"}}, "decisions": {}}
    critic = {"stage": "S5", "role": "qa-code-critic", "scope": ["TC-1"]}
    author = dict(critic, role="qa-automator")
    fresh = state_of("S5")["dispatches"]
    before = {role: mechanical_pass_key(fresh, window) for role, window in (("critic", critic), ("author", author))}
    check("F1 fixture: the reviewer has had one mechanical dispatch (k1), the author one (m1): both next passes are number 2",
          before["critic"].startswith("mechanical pass 2 for qa-code-critic on S5:")
          and before["author"].startswith("mechanical pass 2 for qa-automator on S5:"), str(before))
    own = state_of("S5")
    apply_rerun_after(own, "r", "S5", {"stages": [], "reviews": ["k1"], "decisions": []})
    check_eq("F1 fixture: the S5 rework staled the reviewer's k1 through the `reviews` stamp, with the mark",
             (own["dispatches"]["k1"]["status"], own["dispatches"]["k1"].get("stale_by_rework")), ("stale", "r"))
    check_eq("F1: an own-stage stale keeps the reviewer's mechanical pass number (2, the same key - the old word does not pass a "
             "second reviewer mechanical round)", mechanical_pass_key(own["dispatches"], critic), before["critic"])
    check_eq("F1: ...ONE counter - `mechanical_rounds` by role says 1, as before the stale",
             mechanical_rounds(own["dispatches"], critic, by_role=True), 1)
    check_eq("F1: the author's key is not touched by the reviewer's stale (the AUTHOR branch is unchanged)",
             mechanical_pass_key(own["dispatches"], author), before["author"])
    earlier = state_of("S4")
    apply_rerun_after(earlier, "r", "S4", {"stages": ["S5"], "reviews": [], "decisions": []})
    after = {role: mechanical_pass_key(earlier["dispatches"], window) for role, window in (("critic", critic), ("author", author))}
    check("F1: an EARLIER stage's rework opens a new window for both roles: mechanical pass 1, counted 0",
          after["critic"].startswith("mechanical pass 1 for qa-code-critic on S5:")
          and after["author"].startswith("mechanical pass 1 for qa-automator on S5:"), str(after))
    check_eq("F2: a window never set aside has the first life ''", window_life(fresh, critic), "")
    check_eq("F2: a rework of the window's OWN stage is no new life", window_life(own["dispatches"], critic), "")
    check_eq("F2: the earlier-stage rework that set it aside is the life - for both roles of the loop",
             (window_life(earlier["dispatches"], critic), window_life(earlier["dispatches"], author)), ("r", "r"))
    check_eq("F2: the first life hashes the ledger key with the bar and nothing after it",
             before["critic"].rsplit(":", 1)[1], content_hash("S5:qa-code-critic:" + content_hash(["TC-1"]) + "|")[:12])
    check_eq("F2: the new life's hash is the key, the bar and the rework's id",
             after["critic"].rsplit(":", 1)[1], content_hash("S5:qa-code-critic:" + content_hash(["TC-1"]) + "|r")[:12])
    check("F2: so the same round has another key in the new life (the old word stops matching)",
          repair_passes(fresh, critic)["qa-automator"].rsplit(":", 1)[1]
          != repair_passes(earlier["dispatches"], critic)["qa-automator"].rsplit(":", 1)[1])
    check("F2: the key builder's life argument is the only thing that moves the hash",
          repair_pass_key("S5", "qa-automator", 3, "k") != repair_pass_key("S5", "qa-automator", 3, "k", life="rw-1"))

    def stale(identifier, mark, **extra):
        return dict({"id": identifier, "stage": "S5", "role": "qa-automator", "scope": ["TC-1"], "status": "stale",
                     "stale_by_rework": mark}, **extra)
    def rework(identifier, stage):
        return {"id": identifier, "stage": stage, "role": "qa-worker", "scope": ["TC-1"], "status": "accepted"}
    twice = {"a1": stale("a1", "r4"), "r4": rework("r4", "S4"), "n1": stale("n1", "r3"), "r3": rework("r3", "S3")}
    check_eq("F2 edge: a window staled twice by earlier-stage reworks takes the LATEST in the journal's order",
             window_life(twice, author), "r3")
    check_eq("F2 edge: ...and the order is the journal's, not the id's",
             window_life({"a1": twice["a1"], "n1": twice["n1"], "r3": twice["r3"], "r4": twice["r4"]}, author), "r4")
    anonymous = {"a1": stale("a1", "r"), "r": {key: value for key, value in rework("r", "S4").items() if key != "id"}}
    life, _, err = captured(lambda: window_life(anonymous, author))
    check_eq("F2 edge: a rework record with no id field is the first life, not a KeyError", life, "")
    check_eq("F2 edge: ...and one defect line is printed", len([line for line in err.splitlines() if "no id field" in line]), 1)
    check_eq("F2 edge: a stale mark naming no record is the first life (an old journal), nothing printed",
             captured(lambda: window_life({"a1": stale("a1", "gone")}, author))[::2], ("", ""))


def row_pass_life_end_to_end() -> None:
    """t-708 (F2, R15's second direction) through the real controller, waiver.py and the real stamp: a word recorded for round 3
    of the OLD life of a window does not open round 3 of the NEW life an earlier stage's person-word rework starts."""
    import test_controller_rework as REWORK
    import test_controller_state as BASE
    import test_s5_process as S5
    root, task = ctrl_project("qa-words-door-life-")
    try:
        c = REWORK.story_to_s8(task)
        window = ("TC-1",)
        for name in ("a2", "a3"):                                  # the old life: the opener dS5-author and two rounds
            S5.dispatch(c, task, name, scope=window)
        text = refused_text(lambda: S5.dispatch(c, task, "a4", scope=window))
        old_author, old_critic = pass_blocks(text)
        story_pipeline(task)
        done, _, _ = open_door(root, f"`{door_spans(text)[0]}`", TICKET, "S5")
        recorded("life: the old life's round 3 pass", done, root, TICKET, "S5", old_author)
        check_eq("life: the recorded pass opens round 3 of the OLD life", refused_text(lambda: S5.dispatch(c, task, "a4", scope=window)), "")
        request = c.build_rework_request("S4", "qa-worker", ["TC-1"], REWORK.WORDS, words_given=True)
        check_eq("life fixture: a person's rework of S4 stamps S5 to run again", (request.get("rerun_after") or {}).get("stages")[:1], ["S5"])
        s5_apply(c, dict(request))
        REWORK.settle(c, task, request)
        state = c.state()
        check_eq("life fixture: the old life's dispatches are stale under the S4 rework's mark (counted 0 from here, A1)",
                 [(state["dispatches"][i]["status"], state["dispatches"][i].get("stale_by_rework")) for i in ("a2", "a3", "a4")],
                 [("stale", request["id"])] * 3)
        REWORK.redo(c, task, "S4", "dS4-again")
        c.apply("decision", BASE.bind_gate_a(task, {
            "id": "gate-a2", "gate": "A", "action": "approve", "status": "approved", "authorization_source": "human",
            "source_revision": "src-1", "scope": list(window), "input_revision": "src-1", "idempotency_key": "gate-a2"}))
        check_eq("life: the new life runs its opener and two rounds",
                 [refused_text(lambda: S5.dispatch(c, task, name, scope=window)) for name in ("n1", "n2", "n3")], ["", "", ""])
        again = refused_text(lambda: S5.dispatch(c, task, "n4", scope=window))
        check("life: round 3 of the new life IS refused (the old life's word is not read as this life's)", bool(again),
              "n4 went through: the old life's round 3 pass opened round 3 of the new life")
        if not again:
            return
        new_author, new_critic = pass_blocks(again)
        check("life: round 3 of the NEW life is refused although the old life's round 3 pass is recorded (old key "
              f"{old_author!r}, new key {new_author!r})", again.startswith(new_author + ": qa-automator has already had 2"), again[:160])
        check("life: the refusal prints the NEW key - round 3 again, another hash", new_author.startswith("round pass 3 for qa-automator on S5:")
              and new_author != old_author, f"old {old_author!r} new {new_author!r}")
        check("life: ...and the critic's pass has another hash too (round 1 in both lives)",
              new_critic.split(":")[0] == old_critic.split(":")[0] and new_critic != old_critic, f"old {old_critic!r} new {new_critic!r}")
        done, _, _ = open_door(root, f"`{door_spans(again)[0]}`", TICKET, "S5")
        recorded("life: the new life's round 3 pass", done, root, TICKET, "S5", new_author)
        check_eq("life: the new key opens round 3 of the new life", refused_text(lambda: S5.dispatch(c, task, "n4", scope=window)), "")
    finally:
        cleanup(root)


def row_person_rework_round_pass() -> None:
    """t-708 (F3; the t-698 spec 6 Q-b / R14 / edge 10 pin) through the REAL person-word rework (`--operation rework --words-file`,
    so the `reviews` stamp of an S5 rework stales the S5 critic): two reworks within the cap, the third refused with the key,
    the round-3 pass opens exactly round 3, and the critic's re-review past ITS cap passes with the same answer - the stamp's
    staling of the critic's reviews does not reset the critic's count (A1), which the plain dispatches of `row_round_pass_keys`
    never reach. Lives here, not in the test_controller_rework parts: the pass is recorded through the real waiver.py door, and the
    door helpers (`open_door`, `recorded`, `pass_blocks`) are this file's."""
    import test_controller_rework as REWORK
    from controller import Controller, repair_passes
    root, task = ctrl_project("qa-words-door-rework-")
    try:
        REWORK.story_to_s8(task)
        words = REWORK.words_file(task)
        window = ("TC-1",)
        critic_window = {"stage": "S5", "role": "qa-code-critic", "scope": list(window)}

        def rework_cli():
            """The person's words rework of S5 through the real CLI: (exit code, the new dispatch's id or the refusal's text)."""
            done = run_script("controller.py", "--task-root", str(task), "--operation", "rework", "--stage", "S5", "--role",
                              "qa-automator", "--cases", "TC-1", "--words-file", str(words), cwd=root, env=project_env(root))
            if done.returncode == 0:
                return 0, json.loads(done.stdout)["request"]["id"]
            return done.returncode, json.loads(done.stderr.strip().splitlines()[-1]).get("error", done.stderr)

        def settle_it(identifier):
            REWORK.settle(Controller(task), task, {"id": identifier})

        def review(name):
            return refused_text(lambda: critic_review(Controller(task), task, name, window))

        code, first = rework_cli()
        check_eq("rework: the first person's rework is accepted by the CLI", code, 0)
        settle_it(first)
        check_eq("rework: the critic's re-review is dispatched (its round 1)", review("k2"), "")
        code, second = rework_cli()
        check_eq("rework: the second person's rework is within the cap", code, 0)
        state = Controller(task).state()
        check_eq("rework: its stamp staled the critic's re-review (own stage: a paid round), with the mark",
                 (state["dispatches"]["k2"]["status"], state["dispatches"]["k2"].get("stale_by_rework")), ("stale", second))
        settle_it(second)
        check_eq("rework: the critic's second re-review is dispatched (its round 2: the critic is at its cap)", review("k3"), "")
        code, text = rework_cli()
        check("rework: the third rework is refused with the author's round 3 key",
              code != 0 and str(text).startswith("round pass 3 for qa-automator on S5:"), f"{code} {str(text)[:160]}")
        author, critic = pass_blocks(text)
        check_eq("rework: ...and the refusal prints the critic's own round 3 key as the second door",
                 critic.split(" on ")[0], "round pass 3 for qa-code-critic")
        story_pipeline(task)
        for index, key in enumerate((author, critic)):
            done, _, _ = open_door(root, f"`{door_spans(text)[index]}`", TICKET, "S5")
            recorded(f"rework: the pass {key.split(' on ')[0]}", done, root, TICKET, "S5", key)
        code, third = rework_cli()
        check_eq("rework: the author's pass opens round 3 (the rework is accepted by the CLI)", code, 0)
        state = Controller(task).state()
        check_eq("rework: its stamp staled the critic's k3 under the third rework's mark (the stamp was applied to this very rework)",
                 (state["dispatches"]["k3"]["status"], state["dispatches"]["k3"].get("stale_by_rework")), ("stale", third))
        settle_it(third)
        code, text = rework_cli()
        check("rework: ...exactly round 3 - the fourth rework is refused with round 4's own key",
              code != 0 and str(text).startswith("round pass 4 for qa-automator on S5:"), f"{code} {str(text)[:160]}")
        check_eq("rework: the critic's key now is the one printed before the stamp staled k3 (the staling reset nothing)",
                 repair_passes(Controller(task).state()["dispatches"], critic_window)["qa-code-critic"], critic)
        check_eq("rework: the critic's re-review past its cap passes with the same answer (its round 3)", review("k4"), "")
        check("rework: ...and its round 4 is refused with its own key", review("k5").startswith("round pass 4 for qa-code-critic on S5:"))
    finally:
        cleanup(root)


def door_spans(text: str) -> list:
    """Every waiver command a printed refusal carries, in the order printed."""
    return [s for s in SPAN.findall(text) if "waiver.py" in s]


def pass_blocks(text: str) -> list:
    """The `--block` word of each waiver door in a printed refusal (C1-5a: the round passes), in the order printed."""
    return [m.group(1) for span in door_spans(text) for m in [re.search(r'--block "([^"]+)"', span)] if m]


def row_8_not_receipted() -> None:
    import test_controller_rework_scope as SCOPED
    import test_controller_state as BASE
    import test_controller_release as REL
    root, task = ctrl_project("qa-words-door-receipt-")
    try:
        c = SCOPED.gate_a_task(task)
        s5_apply(c, {"id": "S5-qa-code-critic-1", "stage": "S5", "role": "qa-code-critic",
                             "scope": ["TC-1"], "input_hash": "s5", "budget": {}, "known_paths": {},
                             "idempotency_key": "d-critic"})
        REL.manifest(task)
        accept = {"id": "S5-qa-code-critic-1", "status": "accepted", "stage_complete": False, "unresolved": True,
                  "reason": "the window's second half is not reviewed yet",
                  "evidence_refs": [BASE.evidence_ref(task, "digest.txt")], "idempotency_key": "a-critic"}
        text = refused_text(lambda: c.apply("accept", dict(accept)))
        check_in("8 not receipted: a review with no receipts is refused", "not the person's to produce", text)
        waiver_door(root, task, "8 not receipted", text, "S5", "not receipted")
        check_eq("8 not receipted: the refusing code no longer refuses",
                 refused_text(lambda: c.apply("accept", dict(accept))), "")
    finally:
        cleanup(root)


def row_9_mechanical_round() -> None:
    import test_s5_process as S5
    from event_store import content_hash
    root, task = ctrl_project("qa-words-door-mround-")
    try:
        c = S5.s5_task(task, ("TC-1",))
        S5.dispatch(c, task, "a1", scope=("TC-1",))
        S5.dispatch(c, task, "k1", role="qa-code-critic", scope=("TC-1",))
        S5.dispatch(c, task, "a2", scope=("TC-1",), accept=False, repair_cause="mechanical",
                    reason="TC-1: a sleep -> a wait")
        plan = json.loads((task / "work" / "test-plan.json").read_text(encoding="utf-8"))
        obligation = next(ob for row in plan["rows"] for ob in row.get("coverage_obligations") or [])
        refs = [{"obligation_id": obligation["obligation_id"], "obligation_hash": content_hash(obligation)}]
        proof = S5.evidence(task, "proof.json")
        # a window reviewed and probed on its final bytes (H0 = H0): the author's mechanical dispatch
        # completes it only with the `mechanical_round` record, and this record has none
        instance = {"schema_version": 2, "instance_id": "test_x", "input_hash": "H0", "outcome": "passed",
                    "execution_fingerprint": "fp-1", "review": {"verdict": "approved", "input_hash": "H0"},
                    "change_disposition": "new_or_changed", "change_basis_ref": "diff",
                    "obligation_ids": [obligation["obligation_id"]], "obligation_refs": refs,
                    "obligation_hash": content_hash(refs), "assertion_id": "t.py:9", "defect_location": "src.py:4",
                    "probe": {"verdict": "intended_failure", "input_hash": "H0", "expected_location": "a",
                              "actual_location": "a", "expected_reason": "r", "actual_reason": "r",
                              "failure_kind": "assertion", "mutation_kind": "real_behavior",
                              "obligation_ids": [obligation["obligation_id"]], "obligation_refs": refs,
                              "obligation_hash": content_hash(refs), "assertion_id": "t.py:9",
                              "defect_location": "src.py:4", "evidence_ref": proof["path"]},
                    "evidence_refs": [proof]}
        record = {"schema_version": 2, "input_hash": "h", "required_quality_checks": [],
                  "author_dispatch_id": "a1", "reviewer_dispatch_id": "k1", "quality_receipts": [],
                  "scope_instances": {"TC-1": ["test_x"]}, "instances": [instance]}
        (task / "work").mkdir(exist_ok=True)
        (task / "work" / "s5-window.json").write_text(json.dumps(record), encoding="utf-8")
        import hashlib
        receipt = {"path": "work/s5-window.json",
                   "sha256": hashlib.sha256((task / "work" / "s5-window.json").read_bytes()).hexdigest()}

        def complete():
            return c.apply("accept", {"id": "a2", "status": "accepted", "stage_complete": True, "window": record,
                                      "evidence_refs": [proof, receipt], "idempotency_key": "done"})
        text = refused_text(complete)
        check_in("9 mechanical round: an author's window with no `mechanical_round` record is refused",
                 "no well-formed `mechanical_round`", text)
        waiver_door(root, task, "9 mechanical round", text, "S5", "mechanical round")
        check_eq("9 mechanical round: the refusing code no longer refuses", refused_text(complete), "")
    finally:
        cleanup(root)


def row_10_derived_scope() -> None:
    import test_fixes_13797 as FIX
    root, task = ctrl_project("qa-words-door-derived-")
    try:
        c = FIX.s6_story(task)
        text = FIX.runner(c, task, "S6-auto", "automation", ["TC-1"], True)
        check_in("10 derived scope: the automation half cannot complete S6 alone", "manual-agent case TC-2", text)
        waiver_door(root, task, "10 derived scope", text, "S6", "derived scope")
        check_eq("10 derived scope: the refusing code no longer refuses",
                 FIX.runner(c, task, "S6-auto", "automation", ["TC-1"], True), "")
    finally:
        cleanup(root)


def rows_12_30_release() -> None:
    """The spawn guard prints the release command for a receipt that still blocks (row 30) and
    `next` prints the same one for a dispatch nobody is doing (row 12): both name `--words-file
    <file>`, and the real controller releases the dispatch from the file. One S5 story; the
    release of the first dispatch frees the second."""
    import test_s5_process as S5
    from controller import Controller
    from unittest.mock import patch
    root, task = ctrl_project("qa-words-door-release-")
    try:
        c = S5.s5_task(task)
        S5.dispatch(c, task, "S5-qa-automator-1", accept=False)
        folder = root / "qa-factory" / "state" / "host-dispatches"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "a.json").write_text(json.dumps({
            "agent_id": "a", "agent_type": "qa-automator", "task_id": TICKET, "status": "running",
            "dispatch_id": "S5-qa-automator-1"}), encoding="utf-8")

        def spawn():
            event = {"tool_name": "spawn_agent", "tool_input": {"agent_type": "qa-automator", "message": "x"}}
            code, err = 0, io.StringIO()
            with patch("hooklib.project_root", return_value=root), \
                    patch("stage_guard.requested_ticket", return_value=TICKET), \
                    patch("host_capabilities.inspect", return_value={"story_ready": True}), \
                    redirect_stderr(err):
                import worker_lifecycle
                try:
                    worker_lifecycle.guard(event)
                except SystemExit as stop:
                    code = stop.code
            return code, err.getvalue()
        code, text = spawn()
        check_eq("30 release (spawn guard): a receipt that still blocks refuses the duplicate", code, 2)
        span = span_with(text, "--operation release")
        result = run_printed(root, task, "30 release (spawn guard)", span, task / "state" / "words" / "door.txt")
        check("30 release (spawn guard): the real controller releases from the file (exit 0)",
              result.returncode == 0, f"{result.returncode} {result.stdout[-300:]} {result.stderr[-300:]}")
        check_eq("30 release (spawn guard): the refusing code no longer refuses", spawn()[0], 0)
        # row 12: a second dispatch nobody is doing; `next` prints the door
        S5.dispatch(c, task, "S5-qa-automator-2", accept=False)
        action = Controller(task).next_action()
        check_eq("12 release (next): a running dispatch is waited on", action.get("action"), "wait_existing_job")
        span = action.get("release") or ""
        check("12 release (next): the field is the bare command (no backticks)", "`" not in span, span)
        result = run_printed(root, task, "12 release (next)", span, task / "state" / "words" / "door.txt")
        check("12 release (next): the real controller releases from the file (exit 0)",
              result.returncode == 0, f"{result.returncode} {result.stdout[-300:]} {result.stderr[-300:]}")
        done = json.loads(result.stdout) if result.returncode == 0 else {}
        check_eq("12 release (next): and says what it freed", done.get("dispatch_id"), "S5-qa-automator-2")
        check_eq("12 release (next): the refusing state no longer holds",
                 Controller(task).next_action().get("action") != "wait_existing_job", True)
        check_eq("12 release (next): the dispatch carries the person's words from the file, whole",
                 Controller(task).state()["dispatches"]["S5-qa-automator-2"].get("released_by_person"), WORDS)
    finally:
        cleanup(root)


def row_31_source_preflight() -> None:
    from source_preflight import check_source_inventory
    import test_ticket_adapter as TA
    root, task = ctrl_project("qa-words-door-gap-")
    try:
        work = task / "work"
        work.mkdir()
        path = work / "source-inventory.json"
        path.write_text(json.dumps({"schema_version": 1, "sources": [TA.gap_source()]}), encoding="utf-8")
        pipeline = {"source_inventory_required": True}
        errors = check_source_inventory(task, pipeline)["errors"]
        text = next((e for e in errors if "SRC-gap" in e and "not accepted by a person" in e), "")
        check("31 accept-gap: the S1 check refuses a source nobody accepted", bool(text), str(errors)[:300])
        span = span_with(text, "accept-gap")
        check_in("31 accept-gap: the printed door is the file form", f"{FLAG} <file>", span)
        # the door is run as printed: it names the inventory (`--output`, which ticket_adapter
        # requires) and the source id; only the `<id>` placeholder is filled
        check_in("31 accept-gap: the printed door names the inventory the check read", f"--output {path}", span)
        head = span[:span.index(FLAG)].replace("<id>", "SRC-gap").split()
        words = task / "state" / "words" / "door.txt"
        words.parent.mkdir(parents=True)
        words.write_bytes(WORDS.encode("utf-8"))
        done = run_script(head[0], *head[1:], FLAG, str(words), cwd=root, env=project_env(root))
        check("31 accept-gap: the real ticket_adapter records the printed door (exit 0)", done.returncode == 0,
              f"{done.returncode} {done.stdout} {done.stderr}")
        after = check_source_inventory(task, pipeline)["errors"]
        check_eq("31 accept-gap: the refusing code no longer refuses that source",
                 [e for e in after if "SRC-gap" in e and "not accepted by a person" in e], [])
    finally:
        cleanup(root)


# --- (c) a story in flight ---------------------------------------------------------------------

OLD_KEYWORDS = (("design review", "S4"), ("empty scope", "S3"), ("still running", "S9"),
                ("no accepted controller stage", "S0"), ("obligation-id", "S5"),
                ("story budget", "S5"), ("tracker route", "S1"), ("*", "S4"),
                # the controller's own advice of 0.7.x: each keyword is a substring of the error it
                # answers, and the new text keeps every byte before the words part
                ("empty scope", "S4"), ("empty scope", "S5"), ("mechanical repair round", "S5"),
                ("repair round", "S5"), ("not receipted", "S5"), ("mechanical round", "S5"),
                ("derived scope", "S6"))


def part_in_flight() -> None:
    """A pipeline.json recorded under the OLD advice still passes the NEW texts: invariant A (every
    byte before the words part is unchanged) means the advised `--block` keyword is still a
    substring of the error."""
    overrides = [{"stage": stage, "match": match, "decision": "recorded before the file form",
                  "at": "2026-09-30T10:00:00+00:00", "by": "human"} for match, stage in OLD_KEYWORDS]
    pipeline = {"ticket": "QA-1", "stages": {}, "stage_overrides": overrides}
    for keyword, stage in OLD_KEYWORDS:
        head = f"2 problem(s) about the {keyword if keyword != '*' else 'plan'} of this story"
        advised = person_words.door(f'waiver.py --task QA-1 --stage {stage} --block "{keyword}"')
        _, passed = waiver.split_overridden([f"{head}. A person's word passes it: `{advised}`."], pipeline, stage)
        check_eq(f"in flight: an override recorded under `{keyword}` passes a text with the file-form door",
                 len(passed), 1)
    # and the real texts of this node, with the real stage logic
    root = temp_project("qa-words-inflight-")
    try:
        use_project(root)
        art = S0.story(root)
        data = json.loads((art / "pipeline.json").read_text(encoding="utf-8"))
        data["stage_overrides"] = overrides
        data["stages"] = {"S5": {"status": "running", "role": None, "digest": ""}}
        (art / "pipeline.json").write_text(json.dumps(data), encoding="utf-8")
        code, _, err = captured(lambda: stage_done.run(S0.TASK, "S9", "done", None, "retro done", True))
        # (0.8.1: the close of S9 has checks of its own that this fixture does not satisfy - see row 14; the
        # old override is read when the refusal about the running stage is gone and the word is quoted)
        check_not_in("in flight: S9 no longer refuses over a running stage on the old `still running` override",
                     "is still running", err)
        check_in("in flight: and closes over it on the person's word",
                 "closing S9 over a running stage on the person's word", err)
        S0.initialize(art)
        data = json.loads((art / "pipeline.json").read_text(encoding="utf-8"))
        data["stages"]["S0"] = {"status": "running", "role": None, "digest": ""}
        (art / "pipeline.json").write_text(json.dumps(data), encoding="utf-8")
        check_eq("in flight: a managed stage closes on the old `no accepted controller stage` override",
                 S0.close(art)[0], 0)
        story = {"ticket": "QA-1", "stage_overrides": overrides}
        hinted = stage_guard.waiver_hint("QA-1", "S1", "dispatching qa-scout (S1) is blocked — tracker route x")
        check_eq("in flight: the old `tracker route` override passes the guard's hint-carrying text",
                 len(waiver.split_overridden(["dispatching qa-scout (S1) is blocked — tracker route x " + hinted],
                                             story, "S1")[1]), 1)
        import story_budget
        check_eq("in flight: the old `story budget` override is read by the budget",
                 bool(story_budget.override(story)), True)
    finally:
        cleanup(root)
    root, task = OJ.make_story()
    try:
        (task / "pipeline.json").write_text(json.dumps({"ticket": OJ.TICKET, "stage_overrides": overrides}),
                                            encoding="utf-8")
        fragment = {"obligation_bindings": [{"obligation_id": "OB-1", "instance_ids": ["test_ok"]}]}
        check_eq("in flight: the old `obligation-id` override passes manifest_put", OJ.put(root, fragment).returncode, 0)
    finally:
        cleanup(root)


# --- (d) the real launcher -----------------------------------------------------------------------

def part_launcher() -> None:
    if not WIN:
        print("SKIPPED: not Windows (the cmd route was not run)")
        return
    root = temp_project("qa-words-launcher-")
    work = temp_dir("qa words launcher ")
    env = dict(project_env(root), QA_FACTORY_PYTHON=sys.executable)
    env.pop("QA_FACTORY_LAUNCHER", None)
    try:
        story_with(root, "QA-1", {})

        def launch(tail: str):
            proc = subprocess.run(f'"{LAUNCHER}" waiver.py --task QA-1 --stage S1 {tail}', shell=True,
                                  capture_output=True, cwd=str(work), env=env, timeout=300)
            return proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace")
        words = work / "the words.txt"
        words.write_bytes(WORDS.encode("utf-8"))
        code, out, err = launch(f'--block "x" {FLAG} "{words}"')
        check("launcher: the file door records through run-py.cmd", code == 0, f"{code} {out} {err}")
        check_eq("launcher: the override carries the file's words whole",
                 [o["decision"] for o in overrides_of(root, "QA-1") if o["match"] == "x"], [WORDS.strip()])
        code, out, err = launch('--block "y" --decision "one line"')
        check("launcher: the same door with inline words is refused", code != 0, f"{code} {out} {err}")
        check_in("launcher: and the refusal names the file form", FLAG, err)
        check_eq("launcher: nothing was recorded for it", [o for o in overrides_of(root, "QA-1") if o["match"] == "y"], [])
    finally:
        cleanup(work)
        cleanup(root)


def row_settle_order() -> None:
    """GB-1a (t-1509): `settle_order` takes a person's words through `person_words.read` like `release` does - `--words-file` whole,
    both options at once refused before any event - and the refusal of a cancel with neither words nor a coded reason prints the
    file form of its door."""
    import test_gate_b_orders as GB
    root = temp_project("qa-words-settle-")
    try:
        c = GB.synthetic(root, drafts=("a",), mr="open")
        words = root / "state" / "words" / "settle-1.txt"
        words.parent.mkdir(parents=True, exist_ok=True)
        words.write_bytes(WORDS.encode("utf-8"))
        revision = c.state()["revision"]
        base = ("controller.py", "--task-root", str(root), "--operation", "settle_order", "--order", "mr", "--outcome", "cancelled")
        both = run_script(*base, "--words", "inline", FLAG, str(words), cwd=root, env=project_env(root))
        check("settle: both options at once are refused (exit 2) before any event", both.returncode == 2, both.stderr[-300:])
        none = run_script(*base, cwd=root, env=project_env(root))
        check("settle: no words and no coded reason is refused, naming the file form of the door",
              none.returncode == 2 and f"--operation settle_order --order <order> --outcome cancelled {FLAG} <file>" in none.stderr, none.stderr[-400:])
        check_eq("and nothing was written", c.state()["revision"], revision)
        done = run_script(*base, FLAG, str(words), cwd=root, env=project_env(root))
        check("settle: the file form passes", done.returncode == 0, done.stderr[-300:])
        check_eq("and the record holds the file's words whole (FR-8)",
                 c.state()["decisions"]["gateB-" + root.name]["orders_settled"]["mr"]["words"], WORDS)
    finally:
        cleanup(root)


def row_leave_unlaunched() -> None:
    """C1-6a (t-1151, A3 and A11): the two ops that take a person's words for the work a closed story held back read them through
    `person_words.read` like `release` does - `--words-file` whole, both options at once refused before any event - and the closure
    refusal prints the file form of its door. The `rework` refusal for a LIVE dispatch names both of the conductor's own doors."""
    import test_story_closed as CLOSED
    root, task = ctrl_project("qa-words-leave-")
    try:
        controller = CLOSED.closed_story(task)
        CLOSED.never_started(controller, "S6-qa-runner-9", stage="S6", role="qa-worker", rework_of="S6-qa-runner-1")
        door = refused_text(lambda: controller.apply("dispatch", dict(CLOSED.packet("S3-x-1"), idempotency_key="k1")))
        check_in("leave: the closure refusal prints the file form of its door", f"--operation reopen_story --dispatch <the held dispatch ids> {FLAG} <file>", door)
        words = task / "state" / "words" / "leave-1.txt"
        words.parent.mkdir(parents=True, exist_ok=True)
        revision = controller.state()["revision"]
        words.write_bytes(WORDS.encode("utf-8"))
        both = run_script("controller.py", "--task-root", str(task), "--operation", "leave_unlaunched", "--dispatch", "S6-qa-runner-9",
                          "--words", "inline", FLAG, str(words), cwd=root, env=project_env(root))
        check("leave: both options at once are refused (exit 2) before any event", both.returncode == 2, both.stderr[-300:])
        none = run_script("controller.py", "--task-root", str(task), "--operation", "leave_unlaunched", "--dispatch", "S6-qa-runner-9",
                          cwd=root, env=project_env(root))
        check("leave: no words at all is refused as well", none.returncode != 0, none.stderr[-300:])
        check_eq("and nothing was written", controller.state()["revision"], revision)
        done = run_script("controller.py", "--task-root", str(task), "--operation", "leave_unlaunched", "--dispatch", "S6-qa-runner-9",
                          FLAG, str(words), cwd=root, env=project_env(root))
        check("leave: the file form passes", done.returncode == 0, done.stderr[-300:])
        check_eq("and the record holds the file's words whole (FR-8)", controller.state()["dispatches"]["S6-qa-runner-9"].get("left_by_person"), WORDS)
        # A11: the rework refusal when a LIVE dispatch of the role exists on the stage, and today's text when there is none
        CLOSED.stray(controller, "S4-qa-live-1", stage="S4", role="qa-live")
        live = refused_text(lambda: controller.build_rework_request("S4", "qa-live", [], "x"))
        check_in("rework: a live dispatch is named with its status", "S4-qa-live-1 is running, not accepted", live)
        check_in("rework: and the resume door", "answer `continue`", live)
        check_in("rework: and the release door in the file form", "release --dispatch S4-qa-live-1 --words-file <their words>", live)
        plain = refused_text(lambda: controller.build_rework_request("S4", "qa-nobody", [], "x"))
        check("rework: a role with no dispatch on the stage keeps today's text", "no accepted qa-nobody dispatch on S4 to rework; accepted roles on S4:" in plain
              and "is running" not in plain, plain)
    finally:
        cleanup(root)


def row_words_carry() -> None:
    """GW1-40 (AR-24): `waiver.py --carry-from` copies words that were already recorded, so it needs no `--words-file` and prints no door of
    words: nothing it prints (success, partial, any refusal) holds an inline words part, and the conductor's row for it (`words_carry` in
    the `actions` of conductor-actions.json, not in `moves`) holds none either."""
    row = next((a for a in json.loads((PLUGIN_ROOT / "references" / "conductor-actions.json").read_text(encoding="utf-8"))["actions"]
                if a.get("id") == "words_carry"), None)
    check("carry: the conductor has a row `words_carry` among the actions", row is not None)
    check_eq("carry: ... and it is not among the `moves` (whose key set another table holds equal)",
             any(m.get("id") == "words_carry" for m in json.loads((PLUGIN_ROOT / "references" / "conductor-actions.json").read_text(
                 encoding="utf-8"))["moves"]), False)
    for field in ("says", "run"):
        check_eq(f"carry: the row's `{field}` carries no inline words part", hits_in(str((row or {}).get(field) or "")), [])
    check_in("carry: the row names the form", "waiver.py --carry-from <old key> --task <new key>", (row or {}).get("run", ""))
    root = temp_project("qa-words-door-carry-")
    try:
        use_project(root)
        old = story_with(root, "OLD-1", {})
        pipeline = json.loads((old / "pipeline.json").read_text(encoding="utf-8"))
        pipeline["stage_overrides"] = [{"stage": "S1", "match": "source material unavailable", "decision": "go on", "at": "2026-10-01T10:00:00+00:00"},
                                       {"stage": "S5", "match": "executor unavailable: e2e-ui", "decision": "mine", "at": "2026-10-01T10:00:00+00:00"}]
        (old / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        story_with(root, "NEW-1", {})
        texts = []
        for args in (("--carry-from", "OLD-1", "--task", "NEW-1"), ("--carry-from", "OLD-1", "--task", "NEW-1"),
                     ("--carry-from", "NOPE", "--task", "NEW-1"), ("--carry-from", "OLD-1", "--task", "OLD-1"),
                     ("--carry-from", "../x", "--task", "NEW-1"), ("--carry-from", "OLD-1", "--task", "NO-STORY"),
                     ("--carry-from", "OLD-1", "--stage", "S1", "--task", "NEW-1")):
            done = run_script("waiver.py", *args, cwd=root, env=project_env(root))
            texts.append(done.stdout + "\n" + done.stderr)
        check_eq("carry: the carry ran (a line `carried:` printed once, then `already carried`)",
                 ("carried: S1 · source material unavailable" in texts[0], "already carried:" in texts[1]), (True, True))
        check_eq("carry: every refusal printed something to read", [bool(t.strip()) for t in texts], [True] * len(texts))
        for n, text in enumerate(texts):
            check_eq(f"carry: output {n} holds no inline words part (the form needs no words file)", hits_in(text), [])
            if not text.lstrip().startswith("usage:"):      # argparse's own usage line lists every option of the CLI: not a door
                check_not_in(f"carry: output {n} names no words option", "--words-file", text)
    finally:
        cleanup(root)


def main() -> None:
    row_words_carry()
    row_settle_order()
    row_leave_unlaunched()
    part_renderer()
    part_detector()
    registry_texts()
    row_13_rehearsal()
    row_14_still_running()
    row_15_16_controller_stage()
    row_17_stage_guard_hint()
    row_19_20_21_detectors()
    row_22_manifest_put()
    row_23_24_story_budget()
    row_block_names()
    row_25_readiness_and_tracker_route()
    row_1_2_design_review()
    row_3_empty_scope_at_gate_a()
    rows_4_5_11_dispatch_doors()
    rows_6_7_repair_rounds()
    row_round_pass_keys()
    row_pass_key_counting_and_life()
    row_pass_life_end_to_end()
    row_person_rework_round_pass()
    row_8_not_receipted()
    row_9_mechanical_round()
    row_10_derived_scope()
    rows_12_30_release()
    row_31_source_preflight()
    part_in_flight()
    part_launcher()
    part_doors_hold_the_whole_words_clause()
    finish("test_words_doors")


if __name__ == "__main__":
    main()
