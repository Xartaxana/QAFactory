#!/usr/bin/env python3
"""Scenario `cart-1`: a recorded run of the synthetic MyBooks task CART-1 (a cart feature, size XXL, package 0.10.6),
walked through today's doors by the scenario walker (TD-15.5.2). Data replay: the story is `fixtures/stories/cart-1/`
(story.json = the walk, expected.json = what the run recorded). Run on its own: `python -B scripts/tests/test_scenario_cart_1.py`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scenario_walk  # noqa: E402

if __name__ == "__main__":
    scenario_walk.run("cart-1")
