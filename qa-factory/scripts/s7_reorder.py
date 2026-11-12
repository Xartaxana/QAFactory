#!/usr/bin/env python3
"""s7_reorder.py - the bookkeeping of the S7 `reorder` round (t-1508 R7, steps R8/R9 inside).

A red test whose Thens after the red one are independent of it cannot answer for them: the asserts sit behind the red
one. The failure analyst marks the triage row `reorder: true` (rule 5 of its role, with `blocked_thens`); the author then
MOVES those asserts above the red one - the Then lines and the expected values unchanged, the test staying red at the
same Then - and a code critic reviews that one test. This script is the code between the two:

  s7_reorder.py start  --task <T> --instance <iid>   the snapshot of the test file BEFORE the round
                                                     (`work/s7-reorder/<iid>.json`, written by this script alone)
  s7_reorder.py finish --task <T> --instance <iid>   (a) the edit is only a move of lines of the test's function
                                                     (`variant_shape`); (b) the author's last `repair_verify` run of the
                                                     test, made on the CURRENT bytes, is RED; (c) the triage row is
                                                     carried to the new attempt (`carried_attempts`, `carried_by:
                                                     s7_reorder`); (d) the review of that one test is named, with its
                                                     reason and its brief.
  s7_reorder.py mark-fixed --task <T> --instance <iid>   the critic approved: `fix_result: fixed` on a row this script carried

The driver calls the functions; the conductor runs the commands (`phases/s7.md`, section Repair). Both register the author
and the critic the same way: `controller.py --operation rework --stage S5 --role qa-automator|qa-code-critic --cases <case>
--cause test_defect --reason "S7 reorder: <test>" | "S7 reorder review: <test>" --brief`. The driver's review of a repaired test
the critic had rejected is registered with `REPAIR_REVIEW_REASON` ("S7 repair review: <test>", `story_run.s7_review_repair`).

ERROR DIRECTION. A doubt is a refusal, never a carry: an unknown "before" (no snapshot), a function that cannot be found,
a line added, removed or moved out of the function, a run that is not new, a run on other bytes than the file holds now (or a
report row that carries no `instance_code_sha`), a run that is green are all refusals that name the fact and the door. A
carried row is the only thing this script writes to the triage, and only after (a) and (b) hold: the row never answers
another instance (`contract._attempt_fits` takes only an attempt id the failure itself has) and never a round that changed
what is asserted (a run that went over the bytes of a refused edit is not the run of a later clean move). Whether the new
place of the asserts is right is the critic's judgment (AR-2); the code judges the SHAPE of the edit and the colour of the run
(FR-58: it never reads what the test asserts).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract as C  # noqa: E402
import variant_shape as VS  # noqa: E402
from event_store import atomic_json  # noqa: E402
from hooklib import read_json as _read_json  # noqa: E402  (THE JSON reader, AR-13; None when nothing is there)

SNAPSHOT_DIR = "work/s7-reorder"
TRIAGE_REL = "work/triage.json"
REPORT_REL = "work/run-report.json"
CARRIED_BY = "s7_reorder"
PURPOSE = "repair_verify"
# the reasons the two dispatches are registered with: THE carrier of these words (nothing else reads them: `s5_precheck.
# is_s7_fix_round` knows only `S7 fix` and is False for both - the order of the asserts behind a test's own red is a finding
# in these rounds, K-R5-10)
AUTHOR_REASON = "S7 reorder: {test}"
REVIEW_REASON = "S7 reorder review: {test}"
# RD1-9b (t-593 F-7): the reason of the critic's review of a REPAIRED test the critic had rejected (`story_run.s7_review_repair`
# writes it; the same step replaced the `S7 fix` literal, AR-13). Not a reorder round, but the same kind of word: `is_s7_fix_round` is False.
REPAIR_REVIEW_REASON = "S7 repair review: {test}"


class ReorderRefused(ValueError):
    """The round cannot go on, or its result is not carried. `kind` names why for the caller that routes on it:
    `no_row`, `bad_row`, `no_test`, `no_snapshot`, `unreadable`, `unchanged`, `shape`, `no_run`, `green`."""

    def __init__(self, text: str, kind: str = ""):
        super().__init__(text)
        self.kind = kind


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def snapshot_path(task_root, iid: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", str(iid))[:80]
    return Path(task_root) / SNAPSHOT_DIR / f"{safe}-{hashlib.sha256(str(iid).encode('utf-8')).hexdigest()[:8]}.json"


def repo_of(task_root) -> Path:
    """The project the story lives in: the nearest folder above the story that carries `qa-factory/config.json` (the ONE walk,
    `runtime_paths.nearest_project`, AR-15) - never guessed from the shape of the path, because `artifact_root` is
    configurable (AR-4). No marker: a refusal that names the door, `--repo <project root>`."""
    from runtime_paths import nearest_project
    project = nearest_project(task_root)
    if project is None:
        raise ReorderRefused(f"no project marker (qa-factory/config.json) above {Path(task_root).name!r}, so the test file "
                             "cannot be found; name the project root with `--repo <path>`", "unreadable")
    return project


# --- the triage row -------------------------------------------------------------------------------------------------

def row_problems(row) -> list:
    """The problems of one triage row that asks for a `reorder`, each led by the row's name (`[]` when it asks for none, or is
    sound). A thin delegate: the rule is `contract.triage_reorder_problems`, the one reader the validator shares (AR-13)."""
    name = (C.row_names(row) or ["?"])[0]
    return [f"{name}: {p}" for p in C.triage_reorder_problems(row)]


def wants_reorder(row) -> bool:
    """The row asks for the reorder round (`reorder: true`). ONE predicate for the driver's rows and this script."""
    return isinstance(row, dict) and row.get("reorder") is True


