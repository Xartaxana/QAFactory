"""Keep machine-local qa-factory state out of the project's git history.

Onboarding wrote only one `.gitignore` line (`qa-factory/artifacts/*/work/evidence/`) and
never touched `qa-factory/state/`: telemetry, host-receipts, cost, turns, activities,
scheduler leases and stand-lease files, none of them ever declared "ignore me". Real numbers
that found this: `qa-factory/state/telemetry/` alone held 7375 hook files and 127 command
pairs (27 MB) after five days on one machine; a colleague who re-cloned and re-onboarded the
same project saw 338 files `git status` called untracked. Three artifacts under
`work/` (S5 fragments) are the same problem one level down: `finalize_task.py` reads and
discards them, they are never meant to be committed.

This script writes ONE explicit block, whole and contiguous, never touching any line of the
project's own (a project's ignore rules for its application code are not ours to move or
reorder). The block is derived from the install table (t-232 F7+F8): one line for the machine-local
folder `qa-factory/state/`, none for the tracked `qa-factory/records/`, plus the generated files
inside the artifacts. A reinstall must end with the same file a fresh install writes (t-232), so the
block is not "the missing lines appended": every line of ours that stands elsewhere in the file - the
one line the first generation wrote, the per-file lines of the 22.09 block (the table's
`gitignore_lines`), or part of an older, partial block - is taken out and the block is put back as
one piece, under our own header, at the end. The project's lines keep their places and their order. Idempotent: a
file that already holds the header and the block as one contiguous piece is left untouched,
`.gitignore`'s mtime included.

CLI (from the project root, or any root passed as --root):
  project_gitignore.py --root <project>            dry run: print what would change (or "up to date")
  project_gitignore.py --root <project> --check     doctor: exit 1 and list the lines out of place, else exit 0 silently
  project_gitignore.py --root <project> --write     write the block as one piece, creating .gitignore if absent

No qa-factory/config.json under --root is not refused here (onboarding calls this BEFORE the
project necessarily carries other factory markers) — that check belongs to the caller.
"""
import argparse
import sys
from pathlib import Path

# Owner's decisions: 22.09.2026 everything under qa-factory/state/ is machine-local except the
# three files a reviewer or a resumed story needs from git (the journal, the coverage map, the
# estimation ledger) - which made the block a list of lines per file; 01.10.2026 (t-232 F7+F8) the
# two kinds live in TWO FOLDERS, so it is visible at a glance what is ignored and what is not:
# `qa-factory/records/` is tracked (no line here), `qa-factory/state/` is ignored whole (one line).
# The block is therefore not written down here: it is DERIVED from references/install-paths.json
# (install_paths.gitignore_block - one line per untracked class folder, plus the generated files
# inside a tracked folder), the same table that says which class a path is, so the ignore rule and
# the classification cannot drift apart. No table, no block: a guess would hide or commit a file.
sys.path.insert(0, str(Path(__file__).resolve().parent))
_TABLE_ERROR = None
try:
    import install_paths
    GITIGNORE_BLOCK = install_paths.gitignore_block()
except ValueError as exc:
    GITIGNORE_BLOCK, _TABLE_ERROR = [], str(exc)
HEADER = "# qa-factory: machine-local state - project_gitignore.py --write keeps this block whole"
# The header the first versions of this script wrote (it said "missing lines only"): ours too, so a
# reinstall replaces it instead of leaving two headers.
OLD_HEADERS = ("# qa-factory: machine-local state — project_gitignore.py --write regenerates missing lines only",)


def _read_lines(gitignore: Path) -> list[str]:
    if not gitignore.is_file():
        return []
    try:
        return gitignore.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def _ours() -> set:
    """Every line the factory ever wrote into `.gitignore`: the block, the headers, and the lines
    the install table records for earlier generations (read from data, FR-13; an unreadable
    table only narrows this to what the block itself names - the first generation's line is its
    first line)."""
    lines = set(GITIGNORE_BLOCK) | {HEADER, *OLD_HEADERS}
    try:
        import install_paths
        lines |= {row["line"] for row in install_paths.gitignore_lines()}
    except (ImportError, ValueError, OSError):
        pass
    return lines


