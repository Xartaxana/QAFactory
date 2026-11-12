#!/usr/bin/env python3
"""Immutable case versions and story-pinned links.

Case source files remain authoring inputs. This CLI copies their exact bytes into a
content-addressed shared store and pins that version in the task's story link projection.
It never changes an existing version or link for another task.

    case_versions.py --task-root <TASK_ROOT> --all       # pin the whole story (S4 step) and record its scope
    case_versions.py --task-root <TASK_ROOT> --verify    # name what is not pinned

`--verify` prints one JSON line on stdout and exits 0 only when every case is pinned: `{"verified": true, "cases": n}`
with n >= 1. Exit 1 is never a pass: no case file gives `{"verified": false, "cases": 0, "reason": ...}` (`no_cases`,
`names_outside_form`, `pins_without_files`); unpinned cases give a REJECT list on stderr.

`--all` also records the pinned cases as the approved scope (`record_scope`): the answer's `scope` field says
`recorded`, `unchanged` or `not_recorded` (with `scope_note`). The pin never fails because the scope could not be
recorded, and the controller still judges the critic's start and gate A.

`--store` defaults to `store_root()` — the project's `config.cases_root` when it has one,
else `<TASK_ROOT>/work/test-cases`. Pass it only to pin into a different store.
"""
import argparse
import contextlib
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract as C  # noqa: E402
import hooklib  # noqa: E402
from role_cli import command_from_argv, epilog, refuse, run_guarded  # noqa: E402
from event_store import LockBroken, LockBusy, atomic_json, take_file_lock  # noqa: E402


@contextlib.contextmanager
def store_lock(store: Path):
    # The store may be the shared cases_root (a tracked tree): record_holder stays False, the file stays one byte.
    held = _take_lock(store / ".case-versions.lock", "case version store has an active writer")
    try:
        yield
    finally:
        held.release()


def _take_lock(path: Path, busy_head: str):
    """One try on the package's file lock; the caller's own exception type (RuntimeError) in both outcomes, and the
    words follow the outcome: busy = the head + the holder clause, broken = the LockBroken sentence (never the busy head)."""
    try:
        return take_file_lock(path, 0.0, record_holder=False)
    except LockBusy as exc:
        raise RuntimeError(busy_head + "; " + exc.holder_clause) from exc
    except LockBroken as exc:
        raise RuntimeError(str(exc)) from exc


def portable_source_path(source: Path, root: Path | None = None) -> str:
    """Where the authoring file was, said in a way the next clone can still read.

    Audit rule A20: nothing the factory WRITES may carry a machine-local path, and
    `state/story-case-links.json` is a delivered artifact. It was carrying
    `D:/ws/...\\TC-001.md` — a path that resolves nowhere for anyone else and
    publishes a username on the way. Project-relative with forward slashes; a file outside the
    project (a shared case store on another drive) keeps its name only.
    """
    source = Path(source).resolve()
    try:
        from hooklib import project_root
        base = Path(root).resolve() if root is not None else project_root().resolve()
    except Exception:
        base = None
    if base is not None:
        try:
            return source.relative_to(base).as_posix()
        except ValueError:
            pass
    return source.name


def _portable_record_path(record: dict) -> str:
    """A store record written before A20 still holds an absolute `source_path`; the link it
    feeds is made portable here rather than copying the machine-local value on."""
    raw = str((record or {}).get("source_path") or "")
    return portable_source_path(Path(raw)) if raw and Path(raw).is_absolute() else raw.replace("\\", "/")


def read_source_path(record: dict) -> str:
    """The provenance path of a link or store record, tolerating pins written before A20.

    An absolute value from a 0.7.4 story is returned with forward slashes instead of raising:
    a story in flight must not be refused over a field nothing reads for a decision.
    """
    value = ""
    if isinstance(record, dict):
        provenance = record.get("store_provenance")
        value = (provenance or {}).get("source_path") if isinstance(provenance, dict) else ""
        value = value or record.get("source_path") or ""
    return str(value).replace("\\", "/")


def case_id(path: Path) -> str:
    value = C.case_id(path)
    if not value:
        raise ValueError("case file has no stable case ID")
    return value


def validate_candidate(source: Path) -> dict:
    source = Path(source)
    content = source.read_bytes()
    filename_id = case_id(source)
    declared = C.declared_case_id(source)
    if not declared:
        raise ValueError(f"case file has no frontmatter id: {source}")
    if declared != filename_id:
        raise ValueError(f"case identity mismatch: {source} declares {declared} but filename names {filename_id}")
    area = C.case_area(source)
    return {"case_id": filename_id, "area": area, "key": C.case_key(filename_id, area),
            "source": source, "content": content,
            "content_hash": hashlib.sha256(content).hexdigest()}


