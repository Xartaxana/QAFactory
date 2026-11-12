#!/usr/bin/env python3
"""Where a review sends a window: the cause from the critic's typed findings, the budget from the ledger.

Before B-007 the driver sent every repair as `test_defect` and counted rounds in a local constant
that reset on every restart, although the critic had written the real cause of each finding in its
own form and the controller already kept the round ledger. `repair_route.route` reads the two
together; this test holds its rules (a)-(d) at their boundaries, and then the S5 loop that acts on
them: an environment-only review dispatches no author, a mechanical review dispatches one author
round and no critic after it, a test_defect review at the cap dispatches nothing, and a budget
nobody can read closes the window instead of guessing a number.
"""
import contextlib
import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import repair_route  # noqa: E402


def budget(counted=0, cap=2, mechanical=0, mechanical_cap=1, passes=True):
    """The controller's `repair_budget` since C1-5a: `passes` carries the waiver keys of the NEXT round (`passes=False` is an older controller)."""
    got = {"counted": counted, "by_cause": {}, "cap": cap, "mechanical": mechanical,
           "mechanical_cap": mechanical_cap, "stand_signal": None}
    if passes and isinstance(counted, int):     # no count (None) has no next pass: that budget is the `unknown` code
        got["passes"] = {"qa-automator": f"round pass {counted + 1} for qa-automator on S5:aaaaaaaaaaaa",
                         "qa-code-critic": f"round pass {counted + 1} for qa-code-critic on S5:bbbbbbbbbbbb"}
    return got


def finding(identifier, cause=None, blocking=None, problem="the test proves too little"):
    row = {"id": identifier, "file": "tests/test_a.py", "line": 3, "problem": problem}
    if cause is not None:
        row["cause"] = cause
    if blocking is not None:
        row["blocking"] = blocking
    return row


def form(*rows):
    return {"findings": list(rows)}


def route(verdict, the_form, the_budget):
    return repair_route.route(verdict, the_form, the_budget)


# --- rules (a)-(d), each at its boundary ---------------------------------------------------------

def rule_a_no_typed_findings():
    found = route("concerns", None, budget(counted=1))
    check_eq("(a) no form: a close over the code `untyped`, never a round", (found["action"], found["code"]), ("close", "untyped"))
    check_not_in("(a) and no cause is assumed", "assumed", found["note"] + found["reason"])
    check_eq("(a) at the cap the same", route("concerns", None, budget(counted=2))["code"], "untyped")
    check_eq("(a) beyond the cap it still closes untyped", (route("review", None, budget(counted=3))["action"],
                                                          route("review", None, budget(counted=3))["code"]), ("close", "untyped"))
    check_eq("(a) concerns and zero findings is untyped",
             (route("concerns", form(), budget())["action"], route("concerns", form(), budget())["code"]), ("close", "untyped"))
    check_eq("(a) so is `review`", route("review", form(), budget())["code"], "untyped")
    check_eq("(a) rows that are unfilled placeholders are no findings",
             route("concerns", form({"id": "<F-n>", "cause": "<one of vocabulary.repair_causes>"}), budget())["code"], "untyped")
    check_eq("(a) the budget is not read for an untyped close (unreadable budget: still untyped)",
             route("concerns", None, None)["code"], "untyped")
    check_eq("(a) a verdict that does not send the window back closes even with no form",
             route("approved", None, budget())["action"], "close")
    check_eq("(a) an empty form under an approving verdict closes", route("ok", form(), budget())["action"], "close")


def rule_b_blocking_test_defect():
    one = form(finding("F-1", "test_defect", True))
    check_eq("(b) concerns with a blocking test_defect and a round left: a test_defect round",
             route("concerns", one, budget(counted=1))["action"], "test_defect")
    check_eq("(b) `review` sends back too", route("review", one, budget(counted=0))["action"], "test_defect")
    at_cap = route("concerns", one, budget(counted=2))
    check_eq("(b) at the cap it closes", at_cap["action"], "close")
    check_in("(b) and says the cap was reached", "cap reached", at_cap["reason"])
    check_eq("(b) one below the cap is the last round", route("concerns", one, budget(counted=1, cap=2))["action"], "test_defect")
    check_eq("(b) with a cap of one, counted 0 is a round and counted 1 closes",
             (route("concerns", one, budget(counted=0, cap=1))["action"], route("concerns", one, budget(counted=1, cap=1))["action"]),
             ("test_defect", "close"))
    check_eq("(b) an approving verdict never sends a window back, whatever its findings say (FR-35)",
             route("approved", one, budget())["action"], "close")
    check_eq("(b) `ok` neither", route("ok", one, budget())["action"], "close")
    check_eq("(b) a finding written before `cause` and `blocking` existed is a blocking test_defect",
             route("concerns", form({"id": "F-1", "file": "a.py", "problem": "old form"}), budget())["action"], "test_defect")
    check_eq("(b) an unknown cause reads as test_defect",
             route("concerns", form(finding("F-1", "weird", True)), budget())["action"], "test_defect")
    check_eq("(b) blocking false is not blocking: nothing to send back",
             route("concerns", form(finding("F-1", "test_defect", False)), budget())["action"], "close")
    check_eq("(b) and the text `false` reads the same",
             route("concerns", form(finding("F-1", "test_defect", "false")), budget())["action"], "close")
    mixed = route("concerns", form(finding("F-1", "test_defect", True), finding("F-2", "mechanical", True)),
                  budget(counted=1))
    check_eq("(b) a blocking mechanical finding rides along with the test_defect round", mixed["action"], "test_defect")
    both = form(finding("F-1", "test_defect", True), finding("F-2", "mechanical", True))
    mixed_cap = route("concerns", both, budget(counted=2, mechanical=0, mechanical_cap=1))
    check_eq("(b)->(c) test_defect at its cap with a mechanical round still owed: the mechanical round, not a close (D2)",
             mixed_cap["action"], "mechanical")
    check_eq("(b)->(c) beyond the cap too", route("concerns", both, budget(counted=3))["action"], "mechanical")
    both_used = route("concerns", both, budget(counted=2, mechanical=1, mechanical_cap=1))
    check_eq("(b)->(c) both caps used up closes", both_used["action"], "close")
    check_in("and says both", "cap reached; mechanical cap reached", both_used["reason"])
    check_eq("(b) at the cap with only test_defect findings still closes",
             route("concerns", form(finding("F-1", "test_defect", True), finding("F-2", "mechanical", False)),
                   budget(counted=2))["action"], "close")
    check_eq("(b)->(c) with the budget unreadable it closes, never guesses",
             route("concerns", both, {"counted": 2, "cap": 2})["action"], "close")


