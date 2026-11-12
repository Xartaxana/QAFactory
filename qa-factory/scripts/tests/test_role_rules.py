"""test_role_rules.py - the register of mandatory role rules (design/role-rules.json) and its one reader scripts/role_rules.py.

One table, CASES: (case id, files {path: text or bytes}, register, expected substrings). Each case builds a temporary package
tree, calls role_rules.findings(root) and requires that every expected substring stands in exactly one finding and that no
finding is left over. The rows are the edges of the spec (td-5 section 6, E-1..E-18, E-20, E-22..E-24); E-19 and E-21 are out of
code and named in the docstring of role_rules.py. The shipped case: the package's own register holds in the package's own text.

Runnable on its own: `python -B scripts/tests/test_role_rules.py`.
"""
import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import role_rules  # noqa: E402

AGENT, OTHER, REF, SLICE = "agents/a.md", "agents/b.md", "references/x.md", "references/slices/r/x.md"
TPL, YAML, CARDS = "references/templates/t.md", "handoffs/h.yaml", "references/cards.json"
ANCHOR = "still in focus"
LOST, TWO, MARKER = "lost the rule", "times. Expected exactly once", "stands only inside a package marker comment"


def c(file=AGENT, anchor=ANCHOR):
    return {"file": file, "anchor": anchor}


def row(ident="r1", *carriers, **over):
    r = {"id": ident, "rule": "The field stays in focus.", "source": "t-1", "carriers": list(carriers) or [c()]}
    r.update(over)
    return r


def reg(*rows):
    return {"schema_version": 1, "rows": list(rows)}


def text(body):
    return f"# Role\n\n{body}\n"


HOLDS = {AGENT: text("The value is kept and the field is still in focus.")}
CASES = [
    ("E-1 register absent", {}, None, ["cannot be read (absent)"]),
    ("E-2 register 0 bytes", {}, b"", ["(0 bytes)"]),
    ("E-2 register not UTF-8", {}, b"\xff\xfe{", ["(not a UTF-8 JSON object)"]),
    ("E-2 register not JSON", {}, "{nope", ["(not a UTF-8 JSON object)"]),
    ("E-2 register not an object", {}, "[1]", ["(not a UTF-8 JSON object)"]),
    ("E-2 rows missing", {}, {"schema_version": 1}, ["`rows` is missing or not a list"]),
    ("E-2 rows not a list", {}, {"schema_version": 1, "rows": {}}, ["`rows` is missing or not a list"]),
    ("E-2 schema_version 2", {}, {"schema_version": 2, "rows": []}, ["schema_version is 2, not 1"]),
    ("E-3 rows empty", {}, reg(), []),
    ("E-4 row not an object", {}, reg("x"), ["the row is not an object"]),
    ("E-4 key missing", HOLDS, reg({k: v for k, v in row().items() if k != "rule"}), ["rule is missing"]),
    ("E-4 unknown key", HOLDS, reg(row(anchors=[])), ["anchors is an unknown key"]),
    ("E-4 source wrong type", HOLDS, reg(row(source=5)), ["source is empty or not a string"]),
    ("E-4 rule empty", HOLDS, reg(row(rule="")), ["rule is empty, not a string, multi-line or too long"]),
    ("E-4 rule over 300", HOLDS, reg(row(rule="x" * 301)), ["rule is empty, not a string, multi-line or too long"]),
    ("E-4 rule multi-line", HOLDS, reg(row(rule="a\nb")), ["rule is empty, not a string, multi-line or too long"]),
    ("E-4 bad id", HOLDS, reg(row("Bad_Id")), ["id is 'Bad_Id'"]),
    ("E-4 carriers empty", HOLDS, reg(row(carriers=[])), ["carriers is empty or not a list"]),
    ("E-4 anchor empty", HOLDS, reg(row("r1", c(anchor=""))), ["has 0 word(s)"]),
    ("E-4 anchor one word", HOLDS, reg(row("r1", c(anchor="focus"))), ["has 1 word(s)"]),
    ("E-4 anchor seven words", HOLDS, reg(row("r1", c(anchor="a b c d e f g"))), ["has 7 word(s)"]),
    ("E-4 anchor over 80 chars", HOLDS, reg(row("r1", c(anchor=" ".join(["w" * 21] * 4)))), ["is over 80 characters"]),
    ("E-4 malformed row is not searched", {}, reg(row("r1", c("agents/gone.md", "focus"))), ["has 1 word(s)"]),
    ("E-5 duplicate id", {AGENT: HOLDS[AGENT], OTHER: text("It is still in focus here.")},
     reg(row("d", c()), row("d", c(OTHER))), ["id d is used by rows 1 and 2"]),
    ("E-6 duplicate guard", HOLDS, reg(row("g1", c()), row("g2", c(anchor="Still  IN focus"))), ["rows g1 and g2 guard the same anchor"]),
    ("E-7 absolute path", HOLDS, reg(row("r1", c("/etc/x.md"))), ["is not a package-relative posix path"]),
    ("E-7 drive path", HOLDS, reg(row("r1", c("C:/x.md"))), ["is not a package-relative posix path"]),
    ("E-7 dot-dot", HOLDS, reg(row("r1", c("agents/../x.md"))), ["is not a package-relative posix path"]),
    ("E-7 backslash", HOLDS, reg(row("r1", c("agents\\a.md"))), ["is not a package-relative posix path"]),
    ("E-7 design file", HOLDS, reg(row("r1", c("design/x.md"))), ["design/x.md is not a role carrier"]),
    ("E-7 script file", HOLDS, reg(row("r1", c("scripts/x.py"))), ["scripts/x.py is not a role carrier"]),
    ("E-7 evals json", HOLDS, reg(row("r1", c("skills/s/evals/e.json"))), ["skills/s/evals/e.json is not a role carrier"]),
    ("E-7 same file twice in one row", {AGENT: text("never strike it. still in focus")},
     reg(row("r1", c(anchor="never strike it"), c())), ["names agents/a.md again", "one carrier entry per file"]),
    ("E-7 carrier suffix is not text", HOLDS, reg(row("r1", c("agents/x.py"))), ["has the suffix '.py'", ".md, .yaml, .yml, .json"]),
    ("E-8 carrier missing", {}, reg(row("r1", c("agents/gone.md"))), ["carrier agents/gone.md does not exist"]),
    ("E-9 carrier not UTF-8", {AGENT: b"\xff\xfe\x00"}, reg(row()), ["cannot be read (not UTF-8)"]),
    ("E-9 json carrier not JSON", {CARDS: "{nope"}, reg(row("r1", c(CARDS))), ["cannot be read (not JSON)"]),
    ("E-10 anchor absent", {AGENT: text("Nothing about it.")}, reg(row()), [LOST, "is not in the text"]),
    ("E-11 anchor twice", {AGENT: text("still in focus. And again still in focus.")}, reg(row()), [TWO]),
    ("E-11 capitalised duplicate counts", {AGENT: text("Still in focus. And still in focus.")}, reg(row()), [TWO]),
    ("E-12 only in kind marker", {AGENT: text("<!-- kind: still in focus -->\nplain")}, reg(row()), [MARKER]),
    ("E-12 only in roles marker", {AGENT: text("<!-- roles: still in focus -->\nplain")}, reg(row()), [MARKER]),
    ("E-12 only in gen marker", {AGENT: text("<!-- gen:digest still in focus -->\nplain")}, reg(row()), [MARKER]),
    ("E-13 inside a fenced block", {AGENT: text("```\nthe field still in focus\n```")}, reg(row()), []),
    ("E-14 wrapped, indented, CRLF, nbsp", {AGENT: "# R\r\n   the field still\r\n\t in\u00a0focus\r\n"}, reg(row()), []),
    ("E-15 case differs", {AGENT: text("Still In Focus.")}, reg(row()), []),
    ("E-16 twin lost, other holds", {AGENT: HOLDS[AGENT], OTHER: text("nothing")}, reg(row("t", c(), c(OTHER))),
     [f"{OTHER} lost the rule", f"still held by: {AGENT}"]),
    ("E-17 json: anchor only in a key", {CARDS: json.dumps({"still in focus": "x"})}, reg(row("r1", c(CARDS))), [LOST]),
    ("E-17 json: anchor in a value holds", {CARDS: json.dumps({"k": ["a", {"z": "the field still in focus"}]})},
     reg(row("r1", c(CARDS))), []),
    ("E-18 slice regenerated without the rule", {REF: text("still in focus"), SLICE: text("nothing")},
     reg(row("s", c(REF), c(SLICE))), [f"{SLICE} lost the rule", f"still held by: {REF}"]),
    ("E-20 yaml comment line", {YAML: "# the field still in focus\nkey: v\n"}, reg(row("r1", c(YAML))), []),
    ("E-22 zero-width space in the anchor words", {AGENT: text("the field still in fo\u200bcus")}, reg(row()), [LOST]),
    ("E-23 ordinary comment of a template", {TPL: "<!--\nguidance: the field still in focus\n-->\n"}, reg(row("r1", c(TPL))), []),
    ("E-24 ordinary comment of an agent file", {AGENT: text("<!-- the field still in focus -->")}, reg(row()), []),
    ("E-24 text between gen and /gen", {AGENT: text("<!-- gen:digest x.py -->\nstill in focus\n<!-- /gen -->")}, reg(row()), []),
]


