"""S7 by code: a manual check whose own record already says what stopped it gets its triage row from code, and the
failure analyst is asked only about the failures that need a judgment (t-305 N1; the Lead's decisions Q7, Q9, Q10, Q11,
Q23).

WHY. On TP1-15045 (man1, 02.10) the analyst took 37 turns for five failures, one of which (TC_009) was a manual
`inconclusive` whose record already said, in the runner's own words, why the check could not conclude. That row is not a
judgment about the product: nothing was executed that could answer. The other four were red tests, and a red test is
never pre-judged by code (FR-58, P20) - not even one whose manifest row says `blocked_by_env`: that word was written by
S5, the test still FAILED, and whether the stand or the product failed is the analyst's call.

WHAT CODE DECIDES. Exactly one state: a manual check (`current_manual_checks`) whose result is `inconclusive`, whose
record validated (`evidence_validated` is true), which the reducer did not make inconclusive itself (no
`current_reason`), which carries at least one limitation the ROLE wrote, and whose case no `contradicts_requirement`
row of the manifest names. The row it writes says `verdict: NOT_EXECUTED` (the check did not answer; it lands in
"Left with you"), `source: code`, where it came from (`from`), and the role's own limitations VERBATIM (FR-35).
Everything else - every red result, a manual `fail`/`error`, a reducer-made `inconclusive`, an unnamed failure, a failure
a row of the analyst already answers - is left to the analyst, who may also replace a code row with its own; code never
writes over a row that is not its own (Q11).

TELLING THE ROLE'S LIMITATION FROM THE CODE'S (Q8 a). `manual_evidence.build` appends one sentence of its own to
`limitations[]` of a record that was identified by its image ("the stand was identified by the image it runs (<id>),
not by the sources it serves", FR-41), and a PASSED check carries it too, so "has a limitation" discriminates nothing.
A limitation counts as the role's unless it EQUALS that sentence built from the record's own identity (whitespace at
the ends aside). Exact equality is the whole test: no phrase list (FR-12). The sentence is a second copy of one in
`manual_evidence.py`, pinned by `test_s7_pretriage.py`; a shared constant and a limitation marker are the Q8-b backlog row.

ERROR DIRECTION (a function that advises, `triage_failures`/`bind_triage`, is here the gate of "code closes S7"). The
only allowed mistake is "left to the analyst": one more analyst row is the cost. Inputs this module must leave with the
analyst, each a test: an `inconclusive` whose only limitation is the identity sentence; a reducer-made one; one with
`evidence_validated` false or absent; one beside a `contradicts_requirement` row (CASE_DEFECT is the analyst's alone);
a manual `fail`; limitations that are not strings, blank, or None; a check with no `attempt_id` (the analyst's own
`artifact_producer` refuses a triage row without one, so a code row without it would make the analyst's publish fail);
two attempts of one case (only the failing rows of the CURRENT list count, and they must agree on the attempt). The
boundary the other way: a limitation that has the identity sentence's shape but another image id is the role's text.

TEMPORAL. `NOT_EXECUTED` is not a word of `contract.TRIAGE_VERDICTS` until the integrator adds it (with its vocabulary
row and its owner in `check_delivery.OWNER_BY_TRIAGE_VERDICT`). Before that this module writes NO row: it says so, names
the constant, and the check goes to the analyst as it did before; after it, the rows are written. It never writes a row
whose verdict the contract does not know.

This module is a library the driver calls in-process (`story_run.Driver.stage_S7`); it launches nothing and has no CLI.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract as C  # noqa: E402
from event_store import atomic_json  # noqa: E402

VERDICT = "NOT_EXECUTED"
SOURCE = "code"
REPORT_REL = "work/run-report.json"
TRIAGE_REL = "work/triage.json"
CONTRADICTS = "contradicts_requirement"
# The one sentence `manual_evidence.build` writes for a record's own identity (see the module docstring).
IDENTITY_HEAD = "the stand was identified by the image it runs ("
IDENTITY_TAIL = "), not by the sources it serves"
_CASE_SPLIT = re.compile(r"[\s,;/|]+")


def identity_sentence(identity: str) -> str:
    return IDENTITY_HEAD + identity + IDENTITY_TAIL


def code_sentences(row: dict) -> set:
    """The sentences `manual_evidence` could have written into this record: one per identity the record carries
    (`runtime_before.observed_runtime_identity`, which the writer reads, and the record's own `runtime_identity`) - the
    image sentence of t-279 K-IMG, which 3 records of TP1-15045 still carry (no longer written since t-300 N2, but
    still code's, never the role's: F11) - and the sentences of a person's word (`manual_evidence.person_sentences`, the
    function that writes them, read for the record's own `runtime_before` and `runtime_after`)."""
    before = row.get("runtime_before")
    out = set()
    for identity in ((before or {}).get("observed_runtime_identity") if isinstance(before, dict) else None,
                     row.get("runtime_identity")):
        if isinstance(identity, str) and identity.strip():
            out.add(identity_sentence(identity))
    from manual_evidence import person_sentences, rejudge_sentence
    for probe in (before, row.get("runtime_after")):
        out.update(person_sentences(probe))
    # HF8-19 (N1b): the sentence `manual_evidence.rejudge_record` writes into a re-judged record is code's, never the runner's
    # (FR-35): a record the runner judged again is not "inconclusive with a limitation of the role's own" because of it. The
    # sentence is built from the record's own `rejudge_of` / `rejudge_reason` by the ONE function that writes it.
    of, reason = row.get("rejudge_of"), row.get("rejudge_reason")
    if isinstance(of, str) and of.strip() and isinstance(reason, str) and reason.strip():
        out.add(rejudge_sentence(of, reason))
    return out


def role_limitations(row: dict) -> list:
    """The limitations of a manual check that the role (or the capture) wrote: every non-blank string that is not the
    code's identity sentence, in order, without repeats. Non-strings, blanks and None are not limitations."""
    code = code_sentences(row)
    given = row.get("limitations")
    out = []
    for text in given if isinstance(given, list) else []:
        if isinstance(text, str) and text.strip() and text.strip() not in code and text not in out:
            out.append(text)
    return out


def is_code_row(row) -> bool:
    return isinstance(row, dict) and row.get("source") == SOURCE


def _strings(value) -> list:
    """Every case-like token a manifest cell holds: strings (split on spaces, commas, slashes), lists, and the
    `case_id` / `case` of a link object. The manifest's own writers differ, and error direction decides: more tokens
    means more cases counted as contradicted, which only sends a failure to the analyst."""
    if isinstance(value, str):
        return [t for t in _CASE_SPLIT.split(value.strip()) if t]
    if isinstance(value, list):
        return [t for item in value for t in _strings(item)]
    if isinstance(value, dict):
        return [t for key in ("case_id", "case") for t in _strings(value.get(key))]
    return []


def contradicted(manifest) -> tuple:
    """`(cases, blanket)` of the manifest's `contradicts_requirement` rows: the case tokens they name, and whether one
    names none (then it cannot be told from which case it speaks, so it holds back EVERY manual check - the analyst's
    side of the error direction). The row is found as the driver finds it (`failures_to_triage`): the word anywhere in
    the entry."""
    cases, blanket = set(), False
    for entry in C.manifest_unresolved(manifest if isinstance(manifest, dict) else {}):
        if CONTRADICTS not in json.dumps(entry, ensure_ascii=False):
            continue
        named = set()
        for key in ("case", "covers", "case_version_links", "case_links", "cases"):
            named.update(_strings(entry.get(key)))
        cases |= named
        blanket = blanket or not named
    return cases, blanket


def failing_manual_rows(report: dict) -> tuple:
    """`(list name, {failure key: [the failing rows under it]})`, read the way `contract.triage_failures` reads them:
    the list is `current_manual_checks`, or the legacy `manual_checks` when the current one is absent or empty; a row is
    a failure when `contract.triage_targets` says so, and its key is `("manual", first name)`."""
    current = report.get("current_manual_checks")
    list_name = "current_manual_checks" if current else "manual_checks"
    checks = current or report.get("manual_checks")
    out: dict = {}
    for row in checks if isinstance(checks, list) else []:
        if not isinstance(row, dict):
            continue
        for names in C.triage_targets({"current_manual_checks": [row]})["names"]:
            out.setdefault(("manual", names[0]), []).append(row)
    return list_name, out


def _why_not(rows: list, case_names: set, held: tuple) -> str:
    """"" when every failing row under one failure is a state code may decide, else the reason it is left to the analyst."""
    cases, blanket = held
    if not rows:
        return "no failing row"
    if blanket or case_names & cases:
        return "the manifest holds a contradicts_requirement row for it"
    attempts = set()
    for row in rows:
        if row.get("unprepared") is not None:      # F5: code never decides what an unprepared walk observed (FR-22, P26)
            return "an unprepared walk: whether what it observed is a bug is the analyst's call (P26)"
        if C.triage_targets({"current_manual_checks": [row]})["observations"]:
            return "the runner recorded an observation, and whether it is a bug is the analyst's call (P26)"
        if C.result_status({"status": row.get("result") or row.get("status")}) != "inconclusive":
            return "the check did not end inconclusive"
        if str(row.get("current_reason") or "").strip():
            return "the reducer made it inconclusive"
        if row.get("evidence_validated") is not True:
            return "its evidence was not validated"
        if not role_limitations(row):
            return "its record carries no limitation of the role's own"
        attempt = row.get("attempt_id")
        if not (isinstance(attempt, str) and attempt.strip()):
            return "its record names no attempt"
        attempts.add(attempt.strip())
    if len(attempts) != 1:
        return "its rows name more than one attempt"
    return ""


def _code_row(key: tuple, rows: list, list_name: str, held: tuple) -> tuple:
    """`(row, "")` for a failure code decides, else `(None, why)`. The row is the shape of an analyst's row for a manual
    check (`instance_id` = the case, as the analyst writes it: `artifact_producer` demands `instance_id` and
    `attempt_id` of every row) plus `source`, `from` and the role's limitations verbatim."""
    case_names = {str(r.get("case")).strip() for r in rows if str(r.get("case") or "").strip()} | {key[1]}
    why = _why_not(rows, case_names, held)
    if why:
        return None, why
    attempt = rows[0]["attempt_id"].strip()
    limitation, evidence = [], []
    for row in rows:
        limitation += [t for t in role_limitations(row) if t not in limitation]
        for ref in row.get("evidence_refs") if isinstance(row.get("evidence_refs"), list) else []:
            path = ref.get("path") if isinstance(ref, dict) else None
            if isinstance(path, str) and path.strip() and path not in evidence:
                evidence.append(path)
    case = next((str(r["case"]).strip() for r in rows if str(r.get("case") or "").strip()), key[1])
    return ({"instance_id": key[1], "attempt_id": attempt, "case": case, "verdict": VERDICT, "source": SOURCE,
             "from": {"artifact": REPORT_REL, "state": "inconclusive",
                      "pointer": f"{list_name}[case={case}, attempt={attempt}]"},
             "limitation": limitation, "evidence": evidence}, "")


def decide(report, manifest, rows) -> dict:
    """The pure decision over one run report, one manifest and the triage rows as they stand. Nothing is read or
    written here. Every failure of `contract.triage_failures` lands in exactly one list:
      `write`       the code rows to add (each a failure with no row, in the state code decides);
      `by_code`     failures an existing code row answers;   `by_analyst` failures another row answers (untouched);
      `left`        failures left to the analyst, with `why` (a key -> sentence) for each;
      `unnamed`     the notes of failures that carry no name a row could answer to (left to the analyst, the S1 refusal
                    names them);
      `failures`    how many there are, unnamed included."""
    failures, unnamed = C.triage_failures(report)
    rows = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    bound = C.bind_triage(failures, rows)
    competing = {key for _names, keys in bound["ambiguous"] for key in keys}
    list_name, manual = failing_manual_rows(report if isinstance(report, dict) else {})
    held = contradicted(manifest)
    out = {"write": [], "by_code": [], "by_analyst": [], "left": [], "why": {}, "unnamed": list(unnamed),
           "failures": len(failures) + len(unnamed), "contradicted": bool(held[0] or held[1])}
    for key in failures:
        answers = bound["matched"].get(key) or []
        if answers:
            out["by_code" if all(is_code_row(r) for r in answers) else "by_analyst"].append(key)
            continue
        if key in competing:
            out["left"].append(key)
            out["why"][key] = "a row of the triage names it together with another failure"
            continue
        if key[0] != "manual":
            out["left"].append(key)
            out["why"][key] = "a red test is the analyst's to judge"
            continue
        row, why = _code_row(key, manual.get(key, []), list_name, held)
        if row:
            out["write"].append(row)
        else:
            out["left"].append(key)
            out["why"][key] = why
    return out


def rederives(row, report, manifest, rows=()) -> bool:
    """Would S7's code write THIS row again, from the live record? (t-305 N8, F2: the delivery verdict reads a
    `NOT_EXECUTED` row as "the person will check" only when this says yes.) Pure: `decide` over the report and the
    manifest, with the triage rows given in `rows` (default none) MINUS every row of code's own (`source: code`) - the
    row under test is never its own witness - must `write` a row with the same `instance_id`, `attempt_id` and
    `verdict`.

    ERROR DIRECTION: False is the cheap answer (the delivery says `no` and names the row); True is the forbidden one.
    A row or a report that is not an object, another attempt (a re-run since), a failure an analyst's row already
    answers, a `contradicts_requirement` row, an unvalidated record, a result failure, a manual `fail`: all False."""
    if not (isinstance(row, dict) and isinstance(report, dict)):
        return False
    analyst = [r for r in rows if isinstance(r, dict) and not is_code_row(r)] if isinstance(rows, (list, tuple)) else []
    try:
        out = decide(report, manifest, analyst)
    except Exception:
        return False
    for written in out["write"]:
        if (written.get("instance_id") == row.get("instance_id") and written.get("attempt_id") == row.get("attempt_id")
                and written.get("verdict") == row.get("verdict")):
            return True
    return False


def brief(left: list, unnamed: list, contradicted: bool = False) -> str:
    """The failures the analyst is told to triage, naming only the ones code left to it; `contradicted` keeps the
    driver's own reason for a manifest `contradicts_requirement` row (`failures_to_triage` says it the same way)."""
    parts = []
    results = [name for kind, name in left if kind == "result"]
    manual = [name for kind, name in left if kind == "manual"]
    if results:
        parts.append("failed results " + ", ".join(results))
    if manual:
        parts.append("manual " + ", ".join(manual))
    parts += [str(note) for note in unnamed]
    if contradicted:
        parts.append("contradicts_requirement rows")
    return "; ".join(parts)


def _triage_doc(path: Path) -> tuple:
    """`(doc, "")` for a triage the module may extend: the file is absent (an empty document), or an object whose
    `triage` is a list of objects. Anything else is `(None, why)` - the analyst's file is never overwritten by a guess."""
    if not path.exists():
        return {"schema_version": 2, "task_id": path.parent.parent.name, "triage": []}, ""
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None, f"{TRIAGE_REL} cannot be read as JSON"
    if not isinstance(doc, dict) or not isinstance(doc.get("triage"), list) \
            or any(not isinstance(r, dict) for r in doc["triage"]):
        return None, f"{TRIAGE_REL} is not an object with a `triage` list of rows"
    return doc, ""


def report_problem(task: Path) -> str:
    """"" when `work/run-report.json` reads as a run report, else the ONE text of the unreadable report: the sentence and
    the door `handoff_check` gives the analyst's form (t-323 B4/F2), so the driver and the form say the same thing."""
    import handoff_check as HC
    why = HC._report_unreadable(HC.Artifacts(task))
    return f"{why} - {HC.REPORT_TELL}. To go on: {HC.REPORT_DOOR}." if why else ""


def s6_closed_by_code(task_root) -> bool:
    """Did S6 close on a code-only receipt (the controller's own record: `stages.S6.code_only`)? Then a run report whose
    `execution_status` is `not_executed` is what S6 left on purpose - nothing to execute, or everything handed to a
    person - and S7 may read it (t-305 Q19). A controller that cannot be read says False: a doubt never opens S7."""
    try:
        from controller import Controller
        stage = (Controller(Path(task_root)).state().get("stages") or {}).get("S6") or {}
    except Exception:
        return False
    return stage.get("status") == "completed" and stage.get("code_only") is True


def pretriage(task_root) -> dict:
    """Read the run report, the manifest and the triage of one task; write the code rows `decide` asks for, once and
    atomically (`atomic_json`); say what is left. Idempotent: a second call finds the rows it wrote answering their
    failures and writes nothing. The driver calls it only while no S7 dispatch is in flight (the analyst writes the same
    file). Returns
      `written`  names of the failures a row was written for now;   `kept`  names every code row answers (new and old);
      `left`     {"results": [...], "manual": [...], "unnamed": [...]} - what the analyst is asked about;
      `analyst`  names the analyst's own rows answer;   `failures`  how many failures the report holds;
      `closes`   True when every failure is answered by a code row and nothing is left (S7 may close by code);
      `refused`  "" or the sentence saying what code could not do, with its door - then nothing was written;
      `notes`    lines for the driver's log."""
    task = Path(task_root)
    res = {"written": [], "kept": [], "left": {"results": [], "manual": [], "unnamed": []}, "analyst": [],
           "failures": 0, "closes": False, "contradicted": False, "refused": "", "notes": []}
    problem = report_problem(task)
    if problem:
        res["refused"] = "S7 pre-triage: " + problem + " Nothing was written."
        res["notes"].append(res["refused"])
        return res
    report = C.load_json(task / REPORT_REL)
    manifest = C.load_json(C.artifact(task, "automation-manifest.json"))
    triage_path = C.artifact_write_path(task, "triage.json")
    doc, unreadable = _triage_doc(triage_path)
    decision = decide(report, manifest, doc["triage"] if doc else [])
    refused = ""
    if unreadable:
        refused = (f"S7 pre-triage: {unreadable}, so code writes no row and the failure analyst triages every "
                   "failure; the analyst's form check names the file.")
    elif decision["write"] and VERDICT not in C.TRIAGE_VERDICTS:
        names = ", ".join(row["instance_id"] for row in decision["write"])
        refused = (f"S7 pre-triage: the verdict {VERDICT} is not in contract.TRIAGE_VERDICTS, so no row is written for "
                   f"the manual check(s) {names}; the failure analyst triages them. Expected: scripts/contract.py "
                   f"lists {VERDICT} in TRIAGE_VERDICTS, with its row in handoffs/vocabulary.yaml and its owner in "
                   "check_delivery.OWNER_BY_TRIAGE_VERDICT - the integrator's change; until it lands code writes nothing.")
    if refused:
        for row in decision["write"]:
            key = ("manual", row["instance_id"])
            decision["left"].append(key)
            decision["why"][key] = "code could write no row (see `refused`)"
        decision["write"] = []
        res["refused"] = refused
        res["notes"].append(refused)
    elif decision["write"]:
        doc["triage"] = doc["triage"] + decision["write"]
        atomic_json(triage_path, doc)
    res["written"] = [row["instance_id"] for row in decision["write"]]
    res["kept"] = [name for _kind, name in decision["by_code"]] + res["written"]
    res["analyst"] = [name for _kind, name in decision["by_analyst"]]
    res["failures"] = decision["failures"]
    res["left"] = {"results": [n for k, n in decision["left"] if k == "result"],
                   "manual": [n for k, n in decision["left"] if k == "manual"],
                   "unnamed": list(decision["unnamed"])}
    # a `contradicts_requirement` row anywhere in the manifest keeps the analyst, even for a case that is not failing now:
    # CASE_DEFECT is the analyst's alone, and the driver has always dispatched it for such a row (t-352 F1)
    res["contradicted"] = decision["contradicted"]
    res["closes"] = bool(decision["failures"] and res["kept"] and not decision["left"] and not decision["unnamed"]
                         and not decision["by_analyst"] and not decision["contradicted"])
    if res["written"]:
        res["notes"].append(f"pre-triage: {len(res['written'])} manual check(s) written by code as {VERDICT}: "
                            + ", ".join(res["written"]))
    left = len(decision["left"]) + len(decision["unnamed"])
    if res["kept"] and left:
        res["notes"].append(f"pre-triage: {left} failure(s) are left to the failure analyst")
    return res
