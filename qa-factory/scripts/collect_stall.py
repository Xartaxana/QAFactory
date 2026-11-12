# -*- coding: utf-8 -*-
"""Which stories did the factory stall on, since the last collect - the rule, as code (COLLECT, CL1-3, t-962 section 5).

A library for the packer, not a command: no `__main__`, nothing is printed, nothing is written (FR-45).

Two halves, so that the rule can be tested without a disk (FR-28):

  `read_facts(project, task_dir, now)`   gathers what the story's folder holds into one dict (the only part that reads files)
  `judge(facts, mark, now, quiet_hours)` the rule: PURE, the dict in, the verdict out, no I/O, no clock, no state
  `stall(project, task_dir, mark, now)`  both, in that order

The verdict is `{stalled, current, running_now, waiting_for_person, record, signals: [{id, where, at}], unreadable_reasons,
ignored}`. Seven signals, each an EPISODE that happened after the mark (K4 is the one that can clear itself):

  K1  driver-state.json `interrupted` holds a cut-off call                           window: `at`
  K2  driver-state.json `in_flight` names a process that is gone (or was taken over)  window: `started_at`
  K3  driver-runs.jsonl `launched` row with no outcome row of the same dispatch after it, the dispatch is not live, and the
      row is STRICTLY older than the quiet hours (a conductor call has a `launched` row but never an `in_flight` entry, so a
      call running right now looks the same; a younger row is named in `ignored` as "may be running now").
      NOT a signal: a row the person's stop record cuts off (TR4-11): a LATER row `kind == "stopped_by_person"`, `who == "person"`,
      whose `cut` list holds `<dispatch_id or call>@<started_at>` of the row (`Driver.journal_run` keeps the calls its process launched
      and saw no end row for - so `cut` holds every such call, including one that ended abnormally earlier in the same process
      with no outcome row and a drained call that has a `launched` row but no process; `Driver.person_stop_record` writes them) and whose `since` (the stopping process's start) is not after the
      row's start; it is named in `ignored` ("stopped by the person at <at>"). A dead driver stays a stall: a row with no such record
      after it, one of an earlier process (not in `cut`), one launched after the record, a record with no `cut`, `who` other than
      "person", or a `since`/`at` that is not a time (also a reason: `unreadable`). Known gap, queued: this file reads
      driver-runs.jsonl itself while `driver_journal` calls itself its one reader (AR-13).
                                                                                     window: `started_at` (else `ts`)
  K4  the LAST outcome row of a dispatch is an error (`is_error`, `exit_code` != 0, `infra`); a later ok row of the
      same dispatch clears it                                                        window: `ts`
  K5  conductor.jsonl `action == "stop"` (the conductor gave up)                      window: `ts`
  K6  controller.json dispatch: `abandoned` / `never_started` (window: `started_at`, the `dispatch` event's `created_at`),
      or `returned_unaccepted` whose `returned_at` is STRICTLY older than the quiet hours (a role that has just returned is
      the normal road to acceptance, not a stall)                                    window: as named
      NOT a signal: `stale`, `blocked` / `incomplete` / `paused`, `released_by_person`, and `running` whatever its liveness
      says (a `running` + `unknown` story is the business of `current`)
  K7  events.jsonl `state_repair` / `release`                                         window: `created_at`

Every signal is windowed by ITS OWN time, strictly after the mark; a record with NO time (a status in `controller.json`
that carries none) is never a signal and is named in `ignored`, not dropped silently; a record whose time is there and is not
a time (a huge number, a word) is `unreadable`. The status sets come from `controller`
(`SETTLED` / `STOPPED` / `DISCOUNTED`) and are read at call time: there is no table of statuses in this file (twin tied by a
test). `import controller` has no side effect (checked at CL1-3: nothing printed, nothing written, exit 0).

`current`: the story is not closed, nothing of it is live, and its last activity is strictly older than the quiet hours.
Last activity: `archive_task.last_activity(pipeline)`, else the newest `created_at` in events.jsonl, else the newest
dispatch `started_at`, else NOTHING - and nothing is `unreadable`.

Waiting for a person: an open gate item of `archive_task.open_items` ("gate X was opened after S3 and never answered") or an
open `driver-question.md`. It overrides ONLY `current` (a story that waits is not "running now", and not idle either) and
sets `record` to "waiting for a person". It does NOT touch a K-signal or `unreadable`: a conductor `stop` (K5) always opens
`driver-question.md` (story_run.py `funnel`), so the story the person walked away from is exactly the case that must still
yield its transcripts (t-1022 M-1; the error direction below).

Error direction (the packer's transcripts are the gate): an extra transcript is the safe side, a missing one is not. So
whatever the rule cannot establish - a bad mark, a mark in the future, a carrier that is there and cannot be read, a broken
line, a time that is not a time, a field in a shape the rule does not know, no activity time at all - becomes the signal
`unreadable` and `stalled` (FR-41, FR-59: an unknown is never "fine"; a raise is not an answer either). The readable part
still counts; the unreadable part is named in `unreadable_reasons`.

L (the loop rule, CL3-9): a story that LOOPS is not stalled (it keeps running) yet its archive needs the transcripts just as much.
The loop half of the verdict is `{looped, loop_signals, loop_unreadable_reasons, loop_ignored}`, drawn on the same window rule
(`_after`, strictly after the mark) with its OWN reason list: it never adds to the stall's `signals`, `unreadable_reasons`
or `ignored` (the stall half is byte-identical to before). The closed variety - which record means a loop - is the data table
`references/collect-loops.json` (`load_loops`, the one reader; FR-13): L1 one role dispatched on one `controller.ledger_key`
more often than normal; L2 `window_rounds` hit the cap or repeated; L3 `gate_repair` journal rows stopped by cap or repeat;
L4 `repair_limit` / `repair_limit_s7` answered by the person; L5 a person's recorded word passed a cap (`stage_overrides`: a
repair pass key built by `controller.repair_pass_key`, or a block named in `exit_limit` passes; revoked ones count - history);
L6 the exit gate granted a round; L7 `driver-questions.jsonl` rows of the repair/exit-limit questions - the DURABLE carrier:
the driver pops `window_rounds`, `exit_limit` and its passes when a window or dispatch is accepted and overwrites a
`repair_limit` slot, so L2/L4/L6 see only what is open at collect time and L7 sees what was ever asked (of the repair/exit-limit
questions only). Known gap: a window-round cap question (`no_move` kind `refusal`, why `threshold`) leaves no durable row, so a
window that hit the cap and then closed is seen only through L1/L5; queued: a driver-journal row (`kind: window_round`,
`outcome`) from story_run.py. Exceeded caps only
(a cap exactly reached is not a loop). `looped` is True with any signal, None (unknown, packs) when any loop reason or stall
reason stands, else False. `driver-state.json` absent while the driver journal has rows is an unknown; absent with no driver
rows (the skill road keeps no such record) is "not recorded". A verdict without the key `looped` is read as NOT looped.
Known blind spot (queued): a swept exit-gate pass keeps no durable link to its dispatch.

H (the transcripts of a stalled or looped story): `select_transcripts` keeps the subagent transcripts whose session folder is the stem
of a transcript of one of the story's own sessions (`p.parent.parent.name == Path(transcript).stem`): the host-wide list of
`hooklib.story_subagent_transcripts` carries every story's roles. The summary shown to the person says next to "delete the
file" that the interactive session's main transcript also carries the person's other work.
"""
import json
import math
import re
from pathlib import Path

