"""Check the pytest node ids a run is about to name against what pytest really collects.

CLI: node_ids.py --cwd DIR --ids ID [ID ...] -- <test command without node ids>
     node_ids.py --selftest

TP1-15045, job 071bcb794f4e10520240: a red probe was launched with
`...::test_visual_diff_markers_follow_the_selected_pair_not_a_stale_pair[buffer-R3-vs-selected-R1]`.
pytest-playwright prepends the browser to every parameter id, so the collected id was
`[chromium-buffer-R3-vs-selected-R1]`; pytest exited 4 after 11 seconds with `ERROR: not
found`, nothing ran, the sandbox was burned, and two critic dispatches were spent on "a
tooling blocker". How a project's plugins spell a parameter id is the factory's bookkeeping,
not a role's: an id with exactly one obvious real spelling is resolved here and the run goes
on; only an id with no such spelling stops the launch, and then with the nearest real ids in
the message instead of an exit code.

One broken module does not stop the collect (RH1-3): a caller that hands over the runner's `collect_forms` row
(`launch_check.runner_row`) gets the collect run past files that fail to import, and `collect_verdict` reads the
outcome once for everyone - complete, partial (the healthy files' ids plus the broken files by name), none selected,
all broken, stopped, unread. The error direction is fixed: an id of a file that did not collect is "not verified",
never "missing", and an outcome that does not add up is never "partial".

Standard library only. Nothing here imports the rest of the factory, so the runner and the
sandbox can import it lazily and a half-installed tree degrades to "feature absent".
"""
import argparse
import difflib
import functools
import json
import os
import re
import shutil
import subprocess
import sys

# pytest-playwright's `browser_name` parametrization; the token leads the id because the
# plugin's fixture is resolved before the test's own parameters.
BROWSER_TOKENS = ("chromium", "firefox", "webkit")
HEAD_PREFIXES = ("ERROR", "E   ", "usage:", "ImportError", "ModuleNotFoundError")
HEAD_MAX_LINES = 25
HEAD_MAX_BYTES = 2500
NEAREST = 3

# pytest's --collect-only at verbosity 0 (net of every -v/-q on the command line, addopts
# included) prints a nested tree of these tags instead of flat node ids — no `::` in a
# `<Function ...>` line, so parse_collected finds nothing and every asked id would read as
# missing. A project's own `addopts = -v` cancels the `-q` we send (net verbosity 0) without
# raising an error, so this is silent unless checked for. First live run of 0.7.8: every id
# came back node_id_mismatch on a project whose pytest.ini said exactly `addopts = -v`.
TREE_TAG_RE = re.compile(r"^\s*<(Module|Package|Dir|UnitTestCase)\b", re.M)


BROKEN_HEAD_MAX = 180


class CollectError(Exception):
    """Collection did not give a complete list, so what can be said about an id is limited.

    `kind` says HOW, for a caller that answers each differently (the gate rehearsal asks a person about a
    runner that is not there and about a collect that never finished, SC1-12): `not_started` (the program
    is not there, or has no execute right: FileNotFoundError / PermissionError), `launch_failed` (the launch
    failed for any other OS reason: the factory's own), `timeout` (the tree was killed at the limit), `unread` (pytest counted tests the
    parser read none of, or the runner ended with a partial-collect code and its count does not add up),
    `exit` (a code other than the runner's ok codes, or every test file failed), `stopped` (the runner cut the
    collect short, e.g. `-x`: the list is incomplete and nothing says where), `partial` (RH1-3: the runner
    went on past files that failed to import; `ids` are the tests of the healthy files, `broken` the files that
    were left out, `{"path", "head"}` each), `no_command` (nothing to run). The default `""` keeps every older
    `CollectError(message)` / `CollectError(message, head)` as it was; a caller meeting a kind it does not know
    treats it as unavailable, never as a pass. Only `partial` carries ids, and only for the files that
    gave some: an id of any other file is "not verified", never "missing" (I1)."""

    def __init__(self, message: str, head: str = "", kind: str = "", ids=None, broken=None):
        super().__init__(message)
        self.message = message
        self.head = head or message
        self.kind = kind
        self.ids = list(ids or [])
        self.broken = list(broken or [])


# --- the command ---------------------------------------------------------------------------

_PYTEST_NAMES = ("pytest", "py.test")
_RUNNER_SUFFIXES = (".exe", ".cmd", ".bat")


def _token_name(token) -> str:
    """A command token as a program name: quotes off both ends, the directory cut at `\\` and `/`, lower case, no
    Windows launcher suffix."""
    name = re.split(r"[\\/]", str(token).strip("\"'"))[-1].lower()
    for suffix in _RUNNER_SUFFIXES:
        if name.endswith(suffix):
            return name[:-len(suffix)]
    return name


def _left_is_other_runner(argv, index: int) -> bool:
    """Is a test runner other than pytest already started to the LEFT of `argv[index]`? Then a `pytest` token there is
    an argument of that runner (`npx <runner> test tests/pytest`), not the program. Every prefix is asked, not one
    slice: `npx <runner> test --list tests/pytest` is no form as a whole, and the prefix `npx <runner> test` is.
    `hooklib` is loaded here, not at the top (this module is stdlib-only); one that cannot be loaded, or that fails,
    answers False: counted as before (the error direction is a visible break on `--junitxml`, never a silent pass)."""
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.append(here)  # last: never shadows what the caller already resolved
        import hooklib
        for end in range(1, index + 1):
            form = hooklib.direct_test_form([str(a) for a in argv[:end]])
            if form and form.get("id") != "pytest":
                return True
    except Exception:
        return False
    return False


