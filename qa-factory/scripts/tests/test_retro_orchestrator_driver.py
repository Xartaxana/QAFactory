#!/usr/bin/env python3
"""On a driver run the retro's orchestrator share is the conductor's share of the driver's record.

TP1-13797 (cmp1) ran on the driver: every session is a `claude -p` of its own, the cost
capture sees one collapsed "(no task)" row per file and no orchestrator stream, so the retro
either printed nothing or fell to the control layer, which adds every journal row's running total
(72.6 %, $39.76). The driver's own journal is the record of what each session cost: 35 sessions,
$17.42, 17 conductor sessions with $3.07, a share of 17.6 %. This file holds that reading and its
edges: a ticket session in the denominator only, the journal's share ahead of every other branch,
the per-stage split from the journal, the finding divided by the share's own base, and the words a
person reads.

The follow-up after the critic (t-138) holds ONE SOURCE PER RATIO: the share is published only when
every session of the story has a driver record, priced by the reader's root rule (a falling session
of ANOTHER story makes every multi-row session unknown); a session the driver's record cannot price
is unknown, never priced by a cost file (they are priced by another table, B-225), and a cost file
of $0 with zero usage is never a price. A session the reader counted under another story is left
out and named. The owner's decision on the control layer (30.09): choosing a role and handing it
something to redo is the conductor's management, the extra work the role then does is the ROLE's
cost, so the money of resumed roles is its own line, priced by per-row increments. Synthetic story
roots only; the shapes follow cmp1.

t-170 (true-price piece Q6): the story's money is `task_price`'s one answer, its sessions are the
ones it names (not the ones that carry the ticket in a `by_task` tag: B-223), the S0 ticket call is
the scout's, the old control-layer function and its paragraph are gone, and the by_role / by_stage /
top-dispatch / rework tables sum row INCREMENTS of a running total, never raw row totals. The
retro's price lines have their own file, test_retro_task_price.py.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     temp_dir)

sys.path.insert(0, str(SCRIPTS))
import cost_capture as CC  # noqa: E402
import driver_journal as DJ  # noqa: E402
import retro_numbers as RN  # noqa: E402

TASK = "QA-DRV-1"
PIPELINE = {"stages": {
    "S1": {"status": "done", "started": "2026-09-23T10:00:00Z", "finished": "2026-09-23T11:00:00Z"},
    "S5": {"status": "done", "started": "2026-09-23T11:00:00Z", "finished": "2026-09-23T12:00:00Z"}}}


def row(sid, kind="role", total=1.0, stage="S1", resumed=False, **extra):
    """One journal row. A conductor row carries no role and no dispatch, as the driver writes it."""
    base = {"kind": kind, "session_id": sid, "stage": stage, "resumed": resumed,
            "num_turns": 3, "total_cost_usd": total, "ts": "2026-09-23T10:30:00+00:00"}
    if kind == "role":
        base.update(role="qa-automator", dispatch=f"{stage}-qa-automator-1")
    elif kind == "conductor":
        base.update(role="", dispatch="")
    base.update(extra)
    return base


def cost_file(sid, total, task=TASK, **extra):
    """A session cost file: the whole session's amount, tagged with a ticket or collapsed. It holds
    no request ledger, so the price function has no record A for it (the file's own `total_cost_usd`
    is pinned money that nothing but `cost_file_amount` reads)."""
    data = {"session_id": sid, "total_cost_usd": total, "agents": [],
            "by_task": {task: {"tokens": 10, "requests": 1, "cost": total}}}
    data.update(extra)
    return data


def usage_of(dollars):
    """The usage of a request that costs `dollars` at the catalogue's claude-sonnet-5-5 rate ($10 per
    million output tokens): 100000 output tokens are $1.00."""
    return {"requests": 1, "input": 0, "output": round(dollars * 100000), "cache_read": 0,
            "cache_write_5m": 0, "cache_write_1h": 0}


def request_row(sid, rid, stream, dollars, activity="unclassified", task="(no task)", pinned=None):
    """One request row of a cost file. `pinned` is the file's own stored price of it (bogus 999 unless
    given): a reader that takes the file's money instead of re-pricing the usage shows at once."""
    return {"request_key": f"anthropic:{sid}:{rid}:{stream}", "provider": "anthropic", "session_id": sid,
            "request_id": rid, "stream": stream, "task": task, "model_id": "claude-sonnet-5-5",
            "timestamp": "2026-09-23T10:30:00+00:00", "activity_id": activity, "usage": usage_of(dollars),
            "valuation": {"pricing_coverage": "complete", "subtotal_usd": str(pinned if pinned is not None else 999),
                          "missing_rate_categories": [], "tariff_confirmation": "unconfirmed",
                          "rate_provenance": {"kind": "legacy_project_override"}}}


def priced_file(sid, total, task=TASK, **extra):
    """A cost file whose one request costs `total` at the catalogue's rate (record A = `total`), as a
    driver session's file does, tagged with a ticket or collapsed `(no task)`."""
    data = {"session_id": sid, "total_cost_usd": total, "agents": [],
            "by_task": {task: {"tokens": 7, "requests": 1, "cost": total}},
            "requests": [request_row(sid, "r1", "orchestrator", total)]}
    data.update(extra)
    return data


def write_journal(troot, rows=None, raw=None):
    (troot / "state").mkdir(parents=True, exist_ok=True)
    text = raw if raw is not None else "\n".join(json.dumps(r) for r in rows) + "\n"
    (troot / "state" / "driver-runs.jsonl").write_text(text, encoding="utf-8")


def build(rows=None, costs=(), raw=None, config=None, pipeline=None, stories=None, state_name="qa-factory"):
    """(root, state, troot): a temp project with a story, its journal (rows, or `raw` text), the
    journals of other stories (`stories`: task -> rows) and its cost files. `rows=None` and
    `raw=None` writes no journal file at all."""
    root = temp_dir("qa-retro-driver-")
    state = root / state_name
    troot = state / "artifacts" / TASK
    (state / "state" / "cost").mkdir(parents=True)
    (troot / "state").mkdir(parents=True)
    (state / "config.json").write_text(json.dumps(config or {}), encoding="utf-8")
    (troot / "pipeline.json").write_text(json.dumps(pipeline or {}), encoding="utf-8")
    for data in costs:
        (state / "state" / "cost" / f"{data['session_id']}.json").write_text(
            json.dumps(data), encoding="utf-8")
    if raw is not None or rows is not None:
        write_journal(troot, rows, raw)
    for task, task_rows in (stories or {}).items():
        write_journal(state / "artifacts" / task, task_rows)
    return root, state, troot


