"""probe_by_code.py: a person's word re-runs a PROVED check on the walk road (t-2064 fix W, TR2-14), on the stub runner of `test_probe_walk.World`.

The old road's guard (`proof_level.already_probed`: "a person's recorded word passes the repeat if it was said after the record it repeats") was
read on the walk, but the walk then skipped the proved check by its per-check record. `_probe_plan` now carries the word to `_walk_plan`
(`plan["rerun"]`, `_word_reruns`), which re-runs the proved checks through the same `_walk_attempt` as a first run. Each test names the mutation
that kills it. Fast; no sleeps, no real runner. Runnable alone and collected by pytest."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import probe_by_code as PBC  # noqa: E402
import test_probe_walk as TW  # noqa: E402
from test_probe_every_check import flip, flip_actual, flip_call, flip_models, flip_refusal, flip_snapshot  # noqa: E402
from test_probe_fix_round import aggregate_bytes, with_row  # noqa: E402

RECORDED = "2026-09-01T00:00:00+00:00"
AFTER = "2026-09-01T00:00:01+00:00"
WORD = "probe it again, I asked"


def say(world, at, decision=WORD, match="already probed on these bytes") -> None:
    """A person's recorded word for the repeat block (what waiver.py writes into pipeline.json)."""
    path = world.task_root / "pipeline.json"
    path.write_text(json.dumps({"stage_overrides": [{"stage": "S5", "match": match, "decision": decision, "at": at}]}), encoding="utf-8")


def stamp(world, at=RECORDED) -> None:
    """Say the standing aggregate was recorded at `at` (the fixture's way to say 'recorded long ago')."""
    path = world.task_root / "work" / "probes" / "i1.json"
    body = json.loads(path.read_text(encoding="utf-8"))
    body["recorded_at"] = at
    path.write_text(json.dumps(body), encoding="utf-8")


def proved(tmp_path, monkeypatch, kinds="ss"):
    """A world with a complete walk behind it: every check `intended_failure`, the receipt on the row, one run made, the record stamped old."""
    world = flip(tmp_path, monkeypatch, kinds, stage="S5")
    row = with_row(world, monkeypatch)
    monkeypatch.setattr(PBC.proof_level, "binding_facts", lambda task_root, iid: {      # a content-addressed case version: the receipt is valid
        "case_version": "cv_1", "test_content_hash": PBC.sha256(world.original), "source_revision": "rev1", "build_id": "b1"})
    flip_models(world, flip_actual(world))
    first = flip_call(world)
    assert first["verdict"] == "intended_failure" and first["receipt"], (first["verdict"], first["notes"])
    row["sensitivity_proof"] = {"receipt_ref": first["receipt"]}
    stamp(world)
    return world, row


def test_no_word_a_repeat_is_answered_nothing_launched(tmp_path, monkeypatch):
    """Rule 1: the same bytes, the same model, no word: `already_probed`, no run, not a byte written. Killed by: nothing here (the unchanged
    guard); it is the control the next tests differ from."""
    world, _row = proved(tmp_path, monkeypatch)
    runs, before = len(world.runs), flip_snapshot(world.root, world.task_root)
    again = flip_call(world)
    assert again["verdict"] == "already_probed" and len(world.runs) == runs and flip_snapshot(world.root, world.task_root) == before, (again["verdict"], again["notes"])


def test_the_word_reruns_the_proved_checks_once_and_the_record_says_so(tmp_path, monkeypatch):
    """Rule 2 and 6: a word said after the record: the proved checks run again (one joint run, through `_walk_attempt`), the answer is the
    walk's aggregate, and its notes carry the word. Killed by: `_word_reruns` returning False (the proved checks are skipped, no run)."""
    world, _row = proved(tmp_path, monkeypatch)
    runs = len(world.runs)
    say(world, AFTER)
    seen = []
    real = PBC._walk_attempt
    monkeypatch.setattr(PBC, "_walk_attempt", lambda *a, **k: seen.append(1) or real(*a, **k))
    got = flip_call(world)
    assert got["verdict"] == "intended_failure" and len(world.runs) == runs + 1 and seen == [1], (got["verdict"], len(world.runs), seen)
    assert WORD in " ".join(got["notes"]), got["notes"]
    assert all(c["verdict"] == "intended_failure" for c in got["checks"]), got["checks"]


def test_the_word_is_spent_by_the_record_of_its_own_repeat(tmp_path, monkeypatch):
    """Rule 3: call 1 with a fresh word launches the run; call 2 with the SAME word on file is answered `already_probed` and launches nothing.
    Killed by: `word_passes` fed the record's OLD `recorded_at` (or its comparison forced true): the word stays unspent and call 2 runs again."""
    world, row = proved(tmp_path, monkeypatch)
    say(world, AFTER)
    runs = len(world.runs)
    first = flip_call(world)
    assert len(world.runs) == runs + 1, "the word's call launched the run"
    row["sensitivity_proof"] = {"receipt_ref": first["receipt"]}
    second = flip_call(world)
    assert second["verdict"] == "already_probed" and len(world.runs) == runs + 1, (second["verdict"], len(world.runs))