def is_pytest(argv) -> bool:
    """The ONE reading of "this command is pytest" (EP1-1): the program `pytest` / `py.test` (any directory, quotes,
    case, `.exe` / `.cmd` / `.bat`) or `-m pytest`, anywhere in the command, unless another runner starts to its left.
    Empty or absent argv is not pytest."""
    tokens = [str(a) for a in argv or []]
    names = [_token_name(a) for a in tokens]
    for index, name in enumerate(names):
        candidate = name in _PYTEST_NAMES or (
            name == "-m" and index + 1 < len(names) and names[index + 1] in _PYTEST_NAMES)
        if candidate and not _left_is_other_runner(tokens, index):
            return True
    return False


def _collect_argv(argv, asked=()) -> list:
    """The test command made safe for a collect: no report file, no workers, no node ids.

    A report path belongs to the run that owns the evidence directory — a collect writing
    `--junitxml` there would overwrite or pre-create the run's own report. Workers only slow
    a collect down. A node id left in the command would make pytest fail on exactly the
    spelling this module exists to check.
    """
    asked = set(asked)
    out, skip = [], False
    for arg in [str(a) for a in argv]:
        if skip:
            skip = False
            continue
        if arg in asked or "{report_path}" in arg:
            continue
        if arg in ("--junitxml", "--junit-xml", "-n", "--numprocesses"):
            skip = True
            continue
        if arg.startswith(("--junitxml=", "--junit-xml=", "--numprocesses=")) \
                or re.fullmatch(r"-n(\d+|auto|logical)", arg):
            continue
        out.append(arg)
    return out


def _files(asked) -> list:
    files = []
    for node in asked:
        path = str(node).split("::", 1)[0]
        if path and path not in files:
            files.append(path)
    return files


def _head(text: str) -> str:
    lines = [ln.rstrip() for ln in text.splitlines() if ln.startswith(HEAD_PREFIXES)]
    if not lines:
        lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()][-10:]
    head = "\n".join(lines[:HEAD_MAX_LINES])
    return head.encode("utf-8")[:HEAD_MAX_BYTES].decode("utf-8", errors="ignore")


def kill_tree(proc) -> None:
    """Kill `proc` and what runs under it.

    On Windows proc.kill() takes only the direct child (poetry, npm.cmd) and leaves its children holding
    the pipe - the same field lesson as run_suite.kill_tree, kept in this stdlib-only module so the sandbox,
    the scheduler and the collect share ONE copy (t-958 F-4). On POSIX the whole process group goes, which
    is safe only for a child started with `start_new_session` (`run_bounded` does); a child still in the
    caller's own group is killed alone, never the factory's group with it."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, timeout=30)
        else:
            import signal
            group = os.getpgid(proc.pid)
            if group != os.getpgid(0):
                os.killpg(group, signal.SIGKILL)
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass


class BoundedRunError(Exception):
    """A bounded run that did not finish as a run. `kind` is `not_started` (the program could not be
    launched) or `timeout` (the tree was killed after the limit); the message says which and why."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def run_bounded(argv, cwd, env, timeout_s, grace_s: int = 10, merge_stderr: bool = True):
    """(exit code, raw output bytes) of a command run with a wall-clock limit - the one launcher of the factory
    for a command whose children may outlive it (a collect, a dependency install). With `merge_stderr=False`
    the result is `(exit code, raw stdout, raw stderr)`: the two streams are read apart (EP1-35, B-7).

    stdin is closed (a child must never wait on the factory's terminal), stdout and stderr are one stream, the
    child leads its own process group on POSIX, and the output is read to the end however large it is (the
    pipe is drained, the child is never stopped by a full buffer). After `timeout_s` the whole tree is killed
    and the pipe read for at most `grace_s` more - a grandchild holding it never extends the wait beyond that;
    on Windows `subprocess.run` reads it with no limit, which is why this is not `subprocess.run`."""
    kwargs = {"start_new_session": True} if os.name != "nt" else {}
    try:
        proc = subprocess.Popen([str(a) for a in argv], cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT if merge_stderr else subprocess.PIPE, **kwargs)
    except OSError as exc:
        raise BoundedRunError("not_started", str(exc)) from exc
    try:
        raw, raw_err = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        try:
            proc.communicate(timeout=grace_s)
        except Exception:
            pass
        raise BoundedRunError("timeout", f"timed out after {timeout_s}s") from None
    return (proc.returncode, raw) if merge_stderr else (proc.returncode, raw, raw_err)


