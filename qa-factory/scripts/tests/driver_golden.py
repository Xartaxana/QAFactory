"""The driver golden (t-301 N0): record, compare, stability and probe over the story-runner tests.

    python -B scripts/tests/driver_golden.py --golden-dir <dir> record [--coverage] [--package DIR] [--jobs N]
    python -B scripts/tests/driver_golden.py --golden-dir <dir> record --only FILE[,FILE...]    # a SLICE of the record
    python -B scripts/tests/driver_golden.py --golden-dir <dir> compare [--only FILE[::SCENARIO][,FILE...]]
    python -B scripts/tests/driver_golden.py --golden-dir <dir> stability [--only FILE[::SCENARIO][,FILE...]]
    python -B scripts/tests/driver_golden.py --golden-dir <dir> probe reorder-resume-with

A full record is minutes to an hour on a loaded machine; the slices (`record --only a.py,b.py`, repeated until every file
is in) join ONE golden, which must come from one package state - record from a frozen copy (`--package <copy>`) while other
work edits the tree. A golden that lacks a test file is incomplete: compare refuses it, naming the file.

(`--record`, `--compare`, `--stability`, `--probe NAME` are the same modes as flags.)

What it does: runs each test file of the story-runner rig (the 12 `test_story_run_*.py` that use `run_scenarios`, plus the
files of `driver-golden-rules.json` `files.outside`, each one unit `_main`) as `python -B <file>` with the recorder
(`golden_sitecustomize`) on PYTHONPATH, so that every process of the test records one ORDERED TRACE per scenario (see
`driver_trace.py`). `record` saves the traces under `--golden-dir`, which lives OUTSIDE the package (the release copy must
not ship it); `compare` records again and requires every trace to be line-for-line the saved one.

Exit codes. 0: recorded, or every compared scenario is equal, or the probe detected the mutation. 1: at least one scenario
differs (or a scenario is red), or the probe did NOT detect the mutation. 2: refused with no verdict on equality: no golden,
a different package (K14), a different Python minor version, the recorder did not load, a red scenario during record, a cap
exceeded, a timeout, a bad argument. Only 0 means "equal"; a refusal is never a pass, and an excluded scenario is printed by
name and counted, never counted as equal.
"""

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import driver_trace as T  # noqa: E402

MODES = ("record", "compare", "stability", "probe")
PROBES = ("reorder-resume-with",)
SCHEMA = 1


class Refusal(Exception):
    """Exit 2: no verdict. The text says what is wrong, what was expected, and the door (FR-1)."""


def say(text: str = "") -> None:
    print(text, flush=True)                                  # FR-43: a run of minutes is read while it runs


# --- the package and its files ------------------------------------------------------------------------------
def package_root(args) -> Path:
    root = Path(args.package).resolve() if args.package else HERE.parents[1]
    if not (root / "scripts" / "story_run.py").is_file():
        raise Refusal(f"--package {root} has no scripts/story_run.py: expected the root of a qa-factory package "
                      f"(the directory that holds scripts/ and references/).")
    return root


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package_hashes(root: Path) -> dict:
    """{relative path: sha256} of every file of the package (K14). Bytecode caches and .git are not content."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(str(root)):
        dirnames[:] = sorted(d for d in dirnames if d not in ("__pycache__", ".git"))
        for name in sorted(filenames):
            if name.endswith(".pyc") or name == ".package-commit":       # the frozen copy's marker is not package content
                continue
            path = Path(dirpath) / name
            out[path.relative_to(root).as_posix()] = sha_file(path)
    return out


def package_paths(root: Path, skip: Path | None = None) -> set:
    """Every path (files, directories, caches too) under the package: the litter detector's picture (K15)."""
    out = set()
    for dirpath, dirnames, filenames in os.walk(str(root)):
        if ".git" in dirnames:
            dirnames.remove(".git")
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            if skip is not None and (path == skip or skip in path.parents):
                continue
            out.add(path.relative_to(root).as_posix())
    return out


def layer_map(root: Path) -> dict:
    path = root / "scripts" / "tests" / "fixtures" / "driver-layers.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def driver_modules(root: Path) -> list:
    """The module stems whose `print` the golden records (Q3): the map's modules, else `story_run` alone."""
    stems = []
    for layer in layer_map(root).get("layers", []):
        stems.extend(layer)
    return stems or ["story_run"]


def allowed_patterns(root: Path, rules: dict) -> list:
    patterns = list(rules.get("provenance_allowed", []))
    for layer in layer_map(root).get("layers", []):               # the driver set: the map's own modules
        patterns.extend(f"scripts/{module}.py" for module in layer)
    for row in layer_map(root).get("source_readers", []):
        patterns.append("scripts/tests/" + row["file"])
    return patterns


def changed_files(recorded: dict, now: dict) -> list:
    return sorted(k for k in set(recorded) | set(now) if recorded.get(k) != now.get(k))


def provenance(root: Path, manifest: dict, rules: dict) -> tuple:
    """(refusing files, allowed changed files) between the MANIFEST's hash set and the package now (K14)."""
    changed = changed_files(manifest.get("package_files", {}), package_hashes(root))
    patterns = allowed_patterns(root, rules)
    refusing = [c for c in changed if not any(fnmatch.fnmatch(c, p) for p in patterns)]
    return refusing, [c for c in changed if c not in refusing]


RULES_REL = "scripts/tests/fixtures/driver-golden-rules.json"
RECORDER_FILES = ("scripts/tests/driver_trace.py", "scripts/tests/driver_golden.py",
                  "scripts/tests/golden_sitecustomize/sitecustomize.py", "scripts/tests/story_run_common.py")


def rules_in_effect() -> Path:
    """The rules file the run actually uses: `--rules` (put in the environment by main) or the tool's own."""
    return Path(os.environ.get(T.ENV_RULES) or T.RULES_PATH)


def recorder_hash(root: Path) -> str:
    """One hash over what decides the SHAPE of a trace: the recorder, the CLI (it shapes the test process's environment), the
    hook installer, the rig's tagging and the RULES IN EFFECT (the bytes of the file used, not of the package's copy: a `--rules`
    file is part of the recorder). The tests and the layer map are 'the golden's own files' that may change without making a
    golden stale; these may not - a changed row or a changed recorder makes every stored trace a trace of another kind."""
    digest = hashlib.sha256()
    for rel in RECORDER_FILES:
        path = root / rel
        digest.update(rel.encode("ascii") + b"\0" + (path.read_bytes() if path.is_file() else b"") + b"\0")
    rules = rules_in_effect()
    digest.update(b"rules\0" + (rules.read_bytes() if rules.is_file() else b"") + b"\0")
    return digest.hexdigest()


