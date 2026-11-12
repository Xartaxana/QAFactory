"""grammar.py: the closed lists and small parsers the factory's markdown/JSON artifacts
are built on. Covers the markdown-table reader (table_rows/section_present) the whole
form validator relies on, the front-matter scalar parsers (parse_inline_list,
parse_inline_dict_int), the RULE_CUTOFF date gate, and the oracle/defect-class/
contradiction-cell grammars that separate an accepted cell from a refused one.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import grammar as G  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, finish  # noqa: E402

# --- table_rows / section_present ---
LINES = """## Scenarios
| TS | R | What can go wrong |
|---|---|---|
| TS-1 | R-1 | smoke |
| TS-2 | R-2 | state @ x |

## Seam scenarios
| seam | row |
|---|---|
| a×b | TS-3 |
""".splitlines()

check("section_present finds a heading that exists", G.section_present(LINES, "## Scenarios"))
check("section_present is false for a heading that is not there", not G.section_present(LINES, "## Missing"))

rows = G.table_rows(LINES, "## Scenarios")
check_eq("table_rows skips the header and separator rows", len(rows), 2)
check_eq("table_rows splits cells without the enclosing pipes", rows[0], ["TS-1", "R-1", "smoke"])
seam_rows = G.table_rows(LINES, "## Seam scenarios")
# table_rows only recognizes a fixed set of ID-column header names (R/TS/H/#/ID) as a
# header to skip; "seam" is not one of them, so this header row counts as data — a real
# quirk of the parser worth knowing about, not something this test papers over.
check_eq("table_rows stops at the next '## ' heading (unrecognized header counted as a row)",
         len(seam_rows), 2)
check_eq("...and the recognized-header table above skipped its own header via the TS/R/etc list",
         len(rows), 2)
check_eq("table_rows returns [] for a heading that is not present", G.table_rows(LINES, "## Nope"), [])

# --- inline scalar parsers ---
check_eq("parse_inline_list reads a bracketed list", G.parse_inline_list("[R-1, R-2]"), ["R-1", "R-2"])
check_eq("parse_inline_list reads a bare comma list", G.parse_inline_list("R-1, R-2"), ["R-1", "R-2"])
check_eq("parse_inline_list of empty text is []", G.parse_inline_list(""), [])
check_eq("parse_inline_dict_int reads numeric values", G.parse_inline_dict_int("{story: 2, ac: 3}"), {"story": 2, "ac": 3})
check_eq("parse_inline_dict_int skips a non-numeric value", G.parse_inline_dict_int("{story: 2, bad: x}"), {"story": 2})

# --- RULE_CUTOFF date gate ---
check_eq("date_prefix reads the leading YYYY-MM-DD", G.date_prefix("2026-09-07T10:00:00Z"), "2026-09-07")
check_eq("date_prefix of unrecognized text is ''", G.date_prefix("not a date"), "")
check("after_cutoff is true on the cutoff date itself", G.after_cutoff("2026-09-07"))
check("after_cutoff is true after the cutoff", G.after_cutoff("2026-09-08T00:00:00Z"))
check("after_cutoff is false before the cutoff (old artifact, previous schema)", not G.after_cutoff("2026-09-06"))
check("after_cutoff is false when the value carries no date", not G.after_cutoff(""))

# --- the oracle grammar (WP4): a finding without one of these is an observation, not a bug ---
check("a requirement oracle matches", bool(G.ORACLE_RE.match("requirement:R-2")))
check("an invariant oracle matches", bool(G.ORACLE_RE.match("invariant:one-cancel-event")))
check("a bare 'looks wrong' is refused — no oracle prefix", not G.ORACLE_RE.match("looks wrong to me"))
check("an oracle prefix with nothing after the colon is refused", not G.ORACLE_RE.match("requirement:"))

# --- defect class cells (WP3): "<class> @ <where>" ---
m = G.DEFECT_CLASS_RE.match("state @ subscription.end_date")
check("a defect class cell parses its class name", bool(m) and m.group("cls") == "state")
check("a regression:BUG-n class is accepted", bool(G.DEFECT_CLASS_RE.match("regression:BUG-901 @ checkout")))
check("a defect class without an '@ where' is refused", not G.DEFECT_CLASS_RE.match("state"))

# --- contradiction matrix cells (WP2) ---
for good in ("ok:feature-doc.md#goal", "silent", "contradicts:\"team seats are released\"", "n/a:no bugs"):
    check(f"contradiction cell {good!r} is well-formed", bool(G.CONTRADICTION_CELL_RE.match(good)))
check("a bare 'ok' with no reference is refused (WP2: ok needs a positive control)",
      not G.CONTRADICTION_CELL_RE.match("ok"))
check("a bare 'contradicts' with no quote is refused", not G.CONTRADICTION_CELL_RE.match("contradicts"))

# --- bare decision ids in a report (a person asked for the sentence beside the id) ---
check("a bare decision id with nothing beside it is caught", bool(G.REPORT_BARE_DECISION_RE.search("decision S5-160 applies")))
check("a decision id followed by its own sentence is not flagged",
      not G.REPORT_BARE_DECISION_RE.search("S5-160: the stand carries one account, accept the risk"))

# --- defect_classes / impact_scale: config.json extends the seed lists, in code with a default ---
check("defect_classes() is a superset of the built-in seed", G.DEFECT_CLASSES <= G.defect_classes({}))
check("defect_classes() config extension is additive",
      "flaky-infra" in G.defect_classes({"defect_classes_extra": ["flaky-infra"]}))
scale = G.impact_scale({"impact_scale": {"money": {"priority": "P1", "severity": "major"}}})
check_eq("impact_scale() override replaces one class, not the whole table", scale["money"]["priority"], "P1")
check_eq("impact_scale() leaves un-overridden classes at their default", scale["access"], G.IMPACT_SCALE["access"])
check("impact_scale() ignores a malformed override (missing priority/severity)",
      G.impact_scale({"impact_scale": {"money": {"priority": "P1"}}})["money"] == G.IMPACT_SCALE["money"])
check_eq("impact_scale_problems() names the dropped override and why (OH3-3)",
         G.impact_scale_problems({"impact_scale": {"money": {"priority": "P1"}, "access": "x", "degraded": {"priority": "P2", "severity": "minor"}}}),
         {"money": "is a map without severity, not a {priority, severity} map",
          "access": 'is a string ("x"), not a {priority, severity} map'})
check_eq("impact_scale_problems() is {} for a valid map and for a whole value that is not a map",
         [G.impact_scale_problems(c) for c in ({"impact_scale": {"money": {"priority": "P1", "severity": "major"}}}, {"impact_scale": "x"}, {})],
         [{}, {}, {}])
check_eq("impact_scale_state() tells absent, empty, not a map and a map with classes apart",
         [G.impact_scale_state(c) for c in ({}, {"impact_scale": {}}, {"impact_scale": "x"}, {"impact_scale": 5}, {"impact_scale": None},
                                            {"impact_scale": {"money": 1}})],
         ["absent", "empty", "not a map", "not a map", "not a map", ""])

# --- split_cells / escape_cell (G2-10): the ONE reader of a table row and its inverse ---
check_eq("split_cells: an escaped bar stays in its cell, the others cut", G.split_cells("| a \\| b | c |"), ["a | b", "c"])
check_eq("split_cells: a plain row", G.split_cells("| a | b |"), ["a", "b"])
check_eq("split_cells: a cell ending in an escaped bar right before the closing bar keeps it (EXACTLY one bar is taken off)",
         G.split_cells("| a \\||"), ["a |"])
check_eq("split_cells: ... and with the closing bar after a space", G.split_cells("| a \\| |"), ["a |"])
check_eq("split_cells: a row with no closing bar whose last bar is escaped keeps it as text", G.split_cells("| a | b \\|"), ["a", "b |"])
check_eq("split_cells: no outer bars at all", G.split_cells("a | b"), ["a", "b"])
check_eq("split_cells: an empty line, `||` and `|` are one empty cell, as before",
         [G.split_cells(s) for s in ("", "||", "|", "   ")], [[""], [""], [""], [""]])
check_eq("split_cells: the separator row", G.split_cells("|---|:--:|"), ["---", ":--:"])
check_eq("split_cells: empty cells in the middle are kept", G.split_cells("| a | | c |"), ["a", "", "c"])
check_eq("split_cells: a bare bar in a cell is a border - the cell count GROWS, nothing is guessed (AR-28)",
         G.split_cells("| R-1 | a|b | story |"), ["R-1", "a", "b", "story"])
check_eq("split_cells: None reads as an empty line", G.split_cells(None), [""])
check_eq("split_cells max_cells: the LAST cell keeps the bare bars after it, an escaped one reads as a bar",
         (G.split_cells("| a | b | c | d |", 2), G.split_cells("| a \\| x | b \\| c | d |", 2)), (["a", "b | c | d"], ["a | x", "b | c | d"]))
check_eq("split_cells max_cells: a row with fewer cells, or None, reads as without it",
         (G.split_cells("| a | b |", 5), G.split_cells("| a | b |", None), G.split_cells("| a | b |", 2)), (["a", "b"], ["a", "b"], ["a", "b"]))
check_eq("escape_cell: a bar, every line break kind, None",
         [G.escape_cell("a|b"), G.escape_cell("a\r\nb"), G.escape_cell("a\rb\nc"), G.escape_cell(None), G.escape_cell(7)],
         ["a\\|b", "a b", "a b c", "", "7"])
for words in ("a | b", "x|", "|y", "|", "a \\| b", "tail\\", "p||q", "", "plain"):
    row = "| " + " | ".join(G.escape_cell(w) for w in (words, "next")) + " |"
    check_eq(f"split_cells reads back what escape_cell wrote: {words!r}", G.split_cells(row), [words, "next"])
check_eq("table_rows reads a `\\|` cell as one cell (a role's words may hold a bar)",
         G.table_rows(["## T", "| R | x |", "|---|---|", "| R-1 | a \\| b |"], "## T"), [["R-1", "a | b"]])

finish("test_grammar")
