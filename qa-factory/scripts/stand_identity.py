#!/usr/bin/env python3
"""How the factory reads which build a stand runs, and what a person said about it (t-300).

Two stores, both carried by a reinstall (references/install-paths.json):

  qa-factory/records/stand-identity.json                     the project's registry: per stand and test
      profile, ONE way to read the build (a label of the image, a file in the container, a command, the
      files themselves) or the decision "I check this stand myself". Rows are appended, never edited: the
      last valid row of a stand+profile is in force, earlier rows are history, `forget` appends `withdrawn`.
      Commit it, so the team shares it.
  qa-factory/artifacts/<TASK>/state/stand-confirmations.jsonl  the person's word FOR ONE STORY: "this
      story's build is on the stand now" (`deployed`), "test what is deployed" (`test_deployed`), "test it as
      it is although these files differ" (`content_accepted`, bound to the sha256 of the exact files the probe
      compared), or taking the word back (`withdrawn`). The registry is never touched by it.

    stand_identity.py show      [--environment E] [--profile P] [--json]
    stand_identity.py record    --environment E --profile P --method M [--label N | --path P | --command "<line>"]
                                --words "<the person's words>" [--source person]
    stand_identity.py confirm   --task T --environment E --profile P --revision <40 hex> [--story-revision <40 hex>]
                                [--image image:sha256:<64 hex>] --words "<words>"
    stand_identity.py confirm   --task T --environment E --profile P --revision <40 hex> --content <64 hex>
                                [--image image:sha256:<64 hex>] --words "<words>"   (`content_accepted`)
    stand_identity.py forget    --environment E --profile P --words "<words>"
    stand_identity.py unconfirm --task T --environment E --profile P --words "<words>"
    stand_identity.py validate  [--file PATH]

Write the paths of a `--command` with forward slashes (C:/x): they mean the same everywhere, while backslashes are
consumed by the shell-style split of the command line on every system but Windows, where they are kept as written.

`record`, `confirm`, `forget` and `unconfirm` are a person's word. The driver and the conductor run them on a
person's answer; a role never does (guard_pre_tool.human_word_check) - otherwise the automator could confirm its
own build. The probe (runtime_probe.py) reads both stores and writes one kind of row itself: `probe discovered`.

The vocabulary - methods, defaults, limits, outcome words - is DATA (references/build-identity-methods.json, FR-13).
"""
import argparse
import contextlib
import hashlib
import json
import os
import re
import shlex
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import runtime_paths as RP  # noqa: E402
from event_store import EventStore, StateConflict, atomic_json  # noqa: E402

REGISTRY_NAME = "stand-identity.json"
CONFIRMATIONS_NAME = "stand-confirmations.jsonl"
# The writer lock lives in `state/`, machine-local, whichever folder the registry is in. It is NOT named
# `state/stand-*.json`: the stand_lease row of install-paths.json would claim that.
WRITER_LOCK = ".stand-identity-writer"
DATA_PATH = HERE.parent / "references" / "build-identity-methods.json"
SHA40 = re.compile(r"[0-9a-f]{40}")
SHA64 = re.compile(r"[0-9a-f]{64}")
IMAGE_RE = re.compile(r"image:sha256:[0-9a-f]{64}")
CONFIRM_KINDS = ("deployed", "test_deployed", "content_accepted", "withdrawn")
_DATA: dict = {}


class RegistryError(Exception):
    """A refusal that is the call's or the file's: its text says what is wrong, what was expected and the door
    (FR-1). The CLI prints it and exits 2; the library caller reads `str(error)`."""


def data() -> dict:
    """references/build-identity-methods.json, read once. A missing or unreadable file is a defect of the
    package, said by name - never a silent empty vocabulary that would refuse every row."""
    if not _DATA:
        try:
            _DATA.update(json.loads(DATA_PATH.read_text(encoding="utf-8-sig")))
        except (OSError, ValueError) as exc:
            raise RegistryError(f"the factory's own vocabulary {DATA_PATH.name} cannot be read ({exc}); it is part of the "
                                "package: reinstall the plugin") from exc
    return _DATA


def method_param(method: str) -> dict:
    return (data().get("methods") or {}).get(method) or {}


def default_of(method: str) -> str:
    return str(method_param(method).get("default") or "")


def limit(name: str):
    return (data().get("limits") or {})[name]


def method_words(row: dict) -> str:
    """The words a person reads for a row's way of reading the build (data, FR-13)."""
    template = (data().get("method_words") or {}).get(str(row.get("method")), str(row.get("method")))
    argv = row.get("argv") if isinstance(row.get("argv"), list) else []
    return template.format(label=row.get("label") or default_of("oci_label"),
                           path=row.get("path") or default_of("build_sha_file"),
                           command=" ".join(shlex.quote(str(a)) for a in argv))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def registry_path(project_root) -> Path:
    """Where the registry lives (a new file: always the layout's own place)."""
    return RP.record_new(project_root, REGISTRY_NAME)


def registry_rel() -> str:
    """The spelling of its path for a text a person reads (FR-37)."""
    return RP.rel_text(REGISTRY_NAME)


