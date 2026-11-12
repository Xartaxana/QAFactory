#!/usr/bin/env python3
"""SC1-3 part 1: the lines of every list element of `work/grounding.yaml`, and `grounding_section.py` that reads one part by id.

The rule this file holds: a line range that the code names is the lines of exactly that element, and the reader prints the bytes
the file holds. The error direction is "no span / refused whole" - never another element's lines, never a part of the named one
(spec t-1253 section 4, E-1 .. E-5, E-19, E-20). Keys:

  K1  every list element of a fixture that has lines of its own is named, and its span is exactly its lines
  K2  an element whose FIRST key is a block list (no node of its own on the dash line): the span starts at the dash line
  K3  a flow-map element, one line and wrapped over two
  K4  an id the table does not have: refused whole, the first 20 ids listed, then `and N more` (AT 20 / BEYOND 21)
  K5  one id on two elements: both printed, each under its own path (a refusal is never a pick of one)
  K6  a hunk by its id and by its short id; a risk (K-n) prints the row that holds it
  K7  `--requirement` joins the requirement line, the rows that name it and the claims; none naming it is said out loud
  K8  the unusual inputs the first draft of the walk missed: zero-indent lists, a `|` block scalar (trailing blanks, a
      comment-looking last line), comments between elements, a last element with no final newline, a nested list
  K9  the runtime check: a span that does not give back the element it names is left out of the map (M-2)
  K10 the CLI reads through the one reader: an unreadable table is refused with the reader's own words and who acts; a usage
      error is a refusal; nothing is written
"""
import hashlib
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_project  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import handoff as H  # noqa: E402
import planning_contract as PC  # noqa: E402

# One table with the shapes of the writer (block rows, flow rows, a wrapped flow row), the shapes a role leaves behind (a wrapped
# double-quoted value, a `|` block, a comment between rows) and the ones a hand edit makes (a row whose first key is a list, a
# list at the key's own indent). The LAST line has no final newline.
FIXTURE = """schema_version: 1
implementation_source: diff
register_sha256: "abc"
# a comment before the hunks
diff:
  - {path: work/impl-diff.txt, repo: "", sha256: "aa"}
hunks:
  - id: 3f2a9c01b7de-1
    short: H-1
    file: src/a.py
  - {id: 5e5e5e5e5e5e-1, short: H-2, file: src/b.py,
     function: "def f(x):"}
rows:
  - id: G-1
    hunks:
      - "3f2a9c01b7de-1"
    label: implements
    requirements: [R-1]
    risks:
      - id: K-1
        hypothesis: "null at src/a.py:10"
    question: ""
    reason: "a reason that wraps
      over two lines"
  # a comment between two rows
  - risks:
      - id: K-2
        hypothesis: "the second"
    id: G-2
    hunks: []
    label: refactoring
    requirements: []
    question: ""
    reason: |
      first line
      # the scalar's own text, not a comment

  # a comment after a blank line, before the flow row
  - {id: G-3, hunks: [5e5e5e5e5e5e-1], label: "", requirements: [R-1, R-2], risks: [], question: "", reason: ""}
requirements:
  - r: R-1
    state: implemented
    hunks: [3f2a9c01b7de-1]
    where: ""
    question: ""
  - {r: R-2, state: unknown, hunks: [], where: "", question: ""}
  - {r: R-3, state: unknown, hunks: [], where: "", question: ""}
blast_radius:
  index: {schema: 1}
  areas:
    - id: B-1
      key: src/a.py
      touched: {file: src/a.py}
      matters: ""
    - id: B-2
      key: src/b.py
      matters: ""
claims:
  - {row: G-1, r: R-1, requirement: "x", now: "403"}
base_slice: []
orphans:
- was: row
  why_orphan: hunk_gone
- was: row
  why_orphan: area_changed"""
LINES = FIXTURE.split("\n")


def at(text: str, nth: int = 1) -> int:
    """The 1-based number of the `nth` line that is exactly `text`; the fixture is the carrier of every expectation below."""
    found = [i + 1 for i, line in enumerate(LINES) if line == text]
    assert len(found) >= nth, f"fixture has no line {text!r}"
    return found[nth - 1]


def table_of(root: Path, text: str):
    target = root / "work" / "grounding.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode("utf-8"))          # bytes: write_text would turn the line feeds into CRLF on Windows
    return PC.read_grounding(root)


