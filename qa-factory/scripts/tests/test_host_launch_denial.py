"""FB-24 (TP2-2406): a refused native launch is written down, without closing a live worker.

`worker_lifecycle.guard` refused S5-qa-automator-1's spawn (host unverified) before `inject_context` could note the
denial, so the controller's record stayed `running` with no agent and no receipt and recovery could only say
"liveness unknown". The refusal now writes the story's `dispatch-denials.jsonl` row for the one unlaunched dispatch of
that role. Which dispatch (t-955 M-1, t-969 F-2): the one the event NAMES, when it is `running` of this role with no
`agent_id` and no `returned_at` - and when it is not, NOTHING (the orchestrator meant that dispatch, never another);
an event naming none charges nobody by name: exactly ONE such dispatch of the role gives a row with its stage and
role and no dispatch id, which the controller's `_denial_times` owns. A receipt of the task and role that is still
active (`binding_is_active`: terminal or settled receipts do not count, every doubt does) silences the line - a
duplicate-launch refusal must never settle the worker that owns the receipt.
"""
import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
from worker_lifecycle import guard  # noqa: E402

TICKET = "TP2-2406"
ONE = "S5-qa-automator-1"
TWO = "S5-qa-automator-2"


def dispatch(ident, role="qa-automator", status="running", **fields):
    record = {"id": ident, "stage": "S5", "role": role, "status": status}
    record.update(fields)
    return record


def refused(root: Path, prompt=None, receipts=()) -> int:
    """The guard's exit code against an unverified host, with the given host receipts on disk."""
    folder = root / "qa-factory/state/host-dispatches"
    folder.mkdir(parents=True, exist_ok=True)
    for number, receipt in enumerate(receipts):
        name = hashlib.sha256(str(number).encode()).hexdigest() + ".json"
        (folder / name).write_text(json.dumps(dict(
            {"task_id": TICKET, "agent_type": "qa-automator", "status": "running"}, **receipt)), encoding="utf-8")
    tool_input = {"task_name": "qa_automator__tp2_2406"}
    if prompt is not None:
        tool_input["prompt"] = prompt
    with patch("hooklib.project_root", return_value=root), \
            patch("stage_guard.requested_ticket", return_value=TICKET), \
            patch("host_capabilities.inspect", return_value={"story_ready": False}):
        try:
            guard({"tool_name": "spawn_agent", "tool_input": tool_input})
        except SystemExit as exit_:
            return exit_.code
    return 0


def rows_of(state: Path) -> list:
    denial = state / "dispatch-denials.jsonl"
    return [json.loads(line) for line in denial.read_text(encoding="utf-8").splitlines() if line.strip()] \
        if denial.exists() else []


def case(label, dispatches, prompt=None, receipts=(), expect=None):
    """Run one case; `expect` is None (nothing written) or the dispatch id the row must name ("" = a row naming none)."""
    root = temp_dir("qa-factory-launch-denial-")
    state = root / "qa-factory/artifacts" / TICKET / "state"
    state.mkdir(parents=True)
    (root / "qa-factory/config.json").write_text("{}", encoding="utf-8")
    if dispatches is not None:
        (state / "controller.json").write_text(json.dumps({"dispatches": {d["id"]: d for d in dispatches}}),
                                               encoding="utf-8")
    try:
        check_eq(f"launch denial ({label}): the spawn is still refused", refused(root, prompt, receipts), 2)
        rows = rows_of(state)
        if expect is None:
            check_eq(f"launch denial ({label}): nothing is written", rows, [])
            return
        check_eq(f"launch denial ({label}): one row", len(rows), 1)
        row = rows[0]
        check_eq(f"launch denial ({label}): the row names {expect or 'no dispatch'}", row["dispatch_id"], expect or None)
        check_eq(f"launch denial ({label}): the row names the stage and the role", (row["stage"], row["role"]),
                 ("S5", "qa-automator"))
        check(f"launch denial ({label}): the row carries the refusal", "unverified" in row["reason"])
    finally:
        cleanup(root)


def main() -> None:
    naming = lambda ident: f"You are qa-automator.\nTicket: {TICKET}\nDispatch id: {ident}\n"  # noqa: E731
    # the unique unlaunched dispatch, the event naming none (the desktop's prompt is opaque): a row with no dispatch id
    case("unlaunched", [dispatch(ONE)], expect="")
    case("the fallback never names a dispatch (the controller's rule owns the row)", [dispatch(ONE)],
         prompt="an opaque message with no id", expect="")
    # the fallback needs exactly ONE candidate
    case("two running, none named", [dispatch(ONE), dispatch(TWO)])
    case("launched", [dispatch(ONE, agent_id="worker-1")])
    case("returned", [dispatch(ONE, returned_at=1.0)])
    case("other role", [dispatch("S5-qa-code-critic-1", role="qa-code-critic")])
    case("a candidate without a role", [{"id": ONE, "stage": "S5", "status": "running"}])
    case("no state", None)
    # the dispatch the event names: first, and only when it passes the test
    case("named, two running", [dispatch(ONE), dispatch(TWO)], prompt=naming(TWO), expect=TWO)
    case("named, one running", [dispatch(ONE)], prompt=naming(ONE), expect=ONE)
    case("named, but it carries an agent_id (another unlaunched dispatch stands beside it)",
         [dispatch(ONE, agent_id="worker-1"), dispatch(TWO)], prompt=naming(ONE))
    case("named, but it returned", [dispatch(ONE, returned_at=1.0), dispatch(TWO)], prompt=naming(ONE))
    case("named, but it is not running", [dispatch(ONE, status="accepted"), dispatch(TWO)], prompt=naming(ONE))
    case("named dispatch of another role (a unique automator dispatch stands beside it)",
         [dispatch("S5-qa-code-critic-1", role="qa-code-critic"), dispatch(ONE)], prompt=naming("S5-qa-code-critic-1"))
    case("named dispatch the controller does not know", [dispatch(ONE)], prompt=naming("S5-qa-automator-9"))
    # a receipt of the task and role
    case("an active receipt binds the role", [dispatch(ONE)],
         receipts=[{"dispatch_id": ONE}])
    case("a receipt naming no dispatch binds it too (every doubt keeps it active)", [dispatch(ONE)],
         receipts=[{"dispatch_id": ""}])
    case("a receipt of a story the controller has no record of (doubt)", [dispatch(ONE)],
         receipts=[{"dispatch_id": "S5-qa-automator-77"}])
    case("a terminal receipt of the role does not silence the line", [dispatch(ONE)],
         receipts=[{"dispatch_id": ONE, "status": "terminal"}], expect="")
    case("a running receipt of a dispatch the controller settled does not silence it",
         [dispatch(ONE), dispatch("S5-qa-automator-0", status="accepted")],
         receipts=[{"dispatch_id": "S5-qa-automator-0"}], expect="")
    case("a receipt of another role does not matter", [dispatch(ONE)],
         receipts=[{"dispatch_id": "S5-qa-code-critic-1", "agent_type": "qa-code-critic"}], expect="")
    finish("test_host_launch_denial")


if __name__ == "__main__":
    main()