def check_recorder(root: Path, manifest: dict) -> None:
    if manifest.get("recorder_sha256") != recorder_hash(root):
        raise Refusal("the recorder or its normalisation rows changed since this golden was recorded (driver_trace.py, "
                      "driver_golden.py, golden_sitecustomize/sitecustomize.py, story_run_common.py or the rules file in "
                      "effect differ from the MANIFEST's recorder_sha256): every stored trace is of another shape than one "
                      "recorded now. Expected the same recorder; re-record the golden.")


def check_rules_file(root: Path) -> None:
    """F5: a `--rules` file whose bytes differ from the package's own rules file is refused - K14 and the recorder hash cover
    the file in effect, and the package's copy is the one a reviewer reads."""
    own = root / RULES_REL
    used = rules_in_effect()
    if own.is_file() and used.is_file() and own.read_bytes() != used.read_bytes():
        raise Refusal(f"--rules {used} differs from the package's own {own}: the rules in effect must be the package's. "
                      f"Expected the package's file (drop --rules), or change the package's file and re-record.")


def package_commit(root: Path) -> str:
    """The commit the package state stands for: the `.package-commit` marker of a frozen copy (freeze_package.sh writes it), else
    `git rev-parse HEAD` of the work tree that holds the package (uncommitted edits are NOT in it: K14 sees them), else ''."""
    marker = root / ".package-commit"
    if marker.is_file():
        return marker.read_text(encoding="ascii", errors="replace").strip()
    try:
        done = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def same_root(a, b) -> bool:
    return os.path.normcase(os.path.realpath(str(a))) == os.path.normcase(os.path.realpath(str(b)))


def check_root(root: Path, manifest: dict) -> None:
    """F2: a golden is the trace of ONE package directory: values derived from the length of text that holds a path make the
    same bytes in another directory a different trace. Refused from another root, naming both and the door."""
    recorded = manifest.get("package_root")
    if recorded and not same_root(recorded, root):
        raise Refusal(f"the golden was recorded in the package root {recorded} (commit {manifest.get('package_commit') or 'unknown'}), "
                      f"this run is in {root} (commit {package_commit(root) or 'unknown'}): the same bytes in another directory "
                      f"are another trace. Expected the same root: re-record here, or freeze the package at {recorded} "
                      f"(experiments/driver-golden/freeze_package.sh).")


def discover(root: Path, rules: dict) -> dict:
    """{test file name: {"kind": "rig"|"outside", "side": [...], "inproc": [...], "default": tag}} - the units the golden
    records, found by reading each file's `run_scenarios(...)` call with `ast` (a count printed later must equal it)."""
    tests = root / "scripts" / "tests"
    found = {}
    outside = list(rules["files"]["outside"])
    rig = []
    for path in sorted(tests.glob(rules["files"]["rig_glob"])):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "run_scenarios"]
        if not calls:
            continue
        if len(calls) != 1 or len(calls[0].args) != 2:
            raise Refusal(f"{path.name}: expected exactly one run_scenarios(side_by_side, in_process) call, found "
                          f"{len(calls)}; the golden reads the scenario names from it.")
        lists = []
        for arg in calls[0].args:
            if not isinstance(arg, ast.List) or not all(isinstance(e, ast.Name) for e in arg.elts):
                raise Refusal(f"{path.name}: run_scenarios must be given two list literals of plain function names; "
                              f"found something else, so the scenario names cannot be discovered. Expected "
                              f"`run_scenarios([a, b], [c])`.")
            lists.append([e.id for e in arg.elts])
        names = lists[0] + lists[1]
        if len(set(names)) != len(names):
            raise Refusal(f"{path.name}: a scenario name appears twice in run_scenarios; a scenario is identified by "
                          f"(file, function name): rename one.")
        found[path.name] = {"kind": "rig", "side": lists[0], "inproc": lists[1], "default": "_outside"}
        rig.append(path.name)
    for name in outside:
        if not (tests / name).is_file():
            raise Refusal(f"rules files.outside names {name}, which is not in {tests}: fix driver-golden-rules.json.")
        found[name] = {"kind": "outside", "side": [], "inproc": [], "default": "_main"}
    return found


def scenarios_of(info: dict) -> list:
    return list(info["side"]) + list(info["inproc"]) if info["kind"] == "rig" else ["_main"]


def excluded_units(rules: dict) -> set:
    """{(test file, scenario)} named in rules `scenario_exclude` - each with its reason. An excluded unit is listed and
    counted in every summary and never counted as equal (E12); a file whose every unit is excluded is not run at all."""
    out = set()
    for entry in rules.get("scenario_exclude", []):
        if not (entry.get("file") and entry.get("scenario") and str(entry.get("reason") or "").strip()):
            raise Refusal(f"scenario_exclude row {entry!r} needs a file, a scenario and a reason: an exclusion with no reason is "
                          f"a silent omission. Fix driver-golden-rules.json.")
        out.add((entry["file"], entry["scenario"]))
    return out


def say_excluded(rules: dict) -> None:
    rows = rules.get("scenario_exclude", [])
    if rows:
        say(f"excluded (listed, never counted as equal): {len(rows)}")
        for entry in rows:
            say(f"  {entry['file']}::{entry['scenario']} - {entry['reason']}")


def parse_only(text, found: dict):
    """{file name: scenario or None} for `--only FILE[::SCENARIO][,FILE[::SCENARIO]...]` (a list of files is a SLICE: the
    record of a few files per call); an unknown or malformed value is a refusal."""
    if text is None:
        return None
    if not text.strip():
        raise Refusal("--only is empty: expected FILE or FILE::SCENARIO (several files separated by commas), for example "
                      "--only test_story_run_loop.py::some_scenario")
    out: dict = {}
    for part in text.split(","):
        name, sep, scenario = part.partition("::")
        if name not in found:
            raise Refusal(f"--only {part}: no such test file {name!r}. Known files: {', '.join(sorted(found))}")
        if sep and not scenario:
            raise Refusal(f"--only {part}: nothing after '::'. Expected FILE::SCENARIO; the scenarios of {name} are: "
                          f"{', '.join(scenarios_of(found[name]))}")
        if sep and scenario not in scenarios_of(found[name]):
            raise Refusal(f"--only {part}: {name} has no scenario {scenario!r}. Its scenarios are: "
                          f"{', '.join(scenarios_of(found[name]))}")
        if name in out:
            raise Refusal(f"--only names {name} twice: a file is in a slice once.")
        out[name] = scenario or None
    return out


