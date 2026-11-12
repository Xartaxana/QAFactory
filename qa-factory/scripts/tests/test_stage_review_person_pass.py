"""F3 of t-1936 (B-6): a person's `go on` over the exhausted stage review has a reader.

Arm B recorded `{"stage": "S2", "match": "the verdict word of the stage critic is unreadable", "decision": "go on"}` and the driver kept asking,
because `stage_review_exhausted` never read `stage_overrides`. The seam now builds the `stage acceptance: <text>` line, consults the pass
(`Driver.person_pass`, through `waiver.split_overridden`, the ONE reader) before the conductor and once more after it, honours only a word
recorded AFTER the critic dispatch started, and files one finding. The driver pieces run on a stub `self`; the controller's dispatch clock is a
stand-in (`FakeController`), the dispatch and writer commands are recorded.
"""
import calendar
import copy
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import acceptance  # noqa: E402
import controller  # noqa: E402
import story_run as SR  # noqa: E402

STAGE, AUTHOR_ROLE, AUTHOR, CRITIC = "S2", "qa-requirements-tester", "dA", "dC"
UNREADABLE = "the verdict word of the stage critic is unreadable"
LINE = f"{acceptance.STAGE_ACCEPTANCE_PHRASE}: {UNREADABLE}"
START = calendar.timegm((2026, 11, 5, 1, 0, 0))            # the stage critic's dispatch was journalled at 01:00:00 UTC
BEFORE, AFTER = "2026-11-05T00:50:00+00:00", "2026-11-05T01:15:32+00:00"
# The arm B record (mybooks-stand tr-arm-b, LOCAL-1 pipeline.json `stage_overrides`), copied as DATA; only `at` of the S2 entry is the original.
ARM_B_OVERRIDES = [
    {"stage": "S2", "match": UNREADABLE, "decision": "go on", "at": AFTER, "by": "human"},
    {"stage": "S5", "match": "Q1", "decision": "accept - the person wrote: open_questions-1: accept Q1 was answered at S2 (a)",
     "at": "2026-11-05T02:38:30+00:00", "by": "human"},
]


class FakeController:
    starts = {CRITIC: START}

    def __init__(self, *_a, **_k):
        pass

    def _dispatch_starts(self):
        return dict(FakeController.starts)


@pytest.fixture(autouse=True)
def fake_controller(monkeypatch):
    monkeypatch.setattr(controller, "Controller", FakeController)
    monkeypatch.setattr(FakeController, "starts", {CRITIC: START})


class Rig:
    """A driver (`SR.Driver` pieces bound to a namespace) over a dict pipeline; `no_move`, `py` and `owe_row` are recorded stand-ins."""

    def __init__(self, overrides=None, author=AUTHOR, during=None):
        self.pipe = {"ticket": "QA-9", "stage_overrides": copy.deepcopy(overrides) if overrides is not None else []}
        self.calls, self.during = [], during
        state = {"dispatches": {author: {"id": author, "stage": STAGE, "role": AUTHOR_ROLE, "status": "accepted"}} if author else {}}
        d = self.d = SimpleNamespace(task="QA-9", task_root=Path("."), project=Path("."), stages=lambda: {STAGE: {"outputs": []}},
                                     pipeline=lambda: self.pipe, controller_state=lambda: state)
        d.no_move = self.no_move
        d.py = self.py
        d.owe_row = lambda *a, **k: self.calls.append(("owe", a, k))
        d.accepted_at = lambda author: "2026-11-05T00:55:00Z"       # B-20 F1: the age rule of `consumer_person_pass` (BEFORE is older, AFTER later)
        for name in ("stage_review_exhausted", "person_pass", "consumer_person_pass"):
            setattr(d, name, types.MethodType(getattr(SR.Driver, name), d))

    def no_move(self, state):
        self.calls.append(("seam", state))
        if self.during:
            self.during(self.pipe)
        return "SEAM"

    def py(self, script, *args, **kw):
        self.calls.append(("py", script, args))
        if script == "stage_done.py" and "--acceptor" in args:
            at = lambda key: args[args.index(key) + 1]
            self.pipe.setdefault("acceptance", {}).setdefault(at("--stage"), []).append(
                {"stage": at("--stage"), "verdict": "accept", "acceptor": at("--acceptor"), "quote": at("--quote"),
                 "reviewed_dispatch": at("--acceptance").split("/")[-1][:-5]})
        return 0, ""

    def run(self, record=None, unreadable=True, text=""):
        return self.d.stage_review_exhausted(STAGE, AUTHOR_ROLE, CRITIC, record, f"work/handoffs/{CRITIC}.yaml", unreadable=unreadable, text=text)

    def of(self, kind):
        return [c for c in self.calls if c[0] == kind]

    def accepts(self):
        return [c for c in self.of("py") if c[1] == "stage_done.py"]


