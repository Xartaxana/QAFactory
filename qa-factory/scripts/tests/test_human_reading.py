#!/usr/bin/env python3
"""A person is shown words and screenshots, never the factory's own records (HF8-20, run 12586, owner 29.10.2026).

On 12586 the gate B packet named `work/delivery-summary.json` and a JSON bug draft, the report named ~44 `evidence/<hash>` files,
raw attempt ids and the journal, and the MR description printed `not_verified:stale_ledger_inputs`. The factory writes ONE readable
text per bug draft (`bug_records.write_draft_texts`, called by `delivery_summary.write` only), the gate and the report read it.

Keys: H1 the gate B packet on the fixture names no JSON/YAML/JSONL, no ledger, no manifest; H2 the bug text is a `.md` outside the
draft folder (not a legacy draft, not a draft); H3 the report: no suffix, no attempt id, no hash, no ledger; pictures stay;
H4 the delivery summary says no state code and an unknown code is words; H5 the data row of `human_text`, with a negative and a
positive control; H6 the edges: no text file, an unreadable draft, no summary yet.
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
import delivery_verdict as DV  # noqa: E402
import delivery_summary as DS  # noqa: E402
import gate_brief as GB  # noqa: E402
import human_text as HT  # noqa: E402
import report_facts as RF  # noqa: E402
import traceability as T  # noqa: E402

TECHNICAL = re.compile(r"\.(?:json|ya?ml|jsonl|txt)\b|ledger|manifest|\bti_|/a\d+/|\bevidence/[0-9a-f]{8}", re.IGNORECASE)
HASH = "ab" * 32


def story(root: Path) -> Path:
    """The real story of run 12586 (the red-then fixture): two bug drafts, manual steps, a triage."""
    task = root / "QA-1"
    shutil.copytree(FIXTURES / "run-12586-red-then" / "work", task / "work")
    return task


def h1_gate_b() -> None:
    root = temp_dir("qa-human-h1-")
    try:
        task = story(root)
        BR.write_draft_texts(task)
        (task / "work" / "delivery-summary.md").write_text("summary\n", encoding="utf-8")
        text = GB.render_gate_b("QA-1", task)
        check_not_in("H1 the packet names no JSON, YAML or JSONL file", ".json", text)
        found = [m.group(0) for m in TECHNICAL.finditer(text.split("## How to answer")[0])]
        check_eq("H1 ... no ledger, no manifest, no attempt id, nothing technical (outside a how-to-answer block)", found, [])
        check_in("H1 the delivery summary is named by its readable file", "work/delivery-summary.md", text)
        check_in("H1 each bug is named by its readable text", "work/bug-text/ms-teams-move-project-mismatch.md", text)
        check_not_in("H1 ... and the folder of the JSON drafts is not named", "bug-drafts", text)
    finally:
        cleanup(root)


def h2_bug_text() -> None:
    root = temp_dir("qa-human-h2-")
    try:
        task = story(root)
        written = BR.write_draft_texts(task)
        check_eq("H2 one entry per draft, none refused", [(e["text"].startswith("work/bug-text/"), e["problem"]) for e in written],
                 [(True, ""), (True, "")])
        path = task / "work" / "bug-text" / "ms-teams-move-project-mismatch.md"
        body = path.read_text(encoding="utf-8")
        check_in("H2 the title", "# MS Teams integration cannot be moved", body)
        check_in("H2 the impact with its priority, derived", "Impact: degraded - priority P2", body)
        check_in("H2 the manual steps, numbered", "1. Create projects A and B", body)
        check_in("H2 what was expected and what was seen", "## Expected", body)
        check_in("H2 ... the seen value is the draft's", "Project mismatch", body)
        check_in("H2 how sure the factory is: the one sentence of the step reader", "unconfirmed", body)
        check_not_in("H2 no JSON field name reaches the text", "triage_ref", body)
        check_not_in("H2 ... no `{` of a JSON object of the draft itself", '"title"', body)
        check_eq("H2 the text is no draft (`draft_paths` holds only the JSON ones)", len(BR.draft_paths(task)), 2)
        check_eq("H2 ... and no legacy `.md` draft either (the draft folder holds none)", BR.legacy_md_drafts(task), [])
        again = BR.write_draft_texts(task)
        check_eq("H2 written twice: the same text, one file per draft", (path.read_text(encoding="utf-8") == body, len(list(path.parent.iterdir()))),
                 (True, 2))
        check_eq("H2 ... and the entries are the same", again, written)
    finally:
        cleanup(root)


class _Stub:
    """A story that knows one valid manual record: what `Story.manual_outcome` reads (duck-typed, no files)."""

    def __init__(self, entry):
        self.entry = entry

    def manual_case(self, key):
        return self.entry


def h3_report() -> None:
    png = f"evidence/{HASH}.png"
    case = {"case": "TC-001", "requirements": ["R-1"], "then": "The page reads cancelled.", "state": "checked", "result": "passed",
            "before": "active", "actual": "The page read cancelled after the click", "why": "",
            "shots": {"taken": 1, "provided": 1, "post_image": False, "post_other": True, "files": [png]},
            "quotes": "", "rejudged": ""}
    line = RF._manual_line(case)
    check_eq("H3 no capture of any kind is named: no text, no JSON, no picture path (t-420)",
             [m.group(0) for m in TECHNICAL.finditer(line)], [])
    check_not_in("H3 ... the picture is only said to be provided", png, line)
    check_in("H3 ... provided", RF.SHOTS_PROVIDED, line)
    check_in("H3 a post capture that is only text: the words of the check", "now: the captured page says: The page read cancelled", line)
    shown = dict(case, shots=dict(case["shots"], provided=0))
    check_in("H3 a picture with no copy on this machine: not provided, said so", RF.SHOTS_NO_COPY, RF._manual_line(shown))
    bare = dict(case, shots={"taken": 0, "provided": 0, "post_image": False, "post_other": False, "files": []})
    check_in("H3 no capture at all: said, as before", "no capture was taken after the action", RF._manual_line(bare))
    quoted = dict(case, quotes=RF._then_quote_words({"then_quotes": [{"then": 1, "quote": "Status: cancelled", "kind": "text"},
                                                                     {"then": 2, "quote": "red banner", "kind": "seen"},
                                                                     {"then": 3, "reached": False}]}),
                  rejudged=RF._rejudge_words({"rejudge_of": "a9", "rejudge_reason": "the first read missed the banner"}))
    said = RF._manual_line(quoted)
    check_in("H3 the runner's quote is printed as what the captured page says", "the captured page says: Status: cancelled", said)
    check_in("H3 ... and what it read on a picture", "the screenshot shows: red banner", said)
    check_in("H3 a re-judged verdict says it was not run again", "re-judged from the captures taken earlier, the check was not run again: "
             "the first read missed the banner", said)
    check_not_in("H3 ... with no attempt number", "a9", said)
    check_eq("H3 a record that was not re-judged says nothing of it", RF._rejudge_words({}), "")
    check_eq("H3 an entry with no quote prints nothing", RF._then_quote_words({"then_quotes": [{"then": 3, "reached": False}]}), "")
    entry = {"state": "checked", "result": RF.RESULT_WORDS["pass"], "actual": "cancelled after the click",
             "shots": {"taken": 0, "provided": 0, "post_image": False, "post_other": True, "files": []}}
    basis = T.Story.manual_outcome(_Stub(entry), "TC-001")["basis"]
    check_eq("H3 the Basis of a pass with only a text capture is the runner's words, not a path", basis, "checked by hand: cancelled after the click")
    entry["shots"] = {"taken": 1, "provided": 1, "post_image": True, "post_other": False, "files": [png]}
    check_eq("H3 ... with a picture it is the same words, never the picture's path (t-420)",
             T.Story.manual_outcome(_Stub(entry), "TC-001")["basis"], "checked by hand: cancelled after the click")
    signals = RF._r_hook_signals({"count": 3, "kinds": {"stage_guard": 2, "x": 1}, "path": "/home/x/journal.jsonl"}, "")
    check_eq("H3 the factory's signals: a number and where it is kept, no kinds, no path, no event name",
             signals, "- the factory's own signals during this run: 3 signals, kept in the factory's own log")
    unknown = {}
    RF._load_ledger(Path("no-such-story-folder"), unknown)
    check_eq("H3 a ledger nobody can find is said in words (unknown branch)", [m.group(0) for m in TECHNICAL.finditer(unknown["ledger"])], [])
    # the verdict block on its three unknown branches (a word that disagrees with its flag, no word at all, an unreadable wording)
    base = {"requirements": None, "bugs": None, "cases": None, "tests": None, "ledger": None, "unknown": {},
            "delivery": None, "gate_b": {"decided": False}}
    for label, verdict in (("the word disagrees with its flag", {"ready": None, "word": DV.UNKNOWN, "first_reason": "", "disagreement": ""}),
                           ("no word at all", {"ready": None, "word": None, "first_reason": "", "disagreement": ""})):
        said = RF._r_verdict(dict(base, verdict=verdict), "")
        check_eq(f"H3 the verdict block, unknown branch ({label}): nothing technical, no `ledger`",
                 [m.group(0) for m in TECHNICAL.finditer(said)], [])
        check_in(f"H3 ... and it still says it is unknown ({label})", "delivery_ready: unknown", said)
    # the whole report on the real story of 12586 and on a story with a ledger: every block
    for label, make in (("the 12586 fixture", story), ("a story with a ledger", _ledger_story)):
        root = temp_dir("qa-human-h3-")
        try:
            task = make(root)
            blocks = RF.render(RF.build(task))
            check("H3 the report is rendered, block by block (" + label + ")", bool(blocks), blocks)
            check_eq(f"H3 no block of the report on {label} names a file, a ledger, a manifest, an attempt id or a hash",
                     sorted((name, m.group(0)) for name, body in blocks.items()
                            for m in TECHNICAL.finditer(re.sub(r"evidence/[0-9a-f]{64}\.png", "<picture>", str(body)))), [])
        finally:
            cleanup(root)


def _ledger_story(root: Path) -> Path:
    """The 12586 story with a plan, a ledger of one verified row and one waived row, and a run report: the unknown branches
    are not the only ones that print words."""
    task = story(root)
    plan = ["## Plan", "", "| ts | r |", "|---|---|", "| TS-1 | R-1 |", "| TS-2 | R-1 |"]
    (task / "test-plan.md").write_text("\n".join(plan) + "\n", encoding="utf-8")
    rows = [{"kind": "plan_row", "ref": "TS-1", "state": "passed_green"},
            {"kind": "plan_row", "ref": "TS-2", "state": "waived:not_executed:handed_to_person"}]
    (task / "work" / "ledger.json").write_text(json.dumps({"rows": rows, "reasons": [], "delivery_ready": False}), encoding="utf-8")
    return task


def h4_delivery_summary() -> None:
    summary = {"counts": {"planned": 10, "executed": 4, "planned_manual": 1, "executed_manual": 1, "verified": 0, "failed": 0,
                          "unverified": 10, "env_blocked": 0, "deferred": 0},
               "gaps": [{"ref": "TS-1", "state": "not_verified:stale_ledger_inputs"},
                        {"ref": "TS-2", "state": "not_executed:handed_to_person"},
                        {"ref": "TS-3", "state": "skipped:marked skipped in the run"},
                        {"ref": "TS-4", "state": "env_blocked:user"},
                        {"ref": "TS-5", "state": "not_executed:zz_new_code"}],
               "bugs": [{"ref": "bugs/BUG-1.md", "state": "provenance_invalid", "confirmation": "unconfirmed"},
                        {"ref": "work/bug-drafts/x.json", "state": "zz_new_state", "confirmation": "unconfirmed"}],
               "source_gaps": ["ledger is stale: plan, run report, manifest, or triage changed after generation", "zz new limit"]}
    text = DS.render(summary)
    check_not_in("H4 no state code reaches the description", "not_verified:", text)
    found = [m.group(0) for m in TECHNICAL.finditer(text)]
    check_eq("H4 ... nor a JSON file, a ledger, a manifest", found, [])
    check_in("H4 the stale state is said in words", "TS-1: was verified before, but what it rested on has changed since", text)
    check_in("H4 a state with prose after the colon keeps the prose", "TS-3: skipped — marked skipped in the run", text)
    check_in("H4 an owner code after the colon is dropped", "TS-4: blocked by the environment", text)
    check_in("H4 a code the data does not hold: the words of not knowing, the code not printed",
             "TS-5: the factory cannot say what this row's state means", text)
    check_not_in("H4 ... the code itself is not there", "zz_new_code", text)
    check_not_in("H4 ... nor an unknown bug state", "zz_new_state", text)
    check_in("H4 and one line says the gap is the factory's, nothing is asked of you", "that is its own gap, and nothing is asked of you", text)
    check_in("H4 the counts are the summary's own, unchanged", "| 10 | 4 | 1 | 1 | 0 | 0 | 10 | 0 | 0 |", text)
    check_in("H4 the head of the table is in words from the data", "| Rows in the plan | Checks run |", text)
    clean = DS.render(dict(summary, gaps=[], bugs=[], source_gaps=[]))
    check_not_in("H4 with nothing unknown the finding line is absent", "its own gap", clean)
    check_eq("H4 every column of the table has words in the data", [k for k in
             ("planned", "executed", "planned_manual", "executed_manual", "verified", "failed", "unverified", "env_blocked", "deferred")
             if not (DS._state_table().get("columns") or {}).get(k)], [])
    # the one reader of the words: a ledger state the ledger can write has words or is said as unknown, never printed raw
    # the real rows of a waived plan row are `waived:<its state>` (ledger.py `"waived:" + state`, pinned in test_ledger K-N8.13)
    for state in ("env_blocked:user", "not_verified_flaky", "partial", "impossible", "pending_implementation", "waived",
                  "waived:not_executed:handed_to_person", "waived:not_executed", "waived:env_blocked:user",
                  "waived:skipped:marked skipped in the run", "waived:not_executed:the run recorded nothing for this test",
                  "waived:zz_new_code"):
        words, known = DS.state_words(state)
        check(f"H4 {state}: known words, no snake_case code in them", known and "_" not in words, words)
    check_eq("H4 a waived row says it was waived and then what it was, in words",
             DS.state_words("waived:not_executed:handed_to_person")[0], "waived by a decision — left with you to check")
    check_eq("H4 a waived row whose inner state the data does not hold says only the waiver, the code not printed",
             DS.state_words("waived:zz_new_code")[0], "waived by a decision")
    waived = DS.render(dict(summary, gaps=[{"ref": "TS-6", "state": "waived:not_executed:handed_to_person"},
                                           {"ref": "TS-7", "state": "waived:skipped:marked skipped in the run"},
                                           {"ref": "TS-8", "state": "waived:not_executed:the run recorded nothing for this test"}],
                            bugs=[], source_gaps=[]))
    check_eq("H4 the MR text of waived rows prints no state code", [c for c in ("not_executed", "skipped:", "not_executed:") if c in waived], [])
    check_not_in("H4 ... and no line says the factory does not know the row", "its own gap", waived)
    # the words of the four states that said more than the code knows (critic F-5): none claims a product fact or a stand
    for state, claim in (("not_executed:contradicts_requirement", "the product does not"), ("impossible", "on this stand")):
        check_not_in(f"H4 {state}: does not claim what no run showed", claim, DS.state_words(state)[0])
    check_in("H4 a bug whose link to gate B cannot be established says that, not 'not chosen'",
             "could not be established", text)
    check_in("H4 a draft is 'not chosen so far' (the summary is written before gate B)", "a draft, not chosen so far",
             DS.render(dict(summary, bugs=[{"ref": "work/bug-drafts/d.json", "state": "draft", "confirmation": "unconfirmed"}])))
    # F-6: the same text names no internal word
    comparing = DS.render(dict(summary, comparison_gaps=[{"case_id": "TC-9", "reason": "no before-state yet"}]))
    check_in("H4 a comparison awaiting its before state: the case and the reason, no code word", "- TC-9: no before-state yet", comparing)
    check_eq("H4 ... and no internal heading or term anywhere in the description",
             [w for w in ("awaiting_before", "Projection limits", "evidence-validated") if w in comparing + text], [])
    check_in("H4 the limits have a heading in words", "Limits of this summary:", text)


def h4_plan_rows_equal_report() -> None:
    """F-4: the summary's 'Rows in the plan' and the report's 'plan rows' are one quantity from two readers; they agree on a
    story whose ledger is current, with `subtask_in_progress` left out of the summary's count."""
    root = temp_dir("qa-human-h4b-")
    try:
        task = root / "QA-1"
        (task / "work").mkdir(parents=True)
        plan = ["## Plan", "", "| ts | r |", "|---|---|"] + [f"| TS-{n} | R-1 |" for n in (1, 2, 3)]
        (task / "test-plan.md").write_text("\n".join(plan) + "\n", encoding="utf-8")
        rows = [{"kind": "plan_row", "ref": f"TS-{n}", "state": "passed_green"} for n in (1, 2, 3)]
        rows.append({"kind": "plan_row", "ref": "TS-3", "state": "subtask_in_progress"})
        summary = DS.build(task, {"rows": rows})
        report = RF._size(task, {}, C.parse_plan(task / "test-plan.md"), {}, {}, {"requirements": None})["counts"]["plan_rows"]
        check_eq("H4 the summary's planned rows are the report's plan rows (subtask_in_progress excluded)",
                 (summary["counts"]["planned"], report), (3, 3))
    finally:
        cleanup(root)


