"""Is the agent of an open dispatch alive, gone, or never launched — by proof, not by silence.

0.7.6 answered this from the absence of records: a `running` dispatch with no binding in
`state/host-dispatches/` and no `subagent_stop` of its role was "never launched". On the
Claude Code host there are no launch receipts at all, so EVERY genuinely running dispatch
matched that rule until its role stopped — `next` or `recover` called while a role worked
would have closed a live job (TP1-15045). And the opposite case had no answer either:
on TP2-2523 the role started, refused and stopped, its return was written nowhere,
and the dispatch stayed `running` forever with `cancel_allowed: false`.

Three independent kinds of evidence, in the order of how much they prove:

1. the role's own subagent transcript (`hooklib.subagent_meta` /
   `story_subagent_transcripts`) — fresh bytes mean the agent is working;
2. the host's binding receipt under `state/host-dispatches/` — the Codex host's own record;
3. the project journal's `subagent_stop` line for that role after the dispatch started — a
   recorded return, whoever wrote it.

A fourth, for a role the DRIVER launched as its own `claude -p` process (B-268): the driver's `in_flight`
entry in `state/driver-state.json` names the process id; a live pid is `alive`, a gone one is said as such
("the process is gone"), never as "not proven alive".

A fifth, for a native worker a `story_step` receipt is bound to (TP2-2406 S4, 13.10.2026): the HOST's own
rollout of the receipt's exact path. A clean `task_complete` of this launch, older than the grace window and
alone among the path's candidate rollouts, is `returned` (the role stopped - nothing is written, nothing accepted);
a working or still-completing rollout is `alive`; everything else - a rollout nobody can read (compressed, or its
tail cut mid-row), a clock that cannot be trusted, an abort - is no evidence and leaves the receipt branch below
to answer. This evidence errs ONLY toward "not returned" (`native_stop`).

A sixth, the same question for a Claude Code worker a `story_step` receipt is bound to (OH3-16, 22.10.2026): the
HOST's own record that the child handed its report back - the transcript's LAST line is the host's acknowledgement
of the handback call (read by structure, the names from `references/host-report-forms.json`), the sidecar does not
say `not finished`, and the stop hooks have either released it (a journalled stop at or after the acknowledgement) or
had their grace window. The SubagentStop hook's line alone is never a return (it fired four minutes before the
handback in the incident); a child resumed after a handback has rows after the acknowledgement and is `alive`.
`claude_stop` errs ONLY toward "not returned", like `native_stop`; `host_verdict` is the one per-receipt question
both hosts answer, and `worker_lifecycle.active_binding` asks it too.

Absence still proves nothing. A host that keeps none of the three answers `unknown`, and
the caller keeps its conservative behaviour: a story in flight is never closed because a
helper of ours is not installed on that host.

A receipt is a LAUNCH fact: "launched at T" (`bound_at`, or for an older receipt the file's
last write), never "silent since T" - it has no heartbeat. So a non-terminal receipt of THIS
dispatch written within `abandoned_after_s` is `alive`; an older one, or one with no usable
time, is `unknown` ("a launch receipt is not proof its agent is still working"), and the door
is the person's `release`. Age alone never yields `abandoned` or `never_started`, and it never
reaches `role_stops` or the transcript inventory: a matching non-terminal receipt, fresh or
stale, answers before them. A non-terminal receipt of the role that names NO dispatch counts as
"possibly this one" unless its recorded `bound_at` proves it predates this dispatch; a receipt
that names another dispatch is evidence about that dispatch only.
"""
import json
import math
import time
from pathlib import Path
from codex_usage import first_row, stamp
from hooklib import read_json, sorted_paths

ALIVE = "alive"
ABANDONED = "abandoned"
NEVER_STARTED = "never_started"
RETURNED = "returned"
UNKNOWN = "unknown"

# No transcript activity for this long: the agent is gone, not thinking. A role writes to
# its transcript on every tool call and every turn, so ten minutes of complete silence is
# already far past the longest observed gap (TP1-15045: 24-minute windows, never a
# two-minute silence).
DEFAULT_ABANDONED_AFTER_S = 600.0
# No transcript at all this long after the receipt was written: the launch never happened.
DEFAULT_NEVER_STARTED_AFTER_S = 180.0
# Clocks of the writer and the reader of a receipt or a transcript differ by this much at most.
_CLOCK_SKEW_S = 60.0
# How long after a rollout's `task_complete` the host may still send the worker back: its SubagentStop group
# (exit_gate -> subagent_journal -> cost_capture, hooks/codex.json) runs after the row is written and a blocking
# answer resumes the child. Measured on this project's telemetry (Claude-host runs, 182 stops; no Codex telemetry on
# the machine): exit_gate max 8 s, subagent_journal max 87 s, cost_capture max 164 s - the sum of the maxima is about
# 260 s, so 300 s. Data, not code (FR-13): `dispatch.native_completion_grace_s`. The price is that a checkpoint waits
# this long after a worker's genuine return; the alternative is a duplicate beside a worker the hooks sent back.
NATIVE_COMPLETION_GRACE_S = 300.0


def thresholds(project_root) -> dict:
    """The waiting times, optionally tuned per project in `qa-factory/config.json`.

    Optional by design: a project onboarded on 0.7.x has no `dispatch` section and must keep
    working with the defaults above.
    """
    values = {"abandoned_after_s": DEFAULT_ABANDONED_AFTER_S,
              "never_started_after_s": DEFAULT_NEVER_STARTED_AFTER_S,
              "native_completion_grace_s": NATIVE_COMPLETION_GRACE_S}
    try:
        config = json.loads((Path(project_root) / "qa-factory" / "config.json")
                            .read_text(encoding="utf-8-sig"))
        section = config.get("dispatch") if isinstance(config, dict) else None
        for key in values:
            candidate = (section or {}).get(key)
            if isinstance(candidate, (int, float)) and not isinstance(candidate, bool) and candidate > 0:
                values[key] = float(candidate)
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return values


def _started_at(dispatch) -> float | None:
    for key in ("started_at", "created_at", "dispatched_at"):
        value = dispatch.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def session_transcripts(project_root, since: float = 0.0) -> list:
    """The transcripts a driver's role sessions write: a driver role is its OWN `claude -p` session, so its transcript is a MAIN one
    (`<folder>/<session>.jsonl`), never under `subagents/` (which is all `transcripts()` sees). The folders are the parents of the
    `transcript` paths in `qa-factory/state/cost/*.json` (the layout `cost_capture` writes - no guess at the host's folder encoding);
    the files are the `*.jsonl` there written at or after `since` (epoch). Never raises; no cost file yet is an empty list."""
    folders, found = set(), []
    try:
        cost_dir = Path(project_root) / "qa-factory" / "state" / "cost"
        for cost_file in sorted(cost_dir.glob("*.json")):
            try:
                transcript = json.loads(cost_file.read_text(encoding="utf-8")).get("transcript")
            except (OSError, ValueError, AttributeError):
                continue
            if transcript:
                folders.add(Path(transcript).parent)
        for folder in sorted(folders):
            for path in sorted(folder.glob("*.jsonl")):
                try:
                    if path.stat().st_mtime >= since:
                        found.append(path)
                except OSError:
                    continue
    except Exception:  # noqa: BLE001
        return found
    return found