def validate_batch(sources: list[Path]) -> list[dict]:
    """Read and validate the complete authoring batch before any store or pin mutation.

    A batch is one case per `<area>/TC-NNN`, not per number: `speakers/` and `speaker-detail/`
    both start at TC-001, and reading the number as the identity made the two a collision to
    refuse — or, downstream in `pin`, one link that quietly replaced the other (FB-2428-1).

    Every problem of the batch is one refusal (C4-5 remainder, class K1): the files that cannot be read as a case, in
    the order of `sources`, then the identity collisions among the files that can (a file that failed has no identity to
    collide with, so it is not compared). ONE problem is its own sentence, unchanged; several are the combined refusal
    `detector_verdict.compound` writes. Every unreadable-file sentence names its file, except `case file has no stable
    case ID`, which the stem fallback of `contract.case_id` leaves unreachable for any real file name."""
    candidates, failed = [], []
    for source in sources:
        try:
            candidates.append(validate_candidate(source))
        except ValueError as exc:
            failed.append(str(exc))
    collisions, first = [], {}
    for candidate in candidates:
        prior = first.setdefault(candidate["key"], candidate)
        if prior is not candidate and (prior["source"].resolve() != candidate["source"].resolve() or
                                       prior["content_hash"] != candidate["content_hash"]):
            collisions.append(
                f"case identity collision {candidate['key']}: "
                f"{prior['source']} ({prior['content_hash']}) and "
                f"{candidate['source']} ({candidate['content_hash']})")
    problems = failed + collisions
    if problems:
        from detector_verdict import compound
        raise ValueError(compound(problems))
    return candidates


def create_version(store: Path, source: Path) -> dict:
    source = Path(source)
    candidate = validate_candidate(source)
    content, cid, digest = candidate["content"], candidate["case_id"], candidate["content_hash"]
    version = "cv_" + digest[:20]
    directory = Path(store) / "cases" / cid
    target = directory / (version + ".md")
    meta = directory / (version + ".json")
    with store_lock(Path(store)):
        directory.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(content)
        elif target.read_bytes() != content:
            raise RuntimeError("content-addressed case path conflicts with different bytes")
        if not meta.exists():
            # `area` travels beside the number, never inside it: the store path stays
            # `cases/TC-NNN/<version>.md` (content-addressed, so two areas cannot collide
            # there) and every reader that knows only the number keeps reading `case_id`.
            atomic_json(meta, {"case_id": cid, "area": candidate["area"],
                               "version": version, "content_hash": digest,
                               "source_name": source.name,
                               "source_path": portable_source_path(source),
                               "path": str(target.resolve())})
    return C.load_json(meta)


def link_path(task_root: Path) -> Path:
    return Path(task_root) / "state" / "story-case-links.json"


@contextlib.contextmanager
def task_link_lock(task_root: Path):
    held = _take_lock(Path(task_root) / "state" / ".story-case-links.lock", "story case links have an active writer")
    try:
        yield
    finally:
        held.release()


def _matching(pool: dict, key: str, cfg: dict | None = None):
    """The one entry of `pool` whose key names the same case, or None.

    Links pinned before areas existed are spelled `TC-001`; they still name the case a record
    now calls `speakers/TC-001`, and a bare key that two areas both answer to is nobody's —
    matching it to one of them by chance is exactly how a pin was lost (FB-2428-1)."""
    cfg = C.case_config() if cfg is None else cfg
    found = [value for known, value in pool.items() if C.case_matches(known, key, cfg=cfg)]
    return found[0] if len(found) == 1 else None


def _expected(expected_previous: dict, key: str, cfg: dict | None = None) -> str:
    """The caller's `--expected-previous-version` for this case, in either spelling."""
    if key in expected_previous:
        return expected_previous[key]
    cfg = C.case_config() if cfg is None else cfg
    found = [value for known, value in expected_previous.items() if C.case_matches(known, key, cfg=cfg)]
    return found[0] if len(found) == 1 else None


def pin(task_root: Path, record: dict, expected_previous_version: str | None = None) -> dict:
    with task_link_lock(task_root):
        return _pin_unlocked(task_root, record, expected_previous_version)


