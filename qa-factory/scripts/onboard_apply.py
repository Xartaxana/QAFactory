"""The ONE apply path of an installation: a fresh install and a reinstall are the same plan (t-232).

`plan(root, proposal)` lists what an install would write, rebuild, retire and keep, and joins the
retirement listing to the proposal so the person's single "yes" covers it (the listing is part of
`proposal_hash`). `apply(root, plan, approval_ref)` carries the approved plan out. The proposal is
produced two ways - by the role from discovery (a fresh project) or by
`config_contract.migration_plan` from the old config - in the SAME shape; nothing after that point
knows which.

Invariant, spec-wide: nothing is retired that is carried data, outside the project root, not in
the approved listing, or changed by a person since the summary was made. What holds it:

  * only `install_paths.scan_tree` and a path the person NAMED can be retired; a carried path never
    is (the table's precedence), a directory never is (one file at a time), a link never is;
  * the listing carries the sha256 of every file it names; at apply EVERY listed path is read again
    and one difference refuses the whole apply, nothing written ("the project changed since the
    summary"); no whole-tree hash exists, because hooks write telemetry while onboarding runs;
  * a file the table flags `hook_written` (`dashboard-dirty.json`, `dashboard-refresh.json`, the
    `.dashboard-writer/` folder: a RUNNING session's hooks rewrite them on every call) is never retired, never
    in the sealed listing, never hashed, never a manifest entry, and its stale OS lock is neither removed nor
    counted; the apply asks the table again, so an older sealed listing that still names one is not refused
    on it and does not delete it (`kept: rewritten by a running session`). Every OTHER listed file keeps the
    sha recheck above, so the narrowing is exactly that set and nothing wider (t-298);
  * the mode of a retirement comes from the table's `retire_modes`, per class (owner, F2): delete
    for the factory's own technical data - the discarded rows AND a regenerated file that THIS run's
    regenerate step does not rebuild (its outputs are the table's `regenerate_step`; t-272 item 1) -
    MOVE to `qa-factory/state/retired/<date>/<same relative path>` for anything undetermined (a file
    inside qa-factory/ that no row names and no not_ours row covers, or one the person named; t-272
    item 2), nothing for carried. A file changed since the factory wrote it stays where it is, and
    an unreadable one is listed, never moved;
  * a live writer (an OS-locked `.lock` file, or a lease whose process is alive) refuses the whole
    apply with its door - but only the APPLY: the plan, `--out` and `--listing` read and never refuse,
    they print the locks held right now (`live_locks`); an OS lock is looked at again for up to 10 s
    first (the dashboard writer lets go in seconds); and the ONE exception is the writer lock of the
    session the onboarding itself runs in (`state/cost/.writers/<its session id>/`, found by `session_identity.resolve`), which is not a
    refusal: the onboarding runs inside a session, and its own activity capture would otherwise refuse
    the one session that must run it (t-288). With no session id found nothing is taken for its own. Only an OS lock that the table calls regenerated, under state/, and that
    nobody holds is removed; an existence lock (exit_gate's O_EXCL file), a folder lock and any lock
    under a carried row (artifacts, cost/.writers) are LISTED by name and never removed (t-272 item 6);
  * git is only READ (`git ls-files`, plan time and apply time): the listing names every tracked path
    inside the ignored folder and every tracked deletion or move with the exact `git rm --cached` line;
    the ROLE runs those lines and commits, this script never writes git state (t-272 item 3);
  * the shape of the profiles is a gate (OH3-26): `plan` runs `profile_contract.validate_config` on the proposed configuration
    and a problem the configuration on disk does not already hold over the same row blocks the plan (`blocked`, reason
    `profile_shape`); `main` refuses on it before anything is sealed, recorded or written, and `apply` refuses it too. The
    final half (`--phase final`) writes no configuration and has no gate. The way out is named in the refusal: correct the
    proposal by `references/profile-shape.json`, or write `profiles: []` with the deferral recorded at phase 4;
  * a manifest written by a NEWER factory retires nothing and is not overwritten;
  * order: config -> new-shape files -> `.gitignore` | move the carried records -> regenerate -> retire
    -> manifest LAST. A crash leaves the old manifest (or none) and the next plan recomputes what is
    left. The records an older factory kept in `state/` are MOVED to `records/` (the table's
    `moved_to` rows; bytes unchanged, atomic, before anything is removed - nothing carried is ever
    absent from both places); two different copies are never merged or overwritten, the one not in
    use is listed in `changed_since_install` with `duplicate_of`.

`apply(phase=...)`: `all` runs everything in that order (the headless entry); `early` is the first
half (config, template copies, `.gitignore`) which onboarding runs right after the "yes", because
the role needs the config to prove the login; `final` is the second half, run after the role has
written its documents, which is why the manifest can name them and why the old product passport is
retired only then, behind THIS run's fold receipt.

CLI (stdout is JSON, except `--listing`; FR-14):
  onboard_apply.py --root <project> --preflight              install_exists, manifest status, the version line (p0)
  onboard_apply.py --root <project> [--proposal f] [--answers f] [--also-retire rel ...] [--out f] [--listing]
                                                              the plan, as JSON (or the text a person reads); writes
                                                              NOTHING into the project (FR-45); --out writes the sealed proposal there
  onboard_apply.py --root <project> [--proposal f] [--answers f] --apply [--approval-ref r] [--phase all|early|final]
                                                              apply; with no --approval-ref (the headless entry) the
                                                              command line IS the word and is recorded as such
"""
import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import date as _date, datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import config_contract as C  # noqa: E402
import install_paths as I  # noqa: E402
import profile_contract as PC  # noqa: E402
import project_gitignore as G  # noqa: E402
import runtime_paths as RP  # noqa: E402
import session_identity as SI  # noqa: E402

# --- where things live: the two folders of runtime_paths.py (t-232 section 8) ------------------------
# The carried records are in `records/` (tracked), the machine-local files in `state/` (ignored whole).
# A project an older factory installed has its records under `state/` until THIS install moves them
# (the table's `moved_to` rows); reads go through runtime_paths, which looks at both.
CONFIG_REL = "qa-factory/config.json"
READINESS_REL = f"{RP.HOME}/{RP.STATE}/{RP.READINESS}"
OLD_READINESS_REL = f"{RP.HOME}/{RP.READINESS}"      # where an older factory wrote it, beside the config
DASHBOARD_REL = "qa-factory/state/factory-dashboard.html"
APPROVALS_REL = f"{RP.HOME}/{RP.RECORDS}/{C.APPROVALS_NAME}"
COVERAGE_REL = f"{RP.HOME}/{RP.RECORDS}/coverage-map.md"
PROFILE_REL = "qa-factory/strategy/project-profile.md"
GITIGNORE_REL = ".gitignore"
MANIFEST_REL = I.MANIFEST_REL
# (project path, template file under references/templates/): copied only when the project has none
TEMPLATE_COPIES = (("qa-factory/obligations.md", "obligations.md"),
                   ("qa-factory/factory-backlog.md", "factory-backlog.md"))
LEASE_FILES = ("qa-factory/state/stand-lease.json", "qa-factory/state/execution-leases.json")
# Folders whose files grow while the factory runs (journal, ledger, approvals...): the manifest
# names what an install wrote, not what a story appends to, so a sha would only go stale. Their
# carried files are never retired in any case (`state` holds them in an old-layout project).
RUNTIME_FOLDERS = {RP.STATE, RP.RECORDS}
RECORD_NAME = "retire-record.json"
FOLD_TOKEN = C.FOLD_TOKEN      # the receipt the role's fold step records (config_contract --fold)
PLAN_KEYS = ("write", "regenerate", "retire", "changed_since_install", "not_ours_kept", "locks", "live_locks", "unknown", "refused")
# The scripts the apply's regenerate step runs, in order. The files they write are the table's
# `regenerate_step` (install_paths.regenerate_outputs): the plan reads them from there, so ONE list
# says both what the install rebuilds and which regenerated files it therefore keeps (t-272 item 1).
REGENERATE_SCRIPTS = ("readiness.py", "factory_dashboard.py", "check_coverage.py")
# An existence lock (exit_gate's O_EXCL file) or a folder lock (project_decisions' mkdir) older than
# this is LISTED for the person; younger ones may be held right now and are neither listed nor touched.
OLD_LOCK_HOURS = 24
GIT_NOT_A_REPO = "not a git repository: tracking not checked"


class ApplyRefused(ValueError):
    """A refusal that says what is wrong, what was expected and the move (FR-1, FR-57)."""


def _abs(root, rel: str) -> Path:
    return Path(root).joinpath(*rel.split("/"))


def _today() -> str:
    return _date.today().isoformat()


# --- reading one file for the listing ---------------------------------------------------------

