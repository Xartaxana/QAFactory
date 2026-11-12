#!/usr/bin/env python3
"""B-20 (t-1988 N1, N2): a stage judged by its CONSUMER (S6 by the failure analyst, S7 by the doc scribe) closes from wherever the driver stands.

N1: the read-only `where` (`story_step._next`) reads the pipeline exactly as `next` does, so a standing accept record ends "S<n> awaits" for both.
    Six cases: S6 row with and without the record, S7 row with and without it, a record for an EARLIER dispatch, a `reject` record, an
    unreadable `pipeline.json` (the stated direction: the consumer's stage, never a pass).
N2: `Driver.consumer_word_step` records the person's `stage acceptance` word for a stage that awaits its consumer, from any position, through the
    one writer (`stage_done.py --acceptance`), and files the pass as a finding. Six cases plus F2 (a word written BEFORE the author's dispatch was
    accepted counts for nothing) and the 500-character cut AT and BEYOND its limit.

Fast: the real controller on a temp story, no subprocess driver. Runs under pytest and as `python -B scripts/tests/test_consumer_close_route.py`.
"""
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check_eq, cleanup, finish  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import acceptance as A  # noqa: E402
import hooklib  # noqa: E402
import story_run as SR  # noqa: E402
import story_step  # noqa: E402
import test_stage_acceptance_consumer as C  # noqa: E402  (Rig, s7_world, put_pipeline, s7_record, reject_record, CONSUMER, SCRIBE, ANALYST_ID)