def members_of_flow_lists(doc, paths) -> list:
    """The element paths that live INSIDE a flow value (`requirements: [R-1, R-2]`, or a list inside a flow-map row): a scalar
    node of the Doc is an ancestor of them, and they have no line of their own."""
    return [p for p in paths if any(p.startswith(n) and len(p) > len(n) and p[len(n)] in ".[" for n in doc.nodes)]


def trimmed(value):
    """`value` with the line feeds at the end of every text taken off (a block scalar's text carries the blank lines after it)."""
    if isinstance(value, str):
        return value.rstrip("\n")
    if isinstance(value, dict):
        return {k: trimmed(v) for k, v in value.items()}
    if isinstance(value, list):
        return [trimmed(v) for v in value]
    return value


def all_elements(data) -> list:
    out = []

    def walk(value, path):
        if isinstance(value, dict):
            for key, item in value.items():
                walk(item, f"{path}.{key}" if path else key)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                out.append(f"{path}[{i}]")
                walk(item, f"{path}[{i}]")
    walk(data, "")
    return out


def main() -> None:
    project = temp_project("qa-grounding-section-")
    story = project / "qa-factory" / "artifacts" / "TP3-1"
    (story / "work").mkdir(parents=True)
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project))
    try:
        # ---- K1 / K2 / K3 / K8: the spans of the fixture ------------------------------------------------------------------
        doc, problem = table_of(story, FIXTURE)
        check("the fixture is read clean by the one reader", doc is not None and problem == "", str(problem))
        spans = PC.grounding_item_lines(doc)

        expected = {
            # K1 - a block row: from its dash line to its last key; the wrapped quoted value ends the row
            "rows[0]": (at("  - id: G-1"), at("      over two lines\"")),
            "hunks[0]": (at("  - id: 3f2a9c01b7de-1"), at("    file: src/a.py")),
            "requirements[0]": (at("  - r: R-1"), at("    question: \"\"", 3)),
            "blast_radius.areas[0]": (at("    - id: B-1"), at("      matters: \"\"")),
            "blast_radius.areas[1]": (at("    - id: B-2"), at("      matters: \"\"", 2)),
            "diff[0]": (at("  - {path: work/impl-diff.txt, repo: \"\", sha256: \"aa\"}"),) * 2,
            # K2 - the first key is a block list: the span still starts at the dash
            "rows[1]": (at("  - risks:"), at("      # the scalar's own text, not a comment")),
            # K3 - a flow map: one line, and wrapped over two
            "rows[2]": (at("  - {id: G-3, hunks: [5e5e5e5e5e5e-1], label: \"\", requirements: [R-1, R-2], risks: [], question: \"\", reason: \"\"}"),) * 2,
            "requirements[1]": (at("  - {r: R-2, state: unknown, hunks: [], where: \"\", question: \"\"}"),) * 2,
            "hunks[1]": (at("  - {id: 5e5e5e5e5e5e-1, short: H-2, file: src/b.py,"), at("     function: \"def f(x):\"}")),
            "claims[0]": (at("  - {row: G-1, r: R-1, requirement: \"x\", now: \"403\"}"),) * 2,
            # K8 - nested elements, a scalar item, a list at the key's own indent, the last element with no final newline
            "rows[0].risks[0]": (at("      - id: K-1"), at("        hypothesis: \"null at src/a.py:10\"")),
            "rows[1].risks[0]": (at("      - id: K-2"), at("        hypothesis: \"the second\"")),
            "rows[0].hunks[0]": (at("      - \"3f2a9c01b7de-1\""),) * 2,
            "orphans[0]": (at("- was: row"), at("  why_orphan: hunk_gone")),
            "orphans[1]": (at("- was: row", 2), len(LINES)),
        }
        for path, want in expected.items():
            check_eq(f"K1/K2/K3/K8 span of {path}", spans.get(path), want)
        # the top-level keys: from the key line to the last line of the key's content, a comment before the next key excluded
        tops = {
            "schema_version": (1, 1), "register_sha256": (3, 3),
            "diff": (at("diff:"), at("hunks:") - 1),
            "hunks": (at("hunks:"), at("rows:") - 1),
            "rows": (at("rows:"), at("requirements:") - 1),
            "requirements": (at("requirements:"), at("blast_radius:") - 1),
            "blast_radius": (at("blast_radius:"), at("claims:") - 1),
            "claims": (at("claims:"), at("base_slice: []") - 1),
            "base_slice": (at("base_slice: []"),) * 2,
            "orphans": (at("orphans:"), len(LINES)),
        }
        for path, want in tops.items():
            check_eq(f"K1 span of the top-level key {path}", spans.get(path), want)
        # the comment BEFORE the hunks belongs to no key, and the comment between rows to no row
        comment_line = at("# a comment before the hunks")
        check("K8 a comment between top-level keys is in no span", not any(a <= comment_line <= b for a, b in spans.values()))
        between = at("  # a comment between two rows")
        check("K8 a comment between two rows is in no ELEMENT span (rows[0] ends before it, rows[1] starts after it)",
              spans["rows[0]"][1] < between < spans["rows[1]"][0])
        check_eq("K8 the `|` block scalar's last line is the row's last line (a text, not a comment) and its trailing blank is not",
                 spans["rows[1]"][1], at("      # the scalar's own text, not a comment"))
        check("K8 the comment after the blank line is in no span of rows[1] or rows[2]",
              spans["rows[1]"][1] < at("  # a comment after a blank line, before the flow row") < spans["rows[2]"][0])

        # K1 as a class: every element that has lines of its own is named; the span, put under a key and read again, is the element
        paths = all_elements(doc.data)
        flow_members = set(members_of_flow_lists(doc, paths))
        check_eq("K1 every element with lines of its own is named (only members of a flow value are not)",
                 sorted(p for p in paths if p not in spans), sorted(flow_members))
        for path, (first, last) in sorted(spans.items()):
            if "[" not in path.split(".")[-1]:
                continue                                   # a top-level key is checked by `tops`
            body = LINES[first - 1:last]
            lead = len(body[0]) - len(body[0].lstrip())
            if body[0].lstrip().startswith("- ") and ":" in body[0] and not body[0].lstrip().startswith(("- {", '- "')):
                again = H.parse("\n".join([" " * lead + "  " + body[0].lstrip()[2:]] + body[1:])).data
                element = doc.data
                for token in re.findall(r"\[(\d+)\]|\.?([^.\[\]]+)", path):
                    element = element[int(token[0])] if token[0] != "" else element[token[1]]
                check(f"K1 the lines of {path}, read again as a map, are the element", trimmed(again) == trimmed(element),
                      f"{again!r} != {element!r}")

        # ---- K8: the robustness inputs (a Doc the walk cannot place never raises, never names a wrong span) ----------------
        for label, text in (("an empty document", ""), ("only comments", "# nothing\n\n"),
                            ("a stray line", "schema_version: 1\nthis line is no yaml\nrows:\n  - id: G-1\n"),
                            ("a key with a dash and no list", "rows:\n  - id: G-1\n  b: 1\n"),
                            ("a scalar list at the top level of a key", "rows:\n  - a\n  - b\n")):
            got = PC.grounding_item_lines(H.parse(text))
            check(f"K8 {label}: the function answers with a dict and every span is inside the text",
                  isinstance(got, dict) and all(1 <= a <= b <= max(1, len(text.split("\n"))) for a, b in got.values()), repr(got))
        zero = H.parse("requirements:\n- r: R-1\n  state: x\n- r: R-2\n  state: y\nclaims: []\n")
        check_eq("K8 a list at the key's own indent: both elements, each its own two lines",
                 [PC.grounding_item_lines(zero).get(f"requirements[{i}]") for i in (0, 1)], [(2, 3), (4, 5)])
        check_eq("K8 and the key owns its zero-indent items", PC.grounding_item_lines(zero).get("requirements"), (1, 5))

        # ---- K9: a span that does not give back the element it names is left out ---------------------------------------------
        tampered, _ = table_of(story, FIXTURE)
        tampered.data["rows"][0]["label"] = "something the lines do not say"
        got = PC.grounding_item_lines(tampered)
        check("K9 an element whose data the lines do not give back is left out of the map", "rows[0]" not in got)
        check("K9 and its neighbours stay", "rows[1]" in got and "rows[2]" in got and "requirements[0]" in got)
        check("K9 and the top-level key that holds it is left out too (the lines no longer give back the key)", "rows" not in got)
        extra = H.parse(FIXTURE)
        extra.data["claims"].append({"row": "G-9"})          # the data holds one more element than the lines: no span for it
        check("K9 an element with no lines is not invented", "claims[1]" not in PC.grounding_item_lines(extra))

        # ---- K10 / K4 / K5 / K6 / K7: the CLI -----------------------------------------------------------------------------------
        def run(*args):
            got = run_script("grounding_section.py", "--task", "TP3-1", "--task-root", story, *args, cwd=project, env=env)
            return got.returncode, got.stdout, got.stderr

        target = story / "work" / "grounding.yaml"
        table_of(story, FIXTURE)
        before = hashlib.sha256(target.read_bytes()).hexdigest()

        code, out, err = run("--show", "G-2")
        want = f"G-2 (rows[1], lines {spans['rows[1]'][0]}-{spans['rows[1]'][1]})\n" + "\n".join(LINES[spans["rows[1]"][0] - 1:spans["rows[1]"][1]])
        check_eq("--show G-2: exit 0 and exactly the header and the file's own lines", (code, out.strip("\n").replace("\r\n", "\n")), (0, want))
        check_eq("--show G-2: nothing on stderr", err, "")

        code, out, err = run("--show", "G-1", "--show", "B-2", "--show", "R-3")
        out = out.replace("\r\n", "\n")
        check("--show repeated: three parts, in the order asked, each under its header", code == 0 and out.index("G-1 (rows[0]") < out.index(
            "B-2 (blast_radius.areas[1]") < out.index("R-3 (requirements[2]"), out[:300])
        code, out, _ = run("--show", "G-1", "--show", "G-1")
        check_eq("--show with the same id twice prints the part once", out.count("G-1 (rows[0]"), 1)

        # K6: the two spellings of a hunk, and a risk
        h1 = run("--show", "3f2a9c01b7de-1")[1]
        h2 = run("--show", "H-1")[1]
        check("K6 a hunk by its id and by its short id: the same element", "hunks[0]" in h1 and "hunks[0]" in h2 and h1.count("hunks[0]") == 1,
              h1[:200])
        code, out, _ = run("--show", "K-2")
        check("K6 a risk prints the row that holds it, with the row's lines", code == 0 and out.startswith("K-2 (rows[1], lines ") and "id: G-2" in out,
              out[:200])

        # K5: one id on two elements (a requirement line and a claim carry R-1)
        code, out, _ = run("--show", "R-1")
        out = out.replace("\r\n", "\n")
        check("K5 R-1 is a requirement and a claim: both are printed, each under its own path",
              code == 0 and "R-1 (requirements[0], lines " in out and "R-1 (claims[0], lines " in out
              and out.index("requirements[0]") < out.index("claims[0]"), out[:400])

        # K7: --requirement is the join
        code, out, _ = run("--requirement", "R-1")
        out = out.replace("\r\n", "\n")
        order = [out.find(x) for x in ("R-1 (requirements[0]", "G-1 (rows[0]", "G-3 (rows[2]", "R-1 (claims[0]")]
        check("K7 --requirement R-1: the requirement line, the rows that name it, then the claim", code == 0 and order == sorted(order) and -1 not in order,
              out[:500])
        check_not_in("K7 and not the rows that do not name it", "G-2 (rows[1]", out)
        code, out, _ = run("--requirement", "R-3")
        check("K7 a requirement no row names: its line, and `rows naming R-3: none` (not an empty answer)",
              code == 0 and "R-3 (requirements[2]" in out and "rows naming R-3: none" in out, out[:300])
        code, out, err = run("--requirement", "R-9")
        check("K7 a requirement the table has not: refused whole", code == 2 and out == "" and "no requirement `R-9`" in err, err[:200])
        code, out, err = run("--requirement", "G-1")
        check("K7 an id that is not a requirement is no requirement: refused", code == 2 and out == "" and "no requirement `G-1`" in err, err[:200])
        listed = err.split("requirements there: ", 1)[1].split(". ", 1)[0] if "requirements there: " in err else ""
        check_eq("K7/F-2 the refusal lists the requirements there are, and not the id it refused (G-1)", listed, "R-1, R-2, R-3")
        check_in("K7/F-2 and names --show as the door to the id that is another part of the table", "`--show G-1` prints it", err)
        check_not_in("K7/F-2 (no door to an id the table does not have at all)", "--show R-9", run("--requirement", "R-9")[2])
        code, out, err = run("--requirement", "")
        check("K7 an empty --requirement is a refusal, not an empty answer", code == 2 and out == "", f"{code} {out!r} {err[:100]!r}")

        # K4: an id that is not there (E-1): refused whole, the ids listed by the file's order
        code, out, err = run("--show", "G-1", "--show", "G-99")
        check("K4 one id missing among two: exit 2, NOTHING of the other is printed", code == 2 and out == "", f"{code} {out[:100]!r}")
        check_in("K4 the refusal names the id and the file", "no `G-99` in work/grounding.yaml; ids there: ", err)
        check_in("K4 and starts the list with the table's first id, in the file's order", "ids there: 3f2a9c01b7de-1, H-1, 5e5e5e5e5e5e-1, H-2, G-1, K-1", err)
        check_not_in("K4 a short list has no tail", " more", err)
        code, out, err = run("--show", "")
        check("K4 an empty id is a missing id, not everything", code == 2 and out == "" and "no `` in" in err, err[:150])
        check_eq("nothing was written by any call", hashlib.sha256(target.read_bytes()).hexdigest(), before)

        # K4 at and beyond the limit of 20
        for count in (20, 21):
            text = "schema_version: 1\nrows:\n" + "".join(f"  - id: G-{n}\n    label: x\n" for n in range(1, count + 1))
            table_of(story, text)
            code, out, err = run("--show", "G-99")
            listed = err.split("ids there: ", 1)[1].split(". ", 1)[0] if "ids there: " in err else ""
            if count == 20:
                check("K4 AT the limit: 20 ids, all listed, no tail",
                      code == 2 and listed == ", ".join(f"G-{n}" for n in range(1, 21)), listed[-80:])
            else:
                check_eq("K4 BEYOND the limit: 20 ids and `and 1 more`; the 21st is not named",
                         (code, listed), (2, ", ".join(f"G-{n}" for n in range(1, 21)) + " and 1 more"))

        # K5 (a row id written twice): both are printed, each under its own path
        table_of(story, "schema_version: 1\nrows:\n  - id: G-1\n    label: a\n  - id: G-1\n    label: b\n")
        code, out, _ = run("--show", "G-1")
        out = out.replace("\r\n", "\n")
        check_eq("K5 the same row id on two rows: both parts, each with its own lines",
                 (code, out.strip("\n")), (0, "G-1 (rows[0], lines 3-4)\n  - id: G-1\n    label: a\n\nG-1 (rows[1], lines 5-6)\n  - id: G-1\n    label: b"))

        # a table the one reader refuses: its words and who acts, nothing printed
        table_of(story, "schema_version: 1\nrows: []\nrows: []\n")
        code, out, err = run("--show", "G-1")
        check("K10 an unreadable table (a key written twice): refused with the reader's own sentence and who acts",
              code == 2 and out == "" and "writes the key `rows` twice" in err and "for the role to put right" in err, err[:300])
        target.unlink()
        code, out, err = run("--show", "G-1")
        check("K10 no table at all: refused, the driver acts", code == 2 and out == "" and "does not exist" in err and "for the driver" in err, err[:300])
        table_of(story, "\ufeffschema_version: 1\n")
        code, out, err = run("--show", "G-1")
        check("K10 a byte-order mark: the reader's refusal, not a map", code == 2 and "byte-order mark" in err, err[:200])

        # usage
        table_of(story, FIXTURE)
        for label, args in (("--show with no id", ["--show"]), ("neither --show nor --requirement", []),
                            ("both --show and --requirement", ["--show", "G-1", "--requirement", "R-1"])):
            code, out, err = run(*args)
            check(f"K10 usage: {label} is a refusal (exit 2), nothing printed", code == 2 and out == "" and err != "", f"{code} {err[:120]!r}")
        got = run_script("grounding_section.py", "--task", "TP3-1", "--task-r", story, "--show", "G-1", cwd=project, env=env)
        check("K10 an abbreviated --task-root is not read as --task-root", got.returncode == 2 and "names no story" not in got.stdout + got.stderr)
        got = run_script("grounding_section.py", "--task", "TP3-404", "--task-root", story.parent / "TP3-404", "--show", "G-1", cwd=project, env=env)
        check("K10 a phantom story is refused by the story driver", got.returncode == 2 and "names no story" in got.stderr, got.stderr[:200])
        check_eq("K10 and the table is still the bytes of the fixture", target.read_bytes(), FIXTURE.encode("utf-8"))
    finally:
        cleanup(project)
    finish("test_grounding_section")


if __name__ == "__main__":
    main()
