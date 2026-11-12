"""Where the test repository stood when the story began - recorded once, at the S0 exit.

Whether a test is NEW in a story cannot be read off the repository afterwards: a test the
story wrote and then committed at delivery equals HEAD, so "compare with HEAD now" says
`unchanged` for the one test that is most certainly new - the direction that skips a live
check nobody ran (t-134 redraft, critic-on-plan t-120). The only honest base is the
repository as it was before the story touched anything, and no carrier held it: the
controller's `source_revision` is the hash of the ticket snapshot, not a product revision.
This module is that carrier, and only that: it records, it never judges.

  test_repo_base.py --task TP1-13797
  test_repo_base.py --task TP1-13797 --json

Read-only CLI (FR-45). The writer is `stage_done.py --stage S0 --status done`, which calls
`s0_line` once: it is the one choke point both roads pass (the driver and the skill).

`<task root>/state/test-repo-base.json`:

  schema_version  1
  recorded_at, recorded_by   when, and by what ("stage_done.py S0")
  git             "ok" | "absent" | "not_a_repository" | "error"; `why` says what git said
  repo_prefix     the project root inside the repository, exactly what
                  `git rev-parse --show-prefix` prints there (posix, no trailing slash, "" when the
                  project root IS the repository top). NOT path arithmetic between two
                  directory strings: Windows short names (DEV1~1) and a tests root that is its
                  own repository both break that. When the tests root lies in ANOTHER repository
                  than the project root (`other_repository`), the record is of the tests root's
                  repository and the prefix is that of the directory named by `found_from`.
  head, branch    40 hex or ""; a branch name, or "(detached)"; "" in every state but `ok`
  dirty           every uncommitted path of the WHOLE repository at S0, not only the tests root -
                  a helper outside the tests root that was dirty must not read as clean:
                  {"path": repo-relative posix, "status": "<XY>", "sha256": working-tree hash,
                  "" for a path that does not exist as a file (deleted, a submodule)}
                  A rename is its two paths. DIRTY_LIMIT entries are kept, in git's own order;
                  beyond that `dirty_truncated` is true, `dirty_total` is the whole count and
                  `dirty_kept` says what was kept - a reader then treats the record as "HEAD now".
                  The factory's own folder (`qa-factory/`: artifacts, state, telemetry) is NOT the
                  test repository: its paths are neither listed nor counted, and `dirty_excluded`
                  names the folder (repo-relative, "" when nothing was excluded). When the tests
                  root lies inside that folder nothing is excluded and `dirty_excluded_why` says so.
  late, late_why  true when the story had already produced evidence when this was recorded
                  (a run block, an execution job, S5 past pending): the tests written before the
                  record would read as base. A late record is still written and labelled.
  tests_root, found_from, other_repository   where the repository was found, and whether that
                  is the project's own repository

Nothing is guessed: no git on PATH, a directory that is not a repository, a git error and an
empty repository each say so in `git`/`why` and leave `head` empty. The file is written ONCE:
a second S0 close (a resume) finds it and keeps it byte for byte, because a base that moves
forward would include the story's own edits.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

SCHEMA_VERSION = 1
FILE_NAME = "test-repo-base.json"
DIRTY_LIMIT = 2000
STATUS_TIMEOUT = 60      # `status --untracked-files=all` over a big tree is slower than a rev-parse
GIT_STATES = ("ok", "absent", "not_a_repository", "error")
EXIT_BAD_ARGS = 2


def path_of(task_root) -> Path:
    return Path(task_root) / "state" / FILE_NAME


def load(task_root):
    """The record as a dict, or None - absent, unreadable, not an object, or a schema this
    build does not know. Never raises: a reader that cannot read the base falls back to
    "HEAD now", labelled, and a story is never refused over a file that is not there."""
    try:
        data = json.loads(path_of(task_root).read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    version = data.get("schema_version")
    if type(version) is not int or version != SCHEMA_VERSION:
        return None   # `True == 1` in Python: a bool is not a version
    return data


def _git(root, *args, timeout=10):
    """The package's one way to call git (`gate_preflight._git`: read-only, never prompts,
    None when git cannot answer). Imported late: gate_preflight pulls in `contract`, about a
    second that `load` and the CLI have no reason to pay."""
    import gate_preflight
    return gate_preflight._git(root, *args, timeout=timeout)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _same_dir(a, b) -> bool:
    return os.path.normcase(os.path.realpath(str(a))) == os.path.normcase(os.path.realpath(str(b)))


def _inside_a_repository(start) -> bool:
    """A `.git` (directory, or the file a worktree/submodule leaves) at or above `start`.
    Tells "git failed here" from "there is no repository here": `_git` answers None to both."""
    try:
        cur = Path(start).resolve()
    except Exception:
        return False
    return any((d / ".git").exists() for d in (cur, *cur.parents))


def _top_and_prefix(directory):
    """(top, prefix) of the repository `directory` lies in, or None. One git call; git prints
    the top, then the prefix line - empty at the top, so `_git`'s strip drops that line."""
    out = _git(directory, "rev-parse", "--show-toplevel", "--show-prefix")
    if not out:
        return None
    lines = out.split("\n")
    top = lines[0].strip()
    prefix = lines[1].strip().rstrip("/") if len(lines) > 1 else ""
    return (top, prefix) if top else None


