#!/usr/bin/env python3
"""S0 can be closed. It could not be, and nothing said so.

0.7.7 review, finding A-F1. `s0.md` §8 wrote the pipeline, then told the orchestrator to
initialize the controller, then §9 closed the stage with `stage_done.py --status done`. But
`stage_done` refuses `done` on a controller-managed task whose controller stage is not
`completed`, and NO ROLE runs S0 — there is no dispatch to accept and never will be. A
Sonnet orchestrator following the phase file top to bottom reached a refusal with no remedy
in it, no waiver command, and no registry entry (A24 registered only the opposite
direction). The story could not start and could not be passed by the person's word either.

Three things are proven here: the order that works (close, then initialize), the refusal's
own remedy and waiver line for a task that is already initialized, and the `code_only`
receipt that closes S0 afterwards.
"""
import hashlib
import io
import json
import sys
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     temp_project, use_project)

sys.path.insert(0, str(SCRIPTS))
import stage_done  # noqa: E402
from controller import Controller  # noqa: E402

TASK = "QA-S0"


def story(root):
    """A project with S0's own pipeline.json written, and nothing else done yet."""
    art = root / "qa-factory" / "artifacts" / TASK
    (art / "work").mkdir(parents=True, exist_ok=True)
    (art / "pipeline.json").write_text(json.dumps({
        "ticket": TASK, "parent_feature": None, "size": None, "environment": "local",
        "environment_pending": False, "implementation_source": None, "warnings": [],
        "stages": {"S0": {"status": "running", "role": None, "digest": ""}},
        "gates": {}, "halts": []}), encoding="utf-8")
    return art


def initialize(art):
    Controller(art).apply("initialize", {
        "scope": [], "source_revision": "snapshot-hash",
        "known_paths": {"task_root": str(art)}, "idempotency_key": "init"})


def close(art, **kwargs):
    """stage_done.run for S0, with its stderr captured — that is where the remedy is."""
    err = io.StringIO()
    with redirect_stderr(err):
        code = stage_done.run(TASK, "S0", kwargs.pop("status", "done"), None,
                              "preflight green, env=local", True)
    return code, err.getvalue()


def closing_before_initialize_is_the_order_that_works():
    root = temp_project("qa-s0-order-")
    try:
        use_project(root)
        art = story(root)
        code, _ = close(art)
        check_eq("S0 closes while no controller exists yet", code, 0)
        pipeline = json.loads((art / "pipeline.json").read_text(encoding="utf-8"))
        check_eq("and the pipeline says so", pipeline["stages"]["S0"]["status"], "done")
        initialize(art)
        check("the controller initializes after it",
              bool(Controller(art).state().get("source_revision")))
    finally:
        cleanup(root)


def the_refusal_carries_its_own_way_out():
    root = temp_project("qa-s0-refusal-")
    try:
        use_project(root)
        art = story(root)
        initialize(art)
        code, message = close(art)
        check_eq("initialize-then-close is still refused", code, stage_done.EXIT_BAD_ARGS)
        check_in("the refusal names the ordering rule", "BEFORE `--operation initialize`",
                 message)
        check_in("and the code_only receipt for a task already initialized",
                 "code_only", message)
        check_in("and the accept route for a stage a role DID run",
                 "story_step.py finish --task QA-S0 ", message)
        check_not_in("and the hand-built receipt is not taught any more (SC1-12)",
                     "--operation accept", message)
        check_in("and the person's word, with the ready command", "waiver.py", message)
        check_in("with the exact block text the registry names",
                 '--block "no accepted controller stage"', message)
    finally:
        cleanup(root)


