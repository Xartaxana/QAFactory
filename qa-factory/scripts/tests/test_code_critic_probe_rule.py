#!/usr/bin/env python3
"""The code critic's charter for the mutation-probe judgment (t-1968 N3; formerly RN1-8 K6 / K11).

A probe that failed AT the mutated line on a text code cannot read is `incomplete`, `cause: judgment`: the code critic judges it with
`probe_by_code.py --judge` (the door the code publishes as `probe_by_code.JUDGE_DOOR`). Pinned here: the Tools bullet names every flag
of the door (read from the code, not copied), and every `critic_verdict:` value the charter names is a word of
`contract.CRITIC_VERDICTS` (negative control: `killed` -> red). The role-text phrases of the old checks (the probe-run log, the form
comment, the vocabulary word, the lifecycle slice) moved to design/role-rules.json; the old-road absence scan was dropped.

`test_charter_names_judge_command` reads the flags from `probe_by_code.JUDGE_DOOR`; until that constant exists (node N2) it FAILS
naming the missing constant - never skipped, never passed.

Runnable alone (`python -B scripts/tests/test_code_critic_probe_rule.py`) and collected by pytest."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import contract as C  # noqa: E402
from harness import SCRIPTS  # noqa: E402

PKG = SCRIPTS.parent
CHARTER = PKG / "agents" / "qa-code-critic.md"


def judge_flags(door: str) -> list:
    """The `--flag` words of a door string, in order, once each."""
    seen: list = []
    for flag in re.findall(r"--[a-z][a-z-]*", door):
        if flag not in seen:
            seen.append(flag)
    return seen


def tools_section(text: str) -> str:
    return text[text.index("## Tools"):text.index("## When to ask")]


def missing_flags(text: str, door: str) -> list:
    """The flags of the door that the Tools section of the charter text does not carry."""
    tools = tools_section(text)
    return [flag for flag in judge_flags(door) if flag not in tools]


def unknown_verdicts(text: str) -> list:
    """The `critic_verdict: <word>` values the text names that the contract does not know."""
    return sorted({w for w in re.findall(r"critic_verdict:\s*`?([a-z_]+)", text) if w not in C.CRITIC_VERDICTS})


def test_charter_names_judge_command():
    import probe_by_code
    door = getattr(probe_by_code, "JUDGE_DOOR", None)
    assert door, "probe_by_code.JUDGE_DOOR does not exist yet (node N2 adds it): the charter's flags cannot be read from the code"
    assert missing_flags(CHARTER.read_text(encoding="utf-8"), door) == []


def test_charter_critic_verdicts_are_contract_words():
    text = CHARTER.read_text(encoding="utf-8")
    assert unknown_verdicts(text) == []
    assert "critic_verdict:" in text                                     # control premise
    assert unknown_verdicts(text + "\n`critic_verdict: killed`") == ["killed"]


# --- t-2064 P7: what the critic reads about the probe road. The sentences of the charter and of phases/s5.md are rows of
# design/role-rules.json (ids `probe-*`, `automator-*`), read by scripts/role_rules.py; what stays here cannot be a register row: a key
# looked for in the BUILT brief card (`brief_pack.TOOLING`), and an absence. Each check has a negative control: the key cut from a copy.
def absent_keys(text: str, keys: tuple) -> list:
    """The keys the (whitespace-folded) text does not carry."""
    folded = " ".join(text.split())
    return [key for key in keys if key not in folded]


# The HOW of the probe road (the calls) lives in the card the critic receives (the brief card built by brief_pack, one home: AR-11); the
# charter carries the WHAT and points at the card. The keys are the P7 keys, looked for where the HOW lives.
def card_text() -> str:
    import brief_pack
    return " ".join(" ".join(brief_pack.TOOLING["qa-code-critic"]).split())


def check_card_keys(keys: tuple, text: str = "") -> None:
    text = text or card_text()
    assert absent_keys(text, keys) == [], absent_keys(text, keys)
    for key in keys:                                                     # negative control: the key cut from a copy -> red
        assert absent_keys(" ".join(text.split()).replace(key, ""), keys) == [key], key


def test_charter_does_not_say_the_calls_twice():
    assert "`--at` is a plan of one row" not in CHARTER.read_text(encoding="utf-8")     # the calls are not said twice: the card has them


def test_card_says_background_walk():
    check_card_keys(("runs in the background", "`plan_unfinished`: the same call continues it"))


def test_card_at_is_one_row():
    check_card_keys(("select rows on the same road and need the entry too", "with no --at it walks every check"))


def test_charter_is_assertion_id_old_reading_gone():
    text = CHARTER.read_text(encoding="utf-8")
    assert "the probe broke another line" not in text                    # the old reading of `is_assertion_id: false`


def test_card_product_one_check():
    check_card_keys(("red_sandbox.py --probe", "it proves the one check it names", "you name it with a `product` entry",
                     "the others stay owed"))


def main() -> None:
    failed = 0
    total = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            total += 1
            try:
                fn()
                print("PASS " + name)
            except Exception as exc:                                     # noqa: BLE001
                failed += 1
                print(f"FAIL {name} - {exc}")
    print(f"=== test_code_critic_probe_rule: {total - failed}/{total} ok ===")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
