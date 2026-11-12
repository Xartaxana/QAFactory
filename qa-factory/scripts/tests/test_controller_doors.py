#!/usr/bin/env python3
"""The doors the controller's blocks name are doors that exist, and the first family opens.

`design/controller-blocks.md` gives every one of the 189 blocks a route; for 109 of them the
route is a command the block's own message names. Naming a door is not opening one - that is
how `S3 structured test plan invalid` and `S1 source collection pending/invalid` both came to
advertise `waiver.py --stage ... --block` while the stage stayed shut whatever the person said
(five conductor sessions and $1.94 in TP1-13797 run 5).

Two checks, in the order they pay:

  1. Every command named in the walk EXISTS - an operation the controller knows, or a script in
     the package. Cheap, and it covers all 109 rows at once: a door that is not there cannot
     open, and a rename elsewhere in the factory is caught here instead of in a run.
  2. The `checkpoint` family actually opens: with active work the block fires, after
     `--operation checkpoint` the same request goes through. One family proved end to end is
     worth more than a hundred asserted by reading, and the rest follow the same shape.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import controller as C  # noqa: E402
from controller import Controller, StateConflict  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_controller_state as BASE  # noqa: E402

WALK = harness.PLUGIN_ROOT / "design" / "controller-blocks.md"
OPERATION_RE = re.compile(r"--operation ([a-z_-]+)")
SCRIPT_RE = re.compile(r"`?([a-z][a-z0-9_]*\.py)")


def command_rows() -> list:
    rows = []
    for line in WALK.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| `"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        if len(cells) == 5 and cells[3].strip("`") == "command":
            rows.append((cells[0].strip("`"), cells[2], cells[4]))
    return rows


def main() -> None:
    rows = command_rows()
    check(f"the walk has a `command` route to check ({len(rows)} rows)", len(rows) > 50, str(len(rows)))

    known = set(C.OPERATIONS)
    # M-B6 (CX1-18 I6): the names say the route, not "read"/"write", and the old names are NOT aliases.
    check("M-B6: READ_OPERATIONS and WRITE_OPERATIONS are gone, not aliased",
          not hasattr(C, "READ_OPERATIONS") and not hasattr(C, "WRITE_OPERATIONS"))
    check("M-B6: `recover` is routed, `initialize` is applied, OPERATIONS is both",
          "recover" in C.ROUTED_OPERATIONS and "initialize" in C.APPLY_OPERATIONS
          and C.OPERATIONS == C.ROUTED_OPERATIONS + C.APPLY_OPERATIONS
          and not set(C.ROUTED_OPERATIONS) & set(C.APPLY_OPERATIONS))
    # `gate-decision` and friends are routed operations that PRINT a request; the CLI takes both.
    unknown_ops, missing_scripts = [], []
    for where, block, way in rows:
        for operation in OPERATION_RE.findall(way):
            if operation not in known:
                unknown_ops.append((block[:50], operation))
        for script in SCRIPT_RE.findall(way):
            if not (harness.SCRIPTS / script).is_file():
                missing_scripts.append((block[:50], script))
    check("every operation a block names is one the controller knows", not unknown_ops,
          "; ".join(f"{block}: --operation {op}" for block, op in unknown_ops[:6]))
    check("and every script a block names is in the package", not missing_scripts,
          "; ".join(f"{block}: {name}" for block, name in missing_scripts[:6]))

    # K1 (F-5): the problems a request collects and `_raise_all` refuses whole are blocks too, so their
    # doors are looked up with the rest - the Gate A receipt rows name `--operation gate-inputs`.
    receipt_rows = [(block, way) for _, block, way in rows if block.startswith("Gate A receipt must bind")]
    check("the collected Gate A receipt problems are walked, each with a door the controller knows",
          len(receipt_rows) >= 4 and all(OPERATION_RE.search(way) and
                                         OPERATION_RE.search(way).group(1) in known for _, way in receipt_rows),
          str(receipt_rows[:2]))
    # How many of the 109 name a door this test can even look up. The rest say what to do in
    # words ("accept the successor first"), which is a route and not a command - counted, not
    # judged, so the number moves when somebody makes a row more precise.
    looked_up = sum(1 for _, _, way in rows if OPERATION_RE.search(way) or SCRIPT_RE.search(way))
    print(f"  (of {len(rows)} `command` rows, {looked_up} name a command this test resolves; "
          f"{len(rows) - looked_up} name the move in words)")
    check("most of the command rows name something lookable-up", looked_up >= len(rows) // 3,
          f"{looked_up} of {len(rows)}")

    # --- the checkpoint family, end to end ----------------------------------------------------
    root = harness.temp_dir("qa-controller-doors-")
    import hooklib
    cached, hooklib._PROJECT_ROOT_CACHE = hooklib._PROJECT_ROOT_CACHE, None
    old_env = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = str(root)
    try:
        (root / "qa-factory").mkdir(parents=True, exist_ok=True)
        (root / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
        task = root / "qa-factory" / "artifacts" / root.name
        (task / "work").mkdir(parents=True)
        controller = Controller(task)
        controller.apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1",
                                        "known_paths": {"root": str(task)}, "idempotency_key": "init"})
        BASE.accept_stage(controller, task, "S0")
        controller.apply("dispatch", {"id": "d-live", "stage": "S1", "role": "qa-scout",
                                      "scope": ["TC-1"], "input_hash": "ctx", "budget": {},
                                      "known_paths": {}, "idempotency_key": "d-live"})
        revise = {"scope": ["TC-1", "TC-2"], "plan_revision": "plan-2",
                  "reason": "the person added a case at the gate",
                  "idempotency_key": "revise-1"}
        try:
            controller.apply("revise_plan", dict(revise))
            check("active work blocks a scope revision", False)
        except (StateConflict, ValueError) as refusal:
            check_in("and the block names the door", "checkpoint active work", str(refusal))

        controller.apply("checkpoint", {"id": "d-live", "status": "paused",
                                        "checkpoint": {"completed": [], "next": "resume the scout"},
                                        "reason": "the person is revising the scope",
                                        "idempotency_key": "cp-1"})
        controller.apply("revise_plan", dict(revise, idempotency_key="revise-2"))
        state = controller.state()
        check_eq("after the door the same request goes through",
                 sorted(state.get("scope") or []), ["TC-1", "TC-2"])
        check_eq("and the dispatch is where the door left it",
                 (state["dispatches"]["d-live"] or {}).get("status"), "paused")
    finally:
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
        if old_env is not None:
            os.environ["CLAUDE_PROJECT_DIR"] = old_env
        hooklib._PROJECT_ROOT_CACHE = cached
        harness.cleanup(root)

    harness.finish("test_controller_doors")


if __name__ == "__main__":
    main()
