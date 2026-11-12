"""t-1508 R7: `s7_reorder.py` (start / finish / mark-fixed) and `contract._attempt_fits` with `carried_attempts`.

Keys (spec 5.7): K-R7-3 a move + a red `repair_verify` run on the CURRENT bytes -> the triage row is carried and `bind_triage`
binds it to the new attempt; K-R7-3b a run over the bytes of a REFUSED edit is not the run of a later clean move (no rerun ->
`no_run`; a report row with no `instance_code_sha` -> `no_run`); K-R7-4 a variant that changes a Then line -> refused, nothing
carried; K-R7-5 a green run -> refused (`green`); K-R7-6 `_attempt_fits`: without `carried_attempts` as before, with it only an
attempt the failure itself has; K-R7-10 `finish` without `start` -> refused; `reorder` without `blocked_thens` is a problem; an
open snapshot is kept across a refused round and its `seen_attempts` are refreshed; `mark-fixed` marks only a carried row;
a carried round is resumed (`carried_round`) until the critic sends it back (`send_back`); the project is found by its marker
(`artifact_root` configurable).
Mutants: no `carried_attempts` condition -> K-R7-3 / K-R7-6; no `variant_shape` -> K-R7-4; no green check -> K-R7-5; no
`instance_code_sha` comparison in `finish` -> K-R7-3b; no `seen_attempts` refresh in `start` -> the refresh key; `repo_of` by
`parents[2]` -> the artifact_root key.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness import check, check_eq, check_in, finish  # noqa: E402

import contract as C  # noqa: E402
import execution_request as ER  # noqa: E402
import s7_reorder as R  # noqa: E402
import test_probe_binding as TPB  # noqa: E402  (the job fixture: a stored author request)

IID = "test_move"
BEFORE = ('def test_move():\n    r = call()\n    assert r.a == 1  # Then 1\n    assert r.b == 2  # Then 2\n'
          '    assert r.c == 3  # Then 3\n')
MOVED = ('def test_move():\n    r = call()\n    assert r.a == 1  # Then 1\n    assert r.c == 3  # Then 3\n'
         '    assert r.b == 2  # Then 2\n')
CHANGED = BEFORE.replace("r.c == 3", "r.c == 4")
ROW = {"instance_id": IID, "test": IID, "case": "TC-1", "verdict": "APP_BUG", "attempt_id": "a1", "reorder": True,
       "blocked_thens": [{"then": 3, "blocking_check": "TC-9", "detail": "behind the red"}]}
FIXTURES: list = []


def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((value if isinstance(value, str) else json.dumps(value)).encode("utf-8"))  # LF, as written


class Story:
    """A project with `qa-factory/config.json`, a stored author job of the test (the identity the producer measured) and the
    story's manifest, triage and run report."""

    def __init__(self, row: dict | None = None):
        self.fix = TPB.Fixture({"tests/test_x.py": BEFORE},
                               [TPB.row(IID, "TC-1", "tests/test_x.py", f"tests/test_x.py::{IID}", test=IID)])
        FIXTURES.append(self.fix)
        self.repo, self.task = self.fix.root, self.fix.task
        self.request = self.fix.job(["TC-1"])["request"]
        write(self.task / "work" / "triage.json", {"triage": [row or dict(ROW)]})
        write(self.task / "work" / "run-report.json", {"results": [
            {"instance_id": IID, "status": "failed", "attempt_id": "a1", "purpose": "initial"}]})

    def code_sha(self) -> str:
        """The identity of the test as the file holds it now - the producer's own measurer."""
        return ER.instance_shas(self.repo, self.request, IID)["instance_code_sha"]

    def test_file(self, text: str) -> None:
        write(self.repo / "tests" / "test_x.py", text)

    def run_verify(self, attempt: str, status: str, sha: bool = True) -> None:
        report = json.loads((self.task / "work" / "run-report.json").read_text(encoding="utf-8"))
        row = {"instance_id": IID, "status": status, "attempt_id": attempt, "purpose": "repair_verify"}
        if sha:
            row["instance_code_sha"] = self.code_sha()
        report["results"].append(row)
        write(self.task / "work" / "run-report.json", report)

    def triage_row(self) -> dict:
        return json.loads((self.task / "work" / "triage.json").read_text(encoding="utf-8"))["triage"][0]

    def snapshot(self) -> dict:
        return json.loads(R.snapshot_path(self.task, IID).read_text(encoding="utf-8"))


