#!/usr/bin/env python3
"""The retro measures waits, machine time, repair rounds and dispatches (RN1-25 items 2-5, t-1698 D2-D).

LOCAL-1 printed "Human wait 2h 46m" over about 7 h of waiting, "S6 4h20m machine time" over about 30 min of machine,
"28 repair rounds" for about 10 real returns, "qa-automator 9 dispatches" for 14 handoffs, and "no recorded usage" beside
a role's cost line. One named check per requirement and per edge:

  K-D2  stage machine time = the stage's wall time minus the waits inside its window (a question's span included)
        E-D1 an older capture (no `human_waits`, or `unmeasured`) keeps `human_wait_s` and is named; machine time None
        E-D4 a stage with no wall time has no machine time
        E-D5 a wait outside every stage lowers no stage and is clipped at 0
  K-D3  a repair round is a repeated scope of the same (stage, role); a new window is not; an empty scope is None
        E-D2 no dispatch records: the ordinal rule, labelled
        E-D3 an empty scope is named in the line
  K-D4  the dispatch count of a role is the number of controller records, not of agent files
  K-D5  "cost of <role> not estimated" only when NO cost record of the story carries usage for the role
        (E-C5, idle agents: see the report; the retro keeps the old zero-token rule, `task_price` exempts idle agents)

Every fixture is synthetic and lives in a temp directory.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import retro_numbers as RN  # noqa: E402

TASK = "QA-WAIT-1"
MODEL = "claude-sonnet-5-5"          # catalogue: output $10 per 1M tokens -> 100000 output tokens = $1.00
QUESTION_ASKED, QUESTION_ANSWERED = "2026-11-02T05:20:48+00:00", "2026-11-02T09:10:04+00:00"   # LOCAL-1: 13756 s


# ---------------------------------------------------------------------------------- fixtures

def project(td: Path):
    base = td / "qa-factory"
    troot = base / "artifacts" / TASK
    for sub in (base / "state" / "cost", troot / "work", troot / "state"):
        sub.mkdir(parents=True)
    (base / "config.json").write_text("{}", encoding="utf-8")
    return base, troot


def request(sid, rid, dollars, stream="orchestrator"):
    return {"request_key": f"anthropic:{sid}:{rid}:{stream}", "provider": "anthropic", "session_id": sid,
            "request_id": rid, "stream": stream, "task": TASK, "model_id": MODEL,
            "timestamp": "2026-11-02T05:10:00+00:00", "activity_id": "act-1",
            "usage": {"requests": 1, "input": 0, "output": round(dollars * 100000), "cache_read": 0,
                      "cache_write_5m": 0, "cache_write_1h": 0},
            "valuation": {"pricing_coverage": "complete", "subtotal_usd": "999", "missing_rate_categories": [],
                          "tariff_confirmation": "unconfirmed", "rate_provenance": {"kind": "legacy_project_override"}}}


def agent(role, tokens, tools=None, started="2026-11-02T05:11:00+00:00", file="agent-a.jsonl", stage="S5"):
    return {"agent": f"qa-factory:{role}", "purpose": f"{role} {stage} {TASK}", "task": TASK, "tokens": tokens,
            "cost": 1.0 if tokens else None, "started": started, "by_model": {"m": {"requests": 5}},
            "tools": tools or {}, "file": file}


def cost_file(sid, agents, **extra):
    doc = {"session_id": sid, "by_task": {TASK: {"tokens": 100, "requests": 1, "cost": 999.0}},
           "by_activity": {"act-1": {"type": "story", "task": TASK}},
           "requests": [request(sid, "r1", 1.0)], "agents": agents}
    doc.update(extra)
    return doc


def put(base, name, doc):
    (base / "state" / "cost" / f"{name}.json").write_text(json.dumps(doc), encoding="utf-8")


def pipeline_file(troot, stages):
    (troot / "pipeline.json").write_text(json.dumps({"ticket": TASK, "stages": stages}), encoding="utf-8")


def controller_file(troot, records):
    """`state/controller.json` as the controller writes it: `dispatches` keyed by id, each with stage/role/scope and
    the event's own number `dispatched_seq`."""
    out = {}
    for n, (did, scope, extra) in enumerate(records, start=1):
        out[did] = dict({"id": did, "stage": did.split("-")[0], "role": did.rsplit("-", 1)[0].split("-", 1)[1],
                         "scope": scope, "status": "accepted", "dispatched_seq": n}, **extra)
    (troot / "state" / "controller.json").write_text(json.dumps({"dispatches": out}), encoding="utf-8")


