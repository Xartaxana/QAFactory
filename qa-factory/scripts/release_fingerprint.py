#!/usr/bin/env python3
"""ONE recipe of "which package bytes make the factory", and `package_modified` built on it (collect/1, CL1-8; D-0052 (3)).

Before this module two copies of the recipe walked the same five folders: `install_smoke.package_fingerprint` (the cache key
of a passed smoke) and `runtime_paths.resolve_runtime` (the binding of a dispatch to a package). Both now call
`package_fingerprint` here, through the module attribute (a `from ... import` copy would let a reader drift from the recipe
unseen; test K3 patches the attribute and fails on such a copy). The CLI is the release step:

    python -B scripts/release_fingerprint.py --write   in the release copy, after the CHANGELOG assembly
    python -B scripts/release_fingerprint.py --check   LAST, right before the release-copy commit
    python -B scripts/release_fingerprint.py [--json]  compare() as JSON (what the collector reads)

What the recipe is (HEAD's, byte for byte, so every stored fingerprint keeps its meaning):
  * `.claude-plugin/plugin.json` (b"" when absent), then every file under scripts/, references/, agents/, skills/, hooks/ whose
    suffix is .py .json .md .cmd .sh and whose path has no `tests` part, ordered by `hooklib.sorted_paths`; each file adds its
    package-relative posix path and its RAW bytes to one sha256. Two reasons are part of the recipe, not comments to drop:
    `design/` is deliberately outside (nothing there is loaded while the factory runs, FR-44, so editing it must not invalidate
    a passed smoke or a dispatch), and helpers and role instructions are inside (they change behaviour as much as the
    entrypoints do - fingerprinting only the launchers would miss a changed validation contract).
  * The release file `references/release-fingerprint.json` is excluded from the walk, from the aggregate and from the map: a
    file that judges the package never judges itself (I5). The walk reads names and bytes only, never mtime (I6).
  * Symlinks: `is_file()` follows them (the target's bytes are hashed); a dangling link is invisible; a loop makes `rglob`
    raise, and `compare` answers `unknown / package_unreadable` for it.

The release file (written ONLY by `--write`, in the release copy; this repo carries none): schema, recipe, package_version,
`files` = {package-relative posix path: sha256 of the bytes with CRLF turned into LF} and a note. The map is normalised because
an install route that converts line endings must not accuse every user; the aggregate is not (it binds dispatches and stays
HEAD's). The file carries no aggregate: the verdict is decided by the map alone.

`compare()` answers `package_modified`: `yes` only for a proven byte difference of a named file; `no` for equality; `unknown` with
a `why` for any doubt (FR-41, FR-59; absence of evidence is never `no`, a doubt is never `yes`). The rows run in this order, the
first match wins, and rows 2-8 run BEFORE any digest comparison so that `yes` is unreachable while a doubt stands:
  2 no_release_file          3 release_file_unreadable   4 release_file_invalid   5 recipe_mismatch
  6 version_unknown          7 version_mismatch          8 package_unreadable     9 differs (yes)    10 match (no)
ADDED paths with a `.`- or `~$`-prefixed part (an editor or cache leftover) are reported in `litter[]` and never accuse; a map
never holds such a path (`--write` refuses a litter-named recipe file), so a changed or removed one is never litter. `compare`
compares two key sets and never opens a path taken from the map. `install` says `cache` or `frozen` (hooklib.version_carriers):
a copy that does not live in the plugin cache is an experiment's or a development tree, and `no_release_file` there means
something else than in the cache.

The mechanism's failure detectors (rule 10 (c)): a stale release file -> `--check` as the LAST release step; a forgotten step ->
`no_release_file` at intake of the new release's archives (the per-archive line `package_modified` / `why` / `running_version` /
`install` is a queued row of the CL1-6 intake node); readers drifting back to copies -> K3 in CI. Live by import (audit A1): the
two readers import this module; the CLI is the release step, so there is no CLI_SCRIPTS row.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path, PurePosixPath

RECIPE_ID = "release-fingerprint/1"
RECIPE_FOLDERS = ("scripts", "references", "agents", "skills", "hooks")
RECIPE_SUFFIXES = frozenset({".py", ".json", ".md", ".cmd", ".sh"})
MANIFEST_REL = ".claude-plugin/plugin.json"
RELEASE_FILE_REL = "references/release-fingerprint.json"
SCHEMA = 1
NOTE = "written by scripts/release_fingerprint.py --write at release; excluded from itself"
_HEX64 = re.compile(r"[0-9a-f]{64}")
_LITTER_PREFIXES = (".", "~$")

# What each `unknown` means and the move that follows (FR-1, FR-4): the text `--check` prints, keyed by `why`.
WHY_TEXT = {
    "no_release_file": ("references/release-fingerprint.json is absent (a pre-release install, a development tree or a skipped "
                        "release step)", "run `python -B scripts/release_fingerprint.py --write` in the release copy"),
    "release_file_unreadable": ("references/release-fingerprint.json cannot be read as a JSON object",
                                "run `python -B scripts/release_fingerprint.py --write` again"),
    "release_file_invalid": ("references/release-fingerprint.json is not a release file of schema 1 (a key missing, an empty "
                             "map, a digest that is not 64 lowercase hex, a path the recipe cannot produce or a litter-named one)",
                             "run `python -B scripts/release_fingerprint.py --write` again"),
    "recipe_mismatch": ("the release file was made by another recipe than " + RECIPE_ID,
                        "run `python -B scripts/release_fingerprint.py --write` with this package's scripts"),
    "version_unknown": ("the package's .claude-plugin/plugin.json is absent or carries no version of the form N.N.N",
                        "run from the package root of a release copy"),
    "version_mismatch": ("the release file belongs to another version than the package's plugin.json",
                         "run `python -B scripts/release_fingerprint.py --write` after the version change"),
    "package_unreadable": ("a package file could not be read while walking the tree",
                           "fix the files named under unreadable, then run the check again"),
}


# --- the recipe -----------------------------------------------------------------------------------------------------

def _root(root=None) -> Path:
    return Path(root) if root else Path(__file__).resolve().parents[1]


def _read_bytes(path: Path) -> bytes:
    """The one read of a package file (a seam for the tests: a read error in the middle of a walk)."""
    return Path(path).read_bytes()


def _recipe_part(suffix: str, parts) -> bool:
    """HEAD's per-file condition: a recipe suffix and no `tests` part (the tests are not behaviour)."""
    return suffix in RECIPE_SUFFIXES and "tests" not in parts


