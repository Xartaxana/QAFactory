"""B-361 (D-0026): a stand-gap answer given at gate A reaches the gate B card under the case key.

TP1-15045: the person answered `TC-014: accept` at gate A; the answer lived under the precondition id, the gate B card
looked for the case key, asked the same question again (FR-7) and the delivery check read the case as undecided. The driver
now writes one more record when every gap of a case is accepted - `stand gap: <case>`, stage S5, a CARRIED record - and
`stand_gaps.gate_b_answers` (the card) and `stand_gaps.delivery_decisions` (the delivery check) read it with ONE set of
rules: it settles the case until something recorded since says the world it was given for moved (`carried_change`).

The error direction is toward asking: an unknown (a clock, a report, a block, a file that cannot be read) is a change. The
keys: AK3-AK10 and AK13 of docs/tasks/specs/t-462-b-361-gate-a-answer-to-gate-b.md (the driver's side, AK1/AK2/AK2b, is in
test_story_run_delivery_b.py: `a361_carry_at_gate_a`).
"""
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check_eq, check_in, check_not_in, cleanup,  # noqa: E402
                     finish, temp_dir, use_project)

sys.path.insert(0, str(SCRIPTS))

import check_delivery  # noqa: E402
import contract  # noqa: E402
import gate_brief  # noqa: E402
import stand_gaps  # noqa: E402

TASK = "T-361"
ANSWER = datetime.datetime(2026, 10, 3, 10, 0, 0, tzinfo=datetime.timezone.utc)
REMEDY = {"kind": "flag", "where": "app/config/customer-config.yaml:306-311", "change": "enabled: true", "restart": "the app"}
CASE = ("---\nid: TC-007\ntask: T-361\nplan_row: TS-1\ntitle: a sub-workflow node keeps its own state\n"
        'preconditions: [{"id": "PC-1", "kind": "feature_flag", "what": "sub-workflow states are enabled", "partitions": [],'
        ' "remedy": ' + json.dumps(REMEDY) + ', "check": {"http": {"path": "/v1/config", "status": 200, '
        '"json_path": "features.f1", "equals": true}}}]\n---\n\n## When\n1. call it\n\n## Then\n1. it holds.\n')
TEST = "tests/test_sub.py::test_node_state"
SHA40, SHA64 = "a" * 40, "b" * 64


def iso(delta: int = 0) -> str:
    """The answer's moment, moved by `delta` seconds, in the form `waiver.py` writes."""
    return (ANSWER + datetime.timedelta(seconds=delta)).isoformat(timespec="seconds")


def block_name(delta: int, tail: str = "A1") -> str:
    return (ANSWER + datetime.timedelta(seconds=delta)).strftime("%Y%m%dT%H%M%SZ-") + tail + ".json"


def story(second_area: bool = False) -> tuple:
    """(project root, task root): TC-007 with one precondition, a manifest whose `blocked_by_env` row is keyed by its area and
    whose one test links the case, and a pipeline that holds nothing yet. `second_area`: TC-007 in another area too."""
    root = temp_dir("qa-b361-")
    task_root = root / "qa-factory" / "artifacts" / TASK
    folders = ["workflows"] + (["other"] if second_area else [])
    for folder in folders:
        (task_root / "work" / "test-cases" / folder).mkdir(parents=True)
        (task_root / "work" / "test-cases" / folder / "TC-007.md").write_text(CASE, encoding="utf-8")
    (root / "qa-factory" / "config.json").write_text(json.dumps(
        {"schema_version": 1, "tests_root": "tests", "app_root": ".", "protected_app_paths": ["app"],
         "environments": [{"name": "localhost", "base_url": "http://stand.invalid:8080"}]}), encoding="utf-8")
    (task_root / "work" / "automation-manifest.json").write_text(json.dumps({
        "tests": [{"test": TEST, "instance_id": TEST, "case": "TC-007", "covers": ["TC-007"]}],
        "unresolved": [{"case": "workflows/TC-007", "reason": "blocked_by_env", "owner": "user",
                        "detail": "the flag is off", "remedy": REMEDY}]}), encoding="utf-8")
    (task_root / "pipeline.json").write_text(json.dumps({"ticket": TASK}), encoding="utf-8")
    use_project(root)
    return root, task_root


def put(task_root: Path, gap: str, decision: str, at: str = None, stage: str = "S5", **extra) -> None:
    """One stage override, as `waiver.py --stage ... --block "stand gap: <gap>"` leaves it (a record of the same stage and
    block replaces the earlier one, as `apply_stage_override` does)."""
    path = task_root / "pipeline.json"
    pipeline = json.loads(path.read_text(encoding="utf-8"))
    overrides = [o for o in pipeline.get("stage_overrides") or []
                 if not (o["stage"] == stage and o["match"] == f"stand gap: {gap}")]
    overrides.append(dict({"stage": stage, "match": f"stand gap: {gap}", "decision": decision, "at": iso(0) if at is None else at, "by": "human"}, **extra))
    pipeline["stage_overrides"] = overrides
    path.write_text(json.dumps(pipeline), encoding="utf-8")


def carry(task_root: Path, at: str = None, gap_too: bool = True) -> None:
    """What the driver writes for `TC-007: accept` at gate A: the gap's own record and the case-level one."""
    if gap_too:
        put(task_root, "PC-1", "accept - the person wrote: TC-007: accept", at)
    put(task_root, "TC-007", "accept - the person wrote: TC-007: accept", at, declared=["PC-1"])   # the driver's typed field


def red_run(task_root: Path, started: str = "", name_delta: int = 0, attempt: str = "A1") -> None:
    """A red run of TEST: the report row, and the block of its attempt (its clock: `attempt_started_at`, else the stamp in its name)."""
    (task_root / "work" / "run-report.json").write_text(json.dumps({"current_results": [
        {"instance_id": TEST, "test_id": TEST, "status": "failed", "reason": "the node lost its state", "attempt_id": attempt,
         "case": "TC-007"}]}), encoding="utf-8")
    folder = task_root / "work" / "run-blocks"
    folder.mkdir(parents=True, exist_ok=True)
    data = {"attempt_id": attempt}
    if started:
        data["attempt_started_at"] = started
    (folder / block_name(name_delta, attempt)).write_text(json.dumps(data), encoding="utf-8")


def confirm(task_root: Path, at: str, kind: str = "deployed", revision: str = SHA40, image: str = "absent", sha: str = SHA64,
            profile: str = "api") -> None:
    row = {"schema_version": 1, "at": at, "task": TASK, "environment_id": "localhost", "profile_id": profile, "kind": kind,
           "words": "the person confirmed", "recorded_by": "test"}
    if kind != "withdrawn":
        row.update(revision=revision, image=image, stand_definition_sha=sha)
    path = task_root / "state" / "stand-confirmations.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")


def answer_of(task_root: Path, gap: str = "workflows/TC-007") -> dict:
    return stand_gaps.gate_b_answers(task_root)[0].get(gap) or {}


def change_of(task_root: Path) -> str:
    return answer_of(task_root).get("change", "<no answer>")


def card_of(task_root: Path) -> str:
    return "\n".join(gate_brief.stand_gap_cards(task_root, "B")[0])


def human_broken(text: str) -> list:
    import human_text
    tail = "\n---\nAnswer: write your words to a file and run\n  python answer.py --task QA-1 --answer <file>\n"
    return [p["rule"] for p in human_text.problems(text + tail)]


def delivery(task_root: Path) -> tuple:
    """(the option the delivery check reads for TC-007, its facts)."""
    facts = check_delivery.gather(task_root)
    return check_delivery.env_option_of_case("TC-007", facts), facts


def test_ak3_a_settled_answer_is_shown_and_not_asked_again() -> None:
    root, task_root = story()
    try:
        carry(task_root)
        got = answer_of(task_root)
        check_eq("AK3: the gate B gap holds the gate A answer, settled", (got.get("option"), got.get("gate"), got.get("change")),
                 ("accept", "A", ""))
        card = card_of(task_root)
        check_in("AK3: the card shows it was answered at gate A", f"answered at gate A: accept ({iso(0)})", card)
        check_not_in("AK3: and asks nothing (no word list)", "To answer a stand gap", card)
        option, facts = delivery(task_root)
        check_eq("AK3: the delivery check reads `accept` for the case", option, "accept")
        records = check_delivery.completeness_records(task_root, facts)
        check_eq("AK3: and there is no env_undecided", [r for r in records if r["kind"] == "env_undecided"], [])
        # control: the same fixture with NO carry is asked, so the two keys above can fail
        carry_less_root, carry_less = story()
        try:
            check_not_in("AK3 control: without the carry the card asks", "answered at gate A", card_of(carry_less))
            check_eq("AK3 control: and the delivery check reads the case undecided", delivery(carry_less)[0], "")
        finally:
            cleanup(carry_less_root)
    finally:
        cleanup(root)


