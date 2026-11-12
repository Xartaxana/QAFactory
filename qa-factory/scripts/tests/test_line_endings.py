"""The package pins its own line endings, and a red tree comparison says how the files differ (B-409).

LE-1..LE-3: the package's REAL `.gitattributes` in a throw-away repository. A Windows checkout with
`core.autocrlf=true` writes CRLF for every text file unless the package says otherwise; the tests compare package
files byte for byte (the reinstall-equals-fresh tree comparison, case-version hashes, size caps), so a CRLF fixture
made them red on a second developer's machine. `* text=auto eol=lf` fixes it, and the cmd/sh hook launcher
(`*.cmd`) stays checkout-native because cmd.exe needs CRLF.
LE-4..LE-8: `onboard_apply.describe_difference` / `difference_lines`, the description a red K5 prints.

Mutations this file kills (each by this file alone):
  `eol=lf` dropped from .gitattributes (LE-1) | the `*.cmd` exemption dropped (LE-3) | "only the line endings"
  said without normalizing (LE-5) | `_lines` using str.splitlines() (LE-8) | `_eol_kind` without CR (LE-4) |
  the cap off by one (LE-6)

Run: python -B scripts/tests/test_line_endings.py        (from ai-packages/qa-factory)
"""
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness import PLUGIN_ROOT, check, check_eq, check_in, cleanup, finish, temp_dir, temp_project, use_project  # noqa: E402

use_project(temp_project("qa-line-endings-audit-"))  # onboard_apply pulls config_contract, which reads the hook layer

import onboard_apply as OA  # noqa: E402

PACKAGE_DIR = "ai-packages/qa-factory"       # where the package sits in the throw-away repository (a subfolder, as in this repo)
GITATTRIBUTES = PLUGIN_ROOT / ".gitattributes"
LF_FILES = {
    "scripts/tests/fixtures/old-generation-project/.gitignore": b"node_modules/\n.env\n",
    "scripts/x.py": b"print(1)\nprint(2)\n",
    "references/x.json": b'{\n  "a": 1\n}\n',
    "references/x.md": b"# x\n\ntext\n",
    "hooks/run-py.cmd": b": << 'CMDBLOCK'\n@echo off\ngoto :end\nCMDBLOCK\n:end\n",
}
# characters that str.splitlines() breaks a line on and the parser's own line numbering does not (docs/SIBLING_MAP.md axis 7);
# built from code points so that this file stays ASCII
SPLITLINES_ONLY = ((chr(0x0C), "form feed"), (chr(0x2028), "line separator"), (chr(0x85), "next line"))


