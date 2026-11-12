#!/usr/bin/env python3
"""The stage critic's route, S2-S4 (spec t-1765 X2-7, K14): after the author's stop the driver dispatches `qa-case-critic`, writes the
acceptance record BEFORE the critic's finish, sends a rejected stage back to the author by the ONE repair counter, and hands an
exhausted review to the conductor seam (F-X2-7). What each check proves and the ONE mutation that kills it (builder-rules 7a):

  R1  accept: the record is written inside `complete(digest)` BEFORE the finish, and the stage closes (None)
      mutation: write the record after `story_step finish` (the order check) -> killed by R1
  R2  reject with a round left: `OpenWork("stage_in_repair")`, then one author round in a fresh context with the critic's form as the extra
      mutation: `last_round` always True -> killed by R2
  R3  reject on the last round (counted == cap): the seam is asked, no author round; a `driver` accept closes (None); no move -> Person
      mutation: return None on the last round without the seam -> killed by R3
  R4  the budget cannot be read (None): the critic still runs once, no author round, and a reject goes to the seam
      mutation: skip the critic when the budget is None -> killed by R4
  R5  a verdict word outside the table: no writer call, the seam is asked
      mutation: map an unknown word to accept -> killed by R5
  R6  `stage_repair_owed` and the restart rules: an owed round starts without a new critic; an accepted author is not dispatched again
  R7  S3 is judged only after the exit window; the constants F-X2-4; S4's rounds-left behaviour is unchanged
"""
import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, finish  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))

CRITIC, AUTHORS = "qa-case-critic", {"S2": "qa-requirements-tester", "S3": "qa-test-strategist", "S4": "qa-case-designer"}