def numbers(rows=None, costs=(), **kw):
    root, state, troot = build(rows, costs, **kw)
    try:
        return RN.numbers(TASK, root=state, task_root=troot)
    finally:
        cleanup(root)


def cmp1_rows():
    """The proportions of cmp1: 35 sessions and $17.42, of which 17 conductor sessions and $3.07
    (8 in S1 at $0.18, 8 in S4 at $0.18, one in S5 at $0.19), 17 role sessions launched at $0.40
    and resumed to a running total of $0.80, and one S0 ticket call of $0.75."""
    rows = []
    for i in range(8):
        rows.append(row(f"c-s1-{i}", "conductor", 0.18, "S1"))
        rows.append(row(f"c-s4-{i}", "conductor", 0.18, "S4"))
    rows.append(row("c-s5-0", "conductor", 0.19, "S5"))
    for i in range(17):
        rows.append(row(f"r-{i}", total=0.4, stage="S5"))
        rows.append(row(f"r-{i}", total=0.8, stage="S5", resumed=True))
    rows.append(row("t-0", "ticket", 0.75, "S0"))
    return rows


def cmp1_costs():
    """A cost file for every session at the session's own price (what the CLI charged, so the two
    records agree); 22 of them name the ticket, the 13 others are the collapsed "(no task)" files
    a ticket-tag filter dropped (B-223)."""
    last = {}
    for r in cmp1_rows():
        last[r["session_id"]] = r["total_cost_usd"]
    return [priced_file(sid, last[sid], task=TASK if i < 22 else "(no task)") for i, sid in enumerate(sorted(last))]


def orchestrator_session(usd_orch):
    """A cost file of the session-shaped kind the orchestrator stream produces (session id s1),
    so that `orchestrator_totals / story_spend` has a value of its own: usd_orch of a $100 story. A
    story activity segment of TASK binds it (evidence); each request's stored price is its true one,
    so that a caller handing the file to `orchestrator_totals` bare and one that re-prices read the
    same."""
    def req(rid, when, usd, stream="orchestrator"):
        row = request_row("s1", rid, stream, usd, activity="act-1", task=TASK, pinned=usd)
        row["timestamp"] = when
        return row
    return {"session_id": "s1", "total_cost_usd": 100.0,
            "by_task": {TASK: {"active_s": 10, "machine_s": 10, "cost": 100.0, "tokens": 1000}},
            "by_activity": {"act-1": {"type": "story", "task": TASK}},
            "agents": [{"agent": "qa-automator", "task": TASK, "tokens": 900, "cost": 52.0}],
            "requests": [req("r1", "2026-09-23T10:30:00Z", usd_orch * 0.25),
                         req("r2", "2026-09-23T11:30:00Z", usd_orch * 0.75),
                         req("r3", "2026-09-23T11:30:00Z", 100.0 - usd_orch, stream="agent-1")]}


# ------------------------------------------------------------------------------ the checks

def edge1_share_is_the_conductors_over_every_session():
    data = numbers([row("c1", "conductor", 2.0, "S1"), row("r1", total=6.0, stage="S5"),
                    row("t1", "ticket", 2.0, "S0")])
    basis = data["orchestrator_share_basis"]
    check_eq("edge 1: the share is the conductor's record over every journal session's",
             data["orchestrator_share_percent"], 20.0)
    check_eq("edge 1: a ticket session is in the denominator", basis["total_usd"], 10.0)
    check_eq("edge 1: and not in the numerator", basis["conductor_usd"], 2.0)
    check_eq("edge 1: the ticket call is the scout's: it is in the roles' money ($6 + $2), not the conductor's",
             basis["role_usd"], 8.0)
    check_eq("edge 1: only the conductor session is counted as one",
             (basis["sessions"], basis["conductor_sessions"]), (3, 1))
    two = numbers([row("r1", total=6.0, stage="S5"), row("t1", "ticket", 4.0, "S0")])
    check_eq("edge 1: a run with no conductor session has a share of zero, priced, not unknown",
             two["orchestrator_share_percent"], 0.0)
    costly = numbers([row("c1", "conductor", 2.0), row("r1", total=6.0)],
                     [priced_file("c1", 40.0), priced_file("r1", 60.0)])
    check_eq("edge 1: a story whose sessions are all priced by the driver has its share, and cost "
             "files priced far higher do not move it", costly["orchestrator_share_percent"], 25.0)
    check_eq("edge 1: though the price itself says the records differ, as a range, not as one figure",
             (costly["price"]["status"], costly["story"]["usd"]), ("differs", None))


def edge1_cmp1_proportions():
    data = numbers(cmp1_rows(), cmp1_costs())
    basis = data["orchestrator_share_basis"]
    check_eq("cmp1: the driver's record is $17.42 over 35 sessions",
             (round(basis["total_usd"], 4), basis["sessions"]), (17.42, 35))
    check_eq("cmp1: the conductor's 17 sessions cost $3.07",
             (round(basis["conductor_usd"], 4), basis["conductor_sessions"]), (3.07, 17))
    check_eq("cmp1: the share is 17.6, not what the control layer summed", data["orchestrator_share_percent"], 17.6)
    check_eq("cmp1: the retro publishes no control-layer total any more", "control_layer" in data, False)
    check("cmp1: the old control-layer function is gone, and with it the figure that added every row's total",
          not hasattr(RN, "control_layer"))
    check_eq("cmp1: the story's sessions are the 35 the price names, the 13 collapsed ones a ticket-tag "
             "filter dropped included (B-223)", data["story"]["sessions"], 35)
    check_eq("cmp1: and the story's money is the driver's $17.42, both records agreeing",
             (round(data["story"]["usd"], 4), data["price"]["status"]), (17.42, "agrees"))
    check_eq("cmp1: every session was priced by the driver's record",
             (basis["priced_by_driver"], basis["unpriced"], basis["unknown"], basis["left_out"]),
             (35, 0, [], []))
    check_eq("cmp1: the cost files' own pinned figure is a figure of its own, 35 files",
             (round(basis["cost_files"]["usd"], 4), basis["cost_files"]["sessions"], basis["cost_files"]["of"]),
             (17.42, 35, 35))


