# -*- coding: utf-8 -*-
"""The onboarding run's own notes, written as the phases go (B-411).

Before this script nothing of an onboarding survived a compaction or a new session: phases 1 and 2
held what they found and what the person answered "in working notes" (the model's context), and
the first file under `qa-factory/` appeared at phase 3's "yes". A run that lost its context asked
the same questions again, and a person who had answered them once met them a second time (FR-7).

The notes are the FACTORY'S OWN record of one run, not project files. They live in
`<project>/qa-factory/state/onboarding/` (the folder is in `references/onboarding-notes.json`, FR-13),
and the folder carries its own `.gitignore` (`*`), written before its first file, so `git status`
stays empty until phase 4. Nothing here writes into the project's own files, and no hook ever
creates `qa-factory/`: only `start` does, at phase 1's entry (hooklib.require_project, TP1-14336).

    onboarding_notes.py --root <project> status
    onboarding_notes.py --root <project> start --tree <clean|dirty>
    onboarding_notes.py --root <project> phase --set <p1|p2|p2b|p3|p4|done> [--sealed <path>] [--approval-ref <ref>]
    onboarding_notes.py --root <project> ask --batch <id> --questions-file <json [{"topic","text"}]>
    onboarding_notes.py --root <project> answer --batch <id> --words-file <path> --answered <t,...> [--not-answered <t,...>]
    onboarding_notes.py --root <project> set-aside
    onboarding_notes.py --root <project> close --approval-ref <ref>   (refused while the config's first reader is not
                                                                       satisfied: onboarding_first_reader.py names why)

Files in the folder, and who writes them:
  progress.yaml, interview.yaml   this script only; every scalar is a JSON string/number/bool, so
                                  `handoff.parse` reads it back exactly (an unquoted `null`, `true`
                                  or `a # b` would not survive it)
  discovery.yaml                  the role, one Edit per section: `state:`, `evidence:` (a list of
                                  "path:line") and `notes:`; `status` only READS it
  words/batch-<id>-<stamp>.txt    the person's words, written by the role with its file tool
  proposal.json, sealed.json, answers.json   phase 3's files (the folder is where they live)

stdout is one JSON document on success (FR-14); a refusal goes to stderr and exits 2, naming what
is wrong, what is expected and the door (FR-1). `status` writes nothing and always exits 0: a run
that cannot be read is a REPORT (`readable: false`), never a halt.

Error directions (the reused readers are in a more consequential role here):
  * `handoff.parse` decides "do not ask again": it may err only toward "not recorded" - a reply
    counts only while its words file exists under `words/` with the sha256 recorded;
  * `open_onboarding` gates p0 and both compaction hooks: it may err toward reporting a run, never
    toward missing one;
  * staleness comes from `git diff`: it may err only toward stale.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
sys.path.insert(0, str(HERE))
import handoff  # noqa: E402
from hooklib import sorted_paths  # noqa: E402

DATA_REL = "references/onboarding-notes.json"
# Used ONLY when the data file cannot be read: the hooks still have to say where a run is, and the
# folder is itself a value of that file. The data file wins whenever it can be read.
FALLBACK_FOLDER = "qa-factory/state/onboarding"
SCHEMA = 1
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
# What may sit in the folder without being a run: its own ignore file and the two archives.
NOT_A_RUN = (".gitignore", "retired", "done")
EXIT_REFUSED = 2

PROGRESS = "progress.yaml"
INTERVIEW = "interview.yaml"
DISCOVERY = "discovery.yaml"
WORDS = "words"


class NotesError(Exception):
    """A refusal: the text says what is wrong, what was expected and the door."""


# --------------------------------------------------------------------------------------- the data file

def data_path() -> Path:
    return PLUGIN / DATA_REL


def load_data() -> dict:
    """The closed lists. Raises NotesError naming the file when it is missing or malformed."""
    path = data_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise NotesError(f"{path} cannot be read ({exc}); it is part of the package: reinstall the plugin") from None
    need = {"folder": str, "phases": list, "phase_files": dict, "discovery_sections": list,
            "section_states": list, "topic_states": list, "after_approval_batch_prefix": str, "reask_batch_prefixes": list}
    for key, kind in need.items():
        if not isinstance(data, dict) or not isinstance(data.get(key), kind):
            raise NotesError(f"{path} has no usable `{key}` (expected {kind.__name__}); it is part of the package: "
                             "reinstall the plugin")
    return data


def notes_dir(root, data: dict | None = None) -> Path:
    """The ONE place the notes folder is computed: the CLI, p0 and both hooks print this path (FR-37)."""
    folder = (data or {}).get("folder") or FALLBACK_FOLDER
    return Path(root).resolve().joinpath(*folder.split("/"))


def phase_file(phase, data: dict | None) -> str:
    """The absolute path of the phase text a phase reads, or "" when the data cannot say."""
    try:
        name = (data or {})["phase_files"].get(phase)
        if not name:
            return ""
        return str((PLUGIN / Path(*data["phases_dir"].split("/")) / name))
    except Exception:
        return ""


# --------------------------------------------------------------------------------------- writing the notes

_ESCAPE = re.compile("[\\u007f-\\u009f\\u2028\\u2029{}\\[\\]]")


def q(value) -> str:
    """One scalar as `json.dumps(value, ensure_ascii=False)`, plus a `\\uXXXX` escape for what the
    line reader of `handoff.parse` would otherwise misread: the characters `str.splitlines` breaks a
    line at (U+2028, U+0085, ...) and the brackets and braces its flow-collection counter looks at.
    The result is still a JSON string, and `json.loads` gives the original text back."""
    return _ESCAPE.sub(lambda m: "\\u%04x" % ord(m.group(0)), json.dumps(value, ensure_ascii=False))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_atomic(path: Path, text: str) -> None:
    fd, temp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


PROGRESS_FIELDS = ("schema_version", "started_at", "updated_at", "phase", "head", "config_sha", "tree",
                   "sealed", "approval_ref", "frozen")


def emit_progress(progress: dict) -> str:
    return "".join(f"{key}: {q(progress[key])}\n" for key in PROGRESS_FIELDS)


def emit_interview(updated_at: str, batches: list) -> str:
    lines = [f"schema_version: {q(SCHEMA)}", f"updated_at: {q(updated_at)}"]
    if not batches:
        lines.append("batches: []")
    else:
        lines.append("batches:")
        for b in batches:
            lines.append(f"  - batch: {q(b['batch'])}")
            lines.append(f"    asked_at: {q(b['asked_at'])}")
            lines.append(f"    times_asked: {q(b['times_asked'])}")
            lines.append("    questions:")
            for item in b["questions"]:
                lines.append(f"      - topic: {q(item['topic'])}")
                lines.append(f"        text: {q(item['text'])}")
                lines.append(f"        ask: {q(item['ask'])}")
            if not b["replies"]:
                lines.append("    replies: []")
            else:
                lines.append("    replies:")
                for r in b["replies"]:
                    lines.append(f"      - words_file: {q(r['words_file'])}")
                    lines.append(f"        sha256: {q(r['sha256'])}")
                    lines.append(f"        at: {q(r['at'])}")
                    lines.append(f"        answered: {_flow(r['answered'])}")
                    lines.append(f"        not_answered: {_flow(r['not_answered'])}")
    return "\n".join(lines) + "\n"


def _flow(items) -> str:
    return "[" + ", ".join(q(i) for i in items) + "]" if items else "[]"


def emit_discovery_skeleton(sections) -> str:
    return "".join(f'{s}:\n  state: {q("pending")}\n  evidence: []\n  notes: ""\n' for s in sections)


# --------------------------------------------------------------------------------------- reading the notes

def _read_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8-sig")


def _sha_of_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _entries(notes: Path) -> list:
    """The names in the folder that are not its own ignore file or an archive. Raises OSError."""
    return sorted(e.name for e in os.scandir(notes) if e.name not in NOT_A_RUN)


def _is_run(notes: Path) -> tuple:
    """(open, problem). `open` errs toward True: any top-level name other than the ignore file and
    the two archives is the run (a partial folder is still somebody's answers)."""
    try:
        if not notes.is_dir():
            return False, None
        return bool(_entries(notes)), None
    except OSError as exc:
        return True, f"the folder {notes} cannot be listed ({exc.strerror or exc})"


def _read_progress(notes: Path, data: dict) -> tuple:
    """(progress dict | None, fatal problem | None). A missing, empty, garbage or newer file is
    unreadable and nothing of it is reused."""
    path = notes / PROGRESS
    if not path.exists():
        return None, f"{PROGRESS} is missing from {notes}"
    if path.is_dir():
        return None, f"{PROGRESS} is a folder, not a file"
    try:
        text = _read_text(path)
    except (OSError, ValueError) as exc:
        return None, f"{PROGRESS} cannot be read ({exc})"
    if not text.strip():
        return None, f"{PROGRESS} is empty"
    d = handoff.parse(text).data
    version = d.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int):
        return None, f"{PROGRESS} has no schema_version"
    if version > SCHEMA:
        return None, (f"{PROGRESS} was written by a newer factory (schema_version {version}, this one reads "
                      f"{SCHEMA}): update the plugin, or set the run aside")
    if version < SCHEMA:
        return None, f"{PROGRESS} has schema_version {version}, which this factory does not read"
    out = {"schema_version": version}
    spec = {"started_at": str, "updated_at": str, "phase": str, "head": str, "config_sha": str, "tree": str,
            "sealed": str, "approval_ref": str, "frozen": bool}
    required = ("started_at", "phase")
    for key, kind in spec.items():
        if key not in d:
            if key in required:
                return None, f"{PROGRESS} has no `{key}`"
            out[key] = False if kind is bool else ""
            continue
        if not isinstance(d[key], kind):
            return None, f"{PROGRESS}: `{key}` is {d[key]!r}, expected {kind.__name__}"
        out[key] = d[key]
    if out["phase"] not in data["phases"]:
        return None, f"{PROGRESS}: phase {out['phase']!r} is not one of {data['phases']}"
    if not out["updated_at"]:
        out["updated_at"] = out["started_at"]
    return out, None


