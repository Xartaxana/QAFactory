#!/usr/bin/env python3
"""The form of a role charter (spec t-1765 X1-1, node B-A): six headings in a fixed order, a `kind` marker directly above each,
at most 150 lines, 3 to 6 DoD items, a gen:digest block, the `tried` table named as the witness.

Each test names the ONE mutation that kills it (builder-rules 7a):
  test_shipped_form_is_clean, test_markers_sit_above_headings   -> drop a heading from CHARTER_SECTIONS
  test_line_limit_at_and_beyond                                   -> `>` to `>=` in the CHARTER_MAX_LINES comparison
  test_dod_items_at_and_beyond                                    -> DOD_ITEMS = (3, 7)
  test_marker_kind_must_match, test_marker_must_be_adjacent       -> `sec["kind"] != want` always false
  test_extra_and_reordered_sections                               -> delete the order comparison in charter_errors
  test_old_role_file_is_not_a_charter                             -> is_charter returns True for any file
  test_digest_block_and_tried_line                                -> delete the gen:digest / `tried` check
  test_form_agrees_with_role_load                                 -> `kind` placed one line higher than the heading
  test_kind_before_roles_order                                    -> swap the two marker lines in ROLES_AFTER_KIND
  test_a19_*                                                      -> `charter.is_charter(text)` branch always taken
Run: python -B -m pytest scripts/tests/test_charter_form.py -q
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import audit_factory  # noqa: E402
import charter  # noqa: E402
import contract_slices  # noqa: E402
import role_load  # noqa: E402

PLUGIN = Path(harness.SCRIPTS).parent


def charter_text(items: int = 4, pad: int = 0, craft_tools: bool = False, gap: bool = False, digest: bool = True,
                 intro: str = "The acceptor reads each item against its witness; what you tried is the `tried` table of your handoff form.",
                 order: tuple = None, extra: bool = False) -> str:
    """A well-formed synthetic charter; the switches break exactly one thing."""
    names = order or [n for n, _ in charter.CHARTER_SECTIONS]
    kinds = dict(charter.CHARTER_SECTIONS)
    kinds["Tools"] = "craft" if craft_tools else "process"
    out = ["---", "name: qa-scout", "description: A synthetic charter. Dispatched by qa-story at S1.", "tools: Read, Write",
           "disallowedTools: Agent, Task", "---", "", "# qa-scout", "", "You find everything.", ""]
    for name in names:
        out.append(f"<!-- kind: {kinds[name]} -->")
        if gap and name == "Tools":
            out.append("")
        out.append(f"## {name}")
        out.append("")
        if name == "Good outcome":
            out.append(intro)
            out.append("")
            out += [f"{i}. **Lead {i}.** Text of the item. Witness: `work/x.json`." for i in range(1, items + 1)]
        elif name == "Tools":
            out.append("You may call any of these.")
            if digest:
                out += ["<!-- gen:digest contract_slices.py -->", "- Digest: the common form.", "<!-- /gen -->"]
        else:
            out.append("- A line of text.")
        out.append("")
    if extra:
        out += ["<!-- kind: process -->", "## Notes", "", "- extra", ""]
    out += [""] * pad
    return "\n".join(out)


def test_shipped_form_is_clean():
    assert charter.charter_errors(charter_text()) == []
    assert [n for n, _ in charter.CHARTER_SECTIONS] == ["Outcome", "Good outcome", "Where bugs hide at this stage",
                                                        "Techniques", "Tools", "When to ask"]
    assert [s["heading"] for s in charter.sections(charter_text())] == [n for n, _ in charter.CHARTER_SECTIONS]


def test_markers_sit_above_headings():
    found = charter.sections(charter_text())
    assert [(s["heading"], s["kind"]) for s in found] == list(charter.CHARTER_SECTIONS)
    assert charter.sections(charter_text().replace("\n", "\r\n")) == found       # CRLF reads as LF


def test_line_limit_at_and_beyond():
    base = len(charter_text().split("\n"))
    body = charter_text().rstrip("\n").split("\n")
    pad150 = "\n".join(body + ["- x"] * (150 - len(body)))
    pad151 = "\n".join(body + ["- x"] * (151 - len(body)))
    assert base < 150
    assert charter.charter_errors(pad150) == []
    assert any("151 lines, at most 150" in e for e in charter.charter_errors(pad151))


@pytest.mark.parametrize("items,ok", [(2, False), (3, True), (6, True), (7, False)])
def test_dod_items_at_and_beyond(items, ok):
    errors = charter.charter_errors(charter_text(items=items))
    assert (errors == []) is ok
    if not ok:
        assert any(f"has {items} numbered items, expected 3 to 6" in e for e in errors)


def test_marker_kind_must_match():
    errors = charter.charter_errors(charter_text(craft_tools=True))
    assert any("Tools` is process, its marker says craft" in e for e in errors)


def test_marker_kind_reads_only_the_two_literal_kinds():
    # KIND_MARKER is generic (any kind value); only craft and process are kinds of a charter.
    assert charter._marker_kind("<!-- kind: craft -->") == "craft"
    assert charter._marker_kind("<!-- kind: process -->") == "process"
    assert charter._marker_kind("<!-- kind: other -->") is None


def test_marker_must_be_adjacent():
    errors = charter.charter_errors(charter_text(gap=True))
    assert any("directly above its heading" in e and "Tools" in e for e in errors)
    assert any("Tools" in m or "line" in m for m in charter.stray_markers(charter_text(gap=True)))     # reported, too


def test_extra_and_reordered_sections():
    assert any("`## Notes` is not one of the six" in e for e in charter.charter_errors(charter_text(extra=True)))
    names = [n for n, _ in charter.CHARTER_SECTIONS]
    swapped = tuple([names[1], names[0]] + names[2:])
    errors = charter.charter_errors(charter_text(order=swapped))
    assert any("out of order; expected: " + ", ".join(names) in e for e in errors)
    missing = tuple(n for n in names if n != "Techniques")
    assert any("no `## Techniques` section" in e for e in charter.charter_errors(charter_text(order=missing)))


def test_old_role_file_is_not_a_charter():
    # the negative control of the branch: a role file of the old form is a shipped charter with its kind markers taken off (X7-3: the
    # runner was the old-form file here; it is a charter now, so the control is built from one)
    old_form = re.sub(r"(?m)^<!-- kind: (craft|process) -->\n", "", (PLUGIN / "agents" / "qa-runner.md").read_text(encoding="utf-8"))
    assert charter.is_charter((PLUGIN / "agents" / "qa-runner.md").read_text(encoding="utf-8")) is True
    assert charter.is_charter(old_form) is False
    assert charter.is_charter(charter_text()) is True
    fenced = "```\n<!-- kind: craft -->\n```\n## Heading\n"
    assert charter.is_charter(fenced) is False               # a marker inside a fence is not a marker


def test_digest_block_and_tried_line():
    assert any("gen:digest" in e for e in charter.charter_errors(charter_text(digest=False)))
    errors = charter.charter_errors(charter_text(intro="The acceptor reads each item."))
    assert any("`tried`" in e for e in errors)


def test_form_agrees_with_role_load():
    text = charter_text()
    craft, ignored = role_load.craft_split(text)
    assert ignored == 0 and craft > 0                         # every marker counts, craft is measured by role_load alone
    assert charter.stray_markers(text) == []
    assert role_load.KIND_MARKER is charter.KIND_MARKER      # one craft regexp
    # a marker followed by text is reported, not an error
    odd = "<!-- kind: craft -->\nsome text\n"
    assert charter.stray_markers(odd) and role_load.craft_split(odd)[1] == 1
    assert charter.charter_errors(odd)                       # still not a charter-shaped file


ROLES_AFTER_KIND = "<!-- kind: craft -->\n<!-- roles: qa-scout -->\n## Alpha\nalpha text\n"
KIND_AFTER_ROLES = "<!-- roles: qa-scout -->\n<!-- kind: craft -->\n## Alpha\nalpha text\n"


def _roles_of(text: str, heading: str) -> list:
    """The roles contract_slices.parse gives the section `## <heading>` of a two-section file whose first section is for qa-tester."""
    doc = "<!-- roles: qa-tester -->\n## Zero\nzero text\n\n" + text
    _lead, found = contract_slices.parse(doc)
    for sec in found:
        if heading in sec.heading:
            return list(sec.roles)
    return ["<no such section>"]


def test_kind_before_roles_order():
    """The positional invariant of the marker-order rule (Lead decision, spec t-1765 X1): BOTH orders are legal and give the same
    roles. `roles` above `kind` keeps its roles (contract_slices.parse skips a `kind` line while a `roles` marker is pending, so
    the marker still heads the heading below); `kind` above `roles` keeps them too. What stays refused is a `roles` marker that
    heads nothing: it is dropped and the section goes to the previous roles (the negative control below)."""
    assert _roles_of(ROLES_AFTER_KIND, "Alpha") == ["qa-scout"]
    assert _roles_of(KIND_AFTER_ROLES, "Alpha") == ["qa-scout"]
    assert _roles_of(ROLES_AFTER_KIND, "Alpha") == _roles_of(KIND_AFTER_ROLES, "Alpha")
    orphan = "<!-- roles: qa-scout -->\nsome text under no heading\n\n## Alpha\nalpha text\n"
    assert _roles_of(orphan, "Alpha") != ["qa-scout"]            # negative control: a marker that heads nothing claims nothing
    assert role_load.craft_split(ROLES_AFTER_KIND) == (len(ROLES_AFTER_KIND.encode()), 0)


def _a19_findings(tmp_path, role_text: str) -> list:
    """A19 run over a plugin copy of one role file; the findings it raised (the real stages table is read from references/)."""
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "qa-scout.md").write_text(role_text, encoding="utf-8")
    saved, held = audit_factory.PLUGIN_ROOT, list(audit_factory.FINDINGS)
    audit_factory.PLUGIN_ROOT = tmp_path
    try:
        audit_factory.FINDINGS.clear()
        audit_factory.a19_agents_contract()
        return [f for f in audit_factory.FINDINGS if f.startswith("[A19 agents contract]") and "qa-scout.md" in f]
    finally:
        audit_factory.PLUGIN_ROOT = saved
        audit_factory.FINDINGS[:] = held


def test_a19_recognises_a_charter(tmp_path, capsys):
    text = charter_text().replace("Dispatched by qa-story at S1.", "Dispatched by qa-story at S1.")
    assert _a19_findings(tmp_path, text) == []


def test_a19_refuses_a_malformed_charter_and_an_old_file(tmp_path, capsys):
    broken = _a19_findings(tmp_path, charter_text(items=2))
    assert any("numbered items" in f for f in broken)
    old = tmp_path / "old"
    old.mkdir()
    refused = _a19_findings(old, charter_text().split("<!-- kind: process -->")[0].replace("tools: Read, Write\n", "tools: Read\n")
                            + "# qa-scout\n\nNo sections here.\n")
    assert any("missing section(s)" in f for f in refused)       # not a charter: judged by the old list, still refused


if __name__ == "__main__": raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
