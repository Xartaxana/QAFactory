"""The interim packet of a story held for code (t-2181 PC-7, F-6): `interim-report.md`, assembled by CODE from data.

A story whose deliverable side does not exist yet stops after S5. The person reads this document while it waits: what is
written, what ran and what each run recorded about the sides it ran against, which placeholders stand in for the missing
side, and how to start the story again. DATA ONLY (P27, AR-29): every line is a field read from the story's own files -
the sides, the manifest's tests, the `provisional[]` rows, the `pending_implementation` rows, the run blocks and their
stamps. Nothing here says whether a placeholder is reasonable, whether a test proves anything or whether the story is ready:
a run on a substitute is reported as "ran with a substitute", never as a verdict.

  interim_packet.py --task-root TASK_ROOT [--command TEXT] [--out FILE] [--json]

Without `--out` the document is written to `<task root>/interim-report.md` (the one writer of that file, AR-14) and its path
is printed; with `--json` the data is printed instead and nothing is written (FR-45: a reader writes nothing).

Edges: no manifest yet -> an empty `tests` list, the document says so (a story whose cases are all unresolved still gets a
packet, AR-23); no run block -> every test reads "not run"; a block with no stamp -> "no record of the sides"; a stamp that
says `sides_unknown` -> "side state not known" (an unknown is never read as real, AR-28); an unreadable file -> that
part is empty and one line names it.

Exit 0 written / printed, 2 the story root cannot be read.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import contract as C  # noqa: E402
import hooklib  # noqa: E402

PACKET_NAME = "interim-report.md"


def _runs_by_instance(task_root: Path) -> tuple:
    """({instance id: {"kind", "status", "stamp", "unknown"}} of the NEWEST block that names it, [unreadable block names])."""
    import run_history
    blocks, bad = run_history.read_run_blocks(task_root)
    seen: dict = {}
    for item in blocks:                  # oldest first: a later block replaces an earlier one
        data = item["data"]
        stamp = data.get("sides_met") if isinstance(data.get("sides_met"), dict) else None
        for result in data.get("results") if isinstance(data.get("results"), list) else []:
            iid = str((result or {}).get("instance_id") or "") if isinstance(result, dict) else ""
            if iid:
                seen[iid] = {"kind": str(data.get("kind") or "run"), "status": str(result.get("status") or ""),
                             "stamp": stamp, "unknown": str(data.get("sides_unknown") or "")}
    return seen, bad


def build(task_root, command: str = "") -> dict:
    """The packet's data. Pure: reads the story's files, writes nothing."""
    task_root = Path(task_root)
    pipeline = hooklib.read_json(task_root / "pipeline.json", {}, kind=dict)         # F4: the package's one JSON reader (AR-13)
    manifest = hooklib.read_json(C.artifact(task_root, "automation-manifest.json"), {}, kind=dict)
    sides = C.story_sides(pipeline)
    tests = C.manifest_tests(manifest)
    items = [{"instance_id": C.test_instance_id(entry)} for entry in tests if C.test_instance_id(entry)]
    import acceptance
    pending = acceptance.pending_instances(manifest, items, sides=sides)
    ran, bad = _runs_by_instance(task_root)
    rows = []
    for entry in tests:
        iid = C.test_instance_id(entry)
        if not iid:
            continue
        declared = entry.get("sides") if isinstance(entry.get("sides"), dict) else {}
        row = {"instance_id": iid, "case": str(entry.get("case") or ""), "declared": dict(sorted(declared.items())),
               "waits": iid in pending, "run": None}
        if iid in ran:
            row["run"] = ran[iid]
        rows.append(row)
    rows.sort(key=lambda r: (r["case"], r["instance_id"]))
    provisional = C.manifest_provisional(manifest)["rows"]
    unresolved = [{"case": str(r.get("case") or ""), "instance_ids": [str(i) for i in r.get("instance_ids") or []]}
                  for r in C.manifest_unresolved(manifest)
                  if str(r.get("reason") or "") == "pending_implementation"]
    unknown = pipeline.get("sides_unknown")
    return {"task": task_root.name,
            "sides": [{"name": name, "reality": s["reality"], "deliverable": s["deliverable"], "settles_by": s["settles_by"],
                       "source": s["source"]} for name, s in sorted(sides.items())],
            "sides_unknown": str(unknown.get("why") or "") if isinstance(unknown, dict) else ("" if not unknown else str(unknown)),
            "tests": rows,
            "collects": len([r for r in manifest.get("runs") or [] if isinstance(r, dict) and r.get("kind") == "collect"]),
            "provisional": [{"id": str(r.get("id")), "kind": str(r.get("kind") or ""), "what": str(r.get("what") or ""),
                             "settles_on": str(r.get("settles_on") or ""), "status": str(r.get("status") or ""),
                             "file": str((r.get("home") or {}).get("file") or "") if isinstance(r.get("home"), dict) else ""}
                            for r in provisional],
            "pending": unresolved, "unreadable_blocks": list(bad), "command": str(command or "")}


def _ran_words(run) -> str:
    """One run of a test, in words, from what the block recorded. A stamp is DATA the block carries; it is reported, not judged."""
    if not run:
        return "not run"
    if run["kind"] == "collect":
        return "collected only, nothing ran"
    result = run["status"] or "no result recorded"
    if run["unknown"]:
        return f"ran ({result}); the state of the sides was not known then"
    stamp = run["stamp"]
    if stamp is None:
        return f"ran ({result}); the run recorded nothing about the sides"
    if all(word == "real" for word in stamp.values()):
        return f"ran on real sides ({result})"
    other = ", ".join(f"{name} {word}" for name, word in sorted(stamp.items()) if word != "real")
    return f"ran with a substitute or a missing side ({other}); result: {result}"


def render(data: dict) -> str:
    """The markdown document for the person, from `build`'s data."""
    lines = [f"# Interim report for {data['task']}", "",
             "The tests for this story are written and reviewed, and the story is waiting for the code it is about. "
             "Nothing has been delivered. If the factory needs your answer about the part that does not exist yet, it asks it right "
             "after this page. This page says what exists so far, what the "
             "tests were written against, and what stands in for the part that does not exist yet.", ""]
    lines += ["## What the story waits for", ""]
    waiting = [s for s in data["sides"] if s["reality"] == "absent" and s["deliverable"]]
    for side in data["sides"]:
        mark = "waits for it" if side in waiting else ""
        lines.append(f"- {side['name']}: {side['reality'] or 'not known'}"
                     + ("" if side["deliverable"] else "; another team's"
                        ) + (f"; settled by {side['settles_by']}" if side["settles_by"] else "")
                     + (f" ({mark})" if mark else ""))
    if not data["sides"]:
        lines.append("- the factory could not read which parts of the product this story touches")
    if data["sides_unknown"]:
        lines += ["", f"The factory could not read the project's record of its sides at the start: {data['sides_unknown']}. "
                      "What ran then is reported as not known."]
    lines += ["", "## What is written", ""]
    if not data["tests"]:
        lines.append("No test is recorded for this story yet.")
    case = None
    for row in data["tests"]:
        if row["case"] != case:
            case = row["case"]
            lines.append(f"Case {case or '(none named)'}:")
        declared = ", ".join(f"{n} {w}" for n, w in row["declared"].items())
        lines.append(f"- test {row['instance_id']}"
                     + (f" (written against: {declared})" if declared else "")
                     + (": waits for the code" if row["waits"] else "")
                     + f" - {_ran_words(row['run'])}")
    if data["collects"]:
        lines += ["", f"{data['collects']} collect-only run(s) listed the tests that wait; a collect runs nothing."]
    if data["unreadable_blocks"]:
        lines += ["", "Some run records could not be read, so a test may show as not run: "
                      + ", ".join(data["unreadable_blocks"][:5])]
    lines += ["", "## What stands in for the missing code", ""]
    open_rows = [r for r in data["provisional"] if r["status"] == "open"]
    kept = [r for r in data["provisional"] if r["status"] == "kept_by_decision"]
    if not open_rows and not kept:
        lines.append("No placeholder is recorded.")
    for side in sorted({r["settles_on"] for r in open_rows + kept}):
        lines.append(f"For {side or 'a part not named'}:")
        lines += [f"- {r['what'] or 'no description'} ({r['kind'].replace('_', ' ')}"
                  + ("; kept as it is by decision" if r["status"] == "kept_by_decision" else "") + ")"
                  for r in open_rows + kept if r["settles_on"] == side]
    lines += ["", "## How to answer", "",
              "When the code exists, start the story again with where it is"
              + (":" if data["command"] else " (the merge request, the branch or the commit):")]
    if data["command"]:
        lines += ["", f"    {data['command']} --branch <the branch with the code>",
                  "", "A merge request (--mr <link>) or a commit (--commit <sha>) works the same way; for one part of the "
                      "product only, say which became real with --side <name>=real."]
    homes = sorted({r["file"] for r in open_rows + kept if r["file"]})
    if homes:
        lines += ["", "Where the placeholders live in your project:"] + [f"- {home}" for home in homes]
    lines += ["", "If the part that does not exist belongs to another team, answer `not ours` to the question about it: the story then goes "
                  "on against a stand-in for that part and the report lists what was not checked against the real one.",
              "", "To end the wait without the code, say so in the conversation."]
    return "\n".join(lines) + "\n"


