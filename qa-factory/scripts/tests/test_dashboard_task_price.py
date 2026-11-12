"""The dashboard reads the ONE price of a task (t-137 Q5, R8 and R11) and the health card's share is
"conductor + code" (t-111 P2, R8-R10, R12).

Every money surface of a story - By task and its check label, the story card, By agent, the estimates and their
note, the spend card, the task view - reads the answer `task_price` gave, asked ONCE per task by main(). While the
two records (the transcripts at the catalogue's rates, and what the CLI itself charged) differ the price is a RANGE,
never one figure with a caption. Every cost file is re-priced at read (the catalogue's rates, a project's
`rate_overrides` as the price base): what a file was captured with is never read. The health card's share is the
conductor's records and the capture's orchestrator stream of sessions no journal names, over all records; a ticket or
data-fetching call is the scout's.

One check per requirement of the dispatch (item numbers 1-6) and per edge; the fixtures are the ones of
test_dashboard_task_binding.py (cost files priced from their own usage at the catalogue's rates).
"""
import html
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_dashboard_task_binding as B   # the shared fixtures (no test class of it is collected here)
import cost_capture as CC
import factory_dashboard as D
import task_price as TP

TASK, MODEL = B.TASK, B.MODEL
DASH, TICK = B.DASH, chr(0x2713)
REVISION = CC.load_catalogue()["catalogue_revision"]
OVERRIDE_RATES = {"input": 4, "output": 20, "cache_read": 0.2, "cache_write_5m": 5, "cache_write_1h": 8}   # twice the catalogue's (Sonnet 5.5 cache read is 0.10)


def legacy_pinned(doc, factor=1.5):
    """A cost file as the project's own family table left it on disk (cmp1: every category 1.5 times the list price):
    every pinned valuation and aggregate multiplied, the usage untouched. A page that reads these shows 1.5 x."""
    doc = json.loads(json.dumps(doc))
    for row in doc["requests"]:
        row["valuation"]["subtotal_usd"] = str(float(row["valuation"]["subtotal_usd"]) * factor)
        row["valuation"]["rate_provenance"] = {"kind": "legacy_project_override"}
    for model in doc["by_model"].values():
        model["cost"] = round(model["cost"] * factor, 6)
        model["valuation"]["subtotal_usd"] = str(model["cost"])
    doc["orchestrator"]["cost"] = doc["by_model"][MODEL]["cost"]
    for entry in doc["by_task"].values():
        entry["cost"] = round(entry["cost"] * factor, 6)
    for key in ("priced_subtotal_usd", "total_cost_usd"):
        doc[key] = round(doc[key] * factor, 6)
    return doc


def files_for(slug, names=("s1", "s2", "s3", "s4", "s5", "s6")):
    return [B.carry(n, slug, tags=(TASK,)) for n in names]


def journal_for(files, charges=None):
    """One conductor or role row per file; `charges` maps a session to a CLI charge other than the file's own price."""
    charges = charges or {}
    rows = []
    for i, f in enumerate(files):
        sid = f["session_id"]
        total = charges.get(sid, float(f["priced_subtotal_usd"]))
        rows.append(B.jrow("conductor", sid, total, 3, ts="2026-09-30T05:0%d:00+00:00" % i) if i % 3 == 0 else
                    B.jrow("role", sid, total, 5 + i, "qa-runner", ts="2026-09-30T05:0%d:00+00:00" % i))
    return rows


def card_of(page, label):
    m = re.search(r"<div class='val'>([^<]*)</div><div class='lbl'>" + re.escape(label) + r"</div><div class='sub'>([^<]*)</div>", page)
    return (html.unescape(m.group(1)), html.unescape(m.group(2))) if m else None


def health_card(page, label="orchestrator share of the cost"):
    m = re.search(r"<div class='card'[^>]*><div class='val'>([^<]*)</div><div class='lbl'>" + re.escape(label) + r"</div><div class='sub'>([^<]*)</div>", page)
    return (html.unescape(m.group(1)), html.unescape(m.group(2))) if m else None


class Case(B.Case):
    pass


# --------------------------------------------------------------------------------- item 1: one price, every surface