import controller
import dispatch_liveness as DL
import hooklib
import archive_task

DEFAULT_QUIET_HOURS = 24.0        # t-962 section 5; no config key exists, so the packer passes it (or this default)
RUNNING = "running"               # controller.py writes the literal on a dispatch receipt (no constant exists)
REPAIR_EVENTS = ("state_repair", "release")
UNREADABLE = "unreadable"
WAITING = "waiting for a person"
# archive_task.open_items' own sentence for a gate nobody answered - the factory's wording, not a person's (FR-12);
# test_collect_stall ties it to the real function so a rewording there fails here.
_GATE_UNANSWERED = re.compile(r"^gate \S+ was opened after \S+ and never answered$")

# L (CL3-9). The closed variety is `references/collect-loops.json`; what stays code is the record SHAPES, the files the reader
# knows (and the `facts` key each journal arrives under), and the two forms the factory itself writes (L5).
LOOPS_FILE = Path(__file__).resolve().parents[1] / "references" / "collect-loops.json"
STATE_CARRIER = "driver-state.json"
JOURNAL_FACTS = {"driver-runs.jsonl": "driver_runs", "driver-questions.jsonl": "driver_questions"}
SHAPES = ("series", "records", "nested_records", "rows")
# `controller.repair_pass_key`'s own form (the factory's wording, FR-12); test_collect_stall ties it to the real builder.
PASS_KEY = re.compile(r"^(round|mechanical) pass \d+ for \S+ on S\d+:[0-9a-f]{12}$")
EXIT_BLOCKS = "exit_limit"        # L5 (b): the blocks an exit pass lifted are named in this record's `passes` (story_run.py)


# --- the rule: pure ---------------------------------------------------------------------------------------------------
def _epoch(value):
    """Epoch seconds of a number or an ISO string (a naive one is UTC); None for anything else. A bool is not a time.

    ONE parser, `dispatch_liveness._epoch`. What this wrapper adds is the safe side of a verdict that must not raise: DL's
    returns a NaN / infinity as a time and raises `OverflowError` on a huge integer (legal JSON) - both are "not a time"
    here; so is a date the platform cannot place."""
    try:
        at = DL._epoch(value)
    except (OverflowError, ValueError, OSError):
        return None
    return at if at is not None and math.isfinite(at) else None


def _show(value):
    """A value for a reason line: its repr, cut (a huge integer or a long list must not fill the line)."""
    try:
        return f"{value!r:.60}"
    except Exception:
        return f"<{type(value).__name__}>"


def _quiet_seconds(hours):
    """The quiet window in seconds: a finite number >= 0 (0 is legal: every returned role then counts), else None."""
    if isinstance(hours, bool) or not isinstance(hours, (int, float)) or not math.isfinite(hours) or hours < 0:
        return None
    return float(hours) * 3600.0


def _dicts(value):
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def _list(value):
    return value if isinstance(value, list) else []


def _sig(sig_id, where, at):
    return {"id": sig_id, "where": where, "at": at}


def _after(raw, floor, ignored, reasons, where):
    """The epoch of `raw` when it lies strictly after the mark; None when it does not.

    A record with NO time (absent, null, blank) is never a signal and is named in `ignored`; a time that is there and is not
    a time (a huge number, a word, a list) is a field the rule cannot read: a reason, so the story is `unreadable`."""
    at = _epoch(raw)
    if at is None:
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            ignored.append({"where": where, "why": "no usable time, so never a signal"})
        else:
            reasons.append(f"{where}: its time is not a time ({_show(raw)})")
        return None
    return at if at > floor else None


