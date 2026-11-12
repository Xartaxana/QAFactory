#!/usr/bin/env python3
"""Gate A names the attachments that were not turned into requirements (r0107 S6 step 1c, the owner's word of 30.10.2026).

Keys of the spec table (docs/tasks/specs/r0107-s6-v2-g2-11-tq1-17-20.md, step 1c): GA-1..GA-11. Every refusal or
unknown is shown next to the pass it pairs with. The fixture is the stand's story at gate A (`fixtures/run-12586-gate-a/`)
plus a `source-inventory.json` this test writes.

Mutations (named, run by the integrator, one killing file each - this one):
  m32 branch_accounting._attachment_state: a status with no row of `attachment_words` reads as opened   -> GA-6
  m33 gate_brief.render: the cap does not grow by the attachments block                                  -> GA-4
  extra: gate_brief._attachment_name_lines: a name is printed raw (no `attachment_name`)                  -> GA-7
  extra: branch_accounting.inventory_sources: an absent file reads as an empty list                       -> GA-6 (a corrupt file)

S6 node 1d (docs/tasks/specs/r0107-s6-1d-amendment-v2.md, section 6): GA-10 and DG-1..DG-7 - the block of the kept tickets none of whose
sentences obliges anything (the `T-` receipt is gone), a document is `(opened)` only when a call opens it (FR-18), the words that
leave a kept ticket out reach the conductor (DG-6), one card for a contradiction a file recorded (DG-7).
  m44 branch_accounting._ticket_attachments: `(opened)` for a file with a reason of the listing   -> DG-5
  m45 gate_brief.render: `_no_requirement_lines` not called when the attachments total is 0         -> DG-3
  m54 gate_brief._no_requirement_lines: the block without the tail of the first-line rule            -> DG-1

GA-5 (the conductor's row) is DG-6 now; `conductor.md` holds 11895 bytes against the cap of 11900 (`test_conductor_doors.py`).
"""
import json
import re
import shutil
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import FIXTURES, SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))

import branch_accounting as BA  # noqa: E402
import gate_brief as GB  # noqa: E402
import human_text  # noqa: E402
import story_run  # noqa: E402

FIX = FIXTURES / "run-12586-gate-a"
TASK = "TP1-12586"
WORD = GB.approval_words("A")[0]
HEAD = "## Attachments: not turned into requirements"
LABELS = ("the factory:", "you:", "the story:")


def story(prefix: str = "qa-ga-") -> tuple:
    base = temp_dir(prefix) / "qa-factory"
    root = base / "artifacts" / TASK
    shutil.copytree(FIX / "work", root / "work")
    shutil.copyfile(FIX / "pipeline.json", root / "pipeline.json")
    (root / "state").mkdir(parents=True)
    (base / "state" / "cost").mkdir(parents=True)
    (base / "config.json").write_text("{}", encoding="utf-8")
    return base, root


def att(name, status="read", analysis="read", media="image/png", **extra) -> dict:
    slug = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:40] + f"-{zlib.crc32(name.encode()):08x}"      # a name with a newline or 500 letters is no path
    ref = slug + (".pdf" if name.lower().endswith(".pdf") else "")
    item = {"attachment_id": f"id-{name}", "filename": name, "media_type": media, "status": status, "analysis_status": analysis,
            "local_ref": f"blobs/{ref}" if status == "read" else None, "analysis_reason": "Viewed: the form"}
    item.update(extra)
    return item


def source(key, items=(), relation="referenced", relevance="relevant", status="read", media_items=(), snapshot=True, **extra) -> dict:
    block = {"attachments": {"status": "read", "count": len(items), "items": list(items)},
             "external_media": {"status": "read", "count": len(media_items), "items": list(media_items)}}
    row = {"source_id": f"SRC-{key}", "canonical_ref": f"https://jira.example/browse/{key}", "relation": relation,
           "relevance": relevance, "status": status, "revision": "r1", "materials": block}
    if snapshot:
        row["snapshot_ref"] = f"sources/SRC-{key}/r1/ticket.json"
    row.update(extra)
    return row


def write_inventory(root: Path, *sources, files: bool = True) -> None:
    """The inventory, and (a file is opened only if it is there) a small file for every item the scout read."""
    (root / "work" / "source-inventory.json").write_text(json.dumps({"schema_version": 1, "sources": list(sources)}), encoding="utf-8")
    for src_ in sources if files else ():
        for block in ((src_.get("materials") or {}).values()):
            for item in (block.get("items") or []) if isinstance(block, dict) and isinstance(block.get("items"), list) else []:
                if isinstance(item, dict) and item.get("status") == "read" and item.get("local_ref"):
                    target = root / "work" / item["local_ref"]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(b"x")


def write_snapshot(root: Path, key: str, description: str) -> None:
    path = root / "work" / "sources" / f"SRC-{key}" / "r1" / "ticket.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"key": key, "title": "t", "description": description, "acceptance_criteria": [], "comments": []}),
                    encoding="utf-8")


def data_of(root: Path) -> dict:
    return GB.collect(TASK, root)


def brief(root: Path, **changes) -> str:
    return GB.render(dict(data_of(root), **changes))