def _triage(task_root) -> tuple:
    path = C.artifact_write_path(Path(task_root), "triage.json")
    doc = _read_json(path)
    rows = doc.get("triage") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        raise ReorderRefused(f"{TRIAGE_REL} holds no `triage` list, so the row of the test is unknown; the failure analyst "
                             "writes it again", "no_row")
    return path, doc, rows


def find_row(task_root, iid: str) -> tuple:
    """`(path, doc, row)` of the ONE triage row that names the instance `iid` and asks for `reorder`."""
    path, doc, rows = _triage(task_root)
    hits = [r for r in rows if isinstance(r, dict) and any(C.same_id(iid, n) for n in C.row_names(r))]
    if not hits:
        raise ReorderRefused(f"no row of {TRIAGE_REL} names the instance {iid!r}; the failure analyst writes the row first",
                             "no_row")
    asking = [r for r in hits if wants_reorder(r)]
    if not asking:
        raise ReorderRefused(f"the triage row of {iid!r} carries no `reorder: true`: the round moves asserts only when the "
                             "analyst asked for it (rule 5 of its role)", "no_row")
    if len(asking) > 1:
        raise ReorderRefused(f"{len(asking)} triage rows ask for a reorder of {iid!r}; keep one", "bad_row")
    problems = row_problems(asking[0])
    if problems:
        raise ReorderRefused(problems[0], "bad_row")
    return path, doc, asking[0]


# --- the test ----------------------------------------------------------------------------------------------------------

def _entry(task_root, iid: str) -> dict:
    """The manifest row of the test `iid` stands for (by its id or an alias), else a refusal naming the door."""
    manifest = C.load_json(C.artifact(Path(task_root), "automation-manifest.json"))
    entry = next((t for t in C.manifest_tests(manifest) if isinstance(t, dict)
                  and any(C.same_id(iid, n) for n in ({str(C.test_instance_id(t))} | set(C.instance_id_aliases(t))))), None)
    if entry is None:
        raise ReorderRefused(f"the manifest (work/automation-manifest.json) names no test {iid!r}: the automator records it "
                             "through manifest_put.py first", "no_test")
    return entry


