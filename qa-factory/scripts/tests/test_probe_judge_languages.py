"""probe_by_code.py: the critic's judgment of a check the tool could not judge reads the same in every language (t-2064 fix Q7).

The slow case `one_language` (test_probe_by_code_languages.py) once read the walk's aggregate from BEFORE the judgment and so showed
csharp and typescript red; the product re-folds the aggregate on disk. This fast file pins that road on the World of test_probe_walk.py
(no function of the product is replaced): a failure text of each language's shape, no marker in it, leaves the check owed with its facts
(never proved by code); `--judge <instance>` with `fires` and the critic's quote proves it, the aggregate ON DISK is `intended_failure`
with the receipt, and the aggregate the walk returned still says owed (the call that judged is the one that answers). With no judgment the
check stays owed; `does_not_fire` (`other_failure`) leaves it not proved with the critic's quote as the reason.
Runnable by pytest."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import test_probe_walk as TW  # noqa: E402
from test_probe_every_check import judge_check, judge_refusal, judged_world  # noqa: E402

TEXTS = {
    "csharp": ("Assert.Equal() Failure: Values differ\nExpected: 3\nActual:   4\n   at Tests.CalcTests.Adds() in /clone/tests/CalcTests.cs:line 12",
               "Assert.Equal() Failure: Values differ"),
    "typescript": ("expect(received).toBe(expected)\n\nExpected: 3\nReceived: 4\n      at Object.<anonymous> (/clone/src/sum.test.ts:11:20)",
                   "expect(received).toBe(expected)"),
    "java": ("org.opentest4j.AssertionFailedError: expected: <3> but was: <4>\n\tat CalcTest.adds(CalcTest.java:12)",
             "org.opentest4j.AssertionFailedError: expected: <3> but was: <4>"),
}


def owed_world(tmp_path, monkeypatch, lang):
    text, quote = TEXTS[lang]
    world, walked = judged_world(tmp_path, monkeypatch, "h", scenario=lambda w, run: [TW.row("failed", text)])
    return world, walked, quote


def on_disk(world) -> dict:
    return json.loads((world.task_root / "work" / "probes" / "i1.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("lang", sorted(TEXTS))
def test_a_run_without_a_marker_is_owed_then_the_critics_fires_proves_it(tmp_path, monkeypatch, lang):
    """The walk leaves the check `incomplete` / `judgment` WITH facts and no receipt; `fires` proves it, re-folds the aggregate on disk and writes
    the receipt. Killed by: a check proved by code with no judgment, facts missing on the check row, `proved_by` other than `critic`, or a
    re-fold that leaves the receipt out."""
    world, walked, quote = owed_world(tmp_path, monkeypatch, lang)
    assert [(r["verdict"], r["cause"], r.get("owes_judgment")) for r in walked["checks"]] == [("incomplete", "judgment", True)], walked["checks"]
    assert walked["verdict"] == "incomplete" and walked["receipt"] is None and walked["judgment_owed"] == world.keys, walked
    assert world.record(world.keys[0])["judgment_facts"]["check_key"] == world.keys[0]
    assert on_disk(world)["verdict"] == "incomplete", "no judgment, no proof"
    record = judge_check(world, quote=quote)
    assert record["verdict"] == "intended_failure" and record["checks"][0]["proved_by"] == "critic" and record["receipt"], record
    stored = on_disk(world)
    assert stored["verdict"] == "intended_failure" and stored["receipt"] and stored["checks"][0]["judgment"]["verdict"] == "fires", stored
    assert "already carries a judgment" in judge_refusal(world, check=world.keys[0], quote=quote)


@pytest.mark.parametrize("lang", sorted(TEXTS))
def test_other_failure_leaves_the_check_not_proved_with_the_critics_reason(tmp_path, monkeypatch, lang):
    world, _walked, quote = owed_world(tmp_path, monkeypatch, lang)
    record = judge_check(world, verdict="other_failure", quote=quote, why="a different statement failed")
    assert record["verdict"] != "intended_failure" and not record["receipt"], record
    assert record["checks"][0]["verdict"] == "wrong_location" and quote in str(record["checks"][0].get("reason") or record["checks"][0]), record


def test_an_empty_quote_or_an_unknown_judge_target_is_refused(tmp_path, monkeypatch):
    world, _walked, _quote = owed_world(tmp_path, monkeypatch, "csharp")
    assert "--quote is empty" in judge_refusal(world, quote="  ")
    assert "not a check of the plan" in judge_refusal(world, check="nowhere.cs:1")
    assert on_disk(world)["verdict"] == "incomplete"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
