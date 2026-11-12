"""RC1-14 part 2, node N2 - a rule that code already checks leaves the role's prose as ONE line.

For each moved rule (R1 quiet runs, R2 whole read, R5 digest shape, R7 defect hypothesis, R8 then_bindings):
  every `Code checks: ...` line of its source is at most 200 bytes (AR-20); the lines themselves are rows of design/role-rules.json;
  the refusal that carries the requirement holds its door (the guard's constant, or the guard run on a minimal event);
  R5: every role's common-rules slice keeps the fenced three-line digest shape (the plan critic's R5).

Runnable on its own: `python -B scripts/tests/test_rc1_14_rule_lines.py`.
"""
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import PLUGIN_ROOT, check, check_in, finish  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import guard_pre_tool as G  # noqa: E402
import role_digest as RD  # noqa: E402

REFS = PLUGIN_ROOT / "references"
LINE_CAP = 200


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def code_checks_segments(text: str) -> list:
    """Every `Code checks: ...` segment: from the marker to the end of its line (the line is the one line)."""
    return [m.group(0) for m in re.finditer(r"Code checks:[^\n]*", text)]


# the sources of the moved rules R1, R2, R5, R7, R8 (their `Code checks:` lines are rows of design/role-rules.json)
for source in ("common-rules.md", "automation-candidacy.md", "artifact-contract-automation.md"):
    segs = code_checks_segments(read(REFS / source))
    check(f"{source}: every `Code checks:` line is one line (<= {LINE_CAP} B)",
          all(len(s.encode("utf-8")) <= LINE_CAP for s in segs), str([len(s.encode("utf-8")) for s in segs]))

# --- the refusal carries the requirement and its door -----------------------------------------------------------------

check_in("R1: the runner refusal names the runner", "run_suite.py", G.RUNS_MSG)
check_in("R1: the runner refusal names --detail <test>", "--detail <test>", G.RUNS_MSG)
check_in("R1: the raw-log refusal names --detail", "--detail <test>", G.LOGS_MSG)

with tempfile.TemporaryDirectory() as tmp:
    big = Path(tmp) / "big.json"
    big.write_bytes(b"x" * (G.DEFAULT_BIG_READ_BYTES + 100))
    event = {"tool_name": "Read", "tool_input": {"file_path": str(big)}, "cwd": tmp}
    refusal = G._blocked(lambda ev, cfg: G.big_read_check(ev["tool_input"], cfg, ev), event, {})
    check("R2: a whole read over the limit is refused", bool(refusal), "no refusal")
    check_in("R2: the refusal says what is wrong", "whole is blocked", refusal or "")
    check_in("R2: the refusal names the way through (the range)", "`Read` with `offset`/`limit`", refusal or "")

errors_text = RD.refusal("qa-scout", ["the digest names no artifact path"])
check_in("R5: the exit-gate refusal prints the form", RD.FORM, errors_text)
check_in("R5: the exit-gate refusal names the item per row", "one row per", errors_text)
check_in("R5: the exit-gate refusal names what did not fit", "What does not fit", errors_text)

# the plan validator and the S5 precheck are large; their refusal text is pinned by the string that holds the door
validate_src = read(PLUGIN_ROOT / "scripts" / "validate_artifacts.py")
check_in("R7: the validator's refusal names the form", "needs `<class> @ <place>` ", validate_src)
check_in("R7: the validator's refusal names the closed list", "with a class from {sorted(classes)}", validate_src)
precheck_src = read(PLUGIN_ROOT / "scripts" / "s5_precheck.py")
check_in("R8: the precheck's refusal names the fragment to send", "add then_bindings[] to the fragment", precheck_src)

# --- R5: every role keeps the fenced three-line shape ------------------------------------------------------------------

SHAPE = ("```\n<role> <stage> <window or scope> · ok|concerns|halt|impossible\n<id> · <state> · <reason ≤ 80 chars>\n"
         "<task-relative path of the artifact>\n```")
roles = sorted(p.parent.name for p in (REFS / "slices").glob("*/common-rules.md"))
check("R5: twelve roles have a common-rules slice", len(roles) == 12, str(roles))
for role in roles:
    check(f"R5: {role}'s slice keeps the fenced digest shape",
          SHAPE in read(REFS / "slices" / role / "common-rules.md"))

finish("RC1-14 N2 rule lines")
