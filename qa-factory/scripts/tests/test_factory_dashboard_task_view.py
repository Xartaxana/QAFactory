"""The dashboard's per-task view (--task, --read-only) and role attribution in a driver run.

Seen on the comparison run cmp1 of TP1-13797: the root also held TP1-13958, so its tests,
bugs and ledger stood beside the run's; and every role of the driver run is its own `claude -p`
session, which the cost capture files under `orchestrator` with no agents, so "By agent" read
`orchestrator 35 calls`. The driver's own journal (artifacts/<task>/state/driver-runs.jsonl) knows
the role of every session.
"""
import contextlib
import hashlib
import io
import json
import re
import sys
import tempfile
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cost_capture as CC
import factory_dashboard as D
from dashboard_fixture import build

CASES = json.loads((Path(__file__).parent / "fixtures/dashboard-0.7.json").read_text(encoding="utf-8"))["cases"]
MODEL = "claude-sonnet-5-5"
CATALOGUE = CC.load_catalogue()
DASH, TICK = chr(0x2014), chr(0x2713)    # the page's "no figure" dash and the check mark (no non-ASCII literal in a test)


def _priced_usage(cost, tokens=None):
    """The usage of one request the catalogue prices at exactly `cost` (output tokens at $10 per MTok): the
    page re-prices every cost file from its usage at read, so a fixture's dollars are its usage's dollars.
    With `tokens` the request is that many input tokens instead (a fixture about tokens, not money)."""
    if tokens is not None:
        return {"input": tokens, "output": 0, "cache_read": 0, "cache_write_5m": 0, "cache_write_1h": 0}
    return {"input": 0, "output": int(round(cost * 100000)), "cache_read": 0, "cache_write_5m": 0, "cache_write_1h": 0}


def _row(sid, n, task, activity, usage, stream="orchestrator"):
    return {"request_key": f"{sid or 'anon'}:r{n}", "task": task, "activity_id": activity, "stream": stream,
            "timestamp": "2026-09-20T00:00:00Z", "model_id": MODEL, "usage": usage,
            "valuation": CC.value_usage(dict(usage, requests=1), MODEL, {}, CATALOGUE)}