def _read_interview(notes: Path) -> tuple:
    """(batches, fatal problem | None). No file is the normal state before phase 2."""
    path = notes / INTERVIEW
    if not path.exists():
        return [], None
    if path.is_dir():
        return [], f"{INTERVIEW} is a folder, not a file"
    try:
        text = _read_text(path)
    except (OSError, ValueError) as exc:
        return [], f"{INTERVIEW} cannot be read ({exc})"
    if not text.strip():
        return [], f"{INTERVIEW} is empty"
    d = handoff.parse(text).data
    version = d.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int):
        return [], f"{INTERVIEW} has no schema_version"
    if version > SCHEMA:
        return [], f"{INTERVIEW} was written by a newer factory (schema_version {version}, this one reads {SCHEMA})"
    if version < SCHEMA:
        return [], f"{INTERVIEW} has schema_version {version}, which this factory does not read"
    raw = d.get("batches")
    if raw is None or raw == {} or raw == "":
        raw = []
    if not isinstance(raw, list):
        return [], f"{INTERVIEW}: `batches` is not a list"
    batches = []
    for i, b in enumerate(raw):
        why = _batch_shape(b)
        if why:
            return [], f"{INTERVIEW}: batch #{i + 1} {why}"
        batches.append(b)
    return batches, None


