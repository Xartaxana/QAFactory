"""`project_decisions.py add-finding --words-file`: a person's request to change the factory leaves a finding (CL1-5, D-0052 (3)).

The rule: when a person asks the factory's AI to change the factory (a rule, a role, a script, a form, a question), the first
party that holds the words (the orchestrator, the conductor) records them as an FB row with `--words-file <file>` and the key
`change-request:<T>`; the writer completes the key with a 12-hex digest of the collapsed words. Nobody edits the plugin.

Expected values below come from the spec (t-974 section 3 and the edges E1-E16, t-1111 section 4b), never from the code's own
output (FR-58): the digest is computed here from the spec's formula, the row shape from the spec's example. The carrier keys
(P14) were quoted from the DoD before the run; each has a NEGATIVE control (a scratch copy without the string fails the same
checker). The two defects the same change closes for EVERY `add-finding` caller are pinned too: a retry of a multi-line witness
is the same finding, and a `|` in a witness does not shift the columns or double the row on the next retry.

Runnable on its own: `python -B scripts/tests/test_project_decisions_change_request.py`."""
import contextlib
import hashlib
import io
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT, check, check_eq, cleanup, finish, run_script, temp_dir, temp_project  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import project_decisions as PD  # noqa: E402

WORDS = "Go on.\n\nKeep it local | \"do not publish\" to Jira.\n"
COLLAPSED = "Go on. Keep it local | \"do not publish\" to Jira."
ESSENCE = "The person asks that the factory stop asking which stand to use"
SCOPE = "upstream-candidate"


def digest(words: str) -> str:
    """The spec's own formula (t-974 section 3), written out here: it is NOT imported from the code under test."""
    return hashlib.sha256(" ".join(words.split()).encode("utf-8")).hexdigest()[:12]


def words_file(root: Path, data, name: str = "chat-1.txt") -> Path:
    path = root / "qa-factory" / "state" / "words" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return path


class Ran:
    """What a run of the CLI gave: the exit code and the two streams (the shape of subprocess.CompletedProcess)."""

    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def in_process(*argv) -> Ran:
    """`PD.main()` with this argv, streams captured: the same code path as the CLI without the interpreter start-up (about
    two seconds a call on a loaded machine). A few tests below still start the real interpreter."""
    saved, out, err, code = sys.argv, io.StringIO(), io.StringIO(), 0
    sys.argv = ["project_decisions.py", *[str(a) for a in argv]]
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                PD.main()
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 2
    finally:
        sys.argv = saved
    return Ran(code, out.getvalue(), err.getvalue())


def add(root: Path, *extra, key: str = "change-request:TP3-1", essence: str = ESSENCE, scope: str = SCOPE, cli: bool = False):
    args = ("--root", root, "add-finding", "--essence", essence, "--scope", scope, "--idempotency-key", key, *extra)
    return run_script("project_decisions.py", *args) if cli else in_process(*args)


def add_words(root: Path, data, key: str = "change-request:TP3-1", essence: str = ESSENCE, name: str = "chat-1.txt",
              cli: bool = False):
    return add(root, "--words-file", words_file(root, data, name), key=key, essence=essence, cli=cli)


def rows(root: Path) -> list:
    backlog = root / "qa-factory" / "factory-backlog.md"
    return PD.parse_findings(backlog.read_text(encoding="utf-8")) if backlog.exists() else []


def backlog_text(root: Path) -> str:
    backlog = root / "qa-factory" / "factory-backlog.md"
    return backlog.read_text(encoding="utf-8") if backlog.exists() else ""


def lines(text: str) -> list:
    return [line for line in text.splitlines() if line.strip()]


def test_the_key_gets_the_digest_of_the_collapsed_words() -> None:
    """P1 + P8: the marker ends `idempotency:change-request:TP3-1:<12 hex>`; the md row and the projection have the shape."""
    root = temp_project("qa-factory-change-request-")
    try:
        done = add_words(root, WORDS, cli=True)         # the real interpreter, the real argv
        check_eq("P1: the first call exits 0", done.returncode, 0)
        found = rows(root)
        check_eq("P1: one FB row", len(found), 1)
        expected_witness = f"{COLLAPSED}; idempotency:change-request:TP3-1:{digest(WORDS)}"
        check_eq("P1: the witness is the collapsed words plus the marker with the spec's digest",
                 found[0]["witness/details"], expected_witness)
        check("P1: the digest is 12 lowercase hex characters", len(digest(WORDS)) == 12 and
              all(c in "0123456789abcdef" for c in digest(WORDS)))
        # P8: the md row, character for character (the pipe of the words is escaped)
        expected_row = (f"| FB-1 | {ESSENCE} | {SCOPE} | {COLLAPSED.replace('|', chr(92) + '|')}; "
                        f"idempotency:change-request:TP3-1:{digest(WORDS)} | {date.today().isoformat()} | open | — |")
        check("P8: the md row has the spec's shape", expected_row in backlog_text(root).splitlines(), backlog_text(root)[-500:])
        projection = json.loads(PD._paths(root)[1].read_text(encoding="utf-8"))
        check_eq("P8: the projection has one finding with the same id, scope, witness and status open",
                 [(f["id"], f["scope"], f["witness/details"], f["status"]) for f in projection["findings"]],
                 [("FB-1", SCOPE, expected_witness, "open")])
        check_eq("P8: the CLI prints the row with the full key", json.loads(done.stdout)["witness/details"], expected_witness)
        verbatim = (root / "qa-factory" / "state" / "words" / "chat-1.txt").read_bytes()
        check_eq("E1: the words file under state/words stays verbatim", verbatim, WORDS.encode("utf-8"))
    finally:
        cleanup(root)