def rule_c_mechanical():
    mech = form(finding("F-1", "mechanical", True))
    check_eq("(c) a blocking mechanical finding: the author's mechanical round",
             route("approved", mech, budget(mechanical=0, mechanical_cap=1))["action"], "mechanical")
    check_eq("(c) whatever the verdict - `concerns` too",
             route("concerns", mech, budget(mechanical=0, mechanical_cap=1))["action"], "mechanical")
    used = route("approved", mech, budget(mechanical=1, mechanical_cap=1))
    check_eq("(c) the mechanical cap used up closes", used["action"], "close")
    check_in("(c) and carries the debt in words", "mechanical cap reached", used["reason"])
    check_in("(c) named as a debt", "named debt", used["reason"])
    check_eq("(c) 0 of 2 is a round, 2 of 2 closes",
             (route("approved", mech, budget(mechanical=0, mechanical_cap=2))["action"],
              route("approved", mech, budget(mechanical=2, mechanical_cap=2))["action"]), ("mechanical", "close"))
    check_eq("(c) a mechanical round is not counted against the test_defect cap",
             route("approved", mech, budget(counted=2, cap=2, mechanical=0, mechanical_cap=1))["action"], "mechanical")
    check_eq("(c) a non-blocking mechanical finding asks nothing",
             route("approved", form(finding("F-1", "mechanical", False)), budget())["action"], "close")


def rule_d_and_not_rounds():
    env = form(finding("F-1", "environment", True))
    found = route("concerns", env, budget())
    check_eq("(d) concerns with only an environment finding closes", found["action"], "close")
    check_eq("(d) and names it as nobody's round", found["not_rounds"], [{"id": "F-1", "cause": "environment"}])
    several = route("concerns", form(finding("F-1", "environment", True), finding("F-2", "tooling", True),
                                     finding("F-3", "reviewer_error", True), finding("F-4", "test_defect", False)),
                    budget())
    check_eq("(d) environment, tooling and reviewer_error each go to not_rounds, in order",
             [(n["id"], n["cause"]) for n in several["not_rounds"]],
             [("F-1", "environment"), ("F-2", "tooling"), ("F-3", "reviewer_error")])
    check_eq("(d) and none of them is dispatched", several["action"], "close")
    check_eq("(d) a non-blocking environment finding is not listed",
             route("concerns", form(finding("F-1", "environment", False)), budget())["not_rounds"], [])
    beside = route("concerns", form(finding("F-1", "test_defect", True), finding("F-2", "tooling", True)), budget())
    check_eq("(d) a tooling finding beside a test_defect one is still named", beside["not_rounds"],
             [{"id": "F-2", "cause": "tooling"}])
    check_eq("(d) while the test_defect one is repaired", beside["action"], "test_defect")
    check_eq("(d) an approving review with nothing blocking closes", route("approved", form(), budget())["action"], "close")


def budget_unknown():
    one = form(finding("F-1", "test_defect", True))
    for label, bad in (("None", None), ("no cap", {"counted": 0}), ("text", {"counted": "0", "cap": "2"}), ("empty", {})):
        found = route("concerns", one, bad)
        check_eq(f"a budget nobody can read ({label}) closes the window", found["action"], "close")
        check_in(f"and says so ({label})", "repair budget unknown", found["reason"])
    check_eq("an unknown mechanical count closes too",
             route("approved", form(finding("F-1", "mechanical", True)), {"counted": 0, "cap": 2})["action"], "close")
    check_eq("but an approving review does not need a budget",
             route("approved", form(), None)["action"], "close")
    check_eq("and the environment finding is still named", route("concerns", form(finding("F-1", "environment", True)), None)["not_rounds"],
             [{"id": "F-1", "cause": "environment"}])


def the_form_as_the_critic_writes_it():
    text = ("schema_version: 1\ncontract: s5-critic-to-automator\nheader:\n  role: qa-code-critic\n  verdict: concerns\n"
            "findings:\n"
            "  - id: F-1\n    file: tests/test_a.py\n    line: 10\n    problem: sleep before the click\n"
            "    expected: a wait on the condition\n    fix: use wait_for\n    check: pytest\n"
            "    cause: mechanical\n    blocking: true\n"
            "  - id: F-2\n    file: conftest.py\n    line: 1\n    problem: the env file is not read\n"
            "    cause: environment\n    blocking: true\n"
            "  - id: <F-n>\n    file: <repo-relative path>\n    cause: <one of vocabulary.repair_causes>\n    blocking: <true|false>\n")
    root = Path(tempfile.mkdtemp(prefix="qa-repair-route-"))
    try:
        path = root / "form.yaml"
        path.write_text(text, encoding="utf-8")
        data = repair_route.read_form(path)
        rows = repair_route.findings(data)
        check_eq("the yaml the critic writes reads as typed findings, the placeholder row dropped",
                 [(f["id"], f["cause"], f["blocking"]) for f in rows], [("F-1", "mechanical", True), ("F-2", "environment", True)])
        check_eq("with the problem line, for the journal", rows[1]["problem"], "the env file is not read")
        found = route("concerns", data, budget())
        check_eq("mechanical wins over environment, which is nobody's round",
                 (found["action"], found["not_rounds"]), ("mechanical", [{"id": "F-2", "cause": "environment"}]))
        check_eq("a form that is not there reads as None", repair_route.read_form(root / "absent.yaml"), None)
        (root / "junk.yaml").write_text("\x00not: [a form", encoding="utf-8")
        check("a junk file reads as no form or an empty one, and never raises",
              isinstance(repair_route.read_form(root / "junk.yaml"), (dict, type(None))))
        (root / "text.yaml").write_text("just words\n", encoding="utf-8")
        check_eq("prose is no form", repair_route.read_form(root / "text.yaml") in (None, {}), True)
    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)


