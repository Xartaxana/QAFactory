"""A verdict for another instance must not close a failure by substring."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_delivery as D

class Identity(unittest.TestCase):
    def test_exact_instance_verdict(self):
        with tempfile.TemporaryDirectory() as td:
            task = Path(td)
            (task / "work").mkdir()
            (task / "work/run-report.json").write_text(json.dumps({
                "current_results": [{"instance_id": "i1", "case": "TC-1", "status": "failed"}],
                "current_manual_checks": []}), encoding="utf-8")
            path = task / "work/triage.json"
            path.write_text(json.dumps({"triage": [{"test": "i10", "verdict": "APP_BUG", "evidence": "proof"}]}), encoding="utf-8")
            self.assertTrue(any("failure i1 has no verdict" in reason for reason in D.triage_reasons(task)))
            path.write_text(json.dumps({"triage": [{"test": "i1", "verdict": "APP_BUG", "evidence": "proof"}]}), encoding="utf-8")
            self.assertFalse(any("has no verdict" in reason for reason in D.triage_reasons(task)))

class Spellings(unittest.TestCase):
    """t-309 K3: one id, every spelling it answers to (`contract.id_spellings`)."""

    def test_table(self):
        import contract as C
        table = [
            ("a::b[p]", {"a::b[p]", "a::b"}),                        # AT: the parameter group goes
            ("a::b", {"a::b"}),                                       # and a bare id stands for itself
            ("a::b[x][y]", {"a::b[x][y]", "a::b[x]"}),                # two groups: stripped ONCE, from the LAST `[`
            ("TP1-15045_TC_005", {"TP1-15045_TC_005"}),       # a case id has no suffix
            ("  a::b[p]  ", {"a::b[p]", "a::b"}),                      # whitespace is not part of an id
            ("a::b[p", {"a::b[p"}),                                   # an unclosed group is not a group
            ("[p]", {"[p]"}),                                         # a group with no id before it leaves no id
            ("a[x[1]]", {"a[x[1]]", "a[x"}),                          # the LAST `[`, as stated; never an empty id
        ]
        for value, expected in table:
            self.assertEqual(C.id_spellings(value), expected, repr(value))
        for empty in ("", "   ", None, 5, [], {}, b"a[p]"):
            self.assertEqual(C.id_spellings(empty), set(), f"{empty!r} is no id: it matches nothing")

    def test_two_spellings_meet(self):
        import contract as C
        self.assertTrue(C.id_spellings("a::b[chromium]") & C.id_spellings("a::b"))
        self.assertFalse(C.id_spellings("") & C.id_spellings(""), "two empty ids are not 'the same id'")


class Targets(unittest.TestCase):
    """t-309: `contract.triage_targets` is the one reading of 'a failure that needs triage'."""

    def test_the_union_of_the_readings(self):
        import contract as C
        report = {"current_results": [
            {"instance_id": "t1", "test_id": "m::t1", "status": "failed"},
            {"instance_id": "t2[p]", "status": "error"},
            {"instance_id": "t3", "status": "passed"},
            {"instance_id": "t4", "status": "skipped"},
            "not a row", None],
            "current_manual_checks": [
                {"case": "TC-1", "result": "fail"}, {"case": "TC-2", "result": "failed"},
                {"case": "TC-3", "result": "error"}, {"case": "TC-4", "result": "inconclusive"},
                {"case": "TC-5", "result": "pass"}, {"case": "TC-6", "result": "skipped"},
                {"case": "TC-7", "result": "INCONCLUSIVE "}]}
        got = C.triage_targets(report)
        self.assertEqual(got["results"], {"t1", "t2[p]"})
        self.assertEqual(got["manual"], {"TC-1", "TC-2", "TC-3", "TC-4", "TC-7"})
        self.assertEqual(got["all"], {"t1", "m::t1", "t2[p]", "t2", "TC-1", "TC-2", "TC-3", "TC-4", "TC-7"})
        self.assertEqual(got["unnamed"], set())

    def test_naming_of_a_manual_check(self):
        import contract as C
        got = C.triage_targets({"current_manual_checks": [
            {"result": "inconclusive", "test": "manual.login"},       # no case, no instance_id: named by `test`
            {"result": "inconclusive", "instance_id": "i[x]"},        # named by its instance id
            {"result": "fail"}, {"result": "fail", "case": " "}]})    # nothing to name it by: a note, not a drop
        self.assertEqual(got["manual"], {"manual.login", "i[x]"})
        self.assertEqual(got["all"], {"manual.login", "i[x]", "i"})
        self.assertEqual(len(got["unnamed"]), 2)
        self.assertTrue(all("has no case, instance_id or test" in note for note in got["unnamed"]))

    def test_the_legacy_list_and_the_empty_inputs(self):
        import contract as C
        legacy = {"manual_checks": [{"case": "TC-9", "result": "fail"}]}
        self.assertEqual(C.triage_targets(legacy)["manual"], {"TC-9"}, "no current list: the legacy one is read")
        both = {"current_manual_checks": [{"case": "TC-1", "result": "fail"}], "manual_checks": legacy["manual_checks"]}
        self.assertEqual(C.triage_targets(both)["manual"], {"TC-1"}, "the current list wins when it has rows")
        empty = {"current_manual_checks": [], "manual_checks": legacy["manual_checks"]}
        self.assertEqual(C.triage_targets(empty)["manual"], {"TC-9"}, "an empty current list falls back, as the driver always read it")
        for nothing in (None, [], "x", {}, {"current_results": "x", "current_manual_checks": {"a": 1}}):
            got = C.triage_targets(nothing)
            self.assertEqual(sorted(got), ["all", "manual", "names", "observations", "results", "unnamed", "unnamed_manual"])
            self.assertEqual(got["all"] | got["manual"] | got["unnamed"] | got["unnamed_manual"], set(), repr(nothing))
            self.assertEqual(got["names"], [], repr(nothing))

    def test_a_nameless_failed_result_is_a_failure_with_no_id(self):
        """t-319 F4: `triage_targets` kept a note for a manual check with no name and none for a failed RESULT row, so
        `reduce` counted no failure where HEAD (every failed row) counted one."""
        import contract as C
        got = C.triage_targets({"current_results": [{"status": "failed", "instance_id": ""}, {"status": "error", "nodeid": "z"},
                                                    {"status": "failed", "test_id": "m::t"}, {"status": "passed"}]})
        self.assertEqual(got["results"], {"m::t"})
        self.assertEqual(len(got["unnamed"]), 2)
        self.assertEqual(got["unnamed_manual"], set(), "a result row's note is not a manual check's")
        self.assertTrue(all("has no instance_id, test_instance_id, test_id or test" in note for note in got["unnamed"]))
        # t-323 BL-2 (the pin of attempt 1, which let a `case` name a failed result row, is inverted): a failed
        # RESULT row with only a `case` is nameless - fail-closed - and two of them are two notes
        got = C.triage_targets({"current_results": [{"status": "failed", "case": "C1"}, {"status": "failed", "case": "C1"}]})
        self.assertEqual((got["results"], got["names"], len(got["unnamed"])), (set(), [], 2))
        got = C.triage_targets({"current_manual_checks": [{"result": "fail"}]})
        self.assertEqual((len(got["unnamed"]), got["unnamed_manual"] == got["unnamed"]), (1, True))

    def test_current_results_win_over_the_legacy_list(self):
        """t-319 edge: a report with BOTH `results[]` (the history, every attempt) and `current_results`: the current view
        decides, an empty one included - 'everything repaired' is not 'fall back to the history'. A report with no
        `current_results` list at all is read through the contract's own projection, so its failures are not invisible."""
        import contract as C
        history = [{"instance_id": "old", "status": "failed", "attempt_id": "a1"}]
        both = {"results": history, "current_results": [{"instance_id": "now", "status": "failed"}]}
        self.assertEqual(C.triage_targets(both)["results"], {"now"})
        repaired = {"results": history, "current_results": []}
        self.assertEqual(C.triage_targets(repaired)["results"], set(), "an empty current view: nothing left to triage")
        legacy = {"results": history + [{"instance_id": "old", "status": "passed", "attempt_id": "a2"},
                                       {"instance_id": "still", "status": "failed"}]}
        self.assertEqual(C.triage_targets(legacy)["results"], {"still"}, "legacy: the latest row per instance decides")

    def test_names_are_per_failure(self):
        import contract as C
        got = C.triage_targets({"current_results": [{"instance_id": "x[json]", "test_id": "m::x[json]", "status": "failed"}],
                                "current_manual_checks": [{"case": "TC-1", "instance_id": "i[a]", "result": "fail"}]})
        self.assertEqual(got["names"], [["x[json]", "m::x[json]"], ["TC-1", "i[a]"]])