def test_the_same_request_is_one_row_and_two_requests_are_two() -> None:
    """P2 / P3 / P4 / P5 (I4): idempotent on the same words (CRLF and spacing included), never merged."""
    root = temp_project("qa-factory-change-request-")
    try:
        first = add_words(root, WORDS)
        again = add_words(root, WORDS)
        check_eq("P2: the same command twice: exit 0 both", (first.returncode, again.returncode), (0, 0))
        check_eq("P2: one FB row, FB-1", [r["id"] for r in rows(root)], ["FB-1"])
        check_eq("P2: the second call names the existing row", json.loads(again.stdout)["id"], "FB-1")
        projection = json.loads(PD._paths(root)[1].read_text(encoding="utf-8"))
        check_eq("P2: the projection has one entry", len(projection["findings"]), 1)
        crlf = add_words(root, WORDS.replace("\n", "\r\n"), name="chat-2.txt")
        spaced = add_words(root, "Go on.   Keep it local |   \"do not publish\"\tto Jira.", name="chat-3.txt")
        check_eq("P3: CRLF and doubled spaces are the same request: exit 0, still one row",
                 (crlf.returncode, spaced.returncode, len(rows(root))), (0, 0, 1))
        other = add_words(root, WORDS.replace("local", "locale"), name="chat-4.txt")
        check_eq("P4: words that differ by one character: a second row", (other.returncode, len(rows(root))), (0, 2))
        keys = [r["witness/details"].rsplit("idempotency:", 1)[1] for r in rows(root)]
        check("P4: with another key", len(set(keys)) == 2, str(keys))
        story2 = add_words(root, WORDS, key="change-request:TP3-2", name="chat-5.txt")
        check_eq("P5: the same words in another story: a third row (E5)", (story2.returncode, len(rows(root))), (0, 3))
        check("P5: its key carries its story", rows(root)[2]["witness/details"].endswith(
            f"idempotency:change-request:TP3-2:{digest(WORDS)}"))
    finally:
        cleanup(root)


def test_a_clash_is_refused_in_one_line_that_says_it_is_recorded() -> None:
    """P6 (E4): the same key with another essence: exit 2, one line, the old phrase first, the row named, nothing written."""
    root = temp_project("qa-factory-change-request-")
    try:
        add_words(root, WORDS)
        before = backlog_text(root)
        clash = add_words(root, WORDS, essence="Another essence for the same request")
        err = clash.stderr
        check_eq("P6: exit 3 (the finding is recorded earlier, C1-7a), exactly one stderr line, no traceback",
                 (clash.returncode, len(err.strip().splitlines()), "Traceback" in err), (3, 1, False))
        check("P6: the old phrase stays the head of the refusal",
              "idempotency key reused with different finding content" in err, err)
        check("P6: it names the recorded row and says there is nothing to do",
              "FB-1" in err and "nothing to do" in err, err)
        check("P6: it names the full key it refused", f"change-request:TP3-1:{digest(WORDS)}" in err, err)
        check_eq("P6: nothing was written", (backlog_text(root), len(rows(root))), (before, 1))
        # the echo of the recorded essence: whole AT the cap, cut with `...` BEYOND it
        cap = PD.SCOPE_SHOWN
        for label, length, cut in (("AT", cap, False), ("BEYOND", cap + 1, True)):
            sub = temp_project("qa-factory-change-request-")
            try:
                long_essence = "e" * length
                add_words(sub, WORDS, essence=long_essence)
                refused = add_words(sub, WORDS, essence="other").stderr
                shown = "e" * cap + ("..." if cut else "")
                check(f"P6: {label} {cap} characters the recorded essence is echoed "
                      f"{'cut with ...' if cut else 'whole'}", f"(essence '{shown}')" in refused, refused)
                if cut:
                    check("P6: BEYOND the cap not one more character is echoed", "e" * (cap + 1) not in refused, refused)
            finally:
                cleanup(sub)
    finally:
        cleanup(root)


