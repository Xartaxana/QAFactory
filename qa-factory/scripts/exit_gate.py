"""Handoff exit gate (SubagentStop): an agent cannot finish while its artifacts are broken.

The first failure forces one return. The re-entry after it is checked once more and then
released whatever the result — a role that repaired its artifacts hands off clean, and one
that did not is recorded incomplete; the gate never blocks twice, so there is no loop. An
unchanged repeated event is released as incomplete without re-running detectors. The
durable fuse is scoped by task, dispatch, completion attempt, hook and input fingerprint;
releasing a turn never means accepting the handoff.

Three things are not failures. A block a person passed with their word (`stage_overrides[]`,
written by `waiver.py --stage`) is journaled and dropped. A scout that stops with every
source assessed and no person's review yet is handing the story to that person, not
finishing S1 — it is released as `awaiting_human`, and S1 still cannot close. And a role
whose last word is a `halt` or `impossible` digest is doing exactly what the gate's own
message tells it to do: `required_outputs` are not demanded of it (0.7.7 review, finding
A-F4 — the scout's three charter halts all fire before step 9 writes the manifest, so the
gate blocked the handoff it was asking for). Broken artifacts it DID write are still errors.
"""
import contextlib
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hooklib import artifact_root, is_story_folder, project_root, state_dir, read_event, role_name, subagent_type, read_json
import contract as C
import detector_verdict as DV
import role_digest as RD
from role_cli import PERSON_MARKER, REPAIR_MARKER
import stage_guard as SG
import validate_artifacts as va
import bug_records as BR
from hooklib import sorted_paths

# What `_identity` writes as the scope's `dispatch` when the event names none of dispatch_id / agent_id / session_id.
# The ONE name: `subagent_journal._dispatch_id` and `dispatch_liveness.role_stops` read it from here.
UNKNOWN_DISPATCH = "unknown-dispatch"

# Phase acceptance detectors: role -> the artifact it hands off. The GATE re-runs them,
# not the orchestrator. Two reasons. (1) The author still has the context to fix it in
# place - the orchestrator would need a reject, a re-dispatch and a fresh context for the
# same thing. (2) Measured 09.09: the orchestrator spent 11 turns launching acceptance
# detectors at ~$0.05 a turn, and that is pure mechanics, not a decision. The decision
# itself - accepted/rejected - stays with the orchestrator: the gate answers "the evidence
# contract is satisfied", not "the work is accepted".
#
# The role -> witness-filename map is NOT a Python dict: it is the top-level "witness"
# table of references/stages.json (single source, shared with stage_guard.py and
# inject_context.py). A role with no entry there is simply not gated here.
def witness_gates() -> dict:
    return (SG.stage_model().get("witness") or {})


# How long a detector (or `check_witness`) may run before the gate calls its answer unknown: ONE constant for the two
# places that used to carry the literal 120 (RH1-5, E9). The border: a run that finishes in time is read by the
# contract; one that does not is `unreadable` ("timed out after N s"), never a pass and never a finding of the role.
DETECTOR_TIMEOUT_S = 120


def unreadable_record(script: str, reason, owner_file: str = "") -> DV.Record:
    """The record of a check that could not run (RH1-5, FR-59): the third state of the gate, never a pass. The text
    contains `<script>: unreadable - ` - the name of the check is always in it, because the ONLY word that passes
    it is the named one (`word_class` `named_only`, `waiver.py --block "<script>: unreadable"`). It is the factory's
    defect, not the role's work: no marker sends the role to repair it, and the conductor takes it (P1, P22).

    `owner_file` (N1): a check that runs at EVERY stage's stop but is one stage's business (the S2 register checks)
    starts its text with the file that stage owns, so `scoped_errors.mine()` hands it to that stage and to no other
    (invariant: an S2 crash of the check blocks S2; an S5 stop is not blocked by it). `script` stays the check's name:
    the person's word is `<script>: unreadable`, not the file's."""
    prefix = f"{owner_file}: " if owner_file else ""
    return DV.Record(f"{prefix}{script}: unreadable - {reason} - the factory's own defect, not the role's work; the "
                     "conductor takes it", script=script, kind="unreadable", words="gate")


def _run_failure(exc: BaseException) -> str:
    """Why a check subprocess gave no answer, in words: a timeout, or it did not start (E9, E10)."""
    if isinstance(exc, subprocess.TimeoutExpired):
        return f"timed out after {DETECTOR_TIMEOUT_S} s"
    return f"did not start ({type(exc).__name__})"


def advice_detectors(agent: str = "", stage: str = "") -> set:
    """The scripts a stage declares as ADVISERS (`advice` in stages.json, F-7): their `unreadable` is a signal to the
    person, never a block - an adviser (`sizing.py`) informs the stage, and its crash must not stop a handoff.

    SCOPE (X2-2, E-A15): with `stage` only that stage's `advice` is read, with `agent` only the scripts that stand in that
    stage's `detectors[agent]` (an adviser of a role is a script the role's own stop runs). The gate always passes both;
    the empty call (every stage, every role) is the legacy reading. A stage with no `advice` key gives nothing: the
    absence of the key is never "everything is advice" (E-X2-2a, the error goes toward a block). A script declared an
    adviser on S2 is NOT one on S3: there it is read from S3's own lists and stays a blocking detector."""
    out: set = set()
    for st in SG.stage_model().get("stages") or []:
        if stage and st.get("id") != stage:
            continue
        declared = {str(s) for s in st.get("advice") or []}
        if agent:
            declared &= {str(s) for s in (st.get("detectors") or {}).get(agent) or []}
        out |= declared
    return out
# An artifact older than this almost certainly does not belong to the current dispatch
# (a resumed session, a neighbouring task) - then the gate stays silent and the whole
# acceptance is the orchestrator's. Fail-open: doubt is resolved in favour of letting the
# handoff through; the gate backs the acceptance up here, it does not replace it.
WITNESS_FRESH_HOURS = 4


def witness_errors(agent: str, task: str = "") -> list:
    """Re-run check_witness over the role's artifact. An empty list means nothing blocks."""
    name = witness_gates().get(agent)
    if not name or name.endswith("/"):
        return []  # a directory witness (e.g. test-cases/) has no single-file schema to re-check
    if name.startswith("project:"):
        name = name[len("project:"):]
    root = artifact_root()
    if not root.exists():
        return []
    if task and task != "unknown-task":
        candidates = [root / task / name]
        # Read compatibility for artifacts that predate the work/ split.
        candidates.append(root / task / (name[len("work/"):] if name.startswith("work/") else "work/" + name))
        found = [p for p in candidates if p.is_file()]
    else:
        return []  # ambiguous ownership must not select the newest story
    if not found:
        return []  # the role handed off no artifact - that is the orchestrator's call, not the gate's
    art = max(found, key=lambda p: p.stat().st_mtime)
    age_h = (time.time() - art.stat().st_mtime) / 3600
    if age_h > WITNESS_FRESH_HOURS:
        return []
    try:
        r = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve().parent / "check_witness.py"), str(art)],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=DETECTOR_TIMEOUT_S, cwd=str(project_root()))
    except Exception as exc:
        # RH1-5 (D8): a check that did not start or timed out is NOT a pass - the third state, the conductor's
        return [unreadable_record("check_witness.py", _run_failure(exc))]
    verdict = DV.parse(r.returncode, r.stdout, r.stderr)     # at ANY code: a producer's own `UNREADABLE:` at 0 counts (E8)
    if verdict["unreadable"]:
        return [unreadable_record("check_witness.py", verdict["unreadable"])]
    if r.returncode != 0:
        # check_witness judges no words of its own: its records are the gate's to judge (`words="gate"`). The
        # sentence about the contract stands once, in the header of the block `main` prints.
        tail = (r.stderr or r.stdout or "").strip().splitlines()[-4:]
        summary = DV.Record(f"{name}: the acceptance detector check_witness returned exit {r.returncode} - "
                            "the evidence contract is not satisfied, fix it yourself: you still have the "
                            "context, the orchestrator no longer does. " + " | ".join(tail),
                            script=name, kind="summary")
        return detector_records(name, r.returncode, verdict, words="gate") + [summary]
    print(f"witness OK (re-run by the exit gate): {art.name} - the orchestrator needs no second run")
    return []

MAX_BLOCKS = 1


def _findings_path(agent: str, task: str) -> Path | None:
    """Where the whole list of a cut message is written: `<task root>/state/findings/exit-gate-<role>.txt`. A hook
    that does not know the story (`unknown-task`), or names one that has no folder, has no task root: it saves nothing
    and says so (FR-41). A hook never makes a story's folder (CX1-18, E-8): the folder is S0's."""
    if not task or task == "unknown-task" or not is_story_folder(artifact_root(), task):
        return None
    return artifact_root() / task / "state" / "findings" / f"exit-gate-{agent}.txt"


def render_saved(errors: list, path: Path | None, task: str, source: str) -> tuple[str, str]:
    """`(text, where)`: the list as `DV.render` shows it, and where the whole list is, as a path under the task
    root (a stored path is a hint, not an address: it stays right when the root moves), `""` when `render` wrote
    no file. A file left by an earlier block is removed first, so a file that exists afterwards is this call's.
    PUBLIC (GW1-8 fix round): `story_step._gate_refusal` calls it instead of a copy of the unlink-then-render."""
    try:
        if path is not None:
            path.unlink(missing_ok=True)
    except OSError:
        pass
    text = DV.render(errors, full_path=path, source=source)
    where = path.relative_to(artifact_root() / task).as_posix() if path is not None and path.is_file() else ""
    return text, where


_render_saved = render_saved      # the old private name, kept for one release (no caller outside the package)


def _state_path() -> Path:
    return state_dir() / "state" / ".exit_gate_blocks.json"


def _named_ticket(event: dict) -> tuple:
    """`(story, facts)`: the story the event or the environment NAMES, else "" - never a guess (FR-59) - and the
    `SG.resolve_ticket` facts it decided on, so the audit's header (`_unnamed_header`) prints what THIS decision read.

    `SG.resolve_ticket` also guesses (its step 4: the single running or the single open story), and a guess is
    the wrong error direction here: it can answer a story the stop does not belong to, and that story's audit
    then skips the stopping role's own bug as someone else's. Its answer is kept only when `facts` says where it
    came from: an explicit id (the event's, or the one `host_dispatch.enrich` copied from the child's binding),
    exactly ONE existing story named in the dispatch text (two named stories name none, even when the
    `Ticket:` line settles which of them: the safe direction), the one story the desktop task name's slug
    names, or `$QA_FACTORY_TASK`. A new step of `resolve_ticket` is not on this list until it adds a key of
    its own to `facts` and the list says so."""
    ticket, facts = SG.resolve_ticket(event)
    if not ticket:
        return "", facts
    root = artifact_root()
    in_text = [name for name in facts.get("named") or [] if name not in (".", "..")
               and not any(c in name for c in "/\\:") and (root / name / "pipeline.json").is_file()]
    named = (ticket == facts.get("explicit") or in_text == [ticket]
             or facts.get("slug_matches") == [ticket] or facts.get("env_task") == ticket)
    return (ticket if named else ""), facts


