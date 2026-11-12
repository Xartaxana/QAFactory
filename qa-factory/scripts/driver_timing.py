#!/usr/bin/env python3
"""driver_timing.py - where the time between two role calls goes (t-1937 P2-1, P2-4).

    python driver_timing.py --task <KEY> | --task-root <the story's folder> [--json] [--check-hop-s N]

The driver times its own steps between one role's result and the next launch (`story_run.Driver.timed`) and writes ONE JSON line per step
to `state/driver-timings.jsonl`: `{ts, stage, dispatch, step, seconds}` plus `error: <exception type>` when the step raised (the timer is
a context manager that writes in `__exit__`, so a failed step's time is not lost). `ts` is the END of the step (whole seconds, UTC, the
driver's `_now()`); `seconds` is `time.monotonic`. A step `start.<part>` is a part of the `start` step, reported by `story_step.py start`
as `timing: <name> <seconds>` lines (the driver parses them; nobody prints them raw): it is listed and totalled, never added to the hop a
second time.

This script only reads. A HOP is the span from a call's result row (`state/driver-runs.jsonl`, a row with an `exit_code`) to the next
`launched` row. Per hop it prints the wall, the sum of the timed top-level steps that started and ended inside it, the UNATTRIBUTED
remainder (named, never dropped), and the steps; then per-step totals. A step that straddles a launch (the `handoff` that resumes a
role) belongs to no hop and is listed by name. `--check-hop-s N` exits 1 listing the hops over N seconds - advice for the reader of a
run, never a gate of the factory (non-goal of t-1937). No carrier file: `no timings recorded for <task>`, exit 0; an absent carrier is
never "0 s of overhead" (FR-41). A line that does not parse is counted and named, never dropped silently (FR-28).

The watchdog of a silent role session (P2-4) lives here too: `Silence` (the pure episode logic) and `watch` (the loop one thread runs
while `Driver.launch` waits). It tells, once per silence episode, and never kills.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

CARRIER = "driver-timings.jsonl"
NOTE_OVER_S = 20.0                  # the console says "note: <step> took N s" only over this
HOP_TARGET_S = 20.0                 # the advised median hop (spec t-1937 P2-3); `--check-hop-s` default is none
SLACK_S = 1.0                       # `ts` has whole seconds: a step belongs to a hop within this slack of its edges
WALL_NOTE_OVER_MS = 120000          # P2-4: the CLI's own duration trails the wall clock by more than this -> one note
POLL_S = 60.0                       # P2-4: how often the watchdog asks


# --- the writer side -----------------------------------------------------------------------------------
class Timer:
    """`with Timer(write, step, dispatch, stage) as t:` - times the block with `time.monotonic` and calls
    `write(step, seconds, dispatch=, stage=, error=)` when it ends by ANY road. `t.dispatch` may be set inside the block (a `start`
    knows its dispatch only once it has answered). The block's exception is never swallowed."""

    def __init__(self, write, step: str, dispatch: str = "", stage: str = ""):
        self.write, self.step, self.dispatch, self.stage = write, step, dispatch, stage
        self.began = 0.0

    def __enter__(self):
        self.began = time.monotonic()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.write(self.step, time.monotonic() - self.began, dispatch=self.dispatch, stage=self.stage,
                   error=exc_type.__name__ if exc_type is not None else "")
        return False


def row(ts: str, stage: str, dispatch: str, step: str, seconds: float, error: str = "") -> dict:
    out = {"ts": ts, "stage": stage, "dispatch": dispatch, "step": step, "seconds": round(float(seconds), 2)}
    if error:
        out["error"] = error
    return out


class Laps:
    """The sub-steps of one command (`story_step.py start`): `with laps.lap("start.pre_work"):` then `laps.lines()`."""

    def __init__(self):
        self.rows: list = []

    def lap(self, name: str):
        return Timer(lambda step, seconds, **_: self.rows.append((step, seconds)), name)

    def lines(self) -> list:
        return [f"timing: {name} {seconds:.2f}" for name, seconds in self.rows]


def parse_lines(text: str) -> list:
    """`[(name, seconds)]` from the `timing: <name> <seconds>` lines of a command's output; any other line is not one."""
    found = []
    for line in str(text or "").splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "timing:":
            try:
                found.append((parts[1], float(parts[2])))
            except ValueError:
                continue
    return found


# --- P2-4: the wall-clock note and the silence watchdog -------------------------------------------------
def _clock(ms) -> str:
    seconds = int(round(ms / 1000))
    return f"{seconds // 60}m{seconds % 60:02d}s"


def wall_note(label: str, wall_ms, duration_ms) -> str:
    """The one console line of a call whose wall clock exceeds the CLI's own `duration_ms` by more than 120 s, else ''.
    A number that is not a plain number (absent, bool, text) says nothing: an unknown is no difference (FR-41)."""
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in (wall_ms, duration_ms)):
        return ""
    if wall_ms - duration_ms <= WALL_NOTE_OVER_MS:
        return ""
    return (f"note: {label} took {_clock(wall_ms)} of wall clock, the CLI reports {_clock(duration_ms)}: its own count covers only "
            "the last turn (a background task re-entered it)")


