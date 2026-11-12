#!/usr/bin/env python3
"""The report contract: what a person is handed at gate B, and in what order.

TP1-15045 was assembled from the machine ledger upwards. Its first line was "24 reasons
on the product side" — about twenty of them the factory's own bookkeeping; it had no list of
what had been proven, no single list of what was left with the person, and no size; it linked
to `work/ledger.json` four times and to the four human documents once; it printed `cv_` and
`ti_` hashes and the decision id `S5-160` without the decision's words; and it was written
before gate B, so it still said the bugs awaited a word the person had already given.

Each rule below is one of those, turned into a refusal.

B-211 (t-189, piece P8) added the report CONTRACT of the code-owned blocks: the marker grammar
(`grammar.py`), the block and section checks (`validate_artifacts.check_report_blocks`), the template,
and the three changes of `traceability.py` the report stands on - the bug reader (one reader, the
story's own), the disposition reading of a case-less plan row and of a planned manual case, and the
"answered at gate A" suffix. A report with no marker at all is the generation before the blocks: none
of the new sections and blocks is owed by it, and it says so.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, repaste_appendix, temp_dir  # noqa: E402
from harness import SCRIPTS  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import grammar as G  # noqa: E402
import validate_artifacts as V  # noqa: E402

TEMPLATE = Path(__file__).resolve().parents[2] / "references" / "templates" / "test-report.md"

REGISTER = """---
task: T-1
---

## Register

| R | Requirement | source | derived_from | verifiable | ac_ref |
|---|---|---|---|---|---|
| R-1 | The owner can cancel from settings | ac | — | yes | AC-1 |
| R-2 | Access lasts to the end of the paid period | ac | — | yes | AC-2 |
"""

PLAN = """---
task: T-1
---
# Test plan - T-1

## Plan

| TS | what we verify | R | defect hypothesis | impact class | priority | observable | oracle | disposition + reason | fit | level | technique |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TS-1 | cancel from settings | R-1 | state @ cancel | degraded | P2 | diff:src/a.py:1 | requirement:R-1 | `automate` — core AC | new | api | decision table |
"""

CASE = """---
id: TC-001
title: The owner can cancel from settings
area: billing
task: T-1
covers: [R-1]
plan_row: TS-1
---
Requirements: R-1
Plan row: TS-1

## Then
1. The subscription reads cancelled.
"""

REPORT = """# T-1 — test report

**The change.** Cancelling a subscription from settings.

**Verdict: ready to ship.** Of 2 requirements, 1 is proven by a test, 1 waits for you.

`delivery_ready: yes`

Notation: R-n — a requirement; TC-n — a test case; TS-n — a plan row.

## Proven — 1 green test

- R-1 the owner can cancel from settings (TC-001) — reviewed, the check is live

## Product bugs — 0

None found.

## Left with you

1. **Access after cancelling (R-2, TC-001).** To check: the subscription still answers
   until the end of the paid period. How: check by hand on preview.

## Not proven, and what it costs

- **R-2** — nobody waited out a billing period on this stand.

## Factory defects — nothing is wanted from you

Nothing this run.

## Size

Forecast: **S**. Fact: **S**. No re-estimation during the story.

## Where to look

- understanding.md, test-plan.md, retro.md, the appendix below

## Appendix — traceability

| R | What we verify | TC | Result | Basis |
|:--|:--|:--|:--|:--|
| R-1 | cancel from settings | TC-001 | **pass** | critic review - the check is live |
| R-2 | access lasts the paid period | TC-001 | **wait** | no billing period on the stand |
"""

GATE_B = """
## Decided at gate B

- Delivery: "create a draft MR, bugs into a file"
- S8 · keep it local: "collect all bugs into a file and show them to me in chat"
"""


def story() -> Path:
    root = temp_dir("qa-report-contract-")
    task = root / "qa-factory" / "artifacts" / "T-1"
    (task / "work" / "test-cases" / "billing").mkdir(parents=True)
    (task / "state").mkdir(parents=True)
    (task / "work" / "requirements-register.md").write_text(REGISTER, encoding="utf-8")
    (task / "test-plan.md").write_text(PLAN, encoding="utf-8")
    (task / "work" / "test-cases" / "billing" / "TC-001.md").write_text(CASE, encoding="utf-8")
    (task / "pipeline.json").write_text(json.dumps({
        "ticket": "T-1",
        "gates": {"B": {"authorization_source": "create a draft MR, bugs into a file"}},
        "stage_overrides": [{"stage": "S8", "match": "keep it local",
                             "decision": "collect all bugs into a file and show them to me in chat"}],
    }), encoding="utf-8")
    return root


def errors_for(task: Path, text: str) -> list:
    path = task / "test-report.md"
    path.write_text(text, encoding="utf-8")
    found: list = []
    V.check_test_report(path, found)
    return found


MARKED = """# T-1 — test report

**The change.** Cancelling a subscription from settings.

<!-- facts:verdict -->
**Verdict: ready to ship.** Of 2 requirements, 1 is proven by a test, 1 waits for you.

`delivery_ready: yes`
<!-- /facts:verdict -->

Notation: R-n — a requirement; TC-n — a test case; TS-n — a plan row.

<!-- facts:proven -->
## Proven — 1 green test

- R-1 the owner can cancel from settings (TC-001) — reviewed, the check is live
<!-- /facts:proven -->

<!-- facts:manual-checks -->
## Checked by hand — 0 of 0

Nothing to show: no case was planned for a manual check.
<!-- /facts:manual-checks -->

<!-- facts:bugs -->
## Product bugs — 0

None found.
<!-- /facts:bugs -->

<!-- facts:review-gaps -->
## Review gaps — 0 tests the code critic rejected

None: the code critic left no test rejected.
<!-- /facts:review-gaps -->

## Left with you

1. **Access after cancelling (R-2, TC-001).** To check: the subscription still answers
   until the end of the paid period. How: check by hand on preview.

<!-- facts:regression -->
### Regression to run (from the plan approved at gate A)

- `poetry run pytest tests/test_billing.py` - the billing path the change reuses
<!-- /facts:regression -->

<!-- facts:open-questions -->
## Open questions — 0

none
<!-- /facts:open-questions -->

<!-- facts:skipped-by-plan -->
## Skipped by the plan (approved at gate A)

Nothing: the approved plan skipped no requirement.
<!-- /facts:skipped-by-plan -->

<!-- facts:not-proven -->
## Not proven, and what it costs

- **R-2** — nobody waited out a billing period on this stand : a wrong end date ships unseen.
<!-- /facts:not-proven -->

<!-- facts:gate-a -->
## Decided at gate A

```
go on, size S
```
<!-- /facts:gate-a -->

## Factory defects — nothing is wanted from you

Nothing this run.

<!-- facts:size -->
## Size

Forecast: **S**. Fact: **S**. Difference: none.
<!-- /facts:size -->

<!-- facts:where-to-look -->
## Where to look

- understanding.md, test-plan.md, the appendix below
<!-- /facts:where-to-look -->

## Appendix — traceability