def locate(task_root, iid: str) -> tuple:
    """`(relative path, function name, case)` of the manifest test `iid` stands for, from its `selector` (else `file` and
    `test`). A test the manifest does not name, or one with no node, is a refusal naming the door (`manifest_put.py`)."""
    entry = _entry(task_root, iid)
    node = str(entry.get("selector") or "").strip()
    if not node and entry.get("file") and entry.get("test"):
        node = f"{entry['file']}::{entry['test']}"
    path, sep, function = node.replace("\\", "/").rpartition("::")
    function = function.split("[", 1)[0].strip()
    if not (sep and path and function):
        raise ReorderRefused(f"the manifest row of {iid!r} names no test function (`selector` is {node!r}): the automator "
                             "records it through manifest_put.py", "no_test")
    cases = C.manifest_test_links(entry)
    return path.split("::", 1)[0], function, (cases[0] if cases else "")


def _read_test(repo: Path, rel: str) -> str:
    target = (Path(repo) / rel).resolve()
    if not target.is_relative_to(Path(repo).resolve()):
        raise ReorderRefused(f"{rel!r} leaves the project: the test file is a file of the project", "unreadable")
    try:
        return target.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ReorderRefused(f"the test file {rel!r} cannot be read as UTF-8 text ({type(exc).__name__}): a reorder is judged "
                             "line by line", "unreadable")


def verify_runs(task_root, iid: str) -> list:
    """`[(attempt_id, status, instance_code_sha)]` of the `repair_verify` runs of `iid` in the run report, in the order the
    report holds them. The history is read through `contract.instance_results` (AR-13); `instance_code_sha` is "" for a row
    that carries none (a report written before the field)."""
    report = _read_json(Path(task_root) / REPORT_REL)
    out = []
    for key, rows in (C.instance_results(report) if isinstance(report, dict) else {}).items():
        if not C.same_id(iid, key):
            continue
        for row in rows:
            if str(row.get("purpose") or "").lower() == PURPOSE and not row.get("stale"):
                out.append((str(row.get("attempt_id") or "").strip(), C.result_status(row),
                            str(row.get("instance_code_sha") or "").strip()))
    return out


def code_sha_now(task_root, iid: str, repo) -> str:
    """The `instance_code_sha` of the test as the file holds it NOW, measured by the producer's own measurer
    (`proof_level.instance_identity` -> `execution_request.instance_shas`, the derivation the run used, AR-15). "" when it
    cannot be measured: no stored run of the test, no readable file - the caller refuses then (error toward refusal)."""
    import proof_level
    try:
        got = proof_level.instance_identity(_entry(task_root, iid), Path(task_root), Path(repo))
    except Exception:
        return ""
    return str(((got or {}).get("instance_identity") or {}).get("instance_code_sha") or "")


# --- the briefs (one text for the driver and the conductor) ------------------------------------------------------------

def moved_thens(row: dict) -> list:
    """The Then numbers of the row's `blocked_thens`, in order and once each."""
    out: list = []
    for entry in row.get("blocked_thens") if isinstance(row.get("blocked_thens"), list) else []:
        number = C.then_number(entry.get("then")) if isinstance(entry, dict) else None
        if number and number not in out:
            out.append(number)
    return out


def red_thens(task_root, row: dict, iid: str) -> list:
    """The Thens the manifest names as red on this instance (`contradicts_requirement` rows), sorted; `[]` when none."""
    manifest = C.load_json(C.artifact(Path(task_root), "automation-manifest.json"))
    return sorted(C._red_thens_of(manifest, str(row.get("case") or ""), iid))


def author_brief(test: str, moved: list, red: list) -> list:
    """The lines the author of the round is told. It must PIN the Then rows of the reordered test, or the precheck reads the
    shared range as `red-own-order-unknown` in the round's own window (spec 5.7; critic t-1532)."""
    above = ", ".join(str(n) for n in moved) or "<the Thens in blocked_thens>"
    where = f"the red Then {', '.join(str(n) for n in red)}" if red else "the red Then"
    n = red[0] if red else "<n>"
    m = moved[0] if moved else "<m>"
    return [f"Reorder only {test}: move the asserts of Thens {above} above {where}; the Then-lines and the expected values stay "
            f"as they are; the test stays red at Then {n}. Re-run only this test (`--purpose {PURPOSE}`).",
            f"Pin the rows of the reordered test: on the marker give each Then its own line range "
            f"(`then={{{m}: \"a-b\", {n}: \"c-d\"}}`, a range per Then of the test), or the order cannot be established."]


