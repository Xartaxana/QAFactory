"""reporters.py — the ONE reader of a test run's machine-readable report.

A library module: no CLI, writes nothing, standard library only.

Report rows were read by four private parsers (two in run_suite.py, one in red_sandbox.py, one
in probe_by_code.py) and a fifth reader behind `run_suite --detail`; only one of them knew TRX,
the .NET format. This module is what they share (FR-17: the helper is wired where the problem
occurs, not at three of four sites). The `{report_path}` placeholder is NOT bound here: it is
replaced inside its token at each site (the validator demands exactly one holder token, and the
launch and the gate's reporter probe substitute inside it), as upstream settled it in 0.8.1.

Dispatch is on the TYPED reporter name (`pytest`, `junit-xml`, `trx`), never on the XML root tag:
the project's config says what the command writes, and a reader that guesses from the file turns
a wrong declaration into a plausible-looking wrong answer.

Row shape (every reporter):  {test_id, status, problems: [{kind, message, text}]}
  status   passed | failed | error | skipped | not_run  (the words run_suite already uses, plus
           not_run for "the report does not say" — FR-41: an unknown is never reported as a fact)
  problems in document order; `text` is the stack (JUnit: the node body, TRX: ErrorInfo/StackTrace).
           kind is `failure` / `error`, or `skipped` for a skip that gave a reason (JUnit
           <skipped message>, TRX ErrorInfo/Message of a skipped / not-executed result): run_suite's
           `reason` is `problems[kind=skipped].message[:160] or "(no reason)"` for JUnit and the first
           line of that message for TRX. A skip with no reason has no problem.
TRX rows add `class_name` and `method_name` when the result's `UnitTest/TestMethod` exists.

`test_id` is a contract with the manifest's `report_test_id`: JUnit -> `classname::name`, TRX ->
the `testName` attribute, exactly as run_suite.parse_junitxml / parse_trx build them. This module
never caps, never de-duplicates and never matches rows to anything: ambiguity is the consumer's
to refuse, a row lost here is lost for good.

One row per JUnit testcase, also inside nested suites: the older readers listed a testcase of a
nested suite once per ancestor suite, so row counts differ from theirs only there.
"""
import posixpath
import re
import xml.etree.ElementTree as ET
from pathlib import Path

READERS = ("pytest", "junit-xml", "trx")
STATUSES = ("passed", "failed", "error", "skipped", "not_run")

# B-416 (D-0031): what the code tries on a report it could not read, and the limits of trying. A report is parsed and kept up to
# PARSE_LIMIT / KEEP_LIMIT bytes (AT the limit: yes, one byte beyond: no), at most KEEP_FILES files of one run are kept, and the
# prolog is scanned ENTITY_SCAN_LIMIT bytes for a DOCTYPE that declares entities.
PARSE_LIMIT = 5 * 1024 * 1024
KEEP_LIMIT = 5 * 1024 * 1024
KEEP_FILES = 5
ENTITY_SCAN_LIMIT = 65536
FIT_READERS = ("junit-xml", "trx")      # the typed readers `fits` tries, in this order (`pytest` is the junit reader)

# What each TRX outcome means for a proof. The current run_suite reader passed any word it did not
# know through as the status ("timeout", "aborted") and read an ABSENT outcome as `passed`; the
# first is outside the vocabulary every consumer compares against and the second reports a test
# that never said it ran as one that passed. Anything not named here is `not_run`.
_TRX_STATUS = {
    "passed": "passed",
    "failed": "failed",
    "notexecuted": "skipped",
    "inconclusive": "skipped",
    "skipped": "skipped",
    "error": "error",
    "timeout": "error",
    "aborted": "error",
}


def _check_reporter(reporter) -> None:
    if reporter not in READERS:
        raise ValueError(f"unknown reporter {reporter!r}: expected one of {', '.join(READERS)} "
                         "(`none` means no report is written, so there are no rows to read)")


def read_rows(path, reporter) -> list:
    """One row per test in the report at `path`, read by the TYPED `reporter`.

    Malformed XML (`xml.etree.ElementTree.ParseError`) and a missing file (`OSError`) propagate:
    the caller knows which run this was and what to tell the person."""
    _check_reporter(reporter)
    return _read_trx(path) if reporter == "trx" else _read_junit(path)