def wait(start, end, kind="question"):
    return {"start": start, "end": end, "seconds": 0, "kind": kind}


# ---------------------------------------------------------------------------------- K-D2 machine time

def machine_time():
    pipeline = {"stages": {
        "S5": {"status": "done", "started": "2026-11-02T03:00:00+00:00", "finished": "2026-11-02T05:00:00+00:00"},
        "S6": {"status": "done", "started": "2026-11-02T05:00:00+00:00", "finished": "2026-11-02T09:40:00+00:00"},
        "S7": {"status": "done", "started": "2026-11-02T10:00:00+00:00", "finished": "2026-11-02T10:30:00+00:00"},
        "S8": {"status": "done", "started": "2026-11-02T13:00:00+00:00", "finished": "2026-11-02T11:00:00+00:00"}}}
    times = RN.stage_times(pipeline)
    got = RN.stage_machine_times(times, [wait(QUESTION_ASKED, QUESTION_ANSWERED)], pipeline)
    check_eq("K-D2: S6 05:00-09:40 with the 05:20:48-09:10:04 question inside is 16800 - 13756 s", got["S6"], 3044)
    check_eq("K-D2: that is about 50 minutes, not 4h20m", RN.clock(got["S6"]), "50m 44s")
    check_eq("K-D2: a stage with no wait inside keeps its wall time", got["S5"], 7200)
    # E-D5: a wait outside every stage (11:30, between S7 and any later stage) lowers no stage
    outside = RN.stage_machine_times(times, [wait("2026-11-02T11:30:00+00:00", "2026-11-02T12:30:00+00:00")], pipeline)
    check_eq("E-D5: a wait outside every stage lowers no stage", (outside["S5"], outside["S6"], outside["S7"]), (7200, 16800, 1800))
    # E-D5: a wait wider than the window is clipped to it, never below 0
    wide = RN.stage_machine_times(times, [wait("2026-11-02T04:00:00+00:00", "2026-11-02T20:00:00+00:00")], pipeline)
    check_eq("E-D5: a wait wider than the stage is clipped: machine time 0, never negative", (wide["S6"], wide["S7"]), (0, 0))
    # two sessions waiting at the same time are subtracted once (the union), a turn gap inside a question too
    twice = RN.stage_machine_times(times, [wait(QUESTION_ASKED, QUESTION_ANSWERED), wait(QUESTION_ASKED, QUESTION_ANSWERED),
                                           wait("2026-11-02T06:00:00+00:00", "2026-11-02T06:10:00+00:00", "turn")], pipeline)
    check_eq("two overlapping waits count once", twice["S6"], 3044)
    # E-D4: a stage with no wall time (a reversed clock, S8) has no machine time
    check_eq("E-D4: wall time None -> machine time None", got["S8"], None)
    # E-D1: waits not measured -> None for every stage
    check_eq("E-D1: waits not measured -> machine time None for every stage",
             set(RN.stage_machine_times(times, None, pipeline).values()), {None})
    check_eq("an empty list of measured waits is a measured zero: machine time = wall time",
             RN.stage_machine_times(times, [], pipeline)["S6"], 16800)
    check_eq("an unreadable wait is skipped, not a crash",
             RN.stage_machine_times(times, [{"start": "x", "end": None}, "junk"], pipeline)["S6"], 16800)


