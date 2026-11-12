#!/usr/bin/env python3
"""The retro and the budget ceiling read the ONE price function (t-137 piece Q6, t-170).

`task_price` answers what a story costs from two independent records (A: the cost files re-priced
at the catalogue's list rate; B: the CLI's own charge from the driver's journal). This file holds
what the two READERS of that answer must do, one named check per requirement and per edge:

  R1  the retro's price line says what `task_price` says - one figure when the records agree, "from
      $low to $high" plus the finding when they differ, "not cross-checked" for one record, what is
      known and why when incomplete - and computes no second figure; its by-agent table shows the
      two records and a per-row price pair that adds up to the story's pair; no sentence names an
      "authoritative" record
  R2  (B-223) the story's sessions are the ones the price names, not the ones that carry the ticket
      in a `by_task` tag: on a cmp1-shaped fixture all 35 sessions are in, the 13 a tag filter
      dropped included
  R3  (R12 + P6) the ceiling polices, per session, the CLI's charge where known, else the
      transcripts - never the larger of the two: a double count in the transcripts cannot stop a
      story; a disputed figure says so
  R4  the cache-read rate matches a model by exact id or alias, never by a substring
  R5  (t-171) no money in the retro's facts JSON is the money pinned at capture: the cost files'
      amounts in the share's basis and the dispatches' costs read the re-priced document

Every fixture is synthetic and lives in a temp directory. A cost file carries a bogus PINNED
valuation (999) so that anything reading the file's own money shows at once.
"""
import json
import re
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import cost_capture as CC  # noqa: E402
import retro_numbers as RN  # noqa: E402
import story_budget as SB  # noqa: E402
import task_price as TP  # noqa: E402

TASK = "QA-PRICE-1"
MODEL = "claude-sonnet-5-5"     # catalogue: output $10 per 1M tokens -> 100000 output tokens = $1.00


# ---------------------------------------------------------------------------------- fixtures

def usage_of(dollars):
    return {"requests": 1, "input": 0, "output": round(Decimal(str(dollars)) * 100000), "cache_read": 0,
            "cache_write_5m": 0, "cache_write_1h": 0}


def request(sid, rid, dollars, stream="orchestrator", activity="unclassified", task="(no task)"):
    return {"request_key": f"anthropic:{sid}:{rid}:{stream}", "provider": "anthropic", "session_id": sid,
            "request_id": rid, "stream": stream, "model_id": MODEL, "timestamp": "2026-09-30T05:00:00+00:00",
            "activity_id": activity, "activity_segment_id": activity, "task": task, "usage": usage_of(dollars),
            "valuation": {"subtotal_usd": "999", "pricing_coverage": "complete", "missing_rate_categories": [],
                          "rate_provenance": {"kind": "legacy_project_override"}, "tariff_confirmation": "unconfirmed"}}


def doc(sid, dollars, tag="(no task)", extra_requests=(), **extra):
    """A cost file of one session whose requests cost `dollars` (a number or a list) at the catalogue's
    rate; `tag` is the by_task key it carries (the ticket, or the collapsed `(no task)`)."""
    amounts = dollars if isinstance(dollars, list) else [dollars]
    out = {"session_id": sid, "has_factory_activity": True,
           "requests": [request(sid, f"r{i}", d) for i, d in enumerate(amounts)] + list(extra_requests),
           "by_task": {tag: {"tokens": 7, "requests": len(amounts)}}, "external_calls": [], "agents": [],
           "by_activity": {}, "total_cost_usd": 999.0}
    out.update(extra)
    return out


def story_doc(sid, dollars):
    """A session no journal names, bound to the story by a story activity segment (orchestrator mode)."""
    return doc(sid, dollars, tag=TASK, by_activity={"act-T": {"type": "story", "task": TASK}},
               requests=[request(sid, f"r{i}", d, activity="act-T", task=TASK)
                         for i, d in enumerate(dollars if isinstance(dollars, list) else [dollars])])


def jrow(sid, total, role="qa-runner", kind="role", dispatch="d1", stage="S5", resumed=False,
         ts="2026-09-30T10:00:00+00:00", **extra):
    out = {"kind": kind, "role": role, "dispatch": dispatch, "stage": stage, "session_id": sid,
           "num_turns": 1, "total_cost_usd": total, "resumed": resumed, "ts": ts}
    out.update(extra)
    return out


def conductor(sid, total, stage="S5"):
    return jrow(sid, total, role="", kind="conductor", dispatch="", stage=stage)


