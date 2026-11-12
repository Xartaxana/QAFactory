#!/usr/bin/env python3
"""The System One judge: off by default, never decides under its threshold, never halts a stage.

No test here reaches the network: `judge._post` is replaced by a transport that answers from
a table, so what is checked is the factory's side - registry, thresholds, journal, fallback -
and the one-command stage boundary of story_step.py on a real controller.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import judge  # noqa: E402


def fake_transport(table):
    calls = []

    def post(payload, key, timeout, attempts=4):
        calls.append(payload)
        answers = {}
        for name, question in payload["questions"].items():
            value = table(payload["state"], name, question)
            if question["type"] == "noul":
                answers[name] = {"type": "noul", "noul": value}
            elif question["type"] == "choice":
                answers[name] = {"type": "choice", "choice": value[0], "confidence": value[1],
                                 "probabilities": {value[0]: value[1]}}
            else:
                answers[name] = {"type": "score", "score": value[0], "confidence": value[1],
                                 "probabilities": {str(value[0]): 1.0}}
        return {"model": "judge-test", "answers": answers, "usage": {"input_tokens": 100}}
    post.calls = calls
    return post


def set_judge(root: Path, block: dict | None) -> None:
    path = root / "qa-factory/config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg.pop("judge", None)
    if block is not None:
        cfg["judge"] = block
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def seed_story(root: Path, ticket: str) -> Path:
    task = root / "qa-factory/artifacts" / ticket
    (task / "work").mkdir(parents=True)
    (task / "work/requirements-register.md").write_text(
        "## Register\n\n| R | Requirement | source |\n|---|---|---|\n"
        "| R-1 | An added node is shown with a green border | ac |\n"
        "| R-2 | An added node is shown with a red border | ac |\n"
        "| R-3 | POST /validate returns 422 for a malformed config | ac |\n\n"
        "## Oracle status\n\n| R | status |\n|---|---|\n| R-1 | ok:AC1 |\n", encoding="utf-8")
    return task


def the_project_is_found_by_the_one_walk() -> None:
    """t-622 (B-309 (d)): `judge._project_root` is `runtime_paths.nearest_project` with the working directory as the default
    start. Not found is None - the judge stays off - never the folder it started from."""
    root = harness.temp_project("qa-judge-walk-").resolve()
    outside = harness.temp_dir("qa-judge-outside-").resolve()      # NOT a project on purpose: the judge's "unknown" road (t-617 section 8.2)
    cwd0 = os.getcwd()
    try:
        deep = root / "qa-factory" / "artifacts" / "QA-1" / "work"
        deep.mkdir(parents=True)
        check_eq("the project above a story folder", judge._project_root(deep), root)
        check_eq("a start with a marker AT it is that folder", judge._project_root(root), root)
        check_eq("a start under no project is None, not the start folder", judge._project_root(outside), None)
        os.chdir(root)
        try:
            check_eq("a blank start is the working directory (inside a project: that project)", judge._project_root(""), root)
            check_eq("no start at all is the working directory too", judge._project_root(), root)
            check_eq("an explicit start outside every project is still None while the working directory is inside one",
                     judge._project_root(outside), None)
        finally:
            os.chdir(cwd0)
        os.chdir(outside)
        try:
            check_eq("the working directory outside every project: None (the judge is off)", judge._project_root(), None)
            check_eq("...and settings() says so without a problem", (judge.settings(outside)["provider"], judge.settings(outside)["problems"]),
                     ("none", []))
        finally:
            os.chdir(cwd0)
    finally:
        os.chdir(cwd0)
        harness.cleanup(root)
        harness.cleanup(outside)


def main() -> None:
    the_project_is_found_by_the_one_walk()
    check_eq("the shipped registry is valid", judge.registry_errors(), [])
    registry = judge.load_registry()
    check("every enabled judgment names what it replaces and who gets an undecided item",
          all(item.get("replaces") and item.get("undecided") for item in registry.values()))
    check("a rejected judgment records why", all(item.get("calibration") for item in registry.values()
                                                  if item.get("enabled") is False))

    root = harness.temp_project("qa-judge-")
    os.environ["QA_JUDGE_TEST_KEY"] = "not-a-real-key"
    real_post = judge._post
    try:
        harness.use_project(root)
        task = seed_story(root, "QA-1")

        # provider none: the default, and nothing leaves the machine
        judge._post = fake_transport(lambda *a: 0.99)
        reply = judge.ask({"x": 1}, {"q": {"judgment": "judge_probe"}}, project_root=root)
        check_eq("no judge block means provider none", reply["status"], "off")
        check_eq("provider none sends nothing", len(judge._post.calls), 0)
        import judge_requirements
        check_eq("a judge script is a no-op without a provider", judge_requirements.run(task)["status"], "off")
        check("and writes no file", not (task / "work/judge-requirements.json").exists())

        # K-D5: every coercion `settings` makes is said in `problems`; the default is not a problem
        check_eq("no judge block is the default, not a problem", judge.settings(root)["problems"], [])
        check_eq("and the reply carries the empty list and the plain reason",
                 (reply["problems"], reply["reason"]), ([], "judge.provider is none"))
        set_judge(root, {"provider": "none", "mode": "on"})
        check_eq("provider none and a valid mode are choices", judge.settings(root)["problems"], [])
        set_judge(root, {"provider": "openai", "mode": "of"})
        said = judge.settings(root)
        check_eq("an unknown provider never turns the judge on, an unknown mode stays shadow",
                 (said["provider"], said["mode"]), ("none", "shadow"))
        check("both coercions are named", len(said["problems"]) == 2 and "'openai'" in said["problems"][0]
              and "'of'" in said["problems"][1])
        refused = judge.ask({"x": 1}, {"q": {"judgment": "judge_probe"}}, project_root=root)
        check("when off because of a problem, the reason IS that problem",
              refused["status"] == "off" and refused["reason"] == said["problems"][0] and refused["problems"] == said["problems"])
        check_eq("status() carries the problems", judge.status(root)["problems"], said["problems"])
        set_judge(root, {"provider": "TypeSafe"})
        check("the provider match is exact", judge.settings(root)["provider"] == "none"
              and "'TypeSafe'" in judge.settings(root)["problems"][0])
        set_judge(root, {"provider": "typesafe", "mode": "On", "api_key_env": "QA_JUDGE_TEST_KEY"})
        judge._post = fake_transport(lambda *a: 0.99)
        shadowed = judge.ask({"x": 1}, {"q": {"judgment": "judge_probe"}}, project_root=root)
        check("a mode the code does not know stays shadow, advisory, and says so",
              shadowed["status"] == "ok" and shadowed["advisory"] is True and shadowed["mode"] == "shadow"
              and len(shadowed["problems"]) == 1 and "'On'" in shadowed["problems"][0])
        for odd in ("typesafe", ["typesafe"], None, 0, False):
            path = root / "qa-factory/config.json"
            cfg = json.loads(path.read_text(encoding="utf-8"))
            cfg["judge"] = odd
            path.write_text(json.dumps(cfg), encoding="utf-8")
            said = judge.settings(root)
            check(f"a judge block that is {type(odd).__name__} is named and leaves the judge off",
                  said["provider"] == "none" and len(said["problems"]) == 1 and type(odd).__name__ in said["problems"][0])
        path = root / "qa-factory/config.json"
        good = path.read_text(encoding="utf-8")
        for broken, kind in (("{not json", "JSONDecodeError"), ("[]", "TypeError"), ("", "JSONDecodeError")):
            path.write_text(broken, encoding="utf-8")
            said = judge.settings(root)
            check(f"an unreadable config ({kind}) is named and leaves the judge off",
                  said["provider"] == "none" and len(said["problems"]) == 1 and kind in said["problems"][0])
            check_eq("and ask is off with that reason", judge.ask({"x": 1}, {"q": {"judgment": "judge_probe"}},
                     project_root=root)["reason"], said["problems"][0])
        path.write_text(good, encoding="utf-8")
        set_judge(root, None)
        import tempfile
        with tempfile.TemporaryDirectory() as bare:
            nothing = judge.settings(bare)
            check("no project at all is not a problem either", nothing["problems"] == [] and nothing["project_root"] is None)
        judge._post = fake_transport(lambda *a: 0.99)

        # shadow: journalled, advisory
        set_judge(root, {"provider": "typesafe", "mode": "shadow", "api_key_env": "QA_JUDGE_TEST_KEY"})
        reply = judge.ask({"x": 1}, {"q": {"judgment": "judge_probe"}}, project_root=root, ticket="QA-1")
        check("shadow answers are advisory", reply["status"] == "ok" and reply["advisory"] is True)
        journal = (root / "qa-factory/state/judgments.jsonl").read_text(encoding="utf-8")
        check_in("every answer is journalled", '"judgment": "judge_probe"', journal)
        check("the key is never journalled", "not-a-real-key" not in journal)

        # thresholds: under the threshold is undecided, whatever the leaning
        set_judge(root, {"provider": "typesafe", "mode": "on", "api_key_env": "QA_JUDGE_TEST_KEY"})
        judge._post = fake_transport(lambda *a: 0.6)
        unsure = judge.ask({"x": 1}, {"q": {"judgment": "source_relevant"}}, project_root=root)
        check("a noul between the thresholds decides nothing",
              unsure["answers"]["q"]["decided"] is False and unsure["answers"]["q"]["value"] is None)
        check("mode on is not advisory", unsure["advisory"] is False)

        # a rejected judgment is never sent
        judge._post = fake_transport(lambda *a: 0.99)
        rejected = next(jid for jid, item in registry.items() if item.get("enabled") is False)
        skipped = judge.ask({"x": 1}, {"q": {"judgment": rejected}}, project_root=root)
        check_eq("a judgment that failed calibration is not asked", (skipped["status"], len(judge._post.calls)),
                 ("off", 0))

        # the judge failing is a reason to use the role, never a halt
        def broken(*_a, **_k):
            raise RuntimeError("HTTP 529: overloaded")
        judge._post = broken
        down = judge.ask({"x": 1}, {"q": {"judgment": "judge_probe"}}, project_root=root)
        check_eq("an unreachable judge is `unavailable`, not an exception", down["status"], "unavailable")
        check_eq("and a judge script reports it and exits for the fallback",
                 judge_requirements.run(task)["status"], "unavailable")
        set_judge(root, {"provider": "typesafe", "mode": "on", "api_key_env": "QA_JUDGE_NO_SUCH_KEY"})
        check_eq("a missing key is `unavailable`", judge.ask({"x": 1}, {"q": {"judgment": "judge_probe"}},
                                                           project_root=root)["status"], "unavailable")

        # S2 screens: the Register table only, pairs decided on the probability of `opposite`
        set_judge(root, {"provider": "typesafe", "mode": "on", "api_key_env": "QA_JUDGE_TEST_KEY"})
        rows = judge_requirements.read_register(task / "work/requirements-register.md")
        check_eq("a later table keyed by the same ids does not overwrite the register",
                 rows["R-1"], "An added node is shown with a green border")

        def table(state, name, question):
            if name == "relation":
                both = state["statement_1"] + state["statement_2"]
                hit = "green" in both and "red" in both
                return ("opposite", 0.97) if hit else ("different", 0.95)
            if name == "observable":
                return ("api", 0.97) if "POST" in state["requirement"] else ("ui", 0.96)
            return 0.95
        judge._post = fake_transport(table)
        report = judge_requirements.run(task)
        check_eq("the planted conflict is the only conflict", [c["pair"] for c in report["conflicts"]], [["R-1", "R-2"]])
        check_eq("every pair was asked", report["pairs_asked"], 3)
        check_eq("channel comes from the requirement's own text", report["observable"]["R-3"]["channel"], "api")
        check("each subject is its own small request",
              all(len(json.dumps(call["state"])) < 2000 for call in judge._post.calls))

        # S4: no case is skipped, a case without a plan row is never clean
        cases = task / "work/test-cases/area"
        cases.mkdir(parents=True)
        for number in (1, 2):
            (cases / f"TC-00{number}.md").write_text(
                f"---\nid: TC-00{number}\ntitle: Added node border\nplan_row: TS-{number}\n---\n"
                "## Given\n- a workflow\n## When\n1. open the diff\n## Then\n1. border is green\n", encoding="utf-8")
        (task / "work/test-plan.json").write_text(json.dumps(
            [{"id": "TS-1", "required_scenarios": ["added node is green"], "coverage_obligations": []}]), encoding="utf-8")
        import judge_cases
        judge._post = fake_transport(lambda *a: 0.97)
        verdicts = judge_cases.run(task)
        check_eq("every case is judged", verdicts["cases"], 2)
        check_eq("all judged dimensions passing makes a case clean", verdicts["clean"], ["TC-001"])
        check_eq("a case whose plan row is unknown goes to the critic", verdicts["needs_critic"], ["TC-002"])

        bill = judge.summary(root, "QA-1")
        check("the bill counts questions and money", bill["questions"] > 0 and bill["cost_usd"] > 0)

        # Gates: the judge reads a person's words into an option and records nothing.
        import judge_reply
        judge._post = fake_transport(lambda s, n, q: ("approve_with_edits", 0.97))
        said = judge_reply.intent("Approve the plan?", "yes, but drop TC-012",
                                  ticket="QA-1", project_root=root)
        check_eq("a gate answer is read into a registered option", said["value"], "approve_with_edits")
        check_in("and the line says it is only pre-filled", "confirm it with the person",
                 judge_reply.render(said, "intent"))
        judge._post = fake_transport(lambda s, n, q: ("handed", 0.6))
        unsure = judge_reply.stand_gap_option("I'll see about that one", ticket="QA-1", project_root=root)
        check("under 0.9 a stand-gap answer stays the person's free text",
              unsure["value"] is None and unsure["status"] == "ok")
        judge._post = fake_transport(lambda *a: 0.96)
        same = judge_reply.same_cause("S5 is not accepted", "the controller never accepted S5",
                                      ticket="QA-1", project_root=root)
        check_eq("two refusals can be recognised as one cause", same["value"], True)

        # A judged refusal: passed only in mode on, and shown to the person at the gate.
        judge._post = fake_transport(lambda *a: 0.99)
        passed = judge.judged_refusal("digest", "judge_probe", {"digest": "all green"},
                                      ticket="QA-1", stage="S5", project_root=root)
        check("a FORM refusal the judge is sure about passes in mode on", passed["passed"] is True)
        rows = judge.passes(root, "QA-1")
        check_eq("and is listed for the gate brief", [r["refusal"] for r in rows], ["digest"])
        import gate_brief
        block = gate_brief.judge_lines(gate_brief.judge_facts("QA-1", task))
        check_in("the gate brief carries a Judge block", "## Judge", block)
        check_in("naming the block that was passed", "`digest` passed by `judge_probe`", block)
        check_eq("and no Judge block at all without a provider",
                 gate_brief.judge_lines(gate_brief.judge_facts("QA-1", harness.PLUGIN_ROOT)), [])

        # story_step: one command per boundary on a real controller, and the stop marker
        judge._post = real_post
        set_judge(root, None)
        from controller import Controller
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
        (task / "pipeline.json").write_text(json.dumps(
            {"ticket": "QA-1", "size": "S", "environment": "local", "implementation_source": "diff",
             "stages": {"S0": {"status": "pending"}}, "gates": {}, "halts": []}), encoding="utf-8")
        harness.run_script("stage_done.py", "--task", "QA-1", "--stage", "S0", "--status", "done",
                           "--digest", "preflight green", cwd=root, env=env)
        controller = Controller(task)
        controller.apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1",
                                        "known_paths": {"root": str(task), "project_root": str(root)},
                                        "idempotency_key": "init"})
        started = harness.run_script("story_step.py", "start", "--task", "QA-1", "--stage", "S0",
                                     "--role", "qa-scout", cwd=root, env=env)
        check_in("a role that is not the stage's is refused by name", "not a role of S0", started.stdout)
        where = harness.run_script("story_step.py", "where", "--task", "QA-1", cwd=root, env=env)
        check_in("where prints the controller's next action", '"stage": "S1"', where.stdout)
        check_in("and says the judge is off", "judge: off", where.stdout)
        begun = harness.run_script("story_step.py", "start", "--task", "QA-1", "--stage", "S1",
                                   "--role", "qa-scout", cwd=root, env=env)
        check_in("start dispatches through the controller in one command", "dispatched S1-qa-scout-1", begun.stdout)
        check_in("and prints the Agent prompt with the stage's declared inputs",
                 "qa-factory/artifacts/QA-1/pipeline.json", begun.stdout)
        check_eq("the dispatch is the controller's own receipt",
                 Controller(task).state()["dispatches"]["S1-qa-scout-1"]["status"], "running")
        empty = harness.run_script("story_step.py", "finish", "--ignore-handoff",
                                   "--task", "QA-1", "--dispatch-id",
                                   "S1-qa-scout-1", "--digest", "qa-scout S1 done", cwd=root, env=env)
        check_in("finish refuses a handover with none of the declared outputs", "missing handover", empty.stdout)
        for name in ("context-manifest.json", "context-bundle.json"):
            (task / "work" / name).write_text("{}", encoding="utf-8")
        ended = harness.run_script("story_step.py", "finish", "--ignore-handoff",
                                   "--task", "QA-1", "--dispatch-id", "S1-qa-scout-1",
                                   "--digest", "qa-scout S1 done - work/context-manifest.json - ok", cwd=root, env=env)
        check_in("finish accepts with hashed evidence and closes the stage", "stage complete", ended.stdout)
        check_in("and answers with the next action", '"stage": "S2"', ended.stdout)
        check_eq("pipeline.json and the controller agree",
                 json.loads((task / "pipeline.json").read_text(encoding="utf-8"))["stages"]["S1"]["status"], "done")
        cfg_path = root / "qa-factory/config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["pipeline"] = {"stop_after": "gate_A"}
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        import story_step
        import hooklib
        hooklib._PROJECT_ROOT_CACHE = None
        gate = story_step._next(type("C", (), {"next_action": lambda self: {"action": "await_gate", "gate": "A"}})())
        check_eq("Gate A is still presented under stop_after", gate.get("stop_after"), "gate_A")
        later = story_step._next(type("C", (), {"next_action": lambda self: {"action": "prepare_stage", "stage": "S5"}})())
        check_eq("and nothing after it runs", later["action"], "stop")

        # With a judge configured, every boundary prints the bill and the blocks it passed:
        # a pass nobody sees until the gate brief is a pass nobody could question earlier.
        set_judge(root, {"provider": "typesafe", "mode": "on", "api_key_env": "QA_JUDGE_TEST_KEY"})
        billed = harness.run_script("story_step.py", "where", "--task", "QA-1", cwd=root, env=env)
        check_in("where prints the judge's bill", "judge: typesafe on", billed.stdout)
        check_in("and how many blocks it let through", "1 block(s) passed by the judge", billed.stdout)
    finally:
        judge._post = real_post
        harness.cleanup(root)
    harness.finish("test_judge")


if __name__ == "__main__":
    main()
