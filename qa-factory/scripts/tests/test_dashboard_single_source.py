"""HF7-5 (DP-5): "single source" is information on the page and in the retro, never a finding.

A story whose only record is the chat (no driver journal names a session of it) has nothing to cross-check against.
`task_price` says so in `single_source` (true only for `not_cross_checked`, no journal-named session, nothing still being
written, no unknown CLI charge); the "By task" cell, the price note and the retro read it through
`answer.get("single_source") is True` (a missing field is not a single source). Information never hides a real gap
and an information extra never makes the cell `warn`. The fixture is synthetic (fixtures/synthetic-single-source/):
tokens only, no money.

Keys: K1 (the cell), K2 (the CLI's charge unknown), K2b (the real function says true), K3 (an information extra),
K4 (a real gap stays warn), K5 (the retro), F15 (the window "still being written"), B3 (a remote call with no receipt
and a request counted under no task are known missing money: never a single source), F6 (the fixture holds no money, with
its negative control; a journal that names a session with no cost file).

Mutation table note: "`single_source` without `not cli_unknown` -> K2" is an EQUIVALENT mutation: `cli_unknown` needs a
journal entry, and `journal_named == 0` already excludes it, so no test can kill it. The clause stays because the spec asks.
"""
import json
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import factory_dashboard as D
import retro_numbers as RN
import task_price as TP

TASK = "SYN-1"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "synthetic-single-source" / "synthetic-chat-session.json"
WORDS = "single source (chat): nothing to cross-check against"
TMP = tempfile.TemporaryDirectory()
ROW = re.compile(r"<tr><td>" + TASK + r"</td>.*?<td class='([a-z]*)'>([^<]*)</td></tr>", re.S)


def fixture_doc(**fields):
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    doc.update(fields)
    return doc


def transcript(age_s, name):
    """A transcript file last written `age_s` seconds ago."""
    path = Path(TMP.name) / (name + ".jsonl")
    path.write_text("{}\n", encoding="utf-8")
    stamp = time.time() - age_s
    os.utime(path, (stamp, stamp))
    return str(path)


def stand_in(**fields):
    """A hand-fed price answer (the producer's field is supplied by the test, as K1, K3 and K5 say)."""
    row = {"session": "synthetic-chat-session", "agent": "orchestrator", "stage": "", "a_usd": None, "b_usd": None,
           "a_price_usd": None, "verdict": TP.V_ONE_RECORD, "why": "no driver journal names this session"}
    answer = {"status": TP.NOT_CROSS_CHECKED, "single_source": True, "sessions": [row], "by_agent": [],
              "price_low_usd": None, "price_high_usd": None, "finding": "", "compared": "", "catalogue_revision": "r",
              "rate_overrides": [], "totals": {}}
    answer.update(fields)
    return answer


def cell(doc, answer):
    """(css class, text) of the task's "By task" completeness cell, drawn with the render's own marks."""
    marks = D.session_marks([doc], {})
    page = D.tab_cost([doc], {}, None, {}, {}, None, None, {TASK: answer} if answer is not None else {}, marks=marks)
    match = ROW.search(page.split("By task</h2>")[1].split("</section>")[0])
    assert match, page[:300]
    return match.group(1), match.group(2).replace("&#x27;", "'")


def journal(sid, total):
    row = {"kind": "role", "role": "qa-runner", "dispatch": "d1", "stage": "S5", "session_id": sid, "num_turns": 1,
           "total_cost_usd": total, "ts": "2026-10-01T10:00:00+00:00"}
    entry = {"task": TASK, "rows": [row], "journals": [TASK], "no_timestamps": False, "multi_journal": False}
    return {sid: entry}, {sid: 1}


def price(doc, drv=None, cfg=None):
    return TP.task_price(None, TASK, sessions=[doc], driver=drv if drv is not None else ({}, {}), cfg=cfg or {})


MONEY_KEY = re.compile(r"(?:^|_)(?:cost|usd)(?:_|$)|subtotal|reconciliation|priced_subtotal|total_cost", re.I)
DOLLAR_DIGIT = re.compile(r"\$\s?\d")