class OnePriceEverywhereTests(Case):
    """Item 1 (Q5, R11): the price is computed ONCE per task in main() and read by every money surface."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        slug = B.slug_of(cls.tmp.name)
        cls.files = files_for(slug)
        # 4 sessions the two records agree on; 2 whose CLI charge is higher than the transcripts' (cmp1's missing tail)
        cls.charges = {"s5": 0.6, "s6": 0.6}
        cls.root = B.write_root(cls.tmp.name, cls.files, {TASK: journal_for(cls.files, cls.charges)},
                                estimates=[{"task": TASK, "ts": B.TODAY, "forecast": {"size_initial": "M"}}])
        cls.calls = []
        real = TP.task_price
        TP.task_price = lambda root, task, *a, **k: (cls.calls.append(task), real(root, task, *a, **k))[1]
        try:
            cls.page = B.render(cls.root)
            cls.task_page = B.render(cls.root, "--task", TASK)
        finally:
            TP.task_price = real
        cls.plain = html.unescape(cls.page)
        cls.answer = TP.task_price(cls.root, TASK)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_1a_the_price_function_is_asked_once_per_task_per_render(self):
        # two renders (the whole root and the task view) were made: TASK once in each, never once per surface
        self.assertEqual(self.calls.count(TASK), 2, self.calls)
        self.assertEqual(len(self.calls), len(set(self.calls)) * 2, self.calls)

    def test_1b_while_the_records_differ_every_surface_prints_the_same_range_and_no_single_figure(self):
        self.assertEqual(self.answer["status"], "differs")
        rng = D.pair_text(self.answer["price_low_usd"], self.answer["price_high_usd"])
        self.assertEqual(rng, "from $3.00 to $3.20")
        for page in (self.page, self.task_page):
            cost, _ = B.panel(page, "cost"), B.panel(page, "factory")
            self.assertEqual(B.by_task_rows(page)[TASK][1], rng)                                    # By task row
            self.assertEqual(B.total_row(page, "All stories and activities"), rng)                   # and its total
            self.assertEqual(card_of(page, TASK)[0], rng)                                            # the story card
            self.assertEqual(B.total_row(page, "The rows add up to the price (check)", B.section(page, "By agent")), rng)
            self.assertIn("<div class='val'>" + rng + "</div><div class='lbl'>factory spend", html.unescape(cost))  # the spend card
            self.assertIn(B.ARROW + " " + rng + "</td>", html.unescape(cost))                        # the estimates
            # never one of the two ends as the price: not in the story's row, the total row or a card
            for lone in ("$3.00", "$3.20"):
                self.assertNotEqual(B.by_task_rows(page)[TASK][1], lone)
                self.assertNotEqual(B.total_row(page, "All stories and activities"), lone)
                self.assertNotIn("<div class='val'>" + lone + "</div><div class='lbl'>" + TASK, cost)
                self.assertNotIn("<div class='val'>" + lone + "</div><div class='lbl'>factory spend", cost)
        self.assertEqual(card_of(self.page, TASK)[0], card_of(self.task_page, TASK)[0])             # the task view agrees

    def test_1c_the_finding_is_the_functions_own_words_on_the_card_and_under_by_task(self):
        finding = self.answer["finding"]
        self.assertIn("For 2 of 6 sessions the transcripts at catalogue rates and the CLI's own charge differ", finding)
        self.assertIn(finding, card_of(self.page, TASK)[1])
        self.assertIn(finding, html.unescape(B.section(self.page, "By task")))
        self.assertIn(finding, html.unescape(B.panel(self.page, "cost").split("Estimates at a glance")[1]))

    def test_1d_by_agent_has_two_columns_marks_the_rows_that_differ_and_the_rows_add_up_to_the_price(self):
        agent = B.section(self.page, "By agent")
        self.assertIn("<th>transcripts at catalogue rates</th><th>the CLI's charge</th><th>price</th>", agent)
        self.assertEqual(B.agent_cols(self.page, "conductor")[:2], ("$1.00", "$1.00"))     # s1 and s4: the records agree
        runner = B.agent_cols(self.page, "qa-runner")
        self.assertEqual(runner, ("$2.00", "$2.20", "from $2.00 to $2.20"))                 # s2, s3, s5, s6: s5 and s6 differ
        self.assertIn("differs: 2 sessions", agent)                                          # t-182 F7: the count-based plural
        self.assertNotIn("differs: 2 session(s)", agent)
        self.assertEqual(agent.count("differs: "), 1)                                        # only the row that holds them
        # the rows' price pairs sum to the story's pair: 1.00 + (2.00..2.20) = 3.00..3.20
        self.assertIn("The rows add up to the price.", agent)
        self.assertIn(TICK, agent)

    def test_1e_the_stated_equality_is_checked_at_cents_not_by_float_equality(self):
        def fake(amounts, total):
            rows = [{"agent": name, "sessions": 1, "a_usd": v, "a_price_usd": v, "b_usd": None, "price_low_usd": v,
                     "price_high_usd": v, "remote_usd": None, "b_unknown": 1, "a_unknown": 0, "differing_sessions": 0,
                     "remote_calls": 0} for name, v in amounts]
            return {TASK: {"status": "not_cross_checked", "sessions": [], "by_agent": rows, "price_low_usd": total,
                           "price_high_usd": total, "finding": "", "compared": "", "catalogue_revision": REVISION,
                           "rate_overrides": []}}
        doc = B.cost_file("d", [B.request("d", 0, "(no task)", 0.25, "a", B.SMALL)], "proj", activities={"a": {"type": "doctor"}})
        # 0.1 + 0.2 is 0.30000000000000004 in floats: equal to 0.3 at cents, so the page says the rows add up
        ok = D.tab_cost([doc], {}, None, {}, {}, None, None, fake([("a", 0.1), ("b", 0.2)], 0.3))
        self.assertEqual(0.1 + 0.2 == 0.3, False)
        self.assertIn("The rows add up to the price.", ok)
        self.assertIn("<td>The rows add up to the price (check)</td>", ok)
        # one cent apart: the defect is stated, never a caption under a wrong number
        bad = D.tab_cost([doc], {}, None, {}, {}, None, None, fake([("a", 0.1), ("b", 0.21)], 0.3))
        self.assertIn("The rows do NOT add up to the price", bad)
        self.assertNotIn("The rows add up to the price.", bad)
        self.assertIn("a defect of the factory's measurement", bad)

    def test_1f_by_task_says_what_its_check_row_is_when_the_price_holds_the_clis_charge(self):
        by_task = html.unescape(B.section(self.page, "By task"))
        self.assertIn("Sum of the sessions' transcripts (check; the total above also holds the CLI's charge and remote receipts)", by_task)
        self.assertEqual(B.total_row(self.page, html.escape("Sum of the sessions' transcripts (check; the total above also holds the "
                                                            "CLI's charge and remote receipts)")), "$3.00")

    def test_1g_the_status_words_agrees_not_cross_checked_and_incomplete_print_what_they_promise(self):
        files = files_for("proj", ("a1", "a2"))
        with tempfile.TemporaryDirectory() as td:
            driver, spread = B.read_driver(td, {TASK: journal_for(files)})
        agree = B.cost_page(files, driver, spread)
        rows = B.by_task_rows(agree)
        self.assertEqual(rows[TASK][:2], (2, "$1.00"))                                # agrees: ONE figure
        self.assertIn("the two records agree", rows[TASK][2])
        self.assertNotIn("from $", B.section(agree, "By task"))
        # t-182 F7: the price function's status is the word on whether the price is complete. The capture marks
        # these files provisional, but a transcripts figure that agrees with the CLI's own charge is complete, so the
        # cell says no more than "the two records agree" (it read "...; incomplete - 2 sessions provisional" beside a
        # retro that called the price complete) and no cost-capture finding claims a floor.
        self.assertEqual(rows[TASK][2], "the two records agree")
        self.assertNotIn("Factory finding - cost incomplete", html.unescape(agree).replace(chr(0x2014), "-"))
        # not_cross_checked: one figure, and the words
        silent = [B.jrow("role", f["session_id"], None, 3, "qa-runner") for f in files]
        with tempfile.TemporaryDirectory() as td:
            driver, spread = B.read_driver(td, {TASK: silent})
        page = B.cost_page(files, driver, spread)
        self.assertEqual(B.by_task_rows(page)[TASK][:2], (2, "$1.00"))
        self.assertIn("not cross-checked", B.by_task_rows(page)[TASK][2])
        # ... and where NO record cross-checked a provisional session, the capture's marker is the only word there is
        self.assertIn("incomplete " + chr(0x2014) + " 2 sessions provisional", B.by_task_rows(page)[TASK][2])
        self.assertIn(TASK + ": $1.00 (not cross-checked).", html.unescape(B.section(page, "By task")))
        # incomplete: what is known, and the reason in words
        partial = journal_for(files[:1]) + [B.jrow("role", "gone", None, 3, "qa-scout")]
        with tempfile.TemporaryDirectory() as td:
            driver, spread = B.read_driver(td, {TASK: partial})
        page = B.cost_page(files[:1], driver, spread)
        self.assertEqual(B.by_task_rows(page)[TASK][:2], (2, "$0.50"))
        self.assertIn("incomplete", B.by_task_rows(page)[TASK][2])
        note = html.unescape(B.section(page, "By task"))
        self.assertIn(TASK + ": $0.50 is what is known; the price is incomplete.", note)
        self.assertIn("1 session is in neither record (gone (qa-scout): no cost file for this session", note)

    def test_1h_the_story_card_and_the_spend_card_name_the_agent_forms_the_calls_were_counted_for(self):
        # B-407 D (F-11 a): a call of an agent whose form is in no row cannot be told from a shell command, so the
        # price says which forms it counted for; a forms problem follows the list; an old file (no list) prints nothing
        files = files_for("proj", ("a1", "a2"))
        files[0]["external_reconciliation"] = {"complete": False, "recognized_forms": ["testproject1", "acme"],
                                               "forms_problem": "cost.external_agent_forms is str, not a list"}
        with tempfile.TemporaryDirectory() as td:
            driver, spread = B.read_driver(td, {TASK: journal_for(files)})
        page = html.unescape(B.cost_page(files, driver, spread))
        line = "external calls counted for: testproject1, acme " + chr(0x2014) + " cost.external_agent_forms is str, not a list"
        self.assertIn(line, card_of(page, TASK)[1])                                    # the story card (the price's answer)
        self.assertIn(line, re.search(r"<div class='lbl'>factory spend[^<]*</div><div class='sub'>([^<]*)</div>", page).group(1))
        old = html.unescape(B.cost_page(files_for("proj", ("a1", "a2")), driver, spread))
        self.assertNotIn("external calls counted for", old)                              # a file with no list adds nothing

    def test_1i_a_forms_problem_makes_the_story_card_and_the_reconciliation_card_say_the_same_thing(self):
        # E-D3 / FR-10: where the external-agent forms had a problem the story card is not ONE figure that "agrees"
        # while the reconciliation card says it is not possible: both say the price is not complete
        files = files_for("proj", ("a1", "a2"))
        problem = "references/external-agent-calls.json is missing, unreadable or has no forms list; only the testproject1 floor is used"
        files[0]["external_reconciliation"] = {"complete": False, "recognized_forms": ["testproject1"], "forms_problem": problem}
        with tempfile.TemporaryDirectory() as td:
            driver, spread = B.read_driver(td, {TASK: journal_for(files)})
        page = html.unescape(B.cost_page(files, driver, spread))
        story = card_of(page, TASK)
        self.assertIn("incomplete", story[1])
        self.assertIn(problem, story[1])
        self.assertNotIn("the two records agree", story[1])
        self.assertEqual(card_of(page, "sum reconciliation")[0], "?")                      # the other card: not possible
        self.assertIn(TASK + ": $1.00 is what is known; the price is incomplete.", B.section(page, "By task"))


# --------------------------------------------------------------------------------- item 2: re-priced at read

class RepricedAtReadTests(Case):
    """Item 2 (Q5, R11 last bullet; E15/P8): main() loads every cost file through `revalue_document` ONCE."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        slug = B.slug_of(cls.tmp.name)
        cls.plain_files = files_for(slug)
        cls.pinned = [legacy_pinned(f) for f in cls.plain_files]
        # the project's own family table, 1.5 times the catalogue's in every category, as on cmp1
        family = {"claude-sonnet": {"input": 3, "output": 15, "cache_read": 0.3, "cache_write_5m": 3.75, "cache_write_1h": 6}}
        cls.root = B.write_root(cls.tmp.name, cls.pinned, {TASK: journal_for(cls.plain_files)},
                                config={"cost": {"model_prices": family}})
        cls.page = B.render(cls.root)
        cls.plain = html.unescape(cls.page)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_2a_no_section_shows_the_money_a_file_was_captured_with(self):
        # six files pinned at $0.75 each: $4.50 is the old page's figure, $3.00 the catalogue's (and the CLI's) for the same usage
        self.assertEqual(round(sum(f["priced_subtotal_usd"] for f in self.pinned), 2), 4.5)
        for pinned in ("$4.50", "$0.75", "$1.50</td><td class='warn'>"):
            self.assertNotIn(pinned, self.plain)
        self.assertEqual(B.by_task_rows(self.page)[TASK][:2], (6, "$3.00"))
        self.assertIn("<div class='val'>$3.00</div><div class='lbl'>factory spend", self.plain)
        self.assertEqual(card_of(self.page, TASK)[0], "$3.00")

    def test_2b_the_other_sections_of_the_cost_tab_show_catalogue_prices_too(self):
        # t-2141: this check failed once on CI (UTC, 05:36, a sibling branch with the same dashboard code green in the same
        # minute) and never locally, and the artifact kept no assertion text. It is clock-independent by construction (the fixture's
        # days are YESTERDAY, `By day` groups by the request's own date) and was green under 13 shifted clocks; each assertion now
        # carries the section it judged, so a red names the figure instead of "failures=1" (same checks, none weakened).
        cost = B.panel(self.page, "cost")
        by_model = html.unescape(B.section(self.page, "By model"))
        by_day = B.section(self.page, "By day")
        plain_cost = html.unescape(cost)
        self.assertIn("<td>" + MODEL + "</td>", by_model, by_model)
        self.assertIn("<td class='money'>$3.00</td>", by_model, by_model)
        self.assertIn("<td class='money'>$3.00</td>", by_day, by_day)
        spot = plain_cost.find("4.50")
        self.assertNotIn("4.50", plain_cost, plain_cost[max(0, spot - 200):spot + 80])

    def test_2c_the_page_names_the_catalogue_revision_once_and_says_old_figures_were_pinned_and_are_repriced(self):
        cost = html.unescape(B.panel(self.page, "cost"))
        self.assertEqual(cost.count("revision " + REVISION), 1)
        self.assertEqual(cost.count("pinned at the project's own price table"), 1)
        self.assertIn("they are re-priced here and never rewritten on disk", cost)

    def test_2d_a_project_rate_is_the_price_base_and_the_page_says_which_models_are_priced_at_it(self):
        with tempfile.TemporaryDirectory() as td:
            slug = B.slug_of(td)
            files = files_for(slug, ("o1", "o2"))
            root = B.write_root(td, files, {TASK: journal_for(files)},
                                config={"cost": {"rate_overrides": [{"model_id": MODEL, "rates": OVERRIDE_RATES}]}})
            page = B.render(root)
            answer = TP.task_price(root, TASK)
        plain = html.unescape(page)
        # the price is the override-priced figure ($2.00: twice the list price of two $0.50 files), the check still
        # compares the LIST price with the CLI's charge (they agree), and the page names the model priced at the project's rate
        self.assertEqual(answer["rate_overrides"], [MODEL])
        self.assertEqual(B.by_task_rows(page)[TASK][:2], (2, "$2.00"))
        self.assertIn("the two records agree", B.by_task_rows(page)[TASK][2])
        self.assertEqual(B.agent_cols(page, "conductor")[:2], ("$0.50", "$0.50"))            # list price vs the CLI's charge
        self.assertEqual(B.agent_cols(page, "conductor")[2], "$1.00")                         # the price: the project's rate
        self.assertIn("Priced at the project's own rate (the project's own price table): " + MODEL, plain)
        self.assertNotIn("rate_overrides", B.panel(page, "cost"))                              # t-182 F7: no field name on a page
        # t-182 F2: "the two records agree" never stands beside a figure that is not the one they agree on
        self.assertIn(TASK + ": $2.00 (the two records agree at the catalogue's list rates; the price is at the project's "
                      "own rates).", plain)

    def test_2e_a_file_that_cannot_be_repriced_is_no_priced_usage_the_page_says_so_and_the_render_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            slug = B.slug_of(td)
            good, bad = B.carry("good", slug, tags=(TASK,)), B.carry("bad", slug, tags=(TASK,))
            bad["requests"][0]["boom"] = True
            root = B.write_root(td, [good, bad], {TASK: journal_for([good, bad])})
            real = CC.revalue_document

            def picky(doc, cfg, catalogue):
                if any(isinstance(r, dict) and r.get("boom") for r in (doc.get("requests") or [])):
                    raise ValueError("a malformed cost file")
                return real(doc, cfg, catalogue)
            CC.revalue_document = picky
            try:
                page = B.render(root)
            finally:
                CC.revalue_document = real
        plain = html.unescape(page)
        self.assertIn("1 cost file could not be re-priced (bad) and is counted as having no priced usage.", plain)
        # the good file is priced; the bad one has no transcripts figure, only the CLI's charge, and is not $0.00
        self.assertEqual(B.by_task_rows(page)[TASK][:2], (2, "$1.00"))
        self.assertEqual(B.agent_cols(page, "conductor"), ("$0.50", "$0.50", "$0.50"))
        self.assertEqual(B.agent_cols(page, "qa-runner"), (DASH, "$0.50", "$0.50"))
        self.assertNotIn("$0.00", B.section(page, "By agent"))

    def test_2f_a_file_with_no_request_ledger_is_kept_as_captured_and_counted(self):
        with tempfile.TemporaryDirectory() as td:
            root = B.golden_fixture(td)
            page = html.unescape(B.render(root))
        self.assertIn("1 cost file holds no per-request ledger, so there is no usage to re-price from: their figures are "
                      "the ones pinned at capture.", page)