# --- running one file -------------------------------------------------------------------------------------------
class FileRun:
    def __init__(self, name: str):
        self.name = name
        self.code = None
        self.seconds = 0.0
        self.finals: dict = {}
        self.problems: list = []
        self.red: list = []
        self.timing: dict = {}
        self.coverage: dict = {}
        self.untagged = 0


def kill_tree(proc) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.kill()


def run_file(root: Path, rules: dict, name: str, info: dict, sink: Path, modules: list, coverage: bool) -> FileRun:
    run = FileRun(name)
    sink.mkdir(parents=True, exist_ok=True)
    # rules `ambient_scrub`: variables the driver itself sets that a host shell may already carry (see the rules file's reason)
    scrub = {n.lower() for n in rules.get("ambient_scrub", [])}
    env = {k: v for k, v in os.environ.items() if not k.startswith(T.PREFIX) and k.lower() not in scrub}
    ours = str(T.SITE_DIR)
    env["PYTHONPATH"] = ours + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.update({T.ENV_SINK: str(sink), T.ENV_SPAWN: "0", T.ENV_DEFAULT: info["default"], T.ENV_FILE: name[:-3],
                T.ENV_MODULES: ",".join(modules), T.ENV_PLUGIN: str(root), "PYTHONHASHSEED": "0",
                "PYTHONDONTWRITEBYTECODE": "1"})
    for var in (T.ENV_RULES, T.ENV_DEBUG_TEXT):
        if os.environ.get(var):
            env[var] = os.environ[var]
    if coverage:
        env[T.ENV_COVERAGE] = "1"
    ceiling = float(rules["ceiling_seconds"].get(name, rules["ceiling_seconds"]["default"]))
    log = sink / "run.log"
    started = time.monotonic()
    with log.open("wb") as handle:
        proc = subprocess.Popen([sys.executable, "-B", str(root / "scripts" / "tests" / name)], cwd=str(root), env=env,
                                stdin=subprocess.DEVNULL, stdout=handle, stderr=subprocess.STDOUT)
        try:
            proc.wait(timeout=ceiling)
        except subprocess.TimeoutExpired:
            kill_tree(proc)
            proc.wait()
            last = ""
            try:
                last = (sink / "progress.txt").read_text(encoding="utf-8")
            except OSError:
                pass
            run.problems.append(f"{name}: killed at its ceiling of {ceiling:.0f} s (a hung or slow scenario is never "
                                f"given a wider timeout, FR-31); the last scenario that began: {last or 'none'}; no "
                                f"trace of this file is kept. Find the scenario that hangs and fix it.")
            run.code = None
            run.seconds = time.monotonic() - started
            return run
    run.code = proc.returncode
    run.seconds = time.monotonic() - started
    text = log.read_text(encoding="utf-8", errors="replace")
    run.red = [line for line in text.split("\n") if line.startswith("FAIL")]
    if run.code != 0:
        tail = "\n".join(text.split("\n")[-12:])
        run.red = run.red or [f"(no FAIL line; exit {run.code}) last output:\n{tail}"]
    for marker in sorted(sink.glob("**/hook-error-*.txt")) + sorted(sink.glob("exit-error-*.txt")):
        run.problems.append(f"{name}: the recorder failed in a process ({marker.name}: "
                            f"{marker.read_text(encoding='utf-8')[:300]}). A trace from a broken recorder is never kept.")
    final = sink / "final"
    if final.is_dir():
        for path in sorted(final.glob("*.jsonl")):
            run.finals[path.stem] = [l for l in path.read_text(encoding="utf-8").split("\n") if l]
    try:
        run.timing = json.loads((sink / "timing.json").read_text(encoding="utf-8")).get("scenarios", {})
    except (OSError, ValueError):
        pass
    for path in sorted((sink / "coverage").glob("*.json")) if (sink / "coverage").is_dir() else []:
        for base, lines in json.loads(path.read_text(encoding="utf-8")).items():
            run.coverage.setdefault(base, set()).update(lines)
    validate(run, info, rules)
    for f, s in excluded_units(rules):                  # it ran (the file runs whole), its trace is not kept or compared
        if f == name:
            run.finals.pop(s, None)
    return run


def validate(run: FileRun, info: dict, rules: dict) -> None:
    """The liveness refusals: a hook that went blind, a process that lost its stream, a scenario filed nowhere,
    an event in an untagged thread, the network (E1, E2, E6, E9, E10)."""
    expected = set(scenarios_of(info))
    got = set(run.finals) - {"_outside"}
    if "_untagged" in run.finals:
        events = [json.loads(l) for l in run.finals["_untagged"]]
        run.untagged = max(0, len(events) - 2)
        if run.untagged:
            kinds = ", ".join(f"{e['kind']}" for e in events if e["kind"] not in ("begin", "end"))[:300]
            run.problems.append(f"{run.name}: {run.untagged} event(s) were raised in a thread no scenario tagged "
                                f"({kinds}). Expected every event under a scenario; tag the thread or move the work "
                                f"into the scenario (E6).")
        got.discard("_untagged")
    for scenario in sorted(set(run.finals)):
        lines = run.finals[scenario]
        records = [json.loads(l) for l in lines]
        if not records or records[0]["kind"] != "begin":
            run.problems.append(f"{run.name}::{scenario}: the stream has no `begin` record - the recorder did not run "
                                f"in the test process. Expected a begin record first (E10).")
            continue
        if records[-1]["kind"] != "end":
            run.problems.append(f"{run.name}::{scenario}: the stream has no `end` record: the scenario never finished.")
        for rec in records:
            if rec["kind"] == "hook_missing":
                run.problems.append(f"{run.name}::{scenario}: Python child {rec['payload'].get('script')!r} ran with "
                                    f"no recorder (started with -I/-E/-S or a scrubbed PYTHONPATH). Expected every "
                                    f"Python child to load golden_sitecustomize (E9).")
            elif rec["kind"] == "hook_error":
                run.problems.append(f"{run.name}::{scenario}: the recorder raised: {rec['payload'].get('errors')}")
            elif rec["kind"] == "net":
                host = rec["payload"]["address"].rsplit(":", 1)[0]
                if host not in T.LOOPBACK:
                    run.problems.append(f"{run.name}::{scenario}: a connect to {rec['payload']['address']}: the golden "
                                        f"is offline-only. Expected loopback only; fix the scenario (E2).")
    excluded = {s for f, s in excluded_units(rules) if f == run.name}
    missing = sorted(expected - got - excluded)
    extra = sorted(got - expected)
    if missing:
        run.problems.append(f"{run.name}: no trace for scenario(s) {', '.join(missing)}: they never began. "
                            f"Expected every scenario of run_scenarios.")
    if extra:
        run.problems.append(f"{run.name}: traces for scenario(s) {', '.join(extra)} that run_scenarios does not list.")
    if info["kind"] == "outside" and "_main" not in run.finals and not run.problems:
        run.problems.append(f"{run.name}: no `_main` trace was written.")
    caps = rules.get("caps", {})
    for scenario, lines in ({} if os.environ.get(T.ENV_DEBUG_TEXT) else run.finals).items():   # debug text inflates writes
        problem = T.check_caps(f"{run.name}::{scenario}", lines, caps)
        if problem:
            run.problems.append(problem)