def h5_data_row() -> None:
    row = next((r for r in HT.rules().get("forbidden") or [] if r.get("id") == "technical_file_named"), None)
    check("H5 the data row is there", row is not None)
    bad = "The details are in work/delivery-summary.json and in evidence/a1b2.txt."
    good = "The details are in the delivery summary (work/delivery-summary.md) and the screenshot evidence/a1b2.png."
    check_in("H5 a report naming a JSON and a text file breaks it (negative control)", "technical_file_named",
             [p["rule"] for p in HT.problems(bad, kind="report")])
    check_eq("H5 a report naming a markdown file and a picture does not (positive control)",
             [p["rule"] for p in HT.problems(good, kind="report") if p["rule"] == "technical_file_named"], [])
    stand = "The build marker /usr/share/nginx/html/build-sha.txt is missing on the stand."
    check_eq("H5 a path on the stand is not a factory record (t-427, R8): the row lets it pass",
             [p["rule"] for p in HT.problems(stand, kind="report") if p["rule"] == "technical_file_named"], [])
    mixed = stand + " The details are in work/delivery-summary.json."
    check_in("H5 a factory record named next to a stand path still breaks it (the row keeps its keys)", "technical_file_named",
             [p["rule"] for p in HT.problems(mixed, kind="report")])
    check_in("H5 an absolute path that is not under a stand directory still breaks it", "technical_file_named",
             [p["rule"] for p in HT.problems("See /work/task/delivery-summary.json.", kind="report")])
    check_eq("H5 a question may name the project's own config file: the row checks a report only",
             [p["rule"] for p in HT.shape_problems("Set the stand in `config.json`.", kind="question") if p["rule"] == "technical_file_named"], [])


