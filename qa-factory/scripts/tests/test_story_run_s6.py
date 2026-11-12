"""Story-runner tests, S5 critic finish and S6 freshness (t-079, D1): the last window's critic closes S5 only
over a window record code builds; the automation branch of S6 asks the story's own record what stands, after the
stand question and before any runner; and the words the roles are told are pinned in the driver's source.

Nothing here reaches the network or a real model. The stub and the helpers live in `story_run_common`, which
imports `harness` before anything from scripts/ (harness points STORY_RUN_CLAUDE at no_claude.py).
"""
import json
import re
import subprocess
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


class _Awaits:
    """X7-6c: the `complete` of a final S6 runner window under a consumer is the open-work word `stage_awaits_acceptance` (the runner never closes
    S6 by its own finish); this compares equal to that word, whatever its reason text."""

    def __eq__(self, other):
        return type(other).__name__ == "OpenWork" and story_run_common.awaits(other) == "stage_awaits_acceptance"

    def __repr__(self):
        return "<awaits the consumer>"


AWAITS = _Awaits()
import harness  # noqa: E402
import story_run_common  # noqa: E402
from story_run_common import (  # noqa: E402
    run_scenarios,
    D1Evidence,
    D1_SAME,
    D2_DEAD,
    check,
    check_eq,
    check_in,
    check_not_in,
    d1_answer,
    d1_driver,
    d1_extras,
    d1_write_blocks,
    d2_answer,
    d2_conductor_calls,
    d2_enter,
    d2_pipeline,
    d2_seed,
    driver_for,
    eq,
    human_broken,
    s0_answer,
    s0_journal,
    s0_pipeline,
    s0_project,
    s0_question,
    s0_run,
    s0_state,
    seed,
    set_control,
    stub_calls,
)
import no_move as NM  # noqa: E402


def s5_critic_finish_passes_window() -> None:
    """t-079 (FR-5/FR-48): the last window's critic closes S5 only over a window record; code builds it
    (window_record.py) and passes it to story_step finish. A failed build: finish runs without --window."""
    task = "QA-9"
    root, task_root, env = seed(task)
    try:
        for code in (0, 2):
            driver = driver_for(root, env, task)
            calls = []

            def py(script, *args, **kwargs):
                calls.append((script, [str(a) for a in args]))
                return (code, "record failed: no receipt") if script == "window_record.py" else (0, "accepted x")
            driver.py = py
            driver.finish("S5-qa-code-critic-5", "qa-code-critic S5 W1 ok", complete=True,
                          role="qa-code-critic", stage="S5")
            names = [c[0] for c in calls]
            check_eq(f"S5 critic finish (window_record exit {code}): window_record first, then finish",
                     names, ["window_record.py", "story_step.py"])
            check_eq(f"S5 critic finish (window_record exit {code}): window_record is asked for the dispatch",
                     calls[0][1], ["--task", task, "--dispatch", "S5-qa-code-critic-5"])
            has = "--window" in calls[1][1]
            check_eq(f"S5 critic finish (window_record exit {code}): --window passed only after a built record",
                     has, code == 0)
            if has:
                check_eq("the window path is the record window_record wrote",
                         calls[1][1][calls[1][1].index("--window") + 1], "work/windows/S5-qa-code-critic-5.json")
        driver = driver_for(root, env, task)
        calls = []
        driver.py = lambda script, *args, **kwargs: (calls.append(script) or (0, "accepted x"))
        driver.finish("S5-qa-automator-4", "d", complete=False, role="qa-automator", stage="S5")
        driver.finish("S5-qa-code-critic-4", "d", complete=False, role="qa-code-critic", stage="S5")
        check_eq("no window record for a finish that leaves the stage open", calls, ["story_step.py", "story_step.py"])
    finally:
        harness.cleanup(root)


def d1_s6_freshness() -> None:
    """D1: the automation branch of S6 asks the story's own record what stands, AFTER the stand question and
    BEFORE any runner. In-process, `run_role` recorded, no claude."""
    import story_run
    task = "QA-9"
    two = {"test_a": ("result", "passed", ""), "test_b": ("result", "failed", "")}
    root, task_root, env = d2_seed(task, environment="Local", pending=False)
    pin = pin_project(root)
    try:
        # (i) every result stands: nothing launched, no runner; the receipt, the reduction, the close
        d1_blocks(root, task_root)      # HF2-11b: the test file is on disk - a result of a file that is gone does not stand
        driver, launched, moves, started = d1_driver(root, env, task)
        with D1Evidence(d1_answer(two)) as evidence:
            driver.stage_S6()
        eq("D1(i) the story's record was asked once, for the automated cases, with the run_suite stand probe",
           (len(evidence.calls), evidence.calls[0][0]), (1, ["TC-1", "TC-2"]))
        import run_suite
        check("D1(i) and with the config and the stand probe the runner itself uses",
              evidence.calls[0][1].get("probe") is run_suite.probe_runtime and evidence.calls[0][1].get("cfg") == driver.config)
        eq("D1(i) NO runner is dispatched and nothing is started", (launched, started), ([], []))
        eq("D1(i) the moves are the reduction, the receipt, the close - in that order (the receipt only over a green reduction)",
           [m[0] for m in moves], ["finalize", "code_only", "stage_done"])
        eq("D1(i) the receipt names the stage and the evidence", (moves[1][1], moves[1][3]),
           ("S6", ["work/automation-manifest.json", "state/execution-jobs"]))
        check_in("D1(i) and says what stood, with the counts", "1 passed, 1 failed - reused, nothing re-run", moves[1][2])
        eq("D1(i) finalize_task runs on the task root", Path(moves[0][1]).resolve(), task_root.resolve())
        check_in("D1(i) the close is the S6 stage_done", "--stage S6 --status done", moves[2][1])
        report = json.loads((task_root / "work" / "run-report.json").read_text(encoding="utf-8"))
        eq("D1(i) run-report.json (a real finalize_task) holds the S5 rows of both runs",
           sorted(r["instance_id"] for r in report["current_results"]), ["test_a", "test_b"])
        eq("D1(i) a red result that stands is in the whole-story report as failed",
           (report["execution_status"], report["current_totals"]), ("failed", {"failed": 1, "passed": 1}))
        eq("D1(i) and S7 sees it to triage", driver.failures_to_triage(), "failed=1")

        # (i) but the reduction fails (a corrupt run block): no receipt, no close - the runner as today, with the note
        (task_root / "work" / "run-blocks" / "x.json").write_text("{not json", encoding="utf-8")
        driver, launched, moves, started = d1_driver(root, env, task)
        with D1Evidence(d1_answer(two)):
            driver.stage_S6()
        eq("D1(i) finalize exits non-zero: only the reduction was tried - no receipt, no close",
           [m[0] for m in moves], ["finalize"])
        eq("D1(i) finalize fails: the runner is dispatched as today, whole scope, closing S6",
           [(e["stage"], e["role"], e["scope"], e["complete"]) for e in launched], [("S6", "qa-runner", ["TC-1", "TC-2"], AWAITS)])         # X7-6c: the final window awaits the consumer, it does not close S6
        check_in("D1(i) finalize fails: with the note naming the exit",
                 "The factory could not decide freshness (finalize_task exit 1): decide per instance.", d1_extras(launched))
        (task_root / "work" / "run-blocks" / "x.json").unlink()

        # (ii) one instance is stale: the runner is dispatched, told what stands and what to run
        for label, states, line in (
                ("stale", {"test_a": two["test_a"], "test_b": ("stale", "", D1_SAME)},
                 f"Results that stand: test_a; run only: test_b ({D1_SAME})."),
                ("missing", {"test_a": two["test_a"], "test_b": ("missing", "", "no run of it is on record")},
                 "Results that stand: test_a; run only: test_b (no run of it is on record).")):
            driver, launched, moves, started = d1_driver(root, env, task)
            with D1Evidence(d1_answer(states)):
                driver.stage_S6()
            eq(f"D1(ii) {label}: one qa-runner dispatch, no receipt", ([(e["stage"], e["role"]) for e in launched], moves),
               ([("S6", "qa-runner")], []))
            check_in(f"D1(ii) {label}: the runner is told what stands and what to run", line, d1_extras(launched))
            # OPEN FORK (report): the dispatch keeps the whole automation scope. A dispatch scoped to the stale
            # cases only cannot close S6 - the controller completes S6 over its derived scope by ACCEPTED
            # dispatches (`_s6_completion_problems`) - so narrowing waits for Lead's decision.
            eq(f"D1(ii) {label}: the dispatch scope is the automation scope, and closes S6 (no manual half)",
               (launched[0]["scope"], launched[0]["complete"]), (["TC-1", "TC-2"], AWAITS))         # X7-6c: awaits the consumer
        driver, launched, moves, started = d1_driver(root, env, task)
        with D1Evidence(d1_answer({"test_a": ("stale", "", D1_SAME), "test_b": ("missing", "", "none")})):
            driver.stage_S6()
        check_not_in("D1(ii) nothing stands: no `Results that stand` line, the runner runs as today", "Results that stand", d1_extras(launched))
        check_in("D1(ii) and today's instruction is still the first line", "Execution kind: automation", d1_extras(launched))

        # (iii) the factory cannot decide: the runner as today, with the note (P1)
        long_text = "x" * 200
        for label, answer, why in (
                ("the evidence function raises", RuntimeError("boom"), "RuntimeError: boom"),
                ("a message AT the 200 limit is whole", ValueError(long_text), "ValueError: " + long_text),
                ("a message BEYOND it is cut", ValueError(long_text + "y"), "ValueError: " + long_text + story_run.Driver.CUT),
                ("the stand was not observed", d1_answer({"test_a": ("unknown", "", "the stand's version was not observed")}, observed=False),
                 "the stand's version was not observed"),
                ("no budget data (nothing decided, no instances)", {"instances": {}, "observed": False, "why": "run-budget.json cannot be read"},
                 "run-budget.json cannot be read"),
                ("an empty answer", d1_answer({}), "no test of these cases could be listed"),
                ("a state it does not know", d1_answer({"test_a": ("weird", "", "")}), "test_a: state `weird`"),
                ("a result whose outcome it cannot count", d1_answer({"test_a": ("result", "inconclusive", "")}), "test_a: state `result` with outcome `inconclusive`")):
            driver, launched, moves, started = d1_driver(root, env, task)
            with D1Evidence(answer):
                driver.stage_S6()
            eq(f"D1(iii) {label}: the runner is dispatched as today, no receipt", ([(e["stage"], e["role"]) for e in launched], moves),
               ([("S6", "qa-runner")], []))
            check_in(f"D1(iii) {label}: with the note and its reason", "The factory could not decide freshness (" + why, d1_extras(launched))
            check_in(f"D1(iii) {label}: and the instruction to decide per instance", "): decide per instance.", d1_extras(launched))
            eq(f"D1(iii) {label}: the whole automation scope, awaiting the consumer (X7-6c)", (launched[0]["scope"], launched[0]["complete"]),
               (["TC-1", "TC-2"], AWAITS))

        # a manual half is still to run: the receipt would close the WHOLE stage, so the runner goes as today
        driver, launched, moves, started = d1_driver(root, env, task, manual=("TC-9",))
        with D1Evidence(d1_answer(two)) as evidence:
            driver.stage_S6()
        eq("D1 manual present, every result stands: no receipt (it would close the manual half's stage too)", moves, [])
        eq("D1 manual present: the automation runner goes as today, not closing the stage", (len(launched), launched[0]["complete"]), (1, False))
        check_in("D1 manual present: and is told what stands", "Results that stand: test_a, test_b; run only: nothing.", d1_extras(launched))
        eq("D1 manual present: the manual block is for the loop's next entry", started, [])
        driver, launched, moves, started = d1_driver(root, env, task, manual=("TC-9",), accepted_auto=True)
        with D1Evidence(d1_answer(two)) as evidence:
            driver.stage_S6()
        eq("D1 manual present, the automation half accepted: the manual block still runs, nothing is asked or dispatched",
           (started, launched, moves, evidence.asked), ([("S6", "manual")], [], [], []))

        # the other edges: nothing is asked where nothing is to run
        driver, launched, moves, started = d1_driver(root, env, task, accepted_auto=True)
        with D1Evidence(d1_answer(two)) as evidence:
            driver.stage_S6()
        eq("D1 edge: `auto_done` and no manual half: unchanged - nothing asked, dispatched or closed",
           (evidence.asked, launched, moves, started), ([], [], [], []))
        driver, launched, moves, started = d1_driver(root, env, task, auto=(), manual=("TC-9",))
        with D1Evidence(d1_answer(two)) as evidence:
            driver.stage_S6()
        eq("D1 edge: an empty automation scope (a handed case is out of it already): only the manual block, nothing asked",
           (evidence.asked, launched, moves, started), ([], [], [], [("S6", "manual")]))
        driver, launched, moves, started = d1_driver(root, env, task, auto=(), manual=())
        with D1Evidence(d1_answer(two)) as evidence:
            driver.stage_S6()
        eq("D1 edge: nothing to execute at all is today's code-only close, the record is not asked",
           ([m[:2] for m in moves if m[0] == "code_only"], [m[0] for m in moves], evidence.asked),
           ([("code_only", "S6")], ["finalize", "code_only", "stage_done"], []))
    finally:
        unpin_project(pin)
        harness.cleanup(root)

    # POSITIONAL: the stand question is before the record. An unconfirmed stand asks, and nothing has been
    # asked of the record, dispatched or closed when it does (the invariant `stand_check` documents).
    root, task_root, env = d2_seed(task, environment="Local", pending=True, url=D2_DEAD)
    try:
        d1_write_blocks(task_root)
        driver, launched, moves, started = d1_driver(root, env, task)
        with D1Evidence(d1_answer(two)) as evidence:
            code = d2_enter(driver, "S6")
        eq("D1 position: an unconfirmed stand asks its question first: exit 3", code, 3)
        eq("D1 position: and before it the record was not asked, no runner, no receipt, no close",
           (evidence.asked, launched, moves, started), ([], [], [], []))
        check_in("D1 position: it is the stand question", "kind: environment", s0_question(task_root))
    finally:
        harness.cleanup(root)


def d1_texts() -> None:
    """D2: what the roles are told. The texts sit inside long methods, so they are read from the source as
    the string constants they are (an f-string is its literal parts) - a pin on the words, not on the layout."""
    import ast
    texts, parts = [], set()
    nodes = [node for _path, source in harness.driver_sources() for node in ast.walk(ast.parse(source))]      # every file of the driver set, parsed apart
    for node in nodes:
        if isinstance(node, ast.JoinedStr):
            parts.update(id(p) for p in node.values)      # its literal pieces are counted once, whole
            texts.append("".join(p.value for p in node.values if isinstance(p, ast.Constant)))
    for node in nodes:
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in parts:
            texts.append(node.value)
    whole = "\n".join(texts)
    check_in("D2 critic: probe_by_code once per instance, every check of the test",
             "then probe_by_code.py once per instance, every check of the test: ", whole)
    check_in("D2 critic: red_sandbox only on doubt, proves only the one check it names, the others stay owed",
             "red_sandbox.py --probe (only when you doubt the check looks at the product, with the reason in your findings) proves only the one check it names, the others stay owed", whole)
    check_in("D2 critic: a probe of unchanged bytes and the same entries is answered already_probed", "a probe of unchanged bytes and the same entries is answered `already_probed`", whole)
    check_in("D2 critic: the rest is kept", "write your findings file and the review_receipt_ref on the manifest bindings; `cause:` on each finding.", whole)
    words = "re-run only the instances whose code changed; a comment/docstring/marker-only fix keeps its run (the factory answers `reused`)."
    eq("D2 rework: both S5 repair texts (the test-defect round and the mechanical one) say it", whole.count(words), 2)
    check_not_in("D2 rework: and neither says `files changed` any more", "whose files changed", whole)
    check_in("D2 S7 repair: re-run only the failed test through --mine, node id, repair_verify",
             "--node-id <test> --purpose repair_verify`; FLAKY confirmation per s7.md (at most 3 flaky_diagnostic runs, S7).", whole)
    check_not_in("D2 S7 repair: the old `--request` wording is gone", "run_suite.py --request with purpose repair_verify", whole)


# --- t-261: the manual half of S6 (t-250 §1, C2, C4) --------------------------------------------------------------
# TP1-15045 (cmp2): `run_manual_block` sent all eleven manual cases in one dispatch (the controller refuses a block
# of more than five), and `manual_evidence.prepare` refused every one. The driver now prepares each case by code, never
# dispatches a refused one, and dispatches the rest in blocks of at most five, ONE per entry, in plan-row order.

class ManualWorld:
    """The controller's dispatch table as the driver reads it, and a stand-in for `Controller` that registers a manual
    dispatch into it. `accept(id)` is the controller accepting what a runner finished."""

    def __init__(self):
        self.dispatches = {}
        self.waits = []          # the `wait_seconds` of every Controller the driver built (M8: a lifecycle command waits)

    def accept(self, dispatch_id):
        self.dispatches[dispatch_id]["status"] = "accepted"

    def controller_class(self):
        world = self

        class FakeController:
            def __init__(self, task_root, wait_seconds=0.0):
                world.waits.append(wait_seconds)

            def state(self):
                return {"dispatches": world.dispatches}

            def prepare(self, options):
                return {"dispatch_request": {"id": options["id"], "stage": options["stage"], "role": options["role"],
                                             "scope": list(options["scope"])}}

            def apply(self, operation, request):
                assert operation == "dispatch"
                world.dispatches[request["id"]] = dict(request, status="running")
        return FakeController


def manual_rig(root, env, task, cases, refused=(), world=None, auto_dispatches=(), policy="api"):
    """(driver, world, launched role calls, moves, printed text getter) with `cases` the manual scope: `refused` names the
    cases `prepare` refuses; every seam that would start a process or a model is replaced. `policy` is what
    `manual_policy` answers (t-292): one word for every case, a {case: word} map (an absent case is `api`), or a
    function - the default `api` keeps every older check away from the stand-login question."""
    world = world or ManualWorld()
    driver = driver_for(root, env, task)
    launched, moves = [], []
    # a story at the manual half has its run report from the automated half: `walk_before` (t-1957) finalizes only when it is absent, so
    # the pins below on WHERE the reduction sits count the close's own finalize, not the walker's
    report = Path(driver.task_root) / "work" / "run-report.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    if not report.is_file():
        report.write_text("{}", encoding="utf-8")
    driver.controller_state = lambda: {"dispatches": world.dispatches}
    driver.manual_order = lambda given: list(given)
    driver.MANUAL_BLOCK_MAX = 5     # SC2-38 item 3: the default window is one case; the older checks here keep their blocks of five
    driver.manual_prepare = lambda case: ([], f"the check could not be taken: {case} stands as not checked by hand", "") \
        if case in refused else ([f"OB-{case}"], "", "")
    driver.manual_policy = policy if callable(policy) else (
        (lambda case: policy.get(case, "api")) if isinstance(policy, dict) else (lambda case: policy))
    driver.manual_gate_note = lambda: None
    driver.manual_request_paths = lambda block: [f"work/evidence/manual/{c}/request.json" for c in block]
    driver.run_role = lambda stage, role, **kw: launched.append(dict(kw, stage=stage, role=role)) or ("", None)
    driver.code_only = lambda stage, reason, evidence: moves.append(("code_only", stage, reason, list(evidence)))
    real_py = driver.py

    def py(script, *args, **kwargs):
        if script == "stage_done.py":
            if "running" in args:          # the block's own `--status running` is not a closing move
                return 0, ""
            moves.append(("stage_done", " ".join(str(a) for a in args)))
            return 0, ""
        if script == "finalize_task.py":
            moves.append(("finalize", str(args[0])))
            return 0, ""
        return real_py(script, *args, **kwargs)
    driver.py = py
    return driver, world, launched, moves


def record_failure_analyst_accept(driver, dispatch_id):
    """X7-6c: S6 closes only over the consumer's (failure analyst's) `accept` record for the author's last dispatch, never on the runner's own
    word; the rig's accepted runner dispatch has been judged by the analyst (the record written the way `stage_done.py --acceptance` writes it)."""
    story_run_common.accept_record(driver.task_root, "S6", dispatch_id)


def enter_manual(driver, world, cases, accept=True):
    """One entry: `run_manual_block` with the controller replaced; the new dispatch is ACCEPTED afterwards when asked to
    be (the runner finished). (the printed text, the dispatch id registered or "")."""
    import contextlib
    import io
    from unittest import mock
    before = set(world.dispatches)
    out = io.StringIO()
    with mock.patch("controller.Controller", world.controller_class()), contextlib.redirect_stdout(out):
        driver.run_manual_block(list(cases))
    new = sorted(set(world.dispatches) - before)
    if accept:
        for dispatch_id in new:
            world.accept(dispatch_id)
            record_failure_analyst_accept(driver, dispatch_id)
    return out.getvalue(), (new[0] if new else "")


