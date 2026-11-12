"""The census of stored environment facts and its ratchet (t-304 N0, FR-60's measurer).

What stored fact of the machine (the project's place, the package's, the home, the interpreter, a pid, a host, a container, an
image digest) does the factory write into a file or print, and which writer does it? `state_census.py` runs nine flows in two canary
worlds (and a third run of world A for noise), scans everything they leave, and this file holds the line: the baseline
`fixtures/env-facts-baseline.json` is a list of DEBTS (each row names the node that removes it, FR-58); a hit outside it fails
naming flow, file, pointer, fact and writer, and a row with no hit fails as stale, so the list only shrinks.

Keys: N0-K1 green against the baseline with every flow run (exit 0, at least one artifact); N0-K2 planted facts (a project path, a
pid, a host name) are caught, and without the plants the run is green; N0-K3 the ratchet both ways, on a scratch copy of the
baseline; N0-K4 positive and negative controls on real writers (the install manifest holds no fact, the story_run-shaped
`initialize` does, the driver's in-flight pid is seen); N0-K5 the differential (package_fingerprint equal, input_hash differing,
noise not empty); N0-K6 the size cap AT and BEYOND; N0-K7 the CLI battery; N0-K8 every canary token is 8 characters or fewer;
N0-K9 the F3 in-flight snapshot is taken after the stub read its stdin (no race with the driver's write; a snapshot not taken so
fails the census as "not observed"); N0-K10 `load_baseline` refuses a `leaves_at` outside the legend and an `inventory_row` outside
`writers`; N0-K11 the writers the map had missed are in it; N0-K12 the report appends the notes file verbatim (a missing one is said).
Edges: E8 (an unscanned file is never clean), E9 (a missing key list or baseline is never a pass), E13 (a flow that produced
nothing or exited non-zero fails), E14 (the tree's uncommitted package files are recorded).

Run:  python -B scripts/tests/test_state_portability.py                       (the checks; prints the counts)
      ... --report PATH            also write the census as JSON (census_version 1);  --markdown PATH  the same as Markdown
      ... --write-baseline         regenerate the baseline's rows from the census (the integrator, once, at the package commit);
                                   refused while the census has any failure or a hit has no `file_writers` entry
      ... --baseline PATH          use (or, with --write-baseline, write) another baseline file: a scratch copy
"""
import argparse
import contextlib
import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, check_in, cleanup, finish  # noqa: E402

import state_census as SC  # noqa: E402


class CliError(Exception):
    """A refused command line: the message names the flag and what was expected (FR-1)."""


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CliError(message)


def parse_args(argv):
    ap = _Parser(description=__doc__.splitlines()[0], add_help=True)
    ap.add_argument("--report", metavar="PATH", help="write the census as JSON to this file")
    ap.add_argument("--markdown", metavar="PATH", help="write the census as Markdown to this file")
    ap.add_argument("--write-baseline", action="store_true", help="regenerate the rows of the baseline from the census")
    ap.add_argument("--baseline", metavar="PATH", help="the baseline file to read (and to write with --write-baseline)")
    args = ap.parse_args(argv)
    for flag in ("report", "markdown", "baseline"):
        value = getattr(args, flag)
        if value is None:
            continue
        if not str(value).strip():
            raise CliError(f"--{flag} needs a file path and the value given is empty; give the file to use, for example --{flag} out.json")
        if Path(value).is_dir():
            raise CliError(f"--{flag} {value} is a folder; give a file inside it, for example --{flag} {Path(value) / 'census.json'}")
    return args


def apply_flags(args, census: dict, baseline_path: Path, baseline) -> int:
    """The flags that act on a finished census. 0, or a refusal's exit code (the message is printed here)."""
    for flag, render in (("report", lambda c: json.dumps(SC.public_census(c), indent=1, ensure_ascii=False) + "\n"),
                         ("markdown", SC.render_markdown)):
        target = getattr(args, flag)
        if target:
            try:
                Path(target).parent.mkdir(parents=True, exist_ok=True)
                Path(target).write_text(render(census), encoding="utf-8")
            except OSError as exc:
                print(f"test_state_portability: --{flag} {target} could not be written ({exc}); give a file in a folder you can write to",
                      file=sys.stderr)
                return 2
            print(f"INFO: {flag} written: {target}")
    if args.write_baseline:
        try:
            made = SC.build_baseline(copy.deepcopy(census), baseline)
        except SC.BaselineRefused as exc:
            print(f"test_state_portability: --write-baseline refused: {exc}", file=sys.stderr)
            return 2
        Path(baseline_path).parent.mkdir(parents=True, exist_ok=True)
        Path(baseline_path).write_text(SC.format_baseline(made), encoding="utf-8")
        print(f"INFO: baseline written: {baseline_path} ({len(made['rows'])} rows)")
    return 0