def numbers_waits():
    td = temp_dir("qa-retro-wait-")
    try:
        base, troot = project(td)
        pipeline_file(troot, {"S6": {"status": "done", "started": "2026-11-02T05:00:00+00:00",
                                     "finished": "2026-11-02T09:40:00+00:00"}})
        runner = [agent("qa-runner", 500, {"Bash": 3}, stage="S6")]       # the stage table lists a stage that had a dispatch
        put(base, "s-1", cost_file("s-1", runner, human_wait_s=13756 + 600, question_waits="measured", open_questions=0,
                                   human_waits=[wait(QUESTION_ASKED, QUESTION_ANSWERED),
                                                wait("2026-11-02T09:20:00+00:00", "2026-11-02T09:30:00+00:00", "turn")]))
        data = RN.numbers(TASK, base, troot)
        check_eq("numbers: the story total of waits is the files' human_wait_s", data["human_wait_s"], 14356)
        check_eq("numbers: question waits measured", data["human_wait"]["question_waits"], "measured")
        check_eq("numbers: S6 machine time = wall - question - the turn wait inside it", data["stage_machine_s"]["S6"], 16800 - 13756 - 600)
        text = RN.render(data)
        check_in("render: the stage table has both a wall time and a machine time column", "| Wall time | Machine time |", text)
        check_in("render: S6 prints wall 4h 40m and machine 40m", "| 4h 40m | 40m 44s |", text)
        check_not_in("a measured capture carries no 'not measured' note", "not measured by this capture", text)
        # an open question is named, its length is not invented
        put(base, "s-1", cost_file("s-1", [], human_wait_s=100, question_waits="measured", open_questions=2, human_waits=[]))
        check_in("E-C2: open questions are named in the wait line",
                 "2 questions still open: an open wait is not a known length", RN.render(RN.numbers(TASK, base, troot)))
        # E-D1 TEMPORAL: a cost file from before D2-C (no human_waits, no question_waits)
        put(base, "s-1", cost_file("s-1", runner, human_wait_s=600))
        old = RN.numbers(TASK, base, troot)
        check_eq("E-D1: an older cost file keeps human_wait_s as before", old["human_wait_s"], 600)
        check_eq("E-D1: and is named as not measured", old["human_wait"]["question_waits"], "not_measured")
        check_eq("E-D1: machine time is None", old["stage_machine_s"]["S6"], None)
        old_text = RN.render(old)
        check_in("E-D1: the wait line says question waits were not measured by this capture",
                 "human wait in session:** 10m 0s (question waits not measured by this capture)", old_text)
        check_in("E-D1: the stage table prints machine time as unknown, never the wall time again", "| 4h 40m | unknown |", old_text)
        # a `unmeasured` file (the forms could not be read) is not a measured zero either
        put(base, "s-1", cost_file("s-1", [], human_wait_s=0, question_waits="unmeasured", open_questions=0, human_waits=[]))
        check_eq("E-C1: an `unmeasured` capture is not measured", RN.numbers(TASK, base, troot)["human_wait"]["question_waits"], "not_measured")
        put(base, "s-1", cost_file("s-1", [], human_wait_s=7200))
        facts = RN.estimate_facts(RN.numbers(TASK, base, troot))
        check_in("estimate facts: the person's waiting is a driver and says it is a floor",
                 "human wait: 2h 0m (question waits not measured by this capture)", facts["drivers"])
        check_in("observations: the wait line says it is a floor too", "question waits not measured by this capture",
                 RN.observations(RN.numbers(TASK, base, troot)))
    finally:
        cleanup(td)


# ---------------------------------------------------------------------------------- K-D3 repair rounds