def t261_k2_the_blocks_of_five_and_the_refused_are_not_dispatched() -> None:
    """K2: 7 accepted + 4 refused -> blocks [5, 2] and 4 `not checked` lines; 5 -> [5]; 6 -> [5, 1]; 11 -> [5, 5, 1]; and
    the position/stage rules: ONE dispatch per entry, only the LAST block completes (and only when nothing was refused,
    because the controller refuses a completion over a case no accepted dispatch carried); no block left -> the manual
    half closes with no runner (finalize, then the code-only receipt, then stage_done)."""
    import story_run
    task = "QA-9"
    root, task_root, env = d2_seed(task, environment="Local", pending=False)
    try:
        names = lambda n, tag="TC": [f"QA-9_{tag}_{i:03d}" for i in range(1, n + 1)]
        driver, world, launched, moves = manual_rig(root, env, task, [])
        for ready_n, expected in ((0, []), (1, [1]), (4, [4]), (5, [5]), (6, [5, 1]), (10, [5, 5]), (11, [5, 5, 1]), (12, [5, 5, 2])):
            cases = names(ready_n)
            plan = driver.manual_plan(cases)
            check_eq(f"blocks of {ready_n} prepared cases: {expected}", [len(b) for b in plan["blocks"]], expected)
            check_eq(f"{ready_n} prepared cases: the cases are in the given (plan-row) order, none lost",
                     [c for b in plan["blocks"] for c in b], cases)
        # K2 as stated: 7 accepted + 4 refused
        ready, bad = names(7), names(4, "BAD")
        scope = [c for pair in zip(ready[:4], bad) for c in pair] + ready[4:]       # refused cases between the others
        driver, world, launched, moves = manual_rig(root, env, task, scope, refused=bad)
        plan = driver.manual_plan(scope)
        check_eq("K2: 7 accepted + 4 refused -> blocks [5, 2]", [len(b) for b in plan["blocks"]], [5, 2])
        check_eq("K2: and the four refused are named, each with its words", [c for c, _w in plan["refused"]], bad)
        # entry 1: the first block only, and it does NOT complete the stage (a second block and refused cases follow)
        text, first = enter_manual(driver, world, scope)
        check_eq("entry 1: exactly one dispatch, scope the first five prepared cases, in order",
                 [(e["role"], e["scope"], e["complete"]) for e in launched], [("qa-runner", ready[:5], False)])
        check_eq("entry 1: the dispatch is registered as a manual block of those five (the controller's own field)",
                 (world.dispatches[first]["execution_kind"], world.dispatches[first]["manual_case_ids"]), ("manual", ready[:5]))
        check_eq("K2: four `not checked` lines, one per refused case", len([ln for ln in text.splitlines() if "not checked by hand" in ln]), 4)
        for case in bad:
            check_in(f"the line names {case} and its refusal", f"S6: {case}: not checked by hand — the check could not be taken", text)
        check_in("the runner is told the prepared request of each case of the block, by path",
                 f"work/evidence/manual/{ready[0]}/request.json", " ".join(launched[0]["extra"]))
        # entry 2: the second block (two cases) - still not closing: the refused cases are outside any dispatch's cover
        text, second = enter_manual(driver, world, scope)
        check_eq("entry 2: one more dispatch, the two left, `--not-complete` because four were refused",
                 [(e["scope"], e["complete"]) for e in launched[1:]], [(ready[5:], AWAITS)])         # X7-6c: the last block awaits the consumer
        check_eq("entry 2: and the four lines are said again (each entry is a fresh reading of the plan)",
                 len([ln for ln in text.splitlines() if "not checked by hand" in ln]), 4)
        check_eq("no finalize and no receipt yet", moves, [])
        # entry 3: nothing left to dispatch: the manual half closes with no runner
        text, third = enter_manual(driver, world, scope)
        check_eq("entry 3: no new dispatch and no role call", (third, len(launched)), ("", 2))
        check_eq("entry 3: the reduction FIRST, then the code-only receipt, then the close",
                 [m[0] for m in moves], ["finalize", "code_only", "stage_done"])
        check_eq("the receipt names the stage and the evidence: the run report and each refused case's request",
                 (moves[1][1], moves[1][3]) if len(moves) > 1 else None,
                 ("S6", ["work/run-report.json"] + [f"work/evidence/manual/{c}/request.json" for c in bad]))
        check_in("and says how many were checked and which were not", "7 case(s) checked by an agent by hand, 4 not checked: " + ", ".join(bad),
                 moves[1][2] if len(moves) > 1 else "")
        # a refused case is NEVER in any dispatch scope (the mutation: a refused case dispatched anyway)
        check_eq("no refused case appears in any dispatch scope",
                 [c for e in launched for c in e["scope"] if c in bad], [])
        # 5 -> one block that closes the stage; 6 -> [5] then [1] that closes it; 11 -> [5] [5] [1]
        for n, flags in ((5, [AWAITS]), (6, [False, AWAITS]), (11, [False, False, AWAITS])):         # X7-6c: the LAST block awaits the consumer
            driver, world, launched, moves = manual_rig(root, env, task, [])
            cases = names(n)
            for _ in flags:
                enter_manual(driver, world, cases)
            check_eq(f"{n} prepared cases, none refused: the blocks' `complete` flags (only the LAST block closes S6)",
                     [e["complete"] for e in launched], flags)
            check_eq(f"{n} prepared cases: the dispatches' scopes are the blocks, in order",
                     [len(e["scope"]) for e in launched], {5: [5], 6: [5, 1], 11: [5, 5, 1]}[n])
            check_eq(f"{n} prepared cases: nothing is closed by code (the last runner closes it)", moves, [])
        # 0 prepared: no runner, the manual half closes with the lines
        bad = names(3, "BAD")
        driver, world, launched, moves = manual_rig(root, env, task, bad, refused=bad)
        text, new = enter_manual(driver, world, bad)
        check_eq("0 accepted: no runner, no dispatch", (launched, new), ([], ""))
        check_eq("0 accepted: the three lines, then the manual half closes code-only",
                 (len([ln for ln in text.splitlines() if "not checked by hand" in ln]), [m[0] for m in moves]),
                 (3, ["finalize", "code_only", "stage_done"]))
        # the reduction fails: nothing is closed over a report nobody could build
        driver, world, launched, moves = manual_rig(root, env, task, bad, refused=bad)
        real = driver.py
        driver.py = lambda script, *a, **k: (1, "boom: corrupt run block") if script == "finalize_task.py" else real(script, *a, **k)
        try:
            enter_manual(driver, world, bad)
            check("a failing reduction is a refusal", False)
        except story_run.Refusal as refusal:
            check_in("a failing reduction is a refusal that names it", "finalize_task.py exit 1", refusal.text)
        check_eq("...and no receipt was written", [m for m in moves if m[0] != "finalize"], [])
    finally:
        harness.cleanup(root)


def test_manual_block_dispatches_unprepared() -> None:
    """F5(c) (t-1936 N5, B-15; SLOW, CI judges): a case the FACTORY failed to prepare is dispatched in the same block as the
    prepared ones (the factory never stands), the runner is told its reason in one line that forbids a result, and the driver
    prints it; a case the STORY refuses stays out of every scope. Control: a prepared case gets no such line."""
    task = "QA-9"
    root, task_root, env = d2_seed(task, environment="Local", pending=False)
    try:
        ready, walked, refused = f"{task}_TC_001", f"{task}_TC_002", f"{task}_BAD_001"
        reason = "the plan gives TC_002's check an evidence rule that is not one word"
        driver, world, launched, moves = manual_rig(root, env, task, [ready, walked, refused], refused=[refused])
        base = driver.manual_prepare
        driver.manual_prepare = lambda case: ([f"OB-{case}"], "", reason) if case == walked else base(case)
        text, first = enter_manual(driver, world, [ready, walked, refused])
        check_eq("the prepared and the unprepared case share one dispatch; the refused one is outside it",
                 [e["scope"] for e in launched], [[ready, walked]])
        check_in("the driver says the case is walked unprepared, with the reason", f"S6: {walked}: unprepared - {reason}", text)
        lines = [ln for ln in launched[0]["extra"] if "unprepared" in ln]
        check_eq("the runner gets exactly one unprepared line, for the walked case", len(lines), 1)
        check_in("...that names the case and the reason", f"{walked}: unprepared - {reason}", lines[0])
        check_in("...and forbids a result", "record no pass or fail", lines[0])
        check_not_in("the prepared case has no such line", ready + ": unprepared", " ".join(launched[0]["extra"]))
        check_in("the refused case is still named as not checked", f"S6: {refused}: not checked by hand", text)
    finally:
        harness.cleanup(root)


def t261_resume_after_a_crash_between_blocks_and_the_recovery_rule() -> None:
    """C4: the done blocks are the controller's accepted dispatches, so a FRESH driver after a crash dispatches the next
    block and never the first again; a block that crashed (running, never accepted) is judged by `completion_for` on
    recovery with the same rule the dispatch used."""
    task = "QA-9"
    root, task_root, env = d2_seed(task, environment="Local", pending=False)
    try:
        cases = [f"QA-9_TC_{i:03d}" for i in range(1, 12)]
        driver, world, launched, moves = manual_rig(root, env, task, cases)
        enter_manual(driver, world, cases)                              # block 1 accepted
        check_eq("setup: block 1 went", [len(e["scope"]) for e in launched], [5])
        fresh, _w, launched2, moves2 = manual_rig(root, env, task, cases, world=world)     # a relaunch: new driver, same controller
        enter_manual(fresh, world, cases)
        check_eq("after the crash the NEXT block goes (cases 6-10), not block 1 again",
                 [e["scope"] for e in launched2], [cases[5:10]])
        check_eq("...and it does not close the stage (one more block is left)", [e["complete"] for e in launched2], [False])
        # a crash INSIDE a block: registered, never accepted -> not done; the recovery path asks completion_for
        crashed, w2, l3, m3 = manual_rig(root, env, task, cases)
        enter_manual(crashed, w2, cases, accept=False)
        running = next(iter(w2.dispatches.values()))
        check_eq("setup: the crashed block is `running`, so it is not done", (running["status"], crashed.manual_done()), ("running", set()))
        # completion_for on recovery, with the scope and the preparation replaced
        def completion(record, scope, refused=(), done=()):
            d, w, _l, _m = manual_rig(root, env, task, scope, refused=refused)
            for i, ids in enumerate(done, 1):
                w.dispatches[f"S6-qa-runner-{i}"] = {"stage": "S6", "status": "accepted", "execution_kind": "manual", "manual_case_ids": ids}
            d.stage_scope = lambda stage, kind="": {"scope": list(scope)}
            return d.completion_for("S6", "qa-runner", record)
        last = {"execution_kind": "manual", "manual_case_ids": cases[10:], "scope": cases[10:]}
        check_eq("recovery: the LAST block (nothing else left) closes the stage", completion(last, cases, done=[cases[:5], cases[5:10]]), AWAITS)         # X7-6c: the closing window awaits the consumer
        check_eq("recovery: a block with another still to go does not", completion(dict(last, manual_case_ids=cases[5:10], scope=cases[5:10]), cases, done=[cases[:5]]), False)
        check_eq("recovery: the last block awaits the consumer though a case was refused (X7-6; manual_close closes the refused case later)",
                 completion(last, cases, refused=[cases[0]], done=[cases[1:5], cases[5:10]]), AWAITS)
        auto = {"execution_kind": "automation", "scope": ["QA-9_TC_900"]}
        check_eq("recovery: the AUTOMATION runner does not close S6 while a manual half is left", completion(auto, cases), False)
        check_eq("recovery: ...and does when there is none", completion(auto, []), AWAITS)         # X7-6c
        d, w, _l, _m = manual_rig(root, env, task, cases)
        d.stage_scope = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("controller down"))
        check_eq("recovery: a scope that cannot be read closes nothing (a doubt never closes a stage)",
                 d.completion_for("S6", "qa-runner", last), False)
        check_eq("recovery: another stage's roles keep their own rule (a scout is the default)",
                 d.completion_for("S1", "qa-scout", {}), None)
    finally:
        harness.cleanup(root)


def t261_the_real_controller_refuses_a_completion_over_an_undispatched_case_and_takes_the_code_only_receipt() -> None:
    """The premise of C4 against the REAL controller (the helpers of test_fixes_13797.py, F5): a runner dispatch that
    would complete S6 while a manual-agent case of the derived scope was never dispatched (a case `prepare` refused) is
    refused - which is why the driver sends the last block `--not-complete` when anything was refused - and the code-only
    receipt (`finalize_task`, then `code_only`, then `stage_done`: what `manual_close` writes) closes S6 over that case."""
    import test_fixes_13797 as F
    root = harness.temp_dir("qa-t261-controller-")
    try:
        c = F.s6_story(root)
        refused = F.runner(c, root, "S6-auto", "automation", ["TC-1"], True)
        check_in("a completion over a derived manual case nobody dispatched is refused by the controller (C4's premise)",
                 "manual-agent case TC-2 has no accepted S6 dispatch", refused)
        check_eq("...and S6 stays open", c.state()["stages"]["S6"]["status"], "running")
        check_eq("the same acceptance with `--not-complete` goes through", F.runner(c, root, "S6-auto", "automation", ["TC-1"], False), "")
        evidence = F.BASE.evidence_ref(root, "run-report.json", "{}")
        c.apply("code_only", {"id": "S6-code-only-1", "stage": "S6", "reason": "the manual half of S6: 0 case(s) checked, 1 not checked: TC-2",
                              "evidence_refs": [evidence], "expected_revision": c.state().get("revision", 0),
                              "idempotency_key": "code_only:S6:1"})
        check_eq("the code-only receipt closes S6 with TC-2 never dispatched",
                 (c.state()["stages"]["S6"]["status"], c.state()["stages"]["S6"].get("code_only")), ("completed", True))
    finally:
        harness.cleanup(root)


def t261_prepare_by_code_on_the_cmp2_shape_and_the_temporal_door() -> None:
    """The real `manual_evidence.prepare` over the cmp2-shaped task (scaffold of test_manual_capture): a plan approved
    BEFORE the pass keeps `decision: new`, so every case is refused - naming a door the driver can use (FR-57: the case
    stands as not checked, or gate A is approved again); once the pass has run, TS-7 and TS-12 are prepared and TC_015
    (R-19, implementation-only) is still refused as an unconfirmed expectation (C2) - the free negative control."""
    sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "manual-evidence"))
    import scaffold as S
    import planning_contract as PC
    import story_run
    import manual_evidence as ME
    t = S.make_task(manual=())
    try:
        harness.use_project(t.project)
        shim = types.SimpleNamespace(task_root=t.task)
        manual = [S.CASES["ui"], S.CASES["api"], S.CASES["impl"]]
        words = "\n".join(f"{c}: manual" for c in manual[1:])          # TS-7 is a manual-agent row already; 12 and 15 are the person's words
        # before: the plan as cmp2 approved it - TS-7 is a manual-agent row whose obligation still says `new`
        with t.patched():
            ids, why, _walk = story_run.Driver.manual_prepare(shim, S.CASES["ui"])
        check_eq("temporal: a plan approved before the pass: TC_007 is refused, with no obligation id", (ids, bool(why)), ([], True))
        check_in("...naming what is wrong in words", "the approved plan still has this check as `new`", why)
        check_in("...and a door the driver can use (FR-57): gate A again, or the case stands as not checked", "stands as not checked by hand", why)
        check_in("...and the orchestrator's operation", "semantic_reopen", why)
        written = json.loads(ME.request_path(t.task, S.CASES["ui"]).read_text(encoding="utf-8"))
        check_eq("the refusal is on disk for the report: {refused: {reason, door}} and nothing else",
                 (sorted(written), sorted(written["refused"])), (["refused"], ["door", "reason"]))
        # after: gate A applied the pass (the person said `<TC_012>: manual`, `<TC_015>: manual`)
        PC.apply_gate_answers(t.task, words)
        with t.patched():
            ui = story_run.Driver.manual_prepare(shim, S.CASES["ui"])
            api = story_run.Driver.manual_prepare(shim, S.CASES["api"])
            impl = story_run.Driver.manual_prepare(shim, S.CASES["impl"])
        check_eq("after the pass: TC_007 is prepared (OB-7)", ui, (["OB-7"], "", ""))
        check_eq("after the pass: TC_012 is prepared (OB-12, policy api)", api, (["OB-12"], "", ""))
        check_eq("C2: TC_015 is refused, no obligation id", impl[0], [])
        check_in("C2: as an unconfirmed expectation", "expectation unconfirmed", impl[1])
        check("the prepared case's request.json is the request, the refused one's is the refusal",
              "refused" not in json.loads(ME.request_path(t.task, S.CASES["ui"]).read_text(encoding="utf-8"))
              and "refused" in json.loads(ME.request_path(t.task, S.CASES["impl"]).read_text(encoding="utf-8")))
        # plan-row order: the scope is given in another order; the plan's rows decide (TS-7, TS-12, TS-15)
        check_eq("plan-row order, whatever order the scope names the cases in",
                 story_run.Driver.manual_order(shim, [S.CASES["impl"], S.CASES["api"], S.CASES["ui"]]), manual)
        # an unexpected failure is a refusal too, written for the report - never a dispatch on a doubt
        real = ME.prepare_to_file
        ME.prepare_to_file = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
        try:
            ids, why, _walk = story_run.Driver.manual_prepare(shim, S.CASES["ui"])
        finally:
            ME.prepare_to_file = real
        check_eq("an unexpected failure of prepare: refused (no ids), the failure named", (ids, "OSError: disk full" in why), ([], True))
        check_in("...and written where the report reads it", "OSError: disk full",
                 json.loads(ME.request_path(t.task, S.CASES["ui"]).read_text(encoding="utf-8"))["refused"]["reason"])
    finally:
        S.cleanup(t)