def _pin_unlocked(task_root: Path, record: dict, expected_previous_version: str | None = None) -> dict:
    task_root = Path(task_root)
    path = link_path(task_root)
    current = C.load_json(path)
    links = [item for item in current.get("links") or [] if isinstance(item, dict)]
    source = Path(record["path"])
    content = source.read_bytes()
    if hashlib.sha256(content).hexdigest() != record["content_hash"]:
        raise RuntimeError("shared immutable case content does not match its recorded hash")
    # The identity is `<area>/TC-NNN`, so pinning `speakers/TC-001` does not evict
    # `speaker-detail/TC-001` (FB-2428-1). A link written before areas existed carries only
    # the number and still matches, so it is updated in place instead of duplicated.
    cfg = C.case_config(task_root)  # once: the loops below compare every link (B-013)
    key = C.case_link_key(record, cfg)
    prior = [item for item in links if C.case_matches(C.case_link_key(item, cfg), key, cfg=cfg)]
    if prior and prior[-1].get("version") != record["version"]:
        if expected_previous_version != prior[-1].get("version"):
            raise RuntimeError(f"case {key} update requires expected_previous_version="
                               f"{prior[-1].get('version')}")
    snapshot = task_root / "state" / "case-versions" / record["case_id"] / (record["version"] + ".md")
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    if snapshot.exists() and snapshot.read_bytes() != content:
        raise RuntimeError("task case snapshot conflicts with immutable version bytes")
    if not snapshot.exists():
        snapshot.write_bytes(content)
    relative = snapshot.relative_to(task_root).as_posix()
    link = {"case_id": record["case_id"], "version": record["version"],
            "content_hash": record["content_hash"], "path": relative,
            "store_provenance": {"content_hash": record["content_hash"],
                                 "source_name": record.get("source_name", "")}}
    if record.get("area"):
        link["area"] = str(record["area"])
    # One active version per case makes case_index deterministic.  Earlier pins are
    # retained as history for audit, but never become a second live case by accident.
    links = [item for item in links if not C.case_matches(C.case_link_key(item, cfg), key, cfg=cfg)]
    links.append(link)
    history = [item for item in current.get("history") or [] if isinstance(item, dict)]
    for item in prior + [link]:
        identity = (C.case_link_key(item, cfg), item.get("version"))
        if not any((C.case_link_key(old, cfg), old.get("version")) == identity for old in history):
            history.append(item)
    result = {"schema_version": 2, "task_id": task_root.name, "links": links, "history": history}
    atomic_json(path, result)
    return result


def pin_batch(task_root: Path, records: list[dict], expected_previous: dict | None = None) -> dict:
    with task_link_lock(task_root):
        return _pin_batch_unlocked(task_root, records, expected_previous)


def _pin_batch_unlocked(task_root: Path, records: list[dict], expected_previous: dict | None = None) -> dict:
    """Preflight a complete pin batch, then publish its one link projection atomically."""
    task_root, expected_previous = Path(task_root), expected_previous or {}
    current = C.load_json(link_path(task_root))
    # The story's project config, read once: the loops below match every record against every
    # link, and a config stat per comparison made a hundred-case batch take seconds (B-013).
    cfg = C.case_config(task_root)
    active = {C.case_link_key(row, cfg): row for row in current.get("links") or [] if isinstance(row, dict)}
    seen = {}
    contents = {}
    for record in records:
        # Keyed by `<area>/TC-NNN`: a batch holding `speakers/TC-001` and
        # `speaker-detail/TC-001` is two cases, and reading the number as the identity made it
        # one collision to refuse and, before that, one link that replaced the other on
        # recovery — two approved entries gone (FB-2428-1).
        key, version = C.case_link_key(record, cfg), str(record.get("version") or "")
        source = Path(str(record.get("path") or ""))
        content = source.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest != record.get("content_hash"):
            raise RuntimeError(f"shared immutable case content does not match recorded hash for {key}/{version}")
        if key in seen and seen[key] != (version, digest):
            raise ValueError(f"case identity collision {key}: versions {seen[key][0]} and {version}")
        seen[key], contents[key] = (version, digest), content
        old = active.get(key) or _matching(active, key, cfg)
        if old and old.get("version") != version and _expected(expected_previous, key, cfg) != old.get("version"):
            raise RuntimeError(f"case {key} update requires expected_previous_version={old.get('version')}")
    links = [row for row in current.get("links") or [] if isinstance(row, dict)
             and not any(C.case_matches(C.case_link_key(row, cfg), key, cfg=cfg) for key in seen)]
    history = [row for row in current.get("history") or [] if isinstance(row, dict)]
    for record in records:
        key, cid, version = C.case_link_key(record, cfg), str(record["case_id"]), str(record["version"])
        snapshot = task_root / "state" / "case-versions" / cid / (version + ".md")
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        if snapshot.exists() and snapshot.read_bytes() != contents[key]:
            raise RuntimeError(f"task case snapshot conflicts with immutable version bytes for {key}/{version}")
        if not snapshot.exists():
            snapshot.write_bytes(contents[key])
        link = {"case_id": cid, "version": version, "content_hash": record["content_hash"],
                "path": snapshot.relative_to(task_root).as_posix(),
                "store_provenance": {"content_hash": record["content_hash"],
                                     "source_name": record.get("source_name", ""),
                                     "source_path": _portable_record_path(record)}}
        if record.get("area"):
            link["area"] = str(record["area"])
        links.append(link)
        if not any((C.case_link_key(row, cfg), row.get("version")) == (key, version) for row in history):
            history.append(link)
    result = {"schema_version": 2, "task_id": task_root.name, "links": links, "history": history}
    atomic_json(link_path(task_root), result)
    return result