def _prolog_text(head: bytes) -> str:
    """The head of a file as text for the prolog scan: UTF-8 (a BOM dropped), UTF-16 by its BOM; "" when it cannot be read as either
    (NUL bytes with no BOM - the scan then refuses, the safe side)."""
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return head.decode("utf-16", errors="ignore")
    if b"\x00" in head:
        return ""
    return head.decode("utf-8-sig", errors="ignore")


def _prolog_state(path, scan_limit: int = ENTITY_SCAN_LIMIT) -> str:
    """`ok` (a root element starts within the first `scan_limit` + 1 bytes and the prolog before it declares no entity), `entities` (the
    prolog holds `<!ENTITY`, in any case, inside the DOCTYPE or a comment of it) or `noroot` (no root element start was found in that
    head, or the head cannot be read as text: the safe side). The prolog is walked in XML's own order - processing instructions, comments,
    the DOCTYPE with its internal subset (brackets and quoted strings tracked) - so a `<z>` inside a quoted default never ends it early."""
    try:
        with open(path, "rb") as handle:
            text = _prolog_text(handle.read(scan_limit + 1))
    except OSError:
        return "noroot"
    n, i = len(text), 0
    while i < n:
        if text[i].isspace():
            i += 1
        elif text.startswith("<?", i):
            end = text.find("?>", i + 2)
            if end < 0:
                return "noroot"
            i = end + 2
        elif text.startswith("<!--", i):
            end = text.find("-->", i + 4)
            if end < 0:
                return "noroot"
            i = end + 3
        elif text[i:i + 9].upper() == "<!DOCTYPE":
            j, bracket, quote = i + 9, False, ""
            while j < n:
                c = text[j]
                if quote:
                    quote = "" if c == quote else quote
                elif c in "\"'":
                    quote = c
                elif text.startswith("<!--", j):
                    end = text.find("-->", j + 4)
                    j = end + 2 if end >= 0 else n
                elif c == "[":
                    bracket = True
                elif c == "]":
                    bracket = False
                elif c == ">" and not bracket:
                    break
                j += 1
            else:
                return "noroot"
            if "<!ENTITY" in text[i:j + 1].upper():
                return "entities"
            i = j + 1
        elif text[i] == "<":
            return "ok"
        else:
            return "noroot"
    return "noroot"


def entity_declared(path, scan_limit: int = ENTITY_SCAN_LIMIT) -> bool:
    """True when the prolog of the XML at `path`, before its first root element, declares an entity (`<!DOCTYPE` with `<!ENTITY`) - and
    True also when no root start is found within `scan_limit` bytes (the safe side: a hostile report never reaches the parser, FR-59).
    A DOCTYPE with no ENTITY is not refused. A root start at byte `scan_limit` is read; none within `scan_limit` + 1 bytes is refused."""
    return _prolog_state(path, scan_limit) != "ok"


def fits(path, size_limit: int = PARSE_LIMIT) -> list:
    """`[{reader, tests, error}]` - what each typed reader (`junit-xml`, then `trx`) counts in the file at `path`: DIAGNOSIS for a report the
    declared reader could not read. A reader FITS when it counts at least one row; `read_rows` is unchanged and nothing is written.

    ERROR DIRECTION: only toward "nothing fits". A file over `size_limit`, a prolog that declares entities or holds no root element, a file
    that cannot be opened or parsed, a namespaced JUnit, `tests="0"`, a TRX with no `UnitTestResult`, HTML, JSON, an empty file - each gives
    `tests: 0` for both readers with the reason in `error`, and nothing is parsed that the gates refused."""
    try:
        size = Path(path).stat().st_size
    except OSError as exc:
        return [{"reader": r, "tests": 0, "error": f"the file cannot be read ({exc.strerror or type(exc).__name__})"} for r in FIT_READERS]
    refusal = ""
    if size > size_limit:
        refusal = f"the report is larger than the {size_limit} bytes the factory reads"
    else:
        state = _prolog_state(path)
        if state == "entities":
            refusal = "the report declares XML entities, which the factory does not expand"
        elif state == "noroot":
            refusal = "the file holds no XML element the factory can find"
    if refusal:
        return [{"reader": r, "tests": 0, "error": refusal} for r in FIT_READERS]
    out = []
    for reader in FIT_READERS:
        try:
            out.append({"reader": reader, "tests": len(read_rows(path, reader)), "error": ""})
        except Exception as exc:        # a parse error, a read error: the reader does not fit, never a raise
            out.append({"reader": reader, "tests": 0, "error": f"{type(exc).__name__}: {str(exc)[:80]}"})
    return out


