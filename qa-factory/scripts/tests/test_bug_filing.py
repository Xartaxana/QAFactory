#!/usr/bin/env python3
"""The contract of the bug reporter's hand-off and the record of where a filed bug lies (HF8-21, B-183, run 12586).

Keys: F1 the contract resolves, `handoff_init` writes its form, `handoff_check` takes a filled one on both empty paths (the
`gate_b` / `nothing_chosen` row: a quarantine-only decision and `--bugs ordered` with no draft chosen), the gate B contract is
untouched; F2 the reasons tuple equals the data of the words; F3 `filing_of` in every state and its words; F4 the report's lines and
the header of a new bug (an old bug is not refused); F5 a draft the person did not choose says so by a fact of the decision and
no verdict changes.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_dir  # noqa: E402

import bug_records as BR  # noqa: E402
import contract as C  # noqa: E402
import handoff  # noqa: E402
import report_facts as RF  # noqa: E402
import validate_artifacts as V  # noqa: E402
from hooklib import parse_frontmatter  # noqa: E402

CONTRACT = "s8-bug-reporter-to-scribe"
BUG = ("---\nid: BUG-1\ntitle: Move fails\nstatus: open\nseverity: minor\nviolates: requirement:R-5\nsource_draft: work/bug-drafts/move.json\n"
       "gate_b_decision_id: gateB-QA-1\ncases: [TC-002]\nrequirements: [R-5]\nconfirmation: unconfirmed\n---\n# BUG-1\n")


def story(root: Path, channel="markdown", methods=None, pipeline=None, proposal=None, bug=BUG, decision=None) -> Path:
    (root / "qa-factory").mkdir(parents=True, exist_ok=True)
    ew = {"bugs": channel}
    if methods:
        ew["commands"] = {"jira": "write-it"}
    (root / "qa-factory" / "config.json").write_text(json.dumps({"external_writes": ew}), encoding="utf-8")
    task = root / "qa-factory" / "artifacts" / "QA-1"
    (task / "bugs").mkdir(parents=True, exist_ok=True)
    (task / "work" / "proposals").mkdir(parents=True, exist_ok=True)
    (task / "work" / "bug-drafts").mkdir(parents=True, exist_ok=True)
    for old in (task / "work" / "proposals").glob("*.json"):   # the story folder is reused between cases
        old.unlink()
    (task / "pipeline.json").write_text(json.dumps(pipeline or {"ticket": "QA-1"}), encoding="utf-8")
    (task / "bugs" / "BUG-1.md").write_text(bug, encoding="utf-8")
    for name, text in (proposal or {}).items():
        (task / "work" / "proposals" / name).write_text(text if isinstance(text, str) else json.dumps(text), encoding="utf-8")
    if decision:
        (task / "state").mkdir(exist_ok=True)
        (task / "state" / "controller.json").write_text(json.dumps({"decisions": {"gateB-QA-1": decision}}), encoding="utf-8")
    C.case_config_reset()
    return task


def filing(task: Path) -> dict:
    return BR.filing_of(task, BR.story_bugs(task)["records"][0])


FORM = """schema_version: 1
contract: s8-bug-reporter-to-scribe
stage: S8
from_role: qa-bug-reporter
to_role: qa-doc-scribe
inputs:
  - path: work/handoffs/d.yaml
    what: this file
    required: true
inputs_read:
  - path: work/handoffs/g.yaml
    version: gateB-QA-1
    drafts_chosen: {chosen}
header:
  role: qa-bug-reporter
  stage: S8
  window: QA-1
  verdict: ok
scope:
  - id: {rid}
    state: {state}
    reason: {reason}
filed: {filed}
not_filed: []
quarantined: {quarantined}
claims:
  every_chosen_draft_has_a_row_in_scope: true
  every_filed_bug_names_its_draft_and_its_case_or_says_why_not: true
  no_bug_was_filed_for_a_draft_the_person_did_not_choose: true
  nothing_was_written_to_the_tracker_by_the_role: true
tried:
  - requirement: {rid}
    technique: searched the tracker for a duplicate of the draft by its title
    observation: no existing issue matched the draft
    evidence: work/bug-drafts/move.json
