"""driver_dispatch.py - Driver members and names homed here by ai-packages/qa-factory/scripts/tests/fixtures/driver-layers.json (TD-11 cut by tools/source_split.py); no behaviour of its own."""

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
import hooklib
from driver_chains import _CHAIN, ThreadSlot, once_on
from controller import lane_keys
from role_cli import PERSON_MARKER, REPAIR_MARKER
import detector_verdict as DV
import human_text
import no_move as NM
import waiver
from driver_core import HALT_RECORD_WHY, OpenWork, Person, Priced, Refusal, ReworkRefused, _now, _read_answer, _read_json, _sha, _write_json, finding_key
from driver_runner import HANDOFF_FORM
from driver_conductor import PATH_RE


DIGEST_MAX = 1800

# --- the known-refusal table: (name, regex, action) ------------------------------------------

# An action is a word the driver acts on by code. What is not here goes to the conductor;
# a conductor decision that repeats is a candidate row for this table (conductor.jsonl).
S1_REVIEW_RE = r"no person has reviewed the source decisions"

S1_GAP_RE = r"source (?:material )?unavailable and not accepted by a person: (SRC-[0-9a-f]+)"

# `story_step finish` refusing the role's STRUCTURED artifact (controller.py, accept path of a dispatch with
# stage_complete: `S3 structured test plan invalid: ...`; the pattern is every stage's `S<n> structured ...
# invalid`, S3 is the only one the controller words that way today). Not `S1 source collection pending/invalid`.
STRUCTURED_RE = r"story_step: refused - S\d structured .* invalid"

KNOWN_REFUSALS = [
    # FIRST, on purpose: the controller COMMITTED the event and only what comes after it failed (the
    # dashboard, the projection): "event committed; ...; do not repeat the action" and its sibling
    # "event already committed; projection stale; recover, do not repeat action". The door is a
    # command code can run, so the driver runs `recover` itself and goes back to `where` - it never
    # repeats the committed action. The text after "derived view not refreshed (" is whatever
    # exception the render raised, and it may contain words another row reads ("already completed",
    # "expected_revision", "stands in front of gate"); the fact that the event is in the journal is
    # the one that decides. (FR-48, P3: the conductor is called for a problem.)
    # NOTE: its "projection stale" half also matches a `manifest_put.py` commit refusal, whose
    # manifest projection the controller's `recover` does not rebuild; the driver does not run
    # manifest_put today, so no such text reaches this row from here - a run that starts to
    # would need a row of its own.
    # The pattern is the semicolon form every such text shares ("event committed; derived view not refreshed",
    # "event committed; projection stale", "event committed; the step that follows it did not finish",
    # "event already committed; ..."), not a list of what follows it: a refusal that says the event is committed
    # is never answered by repeating the action, whatever the store words after the semicolon.
    ("committed_event", r"event (?:already )?committed;", "recover"),
    # FIRST among the rows a rehearsal finding's words can match (t-211, C9): `match_known` takes the first match
    # over the whole text, and this refusal carries up to four rehearsal findings whose own words can hold the
    # phrase of a row below (`STORY BUDGET`, `expected_revision`) - an earlier row would win and ask a person or
    # retry a finish that is not at fault.
    # `stage_done` refused to RECORD a stage the controller has already accepted (story_step accepts first,
    # then calls stage_done), so there is nothing to retry and nothing for a conductor to run: the driver's own
    # gate-entry step (`gate_repair`) repairs what the rehearsal lists. cmp2, 01.10: two conductor calls per gate
    # stage, $0.11-0.43 each, to say "continue". `handle_refusal` lets this row continue ONLY while the
    # controller's stage is `completed`; a stage still open is the conductor's, as before.
    ("gate_stage", r"stands in front of gate", "continue"),
    # The S9 exit's own report check (`stage_done.s9_exit`, line prefix `report check:`). The report is the
    # factory's own, so the move is code's and never a question (FR-3, FR-42): run `report_facts.py --write`
    # once and record S9 again once; the same refusal a second time is the conductor's (R-S9.1, t-201).
    ("report_check", r"report check:", "rebuild_report"),
    # The scout's planned stop: source decisions wait for the person. Code asks, code records.
    ("s1_review", S1_REVIEW_RE, "s1_review"),
    ("s1_gap", S1_GAP_RE, "s1_gap"),
    ("handoff_form", r"not the handoff form|digest: your final message|names no artifact path", "resume_handoff"),
    # The handover FORM (handoffs/*.yaml), refused by `handoff_check` after it filled in
    # everything it could derive. What is left is the role's own answer, so the role is resumed
    # with the refusal - never the conductor: on TP1-13797 nineteen conductor sessions at S5
    # answered questions of exactly this kind, and the form makes them the role's again.
    ("handover_form", r"the handover form is not complete|handoff_check: .* is not ready"
                      r"|left its handover form untouched", "resume_handoff"),
    # A value outside a field's closed list: the role writes the right word, nobody else can. The
    # refusal carries REPAIR_MARKER too (handoff_check), so this row is the belt and that is the
    # braces - a wording neither of them knows must not land on the person by default.
    ("form_vocabulary", r"is not a value of this field|Write one of:", "resume_handoff"),
    # `story_step finish` refused the role's STRUCTURED artifact (today only `S3 structured test plan invalid:
    # OB-n: ...`, STRUCTURED_RE). Raised AFTER the role stopped, so no resume has happened yet (the three rows
    # above are resumed inside `handoff`, before the refusal exists): the role's OWN session is resumed once with
    # the refusal verbatim, then `finish` runs again. cmp2, 01.10 (F-cmp2-16): four strategists in a row rebuilt
    # the same plan, because the conductor's rework started a new session with the same brief.
    ("structured_artifact", STRUCTURED_RE, "resume_structured"),
    ("missing_output", r"missing required output|HANDOFF BLOCKED|required key .* is missing", "resume_repair"),
    # `story_step start` refused because the task is sequential and a dispatch of it is still
    # in flight. `where` already answers this - `wait_existing_job` on that dispatch - so the
    # move is to ask it again. Measured on TP1-13797 run 5: four conductor sessions, $0.53,
    # and all four came back with the same sentence ("No command run - where already resolves
    # it"), which is what a row here says for nothing.
    ("active_dispatch", r"sequential task already has an active dispatch", "continue"),
    ("story_budget", r"STORY BUDGET", "ask_person"),
    ("executor", r"executor[_ ]unavailable", "ask_person"),
    ("readiness", r"readiness: .*missing|capabilit(y|ies) .*missing|--require", "ask_person"),
    ("stale_revision", r"expected_revision|revision conflict|stale revision|StateConflict: revision", "retry"),
    ("already_done", r"already accepted|stage already completed|already completed|nothing to record", "continue"),
    ("not_in_build", r"is not in this build", "continue"),
    ("s0_receipt", r"no accepted controller stage", "code_only_s0"),
    ("uninitialized", r"initialize task before work", "initialize"),
    ("dead_dispatch", r"wait_existing_job.*(abandoned|never_started|returned)", "recover"),
    ("no_project", r"no qa-factory/config\.json", "error"),
]

WINDOW_ROUND_STAGES = {"S5": "qa-code-critic"}

# TR3-10 D (t-2291, spec t-2174 item 13): the two situations that raise the `walk_account` question (the raise sites are another step's);
# either is dropped from this one tuple, nowhere else. `no_pair`: a lane's role has no recorded login/password pair; `short_distinct`: the
# cases need N distinct accounts of a role and fewer are recorded while the person said they will add accounts.
WALK_ACCOUNT_TRIGGERS = ("no_pair", "short_distinct")


class WindowsUnreadable(ValueError):
    """`Driver.s5_open_windows` could not read the windows, the dispatches or a scope (FR-59): the caller treats that as open, never as a
    close. A ValueError for any reader that catches that; its own name so it is told from a programming error."""


def _mechanical(error: str) -> bool:
    """Is this refusal the role's own to close? The refusal says so itself.

    An earlier version of this matched a list of wordings, which is the same mistake the
    known-refusal table already made once: a check added anywhere phrases itself differently and
    falls through to the person. The marker is what scripts put there deliberately (P6), so the
    only thing to read is the marker.
    """
    return REPAIR_MARKER.lower() in str(error or "").lower()


# --- why a role is resumed, in one line (t-342, B-273) -----------------------------------------------------

# man1 02.10: the S7 analyst was resumed twice and the S8 scribe once - about five minutes of wall in 22 - and the
# driver log said only "witness OK (re-run by the exit gate)". Every resume now names its reason. The classes are the
# factory's OWN refusal families (the rows of `KNOWN_REFUSALS`, reused by name so the two cannot drift, plus the line
# `form_errors` writes), a closed set owned by this code and not a person's or a project's variety (FR-13); a finding
# that matches none is printed as it is, under `unclassified`, so a new family shows up in the log instead of hiding.
KNOWN_PATTERN = {name: pattern for name, pattern, _action in KNOWN_REFUSALS}

RESUME_CLASSES = (
    (KNOWN_PATTERN["handoff_form"], "the role's final message is not the handoff form"),
    (r"^handover form |" + KNOWN_PATTERN["handover_form"], "the handover form is not complete"),
    (KNOWN_PATTERN["form_vocabulary"], "a value of the handover form is outside its closed list"),
    (KNOWN_PATTERN["structured_artifact"], "the controller refused the role's structured artifact"),
    (KNOWN_PATTERN["missing_output"], "a required output of the role is missing"),
)

# The ONE class the driver closes by code instead of resuming (`Driver.assemble_digest`): the exit gate's refusal of
# a final message that is not the handoff form.
FINAL_MESSAGE_FORM_RE = re.compile(r"^digest: your final message is not the handoff form", re.IGNORECASE)


def resume_reason(findings) -> str:
    """One short line naming why a role is resumed, from the findings it is resumed on (a list of lines, or one
    text). Classified findings give their class words, each once, in order; a finding no class knows is quoted
    whole (200 characters) under `unclassified (...)` - with no finding at all the line says so, and is never empty."""
    if isinstance(findings, str):
        findings = [findings]
    lines = [" ".join(str(f).split()) for f in findings or [] if str(f).strip()]
    classes, rest = [], []
    for line in lines:
        for pattern, words in RESUME_CLASSES:
            if re.search(pattern, line, re.IGNORECASE | re.DOTALL | re.MULTILINE):
                if words not in classes:
                    classes.append(words)
                break
        else:
            rest.append(line)
    if rest:
        unknown = f"unclassified ({rest[0][:200]})"
        return "; ".join(classes + [unknown]) if classes else unknown
    return "; ".join(classes) if classes else "unclassified (the exit gate named no finding)"


def parse_next(out: str) -> dict:
    """The `next: {...}` line story_step and controller print."""
    for line in reversed((out or "").splitlines()):
        line = line.strip()
        if line.startswith("next:"):
            try:
                return json.loads(line[len("next:"):].strip())
            except ValueError:
                break
    raise Refusal("no `next:` line in: " + (out or "")[-600:])


READ_BUDGET = object()      # the default of a `budget` argument: none was passed, the repair-limit gate reads the controller's count


def parse_prompt(out: str) -> tuple:
    """(dispatch id, the Agent prompt block) out of `story_step.py start`'s output."""
    match = re.search(r"^dispatched (\S+) \(revision", out or "", re.M)
    dispatch = match.group(1) if match else ""
    lines, inside = [], False
    for line in (out or "").splitlines():
        if line.startswith("--- Agent prompt, verbatim"):
            inside = True
            continue
        if inside and line.startswith("--- the moment the Agent call returns"):
            break
        if inside:
            lines.append(line)
    if not dispatch or not lines:
        raise Refusal("story_step start printed no dispatch and prompt: " + (out or "")[-800:])
    return dispatch, "\n".join(lines).strip()


