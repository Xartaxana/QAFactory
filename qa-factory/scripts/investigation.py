"""investigation.py - preservation of what the run left open (P2 M2).

The runner's `inconclusive` / `manual_skipped` rows and the open-oracle refusals of a story are observations the run
could not settle. This module names each of them (a target), projects it verbatim into the findings register exactly
once, and turns the ones nobody investigated into `coverage_gap` lines, so they survive `finalize_task` and reach the
report. Nothing here compares an observation to an expectation, files a bug, or adds to "proven" (FR-18, FR-58).

    python scripts/investigation.py targets|unresolved|project|close-gaps --task-root <story folder> [--dispatch <id>] [--why <text>]

What the role still decides: whether a target is worth investigating, what the probe shows, and whether it is a
product matter (that goes through S7 triage and gate B). Code only names the targets, writes the register lines it can
derive verbatim, and leaves every line a role touched alone.

The register is written only through `exploratory_findings.append` (the one writer); this module never writes a file of
its own and never writes into the run's records.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract as C
import hooklib
import install_paths
from role_cli import RefusingParser, run_guarded

SCRIPT = "investigation.py"
SUBCOMMANDS = ("targets", "unresolved", "project", "close-gaps")
BUDGET_PATH = hooklib.PLUGIN_ROOT / "references" / "investigation-budget.json"

OPEN_RESULTS = ("inconclusive", "manual_skipped")
CODE_PREFIX = "code:investigation."
BY_PROJECT = "code:investigation.project"
BY_CLOSE = "code:investigation.close_gaps"

# The three texts a `close_gaps` call may carry (t-087 rev 8 m-6): the closed variety of the CONTRACT, not of projects.
WHY_TEXTS = ("the investigation is not available", "the investigation ended before this target",
             "gate B is already decided")

NOT_INSTALLED = "the findings register is not installed"
NOT_OBSERVED_B = "not observed: the case was refused before any capture"
NO_OBSERVATION_ROW = "the runner recorded no observation for this row"
NO_THEN = "the case states no Then"
NO_QUESTION_WHY = "the expected value has no linked question; the case was refused before any capture"
CASE_FILES = "the case files"
GAP_PREFIX = "gap-"
# Words a person may read (HF8-20): the register lines this module writes reach the report and gate B, so they carry no
# dispatch id, no path, no exception text and no question id (the id goes to `refs`).
OPEN_WHY = "the runner left this open and nobody has looked into it yet"
OWNER_WORDS = "the person who decides the story's expected behaviour"
QUESTION_FALLBACK = "a question the run could not settle"      # decision A: names the case beside it, never a question id (HF8-20)
RECORD_GAP_WHY = ("the run's own record could not be read; this is a gap in the records, not a finding about the product")
ANY_RECORD = "one of the story's own records"


# --- helpers ----------------------------------------------------------------------------------------------------------

def _writer():
    """The register writer module, or None when it is not installed (the findings register is optional to a story)."""
    try:
        import exploratory_findings
    except ImportError:
        return None
    return exploratory_findings


def _s(value) -> str:
    return value if isinstance(value, str) else ("" if value is None else str(value))


def _rel(task: Path, path: Path) -> str:
    return Path(path).resolve().relative_to(task.resolve()).as_posix()


def is_code_line(line: dict) -> bool:
    return _s(line.get("recorded_by")).startswith(CODE_PREFIX)


def _ref(task: Path, raw: str):
    """({path, sha256}, "") for a task-relative path that names a file under the story folder, else (None, the words)."""
    issue = C.evidence_ref_issue(task, {"path": raw}, "evidence", require_hash=False)
    if issue:
        return None, issue
    return {"path": raw, "sha256": install_paths.sha256_file(task.resolve() / raw)}, ""


# --- targets ----------------------------------------------------------------------------------------------------------

def _accepted_s6(task: Path):
    """([accepted S6 dispatch ids in event order], unreadable). A story with no event journal has no dispatches."""
    if not (task / "state" / "events.jsonl").is_file():
        return [], []
    try:
        from controller import Controller
        state = Controller(task).state()
    except Exception as exc:                      # the journal cannot be projected: a record we could not read
        return [], [("state/events.jsonl", f"{type(exc).__name__}: {exc}")]
    return [name for name, d in (state.get("dispatches") or {}).items()
            if isinstance(d, dict) and d.get("stage") == "S6" and d.get("status") == "accepted"], []


def _rows_of(task: Path, dispatch: str):
    """([(index, row)] of the open rows of one handoff, "") or ([], why) when the form exists and cannot be read."""
    path = task / "work" / "handoffs" / f"{dispatch}.yaml"
    if not path.is_file():
        return None, ""
    try:
        import handoff
        doc = handoff.parse(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:          # UnicodeDecodeError is a ValueError
        return [], f"{type(exc).__name__}: {exc}"
    rows = doc.data.get("manual_observations") if isinstance(doc.data, dict) else None
    if rows is None:
        return [], ""
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        return [], "`manual_observations` is not a list of maps"
    return [(i, row) for i, row in enumerate(rows) if _s(row.get("result")).strip() in OPEN_RESULTS], ""


def _blank_target(target_id: str) -> dict:
    return {"id": target_id, "sources": [], "case": None, "dispatch": None, "index": None, "then": "", "observed": "",
            "before_change": "", "evidence": [], "why_inconclusive": "", "question": None, "question_words": "", "carrier": [],
            "refusal": "", "requirements": []}


def investigation_targets(task_root) -> dict:
    """{"targets": [...], "unreadable": [(record, why)]} - every observation the run left open, writes nothing.

    (a) the `inconclusive` / `manual_skipped` rows of `manual_observations` in the accepted S6 forms, verbatim;
    (b) every pinned case whose `request.json` holds `refused` and whose expectation gap is still open, recomputed now.
    A record that exists and cannot be read is `unreadable`, never skipped. What the role still decides: whether any
    of them is worth a probe."""
    task = Path(task_root)
    unreadable: list = []
    pins = {_s(link.get("case_id")) for link in C.story_case_links(task) if _s(link.get("case_id"))}
    index_cache: list = []                         # [case_index or None] once tried

    def case_index():
        if not index_cache:
            try:
                index_cache.append(C.case_index(task))
            except ValueError as exc:
                index_cache.append(None)
                unreadable.append((CASE_FILES, str(exc)))
        return index_cache[0]

    def case_fact(case):
        found = case_index()
        try:
            return found[case] if found is not None else {}
        except KeyError:
            return {}

    targets: dict = {}
    dispatches, bad = _accepted_s6(task)
    unreadable += bad
    for dispatch in dispatches:                    # (a): a later accepted dispatch's row for the same case wins
        rows, why = _rows_of(task, dispatch)
        record = f"work/handoffs/{dispatch}.yaml"
        if why:
            unreadable.append((record, why))
            continue
        for index, row in rows or []:
            case = _s(row.get("case")).strip()
            pinned = case in pins
            target = _blank_target(f"case-{case}" if pinned else f"obs-{dispatch}-{index}")
            evidence = row.get("evidence")
            names = [evidence] if isinstance(evidence, str) else evidence if isinstance(evidence, list) else []
            target.update(sources=["a"], case=case if pinned else None, dispatch=dispatch, index=index,
                          then=_s(row.get("then")), observed=_s(row.get("observed")),
                          before_change=_s(row.get("before_change")), why_inconclusive=_s(row.get("why_inconclusive")),
                          evidence=[_s(name).strip() for name in names if _s(name).strip()], carrier=[record])
            if pinned:
                target["requirements"] = [_s(r) for r in (case_fact(case).get("requirements") or [])]
            targets[target["id"]] = target

    for case in sorted(pins):                      # (b)
        path = _request_path(task, case)
        if not path.is_file():
            continue
        record = _rel(task, path)
        data = hooklib.read_json(path, None, kind=dict)
        if data is None:
            unreadable.append((record, "the request file is not readable JSON (an object was expected)"))
            continue
        refused = data.get("refused")
        if not refused:
            continue
        fact = case_fact(case)
        if not fact:
            continue
        import manual_evidence
        gaps = manual_evidence.expectation_gaps(task, fact)
        if not gaps:
            continue
        question, question_words = next(((_s(qid), _s(words)) for qid, words in gaps if _s(qid)), (None, ""))
        import traceability
        clauses = traceability.case_thens(Path(fact["path"])) if fact.get("path") else {}
        then = " / ".join(clauses[n] for n in sorted(clauses)) or NO_THEN
        reason = _s(refused.get("reason")) if isinstance(refused, dict) else ""
        target = targets.get(f"case-{case}")
        if target is None:
            target = _blank_target(f"case-{case}")
            target.update(case=case, then=then, requirements=[_s(r) for r in (fact.get("requirements") or [])])
            targets[target["id"]] = target
        elif not target["then"].strip():
            target["then"] = then
        target["sources"] = sorted(set(target["sources"]) | {"b"})
        target["question"] = question
        target["question_words"] = question_words
        target["refusal"] = reason
        target["carrier"] = target["carrier"] + [record]
    return {"targets": [targets[key] for key in sorted(targets)], "unreadable": unreadable}


def _request_path(task: Path, case: str) -> Path:
    import manual_evidence
    return manual_evidence.request_path(task, case)


# --- projection -------------------------------------------------------------------------------------------------------

def _question_words(task: Path, target: dict, rows: dict) -> str:
    """The WORDS of the question a (b) target is linked to: the question row's own text, read through the one reader
    (`question_register.load`, cached in `rows` for the pass), else the words of the expectation gap that named it, else a
    fixed sentence - never the question id (a person is not asked by id)."""
    if "loaded" not in rows:
        try:
            import question_register
            rows["loaded"] = {q.get("id"): q for q in question_register.load(task).get("questions", []) if isinstance(q, dict)}
        except Exception:                          # the register cannot be read: the fallbacks below speak
            rows["loaded"] = {}
    row = rows["loaded"].get(target["question"])
    said = _s(row.get("question") if isinstance(row, dict) else "").strip()
    if said:
        return said
    case = _s(target.get("case")).strip()     # the gap's own words name the question id ("its question Q7 is not answered"): not used
    return f"{case} - {QUESTION_FALLBACK}" if case else QUESTION_FALLBACK


def _fields(task: Path, target: dict, printed: list, rows: dict | None = None) -> dict:
    """The register fields a target projects to, verbatim where the target holds a value (C-8 fallbacks otherwise)."""
    rows = rows if rows is not None else {}
    b = "b" in target["sources"]
    question = target["question"] if b else None
    refs_seen, evidence_refs = set(), []
    for raw in list(target["carrier"]) + list(target["evidence"]):
        ref, issue = _ref(task, raw)
        if ref is None:
            printed.append(f"{target['id']}: not recorded as evidence - {issue}")
        elif ref["path"] not in refs_seen:
            refs_seen.add(ref["path"])
            evidence_refs.append(ref)
    if target["observed"].strip():
        statement = target["observed"]
    else:
        statement = NOT_OBSERVED_B if target["sources"] == ["b"] else NO_OBSERVATION_ROW
    if target["why_inconclusive"].strip():
        why = target["why_inconclusive"]
    elif target["refusal"].strip():
        why = target["refusal"]
    elif b and not question:
        why = NO_QUESTION_WHY
    else:
        why = OPEN_WHY
    refs = ([target["case"]] + [r for r in target["requirements"] if r != target["case"]]
            if target["id"].startswith("case-") else [])
    fields = {"kind": "observation", "oracle_status": "owner_question" if b else "none",
              "title": target["then"] if target["then"].strip() else target["id"], "statement": statement,
              "why_not_a_bug": why, "evidence_refs": evidence_refs, "probe": None, "verification_status": "unverified",
              "refs": refs}
    if b and question:                             # the words are the question; its id stays reachable in `refs` (AR-22)
        fields.update(kind="unresolved_question", question=_question_words(task, target, rows), owner_role=OWNER_WORDS,
                      refs=refs + [question] if question not in refs else refs)
    return fields


def _record_words(record: str) -> str:
    """The record an unreadable-record gap is about, in words for a person - never the path. Anything this does not know is
    "one of the story's own records" (the safe direction: a path is never shown)."""
    text = _s(record).replace("\\", "/").strip()
    if text == CASE_FILES:
        return CASE_FILES
    if text == "state/events.jsonl":
        return "the story's event journal"
    if text == "pipeline.json":
        return "the story's stage record"
    if re.fullmatch(r"work/handoffs/[^/]+\.ya?ml", text):
        return "the test runner's hand-back"
    manual = re.fullmatch(r"work/(?:evidence/)?manual/([^/]+)/request\.json", text)
    if manual:
        return f"the manual-check request of {manual.group(1)}"
    if text.startswith("work/"):
        import manual_evidence
        return manual_evidence.plain_words(text)
    return ANY_RECORD


def _settled_by_analyst(task: Path, target_id: str) -> bool:
    """Does `place_answers.settled_answer` (the ONE reader, AR-13) say the analyst settled this target? A reader that raises or cannot
    be imported says no: the target is projected as before (the error goes toward asking)."""
    try:
        import place_answers
        return place_answers.settled_answer(task, target_id)[1] == "settled"
    except Exception:                                   # noqa: BLE001
        return False


def project(task_root, dispatch) -> dict:
    """{"added", "corrected", "skipped", "printed"} - each target of `investigation_targets` goes into the findings
    register once: no chain -> `add` (status `unverified`); a code-only chain whose observation changed -> one `correct`;
    a chain a role touched, or a withdrawn one -> left alone; a target the analyst settled on the stand (`place_answers.settled_answer`
    says `settled`) -> left alone, so gate B is never asked a question about it. Each unreadable record becomes a `coverage_gap`.
    What the role still decides: everything after the line exists (probe it, correct it, withdraw it)."""
    out = {"added": [], "corrected": [], "skipped": [], "printed": []}
    writer = _writer()
    if writer is None:
        out["printed"].append(NOT_INSTALLED)
        return out
    if not _s(dispatch).strip():
        raise ValueError("--dispatch is required: name the dispatch id the lines are recorded under")
    task = Path(task_root)
    found = investigation_targets(task)
    chains = writer.chains_of(writer.read(task)["lines"])          # the register's one derivation of "the chain of a target"
    rows: dict = {}                                                # the question rows, read once for the pass
    for target in found["targets"]:
        chain = chains.get(target["id"], [])
        if chain and (chain[-1]["op"] == "withdraw" or not all(is_code_line(line) for line in chain)):
            out["skipped"].append(target["id"])
            continue
        if _settled_by_analyst(task, target["id"]):      # the analyst settled this place: no question is put on it, no line changed (FR-10)
            out["skipped"].append(target["id"])
            continue
        fields = _fields(task, target, out["printed"], rows)
        origin = {"dispatch": dispatch, "target": target["id"]}
        if not chain:
            out["added"].append(writer.append(task, dict(fields, op="add", origin=origin), by=BY_PROJECT))
            continue
        active = chain[-1]
        if _s(active.get("statement")) == fields["statement"]:
            continue
        if active.get("kind") == "coverage_gap":   # a closed gap stays a gap; only its observation is new
            fields.update(kind="coverage_gap", missing_prerequisite=active.get("missing_prerequisite"))
            fields.pop("question", None)
            fields.pop("owner_role", None)
        out["corrected"].append(writer.append(task, dict(
            fields, op="correct", origin=origin,
            corrects={"id": active["id"], "reason": "the runner's observation changed since it was recorded"}),
            by=BY_PROJECT))
    for record, why in found["unreadable"]:
        key = GAP_PREFIX + record
        if chains.get(key):
            continue
        raw = record if (task / record).is_file() else "pipeline.json"
        ref, issue = _ref(task, raw)
        if ref is None:
            out["printed"].append(f"the factory could not read {record} ({why}); no evidence file to record it with - {issue}")
            continue
        out["printed"].append(f"the factory could not read {record}: {why}")      # the role/CLI channel keeps the path and the reason
        words = _record_words(record)
        out["added"].append(writer.append(task, {
            "op": "add", "kind": "coverage_gap", "title": f"the factory could not read {words}",
            "statement": f"the factory could not read {words}", "missing_prerequisite": f"a readable copy of {words}",
            "why_not_a_bug": RECORD_GAP_WHY, "evidence_refs": [ref], "probe": None,
            "verification_status": "unverified", "refs": [], "origin": {"dispatch": dispatch, "target": key}},
            by=BY_PROJECT))
    return out


# --- resolution -------------------------------------------------------------------------------------------------------

def _unrooted(task: Path, text: str) -> str:
    """`text` with the story's absolute folder replaced by "the story folder" (AR-4: nothing a role reads is bound to one machine).
    Every spelling the folder can take - resolved or not, either slash - and the longest first, so no prefix is left behind."""
    spellings = {str(task), task.as_posix(), str(task.resolve()), task.resolve().as_posix()}
    for root in sorted(spellings, key=len, reverse=True):
        text = text.replace(root, "the story folder")
    return text


def unresolved_targets(task_root, budget) -> dict:
    """{"unresolved": [target], "resolved": [(id, why)], "context": {id: [line]}, "settled": [target]} - which targets still wait.

    Resolved: (i) a role recorded an evidenced outcome (status above `unverified`, `probe.runs` >= 1); (ii) a role
    withdrew the chain or wrote a `coverage_gap`; (iii) the case has a `work/triage.json` row whose verdict is one of the
    budget's `resolving_verdicts` AND whose evidence is a file under `work/evidence/` (a verdict word alone resolves
    nothing); (iv) the analyst settled the place on the stand: `place_answers.settled_answer` says `settled` (a record that
    stands AND its carrier exists); such a target is also listed whole under `settled`. A record that does not stand, or
    whose carrier is missing, resolves nothing, and `place_answers` raising resolves nothing and adds one context line.
    Every other row is attached as context, never as a resolution. The evidence judge errs only toward
    UNRESOLVED. A `resolving_verdicts` that is not a list resolves nothing. What the role still decides: whether a
    context line changes what it investigates."""
    task = Path(task_root)
    targets = investigation_targets(task)["targets"]
    writer = _writer()
    chains = writer.chains_of(writer.read(task)["lines"]) if writer is not None else {}
    verdicts = budget.get("resolving_verdicts") if isinstance(budget, dict) else None
    verdicts = [v for v in verdicts if isinstance(v, str)] if isinstance(verdicts, list) else []
    triage = hooklib.read_json(task / "work" / "triage.json", None, kind=dict)
    rows = triage.get("triage") if isinstance(triage, dict) else None
    rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    out = {"unresolved": [], "resolved": [], "context": {}, "settled": []}
    for target in targets:
        chain = chains.get(target["id"], [])
        active = chain[-1] if chain else None
        why = ""
        if chain and active["op"] == "withdraw":
            why = f"{active['id']} withdrew the chain ({active['recorded_by']})"
        elif active is not None and not is_code_line(active):
            probe = active.get("probe")
            runs = probe.get("runs") if isinstance(probe, dict) else 0
            if active.get("kind") == "coverage_gap":
                why = f"{active['id']} is a coverage gap written by {active['recorded_by']}"
            elif active.get("verification_status") != "unverified" and isinstance(runs, int) and runs >= 1:
                why = f"{active['id']} records an outcome of {runs} run(s) by {active['recorded_by']}"
        context = []
        if triage is None:
            context.append("triage: unreadable")
        for row in rows:
            if target["case"] is None or _s(row.get("case") or row.get("test")).strip() != target["case"]:
                continue
            issue = C.evidence_ref_issue(task / "work", {"path": row.get("evidence", "")}, "triage evidence",
                                         require_hash=False, under="evidence")
            verdict = _s(row.get("verdict"))
            detail = "; ".join(f"{key}: {json.dumps(row[key], ensure_ascii=False) if not isinstance(row[key], str) else row[key]}"
                               for key in ("note", "our_signal", "env_fix", "unverified") if row.get(key))
            context.append(f"triage {verdict} ({_s(row.get('evidence'))})" + (f": {detail}" if detail else "")
                           + (f"; evidence: {_unrooted(task, issue)}" if issue else ""))
            if not why and verdict in verdicts and not issue:
                why = f"triage {verdict} with evidence {_s(row.get('evidence'))}"
        if not why:                                # (iv) the analyst settled this place on the stand (spec t-1991, `place_answers`)
            try:
                import place_answers
                record, state, _reason = place_answers.settled_answer(task, target["id"])
                if state == "settled" and record is not None:
                    why = f"settled by {_s(record.get('dispatch'))}: {_s(record.get('answer'))}"
                    out["settled"].append(target)
            except Exception:                      # an answer that cannot be read resolves nothing (FR-59)
                context.append("place answers: the analyst's answer could not be read")
        if why:
            out["resolved"].append((target["id"], why))
        else:
            out["unresolved"].append(target)
            if context:
                out["context"][target["id"]] = context
    return out


def budget_problems(budget) -> list:
    """[one line per problem] of the investigation budget (`references/investigation-budget.json`), [] when it is valid.
    The ONE validity rule of that file: `None` or not an object, `schema_version` not 1, `methods` not a non-empty list of
    non-empty strings, `probes_per_dispatch` / `reproductions_per_target` / `timebox_minutes` not an int > 0 (a bool is
    refused first), `resolving_verdicts` not a list of strings. Pure. What the role still decides: nothing."""
    if not isinstance(budget, dict):
        return ["cannot be read"]
    problems = []
    version = budget.get("schema_version")
    if isinstance(version, bool) or version != 1:
        problems.append("`schema_version` is not 1")
    methods = budget.get("methods")
    if not (isinstance(methods, list) and methods and all(isinstance(m, str) and m.strip() for m in methods)):
        problems.append("`methods` is not a non-empty list of strings")
    for key in ("probes_per_dispatch", "reproductions_per_target", "timebox_minutes"):
        value = budget.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            problems.append(f"`{key}` is not an int > 0")
    verdicts = budget.get("resolving_verdicts")
    if not (isinstance(verdicts, list) and all(isinstance(v, str) for v in verdicts)):
        problems.append("`resolving_verdicts` is not a list of strings")
    return problems


def load_budget(plugin_root=None) -> tuple:
    """(budget or None, [problem]) - the ONE read of `references/investigation-budget.json` (of `plugin_root` when given, else this
    package's own) with its `budget_problems`. `None` and a non-empty problem list are the same answer: the file cannot be used.
    Never raises. What the caller still decides: what an unusable budget means for its own step."""
    path = BUDGET_PATH if plugin_root is None else Path(plugin_root) / "references" / BUDGET_PATH.name
    budget = hooklib.read_json(path, None, kind=dict)
    return budget, budget_problems(budget)


def open_targets(task_root, budget) -> dict:
    """`unresolved_targets` under the ONE rule "a budget that cannot be used resolves nothing" (FR-59): every caller that asks
    which targets still wait goes through here, so a broken budget never resolves a target on one road and not on another."""
    return unresolved_targets(task_root, {"resolving_verdicts": []} if budget_problems(budget) else budget)


# --- closing the gaps -------------------------------------------------------------------------------------------------

def close_gaps(task_root, why, printed=None, *, budget=None, unresolved=None) -> list:
    """[ids of the lines written] - every target whose chain holds only code lines, is not withdrawn and is still UNRESOLVED
    (a triage verdict that resolves it, with its evidence, is a judgment: it is never "not investigated") becomes a
    `coverage_gap` (one `correct` of its active line: the target keeps ONE active line); a target already closed with the
    same `why` gets nothing, a different `why` one more `correct`. `why` is one of WHY_TEXTS, else ValueError naming them.
    The evidence paths of the corrected line are re-hashed now; a path that is no longer a file is dropped, and a target
    with none left stays as it is and is appended to `printed` (when the caller passes a list). What the role still
    decides: whether the target is investigated before the gate closes. Which targets are resolved comes from `unresolved` (the
    ids or targets the caller already computed) or, with neither it nor `budget`, from `load_budget()`; an unusable budget
    resolves nothing, so every code-only chain is a gap."""
    if why not in WHY_TEXTS:
        raise ValueError(f"`why` is {why!r}; expected one of: " + "; ".join(f"`{text}`" for text in WHY_TEXTS))
    writer = _writer()
    printed = printed if printed is not None else []
    if writer is None:
        printed.append(NOT_INSTALLED)
        return []
    task = Path(task_root)
    chains = writer.chains_of(writer.read(task)["lines"])      # a target's chain is independent of the other targets' writes: read once
    if unresolved is None:
        unresolved = open_targets(task, budget if budget is not None else load_budget()[0])["unresolved"]
    waiting = {str(t.get("id")) if isinstance(t, dict) else str(t) for t in unresolved}
    known = {str(t["id"]) for t in investigation_targets(task)["targets"]}
    resolved = known - waiting                                  # a current target the triage / a role already settled
    missing = f"not investigated - {why}"
    written = []
    for target in sorted(chains):
        if target.startswith(GAP_PREFIX) or target in resolved:    # an unreadable record is already a gap; a resolved target is not
            continue
        chain = chains[target]
        active = chain[-1]
        if active["op"] == "withdraw" or not all(is_code_line(line) for line in chain):
            continue
        if active.get("verification_status") != "unverified":
            continue
        if active.get("kind") == "coverage_gap" and active.get("missing_prerequisite") == missing:
            continue
        refs = []
        for old in active.get("evidence_refs") or []:
            ref, _ = _ref(task, _s(old.get("path")) if isinstance(old, dict) else "")
            if ref is not None:
                refs.append(ref)
        if not refs:
            printed.append(f"{target}: every evidence file of {active['id']} is gone; the line stays as it is")
            continue
        line = {key: active[key] for key in ("title", "statement", "refs", "oracle_status", "why_not_a_bug", "question",
                                             "owner_role") if key in active}
        line.update(op="correct", kind="coverage_gap", missing_prerequisite=missing, probe=None,
                    verification_status="unverified", evidence_refs=refs, origin=active["origin"],
                    corrects={"id": active["id"], "reason": why})
        written.append(writer.append(task, line, by=BY_CLOSE))
    return written


# --- the pass and the decision ----------------------------------------------------------------------------------------

def pass_members(state) -> list:
    """[dict(record, id=...)] - every dispatch record of the controller `state` that is an S7 investigation pass and counts
    in its chain (`controller.s7_part_of`; a status in `controller.DISCOUNTED` does not count), in the state's order.
    Crooked `state` / `dispatches` answer []. Pure. The ONE predicate of "a pass exists" for the driver, the skill road
    and the probe. What the role still decides: nothing."""
    import controller
    dispatches = state.get("dispatches") if isinstance(state, dict) else None
    if not isinstance(dispatches, dict):
        return []
    return [dict(d, id=str(d.get("id") or key)) for key, d in dispatches.items()
            if isinstance(d, dict) and controller.s7_part_of(d) == "investigation"
            and d.get("status") not in controller.DISCOUNTED]


def decision(task_root, state, pipeline, budget) -> tuple:
    """(word, why) - what S7 does about the unresolved targets before it closes by code. word: `none` (close as today),
    `dispatch` (one read-only investigation), `wait` (why = the running member's id), `gaps` (record the targets as
    coverage gaps with `why`, then close). Pure: no write, no dispatch, no print; an exception of
    `unresolved_targets` propagates (the caller's guard owns it). What the role still decides: the investigation itself."""
    members = pass_members(state)
    running = next((m for m in members if m.get("status") == "running"), None)
    if running is not None:
        return "wait", running["id"]
    if _writer() is None:
        return "none", NOT_INSTALLED
    if budget_problems(budget):                     # an unreadable budget resolves nothing and would refuse every probe
        left = open_targets(task_root, budget)["unresolved"]
        return ("none", "") if not left else ("gaps", WHY_TEXTS[0])
    if not open_targets(task_root, budget)["unresolved"]:
        return "none", ""
    if members:
        return "gaps", WHY_TEXTS[1]
    if C.gate_answered(pipeline, "B"):
        return "gaps", WHY_TEXTS[2]
    return "dispatch", ""


# --- the CLI ----------------------------------------------------------------------------------------------------------

def _state_of(task: Path) -> dict:
    """The controller state of a story, {} when it has no event journal. An unreadable journal raises: the CLI refuses
    rather than answer "no pass" from a state nobody could read."""
    if not (task / "state" / "events.jsonl").is_file():
        return {}
    from controller import Controller
    return Controller(task).state()


def _command(argv) -> str:
    writer = _writer()          # the ONE definition lives in the register's module; without it the refusal names the script
    return writer.command_of(SCRIPT, SUBCOMMANDS, argv) if writer is not None else SCRIPT


def _parser(command: str) -> argparse.ArgumentParser:
    parser = RefusingParser(command=command, prog=SCRIPT, description=__doc__.split("\n\n")[0])
    subs = parser.add_subparsers(dest="sub", required=True, parser_class=RefusingParser)
    for name in SUBCOMMANDS:
        sub = subs.add_parser(name, command=f"{SCRIPT} {name}", help=name)
        sub.add_argument("--task-root", required=True, help="the story folder (holds pipeline.json and work/)")
        if name in ("project", "close-gaps"):
            sub.add_argument("--dispatch", help="the dispatch id the lines are recorded under")
        if name == "close-gaps":
            sub.add_argument("--why", help="; ".join(WHY_TEXTS))
    return parser


def _run(argv) -> int:
    args = hooklib.exact_options(_parser(_command(argv))).parse_args(argv)
    task_root = hooklib.story_of(SCRIPT, root=args.task_root, key_flag=None)      # the story first: no phantom folder
    if args.sub == "targets":
        found = investigation_targets(task_root)
        shown = {"targets": found["targets"], "unreadable": [list(item) for item in found["unreadable"]]}
    elif args.sub == "unresolved":
        budget, problems = load_budget()
        members = pass_members(_state_of(task_root))
        found = open_targets(task_root, budget)
        pipeline = hooklib.read_json(task_root / "pipeline.json", None, kind=dict)
        if pipeline is None:
            print("investigation.py: pipeline.json cannot be read; `gate_b_answered` is null", file=sys.stderr)
        shown = {"unresolved": found["unresolved"], "resolved": [list(item) for item in found["resolved"]],
                 "context": found["context"], "budget_problems": problems,
                 "gate_b_answered": None if pipeline is None else C.gate_answered(pipeline, "B"),
                 "pass_members": [{"id": m["id"], "status": m.get("status")} for m in members]}
    elif args.sub == "project":
        shown = project(task_root, args.dispatch)
    else:
        printed: list = []
        budget, _ = load_budget()                       # read once; `close_gaps` uses it as given
        shown = {"closed": close_gaps(task_root, args.why or "", printed, budget=budget), "printed": printed}
    print(json.dumps(shown, ensure_ascii=True))
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    return run_guarded(_command(argv), lambda: _run(argv))


if __name__ == "__main__":
    sys.exit(main())
