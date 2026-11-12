#!/usr/bin/env python3
"""changelog_assemble.py folds changelog.d/ fragments into the next CHANGELOG.md section (node F0-5).

Every case runs the REAL script as a child process on a throw-away copy of the package layout
(scripts/changelog_assemble.py + CHANGELOG.md + changelog.d/), and compares BYTES: the section lands
before the current top `## ` heading in the file's own line ending, the fragments are sorted by name
and deleted, stdout is exactly the inserted section, the rest of the file is untouched.

CA1 assemble: place, order, normalisation (trailing spaces, no final newline, leading blank lines), fragments gone, stdout.
CA2 --list (fragments in order, README never one, 0 fragments says so); --dry-run leaves every byte alone.
CA3 refusals (exit 2, FR-1 form, nothing written or deleted): no fragments, Cyrillic, control byte, heading, empty
    fragment, invalid UTF-8, bad version / date / title, a CHANGELOG without a title line or missing.
CA3b a version already in CHANGELOG.md (also in the dry run; a fenced `## ` line is text) and a file in changelog.d/
    that is not README.md or a lower-case *.md (refused by name; `--list` shows `REFUSED <name>`).
CA4 line endings: CRLF stays CRLF with no bare LF added, stdout stays LF; a title-only CHANGELOG gets the section appended.
CA5 the `--lang` rule is a copy and is pinned to selftest's own predicate.

Mutations this file kills (each by this file alone):
  the section inserted after the top section (CA1) | fragments in directory order (CA1) | fragments left on disk
  (CA1) | --dry-run writing (CA2) | README taken as a fragment (CA2) | the Cyrillic check dropped (CA3) | the
  heading check dropped (CA3) | the version pattern loosened to \\d+\\.\\d+ (CA3) | CRLF written as LF (CA4) |
  CYRILLIC range changed (CA5) | the duplicate-version check dropped or fence-blind (CA3b) | a non-.md file ignored
  again (CA3b)

Run: python -B scripts/tests/test_changelog_assemble.py        (from ai-packages/qa-factory)
     python -m pytest ai-packages/qa-factory/scripts/tests/test_changelog_assemble.py -q   (from the repository root)
"""
import atexit
import functools
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT, RESULTS, check, check_eq, check_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

SCRIPT = PLUGIN_ROOT / "scripts" / "changelog_assemble.py"
CONSOLE_IO = PLUGIN_ROOT / "scripts" / "console_io.py"
DASH = "—"
ZHE = chr(0x0416)                      # a Cyrillic capital letter, built from its code point: this file stays ASCII
SECTIONS = (f"## 0.3.0 {DASH} 2026-01-03 {DASH} third\n\n- c1\n\n"
            f"## 0.2.0 {DASH} 2026-01-02 {DASH} second\n\n- b1\n\n"
            f"## 0.1.0 {DASH} 2026-01-01 {DASH} first\n\n- a1\n")
CHANGELOG = "# Changelog\n\nPointer line.\n\n" + SECTIONS
VERSION, DATE, TITLE = "0.9.1", "2026-10-15", "folded fragments"
HEADING = f"## {VERSION} {DASH} {DATE} {DASH} {TITLE}"
FRAG_B = b"\n\n- Beta change.   "                                   # no final newline, trailing spaces, blank lead
FRAG_A = b"- Alpha change (`a.py`): why.  \r\n  continuation   \r\n\r\n\r\n"      # CRLF, trailing blank lines
BODY = "- Alpha change (`a.py`): why.\n  continuation\n\n- Beta change.\n"
SECTION = HEADING + "\n\n" + BODY
ASSEMBLE = ["--version", VERSION, "--date", DATE, "--title", TITLE]
ROOTS = []


def tree(changelog, fragments, readme=True):
    """A throw-away package layout; `changelog` None = no CHANGELOG.md. The fragments are written in the
    order given, which is the REVERSE of the sorted order in most cases below."""
    root = temp_dir("qa-changelog-assemble-")
    ROOTS.append(root)
    (root / "scripts").mkdir()
    shutil.copy(SCRIPT, root / "scripts" / SCRIPT.name)
    shutil.copy(CONSOLE_IO, root / "scripts" / CONSOLE_IO.name)
    folder = root / "changelog.d"
    folder.mkdir()
    if readme:
        (folder / "README.md").write_bytes(b"# readme, never a fragment\n")
    for name, data in fragments.items():
        (folder / name).write_bytes(data)
    if changelog is not None:
        (root / "CHANGELOG.md").write_bytes(changelog if isinstance(changelog, bytes) else changelog.encode("utf-8"))
    return root