def _project_env():
    """`project_env` imported at call time (this module is standard library only), or None."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import project_env
        return project_env
    except Exception:                                    # pragma: no cover - partial install
        return None


def run_captured(argv, cwd, env, timeout_s) -> "subprocess.CompletedProcess":
    """`subprocess.run(capture_output, text, timeout)` with the launch of the factory (EP1-35, B-7): the head is
    resolved and a `.cmd` wrapper's unsafe argument refused (`project_env.checked_launch`, `CmdUnsafe` is an
    OSError), the tree is killed at the limit (`run_bounded`), the wait after it is bounded. `env=None` is the
    process environment (`launch_argv` finds nothing in an empty one). `FileNotFoundError` and other OSError
    come out as they would from `subprocess.run`; a timeout is `subprocess.TimeoutExpired`."""
    env = dict(os.environ) if env is None else env
    PE = _project_env()
    launch = PE.checked_launch(argv, env) if PE else [str(a) for a in argv]
    try:
        code, raw_out, raw_err = run_bounded(launch, cwd, env, timeout_s, merge_stderr=False)
    except BoundedRunError as exc:
        if exc.kind == "not_started" and exc.__cause__ is not None:
            raise exc.__cause__ from None
        raise subprocess.TimeoutExpired(argv, timeout_s) from None

    def text(raw):
        return (raw or b"").decode("utf-8", errors="replace").replace("\r\n", "\n")
    return subprocess.CompletedProcess(argv, code, text(raw_out), text(raw_err))


def _run(command, cwd, timeout_s):
    env = dict(os.environ)
    # A collect imports every test module; without this it litters the author's tree (or the
    # sandbox whose hashes are compared) with __pycache__ and pytest's rewritten .pyc files.
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    PE = _project_env()
    if PE is None:
        command = [shutil.which(command[0]) or command[0], *command[1:]]
    else:
        try:
            command = PE.checked_launch(command, env)
        except PE.CmdUnsafe as exc:
            raise CollectError(str(exc), kind="launch_failed") from exc
    try:
        code, raw = run_bounded(command, cwd, env, timeout_s)
    except BoundedRunError as exc:
        if exc.kind == "not_started":
            # `not_started` means "there is no runner" (the gate asks the person about a missing executor, FR-3): the
            # launcher's absence or its missing execute right, as `shutil.which` and S5's executor probe read it. Any
            # other OSError (`[WinError 193]`, ENOEXEC, E2BIG) is the factory's own trouble: `launch_failed`.
            gone = isinstance(exc.__cause__, (FileNotFoundError, PermissionError))
            raise CollectError(f"the collect command could not be started: {exc}",
                               kind="not_started" if gone else "launch_failed") from exc
        raise CollectError(f"collect {exc}", kind=exc.kind) from None
    # Windows children write CRLF; a `$` in a multi-line regex does not match before `\r`.
    return code, "\n".join(raw.decode("utf-8", errors="replace").splitlines())


def parse_collected(text: str) -> list:
    """Node ids out of `--collect-only -q` output; stops at the first `====` section AFTER the ids.

    A `=` line before any id is a banner a conftest or a plugin printed (`=== Harness v2 ===`), not a
    pytest section: it is skipped. Until EP1-9 it ended the parse, and a project whose harness greets
    the run was told its API tests did not exist."""
    ids = []
    for line in text.splitlines():
        line = line.rstrip()
        if line.startswith("="):
            if ids:
                break
            continue
        if "::" not in line or line[:1].isspace() or line.startswith(("ERROR", "FAILED", "<")):
            continue
        if line.split("::", 1)[0].replace("\\", "/").endswith(".py") and line not in ids:
            ids.append(line)
    return ids


COUNT_RE = re.compile(r"^=*\s*(\d+)(?:/\d+)? tests? collected", re.M)


def _partial_exits(form) -> tuple:
    """The runner row's `partial_exits` as a tuple of ints; () for no form, or a row that states none."""
    exits = form.get("partial_exits") if isinstance(form, dict) else None
    return tuple(e for e in exits if isinstance(e, int)) if isinstance(exits, list) else ()


@functools.lru_cache(maxsize=32)
def _rx(pattern: str):
    return re.compile(pattern, re.M)


def _form_rx(form, key: str):
    """The compiled regex a runner row names under `key`, or None (a row without the key, or a pattern that does
    not compile: the runner then states no such fact, which `collect_verdict` reads as `unread`)."""
    pattern = form.get(key) if isinstance(form, dict) else None
    if not isinstance(pattern, str) or not pattern:
        return None
    try:
        return _rx(pattern)
    except re.error:
        return None


SECTION_RE = re.compile(r"^_+ ERROR collecting (?P<path>\S.*?) _+$", re.M)


def _section_head(text: str, path: str) -> str:
    """The first `E   ` line of the failure section of `path` (or of a file under it), else ''. A broken module's
    summary line carries no ` - cause`, the cause is only in its section (E3-17)."""
    wanted = path.lower()
    for match in SECTION_RE.finditer(text):
        where = _norm_path(match.group("path")).lower()
        # a broken class node (`file.py::TestX`) has its section under the FILE (B2)
        if where != wanted and not where.startswith(wanted.rstrip("/") + "/") \
                and not ("::" in wanted and where == wanted.partition("::")[0]):
            continue
        for line in text[match.end():].splitlines()[1:]:
            if line.startswith("_") and SECTION_RE.match(line):
                break
            if line.startswith("E   "):
                return line[4:].strip()
    return ""


