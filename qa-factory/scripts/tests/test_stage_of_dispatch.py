#!/usr/bin/env python3
"""The stage of a role is the stage of its live dispatch (spec t-1765 X2-2b; AR-13, AR-28).

`stage_guard.stage_of_dispatch` is PURE (the stage is an argument); `exit_gate._stage_id` and `check_dispatch` feed it.
The real stages.json lists every role on one stage, so every case below runs on a SYNTHETIC model in which `qa-critic`
stands on S2, S3 and S4 (the shape B4 gives the case critic). Per caller: `_identity` (:241), `next_hint`,
`required_outputs_errors`, `scoped_errors`, `_stage_id`, `check_dispatch`, and the selftest/home-stage reading
(`stage_of_role`).

Keys: R1 the resolution roads of `stage_of_dispatch` (held, one stage, one running, not established, awkward inputs),
R2 `stages_of_role` / `stage_of_role`, R3 one test per exit_gate caller, R4 no cycle, R5 the dispatch guard (and what it
refused before it still refuses).
"""
import contextlib
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import exit_gate as EG  # noqa: E402
import stage_guard as SG  # noqa: E402

MODEL = {"stages": [
    {"id": "S1", "name": "scout", "roles": ["qa-scout"], "required_outputs": ["work/s1.txt"], "outputs": ["s1.txt"]},
    {"id": "S2", "name": "second", "roles": ["qa-a", "qa-critic"], "required_outputs": ["work/s2.txt"], "outputs": ["s2.txt"]},
    {"id": "S3", "name": "third", "roles": ["qa-b", "qa-critic"], "required_outputs": ["work/s3.txt"], "outputs": ["s3.txt"]},
    {"id": "S4", "name": "fourth", "roles": ["qa-c", "qa-critic"], "required_outputs": ["work/s4.txt"], "outputs": ["s4.txt"]},
]}


def run(row: dict) -> dict:
    return dict({"status": "running", "role": "qa-critic", "stage": "S2"}, **row)


def stage_id(result):
    return (result or {}).get("id")


# --- R1: the resolution roads -----------------------------------------------------------------------------------------

def test_held_stage_wins_when_the_role_stands_there():
    assert stage_id(SG.stage_of_dispatch(MODEL, "qa-critic", held="S3")) == "S3"
    # held beats a running dispatch of another stage
    assert stage_id(SG.stage_of_dispatch(MODEL, "qa-critic", held="S4", dispatches={"d": run({"stage": "S2"})})) == "S4"


def test_held_stage_the_role_is_not_on_is_skipped():
    assert SG.stage_of_dispatch(MODEL, "qa-critic", held="S1") is None
    assert stage_id(SG.stage_of_dispatch(MODEL, "qa-critic", held="S1", dispatches=[run({"stage": "S4"})])) == "S4"


def test_a_role_of_one_stage_is_its_stage():
    assert stage_id(SG.stage_of_dispatch(MODEL, "qa-c")) == "S4"
    assert stage_id(SG.stage_of_dispatch(MODEL, "qa-scout", held="S4")) == "S1"


def test_one_running_dispatch_names_the_stage_mapping_and_list():
    assert stage_id(SG.stage_of_dispatch(MODEL, "qa-critic", dispatches={"d1": run({})})) == "S2"
    assert stage_id(SG.stage_of_dispatch(MODEL, "qa-critic", dispatches=[run({"stage": "S4"})])) == "S4"


def test_not_established_is_none_never_the_home_stage():
    assert SG.stage_of_dispatch(MODEL, "qa-critic") is None
    assert SG.stage_of_dispatch(MODEL, "qa-critic", dispatches={}) is None
    # a stale second running record (S2 and S4): no held -> None; held decides
    stale = {"a": run({"stage": "S2"}), "b": run({"stage": "S4"})}
    assert SG.stage_of_dispatch(MODEL, "qa-critic", dispatches=stale) is None
    assert stage_id(SG.stage_of_dispatch(MODEL, "qa-critic", held="S2", dispatches=stale)) == "S2"
    # two running records of the SAME stage are two, not one
    assert SG.stage_of_dispatch(MODEL, "qa-critic", dispatches=[run({}), run({})]) is None