def confirmations_path(task_root) -> Path:
    return Path(task_root) / "state" / CONFIRMATIONS_NAME


def confirmations_rel(task: str) -> str:
    return f"{RP.HOME}/artifacts/{task}/state/{CONFIRMATIONS_NAME}"


# --- the pieces of a stand, as the project's config names them ---------------------------------------

def definition_sha(environment) -> str:
    """sha256 of what makes a stand THE stand a person decided about (Q10): its `base_url` and its `frontend_url`
    (an e2e-ui test targets the second, an api test the first). Credentials are not in it: editing a password never
    voids a decision about a build. Stable under key order and the whitespace around a value.
    A device stand (EP1-41e: the row names a `surface`) is also THE app and THE driver server a person decided about: `surface`,
    `app.id` and `driver.url` join the payload, so a decision does not follow the stand to another app or another server. A row with
    no `surface` (every web or API stand) hashes exactly as before, so no stored decision of such a stand is voided by this."""
    env = environment if isinstance(environment, dict) else {}
    import env_probe   # the one reader of a stand's frontend address (axis 29); the stand's own spellings only (F-3)
    payload = {"base_url": str(env.get("base_url") or "").strip(),
               "frontend_url": env_probe.frontend_of({}, "", entry=env)["url"]}
    if env.get("surface"):
        def inner(block, key):
            return str((block.get(key) if isinstance(block, dict) else "") or "").strip()
        payload.update({"surface": str(env["surface"]).strip(), "app_id": inner(env.get("app"), "id"),
                        "driver_url": inner(env.get("driver"), "url")})
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def definition_sha_for(cfg, environment_id: str) -> str:
    """`definition_sha` of the stand `environment_id` of this config, or '' when the config has no such stand."""
    for entry in (cfg or {}).get("environments") or []:
        if isinstance(entry, dict) and str(entry.get("name") or "") == str(environment_id):
            return definition_sha(entry)
    return ""


def in_config(cfg, environment_id: str, profile_id: str) -> str:
    """'' when the stand AND the profile are named in the project's config, else what is missing (E5)."""
    stands = [str(e.get("name")) for e in (cfg or {}).get("environments") or [] if isinstance(e, dict)]
    profiles = [str(p.get("profile_id")) for p in (cfg or {}).get("profiles") or [] if isinstance(p, dict)]
    if environment_id not in stands:
        return f"stand `{environment_id}` is not in this project's config"
    if profile_id not in profiles:
        return f"test profile `{profile_id}` is not in this project's config"
    return ""


def reference_stands(project_root, task: str = "") -> dict:
    """`{stand name: side name}` of the stands that run an OLD version of a side for this story (S-c, t-2181 PC-9b): the story's own
    record of its sides (`contract.story_sides`, the ONE reader: `pipeline.sides` first, then the registry's `environments.reference_for`
    rows). `task` names the story (its pipeline.json under the artifact root); '' reads the registry alone. NEVER raises, writes nothing.
    DIRECTION OF ERROR: an unreadable record reads {} - the caller then asks about a stand it should have skipped (more questions), and
    a run is never refused on a record nobody could read; the run's own gates refuse an unreadable story."""
    try:
        import hooklib
        pipeline = {}
        if str(task or "").strip():
            read = hooklib.read_json(hooklib.artifact_root(root=Path(project_root)) / str(task) / "pipeline.json", {})
            pipeline = read if isinstance(read, dict) else {}
        if not (isinstance(pipeline.get("sides"), dict) and pipeline["sides"]):
            # t-2181 PC-9b (critic t-2513 B3): a story with no `sides` record and a project with no knowledge record has no reference - a
            # `reference` comes only from those two carriers (`contract.story_sides`), the default side carries none. Answered BEFORE
            # `contract` is imported (0.5 s cold): a story with no reference pays nothing for the question.
            import project_knowledge as PK
            if not PK.record_path(project_root).is_file():
                return {}
        import contract as C
        sides = C.story_sides(pipeline, root=Path(project_root))
        return {str(s["reference"]): str(name) for name, s in sides.items()
                if isinstance(s, dict) and isinstance(s.get("reference"), str) and s["reference"].strip()}
    except Exception:
        return {}


def reference_side(project_root, task, stand) -> tuple:
    """`(side, own)` - THE one reader of "is this stand a reference of this story, and is it also the story's own stand" (AR-13; critic
    t-2513 F3: C8 and the probe's skip read the same answer). `side` is the side `stand` is the reference of ('' when it is none, or an
    argument is empty); `own` is the story's own stand (`pipeline.environment`) and is read only when `side` is not '' ('' when unreadable).
    `side` and `own == stand` together are a CONTRADICTION of the record: one stand named as the old version and as the stand under test.
    Both callers take the safe direction on it - C8 refuses and names the record (never the same stand as a door), the probe does not
    skip and asks. NEVER raises, writes nothing."""
    name, key = str(stand or "").strip(), str(task or "").strip()
    if not name or not key:
        return "", ""
    side = reference_stands(project_root, key).get(name, "")
    if not side:
        return "", ""
    try:
        import hooklib
        pipeline = hooklib.read_json(hooklib.artifact_root(root=Path(project_root)) / key / "pipeline.json", {})
        return side, (str(pipeline.get("environment") or "").strip() if isinstance(pipeline, dict) else "")
    except Exception:
        return side, ""