def store_root(task_root: Path) -> Path:
    """The default `--store`: the project's own case store when onboarding recorded one
    (`config.cases_root`), else the story's `work/test-cases/`.

    One default, in one place. It used to be required here and defaulted silently in
    `critic_rollcall.apply_fixes` to a path this module never named, while s4.md wrote
    `--store <case_versions_root>` — a token that exists nowhere — so every window invented
    its own store and pinned into it."""
    try:
        return C.cases_root(Path(task_root))
    except Exception:
        return Path(task_root) / "work" / "test-cases"


def _case_roots(task_root: Path, cases_dirs: list | None = None) -> tuple:
    """The folders `discover_cases` looks in, and the shared library among them (None when there is none):
    the caller's `--cases-dir` folders, else the story's own two and the project's `cases_root`."""
    roots = [Path(d) for d in (cases_dirs or [])]
    shared = None
    if not roots:
        roots = [task_root / "work" / "test-cases", task_root / "test-cases"]
        configured = store_root(task_root)
        if configured not in roots:
            roots.append(configured)
            shared = configured
    return roots, shared


def discover_cases(task_root: Path, cases_dirs: list | None = None) -> list:
    """Every case file (`<case id>.md`, in the project's id form) the story's case design produced,
    in a stable order.

    The orchestrator pins the whole batch in one command (`--all`); before that it was a
    per-file command in the designer's charter, and the designer has no Bash at all — which is
    how TP1-15045 ended with the designer blocked twice and the event "pinned by
    orchestrator script".

    A project with `config.cases_root` keeps its cases in its own library, which is where the
    designer writes them (`qa-case-designer.md`, `contract.case_files`). Looking only under the
    story folder found nothing there: `--all` died with "provide --case-file ...", `--verify`
    answered `cases: 0`, and gate A approved an empty pin set. A shared library also holds
    other stories' cases, so those are selected by the `task` field every case carries.
    """
    task_root = Path(task_root)
    roots, shared = _case_roots(task_root, cases_dirs)
    found: list = []
    cfg = C.case_config(task_root)
    for directory in roots:
        if not directory.is_dir():
            continue
        # Every .md, then the id form decides: the glob used to be `TC-*.md`, so a story whose
        # cases are `TP1-13877_TC_001.md` discovered none of them (B-013, FR-17).
        for path in C.case_glob(directory, cfg=cfg):
            if not path.is_file():
                continue
            if directory == shared and C.case_task(path) not in ("", task_root.name):
                continue
            found.append(path)
    return list(dict.fromkeys(found))


def pin_state(task_root: Path, cases_dirs: list | None = None) -> dict:
    """`{"cases": <case files discovered>, "unpinned": <the list `unpinned` always returned>}` in ONE traversal
    (SC5-15): the gate must tell "every case is pinned" from "there is no case to pin" (an empty list says both).
    A history with no case folder is `{"cases": 0, "unpinned": []}`."""
    links = {C.case_link_key(link): str(link.get("content_hash") or "")
             for link in C.story_case_links(Path(task_root)) if isinstance(link, dict)}
    missing = []
    sources = discover_cases(task_root, cases_dirs)
    for source in sources:
        try:
            candidate = validate_candidate(source)
        except ValueError as exc:
            missing.append(f"{source.name}: {exc}")
            continue
        pinned = links.get(candidate["key"])
        if pinned is None:
            pinned = _matching(links, candidate["key"])
        if pinned != candidate["content_hash"]:
            missing.append(f"{candidate['key']}: {source.name} is not pinned at its current bytes")
    return {"cases": len(sources), "unpinned": missing}


def unpinned(task_root: Path, cases_dirs: list | None = None) -> list:
    """Case files with no active pin of their exact bytes — the precondition for dispatching
    the critic, which reviews pinned versions and nothing else."""
    return pin_state(task_root, cases_dirs)["unpinned"]


