#!/usr/bin/env python3
"""Where a story stands: one function, three readers (t-310).

Owner, 02.10: "Users must see which stage and how far it has gone. S5 may consist of several windows, each with
two automator-critic rounds. It must be visible where we are." The driver runs its roles as `claude -p`
subprocesses, so they are not in the desktop's task list; the story's own records have to say it. The shapes of
the dispatches below are the ones TP1-15045's controller.json held (cmp2r, 02.10): S5's windows with their
superseded critic and its retry, S6's manual runner blocks, gate B asked at 04:18 and still open at 11:21.

Keys: K1 the dict at three positions; K2 the line (length, words, `human_text`); K3 windows and rounds;
K4 a stale `running` is never shown as live; K5 the price (one figure, a range, "recorded only"); K6 the driver
prints one `[progress]` line per transition; K7 the dashboard card draws the block; K8 the command line refuses
with the path. Edge behaviour of the spec is in `edges()`.
"""
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import story_progress as SP  # noqa: E402

TASK = "TP1-15045"
T0 = 1790900000.0                       # an instant in the story's own time (2026-10-02, UTC)
KEYS = ("task", "stage", "position", "running", "waiting", "spend", "done", "remaining")
NONE_SPEND = {"recorded_usd": None, "range": None, "sources_agree": None, "basis": "none", "dispatches": 0}
ALIVE = lambda *_args: {"state": "alive", "evidence": ["its transcript was written 9s ago"]}  # noqa: E731
STAGES = {f"S{i}": n for i, n in enumerate(
    ["Start and preflight", "Context and grounding", "Understanding and size", "Plan", "Cases", "Automation",
     "Run", "Triage", "Results", "Closure and retro"])}
CASES = [f"{TASK}_TC_{n:03d}" for n in range(1, 19)]


def hhmm(epoch) -> str:
    return time.strftime("%H:%M", time.localtime(epoch))


def disp(ident, stage, role, status="accepted", scope=(), **extra) -> dict:
    return dict({"id": ident, "stage": stage, "role": role, "status": status, "scope": list(scope)}, **extra)