def _list_of(value) -> list | None:
    if value is None or value == {}:
        return []
    return value if isinstance(value, list) else None


def _batch_shape(b) -> str | None:
    if not isinstance(b, dict):
        return "is not a map"
    if not (isinstance(b.get("batch"), str) and ID_RE.match(b["batch"])):
        return f"has no valid id ({b.get('batch')!r})"
    if not isinstance(b.get("asked_at"), str):
        return f"({b['batch']}) has no asked_at"
    times = b.get("times_asked")
    if isinstance(times, bool) or not isinstance(times, int) or times < 1:
        return f"({b['batch']}) has no times_asked"
    questions = _list_of(b.get("questions"))
    replies = _list_of(b.get("replies"))
    if questions is None or replies is None:
        return f"({b['batch']}) has questions or replies that are not lists"
    b["questions"], b["replies"] = questions, replies
    for item in questions:
        if not (isinstance(item, dict) and isinstance(item.get("topic"), str) and isinstance(item.get("text"), str)
                and isinstance(item.get("ask"), int) and not isinstance(item.get("ask"), bool)):
            return f"({b['batch']}) has a question that is not {{topic, text, ask}}"
    for r in replies:
        if not (isinstance(r, dict) and isinstance(r.get("words_file"), str) and isinstance(r.get("sha256"), str)
                and isinstance(r.get("at"), str)):
            return f"({b['batch']}) has a reply that is not {{words_file, sha256, at, answered, not_answered}}"
        for key in ("answered", "not_answered"):
            got = _list_of(r.get(key))
            if got is None or not all(isinstance(t, str) for t in got):
                return f"({b['batch']}) has a reply whose `{key}` is not a list of topics"
            r[key] = got
    return None


def _reply_valid(notes: Path, reply: dict) -> tuple:
    """(valid, why-not). A reply counts only while its words file lies under words/ and still has the
    bytes that were recorded: a reply measured on other bytes is absent."""
    rel = reply["words_file"]
    try:
        words = (notes / Path(*rel.split("/"))).resolve()
        words.relative_to((notes / WORDS).resolve())
    except (ValueError, OSError):
        return False, f"words file {rel!r} is not under {WORDS}/"
    if ".." in rel.split("/") or rel.startswith("/") or ":" in rel:
        return False, f"words file {rel!r} is not a path under {WORDS}/"
    try:
        got = _sha_of_file(words)
    except OSError:
        return False, f"words file {rel} is missing"
    if got != reply["sha256"]:
        return False, f"words file {rel} has changed since it was recorded"
    return True, None


def _own_topics(batch: dict) -> list:
    """The topics a batch asked, in the order first asked."""
    out = []
    for item in batch["questions"]:
        if item["topic"] not in out:
            out.append(item["topic"])
    return out


def _covered(notes: Path, batch: dict) -> set:
    """The topics the batch's VALID replies settle, answered or not answered."""
    out = set()
    for r in batch["replies"]:
        if _reply_valid(notes, r)[0]:
            out.update(r["answered"])
            out.update(r["not_answered"])
    return out


def _topics_and_replies(notes: Path, batches: list, soft: list) -> tuple:
    """(answered, not_answered, awaiting_reply, awaiting_topics, batch rows for status, holders).

    A batch is awaiting while any topic it asked is in no valid reply's `answered` or `not_answered`
    (critic t-530 F1: a reply naming only some topics must not clear the whole batch, or the rest is lost and
    cannot be asked again). `awaiting_topics` is `{batch: [topics still open]}`; `holders` is
    `{topic: batch that holds its ANSWER}`, for the refusal of a re-ask under a new batch id (F6)."""
    states: dict = {}
    holders: dict = {}
    awaiting = []
    awaiting_topics = {}
    rows = []
    for b in batches:
        reply_rows = []
        for r in b["replies"]:
            ok, why = _reply_valid(notes, r)
            if not ok:
                soft.append(f"batch {b['batch']}: the reply recorded at {r['at']}: {why}; it counts as not recorded")
            else:
                for t in r["answered"]:
                    states[t] = "answered"
                    holders[t] = b["batch"]
                for t in r["not_answered"]:
                    states[t] = "not_answered"
                    holders.pop(t, None)
            reply_rows.append({"words_file": r["words_file"], "sha256": r["sha256"], "at": r["at"],
                               "answered": list(r["answered"]), "not_answered": list(r["not_answered"]),
                               "valid": ok})
        covered = _covered(notes, b)
        missing = [t for t in _own_topics(b) if t not in covered]
        if missing or not covered:
            awaiting.append(b["batch"])
            awaiting_topics[b["batch"]] = missing
        rows.append({"batch": b["batch"], "asked_at": b["asked_at"], "times_asked": b["times_asked"],
                     "replies": reply_rows})
    answered = [t for t, s in states.items() if s == "answered"]
    not_answered = [t for t, s in states.items() if s == "not_answered"]
    return answered, not_answered, awaiting, awaiting_topics, rows, holders


