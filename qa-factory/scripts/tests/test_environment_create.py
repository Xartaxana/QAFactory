"""FB-23: an explicitly authorized NEW environment plans `create`; nothing less does.

Before the fix `plan_environment` ran the observed-runtime identity rule unconditionally, so a stand that does
not exist yet (`observed_runtime.state == "absent"`) was refused with "observed_runtime source_revision is
required" and could never be created through the factory. The guarded branch takes verified absence bound to
THIS environment, a complete target, a `create: true` authorization bound to the environment and the target
revision, and the adapter's `actions.create` argv - and an unknown EXISTING runtime is still refused (I2).
Expectations come from the requirement (FB-23 and t-958 section 5, edges 6-8), not from the code's output.
"""
import copy
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, check_in, finish  # noqa: E402
from test_environment_preparation import request as existing_request, runtime, step  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from environment_preparation import PreparationError, execute_environment, plan_environment  # noqa: E402


def absent(**changes) -> dict:
    row = {"state": "absent", "environment_id": "qa", "absence_verified": True,
           "observed_at": "2026-10-07T00:00:00Z", "evidence_refs": ["absence.json"], "resources": []}
    row.update(changes)
    return row


def request(root: Path = Path("."), **changes) -> dict:
    """The existing-environment request of test_environment_preparation, turned into a create request."""
    req = existing_request(root)
    req["observed_runtime"] = absent()
    req["authorization"]["create"] = True
    req["actions"]["create"] = [step("create")]
    req.update(changes)
    return req


def refusal(req: dict) -> str:
    """The PreparationError's text, or "" when the plan was accepted."""
    try:
        plan_environment(req)
    except PreparationError as error:
        return str(error)
    return ""


def planning_cases() -> None:
    req = request()
    plan = plan_environment(req)
    check_eq("verified absence + bound create authority + create argv plans `create`",
             (plan["status"], plan["action"]), ("prepared", "create"))
    check_eq("the create plan carries the adapter's own argv", plan["commands"], req["actions"]["create"])
    check_eq("a created stand is neither build-compatible nor source-mounted nor rolled back",
             (plan["build_compatible"], plan["source_mounted"], plan["automatic_rollback"]), (False, False, False))
    check("the create plan fingerprints both runtimes",
          len(plan.get("observed_fingerprint", "")) == 64 and len(plan.get("target_fingerprint", "")) == 64)

    # Edge 6: absence cannot hide existing, unverified, foreign or undated evidence.
    for changes in ({"resources": ["other-container"]}, {"resources": None}, {"absence_verified": False},
                    {"absence_verified": "true"}, {"environment_id": "other"}, {"environment_id": None},
                    {"evidence_refs": []}, {"evidence_refs": [""]}, {"evidence_refs": [7]}, {"evidence_refs": "a.json"},
                    {"observed_at": ""}, {"observed_at": 123}, {"observed_at": None}):
        req = request()
        req["observed_runtime"].update(changes)
        check_in(f"absence cannot hide: {changes}", "verified absence", refusal(req) or "accepted")
    for missing in ("resources", "absence_verified", "environment_id", "observed_at", "evidence_refs"):
        req = request()
        del req["observed_runtime"][missing]
        check_in(f"absence evidence without `{missing}` is refused", "verified absence", refusal(req) or "accepted")

    # Edge 6: only the exact word `absent` opens the branch; anything else is an existing, unidentified runtime.
    for state in ("Absent", "unknown", "", None, "absent "):
        req = request()
        req["observed_runtime"]["state"] = state
        check_in(f"state {state!r} goes through the identity rule, not the create branch",
                 "source_revision is required", refusal(req) or "accepted")
    req = request()
    req["observed_runtime"] = {"source_revision": "unknown"}
    check_in("an unknown EXISTING runtime is still refused by the identity rule",
             "source_revision is required", refusal(req) or "accepted")

    # Edge 7: the authorization is explicit, bound, and separate.
    for changes in ({"create": False}, {"create": "yes"}, {"create": 1}, {"environment_id": "other"},
                    {"target_source_revision": "other"}, {"ref": ""}):
        req = request()
        req["authorization"].update(changes)
        plan = plan_environment(req)
        check_eq(f"create needs explicit authority bound to environment and revision: {changes}",
                 (plan["status"], plan["action"]), ("blocked", "create"))
    req = request()
    del req["authorization"]["create"]
    check_eq("an authorization without `create` (the usual mutation one) does not create",
             plan_environment(req)["status"], "blocked")
    for actions in ({"rebuild": [step("rebuild")]}, {"create": []}, {"create": "adapter"}, {}):
        req = request()
        req["actions"] = actions
        check_eq(f"no usable actions.create blocks the plan rather than borrowing another action: {list(actions)}",
                 (plan_environment(req)["status"], plan_environment(req)["action"]), ("blocked", "create"))
    existing = existing_request(Path("."))
    existing["authorization"]["create"] = True
    existing["actions"]["create"] = [step("create")]
    check_eq("`create: true` for an environment that EXISTS changes nothing: the plan is the ordinary one",
             plan_environment(existing)["action"], plan_environment(existing_request(Path(".")))["action"])

    # Positional invariants: the branch stands AFTER the topology check and BEFORE `_facts(observed)`.
    req = request()
    req["topology"] = {"status": "unresolved"}
    req["observed_runtime"]["absence_verified"] = False  # evidence that would be refused...
    plan = plan_environment(req)  # ...never read, because an incompatible topology blocks first
    check_eq("an unresolved topology blocks before the create branch is even judged", (plan["status"], plan["action"]),
             ("blocked", None))
    req = request()
    check("a runtime that does not exist has no compatibility facts to demand (none given, none asked)",
          "compatibility" not in req["observed_runtime"] and plan_environment(req)["status"] == "prepared")
    req = request()
    req["target_runtime"] = runtime("new")
    req["target_runtime"]["compatibility"]["runtime"] = "unknown"
    check_in("the target still needs complete compatibility facts", "unknown compatibility facts",
             refusal(req) or "accepted")
    req = request()
    req["target_runtime"]["source_revision"] = "unknown"
    check_in("the target still needs a source revision", "target_runtime source_revision is required",
             refusal(req) or "accepted")
    check_eq("the request is not changed by planning", request(), request())


def execution_cases() -> None:
    """One whole run: the create action runs through the durable job and the five probes, and the job is ready."""
    with tempfile.TemporaryDirectory() as td:
        req = request(Path(td))
        before = copy.deepcopy(req)
        job = execute_environment(req, Path(td), poll_seconds=.01)
        check_eq("a create request runs to a ready job", job["status"], "ready")
        check_eq("...whose action is `create`", job.get("action"), "create")
        check_eq("...the first step is the adapter's create command", job["steps"][0]["name"], "create")
        check_eq("the request is not changed by the run", req, before)

    with tempfile.TemporaryDirectory() as td:
        req = request(Path(td))
        req["authorization"]["create"] = False
        job = execute_environment(req, Path(td), poll_seconds=.01)
        check_eq("without the authorization the job is blocked and no step ran",
                 (job["status"], job.get("steps") or []), ("blocked", []))


def main() -> None:
    planning_cases()
    execution_cases()
    finish("test_environment_create")


if __name__ == "__main__":
    main()
