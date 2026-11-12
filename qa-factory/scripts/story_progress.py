#!/usr/bin/env python3
"""Where a story stands, in one place: which stage, how far inside it, what is running, what it cost so far.

    python story_progress.py --task-root <artifacts/TASK> [--json]

ONE function, `progress(task_root)`, three readers: the driver prints its `line` at every transition
(`[progress] ...` in the log a watcher follows), the dashboard's story card draws the same dict, and a person
can ask for it on the command line. Nothing here is a second source of truth (FR-10): the dict is computed
from the story's own records - controller.json, pipeline.json, state/events.jsonl, state/driver-state.json,
state/driver-runs.jsonl and the cost files through `task_price` - and never from the memory of a running
process, so a driver that died and a driver that is thinking leave the same tree and read the same.

Why it exists (owner, 02.10): the driver runs the roles as `claude -p` subprocesses, so they are not in the
desktop's task list, and a person could not tell S5's window 2 of 4 from a stalled run. S5 is several windows,
each with an author and a critic and up to `repair_cycles` repair rounds; without a line that says so, the only
way to know where the story is was reading controller.json by hand.

Error directions (FR-41, P18) - what this reader may get wrong, and what it may not:
  * a dispatch the records call `running` is shown as running (with minutes) ONLY when the host can prove the
    role alive (`dispatch_liveness`: a fresh transcript, or - B-268 - the live pid of the driver's own `in_flight`
    entry). A pid known to be gone is said so ("started 05:12, the process is gone"), and a session the driver's own
    journal recorded as ended - a return the hook journalled, or the host's own rollout ending with `task_complete`
    past its grace window - while the record still says `running` is said so too ("returned 05:38, its dispatch
    still open": the Codex smoke of 10.10 read that as "not proven alive" with the end row on disk, and a person
    could not tell a finished scout from a lost one). Anything else is "recorded
    running since 05:12, not proven alive": the allowed error is a false alarm on a live role, never "running 7 h"
    over a dead one (the rehearsal of 02.10 lost its driver at 05:38 and the record kept saying `running`);
  * a total the records do not hold (windows planned, manual blocks left) is `None` and the line says so;
    it is never taken from the groups seen so far;
  * the price is `task_price`'s own answer: one figure when the two records agree, a range when they differ
    (P18), "recorded only" when one record is missing - never one wrong figure as a fact;
  * the clock is read ONCE, at the top of `progress` (`now`): every duration of the answer is measured against
    that one instant, and a duration that would need a live role is not computed for a record nobody proved.

The line is a text a person reads: it names a role in words, never a dispatch id or a field (human-questions.md,
FR-6: `human_text` rejects `S5-qa-code-critic-6` in a text for a person). The ids stay in the dict.
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hooklib  # noqa: E402

LINE_MAX = 160
# The stage whose dispatches are windows (author + critic over a bounded case list).
WINDOW_STAGE = "S5"
# The stage that also runs manual-agent windows of `controller.MANUAL_WINDOW_CASES` cases (t-323 C4, SC2-38: the
# number is the controller's own constant, read where the windows are counted - never a copy of it here).
MANUAL_STAGE = "S6"
NO_COST = "no cost recorded yet"
NO_FIGURE = "cost recorded only, no figure"      # a recorded-only price with no figure to print (t-323 B3)


class StoryProgressError(Exception):
    """A refusal that names the path (FR-1); the CLI prints it, the driver prints it as a line."""


class NoStory(StoryProgressError):
    pass


class Unreadable(StoryProgressError):
    pass


# ------------------------------------------------------------------------------------------- reading

def _load(path: Path):
    """The JSON object in `path`, None when the file is absent; a file that is there and unreadable is named."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise Unreadable(f"{path} cannot be read ({type(exc).__name__}); nothing is shown from a record that "
                         "cannot be read - restore it, or run the controller's recover on the story")
    try:
        data = json.loads(text)
    except ValueError:
        raise Unreadable(f"{path} is not readable JSON; nothing is shown from a damaged record - "
                         "restore it, or run the controller's recover on the story")
    if not isinstance(data, dict):
        raise Unreadable(f"{path} does not hold an object; nothing is shown from a damaged record")
    return data


def _optional(path: Path, gaps: list):
    """A record the answer can do without: damaged is a named gap, never a stop (P1: code informs)."""
    try:
        return _load(path)
    except StoryProgressError as exc:
        gaps.append(str(exc).split(";")[0])
        return None