def short_head(sha) -> str:
    """The head a person reads, THE one spelling of it (the packet and the question `first_look.same_code` both use it): a commit id cut
    to seven characters; anything else (`unmeasured: ...`, a field name the person never sees) is "no commit recorded"."""
    text = str(sha or "")
    return text[:7] if len(text) == 40 and all(c in "0123456789abcdef" for c in text) else "no commit recorded"


def restart_lines(command: str, lead: str = "") -> list:
    """The lines that say how to start the story again with new code, THE one text (the packet and the printed answer to `source` use it).
    No command given -> no invented command: the three flags are named in words."""
    lines = [lead + "To check new code, start the story again with where it is" + (":" if command else " (the merge request, the branch or the commit).")]
    if command:
        lines += ["", f"    {command} --branch <the branch with the code>", "",
                  "A merge request (--mr <link>) or a commit (--commit <sha>) works the same way."]
    return lines


def status_counts(rows) -> str:
    """`confirms 1, contradicts 0, ...`: the number of rows of the record by each status word `first_look.json` names, in its order."""
    import first_look as FL
    return ", ".join(f"{w} {sum(1 for r in rows if r.get('status') == w)}" for w in (FL.data().get("statuses") or []))


def first_look_packet(task_root, command: str = "") -> str:
    """The document of a story the person stopped after the first look (t-2277 FL-6; cause `first_look_stop`, held from S3): what the
    stand showed, the requirements it did not reach with the evidence the walker cited, the code the look was about and the day the story
    stopped, and how to start it again. DATA ONLY (P27, AR-29): every line is a field of the record `first_look.read` returns (the one
    reader of it, AR-13) and of the hold; nothing says whether the stand is right. Pure: writes nothing (FR-45).
    Edges: a record that is absent, null, stale or unreadable is ONE line saying so and no counts (an unknown is never a count, AR-28);
    no command given -> no invented command; the stop day not on the record -> "an earlier day" (never a date the factory made up, FR-41)."""
    import first_look as FL
    task_root = Path(task_root)
    pipeline = hooklib.read_json(task_root / "pipeline.json", {}, kind=dict)
    hold = C.awaiting(pipeline)
    since = str(hold.get("since") or "")[:10] or "an earlier day"
    state = FL.state(task_root)
    got = state["got"]
    lines = [f"# First look report for {task_root.name}", "",
             f"This story was stopped on {since} after the first look at the stand, and nothing runs until the code you want checked is "
             "named or you say to go on as it is. This page says what the stand showed.", "", "## What the stand showed", ""]
    if state["kind"] != "ok":
        said = {"absent": "no first look is recorded for this story", "null": f"the first look was not walked ({got.get('null', '').replace('_', ' ')})",
                "stale": "the first look is about other code or another list of requirements than the current ones",
                "unreadable": "the record of the first look cannot be read",
                "error": "the record of the first look could not be read"}[state["kind"]]
        lines.append(f"The factory cannot count what the stand showed: {said}.")
    else:
        share = FL.share(task_root, {})
        lines.append(f"The stand showed {share['reachable']} of {share['counted']} requirements"
                     + (f" ({share['share']}%)" if share["share"] is not None else "") + ".")
        lines.append(f"Every requirement, by what the stand answered: {status_counts(got['rows'])}.")
        stuck = [r for r in got["rows"] if r.get("status") == "unreachable"]
        lines += ["", "## Requirements the stand did not reach", ""]
        if not stuck:
            lines.append("None.")
        for row in stuck:
            reason = " ".join(str(row.get("why") or "no reason given").split())
            lines.append(f"- {row.get('req')}: {reason}" + (f" (stopped by: {row['blocked_by']})" if row.get("blocked_by") else ""))
            for path in row.get("evidence") or []:
                lines.append(f"  evidence: {path}")
            if row.get("quote"):
                lines.append(f"  quote: {' '.join(str(row['quote']).split())[:200]}")
    heads = got.get("source_head") or {}
    lines += ["", "## The code the first look was about", ""]
    lines += [f"- {repo}: {short_head(head)}" for repo, head in sorted(heads.items())] or ["- no implementation is recorded for it"]
    lines += ["", "## How to answer", ""] + restart_lines(command, "Nothing to answer now. ")
    lines += ["", "To go on with the plan as it is, or to end the wait, say so in the conversation."]
    return "\n".join(lines) + "\n"