def _summary(path: Path) -> dict:
    """{bytes, mtime, first_line}: what a person needs to recognise a file, never its content."""
    stat = path.stat()
    first = ""
    try:
        with open(path, "rb") as handle:
            chunk = handle.read(1024)
        for raw in chunk.decode("utf-8", "replace").splitlines():
            if raw.strip():
                first = "".join(ch for ch in raw.strip() if ch >= " " and ch != "\x7f")[:80]
                break
    except OSError:
        pass
    return {"bytes": stat.st_size,
            "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "first_line": first}


# --- live writers (E1) -------------------------------------------------------------------------

def _lock_state(path: Path) -> str:
    """'held' when another process holds the OS lock on this file (the same try-lock the writers
    use: event_store, execution_scheduler), 'free' when nobody does, 'unknown' when it cannot be
    tried. A `.lock` file existing is NOT a running session (a live project had four with none
    running). Nothing is written to the file: a file that vanished since the scan is 'unknown', never made."""
    from event_store import file_lock_state
    return file_lock_state(path)


def _holders(value):
    """Every object in a lease file that carries a `pid` - the shape of those files differs
    (a registry of leases, a map by stand) and the question is the same for each."""
    if isinstance(value, dict):
        if "pid" in value:
            yield value
        for item in value.values():
            yield from _holders(item)
    elif isinstance(value, list):
        for item in value:
            yield from _holders(item)


def _holder_state(lease: dict) -> str:
    try:
        pid = int(lease.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    if pid <= 0:
        return "gone"
    try:
        import stand_lease
        return stand_lease._holder_state(lease)
    except Exception:
        return "unknown"       # a holder that cannot be checked is treated as alive: the safe direction


def _age_hours(path: Path) -> float:
    try:
        return max(0.0, (time.time() - path.stat().st_mtime) / 3600.0)
    except OSError:
        return 0.0


THIS_SESSION = "this session"
WRITERS_KEY = ".writers"                  # the table's key of state/cost/.writers/**: one folder per session
DASHBOARD_WRITER_KEY = ".dashboard-writer"
# A live OS lock that is not the running session's own is waited for before the apply refuses. The
# dashboard writer (dashboard_refresh.refresh_project) holds `.dashboard-writer/state/events.lock` for
# the length of ONE TO THREE renders of factory_dashboard.main - expected: seconds (a code-only
# projection that never calls a model); that is an estimate read from the loop, not a measurement, and
# the window below is sized to it. A lease (a story run) is held for minutes: it is never waited for.
LIVE_TRIES = 10
LIVE_WAIT_S = 1.0
_sleep = time.sleep         # injectable: a test must not really wait 9 s


def _own_session() -> str:
    """The id of the session this command runs in, as `session_identity.resolve` finds it (the hook's receipt
    of this very call, and the host's own variable, which must agree). '' when it finds none, or finds two
    answers that differ, or an id that is not safe (a shell run outside any host, an inherited id): then no
    lock is taken for the caller's own. That is the safe direction: a foreign id would mark a foreign live
    writer as this session's own (`_os_holder`) and let the apply through it."""
    return SI.resolve(None, "", "onboard_apply.py")["session_id"]


def _writer_session(rel: str) -> str:
    """The session id of a lock under `<home>/state/cost/.writers/<id>/...`, '' for any other lock."""
    parts = rel.split("/")
    if WRITERS_KEY in parts[:-1]:
        i = parts.index(WRITERS_KEY)
        if i >= 1 and parts[i - 1] == "cost" and i + 1 < len(parts) - 1:
            return parts[i + 1]
    return ""


def _writer_pid(lock_path: Path) -> int:
    """The pid cost_capture recorded in `state/capture.owner` beside a writer's lock (t-165), when that
    process is not provably gone (stand_lease._holder_state); 0 when nothing is known. A record never
    makes a lock live: the OS lock is the proof, this only names who."""
    try:
        data = json.loads((lock_path.parent / "capture.owner").read_text(encoding="utf-8-sig"))
        pid = int(data.get("pid") or 0) if isinstance(data, dict) else 0
    except (OSError, ValueError, TypeError):
        return 0
    return pid if pid > 0 and _holder_state({"pid": pid}) != "gone" else 0


def _os_holder(path: Path, rel: str, own: str) -> str:
    """Who holds a live (or untestable) OS lock: THIS_SESSION for the writer folder of the session
    the caller runs in; 'pid N' when the writer's own record names a process that is not gone;
    'unknown' otherwise (an OS lock does not say who holds it)."""
    session = _writer_session(rel)
    if session and own and session == own:
        return THIS_SESSION
    pid = _writer_pid(path) if session else 0
    return f"pid {pid}" if pid else "unknown"


def find_locks(root, table: dict | None = None) -> list:
    """[{rel_path, state, kind, class, age_hours, action, holder}] for every lock under the factory's
    home (a `*.lock` file or folder) and every lease file whose holder process is alive. Reads only; an
    OS lock is tried and released at once.

    kind comes from the table's `lock_kind` (`os` is the default for a file, `folder` for a folder).
    state: for an `os` lock 'live' (held) | 'stale' (free: provably nobody holds it) | 'unknown'
    (cannot be tried: treated as live by the caller); for an existence or folder lock 'old' (older than
    OLD_LOCK_HOURS) | 'recent' - nothing can prove such a lock stale, because a try-lock calls a held
    O_EXCL file free (t-272 item 6); for a lease file 'live' | 'unknown'.
    action says what the install may do: 'remove' ONLY for an `os` lock that nobody holds and that the
    table calls regenerated (state/**/*.lock) and does not flag `hook_written` (t-298: the stale lock of
    a hook-written row, `.dashboard-writer/`, is 'none' - not removed, not listed, not counted);
    'listed' for what the person is shown and nothing is done
    to (an old existence or folder lock, a free lock under a carried row such as artifacts/ or
    cost/.writers/, a lock no row names); 'none' for a live writer (it refuses the apply) and for a
    recent existence lock.
    holder, for a 'live'/'unknown' lock only ('' for the rest): 'this session' | 'pid N' | 'unknown'. THE ONE
    EXCEPTION to "a live writer refuses the apply": the writer lock of THIS session
    (`state/cost/.writers/<its session id>/`, the id `_own_session` finds) is the activity capture of the very
    session that runs the onboarding, so it would refuse the one session that must run it (a ban with no door,
    FR-57); `_live` leaves it out, and when no session id is found nothing is taken for this session's own."""
    root = Path(root)
    table = table if table is not None else I.load_table()
    home = I.home_of(table)
    own = _own_session()
    out = []

    def add(path: Path, is_dir: bool) -> None:
        rel = path.relative_to(root).as_posix()
        c = I.classify(rel, table=table)
        kind = c["lock_kind"] or ("folder" if is_dir else "os")
        age = _age_hours(path)
        holder = ""
        if kind == "os" and not is_dir:
            state = {"held": "live", "free": "stale"}.get(_lock_state(path), "unknown")
            action = ("remove" if c["class"] == "regenerated" else "listed") if state == "stale" else "none"
            if state == "stale" and c["hook_written"]:
                # t-298: a stale lock under a row a running session's hooks rewrite (the dashboard writer's) is
                # neither removed nor listed nor counted: the next hook makes it again, so removing it only
                # keeps the listing from ever reading "nothing to do". A HELD one is unchanged (waited for, then refuses).
                action = "none"
            if state != "stale":
                holder = _os_holder(path, rel, own)
        else:
            state = "old" if age > OLD_LOCK_HOURS else "recent"
            action = "listed" if state == "old" else "none"
        out.append({"rel_path": rel, "state": state, "kind": kind, "class": c["class"], "age_hours": round(age, 1), "action": action,
                    "holder": holder})

    base = _abs(root, home)
    if base.is_dir():
        for current, dirs, files in os.walk(base):
            for name in list(dirs):
                if name.endswith(".lock"):
                    dirs.remove(name)           # a folder lock is one item: nothing below it is opened
                    add(Path(current, name), True)
            for name in files:
                if name.endswith(".lock"):
                    add(Path(current, name), False)
    for rel in LEASE_FILES:
        path = _abs(root, rel)
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        held = [(h, _holder_state(h)) for h in _holders(data)]
        states = [s for _h, s in held]
        if any(s in ("alive", "unknown") for s in states):
            pids = [str(int(h["pid"])) for h, s in held if s in ("alive", "unknown") and str(h.get("pid") or "").isdigit()]
            out.append({"rel_path": rel, "state": "live" if "alive" in states else "unknown", "kind": "lease",
                        "class": I.classify(rel, table=table)["class"], "age_hours": round(_age_hours(path), 1), "action": "none",
                        "holder": ", ".join(f"pid {p}" for p in pids) if pids else "unknown"})
    return sorted(out, key=lambda r: r["rel_path"])


def _live(locks: list) -> list:
    """The locks that refuse the apply: held (or untestable) and not this session's own."""
    return [lock for lock in locks if lock["state"] in ("live", "unknown") and lock["holder"] != THIS_SESSION]


def _live_after_waiting(root, table) -> tuple:
    """(live locks, tries made). An OS lock may be held for seconds by a writer that is about to
    finish (the dashboard writer), so the apply looks again, LIVE_TRIES times, LIVE_WAIT_S apart,
    before it refuses. A lease is not waited for: a story run holds it for minutes."""
    live, attempt = [], 0
    for attempt in range(1, LIVE_TRIES + 1):
        live = _live(find_locks(root, table))
        if not live or any(lock["kind"] != "os" for lock in live):
            break
        if attempt < LIVE_TRIES:
            _sleep(LIVE_WAIT_S)
    return live, attempt


def _live_door(lock: dict, own: str) -> str:
    """The move that ends a live lock, by what holds it (FR-1, FR-2: nothing is named that cannot be run)."""
    parts = lock["rel_path"].split("/")
    session = _writer_session(lock["rel_path"])
    if lock["kind"] == "lease":
        if parts[-1].startswith("stand-lease"):
            return ("wait until the run or the walks that hold the stand finish and run the onboarding again; if they are known to be "
                    "gone, a person's word releases the stand (every holder of it): stand_lease.py --release --env <stand name> --reason \"<why>\" "
                    "(stand_lease.py --status lists the stands and each holder)")
        return "wait until the run that holds it finishes, then run the onboarding again"
    if session:
        door = f"finish that session (its id is the folder name {session}), then run the onboarding again"
        if not own:
            door += ("; this command could not tell which session it runs in, so if that is the session "
                     "you are in, run the apply from a shell outside it")
        return door
    if DASHBOARD_WRITER_KEY in parts:
        return "wait a moment and run the apply again"
    return "finish the session or run that is writing there, then run the onboarding again"


def live_message(live: list, tries: int) -> str:
    """The apply's refusal for the locks still held after `tries` looks: each lock by path, holder and door."""
    own = _own_session()
    rows = "; ".join(f"{lock['rel_path']} (holder {lock['holder']}): {_live_door(lock, own)}" for lock in live)
    return (f"A factory session is running in this project and still held {len(live)} lock(s) after {tries} look(s)"
            + (f", {LIVE_WAIT_S:g} s apart" if tries > 1 else "") + ". Nothing was changed. " + rows)


# --- the fold receipt (C9) ----------------------------------------------------------------------

def fold_receipt(root, approval_ref: str) -> bool:
    """Is there THIS run's receipt that the old product passport was folded into the project
    profile? A line `{"fold": "product-passport -> project-profile", "for_approval": <ref>}` in
    the approvals log (the role's fold step records it through config_contract with --fold). It
    names the approval by `for_approval`, NOT `approval_ref`: a second line with the same
    `approval_ref` would make the approval ambiguous (config_contract resolves a ref to exactly
    one line). The mere presence of project-profile.md is never a receipt: a profile written by
    hand, by an earlier run, or empty is not proof that the passport's content went into it."""
    try:
        lines = C.approvals_path(root).read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in lines:
        try:
            record = json.loads(line) if line.strip() else None
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("fold") == FOLD_TOKEN and record.get("for_approval") == approval_ref:
            return True
    return False


# --- the install that is already there (p0 step 5) ---------------------------------------------

def table_hits(root, limit: int = 20) -> list:
    """Project paths the table recognises as the factory's own (carried, regenerated or discarded:
    NOT the project's dev factory, and NOT a path whose winning row is `before_install`: the onboarding run's
    own notes), plus a stray first-generation `.gitignore` line. An install
    exists if there is a config OR a manifest OR any of these: a project with old traces and no
    config is never "clean"."""
    root = Path(root)
    table = I.load_table()
    hits = []
    stray = {r["line"] for r in I.gitignore_lines(table)}
    if any(line.strip() in stray for line in G._read_lines(root / GITIGNORE_REL)):
        hits.append(GITIGNORE_REL)
    base = _abs(root, I.home_of(table))
    if base.is_dir():
        for current, _dirs, files in os.walk(base):
            for name in files:
                rel = Path(current, name).relative_to(root).as_posix()
                got = I.classify(rel, table=table)
                if got["before_install"]:
                    continue    # the onboarding run's own notes (B-411): written before any install exists, never a trace of one
                if got["class"] in ("carried", "regenerated", "discarded"):
                    hits.append(rel)
                    if len(hits) >= limit:
                        return hits
    return hits


def preflight(root, *, plugin_root=None, claude_home=None) -> dict:
    """What p0 needs, in one JSON-able dict: install_exists, config_present, manifest
    ('absent'|'ok'|'unreadable', newer), table_hits[], version_line ("" when the versions agree)."""
    root = Path(root)
    manifest = I.read_manifest(root, plugin_root=plugin_root)
    hits = table_hits(root)
    config = _abs(root, CONFIG_REL).exists()
    import hooklib
    return {"install_exists": bool(config or manifest is not None or hits), "config_present": config,
            "manifest": {"status": "absent" if manifest is None else manifest["status"],
                         "newer": None if manifest is None else manifest["newer"],
                         "package_version": None if manifest is None else manifest["package_version"]},
            "table_hits": hits,
            "version_line": hooklib.version_line(root, plugin_root=plugin_root, claude_home=claude_home)}


# --- plan ----------------------------------------------------------------------------------------

def _config_action(current, proposed: dict) -> str:
    if current is None:
        return "create"
    return "none" if json.dumps(proposed) == json.dumps(current) else "update"


def _named_item(root, rel_in, table, modes, changed=frozenset()) -> tuple:
    """(item, None) or (None, refusal) for a path the person named for retirement. Whatever is
    named is MOVED (the person's word is an authority, not a proof that nothing is lost), unless
    the table says the file is the factory's own technical data and the bytes are still the ones
    the factory wrote: that is deleted like the rest of its class."""
    c = I.classify(rel_in, table=table)
    rel = c["rel_path"]
    if c["class"] == "refused":
        return None, {"rel_path": rel, "reason": c["refused"]}
    if c["class"] == "carried":
        return None, {"rel_path": rel, "reason": "carried data is never retired: it is the project's own record, and no word removes it here"}
    if c["hook_written"]:
        # t-319 (critic t-312 F6): a file a running session's hooks rewrite is never retired - `_retire` keeps it
        # whatever its bytes are (t-298) - so a listing that offered it by name would promise a retirement the apply
        # does not do. Refused here, by name, with the reason; the person is not left waiting for a removal.
        return None, {"rel_path": rel, "reason": "a running session's hooks write this file and rebuild it on their own, so it is never "
                                                 "retired, by name or otherwise; nothing is lost by leaving it, and nothing was listed for removal"}
    if c["class"] != "unrecognised" and not c["retire_safe"]:     # an unrecognised path is "not safe" only because no row names it
        return None, {"rel_path": rel, "reason": "a lock or lease file of a running writer is never retired by name"}
    move_root = modes["move_target"].split("<date>")[0].rstrip("/")
    if rel == move_root or rel.startswith(move_root + "/"):
        return None, {"rel_path": rel, "reason": "it is already set aside; empty that folder yourself when you are sure"}
    path, why = I._resolve_inside(root, rel)
    if path is None:
        return None, {"rel_path": rel, "reason": why}
    mode = (I._mode_of(c["retire_mode"], "discarded", table)
            if c["class"] == "discarded" and rel.casefold() not in changed else modes["undetermined"])
    return {"rel_path": rel, "class": c["class"], "source": "named by the person", "generation": c["generation"],
            "requires": c["requires"], "condition": None, "retire_mode": mode}, None


def _manifest_entries(root, table, old, retired: set) -> list:
    """The paths the next manifest names: the factory's own documents at the top of its home
    (literal carried rows two levels deep at most, outside machine-local state), the regenerated
    outputs that exist on this machine (no sha), and what the old manifest named that is still on
    disk, unchanged and not retired - so a path the factory wrote is never forgotten. All of it
    read from the table (FR-13)."""
    home = I.home_of(table)
    entries, seen = [], set()

    def add(rel, cls, local=False):
        if rel.casefold() in seen or rel in retired:
            return
        seen.add(rel.casefold())
        entries.append({"rel_path": rel, "class": cls, "machine_local": local} if local else {"rel_path": rel, "class": cls})

    for rule in I._rules(table):
        glob = rule["glob"]
        if any(ch in glob for ch in "*?"):
            continue
        path = _abs(root, glob)
        if not path.is_file() or MANIFEST_REL == glob:
            continue
        below = glob.split("/")[len(home.split("/")):]
        if rule["class"] == "carried" and not rule["machine_local"] and len(below) <= 2 and not set(below[:-1]) & RUNTIME_FOLDERS:
            add(glob, "carried")
        elif rule["class"] == "regenerated" and rule["machine_local"] and rule["retire_safe"] and not rule["hook_written"]:
            add(glob, "regenerated", True)      # not a hook-written file (t-298): a running session rewrites it, and the manifest never names it
    if old and old["status"] == "ok":
        for e in old["entries"]:
            path = _abs(root, e["rel_path"])
            if not path.is_file() or I.classify(e["rel_path"], table=table)["hook_written"]:
                continue
            if not e["machine_local"] and I.sha256_file(path) != e["sha256"]:
                continue        # changed since: the person's now, not carried forward as the factory's
            add(e["rel_path"], e["class"], e["machine_local"])
    return entries


def _manifest_current(root, entries: list, plugin_root) -> bool:
    m = I.read_manifest(root, plugin_root=plugin_root)
    if m is None or m["status"] != "ok" or m["newer"] is not False or m["package_version"] != m["plugin_version"]:
        return False
    have = {e["rel_path"].casefold() for e in m["entries"]}
    return all(e["rel_path"].casefold() in have for e in entries)


def _readiness_stale(root) -> bool:
    # Only the layout's own place counts: a current report beside the config (where an older factory
    # wrote it) is still rebuilt, in `state/`, and the old one is retired after.
    path = _abs(root, READINESS_REL)
    if not path.is_file():
        return True
    try:
        have = json.loads(path.read_text(encoding="utf-8-sig"))["runtime_paths"]["package_version"]
    except (OSError, ValueError, KeyError, TypeError):
        return True
    return have != C.package_version()


# --- the carried records an older factory kept in state/ (t-232 section 8) ---------------------------

def _move_pairs(root, table) -> tuple:
    """([(from_rel, to_rel)], refused[]): every file the table's `moved_to` rows send from `state/` to
    `records/`, for the files that exist now (a folder row is walked file by file, so a half-moved
    folder is finished, not repeated). A link, or a path that resolves outside the project, is not
    moved and not touched: it is refused with its reason."""
    root = Path(root)
    pairs, refused = [], []
    for m in I.moves(table):
        src_abs = _abs(root, m["from"])
        found = []
        if m["kind"] == "file":
            if os.path.lexists(src_abs):
                found.append((m["from"], m["to"]))
        elif os.path.isdir(src_abs) and not os.path.islink(src_abs):
            for current, dirs, files in os.walk(src_abs):
                dirs.sort()
                for name in sorted(files):
                    rel = Path(current, name).relative_to(root).as_posix()
                    found.append((rel, m["to"] + rel[len(m["from"]):]))
        elif os.path.lexists(src_abs):
            refused.append({"rel_path": m["from"], "reason": "a record folder is expected here, but this is a file or a link: "
                            "nothing in it is moved or touched"})
        for src, dst in found:
            sp, why = I._resolve_inside(root, src)
            dp, why2 = I._resolve_inside(root, dst)
            if sp is None or dp is None or os.path.islink(sp) or not os.path.isfile(sp):
                refused.append({"rel_path": src, "reason": why or why2 or "it is a link or not a plain file: it is not moved and not touched"})
            else:
                pairs.append((src, dst))
    return pairs, refused


def _plan_moves(root, table) -> tuple:
    """(write items, duplicates[], refused[]). A move is a `write` item {rel_path: the new place,
    action 'move', source: the old place}: it joins the listing the person's one "yes" covers. Where
    the new place ALREADY holds the same bytes (a crash between the move's two halves) the item
    finishes it; where it holds DIFFERENT bytes (two machines, a crash mid-write) nothing is moved
    or overwritten: the copy that is NOT in use (the older by mtime; runtime_paths reads the newer)
    is listed in `changed_since_install` with `duplicate_of`, never silently."""
    root = Path(root)
    pairs, refused = _move_pairs(root, table)
    items, dups = [], []
    for src, dst in pairs:
        sp, dp = _abs(root, src), _abs(root, dst)
        if not os.path.lexists(dp):
            items.append({"rel_path": dst, "action": "move", "source": src})
        elif os.path.islink(dp) or not dp.is_file():
            refused.append({"rel_path": dst, "reason": "the new place is not a plain file: the record at " + src + " is not moved"})
        elif I.sha256_file(dp) == I.sha256_file(sp):
            items.append({"rel_path": dst, "action": "move", "source": src})
        else:
            win, lose = (dst, src) if dp.stat().st_mtime >= sp.stat().st_mtime else (src, dst)
            dups.append({"rel_path": lose, "expected_sha256": I.sha256_file(_abs(root, win)),
                         "actual_sha256": I.sha256_file(_abs(root, lose)), "written": False, "duplicate_of": win})
    return items, dups, refused


def _move_one(root, src: str, dst: str) -> dict:
    """Move one record, bytes unchanged. `os.replace` is atomic on one volume, so at no moment is the
    file in neither place (invariant: nothing carried is ever absent from both). The sha256 before
    and after is recorded; it differs only if a writer appended while the file moved."""
    sp, dp = _abs(root, src), _abs(root, dst)
    row = {"from": src, "to": dst}
    if not os.path.lexists(sp):
        row["result"] = "already gone"
    elif os.path.islink(sp) or not sp.is_file():
        row["result"] = "kept: no longer a plain file"
    elif os.path.lexists(dp):
        if os.path.islink(dp) or not dp.is_file():
            row["result"] = "kept: the new place is not a plain file"
        elif I.sha256_file(dp) == I.sha256_file(sp):
            try:
                os.unlink(sp)
                row["result"] = "completed: the new copy was already there, the old one removed"
            except OSError as exc:
                row["result"] = f"kept: {exc.__class__.__name__}"
        else:
            row["result"] = "kept: two different copies, nothing overwritten (the newer one is the one in use)"
    else:
        try:
            before = I.sha256_file(sp)
            dp.parent.mkdir(parents=True, exist_ok=True)
            os.replace(sp, dp)
            after = I.sha256_file(dp)
            row.update({"result": "moved", "sha256": before, "sha256_after": after})
            if before != after:
                row["result"] = "moved: a writer appended while it moved"
        except OSError as exc:
            row["result"] = f"kept: {exc.__class__.__name__}"
    return row


def _prune_empty(path: Path) -> None:
    """Remove `path` and the folders below it that are empty (a record folder an earlier factory
    left behind once its files have moved). Never a file; an OS refusal leaves the folder."""
    if not path.is_dir() or path.is_symlink():
        return
    for current, _dirs, _files in os.walk(path, topdown=False):
        try:
            os.rmdir(current)
        except OSError:
            pass


def _move_records(root, table) -> dict:
    pairs, refused = _move_pairs(root, table)
    results = [_move_one(root, src, dst) for src, dst in pairs]
    for m in I.moves(table):
        if m["kind"] == "dir":
            _prune_empty(_abs(root, m["from"]))
    return {"results": results, "refused": refused}


def _prune_up(root, path) -> None:
    """Remove `path` and each parent that is then empty, up to but not including `qa-factory/state/`:
    what a removed file leaves behind (`scheduler-requests/`, `.dashboard-writer/state/`) is not
    something a fresh install has. Folders only, never a file; any OS refusal stops the climb."""
    stop = _abs(root, f"{RP.HOME}/{RP.STATE}")
    current = Path(path)
    while current != stop and stop in current.parents:
        try:
            os.rmdir(current)
        except OSError:
            return
        current = current.parent


# --- git: what the project's repository tracks (t-272 item 3) ---------------------------------------

def _git(root, *args) -> tuple:
    """(returncode, stdout bytes). Read-only commands only: this module never writes git state."""
    try:
        done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=60)
        return done.returncode, done.stdout
    except (OSError, subprocess.SubprocessError):
        return None, b""


def git_tracked(root) -> dict:
    """What git tracks under `qa-factory/`, READ-ONLY (`git rev-parse`, `git ls-files`):
    {status: 'repo' | 'none' | 'unavailable', tracked: [project-relative paths]}. 'none' = the project is
    not inside a git work tree; 'unavailable' = git could not be run or answered - the caller says so
    and checks nothing (FR-41: an unknown is never reported as 'nothing tracked')."""
    code, out = _git(root, "rev-parse", "--is-inside-work-tree")
    if code is None:
        return {"status": "unavailable", "tracked": []}
    if code != 0 or out.decode("utf-8", "replace").strip() != "true":
        return {"status": "none", "tracked": []}
    code, out = _git(root, "ls-files", "-z", "--", I.home_of(I.load_table()))
    if code != 0:
        return {"status": "unavailable", "tracked": []}
    return {"status": "repo", "tracked": sorted(p for p in out.decode("utf-8", "replace").split("\0") if p)}


def _git_rm_line(rel: str) -> str:
    """The exact line the role runs: `git rm --cached <path>`; a path with anything outside the plain
    set is double-quoted."""
    plain = all(ch.isalnum() or ch in "._/+@%-" for ch in rel)
    return "git rm --cached " + (rel if plain else '"' + rel.replace('"', '\\"') + '"')


def tracking(root, changes: list) -> dict:
    """What the listing says about git, for the changes this install makes. `changes`: [(path, what)]
    - the tracked-or-not paths this run deletes, sets aside, moves away from or removes. Always the same
    keys (FR-14):

      checked            False when git was not asked or could not answer
      line               None, or the one line saying why nothing was checked
      tracked_in_state[] tracked paths inside the ignored qa-factory/state/ ("tracked inside the ignored
                         folder": git keeps them although the block ignores the folder)
      tracked_changes[]  {rel_path, what}: a change of this run to a TRACKED path (a tracked deletion or move)
      tracked_ignored[]  tracked paths the `.gitignore` block now covers INSIDE a tracked folder (the generated
                         files of a story: evidence, fragments, impl-diff; OH3-33), read from the same table the
                         block is derived from (install_paths.ignored_inside_tracked); a project that committed
                         them before the block named them keeps them until the role runs the line
      git_rm[]           the exact `git rm --cached <path>` line for each of those (state, ignored-inside-tracked and
                         changes), sorted: what the ROLE runs after the person's yes (this script never does); then
                         `git add .gitignore qa-factory` / the commit takes the rest."""
    out = {"checked": False, "line": None, "tracked_in_state": [], "tracked_ignored": [], "tracked_changes": [],
           "git_rm": []}
    found = git_tracked(root)
    if found["status"] == "none":
        out["line"] = GIT_NOT_A_REPO
        return out
    if found["status"] == "unavailable":
        out["line"] = "git could not be run: tracking not checked"
        return out
    tracked = {p.casefold(): p for p in found["tracked"]}
    state_prefix = f"{RP.HOME}/{RP.STATE}/".casefold()
    out["checked"] = True
    out["tracked_in_state"] = [p for p in found["tracked"] if p.casefold().startswith(state_prefix)]
    out["tracked_ignored"] = [p for p in found["tracked"] if I.ignored_inside_tracked(p)]
    seen = set()
    for rel, what in changes:
        key = rel.casefold()
        if key in tracked and key not in seen:
            seen.add(key)
            out["tracked_changes"].append({"rel_path": tracked[key], "what": what})
    out["tracked_changes"].sort(key=lambda r: r["rel_path"])
    paths = sorted(set(out["tracked_in_state"]) | set(out["tracked_ignored"])
                   | {c["rel_path"] for c in out["tracked_changes"]})
    out["git_rm"] = [_git_rm_line(p) for p in paths]
    return out


PROFILE_SHAPE = PLUGIN_ROOT / "references" / "profile-shape.json"
_ROW_LINE = re.compile(r"^(profiles|implementation_repos|managed_dependencies)\[(\d+)\]")
_CROSS_ROW_LINE = re.compile(r"^(profiles|implementation_repos)\[\d+\]\.(profile_id|execution_profile_id):")
_WHOLE_KEY_LINE =re.compile(r"^(profiles|implementation_repos|managed_dependencies):")


def _carrier_same(line: str, current: dict, proposed: dict) -> bool:
    """Whether the row (or key) a validator line is ABOUT is the same value in the configuration on disk and in the
    proposal. The validator's lines carry a path and no value, so the same words can stand over two different rows (a new
    row at an index where the old one had the same kind of fault): a line is inherited only when its carrier is equal too.
    ERROR DIRECTION: only toward `new` (a refusal): an unreadable line, a row moved to another index, a missing row, are `new`."""
    row = _ROW_LINE.match(line)
    if row:
        key, index = row.group(1), int(row.group(2))
        a, b = current.get(key), proposed.get(key)
        if not (isinstance(a, list) and isinstance(b, list) and index < len(a) and index < len(b)):
            return False
        if a[index] != b[index]:
            return False
        # a line that names ANOTHER row's fact (a duplicate id, a profile that is not there) also needs the profiles equal
        # (read by the PATH of the line, never by the validator's words: a reworded text still errs toward `new`)
        return not _CROSS_ROW_LINE.match(line) or current.get("profiles") == proposed.get("profiles")
    whole = _WHOLE_KEY_LINE.match(line)
    if whole:
        return current.get(whole.group(1)) == proposed.get(whole.group(1))
    return current == proposed


def _profile_problems(current, proposed) -> dict:
    """OH3-26: the problems of the proposal's `profiles`, `implementation_repos` and `managed_dependencies`, in two lists:
    `new` (the proposal brings them: they refuse) and `inherited` (the configuration on disk already has the very same line over
    the very same row: they are shown, the factory does not change them now, so a project with an old minimal profile can still
    be reinstalled - builder-rules 9). `current` None (a fresh project) makes everything new. `removed`: the ids of the
    profiles on disk when the proposal holds none (what the person is told is going away).
    ERROR DIRECTION: only toward refusal - a validator that raises is one `new` line, never a pass (AR-28)."""
    try:
        found = PC.validate_config(proposed)
    except Exception as exc:     # noqa: BLE001 - what could not be checked is not a pass
        return {"new": [f"profiles: could not be checked ({type(exc).__name__})"], "inherited": [], "removed": []}
    out = {"new": [], "inherited": [], "removed": _removed_profiles(current, proposed)}
    before = set()
    if isinstance(current, dict) and isinstance(proposed, dict):
        try:
            before = set(PC.validate_config(current))
        except Exception:        # noqa: BLE001 - nothing is inherited from a file that cannot be read
            before = set()
    for line in found:
        same = line in before and isinstance(current, dict) and _carrier_same(line, current, proposed)
        out["inherited" if same else "new"].append(line)
    return out


def _removed_profiles(current, proposed) -> list:
    """The ids of the profiles `current` holds when `proposed` holds none (an empty list or no key)."""
    if not isinstance(current, dict) or not isinstance(proposed, dict) or proposed.get("profiles"):
        return []
    held = current.get("profiles")
    return [p["profile_id"].strip() for p in held if isinstance(p, dict) and isinstance(p.get("profile_id"), str)
            and p["profile_id"].strip()] if isinstance(held, list) else []


def _profile_refusal(problems: list) -> str:
    """FR-1: what is wrong (every line, never a slice), what was expected, and the doors a ROLE can use (FR-2)."""
    return (f"{len(problems)} problem(s) in the profiles, implementation_repos or managed_dependencies of the proposal; "
            "nothing was sealed or written:\n" + "\n".join(f"  - {line}" for line in problems) + "\n"
            "Expected: `commands` is an object keyed by command name, `one_test` is the command that runs one test, and every "
            "other field as in the sample. Correct the proposal by " + str(PROFILE_SHAPE) + " and run this command again; if "
            "the person says the profiles can wait, write `profiles: []` and `implementation_repos: []` (a repository row names "
            "its profile) and record the deferral at phase 4 (`project_decisions.py add --field-ref /profiles ...`).")


def _planned_changes(retire: list, write: list, regenerate: list) -> list:
    """[(path, what)] of what a plan would do to paths git may track."""
    out = [(r["rel_path"], "deleted" if r["retire_mode"] == "delete" else "set aside") for r in retire]
    out += [(w["source"], f"moved to {w['rel_path']}") for w in write if w["action"] == "move"]
    out += [(r["rel_path"], "deleted") for r in regenerate if r["action"] == "remove"]
    return out


def plan(root, proposal: dict, *, named=(), date: str | None = None, plugin_root=None,
         context: dict | None = None, check_input: bool = True) -> dict:
    """What an install of this proposal would do to `root`. Writes nothing (FR-45). Always the same
    keys (FR-14):

      date                the run's day (NOT in the hashed listing)
      proposal            the sealed proposal: yours + `listing`, `proposal_hash` over both
      manifest            {status 'absent'|'ok'|'unreadable', reason, newer, package_version}
      install_exists      a config, a manifest or a table hit is present
      write[]             {rel_path, action 'create'|'update'|'rewrite'|'move', source} ('move': rel_path
                          is the new place of a carried record, source the old one; no sha - a record grows)
      regenerate[]        {rel_path, action 'rebuild'|'remove', by, reason}
      retire[]            {rel_path, class, retire_mode 'delete'|'move', sha256, summary{bytes, mtime,
                          first_line}, source, generation, requires[]}
      retire_blocked      None | 'newer_manifest' | 'plugin_version_unknown' (then retire is [])
      changed_since_install[], not_ours_kept[], unknown[]   see install_paths.scan_tree; a record that stands in
                          BOTH places with different bytes is added to changed_since_install with
                          `duplicate_of` (the copy in use) and nothing is moved over it
      set_aside           None | {rel_path, files, bytes}: what earlier runs moved aside
      locks[]             {rel_path, state, kind 'os'|'exclusive_create'|'folder'|'lease', class, age_hours,
                          action 'remove'|'listed'|'none', holder}: see find_locks
      live_locks[]        {rel_path, kind, holder 'this session'|'pid N'|'unknown'}: the locks held right now
                          (a report, never a stop: only the apply waits for them and refuses)
      tracking            {checked, line, tracked_in_state[], tracked_ignored[], tracked_changes[], git_rm[]}: see tracking();
                          what git tracks of the above, read only, NOT sealed (a commit elsewhere must not
                          void the person's word)
      refused[]           {rel_path, reason}
      blocked             None | {reason, message}: nothing may be applied. `profile_shape` (OH3-26): the proposal
                          brings a NEW problem into profiles / implementation_repos / managed_dependencies (a live
                          writer is `live_locks` now, not a block); `main` refuses on it before anything is sealed,
                          recorded or written, and `apply` refuses on it too
      profile_problems    {new[], inherited[], removed[]} (OH3-26): the validator's lines for the three lists above,
                          `new` those the proposal brings, `inherited` those the configuration on disk already has over
                          the same row (shown, not refused: a reinstall is never locked by what the project already
                          holds), `removed` the profile ids on disk when the proposal holds no profile. Not in the
                          sealed listing, not hashed. With `check_input` False (the final half): all three empty
      needs_answers[]     JSON pointers the proposal still waits on
      nothing_to_do       True when a person has nothing to approve (K8): no write, rebuild, retirement,
                          question, conflict, git untracking line, or two-copies duplicate left to look at

    The listing sealed into the proposal is {retire[] (without summaries), write[], regenerate[]}.

    OH3-31: with `check_input` the proposal first gets every template key it lacks (`config_contract.fill_proposal`: the template's
    value, a row in `added`; a project fact - config-keys.json `project_fact` - is never written, `not_filled` names it); the
    sealed proposal and `proposal_hash` include them. A proposal of one test command is not filled."""
    root = Path(root)
    if not isinstance(proposal, dict) or not isinstance(proposal.get("proposed_config"), dict):
        raise ApplyRefused("the proposal has no proposed_config: for a project with no configuration the role writes "
                           "it from discovery first; for one that has a configuration, ask for the migration plan "
                           "(config_contract.py --root <project> --migration-plan) and give that")
    table = I.load_table(plugin_root)
    modes = I.retire_modes(table)
    current = C.read_config_file(root)      # raises ConfigUnreadable with its door
    proposal = copy.deepcopy(proposal)
    if proposal.get("input_hash") in (None, ""):
        proposal["input_hash"] = C._json_hash(current)
    elif check_input and proposal["input_hash"] != C._json_hash(current):
        # `check_input` is off for the second half of an apply: by then the first half has written
        # the configuration (and the role may have added to it), so it is no longer the input.
        raise ApplyRefused("the project's configuration changed since this proposal was made: make the proposal again "
                           "from the configuration as it is now")
    if check_input:
        # OH3-31. POSITION, and the invariant it keeps: before `proposed` below and before `_profile_problems`, so that the keys
        # the template adds are in `proposed_config` (hashed by `proposal_hash`, shown by the listing's "N setting(s) this version
        # added") and the profile gate judges the whole; and only here, where the proposal is sealed - `final` writes no
        # configuration. A second pass over a sealed proposal finds every key present and changes nothing (the hash holds).
        C.fill_proposal(proposal)
    proposed = C._canonical_order(copy.deepcopy(proposal["proposed_config"]), C.canonical_template(), "/", [])
    if context is None:
        import install_smoke
        context = {"package_fingerprint": install_smoke.package_fingerprint()}
    out = {k: [] for k in PLAN_KEYS}
    out.update({"date": date or _today(), "retire_blocked": None, "set_aside": None, "blocked": None,
                "needs_answers": C.unanswered_pointers(proposal),
                "profile_problems": {"new": [], "inherited": [], "removed": []}})
    if check_input:
        # OH3-26: the gate of the profiles' shape. `final` writes no configuration, so it has no gate (a refusal there would
        # leave the installation half done); the proposal of ONE command (`C.command_kind`) never gets here.
        out["profile_problems"] = _profile_problems(current, proposed)
        if out["profile_problems"]["new"]:
            out["blocked"] = {"reason": "profile_shape", "message": _profile_refusal(out["profile_problems"]["new"])}

    # what this run writes or rebuilds (scan_tree never retires these): the config, the manifest, the
    # template copies, and every output of the regenerate step (the table's `regenerate_step`). Whatever
    # else is REGENERATED and sits in the tree is not rebuilt by this run: scan_tree retires it
    # (retire_unbuilt, t-272 item 1) - listed by name under the one "yes".
    cfg_action = _config_action(current, proposed)
    written = ([CONFIG_REL, MANIFEST_REL, READINESS_REL, DASHBOARD_REL] + [rel for rel, _ in TEMPLATE_COPIES]
               + I.regenerate_outputs(table, REGENERATE_SCRIPTS))
    scan = I.scan_tree(root, written, manifest="auto", context=context, table=table, plugin_root=plugin_root, retire_unbuilt=True)
    out["manifest"] = scan["manifest"]
    out["refused"] = list(scan["refused"])
    out["unknown"] = list(scan["unknown"])
    out["retire_blocked"] = scan["retire_blocked"]
    out["install_exists"] = bool(current is not None or scan["manifest"]["status"] != "absent" or table_hits(root, 1))

    # retire: the table's and manifest's candidates + what the person named
    candidates = {c["rel_path"].casefold(): c for c in scan["retire"]}
    if not scan["retire_blocked"]:
        changed_keys = {c["rel_path"].casefold() for c in scan["changed_since_install"]}
        for rel_in in named:
            item, why = _named_item(root, rel_in, table, modes, changed_keys)
            if why:
                out["refused"].append(why)
            elif item["rel_path"].casefold() not in candidates:
                candidates[item["rel_path"].casefold()] = item
        # t-272 item 2 (the owner's rule applied literally): a file inside qa-factory/ that no table row
        # names and no not_ours row covers is UNDETERMINED - not carried, not provably the factory's own
        # technical data - so it is not left lying (that is how a chimera of generations is made) and not
        # deleted either: it is MOVED to retired/<date>/<same relative path>, listed, recoverable, under
        # the one "yes". A file changed since the factory wrote it never gets here (scan_tree reports
        # it under changed_since_install, which stays in place), nor does an unreadable one (unknown).
        for item in scan["not_ours_kept"]:
            if item["reason"] == "unrecognised" and item["rel_path"].casefold() not in candidates:
                candidates[item["rel_path"].casefold()] = {
                    "rel_path": item["rel_path"], "class": "unrecognised", "source": "no row of the factory names it",
                    "generation": None, "requires": [], "condition": None, "retire_mode": modes["undetermined"]}
    named_keys = {I.normalize_rel(n)[0].casefold() for n in named if I.normalize_rel(n)[0]}
    for key in sorted(candidates):
        c = candidates[key]
        path, why = I._resolve_inside(root, c["rel_path"])
        if path is None or os.path.islink(path):
            out["refused"].append({"rel_path": c["rel_path"], "reason": why or "a link is never retired"})
        elif path.is_dir():
            out["refused"].append({"rel_path": c["rel_path"], "reason": "a folder is never retired as a whole: only single "
                                   "files, so nothing inside it is lost by a pattern"})
        elif path.is_file():
            out["retire"].append({"rel_path": c["rel_path"], "class": c["class"], "retire_mode": c["retire_mode"],
                                  "sha256": I.sha256_file(path), "summary": _summary(path), "source": c["source"],
                                  "generation": c["generation"], "requires": list(c["requires"])})
        else:
            out["refused"].append({"rel_path": c["rel_path"], "reason": "there is no such file"})
    # Only what could be retired is worth reporting as changed: a carried file is never retired, and
    # config.json in particular is rewritten by post-approval writers after every install (E4: the
    # keys the table declares `written_by` are outside the "changed since" check altogether).
    out["changed_since_install"] = [c for c in scan["changed_since_install"]
                                    if I.classify(c["rel_path"], table=table)["class"] != "carried"]
    move_root = modes["move_target"].split("<date>")[0].rstrip("/")
    kept = []
    for item in scan["not_ours_kept"]:
        key = item["rel_path"].casefold()
        if key in named_keys and any(r["rel_path"].casefold() == key for r in out["retire"]):
            continue
        if item["rel_path"] == move_root or item["rel_path"].startswith(move_root + "/"):
            continue        # what earlier runs set aside is reported once, below, not as an unknown
        if item["reason"] == "unrecognised" and not scan["retire_blocked"]:
            continue        # undetermined: it is a retire item above (moved aside), or refused with its reason
        kept.append(item)
    out["not_ours_kept"] = kept
    base = _abs(root, move_root)
    if base.is_dir():
        files = [Path(cur, n) for cur, _d, names in os.walk(base) for n in names]
        out["set_aside"] = {"rel_path": move_root, "files": len(files), "bytes": sum(f.stat().st_size for f in files if f.is_file())}

    # writers (E1, t-272 item 6): a stale OS lock of a regenerated row is removed; every other lock (an old
    # existence or folder lock, any lock under a carried row, one no row names) is only LISTED - `action` in
    # find_locks says which, from the table, not from here. A lock held right now is REPORTED (`live_locks`),
    # never a stop: the plan and the sealed proposal only read, and the onboarding runs inside a session whose
    # own hooks hold locks (t-288, found by a live reinstall); the apply is what waits for them and refuses
    out["locks"] = find_locks(root, table)
    out["live_locks"] = [{"rel_path": lock["rel_path"], "kind": lock["kind"], "holder": lock["holder"]}
                         for lock in out["locks"] if lock["state"] in ("live", "unknown")]
    for lock in out["locks"]:
        if lock["action"] == "remove":
            out["regenerate"].append({"rel_path": lock["rel_path"], "action": "remove", "by": "onboarding",
                                      "reason": "a lock file left by a session that is over"})

    # what is written
    if cfg_action != "none":
        out["write"].append({"rel_path": CONFIG_REL, "action": cfg_action, "source": "proposal"})
    for rel, template in TEMPLATE_COPIES:
        if not _abs(root, rel).exists():
            out["write"].append({"rel_path": rel, "action": "create", "source": f"references/templates/{template}"})
    if G.missing_lines(root):
        out["write"].append({"rel_path": GITIGNORE_REL, "action": "rewrite", "source": "project_gitignore.GITIGNORE_BLOCK"})
    moved, duplicates, move_refused = _plan_moves(root, table)
    out["write"].extend(moved)
    out["refused"].extend(move_refused)
    out["changed_since_install"].extend(duplicates)
    entries = _manifest_entries(root, table, I.read_manifest(root, plugin_root=plugin_root), {r["rel_path"] for r in out["retire"]})
    if scan["manifest"]["newer"] is not True and not _manifest_current(root, entries, plugin_root):
        out["write"].append({"rel_path": MANIFEST_REL, "action": "update" if scan["manifest"]["status"] != "absent" else "create",
                             "source": "this install"})
    config_changes = cfg_action != "none"
    if config_changes or _readiness_stale(root):
        out["regenerate"].append({"rel_path": READINESS_REL, "action": "rebuild", "by": "readiness.py", "reason": "the project's readiness report"})
    if config_changes or not _abs(root, DASHBOARD_REL).is_file():
        out["regenerate"].append({"rel_path": DASHBOARD_REL, "action": "rebuild", "by": "factory_dashboard.py", "reason": "the project's dashboard"})

    out["tracking"] = tracking(root, _planned_changes(out["retire"], out["write"], out["regenerate"]))
    # A record kept in two different copies is something the person still has to look at (FR-10: the
    # listing prints it, so the text must not also say "Nothing to do"); so is a tracked path the repository
    # has not been told to let go of.
    out["nothing_to_do"] = not (out["write"] or out["regenerate"] or out["retire"] or out["needs_answers"]
                                or proposal.get("conflicts") or duplicates or out["tracking"]["git_rm"])
    listing = {"retire": [{k: v for k, v in r.items() if k != "summary"} for r in out["retire"]],
               "write": out["write"], "regenerate": out["regenerate"]}
    proposal["listing"] = listing
    proposal["proposal_hash"] = C.proposal_hash(proposal)
    out["proposal"] = proposal
    return out


# --- the text a person reads (p3) --------------------------------------------------------------
#
# No group of the listing is cut. A group used to stop at 20 lines and say "+N more", and the rest was written nowhere the
# person could open: the proposal file (`--out`) holds the configuration, the removals, the moves and the rebuilds, but
# not the kept, unknown, refused, lock and tracking groups, and the removal record exists only after the "yes". A
# count with no place for the rest is a decision on a slice (FR-8, FR-9): the groups the person approves (the
# configuration change, the files moved, deleted, set aside, and the git removals) are printed whole, and so are the
# groups that only inform, because there is no file that could hold their rest (FR-15).

def _config_lines(proposal: dict) -> list:
    """What the configuration change is, as sub-lines of its bullet: removed and renamed settings
    one per line, the added ones and the kept notes as one line each (a live project has dozens)."""
    dotted = lambda pointer: pointer.lstrip("/").replace("/", ".")      # noqa: E731
    out = []
    for row in proposal.get("removed") or []:
        out.append(f"    removed setting {dotted(row['path'])}: {row['reason']}")
    for row in proposal.get("renamed") or []:
        out.append(f"    renamed setting {dotted(row['from'])} to {dotted(row['to'])}")
    added = [dotted(r["path"]) for r in proposal.get("added") or []]
    if added:
        out.append(f"    {len(added)} setting(s) this version added, with the values a fresh install writes: " + ", ".join(added))
    missing = C.not_filled(proposal.get("proposed_config"))
    if missing:
        out.append("    these settings are facts about your project and were not filled in: " + ", ".join(missing)
                   + "; the readiness report will name them")
    legacy = list((proposal.get("answers_legacy") or {}))
    if legacy:
        out.append(f"    your own wording of {len(legacy)} note(s) is kept whole under answers_legacy ({', '.join(legacy)}"
                   + "); the factory's note text takes its place")
    for row in proposal.get("kept") or []:
        if row.get("reason") == C.DEFAULT_RENAMED:
            # the value DOES change: the word is "changed", not "kept" (t-272 item 5)
            out.append(f"    {C.DEFAULT_RENAMED} - {dotted(row['path'])} held a spelling of the factory's old default and now names its new place")
    if proposal.get("reordered"):
        out.append("    settings put in the order a fresh install writes (values unchanged)")
    return out


def _profile_lines(p: dict) -> list:
    """OH3-26 (FR-6, plain words, no script names): the test profiles the person's "yes" covers. Problems the project already
    holds are shown and left; an empty `profiles` is said out loud (the person's "yes" to this summary is the record of the pass:
    FR-4), and so are the profiles that would be removed."""
    found = p.get("profile_problems")
    if not isinstance(found, dict):
        return []
    lines = []
    if found.get("inherited"):
        lines.append("Your configuration already has these problems in `profiles`; the factory does not change them now:")
        lines.extend(f"  - {line}" for line in found["inherited"])
        lines.append("")
    config = (p.get("proposal") or {}).get("proposed_config")
    if isinstance(config, dict) and not config.get("profiles"):
        lines.append("No test profile will be written: nothing here can run a test until you name the command (gate A asks at "
                     "the first story).")
        if found.get("removed"):
            lines.append("These test profiles will be removed: " + ", ".join(found["removed"]) + ".")
        lines.append("")
    lines.extend(_capability_lines(config))
    return lines


def _capability_lines(proposed) -> list:
    """OH3-30 (FR-6, plain words; AR-23: an unknown is declared, not silent): one line per test profile whose tool nothing in the
    configuration says can do what the profile needs - the profile reads `unknown` or `unsupported`, not ready. Read by the same
    function `readiness` reads (`profile_contract.capability_gaps`, AR-13); a line informs and never refuses (P1): the person's
    "yes" covers it. No profiles, no lines."""
    if not isinstance(proposed, dict):
        return []
    rows = proposed.get("profiles")
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not isinstance(row.get("profile_id"), str):
            continue
        words = []
        for gap in PC.capability_gaps(proposed, row):
            if gap["capability"] not in words:
                words.append(gap["capability"])
        if words:
            out.append(f"The test profile `{row['profile_id']}` will read as not ready: nothing in the configuration says its "
                       f"tool can do {', '.join('`' + w + '`' for w in words)}.")
    if out:
        out.append("")
    return out


def render(p: dict) -> str:
    """The retirement listing and what goes with it, in the person's words (FR-6): what the factory
    will write, rebuild, delete, set aside and leave alone, one line per file with its size, day
    and first line, so a name alone never has to be trusted. Paths are the project's own; no script
    or plugin path appears. The question itself belongs to the summary, not here."""
    lines = []
    if p["blocked"]:
        return p["blocked"]["message"]
    if p["nothing_to_do"]:
        lines.append("Nothing to do: this project already matches what a fresh install writes.")
    else:
        lines.append("What the factory will do after your \"yes\":")
    lines.extend(_profile_lines(p))
    m = p["manifest"]
    if m["status"] == "unreadable":
        lines.append(f"The record of the earlier installation cannot be read ({m['reason']}); nothing is removed on its word. "
                     "Fix the file or move it aside; the factory does not guess.")
    elif m["newer"]:
        lines.append("Nothing is removed: a newer factory wrote this project; update the plugin, then run the onboarding again. "
                     "The record of that installation is left as it is.")
    elif m["status"] == "absent" and (p["retire"] or p["install_exists"]):
        lines.append("There is no record of an earlier installation; the list below is what the factory recognises by name - "
                     "the word you give is the only authority.")
    moves = [w for w in p["write"] if w["action"] == "move"]
    if [w for w in p["write"] if w["action"] != "move"]:
        lines.append("")
        lines.append("Will be written:")
        for w in [w for w in p["write"] if w["action"] != "move"]:
            label = {"qa-factory/config.json": "the project's configuration (qa-factory/config.json)",
                     GITIGNORE_REL: "the factory's block in .gitignore, as one piece (your own lines stay where they are)",
                     MANIFEST_REL: "the record of what this installation wrote (qa-factory/install-manifest.json)"}.get(w["rel_path"], w["rel_path"])
            verb = {"create": "new", "update": "changed", "rewrite": "rewritten"}[w["action"]]
            lines.append(f"  - {label} ({verb})")
            if w["rel_path"] == CONFIG_REL:
                lines.extend(_config_lines(p["proposal"]))
    if moves:
        lines.append("")
        lines.append("Will be moved (your records, bytes unchanged: records now live in qa-factory/records/, which git keeps; "
                     "qa-factory/state/ is for files that differ per machine and git ignores it):")
        lines.extend(f"  - {w['source']} -> {w['rel_path']}" for w in moves)
    rebuilt = [r for r in p["regenerate"] if r["action"] == "rebuild"]
    removed_locks = [r for r in p["regenerate"] if r["action"] == "remove"]
    if rebuilt or removed_locks:
        lines.append("")
        lines.append("Will be rebuilt or cleaned:")
        for r in rebuilt:
            lines.append(f"  - {r['rel_path']} ({r['reason']}, made again from the project's data)")
        if removed_locks:
            lines.append(f"  - {len(removed_locks)} lock file(s) left by sessions that are over")
    def entry(r):
        s = r["summary"]
        tail = "; deleted only after its content is folded into the project profile" if "fold_receipt" in r["requires"] else ""
        return f"  - {r['rel_path']} ({s['bytes']} bytes, changed {s['mtime'][:10]}, starts: \"{s['first_line']}\"{tail})"
    delete = [r for r in p["retire"] if r["retire_mode"] == "delete"]
    move = [r for r in p["retire"] if r["retire_mode"] == "move"]
    if delete:
        lines.append("")
        lines.append("Will be deleted (the factory's own technical data, not your records):")
        lines.extend(entry(r) for r in delete)
    if move:
        lines.append("")
        lines.append(f"Will be set aside, not deleted (moved to qa-factory/state/retired/{p['date']}/; you empty that folder yourself):")
        lines.extend(entry(r) for r in move)
    twins = [c for c in p["changed_since_install"] if c.get("duplicate_of")]
    changed = [c for c in p["changed_since_install"] if not c.get("duplicate_of")]
    if changed:
        lines.append("")
        lines.append("Kept: changed since the factory wrote them (name one if you want it set aside):")
        lines.extend(f"  - {c['rel_path']}" for c in changed)
    if twins:
        lines.append("")
        lines.append("Kept, two different copies of one record (nothing is moved over the other; the newer one is the one in use - "
                     "compare them and remove the copy you do not need yourself):")
        lines.extend(f"  - {c['rel_path']} (the other copy: {c['duplicate_of']})" for c in twins)
    if p["not_ours_kept"]:
        lines.append("")
        lines.append("Kept, not touched:")
        why = {"unrecognised": "the factory does not recognise it as its own", "earlier_generation": "written by an earlier version of the factory",
               "not_ours": "not the factory's"}
        # t-272 item 8: a row of the table that covers MANY paths (the team's dev factory: 59 folders on
        # the project that found this) is ONE line with the count and the row's own name; a lone path
        # keeps its own line
        by_reason: dict = {}
        for n in p["not_ours_kept"]:
            by_reason.setdefault(n["reason"], []).append(n)
        rows = []
        for reason, group in by_reason.items():
            if len(group) > 1 and reason not in why:
                rows.append(f"  - {len(group)} paths, for example {group[0]['rel_path']} ({reason})")
            else:
                rows.extend(f"  - {n['rel_path']} ({why.get(n['reason'], n['reason'])})" for n in group)
        lines.extend(rows)
    if p["unknown"]:
        lines.append("")
        lines.append("Kept, could not be checked:")
        lines.extend(f"  - {u['rel_path']} ({u['reason']})" for u in p["unknown"])
    if p["refused"]:
        lines.append("")
        lines.append("Not touched, and why:")
        lines.extend(f"  - {r['rel_path']} ({r['reason']})" for r in p["refused"])
    listed = [l for l in p["locks"] if l.get("action") == "listed"]
    if listed:
        def lock_note(l):
            if l["class"] == "carried":
                return "inside data the factory keeps"
            if l["kind"] in ("exclusive_create", "folder"):
                return f"its existence is the lock, {l['age_hours'] / 24:.0f} day(s) old"
            return "no row of the factory names it"
        lines.append("")
        lines.append("Lock files left alone - they are never removed here, because the factory cannot prove no session is using them; "
                     "if one is a leftover of a session that is over, delete it yourself:")
        lines.extend(f"  - {l['rel_path']} ({lock_note(l)})" for l in listed)
    if p.get("live_locks"):
        lines.append("")
        lines.append("Held right now by a running session (the apply waits for these, then refuses if still held):")
        lines.extend(f"  - {h['rel_path']} - holder {h['holder']}"
                     + (" (the session this runs in: the apply does not wait for it)" if h["holder"] == THIS_SESSION else "")
                     for h in p["live_locks"])
    t = p.get("tracking") or {}
    if t.get("line"):
        lines.append("")
        lines.append(t["line"])
    if t.get("tracked_in_state"):
        lines.append("")
        lines.append("Tracked inside the ignored folder (your repository keeps these although git ignores qa-factory/state/; after your \"yes\" "
                     "the onboarding runs the line beside each one - it only stops git tracking the file, nothing is deleted by it):")
        lines.extend(f"  - {rel}   {_git_rm_line(rel)}" for rel in t["tracked_in_state"])
    shown_above = {c["rel_path"] for c in t.get("tracked_changes") or []}
    ignored_now = [rel for rel in t.get("tracked_ignored") or [] if rel not in shown_above]
    if ignored_now:
        lines.append("")
        lines.append("Generated files your repository still tracks (git ignores them now; after your \"yes\" the onboarding runs the line "
                     "beside each one - it only stops git tracking the file, nothing is deleted by it):")
        lines.extend(f"  - {rel}   {_git_rm_line(rel)}" for rel in ignored_now)
    if t.get("tracked_changes"):
        lines.append("")
        lines.append("A tracked deletion or move (it will show in your repository's history; the onboarding commits it with .gitignore and qa-factory/):")
        lines.extend(f"  - {c['rel_path']} ({c['what']}){'' if c['rel_path'] in t['tracked_in_state'] else '   ' + _git_rm_line(c['rel_path'])}"
                     for c in t["tracked_changes"])
    if p["set_aside"]:
        s = p["set_aside"]
        lines.append("")
        lines.append(f"Earlier runs set {s['files']} file(s) aside ({s['bytes']} bytes) in {s['rel_path']}; they stay until you empty that folder.")
    return "\n".join(lines)


# --- apply ---------------------------------------------------------------------------------------

def _changed_since_summary(root, listing_retire: list, now_retire: list | None = None, table: dict | None = None) -> list:
    """Paths whose bytes are not the ones the summary showed: a listed file with another sha256, a
    listed path that became a folder or a link, and (when `now_retire` is given) a candidate the
    summary did not list. A listed file that is gone is NOT a change (a first attempt may have
    removed it). A listed file that the table flags `hook_written` NOW is skipped (t-298): a running
    session's hooks rewrite it, so a sealed listing of an older package that still names one cannot
    make the apply refuse on it (`_retire` keeps it, whatever its bytes are). Every OTHER listed file
    keeps its sha recheck (C2)."""
    changed = []
    table = table if table is not None else I.load_table()
    for item in listing_retire:
        if I.classify(item["rel_path"], table=table)["hook_written"]:
            continue
        path = _abs(root, item["rel_path"])
        if os.path.lexists(path) and (os.path.islink(path) or not path.is_file() or I.sha256_file(path) != item["sha256"]):
            changed.append(item["rel_path"])
    if now_retire is not None:
        listed = {i["rel_path"].casefold() for i in listing_retire}
        changed.extend(r["rel_path"] for r in now_retire if r["rel_path"].casefold() not in listed)
    return sorted(set(changed))


def changed_message(paths: list) -> str:
    return ("the project changed since the summary: " + ", ".join(paths) + "; make the summary again so you see what is there now. "
            "Nothing was written.")


def _run_script(root, script: str, args=()) -> dict:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", CLAUDE_PROJECT_DIR=str(root))
    try:
        done = subprocess.run([sys.executable, "-B", str(HERE / script), *args], cwd=str(root), env=env,
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
        tail = (done.stderr or done.stdout or "").strip().splitlines()[-1:] or [""]
        return {"step": script, "ok": done.returncode == 0, "rc": done.returncode, "note": tail[0][:200]}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"step": script, "ok": False, "rc": None, "note": f"could not run: {exc}"[:200]}


def _remove_stale_lock(path: Path) -> str:
    """A lock is removed only while nobody holds it; one that is held again, or cannot be removed,
    stays and is reported (never an error: a writer that started in the meantime is a good reason)."""
    state = _lock_state(path)
    if state != "free":
        return "kept: " + ("a session holds it now" if state == "held" else "cannot be checked")
    try:
        os.unlink(path)
        return "removed"
    except OSError as exc:
        return f"kept: {exc.__class__.__name__}"


def _copy_template(root, rel: str, template: str) -> str:
    target = _abs(root, rel)
    if target.exists():
        return "kept: already there"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PLUGIN_ROOT / "references" / "templates" / template, target)
    return "created"