def rig(stage, verdict, counted=0, cap=2, budget="ok", seam=None, recover=""):
    """Run `stage_critic_route` (S2, S3) in-process with every role and script faked; the log is the order of events.
    `recover` ("fresh" | "stale" | "noid"): instead of the route, finish a SAVED critic result the way a restarted process does -
    `completion_for(stage, critic, record)` with `last_dispatch` unset ("fresh"), another role's ("stale"), and a record with no id."""
    import acceptance
    import handoff
    import story_run
    from story_run_common import driver_for, seed
    root, task_root, env = seed("QA-9")
    try:
        driver = driver_for(root, env, "QA-9", max_boundaries=1)
        log = {"events": [], "reworks": [], "seam": [], "defects": 0, "result": "unset", "py": []}
        author = AUTHORS[stage]
        dispatches = {f"{stage}-{author}-1": {"id": f"{stage}-{author}-1", "stage": stage, "role": author, "status": "accepted"}}
        driver.controller_state = lambda: {"dispatches": dict(dispatches)}
        driver.stage_raise_questions = lambda s, a: log["events"].append("questions") or []

        def fake_budget(s, r, scope):
            if budget == "none":
                raise story_run.Refusal("controller prepare (exit 1):\nno state")
            return {"counted": counted, "cap": cap}

        def fake_role(s, role, **kwargs):
            log["events"].append(f"dispatch {role}")
            dispatch = f"{s}-{role}-1"
            driver.last_dispatch = dispatch
            dispatches[dispatch] = {"id": dispatch, "stage": s, "role": role, "status": "running"}
            form = task_root / "work" / "handoffs" / f"{dispatch}.yaml"
            form.parent.mkdir(parents=True, exist_ok=True)
            form.write_text(f"header:\n  role: {role}\n  stage: {s}\n  verdict: {verdict}\nstage_acceptance:\n  failure_class: spec\n"
                            f"  quote: \"work/x.md#R-1: the register omits the limit\"\n  witness_paths: []\n", encoding="utf-8")
            complete = kwargs.get("complete")
            log["result"] = complete("digest") if callable(complete) else complete
            dispatches[dispatch]["status"] = "accepted"
            log["events"].append("finish")
            return "digest", {}

        def fake_py(script, *args, **kwargs):
            log["py"].append(script)
            if script == "question_register.py":
                log["events"].append("raise")
                log.setdefault("raises", []).append((list(args), kwargs.get("check")))
            if script == "stage_done.py" and "--acceptance" in args:
                log["events"].append("record")
                log.setdefault("acceptance_forms", []).append(args[args.index("--acceptance") + 1])
                dispatch = Path(args[args.index("--acceptance") + 1]).stem
                data = handoff.parse((task_root / "work" / "handoffs" / f"{dispatch}.yaml").read_text(encoding="utf-8")).data
                record, problems = acceptance.stage_acceptance_from_form(
                    data, stage=stage, role=author, acceptor=CRITIC, reviewed_dispatch=f"{stage}-{author}-1", witness_form="w", at="t")
                if problems:
                    return 2, "; ".join(problems)
                path = task_root / "pipeline.json"
                pipeline = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
                pipeline.setdefault("acceptance", {}).setdefault(stage, []).append(record)
                path.write_text(json.dumps(pipeline), encoding="utf-8")
            if script == "log_append.py" and "defect_found" in args:
                log["defects"] += 1
            return 0, ""

        def fake_no_move(state, moves=None):
            if state.get("call") is False:       # the seam's own floor (`call=False`): the priced question of the person, no second paid call
                raise Asked(state.get("text", ""))
            log["events"].append("seam")
            log["seam"].append(state)
            if seam == "driver_accept":
                path = task_root / "pipeline.json"
                pipeline = json.loads(path.read_text(encoding="utf-8"))
                pipeline["acceptance"][stage].append({"stage": stage, "role": author, "acceptor": "driver", "reviewed_dispatch": f"{stage}-{author}-1",
                                                      "verdict": "accept", "failure_class": None, "quote": "gap", "witness_paths": [], "at": "t"})
                path.write_text(json.dumps(pipeline), encoding="utf-8")
            return "continue"

        class Asked(Exception):
            pass

        def fake_person(state, rule, code=None):
            return Asked(rule)

        def fake_rework(s, role, cases, reason, **kwargs):
            log["events"].append("rework")
            log["reworks"].append(dict(kwargs, stage=s, role=role, reason=reason))
            return "", {}

        driver.run_role, driver.py, driver.py_trace = fake_role, fake_py, (lambda script, *a, **k: fake_py(script, *a))
        driver.repair_budget, driver.rework = fake_budget, fake_rework
        driver.no_move, driver.fallback_person = fake_no_move, fake_person
        driver.stage_acceptor = lambda s: CRITIC
        driver.stages = lambda: {s: {"id": s, "roles": [AUTHORS[s], CRITIC], "acceptance_by": CRITIC, "outputs": []} for s in AUTHORS}
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                if recover:
                    saved = f"{stage}-{CRITIC}-9"
                    form = task_root / "work" / "handoffs" / f"{saved}.yaml"
                    form.parent.mkdir(parents=True, exist_ok=True)
                    form.write_text(f"header:\n  role: {CRITIC}\n  stage: {stage}\n  verdict: {verdict}\nstage_acceptance:\n  failure_class: spec\n"
                                    f"  quote: \"work/x.md#R-1: the register omits the limit\"\n  witness_paths: []\n", encoding="utf-8")
                    dispatches[saved] = {"id": saved, "stage": stage, "role": CRITIC, "status": "running"}
                    driver.last_dispatch = {"fresh": "", "stale": f"{stage}-{author}-1", "noid": ""}[recover]
                    log["saved"] = saved
                    log["result"] = driver.completion_for(stage, CRITIC, {} if recover == "noid" else {"id": saved})("digest")
                else:
                    driver.stage_critic_route(stage, author)
            except Asked as person:
                log["result"] = f"Person: {person}"
        log["printed"] = out.getvalue()
        return log
    finally:
        harness.cleanup(root)


def r1_accept():
    for stage in ("S2", "S3"):
        log = rig(stage, "ok")
        check_eq(f"R1 {stage}: the record is written inside the critic's dispatch, BEFORE its finish, and the stage closes",
                 (log["events"], log["result"]), (["questions", f"dispatch {CRITIC}", "raise", "record", "finish", "questions"], None))
        check_eq(f"R1 {stage}: no author round after an accept", log["reworks"], [])


def r2_reject_with_a_round_left():
    for stage in ("S2", "S3"):
        log = rig(stage, "concerns", counted=0)
        done = log["result"]
        check_eq(f"R2 {stage}: the critic's finish keeps the stage open by the word stage_in_repair",
                 (type(done).__name__, getattr(done, "unresolved", None)), ("OpenWork", "stage_in_repair"))
        check(f"R2 {stage}: the reason carries the quote and is at most 300 characters",
              "the register omits the limit" in done.reason and len(done.reason) <= 300, done.reason)
        check_eq(f"R2 {stage}: ONE author round follows the finish, after it (order; the conductor settles the critic's questions first)",
                 log["events"][-3:], ["finish", "questions", "rework"])
        rework = log["reworks"][0]
        check_eq(f"R2 {stage}: to the author of the stage, cause test_defect", (rework["role"], rework["cause"]), (AUTHORS[stage], "test_defect"))
        check_in(f"R2 {stage}: the round is counted+1 of the cap and the critic's form is the extra", "Repair round 1 of 2",
                 " ".join(rework["extra"]))
        check_in(f"R2 {stage}: ...and names the critic's form", f"work/handoffs/{stage}-{CRITIC}-1.yaml", " ".join(rework["extra"]))
    log = rig("S2", "concerns", counted=1)
    check_in("R2 S2: the second round reads 2 of 2", "Repair round 2 of 2", " ".join(log["reworks"][0]["extra"]))