def test_ak4_every_change_reopens_the_card() -> None:
    cases = {}
    # C1: a test of the case ran red after the answer (the block carries its own clock)
    root, task_root = story()
    try:
        carry(task_root)
        red_run(task_root, started=iso(1))
        cases["C1"] = (change_of(task_root), card_of(task_root), delivery(task_root))
        check_in("AK4 C1: the words", "a test of this case ran after your answer and failed (ran red: the node lost its state)",
                 cases["C1"][0])
        check_in("AK4 C1: the card says what changed", "  since then: a test of this case ran after your answer and failed", cases["C1"][1])
        check_in("AK4 C1: and shows the word the person gave, now asked again", f"at gate A you answered: accept ({iso(0)})", cases["C1"][1])
        check_in("AK4 C1: with the word list again", "To answer a stand gap", cases["C1"][1])
        check_eq("AK4 C1: the delivery check reads the case undecided", cases["C1"][2][0], "")
        sentence = [r["text"] for r in check_delivery.completeness_records(task_root, cases["C1"][2][1]) if r["kind"] == "env_undecided"]
        check_eq("AK4 C1: one env_undecided sentence", len(sentence), 1)
        check_in("AK4 C1: it names the change", "your answer at gate A no longer covers it: a test of this case ran after your answer", sentence[0])
        check_eq("AK4 C1 (RD1-4 K6): the suffixed stand sentence stays the environment's", check_delivery.reason_record(sentence[0])["owner"],
                 "environment")
        # B-3: the head must not deny the answer the suffix says no longer covers it
        check_eq("AK4 C1 (RD1-4 B-3): the suffixed sentence never says both `no answer` and `your answer`",
                 ("no answer" in sentence[0] and "your answer" in sentence[0]), False)
        check_eq("AK4 C1 (RD1-4 B-3): and it keeps the family head and never says `could not run`",
                 (sentence[0].startswith("blocked on the stand: "), "could not run" in sentence[0]), (True, False))
    finally:
        cleanup(root)
    # C1u: the report cannot be read
    root, task_root = story()
    try:
        carry(task_root)
        (task_root / "work" / "run-report.json").write_text("[1, 2", encoding="utf-8")
        check_in("AK4 C1u (report): an unreadable report", "I could not read every test run made since your answer", change_of(task_root))
        check_eq("AK4 C1u (report): the delivery check reads undecided", delivery(task_root)[0], "")
        (task_root / "work" / "run-report.json").write_text("[]", encoding="utf-8")
        check_in("AK4 C1u (report): a report that is not an object", "I could not read every test run", change_of(task_root))
        (task_root / "work" / "run-report.json").write_text("{}", encoding="utf-8")
        check_eq("AK4 C1u control: an empty object is a readable report", change_of(task_root), "")
    finally:
        cleanup(root)
    # C1u: a block cannot be read (stamped at the answer)
    root, task_root = story()
    try:
        carry(task_root)
        folder = task_root / "work" / "run-blocks"
        folder.mkdir(parents=True)
        (folder / block_name(0, "broken")).write_text("{not json", encoding="utf-8")
        check_in("AK4 C1u (block): an unreadable block", "I could not read every test run", change_of(task_root))
    finally:
        cleanup(root)
    # C2: the build changed (the commit moved)
    root, task_root = story()
    try:
        carry(task_root)
        confirm(task_root, iso(-60))
        confirm(task_root, iso(60), revision="c" * 40)
        words = change_of(task_root)
        check_in("AK4 C2: the build changed, naming what moved and the date", "the build on the stand changed after your answer (the commit, 2026-10-03)", words)
        check_in("AK4 C2: shown on the card", "since then: the build on the stand changed", card_of(task_root))
        check_eq("AK4 C2: the delivery check reads undecided", delivery(task_root)[0], "")
    finally:
        cleanup(root)
    # C3: a later word about one of the case's gate A gaps
    root, task_root = story()
    try:
        carry(task_root)
        put(task_root, "PC-1", "apply - the person wrote: PC-1: change", iso(5))
        check_in("AK4 C3: a later `change`", "at gate A you later answered `change` for one of its stand gaps", change_of(task_root))
        put(task_root, "PC-1", "let me think about it", iso(5))
        check_in("AK4 C3: a later word of their own", "at gate A you later answered in your own words for one of its stand gaps", change_of(task_root))
        check_eq("AK4 C3: the delivery check reads undecided", delivery(task_root)[0], "")
    finally:
        cleanup(root)
    # the clock guard: an answer from the future, and one that cannot be read
    for label, at in (("a future `at`", "2999-01-01T00:00:00+00:00"), ("an unparseable `at`", "last tuesday"), ("an empty `at`", "")):
        root, task_root = story()
        try:
            put(task_root, "PC-1", "accept - the person wrote: TC-007: accept", iso(0))
            put(task_root, "TC-007", "accept - the person wrote: TC-007: accept", at=at)
            check_in(f"AK4 clock guard: {label}", "the time of your answer is not readable, so I ask again", change_of(task_root))
            check_in(f"AK4 clock guard: {label}: the card opens with since then", "since then: the time of your answer is not readable", card_of(task_root))
            check_eq(f"AK4 clock guard: {label}: the delivery check reads undecided", delivery(task_root)[0], "")
        finally:
            cleanup(root)


def test_ak5_time_boundaries() -> None:
    # the red run's clock, one second before / at / after the answer; and a run with no clock at all (the epoch)
    for label, started, name_delta, settled in (("1 s before the answer", iso(-1), -1, True), ("at the answer", iso(0), 0, False),
                                                ("1 s after the answer", iso(1), 1, False),
                                                ("no clock in the block or its name (the epoch)", "", None, False)):
        root, task_root = story()
        try:
            carry(task_root)
            if name_delta is None:
                red_run(task_root)
                (task_root / "work" / "run-blocks" / block_name(0, "A1")).rename(task_root / "work" / "run-blocks" / "noclock.json")
            else:
                red_run(task_root, started=started, name_delta=name_delta)
            change = change_of(task_root)
            check_eq(f"AK5: a red run {label}: " + ("settled" if settled else "changed"), change == "", settled)
            check_eq(f"AK5: {label}: the delivery check agrees", delivery(task_root)[0] == "accept", settled)
        finally:
            cleanup(root)
    # the clock is the block's `attempt_started_at` - a run whose NAME is old but whose `attempt_started_at` is after the answer is after
    root, task_root = story()
    try:
        carry(task_root)
        red_run(task_root, started=iso(30), name_delta=-3600)
        check_in("AK5: the block's own clock decides, not the stamp in its name", "ran after your answer", change_of(task_root))
    finally:
        cleanup(root)
    # a red row whose attempt has no block at all counts as after (an unknown never settles)
    root, task_root = story()
    try:
        carry(task_root)
        red_run(task_root, started=iso(-100), name_delta=-100, attempt="A1")
        report = json.loads((task_root / "work" / "run-report.json").read_text(encoding="utf-8"))
        report["current_results"][0]["attempt_id"] = "A9"
        (task_root / "work" / "run-report.json").write_text(json.dumps(report), encoding="utf-8")
        check_in("AK5: a red row with no block behind its attempt counts as after", "ran after your answer", change_of(task_root))
    finally:
        cleanup(root)
    # a green story: no red row, nothing to read
    root, task_root = story()
    try:
        carry(task_root)
        (task_root / "work" / "run-report.json").write_text(json.dumps({"current_results": [
            {"instance_id": TEST, "test_id": TEST, "status": "passed", "attempt_id": "A1"}]}), encoding="utf-8")
        check_eq("AK5 control: a passed run is not a change", change_of(task_root), "")
    finally:
        cleanup(root)


def test_ak5b_an_unreadable_block_is_judged_by_its_stamp() -> None:
    for label, name_delta, settled in (("stamped 1 s before the answer", -1, True), ("stamped at the answer", 0, False),
                                       ("stamped 1 s after the answer", 1, False), ("with no stamp", None, False)):
        root, task_root = story()
        try:
            carry(task_root)
            folder = task_root / "work" / "run-blocks"
            folder.mkdir(parents=True)
            name = "broken.json" if name_delta is None else block_name(name_delta, "broken")
            (folder / name).write_text("{not json", encoding="utf-8")
            check_eq(f"AK5b: an unreadable block {label}: " + ("settled" if settled else "changed"), change_of(task_root) == "", settled)
        finally:
            cleanup(root)


def test_ak5c_the_build_changed() -> None:
    root, task_root = story()
    try:
        carry(task_root)
        confirm(task_root, iso(60))
        check_eq("AK5c: a FIRST row of a key after the answer is not a change", change_of(task_root), "")
        # F2 (critic t-537, probe P5): with no row of the key before the answer, its FIRST row after it is the baseline
        confirm(task_root, iso(120), revision="c" * 40)
        check_in("AK5c F2: a first row after the answer, then another revision, fires", "(the commit, 2026-10-03)", change_of(task_root))
    finally:
        cleanup(root)
    root, task_root = story()
    try:
        carry(task_root)
        confirm(task_root, iso(-60))
        confirm(task_root, iso(120), revision="c" * 40)
        check_in("AK5c: the same key with another revision than before the answer is", "(the commit, 2026-10-03)", change_of(task_root))
    finally:
        cleanup(root)
    for field, kwargs, words in (("the image", {"image": "image:sha256:" + "d" * 64}, "the image"),
                                 ("the stand's definition", {"sha": "e" * 64}, "the stand's address")):
        root, task_root = story()
        try:
            carry(task_root)
            confirm(task_root, iso(-60))
            confirm(task_root, iso(60), **kwargs)
            check_in(f"AK5c: {field} moved", f"({words}, 2026-10-03)", change_of(task_root))
        finally:
            cleanup(root)
    root, task_root = story()
    try:
        carry(task_root)
        confirm(task_root, iso(-60))
        confirm(task_root, iso(0))
        check_eq("AK5c: the same build confirmed again at the answer is not a change (equality counts only for the time)", change_of(task_root), "")
        confirm(task_root, iso(30), kind="withdrawn")
        check_in("AK5c: a withdrawn confirmation after the answer is", "(the confirmation was withdrawn, 2026-10-03)", change_of(task_root))
    finally:
        cleanup(root)
    # another key's row is another stand: a first row of ANOTHER profile after the answer is not a change either
    root, task_root = story()
    try:
        carry(task_root)
        confirm(task_root, iso(-60), profile="api")
        confirm(task_root, iso(60), profile="ui", revision="c" * 40)
        check_eq("AK5c: a row of ANOTHER key is compared with its own key only", change_of(task_root), "")
    finally:
        cleanup(root)
    # a file with a damaged line: asked (the unknown never settles); an absent file: no change
    root, task_root = story()
    try:
        carry(task_root)
        confirm(task_root, iso(-60))
        with (task_root / "state" / "stand-confirmations.jsonl").open("a", encoding="utf-8") as handle:
            handle.write("{broken\n")
        check_in("AK5c: a record that cannot be read", "I could not read every record of the build on the stand since your answer", change_of(task_root))
    finally:
        cleanup(root)


def test_ak6_a_later_gate_b_answer_is_the_answer() -> None:
    root, task_root = story()
    try:
        carry(task_root, at=iso(0))
        put(task_root, "workflows/TC-007", "handed - the person wrote: TC-007: run", iso(10), stage="S9")
        got = answer_of(task_root)
        check_eq("AK6: the later S9 answer is the gate B answer, with no change rules", (got.get("option"), got.get("gate"), got.get("change")),
                 ("handed", "B", ""))
        card = card_of(task_root)
        check_in("AK6: the card shows `answered:` with the word", "  answered: run (" + iso(10) + ")", card)
        check_not_in("AK6: and not the gate A line", "answered at gate A", card)
        # even a red run after the answers changes nothing about the person's own word at gate B
        red_run(task_root, started=iso(100))
        check_eq("AK6: a red run does not second-guess a gate B answer", answer_of(task_root).get("change"), "")
        check_eq("AK6: the delivery check reads `handed`", delivery(task_root)[0], "handed")
    finally:
        cleanup(root)