def broken_files(text: str, form) -> list:
    """`[{"path", "head"}]` - the files or folders the runner says it could not collect, by the row's `broken_line`:
    forward slashes, each path once, `head` (<= BROKEN_HEAD_MAX) the cause on the line, else the section's first
    `E   ` line, else ''. [] for a row with no `broken_line`."""
    rx = _form_rx(form, "broken_line")
    rows, seen = [], set()
    for match in (rx.finditer(text) if rx else ()):
        path = _norm_path(match.group("path"))
        if not path or path in seen:
            continue
        seen.add(path)
        head = (match.groupdict().get("cause") or "").strip() or _section_head(text, path)
        rows.append({"path": path, "head": " ".join(head.split())[:BROKEN_HEAD_MAX]})
    return rows


def collect_verdict(code: int, text: str, form=None) -> dict:
    """`{"kind", "ids", "broken", "selected", "total", "errors"}` - the ONE reading of a collect's outcome (RH1-3,
    AR-13/AR-15: the gate, the onboarding probe and S5 all read it here). `form` is the runner's `collect_forms`
    row of `references/launch-causes.json` (`launch_check.runner_row`); this module is standard library only, so
    the caller hands it over.

    `kind`: `complete` (a code the runner calls ok, and the output is readable), `partial` (the runner went on past
    broken files: `ids` are the healthy files' tests, `broken` the files left out), `none_selected` (a filter
    selected nothing while K files were broken), `all_broken` (the runner counted no test at all, K files were
    broken - never "there are no tests", I3), `stopped` (the collect was cut short, e.g. `-x`), `unread` (the output
    does not add up: no count line, a count that disagrees with the broken files named, tests counted but none
    read - never `partial`, I2), `failed` (any other code). No `form`, or a row with no `partial_exits`: only
    `complete`, `unread` or `failed`, as before. A partial exit is a PARTIAL only when the run finished, the count
    line was read, its error count equals the number of broken files named, and no stop line is there."""
    ids = parse_collected(text)
    out = {"kind": "failed", "ids": ids, "broken": [], "selected": None, "total": None, "errors": None}
    ok = form.get("ok_exits") if isinstance(form, dict) and isinstance(form.get("ok_exits"), list) else [0, 5]
    if code not in _partial_exits(form):
        if code in ok:
            unread = unread_count(code, text)
            out.update(kind="unread" if unread else "complete", selected=unread or None)
        return out
    out["broken"] = broken_files(text, form)
    stopped = _form_rx(form, "stopped_line")
    if stopped is not None and stopped.search(text):
        out["kind"] = "stopped"
        return out
    count = _form_rx(form, "count_line")
    matches = list(count.finditer(text)) if count else []
    if not matches:
        out["kind"] = "unread"
        return out
    groups = matches[-1].groupdict()
    selected = int(groups["selected"]) if groups.get("selected") else 0     # `no tests collected` has no number
    total = int(groups["total"]) if groups.get("total") else None
    if total is None and groups.get("deselected"):
        # pytest prints `no tests collected (5 deselected), 1 error` - never `0/5` - when a filter took every healthy
        # test: what it counted is what it selected plus what it deselected (B1, I3).
        total = selected + int(groups["deselected"])
    errors = int(groups["errors"]) if groups.get("errors") else 0
    out.update(selected=selected, total=total, errors=errors, kind="unread")
    if errors != len(out["broken"]) or not out["broken"]:
        return out                      # a banner line `ERROR ...`, a path pytest did not name, an exit nothing explains
    if (total if total is not None else selected) == 0:
        out["kind"] = "all_broken"
    elif selected == 0:
        out["kind"] = "none_selected"
    elif ids:
        out["kind"] = "partial"
    return out                          # tests counted, none read: still `unread`


def unread_count(code: int, text: str, form=None) -> int:
    """The ONE count verdict on a collect's output (EP1-9; used by `collect` here and by the gate's own collect).

    Returns N when the collect exited 0 (or, with the runner's `form`, with one of its `partial_exits`: the
    code a collect ends with when it went on past broken files), `parse_collected` reads no id, and pytest's own
    count line reports N > 0 tests - including the deselected form `3/4 tests collected (1 deselected)`, where
    N is the 3 that were collected. Returns 0 in every other case, including exit 0 with no count line at all (an
    empty output is still "nothing collected"). A non-zero N is an output this parser cannot read: the caller
    refuses and names N, it never reports zero tests (AR-28)."""
    if (code != 0 and code not in _partial_exits(form)) or parse_collected(text):
        return 0
    counted = COUNT_RE.search(text)
    return int(counted.group(1)) if counted else 0


def output_head(text: str) -> str:
    """The part of a collect's output a refusal shows: the error lines, else the first five lines."""
    return _head(text) or "\n".join(text.splitlines()[:5])