class RowNamesAndSameId(unittest.TestCase):
    """t-319 F3: the ONE reading of a triage row's names and the ONE matching rule, for the S7 check, the reducer,
    gate B and the ledger."""

    def test_row_names(self):
        import contract as C
        self.assertEqual(C.row_names({"instance_id": "i[x]", "test": "m::t", "case": "TC-1"}), ["i[x]", "m::t"],
                         "a case id does not stand for the instances of that case")
        self.assertEqual(C.row_names({"case": " TC-1 "}), ["TC-1"], "a manual check has only its case")
        self.assertEqual(C.row_names({"test": "m::t"}), ["m::t"])
        for nothing in ({}, {"instance_id": " ", "case": ""}, None, "x", [], {"instance_id": None}):
            self.assertEqual(C.row_names(nothing), [], repr(nothing))

    def test_same_id_is_one_sided(self):
        import contract as C
        same = [("x[chromium]", "x"), ("x", "x[chromium]"), ("x[json]", "x[json]"), (" x[a] ", "x"),
                ("a::b[x][y]", "a::b[x]"), ("a::b[x]", "a::b[x][y]"), ("TC-1", "TC-1")]
        for a, b in same:
            self.assertTrue(C.same_id(a, b), (a, b))
        different = [("x[json]", "x[multi]"),             # two failures that share a base are never one
                     ("a::b[x][y]", "a::b"),               # stripped ONCE: the two-group id does not reach the bare base
                     ("x1", "x"), ("i10", "i1"),           # never a substring
                     ("", ""), ("  ", "  "), ("x", ""), ("", "x"),    # an empty id matches nothing, not even another one
                     (None, None), (None, "x"), ("x", 5), ([], "x")]
        for a, b in different:
            self.assertFalse(C.same_id(a, b), (a, b))
        for a, b in same:
            self.assertEqual(C.same_id(a, b), C.same_id(b, a), "the rule is symmetric")

    def test_the_four_sites_use_it(self):
        """Not one local copy of the names or the widening remains (FR-17): grep for the problem, with a positive control."""
        import re
        scripts = Path(__file__).resolve().parents[1]
        local = re.compile(r"def (_row_ids|_same_id|_row_names|_triage_row_names)\b|C\.id_spellings\(n\) or key|id_spellings\([a-z_]+\) & failures")
        for name in ("handoff_check.py", "finalize_task.py", "check_delivery.py", "ledger.py", "traceability.py"):
            text = (scripts / name).read_text(encoding="utf-8")
            self.assertIsNone(local.search(text), f"{name} holds a local copy of the names / the matching")
        control = "def _row_ids(row): pass\n"
        self.assertIsNotNone(local.search(control), "positive control: the same pattern finds a local copy")
        # t-323 A1: the sites no longer call `same_id` themselves - they read the binding built on it
        for name, call in (("handoff_check.py", "C.bind_triage("), ("finalize_task.py", "C.bind_triage("),
                           ("check_delivery.py", "C.bind_triage("), ("ledger.py", "C.triage_row_for("),
                           ("traceability.py", "C.triage_row_for("), ("factory_dashboard.py", "C.triage_row_for(")):
            self.assertIn(call, (scripts / name).read_text(encoding="utf-8"), f"{name} reads the one binding")