def h6_edges() -> None:
    root = temp_dir("qa-human-h6-")
    try:
        task = story(root)
        packet = GB.render_gate_b("QA-1", task)
        check_in("H6 no readable summary yet: said in words", "the delivery summary is not written yet", packet)
        check_not_in("H6 ... never a JSON path", ".json", packet)
        rows = GB.bug_rows(task, {})
        check_eq("H6 no text written yet: the row has no path field and the packet no path line",
                 ["text" in r for r in rows] + [bool(re.search(r"bug-text", packet))], [False, False, False])
        (task / "work" / "bug-drafts" / "broken.json").write_text("{ torn", encoding="utf-8")
        written = BR.write_draft_texts(task)
        check_eq("H6 an unreadable draft is skipped with a problem and the others are written",
                 sorted((Path(e["draft"]).stem, bool(e["problem"]), bool(e["text"])) for e in written),
                 [("broken", True, False), ("ms-teams-move-project-mismatch", False, True),
                  ("ms-teams-occupied-project-mismatch", False, True)])
        summary = DS.write(task)
        check_in("H6 and the summary carries it as a limit, in words", DS.BUG_TEXT_LIMIT, summary["source_gaps"])
        check_in("H6 ... which the description says without a code", "the readable text of one bug draft could not be written",
                 (task / "work" / "delivery-summary.md").read_text(encoding="utf-8"))
        packet = GB.render_gate_b("QA-1", task)
        check_in("H6 once the summary is written the packet names its readable file", "work/delivery-summary.md", packet)
        check_eq("H6 a story with no draft: no text folder is made", [p.name for p in (root / "empty").glob("*")] if (root / "empty").exists() else [], [])
        check_eq("H6 `write_draft_texts` on a story with no draft is `[]`", BR.write_draft_texts(root / "empty"), [])
        check("H6 ... and made no folder", not (root / "empty").exists())
        notmd = GB._tail_sections({"critic_path": "work/test-cases/critic-findings.json"}, [])
        check_in("H6 a critic file that is no `.md` is not named", "recorded by the factory; ask if you want them", "\n".join(notmd))
        check_not_in("H6 ... as a path", "critic-findings.json", "\n".join(notmd))
        named = GB._tail_sections({"critic_path": "work/test-cases/critic-findings.md"}, [])
        check_in("H6 a markdown critic file is named", "critic findings: work/test-cases/critic-findings.md", "\n".join(named))
    finally:
        cleanup(root)


