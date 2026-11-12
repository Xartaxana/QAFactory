"""One command per stage boundary: the orchestrator manages, it does not assemble requests.

On TP1-15045 the orchestrator spent 238 model turns before Gate A, most of them typing
controller requests by hand: `prepare`, copy `expected_revision` into a JSON file, `dispatch`,
`stage_done --status running`, and after the role `prepare` again, `accept`, `stage_done
--status done`, `next`. Every one of those is deterministic. This script runs each half as one
command and prints one short block the orchestrator acts on.

  story_step.py start  --task T --stage S2 --role qa-requirements-tester
        prepare -> dispatch (the stage guard runs inside) -> stage_done running
        -> judge pre-work for that role -> brief_pack.py (work/briefs/<ID>.md: the files
        to read and the commands; a failure is a note) -> the Agent prompt, verbatim, which is
        also written LAST to work/briefs/<ID>.launch.md (`dispatched` and the card's path are printed
        and flushed right after the dispatch: the command runs 34-112 s on a desktop host and its exec
        cell may yield first - then `where` answers `launch` with the card, see launch_card.py).
        S6 qa-runner, manual half: `--execution-kind manual --scope <1..5 ids>` prepares each case (`manual_evidence.py prepare`),
        registers the block as `manual_case_ids`, and a refusal lists every problem with the next block's ready command.
        [--parallel-window]   (the driver's scheduler only: an S5 window beside a running one; see the controller's admission)
  story_step.py materialize --task T --dispatch-id ID
        the brief, the handover form and the launch card of a running dispatch the controller committed
        OUTSIDE `start` (a `controller.py --operation rework` packet), written from that committed packet:
        no `prepare`, no `apply`, no `stage_done`, the log and the state untouched; the card last. Kept when
        present; a card that differs is refused, never replaced (TP2-2406 S3-3, 15.10.2026).
  story_step.py bind  --task T --dispatch-id ID --agent-id AID
        the host's id for the agent that IS running this dispatch, recorded where the
        resume guard and dispatch_liveness look for it. On Claude the plugin's hook runs it when the
        Agent call returns an id; by hand only on Codex or when the guard or `where` says unbound: on the 21.09 run the guard refused a follow-up because nothing had
        written `agent_id` into pipeline.json, and `start` cannot know it - the id exists
        only after the host has spawned the role.
  story_step.py finish --task T --dispatch-id ID --digest "<the role's digest line>"
        [--output work/extra.json ...] [--not-complete | --complete]
        [--window work/windows/ID.json]   (S5 completion; default: that file when present)
        [--open-windows <cases>]   (S5, with --not-complete: the other windows still open; the driver's parallel
        scheduler passes it, the controller checks each case is a real window of the stage)
        [--unresolved <why> --reason "<words>"]   (a window the critic could not close: the
        controller reads both off the completion; they go together and, on S5, not with --not-complete;
        without them the pair is derived when EVERY gap of the S5 window record is a
        `blocked_by_env:` or `handed_to_person:` instance, and from nothing else)
        evidence hashes -> accept -> stage_done done -> judge post-work -> next action. A role's declared
        halt (`header.verdict: halt|impossible` in its form, or a halting digest) is refused before any accept
        unless the person's decision on the dispatch is recorded (`decide`); the refusal names the doors.
  story_step.py decide --task T --dispatch-id ID --words-file <file> (--hand <cases> | --open [<ids>] | --close)
        the person's decision about a dispatch, recorded once and by code: the S5 cases they run themselves
        (manifest `unresolved[]` rows, the window rebuilt; `finish` derives the completion pair from them), or the
        stage's closing dispatch kept open on named work / closed as it is (`state/decisions/<ID>.json`, read by
        `finish`). Their words come from the file; nothing else of the story's state is written, no agent is called.
        A role that does not close its stage takes `--close` only when its FORM declares a halt (accept this work
        as it is; the stage follows its own rule), and never on S5.
  story_step.py pause  --task T --dispatch-id ID --reason "<why>" [--status blocked]
        checkpoint a dispatch that stops for the person (the S1 source review).
  story_step.py resume --task T --dispatch-id ID [--agent-id AID]
        the person answered: the SAME dispatch, stopped by `pause` (blocked / paused), is running again and its agent goes on
        (SendMessage to it). Replaces the `stage_done --status running` step; `finish` then accepts the work, `pause` can stop it
        again. A different agent is a new dispatch (the retry packet), not a resume.
  story_step.py where  --task T
        the next action, the stop marker and the judge's bill so far. For a desktop dispatch nothing
        shows was launched it answers `launch` and prints the card (rebuilding it from the brief and the
        handover form when `start` died before writing it), or `wait_start` while `start` is still at work -
        or, for a packet no `start` registered, `wait_start` naming `materialize` as the door.
  story_step.py card   --stage S<n>
        the stage's card (the `## Card` section of its phase file: the input, the commands, the exit), the VALUES of the
        config keys its `config:` line names (`config_view.py`), and the index of every other section of the phase file as
        `Read <path> offset=<a> limit=<b>` - read a section only where the card points, never the file whole. A stage
        with no card yet says so and names the whole file. Needs no story (S0's card is read before one has a root).

  story_step.py config-snapshot --task T   |   story_step.py config-restore --task T
        the copy of qa-factory/config.json a FRESH story keeps as it starts (S0), and its revert when the story ends (S9, `stop`) except
        what a recorded writer wrote in the story's window; one JSON line each (`config_contract.snapshot_config` / `restore_config`).

Nothing here decides: every rule still lives in controller.py, stage_guard.py and
stage_done.py, and a refusal from any of them is printed verbatim and ends the command.
The hand-typed path in references/controller-api.md stays valid and is the fallback.

`pipeline.stop_after` in config.json (`gate_A` or `gate_B`) makes `where` and `finish` answer
`stop` once that gate has been presented, instead of the next stage.

A judge script this build does not carry yet is a printed note, never a failure: the packages
that add them land one at a time, and a story must run before the last of them does.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import hooklib  # noqa: E402
import contract as C  # noqa: E402
import person_words  # noqa: E402
import runtime_paths as RP  # noqa: E402
import judge  # noqa: E402
import launch_card  # noqa: E402
import detector_verdict  # noqa: E402  (`joined`: a list in one line, the whole of it in a file past the ceiling)
import config_view  # noqa: E402  (`card_values`: the values of the config keys a stage card names, through the one config reader)
import grammar  # noqa: E402  (`_fence`: a code fence as CommonMark reads it, so `_sections` sees the headings `grammar.heading_lines` sees)
import stage_done  # noqa: E402  (`S3_REMARK_PREFIX`: the one head of the line `finish` keeps whatever follows it)
from controller import (Controller, MANUAL_BLOCK_CASES, MANUAL_WINDOW_CASES, S5_PLAN, SCOPE_SHOWN,  # noqa: E402
                        dispatch_life_key, lane_keys, manual_done_cases, s3_window_of, s5_part_of, stop_after, validate_manual_runner_block,
                        walk_lanes, with_stop_after)
from event_store import EventCommitted, IdempotencyKeyReused  # noqa: E402
from role_cli import REPAIR_MARKER  # noqa: E402

# The planned stop (`pipeline.stop_after`: STOP_VALUES, STOP_GATES, its one reader and its composition)
# lives in controller.py since HF1-8: the gate-decision answer applies the same marker as `where` and `finish`.


def _stages() -> dict:
    return {s["id"]: s for s in hooklib.load_ref_json("stages.json")["stages"]}


def _optional_row(stage_id: str, role: str, purpose):
    """The `optional_dispatches` row of the stage that admits `role` with `purpose`, or None - through the ONE reader
    (`stage_guard.optional_row`, AR-13; t-2277 FL-5). A blank purpose never matches."""
    import stage_guard
    return stage_guard.optional_row({"stages": list(_stages().values())}, stage_id, role, purpose)


def _task_root(task: str) -> Path:
    return hooklib.story_root(task, "story_step --task")  # a project never onboarded exits 3; a story that is not there is a refusal


def _wait(args) -> float:
    """How long this command's commits wait for an in-flight story writer: what `main` put on
    `args`, else 0. A caller that builds its own args (a test, the driver in-process) never gets
    a wait it did not ask for."""
    return getattr(args, "wait_seconds", 0.0)


def _config() -> dict:
    try:
        return hooklib.load_config() or {}
    except Exception:
        return {}


def _run(script: str, *args: str) -> tuple[int, str]:
    path = HERE / script
    if not path.is_file():
        # A package that has not landed yet. The stage runs exactly as it did before that
        # script existed, and the orchestrator is told which one was missing rather than
        # seeing a traceback it would then spend a turn diagnosing.
        return 0, f"{script} is not in this build - skipped, the role does the judgment itself"
    done = subprocess.run([sys.executable, "-B", str(path), *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    return done.returncode, (done.stdout + done.stderr).strip()


def _next(controller: Controller, read_only: bool = False) -> dict:
    # `next_action()` closes a dispatch it can prove was never launched; while a role may be
    # running that proof is a race, so a question asked mid-stage uses the pure reader.
    if read_only:
        state = controller.state()
        # B-20 (AR-13): the same pipeline `next` reads, so a standing acceptance record ends "S<n> awaits" for `where` too
        action = controller.with_resume_command(controller._next_action_for_state(state, controller._pipeline()), state)
    else:
        action = controller.next_action()
    return with_stop_after(action, stop_after())


def _judge_line(task: str) -> str:
    cfg = judge.settings()
    if cfg["provider"] == "none":
        return "judge: off"
    bill = judge.summary(cfg["project_root"], task)
    passed = len(judge.passes(cfg["project_root"], task))
    line = (f"judge: {cfg['provider']} {cfg['mode']} - {bill['questions']} questions, "
            f"{bill['decided']} decided, {bill['input_tokens']} tokens, ${bill['cost_usd']:.4f}")
    # Every block the judge let through is shown at each boundary as well as at the gate: a
    # pass nobody saw until the gate brief is a pass nobody could have questioned earlier.
    return line + (f", {passed} block(s) passed by the judge - both gate briefs list them"
                   if passed else "")


# What a role does with a judge file. It travels in the prompt because agents/*.md sit at
# their size cap, and because it only applies when the file exists.
JUDGE_GUIDANCE = {
    "qa-scout": "Judge: after collecting the task, subject, parent and normative sources and BEFORE you peek "
                "any mention, run `python <plugin>/scripts/judge_sources.py --output <inventory> --ticket <T>`. "
                "It peeks every pending mention and, in mode on, records the ones it is sure about exactly "
                "as `assess` would, collecting relevant ones in full. Then assess only mentions still "
                "`pending`; never re-argue a recorded one, the person reviews them all.",
    "qa-requirements-tester": "Judge: after writing the register run `python <plugin>/scripts/judge_requirements.py "
                              "--task-root <artifacts dir>`. When its first line says mode=on, build the "
                              "contradiction matrix from work/judge-requirements.json: examine `conflicts` and "
                              "`possible`, record the rest as `none (judge)`; read `comments_that_touch_scope` "
                              "first. When it says mode=shadow or is unavailable, work as without it.",
    "qa-test-strategist": "Judge: when work/judge-plan.json says mode on, start each row from its decided `level` "
                          "and spend your reasoning on the undecided rows; `impact` there is a hint in every "
                          "mode. work/judge-requirements.json lists requirement pairs and wording to keep in view.",
    "qa-case-critic": "Judge: work/judge-cases.json scored every pinned case on dimensions 3, 5, 7, 8. Mode on: "
                      "review every `needs_critic` case in full, starting from its flagged dimensions; for a "
                      "`clean` case check only dimensions 1, 2, 4, 6 and write `judge-assisted` in its roll-call "
                      "note. Mode shadow: review everything and ignore the file. A judge pass on dimension 8 is "
                      "never a sensitivity record.",
    "qa-automator": "Judge: before you write a `blocked_by_env` row, run `python <plugin>/scripts/judge_run.py "
                    "--task-root <artifacts dir> --remedy --error-head-file <the run log head> [--case TC-n]`. "
                    "Copy its `{kind, where, change, restart}` into the row's `remedy` - names only, never a "
                    "value. It suggests; the row is yours, and a remedy you cannot ground you leave out.",
    "qa-code-critic": "Judge: work/judge-code-{dispatch}.json screened every test function of this dispatch against the "
                      "rubric. Mode on: review every entry of `needs_critic` in full, starting from its flagged "
                      "dimensions, and for a `clean` test check only what the file does not score. Mode shadow: "
                      "review everything and ignore the file. Write `cause:` on each finding as usual - "
                      "`judge_code.py --cause --finding \"<text>\"` maps your words to the closed list.",
    "qa-runner": "Judge: for a manual-agent step whose Then you observed, "
                 "`python <plugin>/scripts/judge_results.py --observation --then \"<the Then>\" --observed "
                 "\"<what you saw>\"` says whether the two match. It never turns a fail into a pass: an "
                 "undecided or contrary answer is recorded as observed, and your own eyes win.",
    "qa-failure-analyst": "Judge: work/judge-triage.json holds a per-row verdict leaning, whether the case itself "
                          "contradicts the requirement, and a flaky mechanism where three reruns exist. Mode on: "
                          "start each row from it and spend your reasoning on the undecided ones. `APP_BUG` is "
                          "never decided there - you confirm every one of those against the register yourself. A "
                          "decided verdict on a test that went red against an approved case (`case_defect` "
                          "included) is a leaning too: it never replaces the control experiment your charter "
                          "asks of such a red.",
    "qa-bug-reporter": "Judge: work/judge-bugs.json pairs each draft with the existing bugs it may duplicate and "
                       "scores its priority from the damage line. A duplicate is a proposal to the person, never "
                       "a reason to drop a draft they chose.",
    "qa-retro-analyst": "Judge: for a recurring trap you are about to fold, `python "
                        "<plugin>/scripts/judge_results.py --trap \"<the paragraph>\"` says which document owns "
                        "it (test-strategy / framework-rules / faq / none). Audit A21 fails a section written to "
                        "two of them, so one owner or none.",
}

# Judge work a role cannot do for itself: the role has no shell, or the file must exist
# before the prompt is built. (script, args, output file) per role, run at `start`.
PRE_WORK = {
    "qa-case-critic": [("judge_cases.py", ("--task-root", "{root}"), "work/judge-cases.json")],
    "qa-test-strategist": [("judge_plan.py", ("--task-root", "{root}"), "work/judge-plan.json"),
                           (None, (), "work/judge-requirements.json")],
    "qa-scout": [(None, (), "work/judge-sources.json")],  # a re-dispatch sees what was judged
    "qa-code-critic": [("judge_code.py", ("--task-root", "{root}", "--dispatch", "{dispatch}"),
                        "work/judge-code-{dispatch}.json")],      # TR3-15: one file per critic dispatch (`judge_code.report_rel`)
    "qa-failure-analyst": [("judge_results.py", ("--task-root", "{root}", "--triage"),
                            "work/judge-triage.json")],
    "qa-bug-reporter": [("judge_results.py", ("--task-root", "{root}", "--bugs"),
                         "work/judge-bugs.json")],
}


RESUMED_PREFIX = "You are resumed"   # the first words of the line `_resumed_lines` writes; `_prompt` reads them


def _prompt(task: str, stage: dict, role: str, dispatch_id: str, extras: list, brief: str = "",
            form: str = "", packet_lines: tuple = ()) -> str:
    base = f"qa-factory/artifacts/{task}/"
    # `project:readiness.json` / `project:state/journal.jsonl` are the data file's spellings; the
    # prompt names the path where the file really is (runtime_paths, t-232 section 8).
    inputs = [("qa-factory/" + RP.project_alias(hooklib.project_root(), i[len("project:"):])) if i.startswith("project:") else base + i
              for i in stage.get("inputs", [])]
    lines = [f"You are {role}. Ticket: {task}. Dispatch: {dispatch_id}.",
             f"Artifacts dir: {base}", "Inputs:"] + [f"  {p}" for p in inputs + extras]
    # What the committed packet says about THIS dispatch (a rework: whose work, why, which plan rows), after the
    # inputs and before the handover: empty for every dispatch `start` registers, so its prompt is unchanged.
    lines += list(packet_lines)
    if form:
        # The handover is a file, not a sentence: every section, every allowed value and every
        # artifact path is already in it. What the role cannot fill goes under `blocked` and to
        # the conductor - never to the person, and never as a guessed word.
        lines.append(f"Your handover is the form {form}. Fill it as you work; what code could "
                     f"already answer is filled in.")
        # The one reader of "may a text send this role to a script" is `host_adapter.role_has_bash` (the guard
        # refuses by the same line; the brief, the injection and the driver's note ask it too). Imported here, not at
        # module level, so `story_step` never depends on the guard's modules before `main()` runs.
        from host_adapter import role_has_bash
        if role_has_bash(role):
            lines += [
                # This copy's own scripts, by absolute path: the prompt is text no host expands, and
                # the copy that composed it is the one whose checker the role must run (B-014).
                f"  when it is filled: python \"{HERE.as_posix()}/handoff_check.py\" "
                f"--file {form} --task {task} --fix",
                "  it refuses with the field, the problem and the values YOUR role may write; "
                "nothing it says is about the quality of your work",
                f"  what you cannot fill: put it under `blocked` and run handoff_help.py "
                f"--file {form} - the conductor answers, you never ask the person"]
        else:
            # TP2-2406 S4-6/S4-7, 14.10: the lines above sent the case designer (tools: Read, Grep, Glob,
            # Write, Edit - no Bash) to `python .../handoff_check.py`; the role guard (host_adapter.role_policy)
            # refused the call twice in each child and both halted with the form untouched. A role without a shell
            # is never told to run a script: it fills the form with Edit, and `finish` runs the checker by code
            # (`_handoff_check`). Which tool does that on which host is said by the injection and the brief
            # (host_adapter.CODEX_DESKTOP_TOOLS), not here: the prompt is built before the host is known.
            lines += [
                "  fill it with Edit, one field's own lines at a time (a Write over the existing form "
                "is refused); do not run the checker - `story_step finish` validates the form",
                "  what you cannot fill: put it under `blocked` - the conductor answers, you never "
                "ask the person"]
    resumed = any(str(line).startswith(RESUMED_PREFIX) for line in packet_lines)
    if brief and not resumed:
        # The brief names the files to read and every command with its argument shape
        # (brief_pack.py), so the role reads instead of searching. Project-relative like
        # every other path of this prompt: the role's cwd is the project root. A RESUMED role reads its delta, and its
        # resumed line already names this brief as the fallback (SC1-14 fix X, F-1: one instruction, not two).
        lines.append(f"Read {brief} first; it names the files and the commands.")
    if role in JUDGE_GUIDANCE and judge.active():
        lines.append(JUDGE_GUIDANCE[role].replace("{dispatch}", dispatch_id))
    lines.append("Return your digest line only.")
    return "\n".join(lines)


# Where a dispatch's brief and handover form are inside the task folder: ONE spelling for the path code
# writes and tests and for the project-relative path a prompt or a note prints (FR-37).
BRIEF_REL = "work/briefs/{dispatch_id}.md"
FORM_REL = "work/handoffs/{dispatch_id}.yaml"
DELTA_REL = "work/briefs/{dispatch_id}-delta.md"   # what a resumed role reads instead of the whole brief (written by brief_pack, SC1-14 C2)


def _project_rel(task: str, template: str, dispatch_id: str) -> str:
    """The project-relative path of a dispatch's brief or form - the spelling every path of a prompt has."""
    return f"qa-factory/artifacts/{task}/" + template.format(dispatch_id=dispatch_id)


def _author_argv(stage_id: str, role: str, contract: str, task_root: Path) -> list:
    """`["--author-dispatch", id]` when the form's contract holds the author token and the dispatch the role reviews
    (`brief_pack.reviewed_dispatch`) is known, else []. Never raises: every doubt is no argument."""
    try:
        import handoff
        name = contract or handoff.contract_of(stage_id, role, "")
        if not name:
            return []
        if handoff.AUTHOR_TOKEN not in handoff.template(name).text():
            return []
        from controller import Controller
        import brief_pack
        pipeline = _read_pipeline(Path(task_root))      # the module's one reader (utf-8-sig, a dict or {}), as brief_pack._load
        # TR4-12 (2): the ONE reader the brief line uses (a stage critic's own stage author; a consumer's awaiting author, S7/S8)
        author = brief_pack.reviewed_dispatch_id(stage_id, role, Controller(task_root).state(), pipeline)
    except Exception:                                   # noqa: BLE001 - an unreadable state is an unknown author
        return []
    return ["--author-dispatch", str(author)] if author else []


def _handoff_form(task: str, stage_id: str, role: str, dispatch_id: str, task_root: Path,
                  scope: str) -> tuple:
    """(project-relative form path or "", note). The empty handover form, from the contract.

    A handover with no contract in `handoffs/index.yaml` is not an error of the story: the
    role works as it always did and the note says which pair has no contract yet, which is
    how a gap in the factory becomes visible instead of becoming a guessed form.
    """
    # The form is the contract of the dispatch's PURPOSE when the registry has one (S5's plan dispatch, `s5_plan`), else the stage's
    # usual one: an empty answer leaves the call exactly as it was (`handoff_init` looks the usual contract up itself).
    record = _dispatch_record(task_root, dispatch_id)
    contract = _purpose_contract(stage_id, role, record)
    argv = ["--contract", contract] if contract else []
    # A repair dispatch (the record has `rework_of`) repeats accepted work on the same inputs: its form carries the accepted
    # parent's whole-stage answers (HF9-2). Only when the parent's form is on disk; a primary dispatch gets today's argv.
    parent = str(record.get("rework_of") or "") if isinstance(record, dict) else ""
    parent_form = task_root / FORM_REL.format(dispatch_id=parent) if parent and Path(parent).name == parent else None
    if parent_form is not None and parent_form.is_file():
        argv += ["--carry-from", str(parent_form)]
    # RN1-2 (F-4): an S3 rework is sent for named plan rows (the controller's record, `plan_rows`): their ids are a value code
    # knows, so the form arrives with them. S3 only - the other stages' `scope` ids are case or instance ids, not plan rows.
    rows = record.get("plan_rows") if isinstance(record, dict) else None
    if parent and stage_id == "S3" and isinstance(rows, list):
        named = [str(item).strip() for item in rows if isinstance(item, (str, int)) and str(item).strip()]
        if named:
            argv += ["--rows", ",".join(named)]
    # F1 (B-2): a stage critic's contract (S2-S4) carries the token `<the author's dispatch>`; the author's last accepted dispatch is a
    # value code knows (the same function `stage_done` compares with). Unknown or unreadable state -> no argument, the token stays
    # a placeholder (FR-59: a guessed author never stands in a form).
    argv += _author_argv(stage_id, role, contract, task_root)
    code, out = _run("handoff_init.py", "--task", task, "--stage", stage_id, "--role", role,
                     "--dispatch", dispatch_id, "--scope", scope or "",
                     "--task-root", str(task_root), *argv)
    rel = _project_rel(task, FORM_REL, dispatch_id)
    if code == 0 and (task_root / FORM_REL.format(dispatch_id=dispatch_id)).is_file():
        # The form is written, and a loud line of handoff_init (SC1-2 F11 (b): an old values file that could not be moved
        # aside will meet this form) is a note the conductor and the person read; it is never dropped on success.
        loud = [line.strip() for line in out.splitlines()
                if line.startswith("handoff_init: ") and "remove it before the role starts" in line]
        return rel, " ".join(loud + _plan_form_gap(role, _dispatch_record(task_root, dispatch_id), contract))
    return "", (out.splitlines()[0] if out else f"handoff_init exit {code}")


def _purpose_of(record) -> str:
    """The purpose word a dispatch RECORD was made with (`request_binding.purpose`, never the top of the record), or ''."""
    binding = record.get("request_binding") if isinstance(record, dict) else None
    return str(binding.get("purpose") or "") if isinstance(binding, dict) else ""


def _purpose_contract(stage_id: str, role: str, record) -> str:
    """The contract id registered for this dispatch's PURPOSE (`handoff.contract_of(..., purpose=...)`), or '' when the dispatch
    has no purpose, none is registered for it, or the registry cannot be read (the caller then keeps today's lookup). THE one
    place the form is told by purpose: `_handoff_form` writes by it and `_form_owed` asks by it (AR-15)."""
    purpose = _purpose_of(record)
    if not purpose:
        return ""
    try:
        import handoff
        return handoff.contract_of(stage_id, role, purpose=purpose)
    except Exception:
        return ""


def _plan_form_gap(role: str, record, contract: str) -> list:
    """A one-line note when a PLAN dispatch got the stage's usual form because the registry names no contract for the plan: a gap of the
    factory is told, never silently the window's form (only `s5_plan` is a registered purpose, so only it is told)."""
    if contract or _purpose_of(record) != S5_PLAN:
        return []
    return [f"handoff: no contract is registered for purpose {S5_PLAN} ({role}) in handoffs/index.yaml; the stage's usual form was written"]


