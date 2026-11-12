"""CD1-27 (P18, one true price): a driver story is ONE row of By task with its money AND its time, and a session
that only TAGS the task is named "unbound" on that row, never guessed into the price.

The control fixture is the t-1605 night in miniature: five driver sessions of TASK (cost files tagged differently,
one resumed twice), a manual-run file named by no journal. The money of every row is what it was before this change
(the price is `task_price`'s, a tag never moves a dollar); what changed is the time column (the sessions' machine
time, from their cost files) and the words about the sessions no evidence binds.
"""
import html
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import factory_dashboard as D
import dashboard_cost_groups as G
from test_dashboard_task_binding import (COLD, SMALL, TASK, Case, by_task_rows, carry, cost_file, golden_fixture, jrow,
                                         mask, render, request, section, slug_of, total_row, write_root)

NO_TASK = "(no task)"
OTHER = "T-OTHER"


def entry(machine_s, requests=3, cost=0.1):
    return {"tokens": 1, "requests": requests, "cost": cost, "machine_s": machine_s}


def dfile(sid, slug, cost, by_task, **extra):
    """A driver session's cost file: ONE collapsed carry row, the by_task the markers left (tag -> entry)."""
    f = carry(sid, slug, tags=tuple(by_task), cost=cost)
    f["by_task"] = by_task
    f.update(extra)
    return f


def night_files(slug):
    """d1..d5 priced $1.25 / $0.75 / $2.00 / $0.50 / $3.10 (sum $7.60), times 600 / 300 / 120 / 60 / 3000 s (4080 s)."""
    return [dfile("d1", slug, 1.25, {NO_TASK: entry(600)}),
            dfile("d2", slug, 0.75, {NO_TASK: entry(300)}),
            dfile("d3", slug, 2.00, {TASK: entry(120)}),
            dfile("d4", slug, 0.50, {NO_TASK: entry(60), TASK: entry(None, requests=1)}),
            dfile("d5", slug, 3.10, {NO_TASK: entry(1800), TASK: entry(1200)})]


def manual_file(slug, sid="m1"):
    """The manual run's shape: no factory activity, ONE carry row $2.20, tags the task, named by no journal."""
    return dfile(sid, slug, 2.20, {TASK: entry(900, cost=1.2), NO_TASK: entry(100, cost=1.0)})


def night_journal(totals=None):
    """One end row per session at its file's price; d5 resumed twice (running totals 1.00, 2.50, 3.10)."""
    totals = totals or {}
    rows = [jrow("role", sid, totals.get(sid, cost), 1, "qa-runner", ts=f"2026-09-30T0{i}:00:00+00:00")
            for i, (sid, cost) in enumerate((("d1", 1.25), ("d2", 0.75), ("d3", 2.00), ("d4", 0.50)), 1)]
    rows += [jrow("role", "d5", t, n, "qa-runner", ts=f"2026-09-30T0{4 + n}:00:00+00:00")
             for n, t in enumerate((1.00, 2.50, 3.10), 1)]
    return rows


def cells(page, label):
    """The cells of the By task row `label` (text, unescaped), or None."""
    m = re.search(r"<tr><td>" + re.escape(html.escape(label, quote=False)) + r"</td>(.*?)</tr>", section(page, "By task"), re.S)
    return [html.unescape(c) for c in re.findall(r"<td[^>]*>([^<]*)</td>", m.group(1))] if m else None


def total_time(page):
    m = re.search(r"<tr class='total'><td>All stories and activities</td><td></td><td>([^<]*)</td>", page)
    return html.unescape(m.group(1)) if m else None


def night_page(td, extra=(), journals=None, files=None, manual=True):
    slug = slug_of(td)
    files = list(files) if files is not None else night_files(slug)
    if manual:
        files.append(manual_file(slug))
    root = write_root(td, files + list(extra), journals if journals is not None else {TASK: night_journal()})
    return render(root)


