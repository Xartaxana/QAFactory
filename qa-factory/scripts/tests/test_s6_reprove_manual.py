"""HF8-18 N2: S6 with a manual half proves the stale live checks again, once per byte state, before the first manual block.

`Driver.s6_reprove_before_manual` (called from `stage_S6` when the automation runner is accepted, a manual half is still to
run and no manual block is done): the stale live checks (`proof_level.staleness`, replaced by the rig of `test_story_run_s6`)
go through `s6_reprove` in the close context `--s6-close`; the mark `s6_reproved` is `{instance id: <input_hash>:<instance_content_sha>}`
(the byte state `same_test` judges, B1); the mark `s6_manual_runner` (set by `stage_S6` when the runner returns, dropped here) says
the runner of THIS life is accepted - `here`, B2; nothing is closed here. The scenarios are in-process, no model and no network; `probe_by_code.py` is answered by the rig.

Mutations and their one killing file (this one): M-C3 the manual-half condition removed or inverted -> C-K1 / the no-manual
control; M-C4 the proofs after the manual block instead of before it -> C-K1 (the order of moves), and the proofs before the runner
is accepted -> `the_runner_comes_first_and_leaves_its_mark`; M-C4a the mark by dispatch id instead of the byte state -> C-K2 / C-K2a /
B1; `here` always true -> B2 rows.
"""
import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from story_run_common import (D1Evidence, check, check_in, check_not_in, d1_answer, d2_seed,  # noqa: E402
                              eq, run_scenarios)
from test_story_run_s6 import (ACCEPTED_S6, REPLAY_A, REPLAY_B, WHY_RUN, Staleness, d1_blocks, pin_project,  # noqa: E402
                               reprobe_rig, row, stale_probe, unpin_project)

TASK = "QA-9"
TWO = {"test_a": ("result", "passed", ""), "test_b": ("result", "failed", "")}
BOTH = {"test_a": row(("fresh", ""), stale_probe(REPLAY_A)), "test_b": row(("fresh", ""), stale_probe(REPLAY_B))}
ACCEPTED_MANUAL = dict(ACCEPTED_S6, **{"S6-qa-runner-2": {"id": "S6-qa-runner-2", "stage": "S6", "status": "accepted",
                                                         "execution_kind": "manual", "manual_case_ids": ["TC-9"],
                                                         "scope": ["TC-9"]}})


def entered(driver, answer, moves):
    """One entry into S6 under the rig: the manual block is a move too (`("manual", cases)`), the driver's prints are returned."""
    driver.run_manual_block = lambda cases: moves.append(("manual", list(cases)))
    out = io.StringIO()
    with contextlib.redirect_stdout(out), D1Evidence(d1_answer(TWO)), Staleness(answer):
        driver.stage_S6()
    return out.getvalue()


def world():
    root, task_root, env = d2_seed(TASK, environment="Local", pending=False)
    d1_blocks(root, task_root)
    return root, task_root, env