def parse_status(text: str) -> list:
    """[(XY, path)] from `git status --porcelain=v1 -z --branch`, the branch header dropped.

    `--branch` is there on purpose: `_git` strips its output, and the first entry of a plain
    porcelain listing begins with the SPACE of " M path" - stripped, the status would read as
    "M path". The header line ("## ...") never begins with a space, so every entry after it
    arrives whole. In `-z` form a rename or copy is `XY to\\0from\\0`; both paths are returned.
    A shape this cannot read raises ValueError: an entry guessed is a dirty path invented."""
    if not text.startswith("## "):
        raise ValueError("git status did not begin with its branch header, so the first "
                         "entry cannot be trusted")
    tokens = text.split("\0")
    if tokens and tokens[-1] == "":
        tokens.pop()
    out, index = [], 1          # tokens[0] is the header
    while index < len(tokens):
        entry = tokens[index]
        index += 1
        if len(entry) < 4 or entry[2] != " ":
            raise ValueError(f"git status entry {entry[:40]!r} is not `XY path`")
        code, path = entry[:2], entry[3:]
        out.append((code, path))
        if "R" in code or "C" in code:
            if index >= len(tokens):
                raise ValueError(f"git status: the rename of {path!r} has no source path")
            out.append((code, tokens[index]))
            index += 1
    return out


def _sha256_file(path) -> str:
    """The raw working-tree bytes' hash, "" for anything that is not a readable file."""
    try:
        if not Path(path).is_file():
            return ""
        digest = hashlib.sha256()
        with open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return ""


def _empty(tests_root, found_from, git, why):
    return {"git": git, "why": why, "repo_prefix": "", "head": "", "branch": "", "dirty": [],
            "dirty_truncated": False, "dirty_total": 0, "dirty_kept": "all",
            "dirty_excluded": "", "dirty_excluded_why": "",
            "tests_root": tests_root, "found_from": found_from, "other_repository": False}


# The factory's own folder inside a project: its artifacts, state and telemetry. `hooklib.state_dir()`
# is `<project root>/qa-factory`, but it resolves the process's project, not the one `measure_git` is
# given, and no helper there takes a root - so the name is held once, here (queued: a hooklib helper).
FACTORY_FOLDER = "qa-factory"


def _without_factory_folder(entries, project, tests, prefix, other):
    """`(entries kept, folder excluded, why nothing was excluded)` - the paths under the factory's own
    folder are not the story's test repository and are not counted.

    Why: a worktree that had run one story held 4063 dirty paths, 2825 of them under
    `qa-factory/state/telemetry`; the next story's S0 would have crossed `DIRTY_LIMIT`, the record
    would read `dirty_truncated`, every measurement would fall back to "HEAD now" and lose the
    base (t-187, 3e; cmp1). The folder is named in the record (`dirty_excluded`, repo-relative like
    the paths of `dirty`) so a reader knows what the list leaves out. The exclusion is the folder
    and nothing else: a dirty path outside it is counted as ever.

    Nothing is excluded when the folder does not exist, or lies in another repository than the one
    recorded (`other`). When the tests root lies INSIDE the folder the exclusion would hide a dirty
    test - the very thing the list is for - so it is refused and the record says so."""
    if other:
        return entries, "", ""
    folder = project / FACTORY_FOLDER
    if not folder.is_dir():
        return entries, "", ""
    inside = folder.resolve()
    if tests == inside or inside in tests.parents:
        return entries, "", (f"the tests root lies inside {FACTORY_FOLDER}/, so excluding it would "
                             "hide a dirty test; every path is counted")
    rel = f"{prefix}/{FACTORY_FOLDER}" if prefix else FACTORY_FOLDER
    kept = [(code, path) for code, path in entries if path != rel and not path.startswith(rel + "/")]
    return kept, rel, ""