def counts_text(census: dict) -> list:
    c = census["counts"]
    return [f"census: {c['total']} hit identities ({c['baselined']} in the baseline, {c['new']} new, "
            f"{len(census['ratchet']['stale'])} stale rows)",
            "census: by fact: " + ", ".join(f"{k} {v}" for k, v in c["by_fact"].items()),
            "census: by carrier class: " + ", ".join(f"{k} {v}" for k, v in c["by_carrier_class"].items()),
            "census: by flow: " + ", ".join(f"{k} {v}" for k, v in c["by_flow"].items()),
            f"census: not exercised: {len(census['not_exercised'])} writer site(s); noise: {len(census['noise'])} key(s); "
            f"differential: {len(census['differential'])}; unrecognised files: {len(census['unrecognised_files'])}"]


# --- N0-K8, E9, N0-K2, N0-K6: the sections that need no world ----------------------------------------------------

def k8_tokens() -> None:
    tokens = SC.canary_tokens()
    long = {k: v for k, v in tokens.items() if len(v) > 8}
    check_eq("N0-K8: every canary token is 8 characters or fewer (so the 8.3 alias equals the name)", long, {})
    check("N0-K8: and each is uppercase alphanumeric (a path spelling can only change its case or its slashes)",
          all(v.isalnum() and v == v.upper() for v in tokens.values()), str(tokens))
    check("N0-K8: and the two worlds share no token (a hit names its world's place)", len(set(tokens.values())) == len(tokens))
    check_eq("N0-K8: world B puts the project three levels down, world A one", (len(SC.WORLDS["A"]["sub"]), len(SC.WORLDS["B"]["sub"])), (0, 2))


def e9_missing_detector(tmp: Path) -> None:
    missing = tmp / "no-such-key-list.json"
    try:
        SC.load_keys(missing)
        raised = ""
    except SC.DetectorMissing as exc:
        raised = str(exc)
    check_in("E9: a missing key list is a failure that names the file and what to do, never 'clean'", "env-fact-keys.json", raised)
    broken = tmp / "broken-keys.json"
    broken.write_text("{not json", encoding="utf-8")
    empty = tmp / "empty-keys.json"
    empty.write_text(json.dumps({"keys": [], "differential_keys": ["*hash*"]}), encoding="utf-8")
    for label, path in (("not JSON", broken), ("no key rows", empty)):
        try:
            SC.load_keys(path)
            raised = ""
        except SC.DetectorMissing as exc:
            raised = str(exc)
        check(f"E9: a key list that is {label} is refused as well", bool(raised), raised)
    check("E9 control: the shipped key list loads and holds the eight keys of the spec",
          sorted(SC.load_keys()["keys"]) == sorted(["pid", "driver_pid", "hostname", "container", "image", "image_digest",
                                                    "transcript", "machine"]))
    built = []
    real_build = SC.World.build
    SC.World.build = lambda self: built.append(self.label)         # counted, never run: nothing may be built before the list is read
    try:
        SC.run_census(progress=lambda _m: None, flows=["F7"], keys_path=missing)
        refused = ""
    except SC.DetectorMissing as exc:
        refused = str(exc)
    except Exception as exc:
        refused = ""
        built.append(f"unexpected {exc.__class__.__name__}")
    finally:
        SC.World.build = real_build
    check_eq("E9: the census itself stops on a missing key list before it builds any world", (bool(refused), built), (True, []))