def proofs_come_before_the_manual_block_once_per_byte_state() -> None:
    """C-K1, C-K2, C-K2a, the old mark, nothing closed here (C-1)."""
    root, task_root, env = world()
    pin = pin_project(root)
    try:
        driver, launched, moves, probes, sites = reprobe_rig(root, env, TASK, dispatches=ACCEPTED_S6, manual=("TC-9",))
        entered(driver, BOTH, moves)
        eq("C-K1 two stale live checks, a manual half: two proofs, THEN the manual block (M-C4); nothing finalized or closed",
           ([m[0] for m in moves], launched, sites), (["probe", "probe", "manual"], [], []))
        eq("C-K1 each proof is in the close context `--s6-close` (no running dispatch), the replay of its record",
           probes[0], ["--task", TASK, "--s6-close", "--test", "tests/t.py::test_a", "--instance", "test_a", "--mutation", "invert", "--json"])
        eq("C-K1 ...the second names its oracle", probes[1][-5:], ["--mutation", "expected", "--json", "--oracle", "tests/helpers.py::expected_total"])
        marked = driver.state.get("s6_reproved")
        check("C-K1 the mark is `{iid: input_hash}` for both", isinstance(marked, dict) and sorted(marked) == ["test_a", "test_b"]
              and all(isinstance(v, str) and v for v in marked.values()), str(marked))

        # C-K2: the same bytes, the same life (the same driver state): not proved again (M-C4a: a mark by dispatch id would still say so,
        # the next key tells the two apart)
        before = len(probes)
        entered(driver, BOTH, moves)
        eq("C-K2 the same bytes: no new proof, the manual block comes", (len(probes), moves[-1][0]), (before, "manual"))

        # C-K2a: the same last accepted automation id, the test file edited: the bytes moved, the proofs go again
        test_file = Path(root) / "tests" / "t.py"
        test_file.write_text(test_file.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
        entered(driver, BOTH, moves)
        eq("C-K2a a second life, same last accepted id, other bytes: the proofs go again (M-C4a)", len(probes), before + 2)
        entered(driver, BOTH, moves)
        eq("C-K2a ...and once more for the same new bytes: no", len(probes), before + 2)

        # a mark of the old shape (a string) reads as `none yet`
        driver, launched, moves, probes, sites = reprobe_rig(root, env, TASK, dispatches=ACCEPTED_S6, manual=("TC-9",))
        driver.state["s6_reproved"] = "S6-qa-runner-1"
        entered(driver, BOTH, moves)
        eq("C-9 an old-format mark (a string): read as none, the proofs go", len(probes), 2)

        # C-1: after a manual block was done the proofs are not made again, and with no manual half it is the re-entry's work
        driver, launched, moves, probes, sites = reprobe_rig(root, env, TASK, dispatches=ACCEPTED_MANUAL, manual=("TC-9",))
        entered(driver, BOTH, moves)
        eq("C-1 a manual block is already done: no proof after it", probes, [])
    finally:
        unpin_project(pin)
        harness.cleanup(root)


def no_manual_half_is_the_old_path() -> None:
    """The control of M-C3: with no manual half this entry makes no proof of its own (`s6_reentry` owns it, as before)."""
    root, task_root, env = world()
    pin = pin_project(root)
    try:
        driver, launched, moves, probes, sites = reprobe_rig(root, env, TASK, dispatches=ACCEPTED_S6)
        entered(driver, {"test_a": row(), "test_b": row()}, moves)
        eq("no stale check, no manual half: nothing happens", (probes, [m[0] for m in moves]), ([], []))
        driver, launched, moves, probes, sites = reprobe_rig(root, env, TASK, dispatches=ACCEPTED_S6, manual=("TC-9",))
        entered(driver, {"test_a": row(), "test_b": row()}, moves)
        eq("nothing stale with a manual half: no proof, the manual block comes", (probes, [m[0] for m in moves]), ([], ["manual"]))
    finally:
        unpin_project(pin)
        harness.cleanup(root)


def edges_no_stand_unrun_unknown_and_a_failed_proof() -> None:
    """C-K3, C-K4, C-K4a, C-K9."""
    root, task_root, env = world()
    pin = pin_project(root)
    try:
        # C-K3: no stand - no proof, the digest line, the manual block still comes
        driver, launched, moves, probes, sites = reprobe_rig(root, env, TASK, dispatches=ACCEPTED_S6, manual=("TC-9",))
        driver.s6_no_stand = lambda: True
        said = entered(driver, BOTH, moves)
        eq("C-K3 no stand: no proof", (probes, moves[-1][0]), ([], "manual"))
        check_in("C-K3 ...and the line says how many are left for a run elsewhere", driver.S6_LEFT.format(n=2), said)

        # C-K4: a stale RUN is never probed next to
        driver, launched, moves, probes, sites = reprobe_rig(root, env, TASK, dispatches=ACCEPTED_S6, manual=("TC-9",))
        said = entered(driver, {"test_a": row(("stale", WHY_RUN), stale_probe(REPLAY_A)), "test_b": row(("fresh", ""), stale_probe(REPLAY_B))},
                       moves)
        eq("C-K4 one run is stale: no proof at all", probes, [])
        check_in("C-K4 ...one line says why", "re-probe skipped: 1 tests have no run on their current bytes (test_a)", said)
        eq("C-K4 ...and the manual block comes", moves[-1][0], "manual")
        entered(driver, {"test_a": row(("stale", WHY_RUN), stale_probe(REPLAY_A)), "test_b": row(("fresh", ""), stale_probe(REPLAY_B))}, moves)
        eq("C-K4 a skip makes no mark: the next entry asks again", driver.state.get("s6_reproved"), None)

        # C-K4a: an `unknown` run (a runner that records no identity) does not stop the proofs IN THE LIFE the runner ran in: the mark
        # `s6_manual_runner` names it (set by `stage_S6` when the runner returns), it is accepted - `here`
        unknown = {"test_a": row(("unknown", "the run recorded no per-test identity"), stale_probe(REPLAY_A)),
                   "test_b": row(("unknown", "the run recorded no per-test identity"), stale_probe(REPLAY_B))}
        driver, launched, moves, probes, sites = reprobe_rig(root, env, TASK, dispatches=ACCEPTED_S6, manual=("TC-9",))
        driver.state["s6_manual_runner"] = "S6-qa-runner-1"
        entered(driver, unknown, moves)
        eq("C-K4a only `unknown` runs, the runner of this life accepted: the proofs go (a non-pytest runner)", len(probes), 2)
        eq("B2 the mark of the runner is dropped by N2 on its way out", "s6_manual_runner" in driver.state, False)

        # B2: a SECOND life (no mark: `invalidate` leaves earlier dispatches accepted, nothing says the runner ran in this one): `unknown` is
        # no license - one line, no proof; the twin `s6_reentry` pins the same (test_story_run_s6.py, "second life")
        driver, launched, moves, probes, sites = reprobe_rig(root, env, TASK, dispatches=ACCEPTED_S6, manual=("TC-9",))
        driver.state.pop("s6_reproved", None)
        said = entered(driver, unknown, moves)
        eq("B2 second life, `unknown` runs, no mark: no proof, the manual block comes", (probes, moves[-1][0]), ([], "manual"))
        check_in("B2 ...and one line says why", "re-probe skipped: 2 tests have no run on their current bytes (test_a, test_b)", said)
        # ...a mark naming a dispatch that is NOT accepted (the runner never returned) is no license either
        driver, launched, moves, probes, sites = reprobe_rig(root, env, TASK, dispatches=ACCEPTED_S6, manual=("TC-9",))
        driver.state.pop("s6_reproved", None)
        driver.state["s6_manual_runner"] = "S6-qa-runner-7"
        entered(driver, unknown, moves)
        eq("B2 a mark that names no accepted dispatch: no proof", probes, [])
        # ...while rows that are fresh in a second life still probe (C-K2a)
        driver, launched, moves, probes, sites = reprobe_rig(root, env, TASK, dispatches=ACCEPTED_S6, manual=("TC-9",))
        driver.state.pop("s6_reproved", None)
        entered(driver, BOTH, moves)
        eq("B2 second life, fresh runs, no mark: the proofs go", len(probes), 2)

        # C-K9: one proof fails: one line, the other goes, the manual block comes
        def reply(argv):
            if argv[argv.index("--instance") + 1] == "test_a":
                return 2, json.dumps({"status": "refused", "error": "the close context is not open"})
            return 0, json.dumps({"verdict": "intended_failure"})
        driver, launched, moves, probes, sites = reprobe_rig(root, env, TASK, dispatches=ACCEPTED_S6, manual=("TC-9",), reply=reply)
        driver.state.pop("s6_reproved", None)           # the mark of the scenario above lives in this story's state file
        said = entered(driver, BOTH, moves)
        eq("C-K9 a failed proof does not stop the other, nor the manual block", ([p[p.index("--instance") + 1] for p in probes], moves[-1][0]),
           (["test_a", "test_b"], "manual"))
        check_in("C-K9 ...it is one line with the tool's words", "test_a: not proved again (probe_by_code exit 2): the close context is not open", said)
        check_not_in("C-K9 ...and the other is not a line of failure", "test_b: not proved again", said)

        # AR-28: a reader that raises is printed, the manual block still comes
        driver, launched, moves, probes, sites = reprobe_rig(root, env, TASK, dispatches=ACCEPTED_S6, manual=("TC-9",))
        driver.state.pop("s6_reproved", None)
        driver.s6_reprove = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        said = entered(driver, BOTH, moves)
        check_in("AR-28 an exception is a line", "could not be proved again before the manual half (RuntimeError)", said)
        eq("AR-28 ...and the manual block comes", moves[-1][0], "manual")
    finally:
        unpin_project(pin)
        harness.cleanup(root)


@contextlib.contextmanager
def conftest_identity(root):
    """`proof_level.instance_identity` with a per-test identity whose content sha is the sha of `tests/conftest.py` - what `--mine` records
    for a test that reaches that conftest (`execution_request.instance_shas`, measured in `test_proof_level`); the rig has no job directory."""
    import hashlib
    import proof_level
    saved = proof_level.instance_identity

    def fake(entry, task_root, project=None):
        out = dict(saved(entry, task_root, project))
        conftest = Path(root) / "tests" / "conftest.py"
        sha = hashlib.sha256(conftest.read_bytes()).hexdigest() if conftest.is_file() else ""
        out["instance_identity"] = {"instance_content_sha": sha, "instance_code_sha": "c" * 8, "job_id": "j1"}
        return out
    proof_level.instance_identity = fake
    try:
        yield
    finally:
        proof_level.instance_identity = saved


def a_fixture_edit_is_a_new_byte_state() -> None:
    """B1: the mark is the byte state `same_test` judges (the test file AND the per-test content sha, which moves with a conftest the
    test reaches). A conftest edit with the same test file means the proofs go again; with no edit they do not. Kills: the mark by
    `input_hash` alone."""
    root, task_root, env = world()
    pin = pin_project(root)
    try:
        conftest = Path(root) / "tests" / "conftest.py"
        conftest.write_text("import pytest\n\n\n@pytest.fixture\ndef fx():\n    return 1\n", encoding="utf-8")
        with conftest_identity(root):
            driver, launched, moves, probes, sites = reprobe_rig(root, env, TASK, dispatches=ACCEPTED_S6, manual=("TC-9",))
            driver.state.pop("s6_reproved", None)
            entered(driver, BOTH, moves)
            check("B1 the mark holds the test sha AND the fixture's sha", all(v.count(":") == 1 and not v.endswith(":")
                  for v in (driver.state.get("s6_reproved") or {}).values()) and len(probes) == 2, str(driver.state.get("s6_reproved")))
            entered(driver, BOTH, moves)
            eq("B1 nothing edited: not proved again", len(probes), 2)
            conftest.write_text(conftest.read_text(encoding="utf-8").replace("return 1", "return 2"), encoding="utf-8")
            entered(driver, BOTH, moves)
            eq("B1 the conftest edited, the test file the same, both probes still stale: the proofs go again", len(probes), 4)
            entered(driver, BOTH, moves)
            eq("B1 ...and once for the same new bytes", len(probes), 4)
    finally:
        unpin_project(pin)
        harness.cleanup(root)


def the_runner_comes_first_and_leaves_its_mark() -> None:
    """F7 (a) M-C4: with NO accepted automation runner N2 makes no proof - the runner is launched (not closing the stage), the mark
    `s6_manual_runner` names it for the next entry. Kills: N2 placed before the runner is accepted."""
    root, task_root, env = world()
    pin = pin_project(root)
    try:
        driver, launched, moves, probes, sites = reprobe_rig(root, env, TASK, dispatches={}, manual=("TC-9",))
        driver.state.pop("s6_reproved", None)
        driver.last_dispatch = "S6-qa-runner-1"
        entered(driver, BOTH, moves)
        eq("M-C4 no accepted runner: the runner goes (complete=False) and no probe is made", ([e["complete"] for e in launched], probes), ([False], []))
        eq("B2 the runner's id is the mark, for the next entry", driver.state.get("s6_manual_runner"), "S6-qa-runner-1")
    finally:
        unpin_project(pin)
        harness.cleanup(root)


def the_layer_map_names_the_method() -> None:
    """C-K10: `driver-layers.json` holds the new method."""
    rows = json.loads((harness.FIXTURES / "driver-layers.json").read_text(encoding="utf-8"))
    names = [r.get("name") for r in (rows if isinstance(rows, list) else rows.get("rows") or rows.get("members") or [])]
    if not names:
        names = [m.group(1) for m in __import__("re").finditer(r'"name": "([^"]+)"', json.dumps(rows))]
    check("C-K10 driver-layers.json has `Driver.s6_reprove_before_manual`", "Driver.s6_reprove_before_manual" in names, str(names[:3]))


def main() -> None:
    run_scenarios([], [proofs_come_before_the_manual_block_once_per_byte_state, no_manual_half_is_the_old_path,
                       edges_no_stand_unrun_unknown_and_a_failed_proof, a_fixture_edit_is_a_new_byte_state,
                       the_runner_comes_first_and_leaves_its_mark, the_layer_map_names_the_method])
    harness.finish("test_s6_reprove_manual")


if __name__ == "__main__":
    main()