def findings_keep_the_critics_words():
    """C1-5c: `findings` keeps `file`, `line`, `expected` and `fix` beside `problem`, each whole up to 300 characters and cut at
    301 with an ellipsis (300 long, ellipsis included); an absent field is `""`, never a guess or `None`."""
    row = {"id": "F-1", "file": "tests/test_a.py", "line": 12, "problem": "p" * 300, "expected": "e" * 301,
           "fix": "  use\n  wait_for  ", "cause": "test_defect", "blocking": True}
    got = repair_route.findings({"findings": [row]})[0]
    check_eq("file, line, fix are kept (the line as text, whitespace folded)", (got["file"], got["line"], got["fix"]),
             ("tests/test_a.py", "12", "use wait_for"))
    check_eq("300 characters are shown whole", got["problem"], "p" * 300)
    check_eq("301 characters are cut to 300 with the ellipsis", got["expected"], "e" * 299 + "…")
    bare = repair_route.findings({"findings": [{"id": "F-2", "problem": "x"}]})[0]
    check_eq("an absent field reads as an empty string", (bare["file"], bare["line"], bare["expected"], bare["fix"]),
             ("", "", "", ""))
    check_eq("the route's own keys are unchanged", (got["id"], got["cause"], got["blocking"]), ("F-1", "test_defect", True))


# --- the S5 loop that acts on the route ------------------------------------------------------------

def digest_of(verdict):
    return f"qa-code-critic S5 TC-1 · {verdict}\nTC-1 · approved · reviewed\nwork/test-code/critic-findings.md"


def loop(reviews, budgets, windows=1):
    """Run stage_S5 in-process with the roles recorded, not run. `reviews` is a list of
    (verdict, form rows or None) - one per critic dispatch (the last repeats); `budgets` one per
    budget read (a dict, or an exception to raise). Returns (log, printed)."""
    from story_run_common import driver_for, seed
    task = "QA-9"
    root, task_root, env = seed(task)
    try:
        driver = driver_for(root, env, task, max_boundaries=1)
        driver.stage_scope = lambda stage, kind="": {
            "scope": ["TC-1"],
            "windows": [{"scope": ["TC-1"], "surface": "api", "accepted_by": {"qa-automator": 1}}] * windows}
        driver.stand_check = lambda stage, kind="": None
        log = {"critics": [], "complete": [], "reworks": [], "authors": [], "logged": [], "budget_reads": 0}

        def fake_role(stage, role, **kwargs):
            if role != "qa-code-critic":
                log["authors"].append((stage, role))
                return "", {}
            n = len(log["critics"])
            if n >= 6:
                # a loop that keeps dispatching critics is a failure to report, not a test to hang on
                raise RuntimeError("runaway: a seventh critic was dispatched")
            log["critic_extra"] = list(kwargs.get("extra") or [])
            dispatch = f"S5-qa-code-critic-{n + 1}"
            verdict, rows = reviews[min(n, len(reviews) - 1)]
            if rows is not None:
                target = task_root / "work" / "handoffs" / f"{dispatch}.yaml"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("findings:\n" + "".join(
                    f"  - id: {r['id']}\n    file: a.py\n    problem: {r['problem']}\n"
                    + (f"    cause: {r['cause']}\n" if "cause" in r else "")
                    + (f"    blocking: {str(r['blocking']).lower()}\n" if "blocking" in r else "") for r in rows),
                    encoding="utf-8")
            driver.last_dispatch = dispatch
            log["critics"].append(dispatch)
            digest = digest_of(verdict)
            complete = kwargs.get("complete")
            log["complete"].append(complete(digest) if callable(complete) else complete)
            return digest, {}

        def fake_rework(stage, role, cases, reason, **kwargs):
            log["reworks"].append(dict(kwargs, stage=stage, role=role, cases=cases, reason=reason))
            return "qa-automator S5 TC-1 · ok", {}

        def fake_budget(stage, role, scope):
            index = log["budget_reads"]
            log["budget_reads"] += 1
            value = budgets[min(index, len(budgets) - 1)]
            if isinstance(value, Exception):
                raise value
            return value

        def spy_py(script, *args, **kwargs):
            if script == "log_append.py":
                log["logged"].append(list(args))
            return 0, ""

        driver.run_role, driver.rework, driver.repair_budget, driver.py = fake_role, fake_rework, fake_budget, spy_py
        out = io.StringIO()
        log["runaway"] = False
        with contextlib.redirect_stdout(out):
            try:
                driver.stage_S5()
            except RuntimeError as exc:
                if "runaway" not in str(exc):
                    raise
                log["runaway"] = True
        return log, out.getvalue()
    finally:
        harness.cleanup(root)


def loop_environment_only():
    log, printed = loop([("concerns", [finding("F-1", "environment", True)])], [budget()])
    check_eq("an environment-only review dispatches no author", (log["reworks"], log["authors"]), ([], []))
    check_eq("one critic and no second review", log["critics"], ["S5-qa-code-critic-1"])
    # C1-5b1: a close over a seam reason (here `nobody`) is the person's to answer; the gate asks BEFORE the finish (the stage-S5
    # loop here runs on a stub `run_role`, which has no gate - test_story_run_repair_limit.py drives the real one), so the finish
    # of the last window is not a close until `debt` is answered
    check_eq("on the last window its finish does not close S5 over a rejection nobody repairs", log["complete"], [False])
    check_in("the finding is printed as nobody's round", "F-1 of S5-qa-code-critic-1 (environment) is nobody's round", printed)
    check_eq("and an environment finding files nothing with the factory", log["logged"], [])