class ControlValueTests(Case):
    def test_T1_the_task_row_holds_its_five_sessions_its_money_and_its_time(self):
        with tempfile.TemporaryDirectory() as td:
            page = night_page(td)
        row = by_task_rows(page)[TASK]
        self.assertEqual(row[:2], (5, "$7.60"))
        self.assertIn("the two records agree", row[2])
        self.assertIn("unbound: 1 session (not in this price)", row[2])
        self.assertEqual(cells(page, TASK)[1], "1h 08m")      # 600 + 300 + 120 + 60 + 3000 = 4080 s
        self.assertEqual(total_time(page), "1h 08m")
        # the story card carries the same unbound words (t-726 m-2: one wording on every surface)
        self.assertIn("the two records agree · unbound: 1 session (not in this price)", html.unescape(page))

    def test_T2_money_never_moves_with_the_unbound_words(self):
        with tempfile.TemporaryDirectory() as td:
            page = night_page(td)
        with tempfile.TemporaryDirectory() as td:
            slug = slug_of(td)
            plain = dfile("m1", slug, 2.20, {NO_TASK: entry(100, cost=1.0)})       # the same file, tagging nobody
            twin = night_page(td, extra=[plain], manual=False)
        for p in (page, twin):
            self.assertEqual(total_row(p, "All stories and activities"), "$9.80")
            self.assertEqual(by_task_rows(p)["Unclassified"][:2], (1, "$2.20"))
            self.assertEqual(by_task_rows(p)[TASK][:2], (5, "$7.60"))
        self.assertNotIn("unbound", by_task_rows(twin)[TASK][2])
        self.assertIn("unbound", by_task_rows(page)[TASK][2])

    def test_T3_a_resumed_session_is_counted_once(self):
        import task_price as TP
        with tempfile.TemporaryDirectory() as td:
            slug = slug_of(td)
            files = night_files(slug)
            root = write_root(td, files, {TASK: night_journal()})
            driver, spread = D.parse_driver_runs(root)
            answer = TP.task_price(root, TASK, sessions=files, driver=(driver, spread), cfg={})
            page = render(root)
        sessions = {s["session"]: s for s in answer["sessions"]}
        self.assertEqual(len(sessions), 5)
        self.assertEqual(sessions["d5"]["b_usd"], 3.10)          # never 6.60, never the sum of its rows
        self.assertEqual(by_task_rows(page)[TASK][:2], (5, "$7.60"))   # the plain sum of the seven journal rows is $11.10

    def test_T4_a_journal_session_with_no_file_is_untimed_and_named(self):
        ghost = [jrow("role", "g1", 0.40, 1, "qa-runner", ts="2026-09-30T09:00:00+00:00")]
        with tempfile.TemporaryDirectory() as td:
            page = night_page(td, journals={TASK: night_journal() + ghost})
        self.assertEqual(by_task_rows(page)[TASK][:2], (6, "$8.00"))
        self.assertEqual(cells(page, TASK)[1], "1h 08m (1 of 6 sessions untimed)")
        self.assertEqual(total_time(page), "1h 08m (1 session untimed)")       # B-2: not a plain partial sum
        self.assertEqual(total_row(page, "All stories and activities"), "$10.20")

    def test_T4b_a_row_where_every_session_is_untimed_says_unknown_never_a_dash_or_zero(self):
        with tempfile.TemporaryDirectory() as td:
            slug = slug_of(td)
            files = [dfile(sid, slug, c, {NO_TASK: entry(None, requests=4)}) for sid, c in
                     (("d1", 1.25), ("d2", 0.75), ("d3", 2.00), ("d4", 0.50), ("d5", 3.10))]
            page = night_page(td, files=files, manual=False)
        self.assertEqual(cells(page, TASK)[1], "unknown")
        self.assertEqual(total_time(page), "unknown")

    def test_T6a_a_session_counted_in_part_keeps_the_activity_time_of_its_part(self):
        with tempfile.TemporaryDirectory() as td:
            slug = slug_of(td)
            reqs = [request("o1", 0, TASK, 1.0, "a-s", SMALL), request("o1", 1, NO_TASK, 0.5, "unclassified", SMALL)]
            acts = {"a-s": {"type": "story", "task": TASK, "active_s": 90}, "unclassified": {"type": "unclassified", "task": None}}
            orch = cost_file("o1", reqs, slug, activities=acts,
                             by_task={TASK: entry(777, 1), NO_TASK: entry(0, 1)})
            root = write_root(td, [orch], {})
            page = render(root)
        self.assertEqual(cells(page, TASK)[1], "1m 30s")          # 90 s of its activity, never its 777 s session time

    def test_T6b_a_journal_session_is_timed_once_by_its_session_never_activity_plus_session(self):
        with tempfile.TemporaryDirectory() as td:
            slug = slug_of(td)
            reqs = [request("d1", 0, TASK, 1.25, "a-s", COLD)]
            f = cost_file("d1", reqs, slug, activities={"a-s": {"type": "story", "task": TASK, "active_s": 999}},
                          by_task={TASK: entry(600, 1)})
            root = write_root(td, [f], {TASK: [jrow("role", "d1", 1.25, 1, "qa-runner", ts="2026-09-30T01:00:00+00:00")]})
            page = render(root)
        self.assertEqual(cells(page, TASK)[1], "10m 00s")

    def test_T6c_a_root_with_no_journal_keeps_its_time_cells(self):
        with tempfile.TemporaryDirectory() as td:
            page = render(golden_fixture(td))
        self.assertEqual(cells(page, "T-1")[1], "1m 00s")
        self.assertEqual(cells(page, "T-2 - tagged only, not counted in its price")[1], "0m 20s")

    def test_T8_no_journal_no_price_row_no_unbound_words(self):
        with tempfile.TemporaryDirectory() as td:
            page = night_page(td, journals={})
        self.assertNotIn(TASK + "</td>", section(page, "By task"))     # no price row of the task (only "... - tagged only")
        self.assertNotIn("unbound", page)
        with tempfile.TemporaryDirectory() as td:
            slug = slug_of(td)
            root = write_root(td, night_files(slug) + [manual_file(slug)], {})
            state = root / "qa-factory" / "artifacts" / "T-empty" / "state"
            state.mkdir(parents=True)
            (state / "driver-runs.jsonl").write_text("", encoding="utf-8")
            empty = render(root)
        self.assertEqual(mask(empty, root).count("unbound"), 0)

    def test_T9_a_session_of_two_journals_is_counted_under_the_earlier_one_only(self):
        earlier = [jrow("role", "d3", 2.00, 1, "qa-runner", ts="2026-09-29T01:00:00+00:00")]
        with tempfile.TemporaryDirectory() as td:
            page = night_page(td, journals={TASK: night_journal(), "T-B": earlier})
        self.assertEqual(by_task_rows(page)[TASK][0], 4)
        self.assertEqual(by_task_rows(page)["T-B"][:2], (1, "$2.00"))
        self.assertEqual(cells(page, TASK)[1], "1h 06m")                 # 4080 - 120 s
        self.assertIn("session d3 is named by 2 task journals; counted under T-B", html.unescape(page))

    def test_T10_disagreeing_records_print_the_range_and_the_time_stays(self):
        with tempfile.TemporaryDirectory() as td:
            page = night_page(td, journals={TASK: night_journal(totals={"d1": 1.05})})
        row = by_task_rows(page)[TASK]
        self.assertEqual(row[1], "from $7.40 to $7.60")
        self.assertIn("the two records differ", row[2])
        self.assertEqual(cells(page, TASK)[1], "1h 08m")

    def test_B1_a_rebuilt_cost_file_never_adds_a_partial_time_as_the_whole(self):
        with tempfile.TemporaryDirectory() as td:
            slug = slug_of(td)
            files = night_files(slug)
            files[1]["recapture_carried"] = ["stored rows put back"]        # d2: its machine_s was not recomputed
            page = night_page(td, files=files)
        self.assertEqual(cells(page, TASK)[1], "1h 03m (1 of 5 sessions untimed)")     # 4080 - 300 s, d2 named
        self.assertEqual(total_time(page), "1h 03m (1 session untimed)")
        self.assertEqual(by_task_rows(page)[TASK][:2], (5, "$7.60"))             # the money does not move

    def test_unbound_names_where_the_money_is_counted_including_another_tasks_row(self):
        with tempfile.TemporaryDirectory() as td:
            slug = slug_of(td)
            reqs = [request("x1", 0, OTHER, 0.9, "a-o", SMALL)]
            x1 = cost_file("x1", reqs, slug, activities={"a-o": {"type": "story", "task": OTHER, "active_s": 30}},
                           by_task={OTHER: entry(30, 1), TASK: entry(5, 1)})
            page = night_page(td, extra=[x1])
        text = html.unescape(page)
        self.assertEqual(by_task_rows(page)[TASK][0], 5)
        self.assertIn("unbound: 2 sessions (not in this price)", by_task_rows(page)[TASK][2])
        self.assertIn(f"{TASK}: unbound: 2 sessions tag this task in their cost file", text)
        self.assertIn(f"money is counted under {OTHER}, Unclassified (m1, x1)", text)