def block_of(text: str) -> list:
    """The lines of the attachments block: from its head to its last line (the closing sentence of the answers, or the last
    line of the `not known` form)."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("## Attachments:")), None)
    if start is None:
        return []
    end = start + 1
    while end < len(lines) and lines[end].strip() != "":
        end += 1
    return lines[start:end]


def with_table(**changes):
    """Patch `BA.table` for one run: the data file with `changes` over it. Returns the restore function."""
    real = BA.table
    BA.table = lambda: dict(real(), **changes)
    return lambda: setattr(BA, "table", real)


INTRO = ("The factory turned the text of this ticket and of the tickets kept for it into requirements, sentence by sentence. "
         "It did not do that with their attachments, so a requirement that stands only in an attachment is in this plan only if "
         "you add it.")


def expected_block(n: int, lines: list, word: str = WORD) -> list:
    """The block of the spec (amendment 3.2), verbatim, written BEFORE the run and never derived from the code under test."""
    return ([f"{HEAD} ({n})", INTRO, *lines, "Do you want to add a requirement because of any of these?",
             f"(a) `{word}` - nothing to add; this also approves the plan and the cases as they stand.",
             "the factory: a record only; no agent works.",
             "you: nothing more.",
             "the story: what stands only in these attachments is not checked; the delivery verdict stays as the report has it.",
             f"(b) say which requirement, in your own words, instead of `{word}`.",
             "the factory: a helper reads your words and offers you the choices; then the requirements stage (S2) and the stages "
             "after it run again up to this gate.",
             "you: this answer, one more answer to choose, and one more look at this gate.",
             "the story: delivery waits until the gate is shown again.",
             GB.APPROVAL_FIRST_LINE_TAIL.format(what="these attachments")])


def three_sources(root: Path) -> None:
    write_inventory(
        root,
        source("TP1-12586", relation="task",
               items=[att("form.png"), att("notes.zip", status="skipped_by_policy", analysis="skipped_by_policy",
                                          skipped_by_policy="never", reason="skipped_by_policy:never")]),
        source("TP1-2", items=[att("mock.png", analysis="pending")]),
        source("TP1-3", items=[att("a.png"), att("huge.png", status="skipped_by_policy", analysis="skipped_by_policy",
                                                   skipped_by_policy="size", reason="skipped_by_policy:size")]))


# --- GA-1 .. GA-3 --------------------------------------------------------------------------------------------------

def ga_1_the_block_verbatim() -> None:
    base, root = story()
    try:
        three_sources(root)
        text = brief(root)
        want = expected_block(5, ["- TP1-12586: form.png (opened), notes.zip (not opened: this kind of file is not downloaded)",
                                  "- TP1-2: mock.png (not opened: not opened yet)",
                                  "- TP1-3: a.png (opened), huge.png (not opened: too large to download)"])
        check_eq("GA-1: three sources, five attachments -> the block of the spec, verbatim, names by ticket", block_of(text), want)
        check("GA-1: the block stands after the questions and before what is already decided",
              text.find(HEAD) > text.find("## ") and (text.find("Already decided") < 0 or text.find(HEAD) < text.find("Already decided")))
        # a linked ticket nobody kept is not listed, nor counted
        write_inventory(root, source("TP1-12586", relation="task", items=[att("form.png")]),
                        source("TP1-9", items=[att("other.png")], relevance="not_relevant"))
        check_eq("GA-1 pair: a ticket left out by the review is neither listed nor counted",
                 block_of(brief(root))[0], f"{HEAD} (1)")
        check_not_in("GA-1 pair: ...its name is not on the gate", "other.png", brief(root))
        # linked material (a link) is listed with the same words, its name through the short form
        write_inventory(root, source("TP1-12586", relation="task", items=[att("form.png")],
                                     media_items=[{"url": "https://git.example.com/team/repo/-/merge_requests/510?token=SECRET",
                                                   "status": "unavailable"}]))
        shown = " ".join(block_of(brief(root)))
        check_in("GA-1: a linked material is named by its short form and its state in words",
                 "(not opened: could not be read)", shown)
        check_not_in("GA-1: ...the query string (a login) is never shown", "SECRET", shown)
    finally:
        cleanup(base.parent)


def ga_2_empty_list_is_the_old_bytes() -> None:
    base, root = story()
    try:
        old = GB.render({k: v for k, v in data_of(root).items() if k != "attachments"})
        check_eq("GA-2 setup: no inventory on disk -> no block, the bytes of the package without the node", brief(root), old)
        write_inventory(root, source("TP1-12586", relation="task"), source("TP1-2"))
        data = data_of(root)             # an inventory on disk changes other parts of the packet (the rehearsal): the pair is the SAME data
        check_eq("GA-2: every ticket of the scope has no attachment (counts 0, keys read) -> the same bytes as without the node",
                 GB.render(data), GB.render({k: v for k, v in data.items() if k != "attachments"}))
        check_eq("GA-2: ...and the view says 0, known", (BA.attachments_view(root)["total"], BA.attachments_view(root)["known"]), (0, True))
    finally:
        cleanup(base.parent)


def ga_3_the_block_obeys_the_text_rules() -> None:
    base, root = story()
    try:
        three_sources(root)
        block = "\n".join(block_of(brief(root)))
        check_eq("GA-3: human_text.problems on the block is empty (a report: no head, no answer block)",
                 human_text.problems(block, kind="report"), [])
        check_eq("GA-3: price_problems is empty - every option carries the three lines in order", human_text.price_problems(block, [WORD]), [])
        for forbidden in ("blobs/", "analysis_", "SRC-", "local_ref", "skipped_by_policy"):
            check_not_in(f"GA-3: the block carries no `{forbidden}`", forbidden, block)
        # negative control: the same checker finds a price line missing
        broken = block.replace("the factory: a record only; no agent works.\n", "", 1)
        check("GA-3 control: with a price line cut, price_problems reports it", bool(human_text.price_problems(broken, [WORD])))
        write_inventory(root, source("TP1-12586", relation="task", items=[att("form.png")]))
        unknown = "\n".join(block_of(GB.render(dict(data_of(root), attachments={"state": "unreadable", "known": False,
                                                                                  "reason": "the list of the story's sources cannot be read",
                                                                                  "tickets": [], "total": 0}))))
        check_eq("GA-3: the `not known` block passes the shape rules too", human_text.shape_problems(unknown, kind="report"), [])
    finally:
        cleanup(base.parent)


# --- GA-4: the limit ------------------------------------------------------------------------------------------------

def many(n: int) -> list:
    return [att(f"p{i:03d}.png") for i in range(n)]


def names_listed(text: str) -> int:
    return len(re.findall(r"p\d{3}\.png \(opened\)", " ".join(block_of(text))))


def ga_4_the_limit_and_the_cap() -> None:
    base, root = story()
    try:
        write_inventory(root, source("TP1-12586", relation="task", items=many(16)))
        for shown, listed, more in ((15, 15, "(+1 more on TP1-12586)"), (16, 16, None), (1, 1, "(+15 more on TP1-12586)"),
                                    (10000, 16, None)):
            restore = with_table(attachments_shown=shown)
            try:
                text = brief(root)
            finally:
                restore()
            lines = block_of(text)
            check_eq(f"GA-4 at {shown}: `N` is always the full 16", lines[0], f"{HEAD} (16)")
            check_eq(f"GA-4 at {shown}: {listed} names listed", names_listed(text), listed)
            check_eq(f"GA-4 at {shown}: the `more` line", next((l for l in lines if l.startswith("- (+")), None),
                     None if more is None else f"- {more}")
        write_inventory(root, source("TP1-12586", relation="task", items=many(15)))
        check_eq("GA-4: 15 attachments at the limit 15 -> all fifteen, no `more` line", [names_listed(brief(root)),
                 any(l.startswith("- (+") for l in block_of(brief(root)))], [15, False])
        # the cap: a block of 215 lines does not push the document links out (m33)
        write_inventory(root, source("TP1-12586", relation="task", items=many(200)))
        restore = with_table(attachments_shown=10000)
        try:
            text = brief(root)
        finally:
            restore()
        check_eq("GA-4: 200 names are all shown", names_listed(text), 200)
        check_not_in("GA-4: the brief is not cut at its cap (the block raised it)", "brief truncated", text)
        # GW1-11 (the owner's word of 22.10.2026): the brief names no working file - the register link is gone; what stands below the
        # block and could be pushed out of the cap is the answer form
        check_in("GA-4: ...and the answer form below the block is alive", "## How to answer", text)
    finally:
        cleanup(base.parent)


# --- GA-5, GA-8, GA-11: the road of the answer -------------------------------------------------------------------------

def bare_driver():
    driver = object.__new__(story_run.Driver)
    driver.BOM = getattr(story_run.Driver, "BOM", "﻿")
    return driver


def ga_5_8_11_the_answer() -> None:
    driver = bare_driver()
    approving = {"approve": True, "Approve.": True, f"{WORD}\nplease also add the spec": True,
                 f"{WORD}\n\nA requirement: the form has a Reindex button": True}
    not_approving = ["Approve, add spec", "I want to add a requirement from the mockup", "nothing to add", "", "\n",
                     "the Reindex button is missing\napprove", "".join(chr(c) for c in range(0x43d, 0x441)), "x" * 10000]
    for words, wanted in approving.items():
        check_eq(f"GA-8: `{words[:40]!r}` starts with the approval word -> recorded by code: {wanted}", driver.gate_approval("gate_A", words), wanted)
    for words in not_approving:
        check_eq(f"GA-5/8: `{words[:30]!r}` is not the approval word -> it goes whole to the conductor (nothing recorded by code)",
                 driver.gate_approval("gate_A", words), False)
    base, root = story()
    try:
        three_sources(root)
        block = block_of(brief(root))
        tail = GB.APPROVAL_FIRST_LINE_TAIL.format(what="these attachments")
        check("GA-11: the tail line of the first-line rule stands AFTER (b)'s price lines",
              block.index(tail) > max(i for i, l in enumerate(block) if l.startswith("(b)")) + 3 and block[-1] == tail)
        b_lines = block[[i for i, l in enumerate(block) if l.startswith("(b)")][0]:][:4]
        check_in("GA-11: (b) names the helper that reads the words and offers the choices (first call of the conductor)",
                 "a helper reads your words and offers you the choices", b_lines)
        check_in("GA-11: ...and the second: the requirements stage and the stages after it run again", "(S2) and the stages after it run again",
                 b_lines)
        # no approval word (FR-59): the answer is a sentence, no token, no tail
        real = GB.approval_words
        GB.approval_words = lambda gate: ()
        try:
            bare = block_of(brief(root))
        finally:
            GB.approval_words = real
        check_in("GA-5 (no word): (a) reads `say that there is nothing to add`", "(a) say that there is nothing to add.", bare)
        check_in("GA-5 (no word): (b) drops `instead of`", "(b) say which requirement, in your own words.", bare)
        check_not_in("GA-11 (no word): the first-line tail is not printed", "unless your answer starts with the word", bare)
        check_eq("GA-5 (no word): the price lines stay", sum(1 for l in bare if l.startswith(LABELS)), 6)
    finally:
        cleanup(base.parent)


# --- GA-6, GA-7: unknown inputs and names --------------------------------------------------------------------------------

def ga_6_unknown_is_not_opened() -> None:
    base, root = story()
    try:
        write_inventory(root, source("TP1-12586", relation="task",
                                     items=[att("odd.png", analysis="weird"), att("none.png", analysis=None), att("ok.png")]))
        lines = " ".join(block_of(brief(root)))
        check_in("GA-6 (m32): an analysis status with no row of the data file is `not known`, never `opened`",
                 "odd.png (not opened: not known)", lines)
        check_in("GA-6: a missing analysis status is the `unknown` row (not opened yet)", "none.png (not opened: not opened yet)", lines)
        check_in("GA-6 pair: a known status is opened", "ok.png (opened)", lines)
        check_not_in("GA-6 (m32): the unknown one is not `(opened)`", "odd.png (opened)", lines)
        # a corrupt inventory: not `0`, not silence
        (root / "work" / "source-inventory.json").write_text("{not json", encoding="utf-8")
        text = brief(root)
        check_eq("GA-6: an inventory that does not parse -> the `not known` block", block_of(text)[0], "## Attachments: not known")
        check_in("GA-6: ...it says the factory's own gap and the one move", "That is the factory's own gap.", " ".join(block_of(text)))
        check_in("GA-6: ...with a cause in plain words, no path and no exception name",
                 "(the list of the story's sources cannot be read)", " ".join(block_of(text)))
        check_not_in("GA-6: ...no JSONDecodeError", "JSONDecodeError", text)
        (root / "work" / "source-inventory.json").write_text(json.dumps({"sources": {"a": 1}}), encoding="utf-8")
        check_eq("GA-6: `sources` is an object -> not known", block_of(brief(root))[0], "## Attachments: not known")
        (root / "work" / "source-inventory.json").write_text(json.dumps({"sources": [1]}), encoding="utf-8")
        check_eq("GA-6: an element that is no object -> not known", block_of(brief(root))[0], "## Attachments: not known")
        # a list that cannot be read for ONE ticket: the list, plus `- <KEY>: not known`
        bad = source("TP1-2")
        bad["materials"]["attachments"] = {"status": "read", "count": 3, "items": []}
        write_inventory(root, source("TP1-12586", relation="task", items=[att("ok.png")]), bad)
        partial = block_of(brief(root))
        check_eq("GA-6: count 3 with no items -> the list of the known, and the ticket named as not known", [partial[0], "- TP1-2: not known" in partial],
                 [f"{HEAD} (1)", True])
        write_inventory(root, bad)
        only = block_of(brief(root))
        check_eq("GA-6: nothing known and one ticket not known -> the `not known` block, not `(0)`", only[0], "## Attachments: not known")
        check_in("GA-6: ...with the cause of that ticket", "the attachments are counted (3) but not listed", " ".join(only))
        unreadable_status = source("TP1-2")
        unreadable_status["materials"]["attachments"] = {"status": "unknown", "count": None, "items": []}
        write_inventory(root, source("TP1-12586", relation="task", items=[att("ok.png")]), unreadable_status)
        check_in("GA-6: an attachment block whose status is `unknown` -> that ticket is not known", "- TP1-2: not known", block_of(brief(root)))
        # a kept ticket nobody could read: named, not counted as having none
        write_inventory(root, source("TP1-12586", relation="task", items=[att("ok.png")]),
                        {"source_id": "S", "canonical_ref": "https://jira.example/browse/TP1-7", "relation": "referenced",
                         "relevance": "unknown", "status": "unavailable", "materials": {"attachments": {"status": "unknown", "count": None, "items": []},
                                                                                    "external_media": {"status": "unknown", "count": None, "items": []}}})
        check_in("GA-6: a source nobody could read is `not known`, not zero", "- TP1-7: not known", block_of(brief(root)))
        # the data file damaged: the view says so; the gate says `not known`
        restore = with_table(attachment_words={"opened": "read"})
        try:
            view = BA.attachments_view(root)
            check_eq("GA-6: a damaged `attachment_words` -> the view is not known", (view["known"], view["state"]), (False, "unreadable"))
            check_eq("GA-6: ...and the gate says `not known`", block_of(brief(root))[0], "## Attachments: not known")
        finally:
            restore()
    finally:
        cleanup(base.parent)


def ga_7_names_are_data() -> None:
    base, root = story()
    try:
        names = ["line one\nline two", "x\n## How to answer\nstuff", "n" * 500, "`back` `ticks`", "".join(chr(c) for c in range(0x430, 0x436)) + ".png",
                 "a   b\t\tc"]
        write_inventory(root, source("TP1-12586", relation="task", items=[att(n) for n in names]))
        lines = block_of(brief(root))
        listed = [l for l in lines if l.startswith("- TP1-12586:")]
        check_eq("GA-7: the names stand on ONE line of the block", len(listed), 1)
        line = listed[0]
        check_not_in("GA-7: no line break, no heading mark inside the name", "\n", line)
        check("GA-7: no line of the block (but the head) starts a heading", not [l for l in lines[1:] if l.startswith("#")])
        check_not_in("GA-7: back quotes are removed from a name", "`back`", line)
        check_in("GA-7: ...the words stay", "back ticks (opened)", line)
        check_in("GA-7: a whitespace run is one space", "a b c (opened)", line)
        check_in("GA-7: 500 characters are cut to 80 with an ellipsis", "n" * 79 + "… (opened)", line)
        check_not_in("GA-7: ...not the whole name", "n" * 81, line)
        check_in("GA-7: a name in the person's own script is data and is shown", names[4], line)
        check_in("GA-7: `## How to answer` in a name is inside the one line", "x ## How to answer stuff (opened)", line)
        check_eq("GA-7: the block has exactly one answer form (the name did not add one)", sum(1 for l in lines if l.startswith("(a)")), 1)
        # the same function for a ticket key
        key_name = "TP3`CD\nME-1"                                  # the expectation is derived from this very input
        write_inventory(root, source(key_name, relation="task", items=[att("a.png")]))
        check_in("GA-7: a ticket key is cleaned the same way",
                 "- " + key_name.replace("`", "").replace("\n", " ") + ": a.png (opened)", block_of(brief(root)))
    finally:
        cleanup(base.parent)


# --- GA-9: what is new ---------------------------------------------------------------------------------------------------

def ga_9_new_since_the_last_time() -> None:
    base, root = story()
    try:
        three_sources(root)
        everything = GB.attachment_ids(BA.attachments_view(root))
        check_eq("GA-9 setup: `shown_attachments` lists `<KEY>: <name>`, in order", everything[:2], ["TP1-12586: form.png", "TP1-12586: notes.zip"])
        state = root / "state" / "driver-state.json"

        def asked(held):
            state.write_text(json.dumps({"shown_attachments": {"A": held}} if held is not None else {}), encoding="utf-8")
            return " ".join(block_of(brief(root)))
        check_not_in("GA-9: the gate was never recorded -> nothing is claimed new", "new since you last saw this list", asked(None))
        check_not_in("GA-9: shown before, nothing arrived since -> no line", "new since you last saw this list", asked(everything))
        text = asked(everything[:-1])
        check_in("GA-9: one arrived after the last show -> the line, with the name and the ticket", "new since you last saw this list: huge.png (TP1-3)", text)
        check_in("GA-9: ...the whole list is still shown (N stays full)", f"{HEAD} (5)", text)
        state.write_text("{broken", encoding="utf-8")
        check_not_in("GA-9: an unreadable record claims nothing new", "new since you last saw this list", " ".join(block_of(brief(root))))
        state.write_text(json.dumps({"shown_attachments": {"A": [1, 2]}}), encoding="utf-8")
        check_not_in("GA-9: a record of the wrong shape claims nothing new", "new since you last saw this list", " ".join(block_of(brief(root))))
        # the driver keeps what the packet named, AFTER the packet was built (the brief reads the previous record)
        driver = bare_driver()
        driver.task, driver.task_root, driver.state, driver.boundary = TASK, root, {}, ""
        driver.gate_rework_note = lambda gate: ""
        seen_state = []
        driver.gate_text = lambda gate: seen_state.append(dict(driver.state.get("shown_attachments") or {})) or "the packet"
        try:
            driver.gate("A")
            raised = None
        except story_run.Person as person:
            raised = person
        check("GA-9: Driver.gate raises the gate's question", raised is not None)
        check_eq("GA-9: Driver.gate keeps the names the packet showed under state[shown_attachments][A]",
                 driver.state["shown_attachments"]["A"], everything)
        check_eq("GA-9: ...and wrote them only AFTER the packet was built", seen_state, [{}])
        driver.state = {}
        driver.gate_text = lambda gate: "the packet"
        try:
            driver.gate("B")
        except story_run.Person:
            pass
        check_not_in("GA-9: gate B keeps no attachments record (the block is gate A's)", "shown_attachments", json.dumps(driver.state))
        (root / "work" / "source-inventory.json").write_text("{x", encoding="utf-8")
        check_eq("GA-9: an inventory that cannot be read records None, so the next gate claims nothing new", GB.shown_attachments(root), None)
    finally:
        cleanup(base.parent)


# --- GA-10: a ticket set aside by the tester ----------------------------------------------------------------------------------

NR_HEAD = "## Tickets you kept: no requirement taken from their text"
WHY = "a defect of the scheduler, not this sentence's contract"
REGISTER_AT_START = {}      # the fixture's register by path: every `put_register` starts again from it


def nr_block(text: str) -> list:
    """The zero-outcome block of the spec (2.3): from its head to the blank line after it."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith(NR_HEAD)), None)
    if start is None:
        return []
    end = start + 1
    while end < len(lines) and lines[end].strip() != "":
        end += 1
    return lines[start:end]


