#!/usr/bin/env python3
"""Fold the changelog fragments of `changelog.d/` into the next version section of CHANGELOG.md.

Why it exists (team-work plan 3.5, node F0-5): CHANGELOG.md was written by every batch, so two
developers' branches both edited its top and every merge conflicted. Now a batch writes one file,
`changelog.d/<pile>-<batch>-<slug>.md`, and only the release touches CHANGELOG.md, once, here.

    python scripts/changelog_assemble.py --list
    python scripts/changelog_assemble.py --version 0.9.1 --date 2026-10-15 --title "what this release is" [--dry-run]

The section `## <version> - <date> - <title>` (em dashes, like every heading in CHANGELOG.md) goes
right after the title block of CHANGELOG.md, before the current top `## ` section; its body is the
fragments' text, sorted by file name, one blank line between fragments. The fragment files are then
deleted. stdout carries the inserted section and nothing else (FR-14: a caller parses it); every
refusal goes to stderr with exit 2 in the FR-1 form: what is wrong, what was expected, how to pass.
Also refused, in the dry run too: a version that already has a `## <version>` heading in CHANGELOG.md (a `## `
line inside a fenced code block is text, not a heading), and any file in `changelog.d/` other than README.md
that is not named `*.md` in lower case (nothing ships unseen; `--list` shows it as `REFUSED <name>`).

What a fragment may hold is what `selftest.py --lang` accepts of any package file: no Cyrillic
character and none of the control bytes an eaten escape leaves (FR-30, FR-29). The two predicates
below are COPIES of `selftest.CYRILLIC` and `selftest.CONTROL_BYTES` (importing selftest would pull
the whole test runner into a release tool); `test_changelog_assemble.py` pins them equal. The rest
of the non-ASCII range (the em dash, an arrow) is allowed: the existing sections use it.

The rest of CHANGELOG.md is not touched, byte for byte; the new section is written with the file's
own line ending (the ending of its title line), whichever it is.
"""
import argparse
import datetime
import os
import re
import sys
import unicodedata
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
FRAGMENT_DIR = "changelog.d"
README_NAME = "README.md"
CHANGELOG_NAME = "CHANGELOG.md"
DASH = "—"

VERSION_RE = re.compile(r"\d+\.\d+\.\d+")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
TITLE_LINE_RE = re.compile(r"# \S")
HEADING_RE = re.compile(r" {0,3}#{1,6}(?:\s|$)")
SECTION_RE = re.compile(r"## ")
FENCE_RE = re.compile(r" {0,3}(`{3,}|~{3,})(.*)")
LINE_SPLIT_RE = re.compile(r"\r\n|\r|\n")

# Copies of selftest.CYRILLIC / selftest.CONTROL_BYTES (the `--lang` rule); built from code points
# so that this file stays Cyrillic-free and free of control bytes itself.
CYRILLIC = re.compile("[" + chr(0x0400) + "-" + chr(0x04FF) + "]")
CONTROL_BYTES = {7: "0x07 (bell)", 8: "0x08 (an eaten backslash-b)", 11: "0x0b (vertical tab)",
                 12: "0x0c (an eaten backslash-f)"}
MAX_REPORTED_PER_FILE = 3


class Refusal(Exception):
    """A refusal in the FR-1 form; `str()` is the whole text printed to stderr."""

    def __init__(self, wrong, expected, door):
        super().__init__(f"changelog_assemble: refused - {wrong}\n  expected: {expected}\n  to pass: {door}")


def fragment_paths(root):
    """([fragments], [refused]): every file of changelog.d/ except README.md is a fragment when its name ends in
    a lower-case `.md`, else it is refused (nothing ships unseen, FR-4); both lists sorted by name."""
    folder = root / FRAGMENT_DIR
    if not folder.is_dir():
        return [], []
    files = sorted((p for p in folder.iterdir() if p.is_file() and p.name != README_NAME), key=lambda p: p.name)
    return ([p for p in files if p.name.endswith(".md")], [p for p in files if not p.name.endswith(".md")])