def recipe_files(root=None) -> list:
    """THE walk: folders x suffixes, no `tests` part, minus the release file, in `hooklib.sorted_paths` order."""
    from hooklib import sorted_paths    # lazy: hooklib imports runtime_paths lazily and runtime_paths calls this module
    base = _root(root)
    files = []
    for folder in RECIPE_FOLDERS:
        for path in (base / folder).rglob("*"):
            if path.is_file():
                rel = path.relative_to(base)
                if _recipe_part(path.suffix, rel.parts) and rel.as_posix() != RELEASE_FILE_REL:
                    files.append(path)
    return sorted_paths(files)


def package_fingerprint(root=None, files=None) -> str:
    """The package's behaviour-bearing bytes as one sha256: HEAD's aggregate, raw bytes (it binds dispatches and smokes). It never
    builds the per-file map: `resolve_runtime` runs it on every `prepare`, so its cost must not grow. `files` is the list
    `recipe_files(root)` returned a moment ago (a caller that already walked the tree for its own reason, SC1-12): None walks
    here, so every other caller gets the same value as before."""
    base = _root(root)
    manifest = base / MANIFEST_REL
    digest = hashlib.sha256(_read_bytes(manifest) if manifest.is_file() else b"")
    for path in (recipe_files(base) if files is None else files):
        digest.update(path.relative_to(base).as_posix().encode())
        digest.update(_read_bytes(path))
    return digest.hexdigest()


def _scan(base: Path):
    """({package-relative posix path: sha256 of the LF-normalised bytes}, [paths that could not be read]): the manifest and
    every recipe file. A lone CR is not normalised: only the pair CRLF is a line ending."""
    digests, unreadable = {}, []
    manifest = base / MANIFEST_REL
    for path in ([manifest] if manifest.is_file() else []) + recipe_files(base):
        rel = path.relative_to(base).as_posix()
        try:
            digests[rel] = hashlib.sha256(_read_bytes(path).replace(b"\r\n", b"\n")).hexdigest()
        except OSError:
            unreadable.append(rel)
    return digests, sorted(unreadable)


