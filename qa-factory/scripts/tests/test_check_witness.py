"""PC-4 (t-2181 B6, C14): `check_witness` for a manifest whose every test is pending implementation.

A test that touches an absent side is written and collected, never run, so the manifest owes no `run_witness` - but it owes the
collect (`runs[]` row `kind: collect`). One test that could run puts the whole manifest back under the run_witness rule, and a
collect is never a run witness. The excuse is `acceptance.pending_instances`, read in its manifest-only mode.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import check, check_eq, check_in, cleanup, finish, temp_project  # noqa: E402

import acceptance as AC  # noqa: E402
import check_witness as W  # noqa: E402
import handoff_check as H  # noqa: E402
import stage_guard as SG  # noqa: E402
import validate_artifacts as V  # noqa: E402

RULE = W.RULES["automation-manifest.json"]
PENDING_ROW = {"case": "TC-1", "reason": "pending_implementation", "instance_ids": ["test_a"]}
COLLECT = {"label": "collect-1", "kind": "collect", "scope": ["tests/test_ui.py::test_a"]}
REAL_WITNESS = "evidence/w-20261101.json exit 0, 1 passed in 0.3s (a run_suite summary line long enough)"


def test(iid, sides=None, case="TC-1") -> dict:
    out = {"instance_id": iid, "case": case, "covers": [case], "file": "tests/test_ui.py", "status": "Draft"}
    if sides is not None:
        out["sides"] = sides
    return out


def manifest(tests, unresolved=(PENDING_ROW,), runs=(), **extra) -> dict:
    return {"tests": list(tests), "unresolved": list(unresolved), "runs": list(runs), **extra}


def all_pending_with_collect_accepted() -> None:
    d = manifest([test("test_a", {"backend": "absent"})], runs=[COLLECT])
    check_eq("every test pending", AC.run_witness_excused(d), "pending")
    check_eq("B6: all pending + the collect row: no run_witness owed, accepted", RULE(d), [])


def all_pending_without_collect_refused() -> None:
    d = manifest([test("test_a", {"backend": "absent"})])
    errors = RULE(d)
    check_eq("B6: all pending, no collect row: refused", len(errors), 1)
    check_in("B6: and the refusal names the collect and its door", "--collect-only", errors[0])
    check("B6: a run row (not a collect) is no collect", RULE(manifest([test("test_a", {"backend": "absent"})],
                                                                      runs=[{"label": "w", "kind": "run"}])) != [])


def collect_must_be_whole_and_cover_the_files() -> None:
    """F6: a `partial: true` collect, and a collect of an unrelated file, stand for no pending test."""
    d = manifest([test("test_a", {"backend": "absent"})], runs=[{**COLLECT, "partial": True}])
    errors = RULE(d)
    check_eq("F6 all_pending_with_partial_collect_refused: the collect listed only the healthy files", len(errors), 1)
    check_in("F6: and the refusal names the door", "--collect-only", errors[0])
    other = manifest([test("test_a", {"backend": "absent"})], runs=[{"label": "c2", "kind": "collect", "files": ["tests/test_other.py"],
                                                                     "scope": ["tests/test_other.py::test_z"]}])
    check_eq("F6 collect_of_another_file_refused: the collect names another file", len(RULE(other)), 1)
    whole = manifest([test("test_a", {"backend": "absent"})], runs=[{"label": "c3", "kind": "collect", "files": ["tests/test_ui.py"]}])
    check_eq("F6: a whole collect named by `files` alone covers the file", RULE(whole), [])
    two = manifest([test("test_a", {"backend": "absent"}), {**test("test_b", {"backend": "absent"}), "file": "tests/test_two.py"}],
                   unresolved=[{**PENDING_ROW, "instance_ids": ["test_a", "test_b"]}], runs=[COLLECT])
    check_eq("F6: two pending files, a collect of one of them: refused", len(RULE(two)), 1)


def phase_errors_of(d: dict) -> list:
    """What `validate_artifacts.check_phase_json` says about a manifest file holding `d` (B3: the second reader of the excuse)."""
    project = temp_project("qa-witness-phase-")
    try:
        path = project / "automation-manifest.json"
        path.write_text(json.dumps(d), encoding="utf-8")
        errors: list = []
        V.check_phase_json(path, errors)
        return errors
    finally:
        cleanup(project)


def excuse_is_one_reader_in_three_places() -> None:
    """B3: `acceptance.run_witness_excused` is asked by `check_witness`, `check_phase_json` and `handoff_check._run_witness`;
    the pending road and the handed road both pass without a `run_witness` key, and one runnable test brings the refusal back."""
    pending = manifest([test("test_a", {"backend": "absent"})], runs=[COLLECT])
    check_eq("B3: an all-pending manifest with no run_witness key passes phase_errors", phase_errors_of(pending), [])
    runnable = manifest([test("test_a", {"backend": "absent"}), test("test_b", {"ui": "real"}, case="TC-2")], runs=[COLLECT])
    check_in("B3: one runnable test brings the required key back", "run_witness", " ".join(phase_errors_of(runnable)))
    handed = manifest([test("test_h", case="TC-3")], unresolved=[{"case": "TC-3", "reason": "handed_to_person"}])
    check_eq("B3: the all-handed road passes phase_errors with no key as well (the same excuse)", phase_errors_of(handed), [])
    check_in("B3: an ordinary manifest with no key is still refused", "run_witness",
             " ".join(phase_errors_of(manifest([test("test_a")], unresolved=()))))
    art = SimpleNamespace(manifest=pending, run={})
    check_eq("B3: handoff derives the collect row's label for an all-pending manifest",
             H._run_witness(art, {}), ("collect-1", "automation-manifest.runs[] collect"))
    check_eq("B3: and derives nothing for a runnable manifest with only a collect row",
             H._run_witness(SimpleNamespace(manifest=runnable, run={}), {}), None)


def the_collect_door_is_open_to_the_guard() -> None:
    """B4 (FR-2, AR-9): the command the refusal above names, `run_suite.py --task <T> --collect-only --tests ... -- <cmd>`, launches
    no test, so `stage_guard.rule_typed_runner` lets it through while a dispatch is active; an untyped launch is still refused.
    (Placed here: `test_stage_guard.py` is not an owned path of PC-4.)"""
    event = {"cwd": str(Path(__file__).resolve().parents[2]), "tool_input": {}}
    active = {"dispatches": {"d-1": {"id": "d-1", "status": "running", "scope": ["TC-1"]}}}
    collect = "python run_suite.py --task X --collect-only --tests tests/test_ui.py -- python -m pytest tests/test_ui.py"
    check_eq("B4: the collect command passes under an active dispatch", SG.rule_typed_runner(collect, event, "X", active), "")
    check("B4: `--collect-only` is a non-executing flag", "--collect-only" in SG.NON_EXECUTING_FLAGS)
    check("B4: an untyped launch (`--task X --label y`) is still refused",
          bool(SG.rule_typed_runner("python run_suite.py --task X --label y", event, "X", active)))


def one_runnable_needs_run_witness() -> None:
    d = manifest([test("test_a", {"backend": "absent"}), test("test_b", {"ui": "real"}, case="TC-2")], runs=[COLLECT])
    check_eq("a manifest with one test that can run is not all pending", AC.run_witness_excused(d), "")
    errors = RULE(d)
    check_eq("B6: one runnable test: the run_witness is demanded as before, the collect row does not stand for it",
             [e for e in errors if e.startswith("run_witness missing")] != [], True)
    check_eq("B6: and with a real witness it is accepted", RULE({**d, "run_witness": REAL_WITNESS}), [])
    sub = manifest([test("test_a", {"backend": "substituted"})], runs=[COLLECT])
    check("B6: a pending row on a substituted side excuses nothing", AC.run_witness_excused(sub) == "" and RULE(sub) != [])
    check_eq("B6: a pending row with no `sides` declared excuses nothing", AC.run_witness_excused(manifest([test("test_a")], runs=[COLLECT])), "")
    check_eq("B6: a manifest with no tests is not all pending", AC.run_witness_excused(manifest([])), "")


def collect_is_no_run_witness() -> None:
    d = manifest([test("test_a", {"ui": "real"})], unresolved=(), runs=[COLLECT])
    check_in("a collect row is not a run_witness: a runnable manifest with only one is refused", "run_witness missing", " ".join(RULE(d)))
    d2 = manifest([test("test_a", {"ui": "real"})], unresolved=(), runs=[COLLECT], run_witness=COLLECT["label"])
    check_in("and a collect's label put into run_witness is a brush-off, not a witness", "run_witness missing", " ".join(RULE(d2)))


def unchanged_roads() -> None:
    handed = manifest([test("test_h", case="TC-3")], unresolved=[{"case": "TC-3", "reason": "handed_to_person"}])
    check_eq("an all-handed manifest still owes no run_witness", RULE(handed), [])
    check_eq("an ordinary manifest with a witness is accepted as before", RULE(manifest([test("test_a")], unresolved=(),
                                                                                         run_witness=REAL_WITNESS)), [])


def main() -> None:
    all_pending_with_collect_accepted()
    all_pending_without_collect_refused()
    collect_must_be_whole_and_cover_the_files()
    excuse_is_one_reader_in_three_places()
    the_collect_door_is_open_to_the_guard()
    one_runnable_needs_run_witness()
    collect_is_no_run_witness()
    unchanged_roads()
    finish("check witness")


if __name__ == "__main__":
    main()