# --- the approved scope follows the pins (HF8-6, S3.05) -----------------------------------------------------------
# The pinned cases ARE the scope the case critic is dispatched over. Two paths used to record it differently
# (the driver in code, the skill path in a phase text placed after the critic), and the conductor paid for the
# gap on run 12586 (six calls and two refusals). `scope_request` is the one place the request is built; the
# driver (`Driver.revise_plan`) and this CLI (`record_scope`) both call it.

def _last_revise_event(controller):
    """The newest `revise_plan` event of the story, or None when there is none."""
    kept = [event for event in controller.store.read() if event.get("type") == "revise_plan"]
    return kept[-1] if kept else None


def _written_by_us(event, ticket: str) -> bool:
    """True when the event carries the key THIS module builds: `revise_plan:<ticket>:<revision>:<12 hex>` with the
    revision equal to the event's own `expected_revision`. Fields only, never words (FR-12). Residue: a hand-written
    key that repeats the whole form with the right revision cannot be told from ours. The test is the controller's
    (`code_scope_key`: it stamps no plan row for a write of ours, and recognises it by the same key)."""
    from controller import code_scope_key
    return code_scope_key(event.get("idempotency_key"), event.get("expected_revision"), ticket)


def _scope_plan(task_root: Path, controller=None) -> dict:
    """What the scope step would do now, without writing anything (FR-45).

    `request`: the `revise_plan` request, or None. `note`: why nothing is written, when that is worth saying.
    `behind`: the pin keys the stored scope does not name. `new`: the pin keys no stored member names by exactly
    one key. `multi`: the stored members that now name several keys. `gate_current`: gate A is approved now.

    ERROR DIRECTION. This request stales every gate A decision, so the one wrong answer is to stale an approval over
    a set PROVEN unchanged, or to leave it standing over a set that may have grown. Equal keys, or a stored scope
    that is one key per member and the same keys (one case respelled), is "nothing to write". A bare member that
    resolves to several keys is not: the same stored word is an old spelling of one case or a number that grew a
    second area, and nothing on disk tells them apart, so it counts as new (a repeated question is cheaper than
    an approval of a case nobody saw). An index that cannot be built counts as "not equal" (N-6): the bare ids
    go to the controller, which refuses in its own words."""
    from controller import SCOPE_REASON, Controller
    from event_store import content_hash
    task_root = Path(task_root)
    controller = controller or Controller(task_root)
    state = controller.state()
    plan = {"request": None, "note": "", "behind": [], "new": [], "multi": [], "gate_current": False}
    scope = sorted({str(link["case_id"]) for link in controller._pinned_links()})
    if not scope:               # an empty scope is never written (K2)
        return plan
    plan["gate_current"] = bool(controller._current_gate_a(state))
    try:
        _ids, resolution = controller._scope_membership(scope, strict=True)
    except (OSError, ValueError, TypeError):
        resolution = []
    keys = controller._resolved_keys(resolution) if resolution else None
    stored = list(state.get("scope") or [])
    if keys is not None:
        _ids, rows = controller._scope_membership(stored)
        held = {key for _, found, why in rows if not why for key in found}
        single = {found[0] for _, found, why in rows if not why and len(found) == 1}
        plan["behind"] = sorted(set(keys) - held)
        plan["new"] = sorted(set(keys) - single)
        plan["multi"] = [(str(member), found) for member, found, why in rows if not why and len(found) > 1]
        if sorted(stored) == keys:
            return plan
        if (plan["gate_current"] and rows and all(not why and len(found) == 1 for _, found, why in rows)
                and single == set(keys)):
            return plan         # K6: one case respelled, the set is the same
        if stored and plan["behind"]:
            last = _last_revise_event(controller)
            # a scope somebody narrowed on purpose is their word (FR-8): the key of this function is matched whole
            if last is not None and not _written_by_us(last, controller._ticket()):
                plan["note"] = ("the scope was set by hand and stays; pinned outside it: "
                                + controller._listed(plan["behind"]) + "; to include them use `revise_plan`")
                return plan
    plan_file = task_root / "work" / "test-plan.json"
    plan_revision = "sha256:" + (hashlib.sha256(plan_file.read_bytes()).hexdigest() if plan_file.is_file() else "none")
    revision = state.get("revision", 0)
    keyed = keys if keys is not None else scope
    plan["request"] = {
        "scope": scope, "plan_revision": plan_revision,
        "reason": SCOPE_REASON.format(n=len(scope)),
        "required_quality_checks": state.get("required_quality_checks") or [],
        "expected_revision": revision,
        "idempotency_key": f"revise_plan:{controller._ticket()}:{revision}:"
                           + content_hash({"scope": keyed, "plan_revision": plan_revision})[:12]}
    return plan