REFERENCE_RUNS_DIR = "reference-runs"     # work/<this>: the blocks of runs made on a reference stand, apart from `work/run-blocks` (t-2277 W1)
# the evidence-receipt folders under `work/` that no role may write into (artifact_producer.publish, artifact_packet.work_path): ONE tuple (F3)
PROTECTED_RECEIPT_FOLDERS = ("run-blocks", "manual-blocks", "baseline-receipts", REFERENCE_RUNS_DIR)
REFERENCE_RUN_WORDS = "a run on the reference stand - a sample, not the story's result"


def reference_run_mark(project_root, task, stand) -> dict:
    """The mark a run block carries when its target is a reference stand of the story (t-2277 W1, owner 11.11.2026: the factory runs the
    test, records that it did not run on the story's code, and never counts the result as the story's): `{"stand", "side", "story_code":
    False, "words"}`, or {} when `stand` is no reference of this story, an argument is empty, or the record contradicts itself (own stand ==
    reference: that is a data contradiction C8 still refuses, never a sample). The one reader of the question is `reference_side` (AR-13).
    NEVER raises, writes nothing. An older run block has no mark and reads as the story's own stand, as before."""
    name = str(stand or "").strip()
    side, own = reference_side(project_root, task, name)
    if not side or own == name:
        return {}
    return {"stand": name, "side": side, "story_code": False, "words": REFERENCE_RUN_WORDS}