def put_register(root: Path, obligations=(), attachments=(), extra: str = "") -> None:
    """The fixture's register with a `## Source obligations` table, a `## Attachments` table and `extra` text written after it."""
    reg = root / "work" / "requirements-register.md"
    text = REGISTER_AT_START.setdefault(str(reg), reg.read_text(encoding="utf-8"))
    if obligations:
        text += f"\n\n{BA.OBLIGATIONS_HEADING}\n\n| unit | home |\n|---|---|\n" + "\n".join(f"| {u} | {h} |" for u, h in obligations) + "\n"
    if attachments:
        text += (f"\n\n{BA.ATTACHMENTS_HEADING}\n\n| attachment | ticket | reading | R | question | why |\n|---|---|---|---|---|---|\n"
                 + "\n".join(attachments) + "\n")
    reg.write_text(text + extra, encoding="utf-8")


def zero_rows(root: Path, *keys: str, why=WHY) -> list:
    """`(unit id, home)` of every unit of the tickets `keys`, each `not_obligation: <why>` (the zero outcome)."""
    return [(uid, f"not_obligation: {why}") for uid, held in BA.collect(root)["units"].items() if all(o["key"] in keys for o in held["occ"])]


def zero_outcome(root: Path, *keys: str, why=WHY) -> None:
    put_register(root, zero_rows(root, *keys, why=why))


