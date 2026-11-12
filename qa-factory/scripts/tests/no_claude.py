#!/usr/bin/env python3
"""The `claude` a test gets when it names no stub of its own (not a test; selftest ignores it).

harness.py points STORY_RUN_CLAUDE here at import. A test that reaches the driver's
`run_claude` without its own stub used to fall back to whatever `claude` lies on PATH, and a
conductor round trip then started a REAL `claude -p` session: it costs money and acts in a
temp project. This file starts nothing. It says so on stderr, appends the same line to the
file named by NO_CLAUDE_LOG when that is set (so a run can be audited afterwards), and exits
97 - a code no real `claude` uses, so the driver reads it as a failed call, not a verdict.
"""
import os
import sys

line = "a test tried to start a real claude session: " + " ".join(sys.argv[1:])
print(line, file=sys.stderr)
log = os.environ.get("NO_CLAUDE_LOG")
if log:
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")
sys.exit(97)