def money_problems(text: str) -> list:
    """The fixture holds no money: no money-named key with a non-zero value and no `$`+digit anywhere (§5.0 p.4)."""
    found = ["dollar+digit"] if DOLLAR_DIGIT.search(text) else []

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                # a money-named SCALAR with a value; an object under such a name is walked (its own keys are judged)
                if MONEY_KEY.search(str(key)) and not isinstance(item, (dict, list)) and item not in (None, 0, "0", "0.0", False):
                    found.append(str(key))
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(json.loads(text))
    return found


class FixtureTests(unittest.TestCase):
    def test_the_fixture_folder_holds_no_money(self):
        for path in sorted(FIXTURE.parent.glob("*.json")):
            self.assertEqual(money_problems(path.read_text(encoding="utf-8")), [], path.name)

    def test_control_a_non_zero_subtotal_and_a_dollar_amount_turn_it_red(self):
        bad = json.dumps({"valuation": {"subtotal_usd": "1.5"}, "note": "$1.00"})
        self.assertGreaterEqual(len(money_problems(bad)), 2)


class CellTests(unittest.TestCase):
    def test_k1_info_cell_for_a_single_source_answer(self):
        css, text = cell(fixture_doc(), stand_in())
        self.assertEqual(css, "info")
        self.assertTrue(text.startswith(WORDS), text)
        self.assertNotIn("incomplete", text)
        self.assertNotIn("not cross-checked", text)

    def test_k1_the_css_rule_exists_and_is_grey(self):
        self.assertIn(".info{color:#98a1ab}", D.render_css() if hasattr(D, "render_css") else Path(D.__file__).read_text(encoding="utf-8"))

    def test_k1_a_missing_field_is_not_a_single_source(self):
        answer = stand_in()
        del answer["single_source"]
        css, text = cell(fixture_doc(), answer)
        self.assertEqual((css, text), ("skip", "not cross-checked"))
        css, text = cell(fixture_doc(), stand_in(single_source=False))
        self.assertEqual((css, text), ("skip", "not cross-checked"))

    def test_status_that_is_not_not_cross_checked_never_reads_single_source(self):
        css, text = cell(fixture_doc(), stand_in(status=TP.DIFFERS))
        self.assertEqual(css, "warn")
        self.assertNotIn("single source", text)
        css, text = cell(fixture_doc(), stand_in(status=TP.INCOMPLETE))
        self.assertEqual(css, "warn")
        self.assertNotIn("single source", text)
        css, text = cell(fixture_doc(), stand_in(status=TP.AGREES, single_source=False))
        self.assertEqual((css, text), ("ok", "the two records agree"))

    def test_k3_an_information_extra_never_makes_warn(self):
        doc = fixture_doc(usage_completeness="provisional", usage_status="provisional", usage_final=None,
                          transcript=transcript(5, "live-k3"))
        css, text = cell(doc, stand_in())
        self.assertIn("1 session still being written", text)
        self.assertTrue(text.startswith(WORDS), text)
        self.assertNotEqual(css, "warn")
        self.assertEqual(css, "info")

    def test_k3b_the_same_extra_beside_the_words_of_a_plain_not_cross_checked_is_skip(self):
        doc = fixture_doc(usage_completeness="provisional", usage_status="provisional", usage_final=None,
                          transcript=transcript(5, "live-k3b"))
        css, text = cell(doc, stand_in(single_source=False))
        self.assertIn("1 session still being written", text)
        self.assertEqual(css, "skip")

    def test_k4_a_real_gap_beside_a_single_source_stays_warn_and_is_named(self):
        doc = fixture_doc(usage_completeness="provisional", usage_status="provisional", usage_final=None,
                          transcript=transcript(5, "live-k4"), incomplete_agents=["qa-runner"])
        css, text = cell(doc, stand_in())
        self.assertEqual(css, "warn")
        self.assertTrue(text.startswith(WORDS), text)
        self.assertIn("1 role without usage", text)

    def test_k4_a_gap_with_no_information_extra_stays_warn(self):
        css, text = cell(fixture_doc(incomplete_agents=["qa-runner"]), stand_in())
        self.assertEqual(css, "warn")
        self.assertIn("incomplete", text)
        self.assertIn("1 role without usage", text)

    def test_price_note_says_the_words_only_for_a_single_source(self):
        answer = stand_in(price_low_usd=2.0, price_high_usd=2.0, compared="x")
        self.assertIn("(" + WORDS + ").", D.price_note(TASK, answer))
        self.assertEqual(D.status_words(stand_in(single_source=False)), "not cross-checked")
        self.assertEqual(D.status_words(stand_in(status=TP.DIFFERS)), "the two records differ")
        missing = stand_in()
        del missing["single_source"]
        self.assertEqual(D.status_words(missing), "not cross-checked")


