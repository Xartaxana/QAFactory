#!/usr/bin/env python3
"""G1-11 (grounding/1): S3 in two windows - labelling first (`purpose: s3_labelling`), the plan second.

The driver side (`Driver.stage_S3` and its helpers) is run in process over a seeded story with `py`, `run_role`, `controller_state`,
`claim_projector.project` and `grounding_table.check` replaced by recorders (no network, no `claude`); the controller word, the
exit gate branch and the dispatch files of window 1 run for real on scratch roots.

  W1 no new stage      W2 routing            W3 the live road     W4 s3_prepare failures    W5 completion_for matrix
  W6 the window word   W7 step 8             W8 the lines         W9 projector problems     W10 text pins
  W11 off the diff     W12 start/finish      W13 the word check   W14 exit gate             W15 relaunch / never launched
  W16 ticket rework    W17 a failed warning write
"""
import contextlib
import io
import json
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402
from story_run_common import driver_for, seed  # noqa: E402

KEY = "QA-1"
ROLE = "qa-test-strategist"
PLUGIN = harness.PLUGIN_ROOT


def quiet():
    return contextlib.redirect_stdout(io.StringIO())


def put_json(path: Path, data) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def story(*, diff: bool = True, table: bool = True):
    """(root, task_root, env, driver): a seeded story at S3. `diff`: pipeline records `diff`, else `none`; `table`: work/grounding.yaml exists."""
    root, task_root, env = seed(KEY)
    pipeline = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))
    pipeline["implementation_source"] = "diff" if diff else "none"
    put_json(task_root / "pipeline.json", pipeline)
    if table:
        (task_root / "work" / "grounding.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    driver = driver_for(root, env, KEY)
    driver.first_look_step = lambda: None  # the first-look step has its own test (test_first_look_step.py)
    driver.calls, driver.roles = [], []
    return root, task_root, env, driver


def stub_py(driver, codes=None):
    """Replace `py`: record (script, *args); `codes` maps a script (or `script arg0`) to (exit, output)."""
    codes = codes or {}

    def fake(script, *args, check=False, expect=""):
        driver.calls.append((script,) + tuple(str(a) for a in args))
        code, out = codes.get(f"{script} {args[0]}" if f"{script} {args[0]}" in codes else script, (0, "")) if args else codes.get(script, (0, ""))
        if check and code:
            import story_run
            raise story_run.Refusal(f"{script} (exit {code}):\n{out}")
        return code, out
    driver.py = fake


def stub_role(driver):
    def fake(stage, role, **kwargs):
        driver.roles.append(dict(kwargs, stage=stage, role=role))
        return "", {}
    driver.run_role = fake


def scripts_of(driver) -> list:
    return [c[0] for c in driver.calls]


@contextlib.contextmanager
def patched(module, name, value):
    old = getattr(module, name)
    setattr(module, name, value)
    try:
        yield
    finally:
        setattr(module, name, old)


def projection(wrote=False, problems=()):
    return lambda root, **kw: types.SimpleNamespace(projected=[], unchanged=[], problems=list(problems), notes=[], wrote=wrote)


def record(status="accepted", word=True, stage="S3", **extra):
    base = {"id": "S3-qa-test-strategist-1", "stage": stage, "role": ROLE, "status": status, "scope": []}
    base["request_binding"] = {"purpose": "s3_labelling"} if word else {}
    return dict(base, **extra)


def with_state(driver, dispatches: dict) -> None:
    driver.controller_state = lambda: {"dispatches": dispatches}


def finding(rule, who, text=None):
    import grounding_table as GT
    return GT.Finding(rule, text or f"{rule} finding", who)


# --- W1 ---------------------------------------------------------------------------------------------------------------------
def w1_no_new_stage() -> None:
    import brief_pack
    import report_facts
    import window_budget
    names = [f"S{i}" for i in range(10)]
    check_eq("W1: brief_pack.STAGE_ORDER is S0..S9", list(brief_pack.STAGE_ORDER), names)
    check_eq("W1: window_budget.FALLBACK_ORDER is S0..S9", list(window_budget.FALLBACK_ORDER), names)
    check("W1: S3 is a gate-A stage", "S3" in report_facts.GATE_A_STAGES)
    stages = json.loads((PLUGIN / "references" / "stages.json").read_text(encoding="utf-8"))
    rows = stages["stages"] if isinstance(stages, dict) and "stages" in stages else stages
    rows = list(rows.values()) if isinstance(rows, dict) else rows
    by = {r["id"]: r for r in rows}
    check_eq("W1: stages.json ids are exactly S0..S9", sorted(by), names)
    check_eq("W1: S3 requires S2 and has the strategist and the stage critic", (by["S3"]["requires"], by["S3"]["roles"]), (["S2"], [ROLE, "qa-case-critic"]))
    check_eq("W1: S4 requires S3", by["S4"]["requires"], ["S3"])


# --- W2 ---------------------------------------------------------------------------------------------------------------------
def w2_routing() -> None:
    root, _task_root, _env, driver = story()
    try:
        seen = []
        for name in ("stage_S2", "stage_S3", "stage_S4"):
            setattr(driver, name, lambda name=name: seen.append(name))
        driver.stage_simple = lambda stage: seen.append("simple:" + stage)
        for stage in ("S1", "S2", "S3", "S4"):
            driver._act_prepare_stage({"stage": stage})
        check_eq("W2: S1 -> stage_simple, S2 -> stage_S2, S3 -> stage_S3, S4 -> stage_S4 (control)",
                 seen, ["simple:S1", "stage_S2", "stage_S3", "stage_S4"])
    finally:
        harness.cleanup(root)


# --- W3 / W11 ---------------------------------------------------------------------------------------------------------------
def w3_the_live_road() -> None:
    import claim_projector as CP
    root, _task_root, _env, driver = story()
    try:
        stub_py(driver)
        stub_role(driver)
        with_state(driver, {})
        with patched(CP, "project", projection(wrote=False)), quiet():
            driver.stage_S3()
            check_eq("W3: prepare order: index, table, slice - then the role", scripts_of(driver),
                     ["blast_radius.py", "grounding_table.py", "base_slice.py"])
            check_eq("W3: the table is refreshed, never re-skeletoned",
                     driver.calls[1], ("grounding_table.py", "--refresh", "--task", KEY))
            first = driver.roles[0]
            check_eq("W3: window 1 starts with the labelling word", first.get("purpose"), "s3_labelling")
            check("W3: its lines carry no plan line", not any("test-plan.json" in line for line in first["extra"]), str(first["extra"]))
            done = first["complete"]("digest")
            import story_run
            check("W3: window 1 completes OPEN with plan_pending",
                  isinstance(done, story_run.OpenWork) and done.unresolved == "plan_pending", repr(done))
            check_eq("W3: no projection wrote, so no refresh after it", scripts_of(driver), ["blast_radius.py", "grounding_table.py", "base_slice.py"])
        driver.calls.clear()
        with patched(CP, "project", projection(wrote=True)), quiet():
            driver.roles[0]["complete"]("digest")
            check_eq("W3: a projection that wrote is followed by a refresh BEFORE the acceptance", driver.calls,
                     [("grounding_table.py", "--refresh", "--task", KEY)])
        # window 1 accepted -> the loop comes back: between -> step 8 clean -> window 2 (no purpose), closes after the projection
        driver.calls.clear()
        driver.roles.clear()
        with_state(driver, {"S3-qa-test-strategist-1": record("accepted")})
        import grounding_table as GT
        stops = []
        driver.grounding_stop = lambda: stops.append("stop")
        rows_q = lambda root: types.SimpleNamespace(projected=[], problems=[], notes=[], wrote=False)      # noqa: E731
        driver.stage_critic_route = lambda stage, author: None      # the critic's window after window 2 is judged in test_stage_critic_route
        with patched(GT, "check", lambda root: []), patched(CP, "project", projection()), patched(CP, "project_row_questions", rows_q), quiet():
            driver.stage_S3()
            second = driver.roles[0]
            check_eq("W3: window 2 starts with no purpose; the slot before it only measures (--share), no new preparation",
                     (second.get("purpose", ""), driver.calls, stops), ("", [("grounding_table.py", "--share", "--task", KEY)], ["stop"]))
            driver.calls.clear()
            check("W3: window 2 lines carry the plan line and the K-n/B-n reach line",
                  any("test-plan.json" in l for l in second["extra"]) and any("K-n" in l and "B-n" in l for l in second["extra"]), str(second["extra"]))
            check_eq("W3: window 2 closes S3 by the stage's own rule after the projection", second["complete"]("digest"), None)
            check_eq("W3: ...and measures again over the bytes the role left (the saved keys follow them)", driver.calls,
                     [("grounding_table.py", "--share", "--task", KEY)])
    finally:
        harness.cleanup(root)


def w11_off_the_diff() -> None:
    import claim_projector as CP
    root, _task_root, _env, driver = story(diff=False, table=False)
    try:
        stub_py(driver)
        stub_role(driver)
        with_state(driver, {})
        routed = []
        driver.stage_critic_route = lambda stage, author: routed.append((stage, author))   # the critic's window is judged in test_stage_critic_route
        with patched(CP, "project", projection()), quiet():
            driver.stage_S3()
        check_eq("W11: after the author's one window the stage critic is routed once (X2-7)", routed, [("S3", ROLE)])
        check_eq("W11: off the diff the preparation is the GT step alone", scripts_of(driver), ["grounding_table.py"])
        check_eq("W11: one window, no purpose", (len(driver.roles), driver.roles[0].get("purpose", "")), (1, ""))
        check_eq("W11: the lines are today's plan line and the fence line alone (no reach line, nothing counted)",
                 driver.roles[0]["extra"], [driver.S3_PLAN_LINE, driver.S3_FENCE_LINE])
    finally:
        harness.cleanup(root)


# --- W4 ---------------------------------------------------------------------------------------------------------------------
def w4_prepare_failures() -> None:
    import story_run
    cases = [("blast_radius.py", (1, "no index"), ["blast_radius.py"], "blast_radius.py exited 1: no index"),
             ("grounding_table.py", (2, "R0: unreadable"), ["blast_radius.py", "grounding_table.py"], "grounding_table.py --refresh exited 2: R0: unreadable")]
    for script, answer, ran, text in cases:
        root, _task_root, _env, driver = story()
        try:
            stub_py(driver, {script: answer})
            stub_role(driver)
            with_state(driver, {})
            refusal = None
            with quiet():
                try:
                    driver.stage_S3()
                except story_run.Refusal as exc:
                    refusal = exc
            check(f"W4: {script} exit {answer[0]} is a Refusal naming it", refusal is not None and text in refusal.text, getattr(refusal, "text", ""))
            check_eq(f"W4: {script} failing stops the later steps", scripts_of(driver), ran)
            check_eq(f"W4: {script} failing: run_role is not called", driver.roles, [])
        finally:
            harness.cleanup(root)
    root, _task_root, _env, driver = story()
    try:
        stub_py(driver, {"base_slice.py": (2, "cannot read base\nmore")})
        stub_role(driver)
        with_state(driver, {})
        import claim_projector as CP
        with patched(CP, "project", projection()), quiet():
            driver.stage_S3()
        warns = [c for c in driver.calls if c[0] == "stage_done.py"]
        check_eq("W4: a failing slice is ONE --warn line and the role runs", (len(warns), len(driver.roles)), (1, 1))
        check("W4: the warn line names the exit, the first output line and `unknown`",
              "base_slice.py exited 2 (cannot read base)" in warns[0][-1] and "before: unknown" in warns[0][-1], str(warns))
        check("W4/OH1-11: the line starts with the structured prefix gate A reads (`base_slice: unknown - `)",
              warns[0][-1].startswith("base_slice: unknown - "), str(warns))
        driver.calls.clear()
        stub_py(driver)
        with quiet():
            driver.s3_prepare()
        check_eq("W4 control: exit 0 -> no --warn", [c for c in driver.calls if c[0] == "stage_done.py"], [])
    finally:
        harness.cleanup(root)
    # the real stage_done.py records the same line once (stage_done.py:121)
    root, task_root, env = seed(KEY)
    try:
        line = "S3 preparation: base_slice.py exited 2 (x): no base slice for this story; the planner reads before: unknown"
        for _ in range(2):
            harness.run_script("stage_done.py", "--task", KEY, "--warn", line, cwd=root, env=env)
        pipeline = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))
        check_eq("W4: twice recorded, the warning stands once", pipeline["warnings"].count(line), 1)
    finally:
        harness.cleanup(root)


