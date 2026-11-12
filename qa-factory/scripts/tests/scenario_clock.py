"""The per-scenario clock of the package's test files (TD-11 D0): a MEASURER, not a test, and not shipped logic.

  python -B scripts/tests/scenario_clock.py run --sink <dir> [--builders a,b,...] <test file> [<test file> ...]
      runs each test file under `clock_sitecustomize/sitecustomize.py` (put on PYTHONPATH) and writes
      <dir>/<file stem>.jsonl (the hook, the only writer of that file) and <dir>/<file stem>.stdout.txt (the full stdout).
      The exit code is 1 when any test file failed; every named file runs either way. The builder names reach the hook
      through the environment; the hook times each call of those functions directly (a `build` row).
  python -B scripts/tests/scenario_clock.py report --sink <dir> [--builders a,b,...] [--runners x,y,...]
      reads the sink (the only reader) and prints one table per file: per scenario the wall seconds, the checks, the child
      seconds by script, the scratch directories (`tempdir` events: never builds), and - only when builders are named - the
      builds and the builder seconds (measured), with the child seconds that happened INSIDE a build flagged. Without
      `--builders` those columns say `not measured`, never 0.

How a second is attributed: the WALL seconds go by event END time; the gap from the previous event's end to this event's end
belongs to this event's scenario. The BUILDER seconds are not derived from those gaps: they are the `build` rows' own
seconds. The scenario of an event is the outermost function name of its scope that is not a runner name. An event with no
scenario, and the tail after the last event, go to the `unattributed` bucket WITH their seconds - never dropped, never 0.
Builder names and runner names are DATA of the command line; none is written here as a builder. Seconds are printed, never
asserted (FR-31). A report is refused, never printed from half a sink.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOOK_DIR = HERE / "clock_sitecustomize"
SINK_VAR = "QA_SCENARIO_CLOCK_SINK"
SHA_VAR = "QA_SCENARIO_CLOCK_SHA"
PARENT_VAR = "QA_SCENARIO_CLOCK_PARENT"
BUILDERS_VAR = "QA_SCENARIO_CLOCK_BUILDERS"
UNATTRIBUTED = "unattributed"
NOT_MEASURED = "not measured"
# runner frames are skipped when a scenario is named; `_contained` is scenario_world's containment frame
DEFAULT_RUNNERS = ("<module>", "main", "run_scenarios", "run", "scenario", "_contained")

REQUIRED = {
    "file": ("file", "start", "end", "exit", "python", "sha"),
    "check": ("t", "name", "ok", "scope"),
    "child": ("t", "seconds", "script", "scope"),
    "tempdir": ("t", "name", "scope"),
    "build": ("t", "seconds", "name", "scope", "nested"),
    "clock_error": ("error",),
}


class ClockSinkError(ValueError):
    """A sink the reader will not print a table from (missing `file` row, broken line, nothing recorded)."""


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def read_sink(sink) -> list:
    """The rows of every `*.jsonl` of the sink, grouped per test file: [{"name", "file", "events", "errors"}].
    Raises ClockSinkError naming the sink on an empty directory, a broken line, or a file with no / two `file` rows."""
    sink = Path(sink)
    if not sink.is_dir():
        raise ClockSinkError(f"sink {sink}: not a directory (nothing was recorded)")
    paths = sorted(sink.glob("*.jsonl"))
    if not paths:
        raise ClockSinkError(f"sink {sink}: no *.jsonl file (nothing was recorded)")
    files = []
    for path in paths:
        file_rows, events, errors = [], [], []
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError as exc:
                raise ClockSinkError(f"sink {sink}: {path.name} line {number} is not JSON ({exc})") from None
            kind = row.get("event") if isinstance(row, dict) else None
            if kind not in REQUIRED:
                raise ClockSinkError(f"sink {sink}: {path.name} line {number} is not a clock row (event {kind!r})")
            absent = [k for k in REQUIRED[kind] if k not in row]
            if absent:
                raise ClockSinkError(f"sink {sink}: {path.name} line {number} ({kind}) lacks {', '.join(absent)}")
            numeric = [k for k in ("t", "seconds", "start", "end") if k in row and not _number(row[k])]
            if numeric:
                raise ClockSinkError(f"sink {sink}: {path.name} line {number} ({kind}) has a non-number {numeric[0]}")
            if "scope" in row and not isinstance(row["scope"], list):
                raise ClockSinkError(f"sink {sink}: {path.name} line {number} ({kind}) has a scope that is not a list")
            {"file": file_rows, "clock_error": errors}.get(kind, events).append(row)
        if not file_rows:
            raise ClockSinkError(f"sink {sink}: {path.name} has no `file` row (the process ended before the clock wrote "
                                 "it, or the sink was cut); no table is printed from half a sink")
        if len(file_rows) > 1:
            raise ClockSinkError(f"sink {sink}: {path.name} has {len(file_rows)} `file` rows (two processes wrote it)")
        files.append({"name": path.stem, "file": file_rows[0], "events": events, "errors": errors})
    return files


def _end(event) -> float:
    return event["t"] + event["seconds"] if event["event"] in ("child", "build") else event["t"]


def _bucket(name, measured) -> dict:
    """`builds`, `builder_s` and `child_in_build_s` are None (not measured) when no builder was named: never 0 (AR-28)."""
    return {"name": name, "wall": 0.0, "checks": 0, "fails": 0, "child_s": {}, "children": 0, "tempdirs": 0,
            "builds": 0 if measured else None, "builder_s": 0.0 if measured else None,
            "child_in_build_s": 0.0 if measured else None}


def derive(entry: dict, builders=(), runners=DEFAULT_RUNNERS) -> dict:
    """Per file: the scenarios in first-seen order, the unattributed bucket, the totals. `builds` counts the `build` rows
    (the outermost call of a named builder) and `builder_s` sums their own seconds; a `tempdir` row is only a tempdir."""
    row = entry["file"]
    builders, runners = set(builders), set(runners)
    measured = bool(builders)
    scenarios, order = {}, []
    unattributed = _bucket(UNATTRIBUTED, measured)
    cursor = row["start"]
    events = [e for e in entry["events"] if e["event"] != "build" or (measured and e["name"] in builders
                                                                      and not e["nested"])]
    for event in sorted(events, key=_end):
        name = next((n for n in event["scope"] if n not in runners), None)
        if name is None:
            bucket = unattributed
        else:
            if name not in scenarios:
                scenarios[name] = _bucket(name, measured)
                order.append(name)
            bucket = scenarios[name]
        end = _end(event)
        gap = max(0.0, end - cursor)
        cursor = max(cursor, end)
        bucket["wall"] += gap
        if event["event"] == "check":
            bucket["checks"] += 1
            bucket["fails"] += 0 if event["ok"] else 1
        elif event["event"] == "child":
            bucket["children"] += 1
            bucket["child_s"][event["script"]] = bucket["child_s"].get(event["script"], 0.0) + event["seconds"]
            if measured and builders & set(event["scope"]):      # inside a build: part of builder_s, flagged
                bucket["child_in_build_s"] += event["seconds"]
        elif event["event"] == "tempdir":
            bucket["tempdirs"] += 1
        else:                                                    # a `build` row: its own measured seconds
            bucket["builds"] += 1
            bucket["builder_s"] += event["seconds"]
    unattributed["wall"] += max(0.0, row["end"] - cursor)        # the tail after the last event
    notes = [e["error"] for e in entry["errors"]]
    if measured and not any(e["event"] == "build" and e["name"] in builders for e in entry["events"]):
        notes.append("builders were named but the sink holds no build row for them (not called, or not timed)")
    return {"name": entry["name"], "file": row, "wall": row["end"] - row["start"], "measured": measured,
            "scenarios": [scenarios[n] for n in order], "unattributed": unattributed, "clock_errors": notes}


def _by_script(child_s: dict) -> str:
    return ", ".join(f"{k}={v:.2f}" for k, v in sorted(child_s.items())) or "-"


def _cell(value, width, spec) -> str:
    return f"{NOT_MEASURED:>{width}}" if value is None else f"{value:>{width}{spec}}"


def render(derived: list) -> str:
    out = []
    for d in derived:
        row, scen, un = d["file"], d["scenarios"], d["unattributed"]
        every = scen + [un]
        child_all = sum(sum(b["child_s"].values()) for b in every)
        if d["measured"]:
            builder_s = sum(b["builder_s"] for b in every)
            inside = sum(b["child_in_build_s"] for b in every)
            split = (f"builds {sum(b['builds'] for b in every)}  builder_s {builder_s:.2f}  "
                     f"children outside builders {child_all - inside:.2f}s  (children inside builders {inside:.2f}s are "
                     f"part of builder_s, not added again)  rest {d['wall'] - builder_s - (child_all - inside):.2f}s")
        else:
            split = f"builds {NOT_MEASURED}  builder_s {NOT_MEASURED}  children {child_all:.2f}s"
        seen = "" if row.get("exit_seen", True) else " (exit code not seen by the clock: trust the process exit code)"
        out.append(f"== {row['file']}  exit {row['exit']}{seen}  wall {d['wall']:.2f}s  python {row['python']}  "
                   f"sha {str(row['sha'])[:12]}  scenarios: {len(scen)}  checks {sum(b['checks'] for b in every)}  "
                   f"children {sum(b['children'] for b in every)}  tempdirs {sum(b['tempdirs'] for b in every)}")
        out.append(f"   {split}")
        for message in d["clock_errors"]:
            out.append(f"   CLOCK ERROR (numbers below may be partial): {message}")
        out.append(f"   {'scenario':<44} {'wall_s':>8} {'checks':>6} {'fail':>4} {'children':>8} {'child_s':>8} "
                   f"{'in_build_s':>12} {'tempdirs':>8} {'builds':>12} {'builder_s':>12}  child seconds by script")
        for b in scen + ([un] if un["wall"] > 0 or un["checks"] or un["children"] or un["tempdirs"] or un["builds"]
                         else []):
            out.append(f"   {b['name'][:44]:<44} {b['wall']:>8.2f} {b['checks']:>6} {b['fails']:>4} {b['children']:>8} "
                       f"{sum(b['child_s'].values()):>8.2f} {_cell(b['child_in_build_s'], 12, '.2f')} {b['tempdirs']:>8} "
                       f"{_cell(b['builds'], 12, 'd')} {_cell(b['builder_s'], 12, '.2f')}  {_by_script(b['child_s'])}")
    return "\n".join(out)


def report_text(sink, builders=(), runners=DEFAULT_RUNNERS) -> str:
    return render([derive(entry, builders, runners) for entry in read_sink(sink)])


def _git_sha() -> str:
    try:
        done = subprocess.run(["git", "-C", str(HERE), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30)
        return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else "unknown"
    except Exception:
        return "unknown"


def _say(text: str = "") -> None:
    print(text, flush=True)                                      # a log read while it runs is line-buffered (FR-43)


def cmd_run(sink: Path, files: list, builders=()) -> int:
    sink.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(HOOK_DIR) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env[SINK_VAR] = str(sink)
    env[SHA_VAR] = _git_sha()
    env[PARENT_VAR] = str(os.getpid())                           # the hook records only the process started from here
    env["PYTHONUNBUFFERED"] = "1"
    if builders:
        env[BUILDERS_VAR] = ",".join(builders)
    else:
        env.pop(BUILDERS_VAR, None)
    worst = 0
    for name in files:
        path = Path(name).resolve()
        for stale in (sink / f"{path.stem}.jsonl", sink / f"{path.stem}.stdout.txt"):
            stale.unlink(missing_ok=True)                        # one run, one sink file: a rerun never appends
        _say(f"--- scenario_clock run: {path.name}")
        with open(sink / f"{path.stem}.stdout.txt", "w", encoding="utf-8", newline="\n") as log:
            proc = subprocess.Popen([sys.executable, "-B", str(path)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    env=env, text=True, encoding="utf-8", errors="replace")
            for line in proc.stdout:
                log.write(line)
                log.flush()
                sys.stdout.write(line)
                sys.stdout.flush()
            code = proc.wait()
        recorded = None
        try:
            recorded = next(e["file"]["exit"] for e in read_sink(sink) if e["name"] == path.stem)
        except Exception:
            pass
        note = "" if recorded in (None, code) else f" (the clock recorded exit {recorded}: trust the process exit code)"
        _say(f"--- {path.name}: exit {code}{note}")
        worst = worst or (1 if code else 0)
    return worst


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run test files under the clock")
    run.add_argument("--sink", required=True)
    run.add_argument("--builders", default="", help="comma-separated builder function names to time directly")
    run.add_argument("files", nargs="+")
    rep = sub.add_parser("report", help="print the per-scenario table of a sink")
    rep.add_argument("--sink", required=True)
    rep.add_argument("--builders", default="", help="comma-separated builder function names")
    rep.add_argument("--runners", default=",".join(DEFAULT_RUNNERS), help="comma-separated runner function names")
    args = parser.parse_args(argv)
    split = lambda text: [x.strip() for x in text.split(",") if x.strip()]  # noqa: E731
    if args.command == "run":
        return cmd_run(Path(args.sink), args.files, split(args.builders))
    try:
        _say(report_text(args.sink, split(args.builders), split(args.runners)))
    except ClockSinkError as exc:
        print(f"scenario_clock report refused: {exc}", file=sys.stderr, flush=True)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
