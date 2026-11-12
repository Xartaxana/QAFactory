"""Onboarding discovery: ask the judge to pick among candidates the code already found.

`project_inventory.py --access` (env files, login call sites, key names read in code) and the
test-command discovery step of qa-onboarding hand this script a short JSON list of what they
found in code; the judge either narrows it to one candidate (with a confidence) or the
interview asks the team, exactly as it does today without a judge.

Candidate shapes (a JSON list under --candidates):
  test_command  [{"command": str, "evidence": str}, ...]   # one level per call, see --level
  env_file      [{"path": str, "keys": [str, ...], "example": bool}, ...]
  login_site    [{"where": "file:line", "kind": str, "evidence": str}, ...]
  key_role      ["KEY_NAME", ...]                          # NAMEs only, no values, ever

`key_role` classifies every name given, one small state per name (this project's guidance:
never judge many subjects out of one shared state); the other three choose ONE candidate out
of the list, or `none`, and never see anything not already in that list.

  judge_discovery.py --ask test_command --candidates candidates.json --level api
  judge_discovery.py --ask env_file --candidates candidates.json
  judge_discovery.py --ask login_site --candidates candidates.json
  judge_discovery.py --ask key_role --candidates '["JIRA_TOKEN", "APP_BASE_URL"]'

Exit 0 on `ok`/`off`, 3 when the judge was wanted and unavailable; the interview falls back to
asking the team exactly as it would without this script.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import judge  # noqa: E402

CHOICE_JUDGMENTS = {"test_command": "disc_test_command", "env_file": "disc_env_file",
                    "login_site": "disc_login_site"}
MAX_CANDIDATES = 12


def _describe(kind: str, item: dict) -> str:
    if kind == "test_command":
        return f"command `{item.get('command', '')}` - {item.get('evidence', '') or 'no evidence given'}"
    if kind == "env_file":
        keys = item.get("keys") or []
        tag = "example/template file" if item.get("example") else "not marked as an example"
        return f"path `{item.get('path', '')}`, {len(keys)} key(s), {tag}"
    if kind == "login_site":
        return f"{item.get('where', '')} [{item.get('kind', '')}] - {item.get('evidence', '') or 'no evidence given'}"
    raise ValueError(f"unknown candidate kind {kind!r}")


def choose(kind: str, candidates: list, *, level: str | None = None, ticket=None,
          project_root=None, cfg: dict | None = None) -> dict:
    """One choice among `candidates` (already capped to MAX_CANDIDATES) or `none`."""
    judgment_id = CHOICE_JUDGMENTS[kind]
    cfg = cfg or judge.settings(project_root)
    out = {"provider": cfg["provider"], "mode": cfg["mode"], "ask": kind, "status": "ok",
          "chosen": None, "none": False, "decided": False, "confidence": None}
    if not judge.active(cfg, judgment_id):
        out["status"] = "off"
        return out
    candidates = list(candidates)[:MAX_CANDIDATES]
    if not candidates:
        out.update(status="not_ready", reason="no candidates given")
        return out
    keys = [f"cand_{i}" for i in range(len(candidates))]
    criteria = {k: _describe(kind, c) for k, c in zip(keys, candidates)}
    criteria["none"] = "none of the listed candidates is the right one; something else must be asked."
    question = {"judgment": judgment_id, "criteria": criteria, "vars": {"level": level or ""}}
    reply = judge.ask({"candidates": criteria}, {"pick": question}, ticket=ticket, stage="onboarding",
                      project_root=project_root, cfg=cfg)
    if reply["status"] != "ok":
        out.update(status=reply["status"], reason=reply.get("reason"))
        return out
    decision = reply["answers"].get("pick") or {}
    out.update(decided=bool(decision.get("decided")), confidence=decision.get("confidence"),
              probabilities=decision.get("probabilities"))
    chosen_key = decision.get("value")
    if chosen_key == "none":
        out["none"] = True
    elif chosen_key in keys:
        out["chosen"] = candidates[keys.index(chosen_key)]
    else:
        out.update(decided=False)  # an id the judge invented is not a candidate we offered
    return out


def classify_keys(names: list, *, ticket=None, project_root=None, cfg: dict | None = None) -> dict:
    """One small state per NAME - never several names judged out of one shared state."""
    cfg = cfg or judge.settings(project_root)
    out = {"provider": cfg["provider"], "mode": cfg["mode"], "ask": "key_role", "status": "ok",
          "results": {}}
    if not judge.active(cfg, "disc_key_role"):
        out["status"] = "off"
        return out
    names = [str(n) for n in names][:MAX_CANDIDATES]
    if not names:
        out.update(status="not_ready", reason="no candidate names given")
        return out
    replies = judge.ask_many([({"name": name}, {"role": {"judgment": "disc_key_role"}})
                              for name in names],
                             ticket=ticket, stage="onboarding", project_root=project_root, cfg=cfg)
    for name, reply in zip(names, replies):
        if reply["status"] != "ok":
            out.update(status=reply["status"], reason=reply.get("reason"))
            return out
        decision = reply["answers"].get("role") or {}
        out["results"][name] = {"value": decision.get("value") if decision.get("decided") else None,
                                "leaning": decision.get("leaning"), "confidence": decision.get("confidence")}
    return out


def render(report: dict) -> str:
    if report["status"] != "ok":
        return (f"judge_discovery {report['ask']}: {report['status']} - "
                f"{report.get('reason') or 'judge.provider is none'}; ask the team as usual")
    if report["ask"] == "key_role":
        parts = [f"{name}={info['value'] or 'undecided'}({info['confidence']})"
                for name, info in report["results"].items()]
        return "judge_discovery key_role: " + (", ".join(parts) if parts else "no names given")
    if report["none"]:
        return f"judge_discovery {report['ask']}: none of the candidates fit (confidence {report['confidence']})"
    if report["chosen"] is None:
        return f"judge_discovery {report['ask']}: undecided; ask the team"
    return (f"judge_discovery {report['ask']}: chosen {json.dumps(report['chosen'], ensure_ascii=False)}"
           f" (confidence {report['confidence']})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--ask", required=True, choices=["test_command", "env_file", "login_site", "key_role"])
    parser.add_argument("--candidates", required=True,
                        help="JSON list; key_role takes a list of NAMEs, the others a list of candidate objects")
    parser.add_argument("--level", help="test_command only: the test level the command must run (unit/component/api/e2e)")
    parser.add_argument("--ticket")
    parser.add_argument("--project-root")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        candidates = json.loads(args.candidates)
    except ValueError:
        # --candidates may be a path when the caller preferred not to quote a large JSON blob.
        candidates = json.loads(Path(args.candidates).read_text(encoding="utf-8"))
    if args.ask == "key_role":
        report = classify_keys(candidates, ticket=args.ticket, project_root=args.project_root)
    else:
        report = choose(args.ask, candidates, level=args.level, ticket=args.ticket,
                        project_root=args.project_root)
    print(json.dumps(report, indent=2, ensure_ascii=False) if args.json else render(report))
    return 0 if report["status"] in ("ok", "off") else 3


if __name__ == "__main__":
    sys.exit(main())