def _jsonl(path: Path) -> list:
    rows = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    except OSError:
        pass
    return rows


def _epoch(value):
    """Epoch seconds from an epoch number or an ISO string (a zone-less one is read as UTC), else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        when = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return (when if when.tzinfo else when.replace(tzinfo=timezone.utc)).timestamp()


def _iso(epoch):
    return None if epoch is None else datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


def _hhmm(epoch) -> str:
    return time.strftime("%H:%M", time.localtime(epoch))


def _words(minutes) -> str:
    """A duration a person reads: 14 min, 3 h 12 min, 2 days."""
    minutes = max(int(minutes), 0)
    if minutes < 60:
        return f"{minutes} min"
    if minutes < 48 * 60:
        hours, rest = divmod(minutes, 60)
        return f"{hours} h {rest} min" if rest else f"{hours} h"
    return f"{minutes // (24 * 60)} days"


def _project_of(task_root: Path):
    """The project root, found from the task's own place (never from a path stored in a record: a story moved
    to another machine keeps its old absolute paths, t-294): the first parent that holds qa-factory/config.json."""
    here = task_root.resolve()
    return next((p for p in (here, *here.parents) if (p / "qa-factory" / "config.json").is_file()), None)


def _stages_table(gaps: list) -> list:
    try:
        import hooklib
        table = hooklib.load_ref_json("stages.json").get("stages") or []
    except Exception:
        table = []
    table = [s for s in table if isinstance(s, dict) and s.get("id")]
    if not table:
        gaps.append("the stage table (stages.json) could not be read; stage names are not shown")
        table = [{"id": f"S{i}", "name": ""} for i in range(10)]
    return table


# ----------------------------------------------------------------------------------------- the pieces

def _started(root: Path, dispatch: dict, in_flight: dict):
    """When the dispatch was recorded, as epoch seconds, or None for a legacy record that holds no time.

    The first record that names it wins: the driver's own `in_flight` entry (written before the launch), then
    the controller's `dispatch` event (what every story has), then a time on the dispatch itself.
    The `in_flight` entry is B-268's shape `{dispatch_id, pid, started_at}` (t-323 B2: t-310 read `dispatch`/`ts`,
    a shape no writer produces - grep for `in_flight` over the package finds this reader only - so there is no
    fallback to the old pair)."""
    ident = str(dispatch.get("id") or "")
    for entry in (in_flight or {}).values():
        if isinstance(entry, dict) and str(entry.get("dispatch_id") or "") == ident and ident:
            when = _epoch(entry.get("started_at"))
            if when is not None:
                return when
    found = None
    try:
        with (root / "state" / "events.jsonl").open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if ident and ident in line and '"dispatch"' in line:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if event.get("type") == "dispatch" and (event.get("payload") or {}).get("id") == ident:
                        found = _epoch(event.get("created_at"))
    except OSError:
        pass
    if found is not None:
        return found
    for key in ("started_at", "created_at", "dispatched_at"):
        when = _epoch(dispatch.get(key))
        if when is not None:
            return when
    return None


def _running(root, project, task, dispatch, in_flight, now, liveness):
    """The `running` entry: what the records say, and what the host could prove of it."""
    started = _started(root, dispatch, in_flight)
    state, evidence, gone, returned = "unknown", [], False, None
    try:
        if liveness is None:
            import dispatch_liveness
            liveness = dispatch_liveness.state
        if project is not None:
            ident = str(dispatch.get("id") or "")
            entry = next((e for e in (in_flight or {}).values()
                          if isinstance(e, dict) and ident and str(e.get("dispatch_id") or "") == ident), None)
            known = dict(dispatch, started_at=started)
            if entry is not None:
                known["in_flight"] = entry          # the entry this reader already holds: liveness reads no second copy
            answer = liveness(project, task, known, now) or {}
            state, evidence = str(answer.get("state") or "unknown"), list(answer.get("evidence") or [])
            gone = answer.get("process") == "gone"      # B-268: the driver's own process of this role has ended
            if state == "returned":
                # the driver's end row, the hook's journalled return or the host's own rollout: when it says the
                # session ended, as epoch seconds, or None for a record that holds no usable time
                returned = _epoch(answer.get("last_at"))
    except Exception as exc:                      # a reader that cannot prove anything proves nothing
        evidence = [f"liveness could not be asked ({type(exc).__name__})"]
    alive = state == "alive"
    minutes = None
    if alive and started is not None:
        minutes = int(max(now - started, 0) // 60)
    young = False
    if state == "unknown" and started is not None:
        try:
            import dispatch_liveness
            young = now - started <= dispatch_liveness.thresholds(project)["never_started_after_s"]
        except Exception:
            young = False
    return {"dispatch": dispatch.get("id"), "role": dispatch.get("role"), "started_at": _iso(started),
            "minutes": minutes, "proven_alive": alive, "liveness": state, "young": young,
            "evidence": evidence[:3], "_started": started, "_gone": gone and not alive,
            "_returned": returned if state == "returned" and not alive else None}


def _role_words(role) -> str:
    text = str(role or "")
    text = text[3:] if text.startswith("qa-") else text
    return text.replace("-", " ").strip() or "role"


def _short_case(case: str, task: str) -> str:
    case = str(case)
    return case[len(task) + 1:] if task and case.startswith(task + "_") else case


def _live(dispatch: dict) -> bool:
    import controller
    return dispatch.get("status") not in controller.DISCOUNTED


def _groups(dispatches: list, key_of) -> list:
    """Dispatches grouped in order of first appearance. A dispatch whose scope sits inside an earlier group's
    scope joins that group: a one-case rework of a window is the window's work, not another window."""
    groups = []
    for d in dispatches:
        scope = set(str(c) for c in d.get("scope") or [])
        key = key_of(d)
        home = next((g for g in groups if g["key"] == key), None)
        if home is None and scope:
            home = next((g for g in groups if scope <= g["scope"]), None)
        if home is None:
            home = {"key": key, "scope": scope, "dispatches": []}
            groups.append(home)
        home["dispatches"].append(d)
    return groups


