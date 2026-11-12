#!/usr/bin/env python3
"""A receipt without an agent, and a rework nobody could spell.

TP1-15045 ended its morning like this: `--operation dispatch` wrote the S5 receipt, the
hook on `Agent` then refused the call, and the story was left with a `running` dispatch no
agent was doing. `next` answered `wait_existing_job`, `cancel_allowed: false`, "Polling
timeout ... do not authorize cancellation" — no way forward for the orchestrator and none
for the person either.

Earlier the same morning three attempts to dispatch a rework were refused in a row: a bare
`KeyError` printed as `{"error": "'supported'"}`, then "unsupported purpose; regression is
user-owned" for a free-text purpose, then a `SendMessage` to an agent id from a session that
no longer existed. Rework is an operation here, and every refusal names what it wants.
"""
# Shared helpers of test_controller_rework.py, split by tools/test_split.py (TD-11c).
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, s5_apply
sys.path.insert(0, str(SCRIPTS))
from controller import Controller
from event_store import StateConflict  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_controller_state as BASE  # noqa: E402
import test_controller_rework_scope as SCOPED  # noqa: E402  (plan_row/gate_a_task fixtures)


AUTOMATOR = "S5-qa-automator-1"


def at_s5(root):
    """The shape the story was stuck in: gate A approved, an S5 receipt, no agent."""
    controller = SCOPED.gate_a_task(root)
    s5_apply(controller, {"id": AUTOMATOR, "stage": "S5", "role": "qa-automator",
                                  "scope": ["TC-1"], "input_hash": "s5-input", "budget": {},
                                  "known_paths": {"root": str(root)},
                                  "idempotency_key": "dispatch:" + AUTOMATOR})
    return controller


def host_receipt(root, **fields):
    path = root / "qa-factory" / "state" / "host-dispatches" / "one.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fields), encoding="utf-8")


# --- a repair carries its binding, and a continuation keeps the original request ---------------
#
# A rework request named cases and a reason, and the role repaired whatever CaseVersion it
# happened to read (a stale link on the accepted receipt). And when such a repair stopped, the
# retry and relaunch packets copied four fields of the dispatch RECORD: the binding, the cause,
# the lineage and the mandatory `reason` were gone - and the record's own `reason` is not the
# request's (a checkpoint and the liveness repair both rewrite it), so copying it from there
# would have carried the wrong sentence.

STALE, CANONICAL = "cv_e791cbef9b7195262a80", "cv_c098ad9b0d4075cde6dc"


DESIGNER = "S4-qa-case-designer-1"


def pin(root, *links):
    path = root / "state" / "story-case-links.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"links": list(links)}), encoding="utf-8")


def accept_prerequisites(controller, root, scope):
    """S0-S3 accepted over THIS fixture's scope. `BASE.accept_stage` dispatches TC-1 whatever the
    story's scope is, so a fixture of other cases had to widen its own scope to carry it."""
    for stage in ("S0", "S1", "S2", "S3"):
        if stage == "S3":
            BASE.seed_plan(root, [SCOPED.plan_row(1, "automate")])
        controller.apply("dispatch", {"id": "d" + stage, "stage": stage, "role": "qa-worker",
                                      "scope": list(scope), "input_hash": stage, "budget": {},
                                      "known_paths": {}, "idempotency_key": "dispatch-" + stage})
        BASE.record_stage_acceptance(root, stage)  # E-B11 (no-op for S0/S1); the qa-worker stub has no author dispatch
        controller.apply("accept", {"id": "d" + stage, "status": "accepted", "stage_complete": True,
                                    "evidence_refs": [BASE.evidence_ref(root, stage + ".txt", stage)],
                                    "idempotency_key": "accept-" + stage})


def designer_story(root, scope=("TC-082", "TC-099"), links=None):
    """A story whose S4 designer was accepted over the scope, the pin file naming the CURRENT
    versions and the accepted receipt still carrying a stale one for TC-082."""
    controller = Controller(root)
    controller.apply("initialize", {"scope": list(scope), "source_revision": "src-1",
                                    "known_paths": {"root": str(root)}, "idempotency_key": "init"})
    accept_prerequisites(controller, root, scope)
    pin(root, *(links if links is not None else (
        {"case_id": "TC-082", "version": CANONICAL}, {"case_id": "TC-099", "version": "cv_other"})))
    controller.apply("dispatch", {"id": DESIGNER, "stage": "S4", "role": "qa-case-designer",
                                  "scope": list(scope), "input_hash": "design-input",
                                  "known_paths": {"root": str(root)}, "budget": {"requests": 40},
                                  "case_version_links": [{"case_id": "TC-082", "version": STALE}],
                                  "idempotency_key": "d-designer"})
    # No `stage_complete`: the designer is not the role that closes S4 (the critic is), so the
    # stage stays open - and only an open stage is startable again after a round never started.
    controller.apply("accept", {"id": DESIGNER, "status": "accepted",
                                "evidence_refs": [BASE.evidence_ref(root, "designer.txt")],
                                "idempotency_key": "a-designer"})
    return controller


def refusal(call):
    try:
        call()
    except (ValueError, StateConflict) as exc:
        return str(exc)
    return ""


# --- t-675 (C1-4a, F6): a rework that carries a PERSON's words sets aside what runs after it ------------------------
#
# Staying monotonic (`set_stage`) meant a person's "the automation needs changes" re-ran the automator and nothing
# after it: S6-S8 stayed `completed` over code that was about to change, and a gate B decision stayed `approved`.
# The controller now writes `rerun_after` on the rework request - only when the reason IS a person's words
# (`--words-file`) - and its replay lowers the named stages, stales the named reviews and gate decisions. A reason
# typed by code (`--reason`: the driver's repairs, the conductor's refusal repairs) is the factory's own finding and
# never stales a stage it did not name. Every test below runs on the controller alone (the CLI where it matters).

WORDS = "the export test checks only the status code\r\nplease check the body too\r\n"


def story_to_s8(root):
    """S0-S8 accepted, gate A approved, gate B not asked: the story as it waits at gate B."""
    controller = SCOPED.gate_a_task(root)
    for number in range(5, 9):
        BASE.accept_stage(controller, root, f"S{number}")
    return controller


def words_file(root):
    path = root / "words.txt"
    path.write_bytes(WORDS.encode("utf-8"))
    return path


def settle(controller, root, request):
    """The rework is accepted the way the stage's non-closing role is: the stage stays open."""
    controller.apply("accept", {"id": request["id"], "status": "accepted", "stage_complete": False,
                                "evidence_refs": [BASE.evidence_ref(root, request["id"] + ".txt", request["id"])],
                                "idempotency_key": "accept-" + request["id"]})


def redo(controller, root, stage, identifier):
    """A stage that runs again: one fresh dispatch of the fixture's worker, accepted as complete."""
    controller.apply("dispatch", {"id": identifier, "stage": stage, "role": "qa-worker", "scope": ["TC-1"],
                                  "input_hash": identifier, "budget": {}, "known_paths": {},
                                  "idempotency_key": "dispatch-" + identifier})
    BASE.record_stage_acceptance(root, stage)  # E-B11 (no-op outside S2-S4); the qa-worker stub has no author dispatch
    controller.apply("accept", {"id": identifier, "status": "accepted", "stage_complete": True,
                                "evidence_refs": [BASE.evidence_ref(root, identifier + ".txt", identifier)],
                                "idempotency_key": "accept-" + identifier})
