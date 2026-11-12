#!/usr/bin/env python3
"""GW1-1: a person's word names a line by a WHOLE identifier, and a revoked word acts nowhere.

CART-1 / B-338 / B-414: `waiver.split_overridden` matched a word by substring, so `R-3` passed a line about `BR-3`, `PC-1` one
about `PC-10`, `test_x` the variant `test_x[1]`. The one predicate is `contract.names_whole`; the one filter of a live word is
`contract.live_stage_overrides`; the one reader of which stand-gap answer lives is `contract.stand_gap_live_entries`.

Keys: K1 the predicate table (names_whole); K2 split_overridden (whole word, `*`, placeholder, revoked, blank);
K3 live_stage_overrides / stage_override_values never raise and drop the revoked; K4 the stand-gap answers across a revoke;
K5 the readers of P7 skip a revoked word; K6 the refusal of a placeholder (P4); K7 _dispatch_for and recheck_stage_block;
K8 the door the code prints passes its own check (P10); K9 REQ_ID_RE stands alone; K10 the registry row.
Non-ASCII inputs are written as \\uXXXX escapes: the package carries no Cyrillic (FR-30).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, cleanup, finish, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import contract as C  # noqa: E402
import waiver as W  # noqa: E402


# Non-ASCII inputs of the table are built from code points: the package carries no Cyrillic, not even in a fixture (FR-30).
ARABIC3 = chr(0x663)        # an Arabic-Indic digit three: \w and \d in Python, not the ASCII 3
CYR_R = chr(0x420)          # the Cyrillic capital that looks like R
NB_HYPHEN = chr(0x2011)     # a non-breaking hyphen
FULLWIDTH_R = chr(0xFF32)
ZWSP = chr(0x200B)          # outside harmless: not a word character


def ov(stage="S5", match="x", decision="said so", at="2026-10-01T10:00:00+00:00", **extra) -> dict:
    return {"stage": stage, "match": match, "decision": decision, "at": at, "by": "human", **extra}


def pipe(*entries) -> dict:
    return {"stage_overrides": list(entries)}


def passes(match, line, stage="S5", **extra) -> bool:
    return bool(W.split_overridden([line], pipe(ov(stage, match, **extra)), stage)[1])


def k1_the_predicate_table() -> None:
    no = [("R-3", "BR-3"), ("R-3", "X-R-3"), ("R-3", "R-30"), ("R-3", "R-3-a"), ("R-3", "R-3a"), ("R-3", "R-3.1"),
          ("R-3", "R-3[1]"), ("R-3", "R-3_x"), ("R-3", "R-3:x"), ("R-1", "R-1/R-3"),
          ("R-" + ARABIC3, "R-3"), ("R-3", "R-" + ARABIC3), ("R-3", CYR_R + "-3"), ("R-3", "R" + NB_HYPHEN + "3"),
          ("R-3", "R-3" + ARABIC3), ("R-3", FULLWIDTH_R + "-3"), ("RP-web", "RP-web-e2e"), ("PC-1", "PC-10"), ("TC_1", "TC_10"),
          ("TP1-1_TC_002", "TP1-1_TC_0021"), ("tests/a.py::test_x", "tests/a.py::test_x[1]"),
          ("tests/a.py::test_x", "tests/a.py::test_x2"), ("material unavail", "material unavailable"),
          ("probe gap: R-3", "PROBE  GAP: R-3"), ("", "anything"), ("   ", "anything"), ("R-3", "")]
    # GW1-52: the hostile variants of the right edge (a mark followed by ANY non-space character)
    no += [("a.py::test_x", "a.py::test_x[-1]"), ("a.py::test_x", "a.py::test_x[(1, 2)]"), ("a.py::test_x", 'a.py::test_x["a"]'),
           ("PC-1", "PC-1@TC_002"), ("tests\\a", "tests\\a\\b.py"), ("R-3", "R-3.1")]
    for needle, text in no:
        check_eq(f"K1 no: {needle!r} is not in {text!r}", C.names_whole(needle, text), False)
    yes = [("R-3", "R-3."), ("R-3", "R-3:"), ("R-3", "R-3: x"), ("R-3", "R-3)"), ("R-3", "(R-3)"), ("R-3", "`R-3`"),
           ("R-3", "R-3.\n"), ("R-3", "R-3"), ("R-3", "r-3"), ("r-3", "R-3"), ("R-3", "R-1/R-3"), ("R-3", "R-3, R-4"),
           ("R-3", "R-3" + ZWSP), ("a.py", "tests/a.py"), ("a.py::t", "x/a.py::t"), ("`R-3`", "see `R-3` here"),
           ("probe gap: R-3", "Probe gap: R-3 is open")]
    # GW1-52: whole mentions the wider right edge must keep; and the pinned edge of a needle ending in a non-word character
    # (no right guard, as before: a needle ending in `:` or a backtick asks nothing of its right side)
    yes += [("R-3", "R-3. "), ("R-3", "(R-3)"), ("R-3", "R-3, R-4"), ("R-3", "R-3 [x]"), ("tests\\a", "see tests\\a"),
            ("a.py::", "a.py::test_x"), ("`R-3`", "`R-3`x")]
    for needle, text in yes:
        check_eq(f"K1 yes: {needle!r} is in {text!r}", C.names_whole(needle, text), True)
    check_eq("K1 non-strings are read through str(), never raise", (C.names_whole(None, "x"), C.names_whole(3, "a 3 b"),
                                                                    C.names_whole("x", None)), (False, True, False))


def k2_split_overridden() -> None:
    check("K2 R-3 passes the line about R-3", passes("R-3", "no oracle for R-3 in the plan"))
    check("K2 R-3 does not pass the line about BR-3", not passes("R-3", "no oracle for BR-3 in the plan"))
    check("K2 `*` passes everything, as today (FR-4)", passes("*", "any line at all"))
    check("K2 a REVOKED `*` passes nothing", not passes("*", "any line at all", revoked_at="2026-10-02T00:00:00+00:00"))
    check("K2 a revoked word passes nothing", not passes("R-3", "R-3", revoked_at="2026-10-02T00:00:00+00:00"))
    check("K2 a placeholder block on disk passes nothing", not passes("probe gap: <instance or case>",
                                                                      "x probe gap: <instance or case> y"))
    check("K2 RP-<profile> on disk passes nothing", not passes("RP-<profile>", "RP-<profile> is open"))
    check("K2 a blank decision passes nothing", not passes("R-3", "R-3", decision="  "))
    check("K2 a blank match passes nothing", not passes("  ", "R-3"))
    check("K2 another stage's word passes nothing", not W.split_overridden(["R-3"], pipe(ov("S4", "R-3")), "S5")[1])
    check_eq("K2 blocking and passed are split per line",
             W.split_overridden(["R-3 a", "BR-3 b"], pipe(ov("S5", "R-3")), "S5")[0], ["BR-3 b"])
    check_eq("K2 a pipeline that is no object blocks everything",
             W.split_overridden(["R-3"], None, "S5"), (["R-3"], []))
    check("K2 the list line is passed whole, as today (not a regression)", passes("R-3", "R-3, R-4 have no oracle"))
    check("K2 a word about one test does not pass its variant", not passes("tests/a.py::test_x", "tests/a.py::test_x[1] fails"))
    check("K2 a word about R-1 does not pass R-1/R-3 (asks again)", not passes("R-1", "R-1/R-3 is open"))


def k3_live_overrides() -> None:
    live, dead = ov(match="a"), ov(match="b", revoked_at="2026-10-02T00:00:00+00:00")
    blank, other = ov(match="c", decision=" "), ov("S4", match="d")
    p = pipe(live, dead, blank, other, "junk", None)
    check_eq("K3 live = no revoked_at, non-empty decision, file order", C.live_stage_overrides(p), [live, other])
    check_eq("K3 stages narrows (a tuple)", C.live_stage_overrides(p, ("S4",)), [other])
    check_eq("K3 stages narrows (a bare name)", C.live_stage_overrides(p, "S5"), [live])
    for name, bad in (("no object", None), ("a list", []), ("no stage_overrides", {}), ("not a list", {"stage_overrides": "x"}),
                      ("empty", {"stage_overrides": []})):
        check_eq(f"K3 AR-28: a pipeline that is {name} gives []", C.live_stage_overrides(bad), [])
        check_eq(f"K3 AR-28: stage_override_values over {name} gives []", C.stage_override_values(bad, "probe gap:"), [])
    p2 = pipe(ov(match="probe gap: T1"), ov(match="probe gap: T2", revoked_at="2026-10-02T00:00:00+00:00"))
    check_eq("K3 stage_override_values keeps the live record only",
             [v for v, _ in C.stage_override_values(p2, "probe gap:")], ["T1"])


def k4_stand_gap_answers() -> None:
    gap = "stand gap: PC-1"
    s5 = ov("S5", gap, "accept - the person wrote: one", at="2026-10-01T01:00:00+00:00")
    s9 = ov("S9", gap, "theirs - the person wrote: two", at="2026-10-01T03:00:00+00:00")
    revoked = lambda e, when: dict(e, revoked_at=when)  # noqa: E731
    got = C.stand_gap_decisions(pipe(s5, revoked(s9, "2026-10-01T04:00:00+00:00")))
    check_eq("K4 S5 accept t1, S9 theirs t3, S9 revoked: NO answer, the person is asked", got, {})
    got = C.stand_gap_decisions(pipe(revoked(s5, "2026-10-01T04:00:00+00:00"), s9))
    check_eq("K4 S5 accept t1 revoked at t4, S9 theirs t3 live: theirs acts", got["PC-1"]["option"], "theirs")
    t5 = ov("S5", gap, "apply - the person wrote: three", at="2026-10-01T05:00:00+00:00")
    got = C.stand_gap_decisions(pipe(s5, revoked(s9, "2026-10-01T04:00:00+00:00"), t5))
    check_eq("K4 a new answer after the revoke acts (FR-40)", got["PC-1"]["option"], "apply")
    check_eq("K4 every record of a gap revoked: no gap",
             C.stand_gap_decisions(pipe(revoked(s5, "x"), revoked(s9, "y"))), {})
    check_eq("K4 an empty or unreadable `at` is the oldest moment",
             C.stand_gap_decisions(pipe(dict(s9, at=""), dict(s5, at="not a date")))["PC-1"]["option"], "accept")
    check_eq("K4 AR-28: no object / no list give {}", (C.stand_gap_decisions(None), C.stand_gap_decisions({"stage_overrides": 3})), ({}, {}))
    other = ov("S5", "stand gap: PC-2", "accept - the person wrote: z", at="2026-10-01T01:30:00+00:00")
    got = C.stand_gap_decisions(pipe(s5, other, revoked(s9, "2026-10-01T04:00:00+00:00")))
    check_eq("K4 a revoke of one gap id does not touch another", sorted(got), ["PC-2"])
    entries = C.stand_gap_live_entries(pipe(s9, s5))
    check_eq("K4 stand_gap_live_entries is in (moment, position) order", [e["stage"] for e in entries], ["S5", "S9"])
    check_eq("K4 and carries the record shape", sorted(entries[0]), ["at", "entry", "key", "moment", "pos", "stage"])
    import stand_gaps as SG
    check_eq("K4 stand_gaps._live_records reads the contract's list (file order)",
             [r["stage"] for r in SG._live_records(pipe(s9, s5))], ["S9", "S5"])
    check_eq("K4 and shows nothing across the revoke",
             SG._live_records(pipe(s5, revoked(s9, "2026-10-01T04:00:00+00:00"))), [])


def k5_readers_skip_a_revoked_word() -> None:
    gone = "2026-10-02T00:00:00+00:00"
    import story_budget
    check_eq("K5 story_budget.override: a live budget word", bool(story_budget.override(pipe(ov(match="story budget")))), True)
    check_eq("K5 story_budget.override: revoked, no word", story_budget.override(pipe(ov(match="story budget", revoked_at=gone))), None)
    check_eq("K5 story_budget.override: a revoked `*` is no word", story_budget.override(pipe(ov(match="*", revoked_at=gone))), None)

    import report_facts as RF
    live = pipe(ov("S8", "TC-7", "keep TC-7 local"))
    dead = pipe(ov("S8", "TC-7", "keep TC-7 local", revoked_at=gone))
    check_eq("K5 report_facts._person_line: live", RF._person_line(live, "TC-7") != "", True)
    check_eq("K5 report_facts._person_line: revoked", RF._person_line(dict(dead, gates={}), "TC-7"), "")
    check_eq("K5 report_facts._overrides: live", len(RF._overrides(live, ("S8", "S9"))), 1)
    check_eq("K5 report_facts._overrides: revoked", RF._overrides(dead, ("S8", "S9")), [])
    check_eq("K5 report_facts._gate_b_sources: live", RF._gate_b_sources(live), ["keep TC-7 local"])
    check_eq("K5 report_facts._gate_b_sources: revoked", RF._gate_b_sources(dead), [])

    import traceability as T
    import validate_artifacts as V
    check_eq("K5 traceability.decided_at_gate_b: live shows the word", "keep TC-7 local" in T.decided_at_gate_b(live), True)
    check_eq("K5 traceability.decided_at_gate_b: revoked is not shown", T.decided_at_gate_b(dead), "")
    check_eq("K5 validate_artifacts.gate_b_has_words: live", V.gate_b_has_words(live), True)
    check_eq("K5 validate_artifacts.gate_b_has_words: revoked", V.gate_b_has_words(dead), False)
    check_eq("K5 traceability.decided_cases: revoked decides nothing", T.decided_cases(dead), {})

    import gate_brief as GB
    check_eq("K5 gate_brief._recorded_words: live", [k for k, _t in GB._recorded_words(live)], [GB.OVERRIDE_WORDS])
    check_eq("K5 gate_brief._recorded_words: revoked", GB._recorded_words(dead), [])

    import brief_pack as BP
    shown, _minimal, full = BP.decisions(live, "S8", "qa-doc-scribe")
    check_eq("K5 brief_pack.decisions: live word is handed on", any("keep TC-7 local" in line for line in full), True)
    shown, _minimal, full = BP.decisions(dead, "S8", "qa-doc-scribe")
    check_eq("K5 brief_pack.decisions: a revoked word is not handed on as standing", any("keep TC-7 local" in line for line in full), False)

    import retro_numbers as RN
    check_eq("K5 retro_numbers.gate_answers: live has no mark", [l for l in RN.gate_answers(live) if "keep TC-7" in l][0].endswith(W.WITHDRAWN), False)
    check_eq("K5 retro_numbers.gate_answers: revoked stays as history and says (withdrawn)",
             [l for l in RN.gate_answers(dead) if "keep TC-7" in l][0].endswith(W.WITHDRAWN), True)

    import s5_precheck as S5P
    broad = pipe(ov("S5", S5P.CHANGED_AFTER_RED, at="2026-10-01T10:00:00+00:00"))
    _p, left = S5P._words_for_pair(broad, "2026-10-01T11:00:00+00:00")
    check_eq("K5 s5_precheck._words_for_pair: a live broad word given before the pair is left out", len(left), 1)
    broad_dead = pipe(ov("S5", S5P.CHANGED_AFTER_RED, at="2026-10-01T10:00:00+00:00", revoked_at=gone))
    kept, left = S5P._words_for_pair(broad_dead, "2026-10-01T11:00:00+00:00")
    check_eq("K5 s5_precheck._words_for_pair: a revoked broad word is not `left out`, and stays in kept",
             (left, len(kept["stage_overrides"])), ([], 1))

    import bug_records as BR
    local = pipe(ov("S8", "keep it local", "keep it local, I will file it by hand"))
    local_dead = pipe(ov("S8", "keep it local", "keep it local, I will file it by hand", revoked_at=gone))
    root = Path(harness.tempfile.mkdtemp(prefix="gw1-1-"))
    try:
        for name, pl, want in (("live", local, True), ("revoked", local_dead, False)):
            (root / "pipeline.json").write_text(json.dumps(pl), encoding="utf-8")
            check_eq(f"K5 bug_records._kept_local_by_word: {name}", BR._kept_local_by_word(root), want)
    finally:
        cleanup(root)

    project = temp_project()
    try:
        use_project(project)
        import external_writes as EW
        from hooklib import artifacts_dir
        for name, pl, want in (("live", local, True), ("revoked", local_dead, False)):
            folder = artifacts_dir("T-1")
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "pipeline.json").write_text(json.dumps(pl), encoding="utf-8")
            check_eq(f"K5 external_writes.local_only_decision: {name}", bool(EW.local_only_decision("T-1")), want)
    finally:
        cleanup(project)


def k6_the_placeholder_is_refused() -> None:
    for block in ("probe gap: <instance or case>", "RP-<profile>", "x <case> y"):
        got = W.record_refusals(block)
        check_eq(f"K6 {block!r} is refused with one text", len(got), 1)
        check(f"K6 {block!r}: says what is wrong, what is expected, and that nothing was recorded",
              bool(got) and "placeholder" in got[0] and "Expected" in got[0] and got[0].endswith("Nothing was recorded."))
        check(f"K6 {block!r}: names a door that is a real flag", bool(got) and "--remark" in got[0] and "--words-file" in got[0])
    check_eq("K6 `*` keeps its own branch (not refused)", W.record_refusals("*"), [])
    check_eq("K6 a real value is not refused", W.record_refusals("probe gap: TC_003"), [])
    generic = W.record_refusals("expected Array<string> got number")    # G-4: a real `<...>` of the refusal's own text
    check("K6/G-4 an angle-bracket line is refused with the way out: a part of the line without it",
          len(generic) == 1 and "If the <...> is the refusal's own text, give a part of the line without it." in generic[0])
    check_eq("K6 `stand gap: <id>` keeps the stand-gap branch, as today", W.record_refusals("stand gap: <id>"), [])
    check_eq("K6 `stand gap:` with no id keeps its own text", W.record_refusals("stand gap:"), [W.NO_GAP_ID])
    check("K6 the refused text does not itself promise a substring (unmatched_text says whole words)",
          "by a part only" not in __import__("inspect").getsource(W.unmatched_text))


def k7_dispatch_and_recheck() -> None:
    held = {"S5-qa-automator-1": {}, "S5-qa-automator-10": {}}
    was = W._dispatches
    W._dispatches = lambda task: held
    try:
        check_eq("K7 _dispatch_for: `-1` is not inside `-10`", W._dispatch_for("T", "S5-qa-automator-10 is dead"), "S5-qa-automator-10")
        check_eq("K7 _dispatch_for: the short id is named whole", W._dispatch_for("T", "S5-qa-automator-1 is dead"), "S5-qa-automator-1")
        check_eq("K7 _dispatch_for: two named is none (the controller asks)",
                 W._dispatch_for("T", "S5-qa-automator-1 and S5-qa-automator-10"), "")
    finally:
        W._dispatches = was
    was = W._guard_after_record
    W._guard_after_record = lambda task, stage: (["BR-3 has no oracle"], "")
    try:
        check("K7 recheck_stage_block: R-3 over a standing line about BR-3 is no false alarm",
              not W.recheck_stage_block("T", "S5", "R-3").startswith("block NOT lifted"))
        check("K7 recheck_stage_block: BR-3 over its own line is NOT lifted",
              W.recheck_stage_block("T", "S5", "BR-3").startswith("block NOT lifted"))
        check("K7 recheck_stage_block: `*` still reads every line",
              W.recheck_stage_block("T", "S5", "*").startswith("block NOT lifted"))
    finally:
        W._guard_after_record = was


def k8_the_door_passes_its_own_check() -> None:
    import gate_brief as GB
    import gate_preflight as GP
    message = "the matching profile has not been confirmed for this stand so the tests cannot be run there"
    check("K8 the premise: the message is over 60 characters and is cut inside a word at 60",
          len(message) > 60 and message[59].isalpha() and message[60].isalpha())
    block = GB._words_block(message, "S5", "x-1")
    check("K8 _words_block steps back to a space instead of cutting the word", bool(block) and message.startswith(block)
          and len(block) <= GB.OPEN_ITEM_BLOCK_LIMIT and message[len(block)] == " ")
    probe = pipe(ov("S5", block))
    check("K8 and the block passes the item through matched_text", bool(W.split_overridden([GP.matched_text(message, [])], probe, "S5")[1]))
    item = GB._open_item({"id": "x-1", "check": "x", "message": message, "fix": ""}, "S5")
    check_eq("K8 the item gets a `words` door (not `none`)", item["door"]["kind"], "words")
    long_word = "u" * 80
    check_eq("K8 a message of one word over 60 characters: no door, only `approve as is` (as today)",
             GB._words_block(long_word, "S5", "x-1"), "")
    check_eq("K8 a message that fits whole is offered whole", GB._words_block("short message", "S5", "x-1"), "short message")
    # Rehearsal.door cuts at 60 inside the word; the block is appended to matched_text WHOLE, so the finding is dropped.
    cut = " ".join(message.split())[:60]
    doors = [{"block": cut, "stage": "S5", "option": "accept"}]
    check("K8 a Rehearsal door cut inside a word passes through matched_text",
          bool(W.split_overridden([GP.matched_text(message, doors)], pipe(ov("S5", cut)), "S5")[1]))


def k9_requirement_ids_stand_alone() -> None:
    check_eq("K9 R-1 is read", C.REQ_ID_RE.findall("R-1"), ["R-1"])
    check_eq("K9 BR-1 is no requirement", C.REQ_ID_RE.findall("BR-1"), [])
    check_eq("K9 X-R-1 is no requirement", C.REQ_ID_RE.findall("X-R-1"), [])
    check_eq("K9 FR-21 and AR-13 are no requirements", C.REQ_ID_RE.findall("FR-21 AR-13"), [])
    check_eq("K9 a list and a comma are read", C.REQ_ID_RE.findall("covers: R-1, R-12;R-3."), ["R-1", "R-12", "R-3"])
    check_eq("K9 the right edge is untouched (R-12 is read whole, R-1.2 reads R-1)", C.REQ_ID_RE.findall("R-12 R-1.2"), ["R-12", "R-1"])
    check("K9 fullmatch readers are unchanged", bool(C.REQ_ID_RE.fullmatch("R-7")) and not C.REQ_ID_RE.fullmatch("BR-7"))
    # G-1 (t-565): in dumped JSON a newline or tab is the two characters of its escape; the id after it is still whole
    import traceability as T
    for label, value, wanted in (("a newline between two ids", {"violates": "R-1\nR-2"}, ["R-1", "R-2"]),
                                 ("a newline before an id in prose", {"actual": "broken\nR-3 and more"}, ["R-3"]),
                                 ("a tab before an id", {"actual": "broken\tR-4"}, ["R-4"]),
                                 ("FR-21 stays no requirement", {"violates": "FR-21"}, [])):
        check_eq(f"K9/G-1 dumped draft: {label}", C.REQ_ID_RE.findall(T._dumped_for_ids(value)), wanted)


def k10_the_registry_row() -> None:
    import refusal_registry as RR
    row = next((e for e in RR.REGISTRY if e.get("id") == "WV-placeholder-block"), None)
    check("K10 A24 knows the placeholder refusal", row is not None)
    check("K10 the row names its guarantor, and waiver.py still carries it", bool(row) and row["guarantor"] in
          (harness.SCRIPTS / "waiver.py").read_text(encoding="utf-8"))
    check_eq("K10 and the row's override is not empty (it has a door)", bool(str((row or {}).get("override") or "").strip()), True)


def main() -> None:
    k1_the_predicate_table()
    k2_split_overridden()
    k3_live_overrides()
    k4_stand_gap_answers()
    k5_readers_skip_a_revoked_word()
    k6_the_placeholder_is_refused()
    k7_dispatch_and_recheck()
    k8_the_door_passes_its_own_check()
    k9_requirement_ids_stand_alone()
    k10_the_registry_row()
    finish("whole identifier and the revoked word")


if __name__ == "__main__":
    main()