def _retire(root, listing: dict, date: str, approval_ref: str, proposal_hash: str, table, *, locks: dict | None = None,
            changes: list | None = None) -> dict:
    """Retire what the sealed listing names, one file at a time, each re-checked against the sha256 it was
    shown with. -> {results[], record, tracking}. `locks` ({rel: what happened}) and `changes` ([(path, what)]
    the install already made: records moved, locks removed) go into the record and into `tracking`, the git
    lines the ROLE runs afterwards (this function only READS git)."""
    modes = I.retire_modes(table)
    target_dir = modes["move_target"].replace("<date>", date).rstrip("/")
    fold_ok = fold_receipt(root, approval_ref) and _abs(root, PROFILE_REL).is_file()
    results = []
    for item in listing["retire"]:
        rel, path = item["rel_path"], _abs(root, item["rel_path"])
        row = dict(item, result="")
        if "fold_receipt" in item.get("requires", []) and not fold_ok:
            row["result"] = "waits for the fold"
        elif rel == OLD_READINESS_REL and not _abs(root, READINESS_REL).is_file():
            row["result"] = "kept: its replacement (state/readiness.json) was not built"
        elif not os.path.lexists(path):
            row["result"] = "already gone"
        elif I.classify(rel, table=table)["hook_written"]:
            row["result"] = "kept: rewritten by a running session"       # t-298: never retired, whatever an older listing says
        elif os.path.islink(path) or not path.is_file():
            row["result"] = "kept: no longer a plain file"
        elif I.sha256_file(path) != item["sha256"]:
            row["result"] = "kept: changed since the summary"
        elif item["retire_mode"] == "delete":
            try:
                os.unlink(path)
                row["result"] = "deleted"
                _prune_up(root, path.parent)
            except OSError as exc:
                row["result"] = f"kept: {exc.__class__.__name__}"
        else:
            dest = _abs(root, target_dir + "/" + rel)
            n = 1
            while dest.exists():
                dest = dest.with_name(f"{Path(rel).name}.{n}")
                n += 1
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(dest))
                row["result"] = "moved"
                row["moved_to"] = dest.relative_to(root).as_posix()
                _prune_up(root, path.parent)
            except OSError as exc:
                row["result"] = f"kept: {exc.__class__.__name__}"
        results.append(row)
    record_rel = None
    acted = [r for r in results if r["result"] in ("deleted", "moved")]
    git = tracking(root, list(changes or []) + [(r["rel_path"], "deleted" if r["result"] == "deleted" else "set aside") for r in acted])
    if acted:
        folder = _abs(root, target_dir)
        folder.mkdir(parents=True, exist_ok=True)
        n, record = 1, folder / RECORD_NAME
        while record.exists():
            n += 1
            record = folder / f"retire-record-{n}.json"
        body = {"schema_version": 1, "date": date, "approval_ref": approval_ref, "proposal_hash": proposal_hash,
                "retired": results, "locks": locks or {}, "git_rm": git["git_rm"]}
        record.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        record_rel = record.relative_to(root).as_posix()
    return {"results": results, "record": record_rel, "tracking": git}


