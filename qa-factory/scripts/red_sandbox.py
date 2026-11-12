"""Prepare an isolated exact-byte test tree; never mutate or reset the author's tree.

CLI: red_sandbox.py --repo ROOT --destination EMPTY --request mutations.json
     red_sandbox.py --verify-receipt R --request results.json [--baseline unmutated.json]
                    [--task-root T]
     red_sandbox.py --probe --repo ROOT --request mutations.json --task-root T
                    [--dispatch ID] [--destination DIR]
     red_sandbox.py --diagnostic --repo ROOT --request diag.json --task-root T [--dispatch ID]
`--diagnostic` is the failure analyst's ONE run of a red test without the asserts of the Thens that wait behind its
red one, in a copy (see `diagnostic`); it publishes nothing and writes `evidence/diagnostic-<label>.json` alone.
The request lists extra_files and mutations {path,before_sha256,replacement_utf8}, and may opt into
dependency provisioning inside the clone with `sandbox_setup: [{"kind": ..., "cwd": ..., <pin fields>}]`
- the kinds are rows of references/sandbox-setup.json (`provision_dependencies`); the install runs ONLY in
the clone this `prepare` made, before any mutation is written, and the total time of the installs of one
probe call is capped (`sandbox.install_timeout_s`, default 540 s). A `node_modules` directory ABOVE the
clone's `cwd` (a parent of the clone) is not looked at.
A mutation may pin the pytest `node_id` (or `node_ids`) of its instance; with
`collect: {"argv": [<test command without ids>], "cwd": "<dir inside the sandbox>"}` in the
request those ids are checked against a collect inside the prepared sandbox — see
`check_node_ids`.
Run the scoped red request in the returned sandbox, then submit framework diagnostics
and critic semantic verdict with the returned original and mutation hashes.
`--baseline` is the SAME instances run unmutated; it is what tells a surviving test from a
mutation that changed nothing, and it counts on BOTH branches, publication included.

The factory's own generated state is neither copied nor compared (`is_generated`; it is only
named in the receipt's `volatile` list), and a
target the mutation did not actually change is a PROBE defect, never a surviving test.

`--probe` is the whole sequence in one call: ask, prepare, run the mutated instances
(`run_suite.py --mine ... --sandbox-root <clone>`, subprocess — the runner is another package's
file and is edited at the same time, so it is only ever called, never imported; the run
directory under the clone is the profile's own, worked out by the runner), verify, record, publish the
sensitivity receipts and their manifest bindings, clean the sandbox, print one JSON. The
request adds one field to what prepare already reads: `cases` — the case ids `--mine`
selects (a mutation's own `instance_id` is the finer identity `verify()` checks a result
against, never what selects a run). The critic still writes only that one file.

What it asks first, before any sandbox exists (t-043 C): is every target placed in the manifest; was
it already probed over these bytes (`already_probed`: the whole request is answered, nothing is
launched or written); does the author's own green run of it stand as the unmutated baseline
(`execution_request.fresh_evidence` - no green, `not_executed`; a story that cannot say gives today's
own baseline). Then ONE launch per distinct case among the targets, selecting only their nodes, and
`work/probes/product/<stem>.json` per target: the verdict, on record for the next repeat.

A run's report is read by `reporters.read_rows` with the reporter the run's own summary names
(pytest, junit-xml or trx). Every row is bound by the `report_test_id` the JOB REQUEST of its own
run carries for the instance, EXACTLY (`bind_row`); a request that carries none falls back, for a
pytest command only, to the pinned node id's tail. A mutated target no report row answers for is
`probe_defect` (the probe's own run); a baseline target with no row is `not_executed` (exit 1);
neither is ever `survived`. Only `.py::` nodes are passed as `--node-id`; a case holding any other
node is launched whole. The failure site of a `junit-xml` row of a runner that is not pytest is not
read yet (B-337): that proof is `incomplete` (exit 1) with the reason. One path takes one mutation:
two differing replacements of it are refused by `prepare` (B-314).
"""
import argparse
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import contract  # noqa: E402
import proof_level  # noqa: E402
import reporters  # noqa: E402
import runtime_paths  # noqa: E402
from event_store import atomic_json  # noqa: E402
from event_store import content_hash  # noqa: E402
from role_cli import REPAIR_MARKER  # noqa: E402
import hooklib  # noqa: E402
from hooklib import read_json, ref, sorted_paths  # noqa: E402


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inside(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or path == root.resolve():
        raise ValueError("sandbox path escapes its root")
    return path


# `prepare()` hashed every `git ls-files` path and `verify()` then raised "main-tree
# bytes changed during probe" — because the factory's OWN dashboard is tracked (onboarding
# commits it on purpose) and carries a `Generated <time>` stamp that a PostToolUse hook
# rewrites every minute. These paths are generated BY the factory, so a change in them proves
# nothing about the author's tree; they are named in the receipt but neither copied into the
# sandbox nor compared, and a mutation aimed at one of them is refused. Project-agnostic: it is the factory's own state
# directory, not anything of the project under test.
#
# Live story artifacts (`artifact_root`, default `qa-factory/artifacts/`) are mutable factory
# state in the same way: left as probe INPUTS they took part in the restoration comparison and
# a lock or event file rewritten by the running factory looked like a changed author tree. The
# location is the project's own choice (`hooklib.artifact_root`), so it is resolved per repo by
# `artifact_prefixes`, never hard-coded; the default below only serves a caller that passes
# nothing.
#
# The tracked journal, the ledger, the coverage map and the approvals moved from `state/` to
# `records/` (0.8.1): a journal append during a probe is the same live factory write, and left out
# of this set it read as "main-tree bytes changed". Both folders are built from `runtime_paths`
# (FR-37), so an old-layout project (its journal under `state/`), a new-layout one (`records/`) and
# one holding both are all covered, and a mutation aimed at either folder is refused.
STATE_PREFIX = f"{runtime_paths.HOME}/{runtime_paths.STATE}/"
RECORDS_PREFIX = f"{runtime_paths.HOME}/{runtime_paths.RECORDS}/"
DEFAULT_ARTIFACT_PREFIXES = ("qa-factory/artifacts/",)
VOLATILE_SUFFIXES = ("/factory-dashboard.html",)


def artifact_prefixes(repo) -> tuple:
    """The repo-relative prefix of this project's live story artifacts, or `()`.

    Resolved through `hooklib.artifact_root(root=repo)` - which never pins the process's project
    root. No readable config (or a config that does not parse / an unusable value) -> the
    default location. A location OUTSIDE the repo (absolute, or `..`) is not in the clone's input
    set at all, so it adds no prefix; the repo root itself would make every file volatile, so it
    adds none either."""
    try:
        from hooklib import artifact_root
        resolved = Path(artifact_root(root=Path(repo)))
    except Exception:  # unreadable / unparsable config, an unusable value: the default location
        return DEFAULT_ARTIFACT_PREFIXES
    try:
        relative = resolved.relative_to(Path(repo).resolve())
    except ValueError:  # outside the repo: not part of the clone's input set
        return ()
    if relative == Path("."):
        return ()
    return (relative.as_posix().rstrip("/") + "/",)


def is_generated(relative: str, live_prefixes=None) -> bool:
    """`live_prefixes` is what `artifact_prefixes(repo)` returned; None = the default
    location, so a caller that knows no repo keeps its old behaviour."""
    path = str(relative).replace("\\", "/")
    live = DEFAULT_ARTIFACT_PREFIXES if live_prefixes is None else tuple(live_prefixes)
    return (path.startswith((STATE_PREFIX, RECORDS_PREFIX) + live) or path.endswith(VOLATILE_SUFFIXES)
            or path == "factory-dashboard.html")


def repo_files(repo) -> set:
    """Tracked files PLUS untracked ones git does not ignore.

    The sandbox used to copy `git ls-files` only, so the test file the automator had just
    written — new, never `git add`ed — did not exist inside the probe, and the probe ran
    against the tests of the previous commit while reporting on the new ones. Ignored files
    stay out: they are build output, virtualenvs and caches, and the adapter provisions
    dependencies inside the disposable tree itself.
    """
    files: set = set()
    for argv in (["ls-files", "-z"], ["ls-files", "--others", "--exclude-standard", "-z"]):
        result = subprocess.run(["git", "-C", str(repo), *argv],
                                capture_output=True, check=True, timeout=30)
        files.update(set(result.stdout.decode("utf-8").split("\0")) - {""})
    return files


def pinned_ids(item) -> list:
    raw = item.get("node_ids") if isinstance(item.get("node_ids"), list) else []
    return [str(n) for n in ([item.get("node_id")] + list(raw)) if n]


class NodeIdMismatch(ValueError):
    def __init__(self, message, missing):
        super().__init__(message)
        self.missing = missing


class MutationConflict(ValueError):
    """Two mutations of one request rewrite the same file differently (B-314). A refusal of the
    request's own shape: the CLI answers it with exit 2, like the node-id refusal."""


def _mutation_label(number: int, item: dict) -> str:
    return f"mutations[{number}] (instance {item.get('instance_id') or 'not named'})"


def refuse_same_path(repo: Path, mutations: list) -> None:
    """One path takes one mutation. B-314: `prepare()` wrote each mutation in turn, so a second
    mutation of one path overwrote the first while BOTH targets stayed in the receipt, and a
    probe of two obligations proved one. Paths are compared as the filesystem does
    (`os.path.normcase` of the resolved path), so `a\\b`, `./a/b` and an absolute spelling are one
    path, and `A/B` is too where the filesystem ignores case. Identical replacements lose nothing
    and pass. `inside()` is the escape check and runs first, for every mutation."""
    first: dict = {}
    for number, item in enumerate(mutations):
        key = os.path.normcase(inside(repo, item["path"]))
        seen_at, seen = first.setdefault(key, (number, item))
        if seen is item or seen.get("replacement_utf8") == item.get("replacement_utf8"):
            continue
        raise MutationConflict(
            f"{_mutation_label(seen_at, seen)} and {_mutation_label(number, item)} both rewrite "
            f"{item['path']} with different text, and a sandbox holds one version of a file: the "
            "second would silently overwrite the first while both stay in the receipt as proved. "
            "Nothing was prepared. Run one probe per mutation (one request each), or merge the two "
            "into one combined replacement of that file under one instance. No person's word passes "
            f"this one: it would drop a mutation without anyone seeing it. {REPAIR_MARKER}.")


def _passed_by_person(task_root, message: str) -> str:
    """The person's recorded words when an S5 stage override covers this refusal, else ""."""
    if not task_root:
        return ""
    try:
        from waiver import split_overridden
        pipeline = json.loads((Path(task_root) / "pipeline.json").read_text(encoding="utf-8"))
        _, passed = split_overridden([message], pipeline, "S5")
    except (ImportError, OSError, ValueError):
        return ""
    return str(passed[0]["decision"]) if passed else ""


def check_node_ids(destination, request, mutations, task_root=None) -> dict:
    """Verify the pinned ids of a probe against a collect INSIDE the prepared sandbox.

    TP1-15045, job 071bcb794f4e10520240: the probe pinned `...[buffer-R3-vs-selected-R1]`,
    pytest-playwright collects it as `[chromium-buffer-R3-vs-selected-R1]`, pytest exited 4
    with `ERROR: not found` and the sandbox was burned on an id nothing had checked. An id
    with one real spelling is re-pinned in it (the role is not handed the factory's own
    bookkeeping); an id pytest does not collect fails the preparation with the nearest real
    ids, while the destination is still free to be prepared again. A collect that cannot
    answer — no dependencies in the disposable tree yet, a mutation that breaks an import —
    fails nothing: it is recorded, and the run itself will say the rest.
    """
    asked = [n for item in mutations for n in pinned_ids(item)]
    if not asked:
        return {"status": "no_pinned_ids"}
    spec = request.get("collect") if isinstance(request.get("collect"), dict) else {}
    if not spec.get("argv"):
        return {"status": "not_checked", "notes": [
            "the request pins node ids but carries no `collect` command; they were not verified"]}
    try:
        import node_ids
    except ImportError:
        return {"status": "not_checked", "notes": ["node_ids.py is not installed"]}
    cwd = (destination / str(spec.get("cwd") or ".")).resolve()
    if not (cwd == destination or cwd.is_relative_to(destination)) or not cwd.is_dir():
        raise ValueError("collect.cwd must be a directory inside the sandbox, relative to its root")
    argv = [str(a) for a in spec["argv"]]
    form, table_note = node_ids.runner_form(argv)    # the runner's row: one broken file does not hide the rest (AR-15)
    checked = node_ids.check_request(argv, str(cwd), asked, int(spec.get("timeout_s") or 180), form=form)
    if table_note:
        checked["notes"] = list(checked.get("notes") or []) + [table_note]
    if checked.get("collect_error"):
        return {"status": "collect_error", "notes": checked.get("notes") or [],
                "collect_error": checked["collect_error"]}
    notes = list(checked.get("notes") or [])
    if checked["missing"]:
        message = ("pinned node id not collected by pytest inside the sandbox: "
                   + node_ids.missing_sentence(checked["missing"]))
        words = _passed_by_person(task_root, message)
        if not words:
            raise NodeIdMismatch(
                message + ". Nothing was kept under the destination: pin the real id and "
                "prepare again. This is the probe's bookkeeping, not a defect of the test and "
                f"not the person's to repair. {REPAIR_MARKER}. Their word still passes it — "
                "the orchestrator "
                "records `waiver.py --task <id> --stage S5 --block \"not collected by pytest\" "
                "--words-file <file>`, then prepare again with `--task-root <task>`.",
                checked["missing"])
        notes.append(f"passed by a person's recorded decision: {words}")
    for item in mutations:
        if item.get("node_id"):
            item["node_id"] = checked["resolved"].get(str(item["node_id"]), item["node_id"])
        if isinstance(item.get("node_ids"), list):
            item["node_ids"] = [checked["resolved"].get(str(n), n) for n in item["node_ids"]]
    return {"status": "passed_by_person" if checked["missing"] else "verified",
            "resolved": checked["resolved"], "missing": checked["missing"], "notes": notes}


# --- dependency provisioning inside the clone (FB-27) --------------------------------------
# What a request may ask for inside its disposable clone is DATA (FR-13): one row per kind in
# references/sandbox-setup.json, read by `setup_kinds()` alone. A missing or broken table means NO
# kind is known - every `sandbox_setup` row is then refused by name, never run blind and never
# dropped quietly. The request chooses a kind, a folder and the pins; the command comes from the table.

SETUP_KINDS_FILE = ref("sandbox-setup.json")
SETUP_TAIL_CHARS = 500           # the tail of a failed command's output (as `probe` shows a runner's)
SETUP_MAX_TIMEOUT_S = 3600
INSTALL_BUDGET_S = 540           # all installs of ONE probe call; the role's Bash tool stops a call at 600 s
PIN_RE = re.compile(r"^[0-9a-f]{64}$")


class SetupRefused(ValueError):
    """The request's `sandbox_setup` (or the table it names) cannot be used: a fault of the call or of the
    factory, found BEFORE anything was installed. The CLI answers it with exit 2."""


class SetupFailed(ValueError):
    """The install command ran (or could not run) and did not establish its result: a fact about the machine
    or the files, never about the stand (D-0032: a missing dependency is a defect to repair, not an
    environment property to accept). Carries the exit code and the tail of the output."""

    def __init__(self, message, exit_code=None, output_tail=""):
        super().__init__(message)
        self.exit_code = exit_code
        self.output_tail = output_tail


def _component(name) -> bool:
    return (isinstance(name, str) and bool(name) and name not in (".", "..")
            and not any(sep in name for sep in ("/", "\\")))


def _argv_ok(argv) -> bool:
    return isinstance(argv, list) and bool(argv) and all(isinstance(a, str) and a for a in argv)


def _row_problem(row) -> str:
    """What is wrong with a table row (the schema of references/sandbox-setup.json), or ''."""
    if not isinstance(row, dict):
        return "the row is not an object"
    if not _argv_ok(row.get("argv")):
        return "argv (a non-empty list of non-empty strings)"
    platform_argv = row.get("platform_argv", {})
    if not isinstance(platform_argv, dict) or not all(_argv_ok(v) for v in platform_argv.values()):
        return "platform_argv ({os.name: argv})"
    env = row.get("env", {})
    if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        return "env ({str: str})"
    pins = row.get("pins")
    if not isinstance(pins, dict) or not pins or not all(_component(k) and isinstance(v, str) and v
                                                         for k, v in pins.items()):
        return "pins (a non-empty {file name: request field})"
    absent = row.get("must_not_preexist")
    if not isinstance(absent, list) or not absent or not all(_component(n) for n in absent):
        return "must_not_preexist (a non-empty list of names)"
    limit = row.get("timeout_s")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 0 < limit <= SETUP_MAX_TIMEOUT_S:
        return f"timeout_s (an integer from 1 to {SETUP_MAX_TIMEOUT_S})"
    receipt = row.get("receipt", {})
    if not isinstance(receipt, dict) or not all(isinstance(v, (str, int, float, bool)) or v is None
                                                for v in receipt.values()):
        return "receipt ({str: scalar})"
    return ""


def setup_kinds() -> tuple:
    """(kinds, problems) from references/sandbox-setup.json. `kinds` holds the rows that pass the schema;
    `problems` maps a broken row's kind to the field that is wrong, and '' to the file's own fault (it cannot
    be read, is not JSON, or has no `kinds` object - then there are NO kinds). The one reader (axis 16)."""
    table = read_json(SETUP_KINDS_FILE, kind=dict)
    kinds = table.get("kinds") if table else None
    if not isinstance(kinds, dict):
        return {}, {"": "references/sandbox-setup.json is unreadable; the kinds are none"}
    good, problems = {}, {}
    for kind, row in kinds.items():
        problem = _row_problem(row)
        if problem:
            problems[str(kind)] = problem
        else:
            good[str(kind)] = row
    return good, problems


def install_budget_s(repo) -> int:
    """The seconds ONE probe call may spend installing: `sandbox.install_timeout_s` of the project's
    config.json, 540 when the key is absent (a config that predates it). A value that is not a positive
    integer is refused by name - never replaced by the default behind the person's back."""
    config = read_json(Path(repo) / runtime_paths.HOME / "config.json", {}, kind=dict)
    value = (config.get("sandbox") or {}).get("install_timeout_s") if isinstance(config.get("sandbox"), dict) else None
    if value is None:
        return INSTALL_BUDGET_S
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SetupRefused(f"sandbox.install_timeout_s in qa-factory/config.json is {value!r}; it must be a positive "
                           f"whole number of seconds (the default is {INSTALL_BUDGET_S}). Fix or delete the key.")
    return value


def _unsupported(kind, kinds, problems) -> str:
    if isinstance(kind, str) and kind in problems:
        return f"row {kind} of references/sandbox-setup.json is malformed: {problems[kind]} (a factory defect)"
    if "" in problems:
        return problems[""]
    return (f"unsupported sandbox_setup kind {kind!r}; the kinds are {', '.join(sorted(kinds)) or 'none'}. A kind "
            "outside this table is a factory gap: probe without sandbox_setup (an import failure is reported "
            "incomplete) and file it in qa-factory/factory-backlog.md")


def _plan_row(spec, kinds, problems) -> dict:
    kind = spec.get("kind") if isinstance(spec, dict) else None
    if not isinstance(kind, str) or kind not in kinds:
        raise SetupRefused(_unsupported(kind, kinds, problems))
    row = kinds[kind]
    fields = {"kind", "cwd", *row["pins"].values()}
    if set(spec) - fields:
        raise SetupRefused(f"sandbox_setup row {kind}: {', '.join(sorted(set(spec) - fields))} is not a field of "
                           f"this kind (it takes {', '.join(sorted(fields))}). The command, its environment and "
                           "its limits come from references/sandbox-setup.json, never from the request")
    relative = spec.get("cwd")
    if (not isinstance(relative, str) or not relative or Path(relative).is_absolute()
            or relative.startswith(("/", "\\")) or ".." in Path(relative).parts):
        raise SetupRefused(f"sandbox_setup.cwd of {kind} must be a relative folder of the clone ('.' or 'e2e'), "
                           f"got {relative!r}")
    pins = {}
    for name, field in row["pins"].items():
        if not isinstance(spec.get(field), str) or not PIN_RE.match(spec[field]):
            raise SetupRefused(f"sandbox_setup row {kind} needs {field}: the sha256 (64 lowercase hex characters) "
                               f"of {name} in {relative}")
        pins[name] = (field, spec[field])
    argv = [str(a) for a in (row.get("platform_argv") or {}).get(os.name) or row["argv"]]
    return {"kind": kind, "row": row, "spec": spec, "cwd": relative, "pins": pins, "argv": argv,
            "timeout_s": row["timeout_s"]}


def plan_setup(request, budget_s=INSTALL_BUDGET_S) -> list:
    """The `sandbox_setup` rows of a request as a plan, checked for FORM and BUDGET alone - nothing here
    touches a file, so `prepare` calls it before it creates the clone (a wrong request costs no copy). No
    `sandbox_setup` (absent, null or []) is no plan and the table is not even read. `budget_s` is what the
    installs of this call may add up to: their `timeout_s` summed (the worst case) must not exceed it."""
    specs = request.get("sandbox_setup")
    if specs is None or specs == []:
        return []
    if not isinstance(specs, list):
        raise SetupRefused("sandbox_setup must be a list of {kind, cwd, <pin fields>} rows")
    kinds, problems = setup_kinds()
    planned, seen = [], set()
    for spec in specs:
        item = _plan_row(spec, kinds, problems)
        # the folder compares as a NORMALISED path ("e2e/" = "./e2e" = "e2e"; ".tools" is not "tools")
        key = (item["kind"], os.path.normcase(os.path.normpath(item["cwd"])))
        if key in seen:
            raise SetupRefused(f"sandbox_setup names {item['kind']} in {item['cwd']} twice; one install per kind and folder")
        seen.add(key)
        planned.append(item)
    worst = sum(item["timeout_s"] for item in planned)
    if worst > budget_s:
        raise SetupRefused(
            f"the installs of this call may take up to {worst} s ({', '.join(i['kind'] for i in planned)}) and one "
            f"probe call may spend {max(budget_s, 0):.0f} s on them: the Bash tool the critic runs the probe in stops a call at "
            "600 s, and an install cut off that way leaves a half-made clone and a running npm. Either raise "
            "`sandbox.install_timeout_s` in qa-factory/config.json (and run the probe in the background), or probe "
            "in two calls with fewer sandbox_setup rows each")
    return planned


def _clone_guard(root: Path) -> None:
    """I3 inside the function: an install runs only in the clone THIS `prepare` made and has not yet mutated.
    The clone says so in its own marker (`.qa-probe.json`, written by `prepare` before the copy): status
    `preparing`, `sandbox` equal to this folder, the folder outside the author's tree, and every mutation
    target still holding the author's bytes. Any other caller - a call on the author's tree, on a finished
    sandbox, on a mutated clone - is refused (a direct call cannot install anywhere `prepare` did not)."""
    marker = read_json(root / ".qa-probe.json", {}, kind=dict)
    if marker.get("status") != "preparing" or marker.get("sandbox") != str(root):
        raise SetupRefused(f"{root} is not a clone this probe is preparing (no `preparing` marker naming it): "
                           "dependencies are installed only in the throwaway clone, never anywhere else")
    author = Path(str(marker.get("repo") or "")).resolve() if marker.get("repo") else None
    if author is None or root == author or root.is_relative_to(author) or author.is_relative_to(root):
        raise SetupRefused(f"{root} is not disjoint from the author's tree; dependencies are never installed there")
    for target in marker.get("targets") or []:
        path = root / str(target.get("path"))
        if not path.is_file() or digest(path) != target.get("before_sha256"):
            raise SetupRefused(f"{target.get('path')} in the clone is already mutated (or missing): dependencies are "
                               "installed BEFORE any mutation is written, so the install never sees the broken product")


def _check_row_in_clone(root: Path, item: dict) -> Path:
    """The files of the clone this row stands on, before it runs: its folder, its pinned files (a lock file
    that was not committed or is git-ignored is not copied), and a fresh place for what it creates."""
    cwd = root if item["cwd"] == "." else inside(root, item["cwd"])
    if not cwd.is_dir() or cwd.is_symlink():
        raise SetupRefused(f"sandbox_setup.cwd {item['cwd']} is not a materialized folder of the clone")
    for name, (field, pin) in item["pins"].items():
        path = cwd / name
        if path.is_symlink() or not path.is_file():
            raise SetupRefused(f"{name} is not in {item['cwd']} of the clone: the install `{' '.join(item['argv'])}` "
                               "needs it as a pinned file, and a file that is not committed (or is git-ignored) is not copied")
        if digest(path) != pin:
            raise SetupRefused(f"sandbox dependency pin mismatch: {name} ({field}) differs from the file in the clone")
    for name in item["row"]["must_not_preexist"]:
        if os.path.lexists(cwd / name):   # a dangling link or a Windows junction counts
            raise SetupRefused(f"sandbox dependencies must be freshly provisioned: {name} already exists in "
                               f"{item['cwd']} (a link to a shared tree is no fresh install)")
    return cwd


def _not_started_words(item: dict, exc) -> str:
    """Why the install program did not start, in the cause's own words (`errno` and `strerror` of the OSError
    `run_bounded` chained). "Not on PATH" is said only for ENOENT - a refusal to execute (permission, a file that
    is no program, a vanished folder) is reported as what the operating system said, never as a guessed cause
    (FR-41). Either way it is a defect of the machine, not a property of the stand (D-0032)."""
    cause = exc.__cause__ if isinstance(exc.__cause__, OSError) else None
    program = item["argv"][0]
    if cause is None or cause.errno is None:
        said, why = str(exc), f"{program} could not be launched"
    else:
        said = f"{errno.errorcode.get(cause.errno, cause.errno)}: {cause.strerror}"
        why = (f"{program} is not on PATH of this machine" if cause.errno == errno.ENOENT
               else f"the operating system refused to run {program} here")
    return (f"sandbox {item['kind']} could not be started: {said} ({why}: a defect of the machine, "
            "not a property of the stand)")


def _run_install(item: dict, cwd: Path) -> None:
    """Run the row's command in the clone, bounded; a non-zero code, a timeout or a program that cannot start
    is `SetupFailed` carrying the code and the tail."""
    import node_ids
    env = {**os.environ, **{str(k): str(v) for k, v in (item["row"].get("env") or {}).items()}}
    try:
        code, raw = node_ids.run_bounded(item["argv"], cwd, env, item["timeout_s"])
    except node_ids.BoundedRunError as exc:
        if exc.kind == "timeout":
            raise SetupFailed(f"sandbox {item['kind']} timed out after {item['timeout_s']} s; its process tree was "
                              "killed and the clone is removed") from None
        raise SetupFailed(_not_started_words(item, exc)) from exc
    if code:
        text = raw.decode("utf-8", errors="replace").strip()
        tail = text if len(text) <= SETUP_TAIL_CHARS else "..." + text[-SETUP_TAIL_CHARS:]
        raise SetupFailed(f"sandbox {item['kind']} failed (exit {code}); no tests launched. Output: {tail}",
                          exit_code=code, output_tail=tail)


def _post_check(root: Path, item: dict, cwd: Path) -> dict:
    """Exit 0 alone does not establish readiness (FR-18): what the command was to create must exist as a real
    folder inside the clone, and the pinned inputs must still hold the pinned bytes."""
    for name in item["row"]["must_not_preexist"]:
        made = cwd / name
        if made.is_symlink() or not made.is_dir() or not made.resolve().is_relative_to(root):
            raise SetupFailed(f"sandbox {item['kind']} exited 0 but {name} was not created in {item['cwd']} "
                              "as a folder of the clone: exit 0 alone cannot establish readiness", exit_code=0)
    if any(digest(cwd / name) != pin for name, (_field, pin) in item["pins"].items()):
        raise SetupFailed(f"sandbox {item['kind']} changed pinned input: the install rewrote a file it was pinned to",
                          exit_code=0)
    return {**(item["row"].get("receipt") or {}), "kind": item["kind"], "cwd": item["cwd"], "status": "ready",
            **{field: pin for _name, (field, pin) in item["pins"].items()}, "argv": item["argv"]}


def provision_dependencies(destination, request, planned=None):
    """Opt-in, lock-pinned dependency provisioning in the disposable clone (FB-27); returns the
    `dependency_setup` receipt rows (copied into the sensitivity proof).

    A clone of a Node/Playwright project has no node_modules (git-ignored, so `repo_files` never copies it),
    and a TS/JS red probe in it died on MODULE_NOT_FOUND before any assertion. The request opts in with
    `sandbox_setup` rows; what a kind runs comes from references/sandbox-setup.json, never from the request.
    Every row is checked against the clone before any runs, and `prepare` writes no mutation until this
    returned. `planned` is `plan_setup(request)` when the caller already made it (`prepare` does, before the
    clone exists)."""
    planned = plan_setup(request) if planned is None else planned
    if not planned:
        return []
    root = Path(destination).resolve()
    _clone_guard(root)
    cwds = [_check_row_in_clone(root, item) for item in planned]   # every row's files, before the first run
    receipts = []
    for item, cwd in zip(planned, cwds):
        _run_install(item, cwd)
        receipts.append(_post_check(root, item, cwd))
    return receipts


def prepare(repo, destination, request, task_root=None, budget_s=None):
    """`budget_s`: the seconds the installs of this call may add up to; None is the project's own
    `sandbox.install_timeout_s` (a probe passes what is left for the second clone)."""
    repo, destination = Path(repo).resolve(), Path(destination).resolve()
    if destination == repo or destination.is_relative_to(repo) or repo.is_relative_to(destination):
        raise ValueError("sandbox and main tree must be disjoint")
    if destination.exists():
        raise ValueError("sandbox destination must be new; never overwrite another job")
    if budget_s is None:
        budget_s = install_budget_s(repo) if request.get("sandbox_setup") else INSTALL_BUDGET_S
    planned = plan_setup(request, budget_s)   # the form and the budget, before any clone exists
    files = repo_files(repo)
    files.update(request.get("extra_files", []))
    if ".qa-probe.json" in files:
        raise ValueError("reserved sandbox receipt path is tracked")
    mutations = request.get("mutations", [])
    if not mutations:
        raise ValueError("red probe requires a specific mutation and intended oracle")
    refuse_same_path(repo, mutations)  # before anything is created
    live = artifact_prefixes(repo)  # this project's own story-artifacts location
    for item in mutations:
        path = inside(repo, item["path"])
        if is_generated(item["path"], live):
            raise ValueError("a generated factory artefact is not a mutation target; "
                             "mutate the product or test seam the obligation names")
        if item["path"] not in files or not path.is_file() or digest(path) != item["before_sha256"]:
            raise ValueError("mutation does not match current author bytes")
        if not all(item.get(k) for k in ("instance_id", "expected_location", "expected_reason")):
            raise ValueError("mutation requires exact target, location and expected reason")
        semantic = ("obligation_id", "defect_location", "assertion_id")
        if any(item.get(k) for k in semantic) and not all(item.get(k) for k in semantic):
            raise ValueError("semantic mutation requires obligation, real defect location and assertion identity")
        if item.get("defect_location") == item["expected_location"]:
            raise ValueError("semantic mutation must damage the exercised behavior, not its assertion")
        if item.get("mutation_kind") in {"assertion_edit", "mock_expectation"}:
            raise ValueError("assertion-only or mock-call mutations do not prove product behavior")
    # Validate the whole copy set before creating anything. No dependency symlinks:
    # the adapter provisions dependencies independently inside the disposable tree.
    originals = {}
    volatile = []
    for relative in sorted(files):
        path = inside(repo, relative)
        if path.is_symlink() or (repo / relative).is_symlink():
            raise ValueError("sandbox adapter must explicitly materialize symlinks")
        if not path.is_file():
            continue
        if is_generated(relative, live):
            volatile.append(relative)  # named in the receipt, neither copied nor compared
        else:
            originals[relative] = digest(path)
    destination.mkdir(parents=True)
    receipt = {"status": "preparing", "repo": str(repo), "sandbox": str(destination),
               "original_hashes": originals, "volatile": volatile, "targets": mutations}
    atomic_json(destination / ".qa-probe.json", receipt)
    try:
        for relative in originals:
            target = inside(destination, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(inside(repo, relative), target)
            if digest(target) != originals[relative]:
                raise ValueError("author tree changed during sandbox copy; probe is incomplete")
        # Dependencies first, in the still-unmutated copy (I3): a refused or failed install leaves no
        # half-mutated clone behind, and the mutation never meets a tree the install did not see.
        if planned:
            receipt["dependency_setup"] = provision_dependencies(destination, request, planned)
        for item in mutations:
            inside(destination, item["path"]).write_text(item["replacement_utf8"], encoding="utf-8")
        receipt["node_id_check"] = check_node_ids(destination, request, mutations, task_root)
    except ValueError:
        # This call created the directory, so removing it overwrites nobody's job — and a
        # destination left behind would refuse the corrected request ("must be new").
        shutil.rmtree(destination, ignore_errors=True)
        raise
    receipt["status"] = "prepared"
    receipt["mutated_hashes"] = {m["path"]: digest(inside(destination, m["path"])) for m in mutations}
    atomic_json(destination / ".qa-probe.json", receipt)
    return receipt


def reason_matches(actual, expected) -> bool:
    """The same assertion message, with or without pytest's `AssertionError: ` in front.

    TP1-15045, S5-qa-code-critic-5: the pinned reason read "Expected the modified node's
    border to be ...", the junit message read "AssertionError: Expected the modified ...".
    The probe had failed exactly as intended and was refused; a receipt's targets are
    immutable, so a whole second sandbox (C:/qsbx-c4b3) was prepared and run to add fifteen
    characters. The prefix is how pytest spells ANY assertion, so it says nothing about
    which one fired; whitespace runs are folded for the same reason.

    The rule is `reporters.assertion_reason`: the whole texts when they agree (so every receipt
    written before it keeps matching), else the HEADLINES - a .NET assertion's detail lines are
    the reporter's, not the author's pin. `window_record` compares through the same function,
    so the producer and the acceptance side cannot disagree about one reason (Fact 9).
    """
    wanted, seen = reporters.assertion_reason(expected, actual)
    return bool(wanted) and wanted == seen


def probe_defect(target, result, baseline) -> str:
    """Why this non-failing target proves nothing about the TEST — or "" when it does.

    the critic's `autonomous` mutation rewrote a branch guarded by
    `str(request.mode).endswith("AUTONOMOUS")`, a condition that never held, so the mutated
    seam was never executed. The probe reported a "surviving test" and the automator was sent
    to repair an assertion that was doing its job. A mutation that changes nothing is a defect
    of the PROBE, owner factory: before a survivor counts, the mutated seam has to be shown to
    behave differently from the unmutated one.

    First of all (t-043 C, D8): a mutated run that gave this test NO result - skipped, not run, an
    error, a report row that is missing or ambiguous - says nothing about the test either way. It
    was `incomplete_or_wrong_failure`, and the probe called it `survived`: the author was sent to
    repair a test the probe never actually ran. It is the probe's own run, owner factory.
    """
    status = result.get("status") or "not_run"
    if status == "timeout":
        # never `survived` and never a kill: the run did not finish, the test was not judged
        return (f"the mutated run timed out ({result.get('timeout_s') or 'the time budget of the run'}): rerun "
                "the probe with a longer budget, or judge the test by hand")
    if status not in ("passed", "failed"):
        return (f"the mutated run gave this test no result ({status}): the probe's own run, "
                "not the test")
    if result.get("mutation_observed") is False:
        return "the mutated seam was not reached: the probe recorded no behaviour change"
    row = (baseline or {}).get(target["instance_id"])
    # `not_run` is "the report does not say" (FR-41): two runs that read nothing do not show a
    # mutation that changed nothing, so it is never reported as that fact.
    if row and row.get("status") == result.get("status") and result.get("status") != "not_run":
        return (f"mutated and unmutated runs both ended {result.get('status')!r}: the mutation "
                "does not change the exercised behaviour")
    return ""


def verify(receipt, results, baseline=None):
    repo = Path(receipt["repo"])
    # A path the factory itself generates is neither copied nor compared — see is_generated().
    # An old receipt has no `volatile` list, and then everything is compared, as before.
    volatile = set(receipt.get("volatile") or ())
    if any(not inside(repo, p).is_file() or digest(inside(repo, p)) != h
           for p, h in receipt["original_hashes"].items() if p not in volatile):
        raise ValueError("main-tree bytes changed during probe; acceptance blocked")
    by_instance = {r["instance_id"]: r for r in results}
    by_baseline = {str(r.get("instance_id")): r for r in (baseline or []) if isinstance(r, dict)}
    supplied = baseline is not None  # `--verify-receipt` without `--baseline` is unchanged
    proofs = []
    for target in receipt["targets"]:
        result = by_instance.get(target["instance_id"], {})
        semantic_match = all(result.get(k) == target.get(k)
                             for k in ("obligation_id", "defect_location", "assertion_id")) \
            if target.get("obligation_id") else True
        # A failure of the mutated run is the mutation's doing only if the same instance PASSED
        # unmutated: a test that was already red, skipped or never ran is not made sensitive by it.
        base = by_baseline.get(str(target["instance_id"]))
        base_status = str((base or {}).get("status") or "absent") if supplied else "passed"
        valid = (result.get("status") == "failed" and result.get("failure_kind") == "assertion"
                 and semantic_match
                 and result.get("location") == target["expected_location"]
                 and reason_matches(result.get("reason"), target["expected_reason"])
                 and result.get("semantic_verdict") == "intended_failure"
                 and base_status == "passed")
        proof = {"instance_id": target["instance_id"], "valid": valid,
                 "verdict": "intended_failure" if valid else "incomplete_or_wrong_failure"}
        if not valid:
            reason = probe_defect(target, result, by_baseline)
            if reason:
                proof.update({"verdict": "probe_defect", "owner": "factory", "reason": reason})
            elif result.get("site_unread"):
                # The mutated run failed, and where it failed is not read for this runner yet
                # (B-337): the proof is incomplete - the factory's gap, never a verdict on the test.
                proof.update({"site_unread": result["site_unread"],
                              "reason": str(result.get("site_unread_reason")
                                            or f"the assertion site of a {result['site_unread']} report "
                                               "is not read yet (B-337)")})
            elif base_status != "passed":
                said = ("the baseline carries no row for this instance" if base_status == "absent"
                        else f"the unmutated run of this instance ended {base_status!r}")
                proof.update({"baseline_status": base_status,
                              "reason": said + ", not 'passed': a failure of the mutated run cannot "
                              "be read as the mutation's doing. The run's notes say why it did not; "
                              "repair that, then probe again"})
        proofs.append(proof)
    defects = [p for p in proofs if p["verdict"] == "probe_defect"]
    status = "accepted" if all(p["valid"] for p in proofs) else (
        "probe_defect" if defects else "incomplete")
    return {"status": status, "proofs": proofs, "probe_defects": defects}


def manifest_bindings(task: Path, probe_receipt: dict) -> dict:
    """The immutable facts a proof receipt binds, read from what the author already wrote.

    `--bindings <instance-bindings.json>` was a file no role was ever told to write: the
    critic's charter passed it, nothing produced it, and the one command that publishes a
    sensitivity proof could not be run at all (0.7.7 review). Every fact in it already
    exists on disk — the case version and the test bytes in the instance's manifest row, the
    source and build identity in the run block that executed it, and the restoration
    evidence in this probe's own verified main-tree hashes.
    """
    restoration = (f"red_sandbox --verify-receipt: {len(probe_receipt.get('original_hashes') or {})} "
                   "main-tree file hashes unchanged after the probe")
    out = {}
    for target in probe_receipt.get("targets") or []:
        instance_id = str(target.get("instance_id") or "")
        # The facts a receipt binds are read in ONE place, `proof_level.binding_facts`, because
        # `probe_by_code.py` writes a receipt too and two readers of the same sources drift.
        binding = {**proof_level.binding_facts(task, instance_id), "restoration_evidence": restoration}
        missing = [key for key, value in binding.items() if not value]
        if missing:
            raise ValueError(
                f"{instance_id}: the manifest and run blocks carry no {', '.join(missing)}. "
                "This is the author's record, not yours to type: the case version and test "
                "bytes belong in the instance's tests[] row (case_version_links, "
                "trace_binding.test_content_sha) and the source/build identity in the run "
                "block that executed it. Return the gap in your digest.")
        out[instance_id] = binding
    return out


def _original_hash_of(probe_receipt: dict, test_file: str) -> str:
    """The sha256 the sandbox copied for this project-relative file (`original_hashes`), '' when it
    holds none."""
    wanted = str(test_file or "").replace("\\", "/").strip("/")
    for path, digest_ in (probe_receipt.get("original_hashes") or {}).items():
        if wanted and str(path).replace("\\", "/").strip("/") == wanted:
            return str(digest_)
    return ""


_LOCATION_RE = re.compile(r"^(?P<file>.+):(?P<line>\d+)$")


def _receipt_scope(test_file, location) -> tuple:
    """`(scope, checks)` of a product receipt (t-2064 P6, EP-W): what the receipt proves, said in the receipt itself.

    `scope` is `"whole_unlisted"` when the assertion-probe tables (`assertion_detectors`: the AST row, then the entry by suffix) have NO
    reader for the test file's suffix - no list of that test's checks can exist, so the receipt stands as it always did - and
    `"one_check"` otherwise: it proves the one check at `assertion_location` and no other. `checks` is `[{"key": "<file>:<line>",
    "probe_kind": "product"}]` for that location, `[]` when the location is not `<file>:<line>` (unread). The test file is the one the
    identity measured, else the file of the location. ERROR DIRECTION: a table that cannot be read, or no file to tell the suffix by,
    is `one_check` (the receipt never proves more than it names; FR-41, AR-28). Reads the tables; writes nothing."""
    import assertion_detectors as AD
    found = _LOCATION_RE.match(str(location or "").strip())
    checks = [{"key": found.group(0), "probe_kind": "product"}] if found else []
    named = str(test_file or "").strip() or (found.group("file") if found else "")
    suffix = Path(named).suffix if named else ""
    if not suffix:
        return proof_level.ONE_CHECK, checks
    try:
        _language, ast_row = AD.ast_entry(suffix)
        entry = None
        if ast_row is None:
            _language, entry = AD.entry_for_suffix(AD.assertion_detectors(), suffix)
    except AD.DetectorsError:
        return proof_level.ONE_CHECK, checks
    if ast_row is None and entry is None:
        return proof_level.WHOLE_UNLISTED, []
    return proof_level.ONE_CHECK, checks


def _written_scope(task_root, ref) -> str:
    """The `scope` word of the receipt `ref` ({receipt_ref: {path}}) names, read from the file just written (the ONE source of the
    publish decision, t-2064 fix round G). ERROR DIRECTION: a receipt that cannot be read says `one_check` (nothing is published
    for what cannot be named; FR-41, AR-28). Reads; writes nothing."""
    try:
        data = json.loads((Path(task_root) / ref["receipt_ref"]["path"]).read_text(encoding="utf-8"))
        return str(data.get("scope") or proof_level.ONE_CHECK)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return proof_level.ONE_CHECK


def write_sensitivity_receipts(task, probe_receipt, results, bindings, baseline=None, identity=None,
                               notes=None):
    """Publish hash-bound S5 proof receipts from a verified isolated red probe.

    `identity` maps an instance id to `proof_level.instance_identity()`'s answer for its test (plus its
    `test_file`), measured BEFORE the sandbox was prepared. A receipt carries `test_code_sha` and
    `instance_identity` only when the raw sha of the bytes measured equals BOTH what the manifest binds
    (`binding.test_content_hash`) and what the sandbox copied of that file: a code sha of bytes other than
    the ones the receipt claims would keep a proof over a change nobody looked at. Otherwise the receipt
    binds raw bytes only, and `notes` (when given) says why."""
    task = Path(task).resolve()
    # The baseline reaches `verify` here too. Without it `probe_defect` had one signal left
    # on this branch (`mutation_observed`), so a mutation that changed nothing was published
    # as "incomplete or wrong red probe" and the author was sent to repair a healthy test —
    # the TP1-15045 harm `probe_defect` was written to stop.
    checked = verify(probe_receipt, results, baseline)
    if checked["status"] == "probe_defect":
        raise ValueError("the probe's own mutation changed nothing (owner: factory); "
                         "repair the mutation, do not repair the test: "
                         + "; ".join(f"{d['instance_id']}: {d['reason']}" for d in checked["probe_defects"]))
    if checked["status"] != "accepted":
        raise ValueError("incomplete or wrong red probe cannot publish sensitivity proof")
    by_result = {str(row.get("instance_id")): row for row in results}
    by_target = {str(row.get("instance_id")): row for row in probe_receipt.get("targets") or []}
    refs = {}
    for instance_id, binding in bindings.items():
        target, result = by_target.get(instance_id), by_result.get(instance_id)
        if not target or not result:
            raise ValueError(f"binding {instance_id} has no verified probe target/result")
        required = ("case_version", "test_content_hash", "source_revision", "build_id",
                    "restoration_evidence")
        if any(not binding.get(key) for key in required):
            raise ValueError(f"binding {instance_id} lacks immutable case/test/source/build/restoration facts")
        proof = {"instance_id": instance_id, **{key: binding[key] for key in required},
                 "mutation": target.get("mutation_kind") or target.get("replacement_utf8"),
                 "expected_assertion_failure": target.get("expected_reason"),
                 "actual_failure": result.get("reason"),
                 "assertion_location": result.get("location"), "failure_kind": result.get("failure_kind"),
                 # A deliberate break of the product made the test fail: the higher of the two
                 # levels (D-0010). Named on the receipt so no reader has to guess it from the tool.
                 "proof_level": proof_level.PRODUCT, "probe_tool": "red_sandbox.py",
                 "immutable": True}
        measured = (identity or {}).get(instance_id)
        if measured:
            raw = str(measured.get("input_hash") or "")
            copied = _original_hash_of(probe_receipt, measured.get("test_file"))
            if raw and raw == str(binding.get("test_content_hash") or "") and raw == copied:
                if measured.get("test_code_sha"):
                    proof["test_code_sha"] = measured["test_code_sha"]
                if measured.get("instance_identity"):
                    proof["instance_identity"] = measured["instance_identity"]
            elif notes is not None:
                notes.append(f"{instance_id}: the test file hashes {raw or 'nothing readable'}, the manifest binds "
                             f"{binding.get('test_content_hash') or 'nothing'} and the sandbox copied "
                             f"{copied or 'no such file'}: the receipt binds raw bytes only")
        if probe_receipt.get("dependency_setup"):
            # What the clone was provisioned with is part of what the proof was measured on: INSIDE the hash.
            proof["dependency_setup"] = probe_receipt["dependency_setup"]
        # t-2064 P6 (EP-W): what the receipt proves, inside the hash. A reader that finds no `scope` knows it is an old receipt (EP-I).
        proof["scope"], proof["checks"] = _receipt_scope((measured or {}).get("test_file"), result.get("location"))
        proof["receipt_hash"] = content_hash(proof)
        directory = task / "work" / "sensitivity-receipts"
        # An instance id is an identity, not a path: `TC-012::test_x[eu]` cannot be a file
        # name on Windows. A receipt written before 0.7.7 keeps its old name, so both are read.
        suffix = f"-{proof['receipt_hash'][:16]}.json"
        path = directory / (contract.instance_file_stem(instance_id) + suffix)
        legacy = directory / f"{instance_id}{suffix}"
        if legacy.exists() and not path.exists():
            path = legacy
        if path.exists() and json.loads(path.read_text(encoding="utf-8")) != proof:
            raise ValueError("immutable sensitivity receipt collision")
        atomic_json(path, proof)
        refs[instance_id] = {"receipt_ref": {"path": path.relative_to(task).as_posix(),
                                               "sha256": digest(path)}}
    return refs


# --- --probe: the whole manual sequence in one call ---------------------------------------

def _node_tail(node_id) -> str:
    """The part after the LAST `::` of a pytest node id — the function/parameter spelling,
    whatever classname the project's own junit reports (module-dotted, file-pathed, or
    class-qualified); matching on it is what survives that difference."""
    return str(node_id or "").replace("\\", "/").rsplit("::", 1)[-1]


def _param_matches(want: str, held: str) -> bool:
    """A requested parameter `want` names the parameter `held` of a report row: the same text, or the same
    dash-separated parts with exactly ONE extra token before or after (pytest-playwright merges its own
    parameter into the author's bracket: `[json]` is reported as `[chromium-json]`). Two extra tokens, or
    the parts in another order, are another test."""
    if want == held:
        return True
    w, h = want.split("-"), held.split("-")
    return len(h) == len(w) + 1 and (h[1:] == w or h[:-1] == w)


def matching_rows(rows: list, node) -> list:
    """The report rows that ARE the requested node - the ONE matcher (`probe_by_code.py` imports it).
    The row of exactly that id wins. Otherwise a node WITHOUT a parameter (`func`, or an empty `func[]`)
    matches every row `func[<params>]`: a plugin (pytest-playwright adds `[chromium]`) parametrises a test the
    author never parametrised. A node WITH one (`func[p]`) matches every row `func[q]` whose `q` is `p` plus
    one plugin token (`_param_matches`); `func[webkit]` never matches `func[firefox]`. Only the tail after the
    last `::` is compared."""
    want = _node_tail(node)
    exact = [r for r in rows if _node_tail(r["test_id"]) == want]
    if exact:
        return exact
    base, bracket, rest = want.partition("[")
    param = rest[:-1] if bracket and rest.endswith("]") else None
    if bracket and param is None:
        return []
    out = []
    for row in rows:
        tail = _node_tail(row["test_id"])
        if not (tail.startswith(base + "[") and tail.endswith("]")):
            continue
        if not param or _param_matches(param, tail[len(base) + 1:-1]):
            out.append(row)
    return out


def held_ids(rows: list, limit: int = 5) -> str:
    """The ids a report held, for a refusal that found no row: at most `limit` of them, then `(+N more)`."""
    ids = [r["test_id"] for r in rows]
    return ", ".join(repr(i) for i in ids[:limit]) + (f" (+{len(ids) - limit} more)" if len(ids) > limit else "")


def _match_row(node_id, rows: list) -> tuple:
    """(row, note) - the report row this pinned node id names, or none and why. One row, exact or the
    single plugin-parametrised `name[p]` one, is bound; several are never picked (FR-41): the note says so."""
    tail = _node_tail(node_id)
    if not tail:
        return None, "no pinned node_id: cannot match a report row to this instance"
    matches = matching_rows(rows, node_id)
    if not matches:
        return None, f"no report row named {tail!r} in this run" + (f"; the report held {held_ids(rows)}" if rows else "")
    if len(matches) > 1:
        return None, f"{len(matches)} report rows are named {tail!r}; ambiguous"
    return matches[0], ""


def _report_rows(task_root: Path, summary: dict, notes: list, label: str) -> list:
    """The run's report rows, read by the reporter the run's OWN summary names. A summary that
    names none (or `none`) reads nothing: guessing the format from the file would turn a wrong
    declaration into a plausible wrong proof, and the proof stays incomplete (FR-41)."""
    reporter = summary.get("reporter")
    if reporter not in reporters.READERS:
        notes.append(f"{label} run: the run's summary names no readable reporter ({reporter!r}; "
                     f"expected one of {', '.join(reporters.READERS)}), so no report row was read "
                     "and the proof is incomplete. The profile's `reporter.kind` in "
                     "qa-factory/config.json says what its command writes "
                     "(`/qa-factory:qa-onboarding` records it)")
        return []
    evidence = summary.get("report_evidence") or {}
    rel = evidence.get("path")
    if not rel:
        notes.append(f"{label} run: no report evidence ({summary.get('parse_gap') or summary.get('no_junitxml') or summary.get('execution_status') or 'unknown cause'})")
        return []
    xml_path = task_root / rel
    if not xml_path.is_file():
        notes.append(f"{label} run: report evidence missing on disk: {rel}")
        return []
    try:
        return reporters.read_rows(xml_path, reporter)
    except ET.ParseError as exc:
        notes.append(f"{label} run: report is not valid XML: {exc}")
        return []


def _run_contracts(task_root: Path, summary: dict, notes: list, label: str) -> dict:
    """instance id -> the `instance_contracts` entry of the JOB REQUEST of this run.

    The request is what the runner was launched with - `run_suite` persists it as the job record,
    node ids respelled to what pytest really collects (`apply_resolved_ids`) - so the id in it is
    the one the report spells (FR-16: resolved by the tool that produces it, not typed again from
    the author's manifest, which `manifest_from_tests.py` never gives a `report_test_id`). The job
    is found by the summary path it recorded, else by the job id the run's label carries; a run
    no job answers to has no contracts, and says so."""
    directory = Path(task_root) / "state" / "execution-jobs"
    wanted_summary = str(summary.get("summary_path") or "")
    wanted_job = str(summary.get("label") or "").rpartition("-")[2]
    found, by_label = None, None
    for path in sorted_paths(directory.glob("*.json")) if directory.is_dir() else []:
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(job, dict) or not isinstance(job.get("request"), dict):
            continue
        if wanted_summary and job.get("summary") == wanted_summary:
            found = job
            break
        if wanted_job and job.get("job_id") == wanted_job:
            by_label = by_label or job
    found = found or by_label
    if found is None:
        notes.append(f"{label} run: no job record under state/execution-jobs answers to its summary "
                     f"{wanted_summary or 'path (none)'} or job {wanted_job or 'id (none)'}, so the report ids "
                     "of the request could not be read")
        return {}
    contracts = found["request"].get("instance_contracts")
    return contracts if isinstance(contracts, dict) else {}


def _is_pytest(command) -> bool:
    from execution_request import is_pytest_command
    return is_pytest_command(command)


def _launcher(command) -> str:
    """The executable that launched the run (`dotnet`, `npx`, `mvn`): a hint for the text of an
    unread site, never an input of any decision (FR-13)."""
    first = str(next(iter(command or []), "")).strip("\"'")
    name = Path(first).name
    return name[:-4] if name.lower().endswith(".exe") else name


def bind_row(target: dict, contracts, rows: list, reporter, ticket: str = "",
             pytest_command: bool = False) -> tuple:
    """(row, note): the report row of this target, or None and why.

    The row whose `test_id` EQUALS the `report_test_id` the job request carries for the target
    (`contracts` is the request's `instance_contracts`): the identity the runner produced, for every
    reporter. The legacy port matched a suffix of the name, which is a guess and binds the wrong
    test the day two classes share a method name. Where the request carries none - no contracts, no
    contract for the target, an empty id - a pytest run (`pytest_command`, or the `pytest` reporter)
    falls back to the tail of the pinned node id, as it always did; any other runner is not bound,
    with the door that records the id. Nothing matched, or more than one - or one id given to two
    instances - is `not_run` for the caller with the reason (FR-41), never a pick."""
    if reporter not in reporters.READERS:
        return None, ""  # `_report_rows` already said why there are no rows
    instance = str(target.get("instance_id") or "")
    contracts = contracts if isinstance(contracts, dict) else {}
    own = contracts.get(instance)
    report_id = str(own.get("report_test_id") or "").strip() if isinstance(own, dict) else ""
    if not report_id:
        if pytest_command or reporter == "pytest":
            node_id = target.get("node_id") or next(iter(target.get("node_ids") or []), None)
            return _match_row(node_id, rows)
        return None, (
            f"the request of this run carries no `report_test_id` for {instance}, so no row of the "
            f"{reporter} report can be bound to it (the runner's own name for a test is not "
            "guessed from the instance id). The automator records it on the instance's tests[] row "
            f"through `manifest_put.py --task {ticket or '<TICKET>'} --fragment <file>` "
            '(`{"tests": [{"instance_id": "<id>", "report_test_id": "<the runner\'s name>"}]}`); '
            "return that gap in your digest, then probe again")
    owners = sorted(i for i, c in contracts.items()
                    if isinstance(c, dict) and str(c.get("report_test_id") or "").strip() == report_id)
    if len(owners) > 1:
        return None, (f"the request gives report_test_id {report_id!r} to {len(owners)} instances "
                      f"({', '.join(owners)}); ambiguous - which of them a report row belongs to cannot be "
                      "told. Each manifest row must name its own test: "
                      f"`manifest_put.py --task {ticket or '<TICKET>'} --fragment <file>`, then probe again")
    if isinstance(own, dict) and own.get("file"):
        # a selection built from a file (EP1-37): the one matcher; "no row" and "ambiguous" keep their texts below
        matches = selection_rows(rows, own)     # more than one row is the ambiguous text below (the several-projects judge is EP1-36's)
    else:
        matches = [row for row in rows if row["test_id"] == report_id]
    if not matches:
        return None, f"no row of the {reporter} report has test_id {report_id!r} (the request's report_test_id of {instance})"
    if len(matches) > 1:
        return None, (f"{len(matches)} rows of the {reporter} report carry test_id {report_id!r} "
                      f"({', '.join(r['status'] for r in matches)}); ambiguous - the request's "
                      f"report_test_id of {instance} must name exactly one row")
    return matches[0], ""


NEAREST_MIN = 0.6   # the best name a report holds is offered as "nearest" from this ratio on (AT and beyond)


def _report_parts(row) -> tuple:
    """(classname with `/` for `\\`, name) of a report row: JUnit spells `classname::name`, and a Windows runner writes the
    classname with backslashes."""
    classname, _sep, name = str(row.get("test_id") or "").partition("::")
    return classname.replace("\\", "/"), name


def _file_ends_with(file: str, classname: str) -> bool:
    """Is the report's classname this file, or its tail from a path-segment boundary? (`tests/mycart.x` is not
    `cart.x`: a neighbour's file is never bound.)"""
    file = str(file or "").replace("\\", "/")
    return bool(classname) and (file == classname or file.endswith("/" + classname))


def _wanted_parts(report_test_id: str) -> tuple:
    """(file with `/`, name) of a contract's `report_test_id`: the text after the first `::` is the name and the text before it
    the file; an id without `::` is all name, and its file is ""."""
    head, sep, tail = str(report_test_id or "").partition("::")
    return (head.replace("\\", "/"), tail) if sep else ("", head)


def _same_file_by_tail(wanted_file: str, classname: str) -> bool:
    """Is the id's own file part empty, or one file with the report's classname - either is the tail of the other from a
    path-segment boundary?"""
    if not wanted_file:
        return True
    return (wanted_file == classname or wanted_file.endswith("/" + classname)
            or classname.endswith("/" + wanted_file))


def selection_rows(rows: list, contract) -> list:
    """The report rows ONE contract with a `file` names - the ONE matcher of a selection built from a file (EP1-37, AR-13;
    `run_suite.build_run_block` and `bind_row` both call it). A row is the contract's when its `classname` is the file (or its
    tail by a segment boundary) AND its name is: matched by `report_match.pattern` (a templated or looped test: every row the
    pattern fits), else - for `classname_match: file_suffix` - equal to the name in `report_test_id`, else the whole id equal to
    `report_test_id`. Rows whose classnames differ are returned all: the caller reads that as ambiguous and decides.

    The last (exact) branch also binds by NAME (RN1-21): a bare-title `report_test_id` (`@regression LOCAL-1_TC_010 ...`), or one
    spelled with the path of the project's own tree (`tests/api/cart/x.spec.ts::<title>`), is the contract's row when the row's name
    equals the id's name, the row's classname is the contract's file (or its tail by a segment boundary), and the id's own file part,
    if any, is one file with the classname by tail in either direction. Never a prefix, never another file, never another case of
    the title: the error goes to `not_run`, not to another test's row."""
    contract = contract if isinstance(contract, dict) else {}
    import test_source
    file = str(contract.get("file") or "")
    pattern = str((contract.get("report_match") or {}).get("pattern") or "") if isinstance(contract.get("report_match"), dict) else ""
    wanted = str(contract.get("report_test_id") or "")
    tail = wanted.partition("::")[2]
    wanted_file, wanted_name = _wanted_parts(wanted)
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        classname, name = _report_parts(row)
        if pattern:
            hit = test_source.pattern_matches(pattern, name) and _file_ends_with(file, classname)
        elif contract.get("classname_match") == "file_suffix":
            hit = bool(tail) and name == tail and _file_ends_with(file, classname)
        else:
            hit = bool(wanted) and (str(row.get("test_id") or "") == wanted or (
                bool(wanted_name) and name == wanted_name and _file_ends_with(file, classname)
                and _same_file_by_tail(wanted_file, classname)))
        if hit:
            out.append(row)
    return out


def classnames_differ(rows: list) -> bool:
    """Do the rows `selection_rows` returned name more than one file? Then which test ran cannot be told."""
    return len({_report_parts(r)[0] for r in rows}) > 1


def nearest_row(rows: list, contract):
    """The `test_id` of the report row whose name is closest to the contract's, when its ratio is at least NEAREST_MIN; else
    None (a hint is never invented from a poor match)."""
    import difflib
    tail = _wanted_parts(str((contract or {}).get("report_test_id") or ""))[1]    # a bare title has no `::`: it is all name
    best, best_ratio = None, 0.0
    for row in rows:
        if not isinstance(row, dict):
            continue
        ratio = difflib.SequenceMatcher(None, tail, _report_parts(row)[1]).ratio()
        if ratio > best_ratio:
            best, best_ratio = row, ratio
    return str(best.get("test_id")) if best is not None and best_ratio >= NEAREST_MIN else None


def _frame_grammar(expected_file: str) -> dict:
    """The `frames`, `skip_frames` and `frame_path` keywords of `reporters.assertion_site` for the file whose
    suffix has an `assertion_probes` entry in `references/detectors.json` (B-373 R12): the stack-frame grammar
    of that language, read through the ONE reader (`assertion_detectors`, FR-17: the same table the live probe
    reads, never a second parser of it). No entry, or a table that cannot be read, gives `{}` - the keywords
    are then NOT passed (never `frames=[]`: an empty list says "a grammar was given" and would turn every TRX
    row of a suffix with no entry from the built-in read into an unread site, L11) and the behaviour is what
    it was before the table existed, the safe direction."""
    import assertion_detectors as AD
    try:
        _language, entry = AD.entry_for_suffix(AD.assertion_detectors(), Path(str(expected_file)).suffix)
    except AD.DetectorsError:
        return {}
    if entry is None:
        return {}
    frames, skip_frames, frame_path = AD.grammar_of(entry)
    return {"frames": frames, "skip_frames": skip_frames, "frame_path": frame_path}


def target_result(target: dict, row, reporter: str, clone_root, command=None) -> dict:
    """The result `verify()` reads for one target. Status comes from the row (`not_run` when no
    row was bound); the failure site and kind from `reporters.assertion_site`, which for a TRX
    row calls a failure an assertion only when the first located stack frame is in the file of
    the target's `expected_location` inside THIS clone.

    `command` is the run's argv as its summary recorded it. With it, a `junit-xml` row of a command
    that is not pytest has an UNREAD site (B-337) - unless the target's file has an `assertion_probes`
    entry, whose frame grammar then reads it (`_frame_grammar`): the result carries `site_unread` (typed)
    and `site_unread_reason`, no location, and the failure's own message stays the `reason`, when the
    frame cannot be resolved to a project file. Without `command` the pytest grammar is read, as it
    always was."""
    entry = {"instance_id": str(target.get("instance_id") or ""), "status": "not_run"}
    if row:
        entry["status"] = row["status"]
        problems = row.get("problems") or []
        chosen = next((p for p in problems if p.get("kind") == "failure"),
                      next((p for p in problems if p.get("kind") == "error"), None))
        entry["reason"] = (chosen or {}).get("message", "")
        expected_file = str(target.get("expected_location") or "").rpartition(":")[0]
        hint = {} if command is None else {"pytest_command": _is_pytest(command), "runtime": _launcher(command)}
        site = reporters.assertion_site(row, reporter, clone_root, expected_file, **hint, **_frame_grammar(expected_file))
        if "site_unread" in site:
            entry["site_unread"], entry["site_unread_reason"] = site["site_unread"], site["reason"]
        else:
            entry.update(site)
    for key in ("obligation_id", "defect_location", "assertion_id"):
        if target.get(key):
            entry[key] = target[key]
    if entry["status"] == "failed" and entry.get("failure_kind") == "assertion":
        entry["semantic_verdict"] = "intended_failure"
    return entry


def _unmutated_variant(repo: Path, request: dict) -> dict:
    """The same request with every mutation's replacement equal to the CURRENT author bytes:
    `prepare()` on it copies a byte-identical sandbox. The baseline runs there, isolated like
    the mutated probe, never in the author's own tree (`run_suite.py` refuses a red-probe run
    that is not explicitly scoped to one) and never hand-typed a second time."""
    clone = json.loads(json.dumps(request))
    for item in clone.get("mutations") or []:
        item["replacement_utf8"] = (repo / item["path"]).read_text(encoding="utf-8")
    return clone


def _run_mine(run_suite_path: Path, repo: Path, cases: list, *, dispatch: str, sandbox_root: Path,
             reason: str, again: bool, timeout: int, node_ids=()) -> tuple:
    """`--sandbox-root <clone>` and never `--cwd`: the request side refuses the two together, and
    `--cwd` takes ONE directory as given (the clone's root), losing the profile's own subdirectory
    (`backend/`). With `--sandbox-root` the runner works the run directory out inside the clone
    from the profile, and fingerprints the clone's test file, not the author's. `node_ids=()` runs
    the whole case."""
    argv = [sys.executable, "-B", str(run_suite_path), "--mine", *cases]
    for node in node_ids:  # `--mine` with ONE case takes the tests to run; a target's node, not its whole case
        argv += ["--node-id", str(node)]
    argv += ["--purpose", "red_probe", "--sandbox-root", str(sandbox_root), "--reason", reason]
    if dispatch:
        argv += ["--dispatch", dispatch]
    if again:
        argv.append("--again")
    proc = subprocess.run(argv, cwd=str(repo), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)
    lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip().startswith("{")]
    try:
        summary = json.loads(lines[-1]) if lines else {}
    except ValueError:
        summary = {}
    if not lines:
        # A refusal before the run (`store.begin`, a request the runner cannot read) is printed as
        # `{"status": "invalid_request", "error": ...}` on STDERR (run_suite.py): read it there, so the probe
        # reports the typed refusal. ONLY that form is taken - `error` present, `execution_status` absent -
        # because a line with `execution_status` claims a run happened, and a stderr line must never make
        # a run "have been" (the error direction of this read is "no summary").
        stderr = [ln for ln in proc.stderr.strip().splitlines() if ln.strip().startswith("{")]
        try:
            refusal = json.loads(stderr[-1]) if stderr else {}
        except ValueError:
            refusal = {}
        if isinstance(refusal, dict) and refusal.get("error") and "execution_status" not in refusal:
            summary = refusal
    return proc, summary


def _cleanup(path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _case_nodes(placed: dict, case: str) -> list:
    """The `--node-id` selection of ONE case's launch: the targets' own nodes - but only when EVERY
    one of them is a pytest node (`<file>.py::<name>`, the shape `execution_request.manifest_rows`
    itself tests for). A `--node-id` row of the request carries an empty entry and no `report_test_id`
    (`build_mine_request`), so for a non-pytest runner (TRX, a JUnit of dotnet or maven) it would drop
    the runner's own identity of the test and every row would be refused at the binding. Any other
    node, or a case that mixes the two, launches the WHOLE case (an empty selection)."""
    nodes = [str(info["node"]) for info in placed.values() if info["case"] == case]
    return nodes if all(".py::" in node for node in nodes) else []


# --- --probe under the run budget (t-043 C) -------------------------------------------------------
# What `--probe` asks BEFORE it prepares a sandbox or launches anything: is every target placed in the
# manifest (a row, a case of this request, a node), was it already probed over these bytes, and does
# the story already hold a green run of it (the author's own) to stand as the unmutated baseline? A
# question that answers "no" costs no sandbox and no launch. The baseline used to be a second full
# run of the same cases, made in a second sandbox, on every probe: over a test the author had just
# run green on the same bytes it proved only what the budget already knew (D-0017, D-0018).

def _manifest_of(task_root: Path) -> dict:
    for path in (task_root / "work" / "automation-manifest.json", task_root / "automation-manifest.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if isinstance(value, dict):
            return value
    return {}


def _place_targets(manifest: dict, cases: list, targets: list) -> tuple:
    """({instance id: {"entry", "case", "node"}}, {instance id: words}) for the targets a mutations
    file names. A target with no manifest row, no case among `cases`, or no node in its row cannot be
    probed: the words name the field that is missing and the door that fills it (FR-1, FR-2) - the
    critic's own request (`cases`) or the automator's manifest (`manifest_put.py`), whichever holds the
    gap. Nothing here is guessed: a probe that cannot name the test it runs is not started."""
    import execution_request as ER
    placed, missing = {}, {}
    rows_of = {case: ER.manifest_rows(manifest, case)[0] for case in cases}
    for target in targets:
        iid = str(target.get("instance_id") or "") if isinstance(target, dict) else ""
        if not iid:
            missing[""] = "a mutation names no `instance_id`: name the manifest instance it is the probe of"
            continue
        entry = next((t for t in contract.manifest_tests(manifest) if isinstance(t, dict)
                      and iid in ({str(contract.test_instance_id(t))} | set(contract.instance_id_aliases(t)))), None)
        if entry is None:
            missing[iid] = (f"{iid}: the manifest names no such test (work/automation-manifest.json): the "
                            "automator records it through manifest_put.py first")
            continue
        names = {str(contract.test_instance_id(entry))} | set(contract.instance_id_aliases(entry))
        hit = next(((case, row) for case in cases for row in rows_of[case] if row["instance_id"] in names), None)
        if hit is None:
            linked = [c for c in contract.manifest_test_links(entry) if c in cases]
            missing[iid] = (
                f"{iid}: the manifest row names no test function (`selector`) for {', '.join(linked)}: the "
                "automator records it through manifest_put.py" if linked else
                f"{iid}: none of the cases in `cases` ({', '.join(cases)}) is a case of this test in the "
                "manifest: add its case to `cases`, or record the test's case links through manifest_put.py")
            continue
        placed[iid] = {"entry": entry, "case": hit[0], "node": hit[1]["node"]}
    return placed, missing


def _git_file_shas(repo: Path, revision: str, relative: str) -> set:
    """The sha256 the working file has when it is the file a git revision holds: the blob as stored, and
    the blob as a checkout writes it (`cat-file --filters`: a Windows checkout with `core.autocrlf` has
    CRLF where the blob has LF, and comparing the working file with the raw blob alone never matched there,
    so the author's green could never stand). Empty when the revision or the file cannot be read - and
    "cannot tell" is never "the same"."""
    found = set()
    for argv in (["show", f"{revision}:./{relative}"], ["cat-file", "--filters", f"{revision}:./{relative}"]):
        try:
            got = subprocess.run(["git", "-C", str(repo), *argv], capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            continue
        if got.returncode == 0:
            found.add(hashlib.sha256(got.stdout).hexdigest())
    return found


def _fresh_instances(repo: Path, task_root: Path, cases: list) -> dict:
    """{instance id: the state `execution_request.fresh_evidence` classifies its newest result in}, asked with the stand
    probed NOW and the collect `run_suite.mine` uses - the ONE ask, for the baseline of a probe and for the red check of
    a diagnostic run (AR-15). Raises what the ask raises; each caller decides what "cannot tell" means to it."""
    import execution_request as ER
    from hooklib import load_config
    import run_suite

    def collect(argv, cwd, files):
        # the collect S5 itself takes (RH1-3, AR-15): one copy, `run_suite.collect_files`
        return run_suite.collect_files(argv, cwd, files, load_config())

    found = ER.fresh_evidence(repo, task_root.name, cases, cfg=load_config(),
                              probe=run_suite.probe_runtime, collect=collect)
    return found.get("instances") or {}


def _author_baseline(repo: Path, task_root: Path, cases: list, targets: list, placed: dict,
                     notes: list) -> tuple:
    """What stands as the UNMUTATED run of the targets: `("covered", {"results", "jobs"})` - the author's
    green run of every target over these very bytes, no baseline to run - or `("refuse", {iid: words})`
    - a target with no such green: the author runs it first, a probe of a test nobody ran green proves
    nothing - or `("own", None)` - the story cannot say (no budget data, the stand's version cannot be
    observed now, the product file moved since the green, the record cannot be read): today's own
    baseline, so the probe is never a dead end for a reason that is not the test's (FR-41, P1).

    "The author's green" is `execution_request.fresh_evidence` - the classification `--mine` itself
    answers from - asked with the stand probed NOW and the collect `run_suite.mine` uses, so a
    parametrized row is keyed the way the author's run keyed it."""
    import execution_request as ER
    from hooklib import artifact_root
    policy, budget_note = ER.load_run_budget()
    if policy is None:
        notes.append(budget_note)
        return "own", None
    home = (artifact_root(root=repo) / task_root.name).resolve()
    if home != task_root.resolve():
        return "refuse", {"": (f"the --task-root {task_root} is not this project's story ({home}): the "
                               "baseline is read from the story's own run record, so name the story folder "
                               "of this project")}
    try:
        seen = _fresh_instances(repo, task_root, cases)
    except Exception as exc:
        notes.append(f"the author's result could not be read ({type(exc).__name__}: {str(exc)[:160]}): "
                     "the probe runs its own baseline")
        return "own", None
    refuse, unknown = {}, []
    for iid in placed:
        state = seen.get(iid) or {}
        kind = state.get("state") or "missing"
        if kind == "unknown":
            unknown.append(state.get("why") or "the stand's version was not observed")
        elif kind == "result" and state.get("outcome") == "passed":
            continue
        elif kind == "result":
            refuse[iid] = (f"{iid}: its newest result over these bytes is red ({state.get('job_id')}): a probe "
                           "needs a green test; the red goes to triage")
        elif kind == "stale":
            refuse[iid] = (f"{iid}: its earlier result does not stand ({state.get('why') or 'no reason given'}): "
                           "the author runs it on these bytes first")
        else:
            refuse[iid] = (f"no green run of {iid} on these bytes is on record: the author's run comes first; "
                           "a product probe breaks the product under a green test")
    if unknown:
        notes.append(f"the stand's version cannot be observed now ({unknown[0]}): no earlier green can be "
                     "trusted, so the probe runs its own baseline; this is the stand, not the test - "
                     "`environment` in your digest")
        return "own", None
    if refuse:
        return "refuse", refuse
    jobs = {}
    try:
        jobs = {str(j.get("job_id")): j for j in ER.JobStore(task_root / "state" / "execution-jobs").jobs()}
    except Exception:
        pass
    for target in targets:
        iid = str(target.get("instance_id"))
        job = jobs.get(str(seen[iid].get("job_id")))
        revision = str(((job or {}).get("request") or {}).get("fingerprint_components", {}).get("source_sha") or "")
        held = _git_file_shas(repo, revision, str(target.get("path"))) if revision else set()
        if not held or str(target.get("before_sha256") or "") not in held:
            notes.append(f"the product file changed since the author's green ({target.get('path')}): the probe "
                         "runs its own baseline")
            return "own", None
    results = [{"instance_id": iid, "status": "passed", "job_id": str(seen[iid].get("job_id")), "source": "author"}
               for iid in placed]
    ids = sorted({r["job_id"] for r in results})
    notes.append(f"baseline: the author's green {', '.join(ids)} on the same bytes (no baseline run)")
    return "covered", {"results": results, "jobs": ids}


def product_verdict(proof: dict) -> str:
    """The word a proof is on record by, and the one source of "this proof is a survivor": the product
    record (`_write_product_records`) and the request's status in `probe()` both read it, so the answer
    never contradicts a record. `survived` is an invalid proof that is neither the probe's own defect nor
    a proof that could not be judged (a failure site nobody reads, a baseline that was not a pass)."""
    if proof["valid"]:
        return "intended_failure"
    if proof["verdict"] == "probe_defect":
        return "probe_defect"
    if proof.get("site_unread") or proof.get("baseline_status"):
        return "incomplete"
    return "survived"


def request_status(verdict: dict, unrun: list) -> str:
    """The status of a whole request from its proofs - one place for the precedence. The probe's own
    defect first (upstream's order, unchanged); then a real survivor (`product_verdict`), which no other
    target's tooling state may mask; then a baseline that read nothing (`not_executed`); then a proof
    that could not be judged (`incomplete`); `accepted` when every proof is valid. A request of one
    target answers exactly as it did: its one proof is the only one that can decide."""
    if verdict["status"] == "probe_defect":
        return "probe_defect"
    if any(product_verdict(p) == "survived" for p in verdict["proofs"]):
        return "survived"
    if unrun:
        return "not_executed"
    if verdict["status"] != "accepted":
        if any(p.get("baseline_status") or p.get("site_unread") for p in verdict["proofs"]):
            return "incomplete"
        return "survived"
    return "accepted"


def _write_product_records(task_root: Path, dispatch: str, placed: dict, targets: list, proofs: list,
                           repo: Path, notes: list) -> None:
    """`work/probes/product/<stem>.json` for every target of a run that was launched: the verdict of
    `verify()` in the words a repeat is answered by - `intended_failure`, `survived` (a red that was
    not the pinned one), `probe_defect` (the probe's own failure) or `incomplete` (a proof that could
    not be judged: a failure site no reader exists for, a baseline that did not pass). Only
    `survived` blocks a repeat, and the NEWEST record decides, so a `probe_defect` after a person's
    word lifts a survivor's block (D11). The record carries the test's identity as measured BEFORE the sandbox was prepared and the
    product file the mutation touched with the bytes it held, so a later probe is answered only while
    both still hold."""
    when = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for proof in proofs:
        iid = str(proof["instance_id"])
        info = placed.get(iid)
        if info is None:
            continue
        now = info["now"]
        files = []
        for item in targets:
            if isinstance(item, dict) and str(item.get("instance_id")) == iid:
                try:
                    data = (repo / item["path"]).read_bytes()
                except OSError:
                    data = b""
                files.append({"path": str(item["path"]).replace("\\", "/"),
                              "sha256": str(item.get("before_sha256") or ""),
                              "code_sha": proof_level.code_sha(data, Path(str(item["path"])).name) if data else ""})
        record = {"schema_version": 1, "probe_tool": "red_sandbox.py", "instance_id": iid,
                  "verdict": product_verdict(proof),
                  "recorded_at": when, "dispatch_id": dispatch, "test_file_sha256": now["input_hash"],
                  "test_code_sha": now["test_code_sha"], "instance_identity": now["instance_identity"],
                  "mutated_files": files}
        path = proof_level.probe_record_path(task_root, iid, "product")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_json(path, record)
        except OSError as exc:
            notes.append(f"{iid}: the product record could not be written ({type(exc).__name__}): a repeat of "
                         "this probe is not answered")


def probe(repo, request_path, task_root, *, destination=None, dispatch: str = "",
          timeout: int = 1860) -> dict:
    """Ask, prepare, run the mutated targets, verify, record, publish, clean — one JSON answer.

    `{"status": "accepted"|"survived"|"probe_defect"|"incomplete"|"not_executed"|"already_probed",
    "instances": {...}, "receipts": [...], "notes": [...]}` (`incomplete`: the mutated run failed and
    its failure site is not read for this runner yet, or the unmutated run was not a pass - red, skipped,
    errored - so the failure is not the mutation's doing; the typed reason is `site_unread` or
    `baseline_status` in the instance, and the product record says `incomplete` too; exit 1 like
    `not_executed`); a
    `node_id_mismatch` from `prepare()` (the collect
    check) is passed through unwrapped, exactly as the plain `--repo/--destination/--request`
    call already answers it.

    First of all, before the manifest is read: two differing mutations of one path are refused
    (B-314, `not_executed` with the reason). In this order, all of it before a sandbox exists
    (t-043 C): (1) every target must be placed - a
    manifest row, a case of the request, a node - else `not_executed` with the missing field and its
    door; (2) a target already probed over these bytes answers the WHOLE request `already_probed`
    (`proof_level.already_probed`: take it out of `mutations[]` and probe the rest; a person's word
    passes a repeat); (3) the baseline: the author's green run of each target over the same bytes
    (`_author_baseline`) - none, `not_executed`; a story that cannot say, today's own baseline. Then the
    mutated sandbox only, and ONE launch per distinct case among the targets, selecting only the
    targets' nodes."""
    repo = Path(repo).resolve()
    task_root = Path(task_root).resolve()
    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    notes: list = []
    if not isinstance(request, dict):
        return {"status": "not_executed", "instances": {}, "receipts": [],
                "notes": ["the request is not a JSON object: write {\"cases\": [...], \"mutations\": [...]}"]}
    cases = [str(c) for c in (request.get("cases") or []) if str(c).strip()]
    if not cases:
        return {"status": "not_executed", "instances": {}, "receipts": [],
                "notes": ["the request names no `cases` (the case ids qa-code-critic's "
                         "dispatch covers) — nothing to hand run_suite.py --mine"]}
    targets = [t for t in request.get("mutations") or []] if isinstance(request.get("mutations"), list) else []
    placed, own_baseline, author_results = {}, True, []
    if targets and all(isinstance(t, dict) and isinstance(t.get("path"), str) for t in targets):
        # B-314 again, here: `prepare()` refuses it too, but only after the manifest was read, the
        # repeat check answered and a baseline looked for. A request whose own shape is wrong is
        # refused before any of that, any sandbox or any record; a request that names no path is
        # left to the placement below, which already says so.
        try:
            refuse_same_path(repo, targets)
        except ValueError as exc:  # MutationConflict, or `inside()`'s escape refusal
            return {"status": "not_executed", "instances": {}, "receipts": [],
                    "notes": [f"mutations: {exc}"]}
    if targets:
        manifest = _manifest_of(task_root)
        placed, missing = _place_targets(manifest, cases, targets)
        if missing:
            return {"status": "not_executed", "instances": {i: {"words": w} for i, w in missing.items() if i},
                    "receipts": [], "notes": list(missing.values())}
        answered = {}
        for iid, info in placed.items():
            info["now"] = proof_level.instance_identity(info["entry"], task_root, repo)
            # t-2064 fix round H: this is a PRODUCT probe's question; the check key is the location the request expects the test to
            # fail at (one distinct key, else no `kind`: today's answer, a repeat of several checks is never answered by one receipt).
            keys = {str(t.get("expected_location")) for t in targets
                    if isinstance(t, dict) and str(t.get("instance_id")) == iid and _LOCATION_RE.match(str(t.get("expected_location") or ""))}
            asked = {"kind": "product", "check_key": next(iter(keys)) if keys else ""} if len(keys) <= 1 else {}
            try:
                got = proof_level.already_probed(info["entry"], manifest, task_root, now=info["now"],
                                                 project=repo, dispatch=dispatch, **asked)
            except Exception as exc:
                got = {"probed": False, "notes": [f"{iid}: the repeat check failed ({type(exc).__name__}: "
                                                  f"{str(exc)[:160]}); the probe runs"]}
            notes.extend(got.get("notes") or [])
            if got.get("probed"):
                answered[iid] = got
        if answered:
            return {"status": "already_probed", "instances": answered, "receipts": [], "notes": notes,
                    "words": (f"{', '.join(answered)} already probed on these bytes: take "
                              f"{'it' if len(answered) == 1 else 'them'} out of mutations[] and probe the rest. "
                              + " ".join(a["words"] for a in answered.values()))}
        mode, evidence = _author_baseline(repo, task_root, cases, targets, placed, notes)
        if mode == "refuse":
            return {"status": "not_executed",
                    "instances": {i: {"words": w} for i, w in evidence.items() if i}, "receipts": [],
                    "notes": notes + list(evidence.values())}
        own_baseline = mode == "own"
        author_results = evidence["results"] if mode == "covered" else []
    scratch = Path(tempfile.mkdtemp(prefix="qa-probe-scratch-"))
    mutated_dest = (Path(destination).resolve() if destination else
                   repo.parent / f"{repo.name}-redprobe-{uuid.uuid4().hex[:10]}")
    baseline_dest = repo.parent / f"{repo.name}-redprobe-baseline-{uuid.uuid4().hex[:10]}"
    run_suite_path = Path(__file__).resolve().parent / "run_suite.py"
    manifest_put_path = Path(__file__).resolve().parent / "manifest_put.py"

    clock = time.monotonic()
    try:
        mutated_receipt = prepare(repo, mutated_dest, request, str(task_root))
    except NodeIdMismatch as exc:
        _cleanup(scratch)
        return {"status": "node_id_mismatch", "missing": exc.missing, "message": str(exc)}
    except ValueError as exc:
        _cleanup(scratch)
        return {"status": "not_executed", "instances": {}, "receipts": [],
                "notes": notes + [f"prepare (mutated): {exc}"]}

    if own_baseline:
        try:
            # one probe call, one install budget: what the first clone took (its whole preparation, a
            # little more than its install) is not available to the second
            left = {"budget_s": install_budget_s(repo) - (time.monotonic() - clock)} if request.get("sandbox_setup") else {}
            prepare(repo, baseline_dest, _unmutated_variant(repo, request), str(task_root), **left)
        except (ValueError, NodeIdMismatch) as exc:
            _cleanup(mutated_dest)
            _cleanup(scratch)
            return {"status": "not_executed", "instances": {}, "receipts": [],
                    "notes": notes + [f"prepare (baseline): {exc}"]}

    reason = f"red probe for {', '.join(cases)}"
    # The mutated run: ONE launch per distinct case among the targets, in the order of `cases`, selecting
    # only the targets' own nodes (the manifest row's spelling, which a whole-case run already uses). A
    # request with no target at all (`prepare` refuses it above) never gets here.
    groups = [(case, _case_nodes(placed, case))
              for case in cases if any(info["case"] == case for info in placed.values())]
    base_proc, base_summary, launched = None, {}, []
    try:
        # The baseline, when the author's green does not stand for it: first, over a fresh idempotency
        # key; the mutated launches after it, with `--again` — the same instances under the same
        # purpose/dispatch would otherwise read as the run that just completed and never launch
        # (S5-122, TP1-15045), and the product file is not fingerprinted, so an earlier probe's key
        # would answer the new run.
        if own_baseline:
            base_proc, base_summary = _run_mine(
                run_suite_path, repo, cases, dispatch=dispatch, sandbox_root=baseline_dest,
                reason=reason + " (unmutated baseline)", again=False, timeout=timeout)
        for case, nodes in groups or [(None, [])]:
            launched.append((case, *_run_mine(
                run_suite_path, repo, [case] if case else cases, dispatch=dispatch,
                sandbox_root=mutated_dest, reason=reason + " (mutated)", again=True, timeout=timeout,
                node_ids=nodes)))
    except subprocess.TimeoutExpired as exc:
        _cleanup(mutated_dest)
        _cleanup(baseline_dest)
        _cleanup(scratch)
        return {"status": "not_executed", "instances": {}, "receipts": [],
                "notes": notes + [f"run_suite.py --mine: {exc}"]}

    runs = ([("baseline", base_proc, base_summary)] if own_baseline else []) + [
        ("mutated" if len(launched) == 1 else f"mutated ({case})", proc, summary)
        for case, proc, summary in launched]
    refused = False
    for label, proc, summary in runs:
        if not summary:
            notes.append(f"{label} run: run_suite.py printed no summary (exit {proc.returncode}): "
                         f"{(proc.stderr or proc.stdout or '').strip()[-500:]}")
        elif summary.get("error") and not summary.get("execution_status"):
            # The runner answered with a refusal, not a run: a real run's summary always carries
            # `execution_status`. Its own text names the door; nothing ran, so nothing is read.
            refused = True
            notes.append(f"{label} run: run_suite.py refused it ({summary.get('status') or 'no status'}): "
                         f"{summary['error']}" + (f" {summary['hint']}" if summary.get("hint") else ""))
    if any(not summary for _label, _proc, summary in runs) or refused:
        _cleanup(mutated_dest)
        _cleanup(baseline_dest)
        _cleanup(scratch)
        return {"status": "not_executed", "instances": {}, "receipts": [], "notes": notes}

    # Every row is bound by the id the JOB REQUEST of its own run carries, not by the manifest's
    # (`manifest_from_tests.py` never writes `report_test_id`, and a pytest command under a
    # `junit-xml` profile was bound by an id nobody had recorded: both runs `not_run`, `survived`),
    # and only against the report of the launch that ran ITS case: one case's launch never binds a
    # same-named row of another case's.
    base_rows, base_contracts, base_pytest = [], {}, False
    if own_baseline:
        base_rows = _report_rows(task_root, base_summary, notes, "baseline")
        base_contracts = _run_contracts(task_root, base_summary, notes, "baseline")
        base_pytest = _is_pytest(base_summary.get("command"))
    mutated_runs = {}  # case (None: the whole-case fallback) -> (rows, contracts, pytest?, summary)
    for (case, _proc, summary), (label, _p, _s) in zip(launched, runs[1 if own_baseline else 0:]):
        mutated_runs[case] = (_report_rows(task_root, summary, notes, label),
                              _run_contracts(task_root, summary, notes, label),
                              _is_pytest(summary.get("command")), summary)
    by_author = {r["instance_id"]: r for r in author_results}

    results, baseline_results, unrun = [], [], []
    for target in mutated_receipt["targets"]:
        iid = str(target.get("instance_id") or "")
        node_id = (target.get("node_id") or next(iter(target.get("node_ids") or []), None)
                   or (placed.get(iid) or {}).get("node"))
        bind_target = {**target, "node_id": node_id}
        mut_rows, mut_contracts, mut_pytest, mut_summary = (
            mutated_runs.get((placed.get(iid) or {}).get("case")) or mutated_runs.get(None)
            or ([], {}, False, {}))
        row, note = bind_row(bind_target, mut_contracts, mut_rows, mut_summary.get("reporter"),
                             task_root.name, pytest_command=mut_pytest)
        results.append(target_result(target, row, mut_summary.get("reporter"), mutated_receipt["sandbox"],
                                     command=mut_summary.get("command") or []))
        if not row and note:
            notes.append(f"{iid}: {note}")
        # A mutated target with no outcome is never collected here: `verify()` reads it as the
        # probe's own defect (`probe_defect`, the upstream words, said once). Only the note stays
        # for a row that WAS bound and says nothing about the outcome (a TRX with no outcome).
        if row and results[-1]["status"] == "not_run":
            notes.append(f"{iid}: the mutated run's report row carries no outcome (not_run)")

        if iid in by_author:  # the author's green run stands for the unmutated one
            baseline_results.append(dict(by_author[iid]))
            continue
        base_row, base_note = bind_row(bind_target, base_contracts, base_rows, base_summary.get("reporter"),
                                       task_root.name, pytest_command=base_pytest)
        baseline_results.append({"instance_id": iid, "status": base_row["status"] if base_row else "not_run"})
        if not base_row and base_note and base_note != note:
            notes.append(f"{iid} (baseline): {base_note}")
        if baseline_results[-1]["status"] == "not_run":
            unrun.append((iid, "baseline"))
            if base_row:  # a row was bound and says nothing about the outcome
                notes.append(f"{iid}: the baseline run's report row carries no outcome (not_run)")

    verdict = verify(mutated_receipt, results, baseline_results)
    if placed:  # a launched run leaves its verdict on record, for every target (D11)
        _write_product_records(task_root, dispatch, placed, targets, verdict["proofs"], repo, notes)
    by_result = {str(r["instance_id"]): r for r in results}
    by_baseline = {str(r["instance_id"]): r for r in baseline_results}
    instances = {p["instance_id"]: {**p, "mutated": by_result.get(p["instance_id"]),
                                    "baseline": by_baseline.get(p["instance_id"])}
                for p in verdict["proofs"]}

    # The probe's own defect is answered FIRST (a mutated target with no row, a seam never reached,
    # a timeout - upstream's words, said once); only then the baseline that read nothing. A run
    # with no row is never `survived` on either path.
    status = request_status(verdict, unrun)
    if status == "probe_defect":
        _cleanup(mutated_dest)
        _cleanup(baseline_dest)
        _cleanup(scratch)
        return {"status": "probe_defect", "instances": instances, "receipts": [],
                "notes": notes + [f"{p['instance_id']}: {p['reason']}" for p in verdict["probe_defects"]]}
    if status == "survived":
        # A real survivor is the request's answer, whatever another target's tooling state is: the
        # status never contradicts a `survived` product record (FR-35), and a survivor is never masked
        # by a baseline that read nothing or a site nobody reads. The other targets' reasons stay in the
        # notes, and their own records say `incomplete`, which blocks nothing.
        _cleanup(mutated_dest)
        _cleanup(baseline_dest)
        _cleanup(scratch)
        # An unmet baseline is named here too: a proof that is not valid says why, not only that.
        why = [f"{p['instance_id']}: {p['reason']}" for p in verdict["proofs"] if p.get("reason")]
        if unrun:
            said = ", ".join(sorted({f"{iid} ({which})" for iid, which in unrun}))
            why.append(f"no report row answers for {said}: that part proves nothing either way (a `tooling` "
                       "finding), but it does not hide the survivor above")
        return {"status": "survived", "instances": instances, "receipts": [], "notes": notes + why}
    if status == "not_executed":
        # "The report does not say" is not "the test lets the mutation through" (FR-41): the critic
        # who read `survived` filed test_defect and the author paid a counted round for a gap of
        # the factory (FR-19, FR-46). Nothing is proved either way, so the probe did not execute.
        _cleanup(mutated_dest)
        _cleanup(baseline_dest)
        _cleanup(scratch)
        said = ", ".join(sorted({f"{iid} ({which})" for iid, which in unrun}))
        return {"status": "not_executed", "instances": instances, "receipts": [],
                "notes": notes + [f"no report row answers for {said}: the runs read nothing about it, so "
                                  "the probe proves nothing either way. This is the factory's gap, not a "
                                  "test that survived: record it as a `tooling` finding (nobody's round), "
                                  "never `test_defect`"]}
    if status == "incomplete":
        _cleanup(mutated_dest)
        _cleanup(baseline_dest)
        _cleanup(scratch)
        why = [f"{p['instance_id']}: {p['reason']}" for p in verdict["proofs"] if p.get("reason")]
        if any(p.get("baseline_status") for p in verdict["proofs"]) and not any(
                p.get("site_unread") for p in verdict["proofs"]):
            # The unmutated run was not a pass (red, skipped, errored): a failure of the mutated run
            # cannot be read as the mutation's doing, and nothing was shown about the test either way.
            # The word is the one the product record carries (`_write_product_records`), FR-35.
            return {"status": "incomplete", "instances": instances, "receipts": [],
                    "notes": notes + why + [
                        "the baseline status above is the typed reason (`baseline_status` in the instance): the "
                        "unmutated run of the test was not a pass, so the proof is incomplete, not a survivor. "
                        "Repair that run (or let the author's green stand), then probe again; nothing blocks a "
                        "repeat"]}
        # The mutated run FAILED and the factory cannot yet say where (B-337): not a test that
        # let the mutation through, so never `survived`. The failure itself is readable.
        return {"status": "incomplete", "instances": instances, "receipts": [],
                "notes": notes + why + [
                    "the run's own failure text is readable (`run_suite.py --mine <case> --detail <test>`); "
                    "no receipt is published until the site is read. Record it as a `tooling` finding "
                    "(the factory's gap, nobody's round), never `test_defect`"]}

    receipts, refs = [], {}
    try:
        bindings = manifest_bindings(task_root, mutated_receipt)
        identity = {iid: {**info["now"], "test_file": proof_level.test_file_of(info["entry"])}
                    for iid, info in placed.items()}
        refs = write_sensitivity_receipts(task_root, mutated_receipt, results, bindings, baseline_results,
                                          identity=identity, notes=notes)
        receipts = [dict(ref["receipt_ref"], instance_id=iid) for iid, ref in refs.items()]
    except ValueError as exc:
        notes.append(f"sensitivity receipt: {exc}")

    # t-2064 fix round G, B3 (EP-W, AR-22, AR-28): a receipt whose `scope` is `one_check` proves the ONE check it names and has no
    # level for the test as a whole, so it is NOT published to the manifest - no row ref (it would overwrite a valid live ref, a
    # downgrade) and no `proven` binding (`case_stamp` and `coverage_contract` read that pair without a level, so one proved check of
    # several would read as a proven obligation). The decision reads the scope the receipt just written carries (one source). The
    # critic names the receipt with a `product` entry; a `whole_unlisted` receipt (the factory has no reader for the test's
    # language: its only door) publishes as it always did.
    held_back = {iid: ref for iid, ref in refs.items() if _written_scope(task_root, ref) != proof_level.WHOLE_UNLISTED}
    if held_back:
        notes.append("the receipt proves the one check it names, and the other checks of that test stay owed: it is not "
                     "published to the manifest. The critic names it with a `product` entry in the probe's model file "
                     "(`work/probe-models/<dispatch id>.json`); only that entry counts it. Instances: "
                     + ", ".join(sorted(held_back)))
    refs = {iid: ref for iid, ref in refs.items() if iid not in held_back}
    if refs:
        by_obligation: dict = {}
        # `manifest_put` REPLACES a binding's `instance_ids`, so a second instance of one
        # obligation - or a live `probe_by_code.py` receipt already listing another instance -
        # would be erased by a list of only this run's instances. The list here starts from what
        # the manifest already holds (the same class as probe_by_code.publish_binding, FR-17).
        # Only a `whole_unlisted` receipt reaches this point (above): it is the test's only door and stands for the
        # whole test, so a same or lower level is replaced by it, as before.
        try:
            held = contract.load_json(contract.artifact(task_root, "automation-manifest.json"))
        except (OSError, ValueError):
            held = {}
        held_ids = {str(b.get("obligation_id")): proof_level.without_retracted(b.get("instance_ids"), held)
                    for b in held.get("obligation_bindings") or [] if isinstance(b, dict)}
        for target in mutated_receipt["targets"]:
            obligation_id, iid = target.get("obligation_id"), str(target.get("instance_id") or "")
            if not (obligation_id and iid in refs):
                continue
            row = by_obligation.setdefault(obligation_id, {
                "obligation_id": obligation_id, "instance_ids": list(held_ids.get(str(obligation_id), [])),
                "sensitivity": "proven",
                "proof_kind": "executed_red_probe", "probe_receipt_ref": refs[iid]["receipt_ref"]["path"]})
            if iid not in row["instance_ids"]:
                row["instance_ids"].append(iid)
        # The same fragment says it in both places, because delivery reads one of them and
        # coverage the other. Until 0.7.18 the probe published `obligation_bindings` alone and
        # `check_delivery` looked only at `tests[].sensitivity_proof.receipt_ref`, so four
        # receipts that existed on disk were reported as missing proof, owner `product`, and
        # gate B of TP2-2553 asked for four waivers for work that had been done.
        # `manifest_put` merges `tests[]` by instance id as a patch, so the author's row keeps
        # its file, case links and review.
        test_rows = [{"instance_id": iid, "sensitivity_proof": {"receipt_ref": ref["receipt_ref"]}}
                     for iid, ref in sorted(refs.items())]
        if by_obligation or test_rows:
            fragment_path = scratch / "manifest-fragment.json"
            atomic_json(fragment_path, {"obligation_bindings": list(by_obligation.values()),
                                        "tests": test_rows})
            put = subprocess.run(
                [sys.executable, "-B", str(manifest_put_path), "--task", task_root.name,
                 "--fragment", str(fragment_path)],
                cwd=str(repo), capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=120)
            tail = (put.stdout or put.stderr or "").strip().splitlines()
            notes.append(("manifest_put.py: " + tail[0]) if put.returncode == 0 and tail else
                        f"manifest_put.py: {(put.stderr or put.stdout or '').strip()[-500:]}")

    _cleanup(mutated_dest)
    _cleanup(baseline_dest)
    _cleanup(scratch)
    return {"status": "accepted", "instances": instances, "receipts": receipts, "notes": notes}


# --- --diagnostic: ONE run of a test without the red assert, in a copy (t-1508 R4) ---------------------
# The failure analyst's step of S7 ("One red, one triage"): a Then that sits after a red assert of its own test cannot answer
# while the red stands; to learn whether it would hold, the test is run once WITHOUT the lines that assert the red
# Then, in a disposable copy of the tree. It is the same sequence as `probe` (prepare -> `_run_mine` ->
# `_report_rows` -> `bind_row`/`target_result` -> clean) and publishes nothing: no receipt, no `work/probes/`, no
# manifest row, no binding, no run block (`run_suite` writes none for `--purpose red_probe`). The variant is never a
# test of the story: it is not fingerprinted as one, not an ordinary job of the profile (`ordinary_jobs` leaves out
# `red_probe`, so a later `--mine` takes its `cwd` from an ordinary run, never from this clone) and costs the result
# budget nothing. Its only trace is `evidence/diagnostic-<label>.json`, written by this function alone.

DIAGNOSTIC_KEYS = ("label", "instance_id", "cases", "thens_dropped", "mutation")
DIAGNOSTIC_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
DIAGNOSTIC_ROLE, DIAGNOSTIC_STAGE = "qa-failure-analyst", "S7"
DIAGNOSTIC_SUMMARY_KEYS = ("execution_status", "reporter", "exit_code", "totals", "job_id", "purpose")
DIAGNOSTIC_AGAIN = "diagnostic again: "
DIAGNOSTIC_FORM = ('{"label": "<name>", "instance_id": "<the red test\'s instance id>", "cases": ["<case>"], '
                   '"thens_dropped": [<Then numbers whose asserts the variant removes>], '
                   '"mutation": {"path": "<the test file>", "before_sha256": "<its sha256 now>", '
                   '"replacement_utf8": "<the whole file without those lines>"}}')


def _diagnostic_refusal(message: str, **extra) -> dict:
    return {"status": "refused", "message": message, **extra}


def _without_investigation(running: list) -> tuple:
    """(the dispatches that may host a diagnostic run, the S7 investigation ones): a running investigation pass (purpose word read
    through `controller.s7_part_of`, the one reader) reaches the stand only through the probe's caps, so it is never the host of a
    diagnostic run. A record the reader cannot judge stays a candidate (today's behaviour). Never raises."""
    try:
        import controller
        probing = [d for d in running if controller.s7_part_of(d) == "investigation"]
    except Exception:
        return running, []
    return [d for d in running if d not in probing], probing


def _diagnostic_dispatch(task_root: Path, dispatch: str) -> tuple:
    """(dispatch id, refusal text): the S7 dispatch of the failure analyst this run belongs to. `--dispatch` names it;
    without it the story's one open dispatch is it, several open ones are a refusal that asks for the name."""
    import execution_request as ER
    try:
        controller = json.loads((task_root / "state" / "controller.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        controller = {}
    running = ER.running_dispatches(controller if isinstance(controller, dict) else {})
    running, probing = _without_investigation(running)
    if probing and not running:
        return "", (f"the open dispatch {probing[0].get('id')} is the read-only INVESTIGATION: the diagnostic run is a step of the "
                    "failure analyst's triage, not of the investigation; hand the question back in your digest")
    if dispatch:
        running = [d for d in running if d.get("id") == dispatch]
        if not running:
            return "", (f"no open dispatch {dispatch} in this story: name the id of YOUR open dispatch (the prepare packet "
                        "carries it)")
    elif not running:
        return "", ("no dispatch is open in this story: the diagnostic run is a step of the failure analyst's S7 dispatch, "
                    "which the orchestrator opens (controller.py --operation prepare)")
    elif len(running) > 1:
        return "", ("several dispatches are open (" + ", ".join(str(d.get("id")) for d in running[:4])
                    + "): name yours with --dispatch ID")
    one = running[0]
    if str(one.get("stage")) != DIAGNOSTIC_STAGE or str(one.get("role")) != DIAGNOSTIC_ROLE:
        return "", (f"dispatch {one.get('id')} is {one.get('role')} in {one.get('stage')}: the diagnostic run is the "
                    f"{DIAGNOSTIC_ROLE}'s step of {DIAGNOSTIC_STAGE}. Run it inside that dispatch (--dispatch <its id>); "
                    "from another role or stage, hand the question back in your digest")
    return str(one.get("id")), ""


def _instance_thens(manifest: dict, cases: list, names: set) -> list:
    """The Then numbers the manifest binds to this instance (a `then_bindings` row of one of `cases` that names the
    instance): the clauses its test holds. [] when the manifest names none - then nothing is said of the others."""
    out = set()
    for row in manifest.get("then_bindings") or []:
        if (isinstance(row, dict) and str(row.get("instance_id") or "") in names
                and any(contract.case_matches(str(row.get("case") or ""), case) for case in cases)):
            number = contract.then_number(row.get("then"))
            if number:
                out.add(number)
    return sorted(out)


def _diagnostic_again_word(task_root: Path, iid: str, newest: str) -> dict:
    """`{"decision", "at"}` of the person's word `diagnostic again: <iid>` that passes ONE repeat, else {}.

    Read by `contract.stage_override_values` (the ONE reader of a prefixed word, AR-13), the id compared for EQUALITY: the
    word for `test_move` is no match for `test_move_back`, and `*` names no instance. A revoked record is no word, a pipeline
    that cannot be read gives none (the repeat stays refused, FR-59). The word passes by time (`ER.word_passes`)."""
    import execution_request as ER
    try:
        pipeline = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    for value, entry in contract.stage_override_values(pipeline, DIAGNOSTIC_AGAIN.strip(), DIAGNOSTIC_STAGE):
        word = {"decision": str(entry.get("decision") or ""), "at": str(entry.get("at") or "")}
        if value == iid and ER.word_passes(word, newest):
            return word
    return {}


def _earlier_diagnostics(task_root: Path, iid: str, before: str) -> list:
    """[(path, evidence)] of the diagnostic runs already written for this instance over these test bytes."""
    found = []
    for path in sorted_paths((task_root / "evidence").glob("diagnostic-*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and doc.get("instance_id") == iid and doc.get("original_sha256") == before:
            found.append((path, doc))
    return found


def _diagnostic_red(repo: Path, task_root: Path, case: str, iid: str, notes: list) -> str:
    """"" when the instance's newest result is not green (or the story cannot say), else the refusal: a variant of a green
    test is no diagnosis of a red. A story that cannot tell is no reason to stop the analyst (FR-41, P1): it is a note."""
    import execution_request as ER
    policy, why = ER.load_run_budget()
    if policy is None:
        notes.append(f"{why}: whether {iid} is red now was not checked")
        return ""
    try:
        state = (_fresh_instances(repo, task_root, [case]).get(iid)) or {}
    except Exception as exc:
        notes.append(f"the newest result of {iid} could not be read ({type(exc).__name__}: {str(exc)[:160]}): "
                     "whether it is red now was not checked")
        return ""
    if state.get("state") == "result" and state.get("outcome") == "passed":
        return (f"{iid}: its newest result over these bytes is green ({state.get('job_id')}): a diagnostic run is for a red "
                "test; there is nothing behind a red to learn here")
    return ""


def diagnostic(repo, request_path, task_root, *, dispatch: str = "", timeout: int = 1860) -> dict:
    """ONE run of the test without the lines the variant removes, in a copy. One JSON answer:
    `{"status": "passed"|"failed"|"not_executed"|"already_run"|"refused", ...}`.

    The request is `DIAGNOSTIC_FORM`. Every refusal is decided BEFORE a copy exists and names a door: a request of another
    shape, a dispatch that is not the analyst's S7 one (or several open and none named), an instance the story does not place
    or whose newest result is green, a `before_sha256` that is not the file's bytes now, a variant that is not a pure removal
    of lines INSIDE the instance's function (`variant_shape`: lines added or changed, nothing removed, lines moved, a change
    outside the function), `thens_dropped` empty or naming a Then the instance does not hold, a replacement that is not
    UTF-8. The error direction is the refusal: nothing is run on a doubt.

    ONE run per (instance, `before_sha256`): the evidence file is the account. A second request over the same bytes is
    `already_run` with the path, and nothing starts - unless a person's word `diagnostic again: <instance>` (waiver.py
    --stage S7 --block ... --words-file) was recorded AFTER that evidence; the word passes one repeat. New bytes of the file
    are a new key. A `label` whose file exists is refused, the file untouched.

    Then the sequence of `probe` (prepare, `_run_mine` with `--purpose red_probe --sandbox-root <copy>`, `_report_rows`,
    `bind_row`, `target_result`) and the copy is removed in `finally`, whatever happened. A run that never started (the runner
    refused or printed nothing) is `not_executed` with no evidence and spends no slot; a run that started is written:
    `passed` (the row passed), `failed` (red or error), `not_executed` (no row answers: the stand fell, the test was
    skipped). `thens` is written only when the outcome is unambiguous: `passed` -> every Then the manifest binds to the
    instance and the variant keeps is `held`; `not_executed` -> `not_reached`; `failed` -> no `thens`, the analyst reads
    `failure_line` (its line numbers are the VARIANT's). Never a pass on an unknown."""
    import variant_shape
    repo = Path(repo).resolve()
    task_root = Path(task_root).resolve()
    notes: list = []
    try:
        request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _diagnostic_refusal(f"the request cannot be read as UTF-8 JSON ({exc}); write {DIAGNOSTIC_FORM}")
    if not isinstance(request, dict) or set(request) != set(DIAGNOSTIC_KEYS) or not isinstance(request.get("mutation"), dict):
        return _diagnostic_refusal(f"the request must be an object with exactly the keys {', '.join(DIAGNOSTIC_KEYS)}; write "
                                   f"{DIAGNOSTIC_FORM}")
    label, iid = request["label"], request["instance_id"]
    cases = request["cases"]
    dropped = request["thens_dropped"]
    if not (isinstance(label, str) and DIAGNOSTIC_LABEL.match(label)):
        return _diagnostic_refusal(f"`label` {label!r} is not a name: letters, digits, '.', '_' and '-', up to 64, starting "
                                   "with a letter or digit (it becomes evidence/diagnostic-<label>.json)")
    if not (isinstance(iid, str) and iid.strip()):
        return _diagnostic_refusal("`instance_id` is empty: name the instance id of the red test (manifest `tests[]`)")
    if not (isinstance(cases, list) and cases and all(isinstance(c, str) and c.strip() for c in cases)):
        return _diagnostic_refusal("`cases` must list the case ids the dispatch covers (a non-empty list of strings)")
    if not (isinstance(dropped, list) and dropped and all(
            isinstance(n, int) and not isinstance(n, bool) and n >= 1 for n in dropped) and len(set(dropped)) == len(dropped)):
        return _diagnostic_refusal("`thens_dropped` must list, once each, the numbers (>= 1) of the Thens whose asserts the "
                                   "variant removes: a variant that drops no Then diagnoses nothing")
    mutation = request["mutation"]
    path, before, replacement = mutation.get("path"), mutation.get("before_sha256"), mutation.get("replacement_utf8")
    if set(mutation) != {"path", "before_sha256", "replacement_utf8"} or not all(
            isinstance(v, str) for v in (path, before, replacement)) or not path.strip() or not PIN_RE.match(before):
        return _diagnostic_refusal("`mutation` must be {path, before_sha256 (64 hex), replacement_utf8}, all text, exactly "
                                   "those keys")
    try:
        replacement.encode("utf-8")
    except UnicodeEncodeError:
        return _diagnostic_refusal("`mutation.replacement_utf8` is not valid UTF-8 text: write the file again as plain text")
    try:
        target_file = inside(repo, path)
    except ValueError as exc:
        return _diagnostic_refusal(f"`mutation.path` {path!r}: {exc}; name a file of the project, relative to its root")
    if not target_file.is_file():
        return _diagnostic_refusal(f"`mutation.path` {path!r} is not a file of the project")
    if is_generated(path, artifact_prefixes(repo)):
        return _diagnostic_refusal(f"`mutation.path` {path!r} is a file the factory generates, not a test")

    disp, why = _diagnostic_dispatch(task_root, dispatch)
    if why:
        return _diagnostic_refusal(why)
    manifest = _manifest_of(task_root)
    placed, missing = _place_targets(manifest, cases, [{"instance_id": iid}])
    if missing:
        return _diagnostic_refusal(" ".join(missing.values()))
    info = placed[iid]
    node = str(info["node"])
    file_part, _sep, function = node.replace("\\", "/").rpartition("::")
    function = (function or node).split("[", 1)[0].rsplit(".", 1)[-1] if not _sep else function.split("[", 1)[0]
    if _sep and file_part.split("::", 1)[0] != path.replace("\\", "/"):
        return _diagnostic_refusal(f"the variant is of {path!r}, but {iid} lives in {file_part.split('::', 1)[0]!r}: "
                                   "the diagnostic variant is the instance's own test file")
    try:
        original = target_file.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return _diagnostic_refusal(f"{path!r} is not UTF-8 text; a variant of it cannot be compared line by line")
    if digest(target_file) != before:
        return _diagnostic_refusal(f"`before_sha256` is not the sha256 of {path!r} now ({digest(target_file)}): the file "
                                   "changed or the hash is from another copy; read the file again and send the new hash "
                                   "with the variant made from these bytes")

    shape = variant_shape.variant_shape(original, replacement, function)
    if not shape["function_found"]:
        return _diagnostic_refusal(f"the function {function!r} of {iid} is not found in {path!r}: the variant cannot be "
                                   "placed")
    if shape["added"] or not shape["removed"] or shape["moved"] or shape["outside"]:
        what = ("adds or changes lines" if shape["added"] else "moves lines" if shape["moved"]
                else "removes no line" if not shape["removed"] else f"changes lines outside {function}")
        return _diagnostic_refusal(f"the variant {what}: a diagnostic variant only REMOVES lines of the test function "
                                   f"{function} (the asserts of the Thens in `thens_dropped`), nothing is added, changed or "
                                   "moved, and nothing outside the function is touched")
    names = {str(contract.test_instance_id(info["entry"]))} | set(contract.instance_id_aliases(info["entry"]))
    held = _instance_thens(manifest, cases, names)
    if held and not set(dropped) <= set(held):
        return _diagnostic_refusal(f"`thens_dropped` names Then {', '.join(str(n) for n in sorted(set(dropped) - set(held)))}, "
                                   f"which {iid} does not hold (the manifest binds Thens {', '.join(str(n) for n in held)} to it)")

    earlier = _earlier_diagnostics(task_root, iid, before)
    if earlier:
        newest = max(str(doc.get("recorded_at") or "") for _p, doc in earlier)
        message = f"{DIAGNOSTIC_AGAIN}{iid}"
        word = _diagnostic_again_word(task_root, iid, newest)
        if word:
            notes.append(f"a person's recorded word passes this repeat of the diagnostic run: {word['decision']}")
        else:
            shown = earlier[-1][0].relative_to(task_root).as_posix()
            return {"status": "already_run", "evidence": shown, "notes": notes,
                    "words": (f"{iid} was already run without Then {', '.join(str(n) for n in earlier[-1][1].get('thens_dropped') or [])} "
                              f"on these bytes: read {shown}. One diagnostic run per test and bytes; change the test file "
                              f"for another key, or a person's word passes a repeat (waiver.py --stage {DIAGNOSTIC_STAGE} "
                              f"--block \"{message}\" --words-file <file>).")}
    evidence_path = task_root / "evidence" / f"diagnostic-{label}.json"
    if evidence_path.exists():
        return _diagnostic_refusal(f"label taken: {evidence_path.relative_to(task_root).as_posix()} exists and is not "
                                   "overwritten; choose another label")
    case = info["case"]
    red = _diagnostic_red(repo, task_root, case, iid, notes)
    if red:
        return _diagnostic_refusal(red)

    destination = repo.parent / f"{repo.name}-redprobe-{uuid.uuid4().hex[:10]}"
    run_suite_path = Path(__file__).resolve().parent / "run_suite.py"
    target = {"path": path, "before_sha256": before, "replacement_utf8": replacement, "instance_id": iid,
              "expected_location": f"{path}:1", "expected_reason": "diagnostic variant"}
    try:
        try:
            receipt = prepare(repo, destination, {"mutations": [target], "cases": cases}, str(task_root))
        except ValueError as exc:
            return {"status": "not_executed", "notes": notes + [f"prepare: {exc}"]}
        proc, summary = _run_mine(run_suite_path, repo, [case], dispatch=disp, sandbox_root=destination,
                                  reason=f"diagnostic variant of {iid} for {case}", again=True, timeout=timeout,
                                  node_ids=_case_nodes(placed, case))
        if not summary:
            return {"status": "not_executed", "notes": notes + [
                f"run_suite.py printed no summary (exit {proc.returncode}): {(proc.stderr or proc.stdout or '').strip()[-500:]}"]}
        if summary.get("error") and not summary.get("execution_status"):
            return {"status": "not_executed", "notes": notes + [
                f"run_suite.py refused the run ({summary.get('status') or 'no status'}): {summary['error']}"
                + (f" {summary['hint']}" if summary.get("hint") else "")]}
        rows = _report_rows(task_root, summary, notes, "diagnostic")
        contracts = _run_contracts(task_root, summary, notes, "diagnostic")
        row, note = bind_row({**target, "node_id": node}, contracts, rows, summary.get("reporter"), task_root.name,
                             pytest_command=_is_pytest(summary.get("command")))
        result = target_result(target, row, summary.get("reporter"), receipt["sandbox"],
                               command=summary.get("command") or [])
        if not row and note:
            notes.append(f"{iid}: {note}")
        variant_sha = receipt["mutated_hashes"][path]
    except subprocess.TimeoutExpired as exc:
        return {"status": "not_executed", "notes": notes + [f"run_suite.py --mine: {exc}"]}
    except Exception as exc:     # the factory's own failure is a line, not a traceback; the copy goes in `finally`
        return {"status": "not_executed", "notes": notes + [f"the diagnostic run broke ({type(exc).__name__}: {str(exc)[:300]})"]}
    finally:
        _cleanup(destination)

    status = {"passed": "passed", "failed": "failed", "error": "failed"}.get(result["status"], "not_executed")
    failure = ""
    if status == "failed":
        reason = " ".join(str(result.get("reason") or "").split())[:500]
        failure = f"{result['location']}: {reason}" if result.get("location") else reason
    evidence = {"instance_id": iid, "label": label, "cases": cases, "dispatch_id": disp, "original_sha256": before,
                "variant_sha256": variant_sha, "removed_lines": shape["removed"], "thens_dropped": sorted(dropped),
                "run_summary": {k: summary[k] for k in DIAGNOSTIC_SUMMARY_KEYS if k in summary}, "status": status,
                "failure_line": failure or None, "line_numbers_of": "variant",
                "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    left = [n for n in held if n not in set(dropped)]
    if status != "failed":
        if left:
            evidence["thens"] = [{"then": n, "outcome": "held" if status == "passed" else "not_reached"} for n in left]
        else:
            notes.append("the manifest binds no other Then to this instance: no `thens` are written")
    try:
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        with open(evidence_path, "x", encoding="utf-8") as handle:     # never over another file
            handle.write(json.dumps(evidence, ensure_ascii=False, indent=1) + "\n")
    except FileExistsError:
        return _diagnostic_refusal(f"label taken: {evidence_path.relative_to(task_root).as_posix()} appeared during the run; "
                                   "it is not overwritten; choose another label")
    except OSError as exc:
        return {"status": "not_executed", "notes": notes + [f"the evidence file could not be written ({exc})"]}
    return {"status": status, "evidence": {"path": evidence_path.relative_to(task_root).as_posix(),
                                           "sha256": digest(evidence_path)},
            "failure_line": evidence["failure_line"], "thens": evidence.get("thens"), "notes": notes}


def main():
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    import role_cli
    parser = argparse.ArgumentParser(__doc__, epilog=role_cli.epilog("red_sandbox.py"),
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo")
    parser.add_argument("--destination")
    parser.add_argument("--request", required=True)
    parser.add_argument("--verify-receipt")
    parser.add_argument("--task-root", help="the story's artifact folder: publishes the proof; "
                                            "at prepare time it lets a person's recorded S5 "
                                            "decision pass a node-id refusal")
    parser.add_argument("--bindings", help="optional JSON instance binding map (pre-0.7.7 runs); "
                                           "without it the bindings are read from the manifest")
    parser.add_argument("--baseline", help="JSON array of the SAME instances run unmutated; a "
                                           "target whose mutated run matches it is a probe defect")
    parser.add_argument("--probe", action="store_true",
                        help="prepare, run mutated+baseline, verify, publish and clean in one call")
    parser.add_argument("--dispatch", default="", help="--probe: the open S5 dispatch id; --diagnostic: the failure "
                                                        "analyst's open S7 dispatch id; omit when the story has only one")
    parser.add_argument("--diagnostic", action="store_true",
                        help="ONE run of a test without the asserts of the Thens its variant drops, in a copy "
                             "(needs --repo, --request, --task-root); writes evidence/diagnostic-<label>.json only")
    args = hooklib.exact_options(parser).parse_args()
    if args.task_root is not None:      # a GIVEN root names an existing story before anything is prepared or published
        hooklib.story_cli("red_sandbox.py", root=args.task_root, key_flag=None)
    if args.diagnostic:
        if not (args.repo and args.request and args.task_root):
            parser.error("--diagnostic requires --repo, --request and --task-root")
        result = diagnostic(args.repo, args.request, args.task_root, dispatch=args.dispatch)
        print(json.dumps(result, ensure_ascii=False))
        if result.get("status") == "refused":
            # the refusal is also an instruction: the registry's card (what to write, how to prove it) follows it on stderr
            role_cli.refuse("red_sandbox.py --diagnostic", str(result.get("message") or "refused"))
        sys.exit(2 if result.get("status") == "refused" else 0 if result.get("status") in (
            "passed", "failed", "already_run") else 1)
    if args.probe:
        if not (args.repo and args.request and args.task_root):
            parser.error("--probe requires --repo, --request and --task-root")
        result = probe(args.repo, args.request, args.task_root,
                       destination=args.destination, dispatch=args.dispatch)
        print(json.dumps(result, ensure_ascii=False))
        if result.get("status") == "node_id_mismatch":
            sys.exit(2)
        sys.exit(0 if result.get("status") in ("accepted", "survived", "already_probed") else 1)
    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8")) if args.baseline else None
    if args.verify_receipt:
        receipt = json.loads(Path(args.verify_receipt).read_text(encoding="utf-8"))
        if args.task_root or args.bindings:
            if not args.task_root:
                parser.error("receipt publication requires --task-root")
            bindings = (json.loads(Path(args.bindings).read_text(encoding="utf-8"))
                        if args.bindings else manifest_bindings(Path(args.task_root), receipt))
            print(json.dumps({"status": "accepted", "sensitivity_proofs":
                              write_sensitivity_receipts(args.task_root, receipt,
                                                         request["results"], bindings, baseline)}))
        else:
            print(json.dumps(verify(receipt, request["results"], baseline)))
    else:
        try:
            receipt = prepare(args.repo, args.destination, request, args.task_root)
        except NodeIdMismatch as exc:
            # The runner's refusal shape, so a role meets one message, not two.
            print(json.dumps({"status": "node_id_mismatch", "missing": exc.missing,
                              "message": str(exc)}))
            sys.exit(2)
        except (MutationConflict, SetupRefused) as exc:
            # The request's own shape is wrong (or the table it names): one line of JSON and exit 2 (never a
            # traceback), nothing prepared. The refusal names the door.
            print(json.dumps({"status": "refused", "message": str(exc)}))
            sys.exit(2)
        except SetupFailed as exc:
            # The install ran and did not establish its result: the code and the tail travel with it.
            print(json.dumps({"status": "setup_failed", "exit_code": exc.exit_code,
                              "output_tail": exc.output_tail, "message": str(exc)}))
            sys.exit(1)
        out = {"status": receipt["status"], "sandbox": receipt["sandbox"],
               "receipt": str(Path(args.destination) / ".qa-probe.json"),
               "target_count": len(receipt["targets"])}
        check = receipt.get("node_id_check") or {}
        if check.get("status") != "no_pinned_ids":
            # The real spelling is what the red_probe request must name; print it here so the
            # role never opens the receipt to find out what the factory re-pinned.
            out["node_id_check"] = check
            out["node_ids"] = {str(t.get("instance_id")): pinned_ids(t)
                               for t in receipt["targets"] if pinned_ids(t)}
        print(json.dumps(out))


if __name__ == "__main__":
    main()