# --- W5 ---------------------------------------------------------------------------------------------------------------------
def w5_completion_matrix() -> None:
    import story_run
    root, task_root, _env, driver = story()
    try:
        stub_py(driver)
        import claim_projector as CP
        with patched(CP, "project", projection()), quiet():
            labelling = driver.completion_for("S3", ROLE, record("running"))
            check("W5: a labelling record -> a callable -> OpenWork(plan_pending)",
                  callable(labelling) and isinstance(labelling("d"), story_run.OpenWork) and labelling("d").unresolved == "plan_pending")
            closing = driver.completion_for("S3", ROLE, record("running", word=False))
            check("W5: an exit record with a table -> a callable -> None", callable(closing) and closing("d") is None)
            (task_root / "work" / "grounding.yaml").unlink()
            old_road = driver.completion_for("S3", ROLE, record("running", word=False))
            check("W5: `old` (exit, diff, no table) -> a callable that closes as today (None) and projects the PLAN only (RN1-2, B-5b)",
                  callable(old_road) and old_road("d") is None, str(old_road))
            (task_root / "work" / "grounding.yaml").write_text("x: 1\n", encoding="utf-8")
            ticket = driver.completion_for("S3", ROLE, record("running", word=False, repair_cause="ticket_changed", rework_of="S3-x-1"))
            # X2-7: S3 has an acceptor (qa-case-critic), so the ticket re-run runs the side steps and does not close: None, the critic closes
            check("W5: S3 ticket_changed -> the s3_ticket_completion callable (closes=False: the stage critic closes) -> None", callable(ticket) and ticket("d") is None)
            for label, extra in (("rework_of", {"rework_of": "S3-x-1"}), ("repair_verify", {"purpose": "repair_verify"})):
                rework = driver.completion_for("S3", ROLE, record("running", word=False, **extra))
                check(f"W5: S3 {label} -> a callable (the plan projection, RN1-2 B-1) whose answer stays False", callable(rework) and rework("d") is False)
            check_eq("W5 control: another S3 role's rework_of stays the plain False", driver.completion_for("S3", "qa-other", {"rework_of": "x"}), False)
            check_eq("W5 control: S2 ticket_changed -> None (S2 has an acceptor: the stage critic closes)", driver.completion_for("S2", "qa-requirements-tester", {"repair_cause": "ticket_changed"}), None)
            check_eq("W5 control: S4 critic rework_of -> False through the S4 rule's own answer or the rework rule",
                     driver.completion_for("S4", "qa-case-designer", {"rework_of": "x"}), False)
            check_eq("W5 control: S7 analyst unchanged (a callable)", callable(driver.completion_for("S7", "qa-failure-analyst", {})), True)
            check_eq("W5 control: S8 scribe True", driver.completion_for("S8", "qa-doc-scribe", {}), True)
    finally:
        harness.cleanup(root)