def text_problems(text):
    """The `--lang` rule on a text: [(line number, what)] for the first offenders."""
    found = []
    for number, line in enumerate(LINE_SPLIT_RE.split(text), start=1):
        for ch in line:
            if CYRILLIC.match(ch):
                found.append((number, f"U+{ord(ch):04X} {unicodedata.name(ch, 'CYRILLIC')} (Cyrillic)"))
            elif ord(ch) in CONTROL_BYTES:
                found.append((number, f"control byte {CONTROL_BYTES[ord(ch)]}"))
    return found


def read_fragment(path):
    """(normalised lines, problems). Trailing whitespace and the blank edges are normalised, never refused."""
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError as e:
        return [], [f"{path.name}: not valid UTF-8 (byte {e.start})"]
    problems = [f"{path.name}: line {n}: {what}" for n, what in text_problems(text)[:MAX_REPORTED_PER_FILE]]
    lines = [line.rstrip() for line in LINE_SPLIT_RE.split(text)]
    for n, line in enumerate(lines, start=1):
        if HEADING_RE.match(line):
            problems.append(f"{path.name}: line {n}: a heading line ({line[:40]!r})")
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    if not lines:
        problems.append(f"{path.name}: no content (empty or only blank lines)")
    return lines, problems


def check_arguments(version, date, title):
    if not version or not VERSION_RE.fullmatch(version):
        raise Refusal("--version is missing" if version is None else f"--version {version!r} is not a version",
                      "three dot-separated numbers, like 0.9.1",
                      "pass --version 0.9.1 (the version the release bump sets)")
    if not date or not DATE_RE.fullmatch(date):
        raise Refusal("--date is missing" if date is None else f"--date {date!r} is not an ISO date",
                      "YYYY-MM-DD, like 2026-10-15", "pass --date 2026-10-15")
    try:
        datetime.date.fromisoformat(date)
    except ValueError:
        raise Refusal(f"--date {date!r} is not a calendar date", "a real day, YYYY-MM-DD", "pass --date 2026-10-15")
    if not title or not title.strip() or LINE_SPLIT_RE.search(title.strip()):
        raise Refusal("--title is missing, empty or spans several lines", "one line of text naming the release",
                      "pass --title \"what this release is\" (the words after the second dash of the heading)")
    bad = text_problems(title)
    if bad:
        raise Refusal(f"--title carries {bad[0][1]}", "English text, like every package file (FR-30)",
                      "write the title in English")


def build_section(version, date, title, bodies):
    """The inserted section, LF endings, one trailing newline."""
    heading = f"## {version} {DASH} {date} {DASH} {title.strip()}"
    return heading + "\n\n" + "\n\n".join("\n".join(lines) for lines in bodies) + "\n"


def read_changelog(root):
    path = root / CHANGELOG_NAME
    if not path.is_file():
        raise Refusal(f"{CHANGELOG_NAME} does not exist at {path}", "the package's changelog",
                      "run the script from the package (scripts/changelog_assemble.py of ai-packages/qa-factory)")
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        raise Refusal(f"{CHANGELOG_NAME} is not valid UTF-8", "a UTF-8 file", "restore the file from git")
    first = text.split("\n", 1)[0].rstrip("\r")
    if not TITLE_LINE_RE.match(first):
        raise Refusal(f"{CHANGELOG_NAME} has no title on its first line (found {first[:40]!r})",
                      "a first line like '# Changelog'", f"restore the title line of {CHANGELOG_NAME}")
    newline = "\r\n" if text.split("\n", 1)[0].endswith("\r") else "\n"
    return path, text, newline


def section_headings(text):
    """[(offset, line)] of the `## ` lines that are headings: a `## ` line inside a fenced code block is text."""
    found, fence, offset = [], None, 0
    for line in text.split("\n"):
        bare = line.rstrip("\r")
        match = FENCE_RE.match(bare)
        if fence is None:
            if match and not (match.group(1)[0] == "`" and "`" in match.group(2)):
                fence = match.group(1)
            elif SECTION_RE.match(bare):
                found.append((offset, bare))
        elif match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence) \
                and not match.group(2).strip():
            fence = None
        offset += len(line) + 1
    return found