def refused(kind: str, fn, *args):
    try:
        fn(*args)
    except R.ReorderRefused as exc:
        return exc.kind == kind, str(exc)
    return False, "no refusal"


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="s7reorder-"))
    try:
        # K-R7-10: finish without start
        s = Story()
        ok, text = refused("no_snapshot", R.finish, s.task, IID, s.repo)
        check("K-R7-10: finish without start is refused", ok, text)
        check_in("K-R7-10: and names the door", "s7_reorder.py start", text)

        # K-R7-3: a move and a red run on the current bytes are carried; the new attempt binds
        s = Story()
        task, repo = s.task, s.repo
        started = R.start(task, IID, repo)
        check_eq("start writes the snapshot", started["status"], "started")
        s.test_file(MOVED)
        ok, text = refused("no_run", R.finish, task, IID, repo)
        check("a round with no new repair_verify run is refused", ok, text)
        s.run_verify("a2", "failed")
        done = R.finish(task, IID, repo)
        check_eq("K-R7-3: carried to the new attempt", done["status"], "carried")
        row = s.triage_row()
        check_eq("K-R7-3: carried_attempts holds the new attempt", row.get("carried_attempts"), ["a2"])
        check_eq("K-R7-3: carried_by names the script", row.get("carried_by"), "s7_reorder")
        check_eq("K-R7-3: the row keeps its own attempt evidence", row.get("attempt_id"), "a1")
        check_in("the review reason is the registered one", "S7 reorder review: test_move", done["critic"]["reason"])
        check("the review reason never starts with S7 fix", not done["critic"]["reason"].startswith("S7 fix"))
        report = {"current_results": [{"instance_id": IID, "status": "failed", "attempt_id": "a2"}],
                  "results": [{"instance_id": IID, "status": "failed", "attempt_id": "a2"}]}
        failures, _ = C.triage_failures(report)
        bound = C.bind_triage(failures, [row])["matched"]
        check("K-R7-3: bind_triage binds the carried row to the new attempt", any(bound.values()), str(bound))
        plain = dict(row)
        del plain["carried_attempts"]
        check("K-R7-6: without carried_attempts the same row does not bind the new attempt",
              not any(C.bind_triage(failures, [plain])["matched"].values()))
        other = {"current_results": [{"instance_id": "other", "status": "failed", "attempt_id": "a9"}]}
        failures_other, _ = C.triage_failures(other)
        check("K-R7-6: a carried id of another instance's attempt does not fit it",
              not C._attempt_fits(failures_other[("result", "other")], row))
        check("K-R7-6: the failure that has the carried attempt fits", C._attempt_fits(failures[("result", IID)], row))

        # the carried round is resumed straight to the critic until the critic sends it back
        again = R.carried_round(task, IID, repo)
        check("carried_round: a carried, unjudged round at the same bytes is resumed", bool(again) and again["attempt"] == "a2",
              str(again))
        check_in("carried_round: only the critic is registered", "qa-code-critic", again["critic"]["command"])
        s.test_file(MOVED + "# touched\n")
        check("carried_round: other bytes than the round's are a new round", R.carried_round(task, IID, repo) is None)
        s.test_file(MOVED)
        check("carried_round: the bytes back, the round is resumed again", R.carried_round(task, IID, repo) is not None)
        check("send_back closes a carried snapshot", R.send_back(task, IID) is True)
        check("carried_round: a round the critic sent back is not resumed", R.carried_round(task, IID, repo) is None)
        check("send_back: nothing to close the second time", R.send_back(task, IID) is False)
        started = R.start(task, IID, repo)
        check_eq("start after a sent-back round takes a NEW snapshot", started["status"], "started")

        # mark-fixed: only a row carried by this script (CLI and function)
        s = Story()
        check("mark_fixed leaves a row nobody carried alone", R.mark_fixed(s.task, IID) is False)
        check("... and writes nothing", "fix_result" not in s.triage_row())
        check_eq("mark-fixed CLI refuses a row that is not carried (exit 2)",
                 R.main(["mark-fixed", "--task-root", str(s.task), "--instance", IID]), 2)
        check("... and the row stays unmarked", "fix_result" not in s.triage_row())
        R.start(s.task, IID, s.repo)
        s.test_file(MOVED)
        s.run_verify("a2", "failed")
        R.finish(s.task, IID, s.repo)
        check_eq("mark-fixed CLI marks a carried row (exit 0)",
                 R.main(["mark-fixed", "--task-root", str(s.task), "--instance", IID]), 0)
        check_eq("... fix_result: fixed", s.triage_row().get("fix_result"), "fixed")
        check("carried_round: a judged (marked) round is not resumed", R.carried_round(s.task, IID, s.repo) is None)

        # K-R7-3b: the run of a REFUSED edit is not the run of the later clean move (spec 5.7 edge invariant)
        s = Story()
        R.start(s.task, IID, s.repo)
        s.test_file(CHANGED)
        s.run_verify("a2", "failed")
        ok, text = refused("shape", R.finish, s.task, IID, s.repo)
        check("K-R7-3b: round 1 (a Then changed, run a2) is refused for its shape", ok, text)
        s.test_file(MOVED)  # round 2: the author puts it back and only moves lines - and does NOT re-run; `start` is not called
        ok, text = refused("no_run", R.finish, s.task, IID, s.repo)
        check("K-R7-3b: a clean move with no re-run is no_run (the run a2 went over other bytes)", ok, text)
        check_in("K-R7-3b: the refusal says to re-run on the new bytes", "re-run only this test on the new bytes", text)
        check("K-R7-3b: nothing is carried", "carried_attempts" not in s.triage_row())
        # with `start` called in between (the kept snapshot refreshes the runs seen) the same holds
        check_eq("kept snapshot", R.start(s.task, IID, s.repo)["status"], "kept")
        check_in("start refreshes seen_attempts on a kept snapshot", "a2", s.snapshot().get("seen_attempts"))
        check_eq("... the before-bytes stay the first ones", s.snapshot()["before_text"], BEFORE)
        ok, text = refused("no_run", R.finish, s.task, IID, s.repo)
        check("K-R7-3b: still no_run after start", ok, text)
        s.run_verify("a3", "failed")
        done = R.finish(s.task, IID, s.repo)
        check_eq("K-R7-3b: after a run on the new bytes the row is carried to a3", done["attempt"], "a3")
        check_eq("K-R7-3b: and only a3", s.triage_row().get("carried_attempts"), ["a3"])

        # B2 edges: a report row with no instance_code_sha is no_run (error toward refusal)
        s = Story()
        R.start(s.task, IID, s.repo)
        s.test_file(MOVED)
        s.run_verify("a2", "failed", sha=False)
        ok, text = refused("no_run", R.finish, s.task, IID, s.repo)
        check("a run row with no instance_code_sha is no_run", ok, text)
        check_in("... and the door is the re-run", "re-run only this test on the new bytes", text)
        # a test that no stored job names cannot be measured: no_run, not a carry
        for job in (s.task / "state" / "execution-jobs").glob("*"):
            shutil.rmtree(job, ignore_errors=True) if job.is_dir() else job.unlink()
        s.run_verify("a3", "failed", sha=False)
        ok, text = refused("no_run", R.finish, s.task, IID, s.repo)
        check("an unmeasurable identity is no_run", ok, text)
        check_in("... and says it cannot be measured", "cannot be measured", text)

        # K-R7-4: a changed Then line is refused, nothing carried; the open snapshot is kept for the next round
        s = Story()
        R.start(s.task, IID, s.repo)
        s.test_file(CHANGED)
        s.run_verify("a2", "failed")
        ok, text = refused("shape", R.finish, s.task, IID, s.repo)
        check("K-R7-4: a changed Then line is refused", ok, text)
        check_in("K-R7-4: the refusal says a reorder only moves asserts", "a reorder only moves asserts", text)
        check("K-R7-4: nothing is carried", "carried_attempts" not in s.triage_row())
        again = R.start(s.task, IID, s.repo)
        check_eq("an open snapshot is kept (the 'before' stays the first bytes)", again["status"], "kept")
        s.test_file(BEFORE.replace("r.b == 2", "r.b == 2  # x"))
        check("an edited line is a shape refusal too", refused("shape", R.finish, s.task, IID, s.repo)[0])

        # K-R7-5: a green run is refused
        s = Story()
        R.start(s.task, IID, s.repo)
        s.test_file(MOVED)
        s.run_verify("a2", "passed")
        ok, text = refused("green", R.finish, s.task, IID, s.repo)
        check("K-R7-5: a green repair_verify run is refused", ok, text)
        check_in("K-R7-5: it says what changed", "never turns a red by a product bug green", text)
        check("K-R7-5: nothing is carried", "carried_attempts" not in s.triage_row())

        # a reorder with no blocked_thens is a problem, and start refuses it
        s = Story({"instance_id": IID, "test": IID, "case": "TC-1", "verdict": "APP_BUG", "reorder": True})
        check("reorder without blocked_thens is a problem", bool(R.row_problems(s.triage_row())))
        ok, text = refused("bad_row", R.start, s.task, IID, s.repo)
        check("start refuses a reorder with no blocked_thens", ok, text)
        check_eq("a row without reorder has no problem", R.row_problems({"instance_id": IID}), [])
        # tail B1 (t-1564): `reorder: false` is no request (the null-outcome view reads it so), not a malformed one
        check_eq("`reorder: false` is no request: no problem, as with the key absent", R.row_problems({"instance_id": IID, "reorder": False}), [])
        check("`reorder: 0` is still malformed (only the boolean false is 'no request')", bool(R.row_problems({"instance_id": IID, "reorder": 0})))

        # F3: the project is found by its marker, not by the shape of the path (artifact_root is configurable)
        proj = root / "p"
        write(proj / "qa-factory" / "config.json", {"artifact_root": "qa/stories"})
        deep = proj / "qa" / "stories" / "T-1"
        write(deep / "work" / "automation-manifest.json", {"tests": [{
            "case": "TC-1", "covers": ["TC-1"], "instance_id": IID, "test": IID, "selector": f"tests/test_x.py::{IID}"}]})
        write(deep / "work" / "triage.json", {"triage": [dict(ROW)]})
        write(proj / "tests" / "test_x.py", BEFORE)
        write(proj.parent / "tests" / "test_x.py", "def test_move():\n    pass\n")  # the file parents[2] would have read
        check_eq("repo_of: the marker's folder with artifact_root qa/stories", R.repo_of(deep), proj.resolve())
        got = R.start(deep, IID)
        check_eq("start reads the project's own file with a configured artifact_root", got["status"], "started")
        check_eq("... its snapshot holds the project's bytes",
                 json.loads(R.snapshot_path(deep, IID).read_text(encoding="utf-8"))["before_text"], BEFORE)
        lone = root / "nomarker" / "a" / "b" / "T-2"
        lone.mkdir(parents=True)
        ok, text = refused("unreadable", R.repo_of, lone)
        check("no project marker above the story: unreadable", ok, text)
        check_in("... and the door is --repo", "--repo", text)
    finally:
        for fix in FIXTURES:
            fix.close()
        shutil.rmtree(root, ignore_errors=True)
    return finish("test_s7_reorder")


if __name__ == "__main__":
    sys.exit(main())