# --- W6 ---------------------------------------------------------------------------------------------------------------------
def w6_the_window_word() -> None:
    import controller as CT
    good = {"stage": "S3", "request_binding": {"purpose": "s3_labelling"}}
    check_eq("W6: the true case", CT.s3_window_of(good), "labelling")
    bad = [("the word on the top of the record only", {"stage": "S3", "purpose": "s3_labelling"}),
           ("request_binding null", {"stage": "S3", "request_binding": None}),
           ("request_binding a list", {"stage": "S3", "request_binding": ["s3_labelling"]}),
           ("request_binding a string", {"stage": "S3", "request_binding": "s3_labelling"}),
           ("upper case", {"stage": "S3", "request_binding": {"purpose": "S3_LABELLING"}}),
           ("a leading blank", {"stage": "S3", "request_binding": {"purpose": " s3_labelling"}}),
           ("the word on an S4 record", {"stage": "S4", "request_binding": {"purpose": "s3_labelling"}}),
           ("no stage", {"request_binding": {"purpose": "s3_labelling"}}),
           ("not a dict", "s3_labelling"), ("None", None), ("a list", [good])]
    for label, value in bad:
        check_eq(f"W6: {label} -> exit", CT.s3_window_of(value), "exit")
    root, task_root, _env, driver = story()
    try:
        with_state(driver, {"a": record("accepted")})
        check_eq("W6: an accepted labelling record -> between", driver.s3_window(), "between")
        for status in ("released_by_person", "superseded", "stale", "never_started"):
            with_state(driver, {"a": record(status)})
            check_eq(f"W6: a {status} labelling record does not count -> w1", driver.s3_window(), "w1")
        with_state(driver, {"a": record("accepted"), "b": record("released_by_person", word=False)})
        check_eq("W6: a set-aside window 2 after an accepted window 1 -> still between", driver.s3_window(), "between")
        with_state(driver, {"a": record("accepted"), "b": record("accepted", word=False)})
        check_eq("W6: the newest counting record is an exit record -> w1 (a new life of S3)", driver.s3_window(), "w1")
        with_state(driver, {"z": record("accepted"), "a": record("accepted", word=False)})
        check_eq("W6: the order is the insertion order, never the id sort", driver.s3_window(), "w1")
        with_state(driver, {})
        check_eq("W6: no record -> w1", driver.s3_window(), "w1")

        def broken():
            raise ValueError("controller.json unreadable")
        driver.controller_state = broken
        check_eq("W6: an unreadable controller state -> w1 (doubt is never `between`)", driver.s3_window(), "w1")
    finally:
        harness.cleanup(root)


# --- W7 ---------------------------------------------------------------------------------------------------------------------
def w7_step_eight() -> None:
    import grounding_table as GT
    import story_run
    root, task_root, _env, driver = story()
    try:
        stub_py(driver)
        stub_role(driver)

        def fresh(findings, expect_prepare=None, pipeline=None):
            driver.calls.clear()
            if pipeline is not None:
                put_json(task_root / "pipeline.json", pipeline)
            with patched(GT, "check", lambda root: findings), quiet():
                return driver.s3_fresh_for_window2(), scripts_of(driver)
        reason, ran = fresh([finding("R5", "driver", "the register changed")])
        check("W7: R5 -> a reason AND the preparation ran first", bool(reason) and ran == ["blast_radius.py", "grounding_table.py", "base_slice.py"], f"{reason!r} {ran}")
        reason, ran = fresh([finding("R1", "role", "row empty")])
        check("W7: R1 -> window 1, no preparation", bool(reason) and ran == [], f"{reason!r} {ran}")
        reason, ran = fresh([finding("R3", "role"), finding("R4", "role"), finding("R8", "driver")])
        check_eq("W7: R3/R4/R8 alone -> window 2 (they are the exit's)", (reason, ran), ("", []))
        reason, ran = fresh([finding("R0", "role", "syntax")])
        check("W7: R0 by the role -> window 1", bool(reason) and ran == [], f"{reason!r} {ran}")
        reason, ran = fresh([finding("R2", "role", "a requirement line has no state")])
        check("W7: R2 by the role -> window 1, no preparation", bool(reason) and ran == [], f"{reason!r} {ran}")
        reason, ran = fresh([finding("R0", "driver", "the table has no implementation_source")])
        check("W7: R0 by the driver -> the preparation ran, then window 1",
              bool(reason) and ran == ["blast_radius.py", "grounding_table.py", "base_slice.py"], f"{reason!r} {ran}")

        def refused(findings):
            """(Refusal or None, the scripts that ran): step 8 over `findings`. POSITION: nothing is prepared and no role is started."""
            driver.calls.clear()
            driver.roles.clear()
            try:
                with patched(GT, "check", lambda root: findings), quiet():
                    driver.s3_fresh_for_window2()
                return None, scripts_of(driver)
            except story_run.Refusal as exc:
                return exc, scripts_of(driver)
        # B2: a finding window 1 cannot cure (owner driver/conductor, not the prepare road's) is a Refusal naming GT's text and the conductor,
        # one row per rule x owner; the E14 empty diff is the R1 driver row. Window 1's exit keeps only `role` findings, so sending these
        # back would loop paid dispatches with no door.
        for rule, who, text in (("R0", "conductor", "the table is not a mapping"), ("R1", "driver", "the implementation diff on disk has no hunk"),
                                ("R1", "conductor", "the diff index carries no hunk bodies"), ("R2", "driver", "the requirements register cannot be read"),
                                ("R2", "conductor", "the register is held by another writer")):
            raised, ran = refused([finding(rule, who, text)])
            check(f"W7: {rule} ({who}) -> a Refusal carrying GT's text, the owner and the conductor, nothing prepared",
                  raised is not None and text in raised.text and f"owner: {who}" in raised.text and "conductor" in raised.text
                  and raised.dispatch == "" and ran == [], f"{getattr(raised, 'text', None)!r} {ran}")
        raised, ran = refused([finding("R5", "driver", "the register changed"), finding("R1", "driver", "the implementation diff on disk has no hunk")])
        check("W7: a stuck finding beside R5 -> the Refusal first, nothing prepared (nothing is paid, nothing half-run)",
              raised is not None and "no hunk" in raised.text and ran == [], f"{getattr(raised, 'text', None)!r} {ran}")
        with quiet():
            def boom(root):
                raise RuntimeError("check crashed")
            try:
                with patched(GT, "check", boom):
                    driver.s3_fresh_for_window2()
                raised = None
            except story_run.Refusal as exc:
                raised = exc
        check("W7: GT.check raising -> a Refusal naming the exception", raised is not None and "RuntimeError" in raised.text, getattr(raised, "text", ""))
        pipeline = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))
        pipeline["stage_overrides"] = [{"stage": "S3", "match": "row empty", "decision": "go on", "at": "t"}]
        reason, ran = fresh([finding("R1", "role", "row empty")], pipeline=pipeline)
        check_eq("W7: R1 passed by a person's recorded word -> window 2", (reason, ran), ("", []))
        pipeline["stage_overrides"][0]["stage"] = "S5"
        reason, _ = fresh([finding("R1", "role", "row empty")], pipeline=pipeline)
        check("W7 control: the same word on another stage passes nothing", bool(reason))
        pipeline["stage_overrides"] = [{"stage": "S3", "match": "no hunk", "decision": "go on", "at": "t"}]
        put_json(task_root / "pipeline.json", pipeline)
        raised, ran = refused([finding("R1", "driver", "the implementation diff on disk has no hunk")])
        check_eq("W7: a stuck finding passed by a person's recorded word -> no Refusal (FR-4: an informed pass)", (raised, ran), (None, []))
        pipeline["stage_overrides"] = []
        put_json(task_root / "pipeline.json", pipeline)
        # The loop probe (critic t-1238): a standing R1 `driver` finding (E14, the empty diff) over an ACCEPTED labelling record. Three
        # `stage_S3()` calls: window 1 must not be paid again and again - at most ONE labelling run, then a Refusal, never a silent loop.
        import claim_projector as CP
        driver.roles.clear()
        with_state(driver, {"S3-qa-test-strategist-1": record("accepted")})
        refusals = []
        with patched(GT, "check", lambda root: [finding("R1", "driver", "the implementation diff on disk has no hunk")]), \
                patched(CP, "project", projection()), quiet():
            for _ in range(3):
                try:
                    driver.stage_S3()
                except story_run.Refusal as exc:
                    refusals.append(exc)
        check("W7: three stage_S3() calls over a standing R1 driver finding -> at most ONE labelling run, then a Refusal",
              len(driver.roles) <= 1 and len(refusals) >= 1 and len(driver.roles) + len(refusals) == 3,
              f"{len(driver.roles)} role runs {[r.get('purpose') for r in driver.roles]}, {len(refusals)} refusals")
        check("W7: ...and the last call is a Refusal naming the conductor, not another dispatch",
              len(refusals) >= 1 and "conductor" in refusals[-1].text and not any(r.get("purpose") == "s3_labelling" for r in driver.roles[1:]))
    finally:
        harness.cleanup(root)


