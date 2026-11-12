"""Refusals of FORM: a word outside a closed list is asked about before it is refused.

One block of this factory fires for a reason that is not about the work (the handoff form left the exit gate in X2-3: a digest
word outside the list is advice there, not a refusal; the `unresolved[]` reason mapping was cut in X7-2: the role chooses the
route word, the refusal names the closed list and the role's words go after the `:`):

  node ids           pytest collects the asked test under a spelling a plugin of the project
                     shapes, and the launch is refused with the nearest ids (node_ids.match)

The rule is right and the role meant the right thing; what deviates is a spelling the rule's author did not foresee. On
TP1-15045 a red probe burned on `[buffer-R3-vs-selected-R1]` against a collected `[chromium-buffer-R3-...]`.

So it asks the judge ONE mapping question over ONE small state - the asked id with its candidates - and in `judge.mode: on` a
decided answer (0.9, because a mapping passes a block) pins the collected spelling. With `judge.provider: none` nothing here
runs and it refuses exactly what it refused before. What the judge cannot map is refused as today.

  judge_form.py --node-id <asked> --candidates <json list>
  (add --json for the whole answer; text mode prints one line)
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract as C  # noqa: E402
import judge  # noqa: E402

NONE = "none"


def _journal_pass(cfg, refusal_id: str, judgment_id: str, decision, *, passed: bool,
                  ticket=None, stage=None) -> None:
    """The row `judge.judged_refusal` writes, for a question that is a CHOICE.

    `judged_refusal` reads a pass off a noul's `value is True`; a mapping question answers with
    the option it mapped onto, so the same row is written here under the same refusal id. It is
    the row `judge.passes()` lists in the gate brief - the person sees every block the judge let
    through, whichever shape the question had."""
    if not decision:
        return
    try:
        from datetime import datetime, timezone
        judge.journal(cfg.get("project_root"), [{
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "kind": "pass" if passed else "would_pass" if decision.get("decided") else "held",
            "ticket": ticket, "stage": stage, "refusal": refusal_id, "judgment": judgment_id,
            "mode": cfg.get("mode"), "mapped_to": decision.get("value"),
            "probability": decision.get("probability"), "confidence": decision.get("confidence")}])
    except Exception:
        pass  # a journal that cannot be written never fails a stage (judge.py holds the rule)


def _off(cfg, **extra) -> dict:
    return {"status": "off", "mode": cfg["mode"], "provider": cfg["provider"], **extra}


# --- 1. the handoff form: no longer here (X2-3) ----------------------------------------------
# The exit gate does not ask a judge to map a digest word onto the form's list any more: a word outside the list is advice in
# the stage critic's file (`exit_gate._digest_word_split`), and the refusal is left with what is absent.

# --- a node id pytest does not collect under that spelling -----------------------------------

def node_id(asked: str, nearest, *, ticket=None, stage="S5", project_root=None,
            cfg: dict | None = None) -> dict:
    """{"status", "choice", "decided", "confidence"} for one asked id and its candidates.

    The state is the asked id and the candidate list, and nothing else: a collect of a real
    repository is thousands of ids, and a question answered out of its surroundings is the one
    calibration lesson this factory has already paid for."""
    cfg = cfg or judge.settings(project_root)
    candidates = [str(c) for c in (nearest or []) if str(c).strip()]
    out = {"status": "off", "mode": cfg["mode"], "choice": "", "decided": False, "confidence": 0.0}
    if not 2 <= len(candidates) <= 10 or not judge.active(cfg):
        return out
    try:
        described = judge.load_registry()["form_node_id"]["criteria"]
        same, none_of = list(described.values())[:2]
    except (KeyError, ValueError, OSError):
        return out
    # The options ARE the candidates, so they are built here and the registry holds the shape.
    options = {c: same for c in candidates}
    options[NONE] = none_of
    reply = judge.ask({"asked": str(asked), "collected": candidates},
                      {"q": {"judgment": "form_node_id", "criteria": options}},
                      ticket=ticket, stage=stage, project_root=project_root, cfg=cfg)
    decision = reply["answers"].get("q") if reply["status"] == "ok" else None
    if not decision:
        return dict(out, status=reply["status"] if reply["status"] != "ok" else "off")
    out.update(status="ok", confidence=decision.get("confidence") or 0.0,
               decided=bool(decision.get("decided")))
    value = decision.get("value")
    if value in (None, NONE) or value not in candidates:
        return out
    out["choice"] = value
    _journal_pass(cfg, "node_id_mismatch", "form_node_id", decision,
                  passed=cfg["mode"] == "on", ticket=ticket, stage=stage)
    return out


def resolve_missing(result: dict, *, ticket=None, stage="S5", project_root=None,
                    cfg: dict | None = None) -> dict:
    """`node_ids.match`'s own result with the ids the judge could name moved from `missing` to
    `resolved`. In any mode but `on` nothing moves and the note says the judge only watched."""
    missing = [m for m in (result or {}).get("missing") or [] if isinstance(m, dict)]
    cfg = cfg or judge.settings(project_root)
    if not missing or not judge.active(cfg):
        return result
    kept, resolved, notes, judged = [], dict(result.get("resolved") or {}), list(result.get("notes") or []), {}
    for row in missing:
        answer = node_id(row.get("asked"), row.get("nearest"), ticket=ticket, stage=stage,
                         project_root=project_root, cfg=cfg)
        if not answer["choice"]:
            kept.append(row)
            continue
        if cfg["mode"] != "on":
            kept.append(row)
            notes.append(f"{row.get('asked')}: the judge (shadow) reads {answer['choice']} as "
                         "the same test; nothing was changed")
            continue
        resolved[str(row.get("asked"))] = answer["choice"]
        judged[str(row.get("asked"))] = answer["choice"]
        notes.append(f"{row.get('asked')} is not collected under that spelling; the judge named "
                     f"{answer['choice']} as the same test (form_node_id "
                     f"confidence={answer['confidence']}) and the factory pinned it. The "
                     "nearest ids were the only thing it was shown.")
    out = {**result, "resolved": resolved, "missing": kept, "notes": notes}
    if judged:
        out["judged"] = judged
    return out


# --- CLI --------------------------------------------------------------------------------------

def main() -> int:
    C.force_utf8()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--node-id", help="a pytest node id pytest did not collect")
    ap.add_argument("--candidates", help="a JSON list of the collected ids nearest to it")
    ap.add_argument("--ticket")
    ap.add_argument("--stage", default="S5")
    ap.add_argument("--project-root")
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args()
    common = {"ticket": ns.ticket, "project_root": ns.project_root}
    if ns.node_id:
        candidates = json.loads(ns.candidates) if ns.candidates else []
        answer = node_id(ns.node_id, candidates, stage=ns.stage, **common)
        line = f"judge_form node id: {answer['choice'] or 'none'} (confidence={answer['confidence']})"
    else:
        ap.error("--node-id is required")
    print(json.dumps(answer, indent=2, ensure_ascii=False) if ns.json else line)
    return 0 if answer["status"] in ("ok", "off") else 3


if __name__ == "__main__":
    sys.exit(main())
