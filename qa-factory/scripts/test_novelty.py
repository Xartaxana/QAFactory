"""Is a test NEW, CHANGED or UNCHANGED since the story's base - measured, in the safe direction.

Whether a probe is owed to a test depends on it (t-134 redraft, piece P5-B). The one error this
measure may make is toward a live check nobody needed: `unchanged` for a test that is new or
changed lets an old green stand for code nobody ran, so `unchanged` is returned only when the
evidence is complete and everything else is `new`, `changed` or `unknown`:

  measure(project_root, test_rel, function, class_chain=(), extra_files=(), base_record=None,
          run_cwd=None)
  measure_many(project_root, items, base_record=None, run_cwd=None)   # one call per manifest write

Both answer `{"value": "new|changed|unchanged|unknown", "basis": <words a person may read>,
"base": {"kind": "s0|head_now|none", "sha": <40 hex or "">}, "measured_on": {<project-relative
path>: <raw sha256>}}` and never raise: any exception is an `unknown` that names its class.
A measure_many item is a dict `{"test_rel", "function", "class_chain", "extra_files"}` (the last two
optional). `measure` is `measure_many` with one item.

Which base (R2.1, and the owner's rule of 30.09 that an unmeasured green counts as proven, so a
measure that CANNOT decide says `unknown` and never guesses `unchanged`):

  s0        the recorded state of the test repository at the S0 exit (`test_repo_base.load`): git
            ok, a commit, not late, the dirty list not truncated. The ONLY base against which
            `unchanged` is ever returned.
  head_now  no usable record (none, `{}`, git not ok, empty head, late, truncated) but git answers:
            the repository's HEAD now. A test committed during the story equals it, so equality is
            `unknown` here; `new` and `changed` stay.
  none      git does not answer: everything is `unknown`.

What is compared (function_sha, V4): the test's own function and what it names, in the working
tree and in a mirror of the base. The measured set is every file `function_sha` parsed (the test,
the conftests, the `__init__` chain, the project modules it resolved) PLUS every conftest.py from
the test's folder up to the PROJECT root (the run's own chain stops at the run's cwd), PLUS the
pytest configuration files of those folders. A file the base had and the tree no longer has is
mirrored too, so a deleted conftest or module is a difference. One base mirror in the OS temp dir
per call (removed in `finally`), one `git cat-file --batch` process, one parse cache per
side, shared by every item (V3, FR-55: a mirror per test cost 4-5 s per function on this machine).

Order that holds the safe direction: ignored by git -> unknown (an ignored file has no base, so it
must not read as `new`); absent at the base -> new; a file that was uncommitted at S0 is judged by
what the record says of it BEFORE any equality can be claimed (changed since S0 -> changed; absent
from the base commit -> it did not exist at the base, never `unchanged`); then the configuration
files; then function_sha of both sides.

Named residuals (the answer says `unchanged` without them):
  - data read by the test that no import reaches (a JSON/YAML expectation) is invisible to both
    sides (B-217 class);
  - a fixture living in a `pytest_plugins` module is not compared (the basis says so when the
    measured files name `pytest_plugins`);
  - a module DELETED since the base that lies outside the project root is not mirrored.
"""
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

GIT_TIMEOUT = 60
# pytest.toml / .pytest.ini / .pytest.toml are pytest's own names in newer versions; they always
# carry configuration. The other three carry it only under their pytest section.
CONFIG_NAMES = ("pytest.ini", ".pytest.ini", "pytest.toml", ".pytest.toml",
                "pyproject.toml", "setup.cfg", "tox.ini")
_SECTION = {"pyproject.toml": "[tool.pytest", "setup.cfg": "[tool:pytest]", "tox.ini": "[pytest]"}
_OID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$", re.IGNORECASE)


# --- the words (one per outcome; nothing here names a field, a script or a stage) --------------
def _label(kind, sha):
    if kind == "s0":
        return f"the story's base {sha[:12]}"
    return f"HEAD now ({sha[:12]}), because no base was recorded when the story began"


def words_no_git(why=""):
    return ("git is not available here, so whether this test is new cannot be measured"
            + (f" ({why})" if why else ""))


def words_unchanged(kind, sha, plugins=False):
    text = (f"the test and everything it uses are the same as at {_label(kind, sha)} "
            "(comments, blank lines and case markers do not count)")
    if plugins:
        text += ("; fixtures that come from pytest plugin modules (pytest_plugins) are not "
                 "compared")
    return text


WORDS_HEAD_NOW_EQUAL = ("equal to HEAD now, but no base was recorded when the story began: a test "
                        "committed during the story would look the same")
WORDS_ROW_NOT_MEASURABLE = ("the test's code cannot be measured (not Python, not UTF-8, or it does "
                            "not tokenize)")
