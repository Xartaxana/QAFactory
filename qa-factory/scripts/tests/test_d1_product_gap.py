"""D1-C2 (t-1697 RN1-15 / t-1727 addendum Q1-Q3): the product-gap door, its word, its one writer and the report's exclusion.

K-C1a  the door on a `case_environment` finding (`Rehearsal.door(row=)`, `check_case_environment_gaps`), E-C2', E-C9, E-C11, FR-7
K-C1b  `Driver.read_finding_doors` reads `<id>: product gap` (E-C19 at and beyond the separator boundary)
K-C1d  the closed block `finding_door_words` (AR-1): one word, disjoint from every other list of the vocabulary file
K-C2   `Driver._record_door_lines` writes the carrier through `product_gaps.py`, never `waiver.py`; revoke; E-C10..E-C14
K-C3   `report_facts._skipped_by_plan` / `_not_proven` leave a recorded product gap out; the verdict head still names it

Mutations (named, NOT run; one killing file, this one):
  m1 story_run `_record_door_lines`: delete the `continue` after the product_gap branch (waiver.py is called)  -> K-C2 (the stub's `py` raises)
  m2 gate_preflight: `set(reqs) <= decided` becomes `set(reqs) & decided`                                    -> K-C1a (R-23 + R-24, one recorded)
  m3 report_facts `_not_proven`: delete `item["id"] in gap_ids or`                                            -> K-C3
  m4 story_run `read_finding_doors`: drop the `said[len(key)] in ...` guard                                   -> K-C1b (`product gapx`)
  m5 product_gaps `record`: write without the `_load` problem check                                           -> K-C2d (the malformed bytes change)

K-C1b-id (D1-C2 fix round): `story_run.Driver._FINDING_LINE_RE` matches the ordinal id (`case_environment-1`) and the subject id
(`case_environment-TS-23`, `vcs-test-repo`).
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import check_delivery as CD  # noqa: E402
import gate_brief  # noqa: E402
import gate_preflight  # noqa: E402
import hooklib  # noqa: E402
import product_gaps as PG  # noqa: E402
import report_facts as RF  # noqa: E402
import story_run  # noqa: E402


def write_plan(root: Path, rows: list) -> None:
    (root / "work").mkdir(parents=True, exist_ok=True)
    (root / "work" / "test-plan.json").write_text(json.dumps(rows), encoding="utf-8")


def gapped(row_id: str, refs=None) -> dict:
    row = {"id": row_id, "coverage_obligations": [{"obligation_id": "OB-1", "parts": [{"part_id": "p1", "status": "unresolved"}],
                                                   "remaining_gap": "no export button"}]}
    if refs is not None:
        row["requirement_refs"] = refs
    return row


def carrier(root: Path) -> Path:
    return root / "work" / CD.PRODUCT_GAPS_FILE


def findings_of(root: Path) -> tuple:
    r = gate_preflight.Rehearsal(root, "A")
    r.check_case_environment_gaps()
    return r.findings, r.info


def with_vocab(replacement):
    """A context-free patch of `hooklib.load_ref_json`: returns (undo,) - `replacement(real_result)` is what the readers see."""
    real = hooklib.load_ref_json

    def patched(name, *a, **k):
        return replacement(real(name, *a, **k)) if name == "question-vocabulary.json" else real(name, *a, **k)
    hooklib.load_ref_json = patched
    return lambda: setattr(hooklib, "load_ref_json", real)


def door_of(finding: dict) -> dict:
    return [d for d in finding.get("waives") or [] if d.get("option") == "product_gap"][0]


def k_c1a_the_door() -> None:
    root = temp_dir("d1pg-door-")
    try:
        write_plan(root, [gapped("TS-23", ["R-23"])])
        found, _info = findings_of(root)
        f = found[0]
        check_eq("K-C1a: the id is the row's", f["id"], "case_environment-TS-23")
        check_eq("K-C1a: the door is a product_gap door carrying the row", f["waives"],
                 [{"block": "product gap TS-23", "stage": "S5", "option": "product_gap", "row": "TS-23"}])
        check_in("K-C1a: the fix names the finding's own id with the word", "`case_environment-TS-23: product gap`", f["fix"])
        check_not_in("K-C1a: the fix never prints the literal `<id>` (the D1-B defect)", "<id>", f["fix"])
        check_in("K-C1a: accepting the gap and holding the row stay offered", "accept the gap", f["fix"])

        # E-C2': a row that names no requirement gets no door and no product-gap word
        write_plan(root, [gapped("TS-24")])
        f = findings_of(root)[0][0]
        check("E-C2': no `waives` on a row with no requirement", not f.get("waives"))
        check_not_in("E-C2': and no product-gap word in the fix", "product gap", f["fix"])
        check_eq("E-C2': the fix is the one from before D1-B", f["fix"], "answer with your approval: accept the gap, or hold the row back")
        # adversarial: the requirement only in prose, an empty list
        write_plan(root, [dict(gapped("TS-25", []), reason="see R-23 in the text")])
        check("E-C2': an R-n named only in prose is no requirement of the row", not findings_of(root)[0][0].get("waives"))

        # FR-7: a recorded gap is not asked again; one of two requirements recorded still asks (all, not any)
        write_plan(root, [gapped("TS-23", ["R-23"])])
        carrier(root).write_text(json.dumps({"gaps": [{"requirement": "R-23", "words": "no such button", "words_ref": "", "gate": "A"}]}),
                                 encoding="utf-8")
        found, info = findings_of(root)
        check_eq("K-C1a: a recorded product gap leaves no finding", found, [])
        check_eq("K-C1a: ... and one note says so", [i["message"] for i in info if i["check"] == "case_environment"],
                 ["TS-23: the product gap you recorded for R-23 stands; not asked again"])
        # F7 (t-1752): a row with TWO gapped obligations, its requirement recorded: ONE note (not one per obligation), no finding
        two = gapped("TS-23", ["R-23"])
        two["coverage_obligations"].append({"obligation_id": "OB-2", "parts": [{"part_id": "p2", "status": "unresolved"}], "remaining_gap": "no import"})
        write_plan(root, [two])
        found, info = findings_of(root)
        check_eq("K-C1a (F7): two gapped obligations, the requirement recorded: no finding and exactly ONE note",
                 (found, [i["message"] for i in info if i["check"] == "case_environment"]),
                 ([], ["TS-23: the product gap you recorded for R-23 stands; not asked again"]))
        write_plan(root, [gapped("TS-23", ["R-23", "R-24"])])
        check_eq("K-C1a: R-23 + R-24 with only R-23 recorded still asks", [f["id"] for f in findings_of(root)[0]], ["case_environment-TS-23"])
        # E-C11: a malformed carrier suppresses nothing
        carrier(root).write_text("{not json", encoding="utf-8")
        write_plan(root, [gapped("TS-23", ["R-23"])])
        check_eq("E-C11: a malformed carrier never suppresses the question", [f["id"] for f in findings_of(root)[0]],
                 ["case_environment-TS-23"])
        carrier(root).unlink()

        # E-C9: the word list absent -> no door anywhere, no word in the text
        undo = with_vocab(lambda data: {k: v for k, v in (data or {}).items() if k != "finding_door_words"})
        try:
            f = findings_of(root)[0][0]
        finally:
            undo()
        check("E-C9: no block, no door", not f.get("waives"))
        check_not_in("E-C9: ... and no word the code cannot read", "product gap", f["fix"])
        # a door of the old shape is byte-for-byte what it was (no `row` key)
        r = gate_preflight.Rehearsal(root, "A")
        r.door("a block")
        check_eq("K-C1a: `door()` with no row adds no `row` key", r._doors[0], {"block": "a block", "stage": "S5", "option": "accept"})
    finally:
        cleanup(root)


def packet_for(finding: dict) -> str:
    return f"[{finding['id']}] {' '.join(finding['message'].split())}"


def read(words: str, findings: list) -> dict:
    stub = SimpleNamespace(_FINDING_LINE_RE=story_run.Driver._FINDING_LINE_RE)
    shown = "\n".join(packet_for(f) for f in findings)
    doors = {f["id"]: [d for d in f.get("waives") or [] if isinstance(d, dict)] for f in findings}
    return story_run.Driver.read_finding_doors(stub, words, findings, shown, doors)


def k_c1b_the_reader() -> None:
    gap = {"id": "case_environment-1", "check": "case_environment", "message": "TS-23 carries a declared gap",
           "waives": [{"block": "product gap TS-23", "stage": "S5", "option": "product_gap", "row": "TS-23"}]}
    stand = {"id": "stand_gap-1", "check": "stand_gap", "message": "a stand gap",
             "waives": [{"block": "stand gap: PC-1", "stage": "S5", "option": "any"}]}
    one = lambda text: read(f"case_environment-1: {text}", [gap, stand])   # noqa: E731
    got = one("product gap")
    check_eq("K-C1b: `product gap` is read with the product_gap option", [(e["word"], e["reason"]) for e in got["read"]],
             [("product_gap", "")])
    check_eq("K-C1b: the entry carries the finding's own door (the row travels)", got["read"][0]["door"]["row"], "TS-23")
    got = one("product gap, the export button was never built")
    check_eq("K-C1b: a reason after a separator is kept whole", [(e["word"], e["reason"]) for e in got["read"]],
             [("product_gap", "the export button was never built")])
    check_eq("K-C1b: `?` is a question, never consent", (one("product gap?")["read"], len(one("product gap?")["unread"])), ([], 1))
    check_eq("K-C1b: the same line on a stand-gap finding (door option `any`) is unread",
             read("stand_gap-1: product gap", [gap, stand])["read"], [])
    check_eq("K-C1b: `accept` on the product-gap finding is unread (no fitting door, as today)", one("accept, fine")["read"], [])
    # E-C19: at and beyond the boundary
    check_eq("E-C19 AT: the word exactly is read", len(one("product gap")["read"]), 1)
    check_eq("E-C19 BEYOND: `product gapx` is not the word", (one("product gapx")["read"], len(one("product gapx")["unread"])), ([], 1))
    check_eq("E-C19 BEYOND: `product gaps` is not the word", one("product gaps")["read"], [])
    check_eq("E-C19: `product gap.` is read (a closing `.` is dropped)", len(one("product gap.")["read"]), 1)
    check_eq("E-C19: a synonym alone is read", [e["word"] for e in one("no such function")["read"]], ["product_gap"])
    check_eq("E-C19: a synonym as a first word is never read", one("not implemented here")["read"], [])
    # F7 (t-1752): the reader's door-word step is `gate_brief.finding_door_option`, tested directly at and beyond the boundary
    opt = gate_brief.finding_door_option
    check_eq("F7 E-C19 AT: the word (and a closing `.`) -> the option, no reason", (opt("product gap"), opt("`Product Gap`."), opt("no such function")),
             (("product_gap", ""), ("product_gap", ""), ("product_gap", "")))
    check_eq("F7 E-C19: a separator and a reason: the reason is kept whole, by the spelling of the text",
             (opt("product gap, the export button was never built"), opt("product gap - Not Built: yes")),
             (("product_gap", "the export button was never built"), ("product_gap", "Not Built: yes")))
    check_eq("F7 E-C19 BEYOND: a letter after the word, a synonym as a first word, empty, None -> no option",
             (opt("product gapx"), opt("product gaps"), opt("not implemented here"), opt(""), opt(None)), (("", ""),) * 5)
    check_eq("F7: the rows may be handed in (the reader reads the block once): an empty list reads nothing", opt("product gap", []), ("", ""))
    check_eq("K-C1b: a stand-gap word still reads as before", [e["word"] for e in read("stand_gap-1: accept", [gap, stand])["read"]],
             ["accept"] if read("stand_gap-1: accept", [gap, stand])["read"] else [])
    # E-C2': a finding with NO door (a row with no requirement) leaves the line unread
    bare = dict(gap, waives=[])
    got = read("case_environment-1: product gap", [bare])
    check_eq("E-C2': on a finding with no door the line is unread and named", (got["read"], len(got["unread"])), ([], 1))
    # K-C1b-id (D1-C2 item 1): a SUBJECT id is a finding line; membership among the shown findings still decides
    sub = dict(gap, id="case_environment-TS-23")
    check_eq("K-C1b-id: the id `case_environment-TS-23` is read as a finding line",
             [e["word"] for e in read("case_environment-TS-23: product gap", [sub])["read"]], ["product_gap"])
    check_eq("K-C1b-id: the colon with spaces around it (`id : word`) is read",
             len(read("case_environment-TS-23 : product gap", [sub])["read"]), 1)
    repo = {"id": "vcs-test-repo", "check": "vcs", "message": "the repo is not the one",
            "waives": [{"block": "vcs block", "stage": "S5", "option": "accept"}]}
    check_eq("K-C1b-id: `vcs-test-repo: accept <reason>` on a shown finding is read",
             [(e["word"], e["reason"]) for e in read("vcs-test-repo: accept the branch is right", [repo])["read"]],
             [("accept", "the branch is right")])
    other = read("vcs-other-repo: accept the branch is right", [repo])
    check_eq("K-C1b-id: a subject id not among the shown findings is unread (not this reader's line)",
             (other["read"], other["unread"]), ([], []))
    check_eq("K-C1b-id: a subject id with a trailing `?` is unread (a question)",
             (read("case_environment-TS-23: product gap?", [sub])["read"], len(read("case_environment-TS-23: product gap?", [sub])["unread"])),
             ([], 1))
    check_eq("K-C1b-id: an id ending with `-` is not a finding line",
             story_run.Driver._FINDING_LINE_RE.match("case_environment-: product gap"), None)
    check_eq("K-C1b-id: an upper-case first letter is not a finding line (as before)",
             story_run.Driver._FINDING_LINE_RE.match("Case_environment-1: product gap"), None)
    check_eq("K-C1b-id: the ordinal form still matches (pin)",
             story_run.Driver._FINDING_LINE_RE.match("case_environment-1: product gap").group("id"), "case_environment-1")


def k_c1d_the_block() -> None:
    check_eq("K-C1d: the one word", gate_brief.finding_door_word_of(), {"product_gap": "product gap"})
    mine = {gate_brief._word_key(w) for row in gate_brief.finding_door_words() for w in [row["word"], *row["synonyms"]]}
    others = set()
    for row in gate_brief.stand_gap_words(lasting=True):
        others |= {gate_brief._word_key(w) for w in [row["word"], *row["synonyms"]]}
    for row in gate_brief.environment_words() + gate_brief.exploratory_question_words():
        others |= {gate_brief._word_key(w) for w in [row["word"], *row.get("synonyms", [])]}
    check_eq("K-C1d: no word or synonym of the block belongs to another list", mine & others, set())
    undo = with_vocab(lambda data: dict(data, finding_door_words={"answers": [{"option": "accept", "word": "x"}, {"option": "product_gap", "word": " "}]}))
    try:
        check_eq("K-C1d: a row outside FINDING_DOOR_OPTIONS or with no word is dropped", gate_brief.finding_door_words(), [])
    finally:
        undo()


def entry(row: str = "TS-23", line: str = "case_environment-TS-23: product gap, no button") -> dict:
    return {"id": "case_environment-TS-23", "line": line, "word": "product_gap", "reason": "", "replaced": [],
            "door": {"block": "product gap TS-23", "stage": "S5", "option": "product_gap", "row": row}}


def stub_for(root: Path, calls: list):
    def py(*args, **kwargs):
        calls.append(args)
        raise AssertionError("waiver.py must never be called for a product gap")

    def words_file(words, name):
        folder = root / "state" / "words"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"driver-{name}-{len(list(folder.iterdir()))}.txt"
        path.write_text(words, encoding="utf-8")
        return path
    return SimpleNamespace(py=py, words_file=words_file, task_root=root, task="T-1")


def k_c2_the_recorder() -> None:
    root = temp_dir("d1pg-rec-")
    try:
        write_plan(root, [gapped("TS-23", ["R-23"]), gapped("TS-24", ["R-24"]), gapped("TS-25"), gapped("TS-26", ["R-26", "R-27"])])
        calls: list = []
        stub = stub_for(root, calls)
        recorded, failed, _cases = story_run.Driver._record_door_lines(stub, "A", [entry()], [], "S5")
        rows = json.loads(carrier(root).read_text(encoding="utf-8"))["gaps"]
        check_eq("K-C2: recorded, nothing failed", (recorded, failed), (["case_environment-TS-23"], []))
        check_eq("K-C2: one row, R-23, gate A, the person's line whole",
                 [(g["requirement"], g["gate"], g["words"]) for g in rows], [("R-23", "A", "case_environment-TS-23: product gap, no button")])
        check("K-C2: the words_ref file exists", (root / rows[0]["words_ref"]).is_file())
        check_eq("K-C2: the round trip through the delivery side's reader", CD._read_product_gaps(root)[1], "")
        check_eq("K-C2: ... and it reads the requirement", [g["requirement"] for g in CD._read_product_gaps(root)[0]], ["R-23"])
        check_eq("K-C2: waiver.py (`py`) was never called", calls, [])
        check("K-C2: no `stage_overrides` row is made (the driver has no pipeline.json change)", not (root / "pipeline.json").exists())

        story_run.Driver._record_door_lines(stub, "A", [entry(line="case_environment-TS-23: product gap, other words")], [], "S5")
        rows = json.loads(carrier(root).read_text(encoding="utf-8"))["gaps"]
        check_eq("K-C2b / E-C12: the same row twice is one row with the LAST words", [(g["requirement"], g["words"]) for g in rows],
                 [("R-23", "case_environment-TS-23: product gap, other words")])
        story_run.Driver._record_door_lines(stub, "B", [entry("TS-24", "case_environment-TS-24: product gap")], [], "S5")
        rows = json.loads(carrier(root).read_text(encoding="utf-8"))["gaps"]
        check_eq("K-C2c: a second row is a second requirement", sorted(g["requirement"] for g in rows), ["R-23", "R-24"])
        check_eq("K-C2c: ... recorded at its own gate", [g["gate"] for g in rows if g["requirement"] == "R-24"], ["B"])
        story_run.Driver._record_door_lines(stub, "A", [entry("TS-26", "x")], [], "S5")
        check_eq("E-C13: a row naming R-26 and R-27 records both", sorted(g["requirement"] for g in json.loads(carrier(root).read_text(encoding="utf-8"))["gaps"]),
                 ["R-23", "R-24", "R-26", "R-27"])

        # E-C2'/no row/no requirement at the writer: nothing recorded, the problem is the gate line's
        before = carrier(root).read_bytes()
        for what, ent in (("a row with no requirement", entry("TS-25")), ("an unknown row", entry("TS-99")), ("no row at all", entry(""))):
            rec, fail, _c = story_run.Driver._record_door_lines(stub, "A", [ent], [], "S5")
            check_eq(f"E-C2': {what} is failed, not recorded", (rec, len(fail)), ([], 1))
        check_eq("E-C2': ... and the carrier is unchanged", carrier(root).read_bytes(), before)

        # K-C2d / E-C11: a malformed carrier is never written over
        carrier(root).write_text("{broken", encoding="utf-8")
        before = carrier(root).read_bytes()
        rec, fail, _c = story_run.Driver._record_door_lines(stub, "A", [entry()], [], "S5")
        check_eq("K-C2d: a malformed carrier -> failed, not recorded", (rec, len(fail)), ([], 1))
        check_eq("K-C2d: the bytes are unchanged", carrier(root).read_bytes(), before)
        check_in("K-C2d: the reason names the file and says nothing is written over it", "nothing is written over it", fail[0][2])
        carrier(root).write_text(json.dumps({"gaps": "no list"}), encoding="utf-8")
        check_eq("K-C2d: `gaps` that is no list is refused too", len(story_run.Driver._record_door_lines(stub, "A", [entry()], [], "S5")[1]), 1)
        carrier(root).unlink()
        rec, _f, _c = story_run.Driver._record_door_lines(stub, "A", [entry()], [], "S5")
        check_eq("E-C10: an absent carrier is created", (rec, carrier(root).is_file()), (["case_environment-TS-23"], True))

        # E-C14: a failed write is never printed as recorded
        # (re-pinned, F4a t-1758: the writer is `event_store.atomic_json`, so the failing call is `os.replace` itself, no longer `PG.os`)
        import os
        real = os.replace
        os.replace = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
        try:
            rec, fail, _c = story_run.Driver._record_door_lines(stub, "A", [entry("TS-24", "x")], [], "S5")
        finally:
            os.replace = real
        check_eq("E-C14: a write that fails is failed, with the reason", (rec, len(fail)), ([], 1))
        check_in("E-C14: ... and the reason is the OSError's", "disk full", fail[0][2])
        check("E-C14: no temp file is left", not list((root / "work").glob("*.tmp")))

        # the pin: an `accept` door still goes to waiver.py
        asked: list = []
        pin = SimpleNamespace(py=lambda *a, **k: (asked.append(a) or (0, "ok")), waiver_road=lambda *a, **k: [], task="T-1", task_root=root,
                              words_file=stub.words_file)
        accept = {"id": "x-1", "line": "x-1: accept because", "word": "accept", "reason": "because", "replaced": [],
                  "door": {"block": "a block", "stage": "S5", "option": "accept"}}
        story_run.Driver._record_door_lines(pin, "A", [accept], [], "S5")
        check_eq("pin: an `accept` door still calls waiver.py once", [a[0] for a in asked], ["waiver.py"])
    finally:
        cleanup(root)


def k_c2e_revoke_and_the_cli() -> None:
    root = temp_dir("d1pg-cli-")
    try:
        write_plan(root, [gapped("TS-23", ["R-23"]), gapped("TS-24", ["R-24"])])
        words = root / "words.txt"
        words.write_text("the product has no export", encoding="utf-8")
        check_eq("CLI: record exits 0", PG.main(["record", "--task-root", str(root), "--row", "TS-23", "--gate", "A", "--words-file", str(words)]), 0)
        data = json.loads(carrier(root).read_text(encoding="utf-8"))
        check_eq("CLI: the words_ref is relative to the task root", data["gaps"][0]["words_ref"], "words.txt")
        check_eq("CLI: a bad row exits 2", PG.main(["record", "--task-root", str(root), "--row", "TS-99", "--gate", "A", "--words-file", str(words)]), 2)
        check_eq("CLI: a bad gate exits 2", PG.main(["record", "--task-root", str(root), "--row", "TS-23", "--gate", "C", "--words-file", str(words)]), 2)
        check_eq("CLI: a missing words file exits 2", PG.main(["revoke", "--task-root", str(root), "--requirement", "R-23", "--words-file", str(root / "no.txt")]), 2)
        check_eq("K-C2e: revoke exits 0", PG.main(["revoke", "--task-root", str(root), "--requirement", "R-23", "--words-file", str(words)]), 0)
        data = json.loads(carrier(root).read_text(encoding="utf-8"))
        check_eq("K-C2e: `gaps` no longer holds R-23", data["gaps"], [])
        check_eq("K-C2e: `revoked` holds it", [r["requirement"] for r in data["revoked"]], ["R-23"])
        check_eq("K-C2e: the delivery side's reader reads no gap now", CD._read_product_gaps(root), ([], ""))
        check_eq("K-C2e: an unknown requirement exits 2 and writes nothing", PG.main(["revoke", "--task-root", str(root), "--requirement", "R-9", "--words-file", str(words)]), 2)
        check_eq("CLI: no arguments exits 2", PG.main([]), 2)
        # row_ids: what must give [] and what must give exactly ['R-23']
        check_eq("row_ids: requirement_refs", PG.row_ids({"requirement_refs": ["R-23"]}), ["R-23"])
        check_eq("row_ids: an object ref", PG.row_ids({"requirement_refs": [{"ref": "R-23", "revision": 2}]}), ["R-23"])
        check_eq("row_ids: register: in risk_source_refs", PG.row_ids({"risk_source_refs": ["register:R-23"]}), ["R-23"])
        check_eq("row_ids: prose only, empty refs and a non-dict give []",
                 (PG.row_ids({"reason": "R-23 is meant"}), PG.row_ids({"requirement_refs": []}), PG.row_ids("R-23"), PG.row_ids(None)), ([], [], [], []))
    finally:
        cleanup(root)


def k_c3_the_report() -> None:
    reqs = {"items": [{"id": "R-23", "class": "deferred", "bases": [], "plan_row": "TS-23", "impact": "", "hypothesis": "", "partly": None,
                       "results": [], "cases": []}]}
    plan = [{"ts": "TS-23", "requirements": ["R-23"], "disposition": "skip", "reason": "low priority"}]
    ids = lambda rows: [r["id"] for r in rows]   # noqa: E731
    check_eq("K-C3 pin: with no gap ids R-23 is skipped by the plan", ids(RF._skipped_by_plan(reqs, plan, {})), ["R-23"])
    check_eq("K-C3: with gap_ids R-23 is not skipped by the plan", ids(RF._skipped_by_plan(reqs, plan, {}, gap_ids=frozenset({"R-23"}))), [])
    undecided = [{"ts": "TS-23", "requirements": ["R-23"], "disposition": "automate"}]
    check_eq("K-C3 pin: an undecided deferred R-23 is not proven", ids(RF._not_proven(reqs, undecided, {})), ["R-23"])
    check_eq("K-C3: with gap_ids R-23 is not in `not proven` either", ids(RF._not_proven(reqs, undecided, {}, gap_ids=frozenset({"R-23"}))), [])
    check_eq("K-C3: an unrelated gap id leaves R-23 where it was", ids(RF._not_proven(reqs, undecided, {}, gap_ids=frozenset({"R-99"}))), ["R-23"])
    led = {"word": "no", "ready": False, "owners": {"product": 1}, "limit_windows": 0, "items": [], "reds": [], "entities": [],
           "product_gaps": [{"requirement": "R-23", "words": "no export"}], "factory_coverage": 0}
    v = RF._verdict({"ledger": led, "requirements": None, "bugs": None, "tests": None})
    check_in("K-C3: the verdict head still names R-23 (D2-A's group 3)", "R-23", v["first_reason_full"])


def main() -> None:
    k_c1a_the_door()
    k_c1b_the_reader()
    k_c1d_the_block()
    k_c2_the_recorder()
    k_c2e_revoke_and_the_cli()
    k_c3_the_report()
    finish("d1_product_gap")


if __name__ == "__main__":
    main()
