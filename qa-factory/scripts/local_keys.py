"""The key of a story no tracker holds (SS1-14): `LOCAL-<n>`, the text it was given, and the ONE question "is this story local?".

A person has a text and no ticket (the CART-1 run: `ADD-TO-CART`, a name nobody could use as a key). The factory then
makes the key itself: `ticket_adapter.py local-key --words-file <file>` stores the text as
`qa-factory/local-tickets/<KEY>.md` byte for byte and prints the key. The key's shape is DATA, `ticket.local` in
`references/adapter-forms.json`, read through `adapter_forms` (AR-1); nothing here spells it.

  is_local(key, root)      THE reader of "is this story local?" (AR-13): the key LOOKS local AND its text file exists, OR
                           the story's snapshot says `provenance.local_key: true` (a story whose text file was lost keeps
                           being local: it must never go and ask a tracker for a ticket that is somebody else's).
  ticket_path(key, root)   where the text lives.
  mint(text, cfg, root)    the next key and its file; a number is never given twice.

The error direction of `is_local` (it gates a trip to the tracker): a FALSE answer for a local story is allowed (the tracker
answers 404 and the ordinary question follows); a TRUE answer for a real tracker key is forbidden (its requirements would be
read from nowhere). So: exact spelling (`fullmatch`, ASCII digits, the file name found in the folder LISTING, so a
case-blind file system does not turn `local-1.md` into `LOCAL-1`), and ANY exception is False (AR-28).

Stdlib plus `adapter_forms` and `hooklib`.
"""
import json
import os
import re
from pathlib import Path

import adapter_forms as AF
import hooklib

TEXT_DIR = ("qa-factory", "local-tickets")
SNAPSHOT_NAME = "ticket-snapshot.json"
SUPERSEDED = "superseded"
MINT_ATTEMPTS = 100          # numbers tried after the first free one was found busy (two sessions racing for it)
EXIT_USAGE, EXIT_FACTORY = 2, 4


class MintRefused(ValueError):
    """`mint` did not give a key. `code` is the exit the CLI uses (2: the call's fault, 4: the factory's own); `str(exc)` is
    the finished text (what is wrong, what was expected, the door: FR-1)."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def _project(root) -> Path:
    return Path(root).resolve() if root is not None else hooklib.project_root().resolve()


def _text_dir(project: Path) -> Path:
    return project.joinpath(*TEXT_DIR)


def ticket_path(key, root=None) -> Path:
    """`<project>/qa-factory/local-tickets/<KEY>.md`. A value that is not a local key (`../../README`) never builds a path."""
    if not AF.is_local_form(key):
        raise ValueError(f"{key!r} is not a local key, so it names no text file")
    return _text_dir(_project(root)) / f"{key}.md"


def _file_exists(key: str, project: Path) -> bool:
    """The text file by its EXACT name, from the folder listing (a case-blind file system finds `local-1.md` for `LOCAL-1`)."""
    try:
        return f"{key}.md" in os.listdir(_text_dir(project)) and (_text_dir(project) / f"{key}.md").is_file()
    except OSError:
        return False


def _marked(key: str, project: Path) -> bool:
    """Does the story's snapshot carry `provenance.local_key: true` (the JSON true, not the word "true" or "yes")?"""
    parent = hooklib.artifact_root(root=project)
    if not hooklib.is_story_folder(parent, key):
        return False
    data = json.loads((parent / key / "work" / SNAPSHOT_NAME).read_text(encoding="utf-8-sig"))
    provenance = data.get("provenance") if isinstance(data, dict) else None
    return isinstance(provenance, dict) and provenance.get("local_key") is True


def is_local(key, root=None) -> bool:
    """Is this story local? See the module text. Never raises: any exception is False."""
    try:
        if not AF.is_local_form(key):
            return False
        project = _project(root)
        if _file_exists(key, project):
            return True
        return _marked(key, project)
    except Exception:  # noqa: BLE001 - the allowed error is "go to the tracker, which answers 404" (AR-28)
        return False


