#!/usr/bin/env python3
"""t-2181 PC-7 (F-6): `interim_packet.py` assembles `interim-report.md` for a story held for code, from data only (FAST).

A tiny story folder is built on disk (pipeline, manifest, run blocks); the packet is built and rendered. Each check is a field of the
data or a line of the document; none asks whether a placeholder is reasonable (that stays the code critic's).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import human_text  # noqa: E402
import interim_packet as IP  # noqa: E402

ABSENT = {"sides": {"backend": {"reality": "absent", "deliverable": True, "source": "launch"},
                    "ui": {"reality": "real", "deliverable": True, "source": "launch"}}}


def story(root: Path, manifest=None, pipeline=None, blocks=()) -> Path:
    task = root / "QA-700"
    (task / "work" / "run-blocks").mkdir(parents=True, exist_ok=True)
    (task / "pipeline.json").write_text(json.dumps(ABSENT if pipeline is None else pipeline), encoding="utf-8")
    if manifest is not None:
        (task / "work" / "automation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for i, block in enumerate(blocks):
        (task / "work" / "run-blocks" / f"2026110{i}T000000Z-b{i}.json").write_text(json.dumps(block), encoding="utf-8")
    return task


MANIFEST = {
    "tests": [{"instance_id": "test_a", "case": "TC-1", "covers": ["TC-1"], "file": "tests/t.py",
               "sides": {"backend": "absent", "ui": "real"}},
              {"instance_id": "test_b", "case": "TC-2", "covers": ["TC-2"], "file": "tests/t.py", "sides": {"ui": "real"}}],
    "unresolved": [{"case": "TC-1", "reason": "pending_implementation", "instance_ids": ["test_a"]}],
    "provisional": [{"id": "P-1", "kind": "placeholder_locator", "what": "the cart badge selector", "settles_on": "backend",
                     "status": "open", "home": {"file": "tests/pages.py", "line_hint": 3}},
                    {"id": "P-2", "kind": "side_substitute", "what": "a mock of the orders service", "settles_on": "backend",
                     "status": "kept_by_decision", "home": {"file": "tests/mocks.py"}},
                    {"id": "P-3", "kind": "placeholder_locator", "what": "an old one", "settles_on": "backend",
                     "status": "retracted", "home": {"file": "tests/old.py"}}],
    "runs": [{"kind": "collect", "label": "c1", "partial": True}],
}


def packet_data() -> None:
    root = temp_dir("qa-interim-")
    try:
        blocks = [{"block_id": "r0", "kind": "collect", "results": [{"instance_id": "test_a", "status": "collected"}]},
                  {"block_id": "r1", "sides_met": {"ui": "real", "backend": "substituted"},
                   "results": [{"instance_id": "test_b", "status": "passed"}]}]
        data = IP.build(story(root, MANIFEST, blocks=blocks), "python story_run.py --task QA-700")
        by = {t["instance_id"]: t for t in data["tests"]}
        check_eq("the sides are listed with their reality", [(s["name"], s["reality"]) for s in data["sides"]],
                 [("backend", "absent"), ("ui", "real")])
        check_eq("a test whose instance is pending reads `waits`", (by["test_a"]["waits"], by["test_b"]["waits"]), (True, False))
        check_eq("a collect block is a collect, not a run", by["test_a"]["run"]["kind"], "collect")
        check_eq("a run block's stamp is carried as data", by["test_b"]["run"]["stamp"], {"ui": "real", "backend": "substituted"})
        check_eq("the open and the kept rows are listed, the retracted one too as data", [r["id"] for r in data["provisional"]],
                 ["P-1", "P-2", "P-3"])
        check_eq("the collect row of the manifest is counted", data["collects"], 1)
        text = IP.render(data)
        check_in("the document names the waiting side", "backend: absent", text)
        check_in("a collect says nothing ran", "collected only, nothing ran", text)
        check_in("a run on a substitute is reported as such, never as a verdict", "ran with a substitute or a missing side (backend substituted)", text)
        check_in("an open placeholder is in the user's words", "the cart badge selector", text)
        check_in("a kept placeholder says it was kept by decision", "kept as it is by decision", text)
        check_not_in("a retracted placeholder is not listed as standing in", "an old one", text)
        check_in("the restart command sits in the how-to-answer block", "## How to answer", text)
        check_in("... with the driver's command", "python story_run.py --task QA-700 --branch", text)
        body = text.split("\n## How to answer")[0]
        check_eq("the body obeys the human-text rules (report kind)", human_text.problems(body, kind="report"), [])
    finally:
        cleanup(root)


def edges() -> None:
    root = temp_dir("qa-interim-edge-")
    try:
        data = IP.build(story(root, None), "")
        check_eq("no manifest: an empty list, not a refusal", data["tests"], [])
        text = IP.render(data)
        check_in("... and the document says so", "No test is recorded for this story yet.", text)
        check_in("... and says no placeholder is recorded", "No placeholder is recorded.", text)
        check_not_in("no command given: no invented command", "--branch <the branch", text)
        unknown = IP.build(story(root, MANIFEST, blocks=[{"block_id": "r1", "sides_unknown": "registry unreadable",
                                                          "results": [{"instance_id": "test_b", "status": "passed"}]}]), "")
        row = next(t for t in unknown["tests"] if t["instance_id"] == "test_b")
        check_in("a block under sides_unknown is never read as real", "not known", IP._ran_words(row["run"]))
        plain = IP.build(story(root, MANIFEST, blocks=[{"block_id": "r1", "results": [{"instance_id": "test_b", "status": "passed"}]}]), "")
        row = next(t for t in plain["tests"] if t["instance_id"] == "test_b")
        check_in("a block with no stamp says it recorded nothing about the sides", "recorded nothing about the sides", IP._ran_words(row["run"]))
        check_eq("no block: not run", IP._ran_words(None), "not run")
        task = story(root, MANIFEST)
        (task / "work" / "run-blocks" / "bad.json").write_text("{not json", encoding="utf-8")
        check_eq("an unreadable block is named, not fatal", IP.build(task, "")["unreadable_blocks"], ["bad.json"])
    finally:
        cleanup(root)


def writer() -> None:
    root = temp_dir("qa-interim-write-")
    try:
        task = story(root, MANIFEST)
        path = IP.write(task, "cmd")
        check_eq("the one writer puts the document at the story root", path, task / "interim-report.md")
        check_in("... and it holds the story's id", "QA-700", path.read_text(encoding="utf-8"))
        before = sorted(p.name for p in task.iterdir())
        IP.build(task, "cmd")
        check_eq("`build` writes nothing (FR-45)", sorted(p.name for p in task.iterdir()), before)
        argv, sys.argv = sys.argv, ["interim_packet.py", "--task-root", str(root / "nowhere")]
        try:
            check_eq("the CLI refuses a folder that is not there with exit 2", IP.main(), 2)
        finally:
            sys.argv = argv
    finally:
        cleanup(root)


def one_reader() -> None:
    """F4 (AR-13): the packet reads the story's JSON through `hooklib.read_json`, not through a private copy - and an unreadable or
    non-object file still reads as nothing there (a BOM too), so a story with a broken pipeline.json still gets a packet."""
    source = Path(IP.__file__).read_text(encoding="utf-8")
    check_not_in("no private JSON reader is left in interim_packet.py", "def _load(", source)
    check_in("the package's one reader is used", "hooklib.read_json(", source)
    root = temp_dir("qa-interim-reader-")
    try:
        task = story(root, MANIFEST)
        (task / "pipeline.json").write_text("﻿[1, 2]", encoding="utf-8")        # a BOM and a list: not an object
        data = IP.build(task, "cmd")
        check_eq("a pipeline.json that is not an object reads as nothing there (the default side only)",
                 [(s["name"], s["reality"]) for s in data["sides"]], [("product", "real")])
    finally:
        cleanup(root)


def first_look_packet_lists_unreachable() -> None:
    """t-2277 FL-6: the packet of a story stopped after the first look - the count, the unreachable requirements with the evidence the
    walker cited, the heads and the day it stopped, the restart command; an unreadable record is ONE line and no count (AR-28)."""
    import first_look as FL
    import grounding_table as GT
    root = temp_dir("qa-interim-first-look-")
    try:
        task = story(root, None, pipeline={"awaiting": {"cause": "first_look_stop", "held_from": "S3", "since": "2026-11-10T10:00:00+00:00"}})
        (task / "work" / "requirements-register.md").write_text(
            "# Requirements register\n\n## Register\n\n| ID | Requirement | Source |\n|---|---|---|\n"
            + "".join(f"| R-{n} | The stand shows R-{n}. | task |\n" for n in (1, 2, 3)), encoding="utf-8")
        (task / "work" / "context-manifest.json").write_text(json.dumps({"implementations": [{"repo_id": "product", "source_sha": "a" * 40}]}), encoding="utf-8")
        heads, reg = FL.current_keys(task)
        GT.write_yaml(FL._record_path(task), {
            "walked_at": "2026-11-10T09:00:00+00:00", "walk": "w1", "stand": "dev", "stand_build": "not_established", "source_head": json.loads(heads),
            "register_hash": reg, "gaps": [],
            "rows": [{"req": "R-1", "status": "confirms", "why": "the page shows it"},
                     {"req": "R-2", "status": "unreachable", "blocked_by": "product", "why": "the route answers 404", "evidence": ["captures/r2.png"],
                      "quote": "page not found"},
                     {"req": "R-3", "status": "missing", "blocked_by": "product", "why": "no such button"}]})
        text = IP.first_look_packet(task, "python story_run.py --task QA-700")
        check_in("the first look's own title", "# First look report for QA-700", text)
        check_in("the count of what the stand showed", "The stand showed 1 of 3 requirements (33.3%).", text)
        check_in("every status counted", "confirms 1, contradicts 0, missing 1, unreachable 1", text)
        check_in("the unreachable requirement with its reason and blocker", "- R-2: the route answers 404 (stopped by: product)", text)
        check_in("... the capture the walker cited", "evidence: captures/r2.png", text)
        check_in("... and the words quoted from it", "quote: page not found", text)
        check_not_in("a missing requirement is not listed among the unreachable ones", "no such button", text)
        check_in("the head the look was about, cut for a person", "- product: aaaaaaa", text)
        check_in("the day the story stopped", "stopped on 2026-11-10", text)
        check_in("the restart command sits in the how-to-answer block", "python story_run.py --task QA-700 --branch", text.split("## How to answer")[1])
        check_eq("the body obeys the human-text rules (report kind)", human_text.problems(text.split("\n## How to answer")[0], kind="report"), [])
        check_not_in("no S5 words in it", "placeholder", text)
        before = sorted(p.name for p in task.iterdir())
        IP.first_look_packet(task, "")
        check_eq("`first_look_packet` writes nothing (FR-45)", sorted(p.name for p in task.iterdir()), before)
        check_not_in("no command given: no invented command", "--branch <the branch", IP.first_look_packet(task, ""))
        check_eq("the one writer puts it in the interim report's file", IP.write_first_look(task, "cmd"), task / "interim-report.md")
        FL._record_path(task).write_text("rows: [{broken", encoding="utf-8")
        said = IP.first_look_packet(task, "")
        check_in("an unreadable record is one line, no count", "The factory cannot count what the stand showed", said)
        check_not_in("... and no invented number", "requirements (", said)
        FL._record_path(task).unlink()
        check_in("an absent record says so", "no first look is recorded for this story", IP.first_look_packet(task, ""))
        check_in("an unreadable record says so in words (no parser text, no path)", "the record of the first look cannot be read", said)
        check_not_in("... no record path", "first-look.yaml", said)
        # t-2528 F5/N2: a head that is not a commit is words, never the stored value or its field name; no stop day on the hold is not a date
        manifest = {"implementations": [{"repo_id": "product"}]}
        (task / "work" / "context-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        heads, reg = FL.current_keys(task)
        GT.write_yaml(FL._record_path(task), {"walked_at": "2026-11-10T09:00:00+00:00", "walk": "w1", "stand": "dev", "stand_build": "not_established",
                                              "source_head": json.loads(heads), "register_hash": reg, "gaps": [],
                                              "rows": [{"req": "R-1", "status": "confirms", "why": "the page shows it"}]})
        (task / "pipeline.json").write_text(json.dumps({"ticket": "QA-700", "awaiting": {"cause": "first_look_stop", "held_from": "S3"}}), encoding="utf-8")
        shown = IP.first_look_packet(task, "cmd")
        check_in("an unmeasured head reads as no commit recorded", "- product: no commit recorded", shown)
        check_not_in("... never the stored value or the field name", "source_sha", shown)
        check_in("no stop day on the hold: 'an earlier day', not today", "stopped on an earlier day after the first look", shown)
        check_eq("one spelling of a head", (IP.short_head("a" * 40), IP.short_head("unmeasured: x"), IP.short_head(None)), ("aaaaaaa", "no commit recorded", "no commit recorded"))
    finally:
        cleanup(root)


def main() -> int:
    first_look_packet_lists_unreachable()
    packet_data()
    edges()
    writer()
    one_reader()
    return finish("test_interim_packet")


if __name__ == "__main__":
    sys.exit(main())
