"""loop: a part of test_story_run_loop_b.py, split by tools/test_split.py (TD-11c). The shared helpers are in story_run_loop_b_common."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402
from story_run_common import (  # noqa: E402
    run_scenarios,
    SCOUT_DIGEST, check_not_in_text, driver_for, eq, jsonl, rules_broken, run_driver, seam_control, seed, set_control,
    stub_calls,
)


def loop_waiver_and_journal_shapes() -> None:
    task = "QA-9"
    # --- the conductor lifts an exit-gate block; the driver finishes from the saved result -------
    root, task_root, env = seed(task)
    try:
        stage_flag = "--" + "stage"  # spelled apart: a guard matches the literal in a shell command
        set_control(root, {"roles": {"qa-scout": {
            "files": {"work/context-manifest.json": "{}", "work/context-bundle.json": "{}"},
            "result": SCOUT_DIGEST.replace("{task}", task)}},
            "resume": {"result": SCOUT_DIGEST.replace("{task}", task)},
            "conductor": {"action": "continue", "did": "waiver recorded on the person's standing word",
                          "run": [[str(harness.SCRIPTS / "waiver.py"), "--task", task, stage_flag, "S1",
                                   "--block", "*", "--decision", "go on: standing instruction"]]}})
        # boundary 1: the role, its ONE resume at the handoff, and the refusal that is left. t-217 (F-cmp2-23, a declared
        # change of what this scenario used to prove): the role was just resumed on exactly these findings, so a second
        # identical refusal is the PERSON's - the conductor (about $0.3 a call) can add nothing to it. t-828 (re-pinned to
        # conductor/1 C1-5d2, t-698 sec. 12.2.1/12.2.5, sec. 13 F-d1): the refusal is asked by the ONE seam, as the site's own
        # question of kind `exit_limit` (stage and dispatch are its FIELDS). The person's words, which are not one of its
        # tokens, go to the conductor once (`unread`), which records the waiver; the words are NOT filed for the role
        # (sec. 13 F-d8, sec. 14 A7; `_file_words` files `pending_words` only for the kinds `conductor` and `refusal`), so boundary 2
        # finishes on the waiver and the role is not resumed a second time.
        out = run_driver(root, env, "--task", task, "--max-boundaries", "2")
        eq("the blocked handoff ends in the person's question, not in a conductor call", out.returncode, 3,
           out.stdout[-1500:] + out.stderr[-600:])
        check_eq("role, one resume - and no conductor, no second role run",
                 [c["kind"] for c in stub_calls(root)], ["role", "resume"])
        question = (task_root / "state/driver-question.md").read_text(encoding="utf-8")
        # t-698 sec. 12.2.2 (key `exit.resume_limit`, kind `exit_limit`), sec. 12.2.1 (the seam's state: stage, dispatch)
        check_in("the question is the seam's exit-limit question about the dispatch (the field)",
                 "kind: exit_limit\nstage: S1\ndispatch: S1-qa-scout-1", question)
        check_in("and offers the closed answers", "`go on`", question)
        answer = root / "answer.md"
        answer.write_text("go on: standing instruction", encoding="utf-8")
        out = run_driver(root, env, "--task", task, "--answer", str(answer), "--max-boundaries", "1")
        eq("the answer ends in a done stage after the conductor's waiver", out.returncode, 0,
           out.stdout[-1500:] + out.stderr[-600:])
        pipeline = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))
        check_eq("S1 is done", pipeline["stages"].get("S1", {}).get("status"), "done")
        calls = stub_calls(root)
        # t-698 sec. 12.2.5 ("other words go to `self.unread`", D-0041: the conductor reads new words) and sec. 14 A7 / sec. 13
        # F-d8: the words reach the conductor, whose waiver passes the gate; nothing resumes the role on them (t-764 hand-back,
        # EL10: `_file_words` files nothing for kind `exit_limit`), so the sequence ENDS at the conductor
        check_eq("role, one resume, the conductor that records the words - and no second resume of the role",
                 [c["kind"] for c in calls], ["role", "resume", "conductor"])
        check_in("the conductor got the person's words", "go on: standing instruction", calls[2]["prompt"])
        # t-698 sec. 12.2.5 (`self.unread(kind, stage, D, qtext, ...)`): the unread answer's prompt carries the question itself,
        # whose header names the kind; the sentence "kind `refusal`" of `generic_prompt` is not this road's
        check_in("and the kind of the question (its header)", "kind: exit_limit", calls[2]["prompt"])
        conductor = jsonl(task_root / "state/conductor.jsonl")
        check_eq("conductor.jsonl has the continue", conductor[-1]["action"], "continue")
        check_in("the waiver is on record", "go on: standing instruction", (task_root / "pipeline.json").read_text(encoding="utf-8"))
        check("the saved result was consumed", (task_root / "state/driver-runs/S1-qa-scout-1.done.json").is_file())

        # --- journal shapes (design/driver.md) ---------------------------------------------
        runs = jsonl(task_root / "state/driver-runs.jsonl")
        wanted = {"ts", "kind", "role", "dispatch", "stage", "session_id", "num_turns", "total_cost_usd",
                  "duration_ms", "resumed", "exit_code", "is_error", "model"}
        check("every driver-runs line has the documented keys", all(wanted <= set(r) for r in runs))
        check_eq("kinds are role and conductor only", sorted({r["kind"] for r in runs}), ["conductor", "role"])
        wanted = {"ts", "boundary", "stage", "refusal", "action", "did"}
        check("every conductor line has the documented keys", all(wanted <= set(r) for r in conductor))
        check("a conductor call carries its session and cost",
              all({"session_id", "total_cost_usd", "num_turns", "duration_ms", "words"} <= set(r)
                  for r in conductor if not str(r["action"]).startswith("known:")))
    finally:
        harness.cleanup(root)


CRITIC = "S5-qa-code-critic-5"


def unresolved_finish(root, env, task_root, complete, *, wcode: int = 0, record=None, stage="S5", role="qa-code-critic"):
    """One `finish` of the S5 critic with `window_record.py` answering `wcode` and, when `record` is given, that
    record on disk where window_record writes it. (the `story_step.py` argument list, what the driver printed)."""
    import contextlib
    import io
    path = task_root / "work" / "windows" / f"{CRITIC}.json"
    path.unlink(missing_ok=True)
    if record is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record), encoding="utf-8")
    driver = driver_for(root, env, "QA-9")
    calls = []

    def py(script, *args, **kwargs):
        calls.append((script, [str(a) for a in args]))
        return (wcode, "window record: gaps") if script == "window_record.py" else (0, "accepted x")
    driver.py = py
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        driver.finish(CRITIC, "qa-code-critic S5 W1 ok", complete=complete, role=role, stage=stage)
    return [c for c in calls if c[0] == "story_step.py"][0][1], printed.getvalue()


def flag(args: list, name: str):
    """The value after `name`, or None when the flag is not there."""
    return args[args.index(name) + 1] if name in args else None


def s5_finish_unresolved_pair() -> None:
    """t-201 (state-exits.md, an S5 window accepted as unresolved): `finish(complete=(word, reason))` passes
    `--complete --unresolved <word> --reason <reason>`; `True` passes neither; an empty half is no pair."""
    root, task_root, env = seed("QA-9")
    try:
        args, _ = unresolved_finish(root, env, task_root, ("handed_to_person", "TC-1 runs on the person's profile"))
        check_eq("a pair: the finish is complete", "--complete" in args, True)
        check_eq("a pair: --unresolved carries the word", flag(args, "--unresolved"), "handed_to_person")
        check_eq("a pair: --reason carries the reason", flag(args, "--reason"), "TC-1 runs on the person's profile")
        check_eq("a pair: the window record is passed as today (exit 0)", flag(args, "--window"), f"work/windows/{CRITIC}.json")
        check_eq("a pair: never --not-complete", "--not-complete" in args, False)
        args, _ = unresolved_finish(root, env, task_root, lambda digest: ("could_not_judge", "note of the critic"))
        check_eq("a callable returning the pair (the critic's lambda): the same flags",
                 (flag(args, "--unresolved"), flag(args, "--reason")), ("could_not_judge", "note of the critic"))
        args, _ = unresolved_finish(root, env, task_root, True)
        check_eq("True: neither flag (no record on disk)", ("--unresolved" in args, "--reason" in args, "--complete" in args),
                 (False, False, True))
        for label, pair in (("empty word", ("", "a reason")), ("empty reason", ("could_not_judge", "")),
                            ("blank word", ("  ", "a reason")), ("blank reason", ("could_not_judge", " \n")),
                            ("no reason at all", ("could_not_judge",)), ("not text", (None, 5)), ("empty pair", ())):
            args, _ = unresolved_finish(root, env, task_root, pair)
            check_eq(f"{label}: no flags, today's plain --complete",
                     ("--unresolved" in args, "--reason" in args, "--complete" in args), (False, False, True))
        args, _ = unresolved_finish(root, env, task_root, ("handed_to_person", "r"), role="qa-automator")
        check_eq("a pair on another role's finish is passed all the same (the caller decides)", flag(args, "--unresolved"), "handed_to_person")
        args, _ = unresolved_finish(root, env, task_root, False)
        check_eq("False: --not-complete and no flags", ("--not-complete" in args, "--unresolved" in args, "--complete" in args),
                 (True, False, False))
    finally:
        harness.cleanup(root)


# The `handed_to_person` row of the manifest - same shape as `HANDED_ROW` of test_acceptance_semantics.py (not imported: that
# module makes a temp dir on import) and of test_window_record.py.
HANDED_ROW = {"case": "TC-1", "reason": "handed_to_person", "detail": "web: npx playwright test t.spec.ts"}


def confirm_handed(task_root, instance_id) -> None:
    """EP1-4 (t-626 FR-4/AR-28, t-740 diagnosis): a `handed_to_person` claim counts only as far as the manifest under the root
    confirms it, so the instance is registered as a test of TC-1 and TC-1 carries the handed row. Idempotent: the same
    `task_root` is reused across checks, so a second call adds nothing twice."""
    path = task_root / "work" / "automation-manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"tests": [], "unresolved": []}
    if not any(t.get("instance_id") == instance_id for t in manifest["tests"]):
        manifest["tests"].append({"instance_id": instance_id, "covers": ["TC-1"]})
    if not any(r.get("case") == "TC-1" and r.get("reason") == "handed_to_person" for r in manifest["unresolved"]):
        manifest["unresolved"].append(dict(HANDED_ROW))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")


def window_item(task_root, instance_id="t::a", outcome="passed", **change) -> dict:
    """An instance `acceptance.validate_window` finds NO gap in (t-204: `window_gap` reads the record through
    that function, so a bare `{"instance_id", "outcome"}` is a malformed instance now): the evidence file is
    written under `task_root`, the probe is the fixture of test_acceptance_semantics, and a handed instance
    carries no probe. `change` overrides fields, `{"review": ...}` to make a gap."""
    import hashlib
    (task_root / "proof.txt").write_text("proof", encoding="utf-8")
    digest = hashlib.sha256(b"proof").hexdigest()
    handed = outcome == "handed_to_person"
    if handed:
        confirm_handed(task_root, instance_id)
    item = {"schema_version": 2, "instance_id": instance_id, "input_hash": "input", "outcome": outcome,
            "review": {"verdict": "approved", "input_hash": "input"},
            "obligation_ids": ["O-1"], "obligation_hash": "ohash", "assertion_id": "assert-total",
            "defect_location": "src/app.py:8", "change_disposition": "new_or_changed", "change_basis_ref": "diff",
            "probe": {} if handed else {
                "verdict": "intended_failure", "input_hash": "input", "obligation_ids": ["O-1"],
                "obligation_hash": "ohash", "assertion_id": "assert-total", "defect_location": "src/app.py:8",
                "expected_location": "tests/test_app.py:9", "actual_location": "tests/test_app.py:9",
                "expected_reason": "wrong total", "actual_reason": "wrong total", "failure_kind": "assertion",
                "mutation_kind": "real_behavior", "evidence_ref": "proof.txt"},
            "evidence_refs": [{"path": "proof.txt", "sha256": digest}]}
    item.update(change)
    return item


def window_of(instances, changes=None, *, changes_first=False) -> dict:
    """A window record with the keys in the order given (the word of `window_gap` follows the file's order)."""
    head = {"schema_version": 2, "input_hash": "input", "required_quality_checks": []}
    handed_ids = [i["instance_id"] for i in instances if i.get("outcome") == "handed_to_person"]
    if handed_ids:   # the scope map the hand-off is confirmed through (head keys are not gap kinds: the file order is untouched)
        head["scope_instances"] = {"TC-1": handed_ids}
    parts = [("instances", instances)] + ([("expectation_changes", changes)] if changes is not None else [])
    return {**head, **dict(reversed(parts) if changes_first else parts)}


def s5_window_record_gaps_become_the_pair() -> None:
    """t-201: the window record the driver just built says the window holds gaps the critic could not close ->
    the finish carries them; the word is the first gap kind in the record's own order, the reason names every kind
    and is cut at 300 characters; a missing record, a crashed build or a record with no such gap is today's road."""
    root, task_root, env = seed("QA-9")
    try:
        handed = window_item(task_root, "t::a", "handed_to_person")
        passed = window_item(task_root, "t::p")
        judged = {"function": "test_b", "red_attempt": "a1", "green_attempt": "a2", "critic_verdict": "could_not_judge"}
        fitted = {"function": "test_c", "red_attempt": "a1", "green_attempt": "a2", "critic_verdict": "fitted_to_code"}
        two = window_of([handed], [judged])
        args, printed = unresolved_finish(root, env, task_root, True, wcode=1, record=two)
        check_eq("two kinds, `instances` first in the file: the word is the first in file order",
                 flag(args, "--unresolved"), "handed_to_person")
        reason = flag(args, "--reason") or ""
        check("and the reason names both kinds, each with the record's own line",
              reason.startswith("handed_to_person, could_not_judge: handed_to_person:t::a; expectation_change:test_b: ")
              and "could not judge" in reason, reason)
        check_eq("the record is passed with the flags (exit 1 wrote it)", flag(args, "--window"), f"work/windows/{CRITIC}.json")
        check_in("and said", "holds gaps the critic could not close (handed_to_person)", printed)
        swapped = window_of([handed], [judged, fitted], changes_first=True)
        args, _ = unresolved_finish(root, env, task_root, True, wcode=1, record=swapped)
        check_eq("the same kinds with `expectation_changes` first in the file: that kind is the word",
                 flag(args, "--unresolved"), "could_not_judge")
        check_in("and every kind is named in the reason", "could_not_judge, fitted_to_code, handed_to_person: ", flag(args, "--reason") or "")
        args, _ = unresolved_finish(root, env, task_root, True, wcode=0, record=window_of([passed], [fitted]))
        check_eq("fitted_to_code alone, exit 0: the word", flag(args, "--unresolved"), "fitted_to_code")
        check_eq("and the window flag is the one of exit 0, once", args.count("--window"), 1)
        # the limit: 300 characters - at it, nothing is cut; beyond it, the cut keeps the kinds that stand first
        import story_run
        limit = story_run.Driver.WINDOW_REASON_LIMIT
        check_eq("the reason limit is 300", limit, 300)
        path = task_root / "work" / "windows" / "limit.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        stem = len("handed_to_person: handed_to_person:")      # one kind, one instance: the reason is stem + the id
        for extra, label in ((0, "AT the limit (300 characters)"), (1, "one BEYOND it (301 characters)")):
            record = window_of([window_item(task_root, "x" * (limit - stem + extra), "handed_to_person")])
            path.write_text(json.dumps(record), encoding="utf-8")
            pair = story_run.Driver.window_gap(path)
            check_eq(f"{label}: a pair, not `()` (t-740 Q4: an empty answer is a named FAIL, not a crash)", len(pair), 2)
            word, why = pair if len(pair) == 2 else ("", "")
            check_eq(f"{label}: the word", word, "handed_to_person")
            check_eq(f"{label}: the reason is 300 characters", len(why), 300)
            check_eq(f"{label}: and is cut only when it must be", why.endswith("x" * 5) and why.count("x") == limit - stem, True)
        record = window_of([window_item(task_root, "x" * 400, "handed_to_person")], [judged])
        path.write_text(json.dumps(record), encoding="utf-8")
        pair = story_run.Driver.window_gap(path)
        check_eq("far beyond, two kinds: a pair, not `()`", len(pair), 2)
        word, why = pair if len(pair) == 2 else ("", "")
        check("far beyond, two kinds: cut at 300, and the kinds stand first so the cut hides none",
              len(why) == 300 and why.startswith("handed_to_person, could_not_judge: "), why[:80])
        # today's road: no flags
        args, printed = unresolved_finish(root, env, task_root, True, wcode=1, record=None)
        check_eq("record missing (exit 1): no flags, no window flag", ("--unresolved" in args, "--window" in args), (False, False))
        check_in("record missing: the note says what is true (t-217 §4: nothing was written, so nothing is passed)",
                 "(exit 1); no record exists, the finish goes without one", printed)
        args, _ = unresolved_finish(root, env, task_root, True, wcode=2, record=two)
        check_eq("a crashed build (exit 2) with an older file on disk: the file is not read", "--unresolved" in args, False)
        clean = window_of([passed], [{"function": "f", "critic_verdict": "legitimate_correction"}])
        args, _ = unresolved_finish(root, env, task_root, True, wcode=0, record=clean)
        check_eq("a record with no gap: no flags", "--unresolved" in args, False)
        args, _ = unresolved_finish(root, env, task_root, True, wcode=1,
                                    record=window_of([passed], [{"function": "f", "critic_verdict": None}]))
        check_eq("a change with no verdict is not a gap the critic could not close: no flags", "--unresolved" in args, False)
        path.write_text("{not json", encoding="utf-8")
        check_eq("a record that is not JSON: no flags", story_run.Driver.window_gap(path), ())
        path.write_text("[1]", encoding="utf-8")
        check_eq("a record that is not an object: no flags", story_run.Driver.window_gap(path), ())
        check_eq("a file that is not there: no flags", story_run.Driver.window_gap(task_root / "nope.json"), ())
        args, _ = unresolved_finish(root, env, task_root, ("handed_to_person", "given"), wcode=1, record=two)
        check_eq("a pair the caller gave outranks the record's", (flag(args, "--unresolved"), flag(args, "--reason")),
                 ("handed_to_person", "given"))
        args, _ = unresolved_finish(root, env, task_root, False, wcode=1, record=two)
        check_eq("not complete: the record is not read", ("--unresolved" in args, "--not-complete" in args), (False, True))
        args, _ = unresolved_finish(root, env, task_root, True, wcode=1, record=two, role="qa-automator")
        check_eq("not the critic's finish: the record is not read", "--unresolved" in args, False)
    finally:
        harness.cleanup(root)


def s5_window_gap_other_gaps_refuse_the_pair() -> None:
    """t-204 F1: the controller reads `unresolved` as present or not, so a pair covers EVERY gap of the window.
    INVARIANT: the driver never builds the pair over a gap the critic did not name as its own - a handed
    instance beside a failed one (a `product:` gap) is a plain `--complete`, and the controller's refusal stays
    reachable for that window."""
    import story_run
    root, task_root, env = seed("QA-9")
    try:
        handed = window_item(task_root, "t::h", "handed_to_person")
        failed = window_item(task_root, "t::f", "failed")
        passed = window_item(task_root, "t::p")
        judged = {"function": "test_b", "red_attempt": "a1", "green_attempt": "a2", "critic_verdict": "could_not_judge"}
        path = task_root / "work" / "windows" / "gap.json"
        path.parent.mkdir(parents=True, exist_ok=True)

        def gap_of(record):
            path.write_text(json.dumps(record), encoding="utf-8")
            return story_run.Driver.window_gap(path)

        def flags_of(record):
            args, _ = unresolved_finish(root, env, task_root, True, wcode=1, record=record)
            return ("--unresolved" in args, "--reason" in args, "--complete" in args)
        # the controller's own list of gaps for the record, so the test names what it is about
        import acceptance
        mixed = window_of([handed, failed])
        check_eq("the fixture: the handed instance and the failed one are the window's gaps",
                 acceptance.validate_window(mixed, task_root), ["handed_to_person:t::h", "product:t::f"])
        check_eq("handed + failed (a `product:` gap): no pair", gap_of(mixed), ())
        check_eq("and the finish is a plain --complete", flags_of(mixed), (False, False, True))
        check_eq("the same with the failed one first in the list", gap_of(window_of([failed, handed])), ())
        check_eq("handed + failed + a could_not_judge change: still no pair (the failed one is not the critic's)",
                 gap_of(window_of([handed, failed], [judged])), ())
        check_eq("a failed instance with a could_not_judge change and no handed one: no pair",
                 gap_of(window_of([failed], [judged])), ())
        check_eq("handed only: the pair", gap_of(window_of([handed]))[:1], ("handed_to_person",))
        check_eq("handed only, the finish: complete + --unresolved + --reason", flags_of(window_of([handed])),
                 (True, True, True))
        check_eq("could_not_judge only: the pair", gap_of(window_of([passed], [judged]))[:1], ("could_not_judge",))
        check_eq("could_not_judge only, the finish: complete + --unresolved + --reason",
                 flags_of(window_of([passed], [judged])), (True, True, True))
        reviewed = window_item(task_root, "t::r", review={"verdict": "rejected", "input_hash": "input"})
        check_eq("a `review:` gap on a non-handed instance: no pair", gap_of(window_of([reviewed], [judged])), ())
        check_eq("a `review:` gap on a non-handed instance beside a handed one: no pair",
                 gap_of(window_of([handed, reviewed])), ())
        # HF4-10 (t-1480): only a check some factory script produces a receipt for is demanded; the data names `lint`
        import window_record as _wr
        producers = task_root / "work" / "quality-producers.json"
        producers.write_text(json.dumps({"schema_version": 1, "producers": {"lint": "lint_receipt.py"}, "why": {}}),
                             encoding="utf-8")
        saved_file, _wr.QUALITY_PRODUCERS_FILE = _wr.QUALITY_PRODUCERS_FILE, producers
        try:
            check_eq("a `quality:` gap (a required check with no receipt): no pair",
                     gap_of({**window_of([handed]), "required_quality_checks": ["lint"]}), ())
        finally:
            _wr.QUALITY_PRODUCERS_FILE = saved_file
        check_eq("a no-verdict change beside a handed instance: no pair (not the critic's word)",
                 gap_of(window_of([handed], [{"function": "f", "critic_verdict": None}])), ())
        check_eq("an unknown verdict beside a handed instance: no pair",
                 gap_of(window_of([handed], [{"function": "f", "critic_verdict": "strange"}])), ())
        check_eq("a record the validation cannot read (no `required_quality_checks`): no pair",
                 gap_of({"instances": [handed]}), ())
        check_eq("an empty window: no pair", gap_of(window_of([])), ())
    finally:
        harness.cleanup(root)


def s5_window_gap_unconfirmed_claim_is_no_pair() -> None:
    """t-740 / EP1-4 (t-626 FR-4, AR-28): an item that CLAIMS `handed_to_person` while the manifest under the root does not
    confirm it is `handed_unconfirmed:<id>` - a gap that is the record's, never the critic's own - so `window_gap` answers
    `()` and the finish is a plain `--complete`. INVARIANT: no pair is ever built over a hand-off nobody wrote. The twin: the
    same window with the manifest confirming it IS the pair (the fixtures' road)."""
    import acceptance
    import story_run
    root, task_root, env = seed("QA-9")
    try:
        record = window_of([window_item(task_root, "t::u", "handed_to_person")])
        path = task_root / "work" / "windows" / "unconfirmed.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record), encoding="utf-8")
        check_eq("twin, the manifest confirms the claim: the pair", story_run.Driver.window_gap(path)[:1], ("handed_to_person",))
        (task_root / "work" / "automation-manifest.json").unlink()
        found = acceptance.validate_window(record, task_root)
        check_in("no manifest: the claim is a gap of its own kind", "handed_unconfirmed:t::u", found)
        check_not_in("and never `handed_to_person:` (a pair is never derived over it)", "handed_to_person:t::u", found)
        check_eq("and `window_gap` gives no pair", story_run.Driver.window_gap(path), ())
        args, _ = unresolved_finish(root, env, task_root, True, wcode=1, record=record)
        check_eq("and the finish is a plain --complete", ("--unresolved" in args, "--reason" in args, "--complete" in args),
                 (False, False, True))
        confirm_handed(task_root, "t::u")
        no_scope = {k: v for k, v in record.items() if k != "scope_instances"}
        found = acceptance.validate_window(no_scope, task_root)
        check_in("a manifest but no `scope_instances`: still unconfirmed", "handed_unconfirmed:t::u", found)
        check_not_in("and still no `handed_to_person:`", "handed_to_person:t::u", found)
        path.write_text(json.dumps(no_scope), encoding="utf-8")
        check_eq("and `window_gap` gives no pair", story_run.Driver.window_gap(path), ())
    finally:
        harness.cleanup(root)


def window_gaps(n: int = 5, tag: str = "a") -> list:
    """The gap lines `window_record.py` prints for a window (cmp2-27.log:4-8), in its own shape."""
    kinds = ("review", "semantic_sensitivity", "sensitivity")
    return [f"{kinds[i % 3]}:test_{tag}{i} — the manifest row carries no `critic_verdict`; `manifest_put.py` records it"
            for i in range(n)]


def window_output(gaps: list, *, tail: list | None = None) -> str:
    """What `window_record.py` prints on exit 1: the record line, the NOT acceptable line, every gap, then the markers."""
    import story_run
    lines = ["window record: work/windows/x.json — 2 instance(s), scope TC-4, TC-8", "note: a note of the record",
             "this window is NOT acceptable yet. Every gap at once, with the artifact it came from — repair the "
             "artifact, never this record:"] + ["  - " + g for g in gaps]
    lines.append(f"{story_run.REPAIR_MARKER}. A person's word still passes the window: the orchestrator records "
                 "`waiver.py --task T --stage S5 --block \"<part of the line>\" --decision \"<their words>\"`.")
    return "\n".join(lines + (tail or []))


def window_finish(root, env, task_root, *, wcode: int, wout: str, writes: bool, older: bool = False, step=(0, "accepted x")):
    """One S5 critic `finish` with `window_record.py` exiting `wcode` and printing `wout`; `writes`: it (re)writes the
    record file the way the real script does at its start, `older`: a record from an earlier build is on disk before.
    (the `story_step.py` arguments, what the driver printed, the Refusal it raised or None)."""
    import contextlib
    import io
    import story_run
    path = task_root / "work" / "windows" / f"{CRITIC}.json"
    path.unlink(missing_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    if older:
        path.write_text('{"older": true}', encoding="utf-8")
    driver = driver_for(root, env, "QA-9")
    calls = []

    def py(script, *args, **kwargs):
        calls.append((script, [str(a) for a in args]))
        if script == "window_record.py":
            if writes:
                path.write_text(json.dumps({"written_by_this_call": "a record that is longer than the older one"}), encoding="utf-8")
            return wcode, wout
        return step
    driver.py = py
    printed, raised = io.StringIO(), None
    with contextlib.redirect_stdout(printed):
        try:
            driver.finish(CRITIC, "qa-code-critic S5 W1 ok", complete=True, role="qa-code-critic", stage="S5")
        except story_run.Refusal as refusal:
            raised = refusal
    return [c for c in calls if c[0] == "story_step.py"][0][1], printed.getvalue(), raised


def s5_window_note_says_what_is_true() -> None:
    """K4 (t-217 §4, F-cmp2-28b): cmp2-27.log:3 said "the finish goes without a window record" although exit 1 had WRITTEN the
    record and `story_step finish` passes `work/windows/<dispatch>.json` by itself, and :9 echoed the marker line ("This is a
    repair, not a question for the person") at the person. INVARIANTS: PRINT ONLY - the `--window` / `--unresolved` decisions are
    unchanged and no `window_record.py` line is part of the Refusal's text; "written" is the file's stamp before/after the call,
    never the exit code; a line holding a marker is never echoed."""
    import story_run
    root, task_root, env = seed("QA-9")
    try:
        gaps = window_gaps()
        wout = window_output(gaps)
        # exit 1, the record written by this call: the words are the true ones, every gap is shown, no marker is echoed
        args, printed, raised = window_finish(root, env, task_root, wcode=1, wout=wout, writes=True)
        check_in("K4: exit 1 + a record written by this call: found N gaps, the finish passes it, the controller judges",
                 f"found 5 gap(s) in the window of {CRITIC}; the finish passes the record it wrote and the controller judges it", printed)
        check_not_in_text("K4: cmp2-27.log:3's false words are gone", ("goes without a window record",), printed)
        check_not_in_text("K4: and the marker echo of cmp2-27.log:9 (both markers)",
                          (story_run.REPAIR_MARKER, story_run.PERSON_MARKER, "A person's word still passes"), printed)
        check("K4: every gap line is shown", all(g in printed for g in gaps), printed)
        check("and nothing else of the output (the record line, the NOT acceptable line)",
              "window record:" not in printed and "NOT acceptable" not in printed, printed)
        check_eq("PRINT ONLY: the finish is today's plain `--complete` (no --window, no --unresolved)",
                 ("--complete" in args, "--window" in args, "--unresolved" in args), (True, False, False))
        check_eq("and nothing was raised", raised, None)
        # exit 1, a record on disk that this call did not write: said so, and the gaps are still shown
        args, printed, _r = window_finish(root, env, task_root, wcode=1, wout=wout, writes=False, older=True)
        check_in("exit 1, the file's stamp unchanged: an older record is on disk and story_step reads it",
                 f"could not build the record of {CRITIC} (exit 1); an older record is on disk and story_step reads it", printed)
        check("with the gaps", all(g in printed for g in gaps))
        # no record at all
        args, printed, _r = window_finish(root, env, task_root, wcode=1, wout=wout, writes=False)
        check_in("no file: no record exists, the finish goes without one",
                 f"could not build the record of {CRITIC} (exit 1); no record exists, the finish goes without one", printed)
        check_eq("and no --window is passed", "--window" in args, False)
        # a crash AFTER the write (window_record.py main catches errors after the write): the stamp, not the exit code, says written
        args, printed, _r = window_finish(root, env, task_root, wcode=2, wout="Traceback ...\nValueError: x", writes=True)
        check_in("exit 2 after the record was written: said so", "exited 2 after it wrote the record", printed)
        check_not_in_text("exit 2 after a write is not called an older record", ("older record",), printed)
        args, printed, _r = window_finish(root, env, task_root, wcode=2, wout="Traceback ...\nValueError: x", writes=False, older=True)
        check_in("exit 2 with an older record: older", "an older record is on disk and story_step reads it", printed)
        # edges of the output
        args, printed, _r = window_finish(root, env, task_root, wcode=1, wout="", writes=True)
        check_in("an empty output: the count is 0 and the words still say which file state holds", "found 0 gap(s) in the window", printed)
        check_not_in_text("and no colon is left hanging", (":\n",), printed)
        lines = [f"line {n}" for n in range(1, 9)]
        lines[6] = story_run.PERSON_MARKER + " (three options)"
        args, printed, _r = window_finish(root, env, task_root, wcode=1, wout="\n".join(lines), writes=True)
        check("no `  - ` line: the last 6 lines minus the marker lines",
              all(f"line {n}" in printed for n in (3, 4, 5, 6, 8)) and not any(f"line {n}" in printed for n in (1, 2, 7)), printed)
        args, printed, _r = window_finish(root, env, task_root, wcode=0, wout="the window is acceptable", writes=True)
        check_eq("exit 0 is unchanged: the window is passed, nothing is said",
                 (flag(args, "--window"), "found" in printed or "could not build" in printed), (f"work/windows/{CRITIC}.json", False))
        # a refused finish: the window_record output is NEVER part of the Refusal's text; the gaps are a field of their own
        text = "story_step: refused - S5 window record is incomplete: assertion_id is missing"
        args, printed, raised = window_finish(root, env, task_root, wcode=1, wout=wout, writes=True, step=(2, text))
        check("a Refusal was raised", raised is not None)
        if raised:
            check_eq("the Refusal's text is story_step's own words and no window_record.py line",
                     raised.text, f"story_step finish {CRITIC} (exit 2):\n{text}")
            check_not_in_text("pinned: none of the output's lines is in it", [g for g in gaps] + [story_run.REPAIR_MARKER, "NOT acceptable"], raised.text)
            check_eq("the gap lines travel in `window_findings`, for the cap alone (C2)", raised.window_findings, gaps)
            check_eq("`findings` stays empty (the one-resume record never keys on the window's gaps)", raised.findings, [])
            check_eq("and the dispatch is a field (FR-16)", raised.dispatch, CRITIC)
        args, printed, raised = window_finish(root, env, task_root, wcode=2, wout="Traceback\nValueError", writes=True, step=(2, text))
        check_eq("a crash (exit 2) carries no gap lines", raised.window_findings if raised else None, [])
    finally:
        harness.cleanup(root)


def s5_window_rounds_are_capped() -> None:
    """K5 (t-217 §5, F-cmp2-28c): cmp2-27 sent the same five gap lines to the conductor for critic-2 and critic-3 and reworked
    again each time (11 automators + 4 critics, $7.28). INVARIANTS: a finding set equal to an earlier round's, or a third
    round, is the PERSON's - the round is written BEFORE the paid call; AT the cap (2) the round runs, BEYOND it the person is
    asked; only the stage's closing role's accepted completion ends the series (C1: an author's accepted finish between two
    reviews does not); known rows act first and are never counted; an empty set is never recorded and never equal."""
    import contextlib
    import io
    import story_run
    root, task_root, env = seed("QA-9")
    scope = ["TP1-15045_TC_008", "TP1-15045_TC_004"]       # the controller's own order is not sorted
    key = "S5|TP1-15045_TC_004,TP1-15045_TC_008"
    records = {d: {"stage": "S5", "role": role, "scope": list(scope)} for d, role in (
        ("S5-qa-code-critic-2", "qa-code-critic"), ("S5-qa-code-critic-3", "qa-code-critic"),
        ("S5-qa-code-critic-4", "qa-code-critic"), ("S5-qa-code-critic-5", "qa-code-critic"),
        ("S5-qa-automator-10", "qa-automator"))}
    conductor = []
    try:
        def driver_at(dispatch: str, known=True):
            driver = driver_for(root, env, "QA-9")
            driver.controller_state = (lambda: {"dispatches": records}) if known else (lambda: {})
            driver.conductor = lambda text, *, words="", files=None, words_file=None: conductor.append(text) or {"action": "continue", "did": "stub"}
            driver.boundary = "S5:" + dispatch
            return driver

        def refusal(dispatch: str, gaps: list):
            return story_run.Refusal(f"story_step finish {dispatch} (exit 2):\nstory_step: refused - S5 window record is "
                                     "incomplete: assertion_id is missing", dispatch=dispatch, window_findings=gaps)

        def handle(driver, ref):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                try:
                    return driver.handle_refusal(ref), out.getvalue()
                except story_run.Person as person:
                    return person, out.getvalue()

        def held() -> list:
            return (json.loads((task_root / "state/driver-state.json").read_text(encoding="utf-8")).get("window_rounds") or {}).get(key, [])

        g1, g2, g3 = window_gaps(5, "a"), window_gaps(5, "b"), window_gaps(4, "c")

        def with_id(gaps: list, dispatch: str) -> list:
            """The same gap lines as the next dispatch words them: its own id inside each line."""
            return [f"{g} ({dispatch})" for g in gaps]
        # round 1 goes to the conductor and is on disk BEFORE anything else happens to it
        driver = driver_at("S5-qa-code-critic-2")
        outcome, said = handle(driver, refusal("S5-qa-code-critic-2", with_id(g1, "S5-qa-code-critic-2")))
        check_eq("round 1: the conductor is called once and the loop goes on", (outcome, len(conductor)), ("continue", 1))
        check_in("said as it is", f"S5 window {','.join(sorted(scope))}: round 1 of 2 goes to the conductor", said)
        check_eq("the series is keyed `<stage>|<sorted scope>`, one round, outcome to_conductor, the set normalized",
                 [(r["dispatch"], r["outcome"], r["set"]) for r in held()],
                 [("S5-qa-code-critic-2", "to_conductor", story_run.finding_lines(with_id(g1, "S5-qa-code-critic-2")))])
        # C1: an author's ACCEPTED finish between the two critics does not end the series (cmp2-27.log:17)
        driver.py = lambda script, *args, **kw: (0, "accepted x")
        with contextlib.redirect_stdout(io.StringIO()):
            driver.finish("S5-qa-automator-10", "qa-automator S5 W ok", complete=False, role="qa-automator", stage="S5")
            driver.finish("S5-qa-code-critic-3", "qa-code-critic S5 W ok", complete=False, role="qa-code-critic", stage="S5")
        check_eq("C1: an author's accepted finish, and a critic's NOT-complete one, leave the series where it is", len(held()), 1)
        # K5: critic-3 comes back with the same findings (its own dispatch id inside a line changes nothing) -> the person
        relaunched = driver_at("S5-qa-code-critic-3")           # a fresh driver: the series is in the state file
        outcome, said = handle(relaunched, refusal("S5-qa-code-critic-3", with_id(g1, "S5-qa-code-critic-3")))
        check("K5: the same set on a fresh driver is the person's", isinstance(outcome, story_run.Person), repr(outcome))
        check_eq("K5: and the conductor was NOT called again (cmp2-27.log:29 `conductor: continue - ... rework` is gone)", len(conductor), 1)
        if isinstance(outcome, story_run.Person):
            check_eq("the Person is a refusal question about the critic's dispatch", (outcome.kind, outcome.dispatch, outcome.stage),
                     ("refusal", "S5-qa-code-critic-3", "S5"))
            check_in("one plain sentence first, naming the round", "This window came back with the same findings as round 1; the driver does not rework it again.", outcome.text)
            check_in("then the closed answers", "`go on`", outcome.text)
            check_eq("FR-6: the text obeys human-questions.md", rules_broken(outcome.text + "\n\n---\nAnswer: x"), [])
            check_in("the refusal AND the set are beside it", "The findings of this round:", outcome.details)
            check_in("with a line of the set", story_run.finding_lines(with_id(g1, "S5-qa-code-critic-3"))[0].split(" (")[0], outcome.details)
        check_in("said as it is", "round 2 came back with the same 5 finding(s) as round 1 — no further rework; the person is asked", said)
        check_eq("the stop is recorded once, as its own outcome", [r["outcome"] for r in held()], ["to_conductor", "same_set"])
        handle(driver_at("S5-qa-code-critic-3"), refusal("S5-qa-code-critic-3", with_id(g1, "S5-qa-code-critic-3")))
        check_eq("a person's answer clears nothing: the same set afterwards is the person's again, not recorded twice",
                 ([r["outcome"] for r in held()], len(conductor)), (["to_conductor", "same_set"], 1))
        # a set that differs and is within the cap (AT 2) reaches the conductor; the one after it is BEYOND
        outcome, said = handle(driver_at("S5-qa-code-critic-3"), refusal("S5-qa-code-critic-3", g2))
        check_eq("AT the cap: round 2 of 2 runs (the findings changed)", (outcome, len(conductor)), ("continue", 2))
        check_in("said as it is", "round 2 of 2 goes to the conductor (the findings changed)", said)
        outcome, said = handle(driver_at("S5-qa-code-critic-4"), refusal("S5-qa-code-critic-4", g3))
        check("BEYOND the cap: a THIRD set, however new, is the person's", isinstance(outcome, story_run.Person), repr(outcome))
        check_eq("the conductor was not called", len(conductor), 2)
        if isinstance(outcome, story_run.Person):
            check_in("the sentence says the driver has sent it back twice", "sent this window back for rework 2 times already", outcome.text)
        check_in("said as it is", "the cap of 2 rounds is spent — the person is asked", said)
        handle(driver_at("S5-qa-code-critic-4"), refusal("S5-qa-code-critic-4", g3))
        check_eq("the cap stop is recorded once", [r["outcome"] for r in held()], ["to_conductor", "same_set", "to_conductor", "cap"])
        # the closing role's ACCEPTED completion ends the series, and the set is welcome again afterwards
        closer = driver_at("S5-qa-code-critic-5")
        closer.py = lambda script, *args, **kw: (0, "ok") if script == "window_record.py" else (0, "accepted x")
        with contextlib.redirect_stdout(io.StringIO()):
            closer.finish("S5-qa-code-critic-5", "qa-code-critic S5 W ok", complete=True, role="qa-code-critic", stage="S5")
        check_eq("an accepted critic completion pops the series (in memory and on disk)", (key in closer.state["window_rounds"], held()), (False, []))
        outcome, _said = handle(driver_at("S5-qa-code-critic-5"), refusal("S5-qa-code-critic-5", g1))
        check_eq("and the set starts a new series", (outcome, len(conductor)), ("continue", 3))
        # a refused completion pops nothing
        closer = driver_at("S5-qa-code-critic-5")
        closer.py = lambda script, *args, **kw: (0, "ok") if script == "window_record.py" else (2, "story_step: refused")
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                closer.finish("S5-qa-code-critic-5", "qa-code-critic S5 W ok", complete=True, role="qa-code-critic", stage="S5")
        except story_run.Refusal:
            pass
        check_eq("a refused completion leaves the series", len(held()), 1)

        # edges: no findings (an empty set) is never recorded and never equal
        before = len(conductor)
        for label, ref in (("no body", story_run.Refusal("story_step finish S5-qa-code-critic-2 (exit 2):", dispatch="S5-qa-code-critic-2")),
                           ("blank findings", story_run.Refusal("story_step finish S5-qa-code-critic-2 (exit 2):\n  \n",
                                                                dispatch="S5-qa-code-critic-2", window_findings=["", "  "]))):
            for _ in range(3):
                outcome, _said = handle(driver_at("S5-qa-code-critic-2"), ref)
                check_eq(f"{label}: the conductor, as before - never the person", outcome, "continue")
        check_eq("no findings: three calls each, and the series is as it was", (len(conductor) - before, len(held())), (6, 1))
        # scope unreadable: keyed by the dispatch; the series cannot accumulate, the conductor's own cap is the bound
        before = len(conductor)
        for dispatch in ("S5-qa-code-critic-2", "S5-qa-code-critic-3"):
            outcome, _said = handle(driver_at(dispatch, known=False), refusal(dispatch, g1))
            check_eq(f"scope unreadable, {dispatch}: the conductor", outcome, "continue")
        keys = sorted(json.loads((task_root / "state/driver-state.json").read_text(encoding="utf-8"))["window_rounds"])
        check_eq("scope unreadable: one series per dispatch, none of them capped", (len(conductor) - before, keys),
                 (2, sorted([key, "S5|S5-qa-code-critic-2", "S5|S5-qa-code-critic-3"])))
        # known rows act first and are never counted; stages the table does not list are not capped
        before, rounds = len(conductor), len(held())
        outcome, _said = handle(driver_at("S5-qa-code-critic-2"), story_run.Refusal(
            "stage_done: STORY BUDGET: QA-9 is past its ceiling", dispatch="S5-qa-code-critic-2", window_findings=window_gaps(5, "k")))
        check("a known row (STORY BUDGET) is the person's by its own row", isinstance(outcome, story_run.Person), repr(outcome))
        outcome, _said = handle(driver_at("S5-qa-code-critic-2"), story_run.Refusal(
            "story_step finish X (exit 2):\nstage already completed", dispatch="S5-qa-code-critic-2", window_findings=window_gaps(5, "k")))
        check_eq("a known `continue` row goes on with no conductor", (outcome, len(conductor) - before), ("continue", 0))
        check_eq("and neither was counted as a round", len(held()), rounds)
        s3 = driver_at("S5-qa-code-critic-2")
        s3.boundary = "S3:S3-qa-test-strategist-1"
        for n in range(3):
            outcome, _said = handle(s3, story_run.Refusal("story_step finish S3-qa-test-strategist-1 (exit 2):\nS3 same findings",
                                                          dispatch="S3-qa-test-strategist-1"))
            check_eq(f"an uncapped stage (S3, queued): call {n + 1} goes to the conductor", outcome, "continue")
        # `gate_repair` hands over through `conductor_round` and never meets the cap
        gate = driver_at("S5-qa-code-critic-2")
        gate.boundary = "gate_A"
        before = len(conductor)
        for _ in range(4):
            with contextlib.redirect_stdout(io.StringIO()):
                outcome = gate.conductor_round(refusal("S5-qa-code-critic-2", g1), "S4")
            check_eq("conductor_round (the gate-entry hand-over) is never capped by a window", outcome, "continue")
        check_eq("four calls, as the gate's own caps say", len(conductor) - before, 4)
    finally:
        harness.cleanup(root)


def s5_window_cap_spares_refusal_rounds() -> None:
    """DC1-21 (t-699): a conductor round over a refusal whose set is NOT the window record's gap lines (`window_findings`
    absent: the controller's own "not receipted" ...) spends its OWN cap of `WINDOW_ROUND_CAP`, never the window's; each
    record names its `cause`. INVARIANTS: the kind comes from the Refusal FIELD the set came from (never from a phrase); a
    factory line beside window gap lines is a `window` round (R1); an absent or unknown `cause` counts as `window` (R4: the
    gate errs only toward counting); `same_set` is judged across both kinds (R6); an empty set is never recorded (R5)."""
    import contextlib
    import io
    import story_run
    scope = ["TP1-15045_TC_002"]
    key = "S5|TP1-15045_TC_002"
    records = {d: {"stage": "S5", "role": "qa-code-critic", "scope": list(scope)} for d in (
        "S5-qa-code-critic-4", "S5-qa-code-critic-5", "S5-qa-code-critic-6")}
    g1, g2, g3 = window_gaps(5, "a"), window_gaps(5, "b"), window_gaps(4, "c")

    def fresh():
        root, task_root, env = seed("QA-9")
        conductor = []

        def driver_at(dispatch: str):
            driver = driver_for(root, env, "QA-9")
            driver.controller_state = lambda: {"dispatches": records}
            driver.conductor = lambda text, *, words="", files=None, words_file=None: conductor.append(text) or {"action": "continue", "did": "stub"}
            driver.boundary = "S5:" + dispatch
            return driver

        def held() -> list:
            path = task_root / "state/driver-state.json"
            if not path.exists():                       # nothing was ever recorded (T8)
                return []
            return (json.loads(path.read_text(encoding="utf-8")).get("window_rounds") or {}).get(key, [])

        def preset(rounds: list) -> None:
            path = task_root / "state/driver-state.json"
            state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            state["window_rounds"] = {key: rounds}
            path.write_text(json.dumps(state), encoding="utf-8")
        return root, conductor, driver_at, held, preset

    def factory(dispatch: str, tail: str, marker: bool = False):
        body = f"story_step: refused - StateConflict: the qa-code-critic window is not receipted: {tail}"
        return story_run.Refusal(f"story_step finish {dispatch} (exit 2):\n{body}" + (f"\n{story_run.REPAIR_MARKER}" if marker else ""),
                                 dispatch=dispatch)

    def window(dispatch: str, gaps: list):
        return story_run.Refusal(f"story_step finish {dispatch} (exit 2):\nstory_step: refused - S5 window record is incomplete: "
                                 "assertion_id is missing", dispatch=dispatch, window_findings=gaps)

    def handle(driver, ref):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                return driver.handle_refusal(ref), out.getvalue()
            except story_run.Person as person:
                return person, out.getvalue()

    def old(n: int) -> list:
        return [{"at": "2026-10-30T03:46:03", "dispatch": "S5-qa-code-critic-4", "set": [f"old set {i}"], "outcome": "to_conductor"}
                for i in range(n)]

    # T1 night replay + T2 window cap AT/BEYOND with refusal rounds around
    root, conductor, driver_at, held, _preset = fresh()
    try:
        outcome, _said = handle(driver_at("S5-qa-code-critic-4"), factory("S5-qa-code-critic-4", "TC-002 a"))
        check_eq("T1: refusal round 1 goes to the conductor", (outcome, len(conductor)), ("continue", 1))
        outcome, said = handle(driver_at("S5-qa-code-critic-4"), factory("S5-qa-code-critic-4", "TC-002 b", marker=True))
        check_eq("T1: refusal round 2 (the night's marker variant) goes on too", (outcome, len(conductor)), ("continue", 2))
        check_in("T1: said as it is", "refusal round 2 of 2 goes to the conductor - the refusal is not about the window's tests; "
                 "the window's own rounds stay 0 of 2", said)
        check_eq("T1: both records name their cause", [r.get("cause") for r in held()], ["refusal", "refusal"])
        outcome, said = handle(driver_at("S5-qa-code-critic-4"), window("S5-qa-code-critic-4", g1))
        check_eq("T1: a window round afterwards finds the window's cap untouched", (outcome, len(conductor)), ("continue", 3))
        check_in("T1: round 1 of 2", "round 1 of 2 goes to the conductor", said)
        outcome, said = handle(driver_at("S5-qa-code-critic-5"), window("S5-qa-code-critic-5", g2))
        check_eq("T2: AT the window cap: round 2 of 2 runs", (outcome, len(conductor)), ("continue", 4))
        check_in("T2: said as it is", "round 2 of 2 goes to the conductor (the findings changed)", said)
        outcome, said = handle(driver_at("S5-qa-code-critic-6"), window("S5-qa-code-critic-6", g3))
        check("T2: BEYOND the window cap: the person", isinstance(outcome, story_run.Person), repr(outcome))
        check_eq("T2: the conductor was not called", len(conductor), 4)
        if isinstance(outcome, story_run.Person):
            check_in("T2: the window sentence", "sent this window back for rework 2 times already", outcome.text)
        check_eq("T2: the window stop carries cause window", held()[-1].get("cause"), "window")
    finally:
        harness.cleanup(root)

    # T3 refusal cap AT/BEYOND, T5 same_set within the refusal kind
    root, conductor, driver_at, held, _preset = fresh()
    try:
        for tail in ("one", "two"):
            outcome, _said = handle(driver_at("S5-qa-code-critic-4"), factory("S5-qa-code-critic-4", tail))
            check_eq(f"T3: refusal set {tail} runs", outcome, "continue")
        outcome, said = handle(driver_at("S5-qa-code-critic-4"), factory("S5-qa-code-critic-4", "three"))
        check("T3: a third distinct refusal set is the person's", isinstance(outcome, story_run.Person), repr(outcome))
        check_eq("T3: the conductor was not called again", len(conductor), 2)
        if isinstance(outcome, story_run.Person):
            check_in("T3: the factory's own sentence", "The factory's own checks refused this window 2 times", outcome.text)
            check_eq("T3: FR-6: the text obeys human-questions.md", rules_broken(outcome.text + "\n\n---\nAnswer: x"), [])
        check_in("T3: said as it is", "2 rounds over refusals that are not about the window's tests are spent - the person is asked", said)
        handle(driver_at("S5-qa-code-critic-4"), factory("S5-qa-code-critic-4", "three"))
        check_eq("T3: the stop is recorded once, with cause refusal", [(r["outcome"], r.get("cause")) for r in held()],
                 [("to_conductor", "refusal"), ("to_conductor", "refusal"), ("cap", "refusal")])
        outcome, said = handle(driver_at("S5-qa-code-critic-4"), factory("S5-qa-code-critic-4", "one"))
        check("T5: the same refusal set as an earlier round is the person's", isinstance(outcome, story_run.Person), repr(outcome))
        if isinstance(outcome, story_run.Person):
            check_in("T5: the same-set sentence", "refused this window again with the same reasons as round", outcome.text)
            check_in("T5/K1: says nothing was reworked, and the door", "Nothing was reworked", outcome.text)
            check_in("T5/K1: the door", "Tell me how to go on", outcome.text)
            check_not_in("T5/K1: no false rework claim on a factory refusal", "does not rework it again", outcome.text)
            check_eq("T5/K1: FR-6: the text obeys human-questions.md", rules_broken(outcome.text + "\n\n---\nAnswer: x"), [])
    finally:
        harness.cleanup(root)

    # T9 (m-2) same_set is judged ACROSS the two kinds, in both orders; the text follows the round's own kind
    shared = [f"the shared line {i}" for i in range(3)]
    root, conductor, driver_at, held, _preset = fresh()
    try:
        outcome, _said = handle(driver_at("S5-qa-code-critic-4"), window("S5-qa-code-critic-4", shared))
        check_eq("T9: a window round with the set runs", (outcome, [r.get("cause") for r in held()]), ("continue", ["window"]))
        factory_same = story_run.Refusal("story_step finish S5-qa-code-critic-4 (exit 2):\n" + "\n".join(shared), dispatch="S5-qa-code-critic-4")
        outcome, _said = handle(driver_at("S5-qa-code-critic-4"), factory_same)
        check("T9: a factory refusal with the window's set is the person's (same_set across kinds)",
              isinstance(outcome, story_run.Person), repr(outcome))
        check_eq("T9: the conductor was not called again", len(conductor), 1)
        if isinstance(outcome, story_run.Person):
            check_in("T9: the factory-kind text", "Nothing was reworked", outcome.text)
        check_eq("T9: the stop is a same_set of kind refusal", [(r["outcome"], r.get("cause")) for r in held()],
                 [("to_conductor", "window"), ("same_set", "refusal")])
    finally:
        harness.cleanup(root)
    root, conductor, driver_at, held, _preset = fresh()
    try:
        factory_first = story_run.Refusal("story_step finish S5-qa-code-critic-4 (exit 2):\n" + "\n".join(shared), dispatch="S5-qa-code-critic-4")
        outcome, _said = handle(driver_at("S5-qa-code-critic-4"), factory_first)
        check_eq("T9: a factory round with the set runs", (outcome, [r.get("cause") for r in held()]), ("continue", ["refusal"]))
        outcome, _said = handle(driver_at("S5-qa-code-critic-4"), window("S5-qa-code-critic-4", shared))
        check("T9: a window round with the factory round's set is the person's (same_set across kinds)",
              isinstance(outcome, story_run.Person), repr(outcome))
        check_eq("T9: the conductor was not called again", len(conductor), 1)
        if isinstance(outcome, story_run.Person):
            check_in("T9: the window-kind text is unchanged", "does not rework it again", outcome.text)
    finally:
        harness.cleanup(root)

    # T4 both in one round: gap lines beside a factory line are a window round (R1)
    root, conductor, driver_at, held, _preset = fresh()
    try:
        both = story_run.Refusal("story_step finish S5-qa-code-critic-4 (exit 2):\nstory_step: refused - StateConflict: the qa-code-critic "
                                 "window is not receipted: x", dispatch="S5-qa-code-critic-4", window_findings=g1)
        outcome, _said = handle(driver_at("S5-qa-code-critic-4"), both)
        check_eq("T4: gap lines beside a factory line: a window round", (outcome, [r.get("cause") for r in held()]), ("continue", ["window"]))
    finally:
        harness.cleanup(root)

    # T6 in-flight records with no cause count as window; T7 an unknown cause counts as window
    root, conductor, driver_at, held, preset = fresh()
    try:
        preset(old(2))
        outcome, _said = handle(driver_at("S5-qa-code-critic-5"), window("S5-qa-code-critic-5", g1))
        check("T6: two records with no cause are the window's: a new window round is the person's", isinstance(outcome, story_run.Person), repr(outcome))
        outcome, _said = handle(driver_at("S5-qa-code-critic-5"), factory("S5-qa-code-critic-5", "fresh"))
        check_eq("T6: a new refusal round finds its own series at 0 of 2", (outcome, len(conductor)), ("continue", 1))
    finally:
        harness.cleanup(root)
    root, conductor, driver_at, held, preset = fresh()
    try:
        rounds = old(2)
        rounds[0]["cause"], rounds[1]["cause"] = "Refusal", None
        preset(rounds)
        outcome, _said = handle(driver_at("S5-qa-code-critic-5"), window("S5-qa-code-critic-5", g1))
        check("T7: an unknown cause (`Refusal`, None) is never free: the window cap is spent", isinstance(outcome, story_run.Person), repr(outcome))
        check_eq("T7: the conductor was not called", len(conductor), 0)
    finally:
        harness.cleanup(root)

    # T8 an empty refusal set is unchanged: the conductor, nothing recorded
    root, conductor, driver_at, held, _preset = fresh()
    try:
        outcome, _said = handle(driver_at("S5-qa-code-critic-4"), story_run.Refusal("story_step finish S5-qa-code-critic-4 (exit 2):",
                                                                                      dispatch="S5-qa-code-critic-4"))
        check_eq("T8: an empty set goes on and records nothing", (outcome, [r for r in held() if "cause" in r]), ("continue", []))
    finally:
        harness.cleanup(root)


def loop_question_flag_repair() -> None:
    # P6: the question file and the `asked` flag are one fact — each half alone is repaired.
    root, _task_root, env = seed("QA-P6")
    try:
        driver = driver_for(root, env, "QA-P6")
        driver.state["asked"] = {"kind": "halt", "stage": "S5", "dispatch": "S5-qa-automator-1"}
        driver.save_state()
        note = driver.reconcile_question()
        check_in("a flag with no question file is cleared, and says so", "has no driver-question.md", note)
        check_eq("and the flag is gone", driver.state.get("asked"), {})
        driver.question_path().parent.mkdir(parents=True, exist_ok=True)
        driver.question_path().write_text("# leftover", encoding="utf-8")
        note = driver.reconcile_question()
        check_in("a question file with no flag is filed as answered", "filed as answered", note)
        check("the leftover is gone", not driver.question_path().is_file())
        check("and it is where an answered question belongs",
              driver.question_path(answered=True).is_file())
        check_eq("with both halves absent there is nothing to repair", driver.reconcile_question(), "")
    finally:
        harness.cleanup(root)


def loop_known_paths() -> None:
    task = "QA-9"
    import story_run
    # --- the paths a role reaches for are given, not guessed (FR-15) -------------------------
    # 129 of run 5's 644 reads missed, and the top of the list was one file tried at two levels:
    # `test-plan.md` 8 times and `work/test-plan.md` 5. Every path here is resolved through the
    # registry the writers use, so the packet cannot carry a spelling the code does not write.
    root, task_root, env = seed(task)
    try:
        driver = driver_for(root, env, task)
        paths = driver.known_paths()
        import artifact_registry
        for key, name in story_run.Driver.KNOWN_ARTIFACTS.items():
            expected = artifact_registry.canonical(task_root, name).resolve()
            # Resolved on both sides: the temp root reaches the driver in its long form and the
            # test in the 8.3 one, and that difference is Windows, not a disagreement.
            check_eq(f"known_paths names {key} where the registry puts it",
                     Path(paths.get(key, "")).resolve(), expected)
        check_in("the human plan is there under its own key", "test-plan.md", paths.get("plan_document", ""))
        check_in("and the machine plan under its own", "work", paths.get("plan", ""))
        check("no path is empty, which is what the controller refuses",
              all(str(value).strip() for value in paths.values()), str(paths))
    finally:
        harness.cleanup(root)


def loop_stand_job_observed() -> None:
    task = "QA-9"
    import story_run
    # --- a recorded stand preparation is observed, never started a second time ----------------
    root, task_root, env = seed(task)
    try:
        import environment_preparation as EP
        driver = driver_for(root, env, task)
        jobs_dir = task_root / "state" / "environment-jobs"
        store = EP.EnvironmentJobs(jobs_dir)
        key = "env:QA-9:local"
        store.write({"idempotency_key": key, "job_id": "job-1", "status": "ready", "phase": "done",
                     "steps": [{"name": "compose-up", "status": "passed"}]})
        receipt = "state/environment-jobs/" + store.path(key).name
        action = {"action": "observe_environment_job", "stage": "S5", "job_id": "job-1",
                  "status": "ready", "receipt_ref": receipt,
                  "reason": "continue the recorded preparation; do not start a duplicate"}
        driver.dispatch_action(action)
        check("a finished stand job is settled and the story goes on", True)

        # The one state code may not settle: the process that owned it is gone, so whether the
        # preparation finished is unknown - and an unknown is never reported as a fact (FR-41).
        store.write({"idempotency_key": key, "job_id": "job-1", "status": "running", "phase": "steps",
                     "coordinator_pid": 4_000_000_000, "coordinator_started_at": "1999-01-01T00:00:00+00:00",
                     "steps": [{"name": "compose-up", "status": "running"}]})
        # C1-1 (P31): the by-hand state goes through the seam. The person's work is an OPTION with a token, the command that
        # settles the job is in the answer block (answer_note), never in the question body (human-questions.md rule 5).
        set_control(root, {"conductor": seam_control("The stand preparation stopped without a result and nobody can say whether "
                                                     "it finished. Say `retry` once the stand is settled, or `stop`.")})
        try:
            driver.dispatch_action(action)
            check("an orphaned stand job reaches the person", False)
        except story_run.Person as person:
            check_eq("as an environment question", person.kind, "environment")
            check("offering retry and stop", {"retry", "stop"} <= set(person.offered), str(person.offered))
            check_not_in("the question body names no command", "reconcile", person.text)
            check_in("the probe door is in the answer note", "environment_preparation.py reconcile", person.answer_note)
            check("and it carries no stand_question, so its answer keeps the final else (t-017 D2)",
                  "stand_question" not in driver.state)
            # F-5: the site's own account reaches the conductor (the stub's captured prompt), before the moves section, and the
            # person's question keeps what the factory did and its record when the conductor's options come back without them
            sent = [e["prompt"] for e in (json.loads(l) for l in (root / "stub-log.jsonl").read_text(encoding="utf-8").splitlines())
                    if e["kind"] == "conductor"][-1]
            for fact in ("the process that owned it is gone", "I did NOT start it again", f"qa-factory/artifacts/{task}/{receipt}",
                         "carries it as `env_blocked`"):
                check_in(f"the conductor was told: {fact}", fact, sent)
            check("and the lead comes before the moves section", sent.index("I did NOT start it again") < sent.index("## Moves open here"))
            check_in("the person's question keeps that it was not started again", "did NOT start it again", person.text)
            check_in("and the record", f"qa-factory/artifacts/{task}/{receipt}", person.text)
        check_in("the job was settled as blocked, not relaunched", '"status": "blocked"',
                 store.path(key).read_text(encoding="utf-8"))
        # No usable answer from the conductor (no options): the fallback question carries the factory's own sentences
        store.write({"idempotency_key": key, "job_id": "job-1", "status": "running", "phase": "steps",
                     "coordinator_pid": 4_000_000_000, "coordinator_started_at": "1999-01-01T00:00:00+00:00",
                     "steps": [{"name": "compose-up", "status": "running"}]})
        set_control(root, {"conductor": {"action": "ask_person", "question": "What now?", "did": "looked"}})
        try:
            driver.dispatch_action(action)
            check("an orphaned stand job with a conductor that gives no options reaches the person", False)
        except story_run.Person as person:
            check_in("the env_blocked way on", "env_blocked", person.text)
            check_in("saying plainly that nothing was restarted", "did NOT start it again", person.text)
            check_not_in("and no command in the body", "reconcile", person.text)
            check_eq("the standing answers are offered", list(person.offered), ["retry", "go on", "stop"])

        # A job record whose identity cannot be read is a refusal that names the file, not a
        # question to a person (FR-1).
        try:
            driver.dispatch_action(dict(action, receipt_ref="state/environment-jobs/nothing.json"))
            check("an unreadable job record refuses", False)
        except story_run.Refusal as refusal:
            check_in("naming the missing identity", "idempotency_key", refusal.text)
            check_in("and the file it looked in", "nothing.json", refusal.text)
    finally:
        harness.cleanup(root)


def loop_window_counters_and_rollover() -> None:
    task = "QA-9"
    import story_run
    # --- the window counters belong to a model session; this driver has none ------------------
    root, task_root, env = seed(task)
    try:
        driver = driver_for(root, env, task)
        before = json.loads((task_root / "state/controller.json").read_text(encoding="utf-8"))
        driver.dispatch_action({"action": "handoff_ready", "revision": before.get("revision", 0),
                                "rollover_pending": True, "reasons": ["model_requests"],
                                "window_model_requests": 400})
        after = json.loads((task_root / "state/controller.json").read_text(encoding="utf-8"))
        check_eq("the driver takes the lease instead of asking who will",
                 (after.get("window_counters") or {}).get("model_requests"), None)
        check_in("and the lease is its own", "driver:",
                 json.dumps((after.get("leases") or {}).get("orchestrator") or {}))

        # Not safe yet: the refusal names what is unsettled and the door for each kind, and the
        # driver does not pretend the rollover is the problem.
        try:
            driver.dispatch_action({"action": "rollover_pending", "revision": after.get("revision", 0),
                                    "reasons": ["context_percent"],
                                    "wait_for": {"ready": False, "running_dispatches": [],
                                                 "running_jobs": [{"path": "execution-jobs/run-7.json",
                                                                   "status": "running"}],
                                                 "unknown_external_writes": [
                                                     {"path": "work/proposals/bug-1.json", "status": "pending"}]}})
            check("a blocked rollover refuses", False)
        except story_run.Refusal as refusal:
            check_in("naming the run job", "execution-jobs/run-7.json", refusal.text)
            check_in("with its door", "run_suite.py --recover", refusal.text)
            check_in("naming the proposal", "work/proposals/bug-1.json", refusal.text)
            check_in("with its door", "external_writes.py --record", refusal.text)
            check_in("and saying whose window it is", "no context window", refusal.text)
    finally:
        harness.cleanup(root)


def halt_texts_are_words() -> None:
    """B-009 part 2: the halt the driver builds out of a role's final message, and the same role
    halting again after the person's answer, reach the person in plain words (TP1-13877: the
    text led with a dispatch id and pasted the whole message). In-process: the role, the handoff
    and `stage_done` are stubbed, the Person the real `run_role` / `resume_role` raise is the subject."""
    import story_run
    task = "QA-9"
    root, task_root, env = seed(task)
    try:
        driver = driver_for(root, env, task)
        digest = ("qa-test-strategist S3 all · halt\nTS-14 · unresolved · the size limit is in neither the "
                  "ticket nor the code\n")
        driver.step = lambda *a, **k: ("dispatched S3-qa-test-strategist-1 (revision 4)\n--- Agent prompt, verbatim ---\n"
                                       "You are qa-test-strategist.\n--- the moment the Agent call returns ---\n")
        driver.system_file = lambda *a, **k: ""
        driver.run_claude = lambda *a, **k: {"result": digest, "session_id": "", "stderr": "", "total_cost_usd": 0.0,
                                                  "is_error": False}
        driver.handoff = lambda role, stage, dispatch, result: digest
        stages_done = []
        real_py = driver.py

        def py(script, *args, **kwargs):
            if script == "stage_done.py":
                stages_done.append(args)
                return 0, ""
            return real_py(script, *args, **kwargs)
        driver.py = py
        try:
            driver.run_role("S3", "qa-test-strategist")
            person = None
        except story_run.Person as raised:
            person = raised
        check("run_role: a halting digest ends in a question", person is not None)
        if person is not None:
            check_eq("run_role: kind, stage and dispatch are unchanged",
                     (person.kind, person.stage, person.dispatch), ("halt", "S3", "S3-qa-test-strategist-1"))
            check_in("run_role: the body names the stage and the role in words",
                     "The plan stage (S3) stopped: the test strategist cannot go on", person.text)
            check_in("run_role: and the row's own reason", "- TS-14 — the size limit is in neither the ticket nor the code",
                     person.text)
            check_not_in_text("run_role: no dispatch id and no raw digest in the body",
                              ("S3-qa-test-strategist-1", "qa-test-strategist S3 all", "· halt"), person.text)
            check_eq("run_role: the raw digest is the details", person.details, digest.strip())
            driver.ask(person)
            shown = (task_root / "state/driver-question.md").read_text(encoding="utf-8")
            check_eq("run_role: the question obeys human-questions.md", rules_broken(shown), [])
            check_eq("run_role: the head stays six lines, so the re-raise gets the text back",
                     shown.split("\n", 6)[-1].split("\n\n---\nAnswer:")[0], person.text)
            journal = [json.loads(line) for line in
                       (task_root / "state/driver-questions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
            check_eq("run_role: the halt is journalled with no problem", journal[-1]["problems"], [])
        driver.state["sessions"] = {"S3-qa-test-strategist-1": "sess-1"}
        driver.state["pending_words"] = {"S3-qa-test-strategist-1": "go on"}
        try:
            driver.resume_role("S3", "qa-test-strategist", "S3-qa-test-strategist-1", "go on")
            again = None
        except story_run.Person as raised:
            again = raised
        check("resume_role: a role that halts again ends in a question", again is not None)
        if again is not None:
            check_in("resume_role: `stopped again`, in words",
                     "The plan stage (S3) stopped again: the test strategist cannot go on", again.text)
            check_eq("resume_role: the same kind, stage and dispatch",
                     (again.kind, again.stage, again.dispatch), ("halt", "S3", "S3-qa-test-strategist-1"))
            check_eq("resume_role: the raw digest is the details", again.details, digest.strip())
            check_eq("resume_role: the text obeys the rules", rules_broken(again.text + "\n\n---\nAnswer: x"), [])
        # An unreadable digest is not guessed at: the person is told it gave no reason.
        driver.handoff = lambda role, stage, dispatch, result: "qa-test-strategist S3 all · halt"
        try:
            driver.run_role("S3", "qa-test-strategist")
            bare = None
        except story_run.Person as raised:
            bare = raised
        check_in("a halt with no rows says it gave no reason",
                 "It gave no reason in its report; its own words are in the file named below.",
                 bare.text if bare else "")
    finally:
        harness.cleanup(root)


def main() -> None:
    run_scenarios([], [
        s5_finish_unresolved_pair,
        s5_window_record_gaps_become_the_pair,
        s5_window_gap_other_gaps_refuse_the_pair,
        s5_window_gap_unconfirmed_claim_is_no_pair,
        s5_window_note_says_what_is_true,
        s5_window_rounds_are_capped,
        s5_window_cap_spares_refusal_rounds,
        loop_waiver_and_journal_shapes,
        loop_question_flag_repair,
        loop_known_paths,
        loop_stand_job_observed,
        loop_window_counters_and_rollover,
        halt_texts_are_words,
    ])
    harness.finish("test_story_run_loop_b_loop")


# split: runner piece 1
if __name__ == "__main__":
    main()