def loop_tooling_is_filed():
    log, printed = loop([("concerns", [finding("F-7", "tooling", True, problem="probe_by_code refused the node id")])],
                        [budget()])
    check_eq("a tooling finding dispatches nobody", (log["reworks"], log["authors"]), ([], []))
    check_eq("it is filed as a factory defect with the critic's dispatch as --ref", len(log["logged"]), 1)
    args = log["logged"][0]
    check_eq("the event", args[args.index("--event") + 1], "defect_found")
    check_eq("the ref is the critic's dispatch (log_append requires it)", args[args.index("--ref") + 1], "S5-qa-code-critic-1")
    check_in("the owner and the finding", "owner: factory — tooling finding F-7: probe_by_code refused the node id",
             args[args.index("--notes") + 1])
    check_eq("by the driver", args[args.index("--by") + 1], "driver")


def loop_mechanical_last_window():
    log, printed = loop([("approved", [finding("F-1", "mechanical", True), finding("F-2", "mechanical", True)])], [budget()])
    check_eq("a mechanical review dispatches one author round", len(log["reworks"]), 1)
    work = log["reworks"][0]
    check_eq("as a mechanical round", work["cause"], "mechanical")
    check_eq("closing the stage on the last window", work["complete"], True)
    check_in("its reason names the reviewer's dispatch and the findings", "mechanical fixes of review S5-qa-code-critic-1: F-1, F-2",
             work["reason"])
    check_in("and the author is told the reviewer's dispatch id", "S5-qa-code-critic-1", " ".join(work["extra"]))
    check_eq("no critic after it", log["critics"], ["S5-qa-code-critic-1"])
    check_eq("and the loop does not run away", log["runaway"], False)
    check_eq("the critic's own finish did not close the stage: its author is owed a round", log["complete"], [False])


def loop_mechanical_not_last_window():
    log, _printed = loop([("approved", [finding("F-1", "mechanical", True)])], [budget()], windows=2)
    check_eq("on a window that is not the last, the mechanical round does not close the stage",
             (log["reworks"][0]["complete"], log["complete"]), (False, [False]))


def loop_test_defect_at_cap():
    log, printed = loop([("concerns", [finding("F-1", "test_defect", True)])], [budget(counted=2, cap=2)])
    check_eq("a test_defect review at the cap dispatches nothing", (log["reworks"], log["authors"]), ([], []))
    check_eq("its finish does not close the last window over the spent cap until the person answers", log["complete"], [False])
    check_in("and the close says why", "cap reached", printed)


def loop_test_defect_round_then_close():
    log, printed = loop([("concerns", [finding("F-1", "test_defect", True)]), ("approved", [])],
                        [budget(counted=1, cap=2), budget(counted=2, cap=2)])
    check_eq("a test_defect review under the cap is one repair round", len(log["reworks"]), 1)
    work = log["reworks"][0]
    check_eq("with the cause the critic wrote", work["cause"], "test_defect")
    check_in("the round text is counted+1 of the cap, from the ledger", "Repair round 2 of 2", " ".join(work["extra"]))
    check_in("naming the critic's form", "work/handoffs/S5-qa-code-critic-1.yaml", " ".join(work["extra"]))
    check_eq("the critic then reviews the new bytes", log["critics"], ["S5-qa-code-critic-1", "S5-qa-code-critic-2"])
    check_eq("the budget is read before every review", log["budget_reads"], 2)
    check_eq("the first review did not close S5, the second did", log["complete"], [False, True])


def loop_budget_unreadable():
    import story_run
    log, printed = loop([("concerns", [finding("F-1", "test_defect", True)])],
                        [story_run.Refusal("controller prepare (exit 1):\nstate is locked")])
    check_eq("an unreadable budget dispatches no round", (log["reworks"], log["authors"]), ([], []))
    check_in("it is printed with the error", "repair budget unknown: controller prepare (exit 1): state is locked", printed)
    check_eq("the window does not close on its critic's finish: an uncounted budget is the person's to answer", log["complete"], [False])
    check_eq("and the factory's defect is filed", len(log["logged"]), 1)
    args = log["logged"][0]
    check_in("owner factory", "owner: factory", args[args.index("--notes") + 1])
    check("with a --ref, which log_append requires", "--ref" in args and args[args.index("--ref") + 1])


def loop_no_progress_guard():
    """The S5 loop is bounded only by the ledger growing with every round (D4): a ledger that did not
    count the round just run must not send the same review back for ever."""
    log, printed = loop([("concerns", [finding("F-1", "test_defect", True)])], [budget(counted=0), budget(counted=0)])
    check_eq("the round that was not counted is dispatched once, and only once", len(log["reworks"]), 1)
    check_eq("the critic reviews the new bytes and the window then stops at the cap, for the person", (log["critics"], log["complete"]),
             (["S5-qa-code-critic-1", "S5-qa-code-critic-2"], [False, False]))
    check_in("the stop is printed, with the numbers", "the controller did not count the round just run (0 of 2)", printed)
    check_eq("and the loop did not run away", log["runaway"], False)
    grown = loop([("concerns", [finding("F-1", "test_defect", True)]), ("approved", [])],
                 [budget(counted=0), budget(counted=1)])[1]
    check_not_in("a ledger that grew triggers no stop", "did not count", grown)


def first(log):
    """The first rework a fake recorded - or an empty one, so that a missing round is a failed check, not a crash."""
    return (log["reworks"] or [{"extra": [], "cause": None, "cases": None}])[0]


class Stop(RuntimeError):
    """Raised by a fake that has been called more often than any honest loop would."""