def test_ak7_area_keys() -> None:
    gaps = [{"id": "a/TC-007", "case_id": "TC-007"}, {"id": "b/TC-007", "case_id": "TC-007"}]
    root, task_root = story()
    try:
        carry(task_root)
        one, _ = stand_gaps.gate_b_answers(task_root, gaps[:1])
        check_eq("AK7: one gate B gap matches the bare id: the carried word is re-keyed onto it", (one.get("a/TC-007") or {}).get("option"), "accept")
        two, had = stand_gaps.gate_b_answers(task_root, gaps)
        check_eq("AK7: two gaps share the number: not re-keyed, both are asked", two, {})
        check_eq("AK7: ... and the story still says it holds a gate A word", had, True)
    finally:
        cleanup(root)
    # F1 (critic t-537, probe P1): two areas hold TC-007 - the card and the delivery check, on the SAME fixture, both refuse to
    # place a bare number they cannot name, and the delivery sentence names the ambiguity
    root, task_root = story(second_area=True)
    try:
        carry(task_root)
        card = card_of(task_root)
        check_not_in("AK7 F1: the card does not settle a bare id two areas share", "answered at gate A", card)
        check_in("AK7 F1: it asks", "To answer a stand gap", card)
        option, facts = delivery(task_root)
        check_eq("AK7 F1: the delivery check does not settle it either (card and check agree)", option, "")
        check_in("AK7 F1: and `changed` names the ambiguity", "matches more than one case: other/TC-007, workflows/TC-007; say which",
                 facts["changed"].get("TC-007", ""))
        sentence = [r["text"] for r in check_delivery.completeness_records(task_root, facts) if r["kind"] == "env_undecided"]
        check_in("AK7 F1: the completeness sentence says so (FR-20)", "matches more than one case: other/TC-007, workflows/TC-007; say which", " ".join(sentence))
    finally:
        cleanup(root)
    # F1 (probe P7): two gate B gaps, older gate B words on both, then a NEWER bare carry: the older words keep standing in the
    # delivery check as they do on the card
    root, task_root = story(second_area=True)
    try:
        manifest = json.loads((task_root / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
        manifest["unresolved"].append(dict(manifest["unresolved"][0], case="other/TC-007"))
        (task_root / "work" / "automation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        for key in ("workflows/TC-007", "other/TC-007"):
            put(task_root, key, "handed - the person wrote: TC-007: run", iso(-30), stage="S9")
        carry(task_root, at=iso(0))
        answers, _ = stand_gaps.gate_b_answers(task_root)
        check_eq("AK7 P7: the card keeps the older gate B words (the bare carry is not placed)",
                 {k: (v["option"], v["gate"]) for k, v in answers.items()}, {"workflows/TC-007": ("handed", "B"), "other/TC-007": ("handed", "B")})
        facts = check_delivery.gather(task_root)
        check_eq("AK7 P7: and the delivery check reads both as `handed`",
                 [check_delivery.env_option_of_case(k, facts) for k in ("workflows/TC-007", "other/TC-007")], ["handed", "handed"])
    finally:
        cleanup(root)


def test_ak8_had_gate_a_reads_the_raw_store() -> None:
    root, task_root = story()
    try:
        before = card_of(task_root)
        check_eq("AK8: a story with no S5 record renders exactly as the old renderer did",
                 before, "\n".join(gate_brief.stand_gap_card_lines(task_root, stand_gaps.collect(task_root, "B"), stand_gaps.decisions(task_root))))
        check_not_in("AK8: and never says it holds no answer", "I hold no answer from gate A", before)
        put(task_root, "PC-1", "accept - the person wrote: x", iso(0))
        put(task_root, "PC-1", "changed my mind", iso(5), revoked_at=iso(6))     # a revoked-only record: the raw store still holds it
        path = task_root / "pipeline.json"
        pipeline = json.loads(path.read_text(encoding="utf-8"))
        pipeline["stage_overrides"] = [o for o in pipeline["stage_overrides"] if o.get("revoked_at")]
        path.write_text(json.dumps(pipeline), encoding="utf-8")
        check_eq("AK8: had_gate_a counts a revoked-only S5 record", stand_gaps.gate_b_answers(task_root)[1], True)
        check_in("AK8: and the card says no gate A answer covers the case", "  I hold no answer from gate A that covers this case, so it is asked here.", card_of(task_root))
        check_in("AK8: the card still asks", "To answer a stand gap", card_of(task_root))
        # no pipeline, no overrides, no gaps: empty
        check_eq("AK8 edge 7: no overrides, no gaps", stand_gaps.gate_b_answers(task_root, [], {}), ({}, False))
        check_eq("AK8 edge 7: a pipeline that holds a list where a dict is wanted", stand_gaps.gate_b_answers(task_root, None, {"stage_overrides": "x"}), ({}, False))
    finally:
        cleanup(root)


def test_ak9_the_limit_of_the_one_line_form() -> None:
    gaps = [{"id": f"TC-{n:03d}", "case_id": f"TC-{n:03d}", "requirement": "R-1", "missing": "the stand lacks it", "remedy": {}} for n in range(1, 5)]
    for length, cut in ((120, False), (121, True)):
        change = "x" * length
        lines = gate_brief.stand_gap_card_lines(None, gaps, {"TC-004": {"option": "accept", "gate": "A", "at": iso(0), "change": change}})
        line = next(row for row in lines if row.startswith("- TC-004"))
        check_in(f"AK9: the prefix `asked again:` is never cut ({length} characters)", "(asked again: ", line)
        check_eq(f"AK9: a change of {length} characters is " + ("cut" if cut else "whole"), ("…" in line), cut)
        check_eq(f"AK9: and the line still ends with its parenthesis ({length})", line.endswith(")"), True)
    answered = gate_brief.stand_gap_card_lines(None, gaps, {"TC-004": {"option": "accept", "gate": "A", "at": iso(0), "change": ""}})
    check_in("AK9: a settled gate A answer beyond the limit reads `answered at gate A`", "(answered at gate A: accept)", "\n".join(answered))
    old = gate_brief.stand_gap_card_lines(None, gaps, {"TC-004": {"option": "accept", "at": iso(0)}})
    check_in("AK9: an answer with no `gate` reads exactly as before", "(answered: accept)", "\n".join(old))


# --- B-426 D6 (t-625): `stand_gap_card_lines` split into helpers, the text unchanged ---------------------------------------
# The golden below is a CHARACTERISATION: it was taken from the function as it stood BEFORE the split (the code is not an oracle for a
# requirement, FR-58 - it is the oracle for "nothing moved"). A change of the card's words on purpose changes this text on purpose.

D6_LEVEL_REMEDY = {"kind": "reporter", "where": "qa-factory/config.json:profiles[web].commands.one_test",
                   "where_words": "qa-factory/config.json, the command that runs one web test", "change": "name the flag",
                   "profile": "web", "offers": ["theirs", "handed", "accept"]}
D6_CASE_REMEDY = {"kind": "flag", "where": "app/config.yaml:3", "change": "enabled: true", "restart": "the app"}
D6_KEY_LEVEL = {"scope": "level", "contour": "web", "argv_digest": "a" * 64, "reason_class": "zero_tests"}
D6_KEY_CASE = {"scope": "case", "environment": "QA", "definition_sha": "b" * 64, "precondition_kind": "feature_flag", "check_digest": "c" * 64}


def d6_level(gid: str, contour: str, cases: list, **over) -> dict:
    return dict({"id": gid, "scope": "level", "contour": contour, "cases": cases, "case": "", "case_id": "",
                 "the_test": f"every {contour} test of this story", "missing": f"{contour} writes no report (with the command recorded now)",
                 "remedy": D6_LEVEL_REMEDY, "partitions": [], "requirement": "", "reason_class": "zero_tests", "property_key": None, "lasting": ""}, **over)


def d6_case(gid: str, case: str, **over) -> dict:
    return dict({"id": gid, "scope": "case", "case": case, "case_id": case, "the_test": "a node keeps its state",
                 "missing": "feature flag: on (on QA)", "remedy": D6_CASE_REMEDY, "partitions": [], "requirement": "R-3", "stand": "QA",
                 "property_key": None, "lasting": "no_key"}, **over)


def d6_fixture() -> tuple:
    """(gaps, decided, covered): 4 cards in full and 3 one-line gaps past the limit of 4, a gap the environment record covers; the
    words of a reporter card with `offers` and `accept always`, a level answered for only some of its cases, a gate A answer that is
    asked again, one that stands, an answer in the person's own words, `understood` that may be printed and one that may not."""
    gaps = [
        d6_level("RP-web", "web", ["TC-001", "TC-002"], property_key=D6_KEY_LEVEL, lasting="",
                 ran_red="the web test ran and failed: the node lost its state", changed_since="the stand moved since your word",
                 understood="The report holds three suites and none of them was run."),
        d6_case("PC-1", "TC-007", property_key=D6_KEY_CASE, lasting="", understood="run waiver.py --stage S5 now"),
        d6_level("RP-api", "api", ["TC-003", "TC-004"], lasting="fault", reason_class="no_file"),
        d6_case("PC-4", "TC-010"),
        d6_case("PC-5", "TC-011"),
        d6_case("PC-6", "TC-012"),
        d6_case("PC-9", "TC-007"),
    ]
    decided = {
        "PC-1": {"option": "accept", "gate": "A", "at": iso(0), "change": "the commit moved (2026-10-04)"},
        "RP-api": {"option": "accept", "words": "accept", "at": iso(5)},
        "PC-4": {"option": "", "words": "look at it by hand later", "at": iso(6)},
        "PC-5": {"option": "accept", "gate": "A", "at": iso(0), "change": ""},
        "PC-6": {"option": "theirs", "gate": "A", "at": iso(0), "change": "the build changed"},
    }
    prop = {"id": "EP-1", "subject": D6_KEY_LEVEL, "words": "unit: accept always " + "and so on " * 20, "at": "2026-10-05T10:00:00+00:00", "about": "the unit tests"}
    return gaps, decided, [dict(d6_level("RP-unit", "unit", ["TC-020"]), property=prop), "not a gap"]


def d6_card(limit=4, covered=True) -> list:
    """The card of the fixture, with `level_applied` answering for ONE of the level's two cases (the answer from before the level took every case)."""
    gaps, decided, covered_gaps = d6_fixture()
    real = stand_gaps.level_applied
    stand_gaps.level_applied = lambda task_root, gap: ["TC-003"]
    root = temp_dir("qa-d6-")
    try:
        return gate_brief.stand_gap_card_lines(root, gaps, decided, limit=limit, had_gate_a=True, covered=covered_gaps if covered else None)
    finally:
        stand_gaps.level_applied = real
        cleanup(root)


D6_GOLDEN = """\
## Stand gaps (7)

Stand gap: the web tests — a whole level: every web test of this story (2 cases: TC-001, TC-002)
  the test: every web test of this story
  missing:  web writes no report (with the command recorded now)
  your earlier answer for this environment does not apply now: the stand moved since your word
  the web test ran and failed: the node lost its state
  the factory's helper read it: The report holds three suites and none of them was run.
  the fix:  qa-factory/config.json, the command that runs one web test -> name the flag
  I hold no answer from gate A that covers this case, so it is asked here.

Stand gap: PC-1 (case TC-007) — needs R-3 — one case
  the test: a node keeps its state
  missing:  feature flag: on (on QA)
  the factory's helper read it: the factory's helper left a note it cannot print here (names only)
  the fix:  app/config.yaml:3 -> enabled: true; restart the app
  at gate A you answered: accept (2026-10-03T10:00:00+00:00)
  since then: the commit moved (2026-10-04)

Stand gap: the api tests — a whole level: every api test of this story (2 cases: TC-003, TC-004)
  the test: every api test of this story
  missing:  api writes no report (with the command recorded now)
  the fix:  qa-factory/config.json, the command that runs one web test -> name the flag
  the report was not written: a fault of this machine, not a property of the environment - fix it, or write `accept` to go on without it for this story
  answered: accept — applied to TC-003 only; the other 1 are asked (2026-10-03T10:00:05+00:00)

Stand gap: TC-010 — needs R-3 — one case
  the test: a node keeps its state
  missing:  feature flag: on (on QA)
  the fix:  app/config.yaml:3 -> enabled: true; restart the app
  answered: in your own words - look at it by hand later (2026-10-03T10:00:06+00:00)

- TC-011 — needs R-3: feature flag: on (on QA) (answered at gate A: accept)
- TC-012 — needs R-3: feature flag: on (on QA) (asked again: the build changed)
- PC-9 (case TC-007) — needs R-3: feature flag: on (on QA)

To answer a stand gap, write a line of its own: `<case id or level name>: <word>`, for example `web: accept`. The words:
- `change` — I make the change shown above, on your word (offered only for a gap whose card shows an exact change)
- `myself` — you make that change yourself
- `run` — you run this test yourself, where the missing piece exists
- `accept` — it stays blocked and is reported as not run
- `accept always` — the same as `accept` for this story, and the project's environment record keeps it, so no story asks it again until what it was recorded for changes or you take it back
On a card about a test command that writes no report, `accept` means the factory goes on without that report: the tests of that command cannot be read, so the report lists them as not run.
Is this how this command always is, or temporary? A word alone answers for this story; `accept always` records it in the project's environment record for this exact command, on every machine that uses this project, and no story asks it again until the command changes or you take it back.
Is this temporary, or how QA always is? A word alone answers for this story; `accept always` records it in the project's environment record for QA as it is configured now, and no story asks it again until the stand's address changes or you take it back.
Where a card is headed by something other than a case id (a case with several gaps), start the line with exactly what the card is headed by.
Anything else, in your own words, goes to the assistant running this story, who turns it into one of these or asks you back; only the forms above are read by code. That holds unless your answer starts with the word that approves this gate: then only the lines in the form above are read, so do not start the answer with that word if you want your own words read.

## Decided once for this environment (1)

- unit: on this environment the unit tests cannot be checked — you wrote on 2026-10-05: "unit: accept always and so on and so on and so on and so on and so on and so on and so on and so on and so on and so on and so on and so on and so on and so on…"

To have one asked again, write `<name>: ask again` on a line of its own."""


def test_d6_the_card_text_is_pinned_whole() -> None:
    text = "\n".join(d6_card())
    if text != D6_GOLDEN:
        print(text)
    check_eq("D6 golden: the whole card (past the limit, covered, `accept always`, reporter offers), line for line", text, D6_GOLDEN)
    gaps, decided, covered = d6_fixture()
    every = gate_brief.stand_gap_card_lines(None, gaps, decided, limit=None)
    check_eq("D6 edge: `limit=None` shows every card in full - seven cards, no one-line form",
             (sum(row.startswith("Stand gap: ") for row in every), [row for row in every if row.startswith("- TC-")]), (7, []))
    check_eq("D6 edge: no gap and nothing covered is no text; no gap and a covered one is the covered block only",
             (gate_brief.stand_gap_card_lines(None, [], {}), gate_brief.stand_gap_card_lines(None, [], {}, covered=covered)[:1]),
             ([], ["## Decided once for this environment (1)"]))


def test_d6_the_card_with_no_list_of_answers_says_so() -> None:
    real = gate_brief.stand_gap_words
    gate_brief.stand_gap_words = lambda lasting=False: []
    try:
        lines = gate_brief.stand_gap_card_lines(None, [d6_case("PC-1", "TC-007")])
    finally:
        gate_brief.stand_gap_words = real
    check_eq("D6: a data file with no answers: the card says the list could not be read, and lists no word",
             (lines[-1].startswith("The list of answers to a stand gap could not be read"), any(row.startswith("- `") for row in lines)), (True, False))


def understood_printed(text: str) -> str:
    """What the card prints after `the factory's helper read it: ` for a gap whose `understood` is `text`."""
    lead = "  the factory's helper read it: "
    lines = gate_brief.stand_gap_card_lines(None, [d6_case("PC-1", "TC-007", understood=text)])
    return next(row for row in lines if row.startswith(lead))[len(lead):]


def test_d6_understood_is_cut_at_the_display_limit_and_an_unknown_is_never_printed() -> None:
    import report_adapt
    limit = report_adapt.UNDERSTOOD_SHOWN
    check_eq("D6: the card's cut is a named constant, and its value stays 400", limit, 400)
    at = ("ab " * limit)[:limit - 1] + "a"                    # exactly `limit` characters, nothing a person could not be shown
    check_eq("D6 fixture control: the text is the limit long", len(at), limit)
    check_eq("D6 AT: an `understood` of exactly the limit is printed whole", understood_printed(at), at)
    check_eq("D6 BEYOND: one character more prints the first `limit`", understood_printed(at + "b"), at)
    cannot = "the factory's helper left a note it cannot print here (names only)"
    check_eq("D6: a text that may not be shown is not shown", understood_printed("run waiver.py --stage S5 now"), cannot)
    saved = sys.modules.get("report_adapt")
    sys.modules["report_adapt"] = None                          # `import report_adapt` now raises: the rule cannot be read
    try:
        check_eq("D6 / FR-59: when the rule that says what may be printed cannot be loaded, nothing is printed", understood_printed(at), cannot)
    finally:
        if saved is None:
            sys.modules.pop("report_adapt", None)
        else:
            sys.modules["report_adapt"] = saved


def test_ak10_the_card_is_human_text() -> None:
    root, task_root = story()
    try:
        carry(task_root)
        red_run(task_root, started=iso(1))
        for label, text in (("a settled card", None), ("a card asked again (red run)", "red")):
            if text is None:
                (task_root / "work" / "run-report.json").write_text("{}", encoding="utf-8")
            card = card_of(task_root)
            ours = "\n".join(line for line in card.splitlines() if not line.startswith("  the fix:"))
            check_eq(f"AK10: {label} obeys human-questions.md", human_broken("A packet whose body is long enough to stand on its own feet.\n\n" + ours), [])
            for banned in ("S5", "S9", "stand gap:", "waiver", "--"):
                check_not_in(f"AK10: {label} never shows {banned!r}", banned, ours)
        # control: the same checker is awake
        check_in("AK10 control: a planted script name is caught", "script_name",
                 human_broken("A packet whose body is long enough to stand on its own feet.\n\nrun waiver.py --stage S5\n"))
    finally:
        cleanup(root)


def test_ak13_a_later_gate_b_word_beats_the_carry() -> None:
    root, task_root = story()
    try:
        carry(task_root, at=iso(0))
        put(task_root, "workflows/TC-007", "accept - the person wrote: TC-007: accept", iso(0), stage="S9")
        put(task_root, "workflows/TC-007", "handed - the person wrote: TC-007: run", iso(0), stage="S9")
        # same second, the S9 record is LATER in stage_overrides[]: the contract's tie-break (N1)
        check_eq("AK13: the delivery check reads `handed` (the later record wins a tie in time)", delivery(task_root)[0], "handed")
        check_in("AK13: and the card shows `answered:` with the handed word", "answered: run", card_of(task_root))
        check_not_in("AK13: not the gate A line", "answered at gate A", card_of(task_root))
    finally:
        cleanup(root)
    # the other way round: a carry NEWER than the gate B word is the word in force (and older words stand down)
    root, task_root = story()
    try:
        put(task_root, "workflows/TC-007", "handed - the person wrote: TC-007: run", iso(-30), stage="S9")
        carry(task_root, at=iso(0))
        check_eq("AK13 N3: the newer carried `accept` is the word in force, the older `handed` stands down", delivery(task_root)[0], "accept")
        check_eq("AK13 N3: the card agrees (FR-10)", answer_of(task_root).get("option"), "accept")
        # and when the newer carried word is changed, the OLDER gate B word does not settle the case behind the person's back
        red_run(task_root, started=iso(5))
        check_eq("AK13 N3: a changed newest word leaves the case undecided in the delivery check", delivery(task_root)[0], "")
        check_in("AK13 N3: and the card asks again", "since then: a test of this case ran", card_of(task_root))
    finally:
        cleanup(root)
    # A2 by plain overwrite: a gate B word with an EARLIER time than the carry must not overwrite it, a LATER one must
    root, task_root = story()
    try:
        carry(task_root, at=iso(10))
        put(task_root, "workflows/TC-007", "handed - the person wrote: TC-007: run", iso(5), stage="S9")
        check_eq("AK13 A2: an older gate B word does not beat a newer carry", answer_of(task_root).get("option"), "accept")
        put(task_root, "workflows/TC-007", "handed - the person wrote: TC-007: run", iso(11), stage="S9")
        check_eq("AK13 A2: a newer one does", answer_of(task_root).get("option"), "handed")
    finally:
        cleanup(root)


def test_a_hand_written_case_key_record_is_not_settling() -> None:
    """Edge 13: a reader that used to be advice is now the delivery gate; its error direction is toward asking."""
    for word, label in (("apply - the person wrote: TC-007: change", "apply"), ("handed - the person wrote: TC-007: run", "theirs/handed"),
                        ("theirs - the person wrote: TC-007: myself", "theirs"), ("whatever you think", "own words")):
        root, task_root = story()
        try:
            put(task_root, "TC-007", word, iso(0))          # S5, a case key, written by hand
            check_eq(f"edge 13: a hand-written S5 case-key `{label}` record settles nothing (the card)", answer_of(task_root).get("change") != "", True)
            check_eq(f"edge 13: and the delivery check reads the case undecided ({label})", delivery(task_root)[0], "")
            check_in(f"edge 13: the card names the word ({label})", "since then: what you wrote at gate A", card_of(task_root))
        finally:
            cleanup(root)
    # a revoked record is absent
    root, task_root = story()
    try:
        carry(task_root)
        put(task_root, "TC-007", "accept - the person wrote: TC-007: accept", iso(0), revoked_at=iso(1))
        check_eq("edge 13: a revoked carry is no answer (the card)", answer_of(task_root), {})
        check_eq("edge 13: and no answer for the delivery check", delivery(task_root)[0], "")
        check_in("edge 13: the card says it holds no answer that covers the case (the story did hold gate A words)", "I hold no answer from gate A", card_of(task_root))
    finally:
        cleanup(root)


def test_n5_a_bare_revoke_of_a_gate_a_word_is_a_change() -> None:
    root, task_root = story()
    try:
        carry(task_root, at=iso(0))
        put(task_root, "PC-1", "accept - the person wrote: TC-007: accept", iso(0), revoked_at=iso(10))
        check_in("N5: a gate A word taken back after the carry", "at gate A you later took back your answer for one of its stand gaps", change_of(task_root))
        check_eq("N5: the delivery check reads undecided", delivery(task_root)[0], "")
    finally:
        cleanup(root)
    root, task_root = story()
    try:
        carry(task_root, at=iso(10))
        put(task_root, "PC-1", "accept - the person wrote: TC-007: accept", iso(0), revoked_at=iso(1))
        check_eq("N5 control: a word taken back BEFORE the carry is history", change_of(task_root), "")
    finally:
        cleanup(root)


def test_the_card_and_the_delivery_check_read_one_view() -> None:
    """FR-10: across every state the two readers agree whether the case is settled."""
    states = {
        "settled": lambda t: carry(t),
        "red": lambda t: (carry(t), red_run(t, started=iso(1))),
        "later gate A word": lambda t: (carry(t), put(t, "PC-1", "theirs - the person wrote: PC-1: myself", iso(2))),
        "gate B word later": lambda t: (carry(t), put(t, "workflows/TC-007", "handed - x", iso(3), stage="S9")),
        "gate B word earlier": lambda t: (put(t, "workflows/TC-007", "handed - x", iso(-3), stage="S9"), carry(t)),
        "no answer": lambda t: None,
    }
    for label, make in states.items():
        root, task_root = story()
        try:
            make(task_root)
            got = answer_of(task_root)
            card_settled = bool(got) and not got.get("change")
            check_eq(f"FR-10: {label}: the card and the delivery check agree on whether the case is settled",
                     (delivery(task_root)[0] != ""), card_settled)
            if card_settled:
                check_eq(f"FR-10: {label}: and on the word", delivery(task_root)[0], got.get("option"))
        finally:
            cleanup(root)


def test_the_view_that_cannot_be_built_is_never_a_pass() -> None:
    root, task_root = story()
    try:
        carry(task_root)
        original = stand_gaps.delivery_decisions
        stand_gaps.delivery_decisions = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            check_eq("R4: a view that raises drops every S5 record: the case is undecided, never a pass", delivery(task_root)[0], "")
        finally:
            stand_gaps.delivery_decisions = original
        check_eq("R4 control: the same story with the view working settles", delivery(task_root)[0], "accept")
        # carried_change never raises: a rule that cannot be evaluated is itself a change
        original = stand_gaps.declared_preconditions
        stand_gaps.declared_preconditions = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            check_eq("R3: a rule that raises is a change, not a pass - and the text carries no error name (F5, FR-6)",
                     change_of(task_root), "I could not check what happened to this case since your answer, so I ask again")
        finally:
            stand_gaps.declared_preconditions = original
    finally:
        cleanup(root)


def test_the_command_line_reads_the_view() -> None:
    import io
    import contextlib
    root, task_root = story()
    try:
        carry(task_root)
        sys.argv = ["stand_gaps.py", "--task-root", str(task_root), "--gate", "B"]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = stand_gaps.main()
        check_eq("R6: the command line exits 0", code, 0)
        check_in("R6: `--gate B` shows the gate A answer", "answered at gate A: accept", out.getvalue())
        sys.argv = ["stand_gaps.py", "--task-root", str(task_root), "--gate", "A"]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            stand_gaps.main()
        check_not_in("R6: gate A is unchanged", "answered at gate A", out.getvalue())
    finally:
        cleanup(root)


def test_the_story_without_a_gate_a_word_reads_as_before() -> None:
    root, task_root = story()
    try:
        put(task_root, "workflows/TC-007", "accept - the person wrote: TC-007: accept", iso(0), stage="S9")
        got = answer_of(task_root)
        check_eq("a plain gate B answer is read as before (gate B, no change)", (got.get("option"), got.get("gate"), got.get("change"), got.get("stage")),
                 ("accept", "B", "", "S9"))
        check_eq("and the delivery check reads it", delivery(task_root)[0], "accept")
        decided = stand_gaps.decisions(task_root)
        check_eq("and the old reader gives the same option", decided["workflows/TC-007"]["option"], got["option"])
        put(task_root, "PC-1", "accept - the person wrote: TC-007: accept", iso(0))
        check_eq("edge 7: no confirmations, no run blocks, no report: carried_change is empty for a fresh carry",
                 stand_gaps.carried_change(task_root, "TC-007", {"option": "accept", "at": iso(0)}), "")
        check_eq("edge 7: and it never raises over an answer that is no dict", isinstance(stand_gaps.carried_change(task_root, "TC-007", None), str), True)
    finally:
        cleanup(root)


def test_n6_a_level_gap_names_its_cases_for_the_carry_and_for_the_revoke() -> None:
    """N6: a LEVEL gap (no `case_id`, several `cases`) accepted at gate A is carried for EVERY case it names, and a later
    `myself` for it revokes every one of those carries - keyed by `case_id` alone the first writes nothing and the second
    revokes nothing, so gate B would settle on a word the person had replaced (a silent pass). Driven through the
    driver's own reader, with the level gap handed to it as the gate A collection."""
    import test_story_run_delivery_b as drv
    level = {"id": "web", "gate": "A", "stage": "S5", "case": "", "case_id": "", "cases": ["TC-007", "TC-008"], "requirement": "",
             "partitions": [], "the_test": "the web profile", "missing": "the stand has no web runner", "remedy": {},
             "reason": "precondition", "owner": "", "source": "rehearsal", "state": "open"}
    real_collect, real_cases = stand_gaps.collect, stand_gaps.gap_cases
    rehearsal = {"gate": "A", "findings": [], "stand_gaps": []}
    check_eq("N6: `gap_cases` of a level gap is its `cases`, of a case gap its `case_id`, of a gap with neither nothing",
             (stand_gaps.gap_cases(level), stand_gaps.gap_cases({"case_id": "TC-007"}), stand_gaps.gap_cases({"id": "x"})),
             (["TC-007", "TC-008"], ["TC-007"], []))
    for label, patched in (("gap_cases as written", None), ("MUTANT: gap_cases returns [case_id] only", lambda gap: [str(gap.get("case_id"))] if gap.get("case_id") else [])):
        root, task_root, env = drv.gate_a_story()
        try:
            stand_gaps.collect = lambda tr, gate="A", rehearsal=None, probe=True: [dict(level)] if gate == "A" else real_collect(tr, gate, rehearsal, probe)
            if patched:
                stand_gaps.gap_cases = patched
            drv.a364_take(root, env, task_root, "web: accept", rehearsal=rehearsal)
            carried = sorted(m for m in drv.a364_overrides(task_root) if m in ("stand gap: TC-007", "stand gap: TC-008"))
            if patched:
                check_eq(f"N6 control ({label}): a level accept carries nothing - the mutant is visible", carried, [])
                continue
            check_eq("N6: a level accept with two cases is carried for both", carried, ["stand gap: TC-007", "stand gap: TC-008"])
            check_in("N6: the carried word names the person's own line", "the person wrote: web: accept",
                     str(drv.a364_overrides(task_root)["stand gap: TC-007"].get("decision")))
            drv.a364_take(root, env, task_root, "web: myself", rehearsal=rehearsal)
            overrides = drv.a364_overrides(task_root)
            check_eq("N6: `web: myself` afterwards revokes BOTH carries",
                     [bool(overrides[f"stand gap: {c}"].get("revoked_at")) for c in ("TC-007", "TC-008")], [True, True])
            check_eq("N6: and the level gap's own record is the new word, live",
                     (overrides["stand gap: web"].get("revoked_at"), overrides["stand gap: web"]["decision"].split()[0]), (None, "theirs"))
            drv.a364_take(root, env, task_root, "web: accept", rehearsal=rehearsal)
            overrides = drv.a364_overrides(task_root)
            check_eq("N6: a later `web: accept` carries both again (the replacement has no `revoked_at`)",
                     [overrides[f"stand gap: {c}"].get("revoked_at") for c in ("TC-007", "TC-008")], [None, None])
        finally:
            stand_gaps.collect, stand_gaps.gap_cases = real_collect, real_cases
            drv.b272_cleanup(root)


def test_f3_the_change_moment_is_the_earliest_accept_of_the_case() -> None:
    """Critic t-537 F3 (probes P3, P4): R1 carries a case whose last gap was accepted in a LATER answer; what happened after the
    person's FIRST accept still counts. The carry's own `at` is only the fallback and the clock guard's."""
    # P3: PC-1 accepted at -100 s, the build moved at -50 s, the carry completed at 0 s
    root, task_root = story()
    try:
        put(task_root, "PC-1", "accept - the person wrote: PC-1: accept", iso(-100))
        put(task_root, "TC-007", "accept - the person wrote: TC-007: accept", iso(0))
        confirm(task_root, iso(-200))
        confirm(task_root, iso(-50), revision="c" * 40)
        check_in("F3 P3: a build change between the first accept and the carry fires", "(the commit, 2026-10-03)", change_of(task_root))
        check_eq("F3 P3: and the delivery check reads undecided", delivery(task_root)[0], "")
    finally:
        cleanup(root)
    # P4: a red run at -50 s, same pattern
    root, task_root = story()
    try:
        put(task_root, "PC-1", "accept - the person wrote: PC-1: accept", iso(-100))
        put(task_root, "TC-007", "accept - the person wrote: TC-007: accept", iso(0))
        red_run(task_root, started=iso(-50), name_delta=-50)
        check_in("F3 P4: a red run between the first accept and the carry fires", "ran after your answer", change_of(task_root))
    finally:
        cleanup(root)
    # control: the same red run BEFORE the first accept is history
    root, task_root = story()
    try:
        put(task_root, "PC-1", "accept - the person wrote: PC-1: accept", iso(-100))
        put(task_root, "TC-007", "accept - the person wrote: TC-007: accept", iso(0))
        red_run(task_root, started=iso(-150), name_delta=-150)
        check_eq("F3 control: a red run before the earliest accept is not a change", change_of(task_root), "")
    finally:
        cleanup(root)


def test_f6_a_stand_gap_added_after_the_carry_is_asked() -> None:
    """Critic t-537 F6 (probe P8), D-0026 "a new case": PC-4 added to the case after the carry and never answered."""
    root, task_root = story()
    try:
        carry(task_root)
        check_eq("F6 control: the carry settles before the case grows a gap", change_of(task_root), "")
        grown = CASE.replace('preconditions: [', 'preconditions: [{"id": "PC-4", "kind": "feature_flag", "what": "a later flag", "partitions": [], "remedy": '
                             + json.dumps(REMEDY) + ', "check": {"http": {"path": "/v1/config", "status": 200, "json_path": "features.f4", "equals": true}}}, ')
        for folder in (task_root / "work" / "test-cases").iterdir():
            (folder / "TC-007.md").write_text(grown, encoding="utf-8")
        check_in("F6 P8: the new gap reopens the card", "a new stand gap of this case appeared after your answer", change_of(task_root))
        check_in("F6 P8: and the card says so", "since then: a new stand gap of this case appeared after your answer", card_of(task_root))
        check_eq("F6 P8: and the delivery check reads undecided", delivery(task_root)[0], "")
        put(task_root, "PC-4", "theirs - the person wrote: PC-4: myself", iso(5))
        check_in("F6: an id answered otherwise is C3's too", "you later answered `myself`", change_of(task_root))
        check_in("F6: ... and it is still new (the carry did not know it)", "a new stand gap", change_of(task_root))
    finally:
        cleanup(root)
    # a carry written before the `declared` field existed (or whose field could not be stored): C5 is silent - no such carry
    # exists before the release that introduces the field
    root, task_root = story()
    try:
        put(task_root, "PC-1", "accept - the person wrote: TC-007: accept", iso(0))
        put(task_root, "TC-007", "accept - the person wrote: TC-007: accept", iso(0))      # no `declared`
        for folder in (task_root / "work" / "test-cases").iterdir():
            (folder / "TC-007.md").write_text(grown, encoding="utf-8")
        check_eq("F6: a pre-field carry (`declared` absent) never fires C5", change_of(task_root), "")
    finally:
        cleanup(root)
    # the counter-case: a precondition the stand MET at gate A (declared, no card, no accept) is not a new gap
    root, task_root = story()
    try:
        met = CASE.replace('preconditions: [', 'preconditions: [{"id": "PC-0", "kind": "feature_flag", "what": "already on", "partitions": [], "remedy": '
                           + json.dumps(REMEDY) + ', "check": {"http": {"path": "/v1/config", "status": 200, "json_path": "features.f0", "equals": true}}}, ')
        for folder in (task_root / "work" / "test-cases").iterdir():
            (folder / "TC-007.md").write_text(met, encoding="utf-8")
        put(task_root, "PC-1", "accept - the person wrote: TC-007: accept", iso(0))
        put(task_root, "TC-007", "accept - the person wrote: TC-007: accept", iso(0), declared=["PC-0", "PC-1"])
        check_eq("F6 counter-case: a declared-but-met id (in the carry's list, no accept) is not C5", change_of(task_root), "")
        check_eq("F6 counter-case: and the delivery check reads `accept`", delivery(task_root)[0], "accept")
    finally:
        cleanup(root)


# --- B-414 R7b / M3 (critic t-515 A3): ONE change rule for gate B and delivery, with the environment record's carries -----------

ENV = "environment-record"


def env_story() -> tuple:
    """(root, task root, the EP row): the story() fixture, the environment record holding TC-007's precondition for the stand `localhost`
    (a CASE key: the stand, its definition sha, the kind and the digest of the check), and the carry the driver writes from it."""
    import environment_record as ER
    root, task_root = story()
    config = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
    gap = {"scope": "case", "kind": "feature_flag", "what": "sub-workflow states are enabled",
           "check": {"http": {"path": "/v1/config", "status": 200, "json_path": "features.f1", "equals": True}}}
    ep, problem, _ = ER.record(root, ER.property_key(gap, config, "localhost"), "accept", "PC-1: accept always", "T-0", '"sub-workflow states are enabled"')
    assert ep is not None, problem
    return root, task_root, ep


def env_carry(task_root: Path, ep: dict, by: str = ENV) -> None:
    """The carry as `stand_gaps.write_carries` writes it from the record: `by` and the typed `property`."""
    prop = [{"id": ep["id"], "subject": ep["subject"]}]
    put(task_root, "PC-1", "accept - the person wrote: PC-1: accept always (recorded)", iso(0), by=by, property=prop)
    put(task_root, "TC-007", "accept - the person wrote: PC-1: accept always (recorded)", iso(0), by=by, declared=["PC-1"], property=prop)


def test_b414_c2_ignores_a_moved_commit_or_image_for_the_environment_record_only() -> None:
    root, task_root, ep = env_story()
    try:
        env_carry(task_root, ep)
        confirm(task_root, iso(-60))
        confirm(task_root, iso(60), revision="c" * 40, image="image:sha256:" + "d" * 64)
        check_eq("R7b: a redeploy (another commit and image) is NO change for an answer the record gave", change_of(task_root), "")
        check_eq("R7b: and the delivery check reads the same rule: `accept`", delivery(task_root)[0], "accept")
        confirm(task_root, iso(90), sha="e" * 64)
        check_in("R7b: but a re-pointed stand (another definition sha) still is - C2 fires for the record's carry", "(the stand's address, 2026-10-03)", change_of(task_root))
        check_eq("R7b: and delivery agrees", delivery(task_root)[0], "")
    finally:
        cleanup(root)
    root, task_root, ep = env_story()
    try:
        env_carry(task_root, ep)
        confirm(task_root, iso(-60))
        confirm(task_root, iso(60), kind="withdrawn")
        check_in("R7b: a withdrawn confirmation still fires C2 for the record's carry", "(the confirmation was withdrawn, 2026-10-03)", change_of(task_root))
    finally:
        cleanup(root)
    for by in ("driver", "human"):
        root, task_root, ep = env_story()
        try:
            env_carry(task_root, ep, by=by)
            confirm(task_root, iso(-60))
            confirm(task_root, iso(60), revision="c" * 40)
            check_in(f"R7b: for `by` = {by} a moved commit is a change, as before (the exemption is the record's alone)", "(the commit, 2026-10-03)", change_of(task_root))
        finally:
            cleanup(root)


def test_b414_only_names_the_rules_to_run() -> None:
    root, task_root, ep = env_story()
    try:
        carry(task_root)                                    # a person's carry
        confirm(task_root, iso(-60))
        confirm(task_root, iso(60), revision="c" * 40)
        red_run(task_root, started=iso(1))
        both = stand_gaps.carried_change(task_root, "TC-007", {"option": "accept", "words": "accept", "at": iso(0), "declared": ["PC-1"], "by": "human"})
        check_in("only=None: every rule (C1 and C2 here)", "ran after your answer and failed", both)
        check_in("only=None: C2 too", "the commit", both)
        answer = {"option": "accept", "words": "accept", "at": iso(0), "declared": ["PC-1"], "by": "human"}
        only_c2 = stand_gaps.carried_change(task_root, "TC-007", answer, only=("C2",))
        check_eq("only=(C2,): the build only", ("the commit" in only_c2, "ran after your answer" in only_c2), (True, False))
        only_c1 = stand_gaps.carried_change(task_root, "TC-007", answer, only=("C1", "C1u"))
        check_eq("only=(C1, C1u): the red run only", ("the commit" in only_c1, "ran after your answer" in only_c1), (False, True))
        check_eq("only=(): no rule runs, the clock guard and the word still do", stand_gaps.carried_change(task_root, "TC-007", answer, only=()), "")
        check_in("the clock guard runs whatever `only` says", "not readable", stand_gaps.carried_change(task_root, "TC-007", dict(answer, at=""), only=()))
        check_in("and so does `the word is an acceptance`", "is not an acceptance", stand_gaps.carried_change(task_root, "TC-007", dict(answer, option="apply"), only=()))
    finally:
        cleanup(root)


def test_b414_c4_the_recorded_property_must_still_hold() -> None:
    import environment_record as ER
    root, task_root, ep = env_story()
    try:
        env_carry(task_root, ep)
        check_eq("C4: the record's carry with a live row under the same key: nothing changed", change_of(task_root), "")
        for label, edit, words in (
                ("a row taken back", lambda: ER.revoke(root, ep["id"], "ask again"), "it was taken back"),):
            edit()
            check_in(f"C4: {label} reopens the case, in words", f"the recorded environment property no longer holds ({words})", change_of(task_root))
            check_eq("C4: and delivery reads the case undecided - one rule", delivery(task_root)[0], "")
    finally:
        cleanup(root)
    root, task_root, ep = env_story()
    try:
        env_carry(task_root, ep)
        config_path = root / "qa-factory" / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["environments"][0]["base_url"] = "http://elsewhere.invalid"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        check_in("C4 / E4: a stand re-pointed in the config is not the stand the record was given for",
                 "the recorded environment property no longer holds (the command or the stand it was recorded for has changed)", change_of(task_root))
    finally:
        cleanup(root)
    root, task_root, ep = env_story()
    try:
        env_carry(task_root, ep)
        ER.record_path(root).write_text("{broken", encoding="utf-8")
        check_in("C4 / E9: a record that cannot be read", "the recorded environment property no longer holds (the environment record cannot be read)", change_of(task_root))
    finally:
        cleanup(root)
    root, task_root, ep = env_story()
    try:
        put(task_root, "PC-1", "accept - x", iso(0), by=ENV)
        put(task_root, "TC-007", "accept - x", iso(0), by=ENV, declared=["PC-1"])      # `by` = the record, but no row named
        check_in("C4: a carry that says it is the record's and names no row cannot be checked: asked",
                 "the recorded environment property no longer holds (the answer names no record of it)", change_of(task_root))
    finally:
        cleanup(root)
    # a person's own carry has no such rule; one that ALSO rests on a row (mixed) is held to it
    root, task_root, ep = env_story()
    try:
        carry(task_root)
        check_eq("C4: a person's carry is not checked against the record", change_of(task_root), "")
        env_carry(task_root, ep, by="human")
        ER.revoke(root, ep["id"], "ask again")
        check_in("C4: a carry written by the person that rests on a row taken back is asked too (mixed carries)", "the recorded environment property no longer holds", change_of(task_root))
    finally:
        cleanup(root)


def test_t683_d9_the_card_context_is_one_object_that_still_unpacks() -> None:
    """t-683 D9: `_short_line` and `_card` take ONE context. It unpacks as the four values the renderer always took, its
    `word_of` is the dict `stand_gap_word_of` builds from `rows` (t-666 R2), and nothing can be assigned to it (E11)."""
    ctx = gate_brief._card_context(None, [], [])
    rows, word_of, forms, files = ctx
    check_eq("D9: the context is the named type", isinstance(ctx, gate_brief.CardCtx), True)
    check_eq("D9: unpacking and the names agree", (ctx.rows, ctx.word_of, ctx.forms, ctx.files), (rows, word_of, forms, files))
    check_eq("D9: `word_of` is what `stand_gap_word_of` builds from the rows", ctx.word_of, gate_brief.stand_gap_word_of(ctx.rows))
    check_eq("D9: no task root, no case files to link", ctx.files, {})
    try:
        ctx.word_of = {}
        refused = False
    except AttributeError:
        refused = True
    check_eq("D9: a field cannot be assigned", refused, True)


def test_t667_d16_level_remedies_by_accepted_case() -> None:
    """t-667 D16: the pure half of `Driver.carry_environment_properties` - the remedy each LEVEL gap carries, by ACCEPTED case.
    The first gap that names a case wins; a case gap, a level gap with an invalid remedy and a case that was not accepted give none;
    the remedy is copied, never shared, and the inputs are left as they were."""
    import copy
    import story_run
    second = dict(D6_LEVEL_REMEDY, change="a second command")
    first_gap = d6_level("level-1", "api", ["TC-1", "TC-2"])
    later_gap = d6_level("level-2", "ui", ["TC-2", "TC-3"], remedy=second)
    a_case_gap = d6_case("pc-1", "TC-4")
    invalid = d6_level("level-3", "e2e", ["TC-5"], remedy={"kind": "nonsense"})
    unaccepted = d6_level("level-4", "api", ["TC-6"])
    everything = [first_gap, later_gap, a_case_gap, invalid, unaccepted]
    before = copy.deepcopy(everything)
    got = story_run.Driver._level_remedies(everything, ["TC-1", "TC-2", "TC-3", "TC-4", "TC-5"])
    check_eq("D16: each accepted case of a level gap gets its remedy; the FIRST gap that names a case wins",
             got, {"TC-1": D6_LEVEL_REMEDY, "TC-2": D6_LEVEL_REMEDY, "TC-3": second})
    check_eq("D16: and the remedy is a copy of the gap's, not the gap's own dict", got.get("TC-1") is not first_gap["remedy"], True)
    check_eq("D16: the inputs are left as they were", everything, before)
    check_eq("D16: no accepted case, no remedy", story_run.Driver._level_remedies(everything, []), {})
    check_eq("D16: no gap, no remedy", story_run.Driver._level_remedies([], ["TC-1"]), {})


# --- GW1-15: a late word on an `INT-*` gap reopens a carried accept, a new `INT` gap is new for C5 -----------------------------
#
# The fixtures are the 12586 story of `test_gate_preflight_integrations.py` (imported, never copied): TC-001 on the api profile,
# an integration whose `required_by` is "api" - tied by EQUALITY, the only way an `INT-*` card is made since HF8-11 - and the
# gap `INT-jira-integration` the card asks. `INT` is the gap id; the case key carries the person's gate A answer to gate B.

import gate_preflight  # noqa: E402
import test_gate_preflight_integrations as INTS  # noqa: E402

INT = "INT-jira-integration"
TC1 = INTS.TC1
UNREAD_WORDS = "I could not read which stand integrations"
MYSELF = "theirs - the person wrote: INT-jira-integration: myself"


def int_story(prefix: str, rows=None, **kw) -> tuple:
    """(root, task root): TC-001 (plan row TS-10, api, automate) and the integration rows (default: one tied by `required_by`)."""
    root = INTS.story(prefix, integrations=rows if rows is not None else [INTS.integration(required_by=["api"])], one_case=True, **kw)
    use_project(root)
    return root, INTS.task_of(root)


def int_carry(task_root: Path, at: str = None, case: str = TC1, declared="now", gap_at: str = None) -> None:
    """What the driver writes for `<case>: accept` at gate A: the gap's own record and the case-level one with `declared`
    (`now`: the list `write_carries` stores - the preconditions and the `INT-*` of this moment; None: no field, as a carry
    written before it existed; a list: as given)."""
    if declared == "now":
        declared = stand_gaps.declared_ids(task_root, case, None, gate_preflight.integration_ids_of_case(task_root, case))
    put(task_root, INT, f"accept - the person wrote: {case}: accept", iso(0) if gap_at is None else gap_at)
    put(task_root, case, f"accept - the person wrote: {case}: accept", at, **({} if declared is None else {"declared": declared}))


def int_change(task_root: Path, case: str = TC1) -> str:
    """What gate B says changed since the answer: the card's own view (`gate_b_answers`) of the case."""
    return stand_gaps.gate_b_answers(task_root, gaps=[{"id": case, "case_id": case}])[0].get(case, {}).get("change", "<no answer>")


def int_ids(task_root: Path, case: str = TC1):
    return gate_preflight.integration_ids_of_case(task_root, case)


def edit_config(root: Path, change) -> None:
    INTS.T.cmp2_edit(root, change)


def test_gw1_15_k15_1_a_late_word_on_an_int_gap_reopens_the_carried_accept() -> None:
    """The t-062 experiment: accept `INT-jira-integration` and the carry -> gate B reads `accept`; a later
    `INT-jira-integration: theirs` used to leave it at `('accept', '')` (no reader of `INT-*` in `declared_ids`, C3, C5)."""
    root, task_root = int_story("qa-gw15-k1-")
    try:
        check_eq("K15.1: the case is tied to the one gap its card asks", int_ids(task_root), [INT])
        int_carry(task_root)
        check_eq("K15.1 control / K15.3: the carry settles the case, nothing changed since (not asked again)", int_change(task_root), "")
        check_eq("K15.1 control: and the delivery check reads `accept`", stand_gaps.delivery_decisions(
            task_root, json.loads((task_root / "pipeline.json").read_text(encoding="utf-8")))[1], {})
        put(task_root, INT, MYSELF, iso(5))
        change = int_change(task_root)
        check_in("K15.1: the later word on the INT gap reopens the carried accept", "you later answered `myself`", change)
        check_in("K15.1: the delivery check reads the case undecided", "you later answered `myself`", "; ".join(
            stand_gaps.delivery_decisions(task_root, json.loads((task_root / "pipeline.json").read_text(encoding="utf-8")))[1].values()))
    finally:
        cleanup(root)


def test_gw1_15_k15_2_a_new_int_gap_after_the_carry_is_new_for_c5() -> None:
    root, task_root = int_story("qa-gw15-k2-")
    try:
        int_carry(task_root)
        check_eq("K15.2 control: nothing new yet", int_change(task_root), "")
        # the project records a second integration the same story's cases run on, after the person's answer
        edit_config(root, lambda cfg: cfg["environment"]["integrations"].append(
            INTS.integration(name="aws-store", keys=["AWS_ONE"], required_by=["api"])))
        check_eq("K15.2: the case is now tied to both", int_ids(task_root), ["INT-aws-store", INT])
        check_in("K15.2: the gap the carry did not know is a new stand gap (C5)",
                 "a new stand gap of this case appeared after your answer", int_change(task_root))
        # a keyless or not-needed row is no gap: nothing new
        edit_config(root, lambda cfg: cfg["environment"]["integrations"].__setitem__(1, INTS.integration(name="aws-store", keys=[], required_by=["api"])))
        check_eq("K15.2: a row with no keys is no integration, so no new gap", int_change(task_root), "")
        edit_config(root, lambda cfg: cfg["environment"]["integrations"].__setitem__(
            1, INTS.integration(name="aws-store", keys=["AWS_ONE"], required_by=["api"], applicability="not_required")))
        check_eq("K15.2: a row marked not needed on this stand is no new gap", (int_ids(task_root), int_change(task_root)), ([INT], ""))
    finally:
        cleanup(root)


def int_red_run(task_root: Path, started: str, name_delta: int) -> None:
    """A red run of TC-001's test: the manifest that links it, the report row and the block of its attempt."""
    test = "tests/test_jira.py::test_search"
    (task_root / "work" / "automation-manifest.json").write_text(json.dumps(
        {"tests": [{"test": test, "instance_id": test, "case": TC1, "covers": [TC1]}], "unresolved": []}), encoding="utf-8")
    (task_root / "work" / "run-report.json").write_text(json.dumps({"current_results": [
        {"instance_id": test, "test_id": test, "status": "failed", "reason": "the search failed", "attempt_id": "A1", "case": TC1}]}), encoding="utf-8")
    folder = task_root / "work" / "run-blocks"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / block_name(name_delta, "A1")).write_text(json.dumps({"attempt_id": "A1", "attempt_started_at": started}), encoding="utf-8")


def test_gw1_15_k15_4_an_earlier_int_accept_moves_the_answer_to_the_earlier_moment() -> None:
    """F3 on an `INT` gap: the INT accept is in `accepts` now, so the person's word began to cover the case when IT was given."""
    root, task_root = int_story("qa-gw15-k4-")
    try:
        int_carry(task_root, at=iso(0), gap_at=iso(-100))
        int_red_run(task_root, started=iso(-50), name_delta=-50)
        check_in("K15.4: a red run between the earlier INT accept and the carry is after the answer",
                 "ran after your answer and failed", int_change(task_root))
    finally:
        cleanup(root)
    root, task_root = int_story("qa-gw15-k4c-")
    try:
        int_carry(task_root, at=iso(0), gap_at=iso(0))
        int_red_run(task_root, started=iso(-50), name_delta=-50)
        check_eq("K15.4 control: with the INT accept at the carry's moment the same run is before the answer", int_change(task_root), "")
    finally:
        cleanup(root)


def test_gw1_15_k15_5_what_cannot_be_read_is_asked_again() -> None:
    def plan(task_root, root):
        (task_root / "work" / "test-plan.json").write_text("{not json", encoding="utf-8")

    def config(task_root, root):
        (root / "qa-factory" / "config.json").write_text("null", encoding="utf-8")

    def case_line(task_root, root):
        path = next((task_root / "work" / "test-cases").rglob("*_TC_001.md"))
        path.write_text(path.read_text(encoding="utf-8").replace("task: TP1-15045\n", 'task: TP1-15045\npreconditions: [{"id": "PC-1", "kind": "toggle"}]\n'),
                        encoding="utf-8")
    for label, spoil in (("an unreadable plan", plan), ("a config that is there and says nothing (not [])", config),
                         ("an unreadable `preconditions` of the case", case_line)):
        root, task_root = int_story("qa-gw15-k5-")
        try:
            int_carry(task_root)
            check_eq(f"K15.5 control ({label}): readable, the carry settles", int_change(task_root), "")
            spoil(task_root, root)
            contract.case_config_reset()
            check_eq(f"K15.5: {label}: the function does not know", int_ids(task_root), None)
            check_in(f"K15.5: {label}: gate B asks again, in words", UNREAD_WORDS, int_change(task_root))
            pipeline = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))
            check_in(f"K15.5: {label}: the delivery check reads the case undecided with the same words", UNREAD_WORDS,
                     "; ".join(stand_gaps.delivery_decisions(task_root, pipeline)[1].values()))
            check_eq(f"K15.5: {label}: `only` can turn the rule off, and it is a rule of its own", (
                stand_gaps.carried_change(task_root, TC1, {"at": iso(0), "option": "accept", "declared": []}, pipeline, only=("C1",)),
                UNREAD_WORDS in stand_gaps.carried_change(task_root, TC1, {"at": iso(0), "option": "accept", "declared": []}, pipeline, only=("CI",))),
                ("", True))
        finally:
            cleanup(root)
    # an exception inside the function is "not known" too, and the one call per carried_change is one call
    root, task_root = int_story("qa-gw15-k5x-")
    real, calls = gate_preflight.Rehearsal._integration_ties, []
    try:
        int_carry(task_root)
        gate_preflight.Rehearsal._integration_ties = lambda self, spec, declared_by: (_ for _ in ()).throw(RuntimeError("boom"))
        check_eq("K15.5: an exception is None, not []", int_ids(task_root), None)
        check_in("K15.5: ... and gate B asks again", UNREAD_WORDS, int_change(task_root))
    finally:
        gate_preflight.Rehearsal._integration_ties = real
        cleanup(root)
    root, task_root = int_story("qa-gw15-k5n-")
    real_fn = gate_preflight.integration_ids_of_case
    try:
        int_carry(task_root)
        gate_preflight.integration_ids_of_case = lambda *a, **k: calls.append(a) or real_fn(*a, **k)
        pipeline = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))
        stand_gaps.carried_change(task_root, TC1, {"at": iso(0), "option": "accept", "declared": [INT]}, pipeline)
        check_eq("K15.5: one `integration_ids_of_case` per carried change (one rehearsal)", len(calls), 1)
    finally:
        gate_preflight.integration_ids_of_case = real_fn
        cleanup(root)
    # the reasons the method gives are the ones the function reads (a drift makes an unread plan look like prose)
    root, task_root = int_story("qa-gw15-k5r-")
    try:
        plan(task_root, root)
        why = gate_preflight.Rehearsal(task_root, "A")._integration_cases(INTS.integration(required_by=["api"]))[2]
        check_eq("K15.5: the plan reason is one of the constants", why.startswith(gate_preflight.INTEGRATION_UNREAD_WHY), True)
    finally:
        cleanup(root)