def collect_output(argv, cwd, timeout_s: int = 180, files=(), form=None) -> tuple:
    """`(exit code, text)` of the test command run with `--collect-only -q` over `files`, after the retries.

    The ONE launcher of a collect (SC1-12, AR-15; the gate rehearsal, S5's runner and the sandbox all read their
    node ids through it): the command made safe by `_collect_argv`, run bounded, and run AGAIN once when the
    first output is not the flat list of ids - with `-v` when the project's own `-q` made it `-qq`
    (`file.py: 3`), with `-q` when its `-v` made it the `<Module>` tree. The decisions that follow the text (the
    count verdict, the exit code) belong to the caller: `collect` below refuses on them, the gate rehearsal
    turns each into its own question. Raises `CollectError` with a `kind` when nothing could be run.

    `form` (the runner's `collect_forms` row, RH1-3): its `continue_tokens` are added to the ONE collect when the
    command lacks them (one broken file then no longer hides the rest), and the output-shape retry runs also when
    the exit is one of its `partial_exits` - a project whose `-v` makes the tree ends with exit 1 there, not 0 (B2)."""
    if not argv:
        raise CollectError("no test command to collect with", kind="no_command")
    base = _collect_argv(argv) + ["--collect-only", "-q"]
    for token in (form.get("continue_tokens") or []) if isinstance(form, dict) else []:
        if str(token) not in base:
            base.append(str(token))
    targets = [str(f) for f in files]
    code, text = _run(base + targets, cwd, timeout_s)
    ids = parse_collected(text)
    retriable = code == 0 or code in _partial_exits(form)
    if retriable and not ids and re.search(r"^\S+\.py: \d+$", text, re.M):
        # The project's own addopts already carry `-q`, ours made it `-qq`, and pytest then
        # prints `file.py: 3` instead of ids. One `-v` brings the verbosity back to `-q`.
        code, text = _run(base + ["-v"] + targets, cwd, timeout_s)
        ids = parse_collected(text)
    elif retriable and not ids and TREE_TAG_RE.search(text):
        # the opposite problem — the project's own addopts carry a `-v` that CANCELS
        # our `-q` (net verbosity 0), and pytest prints the `<Module>/<Function>` tree.
        # One more `-q` restores the net verbosity our parser expects; parsing the tree
        # itself is a bigger project (class nesting, parametrize ids) for a case one retry
        # already fixes.
        code, text = _run(base + ["-q"] + targets, cwd, timeout_s)
    return code, text


def broken_names(broken, shown: int = 5) -> str:
    """`a, b (+K more)` - the ONE builder of the names text of broken files (AR-15); the callers pass their own `shown`:
    5 for a line a person or the onboarding role reads whole, 10 in `broken_sentence` and the record's notes."""
    names = [str(row.get("path")) for row in broken]
    return ", ".join(names[:shown]) + (f" (+{len(names) - shown} more)" if len(names) > shown else "")


def broken_sentence(broken, shown: int = 10) -> str:
    """`N file(s) could not be collected: a, b (+K more)` - the ONE wording the notes of S5 and the check use; at most
    `shown` files are named, the rest is counted, the record (`collect_gaps`) keeps them all."""
    return f"{len(broken)} file(s) could not be collected: {broken_names(broken, shown)}"


def collect(argv, cwd, timeout_s: int = 180, files=(), form=None) -> list:
    """Run the test command with `--collect-only -q` over `files`; return the full node ids.

    `argv` is the test command WITHOUT node ids. Raises CollectError(message, head) when the
    collect cannot answer completely: not startable, timed out, or the runner reported a usage or collection
    error (any exit code other than its ok codes, 0 and 5 for pytest - with one broken module in the batch, the ids of
    the healthy ones would otherwise be reported as missing, which is a lie about them).

    With `form` (the runner's row, see `collect_verdict`) the collect goes on past broken files and a list comes
    back only when nothing was broken. Otherwise `CollectError`: `partial` / `none_selected` -> `kind="partial"` with
    `ids` (the healthy files' tests) and `broken`; `all_broken` -> `exit`; `stopped`; `unread`. A caller that does not
    know `partial` reads it as "not verified", exactly as it always read an `exit` (the contract of this module): the
    ids of a partial list are for `match_partial`, which never says `missing` about a file that did not collect."""
    code, text = collect_output(argv, cwd, timeout_s, files, form)
    verdict = collect_verdict(code, text, form)
    kind = verdict["kind"]
    if kind == "complete":
        return verdict["ids"]
    if kind == "unread" and code not in _partial_exits(form):
        # the runner's own count disagrees with an empty parse: the output has a shape this parser does not read.
        # A refusal that names it beats a silent "zero tests" (EP1-9, FR-41, AR-28).
        raise CollectError(f"pytest collected {verdict['selected']} test(s) but none could be parsed from its output",
                           output_head(text), kind="unread")
    if kind == "unread":
        raise CollectError(f"the collect ended with exit code {code} and its output does not add up (no readable count, "
                           f"or a count that disagrees with the {len(verdict['broken'])} broken file(s) named)",
                           output_head(text), kind="unread", broken=verdict["broken"])
    if kind in ("partial", "none_selected"):
        raise CollectError(f"{len(verdict['broken'])} file(s) could not be collected and are left out: "
                           f"{broken_names(verdict['broken'])}", _head(text), kind="partial",
                           ids=verdict["ids"], broken=verdict["broken"])
    if kind == "all_broken":
        raise CollectError(f"no test could be collected: {len(verdict['broken'])} file(s) failed: "
                           f"{broken_names(verdict['broken'])}", _head(text), kind="exit", broken=verdict["broken"])
    if kind == "stopped":
        raise CollectError("the runner stopped the collect at the first error, so the list is incomplete",
                           _head(text), kind="stopped", broken=verdict["broken"])
    raise CollectError(f"collect ended with exit code {code}", _head(text), kind="exit")


# --- matching ------------------------------------------------------------------------------