class SessionMachineTests(Case):
    def test_T5_session_machine_s_adversarial(self):
        def one(**e):
            return G.session_machine_s({"by_task": {"A": e}})
        self.assertIsNone(G.session_machine_s({}))
        self.assertIsNone(G.session_machine_s(None))
        self.assertIsNone(G.session_machine_s({"by_task": "x"}))
        self.assertIsNone(G.session_machine_s({"by_task": {}}))
        self.assertIsNone(one(machine_s=True))
        self.assertIsNone(one(machine_s=-5))
        self.assertIsNone(one(machine_s=float("nan")))
        self.assertIsNone(one(machine_s=float("inf")))
        self.assertIsNone(one(machine_s="60"))
        self.assertEqual(one(machine_s=None, requests=1), 0)
        self.assertIsNone(one(machine_s=None, requests=2))
        self.assertIsNone(one(machine_s=None))
        self.assertIsNone(one(machine_s=None, requests=True))
        self.assertEqual(one(machine_s=59.6), 60)
        self.assertIsNone(G.session_machine_s({"by_task": {"A": 1, "B": {"machine_s": 5}}}))
        self.assertEqual(G.session_machine_s({"by_task": {"A": {"machine_s": 600}, "B": {"machine_s": 1200}}}), 1800)
        # a partial entry poisons the whole session: never the sum of what is known
        self.assertIsNone(G.session_machine_s({"by_task": {"A": {"machine_s": 600}, "B": {"machine_s": None, "requests": 5}}}))
        # B-1: a rebuilt file whose stored rows were put back keeps a stale machine_s
        self.assertIsNone(G.session_machine_s({"by_task": {"A": {"machine_s": 300}}, "recapture_carried": ["rows"]}))
        self.assertEqual(G.session_machine_s({"by_task": {"A": {"machine_s": 300}}, "recapture_carried": []}), 300)

    def test_a_bound_legacy_session_is_timed_whole_or_named_untimed(self):
        legacy = {"session_id": "L1", "by_model": {}, "by_task": {"A": {"tokens": 1, "cost": 0.1, "machine_s": 20},
                                                                  "B": {"tokens": 1, "cost": 0.1, "machine_s": None, "requests": 3}}}
        by_task, _ = G.group([legacy], {"L1": TASK}, whole_time={"L1"})
        self.assertEqual((by_task[TASK]["timed"], by_task[TASK]["untimed_sessions"]), (False, {"L1"}))
        old, _ = G.group([legacy], {"L1": TASK})           # outside whole_time: the code path it always had
        self.assertEqual((old[TASK]["active"], old[TASK]["timed"], old[TASK]["untimed_sessions"]), (20, True, set()))

    def test_blank_rows_do_not_share_their_untimed_set(self):
        a, b = G.blank_row(), G.blank_row()
        a["untimed_sessions"].add("s")
        self.assertEqual(b["untimed_sessions"], set())