def episode_statuses():
    """The dispatch statuses that are an episode as they stand, read from `controller` NOW (never copied).

    `SETTLED` less `returned_unaccepted` (that one needs age, K6) plus `never_started`; what the controller also lists as
    `STOPPED` (a planned stop with a checkpoint) or `DISCOUNTED` (stale, superseded, released) is never an episode."""
    stands = (controller.SETTLED - {controller.RETURNED}) | {controller.NEVER_STARTED}
    return stands - controller.STOPPED - (controller.DISCOUNTED - {controller.NEVER_STARTED})


def _live_ids(facts):
    """Dispatch ids with proof of life: a driver process that is alive and not taken over, or a `running` dispatch whose
    liveness verdict is `alive`. `unknown` is not proof."""
    live = {str(e.get("dispatch")) for e in _dicts(facts.get("in_flight"))
            if e.get("alive") is True and e.get("reused") is not True}
    live |= {str(d.get("id")) for d in _dicts(facts.get("dispatches"))
             if d.get("status") == RUNNING and d.get("liveness") == DL.ALIVE}
    return live


def _k1_k2(facts, floor, ignored, reasons):
    out = []
    for entry in _dicts(facts.get("interrupted")):
        where = f"driver-state.json interrupted {entry.get('key')}"
        at = _after(entry.get("at"), floor, ignored, reasons, where)
        if at is not None:
            out.append(_sig("K1", where, at))
    for entry in _dicts(facts.get("in_flight")):
        gone = entry.get("alive") is False or (entry.get("alive") is True and entry.get("reused") is True)
        if not gone:
            continue
        where = f"driver-state.json in_flight {entry.get('dispatch')}"
        at = _after(entry.get("started_at"), floor, ignored, reasons, where)
        if at is not None:
            out.append(_sig("K2", where, at))
    return out


def _outcome_key(row):
    return str(row.get("dispatch") or row.get("kind") or "")


def _is_outcome(row):
    return row.get("kind") != "launched" and any(k in row for k in ("is_error", "exit_code", "infra"))


def _is_error(row):
    code = row.get("exit_code")
    return bool(row.get("is_error")) or bool(row.get("infra")) or (
        isinstance(code, int) and not isinstance(code, bool) and code != 0)


def _person_stop(later, call_id, began, reasons):
    """The first row of `later` (the rows AFTER a `launched` row) that is the person's stop record cutting THIS call, else None.

    Honoured only when ALL hold (clearing a K3 is the unsafe side - a missing transcript): `kind == "stopped_by_person"`, `who ==
    "person"`, `call_id` (`<dispatch_id or call>@<started_at>`, the form `Driver.journal_run` keeps) is in its `cut` list (a record with
    no `cut` - an older writer - clears nothing), `since` and `at` are times, and `since` (when the stopping process began) is not after
    the call's own start. A `since` or `at` that is there and is not a time is a reason (the story is `unreadable`) and the row is
    judged as if no record stood; one that is absent is not honoured, silently."""
    for row in later:
        cut = row.get("cut")
        if row.get("kind") != "stopped_by_person" or row.get("who") != "person" or not isinstance(cut, list) or call_id not in cut:
            continue
        since, at = _epoch(row.get("since")), _epoch(row.get("at"))
        for name, value, parsed in (("since", row.get("since"), since), ("at", row.get("at"), at)):
            if parsed is None and value is not None and not (isinstance(value, str) and not value.strip()):
                reasons.append(f"driver-runs.jsonl stopped_by_person: its {name} is not a time ({_show(value)})")
        if since is not None and at is not None and began is not None and since <= began:
            return row
    return None


def _k3_k4(facts, floor, now_s, quiet_s, ignored, reasons, live):
    rows = _dicts(facts.get("driver_runs"))
    out, last = [], {}
    for i, row in enumerate(rows):
        if _is_outcome(row):
            last[_outcome_key(row)] = row
            continue
        key = str(row.get("dispatch_id") or row.get("call") or "")
        if row.get("kind") != "launched" or key in live:
            continue
        if any(_is_outcome(later) and _outcome_key(later) == key for later in rows[i + 1:]):
            continue
        where = f"driver-runs.jsonl launched {key}"
        began = row.get("started_at") if row.get("started_at") is not None else row.get("ts")
        at = _after(began, floor, ignored, reasons, where)
        if at is None:
            continue
        stop = _person_stop(rows[i + 1:], f"{key}@{began}", _epoch(began), reasons)
        if stop is not None:
            ignored.append({"where": where, "why": f"stopped by the person at {stop.get('at')}"})
        elif now_s - at > quiet_s:
            out.append(_sig("K3", where, at))
        else:       # t-1022 M-2: no `in_flight` entry exists for a conductor call, and a role's appears seconds after the row
            ignored.append({"where": where, "why": "launched less than the quiet window ago with no end row yet: may be running now"})
    for key, row in last.items():
        where = f"driver-runs.jsonl outcome {key}"
        at = _after(row.get("ts"), floor, ignored, reasons, where) if _is_error(row) else None
        if at is not None:
            out.append(_sig("K4", where, at))
    return out


