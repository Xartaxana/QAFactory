#!/usr/bin/env python3
"""t-423 (r0107, the owner's word 31.10.2026): screenshots are the person's, not the repository's. The paths reach the person
at gate B, on both roads, through ONE section of `gate_brief.py --gate B`; no delivered file carries one.

Keys (written before the first run): SG-1 both roads print the section; SG-2 no picture: no section; SG-3 the report says `provided`
only for a picture the section lists (one reader, every scenario); SG-4 the packet is a reading: it writes nothing, and the
files a person never gets (`state/driver-question.md`) are not in the delivery manifest; SG-5 the ledger line carries no link
or path, the machine record keeps its own; SG-6 the section is in the person's words (`human_text`), whole, never cut.

Mutations (named, run by the integrator, one killing file each - this one):
  m1 gate_brief.render_gate_b: the screenshots section is not added                          -> SG-1
  m2 report_facts._manual_shots: `provided` counted by anything but the files the list holds  -> SG-3
  m3 ledger.render: the manual-evidence line writes the link `[post_action](evidence/..)` again -> SG-5
  m4 report_facts.screenshot_section: the list is cut at N cases                              -> SG-6
  m5 report_facts.screenshot_section: the section is printed with no picture                  -> SG-2
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, run_script  # noqa: E402

import test_report_facts as TR  # noqa: E402  (its fixtures: a story with manual-agent cases and exported pictures)

RF, GB = TR.RF, TR.GB
import human_text  # noqa: E402
import ledger as L  # noqa: E402
import grammar as G  # noqa: E402

HEAD = "## Screenshots of the manual checks"


def put_rows(task: Path, rows: list) -> None:
    TR.write(task / "work" / "run-report.json", dict(TR.RUN_REPORT, current_manual_checks=rows, manual_checks=rows))


def section_of(packet: str) -> str:
    """The lines from the section's heading to the next heading."""
    lines = packet.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.strip() == HEAD), None)
    if start is None:
        return ""
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[start:end])