def _unrecorded_words(notes: Path, batches: list) -> list:
    """Files under words/ named `batch-*` that no reply refers to (critic t-530 F2): the role wrote the person's
    words, the context was compacted, `answer` never ran. They are the person's reply on disk: record them with
    `answer` instead of asking again with a false reason (FR-7)."""
    known = {r["words_file"] for b in batches for r in b["replies"]}
    try:
        names = sorted(e.name for e in os.scandir(notes / WORDS) if e.is_file() and e.name.startswith("batch-"))
    except OSError:
        return []
    return [f"{WORDS}/{n}" for n in names if f"{WORDS}/{n}" not in known]


def read_run(notes: Path, data: dict) -> dict:
    """Everything about an open run that needs no git: the shape `status` and the hooks share."""
    fatal, soft = [], []
    progress, why = _read_progress(notes, data)
    if why:
        fatal.append(why)
    batches, why = _read_interview(notes)
    if why:
        fatal.append(why)
    answered, not_answered, awaiting, awaiting_topics, rows, holders = _topics_and_replies(notes, batches, soft)
    return {"progress": progress, "readable": not fatal, "fatal": fatal, "soft": soft,
            "answered": answered, "not_answered": not_answered, "awaiting_reply": awaiting,
            "awaiting_topics": awaiting_topics, "unrecorded_words": _unrecorded_words(notes, batches),
            "answer_holders": holders, "batches": rows, "batch_data": batches}


# --------------------------------------------------------------------------------------- the locator

def _candidate_roots(root, event) -> list:
    out = []
    seen = set()

    def add(path):
        try:
            p = Path(path).resolve()
        except Exception:
            return
        if str(p) not in seen:
            seen.add(str(p))
            out.append(p)

    add(root)
    if event is not None:
        starts = []
        if isinstance(event, dict) and event.get("cwd"):
            starts.append(event["cwd"])
        starts.append(Path.cwd())
        for start in starts:
            try:
                cur = Path(start).resolve()
            except Exception:
                continue
            add(cur)
            for parent in cur.parents:
                add(parent)
    return out


def open_onboarding(root, event=None) -> dict:
    """The ONE predicate for 'is there an unfinished onboarding here': `status`, p0 and both
    compaction hooks use it. It reads and never creates. With an event it also looks upward from the
    event's cwd (a session opened below the project root); it errs toward reporting a run.

    -> {open, path, root, readable, problem[], phase, answered[], not_answered[], awaiting_reply[], awaiting_topics{}}"""
    out = {"open": False, "path": None, "root": None, "readable": True, "problem": [], "phase": None,
           "answered": [], "not_answered": [], "awaiting_reply": [], "awaiting_topics": {}}
    try:
        data = load_data()
        data_problem = None
    except NotesError as exc:
        data, data_problem = None, str(exc)
    for candidate in _candidate_roots(root, event):
        notes = notes_dir(candidate, data)
        is_open, problem = _is_run(notes)
        if not is_open:
            continue
        out.update({"open": True, "path": notes, "root": candidate})
        if data_problem:
            out["readable"] = False
            out["problem"] = [data_problem]
            return out
        run = read_run(notes, data)
        out["problem"] = ([problem] if problem else []) + run["fatal"] + run["soft"]
        out["readable"] = run["readable"] and not problem
        if run["progress"]:
            out["phase"] = run["progress"]["phase"]
        out["answered"], out["not_answered"], out["awaiting_reply"], out["awaiting_topics"] = (
            run["answered"], run["not_answered"], run["awaiting_reply"], run["awaiting_topics"])
        return out
    return out


# --------------------------------------------------------------------------------------- git and staleness

def _git(root: Path, *args) -> tuple:
    """(returncode, stdout). (None, reason) when git cannot be started."""
    try:
        done = subprocess.run(["git", "-c", "core.quotepath=false", *args], cwd=str(root), capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)
    return done.returncode, done.stdout


def head_of(root: Path) -> str:
    code, out = _git(root, "rev-parse", "HEAD")
    return out.strip() if code == 0 and SHA_RE.match(out.strip()) else ""


def config_sha_of(root: Path) -> str:
    path = Path(root) / "qa-factory" / "config.json"
    try:
        return _sha_of_file(path)
    except OSError:
        return ""


def _norm_path(text: str) -> str:
    text = str(text).replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text.casefold()


def _uncomparable(text: str) -> bool:
    """An evidence path that cannot be matched against a diff relative to the project root."""
    return (text.startswith("/") or bool(re.match(r"^[A-Za-z]:", text)) or ".." in text.split("/")
            or text == "")


def evidence_is_stale(entry, changed: set) -> bool:
    """One evidence entry against the set of changed paths; errs only toward stale."""
    if not isinstance(entry, str):
        return True
    whole = _norm_path(entry)
    if _uncomparable(whole):
        return True
    candidates = {whole}
    if ":" in whole:
        candidates.add(whole.rsplit(":", 1)[0])
    for c in candidates:
        if _uncomparable(c):
            return True
        if c in changed or any(p.startswith(c.rstrip("/") + "/") for p in changed):
            return True
    return False


def _discovery(notes: Path, data: dict, soft: list) -> tuple:
    """(sections {id: (state, evidence list)}, extra ids). A section whose state is missing, null or
    not a data word, or whose evidence is not a list, is `pending` and named in `soft`."""
    path = notes / DISCOVERY
    sections: dict = {}
    extra = []
    states = data["section_states"]
    text = ""
    if path.exists():
        try:
            text = _read_text(path)
        except (OSError, ValueError) as exc:
            soft.append(f"{DISCOVERY} cannot be read ({exc}); every section is read as pending")
    top = handoff.parse(text).data if text.strip() else {}
    for key, value in top.items():
        if not isinstance(value, dict):
            soft.append(f"{DISCOVERY}: `{key}` is not a section (a map with state, evidence and notes); it is ignored")
            continue
        state = value.get("state")
        evidence = value.get("evidence")
        if evidence is None or evidence == {}:
            evidence = []
        if not (isinstance(state, str) and state in states):
            soft.append(f"{DISCOVERY}: section {key}: state {state!r} is not one of {states}; read as pending")
            state = "pending"
        if not isinstance(evidence, list):
            soft.append(f"{DISCOVERY}: section {key}: evidence {evidence!r} is not a list of \"path:line\" entries; "
                        "read as pending")
            state, evidence = "pending", []
        sections[key] = (state, evidence)
        if key not in data["discovery_sections"]:
            extra.append(key)
    for key in data["discovery_sections"]:
        sections.setdefault(key, ("pending", []))
    return sections, extra


