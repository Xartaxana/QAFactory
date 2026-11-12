#!/usr/bin/env python3
"""`story_step.py materialize` and the `finish` refusal of a declared halt (CX1-14, t-1139; TP2-2406 S3-3, 15.10.2026).

Part 1 - `materialize`: the brief, the handover form and the launch card of a dispatch the controller committed OUTSIDE
`start` (a `controller.py --operation rework` packet), written from that packet. The incident: `story_step.py start --id
S3-qa-test-strategist-3` was refused ("idempotency key reused with different inputs", no field, no value) because `start`
builds a FRESH request; `where` answered `wait_start ... ask again` for 7000 s; the brief a `start` could have written would
not have held the plan rows TS-1..TS-4 and TS-8 the packet carried. Each check names the ONE mutation that kills it.

  K1 a rework packet through the CLI: files carry the packet's identity; log and state byte-identical; `where` -> launch
  K2 a normal `start` is byte-identical to the rendering main produced (the golden was taken from main before the change)
  K3 idempotence; a differing card is refused and never replaced
  K4 refusals with field, value and door; an adversarial battery of ids
  K5 the doors: `wait_start` for a packet outside `start` (and NOT for a `start` packet), `start --id` names the door once,
     N-2 only for a scope-only difference (F-3)
  K6 the changelog fragment
  K7 the fix round of the critic t-022: identity fields, driver story refusal, derive steps, the S5 settle door

Part 2 - a declared halt is never `accepted`:
  K8 form / digest / both x every flag -> exit 2, tree byte-identical
  K9 the halt is read before the form check and after the decision; F-4 (a); E6
  K10 the reader's battery (E1-E6)
  K11 the driver hears a form halt once, before the resume (F-2 (b)); the scout stays on the S1 road (B-1, E21); the twins
      `resume_role` and `_finish_saved_result` (B-2)
  K12 the no-change note
  K13 the door table of a halt refusal and of `decide` (F-1 (b), F-4); the temporal edge
"""
import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import launch_card  # noqa: E402
import story_step  # noqa: E402
from controller import Controller  # noqa: E402
from event_store import EventStore, StateConflict  # noqa: E402

import test_controller_rework_scope as SCOPED  # noqa: E402  (plan_row fixture)
import test_controller_state as BASE  # noqa: E402  (accept_stage / seed_plan / evidence_ref fixtures)
import test_story_step as STEP  # noqa: E402  (open_story, s4_story, s5_window_story, run_decide)

TICKET = "QA-M"
PARENT, CHILD = "S3-qa-test-strategist-1", "S3-qa-test-strategist-2"
PARENT_HASH = "plan-input-hash"
REASON = "cover R-11 and R-12 of the plan"
CHANGELOG_FRAGMENT = harness.PLUGIN_ROOT / "changelog.d" / "codex-1-cx1-14-materialize-and-halt.md"


# --- fixtures ---------------------------------------------------------------------------------------------