# --------------------------------------------------------------------------------- t-182: the true price

def by_agent_cells(page, label):
    """The money cells (transcripts, CLI charge, price) of the total row `label` of By agent, as printed."""
    m = re.search(r"<tr class='total'><td>" + re.escape(label) + r"</td>(.*?)</tr>", B.section(page, "By agent"), re.S)
    return tuple(html.unescape(c) for c in re.findall(r"<td class='money'>([^<]*)</td>", m.group(1))) if m else None


def every_agent(page):
    """{agent: (transcripts, CLI charge, price)} of every row of By agent, as printed."""
    return {html.unescape(m.group(1)): tuple(html.unescape(c) for c in re.findall(r"<td class='money'>([^<]*)</td>", m.group(2)))
            for m in re.finditer(r"<tr><td><b>([^<]*)</b></td>(.*?)</tr>", B.section(page, "By agent"), re.S)}


def cents_of(cell):
    return int(round(float(cell.replace("$", "").replace(",", "")) * 100)) if re.match(r"^\$[\d,.]+$", cell) else None


class TrueRatesTests(Case):
    """t-182 (P18, the critic's F1/F3/F6/F7): one rate base on the page, printed cents that add up, the tolerance of
    the check said once, and no field name in a person's text."""

    def render_override(self, rates=True, names=("o1", "o2")):
        with tempfile.TemporaryDirectory() as td:
            slug = B.slug_of(td)
            files = files_for(slug, names)
            config = {"cost": {"rate_overrides": [{"model_id": MODEL, "rates": OVERRIDE_RATES}]}} if rates else {}
            root = B.write_root(td, files, {TASK: journal_for(files)}, config=config)
            return html.unescape(B.render(root))

    def test_5a_the_health_cards_share_is_on_the_rate_base_of_the_price(self):
        # the price is $2.00 at the project's rates (twice the list price of two $0.50 sessions); the CLI charged the list
        # price ($0.50 each). The card read "$0.50 of $1.00" beside "$2.00": two rate bases on one page.
        page = self.render_override()
        self.assertEqual(B.by_task_rows(page)[TASK][:2], (2, "$2.00"))
        value, sub = health_card(page)
        self.assertEqual(value, "50%")
        self.assertIn("$1.00 of $2.00 priced", sub)
        self.assertIn("the driver's charges are put on the project's own rates, the same rates as the price", sub)
        self.assertNotIn("$0.50 of $1.00", sub)

    def test_5b_without_project_rates_the_health_card_is_what_it_was(self):
        page = self.render_override(rates=False)
        value, sub = health_card(page)
        self.assertEqual(value, "50%")
        self.assertIn("$0.50 of $1.00 priced", sub)
        self.assertNotIn("project's own rates", sub)

    def test_5c_the_printed_rows_of_by_agent_add_up_to_the_printed_total_at_the_cent(self):
        def fake(amounts, total):
            rows = [{"agent": name, "sessions": 1, "a_usd": v, "a_price_usd": v, "b_usd": v, "price_low_usd": v,
                     "price_high_usd": v, "remote_usd": None, "b_unknown": 0, "a_unknown": 0, "differing_sessions": 0,
                     "remote_calls": 0} for name, v in amounts]
            return {TASK: {"status": "agrees", "sessions": [], "by_agent": rows, "price_low_usd": total,
                           "price_high_usd": total, "finding": "", "compared": "", "catalogue_revision": REVISION,
                           "rate_overrides": [], "totals": {"a": total, "b": total}}}
        doc = B.cost_file("d", [B.request("d", 0, "(no task)", 0.25, "a", B.SMALL)], "proj", activities={"a": {"type": "doctor"}})
        third = 1.0 / 3
        page = html.unescape(D.tab_cost([doc], {}, None, {}, {}, None, None, fake([("a", third), ("b", third), ("c", third)], 1.0)))
        rows = every_agent(page)
        total = by_agent_cells(page, "Sum of orchestrator + agents")
        for column, label in ((0, "transcripts"), (1, "CLI charge"), (2, "price")):
            printed = [cents_of(c[column]) for c in rows.values() if cents_of(c[column]) is not None]
            self.assertEqual(sum(printed), cents_of(total[column]), (label, printed, total))
        cells = [rows[name] for name in ("a", "b", "c")]
        self.assertEqual(sorted(c[2] for c in cells), ["$0.33", "$0.33", "$0.34"])             # plain rounding printed 99 cents
        self.assertEqual(cells[0][2], "$0.34")                                                  # the tie goes to the first row

    def test_5d_a_range_is_rounded_end_by_end_each_end_adding_up_to_its_own_total(self):
        def fake():
            spec = [("a", 0.3345, 0.3345), ("b", 0.3345, 0.3345), ("c", 0.3345, 0.3345), ("d", 0.2, 0.403)]
            rows = [{"agent": n, "sessions": 1, "a_usd": lo, "a_price_usd": lo, "b_usd": hi, "price_low_usd": lo,
                     "price_high_usd": hi, "remote_usd": None, "b_unknown": 0, "a_unknown": 0,
                     "differing_sessions": 1 if lo != hi else 0, "remote_calls": 0} for n, lo, hi in spec]
            low, high = sum(s[1] for s in spec), sum(s[2] for s in spec)
            return {TASK: {"status": "differs", "sessions": [], "by_agent": rows, "price_low_usd": low, "price_high_usd": high,
                           "finding": "", "compared": "", "catalogue_revision": REVISION, "rate_overrides": [],
                           "totals": {"a": low, "b": high}}}
        doc = B.cost_file("d", [B.request("d", 0, "(no task)", 0.25, "a", B.SMALL)], "proj", activities={"a": {"type": "doctor"}})
        page = html.unescape(D.tab_cost([doc], {}, None, {}, {}, None, None, fake()))
        lows, highs = [], []
        for name in ("a", "b", "c", "d"):
            price = B.agent_cols(page, name)[2]
            ends = re.findall(r"\$[\d,.]+", price)
            lows.append(cents_of(ends[0]))
            highs.append(cents_of(ends[-1]))
        self.assertEqual((sum(lows), sum(highs)), (120, 141))            # 1.2035 and 1.4065 at the cent
        for name in ("a", "b", "c"):                                      # a row whose two ends are equal is one figure
            self.assertNotIn("from", B.agent_cols(page, name)[2])

    def test_6a_the_tolerance_of_the_check_is_stated_once_in_words_whatever_the_records_say(self):
        files = files_for("proj", ("a1", "a2"))
        for charges in (None, {"a2": 0.7}):                                   # records that agree exactly, and a gap
            with tempfile.TemporaryDirectory() as td:
                driver, spread = B.read_driver(td, {TASK: journal_for(files, charges)})
            page = html.unescape(B.cost_page(files, driver, spread))
            sentence = "a session agrees when they differ by no more than " + TP.tolerance_words() + "."
            self.assertEqual(page.count(sentence), 1, charges)
            self.assertIn(sentence, html.unescape(B.section(page, "By task")))
            self.assertNotIn("0.001", page.split("By task</h2>")[1].split("</section>")[0])   # words, not the constant

    def test_6b_the_sentence_follows_the_constant(self):
        files = files_for("proj", ("a1", "a2"))
        with tempfile.TemporaryDirectory() as td:
            driver, spread = B.read_driver(td, {TASK: journal_for(files)})
        saved = TP.TOLERANCE_USD
        TP.TOLERANCE_USD = TP.Decimal("0.005")
        try:
            page = html.unescape(B.cost_page(files, driver, spread))
        finally:
            TP.TOLERANCE_USD = saved
        self.assertIn("no more than half a cent.", page)

    def test_7a_the_project_table_is_named_in_words_not_by_its_field(self):
        cost = B.panel(self.render_override(), "cost")
        self.assertNotIn("rate_overrides", cost)
        self.assertIn("the project's own price table", cost)