def project(rows=None, docs=(), config=None, stories=None):
    """(root, state, troot): a temp project with the story's journal (`rows`; none when None), the
    journals of other stories (`stories`: task -> rows) and its cost files."""
    root = temp_dir("qa-retro-price-")
    state = root / "qa-factory"
    troot = state / "artifacts" / TASK
    (state / "state" / "cost").mkdir(parents=True)
    (troot / "state").mkdir(parents=True)
    (state / "config.json").write_text(json.dumps(config or {}), encoding="utf-8")
    (troot / "pipeline.json").write_text(json.dumps({}), encoding="utf-8")
    for body in docs:
        (state / "state" / "cost" / f"{body['session_id']}.json").write_text(json.dumps(body), encoding="utf-8")
    if rows is not None:
        (troot / "state" / "driver-runs.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    for task, task_rows in (stories or {}).items():
        folder = state / "artifacts" / task / "state"
        folder.mkdir(parents=True)
        (folder / "driver-runs.jsonl").write_text("\n".join(json.dumps(r) for r in task_rows) + "\n", encoding="utf-8")
    return root, state, troot


def retro(rows=None, docs=(), config=None, stories=None):
    """(data, text) of the retro of a synthetic project."""
    root, state, troot = project(rows, docs, config, stories)
    try:
        data = RN.numbers(TASK, root=state, task_root=troot)
        return data, RN.render(data)
    finally:
        cleanup(root)


def two_agreeing():
    return ([conductor("c1", 0.5), jrow("r1", 1.0)], [doc("c1", 0.5), doc("r1", 1.0)])


def cmp1_shape():
    """35 sessions: 17 conductor sessions, 17 role sessions launched at $0.4 and resumed to $0.8, one
    ticket call of $0.75; every cost file at its session's price. 22 of the files carry the ticket in
    their by_task tag and 13 are the collapsed `(no task)` ones a tag filter dropped."""
    rows, totals = [], {}
    for i in range(17):
        rows.append(conductor(f"c{i}", 0.18 if i < 16 else 0.19, stage="S1" if i < 8 else "S4"))
        totals[f"c{i}"] = 0.18 if i < 16 else 0.19
        rows.append(jrow(f"r{i}", 0.4))
        rows.append(jrow(f"r{i}", 0.8, resumed=True))
        totals[f"r{i}"] = 0.8
    rows.append(jrow("t0", 0.75, role="", kind="ticket", dispatch="", stage="S0"))
    totals["t0"] = 0.75
    docs = [doc(sid, total, tag=TASK if i < 22 else "(no task)") for i, (sid, total) in enumerate(sorted(totals.items()))]
    return rows, docs


def figure(text):
    """The story's price as the retro prints it: the words after `**Story price: ` up to the closing
    `.**` or ` — `."""
    head = text.split("**Story price: ", 1)[1]
    for stop in (" — ", ".** "):
        if stop in head.split("\n", 1)[0]:
            head = head.split(stop, 1)[0]
            break
    return head


class Counting:
    """Wrap `task_price.task_price` to count its calls (and optionally make it raise)."""
    def __init__(self, raises=None):
        self.calls, self.raises, self.real = 0, raises, TP.task_price

    def __enter__(self):
        def wrapped(*args, **kwargs):
            self.calls += 1
            if self.raises is not None:
                raise self.raises
            return self.real(*args, **kwargs)
        TP.task_price = wrapped
        return self

    def __exit__(self, *exc):
        TP.task_price = self.real


# ------------------------------------------------------------------------------------ R1, the retro

def r1_the_price_line_says_what_the_price_function_says():
    rows, docs = two_agreeing()
    data, text = retro(rows, docs)
    check_eq("R1 agrees: the status is the price function's", data["price"]["status"], "agrees")
    check_eq("R1 agrees: the story's figure is the price, one figure", (data["story"]["usd"], figure(text)), (1.5, "$1.50"))
    check_in("R1 agrees: it says two records agree and what was compared", "Two records agree on it", text)
    check_in("R1 agrees: what was compared is stated", "the CLI's own charge for the 2 sessions the driver's journal names", text)

    rows, docs = [conductor("c1", 0.5), jrow("r1", 1.0)], [doc("c1", 0.5), doc("r1", 1.3)]
    data, text = retro(rows, docs)
    price = data["price"]
    check_eq("R1 differs: the status is the price function's", price["status"], "differs")
    check_eq("R1 differs: a range, no single figure (usd is None, the ends are kept)",
             (data["story"]["usd"], data["story"]["usd_low"], data["story"]["usd_high"]), (None, 1.5, 1.8))
    check_eq("R1 differs: printed as from $low to $high", figure(text), "from $1.50 to $1.80")
    check_in("R1 differs: with the finding in plain words",
             "For 1 of 2 sessions the transcripts at catalogue rates and the CLI's own charge differ.", text)
    check_in("R1 differs: and whose defect it is", "This is a defect of the factory's measurement, not a fact about the story.", text)
    check_in("R1 differs: and that no single figure is published", "no single figure is published", text)
    check_not_in("R1 differs: no sentence names a record the authoritative one", "authoritative", text)
    check_not_in("R1 differs: the old two-totals paragraph is gone", "Two totals", text)
    check_not_in("R1 differs: and its gap line", "Gap —", text)
    check("R1 the old functions are gone", not hasattr(RN, "record_gaps") and not hasattr(RN, "control_layer"))

    data, text = retro(None, [story_doc("s1", 2.0)])
    check_eq("R1 not cross-checked: the status", data["price"]["status"], "not_cross_checked")
    check_in("R1 not cross-checked: the figure is marked (a story with no journal: the chat is the only record, HF7-5)",
             "**Story price: $2.00 — single source (chat): nothing to cross-check against", text)
    check_in("R1 not cross-checked: and says it is one record", "It comes from one record", text)

    data, text = retro([jrow("r1", 1.0), jrow("r2", None)], [doc("r1", 1.0)])
    check_eq("R1 incomplete: the status", data["price"]["status"], "incomplete")
    check_in("R1 incomplete: what is known, as a floor", "**Story price: at least $1.00 — INCOMPLETE.**", text)
    check_in("R1 incomplete: and the reason, in plain words", "1 session is in neither record", text)
    check_eq("R1 incomplete: the story is incomplete and its figure is one figure (a floor)",
             (data["incomplete"], data["story"]["usd"]), (True, 1.0))
    check_in("R1 incomplete: it says the figure is a floor", "The figure is a floor, not a total.", text)


def r1_the_retro_computes_no_second_figure():
    """The mutation of a second computation: a figure printed from anything but the price function's
    own answer. The fixtures are one per status, each compared with a FRESH `task_price` call."""
    fixtures = {
        "agrees": ([conductor("c1", 0.5), jrow("r1", 1.0)], [doc("c1", 0.5), doc("r1", 1.0)]),
        "differs": ([conductor("c1", 0.5), jrow("r1", 1.0)], [doc("c1", 0.5), doc("r1", 1.3)]),
        "differs, the other way": ([jrow("r1", 2.0)], [doc("r1", 1.25)]),
        "one record": ([jrow("r1", 1.0)], []),
    }
    for name, (rows, docs) in fixtures.items():
        root, state, troot = project(rows, docs)
        try:
            data = RN.numbers(TASK, root=state, task_root=troot)
            text = RN.render(data)
            fresh = TP.task_price(root, TASK)
        finally:
            cleanup(root)
        expected = RN.price_words(fresh)
        check_eq(f"R1 ({name}): the printed figure is the price function's own, read fresh", figure(text), expected)
        check_eq(f"R1 ({name}): so are the price and the status in the facts",
                 (data["price"]["status"], data["price"]["price_low_usd"], data["price"]["price_high_usd"]),
                 (fresh["status"], fresh["price_low_usd"], fresh["price_high_usd"]))


def r1_one_call_per_retro():
    rows, docs = two_agreeing()
    root, state, troot = project(rows, docs)
    try:
        with Counting() as counting:
            data = RN.numbers(TASK, root=state, task_root=troot)
            RN.render(data)
        check_eq("R1 numbers() and render() ask the price function exactly once", counting.calls, 1)
    finally:
        cleanup(root)


def r1_the_table_by_agent_splits_the_price():
    rows = [conductor("c1", 0.5), jrow("r1", 1.0, role="qa-runner"), jrow("r2", 2.0, role="qa-automator"),
            jrow("t0", 0.25, role="", kind="ticket", dispatch="", stage="S0")]
    cases = {
        "agreeing records": [doc("c1", 0.5), doc("r1", 1.0), doc("r2", 2.0), doc("t0", 0.25)],
        "differing records": [doc("c1", 0.5), doc("r1", 1.4), doc("r2", 2.0), doc("t0", 0.25)],
    }
    for name, docs in cases.items():
        data, text = retro(rows, docs)
        price, agents = data["price"], data["price"]["by_agent"]
        low = sum((Decimal(repr(r["price_low_usd"])) for r in agents if r["price_low_usd"] is not None), Decimal("0"))
        high = sum((Decimal(repr(r["price_high_usd"])) for r in agents if r["price_high_usd"] is not None), Decimal("0"))
        check(f"R1 table ({name}): the rows' low prices add up to the story's low price",
              abs(low - Decimal(repr(price["price_low_usd"]))) < Decimal("1e-9"), f"{low} vs {price['price_low_usd']}")
        check(f"R1 table ({name}): and so do the high prices",
              abs(high - Decimal(repr(price["price_high_usd"]))) < Decimal("1e-9"), f"{high} vs {price['price_high_usd']}")
        check_in(f"R1 table ({name}): the equality is stated in words",
                 "the price column adds up to the story's price above, exactly", text)
        check_in(f"R1 table ({name}): the two records have a column each",
                 "| Agent | Sessions | Transcripts at catalogue rates | The CLI's own charge | Price |", text)
        check_in(f"R1 table ({name}): the story's own row closes it", "| **Story** | 4 |", text)
    check_in("R1 table: a row by agent carries its price, per row (qa-automator's 2.0)", "| qa-automator | 1 | $2.00 | $2.00 | $2.00 |", text)
    check_in("R1 table: a row whose records differ says so", "qa-runner (1 session differs)", retro(rows, cases["differing records"])[1])
    check_in("R1 table: and shows its price as a range", "| $1.40 | $1.00 | from $1.00 to $1.40 |",
             retro(rows, cases["differing records"])[1])
    agents = {r["agent"]: r for r in data["price"]["by_agent"]}
    check("R1 table: the S0 ticket call is the scout's row, not a row of its own",
          "qa-scout" in agents and "ticket" not in agents, str(sorted(agents)))
    check_eq("R1 table: the conductor's row stands apart", agents["conductor"]["a_usd"], 0.5)
    basis = data["orchestrator_share_basis"]
    check_eq("R1 the ticket call counts with the roles, in the share's role money (not the conductor's)",
             (basis["conductor_usd"], basis["role_usd"]), (0.5, 3.25))
    root, state, troot = project(rows, [])
    try:
        check_eq("R1 the retro's own session labels are the scout's for a ticket call",
                 sorted({r["label"] for r in RN.session_prices(TASK, RN.read_root(state)[0])}),
                 ["conductor", "qa-automator", "qa-runner", "qa-scout"])
    finally:
        cleanup(root)


def r1_edges():
    data, text = retro(None, [])
    check_in("edge zero records: the retro says no session has a record", "No session of this story has a record of its cost.", text)
    check_eq("edge zero records: nothing is priced, the story is incomplete", (data["story"]["usd"], data["incomplete"]), (None, True))
    data, text = retro([jrow("r1", 1.0)], [], config={"cost": {"rate_overrides": [
        {"model_id": MODEL, "rates": {"input": 4, "output": 20, "cache_read": 0.4, "cache_write_5m": 5, "cache_write_1h": 8}}]}})
    check_eq("edge rate_overrides: a story with no cost file has no model to price at the project's rate", data["price"]["rate_overrides"], [])
    data, text = retro([jrow("r1", 1.0)], [doc("r1", 1.0)], config={"cost": {"rate_overrides": [
        {"model_id": MODEL, "rates": {"input": 4, "output": 20, "cache_read": 0.4, "cache_write_5m": 5, "cache_write_1h": 8}}]}})
    check_eq("edge rate_overrides: the price is on the project's own rate (twice the list price here)", data["story"]["usd"], 2.0)
    check_in("edge rate_overrides: the retro names the model priced at the project's own rate",
             f"Priced at the project's own rates: {MODEL}.", text)
    check_eq("edge rate_overrides: the check still compares list prices, so the records agree", data["price"]["status"], "agrees")
    with Counting(raises=KeyError("boom")):
        data, text = retro([jrow("r1", 1.0)], [doc("r1", 1.0)])
    check_in("edge exception: the retro prints the exception class and that the price was not computed",
             "price not computed (KeyError)", text)
    check_eq("edge exception: nothing is priced, the story is incomplete, the retro went on",
             (data["story"]["usd"], data["incomplete"], data["price"]["status"]), (None, True, "error"))
    check("edge exception: the rest of the retro is still there", "| Stage | Dispatches" in text)
    falling =[jrow("r1", 0.78), jrow("r1", 9.51, resumed=True), jrow("r1", 3.39, resumed=True)]
    data, text = retro(falling, [doc("r1", 14.0)])
    check_eq("edge per-call journal: the session is one record and the price is the transcripts'",
             (data["price"]["status"], data["price"]["sessions"][0]["verdict"], data["story"]["usd"]), ("not_cross_checked", "one_record", 14.0))
    check_in("edge per-call journal: the retro says so", "The CLI's own charge is unknown for 1 session", text)
    data, text = retro(falling, [doc("r1", 14.0)], stories=None)
    check_eq("edge per-call journal: driver rows are unknown, not a number made of falling totals",
             (data["by_role"]["qa-runner"]["cost"], data["by_role"]["qa-runner"]["incomplete"]), (None, True))


# ------------------------------------------------------------------------- R2, B-223, the sessions

def r2_the_story_spend_is_every_session_the_price_names():
    rows, docs = cmp1_shape()
    root, state, troot = project(rows, docs)
    try:
        tagged = [d for d in docs if TASK in d["by_task"]]
        check_eq("R2 the fixture: 22 of the 35 cost files carry the ticket, 13 are collapsed `(no task)`",
                 (len(docs), len(tagged)), (35, 22))
        spend = RN.story_spend(TASK, state)
        check_eq("R2 story_spend: all 35 sessions are in, the 13 a tag filter dropped included", spend["sessions"], 35)
        check_eq("R2 story_spend: the money is the driver's $17.42, every session priced by both records",
                 round(spend["usd"], 4), 17.42)
        data = RN.numbers(TASK, root=state, task_root=troot)
        check_eq("R2 numbers(): the same 35 sessions and the same figure", (len(data["sessions"]), round(data["story"]["usd"], 4)), (35, 17.42))
        check_eq("R2 the price agrees on cmp1's proportions", data["price"]["status"], "agrees")
        check_eq("R2 every one of the 35 sessions has BOTH records: none is priced from one record (the 13 "
                 "collapsed cost files are read too)", data["price"]["one_record"], [])
        check_eq("R2 the files handed to the tables are the named sessions' too", len(RN.cost_files(TASK, state, troot)), 35)
        check_eq("R2 the tokens of a journal session are its WHOLE file's, the collapsed ones included (35 x 7)",
                 spend["tokens"], 245)
    finally:
        cleanup(root)
    # A session that only TOUCHED the ticket - a by_task tag with no evidence - is nobody's.
    rows2, docs2 = two_agreeing()
    touched = doc("operator", 1800.0, tag=TASK)
    data, text = retro(rows2, docs2 + [touched])
    check_eq("R2 a session that only carries the ticket in a by_task tag is not the story's (FR-24)",
             (data["story"]["sessions"], data["story"]["usd"]), (2, 1.5))
    check_not_in("R2 and its money is nowhere on the page", "1,800", text)
    data, text = retro(None, [touched])
    check_eq("R2 with no journal at all the tag binds nothing either", (data["story"]["sessions"], data["story"]["usd"]), (0, None))


# ------------------------------------------------------------- R5, no pinned money in the facts

def pinned_doc(sid="c1"):
    """The cost file of one conductor session: its own request ($0.50) and one role dispatch of
    $1.00 in an agent stream, at list price $1.50 in all. The file PINS 1.5x the list price, as the
    cmp1 copies do: the session total at 2.25 and the agent's cost at 1.5."""
    agent = {"agent": "qa-factory:qa-scout", "purpose": f"qa-scout S1 {TASK}", "task": TASK, "tokens": 5,
             "cost": 1.5, "started": "2026-09-30T05:00:00+00:00", "by_model": {}, "tools": {},
             "file": "agent-x.jsonl"}
    return doc(sid, 0.5, extra_requests=[request(sid, "r-agent", 1.0, stream="agent-x.jsonl")],
               agents=[agent], total_cost_usd=2.25)


def r5_no_money_in_the_facts_is_the_money_pinned_at_capture():
    """t-171 item 2: `basis["cost_files"]` and `dispatches` read the RE-PRICED document, like every
    printed money surface reads the price. The journal carries only a conductor row, so the retro
    has a journal (the share's basis exists) and no role row (the dispatches are read from the
    files' `agents[]`)."""
    data, text = retro([conductor("c1", 1.5)], [pinned_doc()])
    basis = data["orchestrator_share_basis"]
    check_eq("R5 the records agree", data["price"]["status"], "agrees")
    check_eq("R5 the cost files' amount is the list price (1.5), not the pinned 2.25",
             basis["cost_files"], {"usd": 1.5, "sessions": 1, "unpriced": 0, "of": 1})
    check_eq("R5 the dispatches are read from the files' agents, at the list price (1.0), not the pinned 1.5",
             [(d["role"], d["stage"], d["cost"]) for d in data["dispatches"]], [("qa-scout", "S1", 1.0)])
    check_eq("R5 so are the per-stage and per-role tables and the top list built from them",
             (data["by_stage"]["S1"]["cost"], data["by_role"]["qa-scout"]["cost"], data["top_dispatches"][0]["cost"]),
             (1.0, 1.0, 1.0))
    check_eq("R5 the sum of the cost files' amounts is the story's price when the two records agree",
             (basis["cost_files"]["usd"], data["story"]["usd"], data["price"]["price_low_usd"]), (1.5, 1.5, 1.5))
    # The records differ: the facts still carry the re-priced A amounts (the transcripts side); the
    # price block is what says the records differ.
    data, text = retro([conductor("c1", 1.2)], [pinned_doc()])
    check_eq("R5 differs: the price block says so", data["price"]["status"], "differs")
    check_eq("R5 differs: the cost files' amount is still the re-priced A (1.5), not the pinned 2.25 and not B's 1.2",
             data["orchestrator_share_basis"]["cost_files"]["usd"], 1.5)
    check_eq("R5 differs: and the dispatch is the re-priced 1.0",
             [d["cost"] for d in data["dispatches"]], [1.0])
    # A file that pins nothing usable is unchanged by the re-pricing: a cost file with no `by_task`
    # entry and no journal row is unbound, not counted, not an error.
    data, text = retro([conductor("c1", 1.5)], [pinned_doc(), doc("stray", 40.0)])
    check_eq("R5 an unbound cost file is not counted (no journal row, no evidence)",
             (data["orchestrator_share_basis"]["cost_files"], data["sessions"]),
             ({"usd": 1.5, "sessions": 1, "unpriced": 0, "of": 1}, ["c1"]))


# --------------------------------------------------------------------------------- R3, the ceiling

def ceiling(rows, docs, cap, extra_config=None, marks=(0.5, 0.8), pipeline=None):
    root, state, troot = project(rows, docs, config=dict({"budget": {"story_usd": cap, "warn_at": list(marks)}},
                                                          **(extra_config or {})))
    try:
        if pipeline is not None:
            (troot / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        return SB.check(TASK, state, troot)
    finally:
        cleanup(root)


def r3_the_ceiling_polices_the_clis_charge_where_known():
    # A doubled in the transcripts (a sidechain request counted in two streams), B known: the ceiling
    # uses B. The larger of the two ($12.00) would stop the story on the factory's own defect.
    doubled = ceiling([jrow("r1", 6.0)], [doc("r1", [6.0, 6.0])], 10.0)
    check_eq("R3 A doubled, B known: the ceiling's figure is B", doubled["spend"]["usd"], 6.0)
    check_eq("R3 A doubled, B known: a double count in A cannot stop a story", doubled["stop"], False)
    check_eq("R3 A doubled, B known: the ratio is B's ($6.00 of $10.00)", doubled["ratio"], 0.6)
    check_in("R3 the notice says the figure is disputed", "The figure is disputed: for 1 session", doubled["notice"])
    check_in("R3 and by how much, and what the transcripts would make it",
             "by $6.00 in all. The ceiling is compared against the CLI's charge; the transcripts would make it $12.00.", doubled["notice"])
    check_eq("R3 the records are in the spend the caller reads", (doubled["spend"]["ceiling"]["disputed"],
                                                                 doubled["spend"]["ceiling"]["by_cli"]), (1, 1))
    # A smaller than B: still B (never the smaller either): $6.00 charged, transcripts say $4.00.
    smaller = ceiling([jrow("r1", 6.0)], [doc("r1", 4.0)], 10.0)
    check_eq("R3 A smaller than B: B, not the smaller figure", smaller["spend"]["usd"], 6.0)
    # A only (one record, no journal): the transcripts are the only figure, and they can stop.
    only_a = ceiling(None, [story_doc("s1", 12.0)], 10.0)
    check_eq("R3 one record (an orchestrator-mode story): A is used, and it stops at the ceiling",
             (only_a["spend"]["usd"], only_a["stop"]), (12.0, True))
    check_not_in("R3 nothing is called disputed when there is no second record", "disputed", only_a["notice"])
    # A per-call journal (driver3's shape): every session one record; A is used and the notice says so.
    per_call = ceiling([jrow("r1", 0.78), jrow("r1", 9.51, resumed=True), jrow("r1", 3.39, resumed=True)],
                       [doc("r1", 14.0)], 10.0)
    check_eq("R3 a per-call journal: the ceiling uses the transcripts' figure", (per_call["spend"]["usd"], per_call["stop"]), (14.0, True))
    check_in("R3 and says the CLI's charge is unknown for it", "For 1 session the CLI's own charge is unknown, so the transcripts' price is used for them.",
             per_call["notice"])
    # Known to neither: incomplete, today's wording, and zero records never stop.
    neither = ceiling([jrow("r1", 6.0), jrow("r2", None)], [doc("r1", 6.0)], 10.0)
    check_eq("R3 a session known to neither: incomplete", neither["spend"]["incomplete"], True)
    check_in("R3 and the notice keeps today's 'a floor' wording", "(a floor: some role usage was not captured)", neither["notice"])
    none = ceiling([jrow("r1", None)], [], 10.0)
    check_eq("R3 zero records: incomplete, no figure, the ceiling does not stop", (none["spend"]["usd"], none["spend"]["incomplete"], none["stop"]),
             (None, True, False))
    check_eq("R3 zero records with no journal at all: nothing to police", ceiling(None, [], 10.0)["stop"], False)


def r3_the_boundary_and_the_disputed_figure():
    at = ceiling([jrow("r1", 10.0)], [doc("r1", 10.0)], 10.0)
    check_eq("R3 at the limit: the ratio is exactly 1 (no float noise from the sum)", at["ratio"], 1.0)
    check_eq("R3 at the limit: today's rule stands - a ceiling REACHED stops and asks", (at["level"], at["stop"]), (1.0, True))
    over = ceiling([jrow("r1", 10.01)], [doc("r1", 10.01)], 10.0)
    check_eq("R3 one cent over: stops", over["stop"], True)
    under = ceiling([jrow("r1", 9.99)], [doc("r1", 9.99)], 10.0)
    check_eq("R3 one cent under: warns, does not stop", (under["stop"], under["level"]), (False, 0.8))
    thirds = ceiling([jrow("a", 3.33), jrow("b", 3.33), jrow("c", 3.34)], [doc("a", 3.33), doc("b", 3.33), doc("c", 3.34)], 10.0)
    check_eq("R3 three figures adding to exactly the ceiling are exactly the ceiling (summed in Decimal)", thirds["ratio"], 1.0)
    disputed = ceiling([jrow("r1", 10.0)], [doc("r1", 12.0)], 10.0)
    check_eq("R3 a disputed figure at the limit: the CLI's charge is what was compared", (disputed["spend"]["usd"], disputed["stop"]), (10.0, True))
    check_in("R3 the stop says the figure is disputed and that the transcripts would differ",
             "the transcripts would make it $12.00.", disputed["notice"])
    check_in("R3 and still names the call that records the person's word", "--block \"story budget\"", disputed["notice"])
    passed = ceiling([jrow("r1", 10.0)], [doc("r1", 12.0)], 10.0,
                     pipeline={"stage_overrides": [{"stage": "S5", "match": "story budget", "decision": "go on"}]})
    check_eq("R3 a person's word passes a disputed ceiling too", passed["stop"], False)
    # A token ceiling is unchanged in kind and still bites with no price at all.
    root, state, troot = project([jrow("r1", None)], [doc("r1", 1.0, total_cost_usd=None)],
                                 config={"budget": {"story_tokens": 5, "warn_at": [0.5]}})
    try:
        tokens = SB.check(TASK, state, troot)
        check_eq("R3 a token ceiling works on the whole tokens of a journal session", (tokens["spend"]["tokens"], tokens["stop"]), (7, True))
    finally:
        cleanup(root)


def r3_one_call_and_never_a_stop_on_an_exception():
    root, state, troot = project([jrow("r1", 6.0)], [doc("r1", 6.0)],
                                 config={"budget": {"story_usd": 10.0, "warn_at": [0.5]}})
    try:
        with Counting() as counting:
            SB.check(TASK, state, troot)
        check_eq("R3 the ceiling reads the price function exactly once", counting.calls, 1)
        SB.marker_path(TASK, state).unlink(missing_ok=True)
        with Counting(raises=RuntimeError("boom")):
            state_result = SB.check(TASK, state, troot)
        check_eq("R3 an exception inside the price function never stops a story (today's rule)",
                 (state_result["stop"], state_result["notice"]), (False, ""))
        SB.marker_path(TASK, state).unlink(missing_ok=True)
        real = RN.all_cost_files
        RN.all_cost_files = lambda *a, **k: (_ for _ in ()).throw(OSError("unreadable"))
        try:
            broken = SB.check(TASK, state, troot)
        finally:
            RN.all_cost_files = real
        check_eq("R3 nor does an unreadable cost folder", broken["stop"], False)
    finally:
        cleanup(root)


# ----------------------------------------------------------------------------- R4, the cache rate

def r4_the_cache_read_rate_is_an_exact_match():
    entries = [e for e in CC.load_catalogue()["entries"] if isinstance(e, dict)]
    check("R4 the catalogue has the shape the critic measured (opus-5 at $0.5 and opus-5-5 at $0.2)",
          RN.cache_read_rate("claude-opus-5") == 0.5 and RN.cache_read_rate("claude-opus-5-5") == 0.2)
    wrong, unpriced = [], []
    for entry in entries:
        for name in [entry["model_id"], *(entry.get("aliases") or [])]:
            rate = entry["rates"].get("cache_read")
            want = float(rate) if isinstance(rate, (int, float)) and rate > 0 else None
            if want is None:
                unpriced.append(name)
            if RN.cache_read_rate(name) != want:
                wrong.append((name, RN.cache_read_rate(name), want))
    check_eq("R4 every catalogue id and alias reads its own entry's rate, and an entry with no cache-read rate reads None "
             "(unknown), never 0.3", wrong, [])
    check("R4 the catalogue has entries with no cache-read rate (the judge ones): the control that makes the line above bite",
          len(unpriced) >= 1, str(unpriced))
    # t-182 F4 (FR-41): no model, or a model no entry names, has NO rate. It used to be the first Sonnet
    # entry's ($0.3 for a story run on claude-sonnet-5-5, whose rate is $0.2): another model's rate.
    sonnet_first = next(float(e["rates"]["cache_read"]) for e in entries if "sonnet" in e["model_id"].lower())
    check("R4 the control: the first Sonnet entry's rate is a real number and NOT the rate of the model the story ran on "
          "(claude-sonnet-5-5)", sonnet_first != RN.cache_read_rate("claude-sonnet-5-5"), str((sonnet_first, RN.cache_read_rate("claude-sonnet-5-5"))))
    check_eq("R4 no model at all: no rate, never the first Sonnet entry's (the model-less fallback of t-182 F4)",
             RN.cache_read_rate(""), None)
    check_eq("R4 a prefix of an id is no match: no rate, not the first entry that contains it", RN.cache_read_rate("claude-opus"), None)
    check_eq("R4 nor is an id that merely CONTAINS a catalogue id: no rate", RN.cache_read_rate("claude-opus-5-5-preview"), None)
    check_eq("R4 the match ignores case, not the id", (RN.cache_read_rate("CLAUDE-OPUS-5-5"), RN.cache_read_rate("claude-opus-5-")), (0.2, None))
    check_eq("R4 a person's own rate for the model replaces the catalogue's (P18): $0.9 for claude-sonnet-5-5",
             RN.cache_read_rate("claude-sonnet-5-5", {"rate_overrides": [{"model_id": "claude-sonnet-5-5", "rates": {"cache_read": 0.9}}]}), 0.9)
    check_eq("R4 ... and a model only the person's table knows has that rate", RN.cache_read_rate(
        "vendor-x", {"rate_overrides": [{"model_id": "vendor-x", "aliases": ["vx"], "rates": {"cache_read": 0.4}}]}), 0.4)
    check_eq("R4 ... but an override with no cache-read rate is an unknown, not the catalogue's number",
             RN.cache_read_rate("claude-sonnet-5-5", {"rate_overrides": [{"model_id": "claude-sonnet-5-5", "rates": {"input": 1}}]}), None)


# ----------------------------------------------------- t-182: the true price, the critic's findings on it

OVR2 = {"cost": {"rate_overrides": [{"model_id": MODEL, "rates": {"input": 4, "output": 20, "cache_read": 0.4,
                                                                     "cache_write_5m": 5, "cache_write_1h": 8}}]}}   # twice the list price


def printed_columns(text):
    """{column: (sum of the printed rows' cents, the printed story row's cents)} of the retro's table by agent, read
    from the PRINTED text the way a person adds it up: a range's low and high end are columns of their own."""
    lines = text.splitlines()
    i = next(k for k, line in enumerate(lines) if line.startswith("| Agent | Sessions"))
    j = next(k for k in range(i, len(lines)) if lines[k].startswith("| **Story**"))

    def cells(line):
        return [c.strip() for c in line.strip().strip("|").split("|")]

    def ends(cell):
        found = [int(Decimal(x.replace(",", "")) * 100) for x in re.findall(r"\$([\d,]+\.\d\d)", cell)]
        return (found[0], found[-1]) if found else (0, 0)
    body, total = lines[i + 2:j], cells(lines[j])
    return {"transcripts": (sum(ends(cells(l)[2])[0] for l in body), ends(total[2])[0]),
            "cli": (sum(ends(cells(l)[3])[0] for l in body), ends(total[3])[0]),
            "low": (sum(ends(cells(l)[4])[0] for l in body), ends(total[4])[0]),
            "high": (sum(ends(cells(l)[4])[1] for l in body), ends(total[4])[1])}


def t182_f1_the_driver_money_is_on_the_rate_base_of_the_price():
    rows = [conductor("c1", 0.5), jrow("r1", 0.4), jrow("r1", 1.0, resumed=True)]
    docs = [doc("c1", 0.5), doc("r1", 1.0)]
    data, text = retro(rows, docs, config=OVR2)
    check_eq("T182 F1 the price is at the project's rates: twice the list price ($3.00), and the records agree at list",
             (data["story"]["usd"], data["price"]["status"]), (3.0, "agrees"))
    basis = data["orchestrator_share_basis"]
    check_eq("T182 F1 the share's money is on the same base: the conductor's $1.00 of $3.00 (was $0.50 of $1.50 under $3.00)",
             (basis["conductor_usd"], basis["total_usd"], basis["share_percent"], basis["on_project_rates"], basis["unscaled"]),
             (1.0, 3.0, 33.3, True, []))
    check_in("T182 F1 the printed share line says so", "the conductor's 1 session cost $1.00 of $3.00.", text)
    check_in("T182 F1 ... and says which rates every amount is on",
             "Every amount is the driver's own charge put on the project's own rates, session by session: the same rates as the "
             "story's price.", text)
    check_eq("T182 F1 the money handed back is on it too (the resumed $0.60 at 2x is $1.20)", data["handed_back_to_roles"]["usd"], 1.2)
    check_in("T182 F1 ... and its line", "work the conductor handed back to roles: $1.20 over 1 resumed role session.**", text)
    check_eq("T182 F1 a dispatch's cost is on it: the role's $1.00 (rows $0.40 + $0.60) is $2.00 by role and by stage, and "
             "the dearest row ($0.60) is $1.20 in the top list",
             (data["by_role"]["qa-runner"]["cost"], data["by_stage"]["S5"]["cost"], data["top_dispatches"][0]["cost"]), (2.0, 2.0, 1.2))
    check_eq("T182 F1 the per-stage split of the orchestrator adds up to the conductor's money on the same base",
             data["orchestrator_by_stage"], {"S5": 1.0})
    check_in("T182 F1 the rates line says the driver's amounts below are on the same rates",
             "the driver's own amounts below are put on the same rates", text)
    data0, text0 = retro(rows, docs)
    basis0 = data0["orchestrator_share_basis"]
    check_eq("T182 F1 control, NO project rates: every figure is what it was ($0.50 of $1.50, handed back $0.60)",
             (basis0["conductor_usd"], basis0["total_usd"], basis0["on_project_rates"], data0["handed_back_to_roles"]["usd"]),
             (0.5, 1.5, False, 0.6))
    check_in("T182 F1 control: the share line is the old one", "the conductor's 1 session cost $0.50 of $1.50.", text0)
    check_not_in("T182 F1 control: and says nothing about project rates on the driver's money", "put on the project's own rates", text0)
    # the three-surface control's third surface: the ceiling polices the price's base
    stop = ceiling(rows, docs, 2.0, extra_config=OVR2)
    check_eq("T182 F1 the ceiling at $2.00 STOPS the story at $3.00 (list-price B read $1.50 of $2.00 and said nothing to do)",
             (stop["spend"]["usd"], stop["stop"], stop["ratio"]), (3.0, True, 1.5))
    check_in("T182 F1 ... and prints the price's figure", "reached its ceiling — $3.00 of $2.00", stop["notice"])
    # edge (i): a session whose list price is $0 cannot be scaled: its charge stands, and the lines say so
    priced = {"rate_overrides": ["m"], "totals": {"a": 1.0, "a_price": 4.0},
              "sessions": [{"session": "s1", "a_usd": 1.0, "a_price_usd": 2.0, "b_usd": 1.0},
                           {"session": "z1", "a_usd": 0.0, "a_price_usd": 2.0, "b_usd": 0.5}]}
    base = RN.price_base(priced)
    check_eq("T182 F1 edge (i): s1 has factor 2, z1 (list price $0) has none and is UNSCALED; the price is at project rates",
             base, {"factors": {"s1": 2.0}, "unscaled": ["z1"], "project_rates": True})
    shared = RN.journal_share(TASK, ["s1", "z1"], {"s1": [conductor("s1", 1.0)], "z1": [jrow("z1", 0.5)]}, (), "", base)
    check_eq("T182 F1 edge (i): the share is s1's 1.0 x 2 plus z1's 0.5 as it stands, and z1 is named",
             (shared["total_usd"], shared["conductor_usd"], shared["unscaled"]), (2.5, 2.0, ["z1"]))
    check_in("T182 F1 edge (i): the line counts it and says it stays at the CLI's own list-price charge",
             "1 session could not be put on them (the transcripts at the catalogue's rates are $0 or unknown), so it stays at "
             "the CLI's own list-price charge.", " ".join(RN.share_lines(shared, shared["share_percent"])))
    check_eq("T182 F1 no project rates: no factors, nothing unscaled, whatever the rows say",
             RN.price_base({"totals": {"a": 1.0, "a_price": 1.0}, "sessions": priced["sessions"]}),
             {"factors": {}, "unscaled": [], "project_rates": False})


def t182_f2_the_wording_under_the_project_rates():
    rows, docs = two_agreeing()
    data, text = retro(rows, docs, config=OVR2)
    check_in("T182 F2 the figure is the project's: $3.00", "**Story price: $3.00.**", text)
    check_not_in("T182 F2 never 'Two records agree on it' beside the override figure", "Two records agree on it", text)
    check_not_in("T182 F2 never 'the catalogue's list prices' as the rates of that figure", "Rates: the catalogue's list prices", text)
    check_in("T182 F2 it says the project's own rates were applied",
             "The project's own rates were applied to it, so this is the price at the person's rates and not at the catalogue's "
             "list prices.", text)
    check_in("T182 F2 ... that at the catalogue's rates the records agree, on THEIR figure ($1.50), within the tolerance in words",
             "At the catalogue's list rates the two records, the transcripts and the CLI's own charge, agree on $1.50, session "
             "by session, within a tenth of a cent each.", text)
    check_in("T182 F2 ... names the project's price table and the model", f"Priced at the project's own rates: {MODEL}.", text)
    check_in("T182 F2 ... and the rates line names the project's table over the catalogue's",
             "Rates: the project's own price table where it has a rate, the catalogue's list prices (revision", text)
    data, text = retro(None, [story_doc("s1", 2.0)], config=OVR2)
    check_in("T182 F2 edge (vii): not cross-checked under the project's rates names the PROJECT's rates, not the catalogue's",
             "It comes from one record, the transcripts priced at the project's own rates: nothing could be compared", text)
    check_not_in("T182 F2 edge (vii): ... and not the catalogue's list rates", "priced at the catalogue's list rates", text)
    data, text = retro([conductor("c1", 0.5), jrow("r1", 1.0)], [doc("c1", 0.5), doc("r1", 1.3)], config=OVR2)
    check_in("T182 F2 differs under project rates: both ends are said to be at them",
             "both ends at the project's own rates (the CLI's charge is put on them session by session)", text)
    data, text = retro(*two_agreeing())
    check_in("T182 F2 control, no project rates: today's sentence, byte for byte (tolerance from the constant, same words)",
             "Two records agree on it: the transcripts priced at the catalogue's list rates and the CLI's own charge, session by "
             "session, within a tenth of a cent each.", text)
    check_in("T182 F2 control: and today's rates line", "Rates: the catalogue's list prices, revision ", text)


def t182_f6_the_retros_tolerance_is_the_constants():
    saved = TP.TOLERANCE_USD
    TP.TOLERANCE_USD = Decimal("0.005")
    try:
        data, text = retro(*two_agreeing())
    finally:
        TP.TOLERANCE_USD = saved
    check_in("T182 F6 the retro's 'a tenth of a cent' is derived from TP.TOLERANCE_USD: at $0.005 it says half a cent",
             "within half a cent each", text)
    check_not_in("T182 F6 ... and no hard-coded 'a tenth of a cent' is left", "a tenth of a cent", text)


def t182_f3_the_printed_cents_add_up():
    thirds = [jrow("r1", 0.3333, role="qa-runner"), jrow("r2", 0.3333, role="qa-automator"), jrow("r3", 0.3333, role="qa-scout")]
    data, text = retro(thirds, [doc("r1", 0.3333), doc("r2", 0.3333), doc("r3", 0.3333)])
    cols = printed_columns(text)
    check_eq("T182 F3 three rows of a third: every printed column adds up to the printed story figure ($1.00 = 100 cents; "
             "plain rounding printed 33 + 33 + 33 = 99)", cols, {k: (100, 100) for k in ("transcripts", "cli", "low", "high")})
    check_in("T182 F3 ... and the heading's 'adds up ... exactly' holds on the page", "the price column adds up to the story's price above, exactly", text)
    check_in("T182 F3 ... the tie goes to the first row, deterministically (34, 33, 33)", "| qa-automator | 1 | $0.34 | $0.34 | $0.34 |", text)
    one = retro([jrow("r1", 0.3333, role="qa-runner")], [doc("r1", 0.3333)])[1]
    check_eq("T182 F3 edge: ONE row: the row equals the total", printed_columns(one), {k: (33, 33) for k in ("transcripts", "cli", "low", "high")})
    ranged = retro(thirds, [doc("r1", 0.3), doc("r2", 0.3333), doc("r3", 0.3333)])[1]
    cols = printed_columns(ranged)
    check_eq("T182 F3 a range: low and high are rounded on their own, each adding up to its own end (97 and 100 cents)",
             (cols["low"], cols["high"]), ((97, 97), (100, 100)))
    check_in("T182 F3 ... the story row prints the range", "| **Story** | 3 | $0.97 | $1.00 | from $0.97 to $1.00 |", ranged)
    check_in("T182 F3 ... a row whose two ends are equal is ONE figure (the lock keeps equal ends equal)", "| qa-scout | 1 | $0.33 | $0.33 | $0.33 |", ranged)
    big = retro([jrow(f"r{i}", 1234.5678, role=f"qa-role-{i}") for i in range(3)],
                [doc(f"r{i}", 1234.5678) for i in range(3)])[1]
    check_eq("T182 F3 thousands: three rows of $1,234.5678 add up at the cent to the story's $3,703.70",
             printed_columns(big), {k: (370370, 370370) for k in ("transcripts", "cli", "low", "high")})


def t182_f4_the_rules_line_is_priced_at_the_model_the_story_ran_on():
    rows, docs = two_agreeing()
    data, text = retro(rows, docs)
    rules = data["rules_weight"]
    check_eq("T182 F4 the model is the story's own (claude-sonnet-5-5) and the rate is ITS rate ($0.2), not the first Sonnet entry's",
             (rules["model"], rules["rate_per_mtok"], rules["models"]), (MODEL, CC_rate(MODEL), 1))
    check("T182 F4 ... which is not the model-less default ($0.3)", rules["rate_per_mtok"] != 0.3, str(rules["rate_per_mtok"]))
    check_in("T182 F4 the line names the model and its rate", f"at ${CC_rate(MODEL)}/Mtok, the cache-read rate of {MODEL}. By layer:", text)
    # several models: the dominant one by cache-read tokens, named, with how many there are
    two = doc("r1", 1.0, by_model={MODEL: {"cache_read": 10}, "claude-opus-5-5": {"cache_read": 900}})
    data, text = retro([conductor("c1", 0.5), jrow("r1", 1.0)], [doc("c1", 0.5), two])
    check_eq("T182 F4 two models: the dominant by cache-read tokens (claude-opus-5-5, $0.2 too) and the count",
             (data["rules_weight"]["model"], data["rules_weight"]["models"]), ("claude-opus-5-5", 2))
    check_in("T182 F4 ... and the line says which and why", "the cache-read rate of claude-opus-5-5 (the model with the most cache-read "
             "tokens of the 2 in the story's cost files)", text)
    # no model in any cost file: the rate is unknown, said, never another model's (FR-41)
    bare = doc("r1", 1.0)
    bare["by_model"] = {}
    bare["requests"] = [dict(r, model_id="") for r in bare["requests"]]
    data, text = retro([jrow("r1", 1.0)], [bare])
    check_eq("T182 F4 edge (iv): no model in the cost files: the rate is unknown (None), no dollars", (data["rules_weight"]["rate_per_mtok"],
             data["rules_weight"]["usd"], data["rules_weight"]["by_layer"]), (None, None, None))
    check_in("T182 F4 edge (iv): the line says so, with the facts it does have", "**The rules' cost is not known**", text)
    check_in("T182 F4 edge (iv): and why", "no model is named in the story's cost files, so there is no cache-read rate to price it at", text)
    check_not_in("T182 F4 edge (iv): never 'The rules cost $...' on a rate nobody knows", "The rules cost", text)
    # a model the catalogue does not name: unknown too, never another model's rate
    alien = doc("r1", 1.0, by_model={"vendor-x": {"cache_read": 5}})
    data, text = retro([jrow("r1", 1.0)], [alien])
    check_in("T182 F4 a model with no rate anywhere is unknown, the model is named", "the model 'vendor-x' has no cache-read rate", text)
    # the pipeline's model stands in only when no cost file names one
    root, state, troot = project([jrow("r1", 1.0)], [bare])
    try:
        (troot / "pipeline.json").write_text(json.dumps({"models": ["claude-opus-5-5"]}), encoding="utf-8")
        data = RN.numbers(TASK, root=state, task_root=troot)
    finally:
        cleanup(root)
    check_eq("T182 F4 the pipeline's model is the fallback when no cost file names one", (data["rules_weight"]["model"], data["rules_weight"]["rate_per_mtok"]),
             ("claude-opus-5-5", 0.2))
    over = RN.rules_weight([{"role": "qa-runner", "requests": 10}], MODEL, {"rate_overrides": [{"model_id": MODEL, "rates": {"cache_read": 0.9}}]})
    check_eq("T182 F4 a person's own cache-read rate for the model is the rate of the line (P18)", (over["rate_per_mtok"], over["rate_source"]), (0.9, "project"))
    data, text = retro(rows, docs, config={"cost": {"rate_overrides": [{"model_id": MODEL, "rates": {"cache_read": 0.9}}]}})
    check_in("T182 F4 ... and the line says whose rate it is", f"at $0.9/Mtok, the project's own cache-read rate of {MODEL}.", text.replace(" By layer:", "."))


def CC_rate(model):
    return next(float(e["rates"]["cache_read"]) for e in CC.load_catalogue()["entries"]
                if isinstance(e, dict) and e.get("model_id") == model)


def main():
    r1_the_price_line_says_what_the_price_function_says()
    r1_the_retro_computes_no_second_figure()
    r1_one_call_per_retro()
    r1_the_table_by_agent_splits_the_price()
    r1_edges()
    r2_the_story_spend_is_every_session_the_price_names()
    r5_no_money_in_the_facts_is_the_money_pinned_at_capture()
    r3_the_ceiling_polices_the_clis_charge_where_known()
    r3_the_boundary_and_the_disputed_figure()
    r3_one_call_and_never_a_stop_on_an_exception()
    r4_the_cache_read_rate_is_an_exact_match()
    t182_f1_the_driver_money_is_on_the_rate_base_of_the_price()
    t182_f2_the_wording_under_the_project_rates()
    t182_f6_the_retros_tolerance_is_the_constants()
    t182_f3_the_printed_cents_add_up()
    t182_f4_the_rules_line_is_priced_at_the_model_the_story_ran_on()
    finish("test_retro_task_price")


if __name__ == "__main__":
    main()