def r3_reject_on_the_last_round():
    for label, counted in (("AT the cap", 2), ("BEYOND the cap", 3)):
        log = rig("S2", "concerns", counted=counted, seam="driver_accept")
        check_eq(f"R3 {label}: no author round, and a driver accept closes (None)", (log["reworks"], log["result"]), ([], None))
        check(f"R3 {label}: the order is dispatch, raise, record, seam, finish",
              log["events"][1:-1] == [f"dispatch {CRITIC}", "raise", "record", "seam", "finish"],
              str(log["events"]))
        check_eq(f"R3 {label}: the seam state names the exhausted review and the stage", (log["seam"][0]["why"], log["seam"][0]["stage"]),
                 ("stage_review_exhausted", "S2"))
    log = rig("S2", "concerns", counted=2)
    check("R3: a conductor that made no move gives the Person of the seam, never a silent close",
          str(log["result"]).startswith("Person:"), str(log["result"]))
    check_eq("R3: ...and no author round either", log["reworks"], [])


def r4_budget_unknown():
    log = rig("S2", "concerns", budget="none", seam="driver_accept")
    check_eq("R4: the budget cannot be read: the critic runs ONCE and no author round is dispatched",
             (log["events"].count(f"dispatch {CRITIC}"), log["reworks"]), (1, []))
    check_eq("R4: ...a defect is filed once and a reject goes to the seam", (log["defects"], len(log["seam"])), (1, 1))
    log = rig("S2", "ok", budget="none")
    check_eq("R4: an accept with an unreadable budget closes", (log["result"], log["reworks"]), (None, []))


def r5_unknown_word():
    log = rig("S3", "rejected")
    check_eq("R5: a verdict word outside the table writes no record and goes to the seam",
             ("record" in log["events"], len(log["seam"]), str(log["result"]).startswith("Person:")), (False, 1, True))
    check_in("R5: the seam says the word is unreadable", "unreadable", log["seam"][0]["text"])


def r6_owed_and_restart():
    import story_run
    owed = story_run.Driver.stage_repair_owed
    base = {"A": {"stage": "S2", "role": "qa-requirements-tester", "status": "accepted"},
            "C": {"stage": "S2", "role": CRITIC, "status": "accepted", "unresolved": "stage_in_repair"}}
    check_eq("R6: a critic accepted with stage_in_repair and no author round after it: owed",
             owed(base, "S2", "qa-requirements-tester", CRITIC, "stage_in_repair"), True)
    check_eq("R6: an author dispatch after it: not owed", owed(dict(base, D={"stage": "S2", "role": "qa-requirements-tester", "status": "running"}),
                                                              "S2", "qa-requirements-tester", CRITIC, "stage_in_repair"), False)
    check_eq("R6: another word, no critic, and a state that is no mapping: not owed",
             (owed({"C": dict(base["C"], unresolved="plan_pending")}, "S2", "qa-requirements-tester", CRITIC, "stage_in_repair"),
              owed({"A": base["A"]}, "S2", "qa-requirements-tester", CRITIC, "stage_in_repair"),
              owed(None, "S2", "qa-requirements-tester", CRITIC, "stage_in_repair")), (False, False, False))
    check_eq("R6: S4's own reading is the same rule with its word",
             story_run.Driver.s4_repair_owed({"C": {"stage": "S4", "role": CRITIC, "status": "accepted", "unresolved": "cases_in_repair"}}), True)