def _identity(event: dict, agent: str) -> tuple[str, dict]:
    """Return a stable completion-check key and its inspectable scope.

    Hosts do not expose identical field names, so explicit task/dispatch/attempt fields
    are preferred and conservative fallbacks are retained. Volatile host fields and the
    re-entry flag are excluded from the fingerprint.

    The third source, `_named_ticket`, exists because a Codex Desktop SubagentStop arrives with no task field
    and an agent type ("default") that maps to no stage: the gate ran as "unknown-task", audited every bug of
    the project's shared folder, and another story's bugs blocked this story's exit (TP2-2406, BUG-1..3
    of 2530 and 2534). It keeps a story only when the event or the environment NAMES it. Any other answer (two
    open stories, one running; one open story that nothing named) leaves "unknown-task" and the audit full, and
    `bug_audit_errors` says so in its first line, with the facts this decision read (`scope["identity_facts"]`,
    not part of the key). It stands AFTER the event's own field and the stage branch:
    an explicit task wins as written, and a role with a stage keeps the stage's ticket (that guess is not this
    node's). Both consumers of this key read the same task: the gate (`main`) and the journal line of
    `subagent_journal.record_return`.
    """
    # An exploration role's stop (qa-scout E1/E2, qa-requirements-tester E3) belongs to its exploration, never to the story that
    # happens to exist (XT1-2): ONE predicate, asked first; a stop it cannot prove (no `explore:` id, no label in the child's own
    # transcript) goes the old way below. `main` ends such a stop; `subagent_journal` journals it under `task: explore:<slug>`.
    try:
        slug, problem = SG.exploration_named(event)
    except Exception:
        slug, problem = "", ""        # an exception is not an exploration
    rejected = ""
    if slug:
        import exploration
        task = exploration.task_id(slug)
    else:
        task = str(event.get("task_id") or event.get("task") or event.get("ticket") or "")
        try:
            import exploration
            if exploration.env_slug(task):
                # An `explore:` id the predicate does not accept is NEVER a story (t-734 m-1, AR-28): no stage lookup, no story
                # guess; `main` ends the stop and says what could not be established.
                rejected = problem or "unreadable"
        except Exception:
            rejected = ""
    if not task:
        try:
            stages = SG.stages_of_role(SG.stage_model(), agent)
            if len(stages) > 1:
                # A role of several stages: the story is the ONE story where one of its stages runs, else not established
                # (falls to `_named_ticket` below); `_ticket_for_stage`'s newest-file fallback would be a guess (X2-2b).
                found: list = []
                _running_stage_among([st.get("id") for st in stages], found)
                task = found[0] if len(set(found)) == 1 else ""
            else:
                task = _ticket_for_stage(stages[0]["id"]) if stages else ""
        except Exception:
            task = ""
    facts = None
    if not task and not rejected:
        try:
            task, facts = _named_ticket(event)
        except Exception:
            task, facts = "", None   # an exception is not a story
    task = task or "unknown-task"
    dispatch = str(event.get("dispatch_id") or event.get("agent_id") or event.get("session_id") or UNKNOWN_DISPATCH)
    attempt = str(event.get("completion_attempt") or event.get("attempt_id") or "default")
    hook = str(event.get("hook_id") or event.get("hook_event_name") or "SubagentStop")
    supplied = event.get("input_fingerprint")
    if supplied:
        fingerprint = str(supplied)
    else:
        stable = {k: v for k, v in event.items() if k not in {
            "stop_hook_active", "timestamp", "ts", "transcript_path", "cwd",
        }}
        # Compatibility fallback for hosts that do not yet send input_fingerprint. File
        # metadata makes an actual repair a new check while repeated identical events
        # remain fused. Explicit task IDs keep parallel stories isolated.
        art_root = artifact_root()
        scan_root = art_root / task if task != "unknown-task" else art_root
        if slug:
            scan_root = exploration.root(slug, project_root(event))
        file_state = []
        try:
            file_state = [(str(p.relative_to(scan_root)), p.stat().st_size, p.stat().st_mtime_ns)
                          for p in sorted_paths(scan_root.rglob("*")) if p.is_file()
                          # the whole list this gate saves itself is not the role's work: writing it must not
                          # make the next, unchanged event look like a repair (the fuse above reads this state)
                          and p.relative_to(scan_root).parts[:2] != ("state", "findings")]
        except Exception:
            pass
        stable["artifact_file_state"] = file_state
        fingerprint = hashlib.sha256(
            json.dumps(stable, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
        ).hexdigest()[:24]
    scope = {"task": task, "dispatch": dispatch, "attempt": attempt, "hook": hook,
             "agent": agent, "input_fingerprint": fingerprint}
    if slug:
        scope["exploration"] = slug      # not part of the key; `main` ends an exploration stop on it
    if rejected:
        scope["exploration_rejected"] = rejected
    if task == "unknown-task" and facts is not None:
        # what the decision read, for the header of the audit nobody scoped (not part of the key below)
        try:
            scope["identity_facts"] = SG.identity_facts(facts)
        except Exception:
            pass   # the header then says no facts reached it
    raw ="|".join(scope[k] for k in ("task", "dispatch", "attempt", "hook", "agent", "input_fingerprint"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest(), scope


LOCK_STEP_S = 0.01
LOCK_WAIT_STEPS = 1000        # TR3-6 (spec t-1937 3.3): 10 s; it was 100 steps (1 s) when one hook at a time wrote the state
LOCK_NOTE_AFTER = 100         # a wait longer than the old 1 s is printed


def _mutate_state(update) -> dict:
    """Serialize state updates across concurrent story hooks and replace atomically.

    Parallel S5 sessions have a hook each, so the lock waits 10 s, and a wait past the old 1 s is printed. INVARIANT: a lock that stays
    busy RAISES (the hook fails and names the lock); a busy lock is never read as "gate passed".

    The lock is an OS byte lock on the file (event_store.take_file_lock, TR4-2 part D): a killed hook's leftover file is
    free at once and the file is never deleted."""
    import event_store as ES
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(path.suffix + ".lock")
    wait_s = LOCK_WAIT_STEPS * LOCK_STEP_S
    try:
        held = ES.take_file_lock(lock, wait_s, purpose="exit gate state", record_holder=True, poll_s=LOCK_STEP_S)
    except ES.LockBusy as exc:
        raise RuntimeError(f"exit gate state lock remained busy for {wait_s:.0f} s: {lock}; {exc.holder_clause}") from exc
    except ES.LockBroken as exc:
        raise RuntimeError(str(exc)) from exc
    if held.waited_s >= LOCK_NOTE_AFTER * LOCK_STEP_S:
        print(f"note: the exit gate state lock was busy for {held.waited_s:.0f} s (another session's hook); this one went on",
              file=sys.stderr)
    try:
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except Exception:
            data = {}
        data = data if isinstance(data, dict) else {}
        update(data)
        tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
        return data
    finally:
        held.release()


def _record(scope_key: str, scope: dict, status: str, errors: list[str] | None = None, *,
            total: int | None = None, errors_file: str = "") -> dict:
    """The fuse receipt. `errors` is kept whole up to the byte ceiling of the renderer (not a count of ten),
    with `errors_total` and, when the list was cut, `errors_file`: where `render` put all of it, a path under the
    task root and only of a file that exists (`_render_saved`); with no such file, `errors_file_note` says so."""
    rec = {**scope, "status": status, "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if errors:
        shown, cut = DV.fit(errors)
        rec["errors"] = [str(e) for e in shown]
        rec["errors_total"] = len(errors) if total is None else total
        if cut or rec["errors_total"] > len(rec["errors"]):
            if errors_file:
                rec["errors_file"] = errors_file
            else:
                rec["errors_file_note"] = "the whole list was not saved"
        rec["error_fingerprint"] = hashlib.sha256("\n".join(errors).encode("utf-8")).hexdigest()
    def update(data: dict) -> None:
        previous = data.get(scope_key) if isinstance(data.get(scope_key), dict) else {}
        rec["blocks"] = int(previous.get("blocks", 0))
        if status == "blocked":
            rec["blocks"] += 1
        data[scope_key] = rec
    return _mutate_state(update).get(scope_key, rec)


def _existing(scope_key: str) -> dict:
    path = _state_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        value = data.get(scope_key, {})
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}

# P6 "next: lines": role -> detector scripts, printed ONLY on a clean pass (errors empty,
# not break-glass). Read from each stage's own "detectors" map in stages.json — not a
# Python dict — so a role rename in the plugin's own data never needs a matching Python edit.
# FB-27 "witness fabrication" (2026-09-02 incident in a neighbouring instance: the scribe drew
# a detector "exit 0" while the real run REJECTed twice and wrote a non-existent fact into the
# map): agent claims about detector results are NOT trusted - the gate RE-RUNS the detectors
# itself, the real exit code decides the handoff, quotes do not participate. A Sonnet
# orchestrator will not catch a forgery by reading - code does.
def detector_gates(stage: str = "") -> dict:
    """role -> detector scripts. With `stage`: that stage's `detectors` alone (the gate judges a stop by the stage it
    holds, E-X2-2d: the detectors of S4 do not judge the work of S2); without it, the merge over every stage (the
    reader that asks "does this role have a gate at all", `story_step`)."""
    out: dict = {}
    for st in SG.stage_model().get("stages") or []:
        if stage and st.get("id") != stage:
            continue
        for role, scripts in (st.get("detectors") or {}).items():
            out.setdefault(role, []).extend(scripts)
    return out


def advice_records(script: str, verdict: dict) -> list:
    """The ADVICE records of one detector run, from `detector_verdict.parse`: one per advice line, `kind="advice"`, the text
    the line printed and the script as its attribute (the file `write_advice` writes keeps both). One shape for every
    producer (AR-18); an advice record is never an error of the gate - `detector_errors` and `run_advisers` do not
    return it, they hand it to `write_advice`."""
    return [DV.Record(line, script=script, words="gate", kind=DV.ADVICE_KIND) for line in verdict.get("advice") or []]


def detector_records(script: str, code: int, verdict: dict, *, words: str) -> list:
    """The gate's records for one refused detector run, from `detector_verdict.parse`: one per finding (with the
    producer's marker verbatim, the way the driver routes on it), one per defect of the detector itself (NO
    marker: a defect of the factory must not send the role to repair it), and one for output that is not in the
    contract's form, shown whole. Each record carries who judged its words (`words`) and its kind. A check that did
    not run (`verdict["unreadable"]`, RH1-5) is ONE `unreadable` record and nothing else: no finding is read from it."""
    if verdict.get("unreadable"):
        return [unreadable_record(script, verdict["unreadable"])]
    marker = {"repair": REPAIR_MARKER, "person": PERSON_MARKER}.get(verdict["marker"], "")
    out = [DV.Record(f"{script}: {line}" + (f" ({marker})" if marker else ""), script=script, words=words,
                     kind="finding", refused=refused)
           for line, refused in zip(verdict["findings"], verdict["refused"])]
    for defect in verdict["defects"]:
        why = ("the gate cannot say what is wrong. This is the factory's own defect, not your work: name it in "
               "your digest under blocked; the orchestrator takes it from there."
               if defect.endswith(DV.PRINTED_NOTHING) else
               "the detector's own defect, not your work: name it in your digest under blocked; the "
               "orchestrator takes it from there")
        out.append(DV.Record(f"{script}: {defect} - {why}", script=script, words="gate", kind="defect"))
    if verdict["unmigrated"]:
        out.append(DV.Record(f"{script}: " + DV.unmigrated_text(verdict["unmigrated"], code),
                             script=script, words=words, kind="unmigrated", refused=verdict["unmigrated_refused"]))
    return out


def _advice_signal(script: str, reason, task: str = "") -> None:
    """An ADVISER that could not run: a signal to the person (`hook_signal`, read by the run report), never a block.
    `task` (N6): the story the caller knows, so the report places the signal by it and not by time."""
    import hooklib
    # the hook event is not at hand in this helper; an empty one is legal for `person_signal` (no session named)
    hooklib.person_signal({}, "gate_unreadable", f"{script}: unreadable (advice) - {reason}",
                          task=task if task and task != "unknown-task" else None)


_HELD_STAGE = [""]      # the stage the caller of `all_errors` holds (t-440), set only by `holding_stage`


def held_stage() -> str:
    """The stage a caller declared with `holding_stage`, or "" (none held)."""
    return _HELD_STAGE[0]


@contextlib.contextmanager
def holding_stage(stage):
    """Within the block, the detectors the gate starts are told the stage the caller holds (`QA_FACTORY_DETECTOR_STAGE`, beside
    the story): `story_step finish` holds `dispatch["stage"]`, and a stale dispatch of another stage in the controller's state must
    not decide which stage's check judges the finisher (FR-59, AR-28). It is a context, not a parameter of `all_errors`, because
    `all_errors` is also the hook's and the driver's function and its signature is theirs. Restored on exit, whatever happens;
    a blank or non-string stage holds nothing."""
    previous = _HELD_STAGE[0]
    _HELD_STAGE[0] = stage.strip() if isinstance(stage, str) else ""
    try:
        yield
    finally:
        _HELD_STAGE[0] = previous


_HELD_DISPATCH = [""]      # the dispatch id the caller of `all_errors` holds (TR3-13), set only by `holding_dispatch`


def held_dispatch() -> str:
    """The dispatch id a caller declared with `holding_dispatch`, or "" (none held)."""
    return _HELD_DISPATCH[0]


@contextlib.contextmanager
def holding_dispatch(dispatch_id):
    """Within the block, the gate knows WHICH dispatch is handing off, in-process (`_live_dispatch`) and in the detectors it starts
    (`QA_FACTORY_DETECTOR_DISPATCH`, beside the story): with two windows running, the count rule cannot name the finisher
    (spec t-1937 B1; `dispatch_identity` is the reader). The twin of `holding_stage`: a context, not a parameter of `all_errors`
    (the hook's and the driver's function); a process global, safe because the driver's gate calls are under its `_book` and
    `story_step finish` is its own process. Restored on exit, whatever happens; a blank or non-string id holds nothing."""
    previous = _HELD_DISPATCH[0]
    _HELD_DISPATCH[0] = dispatch_id.strip() if isinstance(dispatch_id, str) else ""
    try:
        yield
    finally:
        _HELD_DISPATCH[0] = previous


def _detector_env(task: str) -> dict:
    """The environment of a detector the gate starts (GW1-10): a copy of ours that NAMES the story the gate is judging, and, when
    a caller holds one (`holding_stage`), the stage - only beside a named story; any stale stage word of the parent is removed.

    `task` names a story -> `QA_FACTORY_DETECTOR_STORY` = its folder, through the ONE rule "ticket key -> story folder"
    (`hooklib.story_root`, SIBLING_MAP axis 8; the project is passed, so a missing one raises and never exits the gate).
    A key that is no story (a shape the rule refuses, a folder that is not there) raises `StoryRootError` and NO detector
    is started: the caller makes the third state of it, with the RAW task in the reason. `""` (a bare call) and
    `"unknown-task"` (a hook with no story) name nothing: the variable is REMOVED from the copy, so a stale word of the
    parent never redirects a later gate, and the detector guesses as before."""
    import hooklib
    import planning_contract
    env = dict(os.environ)
    env.pop(planning_contract.DETECTOR_STORY_ENV, None)
    env.pop(planning_contract.DETECTOR_STAGE_ENV, None)
    env.pop(planning_contract.DETECTOR_DISPATCH_ENV, None)
    if not task or task == "unknown-task":
        return env
    env[planning_contract.DETECTOR_STORY_ENV] = str(hooklib.story_root(task, "exit_gate", project=project_root()))
    if held_stage():
        env[planning_contract.DETECTOR_STAGE_ENV] = held_stage()
    if held_dispatch():
        env[planning_contract.DETECTOR_DISPATCH_ENV] = held_dispatch()      # the finisher, named to the detector (TR3-13)
    return env


def _run_detector(script: str, task: str) -> tuple:
    """ONE detector run, read by the contract (GW1-10, F-12a): `(records, not_run)` for the story `task` names. The
    subprocess-and-parse loop of `detector_errors` and `run_advisers` - no second copy. `not_run` is the reason the check
    did not run ("" when it did): a timeout, a start that failed, a story the rule refuses, an output outside the contract
    (RH1-5) - and then `records` is `[]`. The caller makes of it what its position says: a blocking detector's third state
    (`unreadable_record`), or an adviser's signal to the person (`_advice_signal`).

    `records` of a run: the ADVICE records (`kind="advice"`, at exit 0 and 1 alike, X2-2), then, at a non-zero exit, the
    refusal records of the contract and the summary. An ADVICE block that breaks its shape at exit 0 is a check that did not
    read properly: `not_run` (never silence). At a non-zero exit the same break is a `defect` record of the refusal."""
    import hooklib
    try:
        r = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve().parent / script)],
                           capture_output=True, text=True, encoding="utf-8", env=_detector_env(task),
                           errors="replace", timeout=DETECTOR_TIMEOUT_S, cwd=str(project_root()))
    except Exception as e:
        # D9 (RH1-5): a detector that did not start or timed out is the third state, not a finding of the role. A story
        # the task names but the rule refuses (GW1-10) is the same third state: no child was started, the reason says why
        return [], str(e) if isinstance(e, hooklib.StoryRootError) else _run_failure(e)
    verdict = DV.parse(r.returncode, r.stdout, r.stderr)      # at ANY code (E8): a clean exit with the marker is refused
    if verdict["unreadable"]:
        return [], verdict["unreadable"]
    if r.returncode == 0 and verdict["defects"]:
        return [], "its ADVICE block breaks the contract: " + "; ".join(verdict["defects"])
    errs = advice_records(script, verdict)
    if r.returncode != 0:
        errs += detector_records(script, r.returncode, verdict, words=verdict["words"])
        # The summary is the record this gate wrote before C2-1, kept word for word for ONE release:
        # a word a person recorded against it still passes the plain records of this detector
        # (`judge_words`, rule 4). It blocks nothing and is shown to nobody.
        tail = (r.stdout or r.stderr or "").strip().splitlines()[-3:]
        errs.append(DV.Record(f"{script}: REAL exit {r.returncode} on the gate re-run "
                              f"(FB-27: quoted detector output is not accepted): " + " | ".join(tail),
                              script=script, kind="summary"))
    return errs, ""