def review_brief(test: str) -> list:
    return [f"Review only {test}: rubric dimension 6 (independent Thens before the red one) and that the asserts only moved, "
            "no Then text changed; probe the new bytes as for any changed test."]


def _registration(role: str, case: str, reason: str) -> str:
    return ("controller.py --operation rework --stage S5 --role " + role + " --cases " + (case or "<case>")
            + " --cause test_defect --reason " + json.dumps(reason) + " --brief")


# --- start / finish ------------------------------------------------------------------------------------------------------

def start(task_root, iid: str, repo=None) -> dict:
    """The snapshot of the test file before the round. A snapshot that is still OPEN (its round was refused, or has not
    finished) is KEPT - the round after a refusal is judged against the bytes before the FIRST attempt, so a refused edit that
    changed a Then line cannot become the new "before" (FR-59: an unknown before is never a carry). The runs seen so far are
    refreshed on a kept snapshot: a run made before this round began is never the run of the round."""
    task_root = Path(task_root)
    _path, _doc, row = find_row(task_root, iid)
    rel, function, case = locate(task_root, iid)
    repo = Path(repo) if repo else repo_of(task_root)
    target = snapshot_path(task_root, iid)
    kept = _read_json(target)
    seen = sorted({a for a, _s, _h in verify_runs(task_root, iid) if a})
    if isinstance(kept, dict) and kept.get("state") == "open" and kept.get("path") == rel and kept.get("function") == function:
        atomic_json(target, dict(kept, seen_attempts=sorted(set(kept.get("seen_attempts") or []) | set(seen))))
        return {"status": "kept", "snapshot": target.relative_to(task_root).as_posix(), "path": rel, "function": function,
                "case": case, "moved": moved_thens(row)}
    text = _read_test(repo, rel)
    snap = {"schema_version": 1, "instance_id": iid, "path": rel, "function": function, "case": case,
            "before_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "function_text": _function_text(text, function), "before_text": text,
            "seen_attempts": seen, "state": "open", "started_at": _now()}
    atomic_json(target, snap)
    return {"status": "started", "snapshot": target.relative_to(task_root).as_posix(), "path": rel, "function": function,
            "case": case, "moved": moved_thens(row)}


def _function_text(text: str, function: str) -> str:
    lines = text.splitlines()
    span = VS.function_span(lines, function)
    return "\n".join(lines[span[0]:span[1]]) if span else ""


def _shown(items: list, limit: int = 3) -> str:
    return "; ".join(f"line {i['line']}: {i['text'].strip()[:80]}" for i in items[:limit]) + (" ..." if len(items) > limit else "")