class LedgerAndTableReadTheSameRows(unittest.TestCase):
    """t-319 F5 (K4): the ledger, the traceability table and the judge read the triage the way gate B does - the analyst's
    `x[chromium]` rows answer the run report's `x`; two siblings never answer for each other."""

    ROWS = [{"instance_id": "ui_a[chromium]", "verdict": "ENV_ISSUE", "attempt_id": "a1"},
            {"instance_id": "api_b[json]", "verdict": "APP_BUG", "attempt_id": "a1"},
            {"instance_id": "api_b[multi]", "verdict": "TEST_BUG", "attempt_id": "a1"}]

    def test_ledger_row_by_near_id(self):
        import ledger as L
        triage = {"triage": self.ROWS}
        entry = {"file": "tests/ui.py", "marker": "ui_a", "instance_id": "ui_a", "case": "TC-1"}
        got = L._triage_row("TC-1", entry, triage, {"instance_id": "ui_a", "status": "failed", "attempt_id": "a1"})
        self.assertEqual((got or {}).get("verdict"), "ENV_ISSUE", "`ui_a` answers the analyst's `ui_a[chromium]`")
        sibling = {"file": "tests/api.py", "marker": "api_b", "instance_id": "api_b"}
        self.assertIsNone(L._triage_row("", sibling, triage, {"instance_id": "api_b", "status": "failed", "attempt_id": "a1"}),
                          "two siblings share the base: neither is the verdict of `api_b`")
        exact = {"file": "tests/api.py", "marker": "api_b", "instance_id": "api_b[json]"}
        self.assertEqual(L._triage_row("", exact, triage, {"instance_id": "api_b[json]", "status": "failed", "attempt_id": "a1"})["verdict"],
                         "APP_BUG", "the exact id picks its own row")
        # end to end, as the ledger reads a manifest test: the cmp2r UI failure reads `env_blocked`, not `failed:untriaged`
        report = {"current_results": [{"instance_id": "ui_a", "status": "failed", "attempt_id": "a1"}], "current_manual_checks": []}
        state, _detail = L.test_state(entry, report, triage)
        self.assertEqual(state.split(":")[0], "env_blocked", state)
        state, _detail = L.test_state(sibling, {"current_results": [{"instance_id": "api_b", "status": "failed", "attempt_id": "a1"}]},
                                      triage)
        self.assertNotIn(state, ("failed:APP_BUG", "failed:TEST_BUG"), "never the verdict of the first of two siblings: " + state)
        other = {"file": "tests/ui.py", "marker": "ui_a", "instance_id": "ui_a"}
        self.assertIsNone(L._triage_row("", other, triage, {"instance_id": "ui_a", "status": "failed", "attempt_id": "zzz"}),
                          "a row of another attempt is not this test's")

    def test_near_triage_row(self):
        import ledger as L
        rows = self.ROWS
        self.assertEqual(L.near_triage_row(rows, ["ui_a"])["verdict"], "ENV_ISSUE")
        self.assertEqual(L.near_triage_row(rows, ["api_b[multi]", "m::api_b[multi]"])["verdict"], "TEST_BUG", "exact beats the base")
        for names in (["api_b"], [], [""], ["nobody"], [None]):
            self.assertIsNone(L.near_triage_row(rows, names), repr(names))
        self.assertIsNone(L.near_triage_row([{"instance_id": ""}, "x", None], ["x"]), "a row with no name answers nothing")

    def test_traceability_table(self):
        import traceability as T
        story = T.Story.__new__(T.Story)
        story.triage_rows = self.ROWS
        story.run_failures = {}
        story.results = {}
        self.assertEqual(story.triage_for("ui_a").get("verdict"), "ENV_ISSUE")
        self.assertEqual(story.triage_for("ui_a[chromium]").get("verdict"), "ENV_ISSUE")
        self.assertEqual(story.triage_for("api_b"), {}, "ambiguous siblings: no verdict, never the first")
        self.assertEqual(story.triage_for("api_b[json]").get("verdict"), "APP_BUG")

    def test_judge_rows_are_the_failures_triage_targets_names(self):
        import contract as C
        import judge_results as J
        report = {"results": [{"instance_id": "old", "status": "failed"}],
                  "current_results": [{"instance_id": "ui_a", "status": "failed"}, {"instance_id": "ok", "status": "passed"},
                                      {"instance_id": "api_b[json]", "status": "error"}, {"status": "fail"}, {"status": "failed", "test": "m::t"},
                                      "x"],
                  "current_manual_checks": [{"case": "TC-5", "result": "inconclusive"}]}
        got = {C.triage_targets({"current_results": [r]})["results"].pop() for r in J._failed_rows(report)
               if C.triage_targets({"current_results": [r]})["results"]}
        self.assertEqual(got, C.triage_targets(report)["results"])
        self.assertEqual(len(J._failed_rows(report)), 4, "three named failures and the nameless one (a failure with no id)")
        self.assertEqual(J._failed_rows({"results": [{"instance_id": "old", "status": "failed"}], "current_results": []}), [],
                         "an empty current view wins over the history")
        self.assertEqual([r["instance_id"] for r in J._failed_rows({"results": [{"instance_id": "old", "status": "failed"}]})], ["old"],
                         "no current list: the legacy history is read through the projection")