# --------------------------------------------------------------------------------- item 3: conductor + code

def collapsed_root(td, rows, charges_files=None):
    slug = B.slug_of(td)
    sids = []
    for row in rows:
        if row.get("session_id") and row["session_id"] not in sids:
            sids.append(row["session_id"])
    files = [B.carry(s, slug, tags=(TASK,), cost=(charges_files or {}).get(s, 0.5)) for s in sids]
    return B.write_root(td, files, {TASK: rows})


class ConductorPlusCodeTests(Case):
    """Item 3 (P2, R9): the orchestrator is the conductor plus the driver's code; the ticket call is the scout's."""

    def test_3a_the_share_is_conductor_records_over_all_records_and_a_ticket_is_never_the_conductor(self):
        rows = [B.jrow("conductor", "c1", 2.0, 3), B.jrow("role", "r1", 6.0, 10, "qa-runner"),
                B.jrow("ticket", "t1", 2.0, 4, "jira-agent")]
        with tempfile.TemporaryDirectory() as td:
            driver, _spread = B.read_driver(td, {TASK: rows})
        charged = D.root_charged(driver)[0]
        split = D.orchestrator_split(D.dispatch_turns([], driver, charged))
        self.assertEqual((split["orch"], split["total"], split["percent"]), (2.0, 10.0, 20.0))    # not 40 %: the ticket is the scout's
        roles = {r["role"] for r in D.dispatch_turns([], driver, charged)}
        self.assertEqual(roles, {"conductor", "qa-runner", "qa-scout"})
        with tempfile.TemporaryDirectory() as td:
            root = collapsed_root(td, rows)
            page = html.unescape(B.render(root))
        self.assertEqual(health_card(page)[0], "20%")
        # the Cost tab's token share follows the same rule: one session in three is the conductor's (33 %, not the
        # 67 % that counting the ticket call as the orchestrator would give)
        self.assertEqual(card_of(page, "orchestrator token share")[0], "33%")

    def test_3b_with_a_driver_record_present_the_sub_text_says_what_the_orchestrator_is_and_who_priced_what(self):
        rows = [B.jrow("conductor", "c1", 2.0, 3), B.jrow("role", "r1", 6.0, 10, "qa-runner"),
                B.jrow("role", "u1", None, 2, "qa-scout")]
        with tempfile.TemporaryDirectory() as td:
            page = html.unescape(B.render(collapsed_root(td, rows)))
        value, sub = health_card(page)
        self.assertEqual(value, "25%")                                      # $2 of $8: the unknown pair is in neither sum
        self.assertIn("$2.00 of $8.00 priced", sub)
        self.assertIn("in a driver run the orchestrator is the conductor plus the driver's code, and that code spends no "
                      "model money", sub)
        self.assertIn("priced by the driver's record: 2 session(s), by the cost files: 0 session(s)", sub)
        self.assertIn("1 dispatch(es) of unknown cost left out of both sums", sub)
        # the tooltip of the card gains that one sentence
        self.assertIn("In a driver run the orchestrator is the conductor plus the driver's code: the code spends no "
                      "model money, so the share counts the conductor's sessions, and a ticket or data-fetching call is "
                      "the scout's spend, never the orchestrator's.", D.ORCHESTRATOR_TIP)

    def test_3c_with_every_session_bound_and_no_conductor_record_the_share_is_zero_and_says_so(self):
        rows = [B.jrow("role", "r1", 6.0, 10, "qa-runner"), B.jrow("role", "r2", 4.0, 8, "qa-scout")]
        with tempfile.TemporaryDirectory() as td:
            page = html.unescape(B.render(collapsed_root(td, rows)))
        value, sub = health_card(page)
        self.assertEqual(value, "0%")
        self.assertIn("no conductor record: the share is 0%", sub)

    def test_3d_with_no_bound_session_at_all_it_is_todays_share_from_the_capture(self):
        with tempfile.TemporaryDirectory() as td:
            slug = B.slug_of(td)
            root = B.write_root(td, B.golden_files(slug))          # no journal anywhere
            page = html.unescape(B.render(root))
        value, sub = health_card(page)
        self.assertEqual(value, "100%")                              # every request of the fixture is an orchestrator stream
        self.assertNotIn("conductor plus the driver's code", sub)
        self.assertRegex(sub, r"^\$[\d.,]+ of \$[\d.,]+ priced")

    def test_3e_a_session_the_journal_names_with_no_cost_file_is_a_record_of_the_share_too(self):
        rows = [B.jrow("conductor", "c1", 2.0, 3), B.jrow("role", "r1", 6.0, 10, "qa-runner")]
        with tempfile.TemporaryDirectory() as td:
            slug = B.slug_of(td)
            root = B.write_root(td, [B.carry("c1", slug, tags=(TASK,))], {TASK: rows})       # r1 has no cost file (E1)
            page = html.unescape(B.render(root))
        self.assertEqual(health_card(page)[0], "25%")                                          # $2 of $8, r1's record counted