class ProducerTests(unittest.TestCase):
    def test_k2b_the_real_function_on_a_chat_session_says_true(self):
        answer = price(fixture_doc())
        self.assertEqual(answer["status"], TP.NOT_CROSS_CHECKED)
        self.assertIs(answer["single_source"], True)

    def test_k2_a_session_with_an_unknown_cli_charge_is_not_a_single_source(self):
        doc = fixture_doc(transcript=transcript(7200, "old-k2"))
        answer = price(doc, journal("synthetic-chat-session", None))
        self.assertEqual(answer["status"], TP.NOT_CROSS_CHECKED)
        self.assertIs(answer["single_source"], False)
        self.assertEqual([r["verdict"] for r in answer["sessions"]], [TP.V_ONE_RECORD])
        css, text = cell(doc, answer)
        self.assertEqual((css, text), ("skip", "not cross-checked"))

    def test_nothing_recorded_is_not_a_single_source(self):
        empty = TP.task_price(None, TASK)
        self.assertIs(empty["single_source"], False)
        self.assertEqual(TP._empty_result(TASK, "r", "why")["single_source"], False)

    def test_a_session_still_being_written_is_not_a_single_source(self):
        answer = price(fixture_doc(transcript=transcript(60, "live-fresh")))
        self.assertEqual(len(answer["in_progress"]), 1)
        self.assertIs(answer["single_source"], False)

    # B3 (P18, AR-27): information never hides a gap. Known money missing from the price makes the answer plain
    # `not cross-checked`, with its finding, never a grey "single source".
    CALL = {"external_call_id": "c1", "consumer_agent": "testproject1-helper", "invocation_method": "m", "usage_status": "pending"}

    def test_b3_a_remote_call_with_no_receipt_inside_the_span_is_not_a_single_source(self):
        doc = fixture_doc(external_calls=[dict(self.CALL, observed_at="2026-10-01T10:02:00+00:00")])
        answer = price(doc)
        self.assertEqual(answer["status"], TP.NOT_CROSS_CHECKED)
        self.assertIs(answer["single_source"], False)
        self.assertIn("left no receipt", answer["finding"])
        css, text = cell(doc, answer)
        self.assertNotEqual(css, "info")
        self.assertNotIn("single source", text)

    def test_b3_control_the_same_call_outside_the_span_is_not_counted_and_the_answer_stays_single_source(self):
        answer = price(fixture_doc(external_calls=[dict(self.CALL, observed_at="2026-10-01T11:02:00+00:00")]))
        self.assertIs(answer["single_source"], True)

    def test_b3_a_request_counted_under_no_task_is_not_a_single_source(self):
        doc = fixture_doc(chat_bindings=[{"task": "SYN-2", "requests": ["r1"]}])
        answer = price(doc)
        self.assertEqual(answer["status"], TP.NOT_CROSS_CHECKED)
        self.assertIs(answer["single_source"], False)
        self.assertIn("counted under none of them", answer["finding"])
        css, text = cell(doc, answer)
        self.assertNotEqual(css, "info")
        self.assertNotIn("single source", text)

    def test_f6_a_journal_that_names_a_session_with_no_cost_file_is_not_a_single_source(self):
        answer = TP.task_price(None, TASK, sessions=[fixture_doc(session_id="other")], driver=journal("ghost", 1.0), cfg={})
        self.assertEqual(answer["status"], TP.NOT_CROSS_CHECKED)
        self.assertIs(answer["single_source"], False)

    def test_agreeing_records_are_not_a_single_source(self):
        doc = fixture_doc()
        total = price(doc)["totals"]["a"]
        answer = price(doc, journal("synthetic-chat-session", total))
        self.assertEqual(answer["status"], TP.AGREES)
        self.assertIs(answer["single_source"], False)