def test_a_multi_line_quote_with_a_pipe_survives_a_retry() -> None:
    """P7 (E2, kills defects (a) and (b)): the scope cell is the scope given, the witness reads back as the collapsed words
    plus the marker, `|` included, and a retry of the same file is the same row. The same holds for an inline witness."""
    root = temp_project("qa-factory-change-request-")
    try:
        check_eq("P7: first call", add_words(root, WORDS).returncode, 0)
        found = rows(root)
        check_eq("P7: the scope cell is the scope given (the pipe did not shift the columns)", found[0]["scope"], SCOPE)
        check_eq("P7: the witness cell reads back as the collapsed words plus the marker, pipe included",
                 found[0]["witness/details"], f"{COLLAPSED}; idempotency:change-request:TP3-1:{digest(WORDS)}")
        check_eq("P7: the created / status / decision cells are in their columns",
                 (found[0]["status"], found[0]["decision"]), ("open", "—"))
        retry = add_words(root, WORDS)
        check_eq("P7: a retry with the same file: exit 0, one row", (retry.returncode, len(rows(root))), (0, 1))
        # defect (a): an INLINE multi-line witness, retried, is not a clash (the table turns the newline into a space)
        inline = "line one\nline two | with a pipe"
        first = add(root, "--witness", inline, key="inline-1")
        second = add(root, "--witness", inline, key="inline-1")
        check_eq("P7a: a multi-line inline witness: first call, then the retry, both exit 0",
                 (first.returncode, second.returncode), (0, 0))
        check_eq("P7a: and the retry wrote no second row", len([r for r in rows(root) if r["witness/details"].endswith(
            "; idempotency:inline-1")]), 1)
        check_eq("P7a: the inline row keeps the pipe in its witness cell",
                 [r["witness/details"] for r in rows(root) if r["witness/details"].endswith("; idempotency:inline-1")],
                 ["line one line two | with a pipe; idempotency:inline-1"])
        # defect (b): the reader splits only on an unescaped pipe
        check_eq("P7b: _cells keeps an escaped pipe inside its cell",
                 PD._cells("| a \\| b | c |"), ["a | b", "c"])
        check_eq("P7b: and still splits on a plain one", PD._cells("| a | b |"), ["a", "b"])
        check_eq("P7b: a literal backslash before a pipe round-trips",
                 PD._read_back("x\\|y"), "x\\|y")
        # G2-10 (AR-13/AR-15): the surviving reader is grammar.split_cells; the registry's reader and writer delegate to it
        import grammar as G
        for line in ("| a \\| b | c |", "| a \\||", "|", "||", "|---|---|", "| a | | c |"):
            check_eq(f"G2-10: PD._cells is grammar.split_cells on {line!r}", PD._cells(line), G.split_cells(line))
        check_eq("G2-10: a cell that ends in an escaped bar before the closing bar keeps it", PD._cells("| a \\||"), ["a |"])
        check_eq("G2-10: PD._escape is grammar.escape_cell (a bar, a line break, None)",
                 [PD._escape(v) for v in ("a|b", "a\r\nb", None)], [G.escape_cell(v) for v in ("a|b", "a\r\nb", None)])
        check_eq("G2-10: a value that ends in a bar survives the registry round trip", PD._read_back("x|"), "x|")
    finally:
        cleanup(root)


def test_the_lookup_is_end_anchored() -> None:
    """P11 / P12 (E7, E8): a key that is a prefix of another never answers for it, nor does a marker typed in a quote."""
    root = temp_project("qa-factory-change-request-")
    try:
        check_eq("P11: `launch-ab` is written", add(root, "--witness", "w1", key="launch-ab").returncode, 0)
        other = add(root, "--witness", "w2", key="launch-a", essence="a different finding")
        check_eq("P11: `launch-a` with other content is a NEW row, not a refusal", (other.returncode, len(rows(root))), (0, 2))
        again = add(root, "--witness", "w1", key="launch-ab")
        check_eq("P11: and `launch-ab` still finds its own row", (again.returncode, len(rows(root))), (0, 2))
        # P12: request A carries B's marker text inside its words
        sub = temp_project("qa-factory-change-request-")
        try:
            quoted = "please keep this; idempotency:launch-TP3-9 - it is my own note"
            check_eq("P12: request A is written", add(sub, "--witness", quoted, key="a-key").returncode, 0)
            b = add(sub, "--witness", "request B", key="launch-TP3-9", essence="request B essence")
            check_eq("P12: request B (whose key is typed inside A's words) is a new row, not a hit on A",
                     (b.returncode, len(rows(sub))), (0, 2))
        finally:
            cleanup(sub)
    finally:
        cleanup(root)


