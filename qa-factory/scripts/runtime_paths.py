"""Where the factory's files live, and the active installation, resolved in one place.

Two jobs, one module (FR-37: a path named in text resolves through here, not by hand):

1. `resolve_runtime` - the active installation, without trusting a product working directory.
   Below it, the READ resolver (t-304 N1): a story's stored absolute paths are hints, and every reader
   resolves them when it reads (`project_for_task`, `state_paths`, `contained`; section "one resolver").
2. THE LAYOUT of a project's `qa-factory/` home (t-232 section 8, owner's decision F7+F8): two
   folders, so it is visible at a glance what git ignores and what it does not.

     qa-factory/records/   tracked: the carried records a person or a past run produced (journal,
                           estimation ledger, coverage map, project decisions, onboarding approvals,
                           config backups). Committed and carried across a reinstall.
     qa-factory/state/     machine-local: ignored whole by ONE `.gitignore` line. Nothing carried
                           lives here; `readiness.json` is here (it is regenerated and holds absolute
                           paths).

   Which name belongs to which folder is a fact the table `references/install-paths.json` states
   (its `folders` block and the rows that carry `moved_to`, FR-13); callers say WHICH KIND of file they mean by the
   function they call (`record` or `state_file`), and this module answers where it is.

Both worlds, until a project is re-onboarded (the temporal edge): a project installed by an older
factory has its records under `state/` (and `readiness.json` beside `config.json`). Every reader and
every writer resolves through `record()` / `readiness()`, which look at the new place first, then the
old one: a project that has only the old file keeps using it (the reinstall moves it, onboard_apply),
a project that has only the new one uses that, and a project that has BOTH (a crash in the middle of
a move, or two machines) reads the NEWER by mtime - never silently: onboard_apply lists the second
copy. A fresh project resolves to the new place. Nothing here creates or moves a file (FR-45); the
caller makes the parent folder when it writes.
"""
import argparse
import copy
import json
import os
import sys
from pathlib import Path

HOME = "qa-factory"
RECORDS = "records"
STATE = "state"
# `readiness.json` sat beside config.json until the layout above; it moved into state/.
READINESS = "readiness.json"


# --- the layout -----------------------------------------------------------------------------------

def home_dir(project) -> Path:
    return Path(project) / HOME


def records_root(project) -> Path:
    """The tracked folder of carried records."""
    return home_dir(project) / RECORDS


def state_root(project) -> Path:
    """The machine-local folder (ignored whole)."""
    return home_dir(project) / STATE


def state_file(project, *parts) -> Path:
    """A machine-local file: `state/<parts>`. There is one place for these, no second world."""
    return state_root(project).joinpath(*parts)


def _newer(a: Path, b: Path) -> Path:
    """Of two existing copies, the newer by mtime (a tie goes to `a`, the layout's own place)."""
    try:
        return b if b.stat().st_mtime > a.stat().st_mtime else a
    except OSError:
        return a


def _both_worlds(new: Path, old: Path) -> Path:
    n, o = os.path.lexists(new), os.path.lexists(old)
    if n and o:
        return _newer(new, old)
    return old if o else new


def record(project, name: str) -> Path:
    """A carried record (`journal.jsonl`, `config-migrations`...): `records/<name>`, or the old
    `state/<name>` while that is the only copy there is. The ONE answer for a reader and a writer
    alike, so a writer never starts a second file beside an old one."""
    return _both_worlds(records_root(project) / name, state_root(project) / name)


def record_new(project, name: str) -> Path:
    """Where the layout puts the record: `records/<name>` (what a move produces)."""
    return records_root(project) / name


def record_old(project, name: str) -> Path:
    """Where an older factory kept it: `state/<name>` (what a move takes from)."""
    return state_root(project) / name


def duplicate(project, name: str):
    """None, or (newer, older) when the record exists in BOTH places."""
    new, old = record_new(project, name), record_old(project, name)
    if os.path.lexists(new) and os.path.lexists(old):
        win = _newer(new, old)
        return win, (old if win == new else new)
    return None


def readiness(project) -> Path:
    """The readiness report: `state/readiness.json`, or the old `readiness.json` beside the config
    while that is the only copy (both: the newer)."""
    return _both_worlds(state_root(project) / READINESS, home_dir(project) / READINESS)


def readiness_write(project) -> Path:
    """Where `readiness.py --write` puts it: always `state/readiness.json`."""
    return state_root(project) / READINESS


def normalise_project_path(value) -> str:
    """ONE spelling of a project-relative path, for everything that compares a path a config names
    with a path the layout owns: surrounding blanks stripped, backslashes to forward slashes, every
    leading `./` dropped, no trailing slash; the case is KEPT (a path that differs only by case is
    another path on a case-sensitive disk). t-272 item 5: the writer (`configured`) and the install's
    value migration (config_contract) used two different readings, so `qa-factory\\state\\journal.jsonl`
    was kept by the migration and resolved to records/ by the writer, and `./qa-factory/state/journal.jsonl`
    was kept AND resolved to the old state/. Not a containment check and not a resolver: `..`, a drive,
    a leading slash (absolute, UNC) stay as they are, so a person's own absolute path is never turned
    into a relative one; an empty value stays empty."""
    text = str(value or "").replace(chr(92), "/").strip()
    while text.startswith("./"):
        text = text[2:].lstrip("/")        # `.//x` is `x`, never the absolute `/x`
    if text == ".":
        return ""
    while len(text) > 1 and text.endswith("/"):
        text = text[:-1]
    return text


def configured(project, value, name: str) -> Path:
    """A path the project's config names for a record (`journal_path`): a person's OWN path is
    honoured as it is; empty, or either spelling of the factory's own default (the old
    `qa-factory/state/<name>`, the new `qa-factory/records/<name>`, in any spelling
    `normalise_project_path` folds together), resolves through the layout."""
    text = normalise_project_path(value)
    if text in ("", f"{HOME}/{STATE}/{name}", f"{HOME}/{RECORDS}/{name}"):
        return record(project, name)
    return Path(project) / text