# The ADVICE the gate collected on the way to a verdict, per `(agent, task, source)`: `detector_errors` and `digest_errors` return
# only what blocks, so what is advice waits here for `run_advisers`, which runs only when nothing blocks and is the one caller of
# `write_advice` (AR-14: a refused stop writes no file). Every producer REPLACES its own entry on each call, so a refused stop
# leaves nothing that a later stop of the same story could file.
_STASH: dict = {}


def _stash_advice(agent: str, task: str, source: str, records: list) -> None:
    _STASH[(agent, task, source)] = list(records)


def _stage_detectors(agent: str, task: str = "") -> tuple:
    """`(stage, scripts, advisers)`: the stage the stop belongs to (`_stage_id`), the detectors that stage declares for the
    role, and the advisers among them (`advice_detectors(agent, stage)`). A stage that is not established gives nothing to
    run (E-X2-2f, AR-28): the detectors of one stage never judge the work of another."""
    stage = _stage_id(agent, task)
    if not stage:
        if len(SG.stages_of_role(SG.stage_model(), agent)) > 1:
            return "", [], set()
        # a role of no stage or of one: there is nothing to confuse, the merge over every stage is its own list (a role that is
        # no stage's has no gate in production; the legacy reading keeps its stand-ins in tests meaning what they meant)
        return "", list(detector_gates().get(agent) or []), advice_detectors()
    return stage, list(detector_gates(stage).get(agent) or []), advice_detectors(agent, stage)


def detector_errors(agent: str, task: str = "") -> list:
    """The records of the role's BLOCKING detectors on the stage it stops in, run for the story `task` names (GW1-10). The
    ADVISERS of the stage (`advice_detectors`) are not run here: `run_advisers` runs them after the verdict. A record with
    `kind="advice"` blocks nothing: it is kept for the advice file, not returned (E-A15)."""
    errs, advice = [], []
    stage, scripts, advisers = _stage_detectors(agent, task)
    for script in scripts:
        if script in advisers:
            continue
        records, not_run = _run_detector(script, task)
        if not_run:
            errs.append(unreadable_record(script, not_run))
        for record in records:
            (advice if record.kind == DV.ADVICE_KIND else errs).append(record)
    _stash_advice(agent, task, "detector", advice)
    return errs


def advice_rel(stage: str, dispatch="") -> str:
    """The task-relative advice file of `stage` (the ONE spelling, AR-13: `write_advice` writes it, `brief_pack.advice_of` reads it).
    S5 with a dispatch id (the finisher the gate identified): `work/advice-S5-<dispatch>.json`, one file per dispatch so two windows
    never share one (TR3-15). No identity, or any other stage: `work/advice-<stage>.json` (the skill road, serial; S2-S4 have one
    dispatch at a time)."""
    ident = str(dispatch or "").strip()
    return f"work/advice-{stage}-{ident}.json" if stage == "S5" and ident else f"work/advice-{stage}.json"


def write_advice(task_root, stage: str, role: str, records: list, unread: list, dispatch="") -> str:
    """The ONE writer of `<task_root>/<advice_rel(stage, dispatch)>` (AR-14), the file the stage critic reads (X2-2, AR-22):
    `{"stage", "role", "written_at", "records": [{"script", "text"}], "unread": [{"script", "reason"}]}` (+ `"dispatch"` when the
    file is one dispatch's). The file is replaced whole, atomically, at each accepted stop of the role, so it reflects the last stop
    the code accepted. `records` are ADVICE records
    (`kind="advice"`); `unread` the advisers that did not run. Returns "" on success, else why nothing was written (no story
    folder - a hook never makes one -, a stage id that is no plain name, a write that failed). Never raises."""
    name = str(stage or "")
    if not re.fullmatch(r"S\d", name) or task_root is None or not Path(task_root).is_dir():
        return "no story folder or no stage"
    try:
        from event_store import atomic_text
        path = Path(task_root) / advice_rel(name, dispatch)
        body = {"stage": name, "role": str(role or ""), "written_at": datetime.now().isoformat(timespec="seconds"),
                "records": [{"script": str(getattr(r, "script", "") or ""), "text": str(r)} for r in records],
                "unread": [{"script": str(u.get("script") or ""), "reason": str(u.get("reason") or "")} for u in unread]}
        if path.name != f"advice-{name}.json":
            body["dispatch"] = str(dispatch).strip()
        atomic_text(path, json.dumps(body, indent=2, ensure_ascii=False) + "\n")
    except OSError as exc:
        return f"the write failed ({type(exc).__name__})"
    return ""


def run_advisers(agent: str, task: str = "") -> list:
    """Run the role's ADVISERS (`sizing.py`, which WRITES `work/sizing.json`) for the story `task` names, then write the advice
    file (`write_advice`). Called by `all_errors` only when nothing blocks: a refused stop writes no file (AR-14, GW1-10 F-B2 a).

    The file holds every ADVICE record of the stop: the advisers' own, the ones `detector_errors` set aside, the digest's (a word
    outside the form's list, X2-3). THE RULE (the Lead, t-1815 F5; E-A15): an adviser NEVER blocks the stop. One that fails
    - a non-zero exit (whatever it printed), a timeout, a start that failed, an output outside the contract - is ONE signal to
    the person (`_advice_signal`, FR-59, AR-28) and a line of `unread` in the file; whatever it printed is filed as advice
    (the records are advice, the failure is the signal) and its content never goes to the person. The returned list is
    therefore always empty (kept for the caller `all_errors`, which judges it like any other block list).

    No file is written for a stage that declares nothing for the role (E-X2-2b: S6, S7) unless there is something to file."""
    stage, scripts, advisers = _stage_detectors(agent, task)
    records = [r for source in ("detector", "digest") for r in _STASH.pop((agent, task, source), [])]
    unread = []
    for script in scripts:
        if script not in advisers:
            continue
        got, not_run = _run_detector(script, task)
        if not_run:
            unread.append({"script": script, "reason": not_run})
            _advice_signal(script, not_run, task)
            continue
        # a non-zero exit leaves a `summary` record (and the contract's refusal records) beside the advice: that is the failure
        failed = any(record.kind != DV.ADVICE_KIND for record in got)
        records += [record for record in got if record.kind != "summary"]
        if failed:
            why = "it exited non-zero; what it printed is filed as advice"
            unread.append({"script": script, "reason": why})
            _advice_signal(script, why, task)
    if stage and (scripts or records or unread):
        ticket = _ticket_of(agent, task)
        live = _live_dispatch(agent, task) if stage == "S5" else None     # TR3-15: the finisher the gate identified (named, held, or the sole one); None: no identity, the old file
        why = write_advice(artifact_root() / ticket if ticket else None, stage, agent, records, unread,
                           str((live or {}).get("id") or "") if isinstance(live, dict) else "")
        if why and (records or unread):
            print(f"exit gate note: the advice of {agent} on {stage} is not filed - {why}", file=sys.stderr)
    return []


def next_hint(agent: str) -> str:
    """The "next:" line, computed from stages.json's own ordering — never a hand-typed
    sentence naming a role or phase that can drift out of date when the stage model
    changes (this replaces a dictionary that still named the retired qa-hardening-gate
    and old Phase 7/9/10 numbering after the S0-S9 rewrite)."""
    try:
        model = SG.stage_model()
        at = SG.stage_index(model, _stage_id(agent))
        stage = model["stages"][at] if at >= 0 else None
        if not stage:
            return ""
        roles = stage.get("roles") or []
        if agent in roles and roles.index(agent) < len(roles) - 1:
            nxt_role = roles[roles.index(agent) + 1]
            return f"next: {nxt_role} finishes stage {stage['id']} ({stage.get('name')})"
        stages = model.get("stages") or []
        idx = SG.stage_index(model, stage["id"])
        if idx < 0 or idx + 1 >= len(stages):
            return ""
        nxt = stages[idx + 1]
        gate = nxt.get("gate_before")
        gate_txt = f"gate {gate} decision, then " if gate else ""
        nxt_roles = nxt.get("roles") or ([nxt["role"]] if nxt.get("role") else ["code only"])
        return f"next: {gate_txt}{', '.join(nxt_roles)} for {nxt['id']} ({nxt.get('name')})"
    except Exception:
        return ""  # a hint is a courtesy, never a reason to fail a clean handoff


def _read_json(path: Path) -> dict:
    """The JSON object in `path`, else {}: absent, unreadable, not JSON, or JSON that is not an object (this gate reads
    objects only). The reading is `hooklib.read_json`; the object check and the {} are this gate's direction."""
    return read_json(path, {}, kind=dict, errors=Exception)


def _output_path(art_dir: Path, name: str) -> Path:
    """Where a stage's declared output actually is.

    `stages.json` names working artifacts under `work/`, but a story started before that
    split has them flat — and a required output looked up only at the new path would block
    the next handoff of every in-flight story the moment the plugin is updated. Accept the
    declared path first, then the other spelling; an already-correct story is unaffected.

    The case store is the other exception. `config.cases_root` moves it out of the story
    tree entirely (a project keeps its cases where it keeps them), so S4's declared
    `work/test-cases/` is "missing" forever on such a project and no handoff after it can
    close. `contract.cases_root` is the one answer to where the cases are."""
    if name.startswith("project:"):
        return project_root() / name[len("project:"):]
    if name.rstrip("/").endswith("test-cases"):
        try:
            from contract import cases_root
            store = cases_root(art_dir)
            if store.exists():
                return store
        except Exception:
            pass  # a configured store that cannot be resolved falls back to the story's own
    declared = art_dir / name
    if declared.exists():
        return declared
    alt = (art_dir / name[len("work/"):]) if name.startswith("work/") else (art_dir / "work" / name)
    return alt if alt.exists() else declared


def _output_present(art_dir: Path, name: str) -> bool:
    p = _output_path(art_dir, name)
    if name.endswith("/"):
        return p.is_dir() and any(f.is_file() for f in p.rglob("*"))
    return p.is_file()


