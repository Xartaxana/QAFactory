#!/usr/bin/env python3
"""The texts the scribe reads BEFORE the work (FR-38, t-109 piece P10): what stays tied to the code, per file.

The report's counts and statuses are code's (`report_facts.py`); what keeps a role from typing them again is a sentence in each
text it reads. Those sentences are rows of `design/role-rules.json` (read by `scripts/role_rules.py`). What this file holds:

  * the charter stays inside its cap of 9,000 bytes;
  * the scribe's ahead-card carries every heading of `grammar.REPORT_SECTIONS`, in order, and stays inside its cap.

Run on its own: `python -B scripts/tests/test_report_texts.py`.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import grammar as G  # noqa: E402

PLUGIN = harness.PLUGIN_ROOT
CHARTER = PLUGIN / "agents" / "qa-doc-scribe.md"
CARDS = PLUGIN / "references" / "ahead-cards.json"
CHARTER_MAX_BYTES = 9000   # builder-rules item 5, measured with `wc -c`
CARD_MAX_BYTES = 1200      # test_ahead_cards.py's own cap for a card


def card_text() -> str:
    data = json.loads(CARDS.read_text(encoding="utf-8"))
    return data["cards"]["qa-doc-scribe"]["text"]


def sections_in_order(text: str, names) -> bool:
    """Every name in `text`, each after the one before it."""
    at = 0
    for name in names:
        found = text.find(name, at)
        if found < 0:
            return False
        at = found + len(name)
    return True


def main() -> None:
    # --- the charter stays inside its cap (it was over it: 9,239 B) -----------------------------
    size = len(CHARTER.read_text(encoding="utf-8").encode("utf-8"))
    check(f"the charter is within {CHARTER_MAX_BYTES} bytes ({size} B)", size <= CHARTER_MAX_BYTES)

    # --- the card carries the code's own section list, in order ---------------------------------
    headings = [s[len("## "):] for s in G.REPORT_SECTIONS]
    check_eq("the code names eleven report sections", len(headings), 11)
    card = card_text()
    for heading in headings:
        check_in(f"the card names the section {heading}", heading, card)
    check("the card names the eleven sections in the code's order", sections_in_order(card, headings))
    check("control: the sections listed in another order are not in order",
          not sections_in_order(card, list(reversed(headings))))
    check(f"the card is within {CARD_MAX_BYTES} bytes ({len(card.encode('utf-8'))} B)",
          len(card.encode("utf-8")) <= CARD_MAX_BYTES)

    harness.finish("test_report_texts")


if __name__ == "__main__":
    main()