def h7_merged_bug() -> None:
    """t-2187 N3b: the packet of a bug drafted from several ways it shows names no record and no field, and its priced block passes the rules."""
    from unittest import mock
    root = temp_dir("qa-human-h7-")
    try:
        task = story(root)
        drafts = task / "work" / "bug-drafts"
        first = sorted(drafts.glob("*.json"))[0]
        data = json.loads(first.read_text(encoding="utf-8"))
        way = {"action": "move the project", "start_state": "from a team channel", "seen": "mismatch", "evidence": "work/evidence/manual/a.txt",
               "red_test_none": "manual check only"}
        data.update(manifestations=[way, dict(way, action="move it again", seen="the same")],
                    mechanism={"statement": "the move reads the old project", "status": "confirmed",
                               "basis": [{"id": "b1", "kind": "run", "case": "c", "capture": "x", "quote": "q", "start_state": "s"}],
                               "claims": [{"says": "a second move behaves alike", "confirmed_by": []}], "why": ""},
                    possibly_same_cause=[{"draft": sorted(drafts.glob("*.json"))[1].name, "why": "both mismatch"}])
        first.write_text(json.dumps(data), encoding="utf-8")
        BR.write_draft_texts(task)
        with mock.patch.object(BR, "mechanism_problems", return_value=[]):
            text = GB.render_gate_b("QA-1", task)
            block = "\n".join(GB.merged_bug_block(GB.bug_rows(task, {}))) + "\n---\nAnswer: say which\n"
        check_in("H7 the merged bug shows its ways", "2 ways it shows", text)
        check_in("H7 ... and the door block", "## One bug or several", text)
        found = [m.group(0) for m in TECHNICAL.finditer(text.split("## How to answer")[0])]
        check_eq("H7 no JSON, ledger, manifest, attempt id or capture path in the packet", found, [])
        check_eq("H7 the block passes price_problems for every token it offers",
                 HT.price_problems(block, ["file", "split", "merge", "not a bug"]), [])
        check_eq("H7 ... and the rules of the text", HT.problems(block, offered=["file", "split", "merge", "not a bug"]), [])
    finally:
        cleanup(root)