def edge2_an_unknown_driver_record_is_never_priced_by_a_cost_file():
    rows = [row("c1", "conductor", 1.0, "S1"),
            # A per-call journal: the figure falls inside the session (driver3, 29240aa1). The
            # last row says $1.0; the session cost $5.0. The last row must never be the price.
            row("r-fall", total=2.0), row("r-fall", total=1.0, resumed=True),
            # No usable figure at all: a string is not a total.
            row("r-none", total="1.0"),
            row("r-ok", total=1.0)]
    costs = [cost_file("r-fall", 5.0, task="(no task)"), cost_file("r-none", 3.0)]
    data = numbers(rows, costs)
    basis = data["orchestrator_share_basis"]
    check_eq("edge 2: two sessions have no driver record and the share is unknown, not a mix of "
             "two tables", data["orchestrator_share_percent"], None)
    check_eq("edge 2: the base is not published either", basis["total_usd"], None)
    check_eq("edge 2: which sessions, and the reader's reason for each",
             basis["unknown"], [{"session": "r-fall", "why": DJ.WHY_FALLS},
                                {"session": "r-none", "why": DJ.WHY_NO_TOTAL}])
    check_eq("edge 2: the known amounts stay as amounts (conductor, roles, all)",
             (basis["conductor_usd"], basis["role_usd"], basis["known_usd"]), (1.0, 1.0, 2.0))
    # The cost files here carry only a PINNED `total_cost_usd` (5.0 and 3.0) and no request ledger. A
    # pinned figure is another table's money and there is nothing to re-price it from: the file gives
    # NO figure (unknown, never the pinned 8.0: FR-41), and the facts say what is there, "2 sessions
    # bound, no figure": `sessions` counts the BOUND files, `unpriced` the bound ones with no figure.
    check_eq("edge 2: two cost files are bound to the story and neither gives a figure",
             basis["cost_files"], {"usd": None, "sessions": 2, "unpriced": 2, "of": 4})
    ledgerless = costs[1]
    check_eq("edge 2: control - the pinned field IS present in the file (so the None above is not an absent total)",
             ledgerless["total_cost_usd"], 3.0)
    check_eq("edge 2: `cost_file_amount` never falls back to the pinned field: re-priced with no ledger it is None",
             RN.cost_file_amount(CC.revalue_document(dict(ledgerless, agents=[{"agent": "a", "tokens": 5}]), {}, None)), None)
    check_eq("edge 2: and with a ledger the same file gives its re-priced figure, not the pinned one",
             RN.cost_file_amount(CC.revalue_document(priced_file("r-ok", 1.0, total_cost_usd=77.0), {}, None)), 1.0)
    text = RN.render(data)
    check_in("edge 2: the retro says how many have no record and why, in plain words",
             "2 of the 4 sessions have no usable driver record: 1 because the journal holds no "
             "usable cost figure for it; 1 because its figure falls between calls, so it is one "
             "call's cost and not the session's.", text)
    check_in("edge 2: and that the cost files are not mixed in",
             "the project's cost files are priced by another table, so they are not mixed in", text)
    check_in("edge 2: the conductor's and the roles' known amounts are printed as amounts",
             "Known amounts, not a share: the conductor's 1 session with a driver record cost "
             "$1.00; the roles' 1 session with one cost $1.00.", text)
    check_in("edge 2: not a share", "**Orchestrator share: not computable.**", text)
    check_not_in("edge 2: no sentence claims a charge for each session", "charged for each", text)
    check_not_in("edge 2: nor a driver record of all of them", "the driver's own record of", text)
    check_not_in("edge 2: nor the old cost-file fallback", "priced from their cost file", text)
    check_in("edge 2: the PRICE says what is known and that two sessions are in neither record",
             "**Story price: at least $2.00 — INCOMPLETE.**", text)
    check_in("edge 2: with the reason", "2 sessions are in neither record", text)
    unusable = numbers([row("c1", "conductor", 1.0), row("r1", total=1.0),
                        row("r-bad", total=True), row("r-neg", total=-4.0)],
                       [cost_file("r-bad", 2.0), cost_file("r-neg", 4.0)])
    ub = unusable["orchestrator_share_basis"]
    check_eq("edge 2: a bool and a negative total are unknown, and their cost files stand in for nothing",
             (unusable["orchestrator_share_percent"], ub["total_usd"], ub["unpriced"]), (None, None, 2))


def edge3_a_role_with_a_zero_cost_file_is_unknown_not_a_hundred():
    """The critic's probe: a conductor with a record, a role whose totals fall (no driver record)
    and whose cost file is $0 with zero usage. The share read 100.0: the $0 file was its price."""
    rows = [row("c1", "conductor", 2.0), row("r-fall", total=0.5), row("r-fall", total=0.2, resumed=True)]
    zero = cost_file("r-fall", 0.0, task="(no task)",
                     agents=[{"agent": "qa-factory:qa-automator", "task": TASK, "tokens": 0, "cost": None}])
    zero["by_task"] = {"(no task)": {"tokens": 0, "requests": 0, "cost": 0.0}}
    data = numbers(rows, [zero])
    basis = data["orchestrator_share_basis"]
    check_eq("edge 3: the share is unknown, not 100.0", data["orchestrator_share_percent"], None)
    check_eq("edge 3: the role is counted unknown, with the reader's reason",
             (basis["unpriced"], basis["unknown"]), (1, [{"session": "r-fall", "why": DJ.WHY_FALLS}]))
    check_eq("edge 3: the conductor's $2.00 is still an amount",
             (basis["conductor_usd"], basis["total_usd"]), (2.0, None))
    check_eq("edge 3: the zero-usage file is not a price of any session",
             basis["cost_files"], {"usd": None, "sessions": 1, "unpriced": 1, "of": 2})
    text = RN.render(data)
    check_in("edge 3: the retro prints it as not computable", "**Orchestrator share: not computable.**", text)
    check_in("edge 3: one session without a record is said in the singular",
             "1 of the 2 sessions has no usable driver record", text)
    check_not_in("edge 3: never 100", "100.0%", text)
    # The same run with a REAL cost file for the falling role: still unknown - one source per ratio.
    real = numbers(rows, [cost_file("r-fall", 5.0)])
    check_eq("edge 3: a cost file with usage does not make the ratio computable either",
             real["orchestrator_share_percent"], None)
    none = numbers([row("a", total=2.0), row("a", total=1.0, resumed=True), row("b", total=None)])
    check_eq("edge 3: nothing priced: the share is unknown, not 0 and not 100",
             none["orchestrator_share_percent"], None)
    check_in("edge 3: and the reason names the count", "none of the 2 sessions has a usable driver record",
             none["orchestrator_share_basis"]["reason"])
    check_eq("edge 3: with nothing known there are no amounts to print", none["orchestrator_share_basis"]["known_usd"], None)
    check_not_in("edge 3: so the retro prints no amounts line", "Known amounts", RN.render(none))
    check_in("edge 3: the retro prints the unknown in words", "Orchestrator share: not computable",
             RN.render(none))
    zero = numbers([row("c1", "conductor", 0.0), row("r1", total=0.0)])
    check_eq("edge 3: priced sessions that add up to nothing have no base: unknown",
             zero["orchestrator_share_percent"], None)
    check_in("edge 3: with a reason", "add up to nothing", zero["orchestrator_share_basis"]["reason"])
    # Plural by count in every sentence that prints a count of sessions (t-171): 1 is "session".
    one_none = numbers([row("a", total=None)])
    check_in("edge 3: one session with no record, in the singular",
             "none of the 1 session has a usable driver record", one_none["orchestrator_share_basis"]["reason"])
    one_zero = numbers([row("r1", total=0.0)])
    check_in("edge 3: one session that adds up to nothing, in the singular",
             "the 1 session adds up to nothing", one_zero["orchestrator_share_basis"]["reason"])
    one_each = numbers([row("c1", "conductor", 1.0), row("r1", total=3.0)])
    check_in("edge 3: a share measured on one conductor session says 'session', not 'sessions'",
             "the conductor's 1 session cost $1.00 of $4.00.", RN.render(one_each))
    check_not_in("edge 3: and never the old '(s)' spelling anywhere on the page", "session(s)", RN.render(one_each))