def s7_run(rows, budgets, digest="qa-automator S5 TC-1 · ok\nTC-1 · still_red · not fixed\nwork/x.md"):
    """Run s7_repairs in-process: `rows` are triage rows, `budgets` one per budget read (dict or exception)."""
    import json
    from story_run_common import driver_for, seed
    task = "QA-9"
    root, task_root, env = seed(task)
    try:
        driver = driver_for(root, env, task, max_boundaries=1)
        (task_root / "work" / "triage.json").write_text(json.dumps({"triage": rows}), encoding="utf-8")
        log = {"reworks": [], "reads": 0, "finalized": 0, "runaway": False, "person": None, "offer": None, "defects": 0}

        def fake_budget(stage, role, scope):
            index = log["reads"]
            log["reads"] += 1
            value = budgets[min(index, len(budgets) - 1)]
            if isinstance(value, Exception):
                raise value
            return value

        def fake_rework(stage, role, cases, reason, **kwargs):
            if len(log["reworks"]) >= 6:
                raise Stop("runaway: a seventh repair round was dispatched")
            log["reworks"].append(dict(kwargs, stage=stage, role=role, cases=cases, reason=reason))
            return digest, {}

        def spy_py(script, *args, **kwargs):
            if script == "finalize_task.py":
                log["finalized"] += 1
            if script == "log_append.py" and "defect_found" in args:
                log["defects"] += 1
            return 0, ""

        import story_run
        driver.repair_budget, driver.rework, driver.py = fake_budget, fake_rework, spy_py
        # the analyst's accepted dispatch is the life; the ledger's refs are test_ledger.py's and the live pin's (test_story_run_s7.py)
        driver.s7_life, driver.s7_fresh = (lambda: "S7-qa-failure-analyst-1"), (lambda: True)
        driver.s7_refs = lambda row: ([str(row.get("test") or row.get("case"))], True)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                driver.s7_repairs()
            except Stop:
                log["runaway"] = True
            except story_run.Person as person:      # the seam's question: at the cap, or with no count (t-698 §4.4, FX-6)
                log["person"], log["offer"] = person, (driver.state.get("repair_ask") or {}).get("offer")
            except story_run.Refusal as refusal:
                log["person"], log["offer"] = refusal, None
        return log, out.getvalue()
    finally:
        harness.cleanup(root)


S7_ROW = {"case": "TC-1", "test": "tests/test_a.py::test_one", "verdict": "TEST_BUG"}


def asked(log):
    """(kind, stage, offer) of the question the loop raised, or None."""
    person = log["person"]
    return None if person is None else (getattr(person, "kind", type(person).__name__), getattr(person, "stage", ""), log["offer"])


def s7_stops_at_the_cap():
    log, printed = s7_run([S7_ROW], [budget(counted=1), budget(counted=2)])
    check_eq("S7: one round is left at 1 of 2, and only one is dispatched", len(log["reworks"]), 1)
    check_in("S7: its text is counted+1 of the cap, from the ledger", "Round: 2 of 2", " ".join(first(log)["extra"]))
    check_eq("S7: with the cause the triage verdict typed", (first(log)["cause"], first(log)["cases"]),
             ("test_defect", ["TC-1"]))
    check_eq("S7: at the cap the seam asks: round / debt / stop, for S7", asked(log), ("repair_limit", "S7", ["round", "debt", "stop"]))
    check_not_in("S7: the old silent stop is gone", "the repair cap of its window is spent", printed)
    check_eq("S7: the budget is re-read on every pass", log["reads"], 2)
    check_eq("S7: no finalize in a process whose question is open", log["finalized"], 0)
    for label, counted in (("AT", 2), ("BEYOND", 3)):
        at = s7_run([S7_ROW], [budget(counted=counted)])
        check_eq(f"S7: {label} the cap nothing is dispatched, the seam asks", (at[0]["reworks"], asked(at[0])),
                 ([], ("repair_limit", "S7", ["round", "debt", "stop"])))
    fresh = s7_run([S7_ROW], [budget(counted=0), budget(counted=1), budget(counted=2)])
    check_eq("S7: from 0 of 2 exactly two rounds run, then the seam asks", (len(fresh[0]["reworks"]), asked(fresh[0])),
             (2, ("repair_limit", "S7", ["round", "debt", "stop"])))
    old = s7_run([S7_ROW], [budget(counted=2, passes=False)])
    check_eq("S7 negative: at the cap a controller that reports no passes is refused by name, no round", (old[0]["reworks"], asked(old[0])[0]),
             ([], "refusal"))
    check_in("S7 negative: the refusal names the missing key", "repair_budget.passes", old[0]["person"].details)


def s7_no_progress_guard():
    log, printed = s7_run([S7_ROW], [budget(counted=0)])
    check_eq("S7: a ledger that never counts the round gets one round, not six", (len(log["reworks"]), log["runaway"]), (1, False))
    check_in("S7: and the stop is printed", "the controller did not count the round just run (0 of 2)", printed)


def s7_green_and_unreadable():
    green = "qa-automator S5 TC-1 · ok\nTC-1 · green · fixed\nwork/x.md"
    log, _printed = s7_run([S7_ROW], [budget(counted=0), budget(counted=1)], digest=green)
    check_eq("S7: a green repair ends the test's loop", len(log["reworks"]), 1)
    import story_run
    log, printed = s7_run([S7_ROW], [story_run.Refusal("controller prepare (exit 1):\nno state")])
    check_eq("S7: an unreadable budget dispatches nothing", log["reworks"], [])
    check_in("S7: and says so", "repair budget unknown", printed)
    check_eq("S7: one defect is filed, and the seam asks debt / stop with no `round` (no round is started blind)",
             (log["defects"], asked(log), log["finalized"]), (1, ("repair_limit", "S7", ["debt", "stop"]), 0))