def _is_whole(lines: list[str]) -> bool:
    """The header directly followed by the whole block, in order, and no other line of ours."""
    stripped = [line.strip() for line in lines]
    piece = [HEADER, *GITIGNORE_BLOCK]
    for start in range(len(stripped) - len(piece) + 1):
        if stripped[start:start + len(piece)] == piece:
            rest = stripped[:start] + stripped[start + len(piece):]
            return not (_ours() & set(rest))
    return False


def missing_lines(root: Path) -> list[str]:
    """The lines of GITIGNORE_BLOCK a `--write` has to put back: all of them while the block is not
    present as one contiguous piece (or a line of ours stands elsewhere), none once it is."""
    return [] if _is_whole(_read_lines(root / ".gitignore")) else list(GITIGNORE_BLOCK)


def write_block(root: Path) -> list[str]:
    """Take every line of ours out of the file, put the header and the block back as one piece at
    the end. Returns the block lines written (empty when the file already held them as one piece:
    the write is skipped entirely, so a project with nothing to change keeps its .gitignore's mtime
    and byte-for-byte content). A blank line left behind by a removed line is dropped only when it
    would double the one blank line that separates the project's rules from our block."""
    if _TABLE_ERROR:
        raise ValueError(_TABLE_ERROR)
    gitignore = root / ".gitignore"
    lines = _read_lines(gitignore)
    if _is_whole(lines):
        return []
    # The project's own line endings stay theirs: a CRLF file stays CRLF (and a new file is LF, the
    # same bytes on every machine - the equality check compares trees).
    try:
        eol = "\r\n" if b"\r\n" in gitignore.read_bytes() else "\n"
    except OSError:
        eol = "\n"
    ours = _ours()
    kept = [line for line in lines if line.strip() not in ours]
    while kept and not kept[-1].strip():
        kept.pop()
    out = list(kept)
    if out:
        out.append("")          # one blank line between the project's own rules and ours
    out.append(HEADER)
    out.extend(GITIGNORE_BLOCK)
    with gitignore.open("w", encoding="utf-8", newline="") as handle:
        handle.write(eol.join(out) + eol)
    return list(GITIGNORE_BLOCK)


def main() -> int:
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", required=True, help="project root (the directory whose .gitignore this manages)")
    ap.add_argument("--check", action="store_true", help="exit 1 and list the block; exit 0 and print nothing when up to date")
    ap.add_argument("--write", action="store_true", help="write the block as one piece, creating .gitignore if there is none")
    args = ap.parse_args()

    if _TABLE_ERROR:
        print(f"project_gitignore.py: refused: {_TABLE_ERROR}", file=sys.stderr)
        return 2
    root = Path(args.root)
    if not root.is_dir():
        print(f"project_gitignore.py: --root {root} is not a directory", file=sys.stderr)
        return 2

    if args.write:
        added = write_block(root)
        if added:
            print(f"{root/'.gitignore'}: wrote the block ({len(added)} line(s)):")
            for line in added:
                print(f"  {line}")
        else:
            print(f"{root/'.gitignore'}: already up to date")
        return 0

    missing = missing_lines(root)
    if args.check:
        if missing:
            print(f"{root/'.gitignore'}: the block is not in place as one piece ({len(missing)} line(s)):")
            for line in missing:
                print(f"  {line}")
            return 1
        return 0

    # Dry run (no flag): report only.
    if missing:
        print(f"{root/'.gitignore'}: the block is not in place as one piece (run --write to put it back):")
        for line in missing:
            print(f"  {line}")
    else:
        print(f"{root/'.gitignore'}: up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