def r7_s3_s4_and_constants():
    import controller as CT
    import story_run
    from story_run_common import driver_for, seed
    for role in ("qa-requirements-tester", "qa-test-strategist"):
        check(f"R7 F-X2-4: {role} is in REPAIR_LOOP_ROLES and AUTHOR_ROLES (a mechanical round of an author counts)",
              role in CT.REPAIR_LOOP_ROLES and role in CT.AUTHOR_ROLES)
    root, _task_root, env = seed("QA-9")
    try:
        driver = driver_for(root, env, "QA-9", max_boundaries=1)
        got = driver.repair_budget("S2", "qa-requirements-tester", [])
        check("R7: the controller counts S2's rounds for the tester (cap 2, nothing spent)", got.get("cap") == 2 and got.get("counted") == 0, str(got))
        stages = driver.stages()
        check_eq("R7: S2, S3 and S4 name the critic as their acceptor; the critic is the last role of each",
                 [(stages[s].get("acceptance_by"), stages[s]["roles"][-1]) for s in ("S2", "S3", "S4")], [(CRITIC, CRITIC)] * 3)
        label = {"id": "S3-qa-test-strategist-1", "role": "qa-test-strategist", "stage": "S3", "status": "accepted",
                 "request_binding": {"purpose": CT.S3_LABELLING}}
        exit_window = {"id": "S3-qa-test-strategist-2", "role": "qa-test-strategist", "stage": "S3", "status": "accepted"}
        driver.controller_state = lambda: {"dispatches": {label["id"]: label}}
        check_eq("R7 E-X2-7f: an accepted window 1 (labelling) is never the author's finished work: no critic route", driver.s3_author_done(), False)
        driver.controller_state = lambda: {"dispatches": {label["id"]: label, exit_window["id"]: exit_window}}
        check_eq("R7: an accepted exit window is: a restart goes straight to the critic", driver.s3_author_done(), True)
        # the dispatcher: S1 stays simple, S2 goes to stage_S2
        calls = []
        driver.stage_simple, driver.stage_S2 = (lambda s: calls.append(("simple", s))), (lambda: calls.append(("S2",)))
        for stage in ("S1", "S2"):
            driver._act_prepare_stage({"stage": stage})
        check_eq("R7: the dispatcher sends S1 to stage_simple and S2 to stage_S2", calls, [("simple", "S1"), ("S2",)])
        # S2 restart: an accepted author is not dispatched again
        roles = []
        driver.stage_S2 = story_run.Driver.stage_S2.__get__(driver)
        driver.controller_state = lambda: {"dispatches": {"A": {"stage": "S2", "role": "qa-requirements-tester", "status": "accepted"}}}
        driver.stage_critic_route = lambda s, a: roles.append(("route", s, a))
        driver.run_role = lambda s, r, **k: roles.append(("author", r)) or ("", {})
        driver.stage_S2()
        check_eq("R6: with an accepted author the author is not dispatched again, the route goes on", roles, [("route", "S2", "qa-requirements-tester")])
        driver.controller_state = lambda: {"dispatches": {}}
        roles.clear()
        driver.role_lines = lambda s, r, record=None: []
        driver.stage_S2()
        check_eq("R6: without one, the author runs first and then the route", roles, [("author", "qa-requirements-tester"), ("route", "S2", "qa-requirements-tester")])
    finally:
        harness.cleanup(root)


def r8_s4_rounds_left_unchanged():
    from story_run_common import driver_for, seed
    for verdict, counted, expect in (("concerns", 0, "OpenWork"), ("ok", 0, "None"), ("concerns", 2, "seam")):
        root, task_root, env = seed("QA-9")
        try:
            driver = driver_for(root, env, "QA-9", max_boundaries=1)
            findings = task_root / "work" / "test-cases" / "a" / "critic-findings.md"
            findings.parent.mkdir(parents=True, exist_ok=True)
            findings.write_text("the cases say too little\n", encoding="utf-8")
            log = {"written": [], "seam": []}
            driver.last_dispatch = "S4-qa-case-critic-1"
            driver.stage_acceptor = lambda s: CRITIC
            driver.stage_verdict_known = lambda form: True
            driver.stage_acceptance_write = lambda s, d: log["written"].append((s, d))
            driver.stage_review_exhausted = lambda *a, **k: log["seam"].append(a[0]) or None
            driver.pipeline = lambda: {}
            complete = driver.s4_critic_completion(["TC-1"], counted, 2)
            got = complete(f"qa-case-critic S4 TC-1 · {verdict}\nTC-1 · ok · reviewed\nwork/x.md")
            check_eq(f"R8 S4 {verdict} at {counted} of 2: the record is written first, then S4's own rule",
                     (log["written"], type(got).__name__ if got is not None else "None", log["seam"]),
                     ([("S4", "S4-qa-case-critic-1")], {"OpenWork": "OpenWork", "None": "NoneType", "seam": "NoneType"}[expect] if expect == "OpenWork" else "None",
                      ["S4"] if expect == "seam" else []))
            if expect == "OpenWork":
                check_eq("R8: the word of S4 stays cases_in_repair", got.unresolved, "cases_in_repair")
        finally:
            harness.cleanup(root)