def write_first_look(task_root, command: str = "", out=None) -> Path:
    """Write `first_look_packet` to the story root as `interim-report.md` - the same file the S5 packet is, one writer (AR-14) - and
    return its path. The `await` record names it by file name."""
    task_root = Path(task_root)
    path = Path(out) if out else task_root / PACKET_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(first_look_packet(task_root, command), encoding="utf-8")
    return path


def write(task_root, command: str = "", out=None) -> Path:
    """Write the document (the one writer of `interim-report.md`) and return its path."""
    task_root = Path(task_root)
    path = Path(out) if out else task_root / PACKET_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(build(task_root, command)), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="Assemble interim-report.md for a story held for code (data only).")
    ap.add_argument("--task-root", required=True)
    ap.add_argument("--command", default="", help="the command that starts the story again, as the driver spells it")
    ap.add_argument("--out", help="write here instead of <task root>/interim-report.md")
    ap.add_argument("--json", action="store_true", help="print the data and write nothing")
    args = ap.parse_args()
    root = Path(args.task_root)
    if not root.is_dir():
        print(f"interim_packet: {root} is not a story folder; pass --task-root <qa-factory/artifacts/<ticket>>", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(build(root, args.command), indent=1, sort_keys=True))
        return 0
    print(write(root, args.command, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
