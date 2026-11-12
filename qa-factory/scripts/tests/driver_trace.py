"""The driver golden's trace library (t-301 N0): record shape, normalisation, tree snapshot, compare, and the
recorder that runs inside every process of a recorded test (loaded by `golden_sitecustomize/sitecustomize.py`).

WHAT THE GOLDEN IS FOR. The driver (`story_run.py`) is about to be split into modules by moves that must change
no behaviour. The rig's assertions look at end states, so a side effect that moves (a state save before or after
the paid call) is invisible to them. The golden is ONE ORDERED TRACE per scenario: every spawn, file write,
rename, removal, copy, network connect, stdout line the driver prints, call a rig fake absorbed, and the final
trees. It is an equivalence reference for moves, never an oracle of correctness (FR-58).

CAPTURE BELOW THE MODULE BOUNDARY. Nothing here patches a `story_run` name, so a moved function cannot bypass it:
the audit hook (open, rename, remove, copy, connect, temp roots), `subprocess.Popen` (spawn, exit, the child's
own stream), `builtins.print` (a driver-module frame only) and `Driver.__setattr__` (a fake assigned to a Driver
method). A write's content digest is DEFERRED to the next audited event of the same process, because the audit
event fires before the bytes exist.

NOTHING HERE IS READ BY THE PACKAGE'S RUNTIME (E16): only `scripts/tests/` mentions the `DRIVER_GOLDEN_` names.
The module is imported by the CLI (`driver_golden.py`) as a plain library; the recorder is installed only by the
sitecustomize, and only when `DRIVER_GOLDEN_SINK` is set.
"""

from __future__ import annotations

import atexit
import builtins
import contextlib
import fnmatch
import hashlib
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

SCHEMA = 1
PREFIX = "DRIVER_GOLDEN_"
ENV_SINK = PREFIX + "SINK"
ENV_SCENARIO = PREFIX + "SCENARIO"
ENV_SPAWN = PREFIX + "SPAWN"
ENV_DEFAULT = PREFIX + "DEFAULT"
ENV_FILE = PREFIX + "FILE"
ENV_MODULES = PREFIX + "MODULES"
ENV_PLUGIN = PREFIX + "PLUGIN"
ENV_COVERAGE = PREFIX + "COVERAGE"
ENV_RULES = PREFIX + "RULES"
ENV_DEBUG_TEXT = PREFIX + "DEBUG_TEXT"

HERE = Path(__file__).resolve().parent
SITE_DIR = HERE / "golden_sitecustomize"
RULES_PATH = HERE / "fixtures" / "driver-golden-rules.json"

LOOPBACK = ("127.0.0.1", "localhost", "::1", "0.0.0.0", "")


def load_rules(path=None) -> dict:
    return json.loads(Path(path or os.environ.get(ENV_RULES) or RULES_PATH).read_text(encoding="utf-8"))


def dumps(record: dict) -> str:
    """Our own record serialisation: key order is not behaviour (sort_keys), ASCII only (K9). File content is never
    re-serialised: it travels as a normalised string inside the record."""
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- normalisation ------------------------------------------------------------------------------------------
_NT = os.name == "nt"


def _short_path(path: str):
    if not _NT:
        return None
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(32768)
        n = ctypes.windll.kernel32.GetShortPathNameW(str(path), buf, 32768)
        return buf.value if n else None
    except Exception:
        return None


def spellings(path) -> set:
    """Every way one path can be spelled in a driver's text: as given, resolved, realpath, the 8.3 short form of each
    (this machine's TEMP is a short path while `Path.resolve()` gives the long one), with forward slashes, with
    JSON-escaped double backslashes, and with the `\\\\?\\` prefix. The match is case-insensitive on Windows."""
    base = {str(path)}
    try:
        base.add(os.path.realpath(str(path)))
    except Exception:
        pass
    try:
        base.add(str(Path(str(path)).resolve()))
    except Exception:
        pass
    for form in list(base):
        short = _short_path(form)
        if short:
            base.add(short)
    out = set()
    for form in base:
        form = form.rstrip("\\/") or form
        out.add(form)
        out.add(form.replace("\\", "/"))
        if "\\" in form:
            out.add(form.replace("\\", "\\\\"))
        if _NT and re.match(r"^[A-Za-z]:\\", form):
            out.add("\\\\?\\" + form)
    return {s for s in out if len(s) > 3}


class _Row:
    """One declarative normalisation row of `driver-golden-rules.json` (FR-13: closed variety lives in data)."""

    def __init__(self, data: dict):
        self.data = data
        self.op = data.get("op", "sub")
        flags = 0
        for letter in data.get("flags", ""):
            flags |= {"i": re.IGNORECASE, "m": re.MULTILINE, "s": re.DOTALL}[letter]
        self.rx = re.compile(data["pattern"], flags)

    def apply(self, reg: "Registry", text: str) -> str:
        d = self.data
        if self.op == "sub":
            return self.rx.sub(d["replace"], text)
        if self.op == "first_seen":
            def rep(match):
                n = reg.number(d["counter"], match.group(d["key"]))
                return match.expand(d["replace"]).replace("{n}", str(n))
            return self.rx.sub(rep, text)
        if self.op == "pid":
            def rep_pid(match):
                n = reg.numbers.get("PID", {}).get(match.group(d["key"]))
                tok = "<PID>" if n is None else f"<PID-{n}>"
                return match.expand(d["replace"].replace("{tok}", tok.replace("\\", "\\\\")))
            return self.rx.sub(rep_pid, text)
        if self.op == "known":
            def rep_known(match):
                held = reg.numbers.get(d["counter"], {})
                if d.get("prefix"):                       # an abbreviation of a registered id (git's 12-hex short form)
                    n = next((num for key, num in held.items() if key.startswith(match.group(0))), None)
                else:
                    n = held.get(match.group(0))
                return match.group(0) if n is None else d["replace"].replace("{n}", str(n))
            return self.rx.sub(rep_known, text)
        if self.op == "revision":
            def rep_rev(match):
                value = match.group("value")
                if value in reg.snapshot_shas:
                    return match.group("head") + "<REV=snapshot>" + match.group("tail")
                return match.group("head") + "<REV-%d>" % reg.number("REV", value) + match.group("tail")
            return self.rx.sub(rep_rev, text)
        raise ValueError(f"unknown normalisation op {self.op!r} in row {d.get('id')!r}")