def transcripts(project_root) -> list | None:
    """Every subagent transcript this host kept for the project, with its parsed header.

    `None` — this host tells us nothing (the helpers are not installed, or reading them
    failed). An empty list is treated the same way by `state()`: a cost file may simply not
    have been written yet, and "no transcript exists anywhere" must never become evidence
    that a running role does not exist.
    """
    try:
        import hooklib
        collect = getattr(hooklib, "story_subagent_transcripts", None)
        describe = getattr(hooklib, "subagent_meta", None)
        if collect is None or describe is None:
            return None
        paths = collect(Path(project_root)) or []
    except Exception:
        return None
    found = []
    for path in paths:
        try:
            meta = dict(describe(Path(path)) or {})
        except Exception:
            continue
        meta["path"] = str(path)
        if not isinstance(meta.get("last_at"), (int, float)):
            try:
                meta["last_at"] = Path(path).stat().st_mtime
            except OSError:
                meta["last_at"] = None
        found.append(meta)
    return found


def host_bindings(project_root) -> list:
    """The host's own launch receipts for this project (the Codex host writes them).

    Each record also carries `_file_mtime`: when its file was last written. That is the only time
    a receipt written before `bound_at` existed has, and it is the LAST write, not the launch. And `_file`:
    the file's name, which the journal's `dispatch_receipt` names.
    """
    records = []
    directory = Path(project_root) / "qa-factory" / "state" / "host-dispatches"
    for path in sorted_paths(directory.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and record.get("factory_diagnostic") != "context_probe":
            record["_file"] = path.name
            try:
                record["_file_mtime"] = path.stat().st_mtime
            except OSError:
                record["_file_mtime"] = None
            records.append(record)
    return records


def _usable_time(value) -> float | None:
    """An epoch second a receipt may be judged by: a finite number above zero, never a bool.

    Anything else (a string, true/false, NaN, infinity, a negative, zero, null, a huge integer)
    is absent: a receipt is a record somebody else wrote, and a nonsense time must not decide
    whether a worker is alive.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        when = float(value)
    except OverflowError:
        return None
    return when if math.isfinite(when) and when > 0 else None


def _receipt_age(binding, now) -> tuple:
    """`(age_in_seconds | None, source)` of a host receipt: how long ago it was written.

    `bound_at` (the launch, set once by the receipt's writer) first - source "recorded"; a receipt
    written before it existed has only its file time - source "file time". No usable time:
    `(None, None)`. A time ahead of `now` by up to a minute is clock skew between the writer and
    this reader (the skew the transcript match in `state` already allows) and counts as age 0;
    further ahead it cannot be trusted at all: `(None, "ahead")`. A recorded time that is ahead is
    NOT replaced by the file time: two disagreeing clocks are not evidence of anything.

    The age says how long ago the launch was recorded. A receipt has no heartbeat - it never says
    "silent since T" - so a large age is a reason to ask, not proof of anything.
    """
    for key, source in (("bound_at", "recorded"), ("_file_mtime", "file time")):
        when = _usable_time(binding.get(key))
        if when is None:
            continue
        if when - now > _CLOCK_SKEW_S:
            return None, "ahead"
        return max(now - when, 0.0), source
    return None, None


# A story_step receipt is written AFTER the spawn returns, so the child's rollout began a little before the
# receipt's `bound_at` (TP2-2406 S4: 40 s). A rollout that began this much earlier still MAY be the same
# launch; an earlier start is another launch under the same path. This is the window for a candidate's START only -
# whether a completion belongs to this launch is `bound_at` itself, with no skew.
_SPAWN_BEFORE_BIND_S = 300.0
# The most of a rollout's end read to find its last two rows. A `task_complete` row carries the worker's whole last
# message, so it can be large (the live S4 last row measured 999 bytes; a test fixture row is 200 KB). A last row
# whose line break lies further than this many bytes from the end of the file is no evidence, never a guess.
_LAST_ROW_CAP_BYTES = 8 * 1024 * 1024


def _row_time(row) -> float | None:
    """Epoch seconds of a rollout row's `timestamp`, or None when it is not a time to trust.

    Only an ISO string that CARRIES A ZONE counts (the host writes `...Z`): a zone-less date reads as local time
    here and as UTC there, a bare number (`20261013`) parses as a date, and a time nobody can place decides nothing -
    the node errs only toward "not returned" (`codex_usage.stamp` is read as it is; the guard lives here)."""
    value = row.get("timestamp") if isinstance(row, dict) else None
    if not isinstance(value, str):
        return None
    when = stamp(value)
    if when is None or when.tzinfo is None:
        return None
    try:
        return _usable_time(when.timestamp())
    except (OverflowError, OSError, ValueError):
        return None


def _iso(epoch) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def _tail(path):
    """`(last, previous, complete)` of a file, read from its END: its last non-empty line, the one before it (None
    when the file has one line or the line lies past the cap), and whether the last line was followed by a line
    break - a line without one is still being written (the rule `codex_usage.scan` applies). None for a file with no
    line, or whose last line starts further than `_LAST_ROW_CAP_BYTES` bytes from the end (a line break within the
    last `_LAST_ROW_CAP_BYTES` bytes is the AT limit; one byte further is beyond it). The window doubles, so the
    bytes read stay within twice the answer."""
    with open(path, "rb") as handle:
        size = handle.seek(0, 2)
        window = 65536
        while True:
            window = min(window, _LAST_ROW_CAP_BYTES)
            start = max(size - window, 0)
            handle.seek(start)
            data = handle.read(size - start)
            body = data.rstrip()
            if start == 0 or body.count(b"\n") >= 2 or window >= _LAST_ROW_CAP_BYTES:
                break
            window *= 2
    parts = body.split(b"\n")
    if start > 0:
        parts = parts[1:]                 # the first piece may begin mid-line
    lines = [part.strip() for part in parts if part.strip()]
    if not lines:
        return None
    return lines[-1], (lines[-2] if len(lines) > 1 else None), b"\n" in data[len(body):]


def _json_row(raw):
    try:
        row = json.loads(raw.decode("utf-8"))
    except (ValueError, AttributeError):
        return None
    return row if isinstance(row, dict) else None


def _read_rollout(path, unreadable, event):
    """One cost record's rollout, read from its first row and its end only; None when it is not evidence.

    A compressed rollout (`.jsonl.zst`: every one of this machine's 107) or a file that cannot be read says so in
    `unreadable` (path-free reasons) and is no evidence: its path cannot be known, so nothing can be said of it.
    `event` is the name of the event that ends a turn, from the host's report forms (`codex.completion_event`)."""
    if path.name.endswith(".zst"):
        unreadable.append("compressed (.zst), no decoder")
        return None
    try:
        first = first_row(path)
        meta = first.get("payload") if isinstance(first, dict) else None
        if (not isinstance(meta, dict) or first.get("type") != "session_meta"
                or not isinstance(meta.get("agent_path"), str) or not meta["agent_path"]):
            return None  # not a child rollout: its tail is never read, and nothing is said of its readability (A4)
        tail = _tail(path)
    except (OSError, ValueError) as exc:
        unreadable.append(f"could not be read ({type(exc).__name__})")
        return None
    last = _json_row(tail[0]) if tail else None
    complete = last is not None and tail[2]
    # a tail that is not a whole, parsed row (cut mid-row, garbage, past the cap) is still being written or never
    # finished: the last row that IS whole stands for the rollout's time, and the rollout can never read as completed
    row = last if complete else _json_row(tail[1]) if tail and tail[1] else None
    payload = row.get("payload") if row and isinstance(row.get("payload"), dict) else {}
    last_type = None if row is None else payload.get("type") if row.get("type") == "event_msg" else row.get("type")
    return {"path": str(path), "agent_path": meta["agent_path"], "first_at": _row_time(first), "broken": not complete,
            "last_at": _row_time(row), "last_type": last_type, "event": event,
            "completed_at": _usable_time(payload.get("completed_at")) if complete and last_type == event else None}


def native_rollouts(project_root, unreadable=None, event=None) -> list:
    """The Codex child rollouts this project's cost records point at, read from their first and last rows only.

    `hooklib.story_subagent_transcripts` inventories Claude-style `subagents/agent-*.jsonl` beside the cost
    transcripts, so a Codex child's rollout was never seen (TP2-2406 S4, 13.10.2026). A cost record's
    `transcript` is the host's own file; it counts only when its first row is a `session_meta` that names an
    `agent_path` (read through `codex_usage.first_row`, the one reader of a rollout's first line). Never raises: a
    record or file that cannot be read is skipped, nothing is written; `unreadable`, when given, collects why.

    `event` is the name of the event that ends a turn, when the caller already read the host's forms (`_forms`);
    otherwise it is read here. With no such name no rollout can be told to have ended, so none is returned."""
    found, reasons = [], [] if unreadable is None else unreadable
    if event is None:
        row, _why = _forms({}, "codex")
        event = row["completion_event"] if row else None
    if event is None:
        return found
    for record in sorted_paths((Path(project_root) / "qa-factory" / "state" / "cost").glob("*.json")):
        try:
            named = read_json(record, {}, kind=dict).get("transcript")
            path = Path(named) if isinstance(named, str) and named else None
            rollout = _read_rollout(path, reasons, event) if path is not None and path.is_file() else None
        except (OSError, ValueError, AttributeError, TypeError):
            continue
        if rollout:
            found.append(rollout)
    return found


def native_target(receipt):
    """`(agent_path, bound_at)` of a receipt the host's rollouts can speak about, else None.

    Only a receipt `story_step` bound (`bound_by`), whose `agent_id` is an absolute agent path and whose `bound_at`
    is a usable time: a spawn-time receipt, a name that is not a path or a launch with no time cannot say WHICH
    launch of a path it is."""
    agent, bound_at = receipt.get("agent_id"), _usable_time(receipt.get("bound_at"))
    if (receipt.get("bound_by") != "story_step" or not isinstance(agent, str) or not agent.startswith("/")
            or bound_at is None):
        return None
    return agent, bound_at


def _completion(rollout, now, limits) -> float | None:
    """When a rollout's own clean `task_complete` says its turn ended: `completed_at`, else the last row's time.
    None for a rollout that does not end that way, or whose time cannot be trusted: a last row more than the clock
    skew ahead of `now`, or no usable time at all. A `completed_at` further ahead than the grace window (a clock
    that is wrong, or milliseconds for seconds) is not read: the row's own time stands."""
    if rollout["broken"] or rollout["last_type"] != rollout["event"]:
        return None
    last = rollout["last_at"]
    if last is None or last - now > _CLOCK_SKEW_S:
        return None
    done = rollout["completed_at"]
    return done if done is not None and done - now <= limits["native_completion_grace_s"] else last


def _candidates(rollouts, agent, bound_at, now, limits) -> list:
    """`[(rollout, completion-or-None)]` of every rollout that may be THIS launch of the receipt's exact path.

    The path matches letter for letter (a prefix is another worker); the rollout began no earlier than
    `_SPAWN_BEFORE_BIND_S` before `bound_at` (a rollout with no trusted start stays a candidate - it cannot be ruled
    out, and a candidate can only hold the verdict back); and a clean completion is no earlier than `bound_at`
    itself: a rollout that ended before the receipt was written is an earlier launch under the same path (the
    receipt is keyed by the path), never evidence for this one. No skew in the freeing direction."""
    found = []
    for rollout in rollouts:
        if rollout["agent_path"] != agent or (rollout["first_at"] is not None
                                              and rollout["first_at"] < bound_at - _SPAWN_BEFORE_BIND_S):
            continue
        done = _completion(rollout, now, limits)
        if done is None or done >= bound_at:
            found.append((rollout, done))
    return found


def _rollout_says(rollout, done, agent, now, limits) -> dict:
    """One candidate rollout's vote: RETURNED (a clean completion older than the grace window), ALIVE (written
    recently and not completed, or completed inside the window - its stop hooks may still send it back), or
    `state: None` - blocks a return and holds nothing (a last row whose time is not trusted or lies ahead, an abort,
    a rollout silent past its window). A tail that is not a whole row is alive only inside the grace window of the
    last whole row; any other unfinished rollout inside `abandoned_after_s`."""
    last_at = rollout["last_at"]
    nothing = {"state": None, "last_at": last_at, "evidence": []}
    if last_at is None or last_at - now > _CLOCK_SKEW_S or rollout["last_type"] == "turn_aborted":
        return nothing
    where = f"({rollout['path']})"
    if done is not None:
        if now - done <= limits["native_completion_grace_s"]:
            return {"state": ALIVE, "last_at": done, "evidence": [
                f"the host's rollout for {agent} completed {int(max(now - done, 0))}s ago; its stop hooks may still "
                f"send it back {where}"]}
        return {"state": RETURNED, "last_at": done, "evidence": [
            f"the host's own rollout for {agent} ends with {rollout['event']} at {_iso(done)} {where}; the story_step "
            "receipt stays non-terminal until `story_step finish` or a person's release - the work is not "
            "accepted by this verdict"]}
    idle = now - last_at
    if idle > (limits["native_completion_grace_s"] if rollout["broken"] else limits["abandoned_after_s"]):
        return nothing
    said = "its last row is still being written" if rollout["broken"] else "has not completed"
    return {"state": ALIVE, "last_at": last_at, "evidence": [
        f"the host's rollout for {agent} was written {int(max(idle, 0))}s ago and {said} {where}"]}


def native_stop(project_root, receipt, now, limits, rollouts=None, held=None) -> dict | None:
    """What the host's own rollouts say about a story_step-bound native worker, or None (today's receipt branch).

    TP2-2406 S4 (13.10.2026): the worker's rollout ended with `task_complete`, but its receipt stays
    non-terminal until `story_step finish`, which refused (handoff incomplete, case bytes unpinned) - and the
    receipt kept the dispatch ALIVE, which kept the authorized checkpoint refused. The host's own completion
    record for the receipt's EXACT path and THIS launch is not inference, so it is read here. The receipt is
    not written and the work is not accepted: RETURNED is "the role stopped", and what it left is the
    orchestrator's to settle.

    The function advises the liveness answer AND frees the controller's checkpoint and, through it, the spawn
    guard - so it errs only toward "not returned": every doubt is None (the caller's own answer). ALL the
    candidate rollouts of the path (`_candidates`) vote; one ALIVE vote wins; RETURNED needs EVERY candidate to be a
    settled clean completion, so a second rollout of the path that is still written, cut mid-row, aborted or
    unreadable-in-time holds the return back. No candidate, a receipt the rollouts cannot speak about, no
    cost record, no readable rollout: None. `rollouts` is the list `native_rollouts` returned, when the caller
    already read it (one read per verdict). The name of the event that ends a turn is the host's report form
    (`codex.completion_event`, through `host_adapter.report_forms`): with no such form this is None too, and
    the reason is said by `_native_verdict` (`held` is the dict of the reads one verdict shares)."""
    target = native_target(receipt)
    if target is None:
        return None
    held = {} if held is None else held
    row, _why = _forms(held, "codex")
    if row is None:
        return None
    agent, bound_at = target
    if rollouts is None:
        rollouts = native_rollouts(project_root, None, row["completion_event"])
    mine = _candidates(rollouts, agent, bound_at, now, limits)
    votes = [_rollout_says(rollout, done, agent, now, limits) for rollout, done in mine]
    alive = [vote for vote in votes if vote["state"] == ALIVE]
    if alive:
        return max(alive, key=lambda vote: vote["last_at"])
    if votes and all(vote["state"] == RETURNED for vote in votes):
        return {"state": RETURNED, "last_at": max(vote["last_at"] for vote in votes),
                "evidence": [line for vote in votes for line in vote["evidence"]]}
    return None


def _forms(held, host):
    """`(row, reason)`: ONE host's rows of the host's report forms, read once per `held` (the dict of the reads one
    verdict shares). The reader is `host_adapter.report_forms` and no other (AR-13); a host whose rows cannot be read
    has NO forms - `row` is None, `reason` says why, and the reason joins `held["notes"]` (FR-41: said, not left out).
    There is no default here: a name typed into this module would be the form the data file exists to keep out."""
    key = "forms:" + host
    if key not in held:
        try:
            import host_adapter
            forms, why = host_adapter.report_forms(host=host)
            row = forms.get(host) if isinstance(forms, dict) else None
        except Exception as error:  # noqa: BLE001 - a reader that fails is "no forms", never a pass
            row, why = None, f"host report forms unreadable: {error.__class__.__name__}"
        if not isinstance(row, dict):
            row, why = None, why or f"host report forms hold no {host} row"
            held.setdefault("notes", []).append(why)
        held[key] = (row, why)
    return held[key]


def host_verdict(project_root, receipt, now, limits, held=None) -> dict | None:
    """The ONE per-receipt question about a non-terminal `story_step` receipt, for both hosts: a Codex receipt (its
    `agent_id` an agent path) asks the host's rollouts (`native_stop`), a Claude Code receipt asks the host's
    transcripts (`claude_stop`). A verdict dict (`state` RETURNED or ALIVE) or None - a receipt neither reader can
    speak about, which blocks a return. `held` shares the reads between the receipts of one call; the two readers
    of the answer, `state` here and `worker_lifecycle.active_binding`, both come through this function."""
    held = {} if held is None else held
    if native_target(receipt) is not None:
        row, _why = _forms(held, "codex")
        if row is None:
            return None
        if "rollouts" not in held:
            held["rollouts"] = native_rollouts(project_root, held.setdefault("unreadable", []), row["completion_event"])
        return native_stop(project_root, receipt, now, limits, held["rollouts"], held)
    if _claude_receipt(receipt):
        return claude_stop(project_root, receipt, now, limits, held)
    return None


def _native_verdict(project_root, waiting, now, limits, held=None):
    """`(verdict-or-None, notes)`: what the host's own records say about ALL the non-terminal receipts of one dispatch.

    Every receipt is asked (`host_verdict`). One that is ALIVE wins at once; RETURNED needs every receipt to be
    RETURNED by the host's record, so a receipt the host says nothing about (a spawn-time receipt, a rollout not
    found, a silent one) blocks it: a running second receipt of the same dispatch is never read as returned.
    `worker_lifecycle.active_binding` asks the same question per receipt, so the two readers agree. `notes` are the
    evidence lines of rollouts the host's cost records named and nobody could read, and of report forms nobody could
    read (FR-41: no evidence is said, not left out)."""
    if not any(native_target(receipt) or _claude_receipt(receipt) for receipt in waiting):
        return None, []
    held = {} if held is None else held
    verdicts = [host_verdict(project_root, receipt, now, limits, held) for receipt in waiting]
    unreadable = held.get("unreadable", [])
    notes = [f"rollout unreadable: {reason}" + (f" (x{unreadable.count(reason)})" if unreadable.count(reason) > 1 else "")
             for reason in dict.fromkeys(unreadable)] + list(dict.fromkeys(held.get("notes", [])))
    alive = next((v for v in verdicts if v and v["state"] == ALIVE), None)
    if alive:
        return alive, notes
    if all(v and v["state"] == RETURNED for v in verdicts):
        return {"state": RETURNED, "last_at": max(v["last_at"] for v in verdicts),
                "evidence": [line for v in verdicts for line in v["evidence"]]}, notes
    return None, notes


# --- Claude Code: the host's own record that a story_step-bound child handed its report back (OH3-16) ---------------

# Whole seconds: the journal's `ts` has a resolution of one, the host's row of a millisecond, and both clocks are this
# machine's. A stop line written within this much BEFORE the acknowledgement still belongs to the same stop.
_STOP_BEFORE_ACK_S = 1.0
# The statuses with which the SubagentStop hook (`subagent_journal`) lets a child go: a stop that is anything else
# (`incomplete`) is the gate sending the child back, and holds a return back.
_RELEASED_STOPS = ("completed", "awaiting_human")


def _claude_receipt(receipt) -> bool:
    """Is this a receipt `claude_stop` speaks about: `story_step` bound it and its `agent_id` is a name, not the
    absolute agent path of a Codex worker (`native_target` speaks about those)."""
    agent = receipt.get("agent_id") if isinstance(receipt, dict) else None
    return (isinstance(receipt, dict) and receipt.get("bound_by") == "story_step" and isinstance(agent, str)
            and bool(agent) and not agent.startswith("/"))


def _stop_records(project_root) -> list:
    """Every `subagent_stop` line of the project's journal, as `{agent, task, dispatch, dispatch_receipt, status,
    ts}` (`ts` an epoch or None, the rest text): THE parser of those lines (AR-13) - `role_stops` and the Claude
    return reader are views over it. Never raises: a journal that is absent or unreadable gives no lines, and a
    reader that has none holds nothing back and frees nothing."""
    try:
        import runtime_paths as RP      # the journal is a carried record: records/, or state/ before the move
        path = RP.record(project_root, "journal.jsonl")
        if not path.is_file():
            return []
        from datetime import datetime
        stops = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict) or record.get("event") != "subagent_stop":
                continue
            try:
                when = datetime.fromisoformat(str(record.get("ts"))).timestamp()
            except (TypeError, ValueError, OverflowError, OSError):
                when = None
            stops.append({"agent": str(record.get("agent") or ""), "task": str(record.get("task") or ""),
                          "dispatch": str(record.get("dispatch") or ""),
                          "dispatch_receipt": str(record.get("dispatch_receipt") or ""),
                          "status": str(record.get("status") or ""), "ts": when})
        return stops
    except Exception:  # noqa: BLE001 - no journal is no evidence
        return []


def _ack_id(row, form):
    """The `tool_use_id` a host acknowledgement row answers, or None when the row is not one. By structure, never by
    the words of the reply (FR-12): a `user` row holding exactly one `tool_result` block that is not an error, whose
    content is ONE JSON object carrying the form's field with the form's value - the same type, so the word `true`
    is not the boolean."""
    if row.get("type") != "user":
        return None
    message = row.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list) or len(content) != 1 or not isinstance(content[0], dict):
        return None
    block = content[0]
    use_id, body = block.get("tool_use_id"), block.get("content")
    if block.get("type") != "tool_result" or not isinstance(use_id, str) or not use_id or block.get("is_error"):
        return None
    if isinstance(body, list):
        body = body[0].get("text") if len(body) == 1 and isinstance(body[0], dict) and body[0].get("type") == "text" else None
    try:
        data = json.loads(body) if isinstance(body, str) else None
    except Exception:  # noqa: BLE001 - not JSON, or nested past the parser: not an acknowledgement
        return None
    got = data.get(form["field"]) if isinstance(data, dict) else None
    return use_id if type(got) is type(form["value"]) and got == form["value"] else None


def _is_call(row, use_id, name) -> bool:
    """Is `row` the assistant row that made the call `use_id`, the call's name EXACTLY `name`."""
    message = row.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return (row.get("type") == "assistant" and isinstance(content, list)
            and any(isinstance(block, dict) and block.get("type") == "tool_use" and block.get("id") == use_id
                    and block.get("name") == name for block in content))


def _sidecar_flag(path, marker):
    """The host's own `finished` flag from the sidecar beside a transcript: True, False, or None when the file is
    absent, unreadable, empty, has no such field or holds a value that is not a boolean (an older host writes none,
    and an unreadable value decides nothing)."""
    try:
        data = json.loads(path.with_name(path.stem + marker["file_suffix"]).read_text(encoding="utf-8-sig"))
    except Exception:  # noqa: BLE001
        return None
    value = data.get(marker["field"]) if isinstance(data, dict) else None
    return value if isinstance(value, bool) else None


def _claude_vote(meta, receipt, row, stops, anchored, now, limits) -> dict:
    """One Claude transcript's vote for one receipt: RETURNED, ALIVE (handed back, the stop hooks' window still
    open), or `state: None` - blocks a return and holds nothing. Rows are read from the END (`_tail`).

    RETURNED needs ALL of: the last whole line is the host's acknowledgement of a handback call that is the row
    before it (a call of another tool, or an acknowledgement of anything else, is not a handback); that row's
    time is a zone-bearing one not ahead of the clock; the acknowledgement belongs to THIS dispatch (at or after
    the receipt's `bound_at`, or the transcript's first prompt names the dispatch); the sidecar does not say
    `not finished`; no stop line of this receipt at or after the acknowledgement is anything but released; and the
    hooks' window has closed - a released stop line at or after the acknowledgement, else the grace window."""
    nothing = {"state": None, "last_at": None, "evidence": []}
    path = Path(meta["path"])
    tail = _tail(path)
    if tail is None or not tail[2] or tail[1] is None:      # no line, a last line still being written, no row before it
        return nothing
    ack, call = _json_row(tail[0]), _json_row(tail[1])
    use_id = _ack_id(ack, row["handback_ack"]) if ack is not None else None
    if use_id is None or call is None or not _is_call(call, use_id, row["handback_tool"]):
        return nothing
    when = _row_time(ack)
    if when is None or when - now > _CLOCK_SKEW_S:
        return nothing
    bound_at = _usable_time(receipt.get("bound_at"))
    if not anchored and (bound_at is None or when < bound_at):
        return nothing                                        # an earlier dispatch's acknowledgement
    flag = _sidecar_flag(path, row["finished_marker"])
    if flag is False:
        return nothing                                        # the host's own "not finished" is never overruled
    after = [stop for stop in stops if stop["ts"] is None or stop["ts"] >= when - _STOP_BEFORE_ACK_S]
    if any(stop["status"] not in _RELEASED_STOPS for stop in after):
        return nothing                                        # the gate sent it back
    released = [stop["ts"] for stop in after if stop["ts"] is not None]
    age = max(now - when, 0.0)
    if not released and age <= limits["native_completion_grace_s"]:
        return {"state": ALIVE, "last_at": when, "evidence": [
            f"the host's own transcript records the handback {int(age)}s ago; its stop hooks may still send it back "
            f"({path})"]}
    closed = (f"the stop hooks released it at {_iso(max(released))}" if released else
              f"{int(age)}s have passed and no stop line holds it back")
    evidence = [f"the host's own transcript ends with the handback call and the host's acknowledgement at {_iso(when)} "
                f"({path}); {closed}; the story_step receipt stays non-terminal until `story_step finish` or a person's "
                "release - the work is not accepted by this verdict"]
    if flag is True:
        evidence.append(f"the host's sidecar for it says {row['finished_marker']['field']}: true")
    return {"state": RETURNED, "last_at": when, "evidence": evidence}


def _claude_votes(project_root, receipt, now, limits, held) -> list:
    """`[(meta, vote)]` for every transcript a Claude receipt answers to; empty when there is no evidence to read (no
    forms, no inventory). A transcript answers to the receipt when its file's id is a name the receipt answers to
    (`host_dispatch.binding_names`, AR-5 axis 20) - or when its first prompt names this receipt's dispatch AND ticket
    (`hooklib.subagent_meta`), which also anchors its acknowledgement to the dispatch. A role and ticket alone never
    count. Read once per receipt per `held`."""
    cache = held.setdefault("votes", {})
    if id(receipt) in cache:
        return cache[id(receipt)]
    cache[id(receipt)] = votes = []
    row, _why = _forms(held, "claude")
    if row is None:
        return votes
    if "transcripts" not in held:
        held["transcripts"] = transcripts(project_root)
    if "stops" not in held:
        held["stops"] = _stop_records(project_root)
    from host_dispatch import binding_names, binding_path
    names = binding_names(receipt)
    task, dispatch = str(receipt.get("task_id") or ""), str(receipt.get("dispatch_id") or "")
    file = str(receipt.get("_file") or binding_path(project_root, receipt["agent_id"]).name)
    stops = [stop for stop in held["stops"] if task and stop["task"] == task and (
        stop["dispatch_receipt"] == file or (stop["dispatch"] and (stop["dispatch"] == dispatch
                                                                    or stop["dispatch"] in names)))]
    for meta in held["transcripts"] or []:
        stem = Path(str(meta.get("path"))).stem
        anchored = bool(task and dispatch and str(meta.get("dispatch_id") or "") == dispatch
                        and str(meta.get("ticket") or "") == task)
        if anchored or (stem.startswith("agent-") and stem[len("agent-"):] in names):
            votes.append((meta, _claude_vote(meta, receipt, row, stops, anchored, now, limits)))
    return votes


def claude_stop(project_root, receipt, now, limits, held=None) -> dict | None:
    """What the host's own transcripts say about a story_step-bound Claude Code worker, or None (today's answer).

    The Claude twin of `native_stop`. OH3-16 (22.10.2026): a critic handed its report back and was judged `alive`
    for ever - its transcript was fresh, then its receipt (non-terminal until `story_step finish`) was old, and the
    SubagentStop hook's journal line did not help (it only journals for a story_step dispatch; and the same hook
    wrote `completed` lines four minutes BEFORE the handback, so a stop line alone is no return). The record that
    is one: the child's transcript ends with the host's acknowledgement of its handback call (`_claude_vote`).

    It advises the liveness answer AND frees the controller's checkpoint and, through `recover`, the spawn guard,
    so it errs ONLY toward "not returned": ALL the transcripts the receipt answers to vote, one ALIVE wins,
    RETURNED needs every one to be RETURNED, anything else is None. Never raises, never writes. The receipt is not
    marked terminal and the work is not accepted: RETURNED is "the role stopped"."""
    try:
        if not _claude_receipt(receipt):
            return None
        held = {} if held is None else held
        votes = [vote for _meta, vote in _claude_votes(project_root, receipt, now, limits, held)]
        alive = [vote for vote in votes if vote["state"] == ALIVE]
        if alive:
            return max(alive, key=lambda vote: vote["last_at"])
        if votes and all(vote["state"] == RETURNED for vote in votes):
            return {"state": RETURNED, "last_at": max(vote["last_at"] for vote in votes),
                    "evidence": [line for vote in votes for line in vote["evidence"]]}
    except Exception:  # noqa: BLE001 - a helper that cannot read proves nothing
        pass
    return None


def _returned_transcripts(project_root, waiting, now, limits, held) -> set:
    """The paths of the transcripts a Claude receipt of this dispatch has handed back (`_claude_vote` RETURNED).
    `state` does not read their last write as "written recently": the handback IS their last write. Any other
    transcript, and any transcript with bytes after its acknowledgement, is not in this set. Never raises."""
    try:
        return {str(meta.get("path")) for receipt in waiting if _claude_receipt(receipt)
                for meta, vote in _claude_votes(project_root, receipt, now, limits, held) if vote["state"] == RETURNED}
    except Exception:  # noqa: BLE001
        return set()


def _may_be_this_dispatch(binding, role, ticket, began) -> bool:
    """Could this non-terminal receipt of the story's role be the dispatch being asked about?

    Only a receipt that names no dispatch (the writer leaves the id empty when two dispatches of
    the role run) and is not PROVEN to predate this one: a recorded `bound_at` more than the skew
    before `began`. File time is never that proof - it is the last write, which a launch long ago
    can still have. `began` unknown: the receipt counts. A receipt that names another dispatch is
    evidence about that dispatch only (TP2-2406: -19 kept `running`, -20 never launched).
    """
    if (str(binding.get("agent_type") or "") != role or str(binding.get("task_id") or "") != str(ticket)
            or str(binding.get("status") or "") == "terminal" or str(binding.get("dispatch_id") or "")):
        return False
    recorded = _usable_time(binding.get("bound_at"))
    return not (began is not None and recorded is not None and recorded < began - _CLOCK_SKEW_S)


def driver_session_end(project_root, ticket, identifier):
    """`(epoch, exit_code)` of the LAST session the driver recorded for this dispatch, or None.

    The three kinds of evidence above were written for a host that launches a role as a subagent
    of the orchestrator. The driver does not: it runs `claude -p --agent` as its own process and
    writes TWO `state/driver-runs.jsonl` rows per call (t-363 B2): a `launched` row before the process starts
    (`dispatch_id`, no `dispatch`, no exit code - this function passes it by) and, when that process exits, the call's
    own row - dispatch, session, exit code and the timestamp. That second row is the strongest proof this factory has
    that a role stopped, and it was not in the list. On TP1-13797 (run 5, 27.09) five of the nine person-boundaries were
    the same question — "confirm this dispatch is dead so I can release it" — while the row had
    been on disk for twenty minutes each time. On this host none of the three kinds exists for a
    driver run at all, so every dispatch answered `unknown`, and `unknown` is reported as "still
    alive" — which is why the person was asked at the end of five stages instead of none.

    The assumption this rests on, said out loud because it is load-bearing: the driver is
    SEQUENTIAL. While a role's session runs, the driver is blocked inside that subprocess and
    launches nothing else; it starts the conductor only after the session ended and the exit gate
    refused. So whenever anybody asks the controller about liveness, the last row is the last
    session, and a row with an exit code means no process of this dispatch is running now. If the
    driver ever launches roles concurrently, this evidence needs an in-flight marker written at
    launch and removed at exit, and this function must read that instead. The marker exists since
    B-268 (`driver-state.json` `in_flight`, read by `in_flight_entry`); it is a rung in `state()`, and
    this row stays the proof of a process that ENDED.
    """
    path = Path(project_root) / "qa-factory" / "artifacts" / str(ticket) / "state" / "driver-runs.jsonl"
    if not identifier or not path.is_file():
        return None
    from datetime import datetime
    last = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or str(row.get("dispatch") or "") != str(identifier):
            continue
        if row.get("exit_code") is None:
            continue                      # a row without an exit code says nothing about ending
        try:
            when = datetime.fromisoformat(str(row.get("ts"))).timestamp()
        except (TypeError, ValueError):
            when = None
        last = (when, row.get("exit_code"))
    return last


def names_no_dispatch(value) -> bool:
    """Does a `subagent_stop` row's `dispatch` field name no dispatch? It is empty (a legacy row) or the gate's own
    sentinel (`exit_gate.UNKNOWN_DISPATCH`, what `exit_gate._identity` writes when the event carries no id at all)."""
    if not value:
        return True
    try:
        from exit_gate import UNKNOWN_DISPATCH
    except Exception:  # noqa: BLE001 - the sentinel cannot be read: the field is then read as naming a dispatch (never closes)
        return False
    return value == UNKNOWN_DISPATCH


def role_stops(project_root, ticket, identifier=None, names=()) -> list:
    """`(role, epoch-or-None, dispatch-field)` for every `subagent_stop` this project journalled for a story: a
    view over `_stop_records`, the one parser of those lines. With `identifier` (the asked dispatch's own id) a stop
    that NAMES another dispatch is left out - a sibling of the same role that stopped says nothing about this one.
    A field names THIS dispatch when it is the id or one of `names` (the host names of the dispatch's receipts,
    `host_dispatch.binding_names`: the stop hook writes the host's agent id there when the event had no `dispatch_id`,
    and `_claude_votes` matches it the same way). A stop that names no dispatch (`names_no_dispatch`: empty or the
    gate's sentinel) is kept, as it always was, and the caller says so."""
    return [(stop["agent"], stop["ts"], stop["dispatch"]) for stop in _stop_records(project_root)
            if stop["task"] == str(ticket)
            and not (identifier and not names_no_dispatch(stop["dispatch"])
                     and stop["dispatch"] != str(identifier) and stop["dispatch"] not in names)]


def process_alive(pid):
    """True / False / None for one process id: None is "could not be asked" (an unusable pid, no permission to
    query, an unexpected error) and is never read as either answer. No `psutil`: `OpenProcess` on Windows,
    `os.kill(pid, 0)` elsewhere. (cost_capture._pid_alive answers True on a doubt - right for a lock that must
    never be broken on a guess, wrong here, where "alive" is the claim a person acts on.)"""
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return None
    try:
        import os
        if os.name == "nt":
            import ctypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            kernel.OpenProcess.restype = ctypes.c_void_p
            kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = kernel.OpenProcess(0x1000, 0, pid)       # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                # 87 = no such process. 5 = access denied: the process EXISTS, but pid 4, lsass or csrss reads the
                # same as a stale pid some protected process took over - and "alive" is the claim a person acts
                # on (and `recover` never closes a dispatch whose process reads alive), so a denied query is "could
                # not be asked", never "alive" (t-335 A2, FR-41)
                return False if ctypes.get_last_error() == 87 else None
            status = ctypes.c_ulong()
            ok = kernel.GetExitCodeProcess(handle, ctypes.byref(status))
            kernel.CloseHandle(handle)
            return None if not ok else status.value == 259    # 259 = STILL_ACTIVE
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return None          # the same denial on POSIX: it exists, and nothing proves it is THE process of the dispatch
    except Exception:
        return None


# Seconds a process's creation may lie after the `started_at` the driver wrote: the driver stamps the entry AFTER
# the process started, truncated to whole seconds, so a live child's creation is at most about a second later than
# its own stamp. A pid taken over by another process is created minutes or hours after it, not seconds.
REUSE_SLACK_S = 2.0


def _epoch(value):
    """Seconds since the epoch of an entry's `started_at` (a number, or the driver's ISO string); None when unreadable."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        from datetime import datetime, timezone
        try:
            when = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return (when if when.tzinfo else when.replace(tzinfo=timezone.utc)).timestamp()
    return None


def process_created_at(pid):
    """Epoch seconds at which the process `pid` was created, or None when that cannot be read (no permission, an
    unusable pid, a host with no way to ask). `GetProcessTimes` on Windows, `/proc/<pid>/stat` starttime on Linux."""
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return None
    try:
        import os
        if os.name == "nt":
            import ctypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            kernel.OpenProcess.restype = ctypes.c_void_p
            kernel.GetProcessTimes.argtypes = [ctypes.c_void_p] + [ctypes.POINTER(ctypes.c_ulonglong)] * 4
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = kernel.OpenProcess(0x1000, 0, pid)
            if not handle:
                return None
            made, gone, kernel_time, user_time = (ctypes.c_ulonglong() for _ in range(4))
            ok = kernel.GetProcessTimes(handle, ctypes.byref(made), ctypes.byref(gone),
                                        ctypes.byref(kernel_time), ctypes.byref(user_time))
            kernel.CloseHandle(handle)
            return (made.value - 116444736000000000) / 1e7 if ok and made.value else None   # FILETIME: 100 ns since 1601
        text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
        ticks = int(text[text.rindex(")") + 2:].split()[19])         # field 22: start time, in ticks since boot
        boot = next(int(line.split()[1]) for line in Path("/proc/stat").read_text().splitlines() if line.startswith("btime "))
        return boot + ticks / os.sysconf("SC_CLK_TCK")
    except Exception:
        return None


def pid_reused(pid, started_at):
    """True when `pid` now belongs to a process created AFTER the one the driver recorded (`started_at`): the dispatch's
    own process ended and a same-user process took its number, which `process_alive` alone reads as "alive". None when
    either time cannot be read - today's answer then stands (an unknown is not a verdict, FR-41)."""
    began, created = _epoch(started_at), process_created_at(pid)
    if began is None or created is None:
        return None
    return created > began + REUSE_SLACK_S


def in_flight_entry(project_root, ticket, identifier):
    """The driver's own `in_flight` entry of this dispatch (B-268: `state/driver-state.json`, written when the
    process starts and removed when it returns), or None - no file, no entry, unreadable. Each dispatch is
    looked up by its own id, so two windows running side by side are two entries read on their own."""
    path = Path(project_root) / "qa-factory" / "artifacts" / str(ticket) / "state" / "driver-state.json"
    if not identifier:
        return None
    try:
        held = json.loads(path.read_text(encoding="utf-8-sig")).get("in_flight")
    except (OSError, ValueError, AttributeError):
        return None
    if not isinstance(held, dict):
        return None
    entry = held.get(str(identifier))
    if isinstance(entry, dict) and str(entry.get("dispatch_id") or identifier) == str(identifier):
        return entry
    return next((e for e in held.values() if isinstance(e, dict) and str(e.get("dispatch_id") or "") == str(identifier)), None)


def state(project_root, ticket, dispatch, now=None) -> dict:
    """What this host can prove about one open dispatch.

    `{"state": alive|abandoned|never_started|returned|unknown, "last_at", "evidence"}`.
    `evidence` is the list of records the verdict rests on, in the caller's own words —
    a closure nobody can explain is how the 0.7.6 defect stayed invisible.

    The driver's `in_flight` entry (B-268) adds a rung on top of `_state`: a pid that is alive is proof the role
    works (`alive`); a pid that is gone adds `"process": "gone"` to whatever the other evidence says, and changes
    NOTHING else - `recover` closes a dispatch on `abandoned`/`returned`, and a record of a process is not a
    reason to close one. An entry with no pid (legacy), no entry, or a pid that could not be asked: today's answer.
    """
    dispatch = dispatch if isinstance(dispatch, dict) else {}
    identifier = str(dispatch.get("id") or "")
    # a caller that already read driver-state.json (story_progress) hands its entry over under `in_flight`: one read,
    # one source (FR-10), and no dependence on where the task folder sits; otherwise the file is read here
    entry = dispatch.get("in_flight") if isinstance(dispatch.get("in_flight"), dict) else in_flight_entry(
        project_root, ticket, identifier)
    alive = process_alive(entry.get("pid")) if entry else None
    taken = bool(alive) and pid_reused(entry.get("pid"), entry.get("started_at")) is True
    if taken:
        alive = False        # the pid is live, but it is another process: this dispatch's own is gone (t-335 A-n1)
    if alive and not (dispatch.get("returned_at") or dispatch.get("returned_digest")):
        return {"state": ALIVE, "last_at": None,
                "evidence": [f"the driver's process {int(entry['pid'])} for this dispatch is running"]}
    verdict = _state(project_root, ticket, dispatch, now)
    if alive is False and verdict.get("state") != ALIVE:
        verdict = dict(verdict, process="gone",
                       evidence=list(verdict.get("evidence") or []) + [
                           f"the driver's process {int(entry['pid'])} for this dispatch is gone"
                           + (" (its number now belongs to a process started later)" if taken else "")])
    return verdict


def _state(project_root, ticket, dispatch, now=None) -> dict:
    dispatch = dispatch if isinstance(dispatch, dict) else {}
    now = time.time() if now is None else float(now)
    limits = thresholds(project_root)
    identifier = str(dispatch.get("id") or "")
    role = str(dispatch.get("role") or "")
    began = _started_at(dispatch)
    evidence = []

    # A return already recorded in the journal by the SubagentStop hook. It is a fact about
    # the role, not a decision about the dispatch: accepting or reworking it stays with the
    # orchestrator.
    if dispatch.get("returned_at") or dispatch.get("returned_digest"):
        return {"state": RETURNED, "last_at": dispatch.get("returned_at"),
                "evidence": ["the role's return was journalled for this dispatch"]}

    found = transcripts(project_root)
    bindings = host_bindings(project_root)
    # Dispatch ids are unique per STORY, not per project: two stories both reach
    # `S5-qa-automator-12`. A receipt of another story - or one that names no story - is no
    # evidence about this dispatch: it can neither close it nor keep it alive. Both receipt
    # writers (host_dispatch.record, story_step.bind) set `task_id` whenever they set `dispatch_id`.
    bound = [b for b in bindings if str(b.get("dispatch_id") or "") == identifier and identifier
             and ticket and str(b.get("task_id") or "") == str(ticket)]
    waiting = [b for b in bound if str(b.get("status") or "") != "terminal"]
    # The reads the host's own records share (`host_verdict`): the transcript inventory is the one just taken.
    held = {"transcripts": found}
    # A transcript a Claude receipt of THIS dispatch has handed back is not "written recently": the handback is its
    # last write, and reading it as activity kept the critic of OH3-16 alive for as long as the receipt was young.
    # Only such transcripts leave `mine`; one with a row after its acknowledgement, and every other, stays.
    returned = _returned_transcripts(project_root, waiting, now, limits, held) if waiting else set()
    mine = []
    for meta in found or []:
        if str(meta.get("path")) in returned:
            continue
        if str(meta.get("dispatch_id") or "") == identifier and identifier:
            mine.append((2, meta))
        elif (role and str(meta.get("role") or "").endswith(role)
              and (not ticket or not meta.get("ticket") or str(meta["ticket"]) == str(ticket))
              and (began is None or not isinstance(meta.get("first_at"), (int, float))
                   or meta["first_at"] >= began - 60)):
            mine.append((1, meta))
    mine.sort(key=lambda item: (item[0], item[1].get("last_at") or 0))
    best = mine[-1][1] if mine else None
    last_at = best.get("last_at") if best else None

    if best and isinstance(last_at, (int, float)):
        idle = now - float(last_at)
        if idle <= limits["abandoned_after_s"]:
            return {"state": ALIVE, "last_at": last_at,
                    "evidence": [f"{best.get('path')} was written {int(max(idle, 0))}s ago"]}
        evidence.append(f"{best.get('path')} has been silent for {int(idle)}s")

    # The driver's own record of the process ending. Placed here on purpose: a transcript still
    # being written wins, so a role that is genuinely working is never declared returned.
    ended = driver_session_end(project_root, ticket, identifier)
    if ended:
        when, code = ended
        return {"state": RETURNED, "last_at": when,
                "evidence": [f"the driver recorded this dispatch's session as ended "
                             f"(exit {code}) in state/driver-runs.jsonl"] + evidence}

    if waiting:
        # A receipt says "launched at T", never "silent since T": it has no heartbeat. So a
        # young one keeps the dispatch alive, and an old one stops saying so - but it proves no
        # death either, so it asks the person (`release`) and closes nothing. Whatever the age,
        # this branch returns before `role_stops` and the transcript inventory can close the
        # dispatch: the position is the invariant, a non-terminal receipt of THIS dispatch is
        # never closed by inference.
        # The one thing read before the age: the HOST's own rollout for the receipt's exact path
        # (`native_stop`; TP2-2406 S4, 13.10.2026: a receipt `finish` could not close kept the
        # dispatch alive while the rollout had ended with task_complete). The invariant stands: this
        # branch closes a dispatch only on the host's own completion record for the receipt's exact
        # path - never on silence, age or a transcript of another path - and it writes nothing. For a Claude Code
        # receipt it is the host's own transcript ending with its acknowledged handback (`claude_stop`, OH3-16), the
        # one transcript the freshness rung above does not count. ALL the waiting
        # receipts are asked (`_native_verdict`): one running second receipt of the dispatch keeps it open. The
        # position is the other half of the invariant: a fresh transcript (any but the handed-back one) and the
        # driver's end row answered above, so a role at work is never declared returned, and this call stays before
        # `ages` so a veto helper that fails leaves today's answer (the `except` below) instead of freeing anything.
        try:
            verdict, notes = _native_verdict(project_root, waiting, now, limits, held)
        except Exception:  # noqa: BLE001 - a helper that cannot read proves nothing
            verdict, notes = None, []
        if verdict:
            return dict(verdict, evidence=evidence + verdict["evidence"])
        evidence = evidence + notes
        ages = [_receipt_age(b, now) for b in waiting]
        known = sorted((age, source) for age, source in ages if age is not None)
        if known and known[0][0] <= limits["abandoned_after_s"]:
            age, source = known[0]
            return {"state": ALIVE, "last_at": last_at,
                    "evidence": evidence + [f"the host receipt of this dispatch was written "
                                            f"{int(age)}s ago (source: {source}) and is not terminal"]}
        if known:
            age, source = known[0]
            when = (f"was written {int(age)}s ago (source: {source}), past the "
                    f"{int(limits['abandoned_after_s'])}s window")
        elif any(source == "ahead" for _age, source in ages):
            when = (f"carries a time more than {int(_CLOCK_SKEW_S)}s ahead of the clock (ahead), "
                    "so its age cannot be trusted")
        else:
            when = "carries no usable time (unknown time)"
        return {"state": UNKNOWN, "last_at": last_at,
                "evidence": evidence + [f"the host receipt of this dispatch is not terminal and {when}; "
                                        "a launch receipt is not proof its agent is still working, nor "
                                        "that it stopped - only a person's release closes it"]}
    if bound:
        return {"state": RETURNED, "last_at": last_at,
                "evidence": evidence + ["the host dispatch receipt for this dispatch is terminal"]}
    if not best and any(_may_be_this_dispatch(b, role, ticket, began) for b in bindings):
        # A receipt for the role of this story that names no dispatch and is not proven older
        # than this one: the writer leaves the id empty when two dispatches of the role run, so
        # it may be THIS one running, and a worker is never closed by inference. A receipt that
        # names another dispatch is evidence about that one only and is not looked at here.
        return {"state": UNKNOWN, "last_at": last_at,
                "evidence": evidence + ["a non-terminal host receipt of this story and role names no "
                                        "dispatch and is not proven older than this one"]}

    try:
        from host_dispatch import binding_names
        # `bound` is empty here (a receipt naming this dispatch answered above), so the receipts that MAY be this
        # dispatch (`_may_be_this_dispatch`: the role's, naming none, not proven older) give the host names
        names = set().union(*(binding_names(b) for b in bindings if _may_be_this_dispatch(b, role, ticket, began)))
    except Exception:  # noqa: BLE001 - no names: only the id itself matches
        names = set()
    for agent, when, stop_of in role_stops(project_root, ticket, identifier, names):
        if not role or not agent.endswith(role):
            continue
        if began is not None and when is not None and when < began - 1:
            continue
        note = [] if not names_no_dispatch(stop_of) else ["that journal row names no dispatch, so it is read as this role's stop"]
        return {"state": RETURNED, "last_at": when if when is not None else last_at,
                "evidence": evidence + [f"the project journal recorded {agent} stopping"
                                        " after this dispatch started"] + note}

    if best:
        return {"state": ABANDONED, "last_at": last_at, "evidence": evidence}
    if found:
        age = None if began is None else now - began
        if age is not None and age > limits["never_started_after_s"]:
            return {"state": NEVER_STARTED, "last_at": None,
                    "evidence": evidence + [
                        f"no subagent transcript names this dispatch {int(age)}s after it was "
                        f"recorded, while this host kept {len(found)} for the project"]}
        return {"state": UNKNOWN, "last_at": None,
                "evidence": evidence + ["no transcript names this dispatch yet; it is too soon to tell"]}
    return {"state": UNKNOWN, "last_at": last_at,
            "evidence": evidence + ["this host recorded no subagent transcript for the project"]}
