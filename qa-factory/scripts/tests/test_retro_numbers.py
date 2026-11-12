"""retro_numbers.py: the resumes of role sessions, counted per stage with their wall time (t-342, B-273; FR-26, FR-41).

man1 02.10: the S7 analyst was resumed twice (0.9 and 0.6 min) and the S8 scribe once (2.4 min) - about five minutes of
22 - and the retro said nothing of it. The retro now carries, per stage, how many times a role's session was resumed, the
wall time of those calls and the reason each gave (`resume_reason`, written by the driver since B-273), counted from the
driver's own journal (`state/driver-runs.jsonl`: rows of `kind: role` with `resumed: true`), and how many handoffs the
driver built by code instead of resuming (`state/driver-runs/<dispatch>.json` with `assembled_by: code`).

What is held here: the numbers add up from a journal written by hand; a row from before the reason field reads as
`no reason recorded`; a row with no usable duration is counted and never read as zero seconds; a story with no journal
at all is `unknown`, not "no resumes"; the line names its carrier; facts written before the key existed render nothing.

Run on its own: `python -B scripts/tests/test_retro_numbers.py`.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import retro_numbers as RN  # noqa: E402

CLASS_FORM = "the role's final message is not the handoff form"
CLASS_HANDOVER = "the handover form is not complete"


def row(stage: str, role: str, session: str, **extra) -> dict:
    base = {"kind": "role", "role": role, "dispatch": f"{stage}-{role}-1", "stage": stage, "session_id": session,
            "num_turns": 5, "total_cost_usd": 1.0, "resumed": False, "ts": "2026-10-02T10:00:00+00:00"}
    base.update(extra)
    return base


def project() -> tuple:
    root = temp_dir("qa-retro-numbers-")
    base = root / "qa-factory"
    troot = base / "artifacts" / "QA-1"
    (base / "state" / "cost").mkdir(parents=True)
    (troot / "work").mkdir(parents=True)
    (troot / "state" / "driver-runs").mkdir(parents=True)
    (base / "config.json").write_text("{}", encoding="utf-8")
    (troot / "pipeline.json").write_text(json.dumps({"ticket": "QA-1", "size": "M", "stages": {}}), encoding="utf-8")
    (troot / "work" / "test-plan.json").write_text("[]", encoding="utf-8")
    return root, base, troot


def write_journal(troot: Path, rows: list) -> None:
    (troot / "state" / "driver-runs.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def the_resumes_add_up_per_stage() -> None:
    root, base, troot = project()
    try:
        write_journal(troot, [
            row("S2", "qa-requirements-tester", "a", duration_ms=600000),
            row("S2", "qa-requirements-tester", "a", resumed=True, duration_ms=54000, resume_reason=CLASS_FORM),
            row("S7", "qa-failure-analyst", "b", duration_ms=300000),
            row("S7", "qa-failure-analyst", "b", resumed=True, duration_ms=36000, resume_reason=CLASS_HANDOVER),
            row("S7", "qa-failure-analyst", "b", resumed=True, duration_ms=54000, resume_reason=CLASS_HANDOVER),
            # a row from before the reason field, and one with no duration at all
            row("S8", "qa-doc-scribe", "c", resumed=True, duration_ms=144000),
            row("S8", "qa-doc-scribe", "c", resumed=True),
            # not role resumes: a conductor call, a resumed flag that is not the boolean, a launch
            {"kind": "conductor", "role": "", "stage": "S2", "session_id": "k", "resumed": True, "duration_ms": 999000},
            row("S9", "qa-retro-analyst", "d", resumed="true", duration_ms=999000),
        ])
        (troot / "state" / "driver-runs" / "S2-qa-requirements-tester-1.json").write_text(
            json.dumps({"result": "x", "assembled_by": "code"}), encoding="utf-8")
        (troot / "state" / "driver-runs" / "S7-qa-failure-analyst-1.done.json").write_text(
            json.dumps({"result": "x", "assembled_by": "code"}), encoding="utf-8")
        (troot / "state" / "driver-runs" / "S8-qa-doc-scribe-1.json").write_text(
            json.dumps({"result": "x"}), encoding="utf-8")
        data = RN.numbers("QA-1", base, troot)
        got = data["resumes"]
        check_eq("the journal is the carrier, and the story's key says so", got["known"], True)
        check_in("named with the rows it counts", "state/driver-runs.jsonl", got["carrier"])
        check_eq("F6: the cost of a resume is unknown, not a guess (a resumed session's total is cumulative)", got["cost"], "unknown (B-219)")
        check_eq("five resumes of role sessions (the conductor and a non-boolean flag are not)", got["count"], 5)
        check_eq("their wall time is the sum of the calls that carry a duration", got["wall_s"], 288)
        check_eq("one call has no duration: counted, never zero seconds", got["wall_unmeasured"], 1)
        check_eq("two rows name no reason (a row from before the field, and the one with no duration)", got["no_reason"], 2)
        check_eq("S2: one resume, 54 s, its reason", (got["by_stage"]["S2"]["count"], got["by_stage"]["S2"]["wall_s"], got["by_stage"]["S2"]["reasons"]),
                 (1, 54, {CLASS_FORM: 1}))
        check_eq("S7: two resumes, 90 s, one reason twice", (got["by_stage"]["S7"]["count"], got["by_stage"]["S7"]["wall_s"], got["by_stage"]["S7"]["reasons"]),
                 (2, 90, {CLASS_HANDOVER: 2}))
        check_eq("S8: two resumes, 144 s measured, one not, both with `no reason recorded`",
                 (got["by_stage"]["S8"]["count"], got["by_stage"]["S8"]["wall_s"], got["by_stage"]["S8"]["wall_unmeasured"], got["by_stage"]["S8"]["reasons"]),
                 (2, 144, 1, {"no reason recorded": 2}))
        check_eq("a stage with no resume is not listed", sorted(got["by_stage"]), ["S2", "S7", "S8"])
        check_eq("two handoffs were assembled by code instead of resuming, by the stage the dispatch names",
                 (got["assembled_by_code"], got["assembled_by_stage"]), (2, {"S2": 1, "S7": 1}))
        lines = RN.resume_lines(got)
        text = "\n".join(lines)
        check_in("the headline: the count, the wall time, the unmeasured call, the carrier",
                 "**Resumes of role sessions:** 5, 4m 48s of wall time (1 call has no recorded duration) — counted from state/driver-runs.jsonl", text)
        check_in("S2's line carries its reason", f"- S2: 1 · 0m 54s — {CLASS_FORM} ×1", text)
        check_in("S7's line carries the repeat", f"- S7: 2 · 1m 30s — {CLASS_HANDOVER} ×2", text)
        check_in("a row with no reason says so", "no reason recorded ×2", text)
        check_in("the resumes that did not happen are counted", "handoffs the driver assembled by code instead of resuming the role: 2 (S2 1, S7 1)", text)
        check_in("the retro's own render carries the block", "**Resumes of role sessions:** 5", RN.render(data))
        check_in("and so does the JSON form of the facts", '"resumes"', json.dumps(data, default=str))
    finally:
        cleanup(root)


def the_unknown_and_the_empty_are_not_the_same() -> None:
    root, base, troot = project()
    try:
        none = RN.numbers("QA-1", base, troot)["resumes"]
        check_eq("no driver journal: the measurement is unknown, not zero", (none["known"], "no driver journal" in none["reason"]), (False, True))
        text = "\n".join(RN.resume_lines(none))
        check_in("and the line says unknown, with the carrier", "**Resumes of role sessions:** unknown", text)
        check_in("naming where it would have been counted", "state/driver-runs.jsonl", text)
        write_journal(troot, [row("S2", "qa-requirements-tester", "a", duration_ms=1000)])
        zero = RN.numbers("QA-1", base, troot)["resumes"]
        check_eq("a journal with launches and no resume: known, zero", (zero["known"], zero["count"], zero["wall_s"], zero["by_stage"]), (True, 0, 0, {}))
        line = "\n".join(RN.resume_lines(zero))
        check_in("zero resumes is said as a count", "**Resumes of role sessions:** 0 — counted from", line)
        check_not_in("with no wall time invented", "wall time", line)
        # the odd durations of a hand-written or damaged row
        write_journal(troot, [row("S3", "qa-test-strategist", "e", resumed=True, duration_ms=value) for value in
                              (True, -5, "9", None, 1500)])
        odd = RN.numbers("QA-1", base, troot)["resumes"]
        check_eq("a boolean, a negative, a text and a null duration are not seconds; 1500 ms is", (odd["count"], odd["wall_unmeasured"], odd["wall_s"]), (5, 4, 2))
        # a garbage line in the journal does not take the retro down
        (troot / "state" / "driver-runs.jsonl").write_text('not json\n[1, 2]\n' + json.dumps(row("S3", "qa-test-strategist", "e", resumed=True, duration_ms=2000)) + "\n", encoding="utf-8")
        check_eq("an unreadable line is skipped", RN.numbers("QA-1", base, troot)["resumes"]["count"], 1)
        # facts written before the key existed render nothing, and no exception
        check_eq("facts without the key render no line", RN.resume_lines(None), [])
        check_eq("and a render of such facts still works", "Resumes of role sessions" in RN.render({k: v for k, v in RN.numbers("QA-1", base, troot).items() if k != "resumes"}), False)
    finally:
        cleanup(root)


DIGEST_HEAD = "digest: your final message is not the handoff form. The orchestrator reads it whole on every later turn"


def write_records_journal(base: Path, rows: list) -> None:
    path = base / "records" / "journal.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def block(first: str, n: int = 1, event: str = "gate_block") -> dict:
    return {"event": event, "agent": "exit_gate", "notes": f"block 1/1; broken artifacts: {n}; first: {first}"}


def the_class_of_a_gate_block_has_one_reader() -> None:
    """R1 + B-4 (F6-51): the class is the FIRST finding, cut at '; ' then 60 characters, from ONE function the dashboard calls."""
    import factory_dashboard as D
    notes = "block 1/1; broken artifacts: %d; first: s5_precheck.py: REAL exit 1 on the gate re-run"
    check_eq("R1: the three cases of test_retry_reason.py give the same results through the new function",
             (RN.gate_block_class(notes % 1) == RN.gate_block_class(notes % 2),
              RN.gate_block_class("something else entirely")), (True, "something else entirely"))
    check_eq("R1: and the dashboard's reader IS that function's answer",
             [D.gate_block_finding(n) for n in (notes % 1, "something else entirely", "", None)],
             [RN.gate_block_class(n) for n in (notes % 1, "something else entirely", "", None)])
    check_eq("E13: empty notes are counted under a class of their own, not dropped", RN.gate_block_class(""), "(no finding text)")
    check_eq("E13: a missing notes field too", RN.gate_block_class(None), "(no finding text)")
    check_eq("E13: a `first: ` with nothing after it", RN.gate_block_class("block 1/1; first: "), "(no finding text)")
    long = "x" * 100
    check_eq("E13: notes longer than 60 characters after `first: ` are cut AT 60", RN.gate_block_class("first: " + long), "x" * 60)
    check_eq("E13: 59 and 60 characters are kept whole",
             (RN.gate_block_class("first: " + "y" * 59), RN.gate_block_class("first: " + "y" * 60)), ("y" * 59, "y" * 60))
    one = "s5_precheck.py: REAL exit 1 on the gate re-run"
    check_eq("B-4: the same first finding followed by different second findings is ONE class (the under-count side is closed)",
             {RN.gate_block_class(f"block 1/1; first: {one}; witness: run-report.json is stale"),
              RN.gate_block_class(f"block 1/1; first: {one}; case TC-003: no basis"),
              RN.gate_block_class(f"block 1/1; first: {one}")}, {one})


def the_gate_block_line_is_measured_not_assumed() -> None:
    import stage_joints as SJ
    root, base, troot = project()
    saved = SJ.DATA
    try:
        write_records_journal(base, [{"event": "compact", "notes": "x"}])
        counted = RN.numbers("QA-1", base, troot)["journal"]
        check_eq("R2/E10: a journal with no gate_block: known, no class, no worst, no signal",
                 (counted["known"], counted["gate_block_classes"]["classes"], counted["gate_block_classes"]["worst"],
                  counted["gate_block_classes"]["signal"]), (True, {}, None, False))
        check_in("R2: the line is a measured zero", "**Gate blocks by class:** none (0) (records/journal.jsonl).", "\n".join(RN.journal_lines(counted)))
        check_in("R2: and the old counts print as numbers", "**gate blocks:** 0 (the norm is zero)", "\n".join(RN.journal_lines(counted)))
        digest = [block(DIGEST_HEAD + f" — one row per item for role {role}", n) for n, role in
                  zip(range(1, 18), ["qa-scout", "qa-runner", "qa-doc-scribe"] * 6)]
        write_records_journal(base, digest)
        data = RN.numbers("QA-1", base, troot)
        classes = data["journal"]["gate_block_classes"]
        check_eq("R3: 17 digest blocks from three roles, the real 12586 refusal head: ONE class x17 and the signal",
                 (list(classes["classes"].values()), classes["worst"][1], classes["signal"]), ([17], 17, True))
        check_in("R3: the retro prints the class line", "**Gate blocks by class:** " + DIGEST_HEAD[:60] + " ×17", RN.render(data))
        check_in("R3: and the observation, with the rule it breaks", "17 gate blocks of one class", "\n".join(RN.observations(data)))
        check_in("R3: naming the cause is the factory's", "not of the role; it is a finding", "\n".join(RN.observations(data)))
        for count, signal in ((3, True), (2, False), (4, True), (1, False)):
            write_records_journal(base, [block("one finding")] * count)
            got = RN.numbers("QA-1", base, troot)
            check_eq(f"R4/E12: {count} blocks of one class at threshold 3: signal {signal}",
                     got["journal"]["gate_block_classes"]["signal"], signal)
            check_eq(f"R4: and the observation follows the signal ({count})",
                     any("gate blocks of one class" in line for line in RN.observations(got)), signal)
        write_records_journal(base, [block("a")] * 2 + [block("b")] * 2 + [block("c")] * 2)
        check_eq("R4: six blocks in three classes of two each are NOT a signal (the class is the unit)",
                 RN.numbers("QA-1", base, troot)["journal"]["gate_block_classes"]["signal"], False)
        write_records_journal(base, [block("one finding")] * 2 + [block("one finding", event="unsafe_completion")] * 5)
        got = RN.numbers("QA-1", base, troot)["journal"]
        check_eq("R4/E14: unsafe_completion rows are not a class (the existing total still counts them)",
                 (got["gate_block_classes"]["classes"], got["gate_blocks"], got["gate_block_classes"]["signal"]),
                 ({"one finding": 2}, 7, False))
        # R6/E9: the threshold unreadable -> the line says so, no observation, no hidden number
        write_records_journal(base, [block("one finding")] * 9)
        tmp = temp_dir("qa-thr-")
        try:
            (tmp / "no-friction.json").write_text(json.dumps({"joints": []}), encoding="utf-8")
            SJ.DATA = tmp / "no-friction.json"
            got = RN.numbers("QA-1", base, troot)
            check_in("R6/E9: with no threshold the classes are printed and the line says `threshold unknown`",
                     "one finding ×9 (records/journal.jsonl) · threshold unknown (references/stage-joints.json).", RN.render(got))
            check_eq("R6: and no observation is made from a number nobody set", (got["journal"]["gate_block_classes"]["signal"],
                     any("gate blocks of one class" in line for line in RN.observations(got))), (False, False))
        finally:
            SJ.DATA = saved
            cleanup(tmp)
    finally:
        SJ.DATA = saved
        cleanup(root)


def a_missing_journal_prints_unknown_beside_no_zero() -> None:
    """R5 + B-3 (FR-10, FR-41): ONE `known` for the journal line; an absent journal prints `unknown` for every count."""
    root, base, troot = project()
    try:
        data = RN.numbers("QA-1", base, troot)
        journal = data["journal"]
        check_eq("R5/E11: no journal file: known False, no signal", (journal["known"], journal["gate_block_classes"]["known"],
                 journal["gate_block_classes"]["signal"]), (False, False, False))
        text = RN.render(data)
        check_in("R5: the class line says unknown, with its carrier", "**Gate blocks by class:** unknown — no journal (records/journal.jsonl).", text)
        check_in("R5b: and the rejects/gate blocks/compacts line says unknown for each", "**Rejects:** unknown · **gate blocks:** unknown · **compacts:** unknown", text)
        check_not_in("R5b: no zero is printed beside the unknown (the norm-is-zero sentence is for a measured zero)", "(the norm is zero)", text)
        check_eq("R5b: and the observations stay silent about gate blocks", any("gate block" in line for line in RN.observations(data)), False)
        facts_before = {k: v for k, v in data["journal"].items() if k not in ("known", "carrier", "gate_block_classes")}
        check_in("a facts file written before `known` existed prints its counts as before",
                 "**gate blocks:** 3 (the norm is zero)", "\n".join(RN.journal_lines({**facts_before, "gate_blocks": 3})))
        write_records_journal(base, [block("one finding")])
        check_eq("R5 (positive control): the same project WITH a journal is known", RN.numbers("QA-1", base, troot)["journal"]["known"], True)
    finally:
        cleanup(root)


def the_rules_cost_is_never_silently_smaller_than_the_whole() -> None:
    """RC1-14 B-2 (FR-41, AR-22): a role the measure could not read is named beside the total; an unreadable role-load.json
    is an `unknown` line with its reason, never a line that vanishes."""
    import role_load as RL
    rows = [{"role": "qa-scout", "requests": 10}, {"role": "qa-runner", "requests": 10}]
    whole = RN.rules_weight(rows, "claude-sonnet-4-5")
    check_eq("K-B2: with both roles readable nothing is unmeasured", ("unmeasured_roles" in whole, sorted(whole["by_role"])),
             (False, ["qa-runner", "qa-scout"]))
    real = RL.static_load

    def partly_unreadable(role, *args, **kw):
        load = real(role, *args, **kw)
        if role == "qa-runner":      # some of the charter's files could not be read: bytes of the readable ones, measured false
            for layer in load["layers"]:
                if layer["name"] == "charter":
                    layer["measured"] = False
        return load

    RL.static_load = partly_unreadable
    try:
        partial = RN.rules_weight(rows, "claude-sonnet-4-5")
    finally:
        RL.static_load = real
    check_eq("K-B2: a PARTLY unreadable layer is unmeasured, not priced as a whole", (sorted(partial["by_role"]), partial["unmeasured_roles"]),
             (["qa-scout"], ["qa-runner"]))
    text = RN.render({"task": "T", "story": {"usd": 1.0, "tokens": 1}, "orchestrator_share_percent": None, "rules_weight": partial})
    check_in("K-B2: the retro prints the unmeasured role beside the total", "Not measured, so left out of this total: qa-runner", text)
    check_in("K-B2: ... next to the priced sentence", "The rules cost", text)
    nowhere = RN.render({"task": "T", "story": {"usd": 1.0, "tokens": 1}, "orchestrator_share_percent": None, "rules_weight": whole})
    check_not_in("K-B2: with every role measured the line is not there", "Not measured, so left out", nowhere)
    unrated = dict(partial, rate_per_mtok=None, usd=None, by_layer=None, reason="no rate")
    check_in("K-B2: an unknown-rate line names the unmeasured role too", "qa-runner",
             RN.render({"task": "T", "story": {"usd": 1.0, "tokens": 1}, "orchestrator_share_percent": None, "rules_weight": unrated}))
    # the except: an unreadable role-load.json
    real_settings = RL.settings

    def broken(*args, **kw):
        raise RL.RoleLoadError("references/role-load.json could not be read - the role start load was not measured")

    RL.settings = broken
    try:
        unknown = RN.rules_weight(rows, "claude-sonnet-4-5")
    finally:
        RL.settings = real_settings
    check("K-B2: an unreadable role-load.json is an `unknown` answer with the reason, not {}",
          bool(unknown.get("unknown")) and "role-load.json could not be read" in unknown["unknown"], str(unknown))
    text = RN.render({"task": "T", "story": {"usd": 1.0, "tokens": 1}, "orchestrator_share_percent": None, "rules_weight": unknown})
    check_in("K-B2: the retro says the rules' cost is not known, and why", "The rules' cost is not known", text)
    check_in("K-B2: ... with the 'unknown' word and the reason", "unknown: role-load.json or the role files could not be read", text)
    # every role unmeasured: said, not dropped
    RL.static_load = lambda role, *a, **kw: dict(real(role, *a, **kw), layers=[dict(l, bytes=None) for l in real(role, *a, **kw)["layers"]])
    try:
        allgone = RN.rules_weight(rows, "claude-sonnet-4-5")
    finally:
        RL.static_load = real
    check_eq("K-B2: every role unmeasured is an unknown naming them all", (bool(allgone.get("unknown")), allgone.get("unmeasured_roles")),
             (True, ["qa-runner", "qa-scout"]))


def the_retro_prints_the_knowledge_table_beside_the_question_count() -> None:
    """t-2277 FL-8 F1: `retro_numbers.render` shows the question count with its counter-metrics and the table "reached / used / not used"
    (`report_facts`' words, one reader); a story with no such facts renders none of it; an unreadable count is `unmeasured`, never 0."""
    root, base, troot = project()
    try:
        older = RN.numbers("QA-1", base, troot)
        check_eq("F1 CONTROL: a story with no first look and no registry has no knowledge block", "knowledge" in older, False)
        check_not_in("F1 CONTROL: ... and the render prints no such line", "Questions put to the person", RN.render(older))
        (base / "records").mkdir()
        (base / "records" / "project-knowledge.json").write_text(json.dumps({"schema_version": 1, "facts": [
            {"id": "PK-1", "key": "product.roles", "environment": "", "element": "auditor", "state": "known", "scope": "project",
             "value": {"sign_in": "account"}, "provenance": {"source": "person", "words": "w", "story": "T-0", "by": "conductor", "where": ""},
             "at": "2026-11-01T10:00:00+00:00"}]}), encoding="utf-8")
        (troot / "pipeline.json").write_text(json.dumps({"ticket": "QA-1", "size": "M", "stages": {}, "created_at": "2026-11-05T09:00:00+00:00"}),
                                             encoding="utf-8")
        data = RN.numbers("QA-1", base, troot)
        check_in("F1: a story that knew a fact before it began carries the knowledge block", "knowledge_use", data["knowledge"]["facts"])
        text = RN.render(data)
        check_in("F1: the render prints the question count (no register: unmeasured, not 0) with its counter-metrics",
                 "**Questions put to the person: unmeasured: the story has no question register", text)
        check_in("F1: ... and the table of what the story knew, a line per fact", "- registry product.roles auditor: unmeasured: briefs are not kept; unmeasured: ", text)
        (troot / "work" / "requirements-readiness.json").write_text(json.dumps({"open_questions": []}), encoding="utf-8")
        zero = RN.render(RN.numbers("QA-1", base, troot))
        check_in("F1: a register read with no question: ZERO is printed only WITH the counter-metrics",
                 "**Questions put to the person: 0; known facts no brief carried: unmeasured: briefs are not kept", zero)
        check_eq("F1: facts of an older shape (no key) render nothing", RN.knowledge_lines(None), [])
        check_in("F1: a block that could not be built is one `unmeasured` line", "unmeasured: boom", "\n".join(RN.knowledge_lines({"problem": "boom"})))
    finally:
        cleanup(root)


def main() -> None:
    the_retro_prints_the_knowledge_table_beside_the_question_count()
    the_resumes_add_up_per_stage()
    the_unknown_and_the_empty_are_not_the_same()
    the_class_of_a_gate_block_has_one_reader()
    the_gate_block_line_is_measured_not_assumed()
    a_missing_journal_prints_unknown_beside_no_zero()
    the_rules_cost_is_never_silently_smaller_than_the_whole()
    finish("test_retro_numbers")


if __name__ == "__main__":
    main()