def edge4_the_journal_share_wins_and_a_run_without_one_is_unchanged():
    """The fixture gives each branch a value of its own: orchestrator_totals / story price 48.0, the
    journal 20.0. (The control-layer branch, 66.7 here, is gone: it had no caller left.)"""
    rows = [row("s1", "conductor", 2.0, "S1"),
            row("s2", total=5.0, stage="S5"), row("s2", total=8.0, stage="S5", resumed=True)]
    costs = [orchestrator_session(48.0)]
    root, state, troot = build(rows, costs, pipeline=PIPELINE)
    try:
        data = RN.numbers(TASK, root=state, task_root=troot)
        check_eq("edge 4: the orchestrator-stream branch has a value of its own here, read from the "
                 "re-priced file", data["orchestrator"]["cost"], 48.0)
        check_eq("edge 4: the journal share wins over it", data["orchestrator_share_percent"], 20.0)
        check_eq("edge 4: over orchestrator_totals / story price in particular",
                 data["orchestrator_share_percent"] == 48.0, False)
        (troot / "state" / "driver-runs.jsonl").unlink()
        old = RN.numbers(TASK, root=state, task_root=troot)
        check_eq("edge 4: the same story without a journal takes the orchestrator-stream branch",
                 old["orchestrator_share_percent"], 48.0)
        check_eq("edge 4: its divisor is the ONE price ($100, the file's requests at catalogue rates)",
                 (old["story"]["usd"], old["price"]["status"]), (100.0, "not_cross_checked"))
        check_eq("edge 4: and carries no journal basis and no resumed-role line",
                 (old["orchestrator_share_basis"], old["handed_back_to_roles"], "control_layer" in old),
                 (None, None, False))
    finally:
        cleanup(root)


def edge5_the_stage_split_comes_from_the_journal():
    rows = [row("c1", "conductor", 1.0, "S1"), row("c1", "conductor", 1.5, "S4"),
            row("c2", "conductor", 0.5, ""), row("c3", "conductor", 0.25),
            row("c-lost", "conductor", None, "S5"),
            row("r1", total=9.0, stage="S5"), row("t1", "ticket", 4.0, "S0")]
    rows[3].pop("stage")
    root, state, troot = build(rows, [cost_file("c-lost", 2.0)], pipeline=PIPELINE)
    try:
        journal = RN.journal_sessions(troot)
        split = RN.orchestrator_by_stage(TASK, RN.all_cost_files(state), PIPELINE, journal)
        check_eq("edge 5: conductor sessions keyed by the stage of their FIRST row; an empty or "
                 "absent stage is unattributed; a session with no driver record (its cost file "
                 "does not stand in), a role and a ticket session are not in it",
                 split, {"S1": 1.5, "unattributed": 0.75})
        shaped = {sid: {"task": TASK, "rows": r} for sid, r in journal.items()}
        shaped["c-other"] = {"task": "OTHER-1", "rows": [row("c-other", "conductor", 9.0, "S9")]}
        check_eq("edge 5: the reader's binding shape works too, and another task's session is not this story's",
                 RN.orchestrator_by_stage(TASK, RN.all_cost_files(state), PIPELINE, shaped), split)
        check_eq("edge 5: an empty journal places nothing",
                 RN.orchestrator_by_stage(TASK, [], PIPELINE, {}), {})
        clock_files = [(None, orchestrator_session(48.0))]
        clock = RN.orchestrator_by_stage(TASK, clock_files, PIPELINE)
        check_eq("edge 5: without a journal it is today's clock split, argument for argument",
                 (round(clock["S1"], 2), round(clock["S5"], 2)), (12.0, 36.0))
        check_eq("edge 5: and `journal=None` is the same call",
                 RN.orchestrator_by_stage(TASK, clock_files, PIPELINE, None), clock)
        check_eq("edge 5: with a journal the clock is not read at all: the same receipts place "
                 "nothing on their own",
                 RN.orchestrator_by_stage(TASK, clock_files, PIPELINE, journal), split)
        data = RN.numbers(TASK, root=state, task_root=troot)
        check_eq("edge 5: numbers() carries the journal split", data["orchestrator_by_stage"], split)
        check_eq("edge 5: which adds up to the share's numerator, the conductor's known money",
                 round(sum(split.values()), 6), data["orchestrator_share_basis"]["conductor_usd"])
        falling = dict(journal, **{"c-fall": [row("c-fall", "conductor", 1.0, "S5"),
                                              row("c-fall", "conductor", 0.5, "S5")]})
        check_eq("edge 5: a falling session anywhere in the root makes a multi-row conductor "
                 "session unknown, so it leaves the split (c1 has two rows)",
                 RN.orchestrator_by_stage(TASK, [], PIPELINE, falling), {"unattributed": 0.75})
    finally:
        cleanup(root)