def finish(task_root, iid: str, repo=None) -> dict:
    """Judge the round and, when it holds, carry the triage row. Returns `{status: carried, attempt, critic: {reason, command,
    brief}}`; raises `ReorderRefused` otherwise (nothing is written then, the snapshot stays open)."""
    task_root = Path(task_root)
    target = snapshot_path(task_root, iid)
    snap = _read_json(target)
    if not isinstance(snap, dict) or snap.get("state") not in ("open", "carried") or not isinstance(snap.get("before_text"), str):  # sent_back too: start first
        raise ReorderRefused(f"no snapshot of the test {iid!r}: run `s7_reorder.py start --task {task_root.name} --instance "
                             f"{iid}` before the round, then the author's round, then `finish`. The factory does not know "
                             "what the file looked like before, so it carries nothing", "no_snapshot")
    if snap["state"] == "carried":
        raise ReorderRefused(f"the round of {iid!r} was already finished (attempt {snap.get('attempt')}); run `s7_reorder.py "
                             "start` for a new round", "no_snapshot")
    path, doc, row = find_row(task_root, iid)
    repo = Path(repo) if repo else repo_of(task_root)
    now = _read_test(repo, str(snap["path"]))
    if now == snap["before_text"]:
        raise ReorderRefused(f"the round changed nothing: {snap['path']} holds the bytes of the snapshot. The author moves the "
                             "asserts of the Thens in `blocked_thens` above the red one, then re-runs the test", "unchanged")
    shape = VS.variant_shape(snap["before_text"], now, str(snap["function"]))
    if not shape["function_found"]:
        raise ReorderRefused(f"a reorder only moves asserts: the function {snap['function']!r} is not found in {snap['path']}",
                             "shape")
    if shape["added"] or shape["removed"] or shape["outside"] or not shape["moved"]:
        what = (f"added {_shown(shape['added'])}" if shape["added"] else f"removed {_shown(shape['removed'])}" if shape["removed"]
                else f"changed lines outside {snap['function']}" if shape["outside"] else "moved no line")
        raise ReorderRefused(f"a reorder only moves asserts: the edit {what}. The Then lines and the expected values stay as "
                             f"they are and nothing outside {snap['function']} changes; restore the file to the snapshot "
                             "bytes and move the asserts only", "shape")
    fresh = [r for r in verify_runs(task_root, iid) if r[0] not in set(snap.get("seen_attempts") or [])]
    door = (f"re-run only this test on the new bytes (`run_suite.py --mine <case> --node-id <test> --purpose {PURPOSE}`), "
            "then finish")
    if not fresh:
        raise ReorderRefused(f"no new `{PURPOSE}` run of {iid!r} in {REPORT_REL}: {door}", "no_run")
    # the run must have gone over the bytes the file holds NOW: a row of the report that names other bytes (the refused edit
    # of an earlier round) or none at all (a report from before the field) answers nothing here
    now_sha = code_sha_now(task_root, iid, repo)
    runs = [r for r in fresh if now_sha and r[2] == now_sha]
    if not runs:
        why = ("the code identity of the test cannot be measured now" if not now_sha else
               "no new run went over these bytes (the runs " + ", ".join(r[0] or "unnamed" for r in fresh) + " name other "
               "bytes, or none)")
        raise ReorderRefused(f"the `{PURPOSE}` run of {iid!r} does not stand for the file as it is now: {why}; {door}", "no_run")
    attempt, status, _sha = runs[-1]
    if status in ("passed", "pass"):
        raise ReorderRefused("a reorder never turns a red by a product bug green; the round changed what is asserted. The "
                             "test passes on the new bytes, so its red Then was moved out of the way or its expectation "
                             "changed: nothing is carried and the round is stopped", "green")
    if status not in ("failed", "error") or not attempt:
        raise ReorderRefused(f"the last `{PURPOSE}` run of {iid!r} is {status or 'unreadable'} (attempt {attempt or 'unnamed'}), "
                             "not a red one: a row is carried only to a red attempt the report names", "no_run")
    carried = [a for a in (row.get("carried_attempts") if isinstance(row.get("carried_attempts"), list) else [])
               if isinstance(a, str) and a.strip()]
    if attempt not in carried:
        carried.append(attempt)
    row["carried_attempts"] = carried
    row["carried_by"] = CARRIED_BY
    atomic_json(path, doc)
    atomic_json(target, dict(snap, state="carried", attempt=attempt, finished_at=_now(),
                             after_sha256=hashlib.sha256(now.encode("utf-8")).hexdigest()))
    return _carried_result(snap, row, iid, attempt)


def _carried_result(snap: dict, row: dict, iid: str, attempt: str) -> dict:
    """What a carried round hands on: the attempt and the registration of the critic of that one test."""
    case = str(snap.get("case") or row.get("case") or "")
    test = str(row.get("test") or iid)
    return {"status": "carried", "attempt": attempt, "case": case,
            "critic": {"reason": REVIEW_REASON.format(test=test), "command": _registration("qa-code-critic", case,
                       REVIEW_REASON.format(test=test)), "brief": review_brief(test)}}