def story(root: Path, dispatches=(), done=(), *, asked=None, rows=(), started=None, decisions=None,
          gates=None, next_action=None, task=TASK, driver_state=None) -> Path:
    """A project with one story, shaped like cmp2r's: `dispatches` in order, the stages in `done` finished,
    `started` {dispatch: epoch} the controller's own `dispatch` events, `asked` the driver's open question."""
    (root / "qa-factory").mkdir(parents=True, exist_ok=True)
    (root / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
    task_root = root / "qa-factory" / "artifacts" / task
    (task_root / "state").mkdir(parents=True, exist_ok=True)
    (task_root / "pipeline.json").write_text(json.dumps(
        {"ticket": task, "stages": {s: {"status": "done"} for s in done}, "gates": gates or {}}), encoding="utf-8")
    (task_root / "state" / "controller.json").write_text(json.dumps(
        {"dispatches": {d["id"]: d for d in dispatches}, "stages": {}, "decisions": decisions or {},
         "next_action": next_action, "scope": CASES}), encoding="utf-8")
    events = [{"type": "dispatch", "created_at": (started or {}).get(d["id"], T0), "payload": {"id": d["id"]}}
              for d in dispatches if d["id"] in (started or {})]
    (task_root / "state" / "events.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    state = dict(driver_state or {}, asked=asked or {})
    (task_root / "state" / "driver-state.json").write_text(json.dumps(state), encoding="utf-8")
    (task_root / "state" / "driver-runs.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return task_root


def run_row(dispatch, role, cost, session="s-1", exit_code=0, kind="role") -> dict:
    return {"ts": "2026-10-02T04:00:00+00:00", "kind": kind, "role": role, "dispatch": dispatch, "stage": "S5",
            "session_id": session, "num_turns": 5, "total_cost_usd": cost, "exit_code": exit_code}


def pick(answer: dict) -> dict:
    return {k: answer[k] for k in KEYS}


def human_problems(line: str) -> list:
    import human_text
    return [p["rule"] for p in human_text.problems(line, kind="report")]


# ------------------------------------------------------------------------------------- K1 + K2: positions

def positions() -> None:
    """The dict (and the line) at the three places the owner named: a window's round, gate B, an S6 manual block."""
    import test_s5_process as S5
    # --- S5, window 2 of 2 planned, the second repair-cycle's critic at work: the real controller's windows
    root = temp_dir("t310-window-")
    try:
        cases = ("TC-1", "TC-2", "TC-3", "TC-4", "TC-5", "TC-6")
        c = S5.s5_task(root, cases, {"TC-1": "e2e-ui", "TC-2": "e2e-ui"})
        first, second = ("TC-3", "TC-4", "TC-5", "TC-6"), ("TC-1", "TC-2")
        S5.dispatch(c, root, "S5-qa-automator-1", scope=first)
        S5.dispatch(c, root, "S5-qa-code-critic-1", role="qa-code-critic", scope=first)
        S5.dispatch(c, root, "S5-qa-automator-2", scope=second)
        S5.dispatch(c, root, "S5-qa-code-critic-2", role="qa-code-critic", scope=second)
        S5.dispatch(c, root, "S5-qa-automator-3", scope=second, rework_of="S5-qa-automator-2",
                    repair_cause="test_defect")
        S5.dispatch(c, root, "S5-qa-code-critic-3", role="qa-code-critic", scope=second, accept=False)
        events = [json.loads(l) for l in (root / "state" / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        began = next(e["created_at"] for e in events
                     if e["type"] == "dispatch" and e["payload"]["id"] == "S5-qa-code-critic-3")
        got = SP.progress(root, now=began + 14 * 60 + 5, liveness=ALIVE)
        check_eq("S5: the dict at window 2, round 1 of 2, the critic at work", pick(got), {
            "task": root.name, "stage": {"id": "S5", "name": "Automation", "status": "running"},
            "position": {"kind": "window", "window": 2, "windows_total": 2, "windows_done": 1, "round": 1,
                         "rounds_total": 2, "round_role": "critic", "mechanical_fix": False,
                         "dispatch": "S5-qa-code-critic-3", "other_windows_open": 0},
            "running": {"dispatch": "S5-qa-code-critic-3", "role": "qa-code-critic", "started_at": SP._iso(began),
                        "minutes": 14, "proven_alive": True, "liveness": "alive",
                        "evidence": ["its transcript was written 9s ago"]},
            "waiting": None, "spend": NONE_SPEND, "done": ["S0", "S1", "S2", "S3", "S4"],
            "remaining": ["S6", "S7", "S8", "S9"]})
        check_eq("S5: the line", got["line"],
                 "S5 Automation · window 2 of 2 planned · round 1 of 2 (critic) · the code critic "
                 "running 14 min · no cost recorded yet · done S0–S4")
        lines = [got["line"]]
    finally:
        cleanup(root)

    # --- gate B, asked at 04:18 and still open: cmp2r as it stood at 11:21
    asked_at = "2026-10-02T04:18:15+00:00"
    asked_epoch = SP._epoch(asked_at)
    price = {"status": "agrees", "price_low_usd": 43.6909044, "price_high_usd": 43.6909044,
             "totals": {"a": 43.6909044, "b": 43.6909044}}
    rows = [run_row("S5-qa-automator-1", "qa-automator", 1.0), run_row("S5-qa-automator-1", "qa-automator", 1.2),
            run_row("S6-qa-runner-1", "qa-runner", 2.0), run_row("", "conductor", 0.3, kind="conductor")]
    done = [f"S{i}" for i in range(9)]
    root = temp_dir("t310-gate-")
    try:
        shape = [disp("S5-qa-automator-1", "S5", "qa-automator"), disp("S6-qa-runner-1", "S6", "qa-runner"),
                 disp("S8-qa-doc-scribe-1", "S8", "qa-doc-scribe")]
        tr = story(root, shape, done, asked={"kind": "gate_B", "stage": "S8", "dispatch": "", "at": asked_at},
                   rows=rows, next_action={"action": "await_gate", "gate": "B"},
                   gates={"A": {"gate": "A", "status": "approved"}})
        got = SP.progress(tr, now=asked_epoch + 52 * 60 + 9, price=price)
        check_eq("gate B: the dict", pick(got), {
            "task": TASK, "stage": {"id": "S9", "name": "Closure and retro", "status": "waiting"},
            "position": {"kind": "gate", "gate": "B"}, "running": None,
            "waiting": {"kind": "gate", "gate": "B", "question": None, "since": asked_at, "minutes": 52},
            "spend": {"recorded_usd": 43.69, "range": [43.69, 43.69], "sources_agree": True, "basis": "both",
                      "dispatches": 2},
            "done": done, "remaining": []})
        check_eq("gate B: the line", got["line"],
                 f"S9 Closure and retro · waiting for your word at gate B since {hhmm(asked_epoch)} (52 min) "
                 "· $43.69 so far · done S0–S8")
        lines.append(got["line"])
    finally:
        cleanup(root)

    # --- S6, the second runner (the first block of the manual half) recorded at T0
    root = temp_dir("t310-block-")
    try:
        shape = [disp("S5-qa-automator-1", "S5", "qa-automator"),
                 disp("S6-qa-runner-1", "S6", "qa-runner", scope=CASES[:2], execution_kind="automation"),
                 disp("S6-qa-runner-2", "S6", "qa-runner", "running", scope=CASES[4:9], execution_kind="manual",
                      manual_case_ids=CASES[4:9], purpose="manual")]
        tr = story(root, shape, [f"S{i}" for i in range(6)], started={"S6-qa-runner-2": T0}, rows=rows,
                   gates={"A": {"gate": "A", "status": "approved"}})
        got = SP.progress(tr, now=T0 + 9 * 60 + 1, liveness=ALIVE, price=price)
        check_eq("S6: the dict at manual block 1, its cases named", pick(got), {
            "task": TASK, "stage": {"id": "S6", "name": "Run", "status": "running"},
            "position": {"kind": "block", "block": 1, "blocks_total": None,
                         "cases": ["TC_005", "TC_006", "TC_007", "TC_008", "TC_009"],
                         "dispatch": "S6-qa-runner-2"},
            "running": {"dispatch": "S6-qa-runner-2", "role": "qa-runner", "started_at": SP._iso(T0), "minutes": 9,
                        "proven_alive": True, "liveness": "alive", "evidence": ["its transcript was written 9s ago"]},
            "waiting": None,
            "spend": {"recorded_usd": 43.69, "range": [43.69, 43.69], "sources_agree": True, "basis": "both",
                      "dispatches": 2},
            "done": [f"S{i}" for i in range(6)], "remaining": ["S7", "S8", "S9"]})
        check_eq("S6: the line says the total is not known (no plan to count the blocks left from)", got["line"],
                 "S6 Run · manual block 1 (total not known yet): TC_005, TC_006, TC_007, TC_008, TC_009 "
                 "· the runner running 9 min · $43.69 so far · done S0–S5")
        lines.append(got["line"])
    finally:
        cleanup(root)

    # --- K2: each line fits, names the stage, the position and the money, and breaks no rule for a person
    # the control: the same check, with the same call, DOES reject a line that names a dispatch (the spec's
    # own example line did) - so an empty answer above is a clean line, not a check that cannot fail
    check_eq("K2 control: a line naming a dispatch is refused by the same check",
             human_problems("S5 Automation · S5-qa-code-critic-6 running 14 min"), ["dispatch_id"])
    for line in lines:
        check(f"K2: at most {SP.LINE_MAX} characters ({len(line)})", len(line) <= SP.LINE_MAX, line)
        check_eq("K2: human_text finds nothing in it", human_problems(line), [])
    check("K2: each carries its stage name", all(n in l for n, l in zip(("Automation", "Closure and retro", "Run"), lines)))
    check("K2: each carries its position",
          all(p in l for p, l in zip(("window 2 of 2", "gate B", "manual block 1"), lines)))
    check("K2: each carries the spend or says there is none",
          all("so far" in l or "no cost recorded yet" in l for l in lines))
    check_not_in("K2: no dispatch id in a line a person reads", "S5-qa", " ".join(lines))


# ---------------------------------------------------------------------------------------- K3 windows, rounds

def windows_and_rounds() -> None:
    """Superseded + retry is ONE round; a window open beside another is named; a total nobody holds is None."""
    root = temp_dir("t310-rounds-")
    try:
        w1, w2 = CASES[2:6], CASES[:2]
        shape = [disp("S5-qa-automator-1", "S5", "qa-automator", scope=w1),
                 disp("S5-qa-code-critic-1", "S5", "qa-code-critic", scope=w1),
                 # window 1 repaired once: the author's first attempt ran out of turns and was resumed
                 disp("S5-qa-automator-2", "S5", "qa-automator", "superseded", scope=w1,
                      rework_of="S5-qa-automator-1"),
                 disp("S5-qa-automator-3", "S5", "qa-automator", "running", scope=w1,
                      rework_of="S5-qa-automator-1", parent_retry="S5-qa-automator-2")]
        tr = story(root, shape, [f"S{i}" for i in range(5)], started={"S5-qa-automator-3": T0},
                   gates={"A": {"gate": "A", "status": "approved"}})
        got = SP.progress(tr, now=T0 + 120, liveness=ALIVE)
        pos = got["position"]
        check_eq("K3: a superseded dispatch and its retry are one round (not two)", pos["round"], 1)
        check_eq("K3: the round cap is the controller's own", pos["rounds_total"], 2)
        check_eq("K3: the author is at work", pos["round_role"], "author")
        check_eq("K3: nobody holds the plan here, so the total of windows is not invented", pos["windows_total"], None)
        check_in("K3: and the line says so", "window 1 (total not known yet)", got["line"])
        check_not_in("K3: it never says 'of 1 planned' from the one group it has seen", "planned", got["line"])
        check_in("K3: round 1 of 2 in words", "round 1 of 2 (author)", got["line"])

        # a one-case rework of window 1 is window 1's work, not a window of its own
        shape.append(disp("S5-qa-automator-4", "S5", "qa-automator", "accepted", scope=w1[:1],
                          rework_of="S5-qa-automator-1"))
        tr = story(root, shape, [f"S{i}" for i in range(5)], started={"S5-qa-automator-3": T0},
                   gates={"A": {"gate": "A", "status": "approved"}})
        check_eq("K3: a narrower rework joins its window", SP.progress(tr, now=T0 + 1, liveness=ALIVE)["position"]["window"], 1)

        # two windows open at once: the one running last is named, the other counted
        shape = [disp("S5-qa-automator-1", "S5", "qa-automator", "running", scope=w1),
                 disp("S5-qa-automator-2", "S5", "qa-automator", "running", scope=w2)]
        tr = story(root, shape, [f"S{i}" for i in range(5)], started={"S5-qa-automator-1": T0, "S5-qa-automator-2": T0 + 60},
                   gates={"A": {"gate": "A", "status": "approved"}})
        got = SP.progress(tr, now=T0 + 600, liveness=ALIVE)
        check_eq("K3: the window named is the one running last", got["position"]["window"], 2)
        check_eq("K3: one other window is open", got["position"]["other_windows_open"], 1)
        check_in("K3: and the line says it", "1 other window open", got["line"])
        check_eq("K3: windows done counts closed windows only", got["position"]["windows_done"], 0)
        check_in("K3: a first pass is called one", "first pass (author)", got["line"])
    finally:
        cleanup(root)

    # the plan implies the total when the controller holds it, and a plan that shrank is not trusted over
    # the windows already seen (the total is then unknown, not the smaller number)
    import test_s5_process as S5
    root = temp_dir("t310-planned-")
    try:
        c = S5.s5_task(root, ("TC-1", "TC-2", "TC-3"), {})
        S5.dispatch(c, root, "S5-qa-automator-1", scope=("TC-1", "TC-2", "TC-3"), accept=False)
        got = SP.progress(root, now=T0, liveness=ALIVE)
        check_eq("K3: a planned total is the controller's (one api window of three cases)",
                 got["position"]["windows_total"], 1)
        check_in("K3: said as planned", "window 1 of 1 planned", got["line"])
        # the plan holds ONE window of the three cases, yet two windows were worked (the plan was cut after the
        # first dispatch): the records hold more windows than the plan implies
        c2 = temp_dir("t310-planned-2-")
        try:
            c = S5.s5_task(c2, ("TC-1", "TC-2", "TC-3"), {})
            S5.dispatch(c, c2, "S5-qa-automator-1", scope=("TC-1", "TC-2"))
            S5.dispatch(c, c2, "S5-qa-automator-2", scope=("TC-3",), accept=False)
            got = SP.progress(c2, now=T0, liveness=ALIVE)
        finally:
            cleanup(c2)
        check_eq("K3: more windows seen than the plan holds -> the total is unknown", got["position"]["windows_total"], None)
    finally:
        cleanup(root)


# ------------------------------------------------------------------------------------------ K4 a stale record

def stale_record() -> None:
    """The rehearsal's 05:38 death: the record says `running`, the driver is gone. Never 'running 7 h'."""
    root = temp_dir("t310-stale-")
    try:
        shape = [disp("S6-qa-runner-1", "S6", "qa-runner", scope=CASES[:2], execution_kind="automation"),
                 disp("S6-qa-runner-2", "S6", "qa-runner", "running", scope=CASES[4:6], execution_kind="manual",
                      manual_case_ids=CASES[4:6], purpose="manual")]
        rows = [run_row("S6-qa-runner-2", "qa-runner", 0.4, exit_code=0)]     # the session ended; the record did not move
        tr = story(root, shape, [f"S{i}" for i in range(6)], started={"S6-qa-runner-2": T0}, rows=rows,
                   gates={"A": {"gate": "A", "status": "approved"}})
        got = SP.progress(tr, now=T0 + 7 * 3600)
        run = got["running"]
        check_eq("K4: nothing proves the role alive", (run["proven_alive"], run["liveness"]), (False, "returned"))
        check_eq("K4: so there are no minutes at all", run["minutes"], None)
        # CX1-3 (deliberate rewrite of this pin): the driver's own row says the session ended, so the line says the role
        # returned and the record is still open - a fact, never "recorded running ..., not proven alive" (see
        # `returned_session_is_said_so`)
        ended = SP._epoch(rows[0]["ts"])
        check_in("K4: the line says the role returned and the record is still open",
                 f"returned {hhmm(ended)}, its dispatch still open", got["line"])
        check_not_in("K4: a journalled end is not 'not proven alive'", "not proven alive", got["line"])
        for word in ("running 7", "7 h", "420 min", "running 4"):
            check_not_in(f"K4: never '{word}'", word, got["line"])
        # no evidence of any kind (no journal row either): the same words, the liveness named `unknown`
        tr = story(root, shape, [f"S{i}" for i in range(6)], started={"S6-qa-runner-2": T0}, rows=[],
                   gates={"A": {"gate": "A", "status": "approved"}})
        got = SP.progress(tr, now=T0 + 7 * 3600)
        check_eq("K4: no evidence is `unknown`, not alive", got["running"]["liveness"], "unknown")
        check_in("K4: and the words are the same", "not proven alive", got["line"])
        # a role recorded a minute ago has had no time to show a transcript: said as that, not as a death
        got = SP.progress(tr, now=T0 + 40)
        check_in("K4: a fresh record has no proof of work yet", f"started {hhmm(T0)}, no proof of work yet", got["line"])
        check_eq("K4: and still no minutes", got["running"]["minutes"], None)
        # with proof, the minutes are measured against the one clock the call was given
        check_eq("K4: proven alive -> minutes", SP.progress(tr, now=T0 + 14 * 60 + 59, liveness=ALIVE)["running"]["minutes"], 14)
        # a legacy story: no `dispatch` event, no start time anywhere -> no duration, no error
        tr = story(root, shape, [f"S{i}" for i in range(6)], started={}, rows=[],
                   gates={"A": {"gate": "A", "status": "approved"}})
        got = SP.progress(tr, now=T0 + 99999, liveness=ALIVE)
        check_eq("K4: a legacy record holds no start: minutes null", (got["running"]["started_at"], got["running"]["minutes"]), (None, None))
        check_in("K4: and the line omits the duration", "the runner running ·", got["line"])
        check_not_in("K4: no 'min' of a start nobody recorded", " min ", got["line"])
        got = SP.progress(tr, now=T0 + 99999)
        check_in("K4: a legacy record not proven alive says that", "recorded running, not proven alive", got["line"])
    finally:
        cleanup(root)


def returned_session_is_said_so() -> None:
    """The Codex smoke of 10.10 (SMOKE-1): the scout's `codex exec` ended (exit 0), the driver cleared its `in_flight`
    entry, wrote the end row and asked the S1 review question - and the line read "the scout recorded running since
    15:47, not proven alive" with the end row ten seconds old on disk. The liveness reader answered `returned` all
    along; the line did not say it. Now: "the scout returned 15:55, its dispatch still open". The rows are the ones
    the Codex driver writes (`host`, `usage`, a thread id as the session, no cost); a Claude row reads the same."""
    import dispatch_liveness as DL
    root = temp_dir("t-codex-returned-")
    thread = "01a12611-aa9e-78d3-8c05-54de60d216f0"
    launched = {"ts": SP._iso(T0), "kind": "launched", "call": "role", "role": "qa-scout", "dispatch_id": "S1-qa-scout-1",
                "stage": "S1", "started_at": SP._iso(T0), "model": "host-default", "retry": 0, "host": "codex"}
    ended = {"ts": SP._iso(T0 + 462), "kind": "role", "role": "qa-scout", "dispatch": "S1-qa-scout-1", "stage": "S1",
             "session_id": thread, "num_turns": 17, "total_cost_usd": None, "duration_ms": 462357, "resumed": False,
             "exit_code": 0, "is_error": False, "model": "host-default", "host": "codex", "subtype": "success",
             "infra": None, "infra_rule": None, "retry": 0,
             "usage": {"input_tokens": 720821, "cached_input_tokens": 666368, "cache_write_input_tokens": 0,
                       "output_tokens": 5011}}
    asked = {"kind": "s1_review", "stage": "S1", "dispatch": "S1-qa-scout-1", "at": SP._iso(T0 + 472)}
    shape = [disp("S1-qa-scout-1", "S1", "qa-scout", "running")]
    real_created = DL.process_created_at
    DL.process_created_at = lambda pid: T0 - 60          # a live child of the driver: created before its entry
    try:
        tr = story(root, shape, ["S0"], started={"S1-qa-scout-1": T0}, rows=[launched, ended], asked=asked)
        got = SP.progress(tr, now=T0 + 480)
        run = got["running"]
        check_eq("K4 returned: the reader's verdict is the driver's end row",
                 (run["liveness"], run["proven_alive"], run["minutes"]), ("returned", False, None))
        check_in("K4 returned: the evidence names the row", "driver-runs.jsonl", " ".join(run["evidence"]))
        check_in("K4 returned: the line says the role returned, when, and that the record is still open",
                 f"the scout returned {hhmm(T0 + 462)}, its dispatch still open", got["line"])
        check_in("K4 returned: beside the open question", "waiting for your answer (s1 review)", got["line"])
        for word in ("not proven alive", "running 8", "recorded running", "no proof of work yet"):
            check_not_in(f"K4 returned: never '{word}'", word, got["line"])
        check_eq("K4 returned: the line passes the human-text rules", human_problems(got["line"]), [])
        check_not_in("K4 returned: no private key of the reader in the dict", "_returned", json.dumps(run))
        # the same story while the role still runs: the driver's in_flight entry with a live pid, no end row yet
        tr = story(root, shape, ["S0"], started={"S1-qa-scout-1": T0}, rows=[launched],
                   driver_state={"in_flight": {"S1-qa-scout-1": {"dispatch_id": "S1-qa-scout-1", "pid": os.getpid(),
                                                                 "started_at": SP._iso(T0)}}})
        got = SP.progress(tr, now=T0 + 8 * 60 + 5)
        check_eq("K4 returned: before the end row, a live pid is the proof",
                 (got["running"]["liveness"], got["running"]["minutes"]), ("alive", 8))
        check_in("K4 returned: and the line says running", "the scout running 8 min", got["line"])
        # the launched row alone (no exit code) proves nothing: the words of a record nobody proved
        tr = story(root, shape, ["S0"], started={"S1-qa-scout-1": T0}, rows=[launched])
        got = SP.progress(tr, now=T0 + 7 * 3600)
        check_eq("K4 returned: a launched row without an exit code is no return", got["running"]["liveness"], "unknown")
        check_in("K4 returned: so today's words", "not proven alive", got["line"])
        # a return the hook journalled on the dispatch itself (`returned_at`, the Claude host) reads the same way
        tr = story(root, [disp("S1-qa-scout-1", "S1", "qa-scout", "running", returned_at=T0 + 300)], ["S0"],
                   started={"S1-qa-scout-1": T0}, rows=[])
        got = SP.progress(tr, now=T0 + 600)
        check_in("K4 returned: a journalled return says returned too",
                 f"the scout returned {hhmm(T0 + 300)}, its dispatch still open", got["line"])
        # edge 15: a return that holds no usable time says so without one; edge 14: a process known gone is said first
        for last_at in (None, "not a time", True):
            stub = lambda project, task, known, now, _at=last_at: {"state": "returned", "last_at": _at, "evidence": ["x"]}  # noqa: E731
            got = SP.progress(tr, now=T0 + 600, liveness=stub)
            check_in(f"K4 returned: a return with last_at {last_at!r} says it without a time",
                     "the scout returned, its dispatch still open", got["line"])
            check_not_in(f"K4 returned: ...and without a made-up hour ({last_at!r})", "returned 0", got["line"])
        gone = lambda project, task, known, now: {"state": "returned", "last_at": T0 + 300, "process": "gone", "evidence": []}  # noqa: E731
        check_in("K4 returned: the process known gone is said before the return",
                 "the process is gone", SP.progress(tr, now=T0 + 600, liveness=gone)["line"])
        native = lambda project, task, known, now: {"state": "returned", "last_at": T0 + 300, "evidence": [
            "the host's own rollout for /root/x ends with task_complete at 2026-10-02T04:00:00Z (C:\\Users\\dev5\\b.jsonl)"]}  # noqa: E731
        line = SP.progress(tr, now=T0 + 600, liveness=native)["line"]
        check_in("K4 returned: the host's own rollout is said the same way", f"returned {hhmm(T0 + 300)}, its dispatch still open", line)
        check_not_in("K4 returned: the rollout's path is evidence in the dict, never in the line", "Users", line)
    finally:
        DL.process_created_at = real_created
        cleanup(root)


def stale_record_pid() -> None:
    """t-329 item 1 (B-268), K4 extended: the driver's `in_flight` entry names the role's process. A live pid proves the
    role at work ("running N min"); a gone pid is a fact, said as one ("the process is gone"), never "not proven alive";
    an entry that proves nothing (no pid - a legacy one; a pid that cannot be asked) keeps today's wording; two entries
    are two answers, each on its own. A dead pid is a real process that was started and waited for."""
    import dispatch_liveness as DL
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    dead_pid = dead.pid
    check("K4 fixture: this very process is alive, the finished child is gone", DL.process_alive(os.getpid()) is True
          and DL.process_alive(dead_pid) is False, f"{DL.process_alive(os.getpid())} {DL.process_alive(dead_pid)}")
    check_eq("K4 edge: a pid that cannot be asked is neither (None), never alive",
             [DL.process_alive(x) for x in (None, True, 0, -3, "12", 1.5)], [None] * 6)
    root = temp_dir("t329-pid-")
    # The fixture's clock is the story's own (T0, a fixed instant) and this very process was created at the real now,
    # AFTER it: t-335 A-n1 would read the live pid as taken over by a later process. The creation time is pinned to
    # before the entry's start here (what a live child of the driver is); the reuse check has its own scenario
    # (`pid_denied_and_reused`) with the real clock.
    real_created = DL.process_created_at
    DL.process_created_at = lambda pid: T0 - 60
    try:
        shape = [disp("S6-qa-runner-1", "S6", "qa-runner", scope=CASES[:2], execution_kind="automation"),
                 disp("S6-qa-runner-2", "S6", "qa-runner", "running", scope=CASES[4:6], execution_kind="manual",
                      manual_case_ids=CASES[4:6], purpose="manual")]

        def at(entry, rows=()):
            return story(root, shape, [f"S{i}" for i in range(6)], started={"S6-qa-runner-2": T0}, rows=list(rows),
                         gates={"A": {"gate": "A", "status": "approved"}},
                         driver_state={"in_flight": {"S6-qa-runner-2": entry}} if entry is not None else None)

        def entry(pid, **extra):
            return dict({"dispatch_id": "S6-qa-runner-2", "pid": pid, "started_at": SP._iso(T0)}, **extra)

        got = SP.progress(at(entry(os.getpid())), now=T0 + 14 * 60 + 59)
        check_eq("K4 pid: alive -> proven alive, minutes from the entry's own start",
                 (got["running"]["proven_alive"], got["running"]["liveness"], got["running"]["minutes"]), (True, "alive", 14))
        check_in("K4 pid: the line says running N min", "the runner running 14 min", got["line"])
        got = SP.progress(at(entry(dead_pid)), now=T0 + 7 * 3600)
        check_eq("K4 pid: gone -> not alive, no minutes", (got["running"]["proven_alive"], got["running"]["minutes"]), (False, None))
        check_in("K4 pid: the line says the process is gone", f"the runner started {hhmm(T0)}, the process is gone", got["line"])
        check_not_in("K4 pid: never 'not proven alive' for a process known gone", "not proven alive", got["line"])
        check_not_in("K4 pid: and never 'running 7' or '7 h'", "running 7", got["line"])
        check_not_in("K4 pid: the dict holds no private key of the reader", "_gone", json.dumps(got["running"]))
        # the session had ended AND the entry stayed: still a gone process, and the liveness is the controller's own
        got = SP.progress(at(entry(dead_pid), rows=[run_row("S6-qa-runner-2", "qa-runner", 0.4)]), now=T0 + 7 * 3600)
        check_eq("K4 pid: gone beside a driver row: the same words, the verdict the row gives",
                 (got["running"]["liveness"], "the process is gone" in got["line"]), ("returned", True))
        # a young record of a gone process is still said as gone (a process we saw is not 'too soon to tell')
        check_in("K4 pid: gone, 40 s after the start", "the process is gone", SP.progress(at(entry(dead_pid)), now=T0 + 40)["line"])
        # entries that prove nothing: today's wording, no error
        for label, held in (("legacy: no pid", {"dispatch_id": "S6-qa-runner-2", "started_at": SP._iso(T0)}),
                            ("pid not a number", entry("4242")), ("pid zero", entry(0)), ("pid True", entry(True))):
            got = SP.progress(at(held), now=T0 + 7 * 3600)
            check_in(f"K4 pid edge ({label}): today's wording", f"recorded running since {hhmm(T0)}, not proven alive", got["line"])
            check_not_in(f"K4 pid edge ({label}): and no claim about the process", "process", got["line"])
        # a read that fails (the helper cannot ask) is today's wording, not a stop and not 'gone'
        saved = DL.process_alive
        DL.process_alive = lambda pid: None
        try:
            got = SP.progress(at(entry(os.getpid())), now=T0 + 7 * 3600)
        finally:
            DL.process_alive = saved
        check_in("K4 pid edge (the query fails): today's wording", f"recorded running since {hhmm(T0)}, not proven alive", got["line"])
        # two windows in flight: each dispatch is judged by its own entry
        story(root, shape, [f"S{i}" for i in range(6)], driver_state={"in_flight": {
            "S5-qa-automator-1": {"dispatch_id": "S5-qa-automator-1", "pid": os.getpid(), "started_at": SP._iso(T0)},
            "S5-qa-automator-2": {"dispatch_id": "S5-qa-automator-2", "pid": dead_pid, "started_at": SP._iso(T0)}}})
        verdicts = {name: DL.state(root, TASK, {"id": name, "role": "qa-automator"}, T0 + 100)
                    for name in ("S5-qa-automator-1", "S5-qa-automator-2", "S5-qa-automator-3")}
        check_eq("K4 pid: two entries, each on its own (alive / gone / no entry)",
                 [(v["state"], v.get("process")) for v in verdicts.values()],
                 [("alive", None), ("unknown", "gone"), ("unknown", None)])
        check_in("K4 pid: the gone one says so in its evidence", "is gone", " ".join(verdicts["S5-qa-automator-2"]["evidence"]))
        check("K4 pid: a missing driver-state.json reads as no entry", DL.in_flight_entry(root / "nowhere", TASK, "x") is None)
        # the entry a caller already holds is used as it is (no second read, no dependence on the folder's name)
        held = DL.state(root / "nowhere", "NOT-THE-FOLDER", {"id": "x", "in_flight": {"dispatch_id": "x", "pid": os.getpid()}}, T0)
        check_eq("K4 pid: a handed-over entry with a live pid proves alive", held["state"], "alive")
        held = DL.state(root / "nowhere", "NOT-THE-FOLDER", {"id": "x", "in_flight": {"dispatch_id": "x", "pid": dead_pid}}, T0)
        check_eq("K4 pid: ...and with a gone pid says so, without claiming anything else", (held["state"], held.get("process")),
                 ("unknown", "gone"))
        # a returned dispatch is never turned alive by a pid that happens to be alive
        held = DL.state(root / "nowhere", TASK, {"id": "x", "returned_at": T0, "in_flight": {"dispatch_id": "x", "pid": os.getpid()}}, T0)
        check_eq("K4 pid: a journalled return wins over a live pid", held["state"], "returned")
    finally:
        DL.process_created_at = real_created
        cleanup(root)


def pid_denied_and_reused() -> None:
    """t-335 A2 + A-n1 (critic t-334), pinned in THIS file (the liveness helper has no test file of its own).

    A2: a process the query is DENIED on (pid 4 / lsass / csrss on Windows, `PermissionError` on POSIX) is "could not be
    asked" (None), never "alive": a stale `in_flight` pid taken over by a protected process would otherwise read alive
    for ever and `recover` would never close the dispatch (FR-41). 87 (no such process) stays False. The Windows branch
    is driven through a mocked kernel32 handle; the real pid 4 is read too, where it exists.
    A-n1: a pid that is alive but belongs to a process created AFTER the entry's `started_at` is another process: the
    dispatch's own is gone. When the creation time cannot be read the answer is today's."""
    from unittest import mock
    import ctypes
    import dispatch_liveness as DL
    if os.name == "nt":
        def kernel_failing_open():
            """kernel32 whose OpenProcess returns no handle (what a denied or absent process gives)."""
            kernel = mock.MagicMock()
            kernel.OpenProcess.return_value = 0
            return kernel

        for error, want in ((5, None), (87, False), (1314, None), (0, None)):
            with mock.patch.object(ctypes, "WinDLL", lambda *a, **k: kernel_failing_open()), \
                    mock.patch.object(ctypes, "get_last_error", lambda error=error: error):
                check_eq(f"A2 mocked OpenProcess error {error}: {want}", DL.process_alive(4242), want)
        real4 = DL.process_alive(4)
        check("A2 the real pid 4 (System): access denied is None, never True", real4 is None or real4 is False, str(real4))
    else:
        for exc, want in ((PermissionError, None), (ProcessLookupError, False)):
            with mock.patch("os.kill", side_effect=exc):
                check_eq(f"A2 mocked os.kill raising {exc.__name__}: {want}", DL.process_alive(4242), want)
    check_eq("A2 a pid of 0, a negative, a bool and a string are None", [DL.process_alive(x) for x in (0, -1, True, "4")], [None] * 4)
    check("A2 control: this very process is still True", DL.process_alive(os.getpid()) is True)

    # A-n1 on the real clock: this process was created `born` seconds ago; an entry that says the driver started its
    # process at `begun` reads as taken over exactly when this process was created later than that.
    born = DL.process_created_at(os.getpid())
    check("A-n1 fixture: the creation time of this very process is readable and in the past",
          isinstance(born, float) and 0 < time.time() - born < 30 * 24 * 3600, str(born))
    if isinstance(born, float):
        iso = lambda epoch: time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(epoch))   # noqa: E731
        check_eq("A-n1 started before this process was created -> reused",
                 DL.pid_reused(os.getpid(), iso(born - 3600)), True)
        check_eq("A-n1 started when this process was created -> not reused (the stamp is whole seconds: the slack)",
                 DL.pid_reused(os.getpid(), iso(born)), False)
        check_eq("A-n1 started an hour AFTER it was created -> not reused", DL.pid_reused(os.getpid(), iso(born + 3600)), False)
        check_eq("A-n1 the same, as a number", DL.pid_reused(os.getpid(), born + 3600), False)
        held = DL.state("nowhere", "NOT-THE-FOLDER", {"id": "x", "in_flight": {"dispatch_id": "x", "pid": os.getpid(),
                                                                              "started_at": iso(born - 3600)}}, time.time())
        check_eq("A-n1 a live pid of a LATER process: the dispatch's own is gone, not alive",
                 (held["state"], held.get("process")), ("unknown", "gone"))
        check_in("A-n1 ...and the evidence says why", "now belongs to a process started later", " ".join(held["evidence"]))
        held = DL.state("nowhere", "NOT-THE-FOLDER", {"id": "x", "in_flight": {"dispatch_id": "x", "pid": os.getpid(),
                                                                              "started_at": iso(born)}}, time.time())
        check_eq("A-n1 control: the same pid with its own start time is alive", held["state"], "alive")
    for label, begun in (("no start time", None), ("an unreadable start time", "yesterday-ish"), ("a bool", True), ("empty", "")):
        check_eq(f"A-n1 edge ({label}): unchanged - not reused, no verdict", DL.pid_reused(os.getpid(), begun), None)
    held = DL.state("nowhere", "NOT-THE-FOLDER", {"id": "x", "in_flight": {"dispatch_id": "x", "pid": os.getpid()}}, time.time())
    check_eq("A-n1 edge: an entry with a pid and no start time is alive as before", held["state"], "alive")
    saved = DL.process_created_at
    DL.process_created_at = lambda pid: None                 # GetProcessTimes (or /proc) fails
    try:
        held = DL.state("nowhere", "NOT-THE-FOLDER", {"id": "x", "in_flight": {"dispatch_id": "x", "pid": os.getpid(),
                                                                              "started_at": "2020-01-01T00:00:00+00:00"}}, time.time())
    finally:
        DL.process_created_at = saved
    check_eq("A-n1 edge: when the creation time cannot be read the answer is unchanged (alive)", held["state"], "alive")
    check_eq("A-n1 edge: an unusable pid has no creation time", [DL.process_created_at(x) for x in (None, 0, -2, True, "7")], [None] * 5)


# ------------------------------------------------------------------------------------------ K5 the price

def spend() -> None:
    """One figure when the two records agree, a range when they differ (P18), 'recorded only' when one is missing."""
    root = temp_dir("t310-spend-")
    try:
        shape = [disp("S5-qa-automator-1", "S5", "qa-automator", "running", scope=CASES[:4])]
        rows = [run_row("S5-qa-automator-1", "qa-automator", 2.0, "s-a"), run_row("S5-qa-automator-1", "qa-automator", 2.1, "s-a")]
        tr = story(root, shape, [f"S{i}" for i in range(5)], started={"S5-qa-automator-1": T0}, rows=rows,
                   gates={"A": {"gate": "A", "status": "approved"}})

        def line_for(answer):
            got = SP.progress(tr, now=T0 + 60, liveness=ALIVE, price=answer)
            return got["spend"], got["line"]

        agree = {"status": "agrees", "price_low_usd": 4.1, "price_high_usd": 4.1, "totals": {"b": 4.1}}
        spend_, line = line_for(agree)
        check_eq("K5: equal sources -> one figure", spend_["range"], [4.1, 4.1])
        check_eq("K5: and they agree", spend_["sources_agree"], True)
        check_in("K5: the line has one number", "$4.10 so far ·", line)
        check_not_in("K5: no range, no caveat", "disagree", line)
        differ = {"status": "differs", "price_low_usd": 4.1, "price_high_usd": 4.6, "totals": {"b": 4.1}}
        spend_, line = line_for(differ)
        check_eq("K5: disagreeing sources -> the range", spend_["range"], [4.1, 4.6])
        check_eq("K5: and they are said not to agree", spend_["sources_agree"], False)
        check_in("K5: the line prints the range and says why", "$4.10–4.60 so far (sources disagree)", line)
        check_not_in("K5: never one of the two figures alone", "$4.10 so far", line)
        one = {"status": "not_cross_checked", "price_low_usd": 4.1, "price_high_usd": 4.1, "totals": {"b": 4.1}}
        spend_, line = line_for(one)
        check_eq("K5: one record -> neither agree nor differ (unknown)", spend_["sources_agree"], None)
        check_in("K5: 'recorded only'", "$4.10 so far (recorded only)", line)
        # t-323 B3: the dashboard card with no figure to print passes a recorded-only price with none: no number
        spend_, line = line_for({"status": "not_cross_checked"})
        check_eq("K5/B3: a recorded-only price with no figure is no figure", (spend_["range"], spend_["basis"]),
                 (None, "recorded_only"))
        check_in("K5/B3: the line says so in words", "cost recorded only, no figure", line)
        check_not_in("K5/B3: and prints no number", "$", line)
        spend_, line = line_for({"status": "incomplete", "finding": "no session has a record"})
        check_eq("K5: no figure at all is None, never a zero", (spend_["range"], spend_["recorded_usd"]), (None, None))
        check_in("K5: said in words", "no cost recorded yet", line)
        check_not_in("K5: no $0.00", "$0", line)
        # the real price function over a journal with no cost file under it: one record
        got = SP.progress(tr, now=T0 + 60, liveness=ALIVE)
        check_eq("K5: the real answer over the driver's journal alone is the recorded one",
                 (got["spend"]["basis"], got["spend"]["sources_agree"]), ("recorded_only", None))
        check_in("K5: and the line says recorded only", "(recorded only)", got["line"])
        check_eq("K5: dispatches counted once each", got["spend"]["dispatches"], 1)
    finally:
        cleanup(root)


# --------------------------------------------------------------------------------------------- the edges

def edges() -> None:
    """Spec section 4, edge by edge."""
    # No dispatch yet: S0 just started - the story is starting, not an error
    root = temp_dir("t310-fresh-")
    try:
        task_root = root / "qa-factory" / "artifacts" / "QA-1"
        got = SP.progress(task_root, fresh_ok=True)
        check_eq("edge: a task with no records is a story that is starting", got["position"], {"kind": "dispatch", "dispatch": None})
        check_in("edge: the line says so", "starting S0 Start and preflight", got["line"])
        check_eq("edge: nothing done, nothing running", (got["done"], got["running"]), ([], None))
        (task_root / "state").mkdir(parents=True)
        (task_root / "pipeline.json").write_text(json.dumps({"ticket": "QA-1", "stages": {"S0": {"status": "pending"}}}),
                                                 encoding="utf-8")
        got = SP.progress(task_root)
        check_in("edge: S0 recorded, no controller yet -> still starting S0", "starting S0 Start and preflight", got["line"])
        check_eq("edge: a position, never a crash", got["position"]["kind"], "dispatch")
    finally:
        cleanup(root)

    # A gate answered and asked again: `since` is the latest post
    root = temp_dir("t310-reask-")
    try:
        first, last = "2026-10-02T04:18:15+00:00", "2026-10-02T09:00:00+00:00"
        tr = story(root, [], [f"S{i}" for i in range(5)], asked={"kind": "gate_A", "stage": "S4", "dispatch": "", "at": last})
        posts = [{"ts": first, "kind": "gate_A", "stage": "S4"}, {"ts": last, "kind": "gate_A", "stage": "S4"}]
        (tr / "state" / "driver-questions.jsonl").write_text("".join(json.dumps(p) + "\n" for p in posts), encoding="utf-8")
        got = SP.progress(tr, now=SP._epoch(last) + 600)
        check_eq("edge: a re-asked gate waits since the latest post", (got["waiting"]["since"], got["waiting"]["minutes"]),
                 (last, 10))
        # an older `asked` with no time of its own: the latest post of that question
        tr = story(root, [], [f"S{i}" for i in range(5)], asked={"kind": "gate_A", "stage": "S4", "dispatch": ""})
        (tr / "state" / "driver-questions.jsonl").write_text("".join(json.dumps(p) + "\n" for p in posts), encoding="utf-8")
        got = SP.progress(tr, now=SP._epoch(last) + 600)
        check_eq("edge: no `at` -> the latest post in the question journal", got["waiting"]["since"], last)
        # a question that is not a gate
        tr = story(root, [], [f"S{i}" for i in range(2)], asked={"kind": "halt", "stage": "S2", "dispatch": "", "at": last})
        got = SP.progress(tr, now=SP._epoch(last) + 90)
        check_eq("edge: a question is a position of its own", got["position"], {"kind": "question", "question": "halt"})
        check_in("edge: said in words", "waiting for your answer (halt) since", got["line"])
    finally:
        cleanup(root)

    # a stage with nothing to automate: a code-only stage, the recorded null in its words
    import test_controller_state as BASE
    from controller import Controller
    from test_controller_rework_scope import plan_row
    root = temp_dir("t310-zero-")
    try:
        (root / "qa-factory").mkdir(parents=True, exist_ok=True)
        (root / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
        c = Controller(root)
        c.apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1", "known_paths": {"root": str(root)},
                               "idempotency_key": "init"})
        for number in range(5):
            BASE.accept_stage(c, root, f"S{number}")
        BASE.seed_plan(root, [plan_row(1, "manual-agent")])
        (root / "state" / "story-case-links.json").write_text(json.dumps({"links": [{"case_id": "TC-1", "version": "cv_1"}]}),
                                                              encoding="utf-8")
        decision = {"id": "gate-a", "gate": "A", "action": "approve", "status": "approved", "authorization_source": "human",
                    "source_revision": "src-1", "scope": ["TC-1"], "input_revision": "src-1", "idempotency_key": "gate-a"}
        c.apply("decision", BASE.bind_gate_a(root, decision))
        got = SP.progress(root)
        check_eq("edge: zero planned windows -> code only", got["position"]["kind"], "code_only")
        check_in("edge: with the recorded null in its words", "nothing to automate", got["line"])
    finally:
        cleanup(root)

    # a damaged optional record is named, never a stop; a damaged required one is a refusal that names the path
    root = temp_dir("t310-damaged-")
    try:
        tr = story(root, [disp("S1-qa-scout-1", "S1", "qa-scout", "running")], ["S0"], started={"S1-qa-scout-1": T0})
        (tr / "state" / "driver-state.json").write_text("{not json", encoding="utf-8")
        got = SP.progress(tr, now=T0 + 30)
        check("edge: an unreadable driver-state.json is a named gap", any("driver-state.json" in g for g in got["gaps"]),
              str(got["gaps"]))
        check_eq("edge: and the story is still answered", got["stage"]["id"], "S1")
    finally:
        cleanup(root)

    # the line that does not fit: case names go first, then the finished stages, the JSON keeps everything
    root = temp_dir("t310-long-")
    try:
        long_cases = [f"{TASK}_TC_{n:03d}_a_rather_long_case_name_{n}" for n in range(1, 6)]
        shape = [disp("S6-qa-runner-2", "S6", "qa-runner", "running", scope=long_cases, execution_kind="manual",
                      manual_case_ids=long_cases, purpose="manual")]
        tr = story(root, shape, [f"S{i}" for i in range(6)], started={"S6-qa-runner-2": T0})
        got = SP.progress(tr, now=T0 + 60, price={"status": "differs", "price_low_usd": 100.5, "price_high_usd": 120.25,
                                                 "totals": {"b": 100.5}})
        check(f"edge: at most {SP.LINE_MAX} characters ({len(got['line'])})", len(got["line"]) <= SP.LINE_MAX, got["line"])
        check_in("edge: the money survives the cut", "(sources disagree)", got["line"])
        check_eq("edge: the JSON keeps every case", len(got["position"]["cases"]), 5)
        check_not_in("edge: the case names went first", "a_rather_long", got["line"])
    finally:
        cleanup(root)
    # a story with everything done
    root = temp_dir("t310-done-")
    try:
        tr = story(root, [], [f"S{i}" for i in range(10)])
        got = SP.progress(tr, now=T0)
        check_eq("edge: all stages done is a position", (got["position"]["kind"], got["stage"]["id"]), ("done", None))
        check_in("edge: said plainly", "all stages done", got["line"])
    finally:
        cleanup(root)


# ----------------------------------------------------------------------------------------- K6 the driver

def count_progress(text: str) -> list:
    return [l for l in text.splitlines() if l.startswith("[progress] ")]


def driver_prints() -> None:
    """The driver prints one `[progress]` line per transition: the start, a role launched, the role's return,
    a question posted, a stage closed by code, the end - counted with the stub `claude` of the loop tests."""
    from story_run_common import GOOD_MANIFEST, SCOUT_DIGEST, driver_for, run_driver, seed, set_control
    task = "QA-9"
    root, task_root, env = seed(task)
    try:
        set_control(root, {"roles": {"qa-scout": {
            "files": {"work/context-manifest.json": json.dumps(GOOD_MANIFEST).replace("{task}", task),
                      "work/context-bundle.json": "{}"},
            "result": SCOUT_DIGEST.replace("{task}", task)}},
            "resume": {"result": SCOUT_DIGEST.replace("{task}", task)}})
        out = run_driver(root, env, "--task", task, "--max-boundaries", "1")
        lines = count_progress(out.stdout)
        check_eq("K6: start, launch, return, end: four lines in one S1 boundary", len(lines), 4)
        check_in("K6: the header says S1 is next", "starting S1 Context and grounding", lines[0])
        check_in("K6: the launch names the role in words", "the scout", lines[1])
        check_in("K6: ... recorded, with no proof of work yet", "no proof of work yet", lines[1])
        check_in("K6: the return says nobody is running now", "starting S2", lines[2])
        check_eq("K6: the end repeats where the story stands", lines[3], lines[2])
        order = [out.stdout.index(l) for l in lines]
        check_eq("K6: in the order of the transitions", order, sorted(order))
        check("K6: the launch line follows the line that says which role goes",
              out.stdout.index("[S1] qa-scout") < out.stdout.index(lines[1]))
        check_not_in("K6: no dispatch id in a progress line", "S1-qa-scout-1", "\n".join(lines))
        for line in lines:
            check_eq("K6: every line passes the person's rules", human_problems(line[len("[progress] "):]), [])
    finally:
        cleanup(root)

    # a question posted is one line, printed before the question's own text; a closing-by-code is one line
    root, task_root, env = seed(task)
    try:
        import story_run
        driver = driver_for(root, env, task)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            driver.where = lambda: {"action": "stop", "reason": "end of test"}
            driver.run()
        lines = count_progress(buffer.getvalue())
        check_eq("K6: a run that stops at once prints its header and its end, once each", len(lines), 2)

        driver = driver_for(root, env, task)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            driver.ask(story_run.Person("conductor", "The scout stopped and needs your word on what to read next.", "S1"))
        text = buffer.getvalue()
        check_eq("K6: a question posted prints one progress line", len(count_progress(text)), 1)
        check("K6: before the question's own text", text.index("[progress]") < text.index("Driver question"), text[:300])
        check_in("K6: naming it as a question", "waiting for your answer (conductor)", text)

        driver = driver_for(root, env, task)
        (task_root / "work").mkdir(exist_ok=True)
        (task_root / "work" / "evidence.json").write_text("{}", encoding="utf-8")
        driver.controller = lambda *args, **kwargs: {}
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            driver.code_only("S1", "nothing to read", ["work/evidence.json"])
        check_eq("K6: a stage closed by code prints one progress line", len(count_progress(buffer.getvalue())), 1)

        # a reader that cannot answer must not stop the run: the line says it, once
        driver = driver_for(root, env, task)
        (task_root / "state" / "controller.json").write_text("{broken", encoding="utf-8")
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            driver.progress_line()
        shown = count_progress(buffer.getvalue())
        check_eq("K6: an unreadable record is one line that names the file", len(shown), 1)
        check_in("K6: with the path", "controller.json", shown[0])
    finally:
        cleanup(root)


def driver_resume_prints() -> None:
    """t-323 B1 (critic t-322 A-F1): K6 extended. A role asked again in its own session (`resume_role`, `resume_with`)
    is a launch like any other: one `[progress]` line when it goes and one when it returns; and a stop that gave up
    prints ONE line (the question's), where the outer handler and `ask` each printed one."""
    from story_run_common import driver_for, seed
    import story_run
    task = "QA-9"
    root, task_root, env = seed(task)
    try:
        for label, call in (
                ("resume_role", lambda d: d.resume_role("S1", "qa-scout", "S1-qa-scout-1", "go on")),
                ("resume_with", lambda d: d.resume_with(story_run.Refusal("the exit gate said no"), "S1", "S1-qa-scout-1",
                                                        "sess-a", "The gate said: "))):
            driver = driver_for(root, env, task)
            buffer, seen = io.StringIO(), []

            def run_claude(*_args, **_kwargs):
                seen.append(len(count_progress(buffer.getvalue())))      # the lines printed BEFORE the call
                return {"result": "qa-scout S1 QA-9 · ok", "session_id": "sess-a", "is_error": False}

            driver.run_claude = run_claude
            driver.py = lambda *a, **k: (0, "")
            driver.handoff = lambda role, stage, dispatch, result: "qa-scout S1 QA-9 · ok"
            driver.question_threshold = lambda *a, **k: None
            driver.finish = lambda *a, **k: ("finished", None)
            driver.dispatch_role = lambda dispatch: "qa-scout"
            driver.state["sessions"]["S1-qa-scout-1"] = "sess-a"
            with redirect_stdout(buffer):
                call(driver)
            check_eq(f"K6 {label}: two progress lines, one at the launch and one at the return",
                     len(count_progress(buffer.getvalue())), 2)
            check_eq(f"K6 {label}: the first is printed before the role is called", seen, [1])
            for line in count_progress(buffer.getvalue()):
                check_eq(f"K6 {label}: the line passes the person's rules", human_problems(line[len("[progress] "):]), [])
        # a stop that gave up: the header, then the question's own line - not a third
        driver = driver_for(root, env, task)

        def give_up():
            raise story_run.Stop(story_run.EXIT_GAVE_UP, "the conductor gave up on this step")

        driver.where = give_up
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = driver.run()
        text = buffer.getvalue()
        check_eq("K6: a gave-up stop exits with its code", code, story_run.EXIT_GAVE_UP)
        check_eq("K6: and prints the header line and ONE line for the stop", len(count_progress(text)), 2)
        check("K6: the stop's line is the question's, printed just before the question's own text",
              text.rindex("[progress]") < text.index("Driver question") and "waiting for your answer" in text, text[-400:])
        # control: a stop that does not give up still prints its one line
        driver = driver_for(root, env, task)
        driver.where = lambda: (_ for _ in ()).throw(story_run.Stop(story_run.EXIT_ERROR, "an error"))
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = driver.run()
        check_eq("K6 control: a plain stop prints the header and one line for the stop", (code, len(count_progress(buffer.getvalue()))),
                 (story_run.EXIT_ERROR, 2))
    finally:
        cleanup(root)


def started_reads_the_in_flight_shape() -> None:
    """t-323 B2 (critic t-322 A-F2): `_started` reads B-268's `in_flight {dispatch_id, pid, started_at}`; the pair t-310
    read (`dispatch`, `ts`) is written by nothing in the package, so it is no fallback."""
    root = temp_dir("t323-inflight-")
    try:
        shape = [disp("S1-qa-scout-1", "S1", "qa-scout", "running")]
        tr = story(root, shape, ["S0"], driver_state={"in_flight": {"k": {
            "dispatch_id": "S1-qa-scout-1", "pid": 4242, "started_at": SP._iso(T0 + 100)}}})
        got = SP.progress(tr, now=T0 + 400, liveness=ALIVE)
        check_eq("B2: the record's own time is the start", (got["running"]["started_at"], got["running"]["minutes"]),
                 (SP._iso(T0 + 100), 5))
        tr = story(root, shape, ["S0"], driver_state={"in_flight": {"k": {
            "dispatch_id": "S1-qa-scout-2", "pid": 1, "started_at": SP._iso(T0 + 100)}}})
        got = SP.progress(tr, now=T0 + 400, liveness=ALIVE)
        check_eq("B2: another dispatch's record is not this one's", got["running"]["started_at"], None)
        tr = story(root, shape, ["S0"], driver_state={"in_flight": {"k": {
            "dispatch": "S1-qa-scout-1", "ts": SP._iso(T0 + 100)}}})
        got = SP.progress(tr, now=T0 + 400, liveness=ALIVE)
        check_eq("B2: the old pair (dispatch, ts) is read by nobody: no start, no duration, no error",
                 (got["running"]["started_at"], got["running"]["minutes"]), (None, None))
    finally:
        cleanup(root)


def block_size_is_the_controllers_constant() -> None:
    """t-323 C4: `blocks_total` counts the windows left by `controller.MANUAL_WINDOW_CASES`, read where it is counted (SC2-38 item 3)."""
    import controller
    check_eq("C4: the ceiling keeps its value", controller.MANUAL_BLOCK_CASES, 5)
    check_eq("C4: the window is three cases (one account set, t-1957 N5s)", controller.MANUAL_WINDOW_CASES, 3)
    check("C4: story_progress holds no copy of the number", not hasattr(SP, "MANUAL_BLOCK_MAX"))
    case_ids = [f"{TASK}_TC_{n:03d}" for n in range(1, 13)]
    first = disp("S6-qa-runner-2", "S6", "qa-runner", "running", scope=case_ids[:5], execution_kind="manual",
                 manual_case_ids=case_ids[:5], purpose="manual")
    saved_scope, saved_size = SP._scope_of, controller.MANUAL_WINDOW_CASES
    SP._scope_of = lambda *_a, **_k: {"derived": True, "scope": case_ids}
    try:
        got = SP._block_position(None, {}, [first], first, TASK)
        check_eq("C4: 7 cases left (no request names an account: one lane), 3 to a window: the block in flight + 3 more", got["blocks_total"], 4)
        controller.MANUAL_WINDOW_CASES = 2
        got = SP._block_position(None, {}, [first], first, TASK)
        check_eq("C4: the constant changed in this copy: 7 left, 2 to a window: blocks_total follows (1 + 4)",
                 got["blocks_total"], 5)
    finally:
        SP._scope_of, controller.MANUAL_WINDOW_CASES = saved_scope, saved_size


# ------------------------------------------------------------------------------------- K7 the dashboard

def dashboard_card() -> None:
    """The story card draws the same dict: the strip, the line, the price; a root with no records draws none."""
    import factory_dashboard as D
    import test_dashboard_task_binding as TB
    with tempfile.TemporaryDirectory() as td:
        driver, spread = TB.read_driver(td, {TB.TASK: TB.A_JOURNAL})
        root = Path(td).resolve() / "project"
        files, binding = TB.a_files("proj"), D.task_binding(driver)
        plain = D.tab_cost(files, {}, root, driver, spread, None, binding, None)
        check_not_in("K7: a story with no records of its own has no progress block", "class='progress'", plain)
        story(root, [disp("S5-qa-automator-1", "S5", "qa-automator", scope=CASES[:4])], [f"S{i}" for i in range(5)],
              asked={"kind": "gate_B", "stage": "S8", "dispatch": "", "at": "2026-10-02T04:18:15+00:00"},
              rows=[], task=TB.TASK, gates={"A": {"gate": "A", "status": "approved"}})
        page = D.tab_cost(files, {}, root, driver, spread, None, binding, None)
        check_in("K7: the card holds the progress block", "class='progress'", page)
        check_in("K7: the stage strip", "class='pchip' data-state='current'", page)
        check_in("K7: the position line", "waiting for your word at gate B", page)
        card = page.split("class='progress'")[0].rsplit("<div class='card'", 1)[1]
        check_in("K7: inside the story's own card", f"<div class='lbl'>{TB.TASK}</div>", card)
        check_in("K7: the card's price is still the range", "from $2.70 to $2.90", card)
        check_in("K7: and the block repeats that one price, not a second one", "$2.70–2.90 so far (sources disagree)", page)
        # t-323 B3 (critic t-322 A-F3): with NO price answers the card prints `group()`'s sum; the block holds that very
        # figure and says "recorded only" - one price string on the page, never a second one worked out by the block
        bare = D.tab_cost(files, {}, root, driver, spread, None, binding, {})
        bare_card = bare.split("class='progress'")[0].rsplit("<div class='card'", 1)[1]
        bare_block = bare.split("class='progress'")[1].split("</div></div>")[0] + "</div>"
        money = re.compile(r"\$\d+\.\d\d")
        check_eq("B3: answers absent: the card prints one price", len(set(money.findall(bare_card))), 1)
        check_eq("B3: answers absent: the block's price is the card's", set(money.findall(bare_block)),
                 set(money.findall(bare_card)))
        check_in("B3: and says what kind of figure it is", "(recorded only)", bare_block)
        check_not_in("B3: no range on the block when the card has none", "disagree", bare_block)
        # the block is drawn from the dict: break the record and the card says so instead of dropping the story
        (root / "qa-factory" / "artifacts" / TB.TASK / "state" / "controller.json").write_text("{broken", encoding="utf-8")
        page = D.tab_cost(files, {}, root, driver, spread, None, binding, None)
        check_in("K7: an unreadable record is said on the card", "not available", page)
        check_in("K7: and the price is still there", "from $2.70 to $2.90", page)


# --------------------------------------------------------------------------------------- K8 the command line

def command_line() -> None:
    script = str(harness.SCRIPTS / "story_progress.py")
    root = temp_dir("t310-cli-")
    try:
        missing = root / "qa-factory" / "artifacts" / "NOPE-1"
        # a root that is not a folder is refused earlier, by hooklib.story_cli (phantom root); the JSON of that refusal
        # escapes backslashes, so the check looks for words, not for the path
        phantom = subprocess.run([sys.executable, "-B", script, "--task-root", str(missing)], capture_output=True,
                                 text=True, encoding="utf-8")
        check_eq("K8: a phantom root -> exit 2", phantom.returncode, 2)
        check_in("K8: a phantom root is refused by name", "names no story", phantom.stderr)
        check_in("K8: a phantom root names the folder", "NOPE-1", phantom.stderr)
        # a folder that is a story by name but holds nothing reaches progress()'s own refusal
        missing.mkdir(parents=True)
        done =subprocess.run([sys.executable, "-B", script, "--task-root", str(missing)], capture_output=True,
                              text=True, encoding="utf-8")
        check_eq("K8: no story here -> exit 2", done.returncode, 2)
        check_in("K8: names the path", str(missing), done.stderr)
        check_in("K8: in the spec's words", "no story here yet", done.stderr)
        check_eq("K8: nothing on stdout (the caller parses it)", done.stdout, "")
        tr = story(root, [disp("S1-qa-scout-1", "S1", "qa-scout", "running")], ["S0"], started={"S1-qa-scout-1": T0})
        ok = subprocess.run([sys.executable, "-B", script, "--task-root", str(tr)], capture_output=True, text=True,
                            encoding="utf-8")
        check_eq("K8: the line, one line", (ok.returncode, len(ok.stdout.strip().splitlines())), (0, 1))
        check_in("K8: it is the story's line", "S1 Context and grounding", ok.stdout)
        as_json = subprocess.run([sys.executable, "-B", script, "--task-root", str(tr), "--json"], capture_output=True,
                                 text=True, encoding="utf-8")
        parsed = json.loads(as_json.stdout)          # the way a caller reads it (FR-14)
        check_eq("K8: --json is the whole dict and nothing else", (parsed["stage"]["id"], parsed["line"] == ok.stdout.strip()),
                 ("S1", True))
        (tr / "state" / "controller.json").write_text("{broken", encoding="utf-8")
        bad = subprocess.run([sys.executable, "-B", script, "--task-root", str(tr)], capture_output=True, text=True,
                             encoding="utf-8")
        check_eq("K8: a damaged record -> exit 2", bad.returncode, 2)
        check_in("K8: names the file", "controller.json", bad.stderr)
        check_in("K8: and a way on", "restore it", bad.stderr)
    finally:
        cleanup(root)


def main() -> None:
    positions()
    windows_and_rounds()
    stale_record()
    returned_session_is_said_so()
    stale_record_pid()
    pid_denied_and_reused()
    spend()
    edges()
    driver_prints()
    driver_resume_prints()
    started_reads_the_in_flight_shape()
    block_size_is_the_controllers_constant()
    dashboard_card()
    command_line()
    finish("test_story_progress")


if __name__ == "__main__":
    main()
