"""S1: per hunk of the implementation diff, ask which acceptance criterion it relates to.

The live run this plan analyses spent a scout's reading budget on 360 KB of UI diff for one
story. This script does the looking in code - `diff_pass.parse` splits every hunk of
`work/impl-diff-*.txt` the story's `context-manifest.json` names - and puts one small state per
hunk (the hunk text plus the story's own AC list, nothing shared or looked up) to `disc_hunk_relates`.
A decided `unrelated` or `infrastructure` hunk is written to `work/judge-diff.json` for the
scout to skip; every other hunk (undecided, or matched to an AC) is read as usual - this is a
skip list, never a keep list, so an unreachable judge changes nothing.

  judge_diff.py --task-root qa-factory/artifacts/<TICKET> [--ticket T] [--json]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import diff_pass  # noqa: E402
import hooklib  # noqa: E402
import judge  # noqa: E402

MAX_HUNK_LINES = 40
MAX_HUNKS = 80


def _ac_entries(manifest: dict) -> list:
    """[(id, text), ...] - the register may hold plain strings ("AC-1: ...") or the newer
    {id, source, text} objects; both are read the same way here."""
    out = []
    for index, item in enumerate(manifest.get("acceptance_criteria") or [], 1):
        if isinstance(item, dict):
            ac_id = str(item.get("id") or f"AC-{index}").strip()
            text = str(item.get("text") or "")
        else:
            text = str(item)
            ac_id = text.split(":", 1)[0].strip() if ":" in text else f"AC-{index}"
        out.append((ac_id, text))
    return out


def _ac_criteria(entries: list) -> dict:
    criteria = {ac_id: text for ac_id, text in entries}
    criteria["infrastructure"] = ("Build, config, dependency, formatting, generated output or "
                                  "test-framework plumbing with no behaviour of its own.")
    criteria["unrelated"] = "Changes behaviour or code that none of the listed acceptance criteria describes."
    return criteria


def _hunk_text(file_path: str, hunk: dict) -> str:
    lines = [f"--- {file_path} {hunk['header']}".strip()]
    shown = hunk["lines"][:MAX_HUNK_LINES]
    for _n, sign, text in shown:
        lines.append(f"{sign}{text}")
    left = len(hunk["lines"]) - len(shown)
    if left > 0:
        lines.append(f"... {left} more line(s), not shown")
    return "\n".join(lines)


def _diff_files(manifest: dict, task_root: Path) -> list:
    """Every diff_path the manifest names, resolved the way context_bundle.py resolves them
    (relative to the qa-factory project root) with a fallback to work/<basename> for a
    fixture or an older manifest that names the file bare."""
    impls = manifest.get("implementations") or []
    if not impls and isinstance(manifest.get("implementation"), dict):
        impls = [manifest["implementation"]]
    project_root = task_root.parent.parent
    paths = []
    for impl in impls:
        raw = impl.get("diff_path") if isinstance(impl, dict) else None
        if not raw:
            continue
        candidate = Path(raw)
        if candidate.is_absolute() and candidate.is_file():
            paths.append(candidate)
            continue
        by_project = project_root / candidate
        if by_project.is_file():
            paths.append(by_project)
            continue
        by_work = task_root / "work" / candidate.name
        if by_work.is_file():
            paths.append(by_work)
    return paths


def run(task_root: Path, ticket=None, cfg: dict | None = None) -> dict:
    cfg = cfg or judge.settings(task_root)
    report = {"provider": cfg["provider"], "mode": cfg["mode"], "hunks": 0, "unrelated": 0,
             "infrastructure": 0, "results": [], "status": "ok"}
    if not judge.active(cfg, "disc_hunk_relates"):
        report["status"] = "off"
        return report
    manifest_path = task_root / "work" / "context-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        report.update(status="not_ready", reason=f"context-manifest.json: {exc}")
        return report
    entries = _ac_entries(manifest)
    if not entries:
        report.update(status="not_ready", reason="no acceptance_criteria in context-manifest.json yet")
        return report
    criteria = _ac_criteria(entries)
    ac_list = [text for _id, text in entries]
    jobs = []
    for diff_path in _diff_files(manifest, task_root):
        try:
            text = diff_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for file_entry in diff_pass.parse(text):
            for hunk in file_entry["hunks"]:
                if len(jobs) >= MAX_HUNKS:
                    break
                state = {"acceptance_criteria": ac_list, "hunk": _hunk_text(file_entry["path"], hunk)}
                jobs.append((state, file_entry["path"], hunk["header"]))
            if len(jobs) >= MAX_HUNKS:
                break
    if not jobs:
        report.update(status="not_ready", reason="no diff hunks found under the manifest's diff_path(s)")
        return report
    replies = judge.ask_many(
        [(state, {"relates": {"judgment": "disc_hunk_relates", "criteria": criteria}}) for state, _p, _h in jobs],
        ticket=ticket, stage="S1", project_root=task_root, cfg=cfg)
    for (_state, path, header), reply in zip(jobs, replies):
        if reply["status"] != "ok":
            report.update(status=reply["status"], reason=reply.get("reason"))
            return report
        decision = reply["answers"].get("relates") or {}
        row = {"path": path, "header": header[:120], "relates": decision.get("value"),
              "leaning": decision.get("leaning"), "confidence": decision.get("confidence"),
              "decided": bool(decision.get("decided"))}
        report["hunks"] += 1
        if row["decided"] and row["relates"] == "unrelated":
            report["unrelated"] += 1
        elif row["decided"] and row["relates"] == "infrastructure":
            report["infrastructure"] += 1
        report["results"].append(row)
    out_path = task_root / "work" / "judge-diff.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def render(report: dict) -> str:
    if report["status"] != "ok":
        return (f"judge_diff: {report['status']} - {report.get('reason') or 'judge.provider is none'}; "
                "read every hunk as usual")
    lines = [f"judge_diff: mode={report['mode']} hunks={report['hunks']} "
            f"unrelated={report['unrelated']} infrastructure={report['infrastructure']}"]
    if report["mode"] != "on":
        lines.append("  shadow mode: nothing skipped; read every hunk yourself.")
    else:
        for row in report["results"]:
            if row["decided"] and row["relates"] in ("unrelated", "infrastructure"):
                lines.append(f"  skip ({row['relates']}): {row['path']} {row['header'][:60]}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--task-root", required=True)
    parser.add_argument("--ticket")
    parser.add_argument("--json", action="store_true")
    args = hooklib.exact_options(parser).parse_args()
    task_root = hooklib.story_cli("judge_diff.py", root=args.task_root, key_flag=None)    # first, even when the judge is off (E-4)
    report = run(task_root, args.ticket)
    print(json.dumps(report, indent=2, ensure_ascii=False) if args.json else render(report))
    return 0 if report["status"] in ("ok", "off") else 3


if __name__ == "__main__":
    sys.exit(main())