def project_alias(project, rel: str) -> str:
    """A `project:<rel>` name of a data file (stages.json, brief-pack lists) as the path under
    `qa-factory/` where the file really is: `readiness.json` and `state/<record>` follow the layout,
    every other name comes back as given. Idempotent for the new spellings."""
    text = str(rel or "").replace(chr(92), "/")
    if text == READINESS:
        return readiness(project).relative_to(home_dir(project)).as_posix()
    for folder in (STATE, RECORDS):
        name = text[len(folder) + 1:] if text.startswith(folder + "/") else ""
        if name and "/" not in name and name in record_names():
            return record(project, name).relative_to(home_dir(project)).as_posix()
    return text


def record_names() -> tuple:
    """The names that live in `records/`: the top-level name of every `moved_to` of the table's
    rows (`install_paths.moves`), read from data (FR-13), so this module holds no second list."""
    try:
        table = json.loads((Path(__file__).resolve().parent.parent / "references" / "install-paths.json")
                           .read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return ()
    prefix = f"{HOME}/{RECORDS}/"
    out = []
    for row in table.get("rules") or []:
        target = row.get("moved_to") if isinstance(row, dict) else None
        if isinstance(target, str) and target.startswith(prefix):
            name = target[len(prefix):].split("/")[0]
            if name and name not in out:
                out.append(name)
    return tuple(out)


def rel_text(name: str, project=None) -> str:
    """`qa-factory/records/<name>` (or where the file is, given a project): the spelling for a text
    a person or a role reads (FR-37)."""
    if project is not None:
        return record(project, name).relative_to(Path(project)).as_posix()
    return f"{HOME}/{RECORDS}/{name}"


# --- where a project is: the ONE search for its marker --------------------------------------------

def nearest_project(start) -> Path | None:
    """The nearest folder at or above `start` where `qa-factory/config.json` is a FILE, or None.

    The ONE walk for the project marker (B-309 (d), t-622): the controller, the judge, the bug records, the
    dashboard fallback, `resolve_runtime`, `project_for_task` (candidate 1), `critic_rollcall.project_root_of`
    and `hooklib._nearest_project` all delegate here, each keeping its own name. It LOCATES; it does not admit
    (`project_for_task` admits a project by its artifact root) and it does not ask the process
    (`hooklib.project_root` answers "the project this process works in", env first, never None).

    Invariants: it never raises, and it never returns a folder without the marker FILE (a `qa-factory/`
    folder with no config, or a `config.json` that is a directory, is not a project; `.git` is never read).
    The allowed error is None (a missed project); the forbidden one is a folder that is no project, so a
    `start` that is None, blank, not a path, holds a NUL or cannot be resolved gives None - never the
    working directory (`Path("")` is the current folder, and a locator that took it would invent a project)
    - and an error on one candidate skips that candidate."""
    text = _fs(start)
    if text is None or not text.strip() or "\0" in text:
        return None
    try:
        here = Path(text).resolve()
    except (OSError, ValueError, RuntimeError):
        return None
    for folder in (here, *here.parents):
        try:
            if (folder / HOME / "config.json").is_file():
                return folder
        except (OSError, ValueError):
            continue
    return None


# --- the active installation ----------------------------------------------------------------------

ENTRYPOINT_NAMES = ('controller', 'run_suite', 'manual_evidence', 'artifact_packet', 'readiness',
                    'env_probe', 'finalize_task', 'stage_done', 'ticket_adapter')


def package_root() -> Path:
    """The package this process runs: never a stored value (a plugin update, a copied story)."""
    return Path(__file__).resolve().parent.parent


def _repository_roots(project, cfg) -> dict:
    """{id: absolute path} of the config's `code_repos`, resolved against `project`."""
    repos = {}
    for item in (cfg.get('code_repos') if isinstance(cfg, dict) else None) or []:
        if isinstance(item, dict) and item.get('path'):
            repos[str(item.get('id') or item.get('name') or item['path'])] = str(
                (Path(project) / item['path']).resolve())
    return repos


_FINGERPRINTS: dict = {}     # {str(package root): (signature, recipe function, fingerprint)} - this process's memory of the last hash


def _package_fingerprint(plugin):
    """`release_fingerprint.package_fingerprint(plugin)`, hashed once per process while the package files are unchanged.

    `resolve_runtime` runs on every `prepare`, every `dispatch` and every package stamp, two to three times in one
    `story_step start`, and each run read and hashed every recipe file (C3-26: 0.8 s on Windows, 151 s on a docker
    bind mount). The signature is `(path, size, mtime_ns)` of the manifest and of each recipe file, taken on EVERY call
    (a stat walk, no read) and BEFORE the hash, so a file changed while it is being hashed leaves a signature the next
    call does not match. The cache is wrong in ONE direction only: a rewrite with the same size AND the same mtime_ns
    inside one process keeps the old value (a copy that preserves the time over a file of the same length); another
    process has no cache. Everything else - another length, a new time, a file gone or added, a stat that fails - is a
    recompute (E21-E23); a failed stat is never cached. The value is the recipe's, unchanged (`test_launch_path_costs` L8)."""
    import release_fingerprint
    key = str(plugin)
    try:
        base = Path(plugin)
        manifest = base / release_fingerprint.MANIFEST_REL
        signature = []
        if manifest.is_file():
            stat = manifest.stat()
            signature.append((str(manifest), stat.st_size, stat.st_mtime_ns))
        else:
            signature.append((str(manifest), None, None))     # the recipe hashes an absent manifest as empty bytes
        files = release_fingerprint.recipe_files(base)
        for path in files:
            stat = path.stat()
            signature.append((str(path), stat.st_size, stat.st_mtime_ns))
        signature = tuple(signature)
    except OSError:
        return release_fingerprint.package_fingerprint(plugin)
    recipe = release_fingerprint.package_fingerprint
    held = _FINGERPRINTS.get(key)
    # the value is kept WITH the recipe function that made it: a reader that swaps the module attribute - a test seam,
    # `test_release_fingerprint` K3 - is followed, never answered from memory
    if held is not None and held[0] == signature and held[1] is recipe:
        return held[2]
    value = recipe(plugin, files=files)       # the list the signature walked: a miss walks the tree ONCE (t-1332 B1)
    _FINGERPRINTS[key] = (signature, recipe, value)
    return value


def resolve_runtime(task_root, project_root=None):
    plugin = package_root()
    task = Path(task_root).resolve()
    project = Path(project_root).resolve() if project_root else nearest_project(task)
    if project is None:
        raise ValueError('project root with qa-factory/config.json required')
    cfg = json.loads((project / 'qa-factory/config.json').read_text(encoding='utf-8-sig'))
    manifest = plugin / '.claude-plugin/plugin.json'
    version = json.loads(manifest.read_text(encoding='utf-8-sig')).get('version')
    entries = {name: str(plugin / 'scripts' / (name + '.py')) for name in ENTRYPOINT_NAMES}
    missing = [name for name, path in entries.items() if not Path(path).is_file()]
    if missing:
        raise ValueError('active installation missing entrypoints: ' + ', '.join(missing))
    # The one recipe (release_fingerprint.py), the same value install_smoke binds a passed smoke to; `_package_fingerprint`
    # imports it lazily, as every hooklib use in this module is (hooklib imports this module lazily, and the recipe imports hooklib).
    repos = _repository_roots(project, cfg)
    return {'plugin_root': str(plugin), 'project_root': str(project), 'task_root': str(task),
            'scripts_root': str(plugin / 'scripts'), 'python_executable': sys.executable,
            'repository_roots': repos, 'package_version': version,
            'package_fingerprint': _package_fingerprint(plugin), 'entrypoints': entries}


# --- one resolver for every reader of a story's stored paths (t-304 N1; B-251, B-249) -------------------------
# cmp2 -> man1, 02.10: a story copied to another worktree kept the ABSOLUTE paths `initialize` stored (`project_root`,
# `plugin_root`, `scripts_root`, `python_executable`, the artifact paths), and six readers took them as locations:
# `contract._config_location` (so `cases_root` wrote case documents into the other project), `dashboard_refresh.
# refresh_for_task` (it refreshed and wrote into the other project), `inject_context` and `story_run.system_file` (a role
# packet naming the other project's paths and the frozen package of the other generation), `controller.prepare`'s
# fallback and the dispatch record the hook prints. Now a stored absolute value is a HINT: it is never used as a location,
# nothing is rewritten in place (the state is immutable, so no reader can refuse it - that would be a dead end, FR-57), and
# every reader resolves the paths when it reads, through this one place (FR-16, FR-17, FR-37).
# Two policies share the token functions below. READ (`state_paths`, `project_for_task`): never writes, never refuses on
# generation, and prefers omitting a path to naming one that is not this story's - one search costs a role a turn, a foreign
# path costs a wrong project. RUN (`known_paths_for_dispatch`, t-335): a packet that is about to be DISPATCHED is refused
# when it was made for another package or names paths this machine does not have, with the door `prepare`.
PROJECT_TOKEN = "{project_root}"
PLUGIN_TOKEN = "{plugin_root}"
TASK_TOKEN = "{task_root}"
PYTHON_TOKEN = "{python}"
TOKENS = (PROJECT_TOKEN, PLUGIN_TOKEN, TASK_TOKEN, PYTHON_TOKEN)
FINGERPRINT_SHOWN = 12
# the absolute-path keys of a packet that a legacy packet is checked on: they are what a dispatch RUNS
LEGACY_RUN_KEYS = ("project_root", "plugin_root", "scripts_root", "python_executable")
# the keys a RUN packet recomputes from the current config and package when it carries an absolute leftover (Q6)
RECOMPUTED_RUN_KEYS = ("repository_roots", "entrypoints", "scripts_root")
# the keys a READ never takes from storage: they are the reader's own roots, so a stored value is only a hint
READ_RECOMPUTED_KEYS = ("task_root", "root", "project_root", "plugin_root", "scripts_root", "python_executable",
                        "entrypoints", "repository_roots")
NOTE_MAX = 200          # a hint is printed at most this long: the note is a line a person reads, not a dump

# The artifacts a role reaches for by name, keyed the way a role would ask. Measured on run 5: **129 of 644 reads
# missed**, and the top of that list is this table's subject - the human plan tried at both levels (`test-plan.md` 8
# times, `work/test-plan.md` 5, the same file), the context manifest 7, the bundle 4, the readiness 3. Every path is
# resolved through the registry that the writers use, never spelled here (FR-15, FR-37). Moved here from
# `story_run.Driver.KNOWN_ARTIFACTS` (which keeps the name as an alias): the writer and the reader share one table.
KNOWN_ARTIFACTS = {
    "plan": "test-plan.json", "plan_document": "test-plan.md",
    "source_inventory": "source-inventory.json", "manifest": "context-manifest.json",
    "bundle": "context-bundle.json", "register": "requirements-register.md",
    "readiness": "requirements-readiness.json", "understanding": "understanding.md",
    "automation_manifest": "automation-manifest.json", "run_report": "run-report.json",
    "triage": "triage.json", "report": "test-report.md", "pipeline": "pipeline.json",
    "grounding": "grounding.yaml",
}

_NOTED: set = set()      # (kind, hint) already printed by this process


VALUE_MAX = 120         # in the omission note a VALUE is cut at this length; a label (a key name) never is


def _short(value, limit: int = NOTE_MAX) -> str:
    text = str(value)
    return text if len(text) <= limit else f"{text[:limit]}...({len(text)} characters)"


def _emit(kind, dedupe, line) -> None:
    """One stderr line per process per (kind, dedupe). Stderr only, never stdout (FR-14: a controller's stdout is parsed
    as JSON)."""
    key = (str(kind), str(dedupe))
    if key in _NOTED:
        return
    if len(_NOTED) > 256:
        _NOTED.clear()
    _NOTED.add(key)
    print(line, file=sys.stderr, flush=True)


def hint_note(kind, hint, reason, used) -> None:
    """ONE stderr line per process per (kind, hint): the stored `hint` is not `reason` here, `used` stands. Stderr only,
    never stdout (FR-14), and no script name or flag in it (FR-6)."""
    _emit(kind, hint, f"{kind}: the stored path ({_short(hint)}) is not {reason} here; using {_short(used)}")


# --- containment and spelling ------------------------------------------------------------------------------

def _abs_text(text) -> bool:
    """An absolute path in either spelling (`C:/x`, `C:` + backslash + `x`, `/x`) - read on any machine, since a packet
    written on one is read on another."""
    if not isinstance(text, str) or len(text) < 2:
        return False
    sep = "/" + chr(92)
    return text[0] in sep or (len(text) > 2 and text[0].isalpha() and text[1] == ":" and text[2] in sep)


def _folded(text: str) -> str:
    text = text.replace(chr(92), "/").rstrip("/")
    return text.lower() if os.name == "nt" else text


def _local_abs(text) -> bool:
    """An absolute path of THIS machine's kind: a drive or a UNC share on Windows (a rooted path with no drive is the
    current drive's, which names nothing), a leading separator elsewhere. A relative path, an empty or blank string,
    a URL (`file://...`), a number or None are not."""
    if not isinstance(text, str) or not text.strip() or "\0" in text:
        return False
    if not os.path.isabs(text):
        return False
    return os.name != "nt" or bool(os.path.splitdrive(text)[0])


def _drive(text: str) -> str:
    """The drive or UNC share of an absolute path, folded (case, slashes on Windows); "" elsewhere. A UNC path pays the
    NETWORK on every filesystem call (measured 3-7.5 s per process, and the hook is a new process on every dispatch), so
    a comparison across drives is answered from the text, before any call."""
    return os.path.normcase(os.path.splitdrive(text)[0])


def _is_unc(text) -> bool:
    return isinstance(text, str) and text[:2] in (chr(92) * 2, "//")


def _fs(value):
    """The text of a str or a path object, None for anything else."""
    try:
        text = os.fspath(value)
    except TypeError:
        return None
    return text if isinstance(text, str) else None


def _rest_under(path, root):
    """(the parts of `path` below `root`, the number of parts of `root`) when `path` is `root` or inside it, else None.

    By COMPONENTS of the REAL places (`os.path.realpath` on both sides - t-319: on Windows one folder has an 8.3 and a long
    spelling, and a junction lands somewhere else - then `normcase`), never by a string prefix: `.../proj` is not a prefix
    of `.../project-copy`. A place that does not exist here cannot be expanded and is compared as spelled (the allowed
    error is not recognising a path as ours, which ends as recompute or omit; calling a foreign path ours is the forbidden
    one). A root that exists and is not a folder holds nothing."""
    path, root = _fs(path), _fs(root)
    if not _local_abs(path) or not _local_abs(root):
        return None
    if _drive(path) != _drive(root):
        return None           # another drive, or a UNC share against a drive letter: never inside, and `realpath` is not paid
    try:
        real_path, real_root = _real(path), _real(root)
        folded_path = Path(os.path.normcase(real_path)).parts
        folded_root = Path(os.path.normcase(real_root)).parts
        if not folded_root or folded_path[:len(folded_root)] != folded_root:
            return None
        if os.path.exists(real_root) and not os.path.isdir(real_root):
            return None
        return Path(real_path).parts[len(folded_root):], len(folded_root)
    except (OSError, ValueError):
        return None


def _real(text: str) -> str:
    """The real place of an absolute path; a path the OS cannot resolve (too long for the call, a broken link) is taken as
    spelled, normalised - a place that cannot be expanded is compared as written (E5)."""
    try:
        return os.path.realpath(text)
    except (OSError, ValueError):
        return os.path.abspath(text)


def contained(path, root) -> bool:
    """Is `path` `root` itself or inside it? See `_rest_under`. A value that is not a str or a path object, an empty or
    relative one, or another drive / a UNC share, is not inside."""
    return _rest_under(path, root) is not None


def _under(text: str, roots: list) -> str:
    """`text` with the longest root of `roots` [(token, path)] that holds it replaced by the token; unchanged when no
    root holds it or it is not an absolute path. The roots are compared as TEXT first (a record of another machine names
    roots that do not exist here); a path no root holds by text is tried by the real places (8.3 / junction / case)."""
    if not _abs_text(text):
        return text
    folded, best = _folded(text), None
    for token, root in roots:
        base = _folded(str(root or ""))
        if base and (folded == base or folded.startswith(base + "/")) and (best is None or len(base) > best[0]):
            best = (len(base), token)
    if best is not None:
        return best[1] + text.replace(chr(92), "/").rstrip("/")[best[0]:]
    found = None
    for token, root in roots:
        hit = _rest_under(text, root) if root else None
        if hit is not None and (found is None or hit[1] > found[0]):
            found = (hit[1], token, hit[0])
    if found is None:
        return text
    return found[1] + "".join("/" + part for part in found[2])


def _climbs_out(original, got, roots) -> bool:
    """A path spelled with a `..` part that the resolution changed and that now lies inside none of `roots`: under a root
    by TEXT, but climbing out of it into a sibling copy. ONE predicate for READ (`state_paths`) and RUN
    (`known_paths_for_dispatch`): the real place decides, through `contained` (FR-17)."""
    return (isinstance(original, str) and isinstance(got, str) and got != original
            and ".." in original.replace(chr(92), "/").split("/")
            and not any(contained(got, root) for root in roots if root))


def _same_place(left: str, right) -> bool:
    """Two absolute paths that name one place (slash, case on Windows, short names): resolved when they can be."""
    if (_is_unc(str(left)) or _is_unc(str(right))) and _drive(str(left)) != _drive(str(right)):
        return False
    def norm(text):
        try:
            return _folded(str(Path(str(text)).resolve()))
        except (OSError, ValueError):
            return _folded(str(text))
    return norm(left) == norm(right)


# --- tokens: portable, and resolved against the roots of the reader --------------------------------------------

def portable_known_paths(paths, project_root, plugin_root, task_root=None):
    """A new dict: every absolute path of `paths` under `project_root` or `plugin_root` (or `task_root`, when given) as a
    token and a forward-slash rest, `python_executable` as `{python}`; a path under none of them (a checkout of another
    repository), a non-path (`package_version`, `package_fingerprint`) and every key the function does not know stay as
    they were. The roots are the ones that WROTE the paths - a packet read from a record of another generation passes that
    record's own `project_root` / `plugin_root`, so it is made portable whatever generation it is. The longest root that
    holds a path wins. Not a dict: returned as it is."""
    if not isinstance(paths, dict):
        return paths
    roots = [(PROJECT_TOKEN, project_root), (PLUGIN_TOKEN, plugin_root)]
    if task_root:
        roots.append((TASK_TOKEN, task_root))
    out = {}
    for key, value in paths.items():
        if key == "python_executable" and isinstance(value, str) and value.strip():
            out[key] = PYTHON_TOKEN
        elif isinstance(value, str):
            out[key] = _under(value, roots)
        elif isinstance(value, dict):
            out[key] = {name: _under(item, roots) if isinstance(item, str) else item for name, item in value.items()}
        else:
            out[key] = value
    return out


def _resolve_text(text, project_root, plugin_root, python, task_root):
    """`text` with its leading token replaced by the root; `text` itself when it holds no token; None when the token's
    root is not known to this reader (a `{task_root}` with no task, a `{project_root}` with no project)."""
    if not isinstance(text, str):
        return text
    if text == PYTHON_TOKEN:
        return str(python) if python else None
    for token, root in ((PROJECT_TOKEN, project_root), (PLUGIN_TOKEN, plugin_root), (TASK_TOKEN, task_root)):
        if text == token or (text.startswith(token) and text[len(token)] in "/" + chr(92)):
            if not root:
                return None
            if text == token:
                return str(root)
            return str(Path(str(root), *[part for part in text[len(token) + 1:].replace(chr(92), "/").split("/") if part]))
    return text


def resolve_known_paths(paths, project_root, plugin_root, python, task_root=None):
    """A new dict with every token of `paths` resolved against these roots; an absolute path and any other value are
    untouched, and so is a token whose root is not given. Not a dict: returned as it is."""
    if not isinstance(paths, dict):
        return paths

    def one(text):
        got = _resolve_text(text, project_root, plugin_root, python, task_root)
        return text if got is None else got

    return {key: ({name: one(item) for name, item in value.items()} if isinstance(value, dict) else one(value))
            for key, value in paths.items()}


def _carries_token(paths: dict) -> bool:
    values = [v for value in paths.values() for v in (value.values() if isinstance(value, dict) else [value])]
    return any(isinstance(v, str) and (v in TOKENS or v.startswith((PROJECT_TOKEN, PLUGIN_TOKEN, TASK_TOKEN)))
               for v in values)


def _exists(text) -> bool:
    try:
        return Path(text).exists()
    except (OSError, ValueError):
        return False


def _string_items(paths: dict) -> list:
    """[(`key` or `key.name`, value)] for every string a packet carries, in order."""
    out = []
    for key, value in paths.items():
        if isinstance(value, dict):
            out += [(f"{key}.{name}", item) for name, item in value.items() if isinstance(item, str)]
        elif isinstance(value, str):
            out.append((key, value))
    return out


def _leftover_paths(paths: dict) -> list:
    """[(key, name or None, value)] for every absolute path a packet carries."""
    out = []
    for key, value in paths.items():
        if isinstance(value, dict):
            out += [(key, name, item) for name, item in value.items() if _abs_text(item)]
        elif _abs_text(value):
            out.append((key, None, value))
    return out


def names_project(paths) -> bool:
    """Does a dispatch packet depend on the project - a `{project_root}` token anywhere in it, or an absolute
    `project_root`? A packet that does not (the driver's own `{"root": ...}`) runs the same with no project; one
    that does must not run against a project nobody found (t-622: the controller's RUN gate asks this before it
    refuses). Not a dict: False."""
    if not isinstance(paths, dict):
        return False
    return _abs_text(paths.get("project_root")) or any(item.startswith(PROJECT_TOKEN) for _, item in _string_items(paths))


def known_paths_for_dispatch(paths, *, project_root, plugin_root, python, current=None, door="", task_root=None):
    """The `known_paths` a dispatch is recorded with: `paths` resolved against THIS process's roots, or a refusal (RUN).

    `current` is a callable that answers `{"package_fingerprint", "package_version"}` of this package (and, when it can,
    `repository_roots`, `entrypoints`, `scripts_root` from the current config and package), or None when it cannot be read
    (called at most once, and only when needed - hashing the package is not free). Rules, in this order:
      1. a packet that carries `package_fingerprint` is compared with this package's; a different one is refused,
         naming both (the first 12 characters) and both versions - whatever the form of its paths, because a
         legacy packet of another generation names paths that EXIST on this machine too, which is exactly how it
         would run the wrong scripts. A fingerprint this package cannot compute, or a packet with none (a legacy one,
         the driver's own), is not compared: an unknown is not a mismatch (FR-41), and nothing blocked before;
      2. a packet with tokens is resolved against the current roots and returned as a new dict. An absolute path it still
         carries (`repository_roots`, an entrypoint of a spelling the packet kept untokenised) is a leftover of the
         machine that wrote it (t-304 Q6): the keys of `RECOMPUTED_RUN_KEYS` are recomputed from `current`, and any other
         leftover that is not on this machine is refused, naming it, with the door;
      3. a legacy packet (no token) is refused with the paths that are not there when a path a dispatch runs
         (`LEGACY_RUN_KEYS`, the entrypoints) is absolute and missing; then it is refused when its absolute
         `project_root` / `task_root` is not this project / this story (`project_root` / `task_root` given; a key the
         caller does not give is not checked) - it was written for another project's artifacts, and its paths exist
         on this machine too; otherwise it is returned as it is. A legacy packet with no `project_root` /
         `task_root` is the same project's by default - nothing names another one.
    `door` is the sentence that ends a refusal: the command that makes the packet again for this package."""
    if not isinstance(paths, dict) or not paths:
        return paths
    asked = []

    def fresh() -> dict:
        if not asked:
            asked.append((current() if callable(current) else None) or {})
        return asked[0]

    said = paths.get("package_fingerprint")
    if isinstance(said, str) and said.strip():
        now = fresh()
        have = str(now.get("package_fingerprint") or "")
        if have and have != said:
            raise ValueError(
                f"This dispatch packet was made for another package: its package_fingerprint is "
                f"{said[:FINGERPRINT_SHOWN]} (version {paths.get('package_version') or 'unknown'}), this package's is "
                f"{have[:FINGERPRINT_SHOWN]} (version {now.get('package_version') or 'unknown'}). Nothing was "
                f"dispatched - a packet never runs the scripts of another generation. {door}")
    if _carries_token(paths):
        try:
            task_here = str(Path(task_root).resolve()) if task_root else None    # `{task_root}` is the story's own folder
        except (OSError, ValueError):
            task_here = str(task_root)
        out = resolve_known_paths(paths, project_root, plugin_root, python, task_here)
        # a token whose root this process does not have is never handed on: a role would read it as a path
        open_tokens = [(where, item) for where, item in _string_items(out)
                       if item in TOKENS or item.startswith((PROJECT_TOKEN, PLUGIN_TOKEN, TASK_TOKEN))]
        if open_tokens:
            have = [token for token, root in ((PROJECT_TOKEN, project_root), (PLUGIN_TOKEN, plugin_root), (TASK_TOKEN, task_here),
                                              (PYTHON_TOKEN, python)) if root]
            where, item = open_tokens[0]
            token = next(t for t in TOKENS if item == t or item.startswith(t))
            raise ValueError(f"This dispatch packet's {token} token (in {', '.join(w for w, _ in open_tokens)}) has no root in "
                             f"this process; expected one of {', '.join(have)}, or an absolute path. Nothing was dispatched. {door}")
        # t-304 N1 critic F1: a token path with a `..` can resolve OUT of its root into a sibling copy - the same
        # predicate READ uses (`_climbs_out`, one `contained` call), so the two policies cannot disagree
        roots = [project_root, plugin_root, task_here]
        climbing = [(where, original, got) for (where, original), (_w, got) in zip(_string_items(paths), _string_items(out))
                    if _climbs_out(original, got, roots)]
        if climbing:
            raise ValueError("This dispatch packet names a path that climbs out of its root: "
                             + "; ".join(f"{where} {original} resolves to {got}" for where, original, got in climbing)
                             + ", which is inside none of the project, the package and the story. Expected a path under one "
                               f"of them. Nothing was dispatched. {door}")
        leftovers = _leftover_paths(paths)
        if leftovers:
            # the recomputable keys are the current config's and package's, whatever the packet kept; when `current`
            # cannot answer, they are left as they came (an unknown is not a mismatch, FR-41)
            for key in RECOMPUTED_RUN_KEYS:
                if any(item[0] == key for item in leftovers) and key in fresh() and type(fresh()[key]) is type(out.get(key)):
                    out[key] = copy.deepcopy(fresh()[key])
            gone = [f"{key}{'.' + name if name else ''} {value}" for key, name, value in leftovers
                    if key not in RECOMPUTED_RUN_KEYS and not _exists(value)]
            if gone:
                raise ValueError("This dispatch packet carries paths of the copy that wrote it that are not on this machine: "
                                 f"{'; '.join(gone)}. Nothing was dispatched. {door}")
        return out
    entries = paths.get("entrypoints") if isinstance(paths.get("entrypoints"), dict) else {}
    named = [(key, paths[key]) for key in LEGACY_RUN_KEYS if _abs_text(paths.get(key))]
    named += [(f"entrypoints.{name}", value) for name, value in entries.items() if _abs_text(value)]
    gone = [f"{key} {value}" for key, value in named if not Path(value).exists()]
    if gone:
        raise ValueError("This dispatch packet names paths that are not on this machine (it was written by another "
                         f"copy of the project or package): {'; '.join(gone)}. Nothing was dispatched. {door}")
    # t-335 A-n3: the paths all exist - but a packet whose project or story is another one's would run on that one's
    # artifacts (two projects on one disk both hold every path). Either refusal costs one `prepare`.
    elsewhere = [f"{key} {paths[key]} (this one is {here})"
                 for key, here in (("project_root", project_root), ("task_root", task_root))
                 if here and _abs_text(paths.get(key)) and not _same_place(paths[key], here)]
    if elsewhere:
        raise ValueError("This dispatch packet was written for another project or story: "
                         f"{'; '.join(elsewhere)}. Nothing was dispatched - a packet never runs on the artifacts of "
                         f"another project. {door}")
    return paths


# --- the project of a story, found from the story's own place ----------------------------------------------------

def _admits(root, task) -> str:
    """"" when `root` is a project whose artifact root contains `task`, else the reason it is not one.

    `hooklib.artifact_root` goes from LOCATING (where do the stories live) to ADMITTING (does this project own the story):
    the allowed error is rejecting a valid project, which ends as the refusal below; the forbidden one is admitting a
    project its own artifact root does not prove. A config that cannot be read, a blank `artifact_root`, a file where a
    folder should be, all reject the candidate and never raise."""
    try:
        if not (Path(root) / HOME / "config.json").is_file():
            return f"it has no {HOME}/config.json"
    except (OSError, ValueError):
        return f"it has no {HOME}/config.json"
    try:
        import hooklib
        artifacts = hooklib.artifact_root(root=Path(root))
    except Exception:
        return "its config cannot be read"
    if not contained(task, artifacts):
        return "its artifact root does not contain the story"
    return ""


def project_for_task(task_root, hint=None) -> Path:
    """The project the story at `task_root` belongs to, found from the story's OWN place (t-294 A1 requirement 1).

    Candidates, in order: (1) the nearest folder above the task that carries `qa-factory/config.json`; (2) the project
    this process works in (`hooklib.project_root()`); (3) `hint` - a stored `known_paths.project_root`, an absolute string
    or nothing (any other value is no hint). A candidate is accepted only if its artifact root CONTAINS the resolved task
    (`_admits`), so another copy of the project that is still on disk (E2: cmp2 beside man1) never wins over the one the
    story is in, and the factory never adopts a project its artifact root does not prove (E4). A hint that names another
    place than the one found is rejected with ONE stderr note naming both (`hint_note`); nothing is refused while a
    candidate holds. None holds: a ValueError that says what was tried, what was expected and the door (FR-1)."""
    try:
        task = Path(task_root).resolve()
    except (TypeError, OSError, ValueError) as exc:
        raise ValueError(f"A story's folder is required to find its project (got {task_root!r}: {type(exc).__name__}). "
                         "Pass the story's own folder.") from exc
    def nearest():
        return nearest_project(task)

    def process_project():
        import hooklib
        return hooklib.project_root()

    def recorded():
        # a hint on another UNC share than the story's is never asked: its config would be read over the network
        # (allowed error: a valid project on a share ends as the refusal below)
        if _local_abs(hint) and not ((_is_unc(hint) or _is_unc(str(task))) and _drive(hint) != _drive(str(task))):
            return Path(hint)
        return None

    # LAZY, in this order: `hooklib.project_root` may shell out to git for up to 10 s, so it runs only when the nearest
    # folder above the story did not hold it; the hint's turn comes after
    finders = ((f"the nearest folder above the story that has {HOME}/config.json", nearest),
               ("the project this process works in", process_project),
               ("the project the story's state recorded", recorded))
    tried, seen = [], set()
    for label, find in finders:
        try:
            path = find()
        except Exception:
            path = None
        if path is None:
            continue
        try:
            key = _folded(str(path)) if _is_unc(str(path)) else os.path.normcase(os.path.realpath(str(path)))
        except (OSError, ValueError):
            key = str(path)
        if key in seen:
            continue
        seen.add(key)
        why = _admits(path, task)
        if not why:
            found = Path(path).resolve()
            if _local_abs(hint) and not _same_place(hint, found):
                hint_note("project", hint, "the project this story is in", found)
            return found
        tried.append(f"{label} {path}: {why}")
    raise ValueError(f"No project holds the story at {task}: none of the places tried has a {HOME}/config.json whose artifact "
                     f"root contains it ({'; '.join(tried) or 'no candidate places'}). A project is a folder with "
                     f"{HOME}/config.json; the story must sit under that config's artifact root (default {HOME}/artifacts). "
                     "Run from the project root, or pass `--project <dir>` to the driver (a script or a hook takes the "
                     "same folder from CLAUDE_PROJECT_DIR).")


# --- the map a story_run driver writes, and the READ policy over a stored one -------------------------------------

def _artifact_items(task_root):
    """(key, absolute path) of every KNOWN_ARTIFACTS name, through the registry the writers use (one by one, so a failure
    keeps what was read)."""
    from contract import artifact_write_path
    for key, name in KNOWN_ARTIFACTS.items():
        yield key, str(artifact_write_path(task_root, name))


def known_paths(task_root, *, project, plugin, python=None, log=None) -> dict:
    """The light map `story_run` stores at `initialize` (the writer; unchanged by N1, Q2): the six roots and the
    KNOWN_ARTIFACTS paths, with no package fingerprint (a role packet needs no compare - `resolve_runtime` hashes every
    package file and stays in `controller.prepare`). `log(message)` gets the one line a half-installed tree prints (the
    driver passes its own `print`: that line has always been on its stdout)."""
    root = str(Path(task_root).resolve())
    paths = {"task_root": root, "root": root, "project_root": str(project),
             "plugin_root": str(plugin), "scripts_root": str(Path(plugin) / "scripts"),
             "python_executable": str(python or sys.executable)}
    try:
        for key, path in _artifact_items(task_root):
            paths[key] = path
    except Exception as exc:
        # A half-installed tree keeps the six paths above: a packet without the extras is
        # poorer, a packet that cannot be built stops the story.
        message = f"known_paths: the registry could not be read ({type(exc).__name__}: {exc})"
        if log:
            log(message)
        else:
            print(message, file=sys.stderr, flush=True)
    return paths


_GONE = object()      # what `state_paths` reads a value as when it cannot be resolved


def _config_of(project):
    try:
        cfg = json.loads((Path(project) / HOME / "config.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return cfg if isinstance(cfg, dict) else None


def state_paths(stored, task_root, *, project=None, plugin=None, python=None, kind="known_paths") -> dict:
    """A story's stored `known_paths`, as a READER sees them: every stored absolute value is a HINT, resolved now (E1).

    Returns a NEW dict (a reader never writes the state back, FR-45) with the stored keys in their stored order:
      - `task_root` and `root` are the reader's own task root; `project_root` is `project`, else `project_for_task`
        (the stored `project_root` is only its hint); `plugin_root`, `scripts_root` and `entrypoints` are the CALLER's
        package (`plugin`, else the running one - the stored package is never used, and a stored fingerprint is copied
        and never compared: a state reader never refuses on generation); `python_executable` is the caller's;
        `repository_roots` is the current project's config; the KNOWN_ARTIFACTS names are the registry's paths for
        this task. None of these is read from storage;
      - any other key: a token is resolved; an absolute string is re-rooted against the roots the RECORD names (used only
        as text) and resolved against the current ones, and kept as it is only if it is inside the task, the project or
        the package; a value that is not a path (a version, a number) is copied;
      - what cannot be resolved (a token whose root this reader does not have; a path of another copy, another drive, a
        checkout that is not ours) is LEFT OUT of the result, with ONE stderr note: omitting costs a role one search, a
        foreign path costs a wrong project (FR-15 against E7: the second is the forbidden error).
    A stored value that is absent, `{}`, a list (a legacy state) or anything else is no hint: `{}` comes back, and the
    reader has no new refusal. On the same place the result equals the stored map exactly (keys, order, values)."""
    if not isinstance(stored, dict) or not stored:
        return {}
    task = None
    if task_root is not None:
        try:
            task = Path(task_root).resolve()
        except (TypeError, OSError, ValueError):
            task = None
    if project is None and task is not None:
        try:
            project = project_for_task(task, hint=stored.get("project_root"))      # notes a stale hint itself
        except ValueError:
            project = None
    elif project is not None:
        # the caller knows its project (the hook, the driver): a stored root that is another place is replaced, and
        # the replacement is said once, as `project_for_task` says it (critic F4; FR-14/FR-15/FR-41)
        stale = stored.get("project_root")
        if _local_abs(stale) and not _same_place(stale, project):
            hint_note("project", stale, "the project this story is in", project)
    package = Path(plugin) if plugin else package_root()
    interpreter = str(python) if python else sys.executable
    fresh = {}
    if task is not None:
        fresh["task_root"] = fresh["root"] = str(task)
    if project is not None:
        fresh["project_root"] = str(project)
    fresh["plugin_root"], fresh["scripts_root"], fresh["python_executable"] = str(package), str(package / "scripts"), interpreter
    if "entrypoints" in stored:
        fresh["entrypoints"] = {name: str(package / "scripts" / (name + ".py")) for name in ENTRYPOINT_NAMES}
    if "repository_roots" in stored and project is not None:
        cfg = _config_of(project)
        if cfg is not None:
            fresh["repository_roots"] = _repository_roots(project, cfg)
    artifacts = None
    if task is not None:
        try:
            artifacts = dict(_artifact_items(task_root))
        except Exception:
            artifacts = None          # a half-installed tree: those keys are read like any other
    controlled = set(READ_RECOMPUTED_KEYS) | (set(KNOWN_ARTIFACTS) if artifacts is not None else set())
    fresh.update(artifacts or {})
    record = [(TASK_TOKEN, stored.get("task_root") or stored.get("root")), (PROJECT_TOKEN, stored.get("project_root")),
              (PLUGIN_TOKEN, stored.get("plugin_root"))]
    record = [(token, root) for token, root in record if _abs_text(root)]
    ours = [root for root in (task, project, package) if root is not None]
    dropped = []

    def read(label, value):
        if isinstance(value, dict):
            return {name: got for name, item in value.items()
                    for got in [read(f"{label}.{name}", item)] if got is not _GONE}
        if isinstance(value, list):
            return [got for index, item in enumerate(value) for got in [read(f"{label}[{index}]", item)] if got is not _GONE]
        if not isinstance(value, str):
            return copy.deepcopy(value)
        def settled(got, original):
            # a `..` that is under a root by TEXT may climb out of it into a sibling copy: the real place decides
            return None if got is not None and _climbs_out(original, got, ours) else got

        resolved = settled(_resolve_text(value, project, package, interpreter, task), value)
        if resolved is None:
            dropped.append((label, value))
            return _GONE
        if resolved != value or not _abs_text(value):
            return resolved
        moved = _under(value, record)
        if moved != value:
            resolved = settled(_resolve_text(moved, project, package, interpreter, task), value)
            if resolved is not None:
                return resolved
        elif any(contained(value, root) for root in ours):
            return value
        dropped.append((label, value))
        return _GONE

    out = {}
    for key, value in stored.items():
        if key in ("package_fingerprint", "package_version"):
            out[key] = copy.deepcopy(value)          # provenance: copied, never compared
        elif key in ("entrypoints", "repository_roots") and key in fresh and isinstance(value, dict):
            # the subset rule holds at every level (critic F5): only the names the stored map has, each recomputed; a name
            # that cannot be recomputed is left out and named, an empty stored map stays empty
            out[key] = {name: fresh[key][name] for name in value if name in fresh[key]}
            dropped += [(f"{key}.{name}", item) for name, item in value.items() if name not in fresh[key]]
        elif key in controlled:
            if key in fresh and key not in ("entrypoints", "repository_roots"):
                out[key] = fresh[key]
            else:
                dropped.append((key, value))
        else:
            got = read(key, value)
            if got is not _GONE:
                out[key] = got
    if dropped:
        # every omitted LABEL is named; only the values are cut (critic F6)
        named = "; ".join(f"{label}={_short(value, VALUE_MAX)}" for label, value in dropped)
        _emit(kind, named, f"{kind}: the stored path ({named}) is not inside this story's task, project or package here; "
                           "using nothing (left out of the packet)")
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--task-root', required=True)
    parser.add_argument('--project-root')
    import hooklib      # only the command line needs it; the library functions above stay free of it
    args = hooklib.exact_options(parser).parse_args()
    story = hooklib.story_cli('runtime_paths.py', root=args.task_root, key_flag=None)    # a phantom story prints no paths
    print(json.dumps(resolve_runtime(story, args.project_root), indent=2))