def run_files(root: Path, rules: dict, names: list, found: dict, jobs: int, coverage: bool, work: Path) -> dict:
    modules = driver_modules(root)
    results: dict = {}

    def one(name):
        say(f"  running {name} ...")
        run = run_file(root, rules, name, found[name], work / name[:-3], modules, coverage)
        say(f"  done    {name}: exit {run.code}, {run.seconds:.0f} s, {len(run.finals)} trace(s)"
            + (f", {len(run.problems)} problem(s)" if run.problems else ""))
        return run
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        for run in pool.map(one, names):
            results[run.name] = run
    return results


# --- golden storage ---------------------------------------------------------------------------------------------
def golden_traces(golden: Path) -> dict:
    """{file stem: {scenario: [lines]}} as stored."""
    out = {}
    if not golden.is_dir():
        return out
    for stem in sorted(p for p in golden.iterdir() if p.is_dir() and p.name != "coverage-hits"):
        out[stem.name] = {f.stem: [l for l in f.read_text(encoding="utf-8").split("\n") if l]
                          for f in sorted(stem.glob("*.jsonl"))}
    return out


def need_golden(golden: Path) -> dict:
    manifest = golden / "MANIFEST.json"
    if not manifest.is_file():
        raise Refusal(f"no golden recorded in {golden} (no MANIFEST.json): run `driver_golden.py --golden-dir "
                      f"{golden} record` on the parent commit of the change first.")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise Refusal(f"the golden's schema is {data.get('schema')}, this tool writes {SCHEMA}: re-record it.")
    return data


def python_minor() -> str:
    return "%d.%d" % sys.version_info[:2]