def kept_tickets(root: Path, n: int, first: int = 200) -> list:
    """The story and `n` kept linked tickets of one sentence each; returns their keys."""
    keys = [f"TP1-{first + i}" for i in range(n)]
    for key in keys:
        write_snapshot(root, key, f"The {key} text is a statement about a scheduler defect.")
    write_inventory(root, source(TASK, relation="task"), *[source(key) for key in keys])
    return keys


def ga_10_no_requirement_block() -> None:
    """GA-10 / DG-1 (S6 1d, spec 2.3): the kept tickets none of whose sentences obliges anything are named in a block of their own."""
    base, root = story()
    try:
        three_sources(root)
        for key in ("TP1-2", "TP1-3"):
            write_snapshot(root, key, f"The {key} text is a statement about a scheduler defect.")
        zero_outcome(root, "TP1-2")
        text = brief(root)
        want = [f"{NR_HEAD} (1)", f"- TP1-2: read; no requirement taken from it: {WHY}",
                f"If one of them holds a requirement, say which, in your own words, instead of `{WORD}`.",
                GB.APPROVAL_FIRST_LINE_TAIL.format(what="these tickets")]
        check_eq("DG-1: N, `<why>`, the way to say a requirement, the tail of the first-line rule - the block of the spec, verbatim",
                 nr_block(text), want)
        check_eq("DG-1: human_text.problems on the block is empty (a report: one move, no options, no prices)",
                 human_text.problems("\n".join(nr_block(text)), kind="report"), [])
        check("DG-1: the block stands AFTER the attachments block, with a blank line between",
              text.index(HEAD) < text.index(NR_HEAD) and "\n\n" + NR_HEAD in text)
        check_in("GA-10: its attachment is still named (the zero outcome of a ticket does not take its files away)",
                 "- TP1-2: mock.png (not opened: not opened yet)", block_of(text))
        check_not_in("GA-10 pair: a ticket with its units not homed that way has no line", "TP1-3: read; no requirement", text)
        # `<word>` is data: no approval word -> a sentence with no `instead of`, and no tail (FR-59)
        real = GB.approval_words
        GB.approval_words = lambda gate: ()
        try:
            bare = nr_block(brief(root))
        finally:
            GB.approval_words = real
        check_eq("DG-1 (no word): no `instead of`, no tail", bare[2:], ["If one of them holds a requirement, say which, in your own words."])
        # the reasons differ: the first one, and the count of the others
        write_snapshot(root, "TP1-2", "A second sentence stands here. A third sentence stands here.")
        ids = [uid for uid, held in BA.collect(root)["units"].items() if held["occ"][0]["key"] == "TP1-2"]
        check_eq("GA-10 setup: the ticket reads as two units", len(ids), 2)
        put_register(root, [(ids[0], "not_obligation: a stack trace"), (ids[1], "not_obligation: a thread about the stand")])
        check_in("GA-10: two reasons -> the first and the count of the others", "- TP1-2: read; no requirement taken from it: a stack trace (and 1 other reasons)",
                 nr_block(brief(root)))
        put_register(root, [(ids[0], "not_obligation: a stack trace"), (ids[1], "R-1")])
        check_eq("GA-10 pair: one unit with a requirement keeps the ticket out of the block", nr_block(brief(root)), [])
        put_register(root, [(ids[0], "not_obligation: a stack trace"), (ids[1], "not_obligation: a stack trace")])
        check_in("GA-10 pair: the same reason twice is one reason", f"{NR_HEAD} (1)", nr_block(brief(root)))
        check_not_in("GA-10 pair: ...no count of others", "other reasons", " ".join(nr_block(brief(root))))
        # the text changed after S2: the old ids are gone, the ticket has units with no home -> no line
        write_snapshot(root, "TP1-2", "A different sentence, now.")
        check_eq("GA-10: the ticket's text changed -> the old homes cover nothing, no block", nr_block(brief(root)), [])
    finally:
        cleanup(base.parent)