def _staleness(root: Path, head_then: str, sections: dict, soft: list) -> tuple:
    """(changed_since, stale_section ids). Errs only toward stale (A6)."""
    with_evidence = [k for k, (_s, ev) in sections.items() if ev]
    if not head_then or not SHA_RE.match(head_then):
        soft.append("no usable head was recorded when the run started: every section with evidence is treated as changed")
        return [], with_evidence
    code, out = _git(root, "diff", "--name-only", "--relative", head_then)
    if code is None:
        soft.append(f"git cannot be run here ({out}): every section with evidence is treated as changed")
        return [], with_evidence
    if code != 0:
        soft.append(f"head {head_then} is not known here (git exit {code}): every section with evidence is treated "
                    "as changed")
        return [], with_evidence
    changed = [line.strip() for line in out.splitlines() if line.strip()]
    changed_norm = {_norm_path(c) for c in changed}
    stale = [k for k in with_evidence if any(evidence_is_stale(e, changed_norm) for e in sections[k][1])]
    return changed, stale


def status_document(root, data: dict | None, data_problem: str | None = None) -> dict:
    """The fixed-shape report of `status` (FR-14). Writes nothing."""
    rootp = Path(root).resolve()
    notes = notes_dir(rootp, data)
    doc = {"exists": False, "path": str(notes), "readable": True, "problem": [],
           "schema_version": None, "phase": None, "started_at": None, "updated_at": None,
           "approval_ref": None, "frozen": False,
           "head_then": None, "head_now": None, "config_sha_then": None, "config_sha_now": None,
           "changed_since": [], "stale_sections": [],
           "discovery_sections": {}, "extra_sections": [],
           "batches": [], "answered": [], "not_answered": [], "awaiting_reply": [], "awaiting_topics": {},
           "unrecorded_words": []}
    if data_problem:
        doc["readable"] = False
        doc["problem"] = [data_problem]
        is_open, why = _is_run(notes)
        doc["exists"] = is_open
        return doc
    is_open, why = _is_run(notes)
    if not is_open:
        return doc
    doc["exists"] = True
    run = read_run(notes, data)
    soft = list(run["soft"])
    progress = run["progress"]
    if progress:
        doc.update({"schema_version": progress["schema_version"], "phase": progress["phase"],
                    "started_at": progress["started_at"], "updated_at": progress["updated_at"],
                    "approval_ref": progress["approval_ref"] or None, "frozen": progress["frozen"],
                    "head_then": progress["head"] or None, "config_sha_then": progress["config_sha"] or None})
    doc["head_now"] = head_of(rootp) or None
    doc["config_sha_now"] = config_sha_of(rootp) or None
    sections, extra = _discovery(notes, data, soft)
    doc["discovery_sections"] = {k: v[0] for k, v in sections.items()}
    doc["extra_sections"] = extra
    if progress:
        doc["changed_since"], doc["stale_sections"] = _staleness(rootp, progress["head"], sections, soft)
    doc["batches"] = run["batches"]
    doc["answered"], doc["not_answered"], doc["awaiting_reply"] = run["answered"], run["not_answered"], run["awaiting_reply"]
    doc["awaiting_topics"], doc["unrecorded_words"] = run["awaiting_topics"], run["unrecorded_words"]
    doc["readable"] = run["readable"] and why is None
    doc["problem"] = ([why] if why else []) + run["fatal"] + soft
    return doc


# --------------------------------------------------------------------------------------- the subcommands

def _refuse_door_status(root) -> str:
    return ("`onboarding_notes.py --root . status` shows the run; `onboarding_notes.py --root . set-aside` starts "
            "over (the notes are moved to retired/, never deleted)")


def _require_run(root, data: dict) -> tuple:
    """(notes, run) of an open, readable run, or a refusal."""
    notes = notes_dir(root, data)
    is_open, why = _is_run(notes)
    if not is_open:
        raise NotesError(f"no onboarding run is open in {Path(root).resolve()} (expected {notes} to hold progress.yaml). "
                         "Phase 1 starts one: `onboarding_notes.py --root . start --tree <clean|dirty>`")
    run = read_run(notes, data)
    if not run["readable"] or why:
        raise NotesError(f"the onboarding run at {notes} cannot be read ({'; '.join(([why] if why else []) + run['fatal'])}). "
                         "Nothing of it is reused. Ask the person whether to start over (set it aside) or to stop: "
                         + _refuse_door_status(root))
    return notes, run


def _check_id(kind: str, value: str) -> None:
    if not (isinstance(value, str) and ID_RE.match(value)):
        raise NotesError(f"{kind} {value!r} is not an id: expected letters, digits, `_`, `.` or `-`, starting with a "
                         "letter or digit (no `:`, no spaces)")


def _save_progress(notes: Path, progress: dict) -> None:
    progress["updated_at"] = _now()
    write_atomic(notes / PROGRESS, emit_progress(progress))