def _local(node) -> str:
    return node.tag.rpartition("}")[2]


def _child(node, name: str):
    for child in node:
        if _local(child) == name:
            return child
    return None


def _text(node) -> str:
    return ((node.text if node is not None else "") or "").strip()


def _read_junit(path) -> list:
    root = ET.parse(path).getroot()
    rows = []
    # One pass over the testcases of the whole tree: iterating every <testsuite> and then each
    # one's descendants lists a testcase of a nested suite once per ancestor, and a duplicate
    # test_id is exactly what a consumer must refuse as ambiguous.
    for case in root.iter("testcase"):
        problems = []
        for child in case:
            if child.tag not in ("failure", "error", "skipped"):
                continue
            problem = {"kind": child.tag, "message": (child.get("message") or "").strip(),
                       "text": _text(child)}
            # A skip with no reason says nothing: no problem, and the consumer's own
            # "(no reason)" fills the gap exactly as run_suite did.
            if child.tag != "skipped" or problem["message"] or problem["text"]:
                problems.append(problem)
        # run_suite.parse_junitxml's rule: error outranks failure, and a skip outranks both.
        status = "passed"
        if any(p["kind"] == "failure" for p in problems):
            status = "failed"
        if any(p["kind"] == "error" for p in problems):
            status = "error"
        if case.find("skipped") is not None:
            status = "skipped"
        rows.append({"test_id": f"{case.get('classname', '')}::{case.get('name', '')}".strip(":"),
                     "status": status, "problems": problems})
    return rows


def _read_trx(path) -> list:
    root = ET.parse(path).getroot()
    methods: dict = {}
    for node in root.iter():
        if _local(node) == "UnitTest":
            method = _child(node, "TestMethod")
            if method is not None:
                methods.setdefault(node.get("id"), (method.get("className") or "", method.get("name") or ""))
    rows = []
    # `iter()` walks InnerResults too: every UnitTestResult is a row, parent first.
    for node in root.iter():
        if _local(node) != "UnitTestResult":
            continue
        outcome = (node.get("outcome") or "").lower()
        status = _TRX_STATUS.get(outcome, "not_run")
        row = {"test_id": node.get("testName") or "?", "status": status, "problems": []}
        # Only the result's OWN Output/ErrorInfo: a parent's descendants include its inner
        # results' messages, and those belong to their own rows.
        output = _child(node, "Output")
        info = _child(output, "ErrorInfo") if output is not None else None
        if info is not None and status in ("failed", "error"):
            row["problems"].append({"kind": "failure" if status == "failed" else "error",
                                    "message": _text(_child(info, "Message")),
                                    "text": _text(_child(info, "StackTrace"))})
        elif info is not None and status == "skipped":
            # The skip reason (xUnit puts it in ErrorInfo/Message); empty means no reason.
            reason, stack = _text(_child(info, "Message")), _text(_child(info, "StackTrace"))
            if reason or stack:
                row["problems"].append({"kind": "skipped", "message": reason, "text": stack})
        definition = methods.get(node.get("testId"))
        if definition is not None:
            row["class_name"], row["method_name"] = definition
        rows.append(row)
    return rows


# --- where a failure happened ----------------------------------------------------------------

# pytest's own last traceback line: `path:line: Exception`.
_TRACE_TAIL = re.compile(r"^(?P<loc>\S.*:\d+):\s*(?P<exc>\S+)\s*$")
# A .NET stack frame that carries a file: `   at Ns.Class.Method() in C:\clone\x.cs:line 42`.
_FRAME = re.compile(r"^\s*at\s+.+?\s+in\s+(?P<path>.+?):line\s+(?P<line>\d+)\s*$")
_DRIVE = re.compile(r"^[A-Za-z]:/")