def run(root, *args):
    return subprocess.run([sys.executable, "-B", str(root / "scripts" / SCRIPT.name), *args],
                          capture_output=True, cwd=str(root), timeout=120)


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def case(fn):
    """One pytest-visible case: the harness `check`s record, the wrapper fails the case on a new FAIL."""
    @functools.wraps(fn)
    def wrapper():
        before = sum(1 for ok, _ in RESULTS if not ok)
        fn()
        failed = [name for ok, name in RESULTS if not ok]
        assert len(failed) == before, f"{fn.__name__}: {failed[before:]}"
    return wrapper


def refused(label, root, args, *needles, keep=True):
    before = snapshot(root)
    r = run(root, *args)
    err = r.stderr.decode("utf-8", errors="replace")
    check_eq(f"{label}: exit 2", r.returncode, 2)
    check_eq(f"{label}: stdout is empty", r.stdout, b"")
    for needle in needles:
        check_in(f"{label}: the refusal names {needle!r}", needle, err)
    check_in(f"{label}: the refusal says what to do (FR-1)", "to pass:", err)
    if keep:
        check(f"{label}: nothing written or deleted", snapshot(root) == before)


@case
def test_ca1_assemble_places_orders_and_cleans():
    root = tree(CHANGELOG, {"forge-2-beta.md": FRAG_B, "forge-1-alpha.md": FRAG_A})
    r = run(root, *ASSEMBLE)
    check_eq("CA1 exit 0", r.returncode, 0)
    expected = "# Changelog\n\nPointer line.\n\n" + SECTION + "\n" + SECTIONS
    check_eq("CA1 the section sits before the top section; order by file name; the rest is untouched",
             (root / "CHANGELOG.md").read_bytes(), expected.encode("utf-8"))
    check_eq("CA1 stdout is exactly the inserted section", r.stdout, SECTION.encode("utf-8"))
    check_eq("CA1 stderr is empty", r.stderr, b"")
    check_eq("CA1 the fragments are gone, the README stays", sorted(p.name for p in (root / "changelog.d").iterdir()),
             ["README.md"])


@case
def test_ca2_list_and_dry_run():
    root = tree(CHANGELOG, {"forge-2-beta.md": FRAG_B, "forge-1-alpha.md": FRAG_A})
    r = run(root, "--list")
    check_eq("CA2 --list exit 0", r.returncode, 0)
    check_eq("CA2 --list prints the fragments in name order, never the README", r.stdout,
             b"forge-1-alpha.md\nforge-2-beta.md\n")
    before = snapshot(root)
    r = run(root, *ASSEMBLE, "--dry-run")
    check_eq("CA2 --dry-run exit 0", r.returncode, 0)
    check_eq("CA2 --dry-run prints the section", r.stdout, SECTION.encode("utf-8"))
    check("CA2 --dry-run leaves every file byte for byte as it was", snapshot(root) == before)
    empty = tree(CHANGELOG, {})
    r = run(empty, "--list")
    check_eq("CA2 --list with only the README: exit 0", r.returncode, 0)
    check_eq("CA2 --list with only the README says so", r.stdout, b"no fragments\n")
    r = run(tree(CHANGELOG, {}, readme=False), "--list")
    check_eq("CA2 --list with the folder empty: exit 0, says so", (r.returncode, r.stdout), (0, b"no fragments\n"))