def _k5_k7(facts, floor, ignored, reasons):
    out = []
    for row in _dicts(facts.get("conductor")):
        if row.get("action") == "stop":
            at = _after(row.get("ts"), floor, ignored, reasons, "conductor.jsonl stop")
            if at is not None:
                out.append(_sig("K5", "conductor.jsonl stop", at))
    for event in _dicts(facts.get("events")):
        if event.get("type") in REPAIR_EVENTS:
            where = f"events.jsonl {event.get('type')} #{event.get('sequence')}"
            at = _after(event.get("created_at"), floor, ignored, reasons, where)
            if at is not None:
                out.append(_sig("K7", where, at))
    return out


def _k6(facts, floor, now_s, quiet_s, ignored, reasons):
    stands, out = episode_statuses(), []
    for d in _dicts(facts.get("dispatches")):
        status = d.get("status")
        if not isinstance(status, str):
            if status is not None:      # a status that is not a word (a list is not even hashable): a field we cannot read
                reasons.append(f"controller.json dispatch {d.get('id')}: its status is not a word ({_show(status)})")
            continue
        where = f"controller.json dispatch {d.get('id')} {status}"
        if status in stands:
            at = _after(d.get("started_at"), floor, ignored, reasons, where)
        elif status == controller.RETURNED:
            at = _after(d.get("returned_at"), floor, ignored, reasons, where)
            at = at if at is not None and now_s - at > quiet_s else None
        else:
            continue
        if at is not None:
            out.append(_sig("K6", where, at))
    return out


def _last_activity(facts):
    """Epoch of the story's last sign of life, or None: the pipeline's newest stamp, else the newest event, else the newest
    dispatch start."""
    stamp = _epoch(facts.get("last_activity"))
    if stamp is not None:
        return stamp
    created = [t for t in (_epoch(e.get("created_at")) for e in _dicts(facts.get("events"))) if t is not None]
    starts = [t for t in (_epoch(d.get("started_at")) for d in _dicts(facts.get("dispatches"))) if t is not None]
    return max(created) if created else (max(starts) if starts else None)


def _waiting(facts):
    return bool(facts.get("driver_question_open")) or any(
        _GATE_UNANSWERED.match(str(item)) for item in _list(facts.get("open_items")))


def _verdict(signals, reasons, ignored, waiting, current, running_now, loop=(None, [], [], [])):
    """The answer: `unreadable` joins the signals when anything could not be established. Waiting for a person is a
    `record` and has already kept `current` False; it never clears a signal (t-1022 M-1: a conductor `stop` always opens
    the question, and that story must still yield its transcripts). `loop` = (looped, signals, reasons, ignored): the loop
    half, kept apart from the stall's lists."""
    signals, reasons = list(signals), list(dict.fromkeys(reasons))
    if reasons:
        signals.append(_sig(UNREADABLE, "; ".join(reasons), None))
    looped, loop_signals, loop_reasons, loop_ignored = loop
    return {"stalled": bool(signals or current), "current": current, "running_now": running_now,
            "waiting_for_person": waiting, "record": WAITING if waiting else None,
            "signals": signals, "unreadable_reasons": reasons, "ignored": ignored,
            "looped": looped, "loop_signals": loop_signals, "loop_unreadable_reasons": loop_reasons, "loop_ignored": loop_ignored}


# --- L: the loop rule (pure; the table is data) -----------------------------------------------------------------------
def _l1_repeat(facts, floor, table, ignored, reasons):
    """L1: one role dispatched on one loop key (`controller.ledger_key`) more often than normal. ONE signal per group, at the
    newest start among the dispatches BEYOND the limit (the earliest `limit` starts are the normal ones)."""
    cfg, groups, out = table["repeat_dispatch"], {}, []
    for d in _dicts(facts.get("dispatches")):
        if d.get("key") is not None:
            groups.setdefault(d["key"], []).append(d)
    for key, group in groups.items():
        limit = cfg["max_normal_repair_roles"] if group[0].get("role") in controller.REPAIR_LOOP_ROLES else cfg["max_normal"]
        if len(group) <= limit:
            continue
        def order(d):
            at = _epoch(d.get("started_at"))
            return (at is None, at or 0.0, str(d.get("id")))
        beyond = sorted(group, key=order)[limit:]
        where = f"controller.json {key} dispatched {len(group)} times (normal at most {limit})"
        seen = [_after(d.get("started_at"), floor, ignored, reasons, f"{where}, dispatch {d.get('id')}") for d in beyond]
        seen = [t for t in seen if t is not None]
        if seen:
            out.append(_sig("L1", where, max(seen)))
    return out


def _rows_of(facts, row):
    """The rows a `rows` table row reads: its journal's rows (the `facts` key by the carrier), narrowed by `kind` when it has one."""
    rows = _dicts(facts.get(JOURNAL_FACTS.get(row["carrier"], "")))
    return [r for r in rows if "kind" not in row or r.get("kind") == row["kind"]]


