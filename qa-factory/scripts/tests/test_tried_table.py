"""handoff_check.tried_errors - the `tried` table of the four S1-S4 handoff forms (spec t-1765 X1-7, decision B3).

The check sees only that a table is there: a row with a filled field, or a `tried_note` saying why not. Whether a technique
fits or an observation convinces is the stage critic's judgment, never read here.

Runnable on its own: `python -B scripts/tests/test_tried_table.py`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import PLUGIN_ROOT, check, check_eq, finish  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import handoff as H  # noqa: E402
import handoff_check as HC  # noqa: E402

S2 = "s2-tester-to-strategist"
FOUR = ("s1-scout-to-tester", "s2-tester-to-strategist", "s3-strategist-to-designer", "s4-designer-to-case-critic")
SIX = ("s5-automator-to-critic", "s6-runner-to-analyst", "s7-analyst-to-scribe", "s8-scribe-to-gate-b",
       "s8-bug-reporter-to-scribe", "s9-retro-to-project")
EXCLUDED = ("s5-automator-plan-to-critic", "s5-automator-to-runner", "s7-analyst-to-automator", "s7-automator-to-analyst")
ROW = ("tried:\n  - requirement: R-1\n    technique: boundary values\n"
       "    observation: the limit is not refused\n    evidence: work/requirements-register.md#R-1\n")
STUB = ("tried:\n  - requirement: <R-n, a source id or an area>\n    technique: <the technique by its name in your charter>\n"
        "    observation: <what you saw, in one line>\n    evidence: <the path (and anchor) where it shows>\n")
BLOCKED = "blocked:\n  field: x\n  problem: y\n  tried:\n    - ran the check, it refused\n"


def errors(text: str, contract: str = S2) -> list:
    return HC.tried_errors(H.parse(text), contract)


def test_cases() -> None:
    check_eq("1: one filled row, no note -> no problem", errors(ROW), [])
    check_eq("2: an empty table with a reason -> no problem",
             errors('tried: []\ntried_note: "grounding window, no plan rows yet"\n'), [])
    bad = errors("tried: []\ntried_note: -\n")
    check("3: an empty table with a dash is one problem on `tried`", len(bad) == 1 and bad[0].path == "tried", str(bad))
    stub = errors(STUB + "tried_note: <why the table is empty, or a dash when it has rows>\n")
    check("4: a placeholder row is no row (AT: a stub is not a row)", len(stub) == 1 and stub[0].path == "tried", str(stub))
    for contract in EXCLUDED:
        check_eq(f"5: {contract} is outside TRIED_CONTRACTS and is never refused", errors("tried: []\ntried_note: -\n", contract), [])
    for contract in SIX:
        empty = errors("tried: []\ntried_note: -\n", contract)
        check(f"5b: {contract}: an empty table with a dash is one problem on `tried`, naming the role's meaning",
              len(empty) == 1 and empty[0].path == "tried" and HC.TRIED_MEANING[contract] in empty[0].text, str(empty))
        check_eq(f"5c: {contract}: an absent section and note are refused", len(errors("header:\n  verdict: ok\n", contract)), 1)
        check_eq(f"5d: {contract}: `tried_note` with a reason is the informed pass",
                 errors('tried: []\ntried_note: "nothing to try: no red test in this window"\n', contract), [])
        check_eq(f"5e: {contract}: a filled row passes", errors(ROW, contract), [])
    blocked = errors(BLOCKED + "tried: []\ntried_note: -\n")
    check("6: `blocked.tried` is another field and is not read", len(blocked) == 1, str(blocked))
    check_eq("6b: and the other way, a filled `tried` beside an empty `blocked.tried` passes", errors(ROW + BLOCKED), [])
    check_eq("6c: an absent table and an absent note are refused for the four, not passed",
             len(errors("header:\n  role: qa-scout\n", "s1-scout-to-tester")), 1)


def test_shipped_forms() -> None:
    check_eq("7: TRIED_CONTRACTS is the explicit tuple: the four S1-S4 forms and the six S5-S9 forms (X7-7)",
             HC.TRIED_CONTRACTS, FOUR + SIX)
    for contract in HC.TRIED_CONTRACTS:
        text = (PLUGIN_ROOT / "handoffs" / f"{contract}.yaml").read_text(encoding="utf-8")
        check(f"7: {contract} carries `tried:` and `tried_note:`", "\ntried:\n" in text and "\ntried_note:" in text)
        check(f"7: {contract} puts the table before `unresolved:`", text.index("\ntried:\n") < text.index("\nunresolved:\n"))
        untouched = HC.tried_errors(H.template(contract), contract)
        check(f"8: the untouched form of {contract} is refused on `tried`", len(untouched) == 1 and untouched[0].path == "tried",
              str(untouched))
    for contract in EXCLUDED:
        text = (PLUGIN_ROOT / "handoffs" / f"{contract}.yaml").read_text(encoding="utf-8")
        check(f"9: {contract} was not given a `tried` block", "\ntried_note:" not in text)
        check_eq(f"9b: the untouched form of {contract} is not refused on `tried`",
                 HC.tried_errors(H.template(contract), contract), [])


test_cases()
test_shipped_forms()
finish("tried table (presence and shape; the meaning is the stage critic's)")