# --------------------------------------------------------------------------------- item 4: the records

class DispatchRecordTests(Case):
    """Item 4 (P2, R8, R10): per-(session, dispatch) records from the journal; the marathon card and By agent's max read them."""

    def test_4a_a_record_is_a_pair_its_turns_are_summed_and_its_cost_is_the_sum_of_its_row_increments(self):
        # the rows of one resumed session interleave two dispatches: A 1.0, B 1.5, A 2.0 (cumulative): A cost 1.5, B 0.5
        rows = [dict(B.jrow("role", "x", 1.0, 4, "qa-runner"), dispatch="A"), dict(B.jrow("role", "x", 1.5, 6, "qa-runner"), dispatch="B"),
                dict(B.jrow("role", "x", 2.0, 2, "qa-runner"), dispatch="A")]
        with tempfile.TemporaryDirectory() as td:
            driver, _ = B.read_driver(td, {TASK: rows})
        records = {r["dispatch"]: r for r in D.journal_records(driver, D.root_charged(driver)[0])}
        self.assertEqual((records["A"]["turns"], records["A"]["cost"]), (6, 1.5))
        self.assertEqual((records["B"]["turns"], records["B"]["cost"]), (6, 0.5))
        self.assertEqual(round(sum(r["cost"] for r in records.values()), 9), 2.0)       # no cent created, none lost

    def test_4b_the_marathon_card_reads_the_journal_a_collapsed_cost_file_has_one_request_row_not_81_turns(self):
        rows = [dict(B.jrow("role", "m1", 1.0, 79, "qa-automator"), dispatch="S5-1", resumed=False),
                dict(B.jrow("role", "m1", 1.4, 1, "qa-automator"), dispatch="S5-1", resumed=True),
                dict(B.jrow("role", "m1", 1.8, 1, "qa-automator"), dispatch="S5-1", resumed=True),       # 79 + 1 + 1 = 81: over
                dict(B.jrow("role", "m2", 1.0, 79, "qa-automator"), dispatch="S5-2"),
                dict(B.jrow("role", "m2", 1.2, 1, "qa-automator"), dispatch="S5-2"),                      # 79 + 1 = 80: at the cap
                B.jrow("role", "m3", 0.5, 81, "qa-scout")]                                                # a single dispatch of 81
        with tempfile.TemporaryDirectory() as td:
            root = collapsed_root(td, rows)
            page = html.unescape(B.render(root))
            driver, _ = D.parse_driver_runs(root)
            files = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((root / "qa-factory" / "state" / "cost").glob("*.json"))]
        self.assertTrue(all(len(f["requests"]) == 1 for f in files))        # the collapsed shape: the old card counted 1 turn each
        turns = {r["session"]: r["turns"] for r in D.dispatch_turns(files, driver)}
        self.assertEqual(turns, {"m1": 81, "m2": 80, "m3": 81})
        value, sub = health_card(page, "marathon dispatches (>80 turns)")
        self.assertEqual(value, "2")                                          # 81 and 81; 80 is not over the cap
        self.assertIn("qa-automator (81 turns, $1.80)", sub)
        self.assertIn("qa-scout (81 turns, $0.50)", sub)
        self.assertNotIn("m2", sub)

    def test_4c_by_agents_max_reads_the_same_records(self):
        rows = [dict(B.jrow("role", "m1", 1.0, 79, "qa-automator"), dispatch="S5-1"),
                dict(B.jrow("role", "m1", 1.4, 3, "qa-automator"), dispatch="S5-1"),          # 82 in one dispatch
                dict(B.jrow("role", "m2", 1.0, 10, "qa-automator"), dispatch="S5-2")]
        with tempfile.TemporaryDirectory() as td:
            page = B.render(collapsed_root(td, rows))
        agent = B.section(page, "By agent")
        self.assertIn("<td><b>qa-automator</b></td><td>2</td><td class='warn' title=", agent)
        self.assertIn(">92 (max 82)</td>", agent)       # 92 turns over two dispatches; the longest single one is 82

    def test_4d_a_pair_with_unknown_cost_is_left_out_of_the_share_and_counted(self):
        rows = [B.jrow("conductor", "c1", 3.0, 2), dict(B.jrow("role", "r1", 4.0, 5, "qa-runner"), dispatch="D1"),
                dict(B.jrow("role", "r1", None, 5, "qa-runner"), dispatch="D2")]       # the second pair has no usable total
        with tempfile.TemporaryDirectory() as td:
            driver, _ = B.read_driver(td, {TASK: rows})
        charged = D.root_charged(driver)[0]
        records = D.dispatch_turns([], driver, charged)
        self.assertEqual(sorted((r["cost"] for r in records if r["role"] == "qa-runner"), key=lambda c: (c is None, c)), [4.0, None])
        split = D.orchestrator_split(records)
        self.assertEqual((split["orch"], split["total"], split["unknown"]), (3.0, 7.0, 1))