def _l_records(facts, floor, table, ignored, reasons):
    """L2-L4, L6, L7: the records a table row names, by its shape. A container in a shape the row does not know is a reason and
    the rest is still read."""
    state = facts.get("driver_state") if isinstance(facts.get("driver_state"), dict) else {}
    out = []

    def take(row, name, raw_time, value):
        where = f"{row['carrier']} {row.get('key') or row.get('kind') or row['field']} {name} {value}"
        at = _after(raw_time, floor, ignored, reasons, where)
        if at is not None:
            out.append(_sig(row["id"], where, at))

    def hit(row, record):
        got = record.get(row["field"])
        return isinstance(got, str) and got in row["values"]

    for row in table["records"]:
        if row["shape"] == "rows":
            for r in _rows_of(facts, row):
                if hit(row, r):
                    take(row, "row", r.get(row["time"]), r.get(row["field"]))
            continue
        held = _shape(state, row["key"], dict, row["carrier"], reasons)
        label = f"{row['carrier']} {row['key']}"
        want = list if row["shape"] == "series" else dict
        for name, rec in held.items():
            if not isinstance(rec, want):               # a record in another shape is a reason, never "no loop"
                _not_read(label, name, want, rec, reasons)
            elif row["shape"] == "series":
                for r in _dicts(rec):
                    if hit(row, r):
                        take(row, name, r.get(row["time"]), r.get(row["field"]))
            elif row["shape"] == "records":
                if hit(row, rec):
                    take(row, name, rec.get(row["time"]), rec.get(row["field"]))
            else:
                inner = _shape(rec, row["inner"], dict, f"{label} {name}", reasons)
                for k, sub in inner.items():
                    if not isinstance(sub, dict):
                        _not_read(f"{label} {name} {row['inner']}", k, dict, sub, reasons)
                        continue
                    got = sub.get(row["field"])
                    if isinstance(got, int) and not isinstance(got, bool) and got >= row["min"]:
                        take(row, f"{name} {k}", sub.get(row["time"]), got)
    return out


def _l5_person_pass(facts, floor, ignored, reasons):
    """L5: a cap or limit passed by the person's recorded word: a `stage_overrides` entry whose `match` is a repair pass key, or
    names a block an exit pass lifted. Revoked entries count (history: the revoke undoes the pass, not the loop). Any other
    override (a source pass, a protected path, a stand gap) is not a loop."""
    entries = _shape(facts, "stage_overrides", list, "pipeline.json", reasons)
    state = facts.get("driver_state") if isinstance(facts.get("driver_state"), dict) else {}
    blocks = {(str(p.get("stage")), str(p.get("block")))
              for rec in _shape(state, EXIT_BLOCKS, dict, STATE_CARRIER, reasons).values() if isinstance(rec, dict)
              for p in _dicts(rec.get("passes"))}
    out = []
    for e in _dicts(entries):
        match = e.get("match")
        if isinstance(match, str) and (PASS_KEY.match(match) or (str(e.get("stage")), match) in blocks):
            where = f"pipeline.json stage_overrides {e.get('stage')} {match[:60]}"
            at = _after(e.get("at"), floor, ignored, reasons, where)
            if at is not None:
                out.append(_sig("L5", where, at))
    return out


def _loops(facts, floor, table):
    """`(signals, ignored, reasons)` of the loop half; PURE. Its lists are its own: the stall's never see them."""
    ignored, reasons = [], [str(r) for r in _list(facts.get("loop_unreadable"))]
    signals = (_l1_repeat(facts, floor, table, ignored, reasons) + _l_records(facts, floor, table, ignored, reasons)
               + _l5_person_pass(facts, floor, ignored, reasons))
    if facts.get("driver_state_present") is False and _dicts(facts.get("driver_runs")):
        reasons.append(f"driver-state.json is absent although the driver journal has {len(_dicts(facts.get('driver_runs')))} rows: "
                       "the window, repair and exit records cannot be read")
    return signals, ignored, list(dict.fromkeys(reasons))


def _loop_half(facts, floor, loop_table, stall_reasons):
    """`(looped, signals, reasons, ignored)`: True with any signal; None (unknown) with any reason, the stall's file-level ones
    included (they may hide a loop carrier); else False. No table = unknown."""
    if loop_table is None:
        return None, [], ["no loop table was given"], []
    signals, ignored, reasons = _loops(facts, floor, loop_table)
    return (True if signals else (None if reasons or stall_reasons else False)), signals, reasons, ignored


def judge(facts, mark, now, quiet_hours=DEFAULT_QUIET_HOURS, loop_table=None):
    """The verdict on one story. PURE: `facts` (see `read_facts`) is not changed and nothing outside it is read.

    `mark`: when the last collect happened (epoch seconds or ISO text); None = never collected, every signal counts.
    `now`: epoch seconds. `quiet_hours`: the quiet window of K6 and `current`; 0 is legal (every returned role is old).
    `loop_table`: `load_loops()`'s table for the loop half; None = the loop state is unknown (`looped` None)."""
    facts = facts if isinstance(facts, dict) else {}
    reasons = [str(r) for r in _list(facts.get("unreadable"))]
    now_s, quiet_s, floor, bad = _epoch(now), _quiet_seconds(quiet_hours), -math.inf, []
    if now_s is None:
        bad.append(f"now ({_show(now)}) is not a time")
    if quiet_s is None:
        bad.append(f"stall_quiet_hours ({_show(quiet_hours)}) is not a number of hours >= 0")
    if mark is not None:
        floor = _epoch(mark)
        if floor is None:
            bad.append(f"the mark ({_show(mark)}) is not a time")
        elif now_s is not None and floor > now_s:
            bad.append(f"the mark ({_show(mark)}) is in the future of now ({_show(now)}): its clock is wrong, no window can be drawn")
    if bad:
        return _verdict([], reasons + bad, [], False, False, False, (None, [], bad, []))
    ignored, live = [], _live_ids(facts)
    signals = (_k1_k2(facts, floor, ignored, reasons) + _k3_k4(facts, floor, now_s, quiet_s, ignored, reasons, live)
               + _k5_k7(facts, floor, ignored, reasons) + _k6(facts, floor, now_s, quiet_s, ignored, reasons))
    waiting, current = _waiting(facts), False
    if not waiting and not facts.get("closed") and not live:
        last = _last_activity(facts)
        if last is None:
            reasons.append("the story has no activity time in pipeline.json, events.jsonl or any dispatch: "
                           "whether it is current cannot be told")
        else:
            current = now_s - last > quiet_s
    return _verdict(signals, reasons, ignored, waiting, current, bool(live), _loop_half(facts, floor, loop_table, reasons))