def s4_run(verdict, the_budget):
    """Run stage_S4 in-process with the roles recorded: designer, critic, rework."""
    from story_run_common import driver_for, seed
    task = "QA-9"
    root, task_root, env = seed(task)
    try:
        driver = driver_for(root, env, task, max_boundaries=1)
        findings = task_root / "work" / "test-cases" / "a" / "critic-findings.md"
        findings.parent.mkdir(parents=True, exist_ok=True)
        findings.write_text("the cases say too little\n", encoding="utf-8")
        driver.pin_cases, driver.revise_plan = (lambda: None), (lambda: None)
        driver.critic_scope = lambda: ["TC-1", "TC-2"]
        driver.role_lines = lambda stage, role: []
        log = {"roles": [], "complete": [], "reworks": [], "asked": [], "py": []}

        def fake_role(stage, role, **kwargs):
            log["roles"].append(role)
            if role != "qa-case-critic":
                return "", {}
            digest = f"qa-case-critic S4 TC-1 · {verdict}\nTC-1 · ok · reviewed\nwork/x.md"
            complete = kwargs.get("complete")
            driver.last_dispatch = "S4-critic-1"        # `run_role` sets it just before `finish`; the finish reads the critic's form by it (t-1815 F1)
            log["complete"].append(complete(digest) if callable(complete) else complete)
            return digest, {}

        def fake_rework(stage, role, cases, reason, **kwargs):
            log["reworks"].append(dict(kwargs, stage=stage, role=role, cases=cases, reason=reason))
            return "", {}

        def fake_budget(stage, role, scope):
            log["asked"].append((stage, role, list(scope)))
            if isinstance(the_budget, Exception):
                raise the_budget
            return the_budget

        driver.run_role, driver.rework, driver.repair_budget = fake_role, fake_rework, fake_budget
        driver.py = lambda script, *args, **kwargs: (log["py"].append(script) or (0, ""))
        # X2-7: the critic's finish writes the stage acceptance record first (here: a known word, a no-op writer) and a critic that sends
        # cases back on the LAST round goes to the conductor seam instead of a silent close (the seam is recorded, answers "no move needed")
        driver.stage_verdict_known = lambda form: True
        driver.stage_acceptance_write = lambda stage, dispatch: None
        driver.pipeline = lambda: {}
        log["seam"] = []
        driver.stage_review_exhausted = lambda stage, *a, **k: log["seam"].append(stage)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            driver.stage_S4()
        return log, out.getvalue()
    finally:
        harness.cleanup(root)


def s4_last_round_and_text_from_the_budget():
    log, _printed = s4_run("concerns", budget(counted=1, cap=2))
    # C2-4 (t-908 §3.4, §L F-7 (b), §L-2 F-3): with a round left AND a findings file (this rig writes one) the critic's finish is no
    # longer the silent `False` (the controller refuses it, so the critic was resumed for a record the driver owns): it is an
    # `OpenWork` with the ONE word `cases_in_repair`, and the reason names the findings file the round reads (§3.4 "its findings:
    # {path}"), is not empty (§5 edge 15) and is at most 300 characters (§3.4). The wording of the reason is not pinned.
    done = log["complete"]
    check_eq("S4: a round is left at 1 of 2: one rework, no closing - the finish keeps S4 open by an OpenWork with the word cases_in_repair",
             (len(log["reworks"]), [(type(c).__name__, getattr(c, "unresolved", None)) for c in done]),
             (1, [("OpenWork", "cases_in_repair")]))
    reason = getattr(done[0], "reason", "") if done else ""
    check("S4: a round is left at 1 of 2: the OpenWork reason names the findings file, is not empty and is at most 300 characters",
          bool(reason.strip()) and len(reason) <= 300 and "work/test-cases/a/critic-findings.md" in reason, repr(reason))
    check_in("S4: the round text is counted+1 of the cap, from the ledger", "Repair round 2 of 2", " ".join(first(log)["extra"]))
    check_eq("S4: the cause stays test_defect, over the critic's scope", (first(log)["cause"], first(log)["cases"]),
             ("test_defect", ["TC-1", "TC-2"]))
    check_eq("S4: the budget is asked for the designer's window", log["asked"], [("S4", "qa-case-designer", ["TC-1", "TC-2"])])
    log, _printed = s4_run("concerns", budget(counted=0, cap=2))
    check_in("S4: the first round reads 1 of 2", "Repair round 1 of 2", " ".join(first(log)["extra"]))
    log, _printed = s4_run("concerns", budget(counted=2, cap=2))
    check_eq("S4: at the cap no rework is dispatched (AT the boundary)", log["reworks"], [])
    check_eq("S4: and the critic's finish closes the stage by the stage's own rule", log["complete"], [None])
    check_in("S4: the stage is closed by the case appendix", "render_case_appendix.py", " ".join(log["py"]))
    log, _printed = s4_run("review", budget(counted=3, cap=2))
    check_eq("S4: beyond the cap it closes too", (log["reworks"], log["complete"]), ([], [None]))
    log, _printed = s4_run("approved", budget(counted=0, cap=2))
    check_eq("S4: an approving verdict is never sent back", (log["reworks"], log["complete"]), ([], [None]))
    import story_run
    log, printed = s4_run("concerns", story_run.Refusal("controller prepare (exit 1):\nno state"))
    check_eq("S4: an unreadable budget dispatches no round and closes", (log["reworks"], log["complete"]), ([], [None]))
    check_in("S4: and says so", "repair budget unknown", printed)


def loop_critic_brief():
    log, _printed = loop([("approved", [])], [budget()])
    brief = " ".join(log["critic_extra"])
    # the load-bearing phrases, not the whole string: the wording around them is the driver's to tune (t-016, t-071)
    check_in("the critic is told to probe by code first (t-016)", "Static review first, then probe_by_code.py once per instance, every check of the test", brief)
    check_in("and red_sandbox only on a doubt (t-016)", "red_sandbox.py --probe (only when you doubt the check looks at the product", brief)
    check_in("and a probe of unchanged bytes is answered already_probed (t-071)", "already_probed", brief)
    check_in("and the findings file, the receipt ref and the cause are still asked for", "review_receipt_ref", brief)
    check_in("and each finding carries its cause", "`cause:` on each finding", brief)
    check_not_in("and no longer named as the default probe", "one isolated batch red probe", " ".join(log["critic_extra"]))