tried_note: "-"
unresolved: []
blocked:
  field: none
  problem: none
  tried:
    - none
  data:
    - none
"""
FILED = """
  - draft: work/bug-drafts/move.json
    bug: BUG-1
    action: created
    cases: TC-002
    no_case_reason: "-"
    requirements: R-5
    source_draft: work/bug-drafts/move.json
    proposal: "-"
"""
QUAR = """
  - id: test_a
    debt_file: bugs/DEBT-1.md
    trigger: the stand is stable"""


def f1_the_contract() -> None:
    check_eq("F1 S8 reporter -> scribe resolves", handoff.contract_of("S8", "qa-bug-reporter"), CONTRACT)
    check_eq("F1 the scribe's own S8 contract is not displaced", handoff.contract_of("S8", "qa-doc-scribe"), "s8-scribe-to-gate-b")
    check_eq("F1 gate B -> the reporter is untouched", handoff.contract_of("B", "person"), "gate-b-to-delivery")
    root = temp_dir("qa-bugfile-f1-")
    try:
        task = story(root)
        res = run_script("handoff_init.py", "--task", "QA-1", "--task-root", task, "--stage", "S8", "--role", "qa-bug-reporter",
                         "--dispatch", "d1")
        out = task / "work" / "handoffs" / "d1.yaml"
        check("F1 handoff_init writes the form for S8 / qa-bug-reporter", res.returncode == 0 and out.is_file(), (res.stdout + res.stderr)[-300:])
        cases = {
            "a bug filed": FORM.format(chosen=1, rid="work/bug-drafts/move.json", state="filed", reason="filed as BUG-1", filed=FILED, quarantined="[]"),
            "no draft chosen, a quarantine": FORM.format(chosen=0, rid="gate_b", state="nothing_chosen", reason="a quarantine only", filed="[]", quarantined=QUAR),
            "no draft chosen, bugs ordered with none": FORM.format(chosen=0, rid="gate_b", state="nothing_chosen", reason="bugs ordered, none chosen", filed="[]", quarantined="[]"),
        }
        for label, text in cases.items():
            path = task / "work" / "handoffs" / "filled.yaml"
            path.write_text(text, encoding="utf-8")
            res = run_script("handoff_check.py", "--file", path, "--task-root", task, "--task", "QA-1")
            check(f"F1 handoff_check takes the filled form ({label})", res.returncode == 0, (res.stdout + res.stderr)[-500:])
        path = task / "work" / "handoffs" / "empty.yaml"
        path.write_text(FORM.format(chosen=0, rid="x", state="nothing_chosen", reason="r", filed="[]", quarantined="[]").replace(
            "  - id: x\n    state: nothing_chosen\n    reason: r\n", "  []\n").replace("scope:\n  []", "scope: []"), encoding="utf-8")
        res = run_script("handoff_check.py", "--file", path, "--task-root", task, "--task", "QA-1")
        check("F1 an EMPTY scope is still refused (the `gate_b` row is the empty outcome, NE33)", res.returncode != 0, res.stdout[-300:])
    finally:
        cleanup(root)


def f2_the_words() -> None:
    text = (Path(__file__).resolve().parents[2] / "handoffs" / "vocabulary.yaml").read_text(encoding="utf-8")
    block = re.search(r"^bug_not_sent_reasons:\n((?:  \w+: .+\n)+)", text, re.MULTILINE)
    keys = tuple(m.group(1) for m in re.finditer(r"^  (\w+): ", block.group(1), re.MULTILINE)) if block else None
    check_eq("F2 vocabulary.yaml bug_not_sent_reasons has the keys of the contract's tuple", keys, tuple(C.BUG_NOT_SENT_REASONS))
    words = handoff.vocabulary().get("bug_not_sent_reasons") or {}
    check_eq("F2 every reason has a word a person reads", sorted(k for k, v in words.items() if str(v).strip()), sorted(C.BUG_NOT_SENT_REASONS))
    check("F2 the two new row states are in the vocabulary", {"not_filed", "nothing_chosen"} <= set(handoff.vocabulary()["row_states"]), "")
    check_in("F2 `run_closed` says what happened: an experiment that sends nothing (F-12)", "experiment", str(words.get("run_closed")))
    check_not_in("F2 ... and not that a write was made too late", "before the write", str(words.get("run_closed")))


def f3_filing_of() -> None:
    root = temp_dir("qa-bugfile-f3-")
    try:
        def state_of(**kw):
            t = filing(story(root, **kw))["tracker"]
            return t["state"], t["why"]
        check_eq("F3 markdown: not sent, the project's choice", state_of(), ("not_sent", "project_choice"))
        check_eq("F3 the file is the bug's own", filing(story(root))["file"], "bugs/BUG-1.md")
        words = BR.filing_words(filing(story(root)))
        check_eq("F3 words: markdown", words, "file: bugs/BUG-1.md · tracker: not sent — the project keeps bugs in markdown")
        sent = {"bug-1.json": {"kind": "bug", "bug_file": "bugs/BUG-1.md", "result": {"external_id": "PRJ-7", "url": "https://t/PRJ-7"}}}
        got = filing(story(root, "jira", True, proposal=sent))
        check_eq("F3 jira + receipt: sent with the key", (got["tracker"]["state"], got["tracker"]["key"]), ("sent", "PRJ-7"))
        check_in("F3 words: sent", "tracker: sent as PRJ-7", BR.filing_words(got))
        # HF821-F3d (t-428): the file's OWN id is a recorded id too, with no proposal at all (the project keeps bugs in markdown,
        # so only the id says "sent")
        own = BUG.replace("confirmation: unconfirmed\n", "confirmation: unconfirmed\nexternal_id: PRJ-9\nexternal_url: https://t/PRJ-9\n")
        got = filing(story(root, bug=own))
        check_eq("F3 a bug file that carries its own external_id: sent with that key and url",
                 (got["tracker"]["state"], got["tracker"]["key"], got["tracker"]["url"]), ("sent", "PRJ-9", "https://t/PRJ-9"))
        check_eq("F3 jira, a proposal and no result: pending", state_of(channel="jira", methods=True,
                 proposal={"bug-1.json": {"kind": "bug", "bug_file": "bugs/BUG-1.md"}}), ("pending", ""))
        check_eq("F3 jira, no receipt at all: unknown, never sent", state_of(channel="jira", methods=True), ("unknown", ""))
        check_in("F3 words: unknown", "the tracker receipt could not be read",
                 BR.filing_words(filing(story(root, "jira", True, proposal={"bug-1.json": "{not json"}))))
        check_eq("F3 jira, a broken proposal: unknown", state_of(channel="jira", methods=True, proposal={"bug-1.json": "{not json"}), ("unknown", ""))
        check_eq("F3 jira with no delivery configured: no access", state_of(channel="jira"), ("not_sent", "no_access"))
        check_eq("F3 the run is closed (no_trace): run closed", state_of(channel="jira", methods=True, pipeline={"no_trace": True}), ("not_sent", "run_closed"))
        word = {"gate_waivers": [{"stage": "S8", "decision": "keep it local, please"}]}
        check_eq("F3 the person said keep it local at gate B", state_of(channel="jira", methods=True, pipeline=word), ("not_sent", "gate_b_word"))
        check_eq("F3 a waiver of another stage is not that word", state_of(channel="jira", methods=True,
                 pipeline={"gate_waivers": [{"stage": "S5", "decision": "keep it local"}]}), ("unknown", ""))
        # F-4: the twin of `external_writes.local_only_decision` skips a row with EMPTY words (the executor does, then tries to send)
        empty = {"gate_waivers": [{"stage": "S8", "decision": "", "requirement": "keep it local"}]}
        check_eq("F3 a row with empty words is not 'you said keep it local'", state_of(channel="jira", methods=True, pipeline=empty), ("unknown", ""))
        check_eq("F3 ... and the executor's own reader agrees (control)", BR._kept_local_by_word(story(root, channel="jira", methods=True, pipeline=empty)), False)
        check("F3 channel `none` is no markdown choice (the executor's pair is \"\" and markdown)",
              state_of(channel="none", methods=True) != ("not_sent", "project_choice"), str(state_of(channel="none", methods=True)))
        for why in C.BUG_NOT_SENT_REASONS:
            say = BR.filing_words({"file": "bugs/BUG-1.md", "tracker": {"state": "not_sent", "why": why}})
            check(f"F3 words for `{why}` exist", "cannot say" not in say, say)
        check_in("F3 an unknown reason is said, not guessed", "the factory cannot say why",
                 BR.filing_words({"file": "bugs/BUG-1.md", "tracker": {"state": "not_sent", "why": "x"}}))
        check_eq("F3 a draft nobody filed has no file and no words", (BR.filing_of(root, {"paths": ["/x/work/bug-drafts/a.json"]})["file"],
                 BR.filing_words(BR.filing_of(root, {"paths": ["/x/a.json"]}))), ("", ""))
        check_eq("F3 a record with no paths never raises", BR.filing_of(root, None)["file"], "")
        # t-436: a delivery that is not configured is `no_access` only when every proposal could be read; a proposal file that
        # cannot be read may have been this bug's, so the state is `unknown` (FR-59: an unknown is not a reason)
        check_eq("F3 (t-436) jira with no delivery configured but a proposal file that cannot be read: unknown, not no access",
                 state_of(channel="jira", proposal={"bug-1.json": "{not json"}), ("unknown", ""))
        check_eq("F3 (t-436) ... control: the same channel with nothing broken is no access", state_of(channel="jira"), ("not_sent", "no_access"))
        # t-436: "Never raises": a bug file whose bytes are not UTF-8 is a filing we cannot establish, not an exception
        task = story(root)
        (task / "bugs" / "BUG-1.md").write_bytes(b"---\nid: BUG-1\ntitle: \xff\xfe\x00 broken\n---\n")
        broken = BR.filing_of(task, {"paths": [str(task / "bugs" / "BUG-1.md")]})
        check_eq("F3 (t-436) a bug file that cannot be decoded: unknown, no exception, the file still named",
                 (broken["file"], broken["tracker"]["state"], broken["tracker"]["why"]), ("bugs/BUG-1.md", "unknown", ""))
        # t-436: the `.md` suffix is read without regard to case
        task = story(root)
        (task / "bugs" / "BUG-2.MD").write_text(BUG.replace("BUG-1", "BUG-2"), encoding="utf-8")
        capital = BR.filing_of(task, {"paths": [str(task / "bugs" / "BUG-2.MD")]})
        check_eq("F3 (t-436) a bug file named `BUG-2.MD` is a bug file",
                 (capital["file"], capital["tracker"]["state"], capital["tracker"]["why"]), ("bugs/BUG-2.MD", "not_sent", "project_choice"))
        # t-436: the words of every state, exactly
        file = "file: bugs/BUG-1.md · tracker: "
        said = {
            "sent with a key and a url": ({"state": "sent", "key": "PRJ-7", "url": "https://t/PRJ-7"}, file + "sent as PRJ-7 (https://t/PRJ-7)"),
            "sent with a key, no url": ({"state": "sent", "key": "PRJ-7", "url": ""}, file + "sent as PRJ-7"),
            "sent with no key": ({"state": "sent", "key": "", "url": ""}, file + "sent as an issue"),
            "pending (no `unknown` prefix: the write is known to be waiting)": (
                {"state": "pending"}, file + "the write is proposed and not made yet"),
            "unknown": ({"state": "unknown"}, file + "unknown — the tracker receipt could not be read"),
            "a state nobody knows": ({"state": "weird"}, file + "unknown — the tracker receipt could not be read"),
            "no tracker at all": (None, file + "unknown — the tracker receipt could not be read"),
        }
        for label, (tracker, expected) in said.items():
            check_eq(f"F3 (t-436) words: {label}", BR.filing_words({"file": "bugs/BUG-1.md", "tracker": tracker}), expected)
    finally:
        cleanup(root)


def f4_the_report_and_the_header() -> None:
    root = temp_dir("qa-bugfile-f4-")
    try:
        task = story(root)
        facts = RF._bugs(root / "qa-factory", task, {})
        line = RF._r_bugs({"bugs": facts, "unknown": {}})
        check_in("F4 the report line carries file and tracker", "file: bugs/BUG-1.md · tracker: not sent — the project keeps bugs in markdown", line)
        check_eq("F4 the record carries `filing`", facts["records"][0]["filing"]["file"], "bugs/BUG-1.md")
        errors: list = []
        V.check_bug_filing_header(Path("BUG-2.md"), parse_frontmatter(BUG), errors)
        check_eq("F4 a bug with case and requirements passes", errors, [])
        new = parse_frontmatter(BUG.replace("cases: [TC-002]\n", "").replace("requirements: [R-5]\n", ""))
        V.check_bug_filing_header(Path("BUG-2.md"), new, errors)
        check_eq("F4 a new bug with neither is refused twice", len(errors), 2)
        errors = []
        V.check_bug_filing_header(Path("BUG-2.md"), dict(new, cases="[]", no_case_reason="the defect is in no case", requirements="[R-5]"), errors)
        check_eq("F4 `cases: []` with a reason passes", errors, [])
        errors = []
        V.check_bug_filing_header(Path("BUG-2.md"), dict(new, cases="[]", requirements="[R-5]"), errors)
        check_eq("F4 `cases: []` without a reason is refused", len(errors), 1)
        old = BUG.replace("source_draft: work/bug-drafts/move.json\n", "").replace("cases: [TC-002]\n", "").replace("requirements: [R-5]\n", "")
        check_eq("F4 an old bug (no source_draft) is not asked", "FORM" in " ".join(_errors_of(root, old)), False)
        # F-1: the R-n is asked only of an oracle that IS a requirement; every other oracle of the grammar has its empty outcome
        for oracle in ("invariant:no-data-loss", "consistency:the list and the card differ", "history:release 4", "impact:money is lost",
                       "external:RFC 7231"):
            errors = []
            V.check_bug_filing_header(Path("BUG-3.md"), dict(new, violates=oracle, cases="[TC-002]", requirements="[]"), errors)
            check_eq(f"F4 oracle `{oracle.split(':')[0]}:` with `requirements: []` passes", errors, [])
            errors = []
            V.check_bug_filing_header(Path("BUG-3.md"), dict(new, violates=oracle, cases="[TC-002]"), errors)
            check_eq(f"F4 oracle `{oracle.split(':')[0]}:` with no `requirements` key passes", errors, [])
        errors = []
        V.check_bug_filing_header(Path("BUG-3.md"), dict(new, violates="requirement:R-5", cases="[TC-002]", requirements="[]"), errors)
        check_eq("F4 a `requirement:` oracle with no R-n is still refused (control)", len(errors), 1)
        # F-3: the real old shape (12586 BUG-1.md): source_draft, no cases, no requirements, made before the release
        form = {"id": "BUG-1", "title": "Move fails", "status": "open", "severity": "minor", "area": "a", "found_by": "x",
                "violates": "requirement:R-5", "impact": "degraded", "source_draft": "work/bug-drafts/move.json",
                "gate_b_decision_id": "gateB-QA-1", "confirmation": "unconfirmed"}
        body = "# BUG-1\n\n## User impact\n\nx\n\n## Initial state\n\ny\n"
        for created, asked in (("2026-10-02T10:00:00", False), ("2026-10-30T23:59:00", False), ("2026-10-31T00:00:00", True)):
            errors = []
            V.check_bug_form(Path("BUG-1.md"), dict(form, created=created), body, errors)
            check_eq(f"F4 a bug created {created[:10]} with source_draft and no cases: header asked = {asked}",
                     any("'cases' is missing" in e for e in errors), asked)
    finally:
        cleanup(root)


def f4b_the_producer_offers_the_keys() -> None:
    """F-5: the producer's template offers the three keys, so a correct bug does not pay one refusal for them."""
    import artifact_producer as AP
    keys = set(AP.prepare("bug")["frontmatter"])
    check("F5b the bug template offers cases, requirements and no_case_reason", {"cases", "requirements", "no_case_reason"} <= keys, str(sorted(keys)))
    filled = {k: "x" for k in keys}
    check("F5b a template filled and rendered keeps the three keys", all(f"{k}:" in AP.render({"frontmatter": filled, "body": "b"})
                                                                      for k in ("cases", "requirements", "no_case_reason")), "")