def wants_transcripts(verdict):
    """The ONE gate of H: a stalled story, or one that looped, or one whose looping is not known (an extra transcript is the
    safe side). A verdict with no `looped` key at all is read as not looped (an older producer, a hand-made verdict)."""
    verdict = verdict if isinstance(verdict, dict) else {}
    return bool(verdict.get("stalled")) or verdict.get("looped", False) is not False


# --- H: which transcripts go with a stalled or looped story ---------------------------------------------------------------------
def select_transcripts(verdict, sessions, subagent_paths):
    """`{main, subagents, gaps, why}`: the transcripts of a stalled or looped story, nothing for any other.

    `sessions`: `[{sid, transcript, exists, why?}]` of THE STORY's own sessions (`session_transcripts`);
    `subagent_paths`: the host-wide list of `hooklib.story_subagent_transcripts`. A subagent file stays only when its session
    folder (`p.parent.parent.name`) is the stem of one of those sessions' transcripts - the other roles are other stories'.
    A session whose transcript file is gone is a gap named by its sid, never a crash. No sessions: "no transcripts".

    A carrier the sessions are read from that could not be read arrives as an entry `{sid: None, unreadable: True, why}`
    (`session_transcripts`): it is a gap with no sid, and when nothing else is known the answer says the sessions are
    UNREADABLE - never that none is recorded (t-1022 M-4: an unknown is not an absence)."""
    verdict = verdict if isinstance(verdict, dict) else {}
    if not wants_transcripts(verdict):
        return {"main": [], "subagents": [], "gaps": [], "why": verdict.get("record") or "the story neither stalled nor looped"}
    sessions = _dicts(sessions)
    broken = [s for s in sessions if s.get("unreadable")]
    sessions = [s for s in sessions if not s.get("unreadable")]
    gaps = [{"sid": None, "why": str(s.get("why"))} for s in broken]
    if not sessions:
        why = ("no transcripts: the sessions of this story could not all be read - unreadable: "
               + "; ".join(g["why"] for g in gaps)) if gaps else "no transcripts: no session of this story is recorded"
        return {"main": [], "subagents": [], "gaps": gaps, "why": why}
    main = list(dict.fromkeys(str(s["transcript"]) for s in sessions if s.get("exists") and s.get("transcript")))
    stems = {Path(str(s["transcript"])).stem for s in sessions if s.get("transcript")}
    kept = [str(p) for p in subagent_paths or [] if Path(str(p)).parent.parent.name in stems]
    gaps += [{"sid": str(s.get("sid")), "why": str(s.get("why") or "the transcript file is not on disk")}
             for s in sessions if not s.get("exists")]
    looped = verdict.get("looped", False)
    why = ("the story is stalled and looped" if looped is True and verdict.get("stalled") else "the story looped" if looped is True
           else "the story is stalled" if verdict.get("stalled") else "whether the story looped is not known")
    return {"main": main, "subagents": kept, "gaps": gaps, "why": why}


# --- the reader: the only part that touches files ---------------------------------------------------------------------
def _json_object(path, label, reasons):
    """The JSON object in `path`; None when the file is absent (not a fault) or unreadable (named in `reasons`)."""
    if not path.is_file():
        return None
    data = hooklib.read_json(path, None, errors=Exception, kind=dict)     # a nesting too deep for the parser is a fault too
    if data is None:
        reasons.append(f"{label} is there and cannot be read as a JSON object")
    return data


def _shape(holder, field, kind, label, reasons):
    """`holder[field]` when it is a `kind`; `kind()` when it is absent; `kind()` and a reason when it is there in another shape."""
    value = holder.get(field)
    if isinstance(value, kind):
        return value
    if value is not None:
        _not_read(label, field, kind, value, reasons)
    return kind()


def _not_read(label, field, kind, value, reasons):
    """The ONE reason text of a value in a shape other than `kind`."""
    reasons.append(f"{label} {field} is not a JSON {kind.__name__} ({type(value).__name__}), so it was not read")


def _guard(label, call, default, reasons):
    """`call()`, or `default` and a reason when it raises: a helper of the package met a shape it does not know."""
    try:
        return call()
    except Exception as exc:
        reasons.append(f"{label} cannot be read ({type(exc).__name__}): a field is not in the shape it expects")
        return default


def _jsonl_rows(path, label, reasons):
    """The object rows of a jsonl file, split on "\\n" only (a lone "\\r" or U+2028 inside a string is data; a leading BOM is
    the encoding, as in `driver_journal.read_rows`). A broken line is named and skipped; a last line with no newline that does
    not parse is a write in progress and is left alone."""
    if not path.is_file():
        return []
    try:
        text = path.read_bytes().decode("utf-8-sig", "replace")
    except OSError as exc:
        reasons.append(f"{label} cannot be read ({type(exc).__name__})")
        return []
    lines, rows = text.split("\n"), []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:                       # ValueError, and RecursionError on a nesting too deep for the parser
            row = None
        if isinstance(row, dict):
            rows.append(row)
        elif not (number == len(lines) and not text.endswith("\n")):
            reasons.append(f"{label} line {number} is not a JSON object")
    return rows