def tree(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


def picture(task: Path, case: str, attempt: str, label: str, phase: str = "pre_action", export: bool = True) -> dict:
    ref = TR.evidence(task, case, attempt, label, phase)
    if export:
        TR.export_ref(task, ref)
    return ref


def parity(name: str, task: Path, rows: list) -> str:
    """SG-3: for every case, `screenshots: provided` in the report line <=> every picture the case took is a path in the packet's
    section; and no path of the section is a file that is not there. Returns the packet."""
    packet = GB.render_gate_b("T-1", task)
    section = section_of(packet)
    block = TR.block_of(task)
    for case in sorted({r["case"] for r in rows}):
        line = TR.case_line(block, case)
        pics = [ref for r in rows if r["case"] == case for ref in r["evidence_refs"] if str(ref["path"]).lower().endswith(".png")]
        listed = all(str(task.resolve() / RF._export_path(ref)) in section for ref in pics if RF._export_path(ref))
        usable = all(RF._export_path(ref) for ref in pics)
        said = RF.SHOTS_PROVIDED in line
        check_eq(f"SG-3 {name} {case}: provided <=> every taken picture is in the section", said, bool(pics) and listed and usable)
    for raw in section.splitlines():
        if raw.startswith("- ") and ": " in raw:
            for path in raw.split(": ", 1)[1].split(", "):
                check(f"SG-3 {name}: a listed path is a file on disk ({path[-40:]})", Path(path).is_file(), path)
    return packet


def sg1_both_roads_and_edges() -> None:
    task = TR.manual_story(with_rows=False)
    try:
        rows, refs = TR.k4_rows(task)
        put_rows(task, rows)
        before = tree(task)
        packet = GB.render_gate_b("T-1", task)
        section = section_of(packet)
        check_in("SG-1 the skill road: gate B's brief has the section", HEAD, packet)
        for key in ("pre1", "post1", "pre2"):
            check_in(f"SG-1 ... with the absolute path of {key}", str(task.resolve() / RF._export_path(refs[key])), section)
        check_not_in("SG-1 ... and not the text capture (not a picture)", RF._export_path(refs["dom1"]), section)
        check("SG-1 ... after the judge lines and before the long documents' list",
              packet.index(HEAD) < packet.index("## The long documents"), packet)
        check_in("SG-1 ... under its case, with the case's Then so the id is explained", 'TC-001 (The subscription reads cancelled.): ', section)
        # the driver road runs the SAME command as a child and pastes its output (`Driver.gate_text`): the CLI prints the section whole
        done = run_script("gate_brief.py", "--task", "T-1", "--gate", "B", cwd=task.parents[2],
                          env=dict(__import__("os").environ, CLAUDE_PROJECT_DIR=str(task.parents[2])))
        check_eq("SG-1 the driver road's child process exits 0", done.returncode, 0)
        check_in("SG-1 ... and prints the section with the paths", str(task.resolve() / RF._export_path(refs["pre1"])), done.stdout)
        check_eq("SG-4 reading the packet writes nothing (the paths reach the person, not a file)", tree(task), before)
        # SG-3 on the base scenario, then four more
        parity("exported", task, rows)
        # SG-6 the section in the person's words and never cut
        found = human_text.problems(section, kind="report")
        check_eq("SG-6 the section breaks no rule of human-questions.md", [p["rule"] for p in found], [])
        many = []
        for n in range(1, 31):
            many.append(TR.manual_row("TC-001", "OB-1", "pass", f"w{n}", [picture(task, "TC-001", f"b{n}", "001-pre")], TR.CLAIM,
                                      attempt_id=f"b{n}"))
        put_rows(task, many)
        listed = RF.screenshot_groups(task)
        check_eq("SG-6 thirty records of one case: all thirty pictures are in the list, none cut", len(listed[0][1]), 30)
        check_eq("SG-6 ... and thirty paths in the section of the packet", section_of(GB.render_gate_b("T-1", task)).count(".png"), 30)
    finally:
        cleanup(task.parents[2])


def sg2_no_picture_no_section() -> None:
    task = TR.manual_story(with_rows=False)
    try:
        state = TR.evidence(task, "TC-001", "a1", "001-state", "post_action", kind="state", payload=b"{}", ext=".json", proves=["completion"])
        TR.export_ref(task, state)
        put_rows(task, [TR.manual_row("TC-001", "OB-1", "pass", "the API said cancelled", [state], TR.CLAIM)])
        packet = GB.render_gate_b("T-1", task)
        check_not_in("SG-2 an API check took no picture: no section, nothing is promised", HEAD, packet)
        check_in("SG-2 ... and the report says none were taken", RF.SHOTS_NONE, TR.block_of(task))
    finally:
        cleanup(task.parents[2])
    plain = TR.story()
    try:
        check_not_in("SG-2 a story with no manual case: no section", HEAD, GB.render_gate_b("T-1", plain))
        check_eq("SG-2 ... and the section function is empty", RF.screenshot_section(plain), [])
        check_eq("SG-2 ... a root that is no folder: empty, no raise", isinstance(RF.screenshot_section(plain / "nowhere"), list), True)
    finally:
        cleanup(plain.parents[2])


def sg3_parity_scenarios() -> None:
    """A second record, a bad hash, a refused export (the file never copied) and a clean checkout: each its own row; `provided` is
    never said for a picture the section does not list."""
    task = TR.manual_story(with_rows=False)
    try:
        a = picture(task, "TC-001", "a1", "001-pre")
        b = picture(task, "TC-001", "a2", "001-pre", export=False)            # the second record's picture was never copied
        rows = [TR.manual_row("TC-001", "OB-1", "pass", "x", [a], TR.CLAIM),
                TR.manual_row("TC-001", "OB-1", "pass", "y", [b], TR.CLAIM, attempt_id="a2")]
        put_rows(task, rows)
        packet = parity("second record", task, rows)
        check_in("SG-3 second record: the report line is not provided", RF.SHOTS_NO_COPY, TR.case_line(TR.block_of(task), "TC-001"))
        check_not_in("SG-3 ... and the section lists only the copy there is", RF._export_path(b), packet)
        TR.export_ref(task, b)
        parity("second record exported", task, rows)
    finally:
        cleanup(task.parents[2])
    task = TR.manual_story(with_rows=False)
    try:
        good = picture(task, "TC-001", "a1", "001-pre")
        bad = dict(picture(task, "TC-001", "a1", "002-post", "post_action"), content_hash="short")
        rows = [TR.manual_row("TC-001", "OB-1", "pass", "x", [good, bad], TR.CLAIM)]
        put_rows(task, rows)
        parity("bad hash", task, rows)
        check_in("SG-3 bad hash: not provided, and not 'none were taken'", RF.SHOTS_NO_COPY, TR.case_line(TR.block_of(task), "TC-001"))
    finally:
        cleanup(task.parents[2])
    task = TR.manual_story(with_rows=False)
    try:
        first = picture(task, "TC-001", "a1", "001-pre", export=False)       # a refused export: the copy is not there at all
        rows = [TR.manual_row("TC-001", "OB-1", "pass", "x", [first], TR.CLAIM)]
        put_rows(task, rows)
        packet = parity("refused export", task, rows)
        check_not_in("SG-3 a refused export: no section is printed for a picture nobody can open", HEAD, packet)
    finally:
        cleanup(task.parents[2])


def sg4_not_in_delivery() -> None:
    import delivery_manifest as M
    task = TR.story()
    try:
        TR.write(task / "state" / "driver-question.md", "# Gate B\n" + str(task) + "/evidence/x.png\n")
        TR.write(task / "state" / "events.jsonl", '{"type": "seed"}\n')
        files = [r["path"] for r in M.build(task)["files"]]
        check("SG-4 the driver's question file (it holds the packet) is not in the delivery manifest",
              "state/driver-question.md" not in files, str(files))
        check("SG-4 ... nor are the packet's own per-question records", not any(p.startswith("state/driver-question") for p in files), str(files))
    finally:
        cleanup(task.parents[2])


def sg5_ledger_line() -> None:
    row = {"case": "TC-001", "result": "pass", "expected": ["e"], "actual": "a",
           "evidence_refs": [{"path": "evidence/abc.png", "phase": "pre_action", "kind": "image"},
                             {"path": "evidence/def.png", "phase": "post_action", "kind": "image"},
                             {"path": "evidence/t.txt", "phase": "supporting", "kind": "log"}]}
    ledger = {"ticket": "T-1", "rows": [], "manual_evidence": {"rows": [row], "errors": []}, "coverage": {}}
    text = L.render(ledger)
    line = next((ln for ln in text.splitlines() if ln.startswith("- TC-001")), "")
    check_in("SG-5 the ledger line says provided, in the report's own words", RF.SHOTS_PROVIDED, line)
    for key in (".png", "evidence/", "](", ".txt"):
        check_not_in(f"SG-5 the ledger line has no link or path ({key})", key, line)
    none = dict(row, evidence_refs=[{"path": "evidence/t.txt", "phase": "post_action", "kind": "state"}])
    line = next(ln for ln in L.render(dict(ledger, manual_evidence={"rows": [none], "errors": []})).splitlines() if ln.startswith("- TC-001"))
    check_in("SG-5 an API check: none were taken, the same sentence as the report's", G.SHOTS_NONE, line)
    check_eq("SG-5 the machine record keeps its paths (the ledger's JSON is not read by a person)",
             json.loads(json.dumps(ledger))["manual_evidence"]["rows"][0]["evidence_refs"][0]["path"], "evidence/abc.png")


def main() -> None:
    sg1_both_roads_and_edges()
    sg2_no_picture_no_section()
    sg3_parity_scenarios()
    sg4_not_in_delivery()
    sg5_ledger_line()
    finish("test_screenshots_gate_b")


if __name__ == "__main__":
    main()