def h8_sides_question_prices() -> None:
    """t-2181 PC-2: the new answers (`not built yet` of the two no-change questions, `sides.deliverable`) resolve to three price lines
    that a person reads without a JSON key or a state code in them (the same rows `closed_question` renders)."""
    import hooklib
    import no_move as NM
    prices, words = NM.load_question_prices(), (hooklib.load_ref_json(NM.VERDICTS_FILE) or {}).get("words") or {}
    for key, answers in (("sides.deliverable", ["ours", "another team's", "stop"]), ("s0.no_change", ["not built yet"]),
                         ("s1.no_diff", ["not built yet"])):
        options = [{"answer": a, "token": a, "says": "says it", "slots": {"role": "the scout", "what": "the change"}} for a in answers]
        text = NM.render_options(NM.priced_options(key, options, NM.data(), words, prices), HT.price_labels())
        check_eq(f"H8 {key}: every new answer is a priced option", all(f"`{a}`" in text for a in answers), True)
        check_eq(f"H8 {key}: the price lines name nothing technical", [m.group(0) for m in TECHNICAL.finditer(text)], [])
    check_in("H8 `not built yet` tells the person the story waits for the code",
             "nothing is checked against it until the code exists", NM.render_options(NM.priced_options(
                 "s0.no_change", [{"answer": "not built yet", "token": "not built yet", "says": "x"}], NM.data(), words, prices), HT.price_labels()))


