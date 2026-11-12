#!/usr/bin/env python3
"""GW1-10: `exit_gate.all_errors` names the story to EVERY detector it starts (the finding
`20261021-detektor-pod-finish-ugadyvaet-istoriyu`). KEYS: G1/G2 (two stories, `finish` on A reads A, whatever is newer),
G3/G4 (the adviser writes `work/sizing.json` for the NAMED story, and only after the verdict), G5/G6 (a story that is no
folder is the third state, never a guess), G7 (the shapes the one name rule refuses, the mini-battery), G8/G9 (nothing
named: the variable is removed, the guess stays), G10 (each of the five detectors reads the named story), G11
(`check_coverage` is untouched), G12 (a person's word passes the only block: the adviser runs), G13 (the form check
stays the net for a claim), G14 (the driver's `exit_errors` reaches the named story)."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, finish  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import detector_verdict as DV  # noqa: E402
import exit_gate as EG  # noqa: E402
import hooklib  # noqa: E402
import planning_contract as PC  # noqa: E402

VAR = PC.DETECTOR_STORY_ENV
S2_ROLE, S5_ROLE = "qa-requirements-tester", "qa-automator"
NONE = lambda *a, **k: []  # noqa: E731
STAMP = [10_000_000]
OTHER_READERS = ("witness_errors", "grounding_errors", "case_identity_errors", "digest_errors", "required_outputs_errors")


def stories(root: Path, *names, stages=("S2", "S3", "S4", "S5")) -> list:
    """Story folders with a pipeline.json running `stages`, the LAST name the most recently touched."""
    out = []
    for name in names:
        art = root / "qa-factory/artifacts" / name
        (art / "work").mkdir(parents=True)
        pipeline = art / "pipeline.json"
        pipeline.write_text(json.dumps({"stages": {s: {"status": "running"} for s in stages}}), encoding="utf-8")
        STAMP[0] += 1000                       # one clock for the whole file: a later story is always the newer
        os.utime(pipeline, (STAMP[0], STAMP[0]))
        out.append(art)
    return out


class Gate:
    """`exit_gate` with every reader but the detectors stubbed, one scoped finding at will, the gates named, `subprocess.run`
    counted. Restores every name on exit."""
    NAMES = ("scoped_errors", "detector_gates") + OTHER_READERS

    def __init__(self, role, scripts, scoped=()):
        self.role, self.scripts, self.scoped, self.runs, self.signals = role, list(scripts), list(scoped), [], []

    def __enter__(self):
        self.saved = {n: getattr(EG, n) for n in self.NAMES}
        self.real_run, self.real_signal = EG.subprocess.run, hooklib.person_signal
        for name in OTHER_READERS:
            setattr(EG, name, NONE)
        EG.scoped_errors = lambda *a, **k: list(self.scoped)
        EG.detector_gates = lambda stage="": {self.role: self.scripts}

        def counted(cmd, **kw):
            self.runs.append((cmd, kw.get("env")))
            return self.real_run(cmd, **kw)
        EG.subprocess.run = counted
        hooklib.person_signal = lambda event, kind, text, **kw: self.signals.append((kind, text)) or True
        return self

    def __exit__(self, *exc):
        for name, value in self.saved.items():
            setattr(EG, name, value)
        EG.subprocess.run, hooklib.person_signal = self.real_run, self.real_signal


def sizing_files(root: Path) -> list:
    return sorted(p.parent.parent.name for p in (root / "qa-factory/artifacts").glob("*/work/sizing.json"))


def two_stories_finish(root: Path, TS) -> None:
    """G1, G2: A red (no run block), B newer, S5 running and with nothing to find."""
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    art_a = TS.author_story(root, "QA-G1A")
    art_b = stories(root, "QA-G1B", stages=("S5",))[0]
    flat = ("finish", "--task", "QA-G1A", "--dispatch-id", "s5-author", "--digest", "x", "--output", "author.txt")
    every = list((root / "qa-factory/artifacts").glob("*/pipeline.json"))
    for path, stamp in [(p, 1000) for p in every] + [(art_a / "pipeline.json", 2000), (art_b / "pipeline.json", 1500)]:
        os.utime(path, (stamp, stamp))
    control = harness.run_script("story_step.py", *flat, cwd=root, env=env)
    check_eq("G1 control: A the most recently touched, `finish` on A refuses (exit 3)", control.returncode, 3)
    os.utime(art_b / "pipeline.json", (3000, 3000))
    before = (art_a / "pipeline.json").read_bytes(), (art_b / "pipeline.json").read_bytes()
    named = harness.run_script("story_step.py", *flat, cwd=root, env=env)
    check_eq("G1: B newer and clean, `finish` on A is still refused (exit 3, A's own finding)", named.returncode, 3)
    check_in("G1: for A's own finding", "no run block has been written for this story yet", named.stdout)
    check("G1: A is not accepted", TS.author_picture_of(art_a, "s5-author")[1] != "accepted", str(TS.author_picture_of(art_a, "s5-author")))
    os.utime(art_a / "pipeline.json", (4000, 4000))          # F-4: A is now the NEWEST, so a guess would read red A, not B
    check_eq("G2 (gate level): the same gate run for B reads B (not the newer, red A) and is clean",
             _precheck("QA-G1B"), [])
    check_eq("G2: and A's and B's pipelines are untouched by the refusal",
             ((art_a / "pipeline.json").read_bytes(), (art_b / "pipeline.json").read_bytes()), before)


def _precheck(task) -> list:
    with Gate(S5_ROLE, ["s5_precheck.py"]):
        return [str(e) for e in EG.detector_errors(S5_ROLE, task)]


def adviser_after_the_verdict(root: Path) -> None:
    """G3, G4, G12."""
    a, b = stories(root, "QA-G3A", "QA-G3B")
    finding = DV.Record("scoped.py: [c 1] another reason", script="scoped.py")
    with Gate(S2_ROLE, ["sizing.py"], scoped=[finding]):
        blocking, _passed = EG.all_errors(S2_ROLE, "QA-G3A", "")
    check_eq("G3: an S2 stop red for another reason is still refused", [str(e) for e in blocking], [str(finding)])
    check_eq("G3: ... and `work/sizing.json` is absent in A and in B", sizing_files(root), [])
    with Gate(S2_ROLE, ["sizing.py"]):
        blocking, passed = EG.all_errors(S2_ROLE, "QA-G3A", "")
    import sizing
    check_eq("G4: an S2 stop with nothing to refuse blocks nothing", (blocking, passed), ([], []))
    check_eq("G4: sizing.json is written in A only (B is newer and untouched)", sizing_files(root), ["QA-G3A"])
    on_disk = json.loads((a / "work/sizing.json").read_text(encoding="utf-8"))
    check_eq("G4: and its size is `sizing.compute(A)`'s", on_disk["size"], sizing.compute(a)["size"])
    (a / "work/sizing.json").unlink()
    word = {"stages": {"S2": {"status": "running"}}, "stage_overrides": [
        {"stage": "S2", "match": "s2gate: unreadable", "decision": "go on", "at": "t"}]}
    (a / "pipeline.json").write_text(json.dumps(word), encoding="utf-8")
    os.utime(a / "pipeline.json", (500, 500))
    block = EG.unreadable_record("s2gate", "boom")
    with Gate(S2_ROLE, ["sizing.py"], scoped=[block]):
        blocking, passed = EG.all_errors(S2_ROLE, "QA-G3A", "")
    check_eq("G12: a person's word passes the only block", (len(blocking), len(passed)), (0, 1))
    check_eq("G12: ... and the adviser ran and wrote the file, for A", sizing_files(root), ["QA-G3A"])
    del b


def phantom_and_shapes(root: Path) -> None:
    """G5, G6, G7."""
    stories(root, "QA-G5A", "QA-G5B")
    before = sizing_files(root)
    with Gate(S5_ROLE, ["s5_precheck.py"]) as gate:
        blocking, _ = EG.all_errors(S5_ROLE, "QA-NO-SUCH", "")
    check_eq("G5: a phantom task, a non-adviser: ONE record, kind unreadable, no finding", [e.kind for e in blocking], ["unreadable"])
    check_in("G5: ... naming the raw task", "'QA-NO-SUCH'", str(blocking[0]))
    check_eq("G5: ... and no detector was started (no guess)", gate.runs, [])
    with Gate(S2_ROLE, ["sizing.py"]) as gate:
        blocking, _ = EG.all_errors(S2_ROLE, "QA-NO-SUCH", "")
    check_eq("G6: a phantom task, the adviser: a signal, no record, no child", (blocking, len(gate.signals), gate.runs), ([], 1, []))
    check_eq("G6: ... and `work/sizing.json` appears nowhere", sizing_files(root), before)
    shapes = ["../x", "a/b", "C:\\x", ".", "..", "   ", "\0", "a\nb", "x" * 300, "\u0417\u0410\u0414-1", "QA-g5a"]
    for name in shapes:
        with Gate(S5_ROLE, ["s5_precheck.py"]) as gate:
            records = EG.detector_errors(S5_ROLE, name)
        label = repr(name)[:24]
        check_eq(f"G7 {label}: no raise, one unreadable record, no child started",
                 ([r.kind for r in records], gate.runs), (["unreadable"], []))
        check_in(f"G7 {label}: the reason asserts the RAW task", repr(name), str(records[0]))
    with Gate(S5_ROLE, ["s5_precheck.py"]) as gate:
        wrong = EG.detector_errors(S5_ROLE, "qa-g5a")
    check_in("G7: a wrong case is refused with the real folder named", "'QA-G5A' exists", str(wrong[0]))


def nothing_named(root: Path, TS) -> None:
    """G8, G9."""
    art_a = TS.author_story(root, "QA-G8A")
    stories(root, "QA-G8B", stages=("S5",))
    os.utime(art_a / "pipeline.json", (1000, 1000))              # B is the newest story of the file: the guess reads B
    for task in ("", "unknown-task"):
        for parent_var in (None, str(art_a)):
            saved = os.environ.pop(VAR, None)
            if parent_var:
                os.environ[VAR] = parent_var
            try:
                with Gate(S5_ROLE, ["s5_precheck.py"]) as gate:
                    got = EG.detector_errors(S5_ROLE, task)
            finally:
                os.environ.pop(VAR, None)
                if saved is not None:
                    os.environ[VAR] = saved
            label = f"task {task!r}, parent variable {'set' if parent_var else 'unset'}"
            check_eq(f"G8/G9 {label}: the child's environment has no variable", [VAR in env for _cmd, env in gate.runs], [False])
            check_eq(f"G8/G9 {label}: the guess runs as today (B newer, clean)", got, [])


def each_detector_reads_the_named_story(root: Path) -> None:
    """G10: one id per detector (five: the four zero-argument ones and the S2 gate `branch_accounting.py`, GW1-10 F-1), with the
    variable at A and B the newer story."""
    a, b = stories(root, "QA-G10A", "QA-G10B")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    env.pop(VAR, None)
    for script in ("sizing.py", "planning_contract.py", "critic_rollcall.py", "s5_precheck.py", "branch_accounting.py"):
        guessed = harness.run_script(script, cwd=root, env=env)
        check_in(f"G10 control {script}: with no variable the newest story is read", "QA-G10B", guessed.stdout)
        named = harness.run_script(script, cwd=root, env=dict(env, **{VAR: str(a)}))
        check_in(f"G10 {script}: with the variable at A it reads A", "QA-G10A", named.stdout)
        check_not_in(f"G10 {script}: ... and never B", "QA-G10B", named.stdout)
        gone = harness.run_script(script, cwd=root, env=dict(env, **{VAR: str(a.parent / "QA-G10-NO")}))
        check_eq(f"G10 {script}: a variable at a folder that is not there is exit 3 (never B)", gone.returncode, DV.EXIT_UNREADABLE)
        check_in(f"G10 {script}: ... printed as the one UNREADABLE line", "UNREADABLE: ", gone.stdout)
    del b


def check_coverage_is_untouched(root: Path) -> None:
    """G11."""
    a = root / "qa-factory/artifacts/QA-G10A"
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    env.pop(VAR, None)
    plain = harness.run_script("check_coverage.py", cwd=root, env=env)
    named = harness.run_script("check_coverage.py", cwd=root, env=dict(env, **{VAR: str(a)}))
    check_eq("G11: the result is the same with the variable set", (plain.returncode, plain.stdout), (named.returncode, named.stdout))


def the_form_check_stays_the_net(root: Path) -> None:
    """G13: `digest_errors` reads `RD.check`, not the form claim; `handoff_check` still refuses a wrong size."""
    import test_handoff as TH
    task = TH._c_story(root)
    out, _fixed, problems, _j, _d, _art = TH._c_check(TH._filled(TH.S2C, {"size.computed": "M"}), TH.S2C, task)
    claim = f"claims.{TH.SIZE_CLAIM}"
    check_eq("G13 (a): a role that never ran sizing - the claim stays blank, the form check does not refuse it as false",
             [p.kind for p in problems if p.path == claim], ["blank"])
    task = TH._c_story(root, sizing={"size": "M"})
    _o, _f, problems, _j, _d, _art = TH._c_check(TH._filled(TH.S2C, {"size.computed": "XL"}), TH.S2C, task)
    check_in("G13 (b): a WRONG size is refused at the form check", "the form says XL, work/sizing.json says M",
             " ".join(p.text for p in problems if p.path == claim))


def the_driver_reads_the_named_story(root: Path, TS) -> None:
    """G14: `Driver.exit_errors` calls `all_errors(role, self.task, digest)`: the finding of A is in `blocking`."""
    import test_driver_gate_unreadable as TD
    a = TS.author_story(root, "QA-G14A")
    stories(root, "QA-G14B", stages=("S5",))                  # B: newer, S5 running, nothing for the precheck to find
    driver = TD.make_driver(root)
    driver.task, driver.task_root = "QA-G14A", a
    with Gate(S5_ROLE, ["s5_precheck.py"]):
        blocking = driver.exit_errors(S5_ROLE, "digest")
    check_in("G14: `Driver.exit_errors` on A, B newer: A's own finding is in `blocking`",
             "no run block has been written for this story yet", " ".join(str(e) for e in blocking))


def _env_set(name, value):
    """Set (or, with None, remove) one environment word; returns the word it replaced for `_env_restore`."""
    saved = os.environ.get(name)
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
    return saved


def the_stage_the_finisher_holds(root: Path) -> None:
    """S1-S4 (t-440, F2 of the t-430 verdict): `finish` names the finisher's stage beside the story. INVARIANT (FR-59, AR-28): a
    stage the gate holds wins over any inference; an unknown stage is "cannot tell", never another stage's check; a call that names
    no stage keeps the fallback. Mutations, one killing key each (not run): S1 `_running_stage` ignoring `detector_stage_named`
    -> S1 named S5 key; the named stage tried before the STAGE_CHECKS membership -> S1 `S7` key; `_detector_env` not setting the
    word -> S2 holding key; not popping the parent's stale word -> S2 stale key; `_finish_gate` not entering `holding_stage` -> S3."""
    import branch_accounting as BA
    import story_step
    STAGE = PC.DETECTOR_STAGE_ENV
    # S1: the stage word over a stale `returned_unaccepted` dispatch of ANOTHER stage (the case of a repair round's `finish`)
    stale = {"d1": {"stage": "S5", "status": "returned_unaccepted"}, "d2": {"stage": "S4", "status": "returned_unaccepted"}}
    art = stories(root, "QA-S1", stages=())[0]
    (art / "state").mkdir()
    (art / "pipeline.json").write_text(json.dumps({"stages": {"S5": {"status": "done"}}}), encoding="utf-8")
    (art / "state" / "controller.json").write_text(json.dumps({"dispatches": stale}), encoding="utf-8")
    saved = os.environ.get(STAGE)
    try:
        for label, word, expected in (("no stage named: two live stages, cannot tell (today's fallback)", None, None),
                                      ("a blank word names nothing: the fallback", "   ", None),
                                      ("S1 named S5 beside a stale S4 dispatch: S5", "S5", "S5"),
                                      ("S1 named S4: S4 (the word is the gate's, not a guess)", " S4 ", "S4"),
                                      ("S1 named S7, which this gate does not judge: cannot tell, never another stage's check", "S7", None),
                                      ("S1 a word that is no stage: cannot tell", "s5; rm", None)):
            _env_set(STAGE, word)
            check_eq(f"S1 {label}", BA._running_stage(art), expected)
        (art / "pipeline.json").write_text(json.dumps({"stages": {"S3": {"status": "running"}}}), encoding="utf-8")
        _env_set(STAGE, "S5")
        check_eq("S1 the named stage wins over a pipeline that says another stage is running", BA._running_stage(art), "S5")
        _env_set(STAGE, None)
        check_eq("S1 control: with no word the pipeline's running stage is still the answer", BA._running_stage(art), "S3")
        # the whole entry: which stage's check is asked, in this process
        (art / "pipeline.json").write_text(json.dumps({"stages": {"S5": {"status": "done"}}}), encoding="utf-8")
        asked, real_runners = [], dict(BA.STAGE_RUNNERS)
        for name in real_runners:
            BA.STAGE_RUNNERS[name] = lambda task_root, _n=name: (asked.append(_n), {"state": "ok", "notes": [], "blocks": []})[1]
        saved_story = _env_set(VAR, str(art))
        try:
            import contextlib
            import io
            for word, code, stages in ((None, DV.EXIT_UNREADABLE, []), ("S5", 0, ["S5"]), ("S7", DV.EXIT_UNREADABLE, [])):
                _env_set(STAGE, word)
                del asked[:]
                with contextlib.redirect_stdout(io.StringIO()):
                    got = BA.detector_main(root)
                check_eq(f"S1 detector_main, stage word {word!r}: (exit, stages asked)", (got, list(asked)), (code, stages))
        finally:
            BA.STAGE_RUNNERS.update(real_runners)
            _env_set(VAR, saved_story)
    finally:
        _env_set(STAGE, saved)

    # S2: the gate writes the word to the child, beside the story, only while a stage is held; the parent's stale word is removed
    stories(root, "QA-S2")
    check_eq("S2 nothing held at rest", EG.held_stage(), "")
    _env_set(STAGE, "S3")                                            # a stale word of the parent
    try:
        with Gate(S5_ROLE, ["s5_precheck.py"]) as gate:
            EG.detector_errors(S5_ROLE, "QA-S2")
            with EG.holding_stage("S5"):
                check_eq("S2 held inside the block", EG.held_stage(), "S5")
                EG.detector_errors(S5_ROLE, "QA-S2")
                EG.detector_errors(S5_ROLE, "")                          # no story named: no stage either
            with EG.holding_stage(None):
                EG.detector_errors(S5_ROLE, "QA-S2")
        words = [env.get(STAGE) for _cmd, env in gate.runs]
        check_eq("S2 stale word removed when nothing is held; S5 inside the block; none without a story; none for a non-string",
                 words, [None, "S5", None, None])
        try:
            with EG.holding_stage("S5"):
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        check_eq("S2 the held stage is restored even when the block raises", EG.held_stage(), "")
        with EG.holding_stage("S5"):
            with EG.holding_stage("S4"):
                check_eq("S2 nested: the inner block", EG.held_stage(), "S4")
            check_eq("S2 nested: the outer one is back", EG.held_stage(), "S5")
    finally:
        _env_set(STAGE, None)

    # S3: `_finish_gate` holds `dispatch["stage"]` while it reads the gate, and a dispatch with no stage holds nothing
    seen, real_all, real_gates = [], EG.all_errors, EG.detector_gates
    EG.detector_gates = lambda stage="": {S5_ROLE: ["branch_accounting.py"]}
    EG.all_errors = lambda *a, **k: (seen.append(EG.held_stage()), ([], []))[1]
    try:
        args = type("A", (), {"task": "QA-S2", "dispatch_id": "d1"})()
        for dispatch, expected in (({"role": S5_ROLE, "stage": "S5", "id": "d1"}, "S5"), ({"role": S5_ROLE, "id": "d1"}, ""),
                                   ({"role": S5_ROLE, "stage": None, "id": "d1"}, "")):
            del seen[:]
            code, _text, _notes = story_step._finish_gate(args, art, dispatch, {})
            check_eq(f"S3 _finish_gate with stage {dispatch.get('stage')!r}: accepted, the stage held while the gate is read",
                     (code, seen), (0, [expected]))
        check_eq("S3 and released afterwards", EG.held_stage(), "")
    finally:
        EG.all_errors, EG.detector_gates = real_all, real_gates

    # S4: end to end, a real child: the stale S4 dispatch no longer makes the finisher's gate unreadable
    with Gate(S5_ROLE, ["branch_accounting.py"]):
        without = [r.kind for r in EG.detector_errors(S5_ROLE, "QA-S1")]
        with EG.holding_stage("S5"):
            held = [r.kind for r in EG.detector_errors(S5_ROLE, "QA-S1")]
    check_eq("S4 a real gate run, a stale S4 dispatch: without the stage 'cannot tell' (unreadable); with S5 held it judges (no record)",
             (without, held), (["unreadable"], []))


def main() -> None:
    import test_story_step as TS
    root = harness.temp_project("qa-gw110-")
    saved = os.environ.get("CLAUDE_PROJECT_DIR"), os.environ.pop(VAR, None)
    try:
        harness.use_project(root)
        two_stories_finish(root, TS)
        adviser_after_the_verdict(root)
        phantom_and_shapes(root)
        nothing_named(root, TS)
        each_detector_reads_the_named_story(root)
        check_coverage_is_untouched(root)
        the_form_check_stays_the_net(root)
        the_driver_reads_the_named_story(root, TS)
        the_stage_the_finisher_holds(root)
    finally:
        harness.cleanup(root)
        if saved[0] is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = saved[0]
    finish("test_detector_named_story")


if __name__ == "__main__":
    main()