def cmd_start(root, data: dict, tree: str) -> dict:
    rootp = Path(root).resolve()
    if tree not in ("clean", "dirty"):
        raise NotesError(f"--tree {tree!r}: expected `clean` or `dirty` (phase 0's working-tree note)")
    if not rootp.is_dir():
        raise NotesError(f"--root {rootp} is not a folder; pass the project root")
    notes = notes_dir(rootp, data)
    is_open, _why = _is_run(notes)
    if is_open:
        run = read_run(notes, data)
        p = run["progress"] or {}
        raise NotesError(f"an unfinished onboarding is already at {notes} (phase {p.get('phase', 'unknown')}, started "
                         f"{p.get('started_at', 'at an unknown time')}, last written {p.get('updated_at', 'unknown')}). "
                         "Do not start a second one: " + _refuse_door_status(rootp) + ". The person decides at phase 0")
    notes.mkdir(parents=True, exist_ok=True)
    gitignore = notes / ".gitignore"
    if not gitignore.exists():
        write_atomic(gitignore, "*\n")        # FIRST: git sees nothing the run writes after this line
    now = _now()
    progress = {"schema_version": SCHEMA, "started_at": now, "updated_at": now, "phase": "p1",
                "head": head_of(rootp), "config_sha": config_sha_of(rootp), "tree": tree, "sealed": "",
                "approval_ref": "", "frozen": False}
    write_atomic(notes / PROGRESS, emit_progress(progress))
    write_atomic(notes / DISCOVERY, emit_discovery_skeleton(data["discovery_sections"]))
    return {"path": str(notes)}


def _approved(root, ref: str) -> bool:
    import config_contract
    try:
        lines = config_contract.approvals_path(root).read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in lines:
        try:
            record = json.loads(line) if line.strip() else None
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("approval_ref") == ref and record.get("status") == "approved":
            return True
    return False


def cmd_phase(root, data: dict, phase: str, sealed, approval_ref) -> dict:
    notes, run = _require_run(root, data)
    progress = dict(run["progress"])
    if phase not in data["phases"]:
        raise NotesError(f"--set {phase!r} is not a phase: expected one of {data['phases']}")
    if phase == "done":
        raise NotesError("--set done is refused: a run is finished by `close`, which moves it to done/ in one step "
                         "(critic t-530 F3: a phase word alone would leave the files where an open run is looked for). "
                         "Run `onboarding_notes.py --root . close --approval-ref <ref>` after phase 4's audit")
    if phase == "p4" and not progress["frozen"] and approval_ref is None:
        raise NotesError("--set p4 needs the person's recorded yes: the run is not frozen and no --approval-ref was given. "
                         "Record the approval (`config_contract.py --root . --record-approval <sealed.json> --approval-ref "
                         "<ref> --evidence-ref <the person's yes in the transcript>`), then run `onboarding_notes.py "
                         "--root . phase --set p4 --approval-ref <ref> --sealed <sealed.json>`")
    if progress["frozen"] and phase not in ("p4", "done"):
        raise NotesError(f"the run is frozen at the person's yes (approval {progress['approval_ref']}): only p4 and done "
                         f"are accepted, not {phase}. What the yes approved is not changed after it; a correction now "
                         "is a new onboarding (`set-aside`, then phase 1)")
    if approval_ref is not None:
        if not approval_ref.strip():
            raise NotesError("--approval-ref is empty: pass the reference the approval was recorded under")
        if progress["frozen"] and approval_ref != progress["approval_ref"]:
            raise NotesError(f"the run is already frozen under approval {progress['approval_ref']!r}: it is not moved to "
                             f"{approval_ref!r}. What the yes approved is not changed after it; a correction now is a new "
                             "onboarding (`set-aside`, then phase 1)")
        if not _approved(root, approval_ref):
            raise NotesError(f"approval {approval_ref!r} is not on record as approved in the approvals log: record it "
                             "first with `config_contract.py --root . --record-approval <sealed.json> --approval-ref "
                             f"{approval_ref} --evidence-ref <the person's yes in the transcript>`, then run this again")
        progress["approval_ref"] = approval_ref
        progress["frozen"] = True
    if sealed is not None:
        progress["sealed"] = sealed
    progress["phase"] = phase
    _save_progress(notes, progress)
    return {"phase": phase, "approval_ref": progress["approval_ref"] or None, "sealed": progress["sealed"] or None}


def _read_questions(path: str) -> list:
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise NotesError(f"--questions-file {path} cannot be read ({exc.strerror or exc}); write the batch as a JSON "
                         'list [{"topic": "<id>", "text": "<the question as it will be put>"}] and pass it again; '
                         "nothing was recorded") from None
    if b"\x00" in raw:
        raise NotesError(f"--questions-file {path} is not UTF-8 text (a Windows PowerShell 5.1 `>` redirect writes UTF-16); "
                         "save it as UTF-8 and pass it again; nothing was recorded")
    try:
        loaded = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise NotesError(f"--questions-file {path} is not UTF-8 JSON; expected a list "
                         '[{"topic": "<id>", "text": "<question>"}]; nothing was recorded') from None
    if not (isinstance(loaded, list) and loaded):
        raise NotesError(f"--questions-file {path}: expected a non-empty list [{{\"topic\", \"text\"}}]; nothing was recorded")
    out = []
    for i, item in enumerate(loaded):
        if not (isinstance(item, dict) and isinstance(item.get("topic"), str) and isinstance(item.get("text"), str)
                and item["text"].strip()):
            raise NotesError(f"--questions-file {path}: item {i + 1} must be {{\"topic\": \"<id>\", \"text\": \"<the "
                             "question, not empty>\"}; nothing was recorded")
        _check_id("topic", item["topic"])
        out.append({"topic": item["topic"], "text": item["text"]})
    return out


