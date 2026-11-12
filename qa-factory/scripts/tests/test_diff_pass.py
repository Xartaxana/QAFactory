"""diff_pass.parse/render: one deterministic pass over a unified diff — which files
changed, and the changed lines numbered in the NEW file (the raw material for
observables[], per the module's docstring). Covers the two-file parse, added/removed
counts, hunk numbering, the files-only view, and the "N more changed lines" cap.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import diff_pass as D  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, check_in, finish  # noqa: E402

SAMPLE = (
    "diff --git a/src/checkout.py b/src/checkout.py\n"
    "index 111..222 100644\n"
    "--- a/src/checkout.py\n"
    "+++ b/src/checkout.py\n"
    "@@ -10,4 +10,5 @@ def cancel(order):\n"
    " def cancel(order):\n"
    "-    charge(order)\n"
    "+    charge(order)\n"
    "+    refund_shipping(order)\n"
    "     return True\n"
    "diff --git a/ui/Page.tsx b/ui/Page.tsx\n"
    "--- a/ui/Page.tsx\n"
    "+++ b/ui/Page.tsx\n"
    "@@ -3,2 +3,2 @@\n"
    "-const x = 1\n"
    "+const x = 2\n"
)

files = D.parse(SAMPLE)
check_eq("parse finds both changed files, in order", [f["path"] for f in files], ["src/checkout.py", "ui/Page.tsx"])
check_eq("added-line count is per file", files[0]["added"], 2)
check_eq("removed-line count is per file", files[0]["removed"], 1)
hunk = files[0]["hunks"][0]
check_eq("the hunk starts where the @@ header says (NEW file numbering)", hunk["new_start"], 10)
check_eq("the hunk keeps its trailing context header", hunk["header"], "def cancel(order):")
added = [(n, t.strip()) for n, s, t in hunk["lines"] if s == "+"]
check_eq("an added line is numbered in the NEW file, not the old", added[-1], (12, "refund_shipping(order)"))
removed = [(n, t.strip()) for n, s, t in hunk["lines"] if s == "-"]
check_eq("a removed line is marked at its position in the surrounding NEW-file numbering",
         removed[0], (11, "charge(order)"))

text = "\n".join(D.render(files, D.DEFAULT_MAX_LINES, False))
check("render prints a citable path:line", "src/checkout.py:10" in text)
check("render shows the changed line", "refund_shipping(order)" in text)
check("render leaves out unchanged context lines", "return True" not in text)

files_only = "\n".join(D.render(files, D.DEFAULT_MAX_LINES, True))
check("--files-only prints the per-file summary", "src/checkout.py" in files_only)
check("--files-only prints no line content", "refund_shipping" not in files_only)

capped = "\n".join(D.render(files, 1, False))
check("a capped hunk says how many more lines it left out", "more changed line(s)" in capped)
uncapped = "\n".join(D.render(files, D.DEFAULT_MAX_LINES, False))
check("an uncapped render carries no such note", "more changed line(s)" not in uncapped)

check_eq("an empty diff parses to no files", D.parse(""), [])

# a `+++ /dev/null` (deleted file) hunk is not adopted as the new path
DELETED = (
    "diff --git a/old.py b/old.py\n"
    "--- a/old.py\n"
    "+++ /dev/null\n"
    "@@ -1,1 +0,0 @@\n"
    "-print(1)\n"
)
deleted_files = D.parse(DELETED)
check_eq("a deleted file keeps its diff --git path when +++ is /dev/null", deleted_files[0]["path"], "old.py")
check_eq("the deletion is counted", deleted_files[0]["removed"], 1)

# ---------------------------------------------------------------------------------------------------------------------
# G1-1: the one reader of a recorded diff. The battery B1..B23 of the spec, then the index (E8, E10, E11), the I1 sum, the
# K10 `body` key and the golden pin of `--json`. Each mutation of the reader is killed by a line below (see the report).
import hashlib  # noqa: E402
import json  # noqa: E402
from harness import cleanup, run_script, temp_dir  # noqa: E402


def one(text: str) -> dict:
    """The only section of a diff text, as `parse` sees it."""
    got = D.parse(text)
    return got[0] if got else {}


def hdr(path: str, body: str, old: str = "") -> str:
    return f"diff --git a/{path} b/{path}\n--- a/{old or path}\n+++ b/{path}\n{body}"


def work_of(files: dict) -> Path:
    """A throwaway `work/` folder holding the given diffs (name -> bytes or str); the caller cleans up."""
    folder = temp_dir("qa-dp-")
    for name, content in files.items():
        (folder / name).write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    return folder


def indexed(files: dict) -> dict:
    folder = work_of(files)
    try:
        return D.index(folder)
    finally:
        cleanup(folder)


# B1 / B2: a header is recognised only OUTSIDE a counted range (the class: `-- x` and `++ x` are lines, not files)
sql = one(hdr("q.sql", "@@ -1,2 +1 @@\n--- drop table t\n-x\n+z\n"))
check_eq("B1: a deleted SQL comment `-- drop table` stays a removed line; the path and old_path are the file's own",
         (sql["path"], sql["old_path"], sql["removed"], sql["added"]), ("q.sql", "a/q.sql", 2, 1))
plus = one(hdr("p.py", "@@ -1 +1,2 @@\n a\n++ x\n"))
check_eq("B2: an added `++ x` is an added line; the path is not reassigned", (plus["path"], plus["added"], plus["hunks"][0]["lines"]),
         ("p.py", 1, [(2, "+", "+ x")]))
# B3: FR-16, the path is the one the header writes (exactly the prefix goes; git's TAB after a blank path goes)
blank = one("diff --git a/x b/y.py b/x b/y.py\n--- a/x b/y.py\t\n+++ b/x b/y.py\t\n@@ -1 +1 @@\n-a\n+b\n")
check_eq("B3: a path holding ` b/` and git's trailing TAB is read whole", (blank["path"], blank["old_path"]), ("x b/y.py", "a/x b/y.py"))
check_eq("B3: `+++ b/build/x.py` keeps its `b` and `u` (lstrip('b/') cut characters)", one(hdr("build/x.py", "@@ -1 +1 @@\n-a\n+b\n"))["path"],
         "build/x.py")
check_eq("B3: a binary new file with a blank in its path is named by the symmetric half of the `diff --git` line",
         one("diff --git a/my pic.png b/my pic.png\nnew file mode 100644\nBinary files /dev/null and b/my pic.png differ\n")["path"],
         "my pic.png")
# B4: a combined diff is refused, nothing around it is touched
MERGE = (hdr("a.py", "@@ -1 +1 @@\n-a\n+b\n") + "diff --cc f.py\nindex 1,2..3\n--- a/f.py\n+++ b/f.py\n@@@ -1,2 -1,2 +1,3 @@@\n+x\n -y\n"
         + hdr("z.py", "@@ -1 +1 @@\n-c\n+d\n"))
entries = D.scan(MERGE, "impl-diff.txt")
check_eq("B4: the combined section is listed under its name, refused, with no hunks; its neighbours are intact",
         [(e.path, bool(e.refused), len(e.hunks), e.added, e.removed) for e in entries],
         [("a.py", False, 1, 1, 1), ("f.py", True, 0, 0, 0), ("z.py", False, 1, 1, 1)])
for needle in ("impl-diff.txt line", "opens a combined diff", "Expected:", "Do: write the merge's diff", "git diff <merge>^1 <merge>",
               "informed pass, FR-4"):
    check_in(f"B4: the refusal says '{needle}'", needle, entries[1].refused)
check_eq("B4: a bare `@@@` after a file header refuses that file too",
         [bool(e.refused) for e in D.scan("diff --git a/g b/g\n@@@ -1 -1 +1 @@@\n+x\n")], [True])
# F5 (t-1050): `diff --cc <path>` names the file, so the record is refused but not unlabelled; a name nobody wrote stays uncertain
named = D.scan('diff --cc f.py\n@@@ -1 -1 +1 @@@\n+x\ndiff --combined "t\\303\\251st.py"\n@@@ -1 -1 +1 @@@\n+x\n@@@ -1 -1 +1 @@@\n')
check_eq("F5: a `diff --cc` / `diff --combined` section (quoted too) is listed under the name git wrote, refused, path_uncertain False",
         [(e.path, e.path_uncertain, bool(e.refused)) for e in named], [("f.py", False, True), ("tést.py", False, True)])
check_eq("F5: ... the index record says the same, and its refusal is the `combined` kind",
         [(f["path"], f["path_uncertain"], f["refused"] != "") for f in indexed({"impl-diff.txt": MERGE})["files"] if f["path"] == "f.py"],
         [("f.py", False, True)])
check_eq("F5: a bare `@@@` with no section name is still listed uncertain (nothing was named)",
         [(e.path_uncertain, bool(e.refused)) for e in D.scan("@@@ -1 -1 +1 @@@\n+x\n")], [(True, True)])
folder = work_of({"impl-diff.txt": MERGE})
try:
    ran =run_script("diff_pass.py", "--diff", folder / "impl-diff.txt", "--files-only")
    check_eq("B4: the command line prints every file, tells the refusal on stderr and exits 3",
             (ran.returncode, "z.py" in ran.stdout, "opens a combined diff" in ran.stderr), (3, True, True))
finally:
    cleanup(folder)
# B5: `\ No newline at end of file` is not a line
nonl = one(hdr("n.py", "@@ -1 +1 @@\n-a\n\\ No newline at end of file\n+b\n\\ No newline at end of file\n"))
check_eq("B5: the marker is no line and moves no number", (nonl["added"], nonl["removed"], nonl["hunks"][0]["lines"]),
         (1, 1, [(1, "-", "a"), (1, "+", "b")]))
# F1 (t-1050; t-1034 B-1; t-1014 §L line 293): the marker is part of `body`, verbatim, on the side git printed it - a newline-only
# edit must change what G1-4 hashes. It is still no line: the lines, the counts and the numbers are the ones of B5.
MARK = "\\ No newline at end of file"
NL_OLD, NL_NEW, NL_NONE = ("@@ -1 +1 @@\n-a\n" + MARK + "\n+a\n", "@@ -1 +1 @@\n-a\n+a\n" + MARK + "\n", "@@ -1 +1 @@\n-a\n+a\n")
nl_hunks = [D.scan(hdr("n.py", variant))[0].hunks[0] for variant in (NL_OLD, NL_NEW, NL_NONE)]
check_eq("F1: the marker sits in the body where git printed it - old side (inside the range), new side (after it), none",
         [h["body"] for h in nl_hunks], [["-a", MARK, "+a"], ["-a", "+a", MARK], ["-a", "+a"]])
check_eq("F1: the three newline variants give three different bodies (a newline-only edit changes the hash input)",
         len({tuple(h["body"]) for h in nl_hunks}), 3)
check_eq("F1: ... and the same lines, counts and numbers (the marker is no line)",
         [(h["lines"], h["truncated"], h["overflow"]) for h in nl_hunks], [([(1, "-", "a"), (1, "+", "a")], False, False)] * 3)
nl_after = D.scan(hdr("n.py", NL_NEW) + "diff --git a/m.py b/m.py\n" + MARK + "\n")
check_eq("F1: a marker with no hunk to hold it (a section's first line) is dropped and touches no other hunk",
         [(e.path, [h["body"] for h in e.hunks]) for e in nl_after], [("n.py", [["-a", "+a", MARK]]), ("m.py", [])])
# B6: CRLF
check_eq("B6: a CRLF diff reads as its LF twin", D.parse(SAMPLE.replace("\n", "\r\n")), D.parse(SAMPLE))
# B7: U+2028 / U+0085 are text, not line breaks (git counts LF only); FR-29: built with chr()
odd = one(hdr("u.py", f"@@ -1 +1,2 @@\n+a{chr(0x2028)}b\n+c{chr(0x85)}d\n"))
check_eq("B7: U+2028 and U+0085 inside an added line stay inside it; the numbering is git's",
         [(n, t) for n, _s, t in odd["hunks"][0]["lines"]], [(1, f"a{chr(0x2028)}b"), (2, f"c{chr(0x85)}d")])
# B8: a lone CR (through the file read, not only the splitter)
lone = indexed({"impl-diff.txt": b"diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -0,0 +1,2 @@\n+x\r\n+y\rz\n"})["files"][0]
check_eq("B8: a lone `\\r` inside a line is not a line break: two lines, numbered as git numbers them, none truncated",
         ([(n, t) for n, _s, t in lone["hunks"][0]["lines"]], lone["hunks"][0]["truncated"], lone["hunks"][0]["overflow"]),
         ([(1, "x"), (2, "y\rz")], False, False))
# B9: counts
zero = D.parse(hdr("c.py", "@@ -0,0 +1 @@\n+x\n") + hdr("d.py", "@@ -1 +1 @@\n-a\n+b\n"))
check_eq("B9: `@@ -0,0 +1 @@` holds one added line and the next `---` is a header; `@@ -1 +1 @@` is 1 and 1",
         [(f["path"], f["added"], f["removed"]) for f in zero], [("c.py", 1, 0), ("d.py", 1, 1)])
# B10 / B11: a section with no hunk gets a pseudo-hunk in the index and none in parse
SECTIONS = {
    "bin.png": "diff --git a/bin.png b/bin.png\nindex 1..2 100644\nBinary files a/bin.png and b/bin.png differ\n",
    "patch.bin": "diff --git a/patch.bin b/patch.bin\nnew file mode 100644\nindex 0..1\nGIT binary patch\nliteral 5\nHcmZ?wbhEHb\n\n",
    "new_name.py": "diff --git a/old_name.py b/new_name.py\nsimilarity index 100%\nrename from old_name.py\nrename to new_name.py\n",
    "copy.py": "diff --git a/src.py b/copy.py\nsimilarity index 100%\ncopy from src.py\ncopy to copy.py\n",
    "run.sh": "diff --git a/run.sh b/run.sh\nold mode 100644\nnew mode 100755\n",
    "empty.py": "diff --git a/empty.py b/empty.py\nnew file mode 100644\nindex 0000000..e69de29\n",
    "gone.py": "diff --git a/gone.py b/gone.py\ndeleted file mode 100644\nindex e69de29..0000000\n",
    "odd.py": "diff --git a/odd.py b/odd.py\nindex 1..2 100644\n",
}
found = indexed({"impl-diff.txt": "".join(SECTIONS.values())})["files"]
check_eq("B10/B11: binary, rename (new path, old_path the old one), copy, mode, new_empty, deleted_empty, unknown: one pseudo-hunk each",
         [(f["path"], f["old_path"], f["hunks"][0]["pseudo"]) for f in found],
         [("bin.png", "", "binary"), ("patch.bin", "", "binary"), ("new_name.py", "old_name.py", "rename"), ("copy.py", "", "copy"),
          ("run.sh", "", "mode"), ("empty.py", "", "new_empty"), ("gone.py", "", "deleted_empty"), ("odd.py", "", "unknown")])
check_eq("B10: `parse` keeps the old shape: no hunk, no pseudo-hunk", [f["hunks"] for f in D.parse("".join(SECTIONS.values()))],
         [[]] * len(SECTIONS))
check_eq("K10: a pseudo-hunk's body is the file's git header lines, never empty", [bool(f["hunks"][0]["body"]) for f in found],
         [True] * len(found))
check_eq("K10: ... in order, as the diff wrote them", found[2]["hunks"][0]["body"], SECTIONS["new_name.py"].splitlines())
check_eq("F-5: a `+` line with no hunk to hold it makes the section `unknown` for the role to label (an extra row, no lost line)",
         indexed({"impl-diff.txt": "diff --git a/s.py b/s.py\n+stray\n"})["files"][0]["hunks"][0]["pseudo"], "unknown")
# B12 / E8: every impl-diff*.txt, a record per repository
two = indexed({"impl-diff-testproject1-backend.txt": hdr("api.py", "@@ -1 +1 @@\n-a\n+b\n"),
               "impl-diff-testproject1-ui.txt": hdr("api.py", "@@ -1 +1 @@\n-c\n+d\n") + hdr("ui.ts", "@@ -1 +1 @@\n-e\n+f\n"),
               "impl-diff.txt": hdr("root.py", "@@ -1 +1 @@\n-g\n+h\n")})
check_eq("B12: all three diffs are read, in order, each record names its diff and repo; one path in two repos is two records",
         [(f["diff"], f["repo"], f["path"]) for f in two["files"]],
         [("impl-diff-testproject1-backend.txt", "testproject1-backend", "api.py"), ("impl-diff-testproject1-ui.txt", "testproject1-ui", "api.py"),
          ("impl-diff-testproject1-ui.txt", "testproject1-ui", "ui.ts"), ("impl-diff.txt", "", "root.py")])
# B13 / E10: no ceiling
BIG = "".join(hdr(f"m{i // 500}.py", "".join(f"@@ -{j},1 +{j},1 @@ def f{j}():\n-{'a' * 60}\n+{'b' * 60}\n" for j in range(i, i + 500)))
              for i in range(0, 3500, 500))
big = indexed({"impl-diff.txt": BIG})
check_eq("B13: a diff over 400 KB and 3000 hunks keeps every hunk (no truncation at the brief's 360 KB)",
         (len(BIG) > 400_000, sum(len(f["hunks"]) for f in big["files"]), BIG.count("\n@@ ")), (True, 3500, 3500))
# B14: nothing
check_eq("B14: an empty text, no diffs and only empty diffs are no files", (D.parse(""), D.parse("\n\n"), indexed({})["files"],
         indexed({"impl-diff.txt": ""})["files"], indexed({"impl-diff.txt": "\n \n"})["files"]), ([], [], [], [], []))
# B15 / B16 / B22: a count that does not match the body
cut = D.scan("diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1,5 +1,5 @@\n x\n-y\n+z\ndiff --git a/b b/b\n--- a/b\n+++ b/b\n@@ -1 +1 @@\n-p\n+q\n")
check_eq("B15: a count of 5 over three lines: the hunk is `truncated`, the next file is whole",
         [(e.path, e.hunks[0]["truncated"], e.added, e.removed) for e in cut], [("a", True, 1, 1), ("b", False, 1, 1)])
over = D.scan("diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1 +1 @@\n-p\n+q\n+extra\n")[0]
check_eq("B16: a line past the count is kept, with `overflow`", (over.added, over.hunks[0]["overflow"], over.hunks[0]["lines"][-1]),
         (2, True, (2, "+", "extra")))
swallow = D.scan("diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1,3 +1,3 @@\n-p\n+q\n--- a/b\n+++ b/b\n@@ -1 +1 @@\n-r\n+s\n")
check_eq("B22: a count larger than the body does not swallow the next file's header (the triple `---` `+++` `@@ -` is one)",
         [(e.path, e.added, e.removed, e.hunks[0]["truncated"]) for e in swallow], [("a", 1, 1, True), ("b", 1, 1, False)])
# F3 (t-1050): the triple is a header inside a range only when the content reading would leave the range open at the `@@ -`
# line. A hunk that ENDS with a removed `-- drop` and an added `++ add` (their lines read `--- drop` / `+++ add`) is legal.
legal = D.scan(hdr("q.sql", "@@ -1,2 +1,2 @@\n x\n--- drop\n+++ add\n@@ -10 +10 @@\n-y\n+z\n"))
check_eq("F3: a legal hunk ending `--- drop` / `+++ add` keeps both lines; the next hunk is the same file's (no phantom file `add`)",
         [(e.path, len(e.hunks), e.added, e.removed, [h["truncated"] for h in e.hunks]) for e in legal],
         [("q.sql", 2, 2, 2, [False, False])])
check_eq("F3: ... the two lines are numbered and kept as written", legal[0].hunks[0]["lines"], [(2, "-", "-- drop"), (2, "+", "++ add")])
for old_count, new_count in ((2, 3), (3, 2)):      # BEYOND the boundary: one side still open -> a header (the count was too large)
    short = D.scan(hdr("a", f"@@ -1,{old_count} +1,{new_count} @@\n x\n") + "--- a/b\n+++ b/b\n@@ -1 +1 @@\n-r\n+s\n")
    check_eq(f"F3: with {old_count} old and {new_count} new lines counted over one line, the triple is the next file's header",
             [(e.path, e.hunks[0]["truncated"], e.added, e.removed) for e in short], [("a", True, 0, 0), ("b", False, 1, 1)])
# B17: glued headerless diffs and a fragment
glued = D.parse("--- /dev/null\n+++ b/A\n@@ -0,0 +1 @@\n+a\n--- /dev/null\n+++ b/B\n@@ -0,0 +1 @@\n+b\n")
check_eq("B17: two glued headerless diffs are two files (the second `---` after a hunk opens a section)", [f["path"] for f in glued], ["A", "B"])
check_eq("B17: a fragment `+++ b/A` / `+++ b/B` is two sections, not one reassigned path", [f["path"] for f in D.parse("+++ b/A\n+++ b/B\n")],
         ["A", "B"])
check_eq("B17: the leading `---` of a headerless diff is not lost", one("--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n")["old_path"], "a/x.py")
# B18: git's quoting
quoted = D.scan('diff --git "a/t\\303\\251st.py" "b/t\\303\\251st.py"\nnew file mode 100644\nBinary files /dev/null and "b/t\\303\\251st.py" differ\n'
                'diff --git a/q.py b/q.py\n--- a/q.py\n+++ "b/t\\303\\251\\"x.py"\n@@ -1 +1 @@\n-a\n+b\n'
                'diff --git a/r.py b/r.py\n--- a/r.py\n+++ "b/bro\\zen.py"\n@@ -1 +1 @@\n-a\n+b\n')
check_eq("B18: a quoted `diff --git` with no `+++` and a quoted `+++` are decoded; a broken quote is kept raw and labelled",
         [(e.path, e.path_uncertain, bool(e.refused)) for e in quoted],
         [("tést.py", False, False), ('té"x.py', False, False), ('"b/bro\\zen.py"', True, True)])
check_in("B18: the path-unknown refusal says what, what was expected and the door", "re-export the diff", quoted[2].refused)
# B19 is the old pin above. B20: an empty line INSIDE a range is context
check_eq("B20: `\"\"` inside a counted range is a context line (the numbering moves)",
         [(n, t) for n, _s, t in one(hdr("e.py", "@@ -1,2 +1,3 @@\n\n+x\n y\n"))["hunks"][0]["lines"]], [(2, "x")])
# B21: BOM
check_eq("B21: a leading BOM does not hide the first file", [f["path"] for f in D.parse("\ufeff" + SAMPLE)], ["src/checkout.py", "ui/Page.tsx"])
check_eq("B21 (t-1050 F4): ... and when the BOM sits before the only line that names the file (no `+++`: a binary file)",
         [f["path"] for f in D.parse("\ufeff" + SECTIONS["bin.png"])], ["bin.png"])
# F-5: an empty line OUTSIDE a range is nothing
gap = D.scan(hdr("g.py", "@@ -1 +1 @@\n-a\n+b\n\n\n") + hdr("h.py", "@@ -1 +1 @@\n-c\n+d\n\n"))
check_eq("F-5: blank lines between files (two after each, as the export writes them) are no hunk lines and no overflow",
         [(e.path, e.added, e.removed, e.hunks[0]["overflow"]) for e in gap], [("g.py", 1, 1, False), ("h.py", 1, 1, False)])
# I1: the sum of lines. The measurer's own count is taken from the raw text (a hunk line is one that starts with a space, `+`, `-`
# or the no-newline marker `\`, after an `@@ ` line and before the next `diff --git`) and is compared with the index: on the real
# diff when this tree has it (a package-only tree does not), and always on the synthetic twin below (Q8, FR-28).
def i1_counts(text: str) -> tuple:
    """(hunk lines, `+`/`-` lines) of a diff text, counted without the reader."""
    inside, counted, signs = False, 0, 0
    for line in text.split("\n"):
        if line.startswith("diff --git "):
            inside = False
        elif line.startswith("@@ "):
            inside = True
        elif inside and line[:1] in (" ", "+", "-", "\\"):
            counted += 1
            signs += line[:1] in ("+", "-")
    return counted, signs


def i1_indexed(folder: Path) -> tuple:
    """(sum of body lines of the real hunks, added + removed over the files) of `impl-diff.txt` in `folder`, as the index has it."""
    files = [f for f in D.index(folder)["files"] if f["diff"] == "impl-diff.txt"]
    hunks = [h for f in files for h in f["hunks"] if "pseudo" not in h]
    return sum(len(h["body"]) for h in hunks), sum(f["added"] + f["removed"] for f in files)


REAL = Path(__file__).resolve().parents[4] / "experiments" / "TP1-13877" / "work" / "impl-diff.txt"
if REAL.is_file():
    real_text = REAL.read_bytes().decode("utf-8-sig")
    counted, signs = i1_counts(real_text)
    got = D.index(REAL.parent)
    real_files = [f for f in got["files"] if f["diff"] == "impl-diff.txt"]
    real_hunks = [h for f in real_files for h in f["hunks"] if "pseudo" not in h]
    check_eq("I1 / K10: on the 13877 diff the lines of all hunk bodies are the hunk lines of the file, and added+removed their +/- lines",
             (sum(len(h["body"]) for h in real_hunks), sum(f["added"] + f["removed"] for f in real_files)), (counted, signs))
    check_eq("13877: 19 files, 35 hunks, no hunk truncated or overflowing (F-5: the blank lines between files are separators)",
             (len(real_files), len(real_hunks), [h["truncated"] or h["overflow"] for h in real_hunks].count(True)), (19, 35, 0))
    check_eq("K10: the pseudo-hunk of the file with no hunk (technical-analysis.md) has a body",
             [(f["hunks"][0]["pseudo"], len(f["hunks"][0]["body"])) for f in real_files if "pseudo" in f["hunks"][0]], [("new_empty", 4)])
    raw_json = run_script("diff_pass.py", "--diff", REAL, "--json").stdout
    check_eq("GOLDEN: the full `--json` of the 13877 diff is byte-for-byte what main printed before this node (no new key)",
             hashlib.sha256(raw_json.encode("utf-8")).hexdigest(), "59fd9ae7add887505737b18527f440afc596fcf4e0c2378eb436268b5456d89e")
else:
    print("SKIP the 13877 pins: experiments/TP1-13877 is not in this tree (the synthetic pins below still run)")
SYN = hdr("a.py", "@@ -1,2 +1,2 @@ ctx\n x\n-y\n+z\n") + "diff --git a/n.md b/n.md\nnew file mode 100644\n--- /dev/null\n+++ b/n.md\n\n"
check_eq("GOLDEN (synthetic): `parse` keeps exactly the old keys and values",
         json.loads(json.dumps(D.parse(SYN))),
         [{"path": "a.py", "old_path": "a/a.py", "added": 1, "removed": 1,
           "hunks": [{"new_start": 1, "header": "ctx", "lines": [[2, "-", "y"], [2, "+", "z"]]}]},
          {"path": "n.md", "old_path": "/dev/null", "added": 0, "removed": 0, "hunks": []}])
rich = indexed({"impl-diff.txt": SYN})["files"]
check_eq("K10: the body of a real hunk is its raw lines in order, context included", rich[0]["hunks"][0]["body"], [" x", "-y", "+z"])
check_eq("index: the additive keys live in the index only", [sorted(set(r) - set(D.parse(SYN)[0])) for r in rich[:1]],
         [["deleted", "diff", "new", "path_uncertain", "refused", "repo"]])
check_eq("index: a new file is `new` by its `--- /dev/null` over the `+++` line", [r["new"] for r in rich], [False, True])
# Q8: the I1 twin over this test's own texts - it runs in every tree, the package-only release copy too (the measurer's invariant
# does not wait for a dev-only file). BIG (3500 hunks), the pseudo-hunk sections, SYN, the three newline variants (a marker on each
# side and none) and the legal hunk that ends `--- drop` / `+++ add`.
TWIN = (BIG + "".join(SECTIONS.values()) + SYN + hdr("o.py", NL_OLD) + hdr("p.py", NL_NEW) + hdr("r.py", NL_NONE)
        + hdr("q.sql", "@@ -1,2 +1,2 @@\n x\n--- drop\n+++ add\n@@ -10 +10 @@\n-y\n+z\n"))
twin_counts = i1_counts(TWIN)
folder = work_of({"impl-diff.txt": TWIN})
try:
    check_eq("Q8 / I1 (synthetic twin): the lines of all hunk bodies are the hunk lines of the text (the no-newline markers count, once "
             "each), and added+removed their +/- lines", i1_indexed(folder), twin_counts)
finally:
    cleanup(folder)
check_eq("Q8: ... and the twin is not vacuous (3500 big hunks, 2 markers, the legal hunk)", (twin_counts[0] > 3500 * 2, TWIN.count(MARK)),
         (True, 2))
# unreadable
folder = work_of({"impl-diff.txt": hdr("a.py", "@@ -1 +1 @@\n-a\n+b\n")})
(folder / "impl-diff-bad.txt").mkdir()
try:
    got = D.index(folder)
    check_eq("an unreadable diff is a refusal in the index, not silence; the readable one is read",
             ([f["path"] for f in got["files"]], [(r["diff"], r["kind"]) for r in got["refusals"]]),
             (["a.py"], [("impl-diff-bad.txt", "unreadable")]))
    check_in("... and it says what, what was expected, the door", "re-export it", got["refusals"][0]["text"])
finally:
    cleanup(folder)

# ---------------------------------------------------------------------------------------------------------------------
# SC1-10 B-K3: the S2 tester's form of the pass - `--files-only`, then `--file <path> --max-lines 100000` per file - reads
# EVERY changed line of EVERY hunk (the lesson of TP1-13797). The error direction of the reader is "list more"
# (module docstring), and the inputs below are the awkward ones: a file that cannot be read as hunks, a hunk one line
# past the default cap, and a hunk AT and ONE PAST the ceiling the card names. Killing mutation of each: the flag
# dropped from the card (test_brief_pack_roles B-K1), `--files-only` skipping a hunk-less file (i), a cap applied to a
# value above DEFAULT_MAX_LINES (ii), an off-by-one in render's cap (iii).
CEILING = 100_000          # brief_pack.DIFF_ALL_LINES, written here as a literal: the two files meet at this number
NEW41 = "diff --git a/new.py b/new.py\nnew file mode 100644\n--- /dev/null\n+++ b/new.py\n@@ -0,0 +1,41 @@\n" + "".join(
    f"+changed_line_{n}\n" for n in range(1, 42))
THREE = (hdr("plain.py", "@@ -1 +1 @@\n-a\n+b\n")
         + "diff --cc merged.py\nindex 1,2..3\n--- a/merged.py\n+++ b/merged.py\n@@@ -1,2 -1,2 +1,3 @@@\n+x\n -y\n"
         + "diff --git a/logo.png b/logo.png\nnew file mode 100644\nBinary files /dev/null and b/logo.png differ\n")
folder = work_of({"impl-diff.txt": THREE, "impl-diff-new.txt": NEW41})
try:
    listed = run_script("diff_pass.py", "--diff", folder / "impl-diff.txt", "--files-only")
    check_eq("B-K3 (i): `--files-only` lists the plain file, the combined one and the binary one (a file with no hunks is listed)",
             [line.split("  ")[0] for line in listed.stdout.splitlines()], ["plain.py", "merged.py", "logo.png"])
    check_eq("B-K3 (i): ... exit 3 (read with refusals), and the refusal of the combined diff is on stderr, not in the list",
             (listed.returncode, "combined" in listed.stderr, "combined" in listed.stdout), (3, True, False))
    flagged = run_script("diff_pass.py", "--diff", folder / "impl-diff-new.txt", "--file", "new.py", "--max-lines", CEILING)
    shown = [x for x in flagged.stdout.splitlines() if "changed_line_" in x]
    check_eq("B-K3 (ii): a new file with a hunk of 41 changed lines, `--max-lines 100000`: all 41 are printed, numbered",
             (flagged.returncode, len(shown), shown[0].split()[:2], shown[-1].split()[:2]), (0, 41, ["1", "+"], ["41", "+"]))
    check("B-K3 (ii): ... and no `more changed line(s)` note", "more changed line(s)" not in flagged.stdout)
    plain_run = run_script("diff_pass.py", "--diff", folder / "impl-diff-new.txt", "--file", "new.py")
    check_eq("B-K3 (ii): the same call WITHOUT the flag prints 40 and says '1 more changed line(s)' (the default cap of 40 is real)",
             (len([x for x in plain_run.stdout.splitlines() if "changed_line_" in x]), "1 more changed line(s)" in plain_run.stdout), (40, True))
finally:
    cleanup(folder)


def synthetic_hunk(count: int) -> list:
    return [{"path": "big.py", "added": count, "removed": 0, "hunks": [
        {"new_start": 1, "header": "", "lines": [(n, "+", "x") for n in range(1, count + 1)]}]}]


at_ceiling = D.render(synthetic_hunk(CEILING), CEILING, False)
check_eq("B-K3 (iii): a hunk of exactly 100000 changed lines: all printed (header + hunk line + 100000), no 'more' line",
         (len(at_ceiling), any("more changed line(s)" in x for x in at_ceiling)), (CEILING + 2, False))
beyond = D.render(synthetic_hunk(CEILING + 1), CEILING, False)
check_eq("B-K3 (iii): a hunk of 100001: 100000 lines printed and ONE note", (len(beyond), beyond[-1].startswith("  ... 1 more changed line(s)")),
         (CEILING + 3, True))
check_in("B-K3 (iii): ... the note names the path and the range to read ('read <path> lines a-b'), not silence",
         "read big.py lines 1-100002 if you need them", beyond[-1])

finish("test_diff_pass")