def test_gw1_15_k15_6_one_id_for_the_card_and_for_the_reader() -> None:
    """The id the card has and the id `integration_ids_of_case` gives are one (twins, one case and two)."""
    twins = [INTS.integration(name="x", keys=["X_ONE"], required_by=["api"]), INTS.integration(name="x", keys=["X_TWO"], required_by=["api"])]
    for label, kw in (("one case", {}), ("two cases", {"base": False, "extra": [(1, "TS-10", []), (2, "TS-12", [])]})):
        root = INTS.story("qa-gw15-k6-", integrations=twins, **({"one_case": True} if not kw else kw))
        try:
            task_root = INTS.task_of(root)
            cards = sorted(g["id"] for g in INTS.creds(root)["stand_gaps"] if g["case"] == TC1)
            check_eq(f"K15.6: {label}: the ids of the cards of TC-001 are the reader's", int_ids(task_root), cards)
            if kw:
                check_eq(f"K15.6: {label}: with two cases the ids carry the case (`shared`)", cards, ["INT-x-2@" + TC1, "INT-x@" + TC1])
            else:
                check_eq(f"K15.6: {label}: twins are told apart by config order", cards, ["INT-x", "INT-x-2"])
        finally:
            cleanup(root)
    # a keyless first twin is no integration, and the ids still count it: the second stays `-2`
    keyless = [INTS.integration(name="x", keys=[], required_by=["api"]), INTS.integration(name="x", keys=["X_TWO"], required_by=["api"])]
    root, task_root = int_story("qa-gw15-k6k-", rows=keyless)
    try:
        check_eq("K15.6: gap ids are counted over every row, so `-2` does not shift", int_ids(task_root), ["INT-x-2"])
        # one word on the twin never closes the other integration
        root2, task2 = int_story("qa-gw15-k6w-", rows=twins[:1])
        try:
            put(task2, "INT-x", "accept - the person wrote: TC: accept", iso(0))
            put(task2, TC1, "accept - the person wrote: TC: accept", iso(0), declared=["INT-x"])
            check_eq("K15.6 control: the carry settles", int_change(task2), "")
            put(task2, "INT-x-2", "theirs - the person wrote: INT-x-2: myself", iso(5))
            check_eq("K15.6: a word on `INT-x-2` does not reopen the case of `INT-x`", int_change(task2), "")
            put(task2, "INT-x", "theirs - the person wrote: INT-x: myself", iso(6))
            check_in("K15.6: a word on `INT-x` does", "you later answered `myself`", int_change(task2))
        finally:
            cleanup(root2)
    finally:
        cleanup(root)