def file_digests(root=None) -> dict:
    """The map of the release file, sorted by path. Raises OSError naming the files when any of them cannot be read."""
    digests, unreadable = _scan(_root(root))
    if unreadable:
        raise OSError("unreadable package files: " + ", ".join(unreadable))
    return dict(sorted(digests.items()))


def running_version(root=None):
    """The version text of the package's plugin.json, or None (the package's one reader: hooklib._package_version_at)."""
    from hooklib import _package_version_at
    return _package_version_at(_root(root))[0]


# --- compare: package_modified -------------------------------------------------------------------------------------

def _is_litter(rel: str) -> bool:
    return rel != MANIFEST_REL and any(part.startswith(_LITTER_PREFIXES) for part in rel.split("/"))


def _recipe_key(key) -> bool:
    """The SHAPE of a recipe path: the manifest, or a posix path under a recipe folder with a recipe suffix and no `tests`, `..`,
    empty, absolute or backslash part. A litter-named path has this shape too (the git gate must still name it)."""
    if not isinstance(key, str) or "\\" in key:
        return False
    if key == MANIFEST_REL:
        return True
    parts = key.split("/")
    return (len(parts) >= 2 and parts[0] in RECIPE_FOLDERS and all(p not in ("", ".", "..") for p in parts)
            and _recipe_part(PurePosixPath(key).suffix, parts))


def _admissible_key(key) -> bool:
    """A map key the release step could have written: a recipe-shaped path that is not litter-named (`--write` refuses a
    litter-named file, so a map never holds one). Anything else is a hand-made file (row 4)."""
    return _recipe_key(key) and not _is_litter(key)


def _release_valid(data: dict) -> bool:
    """Row 4: schema 1, the keys, a non-empty version, a non-empty map of admissible keys and 64-lowercase-hex digests.
    The release file's own entry, if present, is ignored whole (I5)."""
    schema, version, files = data.get("schema"), data.get("package_version"), data.get("files")
    if type(schema) is not int or schema != SCHEMA or not isinstance(data.get("recipe"), str):
        return False
    if not (isinstance(version, str) and version) or not isinstance(files, dict):
        return False
    entries = {key: value for key, value in files.items() if key != RELEASE_FILE_REL}
    return bool(entries) and all(_admissible_key(key) and isinstance(value, str) and _HEX64.fullmatch(value)
                                 for key, value in entries.items())


def _read_release(base: Path):
    """Rows 2-5: (the release file's content, "") when it is usable, else (None, why)."""
    path = base / RELEASE_FILE_REL
    if not os.path.lexists(path):
        return None, "no_release_file"
    from hooklib import read_json
    data = read_json(path, errors=Exception, kind=dict)   # Exception: a nesting too deep for the parser is "unreadable" too
    if data is None:
        return None, "release_file_unreadable"
    if not _release_valid(data):
        return None, "release_file_invalid"
    return (data, "") if data["recipe"] == RECIPE_ID else (None, "recipe_mismatch")


def _install(base: Path) -> str:
    try:
        from hooklib import version_carriers
        return "frozen" if version_carriers(plugin_root=base)["running"]["frozen"] else "cache"
    except Exception:
        return "frozen"


def _verdict(out: dict, mapped: dict, disk: dict) -> None:
    """Rows 9-10: two key sets and the digests of the keys both have; a path never leaves this function opened."""
    mapped = {key: value for key, value in mapped.items() if key != RELEASE_FILE_REL}
    lists = {"changed": sorted(key for key in mapped.keys() & disk.keys() if mapped[key] != disk[key]),
             "removed": sorted(mapped.keys() - disk.keys()), "added": sorted(disk.keys() - mapped.keys())}
    # Litter is an ADDED leftover only (m-5). A mapped path was shipped by the release step, so its change or removal is a proven
    # difference whatever its name (a litter-named key cannot be in an accepted map anyway: `_admissible_key`).
    out["litter"] = sorted(rel for rel in lists["added"] if _is_litter(rel))
    for name, names in lists.items():
        out[name] = [rel for rel in names if name != "added" or not _is_litter(rel)]
    differs = any(out[name] for name in lists)
    out["package_modified"], out["why"] = ("yes", "differs") if differs else ("no", "match")