def _slashes(value: str) -> str:
    return str(value).replace("\\", "/")


def _is_absolute(path: str) -> bool:
    return path.startswith("/") or bool(_DRIVE.match(path))


def _inside_clone(path: str, clone_root) -> str:
    """`path` relative to the clone with forward slashes, or "" when it is not inside it.

    Windows paths compare case-insensitively (the same directory is `C:\\Clone` and `c:\\clone`
    in two places of one build); POSIX ones do not."""
    root = _slashes(clone_root or "").rstrip("/")
    if not root or not _is_absolute(path):
        return ""
    fold = bool(_DRIVE.match(root + "/"))
    left, right = (path.lower(), root.lower()) if fold else (path, root)
    return path[len(root) + 1:] if left.startswith(right + "/") else ""


def _site_path(raw: str, clone_root) -> tuple:
    """(path to REPORT, path to COMPARE). Inside the clone both are clone-relative. Any other
    absolute path is reported as written and compares as itself, so it can never equal a
    clone-relative expectation: a frame in the AUTHOR's tree means the author's build ran, not
    the clone's, and stripping the author's root would turn that into proof."""
    slashed = _slashes(raw)
    inside = _inside_clone(slashed, clone_root)
    if inside:
        return inside, inside
    if _is_absolute(slashed):
        return raw, slashed
    return slashed, slashed


def assertion_site(row: dict, reporter: str, clone_root, test_file, *,
                   pytest_command: bool = True, runtime: str = "",
                   frames=None, skip_frames=None, frame_path: str = "path") -> dict:
    """`{"location": "<path>:<line>", "failure_kind": ...}` for a failed row, or `{}` when the row
    is not proof (no stack, or no frame that names a file), or - for a `junit-xml` row of a runner
    that is not pytest - `{"site_unread": "junit-xml/<runtime>", "reason": ...}`.

    pytest, and junit-xml of a pytest command: pytest's own last traceback line, the rule the old
    private reader applied. That grammar is read for no other JUnit producer: a Jest frame came out
    as a garbage location of kind `exception`, Java JUnit and the .NET JUnit logger as `{}`, and a
    probe over such a profile ended `survived` with no word of why. A failed or errored row of a
    non-pytest `junit-xml` run is therefore a TYPED answer - the site is not read yet (B-337) - and
    the caller turns it into an incomplete proof, never a verdict on the test. `pytest_command` is
    what the caller knows of the run (`execution_request.is_pytest_command(argv)`; True is the old
    behaviour, so a caller that says nothing is unchanged); `runtime` is its hint for the text, the
    launcher's name, and decides nothing.

    trx: the first stack frame that carries a file location. A FAILED row is an `assertion` when
    that frame is in `test_file`, an `exception` when it is elsewhere (an exception the test merely
    exposed); a row whose status is `error` (timeout, aborted, Error) is `error`.

    `frames` (B-373, the live probe for a test in any language): a list of regexes with the named
    groups `path` and `line` - the stack-frame grammar of the runtime, data the caller reads from
    `references/detectors.json`. Given, it REPLACES the built-in grammar for a `trx` row and for a
    `junit-xml` row of a command that is not pytest (for any other row it is ignored: pytest's rule
    stays pytest's). The failure's text is walked top to bottom, a line matching any `skip_frames`
    regex (library and runner frames) is skipped, and the first remaining line that matches a
    `frames` regex is THE frame; the answer then also carries `frame`, that raw line. Only a frame
    that resolves to a project file becomes a location (`frame_path`): `"path"` - inside the clone,
    or a relative path that names an existing file under it; `"basename"` - the frame's file name is
    the test file's AND the regex's `qual` group (the qualified method name, `com.acme.CalcTest.adds`)
    has a package path that is a suffix of the test file's directory, so a same-named file of another
    package is never taken for this one. Anything else, and a failed or errored row with no matching
    frame, is the typed `site_unread` answer: a tooling gap is never turned into a location, and so
    never into a verdict on the test (FR-59). `frames=None` is today's behaviour, byte for byte."""
    _check_reporter(reporter)
    problems = row.get("problems") or []
    if frames is not None and (reporter == "trx" or (reporter == "junit-xml" and not pytest_command)):
        return _frame_site(row, reporter, clone_root, test_file, runtime, frames, skip_frames, frame_path)
    if reporter == "junit-xml" and not pytest_command:
        if row.get("status") not in ("failed", "error"):
            return {}  # a green or skipped row has no site to read
        unread = f"{reporter}/{runtime or 'unknown runtime'}"
        return {"site_unread": unread, "reason": f"the assertion site of a {unread} report is not read yet (B-337)"}
    if reporter != "trx":
        return _pytest_site(row, problems)
    # The row's failure or error problem; a skip's text is not a failure site.
    chosen = next((p for p in problems if p.get("kind") in ("failure", "error")), None)
    for line in ((chosen or {}).get("text") or "").splitlines():
        match = _FRAME.match(line)
        if not match:
            continue
        shown, compared = _site_path(match.group("path").strip(), clone_root)
        expected = _expected_path(test_file, clone_root)
        if row.get("status") == "error":
            kind = "error"
        else:
            kind = "assertion" if row.get("status") == "failed" and expected and compared == expected \
                else "exception"
        return {"location": f"{shown}:{match.group('line')}", "failure_kind": kind}
    return {}