def _norm_path(path: str) -> str:
    path = str(path).replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def split_id(node: str):
    """(file, function-with-classes, params or None). `a.py::T::test_x[p-1]` ->
    ("a.py", "T::test_x", "p-1"). A parameter id may itself hold `::` or brackets, a function
    name cannot hold `[`, so the FIRST `[` after the file is where the parameters begin."""
    node = str(node).strip()
    path, _, rest = node.partition("::")
    if "[" in rest and rest.endswith("]"):
        base, _, params = rest.partition("[")
        return _norm_path(path), base, params[:-1]
    return _norm_path(path), rest, None


def _same_file(asked: str, real: str) -> int:
    """2 = the same spelling, 1 = one is a tail of the other on a directory boundary (an
    absolute sandbox prefix, or a rootdir above the cwd), 0 = different files."""
    if asked == real:
        return 2
    if os.name == "nt" and asked.lower() == real.lower():
        return 2
    a, b = asked.lower(), real.lower()
    return 1 if a.endswith("/" + b) or b.endswith("/" + a) else 0


def same_file(asked: str, real: str) -> bool:
    """Whether two spellings (either slash, a rootdir above the cwd, a `::Class` tail dropped) name the same file; an
    empty one names none."""
    a, r = _norm_path(asked).partition("::")[0], _norm_path(real).partition("::")[0]
    return bool(a and r and _same_file(a, r))


def _drop_browser(params: str) -> str:
    for token in BROWSER_TOKENS:
        if params.startswith(token + "-"):
            return params[len(token) + 1:]
    return params


def _spell(asked: str, base: str, params) -> str:
    """The real function and parameters under the file spelling the caller ASKED with: that
    path is the one valid from the caller's cwd, while a collected id is relative to pytest's
    rootdir, which may sit above it."""
    path = str(asked).strip().partition("::")[0]
    return f"{path}::{base}" + (f"[{params}]" if params is not None else "")


def _nearest(file: str, base: str, params, rows) -> list:
    def score(row):
        _, r_file, r_base, r_params = row
        same_fn = bool(_same_file(file, r_file)) and r_base == base
        same_file = bool(_same_file(file, r_file))
        # Without the browser token, or `chromium-` alone outweighs the part that differs.
        ratio = difflib.SequenceMatcher(None, f"{base}[{_drop_browser(params or '')}]",
                                        f"{r_base}[{_drop_browser(r_params or '')}]").ratio()
        return (same_fn, same_file, ratio)

    ranked = sorted(rows, key=score, reverse=True)
    return [row[0] for row in ranked[:NEAREST]]


def _judged(result: dict, ticket, stage, project_root) -> dict:
    """An id with no obvious real spelling and 2..10 nearest ids is a spelling question, and
    a spelling question has a judge (`judge_form.resolve_missing`). Imported here and not at
    the top on purpose: this module is standard library only so the runner and the sandbox can
    import it from a half-installed tree, and every failure of that import is "feature absent",
    never a launch let through. With `judge.provider: none` the result comes back untouched."""
    if not result.get("missing"):
        return result
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import judge_form
        return judge_form.resolve_missing(result, ticket=ticket, stage=stage,
                                          project_root=project_root)
    except Exception:
        return result


def match(asked, collected, *, ticket=None, stage="S5", project_root=None) -> dict:
    """{"resolved": {asked_id: real_id}, "missing": [{"asked", "nearest"}], "notes": [str]}"""
    rows = []
    for node in collected or []:
        file, base, params = split_id(node)
        rows.append((str(node).strip(), file, base, params))
    resolved, missing, notes = {}, [], []
    for asked_id in asked or []:
        asked_id = str(asked_id)
        file, base, params = split_id(asked_id)
        in_file = [r for r in rows if _same_file(file, r[1]) == 2] \
            or [r for r in rows if _same_file(file, r[1]) == 1]
        if not base:
            # A file or a directory, not a test: present when anything was collected under it.
            folder = file.lower().rstrip("/") + "/"
            under = in_file or [r for r in rows if r[1].lower().startswith(folder)]
            if under:
                resolved[asked_id] = asked_id
            else:
                missing.append({"asked": asked_id,
                                "nearest": _nearest(file, base, params, rows)})
            continue
        siblings = [r for r in in_file if r[2] == base]
        if siblings and (params is None or any(r[3] == params for r in siblings)):
            resolved[asked_id] = asked_id
            continue
        if params is not None:
            prefixed = [r for r in siblings if r[3] is not None and
                        (_drop_browser(r[3]) == params or r[3].endswith("-" + params))]
            stripped = [r for r in siblings if r[3] is not None and r[3] != params
                        and _drop_browser(params) == r[3]]
            candidates = prefixed or stripped
            if len(candidates) == 1:
                real = _spell(asked_id, base, candidates[0][3])
                resolved[asked_id] = real
                notes.append(
                    f"{asked_id} is collected as [{candidates[0][3]}], not [{params}]: a plugin "
                    "of the project (pytest-playwright prepends the browser) shapes the "
                    f"parameter id. The factory pinned the real spelling: {real}")
                continue
            if len(candidates) > 1:
                missing.append({"asked": asked_id, "nearest": [r[0] for r in candidates[:NEAREST]]})
                notes.append(f"{asked_id}: {len(candidates)} collected ids end with [{params}] "
                             "(one per browser, usually); name the one to run")
                continue
        missing.append({"asked": asked_id, "nearest": _nearest(file, base, params, rows)})
    return _judged({"resolved": resolved, "missing": missing, "notes": notes},
                   ticket, stage, project_root)