def repair_rounds():
    td = temp_dir("qa-retro-rounds-")
    try:
        base, troot = project(td)
        # 14 qa-automator records: four first windows (nobody has seen these cases), then ten that repeat one
        first = [("S5-qa-automator-%d" % n, [f"TC-0{n}1", f"TC-0{n}2"], {}) for n in range(1, 5)]
        repeats = [("S5-qa-automator-%d" % n, [f"area/TC-0{(n % 4) + 1}1"], {}) for n in range(5, 15)]
        controller_file(troot, first + repeats)
        rounds = RN.dispatch_rounds(troot)
        check_eq("K-D3: 14 records are 14 dispatches", len(rounds), 14)
        check_eq("K-D3: 14 records, 10 of which repeat an earlier scope -> 10 repair rounds",
                 sum(1 for r in rounds if r["rework"]), 10)
        check_eq("K-D3: the first window of a role is no round", [r["rework"] for r in rounds[:4]], [False] * 4)
        check_eq("the round is the ordinal among the records of the same stage and role", rounds[13]["round"], 14)
        # a new window (a scope no earlier dispatch had) is NOT a repair round
        controller_file(troot, first + [("S5-qa-automator-5", ["TC-900"], {})])
        check_eq("K-D3: a new window is no round", RN.dispatch_rounds(troot)[-1]["rework"], False)
        # identity, not equality: bare vs area spelling match; different areas, TC-1 vs TC-10, TS ids exactly
        controller_file(troot, [("S5-qa-automator-1", ["web/TC-007", "TC-001"], {}),
                                ("S5-qa-automator-2", ["api/TC-007"], {}),
                                ("S5-qa-automator-3", ["TC-0010"], {}),
                                ("S5-qa-automator-4", ["TC-007"], {}),
                                ("S5-qa-code-critic-1", ["TS-1"], {}), ("S5-qa-code-critic-2", ["TS-10"], {}),
                                ("S5-qa-code-critic-3", ["TS-1"], {})])
        got = {r["id"]: r["rework"] for r in RN.dispatch_rounds(troot)}
        check_eq("web/TC-007 then api/TC-007: two areas are two cases", got["S5-qa-automator-2"], False)
        check_eq("TC-001 is not TC-0010", got["S5-qa-automator-3"], False)
        check_eq("a bare id matches any area", got["S5-qa-automator-4"], True)
        check_eq("TS-1 is not TS-10; TS-1 again repeats TS-1",
                 (got["S5-qa-code-critic-2"], got["S5-qa-code-critic-3"]), (False, True))
        # E-D3: an empty scope is neither a repair nor a new window
        controller_file(troot, [("S5-qa-automator-1", ["TC-001"], {}), ("S5-qa-automator-2", [], {}),
                                ("S5-qa-automator-3", [" ", ""], {}), ("S5-qa-automator-4", ["TC-001"], {})])
        got = {r["id"]: r["rework"] for r in RN.dispatch_rounds(troot)}
        check_eq("E-D3: an empty scope is rework None", (got["S5-qa-automator-2"], got["S5-qa-automator-3"]), (None, None))
        check_eq("an empty scope between two records hides no repeat of the first", got["S5-qa-automator-4"], True)
        # stale and imported records are not dispatches; the role is parsed from the id when the record has none
        controller_file(troot, [("S5-qa-automator-1", ["TC-001"], {"status": "stale"}),
                                ("S5-qa-automator-2", ["TC-001"], {"imported": True}),
                                ("S5-qa-automator-3", ["TC-001"], {"role": None}),
                                ("S5-qa-automator-4", ["TC-001"], {"stage": None, "role": None})])
        rows = RN.dispatch_rounds(troot)
        check_eq("stale and imported records are skipped", [r["id"] for r in rows], ["S5-qa-automator-3", "S5-qa-automator-4"])
        check_eq("stage and role are parsed from the id when the record has none",
                 [(r["stage"], r["role"], r["rework"]) for r in rows], [("S5", "qa-automator", False), ("S5", "qa-automator", True)])
        # records are taken in the order they were made, whatever the order of the file
        (troot / "state" / "controller.json").write_text(json.dumps({"dispatches": {
            "S5-qa-automator-2": {"id": "S5-qa-automator-2", "stage": "S5", "role": "qa-automator", "scope": ["TC-001"], "dispatched_seq": 9},
            "S5-qa-automator-1": {"id": "S5-qa-automator-1", "stage": "S5", "role": "qa-automator", "scope": ["TC-001"], "dispatched_seq": 3}}}),
            encoding="utf-8")
        check_eq("record order, not file order, decides which is the repeat",
                 {r["id"]: r["rework"] for r in RN.dispatch_rounds(troot)}, {"S5-qa-automator-1": False, "S5-qa-automator-2": True})
        # K-D3b (F2 t-1753): a continuation is no repair round; an unaccepted result resumed on the same scope is one
        def resumed(reason, **extra):
            controller_file(troot, [("S5-qa-automator-1", ["TC-001"], {}),
                                    ("S5-qa-automator-2", ["TC-001"], dict({"parent_retry": "S5-qa-automator-1",
                                                                          "retry_reason": reason}, **extra))])
            return RN.dispatch_rounds(troot)
        for reason in ("checkpoint", "compaction", "turn_budget", "subagent_silent", "no_digest_at_exit", "host_error:ECONNRESET"):
            rows = resumed(reason)
            check_eq(f"K-D3b: a {reason} continuation is 0 repair rounds", (sum(1 for r in rows if r["rework"]), rows[1]["continuation"]), (0, True))
        for reason in ("unaccepted_result", "person_word", "factory_defect"):
            check_eq(f"K-D3b: a {reason} resume of the same scope is 1 repair round",
                     sum(1 for r in resumed(reason) if r["rework"]), 1)
        controller_file(troot, [("S5-qa-automator-1", ["TC-001"], {"status": "incomplete", "reason": "context compacted"}),
                                ("S5-qa-automator-2", ["TC-001"], {"relaunch_of": "S5-qa-automator-1"})])
        check_eq("K-D3b: an old record names no reason: the parent's status says compaction -> continuation",
                 [r["rework"] for r in RN.dispatch_rounds(troot)], [False, False])
        # no file, no dispatches key, junk: [] (E-D2 then labels the ordinal rule)
        (troot / "state" / "controller.json").write_text("[]", encoding="utf-8")
        check_eq("a controller file that is not an object holds no records", RN.dispatch_rounds(troot), [])
        (troot / "state" / "controller.json").unlink()
        check_eq("no controller file: no records", RN.dispatch_rounds(troot), [])
    finally:
        cleanup(td)