def _grammar(patterns, label: str) -> tuple:
    """(compiled regexes, "") or ([], why): a bare string is one pattern, not a list of letters; a
    value that is neither a string nor a list or tuple is a gap, never an exception."""
    if isinstance(patterns, str):
        patterns = [patterns]
    if patterns is not None and not isinstance(patterns, (list, tuple)):
        return [], f"a {label} grammar must be a list of regexes or one regex, not {type(patterns).__name__}"
    compiled = []
    for pattern in patterns or []:
        try:
            compiled.append(re.compile(pattern))
        except (re.error, TypeError) as error:
            return [], f"a {label} regex does not compile ({error})"
    return compiled, ""


def frame_matches(text: str, wanted: list, skipped: list):
    """THE one frame walk (t-2064 N3b F4): `(line, match)` for each line of `text`, in order, that a compiled `wanted` regex reads as a
    stack frame and no `skipped` regex drops. A group that did not take part in the match is no frame, not a path of None. The site
    reader takes the first; the critic's `frames` fact lists them all."""
    for line in (text or "").splitlines():
        if any(rx.search(line) for rx in skipped):
            continue
        for rx in wanted:
            match = rx.search(line)
            if match and (match.group("path") or "").strip() and match.group("line") is not None:
                yield line, match
                break


def frame_lines(text: str, frames, skip_frames) -> list:
    """The frame lines of `text` (stripped) under a grammar given as patterns, by `frame_matches`; `[]` when a pattern does not compile
    or lacks the groups `path` and `line` (a gap is the site reader's to say, not a list)."""
    wanted, why = _grammar(frames, "frames")
    skipped, skip_why = _grammar(skip_frames, "skip_frames")
    if why or skip_why or not all({"path", "line"} <= set(rx.groupindex) for rx in wanted):
        return []
    return [line.strip() for line, _match in frame_matches(text, wanted, skipped)]


def _expected_path(test_file, clone_root) -> str:
    """The test file as the frames are compared with it: forward slashes, clone-relative when it
    is inside the clone, no leading `./`."""
    expected = _slashes(test_file or "")
    expected = _inside_clone(expected, clone_root) or expected
    return expected[2:] if expected.startswith("./") else expected


def _package_of(qual: str) -> "list | None":
    """The package segments of a qualified frame name `[module/]pkg.Class[$Inner].method`, or None
    when it is not that shape (fewer than a class and a method)."""
    parts = qual.strip().rpartition("/")[2].split(".")
    if len(parts) < 2 or not all(parts):
        return None
    return parts[:-2]