def snapshot(root):
    """Every file under `root`: path -> (sha256, mtime_ns) - what a refused or idempotent run must not change."""
    return {str(p.relative_to(root)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*")) if p.is_file()}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def desktop_story(prefix="qa-mat-"):
    """A desktop story past S0 (no card, no brief yet): (root, env, task, controller)."""
    root = harness.temp_project(prefix)
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    env.pop(launch_card.RUN_MODE_ENV, None)
    harness.use_project(root)
    task = STEP.open_story(root, env, TICKET)
    pipeline = json.loads((task / "pipeline.json").read_text(encoding="utf-8"))
    pipeline["run_mode"] = {"mode": "desktop"}
    (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
    return root, env, task, Controller(task)


def accepted_s3(prefix="qa-mat-"):
    """A story whose S3 qa-test-strategist dispatch is ACCEPTED on `PARENT_HASH` over a three-row plan - what a
    rework is built from."""
    root, env, task, controller = desktop_story(prefix)
    BASE.accept_stage(controller, task, "S1")
    BASE.accept_stage(controller, task, "S2")
    BASE.seed_plan(task, [SCOPED.plan_row(number, "automate") for number in (1, 2, 3)])
    controller.apply("dispatch", {"id": PARENT, "stage": "S3", "role": "qa-test-strategist", "scope": [],
                                  "input_hash": PARENT_HASH, "budget": {},
                                  "known_paths": {"root": str(task), "project_root": str(root)},
                                  "idempotency_key": "dispatch:" + PARENT})
    BASE.record_stage_acceptance(task, "S3", PARENT)  # E-B11: the strategist is the S3 author; the acceptor reviewed its dispatch
    controller.apply("accept", {"id": PARENT, "status": "accepted", "stage_complete": True,
                                "evidence_refs": [BASE.evidence_ref(task, "S3-strategy.txt")],
                                "idempotency_key": "accept-" + PARENT})
    return root, env, task, controller


def rework_cli(root, env, task):
    """The rework packet of the incident, committed the way it was: `controller.py --operation rework`."""
    done = harness.run_script("controller.py", "--task-root", task, "--operation", "rework", "--stage", "S3",
                              "--role", "qa-test-strategist", "--cases", "TC-1", "--rows", "TS-1,TS-3",
                              "--reason", REASON, "--cause", "reviewer_error", cwd=root, env=env)
    return done, (json.loads(done.stdout) if done.returncode == 0 else {})


def step(root, env, *args):
    return harness.run_script("story_step.py", *args, cwd=root, env=env)


def materialize(root, env, dispatch_id=CHILD):
    return step(root, env, "materialize", "--task", TICKET, "--dispatch-id", dispatch_id)


def where(root, env):
    done = step(root, env, "where", "--task", TICKET)
    line = next(l for l in done.stdout.splitlines() if l.startswith("next: "))
    return json.loads(line[len("next: "):]), done.stdout


def files_of(task, dispatch_id=CHILD):
    return (task / "work" / "briefs" / f"{dispatch_id}.md", task / "work" / "handoffs" / f"{dispatch_id}.yaml",
            task / "work" / "briefs" / f"{dispatch_id}.launch.md")


def in_process(task_name=TICKET, dispatch_id=CHILD):
    """`materialize` in this process: (exit code, stdout)."""
    shown = io.StringIO()
    with contextlib.redirect_stdout(shown):
        code = story_step.materialize(argparse.Namespace(task=task_name, dispatch_id=dispatch_id, wait_seconds=0))
    return code, shown.getvalue()


# --- K1 ---------------------------------------------------------------------------------------------------

def a_committed_rework_packet_is_materialized_from_the_packet():
    """KILLS: have `materialize` call `controller.apply`/`prepare` (the log or the input_hash moves); drop
    `_packet_lines` from the prompt (the rework lines disappear); drop the rework/plan rows lines of
    brief_pack's head; pass an empty scope to the form; drop `next` from the rework result."""
    root, env, task, _ = accepted_s3("qa-mat-k1-")
    try:
        made, result = rework_cli(root, env, task)
        check_eq("the rework CLI commits the packet", (made.returncode, result.get("dispatched")), (0, True))
        check_eq("and answers with the door that writes its files", result.get("next"),
                 launch_card.materialize_door(TICKET, CHILD))
        brief, form, card = files_of(task)
        check("the packet has no brief, no form and no card (nothing but `start` wrote them)",
              not (brief.exists() or form.exists() or card.exists()))
        log, state = task / "state" / "events.jsonl", task / "state" / "controller.json"
        before = (sha(log), sha(state))
        done = materialize(root, env)
        check_eq("materialize exits 0", done.returncode, 0)
        check("and writes the brief, the form and the card", brief.is_file() and form.is_file() and card.is_file(),
              done.stdout[-400:] + done.stderr[-400:])
        check_eq("the log and the controller state are byte-identical afterwards", (sha(log), sha(state)), before)
        check_in("it lists the three paths it wrote",
                 "materialized: " + ", ".join(f"qa-factory/artifacts/{TICKET}/work/{rel}" for rel in (
                     f"briefs/{CHILD}.md", f"handoffs/{CHILD}.yaml", f"briefs/{CHILD}.launch.md")), done.stdout)
        printed = next(l for l in done.stdout.splitlines() if l.startswith("materialized: "))[len("materialized: "):]
        check("every path it printed is a file under the project root (FR-37)",
              all((root / rel).is_file() for rel in printed.split(", ")), printed)
        check_not_in("a dispatch that is not the S5 critic is told nothing about the probe debt", "probe_debt",
                     done.stdout)
        text = card.read_text(encoding="utf-8")
        check_in("the card carries the rework line with the cause and the reason",
                 f"Rework of {PARENT} (cause reviewer_error): {REASON}", text)
        check_in("the plan rows of the packet", "Plan rows of this dispatch: TS-1, TS-3", text)
        check_in("the input_hash the packet inherited from its parent (not a recomputed one)",
                 f"Dispatch input_hash: {PARENT_HASH}; purpose: repair_verify", text)
        check_in("the packet line printed says the scope", f"scope TC-1; plan rows TS-1, TS-3; rework of {PARENT} "
                 "(cause reviewer_error)", done.stdout)
        check_in("the card names the brief and the form it was written beside", f"work/briefs/{CHILD}.md first", text)
        check_in("and the form", f"work/handoffs/{CHILD}.yaml", text)
        check("the printed block is the card, byte for byte", done.stdout.endswith(text))
        head = brief.read_text(encoding="utf-8")
        check_in("the brief's head says whose work this repairs", f"Rework of {PARENT}.", head)
        check_in("and which plan rows (FR-49: the rows reach the role)", "Plan rows of this dispatch: TS-1, TS-3.", head)
        check_in("the repair cause and reason, as before", "cause reviewer_error: " + REASON, head)
        check("the card is the LAST file written (it proves the brief and the form are over)",
              card.stat().st_mtime_ns >= brief.stat().st_mtime_ns and card.stat().st_mtime_ns >= form.stat().st_mtime_ns)
        action, shown = where(root, env)
        check_eq("`where` now answers launch, for this dispatch", (action.get("action"), action.get("dispatch_id")),
                 ("launch", CHILD))
        check_in("and prints the card under it", text, shown)
        check_eq("`where` did not move the log either", sha(log), before[0])
        # the card `where` rebuilds from the RECORD is the card `materialize` rendered from the EVENT (I1)
        card.unlink()
        rebuilt, _ = where(root, env)
        check_eq("with the card gone `where` rebuilds it (launch again)", rebuilt.get("action"), "launch")
        check_eq("and the rebuilt card of a rework packet is the materialized card, byte for byte",
                 card.read_text(encoding="utf-8"), text)
    finally:
        cleanup(root)


# --- K2 ---------------------------------------------------------------------------------------------------

# The rendering main produced for `start --task QA-G --stage S1 --role qa-scout` on `STEP.open_story`, taken by
# running main's story_step.py (b9274291, before this change) and normalizing the package's paths: the helper
# extracted from `start`'s tail must not change one byte of it.
GOLDEN_CARD = (
    '--- Agent prompt, verbatim; subagent_type: qa-scout ---\n'
    'You are qa-scout. Ticket: QA-G. Dispatch: S1-qa-scout-1.\n'
    'Artifacts dir: qa-factory/artifacts/QA-G/\n'
    'Inputs:\n'
    '  qa-factory/artifacts/QA-G/pipeline.json\n'
    'Your handover is the form qa-factory/artifacts/QA-G/work/handoffs/S1-qa-scout-1.yaml. Fill it as you work; '
    'what code could already answer is filled in.\n'
    '  when it is filled: python "<scripts>/handoff_check.py" --file '
    'qa-factory/artifacts/QA-G/work/handoffs/S1-qa-scout-1.yaml --task QA-G --fix\n'
    '  it refuses with the field, the problem and the values YOUR role may write; nothing it says is about the '
    'quality of your work\n'
    '  what you cannot fill: put it under `blocked` and run handoff_help.py --file '
    'qa-factory/artifacts/QA-G/work/handoffs/S1-qa-scout-1.yaml - the conductor answers, you never ask the person\n'
    'Read qa-factory/artifacts/QA-G/work/briefs/S1-qa-scout-1.md first; it names the files and the commands.\n'
    'Return your digest line only.\n'
    "--- the moment the Agent call returns an id: on Claude the plugin's hook binds it; by hand only on Codex "
    'or when the guard or `where` says unbound: story_step.py bind --task QA-G --dispatch-id S1-qa-scout-1 '
    '--agent-id <id> ---\n'
    '--- after the digest: story_step.py finish --task QA-G --dispatch-id S1-qa-scout-1 '
    '--digest "<digest>" ---\n')
GOLDEN_HEAD_OF_STDOUT = (
    'dispatched S1-qa-scout-1 (revision 3)\n'
    'launch card: qa-factory/artifacts/QA-G/work/briefs/S1-qa-scout-1.launch.md (written last; if this output '
    'ends here, run: story_step.py where --task QA-G)\n'
    'note: brief: qa-factory/artifacts/QA-G/work/briefs/S1-qa-scout-1.md (<size>)\n')


def a_normal_start_is_byte_identical_to_main():
    """KILLS: let `_packet_lines` return lines for a dispatch that is not a rework; change the order of the
    notes, the brief, the form and the card in `_write_dispatch_files`; print the card twice or not at all."""
    root = harness.temp_project("qa-mat-k2-")
    try:
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
        env.pop(launch_card.RUN_MODE_ENV, None)
        harness.use_project(root)
        task = STEP.open_story(root, env, "QA-G")
        done = harness.run_script("story_step.py", "start", "--task", "QA-G", "--stage", "S1", "--role", "qa-scout",
                                  cwd=root, env=env)

        def normalized(text):
            # the size, and (since RC1-14 N4, e5aa025be) the ceiling it is measured against when they differ
            text = re.sub(r"\((\d[\d.,]*) (B|KB)(, \d[\d.,]* (B|KB) against the ceiling)?\)", "(<size>)", text)
            return text.replace(harness.SCRIPTS.resolve().as_posix(), "<scripts>")

        check_eq("start exits 0", done.returncode, 0)
        check_eq("its output is the golden of main, byte for byte", normalized(done.stdout),
                 GOLDEN_HEAD_OF_STDOUT + GOLDEN_CARD)
        card = task / "work" / "briefs" / "S1-qa-scout-1.launch.md"
        check_eq("and the card on disk is the golden's card", normalized(card.read_text(encoding="utf-8")), GOLDEN_CARD)
        check("the brief and the form are there", (task / "work" / "briefs" / "S1-qa-scout-1.md").is_file()
              and (task / "work" / "handoffs" / "S1-qa-scout-1.yaml").is_file())
        check_not_in("a normal dispatch's prompt has no rework line", "Rework of", card.read_text(encoding="utf-8"))
        check_eq("`_packet_lines` is empty for a dispatch with plan rows and no rework_of (an S4 designer's normal "
                 "packet carries every row)", story_step._packet_lines({"plan_rows": ["TS-1"], "input_hash": "h"}), ())
    finally:
        cleanup(root)


# --- K3 ---------------------------------------------------------------------------------------------------

def a_second_run_writes_nothing_and_a_differing_card_is_never_replaced():
    """KILLS: write the brief or the card unconditionally (the mtime moves); replace a card that differs;
    compare the card only after the brief and the form were rewritten; exit non-zero on 'nothing to do'."""
    root, env, task, _ = accepted_s3("qa-mat-k3-")
    try:
        rework_cli(root, env, task)
        brief, form, card = files_of(task)
        first = materialize(root, env)
        check_eq("run 1 exits 0", first.returncode, 0)
        tree = snapshot(root)
        second = materialize(root, env)
        check_eq("run 2 exits 0", second.returncode, 0)
        check_in("and says it wrote nothing", "materialized: nothing", second.stdout)
        check_eq("no file changed, not even its mtime", snapshot(root), tree)
        check_in("the card is still printed (the orchestrator needs it)", card.read_text(encoding="utf-8"), second.stdout)
        # the crash window: the card is written LAST, so a crash leaves a brief and a form and no card
        card.unlink()
        before = snapshot(root)
        third = materialize(root, env)
        after = snapshot(root)
        check_eq("with the card gone, run 3 exits 0 and writes ONLY the card",
                 (third.returncode, sorted(set(after) - set(before)),
                  {k for k in before if k in after and before[k] != after[k]}), (0, [str(card.relative_to(root))], set()))
        check_eq("and the card is what run 1 wrote", sha(card), tree[str(card.relative_to(root))][0])
        # a card that differs is refused, and nothing is written on the way to the refusal
        original = card.read_bytes()
        card.write_bytes(original + b"an edit by somebody\n")
        brief.unlink()                   # a missing brief must NOT be rewritten before the refusal
        tree = snapshot(root)
        refused = materialize(root, env)
        check_eq("a differing card: exit 2", refused.returncode, 2)
        check_in("the refusal says the card exists and differs, and where", "exists and differs from the card this "
                 "packet renders (first difference at line", refused.stdout)
        check_in("and names the door", launch_card.materialize_door(TICKET, CHILD), refused.stdout)
        check_eq("nothing was written: the card is not replaced and the brief is not rewritten", snapshot(root), tree)
        card.write_bytes(original)
        again = materialize(root, env)
        check_eq("restoring the card, the brief comes back and the run is clean", (again.returncode, brief.is_file()),
                 (0, True))
        # a brief that cannot be written is a note and the card is written all the same, as `start` does
        card.unlink()
        brief.unlink()
        saved = story_step._brief
        story_step._brief = lambda *a, **k: ("", "brief_pack: no brief (stubbed)")
        shown = io.StringIO()
        try:
            os.environ["CLAUDE_PROJECT_DIR"] = str(root)
            with contextlib.redirect_stdout(shown):
                code = story_step.materialize(argparse.Namespace(task=TICKET, dispatch_id=CHILD, wait_seconds=0))
        finally:
            story_step._brief = saved
        check_eq("a brief that fails: exit 0, a note and no refusal", code, 0)
        check_in("the note says what failed", "note: brief_pack: no brief (stubbed)", shown.getvalue())
        check("and the card WAS written", card.is_file())
        written = card.read_text(encoding="utf-8")
        check_not_in("a card with no brief names none", f"work/briefs/{CHILD}.md first", written)
        check_in("the rework line the role needs is in its prompt all the same", f"Rework of {PARENT}", written)
        rerun = materialize(root, env)
        check_eq("a rerun now (brief_pack works) finds a card that differs and refuses, naming the door that deletes it",
                 (rerun.returncode, "exists and differs" in rerun.stdout,
                  launch_card.materialize_door(TICKET, CHILD) in rerun.stdout), (2, True, True))
    finally:
        cleanup(root)


def the_form_is_made_for_the_scope_of_the_packet():
    """KILLS: hand `_handoff_form` the story's scope, an empty string or anything but the packet's own scope."""
    root, env, task, _ = accepted_s3("qa-mat-form-")
    try:
        rework_cli(root, env, task)
        os.environ["CLAUDE_PROJECT_DIR"] = str(root)
        seen = []
        saved = (story_step._handoff_form, story_step._brief)
        story_step._handoff_form = lambda *a: (seen.append(a), ("form-rel", ""))[1]
        story_step._brief = lambda *a: ("brief-rel", "")
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                story_step.materialize(argparse.Namespace(task=TICKET, dispatch_id=CHILD, wait_seconds=0))
        finally:
            story_step._handoff_form, story_step._brief = saved
        check_eq("the form is asked for with the packet's stage, role, dispatch and scope",
                 [(a[0], a[1], a[2], a[3], a[5]) for a in seen], [(TICKET, "S3", "qa-test-strategist", CHILD, "TC-1")])
    finally:
        cleanup(root)


# --- K4 ---------------------------------------------------------------------------------------------------

class Drifting(Controller):
    """A controller whose projection disagrees with the log about one field of one dispatch."""
    target, field, value = CHILD, "input_hash", "somebody-elses-hash"

    def state(self):
        state = super().state()
        state["dispatches"][self.target][self.field] = self.value
        return state


def refusals_name_the_field_the_value_and_the_door():
    """KILLS: drop the status test; drop the parent's input_hash comparison; drop the record-versus-event
    comparison; read the packet from the record instead of the log; let an unknown id fall through; build a path
    from an id before the state holds it."""
    root, env, task, controller = accepted_s3("qa-mat-k4-")
    try:
        rework_cli(root, env, task)
        tree = snapshot(root)

        def refused(name, done, *needles):
            check_eq(f"{name}: exit 2", done.returncode, 2)
            for needle in needles:
                check_in(f"{name}: says {needle!r}", needle, done.stdout)
            check_not_in(f"{name}: no traceback", "Traceback", done.stdout + done.stderr)

        refused("an unknown id", materialize(root, env, "S3-qa-test-strategist-9"),
                "the controller holds no dispatch S3-qa-test-strategist-9", "story_step.py start --task " + TICKET)
        refused("an accepted dispatch", materialize(root, env, PARENT), f"{PARENT} is accepted, not running",
                f"story_step.py where --task {TICKET}")
        check_eq("none of the refusals wrote anything", snapshot(root), tree)
        os.environ["CLAUDE_PROJECT_DIR"] = str(root)
        saved = story_step.Controller
        story_step.Controller = Drifting
        try:
            for name, target, field, value, needles in (
                    ("a record that differs from its event", CHILD, "input_hash", "somebody-elses-hash",
                     ("input_hash: record 'somebody-elses-hash' | committed event '" + PARENT_HASH + "'",
                      "--operation recover", "owner: factory")),
                    ("a record whose plan rows differ", CHILD, "plan_rows", ["TS-1"],
                     ("plan_rows: record ['TS-1'] | committed event ['TS-1', 'TS-3']",)),
                    ("a record whose repair cause differs", CHILD, "repair_cause", "tooling",
                     ("repair_cause: record 'tooling' | committed event 'reviewer_error'", "owner: factory")),
                    ("a rework whose input_hash is not its parent's", PARENT, "input_hash", "the-parent-moved",
                     (f"{CHILD} reworks {PARENT} but its input_hash '{PARENT_HASH}' is not the one {PARENT} was "
                      "accepted on, 'the-parent-moved'", "--operation release --dispatch " + CHILD))):
                Drifting.target, Drifting.field, Drifting.value = target, field, value
                try:
                    story_step.materialize(argparse.Namespace(task=TICKET, dispatch_id=CHILD, wait_seconds=0))
                    message = "(no refusal)"
                except ValueError as exc:
                    message = str(exc)
                for needle in needles:
                    check_in(f"{name}: says {needle!r}", needle, message)
                check_in(f"{name}: and that nothing was written", "Nothing was written", message)
        finally:
            story_step.Controller = saved
        check_eq("the in-process refusals wrote nothing either", snapshot(root), tree)
        for label, bad in (("empty", ""), ("blank", "   "), ("huge", "S3-" + "x" * 6000),
                           ("non-ASCII", "".join(chr(c) for c in (0x434, 0x438, 0x441, 0x43f, 0x2d, 0xe9))), ("path-like", "../../../state/events.jsonl"),
                           ("windows path", "..\\..\\evil"), ("a newline", CHILD + "\nS3-x"),
                           ("the key spelling", "dispatch:" + CHILD)):
            done = materialize(root, env, bad)
            check_eq(f"battery, {label}: exit 2", done.returncode, 2)
            check_in(f"battery, {label}: a refusal in words", "story_step: refused - the controller holds no dispatch",
                     done.stdout)
            check_not_in(f"battery, {label}: no traceback", "Traceback", done.stdout + done.stderr)
        check_eq("and the battery wrote nothing", snapshot(root), tree)
    finally:
        cleanup(root)
    root, env, task, controller = desktop_story("qa-mat-k4b-")
    try:
        controller.apply("dispatch", {"id": "S1-qa-scout-1", "stage": "S1", "role": "qa-scout", "scope": ["TC-1"],
                                      "input_hash": "h", "budget": {}, "known_paths": {},
                                      "idempotency_key": "some-other-key"})
        tree = snapshot(root)
        done = materialize(root, env, "S1-qa-scout-1")
        check_eq("a dispatch committed under another key: exit 2", done.returncode, 2)
        check_in("it says the log holds none with the key", "holds 0 dispatch event(s) with key dispatch:S1-qa-scout-1",
                 done.stdout)
        check_in("and names recover", "--operation recover", done.stdout)
        check_eq("and wrote nothing", snapshot(root), tree)
    finally:
        cleanup(root)


# --- K5 ---------------------------------------------------------------------------------------------------

def the_doors_are_named():
    """KILLS: name `materialize` in `wait_start` for a `start` packet (test_launch_card:682 is the second witness) or drop
    it for a packet outside `start`; revert the idempotency refusal to the bare sentence; append the door twice; drop
    the card-gone reason of `_rebuild_card` for an outside-start packet."""
    root, env, task, _ = accepted_s3("qa-mat-k5-")
    try:
        rework_cli(root, env, task)
        action, _ = where(root, env)
        check_eq("a running dispatch with no card, no brief: wait_start", (action.get("action"), action.get("dispatch_id")),
                 ("wait_start", CHILD))
        check_in("its reason names the materialize door", launch_card.materialize_door(TICKET, CHILD),
                 action.get("reason", ""))
        check_not_in("and does not tell the reader to ask again about a `start` nobody runs (FR-10)",
                     "ask again", action.get("reason", ""))
        check_in("the person's word still frees it", "release", action.get("reason", ""))
        before = (sha(task / "state" / "events.jsonl"), sha(task / "state" / "controller.json"))
        done = step(root, env, "start", "--task", TICKET, "--stage", "S3", "--role", "qa-test-strategist", "--id", CHILD,
                    "--purpose", "repair_verify")
        check_eq("`start --id` on the committed id is still refused", done.returncode, 2)
        for needle in (f"key 'dispatch:{CHILD}' already holds a dispatch request that differs in",
                       f'input_hash: committed="{PARENT_HASH}" | now="',
                       'plan_rows: committed=["TS-1", "TS-3"] | now=<absent>',
                       f'rework_of: committed="{PARENT}" | now=<absent>',
                       launch_card.materialize_door(TICKET, CHILD)):
            check_in(f"the refusal says {needle[:60]!r}", needle, done.stdout)
        check_not_in("a reuse that differs in more than the scope is not sent to `revise_plan` (F-3)", "revise_plan",
                     done.stdout)
        check_eq("and the refusal committed nothing", (sha(task / "state" / "events.jsonl"),
                                                       sha(task / "state" / "controller.json")), before)
        check_eq("`start` appends the door ONCE, from launch_card", done.stdout.count("materialize --task"), 1)
        check_not_in("no `dispatched` line was printed for a refusal", "dispatched " + CHILD, done.stdout)
        # the card is gone but the brief is there and the form is not: the reason of `_rebuild_card` names the door too
        brief, form, card = files_of(task)
        brief.parent.mkdir(parents=True, exist_ok=True)
        brief.write_text("# Brief\n", encoding="utf-8")
        again, _ = where(root, env)
        check_eq("brief there, form not: wait_start", again.get("action"), "wait_start")
        check_in("and the reason names the door (a packet outside `start`)", launch_card.materialize_door(TICKET, CHILD),
                 again.get("reason", ""))
    finally:
        cleanup(root)
    # F-3 at the controller: only a scope-only difference is N-2 (`revise_plan`); any other field is named, with its door
    root, env, task, controller = accepted_s3("qa-mat-n2-")
    try:
        base = {"id": "S3-x-1", "stage": "S3", "role": "qa-test-strategist", "scope": [], "input_hash": "h1", "budget": {},
                "known_paths": {"root": str(task), "project_root": str(root)}, "idempotency_key": "dispatch:S3-x-1"}
        controller.apply("dispatch", dict(base))

        def reuse(**change):
            try:
                controller.apply("dispatch", dict(base, **change))
                return None
            except StateConflict as exc:
                return exc
        other = reuse(input_hash="h2")
        check("a reuse differing in input_hash is an IdempotencyKeyReused for the key, naming the field",
              type(other).__name__ == "IdempotencyKeyReused" and other.key == "dispatch:S3-x-1"
              and "input_hash" in other.fields and 'input_hash: committed="h1" | now="h2"' in str(other), str(other))
        check_not_in("and it is not sent to revise_plan (FR-2)", "revise_plan", str(other))
        extra = reuse(brief_sha="b" * 8)
        check("a reuse differing in brief_sha names brief_sha", extra is not None and "brief_sha" in str(extra), str(extra))
        check_not_in("and does not name revise_plan", "revise_plan", str(extra))
        scoped = reuse(scope=["TC-1"])
        check("a reuse differing only in scope is the N-2 refusal: revise_plan, and its key travels",
              scoped is not None and "revise_plan" in str(scoped) and getattr(scoped, "key", "") == "dispatch:S3-x-1",
              str(scoped))
        both = reuse(scope=["TC-1"], brief_sha="c" * 8)
        check("a reuse differing in the scope AND another field is not the N-2 refusal: the field is named, no revise_plan (F-3)",
              both is not None and "brief_sha" in str(both) and "revise_plan" not in str(both)
              and {"scope", "brief_sha"} <= set(getattr(both, "fields", ())), str(both))
    finally:
        cleanup(root)
    # F-2 (t-1178): `start --id` on a dispatch `start` registered (it carries the config stamp), re-sent with another
    # scope AND another input_hash - not N-2, so the store's text passes up; the refusal still has a door (FR-57)
    root, env, task, controller = accepted_s3("qa-mat-f2-")
    try:
        base = {"id": "S3-y-1", "stage": "S3", "role": "qa-test-strategist", "scope": [], "input_hash": "h1", "budget": {},
                "known_paths": {"root": str(task), "project_root": str(root)}, "idempotency_key": "dispatch:S3-y-1",
                launch_card.CONFIG_START_FIELD: "f" * 64}
        controller.apply("dispatch", base)
        before = (sha(task / "state" / "events.jsonl"), sha(task / "state" / "controller.json"))
        done = step(root, env, "start", "--task", TICKET, "--stage", "S3", "--role", "qa-test-strategist", "--id", "S3-y-1",
                    "--scope", "TC-1")
        check_eq("`start --id` on a start-registered dispatch, scope + input_hash differing: refused", done.returncode, 2)
        check_in("the store's text names the fields", "key 'dispatch:S3-y-1' already holds a dispatch request that differs in",
                 done.stdout)
        check_in("and the way through: a new dispatch takes a new id", "a NEW dispatch takes a new id (run `start` without `--id`)",
                 done.stdout)
        check_not_in("a start-registered dispatch has files in the making: no `materialize` door", "materialize",
                     done.stdout)
        check_not_in("and it is not sent to revise_plan (more than the scope differs)", "revise_plan", done.stdout)
        check_eq("and the refusal committed nothing", (sha(task / "state" / "events.jsonl"),
                                                       sha(task / "state" / "controller.json")), before)
    finally:
        cleanup(root)
    # the store: the same request under its key is still an idempotent replay, and the store spells no door
    work = temp_dir("qa-mat-store-")
    try:
        store = EventStore(work)
        store.commit("dispatch", {"id": "d1", "input_hash": "a"}, "dispatch:d1")
        check_eq("the same request under its key is an idempotent replay", store.commit(
            "dispatch", {"id": "d1", "input_hash": "a"}, "dispatch:d1")["sequence"], 1)
        try:
            store.commit("dispatch", {"id": "d1", "input_hash": "b"}, "dispatch:d1")
            message = "(accepted)"
        except StateConflict as exc:
            message = str(exc)
        check_not_in("the store spells no door of story_step", "materialize", message)
    finally:
        cleanup(work)


# --- K6 ---------------------------------------------------------------------------------------------------

def the_changelog_fragment_names_the_change():
    # a release folds the fragment into CHANGELOG.md (changelog_assemble.py): after it the text lives there, under the version
    folded = not CHANGELOG_FRAGMENT.is_file()
    text = ((harness.PLUGIN_ROOT / "CHANGELOG.md").read_text(encoding="utf-8") if folded
            else CHANGELOG_FRAGMENT.read_text(encoding="utf-8"))
    check("K6: the changelog fragment exists", bool(text.strip()), str(CHANGELOG_FRAGMENT))
    for needle in ("story_step.py materialize", "`_write_dispatch_files`", "launch_card.py", "event_store.py",
                   "TP2-2406", "finish", "halt"):
        check_in(f"K6: the fragment names {needle}", needle, text)
    check("K6: it holds no heading line (the release writes the heading)",
          folded or not re.search(r"(?m)^#{1,6}(\s|$)", text))
    check("K6: it is free of Cyrillic", not re.search("[" + chr(0x400) + "-" + chr(0x4ff) + "]", text))


# --- K7 ---------------------------------------------------------------------------------------------------

def a_record_that_differs_in_reason_is_refused_and_the_wording_is_the_events():
    """KILLS: drop `reason` from IDENTITY_FIELDS."""
    root, env, task, controller = accepted_s3("qa-mat-k7a-")
    try:
        rework_cli(root, env, task)
        os.environ["CLAUDE_PROJECT_DIR"] = str(root)
        tree = snapshot(root)
        saved = story_step.Controller
        story_step.Controller = Drifting
        Drifting.target, Drifting.field, Drifting.value = CHILD, "reason", "another reason"
        try:
            try:
                in_process()
                message = "(no refusal)"
            except ValueError as exc:
                message = str(exc)
        finally:
            story_step.Controller = saved
        check_in("a record whose reason differs from the event is refused as record != event",
                 f"reason: record 'another reason' | committed event {REASON!r}", message)
        check_in("and says nothing was written", "Nothing was written", message)
        check_eq("and nothing was", snapshot(root), tree)
    finally:
        cleanup(root)


def a_driver_story_is_refused_as_start_refuses_it_and_is_not_stamped():
    """KILLS: drop the `run_mode_switch` test from `materialize`; stamp the mode in it; refuse with another text."""
    root, env, task, _ = accepted_s3("qa-mat-k7b-")
    try:
        rework_cli(root, env, task)
        pipeline_file = task / "pipeline.json"
        pipeline = json.loads(pipeline_file.read_text(encoding="utf-8"))
        pipeline["run_mode"] = {"mode": "driver"}
        pipeline_file.write_text(json.dumps(pipeline), encoding="utf-8")
        tree = snapshot(root)
        refused = materialize(root, env)
        by_start = step(root, env, "start", "--task", TICKET, "--stage", "S3", "--role", "qa-test-strategist",
                        "--id", "S3-qa-test-strategist-9")
        check_eq("a story stamped `driver`, materialized by a desktop conductor: exit 2", refused.returncode, 2)
        check_eq("with exactly the text `start` refuses with", refused.stdout, by_start.stdout)
        check_in("that text names the stamped mode and the door", "was started in `driver` mode", refused.stdout)
        check_eq("and nothing was written, the stamp included", snapshot(root), tree)
        del pipeline["run_mode"]
        pipeline_file.write_text(json.dumps(pipeline), encoding="utf-8")
        before = sha(pipeline_file)
        made = materialize(root, env)
        check_eq("a story with no stamp is materialized (exit 0)", made.returncode, 0)
        check_eq("and pipeline.json is byte-identical afterwards: no stamp", sha(pipeline_file), before)
    finally:
        cleanup(root)


def materialize_derives_files_as_start_does_and_does_not_repeat_the_judge():
    """KILLS: skip `_derive_before`; run `_pre_work` on every run; never run it; run `_settle_probe_debt`."""
    root, env, task, _ = accepted_s3("qa-mat-k7c-")
    try:
        rework_cli(root, env, task)
        os.environ["CLAUDE_PROJECT_DIR"] = str(root)
        calls, real = [], story_step._run

        def fake_run(script, *args):
            if script == "judge_plan.py":
                calls.append(script)
                (task / "work" / "judge-plan.json").write_text("{}", encoding="utf-8")
                return 0, "judge_plan: wrote work/judge-plan.json"
            if script in ("fake_derive.py", "probe_debt.py"):
                calls.append(script)
                return 0, "derived"
            return real(script, *args)

        saved = (story_step._run, story_step.judge.active, story_step.DERIVED_BEFORE)
        story_step._run, story_step.judge.active = fake_run, (lambda *a, **k: True)
        story_step.DERIVED_BEFORE = {"qa-test-strategist": [("fake_derive.py", ("--task", "{task}"))]}
        try:
            first_code, first = in_process()
            tree = snapshot(root)
            first_calls = list(calls)
            second_code, second = in_process()
        finally:
            story_step._run, story_step.judge.active, story_step.DERIVED_BEFORE = saved
        check_eq("run 1 (judge on): the judge pre-work ran, then the derived step; run 2: the derived step only",
                 (first_code, first_calls, second_code, calls[len(first_calls):]),
                 (0, ["judge_plan.py", "fake_derive.py"], 0, ["fake_derive.py"]))
        check_in("run 1 says what the pre-work said", "note: judge_plan: wrote work/judge-plan.json", first)
        check_in("run 2 wrote nothing", "materialized: nothing", second)
        check_eq("and run 2 changed no file", snapshot(root), tree)
        check("the probe-debt settle was run by neither", "probe_debt.py" not in calls)
    finally:
        cleanup(root)


def the_s5_critic_card_names_the_settle_door_and_materialize_never_settles():
    """KILLS: call `_settle_probe_debt` from materialize; drop the door line; drop the `_debt_input` note."""
    root, env, task, _ = desktop_story("qa-mat-k7d-")
    try:
        dispatch_id = "S5-qa-code-critic-2"
        packet = {"id": dispatch_id, "stage": "S5", "role": "qa-code-critic", "input_hash": "h", "scope": ["TC-1"],
                  "plan_rows": [], "rework_of": "", "purpose": "", "repair_cause": None, "reason": None}
        events = [{"idempotency_key": "dispatch:" + dispatch_id, "type": "dispatch", "payload": packet}]

        class Fake:
            def __init__(self, _root, wait_seconds=0.0):
                self.store = types.SimpleNamespace(read=lambda: events)

            def state(self):
                return {"dispatches": {dispatch_id: dict(packet, status="running")}, "revision": 1}

        (task / "work" / "probe-debt.json").write_text(json.dumps(
            {"dispatch": "S5-qa-code-critic-1", "left": [{"instance_id": "i-1"}], "outcomes": []}), encoding="utf-8")
        os.environ["CLAUDE_PROJECT_DIR"] = str(root)
        calls = []
        saved = (story_step.Controller, story_step._run, story_step._brief, story_step._handoff_form)
        story_step.Controller = Fake
        story_step._run = lambda script, *args: (calls.append(script), (0, ""))[1]
        story_step._brief = lambda *a: ("brief-rel", "")
        story_step._handoff_form = lambda *a: ("form-rel", "")
        try:
            code, out = in_process(TICKET, dispatch_id)
        finally:
            story_step.Controller, story_step._run, story_step._brief, story_step._handoff_form = saved
        check_eq("an S5 critic packet is materialized (exit 0)", code, 0)
        check_in("its output names the door that settles, with the dispatch",
                 f"probe_debt.py --task {TICKET} --settle --dispatch {dispatch_id}", out)
        check_in("and says materialize does not run it", "probe_debt --settle is not run by materialize", out)
        check("and the settle was NOT run", "probe_debt.py" not in calls, str(calls))
    finally:
        cleanup(root)


# --- part 2: a declared halt ------------------------------------------------------------------------------

def halted_form(role="qa-case-critic", verdict="halt", extra=""):
    return f"header:\n  role: {role}\n  stage: S4\n  window: TC-1\n  verdict: {verdict}\n{extra}"


def s4_halted(prefix, ticket, role="qa-case-critic", did="s4-critic", verdict="halt", form=True, extra=""):
    """An S4 story with `did` running and its form on disk, `header.verdict: <verdict>` (no form when `form` is False)."""
    root = harness.temp_project(prefix)
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    env.pop(launch_card.RUN_MODE_ENV, None)
    harness.use_project(root)
    art = STEP.s4_story(root, ticket, role=role, did=did, valid_case=(verdict == "ok"))
    BASE.record_stage_acceptance(art, "S4")  # E-B11: the fixture's only S4 dispatch is the closing critic, so the author dispatch is ""
    if form:
        (art / "work" / "handoffs").mkdir(parents=True, exist_ok=True)
        (art / "work" / "handoffs" / f"{did}.yaml").write_text(halted_form(role, verdict, extra), encoding="utf-8")
    return root, env, art


def finish_cli(root, env, ticket, did, digest, *more):
    return harness.run_script("story_step.py", "finish", "--task", ticket, "--dispatch-id", did, "--digest", digest,
                              *more, cwd=root, env=env)


def a_declared_halt_is_never_accepted():
    """KILLS: `--ignore-handoff` (or any other flag) passes a halt; read only the digest; read only the form; drop the
    refusal's naming of where the halt was read."""
    root, env, art = s4_halted("qa-halt-k8-", "QA-H1")
    try:
        tree = snapshot(root)
        for label, digest, flags, where_ in (
                ("form only", "qa-case-critic S4 TC-1 · ok", (), "the handover form (header.verdict: halt)"),
                ("digest only", "qa-case-critic S4 TC-1 · halt", (), "the digest"),
                ("form + --ignore-handoff", "qa-case-critic S4 TC-1 · ok", ("--ignore-handoff",), "the handover form"),
                ("form + --unresolved/--reason", "qa-case-critic S4 TC-1 · ok", ("--unresolved", "X", "--reason", "Y"), "the handover form"),
                ("form + --complete", "qa-case-critic S4 TC-1 · ok", ("--complete",), "the handover form"),
                ("form + --not-complete", "qa-case-critic S4 TC-1 · ok", ("--not-complete",), "the handover form"),
                ("form + --output", "qa-case-critic S4 TC-1 · ok", ("--output", "work/case-critic-findings.md"), "the handover form")):
            done = finish_cli(root, env, "QA-H1", "s4-critic", digest, *flags)
            check_eq(f"{label}: exit 2", done.returncode, 2)
            check_in(f"{label}: says where the halt was read", where_, done.stdout)
            check_in(f"{label}: stays open, nothing recorded", "stays open and nothing was recorded", done.stdout)
            check_eq(f"{label}: the tree is byte-identical (the form was not even repaired)", snapshot(root), tree)
        both = finish_cli(root, env, "QA-H1", "s4-critic", "qa-case-critic S4 TC-1 · halt")
        check_in("both places: both are named", "the handover form (header.verdict: halt) and the digest", both.stdout)
    finally:
        cleanup(root)
    root, env, art = s4_halted("qa-halt-k8c-", "QA-H2", verdict="ok")
    try:
        done = finish_cli(root, env, "QA-H2", "s4-critic", "qa-case-critic S4 TC-1 · ok", "--ignore-handoff")
        check("control: a non-halting form is accepted (the dispatch is recorded `accepted`)",
              Controller(art).state()["dispatches"]["s4-critic"]["status"] == "accepted", done.stdout[-600:])
    finally:
        cleanup(root)


def the_halt_is_read_before_the_form_is_checked_and_after_the_decision():
    """KILLS: read the halt after `_handoff_check` (i); refuse before `_decision_of` / let the decision not lift the halt
    (ii); a decision that is not passed on as the form's word (F-4 (a), iii); no outputs still refuses (E6)."""
    root, env, art = s4_halted("qa-halt-k9-", "QA-H3", extra="blocked:\n  - field: x\n")
    try:
        tree = snapshot(root)
        done = finish_cli(root, env, "QA-H3", "s4-critic", "qa-case-critic S4 TC-1 · ok")
        check_eq("(i) halt + a form with problems: the HALT refusal (exit 2), not the form refusal (exit 3)",
                 (done.returncode, "declared a halt" in done.stdout), (2, True))
        check_eq("(i) and the form is untouched", snapshot(root), tree)
        decided = STEP.run_decide(root, env, "QA-H3", ["--close"], dispatch="s4-critic")
        check_eq("decide --close on the halted closing role: recorded", decided.returncode, 0)
        done = finish_cli(root, env, "QA-H3", "s4-critic", "qa-case-critic S4 TC-1 · ok")
        check("(ii) halt + a recorded close: accepted, no --ignore-handoff asked (F-4 (a))",
              Controller(art).state()["dispatches"]["s4-critic"]["status"] == "accepted", done.stdout[-600:])
        check_in("(ii) the halt is named as a note", "the role declared a halt in the handover form", done.stdout)
        check_in("(ii) with the decision that stands", "the person's recorded decision (close,", done.stdout)
    finally:
        cleanup(root)
    # (i) again with a REAL form: the fixture above has no `contract:` line, so `_handoff_check` answers `none` for it and
    # never reaches a form refusal (a mutant that reads the halt after the form check survived it). A form handoff_init
    # wrote is all placeholders: `untouched`, exit 3 without a halt. With the verdict set to halt the HALT gate must
    # refuse first (exit 2), and `--fix`, which writes into the form, must not have run.
    root, env, art = s4_halted("qa-halt-k9r-", "QA-H3R", form=False)
    try:
        os.environ["CLAUDE_PROJECT_DIR"] = str(root)
        story_step._handoff_form("QA-H3R", "S4", "qa-case-critic", "s4-critic", art, "TC-1")
        form = art / "work" / "handoffs" / "s4-critic.yaml"
        control = finish_cli(root, env, "QA-H3R", "s4-critic", "qa-case-critic S4 TC-1 · ok")
        check_eq("(i) control: the real form with no halt is refused by the FORM check (exit 3, untouched)",
                 (control.returncode, "left its handover form untouched" in control.stdout), (3, True))
        form.write_text(re.sub(r"(?m)^(\s*verdict:).*$", r"\1 halt", form.read_text(encoding="utf-8")), encoding="utf-8")
        tree = snapshot(root)
        done = finish_cli(root, env, "QA-H3R", "s4-critic", "qa-case-critic S4 TC-1 · ok")
        check_eq("(i) the same real form with the halt: the HALT refusal (exit 2), not the form refusal (exit 3)",
                 (done.returncode, "declared a halt" in done.stdout, "untouched" in done.stdout), (2, True, False))
        check_eq("(i) and the form was not repaired (`--fix` never ran): the tree is byte-identical", snapshot(root), tree)
    finally:
        cleanup(root)
    root, env, art = s4_halted("qa-halt-k9b-", "QA-H4")
    try:
        decided = STEP.run_decide(root, env, "QA-H4", ["--open", "TC-1"], dispatch="s4-critic")
        check_eq("decide --open on the halted closing role: recorded", decided.returncode, 0)
        done = finish_cli(root, env, "QA-H4", "s4-critic", "qa-case-critic S4 TC-1 · ok", "--complete")
        check("(iii) halt + a recorded open_work: accepted, the stage stays open",
              Controller(art).state()["dispatches"]["s4-critic"]["status"] == "accepted", done.stdout[-600:])
        check_in("(iii) the halt is a note", "the role declared a halt", done.stdout)
        check_in("(iii) and the note says the stage is kept open on the named work (the output as written)",
                 "the person's recorded decision keeps S4 open: TC-1", done.stdout)
        check("(iii) and the stage S4 is not completed in the controller's state",
              Controller(art).state()["stages"]["S4"]["status"] != "completed", done.stdout[-600:])
    finally:
        cleanup(root)
    # E6: halt + decision + no outputs -> the existing refusal stands (an accept is never recorded without evidence)
    root, env, art = s4_halted("qa-halt-k9c-", "QA-H5")
    try:
        STEP.run_decide(root, env, "QA-H5", ["--close"], dispatch="s4-critic")
        import shutil
        shutil.rmtree(art / "work" / "test-cases")
        for leftover in (art / "work" / "case-critic-findings.md",):
            leftover.unlink()
        (art / "state" / "story-case-links.json").unlink(missing_ok=True)      # S4's other declared output
        done = finish_cli(root, env, "QA-H5", "s4-critic", "qa-case-critic S4 TC-1 · ok")
        check("E6: halt + decision + no outputs: exit 3, 'left none of the outputs'",
              (done.returncode, "left none of the outputs" in done.stdout) == (3, True), done.stdout[-600:])
    finally:
        cleanup(root)


def the_declared_halt_reader_battery():
    """KILLS: `_declared_halt` without `.lower()`, without the form, a second word list, a phrase match on the digest."""
    root = temp_dir("qa-halt-k10-")
    try:
        task_root = Path(root)
        (task_root / "work" / "handoffs").mkdir(parents=True)
        form = task_root / "work" / "handoffs" / "d.yaml"
        rel = "work/handoffs/d.yaml"
        for text, halts in (("halt", True), ("HALT", True), (" halt ", True), ('"halt"', True), ("impossible", True),
                            ("Impossible", True), ("halted", False), ("not halt", False), ("ok", False), ("concerns", False),
                            ("<one of vocabulary.header_verdicts>", False), ("ok|concerns|halt|impossible", False),
                            ("[halt]", False), ("{a: halt}", False), ("", False), ("null", False)):
            form.write_text(f"header:\n  role: r\n  stage: S4\n  window: TC-1\n  verdict: {text}\n", encoding="utf-8")
            check_eq(f"verdict {text!r} -> {'halt' if halts else 'no halt'}", bool(story_step._declared_halt(task_root, rel, "")),
                     halts)
        form.write_bytes(b"\xef\xbb\xbf" + halted_form().encode("utf-8"))
        check_in("a BOM does not hide the halt", "header.verdict: halt", story_step._declared_halt(task_root, rel, ""))
        form.write_text("# a comment\n# another\n" + halted_form(), encoding="utf-8")
        check("a halt header on line 3 is a halt", bool(story_step._declared_halt(task_root, rel, "")))
        form.unlink()
        form.mkdir()
        check_eq("the form is a directory: nothing from the form", story_step._declared_halt(task_root, rel, ""), "")
        form.rmdir()
        check_eq("the form is absent: nothing from the form", story_step._declared_halt(task_root, rel, ""), "")
        check_eq("the form is absent and the digest halts: the digest",
                 story_step._declared_halt(task_root, rel, "qa-x S4 TC-1 · halt"), "the digest")
        check_eq("a digest with the word in prose is not a halt",
                 story_step._declared_halt(task_root, "", "I will halt if the stand is down"), "")
        check_eq("an empty / None digest and no form: nothing", (story_step._declared_halt(task_root, "", ""),
                                                                  story_step._declared_halt(task_root, "", None)), ("", ""))
        form.write_bytes(b"\x00\x01 not a form: [[[")
        check_eq("an unparseable form says nothing (the form check owns that refusal)",
                 story_step._declared_halt(task_root, rel, ""), "")
    finally:
        cleanup(root)


def the_no_change_note():
    """KILLS: `_no_change_note` indexing `r["path"]` / `r["sha256"]` (KeyError), comparing the wrong scope, or no note."""
    dispatch = {"rework_of": "P", "plan_rows": ["TS-1"], "purpose": "repair_verify"}
    state = {"dispatches": {"P": {"evidence_refs": [{"path": "work/test-plan.json", "sha256": "aa"}]}}}
    same = [{"path": "work/test-plan.json", "sha256": "aa"}, {"path": "work/handoffs/D.yaml", "sha256": "zz"}]
    check_in("evidence byte-identical to the parent's: the note", "no change against P: work/test-plan.json is byte-identical",
             story_step._no_change_note(dispatch, same, state))
    check_eq("a changed sha: no note", story_step._no_change_note(dispatch, [{"path": "work/test-plan.json", "sha256": "bb"}], state), "")
    check_eq("the parent missing: no note", story_step._no_change_note(dispatch, same, {"dispatches": {}}), "")
    check_eq("purpose not repair_verify: no note", story_step._no_change_note(dict(dispatch, purpose="x"), same, state), "")
    check_eq("a ref without sha256 (or path) and a parent ref without them: no note, no KeyError",
             story_step._no_change_note(dispatch, [{"path": "work/test-plan.json"}, {"sha256": "aa"}, "x"], state), "")
    check_eq("nothing shared: no note", story_step._no_change_note(dispatch, [{"path": "other", "sha256": "aa"}], state), "")


def recover_root(text):
    """The task root a refusal's `controller.py --task-root <R> --operation recover` names, resolved (the child process
    may spell a Windows temp directory in its long form, the test in its short one); None when the text has none."""
    found = re.search(r"controller\.py --task-root (\S+) --operation recover", text)
    return Path(found.group(1)).resolve() if found else None


def the_door_table_of_a_halt():
    """F-4 / F-1 (b). KILLS (one per row): S5 names `decide`; a closing role is not given `decide`; a non-closing role's
    form halt is not given `--close`; `--open` on a non-closing halted role is accepted; `finish` forces the stage closed
    for a role that does not close it; a digest-only halt of a non-closing role is given a `decide` door."""
    root, env, art = s4_halted("qa-halt-k13-", "QA-H6", role="qa-case-designer", did="s4-designer")
    try:
        done = finish_cli(root, env, "QA-H6", "s4-designer", "qa-case-designer S4 TC-1 · ok")
        check_eq("non-closing role, form halt: refused", done.returncode, 2)
        check_in("it names `decide ... --close`", "story_step.py decide --task QA-H6 --dispatch-id s4-designer", done.stdout)
        check_in("and `--close`", "--close`", done.stdout)
        check_not_in("and no `--open`: nothing starts a rework here", "--open", done.stdout)
        check_in("and the pause/recover road beside it", "--operation recover", done.stdout)
        opened = STEP.run_decide(root, env, "QA-H6", ["--open", "TC-1"], dispatch="s4-designer")
        check_eq("(ii) decide --open on a non-closing halted role is REFUSED", opened.returncode, 2)
        check_in("naming --close and the pause/recover road", "`--close` accepts this work as it is", opened.stdout)
        check_in("and the recover door", "--operation recover", opened.stdout)
        # F-1 (t-1178): ONE spelling of the pause -> recover door, with the story's real values in every text a person
        # reads - the finish refusal and the decide refusal name the same task, dispatch and task root
        placeholders = lambda text: len(re.findall(r"<T>|<task root>", text))
        check_eq("positive control: the placeholder search finds the old spelling",
                 placeholders("pause --task <T> ... --task-root <task root> --operation recover"), 2)
        for label, text in (("the finish refusal", done.stdout), ("the `--open` refusal of decide", opened.stdout)):
            check_in(f"{label} names the real task and dispatch in the pause command",
                     "story_step.py pause --task QA-H6 --dispatch-id s4-designer", text)
            check_eq(f"{label} names the real task root in the recover command", recover_root(text), art.resolve())
            check_eq(f"{label}: no `<T>` / `<task root>` placeholder", placeholders(text), 0)
        check_not_in("no false success line", "starts by itself", opened.stdout)
        check_eq("and nothing was recorded", (art / "state" / "decisions" / "s4-designer.json").exists(), False)
        closed = STEP.run_decide(root, env, "QA-H6", ["--close"], dispatch="s4-designer")
        check_eq("decide --close on the non-closing role whose FORM halts: recorded", closed.returncode, 0)
        check_in("and it does not say the stage closes", "follows its own rule", closed.stdout)
        done = finish_cli(root, env, "QA-H6", "s4-designer", "qa-case-designer S4 TC-1 · ok")
        stage = Controller(art).state()["stages"]["S4"]["status"]
        check_eq("finish accepts the designer and S4 stays OPEN (the critic comes after it)",
                 (done.returncode, stage != "completed"), (0, True))
    finally:
        cleanup(root)
    root, env, art = s4_halted("qa-halt-k13b-", "QA-H7", role="qa-case-designer", did="s4-designer", form=False)
    try:
        done = finish_cli(root, env, "QA-H7", "s4-designer", "qa-case-designer S4 TC-1 · halt", "--ignore-handoff")
        check_eq("non-closing role, digest-only halt: refused", done.returncode, 2)
        check_not_in("no `decide` door (decide cannot see the digest)", "story_step.py decide", done.stdout)
        check_in("the pause/recover road", "--status blocked", done.stdout)
        plain = STEP.run_decide(root, env, "QA-H7", ["--close"], dispatch="s4-designer")
        check_eq("and decide --close with no halted form: refused as on main (the pin)", plain.returncode, 2)
        check_in("with main's sentence", "which does not close S4", plain.stdout)
        check_in("and the road with the real task and task root (F-1)", "story_step.py pause --task QA-H7 --dispatch-id "
                 "s4-designer --reason \"<what the role could not do>\" --status blocked`, then take a person's word",
                 plain.stdout)
        check_eq("and the real task root", recover_root(plain.stdout), art.resolve())
    finally:
        cleanup(root)
    root, env, art = s4_halted("qa-halt-k13c-", "QA-H8")
    try:
        done = finish_cli(root, env, "QA-H8", "s4-critic", "qa-case-critic S4 TC-1 · halt")
        check_eq("closing role, digest-only halt: refused", done.returncode, 2)
        check_in("the closing role is given `decide`", "story_step.py decide --task QA-H8 --dispatch-id s4-critic", done.stdout)
        check_in("with `--open` too (accepted today)", "`--open [<ids>]`", done.stdout)
    finally:
        cleanup(root)
    s5_art = None
    root = harness.temp_project("qa-halt-k13d-")
    try:
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
        harness.use_project(root)
        s5_art, _ = STEP.s5_window_story(root, "QA-H9", handed=False)
        done = finish_cli(root, env, "QA-H9", "s5-critic", "qa-code-critic S5 TC-1 · halt")
        check_eq("S5, a halting digest: refused", done.returncode, 2)
        check_not_in("S5 is not given a `decide` door", "story_step.py decide", done.stdout)
        check_in("S5 is given pause -> recover", "--status blocked", done.stdout)
        check_in("and the recover door", "--operation recover", done.stdout)
    finally:
        cleanup(root)


def a_dispatch_committed_before_this_change_has_no_files_and_finish_reads_its_form():
    """The temporal edge (both worlds): a running dispatch committed with NO brief, form or card on disk (everything
    committed before `materialize` existed) is written by `materialize` from the record, which says what it wrote; `finish`
    reads the form at the one path (`FORM_REL`) whenever the form exists. KILLS: a second spelling of the form path."""
    root, env, task, _ = accepted_s3("qa-mat-temporal-")
    try:
        rework_cli(root, env, task)
        brief, form, card = files_of(task)
        check("before: no files on disk", not (brief.exists() or form.exists() or card.exists()))
        form_rel = story_step.FORM_REL.format(dispatch_id=CHILD)
        check_eq("the form path is the one spelling", str(form.relative_to(task)).replace("\\", "/"), form_rel)
        check_eq("with no form, finish reads nothing from it", story_step._declared_halt(task, form_rel, ""), "")
        done = materialize(root, env)
        check_in("after: materialize says what it wrote", "materialized: ", done.stdout)
        form.write_text(halted_form("qa-test-strategist"), encoding="utf-8")
        check_in("and a halt written into that form is read by finish at that path",
                 "header.verdict: halt", story_step._declared_halt(task, form_rel, ""))
        done = finish_cli(root, env, TICKET, CHILD, "qa-test-strategist S3 TC-1 · ok")
        check_eq("finish refuses the rework that halted", (done.returncode, "declared a halt" in done.stdout), (2, True))
    finally:
        cleanup(root)


# --- the driver: one reader of the halt, at three sites ----------------------------------------------------

class FakeDriver:
    """Just enough of `story_run.Driver` for `run_role` (the rework branch, no `start`), `resume_role` and
    `_finish_saved_result`: every collaborator records its call."""

    def __init__(self, task_root, digest, handoff_raises=None, dead=False):
        import story_run
        self.task, self.task_root, self.state_dir = TICKET, task_root, task_root / "state"
        self.plugin = self.scripts = "plugin"
        self.calls, self.digest, self.handoff_raises, self.dead = [], digest, handoff_raises, dead
        self.state = {"sessions": {"d1": "sid"}, "pending_words": {"d1": "w"}}
        self.run = types.SimpleNamespace(is_error=False)
        self.Person = story_run.Person

    def stages(self):
        return story_step._stages()

    def session_of(self, stage, dispatch):
        """t-2133: `resume_role` reads the stored session through `Driver.session_of` (TR3-6); the fake has the stored one only."""
        return self.state["sessions"].get(dispatch)

    def timed(self, *a, **k):
        """t-2113: `run_role` times its steps (`Driver.timed`, TR3-2); the fake times nothing."""
        return contextlib.nullcontext()

    def system_file(self, *a, **k):
        return None

    def progress_line(self):
        pass

    def save_state(self):
        pass

    def pipeline(self):
        return {}

    def py(self, script, *args):
        self.calls.append(("py", script, args[args.index("--status") + 1] if "--status" in args else ""))
        return 0, ""

    def py_trace(self, script, *args, why=""):
        # the real one (story_run.Driver.py_trace, C1-7c) forwards to `py` and never raises: the fake records the same call
        self.py(script, *args)

    def record_running(self, stage, role, dispatch, *, retry, relaunched=False, rework_of=""):
        # C1-7c F-3: the `running` record before a registered dispatch's role goes on; these tests judge what the role's
        # OUTCOME does (halt heard once, dead run, twins), not the record, so the fake writes nothing and refuses nothing
        return None

    def run_claude(self, *a, **k):
        self.calls.append(("run_claude",))
        if self.dead:      # an error and no words: a dead run
            return {"result": "", "session_id": "", "is_error": True}
        return {"result": "the role's last word", "session_id": "", "is_error": False}

    def digest_of(self, text):
        return self.digest

    def handoff(self, role, stage, dispatch, result):
        self.calls.append(("handoff",))
        if self.handoff_raises:
            raise self.handoff_raises
        return self.digest

    def halt_text(self, *a, **k):
        return "the role handed the decision back"

    def walk_reopen(self, dispatch, reopen=True):       # t-2016 F4: `run_role` asks it for every dispatch; none of these is a walk dispatch
        return [], ""

    def s7_is_triage(self, *a, **k):       # `run_role` asks it for every dispatch; none of these is an S7 triage one
        return False

    def question_threshold(self, *a, **k):
        self.calls.append(("question_threshold",))

    def repair_limit_gate(self, *a, **k):
        self.calls.append(("repair_limit_gate",))

    def finish(self, *a, **k):
        self.calls.append(("finish",))
        return ("done", {})

    def completion_for(self, *a, **k):
        return None


def driver_outcome(method, form_verdict, digest, role="qa-test-strategist", handoff_raises=None, *args, dead=False, **kwargs):
    """Run `story_run.Driver.<method>` on a FakeDriver whose form for `d1` says `form_verdict`: (calls, Person kind or '')."""
    import story_run
    root = temp_dir("qa-halt-driver-")
    try:
        task_root = Path(root)
        (task_root / "work" / "handoffs").mkdir(parents=True)
        if form_verdict:
            (task_root / "work" / "handoffs" / "d1.yaml").write_text(halted_form(role, form_verdict), encoding="utf-8")
        fake = FakeDriver(task_root, digest, handoff_raises, dead)
        fake.state["question_stop"] = {}
        saved = story_step._brief
        story_step._brief = lambda *a, **k: ("", "")
        kind = ""
        try:
            getattr(story_run.Driver, method)(fake, *args, **kwargs)
        except story_run.Person as exc:
            kind = exc.kind
        finally:
            story_step._brief = saved
        return fake.calls, kind
    finally:
        cleanup(root)


def the_driver_hears_a_form_halt_once_before_the_resume():
    """KILLS: `run_role` reads only the digest (no early read: `handoff` is called); the early read for the scout (B-1)."""
    ok_digest = "qa-test-strategist S3 TC-1 · ok"
    calls, kind = driver_outcome("run_role", "halt", ok_digest, "qa-test-strategist", None, "S3", "qa-test-strategist",
                                 rework={"id": "d1", "reason": "x"})
    names = [c[0] for c in calls]
    check_eq("a form halt + a non-halting message: Person(halt)", kind, "halt")
    check_eq("stage_done halted was called, finish and the threshold were NOT, and `handoff` (a possible resume) was NOT",
             ("halted" in [c[2] for c in calls if c[0] == "py"], "finish" in names, "question_threshold" in names,
              "handoff" in names), (True, False, False, False))
    calls, kind = driver_outcome("run_role", "ok", ok_digest, "qa-test-strategist", None, "S3", "qa-test-strategist",
                                 rework={"id": "d1", "reason": "x"})
    check_eq("control: no halt -> handoff, the threshold and finish run; no Person", (kind, [c[0] for c in calls if c[0] != "py"]),
             ("", ["run_claude", "handoff", "question_threshold", "repair_limit_gate", "finish"]))
    calls, kind = driver_outcome("run_role", "", "qa-test-strategist S3 TC-1 · halt", "qa-test-strategist", None, "S3",
                                 "qa-test-strategist", rework={"id": "d1", "reason": "x"})
    check_eq("a digest halt still halts (after handoff)", (kind, "handoff" in [c[0] for c in calls]), ("halt", True))
    import story_run
    calls, kind = driver_outcome("run_role", "halt", ok_digest, "qa-scout", story_run.Person("s1_gap", "a gap", "S1", "d1"),
                                 "S1", "qa-scout", rework={"id": "d1", "reason": "x"})
    check_eq("B-1 / E21: a scout with a halt in its form AND an S1 gap -> Person(s1_gap) from `handoff`, never `halt`",
             (kind, "handoff" in [c[0] for c in calls]), ("s1_gap", True))
    calls, kind = driver_outcome("run_role", "halt", ok_digest, "qa-scout", None, "S1", "qa-scout",
                                 rework={"id": "d1", "reason": "x"})
    check_eq("a scout whose form halts and whose handoff is clean: the post-handoff read halts it", kind, "halt")
    calls, kind = driver_outcome("run_role", "halt", ok_digest, "qa-test-strategist", None, "S3", "qa-test-strategist",
                                 rework={"id": "d1", "reason": "x"}, dead=True)
    check_eq("a DEAD run (an error, no words) is not heard early: `handoff` owns it, the form halt is heard after it",
             ("handoff" in [c[0] for c in calls], kind), (True, "halt"))


def the_run_role_twins_hear_a_form_halt_too():
    """B-2. KILLS: `resume_role` or `_finish_saved_result` reading the digest alone (a person-answered form halt would end in
    a `finish` refusal, then the conductor)."""
    ok_digest = "qa-test-strategist S3 TC-1 · ok"
    calls, kind = driver_outcome("resume_role", "halt", ok_digest, "qa-test-strategist", None, "S3", "qa-test-strategist",
                                 "d1", "the answer")
    check_eq("resume_role: a form halt the person answered -> Person(halt), finish NOT called",
             (kind, "finish" in [c[0] for c in calls]), ("halt", False))
    calls, kind = driver_outcome("resume_role", "ok", ok_digest, "qa-test-strategist", None, "S3", "qa-test-strategist",
                                 "d1", "the answer")
    check_eq("resume_role control: no halt -> finish", (kind, "finish" in [c[0] for c in calls]), ("", True))
    calls, kind = driver_outcome("_finish_saved_result", "halt", ok_digest, "qa-test-strategist", None, {"result": "x"},
                                 "qa-test-strategist", "S3", "d1", {"scope": ["TC-1"]})
    check_eq("_finish_saved_result: a form halt -> Person(halt), stage_done halted, finish NOT called",
             (kind, "halted" in [c[2] for c in calls if c[0] == "py"], "finish" in [c[0] for c in calls]),
             ("halt", True, False))
    calls, kind = driver_outcome("_finish_saved_result", "ok", ok_digest, "qa-test-strategist", None, {"result": "x"},
                                 "qa-test-strategist", "S3", "d1", {"scope": ["TC-1"]})
    check_eq("_finish_saved_result control: no halt -> finish", (kind, "finish" in [c[0] for c in calls]), ("", True))


def one_predicate_says_a_packet_was_committed_outside_start():
    """F-5. KILLS: a second spelling of the field in `story_step`; a `start`-registered record counted as outside."""
    check_eq("one definition of the field", story_step.CONFIG_START_FIELD, launch_card.CONFIG_START_FIELD)
    check_eq("a record with the field is `start`'s", launch_card.outside_start({"config_sha256_at_start": "a" * 64}), False)
    check_eq("a record without it is outside `start`", launch_card.outside_start({"id": "x"}), True)
    check_eq("the value `absent` is a measurement, so `start`'s", launch_card.outside_start({"config_sha256_at_start": "absent"}), False)
    check_eq("not an object: not outside (the error direction: a door left unnamed)", launch_card.outside_start(None), False)


def main():
    a_committed_rework_packet_is_materialized_from_the_packet()
    a_normal_start_is_byte_identical_to_main()
    the_form_is_made_for_the_scope_of_the_packet()
    a_second_run_writes_nothing_and_a_differing_card_is_never_replaced()
    refusals_name_the_field_the_value_and_the_door()
    the_doors_are_named()
    the_changelog_fragment_names_the_change()
    a_record_that_differs_in_reason_is_refused_and_the_wording_is_the_events()
    a_driver_story_is_refused_as_start_refuses_it_and_is_not_stamped()
    materialize_derives_files_as_start_does_and_does_not_repeat_the_judge()
    the_s5_critic_card_names_the_settle_door_and_materialize_never_settles()
    a_declared_halt_is_never_accepted()
    the_halt_is_read_before_the_form_is_checked_and_after_the_decision()
    the_declared_halt_reader_battery()
    the_no_change_note()
    the_door_table_of_a_halt()
    a_dispatch_committed_before_this_change_has_no_files_and_finish_reads_its_form()
    the_driver_hears_a_form_halt_once_before_the_resume()
    the_run_role_twins_hear_a_form_halt_too()
    one_predicate_says_a_packet_was_committed_outside_start()
    finish("test_story_step_materialize")


if __name__ == "__main__":
    main()
