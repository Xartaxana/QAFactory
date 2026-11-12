#!/usr/bin/env python3
"""Scenario `local-1-arm-b`: a recorded run of the synthetic MyBooks task LOCAL-1 (package 0.10.9), cut right after the first approved
gate A decision (events up to seq 58; stages S1..S4 and gate A), walked through today's doors by the scenario walker (TD-15.5.1b).
Data replay: the story is `fixtures/stories/local-1-arm-b/` (story.json = the walk, expected.json = what the run recorded).
Run on its own: `python -B scripts/tests/test_scenario_local_1_arm_b.py`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scenario_walk  # noqa: E402

if __name__ == "__main__":
    scenario_walk.run("local-1-arm-b")
