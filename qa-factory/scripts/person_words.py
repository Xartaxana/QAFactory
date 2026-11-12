"""One reader for a person's words that come from a file: `--words-file <path>`.

Every command that records a person's words took them only as a command-line argument. On a
Windows shell route cmd.exe stops reading the command line at the first line break, before any
launcher runs, and quotes can be mangled - silently. At gate B of TP2-2406 a three-
paragraph instruction was recorded as its first paragraph: "local only, do not publish" was lost
from the receipt (defect M30). A file carries the text whole, so the commands below take the words
from one, through this one reader (factory rule FR-17: a tool made for a problem is wired at every
site that has the problem):

    controller.py --operation gate-decision | release      (--words)
    waiver.py                                              (--decision, and --text for --remark)
    archive_task.py                                        (--note)
    project_decisions.py resolve                           (--decision)
    project_decisions.py add-finding                       (--witness)

    words = person_words.read(args.words, args.words_file, "--words")

* `path` given: the file is read as BYTES and decoded as `utf-8-sig`, strictly. The text comes back
  as written - only a BOM is removed, CRLF stays CRLF, nothing is stripped. Each CLI keeps its own
  treatment of the value (the controller stores words as given, waiver strips): the reader never
  decides what the words are worth. An empty file, a BOM-only file and a whitespace-only file are
  refused (below): a named file with no words is never recorded, whatever the CLI does with an
  empty inline value.
* The reader refuses, each time naming the option and the way to satisfy it (FR-1), and the caller
  has recorded nothing yet: both options at once; a path that is missing, is a directory or cannot
  be read; a file with no words in it; bytes that are not UTF-8 - a UTF-16 file (what Windows PowerShell 5.1 `>` writes) or any
  invalid sequence - are never decoded with replacement, which would store a different text than
  the person's.
* Inline words while `run_py_entry.VIA_CMD` is true are refused. The cmd route cannot carry a line
  break, so the words would be recorded cut, and even a one-line text cannot be told from a cut
  one; a silent truncation becomes a refusal (FR-4). By plain python (a list argv, no cmd) inline
  words keep working as before. An empty inline value is not words: it comes back for the CLI's own
  empty refusal.
* No size limit, no stdin route.

The refusal is `WordsRefused`, a `ValueError`, so a CLI that already turns `ValueError` into its
exit-2 answer (controller.py) needs no new handler. Callers resolve the words ONCE, at argument
handling, before they read or write any state: a refusal leaves no event, no override, no file.
The file lives where the orchestrator wrote it (`<story folder>/state/words/<name>.txt`); this
module never deletes or rewrites it.

This module is also the ONE writer of that folder (`words_file_path` and `write_words`, below): the
driver's copy of an answer and the copy `story_step.py decide` makes of a file outside the story are
the same code, so no second place builds the path of `state/words` or writes into it.
"""
import os
import re
import time
from pathlib import Path

OPTION = "--words-file"
# The clause that goes after a printed `waiver.py ... --block "<part of the line>"` door: the part a person types is held against
# the refused line by whole words (`contract.names_whole`), so a cut inside a word is refused. One text, every door (GW1-1 G-3).
WHOLE_PART = "(the part is whole words of the line, never a cut inside a word)"


class WordsRefused(ValueError):
    """The person's words cannot be taken as given; the text says what to do instead."""


def via_cmd() -> bool:
    """True when this process was started by the cmd half of hooks/run-py.cmd."""
    try:
        import run_py_entry
    except ImportError:
        return False
    return bool(getattr(run_py_entry, "VIA_CMD", False))


def _not_utf8(path: str, option: str = OPTION) -> WordsRefused:
    return WordsRefused(
        f"{option} {path} is not UTF-8 text (a Windows PowerShell 5.1 `>` redirect writes "
        f"UTF-16). Save the file as UTF-8 and pass it again; nothing was recorded.")


def _from_file(path: str, option: str = OPTION) -> str:
    try:
        with open(path, "rb") as stream:
            raw = stream.read()
    except FileNotFoundError:
        raise WordsRefused(
            f"{option} {path}: no such file. Write the person's words to it exactly as they "
            f"were given (the orchestrator keeps them in <story folder>/state/words/<name>.txt) "
            f"and pass that path.") from None
    except IsADirectoryError:
        raise WordsRefused(f"{option} {path} is a directory. Pass the file that holds the "
                           f"person's words.") from None
    except PermissionError as exc:
        if os.path.isdir(path):  # Windows reports opening a directory as a permission error
            raise WordsRefused(f"{option} {path} is a directory. Pass the file that holds the "
                               f"person's words.") from None
        raise WordsRefused(f"{option} {path} cannot be read ({exc.strerror or exc}). Write the "
                           f"person's words to a file this command may read and pass it.") from None
    except OSError as exc:
        raise WordsRefused(f"{option} {path} cannot be read ({exc.strerror or exc}). Write the "
                           f"person's words to a file this command may read and pass it.") from None
    # UTF-16 text has a NUL byte next to every ASCII letter: it can pass UTF-8 decoding with no
    # BOM at all, so the NUL is checked on its own. A person's words never carry one.
    if b"\x00" in raw:
        raise _not_utf8(path, option)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise _not_utf8(path, option) from None
    # A file that was NAMED and holds no words (zero bytes, a BOM only, only whitespace) is a
    # file nobody wrote the words into: refused here, for every CLI, so none records an empty
    # decision. Only "all whitespace" is looked at; a text with blank lines around words is
    # returned untouched.
    if not text.strip():
        raise WordsRefused(f"{option} {path} is empty. Write the person's words to it exactly as "
                           f"they were given and pass it again; nothing was recorded.")
    return text