WORDS_IGNORED = "the file is ignored by git; its state before the story is unknown"


def words_test_file_new(kind, sha):
    return f"the test file did not exist at {_label(kind, sha)}"


def words_function_new(kind, sha):
    return f"the test function did not exist in its file at {_label(kind, sha)}"


def words_dirty_changed(rel):
    return f"{rel} changed since the story began"


def words_untracked_at_s0(rel, kind, sha):
    return (f"{rel} did not exist at {_label(kind, sha)} (it was an uncommitted file when the "
            "story began)")


def words_changed(kind, sha, name):
    return (f"the test, or a file it uses, changed since {_label(kind, sha)} "
            f"(first difference: {name})")


def words_config_changed(rel, kind, sha):
    return f"{rel} (the pytest configuration) changed since {_label(kind, sha)}"


def words_outside(path):
    return f"{path} lies outside the test repository"


def words_base_unreadable(kind, sha):
    return (f"git cannot show {_label(kind, sha)} (the commit may have been removed), so the test "
            "cannot be compared with it")


def words_base_not_python(kind, sha):
    return f"the test file at {_label(kind, sha)} does not parse as Python, so it cannot be compared"


def words_base_unmeasurable(kind, sha):
    return (f"what the test uses cannot be read the same way at {_label(kind, sha)} as now, so it "
            "counts as changed")


def words_symlink(rel):
    return f"{rel} is a symbolic link, which cannot be compared with the base"


def words_cannot_rebuild(rel):
    return (f"{rel} cannot be rebuilt as it was at the base (a link, a submodule, or a name this "
            "machine cannot write)")


def words_lost(rel):
    return f"{rel} was changed before the story began and has since been deleted"


def words_exception(exc):
    return (f"measuring this test failed ({type(exc).__name__}), so whether it is new is unknown")


# --- result shape -------------------------------------------------------------------------------
def _result(value, basis, kind="none", sha="", measured_on=None):
    return {"value": value, "basis": basis, "base": {"kind": kind, "sha": sha},
            "measured_on": dict(measured_on or {})}


class _Done(Exception):
    """Ends one item (or a whole group) with its answer; the only control flow here."""

    def __init__(self, value, basis, kind="none", sha="", measured_on=None):
        super().__init__(basis)
        self.value, self.basis, self.kind, self.sha = value, basis, kind, sha
        self.measured_on = measured_on

    def result(self):
        return _result(self.value, self.basis, self.kind, self.sha, self.measured_on)


# --- small helpers ------------------------------------------------------------------------------
def _nc(path):
    return os.path.normcase(str(path))


def _sha256_file(path):
    """The raw working-tree bytes' hash, "" for anything that is not a readable file - the same
    algorithm `test_repo_base` recorded the dirty paths with (one definition, FR-17)."""
    import test_repo_base
    return test_repo_base._sha256_file(path)


def _git(cwd, args, stdin=None):
    """(return code, stdout bytes); return code None when git could not be run at all. Read-only,
    never prompts. (No literal-pathspec switch: `check-ignore` refuses it outright.)"""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="Never")
    try:
        done = subprocess.run(["git", *args], cwd=str(cwd), input=stdin, capture_output=True,
                              timeout=GIT_TIMEOUT, env=env)
    except (OSError, subprocess.SubprocessError):
        return None, b""
    return done.returncode, done.stdout


def _remove_tree(path):
    """rmtree that survives read-only files (a git object store, a copied read-only file)."""
    def force(func, target, _info):
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            pass
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=force)
    else:
        shutil.rmtree(path, onerror=force)


def _norm_bytes(data):
    return data.replace(b"\r\n", b"\n")


def _read(path):
    """The file's bytes, or None when it is not a readable file."""
    try:
        return Path(path).read_bytes() if os.path.isfile(path) else None
    except OSError:
        return None


def _carries_pytest(name, data):
    """Does this configuration file carry pytest's configuration? `pytest.ini` and its siblings
    always do; the shared files only under their pytest section."""
    marker = _SECTION.get(name)
    if marker is None:
        return True
    return marker in data.decode("utf-8", errors="replace")


def _split_batch(out, count):
    """The blobs of a `cat-file --batch` answer, in request order; None for a `missing` line."""
    blobs, pos = [], 0
    for _ in range(count):
        eol = out.find(b"\n", pos)
        if eol < 0:
            raise ValueError("git cat-file answered fewer objects than were asked for")
        header = out[pos:eol].decode("utf-8", errors="replace")
        pos = eol + 1
        if header.endswith(" missing"):
            blobs.append(None)
            continue
        parts = header.split(" ")
        if len(parts) < 3 or parts[-2] != "blob":
            raise ValueError(f"git cat-file answered {header[:60]!r}, not a blob")
        size = int(parts[-1])
        blobs.append(out[pos:pos + size])
        pos += size + 1
    return blobs