class OneBinding(unittest.TestCase):
    """t-323 A1 (critic t-322 B1): ONE binding of failures to triage rows (`contract.bind_triage`). The three probes of
    the critic get the SAME answer from S7's null outcome, gate B, the ledger, the traceability table, the reducer's
    keep/archive and the dashboard card; before it each reader had its own ladder over `same_id`."""

    P1 = ({"current_results": [{"instance_id": "m::x[json]", "status": "failed"},
                               {"instance_id": "m::x[multi]", "status": "failed"}], "current_manual_checks": []},
          [{"instance_id": "m::x", "verdict": "ENV_ISSUE"}], ["m::x[json]", "m::x[multi]"])
    P2 = ({"current_results": [{"instance_id": "t::a", "case": "C1", "status": "failed"},
                               {"instance_id": "t::b", "case": "C1", "status": "failed"}],
           "current_manual_checks": [{"case": "C1", "result": "inconclusive"}]},
          [{"case": "C1", "verdict": "ENV_ISSUE"}], ["t::a", "t::b"])
    P3 = ({"current_results": [{"instance_id": "x", "status": "failed", "attempt_id": "a2"}], "current_manual_checks": []},
          [{"instance_id": "x[chromium]", "attempt_id": "a1", "verdict": "ENV_ISSUE"}], ["x"])

    @staticmethod
    def readers(report, rows, tests) -> dict:
        """What each reader says about the tests of one probe: {reader: {test: verdict row or None}} plus S7's and gate
        B's whole answer."""
        import contract as C
        import finalize_task as F
        import handoff_check as HC
        import ledger as L
        import traceability as T
        import factory_dashboard as FD
        out = {}
        task = Path(tempfile.mkdtemp(prefix="qa-onebinding-"))
        try:
            (task / "work").mkdir()
            (task / "work" / "run-report.json").write_text(json.dumps(report), encoding="utf-8")
            (task / "work" / "triage.json").write_text(json.dumps({"triage": rows}), encoding="utf-8")
            untriaged, _unnamed, ambiguous, multiple = HC._untriaged_failures(HC.Artifacts(task), rows)
            out["s7"] = {"untriaged": untriaged, "ambiguous": [(n, k) for n, k in ambiguous], "multiple": multiple}
            reasons = D.triage_reasons(task)
            out["gate_b"] = {"untriaged": sorted(r.split("the failure ")[1].split(" has no verdict")[0] for r in reasons
                                                 if "has no verdict" in r and "the failure " in r),
                             "ambiguous": sorted(r.split("the row ")[1].split(" names")[0] for r in reasons if "is a verdict for none" in r),
                             "multiple": sorted(r.split("the failure ")[1].split(" in triage.json")[0] for r in reasons
                                                if " rows answer the failure " in r)}
            failures = C.triage_failures(report)[0]
            current = C.current_instance_results(report)
            attempts = {k: str(r.get("attempt_id") or "") for k, r in current.items()}
            out["ledger"] = {t: (L.near_triage_row(rows, [t], attempts.get(t, ""), failures,
                                                   C.result_status(current.get(t) or {})) or {}).get("verdict") for t in tests}
            story = T.Story.__new__(T.Story)
            story.triage_rows, story.run_failures, story.results = C.triage_rows({"triage": rows}), failures, current
            out["traceability"] = {t: story.triage_for(t).get("verdict") for t in tests}
            reducer = {"name": "finalize_task", "sources": []}
            whole = dict({"reducer": reducer, "results": [], "manual_checks": [], "execution_status": "failed"}, **report)
            saved = F.reduce
            F.reduce = lambda t: (whole, {"schema_version": 2, "task_id": t.name, "triage": [], "reducer": reducer})
            try:
                F.refresh(task)
            finally:
                F.reduce = saved
            out["refresh_kept"] = len(json.loads((task / "work" / "triage.json").read_text(encoding="utf-8"))["triage"])
            manifest = {"tests": [{"instance_id": t, "file": "f.py", "marker": t, "case": "C1"} for t in tests]}
            proj = FD.story_projection({"manifest": manifest, "report": report, "triage_doc": {"triage": rows}}, {}, {}, [], [])
            out["dashboard"] = {r["instance"]: r["verdict"] for r in proj["rows"]}
            return out
        finally:
            shutil.rmtree(task, ignore_errors=True)

    def test_probe_1_two_siblings_and_one_base_row_is_ambiguous_everywhere(self):
        got = self.readers(*self.P1)
        self.assertEqual(got["s7"]["untriaged"], [], "the failures are not 'unjudged' - the row that names both speaks")
        self.assertEqual(got["s7"]["ambiguous"], [(["m::x"], ["m::x[json]", "m::x[multi]"])], "S7 refuses, naming row and candidates")
        self.assertEqual(got["gate_b"]["ambiguous"], ["m::x"], "gate B: the same refusal")
        self.assertEqual(got["ledger"], {"m::x[json]": None, "m::x[multi]": None})
        self.assertEqual(got["traceability"], {"m::x[json]": None, "m::x[multi]": None})
        self.assertEqual(got["dashboard"], {"m::x[json]": "", "m::x[multi]": ""})
        self.assertEqual(got["refresh_kept"], 1, "the reducer keeps the ambiguous row: S7 names it, the analyst fixes it")

    def test_probe_2_a_case_row_never_covers_automated_failures(self):
        got = self.readers(*self.P2)
        self.assertEqual(got["s7"]["untriaged"], ["t::a", "t::b"], "the manual check C1 is answered, the two automated ones are not")
        self.assertEqual(got["gate_b"]["untriaged"], ["t::a", "t::b"])
        self.assertEqual(got["ledger"], {"t::a": None, "t::b": None})
        self.assertEqual(got["traceability"], {"t::a": None, "t::b": None})
        self.assertEqual(got["dashboard"], {"t::a": "", "t::b": ""})
        self.assertEqual(got["refresh_kept"], 1, "the row answers the manual check")
        # control: a row naming t::a answers t::a, and only it; the case row's manual check stays untriaged without its row
        report, _rows, tests = self.P2
        got = self.readers(report, [{"instance_id": "t::a", "verdict": "APP_BUG"}], tests)
        self.assertEqual(got["s7"]["untriaged"], ["C1", "t::b"])
        self.assertEqual((got["ledger"]["t::a"], got["ledger"]["t::b"]), ("APP_BUG", None))

    def test_probe_3_a_row_of_another_attempt_binds_nowhere(self):
        got = self.readers(*self.P3)
        self.assertEqual(got["s7"]["untriaged"], ["x"])
        self.assertEqual(got["gate_b"]["untriaged"], ["x"])
        self.assertEqual(got["ledger"], {"x": None})
        self.assertEqual(got["traceability"], {"x": None})
        self.assertEqual(got["dashboard"], {"x": ""})
        self.assertEqual(got["refresh_kept"], 0, "the stale row is archived")
        # control: the same row of the failure's own attempt binds in all of them
        report, rows, tests = self.P3
        got = self.readers(report, [dict(rows[0], attempt_id="a2")], tests)
        self.assertEqual((got["s7"]["untriaged"], got["gate_b"]["untriaged"]), ([], []))
        self.assertEqual((got["ledger"]["x"], got["traceability"]["x"], got["dashboard"]["x"]), ("ENV_ISSUE",) * 3)

    def test_the_card_shows_a_parameter_row(self):
        """A2: a row `x[chromium]` is the verdict of the run report's failure `x` on the dashboard card."""
        import factory_dashboard as FD
        report = {"current_results": [{"instance_id": "x", "status": "failed"}], "current_manual_checks": []}
        manifest = {"tests": [{"instance_id": "x", "file": "f.py", "marker": "x", "case": "C1"}]}
        proj = FD.story_projection({"manifest": manifest, "report": report,
                                    "triage_doc": {"triage": [{"instance_id": "x[chromium]", "verdict": "ENV_ISSUE"}]}},
                                   {}, {}, [], [])
        self.assertEqual([(r["instance"], r["verdict"], r["state"]) for r in proj["rows"]], [("x", "ENV_ISSUE", "env")])

    def test_bind_triage_edges(self):
        import contract as C
        failures, unnamed = C.triage_failures({"current_results": [
            {"instance_id": "a[1]", "test_id": "m::a[1]", "case": "C1", "status": "failed", "attempt_id": "a1"},
            {"case": "C9", "status": "failed"}, {"case": "C9", "status": "failed"}, {"status": "failed"}],
            "current_manual_checks": [{"case": "C1", "result": "fail"}]})
        self.assertEqual(sorted(failures), [("manual", "C1"), ("result", "a[1]")])
        self.assertEqual(failures[("result", "a[1]")]["names"], ["a[1]", "m::a[1]"], "a result failure's names carry no `case`")
        # BL-2 (critic t-327): a result row with only a `case` has no name: fail-closed, and two such rows are two
        # failures (two notes), never one merged key
        self.assertEqual(len(unnamed), 3, unnamed)
        self.assertEqual(sum("has no instance_id, test_instance_id, test_id or test" in n for n in unnamed), 3)
        rows = [{"instance_id": "a[1]", "case": "C1", "verdict": "APP_BUG"}, {"case": "C1", "verdict": "ENV_ISSUE"},
                {"case": "C9", "verdict": "ENV_ISSUE"}]
        got = C.bind_triage(failures, rows)
        self.assertEqual({k: [r["verdict"] for r in v] for k, v in got["matched"].items()},
                         {("manual", "C1"): ["ENV_ISSUE"], ("result", "a[1]"): ["APP_BUG"]},
                         "a row with BOTH instance_id and case binds by the instance; the case row binds the manual check only")
        self.assertEqual(got["ambiguous"], [])
        none = C.bind_triage(failures, [])
        self.assertEqual(none["matched"], {k: [] for k in failures}, "an empty list of rows: every failure untriaged")
        self.assertEqual(C.bind_triage({}, rows)["matched"], {})
        self.assertEqual(C.bind_triage(failures, [None, "x", {}, {"instance_id": " "}])["ambiguous"], [], "no name, no binding")
        self.assertEqual(C.triage_failures(None), ({}, []))

    def test_the_sentinel_finds_the_five_readers(self):
        """The class sentinel (FR-17: grep for the problem): no reader of the triage keeps its own binding by
        `triage_by_instance_attempt` / `triage_by_test` any more; positive control with the same pattern."""
        import re
        scripts = Path(__file__).resolve().parents[1]
        own = re.compile(r"triage_by_instance_attempt\(|triage_by_test\(|\.triage_by_instance\b")
        for name in ("handoff_check.py", "finalize_task.py", "check_delivery.py", "ledger.py", "traceability.py",
                     "factory_dashboard.py"):
            self.assertIsNone(own.search((scripts / name).read_text(encoding="utf-8")), f"{name} binds rows on its own")
        self.assertIsNotNone(own.search("by_attempt = C.triage_by_instance_attempt(doc)"), "positive control: the pattern finds the old form")
        import contract as C
        self.assertFalse(hasattr(C, "triage_by_test") or hasattr(C, "triage_by_instance_attempt"),
                         "t-323 F4: the two dead readers are deleted, not kept for a caller that does not exist")
        self.assertIsNone(own.search((scripts / "contract.py").read_text(encoding="utf-8")), "and nothing in contract.py defines them")