@case
def test_ca3_refusals_are_loud_and_leave_everything():
    frag = {"forge-1-alpha.md": FRAG_A}
    root = tree(CHANGELOG, frag)
    done = run(root, *ASSEMBLE)
    check_eq("CA3 setup: the first assemble passes", done.returncode, 0)
    refused("CA3 a second assemble with no fragments", root, ASSEMBLE, "no fragments")
    refused("CA3 no fragments, only the README", tree(CHANGELOG, {}), ASSEMBLE, "no fragments")
    refused("CA3 Cyrillic in a fragment", tree(CHANGELOG, {"forge-1-ok.md": FRAG_A, "forge-3-bad.md":
            f"- line one\n- caf{ZHE} here\n".encode("utf-8")}), ASSEMBLE, "forge-3-bad.md", "line 2", "U+0416")
    refused("CA3 a control byte (an eaten backslash-b) in a fragment", tree(CHANGELOG, {"forge-1-bell.md":
            b"- a \x08 b\n"}), ASSEMBLE, "forge-1-bell.md", "0x08")
    refused("CA3 a heading line in a fragment", tree(CHANGELOG, {"forge-1-head.md": b"- ok\n## 0.9.1\n- x\n"}),
            ASSEMBLE, "forge-1-head.md", "heading", "line 2")
    refused("CA3 a heading inside a code fence is refused too", tree(CHANGELOG, {"forge-1-fence.md":
            b"- ok\n```\n# not a heading but looks like one\n```\n"}), ASSEMBLE, "forge-1-fence.md", "heading")
    refused("CA3 an empty fragment", tree(CHANGELOG, {"forge-1-empty.md": b"  \n\n"}), ASSEMBLE, "forge-1-empty.md",
            "no content")
    refused("CA3 a fragment that is not UTF-8", tree(CHANGELOG, {"forge-1-bytes.md": b"- \xff\xfe\n"}), ASSEMBLE,
            "forge-1-bytes.md", "UTF-8")
    for bad in ("0.9", "v0.9.1", "0.9.1.2", "a.b.c", ""):
        refused(f"CA3 --version {bad!r}", tree(CHANGELOG, frag), ["--version", bad, "--date", DATE, "--title", TITLE],
                "--version")
    refused("CA3 --version missing", tree(CHANGELOG, frag), ["--date", DATE, "--title", TITLE], "--version")
    for bad in ("15.10.2026", "20261015", "2026-13-40", "2026-02-30", "yesterday"):
        refused(f"CA3 --date {bad!r}", tree(CHANGELOG, frag), ["--version", VERSION, "--date", bad, "--title", TITLE],
                "--date")
    refused("CA3 --title empty", tree(CHANGELOG, frag), ["--version", VERSION, "--date", DATE, "--title", " "],
            "--title")
    refused("CA3 --title in Cyrillic", tree(CHANGELOG, frag), ["--version", VERSION, "--date", DATE, "--title", ZHE],
            "--title", "U+0416")
    refused("CA3 a CHANGELOG with no title line", tree(SECTIONS, frag), ASSEMBLE, "no title")
    refused("CA3 a CHANGELOG whose first line is a section heading", tree("## 0.1.0\n- x\n", frag), ASSEMBLE, "no title")
    refused("CA3 a missing CHANGELOG", tree(None, frag), ASSEMBLE, "CHANGELOG.md")


@case
def test_ca3b_existing_version_and_files_that_would_ship_unseen():
    frag = {"forge-1-alpha.md": FRAG_A}
    top = f"## {VERSION} {DASH} 2026-10-01 {DASH} already released\n\n- z\n\n"
    dup = "# Changelog\n\nPointer line.\n\n" + top + SECTIONS
    refused("CA3 a version already in CHANGELOG.md", tree(dup, frag), ASSEMBLE, VERSION, "line 5", "already has")
    refused("CA3 the same, in the dry run too", tree(dup, frag), [*ASSEMBLE, "--dry-run"], VERSION, "line 5")
    refused("CA3 the same heading with nothing after the version", tree(dup.replace(top.split("\n")[0], "## " + VERSION),
                                                                         frag), ASSEMBLE, VERSION, "line 5")
    refused("CA3 the same, CRLF file", tree(dup.replace("\n", "\r\n").encode("utf-8"), frag), ASSEMBLE, VERSION,
            "line 5")
    deeper = "# Changelog\n\nPointer line.\n\n" + SECTIONS.replace("0.2.0", VERSION)
    refused("CA3 the existing version deeper in the file is found too", tree(deeper, frag), ASSEMBLE, VERSION,
            "line 9")
    near = tree("# Changelog\n\nPointer line.\n\n" + top.replace(VERSION, VERSION + "0") + SECTIONS, frag)
    check_eq("CA3 a longer version (0.9.10) does not block 0.9.1", run(near, *ASSEMBLE).returncode, 0)
    fenced = ("# Changelog\n\nPointer line.\n\n```\n## " + VERSION + " " + DASH + " an example\n```\n\n" + SECTIONS)
    root = tree(fenced, frag)
    r = run(root, *ASSEMBLE)
    check_eq("CA3 a `## 0.9.1` inside a code fence is text, not a heading: exit 0", r.returncode, 0)
    check_eq("CA3 and the section lands before the first REAL heading, not inside the fence",
             (root / "CHANGELOG.md").read_bytes().decode("utf-8"),
             fenced.replace("## 0.3.0", HEADING + "\n\n- Alpha change (`a.py`): why.\n  continuation\n\n## 0.3.0", 1))

    for name in ("forge-1-upper.MD", "forge-1-mixed.Md", "notes.txt", "forge-1-alpha.md.bak", ".gitkeep"):
        refused(f"CA3 {name} in changelog.d/", tree(CHANGELOG, {**frag, name: b"- x\n"}), ASSEMBLE, name,
                "not fragments")
        refused(f"CA3 {name} in changelog.d/ in the dry run", tree(CHANGELOG, {**frag, name: b"- x\n"}),
                [*ASSEMBLE, "--dry-run"], name)
    # README.MD is not README.md: only the exact name is the README (readme=False: a case-insensitive disk
    # would otherwise write both names to one file)
    refused("CA3 README.MD (upper-case extension) is refused like any other non-.md file",
            tree(CHANGELOG, {**frag, "README.MD": b"# x\n"}, readme=False), ASSEMBLE, "README.MD", "not fragments")
    refused("CA3 only a .txt and no fragment names the file, not 'no fragments'", tree(CHANGELOG, {"a.txt": b"x"}),
            ASSEMBLE, "a.txt")
    root = tree(CHANGELOG, {**frag, "forge-0-b.MD": b"- x\n", "z.txt": b"y"})
    r = run(root, "--list")
    check_eq("CA3 --list shows the refused files after the fragments, exit 0",
             (r.returncode, r.stdout), (0, b"forge-1-alpha.md\nREFUSED forge-0-b.MD\nREFUSED z.txt\n"))
    r = run(tree(CHANGELOG, {"z.txt": b"y"}), "--list")
    check_eq("CA3 --list with only a refused file says no fragments and names it",
             r.stdout, b"no fragments\nREFUSED z.txt\n")