| R | What we verify | TC | Result | Basis |
|:--|:--|:--|:--|:--|
| R-1 | cancel from settings | TC-001 | **pass** | critic review - the check is live |
| R-2 | access lasts the paid period | TC-001 | **wait** | no billing period on the stand |
"""

SIZE_BLOCK = "intro\n<!-- facts:size -->\n## Size\n\nFact: S\n<!-- /facts:size -->\noutro\n"


def write_bytes(path: Path, text: str) -> None:
    """A file with exactly these line endings (`write_text` turns LF into CRLF on Windows)."""
    path.write_bytes(text.encode("utf-8"))


def grammar_contract() -> None:
    """The marker grammar, pinned: a marker is a whole line at column 0 outside a code fence."""
    tpl = TEMPLATE.read_text(encoding="utf-8")
    found = G.find_blocks(tpl)
    check_eq("the template carries every block of REPORT_BLOCKS except the when-present ones, in REPORT_BLOCKS order",
             sorted(found, key=lambda name: found[name][0]),
             [b for b in G.REPORT_BLOCKS if b not in G.REPORT_BLOCKS_WHEN_PRESENT])
    # t-250 B3: `## Checked by hand` is a code-owned block heading, deliberately not a REPORT_SECTIONS entry (that tuple
    # is the scribe's section list: its card, the handoff, the report-text tests). The template carries it right
    # after Proven, where the block stands.
    block_only_all = [h for h in G.REPORT_BLOCK_HEADINGS.values() if h and h not in G.REPORT_SECTIONS]
    check_eq("the block-only headings are manual-checks, the exploratory block (when present), review-gaps (C1-5c), the two "
             "blocks inside Left with you (t-305 N8, `### `) and the plan-skipped one (owner amendment 03.10)", block_only_all,
             ["## Checked by hand", "## Exploratory findings and unresolved questions", "## Review gaps", "### Branches left with you",
              "### Added after gate B", "### Regression to run", "## Skipped by the plan (approved at gate A)", "## Branches not proven"])
    # the template carries no `exploratory` block (a story without a register is byte-identical), so its headings are
    # the block-only ones without the when-present block's
    block_only = [h for name, h in G.REPORT_BLOCK_HEADINGS.items()
                  if h and h not in G.REPORT_SECTIONS and name not in G.REPORT_BLOCKS_WHEN_PRESENT]
    expected = list(G.REPORT_SECTIONS)
    expected.insert(expected.index("## Proven") + 1, "## Checked by hand")
    expected.insert(expected.index("## Product bugs") + 1, "## Review gaps")
    expected.insert(expected.index("## Open questions") + 1, "## Skipped by the plan (approved at gate A)")
    check_eq("and its `## ` headings are REPORT_SECTIONS plus the block-only ones in their places, in order",
             [next(s for s in tuple(G.REPORT_SECTIONS) + tuple(block_only) if h.startswith(s)) for h in G.heading_lines(tpl)],
             expected)
    check("the template's block stands right after `proven` and before `bugs`",
          tpl.index("<!-- facts:proven -->") < tpl.index("<!-- facts:manual-checks -->") < tpl.index("<!-- facts:bugs -->"))
    check_eq("`manual-checks` is the block right after `proven` in the grammar too",
             G.REPORT_BLOCKS[G.REPORT_BLOCKS.index("proven") + 1], "manual-checks")
    for name, heading in G.REPORT_BLOCK_HEADINGS.items():
        if name in G.REPORT_BLOCKS_WHEN_PRESENT:
            continue    # the template carries no such block
        body = found[name][2]
        first = next(ln for ln in body.splitlines() if ln.strip())
        check(f"the template's block {name} opens with its own heading", first.startswith(heading), first)
    order = list(G.REPORT_SECTIONS)
    check_eq("F18: Open questions stands right after Left with you",
             order[order.index("## Left with you") + 1], "## Open questions")
    check("and before Factory defects", order.index("## Open questions") < order.index("## Factory defects"))
    check("F10: Decided at gate A stands before gate B's section",
          order.index("## Decided at gate A") < order.index("## Decided at gate B"))
    check_eq("only gate B's block, and the block of what its answers added, wait for the gate", G.REPORT_BLOCKS_AFTER_GATE_B,
             ("gate-b", "left-gate-b"))
    check("t-305 N8: the two blocks inside Left with you stand after the scribe's items and before Open questions",
          G.REPORT_BLOCKS.index("bugs") < G.REPORT_BLOCKS.index("left-gate-b") < G.REPORT_BLOCKS.index("regression")
          < G.REPORT_BLOCKS.index("open-questions"))
    check("owner amendment 03.10: `skipped-by-plan` stands right before `not-proven`",
          G.REPORT_BLOCKS.index("skipped-by-plan") + 1 == G.REPORT_BLOCKS.index("not-proven"))
    check("and the template carries both headings as the amendment names them",
          "## Skipped by the plan (approved at gate A)" in tpl and "## Not proven, and what it costs" in tpl)

    start, end, body = G.find_blocks(SIZE_BLOCK)["size"]
    check_eq("a block's body is the span between its marker lines", body, "## Size\n\nFact: S\n")
    check_eq("and (start, end) are its offsets", SIZE_BLOCK[start:end], body)
    check_eq("replacing a block with its own body changes no byte", G.replace_block(SIZE_BLOCK, "size", body), SIZE_BLOCK)
    check_eq("a new body goes between the same marker lines, the rest untouched",
             G.replace_block(SIZE_BLOCK, "size", "## Size\n\nFact: M"),
             "intro\n<!-- facts:size -->\n## Size\n\nFact: M\n<!-- /facts:size -->\noutro\n")
    check_eq("an empty body leaves the markers adjacent",
             G.replace_block(SIZE_BLOCK, "size", ""), "intro\n<!-- facts:size -->\n<!-- /facts:size -->\noutro\n")
    check_eq("render_block is the marked block, LF, a final newline",
             G.render_block("size", "## Size\r\nFact: S"), "<!-- facts:size -->\n## Size\nFact: S\n<!-- /facts:size -->\n")
    check_eq("render is deterministic (R-S9.3)", G.render_block("size", "a\nb"), G.render_block("size", "a\nb"))
    check_eq("canonical_body equates line endings and the last terminator",
             G.canonical_body("a\r\nb"), G.canonical_body("a\nb\n"))
    try:
        G.render_block("bogus", "x")
        check("render_block refuses a name the report does not have", False, "no error")
    except G.BlockError as exc:
        check_in("render_block refuses a name the report does not have, naming the blocks", "verdict", str(exc))

    # edge (iv): CRLF - markers found, the body keeps the file's endings, the write is LF inside the block
    crlf = SIZE_BLOCK.replace("\n", "\r\n")
    check_eq("CRLF: the markers are found and the body keeps the file's own endings",
             G.find_blocks(crlf)["size"][2], "## Size\r\n\r\nFact: S\r\n")
    changed = G.replace_block(crlf, "size", "## Size\r\n\r\nFact: M")
    check_eq("CRLF: replace_block writes LF inside the block and leaves every other byte as it was",
             changed, "intro\r\n<!-- facts:size -->\r\n## Size\n\nFact: M\n<!-- /facts:size -->\r\noutro\r\n")
    check_eq("CRLF: a second write of the same body changes nothing (a CRLF file checks clean after --write)",
             G.replace_block(changed, "size", "## Size\r\n\r\nFact: M"), changed)
    check_eq("CRLF: the rewritten block is equal to a fresh render under canonical_body",
             G.canonical_body(G.find_blocks(changed)["size"][2]), G.canonical_body("## Size\n\nFact: M"))
    weird = SIZE_BLOCK.replace("Fact: S", "Fact: S still the same line\x0cfor a person's words")
    wstart, wend, wbody = G.find_blocks(weird)["size"]
    check_eq("U+2028 and a form feed in the body do not move an offset", weird[wstart:wend], wbody)
    check_eq("and replace_block still cuts the right bytes",
             G.replace_block(weird, "size", "x"), "intro\n<!-- facts:size -->\nx\n<!-- /facts:size -->\noutro\n")

    # the line-start rule
    check("a marker indented by one space is not a marker", not G.has_markers(" <!-- facts:size -->\n <!-- /facts:size -->\n"))
    check("a marker with text after it is not a marker", not G.has_markers("<!-- facts:size --> x\n<!-- /facts:size --> x\n"))
    check("a marker in the middle of a line is not a marker", not G.has_markers("see <!-- facts:size --> here\n"))
    check("trailing spaces after a marker are fine", G.has_markers("<!-- facts:size -->  \n<!-- /facts:size -->\t\n"))
    check("text with no marker has none", not G.has_markers("## Size\n\nFact: S\n"))

    # edge (ii): the fence rule
    fenced_close = "<!-- facts:proven -->\n## Proven — 1 green test\n\n```\n<!-- /facts:proven -->\n```\n"
    problems = G.marker_problems(fenced_close)
    check_eq("a closing marker inside a fence: ONE problem", len(problems), 1)
    first = problems[0] if problems else ""
    check_in("and it names the block", "block `proven`", first)
    check_in("the line of the fenced marker", "line 5 carries it inside a code fence", first)
    check_in("and what to do (FR-1)", "at the start of a line, outside a code fence", first)
    check("a marker inside a ``` fence is not a marker", not G.has_markers("```\n<!-- facts:size -->\n```\n"))
    check("nor inside a ~~~ fence", not G.has_markers("~~~\n<!-- facts:size -->\n~~~\n"))
    check("a fence is closed by a line at least as long: four backticks close three",
          G.has_markers("```\nx\n````\n<!-- facts:size -->\n<!-- /facts:size -->\n"))
    check("a shorter line does not close a longer fence",
          not G.has_markers("````\n```\n<!-- facts:size -->\n<!-- /facts:size -->\n````\n"))
    check("a ~~~ line does not close a ``` fence",
          not G.has_markers("```\n~~~\n<!-- facts:size -->\n<!-- /facts:size -->\n```\n"))
    check("a fence never closed swallows the rest of the file",
          not G.has_markers("```\n<!-- facts:size -->\n<!-- /facts:size -->\n"))
    check("three backticks inline with text after are no fence",
          G.has_markers("```x```\n<!-- facts:size -->\n<!-- /facts:size -->\n"))
    check("a fence of three or four spaces of indent is no fence (four is code)",
          G.has_markers("    ```\n<!-- facts:size -->\n<!-- /facts:size -->\n"))
    gate_a = "<!-- facts:gate-a -->\n## Decided at gate A\n\n```\nthe words\n```\n<!-- /facts:gate-a -->\n"
    check_eq("a fence INSIDE a block (the gate A words) does not hide the closing marker",
             G.marker_problems(gate_a), [])
    check_eq("and the body keeps the fence", G.find_blocks(gate_a)["gate-a"][2].count("```"), 2)
    check_eq("a heading inside a fence is no heading", G.heading_lines("## A\n```\n## B\n```\n## C\n"), ["## A", "## C"])

    # edge (iii): duplicates, unknown names, stray and crossed markers
    two = SIZE_BLOCK + "<!-- facts:size -->\nagain\n<!-- /facts:size -->\n"
    check_in("a duplicate block is a problem", "opens a second time", " ".join(G.marker_problems(two)))
    check_in("an unknown block name is a problem naming the blocks there are", "names a block the report does not have",
             " ".join(G.marker_problems("<!-- facts:bogus -->\n<!-- /facts:bogus -->\n")))
    check_in("and lists them", "where-to-look", " ".join(G.marker_problems("<!-- facts:bogus -->\n")))
    check_in("a closing marker with no opening one", "closes a block that is not open",
             " ".join(G.marker_problems("text\n<!-- /facts:size -->\n")))
    check_in("a block closed by another block's marker", "a block is closed by its own marker",
             " ".join(G.marker_problems("<!-- facts:size -->\n<!-- /facts:proven -->\n")))
    check_in("a block opened inside another", "blocks do not nest",
             " ".join(G.marker_problems("<!-- facts:size -->\n<!-- facts:proven -->\n<!-- /facts:proven -->\n<!-- /facts:size -->\n")))
    check_in("a block never closed", "is never closed", " ".join(G.marker_problems("<!-- facts:size -->\n## Size\n")))
    for label, damaged in (("duplicate", two), ("unterminated", "<!-- facts:size -->\nx\n"),
                           ("stray", "<!-- /facts:size -->\n")):
        try:
            G.find_blocks(damaged)
            check(f"find_blocks refuses damaged markers ({label})", False, "no error")
        except G.BlockError as exc:
            check(f"find_blocks refuses damaged markers ({label}), and the text is a problem line", bool(str(exc)), "")
        try:
            G.replace_block(damaged, "size", "x")
            check(f"replace_block refuses damaged markers ({label})", False, "no error")
        except G.BlockError:
            check(f"replace_block refuses damaged markers ({label})", True)
    check_eq("blocks_found still answers with the sound blocks of a damaged file",
             sorted(G.blocks_found(two)), ["size"])
    try:
        G.replace_block("no blocks here\n", "size", "x")
        check("replace_block of an absent block is refused", False, "no error")
    except G.BlockError as exc:
        check_in("replace_block of an absent block names the door", "report_facts.py --task <T> --write", str(exc))


def set_pipeline(task: Path, **data) -> None:
    (task / "pipeline.json").write_text(json.dumps(dict({"ticket": "T-1"}, **data)), encoding="utf-8")


def block_contract(root: Path) -> None:
    """The report checks over a report that carries blocks, and over one that does not."""
    task = root / "qa-factory" / "artifacts" / "T-1"
    path = task / "test-report.md"

    def run(text: str, raw: bool = False) -> tuple:
        if raw:
            write_bytes(path, text)
        else:
            path.write_text(text, encoding="utf-8")
        found, notes = [], []
        V.check_test_report(path, found, notes)
        return found, notes

    set_pipeline(task, gates={"A": {"authorization_source": "go on, size S"},
                              "B": {"authorization_source": "create a draft MR, bugs into a file"}})
    found, notes = run(MARKED)
    check_eq("a report with every block, in order, is accepted", found, [])
    check_eq("and says nothing about legacy", notes, [])
    found, notes = run(REPORT)
    check_eq("edge (i): a report with no marker at all passes as today", found, [])
    check_eq("and says so, in the line the contract pins", notes, ["legacy report: facts not checked"])
    check_eq("the line is the grammar's", G.LEGACY_FACTS_LINE, "legacy report: facts not checked")
    check("an unmarked report is not `is_legacy_report` (that is the older section list)",
          not V.is_legacy_report(path) and V.report_is_unmarked(path))
    for section in G.REPORT_SECTIONS_WITH_BLOCKS:
        check_not_in(f"edge (i): the new section {section} is NOT required of a report with no marker",
                     "is missing", " ".join(e for e in found if section in e))
    found, notes = run("# T-1 — test report\n\n## Verdict\n\n`delivery_ready: yes`\n\n"
                       "## Check coverage\n\n| Ref | Kind | State |\n|---|---|---|\n| TS-1 | plan_row | `passed_green` |\n")
    check_eq("edge (i): the older legacy report says it too", notes, [G.LEGACY_FACTS_LINE])
    found, notes = run(REPORT + "\n```\n<!-- facts:size -->\n<!-- /facts:size -->\n```\n")
    check_eq("edge (ii): a report whose only markers stand inside a fence has no marker, and passes as legacy",
             (found, notes), ([], [G.LEGACY_FACTS_LINE]))

    # edge (ii): the fence rule through the report check
    fenced = MARKED.replace("<!-- /facts:proven -->", "```\n<!-- /facts:proven -->\n```")
    found, _ = run(fenced)
    check_eq("edge (ii): a block whose closing marker sits inside a fence is ONE problem", len(found), 1)
    check_in("and it names the block and the file", "test-report.md: block `proven` opened at line", found[0] if found else "")

    # edge (iii)
    found, _ = run(MARKED.replace("<!-- facts:size -->", "<!-- facts:size -->\n<!-- facts:size -->", 1))
    check("edge (iii): a duplicate marker is a problem", any("opens a second time" in e for e in found), str(found))
    found, _ = run(MARKED.replace("<!-- /facts:size -->", "<!-- /facts:sizing -->"))
    check("edge (iii): an unknown block name is a problem", any("names a block the report does not have" in e for e in found), str(found))
    without = MARKED.replace("<!-- facts:size -->\n## Size\n\nForecast: **S**. Fact: **S**. Difference: none.\n"
                             "<!-- /facts:size -->\n\n", "")
    check("(the fixture really lost its block)", "facts:size" not in without)
    found, _ = run(without)
    missing = [e for e in found if "code-owned block `size`" in e]
    check_eq("edge (iii): a block of REPORT_BLOCKS missing from a marked report is a problem", len(missing), 1)
    check_in("and it names the door", "report_facts.py --task T-1 --write", missing[0] if missing else "")
    check_in("and what was expected", "<!-- facts:size -->", missing[0] if missing else "")
    found, _ = run(MARKED.replace("<!-- facts:gate-a -->", "<!-- facts:gate-a-gone -->"))
    check("edge (iii): a block spelled wrong is an unknown name AND a missing block",
          any("gate-a-gone" in e for e in found) and any("code-owned block `gate-a`" in e for e in found), str(found))

    # the new sections are owed by a marked report
    nothing = MARKED.replace("<!-- facts:open-questions -->\n## Open questions — 0\n\nnone\n<!-- /facts:open-questions -->\n\n", "")
    found, _ = run(nothing)
    check("edge (vi): a marked report with no Open questions section is refused, naming the section",
          any("section '## Open questions' is missing" in e for e in found), str(found))
    found, _ = run(MARKED.replace("<!-- facts:gate-a -->\n## Decided at gate A\n\n```\ngo on, size S\n```\n<!-- /facts:gate-a -->\n\n", ""))
    check("F10: and one with no Decided at gate A section",
          any("section '## Decided at gate A' is missing" in e for e in found), str(found))
    moved = MARKED.replace("<!-- facts:open-questions -->\n## Open questions — 0\n\nnone\n<!-- /facts:open-questions -->\n\n", "")
    moved = moved.replace("<!-- facts:gate-a -->", "<!-- facts:open-questions -->\n## Open questions — 0\n\nnone\n"
                          "<!-- /facts:open-questions -->\n\n<!-- facts:gate-a -->")
    found, _ = run(moved)
    check("edge (vi): Open questions after Not proven is out of order",
          any("out of order" in e for e in found), str(found))
    # a marked report with the review-gaps block absent is refused, naming it (C1-5c; the same rule as manual-checks)
    gaps_block = MARKED[MARKED.index("<!-- facts:review-gaps -->"):MARKED.index("<!-- /facts:review-gaps -->\n") + len("<!-- /facts:review-gaps -->\n")]
    found, _ = run(MARKED.replace(gaps_block, ""))
    check("a marked report without the review-gaps block is refused, naming the block",
          any("the code-owned block `review-gaps` (## Review gaps) is missing" in e for e in found), str(found))
    # each block opens with its own heading
    found, _ = run(MARKED.replace("## Open questions — 0\n\nnone", "none"))
    check("a block that lost its heading line is refused, naming the block",
          any("block `open-questions` must open with its own heading line `## Open questions`" in e for e in found), str(found))
    found, _ = run(MARKED.replace("None found.\n<!-- /facts:bugs -->", "None found.\n\n## Size\n<!-- /facts:bugs -->"))
    check("a block that holds a second section is refused",
          any("block `bugs` must open with its own heading line" in e for e in found), str(found))
    found, _ = run(MARKED.replace("`delivery_ready: yes`\n<!-- /facts:verdict -->", "`delivery_ready: yes`\n\n## Proven\n<!-- /facts:verdict -->"))
    check("the verdict block holds no section heading",
          any("block `verdict` holds the section heading" in e for e in found), str(found))
    found, _ = run(MARKED.replace("`delivery_ready: yes`\n<!-- /facts:verdict -->",
                                  "`delivery_ready: yes`\n\n```\n## quoted in a fence\n```\n<!-- /facts:verdict -->"))
    check_eq("but a heading-looking line inside a fence in the verdict is no heading", found, [])

    # edge (v): F11 - the gate B section before the gate
    set_pipeline(task, gates={"A": {"authorization_source": "go on, size S"}})
    shape_13797 = ("## Decided at gate B\n\nNot yet decided. Gate A, in the person's words: \"go on, size S\"\n\n")
    with_b = MARKED.replace("## Factory defects", shape_13797 + "## Factory defects")
    found, notes = run(with_b)
    check("edge (v): a marked report with the gate B heading and no gate B words is refused",
          any("whose gate B has no recorded words" in e for e in found), str(found))
    check_in("and the refusal says what to do (FR-1)", "leave it out until gate B is decided",
             " ".join(e for e in found if "gate B has no recorded words" in e))
    found, notes = run(REPORT.replace("## Factory defects", shape_13797 + "## Factory defects"))
    check_eq("edge (v): the same section in a report with no marker is today's reading - passes, says legacy",
             (found, notes), ([], [G.LEGACY_FACTS_LINE]))
    set_pipeline(task, gates={"A": {"authorization_source": "go on, size S"},
                              "B": {"authorization_source": "create a draft MR"}})
    found, _ = run(with_b)
    check("edge (v): gate A's words under gate B's heading are refused even when gate B has words",
          any("quotes gate A's words" in e for e in found), str(found))
    set_pipeline(task, gates={"A": {"authorization_source": "go on, size S"},
                              "B": {"authorization_source": "create a draft MR"}})
    good_b = MARKED.replace("## Factory defects", "<!-- facts:gate-b -->\n## Decided at gate B (today)\n\n"
                            "- Delivery: \"create a draft MR\"\n<!-- /facts:gate-b -->\n\n## Factory defects")
    found, _ = run(good_b)
    check_eq("edge (v): gate B's own words under its heading are accepted", found, [])
    set_pipeline(task, gates={"A": {"authorization_source": "go on"}},
                 stage_overrides=[{"stage": "S9", "match": "x", "decision": "ship it"}])
    found, _ = run(good_b.replace("create a draft MR", "ship it"))
    check("edge (v): an S8/S9 override counts as gate B words", not any("no recorded words" in e for e in found), str(found))

    # edge (iv) through the report check: CRLF everywhere
    set_pipeline(task, gates={"A": {"authorization_source": "go on, size S"},
                              "B": {"authorization_source": "create a draft MR, bugs into a file"}},
                 stage_overrides=[{"stage": "S8", "match": "keep it local",
                                   "decision": "collect all bugs into a file and show them to me in chat"}])
    found, notes = run(MARKED.replace("\n", "\r\n"), raw=True)
    check_eq("edge (iv): a CRLF report with blocks checks clean", (found, notes), ([], []))
    # a block stays as it is when the rest of the file is rewritten by another writer
    text = path.read_bytes().decode("utf-8")
    check_eq("edge (iv): the CRLF file's blocks are found by the grammar", sorted(G.find_blocks(text)),
             sorted(set(G.REPORT_BLOCKS) - set(G.REPORT_BLOCKS_AFTER_GATE_B) - set(G.REPORT_BLOCKS_WHEN_PRESENT)))

    # edge (x): the delivery_ready line
    (task / "work").mkdir(exist_ok=True)
    (task / "work" / "ledger.json").write_text(json.dumps({"delivery_ready": False}), encoding="utf-8")
    # t-202 F3 said: in a MARKED report the verdict block owns the line, so equality with ledger.json was asked only of a
    # report with NO block. t-305 N8 (Q-N8-7) takes the exemption away: the head IS the ledger's word now
    # (`report_facts._verdict`, D9) and `rebuild_report` re-renders it at S8 and S9 before any validate, so a marked
    # report whose line differs from the ledger's word is stale, and says so. A line missing altogether is an error in both.
    same = "says delivery_ready"
    no_word = "no 'delivery_ready: yes|after_checks|no' line"
    third = {"delivery_ready": False, "delivery_verdict": "after_checks"}
    for label, line, ledger, want_marked, want_unmarked in (
            ("no with its first reason in words", "`delivery_ready: no — R-2 is not proven on this stand`", {"delivery_ready": False}, [], []),
            ("the bare no", "`delivery_ready: no`", {"delivery_ready": False}, [], []),
            ("the bare yes", "`delivery_ready: yes`", {"delivery_ready": True}, [], []),
            ("yes against a ledger that says no", "`delivery_ready: yes`", {"delivery_ready": False},
             [same + " yes"], [same + " yes"]),
            ("no against a ledger that says yes", "`delivery_ready: no — words`", {"delivery_ready": True},
             [same + " no"], [same + " no"]),
            ("the third word over a ledger that says it", "`delivery_ready: after_checks — 2 items are left with you`", third, [], []),
            ("the third word against a ledger that says no", "`delivery_ready: after_checks — 2 items are left with you`",
             {"delivery_ready": False}, [same + " after_checks"], [same + " after_checks"]),
            ("yes against a ledger that says the third word", "`delivery_ready: yes`", third, [same + " yes"], [same + " yes"]),
            ("no yes/no at all", "`delivery_ready: maybe — words`", {"delivery_ready": False}, [no_word], [no_word]),
            ("a word that only starts like the third", "`delivery_ready: after_checksX — words`", third, [no_word], [no_word]),
            ("a word that is not the third", "`delivery_ready: afterchecks — words`", third, [no_word], [no_word]),
            ("no colon, no dash", "`delivery_ready`", {"delivery_ready": False}, [no_word], [no_word])):
        (task / "work" / "ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
        for kind, report, want in (("marked", MARKED, want_marked), ("unmarked", REPORT, want_unmarked)):
            found, _ = run(report.replace("`delivery_ready: yes`", line))
            got = [e for e in found if "delivery_ready" in e and "above the first section" not in e]
            check(f"edge (x): delivery_ready {label} ({kind})",
                  len(got) == len(want) and all(w in g for w, g in zip(want, got)), str(got))
    # K-N8.12: the word is read case-insensitively, as a WHOLE word
    (task / "work" / "ledger.json").write_text(json.dumps(third), encoding="utf-8")
    found, _ = run(MARKED.replace("`delivery_ready: yes`", "`DELIVERY_READY: AFTER_CHECKS — 2 items`"))
    check_eq("K-N8.12: AFTER_CHECKS is read (IGNORECASE, as today)", [e for e in found if "delivery_ready" in e.lower()], [])
    for text, ok in (("after_checks", True), ("after_checksX", False), ("maybe", False), ("afterchecks", False),
                     ("yes", True), ("nothing", False), ("true", True)):
        check_eq(f"K-N8.12: the head regex reads `{text}` as {'a word' if ok else 'no word'}",
                 bool(V.READY_WORD_RE.search(f"delivery_ready: {text}")), ok)
    # the DoD's own case of t-202, turned around: the block says no, the ledger says ready - now a marked report is stale
    (task / "work" / "ledger.json").write_text(json.dumps({"delivery_ready": True}), encoding="utf-8")
    found, _ = run(MARKED.replace("`delivery_ready: yes`", "`delivery_ready: no — R-2 is not proven`"))
    check("Q-N8-7: a marked report whose block says no over a ledger that says ready has the equality error",
          any(same + " no" in e for e in found), str(found))
    found, _ = run(REPORT.replace("`delivery_ready: yes`", "`delivery_ready: no — R-2 is not proven`"))
    check("F3 control: the same line in a report with no block disagrees with the ledger too",
          any(same + " no" in e for e in found), str(found))
    found, _ = run(MARKED.replace("`delivery_ready: yes`", ""))
    check("F3: a marked report with the line missing altogether is still an error",
          any(no_word in e for e in found), str(found))
    check_in("and the error names the door a marked report has", "report_facts.py --task <TICKET> --write",
             " ".join(e for e in found if "no 'delivery_ready" in e))
    # K-N8.12: the regression block's lines (and the block of what gate B's answers added) are code's, exempt from the
    # R-n / case / `To check:` rule; a scribe item without an R-n is still refused
    found, _ = run(MARKED)
    check_eq("K-N8.12: the regression block's own line needs no R-n and no case", [e for e in found if "Left with you" in e], [])
    found, _ = run(MARKED.replace("(R-2, TC-001)", "(TC-001)"))
    check("K-N8.12: a scribe item without an R-n is still refused", any("names no R-n" in e for e in found), str(found))
    gate_b_block = ("<!-- facts:left-gate-b -->\n### Added after gate B (from your answers)\n\n"
                    "- **TC-001** (R-2) — you said: \"accept\" — Needed: a stand\n<!-- /facts:left-gate-b -->\n\n")
    found, _ = run(MARKED.replace("<!-- facts:regression -->", gate_b_block + "<!-- facts:regression -->"))
    check_eq("K-N8.12: the gate B block's lines are exempt too, and its h3 heading is a legal block heading",
             [e for e in found if "Left with you" in e or "left-gate-b" in e], [])
    (task / "work" / "ledger.json").unlink()

    # fork 3: code-owned text is not scribe prose - the 6144-byte cap excludes the bytes inside blocks
    filler = "x " * 4000
    found, _ = run(MARKED.replace("a wrong end date ships unseen.", "a wrong end date ships unseen. " + filler))
    check_eq("a marked report whose blocks alone exceed the prose cap passes", [e for e in found if "bytes outside" in e], [])
    found, _ = run(MARKED.replace("Nothing this run.", "Nothing this run. " + filler))
    check("the same text outside the blocks fails the cap", any("bytes outside the generated tables" in e for e in found), str(found))
    found, _ = run(REPORT.replace("a wrong end date ships unseen.", "") .replace("nobody waited out a billing period on this stand.",
                                  "nobody waited. " + filler))
    check("a report with no marker keeps counting everything", any("bytes outside" in e for e in found), str(found))

    # the closure of the old road refuses a report that carries blocks, and writes nothing
    import traceability as T
    set_pipeline(task, gates={"B": {"authorization_source": "create a draft MR"}})
    write_bytes(path, MARKED)
    before = path.read_bytes()
    outcome = T.close_gate_b(task)
    check_eq("close_gate_b leaves a report with blocks alone", (outcome["written"], path.read_bytes() == before), (False, True))
    check_in("and names the door", "report_facts.py --task T-1 --write", outcome["reason"])
    write_bytes(path, REPORT)
    check_eq("while a report with no marker is still closed by it", T.close_gate_b(task)["written"], True)


def answers(task: Path, lines: list) -> None:
    (task / "work").mkdir(parents=True, exist_ok=True)
    (task / "work" / "question-answers.jsonl").write_text(
        "\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")


def question_rows(ids: list) -> dict:
    return {"open_questions": [{"id": qid, "question": f"question {qid}", "severity": "major",
                                "owner_role": "qa-strategist", "readings": [{"reading": "x"}, {"reading": "y"}]}
                               for qid in ids]}


def suffix_contract(root: Path) -> None:
    """R-216a.1: the suffix goes on a line citing a question the person answered at gate A - and on
    no other."""
    import traceability as T
    task = root / "qa-factory" / "artifacts" / "T-1"
    (task / "work").mkdir(parents=True, exist_ok=True)
    (task / "work" / "requirements-readiness.json").write_text(
        json.dumps(question_rows(["Q1", "Q2", "Q3", "Q10", "Q11"])), encoding="utf-8")
    set_pipeline(task, gates={"A": {"authorization_source": "Q2 (Q-R15): fail open"}})
    answers(task, [
        {"kind": "question", "id": "Q1", "status": "answered", "words": "Q1 / Q-R14: reading a (R-14)",
         "where": "gate A", "by": "conductor", "at": "2026-09-30T10:00:00+00:00"},
        {"kind": "question", "id": "Q11", "status": "answered", "words": "Q11: b", "where": "gate B",
         "by": "conductor", "at": "2026-09-30T10:00:00+00:00"},
    ])
    qs = T._question_statuses(task)
    status = {q["id"]: q["status"] for q in qs}
    check_eq("the register: Q1 answered, Q2 only named, Q3 and Q10 open",
             (status["Q1"], status["Q2"], status["Q3"], status["Q10"]), ("answered", "named", "open", "open"))
    suffix = " — answered at gate A"
    check_eq("the suffix is the contract's words", T.ANSWERED_SUFFIX, suffix)
    check_eq("a basis citing an answered id gets the suffix, the role's words whole",
             T.mark_answered("Then rests on Q1 (owner decides)", qs), "Then rests on Q1 (owner decides)" + suffix)
    check_eq("the plan's spelling of the same question, by presence in the person's words",
             T.mark_answered("rests on open question Q-R14", qs), "rests on open question Q-R14" + suffix)
    check_eq("a requirement id on the same line of the person's words is not a question",
             T.mark_answered("R-14 is handed to a person", qs), "R-14 is handed to a person")
    check_eq("`named` gets no suffix (an id mentioned is not a question settled)",
             T.mark_answered("rests on Q2", qs), "rests on Q2")
    check_eq("nor the plan spelling of a named question", T.mark_answered("rests on Q-R15", qs), "rests on Q-R15")
    check_eq("`open` gets none", T.mark_answered("rests on Q3", qs), "rests on Q3")
    check_eq("Q1 is not in Q10 (the register's own matcher)", T.mark_answered("rests on Q10", qs), "rests on Q10")
    check_eq("and Q10 is not Q1 at the other end", T.mark_answered("rests on Q10 and Q1", qs), "rests on Q10 and Q1")
    check_eq("an id inside a path, a URL or a longer name is not a citation",
             [T.mark_answered(t, qs) for t in ("see Q1.md", "http://x/browse/Q1", "TC-Q1", "Q1-x")],
             ["see Q1.md", "http://x/browse/Q1", "TC-Q1", "Q1-x"])
    check_eq("two questions, one answered and one open: no suffix (it would say the open one is settled)",
             T.mark_answered("rests on Q1 and Q3", qs), "rests on Q1 and Q3")
    check_eq("an answer given at another place is not `answered at gate A`",
             T.mark_answered("rests on Q11", qs), "rests on Q11")
    check_eq("the suffix is added once", T.mark_answered(T.mark_answered("rests on Q1", qs), qs), "rests on Q1" + suffix)
    check_eq("no text, no suffix", T.mark_answered("", qs), "")
    check_eq("no register, no suffix", T.mark_answered("rests on Q1", []), "rests on Q1")
    check_eq("an unreadable register is an empty one, not a crash",
             T._question_statuses(root / "qa-factory" / "artifacts" / "NO-SUCH-STORY"), [])

    # through the table: a not-planned row whose basis cites the question
    (task / "work" / "requirements-register.md").write_text(
        "---\ntask: T-1\n---\n\n## Register\n\n| R | Requirement | source | derived_from | verifiable | ac_ref |\n"
        "|---|---|---|---|---|---|\n| R-14 | A delivery of a disallowed type gets an answer | ac | — | yes | AC-1 |\n",
        encoding="utf-8")
    (task / "test-plan.md").write_text(
        "---\ntask: T-1\n---\n\n## Plan\n\n| TS | what we verify | R | defect hypothesis | impact class | priority | observable | oracle | disposition + reason | fit | level | technique |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|\n\n## Gate A question packet\n\n"
        "1. R-14 rests on Q-R14: which answer does a disallowed type get?\n", encoding="utf-8")
    table = T.build(root / "qa-factory", task)
    row = next(r for r in table["rows"] if r["requirement"] == "R-14")
    check_eq("the table's row carries the suffix", row["basis"].endswith(suffix), True)
    check_in("and the role's words before it", "rests on Q-R14", row["basis"])
    check_in("the appendix prints the suffix", "answered at gate A", T.render(table))


TRACE_REGISTER = "---\ntask: T-1\n---\n\n## Register\n\n| R | Requirement | source | derived_from | verifiable | ac_ref |\n|---|---|---|---|---|---|\n" + "".join(
    f"| R-{n} | Requirement number {n} | ac | — | yes | AC-{n} |\n" for n in range(1, 13))


def plan_line(ts: str, reqs: str, cell: str) -> str:
    return (f"| {ts} | {ts} what we verify | {reqs} | contract @ x | degraded | P2 | diff:a.py:1 | "
            f"requirement:{reqs.split(',')[0].strip()} | {cell} | | | review |\n")


def case_file(root: Path, case_id: str, req: str, ts: str) -> None:
    folder = root / "qa-factory" / "artifacts" / "T-1" / "work" / "test-cases" / "a"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{case_id}.md").write_text(
        f"---\nid: {case_id}\ntitle: Case {case_id}\narea: a\ntask: T-1\ncovers: [{req}]\nplan_row: {ts}\n---\n"
        f"Requirements: {req}\nPlan row: {ts}\n\n## Then\n1. It happens.\n", encoding="utf-8")


def rd1_19_not_planned_reason() -> None:
    """RD1-19: the `## Not planned` section gives the reason (the text after the line's first ` - ` / ` — `), the question
    packet still comes first, and a requirement is matched by its WHOLE name (`R-1` is not `R-13`, `R-3` is not `BR-3`)."""
    import traceability as T
    root = temp_dir("qa-trace-notplanned-")
    try:
        task = root / "qa-factory" / "artifacts" / "T-1"
        (task / "work").mkdir(parents=True)
        (task / "work" / "requirements-register.md").write_text(TRACE_REGISTER, encoding="utf-8")
        plan = ("---\ntask: T-1\n---\n\n## Plan\n\n## Not planned\n\n"
                "- R-9 (the export) — Q2, no source states the export format\n"
                "- R-13 (a long id) — belongs to another story\n"
                "- BR-3 (a prefixed id) - not ours\n"
                "- R-4 (no reason given)\n"
                "- R-5 (asked) - nothing to decide\n"
                "- R-12 (a duplicate) — duplicates R-1, which already covers it\n"
                "- R-14, R-15 — one reason for both\n\n"
                "## Later\n\n- R-6 (outside the section) — not read\n\n"
                "## Gate A question packet\n\n1. R-5 / Q5: is this planned?\n")
        (task / "test-plan.md").write_text(plan, encoding="utf-8")
        story = T.Story(root / "qa-factory", task)
        none = "no plan row names this requirement and no reason is recorded"
        check_eq("RD1-19 a Not planned line gives its reason after the first em dash",
                 T.not_planned_basis(story, "R-9"), "Q2, no source states the export format")
        check_eq("RD1-19 `R-1` does not take the line of `R-13`", T.not_planned_basis(story, "R-1"), none)
        check_eq("t-593 F-3 a requirement named inside ANOTHER line's reason (`R-12 ... duplicates R-1`) is not found there",
                 T.not_planned_basis(story, "R-1"), none)
        check_eq("t-593 F-3 control: that line is R-12's own", T.not_planned_basis(story, "R-12"),
                 "duplicates R-1, which already covers it")
        check_eq("t-593 F-3 a list before the separator names both: `R-14, R-15`",
                 (T.not_planned_basis(story, "R-14"), T.not_planned_basis(story, "R-15")), ("one reason for both",) * 2)
        check_eq("RD1-19 `R-13` takes its own line",T.not_planned_basis(story, "R-13"), "belongs to another story")
        check_eq("RD1-19 `R-3` does not take `BR-3`", T.not_planned_basis(story, "R-3"), none)
        check_eq("RD1-19 a line with no reason: today's phrase", T.not_planned_basis(story, "R-4"), none)
        check_in("RD1-19 the question packet still comes first", "Q5", T.not_planned_basis(story, "R-5"))
        check_eq("RD1-19 a line after the section's end is not read", T.not_planned_basis(story, "R-6"), none)
        (task / "test-plan.md").write_text("", encoding="utf-8")
        check_eq("RD1-19 an empty plan: today's phrase", T.not_planned_basis(story, "R-9"), none)
    finally:
        cleanup(root)


def disposition_contract() -> None:
    """R-new-F32/F33: a case-less plan row speaks through its disposition; a planned manual case
    with nothing recorded waits for the person."""
    import traceability as T
    root = temp_dir("qa-trace-disposition-")
    try:
        task = root / "qa-factory" / "artifacts" / "T-1"
        (task / "work").mkdir(parents=True)
        (task / "work" / "requirements-register.md").write_text(TRACE_REGISTER, encoding="utf-8")
        plan = ("---\ntask: T-1\n---\n\nNot planned as rows: R-12 is nobody's.\n\n## Plan\n\n"
                "| TS | what we verify | R | defect hypothesis | impact class | priority | observable | oracle | disposition + reason | fit | level | technique |\n"
                "|---|---|---|---|---|---|---|---|---|---|---|---|\n"
                + plan_line("TS-1", "R-1", "`manual-human` — a person looks at the screen")
                + plan_line("TS-2", "R-2", "`manual-agent` — the agent checks it by hand")
                + plan_line("TS-3", "R-3", "`automate` — core path")
                + plan_line("TS-4", "R-4, R-5", "`skip` — app team's suite (CAND-2), reviewed at S5/S7")
                + plan_line("TS-5", "R-6", "`unverifiable` — operational goal with no observable; requirements question")
                + plan_line("TS-6", "R-7", "`automate` — planned, its case is not authored yet")
                + plan_line("TS-7", "R-8", "`skip`")
                + plan_line("TS-8", "R-9", "`skip` — reviewed, not duplicated")
                + plan_line("TS-9", "R-9", "`unverifiable` — no observable")
                + plan_line("TS-10", "R-10", "`skip` — set aside")
                + plan_line("TS-11", "R-10", "`automate` — planned")
                + plan_line("TS-12", "R-11", "`skip` — has a case of its own")
                + "\n## Gate A question packet\n\n1. R-7 / Q9: is this planned?\n")
        (task / "test-plan.md").write_text(plan, encoding="utf-8")
        for case_id, req, ts in (("TC-001", "R-1", "TS-1"), ("TC-002", "R-2", "TS-2"), ("TC-003", "R-3", "TS-3"),
                                 ("TC-012", "R-11", "TS-12")):
            case_file(root, case_id, req, ts)
        (task / "pipeline.json").write_text(json.dumps({"ticket": "T-1"}), encoding="utf-8")
        table = T.build(root / "qa-factory", task)
        rows = {}
        for row in table["rows"]:
            rows.setdefault(row["requirement"], row)

        check_eq("F33: a planned manual-human case with no evidence reads wait", rows["R-1"]["result"], "wait")
        check_eq("and its basis is the plan row's reason, not 'no result recorded'",
                 rows["R-1"]["basis"], "a person looks at the screen")
        check_eq("F33: it never reads not run", [r["result"] for r in table["rows"] if r["case"] == "TC-001"], ["wait"])
        check_eq("a manual-AGENT case with no evidence is still not run (the agent should have run it)",
                 rows["R-2"]["result"], "not run")
        check_eq("and so is an automated one", rows["R-3"]["result"], "not run")

        check_eq("F32: a case-less `skip` row reads deferred", rows["R-4"]["result"], "deferred")
        check_eq("with the row's reason", rows["R-4"]["basis"], "app team's suite (CAND-2), reviewed at S5/S7")
        check_eq("for every requirement the row names", rows["R-5"]["result"], "deferred")
        check_eq("F32: a case-less `unverifiable` row reads not planned", rows["R-6"]["result"], "not planned")
        check_eq("with the row's reason, whole (not cut at its first semicolon)",
                 rows["R-6"]["basis"], "operational goal with no observable; requirements question")
        check_eq("the row carries the plan row it was read from", (rows["R-4"]["plan_row"], rows["R-4"]["case"]), ("TS-4", ""))
        check_eq("a `skip` row with no reason says so (FR-41)", rows["R-8"]["basis"],
                 "plan row TS-7 is marked skip and records no reason")
        check_eq("a case-less row with another disposition keeps today's reading: not planned",
                 rows["R-7"]["result"], "not planned")
        check_eq("with today's basis, unchanged", rows["R-7"]["basis"], T.not_planned_basis(T.Story(root / "qa-factory", task), "R-7"))
        check_eq("no plan row names it: today's reading", rows["R-12"]["result"], "not planned")
        check("and no plan_row field", "plan_row" not in rows["R-12"])
        check_eq("two case-less rows that disagree: the one that claims no decision wins",
                 (rows["R-9"]["result"], rows["R-9"]["basis"]), ("not planned", "no observable"))
        check_eq("a skip row beside a planned row that has no case: today's reading (nothing is deferred)",
                 (rows["R-10"]["result"], "plan_row" in rows["R-10"]), ("not planned", False))
        # GW1-41 A2 (changed on purpose, t-525): a case that stayed on a `skip` row and never ran is set aside - the row's decision
        # speaks, not the case. The old pin read it "through the case, whatever its plan row says"; a case that RAN is still read
        # through the case (`set_aside_contract` below).
        check_eq("A2: a requirement whose only case is an unrun one on a `skip` row reads through the row: deferred, no case",
                 (rows["R-11"]["case"], rows["R-11"]["result"], rows["R-11"]["plan_row"]), ("", "deferred", "TS-12"))
        check_eq("--check is green: a plan row is the place of the requirement it speaks for (no 'trace.case is empty')",
                 T.check(root / "qa-factory", task, table), [])
        rendered = T.render(table)
        check("the appendix names the plan row where a case would stand",
              "| R-4 | Requirement number 4 | TS-4 |" in rendered, rendered)
        check_in("and the deferred word", "**deferred**", rendered)
        empty = dict(table, rows=[dict(table["rows"][0], case="", result="pass")])
        check_in("a row with no case and no plan row is still refused by --check", "trace.case is empty",
                 " ".join(T.check(root / "qa-factory", task, empty)))
    finally:
        cleanup(root)


def bug_md(bug_id: str, title: str, found_by: str, req: str, gate: str | None = None,
           confirmation: str | None = None, source_draft: str | None = None) -> str:
    lines = ["---", f"id: {bug_id}", f"title: {title}", "severity: major", f"found_by: {found_by}",
             f"violates: requirement:{req}"]
    for key, value in (("gate_b_decision_id", gate), ("confirmation", confirmation), ("source_draft", source_draft)):
        if value is not None:
            lines.append(f"{key}: {value}")
    return "\n".join(lines + ["---", "", "## Actual result", "broken", ""])


def bug_reader_contract() -> None:
    """R-206.3 last bullet: `traceability.bug_records` is `bug_records.story_bugs`, plus the fields a row joins on."""
    import bug_records as BR
    import traceability as T
    root = temp_dir("qa-trace-bugs-")
    try:
        task = root / "qa-factory" / "artifacts" / "T-1"
        (task / "work").mkdir(parents=True)
        (task / "work" / "requirements-register.md").write_text(TRACE_REGISTER, encoding="utf-8")
        (task / "test-plan.md").write_text("---\ntask: T-1\n---\n\n## Plan\n", encoding="utf-8")
        set_pipeline(task, gates={"B": {"id": "gateB-T-1", "authorization_source": "bugs into a file"}})
        project_bugs = root / "qa-factory" / "bugs"
        project_bugs.mkdir(parents=True)
        (task / "bugs").mkdir()
        (task / "bugs" / "BUG-1.md").write_text(
            bug_md("BUG-1", "The filter is not saved", "TC-001", "R-1"), encoding="utf-8")
        (project_bugs / "BUG-2.md").write_text(
            bug_md("BUG-2", "A second bug", "TC-002", "R-2", gate="gateB-T-1", confirmation="unconfirmed"), encoding="utf-8")
        (project_bugs / "BUG-3.md").write_text(
            bug_md("BUG-3", "Another story's bug", "TC-001", "R-1", gate="gateB-OTHER-1"), encoding="utf-8")
        (project_bugs / "BUG-4.md").write_text(bug_md("BUG-4", "Nobody's", "TC-001", "R-1"), encoding="utf-8")
        reader = BR.story_bugs(task, project_root=root)
        records = T.bug_records(root / "qa-factory", task)
        check_eq("the records are the reader's own, in its order", [r["id"] for r in records],
                 [r["id"] for r in reader["records"]])
        check_eq("the story's folder and the joined project file are counted, the other two are not",
                 [r["id"] for r in records], ["BUG-1", "BUG-2"])
        check_eq("a record keeps everything the reader says of it",
                 all(set(a) <= set(b) for a, b in zip(reader["records"], records)), True)
        by = {r["id"]: r for r in records}
        check_eq("what a row joins on, from the bug file's front matter: cases",
                 (by["BUG-1"]["cases"], by["BUG-2"]["cases"]), (["TC-001"], ["TC-002"]))
        check_eq("and requirements", (by["BUG-1"]["requirements"], by["BUG-2"]["requirements"]), (["R-1"], ["R-2"]))
        check_eq("confirmation is the contract's rule", (by["BUG-1"]["confirmation"], by["BUG-2"]["confirmation"]),
                 ("confirmed_by_person", "unconfirmed"))
        check_eq("a filed record is filed", (by["BUG-1"]["filed"], by["BUG-2"]["filed"]), (True, True))
        check_eq("Story joins a red row to the record by its case", T.Story(root / "qa-factory", task).bug_for("TC-001", "R-1").get("id"), "BUG-1")
        check_eq("and never to the other story's bug or an unattributed one",
                 T.Story(root / "qa-factory", task).bug_for("TC-009", "R-1"), {})
        table = T.build(root / "qa-factory", task)
        check_eq("edge (ix): outside_home rides in the table: BUG-1 lies only in the story's folder",
                 [b["id"] for b in table["bugs_outside_home"]], ["BUG-1"])
        check_eq("and it is still counted", [b["id"] for b in table["bugs"]], ["BUG-1", "BUG-2"])
        check_eq("the headline counts this story's bugs, not the project's", T.bug_headline(table["bugs"]),
                 "Product bugs — 1 confirmed · 1 unconfirmed.")
        check_eq("what the reader reports as outside is what the table carries",
                 table["bugs_outside_home"], reader["outside_home"])

        # a draft, and a draft a filed bug names
        drafts = task / "work" / "bug-drafts"
        drafts.mkdir()
        (drafts / "tc-009.json").write_text(json.dumps({"id": "BD-7", "title": "Draft only"}), encoding="utf-8")
        (drafts / "tc-001.json").write_text(json.dumps({"id": "BD-1", "title": "Same as BUG-1"}), encoding="utf-8")
        (task / "bugs" / "BUG-1.md").write_text(
            bug_md("BUG-1", "The filter is not saved", "TC-001", "R-1", source_draft="bug-drafts/tc-001.json"), encoding="utf-8")
        records = T.bug_records(root / "qa-factory", task)
        by = {r["id"]: r for r in records}
        check_eq("an unfiled draft is a record, as today", (by["BD-7"]["filed"], by["BD-7"]["cases"]), (False, ["TC-009"]))
        check("a draft and the filed bug that names it are ONE record", "BD-1" not in by and len(records) == 3, str(sorted(by)))

        # nothing there
        bare = temp_dir("qa-trace-nobugs-")
        try:
            lone = bare / "qa-factory" / "artifacts" / "T-9"
            lone.mkdir(parents=True)
            check_eq("edge (ix): no bug directory anywhere: empty, no exception",
                     T.bug_records(bare / "qa-factory", lone), [])
            check_eq("a story folder that does not exist: empty too",
                     T.bug_records(bare / "qa-factory", bare / "qa-factory" / "artifacts" / "NOPE"), [])
            check_eq("and the table says none", T.bug_headline([]), "Product bugs — none.")
        finally:
            cleanup(bare)
    finally:
        cleanup(root)


MANUAL_BLOCK = ("<!-- facts:manual-checks -->\n## Checked by hand — 0 of 0\n\n"
                "Nothing to show: no case was planned for a manual check.\n<!-- /facts:manual-checks -->\n\n")


def manual_block_write_contract() -> None:
    """t-250 B3, the TEMPORAL edge of the new block: a marked report written before it has none. `--check` and the
    contract name the missing block with the door; `--write` inserts it at its REPORT_BLOCKS position (right after
    `proven`) and nothing else in the file moves; a report that has the block gets it replaced in place."""
    import report_facts as RF
    root = story()
    try:
        task = root / "qa-factory" / "artifacts" / "T-1"
        path = task / "test-report.md"
        set_pipeline(task, gates={"A": {"authorization_source": "go on, size S"}})
        check("(the fixture really carries the block)", MANUAL_BLOCK in MARKED)
        write_bytes(path, MARKED.replace(MANUAL_BLOCK, ""))
        # world 1: absent
        problems = [p for p in RF.check(task) if "manual-checks" in p]
        check_eq("world 1 (absent): --check names the block, once", len(problems), 1)
        check_in("with the door", "report_facts.py --task T-1 --write", problems[0] if problems else "")
        found: list = []
        V.check_test_report(path, found)
        check("the report contract names it too", any("code-owned block `manual-checks`" in e and "--write" in e for e in found), str(found))
        done = RF.write(task)
        check("world 1: --write succeeds", done["ok"], str(done["lines"]))
        check_in("and says it added the block, not that it replaced one", "added block `manual-checks`", " ".join(done["lines"]))
        # the fixture's hand-written appendix lacks the R-1 row of the story (HF2-6b compares it with a fresh render): paste the
        # render now, before `fresh` is read, so every later byte comparison and "checks clean" below stands on the final state
        repaste_appendix(task)
        fresh = path.read_bytes().decode("utf-8")
        names = [m.group(1) for m in __import__("re").finditer(r"<!-- facts:([a-z-]+) -->", fresh)]
        check_eq("the inserted block stands at its REPORT_BLOCKS position: right after proven, before bugs",
                 names[names.index("proven") + 1: names.index("proven") + 3], ["manual-checks", "bugs"])
        check_eq("and every block stands in REPORT_BLOCKS order", names,
                 [b for b in G.REPORT_BLOCKS
                  if b not in G.REPORT_BLOCKS_AFTER_GATE_B and b not in G.REPORT_BLOCKS_WHEN_PRESENT])
        check_eq("and the report checks clean", RF.check(task), [])
        # every block is fresh now: strip ONLY the manual block and write again - nothing else may move
        stripped = RF._remove_block(fresh, "manual-checks")
        check("(the strip took one block out)", stripped != fresh and "facts:manual-checks" not in stripped)
        for label, eol in (("LF", "\n"), ("CRLF", "\r\n")):
            old = stripped.replace("\n", eol) if eol != "\n" else stripped
            write_bytes(path, old)
            done = RF.write(task)
            after = path.read_bytes().decode("utf-8")
            check(f"[{label}] world 1: written", done["ok"], str(done["lines"]))
            k = old.index("<!-- facts:bugs -->")   # the first part of the report that stands after the new block
            check(f"[{label}] the block was added", "<!-- facts:manual-checks -->" in after and len(after) > len(old))
            check_eq(f"[{label}] every old byte before the block's place is where it was", after[:k], old[:k])
            check(f"[{label}] and every old byte after it follows the block unchanged (nothing else in the file moved)",
                  after.endswith(old[k:]))
            check_eq(f"[{label}] the block sits between proven and bugs, no byte of the old report inside it",
                     after[k:len(after) - len(old[k:])].count("facts:proven") + after[k:len(after) - len(old[k:])].count("facts:bugs"), 0)
            check_eq(f"[{label}] no history copy: nothing was lost by adding a block", done["history"], "")
            check_eq(f"[{label}] and it checks clean", RF.check(task), [])
            again = RF.write(task)
            check_eq(f"[{label}] a second --write changes nothing",
                     (again["lines"], path.read_bytes().decode("utf-8")), (["test-report.md: every code-owned block already matches a fresh render"], after))
        # world 2: present, edited by hand
        write_bytes(path, fresh)
        edited = fresh.replace("Nothing to show:", "Checked by hand myself:")
        check("(the edit took)", edited != fresh)
        write_bytes(path, edited)
        check("world 2 (present, edited): --check names it as stale", any("block `manual-checks` differs" in p for p in RF.check(task)))
        done = RF.write(task)
        after = path.read_bytes().decode("utf-8")
        check_eq("world 2: --write puts the fresh text back in place - the report is the fresh one again", after, fresh)
        check_in("and says it replaced the block", "replaced block `manual-checks`", " ".join(done["lines"]))
        check("and the hand edit is kept in history", bool(done["history"]) and Path(done["history"]).read_bytes() == edited.encode("utf-8"))
        before_block, after_block = edited.split("<!-- facts:manual-checks -->")[0], edited.split("<!-- /facts:manual-checks -->")[1]
        check_eq("nothing outside the block moved", (after.split("<!-- facts:manual-checks -->")[0], after.split("<!-- /facts:manual-checks -->")[1]),
                 (before_block, after_block))
    finally:
        cleanup(root)


def main() -> None:
    root = story()
    try:
        task = root / "qa-factory" / "artifacts" / "T-1"
        check_eq("the report in the agreed form is accepted", errors_for(task, REPORT), [])

        moved = REPORT.replace("## Factory defects — nothing is wanted from you\n\nNothing this run.\n\n", "")
        moved = moved.replace("## Proven — 1 green test",
                              "## Factory defects — nothing is wanted from you\n\nNothing.\n\n## Proven — 1 green test")
        check_in("our own defects may not stand above what was proven",
                 "out of order", errors_for(task, moved))
        check_in("a missing section is named", "section '## Size' is missing",
                 errors_for(task, REPORT.replace("## Size", "## Sizing")))
        check_in("the verdict line belongs above the first section",
                 "line belong above the first section",
                 errors_for(task, REPORT.replace("`delivery_ready: yes`", "")))

        check_in("a requirement in no row of the appendix is refused",
                 "['R-2'] are in the register and in no row",
                 errors_for(task, REPORT.replace(
                     "| R-2 | access lasts the paid period | TC-001 | **wait** | no billing period on the stand |\n", "")))
        check_in("and so is a case of the plan",
                 "cases ['TC-001'] are in the plan",
                 errors_for(task, REPORT.replace("TC-001", "TC-009")))

        check_in("an item of Left with you with no requirement is refused",
                 "names no R-n and a case id",
                 errors_for(task, REPORT.replace("(R-2, TC-001)", "")))
        check_in("an item that says nothing to observe is refused", 'has no "To check:"',
                 errors_for(task, REPORT.replace("To check: the", "The")))
        check_in("an item with no way to do it is refused", 'neither "Needed:" nor "How:"',
                 errors_for(task, REPORT.replace("How: check by hand on preview.", "")))

        for spelling, needle in (("see `work/ledger.json`", "a path under work/"),
                                 ("case version cv_3e3e8c5e0bed", "content-addressed case version"),
                                 ("instance ti_4fa2889035ca", "selector-hash instance id"),
                                 ("<!-- factory-summary:start -->", "generated verification fragment")):
            check_in(f"the report may not carry {spelling[:24]!r}", needle,
                     errors_for(task, REPORT.replace("None found.", "None found. " + spelling)))
        check_in("a decision id with no words beside it is refused",
                 "with no decision text beside it",
                 errors_for(task, REPORT.replace("None found.", "None found. Per S5-160.")))
        check_eq("the same id WITH its words passes",
                 [e for e in errors_for(task, REPORT.replace(
                     "None found.", "None found. Decision S5-160: run it where the keys are."))
                  if "decision text" in e], [])

        with_gate = REPORT.replace("## Factory defects", GATE_B.strip() + "\n\n## Factory defects")
        check_eq("the gate-B section quoting the person verbatim is accepted",
                 errors_for(task, with_gate), [])
        check_in("a paraphrase of the person's words is refused",
                 "does not quote gates.B.authorization_source verbatim",
                 errors_for(task, with_gate.replace("create a draft MR, bugs into a file",
                                                    "the person asked for a draft MR")))
        check_in("and a gate-stage decision left out of it is refused",
                 'is not in "Decided at gate B"',
                 errors_for(task, with_gate.replace(
                     '- S8 · keep it local: "collect all bugs into a file and show them to me in chat"', "")))

        # The appendix is machine text: it grows with the plan and must not eat the prose cap.
        long_appendix = REPORT + "\n" + "\n".join(
            f"| R-1 | filler row {i} | TC-001 | **pass** | critic review |" for i in range(400))
        check_eq("the traceability appendix is outside the prose budget",
                 [e for e in errors_for(task, long_appendix) if "bytes outside" in e], [])
        long_prose = REPORT.replace("Nothing this run.", "Nothing this run. " + "x " * 4000)
        check_in("the hand-written part still has one", "bytes outside the generated tables",
                 errors_for(task, long_prose))

        # The closure writes the gate-B section itself, and takes out of "Left with you"
        # exactly the items the person's words answered — no more.
        import traceability as T
        errors_for(task, REPORT)
        pipeline = json.loads((task / "pipeline.json").read_text(encoding="utf-8"))
        pipeline["gates"]["B"]["authorization_source"] = (
            "create a draft MR; TC-001 access check: accept the risk, do not run it")
        (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        outcome = T.close_gate_b(task)
        closed = (task / "test-report.md").read_text(encoding="utf-8")
        check_eq("the closure answered the item that named the case", outcome["closed"], ["TC-001"])
        check_in("the person's words are in the report", "accept the risk, do not run it", closed)
        check("the answered item left \"Left with you\"",
              "Access after cancelling" not in closed.partition("## Not proven")[0], closed[:200])
        again = T.close_gate_b(task)
        check_eq("running it twice writes one section",
                 (task / "test-report.md").read_text(encoding="utf-8").count("## Decided at gate B"), 1)
        check_eq("and closes nothing new", again["closed"], [])
        check_eq("the rewritten report still passes the contract",
                 [e for e in errors_for(task, closed) if "Decided at gate B" not in e], [])

        # B-009: the Factory defects section is text a person reads (FR-6). It is checked on
        # write by its own function, never inside check_test_report: `traceability.py
        # --close-gate-b` calls that one and exits 1 on its errors.
        path = task / "test-report.md"

        def human_errors(text: str) -> list:
            path.write_text(text, encoding="utf-8")
            found: list = []
            V.check_report_human_text(path, found)
            return found

        defects = "## Factory defects — nothing is wanted from you\n\n"
        ledger_talk = REPORT.replace(defects + "Nothing this run.",
                                     defects + "Two windows stand `review_rejected` in the ledger (FB-27).")
        found = human_errors(ledger_talk)
        check("Factory defects with `review_rejected` is an error", any("review_rejected" in e for e in found),
              str(found))
        check("and a backlog id there is an error too", any("FB-27" in e for e in found), str(found))
        check("the error names the section and the way out (FR-1)",
              all(e.startswith("test-report.md, Factory defects: ") and "in words" in e for e in found), str(found))
        in_words = REPORT.replace(defects + "Nothing this run.",
                                  defects + "The ledger counted two windows as rejected; the critic could not "
                                            "check them, so nobody rejected any work.")
        check_eq("the same defect in words has no human-text error", human_errors(in_words), [])
        check_eq("the report as agreed has none", human_errors(REPORT), [])
        check_eq("a state in ANOTHER section is not this check's business",
                 human_errors(REPORT.replace("None found.", "None found. See `review_rejected`.")), [])
        check_eq("an empty Factory defects section has no human-text error",
                 human_errors(REPORT.replace("Nothing this run.\n", "")), [])
        check_eq("an absent Factory defects section has no human-text error",
                 human_errors(REPORT.replace(defects + "Nothing this run.\n\n", "")), [])
        check_in("a bare dispatch id there is an error", "S5-qa-automator-1",
                 " ".join(human_errors(REPORT.replace("Nothing this run.", "S5-qa-automator-1 halted."))))
        check_eq("check_test_report itself does not carry the new check (close-gate-b is unaffected)",
                 [e for e in errors_for(task, ledger_talk) if "Factory defects:" in e], [])
        check_in("the write branch does", "Factory defects:",
                 " ".join(V.collect_errors(task / "test-report.md", cfg={})))
        legacy_defects = ("# T-1 — test report\n\n## Verdict\n\n`delivery_ready: yes`\n\n"
                          "## Check coverage\n\n| Ref | Kind | State |\n|---|---|---|\n| TS-1 | plan_row | `passed_green` |\n\n"
                          "## Factory defects\n\nStood `review_rejected` (FB-27).\n")
        check_eq("a legacy report is skipped", human_errors(legacy_defects), [])
        # The real Factory defects section of TP1-13877 (a copy, cut to the section and its
        # heading): a field name and a state in code quotes - the scribe was promised a refusal.
        fixture = (Path(__file__).resolve().parent / "fixtures" / "report-13877-factory-defects"
                   / "test-report.md")
        real: list = []
        V.check_report_human_text(fixture, real)
        # Two rows of references/human-text.json refuse the same quoted text since 76789d2a (HF8-20, t-321): `technical_file_named`
        # (`run-report.json`, a record file named to a person) and `code_quotes` (the field and the state in code quotes). Each
        # refusal names its own why; the section is refused by both.
        check("the real 13877 Factory defects section is refused on write, naming the rule's why",
              len(real) == 2 and all(r.startswith("test-report.md, Factory defects: `run-report.json") for r in real)
              and sum("code quotes" in r for r in real) == 1
              and sum("the factory's own record, not a document a person reads" in r for r in real) == 1, str(real))
        path.write_text(closed, encoding="utf-8")  # the file the checks below read: a rebuilt report

        legacy = ("# T-1 — test report\n\n## Verdict\n\n`delivery_ready: yes`\n\n"
                  "## Run this yourself\n\n- none\n\n## Product problems\n\n- none\n\n"
                  "## Check coverage\n\n| Ref | Kind | State |\n|---|---|---|\n"
                  "| TS-1 | plan_row | `passed_green` |\n\n"
                  "## Readiness within what was verified\n\n| R | Status | Basis |\n|---|---|---|\n"
                  "| R-1 | verified | TC-001 |\n| R-2 | verified | TC-001 |\n\n"
                  "## Our tests and the factory\n\n- none\n")
        check("a report written before the rebuild keeps its own contract",
              V.is_legacy_report(task / "test-report.md") is False, "detection is per file")
        check_eq("and is validated against the sections it was written with",
                 errors_for(task, legacy), [])

        # B-211 (t-189): the contract of the code-owned blocks
        grammar_contract()
        block_contract(root)
        suffix_contract(root)
    finally:
        cleanup(root)
    manual_block_write_contract()
    rd1_19_not_planned_reason()
    disposition_contract()
    bug_reader_contract()
    finish("test report contract")


if __name__ == "__main__":
    main()