def _errors_of(root: Path, text: str) -> list:
    path = root / "OLD-BUG.md"
    path.write_text(text, encoding="utf-8")
    errors: list = []
    fm = parse_frontmatter(text) or {}
    if str(fm.get("source_draft", "")).strip():
        V.check_bug_filing_header(path, fm, errors)
    return errors


def f5_gate_b_not_chosen() -> None:
    root = temp_dir("qa-bugfile-f5-")
    try:
        draft = {"title": "Move fails", "impact": "degraded", "violates": "requirement:R-5", "case": "TC-002", "confirmation": "unconfirmed"}
        decision = {"gate": "B", "status": "approved", "selected_drafts": ["work/bug-drafts/other.json"],
                    "authorization_source": "file 1 only, 2 is not a bug"}
        base = story(root, bug="---\nid: X\n---\n")
        (base / "bugs" / "BUG-1.md").unlink()
        (base / "work" / "bug-drafts" / "move.json").write_text(json.dumps(draft), encoding="utf-8")
        before = RF._bugs(root / "qa-factory", base, {})
        check_eq("F5 gate B not decided: no claim about the choice", before["records"][0]["gate_b_not_chosen"], False)
        task = story(root, bug="---\nid: X\n---\n", decision=decision)
        (task / "bugs" / "BUG-1.md").unlink()
        (task / "work" / "bug-drafts" / "move.json").write_text(json.dumps(draft), encoding="utf-8")
        after = RF._bugs(root / "qa-factory", task, {})
        check_eq("F5 a draft outside selected_drafts: the fact, true", after["records"][0]["gate_b_not_chosen"], True)
        text = RF._r_bugs({"bugs": after, "unknown": {}})
        check_in("F5 the report says so with the person's words verbatim", "you did not choose this one at gate B (your words: file 1 only, 2 is not a bug)", text)
        check("F5 the code claims nothing about 'not a bug'", "gate_b_said_not_bug" not in json.dumps(after), "")
        check_eq("F5 the counts and the word of the record are the same as before the decision",
                 (before["confirmed"], before["unconfirmed"], before["records"][0]["confirmation"]),
                 (after["confirmed"], after["unconfirmed"], after["records"][0]["confirmation"]))
        decision["selected_drafts"] = ["work/bug-drafts/move.json"]
        chosen = story(root, bug="---\nid: X\n---\n", decision=decision)
        (chosen / "bugs" / "BUG-1.md").unlink()
        (chosen / "work" / "bug-drafts" / "move.json").write_text(json.dumps(draft), encoding="utf-8")
        check_eq("F5 a chosen draft is not 'not chosen'", RF._bugs(root / "qa-factory", chosen, {})["records"][0]["gate_b_not_chosen"], False)
    finally:
        cleanup(root)