# --- W8 / W9 ----------------------------------------------------------------------------------------------------------------
def w8_the_lines() -> None:
    import handoff as H
    root, _task_root, _env, driver = story()
    try:
        one = driver.role_lines("S3", ROLE, {"window": "labelling"})
        joined = "\n".join(one)
        check_not_in("W8: window 1 has no `write test-plan.json` line", "Write work/test-plan.json", joined)
        check_in("W8: window 1 says it writes no plan and names the table", "write NO plan row", joined)
        check_in("W8: window 1 lists the claims[] field and the 300-character limit of a question", "claims[]", joined)
        check_in("W8: ...the limit", "at most 300 characters", joined)
        check("W8: window 1 carries the claims line whole (B1) - the fields the claim projector judges, not the list's `claims[]` alone",
              driver.S3_CLAIMS_LINE in one and all(key in driver.S3_CLAIMS_LINE for key in ("`before_ref`", "`now_ref`", "`differs`", "`question: raise`", "`ask`", "`impact`")),
              "\n".join(one))
        check_in("W8: ...and the labels from vocabulary.yaml", ", ".join(H.allowed("grounding_labels")), joined)
        original = H.allowed
        with patched(H, "allowed", lambda name: original(name) + ["zz_extra_word"] if name == "grounding_labels" else original(name)):
            check_in("W8: a word added to the vocabulary shows in the line (one carrier, FR-13)", "zz_extra_word",
                     "\n".join(driver.role_lines("S3", ROLE, {"window": "labelling"})))
        both = "\n".join(driver.role_lines("S3", ROLE, {"repair_cause": "ticket_changed"}))
        # B3: ONE dispatch labels, then plans - the packet holds the labelling fields, the claims line, the plan line and the reach line,
        # and no line tells it to write no plan.
        check_not_in("W8: ticket_changed -> the packet never says `write NO plan row`", "write NO plan row", both)
        check_in("W8: ticket_changed -> the lead line says label first, then plan",
                 "This dispatch labels work/grounding.yaml first (the fields below), then writes the plan over it", both)
        check("W8: ticket_changed -> the labelling fields, the claims line, the plan line and the K-n/B-n reach line are all present",
              all(part in both for part in ("Fill only:", driver.S3_CLAIMS_LINE, driver.S3_PLAN_LINE, "`K-n`", "`matters: yes`", "`not_planned`", "blast:B-n")), both)
        check("W8: ticket_changed -> the plan line comes after the labelling fields (label, then plan)",
              both.index("Fill only:") < both.index("Write work/test-plan.json"))
        two = "\n".join(driver.role_lines("S3", ROLE, {"window": "exit"}))
        check("W8: window 2 -> the plan line and the K-n/B-n reach line", "Write work/test-plan.json" in two and "`K-n`" in two and "blast:B-n" in two)
        check_not_in("W8: window 2 does not say `write NO plan row`", "write NO plan row", two)
        check_eq("W8: record {} -> today's window-2 lines (the plan line, the reach line); the claims line is window 1's and the ticket packet's",
                 driver.s3_strategist_lines({}), driver.role_lines("S3", ROLE, {"window": "exit"}))
        check_not_in("W8: ...no claims line in window 2", driver.S3_CLAIMS_LINE, two)
        import controller as CT
        stored = driver.role_lines("S3", ROLE, {"stage": "S3", "request_binding": {"purpose": CT.S3_LABELLING}})
        check_eq("W8: a controller record with the word gives the window-1 lines", stored, one)
        check_eq("W8 control: qa-runner lines are today's", driver.role_lines("S6", "qa-runner", {"window": "labelling"}),
                 driver.role_lines("S6", "qa-runner"))
    finally:
        harness.cleanup(root)
    root, _task_root, _env, driver = story(diff=False, table=False)
    try:
        check_eq("W8: off the diff the window-2 lines are today's plan line and the fence line alone",
                 driver.role_lines("S3", ROLE), [driver.S3_PLAN_LINE, driver.S3_FENCE_LINE])
    finally:
        harness.cleanup(root)


def w9_projector_problems() -> None:
    import claim_projector as CP
    import story_run
    root, _task_root, _env, driver = story()
    try:
        stub_py(driver)
        stub_role(driver)
        with_state(driver, {})
        driver.last_dispatch = "S3-qa-test-strategist-1"
        with patched(CP, "project", projection(problems=[CP.ClaimProblem("R-a", "role", "claims[0]", "claims[0]: before is empty")])), quiet():
            driver.stage_S3()
            raised = None
            try:
                driver.roles[0]["complete"]("d")
            except story_run.Refusal as exc:
                raised = exc
        check("W9: a role problem -> Refusal with the CP text, the dispatch id and the repair marker",
              raised is not None and "before is empty" in raised.text and story_run.REPAIR_MARKER in raised.text
              and raised.dispatch == "S3-qa-test-strategist-1", getattr(raised, "text", ""))
        check_eq("W9: no story_step finish was called", [c for c in driver.calls if c[0] == "story_step.py"], [])
        with patched(CP, "project", projection(problems=[CP.ClaimProblem("R-e", "driver", "lock", "another writer holds the lock")])), quiet():
            raised = None
            try:
                driver.roles[0]["complete"]("d")
            except story_run.Refusal as exc:
                raised = exc
        check("W9: a driver problem -> Refusal WITHOUT the role's marker", raised is not None and story_run.REPAIR_MARKER not in raised.text, getattr(raised, "text", ""))
    finally:
        harness.cleanup(root)