def _doc(sid, rows, activities, by_task, usage_status="provisional"):
    total = {k: sum(r["usage"][k] for r in rows) for k in ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")}
    cost = round(sum(float(r["valuation"]["subtotal_usd"]) for r in rows), 6)
    model = dict(total, requests=len(rows), cost=cost)
    # the capture files a driver run's every session under `orchestrator`
    return {"session_id": sid, "usage_completeness": "provisional", "usage_status": usage_status,
            "requests": rows, "by_model": {MODEL: model}, "orchestrator": {"by_model": {MODEL: model}},
            "by_activity": activities, "by_task": by_task, "tasks": list(by_task),
            "priced_subtotal_usd": cost, "total_cost_usd": cost, "pricing_coverage": "complete",
            "reconciliation": {"match": True}, "has_factory_activity": True}


def _session(sid, task, cost, by_task=None, usage_status="provisional", tokens=None):
    row = _row(sid, 0, task, "a", _priced_usage(cost, tokens))
    return _doc(sid, [row], {"a": {"type": "story" if task != D.NO_TASK else "unclassified", "task": task}},
                by_task or {task: {"tokens": 1010, "requests": 1, "cost": cost}}, usage_status)


def _shared_session(sid, this="T-1", other="T-2"):
    """One session that served two tasks: 4 requests of $0.375 (this task's $1.50) and 5 of $0.70 (the other's $3.50),
    each under its own story activity: the evidence that says which request is whose."""
    rows = ([_row(sid, n, this, "a1", _priced_usage(0.375)) for n in range(4)]
            + [_row(sid, 4 + n, other, "a2", _priced_usage(0.7)) for n in range(5)])
    return _doc(sid, rows, {"a1": {"type": "story", "task": this}, "a2": {"type": "story", "task": other}},
                {this: {"tokens": 100, "requests": 4, "cost": 1.5}, other: {"tokens": 300, "requests": 5, "cost": 3.5}})


def _driver(task, *rows):
    return {"task": task, "rows": [dict(r) for r in rows]}


def _by_agent(html):
    return html.split("By agent</h2>")[1].split("</section>")[0]


def _agent_row(section, agent):
    """(calls, turns) of one "By agent" row, or None when the agent has no row."""
    m = re.search(r"<td><b>" + re.escape(agent) + r"</b></td><td>(\d+)</td><td[^>]*>(\d+)", section)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _cols(section, agent):
    """(transcripts at catalogue rates, the CLI's charge, price) of one "By agent" row as printed, or None."""
    m = re.search(r"<td><b>" + re.escape(agent) + r"</b></td>(.*?)</tr>", section, re.S)
    return tuple(re.findall(r"<td class='money'>([^<]*)</td>", m.group(1))) if m else None


def _tree_hash(root):
    digest = hashlib.sha256()
    for path in sorted(Path(root).rglob("*")):
        digest.update(str(path.relative_to(root)).encode())
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _run_main(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        D.main(list(argv))
    return out.getvalue()


class DriverAttributionTests(unittest.TestCase):
    def setUp(self):
        self.sessions = [_session("s-scout", "T-1", 2.0), _session("s-cond", D.NO_TASK, 0.5),
                         _session("s-plain", "T-1", 1.0)]
        self.driver = {
            "s-scout": _driver("T-1", {"kind": "role", "role": "qa-scout", "num_turns": 18},
                               {"kind": "role", "role": "qa-scout", "num_turns": 31}),
            "s-cond": _driver("T-1", {"kind": "conductor", "role": "", "num_turns": 5}),
        }

    def test_each_session_is_one_row_of_its_role_and_conductor_rows_are_conductor(self):
        section = _by_agent(D.tab_cost(self.sessions, {}, None, self.driver, {}))
        # two rows of one session are ONE call; turns are the rows' num_turns summed
        self.assertEqual(_agent_row(section, "qa-scout"), (1, 49))
        self.assertEqual(_agent_row(section, "conductor"), (1, 5))
        # the scout's money comes from the cost file (the transcripts); the journal rows carry no charge
        self.assertEqual(_cols(section, "qa-scout"), ("$2.00", DASH, "$2.00"))

    def test_a_session_with_no_driver_row_keeps_the_capture_attribution(self):
        section = _by_agent(D.tab_cost(self.sessions, {}, None, self.driver, {}))
        self.assertEqual(_agent_row(section, "orchestrator"), (1, 1))

    def test_without_driver_rows_the_capture_attribution_stands_and_the_note_says_so(self):
        # the control that lets the per-role test fail: same sessions, no journal
        section = _by_agent(D.tab_cost(self.sessions, {}, None, {}, {}))
        self.assertIsNone(_agent_row(section, "qa-scout"))
        self.assertEqual(_agent_row(section, "orchestrator"), (3, 3))
        self.assertIn("no driver-runs journal", section)

    def test_the_note_names_the_sources_and_the_status_of_the_price(self):
        note = _by_agent(D.tab_cost(self.sessions, {}, None, self.driver, {}))
        self.assertIn("state/cost", note)
        self.assertIn("usage_status: provisional x3", note)
        self.assertIn("priced from state/cost (provisional)", note)
        self.assertIn("driver-runs.jsonl for 2 of 3 sessions", note)

    def test_first_role_wins_and_is_counted_and_a_session_under_two_tasks_is_named(self):
        driver = {"s-scout": _driver("T-1", {"kind": "role", "role": "qa-scout", "num_turns": 3},
                                     {"kind": "role", "role": "qa-runner", "num_turns": 4})}
        section = _by_agent(D.tab_cost(self.sessions[:1], {}, None, driver, {"s-scout": 2}))
        self.assertEqual(_agent_row(section, "qa-scout"), (1, 7))
        self.assertIsNone(_agent_row(section, "qa-runner"))
        self.assertIn("1 dispatch(es) carry role rows of different roles: the first role is kept", section)
        self.assertIn("session s-scout appears under 2 tasks", section)

    def test_a_session_of_neither_role_nor_conductor_is_its_own_record_named_by_its_kind_never_the_orchestrator(self):
        driver = {"s-scout": _driver("T-1", {"kind": "delivery", "num_turns": 9})}
        section = _by_agent(D.tab_cost(self.sessions[:1], {}, None, driver, {}))
        self.assertEqual(_agent_row(section, "delivery"), (1, 9))
        self.assertIsNone(_agent_row(section, "orchestrator"))

    def test_a_ticket_session_is_the_scouts_record(self):
        driver = {"s-scout": _driver("T-1", {"kind": "ticket", "num_turns": 9})}
        section = _by_agent(D.tab_cost(self.sessions[:1], {}, None, driver, {}))
        self.assertEqual(_agent_row(section, "qa-scout"), (1, 9))
        self.assertIsNone(_agent_row(section, "ticket"))
        self.assertIsNone(_agent_row(section, "orchestrator"))

    def test_parse_driver_runs_takes_the_earliest_task_and_skips_rows_without_a_session(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for task, ts in (("T-B", "2026-09-02T00:00:00"), ("T-A", "2026-09-01T00:00:00")):
                path = root / "qa-factory" / "artifacts" / task / "state"
                path.mkdir(parents=True)
                (path / "driver-runs.jsonl").write_text(
                    json.dumps({"ts": ts, "kind": "role", "role": "qa-scout", "session_id": "s1", "num_turns": 1}) + "\n"
                    + json.dumps({"ts": ts, "kind": "delivery", "outcome": "nothing_outward"}) + "\nnot json\n",
                    encoding="utf-8")
            by_session, spread = D.parse_driver_runs(root)
            self.assertEqual(list(by_session), ["s1"])
            self.assertEqual(by_session["s1"]["task"], "T-A")
            self.assertEqual(spread, {"s1": 2})


class SelectTaskSessionsTests(unittest.TestCase):
    def test_a_driver_row_beats_the_cost_file_tagging_and_nothing_is_dropped_silently(self):
        untagged = _session("u", D.NO_TASK, 0.4)                  # the driver launched it for T-1
        other = _session("o", "T-2", 3.0)
        stray = _session("x", D.NO_TASK, 0.7)                     # nothing names a task
        own = _session("w", "T-1", 1.0)
        shared = _shared_session("m")
        driver = {"u": _driver("T-1", {"kind": "conductor"})}
        got = D.select_task_sessions([untagged, other, stray, own, shared], ["T-1"], driver)
        self.assertEqual([s["session_id"] for s in got["whole"]], ["u", "w"])
        self.assertEqual([s["session_id"] for s in got["shared"]], ["m"])
        self.assertEqual(got["shares"]["m"], {"tokens": 100, "requests": 4, "cost": 1.5})
        self.assertEqual(got["other"], 1)
        self.assertEqual([s["session_id"] for s in got["not_attributed"]], ["x"])

    def test_the_view_counts_the_requests_the_tasks_evidence_binds_of_a_shared_session_and_lists_the_stray_one_unadded(self):
        own = _session("w", "T-1", 1.0)
        stray = _session("x", D.NO_TASK, 0.7)
        shared = _shared_session("m")
        view = D.select_task_sessions([own, stray, shared], ["T-1"], {})
        view["tasks"] = ["T-1"]
        html = D.tab_cost(view["whole"], {}, None, {}, {}, view)
        self.assertIn("Not attributed to T-1", html)
        self.assertIn("$0.70", html)                        # listed with its cost ...
        section = _by_agent(html)
        # ... never added: 1.00 of the whole session + the 4 requests of the shared one that its story activity
        # names T-1 for ($1.50), none of the other task's $3.50
        self.assertEqual(_cols(section, "orchestrator"), ("$2.50", DASH, "$2.50"))
        self.assertEqual(_agent_row(section, "orchestrator"), (2, 5))
        self.assertIn("of which only the requests this task&#x27;s evidence binds are counted: 1", html)
        by_task = html.split("By task</h2>")[1].split("</section>")[0]
        self.assertIn("<td class='money'>$2.50</td>", by_task)              # By task says the same, from the same answer
        self.assertIn("<td>2</td>", by_task)


def _money(section, agent):
    """The PRICE cell of one "By agent" row as printed, or None."""
    cols = _cols(section, agent)
    return cols[2] if cols else None


class DriverChargedCostTests(unittest.TestCase):
    """FR-25 and P18: two records of one quantity, both shown. The transcripts priced at the catalogue's rates and
    the driver's own record of what the CLI charged (cumulative per session); where they differ the price is a
    range, and a session with one record is priced by it."""

    def setUp(self):
        self.sessions = [_session("s-auto", "T-1", 5.0), _session("s-cond", "T-1", 1.0),
                         _session("s-scout", "T-1", 2.0), _session("s-plain", "T-2", 4.0)]
        self.driver = {
            # a resumed session: the second total INCLUDES the first (cumulative), never added to it
            "s-auto": _driver("T-1", {"kind": "role", "role": "qa-automator", "num_turns": 9, "total_cost_usd": 1.0},
                              {"kind": "role", "role": "qa-automator", "num_turns": 24, "total_cost_usd": 3.0}),
            "s-cond": _driver("T-1", {"kind": "conductor", "num_turns": 5, "total_cost_usd": 0.5}),
            "s-scout": _driver("T-1", {"kind": "role", "role": "qa-scout", "num_turns": 7, "total_cost_usd": None}),
        }
        self.section = _by_agent(D.tab_cost(self.sessions, {}, None, self.driver, {}))

    def test_the_charge_column_is_the_last_cumulative_total_never_the_sum_of_a_sessions_rows(self):
        # the CLI's charge is $3.00 (the last cumulative total: not $4.00), the transcripts say $5.00: a range
        self.assertEqual(_cols(self.section, "qa-automator"), ("$5.00", "$3.00", "from $3.00 to $5.00"))
        self.assertEqual(_cols(self.section, "conductor"), ("$1.00", "$0.50", "from $0.50 to $1.00"))
        self.assertEqual(_agent_row(self.section, "qa-automator"), (1, 33))  # turns stay summed per launch

    def test_a_session_with_no_usable_total_is_priced_by_its_transcripts_and_a_plain_one_is_untouched(self):
        self.assertEqual(_cols(self.section, "qa-scout"), ("$2.00", DASH, "$2.00"))
        self.assertEqual(_cols(self.section, "orchestrator"), ("$4.00", DASH, "$4.00"))
        self.assertIn("No CLI charge is known for 2 session(s)", self.section)    # the scout and the plain session

    def test_the_rows_add_up_to_the_price_and_the_page_says_so_at_cents(self):
        # T-1: automator 3.00..5.00 + conductor 0.50..1.00 + scout 2.00 = 5.50..8.00; T-2: the plain session 4.00
        self.assertEqual(_cols(self.section, "qa-automator")[2], "from $3.00 to $5.00")
        self.assertIn("<td>Sum of orchestrator + agents</td><td></td><td>", self.section)
        self.assertIn("<td class='money'>from $9.50 to $12.00</td>", self.section)
        self.assertIn("The rows add up to the price.", self.section)
        self.assertIn("<td>The rows add up to the price (check)</td>", self.section)
        self.assertIn("<td class='ok'>" + TICK + "</td>", self.section)

    def test_the_last_usable_total_wins_when_the_last_row_has_none(self):
        driver = {"s-auto": _driver("T-1", {"kind": "role", "role": "qa-automator", "total_cost_usd": 2.0},
                                    {"kind": "role", "role": "qa-automator", "total_cost_usd": "n/a"})}
        section = _by_agent(D.tab_cost(self.sessions[:1], {}, None, driver, {}))
        self.assertEqual(_cols(section, "qa-automator"), ("$5.00", "$2.00", "from $2.00 to $5.00"))

    def test_a_root_with_no_driver_journal_is_exactly_todays_view_and_says_no_such_sentence(self):
        section = _by_agent(D.tab_cost(self.sessions, {}, None, {}, {}))
        self.assertEqual(_cols(section, "orchestrator"), ("$12.00", DASH, "$12.00"))
        self.assertNotIn("CLI charged", section)
        self.assertNotIn("Two records of the same money", section)      # no answer asked: no claim about two records
        self.assertIn("so this total matches By task", section)

    def test_a_journal_with_no_usable_total_is_one_record_and_prints_no_charge(self):
        driver = {"s-auto": _driver("T-1", {"kind": "role", "role": "qa-automator", "num_turns": 1})}
        section = _by_agent(D.tab_cost(self.sessions[:1], {}, None, driver, {}))
        self.assertNotIn("CLI charged", section)
        self.assertEqual(_cols(section, "qa-automator"), ("$5.00", DASH, "$5.00"))


class ConductorShareTests(unittest.TestCase):
    """In a driver run the capture files every session under `orchestrator` (100%); the
    orchestrator was replaced by the conductor + code, so the share is the conductor's."""

    def setUp(self):
        self.sessions = [_session("s-cond", "T-1", 2.0, tokens=2), _session("s-role", "T-1", 8.0, tokens=8)]
        self.driver = {"s-cond": _driver("T-1", {"kind": "conductor", "total_cost_usd": 2.0}),
                       "s-role": _driver("T-1", {"kind": "role", "role": "qa-scout", "total_cost_usd": 8.0})}

    @staticmethod
    def _card(html):
        return re.search(r"<div class='val'>([^<]*)</div><div class='lbl'>orchestrator token share", html).group(1)

    def test_conductor_two_of_ten_tokens_is_twenty_percent(self):
        self.assertEqual(self._card(D.tab_cost(self.sessions, {}, None, self.driver, {})), "20%")

    def test_without_a_journal_it_is_the_captures_own_share(self):
        self.assertEqual(self._card(D.tab_cost(self.sessions, {}, None, {}, {})), "100%")

    def test_the_banner_share_line_reads_the_conductor_too(self):
        runs = [{"task": "T-1"}]
        self.assertEqual(D.orchestrator_shares(self.sessions, runs, 30, self.driver), [])   # 20% of $10: under the limit
        line = D.orchestrator_shares(self.sessions, runs, 15, self.driver)
        self.assertEqual(len(line), 1)                                                      # the same 20 %, over a limit of 15
        self.assertIn("spent 20 % of the story (limit 15 %)", line[0])
        self.assertTrue(D.orchestrator_shares(self.sessions, runs, 30, {}))                 # no journal: 100 %, a finding


class SessionIdentityTests(unittest.TestCase):
    """The critic's probe: other task $3, own $1, a shared file with $1.50 of $5 for this task."""

    def _view_agent_total(self, ids):
        other = _session("o" if ids else None, "T-2", 3.0)
        own = _session("w" if ids else None, "T-1", 1.0)
        shared = _shared_session("m" if ids else None)
        view = D.select_task_sessions([other, own, shared], ["T-1"], {})
        view["tasks"] = ["T-1"]
        section = _by_agent(D.tab_cost(view["whole"], {}, None, {}, {}, view))
        return _money(section, "orchestrator")

    def test_files_without_session_ids_get_their_own_share_not_someone_elses(self):
        self.assertEqual(self._view_agent_total(ids=False), "$2.50")     # was $6.00: the share hit the wrong file

    def test_the_same_files_with_ids_give_the_same_number(self):
        self.assertEqual(self._view_agent_total(ids=True), "$2.50")

    def test_a_file_without_an_id_is_identified_by_the_path_it_was_read_from(self):
        self.assertEqual(D.session_key({"session_id": "abc", "_source_file": "x.json"}), "abc")
        self.assertEqual(D.session_key({"_source_file": "x.json"}), "x.json")


class StraySessionTests(unittest.TestCase):
    """FR-24 and P18: a session the cost file tags to a task whose driver journal does not know it is the task's
    only by EVIDENCE: a story activity of the task binds it (`task_price`), a bare tag never does. The page says the
    same thing in the task view, in the default view and in the card: one call, one answer."""

    def setUp(self):
        self.tagged = _session("s-role", "T-1", 2.0)
        self.stray = _session("s-stray", "T-1", 1.0)          # story activity of T-1, no journal row
        self.driver = {"s-role": _driver("T-1", {"kind": "role", "role": "qa-scout", "num_turns": 6, "total_cost_usd": 1.5})}

    def _page(self, sessions):
        view = D.select_task_sessions(sessions, ["T-1"], self.driver)
        view["tasks"] = ["T-1"]
        return D.tab_cost(view["whole"], {}, None, self.driver, {}, view)

    def test_the_stray_session_with_the_tasks_story_activity_is_in_the_price_as_the_captures_orchestrator_row(self):
        section = _by_agent(self._page([self.tagged, self.stray]))
        self.assertEqual(_agent_row(section, "orchestrator"), (1, 1))
        self.assertEqual(_cols(section, "orchestrator"), ("$1.00", DASH, "$1.00"))         # no CLI charge: one record
        self.assertEqual(_cols(section, "qa-scout"), ("$2.00", "$1.50", "from $1.50 to $2.00"))
        self.assertNotIn("no driver record", section)       # the old apart row is gone: the evidence puts it in the price
        self.assertIn("The rows add up to the price.", section)

    def test_the_card_the_by_task_row_and_by_agent_say_the_same_range_with_the_stray_session(self):
        html = self._page([self.tagged, self.stray])
        by_task = html.split("By task</h2>")[1].split("</section>")[0]
        # from $2.50 to $3.00: the scout's 1.50..2.00, plus the stray session's 1.00 (one record)
        self.assertIn("<td class='money'>from $2.50 to $3.00</td>", by_task)
        self.assertIn("<td>2</td>", by_task)
        self.assertIn("<td class='money'>from $2.50 to $3.00</td>", _by_agent(html))
        # and the spend card of the same tab (T-1 is no ticket-shaped id, so it has no card of its own)
        self.assertIn("<div class='val'>from $2.50 to $3.00</div><div class='lbl'>factory spend, this project</div>", html)

    def test_a_tag_with_no_evidence_is_no_part_of_the_price_and_is_listed_apart(self):
        tag_only = _session("s-tag", "T-1", 1.0)
        tag_only["by_activity"] = {"a": {"type": "unclassified", "task": None}}    # the requests carry the tag, no story activity
        html = D.tab_cost([self.tagged, tag_only], {}, None, self.driver, {})
        by_task = html.split("By task</h2>")[1].split("</section>")[0]
        self.assertIn("<td>T-1</td><td>1</td>", by_task)                                 # the journal's one session
        self.assertIn("<td>T-1 - not launched by the driver</td><td>1</td>", by_task)
        self.assertIn("<td class='money'>from $1.50 to $2.00</td>", by_task)              # the price: the scout alone


class BugDedupTests(unittest.TestCase):
    def _root(self, project=(), per_task=()):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for name, title, extra in project:
            _bug_file(root / "qa-factory" / "bugs" / name, title, **extra)
        for task, name, title, extra in per_task:
            _bug_file(root / "qa-factory" / "artifacts" / task / "bugs" / name, title, **extra)
        return root

    def test_two_bug_1_files_with_different_titles_are_two_bugs(self):
        root = self._root(project=[("BUG-1.md", "Project-level title", {"task": "T-1"})],
                          per_task=[("T-1", "BUG-1.md", "Per-task title", {})])
        bugs, sources = D.load_bugs(root)
        self.assertEqual(sorted(b["title"] for b in bugs), ["Per-task title", "Project-level title"])
        self.assertEqual(sources["merged"], 0)

    def test_identical_copies_in_both_places_are_one_bug(self):
        root = self._root(project=[("BUG-1.md", "Same title", {"task": "T-1"})],
                          per_task=[("T-1", "BUG-1.md", "Same title", {"task": "T-1"})])
        bugs, sources = D.load_bugs(root)
        self.assertEqual([b["title"] for b in bugs], ["Same title"])
        self.assertEqual(sources["merged"], 1)

    def test_a_record_whose_task_cannot_be_read_is_never_merged(self):
        root = self._root(project=[("BUG-1.md", "Same title", {})],       # no task in its front matter
                          per_task=[("T-1", "BUG-1.md", "Same title", {})])
        self.assertEqual(len(D.load_bugs(root)[0]), 2)

    def test_the_same_name_and_title_under_two_tasks_are_two_bugs(self):
        root = self._root(per_task=[("T-1", "BUG-1.md", "Same title", {}), ("T-2", "BUG-1.md", "Same title", {})])
        self.assertEqual(len(D.load_bugs(root)[0]), 2)


class BareRootTests(unittest.TestCase):
    def test_read_only_on_a_root_with_no_qa_factory_directory_leaves_nothing_behind(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "bare"
            root.mkdir()
            out = Path(td) / "page.html"
            before = sorted(str(p) for p in root.rglob("*"))
            _run_main("--root", str(root), "--read-only", "--out", str(out))
            self.assertEqual(sorted(str(p) for p in root.rglob("*")), before)
            self.assertEqual(before, [])
            self.assertTrue(out.exists())


class TaskViewPageTests(unittest.TestCase):
    """The real renderer on the synthetic project of dashboard_fixture: three tasks in one root."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name) / "project"
        build(cls.root)
        state = cls.root / "qa-factory" / "artifacts" / "DEMO-15046" / "state"
        state.mkdir(parents=True, exist_ok=True)
        rows = [{"ts": "2026-09-20T10:00:00", "kind": "role", "role": "qa-automator", "session_id": "DEMO-15046-0", "num_turns": 30},
                {"ts": "2026-09-20T11:00:00", "kind": "conductor", "role": "", "session_id": "DEMO-15046-0-x", "num_turns": 4}]
        (state / "driver-runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        cls.outdir = Path(cls.tmp.name) / "out"
        cls.outdir.mkdir()
        cls.before = _tree_hash(cls.root)
        cls.out_task = cls.outdir / "task.html"
        cls.printed = _run_main("--root", str(cls.root), "--task", "DEMO-15046", "--read-only", "--out", str(cls.out_task))
        cls.page = cls.out_task.read_text(encoding="utf-8")
        cls.out_missing = cls.outdir / "missing.html"
        cls.printed_missing = _run_main("--root", str(cls.root), "--task", "NOPE-1", "--read-only", "--out", str(cls.out_missing))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @staticmethod
    def _panel(page, name):
        return page.split(f"id='{name}'>")[1].split("<div class='panel")[0]

    def test_read_only_changes_nothing_under_the_root(self):
        self.assertEqual(_tree_hash(self.root), self.before)

    def test_the_header_says_which_task_and_how_many_others_the_root_holds(self):
        self.assertIn("Task: DEMO-15046", self.page)
        self.assertIn("the root holds 2 other task(s), not shown", self.page)

    def test_the_testing_tab_shows_only_that_tasks_rows(self):
        testing = self._panel(self.page, "testing")
        mine = next(c["title"] for c in CASES if c["task"] == "DEMO-15046")
        theirs = next(c["title"] for c in CASES if c["task"] == "DEMO-15045")
        by_story = testing.split("Tests by task (pyramid)</h2>")[1].split("</section>")[0]
        self.assertIn("DEMO-15046", by_story)
        self.assertNotIn("DEMO-15045", by_story)
        self.assertNotIn("DEMO-15047", by_story)
        # the metric widgets are the whole root's and say so; only they may name the other tasks
        self.assertIn("All tasks in this root: the sections below carry no task key.", testing)
        self.assertIn(mine, testing)
        self.assertNotIn(theirs, testing)

    def test_by_task_holds_only_the_task_and_the_whole_root_sections_say_so(self):
        cost = self._panel(self.page, "cost")
        by_task = cost.split("By task</h2>")[1].split("</section>")[0]
        self.assertIn("DEMO-15046", by_task)
        self.assertNotIn("DEMO-15045", by_task)
        self.assertIn("All tasks in this root: the sections below carry no task key.", cost)
        self.assertIn("All tasks in this root: the sections below carry no task key.", self._panel(self.page, "factory"))

    def test_by_agent_reads_the_role_from_the_drivers_journal(self):
        section = _by_agent(self._panel(self.page, "cost"))
        self.assertEqual(_agent_row(section, "qa-automator"), (1, 30))
        self.assertIn("artifacts/&lt;task&gt;/state/driver-runs.jsonl", section)

    def test_a_task_the_root_does_not_hold_is_an_empty_view_and_one_warning(self):
        self.assertIn("no artifacts for NOPE-1 under", self.printed_missing)
        page = self.out_missing.read_text(encoding="utf-8")
        self.assertIn("no artifacts for NOPE-1 under", page)
        self.assertNotIn(next(c["title"] for c in CASES if c["task"] == "DEMO-15045"), page)

    def test_no_task_flag_is_todays_view(self):
        out = self.outdir / "all.html"
        _run_main("--root", str(self.root), "--read-only", "--out", str(out))
        page = out.read_text(encoding="utf-8")
        self.assertNotIn("Task: ", page)
        testing = self._panel(page, "testing")
        for task in ("DEMO-15045", "DEMO-15046", "DEMO-15047"):
            self.assertIn(task, testing)


def _bug_file(path, title, **extra):
    path.parent.mkdir(parents=True, exist_ok=True)
    head = {"id": path.stem, "title": title, "severity": "major", "status": "Open", "area": "x",
            "found_by": "qa-bug-reporter", "violates": "requirement:R-1", "created": "2026-09-20"}
    head.update(extra)
    path.write_text("---\n" + "".join(f"{k}: {v}\n" for k, v in head.items()) + "---\n\n## Steps\n1. x\n", encoding="utf-8")


class BugsAndLeaksTests(unittest.TestCase):
    """Two tasks with revisions, case-link issues and bugs in one root; the view of one of them."""

    @classmethod
    def setUpClass(cls):
        import metrics_projection as MP
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name) / "project"
        build(cls.root)
        art = cls.root / "qa-factory" / "artifacts"
        _bug_file(art / "DEMO-15046" / "bugs" / "BUG-1.md", "MINE per-task bug")
        _bug_file(art / "DEMO-15045" / "bugs" / "BUG-1.md", "THEIRS per-task bug")   # same name, other task
        _bug_file(cls.root / "qa-factory" / "bugs" / "BUG-7.md", "PROJECT-LEVEL bug")
        real_parse, real_project = D.parse_taskruns, MP.project

        def parse(root, include_archive=False):
            runs = real_parse(root, include_archive)
            for r in runs:
                r["case_lifecycle_issues"] = [f"case link {r['task']}-MARK/cv_x content hash does not match its pinned version"]
            return runs

        def project(*args, **kwargs):
            result = real_project(*args, **kwargs)
            # F07 as project() builds it from the tasks it is GIVEN (the fixture's tasks do not
            # reach that branch on their own): the task view must swap in the requested tasks' list
            for m in result["metrics"]:
                if m["id"] == "F07":
                    m["value"] = [{"task": t["task"], "stale": False, "issues": t["case_lifecycle_issues"]} for t in args[1]]
                    m["sample_size"] = len(m["value"])
                    m["status"] = "available"
            result["estimates"] = [
                {"task": "DEMO-15045", "ts": "2026-09-01", "completed": True, "complete_cost": 2.0, "drivers": ["DRV-THEIRS"],
                 "forecast": {"size_initial": "S", "size_final": "M"}, "delta": {"size_change": "S → M", "direction": "within"}},
                {"task": "DEMO-15046", "ts": "2026-09-02", "completed": True, "complete_cost": 3.0, "drivers": ["DRV-MINE"],
                 "forecast": {"size_initial": "M", "size_final": "XL"}, "delta": {"size_change": "M → XL", "direction": "within"}}]
            return result

        D.parse_taskruns, MP.project = parse, project
        try:
            out = Path(cls.tmp.name) / "out"
            out.mkdir()
            _run_main("--root", str(cls.root), "--task", "DEMO-15046", "--read-only", "--out", str(out / "task.html"))
            _run_main("--root", str(cls.root), "--read-only", "--out", str(out / "whole.html"))
        finally:
            D.parse_taskruns, MP.project = real_parse, real_project
        cls.task_page = (out / "task.html").read_text(encoding="utf-8")
        cls.whole_page = (out / "whole.html").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_both_bug_homes_are_read_a_name_in_both_counts_once_and_two_tasks_keep_their_own(self):
        bugs, sources = D.load_bugs(self.root)
        self.assertEqual(sorted(b["title"] for b in bugs),
                         ["MINE per-task bug", "PROJECT-LEVEL bug", "THEIRS per-task bug"])
        self.assertEqual(sources, {"project": 1, "tasks": {"DEMO-15045": 1, "DEMO-15046": 1}, "merged": 0})
        self.assertEqual({b["task"] for b in bugs if "per-task" in b["title"]}, {"DEMO-15045", "DEMO-15046"})

    def test_a_bug_of_the_task_folder_is_shown_in_its_story_and_the_note_names_the_locations(self):
        self.assertIn("MINE per-task bug", self.task_page)
        self.assertNotIn("THEIRS per-task bug", self.task_page)
        self.assertIn("Bugs read from qa-factory/bugs/ (1 file(s)) and artifacts/&lt;task&gt;/bugs/ (2 file(s)", self.task_page)
        self.assertIn("Shown in this view: 1.", self.task_page)
        self.assertIn("MINE per-task bug", self.whole_page)
        self.assertIn("THEIRS per-task bug", self.whole_page)

    def test_the_revision_matrix_and_precedents_hold_only_the_tasks_estimates(self):
        for marker in ("M</td><td>XL", "DEMO-15046"):
            self.assertIn(marker, self.task_page)
        section = self.task_page.split("Revision matrix</h2>")[1].split("</section>")[0]
        self.assertIn("XL", section)
        self.assertNotIn(">S<", section)
        whole = self.whole_page.split("Revision matrix</h2>")[1].split("</section>")[0]
        self.assertIn(">S<", whole)
        self.assertNotIn("DRV-THEIRS", self.task_page)

    def test_the_testing_tabs_case_link_block_is_the_tasks_own(self):
        block = self.task_page.split("Case-version proof gaps</h2>")[1].split("</section>")[0]
        self.assertIn("DEMO-15046-MARK", block)
        self.assertNotIn("DEMO-15045-MARK", block)
        whole_block = self.whole_page.split("Case-version proof gaps</h2>")[1].split("</section>")[0]
        self.assertIn("DEMO-15045-MARK", whole_block)      # the control: the whole page does carry them

    def test_every_metric_value_in_the_task_view_is_the_whole_roots_value(self):
        # FR-10 / owner: metrics and trends are never filtered, so the page cannot hold two
        # numbers for one quantity. F07 (a list of tasks) is the one that used to be swapped.
        def values(page):
            return dict(re.findall(r"<tr id='(\w+)' data-metric='\1'>.*?data-label='Value'[^>]*>(.*?)</td>", page))
        task_values, whole_values = values(self.task_page), values(self.whole_page)
        # T09 is an age in days measured from "now": it moves between two renders of ANY view
        task_values.pop("T09", None), whole_values.pop("T09", None)
        self.assertGreater(len(whole_values), 20)
        self.assertEqual(task_values, whole_values)
        self.assertIn("DEMO-15045-MARK", task_values["F07"])
        self.assertIn("All tasks in this root: the sections below carry no task key.", self.task_page)

    def test_the_estimates_table_says_it_is_this_tasks_only(self):
        self.assertIn("The estimates table below shows DEMO-15046 only; the metric widgets above are the whole root&#x27;s."
                      .replace("&#x27;", "'"), self.task_page)
        self.assertNotIn("The estimates table below shows", self.whole_page)


class MetricsStayWholeTests(unittest.TestCase):
    def test_a_task_view_never_filters_metrics_or_their_history(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "project"
            build(root)
            state = root / "qa-factory" / "state"
            _run_main("--root", str(root), "--out", str(Path(td) / "whole.html"))
            counts = {t: (state / "metrics.json").read_text(encoding="utf-8").count(t)
                      for t in ("DEMO-15045", "DEMO-15046", "DEMO-15047")}
            _run_main("--root", str(root), "--task", "DEMO-15046", "--out", str(Path(td) / "task.html"))
            after = (state / "metrics.json").read_text(encoding="utf-8")
            self.assertEqual({t: after.count(t) for t in counts}, counts)
            history = json.loads((state / "metrics-history.json").read_text(encoding="utf-8"))
            self.assertEqual(len(history["snapshots"]), 1)      # today's point, replaced, never a second one
            page = (Path(td) / "task.html").read_text(encoding="utf-8")
            self.assertIn("Metric warnings and trends: all tasks in this root, never filtered", page)


class TriageVerdictOnTheCardTests(unittest.TestCase):
    """t-323 A2 (critic t-322 B-F1): the story's tests table reads the triage through `contract.bind_triage` - the one
    binding the ledger, gate B and S7 read - so the analyst's `x[chromium]` row is the verdict of the run report's `x`."""

    @staticmethod
    def _page(triage_rows):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "project"
            build(root)
            work = root / "qa-factory" / "artifacts" / "DEMO-15046" / "work"
            report = json.loads((work / "run-report.json").read_text(encoding="utf-8"))
            report["current_results"].append({"case": "DEMO-X-1", "test_id": "demo::xtest", "instance_id": "xtest",
                                              "status": "failed", "level": "api", "reason": "boom",
                                              "execution_scope": "feature", "attempt_id": "a-new"})
            (work / "run-report.json").write_text(json.dumps(report), encoding="utf-8")
            manifest = json.loads((work / "automation-manifest.json").read_text(encoding="utf-8"))
            manifest["tests"].append({"case": "DEMO-X-1", "test_id": "demo::xtest", "instance_id": "xtest", "level": "api"})
            (work / "automation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (work / "triage.json").write_text(json.dumps({"triage": triage_rows}), encoding="utf-8")
            out = Path(td) / "page.html"
            _run_main("--root", str(root), "--task", "DEMO-15046", "--read-only", "--out", str(out))
            page = out.read_text(encoding="utf-8")
        return page.split("<span class='id'>demo::xtest</span>")[1].split("</tr>")[0]

    def test_a_parameter_row_is_the_verdict_of_the_failure_without_it(self):
        for attempt in ({}, {"attempt_id": "a-new"}):       # a row naming no attempt answers the current one; so does its own
            row = self._page([dict({"instance_id": "xtest[chromium]", "verdict": "ENV_ISSUE"}, **attempt)])
            self.assertIn("<td><span class='skip'>ENV_ISSUE</span></td>", row, attempt)
            self.assertIn("p-env", row)

    def test_controls_no_row_and_a_sibling_row_show_no_verdict(self):
        for label, rows in (("no row", []), ("a row of another test", [{"instance_id": "other[chromium]", "verdict": "ENV_ISSUE"}]),
                            ("a row of another attempt", [{"instance_id": "xtest[chromium]", "verdict": "ENV_ISSUE",
                                                           "attempt_id": "a-old"}])):
            row = self._page(rows)
            self.assertNotIn("ENV_ISSUE", row, label)
            self.assertIn("<td>—</td>", row, label)


class RefusalTests(unittest.TestCase):
    def test_a_partial_or_read_only_render_never_writes_the_shared_page(self):
        with tempfile.TemporaryDirectory() as td:
            for flags in (["--read-only"], ["--task", "T-1"]):
                with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
                    D.main(["--root", td] + flags)
                self.assertIn("need --out", err.getvalue())

    def test_read_only_refuses_an_out_inside_the_root(self):
        with tempfile.TemporaryDirectory() as td:
            with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
                D.main(["--root", td, "--read-only", "--out", str(Path(td) / "qa-factory" / "x.html")])
            self.assertIn("nothing under the root may change", err.getvalue())


if __name__ == "__main__":
    unittest.main()