def h9_arrival_and_stop_questions() -> None:
    """t-2181 PC-7: `arrival.not_waiting` and `awaiting.stop` are priced closed questions whose price lines carry nothing technical."""
    import hooklib
    import no_move as NM
    prices, words = NM.load_question_prices(), (hooklib.load_ref_json(NM.VERDICTS_FILE) or {}).get("words") or {}
    shown = {}
    for key, answers in (("arrival.not_waiting", ["re-ground", "ignore", "stop"]), ("awaiting.stop", ["stop waiting", "keep waiting"])):
        options = [{"answer": a, "token": a, "says": "says it", "slots": {"stages": "the stages"}} for a in answers]
        shown[key] = NM.render_options(NM.priced_options(key, options, NM.data(), words, prices), HT.price_labels())
        check_eq(f"H9 {key}: every answer is a priced option", all(f"`{a}`" in shown[key] for a in answers), True)
        check_eq(f"H9 {key}: the price lines name nothing technical", [m.group(0) for m in TECHNICAL.finditer(shown[key])], [])
    check_in("H9 `stop waiting` says the unchecked part stays unchecked", "never checked", shown["awaiting.stop"])


def h10_first_look_dead_question() -> None:
    """t-2277 FL-5: `first_look.dead` is a priced closed question (`continue`, `stop`) whose price lines carry nothing technical, and each
    answer says what it does to the plan (`continue`: the factory runs a command, nothing for the person; `stop`: the story waits)."""
    import hooklib
    import no_move as NM
    prices, words = NM.load_question_prices(), (hooklib.load_ref_json(NM.VERDICTS_FILE) or {}).get("words") or {}
    options = [{"answer": a, "token": a, "says": "says it"} for a in ("continue", "stop")]
    shown = NM.render_options(NM.priced_options("first_look.dead", options, NM.data(), words, prices), HT.price_labels())
    check_eq("H10 first_look.dead: both answers are priced options", all(f"`{a}`" in shown for a in ("continue", "stop")), True)
    check_eq("H10 first_look.dead: the price lines name nothing technical", [m.group(0) for m in TECHNICAL.finditer(shown)], [])
    check_eq("H10 first_look.dead: the answers are exactly continue and stop", [row["answer"] for row in prices["first_look.dead"]], ["continue", "stop"])
    check_in("H10 first_look.dead: `stop` says the story waits", "waits", shown)