def test_a_story_less_request_and_a_direct_call() -> None:
    """P13 (E9) and the guard's direct call: the `project` form writes a row; `add_finding()` keeps its signature."""
    root = temp_project("qa-factory-change-request-")
    try:
        done = add_words(root, "Please ask less.", key="change-request:project")
        check_eq("P13: `change-request:project` writes a row", (done.returncode, len(rows(root))), (0, 1))
        check("P13: with the digest tail", rows(root)[0]["witness/details"].endswith(
            f"idempotency:change-request:project:{digest('Please ask less.')}"))
        row = PD.add_finding(root, essence="e", scope="local-urgent", witness="w", idempotency_key="guard-escalation:X:s1")
        again = PD.add_finding(root, essence="e", scope="local-urgent", witness="w", idempotency_key="guard-escalation:X:s1")
        check_eq("the guard's direct call (keyword arguments, no words file) still returns the same row twice",
                 (row["id"], again["id"], len(rows(root))), ("FB-2", "FB-2", 2))
        raised = ""
        try:
            PD.add_finding(root, essence="other", scope="local-urgent", witness="w", idempotency_key="guard-escalation:X:s1")
        except ValueError as exc:
            raised = str(exc)
        check("a direct call with other content still raises ValueError (the guard relies on it)",
              raised.startswith("idempotency key reused with different finding content"), raised)
    finally:
        cleanup(root)


def test_the_words_route_refuses_in_one_line_and_writes_nothing() -> None:
    """P9 / P10 (E14): both routes, neither, a missing / empty / whitespace-only / UTF-16 / non-UTF-8 file."""
    root = temp_project("qa-factory-change-request-")
    try:
        path = words_file(root, WORDS)
        both = add(root, "--witness", "inline", "--words-file", path)
        neither = add(root, key="change-request:TP3-1", cli=True)
        for label, done, needles in (("both", both, ("--witness", "--words-file")),
                                     ("neither", neither, ("--witness", "--words-file"))):
            check_eq(f"P9 ({label}): exit 2, one stderr line, no traceback",
                     (done.returncode, len(done.stderr.strip().splitlines()), "Traceback" in done.stderr), (2, 1, False))
            check(f"P9 ({label}): the refusal names both options", all(n in done.stderr for n in needles), done.stderr)
        missing = root / "qa-factory" / "state" / "words" / "nope.txt"
        gone = add(root, "--words-file", missing)
        check_eq("E14: a missing words file: exit 2, one line", (gone.returncode, len(gone.stderr.strip().splitlines())), (2, 1))
        check("E14: and the refusal names the path", str(missing) in gone.stderr, gone.stderr)
        for label, data in (("zero bytes", b""), ("whitespace only", b" \n\t \r\n"), ("a BOM only", b"\xef\xbb\xbf"),
                            ("UTF-16", "hello".encode("utf-16")), ("non-UTF-8 bytes", b"caf\xe9 au lait")):
            done = add(root, "--words-file", words_file(root, data, "bad.txt"))
            check_eq(f"P10 ({label}): exit 2, one line, no traceback",
                     (done.returncode, len(done.stderr.strip().splitlines()), "Traceback" in done.stderr), (2, 1, False))
            check(f"P10 ({label}): the refusal names --words-file", "--words-file" in done.stderr, done.stderr)
        check_eq("P9/P10: nothing was written by any refusal", (rows(root), backlog_text(root)), ([], ""))
        # the empty file is never the digest of the empty string
        empty = digest("")
        check("P10: no row carries the digest of the empty string", empty not in backlog_text(root))
        # an empty key on the words route is still the old 'required' refusal, not the key ':<digest>'
        blank = add(root, "--words-file", path, key="  ")
        check_eq("an empty key with a words file: exit 2, the 'required' refusal, nothing written",
                 (blank.returncode, "idempotency_key are required" in blank.stderr, rows(root)), (2, True, []))
    finally:
        cleanup(root)


def test_control_bytes_and_non_ascii_words() -> None:
    """E1 / FR-29 / E15: control characters collapse to a space in the row; Cyrillic words are written whole."""
    root = temp_project("qa-factory-change-request-")
    try:
        done = add_words(root, "stop\x07asking\x1b[31m me\x0bnow\x7f.")
        check_eq("control bytes in the words: the row is written", (done.returncode, len(rows(root))), (0, 1))
        cell = rows(root)[0]["witness/details"]
        check("no control byte is left in the row", not any(ord(c) < 32 or 0x7f <= ord(c) <= 0x9f for c in
                                                            backlog_text(root).replace("\n", "")), repr(cell))
        check("the words survive as words, each control character a space",
              cell.startswith("stop asking [31m me now ."), repr(cell))
        # built from hex: the package carries no Cyrillic character in its text (FR-30); two Russian lines, one with a pipe
        cyr = bytes.fromhex("d09dd0b520d181d0bfd180d0b0d188d0b8d0b2d0b0d0b9207c20d0bad0b0d0b6d0b4d18bd0b920d180d0b0d0b7"
                            "2e0ad09ed0b4d0b8d0bd20d180d0b0d0b72e").decode("utf-8")
        done = add_words(root, cyr, key="change-request:TP3-2", name="ru.txt", cli=True)
        check_eq("Cyrillic words: exit 0", done.returncode, 0)
        check_eq("Cyrillic words: the row holds them whole on one line",
                 rows(root)[1]["witness/details"], f"{' '.join(cyr.split())}; idempotency:change-request:TP3-2:{digest(cyr)}")
        check("Cyrillic words: the CLI printed them without a traceback", "Traceback" not in done.stderr, done.stderr)
    finally:
        cleanup(root)