def dg_2_the_limit() -> None:
    """DG-2: 15 / 16 / 1 / 10000 at `attachments_shown`; `N` is the full count."""
    base, root = story()
    try:
        keys = kept_tickets(root, 16)
        zero_outcome(root, *keys)
        for shown, listed, more in ((15, 15, "- (+1 more tickets read, with no requirement taken from them)"), (16, 16, None),
                                    (1, 1, "- (+15 more tickets read, with no requirement taken from them)"), (10000, 16, None)):
            restore = with_table(attachments_shown=shown)
            try:
                text = brief(root)
            finally:
                restore()
            lines = nr_block(text)
            check_eq(f"DG-2 at {shown}: `N` is always the full 16", lines[0], f"{NR_HEAD} (16)")
            check_eq(f"DG-2 at {shown}: {listed} tickets listed", sum(1 for l in lines if "read; no requirement taken from it" in l), listed)
            check_eq(f"DG-2 at {shown}: the `more` line", next((l for l in lines if l.startswith("- (+")), None), more)
            check_in(f"DG-2 at {shown}: the tail stands after the list", GB.APPROVAL_FIRST_LINE_TAIL.format(what="these tickets"), lines[-1:])
        restore = with_table(attachments_shown=10000)
        try:
            text = brief(root)
        finally:
            restore()
        check_not_in("DG-2: 16 lines of the block do not push the rest of the brief out of the cap", "brief truncated", text)
        check_in("DG-2: ...the answer form below the block is alive (GW1-11: no working-file links any more)", "## How to answer", text)
    finally:
        cleanup(base.parent)