def h11_first_look_same_code_question() -> None:
    """t-2277 FL-6: `first_look.same_code` is a priced closed question (`wait`, `source`, `continue`) whose price lines carry nothing
    technical; `wait` runs nothing, `source` is the person's work, `continue` is a factory command and not ready for delivery."""
    import hooklib
    import no_move as NM
    prices, words = NM.load_question_prices(), (hooklib.load_ref_json(NM.VERDICTS_FILE) or {}).get("words") or {}
    answers = ["wait", "source", "continue"]
    options = [{"answer": a, "token": a, "says": "says it"} for a in answers]
    shown = NM.render_options(NM.priced_options("first_look.same_code", options, NM.data(), words, prices), HT.price_labels())
    check_eq("H11 first_look.same_code: every answer is a priced option", all(f"`{a}`" in shown for a in answers), True)
    check_eq("H11 first_look.same_code: the price lines name nothing technical", [m.group(0) for m in TECHNICAL.finditer(shown)], [])
    check_eq("H11 first_look.same_code: the answers are exactly wait, source, continue", [row["answer"] for row in prices["first_look.same_code"]], answers)
    check_eq("H11 first_look.same_code: the prices are the spec's (factory / you / the story)",
             [(row["factory"], row["person"], row["delivery"]) for row in prices["first_look.same_code"]],
             [("nothing", "none", "waits"), ("command", "your_work", "waits"), ("command", "none", "no")])
    check_eq("H11 first_look.same_code: the block passes the price rule for every token", HT.price_problems(shown, answers), [])
    check_eq("H11 first_look.same_code: `continue` is the price of `first_look.dead`'s `continue`",
             [r for r in prices["first_look.same_code"] if r["answer"] == "continue"][0]["delivery"],
             [r for r in prices["first_look.dead"] if r["answer"] == "continue"][0]["delivery"])


def h13_absent_side_question() -> None:
    """t-2559 (W2 B3): `awaiting.absent_side` is a priced closed question (`not ours`, `relaunch`); the question the driver raises over
    a real side name passes the report rules, names nothing technical, and says what the factory waits for."""
    import hooklib
    import no_move as NM
    prices, words = NM.load_question_prices(), (hooklib.load_ref_json(NM.VERDICTS_FILE) or {}).get("words") or {}
    answers = ["not ours", "relaunch"]
    options = [{"answer": a, "token": a, "says": "says it"} for a in answers]
    shown = NM.render_options(NM.priced_options("awaiting.absent_side", options, NM.data(), words, prices), HT.price_labels())
    check_eq("H13 awaiting.absent_side: the answers are exactly not ours and relaunch", [r["answer"] for r in prices["awaiting.absent_side"]], answers)
    check_eq("H13 awaiting.absent_side: the price lines name nothing technical", [m.group(0) for m in TECHNICAL.finditer(shown)], [])
    check_eq("H13 awaiting.absent_side: the block passes the price rule for every token", HT.price_problems(shown, answers), [])
    check_in("H13 `not ours` says what stays unchecked", "stand-in", shown)
    import story_run
    driver = story_run.Driver.__new__(story_run.Driver)
    driver.task, driver.state, driver._price_notes = "QA-7", {}, None
    driver.save_state = lambda: None
    person = story_run.Driver._absent_side_person(driver, "api", "S6")
    check_eq("H13 the question: kind, side kept for the executor", (person.kind, driver.state.get("absent_side")), ("absent_side", "api"))
    for needle in ("the part of the product called `api` does not exist yet", "waits for its code", "`not ours`", "`relaunch`"):
        check_in(f"H13 the question says: {needle}", needle, str(person.text))
    # the how-to-answer block is written by `ask()` around the body, so the one rule about it is the only one left for this body
    check_eq("H13 the question body breaks no rule of human-questions.md", [p["rule"] for p in HT.problems(str(person.text), offered=answers)
                                                                           if p["rule"] != "no_how_to_answer"], [])
    # t-2562 B-1: the re-offer after `relaunch` has its own lead (FR-7), and it passes the same rules
    again = story_run.Driver._absent_side_person(driver, "api", "S6", earlier="2026-11-11")
    check_in("H13 the re-offer names the earlier answer and its date", "On 2026-11-11 you said you would start QA-7 again", str(again.text))
    check("H13 the re-offer differs from the first text", str(again.text) != str(person.text))
    check_eq("H13 the re-offer body breaks no rule of human-questions.md", [p["rule"] for p in HT.problems(str(again.text), offered=answers)
                                                                            if p["rule"] != "no_how_to_answer"], [])