def test_residual_an_incomplete_rerun_keeps_the_record_so_the_word_runs_once_more(tmp_path, monkeypatch):
    """Inherited from the old road, not a goal: a re-run that gives no result keeps the standing record (and its old `recorded_at`), so the same
    word is still newer than the record and re-runs ONCE MORE on the next call. It only runs the probe again; it never proves by itself
    (the standing verdict is not lowered or raised by it). Pinned as the code behaves; not a requirement."""
    world, _row = proved(tmp_path, monkeypatch)
    say(world, AFTER)
    world.scenario = lambda w, run: []
    runs = len(world.runs)
    flip_call(world)
    assert len(world.runs) == runs + 1, "the word re-ran the checks"
    flip_call(world)
    assert len(world.runs) == runs + 2, "the word is still valid: the record did not move"
    assert all(r["verdict"] == "intended_failure" for r in standing_of(world)), "nothing was proved or lowered by the repeat"


def standing_of(world) -> list:
    return [json.loads(PBC.proof_level.probe_record_path(world.task_root, "i1", target_line=c["line"], file=c["file"]).read_text())
            for c in world.checks]


def test_the_word_never_lowers_a_proof(tmp_path, monkeypatch):
    """Rule 4: the re-run gives NO result (no report rows: `not_executed`): the standing proved verdict of each check is kept, with its
    `last_attempt`, exactly as for any later attempt on a standing `intended_failure` (`keep_standing_record`). Killed by: the word's re-run
    writing its outcome over the standing record."""
    world, _row = proved(tmp_path, monkeypatch)
    say(world, AFTER)
    world.scenario = lambda w, run: []
    got = flip_call(world)
    assert len(world.runs) == 2, "the word re-ran the checks"
    standing = standing_of(world)
    assert all(r["verdict"] == "intended_failure" and r.get("last_attempt") for r in standing), standing
    assert got["verdict"] != "already_probed", got["verdict"]


def test_a_judged_pass_after_the_word_is_the_old_rule_not_a_new_one(tmp_path, monkeypatch):
    """Rule 4, the judged case: the re-run PASSES (the check survives now): that is a judged `no_failure`, which replaces a standing record as
    it does after any later attempt (E23) - the word adds no rule of its own. Killed by: a word-specific keep that shields the record."""
    world, _row = proved(tmp_path, monkeypatch)
    say(world, AFTER)
    world.scenario = lambda w, run: [TW.row("passed")]
    got = flip_call(world)
    assert len(world.runs) == 2 and got["verdict"] == "no_failure", (len(world.runs), got["verdict"])
    assert [r["verdict"] for r in standing_of(world)] == ["no_failure"] * 2


@pytest.mark.parametrize("at,decision,why", [
    ("2026-08-31T00:00:00+00:00", WORD, "a word older than the record is spent on it"),
    (RECORDED, WORD, "a word said AT the record's time is spent"),
    (AFTER, "", "an empty word is no word"),
    (AFTER, "   ", "a whitespace word is no word"),
])
def test_an_old_spent_or_empty_word_is_no_word(tmp_path, monkeypatch, at, decision, why):
    """The edges of rule 1: answered, nothing launched. Killed by: a word read without its time or its text."""
    world, _row = proved(tmp_path, monkeypatch)
    say(world, at, decision)
    runs = len(world.runs)
    got = flip_call(world)
    assert got["verdict"] == "already_probed" and len(world.runs) == runs, why


def test_a_word_for_another_block_passes_nothing(tmp_path, monkeypatch):
    """A word whose block names something else is no word for this repeat: answered. Killed by: reading any override as a word."""
    world, _row = proved(tmp_path, monkeypatch)
    say(world, AFTER, match="another block")
    runs = len(world.runs)
    assert flip_call(world)["verdict"] == "already_probed" and len(world.runs) == runs


@pytest.mark.parametrize("refusal", ["_shape_refusals", "_locating_refusals"])
def test_refusals_stay_before_everything_with_the_word(tmp_path, monkeypatch, refusal):
    """Rule 5: the R6 shape refusal and the pre-write locating refusal are still the CALL's refusals with the word on file, asked before
    `_walk_plan`: no run, not a byte written. Killed by: moving the word's re-run ahead of these passes in `_probe_plan`."""
    world, _row = proved(tmp_path, monkeypatch)
    say(world, AFTER)
    asked = []

    def refuse(*a, **k):
        asked.append(refusal)
        raise PBC.ToolRefusal(f"{refusal} refuses. Nothing was changed.")

    monkeypatch.setattr(PBC, refusal, refuse)
    monkeypatch.setattr(PBC, "_walk_plan", lambda *a, **k: pytest.fail("the walk must not be reached"))
    runs, before = len(world.runs), flip_snapshot(world.root, world.task_root)
    assert "Nothing was changed" in flip_refusal(world) and asked == [refusal]
    assert len(world.runs) == runs and flip_snapshot(world.root, world.task_root) == before


def test_under_a_selection_the_word_reruns_only_the_selected_check(tmp_path, monkeypatch):
    """`--at` with the word: the selected proved check runs again and the others stay as they were (the old road probed the asked check).
    Killed by: `_word_reruns` ignoring `only` (both checks run: the run's rows name two keys)."""
    world, _row = proved(tmp_path, monkeypatch)
    say(world, AFTER)
    runs = len(world.runs)
    flip_call(world, at=int(world.keys[0].rsplit(":", 1)[1]))
    assert len(world.runs) == runs + 1, "one run"
    marked = sorted(world.runs[-1]["tokens"])
    assert marked == [world.keys[0]], f"only the selected check carried a marker: {marked}"


def test_without_a_selection_the_record_is_the_aggregate_of_the_new_run(tmp_path, monkeypatch):
    """The re-run is written by the one writer: the aggregate on disk changed (a record of this call, not the stamped one)."""
    world, _row = proved(tmp_path, monkeypatch)
    before = aggregate_bytes(world)
    say(world, AFTER)
    flip_call(world)
    assert aggregate_bytes(world) != before


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
