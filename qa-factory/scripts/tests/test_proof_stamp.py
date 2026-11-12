"""t-2181 PC-5a (B2, F-14): the proof stamp - the sides an execution met, written by code on its execution block (run block and
manual block), copied by a reparse, carried by `finalize_task.reduce` onto the report rows, and the `about` a walk names (C11).

Run: python -B scripts/tests/test_proof_stamp.py"""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_suite as RS
import manual_evidence as M
import finalize_task as F
import test_manual_evidence as fixtures
from event_store import EventStore, content_hash, atomic_json
from test_coverage_contract import obligation

SIDES = {"ui": {"reality": "real", "deliverable": True}, "backend": {"reality": "substituted", "deliverable": False}}
JUNIT = ('<testsuite><testcase classname="t" name="a"/></testsuite>')


class Stamp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.task = Path(self.tmp.name)
        self.keep = RS.artifacts_dir
        RS.artifacts_dir = lambda task: self.task          # the story's folder, whatever the project root is
        self.addCleanup(setattr, RS, "artifacts_dir", self.keep)

    def pipeline(self, **fields):
        atomic_json(self.task / "pipeline.json", dict({"stages": {}}, **fields))

    def block(self, task="S-1"):
        request = {"purpose": "initial", "selected_instance_ids": ["i-1"],
                   "instance_contracts": {"i-1": {"report_test_id": "t::a"}}}
        if task:
            request["task"] = task
        return RS.build_run_block(request, {"results": [{"test_id": "t::a", "status": "passed"}], "execution_status": "passed"}, "a1")

    def test_run_block_on_a_story_with_sides_is_stamped(self):
        self.pipeline(sides=SIDES)
        block = self.block()
        self.assertEqual(block["sides_met"], {"ui": "real", "backend": "substituted"})
        self.assertNotIn("sides_unknown", block)

    def test_a_story_with_a_non_real_side_and_no_record_of_it_is_never_called_real(self):
        self.pipeline(sides={"ui": {"deliverable": True}})              # a row with no reality word reads unknown, never real
        self.assertEqual(self.block()["sides_met"], {"ui": ""})

    def test_all_real_story_with_no_pipeline_sides_gets_the_block_of_today_byte_for_byte(self):
        self.pipeline()
        stamped_path = json.dumps(self.block(), sort_keys=False, ensure_ascii=False)
        unnamed = json.dumps(self.block(task=""), sort_keys=False, ensure_ascii=False)       # a request with no story: the old path
        self.assertEqual(stamped_path, unnamed)
        self.assertNotIn("sides_met", stamped_path)
        self.assertNotIn("sides_unknown", stamped_path)

    def test_no_pipeline_file_leaves_the_block_unstamped(self):
        block = self.block()                                             # no pipeline.json at all: no record of the story to copy
        self.assertNotIn("sides_met", block)
        self.assertNotIn("sides_unknown", block)

    def test_a_present_but_unreadable_pipeline_is_unknown_never_the_default_real(self):
        for text in ("{not json", "[1, 2]", ""):
            (self.task / "pipeline.json").write_text(text, encoding="utf-8")
            block = self.block()
            self.assertIn("could not be read", block["sides_unknown"], text)
            self.assertNotIn("sides_met", block, text)                  # the reader's default (all real) is a guess, not copied

    def test_a_pipeline_with_a_bom_is_read_like_any_other(self):
        (self.task / "pipeline.json").write_bytes(b"\xef\xbb\xbf" + json.dumps({"sides": SIDES}).encode("utf-8"))
        block = self.block()
        self.assertEqual(block["sides_met"], {"ui": "real", "backend": "substituted"})
        self.assertNotIn("sides_unknown", block)

    def test_pipeline_sides_that_is_not_a_side_record_is_unknown(self):
        for bad in (["backend"], "backend", [], {}, 3):
            self.pipeline(sides=bad)
            block = self.block()
            self.assertEqual(block.get("sides_unknown"), "pipeline.sides is not a side record", bad)
            self.assertNotIn("sides_met", block, bad)
        self.assertEqual(RS.proof_stamp({"sides": ["backend"]}), {"sides_unknown": "pipeline.sides is not a side record"})
        self.assertEqual(RS.proof_stamp({"sides": "x", "sides_unknown": "the registry"}), {"sides_unknown": "the registry"})

    def test_sides_unknown_is_carried_as_unknown_never_as_real(self):
        self.pipeline(sides_unknown={"at": "2026-11-10T10:00:00", "why": "the registry could not be read"})
        block = self.block()
        self.assertEqual(block["sides_unknown"], "the registry could not be read")
        # the story has no record of its sides: the reader's default (all real) is a guess beside an unknown, so it is not copied
        self.assertNotIn("sides_met", block)
        self.pipeline(sides=SIDES, sides_unknown="the registry could not be read")       # a plain-string `sides_unknown` reads too
        both = self.block()
        self.assertEqual((both["sides_unknown"], both["sides_met"]["backend"]), ("the registry could not be read", "substituted"))

    def test_a_task_id_that_is_not_one_path_component_is_unstamped_not_a_crash(self):
        self.pipeline(sides=SIDES)
        RS.artifacts_dir = self.keep
        self.assertEqual(RS.proof_stamp("../x"), {})

    def _old_block(self, stamp):
        (self.task / "evidence").mkdir(exist_ok=True)
        report = self.task / "evidence" / "report.xml"
        report.write_text(JUNIT, encoding="utf-8")
        import hashlib
        block = self.block(task="")
        block.update(stamp)
        block["evidence"] = [{"summary": "", "reporter": "junit-xml", "report_path": "evidence/report.xml",
                              "report_sha256": hashlib.sha256(report.read_bytes()).hexdigest()}]
        block["attempt_started_at"], block["attempt_ended_at"] = "2026-11-10T10:00:00+00:00", "2026-11-10T10:01:00+00:00"
        path = self.task / "work" / "run-blocks" / "old.json"
        atomic_json(path, block)
        return path

    def _reparse(self, path):
        mapping = {"instance_contracts": {"i-1": {"report_test_id": "t::a"}}}
        return json.loads(RS.reparse_run_block(self.task, path, mapping).read_text(encoding="utf-8"))

    def test_reparse_keeps_the_stamp_of_the_superseded_block(self):
        old = self._old_block({"sides_met": {"ui": "real", "backend": "substituted"}, "sides_unknown": "why"})
        self.pipeline()                                # today's story record is all-real: the reparse still copies the OLD stamp
        new = self._reparse(old)
        self.assertEqual(new["sides_met"], {"ui": "real", "backend": "substituted"})
        self.assertEqual(new["sides_unknown"], "why")
        self.assertEqual(new["supersedes_block_id"], "a1")

    def test_reparse_of_an_unstamped_block_stays_unstamped_even_when_the_story_has_sides_now(self):
        old = self._old_block({})
        self.pipeline(sides=SIDES)
        new = self._reparse(old)
        self.assertNotIn("sides_met", new)
        self.assertNotIn("sides_unknown", new)

    # ---- manual block, C11, reduce ------------------------------------------------------------------------------------------

    def _manual_task(self, **pipeline):
        fixtures.ROOT = self.task
        before, after = self.task / "work/evidence/before.png", self.task / "work/evidence/after.png"
        before.parent.mkdir(parents=True, exist_ok=True)
        before.write_bytes(b"before")
        after.write_bytes(b"after")
        ob = obligation("O-1", "manual-agent")
        ob["evidence_policy"] = "ui"
        atomic_json(self.task / "work/test-plan.json", [{"id": "TS-1", "schema_version": 2, "coverage_obligations": [ob]}])
        atomic_json(self.task / "state/story-case-links.json", {"links": [{"case_id": "TC-1", "version": "cv_1"}]})
        store = EventStore(self.task)
        store.commit("initialize", {"source_revision": fixtures.SNAPSHOT_SHA, "scope": ["TC-1"]}, "init")
        fixtures.seed_provenance(self.task)
        store.commit("dispatch", {"id": "d1", "stage": "S6", "role": "qa-runner", "scope": ["TC-1"]}, "d1")
        row = fixtures.record(before, after)
        row["completion_condition"] = "done"
        row["obligation_hashes"] = {"O-1": content_hash(ob)}
        row["approved_policy_hash"] = content_hash({"evidence_policy": "ui", "completion_condition": ob["completion_condition"],
                                                    "obligation_hashes": row["obligation_hashes"]})
        row["gate_a_decision_ref"] = "decision:gate-a"
        if pipeline:
            self.pipeline(**pipeline)
        return row

    def test_manual_block_is_stamped(self):
        row = self._manual_task(sides=SIDES)
        row["about"] = ["ui"]
        path = M.write_block(self.task, [row])
        block = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(block["sides_met"], {"ui": "real", "backend": "substituted"})
        self.assertEqual(block["manual_checks"][0]["about"], ["ui"])

    def test_manual_block_of_an_all_real_story_is_the_block_of_today(self):
        row = self._manual_task()                         # no pipeline.json at all
        block = json.loads(M.write_block(self.task, [row]).read_text(encoding="utf-8"))
        self.assertEqual(set(block), {"schema_version", "dispatch_id", "attempt_started_at", "attempt_ended_at", "head",
                                      "manual_checks", "block_id"})

    def test_c11_refuses_an_about_that_names_a_non_side_and_names_a_door(self):
        row = self._manual_task(sides=SIDES)
        row["about"] = ["ui", "payments"]
        found = [e for e in M.validate(row, self.task) if "about" in e]
        self.assertEqual(len(found), 1)
        self.assertIn("'payments'", found[0])
        self.assertIn("backend, ui", found[0])
        self.assertIn("Door:", found[0])
        with self.assertRaises(ValueError) as caught:
            M.write_block(self.task, [row])
        self.assertIn("not a side of this story", str(caught.exception))

    def test_c11_about_shapes_and_the_good_case(self):
        row = self._manual_task(sides=SIDES)
        for bad in ("ui", [""], [3], {"ui": 1}):
            self.assertTrue([e for e in M.validate(dict(row, about=bad), self.task) if e.startswith("about must be")], bad)
        self.assertEqual([e for e in M.validate(dict(row, about=["ui", "backend"]), self.task) if "about" in e], [])
        self.assertEqual([e for e in M.validate(dict(row, about=[]), self.task) if "about" in e], [])   # an empty claim names nothing
        self.assertEqual([e for e in M.validate(row, self.task) if "about" in e], [])                    # no `about`: nothing checked

    def test_c11_on_an_unreadable_story_record_says_the_sides_could_not_be_read(self):
        row = self._manual_task(sides=SIDES)
        (self.task / "pipeline.json").write_text("{not json", encoding="utf-8")
        found = [e for e in M.validate(dict(row, about=["ui"]), self.task) if "about" in e]
        self.assertEqual(len(found), 1)
        self.assertIn("could not be read", found[0])
        self.assertNotIn("its sides", found[0])                           # the default side is not listed as the story's sides
        self.assertIn("Door:", found[0])
        self.assertEqual([e for e in M.validate(dict(row, about=[]), self.task) if "about" in e], [])
        (self.task / "pipeline.json").write_bytes(b"\xef\xbb\xbf" + json.dumps({"sides": SIDES}).encode("utf-8"))   # a BOM reads
        self.assertEqual([e for e in M.validate(dict(row, about=["ui"]), self.task) if "about" in e], [])

    def test_about_travels_from_the_walk_verdict_to_the_block(self):
        """F2: walk verdict -> walk_record_of -> record_from_walk -> build_record -> the block (the runner's own road)."""
        import scaffold as S
        import walk_session as WS
        import test_manual_capture as TMC
        t = S.make_task()
        try:
            case = S.CASES["ui"]
            fixtures.seed_provenance(t.task, "e2e-ui", S.probe()["expected_source_revision"])
            TMC.ui_run(t, steps=f"goto {TMC.UI}\ncapture pre_action initial\nread {TMC.VIEWPORT} style=transform\ncapture post_action final\n")
            folder = t.attempt_dir(case)
            text = next(c for c in TMC.jsonl(folder / "captures.jsonl") if Path(c["path"]).suffix in M.QUOTE_SUFFIXES)
            words = " ".join((t.task / text["path"]).read_text(encoding="utf-8").split())[:12]
            atomic_json(t.task / "pipeline.json", {"stages": {}, "sides": SIDES})
            with t.patched():
                M.prepare_to_file(t.task, case, TMC.OBLIGATIONS[case])
                wanted = sorted(json.loads(M.request_path(t.task, case).read_text(encoding="utf-8")).get("thens") or {}, key=int) or ["1"]
                verdict = {"thens": [{"n": int(n), "result": "fail" if i == 0 else "unreached", "quote": words if i == 0 else ""}
                                     for i, n in enumerate(wanted)], "about": ["ui"]}
                made = WS.walk_record_of(t.task, "W1", case, verdict, attempt="a1")
                self.assertEqual(made["about"], ["ui"])
                self.assertNotIn("about", WS.walk_record_of(t.task, "W1", case, {k: v for k, v in verdict.items() if k != "about"}, attempt="a1"))
                bad = M.record_from_walk(t.task, case, dict(made, about=["payments"]))     # C11 refuses a non-side on this road too
                self.assertIn("not a side of this story", bad.get("refused", ""), bad)
                done = M.record_from_walk(t.task, case, made)
                self.assertTrue(done.get("written"), done)
                block = json.loads((t.task / done["block"]).read_text(encoding="utf-8"))
                self.assertEqual(block["manual_checks"][0]["about"], ["ui"])
                self.assertEqual(block["sides_met"], {"ui": "real", "backend": "substituted"})
        finally:
            S.cleanup(t)

    def test_build_cli_takes_about_and_other_commands_refuse_it(self):
        seen = {}
        with mock.patch.object(M, "build_record", lambda *a, **k: seen.update(k) or {"written": True}), \
                mock.patch.object(M.hooklib, "story_of", lambda *a, **k: None):
            args = ["--task-root", str(self.task)]
            self.assertEqual(M.main(["build", *args, "--case", "C", "--result", "pass", "--actual", "x", "--masked",
                                     "--about", "ui", "--about", "backend"]), 0)
            self.assertEqual(seen["about"], ["ui", "backend"])
            seen.clear()
            M.main(["build", *args, "--case", "C", "--result", "pass", "--actual", "x", "--masked"])
            self.assertIsNone(seen["about"])
            self.assertNotEqual(M.main(["validate", *args, "--about", "ui"]), 0)       # never silently dropped

    def test_reduce_carries_the_stamp_to_both_row_kinds(self):
        row = self._manual_task(sides=SIDES)
        row["about"] = ["backend"]
        M.write_block(self.task, [row])
        block = self.block(task="S-1")
        block.update(attempt_started_at="2026-11-10T10:00:00+00:00", attempt_ended_at="2026-11-10T10:01:00+00:00")
        atomic_json(self.task / "work" / "run-blocks" / "r1.json", block)
        report, _ = F.reduce(self.task)
        want = {"ui": "real", "backend": "substituted"}
        self.assertEqual([r["sides_met"] for r in report["results"]], [want])
        self.assertEqual([r["sides_met"] for r in report["manual_checks"]], [want])
        self.assertEqual([r["sides_met"] for r in report["current_manual_checks"]], [want])
        self.assertEqual(report["current_manual_checks"][0]["about"], ["backend"])

    def test_reduce_carries_sides_unknown_and_adds_nothing_to_an_unstamped_block(self):
        plain = self.block(task="")
        plain.update(attempt_started_at="2026-11-10T10:00:00+00:00", attempt_ended_at="2026-11-10T10:01:00+00:00")
        atomic_json(self.task / "work" / "run-blocks" / "plain.json", plain)
        report, _ = F.reduce(self.task)
        self.assertEqual([r for r in report["results"] if "sides_met" in r or "sides_unknown" in r], [])
        unknown = copy.deepcopy(plain)
        unknown.update(block_id="u1", attempt_id="u1", sides_unknown="the registry could not be read",
                       attempt_started_at="2026-11-10T11:00:00+00:00", attempt_ended_at="2026-11-10T11:01:00+00:00")
        atomic_json(self.task / "work" / "run-blocks" / "u1.json", unknown)
        report, _ = F.reduce(self.task)
        stamped = [r for r in report["results"] if r.get("sides_unknown")]
        self.assertEqual(len(stamped), 1)
        self.assertNotIn("sides_met", stamped[0])         # carried as unknown: no reality was invented for it


if __name__ == "__main__":
    unittest.main(verbosity=1)
