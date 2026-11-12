"""The stand-gap vocabulary of contract.py: a remedy is names only, and the person's answer
to a card is read from the one place every decision of theirs lands (stage_overrides[])."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import contract as C


class RemedyTests(unittest.TestCase):
    def test_a_complete_remedy_has_no_errors(self):
        self.assertEqual(C.remedy_errors({"kind": "flag", "where": "config/customer/customer-config.yaml:306-311",
                                          "change": "enabled: true", "restart": "testproject1, testproject1-ui"}), [])

    def test_shape_errors_name_the_field(self):
        errors = C.remedy_errors({"kind": "toggle", "where": "", "change": "x", "restart": 3})
        self.assertTrue(any(e.startswith("remedy.kind") for e in errors))
        self.assertTrue(any(e == "remedy.where is empty" for e in errors))
        self.assertTrue(any(e.startswith("remedy.restart") for e in errors))
        self.assertEqual(C.remedy_errors("fix it"), ["remedy must be an object {kind, where, change, restart?}"])

    def test_a_credential_remedy_names_the_variable_never_its_value(self):
        # TP1-15045: the guardrail fixture reads AWS_ACCESS_KEY_ID; the remedy says which
        # variable to set and where, and a token-shaped `change` is refused outright.
        self.assertEqual(C.remedy_errors({"kind": "credential", "where": "AWS_ACCESS_KEY_ID",
                                          "change": "set in testproject1_test_harness/.env"}), [])
        errors = C.remedy_errors({"kind": "credential", "where": "AWS_ACCESS_KEY_ID",
                                  "change": "AKIA1234567890ABCDEF"})
        self.assertEqual(errors, ["remedy.change looks like a secret value - name the variable, never its value"])


def _record(gap, decision, at="2026-09-23T10:00:00Z", stage="S5", **extra):
    return dict({"stage": stage, "match": f"stand gap: {gap}", "decision": decision, "at": at}, **extra)


def _option(decision):
    """The option the reader gives a one-record pipeline holding `decision` for the gap `G`."""
    return C.stand_gap_decisions({"stage_overrides": [_record("G", decision)]})["G"]["option"]


class StandGapDecisionTests(unittest.TestCase):
    def test_answers_are_read_from_stage_overrides_by_gap_id(self):
        pipeline = {"stage_overrides": [
            {"stage": "S5", "match": "stand gap: PC-1", "decision": "apply - go ahead", "at": "2026-09-23T10:00:00Z"},
            {"stage": "S8", "match": "Stand gap: `api/TC-007`", "decision": "handed", "at": "2026-09-23T11:00:00Z"},
            {"stage": "S5", "match": "executor unavailable: pytest-ui", "decision": "handed_to_person"},
            {"stage": "S5", "match": "stand gap: TC-009", "decision": "let me think about it"},
        ]}
        got = C.stand_gap_decisions(pipeline)
        self.assertEqual(got["PC-1"]["option"], "apply")
        self.assertEqual(got["api/TC-007"], {"option": "handed", "words": "handed", "at": "2026-09-23T11:00:00Z",
                                             "stage": "S8"})
        # Free text is never misread as one of the four options.
        self.assertEqual(got["TC-009"]["option"], "")
        self.assertEqual(got["TC-009"]["words"], "let me think about it")
        self.assertNotIn("pytest-ui", got)

    def test_empty_and_malformed_pipelines_yield_nothing(self):
        self.assertEqual(C.stand_gap_decisions({}), {})
        self.assertEqual(C.stand_gap_decisions({"stage_overrides": ["x", {"match": "stand gap:", "decision": "apply"}]}), {})
        # t-427 N1: a string entry beside an entry with an empty id, a blank decision, a pipeline that is
        # not an object and a list that is not a list - every one of them reads as no answer, none raises
        self.assertEqual(C.stand_gap_decisions({"stage_overrides": ["x", _record("", "apply"),
                                                                    _record("   ", "apply")]}), {})
        self.assertEqual(C.stand_gap_decisions({"stage_overrides": [_record("G", "   "), _record("G", "")]}), {})
        for broken in (None, [], "x", {"stage_overrides": "x"}, {"stage_overrides": {"a": 1}}):
            self.assertEqual(C.stand_gap_decisions(broken), {})

    def test_the_driver_form_reads_its_first_word(self):
        # `story_run.take_stand_gap_answers` writes `<word> - the person wrote: <their words>`
        self.assertEqual(_option("accept - the person wrote: TC-1: accept"), "accept")

    def test_the_first_word_is_judged_whole(self):
        self.assertEqual(_option("Accept, fine"), "accept")
        self.assertEqual(_option("apply: turn it on"), "apply")
        self.assertEqual(_option("accept?"), "")
        self.assertEqual(_option("accepted"), "")
        # an answer outside the four is kept with its words and no option
        got = C.stand_gap_decisions({"stage_overrides": [_record("G", "accept? not sure")]})["G"]
        self.assertEqual((got["option"], got["words"]), ("", "accept? not sure"))

    def test_a_revoked_record_applies_to_nothing(self):
        revoked = _record("G", "apply - go ahead", revoked_at="2026-09-23T11:00:00Z")
        self.assertNotIn("G", C.stand_gap_decisions({"stage_overrides": [revoked]}))
        # every record of an id revoked: the id is absent, not read from the oldest of them
        both = {"stage_overrides": [revoked, _record("G", "accept", at="2026-09-23T12:00:00Z",
                                                     revoked_at="2026-09-23T13:00:00Z")]}
        self.assertNotIn("G", C.stand_gap_decisions(both))
        # B-376: a revoked record whose `at` is LATER than a live one stands that older live answer down
        # (taking back the latest word of a gap does not bring an older one back) - the id is absent
        live = _record("G", "theirs - I will", at="2026-09-23T09:00:00Z")
        later_revoked = _record("G", "apply", at="2026-09-23T12:00:00Z", revoked_at="2026-09-23T13:00:00Z")
        self.assertNotIn("G", C.stand_gap_decisions({"stage_overrides": [live, later_revoked]}))
        # ... but an OLDER record revoked later does not put down a NEWER live one (the key is `at`, not `revoked_at`)
        older_revoked = _record("G", "apply", at="2026-09-23T08:00:00Z", revoked_at="2026-09-23T13:00:00Z")
        got = C.stand_gap_decisions({"stage_overrides": [older_revoked, live]})
        self.assertEqual(got["G"]["option"], "theirs")

    def test_the_latest_answer_wins_whatever_its_stage(self):
        s5_first = {"stage_overrides": [_record("G", "theirs - mine", at="2026-09-23T10:00:00Z", stage="S5"),
                                        _record("G", "accept - leave it", at="2026-09-23T12:00:00Z", stage="S9")]}
        got = C.stand_gap_decisions(s5_first)["G"]
        self.assertEqual((got["option"], got["stage"]), ("accept", "S9"))
        # the same two records in the other list order: the moment decides, not the position
        got = C.stand_gap_decisions({"stage_overrides": list(reversed(s5_first["stage_overrides"]))})["G"]
        self.assertEqual((got["option"], got["stage"]), ("accept", "S9"))
        # reversed times: S9 is older, so the S5 answer is the one that stands
        reversed_times = {"stage_overrides": [_record("G", "theirs - mine", at="2026-09-23T12:00:00Z", stage="S5"),
                                              _record("G", "accept - leave it", at="2026-09-23T10:00:00Z", stage="S9")]}
        got = C.stand_gap_decisions(reversed_times)["G"]
        self.assertEqual((got["option"], got["stage"]), ("theirs", "S5"))

    def test_the_moment_is_read_as_a_time_not_as_text(self):
        # `Z`, an offset and a naive stamp are the same clock (UTC): 10:00Z is later than 09:30+00:00
        # and a naive 2026-09-23T10:30:00 is later than both
        pipeline = {"stage_overrides": [_record("G", "apply - a", at="2026-09-23T10:00:00Z"),
                                        _record("G", "theirs - b", at="2026-09-23T09:30:00+00:00")]}
        self.assertEqual(C.stand_gap_decisions(pipeline)["G"]["option"], "apply")
        pipeline["stage_overrides"].append(_record("G", "handed - c", at="2026-09-23T10:30:00"))
        self.assertEqual(C.stand_gap_decisions(pipeline)["G"]["option"], "handed")
        # an offset moves the clock: 12:00+05:00 is 07:00 UTC, earlier than 10:00Z
        pipeline = {"stage_overrides": [_record("G", "apply - a", at="2026-09-23T10:00:00Z"),
                                        _record("G", "theirs - b", at="2026-09-23T12:00:00+05:00")]}
        self.assertEqual(C.stand_gap_decisions(pipeline)["G"]["option"], "apply")

    def test_a_bad_or_missing_moment_loses_to_a_good_one(self):
        good = _record("G", "accept - fine", at="2026-09-23T10:00:00Z")
        for bad_at in ("yesterday", "", None, "2026-13-45T99:99:99"):
            bad = _record("G", "theirs - mine", at=bad_at)
            for order in ([good, bad], [bad, good]):
                got = C.stand_gap_decisions({"stage_overrides": order})["G"]
                self.assertEqual(got["option"], "accept", (bad_at, order))
        no_key = {"stage": "S5", "match": "stand gap: G", "decision": "theirs - mine"}
        self.assertEqual(C.stand_gap_decisions({"stage_overrides": [good, no_key]})["G"]["option"], "accept")

    def test_equal_moments_the_later_record_in_the_list_wins(self):
        first = _record("G", "theirs - mine", at="2026-09-23T10:00:00Z")
        second = _record("G", "accept - fine", at="2026-09-23T10:00:00+00:00")
        self.assertEqual(C.stand_gap_decisions({"stage_overrides": [first, second]})["G"]["option"], "accept")
        self.assertEqual(C.stand_gap_decisions({"stage_overrides": [second, first]})["G"]["option"], "theirs")
        # two answers with no readable moment at all are equal too: the later one stands
        a, b = _record("G", "theirs - mine", at=""), _record("G", "accept - fine", at="never")
        self.assertEqual(C.stand_gap_decisions({"stage_overrides": [a, b]})["G"]["option"], "accept")

    def test_other_gaps_are_not_touched_by_one_gaps_records(self):
        pipeline = {"stage_overrides": [_record("A", "apply - a", at="2026-09-23T12:00:00Z"),
                                        _record("B", "accept - b", at="2026-09-23T10:00:00Z"),
                                        _record("A", "theirs - a2", at="2026-09-23T11:00:00Z",
                                                revoked_at="2026-09-23T11:30:00Z")]}
        got = C.stand_gap_decisions(pipeline)
        self.assertEqual((got["A"]["option"], got["B"]["option"]), ("apply", "accept"))

    def test_the_gap_id_of_a_match(self):
        self.assertEqual(C.stand_gap_id("Stand gap: `TC-7`"), "TC-7")
        self.assertEqual(C.stand_gap_id("stand   gap:\t\"api/TC-007\" "), "api/TC-007")
        self.assertEqual(C.stand_gap_id("STAND GAP: PC-1"), "PC-1")
        self.assertEqual(C.stand_gap_id("tracker route"), "")
        self.assertEqual(C.stand_gap_id("executor unavailable: pytest-ui"), "")
        self.assertEqual(C.stand_gap_id("stand gap:"), "")
        self.assertEqual(C.stand_gap_id("stand gap: `` "), "")
        self.assertEqual(C.stand_gap_id(None), "")


def _old_expression(word, line, replaced):
    """The expression `story_run._record_gap_lines` (:8979-8980) and `_record_door_lines` (:9007-9008) carried before t-666 R2,
    copied here as the reference the line builder is held to, byte for byte."""
    return f"{word} - the person wrote: {line}" + (
        f" (replaces their earlier line: {'; '.join(replaced)})" if replaced else "")


# (label, replaced, the text the person's record carries after "<word> - the person wrote: <line>")
REPLACED_TABLE = (("empty list", [], ""),
                  ("one earlier line", ["TC-1: accept"], " (replaces their earlier line: TC-1: accept)"),
                  ("two earlier lines", ["TC-1: accept", "TC-1: run"], " (replaces their earlier line: TC-1: accept; TC-1: run)"),
                  ("None", None, ""))


class DecisionLineTests(unittest.TestCase):
    """t-666 R2: the line a recorded decision carries ("<word> - the person wrote: <line>", then the earlier lines it replaces)."""

    def test_the_old_expression_is_pinned_as_literals(self):
        # characterisation: the reference itself is held to literal text, so the differential below cannot drift with it
        for label, replaced, tail in REPLACED_TABLE:
            self.assertEqual(_old_expression("accept", "TC-1: accept always", replaced),
                             "accept - the person wrote: TC-1: accept always" + tail, label)

    def test_the_line_builder_is_the_old_expression_byte_for_byte(self):
        # the differential table: (word, line, replaced) over the four shapes of `replaced`, old expression against the builder
        for word in ("accept", "apply", "handed", "theirs", "Check-7"):
            for line in ("TC-1: accept", "one line", "a; b", "a / b (c)", ""):
                for label, replaced, tail in REPLACED_TABLE:
                    got = C.person_decision(word, line, replaced)
                    self.assertEqual(got, _old_expression(word, line, replaced), (word, line, label))
                    self.assertEqual(got, f"{word} - the person wrote: {line}" + tail, (word, line, label))
        # the third argument is optional: no earlier line
        self.assertEqual(C.person_decision("accept", "TC-1: accept"), _old_expression("accept", "TC-1: accept", []))

    def test_the_tail_alone(self):
        for label, replaced, tail in REPLACED_TABLE:
            self.assertEqual(C.replaces_tail(replaced), tail, label)
        self.assertNotIn("; ", C.replaces_tail(["x"]))          # one element: no separator
        self.assertEqual(C.replaces_tail(()), "")
        self.assertTrue(C.replaces_tail(["x", "y"]).endswith("x; y)"))

    def test_a_decision_it_writes_is_read_back_by_the_reader_of_the_option(self):
        # I2: the word goes FIRST and as given, so `stand_gap_decisions` reads it as the option
        for word in ("accept", "apply", "handed", "theirs"):
            for replaced in (None, ["TC-1: earlier"], ["a", "b"]):
                self.assertEqual(_option(C.person_decision(word, "TC-1: " + word, replaced)), word, (word, replaced))


if __name__ == "__main__":
    unittest.main()