class WindowTests(unittest.TestCase):
    """F-15 (a): "still being written" is the project's idle limit (default 30 min) unless the driver's line carries a
    recorded charge, which proves the process ended; inside the pass's own 300 s window it is live in every case."""

    SID = "synthetic-chat-session"

    def verdict(self, age_s, drv=None, cfg=None):
        answer = price(fixture_doc(transcript=transcript(age_s, f"w-{age_s}-{id(drv)}-{id(cfg)}")), drv, cfg)
        return answer["sessions"][0]["verdict"]

    def test_no_journal_line_the_window_is_the_idle_limit(self):
        self.assertEqual(self.verdict(600), TP.V_IN_PROGRESS)                    # beyond 300 s, inside 30 min
        self.assertEqual(self.verdict(1799), TP.V_IN_PROGRESS)                   # at the limit, inside
        self.assertEqual(self.verdict(1801), TP.V_ONE_RECORD)                    # beyond it: a settled chat
        self.assertEqual(self.verdict(600, cfg={"usage_final_after_idle_min": 60}), TP.V_IN_PROGRESS)
        self.assertEqual(self.verdict(2400, cfg={"usage_final_after_idle_min": 60}), TP.V_IN_PROGRESS)
        self.assertEqual(self.verdict(3700, cfg={"usage_final_after_idle_min": 60}), TP.V_ONE_RECORD)

    def test_a_driver_line_with_a_recorded_charge_proves_the_process_ended(self):
        total = price(fixture_doc())["totals"]["a"]
        self.assertEqual(self.verdict(600, journal(self.SID, total)), TP.V_AGREES)   # beyond 300 s: not live
        self.assertEqual(self.verdict(100, journal(self.SID, total)), TP.V_IN_PROGRESS)  # inside 300 s: live anyway

    def test_a_driver_line_without_a_charge_proves_nothing(self):
        self.assertEqual(self.verdict(600, journal(self.SID, None)), TP.V_IN_PROGRESS)
        self.assertEqual(self.verdict(1801, journal(self.SID, None)), TP.V_ONE_RECORD)

    def test_a_missing_transcript_is_never_live(self):
        answer = price(fixture_doc(transcript=""))
        self.assertEqual(answer["sessions"][0]["verdict"], TP.V_ONE_RECORD)


class RetroTests(unittest.TestCase):
    def head(self, **fields):
        data = {"price": stand_in(price_low_usd=2.0, price_high_usd=2.0, compared="c", **fields), "story": {"tokens": 7}}
        return RN.price_lines(data)[0]

    def test_k5_a_single_source_header_carries_the_same_words(self):
        head = self.head()
        self.assertTrue(head.startswith(f"**Story price: $2.00 — {WORDS}.** It comes from one record"), head)
        self.assertNotIn("not cross-checked", head)

    def test_k5_without_the_field_or_false_the_header_is_byte_for_byte_today(self):
        expected = ("**Story price: $2.00 — not cross-checked.** It comes from one record, the transcripts priced at "
                    "the catalogue's list rates: nothing could be compared against a second record (c). "
                    "Tokens recorded in the cost files of these sessions: 7. Rates: the catalogue's list prices, revision r.")
        self.assertEqual(self.head(single_source=False), expected)
        data = {"price": stand_in(price_low_usd=2.0, price_high_usd=2.0, compared="c"), "story": {"tokens": 7}}
        del data["price"]["single_source"]
        self.assertEqual(RN.price_lines(data)[0], expected)

    def test_the_words_are_one_string_for_the_page_and_the_retro(self):
        self.assertEqual(TP.SINGLE_SOURCE_WORDS, WORDS)
        self.assertEqual(D.SINGLE_SOURCE_WORDS, WORDS)


if __name__ == "__main__":
    unittest.main(verbosity=1)