def r9_restart_road_reads_the_record_id():
    """t-1815 F1: a fresh process finishing a SAVED critic result reads the dispatch from the RECORD, never from `last_dispatch`."""
    for stage in ("S2", "S3"):
        for how in ("fresh", "stale"):
            log = rig(stage, "ok", recover=how)
            form = f"work/handoffs/{log['saved']}.yaml"
            check_eq(f"R9 {stage} ({how} last_dispatch): the record is written from the form of the RECORD's dispatch, and the stage closes",
                     (log.get("acceptance_forms"), log["result"]), ([form], None))
        log = rig(stage, "concerns", counted=0, recover="fresh")
        check_eq(f"R9 {stage}: a saved `concerns` with a round left keeps the stage open by stage_in_repair",
                 getattr(log["result"], "unresolved", None), "stage_in_repair")
        log = rig(stage, "ok", recover="noid")
        check_eq(f"R9 {stage}: a record with NO id goes to the conductor seam with the reason, writes nothing",
                 (log.get("acceptance_forms"), len(log["seam"]), "no dispatch id" in log["seam"][0]["text"]), (None, 1, True))
        check("R9: ...and the seam made no move, so the fallback is the person's - never a silent close",
              str(log["result"]).startswith("Person:"), str(log["result"]))
    # S4: the recovery completion of the case critic, last_dispatch unset
    from story_run_common import driver_for, seed
    root, task_root, env = seed("QA-9")
    try:
        driver = driver_for(root, env, "QA-9", max_boundaries=1)
        log = {"written": [], "seam": []}
        driver.last_dispatch = ""
        driver.stage_acceptor = lambda s: CRITIC
        driver.stage_verdict_known = lambda form: True
        driver.stage_acceptance_write = lambda s, d: log["written"].append((s, d))
        driver.stage_review_exhausted = lambda *a, **k: log["seam"].append(k.get("text") or "verdict") or None
        driver.pipeline = lambda: {}
        got = driver.s4_critic_completion(["TC-1"], 0, 2, dispatch_id="S4-qa-case-critic-7")("qa-case-critic S4 TC-1 · ok\nTC-1 · ok · reviewed\n")
        check_eq("R9 S4: the restart road writes the record of the RECORD's dispatch", (log["written"], got), ([("S4", "S4-qa-case-critic-7")], None))
        log["written"].clear()
        driver.s4_critic_completion(["TC-1"], 0, 2, dispatch_id="")("x")
        check_eq("R9 S4: a record with no id writes nothing and asks the seam with the reason", (log["written"], len(log["seam"])), ([], 1))
        check_in("R9 S4: ...the reason names the missing id", "no dispatch id", log["seam"][0])
    finally:
        harness.cleanup(root)


def r10_questions_come_from_the_critics_form():
    """t-1815 F2: the critic's own `questions[]` are raised before its record, with check=True, by its role; a form with no file raises nothing."""
    log = rig("S2", "ok")
    args, check_flag = log["raises"][0]
    check_eq("R10: the raise is the critic's: --asked-by the critic role, --from-handoff the critic's form, stage S2",
             (args[args.index("--asked-by") + 1], args[args.index("--from-handoff") + 1], args[args.index("--stage") + 1]),
             (CRITIC, f"work/handoffs/S2-{CRITIC}-1.yaml", "S2"))
    check_eq("R10: check=True - a refused form is a Refusal naming its entries, never a silent loss", check_flag, True)
    check_eq("R10: it runs BEFORE the record (a refused record loses no question)", log["events"].index("raise") < log["events"].index("record"), True)
    check_eq("R10: one raise per critic finish (the route's settling is the conductor's, not a second raise)", len(log["raises"]), 1)


def main() -> None:
    r1_accept()
    r2_reject_with_a_round_left()
    r3_reject_on_the_last_round()
    r4_budget_unknown()
    r5_unknown_word()
    r6_owed_and_restart()
    r7_s3_s4_and_constants()
    r8_s4_rounds_left_unchanged()
    r9_restart_road_reads_the_record_id()
    r10_questions_come_from_the_critics_form()
    finish("test_stage_critic_route")


if __name__ == "__main__":
    main()