def apply(root, plan_: dict, approval_ref: str, *, phase: str = "all", date: str | None = None, plugin_root=None,
          checkpoint=None) -> dict:
    """Carry out an approved plan. -> {applied, phase, nothing_to_do, steps[], retired[], record, manifest}.

    Refuses BEFORE writing anything when: a writer is live (E1) after LIVE_TRIES looks, LIVE_WAIT_S apart
    (a lease is not waited for; this session's own writer is not a writer in this sense); the sealed proposal's hash is not
    its own; no recorded approval of THIS proposal carries `approval_ref`; the proposal still waits
    on answers or holds conflicts; a listed path's sha256 differs from the summary (C2). A plan with
    nothing to do needs no approval and writes nothing (K8). `checkpoint(step)` is called after each
    step: a test's way to stop the apply half-way. Steps never raise on the factory's own scripts
    failing (FR-47): the step says what failed and the apply goes on to a consistent state."""
    root = Path(root)
    if phase not in ("all", "early", "final"):
        raise ApplyRefused(f"phase must be all, early or final, not {phase!r}")
    out = {"applied": False, "phase": phase, "nothing_to_do": bool(plan_.get("nothing_to_do")), "steps": [],
           "retired": [], "record": None, "manifest": None, "tracking": None}
    if plan_.get("blocked"):
        # a library call that goes round `main` does not go round the gate (OH3-26): nothing is written
        raise ApplyRefused(str((plan_["blocked"] or {}).get("message") or plan_["blocked"]))
    if plan_.get("nothing_to_do"):
        return out
    proposal = plan_["proposal"]
    day = date or plan_.get("date") or _today()
    table = I.load_table(plugin_root)
    # FIRST, before anything is written or any other refusal is weighed: a writer that is live and not this
    # session's own (waited for, see _live_after_waiting) means nothing may be touched under it
    live, tries = _live_after_waiting(root, table)
    if live:
        raise ApplyRefused(live_message(live, tries))
    if proposal.get("proposal_hash") != C.proposal_hash(proposal):
        raise ApplyRefused("the proposal was changed after it was sealed: make the summary again")
    try:
        C._approval_record(root, approval_ref, proposal)
    except ValueError as exc:
        raise ApplyRefused(f"{exc}: the person's \"yes\" for exactly this summary has to be recorded first "
                           "(config_contract.py --record-approval with the proposal onboard_apply sealed), then apply") from exc
    waiting = C.unanswered_pointers(proposal)
    if waiting or proposal.get("conflicts"):
        raise ApplyRefused("the factory still needs answers before it writes anything: " + ", ".join(waiting or [c.get("path", "?") for c in proposal["conflicts"]])
                           + ". Ask the person once for all of them, then make the proposal again with their answers "
                           "(--answers <file>: one JSON object mapping each pointer to the whole value the person gave).")
    listing = proposal.get("listing") or {"retire": [], "write": [], "regenerate": []}
    if phase in ("all", "final"):
        changed = _changed_since_summary(root, listing["retire"], table=table)
        if changed:
            raise ApplyRefused(changed_message(changed))

    def step(name, detail=None):
        out["steps"].append({"step": name, **({"detail": detail} if detail is not None else {})})
        if checkpoint:
            checkpoint(name)

    if phase in ("all", "early"):
        current = C.read_config_file(root)
        proposed = C._canonical_order(copy.deepcopy(proposal["proposed_config"]), C.canonical_template(), "/", [])
        if _config_action(current, proposed) == "none":
            step("config", "already the proposed configuration")
        else:
            backup = C.apply_plan(root, proposal, approval_ref)
            step("config", {"backup": backup.relative_to(root).as_posix() if backup else None})
        step("new-shape files", {rel: _copy_template(root, rel, tpl) for rel, tpl in TEMPLATE_COPIES})
        step("gitignore", G.write_block(root) and "block written" or "already in place")
    if phase in ("all", "final"):
        # The carried records move FIRST (and always before the retirement below): they must stand in
        # their new place before anything is removed, and the scripts that run next read them there.
        # Recomputed here from the table, not read from the listing: a move is lossless (bytes kept,
        # atomic), and this very run may have made a file in an old folder after the summary (the
        # config backup of the first half).
        moved = _move_records(root, table)
        step("move records", {"results": moved["results"], "refused": moved["refused"]})
        before = {lock["rel_path"] for lock in find_locks(root, table)}
        runs = []
        for script in REGENERATE_SCRIPTS:        # the names the table's `regenerate_step` declares the outputs of
            if script == "check_coverage.py" and not RP.record(root, "coverage-map.md").is_file():
                continue
            args = {"readiness.py": ["--write"]}.get(script, ["--root", str(root)])
            runs.append(_run_script(root, script, args))
        # The listed stale locks, and the lock stubs the scripts above just made themselves (a lock
        # file nobody holds is a leftover, and the next plan must not find the install's own). Only
        # what find_locks calls removable NOW - an OS lock of a regenerated row that nobody holds - is
        # touched, whatever the listing says (t-272 item 6): a lock under a carried row, an existence
        # lock and a folder lock are never removed, so a listing cannot be made to name one.
        removable = {lock["rel_path"] for lock in find_locks(root, table) if lock["action"] == "remove"}
        wanted = {row["rel_path"] for row in listing["regenerate"] if row["action"] == "remove"}
        wanted |= {rel for rel in removable if rel not in before}
        locks = {}
        for rel in sorted(wanted & removable):
            locks[rel] = _remove_stale_lock(_abs(root, rel))
            if locks[rel] == "removed":
                _prune_up(root, _abs(root, rel).parent)
        step("regenerate", {"locks": locks, "scripts": runs})
        changes = [(m["from"], f"moved to {m['to']}") for m in moved["results"] if str(m.get("result", "")).startswith(("moved", "completed"))]
        changes += [(rel, "deleted") for rel, what in locks.items() if what == "removed"]
        done = _retire(root, listing, day, approval_ref, proposal["proposal_hash"], table, locks=locks, changes=changes)
        out["tracking"] = done["tracking"]
        out["retired"], out["record"] = done["results"], done["record"]
        step("retire", {"record": done["record"]})
        old = I.read_manifest(root, plugin_root=plugin_root)
        if old is not None and old["newer"] is True:
            out["manifest"] = {"written": False, "reason": "a newer factory wrote the manifest; update the plugin"}
        else:
            retired = {r["rel_path"] for r in done["results"] if r["result"] in ("deleted", "moved")}
            entries = _manifest_entries(root, table, old, retired)
            try:
                res = I.write_manifest(root, entries, input_hash=str(proposal.get("input_hash", "")), plugin_root=plugin_root, table=table)
                out["manifest"] = {"written": True, "entries": len(res["written"]), "refused": res["refused"],
                                   "package_version": res["package_version"]}
            except ValueError as exc:
                out["manifest"] = {"written": False, "reason": str(exc)}
        step("manifest", out["manifest"])
    out["applied"] = True
    return out