def test_a_busy_registry_is_a_one_line_refusal() -> None:
    """E16: the lock held by another writer: one line, exit 2, the retry is safe (it is idempotent)."""
    root = temp_project("qa-factory-change-request-")
    try:
        path = words_file(root, WORDS)
        import event_store as ES
        lock_file = root / "qa-factory" / "state" / "project-decisions.lock"
        real = PD.lock
        PD.lock = lambda r, timeout=0.2: real(r, timeout)
        argv, err, code = sys.argv, io.StringIO(), None
        sys.argv = ["project_decisions.py", "--root", str(root), "add-finding", "--essence", ESSENCE, "--scope", SCOPE,
                    "--words-file", str(path), "--idempotency-key", "change-request:TP3-1"]
        holder = ES.take_file_lock(lock_file, 0.0, record_holder=True)          # another handle holds the OS lock (a second handle in one process is busy)
        try:
            with contextlib.redirect_stderr(err):
                try:
                    PD.main()
                except SystemExit as exc:
                    code = exc.code
        finally:
            sys.argv = argv
            PD.lock = real
        text = err.getvalue()
        check_eq("E16: exit 2, exactly one line, no traceback", (code, len(text.strip().splitlines()), "Traceback" in text),
                 (2, 1, False))
        check("E16: the line says the registry is busy and to run the same command again",
              "the registry is busy" in text and "run the same command again" in text, text)
        check("E16: the busy line carries the holder clause the lock recorded (F6)", "held by process" in text.lower(), text)
        holder.release()
        check_eq("E16: the retry after the lock is free writes the row", (add_words(root, WORDS).returncode, len(rows(root))), (0, 1))
    finally:
        cleanup(root)


def test_a_broken_lock_never_says_another_writer() -> None:
    """F6 (t-2196): a folder at the lock path cannot be locked: the LockBroken sentence is printed, never 'another writer' or
    'run the same command again' (a retry cannot help). NEGATIVE control: a TimeoutError with no cause keeps today's busy line."""
    root = temp_project("qa-factory-change-request-")
    try:
        path = words_file(root, WORDS)
        (root / "qa-factory" / "state" / "project-decisions.lock").mkdir(parents=True)
        real = PD.lock
        PD.lock = lambda r, timeout=0.2: real(r, timeout)
        argv, err, code = sys.argv, io.StringIO(), None
        sys.argv = ["project_decisions.py", "--root", str(root), "add-finding", "--essence", ESSENCE, "--scope", SCOPE,
                    "--words-file", str(path), "--idempotency-key", "change-request:TP3-1"]
        try:
            with contextlib.redirect_stderr(err):
                try:
                    PD.main()
                except SystemExit as exc:
                    code = exc.code
        finally:
            sys.argv = argv
            PD.lock = real
        text = err.getvalue()
        check_eq("F6: exit 2, one line, no traceback", (code, len(text.strip().splitlines()), "Traceback" in text), (2, 1, False))
        check("F6: the LockBroken sentence is printed", "cannot be locked" in text, text)
        check("F6: no busy head and no retry advice", "the registry is busy" not in text and "run the same command again" not in text, text)
        check_eq("F6: a TimeoutError with no cause keeps the busy line",
                 PD._registry_busy_line("add-finding", TimeoutError("x")),
                 "project_decisions: add-finding refused - the registry is busy (another writer); run the same command again")
    finally:
        cleanup(root)