# --- W10 --------------------------------------------------------------------------------------------------------------------
def w10_text_pins() -> None:
    import grounding_table as GT
    flat = lambda rel: " ".join((PLUGIN / rel).read_text(encoding="utf-8").split())      # noqa: E731
    phase = flat("skills/qa-story/phases/s3.md")
    first = "**A behaviour the register does not hold.** When a `behaviour_change` row of `work/grounding.yaml`"
    last = "A claim is a statement about the code for the person to confirm, never the expected value of a test."
    import story_run
    # spec t-1765 X1 (B-D): the charter keeps `not_planned` (Good outcome 1). The other eight pins are rules under code and move to
    # the carriers the role is handed: the driver's window-1 field list and claims line, and the strategist's slice of the plan contract.
    # Two old words have no verbatim carrier now and the closest sentence is pinned (reported): "Two windows" (a comment of story_run.py
    # names it) -> S3_WINDOW1_FIELDS; "never halt for it yourself" -> the claims line's "never in the register".
    window1 = " ".join(story_run.Driver.S3_WINDOW1_FIELDS.split())
    for key in (".matters", "claims[]", ".regression, .add_tests"):
        check_in(f"W10: the driver's window-1 field list holds {key}", key, window1)
    claims_line = " ".join(story_run.Driver.S3_CLAIMS_LINE.split())
    check_in("W10: the driver's claims line holds the claims rule", "write it as one entry of `claims` in `work/grounding.yaml` (never in the register",
             claims_line)
    check_not_in("W10 control: a wrong claims rule is not in the line", "write it as one entry of `claims` in the register", claims_line)
    # the two sentences `first` and `last` and the R-line rule are rows of design/role-rules.json; `first`/`last` stay below as the
    # bounds of the quoted block that the driver constant is joined to
    fields = [f".{name}" for name in GT.ROLE_AREA_FIELDS] + ["rows[].label", "requirements[].state", "claims[]", ".risks[{id: K-n, hypothesis}]"]
    import story_run
    driver_text = story_run.Driver.S3_WINDOW1_FIELDS
    flat_fields = lambda text: [f for f in fields if f not in text]      # noqa: E731
    check_eq("W10: the driver's window-1 field list names every GT role field", flat_fields(driver_text), [])
    check_eq("W10: phases/s3.md names every GT role field", flat_fields(phase), [])
    check_eq("W10 negative control: a copy of the text with one field removed fails the check",
             flat_fields(phase.replace(".add_tests", "")), [".add_tests"])
    # B1: the claims text reaches the role in its dispatch text (it is told not to read the plugin's files). The driver constant is the
    # quoted block of phases/s3.md - the lines after «Tell the role, verbatim», the "> " markers stripped, joined with a SPACE - byte for byte.
    def quoted_block(text: str) -> str:
        lines = text.splitlines()
        start = next((i for i, line in enumerate(lines) if "Tell the role, verbatim" in line), None)
        block = []
        for line in lines[start + 1:] if start is not None else []:
            if line.startswith("> "):
                block.append(line[2:].rstrip())
            elif block:
                break
        return " ".join(block)
    claims_pinned = lambda constant, text: bool(quoted_block(text)) and constant == quoted_block(text)      # noqa: E731
    phase_raw = (PLUGIN / "skills/qa-story/phases/s3.md").read_text(encoding="utf-8")
    check("W10: S3_CLAIMS_LINE is the quoted block of phases/s3.md, byte for byte (a block was found)",
          claims_pinned(story_run.Driver.S3_CLAIMS_LINE, phase_raw), f"{story_run.Driver.S3_CLAIMS_LINE!r} vs {quoted_block(phase_raw)!r}")
    check("W10: the block starts and ends where the phase's first/last anchors say", quoted_block(phase_raw).startswith(first) and quoted_block(phase_raw).endswith(last))
    root, _task_root, _env, driver = story()
    try:
        # the pinned text is what the role is handed: the phase's block, byte for byte, as one line of the window-1 dispatch and of the ticket packet
        for label, record_ in (("window 1", {"window": "labelling"}), ("the ticket packet", {"repair_cause": "ticket_changed"})):
            check(f"W10: {label} hands the role the phase's quoted block as one line",
                  quoted_block(phase_raw) in driver.role_lines("S3", ROLE, record_), label)
        check("W10 negative control: window 2 is not handed it", quoted_block(phase_raw) not in driver.role_lines("S3", ROLE, {"window": "exit"}))
    finally:
        harness.cleanup(root)
    check("W10 negative control: one character changed in the constant fails the pin",
          not claims_pinned(story_run.Driver.S3_CLAIMS_LINE.replace("differs", "differz", 1), phase_raw))
    check("W10 negative control: one character changed in the phase's block fails the pin",
          not claims_pinned(story_run.Driver.S3_CLAIMS_LINE, phase_raw.replace("`differs`", "`differz`", 1)))
    check("W10 negative control: a phase with no quoted block fails the pin (an empty constant never passes)",
          not claims_pinned("", phase_raw.replace("Tell the role, verbatim", "Tell the role")))


# --- W12 / W13 / W14 / W15 --------------------------------------------------------------------------------------------------
def accepted_story(upto: int = 3):
    """A seeded story whose controller holds S0..S(upto-1) completed (the dispatch of S<upto> may be registered)."""
    root, task_root, env = seed(KEY)
    import test_controller_state as BASE
    from controller import Controller
    controller = Controller(task_root)
    controller.apply("revise_plan", {"scope": ["TC-1"], "plan_revision": "src-1", "reason": "test setup: the story's scope",
                                     "idempotency_key": "scope"})
    for number in range(upto):
        BASE.accept_stage(controller, task_root, f"S{number}")
    return root, task_root, env, controller


def dispatch_payload(stage, role, **extra):
    return dict({"id": f"d-{stage}-{role}-{len(extra)}", "stage": stage, "role": role, "scope": [], "input_hash": "h", "budget": {},
                 "known_paths": {}, "idempotency_key": f"k-{stage}-{role}-{sorted(extra)}"}, **extra)


def w13_the_word_check() -> None:
    root, task_root, _env, controller = accepted_story(3)
    try:
        def refused(payload):
            try:
                controller.apply("dispatch", payload)
            except Exception as exc:
                return type(exc).__name__, str(exc)
            return None, ""
        kind, text = refused(dispatch_payload("S3", "qa-requirements-tester", purpose="s3_labelling"))
        check("W13: the word on another role of S3 -> ValueError naming the word", kind == "ValueError" and "s3_labelling" in text, f"{kind} {text}")
        kind, text = refused(dispatch_payload("S3", ROLE, purpose="s3_labelling", rework_of="d-x"))
        check("W13: the word with rework_of -> ValueError naming the rework", kind == "ValueError" and "rework of d-x" in text, f"{kind} {text}")
        kind, text = refused(dispatch_payload("S3", ROLE, purpose="no_such_word"))
        check("W13: an unknown word -> the OLD closed-set text (the word check sits after it)",
              kind == "ValueError" and "must be one of" in text and "window 1 of S3" not in text, f"{kind} {text}")
        kind, text = refused(dispatch_payload("S3", ROLE, purpose="s3_labelling"))
        record = (controller.state().get("dispatches") or {}).get(dispatch_payload("S3", ROLE, purpose="s3_labelling")["id"]) or {}
        check("W13: on the S3 strategist -> registered, the word is in request_binding",
              kind is None and (record.get("request_binding") or {}).get("purpose") == "s3_labelling", f"{kind} {text}")
    finally:
        harness.cleanup(root)
    root, task_root, _env, controller = accepted_story(4)
    try:
        try:
            controller.apply("dispatch", dispatch_payload("S4", "qa-case-designer", purpose="s3_labelling"))
            raised = ""
        except Exception as exc:
            raised = str(exc)
        check("W13: the word on an S4 dispatch -> refused naming stage S4", "stage S4" in raised and "s3_labelling" in raised, raised)
    finally:
        harness.cleanup(root)