def _read_record(record):
    """`(head, {nc(path): sha256})` when the record is a usable S0 base, else None. Strict on
    purpose: a record this code cannot read whole is not evidence of anything."""
    if not isinstance(record, dict) or record.get("git") != "ok":
        return None
    head = record.get("head")
    if not isinstance(head, str) or not _OID.match(head):   # never an option or a ref name
        return None
    if record.get("late") is not False or record.get("dirty_truncated") is not False:
        return None
    dirty = record.get("dirty")
    if not isinstance(dirty, list):
        return None
    table = {}
    for entry in dirty:
        if (not isinstance(entry, dict) or not isinstance(entry.get("path"), str)
                or not isinstance(entry.get("sha256"), str)):
            return None
        key = _nc(entry["path"])
        if table.setdefault(key, entry["sha256"]) != entry["sha256"]:
            return None
    return head.lower(), table


class _View(dict):
    """The parse cache of ONE item over the cache every item shares: it remembers which files the
    item's own measurement touched (so `measured_on` is the item's, not the union), while each
    file is parsed once for the whole call. `function_sha` only uses `in`, `[]` and `[]=`."""

    def __init__(self, shared):
        super().__init__()
        self._shared = shared
        self.touched = {}

    def __contains__(self, key):
        return key in self._shared

    def __getitem__(self, key):
        self.touched[key] = True
        return self._shared[key]

    def __setitem__(self, key, value):
        self._shared[key] = value

    def get(self, key, default=None):
        return self[key] if key in self._shared else default


# --- the run's cwd ------------------------------------------------------------------------------
def resolve_run_cwd(project_root, test_rel, run_cwd=None, cfg=None):
    """`(path, how)`: how the run's working directory was found. `given` when the caller says;
    `profile` when the project's configuration has a profile for this test and
    `probe_by_code._profile_cwd` (the one derivation the probe itself uses) names its cwd;
    `project_root` otherwise - no configuration, no profile for the file, or `probe_by_code` not
    importable. The measured set reaches the project root either way (V4), so this only decides
    which conftests the run's own chain would have listed."""
    root = Path(os.path.abspath(str(project_root)))
    if run_cwd not in (None, ""):
        return Path(os.path.abspath(os.path.join(str(root), str(run_cwd)))), "given"
    if cfg is None:
        try:
            import json
            cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    if isinstance(cfg, dict) and cfg.get("profiles"):
        try:
            import probe_by_code
            cwd = probe_by_code._profile_cwd(cfg, str(test_rel).replace("\\", "/"))
            if cwd not in ("", "."):    # "." is what it answers for "no profile owns this file"
                return Path(os.path.abspath(os.path.join(str(root), cwd))), "profile"
        except Exception:
            pass
    return root, "project_root"


# --- one call's state ---------------------------------------------------------------------------
class _Ctx:
    """Everything one call shares. File facts are remembered: on this machine a `stat` costs about
    a millisecond, and every item of one file asks the same questions about the same folders."""

    def __init__(self, project_root, record, run_cwd):
        self._real = {}
        self._tops = {}
        self._cfg = None
        self._isfile, self._bytes, self.dirs = {}, {}, {}
        # Everything below is spelled with REAL paths (canonical case, long names): git's own
        # top is, and a path compared with it must not differ by the spelling of a short name.
        self.project = Path(self.real(os.path.abspath(str(project_root))))
        self.s0 = _read_record(record)
        self.run_cwd = run_cwd
        self.git_path = shutil.which("git")
        self.mirror = None
        self.groups = 0
        self.shared_now = {}
        self.project_real = self.real(self.project)

    def isfile(self, path):
        key = str(path)
        if key not in self._isfile:
            self._isfile[key] = os.path.isfile(key)
        return self._isfile[key]

    def read(self, path):
        """The bytes of a file of the working tree, or None; once per call."""
        key = str(path)
        if key not in self._bytes:
            self._bytes[key] = _read(key) if self.isfile(key) else None
        return self._bytes[key]

    def config(self):
        """The project's configuration, read once per call; `{}` when it cannot be read."""
        if self._cfg is None:
            try:
                import json
                self._cfg = json.loads((self.project / "qa-factory" / "config.json")
                                       .read_text(encoding="utf-8"))
            except Exception:
                self._cfg = {}
        return self._cfg

    def real(self, path):
        key = str(path)
        if key not in self._real:
            self._real[key] = os.path.realpath(key)
        return self._real[key]

    def under(self, path, root_real):
        try:
            return os.path.commonpath([_nc(self.real(path)), _nc(root_real)]) == _nc(root_real)
        except ValueError:
            return False

    def rel_to(self, root_real, path):
        """`path` relative to `root_real`, posix; "" for the root itself; None when outside."""
        try:
            rel = os.path.relpath(self.real(path), root_real)
        except ValueError:
            return None
        rel = rel.replace(os.sep, "/")
        if rel == ".":
            return ""
        if rel == ".." or rel.startswith("../"):
            return None
        return rel

    def top_of(self, directory):
        """The real path of the repository top `directory` lies in; raises `_Done` (unknown, base
        kind none) when there is no git, or no repository, or git does not answer."""
        if self.git_path is None:
            raise _Done("unknown", words_no_git("there is no git program on this machine"))
        here = Path(self.real(directory))
        for cur in (here, *here.parents):
            if str(cur) in self._tops:
                return self._tops[str(cur)]
            if (cur / ".git").exists():
                code, out = _git(cur, ["rev-parse", "--show-toplevel"])
                text = out.decode("utf-8", errors="replace").strip()
                if code != 0 or not text:
                    raise _Done("unknown", words_no_git(f"git did not answer in {cur.as_posix()}"))
                top = os.path.realpath(text)
                self._tops[str(cur)] = top
                return top
        raise _Done("unknown", words_no_git("the test folder is not inside a git repository"))

    def new_mirror_dir(self):
        """ONE mirror root per call, one subfolder per repository."""
        if self.mirror is None:
            self.mirror = tempfile.mkdtemp(prefix="qa-novelty-")
        self.groups += 1
        folder = os.path.join(self.mirror, f"r{self.groups}")
        os.makedirs(folder, exist_ok=True)
        return folder