def t289_real_story(root, manual_n):
    """A story in the NEW plan-contract mode through gate A and S5: TC-1 is automated, TC-2..TC-(manual_n+1) are
    manual-agent rows (the shape of `test_fixes_13797.s6_story`, with more manual cases). Returns the real controller."""
    import test_fixes_13797 as F
    import test_controller_state as BASE
    import test_controller_rework_scope as SCOPED
    from controller import Controller
    cases = [f"TC-{i}" for i in range(1, manual_n + 2)]
    (root / "qa-factory").mkdir(parents=True, exist_ok=True)
    (root / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
    c = Controller(root)
    c.apply("initialize", {"scope": cases, "source_revision": "src-1", "known_paths": {"root": str(root)}, "idempotency_key": "init"})
    for number in range(5):
        BASE.accept_stage(c, root, f"S{number}")
    BASE.seed_plan(root, [SCOPED.plan_row(1, "automate")] + [SCOPED.plan_row(i, "manual-agent") for i in range(2, len(cases) + 1)])
    (root / "state" / "story-case-links.json").write_text(json.dumps({"links": [
        {"case_id": case, "version": f"cv_{i}"} for i, case in enumerate(cases, 1)]}), encoding="utf-8")
    decision = {"id": "gate-a", "gate": "A", "action": "approve", "status": "approved", "authorization_source": "human",
                "source_revision": "src-1", "scope": cases, "input_revision": "src-1", "idempotency_key": "gate-a"}
    c.apply("decision", BASE.bind_gate_a(root, decision))
    BASE.accept_stage(c, root, "S5")
    return c, F


def t289_manual_block_goes_through_the_real_prepare_and_a_refusal_is_a_text() -> None:
    """t-289 (live S6 rehearsal, cmp2r): in `plan_contract_mode: new` the REAL `controller.prepare` demands the
    `execution_kind` of a qa-runner packet and validates a manual block, and the driver added both only after `prepare`:
    it died with a ValueError and a traceback. Here no fake controller stands in: K-PREP (the packet is prepared with the
    kind and the block, the dispatch is registered with them), K-RES (a second block after the first is accepted goes as
    the NEXT dispatch, the first never again; no block left -> the manual half closes), and a block the controller
    refuses is the driver's own `Refusal`, never a traceback."""
    import contextlib
    import io
    from unittest import mock
    import story_run
    task = "QA-9"
    root, task_root, env = d2_seed(task, environment="Local", pending=False)
    ctl_root = harness.temp_dir("qa-t289-controller-")
    try:
        c, F = t289_real_story(ctl_root, 6)
        manual = [f"TC-{i}" for i in range(2, 8)]
        check_eq("setup: the story is in the NEW plan-contract mode (the premise of the failure)", c.state().get("plan_contract_mode"), "new")
        # the premise, against the real controller: without the kind `prepare` itself refuses (the mutation's own symptom)
        try:
            c.prepare({"stage": "S6", "role": "qa-runner", "id": "probe", "scope": manual[:2]})
            check("the real prepare refuses a qa-runner packet with no execution_kind", False)
        except ValueError as exc:
            check_in("the real prepare refuses a qa-runner packet with no execution_kind", "requires execution_kind", str(exc))
        check_eq("setup: the automation half is accepted first (as in the rehearsal), not closing the stage",
                 F.runner(c, ctl_root, "S6-qa-runner-1", "automation", ["TC-1"], False), "")

        def rig(size=2):
            driver, world, launched, moves = manual_rig(root, env, task, manual)
            driver.controller_state = lambda: c.state()           # the REAL dispatch table: what is accepted is what is done
            driver.MANUAL_BLOCK_MAX = size

            def enter():
                out = io.StringIO()
                with mock.patch("controller.Controller", lambda _root, wait_seconds=0.0: c), contextlib.redirect_stdout(out):
                    driver.run_manual_block(list(manual))
                return out.getvalue()
            return driver, launched, moves, enter

        # K-PREP: the first block of two, through the real prepare and the real apply
        driver, launched, moves, enter = rig()
        text = enter()
        first = c.state()["dispatches"].get("S6-qa-runner-2") or {}
        check_eq("K-PREP: the block is registered by the real controller as a manual block of those two cases",
                 (first.get("execution_kind"), first.get("manual_case_ids"), first.get("scope")), ("manual", manual[:2], manual[:2]))
        check_eq("K-PREP: and the runner is launched on that block, not closing the stage (two blocks follow)",
                 [(e["scope"], e["complete"]) for e in launched], [(manual[:2], False)])
        check_in("K-PREP: the block line is said", "S6: manual block of 2 case(s), 2 more block(s) after it: " + ", ".join(manual[:2]), text)
        # K-RES: the first block is accepted; a FRESH driver goes on with the next block, never the first again
        check_eq("setup: the runner finishes the first block", F.runner(c, ctl_root, "S6-qa-runner-2", "manual", manual[:2], False), "")
        driver, launched, moves, enter = rig()
        enter()
        check_eq("K-RES: the second block is the NEXT dispatch with the next two cases",
                 [(e["scope"], e["complete"]) for e in launched], [(manual[2:4], False)])
        check_eq("K-RES: registered as such", (c.state()["dispatches"]["S6-qa-runner-3"]["manual_case_ids"],
                                               c.state()["dispatches"]["S6-qa-runner-3"]["execution_kind"]), (manual[2:4], "manual"))
        check_eq("setup: the second block is accepted", F.runner(c, ctl_root, "S6-qa-runner-3", "manual", manual[2:4], False), "")
        driver, launched, moves, enter = rig()
        enter()
        check_eq("K-RES: the LAST block closes the stage and is the third manual dispatch",
                 [(e["scope"], e["complete"]) for e in launched], [(manual[4:], AWAITS)])         # X7-6c
        check_eq("setup: the last block is accepted, closing S6", F.runner(c, ctl_root, "S6-qa-runner-4", "manual", manual[4:], True), "")
        check_eq("K-RES: S6 is completed by the accepted dispatches", c.state()["stages"]["S6"]["status"], "completed")
        # a block the CONTROLLER refuses (6 cases > the limit of five) is the driver's Refusal with the controller's words
        fresh_root = harness.temp_dir("qa-t289-controller-b-")
        try:
            c2, F2 = t289_real_story(fresh_root, 6)
            F2.runner(c2, fresh_root, "S6-qa-runner-1", "automation", ["TC-1"], False)
            driver, world, launched, moves = manual_rig(root, env, task, manual)
            driver.controller_state = lambda: c2.state()
            driver.MANUAL_BLOCK_MAX = 6
            try:
                with mock.patch("controller.Controller", lambda _root, wait_seconds=0.0: c2), contextlib.redirect_stdout(io.StringIO()):
                    driver.run_manual_block(list(manual))
                check("a block of six is refused", False)
            except story_run.Refusal as refusal:
                check_in("a block the real controller refuses is the driver's Refusal, in the controller's words",
                         "S6 manual block dispatch refused: ", refusal.text)
                check_in("...naming what it expected", "manual runner block must name 1..5 unique in-scope cases", refusal.text)
            check_eq("...and nothing was registered or launched",
                     (sorted(d for d in c2.state()["dispatches"] if d.startswith("S6-qa-runner-")), launched),
                     (["S6-qa-runner-1"], []))
        finally:
            harness.cleanup(fresh_root)
        # a ValueError out of `prepare` (what the live run met) is the same Refusal, not a traceback
        driver, world, launched, moves = manual_rig(root, env, task, manual)

        class Refusing:
            def __init__(self, task_root, wait_seconds=0.0):
                pass

            def state(self):
                return {"dispatches": {}}

            def prepare(self, options):
                raise ValueError("new-task qa-runner packet requires execution_kind manual or automation")
        try:
            with mock.patch("controller.Controller", Refusing), contextlib.redirect_stdout(io.StringIO()):
                driver.run_manual_block(list(manual[:2]))
            check("a ValueError of prepare is refused", False)
        except story_run.Refusal as refusal:
            check_in("a ValueError of prepare is the Refusal, with its words", "S6 manual block dispatch refused: ValueError: new-task qa-runner packet requires", refusal.text)
        check_eq("...and no role was launched on it", launched, [])
    finally:
        harness.cleanup(ctl_root)
        harness.cleanup(root)


def t289_the_automation_half_with_a_manual_half_pending_finishes_not_complete() -> None:
    """The part of K-ACC that already holds (t-289, cause (B) is NOT here: the refusal of the automation half in the live
    run came from the EXIT GATE of `handoff`, before `finish` - see the report): with a manual half pending `stage_S6` hands
    the automation runner `complete=False`, and `finish` then speaks `story_step finish --not-complete` and nothing else,
    with no conductor and no `--complete`; with no manual half the runner closes the stage as today."""
    import contextlib
    import io
    task = "QA-9"
    root, task_root, env = d2_seed(task, environment="Local", pending=False)
    try:
        d1_write_blocks(task_root)
        for manual, flag in ((("TC-9",), False), ((), AWAITS)):         # X7-6c: with no manual half the final window awaits the consumer
            driver, launched, moves, started = d1_driver(root, env, task, manual=manual)
            two = {"test_a": ("stale", "", D1_SAME), "test_b": ("missing", "", "none")}
            with D1Evidence(d1_answer(two)):
                driver.stage_S6()
            check_eq(f"manual half {'pending' if manual else 'absent'}: the automation runner gets complete={flag}",
                     [e["complete"] for e in launched], [flag])
            check_eq(f"manual half {'pending' if manual else 'absent'}: the next entry is the manual block (or nothing)",
                     started, [])
        calls = []
        driver = driver_for(root, env, task)
        driver.py = lambda script, *a, **k: calls.append((script, [str(x) for x in a])) or (0, "accepted S6-qa-runner-1")
        driver.conductor = lambda *a, **k: calls.append(("conductor", []))
        with contextlib.redirect_stdout(io.StringIO()):
            driver.finish("S6-qa-runner-1", "digest", complete=False, role="qa-runner", stage="S6")
        check_eq("the finish of the automation half is ONE story_step call", [c[0] for c in calls], ["story_step.py"])
        check("...with --not-complete and without --complete", "--not-complete" in calls[0][1] and "--complete" not in calls[0][1])
    finally:
        harness.cleanup(root)


def t261_the_dry_gate_note_and_the_gate_b_text_slot() -> None:
    """(6) a plan with manual rows and no executable obligation says so once; (§4) the gate B packet holds the block
    `report_facts.manual_checks_text` renders, whole and before the ledger - and ONE line when it is not there, fails or
    prints nothing."""
    import io
    import contextlib
    import report_facts
    task = "QA-9"
    root, task_root, env = d2_seed(task, environment="Local", pending=False)
    try:
        driver = driver_for(root, env, task)
        plan = [{"id": "TS-1", "disposition": "manual-agent", "coverage_obligations": [{"obligation_id": "OB-1", "decision": "new"}]},
                {"id": "TS-2", "disposition": "automate", "coverage_obligations": [{"obligation_id": "OB-2", "decision": "new"}]}]
        (task_root / "work" / "test-plan.json").write_text(json.dumps({"rows": plan}), encoding="utf-8")

        import story_run

        def said(d):
            """(printed text, the Person raised or None)."""
            out, person = io.StringIO(), None
            with contextlib.redirect_stdout(out):
                try:
                    d.manual_gate_note()
                except story_run.Person as raised:
                    person = raised
            return out.getvalue(), person
        text, person = said(driver)
        check_in("(6) manual rows and no executable obligation: one line, `gate A was recorded dry;`", "S6: gate A was recorded dry; the plan has 1 row(s)", text)
        # C1-6b FLIPS the pins that were here ("...with a door that exists": `semantic_reopen` in the printed line; "...once" as the
        # whole outcome): the door is now a QUESTION (kind `gate_a_dry`), and no command is named in anything the person reads
        check_eq("(6) FLIPPED: the dry gate A is a Person, kind `gate_a_dry`, at S6", (getattr(person, "kind", None), getattr(person, "stage", None)),
                 ("gate_a_dry", "S6"))
        check_not_in("(6) FLIPPED: no command in the printed line", "semantic_reopen", text)
        check_not_in("(6) FLIPPED: ...nor in the question", "semantic_reopen", getattr(person, "text", ""))
        check_eq("(6) ...the line is said once", text.count("gate A was recorded dry"), 1)
        plan[0]["coverage_obligations"][0]["decision"] = "manual-agent"
        (task_root / "work" / "test-plan.json").write_text(json.dumps({"rows": plan}), encoding="utf-8")
        check_eq("(6) one executable obligation: nothing is said, nothing is asked", said(driver), ("", None))
        plan[0]["disposition"] = "automate"
        (task_root / "work" / "test-plan.json").write_text(json.dumps({"rows": plan}), encoding="utf-8")
        check_eq("(6) no manual row at all: nothing is said, nothing is asked", said(driver), ("", None))
        (task_root / "work" / "test-plan.json").unlink()
        check_eq("(6) no plan: nothing is said, nothing raised", said(driver), ("", None))

        # the gate B text slot; gate_brief / gate_preflight / waiver are not under test
        def packet(d):
            real = d.py
            d.py = lambda script, *a, **k: (0, f"<{script}>") if script in ("gate_brief.py", "gate_preflight.py", "waiver.py") else real(script, *a, **k)
            return d.gate_text("B")
        held = getattr(report_facts, "manual_checks_text", None)
        if held is not None:
            del report_facts.manual_checks_text
        try:
            ledger = task_root / "work" / "ledger.md"
            ledger.write_text("LEDGER-START " + "x" * 13000 + "\n", encoding="utf-8")
            text = packet(driver)
            check_in("§4: the renderer is not installed: ONE line says so", "manual checks: renderer not installed", text)
            check_eq("§4: ...once", text.count("manual checks:"), 1)
            big = "## Checked by hand — 2 of 3\n" + "\n".join(f"- case {i}: " + "word " * 40 for i in range(120)) + "\nBLOCK-END"
            seen = []
            report_facts.manual_checks_text = lambda task_root_: seen.append(task_root_) or big
            text = packet(driver)
            check_in("§4: the renderer's block is in the packet, WHOLE (long as it is, never cut)", big, text)
            check("§4: ...and stands BEFORE the ledger", 0 <= text.find("BLOCK-END") < text.find("LEDGER-START"))
            check_eq("§4: ...rendered for the story's own task folder", [Path(p).resolve() for p in seen], [task_root.resolve()])
            report_facts.manual_checks_text = lambda task_root_: (_ for _ in ()).throw(RuntimeError("the ledger is torn"))
            text = packet(driver)
            check_in("§4: a renderer that fails: one line naming it", "manual checks: could not be shown (RuntimeError: the ledger is torn)", text)
            check_in("§4: ...and the rest of the packet is still there", "LEDGER-START", text)
            for label, value in (("prints nothing", ""), ("prints a number", 7)):
                report_facts.manual_checks_text = lambda task_root_, value=value: value
                check_in(f"§4: a renderer that {label}: one line", "manual checks: the renderer printed nothing", packet(driver))
        finally:
            if held is not None:
                report_facts.manual_checks_text = held
            elif hasattr(report_facts, "manual_checks_text"):
                del report_facts.manual_checks_text
    finally:
        harness.cleanup(root)


def t261_the_integration_lines_of_the_driver() -> None:
    """The lines of t-253 / t-256 that land in story_run.py: the journal read through the layout (both worlds and a
    person's own path), the case ids handed to the answer reader, and `--apply-fixes` also for a Then that says `raise`."""
    import contextlib
    import io
    task = "QA-9"
    # (a) the journal the --no-trace line counts external writes in: records/ (new), state/ (old), the person's own path
    line = json.dumps({"ts": "2026-09-29T10:00:00+00:00", "event": "external_write", "task": task, "ref": "bug-1", "notes": "filed"}) + "\n"
    for label, where, config, expected in (
            ("old layout (state/)", "qa-factory/state/journal.jsonl", None, 1),
            ("new layout (records/)", "qa-factory/records/journal.jsonl", None, 1),
            ("the person's own path", "elsewhere/journal.jsonl", "elsewhere/journal.jsonl", 1),
            ("no journal at all", None, None, 0)):
        root, task_root, env = seed(task)
        try:
            if config:
                cfg_path = root / "qa-factory" / "config.json"
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                cfg["journal_path"] = config
                cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
            if where:
                target = root / where
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(line, encoding="utf-8")
            driver = driver_for(root, env, task, no_trace=True)
            driver.where = lambda: {"action": "stop", "reason": "end of test"}
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                driver.run()
            check_eq(f"journal through the layout: {label}: the external write is counted (or not) as the file says",
                     "already holds 1 external_write event(s)" in printed.getvalue(), bool(expected))
        finally:
            harness.cleanup(root)
    # (b) parse_choices gets the story's case ids: a case word at a question stop is read as a CASE word and said back
    root, task_root, env = seed(task)
    try:
        work = task_root / "work"
        (work / "test-cases" / "area").mkdir(parents=True)
        (work / "test-cases" / "area" / "QA-9_TC_001.md").write_text(
            "---\nid: QA-9_TC_001\ntitle: first\nplan_row: TS-1\n---\n\n## Then\n1. x.\n", encoding="utf-8")
        (work / "requirements-readiness.json").write_text(json.dumps({"verdict": "blocked", "open_questions": [
            {"id": "Q1", "question": "Which?", "severity": "major",
             "readings": [{"reading": "r0", "from": "description", "if_chosen": "x"}, {"reading": "r1", "from": "description", "if_chosen": "x"}]}]}),
            encoding="utf-8")
        cfg_path = root / "qa-factory" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["case_id_form"] = "{ticket}_TC_{nnn}"
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        driver = driver_for(root, env, task)
        driver.py = lambda script, *a, **k: (0, "")
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            driver.take_question_answer("S3", "S3-qa-test-strategist-1", "Q1: a\nQA-9_TC_001: accept as blocked\n")
        out = printed.getvalue()
        check_in("a question word is still recorded by code", "S3: recorded by code — Q1: a", out)
        check_in("the case word is said back as a case word, not as an unknown question", "`QA-9_TC_001: accept as blocked` is a word about a case", out)
        check_not_in("it is not listed as an unknown question id either", "not recognised as open questions", out)
        check_in("and says where it is applied", "say it again at gate A", out)
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            driver.take_question_answer("S3", "S3-qa-test-strategist-1", "NOT_A_CASE_1: accept as blocked\nQ77: a\n")
        check_not_in("an id that is no case of the story is no case word (control: the line is printed only for a real case)",
                     "is a word about a case", printed.getvalue())
        check_in("an unknown QUESTION id is still named as not recognised", "not recognised as open questions, so nothing is recorded for them: Q77", printed.getvalue())
    finally:
        harness.cleanup(root)
    # (c) stage_S4: `--apply-fixes` also for a pinned case that says `raise`, with or without a findings file
    for label, findings_text, case_says_raise, expected in (
            ("approve_with_fixes in the findings", "verdict: approve_with_fixes\n", False, True),
            ("a plain approve, no `raise` anywhere", "verdict: approve\n", False, False),
            ("a plain approve, a case says `raise`", "verdict: approve\n", True, True),
            ("no findings file, a case says `raise`", None, True, True),
            ("no findings file, nothing says `raise`", None, False, False)):
        root, task_root, env = seed(task)
        try:
            cases = task_root / "work" / "test-cases" / "area"
            cases.mkdir(parents=True)
            oracle = '[{"then": 1, "source": "unknown", "ref": "raise"}]' if case_says_raise else '[{"then": 1, "source": "ac", "ref": "R-1"}]'
            (cases / "TC-001.md").write_text(
                f"---\nid: TC-001\ntask: QA-9\nplan_row: TS-1\nthen_oracles: {oracle}\n---\n\n## Then\n1. x.\n", encoding="utf-8")
            findings = None
            if findings_text is not None:
                findings = cases / "critic-findings.md"
                findings.write_text(findings_text, encoding="utf-8")
            driver = driver_for(root, env, task)
            calls = []
            driver.py = lambda script, *a, **k: calls.append((script, [str(x) for x in a])) or (0, "")
            driver.run_role = lambda *a, **k: ("", None)
            driver.pin_cases = lambda: None
            driver.revise_plan = lambda: None
            driver.render_appendix = lambda: None
            driver.pinned_cases = lambda: ["QA-9_TC_001"]
            driver.critic_scope = lambda: ["QA-9_TC_001"]
            driver.budget_or_none = lambda *a, **k: {"counted": 0, "cap": 2}
            driver.newest = lambda pattern: findings
            with contextlib.redirect_stdout(io.StringIO()):
                driver.stage_S4()
            ran = [c for c in calls if c[0] == "critic_rollcall.py"]
            check_eq(f"S4 exit, {label}: `critic_rollcall.py --apply-fixes` runs: {expected}", bool(ran), expected)
            if ran:
                check_in(f"S4 exit, {label}: it is the same command", "--apply-fixes", " ".join(ran[0][1]))
                check_eq(f"S4 exit, {label}: the findings file is named only when there is one", str(findings) in ran[0][1], findings is not None)
        finally:
            harness.cleanup(root)


# --- t-292: the stand's sign-in account, asked BEFORE a block with a screen case is dispatched ------------------------
# TP1-15045 (cmp2r rehearsal, 02.10): screen cases were dispatched with no usable test account and every capture
# photographed the sign-in page. `d2_seed` records `environment.env_file = qa.env` (an env file with no account in it),
# so the DEFAULT of these scenarios is "the file is there, the account is not"; each scenario writes the config it needs.

def t292_config(root, manual_capture=None, **environment):
    """The project's config with exactly this `environment` (no env_file at all when none is given) and, when given,
    `manual_capture`."""
    path = root / "qa-factory" / "config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["environment"] = dict(environment)
    cfg.pop("manual_capture", None)
    if manual_capture is not None:
        cfg["manual_capture"] = manual_capture
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def t292_account(root, text, name="account.env"):
    """An env file with the given text, and the config pointing at it (default keys AUTH_USERNAME / AUTH_PASSWORD)."""
    (root / name).write_text(text, encoding="utf-8")
    t292_config(root, env_file=name)


SCREENS = {"QA-9_TC_001": "ui", "QA-9_TC_002": "ui"}
WITH_HTTP = dict(SCREENS, **{"QA-9_TC_003": "api"})


def t292_enter(driver, world, cases, accept=True):
    """`enter_manual`, but a raised `Person` is the result: (printed text, new dispatch id, the Person or None)."""
    import story_run
    import contextlib
    import io
    from unittest import mock
    before, out, person = set(world.dispatches), io.StringIO(), None
    try:
        with mock.patch("controller.Controller", world.controller_class()), contextlib.redirect_stdout(out):
            driver.run_manual_block(list(cases))
    except story_run.Person as raised:
        person = raised
    new = sorted(set(world.dispatches) - before)
    if accept:
        for dispatch_id in new:
            world.accept(dispatch_id)
            record_failure_analyst_accept(driver, dispatch_id)
    return out.getvalue(), (new[0] if new else ""), person


def t292_k15_to_k18_the_question_comes_before_any_block() -> None:
    """K15: a block with screen cases and no `environment.env_file` raises the question, registers nothing and launches
    nothing - the http case beside them waits for the same answer (Q10). K16/K17 are the negative controls (http only;
    the account present); K18: a named file that is missing, then present without the password."""
    task = "QA-9"
    root, task_root, env = d2_seed(task, environment="Local", pending=False)
    try:
        t292_config(root)
        cases = list(WITH_HTTP)
        driver, world, launched, moves = manual_rig(root, env, task, cases, policy=WITH_HTTP)
        text, new, person = t292_enter(driver, world, cases)
        check("K15 screen cases and no env_file: a Person is raised", person is not None)
        eq("K15: nothing is launched and no dispatch is registered (the http case waits too)", (launched, world.dispatches, new), ([], {}, ""))
        eq("K15: the Person is kind `stand_login`, at S6, for exactly the screen cases", (person.kind, person.stage, person.login_cases), ("stand_login", "S6", list(SCREENS)))
        eq("K15: the text obeys human-questions.md (with the answer block ask() puts under it)", human_broken(person.text), [])
        for word in ("`retry`", "`by hand`", "`go on`", "I have not started any of these checks"):
            check_in(f"K15: the text says {word}", word, person.text)
        for case in SCREENS:
            check_in(f"K15: the text names {case}", case, person.text)
        check_not_in("K15: and not the http case (it is not what is asked about)", "QA-9_TC_003", person.text)
        check_in("K15: the reason is the no-file one", "the project's settings name no file for it", person.text)
        check_in("K15: the details carry the config key names for the factory's reader", "environment.env_file", person.details)
        check_in("K15: ... and the door for a project that needs no sign-in", "manual_capture.login.ui", person.details)
        # the question is a real one: it is asked, and the flag names it
        driver.ask(person)
        state = s0_state(task_root)
        eq("K15: ask() sets the flag for exactly these cases", state.get("login_question"), {"stage": "S6", "cases": list(SCREENS)})
        eq("K15: and the question is kind stand_login", (state.get("asked") or {}).get("kind"), "stand_login")

        # K16: http only, no env_file: dispatched as today, no Person
        driver, world, launched, moves = manual_rig(root, env, task, ["QA-9_TC_003"], policy="api")
        text, new, person = t292_enter(driver, world, ["QA-9_TC_003"])
        eq("K16 control: http cases only and no env_file: dispatched as today, no Person", (person, [e["scope"] for e in launched]), (None, [["QA-9_TC_003"]]))
        # K17: screen cases, the account present (both keys): dispatched as today
        t292_account(root, "AUTH_USERNAME=qa-user\nAUTH_PASSWORD=SENTINEL-PW-1\n")
        driver, world, launched, moves = manual_rig(root, env, task, cases, policy=WITH_HTTP)
        text, new, person = t292_enter(driver, world, cases)
        eq("K17 control: screen cases with the account in place: dispatched as today, no Person", (person, [e["scope"] for e in launched]), (None, [cases]))
        # K18: a named file that does not exist; then one without the password
        t292_config(root, env_file="missing.env")
        driver, world, launched, moves = manual_rig(root, env, task, cases, policy=WITH_HTTP)
        text, new, person = t292_enter(driver, world, cases)
        check("K18 env_file named but missing: a Person", person is not None)
        check_in("K18: the details say the file does not exist", "does not exist", person.details)
        check_in("K18: the text says the file is not there", "the file the settings name for it is not there", person.text)
        eq("K18: nothing dispatched", (launched, world.dispatches), ([], {}))
        t292_account(root, "AUTH_USERNAME=qa-user\nSOMETHING_ELSE=SENTINEL-PW-2\n")
        driver, world, launched, moves = manual_rig(root, env, task, cases, policy=WITH_HTTP)
        text, new, person = t292_enter(driver, world, cases)
        check("K18 the file there, no password: a Person", person is not None)
        check_in("K18: the details name the missing key", "AUTH_PASSWORD is not set", person.details)
        check_in("K18: the text says the file lacks the account", "does not hold the account's name or its password", person.text)
        check_not_in("K18: no value of the file appears in the text or the details", "SENTINEL-PW", person.text + person.details + text)
        check_not_in("K18: nor the user name's value", "qa-user", person.text + person.details)
        for label, content in (("an empty password", "AUTH_USERNAME=qa-user\nAUTH_PASSWORD=\n"),
                               ("a quoted empty password", "AUTH_USERNAME=qa-user\nAUTH_PASSWORD=\"\"\n"),
                               ("a commented-out password", "AUTH_USERNAME=qa-user\n# AUTH_PASSWORD=SENTINEL-PW-3\n")):
            t292_account(root, content)
            driver, world, launched, moves = manual_rig(root, env, task, cases, policy=WITH_HTTP)
            text, new, person = t292_enter(driver, world, cases)
            check(f"K18 adversarial ({label}): still a Person (the safe side), nothing launched", person is not None and launched == [])
        t292_account(root, "export AUTH_USERNAME=qa-user\nexport AUTH_PASSWORD=pw\n")
        driver, world, launched, moves = manual_rig(root, env, task, cases, policy=WITH_HTTP)
        text, new, person = t292_enter(driver, world, cases)
        eq("K18 `export AUTH_USERNAME=x` reads as present: dispatched", (person, len(launched)), (None, 1))
        # an env_file that names a DIRECTORY, and a relative one resolved against the project root (not the cwd)
        (root / "adir").mkdir()
        t292_config(root, env_file="adir")
        driver, world, launched, moves = manual_rig(root, env, task, cases, policy=WITH_HTTP)
        check("K18 adversarial (env_file names a directory): a Person", t292_enter(driver, world, cases)[2] is not None)
    finally:
        harness.cleanup(root)


def t292_k19_the_answers_have_an_executor() -> None:
    """K19: the three answers through `ask` and `take_answer`. `retry` records nothing and the next entry asks again;
    `by hand` and `go on` record the pass with ONE command and the next entry leaves the screen cases out in the person's
    words (the http case is dispatched, not complete) and the one after closes the manual half code-only; other words go
    to the conductor with that same command."""
    import json as _json
    task = "QA-9"
    root, task_root, env = d2_seed(task, environment="Local", pending=False)
    try:
        t292_config(root)
        cases = list(WITH_HTTP)
        screens = list(SCREENS)

        def ask_it():
            driver, world, launched, moves = manual_rig(root, env, task, cases, policy=WITH_HTTP)
            _text, _new, person = t292_enter(driver, world, cases)
            driver.ask(person)
            return driver, world, launched, moves

        def overrides():
            return [o for o in (s0_pipeline(task_root).get("stage_overrides") or []) if o.get("match") == "stand login missing"]
        # retry: no waiver; the same question is asked again, with the FR-7 notice
        driver, world, launched, moves = ask_it()
        driver.take_answer(Path(d2_answer(root, "retry")))
        eq("K19 `retry`: no pass is recorded", overrides(), [])
        check("K19 `retry`: the flag is gone with the question", "login_question" not in s0_state(task_root))
        check("K19 `retry`: the journal says what was answered", any("S6 (retry): retry" in str(e.get("notes")) for e in s0_journal(root)))
        driver, world, launched, moves = manual_rig(root, env, task, cases, policy=WITH_HTTP)
        text, new, person = t292_enter(driver, world, cases)
        check("K19 `retry`: the next entry raises the Person again (the material is still missing)", person is not None and launched == [])
        driver.ask(person)
        check_in("K19 `retry`: and it is not re-asked silently (FR-7: the earlier answer is shown)", "You have answered this exact question before", s0_question(task_root))
        # other words: the conductor gets the waiver command, and nothing is recorded by code
        calls = []
        driver.conductor = lambda prompt, words=None, **kw: calls.append((prompt, words)) or {"action": "continue", "did": "read"}
        driver.take_answer(Path(d2_answer(root, "I am not sure, ask Dana")))
        eq("K19 other words: ONE conductor call, no pass recorded by code", (len(calls), overrides()), (1, []))
        check_in("K19 other words: it carries the one waiver command with this block and stage",
                 '--stage S6 --block "stand login missing" --words-file ', calls[0][0])
        check_not_in("K19 other words: and no inline `--decision` (the words go by FILE, axis 5)", "--decision", calls[0][0])
        check_in("K19 other words: and the instruction to run nothing when they do not say it", "run nothing", calls[0][0])
        eq("K19 other words: the person's words travel whole", calls[0][1], "I am not sure, ask Dana")
        # `by hand` and `go on`: ONE executor (waiver.py), the words verbatim
        for token, words in (("by hand", "By hand."), ("go on", "go on")):
            fresh_root, fresh_task_root, fresh_env = d2_seed(task, environment="Local", pending=False)
            try:
                t292_config(fresh_root)
                driver, world, launched, moves = manual_rig(fresh_root, fresh_env, task, cases, policy=WITH_HTTP)
                _text, _new, person = t292_enter(driver, world, cases)
                driver.ask(person)
                driver.take_answer(Path(d2_answer(fresh_root, words)))
                got = [o for o in (s0_pipeline(fresh_task_root).get("stage_overrides") or []) if o.get("match") == "stand login missing"]
                eq(f"K19 `{token}`: waiver.py records the block for S6 with the words verbatim", [(o["stage"], o["decision"]) for o in got], [("S6", words)])
                check(f"K19 `{token}`: and the journal has the answer", any(f"S6 ({token}): " in str(e.get("notes")) for e in s0_journal(fresh_root)))
                # the next entry: the http case only, not complete; one line per screen case with the words; request.json says so
                text, new, person = t292_enter(driver, world, cases)
                eq(f"K19 `{token}`: the next entry raises nothing and dispatches only the http case, not closing the stage",
                   (person, [(e["scope"], e["complete"]) for e in launched]), (None, [(["QA-9_TC_003"], AWAITS)]))         # X7-6c: the last window awaits the consumer
                for case in screens:
                    line = next((ln for ln in text.splitlines() if ln.startswith(f"S6: {case}: not checked by hand")), "")
                    check_in(f"K19 `{token}`: a `not checked by hand` line for {case} carries the person's words", f"the person said: \"{words}\"", line)
                    refused = _json.loads((fresh_task_root / "work" / "evidence" / "manual" / case / "request.json").read_text(encoding="utf-8"))
                    check_in(f"K19 `{token}`: {case}'s request says it was left out, in the words", f"the person said: \"{words}\"", refused["refused"]["reason"])
                    check_in(f"K19 `{token}`: ... with a door", "put the stand's test account in the project's settings", refused["refused"]["door"])
                # the one after: nothing left to dispatch: the manual half closes code-only, naming the screen cases
                moves.clear()
                text, new, person = t292_enter(driver, world, cases)
                eq(f"K19 `{token}`: the following entry closes the manual half (finalize, code_only, stage_done), no role", ([m[0] for m in moves], len(launched)), (["finalize", "code_only", "stage_done"], 1))
                check_in(f"K19 `{token}`: and names the screen cases as not checked", ", ".join(screens), moves[1][2])
            finally:
                harness.cleanup(fresh_root)
        # a pass that did not record (waiver.py refused): said, and the question comes back
        fresh_root, fresh_task_root, fresh_env = d2_seed(task, environment="Local", pending=False)
        try:
            t292_config(fresh_root)
            driver, world, launched, moves = manual_rig(fresh_root, fresh_env, task, cases, policy=WITH_HTTP)
            _text, _new, person = t292_enter(driver, world, cases)
            driver.ask(person)
            real = driver.py
            driver.py = lambda script, *a, **k: (2, "waiver: refused") if script == "waiver.py" else real(script, *a, **k)
            import contextlib
            import io
            import story_run
            said = io.StringIO()
            held = None
            with contextlib.redirect_stdout(said):
                try:
                    driver.take_answer(Path(d2_answer(fresh_root, "go on")))
                except story_run.Person as raised:
                    held = raised
            check_in("K19 a pass that did not record is said (the seam's held question, with the writer's words)",
                     "Your word could not be recorded as the pass, so nothing was passed.", getattr(held, "text", ""))
            check_in("K19 ... and it is said on the screen too", "the pass was not recorded", said.getvalue())
            _text, _new, person = t292_enter(driver, world, cases)
            check("K19 ... and the question comes back (nothing was recorded)", person is not None)
        finally:
            harness.cleanup(fresh_root)
    finally:
        harness.cleanup(root)


def t292_k20_to_k24_the_pass_is_read_only_while_the_account_is_missing() -> None:
    """K20 (temporal): the pass is recorded, then the account arrives - the screen cases are dispatched even though a pass
    exists; a revoked pass brings the question back (E17). K21: the flag isolates the answers. K22: `login.ui: null`
    asks nothing. K23: no screen case left asks nothing. K24: an unknown policy counts as a screen case."""
    import contextlib
    import io
    task = "QA-9"
    root, task_root, env = d2_seed(task, environment="Local", pending=False)
    try:
        t292_config(root)
        cases = list(WITH_HTTP)
        d2_pipeline(task_root, stage_overrides=[{"stage": "S6", "match": "stand login missing", "decision": "by hand",
                                                  "at": "2026-10-02T10:00:00+00:00", "by": "human"}])
        driver, world, launched, moves = manual_rig(root, env, task, cases, policy=WITH_HTTP)
        text, new, person = t292_enter(driver, world, cases)
        eq("K20 before the account: the pass holds - the screen cases are left out, no Person", (person, [e["scope"] for e in launched]), (None, [["QA-9_TC_003"]]))
        t292_account(root, "AUTH_USERNAME=qa-user\nAUTH_PASSWORD=pw\n")
        driver, world, launched, moves = manual_rig(root, env, task, cases, policy=WITH_HTTP)
        text, new, person = t292_enter(driver, world, cases)
        eq("K20 temporal: the account arrives after the pass: the screen cases ARE dispatched (a pass is read only while the material is missing)",
           (person, [e["scope"] for e in launched]), (None, [cases]))
        check_not_in("K20: and nothing says they were left out", "not checked by hand", text)
        # E17: the person takes the word back with waiver --revoke; the account is gone again: the question comes back
        t292_config(root)
        code, out = driver.py("waiver.py", "--revoke", "--task", task, "--stage", "S6", "--block", "stand login missing", "--decision", "I have the account now")
        eq("K20 revoke: waiver.py --revoke takes the word back", code, 0)
        driver, world, launched, moves = manual_rig(root, env, task, cases, policy=WITH_HTTP)
        text, new, person = t292_enter(driver, world, cases)
        check("K20 revoke: the question speaks again (a revoked pass is history, not a pass)", person is not None and launched == [])

        # K21: the answers do not cross
        set_control(root, {"conductor": {"action": "continue", "did": "read it", "text": "Read."}})
        d2_pipeline(task_root, stage_overrides=[])
        driver = driver_for(root, env, task)
        driver.state["asked"] = {"kind": "environment", "stage": "S6", "dispatch": ""}
        driver.state["stand_question"] = "S6"
        driver.state["login_question"] = {"stage": "S6", "cases": list(SCREENS)}      # a stale flag of the OTHER question
        driver.save_state()
        (task_root / "state" / "driver-question.md").write_text("# q\nkind: environment\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            driver.take_answer(Path(d2_answer(root, "go on")))
        names = [(o.get("match"), o.get("decision")) for o in (s0_pipeline(task_root).get("stage_overrides") or [])]
        eq("K21 the stand question's answer reaches ITS branch only: the `stand not confirmed` pass, never `stand login missing`",
           [m for m, _d in names], ["stand not confirmed"])
        driver = driver_for(root, env, task)
        before = len(d2_conductor_calls(root))
        driver.state["asked"] = {"kind": "stand_login", "stage": "S6", "dispatch": ""}
        driver.state.pop("login_question", None)
        driver.save_state()
        (task_root / "state" / "driver-question.md").write_text("# q\nkind: stand_login\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            driver.take_answer(Path(d2_answer(root, "go on")))
        names = [o.get("match") for o in (s0_pipeline(task_root).get("stage_overrides") or [])]
        eq("K21 a `stand_login` answer with no flag is not taken by the new branch: it goes to the conductor and records no pass",
           (names, len(d2_conductor_calls(root)) - before), (["stand not confirmed"], 1))

        # K22 (Q7): `manual_capture.login.ui: null` - no Person, the screen cases are dispatched
        t292_config(root, manual_capture={"login": {"ui": None}})
        driver, world, launched, moves = manual_rig(root, env, task, cases, policy=WITH_HTTP)
        text, new, person = t292_enter(driver, world, cases)
        eq("K22 `manual_capture.login.ui: null` and no env_file: no question, everything dispatched", (person, [e["scope"] for e in launched]), (None, [cases]))
        t292_config(root, manual_capture={"login": {"http": None}})
        driver, world, launched, moves = manual_rig(root, env, task, cases, policy=WITH_HTTP)
        check("K22 control: `login.http: null` is not a statement about the screens: the question is asked", t292_enter(driver, world, cases)[2] is not None)

        # K23: no screen case left - refused by prepare, or done - asks nothing, and manual_close is as today
        t292_config(root)
        driver, world, launched, moves = manual_rig(root, env, task, list(SCREENS), refused=list(SCREENS), policy="ui")
        text, new, person = t292_enter(driver, world, list(SCREENS))
        eq("K23 screen cases all refused by prepare, no env_file: no Person; the manual half closes as today", (person, [m[0] for m in moves]), (None, ["finalize", "code_only", "stage_done"]))
        driver, world, launched, moves = manual_rig(root, env, task, list(SCREENS), policy="ui")
        for number, case in enumerate(SCREENS, 1):
            world.dispatches[f"S6-qa-runner-{number}"] = {"stage": "S6", "status": "accepted", "execution_kind": "manual", "manual_case_ids": [case]}
        text, new, person = t292_enter(driver, world, list(SCREENS))
        eq("K23 screen cases all done, no env_file: no Person; closes as today", (person, launched, [m[0] for m in moves]), (None, [], ["finalize", "code_only", "stage_done"]))
        driver, world, launched, moves = manual_rig(root, env, task, cases, refused=list(SCREENS), policy=WITH_HTTP)
        text, new, person = t292_enter(driver, world, cases)
        eq("K23 control: screen cases refused but an http case ready: dispatched, no Person", (person, [e["scope"] for e in launched]), (None, [["QA-9_TC_003"]]))

        # K24: an unknown policy counts as a screen case, with one printed line naming the request
        driver, world, launched, moves = manual_rig(root, env, task, list(SCREENS), policy="")
        said = io.StringIO()
        with contextlib.redirect_stdout(said):
            plan = driver.manual_plan(list(SCREENS))
            try:
                driver.stand_login_gate(plan)
                raised = None
            except Exception as exc:
                raised = exc
        check("K24 an unknown policy (\"\") counts as a screen case: the Person is raised", raised is not None and getattr(raised, "kind", "") == "stand_login")
        for case in SCREENS:
            check_in(f"K24: one line says the request of {case} could not be read", f"S6: {case}: its prepared request (work/evidence/manual/{case}/request.json) could not be read", said.getvalue())
    finally:
        harness.cleanup(root)


def t292_the_real_policy_reader_and_the_question_titles() -> None:
    """`manual_policy` reads what `manual_prepare` wrote (the real one, no stub): `ui`, `api`, a refusal, a broken file and
    an absent one - the last three are "" (unknown). The question names a case by its title and id, or - with no title -
    by a link to its case file on the same line."""
    import manual_evidence as ME
    task = "QA-9"
    root, task_root, env = d2_seed(task, environment="Local", pending=False)
    try:
        driver = driver_for(root, env, task)

        def request(case, content):
            path = ME.request_path(task_root, case)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
        request("QA-9_TC_001", {"evidence_policy": "ui", "case": "QA-9_TC_001"})
        request("QA-9_TC_002", {"evidence_policy": "api"})
        request("QA-9_TC_003", {"refused": {"reason": "r", "door": "d"}, "evidence_policy": "ui"})
        request("QA-9_TC_004", "{not json")
        request("QA-9_TC_005", {"case": "QA-9_TC_005"})
        request("QA-9_TC_006", "[1]")
        eq("manual_policy: ui / api / refused / broken / no policy / not an object / absent",
           [driver.manual_policy(f"QA-9_TC_00{n}") for n in range(1, 8)], ["ui", "api", "", "", "", "", ""])
        # the question's lines
        folder = task_root / "work" / "test-cases" / "area"
        folder.mkdir(parents=True)
        (folder / "QA-9_TC_001.md").write_text("---\nid: QA-9_TC_001\ntitle: Zoom the visual diff\nplan_row: TS-1\n---\n\n## Then\n1. x.\n", encoding="utf-8")
        (folder / "QA-9_TC_002.md").write_text("---\nid: QA-9_TC_002\ntitle: \"\"\nplan_row: TS-2\n---\n\n## Then\n1. x.\n", encoding="utf-8")
        # The index is `contract.case_index`'s own business (tested there; it memoises per process, so an earlier scenario's
        # project can hide this one's files): here it answers with the two files just written, and `case_title` is the real one.
        from unittest import mock
        found = {"QA-9_TC_001": {"path": folder / "QA-9_TC_001.md"}, "QA-9_TC_002": {"path": folder / "QA-9_TC_002.md"}}
        with mock.patch("contract.case_index", lambda _root: found):
            text = driver.stand_login_question_text(["QA-9_TC_001", "QA-9_TC_002", "QA-9_TC_009"], "no_file")
        check_in("question: a case with a title is `title (id)`", "- Zoom the visual diff (QA-9_TC_001)", text)
        check_in("question: a case with an empty title is a link to its case file on the same line", "- [QA-9_TC_002](work/test-cases/area/QA-9_TC_002.md)", text)
        check_in("question: a case the story does not hold is its bare id (never a raise)", "- QA-9_TC_009\n", text)
        eq("question: and it obeys human-questions.md", human_broken(text), [])
        for kind, reason in (("no_file", "the project's settings name no file for it"), ("missing_file", "the file the settings name for it is not there"),
                             ("missing_key", "the file the settings name does not hold the account's name or its password")):
            check_in(f"question: the reason of `{kind}`", reason, driver.stand_login_question_text(["QA-9_TC_001"], kind))
    finally:
        harness.cleanup(root)


def t308_f6_the_reason_the_person_reads_is_the_true_one() -> None:
    """t-308 F6: `stand_login_problem` names the reason the person reads. An env file that is THERE but cannot be read
    (a folder in its place, no permission) is `unreadable`, never "not there"; a settings file that cannot be loaded is a
    `missing_file` reason carrying the loader's own text, never `no_file` ("the settings name no file" - false). Controls:
    an absent file is still `missing_file`, a file without the password `missing_key`, no env_file `no_file`, a login
    declared null and a good file are no problem. Every reason's question passes human-questions.md."""
    from unittest import mock
    import manual_capture as MC
    task = "QA-9"
    root, task_root, env = d2_seed(task, environment="Local", pending=False)
    try:
        driver = driver_for(root, env, task)

        def problem(**environment):
            t292_config(root, **environment)
            return driver.stand_login_problem()
        (root / "adir").mkdir()
        kind, details = problem(env_file="adir")
        eq("F6 a folder where the env file should be: `unreadable`", kind, "unreadable")
        check_in("F6: the details say it cannot be read", "cannot be read", details)
        check_not_in("F6: and not that it does not exist", "does not exist", details)
        (root / "locked.env").write_text("AUTH_USERNAME=u\nAUTH_PASSWORD=SENTINEL-PW-9\n", encoding="utf-8")
        with mock.patch.object(MC, "_env_values", side_effect=PermissionError("denied")):
            kind, details = problem(env_file="locked.env")
        eq("F6 a file that is there but cannot be read (no permission): `unreadable`", kind, "unreadable")
        check_not_in("F6: no value of the file in the details", "SENTINEL-PW", details)
        kind, details = problem(env_file="nowhere.env")
        eq("F6 control: an absent file is still `missing_file`", kind, "missing_file")
        t292_account(root, "AUTH_USERNAME=u\nOTHER=x\n")
        eq("F6 control: a file with no password is `missing_key`", driver.stand_login_problem()[0], "missing_key")
        eq("F6 control: no env_file is `no_file`", problem()[0], "no_file")
        t292_account(root, "AUTH_USERNAME=u\nAUTH_PASSWORD=p\n")
        eq("F6 control: a good file is no problem", driver.stand_login_problem(), ("", ""))
        t292_config(root, manual_capture={"login": {"ui": None}}, env_file="nowhere.env")
        eq("F6 control: a login declared null is no problem even with a missing file", driver.stand_login_problem(), ("", ""))
        t292_config(root, env_file="locked.env")
        with mock.patch.object(MC, "load_config", side_effect=ValueError("config.json is not valid JSON (boom)")):
            kind, details = driver.stand_login_problem()
        eq("F6 the settings cannot be loaded: `missing_file`, not `no_file`", kind, "missing_file")
        check_in("F6: with the loader's own text", "config.json is not valid JSON (boom)", details)
        # every reason's question obeys human-questions.md
        for reason in ("no_file", "missing_file", "unreadable", "missing_key"):
            text = driver.stand_login_question_text(["QA-9_TC_001"], reason)
            eq(f"F6 the question for `{reason}` obeys human-questions.md", human_broken(text), [])
        check_in("F6: the `unreadable` question says the file could not be read", "the file the settings name for it could not be read",
                 driver.stand_login_question_text(["QA-9_TC_001"], "unreadable"))
    finally:
        harness.cleanup(root)


def ep1_41f_cases_all_on_a_device_skip_only_the_default_account() -> None:
    """EP1-41f (N-18): a block whose cases are ALL on a device profile asks nothing about the default web account (no env file is no
    problem), yet the account a case NAMES is still asked for on entry; a web case beside them, `None`, `[]`, a case no profile
    claims, a raise in the keying and a broken table each keep the old question (a question too many, never one too few)."""
    from unittest import mock
    import gate_preflight
    import manual_evidence as ME
    import surfaces
    task = "QA-9"
    root, task_root, env = d2_seed(task, environment="Local", pending=False)
    try:
        driver = driver_for(root, env, task)
        t292_config(root)
        path = root / "qa-factory" / "config.json"
        cfg = json.loads(path.read_text(encoding="utf-8"))
        cfg["profiles"] = [{"profile_id": "e2e-ui", "capabilities": ["web"]}, {"profile_id": "android", "capabilities": ["native"]}]
        cfg["environments"] = [{"name": "Local"}, {"name": "emu", "surface": "android"}]
        path.write_text(json.dumps(cfg), encoding="utf-8")
        keyed = {"android": {"cases": ["QA-9_TC_001", "QA-9_TC_003"]}, "e2e-ui": {"cases": ["QA-9_TC_002"]}}

        def problem(cases, keying=keyed):
            with mock.patch.object(gate_preflight, "stand_profiles", return_value=keying):
                return driver.stand_login_problem(cases)
        eq("41f control: no cases and no env file - the old question (`no_file`)", driver.stand_login_problem()[0], "no_file")
        eq("41f every case on the device: the default account is not asked", problem(["QA-9_TC_001", "QA-9_TC_003"]), ("", ""))
        eq("41f one web case beside the device case: the old question", problem(["QA-9_TC_001", "QA-9_TC_002"])[0], "no_file")
        eq("41f `None` cases: the old question", problem(None)[0], "no_file")
        eq("41f `[]` cases: the old question", problem([])[0], "no_file")
        eq("41f a case no profile claims: the old question", problem(["QA-9_TC_001", "QA-9_TC_404"])[0], "no_file")
        with mock.patch.object(gate_preflight, "stand_profiles", side_effect=OSError("x")):
            eq("41f the keying raises: the old question", driver.stand_login_problem(["QA-9_TC_001"])[0], "no_file")
        with mock.patch.object(surfaces, "TABLE_PATH", root / "no-such-table.json"):
            eq("41f a broken table: the old question, no crash", problem(["QA-9_TC_001"])[0], "no_file")
        # an account the case NAMES, with no pair on the stand, is still asked on entry - the actor loop runs on a device case
        actors = [{"id": "A1", "check": {"stand_account": "Admin"}}]
        with mock.patch.object(ME, "request_actors", return_value=(actors, "")):
            kind, details = problem(["QA-9_TC_001"])
        eq("41f a named account without a pair on a device case: asked (`missing_key`), not skipped", kind, "missing_key")
        check_in("41f ... and the details name the case and the account", "QA-9_TC_001: the account A1", details)
        # a login declared null stays first
        t292_config(root, manual_capture={"login": {"ui": None}})
        eq("41f `login.ui: null` is still no problem for a web block", problem(["QA-9_TC_002"]), ("", ""))
    finally:
        harness.cleanup(root)


IN_FLIGHT_STUB = '''import json, os, sys
from pathlib import Path
state = Path(os.environ["SEEN_STATE"])
import time
# The parent writes in_flight[<dispatch>] only after Popen returns, so the child may start first: poll (cap 5 s, 50 ms)
# until its own entry shows. No dispatch in the env (the conductor) expects no entry: read once, never wait.
want = os.environ.get("QA_FACTORY_DRIVER_RUN")
deadline = time.time() + 5
while True:
    try:
        seen = json.loads(state.read_text(encoding="utf-8")) if state.is_file() else {}
    except ValueError:
        seen = {}
    if not want or (seen.get("in_flight") or {}).get(want) or time.time() >= deadline:
        break
    time.sleep(0.05)
Path(os.environ["SEEN_OUT"]).write_text(json.dumps({"in_flight": seen.get("in_flight"), "pid": os.getpid(),
                                                    "env": os.environ.get("QA_FACTORY_DRIVER_RUN")}), encoding="utf-8")
sys.stdin.read()
print(json.dumps({"type": "result", "session_id": "", "result": "ok", "num_turns": 3, "total_cost_usd": 0.1, "is_error": False}))
'''


def t329_b268_a_role_in_flight_is_written_while_it_runs_and_removed_when_it_returns() -> None:
    """t-329 item 1 (B-268): `run_claude` writes `in_flight[<dispatch>] = {dispatch_id, pid, started_at}` into
    driver-state.json as soon as the `claude -p` process has a pid, and removes it when the call returns by any
    road. The stub reads driver-state.json FROM INSIDE the child: the entry is on disk while the process runs,
    names that very process, and the child's environment carries QA_FACTORY_DRIVER_RUN (item 2). Controls: the
    conductor's call (no dispatch) writes no entry; a call that raises leaves no entry; a resumed call names the
    session; the key is gone, not an empty dict (a state with nobody in flight reads as before)."""
    from unittest import mock
    task = "QA-9"
    root, task_root, env = d2_seed(task, environment="Local", pending=False)
    try:
        driver = driver_for(root, env, task)
        stub = root / "in_flight_stub.py"
        stub.write_text(IN_FLIGHT_STUB, encoding="utf-8")
        out = root / "seen.json"
        driver.claude = [sys.executable, str(stub)]
        driver.claude_env = dict(driver.claude_env, SEEN_STATE=str(task_root / "state" / "driver-state.json"), SEEN_OUT=str(out))
        driver.run_claude("role", "p", role="qa-automator", dispatch="S5-qa-automator-1", stage="S5")
        seen = json.loads(out.read_text(encoding="utf-8"))
        entry = (seen["in_flight"] or {}).get("S5-qa-automator-1") or {}
        eq("T329-1 while the child ran, its entry was on disk: dispatch id, and the child's own pid",
           (entry.get("dispatch_id"), entry.get("pid")), ("S5-qa-automator-1", seen["pid"]))
        check("T329-1 with a start time and no session (a first call)", bool(entry.get("started_at")) and "session_id" not in entry, str(entry))
        eq("T329-1 the child saw QA_FACTORY_DRIVER_RUN = the dispatch id", seen["env"], "S5-qa-automator-1")
        after = json.loads((task_root / "state" / "driver-state.json").read_text(encoding="utf-8"))
        check("T329-1 when the call returned the entry left, and the key with it", "in_flight" not in after, str(after.get("in_flight")))
        eq("T329-1 and the driver's own memory agrees", driver.state.get("in_flight"), None)
        driver.run_claude("role", "p", role="qa-automator", dispatch="S5-qa-automator-1", stage="S5", resume="s-prev")
        entry = (json.loads(out.read_text(encoding="utf-8"))["in_flight"] or {}).get("S5-qa-automator-1") or {}
        eq("T329-1 a resumed call names the session it resumes", entry.get("session_id"), "s-prev")
        driver.run_claude("conductor", "p", stage="S5")
        seen = json.loads(out.read_text(encoding="utf-8"))
        eq("T329-1 control: a call with no dispatch (the conductor) writes no entry and sets no marker",
           (seen["in_flight"], seen["env"]), (None, None))
        with mock.patch.object(subprocess.Popen, "communicate", side_effect=RuntimeError("the call died")):
            try:
                driver.run_claude("role", "p", role="qa-automator", dispatch="S5-qa-automator-2", stage="S5")
                raised = False
            except RuntimeError:
                raised = True
        check("T329-1 control: a call that raises still leaves no entry behind",
              raised and "in_flight" not in json.loads((task_root / "state" / "driver-state.json").read_text(encoding="utf-8")))
        # t-335 A-n6: the marking is INSIDE the try. A marking that raises (here a non-OSError, which `mark_in_flight`
        # does not swallow) used to leave the child waiting on stdin for a prompt nobody sent, and `with Popen` then
        # waited for the child for ever; now the child is killed and the error is the caller's. The stub reads stdin to
        # the end, so a child left alive would not exit by itself: it is the proof the kill happened.
        pids = []
        real_popen = subprocess.Popen

        def spy(*a, **k):
            proc = real_popen(*a, **k)
            pids.append(proc)
            return proc

        with mock.patch.object(subprocess, "Popen", spy), \
                mock.patch.object(driver, "mark_in_flight", side_effect=RuntimeError("the marking died")):
            try:
                driver.run_claude("role", "p", role="qa-automator", dispatch="S5-qa-automator-3", stage="S5")
                died = False
            except RuntimeError as exc:
                died = "the marking died" in str(exc)
        check("T335 A-n6 a marking that raises: the call raises it (the child was killed, `with` did not wait for ever)",
              died and bool(pids) and pids[0].poll() is not None, str([p.poll() for p in pids]))
        check("T335 A-n6 ...and leaves no entry behind", "in_flight" not in driver.state)
    finally:
        harness.cleanup(root)


def t329_item6_a_ticket_file_of_the_person_is_a_question_not_a_factory_fault() -> None:
    """t-329 item 6 (after t-331): the adapter says `owner: person` for a ticket or paste file that is missing or
    empty. `ticket_failure` knew four owner words, so that object read as "the adapter printed no error object" - the
    FACTORY's fault - and a missing ticket file became a factory refusal instead of the question to the person.
    The owner words are now `ticket_adapter.OWNERS`, the adapter's own list. Pinned END TO END (a real driver process,
    the file adapter, the file deleted) and on the function, with the old words as controls."""
    import ticket_adapter
    # --- end to end: `kind: file`, the ticket file is not there
    root, task_root, env = s0_project("QA-1")
    try:
        (root / "tickets" / "QA-1.md").unlink()
        out = s0_run(root, env, "QA-1")
        eq("T329-6 a file adapter with a missing file: the person is asked (exit 3), not refused", out.returncode, 3,
           out.stdout[-900:] + out.stderr[-600:])
        eq("T329-6 the block is `ticket_read` and no model was called", (s0_state(task_root).get("s0_block"), stub_calls(root)),
           ("ticket_read", []))
        ask = s0_question(task_root)
        check_in("T329-6 the question is the file-style one: the ticket file is not there", "I looked for the file QA-1.md", ask)
        check_in("T329-6 ...with a way to put it right and the paste", "put the ticket file in that folder", ask)
        check_not_in("T329-6 never 'the adapter printed no error object'", "no error object", ask + out.stdout + out.stderr)
        check_not_in("T329-6 and never the factory's own refusal", "the cause is the factory's own", out.stdout + out.stderr + ask)
    finally:
        harness.cleanup(root)
    # --- the function: every owner word the adapter can carry survives; a word it does not know is the factory's
    root, task_root, env = d2_seed("QA-9", environment="Local", pending=False)
    try:
        driver = driver_for(root, env, "QA-9")
        for owner in ticket_adapter.OWNERS:
            said = json.dumps({"ok": False, "owner": owner, "status": None, "retry_at": None, "message": "one sentence"})
            got = driver.ticket_failure(1, said, "")
            eq(f"T329-6 owner `{owner}` of the adapter's own list is kept", (got["owner"], got["from_object"], got["message"]),
               (owner, True, "one sentence"))
        check("T329-6 `person` is in the adapter's list (the fixture's own premise)", "person" in ticket_adapter.OWNERS)
        for label, said in (("an owner nobody knows", json.dumps({"ok": False, "owner": "nobody", "message": "x"})),
                            ("an object that says ok", json.dumps({"ok": True, "owner": "person"})),
                            ("no object at all", "not json")):
            got = driver.ticket_failure(1, said, "")
            eq(f"T329-6 control ({label}): the factory's, with the old words", (got["owner"], got["message"], got["from_object"]),
               ("factory", driver.NO_ERROR_OBJECT, False))
        person = driver.ticket_failure(1, json.dumps({"ok": False, "owner": "person", "message": "ticket file not found: X"}), "")
        check("T329-6 a `person` failure is not the factory's fault", not driver.ticket_is_factory_fault(1, person))
        # --- the branch of the question for a read that is not a project folder's (a pasted file that is missing)
        captured = []
        driver.s0_stop = lambda *a, **k: captured.append((a, k))
        driver.config = dict(driver.config, adapters={"ticket": {"kind": "jira"}})
        driver.s0_ticket_read_question(1, "said", person)
        text = captured[0][0][2] if captured else ""
        check_in("T329-6 the `person` branch gives the adapter's own sentence verbatim (FR-8)", "ticket file not found: X", text)
        check_in("T329-6 ...and the way on: put the ticket text in that file, or paste it", "put the ticket text in the file the message names", text)
        check_in("T329-6 ...beside the paste answer", "(c) ", text)
        check_not_in("T329-6 never the tracker's story for a person's file", "through its web interface", text)
        eq("T329-6 and it is the same `ticket_read` question", captured[0][0][0], "ticket_read")
        check_eq("T329-6 the question obeys human-questions.md", human_broken(text), [])
    finally:
        harness.cleanup(root)


def t335_b_n4_a_missing_ticket_file_flag_is_the_question_with_the_path_in_the_answer_block() -> None:
    """t-335 B-n4 (critic t-334): `--ticket-file <missing>` reached the conductor as a raw `Refusal` with the adapter's
    words, and the `person` branch of `s0_ticket_read_question` was reachable by no road. It is wired: the same
    `ticket_read` question, and the path - an instruction, human-questions.md rule 5 - stands in the answer block ONLY,
    never in the body. END TO END (a real driver process, the file adapter, the flag naming a file that is not there),
    then on the function."""
    missing_name = "no-such-ticket.md"
    root, task_root, env = s0_project("QA-1")
    try:
        missing = root / missing_name
        out = s0_run(root, env, "QA-1", "--ticket-file", str(missing))
        eq("T335 B-n4 `--ticket-file` naming a missing file: the person is asked (exit 3), not refused to the conductor",
           out.returncode, 3, out.stdout[-900:] + out.stderr[-600:])
        eq("T335 B-n4 the block is `ticket_read`, no model was called, and no 'tracker failed' mark is left for a later comparison",
           (s0_state(task_root).get("s0_block"), stub_calls(root), "s0_rest_failed" in s0_state(task_root)),
           ("ticket_read", [], False))
        ask = s0_question(task_root)
        body, _sep, answer_block = ask.partition("\n---\nAnswer:")
        check("T335 B-n4 the question has an answer block", bool(_sep), ask[-500:])
        check_not_in("T335 B-n4 the BODY never carries the missing path", missing_name, body)
        check_in("T335 B-n4 the answer block names it", f"The ticket file I looked for: {missing}", answer_block)
        check_in("T335 B-n4 the body says what is missing and points at the block", "named under \"How to answer\" below", body)
        check_not_in("T335 B-n4 the project's folder of ticket files is NOT what was looked at (kind `file` text is not used)",
                     "in the folder of ticket files", body)
        check_in("T335 B-n4 the three answers stand as priced option lines: not needed / retry / the paste, then `stop`",
                 "(a) `not needed` — ", body)
        check_in("T335 B-n4 the retry option", "(b) `retry` — put the ticket text in that file, and I read the ticket again", body)
        check_in("T335 B-n4 the paste option", "(c) paste the ticket here as text", body)
        check_in("T335 B-n4 and the stop option", "(d) `stop` — stop the story here; nothing runs", body)
        eq("T335 B-n4 the body obeys human-questions.md", human_broken(body), [])
        check_not_in("T335 B-n4 and the raw refusal is not relayed", "ticket_adapter get", ask)
        # the answer the person gives is read as for any ticket_read stop: a paste becomes the ticket
        pasted = s0_answer(root, env, "QA-1", "# Pasted title\n\nSome description.\n\n## Acceptance criteria\n- one thing\n", "--ticket-file", str(missing))
        snapshot = task_root / "work" / "ticket-snapshot.json"
        taken = json.loads(snapshot.read_text(encoding="utf-8")) if snapshot.is_file() else {}
        eq("T335 B-n4 the paste is taken: the snapshot is the pasted ticket, labelled as the person's (no second question)",
           (taken.get("title"), (taken.get("provenance") or {}).get("source")), ("Pasted title", "person_pasted"),
           pasted.stdout[-600:] + pasted.stderr[-300:])
    finally:
        harness.cleanup(root)
    # --- the function: with and without the file the adapter names; the project's kind does not change a flag's own file
    root, task_root, env = d2_seed("QA-9", environment="Local", pending=False)
    try:
        driver = driver_for(root, env, "QA-9")
        captured = []
        driver.s0_stop = lambda *a, **k: captured.append((a, k))
        failure = {"owner": "person", "status": None, "retry_at": None, "from_object": True,
                   "message": "ticket file not found: C:/x/mine.md", "file": "C:/x/mine.md"}
        said = "ticket_adapter: ticket file not found: C:/x/mine.md"
        driver.config = dict(driver.config, adapters={"ticket": {"kind": "file", "path": "C:/folder"}})
        driver.s0_ticket_read_question(1, said, failure, own_file=True)
        text, kwargs = captured[-1][0][2], captured[-1][1]
        check_not_in("T335 B-n4 (function, kind file + own_file) the body has no path", "mine.md", text)
        eq("T335 B-n4 (function) the note carries it", kwargs.get("answer_note"), "The ticket file I looked for: C:/x/mine.md")
        check_in("T335 B-n4 (function) the adapter's own sentence goes to the details, with the path",
                 "ticket file not found: C:/x/mine.md", str(kwargs.get("details")))
        driver.state.pop("s0_rest_failed", None)
        driver.s0_ticket_read_question(1, said, failure, own_file=True)
        check("T335 B-n4 (function) own_file leaves no `s0_rest_failed`", "s0_rest_failed" not in driver.state)
        driver.s0_ticket_read_question(1, said, failure)
        text = captured[-1][0][2]
        check("T335 B-n4 control: the project's kind `file` question is the one for a read that is NOT the flag's file",
              "in the folder of ticket files" in text and "mine.md" not in text)
        driver.config = dict(driver.config, adapters={"ticket": {"kind": "jira"}})
        driver.s0_ticket_read_question(1, said, dict(failure, file=None))
        text, kwargs = captured[-1][0][2], captured[-1][1]
        check_in("T335 B-n4 control: an adapter that names no file is relayed as before (the sentence, the old way on)",
                 "ticket file not found: C:/x/mine.md", text)
        eq("T335 B-n4 control: ...and no answer note", kwargs.get("answer_note"), "")
    finally:
        harness.cleanup(root)


def s6_the_manual_block_waits_for_the_writer_lock() -> None:
    """legacy-2406 W2 (M8): the manual S6 runner's in-process controller is a lifecycle command, like every CLI `main`:
    it waits for an in-flight writer instead of failing at once. The wait is `event_store.LIFECYCLE_WAIT_SECONDS`, read
    at CALL time (so a test can shorten it); the only Controller this block builds is that one."""
    import event_store
    task = "QA-9"
    root, task_root, env = d2_seed(task, environment="Local", pending=False)
    try:
        cases = [f"QA-9_TC_{i:03d}" for i in (1, 2)]
        driver, world, launched, moves = manual_rig(root, env, task, cases)
        saved = event_store.LIFECYCLE_WAIT_SECONDS
        event_store.LIFECYCLE_WAIT_SECONDS = 7
        try:
            enter_manual(driver, world, cases)
        finally:
            event_store.LIFECYCLE_WAIT_SECONDS = saved
        check_eq("the manual S6 block is dispatched by a controller that waits for the writer lock (the shortened value is read at call time)",
                 world.waits, [7])
        check_eq("and it did dispatch: one runner, for the block", [(e["role"], e["scope"]) for e in launched],
                 [("qa-runner", cases)])
        driver, world, launched, moves = manual_rig(root, env, task, cases)
        enter_manual(driver, world, cases)
        check_eq("control: unshortened, the wait is the module's own constant", world.waits, [saved])
    finally:
        harness.cleanup(root)


def t329_b270_g_the_manual_block_size_has_one_source() -> None:
    """t-329 (B-270 g): the driver's window size is the controller's own `MANUAL_WINDOW_CASES`, imported - not a second
    literal that a change on one side would leave behind. The class attribute stays settable per instance (tests do)."""
    import re
    import controller
    import story_run
    eq("T329-g the driver's size is the controller's window constant", story_run.Driver.MANUAL_BLOCK_MAX, controller.MANUAL_WINDOW_CASES)
    source = harness.driver_text()
    check("T329-g and the source holds no literal for it", not re.search(r"(?m)^\s*MANUAL_BLOCK_MAX\s*=\s*\d", source))
    check("T329-g it is read from the controller", "MANUAL_BLOCK_MAX = MANUAL_WINDOW_CASES" in source
          and "from controller import MANUAL_WINDOW_CASES" in source)
    task = "QA-9"
    root, task_root, env = d2_seed(task, environment="Local", pending=False)
    try:
        driver = driver_for(root, env, task)
        driver.MANUAL_BLOCK_MAX = 2
        eq("T329-g control: an instance still overrides it (the size is read where the blocks are cut)",
           driver.MANUAL_BLOCK_MAX, 2)
        eq("T329-g control: the class is unchanged by that", story_run.Driver.MANUAL_BLOCK_MAX, controller.MANUAL_WINDOW_CASES)
    finally:
        harness.cleanup(root)


# ---------------------------------------------------------------------------------------------- C1-6b (t-1212)
# S6 as seam questions (spec t-699 section 3.2-3.3, A5-A7). Every question below carries its three price lines per option, its tokens
# unchanged, and an executor in code for each: `retry` / `go on` are the seam's own (`take_seam_answer`), `by hand` is the same pass plus
# a TYPED record (`refused.by`), `reapprove` is the controller's `semantic_reopen`.
PRICE_LABELS = ("the factory:", "you:", "the story:")


def c16b_price_lines(text: str, options: int) -> bool:
    """Every option has its three labelled lines: each label opens one line per option."""
    return all(sum(1 for line in text.splitlines() if line.startswith(label)) == options for label in PRICE_LABELS)


def c16b_refused_by(task_root, cases) -> list:
    """`refused.by` of the request.json of each case ('' when the key is absent)."""
    return [json.loads((task_root / "work" / "evidence" / "manual" / case / "request.json").read_text(encoding="utf-8"))["refused"].get("by", "")
            for case in cases]


def c16b_stand_login_is_priced_and_its_two_passes_are_two_records() -> None:
    """(§3.2, A5, A6, A7) `s6.stand_login`: three options x three price lines, tokens unchanged; the question carries `offered` and the
    block (a seam question). `by hand` -> `refused.by: person_checks`; `go on` -> `left_unchecked`; a pass recorded for other words (the
    conductor's road) -> `left_unchecked` too, even after a `by hand` (the typed record is bound to ITS pass). The `by hand` line does not
    promise `yes`: it states the verdict measured today (`no`). MUTATION `one executor again`: both tokens -> the same `by`."""
    task = "QA-9"
    root, task_root, env = d2_seed(task, environment="Local", pending=False)
    try:
        t292_config(root)
        cases, screens = list(WITH_HTTP), list(SCREENS)
        driver, world, launched, moves = manual_rig(root, env, task, cases, policy=WITH_HTTP)
        _text, _new, person = t292_enter(driver, world, cases)
        eq("C16b stand_login: the tokens are unchanged, in order", list(person.priced), ["retry", "by hand", "go on"])
        check("C16b stand_login: 3 options x 3 price lines", c16b_price_lines(person.text, 3), person.text[-900:])
        eq("C16b stand_login: it is a seam question - `offered`, the moves, the block code knows",
           (person.offered, [o["move"] for o in person.options], person.block),
           (("retry", "by hand", "go on"), ["person_does", "go_on_as_is", "go_on_as_is"], driver.STAND_LOGIN_BLOCK))
        eq("C16b stand_login: and it obeys human-questions.md", human_broken(person.text), [])
        by_hand_line = next(line for line in person.text.splitlines() if line.startswith("the story:") and "left with you" in line)
        check_not_in("C16b stand_login (P21): `by hand` never promises a ready verdict", "will read: ready", by_hand_line)
        check_in("C16b stand_login (C5-4, P21): ...it states the third outcome, conditional, not `no` (the requirement has its \"Left with you\" line)",
                 "ready after your checks only if nothing else holds it", by_hand_line)
        check_not_in("C16b stand_login (C5-4): ...and no longer says the delivery reads `no`", "not ready to ship as is", by_hand_line)
        check_in("C16b stand_login: the person line of `by hand` is the checks left with them", "checks left with you before release", person.text)
        # B-F1 (t-1228, FR-10/FR-41): `go on` leaves the same cases unchecked and the verdict reads the same measured word: the packet
        # never suggests `go on` is the gentler choice for the delivery
        story_lines = [line for line in person.text.splitlines() if line.startswith("the story:")]
        eq("C16b stand_login (B-F1): one `the story:` line per option", len(story_lines), 3)
        check_in("C16b stand_login (B-F1): the `go on` line states the verdict measured today, as `by hand` does", "not ready to ship as is", story_lines[2])
        eq("C16b stand_login (C5-4): `by hand` holds `not_known` (the cases are the person's line), `go on` holds `no` (nothing is left with them)",
           [row["delivery"] for row in NM.load_question_prices()["s6.stand_login"][1:]], ["not_known", "no"])
        check_eq("C16b stand_login: every token has a data row (the loader reads them)",
                 [row["answer"] for row in NM.load_question_prices()["s6.stand_login"]], list(person.priced))
        for token, words in (("by hand", "By hand."), ("go on", "go on")):
            fresh_root, fresh_task_root, fresh_env = d2_seed(task, environment="Local", pending=False)
            try:
                t292_config(fresh_root)
                driver, world, launched, moves = manual_rig(fresh_root, fresh_env, task, cases, policy=WITH_HTTP)
                _text, _new, person = t292_enter(driver, world, cases)
                driver.ask(person)
                eq(f"C16b `{token}`: `ask()` keeps the seam's fields (offered, block)",
                   ((s0_state(fresh_task_root).get("asked") or {}).get("offered"), (s0_state(fresh_task_root).get("asked") or {}).get("block")),
                   (["retry", "by hand", "go on"], "stand login missing"))
                driver.take_answer(Path(d2_answer(fresh_root, words)))
                got = [o for o in (s0_pipeline(fresh_task_root).get("stage_overrides") or []) if o.get("match") == "stand login missing"]
                eq(f"C16b `{token}`: the pass is `waiver.py --words-file`: the words whole", [(o["stage"], o["decision"]) for o in got], [("S6", words)])
                t292_enter(driver, world, cases)
                eq(f"C16b `{token}`: the typed record in each screen case's request.json",
                   c16b_refused_by(fresh_task_root, screens), ["person_checks" if token == "by hand" else "left_unchecked"] * 2)
            finally:
                harness.cleanup(fresh_root)
        # a pass the conductor recorded from free words: no typed record of ours -> `left_unchecked`; and a stale `by hand` record
        # (the pass was replaced by other words) is not read for the new pass
        fresh_root, fresh_task_root, fresh_env = d2_seed(task, environment="Local", pending=False)
        try:
            t292_config(fresh_root)
            d2_pipeline(fresh_task_root, stage_overrides=[{"stage": "S6", "match": "stand login missing", "decision": "ask Dana, she has it",
                                                            "at": "2026-10-02T10:00:00+00:00", "by": "human"}])
            driver, world, launched, moves = manual_rig(fresh_root, fresh_env, task, cases, policy=WITH_HTTP)
            driver.state["login_choice"] = {"token": "by hand", "words": "by hand"}
            t292_enter(driver, world, cases)
            eq("C16b the conductor's pass (free words) and a stale `by hand` record: `left_unchecked`",
               c16b_refused_by(fresh_task_root, screens), ["left_unchecked"] * 2)
        finally:
            harness.cleanup(fresh_root)
        # free words: the conductor, with the words by FILE, no inline `--decision`
        calls = []
        driver, world, launched, moves = manual_rig(root, env, task, cases, policy=WITH_HTTP)
        _text, _new, person = t292_enter(driver, world, cases)
        driver.ask(person)
        driver.conductor = lambda prompt, words=None, **kw: calls.append((prompt, words)) or {"action": "continue", "did": "read"}
        driver.take_answer(Path(d2_answer(root, "I will think about it")))
        check_in("C16b free words: the conductor is told to record them by file", '--block "stand login missing" --words-file ', calls[0][0])
        check_not_in("C16b free words: no inline `--decision` (axis 5)", "--decision", calls[0][0])
        check("C16b free words: and no typed record is made", "login_choice" not in driver.state)
    finally:
        harness.cleanup(root)


def c16b_stand_confirm_is_priced_and_its_answers_have_executors() -> None:
    """(§3.2) `s6.stand_confirm`: the text is the question plus the priced section (3 options x 3 lines when a stand is named and another
    exists); `retry` / `go on` are the seam's executors (the pass is `waiver.py --words-file`, block `stand not confirmed`); the stand's
    NAME is the site's door; free words go to the conductor with the words by FILE (the S5 class of the inline `--decision`).
    MUTATION `price section dropped`: the count of price lines is 0."""
    import contextlib
    import io
    import story_run
    task = "QA-9"
    root, task_root, env = d2_seed(task, environment="Local", pending=True)
    try:
        driver = driver_for(root, env, task)
        text = driver.stand_question_text("S6", "Local", ["Local", "Staging"], "manual")
        check("C16b stand_confirm: 3 options x 3 price lines", c16b_price_lines(text, 3), text[-700:])
        eq("C16b stand_confirm: the priced tokens", list(text.priced), ["retry", "go on"])
        eq("C16b stand_confirm: it obeys human-questions.md", human_broken(text), [])
        eq("C16b stand_confirm: the answers of the data row = the options of the site (named, another stand)",
           [row["answer"] for row in NM.load_question_prices()["s6.stand_confirm"]], ["stand name", "retry", "go on"])
        eq("C16b stand_confirm: no stand recorded: retry + go on, the answers are a subset of the row",
           list(driver.stand_question_text("S5", "", []).priced), ["retry", "go on"])
        real = driver.py
        driver.py = lambda script, *a, **k: (1, "ENVIRONMENT: down") if script == "env_probe.py" else real(script, *a, **k)
        try:
            driver.stand_check("S6", "manual")
            person = None
        except story_run.Person as raised:
            person = raised
        check("C16b stand_confirm: stand_check raises a Person", person is not None)
        eq("C16b stand_confirm: a seam question - kind `environment`, `offered`, the block",
           (person.kind, person.offered, person.block, person.stand_stage), ("environment", ("retry", "go on"), "stand not confirmed", "S6"))
        driver.ask(person)
        driver.take_answer(Path(d2_answer(root, "go on")))
        got = [(o["stage"], o["match"], o["decision"]) for o in (s0_pipeline(task_root).get("stage_overrides") or [])]
        eq("C16b stand_confirm: `go on` is the seam's pass: `waiver.py --words-file`, the words whole", got, [("S6", "stand not confirmed", "go on")])
        # the stand's name is the site's door; the next entry probes it
        d2_pipeline(task_root, stage_overrides=[])
        driver = driver_for(root, env, task)
        driver.py = lambda script, *a, **k: (1, "ENVIRONMENT: down") if script == "env_probe.py" else real(script, *a, **k)
        driver.config = dict(driver.config, environments=[{"name": "Local"}, {"name": "Staging"}])
        try:
            driver.stand_check("S6", "manual")
        except story_run.Person as raised:
            driver.ask(raised)
        driver.take_answer(Path(d2_answer(root, "Staging")))
        eq("C16b stand_confirm: the name sets the stand (pending until probed)",
           (s0_pipeline(task_root).get("environment"), s0_pipeline(task_root).get("environment_pending")), ("Staging", True))
        # C-F3 (t-1228): the journal row of the stand answer is `answer_row` - a refused write is OWED, the stand is still set (the words
        # reach the executor directly), and the drain writes the row once the journal answers
        d2_pipeline(task_root, stage_overrides=[])
        driver = driver_for(root, env, task)
        driver.config = dict(driver.config, environments=[{"name": "Local"}, {"name": "Staging"}])
        journal_ok = [False]

        def journal_down(script, *a, **k):
            if script == "env_probe.py":
                return 1, "ENVIRONMENT: down"
            if script == "log_append.py" and not journal_ok[0]:
                return 1, "journal busy"
            return real(script, *a, **k)
        driver.py = journal_down
        try:
            driver.stand_check("S6", "manual")
        except story_run.Person as raised:
            driver.ask(raised)
        with contextlib.redirect_stdout(io.StringIO()):
            driver.take_answer(Path(d2_answer(root, "Local")))
        eq("C16b stand_confirm (C-F3): the stand is set whatever the journal does",
           (s0_pipeline(task_root).get("environment"), s0_pipeline(task_root).get("environment_pending")), ("Local", True))
        eq("C16b stand_confirm (C-F3): ...and the refused `human_answer` row of the words is OWED",
           [(r["script"], "human_answer" in r["args"], any("stand at S6: Local" in a for a in r["args"])) for r in driver.state.get("owed_rows") or []],
           [("log_append.py", True, True)])
        journal_ok[0] = True
        with contextlib.redirect_stdout(io.StringIO()):
            driver.owed_rows_step()
        eq("C16b stand_confirm (C-F3): ...and the drain writes it", driver.state.get("owed_rows") or [], [])
        # free words: the conductor, the words by FILE
        calls = []
        driver = driver_for(root, env, task)
        driver.py = lambda script, *a, **k: (1, "ENVIRONMENT: down") if script == "env_probe.py" else real(script, *a, **k)
        driver.state["asked"] = {"kind": "environment", "stage": "S6", "dispatch": ""}
        driver.state["stand_question"] = "S6"
        driver.save_state()
        (task_root / "state" / "driver-question.md").write_text("# q\nkind: environment\n", encoding="utf-8")
        driver.conductor = lambda prompt, words=None, **kw: calls.append((prompt, words)) or {"action": "continue", "did": "read"}
        with contextlib.redirect_stdout(io.StringIO()):
            driver.take_answer(Path(d2_answer(root, "use whatever works")))
        check_in("C16b stand_confirm free words: the command takes the words by file", '--block "stand not confirmed" --words-file ', calls[0][0])
        check_not_in("C16b stand_confirm free words: no inline `--decision` (axis 5)", "--decision", calls[0][0])
    finally:
        harness.cleanup(root)


def c16b_gate_a_dry_is_a_priced_question_with_three_executors() -> None:
    """(§3.3, edges 10, 6, 7) `s6.gate_a_dry`: a Person of kind `gate_a_dry` with `reapprove` / `go on` / `stop`, 3 lines each. `reapprove`
    -> the controller's `semantic_reopen` with the answer words as the reason and the MANUAL cases as the scope (the facts the
    controller is asked with: its revision); `go on` -> `waiver.py --stage S6 --block "gate A recorded dry" --words-file`, and the question
    is not asked again (the note line stays); `stop` -> held. `reapprove` is NOT offered while a dispatch runs, in a run that records
    gates dry (`--dry-run`), with no approved gate A, or with no case the approved scope holds - and a typed `reapprove` then goes to
    the conductor, never to the controller. MUTATION `the dry-gate Person removed`: the first check fails."""
    import contextlib
    import io
    from unittest import mock
    import story_run
    task = "QA-9"
    root, task_root, env = d2_seed(task, environment="Local", pending=False)
    try:
        plan = [{"id": "TS-1", "disposition": "manual-agent", "coverage_obligations": [{"obligation_id": "OB-1", "decision": "new"}]}]
        (task_root / "work" / "test-plan.json").write_text(json.dumps({"rows": plan}), encoding="utf-8")
        index = {"QA-9_TC_001": {"path": task_root / "work" / "test-cases" / "QA-9_TC_001.md", "plan_row": "TS-1"},
                 "QA-9_TC_002": {"path": task_root / "work" / "test-cases" / "QA-9_TC_002.md", "plan_row": "TS-2"}}

        def build(running=False, approved=True, dry=False, scope=("QA-9_TC_001", "QA-9_TC_002")):
            driver = driver_for(root, env, task)
            driver.dry = dry
            ctl = {"dispatches": {"S6-qa-runner-1": {"stage": "S6", "status": "running"}} if running else {},
                   "decisions": {"d1": {"gate": "A", "status": "approved", "source_revision": "r1"}} if approved else {},
                   "scope": list(scope), "source_revision": "r1", "revision": 7}
            driver.controller_state = lambda: ctl
            calls = []
            driver.controller = lambda op, *a, input_data=None, **k: calls.append((op, input_data)) or {}
            return driver, calls

        def raised_person(driver):
            out = io.StringIO()
            try:
                with mock.patch("contract.case_index", lambda _root: index), contextlib.redirect_stdout(out):
                    driver.manual_gate_note()
            except story_run.Person as person:
                return person, out.getvalue()
            return None, out.getvalue()

        driver, calls = build()
        person, said = raised_person(driver)
        check("C16b gate A dry: the manual rows with no executable obligation raise a Person", person is not None)
        eq("C16b gate A dry: kind `gate_a_dry`, at S6, the tokens, the moves, the block",
           (person.kind, person.stage, person.offered, [o["move"] for o in person.options], person.block),
           ("gate_a_dry", "S6", ("reapprove", "go on", "stop"), ["site_door", "go_on_as_is", "stop_here"], "gate A recorded dry"))
        check("C16b gate A dry: 3 options x 3 price lines", c16b_price_lines(person.text, 3), person.text[-900:])
        check_in("C16b gate A dry: `reapprove` states the stages it runs again (measured: the case review, not the designer)",
                 "the case review of S4, gate A and the manual half of S6 run again", person.text)
        check_in("C16b gate A dry: the case named is its id (the other plan row's case is not named)", "QA-9_TC_001", person.text)
        check_not_in("C16b gate A dry: and the case of another row is not", "QA-9_TC_002", person.text)
        eq("C16b gate A dry: it obeys human-questions.md", human_broken(person.text), [])
        eq("C16b gate A dry: every token has a data row, and the set is the site's",
           [row["answer"] for row in NM.load_question_prices()["s6.gate_a_dry"]], list(person.priced))
        check_not_in("C16b gate A dry: no command, no script in anything the person reads", "semantic_reopen", person.text + said)
        # reapprove -> semantic_reopen with the words, the manual cases, the controller's own revision
        driver.ask(person)
        driver.take_answer(Path(d2_answer(root, "reapprove")))
        eq("C16b gate A dry: `reapprove` calls semantic_reopen with the manual cases (and only the controller's op)",
           [(op, d["reason"], d["affected_scope"], d["expected_revision"]) for op, d in calls], [("semantic_reopen", "reapprove", ["QA-9_TC_001"], 7)])
        check("C16b gate A dry: ...with an idempotency key of its own", calls[0][1]["idempotency_key"].startswith("semantic_reopen:gate_a_dry:"))
        eq("C16b gate A dry: ...and no waiver was written", s0_pipeline(task_root).get("stage_overrides") or [], [])
        # C-F3 (t-1228): the journal row of the words is `answer_row` - a refused write is OWED (the drain writes it again, the seam asks
        # after a second failure) and the reopening still runs: the words reach the executor directly (E8 of t-1152)
        driver, calls = build()
        person, _said = raised_person(driver)
        driver.ask(person)
        base_py = driver.py
        driver.py = lambda script, *a, **k: (1, "journal busy") if script == "log_append.py" else base_py(script, *a, **k)
        with contextlib.redirect_stdout(io.StringIO()):
            driver.take_answer(Path(d2_answer(root, "reapprove")))
        eq("C16b gate A dry (C-F3): a refused journal row is owed, as a `human_answer` row of those words",
           [(r["script"], "human_answer" in r["args"], any("gate A recorded dry (reapprove): " in a for a in r["args"])) for r in driver.state.get("owed_rows") or []],
           [("log_append.py", True, True)])
        eq("C16b gate A dry (C-F3): ...and the reopening still ran with the words", [op for op, _data in calls], ["semantic_reopen"])
        driver.py = base_py
        with contextlib.redirect_stdout(io.StringIO()):
            driver.owed_rows_step()
        eq("C16b gate A dry (C-F3): ...and the drain writes it", driver.state.get("owed_rows") or [], [])
        # the controller refuses: said, nothing changed, the question comes back
        driver, calls = build()
        person, _said = raised_person(driver)
        driver.ask(person)
        driver.controller = lambda op, *a, input_data=None, **k: (_ for _ in ()).throw(story_run.Refusal("checkpoint active work before reopening Gate A"))
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                driver.take_answer(Path(d2_answer(root, "reapprove")))
            held = None
        except story_run.Person as raised:
            held = raised
        check("C16b gate A dry: a refusal of the controller comes back as the held question, with its words",
              held is not None and "could not be carried out" in held.text and "checkpoint active work" in (held.details or ""))
        # go on -> the waiver by file, asked once (the note line stays)
        driver, calls = build()
        person, _said = raised_person(driver)
        driver.ask(person)
        with contextlib.redirect_stdout(io.StringIO()):
            driver.take_answer(Path(d2_answer(root, "go on")))
        got = [(o["stage"], o["match"], o["decision"]) for o in (s0_pipeline(task_root).get("stage_overrides") or [])]
        eq("C16b gate A dry: `go on` is `waiver.py --stage S6 --block` with the words by file", got, [("S6", "gate A recorded dry", "go on")])
        again, said = raised_person(build()[0])
        eq("C16b gate A dry: a passed question is not asked again - the line stays", (again, "gate A was recorded dry" in said), (None, True))
        d2_pipeline(task_root, stage_overrides=[])
        # stop -> held
        driver, calls = build()
        person, _said = raised_person(driver)
        driver.ask(person)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                driver.take_answer(Path(d2_answer(root, "stop")))
            held = None
        except story_run.Person as raised:
            held = raised
        check("C16b gate A dry: `stop` holds the question (nothing runs, nothing is recorded)",
              held is not None and held.text.startswith("You said to stop.") and calls == [] and not s0_pipeline(task_root).get("stage_overrides"))
        # edge 10: reapprove is not offered when its executor would not run
        for label, kwargs, why in (("a dispatch runs", {"running": True}, "a role is still working"),
                                   ("the run records gates dry", {"dry": True}, "this run records gates dry"),
                                   ("no approved gate A", {"approved": False}, "there is no approved gate A"),
                                   ("the approved scope holds none of the cases", {"scope": ()}, "could not name these cases")):
            driver, calls = build(**kwargs)
            person, _said = raised_person(driver)
            eq(f"C16b gate A dry edge 10 ({label}): `reapprove` is not offered; `go on` and `stop` are", person.offered, ("go on", "stop"))
            check_in(f"C16b gate A dry edge 10 ({label}): and ONE line says why", why, person.text)
            check_not_in(f"C16b gate A dry edge 10 ({label}): no `reapprove` option in the text", "`reapprove`", person.text)
            driver.ask(person)
            seen = []
            driver.conductor = lambda prompt, words=None, **kw: seen.append(words) or {"action": "continue", "did": "read"}
            with contextlib.redirect_stdout(io.StringIO()):
                driver.take_answer(Path(d2_answer(root, "reapprove")))
            eq(f"C16b gate A dry edge 10 ({label}): a typed `reapprove` goes to the conductor, never to the controller", (calls, seen), ([], ["reapprove"]))
    finally:
        harness.cleanup(root)


def c16b_fix_round_one_words_door_one_token_table() -> None:
    """(t-1228 B-F2, B-F3) The words door of the stand prompts is `person_words.door` (the file option has ONE text, the path of the
    answer file is its `path` argument); the tokens the seam owns are `NM.TOKEN_MOVES` and a site table adds only its own words.
    MUTATION `the second door text restored`: `_words_door` builds `--words-file` itself -> the first source check fails."""
    import inspect
    import person_words
    import story_run
    door_source = inspect.getsource(story_run.Driver._words_door)
    check("B-F2: `_words_door` renders through person_words.door", "person_words.door(" in door_source)
    check_not_in("B-F2: ...and holds no text of the file option of its own", "--words-file", door_source.split('"""')[2])
    command = 'python waiver.py --task T --stage S6 --block "stand login missing"'
    eq("B-F2: the door with the answer file is the plain door with that path in the place of the placeholder",
       person_words.door(command, path="work/answers/a.md"), command + " --words-file work/answers/a.md")
    eq("B-F2: no path - the placeholder as before (the form a role reads, and a person reads)",
       (person_words.door(command), person_words.door(command, for_person=True)),
       (command + " --words-file <file>", command + " --words-file <file with your words>"))
    eq("B-F3: the seam's own tokens are NM.TOKEN_MOVES, whole", {t: m for t, m in story_run.Driver.SITE_MOVES.items() if t in NM.TOKEN_MOVES}, NM.TOKEN_MOVES)
    eq("B-F3: ...and the site adds only its two words", sorted(set(story_run.Driver.SITE_MOVES) - set(NM.TOKEN_MOVES)), ["by hand", "reapprove"])
    table_lines = [part.split("\n", 1)[0] for part in harness.driver_text().split("SITE_MOVES = ")[1:]]      # every assignment of the table, in the whole driver set
    check("B-F3: the table is built from NM.TOKEN_MOVES, not copied", len(table_lines) >= 1 and all("{**NM.TOKEN_MOVES," in line for line in table_lines), str(table_lines))


# --- HF2-11b: the live checks of the tests that changed after their run are proved again by code, before S6 closes -------
# The keys (spec t-120 section 3 "11b" as amended by section 10): K1 `s6_freshness` reads `proof_level.staleness` (the run rows'
# own shas move a result from `stand` to `run`; `probes` carries the stale live checks); K2 stale probes + every run standing +
# a stand -> one `probe_by_code.py` each BEFORE the reduction; K3 stale runs -> the runner with `complete=False`, the proofs on its
# return; K4 no stand (the WORD) -> no probe, a digest line; K5 nothing stale -> today's calls and digest; K6 40 tests from one
# fixture -> 40 in "run only", 40 probes, the time in the digest; K-P5 -> B-K1 (HF3-6): no running dispatch -> `--s6-close`,
# the tool is called; K-P9 a `replay` of None -> a digest line naming the instance. `staleness` itself is 11a's (test_run_freshness).

def pin_project(root):
    """`hooklib.project_root()` caches its answer for the life of the process and `proof_level` reads the test files under it; a
    driver test pins it to its own project and gives the old value back with `unpin_project`."""
    import hooklib
    saved = hooklib._PROJECT_ROOT_CACHE
    hooklib._PROJECT_ROOT_CACHE = Path(root).resolve()
    return saved


def unpin_project(saved) -> None:
    import hooklib
    hooklib._PROJECT_ROOT_CACHE = saved


def d1_blocks(root, task_root) -> None:
    """`d1_write_blocks` plus the test file the manifest names: since HF2-11b a result of a test whose file is gone does not
    stand (`run_freshness` rule 1), so the world of a result that stands has the file on disk."""
    d1_write_blocks(task_root)
    (Path(root) / "tests").mkdir(parents=True, exist_ok=True)
    (Path(root) / "tests" / "t.py").write_text("def test_a():\n    assert 1 == 1\n\n\ndef test_b():\n    assert 1 == 2\n", encoding="utf-8")


WHY_RUN = "the test, or a fixture or helper it uses, changed since run a1"
REPLAY_A = {"test": "tests/t.py::test_a", "instance": "test_a", "mutation": "invert", "oracle": ""}
REPLAY_B = {"test": "tests/t.py::test_b", "instance": "test_b", "mutation": "expected", "oracle": "tests/helpers.py::expected_total"}
RUNNING_S6 = {"S6-qa-runner-1": {"id": "S6-qa-runner-1", "stage": "S6", "status": "running", "execution_kind": "automation",
                                  "scope": ["TC-1", "TC-2"]}}
ACCEPTED_S6 = {"S6-qa-runner-1": {"id": "S6-qa-runner-1", "stage": "S6", "status": "accepted", "execution_kind": "automation",
                                   "scope": ["TC-1", "TC-2"]}}


def row(run=("fresh", ""), probe=None) -> dict:
    """One instance of what `proof_level.staleness` answers."""
    return {"run": run, "probe": probe if probe is not None else {"state": "not_required", "why": "", "replay": None}}


def stale_probe(replay) -> dict:
    return {"state": "stale", "why": "the live check was measured on other code than the test holds now", "replay": replay}


class Staleness:
    """`proof_level.staleness` replaced for a block: `answer` is `{instance id: row}` (an id it does not name reads fresh and
    needs no live check) or the exception it raises; `calls` are the id lists the driver asked about."""

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def __enter__(self):
        import proof_level
        self.module, self.saved = proof_level, proof_level.staleness

        def fake(task_root, manifest, ids):
            self.calls.append(list(ids))
            if isinstance(self.answer, Exception):
                raise self.answer
            return {i: self.answer.get(i, row()) for i in ids}
        proof_level.staleness = fake
        return self

    def __exit__(self, *_exc):
        self.module.staleness = self.saved


def reprobe_rig(root, env, task, *, dispatches=None, mark=None, reply=None, manual=()):
    """`d1_driver` plus: the controller's dispatch table as given, the mark `s6_probe_after` as given (None = absent), every
    `probe_by_code.py` call recorded IN ORDER among the moves (`("probe", argv)`) and answered by `reply(argv)` (default: exit 0,
    `intended_failure`), and the `site` of every close by code. (driver, launched roles, moves, probe argvs, sites)."""
    driver, launched, moves, _started = d1_driver(root, env, task, manual=manual)
    probes, sites = [], []
    driver.controller_state = lambda: {"dispatches": dict(dispatches or {})}
    if mark is not None:
        driver.state["s6_probe_after"] = mark
    spied, real_close = driver.py, driver.close_by_code

    def py(script, *args, **kwargs):
        if script != "probe_by_code.py":
            return spied(script, *args, **kwargs)
        argv = [str(a) for a in args]
        probes.append(argv)
        moves.append(("probe", argv))
        return reply(argv) if reply else (0, json.dumps({"verdict": "intended_failure"}))
    driver.py = py
    driver.close_by_code = lambda *a, **k: (sites.append(k.get("site")) or real_close(*a, **k))
    return driver, launched, moves, probes, sites


def close_digest(moves) -> str:
    """The `--digest` of the `stage_done` the code close wrote."""
    args = next((m[1] for m in moves if m[0] == "stage_done"), "")
    return args.split("--digest ", 1)[1].rsplit(" --no-journal", 1)[0] if "--digest " in args else ""


def hf2_11b_s6_freshness_reads_the_run_rows_shas() -> None:
    """K1 + P7: a result the evidence function keeps moves from `stand` to `run` when the run row's own shas say it ran other code
    (a helper module `helper_files` does not name: the evidence compares the whole-file fingerprint and keeps it); `probes` holds the
    stale live checks; `unknown` is NOT stale; the keys are today's plus `probes`; an exception is `undecided`, as today.
    MUTATION `s6_freshness leaves a staleness-stale instance in stand` -> the first three checks fail."""
    task = "QA-9"
    two = {"test_a": ("result", "passed", ""), "test_b": ("result", "failed", "")}
    root, task_root, env = d2_seed(task, environment="Local", pending=False)
    pin = pin_project(root)
    try:
        d1_blocks(root, task_root)
        driver, launched, moves, _started = d1_driver(root, env, task)
        answer = {"test_a": row(("stale", WHY_RUN)), "test_b": row(("fresh", ""), stale_probe(REPLAY_B))}
        with D1Evidence(d1_answer(two)), Staleness(answer) as held:
            fresh = driver.s6_freshness(["TC-1", "TC-2"])
        eq("K1 the staleness reader is asked once, for the instances the evidence named", held.calls, [["test_a", "test_b"]])
        eq("K1 the instance whose run row says other code leaves `stand` for `run`, with the reader's words",
           (fresh["stand"], fresh["run"]), (["test_b"], {"test_a": WHY_RUN}))
        eq("K1 and the counts follow the results that stand", (fresh["passed"], fresh["failed"]), (0, 1))
        eq("K1 `probes` holds the stale live check with its replay", fresh["probes"], {"test_b": REPLAY_B})
        eq("K1 the keys are today's plus `probes`", sorted(fresh), sorted(["decided", "why", "stand", "run", "passed", "failed", "probes"]))
        eq("P7 the runner is told the SAME predicate's answer",
           driver.s6_freshness_lines(fresh), [f"Results that stand: test_b; run only: test_a ({WHY_RUN})."])
        with D1Evidence(d1_answer(two)), Staleness({"test_a": row(("unknown", "the run recorded no per-test identity")), "test_b": row()}):
            fresh = driver.s6_freshness(["TC-1", "TC-2"])
        eq("K1 `unknown` is not `stale`: both results stand, no live check is stale",
           (fresh["stand"], fresh["run"], fresh["probes"]), (["test_a", "test_b"], {}, {}))
        with D1Evidence(d1_answer(two)), Staleness(RuntimeError("boom")):
            fresh = driver.s6_freshness(["TC-1", "TC-2"])
        eq("K1 an exception inside the reader is `undecided`, with its words, and the keys are the same",
           (fresh["decided"], fresh["why"], fresh["probes"], fresh["run"]), (False, "RuntimeError: boom", {}, {}))
        with D1Evidence({"instances": {}, "observed": False, "why": "run-budget.json cannot be read"}):
            fresh = driver.s6_freshness(["TC-1", "TC-2"])
        eq("K1 an undecided answer of the evidence carries `probes` too", (fresh["decided"], fresh["probes"]), (False, {}))
    finally:
        unpin_project(pin)
        harness.cleanup(root)


def hf2_11b_stale_live_checks_are_proved_again_before_the_reduction() -> None:
    """K2 + K-P5 + K-P9: every run stands, some live checks are stale, a stand is up -> one `probe_by_code.py` each, BEFORE
    `finalize_task.py`, the close at site `s6.reprobed` with the count and the time in the digest. A failed proof, a verdict other than
    `intended_failure`, a `replay` of None, a refusal of the close context: ONE digest line each, no question, S6 closes.
    HF3-6 (B-K1..B-K4): no running dispatch -> `--s6-close`; a running one -> `--dispatch`; the receipt names each probe record.
    MUTATIONS: `the probe before the runs` -> K3 (next scenario); `no running dispatch and no call (S6_NO_DISPATCH back)` -> B-K1;
    `--s6-close with a running S6 dispatch` -> B-K2; `the records not in the evidence` -> B-K3; `a refusal of the context stops S6`
    -> B-K4; `the empty set changes the digest` -> K5."""
    import story_run
    task = "QA-9"
    two = {"test_a": ("result", "passed", ""), "test_b": ("result", "failed", "")}
    both = {"test_a": row(("fresh", ""), stale_probe(REPLAY_A)), "test_b": row(("fresh", ""), stale_probe(REPLAY_B))}
    root, task_root, env = d2_seed(task, environment="Local", pending=False)
    pin = pin_project(root)
    try:
        d1_blocks(root, task_root)
        # every proof lands: before the reduction, in the order of the instances, under the OPEN dispatch
        driver, launched, moves, probes, sites = reprobe_rig(root, env, task, dispatches=RUNNING_S6)
        with D1Evidence(d1_answer(two)), Staleness(both):
            driver.stage_S6()
        eq("K2 the proofs come BEFORE the reduction, then the receipt, then the close; no runner",
           ([m[0] for m in moves], launched), (["probe", "probe", "finalize", "code_only", "stage_done"], []))
        eq("K2 the first proof is the replay of the record, under the open S6 dispatch",
           probes[0], ["--task", task, "--dispatch", "S6-qa-runner-1", "--test", "tests/t.py::test_a", "--instance", "test_a",
                       "--mutation", "invert", "--json"])
        eq("K2 and the second names its mutation and the oracle the record had (`--oracle`)",
           probes[1][-5:], ["--mutation", "expected", "--json", "--oracle", "tests/helpers.py::expected_total"])
        eq("K2 the close is at its own site", sites, ["s6.reprobed"])
        digest = close_digest(moves)
        check_in("K2 the digest says how many were proved again, with the time", "re-proved 2 probes after the tests changed (", digest)
        check("K2 ...and the time is a number of seconds", re.search(r"\(\d+ s\)", digest) is not None, digest)
        check_in("K2 the receipt's reason carries the same words", "re-proved 2 probes after the tests changed", moves[3][2])
        eq("K2 the receipt stands on the manifest and the jobs", moves[3][3], ["work/automation-manifest.json", "state/execution-jobs"])

        # a proof that fails (exit 2, the tool's refusal) and one that answers another verdict: a line each, no question, S6 closes
        def reply(argv):
            if "test_a" in argv[argv.index("--instance") + 1]:
                return 2, json.dumps({"status": "refused", "error": "no active dispatch in story QA-9"})
            return 0, json.dumps({"verdict": "no_failure", "words": "the inverted assertion did not fail"})
        driver, launched, moves, probes, sites = reprobe_rig(root, env, task, dispatches=RUNNING_S6, reply=reply)
        with D1Evidence(d1_answer(two)), Staleness(both):
            driver.stage_S6()
        digest = close_digest(moves)
        check_in("K2 a failed proof is one line with its exit and the tool's words",
                 "test_a: not proved again (probe_by_code exit 2): no active dispatch in story QA-9", digest)
        check_in("K2 a verdict other than intended_failure is one line with the tool's words",
                 "test_b: the probe gave `no_failure`, not `intended_failure`: the inverted assertion did not fail", digest)
        check_in("K2 and nothing was proved", "re-proved 0 probes after the tests changed (", digest)
        eq("K2 neither failure asks anyone or stops S6: the close is recorded", ([m[0] for m in moves][-2:], sites), (["code_only", "stage_done"], ["s6.reprobed"]))

        # K-P9: a replay of None names the instance, the other is still proved
        driver, launched, moves, probes, sites = reprobe_rig(root, env, task, dispatches=RUNNING_S6)
        with D1Evidence(d1_answer(two)), Staleness({"test_a": row(("fresh", ""), stale_probe(None)), "test_b": both["test_b"]}):
            driver.stage_S6()
        digest = close_digest(moves)
        check_in("K-P9 a probe code cannot replay is named, with why", "test_a: not proved again - the probe cannot be replayed by code", digest)
        check_in("K-P9 ...among the reasons: the line anchor moved with the edit", "the probe's line anchor moved with the edit", digest)
        eq("K-P9 only the replayable one is proved", [p[p.index("--instance") + 1] for p in probes], ["test_b"])
        check_in("K-P9 and counted", "re-proved 1 probes after the tests changed (", digest)

        # B-K1 (was K-P5, HF3-6): no RUNNING dispatch -> the tool IS called, for every replay, in the close context of S6
        # (`--s6-close`, never `--dispatch`); the old line is gone; S6 closes at its site
        for label, table in (("none at all", {}), ("an accepted one only", ACCEPTED_S6)):
            # an accepted automation runner is `auto_done`: that is the re-entry (the mark says the runner was ours), not the first entry
            driver, launched, moves, probes, sites = reprobe_rig(root, env, task, dispatches=table, mark="S6-qa-runner-1" if table else None)
            with D1Evidence(d1_answer(two)), Staleness(both):
                driver.stage_S6()
            digest = close_digest(moves)
            eq(f"B-K1 {label}: the tool is called for each replay, in order", [p[p.index("--instance") + 1] for p in probes], ["test_a", "test_b"])
            eq(f"B-K1 {label}: every call names the close context and no dispatch",
               [("--s6-close" in p, "--dispatch" in p) for p in probes], [(True, False)] * 2)
            check_in(f"B-K1 {label}: the digest says what was proved again", "re-proved 2 probes after the tests changed (", digest)
            check_not_in(f"B-K1 {label}: the old line is nowhere in the digest", "re-probe skipped: no open S6 dispatch", digest)
            eq(f"B-K1 {label}: the stage closes at its site, after the proofs", (sites, [m[0] for m in moves]),
               (["s6.reprobed"], ["probe", "probe", "finalize", "code_only", "stage_done"]))
        eq("B-K1 the constant of the old line is gone", hasattr(story_run.Driver, "S6_NO_DISPATCH"), False)

        # B-K2: a RUNNING S6 dispatch -> `--dispatch <id>`, never `--s6-close` (the tool runs under the role's own dispatch)
        driver, launched, moves, probes, sites = reprobe_rig(root, env, task, dispatches=RUNNING_S6)
        with D1Evidence(d1_answer(two)), Staleness(both):
            driver.stage_S6()
        eq("B-K2 a running S6 dispatch: the call carries it and not the close context",
           [("--dispatch" in p and p[p.index("--dispatch") + 1], "--s6-close" in p) for p in probes], [("S6-qa-runner-1", False)] * 2)

        # B-K3: the receipt names each probe record the tool printed; a refusal printed none
        def reply_records(argv):
            if "test_a" in argv[argv.index("--instance") + 1]:
                return 0, json.dumps({"verdict": "intended_failure", "record": "work/probes/test_a.json"})
            return 2, json.dumps({"status": "refused", "error": "a dispatch is open in this story (S6-x): a probe runs under it"})
        driver, launched, moves, probes, sites = reprobe_rig(root, env, task, dispatches={}, reply=reply_records)
        with D1Evidence(d1_answer(two)), Staleness(both):
            driver.stage_S6()
        eq("B-K3 the receipt stands on the manifest, the jobs and the record of the proof that gave one",
           next(m[3] for m in moves if m[0] == "code_only"), ["work/automation-manifest.json", "state/execution-jobs", "work/probes/test_a.json"])

        # B-K3 + B-K4: a refusal of the context (exit 2, no record) is ONE line with the tool's words, no question, S6 closes
        driver, launched, moves, probes, sites = reprobe_rig(root, env, task, dispatches={}, reply=lambda argv: (
            2, json.dumps({"status": "refused", "error": "a dispatch is open in this story (S6-x): a probe runs under it"})))
        with D1Evidence(d1_answer(two)), Staleness(both):
            driver.stage_S6()
        digest = close_digest(moves)
        check_in("B-K4 the refused context is a digest line with the exit and the tool's words",
                 "test_a: not proved again (probe_by_code exit 2): a dispatch is open in this story (S6-x)", digest)
        eq("B-K4 one line each (one per instance) and nothing was proved", (digest.count("not proved again (probe_by_code exit 2)"), "re-proved 0 probes" in digest), (2, True))
        eq("B-K4 no question, S6 is closed at its site", ([m[0] for m in moves][-2:], sites), (["code_only", "stage_done"], ["s6.reprobed"]))
        eq("B-K3 a refusal printed no record: the evidence is the base", next(m[3] for m in moves if m[0] == "code_only"),
           ["work/automation-manifest.json", "state/execution-jobs"])
        # a record path that is not a probe record of the story is not evidence (never a path out of the story)
        driver, launched, moves, probes, sites = reprobe_rig(root, env, task, dispatches={}, reply=lambda argv: (
            0, json.dumps({"verdict": "intended_failure", "record": "../../etc/x.json"})))
        with D1Evidence(d1_answer(two)), Staleness(both):
            driver.stage_S6()
        eq("B-K3 a record path outside work/probes is not named", next(m[3] for m in moves if m[0] == "code_only"),
           ["work/automation-manifest.json", "state/execution-jobs"])
        # G-2 (t-1277): an `already_probed` answer by a product record prints `work/probes/product/<stem>.json`: it is named,
        # once, like the `probe_record` one; a path that climbs out of that folder, or goes deeper, is still dropped
        for label, printed, named in (
                ("a product record is named", "work/probes/product/test_a.json", ["work/probes/product/test_a.json"]),
                ("a product record deeper down is not", "work/probes/product/x/test_a.json", []),
                ("a climb out of the product folder is not", "work/probes/product/../../x.json", [])):
            driver, launched, moves, probes, sites = reprobe_rig(root, env, task, dispatches={}, reply=lambda argv, p=printed: (
                0, json.dumps({"verdict": "intended_failure", "record": p})))
            with D1Evidence(d1_answer(two)), Staleness(both):
                driver.stage_S6()
            eq(f"G-2 {label} (once for the two instances)", next(m[3] for m in moves if m[0] == "code_only"),
               ["work/automation-manifest.json", "state/execution-jobs"] + named)
    finally:
        unpin_project(pin)
        harness.cleanup(root)


def hf2_11b_the_tool_takes_only_a_running_dispatch() -> None:
    """The fact K-P5 stands on, from the tool itself (`execution_request.find_active_dispatch`, what `probe_by_code.py` reaches
    through `build_mine_request`): an `accepted` dispatch is refused, a `running` one is found. The code-closed S6 path opens no
    dispatch (`close_by_code` -> `code_only` is a receipt, and the controller REFUSES it while any dispatch is running). The road
    without a running dispatch is `--s6-close` (HF3-6)."""
    import tempfile
    import execution_request
    for status, found in (("accepted", False), ("running", True)):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "QA-9" / "state"
            state.mkdir(parents=True)
            (state / "controller.json").write_text(json.dumps({"dispatches": {"S6-qa-runner-1": {
                "id": "S6-qa-runner-1", "stage": "S6", "status": status, "scope": ["TC-1"]}}}), encoding="utf-8")
            try:
                got = execution_request.find_active_dispatch(Path(tmp), "QA-9", "S6-qa-runner-1", ["TC-1"])[2]["id"]
            except execution_request.MineRefusal:
                got = None
            eq(f"a {status} S6 dispatch is {'found' if found else 'refused'} by the tool the proof goes through", got, "S6-qa-runner-1" if found else None)


def hf2_11b_stale_runs_go_to_the_runner_and_the_proofs_follow() -> None:
    """K3 + invariant (i): stale RUNS -> the runner as today, launched with `complete=False` when stale live checks are owed, no
    probe before it (a probe is never next to code with no run on its current bytes); on its return (`auto_done`) the proofs, the
    reduction and the close at `s6.reprobed`; once per life of S6; the second life (no mark of ours) probes only when every run
    stands. MUTATIONS: `the probe before the runs` -> the first check; `complete=True with stale probes` -> the complete check;
    `the no-consumer window owes nothing` (driver_stage_s6.py `not owed` -> `owed`) -> the no-consumer check; `the consumer's record is
    not written` -> the re-entry key after the record."""
    import story_run
    from unittest import mock
    task = "QA-9"
    two = {"test_a": ("stale", "", D1_SAME), "test_b": ("result", "failed", "")}
    answer = {"test_a": row(("stale", WHY_RUN), stale_probe(REPLAY_A)), "test_b": row(("fresh", ""), stale_probe(REPLAY_B))}
    root, task_root, env = d2_seed(task, environment="Local", pending=False)
    pin = pin_project(root)
    try:
        d1_blocks(root, task_root)
        driver, launched, moves, probes, sites = reprobe_rig(root, env, task, dispatches=RUNNING_S6)
        with D1Evidence(d1_answer(two)), Staleness(answer):
            driver.stage_S6()
        eq("K3 stale runs: the runner is dispatched, whole scope, and NOT closing the stage; no probe, no close before it",
           ([(e["role"], e["scope"], e["complete"]) for e in launched], moves, sites), ([("qa-runner", ["TC-1", "TC-2"], AWAITS)], [], []))         # X7-6c: awaits the consumer (the proofs run at s6_reentry)
        check_in("K3 and it is told what stands and what to run, as today", f"Results that stand: test_b; run only: test_a ({D1_SAME}).",
                 d1_extras(launched))
        eq("K3 the close the runner no longer makes is OWED: the mark is set (before the runner; the dispatch id is filled after it)",
           driver.state.get("s6_probe_after"), "")

        # the runner came back, accepted in this life (the mark names it); the runs stand now; an OPEN dispatch is there
        both_open = dict(ACCEPTED_S6, **{"S6-probe-1": dict(RUNNING_S6["S6-qa-runner-1"], id="S6-probe-1")})
        fresh_runs = {"test_a": row(("fresh", ""), stale_probe(REPLAY_A)), "test_b": row(("unknown", "the run recorded no per-test identity"),
                                                                                            stale_probe(REPLAY_B))}
        # PC2-3: the FIRST re-entry runs with the consumer ON: the runner's entry carries its `role` (a scenario-local copy: `ACCEPTED_S6` is
        # shared with a reader that must not change colour), so `acceptance.stage_author_dispatch` names it as the author. The stage closes only
        # AFTER the consumer's record exists (driver_stage_s6.py X7-6 comment: the proofs run in `s6_reentry` "after the record, whose close
        # site finds it"): before the record the close is REFUSED naming it, nothing proved, nothing closed; after it, the close follows.
        authored = dict(both_open, **{k: dict(v, role="qa-runner") for k, v in ACCEPTED_S6.items()})
        driver, launched, moves, probes, sites = reprobe_rig(root, env, task, dispatches=authored, mark="S6-qa-runner-1")
        refused = ""
        with D1Evidence(d1_answer(two)), Staleness(fresh_runs):
            try:
                driver.stage_S6()
            except story_run.Refusal as refusal:
                refused = refusal.text
        eq("K3 re-entry before the consumer's record: refused, naming the record; no proof, no reduction, no close",
           (refused.startswith("S6 cannot be closed at s6_reentry: no accept record of qa-failure-analyst stands for S6-qa-runner-1"),
            moves, sites), (True, [], []))
        record_failure_analyst_accept(driver, "S6-qa-runner-1")      # the analyst's verdict now stands for the runner's dispatch
        driver, launched, moves, probes, sites = reprobe_rig(root, env, task, dispatches=authored, mark="S6-qa-runner-1")
        with D1Evidence(d1_answer(two)) as evidence, Staleness(fresh_runs):
            driver.stage_S6()
        eq("K3 re-entry: no evidence asked, no runner, the proofs, THEN the reduction, the receipt, the close",
           (evidence.asked, launched, [m[0] for m in moves]), ([], [], ["probe", "probe", "finalize", "code_only", "stage_done"]))
        eq("K3 under the open dispatch, one site", ([p[p.index("--dispatch") + 1] for p in probes], sites), (["S6-probe-1"] * 2, ["s6.reprobed"]))
        check_in("K3 the digest", "re-proved 2 probes after the tests changed (", close_digest(moves))
        check_not_in("K3 the close is the stage's own: the mark is gone", "s6_probe_after", json.dumps(driver.state))

        # The rigs below run with NO consumer for S6 (`acceptance.consumer_of` answers "", the same patch as the no-consumer check at the end):
        # they pin the re-probe logic of a later life, and `both_open` names no author; the consumer-on world is the two re-entry keys above.
        with mock.patch("acceptance.consumer_of", lambda stage, table=None: ""):
            # once per life: the same entry again finds nothing stale and owes nothing
            driver, launched, moves, probes, sites = reprobe_rig(root, env, task, dispatches=both_open)
            with D1Evidence(d1_answer(two)), Staleness({"test_a": row(), "test_b": row()}):
                driver.stage_S6()
            eq("K3 once per life of S6: nothing stale and no mark -> no probe, no close, nothing asked", (moves, sites, launched), ([], [], []))

            # the runner is back but a run STILL has no current bytes (it was not run): no probe next to it; the close is owed all the same
            driver, launched, moves, probes, sites = reprobe_rig(root, env, task, dispatches=both_open, mark="S6-qa-runner-1")
            with D1Evidence(d1_answer(two)), Staleness({"test_a": row(("stale", WHY_RUN), stale_probe(REPLAY_A)), "test_b": row()}):
                driver.stage_S6()
            check_in("invariant (i) a stale run at the return: the proof is skipped and says why",
                     "re-probe skipped: 1 tests have no run on their current bytes (test_a)", close_digest(moves))
            eq("invariant (i) ...no probe, and the stage is still closed by code (the runner was told not to)", (probes, sites), ([], ["s6.reprobed"]))

            # the second life of S6 (`invalidate` leaves earlier dispatches accepted): no mark of ours.
            # `unknown` runs do NOT license a probe there - nothing says the runner ran in this life
            driver, launched, moves, probes, sites = reprobe_rig(root, env, task, dispatches=both_open)
            with D1Evidence(d1_answer(two)), Staleness(fresh_runs):
                driver.stage_S6()
            eq("second life, a run `unknown` and no mark: nothing is probed or closed (invariant (i))", (moves, sites), ([], []))
            # ...while runs that are fresh everywhere do
            driver, launched, moves, probes, sites = reprobe_rig(root, env, task, dispatches=both_open)
            with D1Evidence(d1_answer(two)), Staleness({"test_a": row(("fresh", ""), stale_probe(REPLAY_A)), "test_b": row(("fresh", ""))}):
                driver.stage_S6()
            eq("second life, every run fresh: the stale live check is proved, then the close",
               ([m[0] for m in moves], sites), (["probe", "finalize", "code_only", "stage_done"], ["s6.reprobed"]))

        # a manual half: the runner never closes the stage, so no mark is owed and nothing here changes
        driver, launched, moves, probes, sites = reprobe_rig(root, env, task, dispatches={}, manual=("TC-9",))
        with D1Evidence(d1_answer(two)), Staleness(answer):
            driver.stage_S6()
        eq("a manual half pending: the runner goes as today (complete=False), no mark, no probe",
           ([e["complete"] for e in launched], "s6_probe_after" in driver.state, probes), ([False], False, []))

        # no consumer: a stage table where S6 has no `acceptance_by` (older pipelines). The runner window is the identity of today: it closes
        # S6 itself (`complete` True) unless live checks are owed, which only the driver's own close can prove (`complete` False, the
        # mark set; driver_stage_s6.py "the runner does NOT close the stage" / `consumer_awaits` "the identity with no consumer")
        completes = []
        for stale_rows in (answer, {"test_a": row(("stale", WHY_RUN)), "test_b": row()}):      # owed probes / none owed
            driver, launched, moves, probes, sites = reprobe_rig(root, env, task, dispatches=RUNNING_S6)
            with mock.patch("acceptance.consumer_of", lambda stage, table=None: ""), D1Evidence(d1_answer(two)), Staleness(stale_rows):
                driver.stage_S6()
            completes.append([e["complete"] for e in launched])
        eq("no consumer of S6: the runner window owing live checks is not complete; the control with none owed is", completes, [[False], [True]])
    finally:
        unpin_project(pin)
        harness.cleanup(root)


def hf2_11b_without_a_stand_nothing_is_run_or_proved() -> None:
    """K4 + P11: the carrier of "no stand" is the recorded WORD `stand not confirmed` (not the text of the answer): the stage goes
    on, no probe is launched, and the digest says `N tests changed after their run are left for a run elsewhere` (P19 step 5).
    MUTATION `a probe with the stand not confirmed` -> the first check."""
    task = "QA-9"
    two = {"test_a": ("result", "passed", ""), "test_b": ("result", "failed", "")}
    both = {"test_a": row(("fresh", ""), stale_probe(REPLAY_A)), "test_b": row(("fresh", ""), stale_probe(REPLAY_B))}
    word = [{"stage": "S6", "match": "stand not confirmed", "decision": "carry on, I will run them on staging", "at": "2026-10-26T10:00:00+00:00", "by": "human"}]
    root, task_root, env = d2_seed(task, environment="Local", pending=True)
    pin = pin_project(root)
    try:
        d1_blocks(root, task_root)
        d2_pipeline(task_root, stage_overrides=word)
        driver, launched, moves, probes, sites = reprobe_rig(root, env, task, dispatches=RUNNING_S6)
        eq("P11 the word is recorded: no stand, whatever the answer's own text said", driver.s6_no_stand(), True)
        with D1Evidence(d1_answer(two)), Staleness(both):
            driver.stage_S6()
        eq("K4 every run stands, the live checks are stale, no stand: NO probe (an open dispatch is there)", probes, [])
        check_in("K4 the digest says how many were left for a run elsewhere", "2 tests changed after their run are left for a run elsewhere",
                 close_digest(moves))
        eq("K4 the stage closes as the other code closes do (the reduction first)", ([m[0] for m in moves], sites),
           (["finalize", "code_only", "stage_done"], ["s6.reprobed"]))

        # stale runs with no stand: no new run either - the runner is dispatched as today (the answer is undecided: no stand observed),
        # told the count, and not owed the close
        driver, launched, moves, probes, sites = reprobe_rig(root, env, task, dispatches=RUNNING_S6)
        answer = {"test_a": row(("stale", WHY_RUN)), "test_b": row(("fresh", ""), stale_probe(REPLAY_B))}
        with D1Evidence(d1_answer({"test_a": ("unknown", "", "the stand's version was not observed")}, observed=False)), Staleness(answer):
            driver.stage_S6()
        check_in("K4 stale runs: the runner is told how many are left for a run elsewhere",
                 "2 tests changed after their run are left for a run elsewhere", d1_extras(launched))
        eq("K4 ...is not told to leave the stage open, and no probe was launched",
           ([e["complete"] for e in launched], probes, "s6_probe_after" in driver.state), ([AWAITS], [], False))         # X7-6c

        # P11 negative control: the same pipeline WITHOUT the word is not "no stand"; a confirmed stand never is
        d2_pipeline(task_root, stage_overrides=[])
        eq("P11 control: an unconfirmed stand and NO word is not `no stand` (the stand question comes first)", driver.s6_no_stand(), False)
        d2_pipeline(task_root, stage_overrides=word, environment="Local", environment_pending=False)
        eq("P11 control: a confirmed stand is never `no stand`, whatever words are on file", driver.s6_no_stand(), False)
        driver, launched, moves, probes, sites = reprobe_rig(root, env, task, dispatches=RUNNING_S6)
        with D1Evidence(d1_answer(two)), Staleness(both):
            driver.stage_S6()
        eq("P11 control: with the stand confirmed the same stale live checks ARE proved", len(probes), 2)
    finally:
        unpin_project(pin)
        harness.cleanup(root)


def hf2_11b_nothing_stale_is_byte_identical() -> None:
    """K5: the empty set changes nothing - today's calls, today's receipt text, today's digest, today's runner arguments (the older
    checks of `d1_s6_freshness` go through the real reader on a world whose run rows hold no per-test identity and stay green
    as they were). MUTATION `the empty set changes the digest` -> the digest check."""
    task = "QA-9"
    two = {"test_a": ("result", "passed", ""), "test_b": ("result", "failed", "")}
    root, task_root, env = d2_seed(task, environment="Local", pending=False)
    pin = pin_project(root)
    try:
        d1_blocks(root, task_root)
        driver, launched, moves, probes, sites = reprobe_rig(root, env, task, dispatches=RUNNING_S6)
        with D1Evidence(d1_answer(two)), Staleness({"test_a": row(), "test_b": row()}):
            driver.stage_S6()
        eq("K5 the moves are today's, with no probe", [m[0] for m in moves], ["finalize", "code_only", "stage_done"])
        eq("K5 the receipt's words and the site are today's",
           (moves[1][2], sites), ("every automated test has a result on its current bytes, on the same stand and version: "
                                  "1 passed, 1 failed - reused, nothing re-run", ["s6.results_stand"]))
        eq("K5 the digest is today's", close_digest(moves), "every automated result stands; nothing re-run")
        driver, launched, moves, probes, sites = reprobe_rig(root, env, task, dispatches={})
        with D1Evidence(d1_answer({"test_a": ("stale", "", D1_SAME), "test_b": ("result", "failed", "")})), Staleness({}):
            driver.stage_S6()
        eq("K5 stale runs, no live check: the runner as today (closing the stage), no mark",
           ([(e["scope"], e["complete"]) for e in launched], "s6_probe_after" in driver.state), ([(["TC-1", "TC-2"], AWAITS)], False))         # X7-6c
        check_in("K5 ...with today's line", f"Results that stand: test_b; run only: test_a ({D1_SAME}).", d1_extras(launched))
        check_not_in("K5 ...and no word of the new lines", "left for a run elsewhere", d1_extras(launched))
    finally:
        unpin_project(pin)
        harness.cleanup(root)


def hf2_11b_forty_tests_changed_by_one_fixture() -> None:
    """K6 + F-7 (a): one edit of a fixture makes 40 tests stale -> all 40 in `run only` (no sampling, no ceiling); and, when their
    runs stand, 40 proofs with the time in the digest."""
    task = "QA-9"
    ids = [f"t{n:02d}" for n in range(40)]
    results = {i: ("result", "passed", "") for i in ids + ["keep"]}
    root, task_root, env = d2_seed(task, environment="Local", pending=False)
    pin = pin_project(root)
    try:
        d1_blocks(root, task_root)
        driver, launched, moves, probes, sites = reprobe_rig(root, env, task, dispatches={})
        with D1Evidence(d1_answer(results)), Staleness({i: row(("stale", WHY_RUN)) for i in ids}):
            driver.stage_S6()
        extras = d1_extras(launched)
        eq("K6 the runner is dispatched, not the close", ([e["role"] for e in launched], moves), (["qa-runner"], []))
        check_in("K6 the result that stands is named", "Results that stand: keep; run only: t00 (", extras)
        eq("K6 all 40 are in `run only`", sum(f"{i} ({WHY_RUN})" in extras for i in ids), 40)
        driver, launched, moves, probes, sites = reprobe_rig(root, env, task, dispatches=RUNNING_S6)
        with D1Evidence(d1_answer(results)), Staleness({i: row(("fresh", ""), stale_probe(dict(REPLAY_A, instance=i))) for i in ids}):
            driver.stage_S6()
        eq("K6 40 proofs, none left out", sorted(p[p.index("--instance") + 1] for p in probes), ids)
        check("K6 the time is in the digest", re.search(r"re-proved 40 probes after the tests changed \(\d+ s\)", close_digest(moves)) is not None,
              close_digest(moves))
    finally:
        unpin_project(pin)
        harness.cleanup(root)


def main() -> None:
    run_scenarios([], [s5_critic_finish_passes_window, d1_s6_freshness, d1_texts,
                       hf2_11b_s6_freshness_reads_the_run_rows_shas,
                       hf2_11b_stale_live_checks_are_proved_again_before_the_reduction,
                       hf2_11b_the_tool_takes_only_a_running_dispatch,
                       hf2_11b_stale_runs_go_to_the_runner_and_the_proofs_follow,
                       hf2_11b_without_a_stand_nothing_is_run_or_proved,
                       hf2_11b_nothing_stale_is_byte_identical,
                       hf2_11b_forty_tests_changed_by_one_fixture,
                       s6_the_manual_block_waits_for_the_writer_lock,
                       t329_b270_g_the_manual_block_size_has_one_source,
                       t335_b_n4_a_missing_ticket_file_flag_is_the_question_with_the_path_in_the_answer_block,
                       t329_item6_a_ticket_file_of_the_person_is_a_question_not_a_factory_fault,
                       t329_b268_a_role_in_flight_is_written_while_it_runs_and_removed_when_it_returns,
                       t261_k2_the_blocks_of_five_and_the_refused_are_not_dispatched,
                       test_manual_block_dispatches_unprepared,
                       t261_resume_after_a_crash_between_blocks_and_the_recovery_rule,
                       t261_the_real_controller_refuses_a_completion_over_an_undispatched_case_and_takes_the_code_only_receipt,
                       t261_prepare_by_code_on_the_cmp2_shape_and_the_temporal_door,
                       t289_manual_block_goes_through_the_real_prepare_and_a_refusal_is_a_text,
                       t289_the_automation_half_with_a_manual_half_pending_finishes_not_complete,
                       t261_the_dry_gate_note_and_the_gate_b_text_slot,
                       t261_the_integration_lines_of_the_driver,
                       t292_k15_to_k18_the_question_comes_before_any_block,
                       t292_k19_the_answers_have_an_executor,
                       t292_k20_to_k24_the_pass_is_read_only_while_the_account_is_missing,
                       t292_the_real_policy_reader_and_the_question_titles,
                       t308_f6_the_reason_the_person_reads_is_the_true_one,
                       ep1_41f_cases_all_on_a_device_skip_only_the_default_account,
                       c16b_stand_login_is_priced_and_its_two_passes_are_two_records,
                       c16b_stand_confirm_is_priced_and_its_answers_have_executors,
                       c16b_gate_a_dry_is_a_priced_question_with_three_executors,
                       c16b_fix_round_one_words_door_one_token_table])
    harness.finish("test_story_run_s6")


if __name__ == "__main__":
    main()