def rework_in_numbers():
    td = temp_dir("qa-retro-rework-")
    try:
        base, troot = project(td)
        pipeline_file(troot, {})
        # the cost-file route: ONE agent file served the handoffs -2 and -3 (a resumed agent), and nothing carries a dispatch id
        put(base, "s-1", cost_file("s-1", [agent("qa-automator", 500, {"Bash": 4})]))
        # E-D2: no dispatch records -> the ordinal rule, labelled
        data = RN.numbers(TASK, base, troot)
        check_eq("E-D2: no dispatch records -> the ordinal basis", (data["rework"]["basis"], data["dispatch_records"]), ("ordinal", []))
        check_in("E-D2: and the line says so", "(counted per role, dispatch records absent)", RN.render(data))
        controller_file(troot, [("S5-qa-automator-1", ["TC-001"], {}), ("S5-qa-automator-2", ["TC-001", "TC-002"], {}),
                                ("S5-qa-automator-3", ["TC-002"], {}), ("S5-qa-automator-4", [], {})])
        data = RN.numbers(TASK, base, troot)
        check_eq("K-D4: four records served by ONE agent file are 4 dispatches of the role",
                 (len(data["dispatches"]), data["by_role"]["qa-automator"]["dispatches"]), (1, 4))
        check_eq("K-D4: and of the stage", data["by_stage"]["S5"]["dispatches"], 4)
        check_eq("K-D3: -2 and -3 repeat an earlier scope: 2 rounds, by id",
                 (data["rework"]["basis"], data["rework"]["dispatches"], data["rework"]["rounds"]),
                 ("scope", 2, ["S5-qa-automator-2", "S5-qa-automator-3"]))
        check_eq("a round no cost row names is unpriced: the cost stays unknown, not $0", (data["rework"]["cost"], data["rework"]["priced_rounds"]), (None, 0))
        check_eq("E-D3: the empty-scope dispatch is named", data["rework"]["unscoped"], ["S5-qa-automator-4"])
        text = RN.render(data)
        check_in("the line carries the definition", "a dispatch whose scope an earlier dispatch of the same stage and role already had", text)
        check_in("E-D3: and names the dispatch it could not tell", "1 dispatch with an empty scope (S5-qa-automator-4)", text)
        check_not_in("the ordinal label is gone once records exist", "dispatch records absent", text)
        check_in("the role table counts 4", "| qa-automator | 4 |", text)
        check_in("the stage table counts 4", "| S5 | 4 |", text)
        check_in("observations name the rounds", "S5-qa-automator-2, S5-qa-automator-3", RN.observations(data))
        # the driver route: a journal row carries the dispatch id, so a round is priced by it (two rows of ONE dispatch sum)
        controller_file(troot, [("S5-qa-automator-1", ["TC-001"], {}), ("S5-qa-automator-2", ["TC-001"], {})])
        (base / "state" / "cost" / "s-1.json").unlink()
        put(base, "r-1", cost_file("r-1", []))
        put(base, "c-1", cost_file("c-1", []))
        (troot / "state" / "driver-runs.jsonl").write_text("\n".join(json.dumps(r) for r in [
            {"kind": "role", "role": "qa-automator", "dispatch": "S5-qa-automator-1", "stage": "S5", "session_id": "r-1",
             "num_turns": 3, "total_cost_usd": 1.0, "ts": "2026-11-02T05:10:00+00:00"},
            {"kind": "role", "role": "qa-automator", "dispatch": "S5-qa-automator-2", "stage": "S5", "session_id": "r-1",
             "num_turns": 3, "total_cost_usd": 3.0, "ts": "2026-11-02T06:10:00+00:00"},
            {"kind": "role", "role": "qa-automator", "dispatch": "S5-qa-automator-2", "stage": "S5", "session_id": "r-1",
             "num_turns": 1, "total_cost_usd": 3.5, "resumed": True, "ts": "2026-11-02T06:20:00+00:00"},
            {"kind": "conductor", "session_id": "c-1", "stage": "S5", "total_cost_usd": 1.0}]), encoding="utf-8")
        data = RN.numbers(TASK, base, troot)
        check_eq("driver route: the repair round is the second dispatch (it repeats TC-001), not a resume of the first",
                 (data["rework"]["dispatches"], data["rework"]["rounds"]), (1, ["S5-qa-automator-2"]))
        check_eq("and it is priced by the dispatch id: 2.0 (increment) + 0.5 (its resume)", data["rework"]["cost"], 2.5)
        check_eq("the resume row of the same dispatch is no extra round",
                 [(r["purpose"], r["round"], r["rework"]) for r in data["dispatches"]],
                 [("S5-qa-automator-1", 1, False), ("S5-qa-automator-2", 2, True), ("S5-qa-automator-2", 2, True)])
    finally:
        cleanup(td)