def f5b_gate_b_choice_edges() -> None:
    """t-436: which decision is THE gate B decision, and which bugs the fact `not chosen` may be said about."""
    root = temp_dir("qa-bugfile-f5b-")
    try:
        task = story(root)
        older = {"id": "gateB-QA-1", "gate": "B", "status": "approved", "selected_drafts": ["work/bug-drafts/a.json"],
                 "authorization_source": "the first words"}
        newer = {"id": "gateB-QA-1-2", "gate": "B", "status": "approved", "selected_drafts": ["work/bug-drafts/b.json"],
                 "authorization_source": "the second words"}
        gate_a = {"id": "gateA-QA-1", "gate": "A", "status": "approved", "selected_drafts": ["work/bug-drafts/z.json"]}
        refused = {"id": "gateB-QA-1-3", "gate": "B", "status": "rejected", "selected_drafts": ["work/bug-drafts/c.json"],
                   "authorization_source": "the refused words"}

        def decisions(*rows, names=None):
            (task / "state").mkdir(exist_ok=True)
            (task / "state" / "controller.json").write_text(json.dumps({"decisions": {r["id"]: r for r in rows}}), encoding="utf-8")
            (task / "pipeline.json").write_text(json.dumps({"ticket": "QA-1", "gates": {"B": {"id": names}} if names else {}}), encoding="utf-8")
            return BR.gate_b_choice(task)

        got = decisions(older, newer, names="gateB-QA-1")
        check_eq("F5b the decision the pipeline names wins over a newer one in the file",
                 (got["decided"], got["selected"], got["words"]), (True, ["work/bug-drafts/a.json"], "the first words"))
        got = decisions(older, newer)
        check_eq("F5b the pipeline names none: the last recorded one", (got["selected"], got["words"]),
                 (["work/bug-drafts/b.json"], "the second words"))
        got = decisions(older, newer, names="gateB-NOT-THERE")
        check_eq("F5b the pipeline names an id the file does not hold: the last recorded one", got["selected"], ["work/bug-drafts/b.json"])
        got = decisions(older, refused)
        check_eq("F5b a gate B decision that was not approved is not read, whatever its place", (got["selected"], got["words"]),
                 (["work/bug-drafts/a.json"], "the first words"))
        got = decisions(older, gate_a)
        check_eq("F5b a decision of another gate is not read", got["selected"], ["work/bug-drafts/a.json"])
        got = decisions(refused, gate_a)
        check_eq("F5b only decisions that are not gate B approvals: not decided", (got["decided"], got["selected"], got["words"]), (False, [], ""))

        # a FILED bug is never `not chosen`, and neither is a draft of any spelling of a chosen ref
        drafts = task / "work" / "bug-drafts"
        move = {"paths": [str(drafts / "move.json")]}
        filed = {"paths": [str(task / "bugs" / "BUG-1.md")], "filed": True}
        other = {"decided": True, "selected": ["work/bug-drafts/other.json"], "words": ""}
        check_eq("F5b a draft nobody filed that the decision did not choose: true", BR.not_chosen_at_gate_b(task, move, other), True)
        check_eq("F5b ... the same record once it is filed: false, whatever the decision chose", BR.not_chosen_at_gate_b(
                 task, dict(move, filed=True), other), False)
        check_eq("F5b ... a filed bug file of the story: false", BR.not_chosen_at_gate_b(task, filed, other), False)
        check_eq("F5b ... the same bug file with `filed` absent would be true (control: the flag is what holds it)",
                 BR.not_chosen_at_gate_b(task, {"paths": filed["paths"]}, other), True)
        for ref in ("work/bug-drafts/move.json", "bug-drafts/move.json"):
            check_eq(f"F5b a draft whose ref is `{ref}` in the decision is chosen",
                     BR.not_chosen_at_gate_b(task, move, dict(other, selected=[ref])), False)
        check_eq("F5b a draft with no path of the story is never `not chosen`", BR.not_chosen_at_gate_b(
                 task, {"paths": []}, other), False)
        check_eq("F5b a gate B not yet decided says nothing", BR.not_chosen_at_gate_b(task, move, dict(other, decided=False)), False)
    finally:
        cleanup(root)