def _frame_site(row, reporter, clone_root, test_file, runtime, frames, skip_frames, frame_path) -> dict:
    """`assertion_site` with the caller's frame grammar (see its docstring)."""
    if row.get("status") not in ("failed", "error"):
        return {}  # a green or skipped row has no site to read
    unread = f"{reporter}/{runtime or 'unknown runtime'}"

    def refuse(why: str) -> dict:
        return {"site_unread": unread, "reason": f"the assertion site of a {unread} report was not read: {why}"}

    if frame_path not in ("path", "basename"):
        return refuse(f"frame_path {frame_path!r} is neither 'path' nor 'basename'")
    wanted, why = _grammar(frames, "frames")
    skipped, skip_why = _grammar(skip_frames, "skip_frames")
    if why or skip_why:
        return refuse(why or skip_why)
    if not all({"path", "line"} <= set(rx.groupindex) for rx in wanted):
        return refuse("every frames regex needs the named groups `path` and `line`")
    # The row's failure or error problem; a skip's text is not a failure site.
    chosen = next((p for p in row.get("problems") or [] if p.get("kind") in ("failure", "error")), None)
    found = next(frame_matches((chosen or {}).get("text") or "", wanted, skipped), None)
    if not found:
        return refuse("no frame of its stack matched the declared frame grammar")
    line, match = found
    expected = _expected_path(test_file, clone_root)
    slashed = _slashes(match.group("path").strip())
    if frame_path == "basename":
        if not expected or posixpath.basename(slashed) != posixpath.basename(expected):
            return refuse(f"the frame's file {slashed!r} is not the test file's name")
        package = _package_of(match.groupdict().get("qual") or "")
        if package is None:
            return refuse("a basename frame needs a `qual` group naming its package, and this one has none")
        directory = [part for part in posixpath.dirname(expected).split("/") if part]
        if package and directory[len(directory) - len(package):] != package:
            return refuse(f"the frame's package {'.'.join(package)!r} is not the test file's directory")
        shown = expected
    else:
        inside = _inside_clone(slashed, clone_root)
        if not inside and _is_absolute(slashed):
            return refuse(f"the frame's file {slashed!r} is not inside the clone")
        shown = posixpath.normpath(inside or slashed)
        if shown == "." or shown == ".." or shown.startswith("../"):
            return refuse(f"the frame's path {slashed!r} leaves the clone")
        # A relative path is the runner's working directory's, which this reader cannot know. A
        # proper tail of the test file's own path may be that file seen from a subdirectory - or
        # another file of the clone that happens to exist at the clone root: unprovable, so never
        # a location (it would reach R8 as `wrong_location` and accuse the author).
        if not inside and shown != expected and expected.endswith("/" + shown):
            return refuse(f"ambiguous relative frame {slashed!r}: it is a tail of the test file's path "
                          f"{expected!r}, and the runner's working directory is not known")
        # Otherwise it counts only when the file is really there under the clone.
        if not inside and (not clone_root or not (Path(str(clone_root)) / shown).is_file()):
            return refuse(f"the frame's relative path {slashed!r} names no file under the clone")
    if row.get("status") == "error":
        kind = "error"
    else:
        kind = "assertion" if expected and shown == expected else "exception"
    return {"location": f"{shown}:{match.group('line')}", "failure_kind": kind, "frame": line}