# --------------------------------------------------------------------------------- the edges

class EdgeTests(Case):
    def test_e_zero_records_is_no_price_and_the_sentence_never_a_dollar_figure(self):
        with tempfile.TemporaryDirectory() as td:
            root = B.write_root(td, [], estimates=[{"task": "T-7", "ts": B.TODAY, "forecast": {"size_initial": "M"}}])
            page = html.unescape(B.render(root, "--task", "T-7"))
        answer = TP.task_price(root if False else None, "T-7", sessions=[], driver=({}, {}))
        self.assertNotIn("price_low_usd", answer)
        self.assertIn("T-7: no session of this task has a record.", page)
        self.assertNotIn("$0.00", B.panel(page, "cost"))

    def test_e_a_per_call_journal_leaves_every_session_one_record_and_one_figure_not_cross_checked(self):
        # the driver3 shape: a session's total falls between rows, so every total is one call's cost
        files = [B.carry("p1", "proj", tags=(TASK,)), B.carry("p2", "proj", tags=(TASK,))]
        rows = [B.jrow("role", "p1", 0.78, 4, "qa-automator"), B.jrow("role", "p1", 9.51, 40, "qa-automator"),
                B.jrow("role", "p1", 0.19, 4, "qa-automator"),
                B.jrow("role", "p2", 0.2, 2, "qa-runner"), B.jrow("role", "p2", 0.5, 3, "qa-runner")]
        with tempfile.TemporaryDirectory() as td:
            driver, spread = B.read_driver(td, {TASK: rows})
        answer = B.answer_for(files, driver, spread)
        self.assertEqual({r["verdict"] for r in answer["sessions"]}, {"one_record"})
        page = B.cost_page(files, driver, spread)
        self.assertEqual(B.by_task_rows(page)[TASK][:2], (2, "$1.00"))
        self.assertIn("not cross-checked", B.by_task_rows(page)[TASK][2])
        for last_row in ("$0.19", "$0.78", "$9.51"):
            self.assertNotIn(last_row, html.unescape(page))

    def test_e_the_task_view_of_a_task_with_a_stray_session_has_one_range_on_the_card_and_in_the_rows(self):
        with tempfile.TemporaryDirectory() as td:
            slug = B.slug_of(td)
            files = files_for(slug, ("a1", "a2", "a3"))
            stray = B.cost_file("stray", [B.request("stray", 0, TASK, 0.5, "a", B.COLD)], slug,
                                activities={"a": {"type": "story", "task": TASK}})
            root = B.write_root(td, files + [stray], {TASK: journal_for(files, {"a3": 0.7})})
            page, task_page = B.render(root), B.render(root, "--task", TASK)
        for p in (page, task_page):
            rng = B.by_task_rows(p)[TASK][1]
            self.assertTrue(rng.startswith("from $"), rng)
            self.assertEqual(card_of(p, TASK)[0], rng)
            self.assertEqual(B.total_row(p, "The rows add up to the price (check)", B.section(p, "By agent")), rng)
            self.assertEqual(B.by_task_rows(p)[TASK][0], 4)                # a1, a2, a3 and the stray session

    def test_e_the_share_and_the_price_are_different_quantities_and_the_page_keeps_them_apart(self):
        rows = [B.jrow("conductor", "c1", 1.0, 3), B.jrow("role", "r1", 5.0, 10, "qa-runner")]
        with tempfile.TemporaryDirectory() as td:
            page = html.unescape(B.render(collapsed_root(td, rows, {"c1": 0.5, "r1": 0.5})))
        price = card_of(page, TASK)[0]
        share_value, share_sub = health_card(page)
        self.assertTrue(price.startswith("from $"), price)            # the records differ ($1.00 vs $0.50 ...): a range
        self.assertEqual(share_value, "17%")                           # $1 of $6: the driver's own records, a share of records
        self.assertIn("$1.00 of $6.00 priced", share_sub)
        self.assertNotIn("the price", share_sub)
        self.assertNotIn(price, share_sub)                             # the share's money is never presented as the price
        self.assertEqual(health_card(page, "orchestrator share of the cost") is not None, True)
        self.assertEqual(card_of(page, "orchestrator token share") is not None, True)   # the Cost tab names its own share (tokens)


