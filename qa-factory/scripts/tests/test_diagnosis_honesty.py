"""The 2026-09-20 doctor run and the TP2-2520 feedback, as regressions.

Every case here is a state the factory reported wrongly to a person: a dropped network sent
as a credentials errand, a finished stage un-finishing itself, a waived requirement still
blocking delivery, a checkpoint recommended after the work that replaced it was accepted, an
output contract no producer could satisfy, and a git configuration a role changed on someone
else's machine.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import check, check_eq, check_in, finish  # noqa: E402


def stage_is_monotonic() -> None:
    """A legitimate extra dispatch with stage_complete:false must not un-complete S5."""
    from controller import set_stage
    state = {"stages": {"S5": {"status": "completed", "dispatch_id": "d1"}}}

    set_stage(state, "S5", {"status": "running", "dispatch_id": "d2"})
    check_eq("a later dispatch does not un-complete a finished stage",
             state["stages"]["S5"]["status"], "completed")
    check_eq("the later work is still visible",
             state["stages"]["S5"].get("active_dispatch_id"), "d2")

    set_stage(state, "S5", {"status": "pending", "dispatch_id": "d2", "reason": "quality gate"})
    check_eq("accepting that work with stage_complete:false keeps the stage completed",
             state["stages"]["S5"]["status"], "completed")

    state["stages"]["S4"] = {"status": "running", "dispatch_id": "d3"}
    set_stage(state, "S4", {"status": "pending", "dispatch_id": "d3"})
    check_eq("a stage that was never completed still moves freely",
             state["stages"]["S4"]["status"], "pending")


def superseded_checkpoint_is_not_recommended() -> None:
    """Corrective work that was accepted retires the checkpoint it replaced."""
    from controller import Controller
    state = {
        "environment_jobs": [],
        "dispatches": {
            "d1": {"id": "d1", "stage": "S5", "status": "incomplete", "reason": "ran out of turns"},
            "d2": {"id": "d2", "stage": "S5", "status": "accepted"},
        },
        "window_counters": {}, "window_context_percent": None, "stages": {}, "decisions": {},
        "revision": 1, "scope": [], "gates": {},
    }
    action = Controller._next_action_for_state(state)
    check("a checkpoint replaced by later accepted work is not recommended",
          action.get("action") != "resume_checkpoint")

    state["dispatches"]["d2"]["status"] = "running"
    action = Controller._next_action_for_state(state)
    check_eq("while that work is still running, the running dispatch is what matters",
             action.get("action"), "wait_existing_job")

    state["dispatches"].pop("d2")
    action = Controller._next_action_for_state(state)
    check_eq("an unreplaced stopped dispatch is still recommended",
             action.get("action"), "resume_checkpoint")


def waiver_closes_the_ledger_row() -> None:
    """A requirement a person waived at a gate stops blocking delivery — and says so."""
    from ledger import apply_waiver
    waivers = {"R-1": {"gate": "A", "reason": "accepted by the team"},
               "R-2": {"gate": "B", "reason": "accepted by the team"}}

    entry = apply_waiver({"ref": "TS-1", "state": "not_executed:no result", "detail": "no result"},
                         {"requirements": ["R-1", "R-2"]}, waivers)
    check_eq("a fully waived row is waived", entry["state"], "waived:not_executed:no result")
    check_in("the row says whose decision closed it", "gate A/B waiver", entry["detail"])
    check_in("and still says what was actually observed", "no result", entry["detail"])

    partial = apply_waiver({"ref": "TS-2", "state": "not_executed:no result", "detail": "d"},
                           {"requirements": ["R-1", "R-9"]}, waivers)
    check_eq("a row with one unwaived requirement still owes its evidence",
             partial["state"], "not_executed:no result")

    import contract as C
    check("a waived row is not in the blocking set",
          C.ledger_state_prefix(entry["state"]) == "waived")


def reachability_outranks_credentials() -> None:
    """An unreachable host is never reported as an access problem."""
    import vcs_evidence

    verdict = vcs_evidence.unreachable_readiness("githost.example", {"detail": "no answer within 4s"})
    check_eq("an unreachable host is unknown, not missing", verdict["status"], "unknown")
    check_eq("and it is not the person's fault", verdict["owner"], "factory")
    check_in("the note says access was neither verified nor denied", "NOT denied", verdict["note"])
    # The rule is about blame, not vocabulary: naming SSH as UNTOUCHED is the "what still
    # works" half a person needs. What must never appear is an invitation to go and check
    # access that was never in question.
    for word in ("credential", "token", "authenticat"):
        check(f"the note never raises {word}", word.lower() not in verdict["note"].lower())
    check("SSH is mentioned only as unaffected", "untouched by this" in verdict["note"])
    check_in("the first step is the cheap one", "VPN", verdict["remedy"]["steps"][0])
    check("a second step covers a VPN that is already on", len(verdict["remedy"]["steps"]) > 1)

    check_eq("a name that does not resolve is classified as unreachable",
             vcs_evidence.classify_failure("dial tcp: lookup githost: no such host"), "host_unreachable")
    check_eq("a timeout is transient, and retried",
             vcs_evidence.classify_failure("request timed out"), "network_transient")
    check_eq("anything else is a local configuration problem",
             vcs_evidence.classify_failure("unexpected glab output"), "cli_config_error")


def denial_is_still_a_denial() -> None:
    """A host that answered and refused keeps its verdict, and gets a complete remedy."""
    import vcs_evidence
    verdict = vcs_evidence.failed_readiness("unauthenticated", "githost.example")
    check_eq("a refusal is missing", verdict["status"], "missing")
    check_eq("and it is the person's to fix", verdict["owner"], "user")
    steps = verdict["remedy"]["steps"]
    check_in("a route the factory can take itself comes first", "connector", steps[0])
    check("the token step says where to get it and with what rights",
          any("read_api" in s for s in steps))
    check_in("the cost names what still works", "SSH", verdict["remedy"]["blocks"])
    check_in("and does not overstate it", "pinned base/head", verdict["remedy"]["blocks"])


def every_gap_carries_a_remedy() -> None:
    """No capability may be reported as a problem without saying what to do about it."""
    import readiness
    for status in (readiness.MISSING, readiness.UNKNOWN, readiness.NOT_CONFIGURED):
        entry = readiness.cap(status, "user", "something is not right")
        check(f"{status} carries a remedy", isinstance(entry.get("remedy"), dict))
        check(f"{status} remedy names a step", bool(entry["remedy"].get("steps")))
    ok = readiness.cap(readiness.OK, "factory", "all good")
    check("an ok capability needs no remedy", "remedy" not in ok)


def witness_is_never_invented() -> None:
    """The reducer states what the blocks show, and stays silent when they show nothing."""
    from finalize_task import _witness
    evidence = [{"summary": "qa-factory/artifacts/T-1/evidence/sanity-1.json"}]
    text = _witness(evidence, "passed", {"passed": 3})
    check_in("the witness names the real summary", "sanity-1.json", text)
    check_in("and what it added up to", "passed=3", text)
    check_eq("no evidence means no witness, not a sentence saying so",
             _witness([], "not_executed", {}), "")


def git_config_is_not_the_run_s_to_change() -> None:
    import guard_pre_tool as guard
    blocked = guard._blocked(guard.git_config_check,
                             {"tool_name": "Bash",
                              "tool_input": {"command": "git config --global safe.directory C:/x"}},
                             {})
    check("the exact call a role made on 2520 is blocked", bool(blocked))
    allowed = guard._blocked(guard.git_config_check,
                             {"tool_name": "Bash",
                              "tool_input": {"command": "git config --get remote.origin.url"}}, {})
    check_eq("reading the configuration is still allowed", allowed, None)


def journal_vocabulary_covers_what_the_factory_writes() -> None:
    """A6 reported an unknown event that only the factory itself ever wrote."""
    from log_append import EVENTS
    check("handoff_incomplete is a known event", "handoff_incomplete" in EVENTS)


def control_plane_is_not_sealed() -> None:
    """A5 used to report the orchestrator's own files as violations nobody could fix."""
    from audit_factory import CONTROL_PLANE
    for name in ("pipeline.json", "checkpoint.json", "controller.json", "events.jsonl"):
        check(f"{name} is exempt from the seal", name in CONTROL_PLANE)
    check("a story's evidence is still sealed", "run-report.json" not in CONTROL_PLANE)


def main() -> None:
    stage_is_monotonic()
    superseded_checkpoint_is_not_recommended()
    waiver_closes_the_ledger_row()
    reachability_outranks_credentials()
    denial_is_still_a_denial()
    every_gap_carries_a_remedy()
    witness_is_never_invented()
    git_config_is_not_the_run_s_to_change()
    journal_vocabulary_covers_what_the_factory_writes()
    control_plane_is_not_sealed()
    finish("test_diagnosis_honesty")


if __name__ == "__main__":
    main()