def failure_frames(row, frames, skip_frames, error_head=None, after_frame_ok=()) -> "list | None":
    """`[(path with forward slashes, line number)]` of EVERY frame in EVERY failure/error problem of `row`, or None.

    `_frame_site` stops at the first frame; a runner that keeps going after a failed check (a soft assertion) lists one
    error per failed check inside one `<failure>`, and which lines failed is the answer here, so the walk does not stop
    (EP1-38). The grammar is `_frame_site`'s: `frames` regexes with the named groups `path` and `line`, a line matching
    a `skip_frames` regex is skipped. A frame outside the test file is in the list too: the caller compares the lines
    with its own (a throw inside a helper must not be read as a quiet soft failure). The path is returned as written,
    only the slashes are unified; resolving it is the caller's.

    TEXT INTEGRITY (EP1-38 F-2): a test that stopped (a timeout, a throw with no frame of the test file) leaves a text
    whose only frame is the soft one, and that must not read as "the asserts behind ran". `error_head` (a regex: the
    first line of one error) and `after_frame_ok` (regexes: the only lines allowed after an error's last frame) say how
    the runner builds the text; an error with no frame, or a line after a frame that is not in `after_frame_ok`, gives
    None. Without `error_head` the text is not checked (the caller that needs it passes it).

    None = not established: a row that is not failed or errored, no failure problem, a grammar that is not a list of
    regexes with `path` and `line` (or does not compile), no frame matched, or a text that does not fit the integrity
    check. Error direction: None, never a guess."""
    if not isinstance(row, dict) or row.get("status") not in ("failed", "error"):
        return None
    wanted, why = _grammar(frames, "frames")
    skipped, skip_why = _grammar(skip_frames, "skip_frames")
    if why or skip_why or not wanted or not all({"path", "line"} <= set(rx.groupindex) for rx in wanted):
        return None
    head, ok = None, []
    if error_head is not None:
        heads, head_why = _grammar([error_head], "error_head")
        oks, ok_why = _grammar(list(after_frame_ok or ()), "after_frame_ok")
        if head_why or ok_why or not heads:
            return None
        head, ok = heads[0], oks
    found = []
    for problem in row.get("problems") or []:
        if not isinstance(problem, dict) or problem.get("kind") not in ("failure", "error"):
            continue
        in_block = has_frame = False
        for line in (problem.get("text") or "").splitlines():
            if any(rx.search(line) for rx in skipped):
                continue
            hit = False
            for rx in wanted:
                match = rx.search(line)
                if match and (match.group("path") or "").strip() and match.group("line") is not None:
                    found.append((_slashes(match.group("path").strip()), int(match.group("line"))))
                    hit = has_frame = True
                    break
            if hit or head is None:
                continue
            if head.search(line):
                if in_block and not has_frame:
                    return None   # an error with no frame
                in_block, has_frame = True, False
            elif has_frame and line.strip() and not any(rx.search(line) for rx in ok):
                return None       # text after a frame that the data does not know: the test may have stopped
        if head is not None and in_block and not has_frame:
            return None
    return found or None


def _pytest_site(row: dict, problems: list) -> dict:
    # The old private row reader took the <failure> body before the <error> one; keep that order.
    chosen = next((p for p in problems if p.get("kind") == "failure"),
                  next((p for p in problems if p.get("kind") == "error"), None))
    for line in reversed(((chosen or {}).get("text") or "").splitlines()):
        line = line.strip()
        if not line:
            continue
        match = _TRACE_TAIL.match(line)
        if not match:
            break
        kind = ("assertion" if match.group("exc") == "AssertionError" else
                "error" if row.get("status") == "error" else "exception")
        return {"location": match.group("loc"), "failure_kind": kind}
    return {}


# --- the reason an assertion failed ----------------------------------------------------------

_PREFIX = "AssertionError:"


def _collapse(value) -> str:
    return " ".join(str(value or "").split())


def _fold(value) -> str:
    """Whitespace runs folded, then pytest's `AssertionError:` prefix dropped — the rule the two
    private folds this module replaced (one in red_sandbox, one in window_record) agreed on
    (TP1-15045: a fifteen-character prefix cost a whole second sandbox)."""
    text = _collapse(value)
    return text[len(_PREFIX):].strip() if text.startswith(_PREFIX) else text


def _headline(value) -> str:
    """The first non-empty line, folded. The prefix goes first, so `AssertionError:` alone on a
    line does not become the headline of a message whose real first line follows it."""
    text = str(value or "").lstrip()
    if text.startswith(_PREFIX):
        text = text[len(_PREFIX):]
    for line in text.splitlines():
        if line.strip():
            return _collapse(line)
    return ""


def _pinned_line_count(value) -> int:
    """How many non-empty lines the text has, the `AssertionError:` prefix dropped first (as
    `_headline` does). Trailing blank lines and CRLF do not count as lines."""
    text = str(value or "").lstrip()
    if text.startswith(_PREFIX):
        text = text[len(_PREFIX):]
    return sum(1 for line in text.splitlines() if line.strip())


def _reason_rule(expected, actual) -> str:
    """Which comparison `assertion_reason` MAKES for this pair (not whether it matches): `whole` - the folded texts
    are equal, or the author pinned two or more lines; `headline` - the author pinned ONE line and the texts differ, so
    the actual is cut to its first line; `empty_pin` - the pin has no line. The one rule `assertion_reason` and
    `reason_detail` share (AR-13)."""
    if _fold(expected) == _fold(actual) or _pinned_line_count(expected) > 1:
        return "whole"
    return "headline" if _pinned_line_count(expected) == 1 else "empty_pin"