def test_an_inline_change_request_is_refused_with_its_door() -> None:
    """P17 (F-2, t-974 L-6): a `change-request` key with `--witness` is refused (one line, exit 2, the door `--words-file`,
    nothing written), so the same words by the two routes are never two rows and two different inline requests are never
    answered 'nothing to do'. NEGATIVE controls: any other key class inline passes as before; the words route passes."""
    root = temp_project("qa-factory-change-request-")
    try:
        first = add(root, "--witness", "stop asking me which stand", key="change-request:T")
        second = add(root, "--witness", "a completely different request", key="change-request:T", essence="another essence")
        for label, done in (("first", first), ("second", second)):
            err = done.stderr
            check_eq(f"P17 ({label}): exit 2, exactly one stderr line, no traceback",
                     (done.returncode, len(err.strip().splitlines()), "Traceback" in err), (2, 1, False))
            check(f"P17 ({label}): it says what is wrong (the words came inline) and the door (--words-file <file>)",
                  "inline" in err and "--words-file <file>" in err and "change-request:T" in err, err)
            check(f"P17 ({label}): never the 'nothing to do' of a recorded finding", "nothing to do" not in err, err)
        check_eq("P17: nothing was written by either refusal", (rows(root), backlog_text(root)), ([], ""))
        for label, key in (("case and blanks", "  Change-Request:T "), ("no colon", "change-request")):
            done = add(root, "--witness", "w", key=key)
            check_eq(f"P17 ({label}): the class is read through blanks and case: refused, nothing written",
                     (done.returncode, rows(root)), (2, []))
        # the same words by the words route: one row; the inline route has no second row to add
        check_eq("P17: the words route with the same key is unchanged", add_words(root, WORDS, key="change-request:T").returncode, 0)
        check_eq("P17: and the inline retry of the same words is still refused: one row",
                 (add(root, "--witness", COLLAPSED, key="change-request:T").returncode, len(rows(root))), (2, 1))
        # NEGATIVE control: other classes inline are unchanged (the class is the prefix before the FIRST colon)
        for key in ("launch-a", "change-requests:T", "x:change-request", "guard-escalation:X:s1"):
            done = add(root, "--witness", f"w for {key}", key=key)
            check_eq(f"P17 NEGATIVE: the key {key!r} inline passes as before", done.returncode, 0)
    finally:
        cleanup(root)


def test_every_line_break_is_one_space_in_a_row() -> None:
    """P18 (m-1): `_escape` folds CRLF, a lone CR and the other `splitlines` separators like LF, so an inline witness with
    any of them is one row, the retry is the same finding, and the next write keeps its marker."""
    check_eq("P18: CRLF is one space, like LF", (PD._escape("a\r\nb"), PD._escape("a\nb")), ("a b", "a b"))
    check_eq("P18: a lone CR, VT, FF, NEL and the two Unicode separators are a space each",
             PD._escape("a\rb\x0bc\x0cd\x85e" + chr(0x2028) + "f" + chr(0x2029) + "g"), "a b c d e f g")
    root = temp_project("qa-factory-change-request-")
    try:
        for index, raw in enumerate(("line1\rline2", "line1\r\nline2", "line1" + chr(0x2028) + "line2")):
            key = f"kcr-{index}"
            first, retry = (add(root, "--witness", raw, key=key) for _ in range(2))
            check_eq(f"P18 ({index}): the first call and its retry exit 0", (first.returncode, retry.returncode), (0, 0))
            mine = [r["witness/details"] for r in rows(root) if r["witness/details"].endswith("; idempotency:" + key)]
            check_eq(f"P18 ({index}): one row, the break a space, the marker intact", mine,
                     [f"line1 line2; idempotency:{key}"])
        add(root, "--witness", "another", key="kcr-next")
        check_eq("P18: after one more write the earlier rows still hold their markers",
                 [r["witness/details"].rsplit("; ", 1)[1] for r in rows(root)],
                 ["idempotency:kcr-0", "idempotency:kcr-1", "idempotency:kcr-2", "idempotency:kcr-next"])
    finally:
        cleanup(root)


def test_the_digest_is_over_the_text_after_the_control_collapse() -> None:
    """P19 (m-2): the spec formula `" ".join(text.split())` applied to the text AFTER control characters became spaces.
    Declared behaviour: `stop<BEL>asking` and `stop asking` are one request (one row, one key)."""
    check_eq("P19: the digest of the BEL words is the spec formula over `stop asking`",
             PD.words_digest("stop\x07asking"), digest("stop asking"))
    check("P19: and NOT the spec formula over the raw text (the declared deviation)",
          PD.words_digest("stop\x07asking") != digest("stop\x07asking"))
    root = temp_project("qa-factory-change-request-")
    try:
        a = add_words(root, "stop\x07asking", name="bel.txt")
        b = add_words(root, "stop asking", name="plain.txt")
        check_eq("P19: the two texts are one request: exit 0 both, one row", (a.returncode, b.returncode, len(rows(root))), (0, 0, 1))
        check("P19: its key ends with the digest of `stop asking`",
              rows(root)[0]["witness/details"].endswith(f"idempotency:change-request:TP3-1:{digest('stop asking')}"))
    finally:
        cleanup(root)