def f7_one_bug_many_manifestations() -> None:
    """t-2187 N4 (row 5.13): the bug file of a draft with 2+ manifestations carries every case, `## Cause` and `## Manifestations`
    (each line: its case and its red test or why there is none). Without the resolved draft nothing new is checked and the
    producer SAYS so; an old draft or a one-manifestation draft files exactly as before."""
    import artifact_producer as AP
    root = temp_dir("qa-bugfile-f7-")
    try:
        task = story(root)
        base = "# BUG-1\n\n## User impact\n\nx\n\n## Initial state\n\ny\n"
        merged_body = (base + "\n## Cause\n\nthe field turns any unreadable value into 1.\n\n## Manifestations\n\n"
                       "- TC-002: type -1; seen 11; red test: `pytest t1.py -k neg`\n"
                       "- TC-007: type 1.5; seen 11; no test: manual check only, not in the regression\n")
        fm = {"id": "BUG-1", "title": "Quantity coerced", "status": "Open", "severity": "minor", "area": "cart", "found_by": "x",
              "violates": "requirement:R-5", "impact": "degraded", "created": "2026-11-10T10:00:00", "source_draft": "work/bug-drafts/qty.json",
              "gate_b_decision_id": "gateB-QA-1", "confirmation": "unconfirmed", "cases": ["TC-002", "TC-007"], "requirements": ["R-5"],
              "red_test": "t1.py -- pytest t1.py -k neg"}

        def put(draft) -> None:
            (task / "work" / "bug-drafts" / "qty.json").write_text(json.dumps(draft), encoding="utf-8")

        def errs(front, body, **kw) -> list:
            return [e for e in AP.validate("bug", {"frontmatter": front, "body": body}, **kw) if "FORM" in e or "source draft" in e]

        two = {"title": "t", "case": "TC-002", "manifestations": [
            {"action": "type -1", "start_state": "selected", "seen": "11", "case": "TC-002", "evidence": "e1",
             "red_test": {"path": "t1.py", "command": "pytest t1.py -k neg"}},
            {"action": "type 1.5", "start_state": "erased", "seen": "11", "case": "TC-007", "evidence": "e2",
             "red_test_none": "manual check only, not in the regression"}]}
        put(two)
        check_eq("F7 a merged bug file with every case, both sections and each line: clean", errs(fm, merged_body, task_root=task), [])
        got = errs(fm, base, task_root=task)
        check("F7 no `## Cause` and no `## Manifestations`: a FORM error for each, with the door",
              any('no "## Cause" section' in e for e in got) and any('no "## Manifestations" section' in e for e in got)
              and all("work/bug-text/qty.md" in e for e in got), str(got))
        got = errs(dict(fm, cases=["TC-002"]), merged_body, task_root=task)
        check("F7 a manifestation's case missing from `cases`: refused, names it", len(got) == 1 and "'cases' lacks ['TC-007']" in got[0], str(got))
        got = errs(fm, merged_body.replace("pytest t1.py -k neg", "pytest"), task_root=task)
        check("F7 a line without its red test command: refused", len(got) == 1 and "red test command" in got[0], str(got))
        got = errs(fm, merged_body.replace("no test: manual check only, not in the regression", "later"), task_root=task)
        check("F7 a line without the reason it has no red test: refused", len(got) == 1 and "reason it has no red test" in got[0], str(got))
        got = errs(fm, merged_body.replace("- TC-007:", "- TC-9:"), task_root=task)
        check("F7 a line that does not name its case: refused", any("does not name the case TC-007" in e for e in got), str(got))
        # no resolved draft: nothing new is checked, and the producer says so (never a pass)
        left: list = []
        check_eq("F7 no task root: the merged-draft check is not run, no error", errs(fm, base, not_checked=left), [])
        check_eq("F7 ... and the producer says it was not checked", left, ["the manifestations of the source draft were not checked (no task root)"])
        check_eq("F7 ... a caller passing no list still gets no error and no exception", errs(fm, base), [])
        errors: list = []
        V.check_bug_form(Path("BUG-1.md"), dict(fm), base, errors)
        check_eq("F7 check_bug_form with draft=None: today's errors (none) and no not-checked claim of a pass", errors, [])
        # an unreadable draft is a FORM line, never a pass
        (task / "work" / "bug-drafts" / "qty.json").unlink()
        got = errs(fm, merged_body, task_root=task)
        check("F7 the draft is gone: one FORM line says it cannot be read", len(got) == 1 and "cannot be read" in got[0], str(got))
        # old draft and a one-manifestation draft: valid exactly as today
        put({"title": "t", "case": "TC-002"})
        check_eq("F7 an old draft (no manifestations): no new error", errs(dict(fm, cases=["TC-002"]), base, task_root=task), [])
        put(dict(two, manifestations=two["manifestations"][:1]))
        check_eq("F7 a one-manifestation draft: valid as today (no sections asked)", errs(dict(fm, cases=["TC-002"]), base, task_root=task), [])
        put(dict(two, manifestations="not a list"))
        check_eq("F7 a malformed `manifestations`: reads as none, no new error", errs(dict(fm, cases=["TC-002"]), base, task_root=task), [])
    finally:
        cleanup(root)


for step in (f1_the_contract, f2_the_words, f3_filing_of, f4_the_report_and_the_header, f4b_the_producer_offers_the_keys, f5_gate_b_not_chosen,
             f5b_gate_b_choice_edges, f7_one_bug_many_manifestations):
    step()
finish("test_bug_filing")
