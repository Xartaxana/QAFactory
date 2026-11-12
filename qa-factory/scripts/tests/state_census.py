"""The census of stored environment facts (t-304 N0): a MEASURER, not package logic. It writes nothing into the package.

Not a test itself (no `test_` prefix, so selftest does not run it on its own); `test_state_portability.py` imports it, carries
the ratchet over its baseline, and has the `--report` / `--write-baseline` flags.

What it does. Two canary WORLDS (A: the project folder `ZQ7RT0K4` at depth 1; B: `KX4WQ9Z2/sub/deep` at depth 3), each with its
own package copy, its own home (HOME, USERPROFILE, CLAUDE_CONFIG_DIR), its own interpreter (`python -m venv --without-pip`) and
its own temp folder, run nine flows (F1..F9: the controller, the driver, the inject hook, a fresh install, run_suite --mine,
context_bundle, cost_capture, the runtime probe over a fake docker). Each flow runs in A, again in A (the noise control: what
differs between two runs of identical inputs) and in B. Every file a flow produced and every stdout it printed is scanned by four
detectors:

  value         every canary token in any case, the spellings of the test process's interpreter, the real home and the real
                temp folder (per JSON leaf, so that a hit has a pointer; raw bytes in UTF-8 and UTF-16-LE for the rest)
  key           a closed list of key names that carry a machine fact whatever the value (`fixtures/env-fact-keys.json`, FR-13)
  host          this machine's name, only when it is 6 characters or longer (a short one matches by chance)
  differential  values under hash / digest / fingerprint / id keys are compared between the worlds; a key that already differs
                between the two A runs is NOISE and is reported apart, never as a hit

Error directions (FR-28, FR-41). A writer no flow reaches is MISSED (the report lists those: `not_exercised`); a file over the
size cap is `not_scanned` and FAILS the run, never "clean"; a flow that produced nothing or exited non-zero FAILS; a missing key
list FAILS (a missing detector is never a pass). A false positive needs a canary token to appear by chance.

The baseline (`fixtures/env-facts-baseline.json`) is a list of DEBTS, not an expectation (FR-58): every row names the node that
removes it, a hit outside it fails, and a row with no hit fails as stale, so it only shrinks. The rows are measured facts about
the code as found, never "what is right".

Everything here is English (FR-30). Tokens are 8 or fewer uppercase alphanumerics, so where 8.3 names exist the short alias
equals the name.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))       # story_run_common (flow F3 reuses its stub claude)
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))       # machine_facts: the package's spelling generator
FIXTURES = HERE / "fixtures"
KEYS_FILE = FIXTURES / "env-fact-keys.json"
BASELINE_FILE = FIXTURES / "env-facts-baseline.json"
# the hand-written sections of the report (how to read, the new-N rows, limits, experiments): they live in the repository that
# develops the package, not in the package, so a package copied elsewhere has none and says so (render_markdown)
NOTES_FILE = PACKAGE.parents[1] / "experiments" / "fr60" / "census-notes.md"
CENSUS_VERSION = 1
SIZE_CAP = 8 * 1024 * 1024          # E8: a file of exactly this size is scanned, one byte more is `not_scanned`
ARENA_PREFIX = "qa-census-"
FACTS = ("project_root", "plugin_root", "home", "python", "tmp", "host", "container", "digest", "pid", "other_abs")
STEP_TIMEOUT_S = 300
WORKERS = max(2, min(8, (os.cpu_count() or 4)))      # flows in flight at once: each is its own set of processes, mostly waiting on them

# World A / B: where the project lives and what each piece of the machine is called. Every token is <= 8 uppercase
# alphanumerics (N0-K8). The container and the digest belong to the fake docker, shared by both worlds: a container is not a place.
WORLDS = {
    "A": {"project": "ZQ7RT0K4", "sub": (), "package": "PK4ZQ7RT", "home": "H0MZQ7RT", "python": "PYZQ7RT0"},
    "B": {"project": "KX4WQ9Z2", "sub": ("sub", "deep"), "package": "PK9WQ4KX", "home": "H0MWQ9KX", "python": "PYWQ9KX0"},
}
CONTAINER = "CTZQ7RT0"
DIGEST = "sha256:" + "d7" * 32
HEAD_SHA = "0cc6c4f1" + "a" * 32
WORLD_OF_RUN = {"A": "A", "A2": "A", "B": "B"}      # the noise run is the same world built again at the same place


def canary_tokens() -> dict:
    """Every path-like canary token (N0-K8 checks the length of each): label -> token."""
    out = {}
    for letter, spec in WORLDS.items():
        for kind in ("project", "package", "home", "python"):
            out[f"{kind}_{letter.lower()}"] = spec[kind]
    out["container"] = CONTAINER
    return out


# What the TEST PROCESS knew before any redirection: its real home, its real temp folder, its interpreters, this machine's name.
REAL = {"home": os.path.expanduser("~"), "tmp": tempfile.gettempdir(),
        "pythons": tuple(dict.fromkeys(p for p in (sys.executable, getattr(sys, "_base_executable", "")) if p)),
        "host": socket.gethostname() or os.environ.get("COMPUTERNAME", "")}


# --- the data files (FR-13) --------------------------------------------------------------------------------------

class DetectorMissing(Exception):
    """The key list is absent or unreadable: a census with no key detector is not a clean census (E9)."""


def load_keys(path: Path = KEYS_FILE) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise DetectorMissing(f"the key list {path} cannot be read ({exc.__class__.__name__}); a missing detector is never a "
                              "pass: restore fixtures/env-fact-keys.json") from exc
    except ValueError as exc:
        raise DetectorMissing(f"the key list {path} is not valid JSON ({exc}); restore fixtures/env-fact-keys.json") from exc
    keys = data.get("keys") if isinstance(data, dict) else None
    if not isinstance(keys, list) or not keys or not all(isinstance(k, dict) and k.get("key") and k.get("fact") in FACTS
                                                          for k in keys):
        raise DetectorMissing(f"the key list {path} holds no usable `keys` rows ({{key, fact}}, fact one of {list(FACTS)})")
    patterns = data.get("differential_keys")
    if not isinstance(patterns, list) or not patterns:
        raise DetectorMissing(f"the key list {path} holds no `differential_keys`")
    return {"keys": {k["key"].lower(): k["fact"] for k in keys}, "differential": [str(p).lower() for p in patterns]}


# --- spellings of a path -----------------------------------------------------------------------------------------

# `short83`, `path_variants` and the alternation builder moved to the package module `machine_facts` (CL1-1): one generator of the
# spellings for this measurer and for the collect redactor. The old names stay importable from here.
import machine_facts as _mf  # noqa: E402
from machine_facts import MIN_HOST_CHARS, machine_table, path_variants  # noqa: E402
_alternation, short83 = _mf.alternation, _mf.short83


# --- the value detector ------------------------------------------------------------------------------------------

_STOP = "\"'<>|,;(){}[]"


class Hit(tuple):
    """(fact, detector, spelling). A tuple so that it can sit in a set."""
    __slots__ = ()

    def __new__(cls, fact, detector, spelling):
        return tuple.__new__(cls, (fact, detector, spelling))

    fact = property(lambda self: self[0])
    detector = property(lambda self: self[1])
    spelling = property(lambda self: self[2])


class Detector:
    """Value + host detection over a string, built per world (its own tokens) from what the test process knew BEFORE any
    redirection. A match inside a longer match (the home folder inside the interpreter's path) is dropped; the arena folder in
    front of a canary path is dropped too, because the canary names the fact."""

    def __init__(self, tokens: dict, *, real_home: str = "", real_tmp: str = "", arena: str = "", pythons=(), host: str = "",
                 shared: dict | None = None):
        self.canaries = {t: f for t, f in tokens.items()}                      # original-case token -> fact
        self.shared = dict(shared or {})
        table = machine_table(home=real_home, tmp=real_tmp, pythons=pythons, host=host)       # a short home and a short host: guarded / skipped
        self.host = table.host
        self.arena_name = Path(arena).name if arena else ""
        self.patterns = []                                                      # (fact, kind, regex, {text: label} | {text})
        for token, fact in {**self.canaries, **self.shared}.items():
            self.patterns.append((fact, "token", re.compile(re.escape(token), re.I), {token}))
        self.patterns.extend(table.rows)
        variants = path_variants(arena)
        if variants:
            self.patterns.append(("tmp", "arena", _alternation(variants), variants))
        self._canary_low = [t.lower() for t in {**self.canaries, **self.shared}]

    @staticmethod
    def _run(text: str, start: int, end: int) -> str:
        left = start
        while left > 0 and left > start - 260 and not text[left - 1].isspace() and text[left - 1] not in _STOP:
            left -= 1
        right = end
        while right < len(text) and right < end + 260 and not text[right].isspace() and text[right] not in _STOP:
            right += 1
        return text[left:right]

    def _spelling(self, text: str, start: int, end: int, known) -> str:
        matched = text[start:end]
        if isinstance(known, dict):
            label = known.get(matched)
            if label is None:
                return "short83" if re.search(r"~\d", matched) else "lower"
            if label != "raw":
                return label
        elif matched not in known:
            return "lower"
        run = self._run(text, start, end)
        if "\\\\" in run:
            return "json_escaped"
        if "\\" in run:
            return "raw"
        if "/" in run:
            return "forward"
        if "--" in run:
            return "slug"
        return "raw"

    def scan_text(self, text: str) -> set:
        if not text:
            return set()
        found = []
        for fact, kind, rx, known in self.patterns:
            for m in rx.finditer(text):
                found.append((m.start(), m.end(), fact, kind, known))
        if not found:
            return set()
        found.sort(key=lambda t: (t[0], -(t[1] - t[0])))
        kept = []
        for start, end, fact, kind, known in found:
            if any(start >= ks and end <= ke for ks, ke, *_rest in kept):
                continue
            emit = True
            if fact in ("home", "tmp") and kind in ("path", "arena"):
                # the real home, the real temp folder and the arena are only the PREFIX of every world path (the arena sits in
                # the temp folder, which sits in the home): followed by a canary token or by the arena's own name the prefix
                # names no fact, the canary does. It still absorbs what it contains, so the shorter prefix is not counted either.
                tail = re.split(r"[\s\"'<>|,;(){}\[\]]", text[end:end + 300].lower(), 1)[0]
                if any(c in tail for c in self._canary_low) or (self.arena_name and self.arena_name.lower() in tail):
                    emit = False
            kept.append((start, end, fact, kind, known, emit))
        return {Hit(fact, "host" if kind == "host" else "value", self._spelling(text, start, end, known))
                for start, end, fact, kind, known, emit in kept if emit}


def make_detector(label: str, arena=None) -> Detector:
    """The detector of one world, made from the canary tokens of its spec and what this process knew before redirection."""
    spec = WORLDS[WORLD_OF_RUN.get(label, label)]
    tokens = {spec["project"]: "project_root", spec["package"]: "plugin_root", spec["home"]: "home", spec["python"]: "python"}
    return Detector(tokens, real_home=REAL["home"], real_tmp=REAL["tmp"], arena=str(arena or ""), pythons=REAL["pythons"],
                    host=REAL["host"], shared={CONTAINER: "container", "d7" * 32: "digest"})


# --- normalising names and pointers ------------------------------------------------------------------------------

_TOKEN_NAMES = sorted({t.lower() for t in canary_tokens().values()}, key=len, reverse=True)
_ID_KEY = re.compile(r"^(?:[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*-\d[A-Za-z0-9-]*|[0-9a-f]{8,}|\d+|[A-Za-z]\d{2,}|SRC-[0-9a-f]+)$")
_HEX_RUN = re.compile(r"(?<![0-9A-Za-z])[0-9a-f]{8,}(?![0-9A-Za-z])")
_BIG_NUM = re.compile(r"\d{5,}")         # stamps (20261002, 234542) and process ids (command-25004.jsonl)
_DISPATCH = re.compile(r"S\d+-(?:qa-[a-z-]+?|code-only)-\d+")


def norm_key(key) -> str:
    """A JSON object key as it is written in a pointer: an id-like key (a dispatch, a task, a case, a hash) is `*`, so that one
    writer is one pointer however many ids it wrote."""
    key = str(key)
    low = key.lower()
    if "/" in key or "\\" in key or ":" in key or any(t in low for t in _TOKEN_NAMES):
        return "*"
    return "*" if _ID_KEY.match(key) else key


def pointer_of(parts) -> str:
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def norm_name(name: str) -> str:
    """A file name with its ids made `*`: hashes, millisecond stamps, dispatch ids, canary tokens."""
    out = name
    for token in _TOKEN_NAMES:
        out = re.sub(re.escape(token), "<CANARY>", out, flags=re.I)
    out = _DISPATCH.sub("<DISPATCH>", out)
    out = re.sub(r"\d{8}T\d+Z", "*", out)               # an ISO stamp without separators
    out = _HEX_RUN.sub("*", out)
    return _BIG_NUM.sub("*", out)


def norm_rel(rel: str) -> str:
    """A path under a project folder as a PATTERN: the task folder is `<TASK>`, the ids in names are `*`."""
    parts = rel.replace("\\", "/").split("/")
    out = []
    for i, part in enumerate(parts):
        if i >= 1 and parts[i - 1] == "artifacts":
            out.append("<TASK>")
        else:
            out.append(norm_name(part))
    return "/".join(out)


# --- scanning one artifact ---------------------------------------------------------------------------------------

class Scan:
    """What one scanned artifact gave: hits (pointer, fact, detector, spelling), the values the differential compares, and a
    verdict on whether it could be scanned at all."""

    def __init__(self):
        self.hits = set()               # (pointer, fact, detector, spelling)
        self.values = {}                # pointer -> [text]
        self.not_scanned = None         # a reason, or None

    def add(self, pointer, hit: Hit):
        self.hits.add((pointer, hit.fact, hit.detector, hit.spelling))


def _decode(data: bytes) -> str:
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    return data.decode("utf-8-sig", errors="replace")


def _kind_of(name: str, text: str) -> str:
    low = name.lower()
    if low.endswith(".jsonl"):
        return "jsonl"
    if low.endswith(".json"):
        return "json"
    if text.lstrip()[:1] in ("{", "["):
        try:
            json.loads(text)
            return "json"
        except ValueError:
            return "text"
    return "text"


def scan_bytes(name: str, data: bytes, det: Detector, keys: dict, *, cap: int = SIZE_CAP) -> Scan:
    """Scan one artifact. `name` only picks the parser (.json / .jsonl / anything else is text)."""
    scan = Scan()
    if len(data) > cap:
        scan.not_scanned = f"size {len(data)} bytes is over the cap of {cap}"
        return scan
    texts = [_decode(data)]
    if b"\x00" in data and data[:2] not in (b"\xff\xfe", b"\xfe\xff"):
        texts.append(data.decode("utf-16-le", errors="replace"))
    kind = _kind_of(name, texts[0])
    if kind == "json":
        try:
            _walk(json.loads(texts[0]), [], det, keys, scan, "")
        except ValueError:
            kind = "text"
    elif kind == "jsonl":
        for line in texts[0].splitlines():
            if not line.strip():
                continue
            try:
                _walk(json.loads(line), [], det, keys, scan, "#*")
            except ValueError:
                for hit in det.scan_text(line):
                    scan.add("#*", hit)
    if kind in ("json", "jsonl"):
        # a hit the structural walk could not place (a number, a key of an odd shape) is still a hit: pointer ""
        have = {f for _p, f, _d, _s in scan.hits}
        raw = set()
        for text in texts:
            raw |= det.scan_text(text)
        for hit in raw:
            if hit.fact not in have:
                scan.add("", hit)
    else:
        for text in texts:
            for hit in det.scan_text(text):
                scan.add("", hit)
        # a key that carries a machine fact whatever the value, in a `key: value` text (YAML, front matter)
        for line in texts[0].splitlines():
            m = re.match(r"\s*-?\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(\S.*)$", line)
            if m and m.group(1).lower() in keys["keys"]:
                scan.add("", Hit(keys["keys"][m.group(1).lower()], "key", "raw"))
    return scan


def _diff_key(key, keys: dict) -> bool:
    low = str(key).lower()
    return any(fnmatch.fnmatchcase(low, pat) for pat in keys["differential"])


def _walk(value, parts: list, det: Detector, keys: dict, scan: Scan, prefix: str) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            here = parts + [norm_key(k)]
            where = prefix + pointer_of(here)
            for hit in det.scan_text(str(k)):
                scan.add(where, hit)
            fact = keys["keys"].get(str(k).lower())
            # a key of the list with a NON-EMPTY scalar value (an empty string, null and a boolean name no machine)
            if fact and v is not None and v != "" and not isinstance(v, (dict, list, bool)):
                scan.add(where, Hit(fact, "key", "raw"))
            if _diff_key(k, keys) and isinstance(v, (str, int, float)) and not isinstance(v, bool):
                scan.values.setdefault(where, []).append(str(v))
            _walk(v, here, det, keys, scan, prefix)
    elif isinstance(value, list):
        for item in value:
            _walk(item, parts + ["*"], det, keys, scan, prefix)
    elif isinstance(value, str):
        for hit in det.scan_text(value):
            scan.add(prefix + pointer_of(parts), hit)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        for hit in det.scan_text(str(value)):
            scan.add(prefix + pointer_of(parts), hit)


# --- the world ---------------------------------------------------------------------------------------------------

def rmtree(path) -> None:
    def force(func, target, _info):
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            pass
    if not Path(path).exists():
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=force)
    else:
        shutil.rmtree(path, onerror=force)


# the helper the flows run with the world's interpreter, from the world's package copy: a driver-shaped `known_paths`, and the
# docker seam of the runtime probe (the seam style of test_runtime_probe_onboarding K-IMG: the container and its image answer,
# nothing else does)
HELPER = r'''
import json, os, sys, types
from pathlib import Path
package, mode = Path(sys.argv[1]), sys.argv[2]
sys.path.insert(0, str(package / "scripts"))
if mode == "known_paths":
    project, task = sys.argv[3], sys.argv[4]
    os.environ["CLAUDE_PROJECT_DIR"] = project
    os.chdir(project)
    import story_run
    ns = types.SimpleNamespace(task=task, answer=None, until="end", dry_run=True, model="sonnet", plugin_dir=str(package),
                               project=project, mr=None, branch=None, commit=None, ungrounded=False, ticket_file=None,
                               env=None, branch_suffix="", max_boundaries=10)
    print(json.dumps(story_run.Driver(ns).known_paths()))
elif mode == "probe":
    container, digest, head = sys.argv[3], sys.argv[4], sys.argv[5]
    import runtime_probe as R
    def no_sha(c, path, timeout):
        raise RuntimeError("docker exec " + c + " sha256sum " + path + ": No such file or directory")
    def run(argv, timeout):
        if argv[:2] == ["docker", "inspect"]:
            return (0, digest + "\n", "")
        if argv[3:5] == ["test", "-d"]:
            return (1, "", "")
        return (0, head + "\n", "")
    R.sha_container, R.run_command = no_sha, run
    sys.argv = ["runtime_probe.py"] + sys.argv[6:]
    raise SystemExit(R.main())
'''


def _ignore_for_copy(directory, names):
    here = Path(directory)
    out = []
    for name in names:
        if name in ("__pycache__", ".git"):
            out.append(name)
        elif name == "tests" and here.name == "scripts":
            out.append(name)             # the fingerprint excludes `tests` too, so the copy fingerprints the same
    return out


def _venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


class World:
    """One canary world: a folder tree under the shared arena. `label` is A, A2 (the noise run: world A built again at the
    same place, so that nothing but time differs) or B."""

    def __init__(self, label: str, arena: Path, source: Path | None = None):
        self.label = label
        self.spec = WORLDS[WORLD_OF_RUN[label]]
        self.arena = Path(arena)
        self.source = Path(source or PACKAGE)       # the package bytes every world copies (one snapshot per census)
        self.top = self.arena / self.spec["project"]
        self.root = self.top.joinpath(*self.spec["sub"])
        self.package = self.arena / self.spec["package"]
        self.home = self.arena / self.spec["home"]
        self.venv = self.arena / self.spec["python"]
        self.python = str(_venv_python(self.venv))
        self.tmp = self.arena / ("tmp-" + WORLD_OF_RUN[label].lower())
        self.bin = self.arena / ("bin-" + WORLD_OF_RUN[label].lower())
        self.inputs = self.root / "_inputs"         # requests the flow's driver would have written: setup, never scanned

    def build(self) -> None:
        for folder in (self.root, self.inputs, self.home, self.tmp, self.bin):
            folder.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.source, self.package, ignore=_ignore_for_copy)
        proc = subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(self.venv)], capture_output=True, text=True,
                              timeout=STEP_TIMEOUT_S)
        if proc.returncode != 0 or not Path(self.python).is_file():
            raise RuntimeError(f"the venv of world {self.label} could not be made ({proc.returncode}): {proc.stderr[-300:]}")
        (self.bin / "helper.py").write_text(HELPER, encoding="utf-8")

    def destroy(self) -> None:
        for folder in (self.top, self.package, self.home, self.venv, self.tmp, self.bin):
            rmtree(folder)

    def env(self, project: Path | None, home: Path, tmp: Path, *, dashboard: bool = False, **extra) -> dict:
        keep = ("SYSTEMROOT", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "PATH", "OS", "PROCESSOR_ARCHITECTURE",
                "NUMBER_OF_PROCESSORS", "COMPUTERNAME", "USERNAME", "USERDOMAIN", "SYSTEMDRIVE", "PROGRAMDATA",
                "PROGRAMFILES", "PROGRAMFILES(X86)", "ALLUSERSPROFILE", "PUBLIC", "LANG", "LC_ALL", "TERM", "SHELL")
        env = {k: os.environ[k] for k in keep if k in os.environ}
        env.update(HOME=str(home), USERPROFILE=str(home), APPDATA=str(home / "AppData"), LOCALAPPDATA=str(home / "AppData"),
                   CLAUDE_CONFIG_DIR=str(home / ".claude"), TEMP=str(tmp), TMP=str(tmp), TMPDIR=str(tmp),
                   PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        if project is not None:
            env["CLAUDE_PROJECT_DIR"] = str(project)
        if not dashboard:
            # the dashboard refresh after every write costs seconds per step and is ONE writer (F1 keeps it on)
            env["QA_FACTORY_SKIP_DASHBOARD_REFRESH"] = "1"
        env.update({k: str(v) for k, v in extra.items()})
        return env

    def script(self, name: str) -> str:
        return str(self.package / "scripts" / name)

    def package_fingerprint(self) -> str:
        """The fingerprint the package copy computes of itself (runtime_paths): equal in every world, or the copies differ."""
        project = self.inputs / "fp-project"
        (project / "qa-factory").mkdir(parents=True, exist_ok=True)
        (project / "qa-factory" / "t").mkdir(exist_ok=True)   # runtime_paths refuses a task root that is not a folder
        (project / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
        home, tmp = self.home / "fp", self.tmp / "fp"
        for folder in (home, tmp):
            folder.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run([self.python, "-B", self.script("runtime_paths.py"), "--task-root", str(project / "qa-factory" / "t"),
                               "--project-root", str(project)], capture_output=True, env=self.env(project, home, tmp),
                              timeout=STEP_TIMEOUT_S)
        try:
            return json.loads(proc.stdout.decode("utf-8", "replace"))["package_fingerprint"]
        except (ValueError, KeyError):
            tail = proc.stderr.decode("utf-8", "replace")[-600:] or proc.stdout.decode("utf-8", "replace")[-600:]
            print(f"state_census: runtime_paths gave no package_fingerprint (exit {proc.returncode}): {tail.strip()}",
                  file=sys.stderr)
            return ""


# --- a flow in a world -------------------------------------------------------------------------------------------

class Step:
    def __init__(self, label, argv, code, seconds, stdout: bytes, stderr: bytes, expect):
        self.label, self.argv, self.code, self.seconds = label, argv, code, seconds
        self.stdout, self.stderr, self.expect = stdout, stderr, expect

    @property
    def ok(self) -> bool:
        return self.code in self.expect


def _snapshot(folder: Path) -> dict:
    out = {}
    for base, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for name in files:
            path = Path(base, name)
            try:
                st = path.stat()
            except OSError:
                continue
            out[path] = (st.st_size, st.st_mtime_ns)
    return out


class FlowRun:
    """The handle a flow function gets: its own project, home and temp folders, the world's environment, and a `run` that
    records every step (command, exit code, stdout). `mark()` ends the SETUP: only what is written after it is the flow's."""

    task = "QA-1"
    dashboard = False

    def __init__(self, world: World, flow_id: str):
        self.world = world
        self.id = flow_id
        self.project = world.root / flow_id.lower()
        self.home = world.home / flow_id.lower()
        self.tmp = world.tmp / flow_id.lower()
        for folder in (self.project, self.home / ".claude", self.home / "AppData", self.tmp):
            folder.mkdir(parents=True, exist_ok=True)
        self.steps: list = []
        self.snapshots: list = []           # (path, logical name, carrier[, order marker path]): files copied while they existed
        self.initialize_sent: dict = {}     # the request the last `initialize()` sent (the replays of experiment X2 send it again)
        self.before: dict = {}

    def env(self, *, dashboard: bool | None = None, **extra) -> dict:
        return self.world.env(self.project, self.home, self.tmp, dashboard=self.dashboard if dashboard is None else dashboard,
                              **extra)

    def watch(self) -> dict:
        out = {}
        for folder in (self.project, self.home, self.tmp):
            out.update(_snapshot(folder))
        return out

    def mark(self) -> None:
        self.before = self.watch()

    def setup_file(self, path: Path, text: str) -> Path:
        """A file the flow's own steps need as INPUT (written by the test, not by the factory): not the flow's output."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        st = path.stat()
        self.before[path] = (st.st_size, st.st_mtime_ns)
        return path

    def revision(self) -> int:
        try:
            return json.loads((self.task_root / "state" / "controller.json").read_text(encoding="utf-8")).get("revision", 0)
        except (OSError, ValueError):
            return 0

    def run(self, argv, *, label: str = "", input_text: str | None = None, cwd=None, expect=(0,), env=None, timeout=STEP_TIMEOUT_S):
        started = time.monotonic()
        full = [str(a) for a in argv]
        try:
            proc = subprocess.run(full, input=None if input_text is None else input_text.encode("utf-8"), capture_output=True,
                                  cwd=str(cwd or self.project), env=env or self.env(), timeout=timeout)
            code, out, err = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            code, out, err = 124, exc.stdout or b"", exc.stderr or b""
        step = Step(label or Path(full[min(2, len(full) - 1)]).name, full, code, time.monotonic() - started, out, err, tuple(expect))
        self.steps.append(step)
        return step

    def py(self, script: str, *args, **kw):
        return self.run([self.world.python, "-B", self.world.script(script), *args], label=kw.pop("label", script), **kw)

    @property
    def task_root(self) -> Path:
        return self.project / "qa-factory" / "artifacts" / self.task

    def controller(self, operation: str, *args, request: dict | None = None, name: str = "", **kw):
        argv = ["--task-root", str(self.task_root), "--operation", operation]
        if request is not None:
            path = self.world.inputs / f"{self.id.lower()}-{name or operation}.json"
            path.write_text(json.dumps(request), encoding="utf-8")
            argv += ["--input", str(path)]
        return self.py("controller.py", *argv, *args, label=f"controller {operation}", **kw)

    def json_of(self, step: Step):
        try:
            return json.loads(step.stdout.decode("utf-8", errors="replace"))
        except ValueError:
            return None

    def skeleton(self, *, config_edit=None, pipeline: bool = True) -> None:
        """The project of the flow: the shipped config template, `tests/`, and (unless told not to) a task whose S0 is pending."""
        project = self.project
        (project / "qa-factory" / "state").mkdir(parents=True, exist_ok=True)
        (project / "tests").mkdir(parents=True, exist_ok=True)
        cfg = json.loads((PACKAGE / "references" / "templates" / "config.json").read_text(encoding="utf-8"))
        cfg["tests_root"] = "tests"
        cfg["app_root"] = "."
        cfg["handoffs"] = {"required": False}
        if config_edit:
            config_edit(cfg)
        (project / "qa-factory" / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        if pipeline:
            (self.task_root / "work").mkdir(parents=True, exist_ok=True)
            (self.task_root / "pipeline.json").write_text(json.dumps(
                {"ticket": self.task, "size": "S", "environment": "local", "implementation_source": "diff",
                 "stages": {"S0": {"status": "pending"}}, "gates": {}, "halts": []}), encoding="utf-8")

    def driver_known_paths(self) -> dict:
        """What story_run's `Driver.known_paths()` makes for this project (the writer #1 body), computed by the world's own
        package copy. A setup call: it is not a step of the flow."""
        proc = subprocess.run([self.world.python, "-B", str(self.world.bin / "helper.py"), str(self.world.package),
                               "known_paths", str(self.project), self.task], capture_output=True, env=self.env(),
                              timeout=STEP_TIMEOUT_S)
        try:
            return json.loads(proc.stdout.decode("utf-8", "replace"))
        except ValueError as exc:
            raise RuntimeError("the driver-shaped known_paths could not be made: " + proc.stderr.decode("utf-8", "replace")[-300:]) from exc

    def initialize_request(self, known_paths: dict | None = None, revision: int | None = None) -> dict:
        """The story_run-shaped `initialize` request: absolute known_paths (this world's own unless given)."""
        return {"scope": [], "source_revision": "src-1", "known_paths": known_paths if known_paths is not None else self.driver_known_paths(),
                "required_quality_checks": [], "idempotency_key": f"initialize:{self.task}:driver",
                "coverage_contract_version": 2, "plan_contract_mode": "new",
                "expected_revision": self.revision() if revision is None else revision}

    def initialize(self) -> Step:
        """S0 closed by stage_done, then `controller initialize` with the story_run-shaped (absolute) known_paths."""
        self.py("stage_done.py", "--task", self.task, "--stage", "S0", "--status", "done", "--digest", "preflight green")
        self.initialize_sent = self.initialize_request()
        return self.controller("initialize", request=self.initialize_sent)


# --- the flows ---------------------------------------------------------------------------------------------------

def flow_f1(fr: FlowRun) -> None:
    """controller initialize -> prepare -> dispatch -> checkpoint -> next / recover. The dashboard refresh (a hook-written
    projection that costs seconds per step) is on for the dispatch step only: it is one writer, whichever step runs it."""
    fr.skeleton()
    fr.mark()
    fr.initialize()
    packet = fr.json_of(fr.controller("prepare", request={"stage": "S1", "role": "qa-scout", "id": "S1-qa-scout-1"}, name="prepare")) or {}
    fr.controller("dispatch", request=packet.get("dispatch_request") or {}, name="dispatch", env=fr.env(dashboard=True))
    # the stage is accepted on one evidence file, then sent back (`rework` copies the accepted dispatch's paths), and the
    # reworked dispatch is the one that is paused, read by `next` and repaired by `recover`
    evidence = fr.setup_file(fr.task_root / "S1.txt", "S1")
    fr.controller("accept", request={"id": "S1-qa-scout-1", "status": "accepted", "stage_complete": True,
                                     "evidence_refs": [{"path": "S1.txt", "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}],
                                     "idempotency_key": "accept-S1", "expected_revision": fr.revision()}, name="accept")
    fr.controller("rework", "--stage", "S1", "--role", "qa-scout", "--reason", "census: rework", "--cases", "")
    fr.controller("checkpoint", "--dispatch", "S1-qa-scout-2", "--status", "paused", "--reason", "census: pause")
    fr.controller("next")
    fr.controller("recover")


def _story_up_to_initialize(fr: FlowRun) -> None:
    """Setup shared by the flows that START from an initialized story: S0 closed and `initialize` recorded (flow F1 measures
    those writes itself)."""
    fr.skeleton()
    fr.initialize()
    fr.steps.clear()
    fr.mark()


def flow_f2(fr: FlowRun) -> None:
    """story_run.py --dry-run over an initialized story."""
    _story_up_to_initialize(fr)
    fr.run([fr.world.python, "-B", fr.world.script("story_run.py"), "--task", fr.task, "--dry-run", "--project", str(fr.project),
            "--plugin-dir", str(fr.world.package)], label="story_run --dry-run",
           env=fr.env(STORY_RUN_CLAUDE=fr.world.bin / "none.py"))


# The fake claude copies driver-state.json while it runs: the only moment `in_flight` (a pid) exists on disk. The driver writes
# `in_flight` after `Popen` returns and only THEN sends the prompt (`launch`: mark_in_flight, then communicate), so the copy is taken
# after the stub has READ ITS STDIN - a causal order, no sleep (FR-31). Taken at the start of the stub it raced the driver's write
# (t-348 finding 1). `<dst>.order` says when the copy was taken, observed and not asserted: `after_stdin` (the only good word),
# `at_exit` (the stub ended without reading stdin: a driver that failed before `communicate`), `before_stdin`; no marker at all
# is `not_taken` (the stub was killed). The census FAILS on any word but the good one: the #25 row is then not observed, never passed.
SNAPSHOT_PREAMBLE = r'''
import atexit as _atexit, os as _os, shutil as _shutil
from pathlib import Path as _Path
_census = {"stdin_read": False, "taken": False}


def _census_take(site):
    src, dst = _os.environ.get("CENSUS_SNAPSHOT_FROM"), _os.environ.get("CENSUS_SNAPSHOT_TO")
    if _census["taken"] or not (src and dst):
        return
    _census["taken"] = True
    order = "after_stdin" if _census["stdin_read"] else ("at_exit" if site == "exit" else "before_stdin")
    try:
        _Path(dst).parent.mkdir(parents=True, exist_ok=True)
        if _Path(src).is_file():
            _shutil.copyfile(src, dst)
        _Path(dst + ".order").write_text(order, encoding="utf-8")
    except OSError:
        pass


_atexit.register(_census_take, "exit")
'''
STDIN_ANCHOR = 'prompt = sys.stdin.buffer.read().decode("utf-8")\n'      # story_run_common.STUB: the line that reads the driver's prompt
STDIN_HOOK = '_census["stdin_read"] = True\n_census_take("stdin")\n'


def f3_stub_source() -> str:
    """The fake claude of flow F3: story_run_common's stub with the snapshot taken right after it read its stdin. A stub whose
    stdin line is gone cannot be patched, and that stops the flow (it is not run unpatched)."""
    import story_run_common as T
    if T.STUB.count(STDIN_ANCHOR) != 1:
        raise RuntimeError("story_run_common.STUB no longer has exactly one line `" + STDIN_ANCHOR.strip() + "`: the in-flight "
                           "snapshot cannot be placed after the stub read its stdin; update state_census.STDIN_ANCHOR")
    return SNAPSHOT_PREAMBLE + T.STUB.replace(STDIN_ANCHOR, STDIN_ANCHOR + STDIN_HOOK, 1)


def flow_f3(fr: FlowRun) -> None:
    """The driver runs ONE role (S1) with the fake claude. The fake copies driver-state.json once it has read the prompt, which
    is the only moment `in_flight` (a pid) exists on disk."""
    import story_run_common as T
    _story_up_to_initialize(fr)
    stub = fr.world.bin / "fake_claude.py"
    stub.write_text(f3_stub_source(), encoding="utf-8")
    control = fr.world.inputs / "f3-stub-control.json"
    manifest = json.dumps(T.GOOD_MANIFEST).replace("{task}", fr.task)
    control.write_text(json.dumps({"roles": {"qa-scout": {
        "files": {"work/context-manifest.json": manifest, "work/context-bundle.json": "{}"},
        "result": T.SCOUT_DIGEST.replace("{task}", fr.task)}}}), encoding="utf-8")
    seen = fr.world.inputs / "f3-in-flight-snapshot.json"
    fr.snapshots.append((seen, "<PROJECT>/qa-factory/artifacts/<TASK>/state/driver-state.json@in_flight", "T",
                         seen.with_name(seen.name + ".order")))
    fr.run([fr.world.python, "-B", fr.world.script("story_run.py"), "--task", fr.task, "--project", str(fr.project),
            "--plugin-dir", str(fr.world.package), "--max-boundaries", "1"], label="story_run (one role)",
           env=fr.env(STORY_RUN_CLAUDE=stub, STUB_CONTROL=control, STUB_LOG=fr.world.inputs / "f3-stub-log.jsonl",
                      CENSUS_SNAPSHOT_FROM=fr.task_root / "state" / "driver-state.json", CENSUS_SNAPSHOT_TO=seen))


def flow_f4(fr: FlowRun) -> None:
    """The inject hook's packet for a role whose dispatch the controller has recorded."""
    fr.skeleton()
    fr.initialize()
    packet = fr.json_of(fr.controller("prepare", request={"stage": "S1", "role": "qa-scout", "id": "S1-qa-scout-1"}, name="prepare")) or {}
    fr.controller("dispatch", request=packet.get("dispatch_request") or {}, name="dispatch")
    fr.steps.clear()
    fr.mark()
    event = {"hook_event_name": "PreToolUse", "tool_name": "Agent", "session_id": "census-session",
             "tool_input": {"subagent_type": "qa-scout",
                            "prompt": f"Task: {fr.task}\nDispatch id: S1-qa-scout-1\nCollect the sources."}}
    fr.py("inject_context.py", input_text=json.dumps(event), label="inject_context hook")


FRESH_ANSWERS = {"dod": "Done means the change is reviewed and the suite is green in CI.", "tests_root": "tests",
                 "protected_app_paths": ["src"]}
PORTABLE_PROBE = {"argv": ["{python}", "{plugin_root}/scripts/runtime_probe.py", "--probe"], "cwd": ".", "timeout_s": 60}


def flow_f5(fr: FlowRun) -> None:
    """onboard_apply over a FRESH project (git init, no qa-factory/): the one apply path with the person's "yes". The install
    manifest it writes (#22: relative paths and the version) is the census's positive control: it must hold no fact."""
    subprocess.run(["git", "init", "-q", str(fr.project)], capture_output=True, env=fr.env(), timeout=60)
    cfg = json.loads((PACKAGE / "references" / "templates" / "config.json").read_text(encoding="utf-8"))
    cfg.update(FRESH_ANSWERS)
    cfg["execution"]["runtime_probes"] = {"api": dict(PORTABLE_PROBE)}
    proposal = fr.world.inputs / "f5-proposal.json"
    proposal.write_text(json.dumps({"proposed_config": cfg}), encoding="utf-8")
    fr.mark()
    fr.py("onboard_apply.py", "--root", str(fr.project), "--proposal", str(proposal), "--apply", "--evidence-ref",
          "census: headless", label="onboard_apply --apply")


RUN_SUITE_PROBE = {"profile_id": "api", "timestamp": "2026-09-22T10:00:00Z", "environment_id": "localhost",
                   "expected_source_revision": "source-1", "observed_runtime_identity": "build-1", "evidence_refs": ["probe"],
                   "result": "matched", "provenance": {"technical_verification": True, "source_linkage": "exact",
                                                       "deployed_source_revision": "source-1"}}
FAKE_PYTEST = r'''
import sys
from pathlib import Path
args = sys.argv[1:]
report = next((a.split("=", 1)[1] for a in args if a.startswith("--junitxml=")), "")
nodes = [a for a in args if "::" in a]
rows = []
for node in nodes:
    parts = node.replace("\\", "/").split("::")
    classname = ".".join([parts[0][:-3].replace("/", ".")] + parts[1:-1])
    rows.append('<testcase classname="%s" name="%s"/>' % (classname, parts[-1]))
if report:
    Path(report).parent.mkdir(parents=True, exist_ok=True)
    Path(report).write_text('<testsuite tests="%d" failures="0" errors="0" skipped="0">%s</testsuite>' % (len(rows), "".join(rows)), encoding="utf-8")
'''


def flow_f6(fr: FlowRun) -> None:
    """run_suite --mine over the fixture of test_run_suite_mine (a fake pytest, a fake probe, a hand-made controller state)."""
    fr.task = "MINE-1"
    python = fr.world.python

    def edit(cfg):
        cfg["profiles"] = [{"profile_id": "api", "selected": True, "roots": {"test": "tests"},
                            "commands": {"one_test": {"argv": [python, str(fr.project / "fake" / "pytest"), "<test-file>"], "cwd": "."}},
                            "reporter": {"kind": "pytest"}, "selectors": {"verified": True}}]
        cfg["execution"] = dict(cfg.get("execution") or {}, verify_node_ids=False,
                                runtime_probes={"api": {"argv": [python, str(fr.project / "probe.py")], "cwd": ".", "timeout_s": 20}})
        cfg["run"] = {"parallel": True}
    fr.skeleton(config_edit=edit, pipeline=False)
    project, task_root = fr.project, fr.task_root
    (project / "fake").mkdir(parents=True, exist_ok=True)
    (project / "fake" / "pytest").write_text(FAKE_PYTEST, encoding="utf-8")
    (project / "probe.py").write_text("import json\nprint(json.dumps(" + repr(RUN_SUITE_PROBE) + "))\n", encoding="utf-8")
    (project / "tests" / "conftest.py").write_text("# fixtures\n", encoding="utf-8")
    (project / "tests" / "test_a.py").write_text("def test_green():\n    pass\n", encoding="utf-8")
    (task_root / "state").mkdir(parents=True, exist_ok=True)
    (task_root / "pipeline.json").write_text(json.dumps({"stages": {"S5": {"status": "running"}}}), encoding="utf-8")
    (task_root / "state" / "controller.json").write_text(json.dumps({
        "schema_version": "2", "revision": "41", "source_revision": "source-1",
        "dispatches": {"S5-qa-automator-1": {"id": "S5-qa-automator-1", "stage": "S5", "role": "qa-automator", "status": "running",
                                              "scope": ["TC-001"], "budget": {"requests": 150}}}}), encoding="utf-8")
    (task_root / "work").mkdir(parents=True, exist_ok=True)
    (task_root / "work" / "automation-manifest.json").write_text(json.dumps({"tests": [
        {"case": "TC-001", "file": "tests/test_a.py", "selector": "test_green"}]}), encoding="utf-8")
    fr.mark()
    fr.py("run_suite.py", "--mine", "TC-001", label="run_suite --mine")


def flow_f7(fr: FlowRun) -> None:
    """context_bundle build over a manifest with a known path and a diff."""
    fr.skeleton()
    project, task_root = fr.project, fr.task_root
    (project / "src").mkdir(parents=True, exist_ok=True)
    (project / "src" / "a.py").write_text("print('a')\n", encoding="utf-8")
    (project / "change.diff").write_text("diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n@@ -1 +1 @@\n"
                                         "-print('a')\n+print('b')\n", encoding="utf-8")
    manifest = {"ticket": fr.task, "implementations": [{"repo_id": "app", "source_sha": "abc", "diff_path": "change.diff"}],
                "changed_areas": ["src"], "existing_coverage": [{"test": "tests/test_a.py"}], "constraints": [],
                "facts": [{"id": "R-1", "path": "src/a.py", "range": "1"}], "known_paths": ["src/a.py"], "unresolved_facts": []}
    path = fr.world.inputs / "f7-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    fr.mark()
    fr.py("context_bundle.py", "--manifest", str(path), "--output", str(task_root / "work" / "context-bundle.json"),
          "--root", str(project), label="context_bundle")


def flow_f8(fr: FlowRun) -> None:
    """cost_capture (the Stop hook) over a fake transcript that lies where Claude keeps this project's transcripts."""
    fr.skeleton(pipeline=False)
    # the host's own spelling of the folder (cost_capture.project_slug); the package resolves the project, so the slug is of its
    # resolved spelling (on Windows the long name, where the temp folder is handed out by its 8.3 name)
    slug = re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(fr.project)).strip("-")
    transcript = fr.home / ".claude" / "projects" / slug / "census-session.jsonl"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    row = {"type": "assistant", "isSidechain": False, "requestId": "r1", "uuid": "u-r1", "timestamp": "2026-09-20T19:00:00Z",
           "message": {"model": "claude-sonnet-5", "content": [], "usage": {
               "input_tokens": 1000, "output_tokens": 50, "cache_read_input_tokens": 0,
               "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}}}}
    transcript.write_text(json.dumps(row) + "\n", encoding="utf-8")
    old = time.time() - 3600
    os.utime(transcript, (old, old))
    fr.mark()
    event = {"hook_event_name": "Stop", "session_id": "census-session", "transcript_path": str(transcript), "cwd": str(fr.project)}
    fr.py("cost_capture.py", input_text=json.dumps(event), label="cost_capture (Stop hook)")


def flow_f9(fr: FlowRun) -> None:
    """runtime_probe evidence: the probe over a fake docker (the container answers with its image digest, and its build-sha.txt
    equals the checkout's HEAD, so the record is `matched` and an evidence file is written)."""
    fr.skeleton(pipeline=False)             # no pipeline.json: a story's own stand would have to agree with `--environment`
    ui = fr.project / "ui"
    (ui / "src").mkdir(parents=True, exist_ok=True)
    (ui / "src" / "Page.vue").write_text("v", encoding="utf-8")
    (fr.task_root / "work").mkdir(parents=True, exist_ok=True)
    (fr.task_root / "work" / "impl-diff.txt").write_text("+++ b/src/Page.vue\n", encoding="utf-8")
    fr.mark()
    fr.run([fr.world.python, "-B", str(fr.world.bin / "helper.py"), str(fr.world.package), "probe", CONTAINER, DIGEST, HEAD_SHA,
            "--profile", "e2e-ui", "--environment", "localhost", "--container", CONTAINER, "--checkout", str(ui),
            "--expected", HEAD_SHA, "--task-root", str(fr.task_root)], label="runtime_probe (fake docker)")


FLOWS = {"F1": flow_f1, "F2": flow_f2, "F3": flow_f3, "F4": flow_f4, "F5": flow_f5, "F6": flow_f6, "F7": flow_f7,
         "F8": flow_f8, "F9": flow_f9}


# --- running a flow and scanning what it left --------------------------------------------------------------------

class FlowResult:
    def __init__(self, flow_id: str, world: str):
        self.id, self.world = flow_id, world
        self.ran, self.exit, self.seconds, self.error = False, -1, 0.0, ""
        self.files = 0
        self.hits = set()               # (file, carrier, pointer, fact, detector, spelling)
        self.values = {}                # (file, pointer) -> [text]
        self.carriers = {}              # file -> carrier
        self.not_scanned = []           # {file, bytes, reason}
        self.produced = set()           # normalised file names
        self.qa_rel = set()             # project-relative paths under qa-factory/ (for the table's `unrecognised`)
        self.steps = []                 # (label, code, seconds)
        self.snapshot_orders = {}       # snapshot name -> when the stub took it (after_stdin, at_exit, before_stdin, not_taken)


def _logical(fr: FlowRun, path: Path):
    """(carrier, normalised name, project-relative path or None) of one produced file."""
    for base, tag in ((fr.project, "<PROJECT>"), (fr.home, "<HOME>"), (fr.tmp, "<TMP>")):
        try:
            rel = path.relative_to(base)
        except ValueError:
            continue
        posix = rel.as_posix()
        if tag == "<PROJECT>":
            carrier = "S" if rel.parts[:2] == ("qa-factory", "state") else "T"
            return carrier, f"{tag}/{norm_rel(posix)}", posix
        return "scratch", f"{tag}/{norm_rel(posix)}", None
    return "scratch", "<OTHER>/" + norm_name(path.name), None


def scan_file(path: Path, det: Detector, keys: dict, *, cap: int = SIZE_CAP) -> Scan:
    """Scan one file on disk. A file over the cap, or one that cannot be read, is `not_scanned` and says why: it is never
    reported clean (E8)."""
    scan = Scan()
    try:
        size = Path(path).stat().st_size
        if size > cap:
            scan.not_scanned = f"size {size} bytes is over the cap of {cap}"
            return scan
        data = Path(path).read_bytes()
    except OSError as exc:
        scan.not_scanned = f"unreadable ({exc.__class__.__name__})"
        return scan
    return scan_bytes(Path(path).name, data, det, keys, cap=cap)


def _absorb(res: FlowResult, name: str, carrier: str, rel, scan: Scan, size: int = 0):
    res.files += 1
    res.produced.add(name)
    res.carriers[name] = carrier
    if rel and rel.startswith("qa-factory/"):
        res.qa_rel.add(rel)
    if scan.not_scanned:
        res.not_scanned.append({"file": name, "bytes": size, "reason": scan.not_scanned})
        return
    for pointer, fact, detector, spelling in scan.hits:
        res.hits.add((name, carrier, pointer, fact, detector, spelling))
    for pointer, values in scan.values.items():
        res.values.setdefault((name, pointer), []).extend(values)


def run_flow(world: World, flow_id: str, det: Detector, keys: dict) -> FlowResult:
    res = FlowResult(flow_id, world.label)
    fr = FlowRun(world, flow_id)
    started = time.monotonic()
    try:
        FLOWS[flow_id](fr)
        res.ran = True
    except Exception as exc:               # a flow that did not run is a failure of the census (E13), never "no hits"
        res.error = f"{type(exc).__name__}: {exc}"
    res.seconds = round(time.monotonic() - started, 1)
    bad = next((s for s in fr.steps if not s.ok), None)
    res.exit = bad.code if bad else (0 if res.ran else -1)
    res.steps = [(s.label, s.code, round(s.seconds, 1)) for s in fr.steps]
    after = fr.watch()
    for path, sig in sorted(after.items()):
        if fr.before.get(path) == sig:
            continue                       # written before the flow's own steps: setup, not the flow's
        carrier, name, rel = _logical(fr, path)
        _absorb(res, name, carrier, rel, scan_file(path, det, keys), sig[0])
    for entry in fr.snapshots:
        path, name, carrier = entry[:3]
        if len(entry) > 3:
            try:
                res.snapshot_orders[name] = Path(entry[3]).read_text(encoding="utf-8").strip() or "not_taken"
            except OSError:
                res.snapshot_orders[name] = "not_taken"
        if Path(path).is_file():
            _absorb(res, name, carrier, None, scan_file(path, det, keys), Path(path).stat().st_size)
    for step in fr.steps:
        if not step.stdout:
            continue
        try:
            json.loads(step.stdout.decode("utf-8", errors="replace"))
            scan_name = "stdout.json"
        except ValueError:
            scan_name = "stdout.txt"
        # the same step run twice is one carrier: its hits merge under one name
        _absorb(res, f"<STDOUT>/{norm_name(step.label)}", "stdout", None,
                scan_bytes(scan_name, step.stdout, det, keys), len(step.stdout))
    return res


def scan_dir(root: Path, det: Detector, keys: dict, *, flow: str = "unit", world: str = "A", cap: int = SIZE_CAP) -> dict:
    """Scan a folder as if it were a flow's project (the unit tests' synthetic writer): a census-shaped dict."""
    res = FlowResult(flow, world)
    res.ran, res.exit = True, 0
    root = Path(root)
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root)
        carrier = "S" if rel.parts[:2] == ("qa-factory", "state") or rel.parts[:1] == ("state",) else "T"
        _absorb(res, f"<PROJECT>/{norm_rel(rel.as_posix())}", carrier, rel.as_posix(), scan_file(path, det, keys, cap=cap), path.stat().st_size)
    return assemble({world: {flow: res}}, {}, keys)


def submit_flows(world: World, det: Detector, keys: dict, flows, pool: ThreadPoolExecutor) -> tuple:
    before_pkg = _snapshot(world.package)
    return before_pkg, {fid: pool.submit(run_flow, world, fid, det, keys) for fid in flows}


def collect_world(world: World, det: Detector, keys: dict, submitted: tuple, progress) -> dict:
    before_pkg, futures = submitted
    out = {}
    for fid, fut in futures.items():
        res = fut.result()
        out[fid] = res
        progress(f"census: {fid} in {world.label}: exit {res.exit}, {res.files} artifact(s), {len(res.hits)} raw hit(s), "
                 f"{res.seconds:.0f} s" + (f"  ({res.error})" if res.error else ""))
    # nothing may be written into the package copy (a marketplace installs what lies in it): what a flow left there is scanned too
    pkg = FlowResult("PKG", world.label)
    pkg.ran, pkg.exit = True, 0
    for path, sig in _snapshot(world.package).items():
        if before_pkg.get(path) != sig:
            rel = path.relative_to(world.package).as_posix()
            _absorb(pkg, f"<PACKAGE>/{norm_rel(rel)}", "scratch", None, scan_file(path, det, keys), sig[0])
    out["PKG"] = pkg
    return out


def tree_info() -> dict:
    """E14: the package files with uncommitted changes while the census ran (the baseline then mixes two package states)."""
    try:
        top = subprocess.run(["git", "-C", str(PACKAGE), "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                             timeout=60)
        if top.returncode != 0 or not top.stdout.strip():
            return {"uncommitted_package_files": None, "unknown": "not inside a git work tree"}
        root = Path(top.stdout.strip())
        rel = PACKAGE.resolve().relative_to(root.resolve()).as_posix()
        status = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all", "--", rel],
                                capture_output=True, text=True, timeout=120)
        if status.returncode != 0:
            return {"uncommitted_package_files": None, "unknown": f"git status exited {status.returncode}"}
        files = sorted(line[3:].split(" -> ")[-1].strip().strip('"') for line in status.stdout.splitlines() if len(line) > 3)
        return {"uncommitted_package_files": files}
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {"uncommitted_package_files": None, "unknown": f"git could not be asked ({exc.__class__.__name__})"}


def run_census(progress=print, flows=None, workers: int = WORKERS, keys_path: Path = KEYS_FILE) -> dict:
    """Run the flows in A and B, then again in A (the noise control), scan everything, and return the raw census (no baseline
    applied yet: `evaluate` does that)."""
    keys = load_keys(keys_path)             # raises DetectorMissing: a census with no key list is not a clean census (E9)
    flows = list(flows or FLOWS)
    tree = tree_info()                      # E14, asked before anything is copied
    arena = Path(tempfile.mkdtemp(prefix=ARENA_PREFIX))
    results: dict = {}
    fingerprints: dict = {}
    started = time.monotonic()
    try:
        # ONE copy of the package bytes, taken now: a builder editing the package while the census runs (t-335 was in flight
        # when this was written) must not give world A and world B different packages
        snapshot = arena / "pkg-snapshot"
        shutil.copytree(PACKAGE, snapshot, ignore=_ignore_for_copy)
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            def chain(labels):
                """Worlds one after another in one chain: A, then A again at the same place (it must be gone first). Every flow
                of every chain goes through the one pool; each flow has its own project, home and temp folder."""
                for label in labels:
                    world = World(label, arena, snapshot)
                    try:
                        world.build()
                        fingerprints[label] = world.package_fingerprint()
                        progress(f"census: world {label} built ({time.monotonic() - started:.0f} s)")
                        det = make_detector(label, arena)
                        results[label] = collect_world(world, det, keys, submit_flows(world, det, keys, flows, pool), progress)
                    finally:
                        world.destroy()
            with ThreadPoolExecutor(max_workers=2) as chains:
                for future in [chains.submit(chain, labels) for labels in (("A", "A2"), ("B",))]:
                    future.result()
    finally:
        rmtree(arena)
    return assemble(results, fingerprints, keys, tree)


def assemble(results: dict, fingerprints: dict, keys: dict, tree: dict | None = None) -> dict:
    """The raw census from the per-world results: flows, hits, differential, noise, controls. No baseline applied."""
    flows_out, hits = [], {}
    not_scanned, produced, qa_rel, carriers, snapshots = [], set(), set(), {}, []
    for label, per_flow in results.items():
        for fid, res in per_flow.items():
            snapshots += [{"flow": fid, "world": label, "name": n, "taken": t} for n, t in sorted(res.snapshot_orders.items())]
            if fid != "PKG":
                flows_out.append({"id": fid, "world": label, "ran": res.ran, "exit": res.exit, "files": res.files,
                                  "seconds": res.seconds, **({"error": res.error} if res.error else {})})
            for name, carrier, pointer, fact, detector, spelling in res.hits:
                hits[(fid, label, name, pointer, fact, detector, spelling)] = carrier
            not_scanned += [{"flow": fid, "world": label, **n} for n in res.not_scanned]
            produced |= res.produced
            qa_rel |= {(fid, label, p) for p in res.qa_rel}
            carriers.update(res.carriers)
    differential, noise = [], []
    fids = sorted({fid for per in results.values() for fid in per if fid != "PKG"})
    for fid in fids:
        a, a2, b = (results.get(w, {}).get(fid) for w in ("A", "A2", "B"))
        if not (a and a2 and b):
            continue
        for key in sorted(set(a.values) & set(a2.values) & set(b.values)):
            va, va2, vb = sorted(a.values[key]), sorted(a2.values[key]), sorted(b.values[key])
            name, pointer = key
            if va != va2:
                noise.append({"flow": fid, "file": name, "pointer": pointer})
            elif va != vb:
                differential.append({"flow": fid, "file": name, "pointer": pointer, "a": va[0] if len(va) == 1 else va,
                                     "b": vb[0] if len(vb) == 1 else vb})
                hits[(fid, "A|B", name, pointer, "digest", "differential", "raw")] = carriers.get(name, "scratch")
    rows = [{"flow": fid, "world": world, "file": name, "carrier_class": carrier, "pointer": pointer, "fact": fact,
             "detector": detector, "spelling": spelling}
            for (fid, world, name, pointer, fact, detector, spelling), carrier in sorted(hits.items())]
    fp = {w: fingerprints.get(w, "") for w in ("A", "A2", "B")}
    return {
        "census_version": CENSUS_VERSION,
        "package_fingerprint": fp.get("A", ""),
        "python": sys.version.split()[0],
        "os": sys.platform,
        "tree": tree if tree is not None else tree_info(),
        "canaries": {**canary_tokens(), "digest": DIGEST, "host": REAL["host"] if len(REAL["host"]) >= MIN_HOST_CHARS else
                     f"host not scanned (too short: {len(REAL['host'])} characters)"},
        "flows": sorted(flows_out, key=lambda f: (f["id"], f["world"])),
        "hits": rows,
        "not_scanned": sorted(not_scanned, key=lambda n: (n["flow"], n["world"], n["file"])),
        "snapshots": sorted(snapshots, key=lambda s: (s["flow"], s["world"], s["name"])),
        "differential": differential, "noise": noise,
        "controls": {"package_fingerprint": {**fp, "equal": bool(fp["A"]) and len({fp["A"], fp["A2"], fp["B"]}) == 1}},
        "_produced": sorted(produced), "_qa_rel": sorted(qa_rel),
    }


# --- the baseline and the ratchet --------------------------------------------------------------------------------

class BaselineRefused(Exception):
    """`--write-baseline` will not write a baseline from a census that has a failure, or a hit nothing maps to a node."""


class BaselineInvalid(ValueError):
    """The baseline names a node or an inventory row that does not exist: a typo would otherwise pass for a real debt."""


def validate_baseline(data: dict, path) -> None:
    """Every `leaves_at` word (of a row, a `file_writers` entry or a writer) is a key of `leaves_at_legend`, and every
    `inventory_row` (of a row or a `file_writers` entry) is a key of `writers`. Raises BaselineInvalid naming the row and the word
    (t-348 finding 2: a typo'd node word or row id used to pass, because only truthiness was checked)."""
    legend = data.get("leaves_at_legend") if isinstance(data.get("leaves_at_legend"), dict) else {}
    writers = data.get("writers") if isinstance(data.get("writers"), dict) else {}
    problems = []

    def node(where: str, word) -> None:
        if not word:
            problems.append(f"{where} names no node (`leaves_at` is empty)")
        elif word not in legend:
            problems.append(f"{where} has `leaves_at` {word!r}, which is not in `leaves_at_legend` "
                            f"({', '.join(sorted(legend)) or 'the legend is missing'})")

    def inventory(where: str, word) -> None:
        if not word:
            problems.append(f"{where} names no inventory row (`inventory_row` is empty)")
        elif word not in writers:
            problems.append(f"{where} has `inventory_row` {word!r}, which is not in `writers`")

    for row in data.get("rows") or []:
        where = f"row {row.get('id', '?')}" if isinstance(row, dict) else f"row {row!r}"
        if not isinstance(row, dict):
            problems.append(f"{where} is not an object")
            continue
        node(where, row.get("leaves_at"))
        inventory(where, row.get("inventory_row"))
    for entry in data.get("file_writers") or []:
        where = f"file_writers entry ({entry.get('file')}, {entry.get('pointer')})" if isinstance(entry, dict) else f"file_writers entry {entry!r}"
        if not isinstance(entry, dict):
            problems.append(f"{where} is not an object")
            continue
        node(where, entry.get("leaves_at"))
        inventory(where, entry.get("inventory_row"))
    for key, entry in writers.items():
        if isinstance(entry, dict) and "leaves_at" in entry:
            node(f"writer {key}", entry["leaves_at"])
    if problems:
        raise BaselineInvalid(f"{path} is not a valid baseline: " + "; ".join(problems[:5])
                              + (f"; ... and {len(problems) - 5} more" if len(problems) > 5 else "")
                              + ". Correct the word, or add the node to `leaves_at_legend` / the row to `writers`")


def load_baseline(path: Path = BASELINE_FILE):
    """The baseline, or None when the file is absent (every hit is then new: the ratchet fails loudly, never passes). A baseline
    that names a node outside its legend or an inventory row outside its `writers` is refused (BaselineInvalid, a ValueError)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        raise ValueError(f"{path} is not a baseline: it must be an object with a `rows` list")
    validate_baseline(data, path)
    return data


def identity(row: dict) -> tuple:
    """The identity of a hit (and of a baseline row): flow, file pattern, pointer pattern, fact. Counts within one pattern
    are informational only."""
    return (row["flow"], row["file"], row["pointer"], row["fact"])


def writer_for(row: dict, baseline) -> tuple:
    """(writer, inventory row, node that removes it) from the baseline's STATIC map (never inferred): the first
    `file_writers` entry whose file and pointer globs and (optional) fact fit; `unmapped` otherwise."""
    for entry in (baseline or {}).get("file_writers") or []:
        if fnmatch.fnmatchcase(row["file"], entry.get("file", "*")) and fnmatch.fnmatchcase(row["pointer"], entry.get("pointer", "*")) \
                and entry.get("fact", row["fact"]) == row["fact"] and entry.get("flow", row["flow"]) == row["flow"]:
            site = ((baseline.get("writers") or {}).get(entry.get("inventory_row")) or {}).get("site", "unmapped")
            return site, entry.get("inventory_row"), entry.get("leaves_at")
    return "unmapped", None, None


def evaluate(census: dict, baseline) -> dict:
    """Annotate the census with writers, baseline rows and counts, and return the ratchet's verdict: new hits, stale rows,
    and the failures that do not depend on the baseline (E13, E8)."""
    base_rows = {identity(r): r for r in (baseline or {}).get("rows") or []}
    seen = {}
    for row in census["hits"]:
        writer, inv, _leaves = writer_for(row, baseline)
        row["writer"], row["inventory_row"] = writer, inv
        mine = base_rows.get(identity(row))
        row["baseline"] = mine["id"] if mine else None
        seen.setdefault(identity(row), row)
    census["counts"] = {
        "by_fact": _count(seen.values(), "fact"), "by_carrier_class": _count(seen.values(), "carrier_class"),
        "by_flow": _count(seen.values(), "flow"), "total": len(seen),
        "baselined": sum(1 for k in seen if k in base_rows), "new": sum(1 for k in seen if k not in base_rows)}
    census["not_exercised"] = not_exercised(census, baseline)
    census["unrecognised_files"] = unrecognised_files(census)
    new = [dict(r) for k, r in sorted(seen.items()) if k not in base_rows]
    stale = [dict(r, stale=True) for k, r in sorted(base_rows.items()) if k not in seen]
    failures = census_failures(census)
    census["failures"] = failures
    census["ratchet"] = {"new": [_brief(r) for r in new], "stale": [_brief(r) for r in stale]}
    return {"new": new, "stale": stale, "failures": failures,
            "lines": [f"new hit (not in the baseline): flow {r['flow']}, file {r['file']}, pointer {r['pointer'] or '(whole file)'}, "
                      f"fact {r['fact']}, writer {r['writer']}" for r in new]
                     + [f"stale baseline row {r['id']}: flow {r['flow']}, file {r['file']}, pointer {r['pointer'] or '(whole file)'}, "
                        f"fact {r['fact']} no longer has a hit; delete the row (the baseline only shrinks)" for r in stale]
                     + failures}


def _brief(row: dict) -> dict:
    return {k: row.get(k) for k in ("id", "flow", "file", "pointer", "fact", "writer", "inventory_row") if k in row}


def _count(rows, key) -> dict:
    out: dict = {}
    for row in rows:
        out[row[key]] = out.get(row[key], 0) + 1
    return dict(sorted(out.items()))


def census_failures(census: dict) -> list:
    """The failures that do not need a baseline: a flow that did not run, exited non-zero or produced nothing (E13), and a file
    that could not be scanned (E8). A flow that did not run never counts as "no hits"."""
    out = []
    for f in census["flows"]:
        where = f"flow {f['id']} in world {f['world']}"
        if not f["ran"]:
            out.append(f"{where} did not run ({f.get('error', 'no reason recorded')}); a flow that did not run is not 'no hits'")
        elif f["exit"] != 0:
            out.append(f"{where} exited {f['exit']}; the census needs every step to end as expected")
        elif f["files"] == 0:
            out.append(f"{where} produced no file and no output; a flow that produced nothing is not 'no hits'")
    for n in census["not_scanned"]:
        out.append(f"not scanned: {n['file']} (flow {n['flow']}, world {n['world']}): {n['reason']}; an unscanned file is never clean")
    for s in census.get("snapshots") or []:
        if s.get("taken") != "after_stdin":
            out.append(f"the in-flight snapshot of flow {s['flow']} in world {s['world']} ({s['name']}) was taken {s.get('taken')}, "
                       "not after the stub read its stdin: the driver's `in_flight` pid is not observed (never a pass)")
    fp = (census.get("controls") or {}).get("package_fingerprint") or {}
    if fp and fp.get("A") and not fp.get("equal"):
        out.append("the package copies of the worlds do not fingerprint alike (" + ", ".join(
            f"{w} {str(fp.get(w))[:12]}" for w in ("A", "A2", "B")) + "): the copies are not the same bytes, so a difference "
                   "between the worlds would not be the machine's")
    return out


def not_exercised(census: dict, baseline) -> list:
    """The static writer sites (R-4 section 1 plus #25) that no flow reached: a writer on no flow is MISSED, never 'clean'."""
    produced = census.get("_produced") or []
    out = []
    for inv, entry in sorted(((baseline or {}).get("writers") or {}).items(), key=lambda kv: _row_no(kv[0])):
        patterns = entry.get("produces") or []
        if not any(fnmatch.fnmatchcase(p, pat) for pat in patterns for p in produced):
            out.append({"site": entry.get("site", "?"), "inventory_row": inv,
                        "why": entry.get("not_exercised") or ("no flow produced a file of its pattern" if patterns else "writes nothing a flow can read")})
    return out


def _row_no(inv: str):
    m = re.match(r"#(\d+)(\w*)", inv)
    return (int(m.group(1)), m.group(2)) if m else (9999, inv)


def unrecognised_files(census: dict) -> list:
    """Files under qa-factory/ that install_paths.classify calls `unrecognised`: reported, not enforced (N5 enforces)."""
    scripts = str(PACKAGE / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    try:
        import install_paths as I
        table = I.load_table()
    except Exception as exc:         # an unreadable table is said, never read as "all recognised"
        return [f"(not classified: install_paths could not be used: {exc.__class__.__name__})"]
    out = set()
    for fid, world, rel in census.get("_qa_rel") or []:
        try:
            if I.classify(rel, table=table)["class"] == "unrecognised":
                out.add(norm_rel(rel))
        except Exception:
            out.add(norm_rel(rel) + " (classify raised)")
    return sorted(out)


def build_baseline(census: dict, old, *, tree: dict | None = None) -> dict:
    """The baseline of a census: one row per hit identity. Refused when the census has a failure or a hit has no writer entry
    (`file_writers`) naming the node that removes it: a row with no node is an expectation, not a debt (FR-58)."""
    verdict = evaluate(census, old)
    if verdict["failures"]:
        raise BaselineRefused("the census has a failure, so no baseline is written from it: " + "; ".join(verdict["failures"][:3]))
    keep = {identity(r): r for r in (old or {}).get("rows") or []}
    rows, unmapped, ids = [], [], [int(m.group(1)) for r in keep.values() for m in [re.match(r"B-(\d+)", r.get("id", ""))] if m]
    nxt = max(ids or [0]) + 1
    seen = {}
    for row in census["hits"]:
        seen.setdefault(identity(row), row)
    for key, row in sorted(seen.items()):
        writer, inv, leaves = writer_for(row, old)
        if inv is None or not leaves:
            unmapped.append(row)
            continue
        mine = keep.get(key)
        rid = mine["id"] if mine else f"B-{nxt:03d}"
        nxt += 0 if mine else 1
        rows.append({"id": rid, "flow": row["flow"], "file": row["file"], "pointer": row["pointer"], "fact": row["fact"],
                     "inventory_row": inv, "leaves_at": leaves})
    if unmapped:
        raise BaselineRefused("no `file_writers` entry (inventory row and the node that removes it) for: " + "; ".join(
            f"{r['flow']} {r['file']} {r['pointer'] or '(whole file)'} {r['fact']}" for r in unmapped[:5])
            + (f" ... and {len(unmapped) - 5} more" if len(unmapped) > 5 else ""))
    out = {k: v for k, v in (old or {}).items() if k not in ("rows", "generated")}
    out.setdefault("baseline_version", 1)
    out["generated"] = {"package_fingerprint": census.get("package_fingerprint"), "tree": tree if tree is not None else census.get("tree")}
    out["rows"] = rows
    return out


def format_baseline(data: dict) -> str:
    """The baseline as text: one row, one writer, one `file_writers` entry per line, so that a person edits it by hand, a diff
    at the package commit is a diff of rows, and the file is deterministic."""
    out = ["{"]
    keys = list(data)
    for i, key in enumerate(keys):
        value, tail = data[key], "," if i < len(keys) - 1 else ""
        head = f"  {json.dumps(key)}: "
        if isinstance(value, list) and value:
            out.append(head + "[")
            out += [f"    {json.dumps(item, ensure_ascii=False)}" + ("," if j < len(value) - 1 else "") for j, item in enumerate(value)]
            out.append("  ]" + tail)
        elif isinstance(value, dict) and value:
            out.append(head + "{")
            items = list(value.items())
            out += [f"    {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}" + ("," if j < len(items) - 1 else "")
                    for j, (k, v) in enumerate(items)]
            out.append("  }" + tail)
        else:
            out.append(head + json.dumps(value, ensure_ascii=False) + tail)
    out.append("}")
    return "\n".join(out) + "\n"


# --- the report --------------------------------------------------------------------------------------------------

def public_census(census: dict) -> dict:
    """The census as census.json holds it: the schema of census_version 1 (internal keys with a leading underscore dropped)."""
    return {k: v for k, v in census.items() if not k.startswith("_")}


NO_NOTES_LINE = ("No notes file (experiments/fr60/census-notes.md): the hand-written sections of this report (how to read it, the "
                 "new-N rows, the limits, the experiments) are not part of it.")


def render_markdown(census: dict, notes_path=None) -> str:
    """The census as Markdown: the generated sections, then the hand-written notes file APPENDED VERBATIM (`notes_path`, by default
    NOTES_FILE). The notes used to be appended to the generated file by hand, and the next `--markdown` run dropped them; a notes
    file that is absent is said in one line, never silently."""
    lines =["# Census of stored environment facts (t-304 N0)", "",
             f"Generated by `scripts/tests/test_state_portability.py --report`; census_version {census['census_version']}, "
             f"python {census['python']} on {census['os']}, package fingerprint `{census['package_fingerprint'][:12]}`.", ""]
    tree = census["tree"]
    uncommitted = tree.get("uncommitted_package_files")
    lines += ["## Tree", "", (f"{len(uncommitted)} package file(s) with uncommitted changes while the census ran (E14: the baseline "
                                "is regenerated once at the package commit):" if uncommitted is not None
                                else f"unknown: {tree.get('unknown')}"), ""]
    lines += [f"- `{p}`" for p in (uncommitted or [])] + [""]
    c = census["counts"]
    lines += ["## Counts", "", f"{c['total']} hit identities ({c['baselined']} in the baseline, {c['new']} new).", ""]
    for title, key in (("By fact", "by_fact"), ("By carrier class", "by_carrier_class"), ("By flow", "by_flow")):
        lines += [f"**{title}:** " + ", ".join(f"{k} {v}" for k, v in c[key].items()), ""]
    lines += ["## Flows", "", "| flow | world | ran | exit | artifacts | seconds |", "|---|---|---|---|---|---|"]
    lines += [f"| {f['id']} | {f['world']} | {f['ran']} | {f['exit']} | {f['files']} | {f['seconds']} |" for f in census["flows"]] + [""]
    snaps = census.get("snapshots") or []
    lines += ["In-flight snapshots (when the stub copied driver-state.json; `after_stdin` is the only observed one): "
              + (", ".join(f"{s['flow']}/{s['world']} {s['taken']}" for s in snaps) or "(none)"), ""]
    lines += ["## Hits", "", "Every hit as flow / file / pointer / fact / writer (worlds and spellings merged).", "",
              "| flow | file | pointer | fact | carrier | writer | row | detector |", "|---|---|---|---|---|---|---|---|"]
    merged: dict = {}
    for r in census["hits"]:
        m = merged.setdefault(identity(r), {**r, "detectors": set()})
        m["detectors"].add(r["detector"])
    for k, r in sorted(merged.items()):
        lines.append(f"| {r['flow']} | `{r['file']}` | `{r['pointer'] or '(whole file)'}` | {r['fact']} | {r['carrier_class']} | "
                     f"{r['writer']} | {r['inventory_row'] or '-'} | {'/'.join(sorted(r['detectors']))} |")
    lines += ["", "## Writers no flow reached (not exercised)", ""]
    lines += [f"- {n['inventory_row']} `{n['site']}`: {n['why']}" for n in census["not_exercised"]] or ["- (none)"]
    lines += ["", "## Differential (a value that differs between worlds A and B on identical inputs)", "",
              "| flow | file | pointer | A | B |", "|---|---|---|---|---|"]
    lines += [f"| {d['flow']} | `{d['file']}` | `{d['pointer']}` | `{str(d['a'])[:70]}` | `{str(d['b'])[:70]}` |" for d in census["differential"]]
    lines += ["", f"Control: package_fingerprint A / A2 / B equal: {census['controls']['package_fingerprint']['equal']}.", ""]
    lines += ["## Noise (differs between two runs of world A: never a hit)", ""]
    lines += [f"- {n['flow']} `{n['file']}` `{n['pointer']}`" for n in census["noise"]] or ["- (none)"]
    lines += ["", "## Not scanned", ""] + ([f"- {n['flow']}/{n['world']} `{n['file']}`: {n['reason']}" for n in census["not_scanned"]] or ["- (none)"])
    lines += ["", "## Unrecognised files (reported, not enforced: N5 enforces)", ""] + ([f"- `{f}`" for f in census["unrecognised_files"]] or ["- (none)"])
    lines += ["", "## Failures", ""] + ([f"- {f}" for f in census["failures"]] or ["- (none)"]) + [""]
    body = "\n".join(lines)
    try:
        notes = Path(notes_path or NOTES_FILE).read_text(encoding="utf-8")
    except OSError:
        return body + "\n" + NO_NOTES_LINE + "\n"
    return body + "\n" + notes