def insert_section(text, section_lf, newline):
    """The text with the section in place: before the first `## ` heading, else at the end."""
    section = section_lf.replace("\n", newline)
    headings = section_headings(text)
    if headings:
        start = headings[0][0]
        return text[:start] + section + newline + text[start:]
    return text.rstrip("\r\n") + newline + newline + section


def refuse_existing_version(text, version):
    """A heading `## <version>` (followed by a space or the end of the line) already in CHANGELOG.md."""
    wanted = re.compile(re.escape(version) + r"(?:\s|$)")
    for offset, line in section_headings(text):
        if wanted.match(line[3:]):
            number = text.count("\n", 0, offset) + 1
            raise Refusal(f"{CHANGELOG_NAME} already has a section for {version} (line {number}: {line[:60]!r})",
                          "a version that is not in the changelog yet",
                          "pass the next --version; if the existing section was written by mistake, remove it from "
                          f"{CHANGELOG_NAME} by hand first")


def refuse_unseen_files(refused):
    if refused:
        raise Refusal(f"{FRAGMENT_DIR}/ holds file(s) that are not fragments: {', '.join(p.name for p in refused)}",
                      f"only {README_NAME} and fragments named <pile>-<batch>-<slug>.md (a lower-case .md) in "
                      f"{FRAGMENT_DIR}/",
                      "rename a fragment to end in .md, or move or delete the file: nothing in this folder ships "
                      "unseen")


def assemble(root, version, date, title, dry_run):
    check_arguments(version, date, title)
    path, text, newline = read_changelog(root)
    fragments, refused = fragment_paths(root)
    refuse_unseen_files(refused)
    if not fragments:
        raise Refusal(f"no fragments in {FRAGMENT_DIR}/ - there is nothing to fold into {version}",
                      f"at least one {FRAGMENT_DIR}/<pile>-<batch>-<slug>.md besides {README_NAME}",
                      f"write the batch's lines into a fragment (see {FRAGMENT_DIR}/{README_NAME}), "
                      "or release without a changelog section on purpose by editing CHANGELOG.md by hand")
    refuse_existing_version(text, version)
    bodies, problems = [], []
    for fragment in fragments:
        lines, found = read_fragment(fragment)
        bodies.append(lines)
        problems.extend(found)
    if problems:
        raise Refusal("; ".join(problems),
                      "English text (no Cyrillic, no control bytes), no heading lines, some content "
                      "(the same rule as selftest.py --lang)",
                      f"fix the named fragment(s) in {FRAGMENT_DIR}/; a heading belongs to the release, "
                      "which this script writes")
    section = build_section(version, date, title, bodies)
    if not dry_run:
        write_changelog(path, insert_section(text, section, newline))
        for fragment in fragments:
            fragment.unlink()
    return section


def write_changelog(path, text):
    temp = path.with_name(path.name + ".assemble.tmp")
    try:
        temp.write_bytes(text.encode("utf-8"))
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def emit(text):
    """stdout as UTF-8 bytes with LF, so the section reads the same on every platform."""
    stream = sys.stdout
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        stream.flush()
        buffer.write(text.encode("utf-8"))
        buffer.flush()
    else:
        stream.write(text)


def main(argv=None, root=None):
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    root = Path(root) if root else PACKAGE_ROOT
    ap = argparse.ArgumentParser(description="Fold changelog.d/ fragments into the next CHANGELOG.md section.")
    ap.add_argument("--version", help="the release version, like 0.9.1")
    ap.add_argument("--date", help="the release date, YYYY-MM-DD")
    ap.add_argument("--title", help="the release title (one line, English)")
    ap.add_argument("--list", action="store_true", help="print the fragments and exit")
    ap.add_argument("--dry-run", action="store_true", help="print the section, write nothing")
    args = ap.parse_args(argv)
    if args.list:
        fragments, refused = fragment_paths(root)
        lines = [p.name for p in fragments] or ["no fragments"]
        emit("\n".join(lines + [f"REFUSED {p.name}" for p in refused]) + "\n")
        return 0
    try:
        emit(assemble(root, args.version, args.date, args.title, args.dry_run))
    except Refusal as refusal:
        print(refusal, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
