"""place_answers.py - the places of S7 the analyst settles on the stand, its answer per place, and what happens to a place nobody settled.

    python scripts/place_answers.py list --task-root <story folder> [--json]
    python scripts/place_answers.py write --task-root <story folder> --dispatch <your dispatch id> --place <id> --file <answer.json> [--replace]
    python scripts/place_answers.py close-unsettled --task-root <story folder> --why <one of the gap reasons>

A PLACE is a suspicion the run left unconfirmed, joined from records that already exist: a register row whose `code_says` says
`contradicts`, an investigation target nobody settled, a bug draft whose step is `unconfirmed`, and the analyst's own `new-<slug>`.
The ANALYST answers each place with what it found out on the stand: `bug`, `not_a_bug`, `requirement_silent` (a question for the person
who decides, never a bug) or `impossible` (with why), quoting a capture the factory's recorder wrote and naming where its expectation
comes from (`requirement`, `question`, `person`, `none`; never `none` for a bug). Code assembles the places, checks the KEYS and
CROSS-REFERENCES of an answer, carries it to the findings register and the draft's step, and turns every place nobody settled into a
named gap. Code never decides whether an answer is TRUE (AR-29, FR-47, FR-58): the scribe, a tier above, accepts the analyst's meaning.

The answer is a record `evidence/place-answer-*.json` (one per place, `<id>` in the name) written ONLY here (code sets `writer`, `written_at`, `dispatch`, `replaces`).
The register line is written only through `exploratory_findings.append`. Nothing else is written.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract as C
import hooklib
import install_paths
from investigation import _s                          # the one `_s` (F16): text of a value, "" for None
from manual_evidence import _squash as _squash_text   # the one whitespace squash (F16)
from role_cli import RefusingParser, epilog, run_guarded

SCRIPT = "place_answers.py"
SUBCOMMANDS = ("list", "write", "close-unsettled")
DATA_PATH = hooklib.PLUGIN_ROOT / "references" / "place-answers.json"
REGISTER_NAME = "requirements-register.md"
WORDS_DIR = ("state", "words")


# --- small helpers ----------------------------------------------------------------------------------------------------

def _data() -> dict:
    """`references/place-answers.json` - the closed lists and texts; `{}` when it cannot be read (a caller then says so)."""
    return hooklib.read_json(DATA_PATH, {}, kind=dict)


def _read_object(path: Path) -> tuple:
    """`(object, "")` or `(None, why)`: the file as a JSON object, through the package's one reader `hooklib.read_json` (F16, AR-13).
    Absent, unreadable, not JSON or not an object are one "nothing there" for that reader, so `why` is one why-less text."""
    value = hooklib.read_json(path, None, kind=dict)
    return (value, "") if value is not None else (None, "not readable as a JSON object")


def _squash(text) -> str:
    """`_squash_text` of the text of `text` (None -> "")."""
    return _squash_text(_s(text))


def _p(what: str, door: str) -> str:
    """One refusal line: what is wrong and the door the analyst can use (FR-1, FR-2, FR-57)."""
    return f"{what}. Door: {door}"


def _refuse(problems) -> None:
    """The ONE raise of this module: every refusal of `write` and `close-unsettled` goes through here, one line per problem."""
    lines = [str(item) for item in (problems if isinstance(problems, (list, tuple)) else [problems]) if str(item).strip()]
    raise ValueError("; ".join(lines) if lines else "refused")


def record_rel(place: str) -> str:
    """The task-relative path of the record of `place` (`evidence/place-answer-<id>.json`; characters a file name cannot hold -> `_`)."""
    return f"{_data().get('record_root', 'evidence/place-answer-')}{re.sub(r'[^A-Za-z0-9._-]', '_', _s(place))}.json"


def _read_record(task: Path, place: str):
    """`(record, "")`, `(None, "")` when there is none, `(None, why)` when the file exists and cannot be used."""
    path = task / record_rel(place)
    if not path.is_file():
        return None, ""
    record, _why = _read_object(path)
    if record is None:
        return None, "the answer record cannot be read as a JSON object"
    if record.get("place") != place:
        return None, "the answer record names another place"
    return record, ""


def _records(task: Path) -> tuple:
    """`([(place id, record)], [(record path, why)])` of the answer records - the places that have an answer, whatever lists them now, and
    the record files that cannot be read or name no place (an unknown, never "no place": AR-28)."""
    base = Path(_data().get("record_root", "evidence/place-answer-"))
    root = task / base.parent
    out, bad = [], []
    for path in sorted(root.glob(base.name + "*.json")) if root.is_dir() else []:
        rel = path.relative_to(task).as_posix()
        record, _why = _read_object(path)
        if record is None:
            bad.append((rel, "the answer record cannot be read as a JSON object"))
            continue
        if isinstance(record.get("place"), str) and re.fullmatch(_data().get("place_id_pattern", "$^"), record["place"]):
            out.append((record["place"], record))
        else:
            bad.append((rel, "the answer record names no place"))
    return out, bad


def _register(task: Path):
    """`(rows, text, why)` of the requirements register: `([], "", "")` when the story has none; `why` when it cannot be read."""
    try:
        path = C.artifact(task, REGISTER_NAME)
        if not path.is_file():
            return [], "", ""
        text = C.read_text(path)
        return C.register_rows(text), text, ""
    except (ValueError, OSError) as exc:
        return [], "", f"{type(exc).__name__}: {exc}"


def _questions(task: Path):
    """{id: question row} of the question register, or None when it cannot be read (the safe direction: nothing is confirmed)."""
    try:
        import question_register as QR
        return {q["id"]: q for q in QR.load(task).get("questions", []) if isinstance(q, dict) and "id" in q}
    except Exception:                                  # noqa: BLE001 - an unreadable register confirms nothing
        return None


def _dispatches(task: Path):
    """`({id: dispatch record}, why)` from the controller state; `({}, "")` for a story with no event journal."""
    if not (task / "state" / "events.jsonl").is_file():
        return {}, ""
    try:
        from controller import Controller
        state = Controller(task).state()
    except Exception as exc:                           # noqa: BLE001
        return {}, f"{type(exc).__name__}: {exc}"
    found = state.get("dispatches") if isinstance(state, dict) else None
    return (found if isinstance(found, dict) else {}), ""


def person_words_of(task, dispatch) -> tuple:
    """`(info, why)`: the ONE public reader of a dispatch record that carries the person's own words (t-2187 M1; the `person` source of a
    place answer and the `person` basis of a merge both read it). `info` is `{"stage", "words", "scope"}` - the stage of the dispatch,
    the ORIGINAL reason (read from `request_binding`, which nothing rewrites) and the cases the request was made for (binding, else
    the record) - when the record exists and is marked `person_words` (`Controller.build_rework_request` sets the mark only for a reason
    read from the words file; the mark is read from the record or from its binding). `info` is None otherwise, and `why` says which:
    "unreadable" (the controller state could not be read), "no_record" (no such dispatch) or "no_mark". Reads only (FR-45)."""
    dispatches, problem = _dispatches(Path(task))
    if problem:
        return None, "unreadable"
    record = dispatches.get(_s(dispatch))
    if not isinstance(record, dict):
        return None, "no_record"
    from controller import Controller
    binding = Controller._original_request(record)
    if not (record.get("person_words") is True or binding.get("person_words") is True):
        return None, "no_mark"
    scope = binding.get("scope") if isinstance(binding.get("scope"), list) else record.get("scope")
    return {"stage": _s(record.get("stage")), "words": _s(binding.get("reason")),
            "scope": [str(c) for c in scope] if isinstance(scope, list) else []}, ""


def _draft_json(path: Path):
    """`(draft, "")` or `(None, why)`: a draft file that is not a JSON object is a record we could not read, never skipped."""
    return _read_object(path)


# --- which place a draft belongs to (ONE reading) ---------------------------------------------------------------------------

def place_of_draft(task, name, draft, rows=None, targets=None) -> str:
    """The id of the place a draft belongs to. Pure; the ONE reading of "which place a draft belongs to" (U2 reads it too).
    (1) a code-reading draft -> `req-<R>` of its first `violates` R; (2) a triage-road draft whose `case` is the `case` of an
    investigation target (ALL targets, so a resolution never moves a draft) -> that target's id; (3) a triage-road draft whose
    `violates` names an R whose register row `code_says` contradicts -> `req-<R>` of the first such R; (4) `draft-<file stem>`.
    `rows` (the register rows) and `targets` (all investigation targets) are read when None; what cannot be read is empty.
    A target with no pinned `case` is joined to no draft: the contract gives a draft no field for it yet."""
    import bug_records as BR
    task = Path(task)
    draft = draft if isinstance(draft, dict) else {}
    named = C.REQ_ID_RE.findall(_s(draft.get("violates")))
    if BR.is_code_reading(draft) and named:
        return f"req-{named[0]}"
    if targets is None:
        try:
            import investigation as INV
            targets = INV.investigation_targets(task)["targets"]
        except Exception:                              # noqa: BLE001 - unreadable targets join nothing
            targets = []
    case = _s(draft.get("case")).strip()
    if case:
        for target in targets:
            if _s(target.get("case")).strip() == case:        # `case` is a case id by the draft contract; it is never read as a target id
                return _s(target.get("id"))
    if rows is None:
        rows = _register(task)[0]
    import branch_accounting as BA
    contradicting = {row["r"] for row in rows if BA.code_says_contradicts(row)}
    for rid in named:
        if rid in contradicting:
            return f"req-{rid}"
    return f"draft-{Path(_s(name)).stem}"


# --- the places - ONE join, data only ---------------------------------------------------------------------------------------

def _confirmation(task, draft, rows=None, report=None) -> tuple:
    """`bug_records.confirmation_of` read as a DRAFT: a draft with no `confirmation` word is `unconfirmed` (`draft=True`, the one
    reading every reader of a draft's step shares - AR-13, AR-28). The contract default for FILED bugs is not touched."""
    import bug_records as BR
    return BR.confirmation_of(task, draft, rows, report, draft=True)


def _hint(*texts) -> str:
    return ", ".join(dict.fromkeys(rid for text in texts for rid in C.REQ_ID_RE.findall(_s(text))))


def _add_place(found: dict, pid, source, title, refs, hint) -> None:
    """Join one source of a place into `found`: one place appears once, every source and ref joined into it."""
    place = found.setdefault(pid, {"id": pid, "sources": [], "refs": {}, "title": title or pid, "expectation_hint": hint})
    if source not in place["sources"]:
        place["sources"].append(source)
    for key, value in refs.items():
        if isinstance(value, list):
            place["refs"].setdefault(key, [])
            place["refs"][key] += [item for item in value if item not in place["refs"][key]]
        elif value not in (None, "", []):
            place["refs"].setdefault(key, value)
    if not place["expectation_hint"] and hint:
        place["expectation_hint"] = hint


def _register_places(rows: list, add) -> None:
    """Source `register`: a row whose `code_says` contradicts."""
    import branch_accounting as BA
    for row in rows:
        if BA.code_says_contradicts(row):
            add(f"req-{row['r']}", "register", f"{row['r']}: {_squash(row.get('requirement'))}"[:150],
                {"requirement": _s(row.get("requirement")), "code_says": _s(row.get("code_says"))}, row["r"])


def _target_places(task: Path, add, unreadable: list) -> list:
    """Source `open`: an investigation target nobody resolved, or one the analyst settled. Returns ALL targets (the draft join needs them)."""
    targets: list = []
    try:
        import investigation as INV
        budget, problems = INV.load_budget()
        if problems:
            unreadable.append(("references/investigation-budget.json", "; ".join(problems)))
        got = INV.investigation_targets(task)
        targets = got["targets"]
        unreadable += [(record, reason) for record, reason in got["unreadable"]]
        opened = INV.open_targets(task, budget)
        for target in list(opened["unresolved"]) + list(opened.get("settled", [])):
            add(target["id"], "open", _s(target.get("then")).strip() or target["id"],
                {"then": target.get("then"), "observed": target.get("observed"), "evidence": list(target.get("evidence") or []),
                 "case": target.get("case")}, ", ".join(target.get("requirements") or []))
    except Exception as exc:                           # noqa: BLE001 - the targets could not be computed whole
        unreadable.append(("the investigation's targets", f"{type(exc).__name__}: {exc}"))
    return targets


def _draft_places(task: Path, rows: list, targets: list, add, unreadable: list) -> None:
    """Source `draft`: a draft whose step is `unconfirmed` (a draft with no `confirmation` word included, `_confirmation`)."""
    import bug_records as BR
    paths, unlistable = BR.draft_listing(task)
    unreadable += [(item.split(":")[0], item) for item in unlistable]
    triage_rows, report = BR.step_facts(task)
    for path in paths:
        rel = path.relative_to(task).as_posix() if path.is_relative_to(task) else path.name
        draft, why = _draft_json(path)
        if draft is None:
            unreadable.append((rel, why))
            continue
        try:
            if _confirmation(task, draft, triage_rows, report)[0] != "unconfirmed":
                continue
        except Exception as exc:                       # noqa: BLE001
            unreadable.append((rel, f"{type(exc).__name__}: {exc}"))
            continue
        add(place_of_draft(task, path.name, draft, rows, targets), "draft", _s(draft.get("title")).strip() or path.stem,
            {"draft": [path.name], "draft_paths": [rel], "triage_ref": draft.get("triage_ref"), "violates": draft.get("violates"),
             "manual_steps": draft.get("manual_steps"), "red_test": draft.get("red_test"), "fact": draft.get("fact")},
            _hint(draft.get("violates")))


def places(task_root) -> dict:
    """`{"places": [place], "unreadable": [(record, why)]}` - the suspicious UNCONFIRMED places of the run, writes nothing.
    A place is `{id, sources, refs, title, expectation_hint}`: sources `register` (a row whose `code_says` contradicts), `open` (an
    investigation target nobody resolved, or one the analyst settled), `draft` (a draft whose step is `unconfirmed`), `new` / `record`
    (a place that has an answer and no other source now). One place appears once, with every source joined into it. A source that
    cannot be read is `unreadable`, never "no place" (AR-28); an empty list with nothing unreadable is the only "none"."""
    task = Path(task_root)
    found: dict = {}
    unreadable: list = []

    def add(pid, source, title, refs, hint):
        _add_place(found, pid, source, title, refs, hint)

    rows, _text, why = _register(task)
    if why:
        unreadable.append((f"work/{REGISTER_NAME}", why))
    _register_places(rows, add)
    targets = _target_places(task, add, unreadable)
    _draft_places(task, rows, targets, add, unreadable)
    new_prefix = _data().get("new_prefix", "new-")
    answered, broken = _records(task)
    unreadable += broken
    for pid, _record in answered:
        if pid not in found:
            add(pid, "new" if pid.startswith(new_prefix) else "record", pid, {}, "")
    return {"places": list(found.values()), "unreadable": unreadable}


# --- the answer: keys and cross-references, never truth ---------------------------------------------------------------------

def _capture_list(task: Path, place: str, seen: dict, required: bool) -> list:
    """The capture rules (INVARIANT: a receipt measured on other bytes never counts). `[]` when the capture stands."""
    capture = _s(seen.get("capture")).strip().replace("\\", "/")
    prefix = _data().get("capture_case_prefix", "settle-")
    command = f"manual_capture.py ui|http --task-root <T> --case {prefix}{place}"
    if not capture:
        return [_p("`seen.capture` is missing", f"capture the place first with `{command}` and name the capture's path")] if required else []
    return capture_stands(task, prefix + place, capture, seen.get("quote"))


def capture_stands(task: Path, case: str, capture, quote, field: str = "seen") -> list:
    """Does `capture` stand as evidence of the recorder's case `case`? ONE reader (AR-13): `_capture_list` (an analyst's answer
    per place, case `settle-<place>`) and `bug_records.mechanism_problems` / `manifestation_problems` (a `run` basis and a `probe`,
    which decide whether a MERGE stands) both call it. `[]` when it stands; otherwise one line per problem, each with its door.
    It stands only when: the path is a row of the capture index (`captures.jsonl`) of an attempt of THIS case, the file's bytes
    still hash to the row's `content_hash`, and `quote` is in it (a picture holds no quote). Error direction: DOWN - an empty path,
    a case that cannot name a capture root, an index that is not JSONL, a path with `..` or an absolute one, an empty quote are
    all "does not stand", never a pass. `field` is the key's prefix in the text (`seen` -> `seen.capture`)."""
    import manual_capture as MC
    import manual_evidence as ME
    capture = _s(capture).strip().replace("\\", "/")
    place = _s(case)
    command = f"manual_capture.py ui|http --task-root <T> --case {place}"
    if not capture:
        return [_p(f"`{field}.capture` is missing", f"capture first with `{command}` and name the capture's path")]
    try:
        root = MC.case_root(task, place)
    except ValueError as exc:
        return [_p(f"the place id cannot name a capture case ({exc})", "use an id from `place_answers.py list`")]
    shown = root.relative_to(Path(task).resolve()).as_posix()
    attempts = MC.attempts_of(root)
    if not attempts:
        return [_p(f"no capture of this place exists yet ({shown} has no attempt)", f"capture first: `{command}`")]
    row = None
    for attempt in attempts:
        try:
            rows = ME._jsonl(root / attempt / "captures.jsonl")
        except ValueError as exc:
            return [_p(str(exc), f"capture again: `{command}`")]
        row = next((r for r in rows if isinstance(r, dict) and _s(r.get("path")).replace("\\", "/") == capture), None)
        if row is not None:
            break
    if row is None:
        return [_p(f"`{field}.capture` {capture} is not in the capture index of this place ({shown}, attempts {', '.join(attempts)})",
                   f"name a capture the recorder wrote for THIS place, or capture it: `{command}`")]
    try:
        stored = ME._safe_evidence_path(task, capture)
        unchanged = install_paths.sha256_file(stored) == _s(row.get("content_hash"))
    except (ValueError, OSError) as exc:
        return [_p(f"`{field}.capture` {capture} cannot be read ({exc})", f"capture again: `{command}`")]
    if not unchanged:
        return [_p(f"{capture} changed after the recorder hashed it", f"capture again in a new attempt: `{command}`")]
    if not ME._quote_in(task, {"path": capture}, quote):
        return [_p(f"`{field}.quote` is not in {capture}", "quote words the capture holds, as written (a picture holds no quote: cite a text capture)")]
    return []


def _requirement_list(task: Path, expectation: dict, answer: str) -> list:
    rid, quote = _s(expectation.get("id")).strip(), _s(expectation.get("quote"))
    rows, text, why = _register(task)
    if why:
        return [_p(f"the register cannot be read: {why}", "answer with `question`, `person`, `requirement_silent` or `impossible`")]
    row = next((r for r in rows if r["r"] == rid), None)
    if row is None:
        return [_p(f"{rid!r} is not in the register", "cite an R of work/requirements-register.md exactly as written, or use another source")]
    if not quote.strip() or _squash(quote) not in _squash(row.get("requirement")):
        return [_p(f"`expectation.quote` is not in the text of {rid}", "quote the requirement as the register has it")]
    if answer == "bug" and rid in C.unconfirmed_requirements(text, _questions(task)):
        return [_p(f"{rid} has no confirmed source (derived from code or a test)",
                   "that requirement has no confirmed source: answer `requirement_silent` with your question, or cite the person's "
                   "words (`person`) or their settled question (`question`)")]
    return []


def _question_list(task: Path, expectation: dict) -> list:
    qid = _s(expectation.get("id")).strip()
    if not qid:
        return [_p("`expectation.id` is empty for source `question`", "name the question id, or use another source")]
    import bug_records as BR
    return [_p(detail, "cite a question the person answered, with their words; or answer `requirement_silent` with your own question")
            for _code, detail in BR._oracle_problems(task, {"oracle": {"question": qid, "quote": expectation.get("quote")}}, "",
                                                     _questions(task), None)]


def _person_list(task: Path, expectation: dict, dispatch) -> list:
    door = "this dispatch carries no person's words; cite `requirement`, `question`, or answer `requirement_silent`"
    if not _s(dispatch).strip():
        return [_p("source `person` needs the dispatch you run as", "pass `--dispatch <your dispatch id>`")]
    raw = _s(expectation.get("id")).strip().replace("\\", "/")
    words_root = (task.resolve() / Path(*WORDS_DIR))
    path = None
    if raw:                                  # t-2027 F3: no brief carries the words file's path, so `id` may be empty; a path that is given stays checked
        try:
            path = (task.resolve() / raw).resolve()
            inside = not Path(raw).is_absolute() and path.is_relative_to(words_root) and path.is_file()
        except (OSError, ValueError):
            inside = False
        if not inside:
            return [_p(f"`expectation.id` {raw!r} is no file under {'/'.join(WORDS_DIR)}/", "name the person's words file as the brief gives it, or leave `id` empty; " + door)]
    info, why = person_words_of(task, dispatch)
    if why == "unreadable":
        return [_p("where the story stands could not be read", "report it as a factory defect; cite `requirement` or answer `requirement_silent`")]
    if info is None:
        return [_p(f"dispatch {_s(dispatch)} carries no person_words mark", door)]
    if path is None:                                   # no path: the words are the dispatch's own reason, which the person_words mark vouches for
        words = info["words"]
        if not words.strip():
            return [_p(f"dispatch {_s(dispatch)} carries no person's words (its reason is empty)", door)]
    else:
        import person_words
        try:
            words = person_words.read(None, str(path), "--words")
        except Exception as exc:                       # noqa: BLE001 - WordsRefused and the like
            return [_p(f"the words file cannot be read ({type(exc).__name__})", door)]
        if info["words"] != words:
            return [_p(f"{raw} is not the reason this dispatch was given", door)]
    if not _squash(expectation.get("quote")) or _squash(expectation.get("quote")) not in _squash(words):
        return [_p("`expectation.quote` is not in the person's words", "quote their words as they were given")]
    return []


def _absorbs_place_draft(task: Path, place: str, name: str) -> bool:
    """True when the draft file `name` holds a manifestation whose `from_draft` is the draft the place's recorded answer names. Reads
    the place's record and the live drafts only; no record, no draft in it, or no absorber named `name` -> False (the old refusal)."""
    record, _why = _read_record(task, place)
    recorded = _s(record.get("draft")).strip() if isinstance(record, dict) else ""
    return bool(recorded) and any(found == name for found, _draft, _entry in _absorbers(task, recorded))


def _bug_list(task: Path, record: dict, place: str) -> list:
    name = _s(record.get("draft")).strip()
    if not name:
        return [_p("a `bug` answer needs `draft`, the file name of the draft that carries it",
                   "write the draft under work/bug-drafts/ with a `walk` reproduction entry, then name its file")]
    import bug_records as BR
    paths, _unlistable = BR.draft_listing(task)
    path = next((p for p in paths if p.name == name), None)
    if path is None:
        return [_p(f"`draft` {name!r} is no draft file of the story", "name a file of work/bug-drafts/ as it is spelled")]
    draft, why = _draft_json(path)
    if draft is None:
        return [_p(f"the draft {name} cannot be read ({why})", "repair the draft file")]
    owner = place_of_draft(task, name, draft)
    if owner != place and _absorbs_place_draft(task, place, name):
        return []                                      # a merged draft that absorbed the place's own recorded draft carries the place (m8, FR-57)
    if owner != place:
        return [_p(f"the draft {name} belongs to place {owner}, not {place}", "answer that place with this draft, or name the draft of this place")]
    return []


def _answer_lines(task: Path, record, dispatch) -> list:
    data = _data()
    if not data:
        return [_p("the answer vocabulary (references/place-answers.json) cannot be read", "report it as a factory defect and answer `impossible` with that why")]
    keys = "see `place_answers.py write --help` for the keys of an answer"
    if not isinstance(record, dict):
        return [_p("the answer is not a JSON object", keys)]
    out: list = []
    place, answer = record.get("place"), record.get("answer")
    expectation = record.get("expectation") if isinstance(record.get("expectation"), dict) else {}
    seen = record.get("seen") if isinstance(record.get("seen"), dict) else {}
    place_ok = isinstance(place, str) and re.fullmatch(data["place_id_pattern"], place) is not None
    if not place_ok:
        out.append(_p(f"`place` is {place!r}, not a place id", "copy an id from `place_answers.py list`, or use `new-<slug>` (a-z 0-9 -, at most 40) for your own suspicion"))
    if answer not in data["answers"]:
        out.append(_p(f"`answer` is {answer!r}", "one of " + ", ".join(data["answers"])))
        return out
    source = expectation.get("source")
    if source not in data["sources"]:
        out.append(_p(f"`expectation.source` is {source!r}", "one of " + ", ".join(data["sources"]) + "; `none` when no requirement, question or person decides it"))
        return out
    if source == "none":
        if answer not in data["none_allowed"]:
            out.append(_p("a bug needs the requirement it breaks, a settled question or the person's words",
                          "with none, answer `requirement_silent` with your question"))
    elif source == "requirement":
        out += _requirement_list(task, expectation, answer)
    elif source == "question":
        out += _question_list(task, expectation)
    else:
        out += _person_list(task, expectation, dispatch)
    if answer == "requirement_silent" and not _s(record.get("question")).strip():
        out.append(_p("`question` is empty", "write the question for the person who decides, in plain words"))
    if answer == "impossible" and not _s(record.get("why")).strip():
        out.append(_p("`why` is empty", "say what the stand lacks"))
    if answer == "not_a_bug":
        if not _s(record.get("why")).strip():
            out.append(_p("`why` is empty", "say why it is not a bug, in your words"))
        if not _s(seen.get("quote")).strip():
            out.append(_p("`seen.quote` is empty", "quote the words the stand showed"))
    if place_ok and (answer in data["capture_required"] or _s(seen.get("capture")).strip()):
        out += _capture_list(task, place, seen, answer in data["capture_required"])
    if answer == "bug" and place_ok:
        out += _bug_list(task, record, place)
    if _s(dispatch).strip():
        dispatches, why = _dispatches(task)
        if dispatches and not why and _s(dispatch) not in dispatches:      # a state that reads and knows dispatches names the real one
            out.append(_p(f"{_s(dispatch)!r} is not a dispatch of this story", "pass `--dispatch` with the id you run as, as the brief gives it"))
        import controller
        if controller.s7_part_of(dispatches.get(_s(dispatch))) == "investigation":
            out.append(_p("an investigation dispatch cannot answer a place", "an investigation records through `investigation_probe.py record`; the places are the triage's"))
    return out


def answer_problems(task, record, *, dispatch=None) -> list:
    """`[one refusal line per problem]` of an answer record - keys, membership, joins and quoted bytes only; `[]` when it stands.
    Pure, never raises (a check that could not run reads as a problem, AR-28), reads no place list. Every line names its door.
    It never reads what the words MEAN (AR-29): the analyst's judgment is accepted by the scribe. `dispatch` is the id the answer
    is given as (the `person` source and the investigation refusal need it)."""
    try:
        return _answer_lines(Path(task), record, dispatch)
    except Exception as exc:                           # noqa: BLE001
        return [_p(f"the answer could not be checked ({type(exc).__name__}: {exc})", "report it as a factory defect and answer `impossible` with that why")]


# --- settled / unsettled ----------------------------------------------------------------------------------------------------

def _chain_of(task: Path, place: str):
    """(writer module or None, the chain of `place`)."""
    import investigation as INV
    writer = INV._writer()
    if writer is None:
        return None, []
    return writer, writer.chains_of(writer.read(task)["lines"]).get(place, [])


KIND_OF = {"requirement_silent": "unresolved_question", "not_a_bug": "observation", "impossible": "coverage_gap"}


def _absorbers(task: Path, name: str) -> list:
    """`[(draft file name, draft, manifestation)]` of the LIVE drafts one of whose manifestations names `name` in `from_draft` - the
    drafts that absorbed the draft file `name` (row 5.10). Only a listed, readable draft counts; a draft that does not name `name`
    never appears, so a place is never settled by a draft that does not carry it. [] for an empty name."""
    if not name:
        return []
    import bug_records as BR
    out = []
    for path in BR.draft_listing(task)[0]:
        if path.name == name:
            continue
        draft, _why = _draft_json(path)
        for entry in BR.manifestation_entries(draft):
            if _s(entry.get("from_draft")).strip() == name:
                out.append((path.name, draft, entry))
                break
    return out


def _cites_record(draft: dict, record_path: str) -> bool:
    """Does the draft carry a `walk` entry whose `evidence` is the place's record (`record_rel`)? Presence only (AR-29)."""
    entries = draft.get("reproduction") if isinstance(draft, dict) else None
    return isinstance(entries, list) and any(
        isinstance(e, dict) and _s(e.get("kind")).strip() == "walk"
        and _s(e.get("evidence")).strip().replace("\\", "/") == record_path for e in entries)


def _unconfirmed_sibling(task: Path, record: dict, skip: set, data: dict, named: str) -> str:
    """The refusal line of a `bug` answer whose place still has a draft standing `unconfirmed` besides the drafts in `skip` (already
    judged); "" when every other draft of the place has a step. A place is settled only when no draft of it stays unconfirmed (F13:
    one answer raises every draft that carries the receipt, never hides one that does not). Joins and presence only (AR-29). A draft
    file that cannot be read has no place to join: `places` lists it as unreadable.

    The line names the sibling's OWN reasons (`_confirmation`'s closed words, as `no_draft_carries` does) and only doors that exist
    (FR-1, FR-2): a sibling with no `walk` entry citing the record -> add one; one that has it and still fails -> clear its reasons;
    always -> merge it into `named` (the draft that carries the answer; the `from_draft` road) or leave it, and the close names the
    place as a gap. A sibling with no `confirmation` word gets that reason and the `no_confirmation` door instead of the walk or
    reasons door (`confirmation_of(draft=True)` returns early for it, so a walk entry alone would not lift it). The sibling's place IS this place, so "answer its own place" is no door. No reasons -> no parenthesis."""
    import bug_records as BR
    place, rows = _s(record.get("place")), _register(task)[0]
    texts, rel = data["line_texts"], record_rel(place)
    for path in BR.draft_listing(task)[0]:
        draft, _why = _draft_json(path)
        if draft is None or path.name in skip or place_of_draft(task, path.name, draft, rows) != place:
            continue
        word, _kinds, reasons = _confirmation(task, draft)
        if word != "unconfirmed":
            continue
        reasons = [_s(r).strip() for r in reasons or [] if _s(r).strip()]
        if not _s(draft.get("confirmation")).strip():     # `draft=True` returns early with no reason: a walk entry would not lift it
            reasons, doors = [texts["sibling_no_word_reason"]], [texts["no_confirmation"]]
        elif not _cites_record(draft, rel):
            doors = [texts["sibling_door_no_walk"].format(record=rel)]
        else:
            doors = [texts["sibling_door_reasons"]] if reasons else []
        doors += [texts["sibling_door_merge"].format(named=named), texts["sibling_door_leave"]]
        return texts["sibling_unconfirmed"].format(draft=path.name, reasons=f" ({'; '.join(reasons)})" if reasons else "",
                                                   doors=", ".join(doors))
    return ""


def _settled_through(task: Path, record: dict, claimants: list, data: dict) -> tuple:
    """`settled_answer`'s `bug` verdict for a draft that was absorbed. Two merged drafts naming one `from_draft` is never settled
    (row 5.10 is silent on it: the same state as today, `carrier missing`). One merged draft settles the place when its own step
    holds (`confirmation_of` -> `reproduced_by_factory` with a `walk` receipt) OR the manifestation's `evidence` is the answer's own
    `seen.capture`; otherwise as today."""
    import bug_records as BR
    missing = data["line_texts"]["no_draft_carries"]
    if len(claimants) > 1:
        return record, "carrier missing", missing + f" (more than one draft absorbed it: {', '.join(n for n, _d, _e in claimants)})"
    name, merged, entry = claimants[0]
    seen = record.get("seen") if isinstance(record.get("seen"), dict) else {}
    capture = _s(seen.get("capture")).strip().replace("\\", "/")
    skip = {name, _s(record.get("draft")).strip()}
    if capture and _s(entry.get("evidence")).strip().replace("\\", "/") == capture:
        sibling = _unconfirmed_sibling(task, record, skip, data, name)
        return (record, "carrier missing", sibling) if sibling else (record, "settled", "")
    if not _s(merged.get("confirmation")).strip():
        return record, "carrier missing", data["line_texts"]["no_confirmation"]
    word, kinds, reasons = BR.confirmation_of(task, merged)
    if word == BR.REPRODUCED and "walk" in kinds:
        sibling = _unconfirmed_sibling(task, record, skip, data, name)
        return (record, "carrier missing", sibling) if sibling else (record, "settled", "")
    return record, "carrier missing", missing + (f" ({'; '.join(reasons)})" if reasons else "")


def settled_answer(task_root, place) -> tuple:
    """`(record or None, state, why)` - the ONE predicate "this place is settled" (AR-13). States: `settled` (a record that stands AND
    its carrier exists: an active register line recorded by the answering dispatch, or for `bug` a draft whose step is
    `reproduced_by_factory` with a `walk` receipt); `carrier missing`; `conflict` (a valid `not_a_bug` / `requirement_silent` while a
    joined draft still stands `unconfirmed`); `invalid` (the record no longer stands); `open` (no record). Code never settles a place
    by the analyst's word alone: presence of a record settles nothing."""
    task = Path(task_root)
    data = _data()
    record, why = _read_record(task, place)
    if record is None:
        return (None, "invalid", why) if why else (None, "open", "")
    problems = answer_problems(task, record, dispatch=record.get("dispatch"))
    answer = record["answer"]
    import bug_records as BR
    claimants: list = []
    if answer == "bug" and problems:                           # an absorbed draft is no file now: `_bug_list` refuses it, the merged draft carries it
        named = _s(record.get("draft")).strip()
        if not any(p.name == named for p in BR.draft_listing(task)[0]):      # only a file that is gone; a listed draft keeps today's checks
            claimants = _absorbers(task, named)
        if claimants:
            gone = _bug_list(task, record, _s(record.get("place")))
            problems = [line for line in problems if line not in gone]
    if problems:
        return record, "invalid", problems[0]
    if answer == "bug":
        paths, _bad = BR.draft_listing(task)
        path = next((p for p in paths if p.name == _s(record.get("draft")).strip()), None)
        draft, _why = _draft_json(path) if path is not None else (None, "")
        if path is None and claimants:
            return _settled_through(task, record, claimants, data)
        if draft is None:
            return record, "carrier missing", data["line_texts"]["no_draft_carries"]
        if not _s(draft.get("confirmation")).strip():          # the contract reads that as the person's word: no receipt check would run
            return record, "carrier missing", data["line_texts"]["no_confirmation"]
        word, kinds, reasons = BR.confirmation_of(task, draft)
        if word == BR.REPRODUCED and "walk" in kinds:
            named = _s(record.get("draft")).strip()
            sibling = _unconfirmed_sibling(task, record, {named}, data, named)
            return (record, "carrier missing", sibling) if sibling else (record, "settled", "")
        return record, "carrier missing", data["line_texts"]["no_draft_carries"] + (f" ({'; '.join(reasons)})" if reasons else "")
    if answer in ("not_a_bug", "requirement_silent"):          # BEFORE the line check: the gap line the close writes must not flip the state
        rows = _register(task)[0]
        for path in BR.draft_listing(task)[0]:
            draft, _why = _draft_json(path)
            if (draft is not None and place_of_draft(task, path.name, draft, rows) == place
                    and _confirmation(task, draft)[0] == "unconfirmed"):
                return record, "conflict", f"the draft {path.name} of this place still stands unconfirmed"
    writer, chain = _chain_of(task, place)
    if writer is None:
        return record, "carrier missing", data["line_texts"]["not_installed"]
    active = chain[-1] if chain and chain[-1].get("_status") == "active" else None
    by = _s(active.get("recorded_by")) if active else ""
    if (active is None or active.get("kind") != KIND_OF[answer]
            or not (by == _s(record.get("dispatch")) or by == "person" or by.startswith("person:"))):
        return record, "carrier missing", data["line_texts"]["no_line"]
    return record, "settled", ""


def unsettled(task_root, found=None) -> list:
    """Every place that is not `settled`, as the place dict plus `state`, `why` and `record`. `found` is a `places()` result the caller
    already holds. Code never settles a place by its verdict word."""
    task = Path(task_root)
    found = found if found is not None else places(task)
    out = []
    for place in found["places"]:
        record, state, why = settled_answer(task, place["id"])
        if state != "settled":
            out.append(dict(place, state=state, why=why, record=record))
    return out


# --- closing the places nobody settled --------------------------------------------------------------------------------------

def _summary(place: dict) -> str:
    parts = [f"{key}: {_squash(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))}"
             for key, value in place["refs"].items() if key != "draft_paths" and value not in (None, "", [])]
    return ("; ".join([place["title"]] + parts))[:int(_data().get("gap_summary_max", 300))]


def _foreign(by: str, record, data: dict) -> bool:
    """Is a register line written by someone whose line the close must not rewrite: not the close itself, not code (the investigation's
    projection) and not the dispatch that gave the answer? A probe's outcome, a person's line and another dispatch's line are foreign."""
    return not (by == data["by_close"] or by.startswith("code:") or (isinstance(record, dict) and by == _s(record.get("dispatch"))))


def _active_of(chain):
    return chain[-1] if chain and chain[-1].get("_status") == "active" else None


def close_unsettled(task_root, why, printed=None, *, found=None) -> list:
    """[ids of the register lines written] - for each unsettled place, ONE `coverage_gap` line, and for each place settled as a `bug`
    the withdrawal of the line a draft's receipt now makes pointless. The `coverage_gap` goes to a place of source `draft` or `register`
    in any unsettled state and to a place of source `open` only in `conflict` / `carrier missing`: a place that is still `open` or
    `invalid` and has the `open` source keeps the investigation road, with the person's question the investigation put on it.
    A place with no chain gets an `add`, a place with an active line one `correct` that keeps the line's `question`, `owner_role` and
    `oracle_status`, an unchanged text nothing; a line of another owner is never corrected (named in `printed`); a chain the analyst
    withdrew cannot take a line, so the gap goes under `gap_target_prefix` + the place id. `why` is one of the gap reasons, else
    ValueError naming them. Every failure path leaves a line or a named gap in `printed` (AR-28)."""
    data = _data()
    if why not in data["gap_reasons"]:
        _refuse([_p(f"`why` is {why!r}", "one of: " + "; ".join(f"`{text}`" for text in data["gap_reasons"]))])
    printed = printed if printed is not None else []
    task = Path(task_root)
    import investigation as INV
    writer = INV._writer()
    if writer is None:
        printed.append(data["line_texts"]["not_installed"])
        return []
    written = []
    chains = writer.chains_of(writer.read(task)["lines"])
    found = found if found is not None else places(task)
    rows = [(place,) + tuple(settled_answer(task, place["id"])) for place in found["places"]]
    for place, record, state, reason in rows:
        if state != "settled" or not isinstance(record, dict) or record.get("answer") != "bug":
            continue
        active = _active_of(chains.get(place["id"], []))                    # a bug the receipt now carries: a question line is not asked
        if active is None:
            continue
        by = _s(active.get("recorded_by"))
        if _foreign(by, record, data):
            printed.append(f"{place['id']}: its register line {active['id']} was written by {by}; it is not withdrawn")
            continue
        try:
            writer.append(task, {"op": "withdraw", "origin": {"dispatch": data["close_dispatch"], "target": place["id"]},
                                 "withdraws": {"id": active["id"], "reason": data["line_texts"]["withdraw_reason"]}}, by=data["by_close"])
            printed.append(f"{place['id']}: the walk stands; its register line {active['id']} was withdrawn")
        except ValueError as exc:
            printed.append(f"{place['id']}: the line {active['id']} could not be withdrawn: {exc}")
    for place, record, state, reason in rows:
        if state != "settled":
            continue
        gap = _active_of(chains.get(data["gap_target_prefix"] + place["id"], []))      # t-2027 F10: a gap written while the chain was withdrawn is false now
        if gap is None or _s(gap.get("recorded_by")) != data["by_close"]:
            continue
        try:
            writer.append(task, {"op": "withdraw", "origin": {"dispatch": data["close_dispatch"], "target": data["gap_target_prefix"] + place["id"]},
                                 "withdraws": {"id": gap["id"], "reason": data["line_texts"]["withdraw_reason"]}}, by=data["by_close"])
            printed.append(f"{place['id']}: it is settled; its gap line {gap['id']} under {data['gap_target_prefix']}{place['id']} was withdrawn")
        except ValueError as exc:
            printed.append(f"{place['id']}: the gap line {gap['id']} could not be withdrawn: {exc}")
    for place, record, state, reason in rows:
        if state == "settled":
            continue
        if state in ("open", "invalid") and "open" in place["sources"]:
            continue
        key = "open" if state in ("open", "invalid") else state.replace(" ", "_")
        missing = data["state_texts"][key].format(why=why if key == "open" else reason)
        target = place["id"]
        chain = chains.get(target, [])
        if chain and chain[-1].get("_status") != "active":                 # the analyst withdrew it: the gap goes under its own target
            target = data["gap_target_prefix"] + place["id"]
            chain = chains.get(target, [])
            if chain and chain[-1].get("_status") != "active":
                printed.append(f"{place['id']}: its gap line {chain[-1]['id']} was withdrawn; the place stays unsettled ({missing})")
                continue
        active = chain[-1] if chain else None
        if active is not None and active.get("kind") == "coverage_gap" and active.get("missing_prerequisite") == missing:
            continue
        if active is not None and _foreign(_s(active.get("recorded_by")), record, data):
            printed.append(f"{place['id']}: its register line {active['id']} was written by {_s(active.get('recorded_by'))}; "
                           f"the gap is not written over it ({missing})")
            continue
        evidence = (place["refs"].get("draft_paths") or [None])[0]
        if evidence is None and "register" in place["sources"]:
            evidence = Path(C.artifact(task, REGISTER_NAME)).resolve().relative_to(task.resolve()).as_posix()
        evidence = evidence or record_rel(place["id"])
        refs = [rid for rid in place["expectation_hint"].split(", ") if rid] + [c for c in [place["refs"].get("case")] if c]
        line = {"op": "add", "kind": "coverage_gap", "title": place["title"],
                "statement": data["line_texts"]["gap_statement"].format(summary=_summary(place)),
                "missing_prerequisite": missing, "why_not_a_bug": data["line_texts"]["gap_why_not_a_bug"],
                "refs": refs, "evidence_refs": [{"path": evidence}], "probe": None, "verification_status": "unverified",
                "origin": {"dispatch": data["close_dispatch"], "target": target}}
        if active is not None:
            line.update({k: active[k] for k in ("question", "owner_role", "oracle_status") if k in active})     # a question stays asked
            line.update(op="correct", corrects={"id": active["id"], "reason": data["line_texts"]["gap_correct_reason"].format(why=why)})
        if target != place["id"]:
            printed.append(f"{place['id']}: its chain was withdrawn; the gap is written under {target}")
        try:
            written.append(writer.append(task, line, by=data["by_close"]))
        except ValueError as exc:
            printed.append(f"{place['id']}: the gap line was refused: {exc}")
    return written


# --- write ------------------------------------------------------------------------------------------------------------------

def _line_for(task: Path, record: dict, info, dispatch: str, active) -> dict:
    """The register line of a non-bug answer (every field `append` needs)."""
    data = _data()
    answer, place = record["answer"], record["place"]
    seen = record.get("seen") if isinstance(record.get("seen"), dict) else {}
    texts = data["line_texts"]
    refs = [rid for rid in (info["expectation_hint"].split(", ") if info else []) if rid]
    if info and info["refs"].get("case"):
        refs.append(info["refs"]["case"])
    line = {"op": "add", "kind": KIND_OF[answer], "title": (info["title"] if info else place), "statement": _s(seen.get("quote")).strip(),
            "refs": refs, "evidence_refs": [{"path": record_rel(place)}], "probe": None, "verification_status": "unverified",
            "origin": {"dispatch": dispatch, "target": place}}
    if answer == "requirement_silent":
        line.update(why_not_a_bug=texts["requirement_silent_why_not_a_bug"], question=record["question"],
                    owner_role=_owner_words(), oracle_status="owner_question")
    elif answer == "not_a_bug":
        line.update(why_not_a_bug=record["why"])
    else:
        line.update(why_not_a_bug=texts["impossible_why_not_a_bug"], missing_prerequisite=record["why"])
        line["statement"] = line["statement"] or texts["impossible_statement"]
    if active is not None:
        line.update(op="correct", corrects={"id": active["id"], "reason": texts["correct_reason"].format(answer=answer)})
    return line


def _owner_words() -> str:
    import investigation as INV
    return INV.OWNER_WORDS


def write(task_root, dispatch, place, record, replace=False) -> dict:
    """Check the answer, write its record, then its register line. Returns `{"record", "line", "withdrawn", "refusal", "installed"}`.
    Every refusal is raised through `_refuse` BEFORE anything is written. If the register writer refuses AFTER the record is written,
    the record is KEPT and `refusal` carries the writer's words whole - the place then reads `carrier missing`."""
    task = Path(task_root)
    data = _data()
    dispatch = _s(dispatch).strip()
    if not dispatch:
        _refuse([_p("`--dispatch` is missing", "pass the dispatch id you run as")])
    if not isinstance(record, dict) or record.get("place") != place:
        _refuse([_p(f"the answer's `place` is {record.get('place') if isinstance(record, dict) else None!r}, not {place!r}",
                    "write the same id in the file and in `--place`")])
    problems = answer_problems(task, record, dispatch=dispatch)
    if problems:
        _refuse(problems)
    listed = places(task)["places"]
    known = {item["id"] for item in listed}
    if place not in known and not place.startswith(data["new_prefix"]):
        _refuse([_p(f"{place!r} is not a place of this run", "run `place_answers.py list` and copy an id; `new-<slug>` records your own suspicion")])
    path = task / record_rel(place)
    old = install_paths.sha256_file(path) if path.is_file() else ""
    if old and not replace:
        _refuse([_p(f"place {place} already has an answer", "write again with `--replace` if you changed your mind")])
    writer, chain = _chain_of(task, place)
    active = chain[-1] if chain and chain[-1].get("_status") == "active" else None
    if record["answer"] != "bug" and chain and active is None:
        _refuse([_p("this place's line was withdrawn when you answered bug; the register keeps one chain per target",
                    "answer `bug`, or record the question under a new place `new-<slug>`")])
    info = next((item for item in listed if item["id"] == place), None)
    final = dict(record, writer=data["writer"], written_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                 dispatch=dispatch)
    final.pop("replaces", None)
    if old:
        final["replaces"] = old
    import event_store
    event_store.atomic_json(path, final)
    out = {"record": record_rel(place), "line": None, "withdrawn": None, "refusal": "", "installed": writer is not None}
    if writer is None:
        return out
    try:
        if record["answer"] == "bug":
            # the line gate B would ask is retracted only when the draft's receipt stands NOW; otherwise it stays and the close turns it
            # into a gap (the suspicion always keeps a register line, AR-28)
            if active is not None and settled_answer(task, place)[1] == "settled":
                out["withdrawn"] = writer.append(task, {"op": "withdraw", "origin": {"dispatch": dispatch, "target": place},
                                                        "withdraws": {"id": active["id"], "reason": data["line_texts"]["withdraw_reason"]}},
                                                 by=dispatch)
        else:
            out["line"] = writer.append(task, _line_for(task, final, info, dispatch, active), by=dispatch)
    except ValueError as exc:
        out["refusal"] = str(exc)
    return out


# --- the CLI ----------------------------------------------------------------------------------------------------------------

def _command(argv) -> str:
    for token in argv:
        if token in SUBCOMMANDS:
            return f"{SCRIPT} {token}"
    return SCRIPT


def _parser(command: str) -> argparse.ArgumentParser:
    parser = RefusingParser(command=command, prog=SCRIPT, description=__doc__.split("\n\n")[0], epilog=epilog(SCRIPT),
                            formatter_class=argparse.RawDescriptionHelpFormatter)
    subs = parser.add_subparsers(dest="sub", required=True, parser_class=RefusingParser)
    for name in SUBCOMMANDS:
        sub = subs.add_parser(name, command=f"{SCRIPT} {name}", help=name)
        sub.add_argument("--task-root", required=True, help="the story folder (holds pipeline.json and work/)")
        if name == "list":
            sub.add_argument("--json", action="store_true", help="print the places as JSON")
        if name == "write":
            sub.add_argument("--dispatch", help="the dispatch id you run as")
            sub.add_argument("--place", help="the place id, as `list` prints it, or new-<slug>")
            sub.add_argument("--file", help="your answer, a JSON file")
            sub.add_argument("--replace", action="store_true", help="replace an answer you already gave")
        if name == "close-unsettled":
            sub.add_argument("--why", help="one of the gap reasons of references/place-answers.json")
    return parser


def _list_lines(found: dict, states: dict) -> list:
    if not found["places"] and not found["unreadable"]:
        return ["Places to settle: none in this run"]
    lines = []
    if found["unreadable"]:
        lines.append("The list of places could not be computed whole: " + "; ".join(f"{rec}: {why}" for rec, why in found["unreadable"]))
    if found["places"]:
        lines.append(f"Places to settle ({len(found['places'])}):")
    for place in found["places"]:
        where = _summary(place)
        lines.append(f"{place['id']} | {','.join(place['sources'])} | {states[place['id']][1]} | {place['title']} | "
                     f"expectation named by the record: {place['expectation_hint'] or 'none'} | where: {where}")
    return lines


def _cli(argv) -> int:
    args = hooklib.exact_options(_parser(_command(argv))).parse_args(argv)
    task = hooklib.story_of(SCRIPT, root=args.task_root, key_flag=None)
    if args.sub == "list":
        found = places(task)
        states = {p["id"]: settled_answer(task, p["id"]) for p in found["places"]}
        if args.json:
            print(json.dumps({"places": [dict(p, state=states[p["id"]][1], why=states[p["id"]][2]) for p in found["places"]],
                              "unreadable": [list(item) for item in found["unreadable"]]}, ensure_ascii=True))
        else:
            print("\n".join(_list_lines(found, states)))
        return 0
    if args.sub == "write":
        try:
            record = json.loads(Path(args.file).read_text(encoding="utf-8")) if args.file else None
        except (OSError, ValueError) as exc:
            _refuse([_p(f"--file cannot be read as JSON ({type(exc).__name__})", "write your answer as a JSON object file and pass its path")])
        shown = write(task, args.dispatch, args.place, record, replace=args.replace)
        print(json.dumps(shown, ensure_ascii=True))
        if shown["refusal"]:
            print(f"{SCRIPT} write: the answer is recorded in {shown['record']} but the register refused its line: {shown['refusal']}. "
                  "The place reads `carrier missing` until `write --replace` lands a line.", file=sys.stderr)
            return 2
        if not shown["installed"]:
            print(f"the findings register is not installed; the answer is kept in {shown['record']}", file=sys.stderr)
        return 0
    printed: list = []
    print(json.dumps({"closed": close_unsettled(task, args.why or "", printed), "printed": printed}, ensure_ascii=True))
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    return run_guarded(_command(argv), lambda: _cli(argv))


if __name__ == "__main__":
    sys.exit(main())