def a_persons_word_passes_it():
    root = temp_project("qa-s0-waiver-")
    try:
        use_project(root)
        art = story(root)
        initialize(art)
        pipeline = json.loads((art / "pipeline.json").read_text(encoding="utf-8"))
        pipeline["stage_overrides"] = [{"stage": "S0", "match": "no accepted controller stage",
                                        "decision": "it is preflight, close it",
                                        "at": "2026-09-21T00:00:00Z", "by": "human"}]
        (art / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        code, message = close(art)
        check_eq("no block in this factory is one a person cannot pass", code, 0)
        check_in("and the pass is said out loud, not swallowed",
                 "it is preflight, close it", message)
    finally:
        cleanup(root)


def code_only_closes_s0_on_an_initialized_task():
    root = temp_project("qa-s0-code-only-")
    try:
        use_project(root)
        art = story(root)
        initialize(art)
        evidence = art / "pipeline.json"
        Controller(art).apply("code_only", {
            "id": "s0-preflight", "stage": "S0",
            "reason": "no role runs preflight; the pipeline is its evidence",
            "evidence_refs": [{"path": "pipeline.json",
                               "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}],
            "idempotency_key": "code-only-S0"})
        check_eq("the controller accepts a code-only S0",
                 Controller(art).state()["stages"]["S0"]["status"], "completed")
        code, _ = close(art)
        check_eq("and stage_done then closes the stage", code, 0)
    finally:
        cleanup(root)


def the_story_budget_stops_at_a_closed_stage():
    """0.7.7 review, D-F12. The ceiling printed one line on stderr and exited 0 — a line an
    orchestrator walks straight past. The stage still closes; the stop is the question that
    follows it."""
    root = temp_project("qa-s0-budget-")
    try:
        use_project(root)
        art = story(root)
        config = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        config["budget"] = {"story_usd": 1, "warn_at": [0.5]}
        (root / "qa-factory" / "config.json").write_text(json.dumps(config), encoding="utf-8")
        cost = root / "qa-factory" / "state" / "cost"
        cost.mkdir(parents=True, exist_ok=True)
        (cost / "s-1.json").write_text(json.dumps(
            {"session_id": "s-1", "by_task": {TASK: {"tokens": 10}},
             "agents": []}), encoding="utf-8")
        # The spend the ceiling polices is the sessions the price NAMES by evidence (FR-24, t-170): a
        # `by_task` tag binds none, so the driver's journal names `s-1` (one role row whose running
        # total is the $4.0 the tag used to carry).
        (art / "state").mkdir(parents=True, exist_ok=True)
        (art / "state" / "driver-runs.jsonl").write_text(json.dumps(
            {"kind": "role", "role": "qa-scout", "dispatch": "S1-qa-scout-1", "stage": "S1",
             "session_id": "s-1", "num_turns": 3, "total_cost_usd": 4.0,
             "ts": "2026-09-30T10:00:00+00:00"}) + "\n", encoding="utf-8")
        code, _ = close(art)
        check_eq("a story past its ceiling stops and asks", code, stage_done.STORY_BUDGET_EXIT)
        pipeline = json.loads((art / "pipeline.json").read_text(encoding="utf-8"))
        check_eq("and the stage is closed all the same — this is a question, not a failure",
                 pipeline["stages"]["S0"]["status"], "done")
    finally:
        cleanup(root)


def the_story_facts_are_written_by_code_and_survive_the_projections():
    """S0-S2 used to tell the orchestrator to WRITE `size`, `implementation_source`,
    `environment` and `warnings[]` into pipeline.json, in a skill that forbids editing that
    file by hand, because no script offered to. `stage_done.py --set/--warn` is that script —
    and what it writes has to survive both projections that rewrite the file afterwards."""
    root = temp_project("qa-s0-facts-")
    try:
        use_project(root)
        art = story(root)
        check_eq("a whitelisted fact is written",
                 stage_done.set_facts(TASK, {"implementation_source": "diff"}, []), 0)
        check_eq("a warning is appended", stage_done.set_facts(
            TASK, {"size": "L", "environment_pending": False},
            ["S0 vcs_api: no token — `glab auth login`"]), 0)
        code, _ = close(art)
        check_eq("the stage still closes with facts on the file", code, 0)
        pipeline = json.loads((art / "pipeline.json").read_text(encoding="utf-8"))
        check_eq("and the stage transition does not roll them back",
                 (pipeline["size"], pipeline["implementation_source"],
                  pipeline["environment_pending"]), ("L", "diff", False))
        initialize(art)
        controller = Controller(art)
        controller.project(controller.store.read())
        pipeline = json.loads((art / "pipeline.json").read_text(encoding="utf-8"))
        check_eq("the controller's projection keeps a key it knows nothing about",
                 pipeline["size"], "L")
        check_eq("including the source S2 checks at its entry",
                 pipeline["implementation_source"], "diff")
        check_eq("and the warning gate A has to repeat", len(pipeline["warnings"]), 1)
        err = io.StringIO()
        with redirect_stderr(err):
            code = stage_done.main(["--task", TASK, "--set", "archived=true"])
        check_eq("a key outside the list is refused", code, stage_done.EXIT_BAD_ARGS)
        check_in("naming the keys that exist", "implementation_source", err.getvalue())
    finally:
        cleanup(root)


def the_refusal_is_registered():
    import refusal_registry
    entry = next((e for e in refusal_registry.REGISTRY if e["id"] == "SD-managed-stage"), None)
    check("A24 knows this refusal exists", bool(entry))
    if entry:
        check_in("and how a person's word passes it", "waiver.py", entry["override"])
        check_in("and the test that proves it", "test_s0_close_order.py", entry["test"])
    check_eq("the registry itself is clean", refusal_registry.findings(), [])


def main():
    closing_before_initialize_is_the_order_that_works()
    the_refusal_carries_its_own_way_out()
    a_persons_word_passes_it()
    code_only_closes_s0_on_an_initialized_task()
    the_story_budget_stops_at_a_closed_stage()
    the_story_facts_are_written_by_code_and_survive_the_projections()
    the_refusal_is_registered()
    finish("S0 close order")


if __name__ == "__main__":
    main()