def loop_approved_closes():
    log, _printed = loop([("approved", [])], [budget()])
    check_eq("an approved review dispatches nothing and closes", (log["reworks"], log["complete"]), ([], [True]))
    check_not_in("and files nothing", "defect_found", " ".join(" ".join(a) for a in log["logged"]))


def rework_contract():
    """`rework`: the cause has no default, a round that is not about the test says why, and `complete`
    reaches the author's dispatch."""
    from story_run_common import driver_for, seed
    root, _task_root, env = seed("QA-9")
    try:
        driver = driver_for(root, env, "QA-9", max_boundaries=1)
        driver.controller = lambda operation, *args, input_data=None: {"request": {"id": "S5-qa-automator-2", "scope": ["TC-1"]},
                                                                      "args": list(args)}
        seen = []
        driver.run_role = lambda stage, role, **kwargs: seen.append(kwargs) or ("", {})
        try:
            driver.rework("S5", "qa-automator", ["TC-1"], "why")
            check("rework with no cause is refused", False)
        except TypeError as exc:
            check_in("rework has no default cause", "cause", str(exc))
        try:
            driver.rework("S5", "qa-automator", ["TC-1"], "  ", cause="mechanical")
            check("a mechanical round with no reason is refused", False)
        except ValueError as exc:
            check_in("a round that is not about the test needs a reason, and says so", "mechanical round needs a non-empty reason", str(exc))
        check_eq("and nothing was dispatched by either refusal", seen, [])
        driver.rework("S5", "qa-automator", ["TC-1"], "mechanical fixes of review S5-qa-code-critic-1: F-1",
                      cause="mechanical", complete=True)
        check_eq("complete=True reaches the author's dispatch", seen[-1]["complete"], True)
        driver.rework("S5", "qa-automator", ["TC-1"], "critic round", cause="test_defect")
        check_eq("complete is False by default (the reviewer closes the stage, not the repair)", seen[-1]["complete"], False)
        driver.rework("S5", "qa-automator", ["TC-1"], "", cause="test_defect")
        check_eq("a test_defect round keeps the controller's own reason rule (it refuses an empty one)", len(seen), 3)
        check_eq("the rework registered is the one that runs", seen[-1]["rework"]["id"], "S5-qa-automator-2")
    finally:
        harness.cleanup(root)


def repair_budget_from_the_controller():
    """`repair_budget` is the controller's own answer for the window - counted, cap, mechanical - read
    through `prepare`; the driver keeps no number."""
    import story_run
    from story_run_common import driver_for, seed
    root, _task_root, env = seed("QA-9")
    try:
        driver = driver_for(root, env, "QA-9", max_boundaries=1)
        for stage, role in (("S5", "qa-automator"), ("S4", "qa-case-designer")):
            got = driver.repair_budget(stage, role, ["TC-1"])
            check_eq(f"{stage} {role}: the controller's budget keys", sorted(got),
                     ["by_cause", "cap", "counted", "mechanical", "mechanical_cap", "passes", "stand_signal"])
            check(f"{stage} {role}: counted and cap are numbers, and a fresh window has spent nothing",
                  isinstance(got["cap"], int) and got["cap"] > 0 and got["counted"] == 0, str(got))
        check_eq("a role that carries no repair loop has no budget: refused, not guessed",
                 type(_raises(lambda: driver.repair_budget("S1", "qa-scout", []))).__name__, "Refusal")
        out = io.StringIO()
        driver.repair_budget = lambda stage, role, scope: (_ for _ in ()).throw(story_run.Refusal("controller prepare (exit 1):\nno state"))
        with contextlib.redirect_stdout(out):
            check_eq("budget_or_none turns a refusal into None", driver.budget_or_none("S5", "qa-automator", ["TC-1"], ref="S5-x-1"), None)
        check_in("after printing why", "repair budget unknown: controller prepare (exit 1): no state", out.getvalue())
    finally:
        harness.cleanup(root)


def _raises(call):
    try:
        call()
    except Exception as exc:
        return exc
    return None


def seam_codes():
    """C1-5b1 (t-698 §2, A8): the R-code a close carries - the seam reason the driver asks about; "" for every other route."""
    cap = lambda found: found["code"]
    check_eq("R cap: a test_defect finding at the cap", cap(route("concerns", form(finding("F-1", "test_defect", True)), budget(counted=2))), "cap")
    check_eq("R untyped: no form under a sending-back verdict (no cause is assumed)", cap(route("concerns", None, budget(counted=2))), "untyped")
    check_eq("R unknown: no count in the budget", cap(route("concerns", form(finding("F-1", "test_defect", True)), budget(counted=None))), "unknown")
    check_eq("R unknown: no cap in the budget (a count alone)", cap(route("concerns", form(finding("F-1", "test_defect", True)), {"counted": 2})), "unknown")
    check_eq("R untyped: and with a budget that cannot be read", cap(route("review", None, {"cap": 2})), "untyped")
    check_eq("R unknown: the mechanical count cannot be read", cap(route("approved", form(finding("F-1", "mechanical", True)), {"counted": 0, "cap": 2})), "unknown")
    check_eq("R mech_cap: the mechanical cap is spent", cap(route("concerns", form(finding("F-1", "mechanical", True)), budget(mechanical=1))), "mech_cap")
    check_eq("R cap wins over mech_cap when both caps are spent",
             cap(route("concerns", form(finding("F-1", "test_defect", True), finding("F-2", "mechanical", True)), budget(counted=2, mechanical=1))), "cap")
    check_eq("R nobody: an environment finding under a sending-back verdict", cap(route("concerns", form(finding("F-1", "environment", True)), budget())), "nobody")
    check_eq("R sent_back: a sending-back verdict with only non-blocking findings",
             cap(route("concerns", form(finding("F-1", "test_defect", False)), budget())), "sent_back")
    check_eq("R sent_back: blocking written `False` in mixed case reads as not blocking, still asked",
             cap(route("review", form(finding("F-1", "test_defect", "False")), budget())), "sent_back")
    check_eq("no code: a test_defect round under the cap", cap(route("concerns", form(finding("F-1", "test_defect", True)), budget())), "")
    check_eq("no code: an approving verdict closes without asking", cap(route("approved", form(finding("F-1", "test_defect", True)), budget(counted=2))), "")
    check_eq("no code: a mechanical round under its cap", cap(route("approved", form(finding("F-1", "mechanical", True)), budget())), "")
    check_eq("an unknown cause reads as test_defect and asks at the cap",
             cap(route("concerns", form(finding("F-1", "no_such_cause", True)), budget(counted=2))), "cap")


