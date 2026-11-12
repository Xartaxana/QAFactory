"""GW1-11: gate A names the two documents the person approves, not four.

The owner's variant (a), 22.10.2026: approved are `understanding.md` and `test-plan.md`; the cases are part of the plan, so
`case-appendix.md` and `requirements-register.md` are working files; the list has ONE carrier (`gate_brief.GATE_A_DOCUMENTS`)
and code builds the first line of the message.
Keys: K1 the first line names exactly the two, K2 the carrier is the only list, K3 the paths list shows only the two even when
the working files are on disk, K4 an absent `test-plan.md` keeps the first line and drops only the path, K5 the first line
is built from the carrier (negative control: a changed carrier changes the line).
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))

import gate_brief  # noqa: E402

TWO = ["understanding.md", "test-plan.md"]


def approval_line(text: str) -> str:
    return next(line for line in text.splitlines() if line.startswith("**Approve:"))


head = gate_brief._head_lines({"task": "T-1"})
line = approval_line("\n".join(head))
check_eq("K1 the approval line follows the title", head[0:3:2], ["# Gate A — T-1", line])
named = re.findall(r"`([^`]+\.md)`", line)
check_eq("K1 the first line of the gate A message names exactly the two documents", named, TWO)
check_not_in("K1 no appendix in the line", "case-appendix", line)
check_not_in("K1 no register in the line", "requirements-register", line)
check_in("K1 the brief is a summary (no file name: the driver writes none, FR-37)", "This brief is a summary of them", line)
check_not_in("K1 no brief file path in the line", "gate-a-brief", line)
check_eq("K2 the carrier holds the two", [name for _, name in gate_brief.GATE_A_DOCUMENTS], TWO)

base = temp_dir("qa-gw111-")
try:
    root = base / "artifacts" / "T-1"
    (root / "work").mkdir(parents=True)
    for name in ("understanding.md", "test-plan.md"):
        (root / name).write_text("x\n", encoding="utf-8")
    for name in ("case-appendix.md", "requirements-register.md"):
        (root / "work" / name).write_text("x\n", encoding="utf-8")
    shown = gate_brief.documents(root)
    check_eq("K3 only the two are listed though the working files are on disk", sorted(shown), ["plan", "understanding"])
    check_eq("K3 the appendix and the register are not in the paths", [p for p in shown.values() if "appendix" in p or "register" in p], [])
    (root / "test-plan.md").unlink()
    check_eq("K4 an absent test-plan.md drops its path only", sorted(gate_brief.documents(root)), ["understanding"])
    check_eq("K4 and the first line still names both", re.findall(r"`([^`]+\.md)`", gate_brief.gate_a_approval_line()), TWO)
finally:
    cleanup(base)

saved = gate_brief.GATE_A_DOCUMENTS
try:
    gate_brief.GATE_A_DOCUMENTS = saved + (("extra", "extra.md"),)
    check_in("K5 negative control: the line follows the carrier", "extra.md", gate_brief.gate_a_approval_line())
finally:
    gate_brief.GATE_A_DOCUMENTS = saved

PKG = SCRIPTS.parent
s4 = (PKG / "skills" / "qa-story" / "phases" / "s4.md").read_text(encoding="utf-8")
template = (PKG / "references" / "templates" / "understanding.md").read_text(encoding="utf-8")
for _, name in gate_brief.GATE_A_DOCUMENTS:
    check_in(f"K6 phases/s4.md names {name} (a literal beside the carrier)", name, s4)
check_in("K6 the understanding.md template names the other document", "test-plan.md", template)
check_in("K6 ... and the carrier", "GATE_A_DOCUMENTS", template)
check_not_in("K6 phases/s4.md names no brief file", "gate-a-brief.md", s4)

finish("test_gate_a_two_documents")