def k2_planted(tmp: Path) -> None:
    """A synthetic writer plants facts into `state/planted.json`; the census must go red naming file, pointer and fact."""
    keys = SC.load_keys()
    det = SC.make_detector("A", tmp)
    world = tmp / SC.WORLDS["A"]["project"]
    plant = tmp / "plant"
    (plant / "state").mkdir(parents=True)
    path = plant / "state" / "planted.json"
    path.write_text(json.dumps({"x": str(world / "x"), "pid": 4242, "note": "built on " + SC.REAL["host"], "n": 5}), encoding="utf-8")
    census = SC.scan_dir(plant, det, keys, flow="unit")
    verdict = SC.evaluate(census, {"rows": []})
    text = "\n".join(verdict["lines"])
    check_in("N0-K2: a planted project path is red, naming the file", "<PROJECT>/state/planted.json", text)
    check_in("N0-K2: ... the pointer (/x)", "pointer /x,", text)
    check_in("N0-K2: ... and the fact (project_root)", "fact project_root", text)
    pid = [h for h in census["hits"] if h["pointer"] == "/pid"]
    check_eq("N0-K2: a planted {\"pid\": 4242} is caught by the key detector", [(h["fact"], h["detector"]) for h in pid], [("pid", "key")])
    if SC.REAL["host"] and len(SC.REAL["host"]) >= 6:
        host = [h for h in census["hits"] if h["fact"] == "host"]
        check("N0-K2: a planted host name is caught by the host detector", any(h["detector"] == "host" for h in host), str(host))
    else:
        print(f"INFO: N0-K2 host plant: host not scanned (too short: {len(SC.REAL['host'])} characters)")
    clean = tmp / "clean"
    (clean / "state").mkdir(parents=True)
    (clean / "state" / "planted.json").write_text(json.dumps({"x": "x", "pid": None, "host": "", "image": False, "note": "relative only",
                                                              "n": 5}), encoding="utf-8")
    again = SC.scan_dir(clean, det, keys, flow="unit")
    check_eq("N0-K2 control: without the plants (a null pid, an empty host, a boolean `image`: no machine in any of them) the same "
             "writer's output has no hit and the verdict is green",
             (again["hits"], SC.evaluate(again, {"rows": []})["lines"]), ([], []))
    spelled = tmp / "spelled"
    (spelled / "state").mkdir(parents=True)
    base = str(world / "x")
    (spelled / "state" / "s.json").write_text(json.dumps({"forward": base.replace(chr(92), "/"), "lower": base.lower(),
                                                          "slug": "C--" + SC.WORLDS["A"]["project"] + "-x"}), encoding="utf-8")
    got = {(h["pointer"], h["spelling"]) for h in SC.scan_dir(spelled, det, keys)["hits"]}
    check_eq("N0-K2: the same place in other spellings (forward slashes, lower case, a slug) is still the place",
             got, {("/forward", "forward"), ("/lower", "lower"), ("/slug", "slug")})
    # the stdout / UTF-16 carriers: raw bytes in UTF-16-LE are scanned too
    u16 = tmp / "u16"
    (u16 / "state").mkdir(parents=True)
    (u16 / "state" / "u.txt").write_bytes(("see " + str(world / "y")).encode("utf-16-le"))
    check_eq("N0-K2: a UTF-16-LE file holding the place is a hit", [h["fact"] for h in SC.scan_dir(u16, det, keys)["hits"]], ["project_root"])


