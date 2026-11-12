"""S6-S9: judge questions over failures, bug drafts, a manual observation, a retro trap and a
ticket diff - the later-stage half of the judge (S1-S4 live in judge_requirements.py/judge_cases.py).

Two forms write a file the next role reads first, mirroring judge_cases.py's contract:

  judge_results.py --task-root qa-factory/artifacts/<T> --triage   -> work/judge-triage.json
  judge_results.py --task-root qa-factory/artifacts/<T> --bugs     -> work/judge-bugs.json

`--triage` reads every failed row of `work/run-report.json` and gives qa-failure-analyst a
first sort (`result_triage_verdict`) plus two narrower checks (`result_case_defect`,
`result_flaky_mechanism` once 3 reruns exist) before the analyst opens the evidence itself.
`APP_BUG` is never a decided value here, whatever its confidence: only a person or the
analyst confirms it (s7.md 2b/7), so a winning `APP_BUG` answer is written back with
`decided: false` and its raw choice kept under `leaning` so the analyst still sees it.

`--bugs` reads every `work/bug-drafts/*.json` against the project's own `bugs/*.md` for a
dedup hint (`result_bug_duplicate`) and a first severity guess from the damage line
(`result_bug_priority`, advisory only - a score, never a status a validator could enforce).

Three one-shot forms print one decision to stdout and write no file, the same shape as
`judge_form.py --reason`/`judge_code.py --cause` (Packages A/C): a single small state, a
single registered question, JSON out. None of them take `--task-root`; `--project-root`
is accepted only for tests and defaults to the caller's own working directory, because the
orchestrator always runs these from inside the project:

  judge_results.py --observation --then "<text>" --observed "<text>"
  judge_results.py --trap "<paragraph>"
  judge_results.py --ticket-diff --old <old-file> --new <new-file>

Every call: `judge.provider: none` -> nothing is asked, nothing is written, exit 0 (`off`).
`mode: shadow` -> answers are journalled and printed, nothing acts on them. `mode: on` -> a
decided answer is the one the caller (a role, or a future story_step.py pre-work step) may
act on; an undecided one goes exactly where it would go without a judge. Exit 0 on
`ok`/`off`, 3 when the judge was wanted and unavailable - the fallback is always "the role
does it as before", never a halt.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract  # noqa: E402
import hooklib  # noqa: E402
import judge  # noqa: E402
import ticket_adapter  # noqa: E402
from hooklib import sorted_paths  # noqa: E402

SECTION = re.compile(r"^##\s+(.+?)\s*$", re.M)
ERROR_LINE = re.compile(r"error|assert|exception|traceback|timeout", re.I)
ERROR_HEAD_LINES = 25
STATE_TEXT_LIMIT = 2500
MAX_BUG_PAIRS = 200


def _trim(text: str, limit: int = STATE_TEXT_LIMIT) -> str:
    return (text or "")[:limit]


# --- --triage ------------------------------------------------------------------------------

def _failed_rows(report: dict) -> list:
    """The result rows to triage: the failing ones `contract.triage_targets` names - the ONE definition of "a failure
    that needs triage" the driver, the reducer, the S7 check and gate B read (t-319, critic t-312 F5: this was the
    fifth reading, a raw `status in (failed, error)` tuple over `current_results or results`, so an EMPTY current
    view - everything repaired - fell back to the history and sorted failures that no longer exist).

    Read from the `current_results` list when finalize_task.py wrote one, even an empty one (it wins), else from
    the contract's own projection of the legacy `results`. A failing row with no name is still a row to sort (it is
    a failure with no id, `triage_targets` says so under `unnamed`). Manual checks are not rows here: they carry no
    attempt and no evidence folder for the sort to read, so the analyst opens them as before."""
    rows = report.get("current_results")
    if not isinstance(rows, list):
        rows = list(contract.current_instance_results(report).values())
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        got = contract.triage_targets({"current_results": [row]})
        if got["results"] or got["unnamed"]:
            out.append(row)
    return out


def _rerun_count(report: dict, row: dict) -> int:
    key = row.get("instance_id") or row.get("test_id")
    if not key:
        return 0
    pool = report.get("results") or []
    return sum(1 for r in pool if isinstance(r, dict)
               and (r.get("instance_id") or r.get("test_id")) == key)


def _case_id_of(row: dict) -> str:
    for link in row.get("case_version_links") or []:
        if isinstance(link, dict) and link.get("case_id"):
            return str(link["case_id"])
    for case in contract.case_ids(row.get("case")):
        return case
    return ""


def _find_case_file(task_root: Path, case_id: str) -> Path | None:
    if not case_id:
        return None
    base = task_root / "work/test-cases"
    if not base.is_dir():
        return None
    from s5_precheck import case_files_named  # strict by name on every platform (t-911); lazy: a hook path stays light
    candidates = case_files_named(base, case_id, prefix=True)
    for path in candidates:
        front = hooklib.parse_frontmatter(path.read_text(encoding="utf-8")) or {}
        if str(front.get("id") or path.stem).upper() == case_id.upper():
            return path
    return candidates[0] if candidates else None


def _case_view(task_root: Path, case_id: str) -> dict:
    """{"then": ..., "requirement_ref": ...} for one pinned case - the Then text a triage row
    is judged against, and the `basis`/`covers` this row's requirement text is filed under."""
    path = _find_case_file(task_root, case_id)
    if not path:
        return {"then": "", "requirement_ref": ""}
    text = path.read_text(encoding="utf-8")
    front = hooklib.parse_frontmatter(text) or {}
    body = text.split("\n---", 1)[-1] if text.startswith("---") else text
    parts = SECTION.split(body)
    sections = {parts[i].strip().lower(): parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    return {"then": _trim(sections.get("then", "")),
            "requirement_ref": str(front.get("basis") or front.get("covers") or "")}


def _requirement_text(task_root: Path, ref: str) -> str:
    """The register row a case's `basis`/`covers` names (`requirement:R-n` or bare `R-n`),
    read the same way judge_requirements.read_register does - the Register table only."""
    match = re.search(r"R-?\d+[a-z]?", ref or "", re.I)
    if not match:
        return ""
    register = task_root / "work/requirements-register.md"
    if not register.is_file():
        return ""
    rid = match.group(0).upper()
    row = re.compile(r"^\|\s*(" + re.escape(rid) + r")\s*\|\s*(.+?)\s*\|", re.I)
    inside = False
    for line in register.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            inside = line.strip().lower() == "## register"
            continue
        m = row.match(line) if inside else None
        if m:
            return _trim(m.group(2), 1200)
    return ""


def _manifest_entry(manifest: dict, row: dict, case_id: str) -> dict:
    instance = row.get("instance_id") or ""
    for entry in manifest.get("tests") or []:
        if not isinstance(entry, dict):
            continue
        selector = str(entry.get("selector") or "")
        links = contract.manifest_test_links(entry)
        if (instance and instance in selector) or (case_id and case_id in links):
            return {"file": entry.get("file"), "selector": entry.get("selector"),
                    "status": entry.get("status"), "note": _trim(entry.get("note") or "", 500)}
    return {}


def _error_head(task_root: Path, attempt_id: str, max_lines: int = ERROR_HEAD_LINES) -> str:
    if not attempt_id:
        return ""
    folder = task_root / "evidence/runs" / attempt_id
    if not folder.is_dir():
        return ""
    logs = sorted_paths(folder.glob("*.log"))
    if not logs:
        return ""
    lines = logs[-1].read_text(encoding="utf-8", errors="replace").splitlines()
    for i, line in enumerate(lines):
        if ERROR_LINE.search(line):
            start = max(0, i - 5)
            return _trim("\n".join(lines[start:start + max_lines]))
    return _trim("\n".join(lines[:max_lines]))


def run_triage(task_root: Path) -> dict:
    cfg = judge.settings(task_root)
    report = {"provider": cfg["provider"], "mode": cfg["mode"], "status": "ok"}
    if not judge.active(cfg):
        return dict(report, status="off")
    run_report = hooklib.read_json(task_root / "work/run-report.json")
    if run_report is None:
        return dict(report, status="not_ready", reason="work/run-report.json is not written yet")
    rows = _failed_rows(run_report)
    manifest = hooklib.read_json(task_root / "work/automation-manifest.json") or {}
    requests, meta = [], []
    for row in rows:
        case_id = _case_id_of(row)
        case_view = _case_view(task_root, case_id)
        requirement = _requirement_text(task_root, case_view["requirement_ref"])
        state = {"test": row.get("test_id") or row.get("instance_id") or "",
                 "error_head": _error_head(task_root, row.get("attempt_id") or ""),
                 "assertion": _trim(str(row.get("reason") or ""), 800),
                 "then": case_view["then"],
                 "manifest_row": _manifest_entry(manifest, row, case_id)}
        reruns = _rerun_count(run_report, row)
        info = {"test": state["test"], "case": case_id, "instance_id": row.get("instance_id"),
                "reruns": reruns}
        requests.append((state, {"verdict": {"judgment": "result_triage_verdict"}}))
        meta.append({**info, "kind": "verdict"})
        if requirement:
            # `result_case_defect` reads the requirement text directly (its own small state),
            # never through the shared triage state - the calibration rule every S2/S4
            # judgment above already learned the hard way.
            requests.append(({"then": state["then"], "requirement": requirement},
                             {"case_defect": {"judgment": "result_case_defect"}}))
            meta.append({**info, "kind": "case_defect"})
        if reruns >= contract.FLAKY_MIN_RERUNS:
            key = row.get("instance_id") or row.get("test_id")
            pool = [r for r in (run_report.get("results") or [])
                    if isinstance(r, dict) and (r.get("instance_id") or r.get("test_id")) == key]
            reruns_state = [{"status": r.get("status"), "error_head": _trim(str(r.get("reason") or ""), 400)}
                           for r in pool[-6:]]
            requests.append(({"reruns": reruns_state}, {"flaky": {"judgment": "result_flaky_mechanism"}}))
            meta.append({**info, "kind": "flaky_mechanism"})
    if not requests:
        report.update(rows=0, results=[])
        (task_root / "work/judge-triage.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return report
    replies = judge.ask_many(requests, workers=8, ticket=task_root.name, stage="S7",
                             project_root=task_root, cfg=cfg)
    failed = next((r for r in replies if r["status"] != "ok"), None)
    if failed:
        return dict(report, status=failed["status"], reason=failed.get("reason"))
    by_test: dict = {}
    for info, reply in zip(meta, replies):
        key = (info["test"], info["instance_id"])
        row_out = by_test.setdefault(key, {"test": info["test"], "case": info["case"],
                                           "instance_id": info["instance_id"], "reruns": info["reruns"]})
        if info["kind"] == "verdict":
            answer = dict(reply["answers"].get("verdict") or {})
            # APP_BUG is a leaning, never a decision, from this script - only a person or
            # the failure analyst confirms it (s7.md 2b/7). Confidence never overrides that.
            if answer.get("leaning") == "APP_BUG" or answer.get("value") == "APP_BUG":
                answer["value"], answer["decided"] = None, False
            row_out["verdict"] = answer
        elif info["kind"] == "case_defect":
            row_out["case_defect"] = reply["answers"].get("case_defect")
        elif info["kind"] == "flaky_mechanism":
            row_out["flaky_mechanism"] = reply["answers"].get("flaky")
    results = list(by_test.values())
    report.update(rows=len(rows), results=results,
                  advisory=replies[0]["advisory"] if replies else True,
                  input_tokens=sum(r.get("input_tokens") or 0 for r in replies))
    (task_root / "work/judge-triage.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def render_triage(report: dict) -> str:
    if report["status"] != "ok":
        return (f"judge_results --triage: {report['status']} - "
                f"{report.get('reason') or 'judge.provider is none'}; triage as usual")
    decided = sum(1 for r in report["results"] if (r.get("verdict") or {}).get("decided"))
    return (f"judge_results --triage: mode={report['mode']} {report['rows']} failed rows - "
            f"{decided} verdicts decided (APP_BUG is always left undecided here) -> "
            "work/judge-triage.json")


# --- --bugs ----------------------------------------------------------------------------

def _project_bugs_dir(task_root: Path) -> Path:
    # task_root is qa-factory/artifacts/<TICKET>; bugs live at qa-factory/bugs, two levels up.
    return task_root.parent.parent / "bugs"


def _existing_bug_view(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    front = hooklib.parse_frontmatter(text) or {}
    body = text.split("\n---", 1)[-1] if text.startswith("---") else text
    parts = SECTION.split(body)
    sections = {parts[i].strip().lower(): parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    return {"title": front.get("title"), "area": front.get("area"),
            "expected": _trim(sections.get("expected result", ""), 800),
            "actual": _trim(sections.get("actual result", ""), 800)}


def _draft_area(task_root: Path, draft: dict) -> str:
    """A bug draft carries no `area` field of its own (`artifact-contract-results.md`'s
    draft shape does not have one); the case it names does, as the folder its file lives
    under (`work/test-cases/<area>/<case id>.md`). Leaving this empty would read to the judge as
    a real mismatch against an existing bug's own `area` frontmatter, not as "unknown"."""
    path = _find_case_file(task_root, str(draft.get("case") or ""))
    return path.parent.name if path else ""


def _draft_view(task_root: Path, draft: dict) -> dict:
    return {"title": draft.get("title"), "area": _draft_area(task_root, draft),
            "expected": _trim(str(draft.get("expected") or ""), 800),
            "actual": _trim(str(draft.get("actual") or ""), 800)}


def _damage_line(draft: dict) -> str:
    """What the user loses, in prose - never the draft's own pre-classified `impact` word,
    which would just hand the judge the label it is asked to reproduce."""
    title = str(draft.get("title") or "")
    actual = str(draft.get("actual") or "")
    return _trim(f"{title}. {actual}".strip(". "), 800)


def run_bugs(task_root: Path) -> dict:
    cfg = judge.settings(task_root)
    report = {"provider": cfg["provider"], "mode": cfg["mode"], "status": "ok"}
    if not judge.active(cfg):
        return dict(report, status="off")
    import bug_records as BR   # the one reader of the draft folder (G1-9)
    drafts = BR.draft_paths(task_root)
    if not drafts:
        report.update(drafts=0, results=[])
        (task_root / "work/judge-bugs.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return report
    bugs_dir = _project_bugs_dir(task_root)
    existing = sorted_paths(bugs_dir.glob("BUG-*.md")) if bugs_dir.is_dir() else []
    requests, meta = [], []
    pairs_used = 0
    for draft_path in drafts:
        draft = hooklib.read_json(draft_path) or {}
        draft_view = _draft_view(task_root, draft)
        requests.append(({"damage": _damage_line(draft)}, {"priority": {"judgment": "result_bug_priority"}}))
        meta.append({"draft": draft_path.name, "kind": "priority"})
        for bug_path in existing:
            if pairs_used >= MAX_BUG_PAIRS:
                break
            requests.append(({"draft": draft_view, "existing_bug": _existing_bug_view(bug_path)},
                             {"dup": {"judgment": "result_bug_duplicate"}}))
            meta.append({"draft": draft_path.name, "kind": "duplicate", "bug": bug_path.stem})
            pairs_used += 1
    replies = judge.ask_many(requests, workers=8, ticket=task_root.name, stage="S8",
                             project_root=task_root, cfg=cfg)
    failed = next((r for r in replies if r["status"] != "ok"), None)
    if failed:
        return dict(report, status=failed["status"], reason=failed.get("reason"))
    by_draft: dict = {}
    for info, reply in zip(meta, replies):
        row = by_draft.setdefault(info["draft"], {"draft": info["draft"], "duplicates": []})
        if info["kind"] == "priority":
            row["priority"] = reply["answers"].get("priority")
        else:
            answer = reply["answers"].get("dup") or {}
            if answer.get("value") is True or (answer.get("probability") or 0) >= 0.5:
                row["duplicates"].append({"bug": info["bug"], "decision": answer})
    report.update(drafts=len(drafts), results=list(by_draft.values()),
                  advisory=replies[0]["advisory"] if replies else True,
                  input_tokens=sum(r.get("input_tokens") or 0 for r in replies))
    (task_root / "work/judge-bugs.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def render_bugs(report: dict) -> str:
    if report["status"] != "ok":
        return (f"judge_results --bugs: {report['status']} - "
                f"{report.get('reason') or 'judge.provider is none'}; dedup and score as usual")
    dups = sum(len(r.get("duplicates") or []) for r in report["results"])
    return (f"judge_results --bugs: mode={report['mode']} {report['drafts']} drafts - "
            f"{dups} possible duplicate(s) flagged -> work/judge-bugs.json")


# --- one-shot forms ----------------------------------------------------------------------

def one_shot(judgment_id: str, key: str, state: dict, project_root) -> dict:
    cfg = judge.settings(project_root)
    if not judge.active(cfg, judgment_id):
        return {"status": "off", "reason": "judge.provider is none" if cfg["provider"] == "none"
                else f"{judgment_id} is disabled", "decision": None}
    reply = judge.ask(state, {key: {"judgment": judgment_id}}, project_root=project_root, cfg=cfg)
    if reply["status"] != "ok":
        return {"status": reply["status"], "reason": reply.get("reason"), "decision": None}
    return {"status": "ok", "advisory": reply["advisory"], "decision": reply["answers"].get(key)}


def cmd_observation(then_text: str, observed_text: str, project_root) -> dict:
    return one_shot("result_observation_matches_then", "q",
                    {"then": _trim(then_text), "observed": _trim(observed_text)}, project_root)


def cmd_trap(paragraph: str, project_root) -> dict:
    return one_shot("result_trap_owner", "q", {"trap": _trim(paragraph)}, project_root)


def _trimmed_detail(detail: dict, limit: int = 3000) -> dict:
    """`diff["detail"]` cut down to what a small state can carry - whole fields, in order,
    stopping once the running size would cross `limit` rather than truncating one mid-value."""
    out, used = {}, 0
    for key, value in detail.items():
        text = json.dumps(value, ensure_ascii=False)
        if out and used + len(text) > limit:
            break
        out[key] = value
        used += len(text)
    return out


def cmd_ticket_diff(old_path: Path, new_path: Path, project_root) -> dict:
    diff = ticket_adapter.diff_tickets(old_path, new_path)
    out = {"code_severity": diff["severity"], "changed": diff["changed"]}
    if not diff["changed"]:
        out.update(status="off", reason="ticket unchanged", decision=None, severity=diff["severity"])
        return out
    state = {"changed": diff["changed"], "detail": _trimmed_detail(diff["detail"])}
    result = one_shot("result_ticket_change_severity", "q", state, project_root)
    out.update(result)
    decision = result.get("decision")
    cfg = judge.settings(project_root)
    if decision and decision.get("decided") and cfg["mode"] == "on":
        out["severity"] = decision["value"]
    else:
        out["severity"] = diff["severity"]
    return out


# --- CLI -----------------------------------------------------------------------------------

def main() -> int:
    contract.force_utf8()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--task-root")
    parser.add_argument("--project-root", help="one-shot forms only; defaults to the working directory")
    parser.add_argument("--triage", action="store_true")
    parser.add_argument("--bugs", action="store_true")
    parser.add_argument("--observation", action="store_true")
    parser.add_argument("--then")
    parser.add_argument("--observed")
    parser.add_argument("--trap")
    parser.add_argument("--ticket-diff", action="store_true")
    parser.add_argument("--old")
    parser.add_argument("--new")
    parser.add_argument("--json", action="store_true")
    args = hooklib.exact_options(parser).parse_args()
    if args.task_root is not None:      # a GIVEN root names an existing story, even when the judge is off (E-4)
        hooklib.story_cli("judge_results.py", root=args.task_root, key_flag=None)

    if args.triage or args.bugs:
        if not args.task_root:
            parser.error("--triage/--bugs need --task-root")
        task_root = Path(args.task_root).resolve()
        report = run_triage(task_root) if args.triage else run_bugs(task_root)
        render = render_triage if args.triage else render_bugs
        print(json.dumps(report, indent=2, ensure_ascii=False) if args.json else render(report))
        return 0 if report["status"] in ("ok", "off") else 3

    if args.observation:
        if args.then is None or args.observed is None:
            parser.error("--observation needs --then and --observed")
        result = cmd_observation(args.then, args.observed, args.project_root)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["status"] in ("ok", "off") else 3

    if args.trap is not None:
        result = cmd_trap(args.trap, args.project_root)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["status"] in ("ok", "off") else 3

    if args.ticket_diff:
        if not args.old or not args.new:
            parser.error("--ticket-diff needs --old and --new")
        result = cmd_ticket_diff(Path(args.old), Path(args.new), args.project_root)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["status"] in ("ok", "off") else 3

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
