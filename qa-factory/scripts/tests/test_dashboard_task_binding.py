"""A session the driver's journal names belongs WHOLE to that journal's task (B-196, piece P1), and what
the pages then say about its money (piece P2, Q5: the price is ONE answer, `task_price`).

Seen on the comparison run cmp1 of TP1-13797: every driver `claude -p` session opens no factory
activity, so the cost capture collapses its requests into one `carry:orchestrator` row tagged
"(no task)". By task, the cost finding, the hot-cache warning and the estimates floor then read
"Unclassified" for a story that cost $17. The driver's journal (artifacts/<task>/state/driver-runs.jsonl)
names the sessions it launched; that binding is computed once and read by every section that groups
by task. The money of a story is its price (`task_price`, asked once per task): the fixtures here are
priced at the catalogue's rates from their own usage, because main() re-prices every cost file at read.
"""
import contextlib
import copy
import hashlib
import html
import io
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import factory_dashboard as D
import cost_capture as CC
import task_price as TP
from dashboard_cost_groups import group

TASK = "TP1-13797"
ARROW = chr(0x2192)    # the estimates table's "forecast -> fact" arrow (no non-ASCII literal in a test)
DASH = chr(0x2014)     # the page's "no figure" dash
TOKEN0 = {"input": 0, "output": 0, "cache_read": 0, "cache_write_5m": 0, "cache_write_1h": 0}
# the shape of one cmp1 cost file's usage: 308k tokens, a cold cache (79.7 % hot)
COLD = {"input": 10, "output": 2115, "cache_read": 243793, "cache_write_5m": 0, "cache_write_1h": 62254}
SMALL = {"input": 100, "output": 10, "cache_read": 0, "cache_write_5m": 0, "cache_write_1h": 0}
MODEL = "claude-sonnet-5-5"
CATALOGUE = CC.load_catalogue()
OUTPUT_RATE, CACHE_READ_RATE = Decimal("0.00001"), Decimal("0.0000001")    # $10 and $0.10 per MTok of claude-sonnet-5-5 (cache read 0.05x of $2 input; CD1-7, was 0.2)


def usd_of(usage):
    """What the catalogue prices `usage` at, exactly (a Decimal)."""
    return Decimal(CC.value_usage(dict(TOKEN0, **usage), MODEL, {}, CATALOGUE)["subtotal_usd"])


def shaped(use, cost):
    """`use` (a cache shape) topped up with output and cache-read tokens until the catalogue prices it at
    exactly `cost`: a fixture's dollars are then the catalogue's own, whatever the shape, and the page can
    be checked against a round figure (the hot-cache share is unaffected: output is never served from cache)."""
    extra = Decimal(str(cost)) - usd_of(use)
    assert extra >= 0, (cost, use)
    output = int(extra / OUTPUT_RATE)
    remainder = extra - output * OUTPUT_RATE
    cache_read = remainder / CACHE_READ_RATE
    assert cache_read == int(cache_read), (cost, use)
    return dict(use, output=use["output"] + output, cache_read=use["cache_read"] + int(cache_read))


# Today, not a fixed date: the reporting window of the metrics is the last 30 days, so a fixed date
# would move the golden page one day at a time. (Every date on the page is masked in the comparison.)
TODAY = datetime.now(timezone.utc).date().isoformat()
# The cost files' own timestamps sit on YESTERDAY, never on today. The metrics window ends at the clock's
# NOW (metrics_projection.compute: `start <= ts <= now`), so a request stamped "today 10:00 UTC" was inside
# the window after 10:05 UTC and in the FUTURE, hence outside it, before: the golden page below was green
# when it was cut in the afternoon and red on the same code at 07:00 local (05:00 UTC) the next morning
# (t-291: sections 11, 13 and 20 differed, nothing in the dashboard had changed). A day in the past is
# inside the 30-day window at every hour of the day.
YESTERDAY = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
TS = YESTERDAY + "T10:00:00+00:00"


def request(sid, n, task, cost, activity, use, ts=TS, request_id=None):
    usage = dict(TOKEN0, requests=1, **shaped(use, cost))
    return {"request_key": f"anthropic:{sid}:{request_id or n}", "session_id": sid, "stream": "orchestrator",
            "model_id": MODEL, "request_id": request_id or f"r{n}", "timestamp": ts, "activity_id": activity,
            "task": task, "usage": usage, "valuation": CC.value_usage(usage, MODEL, {}, CATALOGUE)}


def tokens_of(*files):
    return sum(r["usage"][k] for f in files for r in f["requests"] for k in TOKEN0)


def cost_file(sid, reqs, slug, activities=None, by_task=None, factory=True, tags=None):
    """One cost file as the capture writes it, with a transcript folder that names `slug`."""
    total = {k: sum(r["usage"][k] for r in reqs) for k in TOKEN0}
    cost = round(sum(float(r["valuation"]["subtotal_usd"]) for r in reqs), 6)
    model = dict(total, requests=len(reqs), cost=cost, valuation={"pricing_coverage": "complete", "subtotal_usd": str(cost)})
    if activities is None:
        activities = {r["activity_id"]: {"type": "unclassified", "task": None} for r in reqs}
    tokens = sum(total.values())
    tags = list(tags) if tags is not None else sorted({r["task"] for r in reqs})
    return {"session_id": sid, "usage_completeness": "provisional", "usage_status": "provisional",
            "pricing_coverage": "complete", "tariff_confirmation": "unconfirmed", "requests": reqs,
            "external_calls": [], "by_model": {MODEL: model}, "orchestrator": {"by_model": {MODEL: model}, "cost": cost},
            "agents": [], "incomplete_agents": [], "by_activity": activities,
            "by_task": by_task or {t: {"tokens": tokens, "requests": len(reqs), "cost": cost, "machine_s": 10} for t in tags},
            "tasks": tags, "priced_subtotal_usd": cost, "total_cost_usd": cost, "has_factory_activity": factory,
            "transcript": f"C:\\Users\\dev3\\.claude\\projects\\{slug}\\{sid}.jsonl",
            "started": TS, "ended": YESTERDAY + "T10:05:00+00:00",
            "reconciliation": {"match": None}, "human_wait_s": 5, "interactions": 1, "tools": {}}


def carry(sid, slug, tags=("(no task)",), cost=0.5):
    """A cmp1 cost file: ONE collapsed `carry:orchestrator` row tagged "(no task)"; the tags of the
    file's by_task say what the session's markers named (cmp1: 20 files T only, 13 none, 2 both)."""
    reqs = [request(sid, 0, "(no task)", cost, "unclassified", COLD, request_id="carry:orchestrator:" + MODEL)]
    return cost_file(sid, reqs, slug, factory=False, tags=tags)