def k9_snapshot_order(tmp: Path) -> None:
    """The F3 stub copies the driver's state AFTER it read its stdin (t-348 finding 1): the driver writes `in_flight` after Popen
    returns and sends the prompt only then, so the copy cannot precede the write. Run on the real stub text, no sleep: the parent
    plays the driver (writes the file, then sends the prompt) and the marker the stub leaves says when it copied."""
    control = tmp / "k9-control.json"
    control.write_text("{}", encoding="utf-8")
    stub = tmp / "k9-stub.py"
    stub.write_text(SC.f3_stub_source(), encoding="utf-8")
    state, seen = tmp / "k9-driver-state.json", tmp / "k9-seen.json"
    env = {**os.environ, "STUB_CONTROL": str(control), "STUB_LOG": str(tmp / "k9-log.jsonl"), "CENSUS_SNAPSHOT_FROM": str(state),
           "CENSUS_SNAPSHOT_TO": str(seen), "PYTHONDONTWRITEBYTECODE": "1"}
    state.write_text("before the write", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-B", str(stub)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    state.write_text("in_flight written", encoding="utf-8")         # the driver's mark_in_flight, before communicate sends the prompt
    _out, err = proc.communicate(b"the prompt")
    order = seen.with_name(seen.name + ".order")
    check("N0-K9: the stub exited 0 (the control: the order below is not an artifact of a crash)", proc.returncode == 0,
          f"exit {proc.returncode}: " + err.decode("utf-8", "replace")[-200:])
    check_eq("N0-K9: the stub copied the driver's state AFTER it read stdin: the content written before the prompt, marked after_stdin",
             (seen.read_text(encoding="utf-8") if seen.is_file() else None, order.read_text(encoding="utf-8") if order.is_file() else None),
             ("in_flight written", "after_stdin"))
    crash_seen = tmp / "k9-crash-seen.json"
    crash_env = {k: v for k, v in env.items() if k != "STUB_CONTROL"}          # the stub dies on its first line, before any stdin
    crash_env["CENSUS_SNAPSHOT_TO"] = str(crash_seen)
    crashed = subprocess.run([sys.executable, "-B", str(stub)], input=b"the prompt", capture_output=True, env=crash_env, timeout=60)
    crash_order = crash_seen.with_name(crash_seen.name + ".order")
    check_eq("N0-K9 edge: a stub that never reads stdin copies at exit, and says so (at_exit)",
             (crashed.returncode != 0, crash_order.read_text(encoding="utf-8") if crash_order.is_file() else None), (True, "at_exit"))
    base = {"flows": [], "not_scanned": []}
    for taken in ("at_exit", "before_stdin", "not_taken"):
        failures = SC.census_failures({**base, "snapshots": [{"flow": "F3", "world": "A", "name": "driver-state@in_flight", "taken": taken}]})
        check("N0-K9: a snapshot taken " + taken + " fails the census as `not observed`, naming flow, world and when, never a pass",
              len(failures) == 1 and "flow F3 in world A" in failures[0] and taken in failures[0] and "not observed" in failures[0], str(failures))
    check_eq("N0-K9 control: a snapshot taken after_stdin is no failure",
             SC.census_failures({**base, "snapshots": [{"flow": "F3", "world": "A", "name": "n", "taken": "after_stdin"}]}), [])


def k10_baseline_validation(tmp: Path) -> None:
    """`load_baseline` refuses a node word outside the legend and an inventory row outside `writers` (t-348 finding 2)."""
    shipped = json.loads(SC.BASELINE_FILE.read_text(encoding="utf-8"))
    loaded = SC.load_baseline()
    check("N0-K10 control: the shipped baseline loads (rows, legend and writers agree)", loaded is not None and len(loaded["rows"]) == len(shipped["rows"]))
    check_eq("N0-K10 control: a missing baseline file is still None (E9), not a refusal", SC.load_baseline(tmp / "no-such-baseline.json"), None)

    def refused(label: str, edit) -> str:
        data = copy.deepcopy(shipped)
        edit(data)
        path = tmp / "k10-baseline.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        try:
            SC.load_baseline(path)
            return ""
        except ValueError as exc:
            return str(exc)

    rid = shipped["rows"][0]["id"]
    said = refused("row leaves_at", lambda d: d["rows"][0].__setitem__("leaves_at", "N22"))
    check("N0-K10a: a row with a `leaves_at` outside the legend (planted `N22`) is refused, naming the row and the word",
          rid in said and "'N22'" in said and "leaves_at_legend" in said, said[:300])
    said = refused("row inventory_row", lambda d: d["rows"][0].__setitem__("inventory_row", "#99"))
    check("N0-K10b: a row with an `inventory_row` outside `writers` (planted `#99`) is refused, naming the row and the row id",
          rid in said and "'#99'" in said and "`writers`" in said, said[:300])
    said = refused("file_writers leaves_at", lambda d: d["file_writers"][0].__setitem__("leaves_at", "N-two"))
    check("N0-K10a: a `file_writers` entry with a `leaves_at` outside the legend is refused as well, naming the entry and the word",
          "file_writers entry" in said and "'N-two'" in said, said[:300])
    said = refused("file_writers inventory_row", lambda d: d["file_writers"][0].__setitem__("inventory_row", "#98"))
    check("N0-K10b: a `file_writers` entry with an `inventory_row` outside `writers` is refused as well", "'#98'" in said, said[:300])
    said = refused("writer leaves_at", lambda d: d["writers"]["#26"].__setitem__("leaves_at", "N9"))
    check("N0-K10a: a writer whose `leaves_at` is outside the legend is refused, naming the writer", "writer #26" in said and "'N9'" in said, said[:300])
    said = refused("empty leaves_at", lambda d: d["rows"][0].__setitem__("leaves_at", ""))
    check("N0-K10a edge: a row with an empty `leaves_at` is refused (a debt names its node)", rid in said and "names no node" in said, said[:300])
    check_eq("N0-K10 control: the legend itself holds every word the shipped rows use (nothing was added to make the check pass)",
             sorted({r["leaves_at"] for r in shipped["rows"]} - set(shipped["leaves_at_legend"])), [])


NEW_WRITERS = {"#26": ("telemetry_hook.py", "def _write_pretool_receipt"), "#27": ("telemetry_hook.py", "def _write_package_receipt"),
               "#28": ("host_capabilities.py", "def record("), "#29": ("case_versions.py", '"path": str(target.resolve())')}


def k11_writer_map(census: dict, baseline: dict) -> None:
    """The writers t-348 found missing from the map (finding 3): present, each with the reason no flow reaches it, listed by the
    census as not exercised, and each still at the place the map names."""
    writers = baseline.get("writers") or {}
    for inv, (script, needle) in NEW_WRITERS.items():
        entry = writers.get(inv) or {}
        source = (SC.PACKAGE / "scripts" / script).read_text(encoding="utf-8") if (SC.PACKAGE / "scripts" / script).is_file() else ""
        check(f"N0-K11: writer {inv} is in the map with a site, a node and the reason it is not exercised",
              bool(entry.get("site")) and entry.get("leaves_at") in baseline["leaves_at_legend"] and entry.get("produces") == []
              and bool(entry.get("not_exercised")), str(entry)[:200])
        check(f"N0-K11: writer {inv} still sits where the map says ({script}: `{needle}`)", needle in source and script.split(".")[0] in entry.get("site", ""),
              f"{script} has the text: {needle in source}")
    listed = {n["inventory_row"] for n in census["not_exercised"]}
    check_eq("N0-K11: the census lists all four as not exercised (a writer no flow reaches is MISSED, never clean)",
             sorted(set(NEW_WRITERS) & listed), sorted(NEW_WRITERS))
    without = copy.deepcopy(baseline)
    for inv in NEW_WRITERS:
        without["writers"].pop(inv, None)
    check_eq("N0-K11 control: with the four entries removed from a scratch copy, the census no longer lists them",
             sorted(set(NEW_WRITERS) & {n["inventory_row"] for n in SC.not_exercised(census, without)}), [])


def k12_notes(census: dict, tmp: Path) -> None:
    """The hand-written sections live in a notes file the report appends verbatim (t-348 finding 4)."""
    notes = tmp / "k12-notes.md"
    notes.write_text("## K12 planted notes heading\n\nA line of the notes.\n\n## A second heading\n", encoding="utf-8")
    shown = SC.render_markdown(copy.deepcopy(census), notes_path=notes)
    check("N0-K12: the report contains the notes file verbatim (its first heading and the whole text)",
          "## K12 planted notes heading" in shown and notes.read_text(encoding="utf-8") in shown, shown[-300:])
    check("N0-K12: ... after the generated sections (the failures section comes first)",
          0 <= shown.find("## Failures") < shown.find("## K12 planted notes heading"))
    absent = SC.render_markdown(copy.deepcopy(census), notes_path=tmp / "no-such-notes.md")
    check("N0-K12 edge: a missing notes file is one line in the report, not silence",
          absent.count("No notes file") == 1 and "K12 planted" not in absent and absent.rstrip().splitlines()[-1].startswith("No notes file"), absent[-300:])
    if SC.NOTES_FILE.is_file():
        real = SC.NOTES_FILE.read_text(encoding="utf-8")
        first = next((line for line in real.splitlines() if line.startswith("#")), "")
        check("N0-K12: the shipped notes file's first heading is in the report this census renders", bool(first) and first in SC.render_markdown(copy.deepcopy(census)),
              f"first heading: {first!r}")
    else:
        print(f"INFO: N0-K12 the shipped notes file {SC.NOTES_FILE.name} is absent here (a package copied alone has none)")


def k6_size_cap(tmp: Path) -> None:
    keys = SC.load_keys()
    det = SC.make_detector("A", tmp)
    token = SC.WORLDS["A"]["project"].encode()
    at = tmp / "at-the-cap.txt"
    at.write_bytes(b"x" * (SC.SIZE_CAP - 16) + token + b"y" * (16 - len(token)))
    beyond = tmp / "beyond-the-cap.txt"
    beyond.write_bytes(at.read_bytes() + b"z")
    check_eq("N0-K6: the cap is 8 MiB", SC.SIZE_CAP, 8 * 1024 * 1024)
    check_eq("N0-K6: the file of exactly 8 MiB is the size the test means", at.stat().st_size, SC.SIZE_CAP)
    got = SC.scan_file(at, det, keys)
    check_eq("N0-K6 AT: a file of exactly 8 MiB with the canary in its last 16 bytes is scanned and the hit found",
             (got.not_scanned, sorted(h[1] for h in got.hits)), (None, ["project_root"]))
    over = SC.scan_file(beyond, det, keys)
    check("N0-K6 BEYOND: a file of 8 MiB + 1 byte is not scanned, with its size in the reason", bool(over.not_scanned) and str(SC.SIZE_CAP + 1) in over.not_scanned
          and not over.hits, str(over.not_scanned))
    res = SC.FlowResult("unit", "A")
    res.ran, res.exit = True, 0
    SC._absorb(res, "<PROJECT>/beyond-the-cap.txt", "T", None, over, beyond.stat().st_size)
    census = SC.assemble({"A": {"unit": res}}, {}, keys)
    failures = SC.census_failures(census)
    check("N0-K6 BEYOND: ... and it FAILS the run, naming the file: an unscanned file is never reported clean (E8)",
          len(failures) == 1 and "beyond-the-cap.txt" in failures[0] and "never clean" in failures[0], str(failures))
    check_eq("N0-K6 control: a file over the cap that a flow produced is listed under not_scanned of census.json",
             [(n["file"], n["bytes"]) for n in census["not_scanned"]], [("<PROJECT>/beyond-the-cap.txt", SC.SIZE_CAP + 1)])
    gone = SC.scan_file(tmp / "does-not-exist.txt", det, keys)
    check("N0-K6 edge: a file that cannot be read is not scanned either, and says so", bool(gone.not_scanned) and "unreadable" in gone.not_scanned,
          str(gone.not_scanned))


# --- the sections that read the census ---------------------------------------------------------------------------

def k1_green(census: dict, verdict: dict) -> None:
    flows = census["flows"]
    bad = [f"{f['id']}/{f['world']}: ran={f['ran']} exit={f['exit']} files={f['files']}" for f in flows
           if not (f["ran"] and f["exit"] == 0 and f["files"] >= 1)]
    check_eq("N0-K1: every flow ran in every world with exit 0 and at least one artifact (E13)", bad, [])
    check_eq("N0-K1: nine flows in each of A, A2 and B", sorted((f["world"], len([1 for g in flows if g["world"] == f["world"]])) for f in flows if f["id"] == "F1"),
             [("A", 9), ("A2", 9), ("B", 9)])
    check_eq("N0-K1: nothing was left unscanned", census["not_scanned"], [])
    check_eq("N0-K1: green against the baseline: no hit outside it, no stale row", verdict["lines"], [])
    for line in counts_text(census):
        print("INFO: " + line)
    tree = census["tree"]
    uncommitted = tree.get("uncommitted_package_files")
    check("E14: the tree's uncommitted package files are recorded in census.json (a list, or the reason it is unknown)",
          isinstance(uncommitted, list) or bool(tree.get("unknown")), str(tree)[:200])
    print(f"INFO: E14 tree.uncommitted_package_files: {len(uncommitted) if uncommitted is not None else 'unknown: ' + str(tree.get('unknown'))}")
    patterns = [h["file"] + h["pointer"] for h in census["hits"]]
    check("N0-K1: no hit names a canary token or the arena in its file or pointer pattern (the patterns are world-independent)",
          not any(t.lower() in p.lower() for p in patterns for t in SC.canary_tokens().values()) and not any(SC.ARENA_PREFIX in p for p in patterns))


def k3_ratchet(census: dict, baseline: dict, tmp: Path) -> None:
    """Both directions, on a scratch copy of the baseline (the shipped file is never touched)."""
    rows = baseline["rows"]
    if not rows:
        check("N0-K3: the baseline has rows to delete (an empty baseline cannot prove the ratchet)", False, "no rows")
        return
    scratch = tmp / "baseline-copy.json"
    scratch.write_text(json.dumps(baseline), encoding="utf-8")
    copy_rows = json.loads(scratch.read_text(encoding="utf-8"))
    control = SC.evaluate(copy.deepcopy(census), copy_rows)
    check_eq("N0-K3 control: the unchanged copy of the baseline is green", control["lines"], [])
    victim = copy_rows["rows"].pop(len(rows) // 2)
    red = SC.evaluate(copy.deepcopy(census), copy_rows)
    text = "\n".join(red["lines"])
    check("N0-K3: a deleted baseline row turns the run red, naming that row's identity (flow, file, pointer, fact)",
          all(str(part) in text for part in (victim["flow"], victim["file"], victim["fact"])) and "new hit" in text
          and (victim["pointer"] in text or not victim["pointer"]), text[:400])
    check_in("N0-K3: ... and the writer, so the one who reads it knows where to look", "writer ", text)
    stale_row = {"id": "B-999", "flow": "F9", "file": "<PROJECT>/qa-factory/no-such-writer.json", "pointer": "/gone", "fact": "project_root",
                 "inventory_row": "#1", "leaves_at": "N2"}
    copy_rows = json.loads(scratch.read_text(encoding="utf-8"))
    copy_rows["rows"].append(stale_row)
    red = SC.evaluate(copy.deepcopy(census), copy_rows)
    text = "\n".join(red["lines"])
    check("N0-K3: an added stale row turns the run red with 'stale baseline row', naming its id and identity",
          "stale baseline row B-999" in text and "no-such-writer.json" in text and "/gone" in text, text[:400])
    check_eq("N0-K3: the stale row is the only complaint (the rest of the baseline still matches)", len(red["lines"]), 1)
    gone = SC.evaluate(copy.deepcopy(census), None)
    check("E9: no baseline at all is never green: every hit is new", len(gone["new"]) == census["counts"]["total"] and gone["lines"], str(len(gone["lines"])))
    check_eq("N0-K3: the shipped baseline file was not touched", json.loads(SC.BASELINE_FILE.read_text(encoding="utf-8")), baseline)
    rewritten = SC.build_baseline(copy.deepcopy(census), baseline)
    check_eq("--write-baseline control: the rows built from this census are the rows the shipped baseline holds (identity, node, row)",
             sorted((SC.identity(r), r["inventory_row"], r["leaves_at"]) for r in rewritten["rows"]),
             sorted((SC.identity(r), r["inventory_row"], r["leaves_at"]) for r in rows))
    check("N0-K3: every baseline row names the node that removes it and the inventory row it belongs to (a list of debts, FR-58)",
          all(r.get("leaves_at") and r.get("inventory_row") for r in rows), str([r["id"] for r in rows if not (r.get("leaves_at") and r.get("inventory_row"))]))


def k4_controls(census: dict) -> None:
    produced = census["_produced"]
    manifest = "<PROJECT>/qa-factory/install-manifest.json"
    check("N0-K4 control: F5 wrote the install manifest (the zero below is not an absence of the file)", manifest in produced, str(len(produced)))
    manifest_hits = [h for h in census["hits"] if h["flow"] == "F5" and h["file"] == manifest]
    check_eq("N0-K4: the F5 install manifest (#22) has 0 hits", manifest_hits, [])
    f1 = [h for h in census["hits"] if h["flow"] == "F1" and h["pointer"].endswith("/payload/known_paths/project_root")]
    check("N0-K4: F1 has at least one hit at /payload/known_paths/project_root (#1: initialize stores the project's place)",
          len(f1) >= 1 and all(h["fact"] == "project_root" for h in f1), str(f1[:2]))
    f3 = [h for h in census["hits"] if h["flow"] == "F3" and h["fact"] == "pid"]
    check("N0-K4: F3's in-flight snapshot gives a pid hit (#25: a process id in driver-state.json)",
          any("in_flight" in h["file"] and h["detector"] == "key" for h in f3), str(f3[:2]))
    check_eq("N0-K9: the in-flight snapshot of F3 was taken after the stub read its stdin in A, A2 and B (observed, not assumed)",
             sorted((s["flow"], s["world"], s["taken"]) for s in census.get("snapshots") or []),
             [("F3", "A", "after_stdin"), ("F3", "A2", "after_stdin"), ("F3", "B", "after_stdin")])


def k5_differential(census: dict) -> None:
    fp = census["controls"]["package_fingerprint"]
    check("N0-K5 control: package_fingerprint is equal across A, A2 and B (the package copies are the same bytes)",
          fp["equal"] and len(fp["A"]) == 64, str(fp))
    entries = [d for d in census["differential"] if d["pointer"].endswith("/input_hash")]
    check("N0-K5: input_hash differs across A and B on the same task bytes (#3 includes the interpreter)", len(entries) >= 1,
          str([(d["flow"], d["pointer"]) for d in census["differential"]][:6]))
    print("INFO: N0-K5 input_hash A vs B: " + "; ".join(f"{d['flow']} {d['pointer']} {str(d['a'])[:12]}.. vs {str(d['b'])[:12]}.." for d in entries[:3]))
    wrongly = [d for d in census["differential"] if d["pointer"].endswith("package_fingerprint")]
    check_eq("N0-K5: package_fingerprint is nowhere in the differential (the control would otherwise be a hit)", wrongly, [])
    check("N0-K5: the noise set is not empty and holds time-stamped keys (a hash over timestamps differs between two runs of A)",
          len(census["noise"]) >= 1, str(census["noise"][:3]))


def k7_cli(census: dict, baseline: dict, tmp: Path) -> None:
    for argv, flag in ((["--report", ""], "--report"), (["--report", str(tmp)], "--report"), (["--markdown", ""], "--markdown"),
                       (["--baseline", str(tmp)], "--baseline")):
        try:
            parse_args(argv)
            raised = ""
        except CliError as exc:
            raised = str(exc)
        check(f"N0-K7: {argv[0]} {argv[1] and 'an existing folder' or 'an empty value'} is refused, naming the flag and what to give",
              flag in raised and "file" in raised, raised)
    out = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--report", ""], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=120)
    check("N0-K7: the real command line refuses `--report \"\"` at once (exit 2, the flag named on stderr, no census run)",
          out.returncode == 2 and "--report" in out.stderr and "census:" not in out.stdout, f"{out.returncode} {out.stderr[:200]}")
    odd = tmp / ("spa ce " + "".join(chr(c) for c in (0x43F, 0x440, 0x438, 0x43C, 0x435, 0x440)))      # a folder with a space and Cyrillic letters
    target = odd / "census.json"
    code = apply_flags(argparse.Namespace(report=str(target), markdown=str(odd / "census.md"), write_baseline=False, baseline=None),
                       copy.deepcopy(census), tmp / "unused-baseline.json", baseline)
    check_eq("N0-K7: --report into a folder with spaces and Cyrillic letters is written", (code, target.is_file()), (0, True))
    if target.is_file():
        written = json.loads(target.read_text(encoding="utf-8"))
        check_eq("N0-K7: ... a census_version 1 document with the schema's keys",
                 (written["census_version"], sorted(k for k in ("flows", "hits", "counts", "not_exercised", "differential", "noise",
                                                                 "not_scanned", "unrecognised_files", "tree", "canaries") if k in written)),
                 (1, sorted(["flows", "hits", "counts", "not_exercised", "differential", "noise", "not_scanned", "unrecognised_files",
                             "tree", "canaries"])))
        check("N0-K7: ... with no internal key and no machine path of this run (`_produced` is left out)", not any(k.startswith("_") for k in written))
    check("N0-K7: the Markdown companion is written too", (odd / "census.md").is_file())
    scratch = tmp / "refused-baseline.json"

    def write_baseline(source: dict, base) -> tuple:
        """`--write-baseline` over a census: (exit code, what it said on stderr)."""
        said = io.StringIO()
        with contextlib.redirect_stderr(said):
            code = apply_flags(argparse.Namespace(report=None, markdown=None, write_baseline=True, baseline=str(scratch)), source, scratch, base)
        return code, said.getvalue()

    broken = copy.deepcopy(census)
    broken["flows"][0] = dict(broken["flows"][0], exit=1)
    before = scratch.exists()
    code, said = write_baseline(broken, baseline)
    check_eq("N0-K7: --write-baseline refuses while a flow exited non-zero (nothing is written)", (code, scratch.exists(), before), (2, False, False))
    check_in("N0-K7: ... and says which flow and why", "exited 1", said)
    unscanned = copy.deepcopy(census)
    unscanned["not_scanned"] = [{"flow": "F1", "world": "A", "file": "<PROJECT>/big.bin", "bytes": SC.SIZE_CAP + 1, "reason": "size"}]
    code, said = write_baseline(unscanned, baseline)
    check_eq("N0-K7: --write-baseline refuses while a file is unscanned", (code, scratch.exists()), (2, False))
    check_in("N0-K7: ... and names the file", "big.bin", said)
    empty_flow = copy.deepcopy(census)
    empty_flow["flows"][0] = dict(empty_flow["flows"][0], files=0)
    code, said = write_baseline(empty_flow, baseline)
    check_eq("N0-K7: --write-baseline refuses while a flow produced nothing", (code, scratch.exists()), (2, False))
    check_in("N0-K7: ... and says a flow that produced nothing is not 'no hits'", "produced no file", said)
    unmapped = {k: v for k, v in baseline.items() if k != "file_writers"}
    code, said = write_baseline(copy.deepcopy(census), unmapped)
    check_eq("N0-K7: --write-baseline refuses a hit that no `file_writers` entry maps to a node (a row with no node is no debt)",
             (code, scratch.exists()), (2, False))
    check_in("N0-K7: ... and names the hit (flow, file, pointer, fact)", "file_writers", said)
    code, said = write_baseline(copy.deepcopy(census), baseline)
    check_eq("N0-K7 control: the same census with the real map writes the baseline", (code, scratch.is_file(), said), (0, True, ""))
    if scratch.is_file():
        check_eq("N0-K7 control: ... and the file it wrote is the shipped baseline's rows",
                 [(r["flow"], r["file"], r["pointer"], r["fact"]) for r in json.loads(scratch.read_text(encoding="utf-8"))["rows"]],
                 [(r["flow"], r["file"], r["pointer"], r["fact"]) for r in baseline["rows"]])


def main(argv=None) -> int:
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
    except CliError as exc:
        print(f"test_state_portability: {exc}", file=sys.stderr)
        return 2
    baseline_path = Path(args.baseline) if args.baseline else SC.BASELINE_FILE
    tmp = Path(tempfile.mkdtemp(prefix="qa-state-portability-"))
    try:
        k8_tokens()
        e9_missing_detector(tmp)
        k2_planted(tmp)
        k6_size_cap(tmp)
        k9_snapshot_order(tmp)
        k10_baseline_validation(tmp)
        try:
            baseline = SC.load_baseline(baseline_path)
        except ValueError as exc:
            check("E9: the baseline file is readable", False, str(exc))
            baseline = None
        started = time.monotonic()
        try:
            census = SC.run_census(progress=lambda m: print("INFO: " + m, flush=True))
        except SC.DetectorMissing as exc:
            check("N0-K1: the key list is present (E9)", False, str(exc))
            census = None
        except Exception as exc:         # a world that could not be built is a failure of the census, never a pass
            check("N0-K1: the census ran (a world could not be built or scanned)", False, f"{exc.__class__.__name__}: {exc}")
            census = None
        if census is not None:
            print(f"INFO: the census took {time.monotonic() - started:.0f} s (flows run {SC.WORKERS} at a time)")
            verdict = SC.evaluate(census, baseline)
            k1_green(census, verdict)
            if baseline is not None:
                k3_ratchet(census, baseline, tmp)
            k4_controls(census)
            k5_differential(census)
            k12_notes(census, tmp)
            if baseline is not None:
                k11_writer_map(census, baseline)
            if baseline is not None:
                k7_cli(census, baseline, tmp)
            if verdict["lines"]:
                print("RATCHET:")
                for line in verdict["lines"][:40]:
                    print("  " + line)
            code = apply_flags(args, census, baseline_path, baseline)
            check_eq("the report flags did what they were asked", code, 0)
    finally:
        cleanup(tmp)
    finish("test_state_portability")


if __name__ == "__main__":
    sys.exit(main())