def reference_runs(task_root) -> list:
    """The run blocks of `work/reference-runs` (the samples), oldest name first, each the parsed object; a file that is not a JSON object
    is left out (the report names a count of what it read, never a guess). They live apart from `work/run-blocks` on purpose: every reader
    of the story's evidence (`run_history.read_run_blocks` and everything built on it: the reducer, the ledger, the proof stamp, the
    delivery verdict) reads that one folder, so a sample can never become the story's evidence by a reader that forgot to skip it
    (AR-13, AR-15). NEVER raises."""
    import json
    out = []
    try:
        for path in sorted((Path(task_root) / "work" / REFERENCE_RUNS_DIR).glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except Exception:
                continue
            if isinstance(data, dict):
                out.append(data)
    except Exception:
        return []
    return out


def reference_of_running_story(task: str = "") -> dict:
    """`reference_stands` of the project this process works in, for a caller that has no project root at hand (the stand-picking
    functions): the project is the one `hooklib.project_root()` names. A project that cannot be named reads {} (see above)."""
    try:
        import hooklib
        return reference_stands(hooklib.project_root(), task)
    except Exception:
        return {}


def repo_for(cfg, profile_id: str) -> str:
    for repo in (cfg or {}).get("implementation_repos") or []:
        if isinstance(repo, dict) and str(repo.get("execution_profile_id") or "") == profile_id:
            return str(repo.get("repo_id") or "")
    return ""


# --- shapes ------------------------------------------------------------------------------------------

def _iso_ok(value) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _nonempty(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def row_errors(row, index) -> list:
    """Why a registry row is not one - empty when it is. One sentence per fault, each naming the row, the stand,
    the profile and the field (FR-1): a hand-edited file is repaired by reading these."""
    if not isinstance(row, dict):
        return [f"row {index}: must be an object, not {type(row).__name__}"]
    where = f"row {index} (stand `{row.get('environment_id', '?')}`, profile `{row.get('profile_id', '?')}`)"
    errors = []
    for field in ("environment_id", "profile_id"):
        if not _nonempty(row.get(field)):
            errors.append(f"{where}: {field} must be a non-empty string")
    method = row.get("method")
    methods = data().get("methods") or {}
    if method not in methods:
        errors.append(f"{where}: method {method!r} is not one of {', '.join(methods)}")
    elif method == "oci_label":
        if "label" in row and not _nonempty(row.get("label")):
            errors.append(f"{where}: label must be a non-empty string (leave it out for {default_of('oci_label')})")
    elif method == "build_sha_file":
        if not _nonempty(row.get("path")):
            errors.append(f"{where}: path must be the file inside the container that holds the commit")
    elif method == "command":
        argv = row.get("argv")
        if not isinstance(argv, list) or not argv or any(not _nonempty(item) for item in argv):
            errors.append(f"{where}: argv must be a non-empty list of non-empty strings (the command, one word per item)")
    elif method == "sources":
        if "app_root" in row and not _nonempty(row.get("app_root")):
            errors.append(f"{where}: app_root must be a non-empty path inside the container")
    source = row.get("source")
    if source not in (data().get("sources_of_a_row") or []):
        errors.append(f"{where}: source {source!r} is not one of {', '.join(data().get('sources_of_a_row') or [])}")
    elif method in methods and methods[method].get("person_only") and source != "person":
        errors.append(f"{where}: a row with source `{source}` cannot be method `{method}`: only a person's word may "
                      "run a command or stop the factory looking (source `person`, with the words)")
    if not _iso_ok(row.get("recorded_at")):
        errors.append(f"{where}: recorded_at must be an ISO-8601 time")
    words = row.get("words", "")
    if not isinstance(words, str):
        errors.append(f"{where}: words must be text")
    elif source == "person" and not words.strip():
        errors.append(f"{where}: words are empty: a row of source `person` carries the person's own words")
    if "stand_definition_sha" in row and not (isinstance(row["stand_definition_sha"], str)
                                              and SHA64.fullmatch(row["stand_definition_sha"])):
        errors.append(f"{where}: stand_definition_sha must be 64 lower-case hex characters")
    return errors


def version_error(parsed: dict) -> str:
    """'' when a parsed registry is a version this factory reads, else the sentence that says so. ONE predicate for the
    reader (`state`, `validate`) and the writer (`_file_for_write`), so they cannot disagree about a file (t-345 F3: the
    writer used to rewrite a version-2 file as version 1 holding version-2 rows). A file with no `schema_version` is
    version 1, as it always was."""
    version = parsed.get("schema_version", 1)
    return "" if version == 1 else f"schema_version {version!r} is not one this factory reads (it reads 1)"


def validate(parsed) -> list:
    """Every fault of a parsed registry file, one sentence each. `[]` is a file the factory reads whole."""
    if not isinstance(parsed, dict):
        return [f"the file must hold one JSON object with a `rows` list, not {type(parsed).__name__}"]
    errors = []
    if version_error(parsed):
        errors.append(version_error(parsed))
    rows = parsed.get("rows", [])
    if not isinstance(rows, list):
        return errors + ["`rows` must be a list"]
    for index, row in enumerate(rows):
        errors.extend(row_errors(row, index))
    return errors


def _no_duplicate_keys(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"the key {key!r} appears twice in one object")
        seen[key] = value
    return seen


def parse_text(text: str):
    """(parsed, error): the file's JSON with duplicate keys refused (`object_pairs_hook`). An absent or empty
    text is an empty registry - absence is never an error (TE1)."""
    if not text.strip():
        return {"rows": []}, ""
    try:
        return json.loads(text, object_pairs_hook=_no_duplicate_keys), ""
    except ValueError as exc:
        return None, f"it is not valid JSON ({exc})"


def check_text(text: str) -> list:
    """`validate` for the text of a file: the duplicate-key refusal is part of it."""
    parsed, error = parse_text(text)
    return [f"the file {error}"] if error else validate(parsed)


def _read_text(path: Path) -> tuple:
    """(text, error). Absent is ('', '')."""
    try:
        return path.read_text(encoding="utf-8-sig"), ""
    except FileNotFoundError:
        return "", ""
    except (OSError, UnicodeDecodeError) as exc:
        return "", f"it cannot be read ({exc})"


def door(path_text: str) -> str:
    return (f"Fix the row, or delete the file {path_text} (the factory then reads the stand by its defaults and asks again "
            "where it cannot tell)")


def state(project_root) -> dict:
    """The registry as it is now: `{"path", "file_error", "rows" [(index, row)], "errors" [row problems], "in_force"
    {(stand, profile): row}, "withdrawn" {(stand, profile)}, "history" N}`. A file that cannot be read whole sets
    `file_error` and nothing is in force; one invalid row is named in `errors` and IGNORED while its neighbours
    answer (E3). The last VALID row of a key wins; a `withdrawn` one leaves nothing in force (and is remembered, so
    a probe never writes a discovered row over a person's last word, S12)."""
    path = registry_path(project_root)
    out = {"path": path, "file_error": "", "rows": [], "errors": [], "in_force": {}, "withdrawn": set(), "history": 0}
    text, error = _read_text(path)
    parsed = None
    if not error:
        parsed, error = parse_text(text)
        if not error and not isinstance(parsed, dict):
            error = f"it must hold one JSON object with a `rows` list, not {type(parsed).__name__}"
        elif not error and not isinstance(parsed.get("rows", []), list):
            error = "`rows` must be a list"
        elif not error and version_error(parsed):
            error = version_error(parsed)
    if error:
        out["file_error"] = f"{registry_rel()}: {error}. {door(registry_rel())}."
        return out
    for index, row in enumerate(parsed.get("rows", [])):
        problems = row_errors(row, index)
        if problems:
            out["errors"].extend(problems)
            continue
        out["rows"].append((index, row))
        out["history"] += 1
        key = (row["environment_id"], row["profile_id"])
        if row["method"] == "withdrawn":
            out["in_force"].pop(key, None)
            out["withdrawn"].add(key)
        else:
            out["in_force"][key] = row
            out["withdrawn"].discard(key)
    return out


def load(project_root) -> tuple:
    """(in_force {(stand, profile): row}, errors [str]): the rows in force and every problem found."""
    found = state(project_root)
    return found["in_force"], ([found["file_error"]] if found["file_error"] else []) + found["errors"]


# --- the writer --------------------------------------------------------------------------------------

def _locked(project_root, work, sleep=time.sleep):
    """Run `work()` while holding the registry's writer lock. The lock is an OS lock that REFUSES instead of waiting
    (event_store.EventStore.lock raises StateConflict), so two writers at once would lose one: the second waits - a
    bounded number of short sleeps, counted, not timed (FR-31) - and refuses with the door when the first never lets
    go. `sleep` is injectable: a test holds the lock and releases it from the writer's own wait."""
    store = EventStore(RP.state_file(project_root, WRITER_LOCK))
    attempts, step = int(limit("lock_wait_attempts")), float(limit("lock_wait_step_s"))
    for _ in range(attempts):
        stack = contextlib.ExitStack()
        try:
            stack.enter_context(store.lock())
        except StateConflict:
            sleep(step)
            continue
        with stack:
            return work()
    raise RegistryError("another process is writing the stand registry and did not finish within "
                        f"{attempts * step:g} seconds. Run the command again; if it keeps happening, look for a "
                        f"stuck factory process holding qa-factory/state/{WRITER_LOCK}/.")


def _file_for_write(path: Path) -> dict:
    text, error = _read_text(path)
    parsed = None
    if not error:
        parsed, error = parse_text(text)
        if not error and not isinstance(parsed, dict):
            error = "it must hold one JSON object with a `rows` list"
        elif not error and not isinstance(parsed.get("rows", []), list):
            error = "`rows` must be a list"
        elif not error and version_error(parsed):
            error = version_error(parsed)
    if error:
        raise RegistryError(f"{registry_rel()}: {error}. Nothing was written, and the file was not changed. "
                            f"{door(registry_rel())}.")
    return parsed


def append_row(project_root, row: dict, *, sleep=time.sleep, only_if=None):
    """Append one row under the writer lock; the file is read again INSIDE the lock, written to a temp file and
    replaced (the bytes of a reader never see half a file). Returns the path, or None when `only_if(state)` said no
    after the re-read (the probe's discovered row: a row that appeared meanwhile, or a `withdrawn` in force, wins).
    Refuses (RegistryError, nothing written) a row that is not valid, and a file that cannot be read whole - an
    unreadable file is never taken for "nothing known" by a writer (AE4)."""
    problems = row_errors(row, "new")
    if problems:
        raise RegistryError("; ".join(problems))
    path = registry_path(project_root)

    def work():
        parsed = _file_for_write(path)
        if only_if is not None and not only_if(state(project_root)):
            return None
        rows = list(parsed.get("rows", []))
        rows.append(row)
        body = dict(parsed, schema_version=1, rows=rows)
        body.setdefault("note", data().get("registry_note", ""))
        ordered = {"schema_version": body.pop("schema_version"), "note": body.pop("note"), "rows": body.pop("rows"), **body}
        atomic_json(path, ordered)
        return path
    return _locked(project_root, work, sleep)


def make_row(cfg, environment_id, profile_id, method, *, words="", source="person", recorded_by="stand_identity.py",
             label=None, path=None, argv=None, app_root=None) -> dict:
    row = {"environment_id": environment_id, "profile_id": profile_id, "repo_id": repo_for(cfg, profile_id),
           "method": method}
    if method == "oci_label":
        row["label"] = label or default_of("oci_label")
    elif method == "build_sha_file":
        row["path"] = path
    elif method == "command":
        row["argv"] = list(argv or [])
    elif method == "sources" and app_root:
        row["app_root"] = app_root
    if method == "person_confirms":
        row["stand_definition_sha"] = definition_sha_for(cfg, environment_id)
    row.update({"source": source, "recorded_by": recorded_by, "recorded_at": now_iso(), "words": whole(words)})
    return row


def whole(words: str) -> str:
    """The person's words WHOLE (FR-8): the one reader the factory has for them (`brief_pack.person_words_whole`)."""
    import brief_pack
    return brief_pack.person_words_whole(str(words or ""))


# --- the per-story confirmations ---------------------------------------------------------------------

def confirmation_errors(row, task: str = "") -> list:
    if not isinstance(row, dict):
        return ["it is not a JSON object"]
    errors = []
    if row.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if not _iso_ok(row.get("at")):
        errors.append("at must be an ISO-8601 time")
    for field in ("environment_id", "profile_id", "task"):
        if not _nonempty(row.get(field)):
            errors.append(f"{field} must be a non-empty string")
    if task and row.get("task") != task:
        errors.append(f"it is the word for story `{row.get('task')}`, not for `{task}`")
    kind = row.get("kind")
    if kind not in CONFIRM_KINDS:
        errors.append(f"kind must be one of {', '.join(CONFIRM_KINDS)}")
    if kind in ("deployed", "test_deployed", "content_accepted"):
        if not (isinstance(row.get("revision"), str) and SHA40.fullmatch(row["revision"])):
            errors.append("revision must be a full 40-character commit")
        if "story_revision" in row and not (isinstance(row["story_revision"], str) and SHA40.fullmatch(row["story_revision"])):
            errors.append("story_revision must be a full 40-character commit")
        if kind == "test_deployed" and "story_revision" not in row:
            errors.append("a `test_deployed` word names the story's revision too (story_revision)")
        if kind == "content_accepted":
            if not (isinstance(row.get("content"), str) and SHA64.fullmatch(row["content"])):
                errors.append("a `content_accepted` word names the content it was given for: content must be 64 lower-case hex characters")
            if "story_revision" in row:
                errors.append("a `content_accepted` word has no story_revision: one word is one kind")
        if not (row.get("image") == "absent" or (isinstance(row.get("image"), str) and IMAGE_RE.fullmatch(row["image"]))):
            errors.append("image must be image:sha256:<64 hex> or `absent`")
        if not (isinstance(row.get("stand_definition_sha"), str) and SHA64.fullmatch(row["stand_definition_sha"])):
            errors.append("stand_definition_sha must be 64 lower-case hex characters")
    if not _nonempty(row.get("words")):
        errors.append("words are empty: no confirmation without the words a person wrote")
    return errors


def confirmation_rows(task_root) -> tuple:
    """([valid rows in file order], [problems]): a line that cannot be read, or is not a confirmation, is skipped and
    NAMED, and its neighbours stay readable (AE11). A file that cannot be read at all is no word - asked again."""
    path = confirmations_path(task_root)
    text, error = _read_text(path)
    if error:
        return [], [f"{path.name}: {error}; no word of this story is taken from it"]
    task = Path(task_root).name
    rows, problems = [], []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line, object_pairs_hook=_no_duplicate_keys)
        except ValueError as exc:
            problems.append(f"{path.name} line {number}: it is not valid JSON ({exc}); the line is skipped")
            continue
        faults = confirmation_errors(row, task)
        if faults:
            problems.append(f"{path.name} line {number}: {'; '.join(faults)}; the line is skipped")
            continue
        rows.append(row)
    return rows, problems


def task_confirmation(task_root, environment_id: str, profile_id: str, errors=None):
    """The person's word for this story and this (stand, profile): the last VALID line of the key, or None - and None
    too when that last line is a `withdrawn` (`unconfirm`, FR-40). Whether the word still BINDS (the checkout, the
    image, the stand's definition) is the reader's to judge (runtime_probe). Problems found are appended to `errors`."""
    rows, problems = confirmation_rows(task_root)
    if errors is not None:
        errors.extend(problems)
    last = None
    for row in rows:
        if row["environment_id"] == environment_id and row["profile_id"] == profile_id:
            last = row
    return None if last is None or last["kind"] == "withdrawn" else last


def add_confirmation(project_root, task_root, *, task, environment_id, profile_id, kind, words, revision="",
                     story_revision="", image="", stand_definition_sha="", content="", sleep=time.sleep) -> Path:
    """Append one line to the story's confirmation file (under the writer lock). The registry is never touched."""
    row = {"schema_version": 1, "at": now_iso(), "task": task, "environment_id": environment_id,
           "profile_id": profile_id, "kind": kind}
    if kind != "withdrawn":
        row.update(revision=revision, image=image or "absent", stand_definition_sha=stand_definition_sha)
        if story_revision:
            row["story_revision"] = story_revision
        if content:
            row["content"] = content
    row.update(words=whole(words), recorded_by="stand_identity.py")
    faults = confirmation_errors(row, task)
    if faults:
        raise RegistryError("; ".join(faults))
    path = confirmations_path(task_root)

    def work():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return path
    return _locked(project_root, work, sleep)


# --- the CLI -----------------------------------------------------------------------------------------

def _project():
    import hooklib
    return Path(hooklib.project_root()), hooklib.load_config() or {}


def _refuse(message: str) -> int:
    print(f"stand_identity: {message}", file=sys.stderr)
    return 2


def _stand_gate(cfg, environment_id, profile_id) -> str:
    missing = in_config(cfg, environment_id, profile_id)
    if not missing:
        return ""
    # t-373 (class completeness of t-363 B3): the plugin's command is something to TYPE, so it stands in the how-to-answer
    # block (human-questions.md rule 5), which `human_text` reads from this heading - never in the sentence above it
    return (f"{missing}, so nothing was recorded. A stand is added to the project by the onboarding step named below; "
            "say this again once it is there\n\n## How to answer\nThe onboarding step: `/qa-factory:qa-onboarding`.")


def command_argv(line: str) -> list:
    """The words of a `--command` line, as the PERSON'S platform spells a command (t-300 N1b, t-336 deviation 8).

    POSIX (everywhere but Windows): shell-style, a backslash escapes the next character, quotes group and are removed.
    Windows: the same split with NO escape character and no comments (t-366 F1): the backslash is an ordinary character, so
    `C:\\x\\y.exe --flag` keeps its path (the posix split ate every backslash: `C:xy.exe`), while quotes still group and are
    removed wherever they stand - a whole word (`"C:\\Program Files\\p.exe"`) or a part of one (`--name="a b"` is `--name=a b`,
    `--format="{{.Id}}"` is `--format={{.Id}}`), as on POSIX. (`posix=False` kept the quotes and split `--name="a b"` in two.)
    Raises ValueError for an unbalanced quote, on both."""
    if os.name == "nt":
        lexer = shlex.shlex(line or "", posix=True)
        lexer.whitespace_split, lexer.escape, lexer.commenters = True, "", ""
        return list(lexer)
    return shlex.split(line or "", posix=True)


def _abs_path_warning(row) -> str:
    argv = row.get("argv") if isinstance(row.get("argv"), list) else []
    hits = [a for a in argv if isinstance(a, str) and (re.match(r"^[A-Za-z]:[\\/]", a) or a.startswith(("/", "~", "\\")))]
    if not hits:
        return ""
    return (f"  warning: the command names {', '.join(hits)}, a place on this machine; a teammate who shares this file "
            "needs the same path")


def cmd_show(ns) -> int:
    root, cfg = _project()
    found = state(root)
    if found["file_error"]:
        return _refuse(found["file_error"])
    rows = [(key, row) for key, row in sorted(found["in_force"].items())
            if (not ns.environment or key[0] == ns.environment) and (not ns.profile or key[1] == ns.profile)]
    withdrawn = sorted(k for k in found["withdrawn"] if (not ns.environment or k[0] == ns.environment)
                       and (not ns.profile or k[1] == ns.profile))
    if ns.json:
        print(json.dumps({"in_force": [row for _key, row in rows], "withdrawn": [list(k) for k in withdrawn],
                          "history": found["history"], "errors": found["errors"]}, ensure_ascii=False, indent=2))
        return 0
    print(f"{registry_rel()}: {found['history']} row(s) in all, {len(rows)} in force"
          + (" for what you asked about" if ns.environment or ns.profile else ""))
    for (environment_id, profile_id), row in rows:
        note = "" if not in_config(cfg, environment_id, profile_id) else \
            " (not in this project's config: kept, never used)"
        print(f"  stand `{environment_id}`, {profile_id} tests: {method_words(row)} - {row['source']}, "
              f"{row['recorded_at']}{note}")
        warning = _abs_path_warning(row)
        if warning:
            print(warning)
    for environment_id, profile_id in withdrawn:
        print(f"  stand `{environment_id}`, {profile_id} tests: withdrawn - the factory reads it by its defaults")
    for problem in found["errors"]:
        print(f"  ignored: {problem}")
    return 0


def cmd_record(ns) -> int:
    root, cfg = _project()
    refusal = _stand_gate(cfg, ns.environment, ns.profile)
    if refusal:
        return _refuse(refusal)
    methods = data().get("methods") or {}
    if ns.method not in methods or ns.method == "withdrawn":
        return _refuse(f"method `{ns.method}` is not one `record` takes; the methods are "
                       f"{', '.join(m for m in methods if m != 'withdrawn')} (`forget` takes a decision back)")
    kwargs = {}
    if ns.method == "oci_label":
        kwargs["label"] = (ns.label or "").strip() or None
    elif ns.method == "build_sha_file":
        if not (ns.path or "").strip():
            return _refuse("method build_sha_file needs --path <the file inside the container that holds the commit>")
        kwargs["path"] = ns.path.strip()
    elif ns.method == "command":
        try:
            argv = command_argv(ns.command or "")
        except ValueError as exc:
            return _refuse(f"--command could not be read as a command line ({exc}); quote it like a shell would")
        if not argv:
            return _refuse("method command needs --command \"<the command line that prints the commit>\"")
        kwargs["argv"] = argv
    elif ns.method == "sources":
        kwargs["app_root"] = (ns.app_root or "").strip() or None
    if not (ns.words or "").strip() and ns.source == "person":
        return _refuse("--words is empty. A decision of the person carries the person's own words, so nothing was recorded")
    row = make_row(cfg, ns.environment, ns.profile, ns.method, words=ns.words or "", source=ns.source, **kwargs)
    try:
        append_row(root, row)
    except RegistryError as exc:
        return _refuse(str(exc))
    print(f"Recorded the decision for stand `{ns.environment}` ({ns.profile} tests) in {registry_rel()}: "
          f"{method_words(row)}. It is one file for all stands; commit it so the team shares it instead of answering again.")
    warning = _abs_path_warning(row)
    if warning:
        print(warning.strip())
    return 0


def cmd_forget(ns) -> int:
    root, cfg = _project()
    refusal = _stand_gate(cfg, ns.environment, ns.profile)
    if refusal:
        return _refuse(refusal)
    if not (ns.words or "").strip():
        return _refuse("--words is empty. Taking a decision back is the person's word too, so nothing was recorded")
    row = make_row(cfg, ns.environment, ns.profile, "withdrawn", words=ns.words)
    try:
        append_row(root, row)
    except RegistryError as exc:
        return _refuse(str(exc))
    print(f"Withdrew the decision for stand `{ns.environment}` ({ns.profile} tests) in {registry_rel()}: the factory "
          "reads this stand by its defaults again. The earlier rows stay in the file as history.")
    return 0


def _task_root(task: str):
    import hooklib
    try:
        return hooklib.story_root(task, "--task")
    except ValueError as exc:                # the driver's refusal: a key that is no story folder (CX1-18)
        raise RegistryError(f"{exc} Nothing was recorded.") from exc


def cmd_confirm(ns) -> int:
    root, cfg = _project()
    refusal = _stand_gate(cfg, ns.environment, ns.profile)
    if refusal:
        return _refuse(refusal)
    if not (ns.words or "").strip():
        return _refuse("--words is empty. A confirmation is the person's word, so nothing was recorded")
    for flag, value in (("--revision", ns.revision), ("--story-revision", ns.story_revision)):
        if value and not SHA40.fullmatch(value):
            return _refuse(f"{flag} must be a full 40-character commit (lower-case hex), not {value!r}; nothing was recorded")
    if not ns.revision:
        return _refuse("--revision <40 hex> is required: the commit the person says is on the stand")
    if ns.image and not IMAGE_RE.fullmatch(ns.image):
        return _refuse(f"--image must look like image:sha256:<64 hex>, not {ns.image!r}; nothing was recorded")
    if ns.content is not None:
        if ns.story_revision:
            return _refuse("--content and --story-revision are two different words (test as it is / test what is deployed); "
                           "give one of them. Nothing was recorded")
        if not SHA64.fullmatch(ns.content):
            return _refuse(f"--content must be the 64 lower-case hex characters the build question gave, not {ns.content!r}; "
                           "nothing was recorded")
    kind = ("content_accepted" if ns.content is not None
            else "test_deployed" if ns.story_revision and ns.story_revision != ns.revision else "deployed")
    try:
        task_root = _task_root(ns.task)
        add_confirmation(root, task_root, task=ns.task, environment_id=ns.environment, profile_id=ns.profile, kind=kind,
                         words=ns.words, revision=ns.revision, story_revision=ns.story_revision or "", image=ns.image or "",
                         stand_definition_sha=definition_sha_for(cfg, ns.environment), content=ns.content or "")
    except RegistryError as exc:
        return _refuse(str(exc))
    print(f"Took your word for {ns.task} only: recorded in {confirmations_rel(ns.task)}. {registry_rel()} is unchanged, "
          "so the next story asks again.")
    return 0


def cmd_unconfirm(ns) -> int:
    root, cfg = _project()
    refusal = _stand_gate(cfg, ns.environment, ns.profile)
    if refusal:
        return _refuse(refusal)
    if not (ns.words or "").strip():
        return _refuse("--words is empty. Taking a word back is the person's word too, so nothing was recorded")
    try:
        add_confirmation(root, _task_root(ns.task), task=ns.task, environment_id=ns.environment, profile_id=ns.profile,
                         kind="withdrawn", words=ns.words)
    except RegistryError as exc:
        return _refuse(str(exc))
    print(f"Took your word for {ns.task} back: the {ns.profile} tests of stand `{ns.environment}` are unconfirmed again.")
    return 0


def cmd_validate(ns) -> int:
    root, _cfg = _project()
    path = Path(ns.file) if ns.file else registry_path(root)
    text, error = _read_text(path)
    errors = [f"the file {error}"] if error else check_text(text)
    for line in errors:
        print(line)
    if not errors:
        print(f"{path}: valid")
    return 1 if errors else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="The stand's build identity: the registry of ways to read it, and the "
                                             "person's word for one story.")
    sub = ap.add_subparsers(dest="command", required=True)

    def common(p, task=False, words=True):
        p.add_argument("--environment", default="")
        p.add_argument("--profile", default="")
        if task:
            p.add_argument("--task", default="")
        if words:
            p.add_argument("--words", default="", help="the person's words, whole")
    show = sub.add_parser("show")
    common(show, words=False)
    show.add_argument("--json", action="store_true")
    show.set_defaults(fn=cmd_show)
    record = sub.add_parser("record")
    common(record)
    record.add_argument("--method", required=True)
    record.add_argument("--label", default="")
    record.add_argument("--path", default="")
    record.add_argument("--command", default="",
                        help="the command line that prints the commit; write paths with forward slashes (C:/x): they mean "
                             "the same everywhere, while backslashes are consumed by the shell-style split on every "
                             "system but Windows, where they are kept as written")
    record.add_argument("--app-root", default="")
    record.add_argument("--source", default="person")
    record.set_defaults(fn=cmd_record)
    forget = sub.add_parser("forget")
    common(forget)
    forget.set_defaults(fn=cmd_forget)
    confirm = sub.add_parser("confirm")
    common(confirm, task=True)
    confirm.add_argument("--revision", default="")
    confirm.add_argument("--story-revision", default="")
    confirm.add_argument("--image", default="")
    confirm.add_argument("--content", default=None, help="64 hex: the content the probe compared (kind content_accepted)")
    confirm.set_defaults(fn=cmd_confirm)
    unconfirm = sub.add_parser("unconfirm")
    common(unconfirm, task=True)
    unconfirm.set_defaults(fn=cmd_unconfirm)
    check = sub.add_parser("validate")
    check.add_argument("--file", default="")
    check.set_defaults(fn=cmd_validate)
    ns = ap.parse_args(argv)
    if ns.command in ("record", "forget", "confirm", "unconfirm") and (not ns.environment or not ns.profile):
        return _refuse(f"`{ns.command}` needs --environment <stand> and --profile <test profile>")
    if ns.command in ("confirm", "unconfirm") and not ns.task:
        return _refuse(f"`{ns.command}` needs --task <the story's id>")
    try:
        return ns.fn(ns)
    except RegistryError as exc:
        return _refuse(str(exc))


if __name__ == "__main__":
    sys.exit(main())