class _Prep:
    """One item after validation: where its test is."""

    def __init__(self, index, abs_test, function, chain, extras):
        self.index, self.abs_test, self.function = index, abs_test, function
        self.chain, self.extras = tuple(chain), list(extras)
        self.test_dir = abs_test.parent


def _prepare(ctx, index, raw):
    if not isinstance(raw, dict):
        raise _Done("unknown", "the request to measure this test is malformed (it is not a mapping)")
    test_rel, function = raw.get("test_rel"), raw.get("function")
    if not isinstance(test_rel, str) or not test_rel.strip():
        raise _Done("unknown", "the request to measure this test is malformed (no test file)")
    if not isinstance(function, str) or not function.strip():
        raise _Done("unknown", "the request to measure this test is malformed (no function name)")
    chain = raw.get("class_chain") or ()
    if isinstance(chain, str) or not all(isinstance(c, str) for c in chain):
        raise _Done("unknown", "the request to measure this test is malformed (the class chain)")
    extras = raw.get("extra_files") or ()
    if isinstance(extras, str) or not all(isinstance(e, (str, Path)) for e in extras):
        raise _Done("unknown", "the request to measure this test is malformed (the extra files)")
    given = Path(os.path.abspath(os.path.join(str(ctx.project), test_rel)))
    shown = ctx.rel_to(ctx.project_real, given) or given.as_posix()
    if not ctx.isfile(given):
        raise _Done("unknown", f"the test file {shown} does not exist now, so it cannot be measured")
    if given.suffix.lower() != ".py":
        raise _Done("unknown", WORDS_ROW_NOT_MEASURABLE)
    if os.path.islink(given):       # before the real path is taken: that would follow the link
        raise _Done("unknown", words_symlink(shown))
    return _Prep(index, Path(ctx.real(given)), function, chain,
                 [Path(ctx.real(os.path.join(str(ctx.project), str(e)))) for e in extras])