class SiblingNeverAVerdict(unittest.TestCase):
    """t-323 BL-1 (critic t-327): the live cmp2r regression. Two PASSED instances read `failed:APP_BUG` through their
    failing sibling `[json]` because the manifest's base `test` (no `[param]`) was among the names the ledger asked
    with. Every fixture here carries that base `test` field - the ledger fixtures of attempt 1 lacked it, which is why
    the tests missed it."""

    MOD = "tests.workflow.test_validate"
    BASE = "test_validate_rejects_bad_input_with_same_code_as_put"
    FILE = "testproject1_test_harness/tests/workflow/test_validate.py"

    def entry(self, param: str, status: str) -> dict:
        return {"case": "TC_010", "file": self.FILE, "marker": "TC_010", "test": self.BASE,
                "instance_id": f"{self.BASE}[{param}]", "status": status}

    def report_and_triage(self):
        def row(param, status):
            return {"instance_id": f"{self.BASE}[{param}]", "test_id": f"{self.MOD}::{self.BASE}[{param}]",
                    "status": status, "attempt_id": "a1"}
        report = {"current_results": [row("json", "failed"), row("unparseable", "passed"), row("autonomous", "passed")],
                  "current_manual_checks": []}
        triage = {"triage": [{"instance_id": f"{self.BASE}[json]", "test": f"{self.MOD}::{self.BASE}[json]",
                              "verdict": "APP_BUG", "attempt_id": "a1"}]}
        return report, triage

    def test_the_ledger_reads_the_sibling_and_only_the_sibling(self):
        import ledger as L
        report, triage = self.report_and_triage()
        manifest = {"tests": [self.entry(p, "red" if p == "json" else "green") for p in ("json", "unparseable", "autonomous")]}
        states = {t["instance_id"]: L.test_state(t, report, triage, None, manifest)[0] for t in manifest["tests"]}
        self.assertEqual(states[f"{self.BASE}[json]"], "failed:APP_BUG", "the failing instance keeps its verdict")
        for param in ("unparseable", "autonomous"):
            self.assertFalse(states[f"{self.BASE}[{param}]"].startswith("failed"),
                             f"a PASSED sibling is never the verdict of its failing sibling: {states}")

    def test_traceability_and_the_card_say_nothing_for_the_passed_siblings(self):
        import contract as C
        import factory_dashboard as FD
        import traceability as T
        report, triage = self.report_and_triage()
        story = T.Story.__new__(T.Story)
        story.triage_rows, story.run_failures = C.triage_rows(triage), C.triage_failures(report)[0]
        story.results = C.current_instance_results(report)
        # t-128 (fix round 2): `triage_for` asks the run join (`_run_rows`), which reads the story's manifest and artifacts
        story.manifest, story.artifacts = {"tests": [self.entry(p, "red") for p in ("json", "unparseable", "autonomous")]}, None
        for param, verdict in (("json", "APP_BUG"), ("unparseable", None), ("autonomous", None)):
            entry = self.entry(param, "red")
            self.assertEqual(story.triage_for(f"{self.BASE}[{param}]", entry).get("verdict"), verdict, param)
        manifest = {"tests": [self.entry(p, "green") for p in ("json", "unparseable", "autonomous")]}
        proj = FD.story_projection({"manifest": manifest, "report": report, "triage_doc": triage}, {}, {}, [], [])
        self.assertEqual({r["instance"].split("[")[1].rstrip("]"): r["verdict"] for r in proj["rows"]},
                         {"json": "APP_BUG", "unparseable": "", "autonomous": ""})

    def test_the_rule_in_the_contract(self):
        import contract as C
        failures = C.triage_failures({"current_results": [
            {"instance_id": "t[json]", "status": "failed", "attempt_id": "a1"}]})[0]
        rows = [{"instance_id": "t[json]", "verdict": "APP_BUG", "attempt_id": "a1"}]
        # (a) the alias without the `[param]` group of the asked instance's own id is never used
        self.assertIsNone(C.triage_row_for(failures, rows, ["t[unparseable]", "t", "f.py::t"], "a1"))
        self.assertIsNone(C.triage_row_for(failures, rows, ["t[unparseable]", "t"], "a1", "failed"),
                          "(a) holds whatever the status: the base never carries the sibling's row over")
        # (b) a test with its own non-failed result is never moved onto a failure key
        self.assertIsNone(C.triage_row_for(failures, rows, ["t"], "a1", "passed"))
        # controls: the failing instance itself, and a base-only ask over the one failure with no status given
        self.assertEqual(C.triage_row_for(failures, rows, ["t[json]", "t"], "a1", "failed")["verdict"], "APP_BUG")
        self.assertEqual(C.triage_row_for(failures, rows, ["t"], "a1")["verdict"], "APP_BUG",
                         "an ask that has no instance of its own still reads the one failure it stands for")
        # (b) with a row that names the passed test: its own FLAKY row still answers it
        flaky = rows + [{"instance_id": "t[unparseable]", "verdict": "FLAKY", "fix_result": "fixed"}]
        self.assertEqual(C.triage_row_for(failures, flaky, ["t[unparseable]", "t"], "a1", "passed")["verdict"], "FLAKY")

    def test_p8_two_failures_sharing_a_base_test_and_a_row_for_one_of_them(self):
        """critic P8: two failures that both carry the base `test: m::x`, one row `m::x[json]`: it binds [json] ONLY.
        t-323 F7 (the pin inverted): the critic's row ALSO carries that base `test: m::x`, and the EXACT step bound it
        to both siblings through their shared base `test` - [json] and [multi] both read APP_BUG. The EXACT step now
        matches instance ids only: a result row's base `test` never binds."""
        import contract as C
        import ledger as L
        report = {"current_results": [
            {"instance_id": "m::x[json]", "test": "m::x", "status": "failed", "attempt_id": "a1"},
            {"instance_id": "m::x[multi]", "test": "m::x", "status": "failed", "attempt_id": "a1"}],
            "current_manual_checks": []}
        for row in ({"instance_id": "m::x[json]", "verdict": "APP_BUG", "attempt_id": "a1"},
                    {"instance_id": "m::x[json]", "test": "m::x", "verdict": "APP_BUG", "attempt_id": "a1"}):
            triage = {"triage": [row]}
            failures = C.triage_failures(report)[0]
            got = C.bind_triage(failures, C.triage_rows(triage))
            self.assertEqual({k[1]: [r["verdict"] for r in v] for k, v in got["matched"].items()},
                             {"m::x[json]": ["APP_BUG"], "m::x[multi]": []}, row)
            self.assertEqual((got["ambiguous"], got["multiple"]), ([], {}), row)
            for param, verdict in (("json", "failed:APP_BUG"), ("multi", "failed:untriaged")):
                entry = {"file": "f.py", "marker": "x", "test": "m::x", "instance_id": f"m::x[{param}]", "critic_verdict": "approved"}
                self.assertEqual(L.test_state(entry, report, triage)[0], verdict, (param, row))
            # every reader, the same answer: [multi] has no verdict, [json] has its own
            seen = OneBinding.readers(report, [row], ["m::x[json]", "m::x[multi]"])
            self.assertEqual((seen["s7"]["untriaged"], seen["gate_b"]["untriaged"]), (["m::x[multi]"], ["m::x[multi]"]), row)
            for reader in ("ledger", "traceability"):
                self.assertEqual(seen[reader], {"m::x[json]": "APP_BUG", "m::x[multi]": None}, (reader, row))
            self.assertEqual(seen["dashboard"], {"m::x[json]": "APP_BUG", "m::x[multi]": ""}, row)
        # control: a row that names only the shared base is ambiguous between the siblings, never the verdict of both
        got = C.bind_triage(C.triage_failures(report)[0], [{"instance_id": "m::x", "verdict": "APP_BUG"}])
        self.assertEqual(([v for v in got["matched"].values() if v], len(got["ambiguous"])), ([], 1))
        # a manual check's `case` matching is untouched: its names are all EXACT ones
        manual = C.triage_failures({"current_manual_checks": [{"case": "C1", "test": "m::x", "result": "fail"}]})[0]
        self.assertEqual(manual[("manual", "C1")]["ids"], ["C1", "m::x"])
        self.assertEqual(C.bind_triage(manual, [{"case": "C1", "verdict": "ENV_ISSUE"}])["matched"][("manual", "C1")][0]["verdict"],
                         "ENV_ISSUE")

    def test_bl3_the_own_id_without_a_param_group_is_never_dropped(self):
        """t-323 BL-3 (the critic's control pass, the live cmp2r UI shape): the manifest's `instance_id: t`, the run
        report's `test_id: tests...::t[chromium]` (pytest-playwright adds `[chromium]`). Attempt 2 applied rule (a)
        between EVERY pair of asked names, so `t` was dropped as the base of `...::t[chromium]`, and on this GREEN
        test a `FLAKY not_fixed` row naming `t` exactly was lost: the ledger read `passed_green`, the dashboard ''
        (HEAD: `not_verified_flaky` / FLAKY). Now only a name that is the base of the asked instance's OWN id
        (`names[0]`) is dropped, and `names[0]` never is."""
        import contract as C
        import factory_dashboard as FD
        import ledger as L
        import traceability as T
        t = "test_version_history_button_accessible_from_visual_editor"
        file = "testproject1_test_harness/tests/ui/workflows/test_workflow_version_history.py"
        entry = {"instance_id": t, "test": t, "file": file, "selector": f"{file}::{t}", "marker": "TP1-15045_TC_004",
                 "case": "TP1-15045_TC_004", "critic_verdict": "approved"}
        res = {"instance_id": t, "test_id": f"tests.ui.workflows.test_workflow_version_history::{t}[chromium]",
               "status": "passed", "attempt_id": "a1", "case": "TP1-15045_TC_004"}
        report = {"current_results": [res], "results": [res], "current_manual_checks": []}
        # the exact row `t` (the DoD pin) and the analyst's `t[chromium]` spelling (t-309): the readers agree on both
        for row_id in (t, t + "[chromium]"):
            triage = {"triage": [{"instance_id": row_id, "attempt_id": "a1", "verdict": "FLAKY", "fix_result": "not_fixed",
                                  "mechanism": "m"}]}
            self.assertEqual(L.test_state(entry, report, triage, None, {"tests": [entry]})[0], "not_verified_flaky", row_id)
            proj = FD.story_projection({"manifest": {"tests": [entry]}, "report": report, "triage_doc": triage}, {}, {}, [], [])
            self.assertEqual([r["verdict"] for r in proj["rows"]], ["FLAKY"], row_id)
            story = T.Story.__new__(T.Story)
            story.triage_rows, story.run_failures = C.triage_rows(triage), C.triage_failures(report)[0]
            story.results = C.current_instance_results(report)
            story.manifest, story.artifacts = {"tests": [entry]}, None   # t-128: the run join `triage_for` asks reads both
            self.assertEqual(story.triage_for(t, entry).get("verdict"), "FLAKY", row_id)

    def test_bl3_the_rule_in_the_contract(self):
        import contract as C
        fails = C.triage_failures({"current_results": [{"instance_id": "x", "status": "failed", "attempt_id": "a1"}]})[0]
        row = [{"instance_id": "x[chromium]", "attempt_id": "a1", "verdict": "ENV_ISSUE"}]
        # the constructed input of the critic's control pass: `x` has no param group, so nothing is dropped
        self.assertIs(C.triage_row_for(fails, row, ["x", "f.py::x[chromium]"], "a1", "failed"), row[0])
        self.assertIs(C.triage_row_for(fails, row, ["x"], "a1", "failed"), row[0])
        # the own id is never dropped, a base of it always is (BL-1 stays fixed), an alias of ANOTHER name is not
        # judged against that name: only `names[0]` decides
        json_fail = C.triage_failures({"current_results": [{"instance_id": "t[json]", "status": "failed", "attempt_id": "a1"}]})[0]
        json_row = [{"instance_id": "t[json]", "verdict": "APP_BUG", "attempt_id": "a1"}]
        self.assertIsNone(C.triage_row_for(json_fail, json_row, ["t[unparseable]", "f.py::t[unparseable]", "t", "f.py::t"],
                                           "a1", "failed"))
        self.assertEqual(C.triage_row_for(json_fail, json_row, ["t[json]", "t"], "a1", "failed")["verdict"], "APP_BUG")
        # empty names: None, as before
        for nothing in ([], [""], ["  "], [None, 5]):
            self.assertIsNone(C.triage_row_for(fails, row, nothing, "a1", "failed"), repr(nothing))

    def test_t329_triage_row_for_reads_ids_in_its_exact_step_like_bind_triage(self):
        """t-329 (B-270 a): the single-test reader's EXACT step read a failure's `names` - which carry the base `test`
        its siblings share - where `bind_triage` reads `ids` (t-323 F7). A name that is only that base was then "exact"
        for the ONE sibling that listed it and the answer was that sibling's row: a verdict nobody gave this test."""
        import contract as C
        report = {"current_results": [
            {"instance_id": "m::x[json]", "test": "m::x", "status": "failed", "attempt_id": "a1"},
            {"instance_id": "m::x[multi]", "status": "failed", "attempt_id": "a1"}]}      # no base `test` on this one
        failures = C.triage_failures(report)[0]
        rows = [{"instance_id": "m::x[json]", "verdict": "APP_BUG", "attempt_id": "a1"}]
        self.assertEqual(failures[("result", "m::x[json]")]["ids"], ["m::x[json]"], "fixture: the base is in names, not in ids")
        self.assertIn("m::x", failures[("result", "m::x[json]")]["names"])
        # the base alone stands for two failures: ambiguous, not the first sibling's row
        self.assertIsNone(C.triage_row_for(failures, rows, ["m::x"], "a1", "failed"))
        # controls: a sibling asked by its own instance id still gets its own row, the other none
        self.assertEqual(C.triage_row_for(failures, rows, ["m::x[json]", "m::x"], "a1", "failed")["verdict"], "APP_BUG")
        self.assertIsNone(C.triage_row_for(failures, rows, ["m::x[multi]"], "a1", "failed"))
        # a failure dict in the older shape (no `ids`) is still read by its names
        legacy = {("result", "x"): {"names": ["x"], "attempts": {"a1"}, "old": set()}}
        self.assertEqual(C.triage_row_for(legacy, [{"instance_id": "x", "verdict": "APP_BUG", "attempt_id": "a1"}],
                                          ["x"], "a1", "failed")["verdict"], "APP_BUG")