# --- the equality check: a reinstall ends with the tree a fresh install makes (t-232 section 5) -----

COMPARE_SKIP_TOP = (".git",)       # the version control's own folder is not part of an installation


def _tree_files(root) -> dict:
    """{project-relative path with forward slashes: absolute Path} of every FILE under `root`
    (a link is listed as itself, never followed), without the version control's own folder."""
    root = Path(root)
    out = {}
    for current, dirs, files in os.walk(root):
        rel_dir = Path(current).relative_to(root).as_posix()
        if rel_dir == ".":
            dirs[:] = [d for d in dirs if d not in COMPARE_SKIP_TOP]
        dirs.sort()
        for name in sorted(files):
            path = Path(current, name)
            out[path.relative_to(root).as_posix()] = path
    return out


def _is_extra(rel: str, extras) -> bool:
    """A declared extra is an exact project-relative path, `folder/**` for everything under it, or any
    glob of the install table's own dialect (`*`/`?` inside one segment, `**` for whole segments - the
    table's carried machine-local and not_ours rows are used as they stand, t-272 item 1). Matching is
    case-sensitive: an extra hides the path it names and no other."""
    segs = rel.split("/")
    return any(I._match(segs, str(item).replace(chr(92), "/").split("/"), False) for item in extras)


def _without_fields(value, names: frozenset):
    if isinstance(value, dict):
        return {k: _without_fields(v, names) for k, v in value.items() if k not in names}
    if isinstance(value, list):
        return [_without_fields(v, names) for v in value]
    return value