# --- F4 (t-1936 N2): a send-back with no typed finding is never a round on an assumed cause ------------------

UNTYPED_DIGEST = "qa-code-critic S5 TC-1 · concerns\nTC-1 · rejected\nwork/x.md"


def test_untyped_send_back_closes_untyped_not_test_defect():
    for verdict in ("concerns", "review", " concerns  "):
        for the_form in (form(), {}, {"findings": None}, form({"id": "<F-n>", "cause": "<one of vocabulary.repair_causes>"})):
            found = route(verdict, the_form, budget())
            assert (found["action"], found["code"]) == ("close", "untyped"), (verdict, the_form, found)
            assert "assumed" not in found["note"] + found["reason"]
            assert found["action"] != "test_defect"


def test_form_none_send_back_untyped():
    found = route("concerns", None, budget(counted=0))
    assert (found["action"], found["code"], found["reason"]) == ("close", "untyped", "no typed findings")
    assert route("review", None, None)["code"] == "untyped"      # the budget is not read for this close


def test_ok_without_findings_closes_plain():
    for the_form in (None, form()):
        found = route("ok", the_form, budget())
        assert (found["action"], found["code"]) == ("close", "")
    assert route("approved", None, budget())["code"] == ""


def test_send_back_words_equal_rows_owed_words():
    import handoff
    block = handoff.template("s5-critic-to-automator").data.get("rows_owed_when")
    assert sorted(block) == sorted(repair_route.SEND_BACK)
    for word in repair_route.SEND_BACK:
        assert handoff.rows_owed("s5-critic-to-automator", word) == {"findings"}
    assert handoff.rows_owed("s5-critic-to-automator", "ok") == set()


def _driver(root_name="QA-9"):
    from story_run_common import driver_for, seed
    root, task_root, env = seed(root_name)
    return root, driver_for(root, env, root_name, max_boundaries=1)


def test_untyped_asks_review_debt_stop():
    root, driver = _driver()
    try:
        found = route("concerns", form(), budget())
        ask = driver.repair_limit_facts("S5-qa-code-critic-1", ["TC-1"], found, form(), budget())
        assert (ask["key"], ask["offer"], ask["cause"]) == ("s5.nobody_review", ["review", "debt", "stop"], "reviewer_error")
        assert "wrote no finding the test writer can act on" in ask["lead"]
        assert ask["code"] == "untyped"      # the ledger holds the word (FU2)
    finally:
        harness.cleanup(root)


def test_untyped_skips_older_controller_refusal():
    root, driver = _driver()
    try:
        raised = []
        driver.route_of = lambda digest, bud, dispatch="": (route("concerns", form(), bud), form())
        driver.s5_note_findings = lambda *a, **k: None
        driver.repair_answer = lambda *a, **k: {}

        def older(*a, **k):
            raised.append("older")
            raise RuntimeError("the refusal always raises (the seam)")
        driver.repair_older_controller = older
        driver.repair_limit_raise = lambda ask: raised.append(ask["key"])
        old = budget(counted=0, passes=False)
        driver.repair_limit_gate("S5", "qa-code-critic", "S5-qa-code-critic-1", UNTYPED_DIGEST, ["TC-1"], budget=old)
        assert raised == ["s5.nobody_review"], raised
        raised.clear()      # the older-controller refusal still stands for a cap close
        driver.route_of = lambda digest, bud, dispatch="": (route("concerns", form(finding("F-1", "test_defect", True)), budget(counted=2)), None)
        try:
            driver.repair_limit_gate("S5", "qa-code-critic", "S5-qa-code-critic-1", UNTYPED_DIGEST, ["TC-1"], budget=old)
        except RuntimeError:
            pass
        assert raised == ["older"], raised
    finally:
        harness.cleanup(root)


def test_s7_untyped_is_no_progress():
    root, driver = _driver()
    try:
        driver.budget_or_none = lambda *a, **k: budget(counted=0)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            end = driver.s7_reorder_outcome(UNTYPED_DIGEST, "tests/test_a.py::t", "TC-1", what="repair review")
        assert end == "no_progress"
        assert out.getvalue() == "S7: tests/test_a.py::t - the critic sent the repair back without a typed finding; the round is stopped\n"
    finally:
        harness.cleanup(root)


def main():
    test_untyped_send_back_closes_untyped_not_test_defect()
    test_form_none_send_back_untyped()
    test_ok_without_findings_closes_plain()
    test_send_back_words_equal_rows_owed_words()
    test_untyped_asks_review_debt_stop()
    test_untyped_skips_older_controller_refusal()
    test_s7_untyped_is_no_progress()
    seam_codes()
    rework_contract()
    repair_budget_from_the_controller()
    rule_a_no_typed_findings()
    rule_b_blocking_test_defect()
    rule_c_mechanical()
    rule_d_and_not_rounds()
    budget_unknown()
    the_form_as_the_critic_writes_it()
    findings_keep_the_critics_words()
    loop_environment_only()
    loop_tooling_is_filed()
    loop_mechanical_last_window()
    loop_mechanical_not_last_window()
    loop_test_defect_at_cap()
    loop_test_defect_round_then_close()
    loop_budget_unreadable()
    loop_no_progress_guard()
    s7_stops_at_the_cap()
    s7_no_progress_guard()
    s7_green_and_unreadable()
    s4_last_round_and_text_from_the_budget()
    loop_critic_brief()
    loop_approved_closes()
    harness.finish("test_repair_route")


if __name__ == "__main__":
    main()