def dg_3_4_alone_and_unknown() -> None:
    """DG-3: the block stands with no attachment listed; none of it without a ticket. DG-4: what cannot be read is named."""
    base, root = story()
    try:
        keys = kept_tickets(root, 1)
        zero_outcome(root, *keys)
        view = BA.attachments_view(root)
        check_eq("DG-3 setup: no attachment at all (total 0, known)", (view["total"], view["known"]), (0, True))
        text = brief(root)
        check_eq("DG-3: total 0 and a ticket with no requirement: the block and its tail are there", len(nr_block(text)), 4)
        check_eq("DG-3: ...and there is no attachments block", block_of(text), [])
        check_eq("DG-3: ...the tail stands once", text.count(GB.APPROVAL_FIRST_LINE_TAIL.format(what="these tickets")), 1)
        put_register(root)
        data = data_of(root)
        check_eq("DG-3: neither a listed attachment nor a ticket with no requirement: the bytes of the package without the node",
                 GB.render(data), GB.render({k: v for k, v in data.items() if k != "attachments"}))
        zero_outcome(root, *keys)
        write_inventory(root, source(TASK, relation="task", items=[att("form.png")]), source(keys[0]))
        both = brief(root)
        check_eq("DG-3 pair: both blocks, each with its own tail", (len(block_of(both)) > 0, len(nr_block(both)), both.count("unless your answer starts with the word")),
                 (True, 4, 2))
        # DG-4: a register that cannot be read: named, never an empty list
        real = BA._read_register
        BA._read_register = lambda task_root: (_ for _ in ()).throw(BA.Unreadable("boom"))
        try:
            broken = nr_block(brief(root))
        finally:
            BA._read_register = real
        check_eq("DG-4: a register that cannot be read -> `not known`, never an empty list", broken[:2],
                 [f"{NR_HEAD} (not known)", "- the tickets read with no requirement taken from them: not known (the register could not be read)"])
        # DG-4: an inventory that cannot be read: no second block (`## Attachments: not known` has said it once)
        (root / "work" / "source-inventory.json").write_text("{x", encoding="utf-8")
        text = brief(root)
        check_eq("DG-4: an inventory that cannot be read -> the attachments block says `not known` once, the other block is not there",
                 (text.count("## Attachments: not known"), nr_block(text)), (1, []))
    finally:
        cleanup(base.parent)


