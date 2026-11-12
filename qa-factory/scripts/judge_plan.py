"""S3: two per-requirement inputs of the plan, asked of the judge before the strategist starts.

For every row of the register: the lowest test level that can verify it, and - as a hint in
every mode - the impact if it silently broke. The strategist
has no shell, so the orchestrator's `story_step.py start` runs this first and hands the file
over as an input. The strategist takes a decided level as the row's starting point and
spends its reasoning on the undecided ones, on impact and likelihood, on coverage, on fit and on the reason text;
disposition stays its own decision from the four inputs of `automation-candidacy.md`.

  judge_plan.py --task-root qa-factory/artifacts/<T> [--json]
writes work/judge-plan.json.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import judge  # noqa: E402
from judge_requirements import cli_main, read_register, story_and_comments  # noqa: E402

DAMAGE = ("low", "moderate", "severe")


def run(task_root: Path) -> dict:
    cfg = judge.settings(task_root)
    report = {"provider": cfg["provider"], "mode": cfg["mode"], "status": "ok"}
    if not judge.active(cfg):
        return dict(report, status="off")
    register = task_root / "work/requirements-register.md"
    rows = read_register(register) if register.is_file() else {}
    if not rows:
        return dict(report, status="not_ready", reason="no requirements register to read")
    story, _ = story_and_comments(task_root)
    requests = [({"story": story, "requirement": text},
                 {"damage": {"judgment": "plan_row_damage"},
                  "level": {"judgment": "plan_row_level"}}) for text in rows.values()]
    replies = judge.ask_many(requests, workers=8, ticket=task_root.name, stage="S3",
                             project_root=task_root, cfg=cfg)
    failed = next((r for r in replies if r["status"] != "ok"), None)
    if failed:
        return dict(report, status=failed["status"], reason=failed.get("reason"))
    out = {}
    for rid, reply in zip(rows, replies):
        a = reply["answers"]
        damage, level = a.get("damage") or {}, a.get("level") or {}
        index = damage.get("value")
        out[rid] = {
            "impact": DAMAGE[index] if isinstance(index, int) and 0 <= index < len(DAMAGE) else None,
            "impact_leaning": DAMAGE[damage["leaning"]] if isinstance(damage.get("leaning"), int)
            and 0 <= damage["leaning"] < len(DAMAGE) else None,
            "impact_confidence": damage.get("confidence"),
            "level": level.get("value"), "level_leaning": level.get("leaning"),
            "level_confidence": level.get("confidence")}
    undecided = [rid for rid, v in out.items() if v["impact"] is None or v["level"] is None]
    report.update(requirements=len(rows), rows=out, undecided=undecided,
                  advisory=replies[0]["advisory"] if replies else True,
                  input_tokens=sum(r.get("input_tokens") or 0 for r in replies))
    (task_root / "work/judge-plan.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def render(report: dict) -> str:
    if report["status"] != "ok":
        return (f"judge_plan: {report['status']} - {report.get('reason') or 'judge.provider is none'}; "
                "plan as usual")
    return (f"judge_plan: mode={report['mode']} {report['requirements']} requirements - impact and level "
            f"decided for {report['requirements'] - len(report['undecided'])}, left to the strategist: "
            f"{', '.join(report['undecided']) or 'none'} -> work/judge-plan.json")


def main() -> int:
    return cli_main("judge_plan.py", run, render, __doc__)


if __name__ == "__main__":
    sys.exit(main())
