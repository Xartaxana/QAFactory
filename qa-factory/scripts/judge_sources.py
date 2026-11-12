"""S1: look at every mentioned ticket and judge its relevance in one command.

Without a judge the scout spends one model turn to `peek` a mention and one more to `assess`
it, for every key a ticket names. This script does the looking in code (`peek` for every
pending mention, in one run) and puts two registered questions per mention to the judge:
`source_relevant` and `source_relation`.

  judge.mode on      a decided answer is recorded exactly as `ticket_adapter.py assess` would
                     record it, with the probability in the reason; a relevant mention is then
                     collected in full and the mentions *it* brings are judged the same way.
  judge.mode shadow  nothing is recorded in the inventory; the answers go to the journal and
                     to `work/judge-sources.json` so they can be compared with the scout's.
  undecided          the mention stays `pending` for the scout, as without a judge.

The person's source review is untouched: every decision made here is a row of that table,
labelled as the judge's, and the person flips it with one word.

A second, independent question runs in the same command: `disc_attachment_worth_opening` asks,
per attachment already fetched (name, type, size, the comment it was mentioned with, the story
title) whether it is worth a scout's turn to inspect. A decided `false` in `mode: on` records
the attachment's `analysis_status` as `unavailable` with a `skipped_by_judge:` reason through
`source_inventory.record_attachment_inspection` - the same field a real fetch or storage
failure uses, so gate A shows it in `unavailable_materials` exactly like any other gap the
factory could not close on its own, for the person to accept or send back. There is no separate
"skipped" status in that recorder; a rejected attachment differs from a broken one only in its
`analysis_reason` text (see the final report for the change that would add one).

  judge_sources.py --output qa-factory/artifacts/<T>/work/source-inventory.json [--ticket T]
                   [--no-fetch] [--no-attachments] [--rejudge] [--max-rounds 3] [--json]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import judge  # noqa: E402
import local_keys  # noqa: E402
from source_inventory import (load_inventory, update_inventory, peek_jira_source,  # noqa: E402
                              collect_jira_source, record_relevance_assessment,
                              record_attachment_inspection, client_from_config)

STORY_RELATIONS = ("task", "subject", "parent", "normative")
TEXT_LIMIT = 9000
MAX_MENTIONS = 60
MAX_ATTACHMENTS = 40


def _clip(value, limit=TEXT_LIMIT):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + " [...]"


def _view(snapshot: dict, limit=TEXT_LIMIT) -> dict:
    return {"key": snapshot.get("key"), "type": snapshot.get("type"),
            "title": snapshot.get("title") or "",
            "description": _clip(snapshot.get("description") or "", limit),
            "acceptance_criteria": _clip(snapshot.get("acceptance_criteria") or "", limit // 2)}


def _read(work: Path, ref):
    try:
        return json.loads((work / ref).read_text(encoding="utf-8")) if ref else None
    except (OSError, ValueError):
        return None


def story_state(work: Path, inventory: dict, ticket: str | None = None) -> dict | None:
    """The task and what it is about. A testing task often says only "test X": the subject
    and the parent carry the behaviour, so they are part of what a mention is compared with."""
    parts = {}
    for relation in STORY_RELATIONS:
        for item in inventory.get("sources", []):
            if item.get("relation") == relation and item.get("status") == "read":
                snap = _read(work, item.get("snapshot_ref"))
                if snap:
                    parts.setdefault(relation, []).append(_view(snap, 6000 if relation == "task" else 4000))
    if not parts.get("task"):
        return None
    # One story has one task source, but an inventory written before that rule may carry
    # several; the ticket the story was started for is the task, the rest is what it is about.
    parts["task"].sort(key=lambda view: view["key"] != ticket)
    task = parts["task"][0]
    about = [v for rel in ("subject", "parent", "normative") for v in parts.get(rel, [])]
    about += parts["task"][1:]  # an older inventory recorded the subject as a second task
    return {"key": task["key"], "title": task["title"], "description": task["description"],
            "acceptance_criteria": task["acceptance_criteria"], "about": about[:3]}


def _key(item: dict) -> str:
    return str(item.get("canonical_ref") or "").rsplit("/", 1)[-1]


def _client():
    from ticket_adapter import load_config, resolve_adapter
    kind, adapter_cfg = resolve_adapter(load_config())
    if kind != "jira":
        raise RuntimeError("judge_sources fetches through the direct Jira adapter only")
    return client_from_config(adapter_cfg)


def _attachment_state(story_title: str, source: dict, receipt: dict) -> dict:
    return {"story_title": story_title, "filename": receipt.get("filename") or "",
           "media_type": receipt.get("media_type") or "unknown",
           "size": receipt.get("size") if receipt.get("size") is not None else "unknown",
           "comment": (source.get("relation_evidence") or source.get("relevance_reason") or "")[:600]}


def assess_attachments(output: Path, ticket=None, cfg: dict | None = None,
                       max_items: int = MAX_ATTACHMENTS) -> dict:
    """Every already-fetched attachment still `analysis_status: pending`, one small state each
    (never several attachments judged out of one shared inventory) - see the module docstring
    for what a decided `false` records and why."""
    cfg = cfg or judge.settings(output)
    report = {"provider": cfg["provider"], "mode": cfg["mode"], "checked": 0, "skipped": 0,
             "decisions": [], "status": "ok"}
    if not judge.active(cfg, "disc_attachment_worth_opening"):
        report["status"] = "off"
        return report
    inventory = load_inventory(output)
    story = story_state(output.parent, inventory, ticket)
    story_title = story["title"] if story else ""
    jobs = []
    for source in inventory.get("sources", []):
        if source.get("status") != "read":
            continue
        items = ((source.get("materials") or {}).get("attachments") or {}).get("items") or []
        for receipt in items:
            if receipt.get("status") == "read" and receipt.get("analysis_status") == "pending":
                jobs.append((source, receipt))
            if len(jobs) >= max_items:
                break
        if len(jobs) >= max_items:
            break
    if not jobs:
        return report
    replies = judge.ask_many(
        [(_attachment_state(story_title, source, receipt),
          {"worth": {"judgment": "disc_attachment_worth_opening"}}) for source, receipt in jobs],
        ticket=ticket or (story or {}).get("key"), stage="S1", project_root=output, cfg=cfg)
    for (source, receipt), reply in zip(jobs, replies):
        if reply["status"] != "ok":
            report.update(status=reply["status"], reason=reply.get("reason"))
            return report
        decision = reply["answers"].get("worth") or {}
        report["checked"] += 1
        row = {"source_id": source["source_id"], "attachment_id": receipt.get("attachment_id"),
              "filename": receipt.get("filename"), "worth_opening": decision.get("value"),
              "probability": decision.get("probability"), "recorded": False}
        if decision.get("decided") and decision.get("value") is False:
            row["recorded"] = cfg["mode"] == "on"
            if row["recorded"]:
                evidence_ref = f"judge-attachment-{source['source_id']}-{receipt.get('attachment_id')}.json"
                (output.parent / evidence_ref).write_text(
                    json.dumps({"judgment": "disc_attachment_worth_opening", **decision},
                              indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                reason = (f"skipped_by_judge: {cfg['model']} p={decision.get('probability')} - name, type "
                         "and comment give no reason this attachment documents the story's behaviour")
                record_attachment_inspection(output, source["source_id"], str(receipt.get("attachment_id")),
                                             "skipped", evidence_ref, reason)
            report["skipped"] += 1
        report["decisions"].append(row)
    return report


def run(output: Path, ticket=None, fetch=True, rejudge=False, max_rounds=3,
       attachments=True) -> dict:
    cfg = judge.settings(output)
    work = output.parent
    report = {"provider": cfg["provider"], "mode": cfg["mode"], "rounds": 0, "peeked": 0,
              "collected": [], "decisions": [], "left_to_scout": [], "status": "ok"}
    run_mentions = judge.active(cfg, "source_relevant")
    run_attachments = attachments and judge.active(cfg, "disc_attachment_worth_opening")
    if not run_mentions and not run_attachments:
        report["status"] = "off"
        return report
    client = None
    seen = set()
    for _ in range(max_rounds if run_mentions else 0):
        inventory = load_inventory(output)
        story = story_state(work, inventory, ticket)
        if not story:
            report.update(status="not_ready", reason="no fully read task source in the inventory yet")
            return report
        pending = [s for s in inventory["sources"] if s.get("relevance") == "pending"
                   and s["source_id"] not in seen][:MAX_MENTIONS]
        if rejudge and not report["rounds"]:
            pending += [s for s in inventory["sources"] if s.get("assessment_ref")
                        and s.get("relation") == "referenced" and s.get("relevance") != "pending"]
        if not pending:
            break
        report["rounds"] += 1
        for item in [p for p in pending if not p.get("assessment_ref") and not local_keys.is_local(_key(p))]:   # a local key has no tracker to peek (SS1-14)
            if not fetch:
                continue
            client = client or _client()
            record = peek_jira_source(client, _key(item), output,
                                      discovered_from=item.get("discovered_from"),
                                      relation_evidence=item.get("relation_evidence"))
            update_inventory(output, record)
            report["peeked"] += 1
        inventory = load_inventory(output)
        by_id = {s["source_id"]: s for s in inventory["sources"]}
        new_relevant = []
        for source_id in [p["source_id"] for p in pending]:
            seen.add(source_id)
            item = by_id.get(source_id) or {}
            snapshot = _read(work, item.get("assessment_ref"))
            if not snapshot:
                continue  # unavailable or 404: the collector already said why
            reply = judge.ask({"story": story, "candidate": _view(snapshot)},
                              {"relevant": {"judgment": "source_relevant"},
                               "relation": {"judgment": "source_relation"}},
                              ticket=ticket or story["key"], stage="S1", project_root=output, cfg=cfg)
            if reply["status"] != "ok":
                report.update(status=reply["status"], reason=reply.get("reason"))
                return report
            rel, relation = reply["answers"].get("relevant") or {}, reply["answers"].get("relation") or {}
            row = {"key": _key(item), "title": snapshot.get("title"), "source_id": source_id,
                   "relevant": rel.get("value"), "probability": rel.get("probability"),
                   "relation": relation.get("leaning"), "relation_confidence": relation.get("confidence"),
                   "recorded": False, "previous": item.get("relevance")}
            # The two questions must not disagree: "relevant" next to "unrelated" is the judge
            # being unsure in a way one threshold does not show, so the scout gets it.
            consistent = not (rel.get("value") is True and relation.get("leaning") == "unrelated") \
                and not (rel.get("value") is False and relation.get("decided")
                         and relation.get("leaning") in ("defines_behaviour", "defect_in_scope"))
            if not rel.get("decided") or not consistent:
                row["relevant"] = None
                report["left_to_scout"].append(row["key"])
            elif cfg["mode"] == "on" and item.get("relevance") == "pending":
                verdict = "relevant" if rel["value"] else "not_relevant"
                reason = (f"judge {cfg['model']}: {verdict} p={rel['probability']}, relation "
                          f"{relation.get('leaning')} ({relation.get('confidence')}) - against "
                          f"{story['key']} \"{story['title'][:80]}\"")
                record_relevance_assessment(output, source_id, verdict, reason, item["assessment_ref"])
                row["recorded"] = True
                if rel["value"]:
                    new_relevant.append(item)
            report["decisions"].append(row)
        for item in new_relevant if fetch else []:
            client = client or _client()
            existing = next((s for s in load_inventory(output)["sources"]
                             if s["source_id"] == item["source_id"]), None)
            record = collect_jira_source(client, _key(item), output, relation="referenced",
                                         discovered_from=item.get("discovered_from"),
                                         relation_evidence=item.get("relation_evidence"),
                                         existing_record=existing)
            update_inventory(output, record)
            report["collected"].append(_key(item))
        if not new_relevant:
            break
    if run_attachments and report["status"] == "ok":
        attachments_report = assess_attachments(output, ticket, cfg)
        if attachments_report["status"] not in ("ok", "off"):
            report.update(status=attachments_report["status"], reason=attachments_report.get("reason"))
        report["attachments"] = attachments_report
    (work / "judge-sources.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                                             encoding="utf-8")
    return report


def render(report: dict) -> str:
    if report["status"] != "ok":
        return f"judge_sources: {report['status']} - {report.get('reason') or 'judge.provider is none'}; assess mentions as usual"
    lines = [f"judge_sources: mode={report['mode']} peeked={report['peeked']} "
             f"judged={len(report['decisions'])} collected={len(report['collected'])} "
             f"left to the scout={len(report['left_to_scout'])}"]
    for row in report["decisions"]:
        verdict = {True: "relevant", False: "not_relevant", None: "UNDECIDED"}[row["relevant"]]
        lines.append(f"  {row['key']:<18} {verdict:<13} p={row['probability']:<6} {row['relation'] or '-':<22}"
                     f" {'recorded' if row['recorded'] else 'advisory'}  {str(row['title'])[:60]}")
    if report["mode"] != "on":
        lines.append("  shadow mode: nothing was recorded; assess every mention yourself.")
    elif report["left_to_scout"]:
        lines.append("  assess yourself: " + ", ".join(report["left_to_scout"]))
    attachments = report.get("attachments")
    if attachments and attachments["status"] == "ok" and attachments["checked"]:
        lines.append(f"  attachments: checked={attachments['checked']} skipped={attachments['skipped']}"
                     + ("" if report["mode"] == "on" else " (shadow: nothing recorded)"))
        for row in attachments["decisions"]:
            if row["worth_opening"] is False:
                lines.append(f"    {'skip' if row['recorded'] else 'would skip'}: {row['filename']}"
                             f" p={row['probability']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--output", required=True)
    parser.add_argument("--ticket")
    parser.add_argument("--no-fetch", action="store_true", help="judge only what is already peeked")
    parser.add_argument("--rejudge", action="store_true",
                        help="also put already assessed mentions to the judge (comparison only, never recorded)")
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--no-attachments", action="store_true",
                        help="skip the disc_attachment_worth_opening pass over fetched attachments")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run(Path(args.output), args.ticket, not args.no_fetch, args.rejudge, args.max_rounds,
                not args.no_attachments)
    print(json.dumps(report, indent=2, ensure_ascii=False) if args.json else render(report))
    return 0 if report["status"] in ("ok", "off") else 3


if __name__ == "__main__":
    sys.exit(main())