def judge(case_id, files, register, expect):
    root = harness.temp_dir("qa-role-rules-")
    try:
        for rel, body in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_bytes(body if isinstance(body, bytes) else body.encode("utf-8"))
        if register is not None:
            (root / "design").mkdir()
            (root / "design" / "role-rules.json").write_bytes(
                register if isinstance(register, bytes) else (register if isinstance(register, str) else json.dumps(register)).encode("utf-8"))
        found = role_rules.findings(root)
    finally:
        harness.cleanup(root)
    bad = [f"expected substring {s!r} in {sum(s in f for f in found)} finding(s)" for s in expect if sum(s in f for f in found) != 1]
    bad += [f"unexpected finding: {f}" for f in found if not any(s in f for s in expect)]
    return harness.check(case_id, not bad, "; ".join(bad) + (" | " + " | ".join(found) if bad else ""))


def shipped():
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = role_rules.main(["--check"])
    print(out.getvalue().strip().splitlines()[-1])
    found = role_rules.findings(harness.PLUGIN_ROOT)
    harness.check("shipped register holds in the shipped text", found == [] and code == 0, " | ".join(found))


def empty_register_says_nothing_is_guarded():
    root = harness.temp_dir("qa-role-rules-")
    try:
        (root / "design").mkdir()
        (root / "design" / "role-rules.json").write_text(json.dumps(reg()), encoding="utf-8")
        old, role_rules.PLUGIN_ROOT = role_rules.PLUGIN_ROOT, root
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                code = role_rules.main(["--check"])
        finally:
            role_rules.PLUGIN_ROOT = old
    finally:
        harness.cleanup(root)
    harness.check("E-3 the empty register prints that nothing is guarded and passes",
                  code == 0 and "role-rules: 0 rows - no rule of a role is guarded" in out.getvalue(), out.getvalue())


def main():
    for case in CASES:
        judge(*case)
    empty_register_says_nothing_is_guarded()
    shipped()
    harness.finish("role rules")


if __name__ == "__main__":
    main()