def test_awkward_inputs():
    for bad in ("text", 7, None, ({"x": 1},), set()):
        assert SG.stage_of_dispatch(MODEL, "qa-critic", dispatches=bad) is None
    for row in ({"stage": "S1"}, {"stage": "S9"}, {"stage": None}, {"stage": ["S2"]}, {"status": "done"}, {"role": "qa-a"}):
        assert SG.stage_of_dispatch(MODEL, "qa-critic", dispatches=[run(row)]) is None, row
    assert SG.stage_of_dispatch(MODEL, "qa-critic", dispatches=[run({}), "junk", 3, None]) is not None
    no_stage = run({})
    del no_stage["stage"]
    assert SG.stage_of_dispatch(MODEL, "qa-critic", dispatches=[no_stage]) is None
    assert SG.stage_of_dispatch(MODEL, "general-purpose", held="S2") is None
    assert SG.stage_of_dispatch(MODEL, "", held="S2") is None
    assert SG.stage_of_dispatch(MODEL, "qa-critic", held=7) is None


# --- R2: the static readers -----------------------------------------------------------------------------------------

def test_stages_of_role_and_home_stage():
    assert [s["id"] for s in SG.stages_of_role(MODEL, "qa-critic")] == ["S2", "S3", "S4"]
    assert [s["id"] for s in SG.stages_of_role(MODEL, "qa-a")] == ["S2"]
    assert SG.stages_of_role(MODEL, "nobody") == [] and SG.stages_of_role(MODEL, "") == []
    assert stage_id(SG.stage_of_role(MODEL, "qa-critic")) == "S4"      # home = the LAST stage
    assert SG.stage_of_role(MODEL, "nobody") is None
    one = {"stages": [{"id": "S9", "role": "qa-solo"}]}
    assert stage_id(SG.stage_of_role(one, "qa-solo")) == "S9"          # the single `role` spelling
    real = SG.stage_model()
    for st in real["stages"]:                                          # a role on one stage: as before
        for role in st.get("roles") or ([st["role"]] if st.get("role") else []):
            last = [x["id"] for x in SG.stages_of_role(real, role)][-1]    # a role on several stages: the LAST (qa-case-critic -> S4)
            assert stage_id(SG.stage_of_role(real, role)) == last, role
    assert stage_id(SG.stage_of_role(real, "qa-case-critic")) == "S4"


# --- R3: the exit_gate callers ------------------------------------------------------------------------------------------

@contextlib.contextmanager
def world(tmp: Path, *, dispatches=None, running=("S2",), stories=("T-1",)):
    """Synthetic model + a project root with stories whose pipeline.json has `running` stages running."""
    art = tmp / "art"
    for name in stories:
        (art / name / "state").mkdir(parents=True, exist_ok=True)
        stages = {sid: {"status": "running" if sid in running else "pending"} for sid in ("S1", "S2", "S3", "S4")}
        (art / name / "pipeline.json").write_text(json.dumps({"stages": stages}), encoding="utf-8")
        if dispatches is not None:
            (art / name / "state" / "controller.json").write_text(json.dumps({"dispatches": dispatches}), encoding="utf-8")
    saved = (SG.stage_model, EG.artifact_root, EG.held_stage)
    SG.stage_model = lambda: copy.deepcopy(MODEL)
    EG.artifact_root = lambda *a, **k: art
    try:
        yield art
    finally:
        SG.stage_model, EG.artifact_root, EG.held_stage = saved


def make_tmp() -> Path:
    import tempfile
    return Path(tempfile.mkdtemp(prefix="qa-factory-x2b-"))


def with_tmp(fn):
    def wrapper():
        from harness import cleanup
        tmp = make_tmp()
        try:
            fn(tmp)
        finally:
            cleanup(tmp)
    wrapper.__name__ = fn.__name__
    return wrapper


@with_tmp
def test_caller_stage_id(tmp):
    with world(tmp, dispatches={"d": run({})}):
        assert EG._stage_id("qa-critic", "T-1") == "S2"             # the live dispatch of the named task
        assert EG._stage_id("qa-critic") == "S2"                    # no task: the one running stage of the histories
        assert EG._stage_id("qa-c") == "S4" and EG._stage_id("nobody") == "" and EG._stage_id("") == ""
        assert EG._stage_id("qa-critic", "no-such-story") == ""
        with EG.holding_stage("S3"):
            assert EG._stage_id("qa-critic", "T-1") == "S3"        # held decides
    with world(tmp / "n", dispatches={}, running=()):
        assert EG._stage_id("qa-critic", "T-1") == ""               # not established: no dispatch
        assert EG._stage_id("qa-critic") == ""                      # no running stage anywhere
        assert EG._stage_id("qa-critic", "unknown-task") == ""
    with world(tmp / "m", dispatches={}, running=("S2", "S4")):
        assert EG._stage_id("qa-critic") == ""                      # two running stages: not a guess


