#!/usr/bin/env python3
"""A person's word passes a stage block wherever the refusal says it does (FR-4, FR-5).

The rule is the factory's oldest: a check stops a SILENT pass, never an informed one. It was
kept per-check, so it held at one gate and failed at the next — S5's window record cost three
answers and a halt in TP1-13797 run 5 before it read `stage_overrides[]` like everything
else.

The walk that followed (PLAN P21.4, design/controller-blocks.md) counted 96 `raise
StateConflict` in the controller and found seven built from a person-filtered list. Two more
were the same class as S5, and this file is their test:

  * S3 — `planning_contract.py`'s refusal ends by naming `waiver.py --stage S3 --block`, and
    the exit gate passes on that word. The controller did not read it, so the word opened the
    handoff and the stage still would not close. Five conductor sessions of run 5 ($1.94) stood
    on that one message.
  * S1 — the same shape for `source collection pending/invalid`.

What is proved: without the person's word the stage stays blocked (the check still works), with
it the stage closes, and the words are recorded on the dispatch, not swallowed.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, cleanup, finish, s5_apply, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
from controller import Controller, StateConflict  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_controller_state as BASE  # noqa: E402


def story(root: Path) -> tuple:
    (root / "qa-factory").mkdir(parents=True, exist_ok=True)
    (root / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
    task = root / "qa-factory" / "artifacts" / root.name
    (task / "work").mkdir(parents=True)
    controller = Controller(task)
    controller.apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1",
                                    "known_paths": {"root": str(task)}, "idempotency_key": "init"})
    BASE.accept_stage(controller, task, "S0")
    return controller, task


def override(task: Path, stage: str, match: str, decision: str) -> None:
    """What `waiver.py --stage <S> --block "<match>" --decision "<words>"` leaves behind."""
    path = task / "pipeline.json"
    pipeline = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    pipeline.setdefault("stage_overrides", []).append(
        {"stage": stage, "match": match, "decision": decision, "by": "human"})
    path.write_text(json.dumps(pipeline), encoding="utf-8")


def close_s3(controller: Controller, task: Path) -> dict:
    """S3 completion with a plan row the contract refuses."""
    BASE.seed_plan(task, rows=[{"id": "TS-14", "impact": "low", "likelihood": "low",
                                "confidence": "high", "risk_rationale": "bounded",
                                "risk_source_refs": [], "coverage_refs": ["R-1"], "unknowns": [],
                                "verification_depth": "low", "required_scenarios": [],
                                "test_level_rationale": "unit", "design_review_required": False,
                                "bounded_reversible": True}])
    evidence = task / "S3.txt"
    evidence.write_text("plan", encoding="utf-8")
    import hashlib
    controller.apply("dispatch", {"id": "dS3", "stage": "S3", "role": "qa-test-strategist",
                                  "scope": ["TC-1"], "input_hash": "S3", "budget": {},
                                  "known_paths": {}, "idempotency_key": "dispatch-S3"})
    return {"id": "dS3", "status": "accepted", "stage_complete": True,
            "evidence_refs": [{"path": evidence.name,
                               "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}],
            "idempotency_key": "accept-S3"}


def main() -> None:
    root = temp_dir("qa-person-word-")
    import hooklib
    cached, hooklib._PROJECT_ROOT_CACHE = hooklib._PROJECT_ROOT_CACHE, None
    old_env = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = str(root)
    try:
        controller, task = story(root)
        for stage in ("S1", "S2"):
            BASE.accept_stage(controller, task, stage)
        receipt = close_s3(controller, task)

        # 1. The check still checks.
        standing = ""
        try:
            controller.apply("accept", receipt)
            check("an invalid plan row does not close S3 on its own", False)
        except (StateConflict, ValueError) as refusal:
            standing = str(refusal)
            check_in("and the refusal names what is wrong", "TS-14", standing)
            check_in("as the plan contract worded it", "structured test plan invalid", standing)

        # 2. The person's word passes it - recorded by the command itself (t-722 C2-5): the driver leaves the refusal it is
        # handling where `waiver.py` reads it, the block is a PART of one of its lines (the door the refusal prints says
        # `<part of the line>`), and the writer holds it against the record by the readers' rule before it writes.
        import waiver
        (task / "pipeline.json").write_text(json.dumps({"ticket": root.name, "stages": {
            "S0": {"status": "done"}, "S1": {"status": "done"}, "S2": {"status": "done"}}}), encoding="utf-8")
        (task / "state").mkdir(exist_ok=True)
        (task / "state" / "standing-refusal.json").write_text(json.dumps(
            {"stage": "S3", "lines": waiver.refusal_parts([standing]), "doors": waiver.door_blocks(standing)}), encoding="utf-8")
        said = "TS-14 stays as it is: the limit is not testable on this stand and the row says so. Go on."
        check_eq("the S3 refusal's door names a placeholder, which is no door", waiver.door_blocks(standing), [])
        refused = waiver.run_stage(root.name, "S3", "TS-99", said, "human")
        check_eq("a block that is in no line of the standing S3 refusal is refused, nothing recorded",
                 (refused, json.loads((task / "pipeline.json").read_text(encoding="utf-8")).get("stage_overrides")),
                 (waiver.EXIT_BAD_ARGS, None))
        check_eq("the part of a line (`TS-14`) is recorded by the writer itself", waiver.run_stage(root.name, "S3", "TS-14", said, "human"), 0)
        BASE.record_stage_acceptance(task, "S3", "dS3")  # E-B11: the person's word passes the plan, not the missing acceptance
        controller.apply("accept", dict(receipt, idempotency_key="accept-S3-again"))
        state = controller.state()
        check_eq("with it, S3 closes", (state["stages"].get("S3") or {}).get("status"), "completed")
        journal = task / "state" / "passed-by-person.jsonl"
        rows = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()
                if line.strip()] if journal.is_file() else []
        check("and the pass is recorded, not swallowed", bool(rows), str(rows)[:200])
        # A journal, not a ledger: the validator runs on every attempt at the commit, so the
        # same pass can be written more than once. What matters is what it says.
        check_eq("against the stage and the dispatch it passed",
                 {(r["stage"], r["dispatch"]) for r in rows}, {("S3", "dS3")})
        check_in("with the block it passed", "TS-14", json.dumps(rows, ensure_ascii=False))
        check_in("and the person's own words", "not testable on this stand",
                 json.dumps(rows, ensure_ascii=False))
        # The record is NOT in the event payload: `event_store.commit` compares a repeated
        # idempotency key against the payload it stored, so a validator that adds a field would
        # turn the next replay of the same request into "reused with different inputs".
        controller.apply("accept", dict(receipt, idempotency_key="accept-S3-again"))
        check("and the same accept can be replayed with its own key", True)

        # 3. S5's own gate, which learned this in run 5 — and wrote the record onto the
        # projected copy of the dispatch instead of the event, so it never survived. The
        # delivery report of that run noticed the key was empty; this is why.
        # The gate binds the plan document too, so put a clean row back before approving:
        # what is under test here is S5's own gate, not the plan contract again.
        BASE.seed_plan(task)
        BASE.accept_stage(controller, task, "S4")
        controller.apply("decision", BASE.bind_gate_a(task, {
            "id": "A", "gate": "A", "action": "approve", "status": "approved",
            "authorization_source": "go on", "scope": ["TC-1"], "source_revision": "src-1",
            "input_revision": "src-1", "idempotency_key": "gate-A"}))
        import hashlib
        evidence = task / "S5.txt"
        evidence.write_text("window", encoding="utf-8")
        s5_apply(controller, {"id": "dS5-author2", "stage": "S5", "role": "qa-automator",
                                      "scope": ["TC-1"], "input_hash": "S5", "budget": {},
                                      "known_paths": {}, "idempotency_key": "dispatch-S5-author2"})
        controller.apply("accept", {"id": "dS5-author2", "status": "accepted", "stage_complete": False,
                                    "evidence_refs": [{"path": evidence.name,
                                                       "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}],
                                    "idempotency_key": "accept-S5-author2"})
        s5_apply(controller, {"id": "dS5-critic2", "stage": "S5", "role": "qa-code-critic",
                                      "scope": ["TC-1"], "input_hash": "S5", "budget": {},
                                      "known_paths": {}, "idempotency_key": "dispatch-S5-critic2"})
        s5 = {"id": "dS5-critic2", "status": "accepted", "stage_complete": True,
              "evidence_refs": [{"path": evidence.name,
                                 "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}],
              "idempotency_key": "accept-S5-critic2"}
        try:
            controller.apply("accept", s5)
            check("S5 does not close without a window record", False)
        except (StateConflict, ValueError) as refusal:
            check_in("and the refusal names the command that builds one", "window_record.py", str(refusal))
        override(task, "S5", "window acceptance record",
                 "No record for this window: the probe receipt cannot be read. Accept it on my word.")
        controller.apply("accept", dict(s5, idempotency_key="accept-S5-critic2-again"))
        rows = [json.loads(line) for line
                in (task / "state" / "passed-by-person.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()]
        kept = [r for r in rows if r["stage"] == "S5"]
        check("the S5 window pass is recorded too", bool(kept), str(rows)[:300])
        check_in("with the words that passed it", "Accept it on my word",
                 json.dumps(kept, ensure_ascii=False))
    finally:
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
        if old_env is not None:
            os.environ["CLAUDE_PROJECT_DIR"] = old_env
        hooklib._PROJECT_ROOT_CACHE = cached
        cleanup(root)

    finish("test_person_word_stages")


if __name__ == "__main__":
    main()