# --------------------------------------------------------------------------------- a ripe deferred decision

class RipeDecisionTests(Case):
    """`main` used to append the ripe-decision sentence to a `banner` that did not exist yet: an UnboundLocalError on
    every render with a ripe deferred decision. The sentence is now built where the banner is."""

    def test_r_a_ripe_deferred_decision_renders_without_raising_and_the_banner_carries_the_sentence(self):
        backlog = ("## Deferred decisions (onboarding/gates)\n\n"
                   "| id | essence + where the marker is | asked | ripeness trigger | created | status | decision with witness "
                   "| field_refs | scope | owner | trigger_type | trigger_value | resolution_ref |\n"
                   "|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
                   "| DD-1 | A tracker integration was postponed | asked at gate A | date:2020-01-01 | 2020-01-01 | open | "
                   "| | DD | owner | date | 2020-01-01 | |\n")
        with tempfile.TemporaryDirectory() as td:
            root = B.write_root(td, [])
            (root / "qa-factory" / "factory-backlog.md").write_text(backlog, encoding="utf-8")
            page = html.unescape(B.render(root))
        banner = page.split("<div class='tabs'>")[0]
        self.assertIn("Ripe deferred factory decisions: 1 " + chr(0x2014) + " recorded decision triggers need attention", banner)
        self.assertIn("Deferred decisions ready for review: 1", banner)
        self.assertIn("DD-1", B.panel(page, "factory"))          # and the Factory tab lists it


