"""`contract.case_index` refuses with EVERY case-identity problem of a story (K1, C4-5).

The index used to raise at the first file whose front-matter id differed from its file name, or
whose identity another file already held with other bytes, and the other files' problems waited
for the next round. The per-file checks do not read one another, so they are collected over the
whole story and refused together, in file order. The BEFORE texts are the verbatim output of the
same calls on 72e2f22c (the commit this node was cut from).
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import contract as C

HEAD = "{n} problems - the request is refused whole, every one is listed:"


def case(path: Path, cid: str, body: str = "body", area: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    front = f"id: {cid}\n" + (f"area: {area}\n" if area else "")
    path.write_text(f"---\n{front}---\nPlan row: TS-1\n# {body}\n", encoding="utf-8")


class CaseIndexRefusal(unittest.TestCase):
    def story(self, files):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        art = Path(tmp.name) / "QA-1"
        for rel, cid, body, area in files:
            case(art / "work" / "test-cases" / rel, cid, body, area)
        return art

    def refusal(self, art):
        with self.assertRaises(ValueError) as caught:
            C.case_index(art)
        return str(caught.exception).replace("\\", "/").replace(str(art).replace("\\", "/"), "<ART>")

    def mismatch(self, name, declared):
        return f"case identity mismatch: <ART>/work/test-cases/{name}.md declares {declared} but source identity is {name}"

    def test_a_sound_story_is_indexed_and_an_empty_one_is_empty(self):
        art = self.story([("TC-001.md", "TC-001", "a", ""), ("TC-002.md", "TC-002", "b", "")])
        self.assertEqual(["TC-001", "TC-002"], sorted(C.case_index(art)))
        self.assertEqual([], list(C.case_index(self.story([]))))

    def test_one_failing_file_keeps_its_old_text_byte_for_byte(self):
        # BEFORE: the same sentence, raised at that file
        art = self.story([("TC-001.md", "TC-009", "a", "")])
        self.assertEqual(self.mismatch("TC-001", "TC-009"), self.refusal(art))
        art = self.story([("a/TC-002.md", "TC-002", "left", "x"), ("b/TC-002.md", "TC-002", "right", "x")])
        text = self.refusal(art)
        self.assertTrue(text.startswith("case identity collision x/TC-002: <ART>/work/test-cases/a/TC-002.md ("), text)
        self.assertEqual(1, text.count("case identity"))
        self.assertNotIn("problems", text)

    def test_two_files_with_a_problem_each_are_one_refusal_in_file_order(self):
        # BEFORE: only the first mismatch (TC-001) was told; TC-003 waited for the next round
        art = self.story([("TC-001.md", "TC-009", "a", ""), ("TC-003.md", "TC-008", "c", "")])
        self.assertEqual(f"{HEAD.format(n=2)}\n1) {self.mismatch('TC-001', 'TC-009')}\n"
                         f"2) {self.mismatch('TC-003', 'TC-008')}", self.refusal(art))

    def test_a_mismatch_and_a_collision_are_both_told_in_chain_order(self):
        # BEFORE: only the collision (the first failure in file order); the mismatch of TC-001 was hidden
        # The order is the code-point order of the paths (contract.case_glob), the same on every
        # filesystem: `TC-001.md` sorts before `a/` (uppercase T < lowercase a), so the mismatch of
        # TC-001 is told first and the collision of the two TC-002 files second. (t-887: the order
        # used to be the platform's - case-folded on Windows, which put the collision first.)
        art = self.story([("TC-001.md", "TC-009", "a", ""),
                          ("a/TC-002.md", "TC-002", "left", "x"), ("b/TC-002.md", "TC-002", "right", "x")])
        lines = self.refusal(art).split("\n")
        self.assertEqual(HEAD.format(n=2), lines[0])
        self.assertEqual(f"1) {self.mismatch('TC-001', 'TC-009')}", lines[1])
        self.assertTrue(lines[2].startswith("2) case identity collision x/TC-002: "), lines[2])
        self.assertEqual(3, len(lines))

    def test_the_walk_is_sorted_by_code_point_not_by_creation_order_or_case(self):
        # created TC-003 first, then TC-001: the refusal still lists TC-001 first
        art = self.story([("TC-003.md", "TC-008", "c", ""), ("TC-001.md", "TC-009", "a", "")])
        self.assertEqual(f"{HEAD.format(n=2)}\n1) {self.mismatch('TC-001', 'TC-009')}\n"
                         f"2) {self.mismatch('TC-003', 'TC-008')}", self.refusal(art))
        # names differing by case sort by code point: `B/` before `a/` (Windows' own order is a, B)
        art = self.story([("a/TC-001.md", "TC-001", "a", ""), ("B/TC-002.md", "TC-002", "b", "")])
        found = [p.relative_to(art / "work" / "test-cases").as_posix() for p in C.case_glob(art / "work" / "test-cases", art)]
        self.assertEqual(["B/TC-002.md", "a/TC-001.md"], found)

    def test_one_file_with_both_problems_names_both(self):
        # the mismatch and the collision of ONE file are two checks of the loop body
        art = self.story([("a/TC-002.md", "TC-002", "left", "x"), ("b/TC-002.md", "TC-007", "right", "x")])
        lines = self.refusal(art).split("\n")
        self.assertEqual(HEAD.format(n=2), lines[0])
        self.assertIn("declares TC-007 but source identity is TC-002", lines[1])
        self.assertTrue(lines[2].startswith("2) case identity collision x/TC-002: "), lines[2])

    def test_the_class_is_value_error_for_every_caller_that_catches_it(self):
        art = self.story([("TC-001.md", "TC-009", "a", ""), ("TC-003.md", "TC-008", "c", "")])
        try:
            C.case_index(art)
        except ValueError:
            pass
        else:
            self.fail("a joint refusal must still be a ValueError")


class PrefixValue(unittest.TestCase):
    """C4-9 (t-898): `executor unavailable: <value>` is read by ONE helper, `contract.prefix_value`; the reader
    (`handed_profiles`) holds a profile only where the writer would have accepted the block (one token)."""

    PROBES = (
        ("executor unavailable: e2e-ui\nand also lift TC-3", None),   # the critic's probes of t-894 (P1)
        ("executor unavailable: e2e ui", None),
        ("executor unavailable: : x", None),
        ("executor unavailable:", None),
        ("executor unavailable: e2e-ui", "e2e-ui"),
        ("executor unavailable: `e2e-ui`", "e2e-ui"),
        ('EXECUTOR   unavailable:  "e2e-ui"\n', "e2e-ui"),
    )

    def test_the_helper_gives_one_token_or_none(self):
        for text, value in self.PROBES:
            with self.subTest(text=text):
                self.assertEqual(value, C.prefix_value(text, C.HANDED_MATCH_PREFIX))

    def test_the_helper_refuses_what_is_not_the_prefix_and_never_raises(self):
        for text in (None, "", "the executor unavailable: x", "executor unavailable", "stand gap: TC-7"):
            with self.subTest(text=text):
                self.assertIsNone(C.prefix_value(text, C.HANDED_MATCH_PREFIX))
        self.assertEqual("TC-7", C.prefix_value("Stand  gap: TC-7", C.STAND_GAP_MATCH_PREFIX))

    def test_the_reader_holds_a_profile_only_for_a_value_the_helper_gives(self):
        for text, value in self.PROBES:
            with self.subTest(text=text):
                record = {"stage_overrides": [{"stage": "S5", "match": text, "decision": "I run them", "at": "t"}]}
                self.assertEqual([value] if value else [], sorted(C.handed_profiles(record)))

    def test_the_reader_keeps_its_other_conditions(self):
        base = {"stage": "S5", "match": "executor unavailable: e2e-ui", "decision": "I run them", "at": "t"}
        self.assertEqual({"e2e-ui": {"words": "I run them", "at": "t"}}, C.handed_profiles({"stage_overrides": [base]}))
        for changed in ({"decision": ""}, {"stage": "S8"}):
            self.assertEqual({}, C.handed_profiles({"stage_overrides": [dict(base, **changed)]}))
        self.assertEqual({}, C.handed_profiles({"stage_overrides": [3, None]}))
        self.assertEqual({}, C.handed_profiles(None))


def _register(columns, rows, claims=None):
    """A register text: `columns` the `## Register` header, `rows` lists of cells, `claims` (header, rows) or None."""
    out = ["## Register", "", "| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    out += ["| " + " | ".join(cells) + " |" for cells in rows]
    if claims:
        header, body = claims
        out += ["", "## Behaviour claims", "", "| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        out += ["| " + " | ".join(cells) + " |" for cells in body]
    return "\n".join(out) + "\n"


SEVEN = ["R", "Requirement", "source", "derived_from", "verifiable", "ac_ref", "observable"]
EIGHT = SEVEN + ["impact"]
NINE = EIGHT + ["delta"]


class RegisterDeltaAndClaimOrigin(unittest.TestCase):
    """G1-3: the register's `delta` column and the claims' `origin` column - both read by their header only."""

    def test_a_register_of_seven_eight_and_nine_columns_is_read(self):
        row7 = ["R-1", "x", "story", "-", "yes", "AC-1", "diff:a.py:1"]
        for columns, cells in ((SEVEN, row7), (EIGHT, row7 + ["degraded"]), (NINE, row7 + ["degraded", "new"])):
            rows = C.register_rows(_register(columns, [cells]))
            self.assertEqual(["R-1"], [r["r"] for r in rows], columns)
            self.assertEqual("diff:a.py:1", rows[0]["observable"], columns)
            self.assertEqual("story", rows[0]["source"], columns)
        self.assertIsNone(C.register_rows(_register(SEVEN, [row7]))[0]["delta"])
        self.assertIsNone(C.register_rows(_register(EIGHT, [row7 + ["degraded"]]))[0]["delta"])
        self.assertEqual("new", C.register_rows(_register(NINE, [row7 + ["degraded", "new"]]))[0]["delta"])

    def test_delta_is_read_by_its_header_never_by_position_or_prefix(self):
        row = ["R-1", "x", "story", "-", "yes", "AC-1", "diff:a.py:1", "degraded", "changed"]
        # a project's own ninth column, called something else: never `delta`
        for header in ("note", "deltas", "delta (new|changed|unchanged)", "Δ"):
            rows = C.register_rows(_register(EIGHT + [header], [row]))
            self.assertIsNone(rows[0]["delta"], header)
        # the header may stand anywhere and be written `Delta`: the name decides
        moved = SEVEN + ["Delta", "impact"]
        self.assertEqual("unchanged", C.register_rows(_register(moved, [row[:7] + ["unchanged", "degraded"]]))[0]["delta"])

    def test_a_short_row_of_a_register_that_has_the_column_has_an_empty_delta(self):
        rows = C.register_rows(_register(NINE, [["R-1", "x", "story", "-", "yes", "AC-1", "diff:a.py:1"]]))
        self.assertEqual("", rows[0]["delta"])
        self.assertEqual("invalid", C.delta_state(rows[0]))

    def test_delta_state_has_five_words_and_errs_toward_the_count(self):
        want = {"new": "new", "changed": "changed", "unchanged": "unchanged", "`new`": "new", " changed ": "changed",
                "New": "invalid", "CHANGED": "invalid", "same": "invalid", "n/a": "invalid", "": "invalid", "-": "invalid",
                "unchanged_unevidenced": "invalid", "unchanged (current-code:a.py:1)": "invalid"}
        for cell, state in want.items():
            rows = C.register_rows(_register(NINE, [["R-1", "x", "story", "-", "yes", "AC-1", "current-code:a.py:1", "degraded", cell]]))
            self.assertEqual(state, C.delta_state(rows[0]), repr(cell))
        self.assertEqual("absent", C.delta_state({"r": "R-1"}))
        self.assertEqual("absent", C.delta_state({"r": "R-1", "delta": None}))
        for odd in (None, "unchanged", 5, [], {"delta": 5}, {"delta": ["unchanged"]}):
            self.assertIn(C.delta_state(odd), ("absent", "invalid"), repr(odd))
        # the observable's prefix promotes nothing: `unchanged` with `current-code:` is the cell word, no more
        row = C.register_rows(_register(NINE, [["R-1", "x", "story", "-", "yes", "AC-1", "current-code:a.py:1", "degraded", "unchanged"]]))[0]
        self.assertEqual("unchanged", C.delta_state(row))
        row["observable"] = "diff:a.py:1"
        self.assertEqual("unchanged", C.delta_state(row))

    def test_origin_is_read_by_its_header_and_an_old_table_has_none(self):
        head = ["R", "before", "before_ref", "now", "now_ref", "differs", "question"]
        line = ["R-6", "400", "absent", "403", "diff:a.py:1", "yes", "Q7"]
        reg = [["R-6", "x", "derived", "aspect:a", "yes", "-", "diff:a.py:1"]]
        old = C.behaviour_claims(_register(SEVEN, reg, (head, [line])))
        self.assertEqual("", old[0]["origin"])
        self.assertEqual("Q7", old[0]["question"])
        new = C.behaviour_claims(_register(SEVEN, reg, (head + ["origin"], [line + ["S3-grounding"]])))
        self.assertEqual("S3-grounding", new[0]["origin"])
        empty = C.behaviour_claims(_register(SEVEN, reg, (head + ["origin"], [line + [""]])))
        self.assertEqual("", empty[0]["origin"])
        # a table with an eighth column of another name: its cell is NOT the origin
        other = C.behaviour_claims(_register(SEVEN, reg, (head + ["note"], [line + ["S3-grounding"]])))
        self.assertEqual("", other[0]["origin"])
        # a short row of a table that has the column
        short = C.behaviour_claims(_register(SEVEN, reg, (head + ["origin"], [line])))
        self.assertEqual("", short[0]["origin"])

    def test_claim_row_errors_does_not_judge_the_origin_cell(self):
        row = {"before": "400", "before_ref": "absent", "now": "403", "now_ref": "diff:a.py:1", "differs": "no", "question": "Q7"}
        self.assertEqual(C.claim_row_errors(row), C.claim_row_errors(dict(row, origin="whatever")))

    def test_header_index_exact_has_no_prefix_and_no_fallback(self):
        header = ["R", "delta (x)", "origins"]
        self.assertEqual(-1, C._header_index(header, "delta", -1, exact=True))
        self.assertEqual(-1, C._header_index(header, "origin", -1, exact=True))
        self.assertEqual(1, C._header_index(header, "delta", 9))      # the default form still matches a prefix
        self.assertEqual(1, C._header_index(["R", "Delta"], "delta", -1, exact=True))


class RegisterRequirementKey(unittest.TestCase):
    """OH3-34: `register_rows` carries `requirement`, found by the header that STARTS WITH `Requirement`; a register with no such
    column is refused naming it, never read as rows with an empty key."""

    REAL = ["R", "Requirement (one verifiable statement)", "source", "derived_from", "verifiable", "ac_ref", "observable", "impact", "delta"]
    ROW = ["R-1", "The budgets dashboard totals", "story", "-", "yes", "AC-1", "diff:a.py:1", "degraded", "new"]

    def test_the_key_is_there_on_the_template_header_and_on_a_plain_one(self):
        for header in (self.REAL, ["R", "Requirement"] + self.REAL[2:], ["R", "requirement text"] + self.REAL[2:]):
            rows = C.register_rows(_register(header, [self.ROW]))
            self.assertEqual(["The budgets dashboard totals"], [r["requirement"] for r in rows], header[1])
            self.assertEqual("diff:a.py:1", rows[0]["observable"], "every existing key stays")

    def test_the_template_itself_reads(self):
        text = (Path(C.__file__).resolve().parent.parent / "references" / "templates" / "requirements-register.md").read_text(encoding="utf-8")
        rows = C.register_rows(text)
        self.assertTrue(rows)
        self.assertTrue(all(r["requirement"] for r in rows), [r["r"] for r in rows if not r["requirement"]])

    def test_a_register_with_no_requirement_column_is_refused_naming_it(self):
        with self.assertRaises(ValueError) as caught:
            C.register_rows(_register(["R", "Statement", "source"], [["R-1", "x", "story"]]))
        self.assertIn("`Requirement` column", str(caught.exception))

    def test_no_table_and_no_rows_are_no_rows(self):
        self.assertEqual([], C.register_rows("# nothing\n"))
        self.assertEqual([], C.register_rows(_register(self.REAL, [])))


class RegisterRequirementKeyReaders(unittest.TestCase):
    """OH3-34 (critic m-1, m-3): the other readers of the `Requirement` column go through the key, and a malformed header is the role's
    refusal naming the expected header (FR-46), not an exception of the factory."""

    def test_candidate_defects_reads_the_requirement_through_the_key_not_the_position(self):
        columns = ["R", "source", "Requirement (one verifiable statement)", "derived_from", "verifiable", "ac_ref", "observable"]
        text = _register(columns, [["R-1", "derived", "Cart total ignores the discount", "bug:candidate-defect", "yes", "-", "current-code:Cart.tsx:65"]])
        found = C.candidate_defects(text)
        self.assertEqual(["Cart total ignores the discount"], [c["requirement"] for c in found])
        self.assertEqual(("Cart.tsx", 65), (found[0]["file"], found[0]["line"]))

    def test_check_register_refuses_a_header_with_no_requirement_column_naming_the_expected_one(self):
        import validate_artifacts as V
        columns = ["R", "Statement", "source", "derived_from", "verifiable", "ac_ref", "observable", "impact", "delta"]
        body = _register(columns, [["R-1", "x", "story", "-", "yes", "AC-1", "diff:a.py:1", "degraded", "new"]])
        text = "---\nids: [R-1]\nby_source: {story: 1}\n---\n" + body
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "requirements-register.md"
            path.write_text(text, encoding="utf-8")
            errors = []
            V.check_register(path, errors)               # must not raise
        hits = [e for e in errors if "Requirement (one verifiable statement)" in e]
        self.assertEqual(1, len(hits), errors)
        self.assertNotIn("defect", hits[0].lower())      # the role's header, not "the factory's own defect"


class SliceKeysAndPartitionKey(unittest.TestCase):
    """HF2-3 (3a1-K3, K3b): ONE spelling of a partition and ONE list of the keys that make an `unresolved[]` row a slice."""

    def test_slice_scoped_reads_the_constant_and_thens_is_not_a_slice(self):
        for key in C.UNRESOLVED_SLICE_KEYS:                       # a loop over the constant: a new key is covered at once
            self.assertTrue(C._slice_scoped({"case": "TC-1", key: "x"}), key)
            self.assertTrue(C._slice_scoped({"case": "TC-1", key: ["x"]}), key)
            for empty in ([], "", None):
                self.assertFalse(C._slice_scoped({"case": "TC-1", key: empty}), f"{key}={empty!r}")
        self.assertFalse(C._slice_scoped({"thens": [2]}))
        self.assertFalse(C._slice_scoped({"case": "TC-1", "reason": "contradicts_requirement", "thens": [2]}))
        self.assertTrue(C._slice_scoped({"thens": [2], "instance_ids": ["a"]}))
        self.assertFalse(C._slice_scoped({}))
        for odd in (None, [], "x", 5):
            self.assertFalse(C._slice_scoped(odd), repr(odd))

    def test_partition_key(self):
        table = [("msteams", "msteams"), ("P-msteams", "msteams"), ("p-MsTeams", "msteams"), ("  P-msteams  ", "msteams"),
                 ("MSTEAMS", "msteams"), ("P-", ""), ("p-", ""), ("", ""), ("   ", ""), (None, ""), ("P-P-x", "p-x"),
                 ("Pmsteams", "pmsteams"), ("P_x", "p_x"), ("P- x", " x"), ("generic", "generic"), (5, "5")]
        for value, key in table:
            self.assertEqual(key, C.partition_key(value), repr(value))
        self.assertEqual(C.partition_key("msteams"), C.partition_key("P-msteams"))
        self.assertNotEqual(C.partition_key("P-a"), C.partition_key("P-b"))


def window_with(item: dict) -> dict:
    """A shape-complete schema-2 window of ONE instance: `item` laid over a `new_or_changed` red one with no proof."""
    base = {"instance_id": "i1", "input_hash": "h", "outcome": "failed", "execution_fingerprint": "fp",
            "obligation_refs": [], "obligation_ids": ["O-1"], "obligation_hash": "oh", "assertion_id": "a",
            "defect_location": "d", "change_disposition": "new_or_changed", "change_basis_ref": "b",
            "evidence_refs": [{"path": "p", "sha256": "s"}], "review": {"verdict": "approved"}, "schema_version": 2}
    return {"schema_version": 2, "author_dispatch_id": "a", "reviewer_dispatch_id": "r", "input_hash": "h",
            "scope_instances": {"TC-1": ["i1"]}, "instances": [dict(base, **item)],
            "required_quality_checks": [], "quality_receipts": []}


RED_BLOCK = {"why": "red", "reason": "contradicts_requirement",
             "rows": [{"case": "TC-1", "instance_ids": ["i1"], "thens": [1]}]}


class RedWindowShape(unittest.TestCase):
    """HF2-4a (K1, K7): `probe_not_applicable` is the third way to satisfy a `new_or_changed` instance, and ONLY for an
    instance that ran red; the rule of `probe_gap_errors` (a word never turns a red into a passed window) is unchanged."""

    def errors(self, **item):
        return C.window_shape_errors(window_with(item))

    def test_a_red_instance_with_the_block_is_whole_and_without_it_is_today(self):
        self.assertEqual([], self.errors(probe_not_applicable=RED_BLOCK))
        self.assertEqual(["i1: " + C.PROBE_MISSING_ERROR], self.errors())

    def test_the_block_replaces_nothing_for_a_green_instance(self):
        got = self.errors(outcome="passed", probe_not_applicable=RED_BLOCK)
        self.assertTrue(any("carried only by an instance that ran red" in e and "'passed'" in e for e in got), got)
        self.assertNotIn("i1: " + C.PROBE_MISSING_ERROR, got)   # one error for the one defect, not two
        self.assertEqual(["i1: " + C.PROBE_MISSING_ERROR], self.errors(outcome="passed"))

    def test_the_block_is_never_beside_a_proof_or_a_named_gap(self):
        proof = self.errors(probe_not_applicable=RED_BLOCK, probe={"verdict": "intended_failure"})
        self.assertTrue(any("probe_not_applicable and probe are both present" in e for e in proof), proof)
        gap = {"verdict": "not_run", "record": None, "why": "w", "named_by": "i1", "words": "ok"}
        both = self.errors(probe_not_applicable=RED_BLOCK, probe_gap=gap)
        self.assertTrue(any("probe_not_applicable and probe_gap are both present" in e for e in both), both)
        self.assertTrue(any("a probe gap is carried only by an instance that ran green" in e for e in both), both)

    def test_the_form_of_the_block_is_checked_whole(self):
        table = [("not an object", "x", "must be an object"),
                 ("a why that is not red", dict(RED_BLOCK, why="green"), "why must be one of red"),
                 ("no why", {k: v for k, v in RED_BLOCK.items() if k != "why"}, "why must be one of red"),
                 ("another reason", dict(RED_BLOCK, reason="blocked_by_env"), "reason must be contradicts_requirement"),
                 ("no rows", {k: v for k, v in RED_BLOCK.items() if k != "rows"}, "rows must be a non-empty list"),
                 ("empty rows", dict(RED_BLOCK, rows=[]), "rows must be a non-empty list"),
                 ("rows that is no list", dict(RED_BLOCK, rows={"case": "TC-1"}), "rows must be a non-empty list"),
                 ("a row that is no object", dict(RED_BLOCK, rows=["TC-1"]), "rows[0] must be an object"),
                 ("a row without a case", dict(RED_BLOCK, rows=[{"thens": [1]}]), "rows[0] must be an object"),
                 ("a blank case", dict(RED_BLOCK, rows=[{"case": "  "}]), "rows[0] must be an object"),
                 ("the second row is the bad one", dict(RED_BLOCK, rows=[{"case": "TC-1"}, {"case": 5}]), "rows[1] must be")]
        for label, block, said in table:
            got = self.errors(probe_not_applicable=block)
            self.assertTrue(any(said in e and e.startswith("i1: probe_not_applicable: ") for e in got), (label, got))
            self.assertNotIn("i1: " + C.PROBE_MISSING_ERROR, got, label)   # the block is present: judged, not "missing"
        every = C.probe_not_applicable_errors({"outcome": "passed", "probe": {}, "probe_gap": {},
                                               "probe_not_applicable": {}})
        self.assertGreaterEqual(len(every), 6, every)   # all the problems at once, never the first only

    def test_the_slice_keys_and_thens_of_a_row_are_not_judged(self):
        block = dict(RED_BLOCK, rows=[{"case": "TC-1", "partitions": ["P-a"], "instance_ids": [7], "thens": "x"}])
        self.assertEqual([], self.errors(probe_not_applicable=block))

    def test_the_empty_outcome_and_a_total_function(self):
        for item in (None, "x", [], {}, {"outcome": "failed"}):
            self.assertEqual([], C.probe_not_applicable_errors(item), repr(item))

    def test_handed_and_blocked_owe_no_block_and_unchanged_none(self):
        for outcome in ("handed_to_person", "blocked_by_env"):
            self.assertEqual([], self.errors(outcome=outcome), outcome)
        self.assertEqual([], self.errors(change_disposition="unchanged"))

    def test_a_word_never_turns_a_red_into_a_gap(self):
        gap = {"verdict": "not_run", "record": None, "why": "w", "named_by": "i1", "words": "ok"}
        got = C.probe_gap_errors({"outcome": "failed", "probe_gap": gap})
        self.assertEqual(["a probe gap is carried only by an instance that ran green (outcome passed); "
                          "this one is 'failed'"], got)


class TableCells(unittest.TestCase):
    """G2-10: a role's table row is read through `grammar.split_cells` (a `\\|` is part of its cell), a row with more
    cells than its header is the footprint of a bare `|` and is refused by date, and the plan rewrite keeps the bars."""

    HEADER = "| R | text | source |\n|---|---|---|\n"

    def test_md_table_keeps_an_escaped_bar_in_its_cell(self):
        text = "## Register\n" + self.HEADER + "| R-1 | a \\| b | story |\n"
        self.assertEqual([["R", "text", "source"], ["R-1", "a | b", "story"]], C.md_table(text, "## Register"))

    def test_a_row_with_a_bare_bar_is_excess_and_the_narrow_rows_are_not(self):
        text = ("## Register\n" + self.HEADER + "| R-1 | a|b | story |\n| R-2 | a \\| b | story |\n"
                "| R-3 | short |\n| R-4 | x | story | |\n")
        self.assertEqual([("R-1", 3, 4)], C.excess_cell_rows(text, "## Register"))
        self.assertEqual([], C.excess_cell_rows("no table", "## Register"))
        self.assertEqual([], C.excess_cell_rows("## Register\n" + self.HEADER, "## Register"))

    def test_the_cutoff_reads_created_and_an_unreadable_one_is_the_new_world(self):
        def head(created):
            return f"---\ncreated: {created}\n---\n"
        got = [C.after_cell_count_cutoff(head(c)) for c in ("2026-10-30", "2026-10-31", "2026-11-05", "yesterday", "", "2026-13-45")]
        self.assertEqual([False, True, True, True, True, True], got)
        self.assertTrue(C.after_cell_count_cutoff("no front matter at all"))

    def check(self, created):
        import validate_artifacts as V
        text = (f"---\ncreated: {created}\n---\n## Register\n" + self.HEADER + "| R-7 | a|b | story |\n")
        errors: list = []
        del V.ORACLE_NOTES[:]
        V.check_cell_counts(Path("requirements-register.md"), text, "## Register", "register", errors)
        notes = list(V.ORACLE_NOTES)
        del V.ORACLE_NOTES[:]
        return errors, notes

    def test_a_new_register_with_a_bare_bar_is_refused_with_the_door(self):
        errors, notes = self.check("2026-10-31")
        self.assertEqual([], notes)
        self.assertEqual(1, len(errors))
        for part in ("R-7", "4 cells under a header of 3", "write | inside a cell as \\|"):
            self.assertIn(part, errors[0])

    def test_an_older_register_reads_as_before_and_says_so_once(self):
        errors, notes = self.check("2026-10-30")
        self.assertEqual([], errors)
        self.assertEqual(1, len(notes))
        self.assertIn("R-7", notes[0])
        self.assertIn("before 2026-10-31", notes[0])

    def test_an_unreadable_created_refuses(self):
        for created in ("soon", "2026-13-45", "''"):
            errors, notes = self.check(created)
            self.assertEqual(1, len(errors), created)
            self.assertEqual([], notes, created)

    def test_the_plan_rewrite_keeps_the_bars_and_every_other_line_byte_for_byte(self):
        import planning_contract as PC
        head = "---\ncreated: 2026-10-31\n---\n## Plan\n| TS | R | level | fit | disposition + reason |\n|---|---|---|---|---|\n"
        other = "|TS-2|R-2|  api |new|  `automate` — keep a \\| b   |\n"
        text = head + "| TS-1 | R-1 | api | extend | `automate` — old \\| reason |\n" + other + "\n## After\n| x | y |\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test-plan.md"
            path.write_bytes(text.encode("utf-8"))
            done = PC._rerender_plan_cells(Path(tmp), {"TS-1": {"level": "e2e", "disposition_cell": ("manual", "why a|b")}})
            got = path.read_bytes().decode("utf-8")
        self.assertEqual(["TS-1"], done)
        self.assertEqual(head + "| TS-1 | R-1 | e2e | extend | `manual` — why a\\|b |\n" + other + "\n## After\n| x | y |\n", got)

    def test_the_plan_rewrite_of_an_untouched_bar_cell_loses_nothing(self):
        import planning_contract as PC
        head = "## Plan\n| TS | R | level | fit | disposition + reason |\n|---|---|---|---|---|\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test-plan.md"
            path.write_bytes((head + "| TS-1 | R-1 | api | a \\| b | `automate` — x |\n").encode("utf-8"))
            PC._rerender_plan_cells(Path(tmp), {"TS-1": {"level": "ui"}})
            got = path.read_bytes().decode("utf-8")
        self.assertEqual(head + "| TS-1 | R-1 | ui | a \\| b | `automate` — x |\n", got)


class RequestAgentId(unittest.TestCase):
    def test_bind_is_not_a_resume(self):
        self.assertEqual("agent-7", C.request_agent_id({"agent_id": " agent-7 "}))
        self.assertEqual("", C.request_agent_id({"agent_id": "agent-7", "agent_bound_seq": 3}))
        self.assertEqual("", C.request_agent_id({"agent_id": None}))
        self.assertEqual("", C.request_agent_id(None))


if __name__ == "__main__":
    unittest.main()
