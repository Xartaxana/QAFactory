#!/usr/bin/env python3
"""FR-10: one packet shown to a person does not contradict itself.

The measured failure: gate B opened with "Bugs found — none, so there is nothing to file" and
three screens down the report carried "its bug proposal is unfiled". The role knew about the
debt; the code did not, because it counted bugs only from the drafts S7 leaves — and the other
road to a bug, a requirement the product does not deliver, leaves no draft at all.

P21.11 is the systematic pass: for every text assembled out of several sources, one source per
fact. What is held here:

  * the gate-B packet says "nothing to file" only when BOTH sources agree, and a discrepancy no
    draft speaks for is told as the factory's own gap rather than asked as a question (FR-3);
  * one fact, one reader: the roll-call table is parsed by `critic_rollcall` and by nobody else,
    and a delivery reason's owner is decided by `check_delivery.reason_owner` and by nobody else.
    A second parser is how the two halves of one packet start to disagree.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import gate_brief  # noqa: E402

TICKET = "QA-10"


def story(root: Path, unresolved: list, drafts: list) -> Path:
    task = root / TICKET
    (task / "work").mkdir(parents=True, exist_ok=True)
    (task / "pipeline.json").write_text(json.dumps({"ticket": TICKET}), encoding="utf-8")
    (task / "work" / "automation-manifest.json").write_text(
        json.dumps({"tests": [], "unresolved": unresolved}), encoding="utf-8")
    if drafts:
        (task / "work" / "bug-drafts").mkdir(parents=True, exist_ok=True)
        for number, draft in enumerate(drafts, start=1):
            (task / "work" / "bug-drafts" / f"BD-{number}.json").write_text(
                json.dumps(draft), encoding="utf-8")
    return task


def the_gate_b_packet_agrees_with_itself() -> None:
    root = temp_dir("qa-one-source-")
    try:
        # Nothing anywhere: "none" is the truth and the packet may say so.
        task = story(root, [], [])
        text = gate_brief.render_gate_b(TICKET, task)
        check_in("with no drafts and no discrepancy the packet says none", "Bugs found — none",
                 text)

        # A discrepancy with a requirement and no draft: the old packet said "nothing to file".
        task = story(root, [{"case": "TC-7", "reason": "contradicts_requirement",
                             "detail": "AC7: the filter cannot be configured from the UI"}], [])
        text = gate_brief.render_gate_b(TICKET, task)
        check_not_in("a discrepancy nobody drafted is never 'nothing to file'",
                     "there is nothing to file", text)
        check_in("the packet counts it", "1 discrepancy(ies) with a requirement", text)
        check_in("names the case", "TC-7", text)
        check_in("quotes what it says", "cannot be configured from the UI", text)
        check_in("and calls it ours, asking nothing (FR-3)", "the factory's own gap", text)
        rows = gate_brief.undrafted_discrepancies(task)
        check_eq("the fact comes from one function", [row["case"] for row in rows], ["TC-7"])

        # The same case WITH a draft: it is the draft the person answers, counted once.
        task = story(root, [{"case": "TC-7", "reason": "contradicts_requirement", "detail": "AC7"}],
                     [{"id": "BD-1", "case": "TC-7", "title": "AC7 is not delivered",
                       "impact": "blocked-flow"}])
        text = gate_brief.render_gate_b(TICKET, task)
        check_eq("a discrepancy a draft speaks for is not counted again",
                 gate_brief.undrafted_discrepancies(task), [])
        check_in("and the draft is what the person answers", "Answer by number", text)
        check_not_in("with no second list beside it", "no draft speaks for", text)

        # A draft for another case leaves the discrepancy standing, and both are shown.
        task = story(root, [{"case": "TC-7", "reason": "impossible",
                             "detail": "no black-box channel reads the cache"}],
                     [{"id": "BD-1", "case": "TC-3", "title": "totals drift", "impact": "degraded"}])
        text = gate_brief.render_gate_b(TICKET, task)
        check_in("the drafts are answered", "Answer by number", text)
        check_in("and the undrafted discrepancy is named beside them", "no draft speaks for", text)
        check_in("by case and reason", "TC-7 (`impossible`)", text)
    finally:
        cleanup(root)


def one_fact_one_reader() -> None:
    """A second parser of the same artifact is how two sections of one packet disagree.

    `gate_brief` used to parse the roll-call table with a regex of its own — including the phrase
    list over the status cell — while `critic_rollcall` owned that table. Both are now one reader,
    and this keeps it that way."""
    scripts = {path.name: path.read_text(encoding="utf-8", errors="replace")
               for path in sorted(harness.SCRIPTS.glob("*.py"))}
    # The roll-call table: its heading and its column belong to critic_rollcall.
    readers = [name for name, text in scripts.items()
               if name != "critic_rollcall.py" and re.search(r'md_table\([^)]*Roll-call', text)]
    check_eq("only critic_rollcall parses the roll-call table", readers, [])
    for name in ("gate_brief.py", "gate_preflight.py"):
        check_in(f"{name} asks critic_rollcall instead", "critic_rollcall", scripts[name])
        check_in(f"and reads the third answer it gives ({name})", "unstated", scripts[name])
    # The owner of a delivery reason: one function decides it, everyone else reads the record.
    # Reading the closed list to validate a value is not deriving an owner; a second map from a
    # reason to an owner is. `check_delivery` owns that map, and the table behind it is data.
    owners = [name for name, text in scripts.items()
              if name != "check_delivery.py"
              and (re.search(r"def reason_owner\b", text) or re.search(r"OWNER_BY_\w+\s*=", text))]
    check_eq("nobody else maps a reason to an owner", owners, [])
    for name in ("ledger.py", "delivery_summary.py"):
        check_in(f"{name} reads the records rather than the texts", "reason_records", scripts[name])


def main() -> None:
    the_gate_b_packet_agrees_with_itself()
    one_fact_one_reader()
    finish("test_one_source_per_fact")


if __name__ == "__main__":
    main()