@with_tmp
def test_caller_identity_ticket_without_task(tmp):
    with world(tmp, running=("S2",)):
        assert EG._identity({}, "qa-critic")[1]["task"] == "T-1"   # a role of several stages: the ONE story where one runs
        assert EG._identity({}, "qa-c")[1]["task"] == "T-1"        # a role of ONE stage: as today (the newest-file fallback stays)
    with world(tmp / "two", running=("S2",), stories=("T-1", "T-2")):
        assert EG._identity({}, "qa-critic")[1]["task"] == "unknown-task"   # two stories: not established, no guess
    with world(tmp / "none", running=()):
        assert EG._identity({}, "qa-critic")[1]["task"] == "unknown-task"   # no running dispatch: no newest-file fallback
    with world(tmp / "same", running=("S2", "S4"), stories=("T-1",)):
        assert EG._identity({}, "qa-critic")[1]["task"] == "T-1"   # two stages in ONE story: the story is unambiguous


@with_tmp
def test_caller_next_hint(tmp):
    with world(tmp, dispatches={"d": run({"stage": "S2"})}, running=("S2",)):
        hint = EG.next_hint("qa-critic")
        assert "S3" in hint and "qa-b" in hint        # S2's successor, not S4's (S4 is the last: no hint)
    with world(tmp / "n", running=()):
        assert EG.next_hint("qa-critic") == ""        # not established -> no hint printed
        assert EG.next_hint("qa-c") == "next: qa-critic finishes stage S4 (fourth)"   # a role of one stage: as before


@with_tmp
def test_caller_required_outputs(tmp):
    with world(tmp, dispatches={"d": run({})}):
        errors = EG.required_outputs_errors("qa-critic", "T-1")
        text = " ".join(errors)
        assert "s2.txt" in text and "s4.txt" not in text, errors   # S2's outputs, not the home stage's
    with world(tmp / "n", dispatches={}, running=()):
        assert EG.required_outputs_errors("qa-critic", "T-1") == []   # not established: fail-open as for a foreign role
    with world(tmp / "o", dispatches={}, running=()):
        assert any("s4.txt" in e for e in EG.required_outputs_errors("qa-c", "T-1"))   # one stage: as before


@with_tmp
def test_caller_scoped_errors(tmp):
    seen = []
    saved = (EG.collect_errors, EG.bug_audit_errors)
    EG.bug_audit_errors = lambda task, facts_text="": (seen.append("bug_audit"), [])[1]
    EG.collect_errors = lambda task="", facts_text="": ["s2.txt: broken", "s4.txt: broken"]
    try:
        with world(tmp, dispatches={"d": run({})}):
            assert EG.scoped_errors("qa-critic", "T-1") == ["s2.txt: broken"]     # S2's outputs
        with world(tmp / "n", dispatches={}, running=()):
            assert EG.scoped_errors("qa-critic", "T-1") == [] and seen == ["bug_audit"]   # the 'role without a stage' branch
    finally:
        EG.collect_errors, EG.bug_audit_errors = saved


@with_tmp
def test_caller_live_dispatch_and_ticket_of(tmp):
    with world(tmp, dispatches={"d": run({})}):
        live = EG._live_dispatch("qa-critic", "T-1")
        assert live is not None and live["id"] == "d" and live["stage"] == "S2"
        assert EG._ticket_of("qa-critic", "T-1") == "T-1"
        assert EG._ticket_of("qa-critic", "") == "T-1"
    with world(tmp / "n", dispatches={}, running=()):
        assert EG._live_dispatch("qa-critic", "T-1") is None


# --- R4: no cycle ---------------------------------------------------------------------------------------------------------

@with_tmp
def test_stage_id_calls_neither_live_dispatch_nor_ticket_of(tmp):
    def boom(*a, **k):
        raise AssertionError("_stage_id must not call this")
    saved = (EG._live_dispatch, EG._ticket_of)
    EG._live_dispatch, EG._ticket_of = boom, boom
    try:
        with world(tmp, dispatches={"d": run({})}):
            assert EG._stage_id("qa-critic", "T-1") == "S2"
            assert EG._stage_id("qa-critic") == "S2"
    finally:
        EG._live_dispatch, EG._ticket_of = saved