def _ticket_for_stage(stage_id: str) -> str:
    """The ticket the just-stopped role was working on: the most recently touched
    pipeline.json whose entry for this stage is 'running', else the most recently
    touched pipeline.json overall (a role may finish just after the orchestrator marks
    the stage done). No pipeline.json anywhere -> "" (fail-open — not a factory story)."""
    root = artifact_root()
    if not root.exists():
        return ""
    try:
        pipelines = sorted(root.glob("*/pipeline.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        return ""
    for p in pipelines:
        stages = _read_json(p).get("stages")
        if isinstance(stages, dict) and (stages.get(stage_id) or {}).get("status") == "running":
            return p.parent.name
    return pipelines[0].parent.name if pipelines else ""


def stage_dispatch(records, stage: str):
    """The LAST dispatch record of `stage` by the INSERTION order of the `dispatches` mapping (never by id sort), whatever its
    status; None when `records` is not a mapping or holds no record of the stage. ONE reader of "the newest dispatch of a stage"."""
    if not isinstance(records, dict):
        return None
    found = None
    for record in records.values():
        if isinstance(record, dict) and record.get("stage") == stage:
            found = record
    return found


def s3_strategist_records(records) -> dict:
    """The S3 dispatch records of the plan's author (`qa-test-strategist`) that count, in the mapping's own order: the optional first-look
    runner's record (t-2277 FL-5) is none of them, and a set-aside record (`controller.DISCOUNTED`) does not count. THE one reader
    (AR-13) of "the strategist's dispatches": `_s3_window_one` reads it here; `story_run.s3_window` and `s3_author_done` read it too (t-2277 small-1). `{}` for anything that is not a mapping."""
    from controller import DISCOUNTED
    if not isinstance(records, dict):
        return {}
    return {k: v for k, v in records.items()
            if isinstance(v, dict) and v.get("role") == "qa-test-strategist" and v.get("status") not in DISCOUNTED}


def _s3_window_one(art_dir: Path) -> bool:
    """Is the NEWEST S3 strategist dispatch of the story window 1 (`request_binding.purpose: s3_labelling`)? Only `qa-test-strategist`
    records count (`s3_strategist_records`), as in `story_run.s3_window` (t-2277 FL-5): the first-look runner's dispatch (purpose
    `first_look`) is never window 1 and never hides one. Anything unreadable, absent or not a mapping answers False: the plan is owed
    (HEAD behaviour) - the direction is toward refusing, never toward a pass (AR-28)."""
    try:
        from controller import s3_window_of
        state = _read_json(art_dir / "state" / "controller.json")
        return s3_window_of(stage_dispatch(s3_strategist_records(state.get("dispatches")), "S3")) == "labelling"
    except Exception:
        return False


def _optional_placed(agent: str, task: str, model: dict | None = None):
    """`(stage entry, row, record)` when the stop of `agent` is an OPTIONAL dispatch of a stage (t-2277 FL-5: the first look, a `qa-runner`
    of purpose `first_look` in S3), else None: the stage's own `optional_dispatches` rows (`stage_guard.optional_stage_of_dispatch`, the one
    reader) matched against the story's running dispatch (the held one when a caller holds it). A role no stage names in an optional row,
    a stop that names no story, an unreadable state: None - the role is judged by its own stage as before (AR-28)."""
    try:
        model = model if model is not None else SG.stage_model()
        if agent not in SG.optional_roles(model) or not task or task == "unknown-task" or not is_story_folder(artifact_root(), task):
            return None
        dispatches = _read_json(artifact_root() / task / "state" / "controller.json").get("dispatches")
        return SG.optional_stage_of_dispatch(model, agent, dispatches, name=held_dispatch())
    except Exception:
        return None


def _window_one_errors(art_dir: Path) -> list:
    """The role's lines from GT's check of work/grounding.yaml (every rule: R0 syntax, R1, R2, R3, R4, R8) for window 1."""
    try:
        import grounding_table as GT
        findings = GT.check(art_dir)
    except Exception as exc:
        # D16 (RH1-5): a check that could not run is the third state with its own name, not a line the role must "name"
        return [unreadable_record("grounding_table.py", f"S3 window 1 (labelling): the grounding check could not run "
                                                        f"({type(exc).__name__})")]
    return [f"S3 window 1 (labelling): {f.text}" for f in findings if f.who == "role"]


def _s5_plan_dispatch(art_dir: Path, agent: str):
    """The NEWEST S5 dispatch record of THIS role (insertion order of `dispatches`, whatever its status) when it is a plan
    dispatch (`controller.s5_part_of`), else None. Anything unreadable answers None - "not a plan" - which is today's check:
    the direction is toward asking for the manifest and the evidence, never toward a pass (AR-28)."""
    try:
        from controller import s5_part_of
        state = _read_json(art_dir / "state" / "controller.json")
        mine = [d for d in (state.get("dispatches") or {}).values()
                if isinstance(d, dict) and d.get("stage") == "S5" and d.get("role") == agent]
        return mine[-1] if mine and s5_part_of(mine[-1]) == "plan" else None
    except Exception:
        return None


def _s7_investigation_dispatch(art_dir: Path, agent: str):
    """The NEWEST S7 dispatch record of THIS role (insertion order of `dispatches`, whatever its status) when it is an
    investigation dispatch (`controller.s7_part_of`), else None. Anything unreadable answers None - "not an investigation" -
    which is today's full check: the direction is toward asking for the output, never toward a pass (AR-28)."""
    try:
        from controller import s7_part_of
        state = _read_json(art_dir / "state" / "controller.json")
        mine = [d for d in (state.get("dispatches") or {}).values()
                if isinstance(d, dict) and d.get("stage") == "S7" and d.get("role") == agent]
        return mine[-1] if mine and s7_part_of(mine[-1]) == "investigation" else None
    except Exception:
        return None


def _s5_plan_outputs_errors(art_dir: Path, agent: str, plan: dict, ticket: str) -> list:
    """What a plan dispatch owes: the author the plan file, the critic its handover form WITH a `remarks` section (empty is a
    section too). The manifest and `work/evidence/` are the windows' outputs and are not asked of a plan (SC1-14 B1b)."""
    if agent == "qa-automator":
        missing = [] if _output_present(art_dir, "work/s5-plan.json") else ["work/s5-plan.json"]
    else:
        from story_step import FORM_REL
        form = FORM_REL.format(dispatch_id=plan.get("id"))
        missing = [form + " (a form with a `remarks` section)"]
        try:
            import handoff_check
            data = handoff_check.form_view(art_dir / form).data     # the form plus its waiting values file (SC1-2 part D)
            if isinstance(data, dict) and "remarks" in data:
                missing = []
        except Exception:
            pass
    if not missing:
        return []
    return [f"S5 plan ({agent}) is missing required output(s) for {ticket}: {', '.join(missing)} - write them before finishing, or "
            "hand the orchestrator a halt with the reason instead of an incomplete handoff."]


def required_outputs_errors(agent: str, task: str = "") -> list:
    """stages.json's own `required_outputs` for the stage this role belongs to — the
    handoff contract, not a Python list. A role with no matching stage (a foreign agent)
    or a stage with nothing required returns clean; a project with no running story for
    this stage is fail-open, same as the rest of this file."""
    model = SG.stage_model()
    at = SG.stage_index(model, _stage_id(agent, task))
    stage = model["stages"][at] if at >= 0 else None
    if not stage:
        return []
    required =stage.get("required_outputs") or []
    placed = _optional_placed(agent, task, model)       # t-2277 FL-5: the first look is judged by its own output, not by S3's plan files
    if not required and placed is None:
        return []
    ticket = task if task and task != "unknown-task" else _ticket_for_stage(stage["id"])
    if not ticket:
        return []
    art_dir = artifact_root() / ticket
    if placed is not None:
        # t-2277 FL-5: an optional dispatch owes its OWN output (the row's `output`, `stage_guard.optional_outputs`), never the stage's
        # `required_outputs` (the twin of the plan / investigation filters below): the first look owes `work/first-look.yaml`, the S1
        # reference walk `work/reference-snapshot.yaml` (t-2181 PC-9b).
        missing = [name for name in SG.optional_outputs(placed[1]) if not _output_present(art_dir, name)]
        return [f"{stage['id']} ({agent}, {placed[1]['purpose']}) is missing required output(s) for {ticket}: {', '.join(missing)} - write "
                "them before finishing, or hand the orchestrator a halt with the reason instead of an incomplete handoff."] if missing else []
    if stage["id"] == "S3" and _s3_window_one(art_dir):
        # G1-11: window 1 of S3 labels work/grounding.yaml and writes no plan; its output is judged by GT, and only the
        # findings whose fix is the ROLE's (a driver or conductor finding is not the role's to fix: FR-2).
        return _window_one_errors(art_dir)
    plan = _s5_plan_dispatch(art_dir, agent) if stage["id"] == "S5" else None
    if plan is not None:
        # SC1-14 B1b: the plan dispatch of S5 writes the plan (or its review), not a window's manifest and evidence.
        return _s5_plan_outputs_errors(art_dir, agent, plan, ticket)
    if stage["id"] == "S7" and _s7_investigation_dispatch(art_dir, agent) is not None:
        # F10: an investigation dispatch writes its form and the register, not a triage; the filter drops that one output only.
        required = [p for p in required if p != "work/triage.json"]
    missing = [name for name in required if not _output_present(art_dir, name)]
    if not missing:
        return []
    return [
        f"{stage['id']} ({agent}) is missing required output(s) named in references/stages.json "
        f"for {ticket}: {', '.join(missing)} — write them before finishing, or hand the "
        "orchestrator a halt with the reason instead of an incomplete handoff."
    ]


# A role's last word, in the 0.7.x spelling: `<role> <stage> done|halt|impossible|review ·
# <path> · <one fact>`. Only the verb matters here, and only at the start of a line, so a
# sentence that merely contains the word "halt" is not one. The current form carries the
# verdict after the scope (`<role> <stage> <window> · halt`) and is read by role_digest.
HALTING_DIGEST_RE = re.compile(r"(?im)^\s*[\w-]+\s+S\d\s+(halt|impossible)\b")


DIGEST_TAIL_ROWS = 400    # how far back from the end of a transcript the role's last word is looked for
DIGEST_MAX_CHARS = 4000


def _last_word(path, forms) -> tuple:
    """(the last non-empty word of the assistant in the transcript file `path`, why not) - the rows of the last
    DIGEST_TAIL_ROWS lines, walked backwards; a row that is not JSON, not an object or not an assistant's is
    skipped. Both host shapes and the host's handback call are read by the ONE row reader
    (`host_adapter.assistant_row_texts`); the texts of the newest row that has any are joined."""
    from host_adapter import assistant_row_texts
    if not isinstance(path, str) or not path.strip():
        return "", "the event names no usable path"
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as error:
        return "", f"{error.__class__.__name__}"
    for line in reversed(lines[-DIGEST_TAIL_ROWS:]):
        try:
            record = json.loads(line)
        except ValueError:
            continue
        parts = [t for t in assistant_row_texts(record, forms) if t]
        if parts:
            return "\n".join(parts)[:DIGEST_MAX_CHARS], ""
    return "", f"no assistant word in its last {DIGEST_TAIL_ROWS} rows"


def handoff_digest(event: dict) -> str:
    """The role's own last word, from the role's OWN transcript when the host names it.

    Nothing else in the event says what the role decided. Sources, in order: (1) `agent_transcript_path` - the
    subagent's own transcript; (2) `last_assistant_message`, a non-empty string; (3) `transcript_path` - the
    transcript of the session that stopped, which for a host that names no child transcript is the role's.
    POSITION: (1) is first. INVARIANT: when the event names the child's transcript, the parent's text is never the
    role's word - not for the form, not for `is_halting_handoff`, not for `work/digests/`: a parent's prose judged
    as the role's digest blocked a role 17 times on run 12586 for words it never wrote. A child transcript that
    cannot be read answers "", one stderr line and one `hook_signal` (stderr alone reaches nobody) - the digest is
    not judged and not filed, so `finish --digest -` asks for it; never a fall-through to (3). No path at all answers "": the gate behaves as before."""
    from host_adapter import report_forms
    event = event if isinstance(event, dict) else {}
    forms, _why = report_forms()   # unreadable forms: only text blocks are read (the safe side)
    if "agent_transcript_path" in event:
        word, why = _last_word(event.get("agent_transcript_path"), forms)
        if not word:
            if forms is None:
                why = f"{_why}; only text blocks could be read, and the role's word may be its handback call"
            note = (f"exit gate note: the role's own transcript could not be read ({why}); its digest is not judged "
                    "and not filed.")
            print(note, file=sys.stderr)
            # FR-59: stderr at exit 0 reaches nobody. The unknown goes where the orchestrator reads it - the project
            # journal's `hook_signal` (the road `_unreadable_stop` uses) - once per dispatch (its child transcript).
            import hooklib
            hooklib.person_signal(event, "gate_unreadable", note, once_key=f"digest|{event.get('agent_transcript_path')}")
        return word
    message = event.get("last_assistant_message")
    if isinstance(message, str) and message.strip():
        return message[:DIGEST_MAX_CHARS]
    return _last_word(event.get("transcript_path"), forms)[0] if event.get("transcript_path") else ""


def text_end_after_handback(event: dict, agent: str = "", task: str = "") -> list:
    """HF8-15 (1): at most ONE record - a role that already handed its report back (the host's handback call is in its
    own transcript) and then ended its turn in plain text. A role resumed by a message answers with the host's handback
    call; text is not a return, the conductor gets nothing it can take, and the story waits on a role that thinks it
    is done. The record says what to do: call the handback tool (its name is data, `host-report-forms.json`, AR-1).

    Only a factory role with a dispatch is refused: the running dispatch is `_live_dispatch(agent, task)` (the live-dispatch condition), and with none - an agent that is not the factory's, a role with no running dispatch, two
    running - there is no record and the hook exits 0 (FR-2, FR-36, P1; the host sends built-in agents here too).
    Only the Claude host reads it (`is_codex` gives nothing: no handback call in a Codex transcript) and only a
    child's OWN transcript (`agent_transcript_path`; the parent's text is never the role's word, `handoff_digest`).
    POSITION: `main` calls this once, on the first stop, after `all_errors` and before the decision to block; it is
    NOT part of `all_errors`. INVARIANT: `finish` and the driver read the same checks through `all_errors`
    (`_finish_gate`) and never see this record - a text end never stops `finish` and never asks a person's word; the
    fuse of one block is unchanged, so there is no loop. Every unknown (no path, an unreadable file, forms that
    cannot be read, a crash) gives [] - nothing is refused for what could not be read (`handoff_digest` already
    reports an unreadable transcript), and the conductor's wake-up does not take it for a return (AR-28)."""
    try:
        import host_adapter
        if not isinstance(event, dict) or host_adapter.is_codex(event) or _live_dispatch(agent, task) is None:
            return []
        path = event.get("agent_transcript_path")
        forms, _why = host_adapter.report_forms()
        name = host_adapter.handback_name(forms)
        if not name or not isinstance(path, str) or not path.strip():
            return []
        if not host_adapter.ended_in_text_after_handback(path, forms, DIGEST_TAIL_ROWS):
            return []
        return [DV.Record(f"Your last turn ended in text. A resumed role hands its report back with the host's handback "
                          f"call: call {name} with your digest line.", script="exit_gate_text_end")]
    except Exception:  # noqa: BLE001 - a crash of the reader refuses no one
        return []


# The role's own handover form is NOT checked at the stop (X2-3): `story_step finish` checks it with its own code and its own
# `--fix` (`_handoff_check`), so a second refusal of the same fact at the stop only spent the role's one block (21 of 26 blocks
# of run 14857). Absence is `finish`'s refusal; the form's content is the stage critic's reading.


def is_halting_handoff(digest: str) -> bool:
    """A `halt` or `impossible` digest — the role handing the decision back, not finishing."""
    text = str(digest or "")
    if bool(HALTING_DIGEST_RE.search(text)):
        return True
    try:
        return RD.is_halting(text)
    except Exception:
        return False  # a halt unread is a handoff refused: never on an error of ours


def _ticket_of(agent: str, task: str) -> str:
    """The story the just-stopped `agent` worked on: the task the hook named, else the newest story whose stage is running."""
    stage_id = _stage_id(agent, task)
    return task if task and task != "unknown-task" else (_ticket_for_stage(stage_id) if stage_id else "")


def _live_dispatch(agent: str, task: str):
    """The ONE running dispatch record of this role on its stage (the way `s5_precheck.running_dispatch` reads it), with
    its `id` filled from the mapping key when the record lacks it; None for none, two or more, or anything unreadable.
    The ONE reader of "which dispatch is this stop": `dispatch_scope` takes its scope from it and `_write_digest` its id,
    so a digest is never filed under another dispatch's name (E36)."""
    stage_id = _stage_id(agent, task)
    ticket = _ticket_of(agent, task)
    if not ticket or not stage_id:
        return None
    state = _read_json(artifact_root() / ticket / "state" / "controller.json")
    import dispatch_identity
    # AR-13: the one reader. `dispatch_identity.own` reads the rows itself (`records` fills the id from the mapping key) and looks the
    # name up through `held`: a held dispatch (the caller's own, `holding_dispatch`) or a named one (the environment) picks its own
    # record; with no name the count rule, as before. No hand-built rows here.
    return dispatch_identity.own(state.get("dispatches"), role=agent, stage=stage_id, name=held_dispatch() or None)


def dispatch_scope(agent: str, task: str) -> list:
    """The ids this dispatch was scoped to, from the controller's own record of it.

    The running dispatch of this role on this stage (`_live_dispatch`): with none, or two, the
    scope is unknown and the digest is judged on its form alone. Nothing here is a reason to
    fail a handoff, so every unreadable state answers "no scope" — a story whose controller.json
    predates `scope` keeps working untouched."""
    return _scope_of(agent, _live_dispatch(agent, task))


def _scope_of(agent: str, live) -> list:
    """`dispatch_scope` for a live record the caller already holds (`digest_errors` reads `controller.json` once per stop)."""
    if live is None:
        return []
    if role_name(agent) == "qa-bug-reporter":
        # Its items are the bugs it wrote, never the story's cases: a reporter dispatched
        # after gate B inherits the story scope, and the roll-call then demanded a line per
        # test case from a role that files bugs (TP1-13797, driver run 3).
        return []
    return [str(c) for c in (live.get("scope") or live.get("cases") or []) if str(c).strip()]


DIGEST_DIR = "work/digests"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def digest_path(task_root, ident) -> "Path | None":
    """`<task_root>/work/digests/<ident>.txt` - THE one spelling of where a dispatch's filed digest lives, read by the writer
    (`_write_digest`) and by `story_step._digest_of`; None when `ident` is not a plain file name (no path is built from it)."""
    ident = str(ident or "")
    return Path(task_root) / DIGEST_DIR / f"{ident}.txt" if _SAFE_ID.match(ident) else None


def _unfile_digest(agent: str, task: str, live: dict) -> None:
    """A digest the gate REFUSED leaves no earlier file of the same dispatch behind (SC1-14 fix X, F-4): `finish --digest -`
    must read the role's last word, not the verdict of an earlier stop. Never raises."""
    try:
        ticket = _ticket_of(agent, task)
        path = digest_path(artifact_root() / ticket, (live or {}).get("id")) if ticket else None
        if path is not None:
            path.unlink(missing_ok=True)
            path.with_name(f"{path.stem}.original.txt").unlink(missing_ok=True)
    except OSError:
        pass


def _write_digest(agent: str, task: str, live: dict, text: str, original: str = "") -> str:
    """Write the digest the gate passed to `work/digests/<dispatch id>.txt` (the exit gate's own record, the one
    `story_step finish --digest -` reads); when the gate mended the form, the role's own text goes beside it as
    `<id>.original.txt`, and a clean write removes a leftover one of an earlier stop. Returns "" on success, else why no
    file was written (said on stderr by the caller): no story folder (a hook never makes one), an id that is not a plain
    file name, a write that failed. Never raises."""
    ticket = _ticket_of(agent, task)
    path = digest_path(artifact_root() / ticket, (live or {}).get("id")) if ticket else None
    if path is None or not is_story_folder(artifact_root(), ticket):
        return "no story folder or no plain dispatch id"
    aside = path.with_name(f"{path.stem}.original.txt")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if original:
            aside.write_text(original, encoding="utf-8", newline="\n")
        else:
            aside.unlink(missing_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    except OSError as exc:
        return f"the write failed ({type(exc).__name__})"
    return ""


def _witness_path(agent: str, live: dict, art_dir: Path) -> str | None:
    """The task-relative artifact this role's stage names in `stages.json.witness`, when it is a story file or folder
    that EXISTS and the dispatch is not an S5 plan (whose artifact is the plan, not the windows' manifest); else None."""
    name = witness_gates().get(agent)
    if not name or name.startswith("project:"):
        return None
    if live.get("stage") == "S5":
        try:
            from controller import s5_part_of
            if s5_part_of(live) == "plan":
                return None
        except Exception:
            return None        # a plan that cannot be told from a window gets no guessed path
    target = art_dir / name
    return name if (target.is_dir() if name.endswith("/") else target.is_file()) else None


def _mended_digest(agent: str, task: str, digest: str, scope: list, live: dict):
    """The digest with the form defects code can mend (`role_digest.canonical`) when that makes it pass `check`, else
    None. Any exception answers None: not mended, the refusal stands."""
    try:
        art_dir = artifact_root() / _ticket_of(agent, task)
        mended, _ = RD.canonical(digest, scope, _witness_path(agent, live, art_dir), art_dir)
        return mended if mended and not RD.check(mended, scope) else None
    except Exception:
        return None


def digest_errors(agent: str, task: str = "", digest: str = "") -> list:
    """At most ONE error: the role's final message is not the handoff form.

    One, because the message quotes the form, and a form quoted five times is noise. No
    digest at all (a host that sends no transcript) is not a finding — the gate has nothing
    to judge and says nothing, the way it treats every other thing it cannot read. Neither is
    a foreign agent's: the form is what the factory's own roles hand each other, and a
    neighbouring plugin's subagent owes this gate nothing."""
    _stash_advice(agent, task, "digest", [])
    if not str(digest or "").strip() or not _stage_id(agent, task):
        return []
    try:
        live = _live_dispatch(agent, task)
        scope = _scope_of(agent, live)
        errors, words = _digest_word_split(digest, scope, RD.check(digest, scope))
        # a verdict or a state outside the form's list is the stage critic's to read (X2-3, AR-29): it is advice in the file,
        # and the stop is refused only for what is absent (a path, a line for an id of the scope, a header)
        _stash_advice(agent, task, "digest", [DV.Record(w, script="role_digest", kind=DV.ADVICE_KIND) for w in words])
    except Exception as exc:
        # D12 (RH1-5): a digest check that could not run is the third state, never "the digest is in the form"
        return [unreadable_record("role_digest", f"the digest check could not run ({type(exc).__name__})")]
    # SC1-14 B3: EVERY digest the gate lets through is filed for `story_step finish --digest -` - the role's own text
    # when it is in the form, the mended text (`RD.canonical`, a closed list of form defects) when code could mend it.
    # POSITION: the mending is before the judge. INVARIANT: the judge sees only what code did not mend, and a digest
    # nobody can file under ITS dispatch (none or two live) is neither mended nor filed: the verdict is today's.
    if live is None:
        print(f"exit gate note: the digest of {agent} is not filed - there is not exactly one live dispatch of the "
              "role on its stage; `finish --digest -` will ask for the digest line.", file=sys.stderr)
    else:
        # t-1685 N3-2: what the role wrote AFTER the path is kept whole whether the form passes or not (one writer:
        # `role_digest.file_notes`); the accepted digest names it as `notes: <path>`, a refusal says where it is kept.
        # INVARIANT: the verdict is the form lines' alone - a tail never passes or fails a digest. "" when no tail.
        try:
            notes_rel = RD.file_notes(artifact_root() / _ticket_of(agent, task), live.get("id"), digest)
        except Exception:
            notes_rel = ""
        if not errors:
            _filed(_write_digest(agent, task, live, RD.with_notes_line(digest, notes_rel)), live)
        else:
            mended = _mended_digest(agent, task, digest, scope, live)
            if mended is not None:
                _filed(_write_digest(agent, task, live, RD.with_notes_line(mended, notes_rel), original=digest), live)
                return []
    if errors:
        if live is not None:
            _unfile_digest(agent, task, live)
    if not errors:
        return []
    kept = f" Your notes after the path are kept whole in {notes_rel} for the conductor." if live is not None and notes_rel else ""
    return [RD.refusal(agent, errors) + kept]


def _filed(why: str, live: dict) -> None:
    """Say on stderr why a digest could not be filed ("" = it was); the gate's verdict is not touched."""
    if why:
        print(f"exit gate note: the digest of dispatch {live.get('id')} is not filed - {why}; "
              "`finish --digest -` will ask for the digest line.", file=sys.stderr)


def _digest_word_split(digest: str, scope: list, found: list) -> tuple:
    """`(refused, advice)` of the problems `role_digest.check` found: what is ABSENT or malformed (the header, the path, a line for
    each id of the scope) is refused; a verdict or a row state that is a WORD outside the form's list is advice (X2-3). No
    wording is read here: the digest is checked once more with the words it spells outside the list set to words inside it
    (`role_digest.askable` finds where, `apply` sets them), and a problem that is still there is a problem of presence; the
    others are the words'. Direction of error: toward a refusal - a problem that cannot be told apart stays refused."""
    if not found:
        return [], []
    spots = RD.askable(digest)
    if not spots["verdict"] and not spots["rows"]:
        return list(found), []
    neutral = set(RD.check(RD.apply(digest, {"verdict": "ok" if spots["verdict"] else "",
                                             "rows": {row["index"]: "unresolved" for row in spots["rows"]}}), scope))
    return [e for e in found if e in neutral], [e for e in found if e not in neutral]


def answered_question_errors(agent: str, task: str = "") -> list:
    """S2: an answered question stays in the register with its id (T6). `work/question-answers.jsonl` holds what the
    person said; a role that rewrote requirements-readiness.json without the row (or under another id) took the
    question out of the hands of everything that reads its status. One error per row that has a settled or kept-open
    record and no row (`question_register.readiness_drift`), named by the file so the S2 role's own stage owns it.
    [] for any other role, for a story with no folder, no answers and no readable register - the store speaks only
    where it holds a record."""
    if role_name(agent) != "qa-requirements-tester":
        return []
    ticket = task if task and task != "unknown-task" else _ticket_for_stage("S2")
    if not ticket or not is_story_folder(artifact_root(), ticket):
        return []
    try:
        import question_register as QR
        return [f"requirements-readiness.json: {problem}" for problem in QR.readiness_drift(artifact_root() / ticket)]
    except Exception as exc:
        # D10 (RH1-5): the drift check is a back-up of the role's own register discipline, and its failure is said as
        # the third state (the conductor's), not read as "no drift" (FR-59)
        return [unreadable_record("question_register", f"the answered-question drift check could not run ({type(exc).__name__})",
                                  "requirements-readiness.json")]


def _gate_note(note, task: str = "") -> None:
    """A note of the gate for the person (a check that let something wait, a join it could not read): the journal
    event `hook_signal` of kind `exit_gate_note`, which the run report reads. SubagentStop's stdout at exit 0 is not
    read by anybody (RH1-5, H17). `task` (N6): the story, so the report places it by it. `once_key` (N7): the same note
    is said by the hook, by `finish` and by the driver for ONE handoff; this helper holds no session (an empty event), so
    the writer cannot dedupe by itself (`once_key` is passed for a caller that has one) and the REPORT counts one note
    per (story, text): the line is written again, never lost."""
    import hooklib
    hooklib.person_signal({}, "exit_gate_note", f"exit gate note: {note}",
                          task=task if task and task != "unknown-task" else None, once_key=str(note))


def collect_errors(task: str = "", facts_text: str = "") -> list:
    errors: list = []
    artifacts = artifact_root()
    art_root = artifacts / task if task and task != "unknown-task" else None
    if art_root and art_root.exists():
        notes: list = []
        for jf in sorted_paths(art_root.rglob("*.json")):
            va.check_phase_json(jf, errors, notes)
        for note in notes:   # t-290: what the check let wait is said, never silent (FR-4); a SubagentStop's stdout reaches nobody (H17)
            _gate_note(note, task)
        # test-cases live per-ticket: qa-factory/artifacts/<TICKET>/test-cases/. Every .md, then the
        # id form decides (`config.case_id_form`, then `TC-NNN`): the glob used to be `TC-*.md`, so
        # a project-form case was never validated here (B-013, FR-17).
        for case in C.case_glob(art_root, art_root):
            va.check_case(case, errors)
        # O5 (t-227, P20): the register is checked on write, but when it was written BEFORE
        # requirements-readiness.json its claims' question ids could not be checked then - the
        # file was not there. The S2 exit is the first moment both exist, so the claims are
        # re-checked here (the same function, never a copy). A register written after the
        # readiness file was checked on write and reads the same here.
        register = None
        try:
            register = C.artifact(art_root, "requirements-register.md")
            if register.is_file():
                text = register.read_text(encoding="utf-8", errors="replace")
                # F1 (t-269): an unreadable `created` is refused by name, never read as "before the cutoff".
                if va._oracle_dated(va.parse_frontmatter(text) or {}, "created", register.name, errors,
                                    required_already=True):
                    va.check_behaviour_claims(register, text, errors)
        except Exception as exc:
            # D11 (RH1-5): a register that EXISTS and whose claims could not be re-checked is the third state; an
            # absent one has nothing to check (the register is its own write-time finding)
            try:
                present = register is not None and register.is_file()
            except OSError:
                present = True
            if present:
                errors.append(unreadable_record("requirements-register claims",
                                                f"the re-check of the register's claims could not run ({type(exc).__name__})",
                                                "requirements-register.md"))
        # HF2-7: the S2 role's answered question stays in the register. The error names requirements-readiness.json,
        # so `scoped_errors` hands it to the stage that lists that file (S2) and to no other.
        errors.extend(answered_question_errors("qa-requirements-tester", task))
    errors.extend(bug_audit_errors(task, facts_text))
    return errors


UNNAMED_PREFIX = "this stop names no story"


def _is_header(error) -> bool:
    return str(error).startswith(UNNAMED_PREFIX)


def _findings(errors: list) -> list:
    """The list without the unnamed header: the header explains the findings, it is not one (the count a person
    reads, and the first three the journal quotes)."""
    return [e for e in errors if not _is_header(e)]


def _unnamed_header(facts_text: str = "") -> str:
    """The first line of an audit nobody scoped: what the list is, whose it may be, how to narrow it (FR-1, FR-41).
    `facts_text` is what the identity decision itself read (`scope["identity_facts"]`, `SG.identity_facts` of the
    facts `_named_ticket` returned: the ids it found in the text, the task name), never a second read made without
    the stop's event. A caller that has none (the identity step raised, or an audit run outside a stop) gets a line
    saying so, not a list of 'none'."""
    read = facts_text or "\n  (no identity facts reached this audit: the identity step raised, or the caller gave none)"
    return (UNNAMED_PREFIX + " (task unknown-task), so the gate audited EVERY bug of the project and some "
            "findings below may belong to another story. Repair only a bug you filed; report the others to the "
            "orchestrator verbatim, they are not yours to edit. The orchestrator can name the story: "
            "$QA_FACTORY_TASK, or `story_step bind` for this agent. What the gate read:" + read)


def bug_audit_errors(task: str = "", facts_text: str = "") -> list:
    """The project's bug records that fail `check_bug`, for the story `task`; every record when no story is given.

    The project's bug folder is shared by every story, and a bug another story filed is that story's to keep valid:
    it must not stop THIS story's exit (FB-45). A record is skipped only when `bug_records.owner_of` says `other`,
    which needs a positive naming of another story that exists on disk; `unknown` is checked like `mine`. An
    explicit task with no story on disk skips nothing. The join `owner_of` reads is made once for the audit. The
    task `unknown-task` (the identity step found no story) is the full audit and its list opens with a header line
    saying so (`facts_text`: what the identity decision read); a list with no finding gets none, since a header alone
    would block. A join that fails (it raises, or answers no mapping) skips nothing: every bug is audited and a note
    names the reason (FR-41; spec edge 12). A role with no stage reads only this (`scoped_errors`)."""
    errors: list = []
    bugs_root = state_dir() / "bugs"
    if not bugs_root.exists():
        return errors
    bugs = sorted_paths(bugs_root.glob("*BUG-*.md"))
    task_root = artifact_root() / task if task and task != "unknown-task" else None
    joined = None
    if task_root is not None and bugs and (task_root / "pipeline.json").is_file():
        try:
            joined = BR.story_bugs(task_root)
            if not isinstance(joined, dict):
                raise TypeError("the join answered no mapping")
        except Exception as exc:
            # `{}` would read as "the join counted nothing": a bug only the join could call this story's would turn
            # `other` and be skipped. `NO_JOIN` makes `owner_of` answer `unknown` for it, and `unknown` is checked.
            joined = BR.NO_JOIN
            _gate_note(f"the join of {task}'s bugs could not be read ({type(exc).__name__}); "
                       "every bug of the project is audited, none is left to another story", task)
    for bug in bugs:
        if task_root is not None and BR.owner_of(bug, task_root, joined) == BR.OTHER:
            continue
        va.check_bug(bug, errors)
    if errors and task == "unknown-task":
        errors.insert(0, _unnamed_header(facts_text))
    return errors


def scoped_errors(agent: str, task: str = "", facts_text: str = "") -> list:
    """Broken-artifact errors that belong to the stopping role: only files its stage lists
    in `outputs` (stages.json). A scout's broken manifest must not block the designer's
    handover four stages later — the live run of 2026-09-11 break-glassed six roles in a
    row over one upstream key. A role without a stage (a foreign agent, or Codex Desktop's
    "default") sees only the project's bug audit, scoped to its story when the task is known:
    the story's phase json, cases and register are judged at the stop of the role that
    writes them and at the controller's acceptance, and a stop with no stage is neither."""
    model = SG.stage_model()
    at = SG.stage_index(model, _stage_id(agent, task)) if agent else -1
    stage = model["stages"][at] if at >= 0 else None
    if not stage:
        return bug_audit_errors(task, facts_text)
    errors = collect_errors(task, facts_text) if task else collect_errors(facts_text=facts_text)
    if stage.get("id") == "S1":
        ticket = task if task and task != "unknown-task" else _ticket_for_stage("S1")
        if ticket:
            task_root = artifact_root() / ticket
            from source_preflight import check_source_inventory
            pipeline = _read_json(task_root / "pipeline.json")
            errors.extend("source-inventory.json: " + value
                          for value in check_source_inventory(task_root, pipeline)["errors"])
            # The person's list of sources not to read (B-231): the inventory marks and the fetch doors stop
            # the factory's own commands; this is the detector for what the scout's own tools brought in
            # and its manifest then cites. Two structural matches and a receipt scan, never a reading of
            # sentences; [] with no list. A half-installed tree degrades to "feature absent".
            try:
                import source_exclusions
                errors.extend(source_exclusions.manifest_problems(
                    task_root, _read_json(task_root / "work" / "context-manifest.json")))
            except ImportError:
                pass
    # An error names a file, never its folder ("run-report.json: ..."), while stages.json
    # names the path ("work/run-report.json"). Compare on the basename, or a role sees none
    # of its own errors and every handoff passes silently — the direction this gate must
    # never fail in.
    outs = [Path(str(o)).name or str(o) for o in (stage.get("outputs") or [])]
    if stage.get("id") == "S1":
        outs.append("source-inventory.json")
    if not outs:
        return []
    cases = any("test-cases" in o for o in outs)
    bugs = any("bugs" in o or "BUG" in o for o in outs)
    story = artifact_root() / task if task and task != "unknown-task" else None
    cfg = C.case_config(story)

    def mine(err: str) -> bool:
        name = err.split(":", 1)[0].strip()
        if name in outs:
            return True
        # A case-file error is S4's for EVERY name the project's id form recognises; it was
        # a prefix test on the default form, so an error about `TP1-13877_TC_001.md` belonged to
        # nobody and was dropped without a word (B-013, FR-17).
        if cases and C.is_case_file_name(name, cfg=cfg):
            return True
        if bugs and "BUG-" in name:
            return True
        return False

    kept = [e for e in errors if not _is_header(e) and mine(e)]
    # The unnamed header explains the bug findings of this list, so it stays with them (and only with them: a
    # header whose bugs this stage does not own would be a finding of its own, and block alone).
    header = next((e for e in errors if _is_header(e)), None)
    if header is not None and any("BUG-" in str(e).split(":", 1)[0] for e in kept):
        kept.insert(0, header)
    return kept


def _running_stage_among(candidates, tickets_out=None) -> str:
    """The stage, among `candidates` (stage ids), that is `running` in exactly ONE (story, stage) pair of the pipeline.json
    histories under the artifact root; "" for none or more than one. The walk of `_ticket_for_stage`, WITHOUT its fallback to
    the newest file: a stage that cannot be established is not guessed (AR-28). `tickets_out`, a list, receives the story of
    every pair found."""
    root = artifact_root()
    if not root.exists():
        return ""
    try:
        pipelines = sorted(root.glob("*/pipeline.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        return ""
    pairs = []
    for p in pipelines:
        stages = _read_json(p).get("stages")
        if not isinstance(stages, dict):
            continue
        for sid in candidates:
            entry = stages.get(sid)
            if isinstance(entry, dict) and entry.get("status") == "running":
                pairs.append((p.parent.name, sid))
    if isinstance(tickets_out, list):
        tickets_out.extend(ticket for ticket, _ in pairs)
    return pairs[0][1] if len(pairs) == 1 else ""


def _stage_id(agent: str, task: str = "") -> str:
    """The stage id of the stopping role, or "" (not established). A role on one stage: that stage. A role on several: the
    held stage; else the stage of its ONE running dispatch in `task`'s controller.json (`task` named); else the stage running
    in exactly one history (`_running_stage_among`). Calls neither `_ticket_of` nor `_live_dispatch` (no cycle)."""
    try:
        if not agent:
            return ""
        model = SG.stage_model()
        stages = SG.stages_of_role(model, agent)
        if not stages:
            return ""
        optional = _optional_placed(agent, task, model)
        if optional is not None:       # t-2277 FL-5: an optional dispatch stands on the stage whose row names it (the first look: S3)
            return str(optional[0].get("id") or "")
        dispatches = None
        if len(stages) > 1 and not (held_stage() and any(st.get("id") == held_stage() for st in stages)):
            if task and task != "unknown-task":
                if is_story_folder(artifact_root(), task):
                    dispatches = _read_json(artifact_root() / task / "state" / "controller.json").get("dispatches")
            else:
                return _running_stage_among([st.get("id") for st in stages])
        placed = SG.stage_of_dispatch(model, agent, held=held_stage(), dispatches=dispatches)
        return str((placed or {}).get("id") or "")
    except Exception:
        return ""


def _task_pipeline(agent: str, task: str) -> dict:
    stage_id = _stage_id(agent, task)
    ticket = task if task and task != "unknown-task" else (_ticket_for_stage(stage_id) if stage_id else "")
    return _read_json(artifact_root() / ticket / "pipeline.json") if ticket else {}


def awaiting_source_review(agent: str, task: str) -> bool:
    """S1 only: every source carries the factory's decision and no person has seen them."""
    if _stage_id(agent, task) != "S1":
        return False
    ticket = task if task and task != "unknown-task" else _ticket_for_stage("S1")
    if not ticket:
        return False
    try:
        from source_preflight import check_source_inventory
        task_root = artifact_root() / ticket
        return bool(check_source_inventory(task_root, _read_json(task_root / "pipeline.json"))
                    .get("awaiting_review"))
    except Exception:
        return False


def new_production_files(diff_text: str) -> list:
    """The production modules the diff creates: code the requirements never spelled
    out lives there (limits, rejected inputs, guards). The diff is read by `diff_pass.scan` (a new file is
    `new file mode` or `--- /dev/null` right above `+++`) and the kind is `test_files.file_kind` (the one rule),
    asked without the project's word: the gate does not know the implementation checkout."""
    import diff_pass
    import test_files
    created = [entry.path for entry in diff_pass.scan(diff_text or "") if "new" in entry.facts and not entry.combined]
    return test_files.production_files(created, {"production"})


# diff_pass names "say in the handoff" as a door; this gate does not read the handoff, so an unread record
# of the S2 exit carries the doors that open here (a re-export; a person's word) - K10 of G1-10 site 4b.
S2_DIFF_UNREAD_DOOR = ("At the S2 exit the handoff is not read: re-export the diff, or name it in your digest - "
                       "a person's word passes this check (FR-4).")


def grounding_errors(agent: str, task: str = "") -> list:
    """S2: every production module the implementation diff creates must back at least one
    `derived` requirement. TP1-13797, driver run 3: the tester never opened
    work/impl-diff.txt; its register grounded the 13 criteria in the diff's lines and
    derived nothing from the new filter module - the payload limit, the rejected regex
    operator, the rejected root-anchored predicate and the deep-copy guard (3-4 rows in the
    runs whose tester read the diff) were missing, and nothing said so."""
    if role_name(agent) != "qa-requirements-tester":
        return []
    ticket = task if task and task != "unknown-task" else _ticket_for_stage("S2")
    if not ticket:
        return []
    root = artifact_root() / ticket / "work"
    register = root / "requirements-register.md"
    if not register.is_file():
        return []
    import diff_pass
    created, unread = [], []
    for diff in sorted_paths(root.glob("impl-diff*.txt")):
        try:
            text = diff_pass.read_diff(diff)
        except OSError as exc:
            unread.append(f"{diff_pass.unreadable_text(diff.name, str(exc))} {S2_DIFF_UNREAD_DOOR}")   # FR-59: an unread diff is not a pass
            continue
        entries = diff_pass.scan(text, diff.name)
        unread += [f"{entry.refused} {S2_DIFF_UNREAD_DOOR}" for entry in entries if entry.refused]   # a combined diff, a file with no name
        created += new_production_files(text)
    if not created:
        return unread
    try:
        rows = [line for line in register.read_text(encoding="utf-8", errors="replace").splitlines()
                if re.match(r"^\|\s*R-\d+\s*\|", line) and re.search(r"\|\s*derived\s*\|", line)]
    except OSError:
        return unread
    missing = [name for name in dict.fromkeys(created)
               if not any(name.rsplit("/", 1)[-1] in row for row in rows)]
    if not missing:
        return unread
    return unread + [f"requirements-register.md derives nothing from the new module(s) the implementation adds: "
            f"{', '.join(missing)} - no `derived` row cites it. Read every hunk of work/impl-diff*.txt "
            f"(Read with offset/limit, not Grep alone) and add the requirements that code carries: "
            f"limits, rejected inputs and validation, error and failure paths, guards; source `derived` "
            f"with its `derived_from` (for example `invariant:<what>`), observable `diff:<file>:<line>`. "
            f"A `derived` row no ticket source speaks to is implementation-only: the register check then "
            f"asks for its row under \"{C.CLAIM_HEADING}\" (your key page and `## Behaviour claims` of the register template)."]


CASE_FILE_ID_RE = re.compile(r"^id:\s*(\S+)\s*$", re.M)


def _case_front(path: Path) -> tuple:
    """(declared `id`, declared `task`) from a markdown file's front matter, "" for each it lacks.

    Only the head is read: front matter opens the file, and this runs over every `.md` of a case
    tree that can be a whole project library."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            head = handle.read(4000)
    except OSError:
        return "", ""
    # A UTF-8 byte-order mark is not whitespace to str.lstrip; a file an editor saved with one opens
    # with U+FEFF and its front matter was skipped, so its identity was never judged.
    text = head.lstrip(chr(0xFEFF)).lstrip()
    if not text.startswith("---"):
        return "", ""
    parts = text.split("---", 2)
    block = parts[1] if len(parts) > 2 else text[3:]
    found = CASE_FILE_ID_RE.search(block)
    task = C.CASE_TASK_RE.search(block)
    return (found.group(1).strip().strip("\"'") if found else "",
            task.group(1).strip().strip("\"'") if task else "")


def case_identity_errors(agent: str, task: str = "") -> list:
    """S4: a case file's `id` is its file name (`<case id>.md` declares `<case id>`) and is ONE
    case id in a form the project records - the identity every later join uses.

    FORM-FREE by design: it reads every front-matter `id:` in the story's case tree and does not
    ask the glob which files are cases. It used to glob `TC-*.md`, so on TP1-13877 the files
    `TP1-13877_TC_001.md` ... were never looked at, the handoff passed, and every join after
    it read "no cases" (B-013, FR-13). A file whose front matter carries no `id:` is not a case
    document and is out of scope; the store's own layout (`cases/`, `case-versions/`,
    `test-cases/` as a path part below the root) is skipped, and in a shared store (`cases_root`)
    only the files whose `task:` is this story are its own. The designer of TP1-13797 (driver
    run 3) followed the project's strategy note (`TP1-<ticket>_TC_<nnn>`) instead of the
    contract; the handoff passed, the controller's projection refused every recovery and a
    conductor asked the person - the door named below is what it should have been told."""
    if role_name(agent) != "qa-case-designer":
        return []
    ticket = task if task and task != "unknown-task" else _ticket_for_stage("S4")
    if not ticket:
        return []
    story = artifact_root() / ticket
    try:
        root = C.cases_root(story)
    except Exception:
        root = C.artifact(story, "test-cases")  # an unreadable config is the default tree, not silence
    if not root.is_dir():
        return []
    cfg = C.case_config(story)
    shared = root != C.artifact(story, "test-cases")
    wrong = []
    for path in sorted_paths(root.rglob("*.md")):
        if any(part in C.CASE_STORE_DIRS for part in path.relative_to(root).parts[:-1]):
            continue
        declared, owner = _case_front(path)
        if not declared or (shared and owner != ticket):
            continue
        if declared != path.stem:
            wrong.append((path, f"{path.name} declares `{declared}`", declared))
        elif not C.is_case_id(declared, cfg=cfg):
            wrong.append((path, f"{path.name} names `{declared}`, which is not a case id in a form recorded here",
                          declared))
    if not wrong:
        return []
    forms = ", ".join(f"`{form}`" for form in C.case_id_forms(story))
    example = C.case_id_example(ticket, story)
    # Each file gets ITS OWN new name: the case number it already carries (the last digits of its id,
    # else of its name), written in the form in force. One shared example sent three bad files to one
    # name, and a file whose id merely was no recognised form kept "the same id" and was refused again.
    taken, listed = set(), []
    for path, said, declared in wrong:
        tail = re.search(r"(\d+)$", declared) or re.search(r"(\d+)$", path.stem)
        number = int(tail.group(1)) if tail else len(taken) + 1
        while C.case_id_example(ticket, story, number) in taken:
            number += 1
        new = C.case_id_example(ticket, story, number)
        taken.add(new)
        listed.append(f"{said} -> `{new}.md` with `id: {new}`")
    return [f"case identity: a case file's `id` is its file name and one case id in a form this project "
            f"records ({forms}; for this story `{example}`) - {len(wrong)} file(s) break that: "
            # every entry is a REPAIR (`<file> -> <new name>`): a file past the sixth would lose its new name, so none
            # is cut here; the record's own ceiling and file (`_render_saved`) bound a long one
            + DV.joined(listed, noun="file", max_chars=None)
            + ". Way on: write each case again under the name shown for it (its own number, in the form "
            "in force) with `id:` equal to that name (the orchestrator removes the stray file); or, if "
            "this project's own ids look like that, `config.case_id_form` records the form (the person "
            "or qa-onboarding writes it). A person's word passes this check"]


SUMMARY_NOTE = "matched the old detector record (kept for one release)"


def _pass_by(record, words: list, pipeline: dict, stage: str):
    """The entry `waiver.split_overridden` makes when one of `words` passes `record`, else None. The matching
    is that function's alone; this gate has no second matcher."""
    from waiver import split_overridden
    _blocking, passed = split_overridden([record], {**pipeline, "stage_overrides": words}, stage)
    return passed[0] if passed else None


def _through_summaries(records: list, named: list, pipeline: dict, stage: str, blocking: list, passed: list) -> None:
    """Rule 4 of `judge_words`, for one release: a named word that matches no real record of a detector but
    matches that detector's old summary record passes the detector's plain records (`words="gate"`, a finding or
    a defect), as it passed the whole detector before the list was split. Moves records from `blocking` to
    `passed` in place."""
    for summary in (r for r in records if getattr(r, "kind", "") == "summary"):
        mine = [r for r in records if getattr(r, "script", "") == summary.script and r is not summary]
        for word in named:
            if any(_pass_by(r, [word], pipeline, stage) for r in mine):
                continue            # the word names a record: it was judged there
            hit = _pass_by(summary, [word], pipeline, stage)
            ride = [r for r in blocking if getattr(r, "script", "") == summary.script
                    and getattr(r, "words", "gate") == "gate" and getattr(r, "kind", "finding") in ("finding", "defect")
                    and not getattr(r, "refused", "")]         # rule 2 above rule 4: a refusal passes through no summary
            if hit and ride:
                blocking[:] = [b for b in blocking if all(b is not r for r in ride)]
                passed += [{"error": r, "decision": hit["decision"], "at": hit.get("at"), "note": SUMMARY_NOTE}
                           for r in ride]


# The finding tags whose finding WAITS for a person's word that the source reads by IDENTIFIER (`s5_precheck`:
# `then-remainder-unrecorded-<n>`, satisfied by `then handed: <case>#<n>`). The source prints no refusal line for them
# (a line would say "refused to every word", which is not so), yet the gate must not read one as `*`-passable: the
# source already judged every recorded word over it, and a finding that still stands is one no word names. The tag is
# the contract's constant (`contract.THEN_REMAINDER_WAITS`, the one spelling `s5_precheck` builds its ids from).
WAITING_FINDING_TAGS = (C.THEN_REMAINDER_WAITS,)


def _finding_tag_of(record) -> str:
    """The tag of a finding record, read from the id in its label (`[<check> <id>]`, the contract's own structure in
    `detector_verdict.LABEL_RE`, and `<check>:<case>:<tag>` the way `s5_precheck._finding_tag` splits it), else `""`."""
    text, script = str(record), getattr(record, "script", "")
    body = text[len(script) + 2:] if script and text.startswith(script + ": ") else text
    label = DV.LABEL_RE.match(body)
    parts = label.group(2).split(":", 2) if label else []
    return parts[2] if len(parts) > 2 else ""


def word_class(record) -> str:
    """The class of a record by the rule `judge_words` applies, read from its FIELDS (FR-12), the ONE place the rule
    lives (`story_step._gate_refusal` names a door by it): `"refused"` when the record carries the source's refusal tag
    (no word opens it, `*` included) OR is a finding that waits for a word the source reads by identifier
    (`WAITING_FINDING_TAGS`: an unnamed Then remainder - `*` never names a Then, and a named word is judged at the
    source, not here), `"star"` when it was judged at its own source (`words="source"`) or is `unmigrated` (only the
    word `*` opens it), `"named_only"` for an `unreadable` record (RH1-5, owner's word 27.10 F-5: only a word that
    names `<script>: unreadable` opens it - `*` and the bare `unreadable` do not), else `"named"` (a named word opens
    it, judged by `split_overridden`). The `refused` rule stays FIRST: an `unmigrated` record whose cause is the
    word `unreadable` (a text that cannot be split, `detector_verdict.UNREADABLE`) is `"refused"`, not `named_only`
    - the two meanings of the word never meet (E25)."""
    if getattr(record, "refused", ""):
        return "refused"
    if getattr(record, "kind", "") == "unreadable":
        return "named_only"
    if getattr(record, "words", "gate") == "source" and _finding_tag_of(record).startswith(WAITING_FINDING_TAGS):
        return "refused"
    if getattr(record, "words", "gate") == "source" or getattr(record, "kind", "") == "unmigrated":
        return "star"
    return "named"


def judge_words(records: list, pipeline: dict, stage: str) -> tuple[list, list]:
    """`(blocking, passed by a person's word)` for the gate's records, judging each by the rule of whoever
    produced it. The matching of a word with a text is `waiver.split_overridden`'s alone. Each record is judged
    by the first rule that applies to it:

    1. a summary record (the pre-C2-1 text of a detector, kept one release) never blocks and is shown to no one;
    2. a record whose findings a producer judged at its own source (`words="source"`), and a record of output
       that is not in the contract's form (`unmigrated`, whose items cannot be told apart), is never passed by a
       NAMED word - the producer already judged every recorded word over it, or one word would pass all of it.
       The word `*` (the person's "all of it") passes it, EXCEPT a record that carries the source's refusal tag
       (`refused`): what the source refused to every word, `*` included, is checked FIRST and no word opens - and
       so is a finding that waits at the source for a word it reads by identifier (`WAITING_FINDING_TAGS`, `word_class`);
    3. every other record (`words="gate"`: a finding or a defect) is judged by `split_overridden` alone, as before;
    4. for one release a named word that matches no record of a detector but matches its old summary passes the
       detector's rule-3 records (`_through_summaries`); rule 2 stands above this one."""
    pipeline = pipeline or {}
    words = [w for w in pipeline.get("stage_overrides") or [] if isinstance(w, dict)]
    stars = [w for w in words if w.get("match") == "*"]
    named = [w for w in words if w.get("match") != "*"]
    blocking, passed = [], []
    for record in records:
        if getattr(record, "kind", "finding") == "summary":
            continue
        kind = word_class(record)
        if kind == "refused":
            blocking.append(record)
            continue
        if kind == "named_only":
            # RH1-5: the word must NAME this script's `unreadable` in full; `*`, the bare `unreadable` and a part of
            # the script name open nothing. Direction: it can only ask for a word, never open without one.
            wanted = f"{record.script}: unreadable"
            hit = _pass_by(record, [w for w in named if wanted.lower() in str(w.get("match") or "").lower()],
                           pipeline, stage)
        else:
            hit = _pass_by(record, stars if kind == "star" else words, pipeline, stage)
        if hit:
            passed.append(hit)
        else:
            blocking.append(record)
    _through_summaries(records, named, pipeline, stage, blocking, passed)
    return blocking, passed


def all_errors(agent: str, task: str, digest: str = "", facts_text: str = "") -> tuple[list, list]:
    """(blocking, passed over by a person's word). No block in the factory is one a person
    cannot pass: a check exists to stop a silent pass, not an informed decision.

    `digest` is the role's own last word, and the gate judges it twice. Its SHAPE: the
    orchestrator's context receives it whole and carries it for the rest of the story, so a
    final message that is not the handoff form is refused once, with the form quoted (the
    five roles of 2026-09-22 ended in 786-3,401 characters of prose each, and the
    orchestrator compacted mid-S5). And its VERDICT: a `halt`/`impossible` one is exempt from
    the missing-output error, whose own text tells the role to "hand the orchestrator a halt
    with the reason instead of an incomplete handoff" — the scout's three charter halts all
    fire before the step that writes the manifest, so the gate refused the very handoff it
    asked for and the story could not be halted at all (0.7.7 review, finding A-F4).

    `facts_text` is what the identity decision read (`_identity`'s `scope["identity_facts"]`), for the header of an
    audit of a stop that named no story."""
    errors = scoped_errors(agent, task, facts_text) + detector_errors(agent, task) + witness_errors(agent, task)
    errors += grounding_errors(agent, task) + case_identity_errors(agent, task)
    errors += digest_errors(agent, task, digest)
    if not is_halting_handoff(digest):
        errors += required_outputs_errors(agent, task)
    if not errors:
        # nothing blocks: the advisers run and write the advice file for THE NAMED story (GW1-10); what an adviser refuses
        # and is not advice (E-X2-2c) is judged below like any other block
        refused = run_advisers(agent, task)
        if not refused:
            return [], []
        errors = refused
    try:
        blocking, passed = judge_words(errors, _task_pipeline(agent, task), _stage_id(agent, task))
    except Exception:
        # a summary never blocks and is shown to no one, whatever the outcome (rule 1)
        blocking, passed = [e for e in errors if getattr(e, "kind", "finding") != "summary"], []
    if not blocking:                        # a person's word passed every block: the same as a clean stop
        late = run_advisers(agent, task)
        if late:
            try:
                blocking, more = judge_words(late, _task_pipeline(agent, task), _stage_id(agent, task))
            except Exception:
                blocking, more = [e for e in late if getattr(e, "kind", "finding") != "summary"], []
            passed = list(passed) + list(more)
    return blocking, passed


def journal_gate(session: str, event: str, notes: str, scope: dict | None = None) -> None:
    """Every block and every break-glass leaves a trace in the journal.

    Lesson of the first live run: blocks were not journaled — a wave of three
    unsafe_completion events looked sudden, although each agent before it had
    silently lost two block-retries."""
    import hooklib
    rec = {
        "event": event,
        "agent": "exit_gate",
        "notes": notes,
        "session": session,
    }
    if scope:
        rec.update({k: scope[k] for k in ("task", "dispatch", "attempt", "hook", "input_fingerprint")})
    hooklib.append_journal_line(None, rec)      # N8: ONE journal-line writer (stamp, seeded flag, path), shared with person_signal


def _is_unreadable(record) -> bool:
    return getattr(record, "kind", "") == "unreadable"


def _unreadable_stop(event: dict, scope_key: str, scope: dict, agent_name: str, task: str, texts: list, why: str) -> None:
    """The hook's road for a gate that could not decide (D13, N4, N5; RH1-5, P1/P22): the person gets the signal
    `gate_unreadable`, the receipt says `unreadable` (not `blocked`/`incomplete`: the fuse does not hold it and `finish`
    reads the checks again and refuses), and the hook exits 0 - the role is NOT woken for a defect it cannot fix. A
    receipt that cannot be written must not turn exit 0 into a failure: the signal is the trace."""
    import hooklib
    hooklib.person_signal(event, "gate_unreadable", f"exit_gate: unreadable - {why} for {agent_name}", task=task or None)
    try:
        _record(scope_key, scope, "unreadable", [str(t) for t in texts])
    except Exception:
        pass


def main() -> None:
    event = read_event() or {}
    from host_probe import is_probe_child
    if is_probe_child(project_root(event), event):
        # The child of the doctor's context probe (RN1-1) is no stage role: no form and no digest to demand, no story
        # artifacts to accept. ONE predicate (the binding route or the probe's own mark, tied to the same launch); a child
        # that is not the probe is judged below, as before; no `gate_block`, no receipt.
        sys.exit(0)
    if not subagent_type(event):
        # a harness service request with no agent type — the exit gate does not apply to it
        sys.exit(0)
    session = event.get("session_id", "unknown")
    # Namespaced by the harness (`qa-factory:qa-doc-scribe`); every gate below looks the
    # role up in stages.json / the witness and detector maps, all keyed by the bare name.
    agent_name = role_name(event.get("agent_type") or event.get("agent_name") or "")
    scope_key, scope = _identity(event, agent_name)
    if scope.get("exploration_rejected"):
        # A stop whose `explore:` id names no exploration that exists (folder removed, table broken between dispatch and stop):
        # no story checks against a non-folder id; ONE signal says what could not be established (FR-59, AR-28).
        import hooklib
        hooklib.person_signal(event, "exploration_stop_unproven",
                              f"exit gate: the stop names {scope['task']} but no such exploration is proven ({scope['exploration_rejected']}); "
                              "it is not judged as a story. Run `explore_step.py frame` for the exploration again, or ignore this stop.",
                              task="", once_key="exploration-stop-" + scope["task"])
        sys.exit(0)
    if scope.get("exploration"):
        # An exploration role's stop is never judged by a story's checks (`awaiting_source_review`, `all_errors`, the fuse): the
        # step's own `check` (the exploration table) says when a step is done, and `set_step` never marks one done without it,
        # so this exit is no pass. No receipt and no `gate_block`: the `subagent_journal` line carries `task: explore:<slug>`.
        sys.exit(0)
    digest = handoff_digest(event)

    # This must precede artifact validation and every detector/quality subprocess. The
    # host is already handling a forced return; a second check would create the loop.
    # The host is already handling a forced return, so this branch NEVER blocks — that is
    # what prevents the loop. It does look once more: TP1-15045 lost three dispatches to
    # a re-entry that released every repaired handoff as `incomplete` without reading it.
    if event.get("stop_hook_active"):
        try:
            if awaiting_source_review(agent_name, scope["task"]):
                _record(scope_key, scope, "awaiting_human")
                print("exit gate: sources are assessed and wait for the person's review")
                sys.exit(0)
            errors, passed = all_errors(agent_name, scope["task"], digest, scope.get("identity_facts", ""))
            if not errors:
                _record(scope_key, scope, "check_passed")
                journal_gate(session, "gate_recheck_passed",
                             "re-entry after a block: artifacts repaired" +
                             (f"; {len(passed)} block(s) passed by the person's word" if passed else ""), scope)
                print("exit gate: repaired handoff re-checked on re-entry and passed")
                sys.exit(0)
            if all(_is_unreadable(e) for e in errors):      # N4 on the re-entry: nothing the role can repair
                _unreadable_stop(event, scope_key, scope, agent_name, scope["task"], errors,
                                 "; ".join(str(e) for e in errors))
                sys.exit(0)
            findings_file = _findings_path(agent_name, scope["task"])
            text, saved_as = _render_saved(errors, findings_file, scope["task"], f"exit gate, {agent_name}, re-entry")
            _record(scope_key, scope, "incomplete", errors, errors_file=saved_as)
            journal_gate(session, "handoff_incomplete",
                         f"re-entry re-checked, {len(_findings(errors))} error(s) remain; first: "
                         + "; ".join(_findings(errors)[:3]), scope)
            print(f"exit gate: handoff remains incomplete after the re-entry check - {len(_findings(errors))} finding(s):\n"
                  + text)
        except SystemExit:
            raise
        except Exception as exc:
            # N5: the re-entry's own crash (the checks, or the receipt) is the third state too: the signal and the
            # receipt, not stderr alone (nobody reads stderr at exit 0)
            crash = f"the gate crashed on the re-entry ({type(exc).__name__}: {exc})"
            _unreadable_stop(event, scope_key, scope, agent_name, scope["task"], [str(unreadable_record("exit_gate", crash))], crash)
            print(f"exit gate: could not persist the incomplete receipt ({type(exc).__name__}: {exc}); handoff is not accepted",
                  file=sys.stderr)
        sys.exit(0)

    previous = _existing(scope_key)
    if previous.get("status") in {"blocked", "incomplete"}:
        try:
            errors = list(previous.get("errors") or ["unresolved completion check"])
            _record(scope_key, scope, "incomplete", errors, total=previous.get("errors_total"),
                    errors_file=str(previous.get("errors_file") or ""))
            journal_gate(session, "handoff_incomplete", "persisted fuse released repeated unchanged input; checks were not run again", scope)
            print("exit gate: unchanged unresolved handoff remains incomplete; persisted fuse released the turn")
        except Exception as exc:
            print(f"exit gate: persisted fuse failed ({type(exc).__name__}: {exc}); handoff is not accepted", file=sys.stderr)
        sys.exit(0)

    task = scope["task"]
    if awaiting_source_review(agent_name, task):
        _record(scope_key, scope, "awaiting_human")
        journal_gate(session, "awaiting_human", "S1 sources assessed; the person's review is next", scope)
        print("exit gate: sources are assessed and wait for the person's review — S1 is not closed")
        sys.exit(0)
    try:
        errors, passed = all_errors(agent_name, task, digest, scope.get("identity_facts", ""))
    except Exception as exc:
        # D13 (RH1-5, F-10): the gate itself crashed. Exit 1 here left SubagentStop unblocked and said nothing; now the
        # receipt says `unreadable` (the way out is the next `finish`: `status` is not in the fuse's set) and the
        # person gets the signal. The hook still exits 0: a crash of the gate stops no role (P1); `finish` and the
        # driver read the same checks again and refuse by exit 2 / Refusal.
        crash = f"the gate crashed ({type(exc).__name__}: {exc})"
        _unreadable_stop(event, scope_key, scope, agent_name, task, [str(unreadable_record("exit_gate", crash))], crash)
        sys.exit(0)
    if is_halting_handoff(digest):
        journal_gate(session, "awaiting_human",
                     "the role handed back a halt; its stage's required outputs are not "
                     "demanded of a halt", scope)
    if passed:
        journal_gate(session, "gate_override",
                     f"{len(passed)} block(s) passed by the person's word; first: " +
                     "; ".join(f"{p['error']} <- \"{p['decision']}\"" + (f" ({p['note']})" if p.get("note") else "")
                               for p in passed[:3]), scope)
    errors = list(errors) + text_end_after_handback(event, agent_name, task)   # HF8-15 (1): the first stop only, never in `all_errors`
    unread = [e for e in errors if _is_unreadable(e)]
    if unread and len(unread) == len(errors):
        # N4: ONLY checks that could not run stand in `blocking`: the role is not woken for them (spec §0: the conductor
        # takes it). The hook text never says "fix every one" over a record that says "not the role's work" (FR-10).
        _unreadable_stop(event, scope_key, scope, agent_name, task, unread, "; ".join(str(e) for e in unread))
        sys.exit(0)
    if unread:
        # a MIXED set (E2): the role is blocked on its own findings only; the unreadable ones are the conductor's
        import hooklib
        hooklib.person_signal(event, "gate_unreadable", "; ".join(str(e) for e in unread), task=task or None)
        errors = [e for e in errors if not _is_unreadable(e)]
    if not errors:
        _record(scope_key, scope, "check_passed")
        # Fail-open: a lookup/print error must not fail a clean handoff pass.
        try:
            hint = next_hint(agent_name)
            if hint:
                print(hint)
        except Exception:
            pass
        sys.exit(0)

    findings_file = _findings_path(agent_name, task)
    text, saved_as = _render_saved(errors, findings_file, task, f"exit gate, {agent_name}")
    rec = _record(scope_key, scope, "blocked", errors, errors_file=saved_as)
    count = int(rec.get("blocks", 1))
    journal_gate(session, "gate_block",
                 f"block {count}/{MAX_BLOCKS}; broken artifacts: {len(_findings(errors))}; first: "
                 + "; ".join(_findings(errors)[:3]), scope)
    print(
        f"HANDOFF BLOCKED by the exit gate - {len(_findings(errors))} finding(s); the gate re-ran the detectors itself "
        "(FB-27: a quoted detector output is not accepted; a failed evidence contract is yours to fix, you still "
        f"have the context). Fix every one and finish again (block {count}/{MAX_BLOCKS}):\n"
        + text +
        "\nIf a broken artifact was NOT created by you (another phase/agent) — do not invent its "
        "content: report the verbatim error list to the orchestrator; the fix belongs to the artifact's author."
        + (f"\nNot yours - {len(unread)} check(s) could not run, the conductor takes them (do not try to repair them): "
           + "; ".join(str(e) for e in unread) if unread else ""),
        file=sys.stderr,
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