def door(command: str, for_person: bool = False, path: str = "") -> str:
    """The recording command a refusal prints, with the person's words by file: the one renderer.

    About 45 refusals and hints still told the orchestrator to pass a person's words inline
    (`--decision "<their words>"`), the form that cmd.exe cuts at the first line break (M30).
    Every such door is built here, so the file form is one text and a detector can hold it
    (test_words_doors.py). `command` is the whole command up to the words part, block quoting and
    all: it is returned unchanged, with the option appended, so a recorded `--block` keyword that
    names its line by whole words (`contract.names_whole`, GW1-1) keeps matching. `for_person=True` is the form a person reads (a gate
    packet, an owner remedy): the placeholder says what goes in the file. `path`: the file the words
    ARE in already (the answer file a driver prompt hands the conductor), put in place of the
    placeholder - the option text stays this one; an empty `path` keeps the placeholder."""
    text = str(command if command is not None else "").rstrip()
    if not text.strip():
        raise ValueError("person_words.door needs the command the words are recorded with")
    if str(path or "").strip():
        return f"{text} {OPTION} {str(path).strip()}"
    return f"{text} {OPTION} " + ("<file with your words>" if for_person else "<file>")


def read(inline, path, flag, file_flag=OPTION):
    """The person's words: from `path` when given, else the inline value as it came.

    `flag` is the inline option's own name (`--words`, `--decision`, `--text`, `--note`) and only
    shapes the refusals; `file_flag` is the name of the file option the caller really has
    (`--risks-file`, `--reason-file`; default `--words-file`), so a refusal never names a flag the
    caller does not take (F-9). Returns None when neither was given, so a caller's own "required"
    check behaves exactly as it did before this option existed."""
    if path is not None:
        if inline is not None:
            raise WordsRefused(f"{flag} and {file_flag} both carry the person's words. Give exactly "
                               f"one: {flag} for a single line typed by code, or {file_flag} <path> "
                               f"for their words as they were given.")
        return _from_file(path, file_flag)
    if inline is not None and str(inline).strip() and via_cmd():
        raise WordsRefused(
            f"{flag} cannot carry the person's words through run-py.cmd: cmd.exe cuts a command "
            f"line at the first line break, so the words would be recorded cut, and a short text "
            f"cannot be told from a cut one. Nothing was recorded. Write their words exactly as "
            f"they were given to a file and pass {file_flag} <path>.")
    return inline


def words_file_path(task_root, dispatch_id, kind) -> Path:
    """The base of a words file's path, `<task root>/state/words/driver-<kind>[-<dispatch id>]`, no extension.

    Pure: it builds a path and touches nothing. `kind` is a gate or stage word (`gateA`, `s1review`,
    `decidehand`), reduced to letters and digits; `dispatch_id` (empty for the driver's own answers)
    joins the base with its non-alphanumerics folded to `-`. The ONE place that builds the path of
    `state/words` (the driver's `Driver.words_file` and `story_step.py decide` both come through
    `write_words`)."""
    name = "driver-" + re.sub(r"[^A-Za-z0-9]+", "", str(kind or ""))
    ident = re.sub(r"[^A-Za-z0-9]+", "-", str(dispatch_id or "")).strip("-")
    return Path(task_root) / "state" / "words" / (name + ("-" + ident if ident else ""))


def write_words(task_root, dispatch_id, kind, text):
    """Put a person's words in a file, exactly as given; the path, or None when there are no words.

    `<base>-<millisecond stamp>[-<n>].txt` (base: `words_file_path`): UTF-8, no BOM, line breaks as
    given (`newline=""`), created with "x" so a name that exists is never overwritten. Empty or
    whitespace-only words write nothing and return None. A write that fails (no folder, a full disk)
    removes the half-written file and raises `OSError`: the caller says what stopped and records
    nothing - the words are never put on a command line instead (that is the road that cuts them)."""
    if not str(text or "").strip():
        return None
    base = words_file_path(task_root, dispatch_id, kind)
    stem = base.name + "-" + str(int(time.time() * 1000))
    path, made = base.parent / (stem + ".txt"), None
    try:
        base.parent.mkdir(parents=True, exist_ok=True)
        for number in range(1, 1000):
            try:
                with open(path, "x", encoding="utf-8", newline="") as stream:
                    made = path
                    stream.write(text)
            except FileExistsError:
                path = base.parent / f"{stem}-{number}.txt"
                continue
            return path
        raise OSError("no unused file name")
    except OSError:
        if made is not None:
            try:
                made.unlink()                   # half a text must not stand as the person's words
            except OSError:
                pass
        raise