def edge6_the_finding_divides_by_the_shares_own_base():
    root, state, troot = build(cmp1_rows(), cmp1_costs(),
                               config={"retro": {"orchestrator_share_max": 0.1}})
    try:
        data = RN.numbers(TASK, root=state, task_root=troot)
        basis = data["orchestrator_share_basis"]
        parts = data["orchestrator_by_stage"]
        check_eq("edge 6: the conductor's sessions by stage of their first row",
                 {k: round(v, 2) for k, v in parts.items()}, {"S1": 1.44, "S4": 1.44, "S5": 0.19})
        check("edge 6: the stage costs add up to the share's numerator",
              abs(sum(parts.values()) - basis["conductor_usd"]) < 1e-9, str(parts))
        check("edge 6: and, over the share's base, to the headline share",
              abs(100.0 * sum(parts.values()) / basis["total_usd"] - data["orchestrator_share_percent"]) < 0.05,
              str(parts))
        finding = RN.orchestrator_finding(data)
        check_in("edge 6: the finding fires over the configured limit",
                 "the orchestrator spent 18 % of the story (limit 10 %)", finding)
        check_in("edge 6: its stage parts are over the driver's record ($1.44 of $17.42 is 8 %)",
                 "S1 8 %, S4 8 %, S5 1 %", finding)
        check_not_in("edge 6: not over the old tag-filtered cost files' spend ($1.44 of $13.20 would read 11 %)",
                     "11 %", finding)
    finally:
        cleanup(root)
    plain = {"story": {"usd": 100.0}, "orchestrator_share_percent": 50.0,
             "orchestrator_share_limit_percent": 35.0, "orchestrator_by_stage": {"S1": 25.0}}
    check_in("edge 6: a run without a basis (the dashboard banner) divides by the story's spend, as before",
             "S1 25 %", RN.orchestrator_finding(plain))
    check_in("edge 6: a basis changes the divisor",
             "S1 50 %", RN.orchestrator_finding(dict(plain, orchestrator_share_basis={"total_usd": 50.0})))
    check_not_in("edge 6: a basis that priced nothing prints no stage parts",
                 " - S1", RN.orchestrator_finding(dict(plain, orchestrator_share_basis={"total_usd": None})))


def edge7_a_person_reads_which_quantity_is_which():
    data = numbers(cmp1_rows(), cmp1_costs())
    text = RN.render(data)
    check_in("edge 7: the share line names its base, the amounts and the session count, and says "
             "every session was priced by it",
             "**Orchestrator share: 17.6%.** Measured on the driver's own record of 35 sessions, "
             "every one of them priced by it: the conductor's 17 sessions cost $3.07 of $17.42.", text)
    check_in("edge 7: the conductor's money is management and all the share counts",
             "Choosing a role and handing it something to redo is the conductor's management and "
             "is all this share counts", text)
    check_in("edge 7: the price is ONE figure, the two records agreeing, over all 35 sessions",
             "**Story price: $17.42.** Two records agree on it", text)
    check_in("edge 7: and says what was compared",
             "Compared: the CLI's own charge for the 35 sessions the driver's journal names; 0 priced from one record.", text)
    check_not_in("edge 7: the old tag-filtered 'Story spend by the cost files' line is gone", "Story spend by the cost files", text)
    check_not_in("edge 7: the control-layer line, which added resumed roles to the conductor, is gone",
                 "Control layer", text)
    check_not_in("edge 7: with its sentence", "agreeing with itself", text)
    check_not_in("edge 7: there are no two totals to reconcile any more", "Two totals", text)
    check_not_in("edge 7: no gap line, and no record is named the authoritative one", "Gap —", text)
    check_not_in("edge 7: (the word, anywhere)", "authoritative", text)
    check_not_in("edge 7: nothing compares a control layer with the driver's record",
                 "control layer against", text)
    # The lines this change writes: everything above the friction section, which is another
    # section's text (its own path and transcript names).
    ours = text.split("**Friction with")[0]
    for word in ("total_cost_usd", "session_id", "driver-runs", "jsonl", "kind", "orchestrator_share",
                 "priced_by", "record_label", "handed_back", "known_usd", "left_out"):
        check_not_in(f"edge 7: no field name in a person's text ({word})", word, ours)
    incomplete = numbers(cmp1_rows(), [cost_file("c-s1-0", 0.6, agents=[
        {"agent": "qa-factory:qa-automator", "task": TASK, "tokens": 0, "cost": None,
         "tools": {"Bash": 3}}])])   # it RAN (tool calls) with usage unread: a gap; with no tools it would be idle (E-C5)
    rendered = RN.render(incomplete)
    check_in("edge 7: incomplete cost files stay a floor, said as such", "INCOMPLETE", rendered)
    check_in("edge 7: yet the driver's share is still published, it does not stand on them",
             "**Orchestrator share: 17.6%.**", rendered)
    check_not_in("edge 7: and the old sentence that withholds the share is not printed beside it",
                 "no orchestrator share is published while it holds", rendered)
    # Two sessions, the driver's record $2.00; the transcripts' price AT and BEYOND the price
    # function's tolerance (a tenth of a cent per session).
    rows = [row("c1", "conductor", 1.0), row("r1", total=1.0)]
    at = RN.render(numbers(rows, [priced_file("c1", 1.001), priced_file("r1", 1.001)]))
    check_in("edge 7: a gap of exactly the tolerance per session agrees, at the transcripts' figure",
             "**Story price: $2.00.** Two records agree on it", at)
    beyond = RN.render(numbers(rows, [priced_file("c1", 1.0011), priced_file("r1", 1.0011)]))
    check_in("edge 7: a hair more is a range, from the CLI's $2.00 to the transcripts' $2.00 at the cent",
             "**Story price: from $2.00 to $2.00.** The two records of this price disagree", beyond)
    under = RN.render(numbers(rows, [priced_file("c1", 0.5), priced_file("r1", 0.5)]))
    check_in("edge 7: a gap in the other direction is a range too", "**Story price: from $1.00 to $2.00.**", under)
    check_in("edge 7: with the finding, whose defect it is",
             "This is a defect of the factory's measurement, not a fact about the story.", under)
    same = RN.render(numbers(rows, [priced_file("c1", 1.0), priced_file("r1", 1.0)]))
    check_not_in("edge 7: two equal figures need no sentence about a defect", "a defect of the factory's", same)
    nofiles = RN.render(numbers(rows))
    check_in("edge 7: with no cost file at all the price is one record, said so",
             "**Story price: $2.00 — not cross-checked.**", nofiles)
    check_not_in("edge 7: and nothing is called a defect", "a defect of the factory's", nofiles)