def scope_request(task_root: Path, controller=None, notes: list | None = None) -> dict | None:
    """The `revise_plan` request that makes the pinned cases the approved scope, or None when there is nothing to
    write (the controller already holds exactly them, no case is pinned, or the scope was narrowed by hand).
    Pure: it writes nothing. `notes`, when given, receives the sentence that says why a scope that differs from the
    pins is left alone. The check for a controller journal is `record_scope`'s, not this function's: a driver
    with no journal still gets the controller's own refusal from the call that sends the request."""
    plan = _scope_plan(task_root, controller)
    if plan["note"] and notes is not None:
        notes.append(plan["note"])
    return plan["request"]


def record_scope(task_root: Path, changed=()) -> dict:
    """Record the pinned cases as the approved scope through the controller's own `revise_plan`.

    `{"scope": "recorded" | "unchanged" | "not_recorded", "scope_note"?, "gate_a_stale"?, "scope_behind"?,
    "cases_changed"?}`. Never raises for a refusal and never turns one into success (AR-28): the pins stand, the
    answer says what was not written and why, and the controller's own refusals at the critic's start and at gate A
    remain the judges. `changed`: the case keys whose bytes the pin just replaced (the caller compared the versions
    before and after); named in the answer when gate A is current and stays so."""
    from event_store import LIFECYCLE_WAIT_SECONDS, EventCommitted, StateConflict
    from controller import Controller
    task_root = Path(task_root)
    committed = ""
    try:
        controller = Controller(task_root, wait_seconds=LIFECYCLE_WAIT_SECONDS)
        state = controller.state()
        if not state.get("source_revision"):
            return {"scope": "not_recorded",
                    "scope_note": "no controller journal: the story has no initialized controller yet, so the cases are "
                                  "pinned; run --all again after initialize records the scope"}
        missing = unpinned(task_root)
        if missing:
            return _cases_changed(
                {"scope": "not_recorded",
                 "scope_note": "the scope is recorded over a fully pinned story and these cases are not pinned at their "
                               "current bytes: " + controller._listed(missing) + "; run --all without --cases-dir"},
                {"gate_current": bool(controller._current_gate_a(state))}, changed)
        plan = _scope_plan(task_root, controller)
        if plan["request"] is None:
            answer = {"scope": "not_recorded" if plan["note"] else "unchanged"}
            if plan["note"]:
                answer["scope_note"] = plan["note"]
                answer["scope_behind"] = plan["behind"]
            return _cases_changed(answer, plan, changed)
        try:
            controller.apply("revise_plan", plan["request"])
        except EventCommitted as exc:       # the event is in the journal: it is recorded, the rest is said (by type, FR-12)
            committed = str(exc)
        except (StateConflict, ValueError, OSError, TypeError) as exc:
            note = str(exc)
            if (state.get("leases") or {}).get("orchestrator"):
                note += ("; the scope cannot be recorded under a lease; a hand-written revise_plan carries the "
                         "owner_session_id of leases.orchestrator in state/controller.json")
            answer = {"scope": "not_recorded", "scope_note": note}
            if plan["behind"]:
                answer["scope_behind"] = plan["behind"]
            return _cases_changed(answer, plan, changed)
    except (StateConflict, ValueError, OSError, TypeError) as exc:
        return {"scope": "not_recorded", "scope_note": str(exc)}
    answer = {"scope": "recorded"}
    if plan["gate_current"]:
        parts = [f"{member} now names {', '.join(found)}" for member, found in plan["multi"]]
        answer["gate_a_stale"] = True
        answer["scope_note"] = ("gate A approval is stale because of these new cases: "
                                + (controller._listed(plan["new"]) or "the scope changed")
                                + ("; " + "; ".join(parts) if parts else "") + "; ask gate A again")
    if committed:
        answer["scope_note"] = (answer["scope_note"] + "; " if answer.get("scope_note") else "") + committed
    return answer


def review_scope(task_root: Path, controller=None, state=None, pinned=None) -> list:
    """The case ids the case critic is dispatched over (CX2-17 C-7): the cases of the plan rows whose validated
    `design_review_required` is true; every pinned case when the plan names none (a critic with no scope reviews whatever it
    reads). `[]` when no case is pinned. THE one computation: `Driver.critic_scope` and the `review_scope` of `--all`'s
    answer (which `s4.md` reads on the skill path) are this function, so no conductor counts the cases of a row by hand.
    `state`, `pinned`: what the caller already read (the driver passes its own); a plan or a state that cannot be read
    narrows nothing - the pinned cases are the answer (P1: a reader that cannot read says nothing)."""
    from controller import Controller
    from event_store import StateConflict
    task_root = Path(task_root)
    controller = controller or Controller(task_root)
    if pinned is None:
        pinned = sorted({str(link["case_id"]) for link in controller._pinned_links()})
    plan = hooklib.read_json(task_root / "work" / "test-plan.json", [])
    rows = plan.get("rows") if isinstance(plan, dict) else plan
    wanted = {str(row.get("id")) for row in rows or [] if isinstance(row, dict) and row.get("design_review_required")}
    try:
        mapping, _, _ = controller._case_rows(state if state is not None else controller.state())
        scoped = sorted(case for case, row in mapping.items() if str(row) in wanted)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, StateConflict):
        scoped = []
    return scoped or list(pinned)