def _findings_file(task_root: Path, dispatch_id: str, suffix: str) -> Path:
    """`state/findings/<dispatch id made file-safe><suffix>` of the story: where a list too long for one line is kept whole
    (the form problems `-form.txt`, the exit gate's refusal `-finish.txt`). THE spelling of that path in this file."""
    return task_root / "state" / "findings" / (re.sub(r"[^A-Za-z0-9._-]+", "_", dispatch_id) + suffix)


def _handoff_check(task: str, dispatch_id: str, task_root: Path) -> tuple:
    """(status, note, rel path). `status` is one of: none, untouched, green, problems."""
    rel = FORM_REL.format(dispatch_id=dispatch_id)
    form = task_root / rel
    if not form.is_file():
        return "none", "", ""
    code, out = _run("handoff_check.py", "--file", str(form), "--task", task,
                     "--task-root", str(task_root), "--fix", "--json")
    report = hooklib.read_document(out)      # t-2020: `handoff_check --json` prints a PRETTY object (indent=1): the document reader; a stderr warning does not hide it
    if report is None:
        # an answer nobody could read is an unknown, never a pass of the form gate (AR-28, FR-59); the form is there, so it is a problem
        # whose door is the form doors below (`--ignore-handoff`), not a silent "no form"
        return "problems", f"handoff_check gave no readable answer (exit {code}): {(out.splitlines() or ['no output'])[-1][:200]}", rel
    if report.get("untouched"):
        return "untouched", "", rel
    filled = [f"filled by code: {line}" for line in report.get("fixed") or []]
    if not report.get("problems"):
        return "green", "; ".join(filled[:3]), rel
    # EVERY problem of the form, not the first four (12586: "4 fields", then "5 more findings" - a cut is a round):
    # `joined` is the one-line twin of `render`, it names a file with the whole list past its ceiling. Only `path` and
    # `problem` are read from an item (another producer may add keys, AR-22); an item without them is its own text.
    items = [f"{p['path']}: {p['problem']}" if isinstance(p, dict) and "path" in p and "problem" in p else str(p)
             for p in report["problems"]]
    whole = _findings_file(task_root, dispatch_id, "-form.txt")
    problems = detector_verdict.joined(items, noun="form problem", full_path=whole,
                                       max_chars=detector_verdict.FINDINGS_MAX_BYTES, sep="; ")
    return "problems", "; ".join(filled[:2] + [problems]), rel


def _brief(task: str, stage_id: str, role: str, dispatch_id: str, task_root: Path) -> tuple:
    """(project-relative brief path or "", note). Written by brief_pack.py once the dispatch
    is registered - it reads the dispatch's scope from the controller. A failure is a note:
    the role then works from the prompt's inputs, as every role did before the brief."""
    code, out = _run("brief_pack.py", "--task", task, "--stage", stage_id, "--role", role,
                     "--dispatch", dispatch_id)
    rel = _project_rel(task, BRIEF_REL, dispatch_id)
    if code == 0 and (task_root / BRIEF_REL.format(dispatch_id=dispatch_id)).is_file():
        return rel, (out.splitlines()[-1] if out else "")
    tail = out.splitlines()[-1] if out else f"exit {code}"
    return "", f"brief_pack: no brief for {dispatch_id} ({tail}) - the role works from the inputs above"


# Generated inputs a role is about to need, written by code before the dispatch. `traceability.py
# --write` was named in the scribe's charter and in the S8 phase file and called by NOTHING on the
# path: when the role skipped it, `work/traceability.json` simply did not exist, the report's
# appendix was hand-written, and no check anywhere said a generated table was missing (the loose
# end of plan section 9). A generated artifact is code's to write, and the only reliable moment is
# the one before its reader starts.
DERIVED_BEFORE = {
    "qa-doc-scribe": [("traceability.py", ("--task", "{task}", "--write"))],
}


def _derive_before(task: str, role: str, task_root: Path) -> list:
    notes = []
    for script, argv in DERIVED_BEFORE.get(role, []):
        code, out = _run(script, *[a.format(task=task, root=str(task_root)) for a in argv])
        line = (out.splitlines() or [""])[-1][:160]
        notes.append(f"{script}: {line}" if code == 0 else
                     f"{script} exit {code}: {line} — the role writes over a table that is not "
                     "there; fix this before reading its report")
    return notes


# --- the probe debt of the S5 critic (B-207 P6-B, R13, V1) -------------------------------------------
# On TP1-13797 (cmp1) the critic's first window probed 16 instances and every probe passed, yet not
# one receipt stood: the probe measured one sha256 of the test file and the manifest bound another, so
# "Proven" fell from 24 to 8 on the factory's own bookkeeping. `probe_debt.py --settle` clears what code
# may clear (rebind, then a fresh probe) and writes the rest to `work/probe-debt/<dispatch>.json`; here it is RUN,
# because the only moment that reliably comes before the critic's first turn is its own `start`, and the
# conductor is never asked to run it (P3, FR-48). The skill road runs `start` through a shell call that
# times out at 120 s (V1), so the budget (about 90 s, `probe_debt.SETTLE_BUDGET_S`) is the budget of the
# WHOLE `start`: the settle is handed what is left of it (`--budget-s`), measured from the top of `start`,
# and never more. It then keeps to that itself - it does not begin a probe that cannot fit, and a probe
# that has begun ends by its own `--timeout` (see probe_debt.py), never by a kill. `start` only SAYS
# when the settle took long.
DEBT_STAGE, DEBT_ROLE = "S5", "qa-code-critic"
# TR3-15: the debt is one file per critic dispatch (`probe_debt.debt_rel`, the ONE spelling); a story from before has the one old file
# (`probe_debt.OLD_DEBT_REL`), read as a fallback by `_debt_path` and never written.
SETTLE_NOTE_AFTER_S = 60   # a person reads the console: over this, the note says how long the settle took
SETTLE_MIN_LEFT_S = 1      # less than this is left of the budget: the settle is not started at all
_settle_clock = time.monotonic   # the test swaps it; a duration is never read off a real wait there


def _settle_budget():
    """probe_debt's own budget in seconds, or None when that module cannot be read (then the settle is
    run without a figure, and whatever is wrong with probe_debt is told by its own failure note)."""
    try:
        import probe_debt
        return float(probe_debt.SETTLE_BUDGET_S)
    except Exception:
        return None


def _debt_path(task_root: Path, dispatch_id: str) -> str:
    """The task-relative debt file THIS critic dispatch reads, whether or not it exists: its own (`probe_debt.debt_rel`); absent, the
    old single file of a story from before (the same rule as today for it: `_debt_input` still refuses a file written for another
    dispatch). Never another window's file - the critic of one window names only its own."""
    import probe_debt
    own = probe_debt.debt_rel(dispatch_id)
    return own if (task_root / own).is_file() else probe_debt.OLD_DEBT_REL


def _debt_input(task: str, task_root: Path, dispatch_id: str) -> tuple[list, list]:
    """([prompt input] or [], [note]): the debt file is an input of the critic only when it lists
    something. An empty file (no `left`, no `outcomes`) is not an input: the critic would be told to
    read a page that says nothing, and a settle that cleared everything leaves exactly that. A file
    that cannot be read is told in a note and is no input (FR-41: unknown is not `nothing owed`).
    Reads ONLY its own dispatch's file (`_debt_path`); the old single file only when its own is absent."""
    rel = _debt_path(task_root, dispatch_id)
    path = task_root / rel
    if not path.is_file():
        return [], []
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return [], [f"{rel} exists but cannot be read ({type(exc).__name__}): it is not given to "
                    f"the critic; `probe_debt.py --task {task}` lists the debt read-only"]
    if not isinstance(doc, dict):
        return [], [f"{rel} is not a JSON object: it is not given to the critic; "
                    f"`probe_debt.py --task {task}` lists the debt read-only"]
    if not (doc.get("left") or doc.get("outcomes")):
        return [], []
    if doc.get("dispatch") != dispatch_id:
        # A file an EARLIER critic's settle left (this settle failed, or was not run): its commands name
        # that dispatch, which is not open any more, so the probes would be refused. Never given to this
        # critic; the note says where the debt can be read afresh.
        return [], [f"{rel} was written for dispatch {doc.get('dispatch') or '(none named)'}, not for "
                    f"{dispatch_id}: it is not given to the critic; `probe_debt.py --task {task}` lists "
                    "the debt read-only"]
    return [f"qa-factory/artifacts/{task}/{rel}"], []


def _settle_probe_debt(task: str, stage_id: str, role: str, dispatch_id: str, task_root: Path,
                       started: float, purpose: str = "") -> tuple[list, list]:
    """(extra prompt inputs, notes). Only for the S5 code critic; every other (stage, role) gets
    `([], [])` and runs nothing. `started` is the clock reading at the top of `start`: what the settle
    is given is the budget minus what `start` has used since. A settle that exits non-zero or crashes is
    a note and never a stop (P1): the critic still starts, and what the settle did not clear is the
    critic's own work."""
    if (stage_id, role) != (DEBT_STAGE, DEBT_ROLE):
        return [], []
    if _is_plan_dispatch(task_root, dispatch_id, purpose):
        # The plan critic judges a plan, not tests: there is no code to screen and no probe to settle (the debt belongs to the
        # windows). Neither the judge of `_pre_work` nor this settle runs for it.
        return [], ["plan dispatch: no code to judge or probe"]
    notes = []
    argv = ["--task", task, "--settle", "--dispatch", dispatch_id]
    began = _settle_clock()
    budget = _settle_budget()
    if budget is not None:
        left = budget - (began - started)
        if left < SETTLE_MIN_LEFT_S:
            extras, more = _debt_input(task, task_root, dispatch_id)
            return extras, [f"probe_debt --settle was not run: this start had already used {began - started:.1f} s "
                            f"of its {budget:g} s; the critic starts with the debt file as it stands "
                            f"(`probe_debt.py --task {task}` lists what is owed)"] + more
        argv += ["--budget-s", f"{left:.1f}"]
    try:
        code, out = _run("probe_debt.py", *argv)
    except Exception as exc:   # a process that could not even start is told, like a non-zero exit
        code, out = None, f"{type(exc).__name__}: {exc}"
    took = _settle_clock() - began
    if code != 0:
        tail = " ".join((out.splitlines() or [""])[-1].split())[:200] or "no output"
        notes.append(f"probe_debt --settle did not finish ({'exit ' + str(code) if code is not None else 'did not run'}: "
                     f"{tail}); the critic starts all the same, and `probe_debt.py --task {task}` "
                     "lists what is owed")
    if took > SETTLE_NOTE_AFTER_S:
        notes.append(f"probe_debt --settle took {took:.1f} s (its own budget is about 90 s; it never "
                     "stops a probe that has begun)")
    extras, more = _debt_input(task, task_root, dispatch_id)
    if code == 0:
        # P2-2: a settle that found every item as the last one left it started nothing and says so; the file it
        # re-addressed to this dispatch names the one it stood on (`unchanged_since`)
        try:
            doc = json.loads((task_root / _debt_path(task_root, dispatch_id)).read_text(encoding="utf-8-sig"))
            since = doc.get("unchanged_since") if isinstance(doc, dict) and doc.get("dispatch") == dispatch_id else ""
            why = sorted({str(l.get("reason")) for l in doc.get("left") or [] if isinstance(l, dict) and l.get("reason")}) \
                if since else []
        except (OSError, ValueError):
            since, why = "", []
        if since:
            notes.append(f"probe_debt --settle: nothing changed since {since}, not run"
                         + (f" (each item stays as it was left: {', '.join(why)})" if why else ""))
    return extras, notes + more


def _s5_plan_init(task: str, task_root: Path, controller: Controller, dispatch_id: str) -> list:
    """Notes. The skeleton `work/s5-plan.json` of the S5 PLAN dispatch of the author (SC1-14 C1): `s5_plan.init` for a dispatch that
    begins the plan, `s5_plan.refresh` for a rework of it (the author's rows stay). Any other dispatch: `[]`, nothing is read or
    written. The dispatch is read from the controller's RECORD, so the call is only made after `apply` - a refused `start` has no
    record and writes no skeleton. A plan that cannot be written is a note with its door, never a stop (P1): the dispatch is
    already on record and the author can write the plan itself (`s5_plan.py --init` is the door)."""
    record = (controller.state().get("dispatches") or {}).get(dispatch_id)
    if not (isinstance(record, dict) and record.get("stage") == "S5" and record.get("role") == "qa-automator"
            and s5_part_of(record) == "plan"):
        return []
    import s5_plan as SP
    try:
        plan = SP.refresh(task_root, controller) if record.get("rework_of") else SP.init(task_root, controller)
    except (SP.PlanUnreadable, OSError) as exc:
        return [f"plan skeleton not written: {exc}; fix that, then run: python \"{HERE.as_posix()}/s5_plan.py\" --task {task} --init"]
    rows = len(plan.get("cases") or []) if isinstance(plan, dict) else 0
    return [f"plan skeleton: {SP.PLAN_REL} ({rows} case row(s))" if rows else
            "plan skeleton: S5 has no case in scope, so no plan is owed"]


def _is_plan_dispatch(task_root: Path, dispatch_id: str, purpose: str = "") -> bool:
    """Is this dispatch the S5 PLAN dispatch? `purpose` is what the caller is about to register (`start`, before the record
    exists); with none given, the record's own kind (`s5_part_of`, the one reader) - so a packet `materialize` writes is read too."""
    return purpose == S5_PLAN or s5_part_of(_dispatch_record(task_root, dispatch_id)) == "plan"


def _pre_work(role: str, task_root: Path, dispatch_id: str, purpose: str = "") -> list:
    """Judge work that belongs before a role starts: runs the scripts, returns their notes. What the
    role is then given is `_prompt_inputs`' to say, from what is on disk. The plan dispatch of S5 has no code to judge:
    nothing runs for it (`_settle_probe_debt` says so)."""
    notes = []
    if not judge.active() or not PRE_WORK.get(role):
        return notes
    if _is_plan_dispatch(task_root, dispatch_id, purpose):
        return notes
    for script, argv, _ in PRE_WORK.get(role, []):
        if script:
            code, out = _run(script, *[a.format(root=str(task_root), dispatch=dispatch_id) for a in argv])
            notes += (out.splitlines()[:1] or [f"{script} exit {code}"])
    return notes


def _prompt_inputs(task: str, stage_id: str, role: str, task_root: Path, dispatch_id: str) -> list:
    """The extra inputs of a role's prompt, read from what is on disk and nothing else (no script is
    run): the judge outputs of `PRE_WORK` - only while the judge is active, a file left from an earlier
    run is no input of a judge that is off - then, for the S5 critic, the probe-debt file when it lists
    something for this dispatch. `start` calls it after its scripts ran, and `where` calls it to rebuild
    a launch card: ONE formula, so the rebuilt card is the card `start` would have written."""
    base = f"qa-factory/artifacts/{task}/"
    extras = []
    if _is_plan_dispatch(task_root, dispatch_id):
        return extras      # SC1-14 fix X, F-2: the plan has no code, so no judge output and no debt are its inputs
    if judge.active():
        extras += [base + output.replace("{dispatch}", dispatch_id) for _, _, output in PRE_WORK.get(role, [])
                   if (task_root / output.replace("{dispatch}", dispatch_id)).is_file()]    # `{dispatch}`: one judge file per critic dispatch (TR3-15)
    if (stage_id, role) == (DEBT_STAGE, DEBT_ROLE):
        extras += _debt_input(task, task_root, dispatch_id)[0]
    return extras


def _stale(product: Path, screen: Path) -> bool:
    """The screen was never written, or was written before the thing it screens."""
    if not product.exists():
        return False
    return not (screen.is_file() and screen.stat().st_mtime >= product.stat().st_mtime)


def _post_work(task: str, stage_id: str, role: str, task_root: Path) -> list:
    notes = []
    if not judge.active():
        return notes
    if role == "qa-requirements-tester":
        # The role runs this itself when judge.mode is `on`; in `shadow` nobody did, and the
        # comparison record is still wanted. Never twice over an unchanged register.
        if _stale(task_root / "work/requirements-register.md", task_root / "work/judge-requirements.json"):
            code, out = _run("judge_requirements.py", "--task-root", str(task_root))
            notes += out.splitlines()[:1]
    if role in ("qa-failure-analyst", "qa-doc-scribe"):
        # Gate B shows the bug list, and gate B comes BEFORE qa-bug-reporter's own pre-work.
        # Screening the drafts here is what puts the duplicate and the priority in front of
        # the person while the choice is still theirs to make.
        if _stale(task_root / "work/bug-drafts", task_root / "work/judge-bugs.json"):
            code, out = _run("judge_results.py", "--task-root", str(task_root), "--bugs")
            notes += out.splitlines()[:1]
    return notes


# --- run mode (B-014): one story is run by one mode ------------------------------------------------
# The driver (`story_run.py`) and a desktop session run the same package differently - a driver
# child gets `CLAUDE_PLUGIN_ROOT` and its hooks from `--plugin-dir`, a desktop session from the host's
# install - and a story that changes hands between them mid-way keeps state the other mode wrote
# under other assumptions. The mode is stamped once, into `pipeline.run_mode`; a later `start` in
# another mode refuses until a person's word passes it (`stage_overrides[]`, block "mode switch").
RUN_MODE_ENV = launch_card.RUN_MODE_ENV   # one definition: the launch action reads the same variable
import waiver  # noqa: E402  (the one definition of the block name, t-722 N5)
from hooklib import sorted_paths  # noqa: E402
MODE_SWITCH = waiver.MODE_SWITCH_BLOCK


def current_run_mode() -> str:
    """`driver` when the driver started this process (it exports the variable), else `desktop`."""
    return os.environ.get(RUN_MODE_ENV, "").strip() or "desktop"


def run_mode_switch(pipeline: dict, stage: str, mode: str) -> dict | None:
    """The stamped mode and this one, when they differ and no live "mode switch" override of the
    person covers `stage`; None otherwise. A pipeline with no `run_mode` has no switch to refuse: it
    adopts the current mode (`stamp_run_mode`). A revoked override is not honoured."""
    stamped = (pipeline or {}).get("run_mode")
    if not isinstance(stamped, dict) or not str(stamped.get("mode") or "").strip():
        return None
    if str(stamped["mode"]).strip() == mode:
        return None
    for override in (pipeline.get("stage_overrides") or []):
        if (isinstance(override, dict) and override.get("stage") == stage
                and override.get("match") == MODE_SWITCH and not override.get("revoked_at")
                and str(override.get("decision") or "").strip()):
            return None
    return {"stamped": stamped, "current": mode, "stage": stage}


def run_mode_refusal(task: str, switch: dict) -> str:
    """FR-1/FR-57: what differs, what was expected, and the door - the person's word, recorded by
    the command that records it. Written for the orchestrator or the driver, never for a role."""
    stamped = switch["stamped"]
    version = str(stamped.get("plugin_version") or "").strip()
    return (f"story_step: refused - this story was started in `{stamped.get('mode')}` mode"
            + (f" (package {version}, {stamped.get('plugin_root') or 'root unknown'})" if version or stamped.get("plugin_root") else "")
            + f" and this call runs in `{switch['current']}` mode; the stages of one story are run by "
            f"one mode. Run it the way it was started, or record the person's word for the switch: "
            f"python \"{HERE.as_posix()}/waiver.py\" --task {task} --stage {switch['stage']} "
            f"--block \"{MODE_SWITCH}\" --decision \"<their words>\"")