def edge8_a_journal_that_names_nothing_is_an_unknown_share():
    cases = {
        "an empty journal file": "",
        "only blank and broken lines": "\n\n{not json\n[1, 2]\n\"text\"\n",
        "only rows without a session id": "\n".join(json.dumps(r) for r in [
            {"kind": "delivery", "total_cost_usd": 3.0},
            row(None, "conductor", 2.0), row("", "conductor", 2.0), row(5, "conductor", 2.0)]),
        "only an id holding U+FFFD": json.dumps(row("id" + chr(0xFFFD), "conductor", 2.0)),
        "every record unknown and no cost file": "\n".join(json.dumps(r) for r in [
            row("a", total=None), row("b", total="2"), row("c", total=float("nan"))]),
    }
    for name, raw in cases.items():
        try:
            data = numbers(raw=raw)
            text = RN.render(data)
            finding = RN.orchestrator_finding(data)
        except Exception as exc:  # the edge is precisely that nothing raises
            check(f"edge 8: {name}: no exception", False, f"{type(exc).__name__}: {exc}")
            continue
        check_eq(f"edge 8: {name}: the share is unknown", data["orchestrator_share_percent"], None)
        check(f"edge 8: {name}: with a reason", bool(data["orchestrator_share_basis"]["reason"]),
              str(data["orchestrator_share_basis"]))
        check_in(f"edge 8: {name}: printed as not computable, never 0 or 100",
                 "Orchestrator share: not computable.", text)
        check_eq(f"edge 8: {name}: and no finding", finding, "")
    empty = numbers(raw="")
    check_in("edge 8: an empty journal says it names no session",
             "names no session", empty["orchestrator_share_basis"]["reason"])
    check_in("edge 8: and the price says no session has a record, never a $0.00",
             "**Story price: not known.** No session of this story has a record of its cost.", RN.render(empty))
    check_eq("edge 8: the journal, present, is the journal's branch and not the run without one",
             (empty["orchestrator_share_basis"]["sessions"], empty["handed_back_to_roles"]),
             (0, {"usd": 0.0, "sessions": 0, "unknown": 0}))
    ghost = numbers(raw="\n".join(json.dumps(r) for r in [
        row("id" + chr(0xFFFD), "conductor", 5.0), row("c1", "conductor", 2.0), row("r1", total=6.0)]))
    check_eq("edge 8: a session whose id holds U+FFFD is not there at all, in no sum and no count",
             (ghost["orchestrator_share_percent"], ghost["orchestrator_share_basis"]["sessions"]), (25.0, 2))


def edge9_a_story_without_a_journal_is_unchanged():
    root, state, troot = build(None, [orchestrator_session(48.0)], pipeline=PIPELINE)
    try:
        data = RN.numbers(TASK, root=state, task_root=troot)
        check_eq("edge 9: the share is today's orchestrator-stream share", data["orchestrator_share_percent"], 48.0)
        check_eq("edge 9: there is no journal basis", data["orchestrator_share_basis"], None)
        check_eq("edge 9: the stage split is today's clock split",
                 {k: round(v, 2) for k, v in data["orchestrator_by_stage"].items()},
                 {"S1": 12.0, "S5": 36.0})
        text = RN.render(data)
        check_in("edge 9: the price is the file's requests at catalogue rates, one record, marked so",
                 "**Story price: $100.00 — single source (chat): nothing to cross-check against.**", text)
        check_in("edge 9: the tokens are by_task's folded figure", "Tokens recorded in the cost files of these sessions: 1,000.", text)
        check_in("edge 9: and the share is today's", "**Orchestrator share: 48.0%.**", text)
        check_not_in("edge 9: nothing of the driver's record is printed", "driver's own record", text)
        check_not_in("edge 9: nor the two totals", "Two totals", text)
        check_not_in("edge 9: nor a resumed-role line", "handed back", text)
        check_in("edge 9: the finding divides by the story's spend, as before",
                 "S5 36 %, S1 12 %", RN.orchestrator_finding(data))
    finally:
        cleanup(root)


def edge10_the_root_rule_prices_a_session_by_the_whole_root():
    """A session with rows 1.0 then 1.2 rises, so on its own it reads as a running total of $1.20.
    Another story under the same root holds a session that FALLS: what a total means is a property
    of the root, so the session is unknown and the share with it."""
    rows = [row("c1", "conductor", 2.0), row("r1", total=1.0, stage="S5"),
            row("r1", total=1.2, stage="S5", resumed=True)]
    other = {"OTHER-1": [row("o1", total=0.9), row("o1", total=0.3, resumed=True)]}
    alone = numbers(rows)
    check_eq("edge 10: control: alone under its root the session is priced by its last total, $1.20",
             (alone["orchestrator_share_percent"], alone["orchestrator_share_basis"]["total_usd"]), (62.5, 3.2))
    check_eq("edge 10: the reader's per-session price alone would be the same (control values)",
             DJ.driver_charged(rows[1:]), 1.2)
    data = numbers(rows, stories=other)
    basis = data["orchestrator_share_basis"]
    check_eq("edge 10: with another story's falling session in the root the share is unknown",
             data["orchestrator_share_percent"], None)
    check_eq("edge 10: the session is unknown for the per-call reason, and carries it",
             basis["unknown"], [{"session": "r1", "why": DJ.WHY_PER_CALL_ROOT}])
    check_eq("edge 10: the other story's session is neither counted nor listed here",
             (basis["sessions"], basis["left_out"]), (2, []))
    check_in("edge 10: the retro says so in words",
             "1 because the project's journals record each call's cost and not a running total, "
             "so a session with several rows cannot be priced", RN.render(data))
    check_eq("edge 10: a single-row session keeps its price under the per-call root",
             numbers([row("c1", "conductor", 2.0), row("r1", total=3.0)], stories=other)["orchestrator_share_percent"],
             40.0)


def edge11_a_session_named_by_two_journals_is_counted_where_it_starts():
    early, late = "2026-09-23T10:00:00+00:00", "2026-09-23T10:45:00+00:00"
    rows = [row("c1", "conductor", 2.0), row("r1", total=6.0), row("s-x", total=3.0, ts=late)]
    elsewhere = {"OTHER-1": [row("s-x", total=3.0, ts=early)]}
    data = numbers(rows, stories=elsewhere)
    basis = data["orchestrator_share_basis"]
    check_eq("edge 11: the session the reader bound to another story is left out of both sums",
             (data["orchestrator_share_percent"], basis["sessions"], basis["total_usd"]), (25.0, 2, 8.0))
    check_eq("edge 11: and named, with the count of journals and where it is counted",
             basis["left_out"], [{"session": "s-x", "journals": 2, "counted_under": "OTHER-1"}])
    text = RN.render(data)
    check_in("edge 11: the retro prints it in words",
             "session s-x is named by 2 task journals; counted under OTHER-1", text)
    root, state, _troot = build(rows, stories=elsewhere)
    try:
        by_session, problem = RN.read_root(state)
        check_eq("edge 11: it is in no stage split either (and the root was read: no problem)",
                 (RN.orchestrator_by_stage(TASK, [], PIPELINE, by_session), problem), ({"S1": 2.0}, ""))
    finally:
        cleanup(root)
    mirror = numbers([row("c1", "conductor", 2.0), row("r1", total=6.0), row("s-x", total=3.0, ts=early)],
                     stories={"OTHER-1": [row("s-x", total=3.0, ts=late)]})
    mb = mirror["orchestrator_share_basis"]
    check_eq("edge 11: control: bound HERE (the earliest record is this journal's) it is this story's, "
             "and unknown, because this journal holds only a part of it",
             (mirror["orchestrator_share_percent"], mb["left_out"], mb["unknown"]),
             (None, [], [{"session": "s-x", "why": DJ.WHY_SEVERAL_JOURNALS}]))
    check_in("edge 11: a share that is not computable still names the sessions left out",
             "session s-y is named by 2 task journals; counted under OTHER-1",
             RN.render(numbers([row("c1", "conductor", 2.0), row("bad", total=None), row("s-y", total=3.0, ts=late)],
                               stories={"OTHER-1": [row("s-y", total=3.0, ts=early)]})))