def _group_done(group: dict) -> bool:
    """A window is done when its last live dispatch is accepted and closes it: the critic's review, or the
    author's mechanical fix (no critic follows one). An accepted author round in the middle closes nothing."""
    live = [d for d in group["dispatches"] if _live(d)]
    if not live:
        return False
    last = live[-1]
    return last.get("status") == "accepted" and (
        last.get("role") == "qa-code-critic" or last.get("repair_cause") == "mechanical")


def _chain_groups(root, controller_state, stage, planned) -> list:
    """The groups of an S5 on the plan form (SC1-14 FJ-B): one per WRITTEN window, i.e. per chain of the author
    (`Controller._written_windows`, the cut's own reading). An author record is in the group of the chain it is a member of -
    a retry, a continuation and every rework of the window, whatever scope it was given, are one window, so a window that
    grew counts once. A critic record joins the chain whose scope holds its own, else the first chain it meets. A LIVE record
    no chain holds keeps the earlier grouping, after the chains; a set-aside one counts for nothing. A history the cut cannot
    read gives the earlier grouping whole."""
    import controller
    try:
        written = controller.Controller(root)._written_windows(controller_state, planned.get("scope") or [])
    except Exception:
        return _groups(stage, controller.window_key)
    groups = [{"key": w["root"], "scope": set(w["scope"]), "members": set(w["members"]), "dispatches": []} for w in written]
    loose = []
    for d in stage:
        home = next((g for g in groups if str(d.get("id")) in g["members"]), None)
        if home is None and d.get("role") == "qa-code-critic":
            seen = {str(c) for c in d.get("scope") or []}
            home = (next((g for g in groups if seen and seen <= g["scope"]), None)
                    or next((g for g in groups if seen & g["scope"]), None))
        if home is not None:
            home["dispatches"].append(d)
        elif _live(d):
            loose.append(d)
    return groups + _groups(loose, controller.window_key)


def _scope_of(root, controller_state, stage, kind=""):
    """The plan's derived scope (`Controller.stage_scope`, read-only), or None when the controller cannot say."""
    try:
        from controller import Controller
        got = Controller(root).stage_scope(stage, controller_state, kind or None)
    except Exception:
        return None
    return got if isinstance(got, dict) and got.get("derived") else None