def assertion_reason(expected, actual) -> tuple:
    """`(e, a)` — the pair the producer writes and the acceptance side compares; a match is
    `bool(e) and e == a`. The same function serves both, so they cannot disagree (Fact 9).

    The whole texts, folded (upstream's `reason_matches` fold: whitespace runs, then the
    `AssertionError:` prefix), when they are equal. Otherwise, ONLY when the author pinned a
    single line: the folded pin against the actual's HEADLINE - a .NET assertion reads
    "Assert.Equal() Failure" over `Expected:` / `Actual:` lines the author never pinned, and
    refusing a proof for detail the reporter appended is refusing the right failure. A pin of two
    or more lines needs the whole folded text (detail the author pinned is never ignored: "count
    mismatch / expected 4" is not "count mismatch / expected 5"). An empty pin is zero lines, so
    it never matches; it keeps the headline of the actual in the pair, as it always did."""
    folded_expected = _fold(expected)
    if _reason_rule(expected, actual) == "whole":
        return folded_expected, _fold(actual)
    return folded_expected, _headline(actual)


# B-380 (FR-26, FR-49): when the reason matched on the headline alone, the window record keeps the failure's lines it
# was compared against, bounded; `reason_detail_line` is the reader that tells the critic what was not compared.
REASON_DETAIL_LINES = 12   # lines of the actual failure kept in the record
REASON_DETAIL_CHARS = 200  # characters per kept line, the cut mark `…` counts
REASON_DETAIL_SHOWN = 3    # detail lines the note shows


def reason_detail(expected, actual) -> dict:
    """`{rule, actual_lines, actual_lines_total}` - which comparison `assertion_reason` made and the lines of the actual
    failure. `actual_lines`: the `AssertionError:` prefix dropped first (as `_headline` does), blank lines dropped, each
    line whitespace-folded and cut to `REASON_DETAIL_CHARS` (`…` counts), the first `REASON_DETAIL_LINES` kept;
    `actual_lines_total` is the true count before that cap, so the record never claims to hold the whole failure when it
    does not. An empty or absent actual is `[]` and 0 (AR-23)."""
    text = str(actual or "").lstrip()
    if text.startswith(_PREFIX):
        text = text[len(_PREFIX):]
    lines = [_collapse(line) for line in text.splitlines() if line.strip()]
    kept = [line if len(line) <= REASON_DETAIL_CHARS else line[:REASON_DETAIL_CHARS - 1] + "…"
            for line in lines[:REASON_DETAIL_LINES]]
    return {"rule": _reason_rule(expected, actual), "actual_lines": kept, "actual_lines_total": len(lines)}


def reason_detail_line(probe, instance_id) -> str:
    """The note `window_record.verdict` prints for a probe whose reason was compared on the failure's first line only,
    or `""`: speaks only when the probe's `reason_detail` says `headline`, the failure has more than one line, and the
    probe's two reasons are equal and non-empty (it MATCHED). A record without the block (an older plugin) is not
    recorded, not "matched on the whole text" (FR-41); a malformed block is silent. The line does not start with the
    instance id: the readers of `info` take `<iid>:` lines for proof notes."""
    if not isinstance(probe, dict) or not isinstance(probe.get("reason_detail"), dict):
        return ""
    if not probe.get("expected_reason") or probe.get("expected_reason") != probe.get("actual_reason"):
        return ""
    detail = probe["reason_detail"]
    lines, total = detail.get("actual_lines"), detail.get("actual_lines_total")
    if (detail.get("rule") != "headline" or not isinstance(lines, list) or not lines
            or not isinstance(total, int) or isinstance(total, bool) or total <= 1):
        return ""
    shown = [str(line) for line in lines[1:1 + REASON_DETAIL_SHOWN]]
    more = total - 1 - len(shown)
    return (f"probe reason matched on the failure's first line only (\"{lines[0]}\"); {total - 1} other line(s) of the "
            "failure were not compared: " + " | ".join(f'"{line}"' for line in shown)
            + (f" (+{more} more)" if more > 0 else "") + f" ({instance_id})")