def _loop_key(ident, record, loop_reasons):
    """L1's grouping key: `controller.ledger_key` (the survivor of the repair ledger). Over-grouping is the safe error; a
    record whose key cannot be built is a loop REASON, never a skipped record (a skipped one could hide a loop)."""
    try:
        item = dict(record, id=str(ident))
        scope = item.get("scope")
        if isinstance(scope, list):
            try:
                item["scope"] = sorted(set(scope))      # ledger_key keeps a repeated scope item: one series would split
            except TypeError:
                pass                                    # unhashable/unorderable items: budget_scope raises, a loop reason below
        return controller.ledger_key(item)
    except Exception as exc:
        loop_reasons.append(f"controller.json dispatch {ident}: its loop key cannot be built ({type(exc).__name__})")
        return None


def _dispatch_facts(project, task_dir, now, control, in_flight, events, reasons, loop_reasons):
    starts, odd = {}, 0
    for e in events:
        if e.get("type") != "dispatch":
            continue
        payload = {} if e.get("payload") is None else e.get("payload")
        if isinstance(payload, dict):
            starts[str(payload.get("id"))] = e.get("created_at")
        else:
            odd += 1
    if odd:
        reasons.append(f"events.jsonl: {odd} dispatch event(s) carry a payload that is not a JSON object, "
                       f"so the start of their dispatch is not known")
    out = []
    for ident, record in _shape(control, "dispatches", dict, "controller.json", reasons).items():
        if not isinstance(record, dict):
            continue
        item = {"id": str(ident), "status": record.get("status"), "started_at": starts.get(str(ident)),
                "returned_at": record.get("returned_at"), "liveness": None, "role": str(record.get("role")),
                "key": _loop_key(ident, record, loop_reasons)}
        if item["status"] == RUNNING:
            try:
                handed = dict(record, id=str(ident), started_at=_epoch(item["started_at"]),
                              **({"in_flight": in_flight[str(ident)]} if isinstance(in_flight.get(str(ident)), dict) else {}))
                item["liveness"] = DL.state(project, task_dir.name, handed, _epoch(now)).get("state")
            except Exception as exc:     # an unknown liveness is not proof of life: the safe side is a reason, not a pass
                reasons.append(f"the liveness of dispatch {ident} could not be established ({type(exc).__name__})")
        out.append(item)
    return out


def _in_flight_facts(held):
    out = []
    for ident, entry in held.items() if isinstance(held, dict) else []:
        if not isinstance(entry, dict):
            continue
        pid = entry.get("pid")
        alive = DL.process_alive(pid)
        out.append({"dispatch": str(entry.get("dispatch_id") or ident), "started_at": entry.get("started_at"),
                    "alive": alive, "reused": DL.pid_reused(pid, entry.get("started_at")) if alive else None})
    return out


def _pipeline_last(pipeline):
    last = archive_task.last_activity(pipeline)
    return last.timestamp() if last else None


def read_facts(project, task_dir, now):
    """The facts `judge` needs, from one story's folder: one dict, every source optional, every unreadable one named in
    `unreadable`. Reads only; the `dispatch_liveness` verdicts it asks for are computed at `now` (epoch seconds)."""
    task_dir, reasons = Path(task_dir), []
    state = task_dir / "state"
    pipeline = _json_object(task_dir / "pipeline.json", "pipeline.json", reasons)
    driver = _json_object(state / "driver-state.json", "driver-state.json", reasons) or {}
    control = _json_object(state / "controller.json", "controller.json", reasons) or {}
    events = _jsonl_rows(state / "events.jsonl", "events.jsonl", reasons)
    in_flight = _shape(driver, "in_flight", dict, "driver-state.json", reasons)
    interrupted = _shape(driver, "interrupted", dict, "driver-state.json", reasons)
    pl, loop_reasons = "pipeline.json", []
    return {
        "closed": bool(pipeline and _guard(f"{pl} closed state", lambda: hooklib.story_closed(pipeline), "", reasons)),
        "open_items": _guard(f"{pl} open items", lambda: archive_task.open_items(pipeline), [], reasons) if pipeline else [],
        "driver_question_open": (state / "driver-question.md").is_file(),
        "last_activity": _guard(f"{pl} last activity", lambda: _pipeline_last(pipeline), None, reasons) if pipeline else None,
        "interrupted": [dict(v, key=k) for k, v in interrupted.items() if isinstance(v, dict)],
        "in_flight": _in_flight_facts(in_flight),
        "driver_runs": _jsonl_rows(state / "driver-runs.jsonl", "driver-runs.jsonl", reasons),
        "conductor": _jsonl_rows(state / "conductor.jsonl", "conductor.jsonl", reasons),
        "dispatches": _dispatch_facts(project, task_dir, now, control, in_flight, events, reasons, loop_reasons),
        "events": [{"type": e.get("type"), "created_at": e.get("created_at"), "sequence": e.get("sequence")} for e in events],
        "unreadable": reasons,
        # L (CL3-9): the raw driver-state object (the loop table names its keys, this reader names none), the file's presence, the
        # durable question journal, the person's recorded words; shape checks are the rule's, not the reader's
        "driver_state": driver,
        "driver_state_present": (state / STATE_CARRIER).is_file(),
        "driver_questions": _jsonl_rows(state / "driver-questions.jsonl", "driver-questions.jsonl", loop_reasons),
        "stage_overrides": pipeline.get("stage_overrides") if isinstance(pipeline, dict) else None,
        "loop_unreadable": loop_reasons,
    }