def test_the_audit_reads_the_registry_through_the_writers_reader() -> None:
    """P20 (F-1, t-974 L-2 M7): `audit_factory.deferred_rows_without_a_question` reads a row of the writer's table through
    `project_decisions._cells`: a `|` escaped in a cell does not shift the `asked` column. Both directions are pinned: an
    escaped pipe in front of a real question is no violation, and in front of a placeholder it is still reported (the
    naive split read the word after the pipe as the question and accepted it)."""
    import audit_factory as A
    root = temp_project("qa-factory-change-request-")
    try:
        backlog = root / "qa-factory" / "factory-backlog.md"
        backlog.parent.mkdir(parents=True, exist_ok=True)

        def table(*rows_):      # the writer's own output for these rows
            return PD._replace_table("# Findings about the factory itself\n", [dict(zip(PD.HEADER, r)) for r in rows_])

        def row(ident, essence, asked):
            return [ident, essence, asked, "manual", "2026-10-20", "open", "-"]

        backlog.write_text(table(row("DD-1", "App repo is a | b", "batch 1: where is the repo?")), encoding="utf-8")
        check("P20: the writer escaped the pipe (the input is what it claims)", "a \\| b" in backlog.read_text(encoding="utf-8"))
        check_eq("P20: an escaped pipe before a real question is no violation", A.deferred_rows_without_a_question(backlog), [])
        backlog.write_text(table(row("DD-2", "Stand is a | b", "-")), encoding="utf-8")
        found = A.deferred_rows_without_a_question(backlog)
        check_eq("P20: an escaped pipe before a placeholder `asked` is reported, once, by its row",
                 (len(found), "DD-2" in " ".join(found)), (1, True))
        # a row with fewer cells than the header: the reader's existing behaviour, named - the missing `asked` is empty, so reported
        short = backlog.read_text(encoding="utf-8").rstrip("\n") + "\n| DD-3 | only an essence |\n"
        backlog.write_text(short, encoding="utf-8")
        found = A.deferred_rows_without_a_question(backlog)
        check_eq("P20: a short row (fewer cells than the header) has an empty `asked` and is reported with the other one",
                 (len(found), [ident for ident in ("DD-2", "DD-3") if any(ident in m for m in found)]),
                 (2, ["DD-2", "DD-3"]))
    finally:
        cleanup(root)


def test_main_stays_short_and_the_cut_is_written_once() -> None:
    """P21 (m-4, m-5): `main()` is under 60 lines (the add-finding words resolve in a helper), and the `SCOPE_SHOWN` cut
    is written in ONE place (`_shown`), not once per refusal."""
    import ast
    source = Path(PD.__file__).read_text(encoding="utf-8")
    funcs = {node.name: node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)}
    length = funcs["main"].end_lineno - funcs["main"].lineno + 1
    check("P21: main() is under 60 lines", length < 60, f"{length} lines")
    check("P21: the words resolve in the helper `_finding_words`", "_finding_words" in funcs)
    check_eq("P21: the cut `[:SCOPE_SHOWN]` is written once in the file", source.count("[:SCOPE_SHOWN]"), 1)
    check("P21: and it sits in `_shown`", "[:SCOPE_SHOWN]" in ast.get_source_segment(source, funcs["_shown"]))


def test_help_names_the_words_file() -> None:
    """P16: `add-finding --help` names `--words-file`."""
    helped = run_script("project_decisions.py", "add-finding", "--help")
    check_eq("P16: --help exits 0", helped.returncode, 0)
    check("P16: and names --words-file", "--words-file" in helped.stdout, helped.stdout)


# --- P14: the carrier sentences (t-1111 4b, A1-A6), each with a negative control ------------------------------------------

CONDUCTOR = PLUGIN_ROOT / "references" / "conductor.md"
COMMON = PLUGIN_ROOT / "references" / "common-rules.md"

A1 = ("A person's request to change the factory, whatever else you do: `--words-file <file>` for `--witness`, key "
      "`change-request:<T>`; an answer the code recorded without showing you leaves no finding.")
A2 = ("At a gate you record nothing but a request to change the factory (not a story change): offer `approve` or a move; "
      "the code records.")
A3 = ("- Never edit application code, a test, a manifest or a file under the plugin root; a broken artifact goes back to its "
      "author through `rework`.")
A4_ABSENT = ("Never edit files under the plugin root.", "write the question by `references/human-questions.md`.",
             "The file holds their words verbatim;")
A5 = ("A person's words asking to change the factory are a finding, never a plugin edit; you record one only where your own "
      "steps say so.")
A6_PRESENT = "(never silently skipped or worked around — see `environments.md`)"
A6_ABSENT = "responsibility to escalate, not to work around"


def norm(text: str) -> str:
    return " ".join(text.split())


def has(path: Path, needle: str) -> bool:
    """The checker every key goes through: whitespace-collapsed substring."""
    return norm(needle) in norm(path.read_text(encoding="utf-8"))


def row_has(path: Path, row_start: str, needle: str) -> bool:
    row = next((line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith(row_start)), "")
    return norm(needle) in norm(row)