def measure_git(project_root, cfg) -> dict:
    """Every git-derived field of the record. Never raises on what git says; every failure is
    a state named in `git`/`why`, with `head` empty - nothing partial, nothing guessed."""
    cfg = cfg if isinstance(cfg, dict) else {}
    project = Path(project_root).resolve()
    configured = str(cfg.get("tests_root") or ".")
    tests = (project / configured).resolve()
    found_from = "tests_root" if tests.is_dir() else "project_root"
    found = tests if found_from == "tests_root" else project

    def empty(git, why):
        return _empty(configured, found_from, git, why)

    if shutil.which("git") is None:
        return empty("absent", "git is not on PATH, so the test repository's base cannot be read")
    where = _top_and_prefix(found)
    if where is None:
        if _inside_a_repository(found):
            return empty("error", f"git could not answer `rev-parse --show-toplevel` in {found}")
        return empty("not_a_repository", f"{found} is not inside a git repository")
    top, prefix = where
    other = False
    if found != project:
        # The project root's own prefix is what the record carries; when the tests root lies in
        # another repository the project root has no prefix in THIS one, so the record is of
        # the tests root's repository and says so.
        mine = _top_and_prefix(project)
        if mine is not None and _same_dir(mine[0], top):
            prefix = mine[1]
        else:
            other = True
    head = _git(top, "rev-parse", "HEAD")
    if not head:
        return empty("error", "the repository has no commit to record (`git rev-parse HEAD` "
                              "answered nothing: an empty repository, or a HEAD git cannot read)")
    branch = _git(top, "rev-parse", "--abbrev-ref", "HEAD")
    if not branch:
        return empty("error", "`git rev-parse --abbrev-ref HEAD` answered nothing")
    status = _git(top, "status", "--porcelain=v1", "-z", "--branch", "--untracked-files=all",
                  timeout=STATUS_TIMEOUT)
    if status is None:
        return empty("error", "`git status --porcelain=v1 -z --untracked-files=all` failed or "
                              f"took more than {STATUS_TIMEOUT} s")
    try:
        entries = parse_status(status)
    except ValueError as exc:
        return empty("error", str(exc))
    entries, excluded, excluded_why = _without_factory_folder(entries, project, tests, prefix, other)
    total = len(entries)
    kept = entries[:DIRTY_LIMIT]
    dirty = [{"path": path, "status": code, "sha256": _sha256_file(Path(top) / path)}
             for code, path in kept]
    return {"git": "ok", "why": "", "repo_prefix": prefix, "head": head,
            "branch": "(detached)" if branch == "HEAD" else branch,
            "dirty": dirty, "dirty_truncated": total > DIRTY_LIMIT, "dirty_total": total,
            "dirty_kept": "all" if total <= DIRTY_LIMIT
            else f"the first {DIRTY_LIMIT} of {total} paths, in git's own order",
            "dirty_excluded": excluded, "dirty_excluded_why": excluded_why,
            "tests_root": configured, "found_from": found_from, "other_repository": other}


def late_reasons(task_root) -> list:
    """Why a base recorded NOW is not the state before the story: the story has already
    produced evidence. Each source is a fact on disk; none is a guess."""
    root = Path(task_root)
    reasons = []
    try:
        blocks = sorted((root / "work" / "run-blocks").glob("*.json"))
        if blocks:
            reasons.append(f"work/run-blocks already holds {len(blocks)} run block(s)")
    except OSError:
        pass
    try:
        jobs = [p for p in (root / "state" / "execution-jobs").rglob("*") if p.is_file()]
        if jobs:
            reasons.append(f"state/execution-jobs already holds {len(jobs)} file(s)")
    except OSError:
        pass
    try:
        pipeline = json.loads((root / "pipeline.json").read_text(encoding="utf-8"))
        stages = pipeline.get("stages") if isinstance(pipeline, dict) else None
        if isinstance(stages, dict) and "S5" in stages:
            entry = stages["S5"]
            status = entry.get("status") if isinstance(entry, dict) else entry
            if status != "pending":
                reasons.append(f"pipeline.json stage S5 is already {status!r}, not pending")
    except Exception:
        pass    # no pipeline to read is no evidence either way
    return reasons