_ROW_CACHE: dict = {}


def compiled_rows(rules: dict) -> list:
    key = id(rules)
    if key not in _ROW_CACHE or _ROW_CACHE[key][0] is not rules:
        _ROW_CACHE[key] = (rules, [_Row(r) for r in rules.get("rows", [])])
    return _ROW_CACHE[key][1]


class Registry:
    """What one scenario has registered so far: the temp roots (numbered by first registration), the numbered
    tokens of the first-seen rows (uuids, ports, revisions) and the raw digests of the ticket snapshots. It is a
    file `<sink>/<scenario>/registry.json` between the processes of one scenario (they run one after another,
    so first-registration numbering is the same across the tree)."""

    def __init__(self, rules: dict, plugin: str = "", tmp: str = ""):
        self.rules = rules
        self.plugin = plugin
        self.roots: list = []
        self.numbers: dict = {}
        self.snapshot_shas: set = set()
        self._rx = None
        self._tokens: dict = {}
        if not tmp:
            import tempfile
            tmp = tempfile.gettempdir()
        self.tmp = tmp

    # --- persistence
    def to_json(self) -> dict:
        return {"roots": self.roots, "numbers": self.numbers, "snapshot_shas": sorted(self.snapshot_shas)}

    def load_json(self, data: dict) -> None:
        self.roots = list(data.get("roots") or [])
        self.numbers = {k: dict(v) for k, v in (data.get("numbers") or {}).items()}
        self.snapshot_shas = set(data.get("snapshot_shas") or [])
        self._rx = None

    def save(self, path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.to_json()), encoding="utf-8")

    def load(self, path) -> None:
        try:
            self.load_json(json.loads(Path(path).read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass

    # --- registration
    def number(self, counter: str, key: str) -> int:
        held = self.numbers.setdefault(counter, {})
        if key not in held:
            held[key] = len(held) + 1
        return held[key]

    def add_root(self, path) -> int:
        """Register a root (a `tempfile.mkdtemp` / `mkstemp` result); returns its 1-based number. A second spelling
        of an already registered root never becomes a second token (E7)."""
        norm = os.path.normcase(os.path.realpath(str(path)))
        for i, held in enumerate(self.roots):
            if os.path.normcase(os.path.realpath(held)) == norm:
                return i + 1
        self.roots.append(str(path))
        self._rx = None
        return len(self.roots)

    def root_index(self, path):
        norm = os.path.normcase(os.path.realpath(str(path)))
        for i, held in enumerate(self.roots):
            if os.path.normcase(os.path.realpath(held)) == norm:
                return i + 1
        return None

    # --- the path rows N1-N4
    def _build(self) -> None:
        pairs = []                                   # (spelling, token); an earlier category wins a tie
        seen = set()

        def add(path, token):
            for form in spellings(path):
                key = form.lower() if _NT else form
                if key not in seen:
                    seen.add(key)
                    pairs.append((form, token))
        if self.plugin:
            add(self.plugin, "<PLUGIN>")
        for exe in (sys.executable, getattr(sys, "_base_executable", "")):
            if exe:
                add(exe, "<PY>")
        for i, root in enumerate(self.roots, 1):
            add(root, f"<ROOT-{i}>")
        if self.tmp:
            add(self.tmp, "<TMP>")
        pairs.sort(key=lambda p: -len(p[0]))
        self._tokens = {(f.lower() if _NT else f): t for f, t in pairs}
        if pairs:
            # the guard rejects most positions at once (every spelling starts with a drive letter, a `\\?\` prefix or a `/`):
            # an alternation of 30 literals tried at EVERY position of an 80 KB file was most of the recorder's cost
            self._rx = re.compile(r"(?=[A-Za-z]:|\\\\|/)(?:" + "|".join(re.escape(f) for f, _ in pairs) + r")(?![\w-]|\.\w)",
                                  re.IGNORECASE if _NT else 0)
        else:
            self._rx = re.compile(r"(?!x)x")
        # the rig names a task after its temp root (`qa-t261-ctl-83qsh430`): the BARE directory name of a registered root is
        # as random as its path, so it gets its own token (a name 8 characters or longer, whole-word only)
        self._names = {}
        for i, root in enumerate(self.roots, 1):
            base = os.path.basename(str(root).rstrip("\\/"))
            if len(base) >= 8:
                self._names.setdefault(base, f"<ROOT-{i}-NAME>")
        self._name_rx = (re.compile(r"(?<![\w.-])(?:" + "|".join(re.escape(n) for n in sorted(self._names, key=len, reverse=True))
                                    + r")(?![\w-])") if self._names else None)

    def normalise(self, text: str) -> str:
        if not text:
            return text
        if self._rx is None:
            self._build()
        text = self._rx.sub(lambda m: self._tokens[m.group(0).lower() if _NT else m.group(0)], text)
        if self._name_rx is not None:
            text = self._name_rx.sub(lambda m: self._names[m.group(0)], text)
        for row in compiled_rows(self.rules):
            text = row.apply(self, text)
        return text


# --- digests, trees --------------------------------------------------------------------------------------
def digest_bytes(reg: Registry, data: bytes, name: str = "") -> tuple:
    """(sha, size, binary, text). Text that decodes as UTF-8 is normalised and its sha is over the NORMALISED bytes;
    anything else is binary: raw sha, never normalised (E3). `size` is the normalised length for text, the raw length
    for binary, so a value whose digits vary (a pid) cannot move a size."""
    for pattern in reg.rules.get("register_raw_sha", []):
        if fnmatch.fnmatch(name, pattern):
            reg.snapshot_shas.add(hashlib.sha256(data).hexdigest())
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return hashlib.sha256(data).hexdigest(), len(data), True, None
    norm = reg.normalise(text)
    raw = norm.encode("utf-8")
    return hashlib.sha256(raw).hexdigest(), len(raw), False, norm


def _keeps_text(rules: dict, rel: str) -> bool:
    base = rel.rsplit("/", 1)[-1]
    for pattern in rules.get("keep_text", []):
        if "/" in pattern:
            if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(rel, "*/" + pattern):
                return True
        elif fnmatch.fnmatch(base, pattern):
            return True
    return False


def tree_records(reg: Registry, root, caps: dict | None = None) -> list:
    """The `tree` records of one root: [(payload, sha)], one per file or directory, ordered by normalised path.
    `.git/` and `__pycache__` are recorded as present and not entered (rules `tree_exclude`)."""
    rules = reg.rules
    caps = caps or rules.get("caps", {})
    text_cap = int(caps.get("text_bytes", 65536))
    root = Path(root)
    token = reg.normalise(str(root))
    entries = []                                      # (rel, is_dir, excluded, abs)
    if root.is_file():
        entries.append(("", False, False, root))
    elif root.is_dir():
        exclude = set(rules.get("tree_exclude", []))
        for dirpath, dirnames, filenames in os.walk(str(root)):
            dirnames.sort()
            rel_dir = os.path.relpath(dirpath, str(root)).replace("\\", "/")
            rel_dir = "" if rel_dir == "." else rel_dir + "/"
            for d in list(dirnames):
                skip = any(fnmatch.fnmatchcase(d, pattern) for pattern in exclude)      # names or globs (`*.git`: a bare repo)
                entries.append((rel_dir + d, True, skip, Path(dirpath) / d))
                if skip:
                    dirnames.remove(d)
            for f in sorted(filenames):
                entries.append((rel_dir + f, False, False, Path(dirpath) / f))
    out = []
    for order, (rel, is_dir, excluded, path) in enumerate(entries):
        rel_norm = reg.normalise(rel)
        if is_dir:
            payload = {"root": token, "path": rel_norm, "size": 0, "dir": True, "binary": False}
            if excluded:
                payload["excluded"] = True
            out.append((rel_norm, order, payload, None))
            continue
        try:
            data = path.read_bytes()
        except OSError as exc:
            out.append((rel_norm, order, {"root": token, "path": rel_norm, "size": 0, "dir": False, "binary": False,
                                          "unreadable": type(exc).__name__}, None))
            continue
        sha, size, binary, text = digest_bytes(reg, data, path.name)
        payload = {"root": token, "path": rel_norm, "size": size, "dir": False, "binary": binary}
        if text is not None and _keeps_text(rules, rel):
            if size <= text_cap:
                payload["text"] = text
            else:
                payload["text_omitted"] = True
        out.append((rel_norm, order, payload, sha))
    # two files whose names differ only by a normalised token (hook-<PID>.jsonl) tie on the path: the walk order of their REAL
    # names is the process ids' order, which varies; the content's sha is the deterministic tie-break
    out.sort(key=lambda e: (e[0], e[3] or "", e[1]))
    return [(p, s) for _r, _o, p, s in out]


def args_repr(value, depth: int = 0) -> str:
    """A fake call's argument as a short string: str/int/bool/None as they are, list and dict by their members
    (to a small depth), anything else by its type name."""
    if value is None or isinstance(value, (bool, int, float)):
        return repr(value)
    if isinstance(value, str):
        return value
    if depth < 3 and isinstance(value, (list, tuple)):
        return "[" + ", ".join(args_repr(v, depth + 1) for v in list(value)[:20]) + "]"
    if depth < 3 and isinstance(value, dict):
        return "{" + ", ".join(f"{args_repr(k, depth + 1)}: {args_repr(v, depth + 1)}"
                               for k, v in list(value.items())[:20]) + "}"
    return type(value).__name__


# --- finalising a stream -------------------------------------------------------------------------------------
_SKIP_KEYS = {"sha", "out_sha", "err_sha"}


def _norm_obj(obj, reg: Registry, kind: str, key: str = ""):
    if isinstance(obj, str):
        if key in _SKIP_KEYS or (kind == "tree" and key == "text"):
            return obj
        return reg.normalise(obj)
    if isinstance(obj, dict):
        return {k: _norm_obj(v, reg, kind, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_norm_obj(v, reg, kind, key) for v in obj]
    return obj


def finalize(records: list, reg: Registry) -> list:
    """Raw records (already spliced) -> numbered, normalised records. Order is the order they were raised."""
    out = []
    for i, rec in enumerate(records):
        item = {"seq": i, "proc": rec["proc"], "kind": rec["kind"],
                "payload": _norm_obj(rec["payload"], reg, rec["kind"])}
        if rec.get("sha") is not None:
            item["sha"] = rec["sha"]
        out.append(item)
    return out


# --- compare -----------------------------------------------------------------------------------------------
def _text_diff(a: str, b: str, limit: int = 40) -> list:
    import difflib
    if max(len(x) for x in a.split("\n") + b.split("\n")) > 200:      # one very long line (minified HTML, one-line JSON)
        i = 0
        while i < min(len(a), len(b)) and a[i] == b[i]:
            i += 1
        lo = max(0, i - 80)
        return [f"first difference at char {i} (golden {len(a)} chars, now {len(b)} chars):",
                "  golden: ..." + a[lo:i + 120].replace("\n", "\\n"),
                "  now:    ..." + b[lo:i + 120].replace("\n", "\\n")]
    lines = list(difflib.unified_diff(a.split("\n"), b.split("\n"), "golden", "now", lineterm="", n=1))
    if len(lines) > limit:
        return lines[:limit] + [f"({len(lines) - limit} more lines differ)"]
    return lines


def all_diffs(golden: list, now: list, limit: int = 1) -> list:
    """The first `limit` differences between two streams, each {seq, golden, now, text_diff}. The streams are the same
    lines in the same order, or they differ: a missing line on either side is a difference at that position (a
    duplicated or dropped record is as visible as a swapped pair - K4)."""
    out = []
    for i in range(max(len(golden), len(now))):
        g = golden[i] if i < len(golden) else None
        n = now[i] if i < len(now) else None
        if g == n:
            continue
        diff = {"seq": i, "golden": g, "now": n, "text_diff": []}
        try:
            gp, np_ = json.loads(g) if g else {}, json.loads(n) if n else {}
            gt, nt = (gp.get("payload") or {}).get("text"), (np_.get("payload") or {}).get("text")
            if isinstance(gt, str) and isinstance(nt, str) and gt != nt:
                diff["text_diff"] = _text_diff(gt, nt)
        except ValueError:
            pass
        out.append(diff)
        if len(out) >= limit:
            break
    return out


def compare_lines(golden: list, now: list) -> dict | None:
    """None when the two streams are the same lines in the same order; else the FIRST difference (see all_diffs)."""
    found = all_diffs(golden, now, 1)
    return found[0] if found else None


def check_caps(name: str, lines: list, caps: dict) -> str | None:
    """None, or the refusal text: the trace is over its cap (K10), naming the scenario and its five largest records."""
    limit = int(caps.get("trace_bytes", 1048576))
    total = sum(len(line.encode("ascii")) + 1 for line in lines)
    if total <= limit:
        return None
    biggest = sorted(((len(line), i) for i, line in enumerate(lines)), reverse=True)[:5]
    detail = ", ".join(f"seq {i} ({n} B)" for n, i in biggest)
    return (f"scenario {name}: the trace is {total} bytes, over the cap of {limit}; its largest records: {detail}. "
            f"Expected a trace at or under the cap; raise caps.trace_bytes in driver-golden-rules.json by the Lead's "
            f"word, or exclude the scenario by name there.")


# --- the recorder (runs in every process of a recorded test) ----------------------------------------------
RT = None
_WATCHED = frozenset(["open", "os.rename", "shutil.move", "os.remove", "os.rmdir", "shutil.rmtree",
                      "shutil.copyfile", "shutil.copytree", "tempfile.mkdtemp", "tempfile.mkstemp",
                      "socket.connect", "os.system", "os.startfile", "os.spawn", "os.exec", "os.posix_spawn"])


def write_intent(mode, flags):
    """"a" / "w" / "x" / "+" for an open with write intent, else None. `mode` is the string `open()` was given; an
    `os.open` has none, so the flags decide."""
    if isinstance(mode, str) and mode:
        for letter in ("a", "w", "x"):
            if letter in mode:
                return letter
        return "+" if "+" in mode else None
    if isinstance(flags, int):
        if flags & getattr(os, "O_APPEND", 0):
            return "a"
        if flags & getattr(os, "O_TRUNC", 0):
            return "w"
        if flags & getattr(os, "O_EXCL", 0) and flags & getattr(os, "O_CREAT", 0):
            return "x"
        if flags & (os.O_WRONLY | os.O_RDWR | getattr(os, "O_CREAT", 0)):
            return "w" if flags & (os.O_WRONLY | getattr(os, "O_CREAT", 0)) else "+"
    return None


class _Tag:
    """One scenario's records in one process."""

    def __init__(self, rt: "Runtime", name: str, proc: str, reg: Registry):
        self.rt, self.name, self.proc, self.reg = rt, name, proc, reg
        self.records: list = []
        self.pending: list = []
        self.spawns = 0
        self.snapshotted: set = set()
        self.last_move_src = None
        self.lock = threading.RLock()

    def add(self, kind: str, payload: dict, sha=None) -> dict:
        rec = {"proc": self.proc, "kind": kind, "payload": payload}
        if sha is not None:
            rec["sha"] = sha
        with self.lock:
            self.records.append(rec)
        return rec

    def insert_after(self, anchor: dict, new: list) -> None:
        with self.lock:
            for i in range(len(self.records) - 1, -1, -1):
                if self.records[i] is anchor:
                    self.records[i + 1:i + 1] = new
                    return
            self.records.extend(new)

    @property
    def registry_path(self) -> Path:
        return self.rt.tag_dir(self.name) / "registry.json"

    def digest_pending(self) -> None:
        with self.lock:
            pend, self.pending = self.pending, []
        for item in pend:
            rec, path, mode = item["rec"], item["path"], item["mode"]
            payload = rec["payload"]
            try:
                size = os.stat(path).st_size
            except OSError:
                payload["gone"] = True
                continue
            try:
                with open(path, "rb") as handle:
                    if mode == "a":
                        handle.seek(min(item["pre"], size))
                    data = handle.read()
            except OSError as exc:
                payload["unreadable"] = type(exc).__name__
                continue
            sha, nbytes, _binary, _text = digest_bytes(self.reg, data, os.path.basename(path))
            payload["bytes"] = nbytes
            rec["sha"] = sha
            if self.rt.debug_text and _text is not None:       # a debugging aid for --stability, never in a golden
                payload["text"] = _text[:400000]
            stub = os.environ.get("STUB_LOG")
            if mode == "a" and stub and _same_path(path, stub):
                self._stub_records(rec, data)

    def _stub_records(self, anchor: dict, data: bytes) -> None:
        made = []
        for line in data.decode("utf-8", "replace").split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict) or "kind" not in entry:
                continue
            argv = [str(a) for a in (entry.get("argv") or [])]
            payload = {"kind": entry.get("kind"), "role": entry.get("role"), "resume": entry.get("resume"),
                       "flags": [a for a in argv if a.startswith("--")]}
            made.append({"proc": self.proc, "kind": "stub", "payload": payload,
                         "sha": digest_bytes(self.reg, str(entry.get("prompt") or "").encode("utf-8"))[0]})
        if made:
            self.insert_after(anchor, made)


def _same_path(a, b) -> bool:
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
    except Exception:
        return False


def _short_name(path) -> str:
    return os.path.basename(str(path))


class Runtime:
    def __init__(self, env: dict):
        self.sink = Path(env[ENV_SINK])
        self.rules = load_rules(env.get(ENV_RULES) or None)
        self.proc = env.get(ENV_SPAWN) or "0"
        self.is_child = self.proc != "0"
        self.scenario_env = env.get(ENV_SCENARIO) or ""
        self.default_tag = self.scenario_env if self.is_child else (env.get(ENV_DEFAULT) or "_main")
        self.file = env.get(ENV_FILE) or ""
        self.plugin = env.get(ENV_PLUGIN) or ""
        self.debug_text = env.get(ENV_DEBUG_TEXT) == "1"
        self.modules = {m + ".py" for m in (env.get(ENV_MODULES) or "story_run").split(",") if m}
        self.tl = threading.local()
        self.tags: dict = {}
        self.tags_lock = threading.RLock()
        self.errors: list = []
        self.finished: set = set()
        self.started = time.monotonic()
        self.timing: dict = {}
        self.coverage_hits: dict = {}
        self.sink_str = os.path.normcase(str(self.sink))
        self.cov_files = set(self.modules)
        envfile = self.sink / "env0.json"
        if self.is_child:
            try:
                self.root_env = json.loads(envfile.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.root_env = {}
        else:
            self.root_env = strip_ours({k: v for k, v in os.environ.items() if not k.startswith(PREFIX)})
            self.sink.mkdir(parents=True, exist_ok=True)
            envfile.write_text(json.dumps(self.root_env), encoding="utf-8")

    # --- tags
    def tag_dir(self, name: str) -> Path:
        path = self.sink / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def tag_state(self, name: str) -> _Tag:
        with self.tags_lock:
            tag = self.tags.get(name)
            if tag is None:
                reg = Registry(self.rules, self.plugin)
                tag = _Tag(self, name, self.proc, reg)
                if self.is_child:
                    reg.load(tag.registry_path)
                # this process's own id is `PID-<proc>`: a pid written anywhere is then bound to WHICH process it names (F7)
                reg.numbers.setdefault("PID", {})[str(os.getpid())] = self.proc
                self.tags[name] = tag
                begin = {"file": self.file, "scenario": name, "python": "%d.%d" % sys.version_info[:2]}
                if self.is_child:
                    begin["script"] = os.path.basename(sys.argv[0]) if sys.argv and sys.argv[0] else "-c"
                tag.add("begin", begin)
            return tag

    def current_tag(self):
        name = getattr(self.tl, "tag", None)
        if name is None:
            if self.is_child or threading.current_thread() is threading.main_thread():
                name = self.default_tag
            else:
                name = "_untagged"
        if name in self.finished:
            return None
        return self.tag_state(name)

    def ignored(self, path: str) -> bool:
        low = os.path.normcase(path)
        return (low.startswith(self.sink_str) or low in ("nul", os.path.normcase(os.devnull), "conout$", "conin$")
                or low.startswith("\\\\.\\"))

    # --- the audit events
    def _not_a_boundary(self, tag: "_Tag", args: tuple) -> bool:
        """A READ-ONLY open of some other file is not an event boundary for a pending write's digest. Its own `open` raises the
        audit event BEFORE the text wrapper is built, and building the wrapper may import a codec (the first text file of a
        process under a cp1252 locale reads `encodings/cp1252.pyc`): that read-only open arrives between the write's open and
        its content, so digesting there read an EMPTY file in one launch and the real bytes in another (t-374, FR-31). A
        read-only open of the very file that is pending still digests it: the reader is about to see it."""
        path, mode, flags = args[0], args[1], args[2] if len(args) > 2 else None
        if write_intent(mode, flags):
            return False
        if isinstance(path, int) or not isinstance(path, (str, bytes, os.PathLike)):
            return True                                    # an open by descriptor is nobody's boundary
        target = os.path.normcase(_abs(path))
        return not any(os.path.normcase(item["path"]) == target for item in tag.pending)

    def handle(self, event: str, args: tuple) -> None:
        tag = self.current_tag()
        if tag is None:
            return
        if event == "open" and self._not_a_boundary(tag, args):
            return
        tag.digest_pending()
        if event == "open":
            self._on_open(tag, args)
        elif event == "os.rename":
            self._on_rename(tag, args)
        elif event == "shutil.move":
            tag.last_move_src = _abs(args[0])
            tag.add("rename", {"src": _abs(args[0]), "dst": _abs(args[1])})
        elif event in ("os.remove", "os.rmdir"):
            if not _inside_rmtree():
                tag.add("remove" if event == "os.remove" else "rmdir", {"path": _abs(args[0])})
        elif event == "shutil.rmtree":
            path = _abs(args[0])
            idx = tag.reg.root_index(path)
            if idx is not None and path not in tag.snapshotted:
                tag.snapshotted.add(path)
                for payload, sha in tree_records(tag.reg, path):
                    tag.add("tree", payload, sha)
            tag.add("rmtree", {"path": path})
        elif event in ("shutil.copyfile", "shutil.copytree"):
            tag.add("copy", {"src": _abs(args[0]), "dst": _abs(args[1])})
        elif event in ("tempfile.mkdtemp", "tempfile.mkstemp"):
            tag.reg.add_root(args[0])
        elif event == "socket.connect":
            address = args[1] if len(args) > 1 else ""
            if isinstance(address, tuple):
                text = f"{address[0]}:{address[1]}" if len(address) > 1 else str(address[0])
            else:
                text = str(address)
            tag.add("net", {"address": text})
        else:                                           # os.system, os.startfile, os.spawn, os.exec, os.posix_spawn
            tag.add("spawn", {"exe": event, "argv": [args_repr(a) for a in args], "cwd": None, "env_delta": {},
                              "stdin": "inherit", "other": True})

    def _on_open(self, tag: _Tag, args: tuple) -> None:
        path, mode, flags = args[0], args[1], args[2] if len(args) > 2 else None
        if isinstance(path, int) or not isinstance(path, (str, bytes, os.PathLike)):
            return
        intent = write_intent(mode, flags)
        if not intent:
            return
        path = _abs(path)
        if self.ignored(path):
            return
        try:
            pre = os.stat(path).st_size
        except OSError:
            pre = 0
        rec = tag.add("write", {"path": path, "mode": intent, "bytes": None})
        tag.pending.append({"rec": rec, "path": path, "mode": intent, "pre": pre})

    def _on_rename(self, tag: _Tag, args: tuple) -> None:
        src = _abs(args[0])
        if tag.last_move_src is not None and tag.last_move_src == src:
            tag.last_move_src = None                    # the `os.rename` a `shutil.move` raised: one record
            return
        tag.add("rename", {"src": src, "dst": _abs(args[1])})

    # --- finishing a scenario
    def snapshot_live_roots(self, tag: _Tag) -> None:
        for root in list(tag.reg.roots):
            if root in tag.snapshotted or not os.path.exists(root):
                continue
            tag.snapshotted.add(root)
            for payload, sha in tree_records(tag.reg, root):
                tag.add("tree", payload, sha)

    def finish_tag(self, name: str, outcome: str) -> None:
        tag = self.tag_state(name)
        tag.digest_pending()
        if not self.is_child:
            self.snapshot_live_roots(tag)
            tag.add("end", {"outcome": outcome})
        with tag.lock:
            self.finished.add(name)
        if self.is_child:
            tag.reg.save(tag.registry_path)
            path = self.tag_dir(name) / (self.proc + ".jsonl")
            path.write_text("\n".join(json.dumps(r) for r in tag.records) + "\n", encoding="utf-8")
            return
        lines = [dumps(r) for r in finalize(tag.records, tag.reg)]
        final = self.sink / "final"
        final.mkdir(parents=True, exist_ok=True)
        (final / (name + ".jsonl")).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    def exit(self) -> None:
        """atexit: finish every tag still open. A child writes its stream, the root writes its finals."""
        self.tl.busy = True
        try:
            if self.errors:
                self.tag_state(self.default_tag).add("hook_error", {"errors": list(self.errors)[:10]})
            with self.tags_lock:
                names = [n for n in self.tags if n not in self.finished]
            if not self.tags:
                names = [self.default_tag]
            for name in names:
                if name == "_outside" and not self.is_child:
                    tag = self.tag_state(name)
                    tag.digest_pending()
                    self.snapshot_live_roots(tag)
                    # an `_outside` stream with nothing in it is not a scenario: no file, no refusal
                    if len(tag.records) <= 1:
                        self.finished.add(name)
                        continue
                self.finish_tag(name, "returned")
            self._write_coverage()
            if not self.is_child:
                (self.sink / "timing.json").write_text(json.dumps(
                    {"scenarios": self.timing, "process_seconds": round(time.monotonic() - self.started, 3)}),
                    encoding="utf-8")
        except Exception as exc:                          # the last word of a dying process: leave a marker
            try:
                (self.sink / f"exit-error-{self.proc}.txt").write_text(f"{type(exc).__name__}: {exc}", encoding="utf-8")
            except OSError:
                pass

    def _write_coverage(self) -> None:
        if not self.coverage_hits:
            return
        out = self.sink / "coverage"
        out.mkdir(parents=True, exist_ok=True)
        data = {base: sorted(lines) for base, lines in self.coverage_hits.items()}
        (out / f"{self.proc}-{os.getpid()}.json").write_text(json.dumps(data), encoding="utf-8")


def strip_ours(env: dict) -> dict:
    """The environment without the recorder's own PYTHONPATH entry (the `env_delta` of a spawn never shows it)."""
    ours = os.path.normcase(str(SITE_DIR))
    env = dict(env)
    held = env.get("PYTHONPATH", "")
    if held:
        kept = [p for p in held.split(os.pathsep) if os.path.normcase(p) != ours]
        if kept:
            env["PYTHONPATH"] = os.pathsep.join(kept)
        else:
            env.pop("PYTHONPATH", None)
    return env


def _abs(path) -> str:
    try:
        return os.path.abspath(os.fsdecode(path))
    except Exception:
        return str(path)


def _inside_rmtree() -> bool:
    frame = sys._getframe(3)
    for _ in range(14):
        if frame is None:
            return False
        if frame.f_code.co_filename.endswith("shutil.py") and "rmtree" in frame.f_code.co_name:
            return True
        frame = frame.f_back
    return False


@contextlib.contextmanager
def quiet():
    """Our own reads and writes are not events (a guard against the hook seeing itself)."""
    tl = RT.tl
    prev = getattr(tl, "busy", False)
    tl.busy = True
    try:
        yield
    finally:
        tl.busy = prev


def _audit(event, args):
    if event not in _WATCHED:
        return
    rt = RT
    tl = rt.tl
    if getattr(tl, "busy", False):
        return
    tl.busy = True
    try:
        rt.handle(event, args)
    except Exception as exc:
        rt.errors.append(f"{event}: {type(exc).__name__}: {exc}")
    finally:
        tl.busy = False


@contextlib.contextmanager
def scenario(name: str):
    """The rig's `run_scenarios` runs each scenario under this (only when the recorder is installed): the events of
    this thread are filed under `name` until it ends (E6)."""
    rt = RT
    if name in rt.tags:
        raise RuntimeError(f"scenario {name!r} was started twice in one file: a scenario name is its identity; rename one")
    started = time.monotonic()
    rt.tl.tag = name
    with quiet():
        rt.tag_state(name)
        try:                                              # for a hung file: the CLI names the last scenario that began
            (rt.sink / "progress.txt").write_text(name, encoding="utf-8")
        except OSError:
            pass
    outcome = "returned"
    try:
        yield
    except BaseException as exc:
        outcome = "raised: " + type(exc).__name__
        raise
    finally:
        rt.tl.tag = None
        rt.tl.busy = True
        try:
            rt.finish_tag(name, outcome)
            rt.timing[name] = round(time.monotonic() - started, 3)
        finally:
            rt.tl.busy = False


# --- wrappers below the module boundary -------------------------------------------------------------------
def _is_python(exe: str) -> bool:
    base = os.path.basename(str(exe)).lower()
    return base.startswith("python") or base in ("py", "py.exe") or _same_path(exe, sys.executable)


def _script_of(argv: list) -> str:
    """The script a Python command line runs: `-c` for an inline program, else the first argument that is no option."""
    rest = argv[1:]
    if "-c" in rest and not any(not a.startswith("-") for a in rest[:rest.index("-c")]):
        return "-c"
    return next((os.path.basename(a) for a in rest if not a.startswith("-")), "")


def _wrap_popen(rt: Runtime) -> None:
    import subprocess
    cls = subprocess.Popen
    orig_init, orig_comm, orig_wait = cls.__init__, cls.communicate, cls.wait

    def __init__(self, args, bufsize=-1, executable=None, stdin=None, stdout=None, stderr=None, preexec_fn=None,
                 close_fds=True, shell=False, cwd=None, env=None, *rest, **kw):
        if getattr(rt.tl, "busy", False):
            return orig_init(self, args, bufsize, executable, stdin, stdout, stderr, preexec_fn, close_fds, shell,
                             cwd, env, *rest, **kw)
        tag = rt.current_tag()
        if tag is None:
            return orig_init(self, args, bufsize, executable, stdin, stdout, stderr, preexec_fn, close_fds, shell,
                             cwd, env, *rest, **kw)
        with quiet():
            tag.digest_pending()
            tag.spawns += 1
            proc = f"{tag.proc}.{tag.spawns}"
            base = dict(os.environ if env is None else env)
            child = dict(base)
            ours = str(SITE_DIR)
            old = strip_ours(child).get("PYTHONPATH", "")
            child["PYTHONPATH"] = ours + (os.pathsep + old if old else "")
            child[ENV_SINK] = str(rt.sink)
            child[ENV_SCENARIO] = tag.name
            child[ENV_SPAWN] = proc
            for name in (ENV_RULES, ENV_MODULES, ENV_PLUGIN, ENV_COVERAGE, ENV_DEBUG_TEXT):
                if name in os.environ:
                    child.setdefault(name, os.environ[name])
            argv = [str(a) for a in args] if isinstance(args, (list, tuple)) else [str(args)]
            exe = str(executable or (argv[0] if argv else ""))
            python = (not shell) and bool(argv) and _is_python(argv[0])
            delta = {}
            seen = strip_ours({k: v for k, v in child.items() if not k.startswith(PREFIX)})
            for k in sorted(set(seen) | set(rt.root_env)):
                if seen.get(k) != rt.root_env.get(k):
                    delta[k] = seen.get(k)
            payload = {"exe": "<PY>" if python else os.path.basename(exe), "argv": argv,
                       "cwd": str(cwd) if cwd is not None else None, "env_delta": delta,
                       "stdin": "pipe" if stdin == subprocess.PIPE else ("devnull" if stdin == subprocess.DEVNULL
                                                                        else "inherit")}
            rec = tag.add("spawn", payload)
            tag.reg.save(tag.registry_path)
        try:
            orig_init(self, args, bufsize, executable, stdin, stdout, stderr, preexec_fn, close_fds, shell, cwd,
                      child, *rest, **kw)
        except BaseException as exc:
            tag.insert_after(rec, [{"proc": tag.proc, "kind": "exit",
                                    "payload": {"of": proc, "code": None, "error": type(exc).__name__,
                                                "out_lines": 0, "err_lines": 0, "out_sha": "", "err_sha": ""}}])
            raise
        self._golden = {"tag": tag, "proc": proc, "rec": rec, "python": python, "done": False, "in_comm": False,
                        "argv": argv, "wait_rec": None}
        with quiet():                                      # the child's id is `PID-<proc>` wherever it is written (F7)
            tag.reg.numbers.setdefault("PID", {})[str(self.pid)] = proc
            tag.reg.save(tag.registry_path)

    def _mark_wait(g):
        """The `wait` record: where the parent starts waiting for the child. Whatever the parent did between Popen and here
        (B-268: the in-flight marking) stays BEFORE it; the child's records are spliced AFTER it (F4)."""
        if g["wait_rec"] is None and not g["done"]:
            with quiet():
                g["tag"].digest_pending()
                g["wait_rec"] = g["tag"].add("wait", {"of": g["proc"]})

    def _finish(self, out, err):
        g = self._golden
        if g["done"]:
            return
        g["done"] = True
        tag, proc = g["tag"], g["proc"]
        with quiet():
            tag.digest_pending()
            tag.reg.load(tag.registry_path)
            block = []
            stream = rt.tag_dir(tag.name) / (proc + ".jsonl")
            script = _script_of(g["argv"])
            if g["python"] and g.get("killed"):
                # the DRIVER killed it (a rig scenario that makes the marking raise): a process killed before its own exit writes
                # no stream, and what it did before is a race. Recorded as killed, whatever it left; never a refusal (E9)
                block.append({"proc": proc, "kind": "child_killed", "payload": {"proc": proc, "script": script}})
            elif g["python"]:
                if stream.is_file():
                    child_records = [json.loads(line) for line in stream.read_text(encoding="utf-8").split("\n")
                                     if line.strip()]
                    for i, crec in enumerate(child_records):
                        if i == 0 and crec["kind"] == "begin":
                            block.append({"proc": proc, "kind": "child",
                                          "payload": {"proc": proc, "script": crec["payload"].get("script") or script}})
                        else:
                            block.append(crec)
                    block.append({"proc": proc, "kind": "child_end", "payload": {"proc": proc}})
                else:
                    block.append({"proc": proc, "kind": "hook_missing", "payload": {"proc": proc, "script": script}})

            def lines_of(stream_text):
                if stream_text is None:
                    return 0, ""
                if isinstance(stream_text, bytes):
                    stream_text = stream_text.decode("utf-8", "replace")
                norm = tag.reg.normalise(stream_text)
                count = norm.count("\n") + (1 if norm and not norm.endswith("\n") else 0)
                return count, sha256_text(norm)
            ol, osha = lines_of(out)
            el, esha = lines_of(err)
            payload = {"of": proc, "code": self.returncode, "out_lines": ol, "err_lines": el, "out_sha": osha, "err_sha": esha}
            if rt.debug_text:                              # a debugging aid for --stability, never in a golden
                for key, stream_text in (("out_text", out), ("err_text", err)):
                    if stream_text:
                        if isinstance(stream_text, bytes):
                            stream_text = stream_text.decode("utf-8", "replace")
                        payload[key] = tag.reg.normalise(stream_text)[:3000]
            block.append({"proc": proc, "kind": "exit", "payload": payload})
            tag.insert_after(g["wait_rec"] or g["rec"], block)

    def communicate(self, input=None, timeout=None):
        g = getattr(self, "_golden", None)
        if g is None:
            return orig_comm(self, input, timeout)
        if input is not None and g["rec"].get("sha") is None:
            with quiet():
                text = input.decode("utf-8", "replace") if isinstance(input, bytes) else str(input)
                g["rec"]["sha"] = sha256_text(g["tag"].reg.normalise(text))
        _mark_wait(g)
        g["in_comm"] = True
        try:
            out, err = orig_comm(self, input, timeout)
        finally:
            g["in_comm"] = False
        _finish(self, out, err)
        return out, err

    def wait(self, timeout=None):
        g = getattr(self, "_golden", None)
        if g is not None:
            _mark_wait(g)
        code = orig_wait(self, timeout)
        if g is not None and not g["in_comm"] and not g["done"]:
            _finish(self, None, None)
        return code

    def killing(orig):
        def stop(self, *args, **kwargs):
            g = getattr(self, "_golden", None)
            if g is not None:
                g["killed"] = True
            return orig(self, *args, **kwargs)
        return stop

    cls.__init__, cls.communicate, cls.wait = __init__, communicate, wait
    cls.kill, cls.terminate = killing(cls.kill), killing(cls.terminate)


def _wrap_print(rt: Runtime) -> None:
    real = builtins.print

    def print(*args, sep=" ", end="\n", file=None, flush=False):       # noqa: A001 - it replaces the builtin on purpose
        try:
            frame = sys._getframe(1)
            if os.path.basename(frame.f_code.co_filename) in rt.modules and not getattr(rt.tl, "busy", False):
                tag = rt.current_tag()
                if tag is not None:
                    if file is None or file is sys.stdout:
                        stream = "out"
                    elif file is sys.stderr or file is sys.__stderr__:
                        stream = "err"
                    else:
                        stream = "other"
                    text = (sep if isinstance(sep, str) else " ").join(str(a) for a in args) + (
                        end if isinstance(end, str) else "\n")
                    tag.add("stdout", {"text": text, "stream": stream})
        except Exception as exc:
            rt.errors.append(f"print: {type(exc).__name__}: {exc}")
        return real(*args, sep=sep, end=end, file=file, flush=flush)

    builtins.print = print


def _wrap_driver(rt: Runtime, module) -> None:
    """Q4: a callable assigned to a Driver instance under the name of a Driver method is a rig fake; its calls are
    recorded in order. Data and `self.sleep` (not a method) are left alone."""
    cls = getattr(module, "Driver", None)
    if cls is None or getattr(cls, "_golden_wrapped", False):
        return

    def is_method(klass, name):
        for base in klass.__mro__:
            if name in base.__dict__:
                held = base.__dict__[name]
                return isinstance(held, (staticmethod, classmethod)) or callable(held)
        return False

    def recording(name, fake):
        def call(*args, **kwargs):
            tag = None if getattr(rt.tl, "busy", False) else rt.current_tag()
            if tag is not None:
                parts = [args_repr(a) for a in args] + [f"{k}={args_repr(v)}" for k, v in sorted(kwargs.items())]
                for index, token in (rt.rules.get("fake_arg_tokens") or {}).get(name, {}).items():   # an OS number passed as an argument
                    if int(index) < len(args):
                        n = tag.reg.numbers.get("PID", {}).get(parts[int(index)])      # a process of this scenario: PID-<proc>
                        parts[int(index)] = token if n is None else f"<PID-{n}>"
                tag.add("fake_call", {"name": name, "args": parts})
            return fake(*args, **kwargs)
        return call

    def __setattr__(self, name, value):
        if callable(value) and not isinstance(value, type) and is_method(type(self), name):
            value = recording(name, value)
        object.__setattr__(self, name, value)

    cls.__setattr__ = __setattr__
    cls._golden_wrapped = True


class _StoryRunFinder:
    """Wraps the loader of `story_run` so the Driver is patched right after the module body ran (no event can
    come between the import and the patch)."""

    def __init__(self, rt: Runtime):
        self.rt = rt
        self.busy = False

    def find_spec(self, name, path=None, target=None):
        if name != "story_run" or self.busy:
            return None
        import importlib.machinery
        self.busy = True
        try:
            spec = importlib.machinery.PathFinder.find_spec(name, path)
        finally:
            self.busy = False
        if spec is None or spec.loader is None:
            return None
        loader, rt = spec.loader, self.rt
        orig = loader.exec_module

        def exec_module(module):
            orig(module)
            _wrap_driver(rt, module)
        loader.exec_module = exec_module
        return spec


def _start_coverage(rt: Runtime) -> None:
    mon = getattr(sys, "monitoring", None)
    if mon is None:
        rt.errors.append("coverage: sys.monitoring needs Python 3.12 or newer")
        return
    tool = next((i for i in (1, 2, 3, 4, 5, 0) if mon.get_tool(i) is None), None)
    if tool is None:
        rt.errors.append("coverage: no free sys.monitoring tool id")
        return
    mon.use_tool_id(tool, "driver-golden")
    hits = rt.coverage_hits
    wanted = rt.cov_files

    def on_line(code, line):
        base = os.path.basename(code.co_filename)
        if base in wanted:
            hits.setdefault(base, set()).add(line)
        return mon.DISABLE
    mon.register_callback(tool, mon.events.LINE, on_line)
    mon.set_events(tool, mon.events.LINE)


def install(env=None):
    """Install the recorder in THIS process. Called by the sitecustomize; does nothing without the sink variable."""
    global RT
    env = os.environ if env is None else env
    if not env.get(ENV_SINK) or RT is not None:
        return RT
    sys.dont_write_bytecode = True
    RT = Runtime(env)
    RT.tl.busy = True
    try:
        sys.addaudithook(_audit)
        _wrap_popen(RT)
        _wrap_print(RT)
        sys.meta_path.insert(0, _StoryRunFinder(RT))
        if env.get(ENV_COVERAGE) == "1":
            _start_coverage(RT)
        atexit.register(RT.exit)
        RT.tag_state(RT.default_tag)
    finally:
        RT.tl.busy = False
    return RT