def flags(args) -> dict:
    """`{--flag: value}` of a command's arguments."""
    return {a: args[i + 1] for i, a in enumerate(args[:-1]) if str(a).startswith("--")}


def test_live_waiver_closes_before_conductor(capsys):
    rig = Rig(ARM_B_OVERRIDES)
    assert rig.run() is None
    assert rig.of("seam") == []                                  # the conductor is never called: the person has spoken
    (_, _, args), = rig.accepts()
    assert args[args.index("--acceptor") + 1] == acceptance.DRIVER_ACCEPTOR
    assert args[args.index("--acceptance") + 1] == f"work/handoffs/{AUTHOR}.yaml"
    assert args[args.index("--quote") + 1] == "by: person - go on"
    assert "a person's word passes the acceptance" in capsys.readouterr().out
    assert acceptance.accepted_for(rig.pipe, STAGE, AUTHOR, acceptor=acceptance.DRIVER_ACCEPTOR)


def test_arm_b_record_closes_s2_and_the_other_stage_word_does_not_count():
    rig = Rig(ARM_B_OVERRIDES)
    assert rig.run() is None
    assert len(rig.accepts()) == 1 and rig.pipe["stage_overrides"] == ARM_B_OVERRIDES      # the record is read, never rewritten


def test_waiver_recorded_during_seam_closes_after():
    def person_speaks(pipe):
        pipe["stage_overrides"].append({"stage": STAGE, "match": UNREADABLE, "decision": "go on", "at": AFTER, "by": "human"})
    rig = Rig([], during=person_speaks)
    assert rig.run() is None
    assert len(rig.of("seam")) == 1 and len(rig.accepts()) == 1      # the conductor asked once; the person's word then closed the stage
    assert len(rig.of("owe")) == 1


def test_older_waiver_does_not_pass_later_review():
    rig = Rig([dict(ARM_B_OVERRIDES[0], at=BEFORE)])
    assert rig.run() == "SEAM"
    assert rig.accepts() == [] and len(rig.of("seam")) == 2          # the conductor's question and the priced fallback, as today
    assert rig.of("owe") == []


@pytest.mark.parametrize("at", ["not a time", "", None, 5, True, "2026-11-05T01:15:32", "2026-13-45T99:00:00+00:00"],
                         ids=["words", "empty", "absent", "number", "bool", "no-zone", "impossible"])
def test_unreadable_at_not_honoured(at):
    entry = dict(ARM_B_OVERRIDES[0])
    if at is None:
        entry.pop("at")
    else:
        entry["at"] = at
    rig = Rig([entry])
    assert rig.run() == "SEAM" and rig.accepts() == []


def test_equal_second_is_not_later():
    rig = Rig([dict(ARM_B_OVERRIDES[0], at="2026-11-05T01:00:00+00:00")])
    assert rig.run() == "SEAM" and rig.accepts() == []


def test_no_dispatch_start_no_pass():
    for starts in ({}, {CRITIC: None}, {CRITIC: "x"}, {"other": START}):
        FakeController.starts = starts
        rig = Rig(ARM_B_OVERRIDES)
        assert rig.run() == "SEAM", starts
        assert rig.accepts() == [] and rig.of("owe") == []


def test_unreadable_controller_is_no_pass(monkeypatch):
    class Broken:
        def __init__(self, *_a, **_k):
            raise OSError("no event store")
    monkeypatch.setattr(controller, "Controller", Broken)
    rig = Rig(ARM_B_OVERRIDES)
    assert rig.run() == "SEAM" and rig.accepts() == []


@pytest.mark.parametrize("entries", [
    [dict(ARM_B_OVERRIDES[0], revoked_at=AFTER)],
    [dict(ARM_B_OVERRIDES[0], match="*", revoked_at=AFTER)],
    [dict(ARM_B_OVERRIDES[0], decision="")],
    [dict(ARM_B_OVERRIDES[0], match="<what the stage critic said>")],
    [dict(ARM_B_OVERRIDES[0], match="the verdict word of the case critic is unreadable")],
    "absent", "empty-list"], ids=["revoked", "revoked-star", "no-decision", "placeholder", "other-words", "no-key", "empty"])
def test_revoked_waiver_passes_nothing(entries):
    rig = Rig([])
    if entries == "absent":
        del rig.pipe["stage_overrides"]
    elif entries != "empty-list":
        rig.pipe["stage_overrides"] = entries
    assert rig.run() == "SEAM" and rig.accepts() == []


def test_star_passes_but_only_this_stage():
    rig = Rig([dict(ARM_B_OVERRIDES[0], match="*")])
    assert rig.run() is None                                     # existing semantics of `*`, kept
    rig = Rig([dict(ARM_B_OVERRIDES[0], match="*", stage="S3")])
    assert rig.run() == "SEAM" and rig.accepts() == []