def w12_start_and_finish() -> None:
    root, task_root, env, _controller = accepted_story(3)
    try:
        def step(*args):
            return harness.run_script("story_step.py", *args, cwd=root, env=env)
        started = step("start", "--task", KEY, "--stage", "S3", "--role", ROLE, "--purpose", "s3_labelling")
        check("W12: start --purpose s3_labelling exits 0", started.returncode == 0, started.stdout + started.stderr)
        dispatch = "S3-qa-test-strategist-1"
        check("W12: the brief and the card are written", (task_root / "work" / "briefs" / f"{dispatch}.md").is_file()
              and any(p.name.endswith(".launch.md") for p in task_root.rglob(f"*{dispatch}*")))
        check("W12: NO handover form", not (task_root / "work" / "handoffs" / f"{dispatch}.yaml").exists())
        from controller import Controller
        stored = Controller(task_root).state()["dispatches"][dispatch]
        check_eq("W12: the dispatch records the word", (stored.get("request_binding") or {}).get("purpose"), "s3_labelling")
        import story_step
        check_eq("W12: _form_owed is False for the labelling record (where does not wait for a form)", story_step._form_owed("S3", ROLE, stored), False)
        # bytes, not text: `write_text` gives CRLF on Windows and the S3 gate `finish` now reads refuses a control character
        (task_root / "work" / "grounding.yaml").write_bytes(b"schema_version: 1\n")
        done = step("finish", "--task", KEY, "--dispatch-id", dispatch, "--digest", "d", "--not-complete", "--unresolved", "plan_pending",
                    "--reason", "window 1 accepted; the plan is window 2")
        check("W12: finish --not-complete --unresolved plan_pending exits 0", done.returncode == 0, done.stdout + done.stderr)
        state = Controller(task_root).state()
        check_eq("W12: window 1 accepted, S3 not completed",
                 (state["dispatches"][dispatch]["status"], state["stages"]["S3"]["status"] != "completed"), ("accepted", True))
        check_eq("W12: the evidence is work/grounding.yaml",
                 [r.get("path") for r in state["dispatches"][dispatch].get("evidence_refs", [])
                  if "grounding" in str(r.get("path"))], ["work/grounding.yaml"])
    finally:
        harness.cleanup(root)
    root, task_root, env, _controller = accepted_story(3)
    try:
        started = harness.run_script("story_step.py", "start", "--task", KEY, "--stage", "S3", "--role", ROLE, cwd=root, env=env)
        check("W12 control: the same start with no purpose exits 0", started.returncode == 0, started.stdout + started.stderr)
        import story_step
        from controller import Controller
        stored = Controller(task_root).state()["dispatches"]["S3-qa-test-strategist-1"]
        check_eq("W12 control: _form_owed is the registry's answer for the plan dispatch", story_step._form_owed("S3", ROLE, stored),
                 story_step._form_owed("S3", ROLE))
    finally:
        harness.cleanup(root)


def w14_exit_gate() -> None:
    import exit_gate
    import grounding_table as GT
    root, task_root, _env = seed(KEY)
    try:
        state_path = task_root / "state" / "controller.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)

        def required(dispatches):
            put_json(state_path, {"dispatches": dispatches} if dispatches is not None else [])
            with harness.project_pinned(root) if hasattr(harness, "project_pinned") else contextlib.nullcontext():
                return exit_gate.required_outputs_errors(ROLE, KEY)
        pin = pinned(root)
        with pin:
            running = {"S3-q-1": record("running")}
            check_eq("W14: window 1 running, no plan: no `missing required output`",
                     [e for e in required(running) if "missing required output" in e], [])
            with patched(GT, "check", lambda root: [GT.Finding("R1", "an empty row", "role")]):
                lines = required(running)
            check("W14: a GT role finding -> the line", lines == ["S3 window 1 (labelling): an empty row"], str(lines))
            with patched(GT, "check", lambda root: [GT.Finding("R5", "the diff moved", "driver"), GT.Finding("R8", "no index", "conductor")]):
                check_eq("W14: GT findings of the driver/conductor only -> no line", required(running), [])

            def boom(root):
                raise RuntimeError("x")
            with patched(GT, "check", boom):
                lines = required(running)
            check("W14: GT raising -> the factory's-own-defect line", len(lines) == 1 and "factory's own defect" in lines[0], str(lines))
            check("W14: no word (an exit record) -> the plan is owed (HEAD text)",
                  any("missing required output" in e for e in required({"S3-q-1": record("running", word=False)})))
            put_json(state_path, {})
            state_path.write_text("{not json", encoding="utf-8")
            check("W14: controller.json unreadable -> the plan is owed", any("missing required output" in e for e in exit_gate.required_outputs_errors(ROLE, KEY)))
        records = {"z": {"stage": "S3", "id": "z"}, "a": {"stage": "S3", "id": "a"}, "m": {"stage": "S4", "id": "m"}}
        check_eq("W14: stage_dispatch returns the LAST inserted S3 record even when its id sorts first",
                 exit_gate.stage_dispatch(records, "S3")["id"], "a")
        check_eq("W14: stage_dispatch of a non-mapping / no record -> None",
                 (exit_gate.stage_dispatch([], "S3"), exit_gate.stage_dispatch({}, "S3"), exit_gate.stage_dispatch(None, "S3")), (None, None, None))
    finally:
        harness.cleanup(root)


def pinned(root: Path):
    import hooklib
    stack = contextlib.ExitStack()
    stack.enter_context(hooklib.selftest_root_restored())
    hooklib.pin_project_root(root)
    return stack


def w15_relaunch_and_never_launched() -> None:
    import story_run
    root, task_root, _env, driver = story()
    try:
        stub_py(driver)
        stub_role(driver)
        order = []
        driver.s3_prepare = lambda: order.append("prepare")
        driver.controller = lambda op, *a, **kw: order.append("controller:" + op) or {}
        with_state(driver, {"new": record("running")})
        request = {"id": "new", "stage": "S3", "role": ROLE, "purpose": "s3_labelling", "scope": []}
        with quiet():
            driver._act_relaunch({"stage": "S3", "role": ROLE, "dispatch_request": request})
        check_eq("W15: a labelling packet is prepared BEFORE it is dispatched", order[:2], ["prepare", "controller:dispatch"])
        lines = "\n".join(driver.roles[0]["extra"])
        check("W15: ...and the role gets the window-1 lines", "write NO plan row" in lines, lines)
        # never launched
        with_state(driver, {"w1": dict(record("running"), id="w1", purpose="s3_labelling")})
        driver.state["sessions"] = {}
        driver.roles.clear()
        with quiet():
            driver._act_wait_existing_job({"dispatch_id": "w1"})
        rework = driver.roles[0]["rework"]
        check("W15: the never-launched branch never says `Rework reason: s3_labelling`",
              "Not a rework: window 1 of S3 registered and never launched" in rework.get("line", "") and "s3_labelling" not in rework.get("reason", ""), str(rework))
        # a window-2 packet over a table step 8 sends back -> a Refusal naming `release`
        import grounding_table as GT
        driver.roles.clear()
        order.clear()
        packet = {"id": "p2", "stage": "S3", "role": ROLE, "scope": []}
        with patched(GT, "check", lambda root: [finding("R1", "role", "row empty")]):
            raised = None
            with quiet():
                try:
                    driver._act_relaunch({"stage": "S3", "role": ROLE, "dispatch_request": packet})
                except story_run.Refusal as exc:
                    raised = exc
        check("W15: a window-2 relaunch step 8 would send back -> Refusal with the release door, nothing dispatched",
              raised is not None and "release" in raised.text and not driver.roles and "controller:dispatch" not in order, getattr(raised, "text", ""))
    finally:
        harness.cleanup(root)