def _local_row():
    try:
        row = AF.load_table().local
    except AF.FormsTableError as exc:
        raise MintRefused(EXIT_FACTORY, str(exc)) from None
    if not row:
        raise MintRefused(EXIT_FACTORY, "references/adapter-forms.json has no `ticket.local` row, so the factory cannot make a "
                                        "key; restore references/adapter-forms.json from the plugin package")
    return row


def _prefix_of(example: str) -> str:
    """`LOCAL-` of `LOCAL-1`: the example without its trailing number."""
    return re.sub(r"\d+$", "", example)


def _numbers(names, key_pattern: str) -> list:
    """The numbers of the names that BEGIN with a local key (case-blind: on Windows `local-1` is `LOCAL-1`)."""
    found = []
    for name in names:
        match = re.match(key_pattern, str(name), re.IGNORECASE | re.ASCII)
        if match:
            digits = re.search(r"(\d+)$", match.group(0))
            if digits:
                found.append(int(digits.group(1)))
    return found


def _listing(folder: Path) -> list:
    try:
        return os.listdir(folder)
    except OSError:
        return []


def _taken(project: Path, cfg, key_pattern: str) -> int:
    """The highest number already in use anywhere a key of this shape lives: the text files, the story folders (a folder
    without `pipeline.json` takes a number too), `superseded/` inside the artifacts folder, a `file` tracker's folder."""
    names = list(_listing(_text_dir(project)))
    try:
        artifacts = hooklib.artifact_root(root=project)
    except (OSError, ValueError):
        artifacts = project / "qa-factory" / "artifacts"
    names += _listing(artifacts) + _listing(artifacts / SUPERSEDED)
    row = ((cfg or {}).get("adapters") or {}).get("ticket") if isinstance(cfg, dict) else None
    if isinstance(row, dict) and AF.ticket_kind(cfg) == "file" and str(row.get("path") or "").strip():
        base = Path(str(row["path"]))
        names += _listing(base if base.is_absolute() else project / base)
    return max(_numbers(names, key_pattern), default=0)


def _tracker_has_the_prefix(cfg, prefix: str) -> bool:
    row = ((cfg or {}).get("adapters") or {}).get("ticket") if isinstance(cfg, dict) else None
    keys = row.get("project_keys") if isinstance(row, dict) else None
    return isinstance(keys, list) and any(isinstance(k, str) and k.strip().casefold() == prefix for k in keys)


def mint(text, cfg, root=None) -> tuple:
    """(key, relative path of its text file). The text is stored byte for byte (UTF-8, no line-break translation). The file is
    created with `O_EXCL`, so two sessions never get one number; a busy number moves to the next, at most `MINT_ATTEMPTS`
    times. Refused (`MintRefused`): no text (2), the tracker has a project of this prefix (2), no `ticket.local` row (4), every
    attempted number busy (4)."""
    if not isinstance(text, str) or not text.strip():
        raise MintRefused(EXIT_USAGE, "the local key is given with the story's text; none was given: put the story's text in "
                                      "a file and pass --words-file <that file>")
    row = _local_row()
    prefix = _prefix_of(row["example"])
    word = prefix.rstrip("-")
    if _tracker_has_the_prefix(cfg, word.casefold()):
        raise MintRefused(EXIT_USAGE, f"this project's tracker has a project {word}, so {prefix}<n> would name its tickets: "
                                      "create a ticket there and start the story with its key and --ticket-file <your text>")
    project = _project(root)
    folder = _text_dir(project)
    folder.mkdir(parents=True, exist_ok=True)
    first = _taken(project, cfg, row["key"]) + 1
    for number in range(first, first + MINT_ATTEMPTS):
        key = f"{prefix}{number}"
        path = folder / f"{key}.md"
        try:
            handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o666)
        except FileExistsError:
            continue
        try:
            with os.fdopen(handle, "wb") as out:
                out.write(text.encode("utf-8"))
        except BaseException:
            path.unlink(missing_ok=True)       # no half-made key: the number is free again
            raise
        return key, "/".join(TEXT_DIR) + f"/{key}.md"
    raise MintRefused(EXIT_FACTORY, f"{MINT_ATTEMPTS} numbers after {prefix}{first - 1} were all taken at the same moment in "
                                    f"{'/'.join(TEXT_DIR)}: another session is making keys there; run the command again")