def _canonical_json(text: str, ignore: frozenset) -> str:
    """The canonical dump of the JSON in `text` without the `ignore` fields (sorted keys, indent 2). Raises ValueError
    when `text` is not JSON; the callers read that as "differing"."""
    return json.dumps(_without_fields(json.loads(text), ignore), indent=2, sort_keys=True, ensure_ascii=False)


def _same_bytes(pa: Path, pb: Path, ignore: frozenset) -> bool:
    try:
        raw_a, raw_b = pa.read_bytes(), pb.read_bytes()
    except OSError:
        return False
    if raw_a == raw_b:
        return True
    if not ignore:
        return False
    try:        # JSON that differs only in the fields the caller named is the same document
        # Canonical DUMPS, never Python `==`: `true`, `1` and `1.0` are equal there and are three different values.
        # The error direction is "differing": a side that is not JSON, not UTF-8 or nested too deep is never "same".
        return (_canonical_json(raw_a.decode("utf-8-sig"), ignore)
                == _canonical_json(raw_b.decode("utf-8-sig"), ignore))
    except (ValueError, UnicodeDecodeError, RecursionError):
        return False


def compare_trees(a, b, declared_extras=(), *, ignore_json_fields: dict | None = None, table: dict | None = None) -> dict:
    """Are two project trees the same installation? -> {missing_in_a[], missing_in_b[], differing[]},
    each a sorted list of project-relative paths. Writes nothing and reads only (FR-45).

      missing_in_a   a file `b` has and `a` lacks   (a path in the reinstalled tree a fresh install would not make)
      missing_in_b   a file `a` has and `b` lacks   (a path a fresh install makes and the reinstall did not)
      differing      a file both have whose BYTES differ (mtimes are never looked at)

    `declared_extras`: paths left out of BOTH trees before comparing - an exact path or `folder/**` - the
    things a reinstall legitimately keeps or adds (machine-local files, the project's own, what was set
    aside). The caller names them; nothing here widens the list. A file the table (install-paths.json)
    calls MACHINE-LOCAL (it differs per machine by definition: absolute paths and clocks) is compared by
    NAME only, in both directions; every other file by name and bytes. `ignore_json_fields`
    ({path: [field names]}): for those JSON files, a difference only in those fields (anywhere inside)
    is no difference. The version control's own top-level `.git` is not part of an installation."""
    table = table if table is not None else I.load_table()
    ignore = {k: frozenset(v) for k, v in (ignore_json_fields or {}).items()}
    left = {r: p for r, p in _tree_files(a).items() if not _is_extra(r, declared_extras)}
    right = {r: p for r, p in _tree_files(b).items() if not _is_extra(r, declared_extras)}
    differing = []
    for rel in sorted(set(left) & set(right)):
        if I.classify(rel, table=table)["machine_local"]:
            continue
        if not _same_bytes(left[rel], right[rel], ignore.get(rel, frozenset())):
            differing.append(rel)
    return {"missing_in_a": sorted(set(right) - set(left)), "missing_in_b": sorted(set(left) - set(right)),
            "differing": differing}