def test_other_stage_waiver_ignored():
    rig = Rig([dict(ARM_B_OVERRIDES[0], stage="S3")])
    assert rig.run() == "SEAM" and rig.accepts() == []


def test_no_author_no_pass():
    rig = Rig(ARM_B_OVERRIDES, author="")
    assert rig.run() == "SEAM"
    assert rig.accepts() == [] and rig.of("owe") == []           # no accept record without an author dispatch
    assert not rig.d.person_pass(STAGE, "", LINE, since=AFTER)


def test_line_carries_stage_acceptance_phrase():
    rig = Rig([])
    rig.run()
    first = rig.of("seam")[0][1]
    assert first["lines"] == [LINE] and LINE.startswith("stage acceptance: ")
    rig = Rig([])
    rig.run(record={"quote": "TC-3 has no result row"}, unreadable=False)
    assert rig.of("seam")[0][1]["lines"] == [f"{acceptance.STAGE_ACCEPTANCE_PHRASE}: the stage critic rejected S2 and no repair round is "
                                              "left: TC-3 has no result row"]


def test_readable_reject_on_last_round_is_passed_with_the_critics_verdict_on_record():
    rig = Rig([dict(ARM_B_OVERRIDES[0], match="no repair round is left")])
    assert rig.run(record={"quote": "TC-3 has no result row"}, unreadable=False) is None
    assert rig.of("seam") == []
    assert len(rig.accepts()) == 1 and len(rig.of("owe")) == 1


def test_pass_files_one_finding_idempotent():
    rig = Rig(ARM_B_OVERRIDES)
    rig.run()
    rig.run()
    owed = [c for c in rig.of("owe")]
    assert len(owed) == 2                                        # two passes (the second re-ran a closed review), ONE key
    args, kw = owed[0][1], owed[0][2]
    pairs = flags(args)
    assert args[0] == "project_decisions.py" and "add-finding" in args
    assert pairs["--idempotency-key"] == f"stage-review-pass:QA-9:{STAGE}:{CRITIC}"
    assert pairs["--essence"] == f"{STAGE} closed on the person's word over: {LINE}"
    assert pairs["--scope"] == "local-calibration"
    assert "go on" in pairs["--witness"] and AFTER in pairs["--witness"]
    assert kw["stage"] == STAGE
    assert {flags(c[1])["--idempotency-key"] for c in owed} == {pairs["--idempotency-key"]}


def test_finding_names_the_critics_quote_on_a_readable_reject():
    rig = Rig([dict(ARM_B_OVERRIDES[0], match="no repair round is left")])
    rig.run(record={"quote": "TC-3 has no result row"}, unreadable=False)
    args = rig.of("owe")[0][1]
    assert "TC-3 has no result row" in flags(args)["--essence"]


def test_consumer_person_pass_unchanged():
    # (a) a live waiver LATER than the author's acceptance passes (B-20 F1: the age rule is the pass's own, at every site); an older one does not
    line = f"{acceptance.STAGE_ACCEPTANCE_PHRASE}: no accept record stands for {AUTHOR}"
    old = Rig([{"stage": STAGE, "match": line, "decision": "go on", "at": BEFORE, "by": "human"}])
    assert old.d.consumer_person_pass(STAGE, AUTHOR) is False and old.accepts() == []
    rig = Rig([{"stage": STAGE, "match": line, "decision": "go on", "at": AFTER, "by": "human"}])
    assert rig.d.consumer_person_pass(STAGE, AUTHOR) is True
    (_, _, args), = rig.accepts()
    assert args[args.index("--quote") + 1] == "by: person - go on" and len(rig.of("owe")) == 1 and rig.of("seam") == []     # B-20 N2: the pass files its finding (P13)
    # (b) an answer's words pass with no waiver at all
    rig = Rig([])
    assert rig.d.consumer_person_pass(STAGE, AUTHOR, "  accept   it ") is True
    assert "by: person - accept it" in rig.accepts()[0][2]
    # (c) nothing passes -> False, nothing written; no author -> False
    rig = Rig([])
    assert rig.d.consumer_person_pass(STAGE, AUTHOR) is False and rig.accepts() == []
    assert rig.d.consumer_person_pass(STAGE, "") is False
    # (d) an accept record that stands already -> True, no writer call
    rig = Rig([])
    rig.pipe["acceptance"] = {STAGE: [{"verdict": "accept", "reviewed_dispatch": AUTHOR, "acceptor": "x"}]}
    assert rig.d.consumer_person_pass(STAGE, AUTHOR) is True and rig.accepts() == []


if __name__ == "__main__": raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
