#!/usr/bin/env python3
"""A bug the factory itself reproduced is not "nobody has reproduced it" (HF8-16, run 12586).

On 12586 the analyst saw TC-002 fail again three times (a rerun on fresh data, attempt a5ba, a `diagnostic` run) and the report
still said "nobody has reproduced it", "severity not recorded" and, for the requirement behind the other case's red, "no reason
recorded; bug not filed". The step `reproduced_by_factory` is derived by `bug_records.confirmation_of` from a typed receipt
(`reproduction` on the draft); a role's word without a receipt reads `unconfirmed`, and every error goes DOWN.

Keys: R1 the step, R2 the inconvenient inputs (one id each), R3 no verdict changes, R4 the count on every surface, R5 severity,
R6 the requirement behind another case's red, R7 an unknown word and the registry, R8 the vocabulary file, R9 the finding for a
receipt the code cannot read, R10 the limit of the cut.
"""
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import (FIXTURES, check, check_eq, check_in, check_not_in, cleanup,  # noqa: E402
                     finish, temp_dir)

import bug_records as BR  # noqa: E402
import contract as C  # noqa: E402
import delivery_summary as DS  # noqa: E402
import factory_dashboard as FD  # noqa: E402
import gate_brief as GB  # noqa: E402
import gate_preflight as GP  # noqa: E402
import report_facts as RF  # noqa: E402
import traceability as T  # noqa: E402

INSTANCE = "test_put_moves_integration"
OLD_TAIL = "unconfirmed \u2014 nobody has reproduced it; it counts toward nothing"
RUN = [{"instance_id": INSTANCE, "attempt_id": "a1", "purpose": "initial", "status": "failed"},
       {"instance_id": INSTANCE, "attempt_id": "a2", "purpose": "diagnostic", "status": "failed"}]
FRESH = {"kind": "fresh_data_rerun", "evidence": "evidence/rerun.log", "attempt_id": "a2",
         "observed": "400 Project mismatch again, new setting id"}
SCRIPT = {"kind": "own_script", "evidence": "evidence/script.json", "observed": "the same 400 from my own PUT"}