def _covers(broken_path: str, file: str) -> bool:
    """Whether `file` is the broken path itself or lies under it, compared by whole path components: a folder
    `tests/service` that failed does not cover `tests/servicenow_budget/test_a.py` (I1; the cwd-relative spelling of an
    asked path against a rootdir-relative broken path is not compared: that file simply "yielded no test")."""
    b, f = _norm_path(broken_path).lower().strip("/"), _norm_path(file).lower()
    return bool(b) and "/" + b + "/" in "/" + f.rstrip("/") + "/"


def _under_node(broken_path: str, asked_id: str) -> bool:
    """Whether `asked_id` lies under a broken NODE (`file.py::TestX`: pytest names the class when its collection fails,
    not the file): the same file, and the asked id's node path is the broken one or continues it after `::`, nested
    classes included (B2, I1). A broken file or folder (no `::`) is not a node: `_covers` reads those."""
    b_file, sep, b_rest = _norm_path(broken_path).partition("::")
    if not sep or not b_rest:
        return False
    a_file, _, a_rest = str(asked_id).strip().partition("::")
    return bool(_same_file(_norm_path(a_file), b_file)) and (a_rest == b_rest or a_rest.startswith(b_rest + "::")
                                                           or a_rest.startswith(b_rest + "["))


def match_partial(asked, ids, broken, *, ticket=None, stage="S5", project_root=None) -> dict:
    """`match` over the ids of a PARTIAL collect (`CollectError.kind == "partial"`: `ids` of the healthy files, `broken`
    the files left out). The shape of `match` plus `unverified: [{"asked", "reason"}]`.

    Direction of error (I1): toward "not verified", never toward `missing`. An asked id under a broken NODE (a class
    whose collection failed: `file.py::TestX`) is `unverified` FIRST, even when its file gave other ids. An asked id
    whose file (or whose folder) gave at least one collected id goes through `match`, which may say `missing` for a
    test the healthy file does not have. Every other asked id is `unverified`: with the reason "file X could not be collected: <head>" when a broken
    file or folder covers it (by whole path components), else "file X yielded no test in this collect" - a file that
    gave nothing is never proof that the test is not there."""
    ids = [str(i) for i in ids or []]
    files = [split_id(i)[0] for i in ids]
    listed, unverified = [], []
    for asked_id in [str(a) for a in asked or []]:
        file = split_id(asked_id)[0]
        folder = file.lower().rstrip("/") + "/"
        node = next((b for b in broken or [] if _under_node(b.get("path", ""), asked_id)), None)
        if node is None and any(_same_file(file, f) or f.lower().startswith(folder) for f in files):
            listed.append(asked_id)
            continue
        row = node or next((b for b in broken or [] if _covers(b.get("path", ""), file)), None)
        reason = (f"file {row['path']} could not be collected" + (f": {row['head']}" if row.get("head") else "")) if row \
            else f"file {file} yielded no test in this collect"
        unverified.append({"asked": asked_id, "reason": reason})
    result = match(listed, ids, ticket=ticket, stage=stage, project_root=project_root) if listed \
        else {"resolved": {}, "missing": [], "notes": []}
    result["unverified"] = unverified
    for reason in sorted({u["reason"] for u in unverified}):
        result["notes"].append(f"not verified, {reason}")
    return result


def check_request(argv, cwd, asked, timeout_s: int = 180, *, ticket=None, stage="S5",
                  project_root=None, form=None) -> dict:
    """collect + match. A collect that cannot answer never blocks a run: it returns no
    resolved and no missing ids, the reason in `notes` and its head in `collect_error`.
    With `form` a collect that went on past broken files is matched by `match_partial`: the ids of the healthy
    files are checked, the others are `unverified` (notes), and only a `missing` one refuses."""
    asked = [str(a) for a in asked or []]
    if not asked:
        return {"resolved": {}, "missing": [], "notes": []}
    if not is_pytest(argv):
        return {"resolved": {}, "missing": [],
                "notes": ["not a pytest command: node ids were not verified"]}
    try:
        collected = collect(_collect_argv(argv, asked), cwd, timeout_s, files=_files(asked), form=form)
    except CollectError as exc:
        if exc.kind == "partial":
            result = match_partial(asked, exc.ids, exc.broken, ticket=ticket, stage=stage, project_root=project_root)
            result["notes"].insert(0, broken_sentence(exc.broken))
            result["broken"] = list(exc.broken)
            return result
        return {"resolved": {}, "missing": [],
                "notes": [f"node ids were not verified: {exc.message}"],
                "collect_error": exc.head}
    return match(asked, collected, ticket=ticket, stage=stage, project_root=project_root)