def _cases_changed(answer: dict, plan: dict, changed) -> dict:
    """K5: the bytes of approved cases moved while gate A stays current. No judge of the content stands after the
    approval (`gate_inputs` does not read cases), so the answer names the cases instead of staying silent."""
    if changed and plan["gate_current"]:
        answer["cases_changed"] = sorted(str(key) for key in changed)
        note = "the bytes of these approved cases changed: " + ", ".join(answer["cases_changed"])
        answer["scope_note"] = (answer["scope_note"] + "; " + note) if answer.get("scope_note") else note
    return answer


NAMES_LIMIT = 10


def _empty_answer(task_root: Path, cases_dirs: list | None = None, verify: bool = True) -> int:
    """The answer when the story has no case file to pin or to verify: exit 1, never a pass (AR-23, AR-28).

    `verify`: stdout carries one JSON line `{"verified": false, "cases": 0, "reason": ...}`; the reason is a field,
    not words (FR-12): `pins_without_files` (versions are pinned, the files are gone; adds `pins`),
    `names_outside_form` (a `.md` file that looks like a case of this story, `TC_` or the story key in its name, is
    not in the id form; README and library documents never count), else `no_cases`. Without `verify` (`--all`,
    `--cases-dir`) only the text is written and nothing is pinned. ERROR DIRECTION: a false red is allowed, a false
    green is not, so every doubt lands here."""
    from adapter_forms import key_form
    import case_forms
    task_root = Path(task_root)
    roots, shared = _case_roots(task_root, cases_dirs)
    cfg = C.case_config(task_root)
    pins = len([link for link in C.story_case_links(task_root) if isinstance(link, dict)])
    outside = []
    key = task_root.name.casefold()
    for directory in roots:
        if not directory.is_dir():
            continue
        in_form = {p for p in C.case_glob(directory, cfg=cfg)}
        for path in directory.rglob("*.md"):
            name = path.name.casefold()
            if path.stem.casefold() == "readme" or not path.is_file() or path in in_form:
                continue
            # a case of THIS story: `TC_` or the story key in the name; a shared library needs the key (TC_ may be
            # another story's), and its documents (conventions.md) hold neither
            if directory == shared and C.case_task(path) not in ("", task_root.name):
                continue
            if key in name or (directory != shared and "tc_" in name):
                outside.append(path.name)
    outside = sorted(dict.fromkeys(outside))
    reason = "pins_without_files" if pins else "names_outside_form" if outside else "no_cases"
    text = ("no case file found: looked in " + ", ".join(str(d) for d in roots)
            + "; id form " + ", ".join(case_forms.forms(cfg)) + ", ticket " + key_form(cfg, floor=True).pattern
            + "; if the story has no cases yet, run --all after S4 wrote them, then --verify")
    if reason == "names_outside_form":
        more = len(outside) - NAMES_LIMIT
        text += ("; a case file whose name does not match the id form is not found: "
                 + ", ".join(outside[:NAMES_LIMIT]) + (f" and {more} more" if more > 0 else ""))
    elif reason == "pins_without_files":
        text += (f"; {pins} pinned versions have no case file on disk: restore the files or run --all after S4 "
                 "rewrote them")
    if verify:
        answer = {"verified": False, "cases": 0, "reason": reason}
        if reason == "pins_without_files":
            answer["pins"] = pins
        print(json.dumps(answer, ensure_ascii=False))
    print(text, file=sys.stderr)
    return 1