def _record(task_root, project_root, cfg):
    """(record, created). An existing file decides: it is kept whatever it holds."""
    target = path_of(task_root)
    if target.exists():
        existing = load(task_root)
        if existing is None:
            raise ValueError(f"{target} exists but is not a record this build can read; it "
                             "was kept as it is - the base is written once")
        return existing, False
    reasons = late_reasons(task_root)
    rec = {"schema_version": SCHEMA_VERSION, "recorded_at": _now(),
           "recorded_by": "stage_done.py S0"}
    git = measure_git(project_root, cfg)
    rec.update({k: git[k] for k in ("git", "why", "repo_prefix", "head", "branch", "dirty",
                                    "dirty_truncated")})
    rec.update({"late": bool(reasons), "late_why": "; ".join(reasons)})
    rec.update({k: git[k] for k in ("dirty_total", "dirty_kept", "dirty_excluded",
                                    "dirty_excluded_why", "tests_root", "found_from",
                                    "other_repository")})
    from event_store import atomic_json      # a temp file, then replace: never half a record
    atomic_json(target, rec)
    return rec, True


def record(task_root, project_root, cfg) -> dict:
    """Write `state/test-repo-base.json` ONCE and return the record; when it already exists,
    return it untouched. Raises only for what the file system refuses."""
    return _record(task_root, project_root, cfg)[0]


def s0_line(task_root, project_root, cfg) -> str:
    """`record`, and the one line `stage_done.py` prints about it."""
    rec, created = _record(task_root, project_root, cfg)
    if not created:
        return f"test repository base: already recorded at {rec.get('recorded_at')}"
    if rec.get("git") != "ok":
        line = f"test repository base: no commit recorded (git {rec.get('git')}: {rec.get('why')})"
    else:
        line = (f"test repository base: {str(rec.get('head'))[:12]} on {rec.get('branch')}, "
                f"{rec.get('dirty_total')} uncommitted path(s)")
    if rec.get("late"):
        line += f" - recorded late: {rec.get('late_why')}"
    return line


def describe(rec: dict) -> list:
    """The record in words, for a person reading the CLI."""
    lines = [f"recorded {rec.get('recorded_at')} by {rec.get('recorded_by')}"]
    if rec.get("git") == "ok":
        lines.append(f"git: {str(rec.get('head'))[:12]} on {rec.get('branch')}; the project root is "
                     + (f"`{rec.get('repo_prefix')}` inside the repository" if rec.get("repo_prefix")
                        else "the repository top"))
    else:
        lines.append(f"git: {rec.get('git')} - {rec.get('why')} (no base commit is known)")
    if rec.get("other_repository"):
        lines.append("the tests root lies in another repository than the project root; this "
                     "record is of the tests root's repository")
    dirty = rec.get("dirty") if isinstance(rec.get("dirty"), list) else []
    lines.append(f"uncommitted paths at S0: {rec.get('dirty_total', len(dirty))}"
                 + ("" if not rec.get("dirty_truncated") else f" (kept: {rec.get('dirty_kept')})"))
    if rec.get("dirty_excluded"):
        lines.append(f"not counted: the factory's own folder `{rec.get('dirty_excluded')}`")
    elif rec.get("dirty_excluded_why"):
        lines.append(f"nothing left out of the count: {rec.get('dirty_excluded_why')}")
    if rec.get("late"):
        lines.append(f"recorded late: {rec.get('late_why')}; readers treat it as HEAD now")
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Read the test repository base a story recorded "
                                             "at its S0 exit. Read-only.")
    ap.add_argument("--task", required=True)
    ap.add_argument("--json", action="store_true", help="the record as JSON on stdout, nothing "
                    "else (`null` when none was recorded)")
    args = ap.parse_args(argv)
    from hooklib import artifacts_dir, require_project
    require_project("test_repo_base")
    try:
        task_root = artifacts_dir(args.task)
    except ValueError as exc:
        print(f"test_repo_base.py: {exc}", file=sys.stderr)
        return EXIT_BAD_ARGS
    if not task_root.is_dir():
        print(f"test_repo_base.py: no story `{args.task}`: looked for its task folder at "
              f"{task_root} (--task is the story's id, the folder name under "
              "qa-factory/artifacts/)", file=sys.stderr)
        return EXIT_BAD_ARGS
    rec = load(task_root)
    if args.json:
        print(json.dumps(rec, ensure_ascii=False, indent=2))
        return 0
    if rec is None:
        print(f"no test repository base is recorded for {args.task} (looked for "
              f"{path_of(task_root)}): the story passed S0 before this record existed, or S0 was "
              "closed by a resume; readers compare with HEAD now and say so")
        return 0
    print("\n".join(describe(rec)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