class DriverDispatch:
    last_dispatch = ThreadSlot("last_dispatch", default="")

    def system_file(self, role: str, dispatch: str, scope: list) -> Path | None:
        """The rule layer inject_context.py delivers on an Agent dispatch: a headless
        `--agent` session has no PreToolUse Agent hook, so the driver hands it over as the
        appended system prompt instead."""
        # RC1-14 step 5 (N5): the driver REFUSES as the hook does, never runs a role with no rule layer (`blocks = []`). Twin of the
        # hook (`inject_context.dispatch`, axis 8): the same kind, the same text, the same denial line, the same packet.
        # State first (S1): the kind comes from THIS dispatch's record; a story with no controller.json is kind `first`.
        import inject_context
        state = self.controller_state()
        if not isinstance(state, dict):
            state = {}
        records = state.get("dispatches")
        record = records.get(dispatch) if isinstance(records, dict) else None
        record = record if isinstance(record, dict) else None
        kind = inject_context.dispatch_kind(record)
        denial_event = {"cwd": str(self.task_root), "tool_input": {"prompt": f"Dispatch id: {dispatch}"}}
        try:
            imap = inject_context.load_map()
            if not imap:
                raise RuntimeError("references/inject-map.json is missing or empty")
            if role not in (imap.get("roles") or {}):
                raise RuntimeError(f"the role {role} has no entry in references/inject-map.json")
            blocks = inject_context.collect_blocks(role, imap, None, kind)
        except ValueError as exc:
            # over budget: the hook's text byte for byte, the hook's denial line (`recover` closes the receipt)
            inject_context.note_denial(denial_event, self.task, None, role, str(exc))
            refusal = Refusal(str(exc), dispatch=dispatch, title="injection_over_budget")
            refusal.known = False
            raise refusal from exc
        except Exception as exc:
            # DIFFERS from the hook, which fails open here (injection is not security-critical): the driver has the conductor
            # seam the hook lacks, so a role is never started with no rules (AR-28, AR-17); the door is the dry run (AR-9)
            text = (f"the injection layer could not be built ({type(exc).__name__}: {exc}); the role was not started; "
                    f"check it with inject_context.py --dry-run --role {role}; the conductor decides a re-run or the person's word")
            inject_context.note_denial(denial_event, self.task, None, role, text)
            refusal = Refusal(text, dispatch=dispatch, title="injection_unbuilt")
            refusal.known = False
            raise refusal from exc
        # t-304 N1 (reader #4): the packet names THIS driver's project and package, resolved now (B-014: the driver's own
        # generation) - the paths the state stored at `initialize` are hints, and a story copied to another worktree kept
        # the old one's. What cannot be resolved is left out with one stderr note (the story is never stopped for it,
        # and never handed the stored paths instead).
        try:
            import runtime_paths
            resolved = runtime_paths.state_paths(state.get("known_paths", {}), self.task_root, project=self.project,
                                                 plugin=self.plugin, python=sys.executable)
            # E10, as the hook: the record's own `known_paths` is resolved the same way and laid over the state's by `task_packet`
            if record is not None and isinstance(record.get("known_paths"), dict) and record["known_paths"]:
                record = dict(record, known_paths=runtime_paths.state_paths(
                    record["known_paths"], self.task_root, project=self.project, plugin=self.plugin, python=sys.executable))
        except Exception as exc:
            # The same line the hook gives (H12): the role is told, the person gets one signal (`inject`) per dispatch.
            resolved = {}
            if record is not None and "known_paths" in record:
                record = dict(record, known_paths={})
            try:
                blocks.append(inject_context.unavailable_block(
                    None, role, "packet-paths",
                    f"the task packet carries no paths: the stored paths could not be resolved ({type(exc).__name__}: {exc}); "
                    f"work from the prompt and name it under blocked"))
            except Exception:
                print(f"note: the stored paths could not be resolved ({type(exc).__name__}: {exc}) - the packet carries none")
        # ONE packet function for the hook and the driver (AR-13): one `known_paths`, the whitelisted `dispatch` with its kind
        packet = inject_context.task_packet(self.task, state, record, resolved, dispatch, role=role, scope=scope)
        blocks.append("\n\n" + inject_context.PACKET_HEADING + " (reuse paths and completed checks)\n" + json.dumps(packet))
        path = self.state_dir / "driver-tmp" / f"{dispatch}.system.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(blocks), encoding="utf-8")
        return path

    # --- the handoff, checked the way the exit gate checks it ------------------------------

    def exit_errors(self, role: str, digest: str, dispatch: str | None = None) -> list:
        """The exit gate's blocking records for the role's handoff. A check that could NOT run (an `unreadable` record, or
        the gate itself raising) is not the role's work: it used to be a line in the list the role was resumed over, a paid
        resume over the factory's own defect (D14, RH1-5). Now it is ONE `Refusal` (title `gate_unreadable`, `known` False,
        so `route_known` returns None and `handle_refusal` gives it to the conductor, who asks the person and files the
        finding). POSITION: inside this function - the one point every call of the gate passes. INVARIANT: no `assemble_digest`,
        no resume of the role and no `shorten_form` runs over an unknown gate; a record the person's named word already
        passed is in `passed`, not in `blocking`, and raises nothing (E17). The author's own findings that stood next to
        the unreadable ones travel in the same refusal, after them (E2)."""
        crash = ""
        try:
            import exit_gate
            # the dispatch being gated is named to the gate (TR3-13): with two windows running the count cannot say which one it is.
            # It is the PARAMETER (`handoff` has the id), never `last_dispatch` (another window's, or none, on a saved or resumed
            # result). The hold wraps `all_errors` ONLY: it is a process global and `handoff` goes on to `run_claude` (t-2087 F1).
            with exit_gate.holding_dispatch(dispatch):
                blocking, _passed = exit_gate.all_errors(role, self.task, digest)
            blocking = list(blocking)
        except Exception as exc:
            blocking, crash = [], f"the exit gate could not run: {type(exc).__name__}: {exc}"
        unreadable = [r for r in blocking if getattr(r, "kind", "") == "unreadable"]
        if not (crash or unreadable):
            return blocking
        others = [r for r in blocking if getattr(r, "kind", "") != "unreadable"]
        lines = [crash] if crash else [str(r) for r in unreadable]
        try:
            import hooklib
            hooklib.person_signal({"cwd": str(self.task_root)}, "gate_unreadable", f"{role}: " + "; ".join(lines),
                                  task=self.task)
        except Exception:
            pass        # the refusal below is the loud part; a signal that cannot be written never hides it
        listing = self.listed(lines + [str(r) for r in others], "", "handoff")[0]
        refusal = Refusal(f"the exit gate of {role} for {self.task} could not run {len(lines)} check(s), so it does not know "
                          "whether the handoff is acceptable - the factory's own defect, not the role's work; the role is NOT "
                          "resumed and the conductor takes it. Unreadable first, the author's own findings (if any) after:\n"
                          + listing, findings=lines + [str(r) for r in others], title="gate_unreadable")
        refusal.known = False
        raise refusal

    def form_errors(self, dispatch: str) -> list:
        """The handover FORM, checked beside the digest so ONE resume asks for both.

        Only the role can answer what is left after `--fix`, and resuming it is what that
        costs - about $0.60, against $0.45 for a conductor session that cannot answer it at
        all. So the form travels in the same refusal as the exit gate's, and the role repairs
        both in the one resume it already gets.
        """
        return self.form_report(dispatch)[1]

    def form_report(self, dispatch: str, *, shorten: bool = False) -> tuple:
        """`(the handoff_check report or None, the form's error lines)`: the ONE reader of the form check in the driver
        (C2-4: `shorten` adds `--shorten`, the driver's own flag - a role's `--fix` never cuts). `None` when there is no form or
        the check printed no JSON."""
        form = self.task_root / "work" / "handoffs" / f"{dispatch}.yaml"
        if not form.is_file():
            return None, []
        code, out = self.py("handoff_check.py", "--file", str(form), "--task", self.task,
                            "--task-root", str(self.task_root), "--fix", *(["--shorten"] if shorten else []), "--json")
        report = hooklib.read_document(out)  # t-2020: `handoff_check --json` prints a PRETTY object (indent=1): the document reader; a stderr warning does not hide it
        if report is None:
            # an answer nobody could read is an unknown, never a pass of the form gate (AR-28, FR-59), exit 0 or not
            return None, [f"handover form: handoff_check gave no readable answer (exit {code}): {((out or '').splitlines() or ['no output'])[-1][:200]}"]
        required = bool((self.config.get("handoffs") or {}).get("required", True))
        if report.get("untouched") and not required:
            return report, []
        for line in report.get("fixed") or []:
            print(f"note: handover form filled by code: {line}")
        return report, [f"handover form {form.name} - {p['path']}: {p['problem']}"
                        for p in report.get("problems") or []]

    def shorten_form(self, role: str, dispatch: str, digest: str, *, assembly_follows: bool = True) -> int:
        """C2-4 (K9): the number of form fields code cut to their limit (`handoff_check.py --shorten`); 0 when nothing was
        cut - no form, an unreadable answer, or a form with a problem beside the length (the role is woken for that one and says
        it shorter itself, P1). A field over its limit is a count, not a judgement; the role's whole text stays in the form's
        `shortened:` section (I1).

        The guard on the DRIVER's side: the exit gate has nothing to say except, WHERE THE ASSEMBLY FOLLOWS (`assembly_follows`,
        the `handoff` entry), that the last message is not the form (`FINAL_MESSAGE_FORM_RE` - `assemble_digest` answers that, by
        code, on the cut form). Where no assembly follows (the ladder point, after the first resume) that line goes to the role
        with the cut form's words: the exit side must be EMPTY, or the cut leaves the role woken over words code shortened
        (t-919 F-2, edge 6). The guard on the CHECK's side is in `handoff_check.shorten`: it cuts only when every problem of the
        form is a length problem. A failure of either only means "not cut" - today's road, the role."""
        exit_side = self.exit_errors(role, digest, dispatch)
        if any(not (assembly_follows and FINAL_MESSAGE_FORM_RE.search(e)) for e in exit_side):
            return 0
        cut = (self.form_report(dispatch, shorten=True)[0] or {}).get("shortened") or []
        if cut:
            print(f"handoff: {dispatch}: {len(cut)} field(s) over their limit cut by code; the whole text is in "
                  f"work/handoffs/{dispatch}.yaml (shortened) - no resume", flush=True)
        return len(cut)

    def digest_of(self, text: str) -> str:
        """The handoff inside the role's last message: from its header line down. A role that
        says one sentence before the header ("time to finalize the digest and stop") would
        otherwise be refused for a preamble it has already ended, and the resume that follows
        costs a full context (TP1-13797, run 3: the critic was resumed six times)."""
        import role_digest
        lines = role_digest._lines(text)
        if not lines:
            return str(text or "").strip()[:DIGEST_MAX]
        start = 0
        for index, line in enumerate(lines):
            header, error = role_digest._parse_header(line)
            if not error and header.get("verdict"):
                start = index
                break
        digest = "\n".join(lines[start:][-40:])
        return digest[:DIGEST_MAX]

    def s1_person(self, role: str, errors: list, digest: str, stage: str, dispatch: str) -> None:
        """The S1 stops that are a person's, never a resume's and never the conductor's: a source gap, a source review. Raises
        `Person`; returns when the scout's finding set holds neither (and for any other role, and for an EMPTY set - nothing to
        ask). Called twice by `handoff`: on the role's own message (before any resume), and again on the set that is left after the
        ladder's resume (t-809 F-2) - a mixed set (a gap beside a review, a gap beside a form line) that survives the resume keeps
        the road it has always had, instead of a `Refusal` that `route_known` sends to the conductor."""
        if role == "qa-scout" and any(re.search(S1_GAP_RE, e, re.IGNORECASE) for e in errors) \
                and not any(re.search(S1_REVIEW_RE, e, re.IGNORECASE) for e in errors):
            raise Person("s1_gap", self.s1_gap_text("; ".join(errors)), stage, dispatch)
        if role == "qa-scout" and any(re.search(S1_REVIEW_RE, e, re.IGNORECASE) for e in errors):
            # The exit gate names the person, not the role: the source review is the stop the
            # scout's procedure plans, and a repair resume or the conductor can only spend
            # money on it (driver run 3: $0.18 resume + $0.37 conductor per stop).
            raise Person("s1_review", self.s1_review_text(digest), stage, dispatch,
                         answer_note=human_text.onboarding_note(self.pipeline().get("environment"), self.config.get("environments")))

    def handoff(self, role: str, stage: str, dispatch: str, result: dict) -> str:
        """The role's last word, in the form. One resume for the form or a repair the exit
        gate names; what is still wrong after that is a refusal for the table or the
        conductor (a person's waiver passes it, as at the real gate)."""
        if result["is_error"] and not result["result"].strip():
            raise Refusal(f"claude -p for {dispatch} failed (exit {result['exit_code']}): {result['stderr']}",
                          dispatch=dispatch)
        self.revoke_passes_of_dead()    # t-781 m4: before `exit_errors` reads the waiver rows - a dead dispatch's pass is not this one's
        digest = self.digest_of(result["result"])
        errors = self.exit_errors(role, digest, dispatch) + self.form_errors(dispatch)
        # N10 (C2-9): a gap by default whose carrier is a collector receipt is collected again at every scout handover, with
        # or without errors - after the person restores a VPN the merge request simply arrives (FR-57: the door of a default).
        if role == "qa-scout" and (errors or self._defaulted_vcs()) and self.close_vcs_gaps(errors):
            # What code can collect, code collects, and it happens before any branch below decides
            # to ask a person or to resume the role: the material the ladder reaches is simply
            # there on the next read of the gate.
            errors = self.exit_errors(role, digest, dispatch) + self.form_errors(dispatch)
        self.s1_person(role, errors, digest, stage, dispatch)
        # C2-4 (K9): a field over its limit is cut by code, not by a paid session (`shorten_form`). POSITION INVARIANT: AFTER the
        # S1 branches (a person's stop never waits for a cut, I5) and BEFORE the assembly and the resume below - a resume for a
        # count is the cost this removes; the cut happens only when length is the form's sole problem, so a set that also holds
        # judgement still wakes the role once, who can say it shorter itself.
        if errors and self.shorten_form(role, dispatch, digest):
            errors = self.exit_errors(role, digest, dispatch) + self.form_errors(dispatch)
        # t-217 / F-cmp2-23 (FR-42, FR-48): the role is resumed ONCE per finding set on one dispatch+session, across
        # entries and relaunches. The saved result is handed to `handoff` again on every entry (`wait_existing_job`),
        # and every entry used to resume the role again over the same findings (eight resumes in cmp2, 04:27-04:34,
        # and a conductor call between each pair). POSITION INVARIANT: after the S1 branches above (a source gap or
        # review is the person's, never a resume) and BEFORE the resume below; the record is written BEFORE the paid
        # call, so a crash costs one resume and never repeats one. A role that has not seen these findings is still
        # resumed once before anyone else is asked.
        # t-342 (B-273, FR-47/P6): when the ONLY thing wrong is that the role's last message is not the handoff form
        # and the form is all there in what the role already wrote (its handover form, its artifact), the driver
        # assembles the digest by code and does not resume the session for one turn. POSITION INVARIANT: after the S1
        # branches (a person's stop is never assembled over) and BEFORE the resume record is read or written - an
        # assembly is not a resume, and a refused one leaves the resume to happen exactly as before. The assembled
        # digest must pass the SAME exit gate and form check the role's own message would have (all errors gone, or it
        # is not used); anything else wrong beside the digest is the role's to repair, so no assembly is tried then.
        not_assembled = ""
        if errors and all(FINAL_MESSAGE_FORM_RE.search(e) for e in errors):
            assembled, not_assembled = self.assemble_digest(role, stage, dispatch, result)
            if assembled:
                left = self.exit_errors(role, assembled, dispatch) + self.form_errors(dispatch)
                if not left:
                    self.keep_assembled_result(dispatch, result, assembled)
                    print(f"handoff: {dispatch}: the role's final message is not the handoff form; the form is "
                          "assembled by code from its handover form and its artifact (assembled_by: code) - no resume",
                          flush=True)
                    return assembled
                not_assembled = "the assembled form still fails the exit gate: " + " ".join(left[0].split())[:160]
        return self.handoff_ladder(role, stage, dispatch, result, digest, errors, not_assembled)

    def saved_result(self, dispatch: str) -> dict:
        """The dispatch's saved result (`state/driver-runs/<dispatch>.json`): what a resume wrote, {} when there is none."""
        found = _read_json(self.state_dir / "driver-runs" / f"{dispatch}.json")
        return found if isinstance(found, dict) else {}

    EXIT_ASK_HEADS = {"handoff": "The exit gate refused your handoff",
                      "refusal": "The factory refused to close your dispatch",
                      "structured": "The factory refused the structured artifact you handed over"}

    def listed(self, lines: list, dispatch: str, name: str, *, noun: str = "finding") -> tuple:
        """`(the list as a role reads it, whether it was cut, why the whole list is NOT in a file)`: ONE call of
        `detector_verdict.render` - every line whole up to its byte ceiling, past it a count and the path of the file that holds
        the whole list, `state/findings/<dispatch>-<name>.txt` (written by that very call, FR-37). A file left by an earlier call is
        removed first (as `exit_gate._render_saved` does), so a file that exists afterwards is this call's. The third value is `""`
        when nothing was cut or the file was written; else the clause a head may state in place of a promise (`the list is cut at
        N; the whole list could not be saved: <reason>` - a dry run, a blank dispatch or a failed write, FR-10/FR-41). No count of
        lines is a ceiling anywhere (C2-1): the text is the whole list or says where the rest is."""
        lines = [str(line) for line in lines]
        path = None if self.dry or not dispatch else self.state_dir / "findings" / f"{dispatch}-{name}.txt"
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        shown, cut = DV.fit(lines)
        text = DV.render(lines, full_path=path, noun=noun, source=f"driver, dispatch {dispatch or 'unknown'}")
        was_cut = bool(cut or len(shown) < len(lines))
        if not was_cut or (path is not None and path.is_file()):
            return text, was_cut, ""
        reason = ("this is a dry run, which writes no file" if self.dry else "the dispatch has no name" if not dispatch
                  else "the file could not be written")
        return text, True, f"the list is cut at {len(shown)}; the whole list could not be saved: {reason}"

    def exit_ask(self, role: str, dispatch: str, errors: list, *, why: str = "handoff") -> str:
        """The words a role is resumed with over the exit gate's refusal: ALL the lines, what code filled in its form, what code
        fetched while the boundary ran, and what to do. ONE text for the handoff's free resume and for the person's paid
        `round` (t-764: a second copy would drift). `why`: the road that reached the seam - the head names the REAL refusal
        (t-781 m5: a finish refusal or a structured-artifact refusal is not "the exit gate refused your handoff"); an unknown
        `why` keeps the handoff's head. The lines go through `listed` (C2-1): the count, every line, and past the byte ceiling the
        file that holds the rest - never the first eight of N."""
        filled = (self.state.get("form_filled") or {}).get(dispatch) or []
        # F14 (E16): a role whose file lists no Bash is never told to run a script - it edits the form with its Edit tool
        seen_fix = ("set it yourself with `handoff_check.py --file <form> --set <path>=<value>`." if self.role_has_bash(role)
                    else f"correct it in work/handoffs/{dispatch}.yaml with your Edit tool (the exit check runs by itself when "
                         "you hand off; its refusal comes back in this session).")
        seen = ("\n\nCode filled these fields of your form from the artifacts they come from, so "
                "you do not retype them. Read them: if one is wrong for your work, "
                + seen_fix + "\n"
                + self.listed(filled, dispatch, "filled", noun="line")[0]) if filled else ""
        got = [line for lines in (self.state.get("collected") or {}).values() for line in lines]
        arrived = ("\n\nWhile this boundary ran, code fetched this material through the factory's "
                   "own authenticated route — it is on disk now; what it means for the story is "
                   "yours to read and say:\n" + self.listed(got, dispatch, "collected", noun="line")[0]
                   ) if got and role == "qa-scout" else ""
        shown, cut, unsaved = self.listed(errors, dispatch, "handoff")
        # the head promises the file ONLY when the file was written (t-809 F-1, FR-10/FR-41): a list cut with no file says so
        reach = unsaved or "they are all listed here" + (" (the rest in the file named at the end of the list)" if cut else "")
        return (self.EXIT_ASK_HEADS.get(why, self.EXIT_ASK_HEADS["handoff"]) + f": {len(errors)} finding(s). Repair every one of "
                "them in this turn - " + reach
                + ":\n" + shown + arrived + seen +
                "\nRepair what it names in the artifact you wrote (never another role's file), "
                "and fill every `handover form` line in work/handoffs/" + dispatch + ".yaml - "
                "the values it names are the only ones your role may write, and what you cannot "
                "fill goes under `blocked`. Then print your handoff in the exact form and "
                "nothing else:\n" + HANDOFF_FORM)

    def handoff_ladder(self, role: str, stage: str, dispatch: str, result: dict, digest: str, errors: list,
                       not_assembled: str) -> str:
        """The resume ladder of `handoff` (t-764 A13: extracted, its body unchanged but for the first branch): a new finding set
        is resumed once (and once more when every error is mechanical); a set the role has already seen, or a role with no
        session, goes to the ONE seam `exit_limit` (the person is asked; a round the person bought is spent there and the
        role's new result is judged again); what is still wrong after the ladder is a `Refusal`."""
        resume_sid = self.refusal_sid(dispatch, result["session_id"])
        resume_key = finding_key(errors) if errors else ""
        if errors and (not result["session_id"] or (resume_key and resume_key in self.resume_record(dispatch, resume_sid))):
            if result["session_id"]:
                print(f"{stage}: {dispatch} was already resumed on these findings; no second resume")
            self.exit_limit(stage, role, dispatch, self.refusal_lines(None, items=errors), sid=result["session_id"] or "", why="handoff",
                            digest=digest)
            return self.handoff(role, stage, dispatch, self.saved_result(dispatch))
        elif errors and result["session_id"]:
            if resume_key:
                self.note_resume(dispatch, resume_sid, resume_key, "handoff")
            ask = self.exit_ask(role, dispatch, errors)
            again = self.run_claude("role", ask, role=role, dispatch=dispatch, stage=stage,
                                    resume=result["session_id"],
                                    resume_reason=resume_reason(errors)
                                    + (f" (not assembled by code: {not_assembled})" if not_assembled else ""))
            if again["result"].strip():
                digest = self.digest_of(again["result"])
                self.keep_resumed_result(dispatch, again, result)
            errors = self.exit_errors(role, digest, dispatch) + self.form_errors(dispatch)
            # C2-4 (K9), POSITION INVARIANT: between the first resume's recompute and the third resume's condition - the third
            # resume is never spent on a length (a count code makes), and a set the cut empties returns the digest below.
            if errors and self.shorten_form(role, dispatch, digest, assembly_follows=False):
                errors = self.exit_errors(role, digest, dispatch) + self.form_errors(dispatch)
            if errors and all(_mechanical(e) for e in errors):
                # A second and last resume, and this one SHOWS the line instead of describing it.
                # TP1-13797, 26.09: after one resume the critic still had two reasons of 81 and
                # 84 characters and an unfilled receipt path — mechanical to the last character —
                # and the refusal went to the conductor ($0.99) and then to the person, who can fix
                # none of it. One more cheap turn at the role is the right move; if it fails too,
                # the refusal travels as before. (The lengths no longer reach here: C2-4 cuts them above; cmp3
                # showed this turn spent on the receipt-binding lines, which are judgement.)
                # F14 (E16): no Bash in the role's file -> its Edit tool, never a script it cannot run
                how = (f"Your handoff form: fix exactly these {len(errors)} line(s), one field at a time, with "
                       "`handoff_check.py --file work/handoffs/" + dispatch + ".yaml --set <path>=<value>` (never rewrite the file):\n"
                       if self.role_has_bash(role) else
                       f"Your handoff form work/handoffs/{dispatch}.yaml: fix exactly these {len(errors)} line(s) with your Edit "
                       "tool, one field at a time (never rewrite the file):\n")
                exact = ("Two things and nothing else. 1) " + how
                         + self.listed(errors, dispatch, "handoff")[0]
                         + "\n2) Then print your digest, in the form, and nothing else:\n" + HANDOFF_FORM)
                third = self.run_claude("role", exact, role=role, dispatch=dispatch, stage=stage,
                                        resume=again.get("session_id") or result["session_id"],
                                        resume_reason="still not repaired after one resume: " + resume_reason(errors))
                if third["result"].strip():
                    digest = self.digest_of(third["result"])
                    self.keep_resumed_result(dispatch, third, again if again["result"].strip() else result)
                errors = self.exit_errors(role, digest, dispatch) + self.form_errors(dispatch)
        # t-809 F-2: the S1 person branches are evaluated AGAIN on the set the resume left (POSITION INVARIANT: after the
        # resume's recompute, BEFORE the `Refusal` - a scout's source gap or review that survives it is the person's, so a mixed
        # set keeps `s1_gap` / `s1_review`; an empty set raises nothing and returns the digest)
        self.s1_person(role, errors, digest, stage, dispatch)
        if errors:
            raise Refusal(f"exit gate for {dispatch} ({role}, {stage}): {len(errors)} finding(s):\n"
                          + self.listed(errors, dispatch, "handoff")[0],
                          files=[str(self.task_root)], dispatch=dispatch, findings=errors)
        return digest

    # --- one role, start to finish ---------------------------------------------------------

    def run_role(self, stage: str, role: str, *, scope=None, extra=(), complete=None, purpose="",
                 rework: dict | None = None, budget=READ_BUDGET, after=None) -> tuple:
        """start -> claude -p -> bind -> handoff -> finish. Returns (digest, next action).
        `complete`: None = the stage's own rule (its last role closes it), True/False forces.
        `rework`: an already-registered rework dispatch {id, scope, reason} instead of `start`.
        `budget`: the repair budget the S5 loop read for this review, handed to the repair-limit gate as it is (t-729 F2).
        `after`: `after(dispatch, result)`, code that runs once the role is over (t-1957 N5s, E5s.1/E5s.2). POSITION INVARIANT: after the result
        exists (fresh or reused; `{}` when the role crashed or raised) and BEFORE `bind`, `handoff`, `question_threshold`, `repair_limit_gate`
        and `finish`, so the dispatch is still `running` when it writes the records the exit check and `finish` read. A `finally`: a role
        that crashes, is refused or returns nothing still gets its `after`. `None` = the run as it was."""
        stages = self.stages()
        scope = [s for s in (scope or []) if s]
        if rework:
            dispatch = rework["id"]
            import story_step
            # A rework dispatch gets its brief too (files, commands, the person's words);
            # without it the role searches, and the plugin is closed to it.
            form_file = self.task_root / story_step.FORM_REL.format(dispatch_id=dispatch)
            card_file = story_step.launch_card.card_path(self.task_root, dispatch)
            if not form_file.is_file() or not card_file.is_file():
                # F1 (B-7, AR-14): the ONE writer of brief + form + card; `keep` never overwrites a file the role may have filled.
                # A differing card is one note and the role still runs (P1: the prompt carries everything).
                try:
                    story_step._write_dispatch_files(self.task, stage, role, dispatch, self.task_root,
                                                     ",".join(rework.get("scope") or scope), [], keep=True)
                except ValueError as exc:
                    print(f"note: {exc}")
                brief = story_step._project_rel(self.task, story_step.BRIEF_REL, dispatch)
            else:
                brief, note = story_step._brief(self.task, stage, role, dispatch, self.task_root)
                if note:
                    print(f"note: {note}")
            # `line` is the whole line when the caller has one (a dispatch continued after an
            # infrastructure interruption is NOT a rework, and saying "Rework reason" would tell the
            # role its work was refused); `reason` is the rework's own.
            prompt = story_step._prompt(self.task, stages[stage], role, dispatch,
                                        [rework.get("line") or f"Rework reason: {rework.get('reason') or ''}"], brief)
        else:
            # TR3-6: POSITION - before `start`; INVARIANT: a drain registers no new dispatch (a chain that gets here while another raised stops)
            self.stop_if_drained()
            self.count_launch()
            args = ["start", "--task", self.task, "--stage", stage, "--role", role]
            if scope:
                args += ["--scope", ",".join(scope)]
            if purpose:
                args += ["--purpose", purpose]
            if stage == "S6" and role == "qa-runner":
                # S6 is two packets: this call runs the automated half (the manual-agent one
                # goes through run_manual_block, which registers its own dispatch).
                args += ["--execution-kind", "automation"]
            if self.on_chain():
                args.append("--parallel-window")        # only the scheduler's chains ask the controller to admit a window beside another
            with self.timed("start", stage=stage) as lap:         # t-1937 P2-1; the dispatch is known once `start` has answered
                if self.on_chain() and role == "qa-code-critic":
                    # a critic's `start` settles its probe debt (up to 90 s): not under `_book`, one settle at a time
                    # F2: the settle mutates test files in place, so for its length the chain counts as RUNNING to the launch gate
                    # (`chain_overlap_running`): a sibling's session on a file of this window waits for it, and is woken at the end
                    record = getattr(_CHAIN, "record", None)
                    record.running = True
                    try:
                        with self.unbooked(settling=True):
                            out = self.step(*args)
                    finally:
                        record.running = False
                        self._cond.notify_all()
                else:
                    out = self.step(*args)
                dispatch, prompt = parse_prompt(out)
                lap.dispatch = dispatch
            import driver_timing
            for part, seconds in driver_timing.parse_lines(out):    # `start`'s own sub-steps: one reader, never printed raw
                self.timing_write(part, seconds, dispatch=dispatch, stage=stage)
            for line in out.splitlines():
                if line.startswith("note:"):
                    print(line)
        self.boundary = f"{stage}:{dispatch}"
        saved = self.state_dir / "driver-runs" / f"{dispatch}.json"
        result = _read_json(saved) if saved.is_file() else {}
        if result.get("result") and self.retire_infra_result(saved, result, role=role, stage=stage, dispatch=dispatch):
            result = {}      # an infrastructure failure saved by an older driver is not a result to reuse
        if after is None:
            # t-2016 F4: the walk hook has ONE site, this one, whoever called: a dispatch with a walk record (`state/walks/<dispatch>.json`) gets
            # its session reopened when it is not ready (a continuation after an infrastructure cut, a launch that never happened) and the
            # same `after` the first launch had. A dispatch with no record is not a walk: `after` stays None and nothing here ran.
            # t-2022 N7: a saved result stands = no role runs = nothing is reopened (the saved result is read FIRST); `after` still runs
            lane, reopened = self.walk_reopen(dispatch, reopen=not result.get("result"))
            if lane:
                after = lambda d, r, lane=lane: self.walk_after(lane, d, r)     # noqa: E731
            elif dispatch in once_on(self, "survey_reopened", set):
                after = self.survey_after       # t-2548 F1 (AR-25): a survey session reopened just above has no lane, but it is closed when the role ends
            if reopened:        # a survey walk has no lane (no `after` of a case) but its reopened session is told to the role (batch 2b D)
                extra = [*extra, reopened]
        # t-1991 U3b (the ONE join point of every S7 triage dispatch; an investigation gets neither): the walk session opens only when the
        # role will run (no saved result) and BEFORE the lines, which name the session or why there is none; it closes in the `finally` below.
        triage = self.s7_is_triage(stage, role, dispatch, purpose)
        opened = triage and not result.get("result") and self.s7_settle_session(dispatch)
        lines = [prompt]
        if scope:
            lines.append("Dispatch scope (one digest line per item): " + ", ".join(scope))
        if triage:
            lines += self.s7_place_lines(dispatch)         # E3b.1: the ONE site, before `extra`; fresh, scribe-reject and seam rework alike
            lines += self.s7_neighbour_lines(dispatch)     # t-2187 N6: the neighbourhood hint, beside the place lines, the same triage dispatches
        lines += list(extra)
        lines.append(f"Plugin root: {self.plugin} — factory scripts are `python {self.scripts}/<name>.py`; "
                     "the rule layer is in your system prompt, do not read the plugin's files.")
        lines.append("Your final message is the handoff form only:\n" + HANDOFF_FORM)
        full_prompt = "\n".join(lines)
        try:
            if not result.get("result"):
                print(f"[{stage}] {role} → {dispatch}" + (f" scope={','.join(scope)}" if scope else ""))
                self.progress_line()
                result = self.run_claude("role", full_prompt, role=role, dispatch=dispatch, stage=stage,
                                         system_file=self.system_file(role, dispatch, scope))
                _write_json(saved, result)
            else:
                print(f"[{stage}] {dispatch}: reusing the saved result of session {result.get('session_id')}")
        finally:
            if opened:
                self.s7_settle_close(dispatch)          # E3b.2: a role that crashes or is refused leaves no session behind
            if after is not None:
                after(dispatch, result)
        if result["session_id"]:
            with self.timed("bind", dispatch, stage):
                code, out = self.py("story_step.py", "bind", "--task", self.task, "--dispatch-id", dispatch,
                                    "--agent-id", result["session_id"])
            if code and not rework:
                raise Refusal(f"story_step bind (exit {code}):\n{out}", dispatch=dispatch)
        self.last_dispatch = dispatch     # the S5 loop reads this critic's typed form (B-007)
        # CX1-14 (F-2 (b)): ONE reader of a declared halt, `story_step._declared_halt`, called twice. BEFORE `handoff`,
        # the FORM alone: a role that wrote `header.verdict: halt` and ended on a message that is not the form is heard
        # without paying the resume `handoff` would spend on it. POSITION INVARIANT (B-1): the scout (S1) is skipped
        # here - its source gaps and reviews (`close_vcs_gaps`, `s1_person`, D-0043) run INSIDE `handoff` and must
        # speak before any generic halt - and a dead run (an error with no words) stays `handoff`'s Refusal. AFTER
        # `handoff`, form + digest for every role, scout included, which covers a halt that arrives after a resume.
        # Both before `question_threshold` and `finish` (t-113 B2).
        import story_step
        form_rel = story_step.FORM_REL.format(dispatch_id=dispatch)
        dead = bool(result["is_error"]) and not result["result"].strip()
        early = role != "qa-scout" and not dead and story_step._declared_halt(self.task_root, form_rel, "")
        if early:
            digest = self.digest_of(result["result"])
        else:
            with self.timed("handoff", dispatch, stage):
                digest = self.handoff(role, stage, dispatch, result)
        if early or story_step._declared_halt(self.task_root, form_rel, digest):
            # O1 (C1-7c, kind T as T1): the halt reaches the person either way (the Person below is raised whatever the write did) and
            # the role is NOT run again; a failed write is journalled as `trace_failed` and the story goes on to the halt's question
            self.py_trace("stage_done.py", "--task", self.task, "--stage", stage, "--status", "halted", "--role", role, "--digest", digest,
                          why=HALT_RECORD_WHY)
            raise Person("halt", self.halt_text(stage, role, digest), stage, dispatch,
                         details=str(digest or "").strip() or "the role's final message was empty")
        if role == "qa-scout" and re.search(r"\bS1\s+review\b", digest):
            raise Person("s1_review", self.s1_review_text(digest), stage, dispatch,
                         answer_note=human_text.onboarding_note(self.pipeline().get("environment"), self.config.get("environments")))
        # POSITION INVARIANT (t-113 B2, R15): after the halting check above, so a role that stopped
        # on its own is asked once by the `halt` road and never twice, and BEFORE `finish`, so the
        # stage cannot be closed over the very questions the person has not yet seen.
        self.question_threshold(stage, role, dispatch)
        # POSITION INVARIANT (t-698 A4): after the threshold and BEFORE `finish`, so a window is never closed over a repair limit,
        # an uncounted budget or a rejection nobody can repair that the person has not answered for this critic dispatch.
        self.repair_limit_gate(stage, role, dispatch, digest, scope or None, budget=budget)
        finished = self.finish(dispatch, digest, complete=complete, role=role, stage=stage)
        self.progress_line()            # the role returned and its work is recorded: where the story stands now
        return finished

    def finish(self, dispatch: str, digest: str, *, complete, role: str, stage: str) -> tuple:
        """`complete` may be a callable of the digest: the critic's verdict decides whether
        its finish closes the stage, and the verdict is known only here."""
        if callable(complete):
            complete = complete(digest)
        # A window the critic could not close: `(word, reason)` (t-201). A tuple is truthy and means
        # complete, so it can never be `--not-complete`; a word or a reason that is empty (or not text)
        # is no pair at all and the finish is today's plain `--complete`.
        unresolved, given, open_pair = (), complete, ()
        if isinstance(complete, OpenWork):      # BEFORE the tuple branch: an OpenWork is "not complete, with this pair"
            pair = tuple(x.strip() if isinstance(x, str) else "" for x in (complete.unresolved, complete.reason))
            open_pair = pair if all(pair) else ()
            complete = False
        elif isinstance(complete, tuple):
            pair = tuple(x.strip() if isinstance(x, str) else "" for x in (list(complete) + ["", ""])[:2])
            unresolved = pair if all(pair) else ()
            complete = True
        args = ["finish", "--task", self.task, "--dispatch-id", dispatch, "--digest", digest]
        window_gaps: list = []      # the gap lines of this finish's window record (exit 1): read by the window-round cap only
        if complete is True:
            args.append("--complete")
            if unresolved:
                args += ["--unresolved", unresolved[0], "--reason", unresolved[1]]
            if stage == "S5" and role == "qa-code-critic":
                # FR-48/FR-5: the controller closes S5 only over a window acceptance record; building
                # it is a routine command, so code runs it and passes the file (no conductor).
                window = f"work/windows/{dispatch}.json"
                stamp = self.file_stamp(self.task_root / window)
                with self.timed("window_record", dispatch, stage):
                    wcode, wout = self.py("window_record.py", "--task", self.task, "--dispatch", dispatch)
                if wcode:
                    window_gaps = self.window_note(dispatch, wcode, wout, stamp, self.file_stamp(self.task_root / window))
                else:
                    args += ["--window", window]
                # The record says the window holds gaps the critic could not close: the finish carries them
                # as `unresolved` + `reason` (state-exits.md: an S5 window accepted as unresolved), the door
                # `story_step.py` names. Only exits 0 and 1 wrote a FRESH record (2 is a crash, and the file
                # on disk may be an older build); a missing or unreadable file is today's behaviour.
                if not unresolved and wcode in (0, 1):
                    found = self.window_gap(self.task_root / window, self.task_root)
                    if found:
                        unresolved = found
                        args += ["--unresolved", found[0], "--reason", found[1]]
                        print(f"S5: the window record of {dispatch} holds gaps the critic could not close "
                              f"({found[0]}); the finish accepts it as unresolved with their words")
                        if wcode:       # exit 1 wrote the record, and this is the record the gap was read from
                            args += ["--window", window]
        elif complete is False:
            args.append("--not-complete")
            if open_pair:
                args += ["--unresolved", open_pair[0], "--reason", open_pair[1]]
            elif stage == "S5" and (self.on_chain() or self._chains):
                # TR3-6 (B3): a finish that does not close S5 while other windows are open says so, so the controller does not refuse it as
                # "no role to close it". Only a process whose scheduler has run passes it (a chain's finish, and the seam's retry of one on
                # the main thread, where the cases come from the controller's record of the dispatch); the serial road's finish is as it was.
                own = self.s5_cases_of(dispatch)
                args +=self.s5_open_flag(own) if own else []
        if stage == "S9":
            # R-212.1: the report is rebuilt as the story's LAST step, and here the retro role has just
            # returned and this call is what closes S9 (`story_step finish` records the stage itself).
            self.rebuild_report()
        with self.timed("finish", dispatch, stage):
            code, out = self.py("story_step.py", *args)
        for line in out.splitlines():
            if line.startswith("note:") or line.startswith("accepted"):
                print(line)
        saved = self.state_dir / "driver-runs" / f"{dispatch}.json"
        if code:
            retry = lambda: self.finish(dispatch, digest, complete=given, role=role, stage=stage)
            if stage == "S9" and f"stage_done refused {stage}" in out:
                # The dispatch is accepted already; only the S9 record was refused, so "again" is that
                # record with the very arguments `story_step` used, never a second acceptance.
                def retry_record():
                    self.py("stage_done.py", "--task", self.task, "--stage", stage, "--status", "done",
                            "--role", role, "--digest", digest, check=True)
                    if saved.is_file():
                        saved.replace(saved.with_suffix(".done.json"))
                retry = retry_record
            # `window_gaps` travels in a field of its own, never in the text: the text is story_step's own words
            # (t-217 §4/C2), and the one-resume record keys on them.
            raise Refusal(f"story_step finish {dispatch} (exit {code}):\n{out}", retry=retry, dispatch=dispatch,
                          window_findings=window_gaps)
        if complete is True and WINDOW_ROUND_STAGES.get(stage) == role:
            # F-cmp2-28c / C1: ONLY the accepted completion of the stage's closing role ends the window's series.
            # An author's finish (`--not-complete`) between two reviews of the same window never does: that is
            # exactly where cmp2-27 (automator-10, accepted) sat between critic-2 and critic-3.
            self.close_window_series(stage, dispatch)
            if stage == "S5":
                self.s5_release_of_dispatch(dispatch)       # Q1: S5 closed - the window that closed it frees its files on EVERY road
        if complete is True and stage == "S5":
            self.s5_release_completed()     # TR4-10 D5: after `story_step finish` exited 0, so the stage status read is the one this finish wrote
        self.revoke_passes_of_dead(dead=(dispatch,))     # t-764 A5: a person's word over its refusal does not outlive the dispatch it was for
        self.forget_resumes(dispatch)       # accepted: its resume record has nothing left to guard
        if saved.is_file():
            saved.replace(saved.with_suffix(".done.json"))
        try:
            return digest, parse_next(out)
        except Refusal:
            return digest, {}

    @staticmethod
    def file_stamp(path):
        """(mtime in ns, size) of a file, or None when it is not there. "This call wrote the file" is judged by this
        before/after pair and never by an exit code: `window_record.py` writes the record first and a later failure is
        caught after the write (t-217 §4)."""
        try:
            path = Path(path)
            stat = path.stat()
            return (stat.st_mtime_ns, stat.st_size) if path.is_file() else None
        except OSError:
            return None

    def window_note(self, dispatch: str, wcode: int, wout: str, before, after) -> list:
        """What the driver says when `window_record.py` exited non-zero, in the words of what is TRUE (FR-37, FR-41):
        `story_step finish` passes `work/windows/<dispatch>.json` by itself when the file is there
        (`story_step.py` S5 block), so "the finish goes without a window record" was false whenever exit 1 had
        written the record. The gap lines are printed; a line carrying a marker is not echoed (cmp2-27: "This is a
        repair, not a question for the person" was printed at the person). PRINT ONLY: the `--window` and
        `--unresolved` decisions of `finish` are unchanged, and the output is never part of a Refusal's text.
        Returns the gap lines of an exit 1 (the window-round cap reads them), else [].

        Four facts, by the file's own stamp: written by this call and exit 1; written and a later error; present
        but not written by this call (an older record, which `story_step` still reads); absent."""
        lines = [line.rstrip() for line in str(wout or "").splitlines()]

        def marked(line: str) -> bool:
            return any(marker.lower() in line.lower() for marker in (REPAIR_MARKER, PERSON_MARKER))

        shown = [line for line in lines if line.startswith("  - ") and not marked(line)]
        if after is None:
            say = (f"S5: window_record.py could not build the record of {dispatch} (exit {wcode}); "
                   "no record exists, the finish goes without one")
        elif after == before:
            say = (f"S5: window_record.py could not build the record of {dispatch} (exit {wcode}); "
                   "an older record is on disk and story_step reads it")
        elif wcode == 1:
            say = (f"S5: found {len(shown)} gap(s) in the window of {dispatch}; the finish passes the record it "
                   "wrote and the controller judges it")
        else:
            say = (f"S5: window_record.py for {dispatch} exited {wcode} after it wrote the record; the finish "
                   "passes the record on disk and the controller judges it")
        echo = shown or [line for line in lines[-6:] if line.strip() and not marked(line)]
        print(say + (":" if echo else ""))
        for line in echo:
            print(line)
        return [line[4:].strip() for line in shown] if wcode == 1 else []

    def close_window_series(self, stage: str, dispatch: str) -> None:
        """The window's rounds end with the closing role's accepted completion: its series leaves the state."""
        held = self.state.get("window_rounds")
        if not isinstance(held, dict):
            return
        gone = [key for key in {self.window_key(stage, dispatch), f"{stage}|{dispatch}"} if held.pop(key, None) is not None]
        if gone:
            self.save_state()

    # The gap kinds an S5 window may be accepted with as `unresolved` (state-exits.md): the critic's two
    # words for a change it could not close, and the handed instances (`acceptance.HANDED_OUTCOME`).
    WINDOW_GAP_KINDS = ("could_not_judge", "fitted_to_code")

    WINDOW_REASON_LIMIT = 300

    @classmethod
    def window_gap(cls, path, root=None) -> tuple:
        """`(word, reason)` for the gaps the critic could not close in the window record at `path`, or `()`.

        The word is the FIRST gap kind in the record's own order (its keys as written: `instances`, then
        `expectation_changes`), the reason names every kind and carries the record's own gap lines, cut at
        WINDOW_REASON_LIMIT characters - the kinds stand first, so the cut never hides one. The gap lines are
        `acceptance`'s (`handed_to_person:<id>`, the vocabulary's sentence per change): nothing is re-worded
        here. A record that is missing, unreadable or holds none of these gaps gives `()`, which is today's
        plain `--complete`: the controller's own refusal then takes the road it always took.

        INVARIANT (t-204 F1): code never accepts a window as `unresolved` over a gap the critic did not name
        as its own. The controller reads `unresolved` as present or not, so a pair covers EVERY gap of the
        window; the record is therefore read through `acceptance.validate_window` (the controller's own
        function, over the task root `root`, by default three levels above the record) and ANY gap other than
        a handed instance's own (`handed_to_person:<id>`) or one of the critic's two kinds (`could_not_judge`,
        `fitted_to_code`) gives `()`, so the controller's refusal stays reachable for that window. A record the
        validation cannot read gives `()` too: the error direction is the refusal."""
        try:
            path = Path(path)
            record = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(record, dict):
                return ()
            from acceptance import HANDED_OUTCOME, expectation_change_gaps, validate_window
            owned = {text for text, code in expectation_change_gaps(record) if code in cls.WINDOW_GAP_KINDS}
            for gap in validate_window(record, Path(root) if root else path.parent.parent.parent):
                if not (gap.startswith(HANDED_OUTCOME + ":") or gap in owned):
                    return ()
            found = {"instances": [], "expectation_changes": []}
            for item in record.get("instances") if isinstance(record.get("instances"), list) else []:
                if isinstance(item, dict) and item.get("outcome") == HANDED_OUTCOME:
                    found["instances"].append((HANDED_OUTCOME, f"{HANDED_OUTCOME}:{item.get('instance_id') or '?'}"))
            for text, code in expectation_change_gaps(record):
                if code in cls.WINDOW_GAP_KINDS:
                    found["expectation_changes"].append((code, text))
        except Exception:
            return ()
        order = [k for k in record if k in found] + [k for k in found if k not in record]
        gaps = [gap for key in order for gap in found[key]]
        if not gaps:
            return ()
        kinds = list(dict.fromkeys(kind for kind, _text in gaps))
        reason = (", ".join(kinds) + ": " + "; ".join(text for _kind, text in gaps))[:cls.WINDOW_REASON_LIMIT]
        return kinds[0], reason

    def record_running(self, stage: str, role: str, dispatch: str, *, retry, relaunched: bool = False, rework_of: str = "") -> None:
        """C1-7c (O2, O4, G3, the never-launched start; F-3 of t-1252): the `running` stage record written BEFORE a registered
        dispatch's role starts - kind G. A non-zero exit is a `Refusal` (the factory's own, `known=False`) that names the dispatch
        (E-c8: in the text through `expect`, and in `refusal.dispatch`) and carries `retry`, the caller's whole step (the record, then
        the same run), so a registered dispatch is run once and never a second time behind the refusal.

        B-1 (t-1252): NO record - no write, no refusal - when the controller's stage is already `completed`, or when the dispatch is
        a rework of accepted work (`rework_of`). `stage_done.py` refuses `--status running` over a controller-completed stage by design
        ("already accepted by the controller": it would un-complete it), and the controller keeps a stage `completed` under later work
        (`set_stage`), so a record there is a refusal no retry can cure and the role would never run. The two exemptions are the one
        fact told twice: `rework_of` is the packet's own statement (known without a read), the controller's `completed` is the state
        `stage_done.py` itself refuses on. POSITION INVARIANT: the exemption is checked FIRST; on every stage that is not completed a
        non-zero exit still refuses before the role runs."""
        stages = self.controller_state().get("stages") or {}
        if rework_of or (stages.get(stage) or {}).get("status") == "completed":
            return
        try:
            self.py("stage_done.py", "--task", self.task, "--stage", stage, "--status", "running", "--role", role, check=True,
                    expect=f"{stage} recorded running for the {'relaunched ' if relaunched else ''}dispatch {dispatch}")
        except Refusal as refusal:
            refusal.dispatch = dispatch
            refusal.retry = retry
            raise

    def resume_role(self, stage: str, role: str, dispatch: str, words: str, *, complete=None) -> tuple:
        """The person answered a halt or the S1 review: the same session goes on."""
        sid = self.session_of(stage, dispatch)      # TR3-6: on a chain the dispatch's own session only
        self.boundary = f"{stage}:{dispatch}:resume"
        # t-113 B2 (R17, Q8): the words answer a threshold stop of THIS dispatch - a role that had
        # finished its work and was stopped by code, not one that stopped itself - so it gets its
        # own text, not "continue from where you stopped".
        stop = self.state.get("question_stop") or {}
        by_stop = bool(stop.get("resume")) and stop.get("dispatch") == dispatch
        # O2 (C1-7c, kind G as G3): the running record is written BEFORE the role goes on; a non-zero exit is a `Refusal` (the factory's
        # own) and the role is not resumed over a stage the record does not show as running. POSITION INVARIANT: nothing below has run
        # (the person's words are still in `pending_words`, the session is untouched), so the registered running dispatch is never run
        # a second time behind the refusal: `retry` is THIS resume (record, then the same run; the G1/G3 pattern, F-2 of C1-7b), and a
        # `continue` leaves the words for `_act_wait_existing_job`, which finds the dispatch by the id the refusal carries (E-c8: in its
        # text, through `expect`, and in `refusal.dispatch`). B-1: later work of a controller-completed stage writes no record (see
        # `record_running`), so its resume is never refused over a write `stage_done.py` refuses by design.
        self.record_running(stage, role, dispatch, retry=lambda: self.resume_role(stage, role, dispatch, words, complete=complete))
        if by_stop:
            prompt = self.question_resume_prompt(dispatch, words)
        else:
            prompt = (f"The person answered: \"{words.strip()}\"\nContinue your dispatch {dispatch} from where "
                      "you stopped, on that answer. Everything the person said is recorded already; do not "
                      "record it again. Your final message is the handoff form only:\n" + HANDOFF_FORM)
        if not sid:
            if by_stop:
                return self.question_rework(stage, role, dispatch, words, complete,
                                            f"no session is known for {dispatch}")
            raise Refusal(f"no session is known for {dispatch}; the role cannot be resumed by the driver",
                          dispatch=dispatch)
        # t-1957 N5s (E5s.6): a walk dispatch whose server is not `ready` gets it reopened BEFORE the words go in, and the words name the
        # reopened session. POSITION INVARIANT: after the `sid` checks (a role that cannot be resumed opens nothing), before the role runs:
        # a resumed walker never holds a dead `W`.
        lane, reopened = self.walk_reopen(dispatch)
        if reopened:
            prompt += "\n" + reopened
        # t-1991 U3b (E3b.5): a resumed S7 triage dispatch whose settle session is not ready gets it reopened BEFORE the words go in; the
        # words name the session or why there is none. An investigation, and every other role, opens nothing.
        triage = self.s7_is_triage(stage, role, dispatch)
        opened = triage and self.s7_settle_session(dispatch, resume=True)
        if triage and (said := self.s7_session_line(dispatch)):
            prompt += "\n" + "\n".join(said)
        self.progress_line()            # t-323 B1: a role is launched again (a resume): where the story stands, as at any launch
        result = {}
        try:
            result = self.run_claude("role", prompt, role=role, dispatch=dispatch, stage=stage, resume=sid,
                                     resume_reason=("the person answered the question the role was stopped on"
                                                    if by_stop else "the person answered what the role stopped for"))
        finally:
            if opened:
                self.s7_settle_close(dispatch)
            if lane:        # E5s.1/E5s.6: the same `after` as `run_role`, before the handoff reads the records
                self.walk_after(lane, dispatch, result)
            else:           # t-2548 F1 (AR-25): a survey session reopened for this resume is closed with the role (a no-op for any other dispatch)
                self.survey_after(dispatch, result)
        if by_stop and result.get("is_error") and not str(result.get("result") or "").strip():
            # The session is gone: the same dispatch goes on in a new one, with the words as its reason.
            return self.question_rework(stage, role, dispatch, words, complete,
                                        f"the session of {dispatch} could not be resumed")
        _write_json(self.state_dir / "driver-runs" / f"{dispatch}.json", result)
        # t-764 A12 (F10): the role answered the words in THIS result - spent before the handoff judges it, so a refusal of that
        # handoff never re-sends them on the next entry (a pop after the threshold was never reached on that road). Only a result that
        # CARRIES words consumed them (t-781 m2): an error with no words answered nothing - `handoff` raises on it and the person's
        # words stay for the next entry (edge 11: they reach the role at least once)
        if str(result.get("result") or "").strip():
            self.state["pending_words"].pop(dispatch, None)
            self.save_state()
        digest = self.handoff(role, stage, dispatch, result)
        import story_step
        if story_step._declared_halt(self.task_root, story_step.FORM_REL.format(dispatch_id=dispatch), digest):   # CX1-14 (B-2): the one reader
            if by_stop:
                stop.pop("resume", None)     # the words went in; the role's own halt asks its own question
            raise Person("halt", self.halt_text(stage, role, digest, again=True), stage, dispatch,
                         details=str(digest or "").strip() or "the role's final message was empty")
        # A role that added questions while it answered is checked like any other handoff: the same
        # count does not stop twice (the person's answer was the informed pass), a larger one does.
        self.question_threshold(stage, role, dispatch)
        self.state["pending_words"].pop(dispatch, None)
        if by_stop:
            stop.pop("resume", None)
        self.save_state()
        self.repair_limit_gate(stage, role, dispatch, digest, recovering=True)     # t-698 A4: before `finish`, after the words are spent
        finished = self.finish(dispatch, digest, complete=complete, role=role, stage=stage)
        self.progress_line()            # t-323 B1: the resumed role returned and its work is recorded
        return finished

    # --- the walk session around a manual lane: code before the walker starts and after it ends (t-1957 N5s, spec 3.5; E5s.1-E5s.9) ---------
    # state key `walk_retry`: {case: {"refused": n, "open": bool, "reason": text}} - a build the walk refused is walked ONCE more

    def walk_before(self, lane: list, dispatch: str, assigned=None) -> dict:
        """Before the walker of `lane` starts (spec 3.5): `work/run-report.json` (else `finalize_task.py` over what is on disk, F30/F31), the app
        card (`app_card.py build` rebuilds only when its inputs changed), then `walk_session.py open` for the lane's account. Returns
        `{"walking": bool, "report_last": bool}`. E5s.3: no report and none can be made -> `report_last` (the brief names `finalize_task.py`
        as the walker's last command - its Stop is never refused for a file it cannot make). E5s.4: `open` fails (exit 3), the account cannot
        be named, or anything here raises -> `walking` False, the dead record is removed (no walk record), and the lane runs on today's road
        (FR-57: nothing locks the role). POSITION INVARIANT: runs after the dispatch is registered and before the role starts, so the brief
        the role reads is written with the walk record in place."""
        out = {"walking": False, "report_last": False}
        why = ""
        try:
            report = self.task_root / "work" / "run-report.json"
            if not report.is_file():
                code, text = self.py("finalize_task.py", str(self.task_root))
                if code or not report.is_file():
                    out["report_last"] = True
                    print(f"S6: {dispatch}: there is no run-report.json and finalize_task.py could not make one (exit {code}); "
                          "the walker's last command is finalize_task.py")
            # remains: the card is a courtesy; a failed build is the printed last line, and the walker reads whatever card exists (P1)
            _code, line = self.py("app_card.py", "build", "--task-root", str(self.task_root))
            print(f"S6: {(line.splitlines() or ['app-card: no answer'])[-1]}")
            key = lane_keys(self.task_root, lane).get(lane[0])
            actors: list = []
            if key is None:
                why = f"the accounts of {lane[0]} could not be read from its request"
            elif assigned:
                # TR3-10d item 3: the assigned handles in the key's order; a guest or `obtain:` handle opens as `guest`, an `env:U/S` handle
                # passes as is (the real gate is `sign_in_refusal`). Without an assignment (walkers 1, one lane) the code below is today's.
                import walk_pool as WP
                import walk_session as WS
                actors = list(dict.fromkeys(WP.open_as(handle) for handle in assigned.values()))
                limit = int(WS.data()["max_actors"])
                if not actors or len(actors) > limit:
                    actors, why = [], f"the lane names {len(actors)} accounts ({key}); a walk holds at most {limit}"
            elif key == "":
                actors = ["guest"]
            else:
                actors, why = self.walk_actors(lane[0], key)
            if not why:
                code, text = self.py("walk_session.py", "open", "--task-root", str(self.task_root), "--walk", dispatch,
                                     "--items", ",".join(lane), "--actor", actors[0], *(["--actor2", actors[1]] if len(actors) > 1 else []),
                                     # t-2147 C1 item 4(d): on the parallel road (a chain) the session may share the stand with the other walkers
                                     *(["--max-shared", str(self.s6_walkers_cap())] if self.on_chain() else []))
                out["walking"] = code == 0
                why = "" if code == 0 else (text.splitlines() or [f"exit {code}"])[-1][:300]
                if code == 0:       # TR1-4: a lane that walks leaves the old-road list (an earlier mark would keep it out of the medians)
                    for case in lane:
                        (self.state.get("walk_old_road") or {}).pop(case, None)
        except Exception as exc:        # P1: code informs, it never stops the factory
            why = f"{type(exc).__name__}: {' '.join(str(exc).split())[:200]}"
        if not out["walking"]:
            try:
                (self.task_root / "state" / "walks" / f"{dispatch}.json").unlink()
            except OSError:
                pass
            self.walk_settle_unopened(dispatch)     # TR3-10d R1: the records assigned to this lane's walk have an exit (dirty), never held forever
            print(f"S6: {dispatch}: no walk session ({why}); the lane is walked on the recorder, as before")
            # t-2016 F5: an item that left the walker is marked, so a figure taken from the old road never joins a walker's median
            self.state.setdefault("walk_old_road", {}).update({case: why[:200] for case in lane})
        return out

    def walk_actors(self, case: str, key: str) -> tuple:
        """`([handle, ...], why)` for the account set `key` of a lane (`lane_keys`), at most `walk_session.data()['max_actors']` handles in
        the key's order: ONE account is `manual_capture.auto_actor`'s (its refusals and doors, unchanged); two are each resolved like
        `auto_actor` resolves its one - a `stand_account` role whose note names two keys, or `default` - so `--actor` and `--actor2` are
        the lane's two accounts (the walker acts as either with `--as`). `why` is non-empty when the lane cannot walk: more accounts than
        a walk holds, or an account a machine cannot sign in as (today's road, with the reason). t-2174 TR3-10d (AR-15): the body is
        `walk_pool.lane_handles`, the one copy the pool reads too."""
        import walk_pool as WP
        return WP.lane_handles(self.task_root, case, key)

    def walk_env_pair(self, stand, value: str) -> tuple:
        """`(role, why)` for an account named by ONE key `value` (the login key of `env:<key>`), TR1-4: `walk_pool.walk_env_pair`, the one
        copy (TR3-10d, AR-15). ERROR DIRECTION: a doubt is never another account."""
        import walk_pool as WP
        return WP.walk_env_pair(stand, value)

    def walk_settle_unopened(self, dispatch: str, state: str = "dirty") -> None:
        """TR3-10d R1 (AR-25: a held row always has an exit): the records `walk_pool.assign_entities` held for the walk `dispatch` go to
        `state` (`dirty`: the lane may have run on the recorder) when that walk never opened; a walk with a record is not touched
        (`walk_session.settle_unopened`, the one writer). Never raises (P1): a failure is one printed note."""
        try:
            import walk_session as WS
            _moved, problem = WS.settle_unopened(self.task_root, dispatch, state)
            if problem:
                print(f"note: {problem}")
        except Exception as exc:  # noqa: BLE001 - settling never stops a lane
            print(f"note: the records held for walk {dispatch} were not settled ({type(exc).__name__})")

    def walk_lane_facts(self, lane) -> dict:
        """TR3-10d (AR-13: the one reader of this entry's assignment): `{"n": the lane's number or None, "handles": {part: handle} - only when
        EVERY part of the lane's key has one (else {}: today's key-based holds and actor, L3), "entries": {item: [entry]}, "id": the walk id
        reserved for the lane or ""}`. Reads the state `walk_assign_step` wrote; an absent or odd key reads as no assignment (FR-59)."""
        out: dict = {"n": None, "handles": {}, "entries": {}, "id": ""}
        cases = [str(c) for c in lane or ()]
        number = (self.state.get("walk_assign_cases") or {}).get(cases[0]) if cases else None
        if not isinstance(number, int) or isinstance(number, bool):
            return out
        name = str(number)
        out["n"] = number
        handles = (self.state.get("walk_assign") or {}).get(name)
        if isinstance(handles, dict) and handles and all(isinstance(h, str) and h for h in handles.values()):
            out["handles"] = dict(handles)
        entries = (self.state.get("walk_entities") or {}).get(name)
        if isinstance(entries, dict):
            out["entries"] = entries
        reserved = (self.state.get("walk_ids") or {}).get(name)
        out["id"] = reserved if isinstance(reserved, str) else ""
        return out

    def walk_account_gap(self, lane: list) -> str:
        """The reason a lane cannot walk for its ACCOUNTS, else "" (TR1-4, B5: ONE road for every shape of the key; the old road is for a
        failed `walk_session.py open` only). It reads `walk_actors`, the one reader `walk_before` opens the session by, so the lane is
        refused here exactly when it could not open there. An empty key is a guest (walkable); a request that cannot be read, or a
        reader that fails, is a reason too (FR-59: an unknown is never a pass). The text carries no flag or command (P9)."""
        case = lane[0]
        try:
            key = lane_keys(self.task_root, lane).get(case)
            if key is None:
                return f"the accounts of {case} could not be read from its request"
            if key == "":
                return ""
            return self.walk_actors(case, key)[1]
        except ValueError:
            return f"the account of {case} is not one a machine can sign in as"
        except Exception as exc:
            return f"the accounts of {case} could not be established ({type(exc).__name__})"

    def walk_reopen(self, dispatch: str, reopen: bool = True) -> tuple:
        """`(items, words)` for a RESUMED dispatch (E5s.6): `items` are the walk's items (`[]` = this is no walk dispatch); `words` is the line
        the resume prompt adds - the walk session reopened (`walk_session.py open`, same walk, same actors; items with a verdict are kept by
        the server), or why it could not be. A server that is `ready` and alive is left alone and `words` is empty. `reopen=False` (a saved
        result stands, so no role will run): the items only, nothing opened (t-2022 N7: a browser, a sign-in and the lease for no role)."""
        record = _read_json(self.task_root / "state" / "walks" / f"{dispatch}.json")
        place = str(record.get("place") or "case") if isinstance(record, dict) else "case"
        if place == "survey":
            # t-2277 batch 2b D (critic t-2513 F2): the survey walk of an optional dispatch (S1 reference window, S3 first look) is no case walk
            # (no items come back, so no case lane is built over it) but the resumed role gets its session back, on the stand the record names.
            # B1 (critic t-2548): a record that never reached `ready` (`open_walk` stamps it `did not start: ...`) is a walk that never began -
            # no session to give back, and the packet of a failed window says "walk nothing" already (FR-10): nothing is reopened, nothing is said
            if str(record.get("state") or "") != "ready" and str(record.get("reason") or "").startswith("did not start"):
                return [], ""
            return [], (self._survey_reopen(dispatch, record) if reopen else "")
        if place != "case":
            return [], ""       # t-2027 F1: a settle or control session's record (place ids as items) is no case walk; `s7_settle_session` reopens its own
        items = [str(i) for i in record.get("items") or [] if str(i).strip()] if isinstance(record, dict) else []
        if not items or not reopen:
            return items, ""
        try:
            shared = int(record.get("max_shared") or 1)      # F4: a record without the field reads 1 (old records, C.12)
        except (TypeError, ValueError):
            shared = 1
        return items, self._walk_reopen_open(dispatch, record, ["--items", ",".join(items)], ["--max-shared", str(shared)] if shared > 1 else [],
                                             said="S6: {d}: the walk session", unwalked="which items you did not walk",
                                             kept="items with a verdict are done; continue with the next.")[0]

    def _walk_reopen_open(self, dispatch: str, record: dict, head: list, tail: list, *, said: str, unwalked: str, kept: str,
                          where: str = "", cannot: str = "") -> tuple:
        """`(line, opened)`: the COMMON body of a walk reopen (critic t-2548 F4), for the case lane (`walk_reopen`) and the survey walk
        (`_survey_reopen`). `""` when the record's server is `ready` and alive; else `walk_session.py open` over the walk's own id with `head`
        (what names the walk: items, place, stand) and `tail` (flags after the actors), the actors of the record (`guest` when it names none),
        and the line the role is told: the failure (`cannot` is a reason known before any call: the open is not made, FR-41) or the reopened
        session (`where` names a stand, `kept` what stays). `said` is the printed line's start (`{d}` = the dispatch). `opened` is True only
        when the session was opened by THIS call. Never raises."""
        try:
            import walk_session as WS
            alive = record.get("state") == "ready" and WS.alive(record)
        except Exception:
            alive = record.get("state") == "ready"
        if alive:
            return "", False
        said = said.format(d=dispatch)
        text, code = "", 0
        if not cannot:
            actors = [str(a) for a in record.get("actors") or [] if str(a).strip()] or ["guest"]
            argv = ["open", "--task-root", str(self.task_root), "--walk", dispatch, *head, "--actor", actors[0],
                    *(["--actor2", actors[1]] if len(actors) > 1 else []), *tail]
            code, text = self.py("walk_session.py", *argv)
        if cannot or code:
            why = cannot or (text.splitlines() or [f"exit {code}"])[-1][:300]
            print(f"{said} could not be reopened ({why})")
            return (f"Your walk session could not be reopened ({why}); its commands will be refused. Stop here and say {unwalked}."), False
        got = _read_answer(text) or {}      # exit 0 and no answer: the sentence below says "not signed in" and lands on the landing page (a hint only)
        signed = "signed in" if got.get("signed_in") else "not signed in"
        print(f"{said} was reopened")
        return (f"Your walk session was reopened{where} ({signed}, landed on {got.get('landed_on') or 'the landing page'}); {kept}"), True

    def _survey_reopen(self, dispatch: str, record: dict) -> str:
        """The line a resumed role of a SURVEY walk is told (`walk_reopen`, t-2277 batch 2b D), or "" when the server is `ready` and alive.
        The walk is opened again as it was (same walk id, place `survey`, the stand and the actors of the record; the items the walk
        already recorded stay on disk). A record that does not name its stand (the server died before it wrote one) cannot be opened on
        a guess: the line says so and the role is told to stop and say what it did not walk (FR-41, AR-28). A session this call opened is
        remembered (`survey_reopened`): the role's end closes it (`survey_after`, AR-25). Never raises."""
        stand = str(record.get("stand") or "").strip()
        items = [str(i) for i in record.get("items") or [] if str(i).strip()] or ["free"]
        line, opened = self._walk_reopen_open(dispatch, record, ["--place", "survey", "--env", stand, "--items", ",".join(items)], [],
                                              said="{d}: the survey walk session", unwalked="what you did not walk",
                                              kept="what you already captured is kept; continue where you stopped.",
                                              where=f" on `{stand}`", cannot="" if stand else "its record names no stand")
        if opened:
            once_on(self, "survey_reopened", set).add(dispatch)
        return line

    def survey_after(self, dispatch: str, result=None) -> None:
        """The close of a survey session this driver REOPENED for a resumed role (critic t-2548 F1, AR-25): `walk_session.py close`, as
        `walk_after` does for a lane, so the stand lease (a `survey` session holds it in walk mode, up to `idle_s`) is let go when the role
        ends. A dispatch whose session was not reopened here is left alone. Never raises: a failure is a printed note."""
        opened = once_on(self, "survey_reopened", set)
        if dispatch not in opened:
            return
        opened.discard(dispatch)
        try:
            # remains: the exit is read on the next line and said; a server that did not close ends by itself (idle/max/parent watchdog)
            code, text = self.py("walk_session.py", "close", "--task-root", str(self.task_root), "--walk", dispatch)
            if code:
                print(f"note: walk_session.py close exit {code}: {(text.splitlines() or [''])[-1][:200]}; the server ends by itself")
        except Exception as exc:
            print(f"note: walk_session.py close raised {type(exc).__name__}; the server ends by itself")

    def walk_pending(self, lane: list) -> bool:
        """True when a case of `lane` was refused by the build of its record (`walk_after`): it is walked once more in a lane of the next
        entry, or closed `left_unchecked` after a second refusal. Either way the lane that carried it never closes the stage (E5s.1)."""
        retry = self.state.get("walk_retry") or {}
        return any(isinstance(retry.get(case), dict) and (retry[case].get("open") or retry[case].get("refused", 0) > 1) for case in lane)

    def walk_after(self, lane: list, dispatch: str, result) -> None:
        """After the walker of `lane` is over (spec 3.5; `run_role` and `resume_role` call it through `after=`, BEFORE `bind`, `handoff` and
        `finish`): `walk_session.py close`; per item `manual_evidence.record_from_walk` over its result record (a walker that ended with no
        verdict gets `walk_session.write_verdict(..., None)`: every Then `inconclusive`, E5s.2); `finalize_task.py`; the form's values
        `work/handoffs/<dispatch>.values.yaml`; the timing end line. A build the record refuses is re-queued ONCE (`walk_retry`, read by
        `manual_plan`), the second refusal writes the case's request as refused `left_unchecked` (the `manual_close` road). IDEMPOTENT: the
        items already handled stand in `work/walks/<W>/after.json` and are skipped, so a reused saved result runs it safely. Never raises
        (P1): a failure is a printed note and the lane goes on to the checks that follow."""
        T = self.task_root
        try:
            # remains: the exit is read on the next line and said; a server that did not close ends by itself (idle/max/parent watchdog)
            code, text = self.py("walk_session.py", "close", "--task-root", str(T), "--walk", dispatch)
            if code:
                print(f"note: walk_session.py close exit {code}: {(text.splitlines() or [''])[-1][:200]}; the server ends by itself")
        except Exception as exc:
            print(f"note: walk_session.py close raised {type(exc).__name__}; the server ends by itself")
        rows: dict = {}
        try:
            self.walk_case_records(lane, dispatch, rows)
        except Exception as exc:
            print(f"note: the records of walk {dispatch} were not all built ({type(exc).__name__}: {' '.join(str(exc).split())[:200]})")
        try:
            # TR3-10d item 5 (D.9, AR-25): a lane that took `obtain:<role>#n` and left no confirmed user of its cases behind. Every case of it
            # WITHOUT a verdict is re-queued as ONE refusal (a second one closes it `left_unchecked` by the rule of `walk_refusal`), and the role
            # gets no obtain lane for the rest of the story (`walk_assign_step` reads `obtain_failed`): no sign-up loop. A case that has a
            # verdict stands. An obtain lane whose user WAS confirmed changes nothing. IDEMPOTENT: a re-queued case is `refused` in `rows`.
            import manual_capture as MC
            obtain = [str(h) for h in self.walk_lane_facts(lane)["handles"].values() if str(h).startswith("obtain:")]
            names = _read_json(MC.created_names_path(T)) if obtain and MC.created_names_path(T).is_file() else {}
            made = [r for r in (names.get("accounts") if isinstance(names, dict) else None) or [] if isinstance(r, dict)]
            if obtain and not any(r.get("case") in lane and not r.get("status") for r in made):
                retry = self.state.setdefault("walk_retry", {})
                for case in lane:
                    row = rows.get(case)
                    if isinstance(row, dict) and row.get("missing") and row.get("state") != "refused":
                        rows[case] = {**self.walk_refusal(case, "its walker could not get an account: the sign-up was not seen to land", retry),
                                      "missing": True}
                _write_json(T / "work" / "walks" / dispatch / "after.json", {"rows": rows})
                failed = self.state.setdefault("obtain_failed", {})
                for handle in obtain:
                    failed[handle[len("obtain:"):].rsplit("#", 1)[0]] = True
                self.save_state()
        except Exception as exc:
            print(f"note: the sign-up of walk {dispatch} could not be checked ({type(exc).__name__}: {' '.join(str(exc).split())[:200]})")
        try:
            # remains: the exit is read on the next line and said; the handoff check after the role refuses a form over a missing report (P1)
            code, text = self.py("finalize_task.py", str(T))
            if code:
                print(f"note: finalize_task.py exit {code}: {(text.splitlines() or [''])[-1][:200]}")
            self.walk_values(dispatch, rows)
            timing = T / "work" / "walks" / dispatch / "timing.jsonl"
            kept = []
            if timing.is_file():
                for line in timing.read_text(encoding="utf-8").splitlines():
                    try:
                        if line.strip() and "after_end" not in json.loads(line):
                            kept.append(line)
                    except ValueError:
                        kept.append(line)       # a broken line is `walk_timing`'s to count and name (FR-41), not ours to drop
            timing.parent.mkdir(parents=True, exist_ok=True)
            import event_store      # Q-new-2: the rewrite is published whole (a reader of the timing never sees a torn file)
            body = "".join(line + "\n" for line in [*kept, json.dumps({"after_end": _now()})])
            try:
                event_store.atomic_text(timing, body)
            except OSError as exc:       # a reader held it past the retries: the write that worked before, with a note (as `_write_json`)
                print(f"note: {timing.name} could not be published atomically ({type(exc).__name__}); it is written in place", flush=True)
                timing.write_text(body, encoding="utf-8", newline="\n")
        except Exception as exc:
            print(f"note: the walk's closing steps did not all run ({type(exc).__name__}: {' '.join(str(exc).split())[:200]})")

    def walk_case_records(self, lane: list, dispatch: str, rows: dict) -> None:
        """The case record of every item of `lane` that has none yet, into `rows` (the state of `work/walks/<W>/after.json`, written after each
        item). An item with no result record gets one for a MISSING verdict (`write_verdict(..., None)`, marked `missing_verdict`). IDEMPOTENT
        and a resume's friend (t-2016 F4): an item stays handled once built, EXCEPT one handled for a missing verdict whose result record is a
        real verdict now (the walker went on after a halt or a cut): that one is built again, its refusal count from the missing verdict
        forgotten. A build the record refuses is re-queued ONCE (`walk_retry`, read by `manual_plan`); the second refusal writes the
        case's request as refused `left_unchecked` (the `manual_close` road)."""
        T = self.task_root
        import manual_capture as MC
        import manual_evidence as ME
        import walk_session as WS
        marker_path = T / "work" / "walks" / dispatch / "after.json"
        marker = _read_json(marker_path)
        rows.update(marker["rows"] if isinstance(marker.get("rows"), dict) else {})
        retry = self.state.setdefault("walk_retry", {})
        for case in lane:
            found = T / "work" / "walks" / dispatch / f"{MC.case_dir_name(case)}.json"
            walk_record = _read_json(found) if found.is_file() else {}
            missing = not walk_record or bool(walk_record.get("missing_verdict"))
            prior = rows.get(case)
            if isinstance(prior, dict) and not (prior.get("missing") and not missing):
                continue
            if isinstance(prior, dict):
                retry.pop(case, None)
            try:
                if not walk_record:
                    walk_record = WS.write_verdict(T, dispatch, case, None)
                built = ME.record_from_walk(T, case, walk_record)
            except Exception as exc:
                built = {"refused": f"{type(exc).__name__}: {' '.join(str(exc).split())[:300]}"}
            if built.get("refused"):
                rows[case] = {**self.walk_refusal(case, str(built["refused"]), retry), "missing": missing}
            else:
                if isinstance(retry.get(case), dict):
                    retry[case]["open"] = False
                word = "unprepared_walk" if built.get("unprepared") else {"pass": "passed", "fail": "failed"}.get(str(built.get("result")), "inconclusive")
                rows[case] = {"state": word, "block": built.get("block"), "evidence": list(built.get("evidence") or []), "missing": missing}
            _write_json(marker_path, {"rows": rows})
            self.save_state()

    def walk_refusal(self, case: str, refused: str, retry: dict) -> dict:
        """Count a build refusal of `case` in `retry` and say it: the first is walked once more, the second closes the case `left_unchecked`.
        Returns its row of `after.json`."""
        entry = retry.get(case) if isinstance(retry.get(case), dict) else {"refused": 0}
        entry = {"refused": int(entry.get("refused") or 0) + 1, "reason": refused[:400]}
        entry["open"] = entry["refused"] == 1
        retry[case] = entry
        if entry["open"]:
            print(f"S6: {case}: the record of its walk was refused ({entry['reason']}); it is walked once more in the next lane")
        else:
            reason = f"not checked by hand: the record of its walk was refused twice - {entry['reason']}"
            self.refuse_case(None, case, reason, "walk the case again after the build is fixed (retry at gate B), or check it yourself",
                             "left_unchecked", by_first=True)
            print(f"S6: {case}: {reason}")
        return {"state": "refused", "reason": entry["reason"], "n": entry["refused"]}

    def walk_values(self, dispatch: str, rows: dict) -> None:
        """`work/handoffs/<dispatch>.values.yaml`: EVERY required field of the form that code owns (a flat `path: value` JSON object, the one
        `handoff_check.py` applies and renames), so the lane does not pay a resume for a form (t-2016 F3). Words of the records only (P27):
        `header.verdict` is `ok` when every case stood and `concerns` otherwise; `header.window` the lane's cases; `run.*` from the stand
        probes of the attempts and the run report; per case a `scope[]` row (its obligations from its request) and, for a built record, a
        `manual_observations[]` row carrying the Thens verbatim from `request.json` and the record's own `actual`, `before_change` and
        `surprises`; the claims code can count; one `tried[]` row from the walk's own figures. A value code cannot know is a named gap (`-`,
        or words that say it was not established), never an invented one (FR-41): the `run.witness` count comes from the records (a
        case with no recorder step was not walked); `scope[].executed` is `none` for a case that did not run. Written when the form is there and no values file was
        applied to it already - or when one was and the rows have changed since (a late verdict rebuilt a record: the form must say what the
        record says, t-2022 N9; `handoff_check --fix` applies the waiting file over the old words); a refused case is a `manual_skipped`
        row with its reason."""
        T = self.task_root
        form = T / "work" / "handoffs" / f"{dispatch}.yaml"
        if not form.is_file() or not rows:
            return
        values = {"header.verdict": "ok" if all(r.get("state") == "passed" for r in rows.values()) else "concerns",
                  "header.window": ", ".join(rows)}
        built = [(case, row) for case, row in rows.items() if row.get("state") != "refused"]
        facts = {case: self.walk_facts(case, row) for case, row in built}
        values.update(self.walk_run_values(dispatch, rows, facts))
        for at, (case, row) in enumerate(rows.items()):
            state = row.get("state")
            values[f"scope[{at}].id"] = case
            values[f"scope[{at}].case"] = case
            values[f"scope[{at}].state"] = "manual_skipped" if state == "refused" else state
            values[f"scope[{at}].reason"] = (f"walked: {state}" if state != "refused" else str(row.get("reason") or f"record refused {row.get('n')}x"))[:80]
            values[f"scope[{at}].evidence"] = row.get("block") or f"work/evidence/manual/{case}/request.json"
            values[f"scope[{at}].obligations"] = ", ".join(facts.get(case, {}).get("obligations") or []) or "-"
            # t-2022 N8: `none` = nothing ran for this row (a refused or never-walked case); it is no evidence, the row's `state` and `evidence` say so
            values[f"scope[{at}].executed"] = "fresh" if facts.get(case, {}).get("steps") else "none"
        for at, (case, row) in enumerate(built):
            fact = facts[case]
            values[f"manual_observations[{at}].case"] = case
            values[f"manual_observations[{at}].then"] = fact["then"]
            values[f"manual_observations[{at}].observed"] = fact["actual"]
            values[f"manual_observations[{at}].before_change"] = fact["before_change"]
            values[f"manual_observations[{at}].result"] = {"passed": "passed", "failed": "failed"}.get(row.get("state"), "inconclusive")
            values[f"manual_observations[{at}].evidence"] = row.get("block") or ""
            values[f"manual_observations[{at}].surprises"] = fact["surprises"]
        text = json.dumps(values, indent=1)
        applied = form.with_name(f"{dispatch}.values.applied.yaml")
        if applied.is_file() and applied.read_text(encoding="utf-8", errors="replace") == text:
            return          # the words the form already holds: nothing changed since they were applied
        form.with_name(f"{dispatch}.values.yaml").write_text(text, encoding="utf-8", newline="\n")

    def walk_facts(self, case: str, row: dict) -> dict:
        """What the built record of `case` says, read from its files: `then` (the Thens of its request, verbatim), `actual`, `before_change`,
        `surprises`, `obligations`, the stand identity of its probes (`environment`, `build`, `probes` = the probes file) and its `steps`. A
        word the files do not hold is a gap in words, never a guess."""
        import manual_capture as MC
        T = self.task_root
        folder = (T / str(row["evidence"][0])).parent if row.get("evidence") else None
        record = _read_json(folder / "record.json") if folder is not None and (folder / "record.json").is_file() else {}
        request = _read_json(MC.case_root(T, case) / "request.json")
        thens = request.get("thens") if isinstance(request.get("thens"), dict) else {}
        start = next((p.get("probe") or {} for p in (MC.jsonl_rows(folder / "probes.jsonl") if folder is not None else []) if p.get("when") == "start"), {})
        change = record.get("before_change")
        surprises = record.get("surprises") if isinstance(record.get("surprises"), list) else []
        ids = ", ".join(str(s.get("id")) for s in surprises[:30] if isinstance(s, dict))
        return {"then": "; ".join(f"{n}. {thens[n]}" for n in sorted(thens, key=lambda k: int(k) if str(k).isdigit() else 0)) or f"no Then is listed in the request of {case}",
                "actual": str(record.get("actual") or "").strip() or "the record holds no `actual`",
                "before_change": json.dumps(change, sort_keys=True) if change is not None else "not_recorded: the record holds no before_change",
                "surprises": f"{len(surprises)} line(s), surprise_detection {record.get('surprise_detection') or 'not recorded'}" + (f"; ids {ids}" if ids else ""),
                "obligations": [str(o) for o in request.get("obligation_ids") or []],
                "environment": str(start.get("environment_id") or ""), "build": str(start.get("observed_runtime_identity") or ""),
                "probes": (folder / "probes.jsonl").relative_to(T).as_posix() if folder is not None and (folder / "probes.jsonl").is_file() else "",
                "steps": len(MC.jsonl_rows(folder / "steps.jsonl")) if folder is not None else 0}

    def walk_run_values(self, dispatch: str, rows: dict, facts: dict) -> dict:
        """The `run.*`, `inputs_read[]`, `claims.*`, `tried[]` and `superseded` values of a walk's form (see `walk_values`). The run report's
        own figures (`execution_status`, `window_totals`) are derived by `handoff_check --fix`; here is what the report cannot say of a manual lane."""
        T = self.task_root
        first = next(iter(facts.values()), {})
        walked = [case for case, fact in facts.items() if fact["steps"]]          # N8: a case with a recorder step was walked; a refused or empty one was not
        gap = "not established: no case record of this lane was built"
        report = _read_json(T / "work" / "run-report.json")
        provenance = sorted((T / "evidence").glob("runtime-provenance-*.json"))
        return {
            "run.witness": f"no automated run in this dispatch: {len(walked)} of {len(rows)} manual case(s) walked with the walk session {dispatch}",
            "run.environment": first.get("environment") or gap,
            "run.application_build": first.get("build") or gap,
            "run.probe_before": first.get("probes") or gap, "run.probe_after": first.get("probes") or gap,
            "run.totals": json.dumps(report.get("totals"), sort_keys=True) if report.get("totals") else "the report counted no automated test: manual walk only",
            "inputs_read[0].version": "-", "inputs_read[0].instances_handed": "-",
            "inputs_read[1].version": "-", "inputs_read[1].manual_cases_handed": str(len(rows)),
            "inputs_read[2].path": f"evidence/{provenance[-1].name}" if provenance else "-",
            "inputs_read[2].version": first.get("build") or "-",
            "claims.every_row_carries_an_evidence_path": all(bool(r.get("block")) for r in rows.values()),
            "claims.every_blocked_row_names_a_remedy_and_the_probe_line": True,             # a walk's form carries no `env_blocked` row
            "claims.no_comparison_was_fabricated_where_before_evidence_is_missing": True,   # `before_change` is built by code from the register
            "claims.handed_and_manual_human_cases_are_absent_by_design": True,              # a manual block holds manual-agent cases only
            "claims.the_report_was_reduced_by_code_not_written": bool(report),
            "superseded[0].row": "none", "superseded[0].superseded_by": "none",         # a manual lane reran no automated instance: no ghost row
            "tried[0].requirement": ", ".join(rows),
            "tried[0].technique": f"walk session {dispatch}: {sum(f['steps'] for f in facts.values())} recorder step(s) over {len(walked)} walked case(s)",
            "tried[0].observation": "; ".join(f"{case} {row.get('state')}" for case, row in rows.items())[:300],
            "tried[0].evidence": f"work/walks/{dispatch}/timing.jsonl"}

    # --- the question threshold: the stop and the resume (t-113 B2: R15, R16, R17, Q8) ---------------

    QUESTION_ANSWER_BY = "person"     # a value of question-vocabulary.json `by`: the words are the person's

    @staticmethod
    def question_when(at) -> str:
        """`2026-09-30 18:05 UTC`: an instant as a person reads it; anything unreadable as written."""
        text = str(at or "").strip()
        try:
            return datetime.fromisoformat(text).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        except ValueError:
            return text

    @staticmethod
    def larger_than_answered(count, share, answered: dict) -> bool:
        """Q8: the person's answer at a stop is the informed pass for THAT count and THAT share; only a
        strictly larger one is a new fact. An unknown (a share that could not be computed) is never
        larger than anything (FR-41) - it neither stops nor is stopped on."""
        was_count, was_share = answered.get("count"), answered.get("share")
        if isinstance(count, int) and isinstance(was_count, int) and count > was_count:
            return True
        return (isinstance(share, (int, float)) and isinstance(was_share, (int, float)) and share > was_share)

    def question_threshold(self, stage: str, role: str, dispatch: str) -> None:
        """R15: after a role's handoff and before `finish`, count the register's open questions; over
        the limit, stop and ask the WHOLE batch. Raises `Person("questions")` or returns.

        Code only counts and renders (FR-47): the role's own stop is the `halt` road, which has run
        before this point. P1: a failure of the count is printed and the stage goes on - code informs,
        it never stops the factory on its own defect. The stop is recorded in the DRIVER's state, not in
        the role's files (Q8): {stage, dispatch, count, share, at, shown, answered}. A person's word
        passes it (`waiver.py --stage S2|S3|S4 --block "question threshold"`, recorded by the waiver, FR-4).

        HF2-7, the owner's word of 24.10: ONE open question that blocks stops the story whatever the count (`question_stop.
        blocking_stop`). POSITION INVARIANT (M1): the blocking check runs AFTER the applying of the recorded answers and BEFORE any
        early return of the count - not `over`, the count the person answered at, the stage's recorded pass for the COUNT - so none of
        those can hide a blocker; it is held only by `answered.blocking_ids` (`{id: the row's hash the person passed}`, written by
        `go on` alone): a blocker whose row changed since is not the one that was passed (H44). The S4 threshold is the case
        designer's alone (H30): the critic's handoff has no stop and no applying, so the plan does not move under a fresh review."""
        try:
            import question_register as QR
            import question_stop as QS
            where = f"{stage} stop"
            if where not in QR.vocabulary()["where"]:
                return                      # no stop is defined for this stage: the vocabulary says which stages
            if stage == "S4" and role != "qa-case-designer":
                return
            plan_lines = self.apply_question_answers(stage)["plan_lines"]
            found = QS.over_threshold(self.task_root, self.config)
            blocking = QS.blocking_stop(self.task_root)
        except Exception as exc:            # a malformed register, a missing thresholds file: told, not stopped on
            print(f"note: the question threshold was not checked at {stage} ({type(exc).__name__}: {exc}); the stage goes on")
            return
        for warning in found.get("warnings") or []:
            print(f"note: {warning}")
        count, share = found.get("count"), found.get("share")
        earlier = self.state.get("question_stop") or {}
        answered = earlier.get("answered") if isinstance(earlier.get("answered"), dict) else None
        hashes = self.register_hashes()
        blocked = self.blockers_to_stop_on(blocking, answered, hashes)
        count_stop = bool(found.get("over")) and self.count_stop_stands(stage, count, share, answered)
        if not count_stop and not blocked:
            return
        reasons = (["blocking"] if blocked else []) + (["over_threshold"] if count_stop else [])
        options = [
            {"answer": "answers", "says": "answer the questions above, one line each; the role goes on in its own session "
                                          "with your answers", "slots": {"role": f"the {self.role_words(role)}"}},
            {"answer": "go on", "token": "go on", "says": "go on with these questions still open; your word is recorded as the pass"},
            self.STOP_OPTION]
        section = self.priced_section("questions.blocking", options) if blocked else self.priced_section("questions", options)
        try:
            reason = "blocking" if blocked and not count_stop else "over_threshold"
            if blocked and count_stop:          # both stand: the blocking words first, then the count's own lines, one reason
                said = QS.defaults()["reason_words"]
                reason = " ".join([said["blocking"].rstrip(".") + ".", said["over_threshold"].rstrip(".") + ".",
                                   *found["reasons"], *found["warnings"]])
            body = QS.batch_text(self.task_root, reason, priced=section,
                                 previous_answer_at=None if answered is None else self.question_when(answered.get("at")))
            if blocked and count_stop and body.strip():
                body = body.rstrip("\n") + "\n" + QS.BLOCKING_NOTE + "\n"
            text = Priced(body, section.priced)
        except Exception as exc:
            text = ""
            print(f"note: the batch of questions could not be written ({type(exc).__name__}: {exc})")
        if not text.strip():
            print(f"note: {stage} is over the question threshold but there is no open question to show; the stage goes on")
            return
        self.state["question_stop"] = {"stage": stage, "dispatch": dispatch, "count": count, "share": share, "at": _now(),
                                       "shown": hashes, "reasons": reasons,
                                       "blocking_ids_shown": {qid: hashes.get(qid, "") for qid in blocking.get("ids") or []}}
        if answered is not None:
            self.state["question_stop"]["answered"] = answered
        if plan_lines:
            self.state.setdefault("question_pass_lines", {})[dispatch] = plan_lines      # H36: the resumed role is told what code changed
        self.state["pending_words"].pop(dispatch, None)      # a stale answer must not resume a NEW question
        self.save_state()
        # T1 (C1-7b): the Person is raised either way; a later running/done write supersedes the record, and a retry after a resume
        # would write a stale halt. F-4 (t-1252): NOT `HALT_RECORD_WHY` - that text says the role is not run again, and on THIS road it
        # is (`resume_role` runs it on the person's answer), so the text names the threshold road in one clause. H29 (m4): the digest
        # says what the stop was for - `halts[].reason` reads it; the `why` is unchanged.
        digest = (f"stopped on {len(blocking.get('ids') or [])} blocking question(s): {', '.join(blocking.get('ids') or [])}"
                  + (f" and {count} open question(s)" if count_stop else "")) if blocked else \
            f"stopped on the question threshold: {count} open question(s)"
        self.py_trace("stage_done.py", "--task", self.task, "--stage", stage, "--status", "halted", "--role", role,
                      "--digest", digest,
                      why="the question-threshold stop (the role finished and code stopped it; it resumes on the person's answer): the Person is "
                          "raised either way; a later running/done write supersedes the record, and a retry after a resume would write a stale halt")
        raise Person("questions", text, stage, dispatch)

    def register_hashes(self) -> dict:
        """`{question id: the hash of its row today}` of the register, `{}` when it cannot be read: what a stop SHOWS and what a
        person's answer is stamped with. An id with no hash here never matches a passed blocker (FR-59)."""
        try:
            import question_register as QR
            return {q["id"]: q.get("row_hash") or "" for q in QR.load(self.task_root)["questions"]}
        except Exception:
            return {}                       # the answer then takes the row's hash as it is when answered

    @staticmethod
    def blockers_to_stop_on(blocking: dict, answered, hashes: dict) -> list:
        """The ids of the open blockers (`question_stop.blocking_stop`) that no `go on` passed ON THESE BYTES: `answered.blocking_ids`
        holds `{id: the row hash that was passed}`, and an id missing there, or with another hash, is stopped on again (H44). A token
        answer never adds to it (H26), so a blocker the person left alone is asked again."""
        if not blocking.get("stop"):
            return []
        passed = (answered or {}).get("blocking_ids")
        passed = passed if isinstance(passed, dict) else {}
        return [qid for qid in blocking.get("ids") or [] if not passed.get(qid) or passed.get(qid) != hashes.get(qid)]

    def count_stop_stands(self, stage: str, count, share, answered) -> bool:
        """Does the COUNT stop the stage? Not when the person answered at this count and share (Q8: their answer is the pass for
        THAT count, only a larger one is a new fact), and not when the stage carries the person's recorded pass of the question
        threshold. Neither early return touches the blocking check (M1)."""
        if answered is not None and not self.larger_than_answered(count, share, answered):
            print(f"{stage}: {count} question(s) are open, as when the person answered at "
                  f"{self.question_when(answered.get('at'))}: their answer is the pass, no second stop")
            return False
        try:
            _blocking, passed = waiver.split_overridden(
                [f"{waiver.QUESTION_THRESHOLD_BLOCK}: {count} open question(s) at {stage}"], self.pipeline(), stage)
        except Exception as exc:
            passed = []
            print(f"note: the person's pass for the question threshold could not be read ({type(exc).__name__}: {exc})")
        if passed:
            print(f"{stage}: the question threshold is passed by the person's word "
                  f"({' / '.join(str(p.get('decision')) for p in passed)[:300]}); the stage goes on")
            return False
        return True

    def question_resume_prompt(self, dispatch: str, words: str) -> str:
        """The text of a role resumed on the person's answers to a threshold stop. H36: when code changed the plan rows to follow those
        answers (`apply_question_answers`), the role is told what changed and to read the plan again - a role that kept its own copy of
        the plan in its context would overwrite the change."""
        told = (self.state.get("question_pass_lines") or {}).pop(dispatch, None)
        changed = ("\n" + "\n".join(str(line) for line in told) + "\nthe plan rows above were changed by code to follow the "
                    "answers; read work/test-plan.json again before you edit it.\n") if told else ""
        return (f"The person answered the open questions: \"{words.strip()}\". Their answers are recorded; "
                f"continue your dispatch {dispatch} on them — do not ask them again. " + changed +
                "Your final message is the handoff form only:\n" + HANDOFF_FORM)

    def question_rework(self, stage: str, role: str, dispatch: str, words: str, complete, why: str) -> tuple:
        """R17, FR-57: no session to resume (or it failed) - the SAME dispatch runs in a new session as a
        rework whose reason is the person's words, verbatim, and the role continues its interrupted
        artifacts. `controller rework` is not the door: it needs an ACCEPTED dispatch of the role and a
        stop comes before `finish`. The saved result is set aside (not deleted): `run_role` would
        otherwise reuse it and the role would never see the words."""
        print(f"{stage}: {why}; the role goes on in a new session with the person's words as the reason")
        saved = self.state_dir / "driver-runs" / f"{dispatch}.json"
        if saved.is_file():
            saved.replace(saved.with_suffix(".stopped.json"))
        stop = self.state.get("question_stop") or {}
        stop.pop("resume", None)
        self.state["pending_words"].pop(dispatch, None)
        self.save_state()
        record = (self.controller_state().get("dispatches") or {}).get(dispatch) or {}
        scope = list(record.get("scope") or [])
        return self.run_role(stage, role, scope=scope, complete=complete,
                             rework={"id": dispatch, "scope": scope, "reason": words})

    def take_question_answer(self, stage: str, dispatch: str, words: str) -> None:
        """R17: the person's words at a threshold stop. Closed tokens (`Q1: a`, `Q2: not needed`) become
        answer records by code, `where` = `<stage> stop`; the whole words go to the role's own session.
        Nothing here calls the conductor (FR-48). It errs toward NOT recording: an id that is not open, a
        letter beyond the readings, two answers for one question stay with the role, which reads meaning
        (FR-12) - and are printed back, so the person is never left guessing (never a dead end).

        The answer is the informed pass (Q8): the count and share the person was shown are kept - and the blockers they were
        passed ON (`blocking_ids`) are kept as they were: only a `go on` adds to them (H26). HF2-7: the lines are read by
        `question_register.record_answers` over the WHOLE register (an `until the report` line is a word too), and the recorded
        answers are applied to the plan by code in the same move (`apply_question_answers`)."""
        stop = self.state.get("question_stop")
        if not isinstance(stop, dict):
            stop = self.state["question_stop"] = {}
        # F11: the WHOLE answer `go on` or `stop` is read before the choices (`go on` inside other words stays the choices
        # road below, FR-12). Neither files the words for the role: `pending_words` stays empty.
        token = self.s0_normalize(words)
        if token in ("go on", "stop"):
            self.answer_row(f"{stage} question stop ({token}): ", words.strip(), what="your answer at the question stop")
            if token == "stop":
                raise self.held_question(self.stop_held("If you want the factory to go on after all, answer the questions or `go on`."))
            # N9 (FR-4): the pass is recorded for what the person was SHOWN. The count's waiver only when the stop they read was for the
            # count (`over_threshold` among its reasons; a stop recorded before the reasons existed was a count's); the blockers they read
            # are passed by `blocking_ids`, each on the bytes it was shown with (H44) - a stop for blockers alone writes no waiver.
            if "over_threshold" in (stop.get("reasons") or ["over_threshold"]):
                code, out = self.py("waiver.py", "--task", self.task, "--stage", stage, "--block", waiver.QUESTION_THRESHOLD_BLOCK,
                                    "--words-file", str(self.task_root / self.answer_file()), *self.waiver_road())
                if code:
                    print(f"{stage}: the pass was not recorded ({out[-300:]}); the question comes back")
                    raise self.held_question("Your word could not be recorded as the pass, so nothing was passed.")
            print(f"{stage}: going on with the questions open, on the person's word; recorded")
            stop["answered"] = {"count": stop.get("count"), "share": stop.get("share"), "at": _now(),
                                "blocking_ids": {**self.passed_blockers(stop), **(stop.get("blocking_ids_shown") or {})}}
            self.state["pending_words"].pop(dispatch, None)
            return
        self.record_question_words(stage, words, stop.get("shown") if isinstance(stop.get("shown"), dict) else {})
        told = self.apply_question_answers(stage)["plan_lines"]
        if told:
            self.state.setdefault("question_pass_lines", {}).setdefault(dispatch, []).extend(told)      # H36: for the resumed role
        stop["answered"] = {"count": stop.get("count"), "share": stop.get("share"), "at": _now(),
                            "blocking_ids": self.passed_blockers(stop)}
        stop["resume"] = True
        self.state["pending_words"][dispatch] = words
        self.answer_row(f"{stage} question stop: ", words, what="your answers at the question stop")

    @staticmethod
    def passed_blockers(stop: dict) -> dict:
        """`{id: row hash}` of the blockers a `go on` of this stop passed, `{}` when none (a stop recorded before they were kept)."""
        passed = (stop.get("answered") or {}).get("blocking_ids") if isinstance(stop.get("answered"), dict) else None
        return dict(passed) if isinstance(passed, dict) else {}

    def record_question_words(self, stage: str, words: str, shown: dict) -> dict:
        """The person's words at a stop of `stage` (the threshold's or a halt's), turned into answer records by `question_register.
        record_answers` - the ONE move (AR-14): `where` = `<stage> stop`, `shown` the row hashes the person was shown, the story's own case
        ids so a `<case id>: manual|automate|accept as blocked` line is the word about a CASE it is (t-261). What was done is PRINTED, so
        the person is never left guessing: the lines recorded, the lines kept open on their word (`until the report`), the lines not
        read and why, an id the register does not hold (FR-59: never a guess), a decision inside a fenced block, a word about a case (a
        stop decides no case, gate A does). Returns `record_answers`' dict; a failure to read the register is printed and gives
        the empty one (`all_tokens` False): the words still go on, a failure to read them is not a dead end."""
        import question_register as QR
        read = {"recorded": [], "unread": [], "unknown_ids": [], "deferred": [], "all_tokens": False, "fenced": []}
        try:
            try:
                import gate_brief
                case_ids = list(gate_brief.story_cases(self.task_root)[0])
            except Exception:
                case_ids = []
            read = QR.record_answers(self.task_root, words, f"{stage} stop", self.QUESTION_ANSWER_BY, shown, case_ids)
            for notice in QR.fence_notices(read):
                print(f"{stage}: {notice}")
            for token in QR.parse_choices(words, QR.load(self.task_root)["questions"], case_ids).get("case_tokens") or []:
                print(f"{stage}: `{token['written']}: {token['decision']}` is a word about a case; a question stop "
                      "decides no case, so it goes to the role with your words; say it again at gate A for it to be applied")
            if read["unknown_ids"]:
                print(f"{stage}: not recognised as open questions, so nothing is recorded for them: "
                      + ", ".join(read["unknown_ids"]))
        except Exception as exc:
            print(f"note: the answers could not be read against the register ({type(exc).__name__}: {exc}); "
                  "the role gets the words whole")
        print(f"{stage}: recorded by code — " + (", ".join(read["recorded"]) if read["recorded"] else "no question answered by a token"))
        if read["deferred"]:
            print(f"{stage}: kept open until the report, on your word: " + ", ".join(read["deferred"]))
        if read["unread"]:
            print(f"{stage}: not read as an answer, so still open: " + "; ".join(read["unread"]))
        return read

    def record_halt_words(self, stage: str, words: str):
        """B2: the person's answer to a HALT at S2-S4 over a register that holds questions, recorded by code before anyone else reads it:
        the lines through `record_question_words` (`where` = `<stage> stop`), the words journalled as a `human_answer` (FR-8, once), the
        recorded answers laid over the plan (`apply_question_answers`). Returns `record_answers`' dict, or None when this is not such a
        halt (a stage with no stop, no register, no question in it, or a register that cannot be read): the halt then goes on its old
        road unchanged. POSITION INVARIANT: before the conductor and the judge are called, so a token the code read never reaches the
        conductor as 'not recorded' (FR-48)."""
        try:
            import question_register as QR
            if f"{stage} stop" not in QR.vocabulary()["where"] or not QR.load(self.task_root)["questions"]:
                return None
        except Exception:
            return None
        read = self.record_question_words(stage, words, {})
        self.answer_row(f"{stage} halt: ", words.strip(), what="your answer at the halt")
        self.apply_question_answers(stage)
        return read

    # --- HF2-7: an answer recorded AFTER the work that rests on the question was written (the owner's word of 24.10) --------------------

    def apply_question_answers(self, stage: str) -> dict:
        """Lay the answers recorded in the register over the plan, by CODE, at a stop of `stage` (S2-S4) or at gate A (`"A"`), and open the
        rework of whoever wrote what still follows the other reading. `planning_contract.apply_recorded_answers` does the applying
        (it patches the plan rows the answer decides, once per record, never an approved plan, never a changed row); what it names
        for an owner goes to `state["answer_rework"]` (`merge_answer_rework`), which `answer_rework_step` carries out from the loop -
        code opens the rework, the conductor is not called (FR-48). Returns `{"opened": a rework is now owed, "plan_lines": what code
        changed in the plan, for the role that holds a copy of it (H36)}`. It never raises: a failure is a line and the next stop tries
        again (P1). INVARIANT (F-13): the callers are the thresholds AFTER their `where` check and `gate_repair("A")` after the
        open-packet and kept-answer returns - never under a gate A packet the person is reading, whose plan must not change."""
        out = {"opened": False, "plan_lines": []}
        label = "gate A" if stage == "A" else stage
        try:
            import planning_contract as PC
            got = PC.apply_recorded_answers(self.task_root, "gate A" if stage == "A" else f"{stage} stop")
            for line in got["lines"]:
                print(f"{label}: {line}")
            if any(isinstance(r, dict) and r.get("rows") for r in got["applied"]):
                out["plan_lines"] = [str(line) for line in got["lines"]]
            # the answer the person gives NOW, per question: a rework still waiting for another answer to it is replaced, never
            # sent (HF3-10, M3). Only an answer the plan was asked to follow counts - not one refused (a changed row, an approved plan).
            intents = [r for r in got["applied"] if PC.plan_intent(r) and isinstance(r.get("id"), str) and isinstance(r.get("answer"), str)]
            current = {r["id"]: r["answer"] for r in intents}
            # own words carry no letter, so only the record of them tells one answer from the next (HF3-10, F6)
            current_at = {r["id"]: str(r.get("record_at") or "") for r in intents if r["answer"] == ""}
            if got["rework"] or current:
                out["opened"] = self.merge_answer_rework(got["rework"], current, current_at)
        except Exception as exc:
            print(f"note: your recorded answers could not be applied to the plan ({type(exc).__name__}: {exc}); "
                  "they are tried again at the next stop")
        return out

    @staticmethod
    def answer_supersede(items: list, current, current_at=None) -> list:
        """HF3-10 (M3): `items` (of `state["answer_rework"]`) with the part that waits for an answer the person no longer gives taken out.
        `current` = {question id: the answer given now}. For each such id the questions of an item with ANOTHER answer go, and the pairs
        of that id with them (unless a question of the id with the current answer stays); a row or case that HAD pairs and has none left
        goes; an item with no question left goes. A row or case of an item written before pairs existed (no pair at all) stays - only its
        questions go (E14). `current_at` = {question id: the register record of the answer given now}, for an answer in the person's
        OWN WORDS only (it has no letter, so the record tells it from the words before): an entry of those words with another
        `record_at` is the earlier words and goes, so words given twice leave ONE line for the question (F6); no `current_at` entry
        for an id: equal answers are the same answer. Pure: a new list, the input is not changed; an empty or no-dict `current` gives
        the input back. INVARIANT: a role is never told an answer the person has since replaced - the caller passes only the items
        nobody has started."""
        if not isinstance(current, dict) or not current:
            return items
        at_of = current_at if isinstance(current_at, dict) else {}

        def without_replaced(questions: list, pairs: list, qid, answer) -> tuple:
            """(questions, pairs) minus the entries of `qid` that hold another answer, and minus the pairs of `qid` once none stays."""
            at = at_of.get(qid) if answer == "" else None

            def same(entry: dict) -> bool:
                return entry.get("answer") == answer and (not at or entry.get("record_at") == at)
            kept = [a for a in questions if a.get("id") != qid or same(a)]
            if len(kept) != len(questions) and not any(a.get("id") == qid for a in kept):
                pairs = [p for p in pairs if p.get("question") != qid]
            return kept, pairs
        out = []
        for item in items:
            pairs = [p for p in item.get("pairs") or [] if isinstance(p, dict)]
            questions = [dict(a) for a in item.get("questions") or [] if isinstance(a, dict)]
            for qid, answer in current.items():
                questions, pairs = without_replaced(questions, pairs, qid, answer)
            if not questions:
                continue
            had = {p.get("where") for p in item.get("pairs") or [] if isinstance(p, dict)}
            left = {p.get("where") for p in pairs}
            fresh = dict(item, questions=questions)
            if "pairs" in item:
                fresh["pairs"] = pairs
            for where in ("rows", "cases"):
                if where in item:
                    fresh[where] = [w for w in item[where] if w not in had or w in left]
            out.append(fresh)
        return out

    def merge_answer_rework(self, rework: list, current=None, current_at=None) -> bool:
        """Put the rework `apply_recorded_answers` named into `state["answer_rework"]["items"]` - ONE item per (stage, role): `{stage, role,
        rows | cases, questions: [{id, answer, record_at, was?}], pairs: [{question, where, seen}], words_file, before}`, the strategist's
        (S3) first, then the designer's (S4) (H40). `before` = the controller's `question_answer` dispatches of that stage already there, so
        the step finds its OWN dispatch (P22); an item whose dispatch is registered but not yet dropped (a crash between the two) is never
        added to or replaced - a new item starts. Returns whether anything was added. The `words_file` is the person's words, whole (C16).

        HF3-10 (H41): FIRST the unregistered items give way to `current` ({id: the answer given now}, `current_at` {id: the record of
        own words}, `answer_supersede`), THEN the new entries are added - a new answer never displaces itself. `pairs` hold, per (question,
        row or case), whether the branch check NAMED that pair when the rework was named (`seen`), on the plan as the applier left it (this
        runs after `apply_recorded_answers`): only a pair seen and later not named lets the step drop the work (`answer_pairs_owed`). The
        check is read ONCE per call, whenever `rework` is not empty; one that could not be read marks every pair unseen (FR-59)."""
        import controller as C
        owners = {owner: (stage, role) for owner, (stage, role, _flag) in C.ANSWER_REWORK_OWNERS.items()}       # the controller's one table (F-12)
        record = self.state.get("answer_rework")
        items = [i for i in (record.get("items") if isinstance(record, dict) else None) or [] if isinstance(i, dict)]
        dispatches = self.controller_state().get("dispatches") or {} if (self.state_dir / "controller.json").is_file() else {}
        gone = [self.answer_rework_registered(i, dispatches) for i in items]       # registered: the controller has it, not touched
        items = [i for i, g in zip(items, gone) if g] + self.answer_supersede([i for i, g in zip(items, gone) if not g], current, current_at)
        registered = sum(gone)                  # the registered items are the first `registered` of `items`; every other one is open to adds
        findings = self.question_branch_findings() if rework else None
        named = {(f.get("question"), f.get("where")) for f in findings or [] if isinstance(f, dict)}
        merged = False
        for entry in rework:
            found = owners.get(entry.get("owner")) if isinstance(entry, dict) else None
            if found is None:
                print(f"note: a rework for {entry.get('owner') if isinstance(entry, dict) else entry!r} is not one the driver can start; "
                      "gate A names it")
                continue
            stage, role = found
            item = next((i for n, i in enumerate(items) if n >= registered and (i.get("stage"), i.get("role")) == found), None)
            if item is None:
                item = {"stage": stage, "role": role, "rows": [], "cases": [], "questions": [], "pairs": [], "words_file": "",
                        "before": sorted(self.answer_rework_dispatches(dispatches, stage))}
                items.append(item)
            where = "rows" if stage == "S3" else "cases"
            if entry["where"] not in item[where]:
                item[where].append(entry["where"])
            pairs = item.setdefault("pairs", [])
            if not any(isinstance(p, dict) and (p.get("question"), p.get("where")) == (entry["question"], entry["where"]) for p in pairs):
                pairs.append({"question": entry["question"], "where": entry["where"], "seen": (entry["question"], entry["where"]) in named})
            asked = {"id": entry["question"], "answer": entry["answer"], "record_at": entry["record_at"]}
            if isinstance(entry.get("was"), str):
                asked["was"] = entry["was"]
            if asked not in item["questions"]:
                item["questions"].append(asked)
            merged = True
        items.sort(key=lambda i: 0 if i.get("stage") == "S3" else 1)
        for item in items:
            item["words_file"] = self.answer_item_words(item)
        if items:
            self.state["answer_rework"] = {"items": items}
            self.save_state()
        elif record is not None:
            # the replacement left nothing owed (E20): no empty record stays. Not `drop_record` (a higher layer, L5): this is the record's owner
            self.state.pop("answer_rework", None)
            self.save_state()
        return merged

    def answer_rework_dispatches(self, dispatches: dict, stage: str) -> dict:
        """The controller's `question_answer` reworks of `stage`, of either origin (the person's words by file, or the driver's own reason)."""
        return {**self.rework_dispatches(dispatches, "question_answer", by_person=True, stage=stage),
                **self.rework_dispatches(dispatches, "question_answer", by_person=False, stage=stage)}

    def answer_rework_registered(self, item: dict, dispatches: dict) -> bool:
        """Has the controller registered THIS item's rework (a `question_answer` dispatch of its stage that is not in its `before`)?"""
        return any(did not in (item.get("before") or []) for did in self.answer_rework_dispatches(dispatches, str(item.get("stage"))))

    def answer_item_words(self, item: dict) -> str:
        """The task-root relative file of the person's words behind an item, whole (FR-8, C16): the words of the records of its questions.
        The answer being taken now is its own file (`answer_file`); words of another time (an answer recorded by the command line) are
        written ONCE (`words_file`) and the file is kept while it holds the same words. '' with no words: the step then gives the role a
        reason of the driver's own (no file is made of nothing)."""
        import question_register as QR

        def flat(text: str) -> str:
            return text.replace("\r\n", "\n").strip()
        by_id = {q["id"]: q for q in QR.load(self.task_root)["questions"]}
        said = []
        for asked in item["questions"]:
            text = str((by_id.get(asked["id"]) or {}).get("words") or "")
            if text.strip() and text not in said:
                said.append(text)
        text = "\n\n".join(said)
        if not text.strip():
            return ""
        if self._answer and flat(str(self._answer.get("text") or "")) == flat(text):
            return self.answer_file()
        old = str(item.get("words_file") or "")
        try:
            if old and flat((self.task_root / old).read_text(encoding="utf-8")) == flat(text):
                return old
        except OSError:
            pass
        path = self.words_file(text, "questionanswer")
        return path.relative_to(self.task_root).as_posix() if path else ""

    def question_branch_findings(self):
        """The findings of the gate rehearsal's question-branch check (`gate_preflight.Rehearsal.check_question_branches`: the ONE reader,
        `planning_contract.variant_errors` under it) over the plan and the cases as they are NOW, as `[finding]`; None when that could
        not be established (the check could not run, or it said it did not check) - an unknown never drops owed work (FR-59)."""
        try:
            import gate_preflight
            rehearsal = gate_preflight.Rehearsal(self.task_root, "A")
            rehearsal.check_question_branches()
        except Exception:
            return None
        if any(f.get("check") == "question_branches" and f.get("class") == gate_preflight.FACTORY_DEFECT for f in rehearsal.findings):
            return None
        if any(i.get("check") == "question_branches" for i in rehearsal.info):
            return None
        return [f for f in rehearsal.findings if f.get("check") == "question_branches"]

    def _defaulted_vcs(self) -> bool:
        """Does the summary hold a gap by default whose carrier is a collector receipt (`host_unreachable`)? False when the
        inventory cannot be read - then nothing is retried that was not retried before."""
        import source_inventory as SI
        try:
            inventory = SI.load_inventory(self.task_root / "work" / "source-inventory.json")
            summary = SI.completeness(inventory, **SI.class_kwargs(self.task_root))
        except Exception:
            return False
        return any(point.get("cause") == "host_unreachable"
                   for points in (summary.get("defaulted_points") or {}).values() for point in points)

    def refusal_sid(self, dispatch: str, fallback: str = "") -> str:
        """The session a dispatch's resume record is keyed by (C3): the one the driver stored for it
        (`sessions[dispatch]`), else `fallback` (the saved result's own). A new session recorded for the same
        dispatch (a rework in a new session, a call continued after an interruption) starts an empty record, and so
        gets its own one resume."""
        return str(self.state["sessions"].get(dispatch) or fallback or "")

    def resume_record(self, dispatch: str, sid: str) -> dict:
        """`{finding key: why}` for one dispatch and session, read-only; {} when nothing was recorded (a state file
        written before t-217 has no `refusal_resumes`: an in-flight story gets one resume)."""
        by_session = (self.state.get("refusal_resumes") or {}).get(dispatch) if isinstance(
            self.state.get("refusal_resumes"), dict) else None
        record = by_session.get(sid) if isinstance(by_session, dict) else None
        return record if isinstance(record, dict) else {}

    def note_resume(self, dispatch: str, sid: str, key: str, why: str) -> None:
        """Write one resume into `refusal_resumes[dispatch][sid][key] = why` (why: handoff | refusal | stand) and
        save it - called BEFORE the paid call, so that a crash costs one resume and never repeats one."""
        held = self.state.get("refusal_resumes")
        if not isinstance(held, dict):
            held = self.state["refusal_resumes"] = {}
        by_session = held.get(dispatch)
        if not isinstance(by_session, dict):
            by_session = held[dispatch] = {}
        record = by_session.get(sid)
        if not isinstance(record, dict):
            record = by_session[sid] = {}
        record[key] = why
        self.save_state()

    def forget_resumes(self, dispatch: str) -> None:
        """The dispatch was accepted: its record leaves (state-exits.md). A dispatch that is released, or never
        accepted, keeps it - it is terminal, and nothing reads it once the dispatch is gone."""
        held = self.state.get("refusal_resumes")
        changed = isinstance(held, dict) and held.pop(dispatch, None) is not None
        limits = self.state.get("exit_limit")
        if isinstance(limits, dict) and not (limits.get(dispatch) or {}).get("passes") and limits.pop(dispatch, None) is not None:
            changed = True          # t-764 A5: the seam's state leaves with it - unless a pass is still to be revoked (the sweep retries)
        if changed:
            self.save_state()

    def dispatch_role(self, dispatch: str) -> str:
        try:
            role = str(((self.controller_state().get("dispatches") or {}).get(dispatch) or {}).get("role") or "")
        except Exception:
            role = ""
        return role or (re.fullmatch(r"S\d+-(qa-[a-z-]+)-\d+", dispatch) or [None, ""])[1]

    RESUME_SENTENCE = ("Repair the named fields in the artifact, change nothing else, then your final "
                       "message is the handoff form only.")

    def resume_with(self, refusal: Refusal, stage: str, dispatch: str, sid: str, lead: str, reason: str = "",
                    sentence: str | None = None) -> None:
        """ONE resume of the role's own session: `lead`, the refusal whole, the sentence. The result is the
        dispatch's saved result from now on (the loop comes back through `where` -> `wait_existing_job` ->
        `handoff` -> `finish` on THIS result, not on the one the refusal was about). A resume that returns an
        error and no words is spent and is the person's: the session is gone, and the ONE seam `exit_limit` says so (t-764
        F-d6, E10: no round - an offered option is never silently unexecutable). `reason` (t-342, B-273) is the line
        the log prints; with none, the refusal's own findings are classified (`resume_reason`). `sentence`: what closes the
        prompt in place of RESUME_SENTENCE (t-764: the paid round's text already says what to do; "" closes with nothing)."""
        closing = self.RESUME_SENTENCE if sentence is None else sentence
        prompt = lead + refusal.text.strip() + (("\n\n" + closing) if closing else "")
        self.progress_line()            # t-323 B1: the role's own session is asked again: a launch like any other
        result = self.run_claude("role", prompt, role=self.dispatch_role(dispatch), dispatch=dispatch, stage=stage,
                                 resume=sid,
                                 resume_reason=reason or "the factory refused to close the dispatch: "
                                 + resume_reason(refusal.findings or refusal.text))
        if result.get("is_error") and not str(result.get("result") or "").strip():
            self.exit_limit(stage, self.dispatch_role(dispatch), dispatch, self.refusal_lines(refusal), sid=sid, why="session_gone",
                            error=str(result.get("stderr") or "")[-600:], text=refusal.text)
        _write_json(self.state_dir / "driver-runs" / f"{dispatch}.json", result)
        self.state["pending_words"].pop(dispatch, None)     # t-764 A12: the role answered them in THIS result, before anyone judges it
        self.save_state()
        self.progress_line()            # t-323 B1: the resume returned and its result is the dispatch's now

    def assemble_digest(self, role: str, stage: str, dispatch: str, result: dict) -> tuple:
        """(digest, "") or ("", why not): the handoff form built by code from what the role already wrote (t-342, B-273).

        The form is a header (`<role> <stage> <window> · <verdict>`), one row per item (`<id> · <state> · <reason>`)
        and the path of the artifact. All of it is already in the role's HANDOVER FORM (`work/handoffs/<dispatch>.yaml`:
        `header`, `scope[]`) and in its last message or artifacts (the path); nothing here is decided by code - every
        value is the role's own, copied. It is assembled only when EVERY field is there: a verdict that is a real
        non-halting one (a halt is the role's word to the person and is never written for it), every row filled
        (id, state, a reason no longer than the form allows - code never rewrites a role's words; a field `--shorten` cut
        carries its mark and the path to the whole text, C2-4), a path that is a
        file on disk and not absolute, and a digest that fits `DIGEST_MAX` whole (a cut digest would lose its path
        line). Anything missing is the reason returned, and the caller resumes the role as before. The caller then
        judges the result with the same exit gate as a role's own message.

        The last line `assembled_by: code` is the trace (FR-8/P13): it follows the form's path line, so the form is
        read as always and the line is kept as a note of the digest, which is what `finish` records."""
        form = self.task_root / "work" / "handoffs" / f"{dispatch}.yaml"
        if not form.is_file():
            return "", "the role wrote no handover form"
        try:
            import handoff
            import handoff_check
            import role_digest
            doc = handoff_check.form_view(form)      # the form plus its waiting values file (SC1-2, B-1)
        except Exception as exc:
            return "", f"the handover form cannot be read ({type(exc).__name__})"
        if not str(result.get("result") or "").strip():
            return "", "the role's final message is empty"
        # critic t-346 F1 (FR-47): a halt in the role's own message is the role's word to the person - the YAML's `ok`
        # never overwrites it - and so is any header verdict the message states that the form does not.
        message = str(result.get("result") or "")
        if role_digest.is_halting(message):
            return "", "the role's own message halts: a halt is its word to the person and code never writes over it"
        said = ""
        for line in role_digest._lines(message):
            header, error = role_digest._parse_header(line)
            if not error and header.get("verdict"):
                said = {"done": "ok", "review": "concerns"}.get(header["verdict"], header["verdict"])
                break
        verdict = str(doc.get("header.verdict") or "").strip()
        if said and verdict and said != verdict:
            return "", f"the role's message says `{said}` and its form says `{verdict}`: that is the role's to settle"
        window = str(doc.get("header.window") or "").strip()
        if handoff.is_placeholder(verdict) or handoff.is_placeholder(window):
            return "", "the form's header is not filled (verdict or window)"
        if verdict not in role_digest.HEADER_VERDICTS or verdict in role_digest.HALTING_VERDICTS:
            return "", (f"the form's verdict is `{verdict}`: a halt is the role's own word to the person, and a word "
                        "outside the closed list is its own to correct - code writes neither for it")
        rows = []
        for index in doc.rows("scope"):
            row_id = str(doc.get(f"scope[{index}].id") or "").strip()
            state = str(doc.get(f"scope[{index}].state") or "").strip()
            reason = str(doc.get(f"scope[{index}].reason") or "").strip()
            if handoff.is_placeholder(row_id) or handoff.is_placeholder(state):
                return "", f"row {index + 1} of the form is not filled"
            reason = "" if handoff.is_placeholder(reason) else reason
            if len(reason) > role_digest.REASON_MAX:
                return "", f"the reason of {row_id} is {len(reason)} characters, the form allows {role_digest.REASON_MAX}"
            rows.append(f"{row_id} · {state}" + (f" · {reason}" if reason else ""))
        if not rows:
            return "", "the handover form lists no rows"
        # t-363 B5 (B-287, critic t-346 F5): the form's own `artifacts.*` field comes FIRST and the role's PROSE only
        # when the field is empty - structure outranks prose (FR-49, P4); the last existing file named in the prose
        # used to win over the field. INVARIANT of the position: a role's prose never overrides what its own form
        # says, so a field that names a file that is not there is REPORTED missing (FR-37) and the prose path is not
        # used in its place - a wrong form is the role's defect to correct, not a guess for the driver. A field and
        # a prose path that disagree: the field is used and the ignored prose path is named in a `[driver]` note.
        def prose_path() -> str:
            for candidate in reversed(PATH_RE.findall(str(result.get("result") or ""))):
                rel = candidate.replace("\\", "/")
                if rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):
                    continue              # a digest names a path relative to the task or the project, never absolute
                if (self.task_root / rel).is_file() or (self.project / rel).is_file():
                    return rel
            return ""

        fields = [str(node.value or "").strip() for node_path, node in doc.nodes.items()
                  if node_path.startswith("artifacts.") and not handoff.is_placeholder(str(node.value or "").strip())]
        path = ""
        if fields:
            path = next((v for v in fields if not (v.replace("\\", "/").startswith("/") or re.match(r"^[A-Za-z]:", v))
                         and (self.task_root / v).is_file()), "")
            if not path:
                return "", (f"the form's artifact path `{'`, `'.join(fields)}` is not a relative path of a file on disk "
                            "(a path named in the role's message is not used in its place: the form is the role's to correct)")
            ignored = prose_path()
            same = ignored and ({(self.task_root / ignored).resolve(), (self.project / ignored).resolve()}
                                & {(self.task_root / path).resolve()})      # one file spelled two ways is not a disagreement
            if ignored and not same:
                print(f"[driver] {dispatch}: the form's artifact path {path} is used; the path the role's message names "
                      f"({ignored}) is ignored - the form's own field comes first", flush=True)
        else:
            path = prose_path()
        if not path:
            return "", "no artifact path of the role is a file on disk"
        digest = "\n".join([f"{role} {stage} {window} · {verdict}", *rows, path, "assembled_by: code"])
        if len(digest) > DIGEST_MAX:
            return "", f"the assembled form is {len(digest)} characters and the digest limit is {DIGEST_MAX}"
        if len(digest.splitlines()) > 40:        # `digest_of` keeps the last 40 lines of what it reads back
            return "", (f"the assembled form is {len(digest.splitlines())} lines and a digest keeps the last 40 "
                        "(its header would be cut when it is read back)")
        return digest, ""

    def keep_assembled_result(self, dispatch: str, result: dict, digest: str) -> None:
        """The assembled digest is the dispatch's saved result from now on, `assembled_by: code` on the record and the
        role's own last message kept whole beside it (`role_final_message`): a re-entry through `wait_existing_job`
        judges the digest, and nobody has to take the code's word that the role said something else."""
        _write_json(self.state_dir / "driver-runs" / f"{dispatch}.json",
                    dict(result, result=digest, assembled_by="code", role_final_message=str(result.get("result") or "")))

    def keep_resumed_result(self, dispatch: str, resumed: dict, before: dict) -> None:
        """The role's NEW words are the dispatch's saved result from now on (t-217 O1, critic t-244).

        `handoff`'s own in-session resumes (`again`, `third`) used to leave `state/driver-runs/<dispatch>.json` holding the
        FIRST result. After a conductor `continue` on the still-open dispatch, `wait_existing_job` re-judged that stale
        result, found its finding set already in `refusal_resumes`, and raised a false "came back with the same findings"
        question - before the resume record existed another resume would have repaired it. `resume_with` already does
        this for the refusal's resume (its rule: an error with no words is spent and not written); this is the same rule
        at the handoff's two resumes. Callers pass only a non-empty `result`; the session id of the first result stays
        when the resume reports none (a result with no session cannot be bound or resumed again)."""
        if not str(resumed.get("result") or "").strip():
            return
        _write_json(self.state_dir / "driver-runs" / f"{dispatch}.json",
                    dict(resumed, session_id=resumed.get("session_id") or before.get("session_id") or ""))

    def code_doors(self, stage: str, role: str, dispatch: str) -> list:
        """C2-4 (K9): run the doors of CODE that a role would otherwise be paid to walk, and return the names of those that WROTE.

        Chosen by (stage, role) and by the file they would change - never by the refusal's words (FR-12): the form (`handoff_check
        --fix --shorten`), the code critic's review receipt (`window_record --review-receipt`; only when the review's findings file
        exists - a receipt is immutable, and the role is woken for the missing findings anyway, t-909 F-10), the scout's source
        receipts (`ticket_adapter receipts`, for a story that began before the writer stamped them). 'Wrote' is a different sha256
        of the target file before and after (`_sha`), not an exit code and not a sentence: `handoff_check --fix` rewrites its file
        on every call. ERROR DIRECTION (I4): a door that errs only fails to write; none ever stamps a window the role did not see
        (`window_record` itself refuses a window with a gap, a stale review or a collision)."""
        root = self.task_root
        doors = []
        if (root / "work" / "handoffs" / f"{dispatch}.yaml").is_file():
            doors.append(("form", root / "work" / "handoffs" / f"{dispatch}.yaml",
                          lambda: self.form_report(dispatch, shorten=True)))
        if stage == "S5" and role == "qa-code-critic":
            import story_step
            if story_step._role_receipts(root, role, dispatch):
                doors.append(("review receipt", root / "work" / "automation-manifest.json",
                              lambda: self.py("window_record.py", "--task", self.task, "--dispatch", dispatch, "--review-receipt")))
        inventory = root / "work" / "source-inventory.json"
        if role == "qa-scout" and inventory.is_file():
            doors.append(("source receipts", inventory,
                          lambda: self.py("ticket_adapter.py", "receipts", "--output", str(inventory))))
        wrote = []
        for name, target, run in doors:
            before = _sha(target) if target.is_file() else ""
            run()
            if (_sha(target) if target.is_file() else "") != before:
                wrote.append(name)
        return wrote

    # --- S0 by code ------------------------------------------------------------------------

    def quality_check_ids(self) -> list:
        ids = []
        for item in self.config.get("quality_checks") or []:
            ids.append(item.get("id") if isinstance(item, dict) else str(item))
        for profile in self.config.get("profiles") or []:
            gates = (profile or {}).get("quality_gates") or []
            if isinstance(gates, dict):
                gates = gates.get("checks") or gates.get("ids") or []
            for gate in gates:
                ids.append(gate.get("id") if isinstance(gate, dict) else str(gate))
        return [i for i in dict.fromkeys(ids) if i]

    # The artifacts a role reaches for by name, keyed the way a role would ask. Measured on run
    # 5: **129 of 644 reads missed**, and the top of that list is this table's subject - the
    # human plan tried at both levels (`test-plan.md` 8 times, `work/test-plan.md` 5, the same
    # file), the context manifest 7, the bundle 4, the readiness 3. Every path is resolved
    # through the registry that the writers use, never spelled here (FR-15, FR-37).
    # t-304 N1: the table and the map built from it live in `runtime_paths` (the READERS of the stored map resolve it
    # through the same table); the name stays here as an alias, and the map is the writer's body unchanged (Q2).
    import runtime_paths as _rp
    KNOWN_ARTIFACTS = _rp.KNOWN_ARTIFACTS
    del _rp

    def known_paths(self) -> dict:
        import runtime_paths
        return runtime_paths.known_paths(self.task_root, project=self.project, plugin=self.plugin, log=print)

    def initialize(self) -> None:
        # The controller's source_revision is the hash of the story's ONE ticket snapshot: the
        # JSON is the canon; a story begun before that keeps hashing the `.md` it wrote; with
        # neither on disk the seed is the task and the time, as it always was.
        work = self.task_root / "work"
        snapshot = next((p for p in (work / "ticket-snapshot.json", work / "ticket-snapshot.md")
                         if p.is_file()), None)
        seed = snapshot.read_bytes() if snapshot else (self.task + _now()).encode("utf-8")
        state = self.controller_state()
        request = {"source_revision": hashlib.sha256(seed).hexdigest(), "scope": [],
                   "known_paths": self.known_paths(), "required_quality_checks": self.quality_check_ids(),
                   "coverage_contract_version": 2, "plan_contract_mode": "new",
                   "source_inventory_required": True, "expected_revision": state.get("revision", 0),
                   "idempotency_key": f"initialize:{self.task}:driver"}
        self.controller("initialize", input_data=request)
        print("controller initialized")

    def code_only(self, stage: str, reason: str, evidence: list) -> str:
        """The code-only receipt of `stage`; returns its id (the receipt a deferred record is tied to, C2-8 I4). The refusal for missing
        evidence carries the title `code_only_evidence`, so `close_receipt` tells it from the controller's own refusal by the field."""
        refs = []
        for rel in evidence:
            path = self.task_root / rel
            if path.is_file():
                refs.append({"path": rel, "sha256": _sha(path)})
        if not refs:
            raise Refusal(f"code-only {stage}: none of {evidence} exists to stand as evidence", title="code_only_evidence")
        state = self.controller_state()
        n = len([e for e in (state.get("dispatches") or {}) if str(e).startswith(f"{stage}-code-only")]) + 1
        receipt = f"{stage}-code-only-{n}"
        self.controller("code_only", input_data={"id": receipt, "stage": stage, "reason": reason,
                                                 "evidence_refs": refs, "expected_revision": state.get("revision", 0),
                                                 "idempotency_key": f"code_only:{stage}:{n}"})
        self.progress_line()            # the stage is closed by code, not by a role
        return receipt

    def close_receipt(self, site: str, stage: str, reason: str, evidence: list) -> str:
        """`code_only` at a site of `CODE_CLOSE_SITES` (C2-8): the same call, a refusal it raises is marked `close` with the step that
        failed - `evidence` (a file the receipt stands on is missing) or `receipt` (the controller said no). Returns the receipt id."""
        try:
            return self.code_only(stage, reason, evidence) or ""
        except Refusal as refusal:
            if site:
                refusal.close = {"site": site, "stage": stage, "step": "evidence" if refusal.title == "code_only_evidence" else "receipt"}
            raise

    def record_close(self, site: str, stage: str, *args, tail=(), receipt: str = "") -> None:
        """THE record of a stage the code closed (C2-8): `stage_done --stage <stage> <args>`, then the `tail` (lists of `log_append`
        arguments, e.g. the `dispatch_skipped` row). A refusal is marked `close` (step `record`, with what a deferred record needs) and
        its `retry` repeats the WHOLE record - the write and the tail - never the write alone. A record that goes through drops the stage's
        `code_close` facts (I8: the next episode of the stage starts clean - its own `recover`, no stale `passed`)."""
        try:
            self.py("stage_done.py", "--task", self.task, "--stage", stage, *args, check=True)
        except Refusal as refusal:
            if site:
                refusal.close = {"site": site, "stage": stage, "step": "record", "receipt": receipt,
                                 "args": [str(a) for a in args], "tail": [[str(a) for a in line] for line in tail]}
            refusal.retry = lambda: self.record_close(site, stage, *args, tail=tail, receipt=receipt)
            raise
        for line in tail:
            self.py("log_append.py", *line)     # remains: a tail row is a `dispatch_skipped` of a close that is already recorded (M3, t-1214: the only two callers that pass a tail; no `human_answer` rides one); a failed row is no state to ask about
        if site and (self.state.get("code_close") or {}).pop(stage, None) is not None:
            self.save_state()                   # I8: a later episode of this stage starts clean (no stale `recovered` / `passed` / `filed`)

    S3_PLAN_LINE = ("Write work/test-plan.json as {\"rows\": [...]} with the first few rows, then append the "
                    "remaining rows with Edit a few at a time (each edit replaces the closing `]}`); the same "
                    "for test-plan.md. A single Write of the whole plan hits the output cap.")

    # GW1-41: the register fence reaches the strategist BEFORE the work (FR-38, AR-10); window 1 does not get it (the plan is
    # not written there). `skills/qa-story/phases/s3.md` carries the same sentence.
    S3_FENCE_LINE = ("Every id of the `## Register` table reaches a row: name it in `requirements` in work/test-plan.json and in the `R` column of "
                     "test-plan.md. A requirement waiting for a gate A question: `disposition: unverifiable`, `question_refs`, and `if_answered` with a patch "
                     "that sets a disposition; one that should not be checked: `disposition: skip` with the reason. `not_planned` holds only `K-n` and `B-n`.")

    # The fields window 1 fills (agents/qa-test-strategist.md «Two windows» names the same list; test W10 pins both against GT).
    S3_WINDOW1_FIELDS = ("rows[].label, .requirements, .risks[{id: K-n, hypothesis}], .question, .reason, .hunks (the all:<repo>:<file> "
                         "grouping); requirements[].state, .hunks, .where, .question; blast_radius.areas[].matters, .why, .text_says, "
                         ".regression, .add_tests; claims[]. A question is prose of at most 300 characters; write before/now values "
                         "in double quotes")

    # The claims text the role cannot read in the plugin (run_role tells it not to open plugin files): the quoted block of
    # skills/qa-story/phases/s3.md («Tell the role, verbatim»), its "> " markers stripped, the lines joined with a space. Test W10 pins the
    # two byte-equal (G1-11 fix round B1, FR-38 / AR-10 / AR-19).
    S3_CLAIMS_LINE = ("**A behaviour the register does not hold.** When a `behaviour_change` row of `work/grounding.yaml` shows behaviour no requirement of "
                      "`work/requirements-register.md` states, write it as one entry of `claims` in `work/grounding.yaml` (never in the register: its writer is the "
                      "requirements tester, and the code copies your claim into it after this window). Fields: `r` (the next free `R-<n>` — the register's ids "
                      "and every other claim are taken), `row` (that row's id), `requirement` (one verifiable statement), `impact` (the project's scale), `before` "
                      "and `before_ref` (what the code did before the change and where you read it — `diff:-<path>:<line>`, `base:<rev>:<path>:<line>` from the "
                      "base slice, `absent` for a new path, or `before: \"unknown\"` when nothing shows it — never a guess), `now` and `now_ref` (`diff:<path>:<line>`), "
                      "`differs` (yes / no / unknown), `question: raise`, and `ask` (`question`, `source_says`, `severity`, `owner_role`: what the person is asked). "
                      "Put every text value in double quotes. A claim is a statement about the code for the person to confirm, never the expected value of a test.")

    def s3_labelling_of(self, record) -> bool:
        """Is `record` window 1 of S3? The ONE driver reader: the controller's word through `controller.s3_window_of`, or the driver's own
        synthetic `{"window": "labelling"}` record that a caller with no controller record yet passes."""
        import controller as CT
        record = record if isinstance(record, dict) else {}
        return CT.s3_window_of(record) == "labelling" or record.get("window") == "labelling"

    def s3_strategist_lines(self, record) -> list:
        """The strategist's lines for the window `record` names (G1-11, FR-38: the fields reach the role BEFORE the work). `record` is the
        controller record, a packet, or `{"window": ...}` / `{"repair_cause": ...}` from a caller that has no record yet. ONE producer."""
        import grounding_table as GT
        import handoff as H
        base = f"qa-factory/artifacts/{self.task}/"
        record = record if isinstance(record, dict) else {}
        labelling = self.s3_labelling_of(record)
        ticket = record.get("repair_cause") == "ticket_changed"
        reach = ("work/grounding.yaml is the labelled table: every `K-n` and every area with `matters: yes` reaches a row "
                 "(`risk_source_refs: grounding:K-n` / `blast:B-n`) or a `not_planned` entry with `ref`.")
        # The claim fields (S3_CLAIMS_LINE) travel in the dispatch text: the role is told not to read the plugin's files (B1).
        labelling_lines = [f"Fill only: {self.S3_WINDOW1_FIELDS}.",
                           f"labels: {', '.join(H.allowed('grounding_labels'))}; requirement states: "
                           f"{', '.join(H.allowed('requirement_grounding_states'))}.",
                           "The base slice (`base_slice[]`), when present, shows the code before the change.",
                           self.S3_CLAIMS_LINE,
                           "End with the handoff form; the code checks the table (the check lists only fields you fill)."]
        if labelling:
            return [f"This is window 1 of S3 (labelling): write NO plan row; your work is {base}work/grounding.yaml."] + labelling_lines
        if ticket:             # ONE dispatch labels, then plans (B3): no line may tell it to write no plan
            return (["This dispatch labels work/grounding.yaml first (the fields below), then writes the plan over it."]
                    + labelling_lines + [self.S3_PLAN_LINE, self.S3_FENCE_LINE, reach])
        lines = [self.S3_PLAN_LINE, self.S3_FENCE_LINE]
        try:
            diff_world = GT.source_state(self.task_root)[0] == "diff"
        except Exception:
            diff_world = False          # an unreadable state adds no line: today's text alone
        if diff_world:
            lines.append(reach)
            lines += self.s3_counted_lines()
        return lines

    def s3_counted_lines(self) -> list:
        """What the code counted over the table, for the window-2 strategist (G2-2, FR-38): the requirement coverage (and the person's word
        for a stop, when there is one) and, per exit of the blast radius with a command, the line to put into `## Recommended regression`.
        Never raises: a measure that cannot be made adds no line (the stop question is the driver's, not the role's)."""
        import grounding_table as GT
        import planning_contract as PC
        lines: list = []
        try:
            cov = GT.coverage_of(self.task_root)
            if cov["road"] != "unknown":
                text = f"Code counted: {cov['implemented'] + cov['partial']} of {cov['n']} requirements are covered by the change ({cov['percent']}%)."
                if cov["road"] == "stop":
                    word = GT.stop_word(self.pipeline(), GT.COVERAGE_STOP_BLOCK, GT.coverage_digest(self.task_root, cov))
                    text += " The person decided to go on." if word is not None else " No person's word stands for this yet."
                lines.append(text)
            doc, _problem = PC.read_grounding(self.task_root)
            for entry in PC.regression_from_blast(doc) if doc is not None else []:
                if entry.get("command"):
                    tokens = ", ".join(f"blast:{a.strip()}" for a in str(entry["area"]).split(","))   # a merged area "B-1, B-3": ONE token per area (BLAST_TOKEN reads one)
                    lines.append(f"{entry['area']} {entry['command']} - name these tests as items of `## Recommended regression` "
                                 f"(the command goes on its `Command:` line), each item signed with {tokens}.")
        except Exception:
            return lines
        return lines

    def s1_window_owed(self, stage: str, role: str | None = None):
        """`{"row", "references"}` when the S1 reference window is owed - the stage declares an optional `reference_walk` dispatch
        (`stage_guard.optional_rows`) AND the story's sides carry a reference stand (`stand_identity.reference_stands`) - else None.
        The ONE test of "has this story a window", read by `stage_simple` (the first make of S1), by `rework`, by the relaunch road
        of a rework of the S1 scout and by `completion_for` (t-2277 batch 2b D): a story with no reference gets None and every road stays
        as it was. `role` (N1, critic t-2548): when given, the window is owed only for the stage's AUTHOR (its first role, the scout) -
        any other role of the stage gets None - so the one test of "the scout" lives here, not at each caller."""
        if stage != "S1":
            return None
        if role is not None and role != (self.stages().get(stage, {}).get("roles") or [""])[0]:
            return None
        import controller as CT
        import stage_guard as SG
        rows = [r for r in SG.optional_rows(self.stages()[stage]) if r["purpose"] == CT.REFERENCE_WALK]
        if not rows:
            return None
        import stand_identity as SI
        references = SI.reference_stands(self.project, self.task)
        return {"row": rows[0], "references": references} if references else None

    def s1_reference_window(self, stage: str, window: dict) -> None:
        """The runner's walk of the OLD version (the S1 reference window), after the scout's run: dispatch, survey walk on the reference
        stand, the runner's `put` (with `--replace` over an old snapshot). The closing dispatch of S1 (`complete=True`). Whether the
        scout's dispatch was ACCEPTED is checked by `stage_simple` (it runs the scout only when no accepted one exists); `rework` and
        `_act_relaunch` call this right after `run_role` returned, whatever the scout's status is (N2, critic t-2548): this method itself
        checks no status."""
        import controller as CT
        import stage_guard as SG
        import event_store
        row, references = window["row"], window["references"]
        runner, purpose = row["role"], row["purpose"]
        # one reference per story (the snapshot has one `reference_env`): the first by name is walked, every other is NAMED as a gap (F6, AR-28)
        reference = sorted(references)[0]
        unwalked = [f"the reference `{stand}` of the `{references[stand]}` side was not walked: one reference per story"
                    for stand in sorted(references)[1:]]
        for line in unwalked:
            print(f"S1: reference window: {line}")
        controller = CT.Controller(self.task_root, wait_seconds=event_store.LIFECYCLE_WAIT_SECONDS)
        state = controller.state()
        number = 1 + len([d for d in (state.get("dispatches") or {}).values() if isinstance(d, dict) and d.get("stage") == stage and d.get("role") == runner])
        dispatch_id = f"{stage}-{runner}-{number}"
        try:
            # the purpose goes into `prepare` too: the controller admits a qa-runner packet with no `execution_kind` only by the purpose of an
            # optional row of the stage (`controller.runner_kind_required`, B1) - the window runs no half of a plan
            packet = controller.prepare({"stage": stage, "role": runner, "id": dispatch_id, "scope": [], "purpose": purpose})
            controller.apply("dispatch", dict(packet["dispatch_request"], purpose=purpose))
        except Exception as exc:
            raise Refusal(f"{stage} reference window dispatch refused: {type(exc).__name__}: {exc}")
        # the walk session of the OLD version: `survey` place on the reference stand, opened after the dispatch is registered and before the
        # role starts (the record names the stand; `reference_snapshot.py put` takes the walk by code from the newest `reference_walk` dispatch).
        # The actors are `first_look.walk_actors` - the ONE reader of the account list (F7, AR-13): accounts first, `guest` in a slot left over
        import first_look as FL
        import walk_session as WS
        who = FL.walk_actors(self.project, self.config, reference, WS.data()["max_actors"])
        actors = who["actors"]
        code, text = self.py("walk_session.py", "open", "--task-root", str(self.task_root), "--walk", dispatch_id, "--place", "survey",
                             "--env", reference, "--items", "free", "--actor", actors[0], *(["--actor2", actors[1]] if len(actors) > 1 else []))
        out_rel = (SG.optional_outputs(row) or ("work/reference-snapshot.yaml",))[0]
        replace = (self.task_root / out_rel).is_file()      # the story is made again over an old snapshot: `put` replaces it
        put = (f"python \"{self.scripts}/reference_snapshot.py\" put --task-root {self.task_root} --reference {reference} --items-file <items.yaml>"
               + (" --replace" if replace else ""))
        shape = ("The file is block YAML: `items:` - one mapping per behaviour: id (plain id), area, user_path, observed, evidence (a list of "
                 "{path, quote} from a capture of THIS walk) and/or old_test (<file>:<line>), locators_portable (yes | no | unknown) - and a "
                 "`gaps:` list of lines. The snapshot contract - every key, the evidence form and what `put` refuses - is "
                 f"`{self.plugin / 'references' / 'artifact-contract-reference.md'}`.")
        extra_gaps = (" Put these lines in `gaps:`: " + "; ".join(f"\"{g}\"" for g in unwalked) + ".") if unwalked else ""
        if code:
            why = ((_read_answer(text) or {}).get("reason") or (text.splitlines() or [f"exit {code}"])[-1]).strip()[:300]
            gaps = [f"the old version at {reference} could not be reached: {why}", *unwalked]
            try:
                import reference_snapshot as RS
                RS.put_gap(self.task_root, reference, gaps, replace=replace)       # F5: the line is the driver's own, so the driver writes it
                written = True
            except Exception as exc:  # noqa: BLE001 - the runner writes it as before (P1)
                print(f"S1: reference window: the gap-only snapshot was not written by the driver ({type(exc).__name__}); the runner writes it")
                written = False
            if written:
                extra = [f"Reference window: the old version at `{reference}` could not be reached ({why}). The driver has already written "
                         f"{out_rel} with that one gap line: walk nothing, write nothing, ask no one - hand over your form (S1 closes with this dispatch)."]
            else:
                extra = [f"Reference window: the old version at `{reference}` could not be reached: {why}. Walk nothing and ask no one: write the "
                         f"snapshot with `items: []` and the gap line \"the old version at {reference} could not be reached: {why}\": `{put}`." + extra_gaps]
        else:
            who_line = (f"You walk as {', '.join(actors)}" + (f" (accounts not opened, the walk holds {len(actors)}: {', '.join(who['left'])})" if who["left"] else "")
                        + ("; as `guest` you are not signed in" if "guest" in actors else "") + ". ")
            extra = [f"Reference window: walk the OLD version at `{reference}` in walk session `{dispatch_id}` (place survey; items are ids you choose, "
                     "plain letters, digits, - and _), the behaviours the story's requirements say must stay as they are. " + who_line
                     + "Capture with the walk commands of your brief. Then write what you saw ONCE: `" + put + "`. " + shape + extra_gaps]

        def record_then_role() -> None:
            self.record_running(stage, runner, dispatch_id, retry=record_then_role)
            self.run_role(stage, runner, complete=True, extra=extra, purpose=purpose,
                          rework={"id": dispatch_id, "scope": [], "reason": "reference window"},
                          after=(None if code else (lambda d, r: self.py("walk_session.py", "close", "--task-root", str(self.task_root), "--walk", dispatch_id))))
        record_then_role()

    def s3_prepare(self) -> None:
        """The ONE preparation of the grounding table; every road that refreshes it calls this. Diff world: `blast_radius.py` (the index) ->
        `grounding_table.py --refresh` (== the skeleton when no table exists; off the diff it writes the null outcome) -> `base_slice.py`.
        POSITION: the index before the table, both before `start` - a window is never labelled over another index generation or another
        diff; the slice after the table (it reads `hunks[]`). The first two failing are a `Refusal` (nothing after them ran; no dispatch is
        registered); the slice failing is a recorded warning line and the window runs (its `before` is then `unknown`, G1-8)."""
        import grounding_table as GT
        diff = GT.source_state(self.task_root)[0] == "diff"
        first = lambda out: next((ln.strip() for ln in str(out).splitlines() if ln.strip()), "no output")      # noqa: E731
        if diff:
            code, out = self.py("blast_radius.py", "--task", self.task)
            if code:
                raise Refusal(f"S3 preparation: blast_radius.py exited {code}: {first(out)}. The grounding table is not built over a "
                              "missing or stale index; nothing else ran. Way on: the conductor (P22).", dispatch="")
        code, out = self.py("grounding_table.py", "--refresh", "--task", self.task)
        if code:
            raise Refusal(f"S3 preparation: grounding_table.py --refresh exited {code}: {first(out)}. The slice and the window did not "
                          "run. Way on: the conductor (P22).", dispatch="")
        if diff:
            code, out = self.py("base_slice.py", "--task", self.task)
            if code:
                code2, out2 = self.py("stage_done.py", "--task", self.task, "--warn",
                                      f"base_slice: unknown - S3 preparation: base_slice.py exited {code} ({first(out)[:160]}): no base slice for this story; the planner "
                                      "reads before: unknown")
                if code2:
                    raise Refusal(f"S3 preparation: base_slice.py exited {code} and the warning could not be recorded (stage_done.py exited "
                                  f"{code2}: {first(out2)}). The window did not run. Way on: the conductor (P22).", dispatch="")

    def s3_rework_completion(self):
        """The completion of an S3 strategist REWORK (a person's seam choice, the S4 rehearsal's route, a recovered dispatch; RN1-2 B-1):
        the plan projection alone (the revision mark and the `new:<n>` questions - the role writes neither), and the closing outcome stays
        `False`: a rework never closes S3 by itself. The one callable of `completion_for` and `seam_rework_step`."""
        def reworked(digest):
            self.s3_project(claims=False)
            return False
        return reworked

    def s3_project(self, claims: bool = True, reopening: bool = False) -> None:
        """The planner's claims into the register (G1-13): project -> refresh the table when the projection wrote -> done. A problem of the
        ROLE's is the role's to fix (the dispatch stays running and the S3 refusal road resumes it); a driver or conductor problem is not
        the role's and carries no repair marker. Then the PLAN's own projection (RN1-2, `planning_contract.project_plan`): the revision
        mark and the questions the rows declared as `new:<n>`, written AFTER the claims (the claims' register rows come first). Its
        problems are the conductor's, never the role's (no repair marker: the role's plan was accepted at the exit). `claims=False`
        is the `old` road (no grounding table, so no claims) - the plan projection alone."""
        dispatch = getattr(self, "last_dispatch", "") or ""
        if claims:
            import claim_projector as CP
            result = CP.project(self.task_root)
            problems = list(result.problems)
            if problems:
                lines = "\n".join(f"- {p}" for p in problems)
                if any(p.who == "role" for p in problems):
                    raise Refusal(f"S3 claims (claim_projector.py): {lines}\n{REPAIR_MARKER}: fix claims[] in work/grounding.yaml as the "
                                  "lines say.", dispatch=dispatch, retry=None)
                raise Refusal(f"S3 claims (claim_projector.py): {lines}", dispatch=dispatch, retry=None)
            if result.wrote:
                self.py("grounding_table.py", "--refresh", "--task", self.task, check=True)
        import planning_contract as PC
        planned = PC.project_plan(self.task_root, reopening=reopening)
        if planned.problems:
            raise Refusal("S3 plan projection (planning_contract.project_plan): " + "\n".join(f"- {p}" for p in planned.problems),
                          dispatch=dispatch, retry=None)

    def s3_ticket_completion(self, closes: bool = True):
        """The ticket re-run of S3 closes COMPLETE (the plan baseline is re-captured): project -> refresh-if-wrote -> True. With
        `closes=False` (a stage that has an acceptor, X2-7) the same side steps run and the finish does not close: the stage critic does."""
        def closing(digest):
            self.s3_project(reopening=True)      # gate A's approval is on the old text; `ticket_reopen_gate_a` reopens it right after (B-2)
            self.py("grounding_table.py", "--share", "--task", self.task, check=True)
            return True if closes else None
        return closing

    def rework(self, stage: str, role: str, cases: list, reason: str, *, cause: str,
               purpose: str = "repair_verify", extra=(), complete=False, budget=READ_BUDGET, on_request=None,
               rows=(), words_file: str = "") -> tuple:
        """`on_request(id)`: called with the controller's dispatch id the moment `rework` has it, before any role runs (the S7 loop
        records it, t-698 §20 N9). `cause` has no default: a round's cause is the reviewer's typed word (repair_route), and
        a default here is how every repair once went out as `test_defect`. A round that is not
        about the test says what it was for - the receipt is the only place the retro learns it.
        `complete`: the closing flag of the author's dispatch; a mechanical round on the last
        window is the one that may close S5 (the reviewer is not dispatched again).
        `words_file` (C2-6 §4.2 p.9): the task-root relative file of a PERSON's words, whole (FR-8): the controller gets
        `--words-file` INSTEAD of `--reason` (no `[:1500]`; `reason` is that file's text), and a reason longer than 1500 reaches
        the role as the file's path. `rows`: the plan rows an S1-S3 rework goes back over."""
        if cause != "test_defect" and not str(reason or "").strip():
            raise ValueError(f"rework: a {cause} round needs a non-empty reason - one sentence of what "
                             "happened; it spends none of the repair cap, and the receipt is where the retro reads why")
        words_path = str(self.task_root / words_file) if words_file else ""
        args = ["--stage", stage, "--role", role, *(["--words-file", words_path] if words_path else ["--reason", reason[:1500]]),
                "--purpose", purpose, "--cause", cause]
        if cases:
            args += ["--cases", ",".join(cases)]
        if rows:
            args += ["--rows", ",".join(rows)]
        # TR3-6: POSITION - before `controller rework`; INVARIANT: a drain registers no new dispatch
        self.stop_if_drained()
        self.count_launch()
        if self.on_chain():
            args.append("--parallel-window")
        try:
            packet = self.controller("rework", *args)
        except Refusal as exc:
            raise ReworkRefused(exc.text, retry=exc.retry, files=exc.files, dispatch=exc.dispatch) from exc
        request = packet.get("request") or {}
        if not request.get("id"):
            raise ReworkRefused("rework returned no dispatch id: " + json.dumps(packet)[:600])
        if on_request:
            on_request(request["id"])
        given = {"id": request["id"], "scope": cases, "reason": reason}
        if words_path and len(reason) > 1500:        # the role is told WHERE the whole words are, never a cut of them (FR-8)
            given["line"] = (f"Rework reason: the person's words ({len(reason)} characters) are in {words_path}; "
                             "read the whole file before you start.")
        # t-2277 batch 2b D (critic t-2513 F1): `rework S1` of a story with a reference stand re-enters the reference window - the scout's
        # rework does not close S1 (the window is its last dispatch), then the runner walks the old version again and `put` replaces the
        # snapshot (`--replace`, the file exists). POSITION: after the controller registered the rework, in the ONE method every code road of
        # a rework passes. INVARIANT: a story with no reference (`s1_window_owed` None) runs `run_role` exactly as before.
        window = self.s1_window_owed(stage, role)
        done = self.run_role(stage, role, scope=list(request.get("scope") or cases), extra=list(extra),
                             complete=False if window else complete, rework=given, budget=budget)
        if window:
            self.s1_reference_window(stage, window)
        return done

    def repair_budget(self, stage: str, role: str, scope, **packet) -> dict:
        """The window's rounds as the controller counts them from the journal itself: counted, cap,
        mechanical, mechanical_cap. The driver keeps no counter of its own - a local one reset on every
        restart (B-007). Raises Refusal when the controller cannot answer; the caller closes the
        window instead of guessing a number. `packet`: the extra `prepare` options of a role whose packet needs them (the new-mode `qa-runner`:
        `execution_kind`, and `manual_case_ids` of a manual block; X7-6c) - empty values are left out."""
        options = {"stage": stage, "role": role, "scope": list(scope or []), **{k: v for k, v in packet.items() if v}}
        packet = self.controller("prepare", input_data=options)
        budget = packet.get("repair_budget")
        if not isinstance(budget, dict):
            raise Refusal(f"controller prepare for {stage} {role} carries no repair_budget: " + json.dumps(packet)[:400])
        return budget

    def budget_or_none(self, stage: str, role: str, scope, ref: str = "", **packet) -> dict | None:
        """`repair_budget`, or None after saying so: the loops read None as "no round, close" and never
        substitute a number of their own. The controller that cannot count is the factory's own
        defect, so it is printed and filed (owner factory; `--ref` is mandatory in log_append)."""
        try:
            return self.repair_budget(stage, role, scope, **packet)
        except Exception as exc:
            error = " ".join(str(getattr(exc, "text", "") or exc).split())[:300] or type(exc).__name__
            seen = getattr(self, "_budget_unknown", None)       # ONE defect per window per process: the loop and the seam's gate both read
            if seen is None:
                seen = self._budget_unknown = set()
            if (stage, role, tuple(scope or [])) in seen:
                return None
            seen.add((stage, role, tuple(scope or [])))
            print(f"repair budget unknown: {error}")
            # T4 (C1-7b): the window is closed with no round either way (the return below), and the line above already said so
            self.py_trace("log_append.py", "--event", "defect_found", "--task", self.task, "--by", "driver",
                          "--ref", ref or getattr(self, "last_dispatch", "") or f"{stage}-{role}",
                          "--notes", f"owner: factory - the repair budget of {stage} {role} could not be read "
                                     f"({error}); the window was closed with no repair round",
                          why="the window closes with no repair round whether or not the defect row lands, and no decision of this story reads the row")
            return None

    def stage_scope(self, stage: str, kind: str = "") -> dict:
        data = {"stage": stage}
        if kind:
            data["execution_kind"] = kind
        return self.controller("stage-scope", input_data=data)

    def say_once(self, key: str, text: str) -> None:
        """Print `text` once per story: the mark is `state["noted"]` (the one list the findings notes use), and never a stop (P5)."""
        noted = self.state.setdefault("noted", [])
        mark = f"{key}|{text}"
        if mark in noted:
            return
        noted.append(mark)
        print(text, flush=True)
        self.save_state()

    def s5_open_windows(self, excluding=()) -> list:
        """The case lists of the S5 windows that are still open, other than the window meeting `excluding`. Open = no accepted critic, OR
        a running dispatch of the stage meets its scope, OR a round or a debt is owed for it, OR a live chain of this driver holds it, OR
        the LAST non-discounted S5 dispatch meeting its scope came back `returned_unaccepted` (TR4-10 Q2: `_s5_last_round`; a later
        accepted dispatch of the window closes it again, a person's release is dropped with the other discounted statuses), OR that last
        round is an ACCEPTED qa-automator round whose stored cause is not `mechanical` (TR4-13: `_s5_author_awaits_critic`; its critic
        has not reviewed it yet, and a mechanical round is closed by the author's own green run).
        Read fresh. RAISES when the windows, the dispatches or a scope cannot be read (FR-59): the caller treats that as open and never as
        a close; a returned S5 dispatch that names no cases is such a case. Callers: the close predicate of `s5_review` and
        `s5_mechanical_round`, `completion_for` at `parallel_windows` != 1, the old body of `stage_S5` at `parallel_windows` != 1, and the
        finish's `--open-windows`. At N == 1 the serial road does not read this function; a returned last round there is settled by the
        controller's own return road (a named residual, D2)."""
        import dispatch_identity
        import controller as CT
        from controller import s5_part_of
        own = {str(c) for c in (excluding or ()) if c}
        windows = self.stage_scope("S5").get("windows")
        if not isinstance(windows, list):
            raise WindowsUnreadable("stage-scope returned no list of windows")
        ctl = self.controller_state()
        dispatches = ctl.get("dispatches") if isinstance(ctl, dict) else None
        if not isinstance(dispatches, (dict, list)):
            raise WindowsUnreadable("the controller record holds no list of dispatches")
        rows = dispatch_identity.records(dispatches)
        running = [r for r in rows if r.get("stage") == "S5" and r.get("status") == "running" and s5_part_of(r) != "plan"]
        if any(not r.get("scope") for r in running):
            raise WindowsUnreadable("a running dispatch of S5 names no cases, so no window can be told from it")
        if any(r.get("stage") == "S5" and r.get("status") == CT.RETURNED and s5_part_of(r) != "plan" and not r.get("scope") for r in rows):
            raise WindowsUnreadable("a returned dispatch of S5 names no cases, so no window can be told from it")
        live = [r for r in self._chains.values() if not r.done]
        out = []
        for window in windows:
            if not isinstance(window, dict):
                raise WindowsUnreadable("a window of stage-scope is not an object")
            cases = {str(c) for c in window.get("scope") or [] if c}
            if not cases:
                raise WindowsUnreadable("a window of stage-scope names no cases")
            if cases & own:
                continue
            owed = self.repair_owed([window])[0] or self.repair_debt_pending([window])[0]       # F4: the two predicates, not a copy
            last_round = self._s5_last_round(rows, cases)
            if ("qa-code-critic" not in (window.get("accepted_by") or {})
                    or any(cases & {str(c) for c in r.get("scope") or []} for r in running)
                    or owed or any(cases & {str(c) for c in r.cases} for r in live)
                    or (last_round is not None and last_round.get("status") == CT.RETURNED)
                    or self._s5_author_awaits_critic(last_round)):
                out.append(sorted(cases))
        return out

    @staticmethod
    def _s5_author_awaits_critic(last_round) -> bool:
        """TR4-13 (FR-40, AR-25): True when the window's LAST round (`_s5_last_round`) is an ACCEPTED, non-mechanical author round: no
        critic has looked at it, so the window is open and the critic reviews it next, though an earlier accepted critic is still in
        `accepted_by`. The cause is read through the controller's one reader `repair_cause` (an absent or unknown cause is `test_defect`).
        Error direction: a `mechanical` round completes the window as before; anything else costs one more critic entry, never a close
        over an unreviewed round. ONE predicate for `s5_open_windows` and `s5_todo`."""
        import controller as CT
        return (isinstance(last_round, dict) and last_round.get("status") == "accepted" and last_round.get("role") == "qa-automator"
                and CT.repair_cause(last_round) != "mechanical")

    @staticmethod
    def _s5_last_round(rows: list, cases) -> dict | None:
        """The LAST S5 window dispatch (not the plan) among `rows` (`dispatch_identity.records`, the controller's order = dispatch order)
        whose scope meets `cases`, once the statuses in `controller.DISCOUNTED` are dropped; None when there is none. ONE walk for the
        returned clause of `s5_open_windows` and for every reader of "what came back last in this window" (TR4-10)."""
        import controller as CT
        mine = {str(c) for c in (cases or ()) if c}
        found = None
        for row in rows:
            if (row.get("stage") == "S5" and CT.s5_part_of(row) != "plan" and row.get("status") not in CT.DISCOUNTED
                    and mine & {str(c) for c in row.get("scope") or [] if c}):
                found = row
        return found

    def s5_open_flag(self, cases) -> list:
        """`["--open-windows", <cases>]` for a finish that does not close S5 while other windows are open, else []. Unreadable windows:
        the raw list of the other windows; if even that cannot be read, nothing (the controller refuses and the seam gets it)."""
        try:
            opened = self.s5_open_windows(excluding=cases)
        except Exception:       # noqa: BLE001
            try:
                own = {str(c) for c in cases}
                opened = [sorted({str(c) for c in w.get("scope") or []}) for w in self.stage_scope("S5").get("windows") or []
                          if isinstance(w, dict) and not own & {str(c) for c in w.get("scope") or []}]
            except Exception:       # noqa: BLE001
                return []
        names = sorted({c for w in opened for c in w})
        return ["--open-windows", ",".join(names)] if names else []

    def s5_release(self, cases) -> None:
        """A window that closed frees its test files (`window_files.release`, under `_book` on a chain). With `parallel_windows: 1`
        nothing was claimed and nothing is touched. A release that fails is a note; the entry sweep tries again."""
        import config_contract
        import window_files
        if config_contract.parallel_windows(self.config)[0] == 1:
            return
        window = window_files.window_id("S5", cases)
        left, why = [], ""
        try:
            window_files.release(self.task_root, window)
            left = window_files.files_of(self.task_root, window)      # `release` never raises: a claim it could not remove is still there (F7)
        except Exception as exc:       # noqa: BLE001
            why = f" ({type(exc).__name__})"
        if left or why:
            print(f"note: the test files of window {', '.join(cases)} could not be released{why or f' ({len(left)} claim(s) left)'}; "
                  "the next entry tries again")

    def s5_cases_of(self, dispatch: str) -> list:
        """The cases of an S5 dispatch: this chain's record, else the controller's record of `dispatch` ([] when it holds none). The ONE
        reader (R3, AR-13) for `finish`'s open-windows flag and the release of a closing window."""
        own = list(getattr(getattr(_CHAIN, "record", None), "cases", ()) or ())
        if own:
            return own
        from dispatch_identity import records as _records
        ctl = self.controller_state()
        return next((list(r.get("scope") or []) for r in _records(ctl.get("dispatches") if isinstance(ctl, dict) else None)
                     if r.get("id") == dispatch), [])

    def s5_release_of_dispatch(self, dispatch: str) -> None:
        """Q1: the window of the S5 critic `dispatch` whose finish just closed the stage frees its files. The chain road and the old body
        release when `s5_window` returns; the road through the person's gate answer (`s5_close_debt`, the recovery finish, `guarded`) never
        returns there, and a completed S5 is not entered again, so its claims would stay and refuse a later rework's automator. The
        cases come from this chain's record, else from the controller's record of the dispatch. Costs nothing when nothing was claimed;
        never stops the run (P1)."""
        import window_files
        folder = self.task_root / window_files.SUBDIR
        if not folder.is_dir() or not any(folder.glob("*.json")):
            return
        try:
            cases = self.s5_cases_of(dispatch)
            if cases:
                self.s5_release([str(c) for c in cases])
        except Exception as exc:       # noqa: BLE001
            print(f"note: the test files of the window of {dispatch} could not be released ({type(exc).__name__}); the next entry tries again")

    def s5_release_completed(self) -> None:
        """TR4-10 Q1 (D4, D5): S5 is `completed` - every claim of the stage is freed, whichever finish closed it. `s5_release_of_dispatch`
        frees the window of the critic that closed S5; this frees the rest: a recovery process that finished window B's saved critic
        `--not-complete` and then the last window A's `--complete` (B's claims stay: S5 is never entered again), and the live mechanical
        round's finish. Called ONLY after `story_step finish` exited 0, so the stage status read is the one that finish wrote.
        INVARIANT: a claim of a window that can still write is never freed: nothing is freed unless `stages.S5.status == "completed"` AND
        no S5 dispatch is `running`, in `controller.STOPPED` or `controller.RETURNED` (a retry or a resume of the same role writes in
        the same window). Absent or unreadable state, a status that is not text: nothing is freed (late is safe, early is two windows
        on one file). At `parallel_windows: 1` nothing was claimed and nothing is read. A claim left behind is a note, never a stop (P1)."""
        import config_contract
        import controller as CT
        import dispatch_identity
        import window_files
        if config_contract.parallel_windows(self.config)[0] == 1:
            return
        folder = self.task_root / window_files.SUBDIR
        if not folder.is_dir() or not any(folder.glob("*.json")):
            return
        try:
            ctl = self.controller_state()
            if not isinstance(ctl, dict):
                return
            stages = ctl.get("stages")
            stage = stages.get("S5") if isinstance(stages, dict) else None
            if not isinstance(stage, dict) or stage.get("status") != "completed":
                return
            dispatches = ctl.get("dispatches")
            if not isinstance(dispatches, (dict, list)):
                return
            busy = {"running"} | CT.STOPPED | {CT.RETURNED}
            for row in dispatch_identity.records(dispatches):
                status = row.get("status")
                if row.get("stage") == "S5" and (not isinstance(status, str) or status in busy):
                    return
            window_files.release_stage(self.task_root, "S5")
            # only a claim this release meant to free (a readable claim of a window of stage S5): a young empty claim `release` keeps on
            # purpose, and any other stage's claim, are not "left"; `window_files.read_claim` is the claims' own reader
            left = sum(1 for path in folder.glob("*.json")
                       if window_files.window_of_stage((window_files.read_claim(path) or {}).get("window"), "S5"))
        except Exception as exc:       # noqa: BLE001
            print(f"note: the test files of S5 could not be released ({type(exc).__name__}); the next entry tries again")
            return
        if left:
            print(f"note: the test files of S5 could not be released ({left} claim(s) left); the next entry tries again")

    def session_of(self, stage: str, dispatch: str):
        """The stored session of `dispatch`; off a chain, else the stage's agent of the pipeline (the old fallback). On a chain the
        per-dispatch record only: absent means no resume, a fresh attempt by today's rule (the stage's agent may be another window's)."""
        sid = self.state["sessions"].get(dispatch)
        if sid or self.on_chain():
            return sid
        return (self.pipeline().get("stages", {}).get(stage, {}) or {}).get("agent_id")

    def route_of(self, text: str, budget, dispatch: str = "") -> tuple:
        """(route, form): where the review `text` of the critic `dispatch` sends its window, read from the critic's typed form and
        the controller's budget (B-007, FR-47). The form is the file the handoff gate has just checked; `dispatch` defaults to
        `last_dispatch` (run_role sets it). ONE reader for the loop, the seam's gate and the close predicate."""
        import repair_route
        import role_digest
        verdict = (role_digest.parse(text).get("header") or {}).get("verdict", "")
        form = repair_route.read_form(self.task_root / "work" / "handoffs" / f"{dispatch or getattr(self, 'last_dispatch', '')}.yaml")
        return repair_route.route(verdict, form, budget), form

    def s5_note_findings(self, route: dict, form, critic: str) -> None:
        """What is said about findings nobody repairs: each is printed, a tooling one is also the factory's own defect (FR-3). ONCE per
        critic dispatch and finding, across roads and processes (`state["noted"]`): the seam's gate calls this before it asks, the
        loop calls it after the review, and a window closed through the gate's question never reaches the loop again (t-729 F1)."""
        import repair_route
        typed = {f["id"]: f for f in repair_route.findings(form)} if form else {}
        noted = self.state.setdefault("noted", [])
        fresh = []
        for entry in route["not_rounds"] + ([{"id": "", "cause": "note"}] if route["note"] else []):
            mark = f"{critic}|{entry['id']}|{entry['cause']}"
            if mark not in noted:
                noted.append(mark)
                fresh.append(entry)
        for entry in fresh:
            if entry["cause"] == "note":
                print(f"S5: {route['note']}")
                continue
            print(f"S5: finding {entry['id']} of {critic} ({entry['cause']}) is nobody's round: no author is "
                  "dispatched for it; it stays in the review's unverified rows")
            if entry["cause"] == "tooling":
                # T5 (C1-7b): the finding was printed above and stays in the review's unverified rows; the defect row is the factory's note
                self.py_trace("log_append.py", "--event", "defect_found", "--task", self.task, "--ref", critic,
                              "--by", "driver", "--notes", f"owner: factory — tooling finding {entry['id']}: "
                              f"{(typed.get(entry['id']) or {}).get('problem') or 'no problem line in the form'}",
                              why="the finding is printed and stays in the review's unverified rows; the defect row is the factory's own note and no decision of this story reads it")
        if fresh:
            self.save_state()

    # --- the S5 repair limit through the one seam (C1-5b1, t-698 §4) ----------------------------------------------------

    # A window's critic result that closes over a SEAM REASON (`route["code"]`: the cap is spent, the count cannot be read, the
    # blocking findings are nobody's round, the verdict names none) is asked, never closed in silence (I1). The question is the
    # site's own, closed and priced (`call=False`, D-0041): the conductor reads only words code cannot. The gate sits in
    # `run_role`, `_finish_saved_result` and `resume_role` BEFORE the critic's finish, so the stage is never closed over it.
    CAUSE_WORDS = {"test_defect": "about the test itself", "mechanical": "a technical fix to the test",
                   "environment": "the stand got in the way", "reviewer_error": "the critic's own review is in doubt",
                   "tooling": "a fault in the factory's own tools"}

    NOBODY_ORDER = ("environment", "reviewer_error", "tooling")      # the most demanding cause first (t-698 A5)

    @staticmethod
    def window_id(stage: str, cases) -> str:
        """`<stage>|<the cases, sorted and joined by commas>`: THE window key - the conductor's per-window round cap (`window_key`)
        and the repair-limit answers (`repair_key`) share this one formatter (t-729 S2), so b2's S7 asks the same way. The
        formatter is `window_files.window_id` (the claim files of TR3-16 name windows by it too: one reader)."""
        import window_files
        return window_files.window_id(stage, cases)

    @classmethod
    def repair_key(cls, cases, stage: str = "S5") -> str:
        return cls.window_id(stage, cases)

    def repair_answer(self, cases, dispatch: str) -> dict:
        """The person's answer for THIS window and THIS critic dispatch, or {} (an answer for an earlier dispatch is none)."""
        found = (self.state.get("repair_limit") or {}).get(self.repair_key(cases)) or {}
        return found if isinstance(found, dict) and found.get("dispatch") == dispatch else {}

    def repair_owed(self, windows: list) -> tuple:
        """(the answer, its window) of a round the person chose (`round` / `fixed` / `review`) and the loop has not run yet, else
        ({}, None): the critic's finish took the window back (`--not-complete`) and the stage re-enters here. `executed` is set by
        `stage_S5`, after its stand and build checks (t-729 F3)."""
        return self.repair_entry(windows, lambda entry: entry.get("token") in self.OWED_TOKENS and not entry.get("executed"))

    def repair_debt_pending(self, windows: list) -> tuple:
        """(the answer, its window) of a `debt` that consumed an owed round (`owed`) and whose critic finish is not completed yet, else
        ({}, None) (t-733)."""
        return self.repair_entry(windows, lambda entry: entry.get("token") == "debt" and entry.get("owed") and not entry.get("finished"))

    def repair_entry(self, windows: list, wanted) -> tuple:
        """(the first kept answer `wanted` accepts, its window among `windows`), else ({}, None): the one PREDICATE scan of `repair_limit`.
        The other readers (`repair_answer`, `owe_route`, the answer executor) look ONE window up by its key."""
        for entry in (self.state.get("repair_limit") or {}).values():
            if isinstance(entry, dict) and wanted(entry):
                window = next((w for w in windows if sorted(w.get("scope") or []) == sorted(entry.get("cases") or [])), None)
                if window:
                    return entry, window
        return {}, None

    OWED_TOKENS = ("round", "fixed", "review", "route")     # `route`: a recovery finish left an ordinary round owed (t-729 F4)

    def owe_route(self, dispatch: str, cases: list, route: dict) -> None:
        """A recovery road (`_finish_saved_result`, `resume_role`) finished a critic dispatch whose route still owes the AUTHOR a round
        (a test_defect or a mechanical one, no seam reason): the loop that would run it is not on the stack, so the round is recorded as
        owed and `stage_S5` runs it on the next entry - before the L5 refusal, which cannot name a door for it (t-698 A4, FR-1/FR-2).
        One record per window and critic dispatch (a repeated finish writes nothing new)."""
        if route.get("code") or route.get("action") not in ("test_defect", "mechanical"):
            return
        owed = self.state.setdefault("repair_limit", {})
        if (owed.get(self.repair_key(cases)) or {}).get("dispatch") == dispatch:
            return
        owed[self.repair_key(cases)] = {"dispatch": dispatch, "token": "route", "cases": list(cases), "key": "", "at": _now(),
                                        "words_file": "", "cause": "", "reason": route.get("reason") or "", "executed": False,
                                        "action": route["action"]}
        self.save_state()

    @staticmethod
    def repair_countable(budget) -> bool:
        """True when the budget carries both numbers a round is announced with (`counted`, `cap`)."""
        return isinstance(budget, dict) and isinstance(budget.get("counted"), int) and isinstance(budget.get("cap"), int)

    @staticmethod
    def repair_passes(budget):
        """{role: key} of `repair_budget.passes`, or None when the budget does not carry both keys (an older controller, A3)."""
        passes = budget.get("passes") if isinstance(budget, dict) else None
        ok = isinstance(passes, dict) and all(isinstance(passes.get(r), str) and passes[r] for r in ("qa-automator", "qa-code-critic"))
        return {r: passes[r] for r in ("qa-automator", "qa-code-critic")} if ok else None

    def repair_limit_gate(self, stage: str, role: str, dispatch: str, digest: str, scope=None, *, budget=READ_BUDGET,
                          recovering: bool = False) -> None:
        """Between a critic's handoff and its finish: the seam question when the review closes the window over a seam reason and
        the person has not answered for THIS dispatch. Acts only for (S5, qa-code-critic). POSITION INVARIANT: before `finish`, on
        all three roads that finish a critic - the stage is never closed over the question. Allowed error: asking when not
        needed; forbidden: closing without asking. A budget the controller cannot count is the seam reason `unknown`.
        `budget`: the one the S5 loop read for this very review (its forced `unknown` included) - passed, never re-read; the
        recovery roads pass none and the gate reads the controller's count. `recovering`: this road has no loop behind it, so a
        round the route still owes the author is recorded as owed for `stage_S5` (`owe_route`). Findings nobody repairs are told
        and the factory's own defect filed here on every road, once (`s5_note_findings`)."""
        if (stage, role) != ("S5", "qa-code-critic"):
            return
        if scope is None:
            scope = ((self.controller_state().get("dispatches") or {}).get(dispatch) or {}).get("scope") or []
        cases = list(scope)
        if budget is READ_BUDGET:
            budget = self.budget_or_none("S5", "qa-automator", cases, ref=dispatch)
        route, form = self.route_of(digest, budget, dispatch)
        self.s5_note_findings(route, form, dispatch)
        if not route.get("code") or self.repair_answer(cases, dispatch):
            if recovering:
                self.owe_route(dispatch, cases, route)
            return
        if route["code"] not in ("unknown", "untyped") and self.repair_passes(budget) is None:
            self.repair_older_controller("S5", dispatch, budget, "were sent back")
        self.repair_limit_raise(self.repair_limit_facts(dispatch, cases, route, form, budget))

    def repair_older_controller(self, stage: str, dispatch: str, budget, said: str) -> None:
        """An older controller: the keys a `round` needs are not in its record, and the driver never rebuilds them (A3) - the question
        of `stage` is a refusal naming the missing key, never a `round` the driver could not record. Always raises (the seam)."""
        self.no_move({"why": "threshold", "kind": "refusal", "call": False, "stage": stage, "dispatch": dispatch,
                      "lead": f"The tests of this step {said} and the factory cannot say how many more rounds they "
                              "may have: its controller does not report them. Which of these should happen?",
                      "text": f"controller prepare for S5 qa-automator carries no repair_budget.passes: {json.dumps(budget)[:400]}"})

    def repair_limit_facts(self, dispatch: str, cases: list, route: dict, form, budget) -> dict:
        """The facts of the question, kept in the driver's state while it is open (the answer reads them): which key, which answers
        are offered, the passes a `round` / `fixed` will record, and the lead in a person's words (A6: no id, no cause token)."""
        import repair_route
        code = route["code"]
        blocking = [f for f in repair_route.findings(form) if f["blocking"]] if form else []
        causes = {f["cause"] for f in blocking}
        counted = budget.get("counted") if isinstance(budget, dict) else None
        cap = budget.get("cap") if isinstance(budget, dict) else None
        round_counted, round_cap = counted, cap       # what a `round` spends: the test_defect counter, whatever the reason (t-729 S1)
        if code == "mech_cap":
            counted, cap = budget.get("mechanical"), budget.get("mechanical_cap")      # the reason's own numbers (the opening, the debt)
        key, offer, cause = "s5.repair_limit", ["round", "debt", "fixed", "stop"], ""
        if code == "nobody":
            first = next((c for c in self.NOBODY_ORDER if c in causes), "tooling")
            key, offer, cause = {"environment": ("s5.nobody_environment", ["fixed", "debt", "stop"], "environment"),
                                 "reviewer_error": ("s5.nobody_review", ["review", "debt", "stop"], "reviewer_error"),
                                 "tooling": ("s5.nobody_tooling", ["debt", "stop"], "")}[first]
        elif code == "unknown":
            offer = ["debt", "stop"]
        elif code == "untyped":
            # F4 (d): the verdict sent the window back and the form holds no typed finding - the existing closed question
            # `s5.nobody_review` (no new key, no conductor call); `review` spends none of the repair limit
            key, offer, cause = "s5.nobody_review", ["review", "debt", "stop"], "reviewer_error"
        where = ", ".join(cases)
        opening = {
            "cap": f"For {where}: the critic sent the tests back {counted} times; the factory's limit for that is {cap} rounds, "
                   "and it is used up.",
            "mech_cap": f"For {where}: the critic asked for technical fixes to the tests {counted} times; the factory's limit for "
                        f"that is {cap} rounds, and it is used up.",
            "unknown": f"For {where}: the critic sent the tests back, and the factory could not count how many rounds they have "
                       "already had, so it will not start another on its own; starting a round and asking for one more are both "
                       "left out of the answers below.",
            "sent_back": f"For {where}: the critic sent the tests back without naming a blocking finding, so there is nothing "
                         "specific for the test writer to repair.",
            "untyped": f"For {where}: the critic sent the tests back but wrote no finding the test writer can act on; the critic "
                       "can review again and name them.",
            "nobody": {"environment": f"For {where}: the critic could not finish judging the tests because the stand got in the "
                                      "way, and the test writer cannot repair a stand.",
                       "reviewer_error": f"For {where}: the critic sent the tests back, but the doubt is about the critic's own review, "
                                         "not about the tests, and the test writer cannot repair a review.",
                       "tooling": f"For {where}: the critic sent the tests back over a fault in the factory's own tools, and the "
                                  "test writer cannot repair a tool."}.get(cause or "tooling")}[code]
        # A6: "<test> - <problem in the critic's words>" (the cause in words after it); a finding naming no test says so
        lines = [f"- {f['file'] or '(no test named)'} — {f['problem'] or 'the critic gave no reason'} "
                 f"({self.CAUSE_WORDS.get(f['cause'], f['cause'])})" for f in blocking]
        lead = "\n".join([opening, *(["", "What the critic still asks for:", *lines] if lines else []), "", "Which of these should happen?"])
        passes = self.repair_passes(budget)     # None is refused by the gate before this point, except for `unknown` (which offers no `round`)
        reason = next((f["problem"] for f in blocking if f["cause"] == cause), "") if cause else ""
        # the review debt's reason is the ledger's closed list (`ledger.DEBT_REASONS`, which holds `untyped`)
        return {"dispatch": dispatch, "cases": cases, "key": key, "offer": offer, "code": code,
                "lead": lead, "cause": cause,
                "passes": passes or {}, "counted": counted, "cap": cap, "round_counted": round_counted, "round_cap": round_cap,
                "reason": reason, "by_cause": (budget.get("by_cause") if isinstance(budget, dict) else None) or {}}

    def repair_limit_raise(self, ask: dict) -> None:
        """Keep the facts and raise the site's own question through the seam (`call=False`: no paid call; the doors are the
        question's own answers, so a word that is none of them goes to the conductor once)."""
        self.state["repair_ask"] = ask
        self.save_state()
        self.no_move({"why": "threshold", "kind": "repair_limit", "call": False, "stage": ask.get("stage", "S5"), "dispatch": ask["dispatch"],
                      "lead": ask["lead"], "site_doors": tuple(t for t in ask["offer"] if t != "stop"),
                      "site_fallback": lambda said: self.repair_limit_person(ask, said)})

    def repair_limit_person(self, ask: dict, said: str = "") -> Person:
        """The question from its facts: `said` (an unread answer's lead, else the account itself) above the account, then the priced
        answers of the key. One literal `closed_question` per key (the census of question ids reads them)."""
        lead = ask["lead"] if not said.strip() or said.strip() == ask["lead"].strip() else said.strip() + "\n\n" + ask["lead"]
        cases = ", ".join(ask["cases"])
        says = {"round": ("the test writer repairs what the critic rejected, then the critic reviews the tests again; this is round "
                          f"{(ask.get('round_counted', ask['counted']) or 0) + 1} and the factory's limit is "
                          f"{ask.get('round_cap', ask['cap'])}", {"role": "the test writer"}),
                "debt": (f"the window closes now; the tests for {cases} stay rejected and the report lists each with what the "
                         "critic asked", {}),
                "fixed": (("answer this once you have fixed the stand; the critic then reviews the tests again", {"what": "the stand"})
                          if ask["key"] == "s5.nobody_environment" else
                          ("answer this once you have changed the tests yourself; the critic then reviews them again",
                           {"what": "the changes the critic asked for"})),
                "review": ("the critic reviews the window again; this round spends none of the repair limit", {"role": "the critic"})}
        if ask["key"] == "s7.repair_limit":
            says = self.s7_says(ask)
        options = [dict(self.STOP_OPTION) if a == "stop" else
                   {"answer": a, "token": a, "says": says[a][0], "slots": says[a][1]} for a in ask["offer"]]
        if ask["key"] == "s7.repair_limit":
            text = self.closed_question("s7.repair_limit", lead, options)
        elif ask["key"] == "s5.nobody_review":
            text = self.closed_question("s5.nobody_review", lead, options)
        elif ask["key"] == "s5.nobody_environment":
            text = self.closed_question("s5.nobody_environment", lead, options)
        elif ask["key"] == "s5.nobody_tooling":
            text = self.closed_question("s5.nobody_tooling", lead, options)
        else:
            text = self.closed_question("s5.repair_limit", lead, options)
        return Person("repair_limit", text, ask.get("stage", "S5"), ask["dispatch"])

    @staticmethod
    def s7_says(ask: dict) -> dict:
        """The code-side words of the S7 answers (the price lines come from the data): no critic reviews an S7 repair, so `round` is the
        author's one more session and a new run of the test; `debt` leaves the test failing and listed."""
        return {"round": (f"the test writer repairs {ask['name']} once more and the test is run again; this is round "
                          f"{(ask.get('round_counted') or 0) + 1} and the factory's limit is {ask.get('round_cap')}", {"role": "the test writer"}),
                "debt": ((f"the repairs of {ask['name']} stop now; it stays failing and the report lists it with the reason the run failed"
                          if ask.get("bound", True) else
                          f"the repairs of {ask['name']} stop now; it stays failing and is recorded under the run's own name; it is "
                          "not yet listed in the report"), {})}

    @staticmethod
    def repair_pass_keys(token: str, ask: dict, stage: str) -> list:
        """The waiver keys an answer records, from the controller's own `passes` (never rebuilt): `round` the author's and, at S5, the
        critic's (an S7 repair has no critic); `fixed` the critic's only, and only for the cap question; every other token none."""
        passes = ask["passes"]
        if token == "round":
            return [passes["qa-automator"]] + ([] if stage == "S7" else [passes["qa-code-critic"]])
        return [passes["qa-code-critic"]] if token == "fixed" and ask["key"] == "s5.repair_limit" else []

    def _answer_repair_limit(self, words: str, qtext: str, stage: str, dispatch: str) -> None:
        """The answer to the repair-limit question (FR-9: each token has an executor; FR-12: tokens only). `round` records the two
        passes of the controller's own keys (the author's and the critic's, one answer; the author's alone at S7); `fixed` the critic's
        pass only (or none, for the stand); `review` none; `debt` the window in `work/review-debts.json` through THE writer; `stop` holds
        the question. The choice is kept per window and critic dispatch (S7: per test and count), so the gate lets exactly that review
        (that round) through; any other word goes to the seam."""
        ask = self.state.get("repair_ask") or {}
        token = self.s0_normalize(words)
        kept = self.state.get(self.repair_store_name(stage)) or {}
        if token == "debt" and ask.get("dispatch") != dispatch and any(
                isinstance(e, dict) and e.get("dispatch") == dispatch and e.get("token") == "debt" for e in kept.values()):
            # t-733 edges 1 and 3: the same `debt` again (its question is answered already, the window perhaps closed): nothing new is written
            print(f"{stage}: the answer `debt` is recorded already; nothing more is written")
            return
        if ask.get("dispatch") != dispatch or token not in ask.get("offer", ()):
            self.unread("repair_limit", stage, dispatch, qtext, words=words, doors=tuple(ask.get("offer") or ("stop",)),
                        lead=self.unread_lead(words), again=lambda said: self.repair_limit_person(ask, said) if ask else self.held_question(said))
            return
        spent = ask.get("round_counted", ask.get("counted"))
        surplus = token == "round" and isinstance(spent, int) and isinstance(ask.get("round_cap", ask.get("cap")), int) \
            and spent < ask.get("round_cap", ask.get("cap"))
        # the Lead's answer 5 (t-716): a surplus round is acceptable ONLY because the person bought it by this token - the record says so
        self.answer_row(f"{stage} repair limit ({token}{', round bought on a cap not spent' if surplus else ''}): ", words.strip(),
                        what="your answer at the repair limit")
        if token == "stop":
            raise self.held_question(self.stop_held("If you want the factory to go on after all, answer one of the other answers."))
        if stage == "S7" and not ask.get("life"):       # N10: under life "" nothing is written and nothing is trusted (FR-59)
            raise self.held_question("The factory could not read which triage run this question belongs to, so your answer was not "
                                     "recorded and nothing was passed.")
        file = self.answer_file()
        for key in self.repair_pass_keys(token, ask, stage):
            code, out = self.py("waiver.py", "--task", self.task, "--stage", "S5", "--block", key, "--words-file", str(self.task_root / file),
                                *self.waiver_road())
            if code:
                print(f"{stage}: the pass was not recorded ({out[-300:]}); the question comes back")
                raise self.held_question("Your word could not be recorded as the pass for another round, so nothing was passed.", out)
        if token == "debt" and not self.record_repair_debt(ask, file):
            raise self.held_question("Your choice could not be recorded: the record of the earlier answers of this kind cannot be read, "
                                     "so the window stays open and nothing is closed.")
        slot = dispatch if stage == "S7" else self.repair_key(ask["cases"])      # S7: one record per test and count, the dispatch IS the slot
        before = kept.get(slot) or {}
        # t-733: a `debt` to the question of an OWED round (the round of this very critic dispatch) consumes it: `stage_S5` completes the finish
        consumed = before.get("token") if token == "debt" and before.get("dispatch") == dispatch and before.get("token") in ("round", "route") else ""
        self.state.setdefault(self.repair_store_name(stage), {})[slot] = {
            "dispatch": dispatch, "token": token, "cases": ask["cases"], "key": ask["key"], "at": _now(), "words_file": file,
            "cause": ask["cause"] if token in ("fixed", "review") and ask["key"] != "s5.repair_limit" else "", "reason": ask["reason"],
            "executed": token == "debt", **({"owed": consumed} if consumed else {}), **({"tests": ask["tests"], "life": ask["life"], "ident": ask["ident"]} if stage == "S7" else {})}
        self.state.pop("repair_ask", None)
        self.save_state()
        print(f"{stage}: the person's answer `{token}` is recorded for {ask.get('name') or ', '.join(ask['cases'])}")

    @staticmethod
    def repair_store_name(stage: str) -> str:
        """The driver-state key that keeps the answers of the repair-limit question: the S5 windows' (`repair_limit`, matched by their
        cases) and the S7 tests' (`repair_limit_s7`, one per test and count) are two stores, so no S5 reader meets an S7 record."""
        return "repair_limit_s7" if stage == "S7" else "repair_limit"

    def record_repair_debt(self, ask: dict, words_file: str) -> bool:
        """The window as a review debt, through THE writer (`ledger.write_review_debt`); False when the writer could not record it.
        An S7 window names its TESTS (instance ids) and no critic or form; a record of S5 for the same cases is another window."""
        import ledger
        s7 = ask.get("stage") == "S7"
        form = f"work/handoffs/{ask['dispatch']}.yaml"
        window = {"stage": "S7" if s7 else "S5", "cases": ask["cases"], "tests": ask["tests"] if s7 else [],
                  "critic_dispatch": "" if s7 else ask["dispatch"],
                  "form": form if not s7 and (self.task_root / form).is_file() else "", "reason": ask["code"],
                  "rounds": {"counted": ask["counted"], "cap": ask["cap"], "by_cause": ask["by_cause"]},
                  "choice": {"token": "debt", "words_file": words_file, "at": _now()}}
        return ledger.write_review_debt(self.task_root, window) is not None

    # --- TR3-10 D (t-2283): the way question of S6, `walk_supply` (spec t-2174 Part D items 9-11, section 4, L5) -----------------------

    # The site's own closed question: asked once per project, set aside (`no_hold`: it holds no case) and put to the person at gate B.
    # Built like `repair_limit_person` (a priced `closed_question`, NO `offered`); a token has an executor, any other word goes to the
    # conductor once through `unread`. The raise site writes the registry row first and hands its id to `walk_supply_person`.
    # The tokens and the sentence each one records (the `answer` ids of `s6.walk_supply` in question-prices.json; insertion order = option order).
    WALK_SUPPLY_SENTENCES = {
        "the app makes them": ("each extra walker signs up a new user on the app's own sign-up page and makes the records it changes "
                               "through the app, on stands the project's settings allow the factory to change"),
        "one at a time": ("use only the accounts already recorded; checks that share an account or a record run one after another"),
        "I will add accounts": ("the person adds more accounts to the project's environment file and names their keys; until they are "
                                "recorded, checks that share an account run one after another")}

    def walk_supply_text(self, short: list) -> "Priced":
        """The way question (spec section 4; `human-questions.md`): what the factory did, why it cannot decide, one question, the three
        priced answers of `s6.walk_supply`; no option is recommended (the choice is the person's intent). `short` is `walk_pool.short_parts`'s
        list `[(part, lanes waiting, pool size)]`; a part is named by the role as the stand lists it (`default` is the stand's main
        account). Empty `short` (a data shortage raised it): the same question about records alone."""
        shared = []
        for part, waiting, _size in short or []:
            who = "the stand's main account" if part in ("", "default") else f"the stand's {part} account"
            shared.append(f"{who}: {waiting} group{'' if waiting == 1 else 's'} of checks had to wait for another")
        what = ("sign in as the same account (" + "; ".join(shared) + "), so they ran one after another — two walkers in one account would "
                "see each other's work" if shared else "work on the same records, so they ran one after another — two walkers changing "
                "one record would disturb each other's work")
        lead = (f"Some manual checks of this story {what}. Nothing was skipped; this story's checks already ran, only slower. Your "
                "project's settings do not say how it gets more test accounts, or which records walkers may share, and the factory does "
                "not guess. Your answer is kept for this project, so you are asked this once.\n\n"
                "How should walkers get their own accounts and records on this project?")
        sentences = self.WALK_SUPPLY_SENTENCES
        return self.closed_question("s6.walk_supply", lead, [
            {"answer": "the app makes them", "token": "the app makes them",
             "says": sentences["the app makes them"] + "; from the next story these checks run side by side, and the users they make "
                     "are named in the report and left on the stand"},
            {"answer": "one at a time", "token": "one at a time",
             "says": sentences["one at a time"] + "; manual checks keep taking longer"},
            {"answer": "I will add accounts", "token": "I will add accounts", "slots": {"what": "adding the accounts to the project's environment file"},
             "says": ("you put more accounts in the project's environment file and tell me, in your own words, the names of their keys (and, "
                      "if you like, which records walkers may share); until they are recorded the checks run one after another")}])

    def walk_supply_person(self, row_id: str, short: list) -> Person:
        """The way question as a `Person` (kind `walk_supply`, stage S6): NO `offered` (L5), `holds = ()` and `no_hold = True` (read by
        `deferrable`: it waits, holds no case and is put at gate B). `row_id` is the registry row the raise site opened; it is kept in
        `state["walk_supply_asked"]` (the one producer of what `_answer_walk_supply` reads) together with the roles of the short parts
        (`state["walk_supply_roles"]`, what `the app makes them` records). `ask()` saves the state."""
        self.state["walk_supply_asked"] = str(row_id)
        self.state["walk_supply_roles"] = list(dict.fromkeys(str(part) for part, _waiting, _size in short or [] if str(part).strip()))
        person = Person("walk_supply", self.walk_supply_text(short), "S6", answer_note=(
            "Write one of `the app makes them`, `one at a time`, `I will add accounts`, or your own words "
            "(they are read by the conductor and recorded for the project)."))
        person.holds, person.no_hold = (), True
        return person

    def _resolve_decision_row(self, kind: str, row: str, values: dict) -> None:
        """The ONE body of "resolve a registry row with the person's words" (AR-15; the S6 account/data questions share it): runs
        `project_decisions.py resolve` with the answer's words file and the pointer -> value map. No words file, or an exit != 0, is a
        `Refusal` naming the row and the exit: the question stays and the words are on record in `driver-answers.jsonl` (FR-41)."""
        file = self.answer_file()
        if not file:
            raise Refusal(f"{kind}: the answer has no words file, so row {row} was not resolved; the question stays")
        code, out = self.py("project_decisions.py", "--root", str(self.project), "resolve", "--id", row, "--words-file", str(self.task_root / file),
                            "--resolution-ref", f"{self.task} S6", "--field-values", json.dumps(values, ensure_ascii=False))
        if code:
            raise Refusal(f"{kind}: project_decisions.py resolve of row {row} failed (exit {code}); the question stays and the person's "
                          f"words are on record in driver-answers.jsonl:\n{out[-300:]}")

    def _answer_walk_supply(self, words: str, qtext: str, stage: str, dispatch: str) -> None:
        """The answer to the way question (FR-9: each token has an executor; FR-12 / AR-2: the three tokens are the whole closed set, code
        never parses any other word). A token runs `project_decisions.py resolve` on the registry row with the person's words file; the
        value at each pointer is the project's CURRENT object there with only this answer's keys replaced (merge on write: a hand-added
        `more_accounts` survives). Any other words - empty, none of the tokens, words that name a password - go to the conductor ONCE,
        whole, with the registry row named. A failed `resolve` is a `Refusal` naming the row and the exit: the question stays (FR-41),
        the words are on record in `driver-answers.jsonl`."""
        row = str(self.state.get("walk_supply_asked") or "")
        by_norm = {self.s0_normalize(token): (token, sentence) for token, sentence in self.WALK_SUPPLY_SENTENCES.items()}
        picked = by_norm.get(self.s0_normalize(words))
        if picked is None or not row:
            note = f"This question is row {row} of the project's decision registry (the id the recording command takes).\n\n" if row else ""
            self.unread("walk_supply", stage, dispatch, note + qtext, words=words, doors=tuple(self.WALK_SUPPLY_SENTENCES),
                        lead=self.unread_lead(words), again=lambda said: self.held_question(said))
            return
        token, sentence = picked
        said = words.replace(self.BOM, "").strip()
        recorded = f"{sentence}. The person answered: \"{said}\""
        import manual_capture as MC
        try:
            config = MC.load_config(self.task_root)[0]
        except ValueError as exc:
            raise Refusal(f"walk_supply: the project's settings cannot be read ({exc}), so row {row} was not resolved; the question stays")

        import config_contract as CC
        raw = CC.walk_supply_raw(config)        # the raw objects, used only to write them back whole (the deciding readers use `walk_supply`)

        def merged(slot: str, **keys) -> dict:
            return {**raw[slot], **keys}
        # TR3-10d D3b-2 (item 2): `walk_supply_roles` holds PART names (`stand_account:user`, `default`, `env:<login key>`); `self_sign_up.roles` is
        # read back as ROLE names (`walk_pool.obtain_roles_of`). A part is reduced by the readers that exist - the role after `stand_account:`,
        # `default`, the role `walk_pool.walk_env_pair` finds for an `env:` login key - and one none of them reads is left out and NAMED, never guessed.
        sign_up, left_out = [], []
        if token == "the app makes them":
            import walk_pool as WP
            stand = next((e for e in (config.get("environments") if isinstance(config, dict) else None) or [] if isinstance(e, dict)), {})
            for part in (str(p) for p in self.state.get("walk_supply_roles") or []):
                kind, _, value = part.partition(":")
                if part == "default" or (kind == "stand_account" and value.strip()):
                    role = "default" if part == "default" else value.strip()
                else:
                    role = WP.walk_env_pair(stand, value)[0] if kind == "env" and value.strip() else ""
                if not role:
                    left_out.append(part)
                elif role not in sign_up:
                    sign_up.append(role)
        accounts = {"words": recorded, **({"self_sign_up": {"roles": sign_up}} if token == "the app makes them" else {})}
        names = CC.walk_supply_keys()
        values = {f"/manual/{names['accounts']}": merged("accounts", **accounts), f"/manual/{names['data']}": merged("data", words=recorded)}
        self._resolve_decision_row("walk_supply", row, values)
        self.state.pop("walk_supply_roles", None)
        self.answer_row("S6 walk supply: ", said, what="your answer about how walkers get their accounts and records")
        print(f"S6: the answer `{token}` is recorded for this project")
        if left_out:
            print(f"S6: these accounts could not be read as roles of the stand, so they are not on the list of roles a walker may sign up as: "
                  f"{', '.join(left_out)}")
        if token == "I will add accounts":
            print("S6: you said you will add accounts; until they are in the project's settings the checks that share an account run "
                  "one after another")

    # --- TR3-10 D3a step 2 (t-2290): the data-change question `data_change` (spec t-2174 Part D item 12) -------------------------------

    # Whether the factory may make and remove records on the stand for the pools; asked once per project, set aside like `walk_supply`
    # (`no_hold`), a token has an executor (`_answer_data_change`), any other word goes to the conductor once. The raise site writes the
    # registry row first and hands its id to `data_change_person`. The keys ARE the three sentences `config_contract.DATA_MAY_OPTIONS` reads
    # back (the `answer` ids of `s6.data_change`; a test pins the two together); the value is what the option means to the person.
    DATA_CHANGE_SAYS = {
        "only use what exists": ("the factory never makes or removes records; checks that need their own record run one after another, "
                                 "and these checks keep taking longer"),
        "may create, never delete": ("a walker makes its own record for such a check; the record stays on the stand and the report names it; "
                                     "later each such walker spends a few steps making a record"),
        "may create and delete": ("a walker makes its own record for such a check and removes it when the check is done; a few more steps "
                                  "per such check")}

    def data_change_text(self, kinds: list, may_change: bool = True) -> "Priced":
        """The data-change question (spec item 12; `human-questions.md`): the kinds in the story's words (empty `kinds`: "a record"),
        that the answer applies to the stand the person's settings name, that this story's checks already ran one after another (D.4),
        and - when `may_change` is False - that the settings do not mark the stand as one that may be changed. No option is recommended."""
        names = [str(k).strip() for k in kinds or [] if str(k).strip()]
        things = [("an " if n[0].lower() in "aeio" else "a ") + n for n in names] or ["a record"]
        what = things[0] if len(things) == 1 else ", ".join(things[:-1]) + " and " + things[-1]
        stand = ("" if may_change else " Your settings do not mark this stand as one that may be changed, so until you answer the factory "
                                         "only uses what exists.")
        lead = (f"Some manual checks of this story change {what} that other checks also use, and the project's list has no free one for each "
                "walker, so those checks ran one after another; nothing was skipped and this story's checks already ran, only slower. "
                f"Your answer applies to the stand your settings name.{stand} Your answer is kept for this project, so you are asked this once.\n\n"
                "May the factory make records on the stand for them, and remove them afterwards?")
        return self.closed_question("s6.data_change", lead, [
            {"answer": token, "token": token, "says": says} for token, says in self.DATA_CHANGE_SAYS.items()])

    def data_change_person(self, row_id: str, kinds: list, may_change: bool = True) -> Person:
        """The data-change question as a `Person` (kind `data_change`, stage S6): NO `offered`, `holds = ()`, `no_hold = True` (read by
        `deferrable`). `row_id` is the registry row the raise site opened; it is kept in `state["data_change_asked"]` (the one producer of
        what `_answer_data_change` reads, and the raise site's "once per story" test). `ask()` saves the state."""
        self.state["data_change_asked"] = str(row_id)
        person = Person("data_change", self.data_change_text(kinds, may_change), "S6", answer_note=(
            "Write one of `only use what exists`, `may create, never delete`, `may create and delete`, or your own words "
            "(they are read by the conductor and recorded for the project)."))
        person.holds, person.no_hold = (), True
        return person

    def _answer_data_change(self, words: str, qtext: str, stage: str, dispatch: str) -> None:
        """The answer to the data-change question (FR-9: each token has an executor; FR-12 / AR-2: the three tokens are the whole closed
        set, code never parses another word). A token runs `project_decisions.py resolve` with `{"/manual/data_way/may": <the sentence>}`;
        any other words go to the conductor ONCE, whole, the registry row named. No `data_change_asked` in state, or a failed `resolve`,
        is a `Refusal` naming what is missing / the row and the exit: the question stays."""
        row = str(self.state.get("data_change_asked") or "")
        if not row:
            raise Refusal("data_change: the state has no `data_change_asked` (the registry row of this question), so the answer cannot be "
                          "recorded; the question stays and the person's words are on record in driver-answers.jsonl")
        picked = {self.s0_normalize(token): token for token in self.DATA_CHANGE_SAYS}.get(self.s0_normalize(words))
        if picked is None:
            self.unread("data_change", stage, dispatch,
                        f"This question is row {row} of the project's decision registry (the id the recording command takes).\n\n" + qtext,
                        words=words, doors=tuple(self.DATA_CHANGE_SAYS), lead=self.unread_lead(words), again=lambda said: self.held_question(said))
            return
        self._resolve_decision_row("data_change", row, {"/manual/data_way/may": picked})
        self.answer_row("S6 data change: ", words.replace(self.BOM, "").strip(), what="your answer about what the factory may do with records")
        print(f"S6: the answer `{picked}` is recorded for this project")

    # --- TR3-10 D (t-2291): the account question of S6, `walk_account` (spec t-2174 item 13; sibling of `stand_login_gate`, AR-15) ----------

    # Asked for the data of ONE account the project does not have, one question per role; it holds the tied cases (deferrable through the
    # EXISTING rule: no `no_hold`). Built like `walk_supply_person` (a priced `closed_question`, NO `offered`). `by hand` / `go on` are carried
    # out here as `stand_login_gate` does; `added` and every other word go to the conductor (it records key NAMES, code never parses words).
    def walk_account_text(self, role: str, cases: list, lines: list) -> "Priced":
        """The account question (`human-questions.md`): what is missing, in the project's words, what the factory did (the other checks go
        on), one question, the three priced answers of `s6.walk_account`. `lines` are the formed case lines (`case_lines`: title and id);
        `role` is named as the stand lists it. No key path and no file of ours in the body: the project's environment file is the person's
        own and is named only because the question asks them to edit it."""
        who = "main" if role in ("", "default") else role
        lead = (f"These checks need a {who} account that the project's settings do not have yet:\n" + "\n".join(lines)
                + f"\nI have not started {'it' if len(cases) == 1 else 'them'}. Nothing else waits for it: the other checks go on. "
                "Put the account's login and password in your project's environment file (never in this chat) and tell me the names "
                "of the two keys.\n\nWhat should happen with these checks?")
        return self.closed_question("s6.walk_account", lead, [
            {"answer": "added", "token": "added", "slots": {"what": "adding the account's login and password to your project's environment file"},
             "says": ("you put the account's login and password in the environment file and tell me the names of the two keys; I record the "
                      "names, check that the account signs in, and the next run of the story checks these cases")},
            {"answer": "by hand", "token": "by hand", "slots": {"what": "the checks named above"},
             "says": "you will check these yourself; I leave them out and the report says so, in your words"},
            {"answer": "go on", "token": "go on",
             "says": "leave them unchecked; the report carries them as not checked"}])

    def walk_account_person(self, row_id: str, role: str, cases: list, case_lines: list) -> Person:
        """The account question as a `Person` (kind `walk_account`, stage S6): NO `offered` (L5), `holds` = the tied cases and NO `no_hold`
        (`deferrable` sets it aside through its existing case test). `case_lines` are the lines the raise site formed (it lives above
        `Driver.case_lines`' layer). The one producer of `state["walk_account_asked"][row_id] = {"role", "cases"}`, which
        `_answer_walk_account` reads. A role the code cannot hand to the conductor as a key (empty, with a space, non-ASCII), no tied case or no
        registry row is a `Refusal` that says what is missing: nothing is asked, nothing guessed."""
        role, row_id = str(role or ""), str(row_id or "")
        tied = [str(case) for case in cases or [] if str(case).strip()]
        if not role or not role.isascii() or any(ch.isspace() for ch in role):
            raise Refusal(f"walk_account: the role {role!r} cannot be named as an account key (it is empty, has a space or a non-ASCII "
                          "character); the account question was not raised")
        if not tied:
            raise Refusal(f"walk_account: no case is tied to the {role} account, so the question has nothing to hold; it was not raised")
        if not row_id:
            raise Refusal(f"walk_account: no registry row for the {role} account was given, so the answer could not be recorded; the question "
                          "was not raised")
        held = self.state.get("walk_account_asked")
        self.state["walk_account_asked"] = held = held if isinstance(held, dict) else {}
        # TR3-10d D3b-2 (fix a): ONE live row per role - a stale row of this role under another id goes, so a later answer never meets two
        for stale in [key for key, val in held.items() if key != row_id and isinstance(val, dict) and val.get("role") == role]:
            held.pop(stale)
        held[row_id] = {"role": role, "cases": tied}
        seen = self.state.get("walk_account_roles")
        self.state["walk_account_roles"] = seen = seen if isinstance(seen, dict) else {}
        seen[role] = row_id        # kept for the story (never popped): the raise site asks a role once per story
        person = Person("walk_account", self.walk_account_text(role, tied, [str(line) for line in case_lines or []]), "S6", answer_note=(
            "Write `added` and the two key names (for example `added: <LOGIN KEY> and <PASSWORD KEY>`; never the password itself), "
            "`by hand` or `go on`, or your own words (they are read by the conductor)."))
        person.holds = tuple(tied)
        return person

    def _answer_walk_account(self, words: str, qtext: str, stage: str, dispatch: str) -> None:
        """The answer to the account question (FR-9: each token has an executor; FR-12 / AR-2: three tokens, never a phrase). `by hand` ->
        `refuse_case(..., "person_checks")`, `go on` -> `refuse_case(..., "left_unchecked")` for every tied case, as `stand_login_gate`
        does. A BARE `added` (no key name for the conductor to record) is asked again ONCE (`state["walk_account_again"][role]`) with the
        reason "you said the account is added, but did not name the two keys" (D3b-2: not "the keys you named are not in the environment
        file" - that is for a probe that found no keys), then treated as `go on` (one recorded decision per class, P5). `added`
        with names and every other word go to the conductor ONCE, whole: it records key names. The words are never copied into a text
        built here (a password may stand in them). The question's role and cases come from `state["walk_account_asked"]`: the entry whose
        cases are the deferred item's `holds`, else the only entry; none or several that cannot be told apart is a `Refusal`."""
        entries = self.state.get("walk_account_asked")
        entries = {str(key): val for key, val in entries.items() if isinstance(val, dict) and val.get("role") and val.get("cases")} \
            if isinstance(entries, dict) else {}
        if not entries:
            raise Refusal("walk_account: the record of this question (its role and tied cases, `walk_account_asked`) is missing, so the "
                          "answer was not carried out; the question stays and the person's words are on record in driver-answers.jsonl")
        asked = self.state.get("asked") or {}
        chosen = None
        if asked.get("deferred_n") is not None:
            item = next((i for i in self.deferred_items() if i["n"] == asked["deferred_n"]), None)
            held = sorted(str(case) for case in (item or {}).get("holds") or [])
            same = [key for key, val in entries.items() if sorted(str(case) for case in val["cases"]) == held]
            chosen = same[0] if len(same) == 1 else None
        if chosen is None and len(entries) == 1:
            chosen = next(iter(entries))
        if chosen is None:
            raise Refusal("walk_account: " + str(len(entries)) + " account questions are recorded and none of them is the one answered, so "
                          "the answer was not carried out; the question stays and the person's words are on record in driver-answers.jsonl")
        row, role, cases = chosen, str(entries[chosen]["role"]), [str(case) for case in entries[chosen]["cases"]]
        again = self.state.get("walk_account_again")
        self.state["walk_account_again"] = again = again if isinstance(again, dict) else {}
        token = self.s0_normalize(words)
        reason = ""
        if token == "added" and not again.get(role):
            again[role] = 1
            # remains: the person's own question comes back once with what is missing (the two key names); a second "added" closes as `go on`
            raise self.held_question("You said the account is added, but did not name the two keys. Tell me the names of the two variables "
                                     "in your environment file that hold its login and password, or answer `by hand` or `go on`.")
        if token == "added":
            token, reason = "go on", "you said the account is added but did not name its two keys, after you were asked twice"
        if token in ("by hand", "go on"):
            by = "person_checks" if token == "by hand" else "left_unchecked"
            reason = ("not checked by an agent: the " + role + " account it needs is not in the project's settings"
                      + (f"; you answered `{token}`" if not reason else f"; {reason}"))
            door = "put the account's login and password in the project's environment file and name the keys; the next run checks it by hand"
            for case in cases:
                if self.refuse_case(None, case, reason, door, by):
                    print(f"S6: {case}: not checked by hand — {reason}")
                else:
                    print(f"S6: {case}: the decision could not be written to its request.json; the answer is on record")
            entries_left = self.state.get("walk_account_asked")
            entries_left.pop(row, None)
            again.pop(role, None)
            self.answer_row("S6 walk account: ", token, what=f"your answer about the {role} account")
            return
        note = (f"This question is row {row} of the project's decision registry (the id the recording command takes). It asks for the "
                f"account of the role `{role}` (the key of the account in the project's settings) for these cases: {', '.join(cases)}.\n\n")
        self.unread("walk_account", stage, dispatch, note + qtext, words=words, doors=("added", "by hand", "go on"),
                    lead=self.unread_lead(words), again=lambda said: self.held_question(said))

    # --- an exit-gate refusal that survives the resume limit: the ONE seam (conductor/1, C1-5d; t-698 §12-§14, t-764) -----------

    # The class (FR-42, P22): the role was resumed once on this finding set (t-217) and the set came back; `rework` has nothing to
    # rework because no dispatch of the role is accepted. Five callers reach `exit_limit`: the handoff ladder (E3/E6), the refusal
    # road (E8, E9), a resume whose session is gone (E10) and the structured-artifact repeat (E11). It asks the person directly
    # (`call=False`: the conductor reads only words code cannot), with four answers whose executors are `_answer_exit_limit`'s.
    EXIT_SOURCES_SHOWN = 12         # sources the lead lists; the rest is counted (the GATE_TOP_LIMIT precedent)

    def exit_record(self, dispatch: str) -> dict:
        """`state["exit_limit"][dispatch]`: `lines` (the set that reached the seam), `key`, `rounds` ({key: {granted, spent,
        words_file, at}}), `ask` (the question's facts), `passes` (the waiver rows `go on` wrote), `fresh_line`."""
        held = self.state.get("exit_limit")
        if not isinstance(held, dict):
            held = self.state["exit_limit"] = {}
        rec = held.get(dispatch)
        if not isinstance(rec, dict):
            rec = held[dispatch] = {}
        return rec

    def revoke_passes_of_dead(self, dead=()) -> None:
        """t-764 A5 (F3): ONE sweep that revokes the waiver rows `go on` wrote for every dispatch the controller no longer holds
        live (accepted, released, superseded, stale ... - `NM.LIVE_STATUSES` is the live set; `dead`: dispatches known dead before
        the controller's record shows it). A row outlives its dispatch only until the next call of this sweep, which stands at the
        top of `handoff` (t-781 m4: a dispatch the conductor's `restart` released passes nothing to the relaunch's `exit_errors`),
        at the seam's entry, at `finish` and after the seam's own `release`. A dispatch the controller does not know is not dead
        (FR-41); a revoke that fails keeps its row for the next sweep. No row anywhere: it returns at once, reads and writes nothing."""
        held = self.state.get("exit_limit")
        if not isinstance(held, dict) or not any(isinstance(r, dict) and r.get("passes") for r in held.values()):
            return
        try:
            known = self.controller_state().get("dispatches") or {}
        except Exception:
            known = {}
        changed = False
        for dispatch, rec in held.items():
            passes = rec.get("passes") if isinstance(rec, dict) else None
            status = (known.get(dispatch) or {}).get("status") if isinstance(known.get(dispatch), dict) else None
            if not passes or not (dispatch in dead or (isinstance(status, str) and status not in NM.LIVE_STATUSES)):
                continue
            import stand_gaps
            left = []
            for row in passes:
                # t-781 m3: the take-back is the DRIVER's act, in the driver's own words (the gate-A revoke precedent) - never the words
                # of the person's grant, which would read as the person taking their own pass back
                code, out = self.py("waiver.py", "--revoke", "--task", self.task, "--stage", row["stage"], "--block", row["block"],
                                    *stand_gaps.words_args(self.words_file, f"{dispatch} ended ({status or 'released'}): the driver takes "
                                                                            "the pass over the exit gate back", "revoke"), *self.waiver_road(False))
                if code:
                    print(f"{row['stage']}: the person's pass over the exit gate could not be taken back ({out[-160:]}); the next sweep tries again")
                    left.append(row)
            rec["passes"], changed = left, True
        if changed:
            self.save_state()

    def exit_limit(self, stage: str, role: str, dispatch: str, errors: list, *, sid: str, why: str, digest: str = "", error: str = "",
                   text: str = "") -> None:
        """The ONE seam for an exit-gate refusal that survives the resume limit. `errors`: the lines that reached it, already the
        caller's `refusal_lines` (normalised ONCE there, never again here; `None` / `[]` = no lines: the generic question, no record); `text`: the
        refusal's own words, whole, when it has them (they are the details file). `sid`: the
        role's session ('' = none). `why`: handoff | refusal | structured | session_gone. Returns ONLY after a paid round the
        person bought (the caller judges the role's new result); every other way out raises `Person` through `no_move`
        (`call=False`): the question is the site's own, closed and priced. POSITION INVARIANT: after the free resume, the
        mechanical third turn and the S1 person branches (callers), before any `finish` - a stage is never closed over this
        question. The sweep runs first; the person's words the role already answered are spent (F-d8)."""
        self.revoke_passes_of_dead()
        lines = [str(e) for e in (errors or []) if str(e).strip()]      # the caller's `refusal_lines`, normalised ONCE there (t-842 F3)
        key = finding_key(lines)
        rec = self.exit_record(dispatch)
        rec.update(lines=lines, key=key, stage=stage, role=role)
        self.state["pending_words"].pop(dispatch, None)
        self.save_state()
        bought = (rec.get("rounds") or {}).get(key) or {}
        if sid and key and why != "session_gone" and bought.get("granted", 0) > bought.get("spent", 0):
            return self.exit_round(stage, role, dispatch, lines, sid, rec, key, why)
        ask = self.exit_limit_facts(stage, role, dispatch, lines, sid=sid, why=why, digest=digest, error=error, text=text)
        rec["ask"] = ask
        self.save_state()
        self.no_move({"why": "threshold", "kind": "exit_limit", "call": False, "stage": stage, "dispatch": dispatch,
                      "lead": ask["lead"], "text": ask["details"], "lines": lines, "site_doors": tuple(t for t in ask["offer"] if t not in NM.TOKEN_MOVES),
                      "site_fallback": lambda said: self.exit_limit_person(ask, said)})

    def exit_round(self, stage: str, role: str, dispatch: str, lines: list, sid: str, rec: dict, key: str, why: str = "handoff") -> None:
        """The paid round the person bought (`round`, once per answer): spent BEFORE the call (the `note_resume` rule - a crash
        costs one round and never repeats one), in the role's own session, with the check's exact lines and the person's words
        WHOLE (FR-8) as its instruction. The result is the dispatch's saved result (`resume_with`)."""
        taken = rec["rounds"][key]
        taken["spent"] = taken.get("spent", 0) + 1
        self.save_state()
        try:
            words = (self.task_root / taken["words_file"]).read_bytes().decode("utf-8", "replace").strip() if taken.get("words_file") else ""
        except OSError:
            words = ""
        print(f"{stage}: {dispatch} gets one more turn in its own session on the person's answer (round {taken['spent']} of this set)")
        refusal = Refusal(self.exit_ask(role, dispatch, lines, why=why), dispatch=dispatch, findings=lines)
        self.resume_with(refusal, stage, dispatch, sid,
                         "A person has answered what to do about the refusal below. Their words, whole, are your instruction for "
                         "this turn:\n\n" + (words or "(they gave no words beyond the choice)") + "\n\n",
                         reason=f"paid round {taken['spent']} on the person's answer: " + resume_reason(lines), sentence="")

    def s1_open_work(self) -> list:
        """The sources of the S1 inventory with open points of the factory's own work (`source:not_inspected` ...), from the
        inventory's own readers (`completeness`, `gap_points`): `[{source_id, key, text, points}]`, [] when there is none. A reader
        that cannot read the inventory raises - the caller says the structured reader failed and falls to the count (FR-12)."""
        import source_inventory as SI
        inventory = SI.load_inventory(self.task_root / "work" / "source-inventory.json")
        opened = SI.completeness(inventory).get("open_points") or {}
        rows = []
        for item in inventory.get("sources") or []:
            sid = item.get("source_id")
            work = [p for p in SI.gap_points(item) if p["id"] in set(opened.get(sid) or []) and p["class"] == SI.POINT_WORK]
            if work:
                rows.append({"source_id": sid, "key": SI._key(item), "text": "; ".join(p["text"] for p in work),
                             "points": [p["id"] for p in work]})
        return rows

    def exit_missing(self, stage: str, role: str, lines: list) -> tuple:
        """(what is still missing, in words; the S1 rows or []). Structured readers first, the gate's text is never parsed: at S1
        with a readable inventory one line per source with open work, `{ticket key} — {point text}` (at most EXIT_SOURCES_SHOWN,
        then `(+k more)`); otherwise a count and the details file (the unreadable inventory is this branch too)."""
        rows = []
        if stage == "S1":
            try:
                rows = self.s1_open_work()
            except Exception:
                rows = []
        if rows:
            shown = [f"- {r['key']} — {r['text']}" for r in rows[:self.EXIT_SOURCES_SHOWN]]
            more = len(rows) - self.EXIT_SOURCES_SHOWN
            return "\n" + "\n".join(shown + ([f"(+{more} more)"] if more > 0 else [])), rows
        count = f" in {len(lines)} place(s)" if lines else ""
        return f"the {self.role_words(role)}'s handover is not complete{count}; the check's own words are in the file named below", rows

    def exit_next_gate(self, stage: str) -> str:
        """The gate that comes after `stage`, from stages.json `gate_before` (the first LATER stage that names one), in words."""
        try:
            stages = self.stages()
            later = sorted((s for s in stages if re.fullmatch(r"S\d+", s) and int(s[1:]) > int(stage[1:])), key=lambda s: int(s[1:]))
            gate = next((stages[s].get("gate_before") for s in later if stages[s].get("gate_before")), "")
        except Exception:
            gate = ""
        return {"A": "the plan gate (gate A)", "B": "the delivery gate (gate B)"}.get(str(gate), "the retro")

    def exit_fresh_blocked(self, stage: str, facts: dict) -> str:
        """Why `fresh` cannot be offered, in words ('' when it can): the stage is closed, the story is closed (S9 would reopen it),
        or the dispatch is not one `release` frees (`NM.LIVE_STATUSES`). An unreadable fact blocks it (FR-41)."""
        try:
            closed_stage = ((self.controller_state().get("stages") or {}).get(stage) or {}).get("status") in ("completed", "skipped")
        except Exception:
            closed_stage = True
        if closed_stage:
            return "this step is already closed"
        if facts.get("closed") is not False:
            return "the story is closed" if facts.get("closed") else "the factory could not read the state of the story"
        if facts.get("dispatch_status") not in NM.LIVE_STATUSES:
            return "its work can no longer be set aside"
        return ""

    def exit_limit_facts(self, stage: str, role: str, dispatch: str, lines: list, *, sid: str, why: str, digest: str, error: str,
                         text: str = "") -> dict:
        """The facts of the question, kept in the driver's state while it is open (the answer reads them): the lead in the story's
        words (A9: conditional - no session, structured, the paid count only when above 0), the options offered and what each says,
        the details file. Every option that is absent is SAID (FR-42)."""
        who = "the " + self.role_words(role)
        up = who[0].upper() + who[1:]
        spent = sum(r.get("spent", 0) for r in (self.exit_record(dispatch).get("rounds") or {}).values())
        try:
            form = self.form_errors(dispatch)
        except Exception:
            form = []
        facts = self.no_move_facts({"dispatch": dispatch, "kind": "exit_limit"})
        absent, fresh_why = {}, self.exit_fresh_blocked(stage, facts)
        if not sid:
            absent["round"] = f"{up}'s session cannot be resumed, so it cannot be given another turn."
        elif why == "session_gone":
            absent["round"] = f"{up}'s session no longer answers, so it cannot be given another turn."
        if fresh_why:
            absent["fresh"] = f"Starting it again is not possible here: {fresh_why}."
        if form:
            turns = " or ".join(w for w, token in (("give it another turn", "round"), ("start it again", "fresh")) if token not in absent)
            absent["go on"] = (f"{up}'s handover form is not complete in {len(form)} place(s); only {who} can fill it"
                               + (f" — {turns}." if turns else "."))
        missing, rows = self.exit_missing(stage, role, lines)
        place = self.stage_place(stage)
        again = "" if not spent else (", and once more after your answer" if spent == 1 else f", and again {spent} times after your answers")
        if not sid:
            sent = f"{up}'s session cannot be resumed, so it could not be sent back."
        elif why == "session_gone":
            sent = f"{up} was sent back over it, but its session no longer answers."
        elif why == "structured":
            sent = f"{up} was sent back once over its structured handover and came back with the same gaps{again}."
        else:
            sent = f"{up} was sent back once with exactly what the check named, and came back with the same gaps{again}."
        try:
            import role_digest
            halting = bool(digest) and role_digest.is_halting(digest)
        except Exception:
            halting = False
        lead = "\n".join([
            f"The story is at {place}. {up} finished its work there, and the factory's own check of that work refused to let the stage "
            f"go on. {sent}" + (f" {up} also says it cannot go on; its own words are in the file named below." if halting else ""),
            "", "What is still missing:" + (missing if missing.startswith("\n") else " " + missing), *(["", *[absent[t] for t in ("round", "fresh", "go on") if t in absent]] if absent else []), "",
            "The factory cannot finish this step by itself. Which of these should happen?"])
        keys = ", ".join(r["key"] for r in rows)
        consequence = (f"the {self.role_words('qa-scout')}'s reading notes on {keys} are not written; the next roles read those tickets as fetched; "
                       "the plan gate (gate A) lists them among what you decided" if rows and stage == "S1" else
                       f"what the check named stays undone and is kept with your words; {self.exit_next_gate(stage)} lists it among what you decided")
        shown = "the step closes as it is: " + consequence
        halt = self.halt_key(digest) if halting and sid and why != "session_gone" else ""
        says = {"round": (f"{who} gets one more turn in its own session, with the check's exact words and your answer as its instruction; "
                          "then the check looks again", {"role": who}),
                "fresh": (f"{who}'s session is set aside and the role starts this step again from its brief, with the check's words and your "
                          "answer; what it wrote stays on disk for it to read", {"stages": f"{who}'s whole work at {place}"}),
                "go on": (shown, {})}
        if halt:
            says["go on"] = (shown + f"; first {who} reads your words once in its own session and hands its work over again, because it "
                             "also said it cannot go on", {"role": who})
        offer = [t for t in ("round", "fresh", "go on") if t not in absent] + ["stop"]
        options = [dict(self.STOP_OPTION) if t == "stop" else {"answer": t, "token": t, "says": says[t][0], "slots": says[t][1]} for t in offer]
        details = (text.strip() or "The check's lines, whole:\n- " + "\n- ".join(lines)) + (f"\n\nThe resume's own error:\n{error}" if error else "")
        details += f"\n\nThe role's last words:\n{digest.strip()}" if digest.strip() else ""
        return {"stage": stage, "dispatch": dispatch, "lead": lead, "options": options, "offer": offer, "shown": shown,
                "details": details, "form": len(form), "halt": halt}

    @staticmethod
    def halt_key(digest: str) -> str:
        """The identity of the halt a person was shown: a hash of the digest's words (whitespace-normalised); "" for no digest."""
        norm = " ".join(str(digest or "").split())
        return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16] if norm else ""

    def exit_limit_person(self, ask: dict, said: str = "") -> Person:
        """The question from its facts: `said` (an unread answer's lead, else the account itself) above the account, then the priced
        answers of `exit.resume_limit`. ONE literal `closed_question` (the census of question ids reads it)."""
        lead = ask["lead"] if not said.strip() or said.strip() == ask["lead"].strip() else said.strip() + "\n\n" + ask["lead"]
        text = (self.closed_question("exit.resume_limit_halted", lead, ask["options"]) if ask.get("halt")
                else self.closed_question("exit.resume_limit", lead, ask["options"]))
        return Person("exit_limit", text, ask["stage"], ask["dispatch"], details=ask["details"])

    def _answer_exit_limit(self, words: str, qtext: str, stage: str, dispatch: str, *, words_file: str = "") -> bool:
        """The answer to the exit-limit question (FR-9: each token has an executor; FR-12: tokens only). `round` records the one
        round the answer buys (the paid call is spent inside `exit_limit`, on the next entry); `fresh` sets the work aside through
        the controller's `release` and the relaunch carries the check's lines; `go on` passes the lines that REACHED the seam
        (S1: the sources' open work first) and files the factory finding; `stop` holds the question. Any other word goes to the
        conductor once. `words_file`: the person's ORIGINAL words (the conductor road); else this answer's file. True = a token."""
        rec = (self.state.get("exit_limit") or {}).get(dispatch) or {}
        ask = rec.get("ask") or {}
        token = self.s0_normalize(words)
        if not ask or token not in ask.get("offer", ()):
            self.unread("exit_limit", stage, dispatch, qtext, words=words, doors=tuple(ask.get("offer") or ("stop",)),
                        lead=self.unread_lead(words), again=lambda said: self.exit_limit_person(ask, said) if ask else self.held_question(said))
            return False
        if (self.pipeline().get("stages") or {}).get(stage, {}).get("status") == "done":
            self.after_close(stage, words)      # edge 8: no executor runs on a dispatch no longer live
            return True
        file = words_file or self.answer_file()
        self.answer_row(f"{stage} exit gate ({token}): ", words.strip(), what="your answer at the exit gate")
        if token == "stop":
            raise self.held_question(self.stop_held("If you want the factory to go on after all, answer one of the other answers."))
        if token == "round":
            taken = rec.setdefault("rounds", {}).setdefault(rec["key"], {"granted": 0, "spent": 0})
            taken.update(granted=taken.get("granted", 0) + 1, words_file=file, at=_now())
        elif token == "fresh":
            self._exit_fresh(rec, stage, dispatch, file)
        else:
            self._exit_go_on(rec, stage, dispatch, file, words)
        self.save_state()
        print(f"{stage}: the person's answer `{token}` is recorded for {dispatch}")
        return True

    def _exit_fresh(self, rec: dict, stage: str, dispatch: str, file: str) -> None:
        """`fresh`: the dispatch is released by the controller's own operation (by code, no paid call) with the person's words, and
        the relaunch is told why: the check's lines and the files the first attempt left (`relaunch_reason`). A refusal of the release
        is held as it is (FR-1); the rows `go on` may have written for D are revoked by the one sweep."""
        code, out = waiver.run_release(self.task_root, dispatch, words_file=str(self.task_root / file), env=self.env)      # N4: the ONE release caller
        if code:
            raise self.held_question("Your choice could not be carried out: the factory could not set the work aside, so nothing was changed.", out)
        lines = list(rec.get("lines") or [])
        form = f"work/handoffs/{dispatch}.yaml"
        kept = list(dict.fromkeys(([form] if (self.task_root / form).is_file() else [])
                                  + [p for p in PATH_RE.findall("\n".join(lines)) if (self.task_root / p).is_file()]))
        rec["fresh_line"] = (f"A first attempt at this step ({dispatch}) was set aside by the person after the factory's own check refused it "
                             "twice. What the check named:\n- " + "\n- ".join(lines)
                             + ("\nEverything that attempt wrote stays on disk for you to read, among it: " + ", ".join(kept) if kept else
                                "\nEverything that attempt wrote stays on disk for you to read.")
                             + "\nStart this step again from your brief and repair what the check names.")
        self.revoke_passes_of_dead(dead=(dispatch,))

    def _exit_go_on(self, rec: dict, stage: str, dispatch: str, file: str, words: str) -> None:
        """`go on`: S1 first closes the sources' open work through the adapter's own door (`accept-gap --point`, the controller's S1
        check reads it), then ONE waiver row per line that reached the seam, the block = the whole line (never a keyword). The rows
        are kept for the sweep (`revoke_passes_of_dead`); the pass is filed as the factory's finding (FR-4, the `s0_file_pass`
        pattern). A command that fails is held with its output: nothing is passed in silence."""
        if stage == "S1":
            try:
                rows = self.s1_open_work()
            except Exception as exc:
                raise self.held_question("Your word could not be recorded: the sources of this step cannot be read, so nothing was passed.",
                                         f"{type(exc).__name__}: {exc}") from None
            for row in rows:
                code, out = self.py("ticket_adapter.py", "accept-gap", "--output", f"qa-factory/artifacts/{self.task}/work/source-inventory.json",
                                    "--source-id", row["source_id"], "--point", ",".join(row["points"]),
                                    "--shown-text", str((rec.get("ask") or {}).get("shown") or ""), "--words-file", str(self.task_root / file))
                if code:
                    raise self.held_question("Your word could not be recorded as the pass for the sources, so nothing was passed.", out)
        passes = rec.setdefault("passes", [])
        for line in rec.get("lines") or []:
            if any(p["block"] == line and p["stage"] == stage for p in passes):
                continue
            self.pass_block(stage, line, file, "Your word could not be recorded as the pass, so nothing was passed.")
            passes.append({"stage": stage, "block": line, "words_file": file})
        self.owe_row("project_decisions.py", "--root", str(self.project), "add-finding",
                     "--essence", f"exit gate refusal of {dispatch} passed by the person's word: {self.s0_quote(words)}; "
                                  "lines: " + "; ".join(rec.get("lines") or [])[:600],
                     "--scope", "local-calibration", "--witness", f"exit gate {dispatch}: " + str((rec.get("lines") or [""])[0])[:200],
                     "--idempotency-key", f"exit-pass:{self.task}:{dispatch}:{str(rec.get('key'))[:12]}",
                     what="the finding about the exit gate you passed", stage=stage)
        shown = (rec.get("ask") or {}).get("halt")
        if shown and shown == self.halt_key(self.digest_of(self.saved_result(dispatch).get("result") or "")):
            try:
                said = (self.task_root / file).read_text(encoding="utf-8").strip()
            except OSError:
                said = ""
            self.state["pending_words"][dispatch] = said or words
            print(f"{stage}: {dispatch} also said it cannot go on; it reads your words once in its own session, and the question it "
                  "stopped on is not asked again")

    def s6_walkers_cap(self) -> int:
        """`manual.walkers` through `config_contract.walkers` (the one reader, AR-13); a bad value reads the default with its note, said once."""
        import config_contract
        value, note = config_contract.walkers(self.config)
        if note:
            self.say_once("manual_walkers", note)
        return value

    def s7_place_lines(self, dispatch) -> list:
        """t-1991 U3a (the analyst settles the places): the brief lines of the places of S7 - each place with its sources, state and the
        expectation the record names, the four answers and the four sources, the capture case `settle-<place id>`, the commands. The ONE
        formatter is `place_answers._list_lines` (what `place_answers.py list` prints); more places than `brief_places_max` are cut with
        a pointer. A list that could not be computed whole says so in the brief and in ONE printed line, never "none" (AR-28). The
        brief only TELLS the analyst an answer is owed; whether a place is answered is the register's business at the close (P1)."""
        base = f"qa-factory/artifacts/{self.task}/"
        py = '`python "${CLAUDE_PLUGIN_ROOT}/scripts/'
        try:
            import place_answers
            data = place_answers._data()
            found = place_answers.places(self.task_root)
            states = {p["id"]: place_answers.settled_answer(self.task_root, p["id"]) for p in found["places"]}
            listed = place_answers._list_lines(found, states)
        except Exception as exc:
            print(f"S7: the places to settle could not be listed ({type(exc).__name__}: {exc})")
            return [f"The list of places to settle could not be computed whole ({type(exc).__name__}: {exc}): run {py}place_answers.py\" list "
                    f"--task-root {base}` and settle what it lists."] + self.s7_session_line(dispatch)
        if found["unreadable"]:
            print("S7: the places to settle could not be computed whole: " + "; ".join(f"{rec}: {why}" for rec, why in found["unreadable"]))
        count = len(found["places"])
        if not count and not found["unreadable"]:
            return listed + self.s7_session_line(dispatch)      # "Places to settle: none in this run"
        head, rows = listed[:len(listed) - count], listed[len(listed) - count:]
        cap = int(data["brief_places_max"])
        lines = head + rows[:cap] + ([f"[and {count - cap} more: place_answers.py list]"] if count > cap else [])
        disp = str(dispatch) if dispatch else "<your dispatch id>"
        lines += ["An answer is owed for every place that is not settled: `answer` is one of " + ", ".join(f"`{a}`" for a in data["answers"])
                  + "; name beside it where your expectation comes from, `expectation.source` one of "
                  + ", ".join(f"`{s}`" for s in data["sources"]) + ".",
                  "The answer file is one JSON object: `place`; `answer`; `expectation` {`source`, `id`, `quote`}; `seen` {`capture`: the path "
                  "the recorder wrote, `quote`: words that capture holds}; and by answer `question` (requirement_silent), `why` (not_a_bug, "
                  "impossible), `draft` (bug: the file name of your draft under work/bug-drafts/, whose `reproduction` holds "
                  "`{kind: walk, evidence: evidence/place-answer-<place id>.json, observed: what you saw}` and whose `confirmation` is "
                  "`unconfirmed`). `place_answers.py write --help` lists the rest.",
                  f"Capture each place under its own case `settle-<place id>`: {py}manual_capture.py\" ui|http --task-root {base} "
                  "--case settle-<place id>` (`ui` also needs `--steps-file`, `http` needs `--method` and `--url`; the capture is the evidence "
                  "your answer quotes).",
                  f"Commands: {py}place_answers.py\" list --task-root {base}` prints the places with their states; {py}place_answers.py\" write "
                  f"--task-root {base} --dispatch {disp} --place <place id> --file <your answer, a JSON file>` records one answer "
                  "(`--replace` replaces an answer you gave)."]
        return lines + self.s7_session_line(dispatch)

    def s7_neighbour_lines(self, dispatch) -> list:
        """t-2187 N6: the brief lines of the neighbourhood hint of an S7 triage dispatch - the groups of failures, observations, rows and
        drafts that share a requirement, case, test file, code line or seen value, cut to `brief_neighbours_max` groups (the data row of
        `references/place-answers.json`) with the command for the rest. `bug_neighbours` formats and counts; this only hands it over (FR-15).
        A table that could not be computed whole says so in the brief and in ONE printed line, never "none" (AR-28). A hint: the brief
        does not ask the analyst to merge anything (AR-29)."""
        command = f'`python "${{CLAUDE_PLUGIN_ROOT}}/scripts/bug_neighbours.py" --task-root qa-factory/artifacts/{self.task}/`'
        try:
            import bug_neighbours
            import place_answers
            found = bug_neighbours.neighbours(self.task_root)
            shown = bug_neighbours.lines(found, int(place_answers._data()["brief_neighbours_max"]))
        except Exception as exc:
            print(f"S7: the neighbourhood table could not be computed ({type(exc).__name__}: {exc})")
            return [f"The neighbourhood table could not be computed whole ({type(exc).__name__}: {exc}): run {command} for it."]
        if found["unreadable"]:
            print("S7: the neighbourhood table could not be computed whole: " + "; ".join(f"{item[0]}: {item[1]}" for item in found["unreadable"]))
        return shown + [f"Command: {command} prints the whole table."]

    # --- t-1991 U3b: the walk session of an S7 triage dispatch (lane `settle`); opened and closed by `run_role` / `resume_role` -------------

    S7_SETTLE_ITEMS = "free"       # the item word when the run has no place at all (control walks only); otherwise the place ids

    S7_SETTLE_ACTOR = "guest"       # the spec names no account for a place: no sign-in by code is needed to open (returned as a question)

    def s7_is_triage(self, stage: str, role: str, dispatch: str, purpose: str = "") -> bool:
        """True for an S7 `qa-failure-analyst` dispatch that is NOT an investigation (`controller.s7_part_of` of its record, else the
        `purpose` of a request not yet a record). INVARIANT: an investigation never gets the place lines or the session; a record that
        cannot be read answers False (the investigation's side), with one printed line."""
        if stage != "S7" or role != "qa-failure-analyst" or purpose == "investigation":
            return False
        try:
            import controller as CT
            records = (self.controller_state().get("dispatches") or {}).items()
            record = next((d for key, d in records if isinstance(d, dict) and str(d.get("id") or key) == str(dispatch)), {})
            return CT.s7_part_of(record) != "investigation"
        except Exception as exc:
            print(f"S7: the kind of dispatch {dispatch} could not be read ({type(exc).__name__}: {exc}); it gets no place lines and no walk session")
            return False

    def s7_session_line(self, dispatch) -> list:
        """The brief line about the walk session of `dispatch` from `state["s7_walk"][dispatch]`: the session and its reopen door, or
        'no walk session: <why>' with the road that needs none. `[]` when no record exists (nothing was opened or tried)."""
        record = (self.state.get("s7_walk") or {}).get(str(dispatch)) if dispatch else None
        if not isinstance(record, dict):
            return []
        base = f"qa-factory/artifacts/{self.task}/"
        py = '`python "${CLAUDE_PLUGIN_ROOT}/scripts/'
        door = (f"capture with {py}manual_capture.py\" ui|http --task-root {base} --case settle-<place id>`")
        if record.get("failed"):
            return [f"no walk session: {record.get('why') or record['failed']}; capture with `manual_capture.py ui|http --case settle-<place>`"
                    f" ({py}manual_capture.py\" ui|http --task-root {base} --case settle-<place id>`), or answer `impossible` with that why."]
        if record.get("state") != "ready":
            return []                   # closed with its dispatch: nothing to offer
        items = ",".join(record.get("items") or [self.S7_SETTLE_ITEMS])
        skipped = [str(i) for i in record.get("skipped") or []]
        out = [f"The walk session `{dispatch}` is open (its items are the place ids: `{items}`): {py}walk_session.py\" step|look|final "
               f"--task-root {base} --walk {dispatch} --item <place id> --line \"<one step>\"` (or `--steps-file <file>`), one step or a short "
               f"obvious run per call; its captures are under settle-<place id>, where your answer's `seen.capture` points. If a call says "
               f"it ended: {py}walk_session.py\" open --task-root {base} --walk {dispatch} --place settle --items {items} "
               f"--actor {self.S7_SETTLE_ACTOR} --parent-pid {os.getpid()}` reopens it for the same walk; if it cannot open, {door}, or "
               "answer `impossible` with why 'the walk session could not be opened'."]
        if skipped:
            out.append("Places the session cannot carry (their id is no plain id): " + ", ".join(f"`{i}`" for i in skipped)
                       + f"; capture each with {py}manual_capture.py\" ui|http --task-root {base} --case settle-<place id>`.")
        return out

    def s7_settle_session(self, dispatch: str, resume: bool = False) -> bool:
        """Opens the settle walk session of an S7 triage dispatch (`walk_session.py open --place settle --walk <dispatch> --items <the place ids>`; `free` only when the run has no place)
        and records `state["s7_walk"][dispatch]` = `{"state": "ready"}` or `{"failed": "stand"|"session", "why"}` (`s7_gap_reason` reads
        it). Returns True when a session is ready and this call's caller must close it. NEVER raises (P1): a session that cannot open is
        a record and a printed line, and the role runs on the `manual_capture` road. `resume`: a server that is `ready` and alive is left
        alone (E3b.5); any other is reopened for the same walk. `stand` when `open`'s answer carries `cause: stand_busy` (the exit and the
        answer, never a word in the text; t-2027 F11), else `session`. Places whose id the lane cannot carry are left out of the session and
        named in the brief line (t-2027 F9)."""
        walks = self.state.setdefault("s7_walk", {})
        why, cause, skipped = "", "", []
        if resume and isinstance(walks.get(dispatch), dict):
            skipped = [str(i) for i in walks[dispatch].get("skipped") or []]
        try:
            if resume:
                record = _read_json(self.task_root / "state" / "walks" / f"{dispatch}.json")
                import walk_session as WS
                if isinstance(record, dict) and record.get("state") == "ready" and WS.alive(record):
                    walks[dispatch] = {"state": "ready", "items": [str(i) for i in record.get("items") or []]}
                    return True
                items = [str(i) for i in (record or {}).get("items") or []] if isinstance(record, dict) else []
            if not resume or not items:
                import place_answers
                found = place_answers.places(self.task_root)
                if found["unreadable"]:         # AR-28: a list not read whole opens no session (the place ids are the items)
                    why = "ValueError: the places to settle could not be listed whole: " + "; ".join(f"{r}: {w}" for r, w in found["unreadable"])
                else:
                    import walk_session as WS
                    ids = [p["id"] for p in found["places"]]
                    items = [i for i in ids if WS.lane_item_ok(i)] or [self.S7_SETTLE_ITEMS]
                    skipped = [i for i in ids if not WS.lane_item_ok(i)]
            if not why:
                code, text = self.py("walk_session.py", "open", "--task-root", str(self.task_root), "--walk", dispatch, "--place", "settle",
                                     "--items", ",".join(items), "--actor", self.S7_SETTLE_ACTOR)
                if code:
                    got = _read_answer(text) or {}
                    cause = str(got.get("cause") or "")
                    why = str(got.get("reason") or "").strip()[:300] or (text.splitlines() or [f"exit {code}"])[-1][:300]
        except Exception as exc:        # P1: code informs, it never stops the factory
            why = f"{type(exc).__name__}: {' '.join(str(exc).split())[:200]}"
        if why:
            walks[dispatch] = {"failed": "stand" if cause == "stand_busy" else "session", "why": why, **({"skipped": skipped} if skipped else {})}
            print(f"S7: {dispatch}: no walk session ({why}); the analyst captures with manual_capture.py or answers `impossible`")
        else:
            walks[dispatch] = {"state": "ready", "items": items, **({"skipped": skipped} if skipped else {})}
        try:
            self.save_state()
        except Exception as exc:
            print(f"note: the walk record of {dispatch} was not saved ({type(exc).__name__})")
        return not why

    def s7_settle_close(self, dispatch: str) -> None:
        """Closes the settle session of `dispatch` (`walk_session.py close`). Never raises: a server that did not close ends by itself
        (parent check, `max_s`); the failure is one printed line."""
        try:
            # remains: the exit is read on the next line and said; a server that did not close ends by itself (parent check, max_s)
            code, text = self.py("walk_session.py", "close", "--task-root", str(self.task_root), "--walk", dispatch)
            if code:
                print(f"note: walk_session.py close exit {code}: {(text.splitlines() or [''])[-1][:200]}; the server ends by itself")
        except Exception as exc:
            print(f"note: walk_session.py close raised {type(exc).__name__}; the server ends by itself")
        record =(self.state.get("s7_walk") or {}).get(dispatch)
        if isinstance(record, dict) and record.get("state") == "ready":
            record["state"] = "closed"

    # --- the gate-entry repair (t-211, F-cmp2-17) ------------------------------------------------

    # TP1-15045 (cmp2): S4 closed, the person was asked at gate A, and only then did the factory find
    # four times over what it had known since the S4 exit (8 design-review findings, 6 unpinned cases,
    # 1 question branch) - the rehearsal sat INSIDE the packet as advice. `stage_done` refuses to close the
    # stage over them, but story_step has accepted the stage in the controller before it calls stage_done, so
    # that refusal never stopped anything. This step is the gate on SHOWING the gate: the rehearsal runs
    # first, what a code move can repair is repaired by code, and the person is addressed once.
    #
    # `gate_preflight.run` is reused here in a more consequential role than it was written for: from text
    # in the packet (advice) to the trigger of paid dispatches and the condition of showing the gate. The
    # error direction that is allowed is toward SHOWING the gate (today's behaviour); never toward unbounded
    # spend (a round cap, a key set that may not repeat, a stop that outlives the process) and never toward a
    # gate withheld with no door (the conductor, then the person's word).
    def stage_completed(self, stage: str) -> bool:
        """Has the CONTROLLER accepted this stage (`completed`)? pipeline.json can say `done` over a stage
        the controller still holds open, and the other way round; this reads the controller's own record."""
        try:
            return (((self.controller_state().get("stages") or {}).get(stage) or {}).get("status")) == "completed"
        except Exception:
            return False

    def relaunch_reason(self, request: dict, action: dict) -> str:
        """What a relaunched role is told about WHY it starts again. A dispatch the person set aside over the exit gate's refusal
        (`fresh`, t-764 A8) says so - the check's lines, the files that stay readable, the person's own words (read once, from the
        controller's record of the release) - and OUTRANKS the packet's `reason` (`reason` is a binding key the controller copies
        into the packet, so it would win otherwise); the packet's own reason follows. Any other relaunch: the packet's reason, else
        the old line."""
        closed = str(request.get("relaunch_of") or action.get("closed_dispatch_id") or "")
        original = str(request.get("reason") or "").strip()
        line = str(((self.state.get("exit_limit") or {}).get(closed) or {}).get("fresh_line") or "")
        released = str(((self.controller_state().get("dispatches") or {}).get(closed) or {}).get("released_by_person") or "").strip()
        if line or released:
            # a release by a person's word of ANY road (the conductor's `restart` too) carries those words: "never reached an agent"
            # is false for a released dispatch
            return ((line or f"The previous attempt at this step ({closed}) was set aside by the person before it was accepted.")
                    + (f"\n\nThe person's words, whole:\n{released}" if released else "")
                    + (f"\n\nThe reason this dispatch carried before:\n{original}" if original else ""))
        return original or f"{closed} never reached an agent; this repeats it"