# --- R5: the dispatch guard -----------------------------------------------------------------------------------------------

@contextlib.contextmanager
def guard(tmp: Path, role: str, *, dispatches, pipeline="ok"):
    art = tmp / "art" / "T-1"
    (art / "state").mkdir(parents=True, exist_ok=True)
    if pipeline == "ok":
        (art / "pipeline.json").write_text(json.dumps({"stages": {}}), encoding="utf-8")
    if dispatches is not None:
        (art / "state" / "controller.json").write_text(json.dumps({"dispatches": dispatches}), encoding="utf-8")
    seen = {"stages": []}
    names = ("stage_model", "requested_role", "resolve_ticket", "artifacts_dir", "dispatch_errors", "rule_tracker_route",
             "gate_of_executor")
    saved = {n: getattr(SG, n) for n in names}
    SG.stage_model = lambda: copy.deepcopy(MODEL)
    SG.requested_role = lambda event, model: role
    SG.resolve_ticket = lambda event: ("T-1", {})
    SG.artifacts_dir = lambda ticket, event=None: art
    SG.dispatch_errors = lambda pipeline, stage_id, **k: (seen["stages"].append(stage_id), [])[1]
    SG.rule_tracker_route = lambda *a, **k: None
    SG.gate_of_executor = lambda *a, **k: ""
    try:
        yield seen
    finally:
        for n, v in saved.items():
            setattr(SG, n, v)


@with_tmp
def test_guard_places_a_role_of_several_stages_by_its_running_dispatch(tmp):
    with guard(tmp, "qa-critic", dispatches={"d": run({"stage": "S2"})}) as seen:
        assert SG.check_dispatch({}) == SG.ALLOW
        assert seen["stages"] == ["S2"]                      # judged as S2, not the home stage S4
    with guard(tmp / "b", "qa-critic", dispatches={"d": run({"stage": "S4"})}) as seen:
        assert SG.check_dispatch({}) == SG.ALLOW and seen["stages"] == ["S4"]


@with_tmp
def test_guard_refuses_when_the_stage_is_not_established(tmp):
    for label, dispatches in (("none", {}), ("no controller file", None), ("two running", {"a": run({}), "b": run({"stage": "S4"})}),
                              ("another role", {"a": run({"role": "qa-a"})})):
        with guard(tmp / label.replace(" ", "_"), "qa-critic", dispatches=dispatches) as seen:
            assert SG.check_dispatch({}) == SG.DENY, label
            assert seen["stages"] == [], label            # refused BEFORE the stage rules were consulted
            message = SG.LAST_DENIAL["message"]
            assert "S2, S3, S4" in message and "story_step.py start --task T-1 --stage <stage> --role qa-critic" in message


@with_tmp
def test_guard_keeps_what_it_refused(tmp):
    # a foreign role passes BEFORE any ticket is read
    with guard(tmp, "general-purpose", dispatches=None):
        SG.resolve_ticket = lambda event: (_ for _ in ()).throw(AssertionError("ticket read for a foreign role"))
        assert SG.check_dispatch({}) == SG.ALLOW
    # an unreadable pipeline is refused, for a role of one stage and of several, with no stage resolution needed
    for role in ("qa-c", "qa-critic"):
        with guard(tmp / role, role, dispatches={"d": run({})}, pipeline="missing") as seen:
            assert SG.check_dispatch({}) == SG.DENY and "unreadable pipeline" in SG.LAST_DENIAL["message"], role
            assert seen["stages"] == []
    # a role of ONE stage meets no new branch: no controller.json needed, the stage rules see its stage
    with guard(tmp / "one", "qa-c", dispatches=None) as seen:
        assert SG.check_dispatch({}) == SG.ALLOW and seen["stages"] == ["S4"]
    # the stage rules' own refusal still refuses, for the resolved stage
    with guard(tmp / "rules", "qa-critic", dispatches={"d": run({"stage": "S3"})}) as seen:
        SG.dispatch_errors = lambda pipeline, stage_id, **k: [f"{stage_id} is blocked"]
        assert SG.check_dispatch({}) == SG.DENY and "S3 is blocked" in SG.LAST_DENIAL["message"]


def main() -> int:
    failed = 0
    total = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            total += 1
            try:
                fn()
                print("PASS " + name)
            except Exception as exc:       # noqa: BLE001 - a runner reports every failure
                failed += 1
                print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"=== test_stage_of_dispatch: {total - failed}/{total} ok ===")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
