"""RN1-10 (c) / P26: a manual verdict and every doubt the runner saw stand on a quote found in the recorded evidence.

Keys K-E1..K-E5, E6 (a quote beyond a truncated capture), E7 (a green check keeps its observations), E14 (a record made
before the rule has no `observations` and reads as []), and the refusal of `build` over a live browser profile.
Kill map (builder-rules 7a, one file each): accepting a quote without looking it up kills K-E1; folding the case in the quote
kills K-E5; `triage_targets` ignoring a green check's observations kills E7; asking old records to declare the field kills E14.
"""
import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_manual_evidence as fixtures
import manual_evidence as M
import manual_capture as MC
import contract as C

PASS_NOTE = "incomplete evidence cannot claim pass"     # appended by `validate` to any error of a `pass` record: noise here


def valid(record, task):
    return [e for e in M.validate_record(record, task) if e != PASS_NOTE]


PAGE = "Checkout\nThe price is 11 dollars.   Quantity: 1\nTotal 12 dollars"


def add_text(task, name, text, kind="log"):
    path = task / "work/evidence" / name
    path.write_text(text, encoding="utf-8")
    ref = fixtures.evidence(path, "after", ["state"])
    ref["kind"] = kind
    return ref


class Observations(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="qa-observations-"))
        self.task = self.dir / "ST-1"
        fixtures.ROOT = self.task
        before, after = self.task / "work/evidence/before.png", self.task / "work/evidence/after.png"
        before.parent.mkdir(parents=True)
        before.write_bytes(b"before")
        after.write_bytes(b"after")
        self.record = fixtures.record(before, after)
        self.page = add_text(self.task, "page.txt", PAGE)
        self.record["evidence_refs"].append(self.page)
        self.assertEqual(valid(self.record, self.task), [], "the fixture record is valid before any observation")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def observation(self, **over):
        row = {"step": 2, "expected": "the price 12", "seen": "the price shows 11", "evidence": self.page["path"],
               "quote": "The price is 11 dollars."}
        row.update(over)
        return row

    def errors(self, *observations, record=None):
        record = copy.deepcopy(record or self.record)
        record["observations"] = list(observations)
        return valid(record, self.task)

    # --- K-E1 --------------------------------------------------------------------------------------------------
    def test_k_e1_a_quote_from_the_capture_is_taken_an_invented_one_is_refused_by_field(self):
        self.assertEqual(self.errors(self.observation()), [])
        got = self.errors(self.observation(quote="The price is 13 dollars."))
        self.assertEqual(got, ["the quote of observations[0] is not in page.txt"])
        got = self.errors(self.observation(), self.observation(quote="made up words"))
        self.assertEqual(got, ["the quote of observations[1] is not in page.txt"], "the second entry is the one named")

    def test_k_e1_every_missing_key_is_named(self):
        row = self.observation()
        del row["evidence"]
        self.assertEqual(self.errors(row), ["observations[0].evidence is missing"])
        row = self.observation()
        del row["quote"], row["seen"]
        self.assertEqual(self.errors(row), ["observations[0].quote is missing", "observations[0].seen is missing"])
        self.assertIn("observations[0].step must be the number of a step",
                      "; ".join(self.errors(self.observation(step=0))))
        self.assertIn("observations[0].step must be the number of a step",
                      "; ".join(self.errors(self.observation(step=3))), "the record has two steps: 3 is beyond")
        self.assertIn("is not a capture of this record's attempt",
                      "; ".join(self.errors(self.observation(evidence="work/evidence/elsewhere.txt"))))
        self.assertIn("at most 300 characters", "; ".join(self.errors(self.observation(quote="x " * 200))))

    # --- K-E2 --------------------------------------------------------------------------------------------------
    def test_k_e2_a_picture_is_checked_against_the_excerpt_the_capture_tool_wrote_for_that_step(self):
        picture = [r for r in self.record["evidence_refs"] if r["path"].endswith("after.png")][0]["path"]
        steps = MC.case_root(self.task, "TC-1") / "a1" / "steps.jsonl"
        steps.parent.mkdir(parents=True)
        steps.write_text(json.dumps({"step": "open", "outcome": "ok", "observe_text": "Basket 1 item"}) + "\n"
                         + json.dumps({"step": "type 2", "outcome": "ok", "observe_text": "Quantity 11  (was 1)"}) + "\n",
                         encoding="utf-8")
        self.assertEqual(self.errors(self.observation(evidence=picture, quote="Quantity 11")), [])
        got = self.errors(self.observation(evidence=picture, quote="Quantity 2"))
        self.assertEqual(got, ["the quote of observations[0] is not in the excerpt (observe_text) of step 2"])
        # the quote stands in step 2's excerpt, not in step 1's: the step number picks the excerpt
        got = self.errors(self.observation(evidence=picture, quote="Quantity 11", step=1))
        self.assertEqual(got, ["the quote of observations[0] is not in the excerpt (observe_text) of step 1"])
        steps.write_text(json.dumps({"step": "open", "outcome": "ok"}) + "\n" + json.dumps({"step": "x", "outcome": "ok"}) + "\n",
                         encoding="utf-8")
        got = "; ".join(self.errors(self.observation(evidence=picture, quote="Quantity 11")))
        self.assertIn("step 2 has no observe_text", got, "a picture whose step kept no excerpt holds no quote: refused, not passed")

    # --- K-E3 --------------------------------------------------------------------------------------------------
    def test_k_e3_an_empty_list_is_the_declared_outcome_and_a_new_record_without_the_field_is_refused(self):
        self.assertEqual(self.errors(), [], "observations: [] is valid")
        self.assertEqual(valid(self.record, self.task), [], "E14: a record with no field reads as []")
        original = M._validate_current
        M._validate_current = lambda task, value: M.validate_record(value, task)
        try:
            with self.assertRaises(ValueError) as caught:
                M.write_block(self.task, [self.record], declared=True)
            self.assertIn("declare observations: [] when you saw nothing doubtful", str(caught.exception))
            declared = copy.deepcopy(self.record)
            declared["observations"] = []
            self.assertTrue(M.write_block(self.task, [declared], declared=True).is_file())
            self.assertTrue(M.write_block(self.task, [self.record]).is_file(), "E14: the old way of writing is not asked again")
        finally:
            M._validate_current = original
        got = valid(dict(self.record, observations={"step": 1}), self.task)
        self.assertEqual(got, ["observations must be an array of objects ([] when there is nothing to report)"])
        self.assertEqual(valid(dict(self.record, observations=["a doubt"]), self.task), got)

    # --- K-E5 --------------------------------------------------------------------------------------------------
    def test_k_e5_only_whitespace_is_normalised_never_the_case(self):
        self.assertEqual(self.errors(self.observation(quote="  The  price\n is 11 dollars.  Quantity:\t1 ")), [])
        self.assertEqual(self.errors(self.observation(quote="the price is 11 dollars.")),
                         ["the quote of observations[0] is not in page.txt"], "another case is another text")
        self.assertEqual(self.errors(self.observation(quote="THE PRICE")), ["the quote of observations[0] is not in page.txt"])

    # --- E6 ----------------------------------------------------------------------------------------------------
    def test_e6_a_quote_beyond_the_stored_part_is_named_so_and_never_accepted(self):
        cut = add_text(self.task, "response.json",
                       json.dumps({"response": {"body": "start of a long body", "truncated": True, "body_bytes_stored": 20}}),
                       kind="request_response")
        whole = add_text(self.task, "whole.json", json.dumps({"response": {"body": "start", "truncated": False}}),
                         kind="request_response")
        record = copy.deepcopy(self.record)
        record["evidence_refs"] += [cut, whole]
        beyond = "the quote is beyond the stored part (truncated)"
        got = self.errors(self.observation(evidence=cut["path"], quote="the tail that was never stored"), record=record)
        self.assertEqual(len(got), 1)
        self.assertIn("the quote of observations[0] is not in response.json", got[0])
        self.assertIn(beyond, got[0])
        self.assertEqual(self.errors(self.observation(evidence=cut["path"], quote="start of a long body"), record=record), [],
                         "what the stored bytes hold is quotable")
        got = self.errors(self.observation(evidence=whole["path"], quote="the tail that was never stored"), record=record)
        self.assertEqual(got, ["the quote of observations[0] is not in whole.json"], "control: a capture stored whole says no more")
        # the same words for a Then quote
        record["then_quotes"] = [{"then": 1, "quote": "the tail that was never stored", "source": cut["path"], "kind": "text"}]
        got = "; ".join(valid(record, self.task))
        self.assertIn("Then 1: the quote is not in response.json", got)
        self.assertIn(beyond, got)
        # a record that carries the capture tool's limitation sentence names it for a text capture too
        record = copy.deepcopy(self.record)
        record["limitations"] = [MC._limit_words("response")]
        got = self.errors(self.observation(quote="never stored"), record=record)
        self.assertIn(beyond, "; ".join(got))

    # --- E7 and K-E4 -------------------------------------------------------------------------------------------
    def test_k_e4_an_observation_with_no_then_verdict_is_a_triage_target(self):
        row = {"case": "TC-1", "result": "inconclusive", "observations": [self.observation()]}
        got = C.triage_targets({"current_manual_checks": [row]})
        self.assertEqual(got["observations"], {"TC-1#obs1"})
        self.assertEqual(got["manual"], {"TC-1"}, "the inconclusive check is a target as before")
        self.assertEqual(C.triage_targets({"current_manual_checks": [{"case": "TC-1", "result": "inconclusive"}]})["observations"],
                         set(), "control: no observations, no target")
        # and the inconclusive record itself is valid with the observation and no Then verdict
        record = copy.deepcopy(self.record)
        record.update(result="inconclusive", limitations=["step 2 failed before the first Then"],
                      observations=[self.observation()])
        record["evidence_refs"] = [r for r in record["evidence_refs"] if r["phase"] != "after"] + [self.page]
        self.assertEqual(valid(record, self.task), [])

    def test_e7_a_green_check_keeps_its_observations_and_a_nameless_one_is_a_note(self):
        row = {"case": "TC-2", "result": "pass", "observations": [self.observation(), "junk", self.observation()]}
        got = C.triage_targets({"current_manual_checks": [row]})
        self.assertEqual(got["observations"], {"TC-2#obs1", "TC-2#obs3"}, "numbered by place in the list; a non-object is skipped")
        self.assertEqual((got["manual"], got["results"], got["unnamed"]), (set(), set(), set()), "a pass is no failure")
        got = C.triage_targets({"manual_checks": [{"result": "pass", "observations": [self.observation()]}]})
        self.assertEqual(got["observations"], set())
        self.assertEqual(len(got["unnamed_manual"]), 1, "an observation with no case is never silently dropped")
        self.assertEqual(C.triage_targets({"current_manual_checks": [{"case": "TC-2", "result": "pass", "observations": []}]})
                         ["observations"], set())
        self.assertEqual(C.triage_targets("not a report")["observations"], set())

    # --- the live profile --------------------------------------------------------------------------------------
    def test_build_is_refused_over_a_live_browser_profile(self):
        folder = MC.case_root(self.task, "TC-1") / "a1"
        (folder / "sessions" / "user" / "profile").mkdir(parents=True)
        with self.assertRaises(ValueError) as caught:
            M._attempt_files(folder, "a1", "TC-1")
        self.assertIn("close the sessions first: `manual_capture.py session close", str(caught.exception))
        self.assertIn("user", str(caught.exception))
        shutil.rmtree(folder / "sessions" / "user" / "profile")
        (folder / "sessions" / "user" / "state.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError) as caught:
            M._attempt_files(folder, "a1", "TC-1")
        self.assertIn("holds no captures", str(caught.exception), "control: a closed session (state.json only) passes that check")


class Readers(unittest.TestCase):
    """t-1711: the readers of `triage_targets` that take the `observations` key (finalize_task, handoff_check, s7_pretriage);
    each reads a story WITHOUT observations exactly as before (the control in every test)."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="qa-observations-readers-"))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_s7_pretriage_leaves_a_check_with_an_observation_to_the_analyst(self):
        import s7_pretriage as S
        ident = "image:sha256:" + "ab" * 32
        row = {"case": "TC-9", "attempt_id": "a1", "result": "inconclusive", "evidence_validated": True,
               "limitations": ["P-invalid is not runnable here.", S.identity_sentence(ident)], "runtime_identity": ident}
        self.assertEqual(S._why_not([row], {"TC-9"}, (set(), False)), "", "control: no observation, code may decide")
        got = S._why_not([dict(row, observations=[{"step": 1}])], {"TC-9"}, (set(), False))
        self.assertIn("observation", got)

    def test_handoff_check_zero_row_triage_is_not_nothing_to_triage_over_an_observation(self):
        import handoff_check as H

        class Art:
            def __init__(self, report):
                self.report = report

            def json(self, _path):
                return self.report
        green = {"totals": {"passed": 1}, "current_manual_checks": [{"case": "TC-2", "result": "pass"}]}
        self.assertEqual(H._no_failure_shown(Art(green)), "", "control: a green story without observations")
        seen = dict(green, current_manual_checks=[{"case": "TC-2", "result": "pass", "observations": [{"step": 1}]}])
        self.assertIn("TC-2#obs1", H._no_failure_shown(Art(seen)))

    def test_finalize_refresh_keeps_an_observation_row_and_archives_one_without_a_target(self):
        import finalize_task as F
        task = self.dir / "ST-9"
        (task / "work").mkdir(parents=True)

        def reduced(task_, observations):
            report = {"execution_status": "passed", "current_results": [], "results": [], "manual_checks": [],
                      "current_manual_checks": [{"case": "TC-2", "result": "pass", "observations": observations}],
                      "reducer": {"sources": []}}
            return report, {"schema_version": 2, "task_id": "ST-9", "triage": []}
        rows = [{"instance_id": "TC-2#obs1", "verdict": "APP_BUG"}, {"instance_id": "TC-2#obs7", "verdict": "APP_BUG"}]
        (task / "work" / "triage.json").write_text(json.dumps({"triage": rows}), encoding="utf-8")
        saved = F.reduce
        F.reduce = lambda t: reduced(t, [{"step": 1}])
        try:
            F.refresh(task)
        finally:
            F.reduce = saved
        kept = json.loads((task / "work" / "triage.json").read_text(encoding="utf-8"))
        self.assertEqual([r["instance_id"] for r in kept["triage"]], ["TC-2#obs1"], "the unknown target is the stale one")
        self.assertNotIn("reason", kept, "an observation is work: 'no product failures' is not said over it")
        self.assertTrue(list((task / "state" / "migration").glob("stale-triage-*.json")))

    def test_f8_every_verdict_word_stands_in_the_lists_the_roles_read(self):
        """t-1747 F8: the closed verdict list the analyst, the bug reporter, the scribe, the retro and S7 read names NO_DEFECT, and the
        run contract describes the observation row (a word in the closed vocabulary with no mention in the role text is a gap)."""
        base = Path(__file__).resolve().parents[2]
        for rel in ("references/vocabularies.md", "skills/qa-story/phases/s7.md", "references/slices/qa-failure-analyst/vocabularies.md"):
            text = (base / rel).read_text(encoding="utf-8")
            self.assertIn("NO_DEFECT", C.TRIAGE_VERDICTS)
            for word in ("RUNNER_MISREAD_EVIDENCE", "NO_DEFECT"):        # the last word before F8, and the one it lacked
                self.assertIn(f"`{word}`", text, f"{rel} lacks the verdict {word}")
        self.assertIn("<case>#obs<n>", (base / "references/artifact-contract-run.md").read_text(encoding="utf-8"))

    def test_f9_the_bans_a_byte_cut_dropped_are_back_and_the_roles_stay_under_their_ceilings(self):
        """t-1747 F9: bans that live in no other carrier are in the role files, `detail` is optional, and the byte ceiling holds."""
        agents = Path(__file__).resolve().parents[2] / "agents"
        analyst = " ".join((agents / "qa-failure-analyst.md").read_text(encoding="utf-8").split())
        runner = " ".join((agents / "qa-runner.md").read_text(encoding="utf-8").split())
        # X7-3: both are charters now; `charter_errors` holds the size (150 lines), the verdict words are the vocabulary slice's
        # (the f8 test above), and `head` is recorded by run_suite, not told by the role file (pin rows R-drop).
        for words in ("never fetch or infer history just for metrics", "never a second full coverage review",
                      "`detail` (optional: a row without it is not refused)", "a green one too"):
            self.assertIn(words, analyst)
        self.assertIn("nothing reported as checked", runner)
        self.assertNotIn("a green one too", runner)                     # control: the phrase is the analyst's, not in every file

    def test_f11_one_text_for_the_cut_body_words_and_a_true_help_for_session(self):
        """t-1747 F11: `manual_evidence` finds a cut capture by `manual_capture.CUT_WORDS` (no copy), which is inside the sentence the
        capture tool writes; the `--session` help and docstring say `http` needs the same `--profile`."""
        import manual_capture as MC
        import manual_evidence as ME
        self.assertFalse(hasattr(ME, "CUT_WORDS"), "the copy is gone")
        self.assertIn(MC.CUT_WORDS, MC._limit_words("read"))
        self.assertTrue(ME._cut_capture(self.dir, {"path": "none.json"}, [MC._limit_words("response")]))
        self.assertFalse(ME._cut_capture(self.dir, {"path": "none.json"}, ["something else"]), "BEYOND: another limitation is no cut")
        import contextlib
        import io
        shown = io.StringIO()
        with contextlib.redirect_stdout(shown), self.assertRaises(SystemExit):
            MC.build_parser().parse_args(["ui", "--help"])
        for text in (MC.__doc__, " ".join(shown.getvalue().split())):
            self.assertIn("--profile", text)
            self.assertIn("signs in again", " ".join(text.split()))

    def test_f5_one_attempt_aware_binding_for_the_duplicate_check_and_the_refresh_keep(self):
        """t-1747 F5: a1 had a row for obs1, S6 retried, a2 has its own obs1: the stale a1 row is archived by the refresh and is
        no competitor of the a2 row in the duplicate check - both ask `bind_triage`'s attempt rule."""
        import finalize_task as F
        import validate_artifacts as V
        report = {"execution_status": "passed", "current_results": [], "results": [], "manual_checks": [],
                  "current_manual_checks": [{"case": "TC-2", "result": "pass", "attempt_id": "a2", "observations": [{"step": 1}]}],
                  "reducer": {"sources": []}}
        stale = {"instance_id": "TC-2#obs1", "attempt_id": "a1", "verdict": "APP_BUG"}
        fresh = {"instance_id": "TC-2#obs1", "attempt_id": "a2", "verdict": "APP_BUG"}
        self.assertEqual(C.observation_duplicates([stale, fresh], report), {}, "another attempt is no duplicate")
        self.assertEqual(C.observation_duplicates([stale, fresh]), {}, "BEYOND: no report, still grouped by attempt")
        self.assertEqual(len(C.observation_duplicates([fresh, dict(fresh, verdict="NO_DEFECT")], report)["TC-2#obs1"]), 2,
                         "AT: two rows of the SAME attempt are a duplicate")
        errors: list = []
        V.check_triage_v0(Path("triage.json"), {"triage": [stale, fresh]}, errors)
        self.assertFalse([e for e in errors if "both answer" in e], errors)
        errors = []
        V.check_triage_v0(Path("triage.json"), {"triage": [fresh, dict(fresh, verdict="NO_DEFECT")]}, errors)
        self.assertTrue([e for e in errors if "both answer" in e], errors)
        task = self.dir / "ST-5"
        (task / "work").mkdir(parents=True)
        (task / "work" / "triage.json").write_text(json.dumps({"triage": [stale, fresh]}), encoding="utf-8")
        saved = F.reduce
        F.reduce = lambda t: (report, {"schema_version": 2, "task_id": "ST-5", "triage": []})
        try:
            F.refresh(task)
        finally:
            F.reduce = saved
        kept = json.loads((task / "work" / "triage.json").read_text(encoding="utf-8"))
        self.assertEqual([r["attempt_id"] for r in kept["triage"]], ["a2"], "the stale a1 row is archived, the a2 row kept")


QUOTE = 'the capture says "The price is 11 dollars." which the requirement allows'


class Verdicts(unittest.TestCase):
    """t-1715: an observation is a failure of the kind `observation` for every reader that binds a triage row (AR-28: an
    unanswered one never passes), and `NO_DEFECT` is its verdict. A story with no observation reads as before (the controls)."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="qa-observations-verdicts-"))
        self.green = {"execution_status": "passed", "totals": {"passed": 1, "failed": 0},
                      "current_manual_checks": [{"case": "TC-1", "result": "pass", "observations": [{"step": 1}, {"step": 2}]}]}
        self.plain = {"execution_status": "passed", "totals": {"passed": 1, "failed": 0},
                      "current_manual_checks": [{"case": "TC-1", "result": "pass"}]}

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_triage_failures_and_bind_triage_carry_the_observations(self):
        failures, notes = C.triage_failures(self.green)
        self.assertEqual(sorted(failures), [("observation", "TC-1#obs1"), ("observation", "TC-1#obs2")])
        self.assertEqual(notes, [])
        self.assertEqual(C.triage_failures(self.plain), ({}, []), "control: no observation, no failure, as before")
        bound = C.bind_triage(failures, [{"instance_id": "TC-1#obs1", "verdict": "NO_DEFECT"},
                                         {"case": "TC-1", "verdict": "APP_BUG"}])["matched"]
        self.assertEqual(len(bound[("observation", "TC-1#obs1")]), 1)
        self.assertEqual(bound[("observation", "TC-1#obs2")], [], "a row of the case does not answer its observation")
        red = dict(self.green, current_manual_checks=[dict(self.green["current_manual_checks"][0], result="fail")])
        failures, _ = C.triage_failures(red)
        self.assertEqual(sorted(failures)[0], ("manual", "TC-1"), "the red Then stays its own failure beside the doubts")
        self.assertEqual(len(failures), 3)
        bound = C.bind_triage(failures, [{"case": "TC-1", "verdict": "APP_BUG"}])["matched"]
        self.assertEqual(len(bound[("manual", "TC-1")]), 1)
        self.assertEqual(bound[("observation", "TC-1#obs1")], [])

    def test_failures_to_triage_lists_the_observations_of_a_green_check(self):
        import types
        import story_run as SR
        (self.dir / "work").mkdir()
        me = types.SimpleNamespace(task_root=self.dir)
        (self.dir / "work" / "run-report.json").write_text(json.dumps(self.plain), encoding="utf-8")
        self.assertEqual(SR.Driver.failures_to_triage(me), "", "control: a green story without observations")
        (self.dir / "work" / "run-report.json").write_text(json.dumps(self.green), encoding="utf-8")
        self.assertEqual(SR.Driver.failures_to_triage(me), "manual observations TC-1#obs1,TC-1#obs2")

    def test_handoff_check_with_rows_names_an_unanswered_observation(self):
        import handoff_check as H

        class Art:
            def __init__(self, report):
                self.report = report

            def json(self, _path):
                return self.report
        rows = [{"instance_id": "TC-1#obs1", "verdict": "NO_DEFECT"}]
        self.assertEqual(H._untriaged_failures(Art(self.green), rows)[0], ["TC-1#obs2"])
        self.assertEqual(H._untriaged_failures(Art(self.plain), rows)[0], [], "control: no observation, nothing unanswered")
        self.assertEqual(H._untriaged_failures(Art(self.green), [{"instance_id": "TC-1#obs1", "verdict": "x"},
                                                                 {"instance_id": "TC-1#obs2", "verdict": "x"}])[0], [])

    def test_delivery_never_passes_an_unanswered_observation_and_judges_no_defect(self):
        import check_delivery as D
        from harness import GOOD
        art = self.dir / "art"
        shutil.copytree(GOOD, art)
        report_path, triage_path = art / "work" / "run-report.json", art / "work" / "triage.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(D.triage_reasons(art), [], "control: the good set has no reason")
        report["manual_checks"][0]["observations"] = [{"step": 1, "quote": "The price is 11 dollars."}]
        report_path.write_text(json.dumps(report), encoding="utf-8")
        got = "\n".join(D.triage_reasons(art))
        self.assertIn("the observation TC-002#obs1 of a manual check has no verdict", got)

        def judge(row) -> str:
            triage_path.write_text(json.dumps({"triage": [row]}), encoding="utf-8")
            return "\n".join(D.triage_reasons(art))
        self.assertEqual(judge({"instance_id": "TC-002#obs1", "verdict": "NO_DEFECT", "reason": QUOTE}), "")
        self.assertIn("needs a `reason` that quotes", judge({"instance_id": "TC-002#obs1", "verdict": "NO_DEFECT"}))
        self.assertIn("needs a `reason` that quotes",
                      judge({"instance_id": "TC-002#obs1", "verdict": "NO_DEFECT", "reason": "looks fine to me"}))
        got = judge({"case": "TC-002", "verdict": "NO_DEFECT", "reason": QUOTE})
        self.assertIn("is for an observation of a manual check", got)
        self.assertIn("APP_BUG, TEST_BUG", got, "the refusal names the words the Then may take")
        self.assertIn("the observation TC-002#obs1 of a manual check has no verdict", got, "and the doubt stays unanswered")
        # F3 (t-1747): an apostrophe is no quotation mark; the quoted words must stand in the observation's recorded evidence
        self.assertIn("needs a `reason` that quotes", judge({"instance_id": "TC-002#obs1", "verdict": "NO_DEFECT",
                                                              "reason": "it's not a bug, the app's rule"}))
        self.assertEqual(judge({"instance_id": "TC-002#obs1", "verdict": "NO_DEFECT",
                                "reason": 'it\'s fine: the page says "The price is 11 dollars." and the app\'s rule allows it'}),
                         "", "BEYOND: an apostrophe inside real quote marks still passes")
        self.assertIn("no quoted word of the `reason` stands in the recorded evidence",
                      judge({"instance_id": "TC-002#obs1", "verdict": "NO_DEFECT", "reason": 'the page says "Total: 99"'}))
        # F4: ONE bad name among good ones is refused
        mixed = judge({"instance_id": "TC-002#obs1", "test": "spec.ts::red", "verdict": "NO_DEFECT", "reason": QUOTE})
        self.assertIn("and nothing else", mixed)
        self.assertIn("spec.ts::red", mixed)
        self.assertEqual(D.OWNER_BY_TRIAGE_VERDICT.get("NO_DEFECT"), "factory")
        self.assertIn("NO_DEFECT", C.TRIAGE_VERDICTS)
        self.assertEqual(C.triage_no_defect_problems({"case": "TC-002", "verdict": "APP_BUG"}), [], "another verdict is not judged")
        self.assertEqual(C.triage_no_defect_problems("not a row"), [])
        # pure form, no report: the contraction is no quote, a quoted word is (F3); mixed names are refused (F4)
        self.assertEqual(C.quoted_words("it's not a bug, the app's rule"), [])
        self.assertEqual(C.quoted_words('the page says "Total: 11" and it\'s fine'), ["Total: 11"])
        self.assertEqual(C.quoted_words('one "unclosed'), [])
        self.assertEqual(len(C.triage_no_defect_problems({"instance_id": "TC-1#obs1", "test": "a.ts::t", "verdict": "NO_DEFECT",
                                                          "reason": QUOTE})), 1)


if __name__ == "__main__":
    unittest.main()