def w16_ticket_rework() -> None:
    """The ticket re-run of S3: prepared first, ONE dispatch with both windows' lines, closes complete."""
    import claim_projector as CP
    root, task_root, _env, driver = story()
    try:
        stub_py(driver)
        calls = []
        driver.rework = lambda stage, role, cases, reason, **kw: calls.append((stage, kw)) or ("", {})
        driver.owed_rework = lambda key: ({"stages": ["S3"], "words": "new text", "before": []},
                                          {"S3-q-1": {"stage": "S3", "role": ROLE, "status": "accepted"}})
        driver.rework_dispatches = lambda *a, **kw: {}
        driver.save_state = lambda: None
        with quiet():
            moved = driver.ticket_rework_step()
        stage, kw = calls[0]
        check_eq("W16: the S3 ticket re-run is prepared BEFORE its rework", (moved, scripts_of(driver)[:1]), (True, ["blast_radius.py"]))
        lines = "\n".join(kw["extra"])
        check_not_in("W16: its lines never say `write NO plan row` (B3: one dispatch labels, then plans)", "write NO plan row", lines)
        check("W16: its lines carry the label-then-plan lead, the claims line, the plan line and the K-n/B-n reach line",
              all(part in lines for part in ("This dispatch labels work/grounding.yaml first (the fields below), then writes the plan over it",
                                             "Fill only:", driver.S3_CLAIMS_LINE, "Write work/test-plan.json", "`K-n`", "`matters: yes`", "`not_planned`")), lines)
        with patched(CP, "project", projection()):
            check_eq("W16: it closes complete (True)", kw["complete"]("d"), True)
    finally:
        harness.cleanup(root)


# --- W17 --------------------------------------------------------------------------------------------------------------------
def w17_warning_write() -> None:
    """A failed warning write is a Refusal (a state without a move: the warning was owed); a recorded warning lets window 1 run."""
    import story_run
    root, _task_root, _env, driver = story()
    try:
        stub_py(driver, {"base_slice.py": (2, "cannot read base"), "stage_done.py": (1, "pipeline.json is locked\nmore")})
        stub_role(driver)
        with_state(driver, {})
        refusal = None
        with quiet():
            try:
                driver.s3_prepare()
            except story_run.Refusal as exc:
                refusal = exc
        check("W17: stage_done.py failing is a Refusal naming both exits, the first output line and the conductor",
              refusal is not None and "base_slice.py exited 2 and the warning could not be recorded (stage_done.py exited 1: "
              "pipeline.json is locked)" in refusal.text and "conductor" in refusal.text, getattr(refusal, "text", ""))
        check_eq("W17: no role ran over the refused preparation", driver.roles, [])
        stub_py(driver, {"base_slice.py": (2, "cannot read base")})
        driver.calls.clear()
        import claim_projector as CP
        with patched(CP, "project", projection()), quiet():
            driver.stage_S3()
        check_eq("W17 control: a recorded warning lets window 1 run", (len(driver.roles), driver.roles[0]["purpose"]), (1, "s3_labelling"))
    finally:
        harness.cleanup(root)


def w18_the_slot_and_the_counted_lines() -> None:
    """G2-2: a re-dispatched window-2 packet goes through the SAME slot as `stage_S3` (AR-19), and the window-2 lines say what the code counted."""
    import grounding_table as GT
    import planning_contract as PC
    root, _task_root, _env, driver = story()
    try:
        ran = []
        driver.s3_fresh_for_window2 = lambda: ""
        driver.s3_between_windows = lambda: ran.append("slot")
        with patched(GT, "source_state", lambda r: ("diff", "")), quiet():
            driver.s3_check_packet({"id": "S3-qa-test-strategist-2", "purpose": "plan"})
            driver.s3_check_packet({"id": "S3-qa-test-strategist-3", "purpose": "repair_verify"})
        check_eq("W18: a window-2 packet runs the slot, a repair_verify packet does not", ran, ["slot"])
        driver.s3_fresh_for_window2 = lambda: "the register changed"
        ran.clear()
        import story_run
        try:
            with patched(GT, "source_state", lambda r: ("diff", "")), quiet():
                driver.s3_check_packet({"id": "S3-qa-test-strategist-4", "purpose": "plan"})
            check("W18: a packet over a stale table is refused before the slot", False)
        except story_run.Refusal:
            check_eq("W18: ...and the slot did not run", ran, [])
        cov = {"implemented": 1, "partial": 0, "n": 3, "percent": "33.3", "road": "stop", "outside": [], "reading": "", "reason": ""}
        doc = types.SimpleNamespace(data={"blast_radius": {"areas": [{"id": "B-1", "regression": "pytest a", "why": "w"},
                                                                       {"id": "B-2", "regression": "gap: no suite", "why": "w"}]}})
        with patched(GT, "coverage_of", lambda r: cov), patched(GT, "coverage_digest", lambda r, c: "abcdef012345"),                 patched(PC, "read_grounding", lambda r: (doc, None)):
            lines = driver.s3_counted_lines()
            check("W18: the lines say 1 of 3 and that no person's word stands", any("1 of 3" in l and "No person" in l for l in lines), str(lines))
            check("W18: a command of the blast radius is a line signed blast:B-1, naming tests as items (never `put this command`)",
                  any("B-1 pytest a" in l and "blast:B-1" in l and "put this command" not in l and "name these tests" in l for l in lines), str(lines))
            doc.data["blast_radius"]["areas"].append({"id": "B-3", "regression": "pytest a", "why": "w"})
            merged = [l for l in driver.s3_counted_lines() if "pytest a" in l]
            check("W18 F-3: a merged area B-1, B-3 gets ONE blast: token per area (the checker reads one per token)",
                  any("blast:B-1, blast:B-3" in l for l in merged), str(merged))
            doc.data["blast_radius"]["areas"].pop()
            check("W18: a gap is no line", not any("B-2" in l for l in lines), str(lines))
            driver.pipeline = lambda: {"stage_overrides": [{"stage": "S3", "match": f"{GT.COVERAGE_STOP_BLOCK} abcdef012345", "decision": "go on"}]}
            check("W18: with the person's word for the digest the line says so", any("decided to go on" in l for l in driver.s3_counted_lines()))
        with patched(GT, "coverage_of", lambda r: dict(cov, road="unknown")), patched(PC, "read_grounding", lambda r: (None, "x")):
            check_eq("W18: nothing measured, nothing said", driver.s3_counted_lines(), [])
    finally:
        harness.cleanup(root)