def cmd_ask(root, data: dict, batch: str, questions_file: str) -> dict:
    notes, run = _require_run(root, data)
    _check_id("batch", batch)
    progress = dict(run["progress"])
    prefix = data["after_approval_batch_prefix"]
    if progress["frozen"] and not batch.startswith(prefix):
        raise NotesError(f"the run is frozen at the person's yes (approval {progress['approval_ref']}): only batches whose "
                         f"id starts with {prefix!r} are accepted, not {batch!r}. What the yes approved is not changed "
                         "after it; a correction now is a new onboarding")
    questions = _read_questions(questions_file)
    batches = [dict(b) for b in run["batch_data"]]
    existing = next((b for b in batches if b["batch"] == batch), None)
    # A topic that is settled is not asked again (FR-7): refused when this batch's own replies cover it (answered or
    # not), and when ANY batch holds its answer - unless the new batch id starts with a prefix the data file lists
    # (`reask_batch_prefixes`: a correction round p3-edit-<n>, phase 4's own batches), where a changed answer is legitimate.
    exempt = any(batch.startswith(p) for p in data["reask_batch_prefixes"])
    covered_here = _covered(notes, existing) if existing is not None else set()
    closed = []
    for item in questions:
        topic = item["topic"]
        if topic in covered_here:
            closed.append(f"{topic!r} is already settled by a reply in batch {batch!r}")
        elif topic in run["answer_holders"] and not exempt:
            closed.append(f"{topic!r} is already answered under batch {run['answer_holders'][topic]!r}")
    if closed:
        raise NotesError("a topic that is answered is not asked again: " + "; ".join(closed) + ". Ask only what is still open "
                         f"(`status` lists it under awaiting_topics); a changed answer is asked in a batch whose id starts "
                         f"with one of {data['reask_batch_prefixes']}")
    if existing is None:
        existing = {"batch": batch, "asked_at": _now(), "times_asked": 1, "questions": [], "replies": []}
        batches.append(existing)
    else:
        existing["times_asked"] += 1
    for item in questions:
        existing["questions"].append({"topic": item["topic"], "text": item["text"], "ask": existing["times_asked"]})
    now = _now()
    write_atomic(notes / INTERVIEW, emit_interview(now, batches))
    _save_progress(notes, progress)
    return {"batch": batch, "times_asked": existing["times_asked"], "path": str(notes / INTERVIEW)}


def _split_topics(text, flag: str) -> list:
    out = []
    for part in (text or "").split(","):
        part = part.strip()
        if part:
            _check_id("topic", part)
            out.append(part)
    return out


def cmd_answer(root, data: dict, batch: str, words_file: str, answered: str, not_answered) -> dict:
    import person_words
    door = person_words.door(f"onboarding_notes.py --root . answer --batch {batch} --answered <topics>")

    def refuse(text: str):
        raise NotesError(f"{text} Nothing was recorded. {door}")

    try:
        notes, run = _require_run(root, data)
        _check_id("batch", batch)
        yes = _split_topics(answered, "--answered")
        no = _split_topics(not_answered, "--not-answered")
    except NotesError as exc:
        refuse(str(exc).rstrip(".") + ".")
    batches = [dict(b) for b in run["batch_data"]]
    found = next((b for b in batches if b["batch"] == batch), None)
    if found is None:
        refuse(f"batch {batch!r} is not on record (recorded: {[b['batch'] for b in batches] or 'none'}): record the "
               "batch before its reply, with `onboarding_notes.py --root . ask`.")
    own = {item["topic"] for item in found["questions"]}
    if not yes and not no:
        refuse("--answered names no topic: name the topics the reply settles (and --not-answered for the ones the "
               "person did not answer).")
    stray = sorted(t for t in set(yes) | set(no) if t not in own)
    if stray:
        refuse(f"topic(s) {stray} do not belong to batch {batch!r} (its topics: {sorted(own)}).")
    both = sorted(set(yes) & set(no))
    if both:
        refuse(f"topic(s) {both} are named both answered and not answered.")
    words_dir = (notes / WORDS).resolve()
    try:
        target = Path(words_file).resolve()
        target.relative_to(words_dir)
    except (ValueError, OSError):
        refuse(f"--words-file {words_file} is not under {words_dir}: the person's words are kept in that folder, one "
               "file per reply, named batch-<id>-<YYYYMMDD-HHMMSS>.txt.")
    try:
        person_words.read(None, str(target), "--words")
    except person_words.WordsRefused as exc:
        refuse(str(exc))
    raw = target.read_bytes()
    reply = {"words_file": target.relative_to(notes.resolve()).as_posix(), "sha256": hashlib.sha256(raw).hexdigest(),
             "at": _now(), "answered": yes, "not_answered": no}
    found["replies"] = list(found["replies"]) + [reply]
    now = _now()
    write_atomic(notes / INTERVIEW, emit_interview(now, batches))
    _save_progress(notes, dict(run["progress"]))
    covered = _covered(notes, found)
    return {"batch": batch, "words_file": reply["words_file"], "sha256": reply["sha256"], "answered": yes,
            "not_answered": no, "still_open": [t for t in _own_topics(found) if t not in covered]}


def _next_free(parent: Path, name: str) -> Path:
    """`parent/name`, or `parent/name-2`, `-3`...: nothing is ever overwritten."""
    n = 1
    while True:
        candidate = parent / (name if n == 1 else f"{name}-{n}")
        try:
            candidate.mkdir(parents=True, exist_ok=False)
            return candidate
        except FileExistsError:
            n += 1