def carried_round(task_root, iid: str, repo=None):
    """The result of a round that was carried and not yet judged, or None. A driver that fell after `finish` and before the
    critic's verdict comes back here: the author is NOT dispatched again over the bytes of the round, only the critic is
    (AR-25). Only a round whose snapshot says `carried`, whose file holds the bytes of that moment and whose row is carried by
    this script to that attempt with no `fix_result` yet counts; any doubt is None, a new round (`start`)."""
    task_root = Path(task_root)
    snap = _read_json(snapshot_path(task_root, iid))
    if not (isinstance(snap, dict) and snap.get("state") == "carried" and snap.get("attempt") and snap.get("after_sha256")):
        return None
    try:
        row = find_row(task_root, iid)[2]
        now = _read_test(Path(repo) if repo else repo_of(task_root), str(snap["path"]))
    except ReorderRefused:
        return None
    if (row.get("carried_by") != CARRIED_BY or row.get("fix_result") or snap["attempt"] not in (row.get("carried_attempts") or [])
            or hashlib.sha256(now.encode("utf-8")).hexdigest() != snap["after_sha256"]):
        return None
    return _carried_result(snap, row, iid, str(snap["attempt"]))


def send_back(task_root, iid: str) -> bool:
    """The critic sent a carried round back: its snapshot is closed (`sent_back`), so the next round starts afresh and the
    carried round is never resumed as if it had not been judged. False when there is no carried snapshot."""
    target = snapshot_path(task_root, iid)
    snap = _read_json(target)
    if not (isinstance(snap, dict) and snap.get("state") == "carried"):
        return False
    atomic_json(target, dict(snap, state="sent_back"))
    return True


def mark_fixed(task_root, iid: str) -> bool:
    """The critic approved the carried reorder: the row of `iid` gets `fix_result: fixed` (the driver's loop calls this; the
    analyst's role never writes it for a reorder). Only a row that asks for `reorder` AND was carried by this script is marked;
    anything else is left alone and False is returned (FR-59: no carry, no mark)."""
    path, doc, rows = _triage(task_root)
    done = False
    for r in rows:
        if (isinstance(r, dict) and wants_reorder(r) and r.get("carried_by") == CARRIED_BY
                and any(C.same_id(iid, n) for n in C.row_names(r))):
            r["fix_result"] = "fixed"
            done = True
    if done:
        atomic_json(path, doc)
    return done


# --- the command line --------------------------------------------------------------------------------------------------

def main(argv=None) -> int:
    import hooklib
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("mode", choices=("start", "finish", "mark-fixed"))
    parser.add_argument("--task", help="the story's ticket key")
    parser.add_argument("--task-root", help="the story's folder")
    parser.add_argument("--instance", required=True, help="the instance id of the red test (manifest tests[])")
    parser.add_argument("--repo", help="the project root (default: the project of the story)")
    args = hooklib.exact_options(parser).parse_args(argv)
    task_root = hooklib.story_cli("s7_reorder.py", key=args.task, root=args.task_root)
    try:
        if args.mode == "start":
            result = start(task_root, args.instance, args.repo)
            row = find_row(task_root, args.instance)[2]
            red = red_thens(task_root, row, args.instance)
            test = str(row.get("test") or args.instance)
            result["author"] = {"reason": AUTHOR_REASON.format(test=test),
                                "command": _registration("qa-automator", result["case"], AUTHOR_REASON.format(test=test)),
                                "brief": author_brief(test, moved_thens(row), red)}
        elif args.mode == "mark-fixed":
            if not mark_fixed(task_root, args.instance):
                raise ReorderRefused(f"the row of {args.instance!r} is not a reorder row carried by this script, so it is not "
                                     "marked: run `s7_reorder.py finish` first", "no_row")
            result = {"status": "marked", "instance": args.instance}
        else:
            result = finish(task_root, args.instance, args.repo)
    except ReorderRefused as exc:
        print(f"s7_reorder.py {args.mode}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