def w19_the_plan_projection() -> None:
    """RN1-2 (F-1, B-5b): `s3_project` writes the PLAN after the claims (K-1.4b, M-11), on the `old` road too, and its problems are the
    conductor's (no repair marker, K-3.5)."""
    import claim_projector as CP
    import planning_contract as PC
    import story_run
    root, _task_root, _env, driver = story()
    try:
        stub_py(driver)
        order = []
        with patched(CP, "project", lambda r, **kw: order.append("claims") or projection()(r)), \
                patched(PC, "project_plan", lambda r, **kw: order.append("plan") or types.SimpleNamespace(wrote=False, problems=[], notes=[])), quiet():
            driver.s3_project()
            check_eq("W19: the claims are projected first, the plan second", order, ["claims", "plan"])
            order.clear()
            driver.s3_project(claims=False)
            check_eq("W19: `claims=False` (the `old` road) projects the plan alone", order, ["plan"])
        with patched(CP, "project", projection()), \
                patched(PC, "project_plan", lambda r, **kw: types.SimpleNamespace(wrote=False, problems=["the register could not be read"], notes=[])), quiet():
            try:
                driver.s3_project()
                refused = None
            except story_run.Refusal as exc:
                refused = exc
            check("W19: a plan problem is a Refusal naming the projection", refused is not None and "S3 plan projection" in refused.text
                  and "the register could not be read" in refused.text, getattr(refused, "text", ""))
            check("W19: ...and it carries no repair marker (not the role's to fix)", refused is not None and story_run.REPAIR_MARKER not in refused.text)
    finally:
        harness.cleanup(root)


def w20_every_strategist_road_projects_the_plan() -> None:
    """RN1-2 fix round: B-1 (the rework roads) and B-2 (the ticket re-run after gate A was approved)."""
    import coverage_contract
    import planning_contract as PC
    import story_run
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_s3_strategist_rounds import branch, entry, plan_row
    root, task_root, _env, driver = story()
    try:
        stub_py(driver)
        (task_root / "state").mkdir(parents=True, exist_ok=True)
        (task_root / "state" / "controller.json").write_text(json.dumps({"plan_contract_mode": "new", "coverage_contract_version": 1}), encoding="utf-8")
        (task_root / "work" / "requirements-readiness.json").write_text(json.dumps({"open_questions": []}), encoding="utf-8")
        plan_path = task_root / "work" / "test-plan.json"
        marked = plan_row("TS-1", coverage_contract_revision=coverage_contract.COVERAGE_CONTRACT_REVISION)

        def write_plan(rows):
            put_json(plan_path, {"rows": rows})

        def rows_now():
            return {r["id"]: r for r in json.loads(plan_path.read_text(encoding="utf-8"))["rows"]}

        roads = {
            "completion_for (a recovered or conductor-registered rework)": lambda: driver.completion_for(
                "S3", ROLE, record("running", word=False, rework_of="S3-x-1")),
            "completion_for (repair_verify)": lambda: driver.completion_for("S3", ROLE, record("running", word=False, purpose="repair_verify")),
        }
        captured = {}
        driver.rework = lambda stage, role, cases, reason, **kw: captured.update(kw) or ("", {})
        driver.owed_rework = lambda name: ({"stage": "S3", "role": ROLE, "cause": "x", "words_file": "w.txt", "before": []}, {})
        driver.rework_dispatches = lambda *a, **kw: {}
        driver.original_words = lambda rec: ("w.txt", "the person's words")
        driver.drop_record = lambda name: None
        driver.dry = False

        def seam():
            driver.seam_rework_step()
            return captured["complete"]
        roads["seam_rework_step (the person's choice)"] = seam
        for label, road in roads.items():
            write_plan([marked, plan_row("TS-30")])                  # a row ADDED in the rework: no mark
            callable_ = road()
            with quiet():
                answer = callable_("d") if callable(callable_) else callable_
            check(f"B-1 [{label}]: the plan was projected - the added row carries the mark", rows_now()["TS-30"].get("coverage_contract_revision")
                  == coverage_contract.COVERAGE_CONTRACT_REVISION, str(rows_now()["TS-30"].get("coverage_contract_revision")))
            check_eq(f"B-1 [{label}]: ...and the answer is still False (nothing that closes S3 changed)", answer, False)
            write_plan([plan_row("TS-2", question_refs=["new:1"], if_answered=branch("new:1"), new_questions=[entry(1)]), marked])
            with quiet():
                road()("d")
            check_eq(f"B-1 [{label}]: a `new:1` raised in the rework is raised (Q1 in the register, the row rests on it)",
                     (rows_now()["TS-2"]["question_refs"],
                      [q["id"] for q in json.loads((task_root / "work" / "requirements-readiness.json").read_text(encoding="utf-8"))["open_questions"]]),
                     (["Q1"], ["Q1"]))
            put_json(task_root / "work" / "requirements-readiness.json", {"open_questions": []})
        # the rehearsal backstop: a plan that was NOT projected is named on the file again
        write_plan([marked, plan_row("TS-30")])
        lines = PC.gate_plan_errors(json.loads(plan_path.read_text(encoding="utf-8"))["rows"], "new", 1)
        check("B-1: the gate A rehearsal (`gate_plan_errors` on the file) names the missing mark of TS-30 again",
              any(line.startswith("TS-30: missing coverage_contract_revision") for line in lines), str(lines))
        check_eq("B-1: ...and the stamped plan has no such line (the S3 exit judges it stamped)",
                 [x for x in PC.gate_plan_errors(PC.stamp_revision(json.loads(plan_path.read_text(encoding="utf-8"))["rows"], "new"), "new", 1)
                  if "missing coverage_contract_revision" in x], [])
        # B-2: the ticket re-run with gate A approved closes; a rework with gate A approved refuses WITH a door
        pipeline = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))
        pipeline.setdefault("gates", {})["A"] = {"status": "approved"}
        put_json(task_root / "pipeline.json", pipeline)
        write_plan([marked, plan_row("TS-30")])
        import claim_projector as CP
        with patched(CP, "project", projection()), quiet():
            closed = driver.s3_ticket_completion()("d")
        check("B-2: the ticket re-run with gate A approved closes True and writes the mark",
              closed is True and rows_now()["TS-30"].get("coverage_contract_revision") == coverage_contract.COVERAGE_CONTRACT_REVISION, str(closed))
        write_plan([marked, plan_row("TS-31")])
        try:
            with quiet():
                driver.s3_rework_completion()("d")
            refused = None
        except story_run.Refusal as exc:
            refused = exc
        check("B-2 control: any other road keeps the approval ban, and the refusal names a door (FR-1, FR-2)",
              refused is not None and "Door:" in refused.text,
              getattr(refused, "text", ""))
        check("B-2 control: ...and the plan was not written", "coverage_contract_revision" not in rows_now()["TS-31"])
    finally:
        harness.cleanup(root)


SCENARIOS = [w1_no_new_stage, w2_routing, w3_the_live_road, w4_prepare_failures, w5_completion_matrix, w6_the_window_word,
             w7_step_eight, w8_the_lines, w9_projector_problems, w10_text_pins, w11_off_the_diff, w12_start_and_finish,
             w13_the_word_check, w14_exit_gate, w15_relaunch_and_never_launched, w16_ticket_rework, w17_warning_write, w18_the_slot_and_the_counted_lines, w19_the_plan_projection, w20_every_strategist_road_projects_the_plan]


def main() -> None:
    wanted = sys.argv[1:]
    chosen = [s for s in SCENARIOS if not wanted or any(s.__name__.startswith(prefix) for prefix in wanted)]
    if not chosen:
        sys.exit(f"test_story_run_s3_windows: no scenario starts with {wanted}; they are: " + ", ".join(s.__name__ for s in SCENARIOS))
    from story_run_common import run_scenarios
    run_scenarios([], chosen)
    harness.finish("test_story_run_s3_windows")


if __name__ == "__main__":
    main()