def _compare(base: Path, out: dict) -> None:
    out["running_version"] = running_version(base)
    release, why = _read_release(base)
    if release is not None:
        out["release_version"] = release["package_version"]
    if why:
        out["why"] = why
    elif out["running_version"] is None:
        out["why"] = "version_unknown"
    elif release["package_version"] != out["running_version"]:
        out["why"] = "version_mismatch"
    else:
        disk, out["unreadable"] = _scan(base)
        if out["unreadable"]:
            out["why"] = "package_unreadable"
        else:
            _verdict(out, release["files"], disk)


def compare(root=None) -> dict:
    """{package_modified: yes|no|unknown, why, recipe, release_version, running_version, changed, added, removed, unreadable,
    litter, install}: the same keys on every path (FR-14); lists sorted, full, package-relative. Never raises, writes nothing."""
    base = _root(root)
    out = {"package_modified": "unknown", "why": "", "recipe": RECIPE_ID, "release_version": None, "running_version": None,
           "changed": [], "added": [], "removed": [], "unreadable": [], "litter": [], "install": "frozen"}
    try:
        _compare(base, out)
    except Exception:    # a loop in rglob, a vanished folder: no claim is made on a tree that could not be walked
        out["package_modified"], out["why"] = "unknown", "package_unreadable"
    out["install"] = _install(base)
    return out


# --- write: the release step ---------------------------------------------------------------------------------------

class ReleaseRefusal(ValueError):
    """`--write` refuses (FR-1): the message names what is wrong, what was expected and the door."""


_LISTINGS = (("ls-files", "-z", "--others", "--exclude-standard"), ("ls-files", "-z", "--others", "--exclude-standard", "--ignored"),
             ("diff", "--name-only", "--relative", "-z"))    # untracked, ignored, and worktree-vs-index (intent-to-add, unstaged edits)


def _unshipped(base: Path):
    """(recipe files a `git commit` would not carry as they are on disk, "") when the package folder is a git clone, else
    (None, why it was not checked). The files are untracked, ignored, or differ from the index (`git add -N` and an unstaged edit:
    the commit lacks or has other bytes than the map). Git is read through `project_inventory._git`, the package's one git
    wrapper. Inside a clone a listing that fails is a refusal (FR-59): the listing is the evidence, an unknown is not a pass."""
    from project_inventory import _git
    code, out = _git(base, "rev-parse", "--is-inside-work-tree")
    if code != 0 or out != "true":
        return None, "it is not a git clone (or git is unavailable)"
    found = set()
    for args in _LISTINGS:
        code, out = _git(base, *args)
        if code != 0:
            raise ReleaseRefusal("git could not list the untracked, ignored and modified files of the clone " + str(base) + " (`git "
                                 + " ".join(args[:2]) + "` exited " + str(code) + "); expected the listing, because without it a "
                                 "file an install from git would lack cannot be ruled out; run it again, or fix git (`git status` "
                                 "in that folder)")
        found.update(path for path in out.split("\0") if path)
    return sorted(path for path in found if path != RELEASE_FILE_REL and _recipe_key(path)), ""


def _unshipped_text(base: Path, extra: list) -> str:
    return ("these recipe files are untracked, ignored or changed since they were added to the index in the git clone " + str(base)
            + ": " + ", ".join(extra[:10]) + (f" (+{len(extra) - 10} more)" if len(extra) > 10 else "")
            + "; expected every recipe file added to the index as it is now, because an install from git would lack or differ "
            "from them and read `yes`; `git add -A .` the package (or delete or revert the file), then run the command again")


def _found_version(base: Path) -> str:
    """What plugin.json holds where a version of the form N.N.N was expected (for the refusal text)."""
    from hooklib import read_json
    if not (base / MANIFEST_REL).is_file():
        return "plugin.json absent"
    data = read_json(base / MANIFEST_REL, kind=dict)
    value = data.get("version") if data else None
    return "no version field" if value is None else repr(value)[:60]