def _window_position(root, controller_state, dispatches, primary, run):
    """S5: which window, which round, who is working. Totals the records do not hold stay None."""
    import controller
    from runtime_policy import DEFAULT_LIMITS
    # The S5 PLAN dispatch (its scope is every case) is not a window: it would be the first group and every window would join it
    # ("window 1 of 3" for good, `windows_done` wrong; SC1-14 B1a, E33). The plan is shown as its own kind, with the role and no number.
    stage = [d for d in dispatches if d.get("stage") == WINDOW_STAGE and controller.s5_part_of(d) != "plan"]
    plans = [d for d in dispatches if d.get("stage") == WINDOW_STAGE and controller.s5_part_of(d) == "plan" and _live(d)]
    # the live dispatch is the plan: the one running now, or (no window written yet) the latest live plan dispatch
    now_plan = primary if primary and primary.get("stage") == WINDOW_STAGE and controller.s5_part_of(primary) == "plan" else None
    if now_plan or (plans and not stage):
        shown = now_plan or plans[-1]
        return {"kind": "plan", "role": shown.get("role"), "dispatch": shown.get("id")}
    planned = _scope_of(root, controller_state, WINDOW_STAGE)
    # On the plan form (`window_cut` is in the answer) a window is its author's chain, the cut's own reading; `legacy` keeps the
    # grouping by the window key (SC1-14 FJ-B).
    groups = (_chain_groups(root, controller_state, stage, planned) if planned is not None and "window_cut" in planned
              else _groups(stage, controller.window_key))
    anchor = primary if primary and primary.get("stage") == WINDOW_STAGE else (stage[-1] if stage else None)
    home = next((g for g in groups if anchor in g["dispatches"]), groups[-1] if groups else None)
    seen = len(groups)
    total = None
    if planned is not None:
        count = len(planned.get("windows") or [])
        total = count if count and count >= seen else None
    # The rounds are the controller's own count, taken for the same window key the roles are told it under
    # ("Repair round 2 of 2 - the last"): `repair_ledger` collapses a superseded dispatch and its retry
    # into one round, and only a round about the test spends the cap.
    ledger_of = dict(anchor or {}, role="qa-automator") if anchor else None
    counted = controller.repair_ledger(controller_state.get("dispatches") or {}, ledger_of)["counted"] if ledger_of else 0
    role = (primary or {}).get("role") if run else None
    round_role = None if not role else ("critic" if role == "qa-code-critic" else "author")
    open_groups = [g for g in groups if any(d.get("status") == "running" for d in g["dispatches"])]
    return {"kind": "window",
            "window": (groups.index(home) + 1) if home else None,
            "windows_total": total,
            "windows_done": sum(1 for g in groups if _group_done(g)),
            "round": counted, "rounds_total": DEFAULT_LIMITS["repair_cycles"],
            "round_role": round_role,
            "mechanical_fix": bool(run and primary.get("repair_cause") == "mechanical"
                                   and primary.get("role") in controller.AUTHOR_ROLES),
            "dispatch": (anchor or {}).get("id"),
            "other_windows_open": max(len(open_groups) - (1 if home in open_groups else 0), 0)}


def _is_manual(d: dict) -> bool:
    return d.get("stage") == MANUAL_STAGE and (d.get("execution_kind") == "manual" or d.get("purpose") == "manual")


def _on_manual_block(dispatches, primary) -> bool:
    """Is S6 at a manual block: the dispatch running now is one, or (nothing running) the latest S6 one was."""
    if primary is not None:
        return _is_manual(primary)
    latest = [d for d in dispatches if d.get("stage") == MANUAL_STAGE and _live(d)]
    return bool(latest) and _is_manual(latest[-1])


def _block_position(root, controller_state, dispatches, primary, task):
    """S6 manual blocks: block i of n (cases named). A block that was retried is still one block."""
    manual = [d for d in dispatches if _is_manual(d) and _live(d)]
    blocks = []
    for d in manual:
        cases = tuple(str(c) for c in (d.get("manual_case_ids") or d.get("scope") or []))
        if cases not in [b["cases"] for b in blocks]:
            blocks.append({"cases": cases})
    anchor = primary if primary and primary in manual else (manual[-1] if manual else None)
    mine = tuple(str(c) for c in ((anchor or {}).get("manual_case_ids") or (anchor or {}).get("scope") or []))
    index = next((i + 1 for i, b in enumerate(blocks) if b["cases"] == mine), len(blocks))
    total = None
    scope = _scope_of(root, controller_state, MANUAL_STAGE, "manual")
    if scope is not None:
        covered = {c for b in blocks for c in b["cases"]}
        left = [c for c in scope.get("scope") or [] if str(c) not in covered]
        import controller
        # t-1957 N5s (E5s.9, AR-19): the lanes still to walk are counted by the function the driver and the door cut them with
        try:
            keys = controller.lane_keys(root, left)
        except Exception:
            keys = {}                 # unreadable: every case a lane of its own (an account is never guessed)
        total = len(blocks) + len(controller.walk_lanes(left, keys, controller.MANUAL_WINDOW_CASES))
    return {"kind": "block", "block": index, "blocks_total": total,
            "cases": [_short_case(c, task) for c in mine], "dispatch": (anchor or {}).get("id")}