@case
def test_ca4_line_endings_and_title_only_changelog():
    crlf = CHANGELOG.replace("\n", "\r\n")
    root = tree(crlf.encode("utf-8"), {"forge-2-beta.md": FRAG_B, "forge-1-alpha.md": FRAG_A})
    r = run(root, *ASSEMBLE)
    check_eq("CA4 CRLF: exit 0", r.returncode, 0)
    expected = ("# Changelog\n\nPointer line.\n\n" + SECTION + "\n" + SECTIONS).replace("\n", "\r\n")
    got = (root / "CHANGELOG.md").read_bytes()
    check_eq("CA4 CRLF input stays CRLF byte for byte (the section written with CRLF, the rest untouched)",
             got, expected.encode("utf-8"))
    check("CA4 CRLF: no bare LF anywhere in the file", got.replace(b"\r\n", b"").count(b"\n") == 0)
    check_eq("CA4 CRLF: stdout stays LF", r.stdout, SECTION.encode("utf-8"))
    root = tree("# Changelog\n\nOnly a title block.\n", {"forge-1-alpha.md": FRAG_A})
    r = run(root, *ASSEMBLE)
    check_eq("CA4 a CHANGELOG with no section yet: exit 0", r.returncode, 0)
    check_eq("CA4 the section is appended after the title block",
             (root / "CHANGELOG.md").read_bytes().decode("utf-8"),
             "# Changelog\n\nOnly a title block.\n\n" + HEADING + "\n\n- Alpha change (`a.py`): why.\n  continuation\n")
    root = tree(CHANGELOG, {"forge-1-dash.md": f"- the em dash {DASH} and an arrow → are fine\n".encode("utf-8")})
    r = run(root, *ASSEMBLE)
    check_eq("CA4 non-ASCII typography outside Cyrillic is allowed", r.returncode, 0)
    check_in("CA4 and it lands in the file as UTF-8", f"the em dash {DASH} and an arrow →",
             (root / "CHANGELOG.md").read_bytes().decode("utf-8"))


@case
def test_ca5_lang_rule_copy_and_shipped_files():
    import changelog_assemble as CA
    import selftest as S
    check_eq("CA5 the Cyrillic predicate equals selftest.CYRILLIC", CA.CYRILLIC.pattern, S.CYRILLIC.pattern)
    check_eq("CA5 the control-byte table equals selftest.CONTROL_BYTES", CA.CONTROL_BYTES, S.CONTROL_BYTES)


CASES = (test_ca1_assemble_places_orders_and_cleans, test_ca2_list_and_dry_run,
         test_ca3_refusals_are_loud_and_leave_everything, test_ca3b_existing_version_and_files_that_would_ship_unseen,
         test_ca4_line_endings_and_title_only_changelog,
         test_ca5_lang_rule_copy_and_shipped_files)

atexit.register(lambda: [cleanup(tmp) for tmp in ROOTS])      # also under pytest, where no main block runs

if __name__ == "__main__":
    for fn in CASES:
        try:
            fn()
        except AssertionError:
            pass
    finish("changelog_assemble")