def edge12_resumed_role_money_is_its_own_line_priced_by_increments():
    # A role session launched at $1.00 and resumed after a return to a running total of $1.50: the
    # conductor handed back $0.50, not $2.50 (1.0 + 1.5) and not $1.50.
    rows = [row("c1", "conductor", 1.0), row("r1", total=1.0, stage="S5"),
            row("r1", total=1.5, stage="S5", resumed=True)]
    data = numbers(rows)
    check_eq("edge 12: $0.50 handed back over one resumed role session",
             data["handed_back_to_roles"], {"usd": 0.5, "sessions": 1, "unknown": 0})
    text = RN.render(data)
    check_in("edge 12: the retro says it in plain words",
             "work the conductor handed back to roles: $0.50 over 1 resumed role session.", text)
    role_line = [line for line in text.splitlines() if "handed back to roles" in line]
    check_eq("edge 12: one such line", len(role_line), 1)
    check_not_in("edge 12: not the cumulative $2.50", "$2.50", role_line[0])
    check_eq("edge 12: the share is the conductor's alone: $1.00 of $2.50, the resumed money is not "
             "the conductor's", data["orchestrator_share_percent"], 40.0)
    check_eq("edge 12: two resumed rows of one session add their increments (0.5 + 1.0), not totals",
             numbers([row("r2", total=1.0), row("r2", total=1.5, resumed=True),
                      row("r2", total=2.5, resumed=True)])["handed_back_to_roles"],
             {"usd": 1.5, "sessions": 1, "unknown": 0})
    check_eq("edge 12: a conductor session resumed is management, not role spend",
             numbers([row("c1", "conductor", 1.0), row("c1", "conductor", 2.0, resumed=True)])["handed_back_to_roles"],
             {"usd": 0.0, "sessions": 0, "unknown": 0})
    none = RN.render(numbers([row("c1", "conductor", 1.0), row("r1", total=1.0)]))
    check_in("edge 12: no resumed role session is said, not left out",
             "work the conductor handed back to roles: none.", none)
    cmp1 = numbers(cmp1_rows())
    check_eq("edge 12: cmp1: 17 resumed role sessions handed back $6.80 (0.80 - 0.40 each)",
             (round(cmp1["handed_back_to_roles"]["usd"], 4), cmp1["handed_back_to_roles"]["sessions"]), (6.8, 17))
    check_in("edge 12: cmp1: the line a person reads",
             "work the conductor handed back to roles: $6.80 over 17 resumed role sessions.", RN.render(cmp1))
    # A resumed session that cannot be attributed is unknown, never summed.
    fall = numbers([row("r1", total=2.0), row("r1", total=1.0, resumed=True)])
    check_eq("edge 12: a resumed session whose totals fall is unknown", fall["handed_back_to_roles"],
             {"usd": None, "sessions": 0, "unknown": 1})
    check_in("edge 12: and the retro says so, with no invented amount",
             "work the conductor handed back to roles: not known.", RN.render(fall))
    bad = numbers([row("r1", total=1.0), row("r1", total="x", resumed=True), row("r1", total=2.0, resumed=True),
                   row("r2", total=1.0), row("r2", total=1.4, resumed=True)])
    check_eq("edge 12: a resumed row right after an unusable total is unknown; another session's amount stays",
             bad["handed_back_to_roles"], {"usd": 0.4, "sessions": 1, "unknown": 1})
    check_in("edge 12: the amount and the unknown are said together",
             "over 1 resumed role session.** 1 resumed role session has no usable driver record and is not in this amount.",
             RN.render(bad))
    per_call = numbers([row("r1", total=1.0), row("r1", total=1.5, resumed=True)],
                       stories={"OTHER-1": [row("o1", total=0.9), row("o1", total=0.3)]})
    check_eq("edge 12: under a per-call root a resumed multi-row session is unknown too",
             per_call["handed_back_to_roles"], {"usd": None, "sessions": 0, "unknown": 1})


def edge13_the_control_figure_is_the_conductors_money():
    data = numbers(cmp1_rows(), cmp1_costs())
    basis = data["orchestrator_share_basis"]
    check_eq("edge 13: there is no control-layer total in the facts", "control_layer" in data, False)
    check_eq("edge 13: the management figure is the conductor's sessions only, the share's numerator, "
             "and equals the stage parts", (round(basis["conductor_usd"], 4),
                                            round(sum(data["orchestrator_by_stage"].values()), 4)), (3.07, 3.07))
    check("edge 13: and not the old control sum (resumed roles + conductor, $16.67 on these rows)",
          abs(basis["conductor_usd"] - 16.67) > 1.0, str(basis))
    check_in("edge 13: the retro prints the conductor's $3.07 as the management figure",
             "the conductor's 17 sessions cost $3.07", RN.render(data))


def edge14_a_cost_file_is_a_price_only_when_it_measured_something():
    full = cost_file("s", 2.5, agents=[{"agent": "a", "task": TASK, "tokens": 5}])
    check_eq("edge 14: control: a file with usage is its total", RN.cost_file_amount(full), 2.5)
    check_eq("edge 14: a $0 file with zero usage is not a price",
             RN.cost_file_amount({"session_id": "s", "total_cost_usd": 0.0, "agents": [],
                                  "by_task": {TASK: {"tokens": 0, "requests": 0, "cost": 0.0}}}), None)
    check_eq("edge 14: a file declaring incomplete_agents is not a price",
             RN.cost_file_amount(dict(full, incomplete_agents=["qa-factory:qa-scout"])), None)
    check_eq("edge 14: a file with an agent of zero usage is a part of a price, not a price",
             RN.cost_file_amount(dict(full, agents=[{"agent": "a", "tokens": 5}, {"agent": "b", "tokens": 0}])), None)
    check_eq("edge 14: a file with no usage anywhere is not a price, whatever it says it cost",
             RN.cost_file_amount({"session_id": "s", "total_cost_usd": 7.0}), None)
    check_eq("edge 14: a file with no usable total is not a price",
             (RN.cost_file_amount(dict(full, total_cost_usd=None)), RN.cost_file_amount(dict(full, total_cost_usd="2")),
              RN.cost_file_amount(dict(full, total_cost_usd=True)), RN.cost_file_amount("not a dict")),
             (None, None, None, None))
    check_eq("edge 14: request rows alone are usage",
             RN.cost_file_amount({"session_id": "s", "total_cost_usd": 1.0, "requests": [{"x": 1}]}), 1.0)
    check_eq("edge 14: a priced zero WITH usage is a price of zero",
             RN.cost_file_amount(dict(full, total_cost_usd=0.0)), 0.0)