def slice_base(golden: Path, hashes: dict, whole: bool, root: Path, rules: dict) -> dict:
    """The stems a SLICE record adds to. A whole record starts a golden afresh; a slice joins the golden already in the
    directory, which must have been recorded on the same package state (files outside the allowed set), the same recorder
    and rules, the same interpreter and the same schema."""
    if whole or not (golden / "MANIFEST.json").is_file():
        return {}
    data = json.loads((golden / "MANIFEST.json").read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA or data.get("python") != python_minor():
        raise Refusal(f"the golden in {golden} was recorded with schema {data.get('schema')} / Python {data.get('python')}, "
                      f"this run is schema {SCHEMA} / Python {python_minor()}: a slice must join a golden of its own kind. "
                      f"Delete the directory to start over.")
    patterns = allowed_patterns(root, rules)
    drift = [c for c in changed_files(data.get("package_files", {}), hashes) if not any(fnmatch.fnmatch(c, p) for p in patterns)]
    if drift:
        raise Refusal(f"the golden in {golden} was recorded on another package state ({', '.join(drift[:8])}"
                      f"{' ...' if len(drift) > 8 else ''} differ): the slices of ONE golden come from one package state. "
                      f"Record from a frozen copy (--package <copy>), or delete the directory to start over.")
    check_recorder(root, data)
    check_root(root, data)
    return dict(data.get("files", {}))


def write_golden(golden: Path, runs: dict, found: dict, root: Path, rules: dict, hashes: dict, whole: bool = True) -> tuple:
    stems = slice_base(golden, hashes, whole, root, rules)
    for name in sorted(runs):
        stem = name[:-3]
        stems[stem] = {}
        for scenario, lines in sorted(runs[name].finals.items()):
            if scenario == "_untagged":
                continue
            data = ("\n".join(lines) + "\n").encode("ascii")
            stems[stem][scenario] = {"records": len(lines), "bytes": len(data)}
    total = sum(v["bytes"] for per in stems.values() for v in per.values())
    cap = int(rules["caps"]["total_bytes"])
    if total > cap:
        raise Refusal(f"the golden would be {total} bytes, over the total cap of {cap}: expected a golden at or under "
                      f"the cap; revisit caps.total_bytes (and fork Q6) by the Lead's word.")
    golden.mkdir(parents=True, exist_ok=True)
    if whole:
        for entry in list(golden.iterdir()):
            if entry.is_dir() and entry.name in {n[:-3] for n in found}:
                shutil.rmtree(entry)
    for name in sorted(runs):
        folder = golden / name[:-3]
        if folder.is_dir():
            shutil.rmtree(folder)
        folder.mkdir(parents=True, exist_ok=True)
        for scenario, lines in runs[name].finals.items():
            if scenario == "_untagged":
                continue
            (folder / f"{scenario}.jsonl").write_bytes(("\n".join(lines) + "\n").encode("ascii"))
    manifest = {"schema": SCHEMA, "python": python_minor(), "hashseed": "0",
                "story_run_sha256": sha_file(root / "scripts" / "story_run.py"),
                "package_files": hashes, "recorder_sha256": recorder_hash(root), "package_root": str(root),
                "package_commit": package_commit(root), "files": stems,
                "excluded": [{"unit": f"{e['file']}::{e['scenario']}", "reason": e["reason"]}
                             for e in rules.get("scenario_exclude", [])],
                "total_bytes": total}
    (golden / "MANIFEST.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8",
                                          newline="\n")
    return len(stems), total


# --- diffs ------------------------------------------------------------------------------------------------------
def show(record) -> str:
    return "(none: the stream ends here)" if record is None else (record if len(record) < 700 else record[:700] + " ...")


def compare_runs(runs: dict, golden_all: dict, only) -> tuple:
    """(compared, equal, differ[list of dicts], completeness problems)."""
    compared = equal = 0
    differ, problems = [], []
    for name, run in sorted(runs.items()):
        stem = name[:-3]
        gold = golden_all.get(stem)
        if gold is None:
            problems.append(f"{name}: the golden has no traces of this file (golden has: {sorted(golden_all)}).")
            continue
        got = {s: l for s, l in run.finals.items() if s != "_untagged"}
        wanted = set(gold) | set(got)
        if only and only.get(name):
            wanted = {only[name]}
        for scenario in sorted(wanted):
            if scenario not in gold or scenario not in got:
                problems.append(f"{name}::{scenario}: " + ("in the golden but not recorded now (renamed or removed?)"
                                                           if scenario in gold else
                                                           "recorded now but not in the golden (a new scenario?)")
                                + ". A scenario's identity is (file, function name); re-record on the parent commit.")
                continue
            compared += 1
            diff = T.compare_lines(gold[scenario], got[scenario])
            if diff is None:
                equal += 1
            else:
                differ.append(dict(diff, file=name, scenario=scenario))
    return compared, equal, differ, problems


def print_diffs(differ: list) -> None:
    for item in differ[:10]:
        say(f"DIFFER {item['file']}::{item['scenario']} at seq {item['seq']}")
        say(f"  golden: {show(item['golden'])}")
        say(f"  now:    {show(item['now'])}")
        for line in item["text_diff"]:
            say("    " + line)
    if len(differ) > 10:
        say(f"... and {len(differ) - 10} more: " + ", ".join(f"{d['file']}::{d['scenario']}" for d in differ[10:]))


def summary(recorded=0, compared=0, equal=0, untagged=0, excluded=0, extra="") -> None:
    say(f"summary: scenarios recorded={recorded} compared={compared} equal={equal} untagged={untagged} "
        f"excluded={excluded}" + (" " + extra if extra else ""))


# --- coverage ---------------------------------------------------------------------------------------------------
def coverage_report(root: Path, hits: dict, rules: dict) -> dict:
    """C1: the lines of story_run.py no scenario ran, as maximal runs with their function, home and guard."""
    path = root / "scripts" / "story_run.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    code = compile(source, str(path), "exec")
    executable = set()
    stack = [code]
    while stack:
        co = stack.pop()
        executable.update(l for _s, _e, l in co.co_lines() if l)
        stack.extend(c for c in co.co_consts if hasattr(c, "co_code"))
    covered = set(hits.get("story_run.py", set())) & executable
    never = sorted(executable - covered)
    homes = {row["name"]: row["home"] for row in layer_map(root).get("names", [])}

    spans = []                                         # (start, end, qualified name)

    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qual = (prefix + "." if prefix else "") + child.name
                spans.append((child.lineno, child.end_lineno, qual))
                walk(child, qual)
    walk(tree, "")

    def function_of(line):
        best = None
        for start, end, qual in spans:
            if start <= line <= end and (best is None or start >= best[0]):
                best = (start, end, qual)
        return best[2] if best else "<module>"

    def guard_of(line):
        best = None

        def visit(node, label):
            nonlocal best
            for child in ast.iter_child_nodes(node):
                if not hasattr(child, "lineno") or not hasattr(child, "end_lineno"):
                    continue
                if not (child.lineno <= line <= child.end_lineno):
                    continue
                kind = label
                if isinstance(child, ast.If):
                    first_body = child.body[0].lineno
                    if line < first_body:
                        kind = "if-test"
                    elif line <= child.body[-1].end_lineno:
                        kind = "if-body"
                    else:
                        kind = "elif" if (len(child.orelse) == 1 and isinstance(child.orelse[0], ast.If)
                                          and child.orelse[0].lineno <= line) else "else"
                elif isinstance(child, ast.Try):
                    kind = "try-body"
                    for handler in child.handlers:
                        if handler.lineno <= line <= handler.end_lineno:
                            kind = "except"
                    if child.orelse and child.orelse[0].lineno <= line <= child.orelse[-1].end_lineno:
                        kind = "try-else"
                    if child.finalbody and child.finalbody[0].lineno <= line <= child.finalbody[-1].end_lineno:
                        kind = "finally"
                elif isinstance(child, (ast.For, ast.While, ast.AsyncFor)):
                    kind = "loop-else" if child.orelse and child.orelse[0].lineno <= line else "loop-body"
                elif isinstance(child, (ast.With, ast.AsyncWith)):
                    kind = "with-body"
                elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    kind = "function-body"
                    for before in child.body:
                        if before.lineno >= line:
                            break
                        if isinstance(before, ast.If) and before.body and isinstance(
                                before.body[-1], (ast.Return, ast.Raise, ast.Continue, ast.Break)):
                            kind = "function-body after an early return"
                best = kind
                visit(child, kind)
        visit(tree, "module")
        return best or "module"

    runs = []
    for line in never:
        if runs and line - runs[-1][1] <= 1:
            runs[-1][1] = line
        else:
            runs.append([line, line])
    items = []
    for start, end in runs:
        func = function_of(start)
        items.append({"lines": [start, end], "function": func, "home": homes.get(func) or homes.get(
            func.split(".")[0], ""), "guard": guard_of(start)})
    return {"schema": SCHEMA, "python": python_minor(), "story_run_sha256": sha_file(path),
            "executable_lines": len(executable), "covered_lines": len(covered), "never_run_lines": len(never),
            "never_run": items}


# --- modes ------------------------------------------------------------------------------------------------------
def select(found: dict, only, mode: str, rules: dict) -> list:
    if only and mode == "record" and any(only.values()):
        raise Refusal("record with --only FILE::SCENARIO would leave a golden that mixes two recordings of one file: record "
                      "whole files (--only FILE[,FILE...] is a slice), then compare a scenario with --only FILE::SCENARIO.")
    names = [n for n in sorted(found) if n in only] if only else sorted(found)
    excluded = excluded_units(rules)
    return [n for n in names if any((n, s) not in excluded for s in scenarios_of(found[n]))]


def check_python(manifest: dict) -> None:
    if manifest.get("python") != python_minor():
        raise Refusal(f"the golden was recorded under Python {manifest.get('python')}, this is {python_minor()}: "
                      f"expected the same minor version; re-record the golden with this interpreter.")


def litter_check(root: Path, before: set, skip: Path | None) -> None:
    after = package_paths(root, skip)
    new = sorted(after - before)
    if new:
        raise Refusal(f"the run left {', '.join(new[:10])}{' ...' if len(new) > 10 else ''} in the package {root}: "
                      f"a golden run writes nothing there (FR-45). Remove the paths and find the writer.")


def do_record(args, root: Path, rules: dict, found: dict, golden: Path, only=None) -> int:
    names = select(found, only, "record", rules)
    whole = not only
    hashes = package_hashes(root)
    skip = golden if root in golden.parents else None
    before = package_paths(root, skip)
    slice_base(golden, hashes, whole, root, rules)         # a slice of another package state is refused BEFORE it runs
    with tempfile.TemporaryDirectory(prefix="driver-golden-") as work:
        say(f"record: {len(names)} test files{' (a slice)' if not whole else ''}, "
            f"{sum(len(scenarios_of(found[n])) for n in names)} units, jobs={args.jobs}, python {python_minor()}, "
            f"package {root}")
        say_excluded(rules)
        runs = run_files(root, rules, names, found, args.jobs, args.coverage, Path(work))
    problems = [p for r in runs.values() for p in r.problems]
    for run in runs.values():
        if run.code != 0 and run.code is not None:
            problems.append(f"{run.name}: exit {run.code} - a red scenario is never recorded (K1): "
                            + " | ".join(run.red[:3]))
    if problems:
        for p in problems:
            say("REFUSED: " + p)
        return 2
    litter_check(root, before, skip)
    now = package_hashes(root)
    drift = [c for c in changed_files(hashes, now)]
    if drift:
        raise Refusal(f"the package changed while it was recorded ({', '.join(drift[:8])}): a golden belongs to the "
                      f"package it measured (FR-27). Record from a frozen copy: --package <copy>.")
    count, total = write_golden(golden, runs, found, root, rules, hashes, whole)
    units = sum(len(r.finals) for r in runs.values())
    if args.coverage:
        hits_dir = golden / "coverage-hits"                 # one file per test file: slices add to the same record
        if whole and hits_dir.is_dir():
            shutil.rmtree(hits_dir)
        hits_dir.mkdir(parents=True, exist_ok=True)
        for run in runs.values():
            (hits_dir / (run.name[:-3] + ".json")).write_text(json.dumps(
                {base: sorted(lines) for base, lines in run.coverage.items()}), encoding="ascii", newline="\n")
        merged: dict = {}
        for path in sorted(hits_dir.glob("*.json")):
            for base, lines in json.loads(path.read_text(encoding="ascii")).items():
                merged.setdefault(base, set()).update(lines)
        report = coverage_report(root, merged, rules)
        report["test_files_in_the_record"] = sorted(p.stem + ".py" for p in hits_dir.glob("*.json"))
        data = json.dumps(report, indent=1, sort_keys=True) + "\n"
        if len(data.encode("utf-8")) > int(rules["caps"]["coverage_bytes"]):
            raise Refusal(f"coverage-n0.json would be {len(data)} bytes, over caps.coverage_bytes.")
        (golden / "coverage-n0.json").write_text(data, encoding="utf-8", newline="\n")
        say(f"coverage: story_run.py {report['covered_lines']} of {report['executable_lines']} executable lines ran; "
            f"{report['never_run_lines']} never ran, in {len(report['never_run'])} runs -> {golden / 'coverage-n0.json'}")
    slow = sorted(((t, f"{r.name}::{s}") for r in runs.values() for s, t in r.timing.items()), reverse=True)[:5]
    say("slowest scenarios (s): " + ", ".join(f"{n} {t:.1f}" for t, n in slow))
    say("record cost: " + ", ".join(f"{r.name[:-3]} {r.seconds:.0f}s" for r in runs.values()))
    say(f"trace size: {total} bytes over {units} unit traces (cap {rules['caps']['total_bytes']}); excluded: "
        f"{len(rules.get('scenario_exclude', []))}")
    blind = rules.get("known_blind_spots", [])
    say(f"known blind spots (rig patches that absorb a call with no I/O of its own; listed, not hidden): {len(blind)}: "
        + "; ".join(b["patch"] for b in blind))
    untagged = sum(r.untagged for r in runs.values())
    summary(recorded=units, untagged=untagged, excluded=len(rules.get("scenario_exclude", [])),
            extra=f"files={count} bytes={total}")
    return 0


def do_compare(args, root: Path, rules: dict, found: dict, golden: Path, only) -> int:
    manifest = need_golden(golden)
    check_python(manifest)
    check_root(root, manifest)
    refusing, allowed = provenance(root, manifest, rules)
    if refusing:
        raise Refusal("the golden was recorded on a different package (commit "
                      f"{manifest.get('package_commit') or 'unknown'}, this one {package_commit(root) or 'unknown'}): these files "
                      "differ from its MANIFEST and are not in the allowed set (the driver set, the layer map, the golden's own "
                      f"files, design/, CHANGELOG.md, the source-reading tests): {', '.join(refusing[:12])}"
                      f"{' ...' if len(refusing) > 12 else ''}. A diff that cannot be attributed to the move is no "
                      f"evidence about the move (K14): re-record the golden on the parent commit.")
    check_recorder(root, manifest)
    if allowed:
        say(f"compare: changed inside the allowed set: {', '.join(allowed[:12])}")
    names = select(found, only, "compare", rules)
    skip = golden if root in golden.parents else None
    before = package_paths(root, skip)
    golden_all = golden_traces(golden)
    # K11: a file or scenario missing on either side refuses, naming both
    if not only:
        gone = sorted(set(golden_all) - {n[:-3] for n in found})
        if gone:
            raise Refusal(f"the golden holds traces of {', '.join(gone)}, which are no test file of this package now.")
    with tempfile.TemporaryDirectory(prefix="driver-golden-") as work:
        runs = run_files(root, rules, names, found, args.jobs, False, Path(work))
    problems = [p for r in runs.values() for p in r.problems]
    if problems:
        for p in problems:
            say("REFUSED: " + p)
        return 2
    litter_check(root, before, skip)
    compared, equal, differ, incomplete = compare_runs(runs, golden_all, only)
    if incomplete:
        for p in incomplete:
            say("REFUSED: " + p)
        return 2
    red = [r for r in runs.values() if r.code != 0]
    for r in red:
        say(f"RED: {r.name} exited {r.code}: " + " | ".join(r.red[:3]))
    print_diffs(differ)
    excluded = len(rules.get("scenario_exclude", []))
    say_excluded(rules)
    untagged = sum(r.untagged for r in runs.values())
    summary(compared=compared, equal=equal, untagged=untagged, excluded=excluded,
            extra=f"differ={len(differ)} red={len(red)}")
    return 0 if not differ and not red and compared == equal else 1


def do_stability(args, root: Path, rules: dict, found: dict, only) -> int:
    names = select(found, only, "stability", rules)
    say_excluded(rules)
    skip = None
    before = package_paths(root, skip)
    results = []
    for round_ in (1, 2):
        with tempfile.TemporaryDirectory(prefix="driver-golden-") as work:
            say(f"stability: record {round_} of 2 ...")
            runs = run_files(root, rules, names, found, args.jobs, False, Path(work))
        problems = [p for r in runs.values() for p in r.problems]
        problems += [f"{r.name}: exit {r.code} - a red scenario has no stable trace: " + " | ".join(r.red[:3])
                     for r in runs.values() if r.code != 0]
        if problems:
            for p in problems:
                say("REFUSED: " + p)
            return 2
        results.append(runs)
    litter_check(root, before, skip)
    unstable = stability_diffs(results[0], results[1], only)
    count = sum(len([s for s in r.finals if s != "_untagged"]) for r in results[0].values())
    if unstable:
        for item in unstable[:30]:
            say(f"UNSTABLE {item['file']}::{item['scenario']} at seq {item['seq']}")
            say(f"  first:  {show(item['golden'])}")
            say(f"  second: {show(item['now'])}")
            for line in item["text_diff"]:
                say("    " + line)
        names = {(u["file"], u["scenario"]) for u in unstable}
        summary(compared=count, equal=count - len(names), extra=f"unstable={len(names)}")
        return 1
    say(f"stability: {count} unit traces, recorded twice, byte-equal")
    summary(compared=count, equal=count)
    return 0


def stability_diffs(first: dict, second: dict, only) -> list:
    out = []
    for name in sorted(first):
        a = {s: l for s, l in first[name].finals.items() if s != "_untagged"}
        b = {s: l for s, l in second[name].finals.items() if s != "_untagged"}
        for scenario in sorted(set(a) | set(b)):
            if only and only.get(name) and scenario != only[name]:
                continue
            diffs = T.all_diffs(a.get(scenario, []), b.get(scenario, []), 3 if os.environ.get(T.ENV_DEBUG_TEXT) else 1)
            for index, diff in enumerate(diffs):
                out.append(dict(diff, file=name, scenario=scenario, more=index))
    return out


def do_probe(args, root: Path, rules: dict, found: dict, golden: Path, name: str) -> int:
    if name not in PROBES:
        raise Refusal(f"unknown probe {name!r}: the probes are {', '.join(PROBES)}.")
    manifest = need_golden(golden)
    check_python(manifest)
    check_root(root, manifest)
    check_recorder(root, manifest)
    live = root / "scripts" / "story_run.py"
    before = sha_file(live)
    say(f"probe {name}: the live story_run.py sha256 before: {before}")
    with tempfile.TemporaryDirectory(prefix="driver-golden-probe-") as tmp:
        copy = Path(tmp) / "pkg"
        shutil.copytree(root, copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"))
        file_name = "test_story_run_refusals.py"
        if file_name not in found:
            raise Refusal(f"the probe runs {file_name}, which this package does not have.")
        refusing, _allowed = provenance(copy, manifest, rules)
        if refusing:
            raise Refusal("the probe's package copy differs from the golden's package outside the allowed set: "
                          f"{', '.join(refusing[:12])}. Re-record the golden on this package (K14).")
        # THE CONTROL (F3): the same file, the same copy, the same path, UNMUTATED, in this very run. The golden is the stored
        # record of another directory and another moment; what the probe compares the mutant with is its own control.
        with tempfile.TemporaryDirectory(prefix="driver-golden-") as work:
            control_runs = run_files(copy, rules, [file_name], found, 1, False, Path(work))
        problems = [p for r in control_runs.values() for p in r.problems]
        if problems or control_runs[file_name].code != 0:
            for p in problems or [f"the unmutated control exited {control_runs[file_name].code}: a probe needs a green control"]:
                say("REFUSED: " + p)
            return 2
        say(f"probe {name}: the control ({file_name} unmutated, at {copy}) recorded: "
            f"{len(control_runs[file_name].finals)} scenario traces")
        target = copy / "scripts" / "story_run.py"
        text = target.read_bytes().decode("utf-8")
        nl = "\r\n" if "\r\n" in text else "\n"            # a checkout with autocrlf has CRLF: the anchor follows the file
        write_line = '        _write_json(self.state_dir / "driver-runs" / f"{dispatch}.json", result)' + nl
        anchor_start = text.find("    def resume_with(")
        position = text.find(write_line, anchor_start) if anchor_start >= 0 else -1
        next_line = text.find("        self.progress_line()", position) if position >= 0 else -1
        # the two lines must be adjacent: the swap is of the state write and the progress line right after it
        if position < 0 or next_line != position + len(write_line):
            raise Refusal("the probe's anchor was not found in resume_with (the `_write_json(... driver-runs ...)` line "
                          "followed by `self.progress_line()`): update the probe's snippet in driver_golden.py.")
        end = text.find(nl, next_line) + len(nl)
        progress_line = text[next_line:end]
        mutated = text[:position] + progress_line + write_line + text[end:]
        target.write_bytes(mutated.encode("utf-8"))
        with tempfile.TemporaryDirectory(prefix="driver-golden-") as work:
            mutant_runs = run_files(copy, rules, [file_name], found, 1, False, Path(work))
        problems = [p for r in mutant_runs.values() for p in r.problems]
        if problems:
            for p in problems:
                say("REFUSED: " + p)
            return 2
        own = mutant_runs[file_name].code
        control = {s: l for s, l in control_runs[file_name].finals.items() if s != "_untagged"}
        mutant = {s: l for s, l in mutant_runs[file_name].finals.items() if s != "_untagged"}
    after = sha_file(live)
    say(f"probe {name}: the live story_run.py sha256 after:  {after} ({'equal' if after == before else 'DIFFERENT'})")
    if after != before:
        say("REFUSED: the live file changed during the probe: the probe works on a copy only (command hygiene p.7).")
        return 2
    say(f"probe {name}: the mutant's own {file_name} exit code: {own} "
        f"({'the rig is blind to this reorder' if own == 0 else 'the rig noticed it too'})")
    differing = []                                              # (scenario, seq, is the swap, diff)
    for scenario in sorted(set(control) | set(mutant)):
        diff = T.compare_lines(control.get(scenario, []), mutant.get(scenario, []))
        if diff is not None:
            ok, why = is_the_swap(control.get(scenario, []), mutant.get(scenario, []), diff["seq"])
            differing.append((scenario, diff["seq"], ok, why, diff))
    compared = len(control) + len(set(mutant) - set(control))
    equal = compared - len(differing)
    if not differing:
        say(f"probe {name}: NOT detected: all {compared} scenarios equal their control on a reordered side effect")
        summary(compared=compared, equal=equal, extra="probe=missed")
        return 1
    foreign = [d for d in differing if not d[2]]
    if foreign:
        scenario, seq, _ok, why, diff = foreign[0]
        say(f"probe {name}: NOT the swap: the first difference of {file_name}::{scenario} at seq {seq} is not the swapped pair "
            f"({why}); expected the `driver-runs` write and the `[progress]` line of resume_with exchanged, nothing else first.")
        print_diffs([dict(diff, file=file_name, scenario=scenario)])
        summary(compared=compared, equal=equal, extra=f"differ={len(differing)} swap={len(differing) - len(foreign)} probe=not-the-swap")
        return 1
    scenario, seq, _ok, _why, diff = differing[0]
    say(f"probe {name}: detected: scenario {scenario} of {file_name}, first differing seq {seq}: the swapped pair, and the "
        f"first difference of each of the {len(differing)} differing scenarios against an unmutated control at the same path")
    print_diffs([dict(diff, file=file_name, scenario=scenario)])
    summary(compared=compared, equal=equal, extra=f"differ={len(differing)} swap={len(differing)} probe=detected")
    return 0


def is_the_swap(control: list, mutant: list, seq: int) -> tuple:
    """(True, '') when the FIRST difference of two streams at `seq` is exactly the probe's mutation: the control has the
    `driver-runs` write then the `[progress]` line, the mutant has them the other way round, the write itself unchanged, and
    the streams are as long as each other. Anything else - a fingerprint, a path, a drop - is named in the second member."""
    def rec(lines, i):
        return json.loads(lines[i]) if 0 <= i < len(lines) else None

    def bare(r):
        return {k: v for k, v in r.items() if k != "seq"} if r else None
    a, a1, b, b1 = rec(control, seq), rec(control, seq + 1), rec(mutant, seq), rec(mutant, seq + 1)
    if None in (a, a1, b, b1):
        return False, "a stream ends here"
    if len(control) != len(mutant):
        return False, f"the streams are {len(control)} and {len(mutant)} records long"
    progress = lambda r: r["kind"] == "stdout" and str(r["payload"].get("text", "")).startswith("[progress]")
    if not (a["kind"] == "write" and "driver-runs" in str(a["payload"].get("path", "")) and progress(a1)):
        return False, f"the control's pair is {a['kind']} then {a1['kind']}, not the driver-runs write then the progress line"
    if not (progress(b) and bare(b1) == bare(a)):
        return False, f"the mutant's pair is {b['kind']} then {b1['kind']}, not the progress line then the same write"
    return True, ""


# --- main -------------------------------------------------------------------------------------------------------
class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        print(f"driver_golden: {message}. Modes: {', '.join(MODES)} (positional or --<mode>); see the module docstring.",
              file=sys.stderr)
        raise SystemExit(2)


def build_parser() -> Parser:
    ap = Parser(prog="driver_golden.py", description="the driver golden: record / compare / stability / probe")
    ap.add_argument("mode", nargs="?", help="record | compare | stability | probe")
    ap.add_argument("probe_name", nargs="?", help="the probe (with `probe`)")
    for mode in MODES:
        if mode != "probe":
            ap.add_argument("--" + mode, action="store_true", dest="flag_" + mode)
    ap.add_argument("--probe", dest="probe_flag", default=None, help="the probe's name (the flag form of `probe`)")
    ap.add_argument("--only", default=None, help="FILE or FILE::SCENARIO")
    ap.add_argument("--package", default=None, help="the package root to run (default: this tool's own package)")
    ap.add_argument("--golden-dir", default=None, help="where the golden lives (outside the package)")
    ap.add_argument("--jobs", type=int, default=4, help="test files in parallel (default 4)")
    ap.add_argument("--coverage", action="store_true", help="record: also write coverage-n0.json")
    ap.add_argument("--rules", default=None, help="driver-golden-rules.json to use (tests)")
    ap.add_argument("--debug-text", action="store_true",
                    help="stability/compare debugging only: write records carry the normalised content, so a differing "
                         "sha shows what differs. Never for a golden.")
    return ap


def resolve_mode(args):
    chosen = []
    if args.mode:
        if args.mode not in MODES:
            raise Refusal(f"unknown mode {args.mode!r}: the modes are {', '.join(MODES)}.")
        chosen.append(args.mode)
    chosen.extend(m for m in MODES if m != "probe" and getattr(args, "flag_" + m))
    if args.probe_flag is not None:
        chosen.append("probe")
    if not chosen:
        raise Refusal(f"no mode given: choose exactly one of {', '.join(MODES)}.")
    if len(chosen) > 1:
        raise Refusal(f"two modes given ({', '.join(chosen)}): choose exactly one of {', '.join(MODES)}.")
    return chosen[0]


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        mode = resolve_mode(args)
        if args.jobs < 1:
            raise Refusal(f"--jobs {args.jobs}: expected 1 or more (1 runs the files one after another).")
        if not args.golden_dir:
            raise Refusal("--golden-dir is required: the golden lives outside the package, for example "
                          "--golden-dir <repo>/experiments/driver-golden.")
        if args.coverage and mode != "record":
            raise Refusal("--coverage goes with record: the coverage record is made by the recording run.")
        if args.debug_text:
            if mode in ("record", "compare", "probe"):
                raise Refusal("--debug-text changes the records, so it is for stability only: a golden or a compare "
                              "made with it would never match one made without it.")
            os.environ[T.ENV_DEBUG_TEXT] = "1"
        root = package_root(args)
        if args.rules:
            os.environ[T.ENV_RULES] = str(Path(args.rules).resolve())
        rules = T.load_rules(args.rules)
        check_rules_file(root)
        found = discover(root, rules)
        golden = Path(args.golden_dir).resolve()
        only = parse_only(args.only, found)
        say(f"driver_golden {mode}: python {sys.version.split()[0]} ({python_minor()}), {len(found)} test files, "
            f"{sum(len(scenarios_of(i)) for i in found.values())} units")
        if mode == "record":
            select(found, only, mode, rules)
            return do_record(args, root, rules, found, golden, only)
        if mode == "compare":
            return do_compare(args, root, rules, found, golden, only)
        if mode == "stability":
            return do_stability(args, root, rules, found, only)
        name = args.probe_name or args.probe_flag or ""
        if args.mode == "probe" and not name:
            raise Refusal(f"probe needs a name: one of {', '.join(PROBES)}.")
        return do_probe(args, root, rules, found, golden, name)
    except Refusal as exc:
        say(f"REFUSED: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