def dg_5_a_document_is_not_opened_by_the_scout_alone() -> None:
    """DG-5: gate A never says `(opened)` for a file no call of the listing opens, or one the tester did not open (FR-18)."""
    base, root = story()
    try:
        key = TASK
        items = [att("spec.md", media="text/markdown"), att("a.docx", media="application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                 att("big.txt", media="text/plain"), att("scan", media="application/pdf"), att("ok.pdf", media="application/pdf"),
                 att("lost.md", media="text/markdown"), att("gone.png")]
        write_inventory(root, source(key, relation="task", items=items))
        by_name = {i["filename"]: i for i in items}
        (root / "work" / by_name["big.txt"]["local_ref"]).write_bytes(b"x" * 30001)
        (root / "work" / by_name["lost.md"]["local_ref"]).unlink()
        line = lambda: next(l for l in block_of(brief(root)) if l.startswith(f"- {key}:"))     # noqa: E731
        got = line()
        for name, want in (("spec.md", "(opened)"), ("ok.pdf", "(opened)"), ("gone.png", "(opened)"),
                           ("a.docx", "(not opened: this file type cannot be opened here)"),
                           ("big.txt", "(not opened: too large to read at this stage)"),
                           ("scan", "(not opened: saved before this build could open a PDF)"),
                           ("lost.md", "(not opened: the file is missing)")):
            check_in(f"DG-5: {name} -> {want}", f"{name} {want}", got)
        for name in ("a.docx", "big.txt", "scan", "lost.md"):
            check_not_in(f"DG-5 (m44): {name} is never `(opened)` while the scout's line says read", f"{name} (opened)", got)
        # the tester's rows: `not_opened` and `rest` (the inventory only says the scout's bytes were read)
        put_register(root, attachments=[f"| spec.md | {key} | not_opened | - | - | Read answered: too long |",
                                        f"| ok.pdf | {key} | not_an_expectation | - | - | the scout's line says it is a log |",
                                        f"| gone.png | {key} | agrees | - | - | - |"])
        got = line()
        check_in("DG-5: a `not_opened` row -> the tool's answer", "spec.md (not opened: Read answered: too long)", got)
        check_in("DG-5 pair: `not_an_expectation` is as the receipt (opened)", "ok.pdf (opened)", got)
        check_in("DG-5 pair: `agrees` is as the receipt (opened)", "gone.png (opened)", got)
        put_register(root, attachments=[f"| ok.pdf | {key} | agrees | - | - | - |", "| rest | - | not_opened | - | - | the budget ended |"])
        got = line()
        check_in("DG-5: a `rest` row -> the files with no row of their own: `not opened: <why>`, a PDF too (F-9)", "spec.md (not opened: the budget ended)", got)
        check_in("DG-5: ...the PDF with no row of its own", "gone.png (not opened: the budget ended)", got)
        check_in("DG-5 pair: a file with its own row keeps the receipt", "ok.pdf (opened)", got)
        check_in("DG-5 pair: a file the listing has a reason for keeps THAT reason", "a.docx (not opened: this file type cannot be opened here)", got)
        # M5 branch (a): the key 0 gives `too large`; branch b: N > 0 -> `(opened in part)`; 30000 is whole, 30001 is the boundary
        put_register(root)
        restore = with_table(attachment_text_lines=50)
        try:
            part = line()
            (root / "work" / by_name["big.txt"]["local_ref"]).write_bytes(b"x" * 30000)
            whole = line()
        finally:
            restore()
        check_in("DG-5 (M5 branch b): a text file over the limit with `attachment_text_lines` 50 -> `(opened in part)`", "big.txt (opened in part)", part)
        check_in("DG-5 (M5 branch b) AT the limit (30000): whole, `(opened)`", "big.txt (opened)", whole)
        (root / "work" / by_name["big.txt"]["local_ref"]).write_bytes(b"x" * 30001)
        check_in("DG-5 (M5 branch a, key 0): the same file is `too large to read at this stage`", "big.txt (not opened: too large to read at this stage)", line())
        put_register(root, attachments=[f"| big.txt | {key} | not_opened | - | - | the start only was too little |"])
        restore = with_table(attachment_text_lines=50)
        try:
            check_in("DG-5 (M5 branch b): a part read, then `not_opened` by the tester -> `(not opened: ...)`",
                     "big.txt (not opened: the start only was too little)", line())
        finally:
            restore()
    finally:
        cleanup(base.parent)


def dg_6_the_words_reach_the_conductor() -> None:
    """DG-6: words that leave a kept ticket out are no approval; they go whole to the conductor, whose row names the commands.
    (Which model reads them is a live proof, not a test.)"""
    driver = bare_driver()
    for words in ("leave this ticket out: TP1-2", "no - TP1-2 holds a requirement", "remove TP1-2 from the plan"):
        check_eq(f"DG-6: `{words[:36]}` is not the approval word -> nothing is recorded by code", driver.gate_approval("gate_A", words), False)
    # (the conductor row that names leaving a kept ticket out is a row of design/role-rules.json)


def put_attachments_column(register: str, cells: dict) -> str:
    """The register with a column `attachments` appended to its contradiction matrix; `cells` = {R-n: cell}, the other rows `silent`."""
    out, inside = [], False
    for line in register.splitlines():
        if line.startswith("## "):
            inside = line.startswith("## Contradiction matrix")
        if inside and line.startswith("|"):
            first = line.split("|")[1].strip()
            line += (" attachments |" if first == "R" else "---|" if set(first) <= set("-: ") else f" {cells.get(first, 'silent')} |")
        out.append(line)
    return "\n".join(out) + "\n"


def dg_7_one_card() -> None:
    """DG-7: a contradiction a file recorded (cell + fork) is one card: the person's answer to `Q1` closes R-3, no second card about
    R-3 at the gate; without the fork row there is one (why the form check of the tester asks for the fork)."""
    base, root = story()
    try:
        reg = root / "work" / "requirements-register.md"
        text = reg.read_text(encoding="utf-8")
        old_row = next(l for l in text.splitlines() if l.startswith("| R-3 | silent |"))      # the matrix row (the register row of R-3 comes first)
        text = text.replace(old_row, "| R-3 | silent | silent | silent | n/a:no open bug found in the bundle |")
        text = put_attachments_column(text, {"R-3": 'contradicts:"Dedicated UI call to POST /v1/settings/transfer" (mock.png)'})
        reg.write_text(text, encoding="utf-8", newline="\n")
        rows = json.loads((root / "work" / "test-plan.json").read_text(encoding="utf-8"))["rows"]
        ids = lambda: [q["id"] for q in GB.contradiction_questions(root, rows)]        # noqa: E731
        import planning_contract as PC
        check("DG-7 setup: R-3's only contradiction is the file's cell (the quote is read from the new column)",
              PC.register_contradictions(text).get("R-3", "").startswith('contradicts:"Dedicated UI call'))
        check("DG-7 setup: ... and the cell is in the column `attachments`",
              ("R-3", "attachments") in [(r, c) for r, c, _q in PC.register_contradiction_cells(text)])
        check_eq("DG-7: the fork names Q1, Q1 is answered -> no card about R-3 (one question, one answer)", ids(), ["R-2", "TS-14"])
        reg.write_text(text.replace("| Q1 b adopted: outcome check |", "| question at gate A |"), encoding="utf-8", newline="\n")
        check_eq("DG-7 pair: without the fork row the second card about R-3 is there", ids(), ["R-3", "R-2", "TS-14"])
    finally:
        cleanup(base.parent)


# --- one reader (AR-13) and the data (AR-1) ------------------------------------------------------------------------------------

def one_reader_and_data() -> None:
    base, root = story()
    try:
        three_sources(root)
        # in_scope_sources, scope_attachments and attachments_view all answer from `inventory_sources` + `scope_class`
        check_eq("AR-13: the three readers agree on the kept tickets of one inventory",
                 sorted({t["key"] for t in BA.attachments_view(root)["tickets"]}),
                 sorted({"TP1-12586", "TP1-2", "TP1-3"}))
        write_inventory(root, source("TP1-12586", relation="task", items=[att("form.png")]),
                        source("TP1-2", items=[att("b.png")], relevance="not_relevant"),
                        source("TP1-3", items=[att("c.png")], status="excluded"))
        check_eq("AR-13: the story only; not_relevant and excluded are out for the attachments", [t["key"] for t in BA.attachments_view(root)["tickets"]], ["TP1-12586"])
        check_eq("AR-13: ...and for the units' scope (`left_out`)", sorted(k for k, _w in BA.in_scope_sources(root)["left_out"]), ["TP1-2", "TP1-3"])
        check_eq("AR-13: ...and for the files", [i["name"] for i in BA.scope_attachments(root)["items"]], ["form.png"])
        check_eq("AR-13: scope_class is one test for every reader", [BA.scope_class(s) for s in (
            {"relation": "task"}, {"relation": "task", "status": "excluded"}, {"relevance": "not_relevant"}, {"status": "excluded"},
            {"relevance": "relevant", "status": "read"}, {"relevance": "relevant", "status": "unavailable"}, {"relevance": "unknown", "status": "read"})],
            ["own", "own_out", "left_out", "left_out", "kept", "unread", "unread"])
        for word, key in (("too large to download", "skipped_by_policy:size"), ("this kind of file is not downloaded", "skipped_by_policy:never"),
                          ("this file type is not downloaded", "skipped_by_policy:type"), ("could not be read", "unavailable"),
                          ("left out", "skipped"), ("you left it out", "excluded"), ("not opened yet", "pending"), ("not opened yet", "unknown")):
            check_eq(f"AR-1: `{key}` has its plain words in the data file", BA.attachment_words()["causes"].get(key), word)
        check_eq("AR-1: the limit is data (15)", BA.limit("attachments_shown"), 15)
        check_eq("AR-1: a status with no row reads `not known`", BA._attachment_state({"status": "read", "analysis_status": "zzz"}, BA.attachment_words(), False),
                 (False, "not known"))
        check_eq("AR-1 pair: `read` is opened", BA._attachment_state({"status": "read", "analysis_status": "read"}, BA.attachment_words(), False), (True, ""))
        words = GB.attachment_question_words()
        check_eq("AR-1: the answer words are data: both rows read, each with its three price lines", sorted(words), ["nothing_to_add", "own_words"])
        restore = GB_vocab_damaged()
        try:
            check_eq("AR-1: damaged answer words -> {} (the packet then says `not known`)", GB.attachment_question_words(), {})
            three_sources(root)
            check_eq("AR-1: ...the gate says `not known`, never a question with no price lines", block_of(brief(root))[0], "## Attachments: not known")
        finally:
            restore()
    finally:
        cleanup(base.parent)


def GB_vocab_damaged():
    real = GB.hooklib.load_ref_json
    GB.hooklib.load_ref_json = lambda name, *a, **k: ({"attachment_question_words": {"nothing_to_add": {"says": "x"}}}
                                                    if name == "question-vocabulary.json" else real(name, *a, **k))
    return lambda: setattr(GB.hooklib, "load_ref_json", real)


# --- the fix round: what the tester recorded (F-1), partial knowledge (F-3, F-4), excluded (F-5), set aside alone (F-6) ---------

def with_images(root: Path, rows: list, aside=()) -> None:
    """The fixture's register with a `## Attachments` table, and the kept tickets `aside` homed as `not_obligation` (the zero outcome)."""
    put_register(root, zero_rows(root, *aside, why="a defect of another team") if aside else (), rows)


def fix_round_1_pictures_the_tester_did_not_open() -> None:
    base, root = story()
    try:
        key = "TP1-12586"
        write_inventory(root, source(key, relation="task", items=[att("m.png"), att("n.png"), att("k.png"), att("s.png"),
                                                                att("t.pdf", media="application/pdf")]))
        nothing = " ".join(block_of(brief(root)))
        check_in("F-1 pair: no `## Attachments` section -> the inventory's state stands, nothing is overlaid", "m.png (opened), n.png (opened)", nothing)
        rows = [f"| m.png | {key} | not_opened | - | - | Read answered: it is not an image |",
                f"| k.png | {key} | agrees | - | - | - |", f"| s.png | {key} | not_an_expectation | - | - | the scout says: a log |"]
        with_images(root, rows)
        line = next(l for l in block_of(brief(root)) if l.startswith(f"- {key}:"))
        check_in("F-1: a picture on a `not_opened` row is NOT `(opened)`, and says why", "m.png (not opened: Read answered: it is not an image)", line)
        check_not_in("F-1: ...the same picture is never printed as opened", "m.png (opened)", line)
        check_in("F-1 pair: `agrees` stays opened", "k.png (opened)", line)
        check_in("F-1 pair: `not_an_expectation` stays opened (it was looked at)", "s.png (opened)", line)
        check_in("F-1 pair: a picture with no row and no `rest` row keeps the inventory's state", "n.png (opened)", line)
        with_images(root, rows[1:] + ["| rest | - | not_opened | - | - | the budget ended |"])
        line = next(l for l in block_of(brief(root)) if l.startswith(f"- {key}:"))
        check_in("F-1: a `rest` row -> the pictures with no row of their own read `not opened: <why>`", "m.png (not opened: the budget ended", line)
        check_in("F-1: ...`n.png` too", "n.png (not opened: the budget ended", line)
        check_in("F-1 pair: a picture with its own `agrees` row stays opened under a `rest` row", "k.png (opened)", line)
        check_in("F-9: a PDF is a file with a call like any other: a `rest` row reaches it too", "t.pdf (not opened: the budget ended", line)
        # a kept ticket with the zero outcome: its files are still files the tester owes a row (S6 1d, F-9)
        write_inventory(root, source(key, relation="task", items=[att("form.png")]), source("TP1-2", items=[att("mock.png")]))
        write_snapshot(root, "TP1-2", "The TP1-2 text is a statement about a scheduler defect.")
        with_images(root, ["| rest | - | not_opened | - | - | the budget ended |"], aside=("TP1-2",))
        lines = block_of(brief(root))
        check_in("F-1: under a `rest` row the story's own picture is not opened", f"- {key}: form.png (not opened: the budget ended)", lines)
        check_in("F-9: ... and the picture of a ticket with no requirement taken from it is not opened either (no ticket-level exception)",
                 "- TP1-2: mock.png (not opened: the budget ended)", lines)
        # a `rest` row without its reason claims nothing (the S2 exit refuses it) and a broken table claims nothing
        with_images(root, ["| rest | - | agrees | - | - | x |"])
        check_in("F-1 pair: a `rest` row that reads something else is no `rest` row", f"- {key}: form.png (opened)", block_of(brief(root)))
    finally:
        cleanup(base.parent)


def fix_round_3_to_6_partial_knowledge() -> None:
    base, root = story()
    try:
        key = "TP1-12586"
        # F-3: the names of a ticket stay when ANOTHER block of it is not known; then the `not known` line
        half = source(key, relation="task", items=[att("a.png"), att("b.png")])
        half["materials"]["external_media"] = {"status": "unknown", "count": None, "items": []}
        write_inventory(root, half)
        lines = block_of(brief(root))
        check_eq("F-3: two attachments known, the links not known -> N is 2, the names stand, then the `not known` line",
                 [lines[0], f"- {key}: a.png (opened), b.png (opened)" in lines, f"- {key}: not known" in lines],
                 [f"{HEAD} (2)", True, True])
        check_in("F-3: ...the reason is grammatical: `the linked material was not read`", "the linked material was not read",
                 [BA.attachments_view(root)["tickets"][0]["reason"]])
        for block, kind, want in (("attachments", "attachments", "the attachments were not read"),
                                  ("external_media", "linked material", "the linked material was not read")):
            gone = source(key, relation="task")
            gone["materials"][block] = {"status": "unknown", "count": None, "items": []}
            check_eq(f"F-3 grammar: {kind}", BA._block_items(gone["materials"][block], kind)[1], want)
        check_eq("F-3 grammar: counted, not listed - linked material", BA._block_items({"count": 2, "items": []}, "linked material")[1],
                 "the linked material is counted (2) but not listed")
        # F-4: nothing listed, one ticket unknown -> the block names the ticket
        unread = {"source_id": "S", "canonical_ref": "https://jira.example/browse/CR-004", "relation": "referenced", "relevance": "unknown",
                  "status": "unavailable", "materials": {"attachments": {"status": "unknown", "count": None, "items": []},
                                                         "external_media": {"status": "unknown", "count": None, "items": []}}}
        write_inventory(root, source(key, relation="task"), unread)
        text = " ".join(block_of(brief(root)))
        check_in("F-4: the cause names the ticket that is not known (CR-004), not the story's own known ticket",
                 "(CR-004: the attachments were not read)", text)
        check_not_in("F-4: ...the known own ticket is not named as unknown", f"{key}: ", text)
        two = dict(unread, canonical_ref="https://jira.example/browse/CR-005")
        restore = with_table(attachments_shown=1)
        try:
            text = " ".join(block_of(brief_with(root, source(key, relation="task"), unread, two)))
        finally:
            restore()
        check_in("F-4 at the limit 1: one ticket named, the rest counted", "(CR-004: the attachments were not read; 1 more tickets)", text)
        # F-5: a link the person left out reads as what it is, never `not known`
        write_inventory(root, source(key, relation="task", media_items=[{"url": "https://h.example/x/b", "status": "excluded"},
                                                                       {"url": "https://h.example/x/c", "status": "never-heard-of"}]))
        shown = " ".join(block_of(brief(root)))
        check_in("F-5: an `excluded` link is listed as left out by the person", "(not opened: you left it out)", shown)
        check_in("F-5 pair: a status with no row is still `not known`", "(not opened: not known)", shown)
        # F-6 (a lone block for a `T-` ticket) became the block of its own: DG-3
    finally:
        cleanup(base.parent)


def brief_with(root: Path, *sources) -> str:
    write_inventory(root, *sources)
    return brief(root)


if __name__ == "__main__":
    ga_1_the_block_verbatim()
    ga_2_empty_list_is_the_old_bytes()
    ga_3_the_block_obeys_the_text_rules()
    ga_4_the_limit_and_the_cap()
    ga_5_8_11_the_answer()
    ga_6_unknown_is_not_opened()
    ga_7_names_are_data()
    ga_9_new_since_the_last_time()
    ga_10_no_requirement_block()
    dg_2_the_limit()
    dg_3_4_alone_and_unknown()
    dg_5_a_document_is_not_opened_by_the_scout_alone()
    dg_6_the_words_reach_the_conductor()
    dg_7_one_card()
    fix_round_1_pictures_the_tester_did_not_open()
    fix_round_3_to_6_partial_knowledge()
    one_reader_and_data()
    finish("test_gate_brief_attachments")