def edge15_a_project_root_that_cannot_be_found_is_an_unknown_share():
    rows = [row("c1", "conductor", 2.0), row("r1", total=6.0)]
    data = numbers(rows, state_name="factory-state")
    basis = data["orchestrator_share_basis"]
    check_eq("edge 15: the state folder is not named qa-factory: the project cannot be told, the share is unknown",
             data["orchestrator_share_percent"], None)
    check_in("edge 15: with that reason", "the project folder cannot be told from the factory's state folder "
             "(factory-state)", basis["reason"])
    check_eq("edge 15: every session the story's journal names is unknown, not invented",
             sorted(u["why"] for u in basis["unknown"]), [RN.WHY_NOT_READ] * 2)
    check_eq("edge 15: no journal was read, so no split and no resumed line",
             (data["orchestrator_by_stage"], data["handed_back_to_roles"]), ({}, {"usd": 0.0, "sessions": 0, "unknown": 0}))
    moved = numbers(rows, config={"artifact_root": "elsewhere"})
    check_eq("edge 15: a project whose artifact folder is configured elsewhere does not list this story's journal: "
             "the sessions are unknown, named as not listed", (moved["orchestrator_share_percent"],
                                                                sorted(u["why"] for u in moved["orchestrator_share_basis"]["unknown"])),
             (None, [RN.WHY_NOT_READ] * 2))
    check_in("edge 15: in plain words", "2 because the project's journals do not list it, so its record was not found",
             RN.render(moved))


def edge16_the_tables_sum_increments_not_running_totals():
    """A journal row's `total_cost_usd` is a RUNNING total of its session, so a row costs its
    increment. cmp1's 17 role sessions were launched at $0.40 and resumed to $0.80: $13.60 of role
    money in all, where the raw totals add up to $20.40 (0.4 + 0.8 each) - the stage table of the
    real retro summed to $32.0 against the driver's $17.42 (R6, the class t-138 fixed for the share)."""
    data = numbers(cmp1_rows())
    role = data["by_role"]["qa-automator"]
    check_eq("edge 16: by role, 17 sessions x (0.40 + (0.80 - 0.40)) = $13.60, not 17 x (0.4 + 0.8) = $20.40",
             (role["dispatches"], round(role["cost"], 4)), (34, 13.6))
    check_eq("edge 16: by stage, the same money (all of it is S5)", round(data["by_stage"]["S5"]["cost"], 4), 13.6)
    check_eq("edge 16: the tables add up to the roles' own money: the ticket call and the conductor are "
             "not role dispatches", round(sum(b["cost"] for b in data["by_stage"].values()), 4), 13.6)
    # The fixture gives all 17 role sessions ONE dispatch name, so every row after the first is a
    # later round: 33 rows, each adding $0.40 (raw totals would say 16 x 0.4 + 17 x 0.8 = $20.00).
    check_eq("edge 16: rework costs what its rows ADDED, 33 x $0.40 = $13.20, not their running totals",
             (data["rework"]["dispatches"], round(data["rework"]["cost"], 4)), (33, 13.2))
    check_eq("edge 16: a top dispatch is one row's increment", [round(t["cost"], 4) for t in data["top_dispatches"]], [0.4, 0.4, 0.4])
    check("edge 16: nothing is called incomplete when every increment is known",
          not any(b["incomplete"] for b in data["by_role"].values()), str(data["by_role"]))
    fall = numbers([row("r1", total=2.0), row("r1", total=1.0, resumed=True)])
    check_eq("edge 16: a session whose totals FALL is per-call money, not a running total: unknown, never a sum of it",
             (fall["by_role"]["qa-automator"]["cost"], fall["by_role"]["qa-automator"]["incomplete"],
              fall["rework"]["cost"]), (None, True, None))
    bad = numbers([row("r1", total=1.0), row("r1", total="x", resumed=True), row("r1", total=2.0, resumed=True)])
    check_eq("edge 16: a row with no usable total and the row after it have no increment: the known part is "
             "kept and the bucket says it is incomplete", (bad["by_role"]["qa-automator"]["cost"],
                                                             bad["by_role"]["qa-automator"]["incomplete"]), (1.0, True))
    per_call = numbers([row("r1", total=1.0), row("r1", total=1.5, resumed=True)],
                       stories={"OTHER-1": [row("o1", total=0.9), row("o1", total=0.3, resumed=True)]})
    check_eq("edge 16: under a per-call root (another story's session falls) a multi-row session is unknown here too",
             (per_call["by_role"]["qa-automator"]["cost"], per_call["by_role"]["qa-automator"]["incomplete"]), (None, True))
    single = numbers([row("r1", total=3.0)], stories={"OTHER-1": [row("o1", total=0.9), row("o1", total=0.3, resumed=True)]})
    check_eq("edge 16: a single-row session keeps its price under the same root", single["by_role"]["qa-automator"]["cost"], 3.0)
    two = numbers([row("r1", total=1.0, stage="S1"), row("r1", total=3.0, stage="S5", resumed=True)])
    check_eq("edge 16: a resumed row is the increment, and lands in ITS OWN stage",
             {k: round(v["cost"], 4) for k, v in two["by_stage"].items()}, {"S1": 1.0, "S5": 2.0})


def main():
    edge1_share_is_the_conductors_over_every_session()
    edge1_cmp1_proportions()
    edge2_an_unknown_driver_record_is_never_priced_by_a_cost_file()
    edge3_a_role_with_a_zero_cost_file_is_unknown_not_a_hundred()
    edge4_the_journal_share_wins_and_a_run_without_one_is_unchanged()
    edge5_the_stage_split_comes_from_the_journal()
    edge6_the_finding_divides_by_the_shares_own_base()
    edge7_a_person_reads_which_quantity_is_which()
    edge8_a_journal_that_names_nothing_is_an_unknown_share()
    edge9_a_story_without_a_journal_is_unchanged()
    edge10_the_root_rule_prices_a_session_by_the_whole_root()
    edge11_a_session_named_by_two_journals_is_counted_where_it_starts()
    edge12_resumed_role_money_is_its_own_line_priced_by_increments()
    edge13_the_control_figure_is_the_conductors_money()
    edge14_a_cost_file_is_a_price_only_when_it_measured_something()
    edge15_a_project_root_that_cannot_be_found_is_an_unknown_share()
    edge16_the_tables_sum_increments_not_running_totals()
    finish("test_retro_orchestrator_driver")


if __name__ == "__main__":
    main()