# --------------------------------------------------------------------------------- stale cost files

class StaleCostFilesTests(Case):
    """A cost file the capture did NOT recompute shows the last capture's figure, which may be LOWER than the session
    cost (cmp1: 16 files stopped before their session ended). The Cost tab's alert lists every such file with the
    capture's own reason and the door that reason names, whatever the status is."""

    DOOR = "run `--recapture --session <id>`, which rebuilds the file and keeps those rows"

    def with_status(self, sid, status, reason):
        doc = B.carry(sid, "proj", tags=(TASK,))
        doc["recapture_status"] = {"status": status, "reason": reason, "checked_at": "2026-09-30T07:00:00+00:00"}
        return doc

    def test_s_a_cost_file_with_not_recomputed_status_is_in_the_alert_with_its_reason(self):
        page = html.unescape(D.tab_cost([self.with_status("gone1", "not_recomputed", "transcript file no longer present")], {}))
        alert = page.split("<h2>Stale cost files</h2>")[1].split("</section>")[0]
        self.assertIn("gone1: not recomputed (not recomputed) - transcript file no longer present".replace(" - ", " " + chr(0x2014) + " "), alert)
        self.assertIn("Its figure is the last capture and may be lower than what the session cost.", alert)

    def test_s_every_status_but_recomputed_is_listed_with_its_door_and_a_recomputed_one_is_not(self):
        files = [self.with_status("skip1", "skipped", "a checkpoint names a file that is gone: " + self.DOOR),
                 self.with_status("busy1", "busy", "another writer is capturing this session"),
                 self.with_status("done1", "recomputed", "rebuilt")]
        alert = html.unescape(D.tab_cost(files, {})).split("<h2>Stale cost files</h2>")[1].split("</section>")[0]
        self.assertIn("skip1: not recomputed (skipped)", alert)
        self.assertIn(self.DOOR, alert)                       # the door the reason names is printed as the capture wrote it
        self.assertIn("busy1: not recomputed (busy) " + chr(0x2014) + " another writer is capturing this session", alert)
        self.assertNotIn("done1", alert)
        self.assertNotIn("Stale cost files", html.unescape(D.tab_cost([self.with_status("done1", "recomputed", "rebuilt")], {})))

    def test_s_the_outcomes_of_this_renders_recapture_pass_are_kept_and_shown_not_thrown_away(self):
        results = [{"session_id": "live1", "status": "skipped", "reason": "transcript changed 12 s ago - still live",
                    "stale_reason": "transcript grew after this capture"},
                   {"session_id": "ok1", "status": "recomputed", "stale_reason": "old format"},
                   {"session_id": "out1", "status": "skipped", "reason": "parent directory - not recaptured"}]
        stale = D.stale_outcomes(results)
        self.assertEqual(sorted(stale), ["live1", "out1"])
        files = [B.carry("live1", "proj", tags=(TASK,)), B.carry("ok1", "proj", tags=(TASK,))]      # out1 is not in this tab
        alert = html.unescape(D.tab_cost(files, {}, None, {}, {}, None, None, None, None, None, stale)).split(
            "<h2>Stale cost files</h2>")[1].split("</section>")[0]
        self.assertIn("live1: not recomputed (skipped) " + chr(0x2014) + " transcript changed 12 s ago - still live (flagged because: "
                      "transcript grew after this capture)", alert)
        self.assertNotIn("ok1", alert)
        self.assertNotIn("out1", alert)

    def test_s_main_keeps_what_recapture_stale_returned_and_a_read_only_render_reads_the_files_own_status(self):
        with tempfile.TemporaryDirectory() as td:
            slug = B.slug_of(td)
            plain = B.carry("p1", slug, tags=(TASK,))
            flagged = self.with_status("f1", "not_recomputed", "transcript file no longer present")
            flagged["transcript"] = B.carry("f1", slug)["transcript"]
            root = B.write_root(td, [plain, flagged])
            read_only = html.unescape(B.render(root))
            self.assertIn("f1: not recomputed (not recomputed) " + chr(0x2014) + " transcript file no longer present", read_only)
            real = CC.recapture_stale
            CC.recapture_stale = lambda r, explicit=False: [
                {"session_id": "p1", "status": "skipped", "reason": "transcript changed 9 s ago - still live",
                 "stale_reason": "transcript grew after this capture"}]
            try:
                out = Path(td) / "live.html"
                import contextlib
                import io
                with contextlib.redirect_stdout(io.StringIO()):
                    D.main(["--root", str(root), "--out", str(out)])
            finally:
                CC.recapture_stale = real
            live = html.unescape(out.read_text(encoding="utf-8"))
        self.assertIn("p1: not recomputed (skipped) " + chr(0x2014) + " transcript changed 9 s ago - still live", live)


if __name__ == "__main__":
    unittest.main()