def runner_form(argv) -> tuple:
    """`(row, note)`: the runner's `collect_forms` row for `argv` (`launch_check.runner_row`) and, when the table or the
    code that reads it is not usable, the note that says the collect stays all-or-nothing (E3-12) - `(None, note)`.
    For the callers that have no row of their own (the CLI below, the sandbox, the manifest writer): they pass it to
    `check_request`, so one broken file no longer makes every id of the batch "missing" or unverified (AR-15, I1).
    Imported at call time, this module is standard library only: a half-installed tree yields `(None, "")`, the old
    behaviour, never a flag from the code."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import launch_check
        row, problem = launch_check.runner_row(argv)
        return row, (launch_check.table_note(problem) if problem else "")
    except Exception:                                    # pragma: no cover - partial install
        return None, ""


def repair_marker() -> str:
    """`role_cli.REPAIR_MARKER`, or "" when the rest of the factory is not importable.

    This module is standard library only by design, so the constant is fetched at the moment a
    refusal is printed and never at import: a half-installed tree loses the routing hint, not
    the refusal. Fetched rather than copied, because a driver matches the sentence exactly and a
    paraphrase routes a repair to a person (P4b).
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from role_cli import REPAIR_MARKER
        return str(REPAIR_MARKER)
    except Exception:                                    # pragma: no cover - partial install
        return ""


def missing_sentence(missing) -> str:
    """One plain sentence per missing id, shared by the runner's and the sandbox's refusals."""
    parts = []
    for row in missing or []:
        near = ", ".join(row.get("nearest") or []) or "nothing similar was collected"
        parts.append(f"{row.get('asked')} is not collected by pytest; nearest: {near}")
    return "; ".join(parts)


# --- CLI -----------------------------------------------------------------------------------

def selftest() -> int:
    failures: list = []

    def case(name, got, expected):
        if got != expected:
            failures.append(f"{name}: expected {expected!r}, got {got!r}")

    file = "tests/ui/workflows/test_workflow_visual_diff.py"
    fn = f"{file}::test_visual_diff_markers_follow_the_selected_pair_not_a_stale_pair"
    collected = [f"{fn}[chromium-buffer-R3-vs-selected-R1]", f"{fn}[chromium-saved-R2-vs-R1]",
                 f"{file}::test_visual_diff_is_read_only[chromium]"]
    asked = f"{fn}[buffer-R3-vs-selected-R1]"
    got = match([asked], collected)
    case("the TP1-15045 id is resolved to its chromium spelling",
         got["resolved"], {asked: collected[0]})
    case("with a note", len(got["notes"]), 1)
    case("an id without parameters matches any parametrization",
         match([fn], collected)["missing"], [])
    case("an exact id is resolved to itself",
         match([collected[1]], collected)["resolved"], {collected[1]: collected[1]})
    gone = match([f"{fn}[buffer-R9]"], collected)
    case("an unknown parameter id is missing", [m["asked"] for m in gone["missing"]],
         [f"{fn}[buffer-R9]"])
    case("and its nearest ids are of the same function first",
         gone["missing"][0]["nearest"][:2], collected[:2])
    windows = "C:\\qsbx\\" + asked.replace("/", "\\")
    case("an absolute sandbox prefix and backslashes do not break matching",
         list(match([windows], collected)["resolved"]), [windows])
    two = collected + [f"{fn}[firefox-buffer-R3-vs-selected-R1]"]
    case("two browsers are not guessed between", len(match([asked], two)["missing"]), 1)
    case("a report path and workers never reach a collect",
         _collect_argv(["pytest", "-n", "4", "--junitxml=x.xml", "-q", "{report_path}"]),
         ["pytest", "-q"])
    case("pytest is recognised behind a wrapper",
         [is_pytest(["poetry", "run", "pytest"]), is_pytest(["py", "-m", "pytest"]),
          is_pytest(["npx", "playwright", "test"])], [True, True, False])
    case("collected ids are parsed up to the first section",
         parse_collected("a/test_x.py::test_a[chromium-1]\n\n1 test collected\n"
                         "==== warnings ====\nb/test_y.py::test_b\n"),
         ["a/test_x.py::test_a[chromium-1]"])
    case("the verbosity-0 tree is recognised so a retry is triggered",
         bool(TREE_TAG_RE.search("<Dir x>\n  <Module test_a.py>\n    <Function test_x>\n")),
         True)
    case("a flat id list never looks like the tree",
         bool(TREE_TAG_RE.search("a/test_x.py::test_a[chromium-1]\n1 test collected\n")),
         False)

    if failures:
        print("NODE_IDS SELFTEST: VIOLATIONS")
        for f in failures:
            print("  - " + f)
        return 1
    print("NODE_IDS SELFTEST: no violations (browser prefix, bare function, nearest ids, "
          "paths, collect command)")
    return 0


def main() -> int:
    raw = sys.argv[1:]
    command = []
    if "--" in raw:
        cut = raw.index("--")
        raw, command = raw[:cut], raw[cut + 1:]
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cwd", default=".")
    ap.add_argument("--ids", nargs="+", default=[])
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(raw)
    if args.selftest:
        return selftest()
    if not args.ids or not command:
        print("node_ids.py: --ids ID [ID ...] and the test command after `--` are required, e.g. "
              "`node_ids.py --cwd . --ids tests/test_x.py::test_a -- python -m pytest`. "
              + repair_marker(), file=sys.stderr)
        return 2
    form, note = runner_form(command)
    result = check_request(command, args.cwd, args.ids, args.timeout, form=form)
    if note:
        result["notes"] = list(result.get("notes") or []) + [note]
    print(json.dumps(result, indent=1))
    return 2 if result["missing"] else (3 if result.get("collect_error") else 0)


if __name__ == "__main__":
    sys.exit(main())