def build(root: Path, reproduction="absent", *, word="unconfirmed", run=RUN, verdict="APP_BUG", extra=None,
          files=True) -> Path:
    """One story: a draft for TC-002, its triage row, the run report, the receipt files."""
    (root / "qa-factory").mkdir(parents=True, exist_ok=True)
    (root / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
    task = root / "qa-factory" / "artifacts" / "QA-1"
    (task / "work" / "bug-drafts").mkdir(parents=True, exist_ok=True)
    (task / "evidence").mkdir(parents=True, exist_ok=True)
    (task / "pipeline.json").write_text(json.dumps({"ticket": "QA-1"}), encoding="utf-8")
    draft = {"title": "MS Teams integration cannot be moved", "impact": "degraded", "violates": "requirement:R-5",
             "case": "TC-002", "triage_ref": {"instance_id": INSTANCE, "attempt_id": "a1"},
             "manual_steps": ["move the integration to another project"], "confirmation": word}
    if reproduction != "absent":
        draft["reproduction"] = reproduction
    draft.update(extra or {})
    (task / "work" / "bug-drafts" / "move.json").write_text(json.dumps(draft), encoding="utf-8")
    (task / "work" / "triage.json").write_text(json.dumps({"triage": [
        {"test": "t::a", "instance_id": INSTANCE, "attempt_id": "a1", "case": "TC-002", "verdict": verdict,
         "evidence": "evidence/run.json"}]}), encoding="utf-8")
    (task / "work" / "run-report.json").unlink(missing_ok=True)   # the story folder is reused between cases
    if run is not None:
        (task / "work" / "run-report.json").write_text(json.dumps({"results": run}), encoding="utf-8")
    if files:
        (task / "evidence" / "rerun.log").write_text("400\n", encoding="utf-8")
        (task / "evidence" / "script.json").write_text("{}", encoding="utf-8")
        (task / "evidence" / "empty.log").write_text("", encoding="utf-8")
    return task


def record_of(task: Path) -> dict:
    return BR.story_bugs(task)["records"][0]


def r1_the_step() -> None:
    root = temp_dir("qa-repro-r1-")
    try:
        for label, field in (("absent", "absent"), ("[]", []), ("null", None)):
            rec = record_of(build(root, field))
            check_eq(f"R1 {label}: unconfirmed, no kinds, no reason", (rec["confirmation"], rec["reproduced_how"], rec["reproduction_problems"]),
                     ("unconfirmed", [], []))
            check_eq(f"R1 {label}: the old sentence, word for word", BR.reproduction_words(rec), OLD_TAIL)
        rec = record_of(build(root, [FRESH]))
        check_eq("R1 one valid rerun on a `diagnostic` row (the shape of run 12586, attempt a5ba): reproduced",
                 (rec["confirmation"], rec["state"], rec["reproduced_how"]), ("reproduced_by_factory", "reproduced", ["fresh_data_rerun"]))
        check_in("R1 ... and the sentence says it, and that no person has confirmed it", "no person has confirmed it yet", BR.reproduction_words(rec))
        check_not_in("R1 ... and never the old claim", "nobody has reproduced", BR.reproduction_words(rec))
        rec = record_of(build(root, [SCRIPT]))
        check_eq("R1 an own script needs no red row of the report: reproduced", rec["confirmation"], "reproduced_by_factory")
        both = record_of(build(root, [FRESH, SCRIPT]))
        check_in("R1 both kinds: both said, joined by and", "and the analyst's own script reproduced it", BR.reproduction_words(both))
        one_of_three = record_of(build(root, [FRESH, {"kind": "nope", "observed": "x", "evidence": "evidence/rerun.log"}, "text"]))
        check_eq("R1 one valid of three is a step (0 valid = none; 1 = there), the other two are named",
                 (one_of_three["confirmation"], one_of_three["reproduction_problems"]),
                 ("reproduced_by_factory", ["an unknown kind", "an entry that is not an object"]))
        filed = build(root, [FRESH], word="reproduced_by_factory")
        (filed / "bugs").mkdir(exist_ok=True)
        (filed / "bugs" / "BUG-1.md").write_text(
            "---\nid: BUG-1\ntitle: MS Teams integration cannot be moved\nimpact: degraded\nconfirmation: reproduced_by_factory\n"
            "source_draft: work/bug-drafts/move.json\ngate_b_decision_id: gateB-QA-1\n---\nbody\n", encoding="utf-8")
        recs = BR.story_bugs(filed)["records"]
        check_eq("R1 a filed bug that says reproduced_by_factory is checked against its draft: one record, reproduced",
                 [(r["id"], r["confirmation"]) for r in recs], [("BUG-1", "reproduced_by_factory")])
        (filed / "work" / "bug-drafts" / "move.json").unlink()
        gone = BR.story_bugs(filed)["records"][0]
        check_eq("R1 ... and with its draft gone the word reads unconfirmed, with the reason", (gone["confirmation"], gone["reproduction_problems"]),
                 ("unconfirmed", ["the draft of this bug is not there"]))
        # HF816-noreceipt (t-428): the draft is there but holds no `reproduction` at all, and the filed bug claims the step
        build(root, "absent", word="reproduced_by_factory")
        bare = BR.story_bugs(filed)["records"][0]
        check_eq("R1 a filed bug claiming the step whose draft has no receipts: unconfirmed, the reason is named",
                 (bare["confirmation"], bare["reproduction_problems"]), ("unconfirmed", ["no reproduction receipt behind it"]))
        # HF816-dedup (t-428): two entries with the same fault name it once
        twice = record_of(build(root, [dict(FRESH, kind="nope"), dict(FRESH, kind="nope")]))
        check_eq("R1 two entries with the same fault: the reason is named once", twice["reproduction_problems"], ["an unknown kind"])
        # HF816-kinds-dedup (t-436): the kinds of the valid receipts are a set of words, each once, in the order first seen
        many_task = build(root, [FRESH, SCRIPT, dict(FRESH), dict(SCRIPT)])
        many = record_of(many_task)
        check_eq("R1 four valid receipts of two kinds: each kind named once, in the order first seen",
                 (many["confirmation"], many["reproduced_how"]), ("reproduced_by_factory", ["fresh_data_rerun", "own_script"]))
        check_eq("R1 ... the same through the reader a surface calls",
                 BR.confirmation_of(many_task, json.loads((many_task / "work" / "bug-drafts" / "move.json").read_text(encoding="utf-8")))[1],
                 ["fresh_data_rerun", "own_script"])
        # HF816-words-cut (t-436): `cut` is the caller's truncation of the reason list, and only of that list
        problems = {"confirmation": "unconfirmed", "reproduction_problems": ["an unknown kind", "no such file"]}
        check_eq("R1 the caller's `cut` is applied to the reasons and to nothing else in the sentence",
                 BR.reproduction_words(problems, cut=lambda text: "CUT(" + text + ")"),
                 "unconfirmed — a reproduction is recorded but could not be checked: CUT(an unknown kind; no such file); "
                 "it counts toward nothing")
        check_eq("R1 ... no `cut`: the reasons whole", BR.reproduction_words(problems),
                 "unconfirmed — a reproduction is recorded but could not be checked: an unknown kind; no such file; "
                 "it counts toward nothing")
        check_eq("R1 ... a `cut` is not asked about a record with no reasons", BR.reproduction_words(
                 {"confirmation": "unconfirmed"}, cut=lambda text: "CUT(" + text + ")"), OLD_TAIL)
        # HF816-words-kindsfilter (t-436, EQUIVALENT mutant): a kind outside the closed list is never said whether or not it is
        # filtered first, because the sentence tests membership of exactly two words. That holds while both are in the closed list:
        check_eq("R1 a kind outside the closed list is not said, a kind inside it is",
                 BR.reproduction_words({"confirmation": "reproduced_by_factory", "reproduced_how": ["bogus", "own_script"]}),
                 "reproduced by the factory — the analyst's own script reproduced it; no person has confirmed it yet")
        check_eq("R1 ... and the two words the sentence tests are members of the closed list (the premise of the above)",
                 [k in C.BUG_REPRODUCTION_KINDS for k in ("fresh_data_rerun", "own_script")], [True, True])
        # F-1: the analyst always writes `unconfirmed`, so the FILED file says it beside a draft with a valid receipt
        def filed_unconfirmed(reproduction):
            task = build(root, reproduction)
            (task / "bugs").mkdir(exist_ok=True)
            (task / "bugs" / "BUG-1.md").write_text(
                "---\nid: BUG-1\ntitle: MS Teams integration cannot be moved\nimpact: degraded\nconfirmation: unconfirmed\n"
                "source_draft: work/bug-drafts/move.json\ngate_b_decision_id: gateB-QA-1\n---\nbody\n", encoding="utf-8")
            return task
        task = filed_unconfirmed([FRESH])
        recs = BR.story_bugs(task)["records"]
        check_eq("R1 a filed `unconfirmed` bug whose draft holds a valid receipt reads reproduced (one record)",
                 [(r["id"], r["confirmation"], r["state"], r["reproduced_how"]) for r in recs],
                 [("BUG-1", "reproduced_by_factory", "reproduced", ["fresh_data_rerun"])])
        check_not_in("R1 ... and never says nobody has reproduced it", "nobody has reproduced", BR.reproduction_words(recs[0]))
        check_eq("R1 ... the same word through the reader a surface calls: confirmation_of on the filed record's fields",
                 BR.confirmation_of(task, {"confirmation": "unconfirmed", "source_draft": "work/bug-drafts/move.json"})[0], "reproduced_by_factory")
        for ident, entries in (("no receipt", "absent"), ("a receipt that does not hold", [dict(FRESH, evidence="evidence/nope.log")])):
            rec = BR.story_bugs(filed_unconfirmed(entries))["records"][0]
            check_eq(f"R1 a filed `unconfirmed` bug, draft with {ident}: unconfirmed, state unconfirmed", (rec["confirmation"], rec["state"]),
                     ("unconfirmed", "unconfirmed"))
        rec = BR.story_bugs(filed_unconfirmed("absent"))["records"][0]
        check_eq("R1 ... no receipt: no reason, the old sentence (no regression)", (rec["reproduction_problems"], BR.reproduction_words(rec)), ([], OLD_TAIL))
        (filed_unconfirmed("absent") / "work" / "bug-drafts" / "move.json").unlink()
        rec = BR.story_bugs(root / "qa-factory" / "artifacts" / "QA-1")["records"][0]
        check_eq("R1 ... and the draft gone: unconfirmed with NO reason (only a claimed step needs one)",
                 (rec["confirmation"], rec["reproduction_problems"]), ("unconfirmed", []))
    finally:
        cleanup(root)


# (id, reproduction, builder options, the reason word that must be named). Every one reads unconfirmed (I1, I3, I5).
HARD = [
    ("typo-kind", [dict(FRESH, kind="fresh_rerun")], {}, "an unknown kind"),
    ("blank-observed", [dict(FRESH, observed="   ")], {}, "no observation written"),
    ("absolute-evidence", [dict(FRESH, evidence="C:/Windows/win.ini")], {}, "outside the evidence folder"),
    ("another-story", [dict(FRESH, evidence="../OTHER/evidence/x.log")], {}, "outside the evidence folder"),
    ("not-under-evidence", [dict(FRESH, evidence="work/triage.json")], {}, "outside the evidence folder"),
    ("missing-file", [dict(FRESH, evidence="evidence/nope.log")], {}, "no such file"),
    ("empty-file", [dict(FRESH, evidence="evidence/empty.log")], {}, "empty file"),
    ("free-text-evidence", [dict(FRESH, evidence="evidence/rerun.log (own S7 reproduction, 400 again)")], {}, "no such file"),
    ("same-attempt", [dict(FRESH, attempt_id="a1")], {}, "the same attempt as the triage"),
    ("no-attempt", [{k: v for k, v in FRESH.items() if k != "attempt_id"}], {}, "no attempt id"),
    ("attempt-not-in-report", [dict(FRESH, attempt_id="a9")], {}, "no run row for that attempt"),
    ("rerun-went-green", [FRESH], {"run": [RUN[0], dict(RUN[1], status="passed")]}, "that attempt did not fail"),
    ("rerun-skipped", [FRESH], {"run": [RUN[0], dict(RUN[1], status="skipped")]}, "that attempt did not fail"),
    ("nul-evidence", [dict(FRESH, evidence="evidence/a\u0000b")], {}, "no such file"),
    ("results-not-a-list", [FRESH], {"run": 5}, "the run report could not be read"),
    ("a-probe-row-is-no-run", [FRESH], {"run": [RUN[0], dict(RUN[1], purpose="red_probe")]}, "no run row for that attempt"),
    ("green-now", [SCRIPT], {"run": [dict(RUN[0], status="passed", attempt_id="a1")]}, "the test is green now"),
    ("current-skipped", [SCRIPT], {"run": [dict(RUN[0], status="skipped", attempt_id="a1")]}, "the test did not fail in its current result"),
    ("current-not-run", [SCRIPT], {"run": [dict(RUN[0], status="not_run", attempt_id="a1")]}, "the test did not fail in its current result"),
    ("current-row-unknown", [SCRIPT], {"run": [dict(RUN[0], instance_id="another_test")]},
     "the current result of this test is not known"),
    ("test-bug-triage", [FRESH], {"verdict": "TEST_BUG"}, "no APP_BUG triage row"),
    ("not-a-list", {"kind": "own_script"}, {}, "not a list of entries"),
    ("not-an-object", ["rerun"], {}, "an entry that is not an object"),
    ("no-run-report", [FRESH], {"run": None}, "the run report could not be read"),
]


def r2_inconvenient_inputs() -> None:
    root = temp_dir("qa-repro-r2-")
    try:
        for ident, entries, options, reason in HARD:
            task = build(root, entries, **options)
            rec = record_of(task)
            check_eq(f"R2 {ident}: reads unconfirmed", rec["confirmation"], "unconfirmed")
            check_in(f"R2 {ident}: the reason is named", reason, rec["reproduction_problems"])
            words = BR.reproduction_words(rec)
            check_in(f"R2 {ident}: the sentence says it could not be checked", "could not be checked", words)
            check_not_in(f"R2 {ident}: the old claim is not made while a record exists", "nobody has reproduced", words)
            check(f"R2 {ident}: no task root in any line of the report", str(task) not in words and root.name not in words, words)
        # an own script stands when the report is missing (the code does not judge a script); a rerun does not
        check_eq("R2 no run report: an own script is still valid",
                 record_of(build(root, [SCRIPT], run=None))["confirmation"], "reproduced_by_factory")
        # t-442 (canon part D): a run row that names its instance ONLY by `test_instance_id` is that instance's row (the runner's
        # other spelling of the field); it is the attempt the rerun receipt points at, and the receipt holds
        alias = {"test_instance_id": INSTANCE, "attempt_id": "a2", "purpose": "diagnostic", "status": "failed"}
        rec = record_of(build(root, [FRESH], run=[RUN[0], alias]))
        check_eq("R2 a rerun row that carries `test_instance_id` only: the receipt holds, reproduced",
                 (rec["confirmation"], rec["reproduction_problems"], rec["reproduced_how"]), ("reproduced_by_factory", [], ["fresh_data_rerun"]))
        rec = record_of(build(root, [FRESH], run=[RUN[0], dict(alias, test_instance_id="another_test")]))
        check_eq("R2 ... a `test_instance_id` of ANOTHER instance is no row of this one (control)",
                 (rec["confirmation"], rec["reproduction_problems"]), ("unconfirmed", ["no run row for that attempt"]))
        # the role's word without a receipt, and a typo of the word
        for ident, word in (("bare-word", "reproduced_by_factory"), ("typo-word", "reproduced_by_factry")):
            rec = record_of(build(root, "absent", word=word))
            check_eq(f"R2 {ident}: unconfirmed, nothing recorded", (rec["confirmation"], rec["reproduction_problems"]), ("unconfirmed", []))
            check_eq(f"R2 {ident}: the old sentence", BR.reproduction_words(rec), OLD_TAIL)
        # the verdict reaches the person through `_r_bugs`: a record exists, none holds -> the second tail, closed words
        facts = {"bugs": RF._bugs(root / "qa-factory", build(root, [dict(FRESH, attempt_id="a1")]), {}), "unknown": {}}
        text = RF._r_bugs(facts)
        check_in("R2 the report's tail for an unchecked record", "a reproduction is recorded but could not be checked: "
                 "the same attempt as the triage; it counts toward nothing", text)
        check_not_in("R2 ... and it does not carry the old claim", "nobody has reproduced", text)
    finally:
        cleanup(root)


def r3_no_verdict_changes() -> None:
    def bugs(state):
        return {"records": [{"id": "B-1", "title": "t", "severity": "minor", "state": state, "requirements": ["R-1"],
                             "cases": ["TC-1"], "homes": []}] if state else []}
    seen = {}
    for state in (None, "unconfirmed", "reproduced"):
        v = RF._verdict({"ledger": None, "requirements": None, "bugs": bugs(state), "tests": None})
        seen[state] = (v["word"], v["ready"] if "ready" in v else None, v["first_kind"], v["first_reason"])
    # RN1-16: a draft that names a requirement leads the head, said as "not confirmed yet"; the WORD is unchanged (E-A10)
    check_eq("R3 a reproduced bug changes no word: equal to the story with no bug at all", seen["reproduced"][:2], seen[None][:2])
    check_eq("R3 ... it leads the head as a draft", seen["reproduced"][2], "bug_draft")
    check_in("R3 ... and the head says not confirmed yet", "not confirmed yet", seen["reproduced"][3])
    check_eq("R3 control: with no bug at all there is no draft in the head", seen[None][2] != "bug_draft", True)
    check_eq("R3 ... and equal to the unconfirmed one", seen["reproduced"], seen["unconfirmed"])
    confirmed = RF._verdict({"ledger": None, "requirements": None, "bugs": bugs("confirmed"), "tests": None})
    check_eq("R3 control: a CONFIRMED bug is still the first kind `bug` (the test can fail)", confirmed["first_kind"], "bug")
    # the same story files with the receipt and without it: the verdict's word, kind, reason and FIRST SENTENCE are equal
    root = temp_dir("qa-repro-r3-")
    try:
        seen = {}
        for label, field in (("with", [FRESH]), ("without", "absent")):
            task = build(root, field)
            facts = RF.build(task)
            v = RF._verdict(facts)
            first = re.split(r"(?<=[.!?])\s", RF.render(facts)["verdict"].strip(), maxsplit=1)[0]
            seen[label] = (v["word"], v["first_kind"], v["first_reason"], first)
        check_eq("R3 the same files with `reproduction` and without: equal word, first kind, first reason and first sentence",
                 seen["with"], seen["without"])
        check("R3 ... and the first sentence is a sentence (not empty)", bool(seen["with"][3]), repr(seen["with"]))
    finally:
        cleanup(root)


def r4_the_count_on_every_surface() -> None:
    root = temp_dir("qa-repro-r4-")
    try:
        task = build(root, [FRESH])
        qa = root / "qa-factory"
        rec = T.story_bug_records(qa, task)["records"]
        check_eq("R4 the traceability reader hands the new fields on", (rec[0]["confirmation"], rec[0]["reproduced_how"]),
                 ("reproduced_by_factory", ["fresh_data_rerun"]))
        check_eq("R4 headline", T.bug_headline(rec), "Product bugs \u2014 1 reproduced by the factory.")
        table = {"rows": [{"requirement": "R-5", "what": "move", "case": "TC-002", "then": [1], "tests": [], "level": "api",
                           "shape": "new", "result": "bug", "bug": rec[0]["id"], "basis": "x"}], "bugs": rec}
        rendered = T.render(table)
        check_in("R4 appendix cell", f"**{rec[0]['id']}**<br>reproduced by the factory", rendered)
        check_in("R4 appendix legend", "A bug reproduced by the factory failed again", rendered)
        check_not_in("R4 appendix legend does not claim nobody reproduced it", "nobody has reproduced", rendered)
        facts = RF._bugs(qa, task, {})
        check_eq("R4 the report's counts", (facts["confirmed"], facts["reproduced"], facts["unconfirmed"], facts["unreadable"]), (0, 1, 0, 0))
        out = RF._r_bugs({"bugs": facts, "unknown": {}})
        check_in("R4 the report's heading", "## Product bugs \u2014 0 confirmed \u00b7 1 reproduced by the factory \u00b7 0 unconfirmed", out)
        check_in("R4 the report's tail", "(reproduced by the factory \u2014 failed again on another run, and the analyst says on fresh data;"
                 " no person has confirmed it yet)", out)
        blocks = RF.render(RF.build(task))
        check_in("R4 the verdict sentence", "Product bugs: 0 confirmed, 1 reproduced by the factory (minor), 0 unconfirmed.", blocks["verdict"])
        check_not_in("R4 the verdict does not say none recorded", "none recorded", blocks["verdict"])
        check_not_in("R4 ... and the heading does not say unreadable", "unreadable", blocks["bugs"])
        rows = GB.bug_rows(task, {})
        check_eq("R4 the gate packet reads the same word", (rows[0]["confirmation"], rows[0]["reproduced_how"]),
                 ("reproduced_by_factory", ["fresh_data_rerun"]))
        check_eq("R4 ... and the same headline", T.bug_headline(rows), "Product bugs \u2014 1 reproduced by the factory.")
        # the packet itself, through `render_gate_b`: the words reach the person who answers
        packet = GB.render_gate_b("QA-1", root=task)
        check_in("R4 the gate B packet says the draft was reproduced by the factory",
                 "reproduced by the factory — failed again on another run", packet)
        check_not_in("R4 ... and does not say nobody has reproduced it", "nobody has reproduced", packet)
        plain = build(temp_dir("qa-repro-r4c-"), "absent")
        check_in("R4 a draft with no receipt keeps the old words in the packet", OLD_TAIL, GB.render_gate_b("QA-1", root=plain))
        cleanup(plain.parents[2])
        # the delivery summary, through `DS.build` with a filed `.md` that says `unconfirmed` (F-1) and one that says nothing of a step
        (task / "bugs").mkdir(exist_ok=True)
        (task / "bugs" / "BUG-1.md").write_text(
            "---\nid: BUG-1\ntitle: t\nconfirmation: unconfirmed\nsource_draft: work/bug-drafts/move.json\n---\nbody\n", encoding="utf-8")
        (task / "work" / "proposals").mkdir(exist_ok=True)
        (task / "work" / "proposals" / "p1.json").write_text(json.dumps(
            {"kind": "bug", "bug_file": "bugs/BUG-1.md", "source_draft": "work/bug-drafts/move.json",
             "gate_b_decision_id": "gateB-QA-1"}), encoding="utf-8")
        built = DS.build(task, ledger={"rows": []})
        filed_row = [b for b in built["bugs"] if b["ref"] == "bugs/BUG-1.md"]
        check_eq("R4 DS.build reads a filed `.md` through the one reader: reproduced, kinds named",
                 [(b["confirmation"], b["reproduced_how"]) for b in filed_row], [("reproduced_by_factory", ["fresh_data_rerun"])])
        summary = {"counts": {}, "gaps": [], "bugs": [{"ref": "work/bug-drafts/move.json", "state": "draft", "confirmation": "reproduced_by_factory",
                                                       "reproduced_how": ["fresh_data_rerun"], "reproduction_problems": []}]}
        fragment = DS.render(summary)
        check_in("R4 the delivery fragment counts it apart", "Product bugs \u2014 1 reproduced by the factory.", fragment)
        check_in("R4 ... and says no person has confirmed it", "no person has confirmed it yet", fragment)
        board = FD.story_bug_rows([], [json.loads((task / "work" / "bug-drafts" / "move.json").read_text(encoding="utf-8"))],
                                  {"TC-002"}, "QA-1", task)
        check_eq("R4 the board reads it through the one reader", board[0]["confirmation"], "reproduced_by_factory")
        check_eq("R4 the board's head line", FD.bug_confirmation_split(board), "1 reproduced by the factory")
        check_in("R4 the board's cell is amber, not the green of a confirmed bug", "<td class='skip'>reproduced by the factory</td>",
                 FD.story_bugs_table(board))
        bare = FD.story_bug_rows([], [{"title": "x", "case": "TC-002", "confirmation": "reproduced_by_factory"}], {"TC-002"}, "QA-1")
        check_eq("R4 the board with no story root: a bare word is unconfirmed (the error goes down)", bare[0]["confirmation"], "unconfirmed")
        # N = 0: no segment, no new sentence, anywhere
        task0 = build(temp_dir("qa-repro-r4b-"), "absent")
        rec0 = T.story_bug_records(task0.parents[1], task0)["records"]
        text0 = " ".join([T.bug_headline(rec0), T.render({"rows": [], "bugs": rec0}), RF._r_bugs({"bugs": RF._bugs(task0.parents[1], task0, {}), "unknown": {}}),
                          DS.render({"counts": {}, "gaps": [], "bugs": [{"ref": "d.json", "state": "draft", "confirmation": "unconfirmed"}]}),
                          FD.bug_confirmation_split(FD.story_bug_rows([], [{"case": "TC-002", "title": "x"}], {"TC-002"}, "QA-1"))])
        check_not_in("R4 with no reproduced bug the words appear nowhere", "reproduced by the factory", text0)
        cleanup(task0.parents[2])
        # an unreadable bug file is its own group: neither confirmed nor unconfirmed
        unreadable = [{"id": "BUG-9", "confirmation": BR.UNKNOWN}]
        check_eq("R4 `unknown` is counted as unreadable, not as confirmed", T.bug_headline(unreadable), "Product bugs \u2014 1 unreadable.")
        check_not_in("R4 ... and its table cell carries no `unconfirmed`", "unconfirmed",
                     T._result_cell({"result": "bug", "bug": "BUG-9"}, {"BUG-9": T.bug_word(unreadable[0])}))
    finally:
        cleanup(root)


LINE = "setQuantity(Math.max(1, parseInt(e.target.value) || 1))"
WAYS = [{"action": "type -1 one key at a time", "start_state": "field selected", "seen": "11", "requirement": "R-6", "case": "TC-002",
         "evidence": "evidence/rerun.log", "red_test_none": "manual check only"},
        {"action": "type 1.5", "start_state": "field erased first", "seen": "1", "requirement": "R-7", "case": "TC-003",
         "evidence": "evidence/rerun.log", "red_test_none": "manual check only"}]
CODE_BASIS = {"id": "b1", "kind": "code_line", "path": "src/Book.tsx", "line": 2, "quote": LINE}


def merged(root: Path, mechanism: dict, *, ways=WAYS, reproduction=None) -> Path:
    """The `build` story whose draft carries `cases`, `manifestations` and a `mechanism`; the code file the basis names is in the project."""
    (root / "src").mkdir(exist_ok=True)
    (root / "src" / "Book.tsx").write_text("const a = 1;\n  " + LINE + "\n", encoding="utf-8")
    return build(root, [FRESH] if reproduction is None else reproduction,
                 extra={"cases": ["TC-002", "TC-004"], "manifestations": ways, "mechanism": mechanism})


def r11_a_merged_draft_is_one_bug() -> None:
    """t-2187 N3a (rows 5.5, 5.6, 5.9): a draft with `case`, `cases` and manifestations reads as ONE bug carrying every case and
    requirement; the factory's own reproduction step stays the primary's (5.4); the report prints every way it shows, how the cause was
    confirmed, and what nobody verified as "not verified" (FR-41), with no file name and no field name; a bug with one way adds no line."""
    root = temp_dir("qa-repro-r11-")
    try:
        sure = {"statement": "the field turns an invalid value into 1.", "status": "confirmed", "basis": [CODE_BASIS],
                "claims": [{"says": "an invalid value becomes 1", "confirmed_by": ["b1"]},
                           {"says": "pasting -1 behaves like typing it", "confirmed_by": []}], "why": ""}
        task = merged(root, sure)
        qa = root / "qa-factory"
        rec = T.story_bug_records(qa, task)["records"][0]
        check_eq("R11 every case of the draft, in the reader's order (`case`, `cases`, then the manifestations')", rec["cases"],
                 ["TC-002", "TC-004", "TC-003"])
        check_eq("R11 the requirements are the union", sorted(set(rec["requirements"])), ["R-5", "R-6", "R-7"])
        check_eq("R11 the record carries one line per way it shows", rec["manifestations"],
                 ["type -1 one key at a time; start: field selected; seen: 11", "type 1.5; start: field erased first; seen: 1"])
        check_eq("R11 ... and the cause with its facts (`cause_view`: the effective status, how it stands)",
                 (rec["mechanism"]["status"], rec["mechanism"]["by_code"], rec["mechanism"]["runs"], rec["mechanism"]["by_person"],
                  rec["mechanism"]["unverified"]),
                 ("confirmed", True, 0, False, ["pasting -1 behaves like typing it"]))
        single = T.story_bug_records(qa, build(root, [FRESH]))["records"][0]
        check_eq("R11 control: the same story without the keys - one case, no ways, no cause, no link",
                 (single["cases"], single["manifestations"], single["mechanism"], single["possibly_same_cause"]), (["TC-002"], [], {}, []))
        check_eq("R11 the factory's reproduction step is the primary's, whatever the merge adds (5.4)", rec["confirmation"], single["confirmation"])
        task = merged(root, sure)
        out = RF._r_bugs({"bugs": RF._bugs(qa, task, {}), "unknown": {}})
        for needle in ("   One cause (by the line of the application code that does it): the field turns an invalid value into 1.",
                       "   Shows as:", "   - type -1 one key at a time; start: field selected; seen: 11",
                       "   - type 1.5; start: field erased first; seen: 1", "   Not verified: pasting -1 behaves like typing it."):
            check_in(f"R11 the report says: {needle.strip()[:50]}", needle + "\n", out)
        check_not_in("R11 ... and names no field", "manifestation", out.lower())
        check_not_in("R11 ... nor `mechanism`, `triage_ref`, `confirmed_by` or a json key", "mechanism", out.lower())
        check_eq("R11 the counts count bugs, not ways", RF._bugs(qa, task, {})["unconfirmed"] + RF._bugs(qa, task, {})["reproduced"], 1)
        # the basis cannot be re-read: the cause is no longer said to be confirmed (error goes DOWN)
        broken = dict(sure, basis=[dict(CODE_BASIS, quote="something the file does not say")])
        out = RF._r_bugs({"bugs": RF._bugs(qa, merged(root, broken), {}), "unknown": {}})
        check_in("R11 a basis that does not stand: said as not established, the packet's words (M3)", "   Cause not established: the evidence behind it could not be re-read.", out)
        check_not_in("R11 ... never `confirmed`", "confirmed by", out)
        # unverified and unknown
        out = RF._r_bugs({"bugs": RF._bugs(qa, merged(root, {"statement": "maybe the field", "status": "unverified", "why": "only one start state was run",
                                                           "basis": [], "claims": []}), {}), "unknown": {}})
        check_in("R11 an unverified cause is a possibility, with what is missing", "Possibly one cause (not verified: only one start state was run): maybe the field.", out)
        out = RF._r_bugs({"bugs": RF._bugs(qa, merged(root, {"status": "unknown", "why": "no access to the application code"}), {}), "unknown": {}})
        check_in("R11 an unknown cause is never printed as one", "Cause not established: no access to the application code.", out)
        # ONE way: nothing new is printed, whatever the mechanism says
        one = merged(root, sure, ways=WAYS[:1])
        text_one = RF._r_bugs({"bugs": RF._bugs(qa, one, {}), "unknown": {}})
        plain = RF._r_bugs({"bugs": RF._bugs(qa, build(root, [FRESH]), {}), "unknown": {}})
        check_not_in("R11 one way: no cause line, no list of ways", "One cause", text_one)
        check_not_in("R11 ... and none of the new words", "Shows as", text_one)
        check_eq("R11 ... the row line is the plain bug's, but for the case and requirement cells",
                 text_one.splitlines()[2].split(" — ", 1)[1], plain.splitlines()[2].split(" — ", 1)[1])
    finally:
        cleanup(root)


def r5_severity() -> None:
    root = temp_dir("qa-repro-r5-")
    try:
        task = build(root, "absent")
        qa = root / "qa-factory"
        check_eq("R5 a draft with `impact: degraded` has the severity the scale derives: minor", RF._bugs(qa, task, {})["records"][0]["severity"], "minor")
        for impact in ("", "no-such-impact"):
            task = build(root, "absent", extra={"impact": impact})
            check_eq(f"R5 impact {impact!r}: severity not recorded", RF._bugs(qa, task, {})["records"][0]["severity"], "")
        task = build(root, "absent", word="confirmed_by_person")
        (task / "bugs").mkdir(exist_ok=True)
        (task / "bugs" / "BUG-1.md").write_text(
            "---\nid: BUG-1\ntitle: t\nseverity: critical\nimpact: degraded\nconfirmation: confirmed_by_person\n"
            "source_draft: work/bug-drafts/move.json\n---\nbody\n", encoding="utf-8")
        got = RF._bugs(qa, task, {})["records"][0]
        check_eq("R5 the filed file still wins over the derivation", (got["id"], got["severity"]), ("BUG-1", "critical"))
    finally:
        cleanup(root)


def r6_behind_another_red() -> None:
    root = temp_dir("qa-repro-r6-")
    task = root / "QA-1"
    # the REAL story of run 12586, no stub: TC-003's red is behind TC-002's, and TC-003 has no bug of its own
    shutil.copytree(FIXTURES / "run-12586-red-then" / "work", task / "work")
    (task / "work" / "bug-drafts" / "ms-teams-occupied-project-mismatch.json").unlink()

    def edit(change):
        path = task / "work" / "triage.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        change([r for r in data["triage"] if r.get("case") == "TC-003"][0])
        path.write_text(json.dumps(data), encoding="utf-8")
    key = "test_put_project_change_into_project_with_ms_teams_is_rejected"
    try:
        edit(lambda r: r.update(blocking_check="TC-002",
                                blocked_thens=[{"then": 3, "blocking_check": "TC-002", "detail": "the 400 comes first"}]))
        story = T.Story(root, task)
        row = [r for r in story.triage_rows if r.get("case") == "TC-003"][0]
        said = story._behind_another_red(row, "APP_BUG", "R-10")
        check_in("R6 a red behind another case's red: says it is that case's defect, no separate bug",
                 "red run, triaged APP_BUG: this is the defect of TC-002", said)
        check_in("R6 ... with the blocker's own bug and the analyst's detail", "a product bug: MS Teams integration cannot be moved", said)
        check_in("R6 ... and the detail", "no separate bug \u2014 the 400 comes first", said)
        check_not_in("R6 ... and never `bug not filed` or `no reason recorded`", "no reason recorded", said)
        check_not_in("R6 ... and no instance id", "ti_", said)
        check_eq("R6 a row with no `blocking_check` is the old line (no branch)", story._behind_another_red(dict(row, blocking_check=None), "APP_BUG", "R-10"), "")
        check_eq("R6 an empty or non-string blocker takes no branch", [story._behind_another_red(dict(row, blocking_check=b), "APP_BUG", "R-10")
                                                                        for b in ("", "  ", 5, ["TC-9"])], [""] * 4)
        check_eq("R6 a TEST_BUG row with a `blocking_check` takes no branch (it is not the defect of another case)",
                 story._behind_another_red(row, "TEST_BUG", "R-10"), "")
        check_eq("R6 a blocker the contract calls stale (a case not red in this run) takes no branch (the real contract)",
                 story._behind_another_red(dict(row, blocking_check="TC-009"), "APP_BUG", "R-10"), "")
        check_eq("R6 a blocker that is the row's own case takes no branch",
                 story._behind_another_red(dict(row, blocking_check="TC-003"), "APP_BUG", "R-10"), "")
        # the limit of the cut (R10): exactly at it, and one over
        for length, cut in ((RF.FIRST_REASON_LIMIT, False), (RF.FIRST_REASON_LIMIT + 1, True)):
            detail = " ".join(["word"] * 60)[:length].rstrip()
            detail = detail + "d" * (length - len(detail))
            full = story._behind_another_red(dict(row, blocked_thens=[{"then": 3, "blocking_check": "TC-002", "detail": detail}]), "APP_BUG", "R-10")
            tail = full.rsplit(" \u2014 ", 1)[1]
            check_eq(f"R10 a detail of {length} characters is {'cut' if cut else 'whole'}", tail.endswith(RF.ELLIPSIS), cut)
            check(f"R10 ... and never longer than the limit ({length})", len(tail) <= RF.FIRST_REASON_LIMIT, str(len(tail)))
        # the position: through `instance_outcome` itself. After `bug_for` (a found bug keeps `bug`), the result stays `blocked`
        got = story.instance_outcome(key, "TC-003", "R-10")
        check_eq("R6 through instance_outcome: the result stays `blocked` (`bug` is only for a recorded bug)", got["result"], "blocked")
        check_in("R6 ... with the new basis", "this is the defect of TC-002", got["basis"])
        story.bug_for = lambda case, requirement: {"id": "BUG-1", "title": "t"}
        check_eq("R6 a row with a recorded bug is still `bug`: the branch stands BELOW `bug_for`",
                 (story.instance_outcome(key, "TC-003", "R-10")["result"], story.instance_outcome(key, "TC-003", "R-10")["bug"]), ("bug", "BUG-1"))
        edit(lambda r: r.update(blocking_check="TC-009"))
        old = T.Story(root, task).instance_outcome(key, "TC-003", "R-10")
        check_eq("R6 the real contract finds this blocker unknown to the run: the old line stands (no branch, error direction down)",
                 "this is the defect of" in old["basis"], False)
    finally:
        cleanup(root)


def r7_unknown_word_and_registry() -> None:
    check_eq("R7 absent field: legacy, as a person's", C.bug_confirmation({}), "confirmed_by_person")
    check_eq("R7 a typo of a list word reads one step down", C.bug_confirmation({"confirmation": "confirmed_by_persn"}), "unconfirmed")
    check_eq("R7 `unknown` is not a confirmation word", C.bug_confirmation({"confirmation": BR.UNKNOWN}), "unconfirmed")
    check_eq("R7 the new word is on the list", "reproduced_by_factory" in C.BUG_CONFIRMATIONS, True)
    check_eq("R7 a person's word and the rerun word are not lowered by a receipt check",
             [BR.confirmation_of(Path("."), {"confirmation": w, "reproduction": [SCRIPT]})[0] for w in ("confirmed_by_person", "confirmed_by_rerun")],
             ["confirmed_by_person", "confirmed_by_rerun"])
    root = temp_dir("qa-repro-r7-")
    try:
        task = build(root, "absent")
        (task / "work" / "exploratory-findings.jsonl").write_text(
            json.dumps({"id": "F-1", "status": "reproduced", "case": "TC-002"}) + "\n", encoding="utf-8")
        check_eq("R7 a finding of the registry with status `reproduced` is not a step of the bug", record_of(task)["confirmation"], "unconfirmed")
        source = Path(BR.__file__).read_text(encoding="utf-8")
        check("R7 ... because bug_records does not read the registry", "exploratory" not in source.lower().replace("exploratory_", "x"), "")
    finally:
        cleanup(root)


def r8_the_vocabulary_file() -> None:
    text = (Path(__file__).resolve().parents[2] / "handoffs" / "vocabulary.yaml").read_text(encoding="utf-8")
    for key, expected in (("bug_confirmations", C.BUG_CONFIRMATIONS), ("bug_reproduction_kinds", C.BUG_REPRODUCTION_KINDS)):
        match = re.search(rf"^{key}: \[([^\]]*)\]", text, re.MULTILINE)
        check_eq(f"R8 vocabulary.yaml {key} equals the contract's tuple",
                 tuple(w.strip() for w in match.group(1).split(",")) if match else None, tuple(expected))


def r9_the_finding() -> None:
    root = temp_dir("qa-repro-r9-")
    try:
        def findings(entries):
            rehearsal = GP.Rehearsal(build(root, entries), "B")
            rehearsal.check_bug_drafts()
            return [f for f in rehearsal.findings if "reproduction" in str(f)]
        check_eq("R9 no field: no finding", findings("absent"), [])
        check_eq("R9 a valid entry: no finding", findings([FRESH]), [])
        bad = findings([dict(FRESH, evidence="evidence/nope.log")])
        check_eq("R9 an entry the code cannot read: one finding", len(bad), 1)
        check_in("R9 ... named in the factory's own words, with the door", "reproduction not checkable", str(bad))
        check_in("R9 ... the door is the role's: S7 fixes the entry or removes it", "S7 fixes the entry or removes it", str(bad))
    finally:
        cleanup(root)


def r12_a_draft_with_no_word_is_unconfirmed() -> None:
    """TR1-11: a DRAFT with no `confirmation` word (absent or empty) is `unconfirmed` for every reader of a draft's step - the gate B
    packet, the bug records, the bug texts, the delivery rows and the board (FR-59, AR-28); a FILED bug with no word stays
    `confirmed_by_person` (a bug filed before 0.7.16); a draft WITH a word is read as before."""
    root = temp_dir("qa-repro-r12-")
    try:
        task = build(root, "absent")
        path = task / "work" / "bug-drafts" / "move.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data.pop("confirmation")
        path.write_text(json.dumps(data), encoding="utf-8")
        ref = "work/bug-drafts/move.json"
        # the reader itself: the keyword is the caller's word, never a guess from content; the default keeps the legacy reading
        check_eq("R12 default: a record with no word is confirmed_by_person", BR.confirmation_of(task, data)[0], "confirmed_by_person")
        check_eq("R12 draft=True: no word is unconfirmed", BR.confirmation_of(task, data, draft=True), ("unconfirmed", [], []))
        check_eq("R12 draft=True: an empty word is unconfirmed too", BR.confirmation_of(task, dict(data, confirmation=""), draft=True)[0], "unconfirmed")
        check_eq("R12 draft=True: a word that is there is as before", BR.confirmation_of(task, dict(data, confirmation="confirmed_by_person"), draft=True)[0],
                 "confirmed_by_person")
        # gate B: the row, and the line the person reads
        check_eq("R12 gate B row", GB.bug_rows(task, {})[0]["confirmation"], "unconfirmed")
        check_in("R12 gate B keeps its `nobody has reproduced it` line", OLD_TAIL, GB.render_gate_b("QA-1", root=task))
        # the bug records (traceability, report, dashboard read them) and the bug text
        records = BR.story_bugs(task)["records"]
        check_eq("R12 story_bugs draft record", [r["confirmation"] for r in records if not r["filed"]], ["unconfirmed"])
        written = BR.write_draft_texts(task)
        check_in("R12 write_draft_texts says nobody has reproduced it", "nobody has reproduced it", (task / written[0]["text"]).read_text(encoding="utf-8"))
        # the delivery draft rows
        built = DS.build(task, ledger={"rows": []})
        check_eq("R12 delivery draft row", [b["confirmation"] for b in built["bugs"] if b["ref"] == ref], ["unconfirmed"])
        # the board: a draft with and without the story root; a filed bug with no word keeps the legacy word
        check_eq("R12 board draft with root", FD.story_bug_rows([], [data], {"TC-002"}, "QA-1", task)[0]["confirmation"], "unconfirmed")
        check_eq("R12 board draft with no root", FD.story_bug_rows([], [data], {"TC-002"}, "QA-1")[0]["confirmation"], "unconfirmed")
        check_eq("R12 board draft with a word", FD.story_bug_rows([], [dict(data, confirmation="confirmed_by_person")], {"TC-002"}, "QA-1", task)[0]["confirmation"],
                 "confirmed_by_person")
        filed = {"id": "BUG-1", "title": "t", "found_by": "TC-002"}
        check_eq("R12 board filed bug with no word stays confirmed", FD.story_bug_rows([filed], [], {"TC-002"}, "QA-1", task)[0]["confirmation"], "confirmed_by_person")
        check_eq("R12 delivery filed bug with no word stays confirmed", DS._bug_confirmation(task, {"bug_file": "bugs/BUG-1.md"}, "bugs/BUG-1.md")[0],
                 "confirmed_by_person")
        # a draft WITH a word is unchanged at the packet
        data["confirmation"] = "confirmed_by_person"
        path.write_text(json.dumps(data), encoding="utf-8")
        check_eq("R12 gate B row of a draft with a word", GB.bug_rows(task, {})[0]["confirmation"], "confirmed_by_person")
    finally:
        cleanup(root)


if __name__ == "__main__":
    r1_the_step()
    r2_inconvenient_inputs()
    r3_no_verdict_changes()
    r4_the_count_on_every_surface()
    r5_severity()
    r6_behind_another_red()
    r7_unknown_word_and_registry()
    r8_the_vocabulary_file()
    r9_the_finding()
    r11_a_merged_draft_is_one_bug()
    r12_a_draft_with_no_word_is_unconfirmed()
    finish("bug reproduced by the factory (HF8-16)")