def write_release(root=None) -> dict:
    """Write references/release-fingerprint.json from the tree as it is, atomically; returns what was written. Refuses
    (ReleaseRefusal) without a plugin.json version of the form N.N.N, with unreadable files, with a litter-named recipe file
    (a map never holds one), and - when the folder is a git clone - with a recipe file that is untracked, ignored or changed
    since `git add`, or when git cannot list them: an install from git would not have those bytes, so every such install would
    read `yes` (I1)."""
    base = _root(root)
    version = running_version(base)
    if version is None:
        raise ReleaseRefusal("no version of the form N.N.N in .claude-plugin/plugin.json under " + str(base) + " (found: "
                             + _found_version(base) + "); expected the release's manifest; run from the package root of the "
                             "release copy (ai-packages/qa-factory)")
    extra, why = _unshipped(base)
    if extra is None:
        print("release_fingerprint: warning: untracked, ignored and modified recipe files were not checked: " + why, file=sys.stderr)
    elif extra:
        raise ReleaseRefusal(_unshipped_text(base, extra))
    digests = file_digests(base)
    litter = [rel for rel in digests if _is_litter(rel)]
    if litter:
        raise ReleaseRefusal("these recipe files have a `.`- or `~$`-prefixed part, which the release step does not ship: "
                             + ", ".join(litter[:10]) + (f" (+{len(litter) - 10} more)" if len(litter) > 10 else "")
                             + "; expected no litter-named file under scripts, references, agents, skills or hooks; rename it or move "
                             "it out of those folders, then run --write again")
    data = {"schema": SCHEMA, "recipe": RECIPE_ID, "package_version": version, "files": digests, "note": NOTE}
    from event_store import atomic_json
    atomic_json(base / RELEASE_FILE_REL, data)
    return data


# --- the CLI -------------------------------------------------------------------------------------------------------

def _check(base: Path) -> int:
    """Exit 0 = the tree matches the release file, 1 = it differs (files named), 2 = unknown (why named)."""
    result = compare(base)
    verdict, why = result["package_modified"], result["why"]
    if verdict == "no":
        # The tree matches the file; does the COMMIT? (same listing as --write: untracked, ignored, not in the index as it is)
        try:
            extra, not_checked = _unshipped(base)
        except ReleaseRefusal as exc:
            print("release_fingerprint --check: unknown (git_listing_failed): " + str(exc))
            return 2
        if extra:
            print("release_fingerprint --check: unknown (not_in_index): " + _unshipped_text(base, extra))
            return 2
        if extra is None:
            print("release_fingerprint: warning: untracked, ignored and modified recipe files were not checked: " + not_checked,
                  file=sys.stderr)
        print(f"release_fingerprint --check: ok - the tree matches {RELEASE_FILE_REL} (version {result['release_version']}).")
        return 0
    if verdict == "yes":
        print(f"release_fingerprint --check: the tree DIFFERS from {RELEASE_FILE_REL} (version {result['release_version']}).")
        for name in ("changed", "added", "removed"):
            for rel in result[name]:
                print(f"  {name}: {rel}")
        print("Expected: the file written from this very tree. Run `python -B scripts/release_fingerprint.py --write` again "
              "after the last edit, then --check last.")
        return 1
    what, door = WHY_TEXT.get(why, (why, "read the --json output"))
    print(f"release_fingerprint --check: unknown ({why}): {what}. Expected: a release file written from this tree. Door: {door}.")
    for rel in result["unreadable"]:
        print(f"  unreadable: {rel}")
    return 2


def main(argv=None, root=None) -> int:
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    parser = argparse.ArgumentParser(description="Write, check or print the release fingerprint of this package.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="write references/release-fingerprint.json (the release step)")
    mode.add_argument("--check", action="store_true", help="exit 0 = matches, 1 = differs, 2 = unknown (why named)")
    mode.add_argument("--json", action="store_true", help="print compare() as JSON (the default)")
    args = parser.parse_args(argv)
    base = _root(root)
    if args.write:
        try:
            data = write_release(base)
        except (ReleaseRefusal, OSError) as exc:
            print("release_fingerprint --write refused: " + str(exc), file=sys.stderr)
            return 2
        print(f"release_fingerprint --write: wrote {RELEASE_FILE_REL} ({len(data['files'])} files, version {data['package_version']}).")
        return 0
    if args.check:
        return _check(base)
    print(json.dumps(compare(base), indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