def write_root(td, files, journals=None, estimates=(), config=None):
    """A project root under `td`: cost files, one journal per task (a list of rows), a ledger."""
    root = Path(td).resolve() / "project"
    (root / "qa-factory" / "state" / "cost").mkdir(parents=True)
    (root / "qa-factory" / "config.json").write_text(json.dumps(config or {}), encoding="utf-8")
    for f in files:
        name = f.get("session_id") or "anonymous"
        (root / "qa-factory" / "state" / "cost" / (name + ".json")).write_text(json.dumps(f), encoding="utf-8")
    for task, rows in (journals or {}).items():
        state = root / "qa-factory" / "artifacts" / task / "state"
        state.mkdir(parents=True)
        (state / "driver-runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    if estimates:
        (root / "qa-factory" / "records").mkdir(parents=True, exist_ok=True)
        (root / "qa-factory" / "records" / "estimation-ledger.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in estimates), encoding="utf-8")
    return root


def slug_of(td):
    from cost_capture import project_slug
    return project_slug((Path(td).resolve() / "project"))


def render(root, *flags):
    """The page main() draws, read-only, into a file outside the root."""
    out = Path(root).parent / ("page-" + str(len(list(Path(root).parent.glob("page-*.html")))) + ".html")
    with contextlib.redirect_stdout(io.StringIO()):
        D.main(["--root", str(root), "--read-only", "--out", str(out), *flags])
    return out.read_text(encoding="utf-8")


def mask(page, root):
    """The page with what moves between two renders of the same project taken out: the clock, the
    package version, the temp directory the root lives in."""
    page = page.replace(str(root), "<ROOT>").replace(Path(root).as_posix(), "<ROOT>")
    page = re.sub(r"file:///[^\"'<>\s]*?/project/", "file:///<ROOT>/", page)
    # The platform's own spelling of a path (B-301 b: the golden page was cut on Windows and failed on
    # the Linux runner): a POSIX root already starts with a slash, so its file URL read `file://<ROOT>`
    # where Windows read `file:///<ROOT>`, and the evidence lists printed `<ROOT>\a\b` where POSIX
    # prints `<ROOT>/a/b`. One spelling, whichever platform rendered the page.
    page = re.sub(r"file://(?!/)<ROOT>", "file:///<ROOT>", page)
    page = re.sub(r"<ROOT>[^\"'<>\s]*", lambda m: m.group(0).replace("\\", "/"), page)
    page = re.sub(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:[+-]\d{2}:\d{2}|Z)?)?", "<TIME>", page)
    return re.sub(r"QA Factory \d+(?:\.\d+)*", "QA Factory <VERSION>", page)


def golden_files(slug):
    """The cost files of the no-journal root the golden page was rendered from: a story, doctor,
    unclassified, a legacy whole-session file, a file over two tasks, cold big sessions."""
    files = []
    story = [request("g-story", 0, "T-1", 1.25, "a-story", SMALL), request("g-story", 1, "T-1", 0.75, "a-story", COLD)]
    files.append(cost_file("g-story", story, slug, activities={"a-story": {"type": "story", "task": "T-1", "active_s": 60}}))
    files.append(cost_file("g-doctor", [request("g-doctor", 0, "(no task)", 0.25, "a-doc", SMALL)], slug,
                           activities={"a-doc": {"type": "doctor", "task": None}}))
    files.append(cost_file("g-loose", [request("g-loose", 0, "(no task)", 0.5, "unclassified", COLD)], slug))
    two = [request("g-two", 0, "T-1", 0.4, "a-1", SMALL), request("g-two", 1, "T-2", 0.6, "a-2", SMALL)]
    files.append(cost_file("g-two", two, slug, activities={"a-1": {"type": "story", "task": "T-1"},
                                                            "a-2": {"type": "story", "task": "T-2"}}))
    legacy = cost_file("g-legacy", [], slug, tags=["T-2", "(no task)"],
                       by_task={"T-2": {"tokens": 300, "requests": 3, "cost": 0.3, "machine_s": 20},
                                "(no task)": {"tokens": 100, "requests": 1, "cost": 0.1, "machine_s": 5}})
    del legacy["requests"]
    legacy["by_model"] = {"m": dict(SMALL, requests=4, cost=0.4, valuation={"pricing_coverage": "complete", "subtotal_usd": "0.4"})}
    # a legacy file's three records of its one $0.40 agree (the fixture once said $0.00 for two of them, so the
    # old golden page showed By agent $0.40 short of By task under a sentence saying the totals match)
    legacy.update(priced_subtotal_usd=0.4, total_cost_usd=0.4, orchestrator={"by_model": legacy["by_model"], "cost": 0.4})
    files.append(legacy)
    return files


def golden_fixture(td):
    return write_root(td, golden_files(slug_of(td)))


# ------------------------------------------------------------------------------------ helpers

class Case(unittest.TestCase):
    """assertIn / assertNotIn that name the needle and a bounded piece of the haystack: a whole page
    in a failure message is 80 kB of noise."""

    def assertIn(self, member, container, msg=None):
        if member not in container:
            self.fail(f"{member!r} not found in {type(container).__name__} of {len(container)}: ...{str(container)[:240]!r}")

    def assertNotIn(self, member, container, msg=None):
        if member in container:
            at = container.index(member)
            self.fail(f"{member!r} unexpectedly found: ...{container[max(at - 120, 0):at + 200]!r}")

def jrow(kind, sid, total, turns=1, role="", ts=None, **extra):
    """One row of the driver's journal as the driver writes it."""
    row = {"kind": kind, "role": role, "dispatch": ("S1-" + role + "-1") if kind == "role" else "",
           "stage": "S1", "session_id": sid, "num_turns": turns, "total_cost_usd": total}
    if ts:
        row["ts"] = ts
    row.update(extra)
    return row


def section(page, title):
    return page.split(title + "</h2>")[1].split("</section>")[0]


def panel(page, name):
    return page.split(f"id='{name}'>")[1].split("<div class='panel")[0]


def by_task_rows(page):
    """label -> (sessions, cost cell, completeness) of the By task table."""
    rows = {}
    pattern = (r"<tr><td>([^<]*)</td><td>(\d+)</td><td>[^<]*</td><td>[^<]*</td>"
               r"<td class='money'>([^<]*)</td><td class='[a-z]*'>([^<]*)</td></tr>")
    for m in re.finditer(pattern, section(page, "By task")):
        rows[html.unescape(m.group(1))] = (int(m.group(2)), html.unescape(m.group(3)), html.unescape(m.group(4)))
    return rows


def total_row(page, label, in_section=None):
    """The LAST money cell of the total row `label` (for the By task and By agent tables: the price)."""
    m = re.search(r"<tr class='total'><td>" + re.escape(label) + r"</td>(.*?)</tr>", in_section or page, re.S)
    cells = re.findall(r"<td class='money'>([^<]*)</td>", m.group(1)) if m else []
    return html.unescape(cells[-1]) if cells else None


def agent_cols(page, agent):
    """(transcripts, the CLI's charge, price) of one By agent row as printed, or None."""
    m = re.search(r"<td><b>" + re.escape(agent) + r"</b></td>(.*?)</tr>", section(page, "By agent"), re.S)
    return tuple(html.unescape(c) for c in re.findall(r"<td class='money'>([^<]*)</td>", m.group(1))) if m else None


def agent_money(page, agent):
    """The PRICE cell of one By agent row, or None when the agent has no row."""
    cols = agent_cols(page, agent)
    return cols[2] if cols else None


def cost_page(sessions, driver, spread=None, view=None, task_of=None, root=None, prices=None):
    return D.tab_cost(sessions, {}, root, driver, spread or {}, view, task_of, prices)


def read_driver(td, journals):
    """The driver journal reader's own answer for journals written under a temp root."""
    root = write_root(td, [], journals)
    return D.parse_driver_runs(root)


def answer_for(files, driver, spread=None, task=TASK, cfg=None, root=None):
    """The price answer the page must be reading: `task_price` on the same files and journal."""
    return TP.task_price(root, task, sessions=files, driver=(driver, spread or {}), cfg=cfg or {})


# The root of the comparison run cmp1, in miniature: four driver sessions whose cost files are ONE
# collapsed "(no task)" row each (their file tags differ: the story, both, none, none), a role whose
# journal total FALLS between two rows, a journaled session with no cost file at all, a delivery row.
A_JOURNAL = [
    jrow("conductor", "s-cond", 0.3, 5, ts="2026-09-30T03:58:24+00:00"),
    jrow("role", "s-scout", 0.4, 10, "qa-scout", ts="2026-09-30T03:49:37+00:00"),
    jrow("role", "s-scout", 0.45, 20, "qa-scout", ts="2026-09-30T03:56:25+00:00"),
    jrow("role", "s-auto", 1.0, 30, "qa-automator", ts="2026-09-30T04:01:00+00:00"),
    jrow("role", "s-auto", 1.5, 51, "qa-automator", ts="2026-09-30T04:09:00+00:00"),
    jrow("role", "s-runner", 0.5, 4, "qa-runner", ts="2026-09-30T04:10:00+00:00"),
    jrow("role", "s-runner", 0.2, 3, "qa-runner", ts="2026-09-30T04:11:00+00:00"),
    jrow("role", "s-ghost", 0.9, 7, "qa-critic", ts="2026-09-30T04:12:00+00:00"),
    {"ts": "2026-09-30T04:20:00+00:00", "kind": "delivery", "outcome": "nothing_outward"},
]


def a_files(slug):
    return [carry("s-cond", slug), carry("s-scout", slug, tags=(TASK,)),
            carry("s-auto", slug, tags=("(no task)", TASK)), carry("s-runner", slug)]


def a_root(td):
    return write_root(td, a_files(slug_of(td)), {TASK: A_JOURNAL},
                      estimates=[{"task": TASK, "ts": TODAY, "forecast": {"size_initial": "M"}}])


# What the price function makes of A_JOURNAL (each cost file is priced $0.50 at the catalogue's rates).
# A total that FALLS anywhere under the root proves the totals are per call, so a session with several rows
# has no known CLI charge (one record: the transcripts). Known CLI charges: s-cond $0.30 (one row; the
# file says $0.50: the two records DIFFER) and s-ghost $0.90 (one row, no cost file: its one record).
# Price = a range, per session on one rate base: s-cond 0.30 .. 0.50, three sessions at 0.50, s-ghost 0.90:
# from $2.70 to $2.90 over 5 sessions.
#
# RUNNING_JOURNAL: the same sessions with s-runner rising (0.2 -> 0.5): no total falls, every total is a
# running total. The CLI's charges: cond 0.30, scout 0.45, auto 1.50, runner 0.50, ghost 0.90.
RUNNING_JOURNAL = [jrow("role", "s-runner", 0.2, 4, "qa-runner", ts="2026-09-30T04:10:00+00:00") if r.get("session_id") == "s-runner"
                   and r["total_cost_usd"] == 0.5 else
                   jrow("role", "s-runner", 0.5, 3, "qa-runner", ts="2026-09-30T04:11:00+00:00") if r.get("session_id") == "s-runner"
                   else r for r in A_JOURNAL]


def running_root(td, extra_files=()):
    slug = slug_of(td)
    return write_root(td, a_files(slug) + list(extra_files), {TASK: RUNNING_JOURNAL},
                      estimates=[{"task": TASK, "ts": TODAY, "forecast": {"size_initial": "M"}}])


BINDING = {sid: TASK for sid in ("s-cond", "s-scout", "s-auto", "s-runner", "s-ghost")}


def agreeing_journal(files, task_rows=()):
    """One journal row per cost file whose CLI charge is exactly what the catalogue prices the file at."""
    return [jrow("role", f["session_id"], float(f["priced_subtotal_usd"]), 4, "qa-runner", ts="2026-09-30T05:00:00+00:00")
            for f in files] + list(task_rows)


# ------------------------------------------------------------------------------------ group()

class GroupBindingTests(Case):
    def test_no_binding_is_todays_grouping_for_none_and_empty_and_a_binding_of_nobody(self):
        mixed = golden_files("p")
        no_ids = [dict(copy.deepcopy(s), session_id=None) for s in mixed]
        for s in no_ids:
            s.pop("session_id")
        base = group(mixed)
        self.assertEqual(base, group(mixed, task_of=None))
        self.assertEqual(base, group(mixed, task_of={}))
        self.assertEqual(base, group(mixed, {"nobody": "ZZ-1"}))
        # the stand-in id of a file that carries none is never a key the journal can bind
        self.assertEqual(group(no_ids), group(no_ids, {"legacy-0": "ZZ-1", "legacy-1": "ZZ-1"}))
        self.assertEqual(group([], {"x": TASK}), ({}, {}))
        self.assertIn("Unclassified", base[0])   # the control: the mixed fixture does carry it

    def test_a_bound_session_is_whole_under_its_task_and_counted_under_exactly_one_label(self):
        files = [carry("s1", "p"), carry("s2", "p", tags=(TASK,)), carry("s3", "p", tags=("(no task)", TASK))]
        control, _ = group(files)
        self.assertEqual(list(control), ["Unclassified"])          # the defect: 3 sessions, none named
        tasks, _days = group(files, {"s1": TASK, "s2": TASK, "s3": TASK})
        self.assertEqual(list(tasks), [TASK])
        self.assertEqual(tasks[TASK]["sessions"], 3)
        self.assertEqual(tasks[TASK]["tokens"], tokens_of(*files))
        for sid in ("s1", "s2", "s3"):
            self.assertEqual([label for label, v in tasks.items() if sid in v["session_ids"]], [TASK])

    def test_binding_moves_money_between_labels_and_never_changes_it(self):
        files = golden_files("p") + [carry("s1", "p"), carry("s2", "p", tags=(TASK,))]
        binding = {"s1": TASK, "s2": TASK, "g-loose": "T-1", "g-doctor": "T-2", "g-legacy": "T-1"}
        before, days_before = group(files)
        after, days_after = group(files, binding)
        self.assertNotEqual(sorted(before), sorted(after))
        for key in ("cost", "tokens", "unpriced_tokens"):
            self.assertAlmostEqual(sum(v[key] for v in before.values()), sum(v[key] for v in after.values()), places=6)
        self.assertEqual(days_before, days_after)

    def test_position_invariant_no_other_label_gets_a_piece_of_a_bound_session(self):
        # one session, three rows that today reach three different labels (a doctor activity, a story
        # of ANOTHER task, an unclassified turn): bound, all of it is the journal's task's.
        rows = [request("m", 0, "(no task)", 0.1, "a-doc", SMALL), request("m", 1, "T-2", 0.2, "a-story", SMALL),
                request("m", 2, "(no task)", 0.3, "a-none", SMALL)]
        mixed = cost_file("m", rows, "p", activities={"a-doc": {"type": "doctor"}, "a-story": {"type": "story", "task": "T-2"},
                                                     "a-none": {"type": "unclassified"}})
        self.assertEqual(sorted(group([mixed])[0]), ["Doctor", "T-2", "Unclassified"])
        tasks, _ = group([mixed, carry("free", "p")], {"m": TASK})
        self.assertEqual(sorted(tasks), [TASK, "Unclassified"])
        self.assertEqual(tasks[TASK]["session_ids"], {"m"})
        self.assertAlmostEqual(tasks[TASK]["cost"], 0.6)
        self.assertEqual(tasks["Unclassified"]["session_ids"], {"free"})    # the unbound one: today's path

    def test_a_legacy_whole_session_bound_is_one_label_with_its_composition_once(self):
        legacy = [s for s in golden_files("p") if s["session_id"] == "g-legacy"][0]
        loose, _ = group([legacy])
        self.assertFalse(loose["T-2"]["composition_complete"])         # today: split over two tasks
        tasks, _ = group([legacy], {"g-legacy": TASK})
        self.assertEqual(list(tasks), [TASK])
        self.assertEqual(tasks[TASK]["tokens"], 400)
        self.assertTrue(tasks[TASK]["composition_complete"])
        self.assertEqual(tasks[TASK]["composition"]["input"], 100)     # the session's own, added once

    def test_a_session_the_journal_does_not_name_is_apart_in_the_default_view_and_labelled_as_before_elsewhere(self):
        story = lambda sid, task, use=COLD: cost_file(sid, [request(sid, 0, task, 0.5, "a", use)], "p",
                                                     activities={"a": {"type": "story", "task": task}})
        files = [carry("bound", "p"), story("stray", TASK), story("other", "T-9"), carry("loose", "p"),
                 cost_file("doc", [request("doc", 0, "(no task)", 0.1, "a", SMALL)], "p", activities={"a": {"type": "doctor"}})]
        tasks, _ = group(files, {"bound": TASK})
        self.assertEqual(sorted(tasks), sorted([TASK, TASK + " - not launched by the driver", "T-9", "Unclassified", "Doctor"]))
        self.assertEqual(tasks[TASK]["session_ids"], {"bound"})
        self.assertEqual(tasks[TASK + " - not launched by the driver"]["session_ids"], {"stray"})
        # the per-task view keeps the tag (E2), and E3 is today's labelling
        view, _ = group(files, {"bound": TASK}, stray_apart=False)
        self.assertEqual(view[TASK]["session_ids"], {"bound", "stray"})
        self.assertNotIn(TASK + " - not launched by the driver", view)
        # a legacy session tagged to the journaled task is apart too
        legacy = cost_file("old", [], "p", tags=[TASK], by_task={TASK: {"tokens": 5, "cost": 0.1}})
        del legacy["requests"]
        self.assertIn(TASK + " - not launched by the driver", group([legacy], {"bound": TASK})[0])

    def test_a_session_id_that_is_not_a_string_is_never_bound(self):
        numeric = carry("5", "p")
        numeric["session_id"] = 5
        numeric["requests"][0]["session_id"] = 5
        self.assertEqual(list(group([numeric], {"5": TASK})[0]), ["Unclassified"])


# ------------------------------------------------------------------------------------ tab_cost()

class TabCostBindingTests(Case):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.files = a_files("proj")
        cls.driver, cls.spread = read_driver(cls.tmp.name, {TASK: A_JOURNAL})
        cls.binding = D.task_binding(cls.driver)
        cls.page = cost_page(cls.files, cls.driver, cls.spread, task_of=cls.binding)
        cls.plain = html.unescape(cls.page)
        cls.answer = answer_for(cls.files, cls.driver, cls.spread)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_binding_is_the_journals_sessions_and_nothing_else(self):
        self.assertEqual(self.binding, BINDING)
        self.assertEqual(D.task_binding({}), {})
        self.assertEqual(D.task_binding(None), {})

    def test_the_price_answer_of_the_fixture_is_what_the_comments_say(self):
        # the control of every number below: 3 x $0.50 (one record), s-cond $0.30 against $0.50, s-ghost $0.90
        self.assertEqual(self.answer["status"], "differs")
        self.assertEqual((round(self.answer["price_low_usd"], 2), round(self.answer["price_high_usd"], 2)), (2.70, 2.90))
        self.assertEqual(len(self.answer["sessions"]), 5)

    def test_by_task_names_the_story_and_no_unclassified_row(self):
        rows = by_task_rows(self.page)
        self.assertEqual(list(rows), [TASK])
        self.assertEqual(rows[TASK][:2], (5, "from $2.70 to $2.90"))      # 4 cost files + the session with none
        self.assertNotIn("<td>Unclassified</td>", section(self.page, "By task"))
        self.assertNotIn("driver sessions", self.page)

    def test_the_money_of_by_task_the_check_row_and_by_agent_is_the_same_with_and_without_the_binding(self):
        # R4: the binding moves money between labels and never changes it. With a journal that records no
        # CLI charge the price is the transcripts' own, so the same four files read the same with and without it.
        silent = [jrow("role", s, None, 3, "qa-runner") for s in ("s-cond", "s-scout", "s-auto", "s-runner")]
        with tempfile.TemporaryDirectory() as td:
            driver, spread = read_driver(td, {TASK: silent})
        bound = cost_page(self.files, driver, spread, task_of=D.task_binding(driver))
        without = cost_page(self.files, {}, {}, task_of={})
        self.assertEqual(list(by_task_rows(without)), ["Unclassified"])
        self.assertEqual(list(by_task_rows(bound)), [TASK])
        for label in ("All stories and activities", "Sum of sessions (check)"):
            self.assertEqual(total_row(bound, label), total_row(without, label), label)
        self.assertEqual(total_row(bound, "All stories and activities"), "$2.00")
        self.assertEqual(total_row(bound, "Sum of orchestrator + agents", section(bound, "By agent")),
                         total_row(without, "Sum of orchestrator + agents", section(without, "By agent")))

    def test_the_default_binding_is_read_from_the_journal_when_a_caller_gives_none(self):
        self.assertEqual(cost_page(self.files, self.driver, self.spread), self.page)

    def test_the_note_names_the_binding_in_plain_words_and_the_page_shows_no_field_names(self):
        note = html.unescape(section(self.page, "By task"))
        self.assertIn("counted whole under the task whose journal names it, whatever task its cost file tags", note)
        self.assertIn("more than one task's journal names is counted under the task whose journal names it first", note)
        for word in ("task_of", "session_id", "total_cost_usd", "driver-runs", "binding", "total_falls", "WHY_"):
            self.assertNotIn(word, note)
        # (6b) the note about the "not launched by the driver" label is printed only when such a row exists
        self.assertNotIn("not launched by the driver", note)
        self.assertNotIn("not launched by the driver", html.unescape(section(self.page, "By agent")))
        # a session a cost file TAGS to the task (no story activity of it) that the journal does not name
        stray = cost_file("stray", [request("stray", 0, TASK, 0.5, "a", COLD)], "proj", activities={"a": {"type": "unclassified"}})
        page = cost_page(self.files + [stray], self.driver, self.spread, task_of=self.binding)
        self.assertIn("listed apart as '<task> - not launched by the driver'", html.unescape(section(page, "By task")))
        self.assertEqual(by_task_rows(page)[TASK + " - not launched by the driver"][:2], (1, "$0.50"))

    def test_the_story_is_a_range_with_the_functions_finding_and_the_rows_say_what_was_compared(self):
        note = html.unescape(section(self.page, "By task"))
        self.assertIn(self.answer["finding"], note)
        self.assertIn("Compared: " + self.answer["compared"], note)
        self.assertIn(TASK + ": from $2.70 to $2.90 (the two records differ).", note)
        # the completeness cell says it in words and the price is never one figure while the records differ
        self.assertIn("the two records differ", by_task_rows(self.page)[TASK][2])
        self.assertNotIn("<td class='money'>$2.90</td>", section(self.page, "By task"))
        self.assertNotIn("<td class='money'>$2.70</td>", section(self.page, "By task"))

    def test_the_story_card_prints_the_range_and_the_finding(self):
        card = re.search(r"<div class='val'>([^<]*)</div><div class='lbl'>" + TASK + r"</div><div class='sub'>([^<]*)</div>",
                         self.page)
        self.assertEqual(card.group(1), "from $2.70 to $2.90")
        self.assertIn("5 sessions", card.group(2))
        self.assertIn(self.answer["finding"], html.unescape(card.group(2)))
        self.assertEqual(self.plain.count("<div class='val'>$2.70</div>"), 0)

    def test_a_falling_total_is_no_cli_charge_and_the_row_keeps_the_transcripts_figure(self):
        # s-runner falls (0.5 -> 0.2): its CLI charge is unknown, it is one record (the transcripts), never the last row's $0.20
        self.assertEqual(agent_cols(self.page, "qa-runner"), ("$0.50", DASH, "$0.50"))
        # scout and automator rise, but under a per-call root they are not running totals either
        self.assertEqual(agent_cols(self.page, "qa-scout"), ("$0.50", DASH, "$0.50"))
        self.assertEqual(agent_cols(self.page, "qa-automator"), ("$0.50", DASH, "$0.50"))
        # one row: its value stands, and it differs from the file's
        self.assertEqual(agent_cols(self.page, "conductor"), ("$0.50", "$0.30", "from $0.30 to $0.50"))
        self.assertIn("The CLI's own charge is unknown for 3 sessions", html.unescape(section(self.page, "By task")))

    def test_a_session_the_journal_names_with_no_cost_file_is_priced_by_its_one_record_never_a_zero(self):
        # s-ghost: the journal's $0.90 is its only record; it has its own By agent row and is not in any $0.00
        cols = agent_cols(self.page, "qa-critic")
        self.assertEqual(cols, (DASH, "$0.90", "$0.90"))        # no transcripts (no cost file), the CLI's charge, the price
        self.assertIn("their price is the CLI's charge alone", html.unescape(section(self.page, "By task")))
        self.assertNotIn("$0.00", section(self.page, "By agent"))

    def test_a_session_named_by_two_journals_is_counted_under_one_and_every_section_says_so(self):
        driver = {"dup": {"task": "T-2", "rows": [jrow("role", "dup", 0.4, 3, "qa-scout")], "journals": ["T-1", "T-2"],
                          "no_timestamps": False, "multi_journal": True}}
        page = cost_page([carry("dup", "p")], driver, {"dup": 2})
        self.assertIn("session dup is named by 2 task journals; counted under T-2", html.unescape(section(page, "By task")))
        self.assertIn("session dup appears under 2 tasks; counted under T-2", html.unescape(section(page, "By agent")))
        self.assertEqual(list(by_task_rows(page)), ["T-2"])
        self.assertIn("not cross-checked", by_task_rows(page)["T-2"][2])     # several journals: no CLI charge, one record
        driver["dup"].update(task="T-1", no_timestamps=True)
        page = cost_page([carry("dup", "p")], driver, {"dup": 2})
        self.assertIn("session dup is named by 2 task journals; counted under T-1 (no timestamps", html.unescape(section(page, "By task")))

    def test_the_task_view_counts_a_stray_session_with_the_stories_evidence_in_the_story_and_the_rows_agree(self):
        # one call, one answer: a session whose story activity names the task is the task's (task_price R5b); the card,
        # By task and By agent all say the same range, in the default view and in the task view
        stray = cost_file("stray", [request("stray", 0, TASK, 0.5, "a", COLD)], "proj", activities={"a": {"type": "story", "task": TASK}})
        files = self.files + [stray]
        ans = answer_for(files, self.driver, self.spread)
        self.assertEqual(len(ans["sessions"]), 6)
        shown = D.pair_text(ans["price_low_usd"], ans["price_high_usd"])
        view = D.select_task_sessions(files, [TASK], self.driver, self.binding)
        view["tasks"] = [TASK]
        for page in (cost_page(files, self.driver, self.spread, task_of=self.binding),
                     cost_page(view["whole"], self.driver, self.spread, view, self.binding)):
            self.assertEqual(by_task_rows(page)[TASK][:2], (6, shown))
            self.assertIn("<div class='val'>" + shown + "</div><div class='lbl'>" + TASK, page)
            self.assertEqual(total_row(page, "The rows add up to the price (check)", section(page, "By agent")), shown)
            self.assertNotIn("not launched by the driver", section(page, "By task").replace(
                "listed apart as '&lt;task&gt; - not launched by the driver'", ""))

    def test_no_sessions_no_journal_and_an_empty_journal_are_todays_output(self):
        today = D.tab_cost([], {}, None, {}, {})
        self.assertEqual(D.tab_cost(self.files, {}, None, {}, {}), cost_page(self.files, {}, {}, task_of={}))
        self.assertNotIn("journal names", D.tab_cost(self.files, {}, None, {}, {}))
        self.assertEqual(D.journal_binding_note({}, {}, {}, None), "")
        self.assertEqual(cost_page([], {}, {}, task_of={}), today)     # no journal: nothing added
        self.assertNotIn("Two records of the same money", D.tab_cost(self.files, {}, None, {}, {}))   # no answer, no columns note

    def test_6d_a_view_with_no_cost_files_says_so_before_it_returns_early(self):
        # E1: the journal names 5 sessions and no cost file is in this view or the root: said, not silent. The one
        # record of a session with no cost file is the CLI's charge; a session with none is in neither record.
        page = html.unescape(cost_page([], self.driver, self.spread, task_of=self.binding))
        self.assertIn("state/cost/ is empty", page)
        ans = answer_for([], self.driver, self.spread)
        self.assertEqual(ans["status"], "incomplete")
        self.assertIn(TASK + ": " + D.pair_text(ans["price_low_usd"], ans["price_high_usd"]) + " is what is known", page)
        self.assertIn(ans["finding"], page)
        self.assertNotIn("$0.00", page)
        # a view whose only cost files are another project's: the same statement in the parent-directory section
        with tempfile.TemporaryDirectory() as td:
            root = write_root(td, [])
            foreign = carry("elsewhere", "p")
            del foreign["transcript"]          # no project folder and no factory activity: not this project's (Codex rule)
            page = html.unescape(cost_page([foreign], self.driver, self.spread, task_of=self.binding, root=root))
        self.assertIn("Sessions of parent directories", page)
        self.assertIn(answer_for([], self.driver, self.spread, root=root)["finding"], page)


# ------------------------------------------------------------------------------------ the status words

PER_CALL = [jrow("role", "s1", 0.78, 4, "qa-automator", ts="2026-09-30T05:00:00+00:00"),
            jrow("role", "s1", 9.51, 40, "qa-automator", ts="2026-09-30T05:10:00+00:00"),
            jrow("role", "s1", 3.39, 30, "qa-automator", ts="2026-09-30T05:20:00+00:00"),
            jrow("role", "s2", 0.2, 2, "qa-runner", ts="2026-09-30T05:30:00+00:00"),
            jrow("role", "s2", 0.5, 3, "qa-runner", ts="2026-09-30T05:40:00+00:00")]


class RootRuleTests(Case):
    """Item 1: every session of a render is priced by ONE answer, never per session on its own."""

    def test_1_a_per_call_root_prices_no_session_by_its_last_rows_and_says_why(self):
        with tempfile.TemporaryDirectory() as td:
            driver, spread = read_driver(td, {TASK: PER_CALL})
        charged, unknown = D.root_charged(driver)
        self.assertEqual(charged, {"s1": None, "s2": None})      # s1 falls, s2 rises under a root where totals are per call
        self.assertEqual(unknown, [("s1", D.WHY_FALLS), ("s2", D.WHY_PER_CALL_ROOT)])
        files = [carry("s1", "p"), carry("s2", "p")]
        page = cost_page(files, driver, spread, task_of=D.task_binding(driver))
        ans = answer_for(files, driver, spread)
        self.assertEqual(ans["status"], "not_cross_checked")
        # the old page: "driver's record ... $0.50 for 1 session(s)" and a By agent total built from the last rows
        for gone in ("$12.50", "$0.78", "$3.39", "authoritative", "driver record $"):
            self.assertNotIn(gone, html.unescape(page))
        self.assertEqual(by_task_rows(page)[TASK][:2], (2, "$1.00"))
        self.assertIn("not cross-checked", by_task_rows(page)[TASK][2])
        self.assertEqual(agent_cols(page, "qa-automator"), ("$0.50", DASH, "$0.50"))
        self.assertEqual(agent_cols(page, "qa-runner"), ("$0.50", DASH, "$0.50"))
        self.assertEqual(total_row(page, "All stories and activities"), "$1.00")
        self.assertEqual(total_row(page, "Sum of sessions (check)"), "$1.00")
        self.assertEqual(total_row(page, "The rows add up to the price (check)", section(page, "By agent")), "$1.00")

    def test_1_a_session_in_two_journals_has_no_cli_charge_and_the_page_does_not_print_one_journals_total(self):
        with tempfile.TemporaryDirectory() as td:
            driver, spread = read_driver(td, {
                "T-1": [jrow("role", "dup", 1.0, 3, "qa-scout", ts="2026-09-01T00:00:00+00:00")],
                "T-2": [jrow("role", "dup", 3.0, 3, "qa-scout", ts="2026-09-02T00:00:00+00:00")]})
        self.assertEqual(D.root_charged(driver), ({"dup": None}, [("dup", D.WHY_SEVERAL_JOURNALS)]))
        page = cost_page([carry("dup", "p")], driver, spread, task_of=D.task_binding(driver))
        text = html.unescape(section(page, "By task") + section(page, "By agent"))
        self.assertNotIn("$1.00", text)
        self.assertNotIn("$3.00", text)
        self.assertEqual(agent_cols(page, "qa-scout"), ("$0.50", DASH, "$0.50"))
        # (6c) the By agent line for that session is printed once, not twice in one sentence
        agent = html.unescape(section(page, "By agent"))
        self.assertEqual(agent.count("session dup"), 1)       # the session is named once, not twice in one clause
        self.assertIn("session dup appears under 2 tasks; counted under T-1.", agent)
        self.assertNotIn("is named by", agent)

    def test_1_main_asks_the_journal_once_per_render(self):
        calls, original = [], D.root_charged
        D.root_charged = lambda by_session: (calls.append(len(by_session)), original(by_session))[1]
        try:
            with tempfile.TemporaryDirectory() as td:
                render(a_root(td))
        finally:
            D.root_charged = original
        self.assertEqual(calls, [5])      # once, for the 5 sessions of A_JOURNAL (the health card and the banner read the same answer)

    def test_edge_nothing_in_the_journal_and_nothing_to_divide_is_stated_without_a_figure_or_a_division(self):
        self.assertEqual(D.root_charged({}), ({}, []))
        rows, info = D.agent_table([], [], {}, {}, [], {}, {})
        self.assertEqual((rows, info["driver"], info["b_unknown"]), ({}, 0, 0))
        note = D.by_agent_note([], info, {}, {})
        self.assertIn("no driver-runs journal under this root", note)
        self.assertNotIn("$", note)
        files = a_files("proj")
        self.assertEqual(D.tab_cost(files, {}, None, {}, {}, None, None, {}), D.tab_cost(files, {}, None, {}, {}))
        self.assertEqual(D.tab_cost([], {}, None, {}, {}, None, None, {}), D.tab_cost([], {}, None, {}, {}))

    def test_edge_a_session_with_no_usable_total_and_one_in_two_journals_are_one_record_each_and_never_a_zero(self):
        with tempfile.TemporaryDirectory() as td:
            driver, spread = read_driver(td, {
                "T-1": [jrow("role", "blank", None, 2, "qa-scout"), jrow("role", "dup", 1.0, 3, "qa-runner")],
                "T-2": [jrow("role", "dup", 3.0, 3, "qa-runner")]})
        files = [carry("blank", "p"), carry("dup", "p")]
        page = cost_page(files, driver, spread, task_of=D.task_binding(driver))
        ans = answer_for(files, driver, spread, task="T-1")
        self.assertEqual(ans["status"], "not_cross_checked")
        self.assertEqual(by_task_rows(page)["T-1"][:2], (2, "$1.00"))
        self.assertIn(ans["finding"], html.unescape(section(page, "By task")))
        self.assertNotIn("$0.00", page)

    def test_edge_some_known_some_unknown_is_a_range_only_where_a_known_record_differs(self):
        # k1 and k2 have a CLI charge that equals the file's price; u1 has none: the story agrees on the two it can compare
        files = [carry("k1", "p"), carry("k2", "p"), carry("u1", "p")]
        journal = [jrow("role", "k1", 0.5, 2, "qa-scout"), jrow("role", "k2", 0.5, 2, "qa-runner"),
                   jrow("role", "u1", None, 2, "qa-automator")]
        with tempfile.TemporaryDirectory() as td:
            driver, spread = read_driver(td, {TASK: journal})
        page = cost_page(files, driver, spread, task_of=D.task_binding(driver))
        ans = answer_for(files, driver, spread)
        self.assertEqual(ans["status"], "agrees")
        self.assertEqual(by_task_rows(page)[TASK][:2], (3, "$1.50"))
        self.assertIn("the two records agree", by_task_rows(page)[TASK][2])
        self.assertEqual(agent_cols(page, "qa-automator"), ("$0.50", DASH, "$0.50"))     # the one with no CLI charge: its file


class TicketSessionTests(Case):
    """Item 2 (C3, changed by the owner): a session that is neither a role's nor the conductor's (kind `ticket`) is
    data fetching: the SCOUT's record, never the orchestrator's and never a row of its own."""

    TICKET = jrow("ticket", "tk", 0.5, 3, "jira-agent", ts="2026-09-30T03:40:00+00:00")
    SCOUT = jrow("role", "sc", 0.5, 10, "qa-scout", ts="2026-09-30T03:50:00+00:00")

    def page(self, journal, files):
        with tempfile.TemporaryDirectory() as td:
            driver, spread = read_driver(td, {TASK: journal})
        return cost_page(files, driver, spread, task_of=D.task_binding(driver))

    def test_2_a_ticket_session_sits_under_the_scouts_row_and_by_task_and_by_agent_count_the_same_sessions(self):
        page = self.page([self.TICKET, self.SCOUT], [carry("tk", "p"), carry("sc", "p")])
        agent = section(page, "By agent")
        self.assertIn("<td><b>qa-scout</b></td><td>2</td>", agent)                  # both sessions, one row
        self.assertNotIn("<b>orchestrator</b>", agent)
        self.assertNotIn("<b>ticket</b>", agent)
        self.assertEqual(agent_cols(page, "qa-scout"), ("$1.00", "$1.00", "$1.00"))
        self.assertEqual(by_task_rows(page)[TASK][:2], (2, "$1.00"))
        self.assertEqual(total_row(page, "Sum of orchestrator + agents", agent), "$1.00")

    def test_2_a_session_with_a_ticket_row_and_a_role_row_is_one_priced_session_and_two_dispatch_records(self):
        both = [jrow("ticket", "tk", 0.1, 2, "jira-agent", ts="2026-09-30T03:40:00+00:00"),
                jrow("role", "tk", 0.5, 5, "qa-automator", ts="2026-09-30T03:41:00+00:00")]
        page = self.page(both, [carry("tk", "p")])
        agent_section = section(page, "By agent")
        # the money is the session's (its role's); the calls and turns are the per-(session, dispatch) records:
        # the ticket dispatch is the scout's, the role dispatch the automator's (R8)
        self.assertEqual(agent_cols(page, "qa-automator"), ("$0.50", "$0.50", "$0.50"))
        self.assertIn("<td><b>qa-automator</b></td><td>1</td><td>5</td>", agent_section)
        self.assertIn("<td><b>qa-scout</b></td><td>1</td><td>2</td>", agent_section)
        self.assertEqual(by_task_rows(page)[TASK][:2], (1, "$0.50"))
        with tempfile.TemporaryDirectory() as td:
            driver, _ = read_driver(td, {TASK: both})
        records = D.journal_records(driver, D.root_charged(driver)[0])
        self.assertEqual(sorted((r["role"], r["turns"]) for r in records), [("qa-automator", 5), ("qa-scout", 2)])

    def test_2_a_session_of_another_kind_is_its_own_record_named_by_its_kind_not_the_orchestrator(self):
        other = [self.SCOUT, jrow("delivery", "dl", 0.9, 1)]
        page = self.page(other, [carry("sc", "p"), carry("dl", "p")])
        self.assertNotIn("<td><b>orchestrator</b>", section(page, "By agent"))
        self.assertIn("<td><b>delivery</b></td><td>1</td>", section(page, "By agent"))
        self.assertIn("<td><b>qa-scout</b></td><td>1</td>", section(page, "By agent"))

    def test_2_the_label_is_the_one_of_the_reader_a_ticket_is_never_the_conductor(self):
        self.assertEqual(D.DJ.agent_label([self.TICKET]), "qa-scout")
        self.assertEqual(D.DJ.agent_label([jrow("conductor", "c", 1.0)]), "conductor")
        with tempfile.TemporaryDirectory() as td:
            driver, _ = read_driver(td, {TASK: [self.TICKET, self.SCOUT]})
        self.assertEqual({r["role"] for r in D.journal_records(driver, D.root_charged(driver)[0])}, {"qa-scout"})


# ------------------------------------------------------------------------------------ the estimates

class FloorTests(Case):
    """Item 3: the estimates' figure is the story's price; "a floor" is said only where it is true."""

    def estimates(self, root):
        return html.unescape(panel(render(root), "cost")).split("Estimates at a glance")[1]

    def test_3_a_journaled_story_whose_two_records_agree_is_no_floor_and_has_one_figure(self):
        with tempfile.TemporaryDirectory() as td:
            slug = slug_of(td)
            files = [carry("a1", slug), carry("a2", slug)]
            root = write_root(td, files, {TASK: agreeing_journal(files)},
                              estimates=[{"task": TASK, "ts": TODAY, "forecast": {"size_initial": "M"}}])
            estimates = self.estimates(root)
        self.assertIn(ARROW + " $1.00</td>", estimates)            # the figure is shown ...
        self.assertNotIn("(floor)", estimates)                      # ... without the mark
        self.assertNotIn("can only be higher", estimates)
        self.assertNotIn("Costs with a range", estimates)

    def test_3_a_journaled_story_whose_records_differ_has_a_range_and_no_dot_in_the_widgets(self):
        with tempfile.TemporaryDirectory() as td:
            estimates = self.estimates(running_root(td))
        self.assertIn(ARROW + " from $", estimates)
        self.assertNotIn("(floor)", estimates)
        self.assertIn("Costs with a range (" + TASK + ") have no single figure", estimates)
        self.assertIn(TASK + ": from $", estimates)             # the answer's own note, with its finding
        self.assertIn("the transcripts at catalogue rates and the CLI's own charge differ", estimates)

    def test_3_a_story_with_a_session_priced_by_neither_record_stays_a_floor(self):
        journal = [jrow("role", "s-known", 0.5, 3, "qa-runner"), jrow("role", "s-none", None, 3, "qa-scout")]
        with tempfile.TemporaryDirectory() as td:
            slug = slug_of(td)
            root = write_root(td, [carry("s-known", slug)], {TASK: journal},
                              estimates=[{"task": TASK, "ts": TODAY, "forecast": {"size_initial": "M"}}])
            estimates = self.estimates(root)
        self.assertIn(ARROW + " $0.50 (floor)</td>", estimates)
        self.assertIn("Costs marked a floor (" + TASK + ")", estimates)
        self.assertIn("can only be higher", estimates)

    def test_3_a_story_with_no_journal_keeps_one_figure_labelled_single_source(self):
        with tempfile.TemporaryDirectory() as td:
            root = write_root(td, golden_files(slug_of(td)), estimates=[{"task": "T-1", "ts": TODAY, "forecast": {"size_initial": "M"}}])
            estimates = self.estimates(root)
        self.assertIn(ARROW + " $2.40</td>", estimates)             # 1.25 + 0.75 of g-story, 0.4 of g-two's T-1 segment
        self.assertIn("T-1: $2.40 (single source (chat): nothing to cross-check against).", estimates)

    def test_3_a_task_with_no_record_says_so_never_a_dollar_figure(self):
        with tempfile.TemporaryDirectory() as td:
            root = write_root(td, [], estimates=[{"task": "T-7", "ts": TODAY, "forecast": {"size_initial": "M"}}])
            estimates = self.estimates(root)
        self.assertIn("T-7: no session of this task has a record.", estimates)
        self.assertIn(ARROW + " " + DASH + "</td>", estimates)
        self.assertNotIn("$0.00", estimates)


# ------------------------------------------------------------------------------------ the page

class CmpShapedPageTests(Case):
    """main() on a root shaped like cmp1: a journal and collapsed carry-row cost files."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = a_root(cls.tmp.name)
        cls.page = render(cls.root)
        cls.plain = html.unescape(cls.page)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_by_task_the_story_card_the_cost_finding_the_hot_cache_title_and_the_floor_all_name_the_story(self):
        cost, factory = panel(self.plain, "cost"), panel(self.plain, "factory")
        self.assertEqual(list(by_task_rows(self.page)), [TASK])
        self.assertEqual(by_task_rows(self.page)[TASK][:2], (5, "from $2.70 to $2.90"))
        self.assertIn("<div class='lbl'>" + TASK + "</div>", cost)                       # the story card
        finding = "cost incomplete for " + TASK + ": 4 of 4 sessions provisional"
        self.assertIn(finding, cost)                                                    # the Cost tab's finding
        self.assertIn(finding, factory)                                                 # and the Factory tab's
        self.assertIn("Hot cache share below 90% - " + TASK + ": 4 of 4 sessions", self.plain)   # the banner
        self.assertIn(ARROW + " from $2.70 to $2.90</td>", cost)                       # the estimates: a range, no floor
        estimates = cost.split("Estimates at a glance")[1]
        self.assertIn("Costs with a range (" + TASK + ")", estimates)
        self.assertIn(TASK + ": from $2.70 to $2.90 (the two records differ).", estimates)
        for gone in ("cost incomplete for Unclassified", "- Unclassified", "<td>Unclassified</td>", "driver sessions"):
            self.assertNotIn(gone, self.plain)

    def test_the_conductor_is_bound_to_its_task_and_is_the_conductor_row_of_by_agent(self):
        agent = section(self.page, "By agent")
        self.assertIn("<td><b>conductor</b></td><td>1</td>", agent)
        self.assertEqual(agent_cols(self.page, "conductor"), ("$0.50", "$0.30", "from $0.30 to $0.50"))
        self.assertEqual(agent_cols(self.page, "qa-automator"), ("$0.50", DASH, "$0.50"))   # two rising rows under a per-call root

    def test_a_render_with_a_journal_writes_nothing_under_the_root(self):
        before = sorted((p.relative_to(self.root).as_posix(), p.stat().st_size) for p in self.root.rglob("*") if p.is_file())
        render(self.root)
        self.assertEqual(sorted((p.relative_to(self.root).as_posix(), p.stat().st_size)
                                for p in self.root.rglob("*") if p.is_file()), before)


class SeveralStoriesPageTests(Case):
    """E5: several stories on one root. The default view shows every label, --task narrows the lists
    only, and the warnings and the history stay the whole root's."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        slug = slug_of(cls.tmp.name)
        story = lambda sid, task: cost_file(sid, [request(sid, 0, task, 0.5, "a", COLD)], slug,
                                            activities={"a": {"type": "story", "task": task}})
        tag_only = cost_file("stray", [request("stray", 0, "T-A", 0.5, "a", COLD)], slug, activities={"a": {"type": "unclassified"}})
        files = [carry("a1", slug), carry("a2", slug), carry("b1", slug, tags=("T-B",)), tag_only,
                 story("other", "T-9"), carry("loose", slug),
                 cost_file("doc", [request("doc", 0, "(no task)", 0.1, "a", SMALL)], slug, activities={"a": {"type": "doctor"}})]
        journals = {"T-A": [jrow("role", "a1", 0.5, 3, "qa-scout"), jrow("conductor", "a2", 0.5, 2)],
                    "T-B": [jrow("role", "b1", 0.5, 3, "qa-scout")]}
        cls.root = write_root(cls.tmp.name, files, journals)
        cls.page = html.unescape(render(cls.root))
        cls.task_page = html.unescape(render(cls.root, "--task", "T-A"))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_default_view_gives_every_story_its_own_label_and_the_tag_only_session_its_own_too(self):
        rows = by_task_rows(self.page)
        self.assertEqual({k: v[0] for k, v in rows.items()},
                         {"T-A": 2, "T-B": 1, "T-A - not launched by the driver": 1, "T-9": 1, "Unclassified": 1, "Doctor": 1})
        self.assertEqual(rows["T-A"][1], "$1.00")
        self.assertEqual(rows["T-B"][1], "$0.50")
        self.assertEqual(rows["T-A - not launched by the driver"][1], "$0.50")      # listed apart, in no price

    def test_the_task_view_narrows_the_lists_and_carries_the_same_price(self):
        rows = by_task_rows(self.task_page)
        self.assertEqual({k: v[0] for k, v in rows.items() if not k.endswith("not launched by the driver")}, {"T-A": 2})
        self.assertEqual(rows["T-A"][1], "$1.00")
        self.assertNotIn("<td>T-B</td>", section(self.task_page, "By task"))

    def test_the_warnings_are_the_whole_roots_in_both_views(self):
        for page in (self.page, self.task_page):
            for label in ("T-A", "T-B", "T-9", "Unclassified"):
                self.assertIn("Hot cache share below 90% - " + label + ":", page)


class TwoJournalsAndArchivesPageTests(Case):
    """E4 and E13 through main(): one session in two journals, an archived story's journal, a legacy archive/ one."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        slug = slug_of(cls.tmp.name)
        files = [carry(s, slug) for s in ("dup", "t1only", "t2only", "kept", "legacy")]
        journals = {"T-1": [jrow("role", "dup", 0.4, 3, "qa-scout", ts="2026-09-02T00:00:00+00:00"),
                            jrow("role", "t1only", 0.3, 3, "qa-scout", ts="2026-09-02T00:00:00+00:00")],
                    "T-2": [jrow("role", "dup", 0.4, 3, "qa-scout", ts="2026-09-01T00:00:00+00:00"),
                            jrow("role", "t2only", 0.3, 3, "qa-scout", ts="2026-09-01T00:00:00+00:00")],
                    "T-old": [jrow("role", "kept", 0.3, 3, "qa-scout")],
                    "archive/T-legacy": [jrow("role", "legacy", 0.3, 3, "qa-scout")]}
        cls.root = write_root(cls.tmp.name, files, {k: v for k, v in journals.items() if not k.startswith("archive/")})
        (cls.root / "qa-factory" / "artifacts" / "T-old" / "pipeline.json").write_text('{"archived": true}', encoding="utf-8")
        legacy = cls.root / "qa-factory" / "artifacts" / "archive" / "T-legacy" / "state"
        legacy.mkdir(parents=True)
        (legacy / "driver-runs.jsonl").write_text(json.dumps(journals["archive/T-legacy"][0]) + "\n", encoding="utf-8")
        cls.page = html.unescape(render(cls.root))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_session_of_two_journals_is_counted_under_the_earlier_one_and_named_in_both_sections(self):
        rows = by_task_rows(self.page)
        self.assertEqual(rows["T-2"][0], 2)         # dup + t2only
        self.assertEqual(rows["T-1"][0], 1)         # t1only
        self.assertIn("session dup is named by 2 task journals; counted under T-2", section(self.page, "By task"))
        self.assertIn("session dup appears under 2 tasks; counted under T-2", section(self.page, "By agent"))

    def test_an_archived_storys_journal_still_binds_and_a_legacy_archive_folder_is_not_read(self):
        rows = by_task_rows(self.page)
        self.assertEqual(rows["T-old"][0], 1)
        self.assertNotIn("T-legacy", self.page.split("By task")[1].split("</section>")[0])
        self.assertEqual(rows["Unclassified"][0], 1)  # the session only the legacy archive names


class BlankRowDefaultsTests(Case):
    """t-427 (canon part A, survivor 7): the two default arguments of `dashboard_cost_groups.blank_row` were pinned by no
    row. `ok=True, cost=0.0` is the shape of a row an attached rowless gap makes bare; `group`'s empty row passes only
    `cost` (so its `ok` is the default); `task_groups` passes `ok=None` (its `ok` is set from the reconciliation later)."""

    def test_the_bare_row_is_ok_with_a_float_zero_cost(self):
        import dashboard_cost_groups as G
        row = G.blank_row()
        self.assertIs(row["ok"], True)
        self.assertEqual(row["cost"], 0.0)
        self.assertIsInstance(row["cost"], float)

    def test_the_two_callers_that_name_an_argument_get_that_argument_and_the_other_default(self):
        import dashboard_cost_groups as G
        task_row = G.blank_row(ok=None)
        self.assertIsNone(task_row["ok"])
        self.assertIsInstance(task_row["cost"], float)
        self.assertEqual(task_row["cost"], 0.0)
        money = G.blank_row(cost=Decimal("0"))
        self.assertIs(money["ok"], True)
        self.assertIsInstance(money["cost"], Decimal)

    def test_a_gap_with_no_row_gets_a_bare_row_through_attach_rowless_gaps(self):
        import dashboard_cost_groups as G
        by_task = {}
        session = {"session_id": "s-1", "requests": [{"stream": "x"}], "incomplete_agents": ["qa-x"],
                   "incomplete_where": [{"agent": "qa-x", "activities": ["unclassified"]}]}
        G.attach_rowless_gaps(by_task, [session], {})
        row = by_task["Unclassified"]
        self.assertEqual((row["ok"], row["cost"], row["incomplete_agents"]), (True, 0.0, {"qa-x"}))
        self.assertIsInstance(row["cost"], float)

    def test_the_empty_row_of_group_and_of_task_groups_keep_their_arguments(self):
        import dashboard_cost_groups as G
        by_task, _days = G.group([{"session_id": "s-2", "requests": [], "by_model": {}, "incomplete_agents": []}])
        row = by_task.default_factory()  # the `empty` of group: the row a new label starts from
        self.assertIs(row["ok"], True)
        self.assertIsInstance(row["cost"], Decimal)
        self.assertIsNone(D._blank_task_row()["ok"])
        self.assertEqual(D._blank_task_row()["cost"], 0.0)


class GoldenPageTests(Case):
    """R3, with C6's exclusion (R5): a root with NO journal renders as the golden page says. The golden page
    was first cut from `golden_fixture` by the code as it stood BEFORE any edit of t-111 and was RE-CUT ONCE
    by t-169 (the dashboard reads the price function and re-prices every cost file at read: its dollars are
    the catalogue's, its notes and columns are the new ones; the diff is listed in the hand-over). It was re-cut
    again by the r0107 round 2 fix of t-272 (HF7-3, HF7-5 and the HF8-12 N3 `role context` line: see the comment above
    `GOLDEN_SHA256`). What is kept is its sha256 and the sha256 of each of its `<section` pieces."""

    def test_a_root_with_no_journal_renders_as_the_golden_page_says(self):
        with tempfile.TemporaryDirectory() as td:
            root = golden_fixture(td)
            page = mask(render(root), root)
        pieces = re.split(r"(?=<section)", page)
        digests = tuple(hashlib.sha256(p.encode("utf-8")).hexdigest()[:16] for p in pieces)
        differing = [(i, pieces[i][:90]) for i in range(max(len(digests), len(GOLDEN_SECTIONS)))
                     if i >= len(digests) or i >= len(GOLDEN_SECTIONS) or digests[i] != GOLDEN_SECTIONS[i]]
        self.assertEqual(differing, [], "sections that differ from the golden page (index, start)")
        self.assertEqual(hashlib.sha256(page.encode("utf-8")).hexdigest(), GOLDEN_SHA256)

    def test_the_golden_page_does_not_move_with_what_lies_outside_the_fixture_root(self):
        """t-291: the page is a function of the fixture root alone. The two things outside it that a render
        can see are the machine's transcript folder under the user's home and the clock; this renders the
        same fixture under two different ones and wants the one golden page both times. The clock is the
        one that bit (see YESTERDAY): 03:30 UTC and 22:30 UTC are the two sides of the 10:05 UTC at which the
        old fixture's requests stopped being in the future."""
        import metrics_projection as MP

        def at(hour):
            class Clock(datetime):
                @classmethod
                def now(cls, tz=None):
                    base = datetime.now(timezone.utc).replace(hour=hour, minute=30, second=0, microsecond=0)
                    return base if tz else base.replace(tzinfo=None)
            return Clock

        def render_under(hour, junk):
            saved_env = {k: os.environ.get(k) for k in ("HOME", "USERPROFILE")}
            saved_clock = MP.datetime
            try:
                with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as td:
                    root = golden_fixture(td)
                    folder = Path(home) / ".claude" / "projects" / slug_of(td)
                    folder.mkdir(parents=True)
                    for sid in ("g-story", "g-loose", "stranger"):    # a transcript of this very project, and a stranger
                        (folder / (sid + ".jsonl")).write_text(junk, encoding="utf-8")
                    os.environ["HOME"] = os.environ["USERPROFILE"] = home
                    MP.datetime = at(hour)
                    return mask(render(root), root)
            finally:
                MP.datetime = saved_clock
                for k, v in saved_env.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v

        early = render_under(3, "")
        late = render_under(22, json.dumps({"type": "assistant", "message": {"usage": {"output_tokens": 999999}}}) + "\n")
        self.assertEqual(early == late, True, "two renders of one fixture under a different clock and home differ")
        self.assertEqual(hashlib.sha256(early.encode("utf-8")).hexdigest(), GOLDEN_SHA256)

    def test_an_empty_journal_and_a_journal_of_rows_no_session_owns_render_the_cost_tab_as_before(self):
        with tempfile.TemporaryDirectory() as td:
            root = golden_fixture(td)
            control = mask(render(root), root)
            state = root / "qa-factory" / "artifacts" / "T-empty" / "state"
            state.mkdir(parents=True)
            (state / "driver-runs.jsonl").write_text("", encoding="utf-8")
            other = root / "qa-factory" / "artifacts" / "T-noid" / "state"
            other.mkdir(parents=True)
            (other / "driver-runs.jsonl").write_text(json.dumps({"kind": "delivery", "outcome": "nothing_outward"}) + "\nnot json\n",
                                                     encoding="utf-8")
            page = mask(render(root), root)
        self.assertIn("Unclassified", by_task_rows(control))
        # everything the cost tab draws from the sessions (its evidence lists name the journal files
        # the metrics projection read, which is not this change's business)
        head = lambda p: panel(p, "cost").split("<section><h2>By model")[0]
        self.assertEqual(head(page), head(control))
        for title in ("By model", "By day", "Top tools"):
            self.assertEqual(section(page, title), section(control, title))
        self.assertEqual(page.split("<div class='panel")[0], control.split("<div class='panel")[0])   # the banner above the tabs


# ------------------------------------------------------------------------------------ the other consumers

class ConsumerTests(Case):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.driver, cls.spread = read_driver(cls.tmp.name, {TASK: A_JOURNAL})
        cls.files = a_files("proj")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_select_task_sessions_reads_the_one_binding_and_derives_it_when_none_is_given(self):
        others = [carry("x", "p", tags=("T-9",))]
        derived = D.select_task_sessions(self.files + others, [TASK], self.driver)
        given = D.select_task_sessions(self.files + others, [TASK], self.driver, D.task_binding(self.driver))
        self.assertEqual([s["session_id"] for s in derived["whole"]], ["s-cond", "s-scout", "s-auto", "s-runner"])
        self.assertEqual(derived, given)
        none = D.select_task_sessions(self.files, [TASK], self.driver, {})     # an explicit empty binding is no binding
        self.assertEqual([s["session_id"] for s in none["whole"]], ["s-scout"])
        self.assertEqual([s["session_id"] for s in none["shared"]], ["s-auto"])   # tagged to the task AND to no task

    def test_the_cost_findings_of_the_factory_tab_use_the_binding(self):
        bound = D.cost_capture_findings(self.files, None, D.task_binding(self.driver))
        self.assertEqual(len(bound), 1)
        self.assertIn("cost incomplete for " + TASK + ": 4 of 4 sessions provisional", bound[0])
        self.assertIn("Unclassified", D.cost_capture_findings(self.files, None)[0])    # the defect without it
        answers = {TASK: answer_for(self.files, self.driver, self.spread)}
        priced = D.cost_capture_findings(self.files, None, D.task_binding(self.driver), answers, self.driver)
        self.assertEqual(len(priced), 1)                                               # the rows By task draws
        self.assertIn("cost incomplete for " + TASK + ": 4 of 4 sessions provisional", priced[0])

    def test_the_banner_share_line_counts_a_bound_session_for_its_journals_task(self):
        sessions = [dict(carry("c", "p", cost=2.0), requests=[dict(request("c", 0, "(no task)", 2.0, "u", COLD),
                                                                 request_key="c:0")]),
                    carry("r", "p", cost=8.0)]
        driver = {"c": {"task": TASK, "rows": [jrow("conductor", "c", 2.0)]}, "r": {"task": TASK, "rows": [jrow("role", "r", 8.0, 1, "qa-scout")]}}
        runs = [{"task": TASK}]
        # the same two sessions with no journal: tagged "(no task)", so nobody's story: silent, as on cmp1 before the binding
        self.assertEqual(D.orchestrator_shares(sessions, runs, 15, {}, {}), [])
        line = D.orchestrator_shares(sessions, runs, 15, driver, D.task_binding(driver))
        self.assertEqual(len(line), 1)
        self.assertTrue(line[0].startswith(TASK + ":"))
        self.assertIn("spent 20 % of the story", line[0])           # the conductor's $2.00 of the journal's $10.00
        # a session the journal does not name never joins the journaled story (FR-24)
        stray = cost_file("stray", [request("stray", 0, TASK, 50.0, "a", COLD)], "p", activities={"a": {"type": "story", "task": TASK}})
        self.assertEqual(D.orchestrator_shares(sessions + [stray], runs, 15, driver, D.task_binding(driver)), line)

    def test_the_hot_cache_signals_are_per_the_bound_task(self):
        from metric_signals import _hot_cache_signals, refresh
        snapshot = {"as_of": TS, "input_hash": "h", "metrics": []}
        ids = lambda signals: sorted(s["id"] for s in signals)
        without, _ = _hot_cache_signals(snapshot, {}, self.files, {})
        self.assertEqual(ids(without), ["hot-cache-v1:story-Unclassified"])          # the defect: one label, no story
        bound, _ = _hot_cache_signals(snapshot, {}, self.files, {}, D.task_binding(self.driver))
        self.assertEqual(ids(bound), ["hot-cache-v1:story-TP1-13797"])
        self.assertEqual(bound[0]["title"], "Hot cache share below 90% - " + TASK + ": 4 of 4 sessions")
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "qa-factory" / "state").mkdir(parents=True)
            receipt, _history = refresh(td, dict(snapshot, estimates=[], metrics=[{"id": "C08", "label": "x"}]), {}, self.files,
                                        D.task_binding(self.driver))
        self.assertIn("hot-cache-v1:story-" + TASK, [s["id"] for s in receipt["signals"]])


class StoryCardKeyFormTests(unittest.TestCase):
    """B-405: which task name is a story is the PROJECT's ticket-key form (`adapter_forms`, read from
    <root>/qa-factory/config.json), not a Jira literal: a numeric story on GitHub issues gets its card, a number
    on a Jira project does not, and `orchestrator` or `(no task)` is never a story."""

    GITHUB = {"adapters": {"ticket": {"name": "github"}}}

    def card(self, task, cfg):
        with tempfile.TemporaryDirectory() as td:
            files = [cost_file("s1", [request("s1", 0, task, 0.5, "unclassified", COLD)], slug_of(td), factory=True)]
            root = write_root(td, files, config=cfg)
            return ("<div class='lbl'>" + task + "</div>") in html.unescape(D.tab_cost(files, {}, root, {}, {}))

    def test_a_numeric_story_has_its_card_under_a_numeric_form(self):
        self.assertTrue(self.card("123", self.GITHUB))

    def test_the_same_number_is_no_story_under_the_jira_form(self):
        self.assertFalse(self.card("123", {}))

    def test_a_jira_story_has_its_card_under_the_default_form(self):
        self.assertTrue(self.card(TASK, {}))

    def test_orchestrator_is_never_a_story(self):
        self.assertFalse(self.card("orchestrator", self.GITHUB))
        self.assertFalse(self.card("orchestrator", {}))

    def test_a_config_that_cannot_be_read_is_the_default_form(self):
        self.assertEqual(D.project_config(Path("no-such-root-for-b405")), {})
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "qa-factory").mkdir()
            (Path(td) / "qa-factory" / "config.json").write_text("[1, 2]", encoding="utf-8")
            self.assertEqual(D.project_config(td), {})
            (Path(td) / "qa-factory" / "config.json").write_text("{broken", encoding="utf-8")
            self.assertEqual(D.project_config(td), {})
            self.assertEqual(D.project_config(None), {})