# --- the base of one repository -----------------------------------------------------------------
class _Base:
    def __init__(self, ctx, top):
        self.ctx, self.top = ctx, top
        if ctx.s0 is not None:
            self.kind, (self.sha, self.dirty) = "s0", ctx.s0
        else:
            code, out = _git(top, ["rev-parse", "HEAD"])
            head = out.decode("utf-8", errors="replace").strip()
            if code != 0 or not _OID.match(head):
                raise _Done("unknown", words_no_git("git has no commit to read here"))
            self.kind, self.sha, self.dirty = "head_now", head.lower(), {}
        code, out = _git(top, ["ls-tree", "-r", "-z", "--full-tree", self.sha])
        if code != 0:
            raise _Done("unknown", words_base_unreadable(self.kind, self.sha), self.kind, self.sha)
        self.listing = {}
        for entry in out.split(b"\0"):
            meta, _, name = entry.partition(b"\t")
            fields = meta.decode("ascii", errors="replace").split(" ")
            if len(fields) == 3 and name:
                path = name.decode("utf-8", errors="surrogateescape")
                self.listing[_nc(path)] = (path, fields[0], fields[1], fields[2])
        self.folder = ctx.new_mirror_dir()
        self.state = {}           # nc(rel) -> "ok" | "absent" | "dirty_changed" | "untracked_at_s0" | "cannot_rebuild"
        self.lost = []            # dirty at S0, in the base, deleted since: the S0 bytes are gone

    def label(self):
        return _label(self.kind, self.sha)

    def mirror_path(self, rel):
        return os.path.join(self.folder, *rel.split("/"))

    def has(self, rel):
        """Is there a file at `rel` in the mirror? Asked once per path."""
        return self.ctx.isfile(self.mirror_path(rel))

    def read(self, rel):
        """The mirror's bytes of `rel`, or None."""
        return self.ctx.read(self.mirror_path(rel))

    def ignored(self, rels):
        """The subset of `rels` git ignores. A failed question raises: "cannot tell" is never
        "not ignored"."""
        if not rels:
            return set()
        payload = b"".join(r.encode("utf-8", errors="surrogateescape") + b"\0" for r in rels)
        code, out = _git(self.top, ["check-ignore", "--stdin", "-z"], stdin=payload)
        if code not in (0, 1):
            raise _Done("unknown", "git could not say whether the test file is ignored, so its "
                        "state before the story is unknown", self.kind, self.sha)
        return {_nc(p.decode("utf-8", errors="surrogateescape")) for p in out.split(b"\0") if p}

    def deleted_since(self, scope_prefix):
        """Python and configuration files the base has under the project and the tree no longer
        has: `(clean, lost)`. A mirror that held only what exists now could never see one."""
        clean, lost = [], []
        # ONE git question, not a stat per file of the base: here a stat costs about a millisecond.
        # `diff <commit>` compares the commit with the working tree, so a deletion that was
        # committed mid-story is listed too.
        args = ["diff", "--name-only", "--diff-filter=D", "-z", self.sha, "--"]
        if scope_prefix:
            args.append(":(literal)" + scope_prefix)
        code, out = _git(self.top, args)
        if code != 0:
            raise _Done("unknown", "git could not list the files deleted since "
                        f"{_label(self.kind, self.sha)}, so the test cannot be compared with it",
                        self.kind, self.sha)
        for raw in out.split(b"\0"):
            path = raw.decode("utf-8", errors="surrogateescape")
            key = _nc(path)
            name = path.rsplit("/", 1)[-1]
            entry = self.listing.get(key)
            if not path or entry is None or entry[2] != "blob":
                continue
            if not (name.endswith(".py") or name in CONFIG_NAMES):
                continue
            if self.kind == "s0" and key in self.dirty:
                if self.dirty[key]:          # modified at S0, gone now: S0's bytes are unrecoverable
                    lost.append(path)
                continue                     # deleted at S0 and still deleted: absent IS the S0 state
            clean.append(path)
        return clean, lost

    def fetch(self, rels):
        """Write the base's version of every path in `rels` into the mirror, from ONE
        `cat-file --batch` process; decide the state of each (R2.4, R2.5)."""
        want = []
        for rel in sorted(rels):
            key = _nc(rel)
            entry = self.listing.get(key)
            work = os.path.join(self.top, *rel.split("/"))
            if self.kind == "s0" and key in self.dirty:
                current = _sha256_file(work)
                if current != self.dirty[key]:
                    self.state[key] = "dirty_changed"
                elif entry is None:
                    self.state[key] = "untracked_at_s0" if current else "absent"
                elif not current:
                    self.state[key] = "absent"        # deleted at S0 and still deleted
                else:
                    self.state[key] = self._copy(work, rel)
                continue
            if entry is None:
                self.state[key] = "absent"
            elif entry[1] not in ("100644", "100755") or entry[2] != "blob":
                self.state[key] = "cannot_rebuild"
            else:
                want.append((rel, entry))
        if not want:
            return
        # RAW blobs, not `--filters`: measured with git 2.45, `cat-file --batch --filters` reports the
        # blob's size in its header but writes the FILTERED bytes (LF -> CRLF under autocrlf), so
        # the stream cannot be split by the header. Nothing below needs the checkout's bytes: the
        # function measure reads with universal newlines, the configuration files are compared
        # newline-normalised, and a file that was dirty at S0 is taken from the working tree.
        payload = b"".join(f"{e[3]}\n".encode("ascii") for _r, e in want)
        code, out = _git(self.top, ["cat-file", "--batch"], stdin=payload)
        if code != 0:
            raise _Done("unknown", "git could not read the files of the base, so the test cannot be "
                        "compared with it", self.kind, self.sha)
        try:
            blobs = _split_batch(out, len(want))
        except ValueError:
            raise _Done("unknown", "git could not read the files of the base, so the test cannot be "
                        "compared with it", self.kind, self.sha)
        for (rel, _entry), data in zip(want, blobs):
            key = _nc(rel)
            if data is None:
                self.state[key] = "cannot_rebuild"
                continue
            try:
                target = self.mirror_path(rel)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as stream:
                    stream.write(data)
                self.state[key] = "ok"
            except (OSError, ValueError):
                self.state[key] = "cannot_rebuild"

    def _copy(self, work, rel):
        """A file that was uncommitted at S0 and is byte-for-byte the same now: its S0 bytes ARE
        the working tree's."""
        try:
            target = self.mirror_path(rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(work, target)
            return "ok"
        except (OSError, ValueError):
            return "cannot_rebuild"


# --- the now side of one item -------------------------------------------------------------------
class _Pend:
    pass


def _now_side(ctx, fp, base, prep, cache_now):
    """Measure the working tree (R2.2) and list the measured set: every file function_sha parsed,
    the conftests up to the project root, the `__init__` chain candidates, the pytest
    configuration candidates and the extra files - each as a path relative to the repository top."""
    top = base.top
    test_top = ctx.rel_to(top, prep.abs_test)
    if not test_top:
        raise _Done("unknown", words_outside(prep.abs_test.as_posix()), base.kind, base.sha)
    info = _dir_info(ctx, top, prep.test_dir)
    extras = [p for p in prep.extras if _nc(p) not in info.helper_keys]
    helper_paths = info.helpers + extras
    view = _View(cache_now)
    now = fp.function_sha(str(prep.abs_test), prep.function, prep.chain,
                          [str(p) for p in helper_paths if ctx.isfile(p)], view)
    touched = list(view.touched)

    pend = _Pend()
    pend.prep, pend.now, pend.test_top, pend.info = prep, now, test_top, info
    pend.order, pend.now_abs, seen = [], {}, set()     # the order they are named to a person

    def add(path, required=False):
        rel = ctx.rel_to(top, path)
        if rel is None:
            if required:
                raise _Done("unknown", words_outside(Path(path).as_posix()), base.kind, base.sha)
            return None
        key = _nc(rel)
        if key not in seen:
            seen.add(key)
            pend.order.append(rel)
            pend.now_abs[key] = str(path)
        return rel

    add(prep.abs_test, required=True)
    for key in touched:
        add(key, required=True)
    pend.extra_rels = []
    for path in extras:
        rel = add(path, required=ctx.isfile(path))
        if rel is not None:
            pend.extra_rels.append(rel)
    for rel, path in info.candidates:
        add(path)
    pend.measured_on = {}
    for key in touched:
        module = cache_now.get(key)
        rel = ctx.rel_to(ctx.project_real, key)
        pend.measured_on[rel if rel is not None else Path(key).as_posix()] = (
            module.bytes_sha if module is not None else "")
    for path, name in info.config_files:
        if ctx.isfile(path) and _carries_pytest(name, ctx.read(path) or b""):
            rel = ctx.rel_to(ctx.project_real, path)
            pend.measured_on[rel if rel is not None else Path(path).as_posix()] = (
                _sha256_file(path))
    pend.plugins = any("pytest_plugins" in getattr(cache_now[k], "text", "") for k in touched
                       if k in cache_now)
    if now.get("scope") != "function" or not now.get("sha") or not now.get("code_sha"):
        raise _Done("unknown", WORDS_ROW_NOT_MEASURABLE, base.kind, base.sha, pend.measured_on)
    return pend


class _DirInfo:
    """What is true of one test FOLDER, for every item that lives in it: which conftests, `__init__`
    files and pytest configuration files could take part, as paths in the working tree and in the
    repository. Worked out once per folder."""


def _dir_info(ctx, top, test_dir):
    key = (str(test_dir), top)
    if key in ctx.dirs:
        return ctx.dirs[key]
    info = _DirInfo()
    under_project = ctx.under(test_dir, ctx.project_real)
    boundary = ctx.project_real if under_project else top
    dirs, cur = [], Path(test_dir)
    while True:                       # the test's folder up to the repository top
        dirs.append(cur)
        if _nc(ctx.real(cur)) == _nc(top) or cur.parent == cur:
            break
        cur = cur.parent
    bound_at = next((i for i, d in enumerate(dirs) if _nc(ctx.real(d)) == _nc(boundary)),
                    len(dirs) - 1)
    up_dirs = dirs[:bound_at + 1]     # ... up to the PROJECT root: the conftests and the configuration
    run_cwd, _how = resolve_run_cwd(ctx.project, ctx.rel_to(ctx.project_real, test_dir) or "",
                                    ctx.run_cwd, ctx.config())   # a profile's root is a folder
    run_cwd = Path(ctx.real(run_cwd))
    chain = []
    if not ctx.under(run_cwd, boundary):
        # the run's own chain can only reach beyond the project root when the run starts above it;
        # inside the project the up-chain below already holds every conftest it could list
        try:
            from execution_request import _conftest_chain
            chain = [Path(p) for p in _conftest_chain([Path(test_dir) / "x.py"], run_cwd)]
        except Exception:
            chain = []
    info.helpers, info.helper_keys = [], set()
    for path in [d / "conftest.py" for d in up_dirs] + chain:
        if _nc(path) not in info.helper_keys:
            info.helper_keys.add(_nc(path))
            info.helpers.append(path)
    config_dirs = list(up_dirs)
    if ctx.under(run_cwd, boundary):
        walk = run_cwd
        while _nc(ctx.real(walk)) != _nc(boundary) and walk.parent != walk:
            if _nc(ctx.real(walk)) not in {_nc(ctx.real(x)) for x in config_dirs}:
                config_dirs.append(walk)
            walk = walk.parent
    info.config_files = [(d / name, name) for d in config_dirs for name in CONFIG_NAMES]

    def located(paths):               # [(repository-relative path, path in the working tree)]
        return [(rel, p) for rel, p in ((ctx.rel_to(top, p), p) for p in paths) if rel is not None]

    helper_c = located(info.helpers)
    config_c = located([p for p, _n in info.config_files])
    info.candidates = helper_c + located([d / "__init__.py" for d in dirs]) + config_c
    info.helper_rels = [rel for rel, _p in helper_c]
    info.config_c = config_c
    info.config_diff = None           # worked out once, after the base is mirrored
    ctx.dirs[key] = info
    return info


# --- the comparison -----------------------------------------------------------------------------
def _first_difference(ctx, base, pend):
    """The first file of the measured set whose bytes differ from the base's in more than
    comments, blank lines and case markers - the test's own file first."""
    from diff_scope import executable_sha
    for rel in pend.order:
        here, there = _read(pend.now_abs[_nc(rel)]), _read(base.mirror_path(rel))
        if here is None and there is None:
            continue
        if here is None or there is None:
            return rel
        if _norm_bytes(here) == _norm_bytes(there):
            continue
        if rel.endswith(".py"):
            try:
                a, b = here.decode("utf-8"), there.decode("utf-8")
                sha = executable_sha(a, rel)
                if sha and sha == executable_sha(b, rel):
                    continue
            except UnicodeDecodeError:
                pass
        return rel
    return pend.test_top


def _config_difference(ctx, base, info):
    """The first pytest configuration file of this folder's chain that differs from the base's
    ("" when none does): a file that carries configuration on either side, absent on one, or
    different. Worked out once per folder."""
    if info.config_diff is None:
        info.config_diff = ""
        for rel, path in info.config_c:
            here, there = ctx.read(path), base.read(rel)
            if here is None and there is None:
                continue
            name = rel.rsplit("/", 1)[-1]
            if not any(d is not None and _carries_pytest(name, d) for d in (here, there)):
                continue
            if here is None or there is None or _norm_bytes(here) != _norm_bytes(there):
                info.config_diff = rel
                break
    return info.config_diff


def _compare(ctx, fp, base, pend, cache_base):
    prep, now = pend.prep, pend.now
    shown = lambda rel: ctx.rel_to(ctx.project_real, os.path.join(base.top, *rel.split("/"))) or rel
    measured = pend.measured_on
    # R2.3: a test file the base did not have is NEW
    if _nc(pend.test_top) not in base.listing:
        raise _Done("new", words_test_file_new(base.kind, base.sha), base.kind, base.sha, measured)
    # R2.4, BEFORE any equality can be claimed: what the record says of each file
    for rel in pend.order:
        state = base.state.get(_nc(rel))
        if state == "dirty_changed":
            raise _Done("changed", words_dirty_changed(shown(rel)), base.kind, base.sha, measured)
        if state == "untracked_at_s0":
            raise _Done("changed", words_untracked_at_s0(shown(rel), base.kind, base.sha),
                        base.kind, base.sha, measured)
        if state == "cannot_rebuild":
            raise _Done("unknown", words_cannot_rebuild(shown(rel)), base.kind, base.sha, measured)
    if base.lost:
        raise _Done("changed", words_lost(shown(base.lost[0])), base.kind, base.sha, measured)
    config = _config_difference(ctx, base, pend.info)
    if config:
        raise _Done("changed", words_config_changed(shown(config), base.kind, base.sha),
                    base.kind, base.sha, measured)
    # R2.5: the same measurement over the mirror, the helpers in the same order
    mirror_test = base.mirror_path(pend.test_top)
    base_helpers = [base.mirror_path(rel) for rel in pend.info.helper_rels + pend.extra_rels
                    if base.has(rel)]
    then = fp.function_sha(mirror_test, prep.function, prep.chain, base_helpers, cache_base)
    module = cache_base.get(str(Path(mirror_test)))
    if module is None or not module.parsed:
        raise _Done("unknown", words_base_not_python(base.kind, base.sha), base.kind, base.sha, measured)
    if then.get("scope") != "function":
        raise _Done("new", words_function_new(base.kind, base.sha), base.kind, base.sha, measured)
    if not then.get("sha"):
        raise _Done("changed", words_base_unmeasurable(base.kind, base.sha), base.kind, base.sha,
                    measured)
    # R2.6
    same = ((now.get("code_sha") and now.get("code_sha") == then.get("code_sha"))
            or (now.get("sha") and now.get("sha") == then.get("sha")))
    if not same:
        name = shown(_first_difference(ctx, base, pend))
        raise _Done("changed", words_changed(base.kind, base.sha, name), base.kind, base.sha, measured)
    # R2.7 / V2
    if base.kind != "s0":
        raise _Done("unknown", WORDS_HEAD_NOW_EQUAL, base.kind, base.sha, measured)
    raise _Done("unchanged", words_unchanged(base.kind, base.sha, pend.plugins), base.kind,
                base.sha, measured)


# --- the driver ---------------------------------------------------------------------------------
def _measure_group(ctx, fp, top, preps, results):
    base = _Base(ctx, top)
    ignored = base.ignored([r for r in (ctx.rel_to(top, p.abs_test) for p in preps) if r])
    pending, need = [], {}
    cache_base = {}
    for prep in preps:
        try:
            rel = ctx.rel_to(top, prep.abs_test)
            if rel is None:
                raise _Done("unknown", words_outside(prep.abs_test.as_posix()), base.kind, base.sha)
            if _nc(rel) in ignored:
                raise _Done("unknown", WORDS_IGNORED, base.kind, base.sha)
            pend = _now_side(ctx, fp, base, prep, ctx.shared_now)
        except _Done as done:
            results[prep.index] = done.result()
            continue
        except Exception as exc:
            results[prep.index] = _result("unknown", words_exception(exc), base.kind, base.sha)
            continue
        pending.append(pend)
        need.update({_nc(rel): rel for rel in pend.order})
    if not pending:
        return
    scope = ctx.rel_to(top, ctx.project)
    clean, base.lost = base.deleted_since(scope if scope is not None else "")
    need.update({_nc(p): p for p in clean})
    base.fetch(list(need.values()))
    for pend in pending:
        try:
            _compare(ctx, fp, base, pend, cache_base)
        except _Done as done:
            results[pend.prep.index] = done.result()
        except Exception as exc:
            results[pend.prep.index] = _result("unknown", words_exception(exc), base.kind, base.sha,
                                               pend.measured_on)


def _measure_all(ctx, fp, items, results):
    groups = {}
    for index, raw in enumerate(items):
        try:
            prep = _prepare(ctx, index, raw)
            groups.setdefault(ctx.top_of(prep.test_dir), []).append(prep)
        except _Done as done:
            results[index] = done.result()
        except Exception as exc:
            results[index] = _result("unknown", words_exception(exc))
    for top, preps in groups.items():
        try:
            _measure_group(ctx, fp, top, preps, results)
        except _Done as done:
            for prep in preps:
                if results[prep.index] is None:
                    results[prep.index] = done.result()
        except Exception as exc:
            for prep in preps:
                if results[prep.index] is None:
                    results[prep.index] = _result("unknown", words_exception(exc))


def measure_many(project_root, items, base_record=None, run_cwd=None):
    """One result per item, in order, for the functions of one `manifest_from_tests` call: ONE base
    mirror, ONE `git cat-file --batch` process and ONE parse cache per side for all of them."""
    try:
        items = list(items)
    except Exception as exc:
        return [_result("unknown", words_exception(exc))]
    if not items:
        return []
    results = [None] * len(items)
    ctx = None
    try:
        ctx = _Ctx(project_root, base_record, run_cwd)
        import execution_fingerprint as fp
        _measure_all(ctx, fp, items, results)
    except Exception as exc:
        for index, value in enumerate(results):
            if value is None:
                results[index] = _result("unknown", words_exception(exc))
    finally:
        if ctx is not None and ctx.mirror is not None:
            _remove_tree(ctx.mirror)
    return [r if r is not None else _result("unknown", "measuring this test produced no answer")
            for r in results]


def measure(project_root, test_rel, function, class_chain=(), extra_files=(), base_record=None,
            run_cwd=None):
    """`measure_many` with one item."""
    return measure_many(project_root, [{"test_rel": test_rel, "function": function,
                                        "class_chain": class_chain, "extra_files": extra_files}],
                        base_record=base_record, run_cwd=run_cwd)[0]
