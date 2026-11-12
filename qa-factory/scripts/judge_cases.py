"""S4: every pinned case against the rubric dimensions a judge can score, before the critic starts.

On TP1-15045 the case critic left seven of fifteen cases unread in both rounds. Here the
loop is code, so no case is skipped: each pinned case, with its plan row, is one request of
three or four registered questions - Then observable (dimension 3), negative reachable
(5, negative cases only), matches its plan row (7), catches a seeded defect (8).

The critic reads `work/judge-cases.json` first:
  needs_critic   a dimension failed or the judge was not sure -> full review, as without a judge
  clean          every judged dimension passed -> the critic checks only what the judge does
                 not score (coverage 1, atomicity 2, edge cases 4, traceability 6), notes `judge-assisted`
                 in the roll-call, and still owns the verdict `critic_rollcall.py` computes.
In `shadow` mode the file is a comparison record and the critic reviews everything.
A `pass` on dimension 8 is a design analysis, never an executed probe.

  judge_cases.py --task-root qa-factory/artifacts/<T> [--json]
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grammar as G  # noqa: E402
import judge  # noqa: E402
import hooklib  # noqa: E402
from judge_requirements import cli_main  # noqa: E402

DIMENSIONS = {"then_observable": ("case_then_observable", 3),
              "negative_reachable": ("case_negative_reachable", 5),
              "matches_row": ("case_matches_row", 7), "catches_defect": ("case_catches_seeded_defect", 8)}
SECTION = re.compile(r"^##\s+(.+?)\s*$", re.M)
# Why dimension 5 is asked of some cases and not others, when no field says it is negative. It
# travels in the report so the critic reads it beside the case, instead of finding a dimension
# quietly missing from the scores.
NOT_JUDGED_NEGATIVE = ("nothing says whether this case is negative: its defect_class is not one "
                       "that names a refusal, its plan row selects no `negative` scenario, and "
                       "its Then fixes no 4xx/5xx status — rubric dimension 5 is yours to score")


def pinned_cases(task_root: Path) -> list:
    links = task_root / "state/story-case-links.json"
    found = []
    if links.is_file():
        for link in json.loads(links.read_text(encoding="utf-8")).get("links", []):
            path = task_root / link.get("path", "")
            if path.is_file():
                found.append((link["case_id"], link.get("version"), path))
    if not found:  # not pinned yet: the authoring files are the only text there is
        import contract as C  # the id form is the project's (`config.case_id_form`), never a glob here
        for path in C.case_glob(task_root / "work/test-cases", task_root):
            found.append((path.stem, None, path))
    return found


def case_view(text: str) -> tuple[dict, dict]:
    front = hooklib.parse_frontmatter(text) or {}
    body = text.split("\n---", 1)[-1] if text.startswith("---") else text
    parts = SECTION.split(body)
    sections = {parts[i].strip().lower(): parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    view = {"title": front.get("title"), "given": sections.get("given", "")[:2500],
            "when": sections.get("when", "")[:2500], "then": sections.get("then", "")[:3000]}
    return front, view


def plan_rows(task_root: Path) -> dict:
    try:
        document = json.loads((task_root / "work/test-plan.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rows = document.get("rows", []) if isinstance(document, dict) else document
    out = {}
    for row in rows:
        obligations = row.get("coverage_obligations") or []
        out[row.get("id")] = {"id": row.get("id"),
                              "behaviour": [o.get("behavior") for o in obligations if o.get("behavior")][:4],
                              "scenarios": (row.get("required_scenarios") or [])[:8],
                              "defect_hypothesis": row.get("defect_hypothesis")}
    return out


def run(task_root: Path) -> dict:
    cfg = judge.settings(task_root)
    report = {"provider": cfg["provider"], "mode": cfg["mode"], "status": "ok"}
    if not judge.active(cfg):
        return dict(report, status="off")
    cases = pinned_cases(task_root)
    if not cases:
        return dict(report, status="not_ready", reason="no case files to read")
    rows = plan_rows(task_root)
    requests, meta = [], []
    for case_id, version, path in cases:
        front, view = case_view(path.read_text(encoding="utf-8"))
        row = rows.get(str(front.get("plan_row") or "").strip())
        questions = {"then_observable": {"judgment": "case_then_observable"}}
        not_judged = []
        # A field, never the wording: `grammar.negative_case` reads the case's own defect_class,
        # the `negative` variant its plan row selects, and a 4xx/5xx its Then fixes. Until 0.7.19
        # a phrase list over the title and the Then decided this, so a negative case worded
        # otherwise lost the dimension that exists for it and nothing said so (FR-12).
        if G.negative_case(front.get("defect_class"), view["then"], (row or {}).get("scenarios")):
            questions["negative_reachable"] = {"judgment": "case_negative_reachable"}
        else:
            not_judged.append({"dimension": DIMENSIONS["negative_reachable"][1],
                               "why": NOT_JUDGED_NEGATIVE})
        if row:
            questions["matches_row"] = {"judgment": "case_matches_row"}
            questions["catches_defect"] = {"judgment": "case_catches_seeded_defect"}
        requests.append(({"case": view, "plan_row": row or {}}, questions))
        meta.append({"case_id": case_id, "version": version, "plan_row": (row or {}).get("id"),
                     "asked": list(questions), "not_judged": not_judged})
    replies = judge.ask_many(requests, workers=8, ticket=task_root.name, stage="S4",
                             project_root=task_root, cfg=cfg)
    failed = next((r for r in replies if r["status"] != "ok"), None)
    if failed:
        return dict(report, status=failed["status"], reason=failed.get("reason"))
    results, needs, clean = [], [], []
    for info, reply in zip(meta, replies):
        scores = {}
        for name in info["asked"]:
            answer = reply["answers"].get(name) or {}
            verdict = {True: "pass", False: "fail", None: "undecided"}[answer.get("value")]
            scores[name] = {"dimension": DIMENSIONS[name][1], "verdict": verdict,
                            "probability": answer.get("probability")}
        flagged = [n for n, s in scores.items() if s["verdict"] != "pass"]
        if not info["plan_row"]:
            flagged.append("no_plan_row")
        (needs if flagged else clean).append(info["case_id"])
        results.append({**info, "scores": scores, "flagged": flagged})
    report.update(cases=len(cases), results=results, needs_critic=needs, clean=clean,
                  judged_dimensions=[3, 5, 7, 8], critic_only_dimensions=[1, 2, 4, 6],
                  advisory=replies[0]["advisory"] if replies else True,
                  input_tokens=sum(r.get("input_tokens") or 0 for r in replies))
    (task_root / "work/judge-cases.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def render(report: dict) -> str:
    if report["status"] != "ok":
        return (f"judge_cases: {report['status']} - {report.get('reason') or 'judge.provider is none'}; "
                "review every case as usual")
    lines = [f"judge_cases: mode={report['mode']} {report['cases']} cases judged, none skipped - "
             f"{len(report['clean'])} clean, {len(report['needs_critic'])} need the critic "
             "-> work/judge-cases.json"]
    for item in report["results"]:
        if item["flagged"]:
            detail = ", ".join(f"{n}={item['scores'][n]['verdict']}({item['scores'][n]['probability']})"
                               if n in item["scores"] else n for n in item["flagged"])
            lines.append(f"  {item['case_id']}: {detail}")
    # A dimension nobody judged is named, never dropped: the critic scores it, and it can only
    # do that if it is told which case and why (FR-41 — an unknown says so).
    for dimension in sorted({row["dimension"] for item in report["results"]
                             for row in item.get("not_judged") or []}):
        cases = [item["case_id"] for item in report["results"]
                 if any(row["dimension"] == dimension for row in item.get("not_judged") or [])]
        why = next(row["why"] for item in report["results"] for row in item.get("not_judged") or []
                   if row["dimension"] == dimension)
        lines.append(f"  dimension {dimension} not judged for {', '.join(cases)}: {why}")
    return "\n".join(lines)


def main() -> int:
    return cli_main("judge_cases.py", run, render, __doc__)


if __name__ == "__main__":
    sys.exit(main())