def test_gw1_15_k15_7_k15_8_no_integration_changes_nothing_and_preconditions_stay_preconditions() -> None:
    prose = [INTS.integration(required_by=["the team's own words"])]
    root, task_root = int_story("qa-gw15-k7-", rows=prose)
    try:
        check_eq("K15.7: prose ties nothing: no ids", int_ids(task_root), [])
        check_eq("K15.7: `declared_ids` is byte for byte the old list", stand_gaps.declared_ids(task_root, TC1, None, int_ids(task_root)),
                 stand_gaps.declared_ids(task_root, TC1))
        real = gate_preflight.integration_ids_of_case
        gate_preflight.integration_ids_of_case = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            check_eq("K15.7: the write's door says None for a function that raises, and the list is still made",
                     (stand_gaps._integration_ids(task_root, TC1), stand_gaps.declared_ids(task_root, TC1, None, stand_gaps._integration_ids(task_root, TC1))),
                     (None, stand_gaps.declared_ids(task_root, TC1)))
        finally:
            gate_preflight.integration_ids_of_case = real
    finally:
        cleanup(root)
    root = INTS.declared("qa-gw15-k8-", [INTS.integration(required_by=["api"])])
    try:
        task_root = INTS.task_of(root)
        use_project(root)
        check_eq("K15.8: `declared_preconditions` holds the case's own `PC-*` only",
                 sorted(r["id"] for r in stand_gaps.declared_preconditions(task_root)), ["PC-1"])
        check_eq("K15.8: the case that declares the integration has no `INT-*` of it (its card is the PC)", int_ids(task_root), [])
        check_eq("K15.8: and `declared_ids` is its precondition", stand_gaps.declared_ids(task_root, TC1, None, int_ids(task_root)), ["PC-1"])
    finally:
        cleanup(root)
    root, task_root = int_story("qa-gw15-k8n-")
    try:
        check_eq("K15.8: no `INT-*` in `declared_preconditions` of a tied story", [r["id"] for r in stand_gaps.declared_preconditions(task_root)], [])
    finally:
        cleanup(root)
    # the empty outcomes: no integrations recorded at all, and no config file, are [] (nothing to ask), never None
    root, task_root = int_story("qa-gw15-k7e-", rows=[])
    try:
        check_eq("K15.7: no integration recorded: []", int_ids(task_root), [])
        (root / "qa-factory" / "config.json").unlink()
        check_eq("K15.7: no config file: [] (nothing was recorded), not 'unknown'", int_ids(task_root), [])
    finally:
        cleanup(root)