def session_transcripts(project, task_dir):
    """`[{sid, transcript, exists, why?}]`: the story's own sessions - the ids its driver journal and `driver-state.json`
    name (FR-24), plus any cost file whose `by_task` names the ticket - and the `transcript` each cost file recorded.

    A carrier that is there and cannot be read (a broken `driver-state.json`, a broken line of the driver journal) comes back
    as one more entry per reason, `{sid: None, transcript: None, exists: False, unreadable: True, why}`: the sessions it
    would have named are not known, and the sessions the other carriers name are still returned."""
    task_dir = Path(task_dir)
    reasons: list = []
    sids = {str(r["session_id"]) for r in _jsonl_rows(task_dir / "state" / "driver-runs.jsonl", "driver-runs.jsonl", reasons)
            if isinstance(r.get("session_id"), str) and r["session_id"]}
    held = _shape(_json_object(task_dir / "state" / "driver-state.json", "driver-state.json", reasons) or {},
                  "sessions", dict, "driver-state.json", reasons)
    sids |= {str(v) for v in held.values() if isinstance(v, str) and v}
    out, seen = [], set()
    for path in hooklib.sorted_paths((Path(project) / "qa-factory" / "state" / "cost").glob("*.json")):
        doc = hooklib.read_json(path, None, errors=Exception, kind=dict)
        by_task = doc.get("by_task") if doc is not None else None
        if doc is None or not (path.stem in sids or (isinstance(by_task, dict) and task_dir.name in by_task)):
            continue
        seen.add(path.stem)
        transcript = doc.get("transcript")
        out.append({"sid": path.stem, "transcript": str(transcript) if transcript else None,
                    "exists": bool(transcript) and Path(str(transcript)).is_file(),
                    **({} if transcript else {"why": "the cost file records no transcript"})})
    out += [{"sid": s, "transcript": None, "exists": False, "why": "no cost file for this session"} for s in sorted(sids - seen)]
    return out + [{"sid": None, "transcript": None, "exists": False, "unreadable": True, "why": r} for r in reasons]


def load_loops(path=None):
    """The loop table (`references/collect-loops.json`), validated; the ONE reader. Anything wrong raises
    `ValueError("<path>: <what>")`: a half table would pack by guess. `path=None` is resolved HERE at call time, so a test can
    point `LOOPS_FILE` at a copy."""
    path = Path(path) if path is not None else LOOPS_FILE
    nothing = object()
    data = hooklib.read_json(path, nothing, errors=Exception)

    def bad(why):
        return ValueError(f"{path}: {why}")

    def count(value):
        return isinstance(value, int) and not isinstance(value, bool)
    if data is nothing:
        raise bad("absent or not valid JSON")
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise bad("not a JSON object of schema 1")
    cfg = data.get("repeat_dispatch")
    for field in ("max_normal", "max_normal_repair_roles"):
        if not isinstance(cfg, dict) or not count(cfg.get(field)) or cfg[field] < 1:
            raise bad(f"repeat_dispatch.{field} is not an integer >= 1")
    rows = data.get("records")
    if not isinstance(rows, list):
        raise bad("records is not a list")
    for i, row in enumerate(rows):
        name = f"records[{i}]"
        if not isinstance(row, dict):
            raise bad(f"{name} is not an object")
        for field in ("id", "field", "time"):
            if not isinstance(row.get(field), str) or not row[field]:
                raise bad(f"{name}.{field} is not a word")
        if row.get("shape") not in SHAPES:
            raise bad(f"{name}.shape is not one of {', '.join(SHAPES)}")
        shape, carrier = row["shape"], row.get("carrier")
        if not (carrier in JOURNAL_FACTS if shape == "rows" else carrier == STATE_CARRIER):
            raise bad(f"{name}.carrier ({carrier!r}) does not fit the shape {shape}")
        named = ("kind",) if shape == "rows" and "kind" in row else () if shape == "rows" else ("key",)    # a rows row's `kind` is a filter
        for field in named:
            if not isinstance(row.get(field), str) or not row[field]:
                raise bad(f"{name}.{field} is not a word")
        if shape == "nested_records" and not (isinstance(row.get("inner"), str) and row["inner"]):
            raise bad(f"{name}.inner is not a word")
        values = row.get("values")
        wants, forbids = ("min", "values") if shape == "nested_records" else ("values", "min")
        if wants not in row or forbids in row:
            raise bad(f"{name} (shape {shape}) needs {wants} and no {forbids}")
        if "values" in row and not (isinstance(values, list) and values and all(isinstance(v, str) for v in values)):
            raise bad(f"{name}.values is not a non-empty list of words")
        if "min" in row and not count(row["min"]):
            raise bad(f"{name}.min is not an integer")
    return data


def stall(project, task_dir, mark, now, quiet_hours=DEFAULT_QUIET_HOURS, loop_table=None):
    """`judge(read_facts(...))`: the verdict on the story in `task_dir` of `project`, windowed by `mark`. `loop_table` is
    `load_loops()`'s (the packer loads it once and refuses on a broken one); None loads it here and lets its `ValueError` out."""
    table = loop_table if loop_table is not None else load_loops()
    return judge(read_facts(project, task_dir, now), mark, now, quiet_hours, table)


def transcripts_for(project, task_dir, verdict):
    """H for one story: its sessions, the host-wide subagent list of hooklib (not edited, no glob of our own), the filter."""
    return select_transcripts(verdict, session_transcripts(project, task_dir),
                              hooklib.story_subagent_transcripts(Path(project)))