class Silence:
    """The episode logic of the watchdog, pure. `check(last_at, now)` returns the progress line the FIRST time the transcript has been
    silent over `threshold_s`, and '' while the same episode goes on; a write after it ends the episode (the next silence is a new one).
    `last_at` None is an unknown: nothing is said and the episode state is kept."""

    def __init__(self, dispatch: str, threshold_s: float):
        self.dispatch, self.threshold_s, self.told = dispatch, float(threshold_s), False

    def check(self, last_at, now: float) -> str:
        if isinstance(last_at, bool) or not isinstance(last_at, (int, float)):
            return ""
        idle = now - float(last_at)
        if idle <= self.threshold_s:
            self.told = False
            return ""
        if self.told:
            return ""
        self.told = True
        return (f"[progress] {self.dispatch} has written nothing for {int(idle // 60)} min "
                f"(last at {datetime.fromtimestamp(float(last_at)).strftime('%H:%M')})")


def console(line: str) -> None:
    """One console line through the process's ORIGINAL stdout (`sys.__stdout__`), not `sys.stdout`: the driver redirects `sys.stdout`
    process-wide while a deferred question is built (`redirect_stdout`), and a line printed by the watchdog thread then lands in
    that buffer and is lost (t-2034 M2). No stream, or a stream that cannot be written: nothing, never an exception."""
    try:
        stream = sys.__stdout__
        if stream is None:
            return
        stream.write(line + "\n")
        stream.flush()
    except (OSError, ValueError):
        return


def last_write(project_root, dispatch: str, since: float = 0.0, memo=None):
    """Epoch of the newest write to the transcript of `dispatch`: the session whose first user message names `Dispatch: <id>`
    (`hooklib.subagent_meta`), found among `dispatch_liveness.session_transcripts(since)`. The path found is kept in `memo` (a dict the caller holds), so a
    later poll only stats it. None = an unknown (no cost file yet, no transcript names the dispatch, anything unreadable). Never raises."""
    memo = memo if memo is not None else {}
    try:
        path = memo.get("path")
        if path is None:
            import hooklib
            import dispatch_liveness
            for candidate in dispatch_liveness.session_transcripts(project_root, since):
                if str(hooklib.subagent_meta(candidate).get("dispatch_id") or "") == dispatch:
                    path = memo["path"] = candidate
                    break
            if path is None:
                return None
        return Path(path).stat().st_mtime
    except Exception:  # noqa: BLE001 - a courtesy line: whatever goes wrong here is not the run's problem
        return None


def threshold_s(project_root) -> float:
    """`dispatch.abandoned_after_s` of the project's config (default 600): the same number `dispatch_liveness` judges abandonment by."""
    try:
        import dispatch_liveness
        return float(dispatch_liveness.thresholds(project_root)["abandoned_after_s"])
    except Exception:  # noqa: BLE001
        return 600.0


def watch(project_root, dispatch: str, stop, say=None) -> None:
    """Run in ONE thread while a role's process is waited for: every `POLL_S` ask `last_write`, and `say` the silence line once per
    episode. Ends when `stop` (a `threading.Event`) is set - the caller sets it when the call returns, by any road. It kills nothing and
    raises nothing: a role that is working is never stopped by the driver."""
    say = say or console
    silence = Silence(dispatch, threshold_s(project_root))
    since, memo = time.time() - 5.0, {}
    try:
        while not stop.wait(POLL_S):
            line = silence.check(last_write(project_root, dispatch, since, memo), time.time())
            if line:
                say(line)
    except Exception:  # noqa: BLE001
        return


# --- the reader side -----------------------------------------------------------------------------------
def _epoch(value):
    try:
        moment = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return (moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment).timestamp()


def _rows(path, what, problems) -> list:
    """The object lines of a jsonl file. A line that is not a JSON object is counted in `problems` with its number."""
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()   # a torn multi-byte tail is one bad line, not a traceback
    except OSError:
        return []
    out = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except ValueError:
            item = None
        if isinstance(item, dict):
            out.append(item)
        else:
            problems.append(f"{what} line {number} is not a JSON object and was left out")
    return out


def _seconds(item):
    value = item.get("seconds")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None


def _hops(runs: list) -> list:
    """`[(from_epoch, to_epoch, ended dispatch, launched dispatch)]`: a call's result row to the next `launched` row, in file order."""
    hops, ended = [], None
    for item in runs:
        when = _epoch(item.get("ts"))
        if item.get("kind") == "launched":
            if ended is not None and when is not None and when >= ended[0]:
                hops.append((ended[0], when, ended[1], str(item.get("dispatch_id") or "")))
            ended = None
        elif item.get("exit_code") is not None and when is not None:
            ended = (when, str(item.get("dispatch") or item.get("kind") or ""))
    return hops