RUNNER_1 = "S6-qa-runner-1"
FUTURE = lambda: (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")      # noqa: E731  after any acceptance in this run
PAST = "2020-01-01T00:00:00Z"
PHRASE = A.STAGE_ACCEPTANCE_PHRASE


def eq(name, got, want):
    assert check_eq(name, got, want), f"{name}: expected {want!r}, got {got!r}"


class world:
    """`with world(kind) as rig`: S6 (`s6`: the runner stopped awaiting the analyst) or S7 (`s7`: the analyst's triage awaits the scribe, by the marker)."""

    def __init__(self, kind, dispositions=None):
        self.kind, self.dispositions = kind, dispositions

    def __enter__(self):
        self.old = hooklib._PROJECT_ROOT_CACHE
        if self.kind == "s6":
            self.rig = C.Rig(self.dispositions or ["automate"])
            self.rig.author(RUNNER_1, "automation", ["TC-1"])
        else:
            self.rig = C.s7_world()
            C.put_pipeline(self.rig, dict(self.rig.pipeline(), acceptance_awaits={"S7": C.ANALYST_ID}))
        hooklib._PROJECT_ROOT_CACHE = self.rig.root
        return self.rig

    def __exit__(self, *exc):
        hooklib._PROJECT_ROOT_CACHE = self.old
        cleanup(self.rig.root)


def stages(rig):
    """(where's stage, next's stage): the two readers of "what is next" that the driver and the controller own."""
    return story_step._next(rig.c, read_only=True).get("stage"), rig.c.next_action().get("stage")


def accept_record(kind, reviewed):
    return dict(stage="S6", role="qa-runner", acceptor=C.CONSUMER, reviewed_dispatch=reviewed, verdict="accept", failure_class=None, quote="",
                witness_paths=[], at="t") if kind == "s6" else C.s7_record("accept", reviewed=reviewed)


# --- N1 -------------------------------------------------------------------------------------------------------------------------------------
def test_n1_s6_record_stands_where_equals_next():
    with world("s6") as rig:
        eq("N1.2 S6 awaits, no record: both name the consumer's stage S7", stages(rig), ("S7", "S7"))
        rig.append_record(accept_record("s6", RUNNER_1))
        eq("N1.1 S6 awaits, the accept record stands: both name S6 (the author's stage, which closes)", stages(rig), ("S6", "S6"))


def test_n1_s7_row():
    with world("s7") as rig:
        eq("N1.3 S7 awaits the scribe, no record: both name S8", stages(rig), ("S8", "S8"))
        rig.append_record(accept_record("s7", C.ANALYST_ID))
        eq("N1.3 ... the scribe's accept record stands: both name S7", stages(rig), ("S7", "S7"))


def test_n1_earlier_dispatch_record_does_not_count():
    with world("s6", C.MB.MIXED_7) as rig:
        rig.author("S6-qa-runner-2", "manual", ["TC-2", "TC-3", "TC-4", "TC-5", "TC-6"])
        rig.append_record(accept_record("s6", RUNNER_1))
        eq("N1.4 the awaited dispatch is the LAST one", A.awaits_acceptance(rig.c.state(), "S6", rig.pipeline()), "S6-qa-runner-2")
        eq("N1.4 a record for an EARLIER dispatch of the runner: both still name the consumer's stage", stages(rig), ("S7", "S7"))


def test_n1_reject_record_does_not_count():
    with world("s6") as rig:
        rig.append_record(C.reject_record("S6", "qa-runner", C.CONSUMER, RUNNER_1))
        eq("N1.5 a reject record: both name the consumer's stage", stages(rig), ("S7", "S7"))
    with world("s7") as rig:
        rig.append_record(C.reject_record("S7", C.CONSUMER, C.SCRIBE, C.ANALYST_ID))
        eq("N1.5 ... the S7 row too", stages(rig), ("S8", "S8"))


def test_n1_unreadable_pipeline_names_the_consumer_stage():
    with world("s6") as rig:
        rig.append_record(accept_record("s6", RUNNER_1))
        (rig.root / "pipeline.json").write_text("{ not json", encoding="utf-8")
        eq("N1.6 an unreadable pipeline.json: both name the consumer's stage, no crash, no pass of S6", stages(rig), ("S7", "S7"))
    with world("s6") as rig:
        (rig.root / "pipeline.json").unlink()
        eq("N1.6 ... an absent pipeline.json: the same", stages(rig), ("S7", "S7"))


# --- N2 -------------------------------------------------------------------------------------------------------------------------------------
def driver_of(rig):
    d = rig.d
    d.project, d.task = rig.root, "QA-9"
    for name in ("consumer_word_step", "owe_row"):
        setattr(d, name, types.MethodType(getattr(SR.Driver, name), d))
    return d


def say(rig, stage, words, at):
    pipeline = rig.pipeline()
    pipeline.setdefault("stage_overrides", []).append({"stage": stage, "match": PHRASE, "decision": words, "at": at, "by": "human"})
    C.put_pipeline(rig, pipeline)


def written(rig):
    """What the step wrote: the acceptance records, and the commands the driver ran."""
    return (rig.pipeline().get("acceptance") or {}), list(rig.cmds)


def findings(rig):
    return [c for c in rig.cmds if c[0] == "project_decisions.py"]


def test_n2_s6_word_from_s7_position():
    with world("s6") as rig:
        d = driver_of(rig)
        say(rig, "S6", "I accept the run as it is", FUTURE())
        eq("N2.1 before the step: where names S7 (the driver 'is at S7')", stages(rig), ("S7", "S7"))
        eq("N2.1 the step records the pass", d.consumer_word_step(), True)
        rec = A.stage_acceptance(rig.pipeline(), "S6")
        eq("N2.1 a driver accept of the runner's dispatch, by the person's word",
           (rec["acceptor"], rec["verdict"], rec["reviewed_dispatch"], rec["quote"]), (A.DRIVER_ACCEPTOR, "accept", RUNNER_1, "by: person - I accept the run as it is"))
        eq("N2.1 where names S6 now", stages(rig), ("S6", "S6"))
        eq("N2.1 the record is written by the one writer (stage_done.py --acceptance) and filed as a finding",
           ([c[0] for c in rig.cmds], len(findings(rig))), (["stage_done.py", "project_decisions.py"], 1))


def test_n2_s7_word_from_any_position():
    with world("s7") as rig:
        d = driver_of(rig)
        say(rig, "S7", "the triage is fine", FUTURE())
        eq("N2.2 S7 awaits the scribe: where names S8", stages(rig), ("S8", "S8"))
        eq("N2.2 the step records the pass", d.consumer_word_step(), True)
        eq("N2.2 where names S7 now (it closes there)", stages(rig), ("S7", "S7"))
        eq("N2.2 the record names the analyst's dispatch", A.stage_acceptance(rig.pipeline(), "S7")["reviewed_dispatch"], C.ANALYST_ID)


def test_n2_no_word_writes_nothing():
    for kind in ("s6", "s7"):
        with world(kind) as rig:
            d = driver_of(rig)
            before = rig.pipeline()
            eq(f"N2.3 {kind}: no waiver: False", d.consumer_word_step(), False)
            eq(f"N2.3 {kind}: ... nothing written", (rig.pipeline(), rig.cmds), (before, []))
    old = hooklib._PROJECT_ROOT_CACHE
    rig = C.Rig(["automate"])
    try:
        hooklib._PROJECT_ROOT_CACHE = rig.root
        d = driver_of(rig)
        (rig.root / "pipeline.json").unlink()
        d.pipeline = lambda: {}                 # the driver's `_read_json` of an absent file
        eq("N2.3 no stage awaits (no author ran) and no pipeline: False, nothing written", (d.consumer_word_step(), rig.cmds), (False, []))
    finally:
        hooklib._PROJECT_ROOT_CACHE = old
        cleanup(rig.root)


def test_n2_running_dispatch_is_not_accepted_by_a_word():
    with world("s6") as rig:
        d = driver_of(rig)
        rig.c.apply("dispatch", {"id": "S6-qa-runner-2", "stage": "S6", "role": "qa-runner", "execution_kind": "automation", "scope": ["TC-1"],
                                 "input_hash": "s6b", "budget": {}, "known_paths": {}, "idempotency_key": "d-r2", "rework_of": RUNNER_1,
                                 "repair_cause": "question_answer", "reason": "the person's words"})
        eq("N2.4 a newer runner dispatch is running: nothing awaits", A.awaits_acceptance(rig.c.state(), "S6", rig.pipeline()), "")
        say(rig, "S6", "accept", FUTURE())
        before = rig.pipeline()
        eq("N2.4 the word does not accept the running dispatch: False, nothing written", (d.consumer_word_step(), rig.pipeline(), rig.cmds), (False, before, []))


def test_n2_two_passes_one_finding():
    with world("s6") as rig:
        d = driver_of(rig)
        say(rig, "S6", "accept it", FUTURE())
        eq("N2.5 first pass", d.consumer_word_step(), True)
        eq("N2.5 second step: the record stands, nothing awaits: False", d.consumer_word_step(), False)
        eq("N2.5 a direct second pass for the same author: True (the record stands) and no second finding", (d.consumer_person_pass("S6", RUNNER_1), len(findings(rig))), (True, 1))
        key = findings(rig)[0][findings(rig)[0].index("--idempotency-key") + 1]
        eq("N2.5 the finding carries the idempotency key of stage and author dispatch", key, f"stage-acceptance-pass:QA-9:S6:{RUNNER_1}")


def test_n2_finding_quotes_the_words_cut_at_500():
    for n, label in ((500, "AT"), (701, "beyond")):
        words = ("ab" * 400)[:n]
        with world("s6") as rig:
            d = driver_of(rig)
            say(rig, "S6", words, FUTURE())
            eq(f"N2.6 {label} the limit ({n}): the pass is recorded", d.consumer_word_step(), True)
            row = findings(rig)[0]
            essence, quote = row[row.index("--essence") + 1], A.stage_acceptance(rig.pipeline(), "S6")["quote"]
            eq(f"N2.6 {label} ({n}): the finding quotes the first {min(n, 500)} characters", essence.endswith(": " + words[:500]), True)
            eq(f"N2.6 {label} ({n}): ... and not a character more", words[:501] in essence if n > 500 else False, False)
            eq(f"N2.6 {label} ({n}): the record's quote is cut the same way", quote, "by: person - " + words[:500])


def test_n2_f2_a_word_before_the_acceptance_counts_for_nothing():
    with world("s6") as rig:
        d = driver_of(rig)
        say(rig, "S6", "accept whatever comes", PAST)
        before = rig.pipeline()
        eq("N2.F2 a word written before the author's dispatch was accepted: False, nothing written", (d.consumer_word_step(), rig.pipeline(), rig.cmds), (False, before, []))


def refused(call):
    try:
        call()
    except SR.Refusal as exc:
        return str(exc)
    return ""


def test_f1_an_old_word_is_honoured_at_no_site():
    """B-20 F1 (FR-4): the age rule lives in `consumer_person_pass`, so EVERY site that consults a word applies it - the close sites of S6
    and S7 (`consumer_need_record`), the scribe wait, the settle of a reject. A word dated before the acceptance passes nothing, at each."""
    for kind, stage, author in (("s6", "S6", RUNNER_1), ("s7", "S7", C.ANALYST_ID)):
        with world(kind) as rig:
            d = driver_of(rig)
            say(rig, stage, "accept whatever comes", PAST)
            before = rig.pipeline()
            eq(f"F1 {stage} the word step: False", d.consumer_word_step(), False)
            text = refused(lambda: d.consumer_need_record(stage, "close_site"))
            assert "no accept record" in text, f"F1 {stage} the close site still refuses an old word, got {text!r}"
            eq(f"F1 {stage} the direct pass: False", d.consumer_person_pass(stage, author), False)
            eq(f"F1 {stage} ... nothing written by any of them", (rig.pipeline(), rig.cmds), (before, []))
    with world("s7") as rig:
        d = driver_of(rig)
        say(rig, "S7", "accept whatever comes", PAST)
        before = rig.pipeline()
        eq("F1 S7 the scribe wait is not passed by an old word: still waiting", SR.Driver.s7_await_scribe(d), True)
        eq("F1 S7 ... and no accept record written", rig.pipeline().get("acceptance"), before.get("acceptance"))
    with world("s7") as rig:
        d = driver_of(rig)
        rig.append_record(C.reject_record("S7", C.CONSUMER, C.SCRIBE, C.ANALYST_ID))
        say(rig, "S7", "go on", PAST)
        eq("F1 S7 an old word does not take the scribe's reject as the accept (consumer_settled's call)",
           (d.consumer_person_pass("S7", C.ANALYST_ID), findings(rig)), (False, []))


def test_f1_a_later_word_is_honoured_at_the_close_site_and_an_answer_is_exempt():
    with world("s6") as rig:
        d = driver_of(rig)
        say(rig, "S6", "accept it", FUTURE())
        d.consumer_need_record("S6", "close_site")
        eq("F1 control: a word later than the acceptance passes the close site", A.stage_acceptance(rig.pipeline(), "S6")["quote"], "by: person - accept it")
    with world("s6") as rig:
        d = driver_of(rig)
        eq("F1 `answer=` is a fresh word: no age asked", d.consumer_person_pass("S6", RUNNER_1, "go on"), True)
    with world("s6") as rig:
        d = driver_of(rig)
        say(rig, "S6", "accept it", "not a time")
        eq("F1 a word whose time cannot be read is not honoured", d.consumer_person_pass("S6", RUNNER_1), False)
        eq("F1 an acceptance time that cannot be read is empty (no event for the dispatch)", d.accepted_at("S6-nobody-9"), "")


def test_f2_dry_run_records_nothing():
    with world("s6") as rig:
        d = driver_of(rig)
        d.dry = True
        say(rig, "S6", "accept it", FUTURE())
        before = rig.pipeline()
        eq("F2 --dry-run: a live word is said, not recorded: False, no command, no record", (d.consumer_word_step(), rig.pipeline(), rig.cmds), (False, before, []))


def test_f5_a_refused_recording_carries_the_whole_pass_as_its_retry():
    with world("s6") as rig:
        d = driver_of(rig)
        say(rig, "S6", "accept it", FUTURE())
        real = d.py
        d.py = lambda *a, **k: (_ for _ in ()).throw(SR.Refusal("stage_done refused")) if a and a[0] == "stage_done.py" else real(*a, **k)
        try:
            d.consumer_person_pass("S6", RUNNER_1)
            raise AssertionError("F5 the refusal must be raised")
        except SR.Refusal as refusal:
            retry = refusal.retry
        assert retry, "F5 the refusal carries a retry"
        eq("F5 nothing filed while the recording is refused", findings(rig), [])
        d.py = real
        eq("F5 the retry runs the whole pass: recorded", retry(), True)
        eq("F5 ... and the finding is filed (P13), once", len(findings(rig)), 1)


def main():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for _name, fn in tests:
        fn()
    finish("test_consumer_close_route")


if __name__ == "__main__":
    main()