# --- describing a differing file (B-409): ADVICE for a person reading a red comparison, never a verdict --------
# `compare_trees` names paths only and its shape is a contract (FR-14, FR-45); a path in `differing` told the
# second developer's machine nothing (a CRLF `.gitignore` on one side, LF on the other, and "differing" is all
# it said). These two functions are separate, pure and read-only; the caller prints what they return.
import re as _re  # noqa: E402  (kept beside its only users, so this block is the whole of B-409's edit here)

DIFFERENCE_CAP = 10     # files described by `difference_lines`; the rest is one count line
LINE_SHOWN = 80         # characters of a line quoted in a description; longer is cut and ends with "..."


def _lines(text: str) -> list:
    """The lines of `text` split on `\\r\\n|\\r|\\n` ONLY and never `str.splitlines()` (docs/SIBLING_MAP.md axis 7:
    splitlines() also breaks on \\x0b, \\x0c, \\x1c-\\x1e, \\x85, \\u2028 and \\u2029, so a line number would disagree
    with the parser's). One trailing empty element is dropped: a final line break does not start a line."""
    parts = _re.split(r"\r\n|\r|\n", text)
    if parts and parts[-1] == "":
        parts.pop()
    return parts


def _eol_kind(data: bytes) -> str:
    """The line endings of `data`: CRLF, CR, LF (exactly one kind present), `mixed` (two or three), `none`."""
    crlf = data.count(b"\r\n")
    cr = data.count(b"\r") - crlf
    lf = data.count(b"\n") - crlf
    present = [name for name, n in (("CRLF", crlf), ("CR", cr), ("LF", lf)) if n]
    if not present:
        return "none"
    return present[0] if len(present) == 1 else "mixed"


def _quoted(line: str) -> str:
    return ascii(line[:LINE_SHOWN] + ("..." if len(line) > LINE_SHOWN else ""))


def _first_difference(lines_a: list, lines_b: list, ea: str, eb: str):
    """'first difference at line N: A <line> | B <line> (line endings A: .., B: ..)', or None when the lines are equal."""
    for i in range(max(len(lines_a), len(lines_b))):
        line_a = lines_a[i] if i < len(lines_a) else None
        line_b = lines_b[i] if i < len(lines_b) else None
        if line_a != line_b:
            qa = _quoted(line_a) if line_a is not None else f"no line {i + 1}"
            qb = _quoted(line_b) if line_b is not None else f"no line {i + 1}"
            return f"first difference at line {i + 1}: A {qa} | B {qb} (line endings A: {ea}, B: {eb})"
    return None


def _json_difference(text_a: str, text_b: str, ignore: frozenset, ea: str, eb: str):
    """The 'first difference ...' body over the canonical JSON dumps without the `ignore` fields, or None when either side is
    not JSON or the dumps are equal (the caller then reads the raw lines)."""
    try:
        dump = {s: _canonical_json(t, ignore) for s, t in (("A", text_a), ("B", text_b))}
    except (ValueError, RecursionError):                    # not JSON on one side: the raw lines say it
        return None
    return _first_difference(_lines(dump["A"]), _lines(dump["B"]), ea, eb)


def describe_difference(rel: str, pa: Path, pb: Path, ignore: frozenset = frozenset()) -> str:
    """One non-empty line saying HOW the file `rel` differs between two trees (`pa` in A, `pb` in B). Pure: it only
    reads, and it never raises (an exception is a line of its own). It is advice - it never says there is no
    difference (byte-identical files, changed since the comparison, are reported as that), and it never changes what
    `compare_trees` decided. `ignore`: JSON field names `compare_trees` was
    told to excuse for this path; with them, JSON is compared as canonical dumps without those fields (a raw first
    line would point at the excused field)."""
    try:
        raw = {}
        for side, path in (("A", pa), ("B", pb)):
            try:
                raw[side] = Path(path).read_bytes()
            except Exception as exc:                        # a file deleted since the comparison, a permission, a folder
                return f"{rel}: cannot be read on side {side} ({type(exc).__name__})"
        data_a, data_b = raw["A"], raw["B"]
        ea, eb = _eol_kind(data_a), _eol_kind(data_b)
        if data_a == data_b:                                # a path `compare_trees` called differing, rewritten since
            return f"{rel}: the bytes are the same now (changed since the comparison?)"
        if _re.sub(rb"\r\n|\r", b"\n", data_a) == _re.sub(rb"\r\n|\r", b"\n", data_b):
            return f"{rel}: same text, only the line endings differ (A: {ea}, B: {eb})"
        try:
            text_a, text_b = data_a.decode("utf-8-sig"), data_b.decode("utf-8-sig")
        except UnicodeDecodeError:
            return (f"{rel}: not UTF-8 text (A {len(data_a)} bytes, B {len(data_b)} bytes; "
                    f"line endings A: {ea}, B: {eb})")
        found = _json_difference(text_a, text_b, ignore, ea, eb) if ignore else None
        if found:
            return f"{rel} (compared without the fields {', '.join(sorted(ignore))}): {found}"
        found = _first_difference(_lines(text_a), _lines(text_b), ea, eb)
        if found:
            return f"{rel}: {found}"
        bom = lambda d: "yes" if d.startswith(b"\xef\xbb\xbf") else "no"           # noqa: E731
        final = lambda d: "yes" if d.endswith((b"\n", b"\r")) else "no"            # noqa: E731
        return (f"{rel}: same lines, the bytes differ elsewhere (A {len(data_a)} bytes, B {len(data_b)} bytes; "
                f"byte-order mark A: {bom(data_a)}, B: {bom(data_b)}; final line break A: {final(data_a)}, B: {final(data_b)}; "
                f"line endings A: {ea}, B: {eb})")
    except Exception as exc:                                # the description must never be the thing that breaks a run
        return f"{rel}: cannot be described ({type(exc).__name__})"


