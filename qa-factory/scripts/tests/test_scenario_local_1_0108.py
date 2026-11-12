#!/usr/bin/env python3
"""Scenario `local-1-0108`: a scrubbed slice of a real run of the synthetic MyBooks task LOCAL-1, walked through the exit gate,
the gate A / gate B question and decision doors, the hand-over to the next role and the delivery assessment (TD-15.5.3).
The recorded run is `fixtures/stories/local-1-0108/` (README.txt: source, what changed, what was dropped).
Run on its own: `python -B scripts/tests/test_scenario_local_1_0108.py`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scenario_walk  # noqa: E402

scenario_walk.run("local-1-0108")
