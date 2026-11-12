#!/usr/bin/env python3
"""The walk charter (spec t-1957 N4): it is small, and every stop kind and flag it names exists in data.
The rules of the step-call paragraph are rows of design/role-rules.json (a walk-* row per rule), not pins here.

Each test names the ONE mutation that kills it (builder-rules 7a):
  test_charter_words_exist_in_data       -> rename `walk_session` in manual-capture-steps.json, or a stop kind the charter names
  test_flag_outside_parsers_is_reported   -> make `parser_flags` return every `--word` of the file, or drop the `flag not defined` branch
  test_size_at_and_beyond_limit          -> `<=` to `<` in the size comparison, or a charter of 4 501 bytes
  test_runner_injects_walk_charter        -> point inject-map qa-runner back at manual-evidence.md
Red on the real data until node N1a (the `walk_session` object of manual-capture-steps.json) merges: that is the temporal edge E4.5.
Run: python -B -m pytest scripts/tests/test_walk_charter.py -q
"""
import json
import re
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
CHARTER = PLUGIN / "references" / "walk-charter.md"
STEPS = PLUGIN / "references" / "manual-capture-steps.json"
MAX_BYTES = 4500
WALK_SESSION = PLUGIN / "scripts" / "walk_session.py"


def parser_flags(path=WALK_SESSION) -> set:
    """The flags are the ones walk_session.py's parsers define: every `--flag` literal that is an argument of an `add_argument(` call."""
    try:
        source = Path(path).read_text(encoding="utf-8")
    except OSError:
        return set()
    flags = set()
    for call in re.finditer(r"add_argument\(([^)]*)", source):
        flags.update(re.findall(r"""["'](--[a-z][a-z-]*)["']""", call.group(1)))
    return flags


FLAGS = parser_flags()        # read once; a flag the charter names that no parser defines is a word the code does not define

def data_problems(text: str, data: dict) -> list:
    """Every stop kind and flag the charter names must be one the data (or the spec's flag list) defines."""
    walk = data.get("walk_session")
    if not isinstance(walk, dict):
        return ["manual-capture-steps.json has no object `walk_session` (node N1a has not merged)"]
    kinds = set((data.get("surprise") or {}).get("kinds") or [])
    default = walk.get("stop_on_default") or []
    problems = []
    for token in re.findall(r"`--stop-on ([^`]+)`", text):
        for part in token.replace(" or ", ",").split(","):
            part = part.strip().lstrip("+-")
            m = re.fullmatch(r"status:(\d{3})-(\d{3})", part)
            if m:
                if not 400 <= int(m.group(1)) <= int(m.group(2)) <= 599:
                    problems.append(f"status range out of 400-599: {part}")
            elif part not in kinds and part not in ("default", "none"):
                problems.append(f"stop kind not in surprise.kinds: {part}")
    for m in re.finditer(r"`\+(status:\d{3}-\d{3})`", text):          # a bare `+status:lo-hi` token after "or"
        lo, hi = (int(n) for n in re.findall(r"\d{3}", m.group(1)))
        if not 400 <= lo <= hi <= 599:
            problems.append(f"status range out of 400-599: {m.group(1)}")
    if not FLAGS:
        problems.append("walk_session.py defines no flags (unreadable or renamed)")
    else:
        for flag in sorted(set(re.findall(r"(?<![\w-])--[a-z][a-z-]*", text))):
            if flag not in FLAGS:
                problems.append(f"flag not defined: {flag}")
    # the paragraph says what the default stops on: it must be the data's list (AR-10)
    for word, token in (("5xx", "status:500-599"), ("console error", "console"), ("navigation", "url")):
        if word in text and token not in default:
            problems.append(f"charter names {word} as a default stop, data default lacks {token}")
    return problems


def test_charter_words_exist_in_data():
    data = json.loads(STEPS.read_text(encoding="utf-8"))
    assert data_problems(CHARTER.read_text(encoding="utf-8"), data) == []


def test_data_check_passes_on_data_with_walk_session_and_fails_without():
    """The same checking function on a copy of the data with the N1a values (spec: given): green; without the object: red, named."""
    data = json.loads(STEPS.read_text(encoding="utf-8"))
    text = CHARTER.read_text(encoding="utf-8")
    data.setdefault("surprise", {}).setdefault("kinds", ["request", "status", "failed", "console", "url", "field", "text", "blocked_host"])
    without = {k: v for k, v in data.items() if k != "walk_session"}
    assert data_problems(text, without) == ["manual-capture-steps.json has no object `walk_session` (node N1a has not merged)"]
    with_it = dict(without, walk_session={"stop_on_default": ["status:500-599", "console", "url"]})
    assert data_problems(text, with_it) == []
    broken = dict(without, walk_session={"stop_on_default": ["console"]})
    assert data_problems(text, broken) != []
    assert data_problems(text.replace("+field", "+nonsense"), with_it) == ["stop kind not in surprise.kinds: nonsense"]


def test_flag_outside_parsers_is_reported():
    data = json.loads(STEPS.read_text(encoding="utf-8"))
    text = CHARTER.read_text(encoding="utf-8")
    assert {"--final", "--stop-on", "--steps-file", "--item", "--line"} <= FLAGS
    assert data_problems(text + " `--no-such-flag`", data) == ["flag not defined: --no-such-flag"]
    assert parser_flags(PLUGIN / "scripts" / "no-such-file.py") == set()


def test_size_at_and_beyond_limit():
    size = len(CHARTER.read_bytes())
    assert size <= MAX_BYTES, size
    assert len(b"x" * MAX_BYTES) <= MAX_BYTES < len(b"x" * (MAX_BYTES + 1))


def test_no_cyrillic():
    assert not any(0x400 <= ord(c) <= 0x4FF for c in CHARTER.read_text(encoding="utf-8"))


def test_runner_injects_walk_charter():
    roles = json.loads((PLUGIN / "references" / "inject-map.json").read_text(encoding="utf-8"))["roles"]["qa-runner"]
    assert "plugin:references/walk-charter.md" in roles
    assert "plugin:references/manual-evidence.md" not in roles


if __name__ == "__main__": raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