class UnboundTests(Case):
    def doc(self, sid, by_task=None, tasks=None):
        d = {"session_id": sid}
        if by_task is not None:
            d["by_task"] = by_task
        if tasks is not None:
            d["tasks"] = tasks
        return d

    def test_T7_unbound_edges(self):
        tag = self.doc("a", {TASK: {}})
        other_journal = self.doc("b", {TASK: {}})
        in_part = self.doc("c", {TASK: {}})
        named_by_string = self.doc("d", tasks=TASK)                         # a string is never split
        other_case = self.doc("e", {TASK.lower(): {}})
        no_task = self.doc("f", {NO_TASK: {}}, tasks=["", NO_TASK])
        non_dict_entry = self.doc("g", {TASK: 5})
        no_id = {"by_task": {TASK: {}}}
        docs = [tag, other_journal, in_part, named_by_string, other_case, no_task, non_dict_entry, no_id]
        got = D.unbound_sessions(docs, TASK, {TASK: {"c": [0]}}, {"b": "T-OTHER"})
        self.assertEqual(got, ["a"])
        self.assertEqual(D._tagged_tasks(named_by_string), set())
        self.assertEqual(D._tagged_tasks(self.doc("h", {TASK: {}, NO_TASK: {}}, tasks=["X", "", NO_TASK])), {TASK, "X"})
        self.assertEqual(D._tagged_tasks(None), set())

    def test_T7_the_id_list_is_capped_at_five_and_the_count_stays_whole(self):
        five = D.unbound_note(TASK, list("abcde"), ["Unclassified"])
        six = D.unbound_note(TASK, list("abcdef"), ["Unclassified"])
        self.assertIn("(a, b, c, d, e).", five)
        self.assertNotIn("more", five)
        self.assertIn("(a, b, c, d, e, and 1 more).", six)
        self.assertIn("unbound: 6 sessions", six)

    def test_the_cell_words_of_one_task_are_one_wording(self):
        self.assertEqual(D.unbound_words(1), "unbound: 1 session (not in this price)")
        self.assertEqual(D.unbound_words(2), "unbound: 2 sessions (not in this price)")

    def test_time_cell_branches(self):
        base = {"timed": False, "active": 0, "sessions": 3, "untimed_sessions": set()}
        self.assertEqual(D.time_cell(base), "—")
        self.assertEqual(D.time_cell(dict(base, untimed_sessions={"x"})), "unknown")
        self.assertEqual(D.time_cell(dict(base, timed=True, active=65)), "1m 05s")
        self.assertEqual(D.time_cell(dict(base, timed=True, active=65, untimed_sessions={"x"})), "1m 05s (1 of 3 sessions untimed)")
        self.assertEqual(D.total_time_cell([dict(base, timed=True, active=65), dict(base, untimed_sessions={"x", "y"})]),
                         "1m 05s (2 sessions untimed)")


if __name__ == "__main__":
    unittest.main()