def git(cwd: Path, *args, config=()) -> subprocess.CompletedProcess:
    hooks = temp_dir("qa-line-endings-nohooks-")
    try:
        flags = ["-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "-c", f"core.hooksPath={hooks}"]
        for item in config:
            flags += ["-c", item]
        return subprocess.run(["git", "-C", str(cwd), *flags, *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    finally:
        cleanup(hooks)


def make_repo(tmp: Path, name: str, with_attributes: bool) -> Path:
    """A repository holding the package's LF files, committed with core.autocrlf=false (the index is LF, as in this repo)."""
    root = tmp / name
    root.mkdir()
    git(root, "init", "-q")
    package = root.joinpath(*PACKAGE_DIR.split("/"))
    for rel, data in LF_FILES.items():
        target = package.joinpath(*rel.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    if with_attributes:
        (package / ".gitattributes").write_bytes(GITATTRIBUTES.read_bytes())
    check_eq(f"{name}: git add and commit work (core.autocrlf=false)",
             [git(root, "add", "-A", config=("core.autocrlf=false",)).returncode,
              git(root, "commit", "-q", "-m", "package", config=("core.autocrlf=false",)).returncode], [0, 0])
    return root


def clone_with_autocrlf(tmp: Path, source: Path, name: str) -> Path:
    """What a Windows developer's fresh clone does: core.autocrlf=true, set for the clone's own checkout."""
    done = git(tmp, "clone", "-q", "-c", "core.autocrlf=true", str(source), name)
    check_eq(f"{name}: git clone with core.autocrlf=true works", done.returncode, 0)
    return tmp / name


def is_crlf(path: Path) -> bool:
    return b"\r\n" in path.read_bytes()


def clone_keys(tmp: Path) -> None:
    check("precondition: the package's .gitattributes exists", GITATTRIBUTES.is_file(), str(GITATTRIBUTES))
    source = make_repo(tmp, "src-with", True)
    package = clone_with_autocrlf(tmp, source, "clone-with").joinpath(*PACKAGE_DIR.split("/"))
    paths = {rel: package.joinpath(*rel.split("/")) for rel in LF_FILES}
    wrong = [rel for rel, p in paths.items() if not rel.endswith(".cmd") and is_crlf(p)]
    check_eq("LE-1: in a clone with core.autocrlf=true the fixture .gitignore, the .py, .json and .md files contain no CRLF (eol=lf wins)", wrong, [])
    check("LE-1 precondition: those files are really there and have their LF lines",
          all(paths[r].read_bytes() == LF_FILES[r] for r in LF_FILES if not r.endswith(".cmd")), "bytes differ from what was committed")
    # LE-2: the negative control - the same repository with no .gitattributes is what a second developer's machine got
    bare = make_repo(tmp, "src-without", False)
    bare_package = clone_with_autocrlf(tmp, bare, "clone-without").joinpath(*PACKAGE_DIR.split("/"))
    check("LE-2: NEGATIVE CONTROL - without .gitattributes the same clone writes the fixture .gitignore as CRLF",
          is_crlf(bare_package.joinpath(*"scripts/tests/fixtures/old-generation-project/.gitignore".split("/"))), "no CRLF: the control proves nothing")
    # LE-3: the launcher keeps the checkout's own line endings (CRLF for cmd.exe on a Windows checkout)
    check("LE-3: in the LE-1 clone hooks/run-py.cmd is CRLF (the polyglot launcher is exempt: cmd.exe needs CRLF)", is_crlf(paths["hooks/run-py.cmd"]), "LF")
    attrs = git(source, "check-attr", "text", "eol", "--", f"{PACKAGE_DIR}/hooks/run-py.cmd", f"{PACKAGE_DIR}/scripts/x.py")
    check_in("LE-3: check-attr says the .py is text=auto eol=lf and the launcher is unspecified for both",
             "scripts/x.py: eol: lf", attrs.stdout)
    check_in("LE-3: ...the launcher", "hooks/run-py.cmd: eol: unspecified", attrs.stdout)


def describe(tmp: Path, data_a, data_b, ignore=frozenset(), name: str = "f") -> str:
    pa, pb = tmp / "da" / name, tmp / "db" / name
    for path, data in ((pa, data_a), (pb, data_b)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return OA.describe_difference(name, pa, pb, ignore)


def description_keys(tmp: Path) -> None:
    # the two private helpers the keys stand on
    check_eq("_eol_kind: LF, CRLF, CR, mixed (two kinds), none (empty, or no break at all)",
             [OA._eol_kind(b) for b in (b"a\nb\n", b"a\r\nb\r\n", b"a\rb\r", b"a\r\nb\n", b"a\rb\n", b"a\rb\r\nc\n", b"", b"abc")],
             ["LF", "CRLF", "CR", "mixed", "mixed", "mixed", "none", "none"])
    check_eq("_lines: split on CRLF, CR and LF only; one trailing empty element dropped; empty text has no lines",
             [OA._lines(t) for t in ("a\r\nb\rc\n", "a\n\n", "", "\n", "x")], [["a", "b", "c"], ["a", ""], [], [""], ["x"]])
    # LE-4
    check_eq("LE-4: a CRLF-only difference says so, with the kind of each side",
             describe(tmp, b"a\nb\n", b"a\r\nb\r\n"), "f: same text, only the line endings differ (A: LF, B: CRLF)")
    check_eq("LE-4: a CR-only side is named CR", describe(tmp, b"a\rb\r", b"a\nb\n"), "f: same text, only the line endings differ (A: CR, B: LF)")
    # LE-5
    check_eq("LE-5: a real text difference at line 3 names line 3 and quotes both lines (and both sides' line endings)",
             describe(tmp, b"one\ntwo\nthree\n", b"one\ntwo\nthrEE\n"),
             "f: first difference at line 3: A 'three' | B 'thrEE' (line endings A: LF, B: LF)")
    both = describe(tmp, b"one\ntwo\nthree\n", b"one\r\ntwo\r\nthrEE\r\n")
    check("LE-5: a pair that differs in line endings AND in text never says 'only the line endings' - it names line 3 and both kinds",
          "only the line endings" not in both and "line 3" in both and "A: LF" in both and "B: CRLF" in both, both)
    # LE-6: the two limits, AT and BEYOND
    at, beyond = "x" * 80, "x" * 81
    line_at = describe(tmp, "p\n" + at + "\n", "p\n" + "y" * 80 + "\n")
    line_beyond = describe(tmp, "p\n" + beyond + "\n", "p\n" + "y" * 81 + "\n")
    check("LE-6: a line of 80 characters is shown whole, without '...'", repr(at) in line_at and "..." not in line_at, line_at)
    check("LE-6: a line of 81 characters is cut to its first 80 followed by '...'",
          repr("x" * 80 + "...") in line_beyond and "x" * 81 not in line_beyond, line_beyond)
    for count, tail in ((OA.DIFFERENCE_CAP, False), (OA.DIFFERENCE_CAP + 1, True)):
        names = [f"n{i:02d}.txt" for i in range(count)]
        for n in names:
            describe(tmp / f"cap{count}", "1\n", "2\n", name=n)
        got = OA.difference_lines(tmp / f"cap{count}" / "da", tmp / f"cap{count}" / "db", {"differing": names})
        check_eq(f"LE-6: {count} differing files: {OA.DIFFERENCE_CAP} described" + (" plus '+1 more differing file(s) not described'" if tail else ", no tail line (AT the limit)"),
                 (len(got), got[-1] if tail else None, all("first difference at line 1" in l for l in got[:OA.DIFFERENCE_CAP])),
                 (OA.DIFFERENCE_CAP + (1 if tail else 0), "+1 more differing file(s) not described" if tail else None, True))
    check_eq("LE-6: a cap of 2 over 3 files: 2 lines and '+1 more'", len(OA.difference_lines(tmp / "cap11" / "da", tmp / "cap11" / "db",
             {"differing": ["n00.txt", "n01.txt", "n02.txt"]}, cap=2)), 3)
    # LE-7: an excused JSON field is not what the line points at
    first, second = b'{\n  "input_hash": "1",\n  "k": 1,\n  "z": 2\n}\n', b'{\n  "input_hash": "2",\n  "k": 1,\n  "z": 3\n}\n'
    got = describe(tmp, first, second, frozenset({"input_hash"}))
    check_eq("LE-7: an excused field plus a real difference - the prefix names the excused field and the line is the real key's, in the canonical dump",
             got, "f (compared without the fields input_hash): first difference at line 3: A '  \"z\": 2' | B '  \"z\": 3' (line endings A: LF, B: LF)")
    same_dumps = describe(tmp, b'{\n  "input_hash": "1",\n  "k": 1\n}\n', b'{\n  "input_hash": "2",\n  "k": 1\n}\n', frozenset({"input_hash"}))
    check("LE-7: equal canonical dumps fall back to the raw (e) form, with no prefix, naming the raw line",
          "compared without" not in same_dumps and "first difference at line 2" in same_dumps and "input_hash" in same_dumps, same_dumps)
    broken = describe(tmp, b"{ not json\nx\n", b"{ not json\ny\n", frozenset({"input_hash"}))
    check("LE-7: unparseable JSON under `ignore` gives raw lines, no prefix", "compared without" not in broken and "first difference at line 2" in broken, broken)
    one_side = describe(tmp, b'{"input_hash": 1}\n', b"{ not json\n", frozenset({"input_hash"}))
    check("LE-7: JSON on one side only gives raw lines too", "compared without" not in one_side and "first difference at line 1" in one_side, one_side)
    # LE-7 through `difference_lines`: the per-path ignore sets it was given reach describe_difference (critic t-520 F1)
    describe(tmp / "ign", first, second)
    da, db = tmp / "ign" / "da", tmp / "ign" / "db"
    check_eq("LE-7: difference_lines hands the per-path ignore set to describe_difference: the prefix, and the line is the real key's, not input_hash",
             OA.difference_lines(da, db, {"differing": ["f"]}, ignore_json_fields={"f": ["input_hash"]}),
             ["f (compared without the fields input_hash): first difference at line 3: A '  \"z\": 2' | B '  \"z\": 3' (line endings A: LF, B: LF)"])
    other = OA.difference_lines(da, db, {"differing": ["f"]}, ignore_json_fields={"g": ["input_hash"]})
    check("LE-7: ...and an ignore set of ANOTHER path does not apply to this one (raw lines, pointing at input_hash)",
          len(other) == 1 and "compared without" not in other[0] and "first difference at line 2" in other[0] and "input_hash" in other[0], str(other))
    # LE-8: empty, odd, adversarial
    check_eq("LE-8: empty against non-empty: A has no line 1", describe(tmp, b"", b"x\n"),
             "f: first difference at line 1: A no line 1 | B 'x' (line endings A: none, B: LF)")
    bom = describe(tmp, b"\xef\xbb\xbfx\n", b"x\n")
    check("LE-8: a BOM-only difference says the lines are the same, the bytes differ, and which side has the BOM",
          "same lines, the bytes differ elsewhere" in bom and "byte-order mark A: yes, B: no" in bom and "final line break A: yes, B: yes" in bom, bom)
    final = describe(tmp, b"x\n", b"x")
    check("LE-8: a final-line-break-only difference says so",
          "same lines, the bytes differ elsewhere" in final and "final line break A: yes, B: no" in final and "byte-order mark A: no, B: no" in final, final)
    gone = OA.describe_difference("f", tmp / "da" / "f", tmp / "da" / "no-such-file")
    check("LE-8: an unreadable side B names the side and the exception class", gone.startswith("f: cannot be read on side B (") and gone.endswith(")"), gone)
    gone_a = OA.describe_difference("f", tmp / "da" / "no-such-file", tmp / "da" / "f")
    check("LE-8: an unreadable side A names side A", gone_a.startswith("f: cannot be read on side A ("), gone_a)
    check("LE-8: a folder where a file should be is an unreadable side, not a raised error",
          OA.describe_difference("f", tmp / "da", tmp / "da" / "f").startswith("f: cannot be read on side A ("), "raised or other text")
    for char, name in SPLITLINES_ONLY:
        text_a, text_b = f"a{char}b\nX\n", f"a{char}b\nY\n"
        got = describe(tmp, text_a, text_b)
        check(f"LE-8: a {name} inside line 1 of both files does not split it: the real difference is named at line 2 (splitlines() says line 3)",
              "first difference at line 2:" in got, got)
    check_eq("LE-8: not UTF-8 text gives the sizes and the line endings", describe(tmp, b"\xff\xfe\x00a", b"\xff\xfe\x00"),
             "f: not UTF-8 text (A 4 bytes, B 3 bytes; line endings A: none, B: none)")
    nul = describe(tmp, b"a\x00b\n", b"a\x00c\n")
    check_eq("LE-8: a NUL byte inside valid UTF-8 text is quoted, not raised", nul, "f: first difference at line 1: A 'a\\x00b' | B 'a\\x00c' (line endings A: LF, B: LF)")
    huge = describe(tmp, "x" * 10_000_000, "y" * 10_000_000)
    check("LE-8: a 10 MB single line is cut at 80 characters", len(huge) < 300 and huge.count("x") <= 80 + 20, f"{len(huge)} characters")
    check_eq("LE-8: byte-identical files (rewritten since the comparison) are said to be the same now, never 'only the line endings differ'",
             describe(tmp, b"same\r\ntext\r\n", b"same\r\ntext\r\n"), "f: the bytes are the same now (changed since the comparison?)")
    real_loads = OA.json.loads

    def broken_loads(*args, **kwargs):
        raise KeyError("a failure nobody planned for")
    OA.json.loads = broken_loads
    try:
        unplanned = describe(tmp, b'{"input_hash": 1, "a": 1}\n', b'{"input_hash": 2, "a": 2}\n', frozenset({"input_hash"}))
    finally:
        OA.json.loads = real_loads
    check_eq("LE-8: an exception the function did not plan for is a line of its own that names no side (both reads had succeeded)",
             unplanned, "f: cannot be described (KeyError)")
    check_eq("LE-8: difference_lines on an empty, absent or missing `differing` is []",
             [OA.difference_lines(tmp, tmp, r) for r in ({"differing": []}, {"differing": None}, {}, None)], [[], [], [], []])
    check_eq("LE-8: difference_lines writes nothing and never raises on a path that is not there",
             [l.startswith("gone.txt: cannot be read on side A (") for l in OA.difference_lines(tmp / "x1", tmp / "x2", {"differing": ["gone.txt"]})], [True])


def main() -> None:
    tmp = temp_dir("qa-line-endings-")
    try:
        if shutil.which("git"):
            clone_keys(tmp)
        else:
            print("SKIPPED: git not found (the clone keys LE-1..LE-3 were not run)")
        description_keys(tmp)
    finally:
        cleanup(tmp)
    finish("test_line_endings")


if __name__ == "__main__":
    main()