# ---------------------------------------------------------------------------------- K-D5 no phrase beside a cost

def no_usage_phrase():
    td = temp_dir("qa-retro-usage-")
    try:
        base, troot = project(td)
        pipeline_file(troot, {})
        phrase = "cost of qa-automator not estimated: its usage was not recorded."
        # K-D5: one zero-token file plus one file with tokens: the role is not missing, no phrase
        put(base, "s-1", cost_file("s-1", [agent("qa-automator", 0, {"Bash": 4}, file="agent-a.jsonl")]))
        put(base, "s-2", cost_file("s-2", [agent("qa-automator", 700, {"Bash": 9}, file="agent-b.jsonl")]))
        spend = RN.numbers(TASK, base, troot)["story"]
        check_eq("K-D5: a zero-token file beside a file with tokens: the role is not missing", spend["roles_missing"], [])
        check_not_in("K-D5: and no phrase is printed", phrase, spend["reason"])
        # K-D5: only zero-token files -> the phrase, and incomplete
        put(base, "s-2", cost_file("s-2", [agent("qa-automator", 0, {"Bash": 9}, file="agent-b.jsonl")]))
        data = RN.numbers(TASK, base, troot)
        check_eq("K-D5: only zero-token files: the role is missing", data["story"]["roles_missing"], ["qa-automator"])
        check_in("K-D5: the phrase names the role and says its cost is not estimated", phrase, data["story"]["reason"])
        check_eq("K-D5: and the story is incomplete", data["incomplete"], True)
        # a declared incomplete role with usage in another file of the story is not missing; with none anywhere it is
        # F1 (t-1753): a declaration with no zero-token entry of the role in the same file is a dispatch with no transcript
        put(base, "s-2", cost_file("s-2", [agent("qa-automator", 700, {}, file="agent-b.jsonl")], incomplete_agents=["qa-factory:qa-automator"]))
        gap = RN.numbers(TASK, base, troot)
        check_eq("F1a: declared incomplete, no zero-token entry in its file: missing though a priced file carries it",
                 gap["story"]["roles_missing"], ["qa-automator"])
        check_in("F1a: and the 'not estimated' phrase is printed", phrase, gap["story"]["reason"])
        put(base, "s-2", cost_file("s-2", [agent("qa-automator", 700, {}, file="agent-b.jsonl"),
                                           agent("qa-automator", 0, {}, file="agent-c.jsonl")],
                                   incomplete_agents=["qa-factory:qa-automator"]))
        check_eq("F1b: the resumed case (a zero-token entry beside a tokens entry) is not missing",
                 RN.numbers(TASK, base, troot)["story"]["roles_missing"], [])
        put(base, "s-2", cost_file("s-2", [agent("qa-automator", 0, {}, file="agent-b.jsonl")], incomplete_agents=["qa-factory:qa-automator"]))
        check_eq("a declared incomplete role with no usage anywhere is missing",
                 RN.numbers(TASK, base, troot)["story"]["roles_missing"], ["qa-automator"])
        # E-C5: an idle agent (tools 0, tokens 0) is not a gap; one with tool calls and no usage is
        put(base, "s-1", cost_file("s-1", [agent("qa-automator", 0, {}, file="agent-a.jsonl")]))
        put(base, "s-2", cost_file("s-2", []))
        idle = RN.numbers(TASK, base, troot)["story"]
        check_eq("E-C5: an idle zero-token agent is not missing", idle["roles_missing"], [])
        check_not_in("E-C5: and no phrase is printed", phrase, idle["reason"])
        put(base, "s-1", cost_file("s-1", [agent("qa-automator", 0, {"Bash": 2}, file="agent-a.jsonl")]))
        check_eq("E-C5: tool calls with no usage is still a gap",
                 RN.numbers(TASK, base, troot)["story"]["roles_missing"], ["qa-automator"])
        # a driver row with a cost is a cost record of the role
        put(base, "s-1", cost_file("s-1", [agent("qa-automator", 0, {"Bash": 4}, file="agent-a.jsonl")]))
        put(base, "s-2", cost_file("s-2", []))
        put(base, "r-1", cost_file("r-1", []))
        (troot / "state" / "driver-runs.jsonl").write_text(json.dumps(
            {"kind": "role", "role": "qa-automator", "dispatch": "S5-qa-automator-1", "stage": "S5", "session_id": "r-1",
             "num_turns": 3, "total_cost_usd": 1.0}), encoding="utf-8")
        check_eq("a driver row with a cost is a cost record: the role is not missing",
                 RN.numbers(TASK, base, troot)["story"]["roles_missing"], [])
    finally:
        cleanup(td)


def main():
    machine_time()
    numbers_waits()
    repair_rounds()
    rework_in_numbers()
    no_usage_phrase()
    finish("test_retro_wait_rework")


if __name__ == "__main__":
    main()