def stamp_run_mode(pipeline_path: Path, pipeline: dict, mode: str) -> None:
    """Stamp `pipeline.run_mode` when the story has none: {mode, plugin_root, plugin_version, since}."""
    if not pipeline or isinstance(pipeline.get("run_mode"), dict):
        return
    try:
        import story_version
        version = story_version.installed_version()
    except Exception:
        version = ""
    pipeline["run_mode"] = {"mode": mode, "plugin_root": str(HERE.parent), "plugin_version": version,
                            "since": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    pipeline_path.write_text(json.dumps(pipeline, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _read_pipeline(task_root: Path) -> dict:
    try:
        data = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


# --- the boundary detector for qa-factory/config.json (B-193, R-A6) ----------------------------------
# The command every window runs lives in the project's config.json, and on the TP1-13797 S5
# marathon a role edited it mid-dispatch with no one seeing it until the run was over. `start` records
# what the file was; `finish` says whether it still is. It REPORTS - it never refuses, never reverts,
# and never says who changed the file: the orchestrator's own legitimate edit (a profile fixed after a
# `launch:` digest) shows up too, and telling the two apart is the reader's judgment, not ours.
# The value is a sha256 hex digest, or `absent` (no file), or `unreadable: <reason>` (a directory in
# its place, a permission error): a cause that stops us measuring is stored as itself, never as a hash.
CONFIG_START_FIELD = launch_card.CONFIG_START_FIELD   # one definition: `launch_card.outside_start` reads the same field
CONFIG_ABSENT = "absent"
CONFIG_UNREADABLE = "unreadable: "
_HEX = frozenset("0123456789abcdef")


def config_fingerprint() -> str:
    """The project's qa-factory/config.json as one string: hex sha256 of its bytes, `absent`, or
    `unreadable: <reason>`. Reads only; never raises (a detector must not fail a stage boundary)."""
    try:
        path = hooklib.config_path()
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return CONFIG_ABSENT
    except Exception as exc:  # PermissionError, IsADirectoryError, a broken root - all "cannot tell"
        reason = " ".join(f"{type(exc).__name__}: {exc}".split())[:200]
        return CONFIG_UNREADABLE + reason


def _fingerprint_measured(value) -> bool:
    """True for a value that says what the file was: a hex digest or `absent`. Unreadable, missing,
    or anything unrecognised means the file was not measured at that end."""
    return isinstance(value, str) and (value == CONFIG_ABSENT
                                       or (len(value) == 64 and set(value) <= _HEX))


def config_finding(dispatch_id: str, dispatch: dict) -> list:
    """The `finish` notes about config.json for one dispatch: [] when it is unchanged (nothing is
    printed for a silent pass), one line when it changed, one line saying `not measured` and why when
    either end could not be read or the record carries no start value (FR-41: unknown is not
    `unchanged`, and it is not `changed` either)."""
    at_start = (dispatch or {}).get(CONFIG_START_FIELD)
    now = config_fingerprint()
    reasons = []
    if at_start is None:
        reasons.append("its record has no start hash (started before this check, or created by a "
                       "rework or relaunch packet)")
    elif isinstance(at_start, str) and at_start.startswith(CONFIG_UNREADABLE):
        reasons.append("unreadable at start (" + at_start[len(CONFIG_UNREADABLE):] + ")")
    elif not _fingerprint_measured(at_start):
        reasons.append("the start value in its record is not a hash")
    if now.startswith(CONFIG_UNREADABLE):
        reasons.append("unreadable at finish (" + now[len(CONFIG_UNREADABLE):] + ")")
    if reasons:
        return [f"config.json: not measured for {dispatch_id} - " + "; ".join(reasons)]
    return [] if at_start == now else [f"config.json changed during {dispatch_id}"]


def config_story_fresh(task_root: Path) -> tuple:
    """`(fresh, why)`: a story is FRESH when its `pipeline.json` and `state/controller.json` record no stage that has begun and no
    dispatch (B4). A file that is there and cannot be read is not fresh - an unknown is not "nothing recorded" (FR-59). The ONE
    reading, for the driver's story start and for `config-snapshot` alike (AR-19): a copy of config.json is kept only at a real start."""
    for rel in ("pipeline.json", "state/controller.json"):
        path = Path(task_root) / rel
        if not path.exists():
            continue
        data = hooklib.read_json(path, kind=dict)
        if data is None:
            return False, f"{rel} could not be read"
        stages = data.get("stages") if isinstance(data.get("stages"), dict) else {}
        if any(isinstance(row, dict) and str(row.get("status") or "") not in ("", "pending", "not_started") for row in stages.values()):
            return False, f"{rel} records a stage that has begun"
        if data.get("dispatches"):
            return False, f"{rel} records a dispatch"
    return True, ""


def _take_config_copy(project, task_root) -> dict:
    """THE start core (AR-19): the copy a FRESH story keeps, by `snapshot_config`'s result. The driver (`keep_config_copy`) and the
    skill path (`config-snapshot`) both end here."""
    import config_contract
    fresh, why = config_story_fresh(task_root)
    return config_contract.snapshot_config(project, task_root, fresh, why)


def _give_back_config(project, task_root) -> tuple:
    """THE end core (AR-19): `(result, line)` of `restore_config` and its report line. Never raises (`restore_config` does not).
    The driver (`give_back_config`) and the skill path (`config-restore`) both end here."""
    import config_contract
    result = config_contract.restore_config(project, task_root)
    return result, config_contract.revert_line(result)


def keep_config_copy(project, task_root, task: str) -> None:
    """The driver's story START: the copy a FRESH story keeps (the S0 stops re-enter here and find it kept). A failure is a line,
    never a stop (P1: any exception, so the story starts either way)."""
    try:
        kept = _take_config_copy(project, task_root)
    except Exception as exc:
        print(f"{task}: config.json: no copy was kept ({type(exc).__name__}: {str(exc)[:120]})")
        return
    for note in kept["notes"]:
        print(f"{task}: {note}")


def give_back_config(project, task_root, task: str) -> str:
    """The driver's story END (S9 recorded, or `stop`): the revert's report line, printed to the driver log and returned ("" when
    there is nothing to say). The caller that rebuilds the report afterwards finds the line in the story's copy."""
    line = _give_back_config(project, task_root)[1]
    if line:
        print(f"{task}: {line}")
    return line


def config_snapshot(args) -> int:
    """`config-snapshot --task T`: keep the bytes of qa-factory/config.json as this story starts (a fresh story only). One JSON line."""
    hooklib.require_project("story_step config-snapshot")
    print(json.dumps(_take_config_copy(hooklib.project_root(), hooklib.artifacts_dir(args.task)), ensure_ascii=False))
    return 0


def config_restore(args) -> int:
    """`config-restore --task T`: give back config.json as the story found it, except what a recorded writer wrote in the story's
    window (S9 and `stop`). One JSON line: the result and, when there is something to say, `line` (the report line, with the backup)."""
    hooklib.require_project("story_step config-restore")
    result, line = _give_back_config(hooklib.project_root(), hooklib.artifacts_dir(args.task))
    print(json.dumps(dict(result, line=line) if line else result, ensure_ascii=False))
    return 0


def start(args) -> int:
    import driver_timing
    started = _settle_clock()   # the budget of the probe-debt settle is what is left of THIS call's
    task_root = _task_root(args.task)
    stage = _stages().get(args.stage)
    # t-2277 FL-5: a (role, purpose) row of the stage's `optional_dispatches` is admitted without being one of its `roles`. INVARIANT: such a
    # dispatch never completes the stage (`finish` forces not-complete) and a role with no such row meets the refusal below, as before.
    optional = _optional_row(args.stage, args.role, getattr(args, "purpose", "")) if stage else None
    if not stage or (args.role not in stage.get("roles", []) and optional is None):
        print(f"story_step: {args.role} is not a role of {args.stage} in references/stages.json"
              + (f"; its roles are {', '.join(stage.get('roles') or []) or 'none'}" if stage else "")
              + f". {REPAIR_MARKER}: dispatch a role the stage declares.")
        return 2
    # POSITION INVARIANT: before the controller registers anything - a refused mode switch leaves no
    # dispatch, no stage_done `running`, no brief behind it.
    pipeline = _read_pipeline(task_root)
    switch = run_mode_switch(pipeline, args.stage, current_run_mode())
    if switch:
        print(run_mode_refusal(args.task, switch))
        return 2
    # POSITION INVARIANT (FB-9): the Controller and its state are read (both read-only) BEFORE the stamp, so every refusal of the
    # manual-block check below comes before anything is written - no pipeline stamp, no pre-work, no event, no brief.
    controller = Controller(task_root, wait_seconds=_wait(args))
    state = controller.state()
    block, refusal, code = _manual_block_check(args, controller, state)
    if code:
        print("\n".join(refusal))
        return code
    stamp_run_mode(task_root / "pipeline.json", pipeline, current_run_mode())
    prior = [d for d in state.get("dispatches", {}).values()
             if d.get("stage") == args.stage and d.get("role") == args.role]
    dispatch_id = args.id or f"{args.stage}-{args.role}-{len(prior) + 1}"
    options = {"stage": args.stage, "role": args.role, "id": dispatch_id}
    if optional is not None:
        options["purpose"] = args.purpose       # `prepare` reads the purpose of an optional dispatch (the first look names no half)
    if args.scope:
        options["scope"] = [s.strip() for s in args.scope.split(",") if s.strip()]      # S-1: stripped for every `start`
    if block:        # the driver's registration (`Driver.run_manual_block`): the block IS the scope and `manual_case_ids`
        options["scope"], options["manual_case_ids"] = list(block), list(block)
    if getattr(args, "execution_kind", ""):
        # S6 is two packets of one stage (automation / manual-agent) and the controller
        # refuses a qa-runner packet that does not say which - `start` had no way to say it,
        # so the automated half could not be dispatched at all (TP1-13797, driver run 3).
        options["execution_kind"] = args.execution_kind
    laps = driver_timing.Laps()         # t-1937 P2-1: the sub-steps of this call, reported as `timing:` lines at the end
    with laps.lap("start.pre_work"):
        notes = _pre_work(args.role, task_root, dispatch_id, args.purpose or "")
    with laps.lap("start.derive_before"):
        notes += _derive_before(args.task, args.role, task_root)
    packet = controller.prepare(options)
    request = packet["dispatch_request"]
    if block:        # a legacy-mode `prepare` copies neither field; a new-mode one already set them
        request.setdefault("execution_kind", "manual")
        request.setdefault("manual_case_ids", list(block))
    if args.purpose or block:
        request["purpose"] = args.purpose or "manual"
    if getattr(args, "parallel_window", False):
        request["parallel_window"] = True      # t-1937 TR3-4: read by `Controller._window_beside_running`, nowhere else
    # The one field the detector adds to the record; `finish` reads it back. Taken last, so the
    # bytes hashed are the ones the role is about to start under.
    request[CONFIG_START_FIELD] = config_fingerprint()
    try:
        controller.apply("dispatch", request)
    except IdempotencyKeyReused as exc:
        committed = (state.get("dispatches") or {}).get(dispatch_id)
        if exc.key != "dispatch:" + dispatch_id:
            raise
        # The store (or the controller's N-2) says what differs and names no door; the doors for a `dispatch:<id>` key
        # are ours to spell, ONCE (the store does not know `story_step`): a NEW dispatch takes a new id - for every
        # such key (FR-1/FR-57: a refusal of `start --id` always has a way through) - and a dispatch the controller
        # committed outside `start` also has the `materialize` road, from `launch_card`. The refusal stays a refusal
        # of the same type: nothing is replaced and no `dispatched` line was printed.
        write = (f"to write its brief, handover form and launch card run: "
                 f"{launch_card.materialize_door(args.task, dispatch_id)}; "
                 if launch_card.outside_start(committed) else "")
        raise IdempotencyKeyReused(
            f"{exc}. The committed dispatch is not replaced; {write}a NEW dispatch takes a new id "
            "(run `start` without `--id`)", exc.key, exc.fields) from exc
    # INVARIANT (I1): printed only after `apply` returned - a printed id always has a record behind it, and
    # a refused or raising `apply` prints neither the id nor the card's path. The dispatch is on record
    # from here, and what follows takes 34-112 s on a desktop host (the dashboard refresh of `stage_done`,
    # the brief, the form) while the exec cell that runs this command yields after about 30 s. These two
    # lines are the part of the answer that cannot wait for the rest: the id, and where the card will be
    # (TP2-2406). Flushed, or they wait in the buffer too.
    print(f"dispatched {dispatch_id} (revision {controller.state()['revision']})")
    print(f"launch card: {launch_card.card_rel(args.task, dispatch_id)} (written last; if this output ends "
          f"here, run: story_step.py where --task {args.task})")
    sys.stdout.flush()
    code, out = _run("stage_done.py", "--task", args.task, "--stage", args.stage,
                     "--status", "running", "--role", args.role)
    if code:
        notes.append("stage_done running: " + out.splitlines()[-1] if out else "stage_done running failed")
    # POSITION INVARIANT (R13): the probes need a registered critic dispatch (`probe_by_code.py:1200`),
    # so this sits AFTER `controller.apply("dispatch", ...)` above; a start refused by the mode switch
    # above runs no probe, so it is nowhere before that refusal; the critic sees whatever is left over,
    # so it sits BEFORE the brief and the prompt below, which are built from what is on disk. Neither
    # road asks the conductor (P3, FR-48).
    with laps.lap("start.settle_probe_debt"):
        _, debt_notes = _settle_probe_debt(args.task, args.stage, args.role, dispatch_id, task_root, started, args.purpose or "")
    notes += debt_notes
    # POSITION INVARIANT (SC1-14 C1): the plan's skeleton is written only after `apply` returned, so a refused `start` (mode switch,
    # the plan order, a validate) leaves no `work/s5-plan.json` behind; and before the brief, which is built from what is on disk.
    notes += _s5_plan_init(args.task, task_root, controller, dispatch_id)
    # INVARIANT (I2): the card is the LAST file this command writes (after `stage_done`, the debt, the brief
    # and the form), so its existence proves those steps are over; `where` rebuilds it only from a brief on
    # disk. What is written is exactly what is printed below (one renderer, `_card_text`).
    with laps.lap("start.brief_and_files"):         # `_brief` runs inside `_write_dispatch_files`
        text, _ = _write_dispatch_files(args.task, args.stage, args.role, dispatch_id, task_root,
                                        ",".join(block) if block else ",".join(options.get("scope") or []), notes)
    print(text, end="")
    # AFTER the card text: `story_run.parse_prompt` stops at the bind line, so these lines are read by the driver alone (one reader)
    if current_run_mode() == "driver":      # t-2034 mode gate: the card of the skill road ends at the card (byte pin of test_launch_card)
        print("\n".join(laps.lines()))
    return 0


def _manual_block_check(args, controller, state) -> tuple:
    """`(block | None, refusal lines, exit code)` for a qa-runner `start` (FB-9): BEFORE anything is written.

    - an S6 qa-runner packet in the new plan mode says which half it runs (R6; decided by the state's shape, no exception read);
    - kind `manual`: the block is the stripped `--scope`; it is refused whole, every problem in one answer (the controller's own
      text: `validate_manual_runner_block` renders it, plus the plan-membership sentences of the new mode), then each case is
      prepared by `manual_evidence.prepare_for_block` - the driver's function - and a case it refuses is named and leaves the
      block (the start is refused: a block is never silently shrunk). Every S6 refusal ends with a door built from the CLEANED
      block, so the printed command is not refused again for a problem already named (FR-2).
    - kind `automation` with `--scope` given (RH1-10, DC1-15): the same membership check, for the automated half
      (`Controller._half_membership_problems`), refused whole BEFORE anything is written; no block is returned (the manual bound
      never limits an automated run); no `--scope`: `(None, [], 0)`, the controller derives it in `prepare`.
    Anything else (another role): `(None, [], 0)`."""
    if args.role != "qa-runner":
        return None, [], 0
    kind, new_mode = getattr(args, "execution_kind", "") or "", state.get("plan_contract_mode") == "new"
    if args.stage == "S6" and not kind and new_mode:
        return None, ["story_step: refused - an S6 qa-runner packet says which half it runs",
                      "door: --execution-kind automation (the automated half), or --execution-kind manual --scope "
                      f"<1..{MANUAL_BLOCK_CASES} ids> (one manual block)"], 2
    block = [item.strip() for item in (args.scope or "").split(",") if item.strip()]     # the ONE `--scope` split (RH1-10 m3)
    if kind == "automation":
        # RH1-10 (DC1-15): the automated half meets the same membership check as the manual one, BEFORE anything is written
        # (the position the manual check holds: ahead of the stamp, the pre-work, the event and the brief). It is the Controller's
        # own function (AR-15). No `--scope`: the controller derives the scope in `prepare`, which runs the check there - not
        # twice here. The new plan mode only (builder-rules 9). There is no block: the half stays unbounded in size.
        refused = controller._half_membership_problems(args.stage, state, block, "automation") if block and new_mode else []
        if refused:
            return None, ["story_step: refused - " + controller.automation_half_refusal(refused),
                          "door: leave out what is not of the automated half, or start the automated half on its derived scope: "
                          'python "${CLAUDE_PLUGIN_ROOT}/scripts/story_step.py" start --task ' + args.task
                          + " --stage S6 --role qa-runner --execution-kind automation"], 2
        return None, [], 0
    if kind != "manual":
        return None, [], 0
    from event_store import StateConflict

    def door(given, spent=()):
        return _manual_block_door(args.task, given, state, controller, spent) if args.stage == "S6" else []

    if not block:
        return None, [f"story_step: refused - a manual runner block names its cases (1..{MANUAL_BLOCK_CASES} of them) with --scope",
                      *door([])], 2
    if new_mode:
        # F-1 (AR-19): the block is read in the keys the approved scope holds BEFORE it is counted, judged against the half or
        # prepared - the one map `apply` and `prepare` record it by (`Controller._manual_keys`); the keys are what the returned
        # block, its doors and every refusal below carry, so nothing is refused here that `apply` would accept, and nothing
        # passes here that it would refuse after a write. The legacy mode has no half and keeps the written spelling.
        block = controller._manual_keys(block, state)
    extra = controller._half_membership_problems(args.stage, state, block, "manual") if new_mode else []
    try:
        validate_manual_runner_block(block, block, extra=extra)
    except StateConflict as exc:        # the controller's own text, rendered by its own function (one renderer, K-S5)
        return None, ["story_step: refused - " + str(exc), *door(block)], 2
    import manual_evidence
    refused = {}
    for case in block:
        # (ids, why, unprepared): a case the FACTORY failed to prepare has `why` empty and stays IN the block (F5(c), the
        # factory never stands); only a refusal the story owns names the case and leaves the start refused
        why = manual_evidence.prepare_for_block(_task_root(args.task), case)[1]
        if why:
            refused[case] = why
    if refused:
        every = len(refused) == len(block)
        head = ("no case of this block can be checked by hand" if every else
                "some cases of this block cannot be checked by hand, and a block is never silently shrunk")
        return None, ["story_step: refused - " + head,
                      *[f"{case}: not checked by hand - {why}" for case, why in refused.items()],
                      *door([] if every else block, refused)], 2
    return block, [], 0


def _manual_block_door(task: str, given: list, state: dict, controller, spent=()) -> list:
    """The `door:` lines of a refused S6 manual block (R5): the ready `start` of the next block, built from the CLEANED cases -
    the given order, each once, minus every case outside the plan's manual half and every case `prepare` refused in this run.
    Nothing given, or nothing left of it: the next block of the plan's manual half that no accepted block covers (derived
    order). The half cannot be derived: no id is guessed, the door says to name the cases. Nothing left to dispatch: said."""
    derived = controller.stage_scope("S6", state, "manual")
    can = set(derived.get("scope") or []) if derived.get("derived") else None
    cleaned = [case for case in dict.fromkeys(given) if case not in spent and (can is None or case in can)]
    if not cleaned:
        if can is None:
            return [f"door: name the block's cases with --scope (1..{MANUAL_BLOCK_CASES} ids); the stage scope could not be "
                    f"derived: {derived.get('reason') or 'unknown'}"]
        done = manual_done_cases(state)
        cleaned = [case for case in derived["scope"] if case not in done and case not in spent]
        if not cleaned:
            covered = [case for case in derived["scope"] if case in done]
            return ["no manual-agent case is left for a block: nothing was dispatched; covered by "
                    + (detector_verdict.named(covered, SCOPE_SHOWN) or "no accepted block")]
    # t-1957 N5s (E5s.9, AR-19): the lanes the driver cuts - the cases of one account set together, at most MANUAL_WINDOW_CASES each -
    # by the SAME function; a task root that cannot be read leaves every case in a lane of its own (an account is never guessed)
    try:
        keys = lane_keys(_task_root(task), cleaned)
    except Exception:
        keys = {}
    blocks = walk_lanes(cleaned, keys, MANUAL_WINDOW_CASES)
    lines =['door: the next block: python "${CLAUDE_PLUGIN_ROOT}/scripts/story_step.py" start --task ' + task
             + ' --stage S6 --role qa-runner --execution-kind manual --scope ' + ",".join(blocks[0])]
    if len(blocks) > 1:
        lines.append(f"then {len(blocks) - 1} more block(s) of at most {MANUAL_WINDOW_CASES} case(s) for: "
                     + detector_verdict.named([case for rest in blocks[1:] for case in rest], SCOPE_SHOWN)
                     + "; one dispatch runs at a time; each is finished with --not-complete except the last S6 dispatch of "
                       "the stage (manual or automation)")
    return lines


def _card_text(task: str, stage: dict, role: str, dispatch_id: str, task_root: Path, brief: str,
               form: str, packet: dict | None = None) -> str:
    """The launch card of a dispatch, from what is on disk and the paths of its brief and form. The ONE
    renderer: `start` writes and prints it, `where` rebuilds it, `materialize` writes and compares it. `packet`
    is the dispatch's request (the committed event, or the record projected from it): a rework's identity
    reaches the prompt through it, any other dispatch renders exactly as it always did."""
    extras = _prompt_inputs(task, stage["id"], role, task_root, dispatch_id)
    return launch_card.render(task, role, dispatch_id,
                              _prompt(task, stage, role, dispatch_id, extras, brief, form, _packet_lines(packet, task)),
                              _finish_door(stage["id"], role))


def _resumed_lines(packet: dict, task: str) -> tuple:
    """The two lines a RESUMED role reads (SC1-14 C1, E3/E4): only when the packet is a rework, its stage's `rework_mode` is `resume`
    (`contract.rework_mode`, THE reader) AND it carries the parent's `agent_id` - the controller puts that id on the request only
    for `resume` (`build_rework_request`), so the three conditions say one thing from two sides. A mode that cannot be read is
    `fresh` (the same direction as the controller: a typo never resumes an agent). The brief the resumed agent already read is its
    parent's; the fallback names this dispatch's own brief, which `brief_pack` writes in full (E4: the delta is not the only road)."""
    # SC1-14 fix X, F-3: an `agent_id` that `bind` set on the RECORD (it carries `agent_bound_seq`) is the id of a FRESH agent the conductor
    # launched, not the parent's: it is no resume. Only an id that came with the request counts (the committed event has no seq).
    parent = str(packet.get("rework_of") or "")
    agent = C.request_agent_id(packet)
    if not (parent and agent):
        return ()
    try:
        if C.rework_mode(str(packet.get("stage") or "")) != "resume":
            return ()
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return ()
    own = str(packet.get("id") or "")
    place = (lambda template: _project_rel(task, template, own)) if task else (lambda template: template.format(dispatch_id=own))
    return (f"{RESUMED_PREFIX} (same agent as {parent}): the brief is already read; read only {place(DELTA_REL)}. "
            f"If you do not hold {parent}'s context, read {place(BRIEF_REL)} first.",)


def _packet_lines(packet: dict | None, task: str = "") -> tuple:
    """What a rework packet says about itself, as lines of the role's prompt: whose accepted work it repairs,
    why and from which cause, the plan rows it was sent for, the inherited input_hash and the purpose. Empty
    for a dispatch that is not a rework, so `start`'s prompt is byte for byte what it was. A rework that RESUMES its
    agent (`_resumed_lines`) says so after the rework line; `task` only spells the paths of that line.

    TP2-2406 S3-3, 15.10.2026: the packet held TS-1..TS-4 and TS-8 and the repair reason, and the
    brief and the prompt held none of them: the role would have repaired a plan it was never told the rows of
    (FR-49). Gated on `rework_of`, not on `plan_rows`: an S4 designer's NORMAL dispatch carries every plan row."""
    packet = packet or {}
    if not packet.get("rework_of"):
        return ()
    reason = " ".join(str(packet.get("reason") or "").split())
    lines = [f"Rework of {packet['rework_of']} (cause {packet.get('repair_cause') or 'unnamed'}): {reason}"]
    lines += _resumed_lines(packet, task)
    if packet.get("plan_rows"):
        lines.append("Plan rows of this dispatch: " + ", ".join(str(row) for row in packet["plan_rows"]))
    lines.append(f"Dispatch input_hash: {packet.get('input_hash') or 'unset'}; purpose: "
                 f"{packet.get('purpose') or 'unset'}")
    return tuple(lines)


def _write_dispatch_files(task: str, stage_id: str, role: str, dispatch_id: str, task_root: Path, scope: str,
                          notes: list, packet: dict | None = None, keep: bool = False) -> tuple:
    """`(card text, project-relative paths written)`: the brief, the handover form and the launch card of a
    registered dispatch, in that order, the card LAST. The ONE writer of the three - `start` calls it after
    `apply`, `materialize` for a packet committed elsewhere (TP2-2406 S3-3: two writers of the same
    three files would drift). The notes (the caller's, then its own) are printed AFTER the card is written, as
    `start` always did.

    `keep` is `materialize`'s: a brief or form already on disk is kept (brief_pack rewrites unconditionally,
    and the role's own form is never overwritten), a card already on disk must be exactly the card this
    renders and is never replaced - a differing one is a ValueError (the caller's refusal), nothing written
    over it. A brief or form that cannot be written is a note, with or without `keep`, and the card follows.
    Without `keep` (start) the brief is rewritten and the card replaced, as before."""
    stage = _stages()[stage_id]
    brief_file = task_root / BRIEF_REL.format(dispatch_id=dispatch_id)
    form_file = task_root / FORM_REL.format(dispatch_id=dispatch_id)
    card_file = launch_card.card_path(task_root, dispatch_id)
    written = []
    if keep and brief_file.is_file():
        brief = _project_rel(task, BRIEF_REL, dispatch_id)
        notes.append(f"brief present, kept: {brief}")
    else:
        brief, brief_note = _brief(task, stage_id, role, dispatch_id, task_root)
        if brief_note:
            notes.append(brief_note)
        if brief:
            written.append(brief)
    if _labelling(_dispatch_record(task_root, dispatch_id)):
        # G1-11: window 1 of S3 hands over work/grounding.yaml, whose check is GT's; it has no handover contract (FR-11: the
        # role is never asked for plan fields it cannot produce in window 1). `finish` is unchanged: no form -> `none` -> passes.
        form = ""
    elif keep and form_file.is_file():
        form = _project_rel(task, FORM_REL, dispatch_id)
        notes.append(f"handover form present, kept: {form}")
    else:
        existed = form_file.is_file()
        form, form_note = _handoff_form(task, stage_id, role, dispatch_id, task_root, scope)
        if form_note:
            notes.append(form_note)
        if form and not existed:
            written.append(form)
    # A brief or a form that could not be written is a note and the card is written all the same, as in `start`:
    # the prompt already carries the rows and the rework line, and a deterministic failure of brief_pack would
    # otherwise leave the person with no way forward (FR-46, P1).
    text = _card_text(task, stage, role, dispatch_id, task_root, brief, form, packet)
    if keep and card_file.is_file():
        if card_file.read_bytes() != text.encode("utf-8"):
            raise ValueError(_card_differs(task, dispatch_id, card_file, text))
        notes.append(f"launch card present, identical: {launch_card.card_rel(task, dispatch_id)}")
    else:
        # A card that cannot be written is a note, never a failure: the printed block is the same text.
        try:
            launch_card.write(task_root, dispatch_id, text)
            written.append(launch_card.card_rel(task, dispatch_id))
        except OSError as exc:
            notes.append(f"the launch card was not written ({type(exc).__name__}); the block below is the launch "
                         f"card, and `story_step.py where --task {task}` rebuilds the file")
    for note in notes:
        print("note: " + note)
    return text, written


# --- a dispatch the controller committed outside `start` (TP2-2406 S3-3, 15.10.2026) ---------------
# `controller.py --operation rework` commits the packet and stops: no brief, no handover form, no launch card.
# `start` is the only other writer of them and it cannot be pointed at a committed packet - it builds a FRESH
# request (`prepare`) and `apply`s it, and the idempotency guard rightly refuses a key that already holds a
# different request. `materialize` reads the packet that IS committed and writes the three files from it.
# It is a reader of the controller: it never calls `prepare` or `apply` and never touches the log or the state.
# INVARIANT: `where` rebuilds a card from the RECORD and `materialize` renders it from the EVENT; every field
# the prompt reads (`_packet_lines`: rework_of, repair_cause, reason, plan_rows, input_hash, purpose) is compared,
# so a drift on any of them is refused here and never becomes a card that differs from the one `where` wrote.
# ONE field the prompt reads is NOT compared, on purpose: `agent_id` (the resumed line). `bind` sets it on the RECORD through
# the controller's projection (never on the dispatch event), so comparing it would refuse every bound dispatch. The card
# is rendered from the EVENT's id; `where` rebuilds from the record only after `_request_packet` put the event's id back (F-3).
IDENTITY_FIELDS = ("id", "stage", "role", "input_hash", "scope", "plan_rows", "rework_of", "purpose",
                   "repair_cause", "reason")


def _card_differs(task: str, dispatch_id: str, card_file: Path, text: str) -> str:
    have = card_file.read_text(encoding="utf-8", errors="replace").splitlines()
    want = text.splitlines()
    line = next((i + 1 for i, (a, b) in enumerate(zip(have, want)) if a != b), min(len(have), len(want)) + 1)
    return (f"the launch card of {dispatch_id} ({launch_card.card_rel(task, dispatch_id)}) exists and differs from "
            f"the card this packet renders (first difference at line {line}); a card on disk is never overwritten. "
            "If it is the leftover of an earlier packet, delete that one derived file and run: "
            + launch_card.materialize_door(task, dispatch_id))


def _committed_packet(task_root: Path, controller: Controller, dispatch_id: str) -> dict:
    """The payload of the ONE `dispatch` event with key `dispatch:<id>`: the packet as the log holds it."""
    key = "dispatch:" + dispatch_id
    found = [e for e in controller.store.read() if e.get("idempotency_key") == key and e.get("type") == "dispatch"]
    if len(found) != 1 or not isinstance(found[0].get("payload"), dict):
        raise ValueError(f"the log holds {len(found)} dispatch event(s) with key {key} (one is expected), so "
                         "there is no committed packet to write the files from; nothing was written. This is an "
                         f"inconsistency in the factory's own state: run controller.py --task-root {task_root} "
                         "--operation recover; if that does not settle it, say one line - owner: factory, this fact")
    return found[0]["payload"]


def _check_packet(task_root: Path, state: dict, record: dict, packet: dict) -> None:
    """Refuse (ValueError: field, value, door) unless the packet is self-consistent. INVARIANT: nothing is
    written before this passes, and what `materialize` then writes is the PACKET's identity. FR-59: a record
    that disagrees with its own event, or a parent that cannot be found, is an unknown, and an unknown refuses."""
    dispatch_id = str(packet.get("id") or "")
    drift = [f"{key}: record {record.get(key)!r} | committed event {packet.get(key)!r}"
             for key in IDENTITY_FIELDS if record.get(key) != packet.get(key)]
    if drift:
        raise ValueError(f"the projected record of {dispatch_id} differs from its committed event in "
                         + "; ".join(drift) + ". The log is the authority and the record is derived from it, so "
                         "this is the factory's own inconsistency: run controller.py --task-root "
                         f"{task_root} --operation recover; if that does not settle it, say one line - "
                         "owner: factory, this fact. Nothing was written")
    parent = str(packet.get("rework_of") or "")
    if parent:
        before = (state.get("dispatches") or {}).get(parent)
        door = (launch_card.release_door(task_root, dispatch_id)
                + " frees it (a person's word), then `controller.py --operation rework` builds it again")
        if not isinstance(before, dict):
            raise ValueError(f"{dispatch_id} reworks {parent}, which the controller does not hold, so the "
                             f"input_hash it inherited cannot be checked; nothing was written. {door}")
        if before.get("input_hash") != packet.get("input_hash"):
            raise ValueError(f"{dispatch_id} reworks {parent} but its input_hash {packet.get('input_hash')!r} is "
                             f"not the one {parent} was accepted on, {before.get('input_hash')!r}: a rework "
                             f"repeats accepted work on the same inputs. Nothing was written. {door}")


def _refuse_differing_card(task: str, task_root: Path, stage: dict, role: str, dispatch_id: str,
                           packet: dict) -> None:
    """A card that exists and differs from the one this packet renders is refused BEFORE the brief and the form
    are touched. The paths it would name are known: the brief is written or kept (a brief that fails leaves a
    brief-less card, which a rerun then refuses and names the door to delete it); the form when it exists or
    the registry owes one."""
    card_file = launch_card.card_path(task_root, dispatch_id)
    if not card_file.is_file():
        return
    owed = (task_root / FORM_REL.format(dispatch_id=dispatch_id)).is_file() or _form_owed(
        stage["id"], role, _dispatch_record(task_root, dispatch_id))
    expected = _card_text(task, stage, role, dispatch_id, task_root, _project_rel(task, BRIEF_REL, dispatch_id),
                          _project_rel(task, FORM_REL, dispatch_id) if owed else "", packet)
    if card_file.read_bytes() != expected.encode("utf-8"):
        raise ValueError(_card_differs(task, dispatch_id, card_file, expected))


def _inputs_notes(task: str, stage_id: str, role: str, dispatch_id: str, task_root: Path) -> list:
    """The notes of the code `start` runs before the brief that is safe to run again, for `materialize`.
    PARITY with `start` for what DERIVES FILES: `_derive_before` always (deterministic, the traceability table
    the scribe reads); `_pre_work` only when THIS run writes the brief (the judge scripts call the provider, so a
    repeat run, which writes nothing, runs none). NEVER `_settle_probe_debt` (probe_debt.py: it rebinds the
    manifest and runs live probes that mutate the author's test file, for minutes): the S5 code critic's card
    carries the debt-file note and the door that settles, run by the conductor on purpose."""
    notes = []
    if not (task_root / BRIEF_REL.format(dispatch_id=dispatch_id)).is_file():
        notes += _pre_work(role, task_root, dispatch_id)
    notes += _derive_before(task, role, task_root)
    if (stage_id, role) == (DEBT_STAGE, DEBT_ROLE) and not _is_plan_dispatch(task_root, dispatch_id):   # F-2: no debt on the plan critic
        notes += _debt_input(task, task_root, dispatch_id)[1]
        notes.append("probe_debt --settle is not run by materialize (it rebinds the manifest and runs live probes "
                     "for minutes); before the critic is launched run: "
                     f"probe_debt.py --task {task} --settle --dispatch {dispatch_id}")
    return notes


def materialize(args) -> int:
    """Write the brief, the handover form and the launch card of a running dispatch from its COMMITTED packet.
    Idempotent: what is on disk and equal is kept ("materialized: nothing"), a card that differs is refused and
    never replaced. POSITION: no `prepare`, no `apply`, no `stage_done` - the controller's log and state are
    only read; the card is written last (`_write_dispatch_files`), so a crash leaves no card without its brief
    and form. A story of another run mode is refused as `start` refuses it; the code `start` runs that derives
    files is run here too (`_inputs_notes`), the probe-debt settle never. A packet `start` registered is
    allowed too (crash recovery: `start` died after `apply`); only the texts that NAME this door ask
    `launch_card.outside_start`."""
    task_root = _task_root(args.task)
    dispatch_id = args.dispatch_id
    controller = Controller(task_root, wait_seconds=_wait(args))
    state = controller.state()
    record = (state.get("dispatches") or {}).get(dispatch_id)
    if not isinstance(record, dict):
        raise ValueError(f"the controller holds no dispatch {dispatch_id}; materialize writes the files of a "
                         "dispatch the controller already committed. `story_step.py start --task "
                         f"{args.task} --stage <S> --role <role>` registers a new one; state/controller.json lists "
                         "the dispatches there are")
    if record.get("status") != "running":
        raise ValueError(f"{dispatch_id} is {record.get('status')}, not running; materialize writes the files of "
                         f"a running dispatch only. `story_step.py where --task {args.task}` names what is next")
    packet = _committed_packet(task_root, controller, dispatch_id)
    _check_packet(task_root, state, record, packet)
    stage_id, role = str(packet.get("stage") or ""), str(packet.get("role") or "")
    stage = _stages().get(stage_id)
    if not stage:
        raise ValueError(f"the packet of {dispatch_id} names stage {stage_id!r}, which references/stages.json does "
                         "not declare; nothing was written")
    # POSITION INVARIANT: the same refusal as `start`'s, before anything is written, and no stamp - a story run
    # by the driver is never materialized by a desktop conductor (the driver writes its own form), and a story
    # with no stamp is not claimed by this command (only `start` adopts a mode).
    switch = run_mode_switch(_read_pipeline(task_root), stage_id, current_run_mode())
    if switch:
        print(run_mode_refusal(args.task, switch))
        return 2
    _refuse_differing_card(args.task, task_root, stage, role, dispatch_id, packet)
    scope = [str(c) for c in packet.get("scope") or []]
    notes = _inputs_notes(args.task, stage_id, role, dispatch_id, task_root)
    # POSITION INVARIANT (SC1-14 fix X, B-1): after every refusal above (a refused `materialize` writes no plan) and before the files, which are
    # built from what is on disk; the record is RUNNING (checked above), so only a running plan author is touched. `_s5_plan_init` is
    # `refresh` for a rework (the author's rows stay, the new cases get rows, the hashes become current) and idempotent on a current plan, so
    # a repeat `materialize` changes no byte the critic stamped; a plan it cannot write is a note naming the door, never silence.
    # ONLY the rework of a plan that is on disk: a packet with no plan file behaves as before this fix (materialize never begins a plan).
    import s5_plan as SP
    if packet.get("rework_of") and (task_root / SP.PLAN_REL).is_file():
        notes += _s5_plan_init(args.task, task_root, controller, dispatch_id)
    text, written = _write_dispatch_files(args.task, stage_id, role, dispatch_id, task_root, ",".join(scope), notes,
                                          packet=packet, keep=True)
    print("materialized: " + (", ".join(written) or "nothing"))
    rows = [str(r) for r in packet.get("plan_rows") or []]
    print(f"packet: {dispatch_id} ({stage_id} {role}); input_hash {packet.get('input_hash')}; purpose "
          f"{packet.get('purpose') or 'unset'}; scope {', '.join(scope) or 'none'}"
          + (f"; plan rows {', '.join(rows)}" if rows else "")
          + (f"; rework of {packet['rework_of']} (cause {packet.get('repair_cause') or 'unnamed'})"
             if packet.get("rework_of") else ""))
    print(text, end="")
    return 0


def _finish_door(stage_id: str, role: str) -> str:
    """The S5 critic's window may not close (`could_not_judge`, a test fitted to the code, cases handed
    to the person): the controller takes that as `unresolved` + `reason` on the completion, and this
    is the only place the conductor is told where to put them (FR-2: a door a role can use).

    HF8-15 (2): the same critic's other door - the one for a critic that cannot judge because the AUTHOR's work is
    defective (`finish --needs-author`, `_needs_author`); without it the card named no way to send the author back
    while the critic still runs (run 12586: the conductor went round the controller with a message)."""
    return (" (or, for a window the critic could not close: finish --unresolved <why> --reason "
            '"<words>"; or, for a critic that cannot judge because its author\'s work is defective: '
            'finish --needs-author <cases> --reason "<words>")') if (stage_id, role) == (DEBT_STAGE, DEBT_ROLE) else ""


def _binding(task_root: Path):
    """(host_dispatch module, project root) - imported late so story_step still runs where
    the hook layer is not installed."""
    import host_dispatch
    return host_dispatch, hooklib.project_root()


def bind(args) -> int:
    """Record which host agent is doing a dispatch, in both places that are asked later.

    The resume guard reads `pipeline.json`'s `agent_id` (that is how a follow-up reaches the
    agent still holding the context instead of opening a fresh one), and
    `dispatch_liveness.py` reads `state/host-dispatches/`. Neither is written by `start`,
    because the id does not exist until the host has spawned the role - on 21.09 the
    orchestrator discovered that by hand, mid-story, from a refusal.
    """
    task_root = _task_root(args.task)
    controller = Controller(task_root)
    dispatch = controller.state().get("dispatches", {}).get(args.dispatch_id)
    if not dispatch:
        print(f"story_step: no dispatch {args.dispatch_id} in this story; it has "
              + (", ".join(sorted(controller.state().get("dispatches") or {})) or "none")
              + f". {REPAIR_MARKER}: name one of them.")
        return 2
    code, out = _run("stage_done.py", "--task", args.task, "--stage", dispatch["stage"],
                     "--status", "running", "--role", dispatch.get("role") or "",
                     "--agent-id", args.agent_id, "--dispatch-id", args.dispatch_id)
    if code and "already accepted by the controller" in out:
        # A role that runs AFTER its stage was accepted (qa-bug-reporter works after gate B,
        # s8.md §2c) must not re-open the stage to be bound: the binding is about the host
        # agent, not the stage's status. TP1-13797, driver run 3: the reporter wrote its
        # bug draft and the bind refused, stranding the dispatch.
        # HF9-1: a RUNNING dispatch of this stage is bound by `stage_done` itself (a bind-only transition) and never
        # reaches this branch. Here stage_done still refused: the dispatch is not running on this stage (accepted,
        # superseded, released, another stage's), so the controller's record holds NO agent id for it.
        print("note: the stage is already accepted and stage_done did not bind dispatch " + args.dispatch_id
              + " (it binds only a running dispatch of " + dispatch["stage"] + " with a non-blank agent id); "
              "the agent id is NOT on the controller's dispatch record, so the resume "
              "guard may refuse a resume to this agent. Only the host receipt is written")
        code, out = 0, ""
    if code:
        print(out)
        # No REPAIR_MARKER here, and that is deliberate: the refusal above is another script's,
        # and whose it is was decided there. A marker on this line would relabel a question that
        # belongs to a person as a repair, which is the mirror of the defect P4b names.
        print(f"story_step: stage_done refused the binding (exit {code}); the refusal above is the halt")
        return code
    written = ""
    try:
        host_dispatch, root = _binding(task_root)
        path = host_dispatch.binding_path(root, args.agent_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        # `bound_by` is ours: `finish` marks terminal only a receipt story_step wrote, so a
        # host that keeps its own receipts is never edited by us. `bound_at` is the launch,
        # written only here: `_release_binding` edits the receipt later and must not move it.
        # `task_name` / `task_path` are the keys `host_dispatch.record` writes for the same agent: one
        # receipt shape for both writers (the host addresses a follow-up by either spelling, and
        # `host_dispatch.binding_names` is the one reader of them). A bare id has no path.
        # DC1-11: an agent continued by message takes several dispatches, and this receipt is one per agent, so
        # `bound_dispatches` keeps every binding while the scalar `dispatch_id` stays the LAST (its readers are
        # unchanged). Read-modify-write, hence `atomic_json`; a receipt that cannot be read starts the list afresh.
        from event_store import atomic_json
        now, before = time.time(), hooklib.read_json(path, {}, kind=dict, errors=Exception)
        atomic_json(path, {"agent_id": args.agent_id, "agent_type": dispatch.get("role"), "task_id": args.task,
                           "dispatch_id": args.dispatch_id, "status": "running", "bound_by": "story_step",
                           "task_name": args.agent_id.rsplit("/", 1)[-1],
                           "task_path": args.agent_id if args.agent_id.startswith("/") else None,
                           "bound_at": now, "bound_dispatches": host_dispatch.with_bound_dispatch(
                               before, args.task, args.dispatch_id, now)})
        written = str(path)
    except Exception as exc:  # a host without the binding directory still has pipeline.json
        # Read the record as it is NOW: stage_done exiting 0 does not prove it took the id (a dispatch no longer
        # running when the projection ran gets none).
        recorded = Controller(task_root).state().get("dispatches", {}).get(args.dispatch_id, {}).get("agent_id")
        print(f"note: the host binding was not written ({type(exc).__name__}: {exc}); "
              + ("the controller's dispatch record already carries the agent id; only the host receipt is missing"
                 if recorded == args.agent_id else
                 "the agent id is on neither the controller's dispatch record nor a host receipt"))
    print(f"bound {args.dispatch_id} to agent {args.agent_id}"
          + (f" ({written})" if written else ""))
    print("--- after the digest: story_step.py finish --task " + args.task
          + " --dispatch-id " + args.dispatch_id + ' --digest "<digest>" ---')
    return 0


def _release_binding(task_root: Path, dispatch_id: str, task: str = "") -> None:
    """Mark the receipt `bind` wrote terminal. Without it `dispatch_liveness` would keep reading
    the receipt of a dispatch that has already been accepted as a launch with nothing after it:
    `alive` while the receipt is fresh (`abandoned_after_s`, 600 s by default), then `unknown`
    - and `next` would wait for it, or ask the person to release it."""
    try:
        _, root = _binding(task_root)
        directory = Path(root) / "qa-factory" / "state" / "host-dispatches"
        for path in directory.glob("*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            # Dispatch ids repeat across stories (two both reach `S5-qa-automator-12`), so the
            # id alone would release another story's live receipt. A receipt naming no story
            # is not ours to release either (same rule as dispatch_liveness).
            if (record.get("bound_by") == "story_step"
                    and task and record.get("task_id") == task
                    and record.get("dispatch_id") == dispatch_id
                    and record.get("status") != "terminal"):
                record.update(status="terminal", terminal_source="story_step")
                path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    except Exception:
        pass  # bookkeeping of ours; it never fails an acceptance


EVIDENCE_SUFFIXES = (".md", ".json", ".py", ".txt", ".yaml", ".yml", ".jsonl")


def _evidence(task_root: Path, stage: dict, extra: list) -> list:
    """The stage's output files on disk, as evidence refs. A directory output (S4's
    `work/test-cases/`, S5's `work/test-code/`) counts by the files under it: with no
    `--output` list, a finish that ignored directories saw "none of the outputs" beside ten
    case files (TP1-13797, driver run 3) and asked whether the dispatch was dead."""
    declared = [o for o in stage.get("required_outputs", []) + stage.get("outputs", [])
                if not o.startswith("project:")]
    names = []
    root = task_root.resolve()
    for output in declared:
        if output.endswith("/"):
            folder = task_root / output.rstrip("/")
            if folder.is_dir():
                for path in sorted_paths(folder.rglob("*")):
                    if path.is_file() and path.suffix.lower() in EVIDENCE_SUFFIXES:
                        names.append(path.relative_to(task_root).as_posix())
        else:
            names.append(output)
    refs, seen = [], set()
    for name in names + list(extra):
        path = (task_root / name).resolve()
        if name in seen or not path.is_file() or not path.is_relative_to(root):
            continue
        seen.add(name)
        refs.append(name)
    return refs


REVIEW_ROLES = ("qa-code-critic", "qa-case-critic")


def _role_receipts(task_root: Path, role: str, dispatch: str = "") -> list:
    """Files the factory's own receipt rules demand from THIS role, as evidence refs. A
    review is receipted by its findings file (controller: "no findings file in the accepted
    evidence"), and no stage declares that file among its outputs - the orchestrator used to
    pass it by hand with `--output`. TP1-13797, driver run 3: the critic's findings sat
    complete on disk while the finish was refused and the loop asked the person twice.

    t-2098 (TR3-5, AR-13, AR-14): each critic is receipted on ITS OWN findings file, never "the newest on disk" - with two windows
    that was the other window's file. The code critic: the one resolver (`findings_path.resolve`: its dispatch's file, else the
    old single file of a story from before); none yet -> no receipt (the finish then refuses for the missing findings). The case
    critic: the files under `work/test-cases/` only, never an S5 file."""
    if role not in REVIEW_ROLES:
        return []
    if role == "qa-code-critic":
        import findings_path
        own = findings_path.resolve(task_root, dispatch)
        return [own] if own else []
    import findings_path
    found = findings_path.s4_files(task_root)
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [p.relative_to(task_root).as_posix() for p in found[:2]]


def _s1_accepted_gaps(task_root: Path) -> dict:
    """The completion's `unresolved` + `reason` for the source gaps a person accepted: the
    controller refuses an S1 close over an incomplete inventory unless the handoff names
    them, and the scout's digest has no field for it (TP1-13797, driver run 3: a
    conductor session read the controller to build that packet by hand)."""
    inventory_path = task_root / "work" / "source-inventory.json"
    if not inventory_path.is_file():
        return {}
    try:
        from source_inventory import load_inventory, completeness, class_kwargs, gap_words, class_basis
        inventory = load_inventory(inventory_path)
        kinds = class_kwargs(task_root)
        summary = completeness(inventory, **kinds)
    except Exception:
        return {}
    accepted, defaulted = summary.get("accepted_gaps") or [], summary.get("defaulted_gaps") or []
    if (summary.get("complete") and not defaulted) or not (accepted or defaulted):
        return {}
    words, by_default = [], []
    for item in inventory.get("sources") or []:
        sid = item.get("source_id")
        if sid in accepted:
            said = gap_words(item, summary.get("closed_by_class"), kinds["classes"])
            if said:
                basis = class_basis(summary.get("closed_by_class"), kinds["classes"], sid)
                words.append(f"{sid}: {said.strip()[:200]}" + (f" ({basis})" if basis else ""))
        for point in (summary.get("defaulted_points") or {}).get(sid, []):
            by_default.append(f"{sid} - {point['name']} - {point['cause']}: {point['basis']}")
    reason = ("source gaps accepted by the person - " + " | ".join(words)) if accepted else ""
    if by_default:
        # Established by the factory's own probe, not asked (D-0043); named, one entry per point (FR-41).
        reason += (" | " if reason else "") + "".join(
            f"unreachable by the factory: {entry} | " for entry in by_default).rstrip(" |")
    return {"unresolved": list(dict.fromkeys(accepted + defaulted)), "reason": reason}


# The gap kinds of an S5 window record that `finish` may turn into an `unresolved` pair BY ITSELF (t-219, B5):
# an instance the stand blocked (`acceptance.BLOCKED_OUTCOME`) and one the person runs (`HANDED_OUTCOME`).
# Both are named by `acceptance.validate_window` as `<kind>:<instance id>`, and the controller reads both
# words BY NAME in the completion (`names_blocked`, `names_handed`). HF1-14: a third kind, `probe_gap` (an instance
# that ran green whose probe could not run here and whose gap the person's recorded word names), read by
# `names_probe_gap`; `probe_gap_unrecorded` is NOT here - no word names it, so no pair is derived over it.
# HF2-4b: a fourth kind, `contradicts_requirement` (a red test its manifest row explains: an OUTCOME, S7 triages it),
# read by `names_contradicts`. `product:` is NOT here and stays undeclared: it is a red nobody explained, a defect of
# the window the author repairs (the row, FR-2), so no pair is derived over it and the invariant below stays true.
DERIVED_GAP_KINDS = ("blocked_by_env", "handed_to_person", "probe_gap", "contradicts_requirement")
# The longest reason a DERIVED pair carries: `story_run.Driver.WINDOW_REASON_LIMIT`, the same cut the driver
# applies to the pair it derives for its own kinds (test_story_step.py holds the two numbers equal).
WINDOW_REASON_LIMIT = 300


def _window_gaps(window, task_root: Path):
    """`acceptance.validate_window`'s gaps for a window record, or None when it cannot be read.

    Read-only and never raises: a record the validation cannot read (not the shape of a window, a plugin
    file gone) gives None, and the caller then derives NOTHING - the controller's own refusal stays reachable
    (the error direction: a refusal costs one round, a pair over a gap nobody named is t-204 F1)."""
    try:
        from acceptance import validate_window
        return list(validate_window(window, task_root))
    except Exception:
        return None


def _ran_red_marks(window, gaps: list) -> list:
    """The `ran red: <reason>` marks of the blocked instances that RAN and failed (O3), once each, in the
    record's own order. Read from the window's `blocked_by_env[]` and only for the instances the gaps name as
    blocked; the text is `acceptance.ran_red`'s - the same one the window_record line shows."""
    if not isinstance(window, dict) or not isinstance(window.get("blocked_by_env"), list):
        return []
    try:
        from acceptance import ran_red
        blocked = set(_blocked_ids(gaps))
        marks = [ran_red(entry.get("last_run")) for entry in window["blocked_by_env"]
                 if isinstance(entry, dict) and str(entry.get("instance_id") or "") in blocked]
    except Exception:
        return []
    return list(dict.fromkeys(mark for mark in marks if mark))


def _handed_no_instance(window, controller) -> list:
    """The cases of the window's scope that list NO instance and that the manifest carries as `handed_to_person`.

    The rule is the controller's own (`Controller._cases_without_instances`, `NO_INSTANCE_REASONS`): it stays in
    one place. `impossible` is not derived here (t-721 F-2 (a): code never decides a case cannot be tested).
    Anything unreadable gives `[]` - today's behavior, the controller's own refusal stays reachable."""
    try:
        found = controller._cases_without_instances()
        return sorted(case for case, ids in (window.get("scope_instances") or {}).items()
                      if not ids and found.get(case) == "handed_to_person")
    except Exception:
        return []


def _derived_pair(gaps: list, shown: str, marks=(), no_instance=()) -> tuple:
    """`(word, reason)` the window record's own gaps give, or `()` - nothing is derived.

    `no_instance` (t-721 section 3.2): the handed cases of the window with no instance at all; each is a gap line
    `handed_to_person:<case>` of its own, and a window with no gap and no such case gives `()` (a clean window
    needs no pair). The caller drops `empty_scope` from `gaps` only when EVERY case of the scope is such a case.

    Only when EVERY gap is of a kind in DERIVED_GAP_KINDS (INVARIANT, t-204 F1: code never accepts a window as
    unresolved over a gap nobody named; the controller reads `unresolved` as present or not, so a pair
    covers every gap of the window). The word is the first kind in the gaps' own (sorted) order; the reason
    names the kinds, then the record's path, then the `ran red` marks (O3: a blocked instance that RAN and
    failed says so; they count toward the limit), then the gap lines, cut at WINDOW_REASON_LIMIT characters. The
    kinds and the path stand first and are NEVER cut, even when they alone are longer than the limit."""
    gaps = list(gaps or []) + [f"handed_to_person:{case}" for case in no_instance]
    if not gaps or any(gap.partition(":")[0] not in DERIVED_GAP_KINDS or ":" not in gap for gap in gaps):
        return ()
    kinds = list(dict.fromkeys(gap.partition(":")[0] for gap in gaps))
    head = ", ".join(kinds) + "; full list: " + shown
    reason = head + "; " + "; ".join(list(marks) + list(gaps))
    if len(reason) > WINDOW_REASON_LIMIT:
        reason = reason[:WINDOW_REASON_LIMIT] if len(head) < WINDOW_REASON_LIMIT else head
    return kinds[0], reason


def _blocked_ids(gaps: list) -> list:
    return [gap.partition(":")[2] for gap in gaps or [] if gap.startswith("blocked_by_env:")]


def _cut(text: str, room: int, floor: str = "") -> str:
    """`text` cut to `room` characters, the cut marked by `…` (which counts). `floor` is the prefix that is never
    cut: when even that does not fit, the result is `floor` + `…` and is longer than `room` by exactly the rest."""
    if len(text) <= room:
        return text
    return text[:max(room - 1, len(floor))] + "…"


def _caller_pair_reason(reason: str, blocked_ids: list, marks: list, missing: list) -> str:
    """The reason of a pair that came from the caller, grown to what the controller reads (t-721 section 3.2 and
    its N1, edge 18). Three parts, in this order, joined by `; `:

    1. the caller's own `reason` - never cut;
    2. the Q8 block, only when the stand blocked instances: the word `blocked_by_env: <ids>` (unless the caller's
       reason has it) and the `ran red` marks the reason does not quote (O3, F2);
    3. the append, only when cases without instances are missing from the caller's pair: `handed_to_person:<case>`
       for each, so ONE pair names every case the person runs (FR-10).

    Over WINDOW_REASON_LIMIT the LAST part is cut first (the append, then the Q8 block from its tail), every cut
    marked by `…`. The word `blocked_by_env` of the Q8 block is never cut (`names_blocked` looks for it, and
    without it the controller refuses a window with blocked instances): a caller's reason of 300 or more is
    therefore followed by the uncuttable `; blocked_by_env…` and `; …`, longer than the limit by exactly those."""
    named = "blocked_by_env" in reason
    block = ""
    if blocked_ids:
        grown = ([] if named else ["blocked_by_env: " + ", ".join(blocked_ids)])
        quoted = reason + "".join(grown)
        block = "; ".join(grown + [mark for mark in marks if mark not in quoted])
    tail = "; ".join(f"handed_to_person:{case}" for case in missing)
    whole = "; ".join(part for part in (reason, block, tail) if part)
    if len(whole) <= WINDOW_REASON_LIMIT:
        return whole
    head = "; ".join(part for part in (reason, block) if part)
    if tail and len(head) + 2 < WINDOW_REASON_LIMIT:
        return head + "; " + _cut(tail, WINDOW_REASON_LIMIT - len(head) - 2)
    floor = "blocked_by_env" if "blocked_by_env" in block else ""
    room = WINDOW_REASON_LIMIT - len(reason) - 2 - (3 if tail else 0)
    return "; ".join(part for part in (reason, _cut(block, room, floor) if block else "", "…" if tail else "")
                     if part)


def _unresolved_refusal(args, unresolved: str, reason: str) -> str:
    """"" when the `--unresolved` / `--reason` pair is usable, else the refusal (FR-1: what is wrong,
    what is expected, the command that satisfies it). Runs before anything is read or recorded, so a
    refused call leaves the story exactly as it was."""
    if bool(unresolved) != bool(reason):
        had, lacks = ("--unresolved", '--reason "<words>"') if unresolved else ("--reason", "--unresolved <why>")
        return (f"story_step: finish got {had} without {lacks}. They go together: the controller refuses "
                "an unresolved completion that gives no reason, and a reason with nothing unresolved is "
                "not read. For a window the critic could not close: finish --task <T> --dispatch-id <ID> "
                '--digest "<digest>" --unresolved <why> --reason "<words>". '
                f"{REPAIR_MARKER}: repeat the call with both.")
    return ""


def _open_window_refusal(args, unresolved: str, stage: str) -> str:
    """"" or the refusal for `--unresolved` together with `--not-complete` ON S5 (t-721 D1: SS narrows the rule to
    the stage it is about). An S5 window is either accepted as unresolved or left open; any other stage may say both:
    `stage_complete: false` with the work it leaves (the shape the controller already takes, test_stage_closure.py).
    Checked once the dispatch is known and before anything is read or recorded."""
    if stage == "S5" and unresolved and getattr(args, "not_complete", False):
        return ("story_step: finish got --unresolved together with --not-complete on S5. A window is either "
                "accepted as unresolved, with its reason, or left open: the first closes the stage on this "
                "critic, the second says more work remains. Drop --not-complete to accept it as "
                "unresolved, or drop --unresolved and --reason to leave the stage open. "
                f"{REPAIR_MARKER}.")
    return ""


# The two ways past a handover form the role cannot complete, said once for both refusals of `finish`. The
# second is the one a driver run met on TP1-15045 (S7, 02.10): the form had no legal answer, the old text
# presented `--ignore-handoff` as a door only for "a story already running under an older build", and a
# conductor that held the person's words did not take it. A person's word passes this form for this one
# dispatch; the word itself is recorded by whoever records the person's words, not by this flag.
_FORM_DOORS = ("a story already running under an older build sets `handoffs.required: false` in "
               "qa-factory/config.json. A person's word passes this form for this one dispatch: "
               "`finish --ignore-handoff`, recorded by whoever records the person's words (the conductor or "
               "the orchestrator).")


def _stale_view_note(stale, dispatch_id: str, task_root: Path) -> str:
    """The plain-words sentence for an accept that is committed while a view after it is not.

    Built from the refusal's TYPE and fields, never from its text: the text says "event committed;
    ...", and `finish`'s whole stdout is what the driver matches when `stage_done` refuses after it.
    Its first row (`committed_event`) would then take a refusal that is stage_done's own and answer
    it with `recover` + `continue` (critic t-447, E1: an S9 `report check:` refusal lost its
    rebuild). So the sentence says what is true - what is out of date, that `recover` refreshes it,
    that nothing is repeated - without the store's phrase. What failed stays in the file that
    records it, when one does (`recorded_in`); the cause is named by its type only, because its own
    message is free text this code does not control."""
    cause = type(stale.__cause__).__name__ if stale.__cause__ is not None else ""
    recorded = getattr(stale, "recorded_in", "")
    if recorded:
        detail = f"; what failed{f' ({cause})' if cause else ''} is in {recorded}"
    elif cause:
        detail = f"; it failed with {cause} and nothing on disk records it"
    else:
        detail = ""
    return (f"{stale.stale_view} after the accept of {dispatch_id} was recorded{detail}; "
            f"`controller.py --task-root {task_root} --operation recover` refreshes it, and nothing is "
            f"done a second time")


def _declared_halt(task_root: Path, form_rel: str, digest: str) -> str:
    """Where a role declared a halt, or "": `the handover form (header.verdict: halt)` and/or `the digest`. The ONE
    reader of "the role handed the decision back": `finish`, `decide`, and the driver's `run_role`, `resume_role`
    and `_finish_saved_result` all come through it (no caller reads `header.verdict` or the digest for a halt by
    itself). `form_rel` is the form's task-relative path ("" = read the digest only).

    TP2-2406 S3-3 (15.10, FR-18): the strategist halted (`header.verdict: halt`, a false coverage claim,
    a `blocked` field) and `finish` recorded `status: accepted, stage_complete: true` over a plan that never
    changed. The headless driver reads the same word (`role_digest.is_halting` on the digest); this is that
    reading from BOTH places a role says it: the form and the digest line.

    ERROR DIRECTION (advice -> gate): a false halt costs one conductor round with named doors; a false "no halt"
    records a halt as `accepted`. So a parseable verdict errs toward halt: it is compared after
    `strip()` / quote-strip / `lower()` to `role_digest.HALTING_VERDICTS` (the one word list) and nothing else is a
    halt - `halted`, `not halt`, a list, a dict, the placeholder listing the verdicts, `ok`, `concerns`. A form
    that cannot be read says nothing (`_handoff_check` owns that refusal); a sentence in the digest never halts,
    a header on any line always does (`role_digest.is_halting`)."""
    import role_digest
    places = []
    shown = _form_halt_word(task_root, form_rel)
    if shown:
        places.append(f"the handover form (header.verdict: {shown})")
    if role_digest.is_halting(digest or ""):
        places.append("the digest")
    return " and ".join(places)


def _form_halt_word(task_root: Path, form_rel: str) -> str:
    """The halting verdict the handover form declares (as written, stripped), or "" - the STRUCTURED half of
    `_declared_halt` (FR-12): `_halt_doors` and `decide` ask THIS whether the form carries the halt, never the
    wording of `_declared_halt`'s sentence. Same error direction as `_declared_halt`; `form_rel` "" or a form that
    cannot be read says nothing. Reads the form as the next check will see it (`handoff_check.form_view`): a halt the
    role wrote only in its values file is heard (SC1-2, B-1)."""
    import role_digest
    if not form_rel:
        return ""
    try:
        try:
            import handoff_check
            read = handoff_check.form_view
        except Exception:               # never "no halt" because an import failed: the raw form, as before
            import handoff

            def read(path):
                return handoff.parse(path.read_text(encoding="utf-8-sig"))
        verdict = read(task_root / form_rel).get("header.verdict")
    except Exception:
        verdict = None
    shown = str(verdict if isinstance(verdict, str) else "").strip().strip("\"'").strip()
    return shown if shown.lower() in role_digest.HALTING_VERDICTS else ""


def _no_change_note(dispatch: dict, refs: list, state: dict) -> str:
    """`no change against <rework_of>: ...` for a `repair_verify` rework of plan rows whose evidence is the very
    bytes its parent was accepted on, else "". A NOTE, never a refusal: a rework can legitimately end where it began
    (the rows were right). Compared by PATH; a path the parent has no counterpart for (this dispatch's own form) is
    not compared, and nothing shared means nothing to say. TP2-2406 S3-3: the accept cited an unchanged plan
    (sha 51ce88a8, the S3-2 sha) as the evidence of a repair."""
    parent_id = str(dispatch.get("rework_of") or "")
    if not (parent_id and dispatch.get("plan_rows") and dispatch.get("purpose") == "repair_verify"):
        return ""
    parent = (state.get("dispatches") or {}).get(parent_id) or {}
    before = {r.get("path"): r.get("sha256") for r in parent.get("evidence_refs") or [] if isinstance(r, dict)}
    shared = [r for r in refs if isinstance(r, dict) and r.get("path") in before]
    if shared and all(r.get("sha256") == before[r["path"]] for r in shared):
        names = ", ".join(str(r["path"]) for r in shared)
        return (f"no change against {parent_id}: {names} "
                f"{'is' if len(shared) == 1 else 'are'} byte-identical to what {parent_id} was accepted on, "
                f"so the rework of {', '.join(str(r) for r in dispatch['plan_rows'])} changed nothing there")
    return ""


def _pause_recover_door(task: str, dispatch_id: str, task_root: Path, agent="") -> str:
    """The pause -> recover road of a halted role, ONE spelling for every text that names it (`_halt_doors`,
    `_decide_refusal`; FR-37), with the story's real task, dispatch and task root - the only placeholder left is the
    reason, which only the conductor knows. `agent` (SC2-19): the dispatch record's `agent_id`; when it is a non-blank
    string the text also names the `resume` door - after that pause the same agent goes on, the person's word goes to
    it as a message. No agent on the record (absent, blank, not a string): the text is the old one, byte for byte."""
    text = (f"checkpoint it as blocked, `story_step.py pause --task {task} --dispatch-id {dispatch_id} --reason "
            "\"<what the role could not do>\" --status blocked`, then take a person's word on what the role stopped "
            f"for with the retry: `controller.py --task-root {task_root} --operation recover` (it prints the ready "
            "packet; the person's word goes with the retry)")
    agent = agent.strip() if isinstance(agent, str) else ""
    if not agent:
        return text
    return (text + "; or, when the person's word is for the same agent to go on: after that pause, "
            f"`story_step.py resume --task {task} --dispatch-id {dispatch_id}`, then the word goes to agent {agent} "
            "as a message")


def _halt_doors(args, task_root: Path, dispatch: dict, form_halted: bool) -> str:
    """The doors a halt refusal names, ONE table (F-4): S5 -> `pause` -> `recover` always; any other stage's closing
    role -> `decide` (`--close` / `--open`, as `decide` accepts them today); a role that does not close its stage ->
    `--close` only, and only when its FORM declares the halt (`decide` reads the form, never the digest: a door the
    command would refuse is no door, FR-2); a halt only in the digest of such a role has the pause/recover road alone.
    `form_halted` is the structured answer of `_form_halt_word` (FR-12), never read from the halt's sentence.
    INVARIANT: a halt never closes a role the person did not close, and no role is left without a door.
    SS1-13 (M8): at S1, when the scout's manifest says no change was found (`implementation.source: none`), one more door is named - the
    person's choice of how to ground the tests, recorded by `stage_done.py --set` and carried to the SAME scout by `resume` and a message
    (`resume` only prints; the value reaches the role in the message). It adds a door and closes nothing. A manifest that is absent or
    unreadable adds none (ERROR DIRECTION: a door for a halt that is not this one would send the person to a choice nobody asked)."""
    stage, did = dispatch["stage"], args.dispatch_id
    road = _pause_recover_door(args.task, did, task_root, dispatch.get("agent_id"))
    decide = f"`story_step.py decide --task {args.task} --dispatch-id {did} --words-file <file>"
    if stage != "S5" and C.stage_closes_with(stage, dispatch["role"]):
        doors = (f"record the person's decision, then run finish again: {decide} --close` (accept this work as it is) "
                 f"or `--open [<ids>]` (the stage stays open on that work). Or {road}")
    elif stage != "S5" and form_halted:
        doors = (f"record the person's decision, then run finish again: {decide} --close` (accept this work as it is; "
                 f"{stage} follows its own rule). Or {road}")
    else:
        doors = road
    return doors + _no_change_door(args.task, did, task_root, stage)


def _no_change_door(task: str, did: str, task_root: Path, stage: str) -> str:
    """The door of an S1 halt on `implementation.source: none` (SS1-13, M8): `""` at any other stage or when the manifest does not
    say `none` (read by `handoff_check.manifest_impl_source`, the one reader; absent or unreadable is not `none`)."""
    if stage != "S1":
        return ""
    try:
        import handoff_check
        manifest = json.loads((task_root / "work" / "context-manifest.json").read_text(encoding="utf-8"))
        if handoff_check.manifest_impl_source(manifest) != "none":
            return ""
    except Exception:
        return ""
    return (f". Or record the person's choice: `stage_done.py --task {task} --set implementation_source=<current-code|ungrounded>`, then "
            f"`story_step.py resume --task {task} --dispatch-id {did}`, and say `implementation_source: <value>` in the SendMessage it names")


def _halt_gate(args, task_root: Path, dispatch: dict, decided: dict) -> tuple:
    """`(refusal text, note)`. A declared halt is refused (exit 2 by the caller, nothing recorded) unless the person's
    decision on THIS dispatch is recorded (`open_work` / `close`; a `hand` record alone does not lift it) - then
    the halt is still named, as the note. POSITION INVARIANT (t-025, I4): read BEFORE `_handoff_check` (its `--fix`
    writes into the form) and before every branch that can pass the form, so neither `--ignore-handoff`, `--unresolved`
    nor a complete form gets past it; AFTER `_decision_of`, so a decision the person recorded is never refused twice
    (P13, FR-7)."""
    form_rel = FORM_REL.format(dispatch_id=args.dispatch_id)
    halted = _declared_halt(task_root, form_rel, args.digest)
    if not halted:
        return "", ""
    kind = "open_work" if "open_work" in decided else "close" if "close" in decided else ""
    if kind:
        at = decided[kind].get("at") if isinstance(decided[kind], dict) else None
        return "", f"the role declared a halt in {halted}; the person's recorded decision ({kind}, {at}) stands"
    return (f"story_step: {dispatch['role']} declared a halt in {halted}, and a declared halt is not an acceptance: "
            f"{args.dispatch_id} stays open and nothing was recorded.\n  The role handed the decision back. Doors: "
            + _halt_doors(args, task_root, dispatch, bool(_form_halt_word(task_root, form_rel)))
            + ". The role's own reason is in its form (`blocked`) and its digest."), ""


# --- the exit gate at `finish` (GW1-8, t-1264) ----------------------------------------------------------------------
# The exit gate was advice: the hook released a turn after ONE block, and the driver resumed the role. `finish` is the
# only code point between a non-closing role's stop and the next role's dispatch (S5 automator, S8 scribe; the
# controller re-checks most of S2, S3 and S4 at close), and it accepted an automator that had never run its tests - the
# critic was then handed a window with no author-run receipt (20261021 finding). So `finish` re-runs the stage's exit
# gate through the driver's own function and refuses an accept the gate still refuses.
# ERROR DIRECTION (advice -> gate): a false refusal costs one round with a named door; a false pass sends the critic an
# unrun window. Two things this function reuses fail OPEN and stay so here, named in the handoff: `s5_precheck`'s
# detector exits 0 on a crash and when it finds no running story, and a bare detector run finds "its" story by guess.

_GATE_CUT = 200       # a record or a word quoted inside the one-line pass note


def _gate_cut(text, limit: int = _GATE_CUT) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + "..."


def _gate_unreadable(args, task_root: Path, dispatch: dict, cause: str, detail: str = "", records=None,
                     findings=None) -> str:
    """The refusal (exit 2) of a gate that could not be read: what was not established, that it is never a pass, and the
    two doors that open (AR-28, FR-59). No recorded word is offered: there is no finding to judge, and a word would
    open nothing. No repair marker either: an unreadable gate is the factory's defect, not the author's work.

    With `records` (RH1-5: the `unreadable` records of checks that did not run, the third state of a detector) the text
    names every script and its reason, and the doors: fix the cause and `finish` again; the person's word that NAMES
    the script (`<script>: unreadable`, never `*`); the pause/recover road. `findings` are the author's own findings
    that stood next to them (a mixed set, E2): shown AFTER the unreadable ones through `render_saved`, so the role is
    never handed the factory's defect as its repair and the author's findings are never lost."""
    if records:
        import exit_gate
        stage_id, did = dispatch["stage"], args.dispatch_id
        scripts = list(dict.fromkeys(getattr(r, "script", "") or str(r) for r in records))
        lines = [f"story_step: {dispatch['role']} handed {did} off, but {len(records)} check(s) of the exit gate of "
                 f"{stage_id} could not run - the gate does not know whether the handoff is acceptable, and what it does "
                 "not know is never a pass - nothing was recorded. This is the factory's own defect, not the author's work:"]
        lines += ["  - " + str(r) for r in records]
        if findings:
            listing, _where = exit_gate.render_saved([str(f) for f in findings], _findings_file(task_root, did, "-finish.txt"),
                                                     args.task, f"story_step finish, dispatch {did}")
            lines += [f"  The author's own findings stand next to them ({len(findings)}); they are the author's repair, "
                      "and come AFTER the checks that did not run:", listing]
        doors = [person_words.door('waiver.py --task %s --stage %s --block "%s: unreadable"' % (args.task, stage_id, s))
                 for s in scripts]
        words = " or ".join(f"`{d}`" for d in doors)
        lines.append("  Doors: run `finish` again once the cause is fixed (name it in a factory finding so it is fixed); or "
                     f"the person's word that names the check, recorded by the conductor from their own words: {words} "
                     "(`*` and the bare word `unreadable` do not pass it), then `finish` again; or take the road "
                     + _pause_recover_door(args.task, did, task_root))
        return "\n".join(lines)
    return (f"story_step: {dispatch['role']} handed {args.dispatch_id} off, but the exit gate could not be read "
            f"({cause}){detail} for {dispatch['stage']}, and a gate that cannot be read is never a pass - nothing "
            f"was recorded.\n  No recorded word passes it (there is no finding to judge). Doors: run `finish` again "
            f"once the cause is fixed (name it in a factory finding so it is fixed), or take the author road: "
            + _pause_recover_door(args.task, args.dispatch_id, task_root))


def _gate_refusal(args, task_root: Path, dispatch: dict, blocking: list) -> str:
    """The text of exit 3: the head, every record through `detector_verdict.render` (whole up to its byte ceiling, past
    it the file `state/findings/<dispatch>-finish.txt`, written by that very call), the doors, the repair marker.
    The class of a record is `exit_gate.word_class` - the ONE rule `judge_words` applies, read from the record's
    fields, never from its text (FR-12) - so a door is named only where it opens (FR-2, FR-57)."""
    import exit_gate
    stage_id, did = dispatch["stage"], args.dispatch_id
    named, starred, refused = [], [], []
    for record in blocking:
        {"refused": refused, "star": starred, "named": named}[exit_gate.word_class(record)].append(record)
    path = _findings_file(task_root, did, "-finish.txt")
    listing, _where = exit_gate.render_saved([str(r) for r in blocking], path, args.task,
                                             f"story_step finish, dispatch {did}")
    lines = [f"story_step: {dispatch['role']} handed {did} off while the exit gate of {stage_id} still refuses it "
             f"({len(blocking)} finding(s)); a released turn is not an accepted handoff - nothing was recorded.",
             listing,
             f"  Doors: the author's repair, always - the conductor gives {dispatch['role']} ALL of these findings back in "
             "ONE message (the lines above, or the whole-list file they name) - never one finding per message - and "
             "the same role is resumed because this dispatch is not accepted yet (a rework opens only on accepted work), "
             f"or {_pause_recover_door(args.task, did, task_root)}; then run `finish` again."]
    if named:
        lines.append("  A person's recorded word passes the " + str(len(named)) + " finding(s) that carry no "
                     "`refused` tag, judged by the rule the hook and the driver apply: `"
                     + person_words.door(f'waiver.py --task {args.task} --stage {stage_id} --block '
                                         '"<a part only that line holds>"')
                     + "` (the conductor records the person's own words), then run `finish` again.")
    if starred:
        lines.append("  " + str(len(starred)) + " finding(s) were judged at their own source or are not in the "
                     "contract's form: only the person's `*` for the stage passes them, a named word does not: `"
                     + person_words.door(f'waiver.py --task {args.task} --stage {stage_id} --block "*"') + "`.")
    # a finding that WAITS for a word its source reads by identifier (an unnamed Then remainder) is `refused` to every word
    # the gate judges, but its own line names the person's word that opens it: that door is told apart (FR-10, FR-2)
    waiting = [r for r in refused if not getattr(r, "refused", None)
               and exit_gate._finding_tag_of(r).startswith(exit_gate.WAITING_FINDING_TAGS)]
    refused = [r for r in refused if r not in waiting]
    if waiting:
        lines.append("  " + str(len(waiting)) + " finding(s) wait for the person's word their line names (`then handed: "
                     "<case>#<n>`), recorded by the conductor from the person's own words; `*` does not pass them.")
    if refused:
        lines.append("  " + ("No recorded word passes these; they are the author's repair." if not (named or starred or waiting)
                             else f"{len(refused)} finding(s) carry the source's `refused` tag: no recorded word "
                                  "passes them, `*` included; they are the author's repair."))
    lines.append(f"  {REPAIR_MARKER}.")
    return "\n".join(lines)


def _passed_note(passed: list) -> str:
    """ONE note for the findings a person's recorded word passed: the count, the first record and the first decision,
    each cut (an informed pass is recorded, never silent: FR-4)."""
    first = passed[0]       # `judge_words` passes only dicts: {"error": record, "decision": words, "at": ...}
    return (f"the exit gate's {len(passed)} finding(s) passed by the person's recorded word: "
            f"{_gate_cut(first.get('error'))} <- \"{_gate_cut(first.get('decision'))}\"")


def _finish_gate(args, task_root: Path, dispatch: dict, decided: dict) -> tuple:
    """`(exit code, refusal text, notes)` of the stage's exit gate at `finish`; code 0 accepts, with the notes to print.

    WHO reads it: the roles whose stage declares `detectors` in stages.json, asked of `exit_gate.detector_gates()` (the
    one reader of that map; no role is named here). A role with none is not read at all and `finish` is byte-identical
    to what it was. WHAT is read: `exit_gate.all_errors(role, task, "")`, the driver's own function (`Driver.exit_errors`),
    with an empty digest - `finish`'s `--digest` is whatever the caller passes, and its shape is the hook's and the
    driver's to judge, never a reason to refuse an accept. The person's word is judged inside that call.

    POSITION: after `_halt_gate` and the form branches, before `_evidence`, `prepare` and `apply`. INVARIANTS: a
    refusal records nothing; no flag lifts it (the caller never reaches this function's arguments); a dispatch the
    person DECIDED (`state/decisions/<D>.json` holds `open_work` or `close` for THIS dispatch id, a halt or not) is
    not refused a second time and its skip is said, naming the decision kind (P13, FR-7, FR-9; GW1-8 fix round F1 -
    S5 stays closed to it, `decide` refuses `--open/--close` there); a decision file that cannot be read is no
    decision (`_decision_of` says so) and the gate runs; an unreadable verdict (the reader raised, or answered a
    shape that is not `(blocking, passed)`) is exit 2 and never an accept (AR-28)."""
    import exit_gate
    role = dispatch["role"]
    try:
        gated = bool(exit_gate.detector_gates().get(role))
    except Exception as exc:
        return 2, _gate_unreadable(args, task_root, dispatch, type(exc).__name__), []
    if not gated:
        return 0, "", []
    kind = "open_work" if "open_work" in decided else "close" if "close" in decided else ""
    if kind:
        at = decided[kind].get("at") if isinstance(decided.get(kind), dict) else None
        return 0, "", [f"the exit gate was not re-read: the person's recorded decision ({kind}, {at}) stands for "
                       "this dispatch"]
    try:
        # the stage and the dispatch `finish` holds are named to the detectors (t-440; TR3-13: two windows, the count cannot say which)
        with exit_gate.holding_stage(dispatch.get("stage")), exit_gate.holding_dispatch(dispatch.get("id")):
            answer = exit_gate.all_errors(role, args.task, "")
    except Exception as exc:
        return 2, _gate_unreadable(args, task_root, dispatch, type(exc).__name__), []
    if not (isinstance(answer, tuple) and len(answer) == 2 and all(isinstance(part, list) for part in answer)):
        return 2, _gate_unreadable(args, task_root, dispatch, "unknown shape",
                                   f"; it answered {type(answer).__name__}, not (blocking, passed)"), []
    blocking, passed = answer
    # RH1-5: a check that could not run is exit 2 - never 3 (the author's repair) and never 0. POSITION: after the shape
    # check, before `if blocking`. INVARIANT: an `unreadable` record in `blocking` never reaches exit 3 or 0; one in
    # `passed` (a person's word named it) does not refuse (E17); nothing is recorded; the signal is the trace for the report.
    unreadable = [r for r in blocking if getattr(r, "kind", "") == "unreadable"]
    if unreadable:
        import hooklib
        hooklib.person_signal({}, "gate_unreadable", "; ".join(str(r) for r in unreadable), task=args.task)
        return 2, _gate_unreadable(args, task_root, dispatch, "unreadable checks", records=unreadable,
                                   findings=[r for r in blocking if getattr(r, "kind", "") != "unreadable"]), []
    if blocking:
        return 3, _gate_refusal(args, task_root, dispatch, blocking), []
    return 0, "", ([_passed_note(passed)] if passed else [])


def _digest_of(task_root: Path, dispatch_id: str) -> str:
    """The digest the exit gate filed for this dispatch (`work/digests/<id>.txt`, written by `exit_gate._write_digest`),
    or "" when there is none, it cannot be read, or the id is not a plain file name. The ONE reader of that file."""
    import exit_gate
    path = exit_gate.digest_path(task_root, dispatch_id)
    if path is None:
        return ""
    try:
        return path.read_text(encoding="utf-8-sig").strip()
    except (OSError, ValueError):
        return ""


def _stamp_plan_review(task: str, task_root: Path, dispatch_id: str) -> str:
    """"" once the receipt of the plan the critic judged is written (`s5_plan.stamp_review`), else the refusal of `finish`: what could
    not be written, what is expected, and the doors the conductor has (the author mends the file; the receipt file is repaired)."""
    import s5_plan as SP
    try:
        SP.stamp_review(task_root, dispatch_id)
    except (ValueError, OSError) as exc:
        return (f"story_step: the review of the plan was not receipted, so {dispatch_id} is not accepted: {exc}. The receipt "
                f"({SP.REVIEWS_REL}) records which plan the critic read; expected a readable {SP.PLAN_REL} and a receipt file that is "
                f"a JSON list. Door: repair the file named, or send the author back over the plan "
                f"({_rework_command(task, 'qa-automator', [], 'the plan file cannot be read')}), then finish again. {REPAIR_MARKER}.")
    return ""


def _rework_command(task: str, role: str, cases: list, reason: str, cause: str = "") -> str:
    """A ready `controller.py` rework command of S5 (the SC1-8 form: it ends with `--brief`). With `cause` it is a rework of window
    work (no purpose word); without, a rework of the PLAN (`--purpose s5_plan`). No `--cases` when `cases` is empty (the whole scope)."""
    how = f" --cause {cause}" if cause else f" --purpose {S5_PLAN}"
    on = f" --cases {','.join(cases)}" if cases else ""
    return f"controller.py --task {task} --operation rework --stage S5 --role {role}{how}{on} --reason \"{reason}\" --brief"


def _start_command(task: str, role: str, scope: list, purpose: bool = False) -> str:
    return (f"story_step.py start --task {task} --stage S5 --role {role}" + (f" --purpose {S5_PLAN}" if purpose else "")
            + (f" --scope {','.join(scope)}" if scope else ""))


def _plan_next(task: str, task_root: Path, controller: Controller, dispatch_id: str) -> tuple:
    """`([ready commands], [notes])` for the move after a finished PLAN dispatch (SC1-14 C1 step 5, t-1314 delta):

    - the author's plan: no review yet -> `start` the plan critic over the same scope; a review exists (a rework) -> the critic's
      narrow look, a `rework` of the critic over the rows that moved since that review (`s5_plan.moved_cases`: changed and new);
    - the critic's plan, `approved*`: one rework of the author per window that GREW after the review (`stage_scope` `grown`, the
      cases and the tests that tie them), else `start` of the first window that lacks an accepted role (its author, then its critic);
    - the critic's plan, `blocked`: the author's `rework` over the cases the blockers bind (the whole scope when a blocker names none).

    The windows are read from `stage_scope`, the reviews through `s5_plan.reviews`/`review_of` (THE readers). Advice, never a gate
    (P1): a failure to derive it is a note naming `where`, and `finish` has already accepted."""
    try:
        import s5_plan as SP
        state = controller.state()
        record = (state.get("dispatches") or {}).get(dispatch_id) or {}
        scope = [str(case) for case in record.get("scope") or []]
        plan = SP.load(task_root)
        if record.get("role") == "qa-automator":
            chain = [e for e in SP.reviews(task_root, state) if not e["unreadable"]]
            if not chain:
                return [_start_command(task, "qa-code-critic", scope, purpose=True)], []
            changed, new = SP.moved_cases(plan, chain[-1]["rows_sha"])
            moved = sorted(changed | new) or scope
            return [_rework_command(task, "qa-code-critic", moved,
                                    "look again at the plan rows that changed since your review: " + ", ".join(moved))], []
        element = SP.review_of(task_root, dispatch_id)
        if element["unreadable"] or element["outcome"] is None:
            return [], [f"next command not derived: the review of {dispatch_id} cannot be read ({element['unreadable']}); "
                        f"`story_step.py where --task {task}` names the next move"]
        if element["outcome"] == "blocked":
            bound = SP.blocker_cases(plan, element["remarks"], element["tests"])
            blockers = [r["id"] for r in element["remarks"] if r["kind"] == "blocker"]
            return [_rework_command(task, "qa-automator", sorted(bound) if bound else scope,
                                    "mend the plan rows the critic blocked: " + ", ".join(blockers))], []
        windows = controller.stage_scope("S5", state).get("windows") or []
        out = []
        for window in windows:
            grown = [str(case) for case in window.get("grown") or []]
            if not grown:
                continue
            kept = set(str(case) for case in window["scope"]) - set(grown)
            ties = sorted(test for test, cases in SP.tests_cases(plan).items() if set(cases) & set(grown) and set(cases) & kept)
            out.append(_rework_command(
                task, "qa-automator", [str(case) for case in window["scope"]],
                f"case(s) {', '.join(grown)} added to S5 after the plan review"
                + (f"; test(s) {', '.join(ties)} extend this window" if ties else ""), cause="ticket_changed"))
        if out:
            return out, []
        for window in windows:
            have = window.get("accepted_by") or {}
            if "qa-code-critic" in have:
                continue
            role = "qa-code-critic" if "qa-automator" in have else "qa-automator"
            return [_start_command(task, role, [str(case) for case in window["scope"]])], []
        return [], ["the plan review is accepted and no window is left without its author and critic"]
    except Exception as exc:    # noqa: BLE001 - advice must never undo an accepted finish
        return [], [f"next command not derived ({type(exc).__name__}: {exc}); `story_step.py where --task {task}` names the next move"]


def _author_door_form(task: str, dispatch_id: str = "<critic>") -> str:
    """The `finish --needs-author` command line as a person or the conductor types it (one spelling for every refusal below)."""
    return (f'story_step.py finish --task {task} --dispatch-id {dispatch_id} --needs-author <cases> --reason "<words>" '
            "[--cause <repair cause>]")


def _critic_retry_lines(controller, task_root: Path, dispatch: dict) -> list:
    """HF8-15 (2) step 5: the `--- next: ... ---` line of the critic's retry, printed by the AUTHOR's `finish`.

    After `finish --needs-author` the critic's record is `incomplete`; the author's acceptance puts `next` on `prepare_stage S5`
    (`superseded_by_later_work` hides a stop behind later accepted work of the same STAGE, and that invariant is not touched),
    so without this line the conductor has no pointer to the packet that retries the critic. The one reader is
    `Controller.retry_packets` (it lists only a stopped dispatch with no later record of the same stage AND role: the packet of the
    critic whose window this author just repaired). Advice: any failure prints nothing and never undoes an accepted finish."""
    try:
        if dispatch.get("stage") != DEBT_STAGE or dispatch.get("role") != "qa-automator" or s5_part_of(dispatch) == "plan":
            return []
        mine = {str(case) for case in dispatch.get("scope") or []}
        lines = []
        for packet in controller.retry_packets():
            stopped = (controller.state().get("dispatches") or {}).get(packet.get("dispatch_id")) or {}
            if (stopped.get("stage") == DEBT_STAGE and stopped.get("role") == DEBT_ROLE
                    and mine & {str(case) for case in stopped.get("scope") or []}):
                lines.append(f"controller.py --task-root {task_root} --operation recover prints the critic's retry packet for "
                             f"{stopped.get('id')}; dispatch it with --operation dispatch --input <file>, then "
                             + launch_card.materialize_door(task_root.name, "<the packet's id>"))
        return lines
    except Exception:   # noqa: BLE001 - advice must never undo an accepted finish
        return []


def _needs_author(args) -> int:
    """HF8-15 (2): `finish --needs-author <cases> --reason "<words>"` - the S5 critic could not judge because its AUTHOR's work is
    defective; the window is NOT accepted, the critic's record is checkpointed `incomplete`, and the author gets a rework.

    Run 12586 (29.10) and 14857 (30.10): `rework` was refused while the critic ran, `finish --not-complete` and `checkpoint` too, and
    the conductor went round the controller with a message to the closed author (no record, FR-9). This is the one move.

    `accept` is never called on this path: the window is not accepted, no receipt is owed, and the round the critic spent is not
    spent again (`_code_review_refusal` is not bypassed - it is not reached). The steps, in this order, are the invariant:
    1. every check, then the PROBE: the rework request is built and judged by the very function that will judge it
       (`Controller.validate("dispatch")`) on a COPY of the state in which the critic is `incomplete`. A refusal there costs nothing; a
       refusal after step 2 would leave the critic `incomplete` with no author (the third repair cycle did exactly that in the plan
       critic's measurement). Every refusal of step 3 except a revision race is therefore visible before step 2.
    2. the critic is checkpointed `incomplete` (the `active_binding` veto stands: a worker that is not proved returned is not closed).
    3. the receipt of the critic is released, the request is rebuilt (the revision moved) and dispatched; a resumed author is bound.
    A repeat after a failure of step 3 skips step 2 (the critic is already `incomplete`): a state with a way out, never a trap."""
    cases = [part.strip() for part in str(args.needs_author or "").split(",") if part.strip()]
    reason = (getattr(args, "reason", None) or "").strip()
    cause = (getattr(args, "cause", None) or "").strip() or None
    form = _author_door_form(args.task, args.dispatch_id)
    extra = [flag for flag, given in (("--complete", getattr(args, "complete", False)),
                                      ("--unresolved", getattr(args, "unresolved", None)),
                                      ("--ignore-handoff", getattr(args, "ignore_handoff", False)),
                                      ("--window", getattr(args, "window", None)),
                                      ("--output", getattr(args, "output", None))) if given]
    if extra:
        print(f"story_step: finish got --needs-author together with {', '.join(extra)}. This move accepts nothing (the critic "
              "judged nothing and the window stays open), so a flag of an acceptance has no meaning here: drop one. "
              f"Form: {form}. {REPAIR_MARKER}.")
        return 2
    if not cases or not reason:
        print("story_step: finish --needs-author needs " + ("the case ids of the window the author repairs" if not cases else "")
              + (" and " if not cases and not reason else "")
              + ("--reason (what the author must repair: the author reads it as the task)" if not reason else "")
              + f". Form: {form}. {REPAIR_MARKER}.")
        return 2
    task_root = _task_root(args.task)
    controller = Controller(task_root, wait_seconds=_wait(args))
    state = controller.state()
    dispatch = (state.get("dispatches") or {}).get(args.dispatch_id)
    if not dispatch:
        print(f"story_step: no dispatch {args.dispatch_id} in this story; it has "
              + (", ".join(sorted(state.get("dispatches") or {})) or "none") + f". {REPAIR_MARKER}: name one of them.")
        return 2
    rework = _rework_command(args.task, "qa-automator", cases, reason, cause=cause or "test_defect")
    if (dispatch.get("stage"), dispatch.get("role")) != (DEBT_STAGE, DEBT_ROLE):
        print(f"story_step: --needs-author is the S5 code critic's move; {args.dispatch_id} is {dispatch.get('role')} on "
              f"{dispatch.get('stage')}. For another role's work the door is the controller's own rework, once that dispatch is "
              f"finished or stopped: `{rework.replace('--stage S5 --role qa-automator', '--stage <S> --role <role>')}`. "
              f"{REPAIR_MARKER}.")
        return 2
    if s5_part_of(dispatch) == "plan":
        print(f"story_step: {args.dispatch_id} judges the S5 PLAN, not a window; the plan's author is sent back with "
              f"`{_rework_command(args.task, 'qa-automator', [], reason)}` (the plan has its own road, phases/s5.md). {REPAIR_MARKER}.")
        return 2
    status = dispatch.get("status")
    if status not in ("running", "returned_unaccepted", "incomplete"):
        print(f"story_step: {args.dispatch_id} is {status}, so it holds no open window to send back: a closed critic's work "
              f"is taken through the controller, `story_step.py where --task {args.task}` names the move. {REPAIR_MARKER}.")
        return 2
    from controller import closure_of
    if closure_of(state, controller._pipeline())["state"] != "open":
        print(f"story_step: this story is closed or executing the orders of gate B, and more work on it is the person's decision, "
              f"not the factory's: record their words and rework with `controller.py --task-root {task_root} --operation rework "
              f"--stage S5 --role qa-automator --cases {','.join(cases)} --words-file <their words> --brief`, which reopens it.")
        return 2
    canonical, outside = controller._outside_approved(cases, dispatch.get("scope") or [])
    if outside:
        print(f"story_step: case(s) {', '.join(member for member, _ in outside)} are not in the window of {args.dispatch_id}: its "
              f"scope is {', '.join(sorted(map(str, dispatch.get('scope') or []))) or 'empty'}. The author is sent back over the "
              f"cases the critic was judging, never over work outside its window. {REPAIR_MARKER}.")
        return 2

    def build():
        return controller.build_rework_request("S5", "qa-automator", canonical, reason, cause=cause)

    def refused(exc) -> int:
        print(f"story_step: refused - {type(exc).__name__}: {exc}")
        return 2
    try:    # step 1: the probe. A copy of the state, the critic `incomplete`: what `dispatch` will see after step 2.
        import copy
        projected = copy.deepcopy(state)
        projected["dispatches"][args.dispatch_id]["status"] = "incomplete"
        controller.validate("dispatch", build(), projected)
    except Exception as exc:    # noqa: BLE001 - the call's own refusal goes out whole; nothing is written yet
        return refused(exc)
    if status != "incomplete":    # step 2 (skipped on a repeat: the critic is already `incomplete`, E9)
        try:
            controller.apply("checkpoint", controller.build_checkpoint_request(args.dispatch_id, "incomplete", reason,
                                                                                remaining=";".join(canonical)))
        except Exception as exc:    # noqa: BLE001
            refused(exc)
            if "host worker is still active" in str(exc):
                print(f"{args.dispatch_id} is not proved returned: wait for its stop (a text end is sent back by the exit gate); "
                      f"if it is gone: `controller.py --task-root {task_root} --operation release --dispatch {args.dispatch_id} "
                      "--words-file <the person's words>`. Nothing was recorded.")
            return 2
    _release_binding(task_root, args.dispatch_id, args.task)    # step 3
    try:
        request = build()
        controller.apply("dispatch", dict(request))
    except Exception as exc:    # noqa: BLE001
        refused(exc)
        print(f"{args.dispatch_id} is recorded incomplete and the author is not started: repeat the same command (it skips "
              f"the critic's record and opens the author), or `story_step.py where --task {args.task}`.")
        return 2
    bound = ""
    if request.get("agent_id"):
        import contextlib
        import io
        said = io.StringIO()
        with contextlib.redirect_stdout(said):
            code = bind(argparse.Namespace(task=args.task, dispatch_id=request["id"], agent_id=request["agent_id"]))
        bound = (f"; resumed agent {request['agent_id']} is bound to it" if not code else
                 f"; the agent {request['agent_id']} was NOT bound ({said.getvalue().strip().splitlines()[-1:]}): run "
                 f"`story_step.py bind --task {args.task} --dispatch-id {request['id']} --agent-id {request['agent_id']}`")
    print(f"critic {args.dispatch_id} is incomplete: {reason}")
    print(f"author {request['id']} is running: rework of {request.get('rework_of')} over {', '.join(request['scope'])} "
          f"(cause {request.get('repair_cause') or 'test_defect'}){bound}")
    print(launch_card.materialize_door(args.task, request["id"]))
    print(f"--- after the author's finish: controller.py --task-root {task_root} --operation recover prints the critic's retry "
          "packet; dispatch it with --operation dispatch --input <file>, then "
          + launch_card.materialize_door(args.task, "<the packet's id>") + " ---")
    return 0


def finish(args) -> int:
    # HF8-15 (2). POSITION: the FIRST line, before `_unresolved_refusal`. INVARIANT: the `--unresolved`/`--reason` pair and `--digest`
    # judge an acceptance, and this move has none; without `--needs-author` the path below is the path it always was, byte for byte.
    if getattr(args, "needs_author", None) is not None:
        return _needs_author(args)
    if getattr(args, "digest", None) is None:
        print("story_step: finish needs --digest (the role's digest line, or `-` for the one the exit gate filed). Form: "
              'finish --task <T> --dispatch-id <ID> --digest "<digest>"; for an S5 critic that cannot judge because of its '
              f'author\'s defect: {_author_door_form("<T>")}. {REPAIR_MARKER}.')
        return 2
    unresolved = (getattr(args, "unresolved", None) or "").strip()
    reason = (getattr(args, "reason", None) or "").strip()
    refusal = _unresolved_refusal(args, unresolved, reason)
    if refusal:
        print(refusal)
        return 2
    task_root = _task_root(args.task)
    controller = Controller(task_root, wait_seconds=_wait(args))
    dispatch = controller.state().get("dispatches", {}).get(args.dispatch_id)
    if not dispatch:
        print(f"story_step: no dispatch {args.dispatch_id} in this story; it has "
              + (", ".join(sorted(controller.state().get("dispatches") or {})) or "none")
              + f". {REPAIR_MARKER}: name one of them.")
        return 2
    if str(getattr(args, "digest", "") or "").strip() == "-":
        # `--digest -`: the digest the exit gate filed for THIS dispatch. Without a file (the role stopped before 0.10.3,
        # or two dispatches of the role were live) the line must be passed: a digest is never taken from another dispatch.
        args.digest = _digest_of(task_root, args.dispatch_id)
        if not args.digest:
            print(f"story_step: no digest recorded for {args.dispatch_id} by the exit gate (the role stopped before 0.10.3, "
                  "or two dispatches of the role were live); pass the role's digest line: --digest \"<…>\". "
                  f"{REPAIR_MARKER}.")
            return 2
    refusal = _open_window_refusal(args, unresolved, dispatch["stage"])
    if refusal:
        print(refusal)
        return 2
    stage = _stages()[dispatch["stage"]]
    role = dispatch["role"]
    optional = _optional_row(dispatch["stage"], role, _purpose_of(dispatch))      # t-2277 FL-5: an optional dispatch, never a closer
    # The handover form IS the handover. It is checked here, repaired by code where code can
    # derive the value, and kept as evidence - so a receipt nobody wrote cannot close a stage.
    # Required by DEFAULT: a story already running under an older build, whose roles do not
    # know about the form, sets `handoffs.required: false` in config.json; one dispatch passes
    # with `--ignore-handoff`, recorded like any other block a person's word passes.
    # The person's recorded decision on this dispatch (`decide --open` / `--close`) outranks the driver's flag (P13),
    # and it is read BEFORE the halt below, which it lifts (`_halt_gate`: the halt is then a note). A halted
    # dispatch that gets past the gate HAS that decision, and the decision counts as the person's word on the
    # form too (FR-7: the word is not asked twice; the decision file is the record).
    decided = _decision_of(task_root, args.dispatch_id)
    halt_refusal, halt_note = _halt_gate(args, task_root, dispatch, decided)
    if halt_refusal:
        print(halt_refusal)
        return 2
    ignore_handoff = bool(getattr(args, "ignore_handoff", False) or halt_note)
    status, form_note, form_rel = _handoff_check(args.task, args.dispatch_id, task_root)
    required = bool((_config().get("handoffs") or {}).get("required", True))
    if status == "problems" and not ignore_handoff:
        print(f"story_step: the handover form is not complete - {form_note}")
        print(f"  the whole list: handoff_check.py --file {task_root / form_rel} "
              f"--task {args.task} --fix")
        print("  every line of it is about the FORM, not about your work. What you cannot fill "
              "goes under `blocked` and to handoff_help.py; the conductor answers, never the person.")
        print(f"  {REPAIR_MARKER}.")
        print(f"  {_FORM_DOORS}")
        return 3
    if status == "untouched" and required and not ignore_handoff:
        print(f"story_step: {role} left its handover form untouched, and the form IS the "
              f"handover: {task_root / form_rel}")
        print(f"  fill it, then: handoff_check.py --file {task_root / form_rel} "
              f"--task {args.task} --fix")
        print(f"  {_FORM_DOORS}")
        print(f"  {REPAIR_MARKER}.")
        return 3
    # GW1-8: the stage's exit gate is read here - after the halt and the form, before anything is recorded. A flag
    # (`--ignore-handoff`, `--unresolved`, `--complete`, `--window`) never reaches it; only the person's recorded
    # word (judged inside the read) or the person's decision recorded on this dispatch lifts it.
    gate_code, gate_text, gate_notes = _finish_gate(args, task_root, dispatch, decided)
    if gate_code:
        print(gate_text)
        return gate_code
    # Only a form that PASSED its check is evidence. An untouched one is not a handover, and
    # counting it would have hidden the older refusal for a dispatch that produced nothing.
    extra = [form_rel] if status == "green" and form_rel else []
    if optional is not None:       # an optional dispatch is receipted by its OWN output, not by the stage's (the row's `output`)
        import stage_guard
        extra += list(stage_guard.optional_outputs(optional))
    outputs = _evidence(task_root, stage,
                        (args.output or []) + _role_receipts(task_root, role, args.dispatch_id) + extra)
    if not outputs:
        print(f"story_step: {role} left none of the outputs {dispatch['stage']} declares; "
              "that is a missing handover, not an acceptance - re-dispatch once, then halt. "
              f"{REPAIR_MARKER}.")
        return 3
    # The stage closes with its last role - except where the phase file says otherwise. S8's
    # last role is `qa-bug-reporter`, which runs AFTER gate B, while the stage itself must be
    # `completed` BEFORE the gate is recorded (s8.md §2c, and the controller refuses a gate
    # decision on an incomplete stage). `--complete` is that case, named out loud.
    plan_part = dispatch["stage"] == "S5" and s5_part_of(dispatch) == "plan"
    if optional is not None:
        # POSITION: before the plan and last-role rules. INVARIANT: an optional dispatch (the first look) closes nothing, whatever
        # `--complete` says or its role is: the stage's own roles close it (the strategist's window 2, the critic's verdict).
        complete = False
    elif plan_part:
        # A PLAN dispatch never closes S5 (SC1-14 C1; its critic is the stage's last role, so "the last role closes" would
        # close the stage over windows nobody wrote): only the person's `--complete` reaches the controller, which refuses it
        # (B1b) with its door - the refusal is the controller's, not a silent drop of the flag here.
        complete = bool(args.complete) and not args.not_complete
    else:
        complete = not args.not_complete and (args.complete or role == stage.get("roles", [role])[-1])
    decision_notes = ([halt_note] if halt_note else []) + gate_notes
    if "open_work" in decided:
        if complete:
            decision_notes.append("the person's recorded decision keeps " + dispatch["stage"] + " open: "
                                  + ", ".join(decided["open_work"].get("unresolved") or []))
        complete = False
        if not unresolved:
            unresolved, reason = _open_pair(task_root, decided["open_work"])
    elif "close" in decided:
        if not C.stage_closes_with(dispatch["stage"], role):
            # A role that does not close its stage (a halted S4 designer): `close` means "accept this work as it
            # is" and the stage follows its OWN rule - the decision never closes a stage over the role after it.
            decision_notes.append("the person's recorded decision accepts this work as it is (" +
                                  str(decided["close"].get("words_ref")) + "); " + dispatch["stage"] +
                                  " follows its own rule")
        else:
            if not complete:
                decision_notes.append("the person's recorded decision closes " + dispatch["stage"]
                                      + " on this work as it is (" + str(decided["close"].get("words_ref")) + ")")
            complete = True
    options = {"dispatch_id": args.dispatch_id, "outputs": outputs, "stage_complete": complete}
    if getattr(args, "open_windows", None) is not None:
        # t-1937 TR3-4: the OTHER windows the scheduler knows are still open; the controller reads it (accept validate) and
        # checks every case is a real window of the stage. An empty list is sent as it is: the controller refuses it by name.
        options["open_windows"] = [part.strip() for part in str(args.open_windows).split(",") if part.strip()]
    if complete and dispatch["stage"] == "S1":
        options.update(_s1_accepted_gaps(task_root))
    if unresolved:
        # The word goes through UNCHANGED: the controller reads `unresolved` as present-or-not, plus
        # `handed_to_person` by name (`names_handed`, which reads this field and `reason` together), and
        # has no other vocabulary to map it into. After the S1 line above on purpose: a word the
        # conductor gave outranks the one derived from an inventory.
        options["unresolved"] = unresolved
        options["reason"] = reason
    window_note = ""
    if complete and dispatch["stage"] == "S5":
        # FR-5: the controller refuses an S5 completion without the window record, so this
        # path must be able to pass one - the named file, else the record window_record.py
        # wrote for this dispatch. Unreadable or absent: no window, the controller's own refusal.
        given = getattr(args, "window", None)
        path = Path(given) if given else task_root / "work" / "windows" / f"{args.dispatch_id}.json"
        if given and not path.is_absolute():
            path = task_root / path
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                loaded = None
            if isinstance(loaded, dict):
                options["window"] = loaded
                window_note = f"S5 window record passed to the controller: {path}"
                # t-219 (B5): a window whose only gaps are instances the stand blocked, or the person runs,
                # is the critic's finished work (`window_record.py` exits 0 with "acceptable as unresolved"),
                # so the pair the controller wants is DERIVED here, from the record's own gaps, instead of
                # costing a round that ends in a hand-typed `--unresolved`. A caller's pair goes through
                # unchanged. `--not-complete` never reaches this block (`complete` is false: an open stage
                # stays open, E14).
                gaps = _window_gaps(loaded, task_root)
                blocked_ids = _blocked_ids(gaps)
                # t-721 (3.2): cases that list no instance and that the manifest carries as handed to the person.
                # `empty_scope` is covered only when EVERY case of the scope is such a case (INVARIANT: the pair is
                # derived only when every gap is of a derivable kind; a window with no gap and no such case gives
                # `()`; a case the manifest does not carry gets no pair, the controller's "does not carry" stays).
                no_instance = _handed_no_instance(loaded, controller) if gaps is not None else []
                if gaps and no_instance and "empty_scope" in gaps and set(loaded["scope_instances"]) <= set(no_instance):
                    gaps = [gap for gap in gaps if gap != "empty_scope"]
                if not unresolved and (gaps or no_instance):
                    shown = path.relative_to(task_root).as_posix() if path.is_relative_to(task_root) else str(path)
                    pair = _derived_pair(gaps, shown, _ran_red_marks(loaded, gaps), no_instance)
                    if pair:
                        options["unresolved"], options["reason"] = pair
                        window_note += (f"; every gap of it is a blocked_by_env, handed_to_person or probe_gap "
                                        f"instance, "
                                        f"so it is accepted as unresolved ({pair[0]}) and the reason names them")
                elif unresolved:
                    # Q8: the controller refuses blocked gaps unless the completion NAMES the word, so a pair
                    # that came from the caller keeps its words and gains the instances' own; F2 (critic t-243):
                    # and the `ran red` marks too (P20/FR-10). t-721 (F-14): a handed case with no instance that
                    # the caller's pair does not name is appended, so ONE pair names every case the person runs.
                    # Order, cut and what is never cut: `_caller_pair_reason`.
                    # INVARIANT kept (edge viii): a window that hands INSTANCES still needs the caller to say the
                    # word - the append supplements a pair that already speaks it, it never makes one that does
                    # not speak it pass `names_handed`.
                    speaks = "handed_to_person" in reason or not any(
                        gap.startswith("handed_to_person:") for gap in gaps or [])
                    missing = [case for case in no_instance
                               if speaks and f"handed_to_person:{case}" not in reason]
                    if blocked_ids or missing:
                        options["reason"] = _caller_pair_reason(
                            reason, blocked_ids, _ran_red_marks(loaded, gaps) if blocked_ids else [], missing)
    packet = controller.prepare(options)
    if plan_part and role == "qa-code-critic":
        # POSITION INVARIANT (SC1-14 C1, N7/R2): the receipt of the plan the critic judged is written BEFORE the accept - the accept
        # reads its own receipt (`s5_plan.review_of`) - and AFTER every refusal above (a refused finish stamps nothing) and after
        # `prepare` (a request that cannot be built stamps nothing). A stamp that cannot be written refuses the finish: an
        # accept with no receipt would be refused by the controller anyway, and this says why and what to do (FR-1/FR-2).
        stamp_refusal = _stamp_plan_review(args.task, task_root, args.dispatch_id)
        if stamp_refusal:
            print(stamp_refusal)
            return 3
    # Read BEFORE `apply`: the note compares against the parent's accepted refs, not the post-accept state.
    unchanged = _no_change_note(dispatch, (packet.get("accept_request") or {}).get("evidence_refs") or [],
                                controller.state())
    stale = None
    try:
        controller.apply("accept", packet["accept_request"])
    except EventCommitted as exc:
        # The accept IS committed (every `EventCommitted` is raised only after the commit: the
        # projection under the lock, or the dashboard after it, did not finish). The tail below is
        # owed all the same: without it the stage stayed `running` in pipeline.json and the host's
        # receipt stayed non-terminal, behind a refusal that says nothing was lost. Told by TYPE,
        # never by the refusal's words (FR-12). Any OTHER exception means nothing committed and goes
        # through to the caller as before.
        stale = exc
    _release_binding(task_root, args.dispatch_id, args.task)
    notes = ([window_note] if window_note else []) + decision_notes
    stale_index = len(notes)
    if stale is not None:
        notes.append(_stale_view_note(stale, args.dispatch_id, task_root))
    # A report, not a gate: it sits BEFORE the stage_done lines so a refusal printed below still
    # follows its own reason directly, and it adds nothing when the file did not change.
    notes += config_finding(args.dispatch_id, dispatch)
    if unchanged:
        notes.append(unchanged)     # printed with its `note: ` prefix below, like every note
    if complete:
        code, out = _run("stage_done.py", "--task", args.task, "--stage", dispatch["stage"],
                         "--status", "done", "--role", role, "--digest", args.digest)
        # The last four lines of stage_done's output, PLUS every line that opens with the S3 remark head: what stage_done
        # prints after it (the window notice, the pipeline line, stderr) must never push the remarks off (E9, AR-21).
        # A line in both groups is taken once, at its place in the output.
        said = [line for line in out.splitlines() if line.strip()]
        # The remark lines (findings and "not checked" alike: one head, `stage_done.s3_remark_line`) are kept up to the same limit;
        # past it the count of the rest is said, never a silent cut (RH1-12, FR-41).
        remark_numbers = [number for number, line in enumerate(said) if line.startswith(stage_done.S3_REMARK_PREFIX)]
        shown = set(remark_numbers[:4])
        notes += [line for number, line in enumerate(said) if number >= len(said) - 4 or number in shown]
        if len(remark_numbers) > 4:
            notes.append(f"(+{len(remark_numbers) - 4} more not checked)")
        if code:
            # The stale view is still said, as a note, and it is the only line that differs from the
            # same refusal after a fresh view: stage_done's refusal and exit stand alone as the halt.
            if stale is not None:
                notes[stale_index] = "note: " + notes[stale_index]
            print("\n".join(notes))
            print(f"story_step: stage_done refused {dispatch['stage']} (exit {code}); the refusal above is the halt")
            return code
    if stale is not None:
        # Only now is "closed" true: stage_done has recorded the stage.
        notes[stale_index] = ((f"{dispatch['stage']} is recorded and closed; " if complete else
                               f"the accept is recorded and {dispatch['stage']} stays open for its next role; ")
                              + notes[stale_index])
    if form_note:
        notes.append(form_note)
    notes += _post_work(args.task, dispatch["stage"], role, task_root)
    ready = []
    if plan_part:
        ready, more = _plan_next(args.task, task_root, controller, args.dispatch_id)
        notes += more
    # HF8-15 (2) step 5: an author accepted over a window whose critic was sent back (`--needs-author`) names the critic's retry; the
    # line stands before `next:` like every ready command (and `next` itself stays `prepare_stage S5`, see `_critic_retry_lines`).
    ready = ready + _critic_retry_lines(controller, task_root, dispatch)
    print(f"accepted {args.dispatch_id}: {len(outputs)} evidence files, stage "
          f"{'complete' if complete else 'open - next role of this stage'}")
    for note in notes:
        print("note: " + note)
    # The ready command of the plan's next move, one line each, BEFORE `next:` (SC1-8: `next:` stays the last line before the judge's).
    for command in ready:
        print(f"--- next: {command} ---")
    print("next: " + json.dumps(_next(controller), ensure_ascii=False))
    print(_judge_line(args.task))
    return 0


# --- decide: the person's decision about a dispatch, recorded once, by code (t-721 sections 3.1, 3.1.1) ------------

def _decision_path(task_root: Path, dispatch_id: str) -> Path:
    return task_root / "state" / "decisions" / (re.sub(r"[^A-Za-z0-9._-]+", "_", dispatch_id) + ".json")


def _decision_of(task_root: Path, dispatch_id: str) -> dict:
    """The decision record of a dispatch (`state/decisions/<D>.json`), `{}` when there is none. THE reader: `finish`
    and the driver both come through it. No file - every story before this door - is `{}` and `finish` behaves as
    before; an unreadable file is `{}` too, with a note (the error direction is today's behavior: the controller's
    own refusal stays reachable)."""
    path = _decision_path(task_root, dispatch_id)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("it is not a JSON object")
        return data
    except (OSError, ValueError) as exc:
        print(f"note: the decision record of {dispatch_id} could not be read ({exc}); finish goes as without it")
        return {}


def _open_pair(task_root: Path, record: dict) -> tuple:
    """`(unresolved, reason)` a recorded `open_work` decision gives `finish`: the ids, and the first 300 characters
    of the person's words, ` [cut: <words_ref>]` after a cut. Never empty: the controller refuses a silent `false`."""
    ref = str(record.get("words_ref") or "")
    try:
        words = (task_root / ref).read_text(encoding="utf-8-sig").strip() if ref else ""
    except OSError:
        words = ""
    reason = words[:300] + (f" [cut: {ref}]" if len(words) > 300 else "")
    return ([str(i) for i in record.get("unresolved") or []],
            reason or f"the person's decision keeps the stage open; their words are in {ref or 'the decision record'}")


def _decide_args(args) -> tuple:
    """`(kind, ids)` of the one form given: `hand`, `open` or `close`."""
    split = lambda text: [part.strip() for part in str(text or "").split(",") if part.strip()]
    if getattr(args, "hand", None) is not None:
        return "hand", split(args.hand)
    if getattr(args, "open", None) is not None:
        return "open", split(args.open)
    return "close", []


def _in_scope(arg: str, scope: list) -> str:
    """The scope's own spelling of a case the person named (`TC-9` for `speakers/TC-9` when one scope id has it), else ''."""
    if arg in scope:
        return arg
    found = [item for item in scope if (C.split_case_key(item)[1] or item) == arg]
    return found[0] if len(found) == 1 else ""


def _manifest_of(task_root: Path) -> dict:
    try:
        path = Path(C.artifact(task_root, "automation-manifest.json"))
        return C.load_json(path) if path.is_file() else {}
    except Exception:
        return {}


def _row_of(manifest: dict, case: str):
    """The `unresolved[]` row of a case the way `manifest_put` matches it: by case identity, a bare id matching any area."""
    for row in C.manifest_unresolved(manifest):
        key = C.case_key(str(row.get("case") or "").strip(), str(row.get("area") or "").strip())
        if key and C.case_matches(case, key):
            return row
    return None


def _tests_of(manifest: dict, case: str) -> list:
    """The `tests[]` rows that prove the case - the reader the window uses (`C.manifest_test_links`)."""
    bare = C.split_case_key(case)[1] or case
    return [entry for entry in C.manifest_tests(manifest)
            if case in C.manifest_test_links(entry) or bare in C.manifest_test_links(entry)]


def _hand_detail(task_root: Path, case: str, tests: list) -> str:
    """The `detail` of a handed row (s5.md: `<profile id>: <the command and the test file the person runs>`), built from
    the manifest and the config - never from the person's words. With instances: the profile's command
    (`commands.one_test.argv`, placeholders such as `<test-file>` left out - the selectors follow) and the
    `file::function` selectors of the rows; without: the steps of the case file. Never empty."""
    bare = C.split_case_key(case)[1] or case
    profile, command = "", ""
    try:
        import gate_preflight
        config = _config()
        for found, entry in gate_preflight.s5_profiles(config, task_root).items():
            if case in entry.get("cases", []) or bare in entry.get("cases", []):
                profile = found
                spec = next((p for p in config.get("profiles") or [] if isinstance(p, dict)
                             and p.get("profile_id") == found), {})
                import profile_contract  # the ONE reader of `commands` (OH3-27, AR-13); a problem = no command words
                words, _problem = profile_contract.one_test_argv(spec, drop_placeholders=True)
                command = " ".join(words)
                break
    except Exception:
        pass
    lead = f"{profile}: " if profile else ""
    if tests:
        selectors = list(dict.fromkeys(
            str(t.get("selector") or (f"{t['file']}::{t['test']}" if t.get("file") and t.get("test") else "")
                or t.get("test") or C.test_instance_id(t)) for t in tests))
        return lead + (command + " " if command else "") + "; ".join(selectors)
    try:
        index = C.case_index(task_root)
        found = (index.get(case) or index.get(bare) or {}).get("path")
        steps = Path(found).resolve().relative_to(task_root.resolve()).as_posix() if found else ""
    except Exception:
        steps = ""
    return lead + (f"by hand - the steps in {steps}" if steps else f"by hand - the steps of {case}")


def _decide_refusal(kind: str, ids: list, dispatch: dict, did: str, manifest: dict, task: str, task_root: Path,
                    form_halted: bool = False) -> str:
    """"" or the refusal of `decide`, before anything is recorded (FR-1: what is wrong, what is expected). All of the
    arguments are checked against the controller's state first: all or nothing for a list of cases. `form_halted`:
    the dispatch's FORM declares a halt (`_form_halt_word`; the digest is not visible here, so a halt only in the
    digest does not widen anything) - the only case where a role that does not close its stage takes `--close`.
    `task` / `task_root`: the story's own, for the one pause -> recover door (`_pause_recover_door`)."""
    stage, scope = dispatch["stage"], [str(i) for i in dispatch.get("scope") or []]
    if kind == "hand" and stage != "S5":
        return f"story_step: `--hand` hands S5 cases; {did} is a {stage} dispatch. {REPAIR_MARKER}."
    if dispatch.get("status") == "accepted":
        return (f"story_step: {did} is accepted: its window is closed and the manifest it was judged on stands. "
                + ("A case the person now runs themselves goes back through a rework of the S5 role with their "
                   "words - the conductor's `rework_stage`." if kind == "hand" else
                   "Work the person says is left goes back through a rework of the stage's role with their words "
                   "- the conductor's `rework_stage`."))
    if kind == "hand":
        if not ids:
            return "story_step: `--hand` needs the case ids the person runs themselves: --hand TC-1,TC-2."
        wrong = [i for i in ids if not _in_scope(i, scope)]
        if wrong:
            return (f"story_step: {', '.join(wrong)} is not in the scope of {did}. Its cases: {', '.join(scope)}. "
                    f"{REPAIR_MARKER}: name cases from that list.")
        for case in (_in_scope(i, scope) for i in ids):
            row = _row_of(manifest, case)
            reason = str((row or {}).get("reason") or "")
            if reason == "blocked_by_env":
                return (f"story_step: {case} is carried by the manifest as blocked by the stand "
                        f"({', '.join(str(i) for i in row.get('instance_ids') or []) or 'its instances'}); handing it "
                        "over here would erase that record. Its window closes as `blocked_by_env` by itself (`finish` "
                        "derives it); the person's own answer about that gap is given at gate B's stand-gap card.")
            if row is not None and reason != "handed_to_person":
                return (f"story_step: {case} is carried by the manifest as `{reason}` by the role that wrote it; the "
                        "person's word about it goes to that role - the conductor's `rework_stage` with their "
                        "words. Nothing was recorded.")
        return ""
    if stage == "S5":
        return (f"story_step: `--{kind}` is for the other stages; {did} is an S5 dispatch, whose window is either "
                "accepted as unresolved or left open (finish --unresolved / --not-complete).")
    if not C.stage_closes_with(stage, dispatch["role"]):
        if kind == "close" and form_halted:
            # F-1 (b): the one widening - a role whose FORM declares a halt may be accepted as it is (`finish` does
            # not force the stage closed for it). Not `--open`: nothing starts a rework on this host by itself.
            return ""
        pause = _pause_recover_door(task, did, task_root, dispatch.get("agent_id"))
        door = ((f"When its handover form declares a halt, `--close` accepts this work as it is ({stage} follows "
                 "its own rule); otherwise ") if kind == "open" else "The road for a halted role is to ") + pause
        return (f"story_step: `--{kind}` records a decision about the dispatch that closes a stage; {did} is "
                f"{dispatch['role']}, which does not close {stage}. {door}. {REPAIR_MARKER}.")
    wrong = [i for i in ids if i not in scope]
    return (f"story_step: {', '.join(wrong)} is not in the scope of {did}. Its ids: {', '.join(scope)}. "
            f"{REPAIR_MARKER}: name ids from that list, or none for all of it.") if wrong else ""


def _put_unresolved(task: str, task_root: Path, rows: list) -> tuple:
    """`(exit code, output)` of `manifest_put.py` for these `unresolved[]` rows - the only writer of the manifest
    (pattern: `window_record.publish_review_receipt`; the fragment is scratch, never an artifact of the story)."""
    scratch = Path(tempfile.mkdtemp(prefix="qa-decide-"))
    try:
        fragment = scratch / "manifest-fragment.json"
        fragment.write_text(json.dumps({"unresolved": rows}, ensure_ascii=False), encoding="utf-8")
        done = subprocess.run([sys.executable, "-B", str(HERE / "manifest_put.py"), "--task", task,
                               "--fragment", str(fragment)], cwd=str(task_root), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=120)
    finally:
        import shutil
        shutil.rmtree(scratch, ignore_errors=True)
    return done.returncode, (done.stdout + done.stderr).strip()


def decide(args) -> int:
    """`story_step.py decide`: the person's decision about a dispatch, recorded ONCE and by code.

    `--hand <cases>` (S5): the cases the person runs themselves -> `unresolved[]` rows (through `manifest_put`), the
    window rebuilt; `finish` derives the completion pair from them. `--open <ids>` / `--close` (the stage's closing
    role): the stage stays open on that work / closes as it is -> `finish` reads the record. The record is
    `state/decisions/<D>.json`; this door writes nothing else of the story's own state - no `driver-state.json`, no
    agent, no question to the person. Order: (1) the words, (2) the arguments against the controller's state, (3) the
    copy of the words, (4) the manifest rows, (5) the window, (6) the record. A refusal at (1)-(3) records nothing."""
    words = person_words.read(None, args.words_file, "--words")   # --words-file is required: a missing or empty file raises
    kind, ids = _decide_args(args)
    did = args.dispatch_id
    task_root = _task_root(args.task)
    dispatch = Controller(task_root, wait_seconds=_wait(args)).state().get("dispatches", {}).get(did)
    if not dispatch:
        print(f"story_step: no dispatch {did} in this story. {REPAIR_MARKER}: name one of its dispatches.")
        return 2
    manifest = _manifest_of(task_root) if kind == "hand" else {}
    form_halted = bool(_form_halt_word(task_root, FORM_REL.format(dispatch_id=did)))
    refusal = _decide_refusal(kind, ids, dispatch, did, manifest, args.task, task_root, form_halted)
    if refusal:
        print(refusal)
        return 2
    scope = [str(i) for i in dispatch.get("scope") or []]
    cases = [_in_scope(i, scope) for i in ids] if kind == "hand" else (ids or scope)
    key = {"hand": "hand", "open": "open_work", "close": "close"}[kind]
    sha = hashlib.sha256(words.encode("utf-8")).hexdigest()
    record = _decision_of(task_root, did)
    held = record.get(key) or {}
    listing = {"hand": "cases", "open": "unresolved"}.get(kind)
    if held.get("words_sha256") == sha and (not listing or sorted(held.get(listing) or []) == sorted(cases)):
        print(f"note: the same decision is already recorded ({held.get('at')}); nothing was changed")
        return 0
    path = Path(args.words_file).resolve()
    try:
        ref = (path.relative_to(task_root.resolve()).as_posix() if path.is_relative_to(task_root.resolve()) else
               person_words.write_words(task_root, did, "decide" + kind, words).relative_to(task_root).as_posix())
    except OSError as exc:
        print(f"story_step: the person's words could not be saved to {person_words.words_file_path(task_root, did, 'decide' + kind)}"
              f"-<stamp>.txt ({getattr(exc, 'strerror', None) or exc}); nothing was recorded. Make the folder writable "
              f"and run the same command again. {REPAIR_MARKER}.")
        return 2
    notes = []
    if kind == "hand":
        rows, kept = [], 0
        ran = _ran_outcomes(task_root, manifest, cases)
        for case in cases:
            row = _row_of(manifest, case)
            if row is not None:       # `handed_to_person` (the profile road or an earlier call): its command is kept
                kept_row = dict(row, words_ref=ref)
                # A BARE row (`TC-9`) under an area-keyed scope (`speakers/TC-9`) is written back in the SCOPE's spelling
                # (`manifest_put` pairs the two and rewrites `case`), else the controller's stray check reads it as
                # "does not carry". Only the bare spelling of THIS case moves: a row already in the exact spelling, or a
                # compound cell (`TC-1/TC-2`, which answers to its bare ids already), is written unchanged.
                if str(row.get("case") or "").strip() == (C.split_case_key(case)[1] or case):
                    kept_row["case"] = case
                rows.append(kept_row)
                kept += 1
                continue
            tests = _tests_of(manifest, case)
            new = {"case": case, "reason": "handed_to_person", "detail": _hand_detail(task_root, case, tests),
                   "words_ref": ref}
            if tests:
                new["instance_ids"] = [C.test_instance_id(t) for t in tests]
            rows.append(new)
        notes += [f"{case} already ran here ({outcome}); its result stands" for case, outcome in ran.items()]
        code, out = _put_unresolved(args.task, task_root, rows)
        from manifest_put import outcome
        put_kind, move = outcome(code, args.task)       # not `kind`: this function's own `kind` is read below
        if put_kind == "stale":     # exit 4: the rows ARE in the journal, only the manifest's projection failed
            print("story_step: manifest_put.py committed the rows but its projection of the manifest is stale; "
                  f"nothing else was recorded. Run `{move}`, then repeat this command:\n" + out)
            return 2
        if put_kind == "refused":
            print("story_step: manifest_put.py refused the rows; nothing else was recorded:\n" + out)
            return 2
    if kind == "hand" and (task_root / "work" / "windows" / f"{did}.json").is_file():   # --open/--close write only the record
        code, out = _run("window_record.py", "--task", args.task, "--dispatch", did)
        if code > 1:
            notes.append(f"the window record of {did} could not be rebuilt (exit {code}): "
                         + (out.splitlines() or [""])[-1])
    other = "close" if key == "open_work" else "open_work" if key == "close" else ""
    if other and other in record:
        notes.append(f"replaces the recorded {other} decision of {record[other].get('at')}")
        del record[other]
    entry = {"words_ref": ref, "words_sha256": sha, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if listing:
        entry = {listing: cases, **entry}
    record.update({"dispatch": did, "stage": dispatch["stage"], key: entry})
    from event_store import atomic_json
    atomic_json(_decision_path(task_root, did), record)
    for note in notes:
        print("note: " + note)
    if kind == "hand":
        print(f"recorded: {', '.join(cases)} handed to the person (manifest unresolved[] rows: {len(rows) - kept} added, "
              f"{kept} already there - their command kept); the window record of {did} is rebuilt; the finish of {did} "
              "derives handed_to_person from it - answer continue")
    elif kind == "open":
        print(f"recorded: {dispatch['stage']} stays open on {', '.join(cases)}; the rework of that work starts by "
              "itself on the factory's next step, with these words")
    elif not C.stage_closes_with(dispatch["stage"], dispatch["role"]):
        print(f"recorded: the work of {did} is accepted as it is; {dispatch['stage']} follows its own rule (this "
              f"role does not close it); the words are kept in {ref}")
    else:
        print(f"recorded: {dispatch['stage']} closes on this work as it is; the words are kept in {ref}")
    return 0


def _ran_outcomes(task_root: Path, manifest: dict, cases: list) -> dict:
    """case -> the outcome of an instance that already RAN here (edge 12: the window takes the observed result; a red
    result never becomes `handed`). Empty when nothing ran or the runs cannot be read."""
    try:
        import window_record
        runs = window_record._terminal_runs(task_root)
        return {case: C.result_status(runs[C.test_instance_id(t)][0]) for case in cases
                for t in _tests_of(manifest, case) if C.test_instance_id(t) in runs}
    except Exception:
        return {}


def pause(args) -> int:
    task_root = _task_root(args.task)
    controller = Controller(task_root, wait_seconds=_wait(args))
    state = controller.state()
    request = {"id": args.dispatch_id, "status": args.status, "reason": args.reason,
               "checkpoint": {"completed": [], "remaining": [args.reason]},
               "expected_revision": state["revision"],
               # FB-4: a resumed dispatch's later stop is its own event (`dispatch_life_key`: "" until the first resume)
               "idempotency_key": "checkpoint:" + args.dispatch_id + dispatch_life_key(
                   (state.get("dispatches") or {}).get(args.dispatch_id)) + ":" +
               hashlib.sha256(args.reason.encode("utf-8")).hexdigest()[:8]}
    controller.apply("checkpoint", request)
    print(f"checkpointed {args.dispatch_id} as {args.status}")
    print("next: " + json.dumps(_next(controller), ensure_ascii=False))
    return 0


def resume(args) -> int:
    """The same agent goes on with a dispatch stopped for a person (FB-4): the controller's `resume` event, then the stage's
    `running` record. The controller event is THE transition; `stage_done` is its safe-to-repeat projection, so a rerun after a
    full or partial success replays the event and writes the stage again. Nothing here reads the person's words, and a resume
    is not an acceptance: `finish` still judges the work."""
    task_root = _task_root(args.task)
    controller = Controller(task_root, wait_seconds=_wait(args))
    request = controller.build_resume_request(args.dispatch_id, args.agent_id)    # refusals: ValueError / StateConflict -> main
    try:
        controller.apply("resume", request)
    except IdempotencyKeyReused as exc:
        print(f"story_step: refused - {exc}")
        print("story_step: a different agent is a new dispatch: the retry packet "
              f"(`controller.py --task-root {task_root} --operation recover`)")
        return 2
    record = (controller.state().get("dispatches") or {}).get(args.dispatch_id) or {}
    resumes = record.get("resumes") if isinstance(record.get("resumes"), list) else []
    # THIS stop was resumed when the last resume entry retires it - whatever the record is now (it may have returned or been
    # repaired since): a rerun then goes on to the stage's record, never in a loop of "run again" (FR-2)
    if not resumes or (resumes[-1] or {}).get("stop_sequence") != request.get("stop_sequence"):
        print(f"story_step: the stop of {args.dispatch_id} changed since this request (it is {record.get('status')}): "
              "run the command again")
        return 2
    asked = ["--task", args.task, "--stage", record.get("stage") or "", "--status", "running",
             "--role", record.get("role") or "", "--dispatch-id", args.dispatch_id]
    if args.agent_id:
        asked += ["--agent-id", args.agent_id.strip()]
    code, out = _run("stage_done.py", *asked)
    if code and "already accepted by the controller" in out:
        print("note: the stage is already accepted; the dispatch is running again without touching its status")
        code, out = 0, ""
    if code:
        print(out)
        now = (controller.state().get("dispatches") or {}).get(args.dispatch_id, {}).get("status")
        if now != "running":     # the agent returned since: a rerun would meet the same wall - name the road that exists
            print(f"story_step: resumed {args.dispatch_id} in the controller, but it is {now} now and pipeline.json was "
                  f"not updated; `story_step.py finish --task {args.task} --dispatch-id {args.dispatch_id} --digest "
                  '"<digest>"` takes it as it is')
            return code
        print(f"story_step: resumed {args.dispatch_id} in the controller; pipeline.json was not updated - "
              "run this command again")
        return code
    came_from = (resumes[-1] or {}).get("from_status") if resumes else None
    print(f"resumed {args.dispatch_id} ({came_from}) - the same agent continues: SendMessage to {record.get('agent_id')}")
    print("--- after the digest: story_step.py finish --task " + args.task
          + " --dispatch-id " + args.dispatch_id + ' --digest "<digest>" ---')
    return 0


def _pause_door(args) -> None:
    """After a `pause` the controller refused: when the refusal is a host worker the dispatch still has (an active
    receipt, `worker_lifecycle.active_binding` - the controller's own veto, asked again), ONE line with that
    dispatch's `dispatch_liveness.state` and the door that state has (OH3-16, FR-1/FR-2). The controller's refusal
    text is unchanged, and a refusal that is not about a host worker prints nothing more. ALIVE: wait and ask again
    with `where`. UNKNOWN: nothing proves the worker is gone, only the person's `release` closes it. RETURNED, and
    still held: the veto is not the host's silence, so the door is a recorded cancellation. Never raises: a hint
    that cannot be built is not printed."""
    try:
        import dispatch_liveness
        import worker_lifecycle
        task_root = _task_root(args.task)
        project, task, dispatch_id = hooklib.project_root(), task_root.name, args.dispatch_id
        if worker_lifecycle.active_binding(project, dispatch_id, task) is None:
            return
        record = (Controller(task_root).state().get("dispatches") or {}).get(dispatch_id)
        verdict = dispatch_liveness.state(project, task, dict(record) if isinstance(record, dict) else {"id": dispatch_id})
        state = str(verdict.get("state") or "")
        if state == dispatch_liveness.ALIVE:
            door = f"it is at work: wait, and ask again with `story_step.py where --task {args.task}`"
        elif state == dispatch_liveness.UNKNOWN:
            door = ("nothing proves it is gone; if the person says it is, record their words: `"
                    + launch_card.release_door(task_root, dispatch_id) + "`")
        elif state == dispatch_liveness.RETURNED:
            door = (f"the host says it stopped, yet the checkpoint is held; cancel it with a verified cause: "
                    f"`controller.py --task-root {task_root} --operation request_cancel --input <request.json: id, cause, "
                    "evidence_ref>`")
        else:
            door = "the liveness reader says " + state
        print(f"story_step: the host worker of {dispatch_id} is {state}: {door}")
    except Exception:  # noqa: BLE001 - a hint, not a verdict
        return


def _dispatch_record(task_root: Path, dispatch_id: str):
    """The controller's RECORD of a dispatch (`request_binding` lives only there, never on the packet), or None when it cannot be
    read: an unreadable record is an unknown, and the callers read it as "not window 1" (the plan owed, HEAD behaviour)."""
    try:
        record = (Controller(task_root).state().get("dispatches") or {}).get(dispatch_id)
    except Exception:
        return None
    return record if isinstance(record, dict) else None


def _labelling(record) -> bool:
    """Is this dispatch record window 1 of S3 (`purpose: s3_labelling`)? Read through the controller's one reader."""
    return s3_window_of(record) == "labelling"


def _form_owed(stage_id: str, role: str, record=None) -> bool:
    """Does the handoff registry have a contract for this pair, so that `start` writes a handover form
    for it? The same read-only lookup `handoff_init.py` makes (`handoff.contract_of`). A registry that
    cannot be read is an unknown, and an unknown owes the form: the safe side is to wait, never to pass
    (FR-59). `record`: the dispatch record, when the caller holds it - window 1 of S3 owes no form (G1-11)."""
    if _labelling(record):
        return False
    try:
        import handoff
        return bool(_purpose_contract(stage_id, role, record) or handoff.contract_of(stage_id, role))
    except Exception:
        return True


def _request_packet(task_root: Path, record: dict) -> dict:
    """The packet a card is rendered from, given the dispatch RECORD: a record `bind` touched (`agent_bound_seq`) is replaced by its
    committed event, so the resumed line is the one `materialize` renders from the event (F-3). The event cannot be read: the record
    without its `agent_id` and `agent_bound_seq` (the fresh direction, as `controller` does for an unreadable mode)."""
    if record.get("agent_bound_seq") is None:
        return record
    try:
        return _committed_packet(task_root, Controller(task_root), str(record.get("id") or ""))
    except (ValueError, OSError):
        return {k: v for k, v in record.items() if k not in ("agent_id", "agent_bound_seq")}


def _rebuild_card(task: str, task_root: Path, dispatch: dict) -> tuple:
    """`(written, why)`: write the launch card of a dispatch whose `start` never got that far (its output
    lost to the exec cell's yield, or the command killed). The proof that `start` got past `brief_pack` is
    the brief on disk, and past the handover form is the form on disk - owed whenever the registry has a
    contract for the pair (a role launched with no form is refused by `finish` for an untouched one). Not
    there yet: `(False, why)`, `why` naming the form when only it is missing. The prompt is the one `start`
    builds, from the same helpers (`_card_text`, `_prompt_inputs`: no script is run). Writes only the
    derived card."""
    dispatch_id, role = str(dispatch.get("id") or ""), str(dispatch.get("role") or "")
    stage = _stages().get(str(dispatch.get("stage") or ""))
    if not (dispatch_id and role and stage and (task_root / BRIEF_REL.format(dispatch_id=dispatch_id)).is_file()):
        return False, ""
    form = _project_rel(task, FORM_REL, dispatch_id)
    if not (task_root / FORM_REL.format(dispatch_id=dispatch_id)).is_file():
        if _form_owed(stage["id"], role, dispatch):
            if launch_card.outside_start(dispatch):
                # No `start` is writing anything for this packet (FR-10): the door is the one that writes the form.
                return False, ("the handover form is not written yet (the brief is there, the form is not; no "
                               "`start` runs for this packet): run: "
                               + launch_card.materialize_door(task, dispatch_id)
                               + "; if nothing will write it, the person's word frees it: release")
            return False, ("start is still writing the handover form (the brief is there, the form is not); ask "
                           "again, or, if nothing is writing it (start died), the person's word frees it: release")
        form = ""
    launch_card.write(task_root, dispatch_id,
                      _card_text(task, stage, role, dispatch_id, task_root, _project_rel(task, BRIEF_REL, dispatch_id),
                                 form, _request_packet(task_root, dispatch)))
    return True, ""


def _launch_from_where(task: str, task_root: Path, controller: Controller, action: dict) -> tuple:
    """(action, card text) once `launch_card` has had its say about a `wait_existing_job`: `launch`, with
    the card printed under it, when nothing shows the dispatch launched and the card is on disk (rebuilt
    here when only the brief is); `wait_start` while `start` is still writing it; else the action as it
    was. An `alive` verdict keeps the wait, exactly as in `Controller.next_action`. The answer dict is
    `Controller.launch_answer`'s, taken as it comes (one call, one liveness read); this function only
    hands it `_rebuild_card` for the case where the card is the one thing missing."""
    dispatch = (controller.state().get("dispatches") or {}).get(action.get("dispatch_id"))
    if not isinstance(dispatch, dict):
        return action, ""
    answer, _verdict = controller.launch_answer(dispatch, rebuild=lambda d: _rebuild_card(task, task_root, d))
    if not answer:
        return action, ""
    if answer["action"] != "launch":
        return answer, ""
    return answer, launch_card.card_path(task_root, answer["dispatch_id"]).read_text(encoding="utf-8")


# --- the stage card (speed-cost SC1-8 A1, release 0.10.3) ----------------------------------------------------------
# TP1-12586: the conductor read the phase files of S0, S1 and S4 whole (76 KB, about 3.3 million token-reads) when
# one stage's few commands were all a step needed. The phase file opens with a `## Card` section (the input, the
# commands, the config keys the stage reads, the exit); `card` prints that section, the VALUES of the keys it names and an
# index of every other section as a ready `Read <path> offset=<a> limit=<b>`. A stage without a card prints a way back to
# reading the file whole, never silence.
PHASES_DIR = HERE.parent / "skills" / "qa-story" / "phases"
CARD_HEADING = "Card"          # `## Card`: the one place a phase file keeps its card
CARD_MAX_BYTES = 4000          # a size pin is a cap: a card past it is printed whole and said to be a package defect
_CONFIG_LINE = re.compile(r"^config:[ \t]*(.*)$")


def _lines_of(text: str) -> list:
    """The lines of a file as `Read` counts them (split at `\\n` only, CRLF as LF, no phantom line after the last newline)."""
    lines = text.replace("\r\n", "\n").split("\n")
    return lines[:-1] if lines and lines[-1] == "" else lines


def _sections(lines: list) -> list:
    """`[(label, first, last)]`: every line of the file in exactly one range, `[first, last)` 0-based. A range is the `## <label>`
    section that starts at `first`; `label` is None for the lines outside any `## ` section (the title and the intro before the
    first one, text after a `# ` heading). A heading inside a code fence is not a heading; a fence is read as CommonMark and
    `grammar.heading_lines` read it (`grammar._fence`: the same character, at least as long, no info string on the closer)."""
    out, label, first, fence = [], None, 0, None
    for number, line in enumerate(lines):
        shape = grammar._fence(line.rstrip("\r"))
        if fence is None:
            if shape and not (shape[0] == "`" and "`" in shape[2]):
                fence = (shape[0], shape[1])
                continue
        elif shape and shape[0] == fence[0] and shape[1] >= fence[1] and not shape[2].strip(" \t"):
            fence = None
            continue
        if fence is None and (line.startswith("## ") or line.startswith("# ")):
            if number > first:
                out.append((label, first, number))
            label, first = (line[3:].strip() if line.startswith("## ") else None), number
    if len(lines) > first:
        out.append((label, first, len(lines)))
    merged = []
    for entry in out:   # two ranges of "outside any section" that touch are one
        if merged and entry[0] is None and merged[-1][0] is None and merged[-1][2] == entry[1]:
            merged[-1] = (None, merged[-1][1], entry[2])
        else:
            merged.append(entry)
    return merged


def _card_spans(lines: list) -> list:
    """The `(first, last)` line span of every `## Card` section of a phase file, in order."""
    return [(first, last) for label, first, last in _sections(lines) if label == CARD_HEADING]


def _card_section(lines: list) -> str | None:
    """The first `## Card` section of a phase file as written (trailing blank lines dropped), or None. The ONE slice of the card
    text: `_stage_card` prints it and counts its bytes against `CARD_MAX_BYTES`, and the size pin of the cards counts the same."""
    spans = _card_spans(lines)
    return "\n".join(lines[spans[0][0]:spans[0][1]]).rstrip() if spans else None


def _section_index(text: str, skip, path: Path) -> list:
    """One line per range of the file except `skip` (a `(first, last)` span, the card's): `- <heading>: Read <path> offset=<a>
    limit=<b>`, `<a>` the 1-based line `Read` takes. Text outside any `## ` section is `(rest of file)`. Every line that is not
    in `skip` is in exactly one entry, so nothing the card does not say is out of reach."""
    return [f"- {label or '(rest of file)'}: Read {path} offset={first + 1} limit={last - first}"
            for label, first, last in _sections(_lines_of(text)) if (first, last) != skip]


def _stage_card(stage_id: str) -> str:
    """What `card --stage` prints: the stage's card, the values of the config keys its `config:` line names, the index of the
    rest of the phase file. A refusal (ValueError, printed by `main`) names the ids / the reinstall; it never prints an empty card."""
    stages = _stages()
    if stage_id not in stages:
        raise ValueError(f"{stage_id!r} is not a stage id of references/stages.json; the ids are {', '.join(stages)} "
                         f"(exactly as written). {REPAIR_MARKER}: name one of them.")
    path = PHASES_DIR / f"{stage_id.lower()}.md"
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"phases/{path.name} of the plugin is missing or unreadable ({type(exc).__name__}: {exc}): "
                         "reinstall the plugin") from exc
    lines = _lines_of(text)
    if not lines:
        raise ValueError(f"phases/{path.name} of the plugin is empty: reinstall the plugin")
    cards, card_text = _card_spans(lines), _card_section(lines)
    if not cards:
        index = _section_index(text, None, path)
        size = len(text.replace("\r\n", "\n").encode("utf-8"))
        return "\n".join([f"{stage_id} has no card yet: read {path} whole ({size} bytes, {len(lines)} lines); or by section:"]
                         + index) + "\n"
    out, notes = [], []
    for line in card_text.split("\n"):
        out.append(line)
        named = _CONFIG_LINE.match(line)
        if named and named.group(1).strip():
            out += ["  " + value for value in config_view.card_values([k.strip() for k in named.group(1).split(",") if k.strip()])]
    size = len(card_text.encode("utf-8"))
    if size > CARD_MAX_BYTES:
        notes.append(f"note: the {stage_id} card is {size} bytes, over {CARD_MAX_BYTES}: a package defect")
    if len(cards) > 1:
        notes.append(f"note: phases/{path.name} has {len(cards)} `## {CARD_HEADING}` sections; the first one is shown: a package defect")
    index = _section_index(text, cards[0], path)
    return "\n".join(out + [""] + [f"Phase file: {path} ({len(lines)} lines). The rest of it, by section - read one only where "
                                   "the card points:"] + (index or ["- (nothing else in the file)"])
                     + ["Another config key: `config_view.py --keys [PREFIX]` lists them, `config_view.py --get PATH` prints one "
                        "(never read config.json whole)."] + notes) + "\n"


def card(args) -> int:
    """The stage's card (`_stage_card`). Reads; writes nothing and needs no story: S0's card is read before the story has a root."""
    print(_stage_card(args.stage), end="")
    return 0


def where(args) -> int:
    """The next action, the stop marker and the judge's bill. Reads, with ONE write: the derived launch
    card of a dispatch that has a brief but no card (`_rebuild_card`); state and journal are untouched."""
    task_root = _task_root(args.task)
    controller = Controller(task_root)
    action, card = _next(controller, read_only=True), ""
    if action.get("action") == "wait_existing_job":
        try:
            action, card = _launch_from_where(args.task, task_root, controller, action)
        except (OSError, ValueError):   # the card is a convenience: the old answer stands
            card = ""
    print("next: " + json.dumps(action, ensure_ascii=False))
    print(card, end="")
    print(_judge_line(args.task))
    # The pointer that makes the stage card reachable (SC1-8): the LAST line, after the judge's, so `next:` and the launch card stay
    # exactly where every reader finds them.
    if action.get("stage"):
        print(f"stage card: story_step.py card --stage {action['stage']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("start")
    p.add_argument("--task", required=True)
    p.add_argument("--stage", required=True)
    p.add_argument("--role", required=True)
    p.add_argument("--id")
    p.add_argument("--scope", help="comma-separated ids; default is the story scope or the derived stage scope. A manual block "
                                   f"(--execution-kind manual) names 1..{MANUAL_BLOCK_CASES} of them; without it, `start` prints "
                                   "the next block")
    p.add_argument("--purpose")
    p.add_argument("--execution-kind", choices=["automation", "manual"], dest="execution_kind",
                   help="S6 qa-runner: which half of the stage this packet runs; manual: one block of "
                        f"1..{MANUAL_BLOCK_CASES} manual-agent cases from --scope")
    p.add_argument("--parallel-window", action="store_true", dest="parallel_window",
                   help="the driver's scheduler only (t-1937): this S5 window may start beside a running window of other cases; "
                        "the controller still checks stage, role, disjoint scopes and the cap, and refuses as before otherwise")
    p = sub.add_parser("materialize", help="write the brief, the handover form and the launch card of a running "
                                           "dispatch the controller already committed (a rework packet)")
    p.add_argument("--task", required=True)
    p.add_argument("--dispatch-id", required=True, dest="dispatch_id")
    p = sub.add_parser("bind")
    p.add_argument("--task", required=True)
    p.add_argument("--dispatch-id", required=True)
    p.add_argument("--agent-id", required=True, help="the host's id for the agent now running it")
    p = sub.add_parser("finish")
    p.add_argument("--ignore-handoff", action="store_true",
                   help="accept although the handover form is untouched or incomplete - the "
                        "person's word, recorded with waiver.py like any other block")
    p.add_argument("--task", required=True)
    p.add_argument("--dispatch-id", required=True)
    # HF8-15 (2): not `required` any more - `--needs-author` is a finish with NO digest (the critic judged nothing). `finish`
    # itself refuses a call that has neither, with the same sentence-and-form a person reads for any other refusal (FR-1).
    p.add_argument("--digest", default=None)
    p.add_argument("--needs-author", dest="needs_author", default=None,
                   help="S5 critic that cannot judge because its author's work is defective: comma-separated case ids "
                        "of the window for the author to repair; needs --reason, takes no digest; the critic stays open "
                        "for its retry (HF8-15)")
    p.add_argument("--cause", default=None,
                   help="with --needs-author: the repair cause of the author's round (default test_defect)")
    p.add_argument("--output", action="append", help="extra task-relative evidence file")
    p.add_argument("--not-complete", action="store_true", help="accept the work, leave the stage open")
    p.add_argument("--open-windows", dest="open_windows", default=None,
                   help="with --not-complete on an S5 window: comma-separated case ids of the OTHER windows still open "
                        "(the driver's scheduler names them); the controller checks each is a real window of the stage "
                        "and then does not call the bare --not-complete a stage left with no role to close it (t-1937)")
    p.add_argument("--complete", action="store_true",
                   help="close the stage on this role although it is not the last one "
                        "(S8: the scribe closes it, the bug reporter runs after gate B)")
    p.add_argument("--window", help="S5 completion: the window acceptance record (task-relative or "
                                    "absolute); default work/windows/<dispatch-id>.json when present")
    p.add_argument("--unresolved", help="a window the critic could not close, in a word "
                                        "(could_not_judge, fitted_to_code, handed_to_person, ...): "
                                        "goes to the controller unchanged, with --reason")
    p.add_argument("--reason", help='the words for --unresolved: why the window is accepted as unresolved '
                                    '(handed_to_person: the profile and what the person runs)')
    p = sub.add_parser("decide", help="record the person's decision about a dispatch (their words by file)")
    p.add_argument("--task", required=True)
    p.add_argument("--dispatch-id", required=True)
    p.add_argument("--words-file", dest="words_file", required=True,
                   help="the file holding the person's own words, as they were given (UTF-8)")
    form = p.add_mutually_exclusive_group(required=True)
    form.add_argument("--hand", help="S5: comma-separated case ids the person runs themselves")
    form.add_argument("--open", nargs="?", const="", default=None,
                      help="the stage's closing dispatch: the stage stays open on these ids (none = the whole scope)")
    form.add_argument("--close", action="store_true",
                      help="the stage's closing dispatch: the stage closes on this work as it is")
    p = sub.add_parser("pause")
    p.add_argument("--task", required=True)
    p.add_argument("--dispatch-id", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--status", default="blocked", choices=["blocked", "paused", "incomplete"])
    p = sub.add_parser("resume", help="a dispatch stopped for the person (blocked / paused) goes on with the SAME agent")
    p.add_argument("--task", required=True)
    p.add_argument("--dispatch-id", required=True)
    p.add_argument("--agent-id", dest="agent_id", default=None,
                   help="the host's id of the agent that continues; default: the one recorded on the dispatch")
    p = sub.add_parser("where")
    p.add_argument("--task", required=True)
    p = sub.add_parser("card", help="print a stage's card from its phase file, the values of the config keys it names and the "
                                    "index of the rest of the file (no story needed)")
    p.add_argument("--stage", required=True, help="the stage id exactly as references/stages.json writes it (S0..S9)")
    p = sub.add_parser("config-snapshot", help="keep qa-factory/config.json as this FRESH story starts (one JSON line)")
    p.add_argument("--task", required=True)
    p = sub.add_parser("config-restore", help="give config.json back as the story found it, except what a recorded writer wrote (one JSON line)")
    p.add_argument("--task", required=True)
    args = parser.parse_args()
    # The lifecycle wait is chosen here, at the command's entry, and travels on `args`: the
    # library functions below never pick it themselves.
    import event_store
    args.wait_seconds = event_store.LIFECYCLE_WAIT_SECONDS
    try:
        return {"start": start, "materialize": materialize, "bind": bind, "finish": finish, "decide": decide,
                "pause": pause, "resume": resume, "where": where, "card": card,
                "config-snapshot": config_snapshot, "config-restore": config_restore}[args.command](args)
    except (ValueError, KeyError, OSError) as exc:
        print(f"story_step: refused - {exc}")
        if args.command == "pause":
            _pause_door(args)
        return 2
    except Exception as exc:  # StateConflict and guard refusals carry the message the person needs
        print(f"story_step: refused - {type(exc).__name__}: {exc}")
        if args.command == "pause":
            _pause_door(args)
        return 2


if __name__ == "__main__":
    sys.exit(main())