def h12_gate_a_reference_block() -> None:
    """t-2181 PC-9c (AR-16, FR-6): the gate A block of a story with a reference is words for a person - the three forms (the full block, the
    one matching line, the unreadable line) pass the report rules and name no key, no snapshot id, no path, no field."""
    facts = {"state": "read", "env": "the old shop", "total": 20, "carried": 17,
             "differing": [{"r": "R-1", "words": "the cart shows the total with tax", "before": "the cart showed 10.00", "now": "the cart shows 11.00", "differs": "yes"},
                           {"r": "R-2", "words": "", "before": "", "now": "", "differs": "unknown"}],
             "parity_gaps": [{"r": "R-3", "words": "an empty cart says so"}],
             "unused": [GB._reference_item_name({"id": "cart-total", "area": "cart page", "user_path": "open the cart and read the total"})],
             "gaps": ["the checkout page needs a sign-in the factory did not have"], "parity": ["R-1", "R-2", "R-3"], "register_unread": False}
    forms = {"full": GB._reference_lines({"reference": facts}),
             "matches": GB._reference_lines({"reference": dict(facts, differing=[], parity_gaps=[], unused=[], gaps=[], carried=20)}),
             "matches, no parity": GB._reference_lines({"reference": dict(facts, differing=[], parity_gaps=[], unused=[], gaps=[], carried=20, parity=[],
                                                                          document="work/reference-behaviours.md")}),
             "full, with the document": GB._reference_lines({"reference": dict(facts, document="work/reference-behaviours.md")}),
             "unreadable": GB._reference_lines({"reference": {"state": "unreadable", "env": "the old shop"}}),
             "register unread": GB._reference_lines({"reference": dict(facts, register_unread=True, differing=[], parity_gaps=[], parity=[])})}
    for name, lines in forms.items():
        text = "\n".join(lines)
        check_eq(f"H12 {name}: the block passes the shape rules of a text a person reads", HT.problems(text, kind="report"), [])
        check_eq(f"H12 {name}: nothing technical in it", [m.group(0) for m in TECHNICAL.finditer(text)], [])
        for raw in ("cart-total", "reference:", "before_ref", "reference-snapshot", "work/", "parity", "true", "false", "None"):
            check_not_in(f"H12 {name}: no raw `{raw}`", raw, text)
    check_in("H12 the full block names the old version, the sample sentence and the count", "17 of the 20 behaviours", forms["full"])
    check_in("H12 the unused item is named by its words", "cart page — open the cart and read the total", forms["full"])
    check_eq("H12 an unknown difference with no words is said as not described, not as an empty cell",
             [l for l in forms["full"] if l.startswith("- R-2")], ["- R-2: the old version is not described; the story now is not described (not known whether this is a difference)"])
    check_eq("H12 the matching form is ONE line after a blank line", (len(forms["matches"]), forms["matches"][0]), (2, ""))
    check_in("H12 the matching form with parity names what the approval confirms (F-7)", "Your approval confirms that these requirements ask to match", forms["matches"][1])
    check_in("H12 the matching form with no parity says the approval confirms none (F4, like the full block)", "so your approval confirms none.", forms["matches, no parity"][1])
    check_in("H12 ... and the full block says it the same way when it has none",
             "so your approval confirms none.", "\n".join(GB._reference_lines({"reference": dict(facts, parity=[])})))
    check_in("H12 the matching form points to the document in words, never by its path", "All of them are listed in the document below.", forms["matches, no parity"][1])
    check_in("H12 the full block's count line points to the document in words", "All of them are listed in the document below.", "\n".join(forms["full, with the document"]))


def main() -> int:
    h12_gate_a_reference_block()
    h11_first_look_same_code_question()
    h10_first_look_dead_question()
    h9_arrival_and_stop_questions()
    h1_gate_b()
    h2_bug_text()
    h3_report()
    h4_delivery_summary()
    h4_plan_rows_equal_report()
    h5_data_row()
    h6_edges()
    h7_merged_bug()
    h8_sides_question_prices()
    h13_absent_side_question()
    return finish("test_human_reading")


if __name__ == "__main__":
    raise SystemExit(main())