def report(task_root, check_hop_s=None) -> dict:
    task_root = Path(task_root).resolve()
    problems: list = []
    carrier = task_root / "state" / CARRIER
    timings = _rows(carrier, f"state/{CARRIER}", problems)
    usable = []
    for item in timings:
        end, seconds = _epoch(item.get("ts")), _seconds(item)
        if end is None or seconds is None or not isinstance(item.get("step"), str):
            problems.append(f"state/{CARRIER}: a line with step {item.get('step')!r} has no usable ts or seconds and was left out")
        else:
            usable.append((end, seconds, item))
    if not usable:
        return {"task": task_root.name, "timed": False, "text": f"no timings recorded for {task_root.name}", "problems": problems}
    runs = _rows(task_root / "state" / "driver-runs.jsonl", "state/driver-runs.jsonl", problems)
    hops, straddling, taken = [], [], set()
    spans = _hops(runs)
    for start, end, ended, launched in spans:
        steps, subs = {}, {}
        for index, (stop, seconds, item) in enumerate(usable):
            if start - SLACK_S <= stop - seconds and stop <= end + SLACK_S:
                taken.add(index)
                bucket = subs if "." in item["step"] else steps
                bucket[item["step"]] = round(bucket.get(item["step"], 0.0) + seconds, 2)
        wall = round(end - start, 2)
        attributed = round(sum(steps.values()), 2)
        hop = {"after": ended, "before": launched, "from": _stamp(start), "to": _stamp(end), "wall_s": wall,
               "attributed_s": attributed, "unattributed_s": round(max(0.0, wall - attributed), 2), "steps": steps, "sub_steps": subs}
        if attributed > wall:
            hop["over_attributed_s"] = round(attributed - wall, 2)      # whole-second timestamps: named, not hidden
        hops.append(hop)
    for index, (stop, seconds, item) in enumerate(usable):
        if index not in taken and any(s < stop - seconds < e or s < stop < e for s, e, _a, _b in spans):
            straddling.append(f"{item['step']} ({item.get('dispatch') or '-'}, {seconds} s)")
    totals: dict = {}
    for _stop, seconds, item in usable:
        entry = totals.setdefault(item["step"], {"n": 0, "seconds": 0.0, "errors": 0})
        entry["n"] += 1
        entry["seconds"] = round(entry["seconds"] + seconds, 2)
        entry["errors"] += 1 if item.get("error") else 0
    data = {"task": task_root.name, "timed": True, "hops": hops, "step_totals": totals,
            "straddling_a_launch": straddling, "problems": problems}
    if check_hop_s is not None:
        data["check_hop_s"] = check_hop_s
        data["over"] = [h for h in hops if h["wall_s"] > check_hop_s]
    return data


def _stamp(epoch) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


def render(data) -> str:
    if not data["timed"]:
        return data["text"] + "".join(f"\nnote: {p}" for p in data["problems"])
    lines = [f"driver timing of {data['task']}: {len(data['hops'])} hop(s)"]
    for hop in data["hops"]:
        lines.append(f"- {hop['after']} -> {hop['before']}: wall {hop['wall_s']} s = steps {hop['attributed_s']} s + unattributed "
                     f"{hop['unattributed_s']} s" + (f" (steps exceed the wall by {hop['over_attributed_s']} s: timestamps are whole seconds)"
                                                       if "over_attributed_s" in hop else ""))
        for name, seconds in sorted({**hop["steps"], **hop["sub_steps"]}.items(), key=lambda kv: -kv[1]):
            lines.append(f"    {name}: {seconds} s" + ("  (part of start)" if name in hop["sub_steps"] else ""))
    lines.append("per step: " + "; ".join(f"{n} x{t['n']} {t['seconds']} s" + (f" ({t['errors']} raised)" if t["errors"] else "")
                                           for n, t in sorted(data["step_totals"].items(), key=lambda kv: -kv[1]["seconds"])))
    if data["straddling_a_launch"]:
        lines.append("steps that straddle a launch (in no hop): " + "; ".join(data["straddling_a_launch"]))
    if "over" in data:
        lines.append(f"hops over {data['check_hop_s']} s: " + ("; ".join(f"{h['after']} -> {h['before']} {h['wall_s']} s" for h in data["over"])
                                                                or "none"))
    lines += [f"note: {p}" for p in data["problems"]]
    return "\n".join(lines)


def cli_main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--task", help="the story's key (the name of its folder under the artifact root)")
    parser.add_argument("--task-root", help="the story's folder, qa-factory/artifacts/<KEY>")
    parser.add_argument("--json", action="store_true", help="the whole answer as JSON")
    parser.add_argument("--check-hop-s", type=float, default=None, help="exit 1 listing the hops whose wall is over N seconds (advice, not a gate)")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import hooklib
    args = hooklib.exact_options(parser).parse_args(argv)
    task_root = hooklib.story_cli("driver_timing.py", key=args.task, root=args.task_root)
    data = report(task_root, args.check_hop_s)
    print(json.dumps(data, indent=2, ensure_ascii=False) if args.json else render(data))
    return 1 if data.get("over") else 0


if __name__ == "__main__":
    sys.exit(cli_main())
