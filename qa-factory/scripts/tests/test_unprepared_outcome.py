"""t-1955 N3 (B-18): an unprepared manual case always has an outcome the runner's own tool writes (`manual_evidence.py unprepared`).
Fast: no browser, no network. Two worlds: the scaffold task with a fake controller (the command and its refusals), and a real
event-store task (finalize, the exit check)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parents[0]))
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(TESTS / "fixtures" / "manual-evidence"))
import scaffold as S  # noqa: E402
import manual_evidence as M  # noqa: E402
import manual_capture as MC  # noqa: E402
import finalize_task as F  # noqa: E402
from event_store import EventStore, atomic_json  # noqa: E402

PKG = TESTS.parents[1]
REASON = "the plan gives the check an evidence rule that is not one word"
SNAPSHOT = "f" * 64


def jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def step_rows(*stamps):
    return [{"at": at, "command": "ui", "step": f"click {i}", "outcome": "ok", "detail": ""} for i, at in enumerate(stamps, 1)]


def written(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))["manual_checks"][0]


class Scaffolded(unittest.TestCase):
    """The scaffold task (case TC_007 is in the running S6 dispatch's scope) with an unprepared request."""

    def setUp(self):
        self.t = S.make_task(manual=("ui",))
        self.case = S.CASES["ui"]
        atomic_json(M.request_path(self.t.task, self.case),
                    {"case": self.case, "unprepared": {"reason": REASON, "door": "d", "obligation_ids": ["OB-7"],
                                                       "source_revision": S.SOURCE, "gate_a_decision_ref": "gateA-1"}})
        self.patch = self.t.patched()
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        S.cleanup(self.t)

    def attempt(self, name, rows=(), probes=(), surprises=(), env_blocked=False):
        folder = self.t.attempt_dir(self.case, name)
        folder.mkdir(parents=True, exist_ok=True)
        if rows:
            jsonl(folder / "steps.jsonl", rows)
        if probes:
            jsonl(folder / "probes.jsonl", probes)
        if surprises:
            jsonl(folder / "surprises.jsonl", surprises)
        if env_blocked:
            atomic_json(folder / "env_blocked.json", {"id": self.case, "probe_line": "p", "remedy": "r", "owner": "user"})
        return folder

    def blocks(self):
        return sorted((self.t.task / "work" / "manual-blocks").glob("*.json")) if (self.t.task / "work" / "manual-blocks").is_dir() else []

    def refused(self, fragment, *args, **kwargs):
        with self.assertRaises(ValueError) as caught:
            M.write_unprepared(self.t.task, self.case, *args, **kwargs)
        self.assertIn(fragment, str(caught.exception))
        return str(caught.exception)

    # --- the record -------------------------------------------------------------------------------------------------------
    def test_write_unprepared_walked_record_shape(self):
        self.attempt("a1", step_rows("2026-10-01T10:00:01+00:00"))
        self.attempt("a2", step_rows("2026-10-01T10:05:00+00:00", "2026-10-01T10:07:00+00:00"),
                     probes=[{"at": "2026-10-01T10:04:00+00:00", "when": "before"}, {"at": "2026-10-01T10:08:00+00:00", "when": "after"}])
        self.attempt("a3")      # an attempt with no step is no walk
        record = written(M.write_unprepared(self.t.task, self.case, []))
        self.assertEqual(record["attempt_id"], "a2")
        self.assertEqual((record["attempt_started_at"], record["attempt_ended_at"]),
                         ("2026-10-01T10:04:00+00:00", "2026-10-01T10:08:00+00:00"))
        self.assertEqual(record["unprepared"], {"reason": REASON, "walked": True})
        self.assertEqual((record["obligation_ids"], record["source_revision"], record["observations"], record["dispatch_id"]),
                         (["OB-7"], S.SOURCE, [], "S6-qa-runner-1"))
        self.assertNotIn("result", record)
        self.assertNotIn("then_quotes", record)

    def test_walked_carries_recorder_surprises(self):
        self.attempt("a1", step_rows("2026-10-01T10:00:01+00:00"),
                     surprises=[{"line": "surprise", "id": "a1-ui-S1", "step": 1, "kind": "extra_request", "fact": "an extra GET"}])
        obs = [{"step": 1, "expected": "x", "seen": "y", "evidence": "e", "quote": "q", "surprise": "a1-ui-S1"}]
        record = written(M.write_unprepared(self.t.task, self.case, obs))
        self.assertEqual([s["id"] for s in record["surprises"]], ["a1-ui-S1"])
        self.assertIn("surprise_detection", record)
        self.assertEqual(record["observations"], obs)

    def test_write_unprepared_not_walked_carries_reason(self):
        record = written(M.write_unprepared(self.t.task, self.case, [], not_walked="  the page\n never   opened "))
        self.assertEqual(record["unprepared"], {"reason": REASON, "walked": False, "not_walked": "the page never opened"})
        self.assertNotIn("attempt_id", record)
        self.assertEqual(record["attempt_started_at"], record["attempt_ended_at"])
        long = written(M.write_unprepared(self.t.task, self.case, [], not_walked="x" * 400))
        self.assertEqual(len(long["unprepared"]["not_walked"]), M.NOT_WALKED_MAX)
        self.assertTrue(long["unprepared"]["not_walked"].endswith("…"))

    def test_not_walked_required_without_steps(self):
        self.refused("say why with --not-walked", [])
        self.assertEqual(self.blocks(), [])

    def test_not_walked_refused_with_steps(self):
        self.attempt("a1", step_rows("2026-10-01T10:00:01+00:00", "2026-10-01T10:00:02+00:00"))
        message = self.refused("leave --not-walked out", [], not_walked="I did not")
        self.assertIn("attempt a1 holds 2 step(s)", message)
        self.assertEqual(self.blocks(), [])

    def test_env_blocked_only_attempt_is_not_walked(self):
        self.attempt("a1", step_rows("2026-10-01T10:00:01+00:00"), env_blocked=True)      # the failed login step, then the row
        self.refused("say why with --not-walked", [])
        record = written(M.write_unprepared(self.t.task, self.case, [], not_walked="the login did not land"))
        self.assertFalse(record["unprepared"]["walked"])

    def test_no_running_dispatch_refused(self):
        self.t.state(dispatch_status="accepted")
        self.refused("no S6 dispatch is running", [], not_walked="why")
        self.assertEqual(self.blocks(), [])

    def test_case_outside_dispatch_scope_refused(self):
        self.t.state(scope=[S.CASES["api"]])
        self.refused("no S6 dispatch is running", [], not_walked="why")
        self.assertEqual(self.blocks(), [])

    def test_prepared_case_refused(self):
        M.prepare_to_file(self.t.task, self.case, ["OB-7"])         # a prepared request holds no `unprepared`
        self.refused("was prepared", [], not_walked="why")
        atomic_json(M.request_path(self.t.task, self.case), {"refused": {"reason": "not yours", "door": "d"}})
        self.refused("not prepared", [], not_walked="why")
        self.assertEqual(self.blocks(), [])

    def test_blank_not_walked_refused(self):
        code, out, err = S.run(["unprepared", "--task-root", str(self.t.task), "--case", self.case, "--not-walked", "  "],
                               main=M.main, command="manual_evidence.py unprepared")
        self.assertNotEqual(code, 0)
        self.assertIn("say why it was not walked", err + out)
        self.assertEqual(self.blocks(), [])

    def test_observations_file_read_by_unprepared(self):
        self.assertIn("unprepared", M.OBSERVATION_FILE_COMMANDS)
        obs = [{"step": 1, "expected": "a", "seen": "b", "evidence": "c", "quote": "d"}]
        path = self.t.task / "obs.json"
        path.write_text(json.dumps(obs), encoding="utf-8")
        code, out, err = S.run(["unprepared", "--task-root", str(self.t.task), "--case", self.case, "--observations-file", str(path),
                                "--not-walked", "no recorder"], main=M.main, command="manual_evidence.py unprepared")
        self.assertEqual(code, 0, err)
        self.assertEqual(written(self.t.task / json.loads(out)["block"])["observations"], obs)
        path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
        code, out, err = S.run(["unprepared", "--task-root", str(self.t.task), "--case", self.case, "--observations-file", str(path),
                                "--not-walked", "no recorder"], main=M.main, command="manual_evidence.py unprepared")
        self.assertNotEqual(code, 0)
        self.assertIn("must hold a JSON list", err + out)

    def test_write_block_missing_key_is_valueerror(self):
        record = {"schema_version": 2, "case": self.case, "obligation_ids": ["OB-7"], "unprepared": {"reason": REASON},
                  "observations": []}
        with self.assertRaises(ValueError) as caught:
            M.write_block(self.t.task, [record], declared=True)
        for key in ("dispatch_id", "attempt_started_at", "attempt_ended_at", "source_revision"):
            self.assertIn(key, str(caught.exception))

    def test_a_second_call_writes_a_second_block(self):
        first = M.write_unprepared(self.t.task, self.case, [], not_walked="one")
        second = M.write_unprepared(self.t.task, self.case, [], not_walked="two")
        self.assertNotEqual(first, second)
        self.assertEqual(len(self.blocks()), 2)

    # --- the readers ------------------------------------------------------------------------------------------------------
    def test_unprepared_rows_carry_walked(self):
        marker_walked = {"reason": "r", "walked": True}
        marker_not = {"reason": "r", "walked": False, "not_walked": "no recorder"}
        marker_old = {"reason": "r"}
        report = {"current_manual_checks": [{"case": "A", "unprepared": marker_walked}, {"case": "B", "unprepared": marker_not},
                                            {"case": "C", "unprepared": marker_old}]}
        rows = {r["case"]: r for r in M.unprepared_rows(report)}
        self.assertEqual((rows["A"]["walked"], "not_walked" in rows["A"]), (True, False))
        self.assertEqual((rows["B"]["walked"], rows["B"]["not_walked"]), (False, "no recorder"))
        self.assertNotIn("walked", rows["C"])          # a record made before N3 says nothing

    def test_left_item_says_not_walked(self):
        import check_delivery as D
        base = {"case": "TC-7", "reason": "the evidence rule is not one word"}
        walked = D.unprepared_records({"unprepared_walks": [dict(base, walked=True)]})[0]["to_check"]
        old = D.unprepared_records({"unprepared_walks": [base]})[0]["to_check"]
        self.assertEqual(walked, old)
        self.assertNotIn("not walked", walked)
        text = D.unprepared_records({"unprepared_walks": [dict(base, walked=False, not_walked="the page never opened")]})[0]["to_check"]
        self.assertIn("not walked: the page never opened", text)
        self.assertIn("the evidence rule is not one word", text)

    def test_vocabulary_has_unprepared_walk(self):
        text = (PKG / "handoffs" / "vocabulary.yaml").read_text(encoding="utf-8")
        line = next(ln for ln in text.splitlines() if ln.strip().startswith("unprepared_walk:"))
        self.assertIn("qa-runner", line)
        self.assertIn("manual_evidence.py unprepared", line)
        self.assertTrue(text.index(line) > text.index("row_states:"))

    def test_prompt_line_names_the_command(self):
        import inspect
        import story_run
        source = inspect.getsource(story_run.Driver.run_manual_lane)      # TR3-9 C1 moved the prompt lines from run_manual_block to the lane
        for needle in ("manual_evidence.py unprepared --task-root", "--observations-file <file>", "--not-walked", "record no pass or fail",
                       "record every doubtful place"):
            self.assertIn(needle, source)


class Finalized(unittest.TestCase):
    """The record written by the command reaches the run report, and the exit check accepts the case (control: without it, no)."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.task = Path(self.td.name)
        from test_coverage_contract import obligation
        ob = obligation("O-U", "manual-agent")
        ob["evidence_policy"] = "ui"
        atomic_json(self.task / "work/test-plan.json", [{"id": "TS-1", "schema_version": 2, "coverage_obligations": [ob]}])
        atomic_json(self.task / "state/story-case-links.json", {"links": [{"case_id": "TC-1", "version": "cv_1"}]})
        store = EventStore(self.task)
        store.commit("initialize", {"source_revision": SNAPSHOT, "scope": ["TC-1"]}, "init")
        store.commit("dispatch", {"id": "d1", "stage": "S6", "role": "qa-runner", "scope": ["TC-1"]}, "d1")
        atomic_json(MC.case_root(self.task, "TC-1") / "request.json",
                    {"case": "TC-1", "unprepared": {"reason": REASON, "door": "d", "obligation_ids": ["O-U"]}})

    def tearDown(self):
        self.td.cleanup()

    def report(self):
        F.refresh(self.task)
        return json.loads((self.task / "work/run-report.json").read_text(encoding="utf-8"))

    def test_finalize_carries_record_into_current_manual_checks(self):
        M.write_unprepared(self.task, "TC-1", [], not_walked="the page never opened")
        rows = self.report()["current_manual_checks"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["unprepared"]["walked"], False)
        self.assertNotIn("result", rows[0])
        self.assertEqual(rows[0]["source_revision"], SNAPSHOT)       # the marker holds none: the controller's own
        self.assertEqual(M.unprepared_rows(self.report())[0]["not_walked"], "the page never opened")

    def test_exit_check_accepts_unprepared_case(self):
        import validate_artifacts as V
        patches = (mock.patch.object(V.C, "load_json", return_value={}), mock.patch.object(V.C, "manifest_tests", return_value=[]),
                   mock.patch.object(V.C, "parse_plan", return_value=[{"ts": "TS-1", "disposition": "manual-agent"}]),
                   mock.patch.object(V.C, "case_index", return_value={"TC-1": {"plan_row": "TS-1"}}),
                   mock.patch.object(V, "_s6_runner_half", return_value=("manual", ["TC-1"])))

        def exit_check(report):
            errors = []
            path = self.task / "work" / "run-report.json"
            for p in patches:
                p.start()
            try:
                V.check_run_report_coverage(path, report, errors, [])
            finally:
                for p in patches:
                    p.stop()
            return errors

        control = exit_check({"results": [], "manual_checks": [], "current_manual_checks": []})
        self.assertEqual(len(control), 1)
        self.assertIn("TC-1", control[0])
        self.assertIn("An unprepared case is closed by `manual_evidence.py unprepared`", control[0])
        M.write_unprepared(self.task, "TC-1", [], not_walked="the page never opened")
        self.assertEqual(exit_check(self.report()), [])


if __name__ == "__main__":
    unittest.main()