def test_gw1_15_k15_9_an_untied_accept_is_asked_again_at_gate_b() -> None:
    """G-7 (a), a pin of the DIRECTION: an `accept` on `integration missing: <name>` (the story-level question) is not a stand-gap
    word and no key of it reaches the late S5 row; gate B asks. The allowed error is the question; the debt is
    `factory-rules-debt.md` (FR-7). The day the typed `integration` field closes it, this test changes with it."""
    root, task_root = int_story("qa-gw15-k9-", rows=[INTS.required(required_by=[])])
    try:
        path = task_root / "pipeline.json"
        pipeline = json.loads(path.read_text(encoding="utf-8"))
        pipeline["stage_overrides"] = [{"stage": "S5", "match": "integration missing: jira-integration", "decision": "accept - the person wrote: accept",
                                        "at": iso(0), "by": "human"}]
        path.write_text(json.dumps(pipeline), encoding="utf-8")
        # the LATE S5 row, as a run writes it: a run report's `env_blocked` whose detail names the key and the integration
        # (a reading of key names out of this detail, G-7 (b), would close the card and turn this red)
        (task_root / "work" / "run-report.json").write_text(json.dumps({"env_blocked": [
            {"case": TC1, "owner": "user", "detail": "JIRA_URL is not set for jira-integration"}]}), encoding="utf-8")
        late = stand_gaps.collect(task_root, "B")
        check_eq("K15.9: the late S5 row is a gate B card of the case", [g["id"] for g in late], [TC1])
        answers = stand_gaps.gate_b_answers(task_root, gaps=None)[0]
        check_eq("K15.9: the late row of the case has no answer: gate B asks", answers.get(TC1), None)
        check_eq("K15.9: the delivery check has no decision for it either", TC1 in stand_gaps.delivery_decisions(task_root, json.loads(path.read_text(encoding="utf-8")))[0], False)
    finally:
        cleanup(root)


def main() -> None:
    contract.case_config_reset()
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            contract.case_config_reset()
            fn()
    finish("stand gap carry (B-361)")


if __name__ == "__main__":
    main()