def difference_lines(a, b, result: dict, *, ignore_json_fields: dict | None = None, cap: int = DIFFERENCE_CAP) -> list:
    """`describe_difference` for the first `cap` paths of `result["differing"]` (the dict `compare_trees` returned),
    with the same per-path `ignore_json_fields` it was given, plus one '+k more differing file(s) not described'
    line when there are more. An empty or absent `differing` gives []. Writes nothing."""
    ignore = {k: frozenset(v) for k, v in (ignore_json_fields or {}).items()}
    differing = list((result or {}).get("differing") or [])
    out = [describe_difference(rel, Path(a).joinpath(*rel.split("/")), Path(b).joinpath(*rel.split("/")), ignore.get(rel, frozenset()))
           for rel in differing[:cap]]
    if len(differing) > cap:
        out.append(f"+{len(differing) - cap} more differing file(s) not described")
    return out


# --- command line --------------------------------------------------------------------------------

def _load_json(path, what: str):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ApplyRefused(f"{path} cannot be read as JSON ({exc}); it must be {what}") from exc


def _login_recipe_problem(recipe) -> str:
    """"" or what is wrong with a `manual_capture.login.ui` recipe, judged by the readers' own functions in manual_capture
    (`recipe_rows_problem`, `landing_rule`: one rule, no copy - AR-13). A recipe REPLACES the factory's default whole, so the
    three field rows are required here; `path` is an address on the stand's frontend."""
    import manual_capture as MC
    if not isinstance(recipe, dict):
        return "the recipe is not an object. Expected {\"path\": ..., \"username\": ..., \"password\": ..., \"submit\": ..., \"landed\": ...}"
    path = recipe.get("path", "/")
    if not (isinstance(path, str) and path.startswith("/")):
        return "`path` is not an address starting with `/`. Expected the sign-in page's path on the stand's frontend, for example \"/\" or \"/login\""
    absent = [k for k in ("username", "password", "submit") if k not in recipe]
    if absent:
        return ("`" + "`, `".join(absent) + "` is missing. Expected each of username, password and submit as {\"test_id\": "
                "\"<data-testid>\"} or {\"role\": \"textbox\", \"name\": \"<accessible name>\"}")
    problem = MC.recipe_rows_problem(recipe)
    if problem:
        return problem.replace("manual_capture.login.ui.", "")
    try:
        MC.landing_rule(recipe)
    except ValueError as exc:
        return str(exc).replace("manual_capture.login.ui.", "")
    return ""


def set_login_ui(root: Path, recipe) -> dict:
    """Record the project's UI sign-in recipe as `manual_capture.login.ui` in qa-factory/config.json (RN1-10 b; the door of gate A's
    `actor_sign_in` finding). The write goes through `config_contract._write_config` - the ONE writer of the config (AR-14), key order
    and migration backup included - and the result passes `C.validate` first. A malformed recipe is refused naming the field and the
    config is left as it was; the same recipe twice writes nothing (`changed: false`). Other keys of `manual_capture` are kept."""
    problem = _login_recipe_problem(recipe)
    if problem:
        raise ApplyRefused(f"manual_capture.login.ui was not recorded: {problem}. The config is unchanged")
    current = C.read_config_file(root)
    if current is None:
        raise ApplyRefused("there is no qa-factory/config.json yet, so there is nothing to record the sign-in recipe in: "
                           "finish the onboarding install first, then record it")
    proposed = copy.deepcopy(current)
    section = proposed.get("manual_capture")
    section = section if isinstance(section, dict) else {}
    login = section.get("login") if isinstance(section.get("login"), dict) else {}
    if login.get("ui") == recipe:
        return {"changed": False, "recorded": "manual_capture.login.ui", "note": "the config already holds this recipe; nothing was written"}
    login["ui"] = recipe
    section["login"] = login
    proposed["manual_capture"] = section
    errors = C.validate(proposed)
    if errors:
        raise ApplyRefused("manual_capture.login.ui was not recorded, the config would be invalid: " + "; ".join(errors) + ". The config is unchanged")
    backup = C._write_config(root, current, proposed, C._json_hash(current), "login-ui-recipe")
    return {"changed": True, "recorded": "manual_capture.login.ui", "backup": str(backup) if backup else None}


def _proposal_for(root: Path, args) -> dict:
    """The proposal the command line works on: with a configuration on disk, the migration plan
    (re-made here from the answers file when one is given); with none, the role's proposal file."""
    config = C.read_config_file(root)
    answers = _load_json(args.answers, "one JSON object mapping a pointer like /dod to the person's answer") if args.answers else None
    given = _load_json(args.proposal, "the proposal JSON") if args.proposal else None
    if config is not None and (given is None or answers is not None or args.price_table_answer):
        return C.migration_plan(config, args.price_table_answer, args.model_id, answers=answers, root=root)
    if given is None:
        raise ApplyRefused("this project has no configuration yet, so there is no proposal to make from one: give the role's "
                           "proposal with --proposal (the configuration it wrote from discovery)")
    return given


def _report_probe(root: Path, done: dict, args):
    """B-220: right after the profiles are written (`--phase all` or `early`) the apply runs the report probe of every profile's
    test command ITSELF - code runs the command on the transition, the LLM relays (P3). The result is part of the apply's JSON
    (`report_probe`): the probe's own object for code, and `person_text` - per profile that needs a word, the proposal
    sentence with its "Do it?" or the explaining words with the three answers. One proposal at most (round 1; the next profile's
    is made by the probe run again after this one is answered). Nothing but the probe's own durable record is written, and the
    proposals go to a temporary folder outside the project. `--no-probe`, a final half, a plan with nothing to do and an apply
    that did not happen run nothing (None). A probe that fails is reported, never raised: the install is already done."""
    if args.no_probe or args.phase == "final" or not done.get("applied") or done.get("nothing_to_do"):
        return None
    try:
        import tempfile
        import onboarding_probe as OP
        found = OP.probe_profiles(root, tempfile.mkdtemp(prefix="qa-onboarding-proposals-"))
        found["person_text"] = OP.person_texts(found)
        return found
    except Exception as exc:     # noqa: BLE001 - FR-47: say what could not be done, leave the install as it is
        problem = f"the report probe could not run ({type(exc).__name__}: {exc})"
        # ONE person sentence that carries the problem (it used to be an empty list: the person never heard of it)
        try:
            text = OP.problem_text(problem)
        except Exception:    # noqa: BLE001 - the module itself could not be imported
            text = ("The check of the test commands could not run: " + problem + ". Nothing was changed by it.\n\n---\nAnswer: "
                    "nothing to answer now.\n")
        return {"problem": problem, "profiles": [], "person_text": [{"profile": "", "move": "tell", "text": text}]}


def _printable(text: str) -> str:
    """The text as the console of this process can show it: a character it cannot encode is written as `\\uXXXX`, so a profile
    named in another script is shown and never kills the listing (the stream itself is not reconfigured: B-413 census)."""
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        return text.encode(encoding, "backslashreplace").decode(encoding)
    except (LookupError, UnicodeError):
        return text.encode("ascii", "backslashreplace").decode("ascii")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--preflight", action="store_true", help="what p0 needs: install_exists, the manifest, the version line")
    ap.add_argument("--proposal", type=Path)
    ap.add_argument("--answers", type=Path, help="a JSON file mapping a pointer like /dod to the person's answer (re-makes the migration plan)")
    ap.add_argument("--price-table-answer", choices=C.PRICE_ANSWERS, help="the person's answer to the old price table question (as config_contract.py)")
    ap.add_argument("--model-id", action="append", default=[], help="with --price-table-answer own: a model id whose old price is the project's")
    ap.add_argument("--also-retire", action="append", default=[], metavar="REL", help="a path the person named for retirement")
    ap.add_argument("--out", type=Path, help="write the sealed proposal here (record the approval on this file)")
    ap.add_argument("--listing", action="store_true", help="print the text a person reads instead of the plan JSON")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--approval-ref", default="")
    ap.add_argument("--evidence-ref", default="")
    ap.add_argument("--no-probe", action="store_true", help="with --apply: do not run the report probe of the test commands (B-220)")
    ap.add_argument("--phase", choices=("all", "early", "final"), default="all")
    ap.add_argument("--set-login-ui", type=Path, metavar="RECIPE_JSON",
                    help="record the JSON object in this file as manual_capture.login.ui in qa-factory/config.json (the project's UI "
                         "sign-in recipe: path, expand {text|test_id}, username/password/submit as {role,name}|{test_id}, landed); "
                         "a malformed recipe is refused naming the field, the same recipe twice writes nothing")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    try:
        if args.set_login_ui:
            print(json.dumps(set_login_ui(root, _load_json(args.set_login_ui, "one JSON object, the sign-in recipe")), indent=2, ensure_ascii=False))
            return 0
        if args.preflight:
            print(json.dumps(preflight(root), indent=2, ensure_ascii=False))
            return 0
        given = _proposal_for(root, args)
        if isinstance(given, dict) and C.command_kind(given):
            # B-220 F9 + F4: a proposal that changes one test command (a probe's cure, or the command a person gave) is not an
            # install, with a ref or without one. One approval changes one key: the apply of it is `config_contract.py --apply`
            # (apply_plan), which writes that key and nothing else. Here `--apply` would run the whole install under it (the
            # manifest, the readiness, the retirement), which nobody was asked about; and with no ref the headless entry would
            # record the command line as the person's word (`config_contract.record_approval` refuses that too).
            if args.apply:
                raise ApplyRefused("this proposal changes one test command (" + str((given["listing"].get("target") or {}).get("profile_id")
                                   or "a command template") + "), and one approval changes one key, so it is not applied here: a "
                                   "person's yes is recorded (`config_contract.py --root <project> --record-approval <the sealed file> "
                                   "--approval-ref " + C.command_approval_ref(given) + " --evidence-ref <their words in the "
                                   "transcript>`) and then applied by `config_contract.py --root <project> --apply <the sealed file> "
                                   "--approval-ref " + C.command_approval_ref(given) + "`, which writes that one key and nothing else. "
                                   "Show the person the sentence first (`onboarding_probe.py --question <the sealed file>`)")
            if args.listing:
                print(C.command_question(given))        # rendered from the sealed file, never from what the maker said
                return 0
        listing_given = given.get("listing") if isinstance(given, dict) else None
        base = {k: v for k, v in given.items() if k != "listing"} if isinstance(given, dict) else given
        made = plan(root, base, named=args.also_retire, check_input=args.phase != "final")
        if made["blocked"]:
            # POSITION (OH3-26): before `--out`, before the approval record, before `apply`. A refused proposal leaves no sealed
            # file, no approval line and nothing written; stdout stays empty (FR-14), the text is on stderr.
            raise ApplyRefused(made["blocked"]["message"])
        if args.apply:
            if listing_given is not None:
                changed = _changed_since_summary(root, listing_given.get("retire") or [], made["retire"], I.load_table())
                if changed:
                    raise ApplyRefused(changed_message(changed))
                made["proposal"] = given
            ref = args.approval_ref
            if not ref and not made["nothing_to_do"]:
                if args.phase == "final":
                    raise ApplyRefused("--phase final needs the --approval-ref of the approval recorded for this summary")
                ref = f"headless:{made['proposal']['proposal_hash'][:12]}"
                C.record_approval(root, made["proposal"], ref, args.evidence_ref or "headless: --apply on the command line")
            done = apply(root, made, ref, phase=args.phase)
            done["report_probe"] = _report_probe(root, done, args)
            print(json.dumps(done, indent=2, ensure_ascii=False))
            return 0
        if args.out:
            args.out.write_text(json.dumps(made["proposal"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if args.listing:
            print(_printable(render(made)))
        else:
            print(json.dumps(made, indent=2, ensure_ascii=False))
        return 0
    except (ApplyRefused, C.ConfigUnreadable) as exc:
        print(f"onboard_apply: refused: {exc}", file=sys.stderr)
        return 2 if isinstance(exc, C.ConfigUnreadable) else 1
    except ValueError as exc:
        print(f"onboard_apply: refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
