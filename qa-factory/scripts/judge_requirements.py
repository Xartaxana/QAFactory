"""S2: the pairwise, per-requirement and per-comment screens of the register.

One small request per subject - the pair, the requirement or the comment *is* the state -
sent together. The contradiction matrix is n(n-1)/2 identical judgments, 105 for a
fifteen-row register. The role still writes the register, cites `path:line` and asks the
owner; this file gives it four screens it no longer reasons through:

  conflicts    pairs judged `opposite`               -> the role confirms and words the question
  possible     pairs under the threshold             -> the role examines them
               (pairs judged consistent or different are not examined when judge.mode is `on`)
  observable   the channel a requirement is observed through, where the judge is sure
  wording      requirements whose outcome the judge cannot see stated -> candidates for a
               question to the owner
  comments     which comments of the collected sources touch scope -> read these first;
               in `on` mode the ones judged `false` are not read

  judge_requirements.py --task-root qa-factory/artifacts/<T> [--json]
writes work/judge-requirements.json.
"""
import argparse
import itertools
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hooklib  # noqa: E402
import judge  # noqa: E402

ROW = re.compile(r"^\|\s*(R-?\d+[a-z]?)\s*\|\s*(.+?)\s*\|")
MAX_COMMENTS = 60
MAX_PAIRS = 600
CONFLICT_AT, CLEAR_AT = 0.5, 0.1


def read_register(path: Path) -> dict:
    """The `## Register` table only: later sections key other tables by the same R ids."""
    rows, inside = {}, False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            inside = line.strip().lower() == "## register"
            continue
        match = ROW.match(line) if inside else None
        if match and match.group(1) not in rows:
            rows[match.group(1)] = match.group(2)[:1200]
    return rows