def _spend(root, project, task, price, rows):
    ids = {str(r.get("dispatch")) for r in rows if r.get("dispatch")}
    answer = price if isinstance(price, dict) else None
    if answer is None and project is not None:
        try:
            import task_price
            answer = task_price.task_price(project, task)
        except Exception:
            answer = None
    answer = answer or {}
    low, high = answer.get("price_low_usd"), answer.get("price_high_usd")
    status = str(answer.get("status") or "")
    if low is None or high is None:
        # t-323 B3: a caller that says the one record it has is not cross-checked, with no figure (the dashboard card
        # with no price to print), gets a block that prints no number and says "recorded only"; any other price with
        # no figure stays "no cost recorded yet"
        return {"recorded_usd": None, "range": None, "sources_agree": None,
                "basis": "recorded_only" if status == "not_cross_checked" else "none", "dispatches": len(ids)}
    recorded = (answer.get("totals") or {}).get("b")
    basis = {"agrees": "both", "differs": "both"}.get(status, "recorded_only" if status == "not_cross_checked"
                                                    else "incomplete")
    return {"recorded_usd": round(float(recorded if recorded else low), 2),
            "range": [round(float(low), 2), round(float(high), 2)],
            "sources_agree": True if status == "agrees" else False if status == "differs" else None,
            "basis": basis, "dispatches": len(ids)}


def _spend_text(spend) -> str:
    if spend["range"] is None:
        return NO_FIGURE if spend["basis"] == "recorded_only" else NO_COST
    low, high = spend["range"]
    if spend["sources_agree"] is False and f"{low:.2f}" != f"{high:.2f}":
        return f"${low:.2f}–{high:.2f} so far (sources disagree)"
    one = f"${low:.2f} so far"
    if spend["basis"] == "recorded_only":
        return one + " (recorded only)"
    if spend["basis"] == "incomplete":
        return one + " (not every session is recorded)"
    return one


def _span(ids: list) -> str:
    """S0, S1, S2, S4 -> S0–S2, S4."""
    parts, run = [], []
    for sid in ids:
        number = int(sid[1:]) if sid[1:].isdigit() else None
        if run and number is not None and run[-1][1] == number - 1:
            run.append((sid, number))
        else:
            if run:
                parts.append(run)
            run = [(sid, number)]
    if run:
        parts.append(run)
    return ", ".join(r[0][0] if len(r) == 1 else f"{r[0][0]}–{r[-1][0]}" for r in parts)


# ------------------------------------------------------------------------------------------ the answer