def bullet_has(path: Path, bullet_start: str, needle: str) -> bool:
    """The `- **...**` bullet that starts with `bullet_start` (its lines run to the next `- ` bullet or blank line)."""
    out, inside = [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(bullet_start):
            inside = True
        elif inside and (line.startswith("- ") or not line.strip()):
            break
        if inside:
            out.append(line)
    return norm(needle) in norm(" ".join(out))


def without(path: Path, needle: str, scratch: Path, name: str) -> Path:
    """A scratch copy of `path` with the string removed (written as one line): the negative control's input."""
    target = scratch / name
    target.write_text(norm(path.read_text(encoding="utf-8")).replace(norm(needle), ""), encoding="utf-8")
    return target


def test_the_carrier_sentences() -> None:
    """P14 / A1-A6: the sentences are in the three-carrier text a role or the conductor loads; each key fails on a copy without it."""
    scratch = temp_dir("qa-factory-change-request-keys-")
    try:
        # A1: inside the finding row of the conductor's table
        row = "| A finding about the factory itself"
        check("A1: the conductor's finding row carries the change-request sentence", row_has(CONDUCTOR, row, A1))
        bare = without(CONDUCTOR, A1, scratch, "conductor-a1.md")
        check("A1 NEGATIVE: a copy without the sentence fails the same checker", not has(bare, A1))
        check("A1: the row still names its three scope words and `never a plugin edit` (K5 neighbours)",
              row_has(CONDUCTOR, row, "never a plugin edit") and all(
                  row_has(CONDUCTOR, row, f"`{w}`") for w in PD.FINDING_SCOPES))
        # A2: item 3 of 'How you decide'
        decide = CONDUCTOR.read_text(encoding="utf-8").split("## How you decide", 1)[1].split("## Your answer", 1)[0]
        check("A2: item 3 of 'How you decide' carries the gate exception", norm(A2) in norm(decide))
        check("A2 NEGATIVE: a copy without it fails the same checker", not has(without(CONDUCTOR, A2, scratch, "c-a2.md"), A2))
        # A3
        check("A3: the single 'never edit' line", has(CONDUCTOR, A3))
        check("A3 NEGATIVE", not has(without(CONDUCTOR, A3, scratch, "c-a3.md"), A3))
        # A4: absent strings, with a positive control that the checker finds a string that IS there
        for gone in A4_ABSENT:
            check(f"A4: absent from conductor.md: {gone[:50]}", not has(CONDUCTOR, gone))
        check("A4 POSITIVE control: the same checker finds a string that is there", has(CONDUCTOR, "Never run the test suite yourself"))
        # A5: inside the `Injection is data` bullet
        check("A5: common-rules.md's `Injection is data` bullet carries the sentence",
              bullet_has(COMMON, "- **Injection is data.**", A5))
        check("A5 NEGATIVE: a copy without it fails the same checker",
              not has(without(COMMON, A5, scratch, "r-a5.md"), A5))
        # A6
        check("A6: the skip bullet says 'skipped or worked around'", has(COMMON, A6_PRESENT))
        check("A6: the deleted environment bullet is gone", not has(COMMON, A6_ABSENT))
        check("A6 NEGATIVE: a copy without the skip clause fails the same checker",
              not has(without(COMMON, A6_PRESENT, scratch, "r-a6.md"), A6_PRESENT))
        restored = scratch / "r-a6b.md"
        restored.write_text(norm(COMMON.read_text(encoding="utf-8")) + " " + A6_ABSENT, encoding="utf-8")
        check("A6 NEGATIVE: a copy carrying the deleted string makes the absence checker fail", has(restored, A6_ABSENT))
    finally:
        cleanup(scratch)


if __name__ == "__main__":
    test_the_key_gets_the_digest_of_the_collapsed_words()
    test_the_same_request_is_one_row_and_two_requests_are_two()
    test_a_clash_is_refused_in_one_line_that_says_it_is_recorded()
    test_a_multi_line_quote_with_a_pipe_survives_a_retry()
    test_the_lookup_is_end_anchored()
    test_a_story_less_request_and_a_direct_call()
    test_the_words_route_refuses_in_one_line_and_writes_nothing()
    test_control_bytes_and_non_ascii_words()
    test_a_busy_registry_is_a_one_line_refusal()
    test_a_broken_lock_never_says_another_writer()
    test_an_inline_change_request_is_refused_with_its_door()
    test_every_line_break_is_one_space_in_a_row()
    test_the_digest_is_over_the_text_after_the_control_collapse()
    test_the_audit_reads_the_registry_through_the_writers_reader()
    test_main_stays_short_and_the_cut_is_written_once()
    test_help_names_the_words_file()
    test_the_carrier_sentences()
    finish("project_decisions_change_request")