class MultipleAndAttemptRules(unittest.TestCase):
    """t-323 F1 (more than one row for one failure is one class) and F3 (a row with no attempt answers only the latest
    attempt of its instance), through every reader."""

    def test_f1_two_rows_for_one_failure_are_refused_by_s7_and_gate_b_and_answer_nobody_else(self):
        report = {"current_results": [{"instance_id": "x", "status": "failed"}], "current_manual_checks": []}
        rows = [{"instance_id": "x", "verdict": "APP_BUG"}, {"instance_id": "x[chromium]", "verdict": "ENV_ISSUE"}]
        got = OneBinding.readers(report, rows, ["x"])
        self.assertEqual(got["s7"]["multiple"], [("x", 2)], "S7 refuses it: it used to accept")
        self.assertEqual(got["s7"]["untriaged"], [], "...and not as 'no row'")
        self.assertEqual(got["gate_b"]["multiple"], ["x"], "gate B says 2 rows answer it, not 'no verdict'")
        self.assertEqual(got["gate_b"]["untriaged"], [])
        self.assertEqual((got["ledger"]["x"], got["traceability"]["x"], got["dashboard"]["x"]), (None, None, ""),
                         "no reader takes the first of several")
        self.assertEqual(got["refresh_kept"], 2, "the reducer keeps both: S7 names the failure and the analyst keeps one")
        # control: one row for it is answered in all of them
        got = OneBinding.readers(report, rows[:1], ["x"])
        self.assertEqual((got["s7"]["multiple"], got["gate_b"]["multiple"]), ([], []))
        self.assertEqual((got["ledger"]["x"], got["traceability"]["x"], got["dashboard"]["x"]), ("APP_BUG",) * 3)

    def test_f3_a_row_with_no_attempt_never_answers_an_older_attempt(self):
        old = {"results": [{"instance_id": "x", "status": "failed", "attempt_id": "a1"},
                           {"instance_id": "x", "status": "passed", "attempt_id": "a2"}],
               "current_results": [{"instance_id": "x", "status": "failed", "attempt_id": "a1"}], "current_manual_checks": []}
        rows = [{"instance_id": "x[chromium]", "verdict": "ENV_ISSUE"}]          # no attempt_id
        got = OneBinding.readers(old, rows, ["x"])
        self.assertEqual((got["s7"]["untriaged"], got["gate_b"]["untriaged"]), (["x"], ["x"]))
        self.assertEqual((got["ledger"]["x"], got["traceability"]["x"], got["dashboard"]["x"]), (None, None, ""))
        self.assertEqual(got["refresh_kept"], 0, "the reducer archives it: it answers no current failure")
        # a row that names the attempt still answers it (the old attempt IS this failure's)
        got = OneBinding.readers(old, [dict(rows[0], attempt_id="a1")], ["x"])
        self.assertEqual((got["s7"]["untriaged"], got["ledger"]["x"]), ([], "ENV_ISSUE"))
        # control: the same row against the LATEST recorded attempt binds, in all six
        latest = dict(old, results=old["results"][:1])
        got = OneBinding.readers(latest, rows, ["x"])
        self.assertEqual((got["s7"]["untriaged"], got["gate_b"]["untriaged"]), ([], []))
        self.assertEqual((got["ledger"]["x"], got["traceability"]["x"], got["dashboard"]["x"]), ("ENV_ISSUE",) * 3)
        self.assertEqual(got["refresh_kept"], 1)


if __name__ == "__main__":
    unittest.main()