def progress(task_root, *, now=None, liveness=None, price=None, fresh_ok=False) -> dict:
    """The story at `task_root` as a dict (see the module docstring); raises `StoryProgressError` with the path.

    `now`: the clock, read here and nowhere else when not given. `liveness`: a stand-in for
    `dispatch_liveness.state` (tests). `price`: a `task_price` answer the caller already holds (the dashboard
    passes the one its card prints, so a story has one price on a page). `fresh_ok`: a task with no records yet
    is a story that is starting, not an error (the driver's log header)."""
    root = Path(task_root)
    now = time.time() if now is None else float(now)         # THE one place the clock is read
    state_dir = root / "state"
    gaps: list = []
    controller_state = _load(state_dir / "controller.json")
    pipeline = _load(root / "pipeline.json")
    table = _stages_table(gaps)
    order = [s["id"] for s in table]
    names = {s["id"]: str(s.get("name") or "") for s in table}
    if controller_state is None and pipeline is None:
        if not fresh_ok:
            raise NoStory(f"no story here yet: {root} holds no controller.json and no pipeline.json")
        first = order[0]
        return _fresh(root.name, first, names, now, gaps)
    controller_state = controller_state or {}
    pipeline = pipeline or {}
    task = str(pipeline.get("ticket") or root.name)
    dispatches = [dict(d, id=d.get("id") or name) for name, d in (controller_state.get("dispatches") or {}).items()
                  if isinstance(d, dict)]
    driver_state = _optional(state_dir / "driver-state.json", gaps) or {}
    rows = _jsonl(state_dir / "driver-runs.jsonl")
    project = _project_of(root)
    spend = _spend(root, project, task, price, rows)

    def done(sid):
        entry = (pipeline.get("stages") or {}).get(sid)
        if isinstance(entry, dict) and entry.get("status"):
            return entry["status"] == "done"
        return ((controller_state.get("stages") or {}).get(sid) or {}).get("status") == "completed"

    done_ids = [sid for sid in order if done(sid)]
    current = next((sid for sid in order if not done(sid)), None)
    strip = [{"id": sid, "name": names[sid],
              "state": "done" if sid in done_ids else "current" if sid == current else "next"} for sid in order]
    remaining = [sid for sid in order if sid not in done_ids and sid != current]
    out = {"task": task, "stage": {"id": current, "name": names.get(current, ""), "status": "done"},
           "position": {"kind": "done"}, "running": None, "waiting": None, "spend": spend,
           "done": done_ids, "remaining": remaining, "strip": strip, "gaps": gaps}
    if current is None:
        out["parts"] = {"head": "all stages done", "position": "", "activity": "", "spend": _spend_text(spend),
                        "done": ""}
        out["line"] = _compose(out, task)
        return out

    running_all = [d for d in dispatches if d.get("status") == "running"]
    here = [d for d in running_all if d.get("stage") == current]
    primary = (here or running_all or [None])[-1]
    in_flight = driver_state.get("in_flight") if isinstance(driver_state.get("in_flight"), dict) else {}
    run = _running(root, project, task, primary, in_flight, now, liveness) if primary else None
    if run:
        out["running"] = {k: v for k, v in run.items() if not k.startswith("_") and k != "young"}

    stage_row = next((s for s in table if s["id"] == current), {})
    gate = str(stage_row.get("gate_before") or "")
    decided = bool(gate and ((pipeline.get("gates") or {}).get(gate) or any(
        isinstance(d, dict) and d.get("gate") == gate and d.get("status") == "approved"
        for d in (controller_state.get("decisions") or {}).values())))
    asked = driver_state.get("asked") if isinstance(driver_state.get("asked"), dict) else {}
    next_action = controller_state.get("next_action") if isinstance(controller_state.get("next_action"), dict) else {}
    waiting_gate = (str(next_action.get("gate") or "") if next_action.get("action") == "await_gate"
                    else (gate if gate and not decided else ""))
    status = str(((pipeline.get("stages") or {}).get(current) or {}).get("status") or "pending")
    if asked.get("kind"):
        since = _epoch(asked.get("at"))
        if since is None:                                   # an older record without `at`: the latest post
            posts = [r for r in _jsonl(state_dir / "driver-questions.jsonl")
                     if r.get("kind") == asked.get("kind") and r.get("stage") == asked.get("stage")]
            since = _epoch(posts[-1].get("ts")) if posts else None
        kind = str(asked["kind"])
        is_gate = kind.startswith("gate_")
        out["waiting"] = {"kind": "gate" if is_gate else "question", "gate": kind[5:] if is_gate else None,
                          "question": None if is_gate else kind, "since": _iso(since),
                          "minutes": None if since is None else int(max(now - since, 0) // 60)}
        out["position"] = ({"kind": "gate", "gate": kind[5:]} if is_gate
                           else {"kind": "question", "question": kind})
    elif waiting_gate:
        out["waiting"] = {"kind": "gate", "gate": waiting_gate, "question": None, "since": None, "minutes": None}
        out["position"] = {"kind": "gate", "gate": waiting_gate}
    elif not here and _code_only(root, current):
        out["position"] = {"kind": "code_only", "reason": _code_only(root, current)}
    elif current == WINDOW_STAGE and dispatches and any(d.get("stage") == current for d in dispatches):
        out["position"] = _window_position(root, controller_state, dispatches, primary, run)
    elif current == MANUAL_STAGE and _on_manual_block(dispatches, primary):
        out["position"] = _block_position(root, controller_state, dispatches, primary, task)
    else:
        mine = [d for d in dispatches if d.get("stage") == current]
        out["position"] = {"kind": "dispatch",
                           "dispatch": (primary or (mine[-1] if mine else {})).get("id")}
    if current == WINDOW_STAGE and out["position"]["kind"] == "dispatch" and not any(
            d.get("stage") == current for d in dispatches):
        planned = _scope_of(root, controller_state, WINDOW_STAGE)
        if planned is not None and not planned.get("scope"):
            out["position"] = {"kind": "code_only",
                               "reason": "nothing to automate: the approved plan names no case to automate"}
    out["stage"]["status"] = ("waiting" if out["waiting"] else "running" if run
                              else status if status in ("running", "halted") else "pending")
    out["parts"] = _parts(out, run, task, now)
    out["line"] = _compose(out, task)
    return out


def _code_only(root: Path, stage: str) -> str:
    """The reason of a stage the factory closes itself ("nothing to triage"), when its record is there."""
    reason = ""
    try:
        with (root / "state" / "events.jsonl").open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if '"code_only"' in line:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    payload = event.get("payload") or {}
                    if event.get("type") == "code_only" and payload.get("stage") == stage:
                        reason = " ".join(str(payload.get("reason") or "").split())
    except OSError:
        pass
    return reason


def _fresh(task, first, names, now, gaps) -> dict:
    spend = {"recorded_usd": None, "range": None, "sources_agree": None, "basis": "none", "dispatches": 0}
    out = {"task": task, "stage": {"id": first, "name": names.get(first, ""), "status": "pending"},
           "position": {"kind": "dispatch", "dispatch": None}, "running": None, "waiting": None,
           "spend": spend, "done": [], "remaining": [], "strip": [], "gaps": gaps}
    out["parts"] = _parts(out, None, task, now)
    out["line"] = _compose(out, task)
    return out


# ------------------------------------------------------------------------------------------- the words

def _head(d) -> str:
    stage = d["stage"]
    return f"{stage['id']} {stage['name']}".strip() + (" (halted)" if stage["status"] == "halted" else "")


def _parts(d, run, task, now) -> dict:
    """The line's components, in words: the HTML reads these as they are and never works anything out."""
    pos, parts = d["position"], {"head": _head(d), "position": "", "activity": "", "done": ""}
    kind = pos["kind"]
    if kind == "window":
        total = pos["windows_total"]
        text = (f"window {pos['window']} of {total} planned" if total
                else f"window {pos['window']} (total not known yet)")
        who = f" ({pos['round_role']}{', mechanical fix' if pos['mechanical_fix'] else ''})" if pos["round_role"] else ""
        text += " · " + (f"round {pos['round']} of {pos['rounds_total']}" if pos["round"]
                              else "first pass") + who
        parts["position"] = text
    elif kind == "plan":
        parts["position"] = "the automation plan, before the windows"
    elif kind == "block":
        total = pos["blocks_total"]
        text = f"manual block {pos['block']} of {total}" if total else f"manual block {pos['block']} (total not known yet)"
        parts["position"] = text + (": " + ", ".join(pos["cases"]) if pos["cases"] else "")
    elif kind == "gate":
        w = d["waiting"] or {}
        parts["position"] = f"waiting for your word at gate {pos['gate']}"
        if w.get("since"):
            since = _epoch(w["since"])
            parts["position"] += f" since {_hhmm(since)} ({_words(w['minutes'])})"
    elif kind == "question":
        w = d["waiting"] or {}
        parts["position"] = f"waiting for your answer ({pos['question'].replace('_', ' ')})"
        if w.get("since"):
            parts["position"] += f" since {_hhmm(_epoch(w['since']))} ({_words(w['minutes'])})"
    elif kind == "code_only":
        parts["position"] = "closed by the factory itself" + (f": {pos['reason']}" if pos.get("reason") else "")
    if run:
        who = "the " + _role_words(run["role"])
        if run["proven_alive"]:
            parts["activity"] = f"{who} running" + (f" {_words(run['minutes'])}" if run["minutes"] is not None else "")
        elif run.get("_gone"):
            # B-268: the driver recorded the process and it is no longer there - a fact, not a doubt, so it is
            # not said as "not proven alive"
            parts["activity"] = (f"{who} started {_hhmm(run['_started'])}, the process is gone"
                                 if run.get("_started") is not None else f"{who} recorded running, the process is gone")
        elif run.get("liveness") == "returned":
            # the session ENDED (the driver's journal, the hook's journalled return or the host's own rollout) and
            # the dispatch record still says running - the role finished and nobody closed the dispatch yet. A fact,
            # said as one: the Codex smoke of 10.10 printed "not proven alive" over an end row ten seconds old. After
            # `_gone` (a process known gone is said first) and before `young` ("no proof of work yet" is never said of
            # a role that returned); no path, no dispatch id: the evidence stays in the dict
            parts["activity"] = (f"{who} returned {_hhmm(run['_returned'])}, its dispatch still open"
                                 if run.get("_returned") is not None else f"{who} returned, its dispatch still open")
        elif run["young"] and run.get("_started") is not None:
            parts["activity"] = f"{who} started {_hhmm(run['_started'])}, no proof of work yet"
        else:
            parts["activity"] = (f"{who} recorded running since {_hhmm(run['_started'])}, not proven alive"
                                 if run.get("_started") is not None else f"{who} recorded running, not proven alive")
        others = pos.get("other_windows_open") or 0
        if others:
            parts["activity"] += f" · {others} other window{'s' if others > 1 else ''} open"
    elif kind == "dispatch" and not d["waiting"]:
        if pos.get("dispatch"):
            parts["activity"] = "no role running"
        else:
            parts["head"] = "starting " + parts["head"]       # no dispatch of this stage yet
    elif kind in ("window", "block"):
        parts["activity"] = "no role running"
    parts["spend"] = _spend_text(d["spend"])
    parts["done"] = f"done {_span(d['done'])}" if d["done"] else ""
    return parts


def _compose(d, task) -> str:
    """The one line, at most LINE_MAX characters: when it is too long the case names go first, then the
    list of finished stages, and a line that is still too long is cut with an ellipsis (the dict keeps all)."""
    parts = d["parts"]
    pos = d["position"]

    def build(cases=True, tail=True):
        position = parts["position"]
        if not cases and pos["kind"] == "block" and ": " in position:
            position = position.split(": ")[0]
        bits = [parts["head"], position, parts["activity"], parts["spend"], parts["done"] if tail else ""]
        return " · ".join(b for b in bits if b)

    for cases, tail in ((True, True), (False, True), (False, False)):
        line = build(cases, tail)
        if len(line) <= LINE_MAX:
            return line
    return line[:LINE_MAX - 1] + "…"


# --------------------------------------------------------------------------------------------- readers

def render_text(d: dict) -> str:
    return d["line"]


def render_html(d: dict) -> str:
    """The card's block: the stage strip (done / current / still to come), the line, who is working, the
    price so far. Every word is in the dict already; this only draws it (the HTML never computes)."""
    import html
    esc = lambda value: html.escape(str(value), quote=True)
    colors = {"done": "#2dd4a0", "current": "#2297F6", "next": "#98A2B3"}
    chips = "".join(
        f"<span class='pchip' data-state='{c['state']}' title='{esc(c['name'])}' style='display:inline-block;"
        f"margin:0 3px 3px 0;padding:1px 6px;border-radius:8px;font-size:11px;color:#fff;"
        f"background:{colors.get(c['state'], '#98A2B3')}'>{esc(c['id'])}</span>" for c in d.get("strip") or [])
    parts = d.get("parts") or {}
    rows = [f"<div class='pline' style='font-size:12px'>{esc(d['line'])}</div>"]
    if parts.get("activity"):
        rows.append(f"<div class='pnow' style='font-size:11px'>{esc(parts['activity'])}</div>")
    rows.append(f"<div class='pcost' style='font-size:11px'>{esc(parts.get('spend') or '')}</div>")
    return (f"<div class='progress' data-task='{esc(d['task'])}' style='margin-top:6px;text-align:left'>"
            f"<div class='pstrip'>{chips}</div>{''.join(rows)}</div>")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task-root", required=True, help="qa-factory/artifacts/<TASK>")
    ap.add_argument("--json", action="store_true", help="print the whole answer as JSON instead of the line")
    ns = hooklib.exact_options(ap).parse_args()
    # The story first (CX1-18): a phantom root is refused with the driver's text; `progress`'s own refusal below
    # stays for what the driver cannot see (a folder that is a story by name but holds nothing to read).
    task_root = hooklib.story_cli("story_progress.py", root=ns.task_root, key_flag=None)
    try:
        answer = progress(task_root)
    except StoryProgressError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(answer, indent=2, ensure_ascii=False) if ns.json else render_text(answer))
    return 0


if __name__ == "__main__":
    sys.exit(main())