def _move_run(notes: Path, target: Path) -> list:
    moved = []
    for name in _entries(notes):
        os.replace(notes / name, target / name)
        moved.append(name)
    return moved


def cmd_set_aside(root, data: dict) -> dict:
    notes = notes_dir(root, data)
    is_open, _why = _is_run(notes)
    if not is_open:
        return {"set_aside": [], "to": None, "note": f"no run is open at {notes}: nothing to set aside"}
    target = _next_free(notes / "retired", datetime.now().strftime("%Y-%m-%d"))
    return {"set_aside": _move_run(notes, target), "to": str(target)}


def _sanitise_ref(ref: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]", "_", ref).lstrip(".-")
    return text or "ref"


def _already_closed(notes, data: dict, approval_ref: str) -> dict | None:
    """The answer for a run closed earlier under THIS approval, else None (no `done/` folder, or another approval)."""
    base = _sanitise_ref(approval_ref)
    done = notes / "done"
    if not done.is_dir():
        return None
    for entry in sorted_paths(done.iterdir()):
        if entry.name == base or re.fullmatch(re.escape(base) + r"-\d+", entry.name):
            p, _why2 = _read_progress(entry, data)
            if p and p["approval_ref"] == approval_ref:
                return {"closed": True, "already": True, "note": "already closed", "path": str(entry)}
    return None


def cmd_close(root, data: dict, approval_ref: str) -> dict:
    notes = notes_dir(root, data)
    is_open, _why = _is_run(notes)
    if not is_open:
        answer = _already_closed(notes, data, approval_ref)
        if answer is not None:
            return answer
        raise NotesError(f"no onboarding run is open at {notes}, and none was closed under approval {approval_ref!r}: "
                         "there is nothing to close. `onboarding_notes.py --root . status` shows what is there")
    notes, run = _require_run(root, data)
    progress = dict(run["progress"])
    if not progress["approval_ref"] or progress["approval_ref"] != approval_ref:
        raise NotesError(f"--approval-ref {approval_ref!r} is not the approval this run is frozen under "
                         f"({progress['approval_ref'] or 'none yet'}): close with the ref phase 3 recorded, or run "
                         "`onboarding_notes.py --root . status` to read it")
    # The first reader of the config (OH3-29). After the ref check (a wrong ref starts no probe), and not for a run whose
    # phase is already `done` (a close that died after that write was passed once; the notes must not stay stuck).
    if progress["phase"] != "done":
        import onboarding_first_reader as FR     # inside: the hooks import this module and need none of what the check loads
        found = FR.problems(root)
        if found:
            raise NotesError(FR.refusal(found))     # nothing is written: progress.yaml and the folder stay as they were
    progress["phase"] = "done"
    _save_progress(notes, progress)                # `done` first: a crash leaves a run `close` can finish
    target = _next_free(notes / "done", _sanitise_ref(approval_ref))
    _move_run(notes, target)
    return {"closed": True, "already": False, "path": str(target)}


# --------------------------------------------------------------------------------------- the command line

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="onboarding_notes.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", required=True, help="the project root (the folder that holds, or will hold, qa-factory/)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="report the run; writes nothing; always exit 0")
    p = sub.add_parser("start", help="create the notes folder and open a run at phase 1")
    p.add_argument("--tree", required=True, choices=["clean", "dirty"], help="phase 0's working-tree note")
    p = sub.add_parser("phase", help="move the run to a phase")
    p.add_argument("--set", dest="phase", required=True)
    p.add_argument("--sealed", default=None)
    p.add_argument("--approval-ref", dest="approval_ref", default=None)
    p = sub.add_parser("ask", help="record a batch of questions before it is sent")
    p.add_argument("--batch", required=True)
    p.add_argument("--questions-file", dest="questions_file", required=True)
    p = sub.add_parser("answer", help="record the person's reply to a batch")
    p.add_argument("--batch", required=True)
    p.add_argument("--words-file", dest="words_file", required=True)
    p.add_argument("--answered", required=True)
    p.add_argument("--not-answered", dest="not_answered", default=None)
    sub.add_parser("set-aside", help="move the run to retired/, never deleting it")
    p = sub.add_parser("close", help="move the finished run to done/<approval ref>/")
    p.add_argument("--approval-ref", dest="approval_ref", required=True)
    return parser


def main(argv=None) -> int:
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    args = build_parser().parse_args(argv)
    try:
        try:
            data, data_problem = load_data(), None
        except NotesError as exc:
            if args.command == "status":
                data, data_problem = None, str(exc)
            else:
                raise
        if args.command == "status":
            try:
                result = status_document(args.root, data, data_problem)
            except Exception as exc:        # a report, never a halt: status always exits 0
                result = status_document(args.root, None, f"status could not complete ({type(exc).__name__}: {exc})")
        elif args.command == "start":
            result = cmd_start(args.root, data, args.tree)
        elif args.command == "phase":
            result = cmd_phase(args.root, data, args.phase, args.sealed, args.approval_ref)
        elif args.command == "ask":
            result = cmd_ask(args.root, data, args.batch, args.questions_file)
        elif args.command == "answer":
            result = cmd_answer(args.root, data, args.batch, args.words_file, args.answered, args.not_answered)
        elif args.command == "set-aside":
            result = cmd_set_aside(args.root, data)
        else:
            result = cmd_close(args.root, data, args.approval_ref)
    except NotesError as exc:
        print(f"onboarding_notes.py {args.command}: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