def main() -> int:
    C.force_utf8()
    parser = argparse.ArgumentParser(
        description="create immutable case versions and pin them to a story",
        epilog=epilog("case_versions.py"),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store", type=Path, default=None,
                        help="immutable version store; default: config.cases_root, "
                             "else <TASK_ROOT>/work/test-cases")
    parser.add_argument("--task-root", required=True)      # a raw string: `type=Path` read "" as the current folder
    parser.add_argument("--case-file", type=Path, action="append", default=[])
    parser.add_argument("--cases-dir", type=Path, action="append", default=[],
                        help="pin every case file (<case id>.md) under this directory")
    parser.add_argument("--all", action="store_true",
                        help="pin every case of the story in one batch (the orchestrator's S4 step)")
    parser.add_argument("--verify", action="store_true",
                        help="pin nothing; report cases whose current bytes are not pinned. Stdout is one JSON line: "
                             "{verified, cases}, with reason when false; exit 0 only when verified is true "
                             "(cases >= 1), exit 1 otherwise")
    parser.add_argument("--pin", nargs=2, metavar=("CASE_ID", "VERSION"))
    parser.add_argument("--expected-previous-version", action="append", default=[], metavar="CASE_ID=VERSION")
    args = hooklib.exact_options(parser).parse_args()
    try:        # the story first: a phantom root is refused before `--verify` can answer "verified" or `--pin` create it
        args.task_root = hooklib.story_of("case_versions.py", root=args.task_root, key_flag=None)
    except ValueError as exc:       # this script's own channel (E-5)
        return refuse(command_from_argv("case_versions.py"), str(exc))
    if args.store is None:
        args.store = store_root(args.task_root)
    if args.verify:
        found = discover_cases(args.task_root, args.cases_dir)
        if not found:       # no case file is no pass: a story with nothing to check is not "verified"
            return _empty_answer(args.task_root, args.cases_dir)
        missing = unpinned(args.task_root, args.cases_dir)
        if missing:
            if not any(isinstance(link, dict) for link in C.story_case_links(args.task_root)):
                missing.insert(0, "no case of this story has a version yet; run --all")
            print("REJECT — the case critic reviews pinned versions; these are not pinned:\n- "
                  + "\n- ".join(missing), file=sys.stderr)
            return 1
        print(json.dumps({"verified": True, "cases": len(found)}, ensure_ascii=False))
        return 0
    records = []
    if args.pin:
        cid, version = args.pin
        # `--pin speakers/TC-001 cv_x` names the case; the store path is by number alone.
        cid = C.split_case_key(cid)[1] or cid
        meta = C.load_json(args.store / "cases" / cid / (version + ".json"))
        if not meta:
            # `--pin` takes TWO values, so `--pin --case-file x.json` read the flag and the path
            # as a case id and a version, and the refusal named neither mistake.
            return refuse("case_versions.py --pin",
                          f"no immutable version {version} of {cid} in {args.store}")
        records.append(meta)
    sources = list(args.case_file)
    if args.all or args.cases_dir:
        sources.extend(p for p in discover_cases(args.task_root, args.cases_dir) if p not in sources)
    if not sources and not records and (args.all or args.cases_dir):
        return _empty_answer(args.task_root, args.cases_dir, verify=False)    # nothing written: no pin, no scope
    validate_batch(sources)
    for source in sources:
        records.append(create_version(args.store, source))
    if not records:
        parser.error("provide --case-file, --cases-dir, --all or --pin CASE_ID VERSION")
    expected = dict(item.split("=", 1) for item in args.expected_previous_version)
    if args.all or args.cases_dir:
        # A whole-story batch is computed from the links as they are on disk right now, so the
        # stale-writer guard has nothing to catch: fill the expected previous version from the
        # active pins for every case the caller did not name explicitly. A named
        # --expected-previous-version still wins.
        for link in C.story_case_links(args.task_root):
            if isinstance(link, dict) and link.get("case_id"):
                expected.setdefault(C.case_link_key(link), str(link.get("version") or ""))
    before = {C.case_link_key(link): str(link.get("content_hash") or "")
              for link in C.story_case_links(args.task_root) if isinstance(link, dict)} if args.all else {}
    links = pin_batch(args.task_root, records, expected)
    answer = {"pinned": len(records), "links": len((links or {}).get("links") or [])}
    if args.all:
        # after the pin, outside the links lock: the scope never names a pin that is not on disk. The pin has
        # succeeded by now; what the scope step could not do is said in the answer, not by the exit code (P1).
        # a link pinned before areas existed is `TC-001`, the new one `s/TC-001`: `_matching` finds the old by case
        changed = []
        for link in (links or {}).get("links") or []:
            if not isinstance(link, dict):
                continue
            key, own = C.case_link_key(link), str(link.get("content_hash") or "")
            old = before.get(key) or _matching(before, key) or own
            if old != own:
                changed.append(key)
        answer.update(record_scope(args.task_root, changed))
        # the case critic's `--scope` on the skill path: the pinned cases of the design-review rows, computed here once
        try:
            answer["review_scope"] = review_scope(args.task_root)
        except (OSError, ValueError, TypeError):      # the pin has succeeded: what cannot be read is left out of the answer (P1)
            pass
    print(json.dumps(answer, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(run_guarded(command_from_argv("case_versions.py"), main))
