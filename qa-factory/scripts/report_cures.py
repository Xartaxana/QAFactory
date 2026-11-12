#!/usr/bin/env python3
"""The cure words for "this test command writes no report the factory can read" - ONE reader of ONE data file (FR-13).

The words live in `references/report-cures.json`, one row per framework. Three callers read them, and all three go through
this module: the suite runner (`run_suite.report_cure`, the sentence it prints in the middle of a run), gate A's reporter
card (through that same function) and the onboarding probe (`onboarding_probe`, which also PROPOSES a cure). It is a LEAF on
purpose: it imports the standard library and, lazily, `execution_request.is_pytest_command` - never `gate_preflight`,
`run_suite`, `onboarding_probe` or `story_run` - so the runner does not pull the gate into its import closure (a test holds
that by reading this file's imports).

    load(path=None)          -> the table {"question": {...}, "rows": [...]}, or raises CureTableUnreadable
    row_for(argv, rows=None) -> the row for this command, or None
    cure_words(argv)         -> the row's `words` ('' when the framework needs none, or no row names it)

What a row MEANS (its keys, the matching rule) is written in the file's own `note`. What makes a row usable for the PROBE
(its flag, `person_words`, `add_argv`...) is checked by `onboarding_probe.cure_table`; this module keeps only what matching
and the words need - a row of another shape is skipped, never a crash (a words table must not stop a run).
"""
from __future__ import annotations

import json
from pathlib import Path

CURES_FILE = "report-cures.json"
PYTEST_TOKENS = ("pytest", "py.test")


class CureTableUnreadable(Exception):
    """The cure table could not be read; `str(exc)` is a sentence a person can be given: "the cure table could not be read: <why>"."""


def cures_path() -> Path:
    return Path(__file__).resolve().parents[1] / "references" / CURES_FILE


def load(path=None) -> dict:
    """The cure table as the file holds it: {"question": ..., "rows": [...]} (at least `rows`, a list). Raises
    `CureTableUnreadable` for a file that is missing, not JSON, or has no `rows` list - there is then no table to read."""
    src = Path(path) if path else cures_path()
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CureTableUnreadable(f"the cure table could not be read: {type(exc).__name__}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        raise CureTableUnreadable("the cure table could not be read: it has no `rows` list")
    return data


def _is_pytest(argv) -> bool:
    try:
        from execution_request import is_pytest_command
        return bool(is_pytest_command(list(argv)))
    except Exception:       # noqa: BLE001 - a command that cannot be classified falls back to the token test
        return any(any(t in str(part) for t in PYTEST_TOKENS) for part in list(argv)[:3])


def _usable(row) -> bool:
    """What matching and the words need of a row - nothing more (the probe's own check is stricter)."""
    return (isinstance(row, dict) and isinstance(row.get("words"), str)
            and isinstance(row.get("match"), list) and bool(row["match"]) and all(isinstance(t, str) for t in row["match"]))


def row_for(argv, rows=None):
    """The cure row for this command, or None (a framework nobody has written a row for). The FIRST row whose word is in
    the lower-cased command line wins - except that a pytest-shaped command takes the row whose `words` are empty (the runner
    equips pytest itself), so a pytest command whose path happens to say `karma` is never handed a karma cure.
    `rows` is a list already read; None reads the file (and may raise `CureTableUnreadable`)."""
    rows = [r for r in (load()["rows"] if rows is None else rows) if _usable(r)]
    text = " ".join(str(a) for a in (argv or [])).lower()
    if _is_pytest(argv or []):
        for row in rows:
            if not row["words"] and any(t.lower() in text for t in row["match"]):
                return row
    for row in rows:
        if any(t.lower() in text for t in row["match"]):
            return row
    return None


def cure_words(argv, table=None) -> str:
    """The words a person (or a role) is told for this command: the row's `words`, '' when the framework needs none
    (pytest) or no row names it. `table` is a table already read ({"rows": [...]}); None reads the file."""
    row = row_for(argv, None if table is None else table["rows"])
    return row["words"] if row else ""