def story_and_comments(task_root: Path) -> tuple[dict, dict]:
    story, comments = {}, {}
    try:
        sources = json.loads((task_root / "work/source-inventory.json")
                             .read_text(encoding="utf-8")).get("sources", [])
    except (OSError, ValueError):
        return story, comments
    for item in sources:
        if item.get("status") != "read" or not item.get("snapshot_ref"):
            continue
        try:
            snap = json.loads((task_root / "work" / item["snapshot_ref"]).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if item.get("relation") == "task" and (not story or snap.get("key") == task_root.name):
            story = {"key": snap.get("key"), "title": snap.get("title"),
                     "description": (snap.get("description") or "")[:3000]}
        for index, comment in enumerate(snap.get("comments") or []):
            if len(comments) < MAX_COMMENTS and (comment.get("text") or "").strip():
                comments[f"{snap.get('key')}#c{index + 1}"] = (comment["text"] or "")[:3000]
    return story, comments


def run(task_root: Path) -> dict:
    cfg = judge.settings(task_root)
    report = {"provider": cfg["provider"], "mode": cfg["mode"], "status": "ok"}
    if not judge.active(cfg):
        return dict(report, status="off")
    register = task_root / "work/requirements-register.md"
    if not register.is_file():
        return dict(report, status="not_ready", reason="work/requirements-register.md is not written yet")
    rows = read_register(register)
    if not rows:
        return dict(report, status="not_ready", reason="no R rows found in the register table")
    story, comments = story_and_comments(task_root)
    brief = {"key": story.get("key"), "title": story.get("title")}
    requests, keys = [], []
    for rid, text in rows.items():
        requests.append(({"story": brief, "requirement": text},
                         {"observable": {"judgment": "requirement_observable_in"},
                          "verifiable": {"judgment": "requirement_verifiable"}}))
        keys.append(("requirement", rid))
    for cid, text in comments.items():
        requests.append(({"story": story, "comment": text},
                         {"scope": {"judgment": "comment_changes_requirements"}}))
        keys.append(("comment", cid))
    pairs = list(itertools.combinations(rows, 2))[:MAX_PAIRS]
    for a, b in pairs:
        requests.append(({"statement_1": rows[a], "statement_2": rows[b]},
                         {"relation": {"judgment": "requirements_contradict"}}))
        keys.append(("pair", (a, b)))
    replies = judge.ask_many(requests, workers=8, ticket=task_root.name, stage="S2", project_root=task_root, cfg=cfg)
    failed = next((r for r in replies if r["status"] != "ok"), None)
    if failed:
        return dict(report, status=failed["status"], reason=failed.get("reason"))
    observable, wording, scope_comments, quiet_comments = {}, [], [], []
    conflicts, possible = [], []
    for (kind, ident), reply in zip(keys, replies):
        answers = reply["answers"]
        if kind == "requirement":
            channel = answers.get("observable") or {}
            observable[ident] = {"channel": channel.get("value"), "leaning": channel.get("leaning"),
                                 "confidence": channel.get("confidence")}
            verdict = answers.get("verifiable") or {}
            if verdict.get("value") is not True:
                wording.append({"id": ident, "probability": verdict.get("probability"),
                                "verdict": "outcome not stated" if verdict.get("value") is False
                                else "check wording"})
        elif kind == "pair":
            relation = answers.get("relation") or {}
            # Only one option matters here. `consistent` against `different` is a split the
            # matrix does not care about, so the option's own probability decides, not the
            # confidence of the whole distribution.
            opposite = (relation.get("probabilities") or {}).get("opposite", 0.0)
            entry = {"pair": list(ident), "opposite": opposite}
            if opposite >= CONFLICT_AT:
                conflicts.append(entry)
            elif opposite > CLEAR_AT:
                possible.append(entry)
        else:
            scope = answers.get("scope") or {}
            (quiet_comments if scope.get("value") is False else scope_comments).append(
                {"comment": ident, "probability": scope.get("probability")})
    report.update(requirements=len(rows), pairs_asked=len(pairs),
                  pairs_total=len(rows) * (len(rows) - 1) // 2, conflicts=conflicts, possible=possible,
                  observable=observable, wording=wording,
                  comments_that_touch_scope=scope_comments, comments_without_scope=quiet_comments,
                  advisory=replies[0]["advisory"] if replies else True,
                  input_tokens=sum(r.get("input_tokens") or 0 for r in replies))
    (task_root / "work/judge-requirements.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def render(report: dict) -> str:
    if report["status"] != "ok":
        return (f"judge_requirements: {report['status']} - "
                f"{report.get('reason') or 'judge.provider is none'}; screen the register as usual")
    sure = sum(1 for v in report["observable"].values() if v["channel"])
    return (f"judge_requirements: mode={report['mode']} {report['requirements']} requirements, "
            f"{report['pairs_asked']} pairs - {len(report['conflicts'])} conflict, "
            f"{len(report['possible'])} possible; channel decided for {sure}, {len(report['wording'])} to check for wording; comments: "
            f"{len(report['comments_that_touch_scope'])} touch scope, "
            f"{len(report['comments_without_scope'])} do not -> work/judge-requirements.json")


def cli_main(script: str, run_fn, render_fn, doc: str) -> int:
    """The one command line of the three judge scripts (`judge_cases`, `judge_plan`, `judge_requirements`; AR-15): `--task-root`
    (required) and `--json`; the story is resolved first, even when the judge is off (E-4: a phantom root is refused before `run_fn`
    can answer "off"); exit 0 for ok/off, 3 otherwise. Each script passes its own name, `run`, `render` and docstring."""
    parser = argparse.ArgumentParser(description=doc, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--task-root", required=True)
    parser.add_argument("--json", action="store_true")
    args = hooklib.exact_options(parser).parse_args()
    report = run_fn(hooklib.story_cli(script, root=args.task_root, key_flag=None).resolve())
    print(json.dumps(report, indent=2, ensure_ascii=False) if args.json else render_fn(report))
    return 0 if report["status"] in ("ok", "off") else 3


def main() -> int:
    return cli_main("judge_requirements.py", run, render, __doc__)


if __name__ == "__main__":
    sys.exit(main())