# The page the code drew for `golden_fixture` (default view, read-only, masked by `mask`): its sha256, and
# the sha256 (first 16 hex) of each of its `<section` pieces so that a difference names the section it is in.
# Re-cut once by t-169 (see GoldenPageTests), and once by t-182 (the critic's F6/F7 of the true price), which moved
# TWO sections and nothing else: piece 5 (the cost-tab note: "1 cost file(s) hold no per-request ledger" is now "1 cost
# file holds no per-request ledger", the count-based plural) and piece 7 (By task: one added sentence stating the check's
# tolerance in words, "a session agrees when they differ by no more than a tenth of a cent"). The masked page itself is
# 84 kB and lives outside the tests.
# Re-cut by t-260 (fork F3 of t-232) for the PATH TEXT of the two-folder layout and nothing else: piece 14
# (Estimates: "The source is qa-factory/records/estimation-ledger.jsonl", was state/) and the footer, which is
# the tail of the last piece, 20 (the sources line names records/estimation-ledger.jsonl and records/journal.jsonl,
# were state/). The whole-page sha256 and those two pieces are of the old page with ONLY those words changed.
# Re-cut by t-284 for the FORMULA VERSION and nothing else: eight metric rows (C02, C06, C08, C09, C10, C11, C15,
# F08) say "formula v2" where the page above said "formula v1" (metrics_projection.MONEY_FORMULA_VERSION = 2,
# references/metrics-contract.md: the price-basis version of those metrics). The proof is a byte one: the page as it
# renders now, with those eight occurrences of "formula v2" put back to "formula v1", has the previous whole-page
# sha256 (12c7203b...) and every previous piece digest. So pieces 13 and 20 (the last piece, which carries the
# footer) and the whole-page sha256 are the only constants that moved.
# t-291: NOT re-cut. The constants below are the page rendered with the cost files' requests inside the metrics
# window; the fixture's timestamps were moved to a day in the past (YESTERDAY) so that holds at every hour of the
# day, and the page it draws is byte for byte this one (its dates are masked); the isolation test beside the
# golden one renders the fixture under two clocks and two homes and wants this same sha256 from both.
# Re-cut once more for B-301 b (t-413): `mask` now spells paths one way on every platform. Only the three
# sections that list evidence files moved (4, 13, 20); the old Windows page and this one differ in slashes
# alone (checked: equal after replacing "\" by "/"), and the Linux runner renders this very page.
# Re-cut for CD1-7 (t-879) and nothing else: the package's Sonnet 5.5 cache-read rate went from $0.20 to $0.10 per MTok
# (the price page of 2026-10-16), so `shaped()` (CACHE_READ_RATE above) gives a fixture twice the cache-read tokens for the
# same dollars. Only the eight sections that carry token counts or the hot-cache share moved: 1 (metric warnings), 5
# (cost-capture finding), 6 (token composition), 7 (By task), 8 (By agent), 9 (By model), 10 (By day), 13 (cost and
# estimates); the other thirteen digests are those above, unchanged.
# Re-cut for RH1-11 (host_probe.py --check names every unmet condition, changelog rh1-11-host-probe-unmet): with no probe
# file the "Host mechanism receipts" block (piece 18, which follows Factory health) gains `missing (1)` / `no_probe_file`
# and its `reason` ends with `Unmet: no_probe_file (...)`, and the guard probe count goes 3 -> 4. Only piece 18 and the
# whole-page sha256 moved; the other twenty digests are those above (checked by diffing the page of origin/main with this one).
# Re-cut for HF7-3, HF7-5 and HF8-12 N3 (r0107 round 2, t-272): three pieces moved and nothing else (0, 7, 18). Piece 0: the
# CSS gains `.info{color:#98a1ab}` (HF7-5). Piece 7 (By task): the two stories with no journal say "single source (chat):
# nothing to cross-check against" in the cell and in the price note instead of "not cross-checked" (HF7-5; the cell stays
# `warn`, its provisional-session gap still follows the words). Piece 18 (Factory health, with the host receipts block): the readiness block gains
# `role context: Not recorded` (HF8-12 N3, 4692435d: this fixture has no context-delivery receipt; it was already red at the
# merge base for this reason alone). The proof is a byte one: the page as it renders now, with that one `role context` div
# and the `.info` rule taken out and the single-source words put back to "not cross-checked", has every previous piece
# digest (21 of 21) and the previous digests of 0, 7 and 18 are those above. The whole-page sha256 moved with them.
# Re-cut for RH2-5 (a7c5b1a1, t-308; found red by the canon, t-427): the host_hooks note ends with the unmet list and drops the
# transcript door, so piece 18 (Factory health, the "Live guard evidence is incomplete" note) reads "... Unmet: no_probe_file
# (there is no probe file for this project yet)." and no longer "If commands ran but correlation failed, inspect the transcript call
# format.". Proof: the tree at afac6b5c (the last cut) renders the previous golden sha 6850eb8b..., and the diff of its piece 18
# against this tree's is that one sentence pair; the other twenty digests are those above. Piece 18 and the whole-page sha moved.
# Re-cut for CD1-27 (t-719, F4(a): one re-cut, By task only): piece 7 (By task) moved and nothing else; the whole-page sha
# moved with it. The T-2 row (a story priced from its own activity) gains "; unbound: 1 session (not in this price)" in its
# completeness cell (g-legacy tags T-2 and nothing binds it) and the section gains one sentence under the table naming where
# that session's money is counted ("T-2 - tagged only, not counted in its price, Unclassified (g-legacy)"). The time cells
# (T-1 1m 00s, T-2 "-", the tagged-only row 0m 20s, the total 1m 25s) and every dollar are those of the previous cut; the
# other twenty digests are those above (the test lists the differing pieces before it compares the whole page).
# Re-cut for t-1698 D2-D (C04 text) and t-1759 F2 (C06 text), found red by CI on p1-closeout (t-1777): pieces 13 (Cost and estimates)
# and 14 (Estimates (by cost)) render the catalogue's C04 and C06 `formula`/`missing` strings, which those two nodes changed. Proof,
# a byte one: the page as it renders now with the previous (a90704211) C04 and C06 strings put back (6 occurrences, HTML-escaped) has
# the previous whole-page sha f811c93a... and all 21 previous piece digests; only pieces 13 and 14 and the whole-page sha moved.
# Re-cut for the GM2-2 O7 rewrite (t-1927): piece 18 (Factory health) quotes a ticket key in the "orchestrator share" tooltip, and the
# rewrite renamed that key in the package text. Proof, a byte one: the page as it renders now with the old key put back through the O7
# map has the previous piece-18 digest (0f10722332666d3e) and the previous whole-page sha (4c9350fd...); no other piece moved.
GOLDEN_SHA256 = "8f42631fed416a1db805bacd20516524dd6b9669465ef15be745ed915315c5fe"
GOLDEN_SECTIONS = (
    "3ae10aca7c498cbc", "294a2520da8f0334", "327dbfb6b6394f7d", "e4f3362c3aaf2c64", "a96705f8c6253a1f",
    "106c0ce4a6c2eb4c", "fcfc470b4c2d3a24", "60d15664433fdcca", "e3903c519182f139", "f6429d2f27700ea4",
    "e51aa5cf22af34a8", "419590bf1521a4a3", "690298c279c1682c", "e4a218ca69c64eb4", "80fb216ca527cb53",
    "ff519f73d2b74caf", "8e8f7a92d893a9de", "0e789010bcdd5db5", "813bdc1c020cf23d","8f4082e1a1b84432",
    "23c5b313acdd8312",
)


if __name__ == "__main__":
    unittest.main()
